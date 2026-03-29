"""Battle Manager round-trip suite -- parse, modify field, re-parse."""
import io
import os
import sys
import tempfile

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert, _fixture


def run_suite():
    _begin_suite("Battle Manager round-trip  (parse → modify → re-parse)")

    try:
        from torch.battle_io import _read_party_file, _parse_party_section, _serialize_party_trainer
    except ImportError as e:
        _skip("all battle round-trip tests", f"import failed: {e}")
        return

    party_path = _fixture("test_trainers.party")

    # 1. Read and parse both trainers
    try:
        sections = _read_party_file(party_path)
        _assert(
            "test_trainers.party: reads 2 sections",
            len(sections) == 2,
            f"expected 2, got {len(sections)}: {list(sections.keys())}"
        )
    except Exception as e:
        _fail("_read_party_file raised", str(e))
        return

    try:
        record = _parse_party_section(
            sections.get("TRAINER_TEST_GRUNT", ""),
            "TRAINER_TEST_GRUNT"
        )
        _assert(
            "TRAINER_TEST_GRUNT: name parsed correctly",
            record.get("trainer_name") == "Grunt",
            f"got: {record.get('trainer_name')!r}"
        )
        _assert(
            "TRAINER_TEST_GRUNT: party has 1 Pokemon",
            len(record.get("mons", [])) == 1,
            f"got {len(record.get('mons', []))} mons"
        )
    except Exception as e:
        _fail("_parse_party_section raised", str(e))
        return

    # 2. Modify name and re-serialize, then re-parse — value must survive the round-trip
    try:
        record["trainer_name"] = "Grunty"
        serialized = _serialize_party_trainer(record)
        _assert(
            "serialize: output contains modified name 'Grunty'",
            "Grunty" in serialized,
            "modified name not found in serialized output"
        )

        # Re-parse the serialized block (write to a temp file to reuse _read_party_file)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".party",
                                         delete=False) as tmp:
            tmp.write(serialized + "\n")
            tmp_path = tmp.name

        re_sections = _read_party_file(tmp_path)
        re_record = _parse_party_section(
            re_sections.get("TRAINER_TEST_GRUNT", ""),
            "TRAINER_TEST_GRUNT"
        )
        _assert(
            "round-trip: modified name survives re-parse",
            re_record.get("trainer_name") == "Grunty",
            f"got: {re_record.get('trainer_name')!r}"
        )
    except Exception as e:
        _fail("battle round-trip raised", str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    # --- Extended field tests (Stream 65) ---

    ext_path = _fixture("test_trainers_extended.party")

    # 3. Known new fields parse correctly (Back Pic, Starting Status, Tera Type, etc.)
    try:
        ext_sections = _read_party_file(ext_path)
        partner = _parse_party_section(
            ext_sections.get("TRAINER_TEST_PARTNER", ""),
            "TRAINER_TEST_PARTNER"
        )
        _assert(
            "Back Pic parsed correctly",
            partner.get("back_pic") == "Steven",
            f"got: {partner.get('back_pic')!r}"
        )
        _assert(
            "Starting Status parsed correctly",
            partner.get("starting_status") == "STATUS1_TOXIC_POISON",
            f"got: {partner.get('starting_status')!r}"
        )
        mon0 = partner.get("mons", [{}])[0]
        _assert(
            "Tera Type parsed correctly",
            mon0.get("tera_type") == "Steel",
            f"got: {mon0.get('tera_type')!r}"
        )
        _assert(
            "Dynamax Level parsed correctly",
            mon0.get("dynamax_level") == 8,
            f"got: {mon0.get('dynamax_level')!r}"
        )
        _assert(
            "Gigantamax parsed correctly (No -> False)",
            mon0.get("gigantamax") is False,
            f"got: {mon0.get('gigantamax')!r}"
        )
    except Exception as e:
        _fail("extended field parsing raised", str(e))

    # 4. Unknown fields are preserved through parse -> serialize -> re-parse
    try:
        future = _parse_party_section(
            ext_sections.get("TRAINER_TEST_FUTURE", ""),
            "TRAINER_TEST_FUTURE"
        )
        _assert(
            "unknown header fields preserved",
            ("Zodiac Sign", "Aquarius") in future.get("header_extra", [])
            and ("Lucky Number", "7") in future.get("header_extra", []),
            f"got header_extra: {future.get('header_extra')!r}"
        )
        fmon = future.get("mons", [{}])[0]
        _assert(
            "unknown mon fields preserved",
            ("Aura Color", "Yellow") in fmon.get("extra_fields", [])
            and ("Power Level", "9001") in fmon.get("extra_fields", []),
            f"got extra_fields: {fmon.get('extra_fields')!r}"
        )

        # Serialize and re-parse — unknown fields must survive
        serialized_future = _serialize_party_trainer(future)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".party",
                                         delete=False) as tmp2:
            tmp2.write(serialized_future + "\n")
            tmp2_path = tmp2.name
        re_ext = _read_party_file(tmp2_path)
        re_future = _parse_party_section(
            re_ext.get("TRAINER_TEST_FUTURE", ""),
            "TRAINER_TEST_FUTURE"
        )
        _assert(
            "unknown header fields survive round-trip",
            ("Zodiac Sign", "Aquarius") in re_future.get("header_extra", []),
            f"got: {re_future.get('header_extra')!r}"
        )
        re_fmon = re_future.get("mons", [{}])[0]
        _assert(
            "unknown mon fields survive round-trip",
            ("Aura Color", "Yellow") in re_fmon.get("extra_fields", []),
            f"got: {re_fmon.get('extra_fields')!r}"
        )
        os.unlink(tmp2_path)
    except Exception as e:
        _fail("unknown field round-trip raised", str(e))

    # 5. Empty/missing new fields don't produce spurious output
    try:
        grunt = _parse_party_section(
            sections.get("TRAINER_TEST_GRUNT", ""),
            "TRAINER_TEST_GRUNT"
        )
        serialized_grunt = _serialize_party_trainer(grunt)
        _assert(
            "no spurious Back Pic in output",
            "Back Pic:" not in serialized_grunt,
            "Back Pic appeared when not in original"
        )
        _assert(
            "no spurious Tera Type in output",
            "Tera Type:" not in serialized_grunt,
            "Tera Type appeared when not in original"
        )
        _assert(
            "no spurious Starting Status in output",
            "Starting Status:" not in serialized_grunt,
            "Starting Status appeared when not in original"
        )
        _assert(
            "no spurious Dynamax Level in output",
            "Dynamax Level:" not in serialized_grunt,
            "Dynamax Level appeared when not in original"
        )
        _assert(
            "no spurious Gigantamax in output",
            "Gigantamax:" not in serialized_grunt,
            "Gigantamax appeared when not in original"
        )
    except Exception as e:
        _fail("spurious output check raised", str(e))

    # --- Version warning tests (Stream 139) ---

    # 6. back_pic with old expansion version prints warning
    try:
        rec_bp = {
            "trainer_const": "TRAINER_TEST_WARN",
            "trainer_name": "Warn",
            "back_pic": "Steven",
            "mons": [],
        }
        old_stdout = sys.stdout
        sys.stdout = capture = io.StringIO()
        try:
            _serialize_party_trainer(rec_bp, expansion_version=(1, 12, 0))
        finally:
            sys.stdout = old_stdout
        output = capture.getvalue()
        _assert(
            "back_pic: warns on old expansion",
            "Warning" in output and "Back Pic" in output,
            f"got stdout: {output!r}"
        )
    except Exception as e:
        _fail("back_pic version warning raised", str(e))

    # 7. starting_status with old expansion version prints warning
    try:
        rec_ss = {
            "trainer_const": "TRAINER_TEST_WARN2",
            "trainer_name": "Warn2",
            "starting_status": "STATUS1_TOXIC_POISON",
            "mons": [],
        }
        old_stdout = sys.stdout
        sys.stdout = capture = io.StringIO()
        try:
            _serialize_party_trainer(rec_ss, expansion_version=(1, 14, 3))
        finally:
            sys.stdout = old_stdout
        output = capture.getvalue()
        _assert(
            "starting_status: warns on old expansion",
            "Warning" in output and "Starting Status" in output,
            f"got stdout: {output!r}"
        )
    except Exception as e:
        _fail("starting_status version warning raised", str(e))

    # 8. No warnings when expansion_version is None
    try:
        rec_none = {
            "trainer_const": "TRAINER_TEST_WARN3",
            "trainer_name": "Warn3",
            "back_pic": "Steven",
            "starting_status": "STATUS1_TOXIC_POISON",
            "mons": [],
        }
        old_stdout = sys.stdout
        sys.stdout = capture = io.StringIO()
        try:
            _serialize_party_trainer(rec_none, expansion_version=None)
        finally:
            sys.stdout = old_stdout
        output = capture.getvalue()
        _assert(
            "no warnings when expansion_version is None",
            "Warning" not in output,
            f"got stdout: {output!r}"
        )
    except Exception as e:
        _fail("no-warning-when-None raised", str(e))

    # 9. No warnings when version meets requirements
    try:
        rec_ok = {
            "trainer_const": "TRAINER_TEST_WARN4",
            "trainer_name": "Warn4",
            "back_pic": "Steven",
            "starting_status": "STATUS1_TOXIC_POISON",
            "mons": [],
        }
        old_stdout = sys.stdout
        sys.stdout = capture = io.StringIO()
        try:
            _serialize_party_trainer(rec_ok, expansion_version=(1, 15, 0))
        finally:
            sys.stdout = old_stdout
        output = capture.getvalue()
        _assert(
            "no warnings when version meets requirements",
            "Warning" not in output,
            f"got stdout: {output!r}"
        )
    except Exception as e:
        _fail("no-warning-when-meets-version raised", str(e))
