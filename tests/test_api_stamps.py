"""Tests for the Custom Stamps API endpoints (api_stamps.py)."""
import json
import os
import shutil
import tempfile

from torch.tests.harness import _begin_suite, _ok, _fail, _assert
from torch.custom_stamps import _map_name_to_const


# ---------------------------------------------------------------------------
# Mock handler infrastructure
# ---------------------------------------------------------------------------

class _MockServer:
    def __init__(self, game_path):
        self.game_path = game_path


class _MockHandler:
    """Minimal mock of http.server.BaseHTTPRequestHandler for API tests."""

    def __init__(self, game_path, path="/", body=None):
        self.server = _MockServer(game_path)
        self.path = path
        self.headers = {}
        self._body = None
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            self._body = raw
            self.headers["Content-Length"] = str(len(raw))
        else:
            self.headers["Content-Length"] = "0"

    class _Rfile:
        def __init__(self, data):
            self._data = data
            self._pos = 0
        def read(self, n):
            chunk = self._data[self._pos:self._pos + n]
            self._pos += n
            return chunk

    @property
    def rfile(self):
        return self._Rfile(self._body or b"")

    def get(self, key, default=None):
        return self.headers.get(key, default)


# ---------------------------------------------------------------------------
# Game fixture builder
# ---------------------------------------------------------------------------

def _make_game(source_map="TestInterior_1F", parent_map="TestTown",
               map_type="MAP_TYPE_INDOOR"):
    """Create a minimal game dir with source map, parent map, layouts."""
    tmp = tempfile.mkdtemp(prefix="torch_api_stamps_")

    # Source map
    src_dir = os.path.join(tmp, "data", "maps", source_map)
    os.makedirs(src_dir, exist_ok=True)
    src_json = {
        "id": f"MAP_{_map_name_to_const(source_map)}",
        "name": source_map,
        "layout": f"LAYOUT_{_map_name_to_const(source_map)}",
        "music": "MUS_PALLET_TOWN",
        "map_type": map_type,
        "region_map_section": "MAPSEC_NONE",
        "object_events": [
            {
                "graphics_id": "OBJ_EVENT_GFX_BOY_1",
                "x": 3, "y": 2, "elevation": 3,
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "movement_range_x": 0, "movement_range_y": 0,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "script": f"{source_map}_EventScript_Npc1",
                "flag": "0",
            }
        ],
        "warp_events": [
            {"x": 3, "y": 6, "elevation": 0,
             "dest_map": f"MAP_{_map_name_to_const(parent_map)}",
             "dest_warp_id": "0"},
        ],
        "coord_events": [],
        "bg_events": [],
    }
    with open(os.path.join(src_dir, "map.json"), "w") as f:
        json.dump(src_json, f, indent=2, ensure_ascii=False)

    # Parent map
    parent_dir = os.path.join(tmp, "data", "maps", parent_map)
    os.makedirs(parent_dir, exist_ok=True)
    parent_json = {
        "id": f"MAP_{_map_name_to_const(parent_map)}",
        "name": parent_map,
        "layout": f"LAYOUT_{_map_name_to_const(parent_map)}",
        "music": "MUS_PALLET_TOWN",
        "map_type": "MAP_TYPE_TOWN",
        "region_map_section": "MAPSEC_NONE",
        "object_events": [],
        "warp_events": [],
        "coord_events": [],
        "bg_events": [],
    }
    with open(os.path.join(parent_dir, "map.json"), "w") as f:
        json.dump(parent_json, f, indent=2, ensure_ascii=False)

    # Layouts
    src_layout_name = _map_name_to_const(source_map)
    parent_layout_name = _map_name_to_const(parent_map)

    for layout_dir_name in [source_map, parent_map]:
        ld = os.path.join(tmp, "data", "layouts", layout_dir_name)
        os.makedirs(ld, exist_ok=True)
        with open(os.path.join(ld, "map.bin"), "wb") as f:
            f.write(b"\x01\x02" * 63)  # 9x7
        with open(os.path.join(ld, "border.bin"), "wb") as f:
            f.write(b"\x03\x04" * 4)

    layouts_json = {
        "layouts_table_label": "gMapLayouts",
        "layouts": [
            {
                "id": f"LAYOUT_{src_layout_name}",
                "name": f"{source_map}_Layout",
                "width": 9, "height": 7,
                "primary_tileset": "gTileset_Building",
                "secondary_tileset": "gTileset_BrendansMaysHouse",
                "border_filepath": f"data/layouts/{source_map}/border.bin",
                "blockdata_filepath": f"data/layouts/{source_map}/map.bin",
            },
            {
                "id": f"LAYOUT_{parent_layout_name}",
                "name": f"{parent_map}_Layout",
                "width": 20, "height": 20,
                "primary_tileset": "gTileset_General",
                "secondary_tileset": "gTileset_Petalburg",
                "border_filepath": f"data/layouts/{parent_map}/border.bin",
                "blockdata_filepath": f"data/layouts/{parent_map}/map.bin",
            },
        ],
    }
    lay_dir = os.path.join(tmp, "data", "layouts")
    with open(os.path.join(lay_dir, "layouts.json"), "w") as f:
        json.dump(layouts_json, f, indent=2, ensure_ascii=False)

    # Tilesets
    for ts in ["building", "brendansmayshouse", "general", "petalburg"]:
        os.makedirs(os.path.join(tmp, "data", "tilesets", "primary", ts),
                     exist_ok=True)

    def cleanup():
        shutil.rmtree(tmp, ignore_errors=True)

    return tmp, cleanup


def _create_stamp(game_path, name="Test House", source_map="TestInterior_1F"):
    """Helper to create a stamp in the test game dir."""
    from torch.custom_stamps import create_stamp
    return create_stamp(
        game_path, source_map, name, [0],
        description="A test stamp", tags=["test"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_list_stamps_empty():
    """GET /api/stamps with no stamps returns empty list."""
    game, cleanup = _make_game()
    try:
        from torch.web.api_stamps import handle_list_stamps
        handler = _MockHandler(game, "/api/stamps")
        result = handle_list_stamps(handler, None, {})
        _assert("list empty ok", result["ok"] is True)
        _assert("list empty data", result["data"]["stamps"] == [])
    finally:
        cleanup()


def test_list_stamps_with_stamps():
    """GET /api/stamps returns stamps when they exist."""
    game, cleanup = _make_game()
    try:
        _create_stamp(game)
        from torch.web.api_stamps import handle_list_stamps
        handler = _MockHandler(game, "/api/stamps")
        result = handle_list_stamps(handler, None, {})
        _assert("list has stamps", len(result["data"]["stamps"]) == 1)
        _assert("list stamp name", result["data"]["stamps"][0]["name"] == "Test House")
    finally:
        cleanup()


def test_get_stamp_found():
    """GET /api/stamps/<id> returns manifest when found."""
    game, cleanup = _make_game()
    try:
        manifest = _create_stamp(game)
        stamp_id = manifest["id"]

        from torch.web.api_stamps import handle_get_stamp
        import re
        pattern = re.compile(r"^/api/stamps/(?P<stamp_id>[A-Za-z0-9_]+)$")
        match = pattern.match(f"/api/stamps/{stamp_id}")

        handler = _MockHandler(game, f"/api/stamps/{stamp_id}")
        result = handle_get_stamp(handler, match, {})
        _assert("get stamp ok", result["ok"] is True)
        _assert("get stamp name", result["data"]["name"] == "Test House")
    finally:
        cleanup()


def test_get_stamp_not_found():
    """GET /api/stamps/<id> returns 404 for missing stamp."""
    game, cleanup = _make_game()
    try:
        from torch.web.api_stamps import handle_get_stamp
        import re
        pattern = re.compile(r"^/api/stamps/(?P<stamp_id>[A-Za-z0-9_]+)$")
        match = pattern.match("/api/stamps/nonexistent")

        handler = _MockHandler(game, "/api/stamps/nonexistent")
        result = handle_get_stamp(handler, match, {})
        _assert("get stamp 404", result["ok"] is False)
        _assert("get stamp 404 status", result["_status"] == 404)
    finally:
        cleanup()


def test_create_stamp_success():
    """POST /api/stamps/create creates a new stamp."""
    game, cleanup = _make_game()
    try:
        from torch.web.api_stamps import handle_create_stamp
        body = {
            "source_map": "TestInterior_1F",
            "name": "Custom Interior",
            "exit_warp_indices": [0],
            "description": "A nice house",
            "tags": ["house"],
        }
        handler = _MockHandler(game, "/api/stamps/create", body=body)
        result = handle_create_stamp(handler, None, {})
        _assert("create ok", result["ok"] is True)
        _assert("create success", result["data"]["success"] is True)
        _assert("create stamp name",
                result["data"]["stamp"]["name"] == "Custom Interior")
    finally:
        cleanup()


def test_create_stamp_missing_fields():
    """POST /api/stamps/create rejects missing required fields."""
    game, cleanup = _make_game()
    try:
        from torch.web.api_stamps import handle_create_stamp

        # Missing name
        body = {"source_map": "TestInterior_1F", "exit_warp_indices": [0]}
        handler = _MockHandler(game, "/api/stamps/create", body=body)
        result = handle_create_stamp(handler, None, {})
        _assert("create missing name", result["ok"] is False)

        # Missing exit_warp_indices
        body = {"source_map": "TestInterior_1F", "name": "Foo"}
        handler = _MockHandler(game, "/api/stamps/create", body=body)
        result = handle_create_stamp(handler, None, {})
        _assert("create missing warps", result["ok"] is False)
    finally:
        cleanup()


def test_delete_stamp_success():
    """DELETE /api/stamps/<id> deletes an existing stamp."""
    game, cleanup = _make_game()
    try:
        manifest = _create_stamp(game)
        stamp_id = manifest["id"]

        from torch.web.api_stamps import handle_delete_stamp
        import re
        pattern = re.compile(r"^/api/stamps/(?P<stamp_id>[A-Za-z0-9_]+)$")
        match = pattern.match(f"/api/stamps/{stamp_id}")

        handler = _MockHandler(game, f"/api/stamps/{stamp_id}")
        result = handle_delete_stamp(handler, match, {})
        _assert("delete ok", result["ok"] is True)
        _assert("delete success", result["data"]["success"] is True)

        # Verify it's gone
        from torch.custom_stamps import load_stamp
        _assert("delete verified", load_stamp(game, stamp_id) is None)
    finally:
        cleanup()


def test_delete_stamp_not_found():
    """DELETE /api/stamps/<id> returns 404 for missing stamp."""
    game, cleanup = _make_game()
    try:
        from torch.web.api_stamps import handle_delete_stamp
        import re
        pattern = re.compile(r"^/api/stamps/(?P<stamp_id>[A-Za-z0-9_]+)$")
        match = pattern.match("/api/stamps/nonexistent")

        handler = _MockHandler(game, "/api/stamps/nonexistent")
        result = handle_delete_stamp(handler, match, {})
        _assert("delete 404", result["ok"] is False)
        _assert("delete 404 status", result["_status"] == 404)
    finally:
        cleanup()


def test_preview_valid():
    """GET /api/stamps/preview returns valid for a good placement."""
    game, cleanup = _make_game()
    try:
        manifest = _create_stamp(game)
        stamp_id = manifest["id"]

        from torch.web.api_stamps import handle_stamp_preview
        path = (f"/api/stamps/preview?stamp_id={stamp_id}"
                f"&parent_map=TestTown&door_x=5&door_y=5")
        handler = _MockHandler(game, path)
        result = handle_stamp_preview(handler, None, {})
        _assert("preview ok", result["ok"] is True)
        _assert("preview valid", result["data"]["valid"] is True)
        _assert("preview has name", len(result["data"]["suggested_name"]) > 0)
    finally:
        cleanup()


def test_preview_invalid_stamp():
    """GET /api/stamps/preview returns invalid for nonexistent stamp."""
    game, cleanup = _make_game()
    try:
        from torch.web.api_stamps import handle_stamp_preview
        path = ("/api/stamps/preview?stamp_id=nope"
                "&parent_map=TestTown&door_x=5&door_y=5")
        handler = _MockHandler(game, path)
        result = handle_stamp_preview(handler, None, {})
        _assert("preview invalid ok", result["ok"] is True)
        _assert("preview not valid", result["data"]["valid"] is False)
        _assert("preview has errors", len(result["data"]["errors"]) > 0)
    finally:
        cleanup()


def test_preview_missing_params():
    """GET /api/stamps/preview rejects missing params."""
    game, cleanup = _make_game()
    try:
        from torch.web.api_stamps import handle_stamp_preview
        handler = _MockHandler(game, "/api/stamps/preview?stamp_id=foo")
        result = handle_stamp_preview(handler, None, {})
        _assert("preview missing parent", result["ok"] is False)
    finally:
        cleanup()


def test_source_maps():
    """GET /api/stamps/source-maps returns maps with warps."""
    game, cleanup = _make_game()
    try:
        from torch.web.api_stamps import handle_source_maps
        from torch.project_files import clear_project_cache
        clear_project_cache()

        handler = _MockHandler(game, "/api/stamps/source-maps")
        result = handle_source_maps(handler, None, {})
        _assert("source maps ok", result["ok"] is True)
        maps = result["data"]["maps"]
        # TestInterior_1F has a warp, TestTown has none
        names = [m["name"] for m in maps]
        _assert("source has interior", "TestInterior_1F" in names)
        _assert("source no parent (no warps)", "TestTown" not in names)
    finally:
        cleanup()


def test_source_map_warps():
    """GET /api/stamps/source-map/<name>/warps returns warp data."""
    game, cleanup = _make_game()
    try:
        from torch.web.api_stamps import handle_source_map_warps
        import re
        pattern = re.compile(
            r"^/api/stamps/source-map/(?P<name>[A-Za-z0-9_]+)/warps$")
        match = pattern.match("/api/stamps/source-map/TestInterior_1F/warps")

        handler = _MockHandler(game,
                               "/api/stamps/source-map/TestInterior_1F/warps")
        result = handle_source_map_warps(handler, match, {})
        _assert("warps ok", result["ok"] is True)
        warps = result["data"]["warps"]
        _assert("warps count", len(warps) == 1)
        _assert("warp has index", warps[0]["index"] == 0)
        _assert("warp has x", warps[0]["x"] == 3)
    finally:
        cleanup()


def test_source_map_warps_not_found():
    """GET /api/stamps/source-map/<name>/warps returns 404 for bad map."""
    game, cleanup = _make_game()
    try:
        from torch.web.api_stamps import handle_source_map_warps
        import re
        pattern = re.compile(
            r"^/api/stamps/source-map/(?P<name>[A-Za-z0-9_]+)/warps$")
        match = pattern.match("/api/stamps/source-map/NoSuchMap/warps")

        handler = _MockHandler(game,
                               "/api/stamps/source-map/NoSuchMap/warps")
        result = handle_source_map_warps(handler, match, {})
        _assert("warps 404", result["ok"] is False)
        _assert("warps 404 status", result["_status"] == 404)
    finally:
        cleanup()


def test_no_game_path():
    """All endpoints return 500 when game_path is empty."""
    from torch.web.api_stamps import (
        handle_list_stamps, handle_source_maps,
    )
    handler = _MockHandler("", "/api/stamps")
    result = handle_list_stamps(handler, None, {})
    _assert("no game path error", result["ok"] is False)
    _assert("no game path 500", result["_status"] == 500)


# ---------------------------------------------------------------------------
# Suite runner
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("Stamp API  (list, get, create, delete, preview, source)")

    test_list_stamps_empty()
    test_list_stamps_with_stamps()
    test_get_stamp_found()
    test_get_stamp_not_found()
    test_create_stamp_success()
    test_create_stamp_missing_fields()
    test_delete_stamp_success()
    test_delete_stamp_not_found()
    test_preview_valid()
    test_preview_invalid_stamp()
    test_preview_missing_params()
    test_source_maps()
    test_source_map_warps()
    test_source_map_warps_not_found()
    test_no_game_path()
