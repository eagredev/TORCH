# TORCH_MODULE: Web API — Map Renderer
# TORCH_GROUP: Web
"""Map rendering API endpoints for the TORCH web GUI.

Provides server-side map PNG composition, consolidated event data,
and raw blockdata endpoints for the unified map IDE.

The map renderer chains existing parsing primitives from api_metatiles.py:
  - _decode_indexed_png() -> tile pixel indices
  - _parse_metatile_bin() -> metatile tile refs
  - _parse_pal_file() -> palette colors

Routes registered via the shared api_route decorator.
"""

import json
import os
import re
import struct
import zlib

from torch.web.api import api_route, ok_response, error_response, _safe_path
from torch.web.api_metatiles import (
    _decode_indexed_png,
    _parse_metatile_bin,
    _parse_pal_file,
    _resolve_tileset_dir,
)
from torch.project_files import load_map_json, load_layouts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_game_path(handler):
    """Extract game_path from the server, returning (path, error_response)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return None, error_response("No game path configured", 500)
    return game_path, None


_map_id_cache = {}  # game_path -> (mtime, {MAP_CONSTANT -> folder_name})


def _build_map_id_lookup(game_path):
    """Build MAP_CONSTANT -> folder name lookup from map_groups.json.

    E.g. "MAP_SHIRUBE_TOWN" -> "ShirubeTown".
    Cached and invalidated when map_groups.json changes.
    """
    groups_path = os.path.join(game_path, "data", "maps", "map_groups.json")
    try:
        mtime = os.path.getmtime(groups_path)
    except OSError:
        return {}

    cached = _map_id_cache.get(game_path)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        with open(groups_path, "r", encoding="utf-8") as f:
            groups = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    lookup = {}
    for group_maps in groups.values():
        if not isinstance(group_maps, list):
            continue
        for folder_name in group_maps:
            if not isinstance(folder_name, str):
                continue
            map_json_path = os.path.join(
                game_path, "data", "maps", folder_name, "map.json")
            try:
                with open(map_json_path, "r", encoding="utf-8") as f:
                    mdata = json.load(f)
                map_id = mdata.get("id", "")
                if map_id:
                    lookup[map_id] = folder_name
            except (OSError, json.JSONDecodeError):
                continue

    _map_id_cache[game_path] = (mtime, lookup)
    return lookup


def _tileset_const_to_dir(const):
    """Convert gTileset_FooBar to directory name foo_bar.

    Strips the ``gTileset_`` prefix and converts CamelCase to snake_case.
    """
    name = const
    if name.startswith("gTileset_"):
        name = name[len("gTileset_"):]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name).lower()


# ---------------------------------------------------------------------------
# Minimal PNG encoder (stdlib only — no Pillow)
# ---------------------------------------------------------------------------

def _encode_png(width, height, rgba_buf):
    """Encode an RGBA pixel buffer as a PNG file.

    *rgba_buf* is a ``bytes`` or ``bytearray`` of length ``width * height * 4``
    in row-major order (R, G, B, A per pixel).

    Returns the complete PNG file as ``bytes``.
    """
    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)

    # IDAT — filter type 0 (None) per row, then zlib compress
    raw_rows = bytearray()
    stride = width * 4
    for y in range(height):
        raw_rows.append(0)  # filter byte: None
        raw_rows.extend(rgba_buf[y * stride:(y + 1) * stride])

    compressed = zlib.compress(bytes(raw_rows), 6)
    idat = _png_chunk(b"IDAT", compressed)

    # IEND
    iend = _png_chunk(b"IEND", b"")

    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


def _png_chunk(chunk_type, data):
    """Build a single PNG chunk: length + type + data + CRC."""
    body = chunk_type + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# Map rendering engine
# ---------------------------------------------------------------------------

# Cache: game_path -> {map_name -> (png_bytes, mtime_key)}
_render_cache = {}


def _cache_key_mtime(game_path, layout):
    """Build an mtime-based cache key from blockdata and tileset files."""
    paths = []

    bd_path = layout.get("blockdata_filepath", "")
    if bd_path:
        paths.append(os.path.join(game_path, bd_path))

    for ts_key in ("primary_tileset", "secondary_tileset"):
        ts_const = layout.get(ts_key, "")
        if ts_const:
            ts_name = _tileset_const_to_dir(ts_const)
            ts_dir, _ = _resolve_tileset_dir(game_path, ts_name)
            if ts_dir:
                paths.append(os.path.join(ts_dir, "metatiles.bin"))
                paths.append(os.path.join(ts_dir, "tiles.png"))

    mtimes = []
    for p in paths:
        try:
            mtimes.append(os.path.getmtime(p))
        except OSError:
            mtimes.append(0)
    return tuple(mtimes)


def _get_num_metatiles_primary(game_path):
    """Read NUM_METATILES_IN_PRIMARY from fieldmap.h (default 512)."""
    return _read_fieldmap_constant(game_path, "NUM_METATILES_IN_PRIMARY", 512)


def _get_num_tiles_primary(game_path):
    """Read NUM_TILES_IN_PRIMARY from fieldmap.h (default 512).

    This is the tile-level offset: secondary tileset tile indices >= this
    value reference the secondary sheet; indices below reference primary.
    """
    return _read_fieldmap_constant(game_path, "NUM_TILES_IN_PRIMARY", 512)


def _read_fieldmap_constant(game_path, name, default):
    """Read a #define constant from include/fieldmap.h."""
    fmap = os.path.join(game_path, "include", "fieldmap.h")
    if os.path.isfile(fmap):
        try:
            with open(fmap, "r", encoding="utf-8") as f:
                for line in f:
                    m = re.match(
                        rf"#define\s+{re.escape(name)}\s+(\d+)", line)
                    if m:
                        return int(m.group(1))
        except OSError:
            pass
    return default


def _load_tileset_data(game_path, ts_const):
    """Load pixel data, palettes, and metatile refs for a tileset.

    Returns (pixels, sheet_w, sheet_h, palettes, metatiles) or None on error.
    """
    ts_name = _tileset_const_to_dir(ts_const)
    ts_dir, _ = _resolve_tileset_dir(game_path, ts_name)
    if not ts_dir:
        return None

    # Pixels from tiles.png
    try:
        png_path = _safe_path(ts_dir, "tiles.png")
    except ValueError:
        return None
    sheet_w, sheet_h, pixels = _decode_indexed_png(png_path)
    if sheet_w == 0:
        return None

    # Palettes (16 palettes, 16 colors each)
    palettes = []
    pal_dir = os.path.join(ts_dir, "palettes")
    for i in range(16):
        pal_path = os.path.join(pal_dir, f"{i:02d}.pal")
        colors = _parse_pal_file(pal_path)
        if colors is None:
            colors = [[0, 0, 0]] * 16
        palettes.append(colors)

    # Metatile tile refs
    try:
        mt_path = _safe_path(ts_dir, "metatiles.bin")
    except ValueError:
        return None
    if not os.path.isfile(mt_path):
        return None
    try:
        with open(mt_path, "rb") as f:
            mt_data = f.read()
    except OSError:
        return None

    metatiles = _parse_metatile_bin(mt_data)
    return pixels, sheet_w, sheet_h, palettes, metatiles


def _render_tile_to_buf(buf, buf_w, dx, dy, tile_ref,
                        pixels, sheet_w, sheet_h, palettes):
    """Render one 8x8 tile into an RGBA buffer at (dx, dy).

    Mirrors the logic of renderer.js's _renderTileWithPaletteData.
    """
    tile_idx = tile_ref["tile"]
    hflip = tile_ref["hflip"]
    vflip = tile_ref["vflip"]
    pal_idx = tile_ref["palette"]

    tiles_per_row = sheet_w // 8
    total_tiles = tiles_per_row * (sheet_h // 8)
    if tile_idx < 0 or tile_idx >= total_tiles:
        return

    pal = palettes[pal_idx] if pal_idx < len(palettes) else palettes[0]
    if not pal:
        return

    tile_col = tile_idx % tiles_per_row
    tile_row = tile_idx // tiles_per_row
    src_x = tile_col * 8
    src_y = tile_row * 8

    for py in range(8):
        for px in range(8):
            read_x = (7 - px) if hflip else px
            read_y = (7 - py) if vflip else py

            src_idx = (src_y + read_y) * sheet_w + (src_x + read_x)
            if src_idx >= len(pixels):
                continue
            color_idx = pixels[src_idx]

            # Palette index 0 is transparent
            if color_idx == 0:
                continue

            if color_idx < len(pal):
                r, g, b = pal[color_idx]
            else:
                r, g, b = 0, 0, 0

            dst_offset = ((dy + py) * buf_w + (dx + px)) * 4
            buf[dst_offset] = r
            buf[dst_offset + 1] = g
            buf[dst_offset + 2] = b
            buf[dst_offset + 3] = 255


# Metatile tile positions within a 16x16 block.
# 12-tile (3 layer) layout: bottom[0:4], middle[4:8], top[8:12]
# 8-tile (2 layer) layout: bottom[0:4], top[4:8]
# Each group of 4 = 2x2 arrangement: [TL, TR, BL, BR] at offsets (0,0)(8,0)(0,8)(8,8)
_TILE_OFFSETS_2x2 = [(0, 0), (8, 0), (0, 8), (8, 8)]


def _render_metatile_to_buf(buf, buf_w, dx, dy, metatile_tiles,
                            pri_data, sec_data, num_tiles_primary):
    """Render one 16x16 metatile into the RGBA buffer at (dx, dy).

    Each individual tile ref may reference the primary OR secondary tileset:
    - tile index < num_tiles_primary -> use primary tileset sheet/palettes
    - tile index >= num_tiles_primary -> subtract offset, use secondary sheet

    This matches renderer.js's renderMetatileTile() routing logic.
    Renders layers bottom-to-top so upper layers overwrite lower ones.
    """
    tile_count = len(metatile_tiles)

    if tile_count == 12:
        # 3 layers: bottom (0-3), middle (4-7), top (8-11)
        layers = [metatile_tiles[0:4], metatile_tiles[4:8], metatile_tiles[8:12]]
    elif tile_count >= 8:
        # 2 layers: bottom (0-3), top (4-7)
        layers = [metatile_tiles[0:4], metatile_tiles[4:8]]
    else:
        layers = [metatile_tiles]

    for layer in layers:
        for i, tile_ref in enumerate(layer):
            if i >= 4:
                break

            tile_idx = tile_ref["tile"]

            # Route to correct tileset based on tile index
            if num_tiles_primary > 0 and tile_idx < num_tiles_primary:
                # References primary tileset
                ts = pri_data
                adjusted_ref = tile_ref  # index is already correct for primary
            else:
                # References secondary tileset — subtract primary offset
                ts = sec_data
                adjusted_ref = {
                    "tile": tile_idx - num_tiles_primary if num_tiles_primary > 0 else tile_idx,
                    "hflip": tile_ref["hflip"],
                    "vflip": tile_ref["vflip"],
                    "palette": tile_ref["palette"],
                }

            if ts is None:
                continue

            pixels, sheet_w, sheet_h, palettes, _ = ts
            ox, oy = _TILE_OFFSETS_2x2[i]
            _render_tile_to_buf(
                buf, buf_w, dx + ox, dy + oy, adjusted_ref,
                pixels, sheet_w, sheet_h, palettes,
            )


def _render_map(game_path, map_name):
    """Render a full map to a PNG byte string.

    Returns (png_bytes, width_metatiles, height_metatiles) or (None, 0, 0).
    """
    # Load map.json for layout reference
    map_data = load_map_json(game_path, map_name)
    if not map_data:
        return None, 0, 0

    layout_id = map_data.get("layout", "")
    if not layout_id:
        return None, 0, 0

    # Find layout in layouts.json
    layouts_data = load_layouts(game_path)
    if not layouts_data:
        return None, 0, 0

    layout = None
    for lay in layouts_data.get("layouts", []):
        if lay.get("id") == layout_id:
            layout = lay
            break
    if not layout:
        return None, 0, 0

    map_w = layout.get("width", 0)
    map_h = layout.get("height", 0)
    if map_w <= 0 or map_h <= 0:
        return None, 0, 0

    # Read blockdata
    bd_rel = layout.get("blockdata_filepath", "")
    if not bd_rel:
        return None, 0, 0

    bd_path = os.path.join(game_path, bd_rel)
    if not os.path.isfile(bd_path):
        return None, 0, 0
    try:
        with open(bd_path, "rb") as f:
            bd_data = f.read()
    except OSError:
        return None, 0, 0

    expected = map_w * map_h * 2
    if len(bd_data) < expected:
        return None, 0, 0

    # Load primary tileset
    pri_const = layout.get("primary_tileset", "")
    sec_const = layout.get("secondary_tileset", "")

    pri_data = _load_tileset_data(game_path, pri_const) if pri_const else None
    sec_data = _load_tileset_data(game_path, sec_const) if sec_const else None

    if not pri_data and not sec_data:
        return None, 0, 0

    num_metatiles_primary = _get_num_metatiles_primary(game_path)
    num_tiles_primary = _get_num_tiles_primary(game_path)

    # Create RGBA buffer
    img_w = map_w * 16
    img_h = map_h * 16
    buf = bytearray(img_w * img_h * 4)  # initialized to 0 (transparent)

    # Render each metatile
    for cy in range(map_h):
        for cx in range(map_w):
            idx = (cy * map_w + cx) * 2
            val = struct.unpack_from("<H", bd_data, idx)[0]
            metatile_id = val & 0x3FF

            # Determine which tileset owns this metatile definition
            if metatile_id < num_metatiles_primary:
                ts = pri_data
                local_id = metatile_id
            else:
                ts = sec_data
                local_id = metatile_id - num_metatiles_primary

            if ts is None:
                continue

            _, _, _, _, metatiles = ts

            if local_id < 0 or local_id >= len(metatiles):
                continue

            mt_tiles = metatiles[local_id]
            dx = cx * 16
            dy = cy * 16

            # Each tile ref within a metatile can reference EITHER tileset.
            # Tile index < NUM_TILES_IN_PRIMARY -> primary sheet.
            # Tile index >= NUM_TILES_IN_PRIMARY -> secondary sheet (offset).
            # Both tilesets are passed so the renderer can route per-tile.
            _render_metatile_to_buf(
                buf, img_w, dx, dy, mt_tiles,
                pri_data, sec_data, num_tiles_primary,
            )

    png_bytes = _encode_png(img_w, img_h, buf)
    return png_bytes, map_w, map_h


def _render_border(game_path, map_name, depth=3):
    """Render the border tile pattern around a map as a PNG.

    The border is a 2x2 metatile pattern (from border.bin) tiled around
    all four edges of the map, ``depth`` metatiles deep.  The result is
    a PNG showing the full map area plus border padding, with the interior
    (the map area itself) left transparent.

    Returns (png_bytes, map_w, map_h, depth) or (None, 0, 0, 0).
    """
    map_data = load_map_json(game_path, map_name)
    if not map_data:
        return None, 0, 0, 0

    layout_id = map_data.get("layout", "")
    layouts_data = load_layouts(game_path)
    if not layouts_data:
        return None, 0, 0, 0

    layout = None
    for lay in layouts_data.get("layouts", []):
        if lay.get("id") == layout_id:
            layout = lay
            break
    if not layout:
        return None, 0, 0, 0

    map_w = layout.get("width", 0)
    map_h = layout.get("height", 0)
    if map_w <= 0 or map_h <= 0:
        return None, 0, 0, 0

    # Read border.bin — 2x2 metatile IDs (4 u16 values = 8 bytes)
    border_rel = layout.get("border_filepath", "")
    if not border_rel:
        return None, 0, 0, 0

    border_path = os.path.join(game_path, border_rel)
    if not os.path.isfile(border_path):
        return None, 0, 0, 0

    try:
        with open(border_path, "rb") as f:
            border_data = f.read()
    except OSError:
        return None, 0, 0, 0

    if len(border_data) < 8:
        return None, 0, 0, 0

    border_ids = [struct.unpack_from("<H", border_data, i * 2)[0] & 0x3FF
                  for i in range(4)]

    # All zeros means no border defined
    if all(b == 0 for b in border_ids):
        return None, 0, 0, 0

    # Load tilesets
    pri_const = layout.get("primary_tileset", "")
    sec_const = layout.get("secondary_tileset", "")
    pri_data = _load_tileset_data(game_path, pri_const) if pri_const else None
    sec_data = _load_tileset_data(game_path, sec_const) if sec_const else None
    if not pri_data and not sec_data:
        return None, 0, 0, 0

    num_metatiles_primary = _get_num_metatiles_primary(game_path)
    num_tiles_primary = _get_num_tiles_primary(game_path)

    # Output size: map + border padding on all sides
    total_w = map_w + depth * 2
    total_h = map_h + depth * 2
    img_w = total_w * 16
    img_h = total_h * 16
    buf = bytearray(img_w * img_h * 4)

    # Tile the 2x2 border pattern across the entire area.
    # The border is a 2x2 grid that repeats.  Porymap phases the pattern
    # relative to the map origin so the 2x2 block aligns at even map
    # coordinates.  We convert output tile coords (tx, ty) to map-relative
    # coords (map_x, map_y) and use Python's always-positive modulo.
    for ty in range(total_h):
        for tx in range(total_w):
            map_x = tx - depth
            map_y = ty - depth
            # Skip the interior (that's where the map goes — left transparent)
            if 0 <= map_x < map_w and 0 <= map_y < map_h:
                continue

            metatile_id = border_ids[(map_y % 2) * 2 + (map_x % 2)]

            if metatile_id < num_metatiles_primary:
                ts = pri_data
                local_id = metatile_id
            else:
                ts = sec_data
                local_id = metatile_id - num_metatiles_primary

            if ts is None:
                continue

            _, _, _, _, metatiles = ts
            if local_id < 0 or local_id >= len(metatiles):
                continue

            mt_tiles = metatiles[local_id]
            _render_metatile_to_buf(
                buf, img_w, tx * 16, ty * 16, mt_tiles,
                pri_data, sec_data, num_tiles_primary,
            )

    png_bytes = _encode_png(img_w, img_h, buf)
    return png_bytes, map_w, map_h, depth


def _render_strip(game_path, map_name, strip, depth=3):
    """Render a strip of a map's edge as a PNG.

    ``strip`` is one of ``"north"``, ``"south"``, ``"east"``, ``"west"``.
    ``depth`` is how many metatile rows/columns to render.

    Returns (png_bytes, strip_w, strip_h) or (None, 0, 0).
    """
    map_data = load_map_json(game_path, map_name)
    if not map_data:
        return None, 0, 0

    layout_id = map_data.get("layout", "")
    layouts_data = load_layouts(game_path)
    if not layouts_data:
        return None, 0, 0

    layout = None
    for lay in layouts_data.get("layouts", []):
        if lay.get("id") == layout_id:
            layout = lay
            break
    if not layout:
        return None, 0, 0

    map_w = layout.get("width", 0)
    map_h = layout.get("height", 0)
    if map_w <= 0 or map_h <= 0:
        return None, 0, 0

    # Determine which region of the blockdata to render
    if strip == "north":
        col0, row0, col1, row1 = 0, 0, map_w, min(depth, map_h)
    elif strip == "south":
        col0, row0, col1, row1 = 0, max(0, map_h - depth), map_w, map_h
    elif strip == "west":
        col0, row0, col1, row1 = 0, 0, min(depth, map_w), map_h
    elif strip == "east":
        col0, row0, col1, row1 = max(0, map_w - depth), 0, map_w, map_h
    else:
        return None, 0, 0

    region_w = col1 - col0
    region_h = row1 - row0
    if region_w <= 0 or region_h <= 0:
        return None, 0, 0

    # Read blockdata
    bd_rel = layout.get("blockdata_filepath", "")
    if not bd_rel:
        return None, 0, 0
    bd_path = os.path.join(game_path, bd_rel)
    if not os.path.isfile(bd_path):
        return None, 0, 0
    try:
        with open(bd_path, "rb") as f:
            bd_data = f.read()
    except OSError:
        return None, 0, 0

    if len(bd_data) < map_w * map_h * 2:
        return None, 0, 0

    # Load tilesets
    pri_const = layout.get("primary_tileset", "")
    sec_const = layout.get("secondary_tileset", "")
    pri_data = _load_tileset_data(game_path, pri_const) if pri_const else None
    sec_data = _load_tileset_data(game_path, sec_const) if sec_const else None
    if not pri_data and not sec_data:
        return None, 0, 0

    num_metatiles_primary = _get_num_metatiles_primary(game_path)
    num_tiles_primary = _get_num_tiles_primary(game_path)

    img_w = region_w * 16
    img_h = region_h * 16
    buf = bytearray(img_w * img_h * 4)

    for cy in range(row0, row1):
        for cx in range(col0, col1):
            idx = (cy * map_w + cx) * 2
            val = struct.unpack_from("<H", bd_data, idx)[0]
            metatile_id = val & 0x3FF

            if metatile_id < num_metatiles_primary:
                ts = pri_data
                local_id = metatile_id
            else:
                ts = sec_data
                local_id = metatile_id - num_metatiles_primary

            if ts is None:
                continue

            _, _, _, _, metatiles = ts
            if local_id < 0 or local_id >= len(metatiles):
                continue

            mt_tiles = metatiles[local_id]
            dx = (cx - col0) * 16
            dy = (cy - row0) * 16
            _render_metatile_to_buf(
                buf, img_w, dx, dy, mt_tiles,
                pri_data, sec_data, num_tiles_primary,
            )

    png_bytes = _encode_png(img_w, img_h, buf)
    return png_bytes, region_w, region_h


# Cache for border renders: game_path -> {map_name -> (png_bytes, mtime_key)}
_border_cache = {}
# Cache for strip renders: game_path -> {(map_name, strip, depth) -> (png_bytes, mtime_key)}
_strip_cache = {}


# ---------------------------------------------------------------------------
# GET /api/map/<name>/border — Border tile pattern PNG
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/border")
def handle_map_border(handler, match, query_params):
    """Serve the border tile pattern around a map as a PNG.

    The border is the 2x2 metatile pattern from border.bin, tiled around
    all edges with the map interior left transparent.  The client overlays
    this behind the map image.

    Query params:
      - depth: number of border metatiles to render (default 3)
    """
    game_path, err = _get_game_path(handler)
    if err:
        handler.send_error(500, "No game path")
        return None

    map_name = match.group("map_name")
    depth = int(query_params.get("depth", ["3"])[0])
    depth = max(1, min(depth, 8))

    # Cache check
    cache_key = (map_name, depth)
    layouts_data = load_layouts(game_path)
    map_data = load_map_json(game_path, map_name)
    mtime_key = None
    if map_data and layouts_data:
        layout_id = map_data.get("layout", "")
        for lay in layouts_data.get("layouts", []):
            if lay.get("id") == layout_id:
                mtime_key = _cache_key_mtime(game_path, lay)
                break
        if mtime_key:
            cached = _border_cache.get(game_path, {}).get(cache_key)
            if cached and cached[1] == mtime_key:
                png_bytes = cached[0]
                handler.send_response(200)
                handler.send_header("Content-Type", "image/png")
                handler.send_header("Content-Length", str(len(png_bytes)))
                handler.send_header("Cache-Control", "public, max-age=60")
                handler.end_headers()
                handler.wfile.write(png_bytes)
                return None

    png_bytes, map_w, map_h, actual_depth = _render_border(
        game_path, map_name, depth)
    if png_bytes is None:
        handler.send_error(404, "Cannot render border")
        return None

    # Cache
    if mtime_key:
        if game_path not in _border_cache:
            _border_cache[game_path] = {}
        _border_cache[game_path][cache_key] = (png_bytes, mtime_key)

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(png_bytes)))
    handler.send_header("X-Map-Width", str(map_w))
    handler.send_header("X-Map-Height", str(map_h))
    handler.send_header("X-Border-Depth", str(actual_depth))
    handler.send_header("Cache-Control", "public, max-age=60")
    handler.end_headers()
    handler.wfile.write(png_bytes)
    return None


# ---------------------------------------------------------------------------
# GET /api/map/<name>/strip — Partial edge strip PNG
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/strip")
def handle_map_strip(handler, match, query_params):
    """Serve a strip of a map's edge as a PNG.

    Used for rendering adjacent map borders in the IDE.

    Query params:
      - edge: "north", "south", "east", "west" (required)
      - depth: number of metatile rows/columns (default 3)
    """
    game_path, err = _get_game_path(handler)
    if err:
        handler.send_error(500, "No game path")
        return None

    map_name = match.group("map_name")
    edge = query_params.get("edge", [""])[0].lower()
    if edge not in ("north", "south", "east", "west"):
        handler.send_error(400, "Missing or invalid 'edge' param")
        return None

    depth = int(query_params.get("depth", ["3"])[0])
    depth = max(1, min(depth, 8))

    # Cache check
    cache_key = (map_name, edge, depth)
    layouts_data = load_layouts(game_path)
    map_data = load_map_json(game_path, map_name)
    mtime_key = None
    if map_data and layouts_data:
        layout_id = map_data.get("layout", "")
        for lay in layouts_data.get("layouts", []):
            if lay.get("id") == layout_id:
                mtime_key = _cache_key_mtime(game_path, lay)
                break
        if mtime_key:
            cached = _strip_cache.get(game_path, {}).get(cache_key)
            if cached and cached[1] == mtime_key:
                png_bytes = cached[0]
                handler.send_response(200)
                handler.send_header("Content-Type", "image/png")
                handler.send_header("Content-Length", str(len(png_bytes)))
                handler.send_header("Cache-Control", "public, max-age=60")
                handler.end_headers()
                handler.wfile.write(png_bytes)
                return None

    png_bytes, strip_w, strip_h = _render_strip(
        game_path, map_name, edge, depth)
    if png_bytes is None:
        handler.send_error(404, "Cannot render strip")
        return None

    # Cache
    if mtime_key:
        if game_path not in _strip_cache:
            _strip_cache[game_path] = {}
        _strip_cache[game_path][cache_key] = (png_bytes, mtime_key)

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(png_bytes)))
    handler.send_header("X-Strip-Width", str(strip_w))
    handler.send_header("X-Strip-Height", str(strip_h))
    handler.send_header("Cache-Control", "public, max-age=60")
    handler.end_headers()
    handler.wfile.write(png_bytes)
    return None


# ---------------------------------------------------------------------------
# GET /api/map/<name>/render — Server-composed map PNG
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/render")
def handle_map_render(handler, match, query_params):
    """Serve a full map as a pre-rendered PNG image.

    The image composites blockdata + metatile tile refs + palette colors
    into a complete map at native 16px-per-metatile resolution.
    Results are cached and invalidated by file mtime changes.
    """
    game_path, err = _get_game_path(handler)
    if err:
        handler.send_error(500, "No game path")
        return None

    map_name = match.group("map_name")

    # Check cache
    layouts_data = load_layouts(game_path)
    map_data = load_map_json(game_path, map_name)
    if map_data and layouts_data:
        layout_id = map_data.get("layout", "")
        layout = None
        for lay in layouts_data.get("layouts", []):
            if lay.get("id") == layout_id:
                layout = lay
                break
        if layout:
            mtime_key = _cache_key_mtime(game_path, layout)
            cache = _render_cache.get(game_path, {})
            cached = cache.get(map_name)
            if cached and cached[1] == mtime_key:
                png_bytes = cached[0]
                handler.send_response(200)
                handler.send_header("Content-Type", "image/png")
                handler.send_header("Content-Length", str(len(png_bytes)))
                handler.send_header(
                    "Cache-Control", "public, max-age=60")
                handler.end_headers()
                handler.wfile.write(png_bytes)
                return None

    # Render
    png_bytes, map_w, map_h = _render_map(game_path, map_name)
    if png_bytes is None:
        handler.send_error(404, "Cannot render map")
        return None

    # Store in cache
    if map_data and layouts_data and layout:
        mtime_key = _cache_key_mtime(game_path, layout)
        if game_path not in _render_cache:
            _render_cache[game_path] = {}
        _render_cache[game_path][map_name] = (png_bytes, mtime_key)

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(png_bytes)))
    handler.send_header("X-Map-Width", str(map_w))
    handler.send_header("X-Map-Height", str(map_h))
    handler.send_header("Cache-Control", "public, max-age=60")
    handler.end_headers()
    handler.wfile.write(png_bytes)
    return None


# ---------------------------------------------------------------------------
# GET /api/map/<name>/events — Consolidated event data
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/events")
def handle_map_events(handler, match, query_params):
    """Return all events for a map in a single response.

    Consolidates object_events (NPCs), warp_events, coord_events (triggers),
    and bg_events (signs) with resolved sprite URLs and metadata.
    """
    game_path, err = _get_game_path(handler)
    if err:
        return err

    map_name = match.group("map_name")
    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    # Build sprite index once (lazy import to avoid circular dependency)
    from torch.web.api import build_sprite_index
    sprite_index = build_sprite_index(game_path)

    # Build MAP_CONSTANT -> folder name lookup for warp dest resolution
    map_id_to_name = _build_map_id_lookup(game_path)

    # Object events (NPCs)
    object_events = []
    for i, obj in enumerate(data.get("object_events") or []):
        if not isinstance(obj, dict):
            continue
        local_id = obj.get("local_id")
        if isinstance(local_id, int):
            oid = local_id
        elif isinstance(local_id, str) and local_id.isdigit():
            oid = int(local_id)
        else:
            oid = i + 1

        gfx = obj.get("graphics_id", "")
        script = obj.get("script", "")
        if script in ("0x0", "0", ""):
            script = ""

        trainer_type = obj.get("trainer_type", "TRAINER_TYPE_NONE")

        sprite_entry = sprite_index.get(gfx, {})

        # sprite_sheet_url: the raw spritesheet PNG (e.g. 144x32 for 9 frames)
        # frame_width/frame_height: single frame dimensions (e.g. 16x32)
        sprite_sheet_url = ""
        if sprite_entry.get("png"):
            png_rel = sprite_entry["png"]
            # Convert from graphics/object_events/pics/... to the npc_sprites endpoint
            prefix = "graphics/object_events/pics/"
            if png_rel.startswith(prefix):
                sprite_sheet_url = "/api/npc_sprites/" + png_rel[len(prefix):]

        object_events.append({
            "object_id": oid,
            "x": obj.get("x", 0),
            "y": obj.get("y", 0),
            "elevation": obj.get("elevation", 0),
            "graphics_id": gfx,
            "movement_type": obj.get("movement_type", ""),
            "script": script,
            "trainer_type": trainer_type,
            "is_trainer": trainer_type != "TRAINER_TYPE_NONE",
            "flag": obj.get("flag", ""),
            "sprite_sheet_url": sprite_sheet_url,
            "frame_width": sprite_entry.get("width", 16),
            "frame_height": sprite_entry.get("height", 32),
        })

    # Warp events
    warp_events = []
    for i, warp in enumerate(data.get("warp_events") or []):
        if not isinstance(warp, dict):
            continue
        dest_const = warp.get("dest_map", "")
        dest_name = map_id_to_name.get(dest_const, "")
        warp_events.append({
            "id": i,
            "x": warp.get("x", 0),
            "y": warp.get("y", 0),
            "elevation": warp.get("elevation", 0),
            "dest_map": dest_name or dest_const,
            "dest_warp_id": warp.get("dest_warp_id", 0),
        })

    # Coord events (triggers)
    coord_events = []
    for i, coord in enumerate(data.get("coord_events") or []):
        if not isinstance(coord, dict):
            continue
        coord_events.append({
            "id": i,
            "type": coord.get("type", "trigger"),
            "x": coord.get("x", 0),
            "y": coord.get("y", 0),
            "elevation": coord.get("elevation", 0),
            "script": coord.get("script", ""),
            "var": coord.get("var", ""),
            "var_value": coord.get("var_value", ""),
            "weather": coord.get("weather", ""),
        })

    # BG events (signs, hidden items)
    bg_events = []
    for i, bg in enumerate(data.get("bg_events") or []):
        if not isinstance(bg, dict):
            continue
        bg_events.append({
            "id": i,
            "type": bg.get("type", ""),
            "x": bg.get("x", 0),
            "y": bg.get("y", 0),
            "elevation": bg.get("elevation", 0),
            "script": bg.get("script", ""),
            "player_facing_dir": bg.get("player_facing_dir", ""),
            "item": bg.get("item", ""),
            "flag": bg.get("flag", ""),
            "quantity": bg.get("quantity", 0),
        })

    # Layout info for dimensions
    layout_id = data.get("layout", "")
    map_w, map_h = 0, 0
    layouts_data = load_layouts(game_path)
    if layouts_data:
        for lay in layouts_data.get("layouts", []):
            if lay.get("id") == layout_id:
                map_w = lay.get("width", 0)
                map_h = lay.get("height", 0)
                break

    return ok_response({
        "map_name": map_name,
        "width": map_w,
        "height": map_h,
        "object_events": object_events,
        "warp_events": warp_events,
        "coord_events": coord_events,
        "bg_events": bg_events,
        "counts": {
            "npcs": len(object_events),
            "warps": len(warp_events),
            "triggers": len(coord_events),
            "signs": len(bg_events),
        },
    })


# ---------------------------------------------------------------------------
# GET /api/map/<name>/blockdata — Raw blockdata binary
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/blockdata")
def handle_map_blockdata(handler, match, query_params):
    """Serve raw map blockdata as application/octet-stream.

    Width and height sent as X-Map-Width / X-Map-Height headers.
    Each entry is a u16 LE: bits 0-9 = metatile ID, 10-11 = collision,
    12-15 = elevation.
    """
    game_path, err = _get_game_path(handler)
    if err:
        handler.send_error(500, "No game path")
        return None

    map_name = match.group("map_name")
    map_data = load_map_json(game_path, map_name)
    if not map_data:
        handler.send_error(404, "Map not found")
        return None

    layout_id = map_data.get("layout", "")
    layouts_data = load_layouts(game_path)
    if not layouts_data:
        handler.send_error(500, "Cannot load layouts")
        return None

    layout = None
    for lay in layouts_data.get("layouts", []):
        if lay.get("id") == layout_id:
            layout = lay
            break
    if not layout:
        handler.send_error(404, "Layout not found")
        return None

    bd_rel = layout.get("blockdata_filepath", "")
    if not bd_rel:
        handler.send_error(404, "No blockdata path")
        return None

    bd_path = os.path.join(game_path, bd_rel)
    if not os.path.isfile(bd_path):
        handler.send_error(404, "Blockdata file not found")
        return None

    try:
        with open(bd_path, "rb") as f:
            bd_data = f.read()
    except OSError:
        handler.send_error(500, "Cannot read blockdata")
        return None

    handler.send_response(200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(len(bd_data)))
    handler.send_header("X-Map-Width", str(layout.get("width", 0)))
    handler.send_header("X-Map-Height", str(layout.get("height", 0)))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(bd_data)
    return None


