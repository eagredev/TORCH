"""Tests for the NPC API endpoints."""
import json
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _assert, _skip


# ---------------------------------------------------------------------------
# Test fixture helpers
# ---------------------------------------------------------------------------

def _make_game_tree(tmp):
    """Create a minimal game directory with map.json, scripts, and headers."""
    # Map with NPCs
    map_dir = os.path.join(tmp, "data", "maps", "TestTown")
    os.makedirs(map_dir)
    map_json = {
        "object_events": [
            {
                "local_id": 1,
                "graphics_id": "OBJ_EVENT_GFX_NURSE",
                "x": 7, "y": 2,
                "elevation": 3,
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "movement_range_x": 0,
                "movement_range_y": 0,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "flag": "0",
                "script": "TestTown_EventScript_Nurse",
            },
            {
                "local_id": 2,
                "graphics_id": "OBJ_EVENT_GFX_BOY_1",
                "x": 10, "y": 5,
                "elevation": 3,
                "movement_type": "MOVEMENT_TYPE_WANDER_AROUND",
                "movement_range_x": 2,
                "movement_range_y": 2,
                "trainer_type": "TRAINER_TYPE_NORMAL",
                "trainer_sight_or_berry_tree_id": "3",
                "flag": "FLAG_TRAINER_1",
                "script": "TestTown_EventScript_Trainer1",
            },
        ],
        "bg_events": [
            {
                "type": "sign",
                "x": 3, "y": 8,
                "elevation": 0,
                "player_facing_dir": "BG_EVENT_PLAYER_FACING_ANY",
                "script": "TestTown_EventScript_Sign1",
            },
        ],
    }
    with open(os.path.join(map_dir, "map.json"), "w") as f:
        json.dump(map_json, f, indent=2)

    # Scripts.pory with a simple msgbox
    with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
        f.write(
            'script TestTown_EventScript_Nurse {\n'
            '    msgbox(format("Welcome to the Pokemon Center!"), MSGBOX_DEFAULT)\n'
            '}\n\n'
            'script TestTown_EventScript_Trainer1 {\n'
            '    trainerbattle_single(TRAINER_TEST, '
            'format("Let us battle!"), format("You win!"))\n'
            '}\n'
        )

    # Empty map (should be excluded from map list)
    empty_dir = os.path.join(tmp, "data", "maps", "EmptyMap")
    os.makedirs(empty_dir)
    with open(os.path.join(empty_dir, "map.json"), "w") as f:
        json.dump({"object_events": []}, f)

    # Second map for search testing
    map2_dir = os.path.join(tmp, "data", "maps", "Route101")
    os.makedirs(map2_dir)
    map2_json = {
        "object_events": [
            {
                "local_id": 1,
                "graphics_id": "OBJ_EVENT_GFX_GIRL_1",
                "x": 5, "y": 5,
                "elevation": 3,
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "movement_range_x": 0,
                "movement_range_y": 0,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "flag": "0",
                "script": "",
            },
        ],
    }
    with open(os.path.join(map2_dir, "map.json"), "w") as f:
        json.dump(map2_json, f, indent=2)

    # Movement type header
    header_dir = os.path.join(tmp, "include", "constants")
    os.makedirs(header_dir)
    with open(os.path.join(header_dir, "event_object_movement.h"), "w") as f:
        f.write(
            "#define MOVEMENT_TYPE_NONE                  0x0\n"
            "#define MOVEMENT_TYPE_FACE_DOWN             0x8\n"
            "#define MOVEMENT_TYPE_WANDER_AROUND         0x2\n"
        )

    # Graphics ID header
    with open(os.path.join(header_dir, "event_objects.h"), "w") as f:
        f.write(
            "#define OBJ_EVENT_GFX_NURSE    58\n"
            "#define OBJ_EVENT_GFX_BOY_1    7\n"
            "#define OBJ_EVENT_GFX_GIRL_1   8\n"
        )

    # Trainer type header
    with open(os.path.join(header_dir, "trainer_types.h"), "w") as f:
        f.write(
            "#define TRAINER_TYPE_NONE               0\n"
            "#define TRAINER_TYPE_NORMAL             1\n"
        )

    # Sprite resolution chain headers
    oe_dir = os.path.join(tmp, "src", "data", "object_events")
    os.makedirs(oe_dir)

    with open(os.path.join(oe_dir, "object_event_graphics_info_pointers.h"), "w") as f:
        f.write(
            "const struct ObjectEventGraphicsInfo *const gObjectEventGraphicsInfoPointers[] = {\n"
            "    [OBJ_EVENT_GFX_NURSE] = &gObjectEventGraphicsInfo_Nurse,\n"
            "    [OBJ_EVENT_GFX_BOY_1] = &gObjectEventGraphicsInfo_Boy1,\n"
            "};\n"
        )

    with open(os.path.join(oe_dir, "object_event_graphics_info.h"), "w") as f:
        f.write(
            "const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_Nurse = {\n"
            "    .images = sPicTable_Nurse,\n"
            "};\n"
            "const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_Boy1 = {\n"
            "    .images = sPicTable_Boy1,\n"
            "};\n"
        )

    with open(os.path.join(oe_dir, "object_event_pic_tables.h"), "w") as f:
        f.write(
            "static const struct SpriteFrameImage sPicTable_Nurse[] = {\n"
            "    overworld_frame(gObjectEventPic_Nurse, 2, 4, 0),\n"
            "};\n"
            "static const struct SpriteFrameImage sPicTable_Boy1[] = {\n"
            "    overworld_ascending_frames(gObjectEventPic_Boy1, 2, 4),\n"
            "};\n"
        )

    with open(os.path.join(oe_dir, "object_event_graphics.h"), "w") as f:
        f.write(
            'const u32 gObjectEventPic_Nurse[] = INCBIN_U32("graphics/object_events/pics/people/nurse.4bpp");\n'
            'const u32 gObjectEventPic_Boy1[] = INCBIN_U32("graphics/object_events/pics/people/boy_1.4bpp");\n'
        )

    # Create actual PNG files for sprite resolution
    pics_dir = os.path.join(tmp, "graphics", "object_events", "pics", "people")
    os.makedirs(pics_dir)
    # Minimal 1x1 PNG (valid file header)
    _TINY_PNG = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
        b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
        b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    with open(os.path.join(pics_dir, "nurse.png"), "wb") as f:
        f.write(_TINY_PNG)
    with open(os.path.join(pics_dir, "boy_1.png"), "wb") as f:
        f.write(_TINY_PNG)

    return tmp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("API NPCs")

    # Clear caches before testing with mock data
    import torch.web.api_npcs as api_npcs
    import torch.project_files as pf

    tmp = tempfile.mkdtemp(prefix="torch_test_npcs_")
    try:
        _make_game_tree(tmp)
        _run_tests(tmp, api_npcs, pf)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        # Reset caches
        api_npcs._sprite_index = None
        api_npcs._sprite_game_path = None
        api_npcs._constants_cache = None
        api_npcs._constants_game_path = None
        pf.clear_project_cache()


def _run_tests(game_path, api_npcs, pf):
    """Run all NPC API tests using the mock game tree."""

    # -----------------------------------------------------------------------
    # Import test
    # -----------------------------------------------------------------------
    try:
        from torch.web.api_npcs import (
            handle_npc_maps, handle_npc_constants, handle_npc_list,
            handle_npc_sprite, _build_sprite_index, _extract_dialogue_preview,
            _classify_script_type,
        )
        _ok("import api_npcs")
    except Exception as exc:
        _fail("import api_npcs", str(exc))
        return

    # -----------------------------------------------------------------------
    # Mock handler
    # -----------------------------------------------------------------------
    class MockServer:
        pass

    class MockHandler:
        pass

    server = MockServer()
    server.game_path = game_path
    server.project_dir = ""
    handler = MockHandler()
    handler.server = server

    class FakeMatch:
        def __init__(self, groups=None):
            self._groups = groups or {}
        def group(self, name):
            return self._groups.get(name, "")

    # -----------------------------------------------------------------------
    # Map list endpoint
    # -----------------------------------------------------------------------
    result = handle_npc_maps(handler, FakeMatch(), {"q": [""]})
    _assert("map list returns ok",
            result.get("ok") is True,
            f"got {result!r}")

    maps = result.get("data", {}).get("maps", [])
    _assert("map list has maps",
            len(maps) >= 2,
            f"expected >=2 maps, got {len(maps)}")

    # EmptyMap should be excluded
    map_names = [m["name"] for m in maps]
    _assert("empty map excluded",
            "EmptyMap" not in map_names,
            f"EmptyMap in {map_names}")

    # TestTown should be present with correct counts
    test_town = next((m for m in maps if m["name"] == "TestTown"), None)
    _assert("TestTown in map list",
            test_town is not None,
            f"TestTown not found in {map_names}")

    if test_town:
        _assert("map list npc_count field",
                test_town.get("npc_count") == 2,
                f"expected 2, got {test_town.get('npc_count')}")
        _assert("map list trainer_count field",
                test_town.get("trainer_count") == 1,
                f"expected 1, got {test_town.get('trainer_count')}")
        _assert("map list has_nurse field",
                test_town.get("has_nurse") is True,
                f"expected True, got {test_town.get('has_nurse')}")

    # -----------------------------------------------------------------------
    # Map list search
    # -----------------------------------------------------------------------
    result = handle_npc_maps(handler, FakeMatch(), {"q": ["route"]})
    maps = result.get("data", {}).get("maps", [])
    _assert("search filters to Route maps",
            all("route" in m["name"].lower() for m in maps),
            f"unfiltered maps: {[m['name'] for m in maps]}")
    _assert("search finds Route101",
            any(m["name"] == "Route101" for m in maps),
            f"Route101 not in {[m['name'] for m in maps]}")

    result = handle_npc_maps(handler, FakeMatch(), {"q": ["zzzznotamap"]})
    maps = result.get("data", {}).get("maps", [])
    _assert("search for nonexistent returns empty",
            len(maps) == 0,
            f"expected 0, got {len(maps)}")

    # -----------------------------------------------------------------------
    # NPC list endpoint
    # -----------------------------------------------------------------------
    match = FakeMatch({"map_name": "TestTown"})
    result = handle_npc_list(handler, match, {})
    _assert("npc list returns ok",
            result.get("ok") is True,
            f"got {result!r}")

    data = result.get("data", {})
    npcs = data.get("npcs", [])
    _assert("npc list has 2 npcs",
            len(npcs) == 2,
            f"expected 2, got {len(npcs)}")

    # Check required fields on first NPC
    if npcs:
        npc = npcs[0]
        required_keys = [
            "object_id", "graphics_id", "display_name", "x", "y",
            "elevation", "movement_type", "movement_range_x",
            "movement_range_y", "trainer_type",
            "trainer_sight_or_berry_tree_id", "flag", "script",
            "script_type", "dialogue_preview", "sprite_url", "is_trainer",
        ]
        for key in required_keys:
            _assert(f"npc has key '{key}'",
                    key in npc,
                    f"missing key '{key}' in {list(npc.keys())}")

    # -----------------------------------------------------------------------
    # Display name conversion
    # -----------------------------------------------------------------------
    if npcs:
        _assert("display_name Nurse",
                npcs[0].get("display_name") == "Nurse",
                f"expected 'Nurse', got {npcs[0].get('display_name')!r}")

    # -----------------------------------------------------------------------
    # Trainer detection
    # -----------------------------------------------------------------------
    if len(npcs) >= 2:
        _assert("nurse is not trainer",
                npcs[0].get("is_trainer") is False,
                f"expected False, got {npcs[0].get('is_trainer')}")
        _assert("trainer is detected",
                npcs[1].get("is_trainer") is True,
                f"expected True, got {npcs[1].get('is_trainer')}")

    # -----------------------------------------------------------------------
    # BG events
    # -----------------------------------------------------------------------
    bg_events = data.get("bg_events", [])
    _assert("bg_events included",
            len(bg_events) == 1,
            f"expected 1 bg_event, got {len(bg_events)}")

    if bg_events:
        bg = bg_events[0]
        _assert("bg_event has type",
                bg.get("type") == "sign",
                f"got {bg.get('type')!r}")
        _assert("bg_event has script",
                bg.get("script") == "TestTown_EventScript_Sign1",
                f"got {bg.get('script')!r}")

    # -----------------------------------------------------------------------
    # Dialogue preview
    # -----------------------------------------------------------------------
    if npcs:
        _assert("dialogue preview extracted",
                npcs[0].get("dialogue_preview") is not None,
                f"expected text, got None")
        preview = npcs[0].get("dialogue_preview", "")
        _assert("dialogue contains 'Pokemon Center'",
                "Pokemon Center" in preview,
                f"got {preview!r}")

    # -----------------------------------------------------------------------
    # Sprite URL resolution
    # -----------------------------------------------------------------------
    index = _build_sprite_index(game_path)
    _assert("sprite index built",
            isinstance(index, dict) and len(index) > 0,
            f"got {index!r}")
    _assert("sprite index has NURSE",
            "OBJ_EVENT_GFX_NURSE" in index,
            f"NURSE not in {list(index.keys())}")
    _assert("sprite index has BOY_1",
            "OBJ_EVENT_GFX_BOY_1" in index,
            f"BOY_1 not in {list(index.keys())}")

    if npcs:
        _assert("npc sprite_url is non-null",
                npcs[0].get("sprite_url") is not None,
                f"sprite_url is None for {npcs[0].get('graphics_id')}")
        url = npcs[0].get("sprite_url", "")
        _assert("sprite_url uses overworld-frame endpoint",
                url.startswith("/api/assets/overworld-frame/"),
                f"got {url!r}")

    # -----------------------------------------------------------------------
    # Sprite endpoint — missing file returns 404
    # -----------------------------------------------------------------------
    match404 = FakeMatch({"path": "nonexistent/fake_sprite.png"})
    result = handle_npc_sprite(handler, match404, {})
    _assert("missing sprite returns 404 error",
            result is not None and result.get("ok") is False,
            f"expected error, got {result!r}")

    # -----------------------------------------------------------------------
    # Constants endpoint
    # -----------------------------------------------------------------------
    result = handle_npc_constants(handler, FakeMatch(), {})
    _assert("constants returns ok",
            result.get("ok") is True,
            f"got {result!r}")

    cdata = result.get("data", {})
    _assert("constants has movement_types",
            "movement_types" in cdata,
            f"missing movement_types")
    _assert("constants has graphics_ids",
            "graphics_ids" in cdata,
            f"missing graphics_ids")
    _assert("constants has trainer_types",
            "trainer_types" in cdata,
            f"missing trainer_types")

    # Check entry shape
    mt = cdata.get("movement_types", [])
    if mt:
        _assert("movement_type entry has const",
                "const" in mt[0],
                f"missing 'const' key")
        _assert("movement_type entry has label",
                "label" in mt[0],
                f"missing 'label' key")

    gi = cdata.get("graphics_ids", [])
    _assert("graphics_ids not empty",
            len(gi) >= 2,
            f"expected >=2, got {len(gi)}")

    # Check label conversion
    nurse_entry = next(
        (g for g in gi if g["const"] == "OBJ_EVENT_GFX_NURSE"), None
    )
    _assert("nurse constant label",
            nurse_entry and nurse_entry.get("label") == "Nurse",
            f"got {nurse_entry!r}")

    # -----------------------------------------------------------------------
    # Constants caching
    # -----------------------------------------------------------------------
    result2 = handle_npc_constants(handler, FakeMatch(), {})
    cdata2 = result2.get("data", {})
    _assert("constants cache returns same data",
            cdata2 == cdata,
            "cached result differs from first call")

    # -----------------------------------------------------------------------
    # Script type classification
    # -----------------------------------------------------------------------
    _assert("classify nurse script",
            _classify_script_type("Nurse_Script", "OBJ_EVENT_GFX_NURSE") == "nurse",
            "expected 'nurse'")
    _assert("classify empty script",
            _classify_script_type("", "OBJ_EVENT_GFX_BOY_1") == "none",
            "expected 'none'")
    _assert("classify generic script defaults to flavor",
            _classify_script_type("SomeRandom_Script", "OBJ_EVENT_GFX_BOY_1") == "flavor",
            "expected 'flavor'")

    # -----------------------------------------------------------------------
    # Missing map returns 404
    # -----------------------------------------------------------------------
    match_bad = FakeMatch({"map_name": "NoSuchMap"})
    result = handle_npc_list(handler, match_bad, {})
    _assert("missing map returns 404",
            result.get("ok") is False and result.get("_status") == 404,
            f"got {result!r}")

    # -----------------------------------------------------------------------
    # Dialogue preview standalone tests
    # -----------------------------------------------------------------------
    from torch.web.api_npcs import _find_dialogue_in_content

    test_content = (
        'script MyMap_Script {\n'
        '    msgbox(format("Hello world!"), MSGBOX_DEFAULT)\n'
        '}\n'
    )
    _assert("dialogue from content",
            _find_dialogue_in_content(test_content, "MyMap_Script") == "Hello world!",
            f"got {_find_dialogue_in_content(test_content, 'MyMap_Script')!r}")

    _assert("dialogue missing label returns None",
            _find_dialogue_in_content(test_content, "Nonexistent_Script") is None,
            "expected None")

    # Test GBA formatting cleanup
    test_gba = (
        'script GBA_Script {\n'
        '    msgbox(format("Line one\\nLine two\\pPage two"), MSGBOX_DEFAULT)\n'
        '}\n'
    )
    result = _find_dialogue_in_content(test_gba, "GBA_Script")
    _assert("dialogue cleans GBA formatting",
            result is not None and "\\n" not in result and "\\p" not in result,
            f"got {result!r}")

    # -----------------------------------------------------------------------
    # Path traversal in sprite endpoint
    # -----------------------------------------------------------------------
    match_trav = FakeMatch({"path": "../../etc/passwd"})
    result = handle_npc_sprite(handler, match_trav, {})
    _assert("sprite path traversal blocked",
            result is not None and result.get("ok") is False,
            f"expected error, got {result!r}")

    _ok("all NPC API tests complete")
