"""Scorch scanner suite -- tests pure-logic functions in scorch_scanner.py."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _assert


def run_suite():
    _begin_suite("Scorch Scanner")

    try:
        from torch.scorch_scanner import (
            ScorchPlan, _extract_labels, _build_tileset_dir_map,
            _ENGINE_KEEP_MAPS, _parse_heal_enum, _heal_matches_custom,
            _build_vanilla_layout_consts, _is_already_scorched,
        )
    except ImportError as e:
        from torch.tests.harness import _skip
        _skip("all scorch scanner tests", f"import failed: {e}")
        return

    # ==========================================================
    # A. ScorchPlan class
    # ==========================================================

    try:
        plan = ScorchPlan()
        _assert("ScorchPlan: empty defaults",
                plan.nuke_maps == set()
                and plan.keep_maps == set()
                and plan.vanilla_trainers == []
                and plan.custom_trainers == []
                and plan.vanilla_encounters == []
                and plan.custom_encounters == []
                and plan.map_groups_data == {}
                and plan.errors == [],
                f"unexpected defaults")

        plan.nuke_maps = {"MapA", "MapB"}
        plan.keep_maps = {"CustomMap"}
        plan.vanilla_trainers = [("TRAINER_A", 1), ("TRAINER_B", 2)]
        plan.custom_trainers = [("TRAINER_C", 3)]
        plan.vanilla_encounters = [{"map": "MapA"}]
        plan.custom_encounters = [{"map": "Custom"}]

        s = plan.summary()
        _assert("ScorchPlan: summary maps tuple",
                s["maps"] == (2, 1),
                f"expected (2,1), got {s['maps']!r}")
        _assert("ScorchPlan: summary trainers tuple",
                s["trainers"] == (2, 1),
                f"expected (2,1), got {s['trainers']!r}")
        _assert("ScorchPlan: summary encounters tuple",
                s["encounters"] == (1, 1),
                f"expected (1,1), got {s['encounters']!r}")
        _assert("ScorchPlan: summary has expected keys",
                set(s.keys()) == {"maps", "layouts", "trainers", "encounters",
                                  "scripts", "tilesets", "mapsecs",
                                  "heal_locs", "c_patches"},
                f"got keys {set(s.keys())!r}")
    except Exception as e:
        _fail("ScorchPlan", str(e))

    # ==========================================================
    # B. _extract_labels
    # ==========================================================

    tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
    try:
        # Double-colon label
        f1 = os.path.join(tmp, "double.inc")
        with open(f1, "w") as f:
            f.write("MyLabel::\n")
        labels = _extract_labels(f1)
        _assert("extract_labels: double colon",
                "MyLabel" in labels,
                f"got {labels!r}")

        # Single-colon label
        f2 = os.path.join(tmp, "single.inc")
        with open(f2, "w") as f:
            f.write("AnotherLabel:\n")
        labels = _extract_labels(f2)
        _assert("extract_labels: single colon",
                "AnotherLabel" in labels,
                f"got {labels!r}")

        # Non-label lines should be excluded
        f3 = os.path.join(tmp, "noise.inc")
        with open(f3, "w") as f:
            f.write('.string "text$"\n@ comment\n\n')
        labels = _extract_labels(f3)
        _assert("extract_labels: noise excluded",
                len(labels) == 0,
                f"expected empty, got {labels!r}")

        # Empty file
        f4 = os.path.join(tmp, "empty.inc")
        with open(f4, "w") as f:
            f.write("")
        labels = _extract_labels(f4)
        _assert("extract_labels: empty file",
                len(labels) == 0,
                f"expected empty, got {labels!r}")

        # Mixed content: only labels extracted
        f5 = os.path.join(tmp, "mixed.inc")
        with open(f5, "w") as f:
            f.write("@ === Script ===\n"
                    "EventScript_Start::\n"
                    '\t.string "Hello$"\n'
                    "LocalLabel:\n"
                    "\treturn\n")
        labels = _extract_labels(f5)
        _assert("extract_labels: mixed content",
                labels == {"EventScript_Start", "LocalLabel"},
                f"expected 2 labels, got {labels!r}")
    except Exception as e:
        _fail("_extract_labels", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # C. _build_tileset_dir_map
    # ==========================================================

    tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
    try:
        gh = os.path.join(tmp, "graphics.h")
        with open(gh, "w") as f:
            f.write(
                'const u32 gTilesetTiles_Petalburg[] = INCBIN_U32("data/tilesets/secondary/petalburg/tiles.4bpp.lz");\n'
                'const u32 gTilesetTiles_BattleFrontier[] = INCBIN_U32("data/tilesets/secondary/battle_frontier/tiles.4bpp.lz");\n'
                '// Not a tileset line\n'
                'const u32 gSomeOtherData[] = INCBIN_U32("data/other/stuff.bin");\n'
            )
        result = _build_tileset_dir_map(gh)
        _assert("tileset_dir_map: Petalburg -> petalburg",
                result.get("Petalburg") == "petalburg",
                f"got {result.get('Petalburg')!r}")
        _assert("tileset_dir_map: BattleFrontier -> battle_frontier",
                result.get("BattleFrontier") == "battle_frontier",
                f"got {result.get('BattleFrontier')!r}")
        _assert("tileset_dir_map: non-tileset excluded",
                "gSomeOtherData" not in result
                and "SomeOtherData" not in result,
                f"unexpected keys: {list(result.keys())!r}")
        _assert("tileset_dir_map: correct size",
                len(result) == 2,
                f"expected 2 entries, got {len(result)}")

        # Empty file
        gh_empty = os.path.join(tmp, "empty_graphics.h")
        with open(gh_empty, "w") as f:
            f.write("")
        result_empty = _build_tileset_dir_map(gh_empty)
        _assert("tileset_dir_map: empty file",
                result_empty == {},
                f"expected empty, got {result_empty!r}")

        # Nonexistent file
        result_missing = _build_tileset_dir_map(os.path.join(tmp, "no_such_file.h"))
        _assert("tileset_dir_map: missing file",
                result_missing == {},
                f"expected empty, got {result_missing!r}")
    except Exception as e:
        _fail("_build_tileset_dir_map", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # D. Engine-keep maps
    # ==========================================================

    # D-1: _ENGINE_KEEP_MAPS constant exists and contains InsideOfTruck
    try:
        _assert("engine_keep: is a set",
                isinstance(_ENGINE_KEEP_MAPS, set),
                f"expected set, got {type(_ENGINE_KEEP_MAPS).__name__}")
        _assert("engine_keep: contains InsideOfTruck",
                "InsideOfTruck" in _ENGINE_KEEP_MAPS,
                f"got {_ENGINE_KEEP_MAPS!r}")
    except Exception as e:
        _fail("_ENGINE_KEEP_MAPS constant", str(e))

    # D-2: engine-keep logic moves maps from nuke to keep
    try:
        plan = ScorchPlan()
        plan.vanilla_maps = {"InsideOfTruck", "Route101"}
        plan.nuke_maps = {"InsideOfTruck", "Route101"}
        plan.keep_maps = set()

        # Simulate the engine-keep logic from _scan_maps
        for keep_map in _ENGINE_KEEP_MAPS:
            if keep_map in plan.nuke_maps:
                plan.nuke_maps.discard(keep_map)
                plan.keep_maps.add(keep_map)

        _assert("engine_keep: InsideOfTruck moved to keep_maps",
                "InsideOfTruck" in plan.keep_maps,
                f"keep_maps = {plan.keep_maps!r}")
        _assert("engine_keep: InsideOfTruck removed from nuke_maps",
                "InsideOfTruck" not in plan.nuke_maps,
                f"nuke_maps = {plan.nuke_maps!r}")
        _assert("engine_keep: Route101 still in nuke_maps",
                "Route101" in plan.nuke_maps,
                f"nuke_maps = {plan.nuke_maps!r}")
    except Exception as e:
        _fail("engine-keep logic", str(e))

    # D-3: ScorchPlan defaults for skipped scanning phases
    try:
        plan = ScorchPlan()
        _assert("skipped phases: vanilla_tilesets default empty",
                plan.vanilla_tilesets == [],
                f"got {plan.vanilla_tilesets!r}")
        _assert("skipped phases: vanilla_scripts default empty",
                plan.vanilla_scripts == [],
                f"got {plan.vanilla_scripts!r}")
    except Exception as e:
        _fail("skipped scanning phases defaults", str(e))

    # ==========================================================
    # E. _parse_heal_enum — parses enum-format heal_locations.h
    # ==========================================================

    tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
    try:
        heal_h = os.path.join(tmp, "heal_locations.h")
        with open(heal_h, "w") as f:
            f.write(
                "#ifndef GUARD_CONSTANTS_HEAL_LOCATIONS_H\n"
                "#define GUARD_CONSTANTS_HEAL_LOCATIONS_H\n"
                "\n"
                "enum {\n"
                "    HEAL_LOCATION_NONE,\n"
                "    HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F,\n"
                "    HEAL_LOCATION_PETALBURG_CITY,\n"
                "    HEAL_LOCATION_PLAYER_BEDROOM,\n"
                "    NUM_HEAL_LOCATIONS\n"
                "};\n"
                "\n"
                "#endif\n"
            )

        members = _parse_heal_enum(heal_h)
        _assert("parse_heal_enum: correct count (excludes NONE and NUM)",
                len(members) == 3,
                f"expected 3, got {len(members)}: {members}")
        _assert("parse_heal_enum: first is LITTLEROOT",
                members[0] == "HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F",
                f"got {members[0]!r}")
        _assert("parse_heal_enum: last is PLAYER_BEDROOM",
                members[2] == "HEAL_LOCATION_PLAYER_BEDROOM",
                f"got {members[2]!r}")
        _assert("parse_heal_enum: NONE excluded",
                "HEAL_LOCATION_NONE" not in members,
                f"NONE found in {members}")
    except Exception as e:
        _fail("_parse_heal_enum", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # E-2: Empty file returns empty list
    tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
    try:
        heal_h = os.path.join(tmp, "heal_locations.h")
        with open(heal_h, "w") as f:
            f.write("")
        members = _parse_heal_enum(heal_h)
        _assert("parse_heal_enum: empty file", members == [],
                f"expected empty, got {members}")
    except Exception as e:
        _fail("_parse_heal_enum: empty file", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # E-3: Missing file returns empty list
    try:
        members = _parse_heal_enum("/nonexistent/heal_locations.h")
        _assert("parse_heal_enum: missing file", members == [],
                f"expected empty, got {members}")
    except Exception as e:
        _fail("_parse_heal_enum: missing file", str(e))

    # ==========================================================
    # F. _heal_matches_custom
    # ==========================================================

    try:
        frags = {"PLAYER_BEDROOM", "SHIRUBE_TOWN"}
        _assert("heal_matches: PLAYER_BEDROOM matches",
                _heal_matches_custom("HEAL_LOCATION_PLAYER_BEDROOM", frags) is True,
                "expected True")
        _assert("heal_matches: PETALBURG_CITY no match",
                _heal_matches_custom("HEAL_LOCATION_PETALBURG_CITY", frags) is False,
                "expected False")
        _assert("heal_matches: SHIRUBE_TOWN_POKEMON_CENTER matches",
                _heal_matches_custom("HEAL_LOCATION_SHIRUBE_TOWN_POKEMON_CENTER_1F", frags) is True,
                "expected True")
        _assert("heal_matches: empty fragments never matches",
                _heal_matches_custom("HEAL_LOCATION_PETALBURG_CITY", set()) is False,
                "expected False")
    except Exception as e:
        _fail("_heal_matches_custom", str(e))

    # ==========================================================
    # G. _build_vanilla_layout_consts
    # ==========================================================

    import json

    # G-1: Finds layouts whose blockdata is in a nuke_maps directory
    tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
    try:
        layouts_dir = os.path.join(tmp, "data", "layouts")
        os.makedirs(layouts_dir)
        layouts_data = {
            "layouts_table_label": "gMapLayouts",
            "layouts": [
                {
                    "id": "LAYOUT_ROUTE101",
                    "name": "Route101_Layout",
                    "blockdata_filepath": "data/maps/Route101/map.bin",
                },
                {
                    "id": "LAYOUT_PETALBURG_CITY",
                    "name": "PetalburgCity_Layout",
                    "blockdata_filepath": "data/maps/PetalburgCity/map.bin",
                },
                {
                    "id": "LAYOUT_CUSTOM_TOWN",
                    "name": "CustomTown_Layout",
                    "blockdata_filepath": "data/maps/CustomTown/map.bin",
                },
                {
                    "id": "LAYOUT_SHARED",
                    "name": "Shared_Layout",
                    "blockdata_filepath": "",
                },
            ]
        }
        with open(os.path.join(layouts_dir, "layouts.json"), "w") as f:
            json.dump(layouts_data, f)

        plan = ScorchPlan()
        plan.nuke_maps = {"Route101", "PetalburgCity"}

        result = _build_vanilla_layout_consts(tmp, plan)
        _assert("layout_consts: Route101 found",
                "LAYOUT_ROUTE101" in result,
                f"got {result!r}")
        _assert("layout_consts: PetalburgCity found",
                "LAYOUT_PETALBURG_CITY" in result,
                f"got {result!r}")
        _assert("layout_consts: CustomTown excluded",
                "LAYOUT_CUSTOM_TOWN" not in result,
                f"got {result!r}")
        _assert("layout_consts: empty blockdata excluded",
                "LAYOUT_SHARED" not in result,
                f"got {result!r}")
        _assert("layout_consts: correct count",
                len(result) == 2,
                f"expected 2, got {len(result)}")
    except Exception as e:
        _fail("_build_vanilla_layout_consts: basic", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # G-2: Empty nuke_maps returns empty set
    tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
    try:
        layouts_dir = os.path.join(tmp, "data", "layouts")
        os.makedirs(layouts_dir)
        layouts_data = {
            "layouts_table_label": "gMapLayouts",
            "layouts": [
                {
                    "id": "LAYOUT_ROUTE101",
                    "name": "Route101_Layout",
                    "blockdata_filepath": "data/maps/Route101/map.bin",
                },
            ]
        }
        with open(os.path.join(layouts_dir, "layouts.json"), "w") as f:
            json.dump(layouts_data, f)

        plan = ScorchPlan()
        plan.nuke_maps = set()
        result = _build_vanilla_layout_consts(tmp, plan)
        _assert("layout_consts: empty nuke_maps -> empty result",
                result == set(),
                f"expected empty, got {result!r}")
    except Exception as e:
        _fail("_build_vanilla_layout_consts: empty nuke", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # G-3: Missing layouts.json returns empty set
    tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
    try:
        plan = ScorchPlan()
        plan.nuke_maps = {"Route101"}
        result = _build_vanilla_layout_consts(tmp, plan)
        _assert("layout_consts: missing file -> empty result",
                result == set(),
                f"expected empty, got {result!r}")
    except Exception as e:
        _fail("_build_vanilla_layout_consts: missing file", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # G-4: Windows-style backslash paths are normalised
    tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
    try:
        layouts_dir = os.path.join(tmp, "data", "layouts")
        os.makedirs(layouts_dir)
        layouts_data = {
            "layouts_table_label": "gMapLayouts",
            "layouts": [
                {
                    "id": "LAYOUT_ROUTE101",
                    "name": "Route101_Layout",
                    "blockdata_filepath": "data\\maps\\Route101\\map.bin",
                },
            ]
        }
        with open(os.path.join(layouts_dir, "layouts.json"), "w") as f:
            json.dump(layouts_data, f)

        plan = ScorchPlan()
        plan.nuke_maps = {"Route101"}
        result = _build_vanilla_layout_consts(tmp, plan)
        _assert("layout_consts: backslash path normalised",
                "LAYOUT_ROUTE101" in result,
                f"expected LAYOUT_ROUTE101, got {result!r}")
    except Exception as e:
        _fail("_build_vanilla_layout_consts: backslash path", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # H. ScorchPlan.vanilla_layout_consts field
    # ==========================================================

    try:
        plan = ScorchPlan()
        _assert("ScorchPlan: vanilla_layout_consts default is empty set",
                plan.vanilla_layout_consts == set(),
                f"got {plan.vanilla_layout_consts!r}")
    except Exception as e:
        _fail("ScorchPlan: vanilla_layout_consts field", str(e))

    # ==========================================================
    # I. Re-entrancy guard
    # ==========================================================

    # I-1: build_scorch_plan with too few maps triggers error
    tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
    try:
        from torch.scorch_scanner import build_scorch_plan

        # Create minimal project structure with only 2 maps
        maps_dir = os.path.join(tmp, "data", "maps")
        os.makedirs(maps_dir)
        mg_path = os.path.join(tmp, "data", "maps", "map_groups.json")

        # Create a map_groups.json with very few maps (simulates scorched project)
        mg_data = {
            "gMapGroup_Custom": ["PlayerHome", "ShirubeTown"]
        }
        with open(mg_path, "w") as f:
            json.dump(mg_data, f)

        # Create map dirs so classify_maps finds them
        os.makedirs(os.path.join(maps_dir, "PlayerHome"), exist_ok=True)
        os.makedirs(os.path.join(maps_dir, "ShirubeTown"), exist_ok=True)

        plan = build_scorch_plan(tmp)
        has_guard_error = any("already be scorched" in e for e in plan.errors)
        _assert("re-entrancy guard: triggers on < 20 maps",
                has_guard_error,
                f"errors: {plan.errors!r}")
    except Exception as e:
        _fail("re-entrancy guard: triggers", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==========================================================
    # J. ScorchPlan MAPSEC fields
    # ==========================================================

    try:
        plan = ScorchPlan()
        _assert("ScorchPlan: vanilla_mapsecs default is empty set",
                plan.vanilla_mapsecs == set(),
                f"got {plan.vanilla_mapsecs!r}")
        _assert("ScorchPlan: custom_mapsecs default is empty set",
                plan.custom_mapsecs == set(),
                f"got {plan.custom_mapsecs!r}")
        _assert("ScorchPlan: system_mapsecs contains NONE and DYNAMIC",
                "MAPSEC_NONE" in plan.system_mapsecs
                and "MAPSEC_DYNAMIC" in plan.system_mapsecs,
                f"got {plan.system_mapsecs!r}")
        _assert("ScorchPlan: summary includes mapsecs key",
                "mapsecs" in plan.summary(),
                f"keys: {list(plan.summary().keys())!r}")
    except Exception as e:
        _fail("ScorchPlan MAPSEC fields", str(e))

    # ==========================================================
    # K. _scan_mapsecs
    # ==========================================================

    import json

    try:
        from torch.scorch_scanner import (
            _scan_mapsecs, _collect_surviving_mapsecs,
        )
    except ImportError as e:
        _fail("_scan_mapsecs import", str(e))
        return

    # K-1: Basic vanilla vs custom MAPSEC detection
    tmp = tempfile.mkdtemp(prefix="torch_scanner_mapsec_")
    try:
        # Create region_map_sections.json
        rms_dir = os.path.join(tmp, "src", "data", "region_map")
        os.makedirs(rms_dir, exist_ok=True)
        rms_data = {
            "map_sections": [
                {"id": "MAPSEC_LITTLEROOT_TOWN", "name": "LITTLEROOT TOWN",
                 "x": 4, "y": 11, "width": 1, "height": 1},
                {"id": "MAPSEC_OLDALE_TOWN", "name": "OLDALE TOWN",
                 "x": 4, "y": 9, "width": 1, "height": 1},
                {"id": "MAPSEC_SHIRUBE_TOWN", "name": "SHIRUBE TOWN",
                 "x": 0, "y": 0, "width": 1, "height": 1},
                {"id": "MAPSEC_INSIDE_OF_TRUCK", "name": "INSIDE OF TRUCK",
                 "x": 0, "y": 0, "width": 1, "height": 1},
                {"id": "MAPSEC_DYNAMIC", "name": "DYNAMIC",
                 "x": 0, "y": 0, "width": 1, "height": 1},
            ]
        }
        rms_path = os.path.join(rms_dir, "region_map_sections.json")
        with open(rms_path, "w") as f:
            json.dump(rms_data, f)

        # Create a surviving map that references MAPSEC_SHIRUBE_TOWN
        maps_dir = os.path.join(tmp, "data", "maps", "ShirubeTown")
        os.makedirs(maps_dir, exist_ok=True)
        with open(os.path.join(maps_dir, "map.json"), "w") as f:
            json.dump({"region_map_section": "MAPSEC_SHIRUBE_TOWN"}, f)

        plan = ScorchPlan()
        plan.keep_maps = {"ShirubeTown", "InsideOfTruck"}
        plan.nuke_maps = {"LittlerootTown", "OldaleTown"}

        _scan_mapsecs(tmp, plan)

        _assert("scan_mapsecs: SHIRUBE_TOWN is custom (referenced by surviving map)",
                "MAPSEC_SHIRUBE_TOWN" in plan.custom_mapsecs,
                f"custom: {plan.custom_mapsecs!r}")
        _assert("scan_mapsecs: INSIDE_OF_TRUCK is custom (always kept)",
                "MAPSEC_INSIDE_OF_TRUCK" in plan.custom_mapsecs,
                f"custom: {plan.custom_mapsecs!r}")
        _assert("scan_mapsecs: DYNAMIC is custom (system MAPSEC)",
                "MAPSEC_DYNAMIC" in plan.custom_mapsecs,
                f"custom: {plan.custom_mapsecs!r}")
        _assert("scan_mapsecs: LITTLEROOT_TOWN is vanilla",
                "MAPSEC_LITTLEROOT_TOWN" in plan.vanilla_mapsecs,
                f"vanilla: {plan.vanilla_mapsecs!r}")
        _assert("scan_mapsecs: OLDALE_TOWN is vanilla",
                "MAPSEC_OLDALE_TOWN" in plan.vanilla_mapsecs,
                f"vanilla: {plan.vanilla_mapsecs!r}")
        _assert("scan_mapsecs: vanilla + custom = all",
                len(plan.vanilla_mapsecs) + len(plan.custom_mapsecs) == 5,
                f"vanilla={len(plan.vanilla_mapsecs)}, custom={len(plan.custom_mapsecs)}")
    except Exception as e:
        _fail("_scan_mapsecs: basic detection", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # K-2: Missing region_map_sections.json is a no-op
    tmp = tempfile.mkdtemp(prefix="torch_scanner_mapsec_")
    try:
        plan = ScorchPlan()
        plan.keep_maps = {"ShirubeTown"}
        _scan_mapsecs(tmp, plan)
        _assert("scan_mapsecs: missing file -> empty sets",
                plan.vanilla_mapsecs == set() and plan.custom_mapsecs == set(),
                f"vanilla={plan.vanilla_mapsecs!r}, custom={plan.custom_mapsecs!r}")
    except Exception as e:
        _fail("_scan_mapsecs: missing file", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # K-3: _collect_surviving_mapsecs reads map.json correctly
    tmp = tempfile.mkdtemp(prefix="torch_scanner_mapsec_")
    try:
        maps_dir = os.path.join(tmp, "data", "maps")
        map_a = os.path.join(maps_dir, "MapA")
        map_b = os.path.join(maps_dir, "MapB")
        os.makedirs(map_a, exist_ok=True)
        os.makedirs(map_b, exist_ok=True)

        with open(os.path.join(map_a, "map.json"), "w") as f:
            json.dump({"region_map_section": "MAPSEC_CUSTOM_A"}, f)
        with open(os.path.join(map_b, "map.json"), "w") as f:
            json.dump({"region_map_section": "MAPSEC_CUSTOM_B"}, f)

        result = _collect_surviving_mapsecs(tmp, {"MapA", "MapB"})
        _assert("collect_surviving: finds both MAPSECs",
                result == {"MAPSEC_CUSTOM_A", "MAPSEC_CUSTOM_B"},
                f"got {result!r}")

        # Missing map dir returns empty
        result2 = _collect_surviving_mapsecs(tmp, {"NonExistent"})
        _assert("collect_surviving: missing map -> empty",
                result2 == set(),
                f"got {result2!r}")
    except Exception as e:
        _fail("_collect_surviving_mapsecs", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
