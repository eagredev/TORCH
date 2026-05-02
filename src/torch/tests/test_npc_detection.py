"""NPC Detection suite — get_map_objects and display name conversion."""
import os
import json
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_npc_map(tmp, map_name, object_events):
    """Create a game tree with a map.json containing given object_events."""
    game = os.path.join(tmp, "game")
    map_dir = os.path.join(game, "data", "maps", map_name)
    os.makedirs(map_dir, exist_ok=True)
    map_data = {
        "id": f"MAP_{map_name.upper()}",
        "name": map_name,
        "object_events": object_events,
    }
    with open(os.path.join(map_dir, "map.json"), "w") as f:
        json.dump(map_data, f)
    return game


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("NPC Detection  (get_map_objects, display names)")

    try:
        from torch.project_files import get_map_objects, clear_project_cache
    except ImportError as e:
        _skip("all npc_detection tests", f"import failed: {e}")
        return

    tmp = tempfile.mkdtemp(prefix="torch_npc_test_")
    try:
        # ---- 1. Basic NPC extraction (index-based IDs) ----
        clear_project_cache()
        events = [
            {
                "graphics_id": "OBJ_EVENT_GFX_NURSE",
                "x": 3, "y": 5,
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "script": "TestMap_EventScript_Nurse",
                "flag": "0",
            },
            {
                "graphics_id": "OBJ_EVENT_GFX_SWIMMER_M",
                "x": 24, "y": 15,
                "movement_type": "MOVEMENT_TYPE_FACE_RIGHT",
                "trainer_type": "TRAINER_TYPE_NORMAL",
                "trainer_sight_or_berry_tree_id": "4",
                "script": "TestMap_EventScript_Isaiah",
                "flag": "0",
            },
        ]
        game = _make_npc_map(tmp, "TestMap", events)
        npcs = get_map_objects(game, "TestMap")

        _assert(
            "get_map_objects: returns 2 NPCs",
            len(npcs) == 2,
            f"expected 2, got {len(npcs)}"
        )
        _assert(
            "get_map_objects: first NPC object_id is 1 (1-based index)",
            npcs[0]["object_id"] == 1,
            f"got {npcs[0]['object_id']}"
        )
        _assert(
            "get_map_objects: second NPC object_id is 2",
            npcs[1]["object_id"] == 2,
            f"got {npcs[1]['object_id']}"
        )
        _assert(
            "get_map_objects: display_name strips prefix and title-cases",
            npcs[0]["display_name"] == "Nurse",
            f"got '{npcs[0]['display_name']}'"
        )
        _assert(
            "get_map_objects: multi-word display name",
            npcs[1]["display_name"] == "Swimmer M",
            f"got '{npcs[1]['display_name']}'"
        )
        _assert(
            "get_map_objects: coordinates extracted",
            npcs[0]["x"] == 3 and npcs[0]["y"] == 5,
            f"got ({npcs[0]['x']}, {npcs[0]['y']})"
        )
        _assert(
            "get_map_objects: script extracted",
            npcs[0]["script"] == "TestMap_EventScript_Nurse",
            f"got '{npcs[0]['script']}'"
        )
        _assert(
            "get_map_objects: trainer type preserved",
            npcs[1]["trainer_type"] == "TRAINER_TYPE_NORMAL",
            f"got '{npcs[1]['trainer_type']}'"
        )
        _assert(
            "get_map_objects: non-trainer has TRAINER_TYPE_NONE",
            npcs[0]["trainer_type"] == "TRAINER_TYPE_NONE",
            f"got '{npcs[0]['trainer_type']}'"
        )

        # ---- 2. Explicit local_id (named constant — uses 1-based fallback) ----
        clear_project_cache()
        shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)
        events_lid = [
            {
                "local_id": "LOCALID_WALLY",
                "graphics_id": "OBJ_EVENT_GFX_WALLY",
                "x": 15, "y": 10,
                "trainer_type": "TRAINER_TYPE_NONE",
                "script": "0x0",
                "flag": "FLAG_HIDE_WALLY",
            },
            {
                "local_id": 5,
                "graphics_id": "OBJ_EVENT_GFX_BOY_1",
                "x": 8, "y": 22,
                "trainer_type": "TRAINER_TYPE_NONE",
                "script": "Town_EventScript_Boy",
                "flag": "0",
            },
        ]
        game2 = _make_npc_map(tmp, "Town", events_lid)
        npcs2 = get_map_objects(game2, "Town")

        _assert(
            "get_map_objects: named local_id falls back to 1-based index",
            npcs2[0]["object_id"] == 1,
            f"got {npcs2[0]['object_id']}"
        )
        _assert(
            "get_map_objects: integer local_id is used directly",
            npcs2[1]["object_id"] == 5,
            f"got {npcs2[1]['object_id']}"
        )

        # ---- 3. Script normalization (0x0, 0, empty) ----
        _assert(
            "get_map_objects: script '0x0' normalized to empty",
            npcs2[0]["script"] == "",
            f"got '{npcs2[0]['script']}'"
        )
        _assert(
            "get_map_objects: flag '0' normalized to empty",
            npcs2[1]["flag"] == "",
            f"got '{npcs2[1]['flag']}'"
        )
        _assert(
            "get_map_objects: real flag preserved",
            npcs2[0]["flag"] == "FLAG_HIDE_WALLY",
            f"got '{npcs2[0]['flag']}'"
        )

        # ---- 4. No object_events ----
        clear_project_cache()
        shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)
        game3 = _make_npc_map(tmp, "EmptyMap", [])
        _assert(
            "get_map_objects: empty object_events returns []",
            get_map_objects(game3, "EmptyMap") == [],
            "expected []"
        )

        # ---- 5. Missing map.json ----
        clear_project_cache()
        _assert(
            "get_map_objects: missing map returns []",
            get_map_objects(game3, "NoSuchMap") == [],
            "expected []"
        )

        # ---- 6. Missing game path ----
        clear_project_cache()
        _assert(
            "get_map_objects: invalid game_path returns []",
            get_map_objects("/nonexistent/path", "AnyMap") == [],
            "expected []"
        )

        # ---- 7. map.json without object_events key ----
        clear_project_cache()
        shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)
        game_no_key = os.path.join(tmp, "game")
        map_dir = os.path.join(game_no_key, "data", "maps", "PlainMap")
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "map.json"), "w") as f:
            json.dump({"id": "MAP_PLAIN", "layout": "LAYOUT_PLAIN"}, f)
        _assert(
            "get_map_objects: no object_events key returns []",
            get_map_objects(game_no_key, "PlainMap") == [],
            "expected []"
        )

        # ---- 8. Numeric string local_id ----
        clear_project_cache()
        shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)
        events_numstr = [
            {
                "local_id": "7",
                "graphics_id": "OBJ_EVENT_GFX_GENTLEMAN",
                "x": 20, "y": 10,
                "trainer_type": "TRAINER_TYPE_NONE",
                "script": "Town_EventScript_Gentleman",
                "flag": "0",
            },
        ]
        game_ns = _make_npc_map(tmp, "NumMap", events_numstr)
        npcs_ns = get_map_objects(game_ns, "NumMap")
        _assert(
            "get_map_objects: string digit local_id parsed as int",
            npcs_ns[0]["object_id"] == 7,
            f"got {npcs_ns[0]['object_id']}"
        )

        # ---- 9. Trainer detection ----
        clear_project_cache()
        shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)
        events_trainer = [
            {
                "graphics_id": "OBJ_EVENT_GFX_HIKER",
                "x": 5, "y": 5,
                "trainer_type": "TRAINER_TYPE_NORMAL",
                "script": "Route_EventScript_Hiker",
                "flag": "0",
            },
            {
                "graphics_id": "OBJ_EVENT_GFX_WOMAN_1",
                "x": 10, "y": 10,
                "trainer_type": "TRAINER_TYPE_NONE",
                "script": "Route_EventScript_Woman",
                "flag": "0",
            },
        ]
        game_t = _make_npc_map(tmp, "RouteT", events_trainer)
        npcs_t = get_map_objects(game_t, "RouteT")
        _assert(
            "get_map_objects: trainer detected correctly",
            npcs_t[0]["trainer_type"] == "TRAINER_TYPE_NORMAL"
            and npcs_t[1]["trainer_type"] == "TRAINER_TYPE_NONE",
            f"got [{npcs_t[0]['trainer_type']}, {npcs_t[1]['trainer_type']}]"
        )

        # ---- 10. Display name edge cases ----
        try:
            from torch.names import _const_to_human_name
            _assert(
                "display_name: OBJ_EVENT_GFX_ITEM_BALL -> Item Ball",
                _const_to_human_name("OBJ_EVENT_GFX_ITEM_BALL", "OBJ_EVENT_GFX_") == "Item Ball",
                f"got '{_const_to_human_name('OBJ_EVENT_GFX_ITEM_BALL', 'OBJ_EVENT_GFX_')}'"
            )
            _assert(
                "display_name: OBJ_EVENT_GFX_STEVEN -> Steven",
                _const_to_human_name("OBJ_EVENT_GFX_STEVEN", "OBJ_EVENT_GFX_") == "Steven",
                f"got '{_const_to_human_name('OBJ_EVENT_GFX_STEVEN', 'OBJ_EVENT_GFX_')}'"
            )
            _assert(
                "display_name: empty string -> empty",
                _const_to_human_name("", "OBJ_EVENT_GFX_") == "",
                "expected empty"
            )
        except ImportError as e:
            _skip("display_name tests", f"import failed: {e}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()
