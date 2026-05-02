"""Tests for heal_locations module."""
import os
import json
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    """Entry point called by run_tests.py."""
    _begin_suite("Heal Locations")

    try:
        from torch.project_files import (
            load_heal_locations, write_heal_locations, folder_to_map_const,
        )
        from torch.heal_locations import (
            _map_const_to_heal_id, _folder_to_heal_id, _validate_coordinate,
            _find_pokecenter_warps, _scan_maps_for_heal, heal_command,
            _heal_id_to_display, _map_const_to_display, _map_const_to_folder,
            _detect_heal_coords, _detect_respawn_npc, _scan_drift,
            _auto_add_heal, _validate_location,
        )
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # -- ID generation ---------------------------------------------------------

    try:
        result = _map_const_to_heal_id("MAP_PETALBURG_CITY")
        _assert("id_from_map_const: PetalburgCity",
                result == "HEAL_LOCATION_PETALBURG_CITY",
                f"got {result}")
    except Exception as e:
        _fail("id_from_map_const: PetalburgCity", str(e))

    try:
        result = _map_const_to_heal_id("MAP_SLATEPORT_CITY")
        _assert("id_from_map_const: SlateportCity",
                result == "HEAL_LOCATION_SLATEPORT_CITY",
                f"got {result}")
    except Exception as e:
        _fail("id_from_map_const: SlateportCity", str(e))

    try:
        result = _folder_to_heal_id("PetalburgCity")
        _assert("id_from_folder: PetalburgCity",
                result == "HEAL_LOCATION_PETALBURG_CITY",
                f"got {result}")
    except Exception as e:
        _fail("id_from_folder: PetalburgCity", str(e))

    try:
        result = _folder_to_heal_id("Route101")
        _assert("id_from_folder: Route101",
                result == "HEAL_LOCATION_ROUTE101",
                f"got {result}")
    except Exception as e:
        _fail("id_from_folder: Route101", str(e))

    try:
        result = _folder_to_heal_id("ArtisanCave_1F")
        _assert("id_from_folder: ArtisanCave_1F",
                result == "HEAL_LOCATION_ARTISAN_CAVE_1F",
                f"got {result}")
    except Exception as e:
        _fail("id_from_folder: ArtisanCave_1F", str(e))

    # -- Coordinate validation -------------------------------------------------

    try:
        _assert("validate_coordinate: valid int", _validate_coordinate("20") == 20,
                f"got {_validate_coordinate('20')}")
        _assert("validate_coordinate: zero", _validate_coordinate("0") == 0,
                f"got {_validate_coordinate('0')}")
        _assert("validate_coordinate: negative", _validate_coordinate("-5") == -5,
                f"got {_validate_coordinate('-5')}")
        _assert("validate_coordinate: empty -> None",
                _validate_coordinate("") is None, "expected None")
        _assert("validate_coordinate: non-numeric -> None",
                _validate_coordinate("abc") is None, "expected None")
        _assert("validate_coordinate: float -> None",
                _validate_coordinate("3.5") is None, "expected None")
    except Exception as e:
        _fail("validate_coordinate", str(e))

    # -- JSON load/write -------------------------------------------------------

    tmp_dir = tempfile.mkdtemp(prefix="torch_heal_test_")
    try:
        # Create directory structure
        data_dir = os.path.join(tmp_dir, "src", "data")
        os.makedirs(data_dir, exist_ok=True)

        # Write a test heal_locations.json
        test_data = {
            "heal_locations": [
                {
                    "id": "HEAL_LOCATION_TEST_TOWN",
                    "map": "MAP_TEST_TOWN",
                    "x": 10,
                    "y": 20,
                    "respawn_map": "MAP_TEST_TOWN_POKEMON_CENTER_1F",
                    "respawn_npc": "LOCALID_TEST_NURSE",
                },
                {
                    "id": "HEAL_LOCATION_TEST_CITY",
                    "map": "MAP_TEST_CITY",
                    "x": 5,
                    "y": 15,
                    "respawn_map": "MAP_TEST_CITY_POKEMON_CENTER_1F",
                    "respawn_npc": "LOCALID_TEST_CITY_NURSE",
                    "respawn_x": 3,
                    "respawn_y": 7,
                },
            ]
        }
        filepath = os.path.join(data_dir, "heal_locations.json")
        with open(filepath, "w") as f:
            json.dump(test_data, f, indent=2)

        # Test load
        locs = load_heal_locations(tmp_dir)
        _assert("load: returns list", isinstance(locs, list),
                f"got {type(locs)}")
        _assert("load: correct count", len(locs) == 2,
                f"got {len(locs)}")
        _assert("load: first entry id",
                locs[0]["id"] == "HEAL_LOCATION_TEST_TOWN",
                f"got {locs[0].get('id')}")
        _assert("load: second entry has respawn_x",
                locs[1].get("respawn_x") == 3,
                f"got {locs[1].get('respawn_x')}")

        # Test write (add a new entry)
        new_entry = {
            "id": "HEAL_LOCATION_NEW_TOWN",
            "map": "MAP_NEW_TOWN",
            "x": 1,
            "y": 2,
            "respawn_map": "MAP_NEW_TOWN_POKEMON_CENTER_1F",
            "respawn_npc": "LOCALID_NEW_NURSE",
        }
        new_list = list(locs) + [new_entry]
        ok = write_heal_locations(tmp_dir, new_list)
        _assert("write: returns True", ok is True, f"got {ok}")

        # Reload and verify
        locs2 = load_heal_locations(tmp_dir)
        _assert("write: count increased", len(locs2) == 3,
                f"got {len(locs2)}")
        _assert("write: new entry present",
                locs2[2]["id"] == "HEAL_LOCATION_NEW_TOWN",
                f"got {locs2[2].get('id')}")

        # Verify JSON structure on disk
        with open(filepath) as f:
            raw = json.load(f)
        _assert("write: wrapper key preserved",
                "heal_locations" in raw,
                f"keys: {list(raw.keys())}")

    except Exception as e:
        _fail("json_load_write", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Load from missing/corrupt file ---------------------------------------

    tmp_dir2 = tempfile.mkdtemp(prefix="torch_heal_test2_")
    try:
        result = load_heal_locations(tmp_dir2)
        _assert("load: missing file -> None", result is None,
                f"got {result}")
    except Exception as e:
        _fail("load: missing file", str(e))
    finally:
        shutil.rmtree(tmp_dir2, ignore_errors=True)

    tmp_dir3 = tempfile.mkdtemp(prefix="torch_heal_test3_")
    try:
        data_dir = os.path.join(tmp_dir3, "src", "data")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "heal_locations.json"), "w") as f:
            f.write("{invalid json")
        result = load_heal_locations(tmp_dir3)
        _assert("load: corrupt JSON -> None", result is None,
                f"got {result}")
    except Exception as e:
        _fail("load: corrupt JSON", str(e))
    finally:
        shutil.rmtree(tmp_dir3, ignore_errors=True)

    # -- Delete: remove entry, verify count decreases --------------------------

    tmp_dir4 = tempfile.mkdtemp(prefix="torch_heal_test4_")
    try:
        data_dir = os.path.join(tmp_dir4, "src", "data")
        os.makedirs(data_dir, exist_ok=True)
        test_data = {
            "heal_locations": [
                {"id": "HEAL_LOCATION_A", "map": "MAP_A", "x": 1, "y": 2,
                 "respawn_map": "MAP_A_PC", "respawn_npc": "LOCALID_A"},
                {"id": "HEAL_LOCATION_B", "map": "MAP_B", "x": 3, "y": 4,
                 "respawn_map": "MAP_B_PC", "respawn_npc": "LOCALID_B"},
                {"id": "HEAL_LOCATION_C", "map": "MAP_C", "x": 5, "y": 6,
                 "respawn_map": "MAP_C_PC", "respawn_npc": "LOCALID_C"},
            ]
        }
        with open(os.path.join(data_dir, "heal_locations.json"), "w") as f:
            json.dump(test_data, f)

        locs = load_heal_locations(tmp_dir4)
        _assert("delete: initial count", len(locs) == 3, f"got {len(locs)}")

        # Simulate delete of index 1 (HEAL_LOCATION_B)
        new_list = [l for i, l in enumerate(locs) if i != 1]
        ok = write_heal_locations(tmp_dir4, new_list)
        _assert("delete: write success", ok is True, f"got {ok}")

        locs2 = load_heal_locations(tmp_dir4)
        _assert("delete: count decreased", len(locs2) == 2, f"got {len(locs2)}")
        ids = [l["id"] for l in locs2]
        _assert("delete: correct entry removed",
                "HEAL_LOCATION_B" not in ids,
                f"remaining: {ids}")
        _assert("delete: other entries preserved",
                "HEAL_LOCATION_A" in ids and "HEAL_LOCATION_C" in ids,
                f"remaining: {ids}")
    except Exception as e:
        _fail("delete", str(e))
    finally:
        shutil.rmtree(tmp_dir4, ignore_errors=True)

    # -- Global scan suggestion logic ------------------------------------------

    tmp_dir5 = tempfile.mkdtemp(prefix="torch_heal_test5_")
    try:
        # Create data/maps with a town that has no heal, and a city that does
        data_dir = os.path.join(tmp_dir5, "src", "data")
        os.makedirs(data_dir, exist_ok=True)

        maps_dir = os.path.join(tmp_dir5, "data", "maps")

        # Town without heal location
        town_dir = os.path.join(maps_dir, "TestTown")
        os.makedirs(town_dir, exist_ok=True)
        with open(os.path.join(town_dir, "map.json"), "w") as f:
            json.dump({"id": "MAP_TEST_TOWN", "name": "TestTown",
                        "map_type": "MAP_TYPE_TOWN",
                        "layout": "LAYOUT_TEST_TOWN"}, f)

        # City with heal location
        city_dir = os.path.join(maps_dir, "TestCity")
        os.makedirs(city_dir, exist_ok=True)
        with open(os.path.join(city_dir, "map.json"), "w") as f:
            json.dump({"id": "MAP_TEST_CITY", "name": "TestCity",
                        "map_type": "MAP_TYPE_CITY",
                        "layout": "LAYOUT_TEST_CITY"}, f)

        # Route (should be ignored)
        route_dir = os.path.join(maps_dir, "Route1")
        os.makedirs(route_dir, exist_ok=True)
        with open(os.path.join(route_dir, "map.json"), "w") as f:
            json.dump({"id": "MAP_ROUTE1", "name": "Route1",
                        "map_type": "MAP_TYPE_ROUTE",
                        "layout": "LAYOUT_ROUTE1"}, f)

        # Heal locations — only city has one
        heal_data = {
            "heal_locations": [
                {"id": "HEAL_LOCATION_TEST_CITY", "map": "MAP_TEST_CITY",
                 "x": 1, "y": 2, "respawn_map": "MAP_PC", "respawn_npc": "NPC"},
            ]
        }
        with open(os.path.join(data_dir, "heal_locations.json"), "w") as f:
            json.dump(heal_data, f)

        results = _scan_maps_for_heal(tmp_dir5)
        _assert("scan: finds city/town only",
                len(results) == 2,
                f"got {len(results)} results: {results}")

        # Check town is flagged as missing
        town_result = [r for r in results if r[0] == "TestTown"]
        _assert("scan: town missing heal",
                len(town_result) == 1 and town_result[0][2] is False,
                f"got {town_result}")

        # Check city is OK
        city_result = [r for r in results if r[0] == "TestCity"]
        _assert("scan: city has heal",
                len(city_result) == 1 and city_result[0][2] is True,
                f"got {city_result}")

    except Exception as e:
        _fail("global_scan", str(e))
    finally:
        shutil.rmtree(tmp_dir5, ignore_errors=True)

    # -- Pokecenter warp detection ---------------------------------------------

    tmp_dir6 = tempfile.mkdtemp(prefix="torch_heal_test6_")
    try:
        maps_dir = os.path.join(tmp_dir6, "data", "maps")
        town_dir = os.path.join(maps_dir, "WarpTown")
        os.makedirs(town_dir, exist_ok=True)
        with open(os.path.join(town_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_WARP_TOWN", "name": "WarpTown",
                "map_type": "MAP_TYPE_TOWN",
                "layout": "LAYOUT_WARP_TOWN",
                "warp_events": [
                    {"x": 1, "y": 2, "dest_map": "MAP_WARP_TOWN_HOUSE1",
                     "dest_warp_id": 0},
                    {"x": 3, "y": 4, "dest_map": "MAP_WARP_TOWN_POKEMON_CENTER_1F",
                     "dest_warp_id": 0},
                ]
            }, f)

        pcs = _find_pokecenter_warps(tmp_dir6, "WarpTown")
        _assert("pokecenter_warps: finds PC",
                len(pcs) == 1 and "POKEMON_CENTER" in pcs[0],
                f"got {pcs}")

        # Map with no PC warps
        nopc_dir = os.path.join(maps_dir, "NoPcTown")
        os.makedirs(nopc_dir, exist_ok=True)
        with open(os.path.join(nopc_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_NO_PC_TOWN", "name": "NoPcTown",
                "map_type": "MAP_TYPE_TOWN",
                "layout": "LAYOUT_NO_PC_TOWN",
                "warp_events": [
                    {"x": 1, "y": 2, "dest_map": "MAP_NO_PC_TOWN_HOUSE1",
                     "dest_warp_id": 0},
                ]
            }, f)

        pcs2 = _find_pokecenter_warps(tmp_dir6, "NoPcTown")
        _assert("pokecenter_warps: no PC -> empty",
                len(pcs2) == 0,
                f"got {pcs2}")

    except Exception as e:
        _fail("pokecenter_warps", str(e))
    finally:
        shutil.rmtree(tmp_dir6, ignore_errors=True)

    # -- Display helpers ----------------------------------------------------------

    try:
        result = _heal_id_to_display("HEAL_LOCATION_PETALBURG_CITY")
        _assert("display: heal_id Petalburg",
                result == "Petalburg City", f"got {result!r}")
    except Exception as e:
        _fail("display: heal_id Petalburg", str(e))

    try:
        result = _heal_id_to_display("HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F")
        _assert("display: heal_id with 2F suffix",
                result == "Littleroot Town Brendans House 2F", f"got {result!r}")
    except Exception as e:
        _fail("display: heal_id with 2F suffix", str(e))

    try:
        result = _map_const_to_display("MAP_PETALBURG_CITY_POKEMON_CENTER_1F")
        _assert("display: map_const PC",
                result == "Petalburg City Pokemon Center 1F", f"got {result!r}")
    except Exception as e:
        _fail("display: map_const PC", str(e))

    # -- Map const to folder conversion -------------------------------------------

    tmp_folder = tempfile.mkdtemp(prefix="torch_heal_folder_")
    try:
        # Create map folders so disk lookup works
        maps_dir = os.path.join(tmp_folder, "data", "maps")
        for d in ("PetalburgCity", "PetalburgCity_PokemonCenter_1F", "Route101"):
            os.makedirs(os.path.join(maps_dir, d), exist_ok=True)

        result = _map_const_to_folder("MAP_PETALBURG_CITY", tmp_folder)
        _assert("folder: PetalburgCity",
                result == "PetalburgCity", f"got {result!r}")

        result = _map_const_to_folder("MAP_PETALBURG_CITY_POKEMON_CENTER_1F", tmp_folder)
        _assert("folder: PetalburgCity_PokemonCenter_1F",
                result == "PetalburgCity_PokemonCenter_1F", f"got {result!r}")

        result = _map_const_to_folder("MAP_ROUTE101", tmp_folder)
        _assert("folder: Route101",
                result == "Route101", f"got {result!r}")

        # Heuristic fallback (no game_path): simple case still works
        result = _map_const_to_folder("MAP_PETALBURG_CITY")
        _assert("folder: heuristic PetalburgCity",
                result == "PetalburgCity", f"got {result!r}")
    except Exception as e:
        _fail("folder conversion", str(e))
    finally:
        shutil.rmtree(tmp_folder, ignore_errors=True)

    # -- Coordinate auto-detection ------------------------------------------------

    tmp_dir7 = tempfile.mkdtemp(prefix="torch_heal_test7_")
    try:
        maps_dir = os.path.join(tmp_dir7, "data", "maps")

        # Map with PC warp at (22, 7) -> detect (22, 8)
        town_dir = os.path.join(maps_dir, "DetectTown")
        os.makedirs(town_dir, exist_ok=True)
        with open(os.path.join(town_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_DETECT_TOWN", "name": "DetectTown",
                "warp_events": [
                    {"x": 5, "y": 3, "dest_map": "MAP_DETECT_TOWN_HOUSE",
                     "dest_warp_id": 0},
                    {"x": 22, "y": 7, "dest_map": "MAP_DETECT_TOWN_POKEMON_CENTER_1F",
                     "dest_warp_id": 0},
                ]
            }, f)

        coords = _detect_heal_coords(tmp_dir7, "DetectTown")
        _assert("detect_coords: warp+1",
                coords == (22, 8), f"got {coords}")

        # Map with no PC warps -> None
        nopc_dir = os.path.join(maps_dir, "NoPcVillage")
        os.makedirs(nopc_dir, exist_ok=True)
        with open(os.path.join(nopc_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_NO_PC_VILLAGE", "name": "NoPcVillage",
                "warp_events": [
                    {"x": 1, "y": 2, "dest_map": "MAP_NO_PC_VILLAGE_HOUSE",
                     "dest_warp_id": 0},
                ]
            }, f)

        coords2 = _detect_heal_coords(tmp_dir7, "NoPcVillage")
        _assert("detect_coords: no PC -> None",
                coords2 is None, f"got {coords2}")

        # Map with multiple PC warps -> returns first
        multi_dir = os.path.join(maps_dir, "MultiPcTown")
        os.makedirs(multi_dir, exist_ok=True)
        with open(os.path.join(multi_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_MULTI_PC_TOWN", "name": "MultiPcTown",
                "warp_events": [
                    {"x": 10, "y": 5, "dest_map": "MAP_MULTI_PC_TOWN_POKEMON_CENTER_1F",
                     "dest_warp_id": 0},
                    {"x": 20, "y": 15, "dest_map": "MAP_MULTI_PC_TOWN_POKEMON_CENTER_2F",
                     "dest_warp_id": 0},
                ]
            }, f)

        coords3 = _detect_heal_coords(tmp_dir7, "MultiPcTown")
        _assert("detect_coords: multiple PCs -> first",
                coords3 == (10, 6), f"got {coords3}")

    except Exception as e:
        _fail("detect_coords", str(e))
    finally:
        shutil.rmtree(tmp_dir7, ignore_errors=True)

    # -- Nurse auto-detection -----------------------------------------------------

    tmp_dir8 = tempfile.mkdtemp(prefix="torch_heal_test8_")
    try:
        maps_dir = os.path.join(tmp_dir8, "data", "maps")

        # PC interior with nurse
        pc_dir = os.path.join(maps_dir, "TestTown_PokemonCenter_1F")
        os.makedirs(pc_dir, exist_ok=True)
        with open(os.path.join(pc_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_TEST_TOWN_POKEMON_CENTER_1F",
                "object_events": [
                    {"graphics_id": "OBJ_EVENT_GFX_NURSE",
                     "local_id": "LOCALID_TEST_NURSE", "x": 7, "y": 3},
                    {"graphics_id": "OBJ_EVENT_GFX_MAN_1",
                     "local_id": 2, "x": 5, "y": 6},
                ]
            }, f)

        npc = _detect_respawn_npc(tmp_dir8, "TestTown_PokemonCenter_1F")
        _assert("detect_npc: finds nurse",
                npc == "LOCALID_TEST_NURSE", f"got {npc!r}")

        # PC interior without nurse
        nopc_dir = os.path.join(maps_dir, "EmptyCenter_1F")
        os.makedirs(nopc_dir, exist_ok=True)
        with open(os.path.join(nopc_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_EMPTY_CENTER_1F",
                "object_events": [
                    {"graphics_id": "OBJ_EVENT_GFX_MAN_1",
                     "local_id": 1, "x": 5, "y": 6},
                ]
            }, f)

        npc2 = _detect_respawn_npc(tmp_dir8, "EmptyCenter_1F")
        _assert("detect_npc: no nurse -> None",
                npc2 is None, f"got {npc2!r}")

    except Exception as e:
        _fail("detect_npc", str(e))
    finally:
        shutil.rmtree(tmp_dir8, ignore_errors=True)

    # -- Drift detection ----------------------------------------------------------

    tmp_dir9 = tempfile.mkdtemp(prefix="torch_heal_test9_")
    try:
        maps_dir = os.path.join(tmp_dir9, "data", "maps")
        data_dir = os.path.join(tmp_dir9, "src", "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create overworld map with PC warp at (15, 9) -> heal at (15, 10)
        town_dir = os.path.join(maps_dir, "DriftTown")
        os.makedirs(town_dir, exist_ok=True)
        with open(os.path.join(town_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_DRIFT_TOWN", "name": "DriftTown",
                "warp_events": [
                    {"x": 15, "y": 9, "dest_map": "MAP_DRIFT_TOWN_POKEMON_CENTER_1F",
                     "dest_warp_id": 0},
                ]
            }, f)

        # Location with correct coords -> no drift
        # Location with wrong coords -> drift
        heal_data = {
            "heal_locations": [
                {"id": "HEAL_LOCATION_DRIFT_TOWN", "map": "MAP_DRIFT_TOWN",
                 "x": 15, "y": 10,
                 "respawn_map": "MAP_DRIFT_TOWN_PC", "respawn_npc": "1"},
                {"id": "HEAL_LOCATION_DRIFT_TOWN_OLD", "map": "MAP_DRIFT_TOWN",
                 "x": 15, "y": 12,
                 "respawn_map": "MAP_DRIFT_TOWN_PC", "respawn_npc": "1"},
            ]
        }
        with open(os.path.join(data_dir, "heal_locations.json"), "w") as f:
            json.dump(heal_data, f)

        from torch.project_files import clear_project_cache
        clear_project_cache()

        locs = [
            {"id": "HEAL_LOCATION_DRIFT_TOWN", "map": "MAP_DRIFT_TOWN",
             "x": 15, "y": 10,
             "respawn_map": "MAP_DRIFT_TOWN_PC", "respawn_npc": "1"},
            {"id": "HEAL_LOCATION_DRIFT_TOWN_OLD", "map": "MAP_DRIFT_TOWN",
             "x": 15, "y": 12,
             "respawn_map": "MAP_DRIFT_TOWN_PC", "respawn_npc": "1"},
        ]
        drift = _scan_drift(tmp_dir9, locs)
        _assert("drift: correct coords -> no drift for first",
                not any(d[1] == "HEAL_LOCATION_DRIFT_TOWN" for d in drift),
                f"got {drift}")
        _assert("drift: wrong coords -> drift reported",
                any(d[1] == "HEAL_LOCATION_DRIFT_TOWN_OLD" for d in drift),
                f"got {drift}")

        # Check drift details
        drifted = [d for d in drift if d[1] == "HEAL_LOCATION_DRIFT_TOWN_OLD"][0]
        _assert("drift: old coords correct",
                drifted[2] == (15, 12), f"got {drifted[2]}")
        _assert("drift: new coords correct",
                drifted[3] == (15, 10), f"got {drifted[3]}")

        # User override flag
        locs[1]["_user_override"] = True
        drift2 = _scan_drift(tmp_dir9, locs)
        drifted2 = [d for d in drift2 if d[1] == "HEAL_LOCATION_DRIFT_TOWN_OLD"][0]
        _assert("drift: user_override reported",
                drifted2[4] is True, f"got {drifted2[4]}")

    except Exception as e:
        _fail("drift", str(e))
    finally:
        shutil.rmtree(tmp_dir9, ignore_errors=True)

    # -- Scan has_pc field --------------------------------------------------------

    tmp_dir10 = tempfile.mkdtemp(prefix="torch_heal_test10_")
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()

        data_dir = os.path.join(tmp_dir10, "src", "data")
        os.makedirs(data_dir, exist_ok=True)
        maps_dir = os.path.join(tmp_dir10, "data", "maps")

        # Town WITH a PC warp
        pc_town = os.path.join(maps_dir, "PcTown")
        os.makedirs(pc_town, exist_ok=True)
        with open(os.path.join(pc_town, "map.json"), "w") as f:
            json.dump({"id": "MAP_PC_TOWN", "name": "PcTown",
                        "map_type": "MAP_TYPE_TOWN",
                        "warp_events": [
                            {"x": 5, "y": 3,
                             "dest_map": "MAP_PC_TOWN_POKEMON_CENTER_1F",
                             "dest_warp_id": 0}
                        ]}, f)

        # Town WITHOUT a PC warp (like LakeElixSouth)
        no_pc = os.path.join(maps_dir, "NoPcArea")
        os.makedirs(no_pc, exist_ok=True)
        with open(os.path.join(no_pc, "map.json"), "w") as f:
            json.dump({"id": "MAP_NO_PC_AREA", "name": "NoPcArea",
                        "map_type": "MAP_TYPE_TOWN",
                        "warp_events": [
                            {"x": 1, "y": 2, "dest_map": "MAP_SOME_HOUSE",
                             "dest_warp_id": 0}
                        ]}, f)

        heal_data = {"heal_locations": []}
        with open(os.path.join(data_dir, "heal_locations.json"), "w") as f:
            json.dump(heal_data, f)

        results = _scan_maps_for_heal(tmp_dir10)
        pc_result = [r for r in results if r[0] == "PcTown"]
        nopc_result = [r for r in results if r[0] == "NoPcArea"]

        _assert("scan: town with PC has has_pc=True",
                len(pc_result) == 1 and pc_result[0][3] is True,
                f"got {pc_result}")
        _assert("scan: town without PC has has_pc=False",
                len(nopc_result) == 1 and nopc_result[0][3] is False,
                f"got {nopc_result}")

    except Exception as e:
        _fail("scan_has_pc", str(e))
    finally:
        shutil.rmtree(tmp_dir10, ignore_errors=True)

    # -- Auto-add from scan -------------------------------------------------------

    tmp_dir11 = tempfile.mkdtemp(prefix="torch_heal_test11_")
    try:
        clear_project_cache()

        maps_dir = os.path.join(tmp_dir11, "data", "maps")

        # Overworld with PC warp
        town_dir = os.path.join(maps_dir, "AutoTown")
        os.makedirs(town_dir, exist_ok=True)
        with open(os.path.join(town_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_AUTO_TOWN", "name": "AutoTown",
                "warp_events": [
                    {"x": 10, "y": 5,
                     "dest_map": "MAP_AUTO_TOWN_POKEMON_CENTER_1F",
                     "dest_warp_id": 0}
                ]
            }, f)

        # PC interior with nurse (no local_id field, like ShirubeTown)
        pc_dir = os.path.join(maps_dir, "AutoTown_PokemonCenter_1F")
        os.makedirs(pc_dir, exist_ok=True)
        with open(os.path.join(pc_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_AUTO_TOWN_POKEMON_CENTER_1F",
                "object_events": [
                    {"graphics_id": "OBJ_EVENT_GFX_NURSE",
                     "x": 7, "y": 2},
                ]
            }, f)

        entry = _auto_add_heal(tmp_dir11, "AutoTown")
        _assert("auto_add: returns entry",
                entry is not None, "got None")
        _assert("auto_add: correct id",
                entry["id"] == "HEAL_LOCATION_AUTO_TOWN",
                f"got {entry.get('id')}")
        _assert("auto_add: coords are warp+1",
                entry["x"] == 10 and entry["y"] == 6,
                f"got ({entry.get('x')}, {entry.get('y')})")
        _assert("auto_add: respawn map detected",
                entry["respawn_map"] == "MAP_AUTO_TOWN_POKEMON_CENTER_1F",
                f"got {entry.get('respawn_map')}")
        _assert("auto_add: nurse npc is 1",
                entry["respawn_npc"] == "1",
                f"got {entry.get('respawn_npc')!r}")

        # Map with no PC -> None
        entry2 = _auto_add_heal(tmp_dir11, "NonExistent")
        _assert("auto_add: no map -> None",
                entry2 is None, f"got {entry2}")

    except Exception as e:
        _fail("auto_add", str(e))
    finally:
        shutil.rmtree(tmp_dir11, ignore_errors=True)

    # -- Custom entry (no respawn_map) round-trip ---------------------------------

    tmp_dir12 = tempfile.mkdtemp(prefix="torch_heal_test12_")
    try:
        clear_project_cache()
        data_dir = os.path.join(tmp_dir12, "src", "data")
        os.makedirs(data_dir, exist_ok=True)

        # Write a custom entry without respawn data
        test_data = {
            "heal_locations": [
                {
                    "id": "HEAL_LOCATION_PLAYER_BEDROOM",
                    "map": "MAP_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F",
                    "x": 4,
                    "y": 2,
                },
                {
                    "id": "HEAL_LOCATION_TEST_CITY",
                    "map": "MAP_TEST_CITY",
                    "x": 10,
                    "y": 20,
                    "respawn_map": "MAP_TEST_CITY_POKEMON_CENTER_1F",
                    "respawn_npc": "1",
                },
            ]
        }
        filepath = os.path.join(data_dir, "heal_locations.json")
        with open(filepath, "w") as f:
            json.dump(test_data, f, indent=2)

        # Load
        locs = load_heal_locations(tmp_dir12)
        _assert("custom_entry: load count", len(locs) == 2,
                f"got {len(locs)}")
        _assert("custom_entry: no respawn_map key",
                "respawn_map" not in locs[0],
                f"keys: {list(locs[0].keys())}")
        _assert("custom_entry: has id/map/x/y",
                all(k in locs[0] for k in ("id", "map", "x", "y")),
                f"keys: {list(locs[0].keys())}")

        # Write back and reload (round-trip)
        ok = write_heal_locations(tmp_dir12, locs)
        _assert("custom_entry: write ok", ok is True, f"got {ok}")

        clear_project_cache()
        locs2 = load_heal_locations(tmp_dir12)
        _assert("custom_entry: round-trip count", len(locs2) == 2,
                f"got {len(locs2)}")
        _assert("custom_entry: round-trip no respawn_map",
                "respawn_map" not in locs2[0],
                f"keys: {list(locs2[0].keys())}")
        _assert("custom_entry: round-trip values preserved",
                locs2[0]["x"] == 4 and locs2[0]["y"] == 2,
                f"got ({locs2[0].get('x')}, {locs2[0].get('y')})")

    except Exception as e:
        _fail("custom_entry_roundtrip", str(e))
    finally:
        shutil.rmtree(tmp_dir12, ignore_errors=True)

    # -- Validate custom entry (no respawn warnings) ------------------------------

    tmp_dir13 = tempfile.mkdtemp(prefix="torch_heal_test13_")
    try:
        maps_dir = os.path.join(tmp_dir13, "data", "maps")
        # Create the map folder so map-exists check passes
        os.makedirs(os.path.join(maps_dir, "PlayerHouse_2F"), exist_ok=True)
        with open(os.path.join(maps_dir, "PlayerHouse_2F", "map.json"), "w") as f:
            json.dump({"id": "MAP_PLAYER_HOUSE_2F", "name": "PlayerHouse_2F"}, f)

        custom_entry = {
            "id": "HEAL_LOCATION_PLAYER_HOUSE_2F",
            "map": "MAP_PLAYER_HOUSE_2F",
            "x": 3,
            "y": 5,
        }
        warns = _validate_location(tmp_dir13, custom_entry)
        _assert("validate_custom: no warnings",
                len(warns) == 0,
                f"got {warns}")

        # Compare: a PC entry with bogus respawn SHOULD warn
        pc_entry = {
            "id": "HEAL_LOCATION_PLAYER_HOUSE_2F",
            "map": "MAP_PLAYER_HOUSE_2F",
            "x": 3,
            "y": 5,
            "respawn_map": "MAP_NONEXISTENT_PC",
            "respawn_npc": "1",
        }
        warns2 = _validate_location(tmp_dir13, pc_entry)
        _assert("validate_pc_entry: warns about bad respawn",
                len(warns2) > 0,
                f"got {warns2}")

    except Exception as e:
        _fail("validate_custom", str(e))
    finally:
        shutil.rmtree(tmp_dir13, ignore_errors=True)

    # -- auto_add_heal: no PC warps -> None (sanity) ------------------------------

    tmp_dir14 = tempfile.mkdtemp(prefix="torch_heal_test14_")
    try:
        clear_project_cache()
        maps_dir = os.path.join(tmp_dir14, "data", "maps")
        # Map with no PC warps
        house_dir = os.path.join(maps_dir, "PlayerHouse")
        os.makedirs(house_dir, exist_ok=True)
        with open(os.path.join(house_dir, "map.json"), "w") as f:
            json.dump({
                "id": "MAP_PLAYER_HOUSE", "name": "PlayerHouse",
                "warp_events": [
                    {"x": 1, "y": 2, "dest_map": "MAP_LITTLEROOT_TOWN",
                     "dest_warp_id": 0}
                ]
            }, f)

        entry = _auto_add_heal(tmp_dir14, "PlayerHouse")
        _assert("auto_add_no_pc: returns None",
                entry is None, f"got {entry}")

    except Exception as e:
        _fail("auto_add_no_pc", str(e))
    finally:
        shutil.rmtree(tmp_dir14, ignore_errors=True)

    # -- heal_command is callable -----------------------------------------------

    try:
        _assert("heal_command: callable", callable(heal_command), "not callable")
    except Exception as e:
        _fail("heal_command: callable", str(e))
