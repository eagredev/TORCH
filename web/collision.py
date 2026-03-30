# TORCH_MODULE: Collision Data
# TORCH_GROUP: Web
"""Map collision and walkability data.

Parses map blockdata and metatile attributes to produce per-tile collision
and behavior grids.  Used by the collision overlay API endpoint and by
patrol position filtering in the NPC editor.

Blockdata format (pokeemerald-expansion):
  Each tile = u16 (little-endian)
    bits 0-9:   metatile ID (0-1023)
    bits 10-11: collision (0 = passable, 1-3 = impassable/directional)
    bits 12-15: elevation

Metatile attributes:
  Each entry = u16 (2 bytes, little-endian)
    behavior = val & 0xFF
"""

import os
import re
import struct


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NUM_METATILES_IN_PRIMARY_DEFAULT = 512


# ---------------------------------------------------------------------------
# Attribute parsing (inlined from api_metatiles to avoid circular imports)
# ---------------------------------------------------------------------------

def _parse_attributes_bin(data):
    """Parse metatile_attributes.bin (u16 format).

    Each attribute is a u16: ``behavior = val & 0xFF``,
    ``layer_type = (val >> 12) & 0xF``.

    Returns list of ``{"behavior": int, "layer_type": int, "raw": int}``.
    """
    total = len(data)
    if total == 0:
        return []

    attrs = []
    for offset in range(0, total, 2):
        if offset + 2 > total:
            break
        val = struct.unpack_from("<H", data, offset)[0]
        attrs.append({
            "behavior": val & 0xFF,
            "layer_type": (val >> 12) & 0xF,
            "raw": val,
        })
    return attrs


def _resolve_tileset_dir(game_path, name):
    """Find the tileset directory for *name*.

    Searches secondary then primary.  Returns (dir_path, tier) or
    (None, None) if not found.
    """
    for tier in ("secondary", "primary"):
        candidate = os.path.normpath(
            os.path.join(game_path, "data", "tilesets", tier, name))
        if os.path.isdir(candidate):
            return candidate, tier
    return None, None


# ---------------------------------------------------------------------------
# Core grid builder
# ---------------------------------------------------------------------------

def get_collision_grid(game_path, map_name):
    """Return collision and behavior grids for a map.

    Returns ``(width, height, collision_grid, behavior_grid)`` where:
    - ``collision_grid[y][x]`` = collision bits from blockdata (0 = passable)
    - ``behavior_grid[y][x]``  = metatile behavior ID

    Returns ``None`` if data cannot be loaded (missing files, corrupt data).
    """
    from torch.project_files import load_map_json, load_layouts

    # --- load map.json and find layout ---
    map_data = load_map_json(game_path, map_name)
    if not map_data:
        return None

    layout_id = map_data.get("layout", "")
    if not layout_id:
        return None

    layouts_data = load_layouts(game_path)
    if not layouts_data:
        return None

    layout = None
    for lay in layouts_data.get("layouts", []):
        if lay.get("id") == layout_id:
            layout = lay
            break
    if not layout:
        return None

    return _collision_from_layout(game_path, layout)


def _collision_from_layout(game_path, layout):
    """Build collision grids from a resolved layout dict.

    Returns ``(width, height, collision_grid, behavior_grid)`` or ``None``.
    """
    map_w = layout.get("width", 0)
    map_h = layout.get("height", 0)
    if map_w <= 0 or map_h <= 0:
        return None

    # --- read blockdata ---
    bd_rel = layout.get("blockdata_filepath", "")
    if not bd_rel:
        return None

    bd_path = os.path.join(game_path, bd_rel)
    if not os.path.isfile(bd_path):
        return None

    try:
        with open(bd_path, "rb") as f:
            bd_data = f.read()
    except OSError:
        return None

    expected = map_w * map_h * 2
    if len(bd_data) < expected:
        return None

    # --- parse blockdata into metatile IDs and collision bits ---
    metatile_ids = []
    collision_flat = []
    for i in range(map_w * map_h):
        val = struct.unpack_from("<H", bd_data, i * 2)[0]
        metatile_ids.append(val & 0x3FF)
        collision_flat.append((val >> 10) & 0x3)

    # --- load metatile attributes from both tilesets ---
    num_mt_primary = _get_num_metatiles_primary(game_path)
    pri_attrs = _load_tileset_attrs(game_path, layout.get("primary_tileset", ""))
    sec_attrs = _load_tileset_attrs(game_path, layout.get("secondary_tileset", ""))

    # --- build grids ---
    collision_grid = []
    behavior_grid = []
    idx = 0
    for y in range(map_h):
        coll_row = []
        beh_row = []
        for x in range(map_w):
            coll_row.append(collision_flat[idx])
            mt_id = metatile_ids[idx]
            beh_row.append(_lookup_behavior(mt_id, num_mt_primary,
                                            pri_attrs, sec_attrs))
            idx += 1
        collision_grid.append(coll_row)
        behavior_grid.append(beh_row)

    return map_w, map_h, collision_grid, behavior_grid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_num_metatiles_primary(game_path):
    """Read NUM_METATILES_IN_PRIMARY from fieldmap.h (default 512)."""
    fmap = os.path.join(game_path, "include", "fieldmap.h")
    if not os.path.isfile(fmap):
        return NUM_METATILES_IN_PRIMARY_DEFAULT
    try:
        with open(fmap, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(
                    r"#define\s+NUM_METATILES_IN_PRIMARY\s+(\d+)", line)
                if m:
                    return int(m.group(1))
    except OSError:
        pass
    return NUM_METATILES_IN_PRIMARY_DEFAULT


def _load_tileset_attrs(game_path, ts_const):
    """Load metatile_attributes.bin for a tileset constant like gTileset_General.

    Returns a list of ``{"behavior": int, ...}`` dicts, or an empty list.
    """
    if not ts_const:
        return []

    name = ts_const
    if name.startswith("gTileset_"):
        name = name[len("gTileset_"):]
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name).lower()

    ts_dir, _ = _resolve_tileset_dir(game_path, name)
    if not ts_dir:
        return []

    attr_path = os.path.join(ts_dir, "metatile_attributes.bin")
    if not os.path.isfile(attr_path):
        return []

    try:
        with open(attr_path, "rb") as f:
            data = f.read()
    except OSError:
        return []

    return _parse_attributes_bin(data)


def _lookup_behavior(metatile_id, num_mt_primary, pri_attrs, sec_attrs):
    """Look up the behavior for a metatile ID.

    IDs < num_mt_primary come from the primary tileset.
    IDs >= num_mt_primary come from the secondary tileset (offset subtracted).
    Returns 0 if the attribute cannot be found.
    """
    if metatile_id < num_mt_primary:
        if metatile_id < len(pri_attrs):
            return pri_attrs[metatile_id]["behavior"]
    else:
        sec_idx = metatile_id - num_mt_primary
        if sec_idx < len(sec_attrs):
            return sec_attrs[sec_idx]["behavior"]
    return 0


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

def _register_routes():
    """Register the collision API route.

    Called lazily to avoid circular imports with torch.web.api.
    """
    from torch.web.api import api_route, ok_response, error_response

    @api_route("GET", r"/api/maps/(?P<name>[A-Za-z0-9_]+)/collision")
    def handle_map_collision(handler, match, query_params):
        """Return collision and behavior grids for a map."""
        game_path = getattr(handler.server, "game_path", "")
        if not game_path:
            return error_response("No game path configured", 500)

        map_name = match.group("name")

        result = get_collision_grid(game_path, map_name)
        if result is None:
            return error_response(
                f"Cannot load collision data for {map_name}", 404)

        width, height, collision_grid, behavior_grid = result
        return ok_response({
            "width": width,
            "height": height,
            "collision": collision_grid,
            "behaviors": behavior_grid,
        })


_register_routes()
