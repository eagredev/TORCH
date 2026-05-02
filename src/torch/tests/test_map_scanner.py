"""Tests for map_scanner.py — game map scanning and classification."""
import os
import json
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _assert


def run_suite():
    _begin_suite("Map Scanner (_scan_game_maps)")

    from torch.map_scanner import _scan_game_maps

    # ── A. Empty maps directory ────────────────────────────────────

    tmpdir = tempfile.mkdtemp(prefix="torch_test_scanner_")
    try:
        game_path = os.path.join(tmpdir, "game")
        project_dir = os.path.join(tmpdir, "workspace")
        maps_dir = os.path.join(game_path, "data", "maps")
        os.makedirs(maps_dir)
        os.makedirs(project_dir)

        # Empty map_groups.json so classify_maps returns (set(), set())
        with open(os.path.join(maps_dir, "map_groups.json"), "w") as f:
            json.dump({}, f)

        results = _scan_game_maps(game_path, project_dir)
        _assert("empty maps dir returns empty list",
                results == [],
                f"got {len(results)} results")

        # ── B. Vanilla map (in data/maps/ but not in workspace) ────

        map1_dir = os.path.join(maps_dir, "Route101")
        os.makedirs(map1_dir)
        with open(os.path.join(map1_dir, "map.json"), "w") as f:
            json.dump({"name": "Route101"}, f)

        results = _scan_game_maps(game_path, project_dir)
        _assert("one vanilla map discovered",
                len(results) == 1,
                f"expected 1, got {len(results)}")

        r = results[0]
        _assert("vanilla map name is correct",
                r["name"] == "Route101",
                f"got {r['name']}")

        _assert("vanilla map status is VANILLA",
                r["status"] == "VANILLA",
                f"got {r['status']}")

        _assert("vanilla map has no workspace_dir",
                r["workspace_dir"] is None,
                f"got {r['workspace_dir']}")

        _assert("vanilla map game_dir is set",
                r["game_dir"] == map1_dir,
                f"got {r['game_dir']}")

        _assert("vanilla map mtime is 0.0",
                r["mtime"] == 0.0,
                f"got {r['mtime']}")

        _assert("vanilla map script_count is 0",
                r["script_count"] == 0,
                f"got {r['script_count']}")

        # ── C. Active map (in both data/maps/ and workspace) ───────

        ws_route = os.path.join(project_dir, "Route101")
        os.makedirs(ws_route)
        script_path = os.path.join(ws_route, "scene1.txt")
        with open(script_path, "w") as f:
            f.write("# test script")

        results = _scan_game_maps(game_path, project_dir)
        active = [r for r in results if r["name"] == "Route101"]
        _assert("active map detected",
                len(active) == 1 and active[0]["status"] == "ACTIVE",
                f"got {[r['status'] for r in active]}")

        _assert("active map has workspace_dir",
                active[0]["workspace_dir"] == ws_route,
                f"got {active[0]['workspace_dir']}")

        _assert("active map script_count is 1",
                active[0]["script_count"] == 1,
                f"got {active[0]['script_count']}")

        _assert("active map mtime > 0",
                active[0]["mtime"] > 0.0,
                f"got {active[0]['mtime']}")

        # ── D. Orphan workspace (in workspace but not data/maps/) ──

        orphan_ws = os.path.join(project_dir, "MyCustomMap")
        os.makedirs(orphan_ws)
        with open(os.path.join(orphan_ws, "dialogue.pory"), "w") as f:
            f.write("// pory")

        results = _scan_game_maps(game_path, project_dir)
        orphans = [r for r in results if r["name"] == "MyCustomMap"]
        _assert("orphan workspace detected",
                len(orphans) == 1 and orphans[0]["status"] == "ORPHAN",
                f"got {orphans}")

        _assert("orphan has no game_dir",
                orphans[0]["game_dir"] is None,
                f"got {orphans[0]['game_dir']}")

        _assert("orphan script_count is 1",
                orphans[0]["script_count"] == 1,
                f"got {orphans[0]['script_count']}")

        # ── E. Workspace skip dirs are ignored ─────────────────────

        skip_dir = os.path.join(project_dir, "backups")
        os.makedirs(skip_dir)
        with open(os.path.join(skip_dir, "old.txt"), "w") as f:
            f.write("backup")

        results = _scan_game_maps(game_path, project_dir)
        backup_hits = [r for r in results if r["name"] == "backups"]
        _assert("skip dirs (backups) not scanned",
                len(backup_hits) == 0,
                f"found {len(backup_hits)} entries for 'backups'")

    finally:
        shutil.rmtree(tmpdir)

    # ══════════════════════════════════════════════════════════════
    # _read_map_metadata tests
    # ══════════════════════════════════════════════════════════════

    _begin_suite("Map Scanner (_read_map_metadata)")

    from torch.map_scanner import _read_map_metadata
    from torch.project_files import clear_project_cache

    # ── F. Map with events, trainers, encounters ─────────────────

    tmpdir = tempfile.mkdtemp(prefix="torch_test_metadata_")
    try:
        game_path = os.path.join(tmpdir, "game")
        maps_dir = os.path.join(game_path, "data", "maps")

        # Create a map with varied events
        test_map = os.path.join(maps_dir, "TestTown")
        os.makedirs(test_map)
        map_json = {
            "object_events": [
                {"graphics_id": "OBJ_EVENT_GFX_BOY_1", "trainer_type": "TRAINER_TYPE_NONE"},
                {"graphics_id": "OBJ_EVENT_GFX_GIRL_1", "trainer_type": "TRAINER_TYPE_NORMAL"},
                {"graphics_id": "OBJ_EVENT_GFX_MAN_1", "trainer_type": "TRAINER_TYPE_NORMAL"},
            ],
            "warp_events": [
                {"x": 5, "y": 10},
                {"x": 8, "y": 12},
            ],
            "coord_events": [
                {"x": 3, "y": 7},
            ],
            "bg_events": [
                {"type": "sign"},
                {"type": "sign"},
            ],
        }
        with open(os.path.join(test_map, "map.json"), "w") as f:
            json.dump(map_json, f)

        # Create script files with trainerbattle calls (trainer count is script-based)
        with open(os.path.join(test_map, "scripts.pory"), "w") as f:
            f.write('trainerbattle_single(TRAINER_GIRL_1, Text1, Text2)\n')
            f.write('trainerbattle_double(TRAINER_MAN_1, Text1, Text2, Text3)\n')

        clear_project_cache()
        meta = _read_map_metadata(game_path, "TestTown")

        _assert("metadata npc_count counts object_events",
                meta["npc_count"] == 3,
                f"expected 3, got {meta['npc_count']}")

        _assert("metadata trainer_count from script scanning",
                meta["trainer_count"] == 2,
                f"expected 2, got {meta['trainer_count']}")

        # ── F2. npc_names grouping ────────────────────────────────
        # Boy 1 and Girl 1 appear once each, Man 1 once → 3 unique names
        _assert("metadata npc_names is a list",
                isinstance(meta["npc_names"], list),
                f"expected list, got {type(meta['npc_names'])}")
        _assert("metadata npc_names has 3 entries (no dupes)",
                len(meta["npc_names"]) == 3,
                f"expected 3 names, got {meta['npc_names']}")

        # ── F3. trainer_consts list ───────────────────────────────
        _assert("metadata trainer_consts is a list",
                isinstance(meta["trainer_consts"], list),
                f"expected list, got {type(meta['trainer_consts'])}")
        _assert("metadata trainer_consts has 2 entries",
                len(meta["trainer_consts"]) == 2,
                f"expected 2, got {meta['trainer_consts']}")

        # ── F4. encounter_types is a list ─────────────────────────
        _assert("metadata encounter_types is a list",
                isinstance(meta["encounter_types"], list),
                f"expected list, got {type(meta['encounter_types'])}")

        # ── F5. heal_count is an int ──────────────────────────────
        _assert("metadata heal_count is an int",
                isinstance(meta["heal_count"], int),
                f"expected int, got {type(meta['heal_count'])}")

        # ── F6. NPC name duplicate grouping ───────────────────────
        # Create a map with duplicate NPCs to test "x2" grouping
        dup_map = os.path.join(maps_dir, "DupNpcMap")
        os.makedirs(dup_map)
        dup_json = {
            "object_events": [
                {"graphics_id": "OBJ_EVENT_GFX_TWIN", "trainer_type": "TRAINER_TYPE_NONE"},
                {"graphics_id": "OBJ_EVENT_GFX_TWIN", "trainer_type": "TRAINER_TYPE_NONE"},
                {"graphics_id": "OBJ_EVENT_GFX_FAT_MAN", "trainer_type": "TRAINER_TYPE_NONE"},
            ],
        }
        with open(os.path.join(dup_map, "map.json"), "w") as f:
            json.dump(dup_json, f)

        clear_project_cache()
        meta_dup = _read_map_metadata(game_path, "DupNpcMap")
        _assert("duplicate NPCs grouped with x2",
                "Twin x2" in meta_dup["npc_names"],
                f"expected 'Twin x2' in {meta_dup['npc_names']}")
        _assert("non-duplicate NPC listed alone",
                "Fat Man" in meta_dup["npc_names"],
                f"expected 'Fat Man' in {meta_dup['npc_names']}")
        _assert("grouped npc_names has 2 entries (Twin x2, Fat Man)",
                len(meta_dup["npc_names"]) == 2,
                f"expected 2, got {meta_dup['npc_names']}")

        # ── G. Map with no events (empty map.json) ──────────────────

        empty_map = os.path.join(maps_dir, "EmptyMap")
        os.makedirs(empty_map)
        with open(os.path.join(empty_map, "map.json"), "w") as f:
            json.dump({"name": "EmptyMap"}, f)

        clear_project_cache()
        meta_empty = _read_map_metadata(game_path, "EmptyMap")

        _assert("empty map npc_count is 0",
                meta_empty["npc_count"] == 0,
                f"got {meta_empty['npc_count']}")

        _assert("empty map trainer_count is 0",
                meta_empty["trainer_count"] == 0,
                f"got {meta_empty['trainer_count']}")

        _assert("empty map encounter_detail is empty",
                meta_empty["encounter_detail"] == {},
                f"got {meta_empty['encounter_detail']}")

        _assert("empty map npc_names is empty list",
                meta_empty["npc_names"] == [],
                f"got {meta_empty['npc_names']}")

        _assert("empty map trainer_consts is empty list",
                meta_empty["trainer_consts"] == [],
                f"got {meta_empty['trainer_consts']}")

        _assert("empty map encounter_types is empty list",
                meta_empty["encounter_types"] == [],
                f"got {meta_empty['encounter_types']}")

        _assert("empty map heal_count is 0",
                meta_empty["heal_count"] == 0,
                f"got {meta_empty['heal_count']}")

        # ── H. Map with no map.json (load failure) ──────────────────

        missing_map = os.path.join(maps_dir, "MissingJson")
        os.makedirs(missing_map)
        # No map.json file created

        clear_project_cache()
        meta_missing = _read_map_metadata(game_path, "MissingJson")

        _assert("missing map.json returns npc_count 0",
                meta_missing["npc_count"] == 0,
                f"got {meta_missing['npc_count']}")

        _assert("missing map.json returns trainer_count 0",
                meta_missing["trainer_count"] == 0,
                f"got {meta_missing['trainer_count']}")

        _assert("missing map.json returns encounter_detail empty",
                meta_missing["encounter_detail"] == {},
                f"got {meta_missing['encounter_detail']}")

        # ── I. Non-existent map (no folder at all) ──────────────────

        clear_project_cache()
        meta_nomap = _read_map_metadata(game_path, "NonExistentMap")

        expected_empty = {
            "npc_count": 0, "npc_names": [], "trainer_count": 0,
            "trainer_consts": [], "encounter_detail": {},
            "encounter_types": [], "heal_count": 0,
        }
        _assert("non-existent map returns all zeros",
                meta_nomap == expected_empty,
                f"got {meta_nomap}")

    finally:
        shutil.rmtree(tmpdir)
