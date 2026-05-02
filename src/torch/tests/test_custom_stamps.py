"""Tests for custom_stamps.py — stamp library engine."""
import json
import os
import shutil
import tempfile

from torch.tests.harness import _begin_suite, _assert
from torch.custom_stamps import (
    STAMPS_DIR,
    _slugify,
    _map_name_to_const,
    _parameterize_events,
    _parameterize_scripts,
    get_stamps_dir,
    list_stamps,
    load_stamp,
    create_stamp,
    delete_stamp,
    validate_stamp_placement,
)


# ---------------------------------------------------------------------------
# Test fixture helpers
# ---------------------------------------------------------------------------

def _make_game(source_map="LittlerootTown_BrendansHouse_1F",
               parent_map="LittlerootTown",
               map_width=9, map_height=7,
               parent_width=20, parent_height=20,
               object_events=None, warp_events=None,
               parent_warps=None, include_pory=False,
               extra_tilesets=None):
    """Create a minimal fake game directory with a source map.

    Returns (game_path, cleanup_fn).
    """
    tmp = tempfile.mkdtemp(prefix="torch_stamps_test_")

    # --- Source map ---
    src_dir = os.path.join(tmp, "data", "maps", source_map)
    os.makedirs(src_dir, exist_ok=True)

    if object_events is None:
        object_events = [
            {
                "graphics_id": "OBJ_EVENT_GFX_MAN_1",
                "x": 3, "y": 2,
                "elevation": 3,
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "movement_range_x": 0, "movement_range_y": 0,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "script": f"{source_map}_EventScript_OldMan",
                "flag": "0",
            }
        ]
    if warp_events is None:
        warp_events = [
            {"x": 3, "y": 6, "elevation": 0,
             "dest_map": f"MAP_{_map_name_to_const(parent_map)}",
             "dest_warp_id": "0"},
            {"x": 4, "y": 6, "elevation": 0,
             "dest_map": f"MAP_{_map_name_to_const(parent_map)}",
             "dest_warp_id": "0"},
        ]

    map_json = {
        "id": f"MAP_{_map_name_to_const(source_map)}",
        "name": source_map,
        "layout": f"LAYOUT_{_map_name_to_const(source_map)}",
        "music": "MUS_LITTLEROOT_TOWN",
        "region_map_section": "MAPSEC_LITTLEROOT_TOWN",
        "requires_flash": False,
        "weather": "WEATHER_NONE",
        "map_type": "MAP_TYPE_INDOOR",
        "object_events": object_events,
        "warp_events": warp_events,
        "coord_events": [],
        "bg_events": [],
    }
    with open(os.path.join(src_dir, "map.json"), "w") as f:
        json.dump(map_json, f, indent=2, ensure_ascii=False)

    # scripts.pory (optional)
    if include_pory:
        pory_text = (
            f"mapscripts {source_map}_MapScripts {{}}\n\n"
            f"script {source_map}_EventScript_OldMan {{\n"
            f"    msgbox(\"{source_map}_Text_Hello\")\n"
            f"}}\n"
        )
        with open(os.path.join(src_dir, "scripts.pory"), "w") as f:
            f.write(pory_text)

    # --- Layout ---
    layout_name = _map_name_to_const(source_map)
    layout_dir_name = source_map
    layout_dir = os.path.join(tmp, "data", "layouts", layout_dir_name)
    os.makedirs(layout_dir, exist_ok=True)

    map_bin = b"\x01\x02" * (map_width * map_height)
    border_bin = b"\x03\x04" * 4
    with open(os.path.join(layout_dir, "map.bin"), "wb") as f:
        f.write(map_bin)
    with open(os.path.join(layout_dir, "border.bin"), "wb") as f:
        f.write(border_bin)

    layouts_json = {
        "layouts_table_label": "gMapLayouts",
        "layouts": [
            {
                "id": f"LAYOUT_{layout_name}",
                "name": f"{source_map}_Layout",
                "width": map_width,
                "height": map_height,
                "primary_tileset": "gTileset_Building",
                "secondary_tileset": "gTileset_BrendansMaysHouse",
                "border_filepath": f"data/layouts/{layout_dir_name}/border.bin",
                "blockdata_filepath": f"data/layouts/{layout_dir_name}/map.bin",
            },
        ],
    }

    # Parent map layout
    parent_layout_name = _map_name_to_const(parent_map)
    parent_layout_dir = os.path.join(tmp, "data", "layouts", parent_map)
    os.makedirs(parent_layout_dir, exist_ok=True)
    with open(os.path.join(parent_layout_dir, "map.bin"), "wb") as f:
        f.write(b"\x00" * 4)
    with open(os.path.join(parent_layout_dir, "border.bin"), "wb") as f:
        f.write(b"\x00" * 4)

    layouts_json["layouts"].append({
        "id": f"LAYOUT_{parent_layout_name}",
        "name": f"{parent_map}_Layout",
        "width": parent_width,
        "height": parent_height,
        "primary_tileset": "gTileset_General",
        "secondary_tileset": "gTileset_Petalburg",
        "border_filepath": f"data/layouts/{parent_map}/border.bin",
        "blockdata_filepath": f"data/layouts/{parent_map}/map.bin",
    })

    lay_dir = os.path.join(tmp, "data", "layouts")
    with open(os.path.join(lay_dir, "layouts.json"), "w") as f:
        json.dump(layouts_json, f, indent=2, ensure_ascii=False)

    # --- Parent map ---
    parent_dir = os.path.join(tmp, "data", "maps", parent_map)
    os.makedirs(parent_dir, exist_ok=True)
    parent_json = {
        "id": f"MAP_{parent_layout_name}",
        "name": parent_map,
        "layout": f"LAYOUT_{parent_layout_name}",
        "music": "MUS_LITTLEROOT_TOWN",
        "object_events": [],
        "warp_events": parent_warps or [],
        "coord_events": [],
        "bg_events": [],
    }
    with open(os.path.join(parent_dir, "map.json"), "w") as f:
        json.dump(parent_json, f, indent=2, ensure_ascii=False)

    # --- Tilesets ---
    for ts in ["building", "brendansmayshouse"]:
        os.makedirs(os.path.join(tmp, "data", "tilesets", "primary", ts),
                     exist_ok=True)
    if extra_tilesets:
        for sub, name in extra_tilesets:
            os.makedirs(os.path.join(tmp, "data", "tilesets", sub, name),
                         exist_ok=True)

    def cleanup():
        shutil.rmtree(tmp, ignore_errors=True)

    return tmp, cleanup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_slugify_basic():
    _assert("slugify simple", _slugify("My House") == "my_house")

def test_slugify_special_chars():
    _assert("slugify special", _slugify("PokéCenter (Large)") == "pok_center_large")

def test_slugify_underscores():
    _assert("slugify underscores", _slugify("___foo___bar___") == "foo_bar")

def test_slugify_numbers():
    _assert("slugify numbers", _slugify("House 2F") == "house_2f")

def test_slugify_empty():
    _assert("slugify empty", _slugify("") == "")


def test_map_name_to_const_basic():
    result = _map_name_to_const("LittlerootTown")
    _assert("const basic", result == "LITTLEROOT_TOWN", f"got {result}")

def test_map_name_to_const_with_underscores():
    result = _map_name_to_const("LittlerootTown_House1")
    _assert("const underscore", result == "LITTLEROOT_TOWN_HOUSE1", f"got {result}")

def test_map_name_to_const_with_floor():
    result = _map_name_to_const("LittlerootTown_BrendansHouse_1F")
    _assert("const floor", result == "LITTLEROOT_TOWN_BRENDANS_HOUSE_1F",
            f"got {result}")

def test_map_name_to_const_empty():
    _assert("const empty", _map_name_to_const("") == "")

def test_map_name_to_const_route():
    result = _map_name_to_const("Route101")
    _assert("const route", result == "ROUTE101", f"got {result}")


def test_parameterize_events_script_replacement():
    events = [
        {"script": "TestMap_EventScript_NPC1", "x": 1, "y": 2},
        {"script": "TestMap_EventScript_NPC2", "x": 3, "y": 4},
    ]
    result = _parameterize_events(events, "TestMap")
    _assert("param script 1",
            result[0]["script"] == "{map_name}_EventScript_NPC1")
    _assert("param script 2",
            result[1]["script"] == "{map_name}_EventScript_NPC2")

def test_parameterize_events_dest_map():
    events = [
        {"dest_map": "MAP_TEST_MAP", "x": 0, "y": 0},
    ]
    result = _parameterize_events(events, "TestMap")
    _assert("param dest_map",
            result[0]["dest_map"] == "MAP_{MAP_CONST}",
            f"got {result[0]['dest_map']}")

def test_parameterize_events_deep_copy():
    events = [{"script": "TestMap_Foo", "nested": {"a": 1}}]
    result = _parameterize_events(events, "TestMap")
    result[0]["nested"]["a"] = 999
    _assert("param deep copy", events[0]["nested"]["a"] == 1)

def test_parameterize_events_no_match():
    events = [{"script": "OtherMap_Foo", "x": 0}]
    result = _parameterize_events(events, "TestMap")
    _assert("param no match", result[0]["script"] == "OtherMap_Foo")


def test_parameterize_scripts_basic():
    text = "script TestMap_EventScript_Foo {\n    msgbox(\"TestMap_Text\")\n}"
    result = _parameterize_scripts(text, "TestMap")
    _assert("pory param name", "{map_name}_EventScript_Foo" in result)
    _assert("pory param text", "{map_name}_Text" in result)

def test_parameterize_scripts_const():
    text = "goto MAP_TEST_MAP\n"
    result = _parameterize_scripts(text, "TestMap")
    _assert("pory param const", "MAP_{MAP_CONST}" in result, f"got {result}")

def test_parameterize_scripts_empty():
    _assert("pory param empty", _parameterize_scripts("", "Foo") == "")
    _assert("pory param none", _parameterize_scripts(None, "Foo") is None)


def test_create_stamp_basic():
    game, cleanup = _make_game()
    try:
        manifest = create_stamp(
            game, "LittlerootTown_BrendansHouse_1F",
            "Brendan House", exit_warp_indices=[0, 1],
            description="Test stamp", tags=["house"])

        _assert("create id", manifest["id"] == "brendan_house")
        _assert("create name", manifest["name"] == "Brendan House")
        _assert("create desc", manifest["description"] == "Test stamp")
        _assert("create width", manifest["width"] == 9)
        _assert("create height", manifest["height"] == 7)
        _assert("create tags", manifest["tags"] == ["house"])
        _assert("create source", manifest["created_from"] == "LittlerootTown_BrendansHouse_1F")
        _assert("create version", manifest["stamp_version"] == "1.0")

        # Check exit warps tagged
        exit_warps = [w for w in manifest["warp_events"]
                      if w.get("role") == "exit_warp"]
        _assert("create exit warps", len(exit_warps) == 2)

        # Check door_positions generated
        _assert("create doors", len(manifest["door_positions"]) == 2)

        # Check files on disk
        stamp_dir = os.path.join(game, STAMPS_DIR, "brendan_house")
        _assert("create dir exists", os.path.isdir(stamp_dir))
        _assert("create map.bin", os.path.isfile(
            os.path.join(stamp_dir, "map.bin")))
        _assert("create border.bin", os.path.isfile(
            os.path.join(stamp_dir, "border.bin")))
        _assert("create manifest", os.path.isfile(
            os.path.join(stamp_dir, "manifest.json")))

        # Verify parameterization
        obj = manifest["object_events"][0]
        _assert("create param script",
                "{map_name}" in obj["script"],
                f"got {obj['script']}")
    finally:
        cleanup()


def test_create_stamp_with_scripts():
    game, cleanup = _make_game(include_pory=True)
    try:
        manifest = create_stamp(
            game, "LittlerootTown_BrendansHouse_1F",
            "Brendan House Scripts", exit_warp_indices=[0],
            include_scripts=True)

        _assert("create script template has placeholder",
                "{map_name}" in manifest["script_template"])
        _assert("create script not default",
                "EventScript_OldMan" in manifest["script_template"])
    finally:
        cleanup()


def test_create_stamp_missing_map():
    game, cleanup = _make_game()
    try:
        raised = False
        try:
            create_stamp(game, "NonexistentMap", "Test", [])
        except ValueError:
            raised = True
        _assert("create missing map raises", raised)
    finally:
        cleanup()


def test_list_stamps_empty():
    tmp = tempfile.mkdtemp(prefix="torch_stamps_test_")
    try:
        result = list_stamps(tmp)
        _assert("list empty", result == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_list_stamps_multiple():
    game, cleanup = _make_game()
    try:
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Stamp A", [0], tags=["a"])
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Stamp B", [0], tags=["b"])

        result = list_stamps(game)
        _assert("list count", len(result) == 2, f"got {len(result)}")
        ids = {s["id"] for s in result}
        _assert("list ids", "stamp_a" in ids and "stamp_b" in ids,
                f"got {ids}")
    finally:
        cleanup()


def test_load_stamp_valid():
    game, cleanup = _make_game()
    try:
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Load Test", [0])
        loaded = load_stamp(game, "load_test")
        _assert("load valid", loaded is not None)
        _assert("load name", loaded["name"] == "Load Test")
        _assert("load has events", len(loaded["object_events"]) > 0)
    finally:
        cleanup()


def test_load_stamp_missing():
    tmp = tempfile.mkdtemp(prefix="torch_stamps_test_")
    try:
        result = load_stamp(tmp, "nonexistent")
        _assert("load missing", result is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_delete_stamp_exists():
    game, cleanup = _make_game()
    try:
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Delete Me", [0])
        _assert("delete exists before", load_stamp(game, "delete_me") is not None)
        result = delete_stamp(game, "delete_me")
        _assert("delete returns true", result is True)
        _assert("delete gone", load_stamp(game, "delete_me") is None)
    finally:
        cleanup()


def test_delete_stamp_not_found():
    tmp = tempfile.mkdtemp(prefix="torch_stamps_test_")
    try:
        result = delete_stamp(tmp, "nonexistent")
        _assert("delete not found", result is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_validate_valid():
    game, cleanup = _make_game()
    try:
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Valid Stamp", [0])
        result = validate_stamp_placement(
            game, "valid_stamp", "LittlerootTown", 5, 5)
        _assert("validate valid", result["valid"], f"errors: {result['errors']}")
        _assert("validate no errors", len(result["errors"]) == 0)
        _assert("validate has name", len(result["suggested_name"]) > 0)
    finally:
        cleanup()


def test_validate_missing_stamp():
    game, cleanup = _make_game()
    try:
        result = validate_stamp_placement(
            game, "nonexistent", "LittlerootTown", 5, 5)
        _assert("validate missing stamp", not result["valid"])
        _assert("validate missing stamp error",
                any("not found" in e for e in result["errors"]))
    finally:
        cleanup()


def test_validate_out_of_bounds():
    game, cleanup = _make_game(parent_width=10, parent_height=10)
    try:
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Bounds Test", [0])
        result = validate_stamp_placement(
            game, "bounds_test", "LittlerootTown", 15, 15)
        _assert("validate oob", not result["valid"])
        _assert("validate oob x",
                any("door_x" in e for e in result["errors"]))
        _assert("validate oob y",
                any("door_y" in e for e in result["errors"]))
    finally:
        cleanup()


def test_validate_missing_tileset():
    game, cleanup = _make_game()
    try:
        # Remove tilesets so they can't be found
        ts_dir = os.path.join(game, "data", "tilesets")
        shutil.rmtree(ts_dir)
        os.makedirs(ts_dir, exist_ok=True)

        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Tileset Test", [0])
        result = validate_stamp_placement(
            game, "tileset_test", "LittlerootTown", 5, 5)
        _assert("validate tileset", not result["valid"])
        _assert("validate tileset error",
                any("tileset" in e.lower() for e in result["errors"]))
    finally:
        cleanup()


def test_validate_name_collision():
    game, cleanup = _make_game()
    try:
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Collision Test", [0])
        # Create a map dir with the name that would be suggested
        suggested = f"LittlerootTown_CollisionTest"
        os.makedirs(os.path.join(game, "data", "maps", suggested),
                     exist_ok=True)
        result = validate_stamp_placement(
            game, "collision_test", "LittlerootTown", 5, 5)
        _assert("validate collision", not result["valid"])
        _assert("validate collision error",
                any("already exists" in e for e in result["errors"]))
    finally:
        cleanup()


def test_validate_warp_conflict_warning():
    game, cleanup = _make_game(
        parent_warps=[{"x": 5, "y": 5, "elevation": 0,
                       "dest_map": "MAP_SOME", "dest_warp_id": "0"}])
    try:
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Warp Warning", [0])
        result = validate_stamp_placement(
            game, "warp_warning", "LittlerootTown", 5, 5)
        _assert("validate warp warning", len(result["warnings"]) > 0)
        _assert("validate warp warning text",
                any("warp" in w.lower() for w in result["warnings"]))
    finally:
        cleanup()


def test_validate_name_override():
    game, cleanup = _make_game()
    try:
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Override Test", [0])
        result = validate_stamp_placement(
            game, "override_test", "LittlerootTown", 5, 5,
            map_name_override="CustomName")
        _assert("validate override name",
                result["suggested_name"] == "CustomName")
    finally:
        cleanup()


def test_round_trip():
    """Full round trip: create -> list -> load -> validate -> delete."""
    game, cleanup = _make_game()
    try:
        # Create
        manifest = create_stamp(
            game, "LittlerootTown_BrendansHouse_1F",
            "Round Trip", [0, 1],
            description="Full lifecycle", tags=["test"])
        stamp_id = manifest["id"]
        _assert("rt create", stamp_id == "round_trip")

        # List
        stamps = list_stamps(game)
        _assert("rt list", any(s["id"] == stamp_id for s in stamps))

        # Load
        loaded = load_stamp(game, stamp_id)
        _assert("rt load", loaded is not None)
        _assert("rt load match", loaded["name"] == manifest["name"])
        _assert("rt load width", loaded["width"] == manifest["width"])

        # Validate
        result = validate_stamp_placement(
            game, stamp_id, "LittlerootTown", 5, 5)
        _assert("rt validate", result["valid"],
                f"errors: {result['errors']}")

        # Delete
        _assert("rt delete", delete_stamp(game, stamp_id))
        _assert("rt gone", load_stamp(game, stamp_id) is None)
        _assert("rt list empty",
                not any(s["id"] == stamp_id for s in list_stamps(game)))
    finally:
        cleanup()


def test_get_stamps_dir_creates():
    tmp = tempfile.mkdtemp(prefix="torch_stamps_test_")
    try:
        stamps = get_stamps_dir(tmp)
        _assert("stamps dir created", os.path.isdir(stamps))
        _assert("stamps dir path", stamps.endswith(STAMPS_DIR))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# TUI helper tests
# ---------------------------------------------------------------------------

def test_list_maps_basic():
    """_custom_stamp_list_maps returns sorted map folder names."""
    from torch.__main__ import _custom_stamp_list_maps
    game, cleanup = _make_game()
    try:
        maps = _custom_stamp_list_maps(game)
        _assert("list_maps includes source",
                "LittlerootTown_BrendansHouse_1F" in maps)
        _assert("list_maps includes parent",
                "LittlerootTown" in maps)
        _assert("list_maps sorted", maps == sorted(maps))
    finally:
        cleanup()


def test_list_maps_empty():
    """_custom_stamp_list_maps returns empty list for missing dir."""
    from torch.__main__ import _custom_stamp_list_maps
    tmp = tempfile.mkdtemp(prefix="torch_stamps_test_")
    try:
        maps = _custom_stamp_list_maps(tmp)
        _assert("list_maps empty", maps == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_list_maps_no_mapjson():
    """_custom_stamp_list_maps skips folders without map.json."""
    from torch.__main__ import _custom_stamp_list_maps
    tmp = tempfile.mkdtemp(prefix="torch_stamps_test_")
    try:
        maps_dir = os.path.join(tmp, "data", "maps")
        os.makedirs(maps_dir, exist_ok=True)
        # Folder with no map.json
        os.makedirs(os.path.join(maps_dir, "EmptyFolder"))
        # Folder with map.json
        real_map = os.path.join(maps_dir, "RealMap")
        os.makedirs(real_map)
        with open(os.path.join(real_map, "map.json"), "w") as f:
            f.write("{}")
        maps = _custom_stamp_list_maps(tmp)
        _assert("list_maps no mapjson",
                maps == ["RealMap"],
                f"got {maps}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_stamp_info_output():
    """_custom_stamp_info runs without error on a valid stamp."""
    import io
    import sys
    from torch.__main__ import _custom_stamp_info
    game, cleanup = _make_game()
    try:
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "Info Test", [0, 1], description="Desc here")
        # Capture stdout
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            _custom_stamp_info(game, "info_test")
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        _assert("info shows name", "Info Test" in output)
        _assert("info shows desc", "Desc here" in output)
        _assert("info shows dims", "9x7" in output)
        _assert("info shows source",
                "LittlerootTown_BrendansHouse_1F" in output)
    finally:
        cleanup()


def test_stamp_info_missing():
    """_custom_stamp_info handles missing stamp gracefully."""
    import io
    import sys
    from torch.__main__ import _custom_stamp_info
    tmp = tempfile.mkdtemp(prefix="torch_stamps_test_")
    try:
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            _custom_stamp_info(tmp, "nonexistent")
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        _assert("info missing shows error", "not found" in output.lower())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_stamp_list_output():
    """_custom_stamp_list formats table output."""
    import io
    import sys
    from torch.__main__ import _custom_stamp_list
    game, cleanup = _make_game()
    try:
        create_stamp(game, "LittlerootTown_BrendansHouse_1F",
                     "List Output", [0])
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            _custom_stamp_list(game)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        _assert("list output shows name", "List Output" in output)
        _assert("list output shows id", "list_output" in output)
        _assert("list output shows count", "1" in output)
    finally:
        cleanup()


def test_stamp_list_empty_output():
    """_custom_stamp_list shows helpful message when empty."""
    import io
    import sys
    from torch.__main__ import _custom_stamp_list
    tmp = tempfile.mkdtemp(prefix="torch_stamps_test_")
    try:
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            _custom_stamp_list(tmp)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        _assert("list empty message", "no custom stamps" in output.lower())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Suite entry point
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("custom_stamps")

    # _slugify
    test_slugify_basic()
    test_slugify_special_chars()
    test_slugify_underscores()
    test_slugify_numbers()
    test_slugify_empty()

    # _map_name_to_const
    test_map_name_to_const_basic()
    test_map_name_to_const_with_underscores()
    test_map_name_to_const_with_floor()
    test_map_name_to_const_empty()
    test_map_name_to_const_route()

    # _parameterize_events
    test_parameterize_events_script_replacement()
    test_parameterize_events_dest_map()
    test_parameterize_events_deep_copy()
    test_parameterize_events_no_match()

    # _parameterize_scripts
    test_parameterize_scripts_basic()
    test_parameterize_scripts_const()
    test_parameterize_scripts_empty()

    # create_stamp
    test_create_stamp_basic()
    test_create_stamp_with_scripts()
    test_create_stamp_missing_map()

    # list_stamps
    test_list_stamps_empty()
    test_list_stamps_multiple()

    # load_stamp
    test_load_stamp_valid()
    test_load_stamp_missing()

    # delete_stamp
    test_delete_stamp_exists()
    test_delete_stamp_not_found()

    # validate_stamp_placement
    test_validate_valid()
    test_validate_missing_stamp()
    test_validate_out_of_bounds()
    test_validate_missing_tileset()
    test_validate_name_collision()
    test_validate_warp_conflict_warning()
    test_validate_name_override()

    # Round trip
    test_round_trip()

    # get_stamps_dir
    test_get_stamps_dir_creates()

    # TUI helpers
    test_list_maps_basic()
    test_list_maps_empty()
    test_list_maps_no_mapjson()
    test_stamp_info_output()
    test_stamp_info_missing()
    test_stamp_list_output()
    test_stamp_list_empty_output()
