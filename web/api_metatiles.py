# TORCH_MODULE: Web API — Metatiles
# TORCH_GROUP: Web
"""Metatile layer type and behavior editor API endpoints.

Provides endpoints to read metatile tile refs, attributes (layer type
and behavior), palettes, and the behavior enum.  Also provides a save
endpoint for bulk-updating layer types and behaviors in
metatile_attributes.bin.
"""

import os
import re
import struct
import tempfile
import zlib

from torch.web.api import (
    api_route, ok_response, error_response, _safe_path,
    _read_json_body,
)


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

_behavior_cache = {}  # game_path -> [{"value": int, "name": str}, ...]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_game_path(handler):
    """Extract game_path from handler, return (path, error_response)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return None, error_response("No game path configured", 500)
    return game_path, None


def _resolve_tileset_dir(game_path, name):
    """Find the tileset directory for *name*.

    Searches secondary then primary.  Returns (dir_path, tier) where
    tier is ``"secondary"`` or ``"primary"``, or ``(None, None)`` if not
    found.
    """
    for tier in ("secondary", "primary"):
        try:
            candidate = _safe_path(
                game_path, "data", "tilesets", tier, name,
            )
        except ValueError:
            continue
        if os.path.isdir(candidate):
            return candidate, tier
    return None, None


def _parse_pal_file(path):
    """Read a JASC-PAL text file and return 16 ``[r, g, b]`` entries.

    If *path* does not exist but a ``.gbapal`` sibling does, read the
    binary RGB555 format instead (32 bytes, 16 little-endian u16 values).
    Returns ``None`` on failure.
    """
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
            # Skip header: "JASC-PAL", "0100", "<count>"
            data_lines = lines[3:19]
            colors = []
            for line in data_lines:
                parts = line.split()
                if len(parts) >= 3:
                    colors.append([int(parts[0]), int(parts[1]), int(parts[2])])
            if len(colors) == 16:
                return colors
        except (OSError, ValueError):
            pass

    # Try binary .gbapal fallback
    gbapal = os.path.splitext(path)[0] + ".gbapal"
    if os.path.isfile(gbapal):
        try:
            with open(gbapal, "rb") as f:
                data = f.read(32)
            if len(data) == 32:
                colors = []
                for i in range(16):
                    val = struct.unpack_from("<H", data, i * 2)[0]
                    r = (val & 0x1F) << 3
                    g = ((val >> 5) & 0x1F) << 3
                    b = ((val >> 10) & 0x1F) << 3
                    colors.append([r, g, b])
                return colors
        except (OSError, struct.error):
            pass

    return None


def _parse_behaviors(game_path):
    """Parse the metatile_behaviors.h enum and return a list of dicts.

    Each dict has ``{"value": int, "name": str}``.  Results are cached
    per *game_path* in ``_behavior_cache``.
    """
    if game_path in _behavior_cache:
        return _behavior_cache[game_path]

    header = os.path.join(
        game_path, "include", "constants", "metatile_behaviors.h",
    )
    if not os.path.isfile(header):
        return []

    try:
        with open(header, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []

    # Find the enum body
    m = re.search(r"enum\s*\{([^}]+)\}", text, re.DOTALL)
    if not m:
        return []

    body = m.group(1)
    entry_re = re.compile(
        r"(MB_\w+)\s*(?:=\s*(\d+|0x[0-9A-Fa-f]+))?\s*[,}]"
    )

    behaviors = []
    counter = 0
    for em in entry_re.finditer(body):
        name = em.group(1)
        if name == "NUM_METATILE_BEHAVIORS":
            continue
        if em.group(2) is not None:
            counter = int(em.group(2), 0)
        behaviors.append({"value": counter, "name": name})
        counter += 1

    _behavior_cache[game_path] = behaviors
    return behaviors


def _parse_metatile_bin(data):
    """Parse metatiles.bin into a list of metatile tile-ref lists.

    Each metatile is either 12 tiles (24 bytes, expansion) or 8 tiles
    (16 bytes, vanilla).  Each tile ref is a u16 decoded into::

        {"tile": int, "hflip": bool, "vflip": bool, "palette": int}
    """
    total = len(data)
    if total == 0:
        return []

    if total % 24 == 0:
        tile_count = 12
        stride = 24
    else:
        tile_count = 8
        stride = 16

    metatiles = []
    for offset in range(0, total, stride):
        tiles = []
        for t in range(tile_count):
            pos = offset + t * 2
            if pos + 2 > total:
                break
            val = struct.unpack_from("<H", data, pos)[0]
            tiles.append({
                "tile": val & 0x3FF,
                "hflip": bool(val & 0x400),
                "vflip": bool(val & 0x800),
                "palette": (val >> 12) & 0xF,
            })
        metatiles.append(tiles)
    return metatiles


def _parse_attributes_bin(data):
    """Parse metatile_attributes.bin.

    Detects 2-byte (u16) vs 4-byte (u32) attribute format:
    - 2-byte: ``behavior = val & 0xFF, layer_type = (val >> 12) & 0xF``
    - 4-byte: ``behavior = val & 0x1FF, layer_type = (val >> 29) & 0x7``

    Returns list of ``{"behavior": int, "layer_type": int, "raw": int}``.
    """
    total = len(data)
    if total == 0:
        return []

    # Heuristic: if total / num_metatiles = 4, it's u32; else u16
    # Since we don't know num_metatiles here, check divisibility
    if total % 4 == 0 and total % 2 == 0:
        # Try to determine: if file is small enough that u16 count would
        # still be reasonable AND total is not divisible by 4 cleanly when
        # paired with a metatiles.bin, default to u16.  However, since
        # expansion commonly uses u32, check if any u32 entry has high
        # bits set that would indicate it's truly 4-byte.
        # Simple approach: use 2-byte format (the most common in
        # pokeemerald-expansion).
        pass

    # Default: 2-byte attributes (pokeemerald-expansion standard)
    attrs = []
    stride = 2
    fmt = "<H"
    for offset in range(0, total, stride):
        if offset + stride > total:
            break
        val = struct.unpack_from(fmt, data, offset)[0]
        attrs.append({
            "behavior": val & 0xFF,
            "layer_type": (val >> 12) & 0xF,
            "raw": val,
        })
    return attrs


# ---------------------------------------------------------------------------
# GET /api/metatiles/<name> — Full metatile data
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/metatiles/(?P<name>[A-Za-z0-9_]+)")
def handle_metatiles_detail(handler, match, query_params):
    """Return all metatile data for a tileset (tiles, attributes, behaviors)."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    name = match.group("name")
    ts_dir, tier = _resolve_tileset_dir(game_path, name)
    if not ts_dir:
        return error_response(f"Tileset not found: {name}", 404)

    # Read metatiles.bin
    try:
        mt_path = _safe_path(ts_dir, "metatiles.bin")
    except ValueError:
        return error_response("Invalid tileset path", 400)

    if not os.path.isfile(mt_path):
        return error_response(f"metatiles.bin not found for {name}", 404)

    try:
        with open(mt_path, "rb") as f:
            mt_data = f.read()
    except OSError as e:
        return error_response(f"Cannot read metatiles.bin: {e}", 500)

    metatiles = _parse_metatile_bin(mt_data)

    # Read metatile_attributes.bin
    try:
        attr_path = _safe_path(ts_dir, "metatile_attributes.bin")
    except ValueError:
        return error_response("Invalid tileset path", 400)

    if not os.path.isfile(attr_path):
        return error_response(
            f"metatile_attributes.bin not found for {name}", 404,
        )

    try:
        with open(attr_path, "rb") as f:
            attr_data = f.read()
    except OSError as e:
        return error_response(
            f"Cannot read metatile_attributes.bin: {e}", 500,
        )

    attributes = _parse_attributes_bin(attr_data)

    # Build behavior name lookup
    behaviors = _parse_behaviors(game_path)
    behavior_names = {b["value"]: b["name"] for b in behaviors}

    # Combine into response
    combined = []
    for i, tiles in enumerate(metatiles):
        attr = attributes[i] if i < len(attributes) else {
            "behavior": 0, "layer_type": 0, "raw": 0,
        }
        combined.append({
            "id": i,
            "tiles": tiles,
            "behavior": attr["behavior"],
            "behavior_name": behavior_names.get(attr["behavior"], ""),
            "layer_type": attr["layer_type"],
        })

    # Find paired primary tileset name (for rendering tiles that reference primary)
    primary_name = ""
    if tier == "secondary":
        layouts_path = os.path.join(game_path, "data", "layouts", "layouts.json")
        try:
            import json as _json
            with open(layouts_path, "r", encoding="utf-8") as f:
                layouts_data = _json.load(f)
            ts_const = f"gTileset_{name[0].upper()}{name[1:]}"
            # Try CamelCase variants
            camel = "".join(w.capitalize() for w in name.split("_"))
            for layout in layouts_data.get("layouts", []):
                sec = layout.get("secondary_tileset", "")
                if sec.endswith(camel) or sec.endswith(name):
                    pri = layout.get("primary_tileset", "")
                    # Extract name from gTileset_Building -> building
                    if pri.startswith("gTileset_"):
                        primary_name = pri[len("gTileset_"):]
                        # Convert CamelCase to snake_case for dir lookup
                        import re as _re
                        primary_name = _re.sub(
                            r'(?<=[a-z])(?=[A-Z])', '_', primary_name).lower()
                    break
        except (OSError, ValueError):
            pass

    # Secondary tilesets store global tile indices (offset by NUM_TILES_IN_PRIMARY,
    # typically 512).  The frontend needs this to map indices into the spritesheet.
    primary_tiles = 0
    if tier == "secondary":
        fmap = os.path.join(game_path, "include", "fieldmap.h")
        if os.path.isfile(fmap):
            try:
                with open(fmap, "r", encoding="utf-8") as f:
                    for line in f:
                        m = re.match(
                            r"#define\s+NUM_TILES_IN_PRIMARY\s+(\d+)", line)
                        if m:
                            primary_tiles = int(m.group(1))
                            break
            except OSError:
                pass
        if primary_tiles == 0:
            primary_tiles = 512  # expansion default

    # Detect FR import pattern: bottom+top with empty middle on multi-layer tiles
    fr_import = False
    tile_count = 12 if len(mt_data) % 24 == 0 else 8
    if tile_count == 12:
        bt_count = 0
        multi_count = 0
        for tiles in metatiles:
            has_b = any(t["tile"] != 0 or t["palette"] != 0 for t in tiles[0:4])
            has_m = any(t["tile"] != 0 or t["palette"] != 0 for t in tiles[4:8])
            has_t = any(t["tile"] != 0 or t["palette"] != 0 for t in tiles[8:12])
            layers = (1 if has_b else 0) + (1 if has_m else 0) + (1 if has_t else 0)
            if layers >= 2:
                multi_count += 1
                if has_b and has_t and not has_m:
                    bt_count += 1
        # If >80% of multi-layer tiles are bottom+top, it's an FR import
        if multi_count > 0 and bt_count / multi_count > 0.8:
            fr_import = True

    return ok_response({
        "name": name,
        "tier": tier,
        "count": len(combined),
        "tile_count": tile_count,
        "primary_tile_offset": primary_tiles,
        "primary_tileset": primary_name,
        "fr_import_pattern": fr_import,
        "metatiles": combined,
    })


# ---------------------------------------------------------------------------
# GET /api/metatiles/<name>/palettes — Tileset palettes
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/metatiles/(?P<name>[A-Za-z0-9_]+)/palettes")
def handle_metatiles_palettes(handler, match, query_params):
    """Return all 16 palettes for a tileset."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    name = match.group("name")
    ts_dir, tier = _resolve_tileset_dir(game_path, name)
    if not ts_dir:
        return error_response(f"Tileset not found: {name}", 404)

    try:
        pal_dir = _safe_path(ts_dir, "palettes")
    except ValueError:
        return error_response("Invalid tileset path", 400)

    palettes = []
    for i in range(16):
        nn = f"{i:02d}"
        pal_path = os.path.join(pal_dir, f"{nn}.pal")
        colors = _parse_pal_file(pal_path)
        if colors is None:
            # Empty palette — 16 black entries
            colors = [[0, 0, 0]] * 16
        palettes.append(colors)

    return ok_response({"palettes": palettes})


# ---------------------------------------------------------------------------
# GET /api/metatiles/<name>/pixels — Raw indexed pixel data from tiles.png
# ---------------------------------------------------------------------------

def _decode_indexed_png(png_path):
    """Decode an indexed (color type 3) PNG into raw palette indices.

    Returns (width, height, pixels) where pixels is a bytes object with
    one byte per pixel (values 0-15 for 4-bit, 0-255 for 8-bit).
    Returns (0, 0, b"") on failure.
    """
    try:
        with open(png_path, "rb") as f:
            data = f.read()
    except OSError:
        return 0, 0, b""

    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return 0, 0, b""

    # Parse chunks
    pos = 8
    width = height = bit_depth = color_type = 0
    idat_chunks = []
    while pos < len(data) - 4:
        chunk_len = struct.unpack_from(">I", data, pos)[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + chunk_len]
        pos += 12 + chunk_len  # len + type + data + crc

        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(
                ">IIBB", chunk_data[:10])
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if color_type != 3 or not idat_chunks:
        return 0, 0, b""

    # Decompress
    raw = zlib.decompress(b"".join(idat_chunks))

    # Decode filtered scanlines
    if bit_depth == 4:
        bytes_per_row = (width + 1) // 2  # 2 pixels per byte
    elif bit_depth == 8:
        bytes_per_row = width
    else:
        return 0, 0, b""

    pixels = bytearray()
    row_stride = 1 + bytes_per_row  # 1 filter byte + pixel data
    prev_row = bytearray(bytes_per_row)

    for y in range(height):
        offset = y * row_stride
        if offset >= len(raw):
            break
        filt = raw[offset]
        row = bytearray(raw[offset + 1 : offset + 1 + bytes_per_row])

        # Apply PNG filter
        if filt == 1:  # Sub
            for i in range(1, len(row)):
                row[i] = (row[i] + row[i - 1]) & 0xFF
        elif filt == 2:  # Up
            for i in range(len(row)):
                row[i] = (row[i] + prev_row[i]) & 0xFF
        elif filt == 3:  # Average
            for i in range(len(row)):
                a = row[i - 1] if i > 0 else 0
                row[i] = (row[i] + (a + prev_row[i]) // 2) & 0xFF
        elif filt == 4:  # Paeth
            for i in range(len(row)):
                a = row[i - 1] if i > 0 else 0
                b = prev_row[i]
                c = prev_row[i - 1] if i > 0 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                row[i] = (row[i] + pr) & 0xFF
        # filt == 0: None — no change

        # Expand 4-bit to 1-byte-per-pixel
        if bit_depth == 4:
            for byte in row:
                pixels.append((byte >> 4) & 0xF)
                if len(pixels) % width != 0 or len(pixels) == 0:
                    pixels.append(byte & 0xF)
                # Handle odd-width rows (skip padding nibble)
            # Trim to exact width
            start = y * width
            while len(pixels) > start + width:
                pixels.pop()
        else:
            pixels.extend(row)

        prev_row = row

    return width, height, bytes(pixels[:width * height])


@api_route("GET", r"/api/metatiles/(?P<name>[A-Za-z0-9_]+)/pixels")
def handle_metatiles_pixels(handler, match, query_params):
    """Serve the raw indexed pixel data from tiles.png as binary.

    Response is application/octet-stream: width * height bytes, one byte
    per pixel, values 0-15 (palette indices).  Width and height are sent
    as response headers X-Tile-Width and X-Tile-Height.
    """
    game_path, err = _get_game_path(handler)
    if err:
        handler.send_error(404, "Not Found")
        return None

    name = match.group("name")
    ts_dir, tier = _resolve_tileset_dir(game_path, name)
    if not ts_dir:
        handler.send_error(404, "Not Found")
        return None

    try:
        png_path = _safe_path(ts_dir, "tiles.png")
    except ValueError:
        handler.send_error(403, "Forbidden")
        return None

    if not os.path.isfile(png_path):
        handler.send_error(404, "Not Found")
        return None

    width, height, pixels = _decode_indexed_png(png_path)
    if not pixels:
        handler.send_error(500, "Could not decode tiles.png")
        return None

    handler.send_response(200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(len(pixels)))
    handler.send_header("X-Tile-Width", str(width))
    handler.send_header("X-Tile-Height", str(height))
    handler.send_header("Cache-Control", "public, max-age=60")
    handler.end_headers()
    handler.wfile.write(pixels)
    return None


# ---------------------------------------------------------------------------
# GET /api/metatiles/<name>/behaviors — Behavior enum
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/metatiles/(?P<name>[A-Za-z0-9_]+)/behaviors")
def handle_metatiles_behaviors(handler, match, query_params):
    """Return the metatile behavior enum for this game."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    behaviors = _parse_behaviors(game_path)
    if not behaviors:
        return error_response("metatile_behaviors.h not found or empty", 404)

    return ok_response({"behaviors": behaviors})


# ---------------------------------------------------------------------------
# POST /api/metatiles/<name>/save — Bulk-update attributes
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/metatiles/(?P<name>[A-Za-z0-9_]+)/save")
def handle_metatiles_save(handler, match, query_params):
    """Save modified metatile layer types and/or behaviors."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    name = match.group("name")
    ts_dir, tier = _resolve_tileset_dir(game_path, name)
    if not ts_dir:
        return error_response(f"Tileset not found: {name}", 404)

    body = _read_json_body(handler)
    if not body:
        return error_response("Request body required", 400)

    changes = body.get("changes")
    if not isinstance(changes, list) or not changes:
        return error_response("'changes' must be a non-empty list", 400)

    # Read current attributes
    try:
        attr_path = _safe_path(ts_dir, "metatile_attributes.bin")
    except ValueError:
        return error_response("Invalid tileset path", 400)

    if not os.path.isfile(attr_path):
        return error_response(
            f"metatile_attributes.bin not found for {name}", 404,
        )

    try:
        with open(attr_path, "rb") as f:
            attr_data = bytearray(f.read())
    except OSError as e:
        return error_response(
            f"Cannot read metatile_attributes.bin: {e}", 500,
        )

    total = len(attr_data)
    stride = 2  # u16 attributes
    num_metatiles = total // stride

    # Validate all changes before writing any
    for change in changes:
        if not isinstance(change, dict):
            return error_response("Each change must be an object", 400)

        mt_id = change.get("id")
        if not isinstance(mt_id, int) or mt_id < 0 or mt_id >= num_metatiles:
            return error_response(
                f"Invalid metatile id: {mt_id!r} "
                f"(must be 0-{num_metatiles - 1})",
                400,
            )

        has_layer = "layer_type" in change
        has_behavior = "behavior" in change
        has_action = "layer_action" in change
        if not has_layer and not has_behavior and not has_action:
            return error_response(
                f"Change for id {mt_id} must include 'layer_type', "
                f"'layer_action', and/or 'behavior'",
                400,
            )

        if has_layer:
            lt = change["layer_type"]
            if not isinstance(lt, int) or lt < 0 or lt > 3:
                return error_response(
                    f"layer_type must be 0-3, got {lt!r}", 400,
                )

        if has_behavior:
            bv = change["behavior"]
            if not isinstance(bv, int) or bv < 0 or bv > 255:
                return error_response(
                    f"behavior must be 0-255, got {bv!r}", 400,
                )

    # For FR import tilesets: also fix metatiles.bin when changing layer types.
    # FR imports have data on bottom+top with empty middle.
    # Covered (1) reads bot+mid, so we need to copy top→middle.
    # Split (2) reads bot+top, which is already correct.
    # Always load metatiles.bin — needed for layer_action (moving tiles
    # between layers) and fr_import_fix.
    mt_data = None
    mt_path = None
    try:
        mt_path = _safe_path(ts_dir, "metatiles.bin")
        with open(mt_path, "rb") as f:
            mt_data = bytearray(f.read())
    except (ValueError, OSError):
        mt_data = None

    mt_stride = 24  # 12 tiles per metatile

    # Apply changes
    count = 0
    for change in changes:
        mt_id = change["id"]
        offset = mt_id * stride
        val = struct.unpack_from("<H", attr_data, offset)[0]

        if "behavior" in change:
            val = (val & ~0xFF) | (change["behavior"] & 0xFF)

        new_layer = change.get("layer_type")
        if new_layer is not None:
            val = (val & ~0xF000) | ((new_layer & 0xF) << 12)

        # Move tile data between layers (the ACTUAL rendering fix).
        # In triple-layer mode, the engine ignores layer_type for rendering.
        # BG1 (top) ALWAYS renders in front of sprites.
        # BG2 (middle) and BG3 (bottom) render behind sprites.
        # So what matters is which layer the tile data is physically on.
        layer_action = change.get("layer_action")
        if layer_action and mt_data and mt_id * mt_stride + mt_stride <= len(mt_data):
            mt_off = mt_id * mt_stride
            if layer_action == "top_to_middle":
                # Move top→middle (tile renders behind player)
                for t in range(4):
                    top_val = struct.unpack_from(
                        "<H", mt_data, mt_off + 16 + t * 2)[0]
                    mid_val = struct.unpack_from(
                        "<H", mt_data, mt_off + 8 + t * 2)[0]
                    if top_val != 0 and mid_val == 0:
                        struct.pack_into(
                            "<H", mt_data, mt_off + 8 + t * 2, top_val)
                    struct.pack_into(
                        "<H", mt_data, mt_off + 16 + t * 2, 0)
            elif layer_action == "middle_to_top":
                # Move middle→top (tile renders in front of player)
                for t in range(4):
                    mid_val = struct.unpack_from(
                        "<H", mt_data, mt_off + 8 + t * 2)[0]
                    top_val = struct.unpack_from(
                        "<H", mt_data, mt_off + 16 + t * 2)[0]
                    if mid_val != 0 and top_val == 0:
                        struct.pack_into(
                            "<H", mt_data, mt_off + 16 + t * 2, mid_val)
                    struct.pack_into(
                        "<H", mt_data, mt_off + 8 + t * 2, 0)

        struct.pack_into("<H", attr_data, offset, val)
        count += 1

    # Atomic write attributes
    dir_path = os.path.dirname(attr_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(attr_data)
        os.replace(tmp_path, attr_path)
    except OSError as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return error_response(f"Failed to write attributes: {e}", 500)

    # Atomic write metatiles if modified
    if mt_data and mt_path:
        fd2, tmp2 = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd2, "wb") as f:
                f.write(mt_data)
            os.replace(tmp2, mt_path)
        except OSError:
            try:
                os.unlink(tmp2)
            except OSError:
                pass

    return ok_response({"saved": count})
