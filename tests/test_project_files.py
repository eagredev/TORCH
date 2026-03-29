"""Project Files loader suite — cached JSON loaders for game data."""
import os
import json
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------

def _make_game_tree(tmp):
    """Create a minimal game tree under tmp and return the game_path."""
    game = os.path.join(tmp, "game")

    # data/maps/map_groups.json
    # Uses real PascalCase vanilla names so the frozen set classifies them
    mg_dir = os.path.join(game, "data", "maps")
    os.makedirs(mg_dir)
    mg_data = {
        "group_order": [
            "gMapGroup_PetalburgCity",
            "gMapGroup_IndoorRoute124",
            "gMapGroup_CustomTown",
        ],
        "gMapGroup_PetalburgCity": ["PetalburgCity", "PetalburgCity_Gym"],
        "gMapGroup_IndoorRoute124": ["Route124_DivingTreasureHuntersHouse"],
        "gMapGroup_CustomTown": ["CustomTownCenter", "CustomTownHouse1"],
    }
    with open(os.path.join(mg_dir, "map_groups.json"), "w") as f:
        json.dump(mg_data, f)

    # data/maps/TestMap/map.json
    test_map_dir = os.path.join(mg_dir, "TestMap")
    os.makedirs(test_map_dir)
    map_json = {"layout": "LAYOUT_TESTMAP", "music": "MUS_TEST"}
    with open(os.path.join(test_map_dir, "map.json"), "w") as f:
        json.dump(map_json, f)

    # data/layouts/layouts.json
    layouts_dir = os.path.join(game, "data", "layouts")
    os.makedirs(layouts_dir)
    layouts_data = {
        "layouts_table_label": "gMapLayouts",
        "layouts": [
            {
                "id": "LAYOUT_TESTMAP",
                "name": "TestMap_Layout",
                "width": 20,
                "height": 20,
                "blockdata_filepath": "data/layouts/TestMap/map.bin",
            },
            {
                "id": "LAYOUT_SECOND",
                "name": "SecondLayout",
                "width": 10,
                "height": 10,
                "blockdata_filepath": "data/layouts/SecondArea/map.bin",
            },
        ],
    }
    with open(os.path.join(layouts_dir, "layouts.json"), "w") as f:
        json.dump(layouts_data, f)

    # src/data/wild_encounters.json
    enc_dir = os.path.join(game, "src", "data")
    os.makedirs(enc_dir)
    enc_data = {
        "wild_encounter_groups": [
            {
                "label": "gWildMonHeaders",
                "encounters": [
                    {"map": "MAP_ROUTE101", "base_label": "gRoute101"},
                ],
            }
        ]
    }
    with open(os.path.join(enc_dir, "wild_encounters.json"), "w") as f:
        json.dump(enc_data, f)

    return game


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("Project Files  (cached JSON loaders)")

    try:
        from torch.project_files import (
            load_map_groups, classify_maps, load_layouts,
            load_map_json, load_wild_encounters, find_layout_dir,
            clear_project_cache,
        )
    except ImportError as e:
        _skip("all project_files tests", f"import failed: {e}")
        return

    tmp = tempfile.mkdtemp(prefix="torch_pf_test_")
    try:
        game = _make_game_tree(tmp)
        clear_project_cache()

        # ---- load_map_groups ----
        mg = load_map_groups(game)
        _assert(
            "load_map_groups: returns dict",
            isinstance(mg, dict),
            f"expected dict, got {type(mg)}"
        )
        _assert(
            "load_map_groups: has group_order",
            "group_order" in mg,
            f"keys: {list(mg.keys())}"
        )

        # Caching: second call returns same object
        mg2 = load_map_groups(game)
        _assert(
            "load_map_groups: cached (same object)",
            mg is mg2,
            "second call returned different object"
        )

        # Missing file
        missing = load_map_groups("/nonexistent/path")
        _assert(
            "load_map_groups: missing file returns None",
            missing is None,
            f"expected None, got {type(missing)}"
        )

        # Malformed JSON
        clear_project_cache()
        bad_dir = os.path.join(tmp, "bad")
        bad_mg_dir = os.path.join(bad_dir, "data", "maps")
        os.makedirs(bad_mg_dir)
        with open(os.path.join(bad_mg_dir, "map_groups.json"), "w") as f:
            f.write("{invalid json")
        bad_result = load_map_groups(bad_dir)
        _assert(
            "load_map_groups: malformed JSON returns None",
            bad_result is None,
            f"expected None, got {type(bad_result)}"
        )

        # ---- classify_maps ----
        clear_project_cache()
        vanilla, custom = classify_maps(game)
        _assert(
            "classify_maps: vanilla names classified as vanilla",
            "PetalburgCity" in vanilla
            and "Route124_DivingTreasureHuntersHouse" in vanilla,
            f"vanilla: {vanilla}"
        )
        _assert(
            "classify_maps: non-vanilla names classified as custom",
            "CustomTownCenter" in custom
            and "CustomTownHouse1" in custom,
            f"custom: {custom}"
        )
        _assert(
            "classify_maps: vanilla and custom are disjoint",
            len(vanilla & custom) == 0,
            f"overlap: {vanilla & custom}"
        )

        # No sentinel in group_order — still classifies by name
        clear_project_cache()
        no_sentinel_dir = os.path.join(tmp, "nosent")
        ns_mg = os.path.join(no_sentinel_dir, "data", "maps")
        os.makedirs(ns_mg)
        with open(os.path.join(ns_mg, "map_groups.json"), "w") as f:
            json.dump({
                "group_order": ["gMapGroup_Mix"],
                "gMapGroup_Mix": ["Route101", "MyCustomMap"],
            }, f)
        v2, c2 = classify_maps(no_sentinel_dir)
        _assert(
            "classify_maps: no sentinel -> name-based classification",
            "Route101" in v2 and "MyCustomMap" in c2,
            f"vanilla={v2}, custom={c2}"
        )

        # Post-Phoenix project (only custom maps)
        clear_project_cache()
        phoenix_dir = os.path.join(tmp, "phoenix")
        ph_mg = os.path.join(phoenix_dir, "data", "maps")
        os.makedirs(ph_mg)
        with open(os.path.join(ph_mg, "map_groups.json"), "w") as f:
            json.dump({
                "group_order": ["gMapGroup_Custom"],
                "gMapGroup_Custom": ["ShirubeTown", "LakeElixSouth"],
            }, f)
        v_ph, c_ph = classify_maps(phoenix_dir)
        _assert(
            "classify_maps: post-Phoenix -> empty vanilla, populated custom",
            len(v_ph) == 0 and "ShirubeTown" in c_ph and "LakeElixSouth" in c_ph,
            f"vanilla={v_ph}, custom={c_ph}"
        )

        # Missing file
        v3, c3 = classify_maps("/nonexistent")
        _assert(
            "classify_maps: missing file returns (set(), set())",
            v3 == set() and c3 == set(),
            f"got ({v3}, {c3})"
        )

        # ---- load_layouts ----
        clear_project_cache()
        layouts = load_layouts(game)
        _assert(
            "load_layouts: returns dict with layouts key",
            isinstance(layouts, dict) and "layouts" in layouts,
            f"got {type(layouts)}"
        )
        _assert(
            "load_layouts: has 2 layout entries",
            len(layouts["layouts"]) == 2,
            f"expected 2, got {len(layouts['layouts'])}"
        )

        # Missing file
        _assert(
            "load_layouts: missing file returns None",
            load_layouts("/nonexistent") is None,
            "expected None"
        )

        # ---- load_map_json ----
        clear_project_cache()
        mj = load_map_json(game, "TestMap")
        _assert(
            "load_map_json: returns dict",
            isinstance(mj, dict),
            f"expected dict, got {type(mj)}"
        )
        _assert(
            "load_map_json: correct layout field",
            mj.get("layout") == "LAYOUT_TESTMAP",
            f"layout: {mj.get('layout')}"
        )

        # Missing map
        _assert(
            "load_map_json: missing map returns None",
            load_map_json(game, "NoSuchMap") is None,
            "expected None"
        )

        # ---- find_layout_dir ----
        clear_project_cache()
        ld = find_layout_dir(game, "LAYOUT_TESTMAP")
        _assert(
            "find_layout_dir: returns correct directory",
            ld == "TestMap",
            f"expected 'TestMap', got '{ld}'"
        )

        ld2 = find_layout_dir(game, "LAYOUT_SECOND")
        _assert(
            "find_layout_dir: second layout lookup",
            ld2 == "SecondArea",
            f"expected 'SecondArea', got '{ld2}'"
        )

        _assert(
            "find_layout_dir: unknown ID returns None",
            find_layout_dir(game, "LAYOUT_NONEXISTENT") is None,
            "expected None"
        )

        # ---- load_wild_encounters ----
        clear_project_cache()
        enc = load_wild_encounters(game)
        _assert(
            "load_wild_encounters: returns dict",
            isinstance(enc, dict),
            f"expected dict, got {type(enc)}"
        )
        _assert(
            "load_wild_encounters: has encounter groups",
            len(enc.get("wild_encounter_groups", [])) == 1,
            f"groups: {enc.get('wild_encounter_groups')}"
        )

        # Missing file
        _assert(
            "load_wild_encounters: missing file returns None",
            load_wild_encounters("/nonexistent") is None,
            "expected None"
        )

        # ---- clear_project_cache ----
        clear_project_cache()
        mg_before = load_map_groups(game)

        # Modify the file on disk
        mg_file = os.path.join(game, "data", "maps", "map_groups.json")
        with open(mg_file, "w") as f:
            json.dump({"group_order": [], "modified": True}, f)

        # Cache should still return old data
        mg_cached = load_map_groups(game)
        _assert(
            "clear_project_cache: cache returns old data before clear",
            mg_cached is mg_before,
            "cache miss before clear"
        )

        # Clear and re-read
        clear_project_cache()
        mg_after = load_map_groups(game)
        _assert(
            "clear_project_cache: re-read returns new data after clear",
            mg_after is not mg_before and mg_after.get("modified") is True,
            f"got {mg_after}"
        )

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

    # Run the sub-suites
    run_folder_to_map_const_suite()
    run_encounter_suite()
    run_trainer_map_index_suite()


# ---------------------------------------------------------------------------
# folder_to_map_const
# ---------------------------------------------------------------------------

def run_folder_to_map_const_suite():
    _begin_suite("Project Files  (folder_to_map_const)")

    try:
        from torch.project_files import folder_to_map_const
    except ImportError as e:
        _skip("all folder_to_map_const tests", f"import failed: {e}")
        return

    _assert(
        "folder_to_map_const: PetalburgCity -> MAP_PETALBURG_CITY",
        folder_to_map_const("PetalburgCity") == "MAP_PETALBURG_CITY",
        f"got: {folder_to_map_const('PetalburgCity')}"
    )
    _assert(
        "folder_to_map_const: Route101 -> MAP_ROUTE101",
        folder_to_map_const("Route101") == "MAP_ROUTE101",
        f"got: {folder_to_map_const('Route101')}"
    )
    _assert(
        "folder_to_map_const: ShirubeTown -> MAP_SHIRUBE_TOWN",
        folder_to_map_const("ShirubeTown") == "MAP_SHIRUBE_TOWN",
        f"got: {folder_to_map_const('ShirubeTown')}"
    )
    _assert(
        "folder_to_map_const: ArtisanCave_1F -> MAP_ARTISAN_CAVE_1F",
        folder_to_map_const("ArtisanCave_1F") == "MAP_ARTISAN_CAVE_1F",
        f"got: {folder_to_map_const('ArtisanCave_1F')}"
    )
    _assert(
        "folder_to_map_const: AbandonedShip_B1F -> MAP_ABANDONED_SHIP_B1F",
        folder_to_map_const("AbandonedShip_B1F") == "MAP_ABANDONED_SHIP_B1F",
        f"got: {folder_to_map_const('AbandonedShip_B1F')}"
    )
    _assert(
        "folder_to_map_const: empty -> empty",
        folder_to_map_const("") == "",
        f"got: {folder_to_map_const('')}"
    )


# ---------------------------------------------------------------------------
# Encounter data functions
# ---------------------------------------------------------------------------

def _make_encounter_tree(tmp):
    """Create a game tree with rich encounter data for testing."""
    game = os.path.join(tmp, "enc_game")
    enc_dir = os.path.join(game, "src", "data")
    os.makedirs(enc_dir)
    enc_data = {
        "wild_encounter_groups": [
            {
                "label": "gWildMonHeaders",
                "for_maps": True,
                "fields": [],
                "encounters": [
                    {
                        "map": "MAP_ROUTE101",
                        "base_label": "gRoute101",
                        "land_mons": {
                            "encounter_rate": 20,
                            "mons": [
                                {"min_level": 2, "max_level": 2,
                                 "species": "SPECIES_WURMPLE"},
                                {"min_level": 3, "max_level": 3,
                                 "species": "SPECIES_POOCHYENA"},
                            ],
                        },
                    },
                    {
                        "map": "MAP_ROUTE102",
                        "base_label": "gRoute102",
                        "land_mons": {
                            "encounter_rate": 20,
                            "mons": [
                                {"min_level": 3, "max_level": 4,
                                 "species": "SPECIES_ZIGZAGOON"},
                            ],
                        },
                        "water_mons": {
                            "encounter_rate": 5,
                            "mons": [
                                {"min_level": 20, "max_level": 30,
                                 "species": "SPECIES_MARILL"},
                            ],
                        },
                    },
                    {
                        "map": "MAP_ROUTE103",
                        "base_label": "gRoute103_Morning",
                        "land_mons": {
                            "encounter_rate": 20,
                            "mons": [
                                {"min_level": 5, "max_level": 5,
                                 "species": "SPECIES_TAILLOW"},
                            ],
                        },
                    },
                    {
                        "map": "MAP_ROUTE103",
                        "base_label": "gRoute103_Night",
                        "land_mons": {
                            "encounter_rate": 20,
                            "mons": [
                                {"min_level": 5, "max_level": 5,
                                 "species": "SPECIES_HOOTHOOT"},
                            ],
                        },
                    },
                ],
            }
        ]
    }
    with open(os.path.join(enc_dir, "wild_encounters.json"), "w") as f:
        json.dump(enc_data, f)
    return game


def run_encounter_suite():
    _begin_suite("Project Files  (encounter data functions)")

    try:
        from torch.project_files import (
            get_all_encounters, get_encounters_for_map,
            get_encounter_types, get_encounter_species,
            extract_time_suffix, get_maps_with_encounters,
            write_encounters, remove_encounters_for_map,
            clear_project_cache, load_wild_encounters,
        )
    except ImportError as e:
        _skip("all encounter tests", f"import failed: {e}")
        return

    tmp = tempfile.mkdtemp(prefix="torch_enc_test_")
    try:
        game = _make_encounter_tree(tmp)
        clear_project_cache()

        # 1. get_all_encounters: returns 4 entries
        all_enc = get_all_encounters(game)
        _assert(
            "get_all_encounters: returns 4 entries",
            len(all_enc) == 4,
            f"expected 4, got {len(all_enc)}"
        )
        maps_found = [e.get("map") for e in all_enc]
        _assert(
            "get_all_encounters: correct map constants",
            "MAP_ROUTE101" in maps_found and "MAP_ROUTE102" in maps_found,
            f"maps: {maps_found}"
        )

        # 2. get_all_encounters with missing file
        _assert(
            "get_all_encounters: missing file returns []",
            get_all_encounters("/nonexistent/path") == [],
            "expected []"
        )

        # 3. get_encounters_for_map: route101 returns 1 entry
        r101 = get_encounters_for_map(game, "MAP_ROUTE101")
        _assert(
            "get_encounters_for_map: MAP_ROUTE101 returns 1 entry",
            len(r101) == 1 and r101[0].get("base_label") == "gRoute101",
            f"got {r101}"
        )

        # 4. get_encounters_for_map: nonexistent map
        _assert(
            "get_encounters_for_map: MAP_NONEXISTENT returns []",
            get_encounters_for_map(game, "MAP_NONEXISTENT") == [],
            "expected []"
        )

        # 5. get_encounter_types: route102 has land_mons and water_mons
        r102 = get_encounters_for_map(game, "MAP_ROUTE102")[0]
        types_102 = get_encounter_types(r102)
        _assert(
            "get_encounter_types: route102 has land_mons and water_mons",
            types_102 == ["land_mons", "water_mons"],
            f"got {types_102}"
        )

        # 6. get_encounter_types: route101 has only land_mons
        r101_entry = r101[0]
        types_101 = get_encounter_types(r101_entry)
        _assert(
            "get_encounter_types: route101 has only land_mons",
            types_101 == ["land_mons"],
            f"got {types_101}"
        )

        # 7. get_encounter_species: land_mons returns 2 species dicts
        species = get_encounter_species(r101_entry, "land_mons")
        _assert(
            "get_encounter_species: land_mons returns 2 species",
            len(species) == 2
            and species[0]["species"] == "SPECIES_WURMPLE"
            and species[1]["species"] == "SPECIES_POOCHYENA",
            f"got {species}"
        )

        # 8. get_encounter_species: missing type returns []
        _assert(
            "get_encounter_species: missing type returns []",
            get_encounter_species(r101_entry, "water_mons") == [],
            "expected []"
        )

        # 9. extract_time_suffix: no suffix
        _assert(
            "extract_time_suffix: gRoute101 returns None",
            extract_time_suffix("gRoute101") is None,
            "expected None"
        )

        # 10. extract_time_suffix: Morning
        _assert(
            "extract_time_suffix: gRoute101_Morning returns Morning",
            extract_time_suffix("gRoute101_Morning") == "Morning",
            "expected Morning"
        )

        # 11. extract_time_suffix: Night
        _assert(
            "extract_time_suffix: gRoute101_Night returns Night",
            extract_time_suffix("gRoute101_Night") == "Night",
            "expected Night"
        )

        # 12. get_maps_with_encounters
        all_maps = get_maps_with_encounters(game)
        _assert(
            "get_maps_with_encounters: returns correct set",
            all_maps == {"MAP_ROUTE101", "MAP_ROUTE102", "MAP_ROUTE103"},
            f"got {all_maps}"
        )

        # 13. remove_encounters_for_map: removes MAP_ROUTE101
        clear_project_cache()
        removed = remove_encounters_for_map(game, "MAP_ROUTE101")
        _assert(
            "remove_encounters_for_map: returns 1",
            removed == 1,
            f"expected 1, got {removed}"
        )
        clear_project_cache()
        remaining = get_all_encounters(game)
        _assert(
            "remove_encounters_for_map: file now has 3 entries",
            len(remaining) == 3,
            f"expected 3, got {len(remaining)}"
        )
        _assert(
            "remove_encounters_for_map: MAP_ROUTE101 is gone",
            all(e.get("map") != "MAP_ROUTE101" for e in remaining),
            "MAP_ROUTE101 still present"
        )

        # 14. write_encounters: writes valid JSON, cache invalidated
        clear_project_cache()
        data = load_wild_encounters(game)
        ok = write_encounters(game, data)
        _assert(
            "write_encounters: returns True",
            ok is True,
            f"expected True, got {ok}"
        )
        clear_project_cache()
        reloaded = load_wild_encounters(game)
        _assert(
            "write_encounters: file is valid JSON after write",
            reloaded is not None
            and "wild_encounter_groups" in reloaded,
            f"got {reloaded}"
        )

        # 15. get_encounters_for_map: time-based MAP_ROUTE103 returns 2 entries
        clear_project_cache()
        # Rebuild fixture for route103 tests (route101 was removed above)
        game2 = _make_encounter_tree(tmp + "_tb")
        clear_project_cache()
        r103 = get_encounters_for_map(game2, "MAP_ROUTE103")
        _assert(
            "get_encounters_for_map: MAP_ROUTE103 returns 2 entries",
            len(r103) == 2,
            f"expected 2, got {len(r103)}"
        )

        # 16. extract_time_suffix on time-based entries
        suffixes = sorted([extract_time_suffix(e.get("base_label", ""))
                           for e in r103])
        _assert(
            "extract_time_suffix: time-based entries return Morning and Night",
            suffixes == ["Morning", "Night"],
            f"got {suffixes}"
        )

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if os.path.isdir(tmp + "_tb"):
            shutil.rmtree(tmp + "_tb", ignore_errors=True)
        clear_project_cache()


# ---------------------------------------------------------------------------
# build_trainer_map_index
# ---------------------------------------------------------------------------

def _make_trainer_tree(tmp):
    """Create a game tree with map script files containing trainerbattle calls."""
    game = os.path.join(tmp, "tmi_game")
    maps_dir = os.path.join(game, "data", "maps")

    # Map with .pory trainerbattle calls
    route1 = os.path.join(maps_dir, "Route1")
    os.makedirs(route1)
    with open(os.path.join(route1, "map.json"), "w") as f:
        json.dump({"id": "MAP_ROUTE1", "name": "Route1"}, f)
    with open(os.path.join(route1, "scripts.pory"), "w") as f:
        f.write('script Route1_Trainer1 {\n')
        f.write('    trainerbattle_single(TRAINER_GRUNT_1, Text_Intro, Text_Defeat)\n')
        f.write('}\n')
        f.write('script Route1_Trainer2 {\n')
        f.write('    trainerbattle_double(TRAINER_GRUNT_2, Text_Intro, Text_Defeat, Text_NotEnough)\n')
        f.write('}\n')

    # Map with .inc trainerbattle call
    route2 = os.path.join(maps_dir, "Route2")
    os.makedirs(route2)
    with open(os.path.join(route2, "map.json"), "w") as f:
        json.dump({"id": "MAP_ROUTE2", "name": "Route2"}, f)
    with open(os.path.join(route2, "scripts.inc"), "w") as f:
        f.write('Route2_EventScript_Rival::\n')
        f.write('\ttrainerbattle_single TRAINER_RIVAL_1, Route2_Text_Intro, Route2_Text_Defeat\n')
        f.write('\treturn\n')

    # Map with no trainers
    town = os.path.join(maps_dir, "Town1")
    os.makedirs(town)
    with open(os.path.join(town, "map.json"), "w") as f:
        json.dump({"id": "MAP_TOWN1", "name": "Town1"}, f)
    with open(os.path.join(town, "scripts.pory"), "w") as f:
        f.write('script Town1_NPC {\n')
        f.write('    msgbox("Hello!")\n')
        f.write('}\n')

    # Map with both .pory and .inc referencing same trainer (pory should win)
    route3 = os.path.join(maps_dir, "Route3")
    os.makedirs(route3)
    with open(os.path.join(route3, "map.json"), "w") as f:
        json.dump({"id": "MAP_ROUTE3", "name": "Route3"}, f)
    with open(os.path.join(route3, "scripts.pory"), "w") as f:
        f.write('script Route3_Trainer {\n')
        f.write('    trainerbattle_single(TRAINER_ACE_1, Text_Intro, Text_Defeat)\n')
        f.write('}\n')
    with open(os.path.join(route3, "scripts.inc"), "w") as f:
        f.write('\ttrainerbattle_single TRAINER_ACE_1, Route3_Text_Intro, Route3_Text_Defeat\n')

    return game


def run_trainer_map_index_suite():
    _begin_suite("Project Files  (build_trainer_map_index)")

    try:
        from torch.project_files import build_trainer_map_index, clear_project_cache
    except ImportError as e:
        _skip("all trainer_map_index tests", f"import failed: {e}")
        return

    tmp = tempfile.mkdtemp(prefix="torch_tmi_test_")
    try:
        game = _make_trainer_tree(tmp)
        clear_project_cache()

        map_trainers, trainer_map = build_trainer_map_index(game)

        # 1. Route1 has two trainers
        _assert(
            "build_trainer_map_index: Route1 has 2 trainers",
            sorted(map_trainers.get("Route1", [])) == ["TRAINER_GRUNT_1", "TRAINER_GRUNT_2"],
            f"got: {map_trainers.get('Route1')}"
        )

        # 2. Route2 has one trainer (from .inc)
        _assert(
            "build_trainer_map_index: Route2 has 1 trainer from .inc",
            map_trainers.get("Route2", []) == ["TRAINER_RIVAL_1"],
            f"got: {map_trainers.get('Route2')}"
        )

        # 3. Town1 has no trainers (not in map_trainers)
        _assert(
            "build_trainer_map_index: Town1 has no trainers",
            "Town1" not in map_trainers,
            f"Town1 in map_trainers: {map_trainers.get('Town1')}"
        )

        # 4. Reverse mapping works
        _assert(
            "build_trainer_map_index: TRAINER_GRUNT_1 maps to Route1",
            trainer_map.get("TRAINER_GRUNT_1") == "Route1",
            f"got: {trainer_map.get('TRAINER_GRUNT_1')}"
        )
        _assert(
            "build_trainer_map_index: TRAINER_RIVAL_1 maps to Route2",
            trainer_map.get("TRAINER_RIVAL_1") == "Route2",
            f"got: {trainer_map.get('TRAINER_RIVAL_1')}"
        )

        # 5. Pory takes precedence over .inc (Route3 — both have TRAINER_ACE_1)
        _assert(
            "build_trainer_map_index: TRAINER_ACE_1 mapped to Route3",
            trainer_map.get("TRAINER_ACE_1") == "Route3",
            f"got: {trainer_map.get('TRAINER_ACE_1')}"
        )
        _assert(
            "build_trainer_map_index: Route3 has exactly 1 trainer (no dup from .inc)",
            map_trainers.get("Route3", []) == ["TRAINER_ACE_1"],
            f"got: {map_trainers.get('Route3')}"
        )

        # 6. Cache works (second call returns same object)
        result2_mt, result2_tm = build_trainer_map_index(game)
        _assert(
            "build_trainer_map_index: cached (same object)",
            result2_mt is map_trainers and result2_tm is trainer_map,
            "second call returned different object"
        )

        # 7. Missing game path returns empty
        clear_project_cache()
        mt, tm = build_trainer_map_index("/nonexistent/path")
        _assert(
            "build_trainer_map_index: missing path returns empty dicts",
            mt == {} and tm == {},
            f"got: ({mt}, {tm})"
        )

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()
