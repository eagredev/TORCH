"""Battle Card suite — trainer card helpers, reference scanner, ID operations."""
import os
import re
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _assert


def run_suite():
    _begin_suite("Battle Card  (species abilities, IDs, references, reports)")

    try:
        from torch.battle_card import (
            _parse_species_abilities,
            _find_lowest_available_id,
            _recalculate_trainers_count,
            _scan_all_references,
            _write_deletion_report,
        )
    except ImportError as e:
        _fail("import battle_card", str(e))
        return

    # ------------------------------------------------------------------
    # _parse_species_abilities
    # ------------------------------------------------------------------

    # Build a minimal species_info file tree
    tmp = tempfile.mkdtemp(prefix="torch_bc_")
    try:
        poke_dir = os.path.join(tmp, "src", "data", "pokemon")
        os.makedirs(poke_dir)
        species_file = os.path.join(poke_dir, "species_info.h")
        with open(species_file, "w") as f:
            # Real species_info files have indented blocks; the regex
            # matches from [SPECIES_X] to the first \n} (brace at col 0).
            # Mimic that by ending the file with a }; on its own line.
            f.write("""\
    [SPECIES_PIKACHU] =
    {
        .baseHP = 35,
        .abilities = { ABILITY_STATIC, ABILITY_NONE, ABILITY_LIGHTNING_ROD },
    },

    [SPECIES_BULBASAUR] =
    {
        .baseHP = 45,
        .abilities = { ABILITY_OVERGROW, ABILITY_NONE, ABILITY_CHLOROPHYLL },
    },
};
""")

        # Test 1: basic ability extraction
        result = _parse_species_abilities("SPECIES_PIKACHU", tmp)
        _assert(
            "parse_species_abilities: Pikachu abilities found",
            "ABILITY_STATIC" in result and "ABILITY_LIGHTNING_ROD" in result,
            f"got {result}"
        )
        _assert(
            "parse_species_abilities: ABILITY_NONE filtered out",
            "ABILITY_NONE" not in result,
            f"got {result}"
        )

        # Test 2: auto-prefixes bare species name
        result2 = _parse_species_abilities("BULBASAUR", tmp)
        _assert(
            "parse_species_abilities: bare name auto-prefixed",
            "ABILITY_OVERGROW" in result2,
            f"got {result2}"
        )

        # Test 3: missing species returns empty list
        result3 = _parse_species_abilities("SPECIES_CHARIZARD", tmp)
        _assert(
            "parse_species_abilities: missing species returns []",
            result3 == [],
            f"got {result3}"
        )

        # Test 4: invalid game_path returns empty list
        result4 = _parse_species_abilities("SPECIES_PIKACHU", "/nonexistent/path")
        _assert(
            "parse_species_abilities: bad game path returns []",
            result4 == [],
            f"got {result4}"
        )

        # Test 5: empty game_path returns empty list
        result5 = _parse_species_abilities("SPECIES_PIKACHU", "")
        _assert(
            "parse_species_abilities: empty game path returns []",
            result5 == [],
            f"got {result5}"
        )

    finally:
        shutil.rmtree(tmp)

    # ------------------------------------------------------------------
    # _find_lowest_available_id
    # ------------------------------------------------------------------

    tmp2 = tempfile.mkdtemp(prefix="torch_bc_")
    try:
        opp_path = os.path.join(tmp2, "opponents.h")

        # Test 6: contiguous custom IDs — finds lowest free from 1
        with open(opp_path, "w") as f:
            f.write("#define TRAINER_NONE 0\n")
            f.write("#define TRAINER_GRUNT_1 855\n")
            f.write("#define TRAINER_GRUNT_2 856\n")
            f.write("#define TRAINER_GRUNT_3 857\n")
            f.write("#define TRAINERS_COUNT 858\n")
        result = _find_lowest_available_id(opp_path)
        _assert(
            "find_lowest_id: no vanilla returns 1",
            result == 1,
            f"expected 1, got {result}"
        )

        # Test 7: with vanilla IDs filling 1-854 — returns 855+
        with open(opp_path, "w") as f:
            f.write("#define TRAINER_NONE 0\n")
            for i in range(1, 855):
                f.write(f"#define TRAINER_V{i} {i}\n")
            f.write("#define TRAINER_GRUNT_1 855\n")
            f.write("#define TRAINER_GRUNT_3 857\n")
            f.write("#define TRAINERS_COUNT 858\n")
        result = _find_lowest_available_id(opp_path)
        _assert(
            "find_lowest_id: vanilla present, gap returns 856",
            result == 856,
            f"expected 856, got {result}"
        )

        # Test 8: empty file — returns 1
        with open(opp_path, "w") as f:
            f.write("// empty opponents\n")
        result = _find_lowest_available_id(opp_path)
        _assert(
            "find_lowest_id: empty file returns 1",
            result == 1,
            f"expected 1, got {result}"
        )

        # Test 9: nonexistent file — returns 1
        result = _find_lowest_available_id(os.path.join(tmp2, "nope.h"))
        _assert(
            "find_lowest_id: missing file returns 1",
            result == 1,
            f"expected 1, got {result}"
        )

        # Test 9b: post-Phoenix (custom trainers at high IDs) — returns 1
        with open(opp_path, "w") as f:
            f.write("#define TRAINER_NONE 0\n")
            f.write("#define TRAINER_ROCKET_BUSTER 855\n")
            f.write("#define TRAINER_ROCKET_DUO 856\n")
            f.write("#define TRAINERS_COUNT 857\n")
        result = _find_lowest_available_id(opp_path)
        _assert(
            "find_lowest_id: post-Phoenix returns 1",
            result == 1,
            f"expected 1, got {result}"
        )

        # Test 9c: ID 1 taken, next free is 2
        with open(opp_path, "w") as f:
            f.write("#define TRAINER_NONE 0\n")
            f.write("#define TRAINER_FIRST 1\n")
            f.write("#define TRAINER_ROCKET_BUSTER 855\n")
            f.write("#define TRAINERS_COUNT 857\n")
        result = _find_lowest_available_id(opp_path)
        _assert(
            "find_lowest_id: ID 1 taken returns 2",
            result == 2,
            f"expected 2, got {result}"
        )

    finally:
        shutil.rmtree(tmp2)

    # ------------------------------------------------------------------
    # _recalculate_trainers_count
    # ------------------------------------------------------------------

    tmp3 = tempfile.mkdtemp(prefix="torch_bc_")
    try:
        opp_path = os.path.join(tmp3, "opponents.h")

        # Test 10: patches TRAINERS_COUNT to max+1
        with open(opp_path, "w") as f:
            f.write("#define TRAINER_GRUNT_1 855\n")
            f.write("#define TRAINER_GRUNT_2 856\n")
            f.write("#define TRAINER_GRUNT_3 860\n")
            f.write("#define TRAINERS_COUNT 100\n")
        new_count = _recalculate_trainers_count(opp_path)
        _assert(
            "recalculate_count: returns max+1",
            new_count == 861,
            f"expected 861, got {new_count}"
        )
        # Verify the file was actually updated
        with open(opp_path) as f:
            content = f.read()
        _assert(
            "recalculate_count: file updated with 861",
            "861" in content,
            f"file content: {content!r}"
        )

        # Test 11: missing TRAINERS_COUNT line — still returns value, file unchanged
        with open(opp_path, "w") as f:
            f.write("#define TRAINER_GRUNT_1 855\n")
            f.write("#define TRAINER_GRUNT_2 856\n")
        new_count = _recalculate_trainers_count(opp_path)
        _assert(
            "recalculate_count: no TRAINERS_COUNT line still works",
            new_count == 857,
            f"expected 857, got {new_count}"
        )

    finally:
        shutil.rmtree(tmp3)

    # ------------------------------------------------------------------
    # _scan_all_references
    # ------------------------------------------------------------------

    tmp4 = tempfile.mkdtemp(prefix="torch_bc_")
    try:
        # Build a minimal game project tree
        inc_dir = os.path.join(tmp4, "include", "constants")
        src_dir = os.path.join(tmp4, "src", "data")
        map_dir = os.path.join(tmp4, "data", "maps", "Route1")
        os.makedirs(inc_dir)
        os.makedirs(src_dir)
        os.makedirs(map_dir)

        with open(os.path.join(inc_dir, "opponents.h"), "w") as f:
            f.write("#define TRAINER_TEST_GUY 900\n")

        with open(os.path.join(src_dir, "trainers.h"), "w") as f:
            f.write("[TRAINER_TEST_GUY] = { .trainerName = _(\"GUY\") },\n")

        with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
            f.write("trainerbattle_single(TRAINER_TEST_GUY, ...)\n")

        # Test 12: finds references across files with correct categories
        refs = _scan_all_references("TRAINER_TEST_GUY", tmp4)
        _assert(
            "scan_refs: finds 3 references",
            len(refs) == 3,
            f"expected 3, got {len(refs)}: {[r['category'] for r in refs]}"
        )

        categories = {r["category"] for r in refs}
        _assert(
            "scan_refs: categorizes opponents.h",
            "opponents.h" in categories,
            f"categories: {categories}"
        )
        _assert(
            "scan_refs: categorizes trainers.h",
            "trainers.h" in categories,
            f"categories: {categories}"
        )
        _assert(
            "scan_refs: categorizes map_script",
            "map_script" in categories,
            f"categories: {categories}"
        )

        # Test 13: no references returns empty
        refs_empty = _scan_all_references("TRAINER_NOBODY", tmp4)
        _assert(
            "scan_refs: no matches returns []",
            refs_empty == [],
            f"expected [], got {refs_empty}"
        )

    finally:
        shutil.rmtree(tmp4)

    # ------------------------------------------------------------------
    # _write_deletion_report
    # ------------------------------------------------------------------

    tmp5 = tempfile.mkdtemp(prefix="torch_bc_")
    try:
        record = {
            "trainer_id": 900,
            "trainer_name": "GUY",
            "trainer_const": "TRAINER_TEST_GUY",
        }
        refs = [
            {"file": "data/maps/Route1/scripts.pory", "line_num": 5,
             "line_text": "trainerbattle(TRAINER_TEST_GUY)", "category": "map_script"},
        ]
        auto_cleaned = [
            ("opponents.h", "Removed #define"),
            ("trainers.h", "Removed block"),
        ]

        # Test 14: report contains trainer name
        report_path = _write_deletion_report(
            "TRAINER_TEST_GUY", record, refs, auto_cleaned, tmp5
        )
        with open(report_path) as f:
            report_text = f.read()

        _assert(
            "deletion_report: contains trainer name",
            "GUY" in report_text,
            f"trainer name not found in report"
        )

        # Test 15: report contains reference file
        _assert(
            "deletion_report: contains reference file path",
            "scripts.pory" in report_text,
            "reference file not in report"
        )

        # Test 16: report contains auto-cleaned entries
        _assert(
            "deletion_report: contains auto-cleaned labels",
            "opponents.h" in report_text and "trainers.h" in report_text,
            "auto-cleaned entries missing"
        )

        # Test 17: report file was created in correct location
        _assert(
            "deletion_report: created in config/deletion_reports/",
            "deletion_reports" in report_path and os.path.exists(report_path),
            f"path: {report_path}"
        )

    finally:
        shutil.rmtree(tmp5)
