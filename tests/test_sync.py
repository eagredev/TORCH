"""Sync engine suite -- tests pure-logic functions in sync.py."""
import os
import sys
import tempfile
import shutil
import json
import zipfile
import time

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert, _fixture


def run_suite():
    _begin_suite("Sync Engine")

    try:
        from torch.sync import (
            get_workspace_files, create_snapshot,
            _validate_labels, _validate_constants, _run_map_guard,
        )
    except ImportError as e:
        _skip("all sync tests", f"import failed: {e}")
        return

    # Need to clear gamedata cache between tests to avoid stale reads
    from torch.gamedata import clear_gamedata_cache

    # ===================================================================
    # A. get_workspace_files  (~3 assertions)
    # ===================================================================

    tmp = tempfile.mkdtemp(prefix="torch_sync_test_")
    try:
        # Create test files
        for fname in ["scene1.txt", "setup.pory", "notes.json", "backup.bak", "battle.txt"]:
            with open(os.path.join(tmp, fname), "w") as f:
                f.write("test")

        # Create a backups/ subfolder with files that should be excluded
        bkdir = os.path.join(tmp, "backups")
        os.makedirs(bkdir)
        with open(os.path.join(bkdir, "old.txt"), "w") as f:
            f.write("backup")

        result = get_workspace_files(tmp)

        _assert(
            "get_workspace_files: returns only .txt and .pory",
            set(result) == {"battle.txt", "scene1.txt", "setup.pory"},
            f"expected 3 source files, got {result}"
        )

        _assert(
            "get_workspace_files: excludes non-source files",
            "notes.json" not in result and "backup.bak" not in result,
            f"non-source files found in result: {result}"
        )

        _assert(
            "get_workspace_files: results sorted alphabetically",
            result == sorted(result),
            f"not sorted: {result}"
        )
    except Exception as e:
        _fail("get_workspace_files", str(e))
    finally:
        shutil.rmtree(tmp)

    # ===================================================================
    # B. create_snapshot  (~6 assertions)
    # ===================================================================

    tmp = tempfile.mkdtemp(prefix="torch_sync_test_")
    try:
        src = os.path.join(tmp, "source")
        snaps = os.path.join(tmp, "snapshots")
        os.makedirs(src)

        # Create source files
        for fname in ["setup.pory", "scene1.txt"]:
            with open(os.path.join(src, fname), "w") as f:
                f.write(f"content of {fname}")

        # Test basic snapshot creation
        result = create_snapshot(src, snaps, "TestMap")

        _assert(
            "create_snapshot: returns filename string",
            isinstance(result, str) and result.endswith(".zip"),
            f"expected zip filename, got {result}"
        )

        _assert(
            "create_snapshot: filename contains map name",
            "TestMap" in result,
            f"map name not in filename: {result}"
        )

        zip_path = os.path.join(snaps, result)
        _assert(
            "create_snapshot: ZIP file exists",
            os.path.exists(zip_path),
            f"zip not found at {zip_path}"
        )

        # Verify ZIP contents
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = sorted(zf.namelist())
        _assert(
            "create_snapshot: ZIP contains source files",
            names == ["scene1.txt", "setup.pory"],
            f"expected [scene1.txt, setup.pory], got {names}"
        )

        # Test pruning: create max_snapshots+1 snapshots
        max_s = 3
        for i in range(max_s + 2):
            time.sleep(0.01)  # ensure unique timestamps
            create_snapshot(src, snaps, "PruneMap", max_snapshots=max_s)

        prune_zips = [f for f in os.listdir(snaps)
                      if f.startswith("PruneMap_") and f.endswith(".zip")]
        _assert(
            "create_snapshot: prunes to max_snapshots",
            len(prune_zips) <= max_s,
            f"expected <= {max_s} snapshots, found {len(prune_zips)}"
        )

        # Test empty source dir
        empty_src = os.path.join(tmp, "empty")
        os.makedirs(empty_src)
        empty_result = create_snapshot(empty_src, snaps, "EmptyMap")
        # Should create a ZIP (possibly empty) or handle gracefully
        _assert(
            "create_snapshot: handles empty source dir",
            empty_result is not None,
            "returned None for empty source dir"
        )

    except Exception as e:
        _fail("create_snapshot", str(e))
    finally:
        shutil.rmtree(tmp)

    # ===================================================================
    # C. _validate_labels  (~8 assertions)
    # ===================================================================

    try:
        # regions is a list of (name, content, had_errors) tuples

        # Test 1: defined label, no warnings
        assembled = "script MyScript {\n    goto(MyScript)\n}\n"
        regions = [("test", "goto(MyScript)", False)]
        warnings = _validate_labels(assembled, regions)
        _assert(
            "validate_labels: defined goto target = 0 warnings",
            len(warnings) == 0,
            f"expected 0 warnings, got {len(warnings)}: {warnings}"
        )

        # Test 2: undefined goto target
        assembled = "script DefinedScript {\n    goto(MissingLabel)\n}\n"
        regions = [("test", "goto(MissingLabel)", False)]
        warnings = _validate_labels(assembled, regions)
        _assert(
            "validate_labels: undefined goto = 1 warning",
            len(warnings) == 1 and "MissingLabel" in warnings[0],
            f"expected 1 warning about MissingLabel, got {warnings}"
        )

        # Test 3: undefined call target
        assembled = "script Main {\n    call(MissingCall)\n}\n"
        regions = [("test", "call(MissingCall)", False)]
        warnings = _validate_labels(assembled, regions)
        _assert(
            "validate_labels: undefined call = warning",
            len(warnings) == 1 and "MissingCall" in warnings[0],
            f"expected warning about MissingCall, got {warnings}"
        )

        # Test 4: trainerbattle with defined defeat text
        assembled = (
            "script BattleScript {\n"
            "    trainerbattle_single(TRAINER_FOO, IntroText, DefeatText)\n"
            "}\n"
            "text IntroText {\n}\n"
            "text DefeatText {\n}\n"
        )
        regions = [("test", "trainerbattle_single(TRAINER_FOO, IntroText, DefeatText)", False)]
        warnings = _validate_labels(assembled, regions)
        _assert(
            "validate_labels: trainerbattle with defined labels = 0 warnings",
            len(warnings) == 0,
            f"expected 0 warnings, got {warnings}"
        )

        # Test 5: trainerbattle with undefined defeat text
        assembled = (
            "script BattleScript {\n"
            "    trainerbattle_single(TRAINER_FOO, IntroText2, MissingDefeat)\n"
            "}\n"
            "text IntroText2 {\n}\n"
        )
        regions = [("test", "trainerbattle_single(TRAINER_FOO, IntroText2, MissingDefeat)", False)]
        warnings = _validate_labels(assembled, regions)
        _assert(
            "validate_labels: trainerbattle missing defeat text = warning",
            any("MissingDefeat" in w for w in warnings),
            f"expected warning about MissingDefeat, got {warnings}"
        )

        # Test 6: movement label defined and referenced
        assembled = (
            "script WalkScript {\n"
            "    applymovement(OBJ_EVENT_ID_PLAYER, WalkUp)\n"
            "}\n"
            "movement WalkUp {\n}\n"
        )
        regions = [("test", "applymovement(OBJ_EVENT_ID_PLAYER, WalkUp)", False)]
        warnings = _validate_labels(assembled, regions)
        _assert(
            "validate_labels: defined movement label = 0 warnings",
            len(warnings) == 0,
            f"expected 0 warnings, got {warnings}"
        )

        # Test 7: empty assembled text
        warnings = _validate_labels("", [])
        _assert(
            "validate_labels: empty text = 0 warnings, no crash",
            len(warnings) == 0,
            f"expected 0 warnings, got {warnings}"
        )

        # Test 8: script block labels are recognized as definitions
        assembled = (
            "script CheckLabel {\n"
            "    goto(CheckLabel)\n"
            "}\n"
        )
        regions = [("test", "goto(CheckLabel)", False)]
        warnings = _validate_labels(assembled, regions)
        _assert(
            "validate_labels: script block label recognized as definition",
            len(warnings) == 0,
            f"expected 0 warnings, got {warnings}"
        )

    except Exception as e:
        _fail("validate_labels", str(e))

    # ===================================================================
    # D. _validate_constants  (~6 assertions)
    # ===================================================================

    tmp = tempfile.mkdtemp(prefix="torch_sync_test_")
    try:
        clear_gamedata_cache()

        # Build a minimal game directory with header files
        game = os.path.join(tmp, "game")
        const_dir = os.path.join(game, "include", "constants")
        data_dir = os.path.join(game, "data")
        os.makedirs(const_dir)
        os.makedirs(data_dir)

        with open(os.path.join(const_dir, "flags.h"), "w") as f:
            f.write("#define FLAG_BADGE1 0x001\n")
            f.write("#define FLAG_VISITED_TOWN 0x002\n")

        with open(os.path.join(const_dir, "vars.h"), "w") as f:
            f.write("#define VAR_QUEST_STATE 0x4000\n")

        with open(os.path.join(const_dir, "opponents.h"), "w") as f:
            f.write("#define TRAINER_RIVAL_1 0\n")
            f.write("#define TRAINER_GRUNT_1 1\n")

        # Create empty stubs for other headers so loaders don't return empty
        for hdr in ["songs.h", "sound.h", "species.h"]:
            with open(os.path.join(const_dir, hdr), "w") as f:
                f.write("")

        with open(os.path.join(data_dir, "specials.inc"), "w") as f:
            f.write("")

        # Test 1: known flag
        assembled = "setflag(FLAG_BADGE1)"
        warnings = _validate_constants(assembled, game)
        _assert(
            "validate_constants: known FLAG = 0 warnings",
            len(warnings) == 0,
            f"expected 0 warnings, got {warnings}"
        )

        clear_gamedata_cache()

        # Test 2: unknown flag
        assembled = "setflag(FLAG_NONEXISTENT)"
        warnings = _validate_constants(assembled, game)
        _assert(
            "validate_constants: unknown FLAG = 1 warning",
            len(warnings) == 1 and "FLAG_NONEXISTENT" in warnings[0],
            f"expected 1 warning about FLAG_NONEXISTENT, got {warnings}"
        )

        clear_gamedata_cache()

        # Test 3: known var
        assembled = "setvar(VAR_QUEST_STATE, 1)"
        warnings = _validate_constants(assembled, game)
        _assert(
            "validate_constants: known VAR = 0 warnings",
            len(warnings) == 0,
            f"expected 0 warnings, got {warnings}"
        )

        clear_gamedata_cache()

        # Test 4: unknown var
        assembled = "compare(VAR_MISSING, 5)"
        warnings = _validate_constants(assembled, game)
        _assert(
            "validate_constants: unknown VAR = 1 warning",
            len(warnings) == 1 and "VAR_MISSING" in warnings[0],
            f"expected 1 warning about VAR_MISSING, got {warnings}"
        )

        clear_gamedata_cache()

        # Test 5: known trainer
        assembled = "trainerbattle_single(TRAINER_RIVAL_1, Intro, Defeat)"
        warnings = _validate_constants(assembled, game)
        _assert(
            "validate_constants: known TRAINER = 0 warnings",
            len(warnings) == 0,
            f"expected 0 warnings, got {warnings}"
        )

        clear_gamedata_cache()

        # Test 6: unknown trainer
        assembled = "trainerbattle_single(TRAINER_UNKNOWN_GUY, Intro, Defeat)"
        warnings = _validate_constants(assembled, game)
        _assert(
            "validate_constants: unknown TRAINER = 1 warning",
            len(warnings) == 1 and "TRAINER_UNKNOWN_GUY" in warnings[0],
            f"expected 1 warning about TRAINER_UNKNOWN_GUY, got {warnings}"
        )

    except Exception as e:
        _fail("validate_constants", str(e))
    finally:
        clear_gamedata_cache()
        shutil.rmtree(tmp)

    # ===================================================================
    # E. _run_map_guard  (~7 assertions)
    # ===================================================================

    # --- Bug 1: "id" -> "map_section" rename ---
    tmp = tempfile.mkdtemp(prefix="torch_sync_test_")
    try:
        game = os.path.join(tmp, "game")
        rm_dir = os.path.join(game, "src", "data", "region_map")
        maps_dir = os.path.join(game, "data", "maps")
        os.makedirs(rm_dir)
        os.makedirs(maps_dir)

        # Write JSON with the buggy "id" key
        buggy_data = {
            "map_sections": [
                {"id": "MAPSEC_LITTLEROOT_TOWN", "name": "LITTLEROOT TOWN", "x": 0, "y": 0, "width": 1, "height": 1}
            ]
        }
        rm_file = os.path.join(rm_dir, "region_map_sections.json")
        with open(rm_file, "w") as f:
            json.dump(buggy_data, f)

        fixes = _run_map_guard(game)

        with open(rm_file, "r") as f:
            content = f.read()

        _assert(
            "map_guard bug1: 'id' renamed to 'map_section'",
            '"map_section":' in content and '"id":' not in content,
            f"expected 'map_section' key, got: {content[:200]}"
        )

        _assert(
            "map_guard bug1: fixes count >= 1",
            fixes >= 1,
            f"expected fixes >= 1, got {fixes}"
        )

    except Exception as e:
        _fail("map_guard bug1", str(e))
    finally:
        shutil.rmtree(tmp)

    # --- Bug 2: Missing "name" fields ---
    tmp = tempfile.mkdtemp(prefix="torch_sync_test_")
    try:
        game = os.path.join(tmp, "game")
        rm_dir = os.path.join(game, "src", "data", "region_map")
        maps_dir = os.path.join(game, "data", "maps")
        os.makedirs(rm_dir)
        os.makedirs(maps_dir)

        # Write JSON with missing "name" field
        data = {
            "map_sections": [
                {"map_section": "MAPSEC_ROUTE_101", "x": 0, "y": 0, "width": 1, "height": 1}
            ]
        }
        rm_file = os.path.join(rm_dir, "region_map_sections.json")
        with open(rm_file, "w") as f:
            json.dump(data, f)

        fixes = _run_map_guard(game)

        with open(rm_file, "r") as f:
            result_data = json.load(f)

        entry = result_data["map_sections"][0]
        _assert(
            "map_guard bug2: 'name' field added",
            "name" in entry,
            f"expected 'name' key in entry, got {entry}"
        )

        _assert(
            "map_guard bug2: fixes count >= 1",
            fixes >= 1,
            f"expected fixes >= 1, got {fixes}"
        )

    except Exception as e:
        _fail("map_guard bug2", str(e))
    finally:
        shutil.rmtree(tmp)

    # --- Bug 3: Mapsec assignment restoration ---
    # Simulates Porymap resetting a custom map's region_map_section to
    # MAPSEC_NONE.  Map Guard's per-project backup (with the correct
    # assignment from a previous run) should restore it.
    tmp = tempfile.mkdtemp(prefix="torch_sync_test_")
    try:
        game = os.path.join(tmp, "game")
        maps_dir = os.path.join(game, "data", "maps", "TestMap")
        os.makedirs(maps_dir)

        # Create a map.json with the wrong mapsec (Porymap reset it)
        map_json = os.path.join(maps_dir, "map.json")
        with open(map_json, "w") as f:
            json.dump({"region_map_section": "MAPSEC_NONE"}, f)

        # Create the per-project backup with the correct assignment
        # (established by a previous Map Guard run before corruption)
        backup_dir = os.path.join(game, ".torch", "mapsec_backup")
        os.makedirs(backup_dir)
        with open(os.path.join(backup_dir, "mapsecs.json"), "w") as f:
            json.dump({"TestMap": "MAPSEC_CUSTOM_TOWN"}, f)

        fixes = _run_map_guard(game)

        with open(map_json, "r") as f:
            result = json.load(f)

        _assert(
            "map_guard bug3: mapsec restored from backup",
            result.get("region_map_section") == "MAPSEC_CUSTOM_TOWN",
            f"expected MAPSEC_CUSTOM_TOWN, got {result.get('region_map_section')}"
        )

        _assert(
            "map_guard bug3: fixes count >= 1",
            fixes >= 1,
            f"expected fixes >= 1, got {fixes}"
        )

    except Exception as e:
        _fail("map_guard bug3", str(e))
    finally:
        shutil.rmtree(tmp)

    # --- Clean game dir (no bugs) ---
    # Map Guard reads from ~/map_mapsec_backup/ (hardcoded paths for
    # custom_mapsecs.json and mapsecs.json). Temporarily hide the whole
    # directory so it doesn't interfere with the clean/missing tests.
    _real_backup_dir = os.path.expanduser("~/map_mapsec_backup")
    _real_backup_hidden = _real_backup_dir + "_test_hide"
    _hid_backup_dir = False
    if os.path.isdir(_real_backup_dir):
        os.rename(_real_backup_dir, _real_backup_hidden)
        _hid_backup_dir = True

    tmp = tempfile.mkdtemp(prefix="torch_sync_test_")
    try:
        game = os.path.join(tmp, "game")
        rm_dir = os.path.join(game, "src", "data", "region_map")
        maps_dir = os.path.join(game, "data", "maps")
        os.makedirs(rm_dir)
        os.makedirs(maps_dir)

        clean_data = {
            "map_sections": [
                {"map_section": "MAPSEC_ROUTE_101", "name": "ROUTE 101", "x": 0, "y": 0}
            ]
        }
        rm_file = os.path.join(rm_dir, "region_map_sections.json")
        with open(rm_file, "w") as f:
            json.dump(clean_data, f)

        fixes = _run_map_guard(game)
        _assert(
            "map_guard clean: no bugs = 0 fixes",
            fixes == 0,
            f"expected 0 fixes on clean data, got {fixes}"
        )

    except Exception as e:
        _fail("map_guard clean", str(e))
    finally:
        shutil.rmtree(tmp)

    # --- Missing region_map file ---
    tmp = tempfile.mkdtemp(prefix="torch_sync_test_")
    try:
        game = os.path.join(tmp, "game")
        os.makedirs(game)

        fixes = _run_map_guard(game)
        _assert(
            "map_guard missing file: no crash, 0 fixes",
            fixes == 0,
            f"expected 0 fixes when file missing, got {fixes}"
        )

    except Exception as e:
        _fail("map_guard missing file", str(e))
    finally:
        shutil.rmtree(tmp)
        # Restore the hidden mapsec backup directory
        if _hid_backup_dir and os.path.isdir(_real_backup_hidden):
            os.rename(_real_backup_hidden, _real_backup_dir)

    # ===================================================================
    # G. _extract_unmanaged_content  (~8 assertions)
    # ===================================================================

    try:
        from torch.sync import (
            _extract_unmanaged_content, _import_unmanaged_to_workspace,
            _detect_label_collisions,
        )
    except ImportError as e:
        _skip("all unmanaged content tests", f"import failed: {e}")
        return

    # G1: Non-existent file returns empty
    segments, has_header = _extract_unmanaged_content("/tmp/nonexistent_torch_test_file.pory")
    _assert(
        "extract_unmanaged: non-existent file returns empty",
        segments == [] and has_header is False,
        f"got segments={segments}, has_header={has_header}"
    )

    # G2: TORCH file with no unmanaged content
    tmp = tempfile.mkdtemp(prefix="torch_unmanaged_test_")
    try:
        pory = os.path.join(tmp, "scripts.pory")
        with open(pory, "w") as f:
            f.write(
                "// ============================================\n"
                "// AUTO-GENERATED by TORCH -- do not hand-edit\n"
                "// Source: TORCH/TestProject/TestMap/\n"
                "// ============================================\n"
                "\n"
                "// # REGION: setup\n"
                "mapscripts TestMap_MapScripts {}\n"
                "// # END REGION: setup\n"
            )
        segments, has_header = _extract_unmanaged_content(pory)
        _assert(
            "extract_unmanaged: TORCH file with only regions returns empty",
            segments == [] and has_header is True,
            f"got {len(segments)} segments, has_header={has_header}"
        )
    except Exception as e:
        _fail("extract_unmanaged: TORCH-only file", str(e))
    finally:
        shutil.rmtree(tmp)

    # G3: TORCH file with content between/after regions
    tmp = tempfile.mkdtemp(prefix="torch_unmanaged_test_")
    try:
        pory = os.path.join(tmp, "scripts.pory")
        with open(pory, "w") as f:
            f.write(
                "// ============================================\n"
                "// AUTO-GENERATED by TORCH -- do not hand-edit\n"
                "// Source: TORCH/TestProject/TestMap/\n"
                "// ============================================\n"
                "\n"
                "// # REGION: setup\n"
                "mapscripts TestMap_MapScripts {}\n"
                "// # END REGION: setup\n"
                "\n"
                "script TestMap_CustomScript {\n"
                "    lock\n"
                "    release\n"
                "}\n"
            )
        segments, has_header = _extract_unmanaged_content(pory)
        _assert(
            "extract_unmanaged: finds content after regions",
            len(segments) == 1 and "TestMap_CustomScript" in segments[0],
            f"got {len(segments)} segments: {segments}"
        )
        _assert(
            "extract_unmanaged: has_torch_header is True",
            has_header is True,
            f"has_header={has_header}"
        )
    except Exception as e:
        _fail("extract_unmanaged: content after regions", str(e))
    finally:
        shutil.rmtree(tmp)

    # G4: Non-TORCH file (no header) — entire file is unmanaged
    tmp = tempfile.mkdtemp(prefix="torch_unmanaged_test_")
    try:
        pory = os.path.join(tmp, "scripts.pory")
        with open(pory, "w") as f:
            f.write(
                "script HandWrittenScript {\n"
                "    lock\n"
                "    release\n"
                "}\n"
            )
        segments, has_header = _extract_unmanaged_content(pory)
        _assert(
            "extract_unmanaged: non-TORCH file returns entire content",
            len(segments) == 1 and "HandWrittenScript" in segments[0],
            f"got {len(segments)} segments"
        )
        _assert(
            "extract_unmanaged: non-TORCH file has_header is False",
            has_header is False,
            f"has_header={has_header}"
        )
    except Exception as e:
        _fail("extract_unmanaged: non-TORCH file", str(e))
    finally:
        shutil.rmtree(tmp)

    # G5: UNMANAGED block round-trip (extract from previously preserved content)
    tmp = tempfile.mkdtemp(prefix="torch_unmanaged_test_")
    try:
        pory = os.path.join(tmp, "scripts.pory")
        with open(pory, "w") as f:
            f.write(
                "// ============================================\n"
                "// AUTO-GENERATED by TORCH -- do not hand-edit\n"
                "// Source: TORCH/TestProject/TestMap/\n"
                "// ============================================\n"
                "\n"
                "// # REGION: setup\n"
                "mapscripts TestMap_MapScripts {}\n"
                "// # END REGION: setup\n"
                "\n"
                "// # UNMANAGED: Preserved content (not managed by TORCH)\n"
                "// # To bring them under TORCH management, move them to a .pory file in the workspace.\n"
                "script TestMap_Preserved {\n"
                "    lock\n"
                "    release\n"
                "}\n"
                "// # END UNMANAGED\n"
            )
        segments, has_header = _extract_unmanaged_content(pory)
        _assert(
            "extract_unmanaged: round-trip preserves UNMANAGED block content",
            len(segments) == 1 and "TestMap_Preserved" in segments[0],
            f"got {len(segments)} segments: {segments}"
        )
        # Verify the explanatory comment lines are stripped
        _assert(
            "extract_unmanaged: strips explanatory comments from UNMANAGED block",
            "To bring them" not in segments[0] and "These scripts were" not in segments[0],
            f"explanatory comment leaked into segment: {segments[0][:100]}"
        )
    except Exception as e:
        _fail("extract_unmanaged: UNMANAGED round-trip", str(e))
    finally:
        shutil.rmtree(tmp)

    # G6: Whitespace-only segments are discarded
    tmp = tempfile.mkdtemp(prefix="torch_unmanaged_test_")
    try:
        pory = os.path.join(tmp, "scripts.pory")
        with open(pory, "w") as f:
            f.write(
                "// ============================================\n"
                "// AUTO-GENERATED by TORCH -- do not hand-edit\n"
                "// Source: TORCH/TestProject/TestMap/\n"
                "// ============================================\n"
                "\n"
                "// # REGION: setup\n"
                "mapscripts TestMap_MapScripts {}\n"
                "// # END REGION: setup\n"
                "\n"
                "\n"
                "// # REGION: events\n"
                "script TestMap_Event {}\n"
                "// # END REGION: events\n"
                "\n"
            )
        segments, _ = _extract_unmanaged_content(pory)
        _assert(
            "extract_unmanaged: whitespace-only between regions is discarded",
            segments == [],
            f"expected empty, got {len(segments)} segments: {segments}"
        )
    except Exception as e:
        _fail("extract_unmanaged: whitespace-only segments", str(e))
    finally:
        shutil.rmtree(tmp)

    # ===================================================================
    # H. _import_unmanaged_to_workspace  (~3 assertions)
    # ===================================================================

    # H1: Creates custom.pory
    tmp = tempfile.mkdtemp(prefix="torch_import_test_")
    try:
        result = _import_unmanaged_to_workspace(
            ["script Foo {\n    lock\n    release\n}"],
            tmp, "TestMap", quiet=True
        )
        _assert(
            "import_unmanaged: creates custom.pory",
            result == "custom.pory",
            f"got filename={result}"
        )
        content = open(os.path.join(tmp, "custom.pory")).read()
        _assert(
            "import_unmanaged: file contains script content",
            "script Foo" in content,
            f"content={content[:100]}"
        )
    except Exception as e:
        _fail("import_unmanaged: creates custom.pory", str(e))
    finally:
        shutil.rmtree(tmp)

    # H2: Collision handling — custom.pory exists, creates custom_1.pory
    tmp = tempfile.mkdtemp(prefix="torch_import_test_")
    try:
        with open(os.path.join(tmp, "custom.pory"), "w") as f:
            f.write("existing")
        result = _import_unmanaged_to_workspace(
            ["script Bar {}"],
            tmp, "TestMap", quiet=True
        )
        _assert(
            "import_unmanaged: collision creates custom_1.pory",
            result == "custom_1.pory",
            f"got filename={result}"
        )
    except Exception as e:
        _fail("import_unmanaged: collision handling", str(e))
    finally:
        shutil.rmtree(tmp)

    # ===================================================================
    # I. _detect_label_collisions  (~2 assertions)
    # ===================================================================

    # I1: No collision
    regions_test = [("setup", "mapscripts Foo_MapScripts {}", False)]
    warnings = _detect_label_collisions(
        ["script Foo_CustomScript {\n    lock\n}"],
        regions_test
    )
    _assert(
        "label_collision: no collision returns empty",
        warnings == [],
        f"got {len(warnings)} warnings: {warnings}"
    )

    # I2: Collision detected
    regions_test = [("events", "script Foo_CustomScript {\n    lock\n}", False)]
    warnings = _detect_label_collisions(
        ["script Foo_CustomScript {\n    release\n}"],
        regions_test
    )
    _assert(
        "label_collision: detects duplicate label",
        len(warnings) == 1 and "Foo_CustomScript" in warnings[0],
        f"got {len(warnings)} warnings: {warnings}"
    )

    # ===================================================================
    # J. Full round-trip: extract -> assemble -> extract again  (~2 assertions)
    # ===================================================================

    try:
        from torch.sync import _sync_assemble_and_write
    except ImportError as e:
        _skip("round-trip test", f"import failed: {e}")
        return

    tmp = tempfile.mkdtemp(prefix="torch_roundtrip_test_")
    try:
        target = os.path.join(tmp, "scripts.pory")
        regions_rt = [("setup", "mapscripts RT_MapScripts {}", False)]
        unmanaged = ["script RT_Custom {\n    lock\n    release\n}"]

        # First write with unmanaged content
        ok = _sync_assemble_and_write(
            list(regions_rt), {}, "TORCH/Test", "RTMap",
            target, tmp, quiet=True,
            unmanaged_content=unmanaged
        )
        _assert("round_trip: first write succeeds", ok is True, f"ok={ok}")

        # Read back and extract — should get the same content
        segments2, _ = _extract_unmanaged_content(target)
        _assert(
            "round_trip: unmanaged survives write->extract cycle",
            len(segments2) == 1 and "RT_Custom" in segments2[0],
            f"got {len(segments2)} segments: {segments2}"
        )

        # Second write (simulates second sync) — should still preserve
        ok2 = _sync_assemble_and_write(
            list(regions_rt), {}, "TORCH/Test", "RTMap",
            target, tmp, quiet=True,
            unmanaged_content=segments2
        )
        _assert("round_trip: second write succeeds", ok2 is True, f"ok2={ok2}")

        segments3, _ = _extract_unmanaged_content(target)
        _assert(
            "round_trip: unmanaged survives two write->extract cycles",
            len(segments3) == 1 and "RT_Custom" in segments3[0],
            f"got {len(segments3)} segments: {segments3}"
        )

        # Verify no duplication — content shouldn't grow
        _assert(
            "round_trip: no content duplication across cycles",
            segments3[0].strip() == segments2[0].strip(),
            f"content diverged:\ncycle1: {segments2[0][:200]}\ncycle2: {segments3[0][:200]}"
        )
    except Exception as e:
        _fail("round_trip: extract-assemble cycle", str(e))
    finally:
        shutil.rmtree(tmp)
