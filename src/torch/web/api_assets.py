# TORCH_MODULE: Web API — Assets
# TORCH_GROUP: Web
"""Asset Browser API endpoints for the TORCH web GUI.

Provides read-only catalogue endpoints for browsing game assets:
trainer sprites, overworld sprites, back sprites, item icons,
music, sound effects, tilesets.

Backed by the pure scanner functions in asset_browser.py.
"""

import os
import re
import struct
import time
import zlib

from torch.web.api import (
    api_route, ok_response, error_response, _safe_path,
)
from torch.asset_browser import (
    _scan_trainer_sprites,
    _scan_overworld_sprites,
    _scan_trainer_back_sprites,
    _scan_item_icons,
    _scan_music_tracks,
    _scan_sound_effects,
    _scan_tilesets,
    _count_custom_palettes,
    _filter_assets,
    _search_assets,
    _build_sprite_trainer_map,
)
from torch.asset_manager import (
    ASSET_TYPES,
    _scan_import_dir,
    _detect_already_imported,
    _ensure_import_dirs,
    _append_manifest,
    _move_to_imported,
    _cleanup_imported_staging,
    _list_imported_backup,
    _parse_png_info,
    _read_manifest,
)


# ---------------------------------------------------------------------------
# Category registry
# ---------------------------------------------------------------------------

_CATEGORIES = {
    "trainer_sprites": {
        "name": "Trainer Sprites",
        "scanner": _scan_trainer_sprites,
    },
    "trainer_back_sprites": {
        "name": "Back Sprites",
        "scanner": _scan_trainer_back_sprites,
    },
    "overworld_sprites": {
        "name": "Overworld Sprites",
        "scanner": _scan_overworld_sprites,
    },
    "item_icons": {
        "name": "Item Icons",
        "scanner": _scan_item_icons,
    },
    "music": {
        "name": "Music",
        "scanner": _scan_music_tracks,
    },
    "sound_effects": {
        "name": "Sound Effects",
        "scanner": _scan_sound_effects,
    },
    "tilesets": {
        "name": "Tilesets",
        "scanner": _scan_tilesets,
    },
}


# ---------------------------------------------------------------------------
# Scanner cache — avoid rescanning hundreds of files on every page load.
# 30-second TTL is enough to survive rapid navigations while staying fresh.
# ---------------------------------------------------------------------------

_asset_cache = {}   # (game_path, category) -> (timestamp, result)
_CACHE_TTL = 30


def _cached_scan(category, scanner, game_path):
    """Return cached scanner results, re-scanning only after TTL expires."""
    key = (game_path, category)
    now = time.time()
    if key in _asset_cache:
        ts, result = _asset_cache[key]
        if now - ts < _CACHE_TTL:
            return result
    result = scanner(game_path)
    _asset_cache[key] = (now, result)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_game_path(handler):
    """Extract game_path from handler, return (path, error_response)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return None, error_response("No game path configured", 500)
    return game_path, None


def _apply_filters(assets, query_params):
    """Apply filter and search query params to an asset list."""
    filter_mode = query_params.get("filter", ["all"])[0]
    if filter_mode not in ("all", "custom", "vanilla"):
        filter_mode = "all"
    result = _filter_assets(assets, filter_mode)

    search = query_params.get("search", [""])[0].strip()
    if search:
        result = _search_assets(result, search)

    # Sort
    sort_mode = query_params.get("sort", ["id"])[0]
    if sort_mode == "name":
        result = sorted(result, key=lambda a: a["name"].lower())
    elif sort_mode == "custom_first":
        result = sorted(result, key=lambda a: (not a["is_custom"], a["id"]))
    # default: by id (already sorted from scanners)

    return result


def _ensure_png_transparency(data):
    """Add tRNS chunk to indexed PNG if missing, marking palette index 0 as transparent."""
    if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n':
        return data
    color_type = data[25]
    if color_type != 3:
        return data
    if b'tRNS' in data:
        return data
    pos = 8
    plte_end = None
    palette_entries = 0
    while pos < len(data) - 4:
        chunk_len = struct.unpack('>I', data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_end = pos + 12 + chunk_len
        if chunk_type == b'PLTE':
            palette_entries = chunk_len // 3
            plte_end = chunk_end
            break
        pos = chunk_end
    if not plte_end or palette_entries == 0:
        return data
    trns_data = b'\x00' + b'\xff' * (palette_entries - 1)
    trns_crc = zlib.crc32(b'tRNS' + trns_data) & 0xffffffff
    trns_chunk = (struct.pack('>I', len(trns_data)) + b'tRNS'
                  + trns_data + struct.pack('>I', trns_crc))
    return data[:plte_end] + trns_chunk + data[plte_end:]


def _serve_png(handler, full_path, transparent=True):
    """Read a PNG file and send it as the HTTP response.

    If transparent is True, adds tRNS chunk for indexed PNGs.
    Returns None (signals handler already wrote response).
    """
    if not os.path.isfile(full_path):
        handler.send_error(404, "Not Found")
        return None

    try:
        with open(full_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_error(500, "Read error")
        return None

    if transparent:
        data = _ensure_png_transparency(data)

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)
    return None


# ---------------------------------------------------------------------------
# GET /api/assets/summary — Overview stats
# ---------------------------------------------------------------------------

@api_route("GET", "/api/assets/summary")
def handle_assets_summary(handler, match, query_params):
    """Return total and custom counts for all asset categories."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    categories = []
    total_all = 0
    custom_all = 0
    for cat_id, cat in _CATEGORIES.items():
        assets = _cached_scan(cat_id, cat["scanner"], game_path)
        total = len(assets)
        custom = sum(1 for a in assets if a["is_custom"])
        total_all += total
        custom_all += custom
        categories.append({
            "id": cat_id,
            "name": cat["name"],
            "count": total,
            "custom_count": custom,
        })

    return ok_response({
        "categories": categories,
        "total": total_all,
        "custom_total": custom_all,
    })


# ---------------------------------------------------------------------------
# GET /api/assets/categories — Category list with counts
# ---------------------------------------------------------------------------

@api_route("GET", "/api/assets/categories")
def handle_assets_categories(handler, match, query_params):
    """Return the list of asset categories with counts."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    result = []
    for cat_id, cat in _CATEGORIES.items():
        assets = _cached_scan(cat_id, cat["scanner"], game_path)
        total = len(assets)
        custom = sum(1 for a in assets if a["is_custom"])
        result.append({
            "id": cat_id,
            "name": cat["name"],
            "count": total,
            "custom_count": custom,
        })

    return ok_response({"categories": result})


# ---------------------------------------------------------------------------
# GET /api/assets/palettes — Palette summary
# ---------------------------------------------------------------------------

@api_route("GET", "/api/assets/palettes")
def handle_assets_palettes(handler, match, query_params):
    """Return custom palette tag usage stats."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    count, capacity = _count_custom_palettes(game_path)
    return ok_response({
        "count": count,
        "capacity": capacity,
        "usage_pct": round(count / capacity * 100, 1) if capacity > 0 else 0,
    })


# ---------------------------------------------------------------------------
# GET /api/assets/<category> — List assets in a category
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/assets/(?P<category>[a-z_]+)/list")
def handle_assets_list(handler, match, query_params):
    """Return all assets in a given category, with optional filtering."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    cat_id = match.group("category")
    cat = _CATEGORIES.get(cat_id)
    if not cat:
        return error_response(f"Unknown category: {cat_id}", 404)

    all_assets = _cached_scan(cat_id, cat["scanner"], game_path)
    filtered = _apply_filters(all_assets, query_params)

    total = len(all_assets)
    custom = sum(1 for a in all_assets if a["is_custom"])

    return ok_response({
        "category": cat_id,
        "name": cat["name"],
        "assets": filtered,
        "total": total,
        "custom_count": custom,
        "filtered_count": len(filtered),
    })


# ---------------------------------------------------------------------------
# GET /api/assets/<category>/<constant> — Asset detail
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/assets/(?P<category>[a-z_]+)/detail/(?P<constant>\w+)")
def handle_asset_detail(handler, match, query_params):
    """Return detail for a single asset."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    cat_id = match.group("category")
    constant = match.group("constant")
    cat = _CATEGORIES.get(cat_id)
    if not cat:
        return error_response(f"Unknown category: {cat_id}", 404)

    all_assets = _cached_scan(cat_id, cat["scanner"], game_path)
    asset = None
    for a in all_assets:
        if a["constant"] == constant:
            asset = a
            break

    if not asset:
        return error_response(f"Asset not found: {constant}", 404)

    detail = dict(asset)

    # Trainer sprite cross-reference: which trainers use this pic
    if cat_id == "trainer_sprites":
        sprite_map = _build_sprite_trainer_map(game_path)
        trainers = sprite_map.get(constant, [])
        detail["used_by_trainers"] = [
            {"constant": t, "map": m} for t, m in trainers
        ]

    # Tileset extra info
    if cat_id == "tilesets" and asset["file"]:
        ts_dir = os.path.join(game_path, asset["file"])
        metatiles_bin = os.path.join(ts_dir, "metatiles.bin")
        palettes = [f for f in os.listdir(ts_dir)
                    if f.endswith(".pal")] if os.path.isdir(ts_dir) else []
        metatile_count = 0
        if os.path.isfile(metatiles_bin):
            try:
                size = os.path.getsize(metatiles_bin)
                # Expansion: 24 bytes/metatile (12 tiles), vanilla: 16 bytes (8 tiles)
                # Cross-reference with attributes file to detect format
                attrs_bin = os.path.join(ts_dir, "metatile_attributes.bin")
                attrs_size = 0
                if os.path.isfile(attrs_bin):
                    attrs_size = os.path.getsize(attrs_bin)
                if attrs_size > 0 and size % 24 == 0 and attrs_size // 2 == size // 24:
                    metatile_count = size // 24
                elif attrs_size > 0 and size % 16 == 0 and attrs_size // 4 == size // 16:
                    metatile_count = size // 16
                else:
                    metatile_count = size // 24  # expansion default
            except OSError:
                pass
        detail["palette_count"] = len(palettes)
        detail["metatile_count"] = metatile_count

    return ok_response(detail)


# ---------------------------------------------------------------------------
# GET /api/assets/trainer-back/<constant> — Serve trainer back sprite
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/assets/trainer-back/(?P<constant>TRAINER_BACK_PIC_\w+)")
def handle_trainer_back_sprite(handler, match, query_params):
    """Serve a trainer back sprite PNG."""
    game_path, err = _get_game_path(handler)
    if err:
        handler.send_error(404, "Not Found")
        return None

    constant = match.group("constant")

    # Use INCBIN map for accurate path, fall back to constant-derived name
    from torch.asset_browser import _build_trainer_back_incbin_map
    back_map = _build_trainer_back_incbin_map(game_path)
    file_rel = back_map.get(constant, "")

    if file_rel:
        try:
            full_path = _safe_path(game_path, file_rel)
        except ValueError:
            handler.send_error(403, "Forbidden")
            return None
    else:
        stem = constant.replace("TRAINER_BACK_PIC_", "").lower()
        pics_dir = os.path.join(game_path, "graphics", "trainers", "back_pics")
        try:
            full_path = _safe_path(pics_dir, f"{stem}.png")
        except ValueError:
            handler.send_error(403, "Forbidden")
            return None

    return _serve_png(handler, full_path)


# ---------------------------------------------------------------------------
# GET /api/assets/tilesets/<name>/image — Serve tileset PNG
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/assets/tilesets/(?P<name>[A-Za-z0-9_]+)/image")
def handle_tileset_image(handler, match, query_params):
    """Serve a tileset's tiles.png file."""
    game_path, err = _get_game_path(handler)
    if err:
        handler.send_error(404, "Not Found")
        return None

    name = match.group("name")

    # Try secondary first, then primary.
    # tiles.png lives under data/tilesets/, not graphics/tilesets/.
    for tier in ("secondary", "primary"):
        data_dir = os.path.join(game_path, "data", "tilesets", tier, name)
        png_path = os.path.join(data_dir, "tiles.png")
        if os.path.isfile(png_path):
            try:
                full_path = _safe_path(
                    os.path.join(game_path, "data", "tilesets"),
                    tier, name, "tiles.png",
                )
            except ValueError:
                handler.send_error(403, "Forbidden")
                return None
            return _serve_png(handler, full_path, transparent=False)

    handler.send_error(404, "Not Found")
    return None


# ---------------------------------------------------------------------------
# GET /api/assets/item-icon/<symbol> — Serve item icon by gItemIcon_ symbol
# ---------------------------------------------------------------------------

_item_symbol_cache = {}  # game_path -> {gItemIcon_X: "filename.png"}


def _build_item_symbol_map(game_path):
    """Build gItemIcon_X -> filename.png mapping from INCBIN declarations."""
    gfx_h = os.path.join(game_path, "src", "data", "graphics", "items.h")
    result = {}
    if not os.path.isfile(gfx_h):
        return result
    try:
        text = open(gfx_h, encoding="utf-8", errors="replace").read()
        for m in re.findall(
                r'const u32 (\w+)\[\]\s*=\s*INCBIN_U32\('
                r'"graphics/items/icons/(\w+)\.', text):
            result[m[0]] = m[1] + ".png"
    except OSError:
        pass
    return result


@api_route("GET", r"/api/assets/item-icon/(?P<symbol>gItemIcon_\w+)")
def handle_item_icon_by_symbol(handler, match, query_params):
    """Serve an item icon PNG by its gItemIcon_ symbol name."""
    game_path, err = _get_game_path(handler)
    if err:
        handler.send_error(404, "Not Found")
        return None

    symbol = match.group("symbol")

    if game_path not in _item_symbol_cache:
        _item_symbol_cache[game_path] = _build_item_symbol_map(game_path)
    symbol_map = _item_symbol_cache[game_path]

    filename = symbol_map.get(symbol)
    if not filename:
        handler.send_error(404, "Not Found")
        return None

    icons_dir = os.path.join(game_path, "graphics", "items", "icons")
    try:
        full_path = _safe_path(icons_dir, filename)
    except ValueError:
        handler.send_error(403, "Forbidden")
        return None

    return _serve_png(handler, full_path)


# ---------------------------------------------------------------------------
# GET /api/assets/overworld-frame/<constant> — Serve first frame of overworld
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/assets/overworld-frame/(?P<constant>OBJ_EVENT_GFX_\w+)")
def handle_overworld_frame(handler, match, query_params):
    """Serve the first frame of an overworld spritesheet as a cropped PNG.

    Overworld PNGs are spritesheets (e.g. 144x32 = 9 frames of 16x32).
    This endpoint extracts the first frame for thumbnail display.
    """
    game_path, err = _get_game_path(handler)
    if err:
        handler.send_error(404, "Not Found")
        return None

    # Reuse the sprite index from api.py to find PNG path + dimensions
    from torch.web.api import build_sprite_index
    sprite_index = build_sprite_index(game_path)
    constant = match.group("constant")
    entry = sprite_index.get(constant)
    if not entry:
        handler.send_error(404, "Not Found")
        return None

    png_rel = entry["png"]
    try:
        full_path = _safe_path(game_path, png_rel)
    except ValueError:
        handler.send_error(403, "Forbidden")
        return None

    if not os.path.isfile(full_path):
        handler.send_error(404, "Not Found")
        return None

    width = entry.get("width", 16)
    height = entry.get("height", 32)

    try:
        with open(full_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_error(500, "Read error")
        return None

    # Crop to first frame using pure-Python PNG manipulation
    cropped = _crop_indexed_png(data, width, height)
    if cropped is None:
        # Fallback: serve full sheet with transparency
        data = _ensure_png_transparency(data)
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "public, max-age=86400")
        handler.end_headers()
        handler.wfile.write(data)
        return None

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(cropped)))
    handler.send_header("Cache-Control", "public, max-age=86400")
    handler.end_headers()
    handler.wfile.write(cropped)
    return None


def _crop_indexed_png(data, frame_w, frame_h):
    """Crop an indexed-color PNG to its first frame (top-left frame_w x frame_h).

    Works with 4-bit (bitDepth=4) and 8-bit (bitDepth=8) indexed PNGs.
    Returns new PNG bytes, or None if cropping fails.
    """
    if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n':
        return None

    # Parse IHDR
    ihdr_len = struct.unpack('>I', data[8:12])[0]
    if data[12:16] != b'IHDR' or ihdr_len < 13:
        return None
    ihdr_data = data[16:16 + ihdr_len]
    img_w = struct.unpack('>I', ihdr_data[0:4])[0]
    img_h = struct.unpack('>I', ihdr_data[4:8])[0]
    bit_depth = ihdr_data[8]
    color_type = ihdr_data[9]

    # Only handle indexed color (type 3)
    if color_type != 3:
        return None
    if bit_depth not in (4, 8):
        return None

    # If image is already the right size, no crop needed
    if img_w == frame_w and img_h == frame_h:
        return _ensure_png_transparency(data)

    # Collect all chunks
    chunks = []
    pos = 8
    idat_data = b""
    while pos < len(data):
        if pos + 8 > len(data):
            break
        chunk_len = struct.unpack('>I', data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_body = data[pos + 8:pos + 8 + chunk_len]
        pos = pos + 12 + chunk_len
        if chunk_type == b'IDAT':
            idat_data += chunk_body
        elif chunk_type != b'IEND':
            chunks.append((chunk_type, chunk_body))

    # Decompress image data
    try:
        raw = zlib.decompress(idat_data)
    except zlib.error:
        return None

    # Calculate row stride (with filter byte)
    if bit_depth == 8:
        stride = 1 + img_w  # 1 filter byte + 1 byte per pixel
    else:  # bit_depth == 4
        stride = 1 + (img_w + 1) // 2  # 1 filter byte + ceil(w/2) bytes

    if len(raw) < stride * img_h:
        return None

    # Extract first frame rows, taking only frame_w pixels from each row.
    # We must track unfiltered rows for Up/Average filter reconstruction.
    cropped_rows = []
    prev_unfiltered = b'\x00' * (stride - 1)
    for y in range(min(frame_h, img_h)):
        row_start = y * stride
        filter_byte = raw[row_start:row_start + 1]
        row_data = raw[row_start + 1:row_start + stride]

        fb = filter_byte[0] if filter_byte else 0
        if fb == 0:
            # None filter — use as-is
            pass
        elif fb == 1:
            # Sub filter — each byte depends on previous byte
            arr = bytearray(row_data)
            for i in range(1, len(arr)):
                arr[i] = (arr[i] + arr[i - 1]) & 0xFF
            row_data = bytes(arr)
        elif fb == 2:
            # Up filter — each byte depends on same position in previous row
            arr = bytearray(row_data)
            for i in range(len(arr)):
                arr[i] = (arr[i] + prev_unfiltered[i]) & 0xFF
            row_data = bytes(arr)
        elif fb == 3:
            # Average filter
            arr = bytearray(row_data)
            for i in range(len(arr)):
                left = arr[i - 1] if i > 0 else 0
                up = prev_unfiltered[i]
                arr[i] = (arr[i] + (left + up) // 2) & 0xFF
            row_data = bytes(arr)
        elif fb == 4:
            # Paeth filter
            arr = bytearray(row_data)
            for i in range(len(arr)):
                a = arr[i - 1] if i > 0 else 0        # left
                b = prev_unfiltered[i]                  # above
                c = prev_unfiltered[i - 1] if i > 0 else 0  # upper-left
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                arr[i] = (arr[i] + pr) & 0xFF
            row_data = bytes(arr)
        else:
            return None

        prev_unfiltered = row_data

        # Trim to frame_w pixels
        if bit_depth == 8:
            trimmed = row_data[:frame_w]
        else:  # 4-bit
            bytes_needed = (frame_w + 1) // 2
            trimmed = row_data[:bytes_needed]
            if frame_w % 2 == 1 and trimmed:
                trimmed = trimmed[:-1] + bytes([trimmed[-1] & 0xF0])

        # Re-encode with filter=None
        cropped_rows.append(b'\x00' + trimmed)

    cropped_raw = b''.join(cropped_rows)

    # Build new PNG
    result = b'\x89PNG\r\n\x1a\n'

    # New IHDR
    new_ihdr = struct.pack('>II', frame_w, frame_h) + ihdr_data[8:]
    result += _png_chunk(b'IHDR', new_ihdr)

    # Copy PLTE, tRNS, and other ancillary chunks
    has_trns = False
    for chunk_type, chunk_body in chunks:
        if chunk_type == b'IHDR':
            continue
        if chunk_type == b'tRNS':
            has_trns = True
        result += _png_chunk(chunk_type, chunk_body)

    # Add tRNS if missing (palette index 0 = transparent)
    if not has_trns:
        for chunk_type, chunk_body in chunks:
            if chunk_type == b'PLTE':
                palette_entries = len(chunk_body) // 3
                trns = b'\x00' + b'\xff' * (palette_entries - 1)
                result += _png_chunk(b'tRNS', trns)
                break

    # Compressed image data
    compressed = zlib.compress(cropped_raw)
    result += _png_chunk(b'IDAT', compressed)

    # IEND
    result += _png_chunk(b'IEND', b'')

    return result


def _png_chunk(chunk_type, data):
    """Build a PNG chunk with length, type, data, and CRC."""
    body = chunk_type + data
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return struct.pack('>I', len(data)) + body + struct.pack('>I', crc)


# ---------------------------------------------------------------------------
# GET /api/assets/music/<constant>/midi — Serve MIDI file
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/assets/music/(?P<constant>MUS_\w+)/midi")
def handle_music_midi(handler, match, query_params):
    """Serve a music track's MIDI file."""
    game_path, err = _get_game_path(handler)
    if err:
        handler.send_error(404, "Not Found")
        return None

    constant = match.group("constant")
    stem = constant.replace("MUS_", "").lower()

    midi_dir = os.path.join(game_path, "sound", "songs", "midi")
    midi_name = f"mus_{stem}.mid"

    try:
        full_path = _safe_path(midi_dir, midi_name)
    except ValueError:
        handler.send_error(403, "Forbidden")
        return None

    if not os.path.isfile(full_path):
        handler.send_error(404, "Not Found")
        return None

    try:
        with open(full_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_error(500, "Read error")
        return None

    handler.send_response(200)
    handler.send_header("Content-Type", "audio/midi")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)
    return None


# ---------------------------------------------------------------------------
# GET /api/assets/character-sheet/<name> — Cross-reference sprites by name
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/assets/character-sheet/(?P<name>[A-Za-z0-9_]+)")
def handle_character_sheet(handler, match, query_params):
    """Find matching sprites across categories for a character name.

    Matches trainer front sprite, back sprite, and overworld sprite
    by name similarity (case-insensitive substring match).
    """
    game_path, err = _get_game_path(handler)
    if err:
        return err

    name = match.group("name").lower()

    result = {"name": name, "sprites": {}}

    # Search trainer front sprites
    front = _cached_scan("trainer_sprites",
                         _CATEGORIES["trainer_sprites"]["scanner"], game_path)
    for a in front:
        if a["name"].lower() == name:
            result["sprites"]["trainer_front"] = {
                "constant": a["constant"],
                "name": a["name"],
                "url": f"/api/trainers/sprites/{a['file'].replace('graphics/trainers/front_pics/', '')}" if a["file"] else "",
            }
            break

    # Search trainer back sprites
    back = _cached_scan("trainer_back_sprites",
                        _CATEGORIES["trainer_back_sprites"]["scanner"], game_path)
    for a in back:
        if a["name"].lower() == name:
            result["sprites"]["trainer_back"] = {
                "constant": a["constant"],
                "name": a["name"],
                "url": f"/api/assets/trainer-back/{a['constant']}",
            }
            break

    # Search overworld sprites
    overworld = _cached_scan("overworld_sprites",
                             _CATEGORIES["overworld_sprites"]["scanner"],
                             game_path)
    for a in overworld:
        # Overworld names are like "Brendan Normal" — match if starts with name
        ow_name = a["name"].lower()
        if ow_name == name or ow_name.startswith(name + " "):
            entry = {
                "constant": a["constant"],
                "name": a["name"],
                "url": f"/api/assets/overworld-frame/{a['constant']}",
            }
            if "overworld" not in result["sprites"]:
                result["sprites"]["overworld"] = []
            result["sprites"]["overworld"].append(entry)

    return ok_response(result)


# ---------------------------------------------------------------------------
# Staging helpers
# ---------------------------------------------------------------------------

def _get_import_base(handler):
    """Resolve the asset import base directory from server state.

    project_dir is <workspace>/<proj_name> (e.g. ~/ROMHacking/TORCH/Pokemon Seihoku).
    The import directory is <project_dir>/assets/ unless overridden in settings.
    """
    settings = getattr(handler.server, "settings", {})
    project_dir = getattr(handler.server, "project_dir", "")

    # Check for custom override first
    custom = settings.get("asset_import_dir", "")
    if custom:
        return os.path.expanduser(custom)

    # Default: <project_dir>/assets/
    if project_dir:
        return os.path.join(project_dir, "assets")
    return None


# Map asset_browser category IDs to asset_manager type keys
_BROWSER_TO_MANAGER = {
    "trainer_sprites": "trainer_sprites",
    "trainer_back_sprites": "trainer_back_sprites",
    "overworld_sprites": "overworld_sprites",
    "item_icons": "item_icons",
    "music": "music_tracks",
    "sound_effects": "sound_effects",
    "tilesets": None,  # tilesets use a different import path
}


# ---------------------------------------------------------------------------
# GET /api/assets/staged — List all staged files awaiting import
# ---------------------------------------------------------------------------

@api_route("GET", "/api/assets/staged")
def handle_staged_list(handler, match, query_params):
    """List files in the import staging directory, grouped by type.

    Each file includes: filename, type, validation status, preview URL,
    derived constant name, and whether it's already imported.
    """
    game_path, err = _get_game_path(handler)
    if err:
        return err

    import_base = _get_import_base(handler)
    if not import_base:
        return error_response("Import directory not configured", 500)

    _ensure_import_dirs(import_base)

    result = {
        "import_dir": import_base,
        "categories": [],
        "total_staged": 0,
        "total_ready": 0,
    }

    for type_key, atype in ASSET_TYPES.items():
        files = _scan_import_dir(type_key, import_base)
        if not files:
            continue

        existing = _detect_already_imported(type_key, game_path)
        const_fn = atype["const_from_file"]

        staged = []
        for fpath in files:
            fname = os.path.basename(fpath)
            const = const_fn(fname)
            already_imported = const in existing

            # Validate
            ok, msg = atype["validator"](fpath)

            # Build preview URL
            preview_url = ""
            if atype["file_pattern"] == "*.png":
                preview_url = f"/api/assets/staged/preview/{type_key}/{fname}"
            elif atype["file_pattern"] == "*.mid":
                preview_url = f"/api/assets/staged/preview/{type_key}/{fname}"

            # File info
            info = {
                "filename": fname,
                "constant": const,
                "valid": ok,
                "message": msg,
                "already_imported": already_imported,
                "preview_url": preview_url,
            }

            # Add PNG dimensions for visual types
            if fpath.endswith(".png"):
                png_info = _parse_png_info(fpath)
                if png_info:
                    info["width"] = png_info["width"]
                    info["height"] = png_info["height"]
                    info["palette_size"] = png_info["palette_size"]

            staged.append(info)

        ready = sum(1 for s in staged if s["valid"] and not s["already_imported"])
        result["categories"].append({
            "type_key": type_key,
            "name": atype["name"],
            "description": atype.get("description", ""),
            "staged": staged,
            "count": len(staged),
            "ready_count": ready,
        })
        result["total_staged"] += len(staged)
        result["total_ready"] += ready

    return ok_response(result)


# ---------------------------------------------------------------------------
# GET /api/assets/staged/preview/<type>/<filename> — Serve staged file
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/assets/staged/preview/(?P<type_key>[a-z_]+)/(?P<filename>[A-Za-z0-9_.\-]+)")
def handle_staged_preview(handler, match, query_params):
    """Serve a preview of a staged file (PNG or MIDI)."""
    import_base = _get_import_base(handler)
    if not import_base:
        handler.send_error(404, "Not Found")
        return None

    type_key = match.group("type_key")
    filename = match.group("filename")

    if type_key not in ASSET_TYPES:
        handler.send_error(404, "Not Found")
        return None

    atype = ASSET_TYPES[type_key]
    import_dir = os.path.join(import_base, atype["import_dir"])

    try:
        full_path = _safe_path(import_dir, filename)
    except ValueError:
        handler.send_error(403, "Forbidden")
        return None

    if not os.path.isfile(full_path):
        handler.send_error(404, "Not Found")
        return None

    # Determine content type
    if filename.endswith(".png"):
        return _serve_png(handler, full_path)
    elif filename.endswith(".mid"):
        try:
            with open(full_path, "rb") as f:
                data = f.read()
        except OSError:
            handler.send_error(500, "Read error")
            return None
        handler.send_response(200)
        handler.send_header("Content-Type", "audio/midi")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        return None
    else:
        handler.send_error(415, "Unsupported Media Type")
        return None


# ---------------------------------------------------------------------------
# POST /api/assets/staged/import — Import staged files
# ---------------------------------------------------------------------------

@api_route("POST", "/api/assets/staged/import")
def handle_staged_import(handler, match, query_params):
    """Import one or all staged files.

    Body JSON: {"type_key": "trainer_sprites", "filename": "my_trainer.png"}
    Or for all ready files: {"type_key": "all"}
    """
    import json

    game_path, err = _get_game_path(handler)
    if err:
        return err

    import_base = _get_import_base(handler)
    if not import_base:
        return error_response("Import directory not configured", 500)

    # Read request body
    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length == 0:
        return error_response("Request body required", 400)
    try:
        body = json.loads(handler.rfile.read(content_length))
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON", 400)

    type_key = body.get("type_key", "")
    filename = body.get("filename", "")

    if type_key == "all":
        return _import_all_staged(game_path, import_base)

    if type_key not in ASSET_TYPES:
        return error_response(f"Unknown asset type: {type_key}", 400)

    if not filename:
        return _import_type_staged(type_key, game_path, import_base)

    return _import_single_staged(type_key, filename, game_path, import_base)


def _import_single_staged(type_key, filename, game_path, import_base):
    """Import a single staged file."""
    atype = ASSET_TYPES[type_key]
    import_dir = os.path.join(import_base, atype["import_dir"])
    fpath = os.path.join(import_dir, filename)

    if not os.path.isfile(fpath):
        return error_response(f"File not found: {filename}", 404)

    # Validate
    ok, msg = atype["validator"](fpath)
    if not ok:
        return error_response(f"Validation failed: {msg}", 400)

    # Check not already imported
    existing = _detect_already_imported(type_key, game_path)
    const = atype["const_from_file"](filename)
    if const in existing:
        return error_response(f"Already imported: {const}", 409)

    # Import
    try:
        atype["importer"](fpath, game_path)
        _append_manifest(import_base, type_key, filename)
        _move_to_imported(import_base, type_key, filename)
    except Exception as exc:
        return error_response(f"Import failed: {exc}", 500)

    # Invalidate asset cache for this category
    browser_cat = None
    for bcat, mkey in _BROWSER_TO_MANAGER.items():
        if mkey == type_key:
            browser_cat = bcat
            break
    if browser_cat:
        cache_key = (game_path, browser_cat)
        _asset_cache.pop(cache_key, None)

    return ok_response({
        "imported": filename,
        "constant": const,
        "type": atype["name"],
    })


def _import_type_staged(type_key, game_path, import_base):
    """Import all ready files for a specific type."""
    atype = ASSET_TYPES[type_key]
    files = _scan_import_dir(type_key, import_base)
    existing = _detect_already_imported(type_key, game_path)
    const_fn = atype["const_from_file"]

    results = []
    for fpath in files:
        fname = os.path.basename(fpath)
        const = const_fn(fname)
        if const in existing:
            continue
        ok, msg = atype["validator"](fpath)
        if not ok:
            results.append({"filename": fname, "ok": False, "error": msg})
            continue
        try:
            atype["importer"](fpath, game_path)
            _append_manifest(import_base, type_key, fname)
            _move_to_imported(import_base, type_key, fname)
            results.append({"filename": fname, "ok": True, "constant": const})
        except Exception as exc:
            results.append({"filename": fname, "ok": False, "error": str(exc)})

    # Invalidate cache
    for bcat, mkey in _BROWSER_TO_MANAGER.items():
        if mkey == type_key:
            _asset_cache.pop((game_path, bcat), None)
            break

    return ok_response({
        "type": atype["name"],
        "results": results,
        "imported_count": sum(1 for r in results if r["ok"]),
    })


def _import_all_staged(game_path, import_base):
    """Import all ready files across all types."""
    all_results = {}
    total_imported = 0

    for type_key, atype in ASSET_TYPES.items():
        files = _scan_import_dir(type_key, import_base)
        if not files:
            continue
        existing = _detect_already_imported(type_key, game_path)
        const_fn = atype["const_from_file"]

        type_results = []
        for fpath in files:
            fname = os.path.basename(fpath)
            const = const_fn(fname)
            if const in existing:
                continue
            ok, msg = atype["validator"](fpath)
            if not ok:
                type_results.append({"filename": fname, "ok": False, "error": msg})
                continue
            try:
                atype["importer"](fpath, game_path)
                _append_manifest(import_base, type_key, fname)
                _move_to_imported(import_base, type_key, fname)
                type_results.append({"filename": fname, "ok": True, "constant": const})
                total_imported += 1
            except Exception as exc:
                type_results.append({"filename": fname, "ok": False, "error": str(exc)})

        if type_results:
            all_results[type_key] = type_results

        # Invalidate cache
        for bcat, mkey in _BROWSER_TO_MANAGER.items():
            if mkey == type_key:
                _asset_cache.pop((game_path, bcat), None)
                break

    return ok_response({
        "results": all_results,
        "total_imported": total_imported,
    })


# ---------------------------------------------------------------------------
# GET /api/assets/custom — Dashboard data for Assets Home
# ---------------------------------------------------------------------------

@api_route("GET", "/api/assets/custom")
def handle_custom_dashboard(handler, match, query_params):
    """Return dashboard data: custom counts, staged counts, backup counts."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    import_base = _get_import_base(handler)
    if import_base:
        _ensure_import_dirs(import_base)

    cats = []
    total_custom = 0
    total_staged = 0

    for cat_id, cat in _CATEGORIES.items():
        assets = _cached_scan(cat_id, cat["scanner"], game_path)
        custom = sum(1 for a in assets if a["is_custom"])
        total_custom += custom

        # Staged count for this category
        staged_count = 0
        staged_ready = 0
        mgr_key = _BROWSER_TO_MANAGER.get(cat_id)
        if mgr_key and import_base and mgr_key in ASSET_TYPES:
            files = _scan_import_dir(mgr_key, import_base)
            existing = _detect_already_imported(mgr_key, game_path)
            const_fn = ASSET_TYPES[mgr_key]["const_from_file"]
            for fpath in files:
                fname = os.path.basename(fpath)
                const = const_fn(fname)
                if const not in existing:
                    staged_count += 1
                    ok, _ = ASSET_TYPES[mgr_key]["validator"](fpath)
                    if ok:
                        staged_ready += 1
            total_staged += staged_count

        # Backup count
        backup_count = 0
        if mgr_key and import_base:
            backup_dir = os.path.join(
                import_base, "imported",
                ASSET_TYPES[mgr_key]["import_dir"])
            if os.path.isdir(backup_dir):
                import glob as _gl
                backup_count = len(_gl.glob(os.path.join(
                    backup_dir, ASSET_TYPES[mgr_key]["file_pattern"])))

        cats.append({
            "id": cat_id,
            "type_key": mgr_key or "",
            "name": cat["name"],
            "custom_count": custom,
            "total_count": len(assets),
            "staged_count": staged_count,
            "staged_ready": staged_ready,
            "backup_count": backup_count,
        })

    # Backup total
    backup_list, backup_total = (
        _list_imported_backup(import_base) if import_base else ([], 0))

    return ok_response({
        "categories": cats,
        "total_custom": total_custom,
        "total_staged": total_staged,
        "backup_total": backup_total,
        "import_dir": import_base or "",
    })


# ---------------------------------------------------------------------------
# POST /api/assets/upload — Upload file to staging via base64
# ---------------------------------------------------------------------------

@api_route("POST", "/api/assets/upload")
def handle_upload(handler, match, query_params):
    """Upload a file to the staging directory via base64-encoded JSON body.

    Body: {"type_key": "trainer_sprites", "filename": "my.png", "data": "<base64>"}
    """
    import base64
    import json

    game_path, err = _get_game_path(handler)
    if err:
        return err

    import_base = _get_import_base(handler)
    if not import_base:
        return error_response("Import directory not configured", 500)

    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length == 0:
        return error_response("Request body required", 400)
    # 3MB cap on request body (base64 overhead on 2MB file)
    if content_length > 3 * 1024 * 1024:
        return error_response("File too large (max 2MB)", 413)

    try:
        body = json.loads(handler.rfile.read(content_length))
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON", 400)

    type_key = body.get("type_key", "")
    filename = body.get("filename", "")
    data_b64 = body.get("data", "")

    if type_key not in ASSET_TYPES:
        return error_response(f"Unknown asset type: {type_key}", 400)
    if not filename:
        return error_response("Filename required", 400)
    if not data_b64:
        return error_response("File data required", 400)

    # Sanitize filename
    if not re.match(r'^[A-Za-z0-9_.\-]+$', filename):
        return error_response("Invalid filename (alphanumeric, underscore, dot, hyphen only)", 400)

    # Check file pattern
    atype = ASSET_TYPES[type_key]
    pattern_ext = atype["file_pattern"].replace("*", "")
    if not filename.endswith(pattern_ext):
        return error_response(
            f"File must match pattern {atype['file_pattern']}", 400)

    # Decode
    try:
        file_data = base64.b64decode(data_b64)
    except Exception:
        return error_response("Invalid base64 data", 400)

    # Size check (2MB decoded)
    if len(file_data) > 2 * 1024 * 1024:
        return error_response("File too large (max 2MB)", 413)

    # Write to staging directory
    _ensure_import_dirs(import_base)
    staging_dir = os.path.join(import_base, atype["import_dir"])
    try:
        dest = _safe_path(staging_dir, filename)
    except ValueError:
        return error_response("Invalid filename", 400)

    if os.path.isfile(dest):
        return error_response(f"File already exists in staging: {filename}", 409)

    try:
        with open(dest, "wb") as f:
            f.write(file_data)
    except OSError as exc:
        return error_response(f"Write failed: {exc}", 500)

    # Validate the written file
    ok, msg = atype["validator"](dest)

    # Preview URL
    preview_url = f"/api/assets/staged/preview/{type_key}/{filename}"

    return ok_response({
        "filename": filename,
        "type_key": type_key,
        "valid": ok,
        "message": msg,
        "preview_url": preview_url,
        "size": len(file_data),
    })


# ---------------------------------------------------------------------------
# POST /api/assets/staged/cleanup — Move already-imported to backup
# ---------------------------------------------------------------------------

@api_route("POST", "/api/assets/staged/cleanup")
def handle_staged_cleanup(handler, match, query_params):
    """Move all already-imported files from staging to imported/ backup."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    import_base = _get_import_base(handler)
    if not import_base:
        return error_response("Import directory not configured", 500)

    _ensure_import_dirs(import_base)
    moved = _cleanup_imported_staging(import_base, game_path)

    return ok_response({"moved": moved})


# ---------------------------------------------------------------------------
# DELETE /api/assets/staged/<type>/<filename> — Remove staged file
# ---------------------------------------------------------------------------

@api_route("DELETE", r"/api/assets/staged/(?P<type_key>[a-z_]+)/(?P<filename>[A-Za-z0-9_.\-]+)")
def handle_staged_delete(handler, match, query_params):
    """Remove a file from the staging directory (discard without importing)."""
    import_base = _get_import_base(handler)
    if not import_base:
        return error_response("Import directory not configured", 500)

    type_key = match.group("type_key")
    filename = match.group("filename")

    if type_key not in ASSET_TYPES:
        return error_response(f"Unknown asset type: {type_key}", 404)

    atype = ASSET_TYPES[type_key]
    staging_dir = os.path.join(import_base, atype["import_dir"])

    try:
        full_path = _safe_path(staging_dir, filename)
    except ValueError:
        return error_response("Invalid filename", 400)

    if not os.path.isfile(full_path):
        return error_response(f"File not found: {filename}", 404)

    try:
        os.remove(full_path)
    except OSError as exc:
        return error_response(f"Delete failed: {exc}", 500)

    return ok_response({"deleted": filename})


# ---------------------------------------------------------------------------
# GET /api/assets/imported — List backup files
# ---------------------------------------------------------------------------

@api_route("GET", "/api/assets/imported")
def handle_imported_list(handler, match, query_params):
    """List files in the imported/ backup directory."""
    import_base = _get_import_base(handler)
    if not import_base:
        return error_response("Import directory not configured", 500)

    result, total = _list_imported_backup(import_base)
    return ok_response({"categories": result, "total": total})


# ---------------------------------------------------------------------------
# DELETE /api/assets/imported/clear — Clear backup archive
# ---------------------------------------------------------------------------

@api_route("DELETE", "/api/assets/imported/clear")
def handle_imported_clear(handler, match, query_params):
    """Clear all files in the imported/ backup directory."""
    import_base = _get_import_base(handler)
    if not import_base:
        return error_response("Import directory not configured", 500)

    removed = 0
    for type_key, atype in ASSET_TYPES.items():
        backup_dir = os.path.join(import_base, "imported", atype["import_dir"])
        if not os.path.isdir(backup_dir):
            continue
        for fname in os.listdir(backup_dir):
            fpath = os.path.join(backup_dir, fname)
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                    removed += 1
                except OSError:
                    pass

    return ok_response({"removed": removed})
