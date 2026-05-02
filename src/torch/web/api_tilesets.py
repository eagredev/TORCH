# TORCH_MODULE: Web API — Tilesets
# TORCH_GROUP: Web
"""Tileset Editor API endpoints.

Provides endpoints for the Tileset Editor that go beyond the existing
metatile layer/behavior editor:
- Tileset listing with metadata
- Metatile composition saving (tile ref assignment)
"""

import os
import shutil
import struct
import tempfile
import time
import zlib

from torch.web.api import (
    api_route, ok_response, error_response, _safe_path,
    _read_json_body,
)
from torch.web.api_metatiles import _resolve_tileset_dir


def _get_game_path(handler):
    """Extract game_path from handler, return (path, error_response)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return None, error_response("No game path configured", 500)
    return game_path, None


# ---------------------------------------------------------------------------
# GET /api/tilesets — list all tilesets
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/tilesets$")
def handle_tilesets_list(handler, match, query_params):
    """List all primary and secondary tilesets with metadata."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    result = {"primary": [], "secondary": []}

    for tier in ("primary", "secondary"):
        tier_dir = os.path.join(game_path, "data", "tilesets", tier)
        if not os.path.isdir(tier_dir):
            continue
        for name in sorted(os.listdir(tier_dir)):
            ts_dir = os.path.join(tier_dir, name)
            if not os.path.isdir(ts_dir):
                continue

            info = {"name": name, "display": name.replace("_", " ").title()}

            # Metatile count
            mt_path = os.path.join(ts_dir, "metatiles.bin")
            if os.path.isfile(mt_path):
                size = os.path.getsize(mt_path)
                info["metatile_count"] = size // 24  # 12 tiles × 2 bytes
            else:
                info["metatile_count"] = 0

            # Tile count (from tiles.png dimensions or 4bpp size)
            info["tile_count"] = _count_tiles(ts_dir)

            result[tier].append(info)

    return ok_response(result)


def _count_tiles(ts_dir):
    """Estimate tile count from tiles.png or tiles.4bpp."""
    # Try tiles.4bpp (32 bytes per 8×8 tile at 4bpp)
    for name in ("tiles.4bpp", "tiles.4bpp.lz", "tiles.4bpp.fastSmol"):
        path = os.path.join(ts_dir, name)
        if os.path.isfile(path):
            if name == "tiles.4bpp":
                return os.path.getsize(path) // 32
            # Compressed — can't easily determine, fall through
            break
    return 0


# ---------------------------------------------------------------------------
# POST /api/tilesets/<name>/composition/save — save tile refs
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/tilesets/(?P<name>[A-Za-z0-9_]+)/composition/save")
def handle_composition_save(handler, match, query_params):
    """Save metatile tile ref changes to metatiles.bin.

    Body: {"changes": [{"id": int, "tiles": [{"tile":int, "hflip":bool,
           "vflip":bool, "palette":int} × 12]}, ...]}
    """
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

    # Read current metatiles.bin
    try:
        mt_path = _safe_path(ts_dir, "metatiles.bin")
    except ValueError:
        return error_response("Invalid tileset path", 400)

    if not os.path.isfile(mt_path):
        return error_response(
            f"metatiles.bin not found for {name}", 404,
        )

    try:
        with open(mt_path, "rb") as f:
            mt_data = bytearray(f.read())
    except OSError as e:
        return error_response(f"Cannot read metatiles.bin: {e}", 500)

    stride = 24  # 12 u16 entries per metatile
    num_metatiles = len(mt_data) // stride

    # Validate all changes
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

        tiles = change.get("tiles")
        if not isinstance(tiles, list) or len(tiles) != 12:
            return error_response(
                f"Change for id {mt_id}: 'tiles' must be a list of 12 entries",
                400,
            )

        for i, t in enumerate(tiles):
            if not isinstance(t, dict):
                return error_response(
                    f"Change for id {mt_id}, tile {i}: must be an object",
                    400,
                )
            tile_num = t.get("tile", 0)
            palette = t.get("palette", 0)
            if not isinstance(tile_num, int) or tile_num < 0 or tile_num > 1023:
                return error_response(
                    f"Change for id {mt_id}, tile {i}: "
                    f"tile index must be 0-1023, got {tile_num!r}",
                    400,
                )
            if not isinstance(palette, int) or palette < 0 or palette > 15:
                return error_response(
                    f"Change for id {mt_id}, tile {i}: "
                    f"palette must be 0-15, got {palette!r}",
                    400,
                )

    # Auto-snapshot before writing
    auto_snapshot_before_save(ts_dir, name)

    # Apply changes
    count = 0
    for change in changes:
        mt_id = change["id"]
        mt_off = mt_id * stride
        tiles = change["tiles"]

        for i, t in enumerate(tiles):
            tile_num = t.get("tile", 0) & 0x3FF      # 10 bits
            hflip = 1 if t.get("hflip", False) else 0  # bit 10
            vflip = 1 if t.get("vflip", False) else 0  # bit 11
            palette = (t.get("palette", 0) & 0xF)      # 4 bits

            val = tile_num | (hflip << 10) | (vflip << 11) | (palette << 12)
            struct.pack_into("<H", mt_data, mt_off + i * 2, val)

        count += 1

    # Atomic write
    dir_path = os.path.dirname(mt_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(mt_data)
        os.replace(tmp_path, mt_path)
    except OSError as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return error_response(f"Failed to write metatiles.bin: {e}", 500)

    return ok_response({"saved": count})


# ---------------------------------------------------------------------------
# PNG encoder (indexed, 4-bit or 8-bit)
# ---------------------------------------------------------------------------

def _encode_indexed_png(width, height, pixels, palette_rgb):
    """Encode pixel data as an indexed PNG (color type 3).

    *pixels* is a bytes/bytearray of length width*height, one byte per pixel
    (palette indices 0-15).  *palette_rgb* is a list of [r,g,b] triples.
    Returns the PNG file content as bytes.
    """

    def _chunk(chunk_type, data):
        """Build a PNG chunk: length + type + data + CRC."""
        raw = chunk_type + data
        crc = zlib.crc32(raw) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + raw + struct.pack(">I", crc)

    # Determine bit depth: use 4-bit if all indices fit
    max_idx = max(pixels) if pixels else 0
    bit_depth = 4 if max_idx < 16 else 8

    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, bit_depth, 3, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)

    # PLTE (up to 16 entries for 4-bit)
    num_entries = min(len(palette_rgb), 1 << bit_depth)
    plte_data = bytearray()
    for i in range(num_entries):
        c = palette_rgb[i] if i < len(palette_rgb) else [0, 0, 0]
        plte_data.extend([c[0] & 0xFF, c[1] & 0xFF, c[2] & 0xFF])
    # Pad to at least required number of entries
    while len(plte_data) < num_entries * 3:
        plte_data.extend([0, 0, 0])
    plte = _chunk(b"PLTE", bytes(plte_data))

    # tRNS — mark index 0 as transparent
    trns = _chunk(b"tRNS", b"\x00")

    # IDAT — filtered scanlines
    raw_lines = bytearray()
    for y in range(height):
        raw_lines.append(0)  # filter type 0 (None)
        row_start = y * width
        if bit_depth == 4:
            # Pack two pixels per byte
            for x in range(0, width, 2):
                hi = pixels[row_start + x] & 0xF
                lo = pixels[row_start + x + 1] & 0xF if x + 1 < width else 0
                raw_lines.append((hi << 4) | lo)
        else:
            raw_lines.extend(pixels[row_start : row_start + width])

    compressed = zlib.compress(bytes(raw_lines))
    idat = _chunk(b"IDAT", compressed)

    # IEND
    iend = _chunk(b"IEND", b"")

    # Assemble PNG
    sig = b'\x89PNG\r\n\x1a\n'
    return sig + ihdr + plte + trns + idat + iend


def _read_png_palette(png_path):
    """Extract the PLTE chunk from a PNG file. Returns [[r,g,b], ...]."""
    try:
        with open(png_path, "rb") as f:
            data = f.read()
    except OSError:
        return []

    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return []

    pos = 8
    while pos < len(data) - 4:
        chunk_len = struct.unpack_from(">I", data, pos)[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + chunk_len]
        pos += 12 + chunk_len

        if chunk_type == b"PLTE":
            colors = []
            for i in range(0, len(chunk_data), 3):
                colors.append([chunk_data[i], chunk_data[i+1], chunk_data[i+2]])
            return colors
        elif chunk_type == b"IEND":
            break

    return []


# ---------------------------------------------------------------------------
# POST /api/tilesets/<name>/tiles/save — save modified tile pixels
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/tilesets/(?P<name>[A-Za-z0-9_]+)/tiles/save")
def handle_tiles_save(handler, match, query_params):
    """Save modified tile pixel data back to tiles.png.

    Body: {"tiles": {"<globalTileIndex>": [64 palette indices], ...}}
    Each tile is 8×8 = 64 pixels, values 0-15.
    """
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

    tile_changes = body.get("tiles")
    if not isinstance(tile_changes, dict) or not tile_changes:
        return error_response("'tiles' must be a non-empty object", 400)

    # Read current tiles.png
    try:
        png_path = os.path.join(ts_dir, "tiles.png")
    except (ValueError, TypeError):
        return error_response("Invalid tileset path", 400)

    if not os.path.isfile(png_path):
        return error_response(f"tiles.png not found for {name}", 404)

    from torch.web.api_metatiles import _decode_indexed_png
    width, height, pixels = _decode_indexed_png(png_path)
    if not pixels:
        return error_response("Could not decode tiles.png", 500)

    pixels = bytearray(pixels)  # make mutable
    palette = _read_png_palette(png_path)
    tilesPerRow = width // 8

    # Auto-snapshot before writing
    auto_snapshot_before_save(ts_dir, name)

    # Apply changes
    count = 0
    for idx_str, pixel_data in tile_changes.items():
        try:
            tile_idx = int(idx_str)
        except (ValueError, TypeError):
            return error_response(f"Invalid tile index: {idx_str!r}", 400)

        if not isinstance(pixel_data, list) or len(pixel_data) != 64:
            return error_response(
                f"Tile {tile_idx}: pixel data must be array of 64 values", 400)

        # Calculate position in pixel array
        tileCol = tile_idx % tilesPerRow
        tileRow = tile_idx // tilesPerRow
        baseX = tileCol * 8
        baseY = tileRow * 8

        if baseY + 8 > height or baseX + 8 > width:
            return error_response(
                f"Tile {tile_idx} out of bounds for {width}×{height} image", 400)

        for py in range(8):
            for px in range(8):
                val = pixel_data[py * 8 + px]
                if not isinstance(val, int) or val < 0 or val > 15:
                    return error_response(
                        f"Tile {tile_idx}: pixel values must be 0-15", 400)
                pixels[(baseY + py) * width + (baseX + px)] = val

        count += 1

    # Encode and write new PNG
    png_data = _encode_indexed_png(width, height, pixels, palette)

    fd, tmp_path = tempfile.mkstemp(dir=ts_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(png_data)
        os.replace(tmp_path, png_path)
    except OSError as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return error_response(f"Failed to write tiles.png: {e}", 500)

    # Delete compiled tile files so the build regenerates from tiles.png
    for compiled in ("tiles.4bpp", "tiles.4bpp.lz", "tiles.4bpp.fastSmol"):
        cp = os.path.join(ts_dir, compiled)
        if os.path.isfile(cp):
            try:
                os.unlink(cp)
            except OSError:
                pass

    return ok_response({"saved": count})


# ---------------------------------------------------------------------------
# Tileset snapshot system
# ---------------------------------------------------------------------------

# Snapshot files: the 3 files that define a tileset's visual state
_SNAPSHOT_FILES = ("metatiles.bin", "metatile_attributes.bin", "tiles.png")
_MAX_ROLLING = 3  # number of rolling snapshots to keep

def _snapshot_dir():
    """Return the base snapshot directory, creating it if needed."""
    home = os.path.expanduser("~")
    base = os.path.join(home, ".config", "torch", "tileset_snapshots")
    os.makedirs(base, exist_ok=True)
    return base


def _tileset_snapshot_dir(name):
    """Return the snapshot directory for a specific tileset."""
    d = os.path.join(_snapshot_dir(), name)
    os.makedirs(d, exist_ok=True)
    return d


def _create_snapshot(ts_dir, name, label):
    """Create a snapshot of the tileset files.

    *label* is used as a subdirectory name (e.g. "original", "rolling_001").
    Returns True on success.
    """
    snap_dir = os.path.join(_tileset_snapshot_dir(name), label)
    os.makedirs(snap_dir, exist_ok=True)

    for fname in _SNAPSHOT_FILES:
        src = os.path.join(ts_dir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(snap_dir, fname))

    # Write a timestamp file
    with open(os.path.join(snap_dir, ".timestamp"), "w") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S"))

    return True


def _ensure_original(ts_dir, name):
    """Ensure the 'original' snapshot exists. Only created once."""
    orig_dir = os.path.join(_tileset_snapshot_dir(name), "original")
    if os.path.isdir(orig_dir) and any(
        os.path.isfile(os.path.join(orig_dir, f)) for f in _SNAPSHOT_FILES
    ):
        return  # already exists
    _create_snapshot(ts_dir, name, "original")


def _create_rolling_snapshot(ts_dir, name):
    """Create a rolling snapshot, rotating old ones. Keeps _MAX_ROLLING."""
    snap_base = _tileset_snapshot_dir(name)

    # Find existing rolling snapshots
    existing = sorted([
        d for d in os.listdir(snap_base)
        if d.startswith("rolling_") and os.path.isdir(os.path.join(snap_base, d))
    ])

    # Rotate: delete oldest if at limit
    while len(existing) >= _MAX_ROLLING:
        oldest = existing.pop(0)
        shutil.rmtree(os.path.join(snap_base, oldest), ignore_errors=True)

    # Create new rolling snapshot with timestamp-based name
    label = f"rolling_{time.strftime('%Y%m%d_%H%M%S')}"
    _create_snapshot(ts_dir, name, label)


def auto_snapshot_before_save(ts_dir, name):
    """Called before any save operation. Ensures original + creates rolling."""
    _ensure_original(ts_dir, name)
    _create_rolling_snapshot(ts_dir, name)


# ---------------------------------------------------------------------------
# GET /api/tilesets/<name>/snapshots — list available snapshots
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/tilesets/(?P<name>[A-Za-z0-9_]+)/snapshots")
def handle_snapshots_list(handler, match, query_params):
    """List all snapshots for a tileset."""
    name = match.group("name")
    snap_base = _tileset_snapshot_dir(name)

    snapshots = []
    if os.path.isdir(snap_base):
        for entry in sorted(os.listdir(snap_base)):
            snap_path = os.path.join(snap_base, entry)
            if not os.path.isdir(snap_path):
                continue

            ts_file = os.path.join(snap_path, ".timestamp")
            timestamp = ""
            if os.path.isfile(ts_file):
                try:
                    with open(ts_file) as f:
                        timestamp = f.read().strip()
                except OSError:
                    pass

            files = [f for f in _SNAPSHOT_FILES
                     if os.path.isfile(os.path.join(snap_path, f))]

            is_original = entry == "original"
            label = "Original (first seen)" if is_original else timestamp or entry

            snapshots.append({
                "id": entry,
                "label": label,
                "timestamp": timestamp,
                "is_original": is_original,
                "files": files,
            })

    # Sort: original first, then rolling newest first
    orig = [s for s in snapshots if s["is_original"]]
    rolling = sorted([s for s in snapshots if not s["is_original"]],
                     key=lambda s: s["id"], reverse=True)

    return ok_response({"snapshots": orig + rolling})


# ---------------------------------------------------------------------------
# POST /api/tilesets/<name>/restore — restore from a snapshot
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/tilesets/(?P<name>[A-Za-z0-9_]+)/restore")
def handle_snapshot_restore(handler, match, query_params):
    """Restore a tileset from a snapshot."""
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

    snapshot_id = body.get("snapshot_id")
    if not snapshot_id or not isinstance(snapshot_id, str):
        return error_response("'snapshot_id' is required", 400)

    snap_path = os.path.join(_tileset_snapshot_dir(name), snapshot_id)
    if not os.path.isdir(snap_path):
        return error_response(f"Snapshot not found: {snapshot_id}", 404)

    # Snapshot current state before restoring
    _create_rolling_snapshot(ts_dir, name)

    # Restore files
    restored = []
    for fname in _SNAPSHOT_FILES:
        src = os.path.join(snap_path, fname)
        dst = os.path.join(ts_dir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            restored.append(fname)

    # Delete compiled files so build regenerates
    for compiled in ("tiles.4bpp", "tiles.4bpp.lz", "tiles.4bpp.fastSmol"):
        cp = os.path.join(ts_dir, compiled)
        if os.path.isfile(cp):
            try:
                os.unlink(cp)
            except OSError:
                pass

    return ok_response({
        "restored": len(restored),
        "files": restored,
        "from_snapshot": snapshot_id,
    })
