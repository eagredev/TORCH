"""Battle Partners suite -- partner I/O, follower/multi beat round-trips, compiler output."""
import os
import re
import tempfile

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Battle Partners  (I/O + follower/multi beats)")

    try:
        from torch.battle_partners import (
            _read_partner_constants, _read_partner_count,
            _insert_partner_constant, _remove_partner_constant,
            _is_custom_partner,
        )
    except ImportError as e:
        _skip("all battle partner tests", f"import failed: {e}")
        return

    # ================================================================
    # Partner I/O tests
    # ================================================================

    # Create a temp game directory with battle_partner.h
    tmpdir = tempfile.mkdtemp(prefix="torch_partner_test_")
    constants_dir = os.path.join(tmpdir, "include", "constants")
    data_dir = os.path.join(tmpdir, "src", "data")
    os.makedirs(constants_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)

    header_path = os.path.join(constants_dir, "battle_partner.h")
    party_path = os.path.join(data_dir, "battle_partners.party")

    # Write a test battle_partner.h
    with open(header_path, "w") as f:
        f.write(
            "#ifndef GUARD_CONSTANTS_BATTLE_PARTNERS_H\n"
            "#define GUARD_CONSTANTS_BATTLE_PARTNERS_H\n"
            "\n"
            "#define PARTNER_NONE 0\n"
            "#define PARTNER_STEVEN 1\n"
            "#define PARTNER_COUNT 2\n"
            "\n"
            "#endif\n"
        )

    # Write a test battle_partners.party
    with open(party_path, "w") as f:
        f.write(
            "=== PARTNER_NONE ===\n"
            "Name:\n"
            "Class: Pkmn Trainer 1\n"
            "Pic: Brendan\n"
            "Gender: Male\n"
            "Music: Male\n"
            "\n"
            "=== PARTNER_STEVEN ===\n"
            "Name: STEVEN\n"
            "Class: Rival\n"
            "Pic: Steven\n"
            "Gender: Male\n"
            "Music: Male\n"
            "AI: Basic Trainer\n"
            "\n"
            "Metang\n"
            "Level: 42\n"
            "- Light Screen\n"
            "- Psychic\n"
            "- Reflect\n"
            "- Metal Claw\n"
        )

    try:
        # Test 1: Read partner constants
        constants = _read_partner_constants(tmpdir)
        _assert(
            "read constants: finds 2 partners",
            len(constants) == 2,
            f"expected 2, got {len(constants)}: {constants}"
        )
        _assert(
            "read constants: PARTNER_NONE is first",
            constants[0][0] == "PARTNER_NONE" and constants[0][1] == 0,
            f"got: {constants[0]}"
        )

        # Test 2: Read partner count
        count = _read_partner_count(tmpdir)
        _assert(
            "read count: PARTNER_COUNT is 2",
            count == 2,
            f"expected 2, got {count}"
        )

        # Test 3: Custom partner detection
        _assert(
            "is_custom: PARTNER_NONE is not custom",
            not _is_custom_partner("PARTNER_NONE"),
            ""
        )
        _assert(
            "is_custom: PARTNER_STEVEN is not custom",
            not _is_custom_partner("PARTNER_STEVEN"),
            ""
        )
        _assert(
            "is_custom: PARTNER_SABRINA is custom",
            _is_custom_partner("PARTNER_SABRINA"),
            ""
        )

        # Test 4: Insert partner constant
        new_id = _insert_partner_constant(tmpdir, "PARTNER_SABRINA")
        _assert(
            "insert constant: returns ID 2",
            new_id == 2,
            f"expected 2, got {new_id}"
        )

        # Verify the file was updated
        new_count = _read_partner_count(tmpdir)
        _assert(
            "insert constant: PARTNER_COUNT bumped to 3",
            new_count == 3,
            f"expected 3, got {new_count}"
        )

        new_constants = _read_partner_constants(tmpdir)
        _assert(
            "insert constant: now has 3 partners",
            len(new_constants) == 3,
            f"expected 3, got {len(new_constants)}"
        )
        sabrina_found = any(n == "PARTNER_SABRINA" for n, _ in new_constants)
        _assert(
            "insert constant: PARTNER_SABRINA in list",
            sabrina_found,
            f"constants: {new_constants}"
        )

        # Test 5: Remove partner constant
        success = _remove_partner_constant(tmpdir, "PARTNER_SABRINA")
        _assert(
            "remove constant: returns True",
            success is True,
            f"returned {success}"
        )
        after_count = _read_partner_count(tmpdir)
        _assert(
            "remove constant: PARTNER_COUNT back to 2",
            after_count == 2,
            f"expected 2, got {after_count}"
        )

        # Test 6: Read partner records from .party file
        from torch.battle_partners import _read_all_partners
        records = _read_all_partners(tmpdir)
        _assert(
            "read all partners: returns 2 records",
            len(records) == 2,
            f"expected 2, got {len(records)}"
        )
        steven = next((r for r in records if r.get("trainer_const") == "PARTNER_STEVEN"), None)
        _assert(
            "read partners: Steven has name STEVEN",
            steven is not None and steven.get("trainer_name") == "STEVEN",
            f"got: {steven.get('trainer_name') if steven else 'None'}"
        )
        _assert(
            "read partners: Steven has 1 Pokemon",
            steven is not None and len(steven.get("mons", [])) == 1,
            f"got {len(steven.get('mons', [])) if steven else 0} mons"
        )

    except Exception as e:
        _fail("partner I/O test raised", str(e))
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ================================================================
    # Follower beat round-trip tests
    # ================================================================

    try:
        from torch.script_model import (
            _parse_script, _serialize_script,
            _PARSE_CMD_DISPATCH, _SERIALIZE_DISPATCH, _SUMMARY_DISPATCH,
            BEAT_TAGS,
        )

        # Verify registration
        _assert(
            "follower: registered in BEAT_TAGS",
            "follower" in BEAT_TAGS and BEAT_TAGS["follower"] == "FOL",
            f"BEAT_TAGS has: {BEAT_TAGS.get('follower')}"
        )
        _assert(
            "follower: registered in parse dispatch",
            "follower" in _PARSE_CMD_DISPATCH,
            "missing from _PARSE_CMD_DISPATCH"
        )
        _assert(
            "follower: registered in serialize dispatch",
            "follower" in _SERIALIZE_DISPATCH,
            "missing from _SERIALIZE_DISPATCH"
        )
        _assert(
            "follower: registered in summary dispatch",
            "follower" in _SUMMARY_DISPATCH,
            "missing from _SUMMARY_DISPATCH"
        )

        # Parse/serialize round-trip for various follower lines
        follower_lines = [
            "follower add local LOCALID_SABRINA PARTNER_SABRINA FNPC_ALL",
            "follower remove",
            "follower check",
            "follower change PARTNER_STEVEN",
            "follower face",
            "follower hide",
        ]

        for line in follower_lines:
            tokens = line.split()
            parser = _PARSE_CMD_DISPATCH["follower"]
            beat, new_i = parser(tokens, line, [line], 0, {})
            _assert(
                f"follower parse: '{line[:40]}' -> type=follower",
                beat["type"] == "follower",
                f"got type={beat['type']}"
            )

            # Serialize back
            out_lines = []
            serializer = _SERIALIZE_DISPATCH["follower"]
            serializer(beat["data"], out_lines)
            _assert(
                f"follower round-trip: '{line[:40]}' survives",
                len(out_lines) == 1 and out_lines[0] == line,
                f"got: {out_lines}"
            )

    except Exception as e:
        _fail("follower beat round-trip raised", str(e))

    # ================================================================
    # Multi beat round-trip tests
    # ================================================================

    try:
        _assert(
            "multi: registered in BEAT_TAGS",
            "multi" in BEAT_TAGS and BEAT_TAGS["multi"] == "MLT",
            f"BEAT_TAGS has: {BEAT_TAGS.get('multi')}"
        )

        multi_lines = [
            "multi 2v2 TRAINER_MAXIE Text_MaxieDefeat TRAINER_TABITHA Text_TabithaDefeat PARTNER_STEVEN",
            "multi 2v1 TRAINER_MAXIE Text_MaxieDefeat PARTNER_STEVEN",
            "multi 2v2_fixed TRAINER_A TextA TRAINER_B TextB PARTNER_X",
            "multi 2v1_fixed TRAINER_A TextA PARTNER_X",
        ]

        for line in multi_lines:
            tokens = line.split()
            parser = _PARSE_CMD_DISPATCH["multi"]
            beat, new_i = parser(tokens, line, [line], 0, {})
            _assert(
                f"multi parse: variant={tokens[1]}",
                beat["type"] == "multi" and beat["data"]["variant"] == tokens[1],
                f"got type={beat['type']}, variant={beat['data'].get('variant')}"
            )

            # Serialize back
            out_lines = []
            serializer = _SERIALIZE_DISPATCH["multi"]
            serializer(beat["data"], out_lines)
            _assert(
                f"multi round-trip: variant={tokens[1]}",
                len(out_lines) == 1 and out_lines[0] == line,
                f"got: {out_lines}"
            )

    except Exception as e:
        _fail("multi beat round-trip raised", str(e))

    # ================================================================
    # Compiler output tests
    # ================================================================

    try:
        from torch.compiler import compile_script

        # Create a temp .txt with follower and multi beats
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as tmp:
            tmp.write("label TestScene\n")
            tmp.write("follower add local LOCALID_SABRINA PARTNER_SABRINA FNPC_ALL\n")
            tmp.write("follower remove\n")
            tmp.write("follower check\n")
            tmp.write("follower change PARTNER_STEVEN\n")
            tmp.write("multi 2v2 TRAINER_MAXIE Text_MaxieDefeat TRAINER_TABITHA Text_TabithaDefeat PARTNER_STEVEN\n")
            tmp.write("multi 2v1 TRAINER_A Text_ADefeat PARTNER_STEVEN\n")
            tmp_path = tmp.name

        output, errors = compile_script(tmp_path, "TestScene", "")

        _assert(
            "compiler: follower/multi script compiles without errors",
            len(errors) == 0,
            f"errors: {errors}"
        )
        _assert(
            "compiler: output contains setfollowernpc",
            "setfollowernpc(LOCALID_SABRINA, FNPC_ALL, 0, PARTNER_SABRINA)" in output,
            "setfollowernpc not found"
        )
        _assert(
            "compiler: output contains destroyfollowernpc",
            "destroyfollowernpc" in output,
            "destroyfollowernpc not found"
        )
        _assert(
            "compiler: output contains checkfollowernpc",
            "checkfollowernpc" in output,
            "checkfollowernpc not found"
        )
        _assert(
            "compiler: output contains changefollowerbattler",
            "changefollowerbattler(PARTNER_STEVEN)" in output,
            "changefollowerbattler not found"
        )
        _assert(
            "compiler: output contains multi_2_vs_2",
            "multi_2_vs_2(TRAINER_MAXIE, Text_MaxieDefeat, TRAINER_TABITHA, Text_TabithaDefeat, PARTNER_STEVEN)" in output,
            "multi_2_vs_2 not found"
        )
        _assert(
            "compiler: output contains multi_2_vs_1",
            "multi_2_vs_1(TRAINER_A, Text_ADefeat, PARTNER_STEVEN)" in output,
            "multi_2_vs_1 not found"
        )

    except Exception as e:
        _fail("compiler output test raised", str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
