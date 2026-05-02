"""Cleanup Scanner suite -- tests SCORCH Scanner pure-logic functions."""
import os
import json
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Cleanup Scanner")

    try:
        from torch.cleanup_scanner import (
            CATEGORIES, CATEGORY_IDS, _category_by_id,
            map_const_to_folder, _map_const_to_folder,
            RemovalItem, RemovalPlan, SAFE, BLOCKED, CAUTION,
            _load_all_trainer_consts, _classify_trainers,
            _VANILLA_TRAINER_THRESHOLD, _META_DEFINES,
            _classify_encounters, _load_encounters,
            CrossRefScanner,
            _extract_script_labels,
            _detect_frontier,
            _find_tilesets_with_c_source_refs,
        )
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # ==================================================================
    # 1. Pure converters (~8 tests)
    # ==================================================================

    # 1.1: _category_by_id valid id
    try:
        cat = _category_by_id("maps")
        _assert("category_by_id: valid id returns dict",
                cat is not None and cat["id"] == "maps",
                f"got {cat!r}")
    except Exception as e:
        _fail("category_by_id: valid id returns dict", str(e))

    # 1.2: _category_by_id invalid id
    try:
        _assert("category_by_id: invalid id returns None",
                _category_by_id("fake") is None,
                "expected None for unknown id")
    except Exception as e:
        _fail("category_by_id: invalid id returns None", str(e))

    # 1.3: map_const_to_folder: MAP_PETALBURG_CITY
    try:
        result = map_const_to_folder("MAP_PETALBURG_CITY")
        _assert("map_const_to_folder: MAP_PETALBURG_CITY -> PetalburgCity",
                result == "PetalburgCity",
                f"got {result!r}")
    except Exception as e:
        _fail("map_const_to_folder: MAP_PETALBURG_CITY", str(e))

    # 1.4: map_const_to_folder: MAP_ROUTE_101
    try:
        result = map_const_to_folder("MAP_ROUTE_101")
        _assert("map_const_to_folder: MAP_ROUTE_101 -> Route101",
                result == "Route101",
                f"got {result!r}")
    except Exception as e:
        _fail("map_const_to_folder: MAP_ROUTE_101", str(e))

    # 1.5: map_const_to_folder: empty string
    try:
        result = map_const_to_folder("")
        _assert("map_const_to_folder: empty string -> empty",
                result == "",
                f"got {result!r}")
    except Exception as e:
        _fail("map_const_to_folder: empty string", str(e))

    # 1.6: map_const_to_folder: None
    try:
        result = map_const_to_folder(None)
        _assert("map_const_to_folder: None -> empty",
                result == "",
                f"got {result!r}")
    except Exception as e:
        _fail("map_const_to_folder: None", str(e))

    # 1.7: _map_const_to_folder is same function (backward compat alias)
    try:
        _assert("_map_const_to_folder: is alias for map_const_to_folder",
                _map_const_to_folder is map_const_to_folder,
                "alias does not point to same function")
    except Exception as e:
        _fail("_map_const_to_folder: alias", str(e))

    # 1.8: CATEGORIES structure has expected ids and all have label+priority
    try:
        ids_present = set(CATEGORY_IDS)
        expected = {"maps", "trainers", "encounters", "frontier", "scripts",
                    "tilesets", "graphics", "music"}
        _assert("CATEGORIES: has all expected ids",
                expected.issubset(ids_present),
                f"missing: {expected - ids_present}")
        all_valid = all(
            "label" in c and "priority" in c and "id" in c
            for c in CATEGORIES
        )
        _assert("CATEGORIES: all entries have label+priority+id",
                all_valid,
                f"some category missing required keys")
    except Exception as e:
        _fail("CATEGORIES structure", str(e))

    # ==================================================================
    # 2. RemovalItem + RemovalPlan (~15 tests)
    # ==================================================================

    # 2.1: RemovalItem construction with defaults
    try:
        item = RemovalItem("maps", "TestMap")
        _assert("RemovalItem: default status is SAFE",
                item.status == SAFE,
                f"got {item.status!r}")
        _assert("RemovalItem: default detail is empty",
                item.detail == "",
                f"got {item.detail!r}")
        _assert("RemovalItem: default refs is empty list",
                item.refs == [],
                f"got {item.refs!r}")
        _assert("RemovalItem: default data is empty dict",
                item.data == {},
                f"got {item.data!r}")
    except Exception as e:
        _fail("RemovalItem: defaults", str(e))

    # 2.2: RemovalItem construction with custom values
    try:
        item = RemovalItem("trainers", "TRAINER_FOO", BLOCKED,
                           detail="referenced", refs=["ref1"],
                           data={"key": "val"})
        _assert("RemovalItem: custom category",
                item.category == "trainers",
                f"got {item.category!r}")
        _assert("RemovalItem: custom status BLOCKED",
                item.status == BLOCKED,
                f"got {item.status!r}")
        _assert("RemovalItem: custom refs",
                item.refs == ["ref1"],
                f"got {item.refs!r}")
        _assert("RemovalItem: custom data",
                item.data == {"key": "val"},
                f"got {item.data!r}")
    except Exception as e:
        _fail("RemovalItem: custom values", str(e))

    # 2.3: RemovalItem __slots__
    try:
        _assert("RemovalItem: has __slots__",
                hasattr(RemovalItem, "__slots__"),
                "RemovalItem missing __slots__")
        expected_slots = {"category", "name", "status", "detail", "refs", "data"}
        _assert("RemovalItem: __slots__ has all fields",
                set(RemovalItem.__slots__) == expected_slots,
                f"got {set(RemovalItem.__slots__)!r}")
    except Exception as e:
        _fail("RemovalItem: __slots__", str(e))

    # 2.4: RemovalPlan empty plan
    try:
        plan = RemovalPlan()
        _assert("RemovalPlan: empty items list",
                plan.items == [],
                f"got {plan.items!r}")
        _assert("RemovalPlan: empty scan_errors",
                plan.scan_errors == [],
                f"got {plan.scan_errors!r}")
    except Exception as e:
        _fail("RemovalPlan: empty plan", str(e))

    # 2.5: RemovalPlan.add()
    try:
        plan = RemovalPlan()
        item = RemovalItem("maps", "TestMap")
        plan.add(item)
        _assert("RemovalPlan: add() appends item",
                len(plan.items) == 1 and plan.items[0] is item,
                f"items={plan.items!r}")
    except Exception as e:
        _fail("RemovalPlan: add()", str(e))

    # 2.6-2.10: RemovalPlan filtering methods with mixed items
    try:
        plan = RemovalPlan()
        plan.add(RemovalItem("maps", "SafeMap1", SAFE))
        plan.add(RemovalItem("maps", "BlockedMap1", BLOCKED, refs=["r"]))
        plan.add(RemovalItem("maps", "CautionMap1", CAUTION))
        plan.add(RemovalItem("trainers", "SafeTrainer", SAFE))
        plan.add(RemovalItem("trainers", "BlockedTrainer", BLOCKED, refs=["r"]))

        # by_category
        maps_items = plan.by_category("maps")
        _assert("RemovalPlan: by_category('maps') returns 3",
                len(maps_items) == 3,
                f"got {len(maps_items)}")

        # safe_items (all categories)
        safe_all = plan.safe_items()
        _assert("RemovalPlan: safe_items() returns 2",
                len(safe_all) == 2,
                f"got {len(safe_all)}")

        # safe_items (specific category)
        safe_maps = plan.safe_items("maps")
        _assert("RemovalPlan: safe_items('maps') returns 1",
                len(safe_maps) == 1 and safe_maps[0].name == "SafeMap1",
                f"got {[i.name for i in safe_maps]}")

        # blocked_items
        blocked_all = plan.blocked_items()
        _assert("RemovalPlan: blocked_items() returns 2",
                len(blocked_all) == 2,
                f"got {len(blocked_all)}")

        # caution_items
        caution_all = plan.caution_items()
        _assert("RemovalPlan: caution_items() returns 1",
                len(caution_all) == 1 and caution_all[0].name == "CautionMap1",
                f"got {[i.name for i in caution_all]}")
    except Exception as e:
        _fail("RemovalPlan: filtering methods", str(e))

    # 2.11: category_summary with mixed items
    try:
        plan = RemovalPlan()
        plan.add(RemovalItem("maps", "S1", SAFE))
        plan.add(RemovalItem("maps", "B1", BLOCKED, refs=["r"]))
        plan.add(RemovalItem("maps", "C1", CAUTION))
        plan.add(RemovalItem("trainers", "T1", SAFE))

        summary = plan.category_summary()
        maps_sum = next((s for s in summary if s["id"] == "maps"), None)
        _assert("category_summary: maps entry exists",
                maps_sum is not None,
                f"summary={summary!r}")
        _assert("category_summary: maps total=3, safe=1, blocked=1, caution=1",
                maps_sum and maps_sum["total"] == 3 and maps_sum["safe"] == 1
                and maps_sum["blocked"] == 1 and maps_sum["caution"] == 1,
                f"got {maps_sum!r}")

        trainers_sum = next((s for s in summary if s["id"] == "trainers"), None)
        _assert("category_summary: trainers total=1",
                trainers_sum is not None and trainers_sum["total"] == 1,
                f"got {trainers_sum!r}")
    except Exception as e:
        _fail("category_summary", str(e))

    # 2.12: total_safe
    try:
        plan = RemovalPlan()
        plan.add(RemovalItem("maps", "S1", SAFE))
        plan.add(RemovalItem("maps", "S2", SAFE))
        plan.add(RemovalItem("maps", "B1", BLOCKED, refs=["r"]))
        _assert("RemovalPlan: total_safe() returns 2",
                plan.total_safe() == 2,
                f"got {plan.total_safe()}")
    except Exception as e:
        _fail("RemovalPlan: total_safe()", str(e))

    # 2.13: total_blocked
    try:
        _assert("RemovalPlan: total_blocked() returns 1",
                plan.total_blocked() == 1,
                f"got {plan.total_blocked()}")
    except Exception as e:
        _fail("RemovalPlan: total_blocked()", str(e))

    # 2.14: category_summary skips empty categories
    try:
        plan = RemovalPlan()
        plan.add(RemovalItem("maps", "M1", SAFE))
        summary = plan.category_summary()
        _assert("category_summary: skips empty categories",
                len(summary) == 1 and summary[0]["id"] == "maps",
                f"got {[s['id'] for s in summary]}")
    except Exception as e:
        _fail("category_summary: empty categories", str(e))

    # 2.15: blocked_items with category filter
    try:
        plan = RemovalPlan()
        plan.add(RemovalItem("maps", "B1", BLOCKED, refs=["r"]))
        plan.add(RemovalItem("trainers", "B2", BLOCKED, refs=["r"]))
        blocked_maps = plan.blocked_items("maps")
        _assert("RemovalPlan: blocked_items('maps') returns 1",
                len(blocked_maps) == 1 and blocked_maps[0].name == "B1",
                f"got {[i.name for i in blocked_maps]}")
    except Exception as e:
        _fail("RemovalPlan: blocked_items filtered", str(e))

    # ==================================================================
    # 3. Trainer detection (~8 tests)
    # ==================================================================

    # 3.1-3.3: _load_all_trainer_consts with fake opponents.h
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
        inc_dir = os.path.join(tmp, "include", "constants")
        os.makedirs(inc_dir)

        # Write a fake opponents.h
        opp_path = os.path.join(inc_dir, "opponents.h")
        with open(opp_path, "w") as f:
            f.write("#define TRAINER_NONE 0\n")
            f.write("#define TRAINER_GRUNT 100\n")
            f.write("#define TRAINER_RIVAL 200\n")
            f.write("#define TRAINER_CUSTOM_ACE 900\n")
            f.write("#define TRAINERS_COUNT 4\n")  # meta define
            f.write("#define TRAINER_PARTNER 999\n")  # meta define

        results = _load_all_trainer_consts(tmp)
        names = [c for c, tid in results]

        _assert("_load_all_trainer_consts: finds TRAINER_GRUNT",
                "TRAINER_GRUNT" in names,
                f"names={names}")
        _assert("_load_all_trainer_consts: finds TRAINER_RIVAL",
                "TRAINER_RIVAL" in names,
                f"names={names}")
        _assert("_load_all_trainer_consts: skips meta define TRAINERS_COUNT",
                "TRAINERS_COUNT" not in names,
                f"names={names}")
        _assert("_load_all_trainer_consts: skips meta define TRAINER_PARTNER",
                "TRAINER_PARTNER" not in names,
                f"names={names}")
        _assert("_load_all_trainer_consts: skips meta define TRAINER_NONE",
                "TRAINER_NONE" not in names,
                f"names={names}")
    except Exception as e:
        _fail("_load_all_trainer_consts: fake opponents.h", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 3.4: _load_all_trainer_consts with empty file
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
        inc_dir = os.path.join(tmp, "include", "constants")
        os.makedirs(inc_dir)
        with open(os.path.join(inc_dir, "opponents.h"), "w") as f:
            f.write("// empty\n")

        results = _load_all_trainer_consts(tmp)
        _assert("_load_all_trainer_consts: empty file -> empty list",
                results == [],
                f"got {results!r}")
    except Exception as e:
        _fail("_load_all_trainer_consts: empty file", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 3.5: _load_all_trainer_consts with missing file
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
        results = _load_all_trainer_consts(tmp)
        _assert("_load_all_trainer_consts: missing file -> empty list",
                results == [],
                f"got {results!r}")
    except Exception as e:
        _fail("_load_all_trainer_consts: missing file", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 3.6-3.8: _classify_trainers splits correctly
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_scanner_test_")
        inc_dir = os.path.join(tmp, "include", "constants")
        os.makedirs(inc_dir)

        threshold = _VANILLA_TRAINER_THRESHOLD
        with open(os.path.join(inc_dir, "opponents.h"), "w") as f:
            f.write(f"#define TRAINER_VANILLA_A 10\n")
            f.write(f"#define TRAINER_VANILLA_B {threshold}\n")
            f.write(f"#define TRAINER_CUSTOM_A {threshold + 1}\n")
            f.write(f"#define TRAINER_CUSTOM_B {threshold + 50}\n")

        vanilla, custom = _classify_trainers(tmp)
        vanilla_names = [c for c, _ in vanilla]
        custom_names = [c for c, _ in custom]

        _assert("_classify_trainers: vanilla includes id <= threshold",
                "TRAINER_VANILLA_A" in vanilla_names
                and "TRAINER_VANILLA_B" in vanilla_names,
                f"vanilla={vanilla_names}")
        _assert("_classify_trainers: custom includes id > threshold",
                "TRAINER_CUSTOM_A" in custom_names
                and "TRAINER_CUSTOM_B" in custom_names,
                f"custom={custom_names}")
        _assert("_classify_trainers: no overlap",
                not set(vanilla_names) & set(custom_names),
                f"overlap detected")
    except Exception as e:
        _fail("_classify_trainers", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # ==================================================================
    # 4. Encounter classification (~6 tests)
    # ==================================================================

    # 4.1-4.2: map_const_to_folder additional conversions
    try:
        result = map_const_to_folder("MAP_RUSTBORO_CITY")
        _assert("map_const_to_folder: MAP_RUSTBORO_CITY -> RustboroCity",
                result == "RustboroCity",
                f"got {result!r}")
    except Exception as e:
        _fail("map_const_to_folder: MAP_RUSTBORO_CITY", str(e))

    try:
        result = map_const_to_folder("MAP_ROUTE101")
        _assert("map_const_to_folder: MAP_ROUTE101 (no underscore) -> Route101",
                result == "Route101",
                f"got {result!r}")
    except Exception as e:
        _fail("map_const_to_folder: MAP_ROUTE101", str(e))

    # 4.3: _classify_encounters given vanilla_maps set
    try:
        # Monkeypatch _load_encounters to return controlled data
        import torch.cleanup_scanner as _cs_mod
        orig_load = _cs_mod._load_encounters

        fake_encounters = [
            {"map": "MAP_PETALBURG_CITY", "base_label": "p"},
            {"map": "MAP_ROUTE_101", "base_label": "r"},
            {"map": "MAP_CUSTOM_TOWN", "base_label": "c"},
        ]
        _cs_mod._load_encounters = lambda gp: fake_encounters

        vanilla_maps_set = {"PetalburgCity", "Route101"}
        vanilla_enc, custom_enc = _classify_encounters("/fake", vanilla_maps_set)

        _assert("_classify_encounters: vanilla encounters found",
                len(vanilla_enc) == 2,
                f"got {len(vanilla_enc)}: {[e['map'] for e in vanilla_enc]}")
        _assert("_classify_encounters: custom encounters found",
                len(custom_enc) == 1
                and custom_enc[0]["map"] == "MAP_CUSTOM_TOWN",
                f"got {len(custom_enc)}: {[e['map'] for e in custom_enc]}")

        _cs_mod._load_encounters = orig_load
    except Exception as e:
        _fail("_classify_encounters", str(e))
        try:
            _cs_mod._load_encounters = orig_load
        except Exception:
            pass

    # 4.4: _classify_encounters with empty encounter list
    try:
        import torch.cleanup_scanner as _cs_mod2
        orig_load2 = _cs_mod2._load_encounters
        _cs_mod2._load_encounters = lambda gp: []

        vanilla_enc, custom_enc = _classify_encounters("/fake", {"SomeMap"})
        _assert("_classify_encounters: empty encounters -> both empty",
                vanilla_enc == [] and custom_enc == [],
                f"v={len(vanilla_enc)}, c={len(custom_enc)}")

        _cs_mod2._load_encounters = orig_load2
    except Exception as e:
        _fail("_classify_encounters: empty encounters", str(e))
        try:
            _cs_mod2._load_encounters = orig_load2
        except Exception:
            pass

    # 4.5: _load_encounters with fake path doesn't crash
    try:
        result = _load_encounters("/nonexistent/path/xyz")
        _assert("_load_encounters: fake path returns list (possibly empty)",
                isinstance(result, list),
                f"got type={type(result).__name__}")
    except Exception as e:
        _fail("_load_encounters: fake path", str(e))

    # 4.6: map_const_to_folder multi-word with numbers
    try:
        result = map_const_to_folder("MAP_EVER_GRANDE_CITY")
        _assert("map_const_to_folder: MAP_EVER_GRANDE_CITY -> EverGrandeCity",
                result == "EverGrandeCity",
                f"got {result!r}")
    except Exception as e:
        _fail("map_const_to_folder: MAP_EVER_GRANDE_CITY", str(e))

    # ==================================================================
    # 5. CrossRefScanner (~15 tests)
    # ==================================================================

    # Helper: build a minimal fake game tree for CrossRefScanner tests
    def _make_xref_tree():
        tmp = tempfile.mkdtemp(prefix="torch_xref_test_")
        maps_dir = os.path.join(tmp, "data", "maps")

        # Custom map with a warp to a vanilla map
        custom_dir = os.path.join(maps_dir, "CustomMap")
        os.makedirs(custom_dir)
        custom_map_json = {
            "id": "MAP_CUSTOM_MAP",
            "name": "CustomMap",
            "layout": "LAYOUT_CUSTOM_MAP",
            "music": "MUS_LITTLEROOT",
            "connections": [
                {"map": "MAP_VANILLA_MAP", "direction": "south"}
            ],
            "warp_events": [
                {"dest_map": "MAP_VANILLA_MAP", "dest_warp_id": 0}
            ],
        }
        with open(os.path.join(custom_dir, "map.json"), "w") as f:
            json.dump(custom_map_json, f, indent=2)

        # Custom map scripts referencing vanilla content
        with open(os.path.join(custom_dir, "scripts.inc"), "w") as f:
            f.write("CustomMap_EventScript_Test::\n")
            f.write("    goto MAP_VANILLA_MAP\n")
            f.write("    trainerbattle_single TRAINER_VANILLA_GRUNT, 0\n")
            f.write("    call VanillaLabel\n")
            f.write("    setmusic MUS_VANILLA_SONG\n")
            f.write("    goto BATTLE_FRONTIER_LOBBY\n")
            f.write("    end\n")

        # Custom map 2 (no refs to vanilla)
        custom2_dir = os.path.join(maps_dir, "CustomMap2")
        os.makedirs(custom2_dir)
        custom2_json = {
            "id": "MAP_CUSTOM_MAP2",
            "name": "CustomMap2",
            "layout": "LAYOUT_CUSTOM_MAP2",
            "music": "MUS_CUSTOM_SONG",
            "connections": [],
            "warp_events": [],
        }
        with open(os.path.join(custom2_dir, "map.json"), "w") as f:
            json.dump(custom2_json, f, indent=2)
        with open(os.path.join(custom2_dir, "scripts.inc"), "w") as f:
            f.write("CustomMap2_EventScript_Test::\n")
            f.write("    end\n")

        # Vanilla map (for completeness; CrossRefScanner only reads custom maps)
        vanilla_dir = os.path.join(maps_dir, "VanillaMap")
        os.makedirs(vanilla_dir)
        vanilla_json = {
            "id": "MAP_VANILLA_MAP",
            "name": "VanillaMap",
            "layout": "LAYOUT_VANILLA_MAP",
            "music": "MUS_VANILLA_SONG",
            "connections": [],
            "warp_events": [],
        }
        with open(os.path.join(vanilla_dir, "map.json"), "w") as f:
            json.dump(vanilla_json, f, indent=2)

        return tmp

    # 5.1: check_map_warp_refs finds custom->vanilla warp
    tmp = None
    try:
        tmp = _make_xref_tree()
        vanilla_maps = {"VanillaMap"}
        custom_maps = {"CustomMap", "CustomMap2"}
        xref = CrossRefScanner(tmp, vanilla_maps, custom_maps)

        refs = xref.check_map_warp_refs("VanillaMap")
        _assert("check_map_warp_refs: finds custom map with warp to vanilla",
                "CustomMap" in refs,
                f"refs={refs}")
    except Exception as e:
        _fail("check_map_warp_refs: finds ref", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.2: check_map_warp_refs returns empty for unreferenced map
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        # CustomMap2 has no warp to VanillaMap, but CustomMap does;
        # test a vanilla map that nobody references
        # We need to add a second vanilla map that nobody references
        maps_dir = os.path.join(tmp, "data", "maps", "VanillaMap2")
        os.makedirs(maps_dir)
        with open(os.path.join(maps_dir, "map.json"), "w") as f:
            json.dump({"id": "MAP_VANILLA_MAP2", "name": "VanillaMap2"}, f)

        refs = xref.check_map_warp_refs("VanillaMap2")
        _assert("check_map_warp_refs: unreferenced map -> empty",
                refs == [],
                f"refs={refs}")
    except Exception as e:
        _fail("check_map_warp_refs: empty", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.3: check_map_connection_refs finds custom->vanilla connection
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        refs = xref.check_map_connection_refs("VanillaMap")
        _assert("check_map_connection_refs: finds connection",
                "CustomMap" in refs,
                f"refs={refs}")
    except Exception as e:
        _fail("check_map_connection_refs: finds ref", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.4: check_map_connection_refs returns empty when no connection
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap2"})
        refs = xref.check_map_connection_refs("VanillaMap")
        _assert("check_map_connection_refs: no connection -> empty",
                refs == [],
                f"refs={refs}")
    except Exception as e:
        _fail("check_map_connection_refs: empty", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.5: check_map_script_refs finds MAP_VANILLA_MAP in scripts
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        refs = xref.check_map_script_refs("VanillaMap")
        _assert("check_map_script_refs: finds MAP_VANILLA_MAP in scripts",
                "CustomMap" in refs,
                f"refs={refs}")
    except Exception as e:
        _fail("check_map_script_refs: finds ref", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.6: check_map_script_refs empty for unreferenced map
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap2"})
        refs = xref.check_map_script_refs("VanillaMap")
        _assert("check_map_script_refs: unreferenced -> empty",
                refs == [],
                f"refs={refs}")
    except Exception as e:
        _fail("check_map_script_refs: empty", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.7: check_trainer_refs finds TRAINER_VANILLA_GRUNT
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        refs = xref.check_trainer_refs("TRAINER_VANILLA_GRUNT")
        _assert("check_trainer_refs: finds trainer in custom scripts",
                len(refs) >= 1 and refs[0]["map_name"] == "CustomMap",
                f"refs={refs}")
    except Exception as e:
        _fail("check_trainer_refs: finds ref", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.8: check_trainer_refs empty for unused trainer
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        refs = xref.check_trainer_refs("TRAINER_NOBODY_USES")
        _assert("check_trainer_refs: unused trainer -> empty",
                refs == [],
                f"refs={refs}")
    except Exception as e:
        _fail("check_trainer_refs: empty", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.9: check_script_label_refs finds label
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        refs = xref.check_script_label_refs("VanillaLabel")
        _assert("check_script_label_refs: finds label reference",
                len(refs) >= 1 and refs[0]["map_name"] == "CustomMap",
                f"refs={refs}")
    except Exception as e:
        _fail("check_script_label_refs: finds ref", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.10: check_script_label_refs empty for unused label
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        refs = xref.check_script_label_refs("NobodyReferencesThis")
        _assert("check_script_label_refs: unused label -> empty",
                refs == [],
                f"refs={refs}")
    except Exception as e:
        _fail("check_script_label_refs: empty", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.11: check_music_refs finds song in map.json header
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        refs = xref.check_music_refs("MUS_LITTLEROOT")
        map_header_refs = [r for r in refs if r.get("type") == "map_header"]
        _assert("check_music_refs: finds song in map header",
                len(map_header_refs) >= 1,
                f"refs={refs}")
    except Exception as e:
        _fail("check_music_refs: map header", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.12: check_music_refs finds song in script
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        refs = xref.check_music_refs("MUS_VANILLA_SONG")
        script_refs = [r for r in refs if r.get("type") == "script"]
        _assert("check_music_refs: finds song in script",
                len(script_refs) >= 1,
                f"refs={refs}")
    except Exception as e:
        _fail("check_music_refs: script ref", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.13: check_music_refs empty for unused song
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        refs = xref.check_music_refs("MUS_NOBODY_USES_THIS")
        _assert("check_music_refs: unused song -> empty",
                refs == [],
                f"refs={refs}")
    except Exception as e:
        _fail("check_music_refs: empty", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.14: check_frontier_refs finds BATTLE_FRONTIER_ pattern
    tmp = None
    try:
        tmp = _make_xref_tree()
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap", "CustomMap2"})
        refs = xref.check_frontier_refs()
        _assert("check_frontier_refs: finds BATTLE_FRONTIER_ in scripts",
                len(refs) >= 1,
                f"refs={refs}")
    except Exception as e:
        _fail("check_frontier_refs: finds ref", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 5.15: check_frontier_refs empty when no frontier refs
    tmp = None
    try:
        tmp = _make_xref_tree()
        # Only use CustomMap2 which has no frontier references
        xref = CrossRefScanner(tmp, {"VanillaMap"}, {"CustomMap2"})
        refs = xref.check_frontier_refs()
        _assert("check_frontier_refs: no frontier refs -> empty",
                refs == [],
                f"refs={refs}")
    except Exception as e:
        _fail("check_frontier_refs: empty", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # ==================================================================
    # 6. Script label extraction (~5 tests)
    # ==================================================================

    # 6.1: _extract_script_labels with double-colon labels
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_labels_test_")
        inc_path = os.path.join(tmp, "test.inc")
        with open(inc_path, "w") as f:
            f.write("MyScript::\n")
            f.write("    msgbox MyScript_Text\n")
            f.write("    end\n")
            f.write("MyScript_Text::\n")
            f.write('    .string "Hello"\n')

        labels = _extract_script_labels(inc_path)
        _assert("_extract_script_labels: finds double-colon labels",
                "MyScript" in labels and "MyScript_Text" in labels,
                f"labels={labels}")
    except Exception as e:
        _fail("_extract_script_labels: double-colon", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 6.2: _extract_script_labels with single-colon labels
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_labels_test_")
        inc_path = os.path.join(tmp, "test.inc")
        with open(inc_path, "w") as f:
            f.write("SingleLabel:\n")
            f.write("    nop\n")

        labels = _extract_script_labels(inc_path)
        _assert("_extract_script_labels: finds single-colon labels",
                "SingleLabel" in labels,
                f"labels={labels}")
    except Exception as e:
        _fail("_extract_script_labels: single-colon", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 6.3: _extract_script_labels with mixed labels
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_labels_test_")
        inc_path = os.path.join(tmp, "test.inc")
        with open(inc_path, "w") as f:
            f.write("LabelA::\n")
            f.write("    call LabelB\n")
            f.write("LabelB:\n")
            f.write("    return\n")

        labels = _extract_script_labels(inc_path)
        _assert("_extract_script_labels: mixed single/double colon",
                "LabelA" in labels and "LabelB" in labels,
                f"labels={labels}")
    except Exception as e:
        _fail("_extract_script_labels: mixed", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 6.4: _extract_script_labels with empty file
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_labels_test_")
        inc_path = os.path.join(tmp, "empty.inc")
        with open(inc_path, "w") as f:
            f.write("")

        labels = _extract_script_labels(inc_path)
        _assert("_extract_script_labels: empty file -> empty list",
                labels == [],
                f"labels={labels}")
    except Exception as e:
        _fail("_extract_script_labels: empty file", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 6.5: _extract_script_labels excludes non-label lines
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_labels_test_")
        inc_path = os.path.join(tmp, "test.inc")
        with open(inc_path, "w") as f:
            f.write("    msgbox SomeText\n")
            f.write("@ This is a comment\n")
            f.write("    .string \"test\"\n")
            f.write("RealLabel::\n")

        labels = _extract_script_labels(inc_path)
        _assert("_extract_script_labels: excludes noise, only finds labels",
                labels == ["RealLabel"],
                f"labels={labels}")
    except Exception as e:
        _fail("_extract_script_labels: noise excluded", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # ==================================================================
    # 7. Tileset / frontier detection (~8 tests)
    # ==================================================================

    # 7.1: _detect_frontier: has frontier dir + maps
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_frontier_test_")
        frontier_data = os.path.join(tmp, "src", "data", "battle_frontier")
        os.makedirs(frontier_data)
        with open(os.path.join(frontier_data, "battle_tent.h"), "w") as f:
            f.write("// placeholder\n")

        frontier_maps = os.path.join(tmp, "data", "maps", "BattleFrontier_Lobby")
        os.makedirs(frontier_maps)

        result = _detect_frontier(tmp)
        _assert("_detect_frontier: has_frontier is True",
                result["has_frontier"] is True,
                f"got {result!r}")
        _assert("_detect_frontier: frontier_maps includes BattleFrontier_Lobby",
                "BattleFrontier_Lobby" in result["frontier_maps"],
                f"got {result['frontier_maps']!r}")
        _assert("_detect_frontier: frontier_src_files includes battle_tent.h",
                "battle_tent.h" in result["frontier_src_files"],
                f"got {result['frontier_src_files']!r}")
    except Exception as e:
        _fail("_detect_frontier: has frontier", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 7.2: _detect_frontier: no frontier
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_frontier_test_")
        result = _detect_frontier(tmp)
        _assert("_detect_frontier: no frontier -> has_frontier False",
                result["has_frontier"] is False,
                f"got {result!r}")
        _assert("_detect_frontier: no frontier -> empty maps",
                result["frontier_maps"] == [],
                f"got {result['frontier_maps']!r}")
    except Exception as e:
        _fail("_detect_frontier: no frontier", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 7.3: _detect_frontier: only data dir, no maps
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_frontier_test_")
        frontier_data = os.path.join(tmp, "src", "data", "battle_frontier")
        os.makedirs(frontier_data)
        with open(os.path.join(frontier_data, "stuff.c"), "w") as f:
            f.write("// code\n")

        result = _detect_frontier(tmp)
        _assert("_detect_frontier: data dir only -> has_frontier True",
                result["has_frontier"] is True,
                f"got {result!r}")
        _assert("_detect_frontier: data dir only -> frontier_maps empty",
                result["frontier_maps"] == [],
                f"got {result['frontier_maps']!r}")
    except Exception as e:
        _fail("_detect_frontier: data dir only", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 7.4: _find_tilesets_with_c_source_refs: C file with INCBIN reference
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_tilesets_test_")
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)

        with open(os.path.join(src_dir, "custom_code.c"), "w") as f:
            f.write('const u32 gSomeThing[] = INCBIN_U32("data/tilesets/secondary/petalburg/tiles.4bpp.lz");\n')
            f.write('const u32 gOther[] = INCBIN_U32("data/tilesets/secondary/rustboro/palettes.gbapal");\n')

        refs = _find_tilesets_with_c_source_refs(tmp)
        _assert("_find_tilesets_with_c_source_refs: finds petalburg ref",
                "petalburg" in refs,
                f"refs={refs}")
        _assert("_find_tilesets_with_c_source_refs: finds rustboro ref",
                "rustboro" in refs,
                f"refs={refs}")
    except Exception as e:
        _fail("_find_tilesets_with_c_source_refs: finds refs", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 7.5: _find_tilesets_with_c_source_refs: no references
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_tilesets_test_")
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "clean.c"), "w") as f:
            f.write("// no tileset references here\n")

        refs = _find_tilesets_with_c_source_refs(tmp)
        _assert("_find_tilesets_with_c_source_refs: no refs -> empty",
                refs == {},
                f"refs={refs}")
    except Exception as e:
        _fail("_find_tilesets_with_c_source_refs: empty", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 7.6: _find_tilesets_with_c_source_refs: skips managed files
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_tilesets_test_")
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)

        # graphics.h is a managed file - should be skipped
        with open(os.path.join(src_dir, "graphics.h"), "w") as f:
            f.write('INCBIN_U32("data/tilesets/secondary/petalburg/tiles.4bpp.lz");\n')

        refs = _find_tilesets_with_c_source_refs(tmp)
        _assert("_find_tilesets_with_c_source_refs: skips managed files",
                refs == {},
                f"refs={refs}")
    except Exception as e:
        _fail("_find_tilesets_with_c_source_refs: managed files", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 7.7: _find_tilesets_with_c_source_refs: include dir also scanned
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_tilesets_test_")
        inc_dir = os.path.join(tmp, "include")
        os.makedirs(inc_dir)

        with open(os.path.join(inc_dir, "custom.h"), "w") as f:
            f.write('extern const u32 gFoo; // data/tilesets/secondary/myts/foo\n')

        refs = _find_tilesets_with_c_source_refs(tmp)
        _assert("_find_tilesets_with_c_source_refs: scans include dir",
                "myts" in refs,
                f"refs={refs}")
    except Exception as e:
        _fail("_find_tilesets_with_c_source_refs: include dir", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # 7.8: _detect_frontier: frontier data with .inc file
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="torch_frontier_test_")
        frontier_data = os.path.join(tmp, "src", "data", "battle_frontier")
        os.makedirs(frontier_data)
        with open(os.path.join(frontier_data, "scripts.inc"), "w") as f:
            f.write("@ scripts\n")
        with open(os.path.join(frontier_data, "readme.txt"), "w") as f:
            f.write("not counted\n")

        result = _detect_frontier(tmp)
        _assert("_detect_frontier: .inc counted, .txt excluded",
                "scripts.inc" in result["frontier_src_files"]
                and "readme.txt" not in result["frontier_src_files"],
                f"got {result['frontier_src_files']!r}")
    except Exception as e:
        _fail("_detect_frontier: file extension filtering", str(e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
