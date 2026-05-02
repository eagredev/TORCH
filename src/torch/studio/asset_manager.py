"""Asset Manager — import and register custom game assets.

Provides a framework for importing assets (PNGs, MIDIs, etc.) into a
pokeemerald-expansion project.  Supports trainer front sprites, overworld
NPC sprites, music tracks, and sound effects; additional asset types can
be added to ASSET_TYPES.

CLI entry: torch assets
"""
# TORCH_MODULE: Asset Manager
# TORCH_GROUP: Data

import hashlib
import os
import re
import shutil
import struct
import subprocess

from torch.colours import GOLD, WHITE, CYAN, GREEN, RED, DIM, RST, BAR
from torch.ui import print_logo, clear_screen, _offer_build, _k
from torch.filewriter import _write_atomic

ASSET_VERSION = "0.1.0"


# ============================================================
# IMPORT TRANSACTION — rollback on pipeline failure
# ============================================================

class _ImportTransaction:
    """Track file mutations during an import pipeline for rollback on failure.

    Usage:
        txn = _ImportTransaction()
        txn.track_create(new_file)        # will delete on rollback
        txn.track_modify(existing_file)   # snapshots content, restores on rollback
        ...
        if error:
            txn.rollback()                # undo in LIFO order
        else:
            txn.commit()                  # discard snapshots
    """

    def __init__(self):
        self._created = []         # files to delete on rollback
        self._modified = {}        # filepath -> original_content (bytes or str)
        self._order = []           # operation log for LIFO ordering

    def track_create(self, filepath):
        """Register a file that was created during this transaction."""
        self._created.append(filepath)
        self._order.append(("create", filepath))

    def track_modify(self, filepath):
        """Snapshot a file before first mutation.  No-op if already tracked."""
        if filepath in self._modified:
            return
        try:
            with open(filepath, "rb") as f:
                self._modified[filepath] = f.read()
        except OSError:
            self._modified[filepath] = None  # file didn't exist
        self._order.append(("modify", filepath))

    def rollback(self):
        """Undo all tracked operations in LIFO order."""
        # Process in reverse order
        seen_create = set()
        seen_modify = set()
        for op_type, filepath in reversed(self._order):
            if op_type == "create" and filepath not in seen_create:
                seen_create.add(filepath)
                try:
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                except OSError:
                    pass
            elif op_type == "modify" and filepath not in seen_modify:
                seen_modify.add(filepath)
                original = self._modified.get(filepath)
                if original is None:
                    # File didn't exist before — delete it
                    try:
                        if os.path.isfile(filepath):
                            os.remove(filepath)
                    except OSError:
                        pass
                else:
                    try:
                        with open(filepath, "wb") as f:
                            f.write(original)
                    except OSError:
                        pass
        self._created.clear()
        self._modified.clear()
        self._order.clear()

    def commit(self):
        """Discard all snapshots — transaction succeeded."""
        self._created.clear()
        self._modified.clear()
        self._order.clear()


# ============================================================
# PNG HEADER PARSER (stdlib-only — no PIL/Pillow)
# ============================================================

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _parse_png_info(filepath):
    """Read basic PNG info without external dependencies.

    Parses the IHDR chunk for dimensions/bit depth/colour type and the
    PLTE chunk for palette entry count.  No pixel decompression.

    Returns dict with keys: width, height, bit_depth, color_type,
    palette_size (0 if no PLTE chunk).  Returns None on error.
    """
    try:
        with open(filepath, "rb") as f:
            sig = f.read(8)
            if sig != _PNG_SIGNATURE:
                return None

            result = {
                "width": 0,
                "height": 0,
                "bit_depth": 0,
                "color_type": 0,
                "palette_size": 0,
                "has_trns": False,
            }

            while True:
                header = f.read(8)
                if len(header) < 8:
                    break
                chunk_len = struct.unpack(">I", header[:4])[0]
                chunk_type = header[4:8]

                if chunk_type == b"IHDR":
                    if chunk_len < 13:
                        return None
                    ihdr_data = f.read(13)
                    if len(ihdr_data) < 13:
                        return None
                    w, h = struct.unpack(">II", ihdr_data[:8])
                    result["width"] = w
                    result["height"] = h
                    result["bit_depth"] = ihdr_data[8]
                    result["color_type"] = ihdr_data[9]
                    # Skip rest of chunk + CRC
                    remaining = chunk_len - 13
                    if remaining > 0:
                        f.seek(remaining, 1)
                    f.seek(4, 1)  # CRC
                    continue

                if chunk_type == b"PLTE":
                    # Each palette entry is 3 bytes (R, G, B)
                    if chunk_len % 3 != 0:
                        return None
                    result["palette_size"] = chunk_len // 3
                    f.seek(chunk_len + 4, 1)  # data + CRC
                    continue

                if chunk_type == b"tRNS":
                    result["has_trns"] = True
                    f.seek(chunk_len + 4, 1)  # data + CRC
                    continue

                if chunk_type == b"IDAT":
                    # No need to read past image data
                    break

                if chunk_type == b"IEND":
                    break

                # Skip unknown chunks
                f.seek(chunk_len + 4, 1)  # data + CRC

            return result
    except (OSError, struct.error):
        return None


def _validate_png_structural_integrity(filepath):
    """Verify essential PNG chunks are present before import.

    Checks that IHDR, IDAT, and IEND chunks exist.  For indexed PNGs
    (color_type == 3), also requires a PLTE chunk.

    Returns (ok, message).
    """
    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except OSError:
        return False, "Cannot read file"

    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        return False, "Not a valid PNG file (bad signature)"

    has_ihdr = False
    has_plte = False
    has_idat = False
    has_iend = False
    color_type = None

    pos = 8
    while pos + 8 <= len(data):
        if pos + 4 > len(data):
            break
        chunk_len = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_end = pos + 12 + chunk_len

        if chunk_type == b"IHDR":
            has_ihdr = True
            if chunk_len >= 13 and pos + 8 + 13 <= len(data):
                color_type = data[pos + 8 + 9]
        elif chunk_type == b"PLTE":
            has_plte = True
        elif chunk_type == b"IDAT":
            has_idat = True
        elif chunk_type == b"IEND":
            has_iend = True
            break

        if chunk_end > len(data):
            break
        pos = chunk_end

    if not has_ihdr:
        return False, "Corrupt PNG: missing IHDR chunk"
    if color_type == 3 and not has_plte:
        return False, "Corrupt PNG: indexed image missing PLTE chunk"
    if not has_idat:
        return False, "Corrupt PNG: missing IDAT chunk (no image data)"
    if not has_iend:
        return False, "Corrupt PNG: missing IEND chunk (truncated file)"
    return True, "PNG structure valid"


def _sanitise_sprite_png(src, dest):
    """Copy a sprite PNG, stripping the tRNS chunk if present.

    The GBA uses palette index 0 as the transparent colour.  Indexed PNGs
    from some sources (notably pokefirered) include a tRNS chunk that marks
    palette index 0 as alpha-transparent.  The gbagfx converter doesn't
    handle this correctly, producing garbled tile data (repeated/missing
    frames at runtime).

    This function copies the PNG byte-for-byte but drops any tRNS chunk.
    If the PNG has no tRNS chunk, it's a straight copy.

    Returns True if a tRNS chunk was stripped, False if the file was
    copied unchanged.  Raises OSError on I/O failure.
    """
    with open(src, "rb") as f:
        data = f.read()

    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        # Not a PNG — copy as-is and let validation catch it
        shutil.copy2(src, dest)
        return False

    # Scan for a tRNS chunk
    pos = 8
    has_trns = False
    while pos + 8 <= len(data):
        chunk_len = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_end = pos + 12 + chunk_len  # len(4) + type(4) + data + crc(4)
        if chunk_type == b"tRNS":
            has_trns = True
            break
        if chunk_type == b"IEND":
            break
        pos = chunk_end

    if not has_trns:
        shutil.copy2(src, dest)
        return False

    # Rebuild the PNG without the tRNS chunk
    out = bytearray(data[:8])  # PNG signature
    pos = 8
    while pos + 8 <= len(data):
        chunk_len = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_end = pos + 12 + chunk_len
        if chunk_type != b"tRNS":
            out += data[pos:chunk_end]
        if chunk_type == b"IEND":
            break
        pos = chunk_end

    with open(dest, "wb") as f:
        f.write(out)
    # Preserve timestamps like shutil.copy2
    shutil.copystat(src, dest)
    return True


# ============================================================
# MANIFEST — TRACKING IMPORTED ASSETS
# ============================================================

def _manifest_path(import_base):
    """Return the path to the manifest file."""
    return os.path.join(import_base, "imports.manifest")


def _read_manifest(import_base):
    """Read the manifest file into {type_key: set(filenames)}.

    Returns empty dict if manifest doesn't exist.
    """
    path = _manifest_path(import_base)
    if not os.path.isfile(path):
        return {}
    result = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                type_key, filename = line.split(":", 1)
                type_key = type_key.strip()
                filename = filename.strip()
                if type_key and filename:
                    result.setdefault(type_key, set()).add(filename)
    except OSError:
        pass
    return result


def _write_manifest(import_base, manifest):
    """Write the full manifest atomically.

    manifest: {type_key: set(filenames)}
    """
    path = _manifest_path(import_base)
    lines = ["# TORCH asset manifest\n", "# type:filename\n"]
    for type_key in sorted(manifest):
        for filename in sorted(manifest[type_key]):
            lines.append(f"{type_key}:{filename}\n")
    _write_atomic(path, lines)


def _append_manifest(import_base, type_key, filename):
    """Append a single entry to the manifest after successful import."""
    path = _manifest_path(import_base)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        # Create with header if new
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write("# TORCH asset manifest\n")
                f.write("# type:filename\n")
                f.write(f"{type_key}:{filename}\n")
        else:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{type_key}:{filename}\n")
    except OSError:
        pass


def _backfill_manifest(import_base, game_path):
    """Auto-populate manifest for already-imported assets.

    Scans the import dir for files whose constants already exist in game
    headers, and records them so removal detection works.
    Returns the populated manifest.
    """
    manifest = _read_manifest(import_base)
    changed = False
    for type_key, atype in ASSET_TYPES.items():
        existing = _detect_already_imported(type_key, game_path)
        if not existing:
            continue
        files = _scan_import_dir(type_key, import_base)
        const_fn = atype["const_from_file"]
        for fpath in files:
            fname = os.path.basename(fpath)
            const = const_fn(fname)
            if const in existing:
                current = manifest.get(type_key, set())
                if fname not in current:
                    manifest.setdefault(type_key, set()).add(fname)
                    changed = True
    if changed:
        _write_manifest(import_base, manifest)
    return manifest


# ============================================================
# FILE HASHING
# ============================================================

def _file_hash(filepath):
    """Return SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _hash_sanitised_png(filepath):
    """Hash a PNG after stripping tRNS in memory.

    This lets us compare a source PNG (which may have tRNS) against a
    game-side copy (which had tRNS stripped during import) without
    false-positive "changed" results.
    """
    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except OSError:
        return None

    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        return hashlib.sha256(data).hexdigest()

    # Rebuild without tRNS
    out = bytearray(data[:8])
    pos = 8
    while pos + 8 <= len(data):
        chunk_len = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_end = pos + 12 + chunk_len
        if chunk_type != b"tRNS":
            out += data[pos:chunk_end]
        if chunk_type == b"IEND":
            break
        pos = chunk_end

    return hashlib.sha256(bytes(out)).hexdigest()


def _extract_gbapal_from_png(png_path, gbapal_path):
    """Extract palette from an indexed PNG and write as .gbapal file.

    Reads the PLTE chunk, converts each RGB888 entry to GBA BGR555
    (little-endian u16), pads to exactly 16 entries (32 bytes).
    Returns True on success.
    """
    try:
        with open(png_path, "rb") as f:
            data = f.read()
    except OSError:
        return False

    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        return False

    # Find PLTE chunk
    pos = 8
    plte_data = None
    while pos + 8 <= len(data):
        chunk_len = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        if chunk_type == b"PLTE":
            plte_data = data[pos + 8:pos + 8 + chunk_len]
            break
        if chunk_type == b"IEND":
            break
        pos += 12 + chunk_len

    if plte_data is None or len(plte_data) % 3 != 0:
        return False

    # Convert RGB888 -> GBA BGR555 (little-endian u16)
    num_colors = min(len(plte_data) // 3, 16)
    gba_pal = bytearray(32)  # 16 entries * 2 bytes, zero-padded
    for i in range(num_colors):
        r = plte_data[i * 3]
        g = plte_data[i * 3 + 1]
        b = plte_data[i * 3 + 2]
        # GBA uses 5-bit channels: BBBBBGGGGGRRRRR (little-endian)
        r5 = r >> 3
        g5 = g >> 3
        b5 = b >> 3
        color = (b5 << 10) | (g5 << 5) | r5
        struct.pack_into("<H", gba_pal, i * 2, color)

    try:
        os.makedirs(os.path.dirname(gbapal_path), exist_ok=True)
        with open(gbapal_path, "wb") as f:
            f.write(gba_pal)
    except OSError:
        return False
    return True


def _extract_jasc_pal_from_png(png_path, pal_path):
    """Extract palette from an indexed PNG and write as JASC-PAL file.

    JASC-PAL is the text format used by gbagfx as an alternative source.
    Returns True on success.
    """
    try:
        with open(png_path, "rb") as f:
            data = f.read()
    except OSError:
        return False

    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        return False

    pos = 8
    plte_data = None
    while pos + 8 <= len(data):
        chunk_len = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        if chunk_type == b"PLTE":
            plte_data = data[pos + 8:pos + 8 + chunk_len]
            break
        if chunk_type == b"IEND":
            break
        pos += 12 + chunk_len

    if plte_data is None or len(plte_data) % 3 != 0:
        return False

    num_colors = min(len(plte_data) // 3, 16)
    lines = ["JASC-PAL", "0100", "16"]
    for i in range(num_colors):
        r = plte_data[i * 3]
        g = plte_data[i * 3 + 1]
        b = plte_data[i * 3 + 2]
        lines.append(f"{r} {g} {b}")
    # Pad to 16 entries
    for _ in range(16 - num_colors):
        lines.append("0 0 0")

    try:
        os.makedirs(os.path.dirname(pal_path), exist_ok=True)
        with open(pal_path, "w", newline="\r\n") as f:
            f.write("\r\n".join(lines) + "\r\n")
    except OSError:
        return False
    return True


def _extract_plte_as_bgr555(png_path):
    """Extract palette from an indexed PNG as in-memory BGR555 bytearray.

    Same conversion as _extract_gbapal_from_png but returns (bytearray_32,
    num_colors) instead of writing to disk.  Returns (None, 0) on error.
    """
    try:
        with open(png_path, "rb") as f:
            data = f.read()
    except OSError:
        return None, 0

    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        return None, 0

    pos = 8
    plte_data = None
    while pos + 8 <= len(data):
        chunk_len = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        if chunk_type == b"PLTE":
            plte_data = data[pos + 8:pos + 8 + chunk_len]
            break
        if chunk_type == b"IEND":
            break
        pos += 12 + chunk_len

    if plte_data is None or len(plte_data) % 3 != 0:
        return None, 0

    num_colors = min(len(plte_data) // 3, 16)
    gba_pal = bytearray(32)
    for i in range(num_colors):
        r = plte_data[i * 3]
        g = plte_data[i * 3 + 1]
        b = plte_data[i * 3 + 2]
        r5 = r >> 3
        g5 = g >> 3
        b5 = b >> 3
        color = (b5 << 10) | (g5 << 5) | r5
        struct.pack_into("<H", gba_pal, i * 2, color)

    return gba_pal, num_colors


def _palettes_match(pal_a, pal_b, num_a, num_b):
    """Compare two 32-byte BGR555 palette bytearrays.

    Skips index 0 (transparent).  Compares indices 1 through
    min(num_a, num_b) - 1.  All compared entries must be identical
    (index-exact match, no re-indexing).

    Returns True if palettes match, False otherwise.
    """
    if pal_a is None or pal_b is None:
        return False
    count = min(num_a, num_b)
    if count <= 1:
        # Only index 0 (transparent) — nothing to compare
        return True
    # Compare indices 1 through count-1 (skip index 0)
    for i in range(1, count):
        offset = i * 2
        if pal_a[offset:offset + 2] != pal_b[offset:offset + 2]:
            return False
    return True


def _read_gbapal_file(gbapal_path):
    """Read a .gbapal file and return (bytearray_32, num_colors).

    Returns (None, 0) if the file can't be read.
    """
    try:
        with open(gbapal_path, "rb") as f:
            data = f.read()
    except OSError:
        return None, 0
    if len(data) != 32:
        return None, 0
    # Count non-zero entries (colors actually defined)
    num = 0
    for i in range(16):
        if data[i * 2:i * 2 + 2] != b"\x00\x00":
            num = i + 1
    # At minimum 1 (even all-black counts as 1 entry)
    return bytearray(data), max(num, 1)


def _find_palette_slot_for_tag(info_h_path, tag_name):
    """Find the paletteSlot used by an existing struct with this palette tag.

    Scans object_event_graphics_info.h for a struct whose .paletteTag
    matches tag_name, then extracts its .paletteSlot value.

    Returns the slot string (e.g. 'PALSLOT_NPC_SPECIAL') or None.
    """
    try:
        with open(info_h_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None

    # Find a struct block containing this palette tag
    pat = re.compile(
        r"gObjectEventGraphicsInfo_\w+\s*=\s*\{(.*?)\};",
        re.DOTALL)
    for m in pat.finditer(content):
        body = m.group(1)
        if f".paletteTag = {tag_name}" not in body:
            continue
        slot_m = re.search(r"\.paletteSlot\s*=\s*(\w+)", body)
        if slot_m:
            return slot_m.group(1)
    return None


def _find_matching_palette(png_path, game_path):
    """Find an existing palette that matches the incoming sprite's colours.

    Returns (match_type, tag_name, slot_name):
      - ("shared", "OBJ_EVENT_PAL_TAG_NPC_N", "PALSLOT_NPC_N") for shared match
      - ("custom", tag_name, slot) for existing custom palette match
      - ("none", None, None) for no match
    """
    incoming_pal, incoming_count = _extract_plte_as_bgr555(png_path)
    if incoming_pal is None:
        return "none", None, None

    pal_dir = os.path.join(game_path, "graphics", "object_events", "palettes")

    # Step 1: Check shared NPC palettes (npc_1 through npc_4)
    for n in range(1, 5):
        gbapal_path = os.path.join(pal_dir, f"npc_{n}.gbapal")
        ref_pal, ref_count = _read_gbapal_file(gbapal_path)
        if ref_pal is not None and _palettes_match(incoming_pal, ref_pal,
                                                   incoming_count, ref_count):
            return ("shared",
                    f"OBJ_EVENT_PAL_TAG_NPC_{n}",
                    f"PALSLOT_NPC_{n}")

    # Step 2: Check existing TORCH-registered custom palettes
    event_obj_h = os.path.join(game_path, "include", "constants", "event_objects.h")
    graphics_h = os.path.join(game_path, "src", "data", "object_events",
                              "object_event_graphics.h")
    info_h = os.path.join(game_path, "src", "data", "object_events",
                          "object_event_graphics_info.h")

    try:
        with open(event_obj_h, encoding="utf-8", errors="replace") as f:
            eo_content = f.read()
    except OSError:
        return "none", None, None

    # Find custom tags in TORCH range (0x1125-0x114F, above DYNAMIC at 0x1124)
    tag_pat = re.compile(
        r"#define\s+(OBJ_EVENT_PAL_TAG_\w+)\s+(0x[0-9A-Fa-f]+)")
    custom_tags = []
    for m in tag_pat.finditer(eo_content):
        tag_name = m.group(1)
        tag_val = int(m.group(2), 16)
        if 0x1125 <= tag_val <= 0x114F:
            custom_tags.append(tag_name)

    if not custom_tags:
        return "none", None, None

    # Read graphics.h to find .gbapal paths from INCBIN lines
    try:
        with open(graphics_h, encoding="utf-8", errors="replace") as f:
            gfx_content = f.read()
    except OSError:
        return "none", None, None

    # For each custom tag, find the palette data name and its .gbapal file
    for tag_name in custom_tags:
        # Derive camel name from tag: OBJ_EVENT_PAL_TAG_ROCKET_M -> RocketM
        suffix = tag_name.replace("OBJ_EVENT_PAL_TAG_", "")
        # Convert UPPER_SNAKE to CamelCase
        camel = "".join(part.capitalize() for part in suffix.split("_") if part)
        pal_var = f"gObjectEventPal_{camel}"

        # Find the INCBIN line for this palette
        incbin_pat = re.compile(
            rf"{re.escape(pal_var)}\[\]\s*=\s*INCBIN_U(?:16|32)\(\"(.*?)\"\)")
        incbin_m = incbin_pat.search(gfx_content)
        if not incbin_m:
            continue
        rel_path = incbin_m.group(1)
        gbapal_path = os.path.join(game_path, rel_path)
        if not os.path.isfile(gbapal_path):
            continue

        ref_pal, ref_count = _read_gbapal_file(gbapal_path)
        if ref_pal is not None and _palettes_match(incoming_pal, ref_pal,
                                                   incoming_count, ref_count):
            # Found a matching custom palette — find its slot
            slot = _find_palette_slot_for_tag(info_h, tag_name)
            if slot is None:
                slot = "PALSLOT_NPC_SPECIAL"
            return "custom", tag_name, slot

    return "none", None, None


def _has_own_custom_palette(camel_name, game_path):
    """Check whether this sprite has its own custom palette tag registered.

    Returns True if the sprite's derived palette tag (OBJ_EVENT_PAL_TAG_*)
    exists in event_objects.h within the TORCH range (0x1125-0x114F).
    """
    tag_name = _derive_palette_tag_name(camel_name)
    event_obj_h = os.path.join(game_path, "include", "constants", "event_objects.h")
    try:
        with open(event_obj_h, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return False
    # Check if the tag exists AND is in the TORCH range
    pat = re.compile(
        rf"#define\s+{re.escape(tag_name)}\s+(0x[0-9A-Fa-f]+)")
    m = pat.search(content)
    if not m:
        return False
    val = int(m.group(1), 16)
    return 0x1125 <= val <= 0x114F


def _count_palette_users(info_h_path, tag_name, exclude=None):
    """Count how many graphics info structs reference a palette tag.

    exclude: CamelCase sprite name to skip (the one being removed).
    Returns the count of OTHER sprites using this tag.
    """
    try:
        with open(info_h_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return 0

    count = 0
    struct_pat = re.compile(
        r"gObjectEventGraphicsInfo_(\w+)\s*=\s*\{(.*?)\};", re.DOTALL)
    for m in struct_pat.finditer(content):
        name = m.group(1)
        if exclude and name == exclude:
            continue
        body = m.group(2)
        tag_m = re.search(r"\.paletteTag\s*=\s*(\w+)", body)
        if tag_m and tag_m.group(1) == tag_name:
            count += 1
    return count


# ============================================================
# NAME DERIVATION
# ============================================================

def _derive_trainer_pic_name(filename):
    """Convert a filename to CamelCase for C identifiers.

    Strips common suffixes (_front_pic, _back_pic) before conversion.

    'rival_dawn.png' -> 'RivalDawn'
    'gym_leader_kai.png' -> 'GymLeaderKai'
    'elite-four-nova.png' -> 'EliteFourNova'
    'rocket_grunt_m_front_pic.png' -> 'RocketGruntM'
    """
    stem = os.path.splitext(filename)[0]
    # Normalise separators to underscores
    stem = stem.replace("-", "_")
    # Strip common non-standard suffixes
    lower = stem.lower()
    for suffix in ("_front_pic", "_back_pic"):
        if lower.endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    # Split on underscores and capitalise each part
    return "".join(part.capitalize() for part in stem.split("_") if part)


def _derive_trainer_pic_const(camel_name):
    """Convert CamelCase to UPPER_SNAKE for #define constants.

    'RivalDawn' -> 'TRAINER_PIC_RIVAL_DAWN'
    'GymLeaderKai' -> 'TRAINER_PIC_GYM_LEADER_KAI'
    'RocketGruntM' -> 'TRAINER_PIC_ROCKET_GRUNT_M'
    """
    # Two-pass: first split runs of uppercase (e.g. MFront -> M_Front),
    # then split lowercase/digit -> uppercase transitions.
    snake = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", camel_name)
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", snake)
    return "TRAINER_PIC_" + snake.upper()


def _derive_file_stem(filename):
    """Convert filename to lowercase_underscore for file paths.

    Strips common suffixes (_front_pic, _back_pic) that don't belong in
    game asset names — vanilla sprites use e.g. 'aqua_grunt_m.png', not
    'aqua_grunt_m_front_pic.png'.

    'rival_dawn.png' -> 'rival_dawn'
    'Rival-Dawn.png' -> 'rival_dawn'
    'rocket_grunt_m_front_pic.png' -> 'rocket_grunt_m'
    """
    stem = os.path.splitext(filename)[0]
    stem = stem.replace("-", "_")
    stem = stem.lower()
    # Strip common non-standard suffixes
    for suffix in ("_front_pic", "_back_pic"):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    return stem


def _camel_to_upper_snake(camel_name):
    """Convert CamelCase to UPPER_SNAKE.

    'RivalDawn' -> 'RIVAL_DAWN'
    'GymLeaderKai' -> 'GYM_LEADER_KAI'
    'RocketGruntM' -> 'ROCKET_GRUNT_M'
    """
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", camel_name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).upper()


def _upper_snake_to_camel(s):
    """Convert UPPER_SNAKE to CamelCase.

    'RIVAL_DAWN' -> 'RivalDawn'
    'GYM_LEADER_KAI' -> 'GymLeaderKai'
    """
    return "".join(part.capitalize() for part in s.lower().split("_") if part)


def _derive_overworld_name(filename):
    """Convert a filename to CamelCase for overworld C identifiers.

    Same logic as trainer names — CamelCase from underscore/hyphen.
    'my_npc.png' -> 'MyNpc'
    'police_officer.png' -> 'PoliceOfficer'
    """
    return _derive_trainer_pic_name(filename)


def _derive_overworld_const(camel_name):
    """Convert CamelCase to OBJ_EVENT_GFX_UPPER_SNAKE.

    'MyNpc' -> 'OBJ_EVENT_GFX_MY_NPC'
    'PoliceOfficer' -> 'OBJ_EVENT_GFX_POLICE_OFFICER'
    """
    return "OBJ_EVENT_GFX_" + _camel_to_upper_snake(camel_name)


# ============================================================
# TRAINER SPRITE VALIDATION
# ============================================================

def _validate_trainer_sprite(filepath):
    """Validate a PNG for use as a trainer front sprite.

    Returns (ok, message) tuple.
    ok=True: sprite is valid.  message describes dimensions/colours.
    ok=False: sprite is invalid.  message describes the problem.
    """
    info = _parse_png_info(filepath)
    if info is None:
        return False, "Not a valid PNG file"

    w, h = info["width"], info["height"]
    if w != 64 or h != 64:
        return False, f"Wrong dimensions: {w}x{h} (need 64x64)"

    # Color type 3 = indexed colour (palette-based), which is what the GBA needs.
    # Color type 2 = truecolour (no palette) — the build system can convert,
    # but we still need the palette to have <= 16 unique colours.
    ct = info["color_type"]
    trns_note = " (tRNS → will fix)" if info.get("has_trns") else ""
    if ct == 3:
        # Indexed — check palette size directly
        pal = info["palette_size"]
        if pal > 16:
            return False, f"Too many colours: {pal} (max 16)"
        return True, f"64x64, {pal} colours{trns_note}"
    elif ct in (0, 2, 4, 6):
        # Greyscale or truecolour — we can't count unique colours without
        # decompressing pixels (which we can't do stdlib-only).  Accept it
        # but warn the user.
        return True, f"64x64, non-indexed (colour type {ct}) — build may convert"
    else:
        return False, f"Unsupported PNG colour type: {ct}"


# ============================================================
# OVERWORLD SPRITE VALIDATION
# ============================================================

# Supported frame sizes: (pixel_width, pixel_height) -> (tile_w, tile_h)
_OW_FRAME_SIZES = {
    (16, 16): (2, 2),
    (16, 32): (2, 4),
    (32, 32): (4, 4),
    (64, 64): (8, 8),
}

# Standard frame counts for walking NPCs (used for disambiguation)
_STANDARD_FRAME_COUNTS = {9, 4, 1}

# Maximum overworld sprite dimensions — generous VRAM budget guards
_OW_MAX_TOTAL_TILES = 512   # 16KB per sprite, generous VRAM budget
_OW_MAX_WIDTH = 512
_OW_MAX_HEIGHT = 256


def _detect_overworld_frame_size(width, height):
    """Detect per-frame pixel dimensions from a spritesheet.

    Standard overworld sprites are laid out as horizontal strips:
    - 16x32 NPC: 144x32 (9 frames) or 64x32 (4 frames)
    - 16x16 small NPC: 144x16 (9 frames)
    - 32x32 large NPC: 288x32 (9 frames)

    When multiple frame sizes match, prefers the one that gives a
    standard frame count (9, 4, or 1).

    Returns (frame_w, frame_h, frame_count) or None on failure.
    """
    # Collect all matches where height == frame height
    candidates = []
    for (fw, fh) in _OW_FRAME_SIZES:
        if height == fh and width % fw == 0 and width >= fw:
            candidates.append((fw, fh, width // fw))

    if candidates:
        # Prefer standard frame count, then smallest frame width
        for c in candidates:
            if c[2] in _STANDARD_FRAME_COUNTS:
                return c
        return candidates[0]

    # Also support tall spritesheets (multiple rows)
    for (fw, fh) in _OW_FRAME_SIZES:
        if width % fw == 0 and height % fh == 0 and height > fh:
            cols = width // fw
            rows = height // fh
            return fw, fh, cols * rows
    return None


def _validate_overworld_sprite(filepath):
    """Validate a PNG for use as an overworld NPC sprite.

    Accepts spritesheets with standard frame sizes (16x16, 16x32,
    32x32, 64x64).  Dimensions must be exact multiples of the frame size.

    Returns (ok, message) tuple.
    """
    info = _parse_png_info(filepath)
    if info is None:
        return False, "Not a valid PNG file"

    w, h = info["width"], info["height"]

    # Reject obviously oversized sprites before frame detection
    if w > _OW_MAX_WIDTH:
        return False, f"Too wide: {w}px exceeds maximum {_OW_MAX_WIDTH}px"
    if h > _OW_MAX_HEIGHT:
        return False, f"Too tall: {h}px exceeds maximum {_OW_MAX_HEIGHT}px"

    result = _detect_overworld_frame_size(w, h)
    if result is None:
        return False, f"Unsupported dimensions: {w}x{h} (need multiples of a standard frame size)"

    fw, fh, frame_count = result

    # Check total tile count against VRAM budget
    total_tiles = (fw // 8) * (fh // 8) * frame_count
    if total_tiles > _OW_MAX_TOTAL_TILES:
        return False, f"Too large: {total_tiles} tiles exceeds GBA VRAM budget ({_OW_MAX_TOTAL_TILES} max)"

    ct = info["color_type"]
    trns_note = " (tRNS → will fix)" if info.get("has_trns") else ""
    if ct == 3:
        pal = info["palette_size"]
        if pal > 16:
            return False, f"Too many colours: {pal} (max 16)"
        return True, f"{w}x{h}, {fw}x{fh} frames, {frame_count}f, {pal} colours{trns_note}"
    elif ct in (0, 2, 4, 6):
        return True, f"{w}x{h}, {fw}x{fh} frames, {frame_count}f, non-indexed — build may convert"
    else:
        return False, f"Unsupported PNG colour type: {ct}"


# ============================================================
# TRAINER SPRITE IMPORTER
# ============================================================

def _read_trainer_pic_count(trainers_const_path):
    """Read the current TRAINER_PIC_COUNT value from constants/trainers.h.

    Returns (count, line_number) or (None, None) on failure.
    """
    try:
        with open(trainers_const_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None, None

    pat = re.compile(r"^#define\s+TRAINER_PIC_COUNT\s+(\d+)")
    for i, line in enumerate(lines):
        m = pat.match(line)
        if m:
            return int(m.group(1)), i
    return None, None


def _is_already_imported(const_name, trainers_const_path):
    """Check if a TRAINER_PIC_* constant already exists (exact match)."""
    try:
        with open(trainers_const_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return False
    return bool(re.search(rf"^#define\s+{re.escape(const_name)}\s",
                          content, re.MULTILINE))


def _insert_incbin(trainers_h_path, camel_name, file_stem):
    """Insert INCBIN lines for a new trainer sprite into trainers.h.

    Inserts after the last gTrainerPalette_ line before the first
    gTrainerBackPic_ line.

    Returns True on success.
    """
    try:
        with open(trainers_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find the last front-pic palette line before back pics start
    last_palette_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^const\s+u8\s+gTrainerBackPic_", line):
            break
        if re.match(r"^const\s+u16\s+gTrainerPalette_\w+\[\]", line):
            last_palette_idx = i

    if last_palette_idx is None:
        return False

    new_lines = [
        "\n",
        f'const u32 gTrainerFrontPic_{camel_name}[] = INCBIN_U32("graphics/trainers/front_pics/{file_stem}.4bpp.smol");\n',
        f'const u16 gTrainerPalette_{camel_name}[] = INCBIN_U16("graphics/trainers/front_pics/{file_stem}.gbapal");\n',
    ]

    result = lines[:last_palette_idx + 1] + new_lines + lines[last_palette_idx + 1:]
    return _write_atomic(trainers_h_path, result)


def _insert_sprite_entry(trainers_h_path, const_name, camel_name):
    """Insert a TRAINER_SPRITE() entry into the gTrainerSprites[] array.

    Inserts before the closing '};' of the array.

    Returns True on success.
    """
    try:
        with open(trainers_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find 'const struct TrainerSprite gTrainerSprites[]' then its closing '};'
    in_array = False
    close_idx = None
    for i, line in enumerate(lines):
        if "gTrainerSprites" in line and "const" in line:
            in_array = True
        elif in_array and line.strip() == "};":
            close_idx = i
            break

    if close_idx is None:
        return False

    entry = f"    TRAINER_SPRITE({const_name}, gTrainerFrontPic_{camel_name}, gTrainerPalette_{camel_name}),\n"
    result = lines[:close_idx] + [entry] + lines[close_idx:]
    return _write_atomic(trainers_h_path, result)


def _insert_pic_constant(trainers_const_path, const_name):
    """Insert a new TRAINER_PIC_* constant and increment TRAINER_PIC_COUNT.

    Returns the assigned pic ID on success, or None on failure.
    """
    count, count_line = _read_trainer_pic_count(trainers_const_path)
    if count is None:
        return None

    try:
        with open(trainers_const_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    # Determine alignment — match existing defines
    new_define = f"#define {const_name:<38}{count}\n"
    new_count = f"#define TRAINER_PIC_COUNT{' ' * (38 - len('TRAINER_PIC_COUNT'))}{count + 1}\n"

    result = lines[:count_line] + [new_define] + lines[count_line + 1:]
    # The count line is now at count_line + 1 in the new list
    result.insert(count_line + 1, new_count)

    if not _write_atomic(trainers_const_path, result):
        return None
    return count


def _import_trainer_sprite(filepath, game_path):
    """Full trainer sprite registration pipeline with transaction rollback.

    1. Copy PNG to graphics/trainers/front_pics/
    2. Add INCBIN lines to src/data/graphics/trainers.h
    3. Add TRAINER_SPRITE entry to gTrainerSprites[] array
    4. Add constant to include/constants/trainers.h + increment count

    On failure at any step, rolls back all prior steps.

    Returns a result dict on success, or None on failure.
    """
    filename = os.path.basename(filepath)
    file_stem = _derive_file_stem(filename)
    camel_name = _derive_trainer_pic_name(filename)
    const_name = _derive_trainer_pic_const(camel_name)

    trainers_h = os.path.join(game_path, "src", "data", "graphics", "trainers.h")
    trainers_const = os.path.join(game_path, "include", "constants", "trainers.h")

    if not os.path.isfile(trainers_h):
        print(f"  {RED}Error:{RST} {trainers_h} not found")
        return None
    if not os.path.isfile(trainers_const):
        print(f"  {RED}Error:{RST} {trainers_const} not found")
        return None

    # PNG structural integrity check
    png_ok, png_msg = _validate_png_structural_integrity(filepath)
    if not png_ok:
        print(f"  {RED}Error:{RST} {png_msg}")
        return None

    # Check for duplicate
    if _is_already_imported(const_name, trainers_const):
        print(f"  {RED}Error:{RST} {const_name} already exists — skipping")
        return None

    txn = _ImportTransaction()

    # Step 1: Copy PNG + palette (strip tRNS chunk if present — GBA uses
    # palette index 0 for transparency, not PNG alpha)
    dest_dir = os.path.join(game_path, "graphics", "trainers", "front_pics")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"{file_stem}.png")
    try:
        stripped = _sanitise_sprite_png(filepath, dest_path)
        txn.track_create(dest_path)
        if stripped:
            print(f"  {DIM}Stripped tRNS chunk (PNG alpha → GBA palette transparency){RST}")
    except OSError as e:
        print(f"  {RED}Error copying file:{RST} {e}")
        txn.rollback()
        return None

    # Copy companion palette if found next to the PNG (.gbapal or .pal).
    src_dir = os.path.dirname(filepath)
    pal_copied = False
    pal_ext_used = ""
    pal_stems = [file_stem]
    for suffix in ("_front_pic", "_pic"):
        if file_stem.endswith(suffix):
            pal_stems.append(file_stem[:-len(suffix)])
    for ext in (".gbapal", ".pal"):
        for stem in pal_stems:
            candidates = [
                os.path.join(src_dir, stem + ext),
                os.path.join(src_dir, "..", "palettes", stem + ext),
            ]
            for pal_src in candidates:
                pal_src = os.path.normpath(pal_src)
                if os.path.isfile(pal_src):
                    pal_dest = os.path.join(dest_dir, file_stem + ext)
                    try:
                        shutil.copy2(pal_src, pal_dest)
                        txn.track_create(pal_dest)
                        pal_copied = True
                        pal_ext_used = ext
                    except OSError:
                        pass
                    break
            if pal_copied:
                break
        if pal_copied:
            break

    # Step 2: Add INCBIN lines
    txn.track_modify(trainers_h)
    if not _insert_incbin(trainers_h, camel_name, file_stem):
        print(f"  {RED}Error:{RST} Failed to insert INCBIN lines into trainers.h")
        txn.rollback()
        return None

    # Step 3: Add TRAINER_SPRITE entry
    txn.track_modify(trainers_h)
    if not _insert_sprite_entry(trainers_h, const_name, camel_name):
        print(f"  {RED}Error:{RST} Failed to insert TRAINER_SPRITE entry")
        txn.rollback()
        return None

    # Step 4: Add constant + increment count
    txn.track_modify(trainers_const)
    pic_id = _insert_pic_constant(trainers_const, const_name)
    if pic_id is None:
        print(f"  {RED}Error:{RST} Failed to insert {const_name} constant")
        txn.rollback()
        return None

    txn.commit()
    result = {
        "name": camel_name,
        "constant": const_name,
        "pic_id": pic_id,
        "files_modified": [
            "src/data/graphics/trainers.h",
            "include/constants/trainers.h",
        ],
        "file_copied": f"graphics/trainers/front_pics/{file_stem}.png",
    }
    if pal_copied:
        result["palette_copied"] = True
        result["palette_ext"] = pal_ext_used
    return result


# ============================================================
# OVERWORLD SPRITE IMPORTER
# ============================================================

def _read_ow_gfx_count(event_objects_h_path):
    """Read the current NUM_OBJ_EVENT_GFX (or OBJ_EVENT_GFX_COUNT) value.

    Returns (count, line_number, count_name) or (None, None, None).
    """
    try:
        with open(event_objects_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None, None, None

    # Try both naming conventions
    for name in ("NUM_OBJ_EVENT_GFX", "OBJ_EVENT_GFX_COUNT"):
        pat = re.compile(rf"^#define\s+{re.escape(name)}\s+(\d+)")
        for i, line in enumerate(lines):
            m = pat.match(line)
            if m:
                return int(m.group(1)), i, name
    return None, None, None


def _is_ow_already_imported(const_name, event_objects_h_path):
    """Check if an OBJ_EVENT_GFX_* constant already exists (exact match)."""
    try:
        with open(event_objects_h_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return False
    return bool(re.search(rf"^#define\s+{re.escape(const_name)}\s",
                          content, re.MULTILINE))


def _insert_overworld_constant(event_objects_h_path, const_name):
    """Insert a new OBJ_EVENT_GFX_* constant and increment count.

    Returns the assigned GFX ID on success, or None on failure.
    """
    count, count_line, count_name = _read_ow_gfx_count(event_objects_h_path)
    if count is None:
        return None

    try:
        with open(event_objects_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    new_define = f"#define {const_name:<41}{count}\n"
    new_count = f"#define {count_name:<41}{count + 1}\n"

    result = lines[:count_line] + [new_define] + lines[count_line + 1:]
    result.insert(count_line + 1, new_count)

    if not _write_atomic(event_objects_h_path, result):
        return None
    return count


def _insert_overworld_incbin(graphics_h_path, camel_name, file_stem):
    """Insert INCBIN line for a new overworld sprite.

    Appends after the last gObjectEventPic_* line.
    Returns True on success.
    """
    try:
        with open(graphics_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    last_pic_idx = None
    pat = re.compile(r"^const\s+u32\s+gObjectEventPic_\w+\[\]")
    for i, line in enumerate(lines):
        if pat.match(line):
            last_pic_idx = i

    if last_pic_idx is None:
        return False

    new_line = f'const u32 gObjectEventPic_{camel_name}[] = INCBIN_U32("graphics/object_events/pics/people/{file_stem}.4bpp");\n'
    result = lines[:last_pic_idx + 1] + [new_line] + lines[last_pic_idx + 1:]
    return _write_atomic(graphics_h_path, result)


def _insert_overworld_pic_table(pic_tables_h_path, camel_name, tile_w, tile_h):
    """Insert a sPicTable_* definition for a new overworld sprite.

    Uses overworld_ascending_frames macro (standard for walking NPCs).
    Appends after the last sPicTable_* definition.
    Returns True on success.
    """
    try:
        with open(pic_tables_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find last '};' that closes a sPicTable_ definition
    last_close_idx = None
    in_pic_table = False
    for i, line in enumerate(lines):
        if re.match(r"^static\s+const\s+struct\s+SpriteFrameImage\s+sPicTable_", line):
            in_pic_table = True
        if in_pic_table and line.strip() == "};":
            last_close_idx = i
            in_pic_table = False

    if last_close_idx is None:
        return False

    new_lines = [
        "\n",
        f"static const struct SpriteFrameImage sPicTable_{camel_name}[] = {{\n",
        f"    overworld_ascending_frames(gObjectEventPic_{camel_name}, {tile_w}, {tile_h}),\n",
        "};\n",
    ]

    result = lines[:last_close_idx + 1] + new_lines + lines[last_close_idx + 1:]
    return _write_atomic(pic_tables_h_path, result)


def _ow_size_fields(frame_w, frame_h):
    """Return (size_bytes, oam_suffix) for a given frame pixel size."""
    tile_w = frame_w // 8
    tile_h = frame_h // 8
    size_bytes = tile_w * tile_h * 32
    oam_suffix = f"{frame_w}x{frame_h}"
    return size_bytes, oam_suffix, tile_w, tile_h


def _generate_4bpp(game_path, png_path, tile_w, tile_h):
    """Run gbagfx to generate a .4bpp file with correct metatile dimensions.

    The default make rule (gbagfx input.png output.4bpp) uses 1x1 metatiles,
    which arranges tiles in the wrong order for multi-tile sprites.  Overworld
    sprites need -mwidth/-mheight matching the frame tile dimensions so the
    GBA hardware reads the tile data in the correct order.

    Returns True on success.
    """
    gbagfx = os.path.join(game_path, "tools", "gbagfx", "gbagfx")
    if not os.path.isfile(gbagfx):
        return False
    stem = os.path.splitext(png_path)[0]
    out_path = stem + ".4bpp"
    try:
        subprocess.run(
            [gbagfx, png_path, out_path,
             "-mwidth", str(tile_w), "-mheight", str(tile_h)],
            check=True, capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


def _regenerate_4bpp(type_key, png_dest_path, game_path):
    """Regenerate .4bpp for a game-side PNG with correct metatile dimensions.

    Overworld spritesheets contain multiple frames — gbagfx needs
    -mwidth/-mheight matching the frame tile size to arrange tiles
    correctly.  Without this, the default 1x1 metatile produces
    wrong tile ordering and garbled in-game sprites.

    No-op for non-overworld types (trainers are single 64x64 frames
    where tile order doesn't matter).
    """
    if type_key != "overworld_sprites":
        return
    info = _parse_png_info(png_dest_path)
    if info is None:
        return
    result = _detect_overworld_frame_size(info["width"], info["height"])
    if result is None:
        return
    frame_w, frame_h, _ = result
    _, _, tile_w, tile_h = _ow_size_fields(frame_w, frame_h)
    _generate_4bpp(game_path, png_dest_path, tile_w, tile_h)


# ============================================================
# CUSTOM OVERWORLD PALETTE REGISTRATION
# ============================================================

def _derive_palette_tag_name(camel_name):
    """Derive OBJ_EVENT_PAL_TAG constant name from CamelCase sprite name.

    'RocketM' -> 'OBJ_EVENT_PAL_TAG_ROCKET_M'
    """
    return "OBJ_EVENT_PAL_TAG_" + _camel_to_upper_snake(camel_name)


def _derive_palette_data_name(camel_name):
    """Derive gObjectEventPal_ variable name from CamelCase sprite name.

    'RocketM' -> 'gObjectEventPal_RocketM'
    """
    return f"gObjectEventPal_{camel_name}"


def _next_palette_tag_value(event_obj_h):
    """Find the next available OBJ_EVENT_PAL_TAG hex value.

    Scans existing #define OBJ_EVENT_PAL_TAG_* lines in the 0x1100-0x114F
    range (the main custom range, below pokeball tags at 0x1150+).
    Returns the hex string (e.g. '0x1125') or None on error.
    """
    try:
        with open(event_obj_h, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None

    max_val = 0x1124  # OBJ_EVENT_PAL_TAG_DYNAMIC is the last vanilla tag
    pat = re.compile(r"#define\s+OBJ_EVENT_PAL_TAG_\w+\s+(0x[0-9A-Fa-f]+)")
    for m in pat.finditer(content):
        val = int(m.group(1), 16)
        # Stay in the main tag range (below pokeball block at 0x1150)
        if 0x1100 <= val < 0x1150 and val > max_val:
            max_val = val
    next_val = max_val + 1
    if next_val >= 0x1150:
        return None  # Range exhausted (43 custom tags maximum)
    return f"0x{next_val:04X}"


# Total capacity: 0x1125 through 0x114F = 43 slots
_PALETTE_TAG_CAPACITY = 43


def _count_custom_palette_tags(event_obj_h):
    """Count how many custom palette tags are in use.

    Scans for #define OBJ_EVENT_PAL_TAG_* in the TORCH range (0x1125-0x114F).
    Returns (used, capacity) tuple.
    """
    try:
        with open(event_obj_h, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return 0, _PALETTE_TAG_CAPACITY

    pat = re.compile(r"#define\s+OBJ_EVENT_PAL_TAG_\w+\s+(0x[0-9A-Fa-f]+)")
    used = 0
    for m in pat.finditer(content):
        val = int(m.group(1), 16)
        if 0x1125 <= val <= 0x114F:
            used += 1
    return used, _PALETTE_TAG_CAPACITY


def _insert_palette_tag_define(event_obj_h, tag_name, tag_value):
    """Insert #define for a custom palette tag into event_objects.h.

    Inserts before the OBJ_EVENT_PAL_TAG_DYNAMIC line (or before the
    pokeball block if DYNAMIC isn't found).
    Returns True on success.
    """
    try:
        with open(event_obj_h, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find insertion point — before OBJ_EVENT_PAL_TAG_DYNAMIC
    insert_idx = None
    for i, line in enumerate(lines):
        if "OBJ_EVENT_PAL_TAG_DYNAMIC" in line and "#define" in line:
            insert_idx = i
            break

    if insert_idx is None:
        # Fallback: before pokeball block
        for i, line in enumerate(lines):
            if "OW_FOLLOWERS_POKEBALLS" in line:
                insert_idx = i
                break

    if insert_idx is None:
        return False

    # Align the value column to match surrounding defines
    new_line = f"#define {tag_name:<46s}{tag_value}\n"
    result = lines[:insert_idx] + [new_line] + lines[insert_idx:]
    return _write_atomic(event_obj_h, result)


def _insert_palette_incbin(graphics_h, camel_name, file_stem):
    """Insert palette INCBIN line into object_event_graphics.h.

    Adds after the last existing gObjectEventPal_* INCBIN line.
    Returns True on success.
    """
    try:
        with open(graphics_h, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    last_pal_idx = None
    pat = re.compile(r"^const\s+u16\s+gObjectEventPal_\w+\[\]")
    for i, line in enumerate(lines):
        if pat.match(line) and "INCBIN_U16" in line:
            last_pal_idx = i

    if last_pal_idx is None:
        return False

    new_line = f'const u16 gObjectEventPal_{camel_name}[] = INCBIN_U16("graphics/object_events/palettes/{file_stem}.gbapal");\n'
    result = lines[:last_pal_idx + 1] + [new_line] + lines[last_pal_idx + 1:]
    return _write_atomic(graphics_h, result)


def _insert_palette_table_entry(movement_c, camel_name, tag_name):
    """Insert entry into sObjectEventSpritePalettes[] in event_object_movement.c.

    Adds before the #if OW_FOLLOWERS_POKEBALLS block (or before the
    terminator entry if pokeball block isn't found).
    Returns True on success.
    """
    try:
        with open(movement_c, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find sObjectEventSpritePalettes array
    in_array = False
    insert_idx = None
    for i, line in enumerate(lines):
        if "sObjectEventSpritePalettes" in line and "static" in line:
            in_array = True
            continue
        if not in_array:
            continue
        # Insert before pokeball block
        if "OW_FOLLOWERS_POKEBALLS" in line:
            insert_idx = i
            break
        # Fallback: before Substitute entry (which precedes light/emotes/terminator)
        if "OBJ_EVENT_PAL_TAG_SUBSTITUTE" in line:
            insert_idx = i
            break
        # Fallback: before terminator
        if "OBJ_EVENT_PAL_TAG_NONE" in line:
            insert_idx = i
            break

    if insert_idx is None:
        return False

    data_name = _derive_palette_data_name(camel_name)
    # Align to match surrounding entries
    entry = f"    {{{data_name + ',':<44s}{tag_name}}},\n"
    result = lines[:insert_idx] + [entry] + lines[insert_idx:]
    return _write_atomic(movement_c, result)


def _register_custom_palette(game_path, camel_name, file_stem, png_path):
    """Full custom palette registration pipeline for an overworld sprite.

    1. Extract .gbapal and .pal from the PNG
    2. Allocate next palette tag value
    3. Insert #define into event_objects.h
    4. Insert INCBIN into object_event_graphics.h
    5. Insert entry into sObjectEventSpritePalettes[]

    Returns the palette tag name on success, or None on failure.
    """
    event_obj_h = os.path.join(game_path, "include", "constants", "event_objects.h")
    graphics_h = os.path.join(game_path, "src", "data", "object_events", "object_event_graphics.h")
    movement_c = os.path.join(game_path, "src", "event_object_movement.c")
    pal_dir = os.path.join(game_path, "graphics", "object_events", "palettes")

    for path in (event_obj_h, graphics_h, movement_c):
        if not os.path.isfile(path):
            print(f"  {RED}Error:{RST} {path} not found")
            return None

    tag_name = _derive_palette_tag_name(camel_name)

    # Check if tag already registered
    try:
        with open(event_obj_h, encoding="utf-8", errors="replace") as f:
            if tag_name in f.read():
                return tag_name  # Already registered
    except OSError:
        return None

    # Step 1: Extract palette files
    gbapal_path = os.path.join(pal_dir, f"{file_stem}.gbapal")
    pal_path = os.path.join(pal_dir, f"{file_stem}.pal")
    if not _extract_gbapal_from_png(png_path, gbapal_path):
        print(f"  {RED}Error:{RST} Failed to extract palette from PNG")
        return None
    _extract_jasc_pal_from_png(png_path, pal_path)  # .pal is optional, best-effort

    # Step 2: Allocate tag value
    tag_value = _next_palette_tag_value(event_obj_h)
    if tag_value is None:
        print(f"  {RED}Error:{RST} No available palette tag values")
        return None

    # Step 3: Insert tag define
    if not _insert_palette_tag_define(event_obj_h, tag_name, tag_value):
        print(f"  {RED}Error:{RST} Failed to insert palette tag define")
        return None

    # Step 4: Insert INCBIN
    if not _insert_palette_incbin(graphics_h, camel_name, file_stem):
        print(f"  {RED}Error:{RST} Failed to insert palette INCBIN")
        return None

    # Step 5: Insert palette table entry
    if not _insert_palette_table_entry(movement_c, camel_name, tag_name):
        print(f"  {RED}Error:{RST} Failed to insert palette table entry")
        return None

    return tag_name


def _update_palette_files(png_src_path, filename, game_path):
    """Re-extract .gbapal and .pal from an updated source PNG.

    Called during sync update and force regenerate — the palette
    registration (tag define, INCBIN, table entry) already exists,
    only the binary palette data needs refreshing.

    Skips sprites that use shared NPC palettes or share another
    sprite's custom palette (they don't have their own .gbapal file).
    """
    camel_name = _derive_overworld_name(filename)
    if not _has_own_custom_palette(camel_name, game_path):
        return
    file_stem = _derive_file_stem(filename)
    pal_dir = os.path.join(game_path, "graphics", "object_events", "palettes")
    gbapal_path = os.path.join(pal_dir, f"{file_stem}.gbapal")
    pal_path = os.path.join(pal_dir, f"{file_stem}.pal")
    _extract_gbapal_from_png(png_src_path, gbapal_path)
    _extract_jasc_pal_from_png(png_src_path, pal_path)


def _insert_overworld_graphics_info(info_h_path, camel_name, frame_w, frame_h,
                                    palette_tag=None, palette_slot=None):
    """Insert a gObjectEventGraphicsInfo_* struct.

    Appends after the last such struct definition.
    palette_tag: explicit palette tag (e.g. OBJ_EVENT_PAL_TAG_NPC_1 or custom)
    palette_slot: explicit slot (e.g. PALSLOT_NPC_1 or PALSLOT_NPC_SPECIAL)
    Returns True on success.
    """
    try:
        with open(info_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find last '};' closing a gObjectEventGraphicsInfo_ definition
    last_close_idx = None
    in_info = False
    for i, line in enumerate(lines):
        if re.match(r"^const\s+struct\s+ObjectEventGraphicsInfo\s+gObjectEventGraphicsInfo_", line):
            in_info = True
        if in_info and line.strip() == "};":
            last_close_idx = i
            in_info = False

    if last_close_idx is None:
        return False

    size_bytes, oam_suffix, _, _ = _ow_size_fields(frame_w, frame_h)

    # Use provided tag/slot, or fall back to NPC_1 defaults
    pal_tag = palette_tag or "OBJ_EVENT_PAL_TAG_NPC_1"
    pal_slot = palette_slot or "PALSLOT_NPC_1"

    new_lines = [
        "\n",
        f"const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_{camel_name} = {{\n",
        "    .tileTag = TAG_NONE,\n",
        f"    .paletteTag = {pal_tag},\n",
        "    .reflectionPaletteTag = OBJ_EVENT_PAL_TAG_NONE,\n",
        f"    .size = {size_bytes},\n",
        f"    .width = {frame_w},\n",
        f"    .height = {frame_h},\n",
        f"    .paletteSlot = {pal_slot},\n",
        "    .shadowSize = SHADOW_SIZE_M,\n",
        "    .inanimate = FALSE,\n",
        "    .compressed = FALSE,\n",
        "    .tracks = TRACKS_FOOT,\n",
        f"    .oam = &gObjectEventBaseOam_{oam_suffix},\n",
        f"    .subspriteTables = sOamTables_{oam_suffix},\n",
        "    .anims = sAnimTable_Standard,\n",
        f"    .images = sPicTable_{camel_name},\n",
        "    .affineAnims = gDummySpriteAffineAnimTable,\n",
        "};\n",
    ]

    result = lines[:last_close_idx + 1] + new_lines + lines[last_close_idx + 1:]
    return _write_atomic(info_h_path, result)


def _insert_overworld_pointer(pointers_h_path, camel_name, const_name):
    """Insert extern declaration and pointer table entry.

    Adds extern after the last existing extern, and array entry before
    the closing '};' of gObjectEventGraphicsInfoPointers[].
    Returns True on success.
    """
    try:
        with open(pointers_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find last extern line
    last_extern_idx = None
    extern_pat = re.compile(r"^extern\s+const\s+struct\s+ObjectEventGraphicsInfo\s+")
    for i, line in enumerate(lines):
        if extern_pat.match(line):
            last_extern_idx = i

    if last_extern_idx is None:
        return False

    extern_line = f"extern const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_{camel_name};\n"
    lines = lines[:last_extern_idx + 1] + [extern_line] + lines[last_extern_idx + 1:]

    # Find the closing '};' of gObjectEventGraphicsInfoPointers[]
    in_array = False
    close_idx = None
    for i, line in enumerate(lines):
        if "gObjectEventGraphicsInfoPointers" in line and "const" in line:
            in_array = True
        elif in_array and line.strip() == "};":
            close_idx = i
            break

    if close_idx is None:
        return False

    entry = f"    [{const_name}] = &gObjectEventGraphicsInfo_{camel_name},\n"
    result = lines[:close_idx] + [entry] + lines[close_idx:]
    return _write_atomic(pointers_h_path, result)


def _import_overworld_sprite(filepath, game_path):
    """Full overworld sprite registration pipeline with transaction rollback.

    1. Copy PNG to graphics/object_events/pics/people/
    2. Register custom palette (extract .gbapal, define tag, INCBIN, table entry)
    3. Add GFX constant to include/constants/event_objects.h
    4. Add INCBIN to src/data/object_events/object_event_graphics.h
    5. Add pic table to src/data/object_events/object_event_pic_tables.h
    6. Add graphics info to src/data/object_events/object_event_graphics_info.h
    7. Add pointer to src/data/object_events/object_event_graphics_info_pointers.h

    On failure at any step, rolls back all prior steps to prevent orphaned files.

    Returns a result dict on success, or None on failure.
    """
    filename = os.path.basename(filepath)
    file_stem = _derive_file_stem(filename)
    camel_name = _derive_overworld_name(filename)
    const_name = _derive_overworld_const(camel_name)

    # Resolve game file paths
    event_obj_h = os.path.join(game_path, "include", "constants", "event_objects.h")
    graphics_h = os.path.join(game_path, "src", "data", "object_events", "object_event_graphics.h")
    pic_tables_h = os.path.join(game_path, "src", "data", "object_events", "object_event_pic_tables.h")
    info_h = os.path.join(game_path, "src", "data", "object_events", "object_event_graphics_info.h")
    pointers_h = os.path.join(game_path, "src", "data", "object_events", "object_event_graphics_info_pointers.h")
    movement_c = os.path.join(game_path, "src", "event_object_movement.c")

    for path in (event_obj_h, graphics_h, pic_tables_h, info_h, pointers_h, movement_c):
        if not os.path.isfile(path):
            print(f"  {RED}Error:{RST} {path} not found")
            return None

    # PNG structural integrity check
    png_ok, png_msg = _validate_png_structural_integrity(filepath)
    if not png_ok:
        print(f"  {RED}Error:{RST} {png_msg}")
        return None

    # Detect frame size from PNG
    info = _parse_png_info(filepath)
    if info is None:
        print(f"  {RED}Error:{RST} Cannot read PNG info")
        return None
    result = _detect_overworld_frame_size(info["width"], info["height"])
    if result is None:
        print(f"  {RED}Error:{RST} Unsupported sprite dimensions: {info['width']}x{info['height']}")
        return None
    frame_w, frame_h, _ = result
    _, _, tile_w, tile_h = _ow_size_fields(frame_w, frame_h)

    # Check for duplicate
    if _is_ow_already_imported(const_name, event_obj_h):
        print(f"  {RED}Error:{RST} {const_name} already exists — skipping")
        return None

    # Palette tag exhaustion check
    used, total = _count_custom_palette_tags(event_obj_h)
    if used >= total:
        # Only matters if we'd need a new palette — check first
        match_type, _, _ = _find_matching_palette(filepath, game_path)
        if match_type == "none":
            print(f"  {RED}Error:{RST} All {total} custom palette slots in use. "
                  f"Run Sync > Deduplicate first.")
            return None
    elif used >= total - 2:
        print(f"  {DIM}Warning: Only {total - used} palette slots remaining ({used}/{total}){RST}")

    txn = _ImportTransaction()

    # Step 1: Copy PNG (strip tRNS chunk if present — GBA uses palette
    # index 0 for transparency, not PNG alpha)
    dest_dir = os.path.join(game_path, "graphics", "object_events", "pics", "people")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"{file_stem}.png")
    try:
        stripped = _sanitise_sprite_png(filepath, dest_path)
        txn.track_create(dest_path)
        if stripped:
            print(f"  {DIM}Stripped tRNS chunk (PNG alpha → GBA palette transparency){RST}")
    except OSError as e:
        print(f"  {RED}Error copying file:{RST} {e}")
        txn.rollback()
        return None

    # Pre-generate .4bpp with correct metatile dimensions so the build
    # system uses properly-tiled data (default gbagfx uses 1x1 metatiles
    # which produces wrong tile ordering for multi-tile sprites)
    if _generate_4bpp(game_path, dest_path, tile_w, tile_h):
        fourBpp = os.path.splitext(dest_path)[0] + ".4bpp"
        if os.path.isfile(fourBpp):
            txn.track_create(fourBpp)
        print(f"  {DIM}Generated .4bpp ({tile_w}x{tile_h} metatile){RST}")

    # Step 2: Smart palette selection — check shared NPC palettes and
    # existing custom palettes before registering a new one.
    match_type, match_tag, match_slot = _find_matching_palette(filepath, game_path)
    if match_type == "shared":
        palette_tag = match_tag
        palette_slot = match_slot
        n = match_tag.rsplit("_", 1)[-1]
        print(f"  {DIM}Using shared palette NPC_{n}{RST}")
    elif match_type == "custom":
        palette_tag = match_tag
        palette_slot = match_slot
        print(f"  {DIM}Sharing palette with existing sprite ({match_tag}){RST}")
    else:
        # Snapshot files that _register_custom_palette will modify
        pal_dir = os.path.join(game_path, "graphics", "object_events", "palettes")
        txn.track_modify(event_obj_h)
        txn.track_modify(os.path.join(game_path, "src", "data", "object_events", "object_event_graphics.h"))
        txn.track_modify(movement_c)
        palette_tag = _register_custom_palette(game_path, camel_name, file_stem, filepath)
        if palette_tag is None:
            print(f"  {RED}Error:{RST} Failed to register custom palette")
            txn.rollback()
            return None
        # Track created palette files
        for ext in (".gbapal", ".pal"):
            pf = os.path.join(pal_dir, f"{file_stem}{ext}")
            if os.path.isfile(pf):
                txn.track_create(pf)
        palette_slot = "PALSLOT_NPC_SPECIAL"
        print(f"  {DIM}Registered custom palette ({palette_tag}){RST}")

    # Step 3: Add GFX constant
    txn.track_modify(event_obj_h)
    gfx_id = _insert_overworld_constant(event_obj_h, const_name)
    if gfx_id is None:
        print(f"  {RED}Error:{RST} Failed to insert {const_name} constant")
        txn.rollback()
        return None

    # Step 4: Add INCBIN
    txn.track_modify(graphics_h)
    if not _insert_overworld_incbin(graphics_h, camel_name, file_stem):
        print(f"  {RED}Error:{RST} Failed to insert INCBIN into object_event_graphics.h")
        txn.rollback()
        return None

    # Step 5: Add pic table
    txn.track_modify(pic_tables_h)
    if not _insert_overworld_pic_table(pic_tables_h, camel_name, tile_w, tile_h):
        print(f"  {RED}Error:{RST} Failed to insert pic table into object_event_pic_tables.h")
        txn.rollback()
        return None

    # Step 6: Add graphics info struct (with palette tag and slot)
    txn.track_modify(info_h)
    if not _insert_overworld_graphics_info(info_h, camel_name, frame_w, frame_h,
                                           palette_tag=palette_tag,
                                           palette_slot=palette_slot):
        print(f"  {RED}Error:{RST} Failed to insert graphics info struct")
        txn.rollback()
        return None

    # Step 7: Add pointer
    txn.track_modify(pointers_h)
    if not _insert_overworld_pointer(pointers_h, camel_name, const_name):
        print(f"  {RED}Error:{RST} Failed to insert pointer entry")
        txn.rollback()
        return None

    txn.commit()
    return {
        "name": camel_name,
        "constant": const_name,
        "pic_id": gfx_id,
        "palette_tag": palette_tag,
        "files_modified": [
            "include/constants/event_objects.h",
            "src/data/object_events/object_event_graphics.h",
            "src/data/object_events/object_event_pic_tables.h",
            "src/data/object_events/object_event_graphics_info.h",
            "src/data/object_events/object_event_graphics_info_pointers.h",
            "src/event_object_movement.c",
        ],
        "file_copied": f"graphics/object_events/pics/people/{file_stem}.png",
    }


# ============================================================
# MUSIC TRACK NAME DERIVATION
# ============================================================

def _derive_music_name(filename):
    """Convert a filename to lowercase_underscore for music file paths.

    'battle_theme.mid' -> 'battle_theme'
    'Route-123-Night.mid' -> 'route_123_night'
    """
    stem = os.path.splitext(filename)[0]
    stem = stem.replace("-", "_")
    return stem.lower()


def _derive_music_const(name):
    """Convert a lowercase music name to MUS_UPPER_SNAKE constant.

    'battle_theme' -> 'MUS_BATTLE_THEME'
    'route_123_night' -> 'MUS_ROUTE_123_NIGHT'
    """
    return "MUS_" + name.upper()


# ============================================================
# MUSIC TRACK VALIDATION
# ============================================================

_MUSIC_MAX_SIZE = 10 * 1024 * 1024  # 10 MB sanity limit


def _validate_music_file(filepath):
    """Validate a MIDI file for import.

    Checks: exists, .mid extension, non-empty, under 10 MB.
    Actual MIDI parsing is left to mid2agb at build time.

    Returns (ok, message) tuple.
    """
    if not os.path.isfile(filepath):
        return False, "File not found"

    ext = os.path.splitext(filepath)[1].lower()
    if ext != ".mid":
        return False, f"Wrong extension: {ext} (need .mid)"

    try:
        size = os.path.getsize(filepath)
    except OSError:
        return False, "Cannot read file size"

    if size == 0:
        return False, "Empty file (0 bytes)"

    if size > _MUSIC_MAX_SIZE:
        mb = size / (1024 * 1024)
        return False, f"File too large: {mb:.1f} MB (max 10 MB)"

    kb = size / 1024
    return True, f"MIDI, {kb:.1f} KB"


# ============================================================
# MUSIC TRACK IMPORTER
# ============================================================

def _read_end_mus_line(songs_h_path):
    """Find END_MUS in songs.h and the last MUS_* constant value.

    Returns (last_mus_value, end_mus_line_idx) or (None, None).
    """
    try:
        with open(songs_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None, None

    end_mus_idx = None
    last_mus_val = None

    # Find END_MUS and track the highest MUS_* numeric value
    mus_pat = re.compile(r"^#define\s+(MUS_\w+)\s+(\d+)")
    end_pat = re.compile(r"^#define\s+END_MUS\b")

    for i, line in enumerate(lines):
        if end_pat.match(line):
            end_mus_idx = i
            continue
        m = mus_pat.match(line)
        if m:
            val = int(m.group(2))
            if last_mus_val is None or val > last_mus_val:
                last_mus_val = val

    if end_mus_idx is None or last_mus_val is None:
        return None, None
    return last_mus_val, end_mus_idx


def _is_music_already_imported(const_name, songs_h_path):
    """Check if a MUS_* constant already exists in songs.h (exact match)."""
    try:
        with open(songs_h_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return False
    return bool(re.search(rf"^#define\s+{re.escape(const_name)}\s",
                          content, re.MULTILINE))


def _insert_music_constant(songs_h_path, const_name):
    """Insert a new MUS_* constant before END_MUS and update END_MUS.

    Returns the assigned music ID on success, or None on failure.
    """
    last_mus_val, end_mus_idx = _read_end_mus_line(songs_h_path)
    if last_mus_val is None:
        return None

    try:
        with open(songs_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    new_id = last_mus_val + 1
    new_define = f"#define {const_name:<28}{new_id}\n"
    new_end_mus = f"#define END_MUS                     {const_name}\n"

    # Insert new constant before END_MUS, then replace END_MUS
    result = lines[:end_mus_idx] + [new_define] + lines[end_mus_idx + 1:]
    # END_MUS was at end_mus_idx, now new_define is there, so END_MUS goes at end_mus_idx+1
    result.insert(end_mus_idx + 1, new_end_mus)

    if not _write_atomic(songs_h_path, result):
        return None
    return new_id


def _insert_song_table_entry(song_table_path, file_stem):
    """Insert a song table entry into song_table.inc.

    Inserts after the last 'song mus_*' line (before phoneme entries).
    Returns True on success.
    """
    try:
        with open(song_table_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find the last line matching 'song mus_*' (lowercase mus_ in assembly)
    last_mus_idx = None
    mus_song_pat = re.compile(r"^\s+song\s+mus_")
    for i, line in enumerate(lines):
        if mus_song_pat.match(line):
            last_mus_idx = i

    if last_mus_idx is None:
        return False

    new_entry = f"\tsong mus_{file_stem}, MUSIC_PLAYER_BGM, 0\n"
    result = lines[:last_mus_idx + 1] + [new_entry] + lines[last_mus_idx + 1:]
    return _write_atomic(song_table_path, result)


def _import_music_track(filepath, game_path):
    """Full music track registration pipeline with transaction rollback.

    1. Copy MIDI to sound/songs/midi/
    2. Add MUS_* constant to include/constants/songs.h
    3. Add entry to sound/song_table.inc

    On failure at any step, rolls back all prior steps.

    Returns a result dict on success, or None on failure.
    """
    filename = os.path.basename(filepath)
    name = _derive_music_name(filename)
    file_stem = name
    const_name = _derive_music_const(name)

    songs_h = os.path.join(game_path, "include", "constants", "songs.h")
    song_table = os.path.join(game_path, "sound", "song_table.inc")

    if not os.path.isfile(songs_h):
        print(f"  {RED}Error:{RST} {songs_h} not found")
        return None
    if not os.path.isfile(song_table):
        print(f"  {RED}Error:{RST} {song_table} not found")
        return None

    # Check for duplicate
    if _is_music_already_imported(const_name, songs_h):
        print(f"  {RED}Error:{RST} {const_name} already exists — skipping")
        return None

    txn = _ImportTransaction()

    # Step 1: Copy MIDI to sound/songs/midi/
    dest_dir = os.path.join(game_path, "sound", "songs", "midi")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"mus_{file_stem}.mid")
    try:
        shutil.copy2(filepath, dest_path)
        txn.track_create(dest_path)
    except OSError as e:
        print(f"  {RED}Error copying file:{RST} {e}")
        txn.rollback()
        return None

    # Step 2: Add constant to songs.h
    txn.track_modify(songs_h)
    music_id = _insert_music_constant(songs_h, const_name)
    if music_id is None:
        print(f"  {RED}Error:{RST} Failed to insert {const_name} into songs.h")
        txn.rollback()
        return None

    # Step 3: Add entry to song_table.inc
    txn.track_modify(song_table)
    if not _insert_song_table_entry(song_table, file_stem):
        print(f"  {RED}Error:{RST} Failed to insert song table entry")
        txn.rollback()
        return None

    txn.commit()
    return {
        "name": name,
        "constant": const_name,
        "pic_id": music_id,
        "files_modified": [
            "include/constants/songs.h",
            "sound/song_table.inc",
        ],
        "file_copied": f"sound/songs/midi/mus_{file_stem}.mid",
    }


# ============================================================
# SOUND EFFECT NAME DERIVATION
# ============================================================

def _derive_se_name(filename):
    """Convert a filename to lowercase_underscore with se_ prefix.

    'my_sound.s' -> 'se_my_sound'
    'se_custom_hit.s' -> 'se_custom_hit' (no double prefix)
    'Hit-Sound.s' -> 'se_hit_sound'
    """
    stem = os.path.splitext(filename)[0]
    stem = stem.replace("-", "_").lower()
    if not stem.startswith("se_"):
        stem = "se_" + stem
    return stem


def _derive_se_const(name):
    """Convert a lowercase SE name to SE_UPPER_SNAKE constant.

    'se_my_sound' -> 'SE_MY_SOUND'
    'se_custom_hit' -> 'SE_CUSTOM_HIT'
    """
    return name.upper()


# ============================================================
# SOUND EFFECT VALIDATION
# ============================================================

def _validate_se_file(filepath):
    """Validate a GBA sound effect assembly file for import.

    Checks: exists, .s extension, non-empty, contains .include "MPlayDef.s".

    Returns (ok, message) tuple.
    """
    if not os.path.isfile(filepath):
        return False, "File not found"

    ext = os.path.splitext(filepath)[1].lower()
    if ext != ".s":
        return False, f"Wrong extension: {ext} (need .s)"

    try:
        size = os.path.getsize(filepath)
    except OSError:
        return False, "Cannot read file size"

    if size == 0:
        return False, "Empty file (0 bytes)"

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return False, "Cannot read file"

    if '.include "MPlayDef.s"' not in content:
        return False, "Missing MPlayDef.s include (not a GBA audio file)"

    kb = size / 1024
    return True, f"GBA assembly, {kb:.1f} KB"


# ============================================================
# SOUND EFFECT IMPORTER
# ============================================================

def _read_end_se_line(songs_h_path):
    """Find END_SE in songs.h and the last SE_* constant value.

    Returns (last_se_value, end_se_line_idx) or (None, None).
    """
    try:
        with open(songs_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None, None

    end_se_idx = None
    last_se_val = None

    se_pat = re.compile(r"^#define\s+(SE_\w+)\s+(\d+)")
    end_pat = re.compile(r"^#define\s+END_SE\b")

    for i, line in enumerate(lines):
        if end_pat.match(line):
            end_se_idx = i
            continue
        m = se_pat.match(line)
        if m:
            val = int(m.group(2))
            if last_se_val is None or val > last_se_val:
                last_se_val = val

    if end_se_idx is None or last_se_val is None:
        return None, None
    return last_se_val, end_se_idx


def _is_se_already_imported(const_name, songs_h_path):
    """Check if an SE_* constant already exists in songs.h (exact match)."""
    try:
        with open(songs_h_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return False
    return bool(re.search(rf"^#define\s+{re.escape(const_name)}\s",
                          content, re.MULTILINE))


def _insert_se_constant(songs_h_path, const_name):
    """Insert a new SE_* constant before END_SE and update END_SE.

    Returns the assigned SE ID on success, or None on failure.
    """
    last_se_val, end_se_idx = _read_end_se_line(songs_h_path)
    if last_se_val is None:
        return None

    try:
        with open(songs_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    new_id = last_se_val + 1
    new_define = f"#define {const_name:<28}{new_id}\n"
    new_end_se = f"#define END_SE                      {const_name}\n"

    # Insert new constant before END_SE, then replace END_SE
    result = lines[:end_se_idx] + [new_define] + lines[end_se_idx + 1:]
    # END_SE was at end_se_idx, now new_define is there, so END_SE goes at end_se_idx+1
    result.insert(end_se_idx + 1, new_end_se)

    if not _write_atomic(songs_h_path, result):
        return None
    return new_id


def _insert_se_song_table_entry(song_table_path, file_stem):
    """Insert a song table entry for an SE into song_table.inc.

    Inserts after the last 'song se_*' line (before mus_* entries).
    Returns True on success.
    """
    try:
        with open(song_table_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find the last line matching 'song se_*'
    last_se_idx = None
    se_song_pat = re.compile(r"^\s+song\s+se_")
    for i, line in enumerate(lines):
        if se_song_pat.match(line):
            last_se_idx = i

    if last_se_idx is None:
        return False

    new_entry = f"\tsong {file_stem}, MUSIC_PLAYER_SE1, 1\n"
    result = lines[:last_se_idx + 1] + [new_entry] + lines[last_se_idx + 1:]
    return _write_atomic(song_table_path, result)


def _import_sound_effect(filepath, game_path):
    """Full sound effect registration pipeline with transaction rollback.

    1. Copy .s file to sound/songs/
    2. Add SE_* constant to include/constants/songs.h
    3. Add entry to sound/song_table.inc

    On failure at any step, rolls back all prior steps.

    Returns a result dict on success, or None on failure.
    """
    filename = os.path.basename(filepath)
    name = _derive_se_name(filename)
    file_stem = name
    const_name = _derive_se_const(name)

    songs_h = os.path.join(game_path, "include", "constants", "songs.h")
    song_table = os.path.join(game_path, "sound", "song_table.inc")

    if not os.path.isfile(songs_h):
        print(f"  {RED}Error:{RST} {songs_h} not found")
        return None
    if not os.path.isfile(song_table):
        print(f"  {RED}Error:{RST} {song_table} not found")
        return None

    # Check for duplicate
    if _is_se_already_imported(const_name, songs_h):
        print(f"  {RED}Error:{RST} {const_name} already exists — skipping")
        return None

    txn = _ImportTransaction()

    # Step 1: Copy .s file to sound/songs/
    dest_dir = os.path.join(game_path, "sound", "songs")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"{file_stem}.s")
    try:
        shutil.copy2(filepath, dest_path)
        txn.track_create(dest_path)
    except OSError as e:
        print(f"  {RED}Error copying file:{RST} {e}")
        txn.rollback()
        return None

    # Step 2: Add constant to songs.h
    txn.track_modify(songs_h)
    se_id = _insert_se_constant(songs_h, const_name)
    if se_id is None:
        print(f"  {RED}Error:{RST} Failed to insert {const_name} into songs.h")
        txn.rollback()
        return None

    # Step 3: Add entry to song_table.inc
    txn.track_modify(song_table)
    if not _insert_se_song_table_entry(song_table, file_stem):
        print(f"  {RED}Error:{RST} Failed to insert song table entry")
        txn.rollback()
        return None

    txn.commit()
    return {
        "name": name,
        "constant": const_name,
        "pic_id": se_id,
        "files_modified": [
            "include/constants/songs.h",
            "sound/song_table.inc",
        ],
        "file_copied": f"sound/songs/{file_stem}.s",
    }


# ============================================================
# TRAINER BACK SPRITE SUPPORT
# ============================================================

def _derive_trainer_back_const(camel_name):
    """Convert CamelCase to TRAINER_BACK_PIC_UPPER_SNAKE.

    'RivalDawn' -> 'TRAINER_BACK_PIC_RIVAL_DAWN'
    """
    return "TRAINER_BACK_PIC_" + _camel_to_upper_snake(camel_name)


def _validate_trainer_back_sprite(filepath):
    """Validate a PNG for use as a trainer back sprite.

    Must be 64x256 (4 frames of 64x64), indexed, <=16 colours.
    Returns (ok, message) tuple.
    """
    # Structural integrity check
    png_ok, png_msg = _validate_png_structural_integrity(filepath)
    if not png_ok:
        return False, png_msg

    info = _parse_png_info(filepath)
    if info is None:
        return False, "Not a valid PNG file"

    w, h = info["width"], info["height"]
    if w != 64 or h != 256:
        if w == 64 and h == 64:
            return False, f"Wrong dimensions: {w}x{h} (that's a front pic — back sprites are 64x256, 4 frames)"
        return False, f"Wrong dimensions: {w}x{h} (need 64x256 — 4 frames of 64x64)"

    ct = info["color_type"]
    trns_note = " (tRNS -> will fix)" if info.get("has_trns") else ""
    if ct == 3:
        pal = info["palette_size"]
        if pal > 16:
            return False, f"Too many colours: {pal} (max 16)"
        return True, f"64x256, 4 frames, {pal} colours{trns_note}"
    elif ct in (0, 2, 4, 6):
        return True, f"64x256, 4 frames, non-indexed (colour type {ct}) — build may convert"
    else:
        return False, f"Unsupported PNG colour type: {ct}"


def _is_trainer_back_already_imported(const_name, trainers_const_path):
    """Check if a TRAINER_BACK_PIC_* constant already exists (exact match)."""
    try:
        with open(trainers_const_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return False
    return bool(re.search(rf"^#define\s+{re.escape(const_name)}\s",
                          content, re.MULTILINE))


def _insert_trainer_back_incbin(trainers_h_path, camel_name, file_stem):
    """Insert INCBIN lines for a new trainer back sprite.

    Inserts after the last gTrainerBackPic_ or gTrainerBackPalette_ line.
    Returns True on success.
    """
    try:
        with open(trainers_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find the last back pic or back palette line
    last_back_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^const\s+u(?:8|32)\s+gTrainerBackPic_\w+\[\]", line):
            last_back_idx = i
        elif re.match(r"^const\s+u16\s+gTrainerBackPalette_\w+\[\]", line):
            last_back_idx = i

    if last_back_idx is None:
        # Fallback: find gTrainerBackPic_ section marker
        for i, line in enumerate(lines):
            if "gTrainerBackPic_" in line:
                last_back_idx = i
        if last_back_idx is None:
            return False

    new_lines = [
        "\n",
        f'const u32 gTrainerBackPic_{camel_name}[] = INCBIN_U32("graphics/trainers/back_pics/{file_stem}.4bpp.smol");\n',
        f'const u16 gTrainerBackPalette_{camel_name}[] = INCBIN_U16("graphics/trainers/back_pics/{file_stem}.gbapal");\n',
    ]

    result = lines[:last_back_idx + 1] + new_lines + lines[last_back_idx + 1:]
    return _write_atomic(trainers_h_path, result)


def _insert_trainer_back_sprite_entry(trainers_h_path, const_name, camel_name,
                                       y_offset=4):
    """Insert a TRAINER_BACK_SPRITE() entry into gTrainerBacksprites[].

    Inserts before the closing '};' of the array.
    Returns True on success.
    """
    try:
        with open(trainers_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find 'gTrainerBacksprites' (note lowercase s) then its closing '};'
    in_array = False
    close_idx = None
    for i, line in enumerate(lines):
        if "gTrainerBacksprites" in line and "const" in line:
            in_array = True
        elif in_array and line.strip() == "};":
            close_idx = i
            break

    if close_idx is None:
        # Try alternate name: gTrainerBackPicSprites
        in_array = False
        for i, line in enumerate(lines):
            if "gTrainerBackPicSprites" in line and "const" in line:
                in_array = True
            elif in_array and line.strip() == "};":
                close_idx = i
                break

    if close_idx is None:
        return False

    entry = (f"    TRAINER_BACK_SPRITE({const_name}, {y_offset}, "
             f"gTrainerBackPic_{camel_name}, gTrainerBackPalette_{camel_name}, "
             f"gTrainerBackAnimTable_{camel_name}),\n")
    result = lines[:close_idx] + [entry] + lines[close_idx:]
    return _write_atomic(trainers_h_path, result)


def _insert_trainer_back_pic_constant(trainers_const_path, const_name):
    """Insert a new TRAINER_BACK_PIC_* constant.

    Back pic constants don't have a counter like front pics — they're
    just sequential defines.  Inserts after the last existing
    TRAINER_BACK_PIC_* define.

    Returns the assigned ID on success, or None on failure.
    """
    try:
        with open(trainers_const_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    # Find the last TRAINER_BACK_PIC_* define and its value
    pat = re.compile(r"^#define\s+(TRAINER_BACK_PIC_\w+)\s+(\d+)")
    last_idx = None
    last_val = -1
    for i, line in enumerate(lines):
        m = pat.match(line)
        if m:
            val = int(m.group(2))
            if val > last_val:
                last_val = val
                last_idx = i

    if last_idx is None:
        return None

    new_id = last_val + 1
    new_define = f"#define {const_name:<42}{new_id}\n"
    result = lines[:last_idx + 1] + [new_define] + lines[last_idx + 1:]

    if not _write_atomic(trainers_const_path, result):
        return None
    return new_id


def _import_trainer_back_sprite(filepath, game_path):
    """Full trainer back sprite registration pipeline with transaction rollback.

    1. Copy PNG to graphics/trainers/back_pics/
    2. Extract palette to same directory
    3. Add INCBIN lines to src/data/graphics/trainers.h (back pic section)
    4. Add TRAINER_BACK_SPRITE() entry to gTrainerBacksprites[]
    5. Add TRAINER_BACK_PIC_* constant to include/constants/trainers.h

    Returns a result dict on success, or None on failure.
    """
    filename = os.path.basename(filepath)
    file_stem = _derive_file_stem(filename)
    camel_name = _derive_trainer_pic_name(filename)
    const_name = _derive_trainer_back_const(camel_name)

    trainers_h = os.path.join(game_path, "src", "data", "graphics", "trainers.h")
    trainers_const = os.path.join(game_path, "include", "constants", "trainers.h")

    if not os.path.isfile(trainers_h):
        print(f"  {RED}Error:{RST} {trainers_h} not found")
        return None
    if not os.path.isfile(trainers_const):
        print(f"  {RED}Error:{RST} {trainers_const} not found")
        return None

    # Check for duplicate
    if _is_trainer_back_already_imported(const_name, trainers_const):
        print(f"  {RED}Error:{RST} {const_name} already exists — skipping")
        return None

    txn = _ImportTransaction()

    # Step 1: Copy PNG (strip tRNS)
    dest_dir = os.path.join(game_path, "graphics", "trainers", "back_pics")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"{file_stem}.png")
    try:
        stripped = _sanitise_sprite_png(filepath, dest_path)
        txn.track_create(dest_path)
        if stripped:
            print(f"  {DIM}Stripped tRNS chunk (PNG alpha -> GBA palette transparency){RST}")
    except OSError as e:
        print(f"  {RED}Error copying file:{RST} {e}")
        txn.rollback()
        return None

    # Step 2: Extract palette
    gbapal_path = os.path.join(dest_dir, f"{file_stem}.gbapal")
    if not _extract_gbapal_from_png(filepath, gbapal_path):
        print(f"  {RED}Error:{RST} Failed to extract palette from PNG")
        txn.rollback()
        return None
    txn.track_create(gbapal_path)

    # Step 3: Add INCBIN lines
    txn.track_modify(trainers_h)
    if not _insert_trainer_back_incbin(trainers_h, camel_name, file_stem):
        print(f"  {RED}Error:{RST} Failed to insert INCBIN lines into trainers.h")
        txn.rollback()
        return None

    # Step 4: Add TRAINER_BACK_SPRITE entry
    txn.track_modify(trainers_h)
    if not _insert_trainer_back_sprite_entry(trainers_h, const_name, camel_name):
        print(f"  {RED}Error:{RST} Failed to insert TRAINER_BACK_SPRITE entry")
        txn.rollback()
        return None

    # Step 5: Add constant
    txn.track_modify(trainers_const)
    pic_id = _insert_trainer_back_pic_constant(trainers_const, const_name)
    if pic_id is None:
        print(f"  {RED}Error:{RST} Failed to insert {const_name} constant")
        txn.rollback()
        return None

    txn.commit()
    print(f"  {DIM}Back sprite imported with y_offset=4 (default).{RST}")
    print(f"  {DIM}Edit gTrainerBacksprites[] if your sprite needs different vertical positioning.{RST}")
    return {
        "name": camel_name,
        "constant": const_name,
        "pic_id": pic_id,
        "files_modified": [
            "src/data/graphics/trainers.h",
            "include/constants/trainers.h",
        ],
        "file_copied": f"graphics/trainers/back_pics/{file_stem}.png",
    }


def _remove_trainer_back_sprite(const_name, game_path):
    """Remove a trainer back sprite from all registration points.

    1. Delete graphics/trainers/back_pics/{stem}.png + .gbapal
    2. Remove INCBIN lines from src/data/graphics/trainers.h
    3. Remove TRAINER_BACK_SPRITE entry from gTrainerBacksprites[]
    4. Remove TRAINER_BACK_PIC_* constant from include/constants/trainers.h
    """
    suffix = const_name.replace("TRAINER_BACK_PIC_", "")
    camel = _upper_snake_to_camel(suffix)
    stem = suffix.lower()
    errors = []

    # 1. Delete sprite files
    back_dir = os.path.join(game_path, "graphics", "trainers", "back_pics")
    for ext in (".png", ".gbapal", ".pal", ".4bpp", ".4bpp.smol", ".4bpp.lz"):
        fpath = os.path.join(back_dir, stem + ext)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
            except OSError as e:
                errors.append(f"delete {fpath}: {e}")

    # 2. Remove INCBIN lines from trainers.h
    trainers_h = os.path.join(game_path, "src", "data", "graphics", "trainers.h")
    if os.path.isfile(trainers_h):
        _remove_lines_matching(trainers_h, [
            f"gTrainerBackPic_{camel}",
            f"gTrainerBackPalette_{camel}",
        ])

    # 3. Remove TRAINER_BACK_SPRITE entry
    if os.path.isfile(trainers_h):
        _remove_lines_matching(trainers_h, [
            f"TRAINER_BACK_SPRITE({const_name},",
        ])

    # 4. Remove constant (no counter to decrement for back pics)
    trainers_const = os.path.join(game_path, "include", "constants", "trainers.h")
    if os.path.isfile(trainers_const):
        removed = _remove_lines_matching(trainers_const, [const_name])
        if removed == 0:
            errors.append(f"failed to remove {const_name} from trainers.h")

    return errors


# ============================================================
# ITEM ICON SUPPORT
# ============================================================

def _derive_item_icon_name(filename):
    """Convert a filename to CamelCase for item icon C identifiers.

    'mystic_gem.png' -> 'MysticGem'
    'tm-fire.png' -> 'TmFire'
    """
    return _derive_trainer_pic_name(filename)


def _validate_item_icon(filepath):
    """Validate a PNG for use as an item icon.

    Must be 24x24, indexed, <=16 colours.
    Returns (ok, message) tuple.
    """
    png_ok, png_msg = _validate_png_structural_integrity(filepath)
    if not png_ok:
        return False, png_msg

    info = _parse_png_info(filepath)
    if info is None:
        return False, "Not a valid PNG file"

    w, h = info["width"], info["height"]
    if w != 24 or h != 24:
        return False, f"Wrong dimensions: {w}x{h} (need 24x24)"

    ct = info["color_type"]
    if ct == 3:
        pal = info["palette_size"]
        if pal > 16:
            return False, f"Too many colours: {pal} (max 16)"
        return True, f"24x24, {pal} colours"
    elif ct in (0, 2, 4, 6):
        return True, f"24x24, non-indexed (colour type {ct}) — build may convert"
    else:
        return False, f"Unsupported PNG colour type: {ct}"


def _is_item_icon_already_imported(camel_name, items_h_path):
    """Check if gItemIcon_{camel_name} already exists in items.h."""
    try:
        with open(items_h_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return False
    return bool(re.search(rf"gItemIcon_{re.escape(camel_name)}\b", content))


def _insert_item_icon_incbin(items_h_path, camel_name, file_stem, use_smol):
    """Insert INCBIN lines for a new item icon into items.h.

    Adds after the last gItemIconPalette_* line.
    Uses .4bpp.smol on expansion >=1.13.0, .4bpp otherwise.
    Returns True on success.
    """
    try:
        with open(items_h_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find the last gItemIconPalette_* line
    last_pal_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^const\s+u16\s+gItemIconPalette_\w+\[\]", line):
            last_pal_idx = i

    if last_pal_idx is None:
        # Fallback: find last gItemIcon_ line
        for i, line in enumerate(lines):
            if re.match(r"^const\s+u32\s+gItemIcon_\w+\[\]", line):
                last_pal_idx = i
        if last_pal_idx is None:
            return False

    bpp_ext = ".4bpp.smol" if use_smol else ".4bpp"
    new_lines = [
        "\n",
        f'const u32 gItemIcon_{camel_name}[] = INCBIN_U32("graphics/items/icons/{file_stem}{bpp_ext}");\n',
        f'const u16 gItemIconPalette_{camel_name}[] = INCBIN_U16("graphics/items/icon_palettes/{file_stem}.gbapal");\n',
    ]

    result = lines[:last_pal_idx + 1] + new_lines + lines[last_pal_idx + 1:]
    return _write_atomic(items_h_path, result)


def _import_item_icon(filepath, game_path):
    """Full item icon registration pipeline with transaction rollback.

    1. Copy PNG to graphics/items/icons/
    2. Extract palette to graphics/items/icon_palettes/
    3. Add two INCBIN lines to src/data/graphics/items.h

    After importing, the user wires the icon to their item definition
    with .iconPic and .iconPalette in their item struct.

    Returns a result dict on success, or None on failure.
    """
    from torch.expansion_compat import detect_expansion_version, requires_version, SMOL_COMPRESSION

    filename = os.path.basename(filepath)
    file_stem = _derive_file_stem(filename)
    camel_name = _derive_item_icon_name(filename)

    items_h = os.path.join(game_path, "src", "data", "graphics", "items.h")
    if not os.path.isfile(items_h):
        print(f"  {RED}Error:{RST} {items_h} not found")
        return None

    # Check for duplicate
    if _is_item_icon_already_imported(camel_name, items_h):
        print(f"  {RED}Error:{RST} gItemIcon_{camel_name} already exists — skipping")
        return None

    version = detect_expansion_version(game_path)
    use_smol = requires_version(version, SMOL_COMPRESSION)

    txn = _ImportTransaction()

    # Step 1: Copy PNG to graphics/items/icons/
    icon_dir = os.path.join(game_path, "graphics", "items", "icons")
    os.makedirs(icon_dir, exist_ok=True)
    dest_path = os.path.join(icon_dir, f"{file_stem}.png")
    try:
        _sanitise_sprite_png(filepath, dest_path)
        txn.track_create(dest_path)
    except OSError as e:
        print(f"  {RED}Error copying file:{RST} {e}")
        txn.rollback()
        return None

    # Step 2: Extract palette to icon_palettes/
    pal_dir = os.path.join(game_path, "graphics", "items", "icon_palettes")
    os.makedirs(pal_dir, exist_ok=True)
    gbapal_path = os.path.join(pal_dir, f"{file_stem}.gbapal")
    if not _extract_gbapal_from_png(filepath, gbapal_path):
        print(f"  {RED}Error:{RST} Failed to extract palette from PNG")
        txn.rollback()
        return None
    txn.track_create(gbapal_path)

    # Step 3: Add INCBIN lines
    txn.track_modify(items_h)
    if not _insert_item_icon_incbin(items_h, camel_name, file_stem, use_smol):
        print(f"  {RED}Error:{RST} Failed to insert INCBIN lines into items.h")
        txn.rollback()
        return None

    txn.commit()
    ext_note = ".4bpp.smol" if use_smol else ".4bpp"
    print(f"  {DIM}Icon registered ({ext_note}). Reference in your item definition:{RST}")
    print(f"  {DIM}  .iconPic = gItemIcon_{camel_name},{RST}")
    print(f"  {DIM}  .iconPalette = gItemIconPalette_{camel_name},{RST}")
    return {
        "name": camel_name,
        "constant": f"gItemIcon_{camel_name}",
        "pic_id": 0,  # Item icons don't have numeric IDs
        "files_modified": ["src/data/graphics/items.h"],
        "file_copied": f"graphics/items/icons/{file_stem}.png",
    }


def _remove_item_icon(const_name, game_path):
    """Remove an item icon from all registration points.

    const_name: the gItemIcon_ name (e.g. 'gItemIcon_MysticGem')
    1. Delete PNG + build artifacts from graphics/items/icons/
    2. Delete .gbapal from graphics/items/icon_palettes/
    3. Remove INCBIN lines from src/data/graphics/items.h
    """
    # Derive camel name from const: gItemIcon_MysticGem -> MysticGem
    camel = const_name.replace("gItemIcon_", "")
    stem = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", camel).lower()
    errors = []

    # 1. Delete icon files
    icon_dir = os.path.join(game_path, "graphics", "items", "icons")
    for ext in (".png", ".4bpp", ".4bpp.smol", ".4bpp.lz"):
        fpath = os.path.join(icon_dir, stem + ext)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
            except OSError as e:
                errors.append(f"delete {fpath}: {e}")

    # 2. Delete palette
    pal_dir = os.path.join(game_path, "graphics", "items", "icon_palettes")
    gbapal = os.path.join(pal_dir, f"{stem}.gbapal")
    if os.path.isfile(gbapal):
        try:
            os.remove(gbapal)
        except OSError as e:
            errors.append(f"delete {gbapal}: {e}")

    # 3. Remove INCBIN lines
    items_h = os.path.join(game_path, "src", "data", "graphics", "items.h")
    if os.path.isfile(items_h):
        _remove_lines_matching(items_h, [
            f"gItemIcon_{camel}",
            f"gItemIconPalette_{camel}",
        ])

    return errors


# ============================================================
# ASSET TYPE REGISTRY
# ============================================================

ASSET_TYPES = {
    "trainer_sprites": {
        "name": "Trainer Sprites",
        "import_dir": "trainer_sprites",
        "file_pattern": "*.png",
        "validator": _validate_trainer_sprite,
        "importer": _import_trainer_sprite,
        "const_from_file": lambda f: _derive_trainer_pic_const(_derive_trainer_pic_name(f)),
        "dest_from_file": lambda f, gp: os.path.join(gp, "graphics", "trainers", "front_pics", _derive_file_stem(f) + ".png"),
        "description": "Front-facing trainer battle sprites (64x64, 16 colours).\n"
                       "  Place .pal or .gbapal palette files alongside PNGs for best results.\n"
                       "  If no palette is provided, the build system will extract one from the PNG.",
    },
    "overworld_sprites": {
        "name": "Overworld Sprites",
        "import_dir": "overworld_sprites",
        "file_pattern": "*.png",
        "validator": _validate_overworld_sprite,
        "importer": _import_overworld_sprite,
        "const_from_file": lambda f: _derive_overworld_const(_derive_overworld_name(f)),
        "dest_from_file": lambda f, gp: os.path.join(gp, "graphics", "object_events", "pics", "people", _derive_file_stem(f) + ".png"),
        "description": "Overworld NPC sprites (16x32 standard, 16 colours)",
    },
    "music_tracks": {
        "name": "Music Tracks",
        "import_dir": "music",
        "file_pattern": "*.mid",
        "validator": _validate_music_file,
        "importer": _import_music_track,
        "const_from_file": lambda f: _derive_music_const(_derive_music_name(f)),
        "dest_from_file": lambda f, gp: os.path.join(gp, "sound", "songs", "midi", "mus_" + _derive_music_name(f) + ".mid"),
        "description": "MIDI music tracks — converted to GBA format at build time",
    },
    "sound_effects": {
        "name": "Sound Effects",
        "import_dir": "sound_effects",
        "file_pattern": "*.s",
        "validator": _validate_se_file,
        "importer": _import_sound_effect,
        "const_from_file": lambda f: _derive_se_const(_derive_se_name(f)),
        "dest_from_file": lambda f, gp: os.path.join(gp, "sound", "songs", _derive_se_name(f) + ".s"),
        "description": "GBA sound effect assembly files (.s) — registered in songs.h",
    },
    "trainer_back_sprites": {
        "name": "Trainer Back Sprites",
        "import_dir": "trainer_back_sprites",
        "file_pattern": "*.png",
        "validator": _validate_trainer_back_sprite,
        "importer": _import_trainer_back_sprite,
        "const_from_file": lambda f: _derive_trainer_back_const(_derive_trainer_pic_name(f)),
        "dest_from_file": lambda f, gp: os.path.join(gp, "graphics", "trainers", "back_pics", _derive_file_stem(f) + ".png"),
        "description": "Back-facing trainer battle sprites (64x256 spritesheet, 4 frames, 16 colours).",
    },
    "item_icons": {
        "name": "Item Icons",
        "import_dir": "item_icons",
        "file_pattern": "*.png",
        "validator": _validate_item_icon,
        "importer": _import_item_icon,
        "const_from_file": lambda f: "gItemIcon_" + _derive_item_icon_name(f),
        "dest_from_file": lambda f, gp: os.path.join(gp, "graphics", "items", "icons", _derive_file_stem(f) + ".png"),
        "description": "Item bag icons (24x24, 16 colours).\n"
                       "  After importing, reference in your item definition with .iconPic and .iconPalette.",
    },
}


# ============================================================
# SYNC — REMOVAL HELPERS (reusable)
# ============================================================

def _get_define_value(filepath, const_name):
    """Read the integer value of a #define constant from a header file.

    Returns the int value, or None if not found.
    """
    pat = re.compile(rf"^#define\s+{re.escape(const_name)}\s+(\d+)")
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.match(line)
                if m:
                    return int(m.group(1))
    except OSError:
        pass
    return None


def _remove_lines_matching(filepath, patterns):
    """Remove lines containing any of the given patterns. Atomic write.

    patterns: list of plain strings (not regex).
    Returns number of lines removed.
    """
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return 0
    kept = []
    removed = 0
    for line in lines:
        if any(p in line for p in patterns):
            removed += 1
        else:
            kept.append(line)
    if removed > 0:
        _write_atomic(filepath, kept)
    return removed


def _remove_struct_block(filepath, identifier):
    """Remove a multi-line block starting with identifier through '};'.

    Matches lines containing the identifier, then removes through the
    next line that is just '};'.  Also removes a preceding blank line
    if present.

    Returns True if a block was removed.
    """
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    start = None
    end = None
    for i, line in enumerate(lines):
        if identifier in line:
            start = i
        elif start is not None and line.strip() == "};":
            end = i
            break

    if start is None or end is None:
        return False

    # Remove preceding blank line if present
    if start > 0 and lines[start - 1].strip() == "":
        start -= 1

    result = lines[:start] + lines[end + 1:]
    return _write_atomic(filepath, result)


def _remove_define_and_decrement(filepath, const_name, count_name):
    """Remove a #define and decrement a count #define.

    Finds '#define const_name <val>', removes it.
    Finds '#define count_name <val>', decrements by 1.
    Returns True on success.
    """
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    const_pat = re.compile(rf"^#define\s+{re.escape(const_name)}\s+\d+")
    count_pat = re.compile(rf"^(#define\s+{re.escape(count_name)}\s+)(\d+)")

    new_lines = []
    found_const = False
    for line in lines:
        if const_pat.match(line):
            found_const = True
            continue
        m = count_pat.match(line)
        if m:
            old_val = int(m.group(2))
            # Preserve alignment
            prefix = m.group(1)
            new_lines.append(f"{prefix}{old_val - 1}\n")
            continue
        new_lines.append(line)

    if not found_const:
        return False
    return _write_atomic(filepath, new_lines)


def _remove_last_music_constant(songs_h, const_name):
    """Remove a MUS_* constant and fix END_MUS to point to the previous entry.

    Returns True on success.
    """
    try:
        with open(songs_h, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find all MUS_* defines with values, the target, and END_MUS
    mus_pat = re.compile(r"^#define\s+(MUS_\w+)\s+(\d+)")
    end_pat = re.compile(r"^#define\s+END_MUS\b")
    target_pat = re.compile(rf"^#define\s+{re.escape(const_name)}\s+\d+")

    mus_entries = []  # (line_idx, name, value)
    end_mus_idx = None
    target_idx = None

    for i, line in enumerate(lines):
        if target_pat.match(line):
            target_idx = i
        m = mus_pat.match(line)
        if m:
            mus_entries.append((i, m.group(1), int(m.group(2))))
        if end_pat.match(line):
            end_mus_idx = i

    if target_idx is None or end_mus_idx is None or len(mus_entries) < 2:
        return False

    # Find the previous MUS entry (highest value that isn't the target)
    prev_name = None
    prev_val = -1
    for _, name, val in mus_entries:
        if name != const_name and val > prev_val:
            prev_name = name
            prev_val = val

    if prev_name is None:
        return False

    # Remove the target line, update END_MUS
    new_lines = []
    for i, line in enumerate(lines):
        if i == target_idx:
            continue
        if i == end_mus_idx:
            new_lines.append(f"#define END_MUS                     {prev_name}\n")
            continue
        new_lines.append(line)

    return _write_atomic(songs_h, new_lines)


def _remove_last_se_constant(songs_h, const_name):
    """Remove an SE_* constant and fix END_SE to point to the previous entry.

    Returns True on success.
    """
    try:
        with open(songs_h, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    se_pat = re.compile(r"^#define\s+(SE_\w+)\s+(\d+)")
    end_pat = re.compile(r"^#define\s+END_SE\b")
    target_pat = re.compile(rf"^#define\s+{re.escape(const_name)}\s+\d+")

    se_entries = []
    end_se_idx = None
    target_idx = None

    for i, line in enumerate(lines):
        if target_pat.match(line):
            target_idx = i
        m = se_pat.match(line)
        if m:
            se_entries.append((i, m.group(1), int(m.group(2))))
        if end_pat.match(line):
            end_se_idx = i

    if target_idx is None or end_se_idx is None or len(se_entries) < 2:
        return False

    prev_name = None
    prev_val = -1
    for _, name, val in se_entries:
        if name != const_name and val > prev_val:
            prev_name = name
            prev_val = val

    if prev_name is None:
        return False

    new_lines = []
    for i, line in enumerate(lines):
        if i == target_idx:
            continue
        if i == end_se_idx:
            new_lines.append(f"#define END_SE                      {prev_name}\n")
            continue
        new_lines.append(line)

    return _write_atomic(songs_h, new_lines)


def _can_remove_asset(type_key, const_name, game_path):
    """Check if an asset can be safely removed.

    Music and SE entries can only be removed if they are the LAST entry
    (highest ID), because song_table.inc is positional.

    Returns (can_remove, reason).
    """
    if type_key == "music_tracks":
        songs_h = os.path.join(game_path, "include", "constants", "songs.h")
        # Check if this is the last MUS entry (END_MUS points to it)
        try:
            with open(songs_h, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return False, "Cannot read songs.h"
        # Extract what END_MUS points to
        m = re.search(r"^#define\s+END_MUS\s+(\w+)", content, re.MULTILINE)
        if m and m.group(1) == const_name:
            return True, ""
        return False, (
            f"{const_name} is not the last music entry. "
            "song_table.inc is positional — removing non-last entries shifts "
            "all subsequent IDs. Remove entries in reverse order (last added "
            "first), or replace the MIDI with a silent track to keep the ID "
            "slot occupied."
        )
    elif type_key == "sound_effects":
        songs_h = os.path.join(game_path, "include", "constants", "songs.h")
        try:
            with open(songs_h, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return False, "Cannot read songs.h"
        m = re.search(r"^#define\s+END_SE\s+(\w+)", content, re.MULTILINE)
        if m and m.group(1) == const_name:
            return True, ""
        return False, (
            f"{const_name} is not the last SE entry. "
            "song_table.inc is positional — removing non-last entries shifts "
            "all subsequent IDs. Remove entries in reverse order (last added "
            "first), or replace the .s file with a silent effect to keep the "
            "ID slot occupied."
        )
    # Trainer and overworld sprites can always be removed
    return True, ""


# ============================================================
# SYNC — PER-TYPE REMOVAL
# ============================================================

def _remove_trainer_sprite(const_name, game_path):
    """Remove a trainer sprite from all 4 registration points.

    1. Delete graphics/trainers/front_pics/{stem}.png + .gbapal/.pal
    2. Remove INCBIN lines from src/data/graphics/trainers.h
    3. Remove TRAINER_SPRITE entry from gTrainerSprites[]
    4. Remove #define from include/constants/trainers.h + decrement count
    """
    # Derive names from constant
    # TRAINER_PIC_RIVAL_DAWN -> RIVAL_DAWN -> RivalDawn -> rival_dawn
    suffix = const_name.replace("TRAINER_PIC_", "")
    camel = _upper_snake_to_camel(suffix)
    stem = suffix.lower()

    errors = []

    # 1. Delete sprite files
    front_dir = os.path.join(game_path, "graphics", "trainers", "front_pics")
    for ext in (".png", ".gbapal", ".pal"):
        fpath = os.path.join(front_dir, stem + ext)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
            except OSError as e:
                errors.append(f"delete {fpath}: {e}")

    # 2. Remove INCBIN lines from trainers.h
    trainers_h = os.path.join(game_path, "src", "data", "graphics", "trainers.h")
    if os.path.isfile(trainers_h):
        _remove_lines_matching(trainers_h, [
            f"gTrainerFrontPic_{camel}",
            f"gTrainerPalette_{camel}",
        ])

    # 3. Remove TRAINER_SPRITE entry
    if os.path.isfile(trainers_h):
        _remove_lines_matching(trainers_h, [
            f"TRAINER_SPRITE({const_name},",
        ])

    # 4. Remove #define + decrement count
    trainers_const = os.path.join(game_path, "include", "constants", "trainers.h")
    if os.path.isfile(trainers_const):
        if not _remove_define_and_decrement(trainers_const, const_name, "TRAINER_PIC_COUNT"):
            errors.append("failed to remove constant from trainers.h")

    return errors


def _remove_overworld_sprite(const_name, game_path):
    """Remove an overworld sprite from all registration points.

    1. Delete graphics/object_events/pics/people/{stem}.png + build artifacts
    2. Remove INCBIN from object_event_graphics.h
    3. Remove sPicTable_ block from object_event_pic_tables.h
    4. Remove gObjectEventGraphicsInfo_ struct from object_event_graphics_info.h
    5. Remove extern + pointer from object_event_graphics_info_pointers.h
    6. Remove #define from event_objects.h + decrement count
    7. Remove custom palette (tag define, INCBIN, palette files, table entry)
    """
    suffix = const_name.replace("OBJ_EVENT_GFX_", "")
    camel = _upper_snake_to_camel(suffix)
    stem = suffix.lower()

    errors = []

    # 1. Delete sprite file + build artifacts
    sprite_path = os.path.join(game_path, "graphics", "object_events", "pics", "people", stem + ".png")
    if os.path.isfile(sprite_path):
        _delete_build_artifacts(sprite_path)
        try:
            os.remove(sprite_path)
        except OSError as e:
            errors.append(f"delete {sprite_path}: {e}")

    # 2. Remove sprite INCBIN (palette INCBIN handled in step 7)
    graphics_h = os.path.join(game_path, "src", "data", "object_events", "object_event_graphics.h")
    if os.path.isfile(graphics_h):
        _remove_lines_matching(graphics_h, [
            f"gObjectEventPic_{camel}",
        ])

    # 3. Remove sPicTable_ block
    pic_tables_h = os.path.join(game_path, "src", "data", "object_events", "object_event_pic_tables.h")
    if os.path.isfile(pic_tables_h):
        _remove_struct_block(pic_tables_h, f"sPicTable_{camel}")

    # 4. Remove gObjectEventGraphicsInfo_ struct
    info_h = os.path.join(game_path, "src", "data", "object_events", "object_event_graphics_info.h")
    if os.path.isfile(info_h):
        _remove_struct_block(info_h, f"gObjectEventGraphicsInfo_{camel}")

    # 5. Remove extern + pointer entry
    pointers_h = os.path.join(game_path, "src", "data", "object_events", "object_event_graphics_info_pointers.h")
    if os.path.isfile(pointers_h):
        _remove_lines_matching(pointers_h, [
            f"gObjectEventGraphicsInfo_{camel};",
            f"[{const_name}]",
        ])

    # 6. Remove GFX #define + decrement count
    event_obj_h = os.path.join(game_path, "include", "constants", "event_objects.h")
    if os.path.isfile(event_obj_h):
        # Detect which count name is used
        _, _, count_name = _read_ow_gfx_count(event_obj_h)
        if count_name:
            if not _remove_define_and_decrement(event_obj_h, const_name, count_name):
                errors.append("failed to remove constant from event_objects.h")
        else:
            errors.append("could not find OW GFX count constant")

    # 7. Remove custom palette registrations — only if this sprite owns
    # a custom palette AND no other sprites share it.
    pal_tag_name = _derive_palette_tag_name(camel)
    owns_palette = _has_own_custom_palette(camel, game_path)

    if owns_palette:
        # Check if other sprites still reference this palette tag
        other_users = _count_palette_users(info_h, pal_tag_name, exclude=camel)
        if other_users > 0:
            # Other sprites share this palette — don't delete the registration.
            # The remaining sprites will keep using it.
            pass
        else:
            # This sprite is the sole user — safe to remove everything
            if os.path.isfile(event_obj_h):
                _remove_lines_matching(event_obj_h, [pal_tag_name])
            movement_c = os.path.join(game_path, "src", "event_object_movement.c")
            if os.path.isfile(movement_c):
                _remove_lines_matching(movement_c, [f"gObjectEventPal_{camel},"])
            if os.path.isfile(graphics_h):
                _remove_lines_matching(graphics_h, [f"gObjectEventPal_{camel}"])
            pal_dir = os.path.join(game_path, "graphics", "object_events", "palettes")
            for ext in (".gbapal", ".pal"):
                pal_file = os.path.join(pal_dir, stem + ext)
                if os.path.isfile(pal_file):
                    try:
                        os.remove(pal_file)
                    except OSError as e:
                        errors.append(f"delete {pal_file}: {e}")

    return errors


def _remove_music_track(const_name, game_path):
    """Remove a music track (must be last entry).

    1. Delete sound/songs/midi/mus_{name}.mid
    2. Remove #define + fix END_MUS in songs.h
    3. Remove song entry from song_table.inc
    """
    name = const_name.replace("MUS_", "").lower()
    errors = []

    # 1. Delete MIDI file
    midi_path = os.path.join(game_path, "sound", "songs", "midi", f"mus_{name}.mid")
    if os.path.isfile(midi_path):
        try:
            os.remove(midi_path)
        except OSError as e:
            errors.append(f"delete {midi_path}: {e}")

    # 2. Remove constant + fix END_MUS
    songs_h = os.path.join(game_path, "include", "constants", "songs.h")
    if os.path.isfile(songs_h):
        if not _remove_last_music_constant(songs_h, const_name):
            errors.append("failed to remove constant from songs.h")

    # 3. Remove song table entry
    song_table = os.path.join(game_path, "sound", "song_table.inc")
    if os.path.isfile(song_table):
        _remove_lines_matching(song_table, [f"song mus_{name},"])

    return errors


def _remove_sound_effect(const_name, game_path):
    """Remove a sound effect (must be last entry).

    1. Delete sound/songs/{se_name}.s
    2. Remove #define + fix END_SE in songs.h
    3. Remove song entry from song_table.inc
    """
    se_name = const_name.lower()
    errors = []

    # 1. Delete .s file
    se_path = os.path.join(game_path, "sound", "songs", f"{se_name}.s")
    if os.path.isfile(se_path):
        try:
            os.remove(se_path)
        except OSError as e:
            errors.append(f"delete {se_path}: {e}")

    # 2. Remove constant + fix END_SE
    songs_h = os.path.join(game_path, "include", "constants", "songs.h")
    if os.path.isfile(songs_h):
        if not _remove_last_se_constant(songs_h, const_name):
            errors.append("failed to remove constant from songs.h")

    # 3. Remove song table entry
    song_table = os.path.join(game_path, "sound", "song_table.inc")
    if os.path.isfile(song_table):
        _remove_lines_matching(song_table, [f"song {se_name},"])

    return errors


_REMOVERS = {
    "trainer_sprites": _remove_trainer_sprite,
    "overworld_sprites": _remove_overworld_sprite,
    "music_tracks": _remove_music_track,
    "sound_effects": _remove_sound_effect,
    "trainer_back_sprites": _remove_trainer_back_sprite,
    "item_icons": _remove_item_icon,
}


# ============================================================
# BUILD ARTIFACT CLEANUP
# ============================================================

# Build artifacts generated from sprite PNGs.  The build system won't
# regenerate these if they already exist, so syncing a new PNG without
# deleting the old .4bpp leaves stale data in the ROM.
_BUILD_ARTIFACT_EXTENSIONS = (".4bpp", ".4bpp.smol", ".4bpp.lz")


def _delete_build_artifacts(png_dest_path):
    """Delete cached build artifacts for a PNG so they get regenerated.

    Given a game-side PNG path like .../rival_dawn.png, removes any
    companion .4bpp, .4bpp.smol, or .4bpp.lz files in the same directory.

    Returns list of deleted file paths (for logging).
    """
    stem = os.path.splitext(png_dest_path)[0]
    deleted = []
    for ext in _BUILD_ARTIFACT_EXTENSIONS:
        artifact = stem + ext
        if os.path.isfile(artifact):
            try:
                os.remove(artifact)
                deleted.append(artifact)
            except OSError:
                pass
    return deleted


def _has_stale_artifacts(png_dest_path):
    """Check if a game-side PNG has build artifacts older than the PNG.

    Returns True if any .4bpp/.4bpp.smol/.4bpp.lz exists alongside the
    PNG AND has an older modification time — meaning the PNG was updated
    but the build artifacts weren't regenerated.

    Artifacts that are newer than (or equal to) the PNG are from a
    successful build and don't need regeneration.

    Only call this for TORCH-managed assets (checked via manifest),
    not vanilla sprites that ship with committed .4bpp files.
    """
    stem = os.path.splitext(png_dest_path)[0]
    try:
        png_mtime = os.path.getmtime(png_dest_path)
    except OSError:
        return False
    for ext in _BUILD_ARTIFACT_EXTENSIONS:
        artifact = stem + ext
        try:
            if os.path.isfile(artifact) and os.path.getmtime(artifact) < png_mtime:
                return True
        except OSError:
            continue
    return False


# ============================================================
# SYNC SCANNER
# ============================================================

def _scan_sync_status(import_base, game_path):
    """Cross-reference import dir, game headers, and manifest.

    Returns a dict keyed by type_key, each containing:
        updates: [(filename, const_name, src_path, dest_path)]
        stale: [(filename, const_name, dest_path)]
        new_files: [(filename, const_name)]
        removals: [(filename, const_name)]
    """
    manifest = _backfill_manifest(import_base, game_path)
    result = {}

    for type_key, atype in ASSET_TYPES.items():
        updates = []
        stale = []
        new_files = []
        removals = []

        existing_consts = _detect_already_imported(type_key, game_path)
        manifest_files = manifest.get(type_key, set())
        const_fn = atype["const_from_file"]
        dest_fn = atype["dest_from_file"]
        is_png = atype["file_pattern"] == "*.png"

        # Scan import dir for files
        files = _scan_import_dir(type_key, import_base)
        import_filenames = set()
        for fpath in files:
            fname = os.path.basename(fpath)
            import_filenames.add(fname)
            const = const_fn(fname)

            if const not in existing_consts:
                # NEW — not registered in game
                new_files.append((fname, const))
            else:
                # Registered — check for changes
                dest_path = dest_fn(fname, game_path)
                if os.path.isfile(dest_path):
                    if is_png:
                        src_hash = _hash_sanitised_png(fpath)
                        dest_hash = _file_hash(dest_path)
                    else:
                        src_hash = _file_hash(fpath)
                        dest_hash = _file_hash(dest_path)
                    if src_hash and dest_hash and src_hash != dest_hash:
                        updates.append((fname, const, fpath, dest_path))
                    elif is_png and fname in manifest_files \
                            and _has_stale_artifacts(dest_path):
                        # PNG matches but TORCH-imported sprite has
                        # cached build artifacts that may be stale
                        stale.append((fname, const, dest_path))

        # Check manifest for removals
        for fname in manifest_files:
            if fname not in import_filenames:
                const = const_fn(fname)
                if const in existing_consts:
                    removals.append((fname, const))

        if updates or stale or new_files or removals:
            result[type_key] = {
                "updates": updates,
                "stale": stale,
                "new_files": new_files,
                "removals": removals,
            }

    return result


# ============================================================
# IMPORT FRAMEWORK
# ============================================================

def _ensure_import_dirs(import_base_dir):
    """Create the asset import directory structure (staging + backup)."""
    for atype in ASSET_TYPES.values():
        d = os.path.join(import_base_dir, atype["import_dir"])
        os.makedirs(d, exist_ok=True)
        # Also create imported/ backup subdirectories
        backup = os.path.join(import_base_dir, "imported", atype["import_dir"])
        os.makedirs(backup, exist_ok=True)


def _move_to_imported(import_base, type_key, filename):
    """Move a successfully imported file from staging to imported/ backup.

    Safe no-op if the source file doesn't exist (already moved or deleted).
    """
    atype = ASSET_TYPES[type_key]
    src = os.path.join(import_base, atype["import_dir"], filename)
    if not os.path.isfile(src):
        return
    dest_dir = os.path.join(import_base, "imported", atype["import_dir"])
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename)
    shutil.move(src, dest)


def _cleanup_imported_staging(import_base, game_path):
    """Move all already-imported files from staging to imported/ backup.

    Scans each staging directory, checks if the file's constant is registered
    in game headers, and moves confirmed imports to the backup directory.

    Returns the number of files moved.
    """
    moved = 0
    manifest = _read_manifest(import_base)
    for type_key, atype in ASSET_TYPES.items():
        files = _scan_import_dir(type_key, import_base)
        if not files:
            continue
        existing = _detect_already_imported(type_key, game_path)
        const_fn = atype["const_from_file"]
        for fpath in files:
            fname = os.path.basename(fpath)
            const = const_fn(fname)
            if const in existing:
                _move_to_imported(import_base, type_key, fname)
                moved += 1
    return moved


def _list_imported_backup(import_base):
    """List files in the imported/ backup directory, grouped by type.

    Returns list of dicts: [{type_key, name, files: [filename, ...]}]
    """
    result = []
    total = 0
    for type_key, atype in ASSET_TYPES.items():
        backup_dir = os.path.join(import_base, "imported", atype["import_dir"])
        if not os.path.isdir(backup_dir):
            continue
        import glob as _glob
        pattern = os.path.join(backup_dir, atype["file_pattern"])
        files = sorted(os.path.basename(f) for f in _glob.glob(pattern))
        if files:
            result.append({
                "type_key": type_key,
                "name": atype["name"],
                "files": files,
            })
            total += len(files)
    return result, total


def _resolve_import_dir(settings, workspace_expanded, proj_name):
    """Resolve the asset import base directory.

    Uses asset_import_dir from settings if set, otherwise defaults to
    <workspace>/<proj_name>/assets/.
    """
    custom = settings.get("asset_import_dir", "")
    if custom:
        return os.path.expanduser(custom)
    return os.path.join(workspace_expanded, proj_name, "assets") if proj_name else ""


def _scan_import_dir(asset_type_key, import_base_dir):
    """Find files matching the asset type's pattern in its import subdirectory.

    Returns list of absolute file paths.
    """
    atype = ASSET_TYPES[asset_type_key]
    import_dir = os.path.join(import_base_dir, atype["import_dir"])
    if not os.path.isdir(import_dir):
        return []

    import glob
    pattern = os.path.join(import_dir, atype["file_pattern"])
    return sorted(glob.glob(pattern))


def _detect_already_imported(asset_type_key, game_path):
    """Return a set of constant names already registered in the game.

    Scans the appropriate header file for existing defines.
    """
    _DETECT_CONFIG = {
        "trainer_sprites": (
            os.path.join("include", "constants", "trainers.h"),
            re.compile(r"^#define\s+(TRAINER_PIC_\w+)\s+\d+"),
        ),
        "overworld_sprites": (
            os.path.join("include", "constants", "event_objects.h"),
            re.compile(r"^#define\s+(OBJ_EVENT_GFX_\w+)\s+\d+"),
        ),
        "music_tracks": (
            os.path.join("include", "constants", "songs.h"),
            re.compile(r"^#define\s+(MUS_\w+)\s+\d+"),
        ),
        "sound_effects": (
            os.path.join("include", "constants", "songs.h"),
            re.compile(r"^#define\s+(SE_\w+)\s+\d+"),
        ),
        "trainer_back_sprites": (
            os.path.join("include", "constants", "trainers.h"),
            re.compile(r"^#define\s+(TRAINER_BACK_PIC_\w+)\s+\d+"),
        ),
        "item_icons": (
            os.path.join("src", "data", "graphics", "items.h"),
            re.compile(r"^const\s+u32\s+(gItemIcon_\w+)\[\]"),
        ),
    }

    cfg = _DETECT_CONFIG.get(asset_type_key)
    if cfg is None:
        return set()

    rel_path, pat = cfg
    full_path = os.path.join(game_path, rel_path)
    if not os.path.isfile(full_path):
        return set()

    existing = set()
    try:
        with open(full_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.match(line)
                if m:
                    existing.add(m.group(1))
    except OSError:
        pass
    return existing


def _show_import_candidates(candidates, asset_type_key):
    """Display found files with validation status.

    candidates: list of (filepath, ok, message) tuples.
    Returns (valid_list, invalid_count).
    """
    valid = []
    invalid = 0
    for i, (fpath, ok, msg) in enumerate(candidates, 1):
        fname = os.path.basename(fpath)
        if ok:
            print(f"    {i}. {WHITE}{fname}{RST} ({msg}) {GREEN}ok{RST}")
            valid.append(fpath)
        else:
            print(f"    {i}. {WHITE}{fname}{RST} ({msg}) {RED}invalid{RST}")
            invalid += 1
    return valid, invalid


def _run_import(valid_files, asset_type_key, game_path, import_base=None):
    """Import all valid files. Returns list of result dicts."""
    atype = ASSET_TYPES[asset_type_key]
    importer = atype["importer"]
    results = []
    for fpath in valid_files:
        fname = os.path.basename(fpath)
        print(f"    Importing {WHITE}{fname}{RST}...", end=" ")
        result = importer(fpath, game_path)
        if result:
            print(f"{GREEN}done{RST} ({result['constant']})")
            # Show palette status for trainer sprites
            if result.get("palette_copied"):
                pal_ext = result.get("palette_ext", ".pal/.gbapal")
                print(f"      {DIM}Palette ({pal_ext}) found and copied{RST}")
            elif asset_type_key == "trainer_sprites":
                print(f"      {DIM}No palette file found — build will extract from PNG{RST}")
            # Record in manifest
            if import_base:
                _append_manifest(import_base, asset_type_key, fname)
            results.append(result)
        else:
            print(f"{RED}failed{RST}")
    return results


# ============================================================
# ASSET MANAGER MENU
# ============================================================

def asset_manager_menu(game_path, settings, proj_name=None,
                       workspace_expanded=""):
    """Main Asset Manager TUI menu."""
    from torch.expansion_compat import detect_expansion_version

    # Vanilla pokeemerald guard
    version = detect_expansion_version(game_path)
    if version is None:
        clear_screen()
        print_logo(proj_name)
        print(BAR)
        print(f"  {RED}Asset Manager requires pokeemerald-expansion.{RST}")
        print(f"  {DIM}Vanilla pokeemerald has a different sprite registration format.{RST}")
        print(BAR)
        input(f"\n  {DIM}Press Enter to return{RST} > ")
        return

    import_base = _resolve_import_dir(settings, workspace_expanded, proj_name)
    if not import_base:
        print(f"  {RED}Error:{RST} Could not determine asset import directory.")
        input(f"\n  {DIM}Press Enter{RST} > ")
        return

    while True:
        clear_screen()
        print_logo(proj_name)
        print(BAR)
        print(f"  {WHITE}Asset Manager{RST}")
        print(BAR)
        print()
        print(f"  {DIM}Import directory:{RST} {CYAN}{import_base}{RST}")
        print()
        print(f"  {_k('1')} {WHITE}Import new assets{RST}    {DIM}Scan for and register new asset files{RST}")
        print(f"  {_k('2')} {WHITE}Browse assets{RST}        {DIM}View all game assets by category{RST}")
        print(f"  {_k('3')} {WHITE}Sync assets{RST}          {DIM}Detect changed or removed import files{RST}")
        print()
        print(f"  {_k('q')} {DIM}Back{RST}")
        print()

        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if choice in ("q", ""):
            return
        elif choice == "1":
            _import_menu(game_path, import_base, settings, proj_name)
        elif choice == "2":
            from torch.asset_browser import asset_browser_menu
            asset_browser_menu(game_path, settings, proj_name=proj_name)
        elif choice == "3":
            _sync_menu(game_path, import_base, settings, proj_name)


def _import_menu(game_path, import_base, settings, proj_name):
    """Scan for importable assets and offer to import them."""
    _ensure_import_dirs(import_base)

    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}Import Assets{RST}")
    print(BAR)
    print()

    any_found = False
    total_imported = 0
    for type_key, atype in ASSET_TYPES.items():
        files = _scan_import_dir(type_key, import_base)
        if not files:
            continue

        # Filter out already-imported
        existing = _detect_already_imported(type_key, game_path)
        const_fn = atype["const_from_file"]
        candidates = []
        for fpath in files:
            fname = os.path.basename(fpath)
            const = const_fn(fname)
            if const in existing:
                continue
            ok, msg = atype["validator"](fpath)
            candidates.append((fpath, ok, msg))

        if not candidates:
            continue

        any_found = True
        print(f"  {GOLD}{atype['name']}{RST}")
        print(f"  {DIM}{atype['description']}{RST}")
        print()

        valid, invalid = _show_import_candidates(candidates, type_key)
        print()

        if not valid:
            print(f"  {DIM}No valid files to import.{RST}")
            continue

        count = len(valid)
        prompt = f"  Import {count} valid file{'s' if count != 1 else ''}? [y/n] "
        answer = input(prompt).strip().lower()
        if answer != "y":
            print(f"  {DIM}Skipped.{RST}")
            continue

        print()
        results = _run_import(valid, type_key, game_path, import_base)
        print()

        if results:
            total_imported += len(results)
            print(f"  {GREEN}Imported {len(results)} file{'s' if len(results) != 1 else ''}.{RST}")
            print()
            for r in results:
                print(f"    {DIM}{r['constant']}{RST} (ID {r['pic_id']})")
            print()
            input(f"  {DIM}Press Enter to continue{RST} > ")
            print()

    if not any_found:
        print(f"  {DIM}No new assets found.{RST}")
        print()
        print(f"  {DIM}Drop asset files into:{RST}")
        for atype in ASSET_TYPES.values():
            d = os.path.join(import_base, atype["import_dir"])
            print(f"    {CYAN}{d}{RST}  {DIM}({atype['file_pattern']}){RST}")
        print()
    elif total_imported > 0:
        # Single build offer after all asset types are processed
        answer = input(f"  Build ROM now? [y/n] ").strip().lower()
        if answer == "y":
            _offer_build(
                game_path=game_path,
                trigger="asset_import",
                safe=True,
                auto_build=True,
                max_snapshots=settings.get("max_snapshots", 5),
            )
            return

    input(f"\n  {DIM}Press Enter to return{RST} > ")


# ============================================================
# FORCE RESYNC
# ============================================================

def _force_resync(import_base, game_path, manifest, settings, proj_name):
    """Re-copy all manifest-tracked assets and regenerate .4bpp files."""
    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}Force Regenerate{RST}")
    print(BAR)
    print()

    count = 0
    for type_key, filenames in manifest.items():
        if type_key not in ASSET_TYPES:
            continue
        atype = ASSET_TYPES[type_key]
        dest_fn = atype["dest_from_file"]
        is_png = atype["file_pattern"] == "*.png"
        import_dir = os.path.join(import_base, atype["import_dir"])

        for fname in sorted(filenames):
            src_path = os.path.join(import_dir, fname)
            if not os.path.isfile(src_path):
                continue
            dest_path = dest_fn(fname, game_path)
            print(f"  {WHITE}{fname}{RST}...", end=" ")
            try:
                if is_png:
                    _sanitise_sprite_png(src_path, dest_path)
                    _delete_build_artifacts(dest_path)
                    _regenerate_4bpp(type_key, dest_path, game_path)
                    # Update palette files for overworld sprites
                    if type_key == "overworld_sprites":
                        _update_palette_files(src_path, fname, game_path)
                else:
                    shutil.copy2(src_path, dest_path)
                print(f"{GREEN}done{RST}")
                count += 1
            except OSError as e:
                print(f"{RED}failed{RST} ({e})")

    print()
    if count > 0:
        print(f"  {GREEN}Regenerated {count} asset{'s' if count != 1 else ''}.{RST}")
        print()
        answer = input(f"  Build ROM now? [y/n] ").strip().lower()
        if answer == "y":
            _offer_build(
                game_path=game_path,
                trigger="asset_sync",
                safe=True,
                auto_build=True,
                max_snapshots=settings.get("max_snapshots", 5),
            )
            return
    else:
        print(f"  {DIM}No source files found in import directory.{RST}")

    input(f"\n  {DIM}Press Enter to return{RST} > ")


def _scan_palette_repairs(import_base, game_path):
    """Find manifest-tracked overworld sprites using shared NPC palettes.

    Returns list of (filename, camel_name, const_name) for sprites whose
    gObjectEventGraphicsInfo struct still references OBJ_EVENT_PAL_TAG_NPC_*
    instead of a custom palette.
    """
    manifest = _read_manifest(import_base)
    ow_files = manifest.get("overworld_sprites", set())
    if not ow_files:
        return []

    info_h = os.path.join(game_path, "src", "data", "object_events",
                          "object_event_graphics_info.h")
    try:
        with open(info_h, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return []

    repairs = []
    for fname in sorted(ow_files):
        camel = _derive_overworld_name(fname)
        const = _derive_overworld_const(camel)

        # Check if this sprite's struct uses a shared NPC palette
        pat = re.compile(
            rf"gObjectEventGraphicsInfo_{re.escape(camel)}\s*=\s*\{{(.*?)\}};",
            re.DOTALL)
        m = pat.search(content)
        if not m:
            continue
        struct_body = m.group(1)
        # Check for shared NPC palette tags
        if re.search(r"OBJ_EVENT_PAL_TAG_NPC_[1-4]\b", struct_body):
            repairs.append((fname, camel, const))

    return repairs


def _repair_palette(fname, camel_name, game_path, import_base):
    """Upgrade a single overworld sprite from shared NPC palette to custom.

    Uses smart palette matching: checks existing custom palettes first
    to avoid creating duplicates (e.g. Rocket_F shares Rocket_M's palette).
    Only registers a new custom palette as a last resort.
    """
    file_stem = _derive_file_stem(fname)
    atype = ASSET_TYPES["overworld_sprites"]
    import_dir = os.path.join(import_base, atype["import_dir"])
    src_png = os.path.join(import_dir, fname)

    # Fall back to game-side PNG if source isn't in import dir
    if not os.path.isfile(src_png):
        src_png = atype["dest_from_file"](fname, game_path)
    if not os.path.isfile(src_png):
        return False, "source PNG not found"

    # Smart match: check existing custom palettes before creating a new one
    match_type, match_tag, match_slot = _find_matching_palette(src_png, game_path)
    if match_type == "custom":
        tag_name = match_tag
        slot_name = match_slot
    else:
        # No existing match — register a new custom palette
        tag_name = _register_custom_palette(game_path, camel_name, file_stem, src_png)
        if tag_name is None:
            return False, "palette registration failed"
        slot_name = "PALSLOT_NPC_SPECIAL"

    # Patch the existing graphics info struct
    info_h = os.path.join(game_path, "src", "data", "object_events",
                          "object_event_graphics_info.h")
    try:
        with open(info_h, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False, "cannot read graphics info"

    in_struct = False
    changed = False
    for i, line in enumerate(lines):
        if f"gObjectEventGraphicsInfo_{camel_name}" in line and "=" in line:
            in_struct = True
        if not in_struct:
            continue
        if line.strip() == "};":
            in_struct = False
            continue
        # Replace shared NPC palette tag with matched/new custom tag
        if re.search(r"\.paletteTag\s*=\s*OBJ_EVENT_PAL_TAG_NPC_[1-4]", line):
            lines[i] = re.sub(
                r"OBJ_EVENT_PAL_TAG_NPC_[1-4]",
                tag_name, line)
            changed = True
        # Replace PALSLOT_NPC_N with the correct slot
        if re.search(r"\.paletteSlot\s*=\s*PALSLOT_NPC_[1-4]", line):
            lines[i] = re.sub(
                r"PALSLOT_NPC_[1-4]",
                slot_name, line)

    if not changed:
        return False, "could not find paletteTag to patch"

    if not _write_atomic(info_h, lines):
        return False, "failed to write patched graphics info"

    return True, tag_name


def _scan_duplicate_palettes(game_path):
    """Find custom overworld palettes that are identical and can be merged.

    Reads all TORCH-range custom palette tags, loads their .gbapal files,
    groups by identical palette data.

    Returns list of merge groups:
        [(keep_tag, keep_camel, [(dup_tag, dup_camel), ...])]
    Only groups with 2+ sprites are returned.  The first tag (lowest value)
    is the one to keep; the rest are duplicates.
    """
    event_obj_h = os.path.join(game_path, "include", "constants", "event_objects.h")
    graphics_h = os.path.join(game_path, "src", "data", "object_events",
                              "object_event_graphics.h")

    try:
        with open(event_obj_h, encoding="utf-8", errors="replace") as f:
            eo_content = f.read()
    except OSError:
        return []

    # Collect all custom tags in TORCH range
    tag_pat = re.compile(
        r"#define\s+(OBJ_EVENT_PAL_TAG_\w+)\s+(0x[0-9A-Fa-f]+)")
    custom_tags = []
    for m in tag_pat.finditer(eo_content):
        tag_name = m.group(1)
        tag_val = int(m.group(2), 16)
        if 0x1125 <= tag_val <= 0x114F:
            custom_tags.append((tag_name, tag_val))

    if len(custom_tags) < 2:
        return []

    # Sort by value so the lowest tag is kept as canonical
    custom_tags.sort(key=lambda x: x[1])

    # Read graphics.h for INCBIN paths
    try:
        with open(graphics_h, encoding="utf-8", errors="replace") as f:
            gfx_content = f.read()
    except OSError:
        return []

    # Load palette data for each tag
    tag_palettes = []  # [(tag_name, camel_name, pal_bytes)]
    for tag_name, _ in custom_tags:
        suffix = tag_name.replace("OBJ_EVENT_PAL_TAG_", "")
        camel = "".join(part.capitalize() for part in suffix.split("_") if part)
        pal_var = f"gObjectEventPal_{camel}"
        incbin_pat = re.compile(
            rf"{re.escape(pal_var)}\[\]\s*=\s*INCBIN_U(?:16|32)\(\"(.*?)\"\)")
        incbin_m = incbin_pat.search(gfx_content)
        if not incbin_m:
            continue
        gbapal_path = os.path.join(game_path, incbin_m.group(1))
        pal_data, count = _read_gbapal_file(gbapal_path)
        if pal_data is not None:
            tag_palettes.append((tag_name, camel, bytes(pal_data)))

    # Group by identical palette data (comparing all 32 bytes)
    groups = {}  # palette_bytes -> [(tag_name, camel)]
    for tag_name, camel, pal_bytes in tag_palettes:
        groups.setdefault(pal_bytes, []).append((tag_name, camel))

    # Build merge list — only groups with duplicates
    result = []
    for pal_bytes, members in groups.items():
        if len(members) < 2:
            continue
        keep_tag, keep_camel = members[0]
        dups = members[1:]
        result.append((keep_tag, keep_camel, dups))

    return result


def _dedup_palette(keep_tag, dup_tag, dup_camel, game_path):
    """Merge a duplicate custom palette into the keeper.

    1. Patch all graphics info structs using dup_tag to use keep_tag instead
    2. Remove dup_tag's palette registration (define, INCBIN, table entry)
    3. Delete dup's .gbapal and .pal files

    Returns (ok, message).
    """
    event_obj_h = os.path.join(game_path, "include", "constants", "event_objects.h")
    graphics_h = os.path.join(game_path, "src", "data", "object_events",
                              "object_event_graphics.h")
    info_h = os.path.join(game_path, "src", "data", "object_events",
                          "object_event_graphics_info.h")
    movement_c = os.path.join(game_path, "src", "event_object_movement.c")

    # Step 1: Patch all structs using dup_tag to use keep_tag
    try:
        with open(info_h, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return False, "cannot read graphics info"

    new_content = content.replace(
        f".paletteTag = {dup_tag}",
        f".paletteTag = {keep_tag}")
    if new_content != content:
        if not _write_atomic(info_h, [new_content]):
            return False, "failed to patch graphics info"

    # Step 2: Remove dup palette registrations
    # Remove tag define
    if os.path.isfile(event_obj_h):
        _remove_lines_matching(event_obj_h, [dup_tag])

    # Remove palette INCBIN
    if os.path.isfile(graphics_h):
        _remove_lines_matching(graphics_h, [f"gObjectEventPal_{dup_camel}"])

    # Remove palette table entry
    if os.path.isfile(movement_c):
        _remove_lines_matching(movement_c, [f"gObjectEventPal_{dup_camel},"])

    # Step 3: Delete palette files
    dup_stem = dup_camel[0].lower() + dup_camel[1:]
    # Convert CamelCase to lower_snake for file stem
    dup_snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", dup_camel).lower()
    pal_dir = os.path.join(game_path, "graphics", "object_events", "palettes")
    for ext in (".gbapal", ".pal"):
        pal_file = os.path.join(pal_dir, dup_snake + ext)
        if os.path.isfile(pal_file):
            try:
                os.remove(pal_file)
            except OSError:
                pass

    return True, f"merged into {keep_tag}"


def _repair_palettes_menu(import_base, game_path, settings, proj_name):
    """Interactive menu for repairing overworld sprites with shared palettes."""
    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}Repair Palettes{RST}")
    print(BAR)
    print()

    repairs = _scan_palette_repairs(import_base, game_path)
    if not repairs:
        print(f"  {GREEN}All overworld sprites have custom palettes.{RST}")
        input(f"\n  {DIM}Press Enter to return{RST} > ")
        return

    print(f"  Found {CYAN}{len(repairs)}{RST} sprite{'s' if len(repairs) != 1 else ''}"
          f" using shared NPC palettes:")
    print()
    for fname, camel, const in repairs:
        print(f"    {WHITE}{fname}{RST}  ({const})")
    print()
    print(f"  {DIM}These sprites may display with wrong colours because shared{RST}")
    print(f"  {DIM}NPC palettes don't contain their unique colours.{RST}")
    print()

    answer = input(f"  Upgrade to custom palettes? [y/n] ").strip().lower()
    if answer != "y":
        print(f"  {DIM}Skipped.{RST}")
        input(f"\n  {DIM}Press Enter to return{RST} > ")
        return

    print()
    count = 0
    for fname, camel, const in repairs:
        print(f"  {WHITE}{fname}{RST}...", end=" ")
        ok, result = _repair_palette(fname, camel, game_path, import_base)
        if ok:
            print(f"{GREEN}done{RST} ({result})")
            count += 1
        else:
            print(f"{RED}failed{RST} ({result})")

    print()
    if count > 0:
        print(f"  {GREEN}Upgraded {count} sprite{'s' if count != 1 else ''} to custom palettes.{RST}")
        print()
        answer = input(f"  Build ROM now? [y/n] ").strip().lower()
        if answer == "y":
            _offer_build(
                game_path=game_path,
                trigger="palette_repair",
                safe=True,
                auto_build=True,
                max_snapshots=settings.get("max_snapshots", 5),
            )
            return

    input(f"\n  {DIM}Press Enter to return{RST} > ")


def _dedup_palettes_flow(pal_dupes, game_path, settings):
    """Interactive flow for merging duplicate palettes."""
    clear_screen()
    print_logo(None)
    print(BAR)
    print(f"  {WHITE}Deduplicate Palettes{RST}")
    print(BAR)
    print()

    total = sum(len(dups) for _, _, dups in pal_dupes)
    print(f"  Found {CYAN}{total}{RST} duplicate palette{'s' if total != 1 else ''}"
          f" across {len(pal_dupes)} group{'s' if len(pal_dupes) != 1 else ''}:")
    print()
    for keep_tag, keep_camel, dups in pal_dupes:
        dup_names = ", ".join(c for _, c in dups)
        print(f"    {WHITE}{keep_camel}{RST} {DIM}(keep){RST}")
        for _, dup_camel in dups:
            print(f"      {DIM}{dup_camel} -> merge into {keep_tag}{RST}")
    print()
    print(f"  {DIM}Duplicate sprites will share the first sprite's palette tag.{RST}")
    print(f"  {DIM}Redundant palette files and registrations will be removed.{RST}")
    print()

    answer = input(f"  Merge duplicate palettes? [y/n] ").strip().lower()
    if answer != "y":
        print(f"  {DIM}Skipped.{RST}")
        input(f"\n  {DIM}Press Enter to return{RST} > ")
        return

    print()
    count = 0
    for keep_tag, keep_camel, dups in pal_dupes:
        for dup_tag, dup_camel in dups:
            print(f"  {WHITE}{dup_camel}{RST}...", end=" ")
            ok, result = _dedup_palette(keep_tag, dup_tag, dup_camel, game_path)
            if ok:
                print(f"{GREEN}done{RST} ({result})")
                count += 1
            else:
                print(f"{RED}failed{RST} ({result})")

    print()
    if count > 0:
        print(f"  {GREEN}Merged {count} duplicate palette{'s' if count != 1 else ''}.{RST}")
        print()
        answer = input(f"  Build ROM now? [y/n] ").strip().lower()
        if answer == "y":
            _offer_build(
                game_path=game_path,
                trigger="palette_dedup",
                safe=True,
                auto_build=True,
                max_snapshots=settings.get("max_snapshots", 5),
            )
            return

    input(f"\n  {DIM}Press Enter to return{RST} > ")


# ============================================================
# SYNC MENU
# ============================================================

def _sync_menu(game_path, import_base, settings, proj_name):
    """Detect changed or removed import files and offer to sync."""
    _ensure_import_dirs(import_base)

    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}Sync Assets{RST}")
    print(BAR)
    print()
    print(f"  {DIM}Scanning for changes...{RST}")

    status = _scan_sync_status(import_base, game_path)
    manifest = _read_manifest(import_base)
    has_tracked = any(manifest.values())

    pal_repairs = _scan_palette_repairs(import_base, game_path)
    pal_dupes = _scan_duplicate_palettes(game_path)
    dup_count = sum(len(dups) for _, _, dups in pal_dupes)

    if not status:
        print(f"\n  {GREEN}All imported assets are up to date.{RST}")
        if has_tracked or pal_repairs or pal_dupes:
            print()
            if has_tracked:
                print(f"  {_k('r')} {WHITE}Force regenerate{RST}  {DIM}Re-copy all tracked assets and rebuild .4bpp files{RST}")
            if pal_repairs:
                print(f"  {_k('p')} {WHITE}Repair palettes{RST}  {DIM}Upgrade {len(pal_repairs)} sprite{'s' if len(pal_repairs) != 1 else ''} from shared to custom palettes{RST}")
            if pal_dupes:
                print(f"  {_k('d')} {WHITE}Deduplicate palettes{RST}  {DIM}Merge {dup_count} duplicate palette{'s' if dup_count != 1 else ''}{RST}")
            print(f"  {_k('q')} {DIM}Back{RST}")
            print()
            choice = input(f"  {GOLD}>{RST} ").strip().lower()
            if choice == "r" and has_tracked:
                _force_resync(import_base, game_path, manifest, settings, proj_name)
                return
            if choice == "p" and pal_repairs:
                _repair_palettes_menu(import_base, game_path, settings, proj_name)
                return
            if choice == "d" and pal_dupes:
                _dedup_palettes_flow(pal_dupes, game_path, settings)
                return
        else:
            input(f"\n  {DIM}Press Enter to return{RST} > ")
        return

    # Show summary
    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}Sync Assets{RST}")
    print(BAR)
    print()

    anything_changed = False

    for type_key in ASSET_TYPES:
        if type_key not in status:
            continue
        info = status[type_key]
        type_name = ASSET_TYPES[type_key]["name"]
        updates = info["updates"]
        stale = info["stale"]
        new_files = info["new_files"]
        removals = info["removals"]

        print(f"  {GOLD}{type_name}{RST}")

        if updates:
            print(f"    {CYAN}UPDATE{RST}: {len(updates)} changed file{'s' if len(updates) != 1 else ''}")
            for fname, const, _, _ in updates:
                print(f"      {WHITE}{fname}{RST} ({const})")
        if stale:
            print(f"    {CYAN}STALE{RST}: {len(stale)} file{'s' if len(stale) != 1 else ''} with outdated build cache")
            for fname, const, _ in stale:
                print(f"      {WHITE}{fname}{RST} ({const}) {DIM}.4bpp older than .png{RST}")
        if new_files:
            print(f"    {GREEN}NEW{RST}: {len(new_files)} unregistered file{'s' if len(new_files) != 1 else ''} (use Import)")
            for fname, const in new_files:
                print(f"      {DIM}{fname}{RST}")
        if removals:
            print(f"    {RED}REMOVED{RST}: {len(removals)} missing from import dir")
            for fname, const in removals:
                print(f"      {WHITE}{fname}{RST} ({const})")
        print()

    # Process updates
    for type_key in ASSET_TYPES:
        if type_key not in status:
            continue
        updates = status[type_key]["updates"]
        if not updates:
            continue
        type_name = ASSET_TYPES[type_key]["name"]
        is_png = ASSET_TYPES[type_key]["file_pattern"] == "*.png"
        count = len(updates)
        answer = input(f"  Update {count} changed {type_name.lower()}? [y/n] ").strip().lower()
        if answer != "y":
            print(f"  {DIM}Skipped.{RST}")
            continue

        for fname, const, src_path, dest_path in updates:
            print(f"    Updating {WHITE}{fname}{RST}...", end=" ")
            try:
                if is_png:
                    _sanitise_sprite_png(src_path, dest_path)
                    # Delete stale build artifacts and regenerate with
                    # correct metatile dimensions
                    _delete_build_artifacts(dest_path)
                    _regenerate_4bpp(type_key, dest_path, game_path)
                    # Update palette files for overworld sprites
                    if type_key == "overworld_sprites":
                        _update_palette_files(src_path, fname, game_path)
                else:
                    shutil.copy2(src_path, dest_path)
                print(f"{GREEN}done{RST}")
                anything_changed = True
            except OSError as e:
                print(f"{RED}failed{RST} ({e})")
        print()

    # Process stale build artifacts
    all_stale = []
    for type_key in ASSET_TYPES:
        if type_key not in status:
            continue
        for fname, const, dest_path in status[type_key]["stale"]:
            all_stale.append((type_key, fname, dest_path))
    if all_stale:
        count = len(all_stale)
        answer = input(f"  Regenerate {count} stale build artifact{'s' if count != 1 else ''}? [y/n] ").strip().lower()
        if answer == "y":
            for tk, fname, dest_path in all_stale:
                deleted = _delete_build_artifacts(dest_path)
                if deleted:
                    for d in deleted:
                        print(f"    {DIM}Deleted {os.path.basename(d)}{RST}")
                _regenerate_4bpp(tk, dest_path, game_path)
                anything_changed = True
            print()
        else:
            print(f"  {DIM}Skipped.{RST}")

    # Process removals
    for type_key in ASSET_TYPES:
        if type_key not in status:
            continue
        removals = status[type_key]["removals"]
        if not removals:
            continue
        type_name = ASSET_TYPES[type_key]["name"]

        for fname, const in removals:
            # Check if removal is allowed
            can_rm, reason = _can_remove_asset(type_key, const, game_path)
            if not can_rm:
                print(f"  {RED}Cannot remove {fname}:{RST} {reason}")
                print()
                continue

            print(f"  {RED}Asset Removal{RST}")
            print(f"  {DIM}WARNING: Removing assets can break NPCs, trainers, and scripts{RST}")
            print(f"  {DIM}that reference them. Verify no dependencies exist before removing.{RST}")
            print()
            print(f"  Remove {WHITE}{fname}{RST} ({CYAN}{const}{RST})?")
            print(f"  {DIM}This will delete the file and all header registrations.{RST}")
            answer = input(f"  [y/n] ").strip().lower()

            if answer != "y":
                print(f"  {DIM}Skipped.{RST}")
                print()
                continue

            remover = _REMOVERS.get(type_key)
            if not remover:
                print(f"  {RED}No remover for type {type_key}{RST}")
                print()
                continue

            errors = remover(const, game_path)
            if errors:
                print(f"  {RED}Removed with warnings:{RST}")
                for err in errors:
                    print(f"    {DIM}{err}{RST}")
            else:
                print(f"  {GREEN}Removed {const}{RST}")
            anything_changed = True

            # Remove from manifest
            manifest = _read_manifest(import_base)
            mset = manifest.get(type_key, set())
            mset.discard(fname)
            if mset:
                manifest[type_key] = mset
            else:
                manifest.pop(type_key, None)
            _write_manifest(import_base, manifest)
            print()

    # Offer palette repair if needed
    if pal_repairs:
        print(f"  {CYAN}{len(pal_repairs)}{RST} sprite{'s' if len(pal_repairs) != 1 else ''}"
              f" using shared NPC palettes (may have wrong colours).")
        answer = input(f"  Upgrade to custom palettes? [y/n] ").strip().lower()
        if answer == "y":
            for fname, camel, const in pal_repairs:
                print(f"    {WHITE}{fname}{RST}...", end=" ")
                ok, result = _repair_palette(fname, camel, game_path, import_base)
                if ok:
                    print(f"{GREEN}done{RST} ({result})")
                    anything_changed = True
                else:
                    print(f"{RED}failed{RST} ({result})")
            print()

    # Offer palette deduplication if needed
    if pal_dupes:
        print(f"  {CYAN}{dup_count}{RST} duplicate palette{'s' if dup_count != 1 else ''}"
              f" can be merged.")
        for keep_tag, keep_camel, dups in pal_dupes:
            dup_names = ", ".join(c for _, c in dups)
            print(f"    {DIM}{dup_names} -> {keep_tag}{RST}")
        answer = input(f"  Merge duplicate palettes? [y/n] ").strip().lower()
        if answer == "y":
            for keep_tag, keep_camel, dups in pal_dupes:
                for dup_tag, dup_camel in dups:
                    print(f"    {WHITE}{dup_camel}{RST}...", end=" ")
                    ok, result = _dedup_palette(keep_tag, dup_tag, dup_camel, game_path)
                    if ok:
                        print(f"{GREEN}done{RST} ({result})")
                        anything_changed = True
                    else:
                        print(f"{RED}failed{RST} ({result})")
            print()

    if anything_changed:
        answer = input(f"  Build ROM now? [y/n] ").strip().lower()
        if answer == "y":
            _offer_build(
                game_path=game_path,
                trigger="asset_sync",
                safe=True,
                auto_build=True,
                max_snapshots=settings.get("max_snapshots", 5),
            )
            return

    input(f"\n  {DIM}Press Enter to return{RST} > ")


# ============================================================
# CLI ENTRY POINT
# ============================================================

def assets_command(game_path, settings, proj_name=None,
                   workspace_expanded=""):
    """CLI entry point for 'torch assets'."""
    asset_manager_menu(game_path, settings, proj_name=proj_name,
                       workspace_expanded=workspace_expanded)
