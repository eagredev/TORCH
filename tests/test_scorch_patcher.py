"""Scorch patcher suite -- tests C source patching for vanilla content removal."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


class MockPlan:
    """Minimal plan object for patcher testing."""

    def __init__(self):
        self.nuke_maps = []
        self.vanilla_tilesets = []
        self.vanilla_trainers = []
        self.custom_trainers = []
        self.vanilla_heal_ids = []
        self.custom_heal_ids = []
        self.c_patch_targets = []
        self.vanilla_mapsecs = set()


def run_suite():
    _begin_suite("Scorch Patcher")

    try:
        from torch.scorch_patcher import (
            PatchReport,
            _build_vanilla_map_const_set,
            _build_vanilla_tileset_symbols,
            _symbol_to_dir_name,
            _stub_static_bool_function,
            _patch_battle_setup,
            _patch_gym_leader_rematch_h,
            _patch_rematches_h,
            _patch_heal_locations_h,
            _patch_heal_locations_json,
            _patch_generic_map_refs,
            _patch_post_battle_heal,
            _extract_declared_var,
            _fix_orphaned_var_refs,
            _fix_guard_clause_inversions,
            _count_line_braces,
            _fix_orphaned_loop_stmts,
            _fix_orphaned_switch_cases,
            _fix_unreachable_switch_stmts,
            _fix_orphaned_block_bodies,
            _fix_braceless_scorched_bodies,
            _patch_battle_frontier_stubs,
            _ensure_custom_map_scripts,
            _stub_missing_localids,
            _patch_overworld_config,
            _fix_trailing_operator_on_prev_line,
            _is_conditional_stmt,
            _is_complete_statement,
            _handle_evolution_macro,
            _split_evolution_entries,
            apply_patches,
        )
    except ImportError as e:
        _skip("all scorch patcher tests", f"import failed: {e}")
        return

    # ==========================================================
    # A. PatchReport class
    # ==========================================================

    try:
        r = PatchReport()
        _assert("PatchReport: patches starts empty",
                r.patches == [], f"got {r.patches!r}")
        r.add("file.c", "action", "detail")
        _assert("PatchReport: add() creates entry with correct fields",
                len(r.patches) == 1
                and r.patches[0]["file"] == "file.c"
                and r.patches[0]["action"] == "action"
                and r.patches[0]["detail"] == "detail",
                f"got {r.patches!r}")
        _assert("PatchReport: errors still empty after add()",
                r.errors == [], f"got {r.errors!r}")
    except Exception as e:
        _fail("PatchReport", str(e))

    # ==========================================================
    # B. _build_vanilla_map_const_set
    # ==========================================================

    try:
        plan = MockPlan()
        plan.nuke_maps = ["PetalburgCity", "Route110", "BattleFrontierOutsideWest"]
        result = _build_vanilla_map_const_set(plan)

        _assert("map_const_set: PETALBURG_CITY in set",
                "PETALBURG_CITY" in result,
                f"got {result!r}")
        _assert("map_const_set: PascalCase NOT in set",
                "PetalburgCity" not in result,
                f"PascalCase found in {result!r}")
        _assert("map_const_set: correct size for 3 maps",
                len(result) == 3,
                f"expected 3, got {len(result)}")
    except Exception as e:
        _fail("_build_vanilla_map_const_set", str(e))

    # ==========================================================
    # C. _build_vanilla_tileset_symbols
    # ==========================================================

    try:
        plan = MockPlan()
        plan.vanilla_tilesets = [
            {"symbol": "gTileset_Petalburg"},
            {"symbol": "gTileset_BattleFrontierOutsideEast"},
        ]
        result = _build_vanilla_tileset_symbols(plan)

        _assert("tileset_symbols: Petalburg in set",
                "Petalburg" in result,
                f"got {result!r}")
        _assert("tileset_symbols: BattleFrontierOutsideEast in set",
                "BattleFrontierOutsideEast" in result,
                f"got {result!r}")
    except Exception as e:
        _fail("_build_vanilla_tileset_symbols", str(e))

    # ==========================================================
    # D. _symbol_to_dir_name
    # ==========================================================

    try:
        _assert("symbol_to_dir: Petalburg -> petalburg",
                _symbol_to_dir_name("Petalburg") == "petalburg",
                f"got {_symbol_to_dir_name('Petalburg')!r}")
        _assert("symbol_to_dir: BattleFrontierOutsideEast -> battle_frontier_outside_east",
                _symbol_to_dir_name("BattleFrontierOutsideEast") == "battle_frontier_outside_east",
                f"got {_symbol_to_dir_name('BattleFrontierOutsideEast')!r}")
        _assert("symbol_to_dir: empty -> empty",
                _symbol_to_dir_name("") == "",
                f"got {_symbol_to_dir_name('')!r}")
    except Exception as e:
        _fail("_symbol_to_dir_name", str(e))

    # ==========================================================
    # E. _stub_static_bool_function
    # ==========================================================

    try:
        fake_c = (
            "// header\n"
            "static bool16 MyFunc(void)\n"
            "{\n"
            "    if (condition)\n"
            "        return TRUE;\n"
            "    return FALSE;\n"
            "}\n"
            "// footer\n"
        )

        new_content, was_patched = _stub_static_bool_function(fake_c, "MyFunc")
        _assert("stub_bool: return FALSE in output",
                "return FALSE;" in new_content,
                f"content: {new_content!r}")
        _assert("stub_bool: original body removed",
                "if (condition)" not in new_content,
                f"original body still present")
        _assert("stub_bool: was_patched is True",
                was_patched is True,
                f"got {was_patched!r}")

        no_content, no_patch = _stub_static_bool_function(fake_c, "NonExistent")
        _assert("stub_bool: missing func returns False and unchanged",
                no_patch is False and no_content == fake_c,
                f"was_patched={no_patch!r}")
    except Exception as e:
        _fail("_stub_static_bool_function", str(e))

    # ==========================================================
    # F. _patch_battle_setup
    # ==========================================================

    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        battle_setup = os.path.join(src_dir, "battle_setup.c")
        original = (
            "// stuff before\n"
            "const struct RematchTrainer gRematchTable[REMATCH_TABLE_ENTRIES] =\n"
            "{\n"
            "    [REMATCH_ROXANNE] = { TRAINER_ROXANNE_1, ... },\n"
            "    [REMATCH_BRAWLY]  = { TRAINER_BRAWLY_1,  ... },\n"
            "\n};"
            "\n// stuff after\n"
        )
        with open(battle_setup, "w") as f:
            f.write(original)

        plan = MockPlan()
        report = PatchReport()
        _patch_battle_setup(tmp, plan, report)

        with open(battle_setup, "r") as f:
            result = f.read()

        _assert("patch_battle_setup: file was modified",
                result != original,
                "file unchanged")
        _assert("patch_battle_setup: report has patch entry",
                len(report.patches) >= 1,
                f"patches: {report.patches!r}")
        _assert("patch_battle_setup: vanilla entries removed",
                "TRAINER_ROXANNE_1" not in result,
                "vanilla entries still present")
    except Exception as e:
        _fail("_patch_battle_setup", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # G. _patch_heal_locations_h
    # ==========================================================

    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        inc_dir = os.path.join(tmp, "include", "constants")
        os.makedirs(inc_dir)
        heal_h = os.path.join(inc_dir, "heal_locations.h")
        original = (
            "#ifndef GUARD_CONSTANTS_HEAL_LOCATIONS_H\n"
            "#define GUARD_CONSTANTS_HEAL_LOCATIONS_H\n"
            "\n"
            "#define HEAL_LOCATION_NONE 0\n"
            "#define HEAL_LOCATION_PETALBURG_CITY 1\n"
            "#define HEAL_LOCATION_SLATEPORT_CITY 2\n"
            "#define HEAL_LOCATION_SEIHOKU_TOWN 3\n"
            "\n"
            "#endif\n"
        )
        with open(heal_h, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.vanilla_heal_ids = [
            ("HEAL_LOCATION_PETALBURG_CITY", 1),
            ("HEAL_LOCATION_SLATEPORT_CITY", 2),
        ]
        plan.custom_heal_ids = [
            ("HEAL_LOCATION_SEIHOKU_TOWN", 3),
        ]
        report = PatchReport()
        _patch_heal_locations_h(tmp, plan, report)

        with open(heal_h, "r") as f:
            result = f.read()

        _assert("patch_heal_h: vanilla entries removed",
                "PETALBURG_CITY" not in result and "SLATEPORT_CITY" not in result,
                f"vanilla still present in: {result!r}")
        _assert("patch_heal_h: custom entry survived",
                "HEAL_LOCATION_SEIHOKU_TOWN" in result,
                f"custom entry missing from: {result!r}")
        _assert("patch_heal_h: custom entry renumbered to 1",
                "HEAL_LOCATION_SEIHOKU_TOWN" in result
                and "1" in result.split("HEAL_LOCATION_SEIHOKU_TOWN")[1].split("\n")[0],
                f"renumbering failed: {result!r}")
    except Exception as e:
        _fail("_patch_heal_locations_h", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # H. _patch_generic_map_refs
    # ==========================================================

    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        generic_c = os.path.join(src_dir, "some_file.c")
        original = (
            "// unrelated header\n"
            "int x = 5;\n"
            "    case MAP_NUM(PETALBURG_CITY):\n"
            "        do_stuff();\n"
            "char *name = \"hello\";\n"
        )
        with open(generic_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = ["PetalburgCity"]
        plan.c_patch_targets = [
            {"rel_path": "src/some_file.c", "path": generic_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(generic_c, "r") as f:
            result = f.read()

        _assert("patch_generic: vanilla MAP_ ref handled",
                "case MAP_NUM(PETALBURG_CITY)" not in result,
                f"vanilla ref still present")
        _assert("patch_generic: report recorded action",
                len(report.patches) >= 1,
                f"patches: {report.patches!r}")
        _assert("patch_generic: unrelated content preserved",
                'int x = 5;' in result and '"hello"' in result,
                f"unrelated content lost")
    except Exception as e:
        _fail("_patch_generic_map_refs", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # I. Error paths
    # ==========================================================

    # I-1: Patcher with missing file — no crash
    try:
        plan = MockPlan()
        report = PatchReport()
        _patch_battle_setup("/nonexistent/path", plan, report)
        _assert("error: missing file no crash",
                True, "")
    except Exception as e:
        _fail("error: missing file no crash", str(e))

    # I-2: apply_patches with empty plan — returns empty report
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        plan = MockPlan()
        report = apply_patches(tmp, plan)
        _assert("error: empty plan returns empty report",
                isinstance(report, PatchReport)
                and len(report.patches) == 0
                and len(report.errors) == 0,
                f"patches={report.patches!r}, errors={report.errors!r}")
    except Exception as e:
        _fail("error: empty plan returns empty report", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # I-3: _patch_battle_setup with file but no matching pattern — records error
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "battle_setup.c"), "w") as f:
            f.write("// empty file with no gRematchTable\n")
        plan = MockPlan()
        report = PatchReport()
        _patch_battle_setup(tmp, plan, report)
        _assert("error: no pattern match records error",
                len(report.errors) >= 1,
                f"errors={report.errors!r}")
    except Exception as e:
        _fail("error: no pattern match records error", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # J. Idempotency
    # ==========================================================

    # J-1: _stub_static_bool_function is idempotent
    try:
        fake_c = (
            "static bool16 TestFunc(void)\n"
            "{\n"
            "    int x = 1;\n"
            "    return TRUE;\n"
            "}\n"
        )
        pass1, patched1 = _stub_static_bool_function(fake_c, "TestFunc")
        pass2, patched2 = _stub_static_bool_function(pass1, "TestFunc")
        _assert("idempotent: stub_bool 2nd pass matches 1st",
                pass2 == pass1,
                f"pass1 len={len(pass1)}, pass2 len={len(pass2)}")
    except Exception as e:
        _fail("idempotent: stub_bool", str(e))

    # J-2: _patch_battle_setup is idempotent
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        battle_setup = os.path.join(src_dir, "battle_setup.c")
        original = (
            "const struct RematchTrainer gRematchTable[REMATCH_TABLE_ENTRIES] =\n"
            "{\n"
            "    [REMATCH_ROXANNE] = { TRAINER_ROXANNE_1 },\n"
            "\n};"
            "\n"
        )
        with open(battle_setup, "w") as f:
            f.write(original)

        plan = MockPlan()
        report1 = PatchReport()
        _patch_battle_setup(tmp, plan, report1)
        with open(battle_setup, "r") as f:
            after_first = f.read()

        report2 = PatchReport()
        _patch_battle_setup(tmp, plan, report2)
        with open(battle_setup, "r") as f:
            after_second = f.read()

        _assert("idempotent: battle_setup 2nd pass matches 1st",
                after_second == after_first,
                f"first len={len(after_first)}, second len={len(after_second)}")
    except Exception as e:
        _fail("idempotent: battle_setup", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # K. _patch_post_battle_heal
    # ==========================================================

    # K-1: Patches both vanilla heal locations
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        pbef = os.path.join(src_dir, "post_battle_event_funcs.c")
        with open(pbef, "w") as f:
            f.write(
                "void GameClear(void)\n"
                "{\n"
                "    if (gSaveBlock2Ptr->playerGender == MALE)\n"
                "        SetContinueGameWarpToHealLocation(HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F);\n"
                "    else\n"
                "        SetContinueGameWarpToHealLocation(HEAL_LOCATION_LITTLEROOT_TOWN_MAYS_HOUSE_2F);\n"
                "}\n"
            )

        plan = MockPlan()
        plan.custom_heal_ids = [("HEAL_LOCATION_PLAYER_BEDROOM", 23)]
        report = PatchReport()
        _patch_post_battle_heal(tmp, plan, report)

        with open(pbef, "r") as f:
            result = f.read()

        _assert("post_battle_heal: BRENDANS replaced",
                "HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F" not in result,
                f"vanilla ref still present")
        _assert("post_battle_heal: MAYS replaced",
                "HEAL_LOCATION_LITTLEROOT_TOWN_MAYS_HOUSE_2F" not in result,
                f"vanilla ref still present")
        _assert("post_battle_heal: custom heal used",
                result.count("HEAL_LOCATION_PLAYER_BEDROOM") == 2,
                f"expected 2 occurrences, got {result.count('HEAL_LOCATION_PLAYER_BEDROOM')}")
        _assert("post_battle_heal: report has patch",
                len(report.patches) == 1
                and report.patches[0]["file"] == "src/post_battle_event_funcs.c",
                f"patches: {report.patches!r}")
    except Exception as e:
        _fail("_patch_post_battle_heal: patches both", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # K-2: No crash on missing file
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        plan = MockPlan()
        plan.custom_heal_ids = [("HEAL_LOCATION_PLAYER_BEDROOM", 23)]
        report = PatchReport()
        _patch_post_battle_heal(tmp, plan, report)
        _assert("post_battle_heal: missing file no crash",
                len(report.patches) == 0 and len(report.errors) == 0,
                f"patches={report.patches!r}, errors={report.errors!r}")
    except Exception as e:
        _fail("_patch_post_battle_heal: missing file", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # K-3: Error on no custom heal locations
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        pbef = os.path.join(src_dir, "post_battle_event_funcs.c")
        with open(pbef, "w") as f:
            f.write(
                "void GameClear(void)\n"
                "{\n"
                "    SetContinueGameWarpToHealLocation(HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F);\n"
                "}\n"
            )

        plan = MockPlan()
        plan.custom_heal_ids = []
        report = PatchReport()
        _patch_post_battle_heal(tmp, plan, report)
        # With no custom heals, the patcher skips gracefully (vanilla heal
        # constants are redirected to InsideOfTruck by the JSON patcher)
        with open(pbef, "r") as f:
            result = f.read()
        _assert("post_battle_heal: no-op on no custom heals",
                "HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F" in result,
                "should leave file unchanged when no custom heals")
    except Exception as e:
        _fail("_patch_post_battle_heal: no custom heals", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # L. _patch_gym_leader_rematch_h — with rematches.h (v1.14+)
    # ==========================================================

    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        inc_dir = os.path.join(tmp, "include")
        const_dir = os.path.join(inc_dir, "constants")
        os.makedirs(const_dir)
        glr_h = os.path.join(inc_dir, "gym_leader_rematch.h")
        with open(glr_h, "w") as f:
            f.write(
                "#ifndef GUARD_TRAINER_REMATCH_H\n"
                "#define GUARD_TRAINER_REMATCH_H\n"
                "#include \"constants/rematches.h\"\n"
                "void UpdateGymLeaderRematch(void);\n"
                "#endif\n"
            )
        # Create the rematches.h file so the patcher sees it
        with open(os.path.join(const_dir, "rematches.h"), "w") as f:
            f.write("enum { REMATCH_TABLE_ENTRIES };\n")

        plan = MockPlan()
        report = PatchReport()
        _patch_gym_leader_rematch_h(tmp, plan, report)

        with open(glr_h, "r") as f:
            result = f.read()

        _assert("patch_glr_h: includes rematches.h when file exists",
                '#include "constants/rematches.h"' in result,
                f"include missing from: {result!r}")
        _assert("patch_glr_h: has REMATCH_SPECIAL_TRAINER_START define",
                "REMATCH_SPECIAL_TRAINER_START" in result,
                f"define missing from: {result!r}")
        _assert("patch_glr_h: has function decl",
                "void UpdateGymLeaderRematch(void);" in result,
                f"function decl missing from: {result!r}")
        _assert("patch_glr_h: report recorded",
                len(report.patches) >= 1,
                f"patches: {report.patches!r}")
    except Exception as e:
        _fail("_patch_gym_leader_rematch_h (with rematches.h)", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # L2. _patch_gym_leader_rematch_h — no rematches.h (v1.9.x)
    # ==========================================================

    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        inc_dir = os.path.join(tmp, "include")
        os.makedirs(inc_dir)
        glr_h = os.path.join(inc_dir, "gym_leader_rematch.h")
        with open(glr_h, "w") as f:
            f.write(
                "#ifndef GUARD_TRAINER_REMATCH_H\n"
                "#define GUARD_TRAINER_REMATCH_H\n"
                "enum {\n"
                "    REMATCH_ROSE,\n"
                "    REMATCH_TABLE_ENTRIES\n"
                "};\n"
                "void UpdateGymLeaderRematch(void);\n"
                "#endif\n"
            )
        # No rematches.h file — simulates v1.9.x layout

        plan = MockPlan()
        report = PatchReport()
        _patch_gym_leader_rematch_h(tmp, plan, report)

        with open(glr_h, "r") as f:
            result = f.read()

        _assert("patch_glr_h_v19: inlines stub enum",
                "enum {" in result and "REMATCH_TABLE_ENTRIES" in result,
                f"stub enum missing from: {result!r}")
        _assert("patch_glr_h_v19: no rematches.h include",
                '#include "constants/rematches.h"' not in result,
                f"should not include rematches.h: {result!r}")
        _assert("patch_glr_h_v19: extracted REMATCH_ROSE",
                "REMATCH_ROSE" in getattr(plan, "vanilla_rematch_consts", set()),
                f"REMATCH_ROSE not extracted: {getattr(plan, 'vanilla_rematch_consts', None)}")
        _assert("patch_glr_h_v19: report recorded",
                len(report.patches) >= 1,
                f"patches: {report.patches!r}")
    except Exception as e:
        _fail("_patch_gym_leader_rematch_h (no rematches.h)", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # M. _patch_rematches_h — stubs enum to REMATCH_TABLE_ENTRIES only
    # ==========================================================

    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        const_dir = os.path.join(tmp, "include", "constants")
        os.makedirs(const_dir)
        rem_h = os.path.join(const_dir, "rematches.h")
        with open(rem_h, "w") as f:
            f.write(
                "#ifndef GUARD_REMATCHES_H\n"
                "#define GUARD_REMATCHES_H\n"
                "enum {\n"
                "    REMATCH_ROXANNE,\n"
                "    REMATCH_BRAWLY,\n"
                "    REMATCH_TABLE_ENTRIES\n"
                "};\n"
                "#define REMATCH_SPECIAL_TRAINER_START REMATCH_WALLY_VR\n"
                "#endif\n"
            )

        plan = MockPlan()
        report = PatchReport()
        _patch_rematches_h(tmp, plan, report)

        with open(rem_h, "r") as f:
            result = f.read()

        _assert("patch_rematches_h: vanilla entries removed",
                "REMATCH_ROXANNE" not in result and "REMATCH_BRAWLY" not in result,
                f"vanilla entries still in: {result!r}")
        _assert("patch_rematches_h: REMATCH_TABLE_ENTRIES kept",
                "REMATCH_TABLE_ENTRIES" in result,
                f"REMATCH_TABLE_ENTRIES missing from: {result!r}")
        _assert("patch_rematches_h: old defines removed",
                "REMATCH_WALLY_VR" not in result,
                f"old define still in: {result!r}")
        _assert("patch_rematches_h: report recorded",
                len(report.patches) >= 1,
                f"patches: {report.patches!r}")
    except Exception as e:
        _fail("_patch_rematches_h", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # M-2: No crash on missing file
    try:
        plan = MockPlan()
        report = PatchReport()
        _patch_rematches_h("/nonexistent/path", plan, report)
        _assert("patch_rematches_h: missing file no crash",
                len(report.patches) == 0, "")
    except Exception as e:
        _fail("_patch_rematches_h: missing file", str(e))

    # ==========================================================
    # N. _patch_heal_locations_json
    # ==========================================================

    import json

    # N-1: Removes vanilla entries, keeps custom
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        data_dir = os.path.join(tmp, "src", "data")
        os.makedirs(data_dir)
        heal_json = os.path.join(data_dir, "heal_locations.json")
        heal_data = {
            "heal_locations": [
                {"id": "HEAL_LOCATION_PETALBURG_CITY", "map": "MAP_PETALBURG_CITY", "x": 1, "y": 2},
                {"id": "HEAL_LOCATION_SLATEPORT_CITY", "map": "MAP_SLATEPORT_CITY", "x": 3, "y": 4},
                {"id": "HEAL_LOCATION_PLAYER_BEDROOM", "map": "MAP_PLAYER_BEDROOM", "x": 1, "y": 4},
            ]
        }
        with open(heal_json, "w") as f:
            json.dump(heal_data, f, indent=2)

        plan = MockPlan()
        plan.vanilla_heal_ids = [
            ("HEAL_LOCATION_PETALBURG_CITY", 1),
            ("HEAL_LOCATION_SLATEPORT_CITY", 2),
        ]
        plan.custom_heal_ids = [
            ("HEAL_LOCATION_PLAYER_BEDROOM", 3),
        ]
        report = PatchReport()
        _patch_heal_locations_json(tmp, plan, report)

        with open(heal_json, "r") as f:
            result = json.load(f)

        locs = result["heal_locations"]
        loc_ids = [l["id"] for l in locs]
        # Vanilla entries removed; InsideOfTruck fallback added; custom kept
        _assert("heal_json: vanilla removed + fallback added",
                len(locs) == 2,
                f"expected 2 entries (fallback + custom), got {len(locs)}: {loc_ids}")
        _assert("heal_json: InsideOfTruck fallback present",
                any(l["id"] == "HEAL_LOCATION_INSIDE_OF_TRUCK" for l in locs),
                f"missing InsideOfTruck fallback, got {loc_ids}")
        custom_loc = [l for l in locs if l["id"] == "HEAL_LOCATION_PLAYER_BEDROOM"][0]
        _assert("heal_json: custom entry unchanged",
                custom_loc["map"] == "MAP_PLAYER_BEDROOM",
                f"expected MAP_PLAYER_BEDROOM, got {custom_loc['map']}")
        _assert("heal_json: report recorded",
                len(report.patches) >= 1,
                f"patches: {report.patches!r}")
    except Exception as e:
        _fail("_patch_heal_locations_json", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # N-2: No crash on missing file
    try:
        plan = MockPlan()
        plan.vanilla_heal_ids = [("HEAL_LOCATION_PETALBURG_CITY", 1)]
        plan.custom_heal_ids = [("HEAL_LOCATION_PLAYER_BEDROOM", 3)]
        report = PatchReport()
        _patch_heal_locations_json("/nonexistent/path", plan, report)
        _assert("heal_json: missing file no crash",
                len(report.patches) == 0, "")
    except Exception as e:
        _fail("_patch_heal_locations_json: missing file", str(e))

    # N-3: No-op when no vanilla entries to remove
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        data_dir = os.path.join(tmp, "src", "data")
        os.makedirs(data_dir)
        heal_json = os.path.join(data_dir, "heal_locations.json")
        heal_data = {
            "heal_locations": [
                {"id": "HEAL_LOCATION_PLAYER_BEDROOM", "map": "MAP_PLAYER_BEDROOM", "x": 1, "y": 4},
            ]
        }
        with open(heal_json, "w") as f:
            json.dump(heal_data, f, indent=2)

        plan = MockPlan()
        plan.vanilla_heal_ids = []
        plan.custom_heal_ids = [("HEAL_LOCATION_PLAYER_BEDROOM", 1)]
        report = PatchReport()
        _patch_heal_locations_json(tmp, plan, report)
        _assert("heal_json: no-op when no vanilla",
                len(report.patches) == 0,
                f"patches: {report.patches!r}")
    except Exception as e:
        _fail("_patch_heal_locations_json: no-op", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # O. LAYOUT_* patching via _patch_generic_map_refs
    # ==========================================================

    # O-1: case LAYOUT_* lines are removed
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        layout_c = os.path.join(src_dir, "battle_pike.c")
        original = (
            "switch (gMapHeader.mapLayoutId)\n"
            "{\n"
            "    case LAYOUT_BATTLE_FRONTIER_BATTLE_PIKE_ROOM_NORMAL:\n"
            "        doNormal();\n"
            "        break;\n"
            "    case LAYOUT_CUSTOM_MAP:\n"
            "        doCustom();\n"
            "        break;\n"
            "}\n"
        )
        with open(layout_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {"LAYOUT_BATTLE_FRONTIER_BATTLE_PIKE_ROOM_NORMAL"}
        plan.c_patch_targets = [
            {"rel_path": "src/battle_pike.c", "path": layout_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(layout_c, "r") as f:
            result = f.read()

        _assert("layout_patch: case LAYOUT_* removed",
                "LAYOUT_BATTLE_FRONTIER_BATTLE_PIKE_ROOM_NORMAL" not in result,
                f"vanilla ref still present")
        _assert("layout_patch: custom case preserved",
                "LAYOUT_CUSTOM_MAP" in result,
                f"custom ref lost")
        _assert("layout_patch: report recorded",
                len(report.patches) >= 1,
                f"patches: {report.patches!r}")
    except Exception as e:
        _fail("LAYOUT_* case removal", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # O-2: return statement with LAYOUT_* is stubbed
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        hill_c = os.path.join(src_dir, "trainer_hill.c")
        original = (
            "static u8 GetFloorId(void)\n"
            "{\n"
            "    return gMapHeader.mapLayoutId - LAYOUT_TRAINER_HILL_1F;\n"
            "}\n"
        )
        with open(hill_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {"LAYOUT_TRAINER_HILL_1F"}
        plan.c_patch_targets = [
            {"rel_path": "src/trainer_hill.c", "path": hill_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(hill_c, "r") as f:
            result = f.read()

        _assert("layout_patch: return LAYOUT_* stubbed to 0",
                "return 0;" in result,
                f"return not stubbed: {result!r}")
        _assert("layout_patch: original LAYOUT ref removed",
                "LAYOUT_TRAINER_HILL_1F" not in result,
                f"vanilla ref still present")
    except Exception as e:
        _fail("LAYOUT_* return stub", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # O-3: if condition with LAYOUT_* replaced with FALSE
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        test_c = os.path.join(src_dir, "test_layout_if.c")
        original = (
            "void Func(void)\n"
            "{\n"
            "    if (gMapHeader.mapLayoutId == LAYOUT_ALTERING_CAVE)\n"
            "        DoAlteringCave();\n"
            "}\n"
        )
        with open(test_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {"LAYOUT_ALTERING_CAVE"}
        plan.c_patch_targets = [
            {"rel_path": "src/test_layout_if.c", "path": test_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(test_c, "r") as f:
            result = f.read()

        _assert("layout_patch: if LAYOUT_* replaced with FALSE",
                "if (FALSE)" in result,
                f"if not replaced: {result!r}")
        _assert("layout_patch: vanilla LAYOUT ref removed from if",
                "LAYOUT_ALTERING_CAVE" not in result,
                f"vanilla ref still present")
    except Exception as e:
        _fail("LAYOUT_* if condition", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # O-4: array initializer with LAYOUT_* removed
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        test_c = os.path.join(src_dir, "test_layout_array.c")
        original = (
            "static const u16 sLayouts[] = {\n"
            "    [LAYOUT_TRAINER_HILL_1F] = 1,\n"
            "    [LAYOUT_CUSTOM] = 2,\n"
            "};\n"
        )
        with open(test_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {"LAYOUT_TRAINER_HILL_1F"}
        plan.c_patch_targets = [
            {"rel_path": "src/test_layout_array.c", "path": test_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(test_c, "r") as f:
            result = f.read()

        _assert("layout_patch: array [LAYOUT_*] removed",
                "LAYOUT_TRAINER_HILL_1F" not in result,
                f"vanilla ref still present")
        _assert("layout_patch: custom array entry preserved",
                "LAYOUT_CUSTOM" in result,
                f"custom ref lost")
    except Exception as e:
        _fail("LAYOUT_* array initializer", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # O-5: No-op when vanilla_layout_consts is empty
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        test_c = os.path.join(src_dir, "noop.c")
        original = "    case LAYOUT_SOMETHING:\n"
        with open(test_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = set()
        plan.c_patch_targets = [
            {"rel_path": "src/noop.c", "path": test_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(test_c, "r") as f:
            result = f.read()

        _assert("layout_patch: no-op when empty layout set",
                result == original,
                f"file was modified unexpectedly")
    except Exception as e:
        _fail("LAYOUT_* no-op on empty set", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # P. Continuation line consumption
    # ==========================================================

    # P-1: Multi-line return where ALL continuations have vanilla refs
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        test_c = os.path.join(src_dir, "cont_all_vanilla.c")
        original = (
            "bool8 InBattlePike(void)\n"
            "{\n"
            "    return gMapHeader.mapLayoutId == LAYOUT_BATTLE_PIKE_THREE_PATH\n"
            "        || gMapHeader.mapLayoutId == LAYOUT_BATTLE_PIKE_NORMAL\n"
            "        || gMapHeader.mapLayoutId == LAYOUT_BATTLE_PIKE_WILD;\n"
            "}\n"
        )
        with open(test_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {
            "LAYOUT_BATTLE_PIKE_THREE_PATH",
            "LAYOUT_BATTLE_PIKE_NORMAL",
            "LAYOUT_BATTLE_PIKE_WILD",
        }
        plan.c_patch_targets = [
            {"rel_path": "src/cont_all_vanilla.c", "path": test_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(test_c, "r") as f:
            result = f.read()

        _assert("continuation P1: return stubbed to 0",
                "return 0;" in result,
                f"return not stubbed: {result!r}")
        # Check no live (uncommented) continuation lines remain
        live_cont = [l for l in result.splitlines()
                     if l.strip().startswith("||") and not l.strip().startswith("//")]
        _assert("continuation P1: all continuations consumed",
                len(live_cont) == 0,
                f"live continuations survived: {live_cont!r}")
        _assert("continuation P1: continuations are commented",
                "// Scorched:" in result,
                f"missing scorched comments: {result!r}")
    except Exception as e:
        _fail("continuation P1: all vanilla", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # P-2: Multi-line return where last continuation has NON-vanilla ref
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        test_c = os.path.join(src_dir, "cont_mixed.c")
        original = (
            "bool8 InBattlePike(void)\n"
            "{\n"
            "    return gMapHeader.mapLayoutId == LAYOUT_BATTLE_PIKE_THREE_PATH\n"
            "        || gMapHeader.mapLayoutId == LAYOUT_BATTLE_PIKE_NORMAL\n"
            "        || gMapHeader.mapLayoutId == LAYOUT_CUSTOM_ROOM;\n"
            "}\n"
        )
        with open(test_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {
            "LAYOUT_BATTLE_PIKE_THREE_PATH",
            "LAYOUT_BATTLE_PIKE_NORMAL",
        }
        plan.c_patch_targets = [
            {"rel_path": "src/cont_mixed.c", "path": test_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(test_c, "r") as f:
            result = f.read()

        _assert("continuation P2: return stubbed to 0",
                "return 0;" in result,
                f"return not stubbed: {result!r}")
        _assert("continuation P2: non-vanilla continuation also consumed",
                "LAYOUT_CUSTOM_ROOM" not in result
                or "// Scorched:" in result.split("LAYOUT_CUSTOM_ROOM")[0].split("\n")[-1],
                f"non-vanilla continuation not consumed: {result!r}")
        _assert("continuation P2: no dangling ||",
                "\n        || " not in result.replace("// Scorched:", ""),
                f"dangling || found: {result!r}")
    except Exception as e:
        _fail("continuation P2: mixed vanilla/non-vanilla", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # P-3: Multi-line if where continuations have vanilla refs
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        test_c = os.path.join(src_dir, "cont_if.c")
        original = (
            "void Func(void)\n"
            "{\n"
            "    if (gMapHeader.mapLayoutId == LAYOUT_BATTLE_PIKE_THREE_PATH\n"
            "        && gMapHeader.mapLayoutId == LAYOUT_BATTLE_PIKE_NORMAL)\n"
            "    {\n"
            "        DoStuff();\n"
            "    }\n"
            "}\n"
        )
        with open(test_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {
            "LAYOUT_BATTLE_PIKE_THREE_PATH",
            "LAYOUT_BATTLE_PIKE_NORMAL",
        }
        plan.c_patch_targets = [
            {"rel_path": "src/cont_if.c", "path": test_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(test_c, "r") as f:
            result = f.read()

        _assert("continuation P3: if replaced with FALSE",
                "if (FALSE)" in result,
                f"if not replaced: {result!r}")
        _assert("continuation P3: && continuation consumed",
                "&& gMapHeader" not in result or "// Scorched:" in result,
                f"continuation not consumed: {result!r}")
    except Exception as e:
        _fail("continuation P3: multi-line if", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # P-4: Vanilla ref line followed by non-continuation — only vanilla patched
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        test_c = os.path.join(src_dir, "cont_no_cont.c")
        original = (
            "    return gMapHeader.mapLayoutId - LAYOUT_BATTLE_PIKE_THREE_PATH;\n"
            "    int x = 5;\n"
        )
        with open(test_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {"LAYOUT_BATTLE_PIKE_THREE_PATH"}
        plan.c_patch_targets = [
            {"rel_path": "src/cont_no_cont.c", "path": test_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(test_c, "r") as f:
            result = f.read()

        _assert("continuation P4: vanilla line patched",
                "return 0;" in result,
                f"vanilla not patched: {result!r}")
        _assert("continuation P4: next line unchanged",
                "int x = 5;" in result,
                f"next line was modified: {result!r}")
    except Exception as e:
        _fail("continuation P4: no continuation", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # Q. Variable declaration dependency
    # ==========================================================

    # Q-1: Var decl with vanilla ref, 3 downstream lines using it — all commented
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        test_c = os.path.join(src_dir, "vardep_all.c")
        original = (
            "void Func(void)\n"
            "{\n"
            "    const struct MapLayout *mapLayout = gMapLayouts[LAYOUT_BATTLE_PYRAMID_FLOOR];\n"
            "    const u16 *layoutMap = mapLayout->map;\n"
            "    int width = mapLayout->width;\n"
            "    int height = mapLayout->height;\n"
            "}\n"
        )
        with open(test_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {"LAYOUT_BATTLE_PYRAMID_FLOOR"}
        plan.c_patch_targets = [
            {"rel_path": "src/vardep_all.c", "path": test_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(test_c, "r") as f:
            result = f.read()

        _assert("vardep Q1: declaration commented out",
                "// Scorched:" in result and "LAYOUT_BATTLE_PYRAMID_FLOOR" in result,
                f"declaration not commented: {result!r}")
        _assert("vardep Q1: downstream mapLayout refs commented",
                "mapLayout->map" not in result.replace("// Scorched:", "").split("//")[0]
                or all("// Scorched:" in l for l in result.splitlines() if "mapLayout" in l and "void" not in l),
                f"downstream refs not commented: {result!r}")
        # All 4 lines (decl + 3 downstream) should be commented
        scorched_count = result.count("// Scorched:")
        _assert("vardep Q1: all 4 lines scorched",
                scorched_count == 4,
                f"expected 4, got {scorched_count}")
    except Exception as e:
        _fail("vardep Q1: all downstream", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Q-2: Var decl + mixed downstream (some use var, some don't)
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        test_c = os.path.join(src_dir, "vardep_mixed.c")
        original = (
            "void Func(void)\n"
            "{\n"
            "    const struct MapLayout *mapLayout = gMapLayouts[LAYOUT_BATTLE_PYRAMID_FLOOR];\n"
            "    const u16 *layoutMap = mapLayout->map;\n"
            "    int unrelated = 42;\n"
            "    gBackupMapLayout.width = mapLayout->width;\n"
            "}\n"
        )
        with open(test_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {"LAYOUT_BATTLE_PYRAMID_FLOOR"}
        plan.c_patch_targets = [
            {"rel_path": "src/vardep_mixed.c", "path": test_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(test_c, "r") as f:
            result = f.read()

        _assert("vardep Q2: unrelated line preserved",
                "int unrelated = 42;" in result
                and "// Scorched: int unrelated" not in result,
                f"unrelated line was modified: {result!r}")
        _assert("vardep Q2: var-using lines commented",
                all("// Scorched:" in l for l in result.splitlines()
                    if "mapLayout" in l and "void" not in l),
                f"var-using lines not all commented: {result!r}")
    except Exception as e:
        _fail("vardep Q2: mixed downstream", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Q-3: No variable declaration (regular comment-out) — no downstream scan
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        test_c = os.path.join(src_dir, "vardep_none.c")
        original = (
            "void Func(void)\n"
            "{\n"
            "    DoSomething(LAYOUT_BATTLE_PYRAMID_FLOOR);\n"
            "    int x = 5;\n"
            "    int y = 10;\n"
            "}\n"
        )
        with open(test_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_layout_consts = {"LAYOUT_BATTLE_PYRAMID_FLOOR"}
        plan.c_patch_targets = [
            {"rel_path": "src/vardep_none.c", "path": test_c},
        ]
        report = PatchReport()
        _patch_generic_map_refs(tmp, plan, report)

        with open(test_c, "r") as f:
            result = f.read()

        _assert("vardep Q3: vanilla line commented",
                "// Scorched:" in result and "LAYOUT_BATTLE_PYRAMID_FLOOR" in result,
                f"vanilla not commented: {result!r}")
        _assert("vardep Q3: downstream lines preserved",
                "int x = 5;" in result and "int y = 10;" in result,
                f"downstream lines were modified: {result!r}")
        scorched_count = result.count("// Scorched:")
        _assert("vardep Q3: only 1 line scorched",
                scorched_count == 1,
                f"expected 1, got {scorched_count}")
    except Exception as e:
        _fail("vardep Q3: no var decl", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # R. _extract_declared_var helper
    # ==========================================================

    try:
        _assert("extract_var: simple type",
                _extract_declared_var("    int foo = 5;") == "foo",
                f"got {_extract_declared_var('    int foo = 5;')!r}")
        _assert("extract_var: const struct pointer",
                _extract_declared_var("    const struct MapLayout *mapLayout = gMapLayouts[0];") == "mapLayout",
                f"got {_extract_declared_var('    const struct MapLayout *mapLayout = gMapLayouts[0];')!r}")
        _assert("extract_var: const u16 pointer",
                _extract_declared_var("    const u16 *layoutMap = mapLayout->map;") == "layoutMap",
                f"got {_extract_declared_var('    const u16 *layoutMap = mapLayout->map;')!r}")
        _assert("extract_var: not a declaration",
                _extract_declared_var("    DoSomething(foo);") is None,
                f"got {_extract_declared_var('    DoSomething(foo);')!r}")
        _assert("extract_var: if statement not a declaration",
                _extract_declared_var("    if (x == 5)") is None,
                f"got {_extract_declared_var('    if (x == 5)')!r}")
    except Exception as e:
        _fail("_extract_declared_var", str(e))

    # R-2: Bug 7 — storage class specifiers and array brackets
    try:
        _assert("extract_var: static const array",
                _extract_declared_var("static const u8 sMapSectionToThemeId[MAPSEC_COUNT - KANTO_MAPSEC_COUNT - 1] =") == "sMapSectionToThemeId",
                f"got {_extract_declared_var('static const u8 sMapSectionToThemeId[MAPSEC_COUNT - KANTO_MAPSEC_COUNT - 1] =')!r}")
        _assert("extract_var: static array empty brackets",
                _extract_declared_var("static u8 baz[] =") == "baz",
                f"got {_extract_declared_var('static u8 baz[] =')!r}")
        _assert("extract_var: extern",
                _extract_declared_var("extern u32 gGlobal =") == "gGlobal",
                f"got {_extract_declared_var('extern u32 gGlobal =')!r}")
        _assert("extract_var: static volatile",
                _extract_declared_var("static volatile u16 counter = 0;") == "counter",
                f"got {_extract_declared_var('static volatile u16 counter = 0;')!r}")
        _assert("extract_var: plain array",
                _extract_declared_var("u8 simple[10] =") == "simple",
                f"got {_extract_declared_var('u8 simple[10] =')!r}")
        _assert("extract_var: static const struct pointer",
                _extract_declared_var("static const struct Thing *ptr = NULL;") == "ptr",
                f"got {_extract_declared_var('static const struct Thing *ptr = NULL;')!r}")
        # Negative cases
        _assert("extract_var: return not a decl",
                _extract_declared_var("    return foo;") is None,
                f"got {_extract_declared_var('    return foo;')!r}")
        _assert("extract_var: if assignment not a decl",
                _extract_declared_var("    if (x = 5)") is None,
                f"got {_extract_declared_var('    if (x = 5)')!r}")
        _assert("extract_var: arrow assignment not a decl",
                _extract_declared_var("    foo->bar = 3") is None,
                f"got {_extract_declared_var('    foo->bar = 3')!r}")
    except Exception as e:
        _fail("_extract_declared_var Bug 7", str(e))

    # R-3: Bug 7 end-to-end — Pass 2 catches refs to scorched static array
    try:
        lines = [
            "// Scorched: static const u8 myArray[SIZE] = {\n",
            "// Scorched:     1, 2, 3,\n",
            "// Scorched: };\n",
            "    x = myArray[i];\n",
            "    y = otherVar + 1;\n",
        ]
        result, count = _fix_orphaned_var_refs(lines)
        joined = "".join(result)
        _assert("R-3: Pass 2 scorches ref to static array",
                "// Scorched:" in result[3] and "myArray" in result[3],
                f"line 3 not scorched, got: {result[3]!r}")
        _assert("R-3: unrelated line survives",
                result[4] == "    y = otherVar + 1;\n",
                f"line 4 modified, got: {result[4]!r}")
        _assert("R-3: count is 1",
                count == 1, f"expected 1 patch, got {count}")
    except Exception as e:
        _fail("_fix_orphaned_var_refs Bug 7 e2e", str(e))

    # ==========================================================
    # S. Battle Frontier stub declarations
    # ==========================================================

    # S-1: Stubs inserted correctly in battle_pike.c
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        pike_c = os.path.join(src_dir, "battle_pike.c")
        original = (
            '#include "global.h"\n'
            '#include "battle_pike.h"\n'
            '\n'
            'void BattlePikeFunc(void)\n'
            '{\n'
            '    gTrainerBattleOpponent_A = 5;\n'
            '}\n'
        )
        with open(pike_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        report = PatchReport()
        _patch_battle_frontier_stubs(tmp, plan, report)

        with open(pike_c, "r") as f:
            result = f.read()

        _assert("frontier S1: stub comment present",
                "// Scorched: stub declarations" in result,
                f"stub comment missing: {result!r}")
        _assert("frontier S1: report entry added",
                len(report.patches) == 1
                and report.patches[0]["file"] == "src/battle_pike.c",
                f"report wrong: {report.patches!r}")
    except Exception as e:
        _fail("frontier S1: battle_pike.c stubs", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # S-2: Stubs inserted correctly in battle_pyramid.c
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        pyr_c = os.path.join(src_dir, "battle_pyramid.c")
        original = (
            '#include "global.h"\n'
            '#include "battle_pyramid.h"\n'
            '\n'
            'void PyramidFunc(void)\n'
            '{\n'
            '    gTrainerBattleOpponent_A = 1;\n'
            '    u32 bit = gBitTable[3];\n'
            '}\n'
        )
        with open(pyr_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        report = PatchReport()
        _patch_battle_frontier_stubs(tmp, plan, report)

        with open(pyr_c, "r") as f:
            result = f.read()

        _assert("frontier S2: BATTLE_PYRAMID_FUNC_IS_IN declared",
                "#define BATTLE_PYRAMID_FUNC_IS_IN 12" in result,
                f"define missing: {result!r}")
        _assert("frontier S2: InBattlePyramid forward declared",
                "u8 InBattlePyramid(void);" in result,
                f"forward decl missing: {result!r}")
        _assert("frontier S2: report entry added",
                len(report.patches) == 1
                and report.patches[0]["file"] == "src/battle_pyramid.c",
                f"report wrong: {report.patches!r}")
    except Exception as e:
        _fail("frontier S2: battle_pyramid.c stubs", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # S-3: Already-patched file is NOT double-patched
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        pike_c = os.path.join(src_dir, "battle_pike.c")
        original = (
            '#include "global.h"\n'
            '#include "battle_pike.h"\n'
            '\n'
            '// Scorched: stub declarations for removed Battle Frontier symbols\n'
            '\n'
            'void BattlePikeFunc(void)\n'
            '{\n'
            '    gTrainerBattleOpponent_A = 5;\n'
            '}\n'
        )
        with open(pike_c, "w") as f:
            f.write(original)

        plan = MockPlan()
        report = PatchReport()
        _patch_battle_frontier_stubs(tmp, plan, report)

        with open(pike_c, "r") as f:
            result = f.read()

        _assert("frontier S3: no double-patch",
                result.count("// Scorched: stub declarations") == 1,
                f"double-patched: {result!r}")
        _assert("frontier S3: no report entry",
                len(report.patches) == 0,
                f"report should be empty: {report.patches!r}")
    except Exception as e:
        _fail("frontier S3: no double-patch", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # S-4: Missing file is skipped gracefully
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        # Don't create any files — both should be missing
        plan = MockPlan()
        report = PatchReport()
        _patch_battle_frontier_stubs(tmp, plan, report)

        _assert("frontier S4: no report for missing files",
                len(report.patches) == 0,
                f"report should be empty: {report.patches!r}")
        _assert("frontier S4: no errors",
                len(report.errors) == 0,
                f"errors should be empty: {report.errors!r}")
    except Exception as e:
        _fail("frontier S4: missing file skip", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # S-5: Both files patched in one call
    tmp = tempfile.mkdtemp(prefix="torch_patcher_test_")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        for fname, content in [
            ("battle_pike.c", '#include "global.h"\nvoid F(void) {}\n'),
            ("battle_pyramid.c", '#include "global.h"\nvoid G(void) {}\n'),
        ]:
            with open(os.path.join(src_dir, fname), "w") as f:
                f.write(content)

        plan = MockPlan()
        report = PatchReport()
        _patch_battle_frontier_stubs(tmp, plan, report)

        _assert("frontier S5: both files patched",
                len(report.patches) == 2,
                f"expected 2 patches, got {len(report.patches)}: {report.patches!r}")
    except Exception as e:
        _fail("frontier S5: both files", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # Bug 2: _patch_battle_frontier_stubs in pipeline
    # ==========================================================

    # Verify _patch_battle_frontier_stubs is called during apply_patches
    # by running apply_patches on a minimal game tree with a stub-needing file.
    tmp = tempfile.mkdtemp(prefix="torch_patcher_bug2_")
    try:
        # Minimal game tree
        src_dir = os.path.join(tmp, "src")
        inc_dir = os.path.join(tmp, "include", "constants")
        data_dir = os.path.join(tmp, "data", "maps")
        scripts_dir = os.path.join(tmp, "data", "scripts")
        os.makedirs(src_dir)
        os.makedirs(inc_dir)
        os.makedirs(data_dir)
        os.makedirs(scripts_dir)

        # pokenav_match_call_data.c — needs FLAG_REGISTERED_* stubs
        pnmc = os.path.join(src_dir, "pokenav_match_call_data.c")
        with open(pnmc, "w") as f:
            f.write(
                '#include "global.h"\n'
                '\n'
                'static const int sData[] = {\n'
                '    FLAG_REGISTERED_SIDNEY,\n'
                '};\n'
            )

        plan = MockPlan()
        plan.nuke_maps = []
        plan.vanilla_trainers = []
        plan.c_patch_targets = []

        report = apply_patches(tmp, plan)

        with open(pnmc, "r") as f:
            result = f.read()

        _assert("bug2: FLAG_REGISTERED stubs injected by apply_patches",
                "FLAG_REGISTERED_SIDNEY" in result
                and "#define FLAG_REGISTERED_SIDNEY" in result,
                f"stubs not found in: {result[:300]}")
    except Exception as e:
        _fail("Bug 2: frontier stubs via apply_patches", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # Bug 3: _stub_missing_localids
    # ==========================================================

    # Test: LOCALID stubs generated for referenced but deleted constants
    tmp = tempfile.mkdtemp(prefix="torch_patcher_bug3_")
    try:
        src_dir = os.path.join(tmp, "src")
        inc_dir = os.path.join(tmp, "include", "constants")
        maps_dir = os.path.join(tmp, "data", "maps")
        os.makedirs(src_dir)
        os.makedirs(inc_dir)
        os.makedirs(maps_dir)

        # map_event_ids.h with vanilla + custom LOCALIDs
        mei_content = (
            "#ifndef GUARD_CONSTANTS_MAP_EVENT_IDS_H\n"
            "#define GUARD_CONSTANTS_MAP_EVENT_IDS_H\n"
            "\n"
            "// ContestHall\n"
            "#define LOCALID_CONTESTANT_1 3\n"
            "#define LOCALID_CONTESTANT_2 4\n"
            "\n"
            "// FarawayIsland\n"
            "#define LOCALID_FARAWAY_ISLAND_MEW 1\n"
            "\n"
            "// CustomCity\n"
            "#define LOCALID_CUSTOM_NPC 1\n"
            "\n"
            "#endif\n"
        )
        with open(os.path.join(inc_dir, "map_event_ids.h"), "w") as f:
            f.write(mei_content)

        # event_objects.h that includes map_event_ids.h
        eo_content = (
            '#ifndef GUARD_EVENT_OBJECTS_H\n'
            '#define GUARD_EVENT_OBJECTS_H\n'
            '#include "constants/map_event_ids.h"\n'
            '#endif\n'
        )
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write(eo_content)

        # C file referencing vanilla LOCALIDs
        with open(os.path.join(src_dir, "contest_util.c"), "w") as f:
            f.write(
                '#include "global.h"\n'
                'void foo(void) {\n'
                '    int x = LOCALID_CONTESTANT_1;\n'
                '    int y = LOCALID_CONTESTANT_2;\n'
                '    int z = LOCALID_CUSTOM_NPC;\n'
                '}\n'
            )

        # C file referencing FarawayIsland LOCALID
        with open(os.path.join(src_dir, "faraway_island.c"), "w") as f:
            f.write(
                '#include "global.h"\n'
                'void bar(void) {\n'
                '    int m = LOCALID_FARAWAY_ISLAND_MEW;\n'
                '}\n'
            )

        plan = MockPlan()
        plan.nuke_maps = ["ContestHall", "FarawayIsland"]
        plan.keep_maps = {"CustomCity"}

        report = PatchReport()
        _stub_missing_localids(tmp, plan, report)

        # Check stub file was created
        stub_path = os.path.join(inc_dir, "scorched_localid_stubs.h")
        _assert("bug3: stub file created", os.path.isfile(stub_path),
                "scorched_localid_stubs.h not found")

        with open(stub_path, "r") as f:
            stub_content = f.read()

        _assert("bug3: LOCALID_CONTESTANT_1 stubbed",
                "LOCALID_CONTESTANT_1" in stub_content)
        _assert("bug3: LOCALID_CONTESTANT_2 stubbed",
                "LOCALID_CONTESTANT_2" in stub_content)
        _assert("bug3: LOCALID_FARAWAY_ISLAND_MEW stubbed",
                "LOCALID_FARAWAY_ISLAND_MEW" in stub_content)
        _assert("bug3: LOCALID_CUSTOM_NPC NOT stubbed (kept map)",
                "LOCALID_CUSTOM_NPC" not in stub_content,
                f"custom NPC should not be in stubs: {stub_content}")

        # Check event_objects.h was updated
        with open(os.path.join(inc_dir, "event_objects.h"), "r") as f:
            eo_after = f.read()
        _assert("bug3: event_objects.h includes stub header",
                "scorched_localid_stubs.h" in eo_after)

        # Check report
        _assert("bug3: report includes stub count",
                any("localid" in p["file"] for p in report.patches),
                f"report patches: {report.patches}")

    except Exception as e:
        _fail("Bug 3: LOCALID stubs", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test: No stubs when no LOCALIDs are missing
    tmp = tempfile.mkdtemp(prefix="torch_patcher_bug3b_")
    try:
        src_dir = os.path.join(tmp, "src")
        inc_dir = os.path.join(tmp, "include", "constants")
        os.makedirs(src_dir)
        os.makedirs(inc_dir)

        mei_content = (
            "#ifndef GUARD\n"
            "#define GUARD\n"
            "// CustomCity\n"
            "#define LOCALID_CUSTOM_NPC 1\n"
            "#endif\n"
        )
        with open(os.path.join(inc_dir, "map_event_ids.h"), "w") as f:
            f.write(mei_content)

        with open(os.path.join(src_dir, "test.c"), "w") as f:
            f.write('int x = LOCALID_CUSTOM_NPC;\n')

        plan = MockPlan()
        plan.nuke_maps = []
        plan.keep_maps = {"CustomCity"}

        report = PatchReport()
        _stub_missing_localids(tmp, plan, report)

        stub_path = os.path.join(inc_dir, "scorched_localid_stubs.h")
        _assert("bug3b: no stub file when nothing missing",
                not os.path.isfile(stub_path),
                "stub file should not exist")
    except Exception as e:
        _fail("Bug 3b: no stubs needed", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test: LOCALID refs in .s files (event_scripts.s) are caught
    tmp = tempfile.mkdtemp(prefix="torch_patcher_bug3c_")
    try:
        src_dir = os.path.join(tmp, "src")
        inc_dir = os.path.join(tmp, "include", "constants")
        data_dir = os.path.join(tmp, "data")
        os.makedirs(src_dir)
        os.makedirs(inc_dir)
        os.makedirs(data_dir)

        mei_content = (
            "#ifndef GUARD\n"
            "#define GUARD\n"
            "// RusturfTunnel\n"
            "#define LOCALID_RUSTURF_TUNNEL_WANDA 1\n"
            "#define LOCALID_RUSTURF_TUNNEL_WANDAS_BF 2\n"
            "// CustomCity\n"
            "#define LOCALID_CUSTOM_NPC 1\n"
            "#endif\n"
        )
        with open(os.path.join(inc_dir, "map_event_ids.h"), "w") as f:
            f.write(mei_content)

        eo_content = (
            '#ifndef GUARD_EVENT_OBJECTS_H\n'
            '#define GUARD_EVENT_OBJECTS_H\n'
            '#include "constants/map_event_ids.h"\n'
            '#endif\n'
        )
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write(eo_content)

        # .s file referencing vanilla LOCALIDs (like event_scripts.s)
        with open(os.path.join(data_dir, "event_scripts.s"), "w") as f:
            f.write(
                'RusturfTunnel_EventScript_SetOpen::\n'
                '\tremoveobject LOCALID_RUSTURF_TUNNEL_WANDAS_BF\n'
                '\tremoveobject LOCALID_RUSTURF_TUNNEL_WANDA\n'
                '\treturn\n'
            )

        plan = MockPlan()
        plan.nuke_maps = ["RusturfTunnel"]
        plan.keep_maps = {"CustomCity"}

        report = PatchReport()
        _stub_missing_localids(tmp, plan, report)

        stub_path = os.path.join(inc_dir, "scorched_localid_stubs.h")
        _assert("bug3c: stub file created for .s refs",
                os.path.isfile(stub_path),
                "scorched_localid_stubs.h not found")
        with open(stub_path, "r") as f:
            stub_content = f.read()
        _assert("bug3c: LOCALID_RUSTURF_TUNNEL_WANDA stubbed",
                "LOCALID_RUSTURF_TUNNEL_WANDA" in stub_content)
        _assert("bug3c: LOCALID_RUSTURF_TUNNEL_WANDAS_BF stubbed",
                "LOCALID_RUSTURF_TUNNEL_WANDAS_BF" in stub_content)
    except Exception as e:
        _fail("Bug 3c: LOCALID stubs from .s files", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # Bug 4: _ensure_custom_map_scripts scans disk
    # ==========================================================

    # Test (a): map in keep_maps and on disk — included
    tmp = tempfile.mkdtemp(prefix="torch_patcher_bug4_")
    try:
        maps_dir = os.path.join(tmp, "data", "maps")
        os.makedirs(os.path.join(maps_dir, "KeptMap"))
        with open(os.path.join(maps_dir, "KeptMap", "scripts.inc"), "w") as f:
            f.write("@ scripts\n")

        es_path = os.path.join(tmp, "data", "event_scripts.s")
        with open(es_path, "w") as f:
            f.write('\t.include "data/scripts/std.inc"\n')

        plan = MockPlan()
        plan.keep_maps = {"KeptMap"}

        report = PatchReport()
        _ensure_custom_map_scripts(tmp, plan, report)

        with open(es_path, "r") as f:
            es_content = f.read()

        _assert("bug4a: keep_maps map included",
                'data/maps/KeptMap/scripts.inc' in es_content)

    except Exception as e:
        _fail("Bug 4a: keep_maps map included", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test (b): map on disk but NOT in keep_maps — still included
    tmp = tempfile.mkdtemp(prefix="torch_patcher_bug4b_")
    try:
        maps_dir = os.path.join(tmp, "data", "maps")
        os.makedirs(os.path.join(maps_dir, "NewMap"))
        with open(os.path.join(maps_dir, "NewMap", "scripts.inc"), "w") as f:
            f.write("@ scripts\n")

        es_path = os.path.join(tmp, "data", "event_scripts.s")
        with open(es_path, "w") as f:
            f.write('\t.include "data/scripts/std.inc"\n')

        plan = MockPlan()
        plan.keep_maps = set()  # empty — NewMap NOT in keep_maps

        report = PatchReport()
        _ensure_custom_map_scripts(tmp, plan, report)

        with open(es_path, "r") as f:
            es_content = f.read()

        _assert("bug4b: disk-only map included",
                'data/maps/NewMap/scripts.inc' in es_content,
                f"content: {es_content}")

    except Exception as e:
        _fail("Bug 4b: disk-only map included", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test (c): map in keep_maps but no scripts.inc on disk — skipped
    tmp = tempfile.mkdtemp(prefix="torch_patcher_bug4c_")
    try:
        maps_dir = os.path.join(tmp, "data", "maps")
        os.makedirs(os.path.join(maps_dir, "NoScriptMap"))
        # No scripts.inc created

        es_path = os.path.join(tmp, "data", "event_scripts.s")
        with open(es_path, "w") as f:
            f.write('\t.include "data/scripts/std.inc"\n')

        plan = MockPlan()
        plan.keep_maps = {"NoScriptMap"}

        report = PatchReport()
        _ensure_custom_map_scripts(tmp, plan, report)

        with open(es_path, "r") as f:
            es_content = f.read()

        _assert("bug4c: no-script map not included",
                'NoScriptMap' not in es_content,
                f"content: {es_content}")

    except Exception as e:
        _fail("Bug 4c: no-script map skipped", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # L. Guard clause inversion fix (Pass 1b)
    # ==========================================================

    # Test L1: Pattern A — single-line guard (bare return) → removed entirely
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return;\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("guard L1: single-line guard converted",
                "guard clause removed" in joined and "if (FALSE)" not in joined
                and "return;" in joined and count == 1,
                f"got: {joined!r}")
    except Exception as e:
        _fail("guard L1: single-line guard", str(e))

    # Test L2: Pattern B — guard with scorched comments between → removed entirely
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "     // Scorched: || gSaveBlock1Ptr->location.mapNum != MAP_NUM(MAP_ROUTE111)\n",
            "     // Scorched: || another_condition\n",
            "        return;\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("guard L2: guard with scorched comments",
                "guard clause removed" in joined and "if (FALSE)" not in joined
                and count == 1,
                f"got: {joined!r}")
    except Exception as e:
        _fail("guard L2: guard with scorched comments", str(e))

    # Test L3: Pattern C — guard returning a value (TRUE) → removed entirely
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return TRUE;\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("guard L3: return TRUE guard",
                "guard clause removed" in joined and "if (FALSE)" not in joined
                and "return TRUE;" not in joined and count == 1,
                f"got: {joined!r}")
    except Exception as e:
        _fail("guard L3: return TRUE guard", str(e))

    # Test L3b: Pattern C — guard returning 0 → removed entirely
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return 0;\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("guard L3b: return 0 guard",
                "guard clause removed" in joined and "if (FALSE)" not in joined
                and "return 0;" not in joined and count == 1,
                f"got: {joined!r}")
    except Exception as e:
        _fail("guard L3b: return 0 guard", str(e))

    # Test L4: Pattern D — guard with braces around bare return → removed entirely
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "    {\n",
            "        return;\n",
            "    }\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("guard L4: braced guard converted",
                "guard clause removed" in joined and "if (FALSE)" not in joined
                and "return;" in joined and count == 1,
                f"got: {joined!r}")
    except Exception as e:
        _fail("guard L4: braced guard", str(e))

    # Test L5 (negative): else if (FALSE) return; — should NOT be converted
    try:
        lines = [
            "    else if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return;\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("guard L5: else if NOT converted",
                "else if (FALSE)" in joined and count == 0,
                f"got: {joined!r}")
    except Exception as e:
        _fail("guard L5: else if not converted", str(e))

    # Test L6 (negative): if (FALSE) { x = 1; return; } — multiple stmts, NOT a guard
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "    {\n",
            "        x = 1;\n",
            "        return;\n",
            "    }\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("guard L6: multi-stmt block NOT converted",
                "if (FALSE)" in joined and count == 0,
                f"got: {joined!r}")
    except Exception as e:
        _fail("guard L6: multi-stmt block not converted", str(e))

    # Test L7 (negative): if (FALSE) do_something(); — not a return, NOT a guard
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        do_something();\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("guard L7: non-return NOT converted",
                "if (FALSE)" in joined and count == 0,
                f"got: {joined!r}")
    except Exception as e:
        _fail("guard L7: non-return not converted", str(e))

    # Test L8: guard with else branch — should NOT be converted
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return;\n",
            "    else\n",
            "        do_something();\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("guard L8: guard with else NOT converted",
                "if (FALSE)" in joined and count == 0,
                f"got: {joined!r}")
    except Exception as e:
        _fail("guard L8: guard with else not converted", str(e))

    # Test L9: braced guard returning value → removed entirely
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "    {\n",
            "        return FALSE;\n",
            "    }\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("guard L9: braced guard returning FALSE",
                "guard clause removed" in joined and "if (FALSE)" not in joined
                and "return FALSE;" not in joined and count == 1,
                f"got: {joined!r}")
    except Exception as e:
        _fail("guard L9: braced guard returning value", str(e))

    # ==========================================================
    # M. MAPSEC constant pattern building
    # ==========================================================

    from torch.scorch_patcher import _build_generic_const_pattern, _classify_vanilla_line

    # M-1: MAPSEC constants included in generic pattern
    try:
        plan = MockPlan()
        plan.vanilla_mapsecs = {"MAPSEC_LITTLEROOT_TOWN", "MAPSEC_OLDALE_TOWN"}
        pattern = _build_generic_const_pattern(plan)
        _assert("mapsec_pattern: pattern not None",
                pattern is not None,
                "expected a compiled pattern")
        _assert("mapsec_pattern: matches MAPSEC_LITTLEROOT_TOWN",
                pattern.search("case MAPSEC_LITTLEROOT_TOWN:") is not None,
                "expected match")
        _assert("mapsec_pattern: no match MAPSEC_SHIRUBE_TOWN",
                pattern.search("case MAPSEC_SHIRUBE_TOWN:") is None,
                "expected no match for custom MAPSEC")
    except Exception as e:
        _fail("MAPSEC pattern building", str(e))

    # M-2: Kanto range macros included when Kanto MAPSECs are vanilla
    try:
        plan = MockPlan()
        plan.vanilla_mapsecs = {
            "MAPSEC_PALLET_TOWN", "MAPSEC_SPECIAL_AREA",
            "MAPSEC_LITTLEROOT_TOWN",
        }
        pattern = _build_generic_const_pattern(plan)
        _assert("mapsec_kanto: KANTO_MAPSEC_COUNT matched",
                pattern.search("int x = KANTO_MAPSEC_COUNT;") is not None,
                "expected match for KANTO_MAPSEC_COUNT")
        _assert("mapsec_kanto: KANTO_MAPSEC_START matched",
                pattern.search("KANTO_MAPSEC_START") is not None,
                "expected match for KANTO_MAPSEC_START")
    except Exception as e:
        _fail("MAPSEC Kanto range macros", str(e))

    # M-3: Kanto macros NOT included if Kanto MAPSECs are not both vanilla
    try:
        plan = MockPlan()
        plan.vanilla_mapsecs = {"MAPSEC_PALLET_TOWN"}  # SPECIAL_AREA missing
        pattern = _build_generic_const_pattern(plan)
        _assert("mapsec_no_kanto: KANTO_MAPSEC_COUNT not matched",
                pattern.search("KANTO_MAPSEC_COUNT") is None,
                "expected no match")
    except Exception as e:
        _fail("MAPSEC Kanto range not included", str(e))

    # M-4: _classify_vanilla_line handles MAPSEC case labels
    try:
        action, _rep = _classify_vanilla_line(
            "    case MAPSEC_LITTLEROOT_TOWN:\n",
            "case MAPSEC_LITTLEROOT_TOWN:")
        _assert("classify: MAPSEC case label removed",
                action == "remove",
                f"got action={action!r}")
    except Exception as e:
        _fail("classify MAPSEC case label", str(e))

    # M-5: _classify_vanilla_line handles MAPSEC array initializer
    try:
        action, _rep = _classify_vanilla_line(
            "    [MAPSEC_LITTLEROOT_TOWN] = MAPPOPUP_THEME_WOOD,\n",
            "[MAPSEC_LITTLEROOT_TOWN] = MAPPOPUP_THEME_WOOD,")
        _assert("classify: MAPSEC array initializer removed",
                action == "remove",
                f"got action={action!r}")
    except Exception as e:
        _fail("classify MAPSEC array initializer", str(e))

    # M-6: Empty vanilla_mapsecs returns None (no pattern)
    try:
        plan = MockPlan()
        plan.vanilla_mapsecs = set()
        pattern = _build_generic_const_pattern(plan)
        _assert("mapsec_empty: no pattern when no vanilla consts",
                pattern is None,
                "expected None")
    except Exception as e:
        _fail("MAPSEC empty pattern", str(e))

    # ==========================================================
    # N. Bug 4a: _fix_unreachable_switch_stmts (Pass 5b)
    # ==========================================================

    # N-1: Orphaned bodies before first live case label
    try:
        lines = [
            "    switch (gMapHeader.regionMapSectionId) {\n",
            "        multi = TYPE_ROCK;\n",
            "        break;\n",
            "        multi = TYPE_FIGHTING;\n",
            "        break;\n",
            "    case MAPSEC_PETALBURG_CITY:\n",
            "        multi = TYPE_NORMAL;\n",
            "        break;\n",
            "    default:\n",
            "        multi = NUMBER_OF_MON_TYPES;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("N-1: orphaned stmts before first case scorched",
                "// Scorched: multi = TYPE_ROCK;" in joined
                and "// Scorched: break;" in joined
                and "// Scorched: multi = TYPE_FIGHTING;" in joined
                and count == 4,
                f"count={count}, got:\n{joined}")
        _assert("N-1: live case body preserved",
                "        multi = TYPE_NORMAL;\n" in joined
                and "    case MAPSEC_PETALBURG_CITY:\n" in joined,
                f"got:\n{joined}")
    except Exception as e:
        _fail("N-1: orphaned before first case", str(e))

    # N-2: Orphaned bodies between live cases (after break)
    try:
        lines = [
            "    switch (x) {\n",
            "    case LIVE_A:\n",
            "        do_a();\n",
            "        break;\n",
            "        orphan_stmt();\n",
            "        break;\n",
            "    case LIVE_B:\n",
            "        do_b();\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("N-2: orphaned stmts between cases scorched",
                "// Scorched: orphan_stmt();" in joined
                and "// Scorched: break;" in joined
                and count == 2,
                f"count={count}, got:\n{joined}")
        _assert("N-2: live case bodies preserved",
                "        do_a();\n" in joined
                and "        do_b();\n" in joined,
                f"got:\n{joined}")
    except Exception as e:
        _fail("N-2: orphaned between cases", str(e))

    # N-3: All case labels removed, only orphaned bodies + default
    try:
        lines = [
            "    switch (x) {\n",
            "        stmt_a();\n",
            "        break;\n",
            "        stmt_b();\n",
            "        break;\n",
            "    default:\n",
            "        do_default();\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("N-3: all orphaned bodies scorched before default",
                "// Scorched: stmt_a();" in joined
                and "// Scorched: stmt_b();" in joined
                and count == 4,
                f"count={count}, got:\n{joined}")
        _assert("N-3: default body preserved",
                "        do_default();\n" in joined,
                f"got:\n{joined}")
    except Exception as e:
        _fail("N-3: all cases removed, default survives", str(e))

    # N-4: Nested switch — inner switch cases NOT touched
    try:
        lines = [
            "    switch (outer) {\n",
            "    case OUTER_LIVE:\n",
            "        switch (inner) {\n",
            "        case INNER_A:\n",
            "            inner_stmt();\n",
            "            break;\n",
            "        }\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("N-4: nested switch internals untouched",
                count == 0
                and "inner_stmt();" in joined
                and "case INNER_A:" in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("N-4: nested switch untouched", str(e))

    # N-5: break and return both mark subsequent code unreachable
    try:
        lines = [
            "    switch (x) {\n",
            "    case LIVE_A:\n",
            "        do_a();\n",
            "        return 0;\n",
            "        orphan_after_return();\n",
            "    case LIVE_B:\n",
            "        do_b();\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("N-5: orphan after return scorched",
                "// Scorched: orphan_after_return();" in joined
                and count == 1,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("N-5: return marks unreachable", str(e))

    # N-6: Already-scorched lines are skipped
    try:
        lines = [
            "    switch (x) {\n",
            "        // Scorched: case MAPSEC_OLD:\n",
            "        // Scorched: multi = TYPE_ROCK;\n",
            "    case LIVE:\n",
            "        do_live();\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("N-6: already-scorched lines not double-scorched",
                count == 0
                and "// Scorched: case MAPSEC_OLD:" in joined
                and "// Scorched: multi = TYPE_ROCK;" in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("N-6: already-scorched skipped", str(e))

    # ==========================================================
    # O. Bug 4b: _fix_orphaned_block_bodies — scorched declarations
    # ==========================================================

    # O-1: Scorched static const array declaration with initializer body
    try:
        lines = [
            "// Scorched: static const u8 sMapSectionToThemeId[MAPSEC_COUNT - KANTO_MAPSEC_COUNT - 1] =\n",
            "{\n",
            "    [MAPSEC_LITTLEROOT_TOWN] = MAPPOPUP_THEME_WOOD,\n",
            "    [MAPSEC_OLDALE_TOWN] = MAPPOPUP_THEME_WOOD,\n",
            "};\n",
        ]
        result, count = _fix_orphaned_block_bodies(lines)
        joined = "".join(result)
        _assert("O-1: initializer body scorched",
                "// Scorched: {" in joined
                and "// Scorched: };" in joined
                and count >= 4,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("O-1: scorched array declaration", str(e))

    # O-2: Scorched const struct declaration
    try:
        lines = [
            "// Scorched: const struct MapData gRegionMap =\n",
            "{\n",
            "    .width = 10,\n",
            "    .height = 5,\n",
            "};\n",
        ]
        result, count = _fix_orphaned_block_bodies(lines)
        joined = "".join(result)
        _assert("O-2: struct initializer body scorched",
                "// Scorched: {" in joined
                and count >= 4,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("O-2: scorched struct declaration", str(e))

    # O-3: Scorched declaration NOT followed by brace (inline value) — no action
    try:
        lines = [
            "// Scorched: static const u8 sCount = MAPSEC_COUNT;\n",
            "void other_func(void) {\n",
            "}\n",
        ]
        result, count = _fix_orphaned_block_bodies(lines)
        joined = "".join(result)
        _assert("O-3: inline value not treated as block header",
                count == 0
                and "void other_func" in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("O-3: inline value no action", str(e))

    # O-4: Nested braces in initializer (struct of arrays)
    try:
        lines = [
            "// Scorched: static const struct MapLayout sLayouts[LAYOUT_COUNT] =\n",
            "{\n",
            "    {\n",
            "        .width = 10,\n",
            "        .tiles = { 1, 2, 3 },\n",
            "    },\n",
            "    {\n",
            "        .width = 20,\n",
            "    },\n",
            "};\n",
        ]
        result, count = _fix_orphaned_block_bodies(lines)
        joined = "".join(result)
        _assert("O-4: nested braces fully scorched",
                "// Scorched: {" in joined
                and "// Scorched: };" in joined
                and count >= 9,
                f"count={count}, got:\n{joined}")
        # Verify no un-scorched content lines remain
        for line in result:
            s = line.strip()
            if s and not s.startswith("//"):
                _fail("O-4: unscoched line remains", f"line: {s!r}")
                break
    except Exception as e:
        _fail("O-4: nested braces", str(e))

    # ==========================================================
    # P. Bug 4c: _fix_orphaned_block_bodies — scorched loop headers
    # ==========================================================

    # P-1: Scorched for-loop with brace body
    try:
        lines = [
            "// Scorched: for (mapSecId = MAPSEC_LITTLEROOT_TOWN; mapSecId <= MAPSEC_EVER_GRANDE_CITY; mapSecId++)\n",
            "{\n",
            "    GetMapSecDimensions(mapSecId, &x, &y, &width, &height);\n",
            "    DoSomething();\n",
            "}\n",
        ]
        result, count = _fix_orphaned_block_bodies(lines)
        joined = "".join(result)
        _assert("P-1: for-loop body scorched",
                "// Scorched: {" in joined
                and "// Scorched: GetMapSecDimensions" in joined
                and "// Scorched: }" in joined
                and count >= 4,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("P-1: scorched for-loop body", str(e))

    # P-2: Scorched while-loop with brace body
    try:
        lines = [
            "// Scorched: while (mapSecId < MAPSEC_COUNT)\n",
            "{\n",
            "    Process(mapSecId);\n",
            "    mapSecId++;\n",
            "}\n",
        ]
        result, count = _fix_orphaned_block_bodies(lines)
        joined = "".join(result)
        _assert("P-2: while-loop body scorched",
                "// Scorched: {" in joined
                and "// Scorched: Process(mapSecId);" in joined
                and count >= 4,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("P-2: scorched while-loop body", str(e))

    # P-3: Scorched for-loop with braceless body — already handled by Pass 7
    # Verify no double-action (Pass 6 should not fire since no '{' follows)
    try:
        lines = [
            "// Scorched: for (i = 0; i < MAPSEC_COUNT; i++)\n",
            "    DoSomething(i);\n",
        ]
        result, count = _fix_orphaned_block_bodies(lines)
        joined = "".join(result)
        _assert("P-3: braceless for body not double-scorched by Pass 6",
                count == 0
                and "    DoSomething(i);\n" in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("P-3: braceless for no double-action", str(e))

    # P-4: Original function signature pattern still works after refactor
    try:
        lines = [
            "// Scorched: static void DoVanillaSetup(void)\n",
            "{\n",
            "    LoadPalette(data, 0, 0x20);\n",
            "    SetupBg();\n",
            "}\n",
        ]
        result, count = _fix_orphaned_block_bodies(lines)
        joined = "".join(result)
        _assert("P-4: function signature body still scorched",
                "// Scorched: {" in joined
                and "// Scorched: LoadPalette" in joined
                and "// Scorched: }" in joined
                and count >= 4,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("P-4: function signature still works", str(e))

    # ==========================================================
    # Q. Bug 5a: _fix_trailing_operator_on_prev_line
    # ==========================================================

    # Q-1: Line ending with && followed by scorched continuation
    try:
        new_lines = [
            "        return (gSaveBlock1Ptr->location.mapGroup == cond->data.bytes[0] &&\n",
        ]
        _fix_trailing_operator_on_prev_line(new_lines)
        result = new_lines[0]
        _assert("Q-1: trailing && removed and expression closed",
                "&&" not in result
                and result.strip().endswith(");")
                and "cond->data.bytes[0]" in result,
                f"got: {result!r}")
    except Exception as e:
        _fail("Q-1: trailing && fix", str(e))

    # Q-2: Line ending with || followed by scorched continuation
    try:
        new_lines = [
            "        return (obj->currentMetatileBehavior == cond->data.bytes[0] ||\n",
        ]
        _fix_trailing_operator_on_prev_line(new_lines)
        result = new_lines[0]
        _assert("Q-2: trailing || removed and expression closed",
                "||" not in result
                and result.strip().endswith(");")
                and "cond->data.bytes[0]" in result,
                f"got: {result!r}")
    except Exception as e:
        _fail("Q-2: trailing || fix", str(e))

    # Q-3: Multi-level paren nesting
    try:
        new_lines = [
            "    return (a && (b ||\n",
        ]
        _fix_trailing_operator_on_prev_line(new_lines)
        result = new_lines[0]
        _assert("Q-3: multi-level parens balanced",
                "||" not in result
                and result.strip().endswith(");")
                and result.count(")") - result.count("(") == 0,
                f"got: {result!r}")
    except Exception as e:
        _fail("Q-3: multi-level paren nesting", str(e))

    # Q-4: Assignment expression (not return)
    try:
        new_lines = [
            "    x = (expr1 &&\n",
        ]
        _fix_trailing_operator_on_prev_line(new_lines)
        result = new_lines[0]
        _assert("Q-4: assignment closed with ;",
                "&&" not in result
                and result.strip().endswith(");"),
                f"got: {result!r}")
    except Exception as e:
        _fail("Q-4: assignment expression", str(e))

    # Q-5: No trailing operator — should not modify
    try:
        new_lines = [
            "    return (something);\n",
        ]
        _fix_trailing_operator_on_prev_line(new_lines)
        result = new_lines[0]
        _assert("Q-5: no trailing op, no modification",
                result == "    return (something);\n",
                f"got: {result!r}")
    except Exception as e:
        _fail("Q-5: no trailing op", str(e))

    # ==========================================================
    # R. Bug 5d: _is_conditional_stmt / unreachable switch fix
    # ==========================================================

    # R-1: Braceless if before return → conditional, NOT unreachable
    try:
        lines = [
            "    switch (collision)\n",
            "    {\n",
            "    case SOME_CASE:\n",
            "        if (condition)\n",
            "            return VALUE;\n",
            "        next_statement;\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R-1: stmt after braceless-if return NOT scorched",
                "next_statement;" in joined
                and "break;" in joined
                and "// Scorched" not in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R-1: braceless if return", str(e))

    # R-2: Braceless if before break → conditional, NOT unreachable
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "        if (cond)\n",
            "            break;\n",
            "        do_something();\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R-2: stmt after braceless-if break NOT scorched",
                "do_something();" in joined
                and "// Scorched" not in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R-2: braceless if break", str(e))

    # R-3: Unconditional return → subsequent stmts ARE scorched (existing behavior)
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "        return 0;\n",
            "        dead_code;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R-3: unconditional return scorches subsequent",
                "// Scorched: dead_code;" in joined and count == 1,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R-3: unconditional return", str(e))

    # R-4: else if before return → conditional
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "        else if (cond)\n",
            "            return 0;\n",
            "        next_stmt;\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R-4: else-if return is conditional",
                "next_stmt;" in joined and "// Scorched" not in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R-4: else if return conditional", str(e))

    # R-5: Multiple braceless-if-returns in sequence → none trigger false unreachable
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "        if (a)\n",
            "            return 1;\n",
            "        if (b)\n",
            "            return 2;\n",
            "        return 3;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R-5: multiple braceless-if returns, no false scorching",
                "return 1;" in joined
                and "return 2;" in joined
                and "return 3;" in joined
                and "// Scorched" not in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R-5: multiple braceless-if returns", str(e))

    # R-6: Braced if { return; } → inner_depth handles this (no regression)
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "        if (cond) {\n",
            "            return 0;\n",
            "        }\n",
            "        next_stmt;\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R-6: braced if return, inner_depth handles it",
                "next_stmt;" in joined and "// Scorched" not in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R-6: braced if return no regression", str(e))

    # ==========================================================
    # R2. Bug 6: Multi-line return reachability
    # ==========================================================

    # R2-1: _is_complete_statement unit tests
    try:
        _assert("R2-1a: break; is complete",
                _is_complete_statement("break;"),
                "break; should be complete")
        _assert("R2-1b: return; is complete",
                _is_complete_statement("return;"),
                "return; should be complete")
        _assert("R2-1c: return 0; is complete",
                _is_complete_statement("return 0;"),
                "return 0; should be complete")
        _assert("R2-1d: return (expr); is complete",
                _is_complete_statement("return (foo && bar);"),
                "return (foo && bar); should be complete")
        _assert("R2-1e: return (expr && is incomplete",
                not _is_complete_statement("return (gSaveBlock1Ptr->location.mapGroup == cond->data.bytes[0] &&"),
                "trailing && with unclosed paren should be incomplete")
        _assert("R2-1f: return (expr || is incomplete",
                not _is_complete_statement("return (obj->currentMetatileBehavior == cond->data.bytes[0] ||"),
                "trailing || with unclosed paren should be incomplete")
        _assert("R2-1g: return func( is incomplete",
                not _is_complete_statement("return func("),
                "unclosed paren should be incomplete")
        _assert("R2-1h: return (a, is incomplete",
                not _is_complete_statement("return (a,"),
                "unclosed paren with comma should be incomplete")
    except Exception as e:
        _fail("R2-1: _is_complete_statement unit tests", str(e))

    # R2-2: Multi-line return (&&) — continuation NOT scorched
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case MSG_COND_MAP:\n",
            "        return (gSaveBlock1Ptr->location.mapGroup == cond->data.bytes[0] &&\n",
            "                gSaveBlock1Ptr->location.mapNum == cond->data.bytes[1]);\n",
            "    case MSG_COND_ON_MB:\n",
            "        return obj->currentMetatileBehavior;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R2-2: continuation line preserved",
                "gSaveBlock1Ptr->location.mapNum" in joined
                and "// Scorched" not in joined
                and count == 0,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R2-2: multi-line return && continuation", str(e))

    # R2-3: Multi-line return (||) — continuation NOT scorched
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case MSG_COND_ON_MB:\n",
            "        return (obj->currentMetatileBehavior == cond->data.bytes[0] ||\n",
            "                obj->currentMetatileBehavior == cond->data.bytes[1]);\n",
            "    case NEXT:\n",
            "        return 0;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R2-3: || continuation preserved",
                "obj->currentMetatileBehavior == cond->data.bytes[1]" in joined
                and "// Scorched" not in joined
                and count == 0,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R2-3: multi-line return || continuation", str(e))

    # R2-4: Multi-line return (comma) — continuation NOT scorched
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "        return (a,\n",
            "                b);\n",
            "    case 2:\n",
            "        return 0;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R2-4: comma continuation preserved",
                "b);" in joined
                and "// Scorched" not in joined
                and count == 0,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R2-4: multi-line return comma continuation", str(e))

    # R2-5: Single-line return still triggers unreachable (regression check)
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "        return 0;\n",
            "        dead_code;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R2-5: single-line return still scorches dead code",
                "// Scorched: dead_code;" in joined and count == 1,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R2-5: single-line return regression", str(e))

    # R2-6: break; still triggers unreachable (regression check)
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "        do_a();\n",
            "        break;\n",
            "        orphan_stmt();\n",
            "    case 2:\n",
            "        do_b();\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R2-6: break still scorches orphaned stmt",
                "// Scorched: orphan_stmt();" in joined and count == 1,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R2-6: break regression", str(e))

    # R2-7: Conditional multi-line return — braceless if check still applies
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "        if (cond)\n",
            "            return (a &&\n",
            "                    b);\n",
            "        next_stmt;\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R2-7: conditional multi-line return, next_stmt preserved",
                "next_stmt;" in joined
                and "b);" in joined
                and "// Scorched" not in joined
                and count == 0,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R2-7: conditional multi-line return", str(e))

    # R2-8: return; (bare) still triggers unreachable
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "        return;\n",
            "        dead_code;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("R2-8: bare return; still marks unreachable",
                "// Scorched: dead_code;" in joined and count == 1,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("R2-8: bare return regression", str(e))

    # ==========================================================
    # S. Bug 5e: _split_evolution_entries / _handle_evolution_macro
    # ==========================================================

    # S-1: Split EVOLUTION entries — mixed vanilla and non-vanilla
    try:
        macro = (
            ".evolutions = EVOLUTION({EVO_LEVEL, 0, SPECIES_VIKAVOLT, "
            "CONDITIONS({IF_IN_MAPSEC, MAPSEC_NEW_MAUVILLE})}, "
            "{EVO_ITEM, ITEM_THUNDER_STONE, SPECIES_VIKAVOLT}, "
            "{EVO_NONE, 0, SPECIES_VIKAVOLT_TOTEM}),"
        )
        entries = _split_evolution_entries(macro)
        _assert("S-1: split returns 3 entries",
                len(entries) == 3,
                f"got {len(entries)}: {entries!r}")
        _assert("S-1: first entry has MAPSEC",
                "MAPSEC_NEW_MAUVILLE" in entries[0],
                f"entry[0]: {entries[0]!r}")
        _assert("S-1: second entry has EVO_ITEM",
                "EVO_ITEM" in entries[1],
                f"entry[1]: {entries[1]!r}")
    except Exception as e:
        _fail("S-1: split evolution entries", str(e))

    # S-2: handle_evolution_macro — 1 vanilla + 2 non-vanilla
    try:
        import re as _re
        pattern = _re.compile(r"\bMAPSEC_NEW_MAUVILLE\b")
        lines = [
            "        .evolutions = EVOLUTION({EVO_LEVEL, 0, SPECIES_VIKAVOLT, CONDITIONS({IF_IN_MAPSEC, MAPSEC_NEW_MAUVILLE})},\n",
            "                                {EVO_ITEM, ITEM_THUNDER_STONE, SPECIES_VIKAVOLT},\n",
            "                                {EVO_NONE, 0, SPECIES_VIKAVOLT_TOTEM}),\n",
        ]
        result = _handle_evolution_macro(lines, 0, pattern)
        _assert("S-2: result not None", result is not None, f"got None")
        evo_lines, consumed = result
        joined = "".join(evo_lines)
        _assert("S-2: vanilla entry removed, 2 kept",
                "EVO_ITEM" in joined
                and "EVO_NONE" in joined
                and "MAPSEC_NEW_MAUVILLE" not in joined
                and consumed == 2,
                f"consumed={consumed}, got:\n{joined}")
    except Exception as e:
        _fail("S-2: handle evolution macro mixed", str(e))

    # S-3: handle_evolution_macro — ALL vanilla → entire macro scorched
    try:
        pattern = _re.compile(r"\bMAPSEC_\w+\b")
        lines = [
            "        .evolutions = EVOLUTION({EVO_LEVEL, 0, SPECIES_X, CONDITIONS({IF_IN_MAPSEC, MAPSEC_ROUTE1})},\n",
            "                                {EVO_LEVEL, 0, SPECIES_Y, CONDITIONS({IF_IN_MAPSEC, MAPSEC_ROUTE2})}),\n",
        ]
        result = _handle_evolution_macro(lines, 0, pattern)
        _assert("S-3: result not None", result is not None, f"got None")
        evo_lines, consumed = result
        joined = "".join(evo_lines)
        _assert("S-3: all vanilla, all scorched",
                "// Scorched:" in joined
                and not any(l.strip().startswith(".evolutions") for l in evo_lines),
                f"consumed={consumed}, got:\n{joined}")
    except Exception as e:
        _fail("S-3: all vanilla evolution entries", str(e))

    # S-4: handle_evolution_macro — no vanilla entries → returns None (passthrough)
    try:
        pattern = _re.compile(r"\bMAPSEC_FAKE_NEVER_MATCH\b")
        lines = [
            "        .evolutions = EVOLUTION({EVO_ITEM, ITEM_X, SPECIES_A}),\n",
        ]
        result = _handle_evolution_macro(lines, 0, pattern)
        _assert("S-4: no vanilla entries, returns None",
                result is None,
                f"got: {result!r}")
    except Exception as e:
        _fail("S-4: no vanilla entries", str(e))

    # S-5: Single-line EVOLUTION macro with 1 vanilla + 1 non-vanilla
    try:
        pattern = _re.compile(r"\bMAPSEC_NEW_MAUVILLE\b")
        lines = [
            "        .evolutions = EVOLUTION({EVO_LEVEL, 0, SPECIES_X, CONDITIONS({IF_IN_MAPSEC, MAPSEC_NEW_MAUVILLE})}, {EVO_ITEM, ITEM_Y, SPECIES_Z}),\n",
        ]
        result = _handle_evolution_macro(lines, 0, pattern)
        _assert("S-5: result not None", result is not None, f"got None")
        evo_lines, consumed = result
        joined = "".join(evo_lines)
        _assert("S-5: single-line, vanilla removed, non-vanilla kept",
                "EVO_ITEM" in joined
                and "MAPSEC_NEW_MAUVILLE" not in joined
                and consumed == 0,
                f"consumed={consumed}, got:\n{joined}")
    except Exception as e:
        _fail("S-5: single-line evolution macro", str(e))

    # ==========================================================
    # T. Bug 5f: Guard clause chains — removal instead of conversion
    # ==========================================================

    # T-1: Single guard removed entirely (not converted to unconditional return)
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return PUZZLE_X;\n",
            "    return PUZZLE_NONE;\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("T-1: guard removed, fallback survives",
                "return PUZZLE_NONE;" in joined
                and "return PUZZLE_X;" not in joined
                and "guard clause removed" in joined
                and count == 1,
                f"got:\n{joined}")
    except Exception as e:
        _fail("T-1: single guard removal", str(e))

    # T-2: Multiple consecutive guards → all removed, fallback survives
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return PUZZLE_FORTREE;\n",
            "\n",
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return PUZZLE_TRICK_HOUSE;\n",
            "\n",
            "    return PUZZLE_NONE;\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("T-2: multiple guards removed, only fallback survives",
                "return PUZZLE_NONE;" in joined
                and "return PUZZLE_FORTREE;" not in joined
                and "return PUZZLE_TRICK_HOUSE;" not in joined
                and count == 2,
                f"got:\n{joined}")
    except Exception as e:
        _fail("T-2: multiple guards removed", str(e))

    # T-3: Guard with else branch → NOT treated as guard (existing behavior)
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return X;\n",
            "    else\n",
            "        do_something();\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("T-3: guard with else NOT removed",
                "if (FALSE)" in joined and count == 0,
                f"got:\n{joined}")
    except Exception as e:
        _fail("T-3: guard with else preserved", str(e))

    # T-4: Guard followed by fallback return → only fallback survives
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return FALSE;\n",
            "    return TRUE;\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("T-4: guard removed, fallback return TRUE survives",
                "return TRUE;" in joined
                and "return FALSE;" not in joined
                and count == 1,
                f"got:\n{joined}")
    except Exception as e:
        _fail("T-4: guard + fallback", str(e))

    # ==========================================================
    # U. _fix_braceless_scorched_bodies (Pass 7) — Bug 8
    # ==========================================================

    # U-1: Braceless else with scorched body followed by another scorched line
    # (Bug 8 case — was skipped because next line is not 'else' or '}')
    try:
        lines = [
            "        if (cond)\n",
            "            valid_stmt;\n",
            "        else\n",
            "            // Scorched: was_else_body;\n",
            "        // Scorched: was_next_stmt;\n",
            "    }\n",
        ]
        result, count = _fix_braceless_scorched_bodies(lines)
        joined = "".join(result)
        _assert("U-1: braceless else scorched body gets (void)0 when next is scorched",
                "(void)0; // Scorched: was_else_body;" in joined
                and count == 1,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("U-1: braceless else + scorched next", str(e))

    # U-2: Braceless if with scorched body followed by scorched line (not else)
    try:
        lines = [
            "    if (cond)\n",
            "        // Scorched: was_if_body;\n",
            "    // Scorched: was_next_stmt;\n",
            "    next_real_line;\n",
        ]
        result, count = _fix_braceless_scorched_bodies(lines)
        joined = "".join(result)
        _assert("U-2: braceless if scorched body gets (void)0 when next is scorched",
                "(void)0; // Scorched: was_if_body;" in joined
                and count == 1,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("U-2: braceless if + scorched next", str(e))

    # U-3: Braceless else with scorched body followed by '}' (existing behavior)
    try:
        lines = [
            "    if (cond)\n",
            "        valid_stmt;\n",
            "    else\n",
            "        // Scorched: was_else_body;\n",
            "    }\n",
        ]
        result, count = _fix_braceless_scorched_bodies(lines)
        joined = "".join(result)
        _assert("U-3: braceless else scorched body gets (void)0 before '}'",
                "(void)0; // Scorched: was_else_body;" in joined
                and count == 1,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("U-3: braceless else + closing brace", str(e))

    # U-4: map_name_popup.c exact failing case
    try:
        lines = [
            "        if (gMapHeader.weather == WEATHER_UNDERWATER_BUBBLES)\n",
            "            LoadPalette(&sMapPopUp_Palette_Underwater, BG_PLTT_ID(13), PLTT_SIZE_4BPP);\n",
            "        else\n",
            "            // Scorched: LoadPalette(sMapPopUp_PaletteTable[GetCurrentMapType()], BG_PLTT_ID(13), PLTT_SIZE_4BPP);\n",
            "        // Scorched: BlitBitmapToWindow(popupWindowId, sMapPopUp_Table[GetCurrentMapType()], 0, 0, 80, 24);\n",
            "    }\n",
        ]
        result, count = _fix_braceless_scorched_bodies(lines)
        joined = "".join(result)
        _assert("U-4: map_name_popup exact case — else body gets (void)0",
                "(void)0; // Scorched: LoadPalette(" in joined
                and count == 1,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("U-4: map_name_popup.c exact case", str(e))

    # U-5: Non-braceless scorched line should NOT get (void)0
    try:
        lines = [
            "    stmt_before;\n",
            "    // Scorched: some_call();\n",
            "    stmt_after;\n",
        ]
        result, count = _fix_braceless_scorched_bodies(lines)
        _assert("U-5: scorched line not in braceless body left alone",
                count == 0,
                f"count={count}")
    except Exception as e:
        _fail("U-5: non-braceless scorched", str(e))

    # V. _fix_braceless_scorched_bodies (Pass 7) — Bug 9
    # ==========================================================
    # Bug 9: Scorched condition continuations (|| / &&) should NOT get (void)0;

    # V-1: Scorched || continuation should NOT get (void)0
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        // Scorched: || (mapNum >= MAP_NUM(MAP_X))\n",
            "        return FACILITY_TOWER + 1;\n",
            "    else if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return FACILITY_DOME + 1;\n",
            "    else\n",
            "        return 0;\n",
        ]
        result, count = _fix_braceless_scorched_bodies(lines)
        joined = "".join(result)
        _assert("V-1: scorched || continuation NOT given (void)0",
                count == 0
                and "(void)0;" not in joined
                and "// Scorched: || (mapNum" in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("V-1: scorched || continuation", str(e))

    # V-2: Scorched && continuation should NOT get (void)0
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        // Scorched: && otherCond)\n",
            "        doSomething();\n",
        ]
        result, count = _fix_braceless_scorched_bodies(lines)
        joined = "".join(result)
        _assert("V-2: scorched && continuation NOT given (void)0",
                count == 0
                and "(void)0;" not in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("V-2: scorched && continuation", str(e))

    # V-3: Actual scorched body (not continuation) still gets (void)0
    try:
        lines = [
            "    if (cond)\n",
            "        // Scorched: doSomething();\n",
            "    else\n",
            "        doOther();\n",
        ]
        result, count = _fix_braceless_scorched_bodies(lines)
        joined = "".join(result)
        _assert("V-3: actual scorched body still gets (void)0",
                count == 1
                and "(void)0; // Scorched: doSomething();" in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("V-3: actual scorched body preserved", str(e))

    # V-4: Multiple consecutive continuations before the body
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        // Scorched: || condB\n",
            "        // Scorched: || condC)\n",
            "        return VALUE;\n",
        ]
        result, count = _fix_braceless_scorched_bodies(lines)
        joined = "".join(result)
        _assert("V-4: multiple continuations none get (void)0",
                count == 0
                and "(void)0;" not in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("V-4: multiple continuations", str(e))

    # V-5: frontier_pass.c exact pattern — full if/else-if chain with continuations
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        // Scorched: || (mapNum >= MAP_NUM(MAP_BATTLE_FRONTIER_BATTLE_TOWER_MULTI_PARTNER_ROOM)\n",
            "        // Scorched: && mapNum <= MAP_NUM(MAP_BATTLE_FRONTIER_BATTLE_TOWER_MULTI_BATTLE_ROOM)))\n",
            "        return FRONTIER_FACILITY_TOWER + 1;\n",
            "    else if (FALSE)  // Scorched: vanilla ref removed\n",
            "        // Scorched: || (mapNum >= MAP_NUM(MAP_BATTLE_FRONTIER_BATTLE_DOME_PRE_BATTLE_ROOM)\n",
            "        // Scorched: && mapNum <= MAP_NUM(MAP_BATTLE_FRONTIER_BATTLE_DOME_BATTLE_ROOM)))\n",
            "        return FRONTIER_FACILITY_DOME + 1;\n",
            "    else\n",
            "        return 0;\n",
        ]
        result, count = _fix_braceless_scorched_bodies(lines)
        joined = "".join(result)
        _assert("V-5: frontier_pass.c exact pattern — no (void)0 on continuations",
                count == 0
                and "(void)0;" not in joined
                and "else if" in joined
                and "else\n" in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("V-5: frontier_pass.c exact pattern", str(e))

    # W. Inline brace tracking (Bug 10)
    # Bug 10: Pass 4/5/5b fail on inline {} (compact for loops) — the {}
    # triggers a pop without a push, throwing off brace depth tracking.

    # W-1: Pass 5 — inline {} inside switch case should NOT break depth tracking
    try:
        lines = [
            "    switch (field)\n",
            "    {\n",
            "    case MON_DATA_NICKNAME:\n",
            "    {\n",
            "        for (i = 0; i < LEN && arr[i] != EOS;\n",
            "            data[i] = arr[i], i++) {}\n",
            "        data[i] = EOS;\n",
            "        break;\n",
            "    }\n",
            "    case MON_DATA_SPECIES:\n",
            "        retVal = GetSpecies();\n",
            "        break;\n",
            "    case MON_DATA_HELD_ITEM:\n",
            "        retVal = GetItem();\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_orphaned_switch_cases(lines)
        joined = "".join(result)
        _assert("W-1: inline {} does not break switch depth in Pass 5",
                count == 0
                and "// Scorched: case MON_DATA_SPECIES:" not in joined
                and "// Scorched: case MON_DATA_HELD_ITEM:" not in joined
                and "case MON_DATA_SPECIES:" in joined
                and "case MON_DATA_HELD_ITEM:" in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("W-1: inline {} pass 5", str(e))

    # W-2: Pass 5 — multiple inline {} inside one case block
    try:
        lines = [
            "    switch (x)\n",
            "    {\n",
            "    case 1:\n",
            "    {\n",
            "        for (a = 0; a < N; a++) {}\n",
            "        for (b = 0; b < M; b++) {}\n",
            "        break;\n",
            "    }\n",
            "    case 2:\n",
            "        doSomething();\n",
            "        break;\n",
            "    default:\n",
            "        doDefault();\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_orphaned_switch_cases(lines)
        joined = "".join(result)
        _assert("W-2: double inline {} does not break switch depth",
                count == 0
                and "case 2:" in joined
                and "default:" in joined
                and "// Scorched" not in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("W-2: double inline {}", str(e))

    # W-3: Pass 4 — inline {} inside a loop doesn't break loop depth
    try:
        lines = [
            "    for (int i = 0; i < n; i++)\n",
            "    {\n",
            "        for (int j = 0; j < m; data[j] = src[j], j++) {}\n",
            "        if (done) continue;\n",
            "        process();\n",
            "    }\n",
        ]
        result, count = _fix_orphaned_loop_stmts(lines)
        joined = "".join(result)
        _assert("W-3: inline {} inside loop preserves continue",
                count == 0
                and "// Scorched" not in joined
                and "continue;" in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("W-3: inline {} pass 4", str(e))

    # W-4: Pass 5 — pokemon.c exact pattern: GetBoxMonData3 with nickname handler
    try:
        lines = [
            "    switch (field)\n",
            "    {\n",
            "    case MON_DATA_NICKNAME:\n",
            "    case MON_DATA_NICKNAME10:\n",
            "    {\n",
            "        if (IsBadEgg(boxMon))\n",
            "        {\n",
            "            for (retVal = 0;\n",
            "                retVal < POKEMON_NAME_LENGTH && gText_BadEgg[retVal] != EOS;\n",
            "                data[retVal] = gText_BadEgg[retVal], retVal++) {}\n",
            "            data[retVal] = EOS;\n",
            "        }\n",
            "        else\n",
            "        {\n",
            "            retVal = 0;\n",
            "            while (retVal < 10)\n",
            "            {\n",
            "                data[retVal] = boxMon->nickname[retVal];\n",
            "                retVal++;\n",
            "            }\n",
            "            data[retVal] = EOS;\n",
            "        }\n",
            "        break;\n",
            "    }\n",
            "    case MON_DATA_SPECIES:\n",
            "        retVal = GetSubstruct0(boxMon)->species;\n",
            "        break;\n",
            "    case MON_DATA_HELD_ITEM:\n",
            "        retVal = GetSubstruct0(boxMon)->heldItem;\n",
            "        break;\n",
            "    case MON_DATA_EXP:\n",
            "        retVal = GetSubstruct0(boxMon)->experience;\n",
            "        break;\n",
            "    default:\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_orphaned_switch_cases(lines)
        joined = "".join(result)
        _assert("W-4: pokemon.c GetBoxMonData3 exact pattern",
                count == 0
                and "case MON_DATA_SPECIES:" in joined
                and "case MON_DATA_HELD_ITEM:" in joined
                and "case MON_DATA_EXP:" in joined
                and "default:" in joined
                and "// Scorched" not in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("W-4: pokemon.c exact pattern", str(e))

    # W-5: Pass 5b — inline {} doesn't break unreachable tracking
    try:
        lines = [
            "    switch (field)\n",
            "    {\n",
            "    case LABEL_A:\n",
            "    {\n",
            "        for (i = 0; i < N; data[i] = src[i], i++) {}\n",
            "        break;\n",
            "    }\n",
            "    case LABEL_B:\n",
            "        doB();\n",
            "        break;\n",
            "    }\n",
        ]
        result, count = _fix_unreachable_switch_stmts(lines)
        joined = "".join(result)
        _assert("W-5: Pass 5b inline {} preserves reachable cases",
                count == 0
                and "case LABEL_B:" in joined
                and "doB();" in joined
                and "// Scorched" not in joined,
                f"count={count}, got:\n{joined}")
    except Exception as e:
        _fail("W-5: pass 5b inline {}", str(e))

    # W-6: _count_line_braces correctly counts inline {}
    try:
        o, c = _count_line_braces("data[i] = arr[i], i++) {}")
        _assert("W-6a: inline {} counts (1,1)",
                o == 1 and c == 1,
                f"got ({o},{c})")
        o, c = _count_line_braces("switch (x) {")
        _assert("W-6b: switch header counts (1,0)",
                o == 1 and c == 0,
                f"got ({o},{c})")
        o, c = _count_line_braces("}")
        _assert("W-6c: lone } counts (0,1)",
                o == 0 and c == 1,
                f"got ({o},{c})")
        o, c = _count_line_braces("if (x) { foo(); } else { bar(); }")
        _assert("W-6d: multi-brace line counts (2,2)",
                o == 2 and c == 2,
                f"got ({o},{c})")
        o, c = _count_line_braces('char *s = "{}";  // not real braces')
        _assert("W-6e: braces in string literal ignored",
                o == 0 and c == 0,
                f"got ({o},{c})")
    except Exception as e:
        _fail("W-6: _count_line_braces", str(e))

    # X. Guard clause void return stubbing (Bug 11)
    # Bug 11: void guard clauses (return;) should keep the return to stub
    # the function. Value guard clauses (return 0;) should still remove it.

    # X-1: void guard — return; kept to stub the function
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return;\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("X-1: void guard keeps return;",
                "guard clause removed" in joined
                and "return;" in joined
                and "if (FALSE)" not in joined
                and count == 1,
                f"got: {joined!r}")
    except Exception as e:
        _fail("X-1: void guard", str(e))

    # X-2: value guard — return 0; removed (fallback return survives)
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "        return 0;\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("X-2: value guard removes return",
                "guard clause removed" in joined
                and "return 0;" not in joined
                and count == 1,
                f"got: {joined!r}")
    except Exception as e:
        _fail("X-2: value guard", str(e))

    # X-3: braced void guard — return; kept
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "    {\n",
            "        return;\n",
            "    }\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("X-3: braced void guard keeps return;",
                "guard clause removed" in joined
                and "return;" in joined
                and "if (FALSE)" not in joined
                and count == 1,
                f"got: {joined!r}")
    except Exception as e:
        _fail("X-3: braced void guard", str(e))

    # X-4: mirage tower exact pattern — multi-condition void guard stubbed
    try:
        lines = [
            "    if (FALSE)  // Scorched: vanilla ref removed\n",
            "     // Scorched: || gSaveBlock1Ptr->location.mapNum != MAP_NUM(MAP_ROUTE111)\n",
            "     // Scorched: || !FlagGet(FLAG_MIRAGE_TOWER_VISIBLE)\n",
            "        return;\n",
            "\n",
            "    sMirageTowerPulseBlend = AllocZeroed(sizeof(*sMirageTowerPulseBlend));\n",
        ]
        result, count = _fix_guard_clause_inversions(lines)
        joined = "".join(result)
        _assert("X-4: mirage tower pattern — function stubbed with return;",
                "guard clause removed" in joined
                and "return;" in joined
                and "if (FALSE)" not in joined
                and "AllocZeroed" in joined  # body is still there (Pass 1b doesn't touch it)
                and count == 1,
                f"got: {joined!r}")
    except Exception as e:
        _fail("X-4: mirage tower pattern", str(e))

    # ==========================================================
    # Y. Overworld config patch (Union Room disable)

    try:
        tmp = tempfile.mkdtemp()
        cfg_dir = os.path.join(tmp, "include", "config")
        os.makedirs(cfg_dir)
        ow_path = os.path.join(cfg_dir, "overworld.h")

        # Test 1: FALSE -> TRUE
        with open(ow_path, "w") as f:
            f.write('#define OW_UNION_DISABLE_CHECK           FALSE\n')
        plan = MockPlan()
        report = PatchReport()
        _patch_overworld_config(tmp, plan, report)
        with open(ow_path) as f:
            result = f.read()
        _assert("overworld_config: union check set to TRUE",
                "TRUE" in result and "FALSE" not in result,
                f"got: {result!r}")
        _assert("overworld_config: report recorded",
                len(report.patches) == 1,
                f"patches: {report.patches}")

        # Test 2: already TRUE (idempotent)
        report2 = PatchReport()
        _patch_overworld_config(tmp, plan, report2)
        _assert("overworld_config: idempotent — no double patch",
                len(report2.patches) == 0,
                f"patches: {report2.patches}")

        # Test 3: missing file (no crash)
        report3 = PatchReport()
        os.remove(ow_path)
        _patch_overworld_config(tmp, plan, report3)
        _assert("overworld_config: missing file no crash",
                len(report3.patches) == 0,
                "should silently skip")

        shutil.rmtree(tmp)
    except Exception as e:
        _fail("overworld_config", str(e))
