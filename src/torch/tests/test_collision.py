"""Tests for the collision / walkability data module."""

import json
import os
import struct
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _assert
from torch.web.collision import (
    get_collision_grid,
    _collision_from_layout,
    _lookup_behavior,
    _load_tileset_attrs,
    _parse_attributes_bin,
)
from torch.web.api import _compute_patrol_positions


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _make_blockdata(tiles):
    """Build blockdata bytes from a list of (metatile_id, collision, elevation) tuples.

    Each tile is packed as u16: bits 0-9 = metatile_id, 10-11 = collision, 12-15 = elevation.
    """
    buf = bytearray()
    for mt_id, coll, elev in tiles:
        val = (mt_id & 0x3FF) | ((coll & 0x3) << 10) | ((elev & 0xF) << 12)
        buf += struct.pack("<H", val)
    return bytes(buf)


def _make_attrs(behaviors):
    """Build metatile_attributes.bin from a list of behavior values (u16 format)."""
    buf = bytearray()
    for beh in behaviors:
        buf += struct.pack("<H", beh & 0xFF)
    return bytes(buf)


def _setup_game_dir(width, height, tiles, pri_behaviors, sec_behaviors,
                    pri_name="general", sec_name="petalburg",
                    num_mt_primary=512):
    """Create a temporary game directory with the minimum files for collision loading.

    *tiles* is a list of (metatile_id, collision, elevation) tuples (w*h entries).
    Returns (tmpdir, map_name).
    """
    tmpdir = tempfile.mkdtemp(prefix="torch_collision_")
    map_name = "TestMap"

    # layouts.json
    layouts_dir = os.path.join(tmpdir, "data", "layouts")
    os.makedirs(layouts_dir, exist_ok=True)

    bd_rel = f"data/layouts/TestLayout/map.bin"
    layout_dir = os.path.join(tmpdir, "data", "layouts", "TestLayout")
    os.makedirs(layout_dir, exist_ok=True)
    with open(os.path.join(layout_dir, "map.bin"), "wb") as f:
        f.write(_make_blockdata(tiles))

    layouts = {"layouts_table_label": "gMapLayouts", "layouts": [{
        "id": "LAYOUT_TEST",
        "name": "TestLayout",
        "width": width,
        "height": height,
        "primary_tileset": f"gTileset_{pri_name.capitalize()}",
        "secondary_tileset": f"gTileset_{sec_name.capitalize()}",
        "blockdata_filepath": bd_rel,
    }]}
    with open(os.path.join(layouts_dir, "layouts.json"), "w") as f:
        json.dump(layouts, f, indent=2)

    # map.json
    map_dir = os.path.join(tmpdir, "data", "maps", map_name)
    os.makedirs(map_dir, exist_ok=True)
    with open(os.path.join(map_dir, "map.json"), "w") as f:
        json.dump({"id": "MAP_TEST_MAP", "layout": "LAYOUT_TEST"}, f, indent=2)

    # map_groups.json (needed by load_map_json)
    maps_dir = os.path.join(tmpdir, "data", "maps")
    with open(os.path.join(maps_dir, "map_groups.json"), "w") as f:
        json.dump({"gMapGroup_Test": [map_name]}, f, indent=2)

    # primary tileset
    pri_dir = os.path.join(tmpdir, "data", "tilesets", "primary", pri_name)
    os.makedirs(pri_dir, exist_ok=True)
    with open(os.path.join(pri_dir, "metatile_attributes.bin"), "wb") as f:
        f.write(_make_attrs(pri_behaviors))

    # secondary tileset
    sec_dir = os.path.join(tmpdir, "data", "tilesets", "secondary", sec_name)
    os.makedirs(sec_dir, exist_ok=True)
    with open(os.path.join(sec_dir, "metatile_attributes.bin"), "wb") as f:
        f.write(_make_attrs(sec_behaviors))

    # fieldmap.h
    inc_dir = os.path.join(tmpdir, "include")
    os.makedirs(inc_dir, exist_ok=True)
    with open(os.path.join(inc_dir, "fieldmap.h"), "w") as f:
        f.write(f"#define NUM_METATILES_IN_PRIMARY {num_mt_primary}\n")

    return tmpdir, map_name


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("collision")

    # --- blockdata parsing: extract metatile IDs ---
    try:
        data = _make_blockdata([(0, 0, 0), (100, 0, 0), (1023, 0, 0)])
        vals = []
        for i in range(3):
            v = struct.unpack_from("<H", data, i * 2)[0]
            vals.append(v & 0x3FF)
        _assert(vals == [0, 100, 1023], f"metatile IDs: {vals}")
        _ok("parse_blockdata_metatile_ids")
    except Exception as e:
        _fail("parse_blockdata_metatile_ids", e)

    # --- blockdata parsing: extract collision bits ---
    try:
        data = _make_blockdata([(0, 0, 0), (0, 1, 0), (0, 2, 0), (0, 3, 0)])
        colls = []
        for i in range(4):
            v = struct.unpack_from("<H", data, i * 2)[0]
            colls.append((v >> 10) & 0x3)
        _assert(colls == [0, 1, 2, 3], f"collision bits: {colls}")
        _ok("parse_blockdata_collision_bits")
    except Exception as e:
        _fail("parse_blockdata_collision_bits", e)

    # --- blockdata parsing: extract elevation ---
    try:
        data = _make_blockdata([(0, 0, 5), (0, 0, 15)])
        elevs = []
        for i in range(2):
            v = struct.unpack_from("<H", data, i * 2)[0]
            elevs.append((v >> 12) & 0xF)
        _assert(elevs == [5, 15], f"elevations: {elevs}")
        _ok("parse_blockdata_elevation")
    except Exception as e:
        _fail("parse_blockdata_elevation", e)

    # --- behavior lookup from primary tileset ---
    try:
        pri = [{"behavior": 0}, {"behavior": 1}, {"behavior": 48}]
        sec = [{"behavior": 99}]
        beh = _lookup_behavior(0, 512, pri, sec)
        _assert(beh == 0, f"primary[0] behavior={beh}")
        beh = _lookup_behavior(2, 512, pri, sec)
        _assert(beh == 48, f"primary[2] behavior={beh}")
        _ok("lookup_behavior_primary")
    except Exception as e:
        _fail("lookup_behavior_primary", e)

    # --- behavior lookup from secondary tileset (ID >= 512) ---
    try:
        pri = [{"behavior": 0}]
        sec = [{"behavior": 77}, {"behavior": 88}]
        beh = _lookup_behavior(512, 512, pri, sec)
        _assert(beh == 77, f"secondary[0] behavior={beh}")
        beh = _lookup_behavior(513, 512, pri, sec)
        _assert(beh == 88, f"secondary[1] behavior={beh}")
        _ok("lookup_behavior_secondary")
    except Exception as e:
        _fail("lookup_behavior_secondary", e)

    # --- behavior lookup out-of-range returns 0 ---
    try:
        beh = _lookup_behavior(999, 512, [], [])
        _assert(beh == 0, f"out of range behavior={beh}")
        _ok("lookup_behavior_out_of_range")
    except Exception as e:
        _fail("lookup_behavior_out_of_range", e)

    # --- full grid: single tile map ---
    tmpdir = None
    try:
        tiles = [(5, 1, 3)]
        pri_beh = [0] * 6  # behaviors for metatile IDs 0-5
        pri_beh[5] = 42
        tmpdir, map_name = _setup_game_dir(1, 1, tiles, pri_beh, [])

        result = get_collision_grid(tmpdir, map_name)
        _assert(result is not None, "result should not be None")
        w, h, coll, beh = result
        _assert(w == 1 and h == 1, f"dims: {w}x{h}")
        _assert(coll == [[1]], f"collision: {coll}")
        _assert(beh == [[42]], f"behaviors: {beh}")
        _ok("full_grid_single_tile")
    except Exception as e:
        _fail("full_grid_single_tile", e)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- full grid: 3x2 map with mixed primary/secondary ---
    tmpdir = None
    try:
        # 3x2 = 6 tiles
        # metatile IDs: 0(pri), 1(pri), 512(sec), 0(pri), 513(sec), 2(pri)
        # collision:     0,      1,      0,        0,      1,         0
        tiles = [
            (0, 0, 0), (1, 1, 0), (512, 0, 0),
            (0, 0, 0), (513, 1, 0), (2, 0, 0),
        ]
        pri_beh = [10, 11, 12]
        sec_beh = [20, 21]
        tmpdir, map_name = _setup_game_dir(3, 2, tiles, pri_beh, sec_beh)

        result = get_collision_grid(tmpdir, map_name)
        _assert(result is not None, "result should not be None")
        w, h, coll, beh = result
        _assert(w == 3 and h == 2, f"dims: {w}x{h}")
        _assert(coll[0] == [0, 1, 0], f"coll row 0: {coll[0]}")
        _assert(coll[1] == [0, 1, 0], f"coll row 1: {coll[1]}")
        _assert(beh[0] == [10, 11, 20], f"beh row 0: {beh[0]}")
        _assert(beh[1] == [10, 21, 12], f"beh row 1: {beh[1]}")
        _ok("full_grid_mixed_tilesets")
    except Exception as e:
        _fail("full_grid_mixed_tilesets", e)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- missing blockdata file ---
    tmpdir = None
    try:
        tmpdir, map_name = _setup_game_dir(2, 2,
                                           [(0, 0, 0)] * 4, [0], [0])
        # Delete the blockdata file
        bd_path = os.path.join(tmpdir, "data", "layouts", "TestLayout", "map.bin")
        os.remove(bd_path)

        result = get_collision_grid(tmpdir, map_name)
        _assert(result is None, "should return None for missing blockdata")
        _ok("missing_blockdata_returns_none")
    except Exception as e:
        _fail("missing_blockdata_returns_none", e)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- missing metatile_attributes.bin: behaviors should be 0 ---
    tmpdir = None
    try:
        tiles = [(0, 0, 0)]
        tmpdir, map_name = _setup_game_dir(1, 1, tiles, [5], [])
        # Delete the primary tileset's attributes
        attr_path = os.path.join(tmpdir, "data", "tilesets", "primary",
                                 "general", "metatile_attributes.bin")
        os.remove(attr_path)

        result = get_collision_grid(tmpdir, map_name)
        _assert(result is not None, "should still load (collision from blockdata)")
        w, h, coll, beh = result
        _assert(beh == [[0]], f"behavior should default to 0: {beh}")
        _ok("missing_attrs_defaults_behavior_zero")
    except Exception as e:
        _fail("missing_attrs_defaults_behavior_zero", e)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- missing map returns None ---
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="torch_collision_empty_")
        result = get_collision_grid(tmpdir, "NonexistentMap")
        _assert(result is None, "nonexistent map should return None")
        _ok("missing_map_returns_none")
    except Exception as e:
        _fail("missing_map_returns_none", e)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- empty map (0x0) returns None ---
    tmpdir = None
    try:
        tmpdir, map_name = _setup_game_dir(0, 0, [], [0], [0])
        result = get_collision_grid(tmpdir, map_name)
        _assert(result is None, "0x0 map should return None")
        _ok("empty_map_returns_none")
    except Exception as e:
        _fail("empty_map_returns_none", e)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- truncated blockdata returns None ---
    tmpdir = None
    try:
        tiles = [(0, 0, 0)]  # Only 1 tile of data
        tmpdir, map_name = _setup_game_dir(2, 2, tiles, [0], [0])
        # blockdata has 1 tile (2 bytes) but map expects 2*2=4 tiles (8 bytes)
        result = get_collision_grid(tmpdir, map_name)
        _assert(result is None, "truncated blockdata should return None")
        _ok("truncated_blockdata_returns_none")
    except Exception as e:
        _fail("truncated_blockdata_returns_none", e)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- _parse_attributes_bin with synthetic data ---
    try:
        # 3 metatiles: behaviors 0, 1, 0x30 (48)
        data = struct.pack("<HHH", 0x0000, 0x0001, 0x0030)
        attrs = _parse_attributes_bin(data)
        _assert(len(attrs) == 3, f"attrs count: {len(attrs)}")
        _assert(attrs[0]["behavior"] == 0, f"attr[0] behavior: {attrs[0]['behavior']}")
        _assert(attrs[1]["behavior"] == 1, f"attr[1] behavior: {attrs[1]['behavior']}")
        _assert(attrs[2]["behavior"] == 0x30, f"attr[2] behavior: {attrs[2]['behavior']}")
        _ok("parse_attributes_bin_synthetic")
    except Exception as e:
        _fail("parse_attributes_bin_synthetic", e)

    # --- custom NUM_METATILES_IN_PRIMARY ---
    tmpdir = None
    try:
        # With num_mt_primary=4, metatile ID 4 maps to secondary[0]
        tiles = [(4, 0, 0)]
        pri_beh = [10, 11, 12, 13]
        sec_beh = [99]
        tmpdir, map_name = _setup_game_dir(1, 1, tiles, pri_beh, sec_beh,
                                           num_mt_primary=4)

        result = get_collision_grid(tmpdir, map_name)
        _assert(result is not None, "result should not be None")
        w, h, coll, beh = result
        _assert(beh == [[99]], f"behavior should be 99 (secondary): {beh}")
        _ok("custom_num_metatiles_primary")
    except Exception as e:
        _fail("custom_num_metatiles_primary", e)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- all collision values in a row ---
    tmpdir = None
    try:
        tiles = [(0, 0, 0), (0, 1, 0), (0, 2, 0), (0, 3, 0)]
        tmpdir, map_name = _setup_game_dir(4, 1, tiles, [0], [])

        result = get_collision_grid(tmpdir, map_name)
        _assert(result is not None, "result should not be None")
        w, h, coll, beh = result
        _assert(coll[0] == [0, 1, 2, 3], f"all collision values: {coll[0]}")
        _ok("all_collision_values")
    except Exception as e:
        _fail("all_collision_values", e)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # -----------------------------------------------------------------------
    # Patrol position filtering tests
    # -----------------------------------------------------------------------

    # --- no collision data: all positions returned (legacy behavior) ---
    try:
        obj = {"x": 5, "y": 5, "movement_type": "MOVEMENT_TYPE_WANDER_AROUND",
               "movement_range_x": "1", "movement_range_y": "1"}
        pos = _compute_patrol_positions(obj)
        coords = {(p["x"], p["y"]) for p in pos}
        # 3x3 = 9 tiles
        _assert(len(coords) == 9, f"no filter: expected 9, got {len(coords)}")
        _ok("patrol_no_collision_data")
    except Exception as e:
        _fail("patrol_no_collision_data", e)

    # --- collision grid filters impassable tiles ---
    try:
        # 10x10 grid, NPC at (5,5), range 1 -> 3x3 area (4-6, 4-6)
        # Make (4,4) and (6,6) impassable via collision
        coll = [[0]*10 for _ in range(10)]
        coll[4][4] = 1  # impassable
        coll[6][6] = 1  # impassable
        beh = [[0]*10 for _ in range(10)]

        obj = {"x": 5, "y": 5, "movement_type": "MOVEMENT_TYPE_WANDER_AROUND",
               "movement_range_x": "1", "movement_range_y": "1"}
        pos = _compute_patrol_positions(obj, collision_grid=coll, behavior_grid=beh)
        coords = {(p["x"], p["y"]) for p in pos}
        _assert((4, 4) not in coords, "(4,4) should be filtered")
        _assert((6, 6) not in coords, "(6,6) should be filtered")
        _assert((5, 5) in coords, "home tile (5,5) should be kept")
        _assert(len(coords) == 7, f"expected 7 passable tiles, got {len(coords)}")
        _ok("patrol_collision_filters_impassable")
    except Exception as e:
        _fail("patrol_collision_filters_impassable", e)

    # --- behavior grid filters wall behaviors ---
    try:
        coll = [[0]*10 for _ in range(10)]
        beh = [[0]*10 for _ in range(10)]
        beh[4][5] = 1   # MB_IMPASSABLE
        beh[5][4] = 48  # wall-type behavior

        obj = {"x": 5, "y": 5, "movement_type": "MOVEMENT_TYPE_WANDER_AROUND",
               "movement_range_x": "1", "movement_range_y": "1"}
        pos = _compute_patrol_positions(obj, collision_grid=coll, behavior_grid=beh)
        coords = {(p["x"], p["y"]) for p in pos}
        _assert((5, 4) not in coords, "(5,4) behavior=1 should be filtered")
        _assert((4, 5) not in coords, "(4,5) behavior=48 should be filtered")
        _assert((5, 5) in coords, "home tile always kept")
        _assert(len(coords) == 7, f"expected 7 passable tiles, got {len(coords)}")
        _ok("patrol_behavior_filters_walls")
    except Exception as e:
        _fail("patrol_behavior_filters_walls", e)

    # --- water/grass behaviors NOT filtered (walkable terrain) ---
    try:
        coll = [[0]*10 for _ in range(10)]
        beh = [[0]*10 for _ in range(10)]
        # Behavior 4 = MB_TALL_GRASS, 16 = MB_POND_WATER — both walkable
        beh[4][5] = 4
        beh[5][6] = 16

        obj = {"x": 5, "y": 5, "movement_type": "MOVEMENT_TYPE_WANDER_AROUND",
               "movement_range_x": "1", "movement_range_y": "1"}
        pos = _compute_patrol_positions(obj, collision_grid=coll, behavior_grid=beh)
        coords = {(p["x"], p["y"]) for p in pos}
        _assert((5, 4) in coords, "grass tile should NOT be filtered")
        _assert((6, 5) in coords, "water tile should NOT be filtered")
        _assert(len(coords) == 9, f"expected all 9 tiles, got {len(coords)}")
        _ok("patrol_water_grass_not_filtered")
    except Exception as e:
        _fail("patrol_water_grass_not_filtered", e)

    # --- NPC home tile on impassable: still kept ---
    try:
        coll = [[1]*10 for _ in range(10)]  # everything impassable
        beh = [[0]*10 for _ in range(10)]

        obj = {"x": 5, "y": 5, "movement_type": "MOVEMENT_TYPE_WANDER_AROUND",
               "movement_range_x": "1", "movement_range_y": "1"}
        pos = _compute_patrol_positions(obj, collision_grid=coll, behavior_grid=beh)
        coords = {(p["x"], p["y"]) for p in pos}
        _assert((5, 5) in coords, "home tile must always be kept")
        _assert(len(coords) == 1, f"expected only home tile, got {len(coords)}")
        _ok("patrol_home_tile_always_kept")
    except Exception as e:
        _fail("patrol_home_tile_always_kept", e)

    # --- stationary NPC: no filtering needed ---
    try:
        coll = [[1]*10 for _ in range(10)]
        beh = [[1]*10 for _ in range(10)]  # all walls

        obj = {"x": 3, "y": 3, "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
               "movement_range_x": "0", "movement_range_y": "0"}
        pos = _compute_patrol_positions(obj, collision_grid=coll, behavior_grid=beh)
        _assert(len(pos) == 1, f"stationary: expected 1, got {len(pos)}")
        _assert(pos[0]["x"] == 3 and pos[0]["y"] == 3, "should be at origin")
        _ok("patrol_stationary_on_wall")
    except Exception as e:
        _fail("patrol_stationary_on_wall", e)

    # --- linear patrol (up/down) with collision ---
    try:
        coll = [[0]*10 for _ in range(10)]
        beh = [[0]*10 for _ in range(10)]
        coll[3][5] = 1  # wall above NPC at y=3

        obj = {"x": 5, "y": 5, "movement_type": "MOVEMENT_TYPE_WALK_UP_AND_DOWN",
               "movement_range_x": "0", "movement_range_y": "2"}
        pos = _compute_patrol_positions(obj, collision_grid=coll, behavior_grid=beh)
        coords = {(p["x"], p["y"]) for p in pos}
        _assert((5, 3) not in coords, "wall at (5,3) should be filtered")
        _assert((5, 4) in coords, "(5,4) should be passable")
        _assert((5, 5) in coords, "home tile kept")
        _assert((5, 6) in coords, "(5,6) should be passable")
        _assert((5, 7) in coords, "(5,7) should be passable")
        _assert(len(coords) == 4, f"expected 4 tiles, got {len(coords)}")
        _ok("patrol_linear_with_collision")
    except Exception as e:
        _fail("patrol_linear_with_collision", e)

    # --- only collision_grid provided, no behavior_grid ---
    try:
        coll = [[0]*10 for _ in range(10)]
        coll[4][4] = 1

        obj = {"x": 5, "y": 5, "movement_type": "MOVEMENT_TYPE_WANDER_AROUND",
               "movement_range_x": "1", "movement_range_y": "1"}
        pos = _compute_patrol_positions(obj, collision_grid=coll, behavior_grid=None)
        coords = {(p["x"], p["y"]) for p in pos}
        _assert((4, 4) not in coords, "collision-only: (4,4) filtered")
        _assert(len(coords) == 8, f"expected 8, got {len(coords)}")
        _ok("patrol_collision_only_no_behavior")
    except Exception as e:
        _fail("patrol_collision_only_no_behavior", e)

    # --- only behavior_grid provided, no collision_grid ---
    try:
        beh = [[0]*10 for _ in range(10)]
        beh[6][6] = 1  # MB_IMPASSABLE

        obj = {"x": 5, "y": 5, "movement_type": "MOVEMENT_TYPE_WANDER_AROUND",
               "movement_range_x": "1", "movement_range_y": "1"}
        pos = _compute_patrol_positions(obj, collision_grid=None, behavior_grid=beh)
        coords = {(p["x"], p["y"]) for p in pos}
        _assert((6, 6) not in coords, "behavior-only: (6,6) filtered")
        _assert(len(coords) == 8, f"expected 8, got {len(coords)}")
        _ok("patrol_behavior_only_no_collision")
    except Exception as e:
        _fail("patrol_behavior_only_no_collision", e)
