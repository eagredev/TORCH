"""TORCH Tileset Assistant -- create, browse, and validate tilesets.

Scaffolds new secondary tilesets with proper directory structure and C
registration, copies existing tilesets as starting points, browses all
tilesets with map usage info, and validates tileset completeness.
"""
# TORCH_MODULE: Tileset Assistant
# TORCH_GROUP: Tools

import json
import os
import re
import shutil
import struct

from torch.colours import GOLD, WHITE, CYAN, DIM, RED, GREEN, RST, BAR
from torch.config import _nav_keys, SETTINGS_DEFAULTS
from torch.filewriter import _write_atomic
from torch.list_widget import (
    ListState, handle_input, visible_range,
    overflow_above, overflow_below, marker, footer_hint, guard_bounds,
)
from torch.ui import clear_screen, print_logo, _k, _set_terminal_title

TILESET_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Name derivation
# ---------------------------------------------------------------------------

def _derive_names(user_input):
    """Derive C name and directory name from user input.

    Returns (camel_name, dir_name) -- e.g. ("MyCave", "my_cave").
    """
    raw = user_input.strip()
    if not raw:
        return None, None

    # If user gives CamelCase already, keep it
    if re.match(r'^[A-Z][a-zA-Z0-9]+$', raw) and not raw.islower():
        camel = raw
    else:
        # Split on spaces, underscores, hyphens
        parts = re.split(r'[\s_\-]+', raw)
        camel = "".join(p.capitalize() for p in parts if p)

    if not camel:
        return None, None

    # Directory: CamelCase -> snake_case
    dir_name = re.sub(r'([A-Z])', r'_\1', camel).strip('_').lower()
    # Clean up double underscores
    dir_name = re.sub(r'_+', '_', dir_name)

    return camel, dir_name


def _tileset_const(camel_name):
    """Return the gTileset_X constant name."""
    return f"gTileset_{camel_name}"


# ---------------------------------------------------------------------------
# Compression format detection
# ---------------------------------------------------------------------------

def _detect_compression(game_path):
    """Detect compression suffix used by existing secondary tilesets.

    Scans graphics.h for INCBIN patterns on secondary tilesets and returns
    the most common suffix (e.g. ".4bpp.fastSmol", ".4bpp.lz", ".4bpp.smol").
    Falls back to ".4bpp.lz" if nothing is found.
    """
    gfx_path = os.path.join(game_path, "src", "data", "tilesets", "graphics.h")
    if not os.path.isfile(gfx_path):
        return ".4bpp.lz"

    try:
        with open(gfx_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return ".4bpp.lz"

    # Match: INCBIN_U32("data/tilesets/secondary/.../tiles.SUFFIX")
    hits = re.findall(
        r'INCBIN_U32\("data/tilesets/secondary/[^"]+/tiles(\.[^"]+)"\)',
        text,
    )
    if not hits:
        return ".4bpp.lz"

    # Most common suffix wins
    counts = {}
    for h in hits:
        counts[h] = counts.get(h, 0) + 1
    return max(counts, key=counts.get)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _scan_tilesets(game_path):
    """Scan all tilesets (primary + secondary) with metadata.

    Returns list of dicts:
        name        -- display name ("Petalburg")
        dir_name    -- directory name ("petalburg")
        camel_name  -- CamelCase name ("Petalburg")
        constant    -- C constant ("gTileset_Petalburg")
        kind        -- "primary" or "secondary"
        path        -- relative path from game root
        registered  -- True if found in headers.h
    """
    results = []

    for kind in ("primary", "secondary"):
        ts_dir = os.path.join(game_path, "data", "tilesets", kind)
        if not os.path.isdir(ts_dir):
            continue
        try:
            dirs = sorted(os.listdir(ts_dir))
        except OSError:
            continue

        for name in dirs:
            full = os.path.join(ts_dir, name)
            if not os.path.isdir(full):
                continue
            # Derive CamelCase from directory name
            parts = name.split("_")
            camel = "".join(p.capitalize() for p in parts if p)
            results.append({
                "name": name.replace("_", " ").title(),
                "dir_name": name,
                "camel_name": camel,
                "constant": f"gTileset_{camel}",
                "kind": kind,
                "path": f"data/tilesets/{kind}/{name}/",
                "registered": False,
            })

    # Check registration in headers.h
    headers_path = os.path.join(game_path, "src", "data", "tilesets", "headers.h")
    registered = set()
    if os.path.isfile(headers_path):
        try:
            with open(headers_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.match(r'const\s+struct\s+Tileset\s+(gTileset_\w+)', line)
                    if m:
                        registered.add(m.group(1))
        except OSError:
            pass

    for ts in results:
        ts["registered"] = ts["constant"] in registered

    return results


def _get_tileset_maps(game_path):
    """Return dict mapping tileset constant -> list of layout names that use it.

    Parses layouts.json to find which layouts reference each tileset.
    """
    layouts_path = os.path.join(game_path, "data", "layouts", "layouts.json")
    usage = {}
    if not os.path.isfile(layouts_path):
        return usage

    try:
        with open(layouts_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return usage

    for layout in data.get("layouts", []):
        for field in ("primary_tileset", "secondary_tileset"):
            ts = layout.get(field, "")
            if ts:
                usage.setdefault(ts, []).append(layout.get("name", layout.get("id", "?")))

    return usage


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

_REQUIRED_FILES = [
    "metatiles.bin",
    "metatile_attributes.bin",
]

_PALETTE_COUNT = 16


def _check_tileset_health(game_path, tileset):
    """Validate a single tileset for completeness.

    Returns list of (severity, message) tuples.
    severity: "error" or "warning".
    """
    issues = []
    ts_dir = os.path.join(game_path, tileset["path"])

    if not os.path.isdir(ts_dir):
        issues.append(("error", "Directory does not exist"))
        return issues

    # Check required binary files
    for req in _REQUIRED_FILES:
        if not os.path.isfile(os.path.join(ts_dir, req)):
            issues.append(("error", f"Missing {req}"))

    # Check for tiles (either .4bpp or .png)
    has_tiles = (
        os.path.isfile(os.path.join(ts_dir, "tiles.png"))
        or any(
            f.startswith("tiles.4bpp")
            for f in os.listdir(ts_dir)
            if os.path.isfile(os.path.join(ts_dir, f))
        )
    )
    if not has_tiles:
        issues.append(("error", "Missing tiles (no tiles.png or tiles.4bpp*)"))

    # Check palettes
    pal_dir = os.path.join(ts_dir, "palettes")
    if not os.path.isdir(pal_dir):
        issues.append(("error", "Missing palettes/ directory"))
    else:
        for i in range(_PALETTE_COUNT):
            gbapal = os.path.join(pal_dir, f"{i:02d}.gbapal")
            if not os.path.isfile(gbapal):
                issues.append(("warning", f"Missing palettes/{i:02d}.gbapal"))

    # Check C registration
    reg_issues = _check_registration(game_path, tileset["camel_name"],
                                      tileset["dir_name"], tileset["kind"])
    issues.extend(reg_issues)

    return issues


def _check_registration(game_path, camel_name, dir_name, kind):
    """Check if a tileset is registered in all 3 C header files.

    Returns list of (severity, message) tuples.
    """
    issues = []
    src = os.path.join(game_path, "src", "data", "tilesets")
    const = f"gTileset_{camel_name}"

    # headers.h
    headers_path = os.path.join(src, "headers.h")
    if os.path.isfile(headers_path):
        try:
            with open(headers_path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if const not in text:
                issues.append(("error", f"Not registered in headers.h"))
        except OSError:
            pass
    else:
        issues.append(("error", "headers.h not found"))

    # graphics.h
    gfx_path = os.path.join(src, "graphics.h")
    tiles_const = f"gTilesetTiles_{camel_name}"
    pals_const = f"gTilesetPalettes_{camel_name}"
    if os.path.isfile(gfx_path):
        try:
            with open(gfx_path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if tiles_const not in text:
                issues.append(("error", f"Not registered in graphics.h (tiles)"))
            if pals_const not in text:
                issues.append(("error", f"Not registered in graphics.h (palettes)"))
        except OSError:
            pass
    else:
        issues.append(("error", "graphics.h not found"))

    # metatiles.h
    meta_path = os.path.join(src, "metatiles.h")
    meta_const = f"gMetatiles_{camel_name}"
    attr_const = f"gMetatileAttributes_{camel_name}"
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if meta_const not in text:
                issues.append(("error", f"Not registered in metatiles.h (metatiles)"))
            if attr_const not in text:
                issues.append(("error", f"Not registered in metatiles.h (attributes)"))
        except OSError:
            pass
    else:
        issues.append(("error", "metatiles.h not found"))

    return issues


def _check_orphaned_registrations(game_path):
    """Find C registrations that point to non-existent tileset directories.

    Returns list of (constant, expected_path) tuples.
    """
    orphans = []
    gfx_path = os.path.join(game_path, "src", "data", "tilesets", "graphics.h")
    if not os.path.isfile(gfx_path):
        return orphans

    try:
        with open(gfx_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return orphans

    # Find all tileset directory references
    for m in re.finditer(
        r'INCBIN_U\d+\("(data/tilesets/(primary|secondary)/([^/]+))/[^"]*"\)',
        text,
    ):
        rel_dir = m.group(1)
        full_dir = os.path.join(game_path, rel_dir)
        if not os.path.isdir(full_dir):
            # Derive the constant name
            parts = m.group(3).split("_")
            camel = "".join(p.capitalize() for p in parts if p)
            const = f"gTileset_{camel}"
            entry = (const, rel_dir)
            if entry not in orphans:
                orphans.append(entry)

    return orphans


# ---------------------------------------------------------------------------
# Creation — empty palette / directory scaffolding
# ---------------------------------------------------------------------------

def _create_empty_gbapal(filepath):
    """Write a 32-byte empty GBA palette file (all zeros = transparent)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(b'\x00' * 32)


def _create_empty_pal(filepath):
    """Write an empty JASC-PAL text palette file (16 black colors)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    lines = ["JASC-PAL\n", "0100\n", "16\n"]
    for _ in range(16):
        lines.append("0 0 0\n")
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _create_tileset_scaffold(game_path, dir_name):
    """Create an empty tileset directory with minimal valid files.

    Creates:
    - metatiles.bin (empty)
    - metatile_attributes.bin (empty)
    - 16 empty .gbapal + .pal files

    Does NOT create tiles.png or tiles.4bpp — Porymap creates these
    when the user first opens the tileset.

    Returns the full path to the created directory.
    """
    ts_dir = os.path.join(game_path, "data", "tilesets", "secondary", dir_name)
    os.makedirs(ts_dir, exist_ok=True)

    # Empty binary files (0 bytes is valid — means no metatiles defined yet)
    for binfile in ("metatiles.bin", "metatile_attributes.bin"):
        path = os.path.join(ts_dir, binfile)
        with open(path, "wb") as f:
            pass  # 0 bytes

    # Palettes
    pal_dir = os.path.join(ts_dir, "palettes")
    os.makedirs(pal_dir, exist_ok=True)
    for i in range(_PALETTE_COUNT):
        _create_empty_gbapal(os.path.join(pal_dir, f"{i:02d}.gbapal"))
        _create_empty_pal(os.path.join(pal_dir, f"{i:02d}.pal"))

    return ts_dir


def _copy_tileset_dir(game_path, source_dir_name, source_kind, dest_dir_name):
    """Deep-copy a tileset directory to a new secondary tileset.

    Returns the full path to the new directory, or None on error.
    """
    src = os.path.join(game_path, "data", "tilesets", source_kind, source_dir_name)
    dst = os.path.join(game_path, "data", "tilesets", "secondary", dest_dir_name)

    if not os.path.isdir(src):
        return None
    if os.path.exists(dst):
        return None  # already exists

    shutil.copytree(src, dst)
    return dst


# ---------------------------------------------------------------------------
# C registration — insert into header files
# ---------------------------------------------------------------------------

def _insert_graphics_h(game_path, camel_name, dir_name, compression):
    """Insert tiles INCBIN + palette array into graphics.h.

    Appends at end of file. Returns True on success.
    """
    path = os.path.join(game_path, "src", "data", "tilesets", "graphics.h")
    if not os.path.isfile(path):
        return False

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Build new lines
    new_lines = ["\n"]
    new_lines.append(
        f'const u32 gTilesetTiles_{camel_name}[] = '
        f'INCBIN_U32("data/tilesets/secondary/{dir_name}/tiles{compression}");\n'
    )
    new_lines.append("\n")
    new_lines.append(f"const u16 gTilesetPalettes_{camel_name}[][16] =\n")
    new_lines.append("{\n")
    for i in range(_PALETTE_COUNT):
        comma = "," if i < _PALETTE_COUNT - 1 else ","
        new_lines.append(
            f'    INCBIN_U16("data/tilesets/secondary/{dir_name}/'
            f'palettes/{i:02d}.gbapal"){comma}\n'
        )
    new_lines.append("};\n")

    lines.extend(new_lines)
    return _write_atomic(path, lines)


def _insert_metatiles_h(game_path, camel_name, dir_name):
    """Insert metatile + attribute INCBINs into metatiles.h.

    Appends at end of file. Returns True on success.
    """
    path = os.path.join(game_path, "src", "data", "tilesets", "metatiles.h")
    if not os.path.isfile(path):
        return False

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    new_lines = ["\n"]
    new_lines.append(
        f'const u16 gMetatiles_{camel_name}[] = '
        f'INCBIN_U16("data/tilesets/secondary/{dir_name}/metatiles.bin");\n'
    )
    new_lines.append(
        f'const u16 gMetatileAttributes_{camel_name}[] = '
        f'INCBIN_U16("data/tilesets/secondary/{dir_name}/metatile_attributes.bin");\n'
    )

    lines.extend(new_lines)
    return _write_atomic(path, lines)


def _insert_headers_h(game_path, camel_name):
    """Insert struct Tileset definition into headers.h.

    Appends at end of file. Returns True on success.
    """
    path = os.path.join(game_path, "src", "data", "tilesets", "headers.h")
    if not os.path.isfile(path):
        return False

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    new_lines = ["\n"]
    new_lines.append(f"const struct Tileset gTileset_{camel_name} =\n")
    new_lines.append("{\n")
    new_lines.append("    .isCompressed = TRUE,\n")
    new_lines.append("    .isSecondary = TRUE,\n")
    new_lines.append(f"    .tiles = gTilesetTiles_{camel_name},\n")
    new_lines.append(f"    .palettes = gTilesetPalettes_{camel_name},\n")
    new_lines.append(f"    .metatiles = gMetatiles_{camel_name},\n")
    new_lines.append(f"    .metatileAttributes = gMetatileAttributes_{camel_name},\n")
    new_lines.append("    .callback = NULL,\n")
    new_lines.append("};\n")

    lines.extend(new_lines)
    return _write_atomic(path, lines)


def _register_tileset(game_path, camel_name, dir_name, compression=None):
    """Register a new tileset in all 3 C header files.

    Returns (success, errors) where errors is a list of strings.
    """
    if compression is None:
        compression = _detect_compression(game_path)

    errors = []
    if not _insert_graphics_h(game_path, camel_name, dir_name, compression):
        errors.append("Failed to update graphics.h")
    if not _insert_metatiles_h(game_path, camel_name, dir_name):
        errors.append("Failed to update metatiles.h")
    if not _insert_headers_h(game_path, camel_name):
        errors.append("Failed to update headers.h")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# High-level creation
# ---------------------------------------------------------------------------

def create_tileset_copy(game_path, source_name, new_name):
    """Copy an existing tileset and register the copy.

    source_name: directory name of source (e.g. "cave")
    new_name: user input for new name (e.g. "my cave")

    Returns (success, camel_name, dir_name, messages).
    """
    camel, dir_name = _derive_names(new_name)
    if not camel:
        return False, None, None, ["Invalid tileset name."]

    msgs = []

    # Find source
    tilesets = _scan_tilesets(game_path)
    source = None
    for ts in tilesets:
        if ts["dir_name"] == source_name:
            source = ts
            break
    if not source:
        return False, camel, dir_name, [f"Source tileset '{source_name}' not found."]

    # Check destination doesn't exist
    dest = os.path.join(game_path, "data", "tilesets", "secondary", dir_name)
    if os.path.exists(dest):
        return False, camel, dir_name, [f"Tileset directory '{dir_name}' already exists."]

    # Copy directory
    result = _copy_tileset_dir(game_path, source["dir_name"], source["kind"], dir_name)
    if not result:
        return False, camel, dir_name, ["Failed to copy tileset directory."]
    msgs.append(f"Copied directory data/tilesets/secondary/{dir_name}/")

    # Register in C headers
    compression = _detect_compression(game_path)
    ok, errors = _register_tileset(game_path, camel, dir_name, compression)
    if ok:
        msgs.append("Registered in graphics.h")
        msgs.append("Registered in metatiles.h")
        msgs.append("Registered in headers.h")
    else:
        msgs.extend(errors)

    return ok, camel, dir_name, msgs


def create_tileset_scaffold(game_path, new_name):
    """Scaffold a new empty tileset and register it.

    Returns (success, camel_name, dir_name, messages).
    """
    camel, dir_name = _derive_names(new_name)
    if not camel:
        return False, None, None, ["Invalid tileset name."]

    msgs = []

    # Check destination doesn't exist
    dest = os.path.join(game_path, "data", "tilesets", "secondary", dir_name)
    if os.path.exists(dest):
        return False, camel, dir_name, [f"Tileset directory '{dir_name}' already exists."]

    # Create scaffold
    _create_tileset_scaffold(game_path, dir_name)
    msgs.append(f"Created directory data/tilesets/secondary/{dir_name}/")
    msgs.append("Created empty metatiles.bin")
    msgs.append("Created empty metatile_attributes.bin")
    msgs.append("Created 16 empty palettes")

    # Register in C headers
    compression = _detect_compression(game_path)
    ok, errors = _register_tileset(game_path, camel, dir_name, compression)
    if ok:
        msgs.append("Registered in graphics.h")
        msgs.append("Registered in metatiles.h")
        msgs.append("Registered in headers.h")
    else:
        msgs.extend(errors)

    return ok, camel, dir_name, msgs


# ---------------------------------------------------------------------------
# Cross-decomp import — format detection
# ---------------------------------------------------------------------------

def _find_project_root(path):
    """Walk up from path to find the decomp project root.

    Looks for a directory containing src/data/tilesets/headers.h or
    include/fieldmap.h — typical markers for a pokeemerald/pokefirered project.

    Returns the root path, or None if not found.
    """
    cur = os.path.abspath(path)
    for _ in range(10):
        if os.path.isfile(os.path.join(cur, "include", "fieldmap.h")):
            return cur
        if os.path.isfile(os.path.join(cur, "src", "data", "tilesets", "headers.h")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _read_tiles_per_metatile(fieldmap_path):
    """Parse NUM_TILES_PER_METATILE from a fieldmap.h file.

    Returns int (8 or 12), or None if not found.
    """
    try:
        with open(fieldmap_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(
                    r'\s*#define\s+NUM_TILES_PER_METATILE\s+(\d+)', line
                )
                if m:
                    return int(m.group(1))
    except OSError:
        pass
    return None


def _read_primary_tile_count(fieldmap_path):
    """Parse NUM_TILES_IN_PRIMARY from a fieldmap.h file.

    This is the tile index offset where secondary tileset tiles begin.
    FireRed uses 640, Emerald expansion uses 512.
    Returns int or None if not found.
    """
    try:
        with open(fieldmap_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(
                    r'\s*#define\s+NUM_TILES_IN_PRIMARY\s+(\d+)', line
                )
                if m:
                    return int(m.group(1))
    except OSError:
        pass
    return None


def _detect_attr_bytes(metatiles_path, attrs_path, tiles_per):
    """Infer attribute byte width from file sizes.

    metatile_count = metatiles_size / (tiles_per * 2)
    attr_bytes_per = attrs_size / metatile_count

    Returns int (2 or 4), or None if files are missing/empty.
    """
    try:
        mt_size = os.path.getsize(metatiles_path)
        at_size = os.path.getsize(attrs_path)
    except OSError:
        return None
    if mt_size == 0 or at_size == 0:
        return None
    bytes_per_metatile = tiles_per * 2
    metatile_count = mt_size // bytes_per_metatile
    if metatile_count == 0:
        return None
    attr_per = at_size // metatile_count
    if attr_per in (2, 4):
        return attr_per
    return None


def _detect_source_format(source_path):
    """Detect the metatile format of the source tileset.

    Returns dict with:
      tiles_per_metatile: 8 or 12
      attr_bytes: 2 or 4
      compression: str (e.g. '.4bpp.lz')
    Or None if detection fails.
    """
    root = _find_project_root(source_path)
    if not root:
        return None

    # tiles per metatile
    fm = os.path.join(root, "include", "fieldmap.h")
    tiles_per = _read_tiles_per_metatile(fm) if os.path.isfile(fm) else None
    if tiles_per is None:
        tiles_per = 8  # safe default for vanilla decomps

    # attribute bytes — verify from binary sizes
    mt_bin = os.path.join(source_path, "metatiles.bin")
    at_bin = os.path.join(source_path, "metatile_attributes.bin")
    attr_bytes = _detect_attr_bytes(mt_bin, at_bin, tiles_per)
    if attr_bytes is None:
        # Fall back based on tiles_per: 8-tile decomps use 4-byte attrs
        attr_bytes = 4 if tiles_per == 8 else 2

    # compression
    compression = _detect_compression(root)

    # primary tile count (secondary tiles start at this index)
    primary_tiles = _read_primary_tile_count(fm) if os.path.isfile(fm) else None
    if primary_tiles is None:
        primary_tiles = 640 if tiles_per == 8 else 512

    return {
        "tiles_per_metatile": tiles_per,
        "attr_bytes": attr_bytes,
        "compression": compression,
        "primary_tiles": primary_tiles,
    }


def _detect_target_format(game_path):
    """Detect the metatile format of the target project.

    Same approach as _detect_source_format but for the target game.
    """
    fm = os.path.join(game_path, "include", "fieldmap.h")
    tiles_per = _read_tiles_per_metatile(fm) if os.path.isfile(fm) else None
    if tiles_per is None:
        tiles_per = 12  # expansion default

    # Try to detect from an existing tileset
    attr_bytes = None
    for kind in ("primary", "secondary"):
        ts_dir = os.path.join(game_path, "data", "tilesets", kind)
        if not os.path.isdir(ts_dir):
            continue
        try:
            dirs = os.listdir(ts_dir)
        except OSError:
            continue
        for d in dirs:
            mt = os.path.join(ts_dir, d, "metatiles.bin")
            at = os.path.join(ts_dir, d, "metatile_attributes.bin")
            detected = _detect_attr_bytes(mt, at, tiles_per)
            if detected is not None:
                attr_bytes = detected
                break
        if attr_bytes is not None:
            break

    if attr_bytes is None:
        attr_bytes = 2 if tiles_per == 12 else 4

    compression = _detect_compression(game_path)

    # primary tile count
    primary_tiles = _read_primary_tile_count(fm) if os.path.isfile(fm) else None
    if primary_tiles is None:
        primary_tiles = 512 if tiles_per == 12 else 640

    return {
        "tiles_per_metatile": tiles_per,
        "attr_bytes": attr_bytes,
        "compression": compression,
        "primary_tiles": primary_tiles,
    }


# ---------------------------------------------------------------------------
# Cross-decomp import — binary conversion
# ---------------------------------------------------------------------------

def _remap_tile_ref(tile_u16, src_primary, dst_primary):
    """Remap a single 16-bit tile reference to adjust the secondary tile offset.

    Tile ref format: bits 0-9 = tile index, bit 10 = h-flip, bit 11 = v-flip,
                     bits 12-15 = palette number.

    Secondary tiles start at src_primary in the source and dst_primary in the
    target.  Tile indices >= src_primary are remapped to dst_primary-based.
    """
    tile_idx = tile_u16 & 0x3FF
    flags = tile_u16 & 0xFC00  # palette + flips

    if tile_idx >= src_primary:
        tile_idx = (tile_idx - src_primary) + dst_primary
        if tile_idx > 0x3FF:
            tile_idx = 0  # overflow — clamp to empty
    return flags | (tile_idx & 0x3FF)


def _convert_metatiles(source_path, dest_path, source_tiles, dest_tiles,
                       src_primary=None, dst_primary=None,
                       src_layer_types=None):
    """Convert metatiles.bin between formats.

    8->12 tiles: insert empty middle layer between bottom and top.
    12->8 tiles: drop middle layer.
    Also remaps tile indices when primary tile counts differ (e.g. FR 640 vs
    expansion 512).

    If src_layer_types is provided (list of ints, one per metatile), it
    controls where the second FR layer is placed during 8->12 conversion:
    - COVERED (1): FR top → Emerald middle (both behind player)
    - NORMAL (0) or SPLIT (2): FR top → Emerald top (overlaps player)

    Returns (success, warning_msg_or_None).
    """
    try:
        with open(source_path, "rb") as f:
            data = f.read()
    except OSError:
        return False, "Could not read source metatiles.bin"

    need_remap = (src_primary is not None and dst_primary is not None
                  and src_primary != dst_primary)

    if source_tiles == dest_tiles and not need_remap:
        with open(dest_path, "wb") as f:
            f.write(data)
        return True, None

    src_chunk = source_tiles * 2
    metatile_count = len(data) // src_chunk
    warn = None

    # Each layer = 4 tiles = 8 bytes (2x2 quadrant of tile refs)
    layer_bytes = 4 * 2  # 4 tiles per layer, 2 bytes per tile ref
    src_layers = source_tiles // 4
    dst_layers = dest_tiles // 4

    import struct

    out = bytearray()
    for i in range(metatile_count):
        chunk = data[i * src_chunk : (i + 1) * src_chunk]

        # Remap tile indices if primary tile counts differ
        if need_remap:
            tile_refs = struct.unpack(f'<{source_tiles}H', chunk)
            remapped = struct.pack(
                f'<{source_tiles}H',
                *(_remap_tile_ref(t, src_primary, dst_primary) for t in tile_refs)
            )
            chunk = remapped

        if src_layers == 2 and dst_layers == 3:
            # 8->12: route FR's second layer based on layer type.
            # FR layout:  bottom(4 tiles) + top(4 tiles)
            # Expansion:  bottom(4 tiles) + middle(4 tiles) + top(4 tiles)
            #
            # In Emerald: BG3=bottom, BG2=middle (behind player),
            #             BG1=top (IN FRONT of player, always).
            #
            # FR COVERED (1): both layers behind player
            #   → FR top goes to Emerald MIDDLE (BG2, behind player)
            # FR NORMAL (0) / SPLIT (2): second layer overlaps player
            #   → FR top goes to Emerald TOP (BG1, in front of player)
            fr_bottom = chunk[:layer_bytes]
            fr_top = chunk[layer_bytes:]
            lt = src_layer_types[i] if src_layer_types and i < len(src_layer_types) else 0
            if lt == 1:  # COVERED — both behind player
                out.extend(fr_bottom)                # bottom → BG3
                out.extend(fr_top)                   # FR top → middle (BG2, behind)
                out.extend(b'\x00' * layer_bytes)    # top (BG1) empty
            else:  # NORMAL or SPLIT — second layer overlaps player
                out.extend(fr_bottom)                # bottom → BG3
                out.extend(b'\x00' * layer_bytes)    # middle empty
                out.extend(fr_top)                   # FR top → top (BG1, in front)
        elif src_layers == 3 and dst_layers == 2:
            # 12->8: drop middle layer, keep bottom and top
            out.extend(chunk[:layer_bytes])           # bottom layer
            out.extend(chunk[2 * layer_bytes:])       # top layer (skip middle)
            warn = "Middle layer data dropped during conversion"
        elif source_tiles == dest_tiles:
            # Same layer count (remap-only path)
            out.extend(chunk)
        elif dest_tiles > source_tiles:
            # Generic pad
            pad_bytes = (dest_tiles - source_tiles) * 2
            out.extend(chunk)
            out.extend(b'\x00' * pad_bytes)
        else:
            # Generic truncate
            out.extend(chunk[:dest_tiles * 2])
            warn = "Layer data truncated during conversion"

    with open(dest_path, "wb") as f:
        f.write(out)
    return True, warn


def _build_behavior_remap(source_project, target_project):
    """Build a behavior value remap table from source→target decomp.

    Parses metatile_behaviors.h from both projects, matches by name,
    and returns a dict mapping source values to target values.
    Values with no name match are mapped to 0 (MB_NORMAL).
    """
    def _parse_beh_header(path):
        behs = {}
        counter = 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    # #define style (FR)
                    m = re.match(
                        r"#define\s+(MB_\w+)\s+(0x[0-9a-fA-F]+|\d+)",
                        line.strip())
                    if m:
                        behs[m.group(1)] = int(m.group(2), 0)
                        continue
                    # enum style (expansion)
                    m = re.match(
                        r"\s*(MB_\w+)\s*(?:=\s*(\d+|0x[0-9a-fA-F]+))?\s*,?",
                        line.strip())
                    if m and m.group(1) != "NUM_METATILE_BEHAVIORS":
                        if m.group(2):
                            counter = int(m.group(2), 0)
                        behs[m.group(1)] = counter
                        counter += 1
        except OSError:
            pass
        return behs

    src_path = os.path.join(
        source_project, "include", "constants", "metatile_behaviors.h")
    dst_path = os.path.join(
        target_project, "include", "constants", "metatile_behaviors.h")

    src_behs = _parse_beh_header(src_path)
    dst_behs = _parse_beh_header(dst_path)

    if not src_behs or not dst_behs:
        return {}

    # Invert source: value -> name
    src_by_val = {v: k for k, v in src_behs.items()}

    remap = {}
    for src_val, src_name in src_by_val.items():
        if src_val == 0:
            continue  # MB_NORMAL stays 0
        if src_name in dst_behs:
            dst_val = dst_behs[src_name]
            if dst_val != src_val:
                remap[src_val] = dst_val
            # else: same value, no remap needed
        else:
            # No name match → clear to MB_NORMAL
            remap[src_val] = 0

    return remap


def _convert_metatile_attributes_data(data, src_bytes, dst_bytes,
                                       behavior_remap=None):
    """Convert metatile attribute data between formats (pure function).

    FireRed uses 4-byte (u32) packed bitfields per metatile:
        Bits 0-8:   Behavior  (9 bits, mask 0x000001FF)
        Bits 29-30: Layer type (2 bits, mask 0x60000000)
        (Terrain, encounter type, and other fields are lost in conversion.)

    Emerald expansion uses 2-byte (u16) packed bitfields per metatile:
        Bits 0-7:   Behavior  (8 bits, mask 0x00FF)
        Bits 12-15: Layer type (4 bits, mask 0xF000)

    If behavior_remap is provided (dict: src_value -> dst_value),
    behavior values are remapped during conversion.  Values not in the
    map are kept as-is; values mapped to 0 become MB_NORMAL.

    Returns (output_bytes, warnings_list).
    """
    if src_bytes == dst_bytes:
        return bytes(data), []

    attr_count = len(data) // src_bytes
    warnings = []
    out = bytearray()
    clamped = 0

    if src_bytes == 4 and dst_bytes == 2:
        # FireRed (u32) -> Emerald (u16)
        remapped = 0
        cleared = 0
        for i in range(attr_count):
            val = struct.unpack_from('<I', data, i * 4)[0]
            behavior = val & 0x1FF           # 9-bit FR behavior
            layer = (val >> 29) & 0x3        # 2-bit layer type
            if behavior > 255:
                clamped += 1
                behavior &= 0xFF
            # Apply behavior remap if available
            if behavior_remap and behavior in behavior_remap:
                new_beh = behavior_remap[behavior]
                if new_beh == 0 and behavior != 0:
                    cleared += 1
                elif new_beh != behavior:
                    remapped += 1
                behavior = new_beh
            emerald = (behavior & 0xFF) | (layer << 12)
            out += struct.pack('<H', emerald)
        if clamped:
            warnings.append(
                f"{clamped} metatile(s) had behavior > 255 (clamped to 8-bit)")
        if remapped:
            warnings.append(
                f"{remapped} behavior(s) remapped to Emerald equivalents")
        if cleared:
            warnings.append(
                f"{cleared} behavior(s) cleared (no Emerald equivalent)")

    elif src_bytes == 2 and dst_bytes == 4:
        # Emerald (u16) -> FireRed (u32)
        for i in range(attr_count):
            val = struct.unpack_from('<H', data, i * 2)[0]
            behavior = val & 0xFF
            layer = (val >> 12) & 0xF
            fr_val = behavior | (layer << 29)
            out += struct.pack('<I', fr_val)

    else:
        # Unknown format combination — fall back to zero-pad/truncate
        for i in range(attr_count):
            chunk = data[i * src_bytes : (i + 1) * src_bytes]
            if dst_bytes < src_bytes:
                out.extend(chunk[:dst_bytes])
            else:
                out.extend(chunk)
                out.extend(b'\x00' * (dst_bytes - src_bytes))
        warnings.append(
            f"Unknown format pair ({src_bytes}->{dst_bytes}), "
            "used raw truncation/padding")

    return bytes(out), warnings


def _convert_metatile_attributes(source_path, dest_path, src_bytes, dst_bytes,
                                  behavior_remap=None):
    """Convert metatile_attributes.bin between formats.

    Extracts behavior and layer type from source bitfield layout and
    repacks into destination layout.  See _convert_metatile_attributes_data
    for format details.

    If behavior_remap is provided, behavior values are remapped during
    conversion (for cross-decomp imports where behavior enums differ).

    Returns (success, warning_msg_or_None).
    """
    try:
        with open(source_path, "rb") as f:
            data = f.read()
    except OSError:
        return False, "Could not read source metatile_attributes.bin"

    if src_bytes == dst_bytes and not behavior_remap:
        with open(dest_path, "wb") as f:
            f.write(data)
        return True, None

    result, warnings = _convert_metatile_attributes_data(
        data, src_bytes, dst_bytes, behavior_remap=behavior_remap)

    with open(dest_path, "wb") as f:
        f.write(result)

    warn = "; ".join(warnings) if warnings else None
    return True, warn


# ---------------------------------------------------------------------------
# Repair already-imported metatile attributes
# ---------------------------------------------------------------------------

def repair_metatile_attributes(game_path, tileset_dir_name, source_path):
    """Re-convert metatile_attributes.bin from original source to fix
    broken imports where layer type data was lost.

    game_path:        target project root
    tileset_dir_name: e.g. "silph_co"
    source_path:      path to the original source tileset directory

    Creates a .bak backup before overwriting.
    Returns (success, messages_list).
    """
    msgs = []

    # Locate target attributes file
    target_dir = os.path.join(
        game_path, "data", "tilesets", "secondary", tileset_dir_name)
    target_attrs = os.path.join(target_dir, "metatile_attributes.bin")
    if not os.path.isfile(target_attrs):
        return False, [f"Target not found: {target_attrs}"]

    # Locate source attributes file
    source_attrs = os.path.join(source_path, "metatile_attributes.bin")
    if not os.path.isfile(source_attrs):
        return False, [f"Source not found: {source_attrs}"]

    # Detect formats
    src_bytes = _detect_source_attr_bytes(source_path)
    dst_bytes = _detect_target_attr_bytes(game_path)

    if src_bytes is None:
        return False, ["Could not detect source attribute format"]
    if dst_bytes is None:
        return False, ["Could not detect target attribute format"]

    msgs.append(f"Source format: {src_bytes}-byte, target format: {dst_bytes}-byte")

    if src_bytes == dst_bytes:
        msgs.append("Both projects use the same attribute format — "
                     "no conversion needed (copying directly)")

    # Read source data
    try:
        with open(source_attrs, "rb") as f:
            src_data = f.read()
    except OSError as e:
        return False, [f"Could not read source: {e}"]

    # Read current target for comparison
    try:
        with open(target_attrs, "rb") as f:
            old_data = f.read()
    except OSError:
        old_data = b""

    # Convert
    result, warnings = _convert_metatile_attributes_data(
        src_data, src_bytes, dst_bytes)
    msgs.extend(warnings)

    # Count meaningful changes
    attr_count = len(result) // dst_bytes
    changed = 0
    layer_fixed = 0
    if len(old_data) == len(result) and dst_bytes == 2:
        for i in range(attr_count):
            old_val = struct.unpack_from('<H', old_data, i * 2)[0]
            new_val = struct.unpack_from('<H', result, i * 2)[0]
            if old_val != new_val:
                changed += 1
                old_layer = (old_val >> 12) & 0xF
                new_layer = (new_val >> 12) & 0xF
                if old_layer != new_layer:
                    layer_fixed += 1

    # Backup
    bak_path = target_attrs + ".bak"
    try:
        shutil.copy2(target_attrs, bak_path)
        msgs.append(f"Backup saved to {os.path.basename(bak_path)}")
    except OSError as e:
        msgs.append(f"Warning: could not create backup: {e}")

    # Write
    try:
        with open(target_attrs, "wb") as f:
            f.write(result)
    except OSError as e:
        return False, msgs + [f"Write failed: {e}"]

    msgs.append(f"{attr_count} metatiles processed, "
                f"{changed} changed, {layer_fixed} layer types fixed")
    return True, msgs


def _detect_source_attr_bytes(source_path):
    """Detect attribute byte width from a source tileset directory.

    Heuristic: read metatile_attributes.bin size and metatiles.bin size.
    If attrs_size / metatile_count == 4, it's FireRed format.
    If attrs_size / metatile_count == 2, it's Emerald format.
    """
    attrs_path = os.path.join(source_path, "metatile_attributes.bin")
    meta_path = os.path.join(source_path, "metatiles.bin")

    try:
        attrs_size = os.path.getsize(attrs_path)
    except OSError:
        return None

    # Try to infer from metatiles.bin — 16 bytes per metatile (8 tiles)
    # or 24 bytes per metatile (12 tiles, Emerald triple-layer)
    if os.path.isfile(meta_path):
        meta_size = os.path.getsize(meta_path)
        # Try 8-tile format (16 bytes per metatile)
        if meta_size % 16 == 0:
            count_8 = meta_size // 16
            if count_8 > 0 and attrs_size == count_8 * 4:
                return 4
            if count_8 > 0 and attrs_size == count_8 * 2:
                return 2
        # Try 12-tile format (24 bytes per metatile)
        if meta_size % 24 == 0:
            count_12 = meta_size // 24
            if count_12 > 0 and attrs_size == count_12 * 4:
                return 4
            if count_12 > 0 and attrs_size == count_12 * 2:
                return 2

    # Fallback: check if attrs_size is divisible by 4 or 2
    if attrs_size % 4 == 0 and attrs_size % 2 == 0:
        # Ambiguous — try reading fieldmap.h from parent project
        # Walk up to find include/global.fieldmap.h
        parent = source_path
        for _ in range(6):
            parent = os.path.dirname(parent)
            fmap = os.path.join(parent, "include", "global.fieldmap.h")
            if os.path.isfile(fmap):
                try:
                    with open(fmap, "r", encoding="utf-8") as f:
                        content = f.read()
                    if "METATILE_ATTR_LAYER_MASK" in content:
                        # Emerald-style 2-byte
                        return 2
                    if "METATILE_ATTRIBUTE_LAYER_TYPE" in content:
                        # FireRed-style 4-byte
                        return 4
                except OSError:
                    pass
                break
    return None


def _detect_target_attr_bytes(game_path):
    """Detect attribute byte width for the target project."""
    fmap = os.path.join(game_path, "include", "global.fieldmap.h")
    if os.path.isfile(fmap):
        try:
            with open(fmap, "r", encoding="utf-8") as f:
                content = f.read()
            if "METATILE_ATTR_LAYER_MASK" in content:
                return 2
            if "METATILE_ATTRIBUTE_LAYER_TYPE" in content:
                return 4
        except OSError:
            pass
    # Default for pokeemerald-expansion
    return 2


# ---------------------------------------------------------------------------
# Cross-decomp import — shared tile graphics resolution
# ---------------------------------------------------------------------------

def _resolve_tile_source(project_root, tileset_dir_name):
    """Find where a tileset's tiles and palettes actually live.

    Some tilesets share tiles/palettes with another tileset
    (e.g. SilphCo uses Condominiums' tiles). This parses headers.h
    to find the actual source.

    Returns (tiles_dir, palettes_dir) — full paths.
    Both may be the same directory. Falls back to the tileset's own dir.
    """
    if project_root is None:
        return None, None

    headers_path = os.path.join(
        project_root, "src", "data", "tilesets", "headers.h"
    )
    if not os.path.isfile(headers_path):
        return None, None

    # Derive the CamelCase name for this tileset
    parts = tileset_dir_name.split("_")
    camel = "".join(p.capitalize() for p in parts if p)

    try:
        with open(headers_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None, None

    # Find the struct definition for this tileset
    pattern = (
        r'const\s+struct\s+Tileset\s+gTileset_' + re.escape(camel)
        + r'\s*=\s*\{([^}]+)\}'
    )
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return None, None

    body = m.group(1)

    # Extract .tiles and .palettes references
    tiles_ref = _extract_struct_ref(body, "tiles", "gTilesetTiles_")
    pals_ref = _extract_struct_ref(body, "palettes", "gTilesetPalettes_")

    # Resolve the actual directories via graphics.h
    tiles_dir = _resolve_gfx_dir(project_root, tiles_ref, "tiles")
    pals_dir = _resolve_gfx_dir(project_root, pals_ref, "palettes")

    return tiles_dir, pals_dir


def _extract_struct_ref(struct_body, field_name, prefix):
    """Extract a tileset constant name from a struct field.

    e.g. ".tiles = gTilesetTiles_Condominiums," -> "Condominiums"
    Returns the CamelCase suffix, or None.
    """
    pattern = r'\.' + re.escape(field_name) + r'\s*=\s*' + re.escape(prefix) + r'(\w+)'
    m = re.search(pattern, struct_body)
    if m:
        return m.group(1)
    return None


def _resolve_gfx_dir(project_root, camel_ref, asset_type):
    """Resolve a tileset constant name to a directory path.

    Parses graphics.h to find the INCBIN path for the constant, then
    returns the directory containing the referenced file.

    asset_type: "tiles" or "palettes"
    """
    if camel_ref is None:
        return None

    gfx_path = os.path.join(
        project_root, "src", "data", "tilesets", "graphics.h"
    )
    if not os.path.isfile(gfx_path):
        return None

    try:
        with open(gfx_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None

    if asset_type == "tiles":
        # Look for: gTilesetTiles_X[] = INCBIN_U32("data/.../tiles.4bpp...")
        pattern = (
            r'gTilesetTiles_' + re.escape(camel_ref)
            + r'\[\]\s*=\s*INCBIN_U\d+\("([^"]+)"'
        )
    else:
        # Look for: gTilesetPalettes_X[][16] =
        # The INCBIN is on the next lines; find the directory from the first
        pattern = (
            r'gTilesetPalettes_' + re.escape(camel_ref)
            + r'\[\]\[16\]\s*=[\s\S]*?INCBIN_U\d+\("([^"]+)"'
        )

    m = re.search(pattern, text)
    if not m:
        return None

    # The path is relative to project root, e.g. "data/tilesets/secondary/condominiums/tiles.4bpp.lz"
    rel = m.group(1)
    full = os.path.join(project_root, os.path.dirname(rel))
    if os.path.isdir(full):
        return full
    return None


# ---------------------------------------------------------------------------
# Cross-decomp import — high-level pipeline
# ---------------------------------------------------------------------------

def _import_copy_tiles(tiles_dir, dest, messages):
    """Copy tiles.png from resolved source to destination."""
    if tiles_dir is None:
        messages.append("WARNING: Could not resolve tile source directory")
        return
    src_tiles_png = os.path.join(tiles_dir, "tiles.png")
    if os.path.isfile(src_tiles_png):
        shutil.copy2(src_tiles_png, os.path.join(dest, "tiles.png"))
        src_label = os.path.basename(tiles_dir)
        messages.append(f"Copied tiles.png from {src_label}/")
    else:
        messages.append("WARNING: No tiles.png found -- you'll need to provide tile graphics")


def _import_copy_palettes(tiles_dir, pals_dir, dest, messages):
    """Copy palette files from resolved source to destination."""
    # Determine where palettes/ lives
    candidates = []
    if pals_dir is not None:
        candidates.append(os.path.join(pals_dir, "palettes"))
        candidates.append(pals_dir)
    if tiles_dir is not None and tiles_dir != pals_dir:
        candidates.append(os.path.join(tiles_dir, "palettes"))

    src_pal_dir = None
    for c in candidates:
        if os.path.isdir(c):
            # Check it actually has palette files
            try:
                if any(f.endswith(".pal") for f in os.listdir(c)):
                    src_pal_dir = c
                    break
            except OSError:
                pass

    if src_pal_dir is None:
        messages.append("WARNING: No palette files found")
        return

    pal_count = 0
    dest_pal_dir = os.path.join(dest, "palettes")
    for i in range(16):
        src_pal = os.path.join(src_pal_dir, f"{i:02d}.pal")
        if os.path.isfile(src_pal):
            shutil.copy2(src_pal, os.path.join(dest_pal_dir, f"{i:02d}.pal"))
            pal_count += 1
    messages.append(f"Copied {pal_count} palette files (.pal)")


def _import_convert_binaries(source_path, dest, src_fmt, tgt_fmt, messages,
                             behavior_remap=None):
    """Convert and copy metatiles.bin and metatile_attributes.bin."""
    # Read source layer types BEFORE metatile conversion (needed for
    # correct layer placement during 8->12 tile conversion).
    src_layer_types = None
    src_at = os.path.join(source_path, "metatile_attributes.bin")
    if (os.path.isfile(src_at)
            and src_fmt["tiles_per_metatile"] == 8
            and tgt_fmt["tiles_per_metatile"] == 12):
        try:
            with open(src_at, "rb") as f:
                at_data = f.read()
            src_layer_types = []
            stride = src_fmt["attr_bytes"]
            for j in range(len(at_data) // stride):
                if stride == 4:
                    val = struct.unpack_from("<I", at_data, j * 4)[0]
                    src_layer_types.append((val >> 29) & 0x3)
                else:
                    val = struct.unpack_from("<H", at_data, j * 2)[0]
                    src_layer_types.append((val >> 12) & 0xF)
            messages.append(
                f"Read {len(src_layer_types)} layer types from source "
                f"for layer-aware metatile conversion")
        except OSError:
            src_layer_types = None

    # metatiles.bin
    src_mt = os.path.join(source_path, "metatiles.bin")
    if os.path.isfile(src_mt):
        ok, warn = _convert_metatiles(
            src_mt, os.path.join(dest, "metatiles.bin"),
            src_fmt["tiles_per_metatile"], tgt_fmt["tiles_per_metatile"],
            src_primary=src_fmt.get("primary_tiles"),
            dst_primary=tgt_fmt.get("primary_tiles"),
            src_layer_types=src_layer_types,
        )
        if ok:
            msg = "Converted metatiles.bin"
            if src_fmt["tiles_per_metatile"] != tgt_fmt["tiles_per_metatile"]:
                msg += (f" ({src_fmt['tiles_per_metatile']}"
                        f" -> {tgt_fmt['tiles_per_metatile']} tiles/metatile)")
            src_pt = src_fmt.get("primary_tiles")
            dst_pt = tgt_fmt.get("primary_tiles")
            if src_pt and dst_pt and src_pt != dst_pt:
                msg += f", tile indices remapped ({src_pt} -> {dst_pt})"
            messages.append(msg)
        else:
            messages.append(f"ERROR: {warn}")
        if warn and ok:
            messages.append(f"WARNING: {warn}")
    else:
        messages.append("WARNING: No metatiles.bin in source")

    # metatile_attributes.bin
    src_at = os.path.join(source_path, "metatile_attributes.bin")
    if os.path.isfile(src_at):
        ok, warn = _convert_metatile_attributes(
            src_at, os.path.join(dest, "metatile_attributes.bin"),
            src_fmt["attr_bytes"], tgt_fmt["attr_bytes"],
            behavior_remap=behavior_remap,
        )
        if ok:
            msg = "Converted metatile_attributes.bin"
            if src_fmt["attr_bytes"] != tgt_fmt["attr_bytes"]:
                msg += (f" ({src_fmt['attr_bytes']}"
                        f" -> {tgt_fmt['attr_bytes']} bytes/attr)")
            messages.append(msg)
        else:
            messages.append(f"ERROR: {warn}")
        if warn and ok:
            messages.append(f"WARNING: {warn}")
    else:
        messages.append("WARNING: No metatile_attributes.bin in source")


def import_tileset(game_path, source_path, new_name=None):
    """Import a tileset from another decomp project.

    source_path: Path to a tileset directory (e.g.
        ~/Documents/pokefirered/data/tilesets/secondary/silph_co)
    new_name: Optional name for the imported tileset. Defaults to
        the source directory name.

    Returns (success, camel_name, dir_name, messages).
    """
    messages = []

    # 1. Validate source
    if not os.path.isdir(source_path):
        return False, "", "", ["Source path not found: " + source_path]

    # 2. Derive names
    dir_name_source = os.path.basename(os.path.normpath(source_path))
    name = new_name or dir_name_source
    camel_name, dir_name = _derive_names(name)
    if not camel_name:
        return False, "", "", ["Invalid tileset name"]

    # 3. Check for conflicts
    dest = os.path.join(game_path, "data", "tilesets", "secondary", dir_name)
    if os.path.exists(dest):
        return False, camel_name, dir_name, [
            f"Tileset directory already exists: data/tilesets/secondary/{dir_name}/"
        ]

    # 4. Detect formats
    src_fmt = _detect_source_format(source_path)
    if src_fmt is None:
        return False, camel_name, dir_name, [
            "Could not detect source project format "
            "(no fieldmap.h found above source path)"
        ]
    tgt_fmt = _detect_target_format(game_path)

    messages.append(
        f"Source: {src_fmt['tiles_per_metatile']} tiles/metatile, "
        f"{src_fmt['attr_bytes']}-byte attrs, {src_fmt['compression']}"
    )
    messages.append(
        f"Target: {tgt_fmt['tiles_per_metatile']} tiles/metatile, "
        f"{tgt_fmt['attr_bytes']}-byte attrs, {tgt_fmt['compression']}"
    )

    # 5. Resolve tile/palette source (handle shared graphics)
    source_root = _find_project_root(source_path)
    tiles_dir, pals_dir = _resolve_tile_source(source_root, dir_name_source)

    # Fall back to source directory itself if resolution failed
    if tiles_dir is None:
        tiles_dir = source_path
    if pals_dir is None:
        pals_dir = tiles_dir

    if tiles_dir != source_path:
        messages.append(
            f"Shared graphics: tiles from {os.path.basename(tiles_dir)}/"
        )

    # 6. Create destination directory
    os.makedirs(dest, exist_ok=True)
    os.makedirs(os.path.join(dest, "palettes"), exist_ok=True)

    # 7. Copy tiles.png
    _import_copy_tiles(tiles_dir, dest, messages)

    # 8. Copy palettes
    _import_copy_palettes(tiles_dir, pals_dir, dest, messages)

    # 9-10. Convert binary files (with behavior remapping for cross-decomp)
    beh_remap = None
    if src_fmt.get("attr_bytes") != tgt_fmt.get("attr_bytes"):
        # Different attribute format → likely cross-decomp import.
        # Try to find the source project root for behavior remapping.
        src_root = source_path
        for _ in range(6):
            src_root = os.path.dirname(src_root)
            if os.path.isfile(os.path.join(
                    src_root, "include", "constants", "metatile_behaviors.h")):
                beh_remap = _build_behavior_remap(src_root, game_path)
                if beh_remap:
                    messages.append(
                        f"Behavior remap: {len(beh_remap)} values mapped "
                        f"from source to target decomp")
                break
    _import_convert_binaries(source_path, dest, src_fmt, tgt_fmt, messages,
                             behavior_remap=beh_remap)

    # 11. Register in C headers
    compression = _detect_compression(game_path)
    success, errors = _register_tileset(game_path, camel_name, dir_name,
                                        compression)
    if success:
        messages.append(f"Registered as gTileset_{camel_name}")
    else:
        messages.extend(errors)
        messages.append(
            "WARNING: Registration incomplete -- "
            "run 'torch tileset check' to diagnose"
        )

    return True, camel_name, dir_name, messages


# ---------------------------------------------------------------------------
# TUI — Main menu
# ---------------------------------------------------------------------------

def tileset_assistant_menu(game_path, settings, proj_name=None):
    """Main entry point for the Tileset Assistant."""
    _set_terminal_title("TORCH -- Tilesets")

    while True:
        clear_screen()
        print_logo(proj_name)
        print(BAR)
        print(f"  {WHITE}Tileset Assistant{RST}  {DIM}v{TILESET_VERSION}{RST}")
        print(BAR)
        print()
        print(f"  {_k('1')} {WHITE}Create new tileset{RST}    {DIM}Scaffold from scratch or copy existing{RST}")
        print(f"  {_k('2')} {WHITE}Browse tilesets{RST}       {DIM}View all tilesets with map assignments{RST}")
        print(f"  {_k('3')} {WHITE}Health check{RST}          {DIM}Validate completeness of all tilesets{RST}")
        print(f"  {_k('4')} {WHITE}Import tileset{RST}        {DIM}Import from another decomp project{RST}")
        print()
        print(f"  {_k('q')} {DIM}Back{RST}")
        print()

        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if choice in ("q", ""):
            return
        elif choice == "1":
            _create_menu(game_path, settings, proj_name)
        elif choice == "2":
            _browse_tilesets(game_path, settings, proj_name)
        elif choice == "3":
            _health_check(game_path, settings, proj_name)
        elif choice == "4":
            _import_menu(game_path, settings, proj_name)


# ---------------------------------------------------------------------------
# TUI — Create
# ---------------------------------------------------------------------------

def _create_menu(game_path, settings, proj_name=None):
    """Create tileset sub-menu: copy existing or scaffold new."""
    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}Create New Tileset{RST}")
    print(BAR)
    print()
    print(f"  {_k('1')} {WHITE}Copy existing tileset{RST}  {DIM}Use a vanilla tileset as a starting point{RST}")
    print(f"  {_k('2')} {WHITE}Scaffold from scratch{RST}  {DIM}Create empty tileset directory{RST}")
    print()
    print(f"  {_k('q')} {DIM}Back{RST}")
    print()

    choice = input(f"  {GOLD}>{RST} ").strip().lower()

    if choice == "1":
        _create_from_copy(game_path, settings, proj_name)
    elif choice == "2":
        _create_from_scaffold(game_path, settings, proj_name)


def _find_source_tileset(raw, secondary):
    """Look up a tileset by number or name. Returns match or None."""
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(secondary):
            return secondary[idx]
        return None
    raw_lower = raw.lower()
    for ts in secondary:
        if ts["dir_name"] == raw_lower or ts["name"].lower() == raw_lower:
            return ts
    return None


def _print_result_msgs(ok, msgs, success_words):
    """Print creation result messages with colour-coded icons."""
    for msg in msgs:
        if ok or any(w in msg for w in success_words):
            print(f"  {GREEN}v{RST} {msg}")
        else:
            print(f"  {RED}x{RST} {msg}")


def _create_from_copy(game_path, settings, proj_name=None):
    """Interactive: pick source tileset, name new one, copy + register."""
    tilesets = _scan_tilesets(game_path)
    secondary = [ts for ts in tilesets if ts["kind"] == "secondary"]

    if not secondary:
        print()
        print(f"  {RED}No secondary tilesets found to copy.{RST}")
        input(f"\n  {DIM}Press Enter{RST} > ")
        return

    # Show list for user to pick source
    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}Pick a Source Tileset{RST}")
    print(BAR)
    print()

    for i, ts in enumerate(secondary):
        print(f"  {DIM}{i + 1:3}.{RST}  {WHITE}{ts['name']}{RST}  {DIM}({ts['dir_name']}){RST}")
    print()

    try:
        raw = input(f"  {DIM}Number or name (q = cancel):{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if raw.lower() == "q" or not raw:
        return

    source = _find_source_tileset(raw, secondary)
    if not source:
        print(f"\n  {RED}Tileset not found.{RST}")
        input(f"\n  {DIM}Press Enter{RST} > ")
        return

    print(f"\n  Source: {CYAN}{source['constant']}{RST}")
    print()

    try:
        new_name = input(f"  {DIM}New tileset name:{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not new_name:
        return

    print()
    ok, camel, dir_name, msgs = create_tileset_copy(game_path, source["dir_name"], new_name)
    _print_result_msgs(ok, msgs, ("Registered", "Copied"))

    if ok:
        print()
        print(f"  {GREEN}Done!{RST} Open in Porymap to customize:")
        print(f"  {CYAN}data/tilesets/secondary/{dir_name}/tiles.png{RST}")

    input(f"\n  {DIM}Press Enter{RST} > ")


def _create_from_scaffold(game_path, settings, proj_name=None):
    """Interactive: name new tileset, scaffold + register."""
    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}Scaffold New Tileset{RST}")
    print(BAR)
    print()

    try:
        new_name = input(f"  {DIM}Tileset name:{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if not new_name:
        return

    print()
    ok, camel, dir_name, msgs = create_tileset_scaffold(game_path, new_name)

    for msg in msgs:
        if ok or "Created" in msg or "Registered" in msg:
            print(f"  {GREEN}v{RST} {msg}")
        else:
            print(f"  {RED}x{RST} {msg}")

    if ok:
        print()
        print(f"  {GREEN}Done!{RST} Edit tiles in Porymap:")
        print(f"  {CYAN}data/tilesets/secondary/{dir_name}/tiles.png{RST}")

    input(f"\n  {DIM}Press Enter{RST} > ")


# ---------------------------------------------------------------------------
# TUI — Import
# ---------------------------------------------------------------------------

def _import_menu(game_path, settings, proj_name=None):
    """Interactive: import tileset from another decomp project."""
    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}Import Tileset{RST}  {DIM}from another decomp project{RST}")
    print(BAR)
    print()
    print(f"  {DIM}Paste the full path to a tileset directory, e.g.:{RST}")
    print(f"  {CYAN}~/Documents/pokefirered/data/tilesets/secondary/silph_co{RST}")
    print()

    try:
        raw = input(f"  {DIM}Source path (q = cancel):{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if raw.lower() == "q" or not raw:
        return

    source_path = os.path.expanduser(raw)
    if not os.path.isdir(source_path):
        print(f"\n  {RED}Directory not found: {source_path}{RST}")
        input(f"\n  {DIM}Press Enter{RST} > ")
        return

    print()
    try:
        new_name = input(
            f"  {DIM}Name for imported tileset "
            f"(Enter = {os.path.basename(source_path)}):{RST} "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return

    if not new_name:
        new_name = None  # use source directory name

    print()
    ok, camel, dir_name, msgs = import_tileset(game_path, source_path, new_name)
    _print_result_msgs(ok, msgs, ("Copied", "Converted", "Registered", "Shared", "Source", "Target"))

    if ok:
        print()
        print(f"  {GREEN}Done!{RST} Open in Porymap to review metatiles:")
        print(f"  {CYAN}data/tilesets/secondary/{dir_name}/{RST}")

    input(f"\n  {DIM}Press Enter{RST} > ")


# ---------------------------------------------------------------------------
# TUI — Browse
# ---------------------------------------------------------------------------

def _render_tileset_row(state, i, ts):
    """Render one tileset row in the browser list."""
    sel = marker(state, i)
    kind_tag = f"{DIM}P{RST}" if ts["kind"] == "primary" else f"{DIM}S{RST}"
    count = ts["map_count"]
    usage_str = f"{RED}unused{RST}" if count == 0 else f"{DIM}{count} map{'s' if count != 1 else ''}{RST}"
    reg = f"{GREEN}R{RST}" if ts["registered"] else f"{RED}!{RST}"
    print(f"  {sel} {kind_tag} {reg}  {WHITE}{ts['name']:<24}{RST}  {usage_str}")


def _filter_tilesets(tilesets, filter_mode, search):
    """Apply filter and search to tileset list."""
    result = tilesets
    if filter_mode == "primary":
        result = [t for t in result if t["kind"] == "primary"]
    elif filter_mode == "secondary":
        result = [t for t in result if t["kind"] == "secondary"]
    elif filter_mode == "unused":
        result = [t for t in result if t["map_count"] == 0]
    if search:
        sl = search.lower()
        result = [t for t in result if sl in t["name"].lower()
                  or sl in t["dir_name"]]
    return result


def _render_browse_page(state, filtered, tilesets, search, filter_mode,
                        settings, proj_name):
    """Render one page of the tileset browser."""
    start, end = visible_range(state)

    clear_screen()
    print_logo(proj_name)
    print(BAR)
    title = f"  {WHITE}Tilesets{RST}  {DIM}({len(filtered)} of {len(tilesets)}){RST}"
    if search:
        title += f"  {DIM}search: {CYAN}{search}{RST}"
    if filter_mode != "all":
        title += f"  {DIM}filter: {GOLD}{filter_mode}{RST}"
    print(title)
    print(BAR)

    above = overflow_above(state)
    if above:
        print(above)
    for i in range(start, end):
        _render_tileset_row(state, i, filtered[i])
    below = overflow_below(state)
    if below:
        print(below)

    print()
    hint = footer_hint(settings)
    print(f"  {hint}  {_k('/')} {DIM}search{RST}  {_k('f')} {DIM}filter{RST}  {_k('v')} {DIM}detail{RST}  {_k('q')} {DIM}back{RST}")
    print()


def _browse_tilesets(game_path, settings, proj_name=None):
    """Scrolling list of all tilesets with usage info."""
    tilesets = _scan_tilesets(game_path)
    if not tilesets:
        print(f"\n  {DIM}No tilesets found.{RST}")
        input(f"\n  {DIM}Press Enter{RST} > ")
        return

    usage = _get_tileset_maps(game_path)
    for ts in tilesets:
        maps = usage.get(ts["constant"], [])
        ts["map_count"] = len(maps)
        ts["maps"] = maps
    tilesets.sort(key=lambda t: (0 if t["kind"] == "secondary" else 1, t["name"]))

    page_size = 18
    state = ListState(total=len(tilesets), page_size=page_size, selected=0,
                      scroll_top=0)
    search = ""
    filter_mode = "all"

    while True:
        filtered = _filter_tilesets(tilesets, filter_mode, search)
        state.total = len(filtered)
        guard_bounds(state)
        _render_browse_page(state, filtered, tilesets, search, filter_mode,
                           settings, proj_name)

        try:
            ch = input(f"  {GOLD}>{RST} ").strip()
        except (EOFError, KeyboardInterrupt):
            return

        if ch == "q":
            return
        elif ch == "/":
            try:
                search = input(f"  {DIM}Search:{RST} ").strip()
            except (EOFError, KeyboardInterrupt):
                search = ""
            state.selected = 0
            state.scroll_top = 0
        elif ch == "f":
            modes = ["all", "primary", "secondary", "unused"]
            idx = modes.index(filter_mode) if filter_mode in modes else 0
            filter_mode = modes[(idx + 1) % len(modes)]
            state.selected = 0
            state.scroll_top = 0
        elif ch == "v" and filtered:
            _tileset_detail(game_path, filtered[state.selected], settings, proj_name)
        else:
            handle_input(state, ch, settings)


def _tileset_detail(game_path, tileset, settings, proj_name=None):
    """Show detailed info for one tileset."""
    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}{tileset['name']}{RST}  {DIM}({tileset['constant']}){RST}")
    print(BAR)
    print()

    print(f"  {DIM}Type:{RST}       {tileset['kind'].capitalize()}")
    print(f"  {DIM}Directory:{RST}  {CYAN}{tileset['path']}{RST}")
    print(f"  {DIM}Registered:{RST} {'Yes' if tileset['registered'] else f'{RED}No{RST}'}")
    print()

    # Maps using this tileset
    maps = tileset.get("maps", [])
    if maps:
        print(f"  {GOLD}Used by {len(maps)} map{'s' if len(maps) != 1 else ''}:{RST}")
        for m in maps[:20]:
            print(f"    {DIM}-{RST} {m}")
        if len(maps) > 20:
            print(f"    {DIM}... and {len(maps) - 20} more{RST}")
    else:
        print(f"  {DIM}Not used by any maps.{RST}")
    print()

    # Health check
    issues = _check_tileset_health(game_path, tileset)
    if issues:
        print(f"  {GOLD}Health issues:{RST}")
        for sev, msg in issues:
            icon = f"{RED}x{RST}" if sev == "error" else f"{GOLD}!{RST}"
            print(f"    {icon} {msg}")
    else:
        print(f"  {GREEN}Healthy{RST} — all files present and registered.")
    print()

    # File list
    ts_dir = os.path.join(game_path, tileset["path"])
    if os.path.isdir(ts_dir):
        print(f"  {GOLD}Files:{RST}")
        for entry in sorted(os.listdir(ts_dir)):
            full = os.path.join(ts_dir, entry)
            if os.path.isdir(full):
                print(f"    {DIM}{entry}/{RST}")
            else:
                size = os.path.getsize(full)
                if size < 1024:
                    sz = f"{size} B"
                else:
                    sz = f"{size / 1024:.1f} KB"
                print(f"    {entry}  {DIM}({sz}){RST}")

    input(f"\n  {DIM}Press Enter{RST} > ")


# ---------------------------------------------------------------------------
# TUI — Health check
# ---------------------------------------------------------------------------

def _print_health_problems(problem_tilesets, orphans):
    """Print detailed health check issues."""
    if problem_tilesets:
        print(f"  {RED}{len(problem_tilesets)} with issues:{RST}")
        print()
        for ts, issues in problem_tilesets:
            print(f"  {WHITE}{ts['constant']}{RST}  {DIM}({ts['kind']}){RST}")
            for sev, msg in issues:
                icon = f"{RED}x{RST}" if sev == "error" else f"{GOLD}!{RST}"
                print(f"    {icon} {msg}")
            print()
    if orphans:
        print(f"  {RED}{len(orphans)} orphaned registration{'s' if len(orphans) != 1 else ''}:{RST}")
        for const, path in orphans:
            print(f"    {RED}x{RST} {const} -> {DIM}{path}{RST} (directory missing)")
        print()


def _health_check(game_path, settings, proj_name=None):
    """Full validation report for all tilesets."""
    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}Tileset Health Check{RST}")
    print(BAR)
    print()

    tilesets = _scan_tilesets(game_path)
    if not tilesets:
        print(f"  {DIM}No tilesets found.{RST}")
        input(f"\n  {DIM}Press Enter{RST} > ")
        return

    primary = [t for t in tilesets if t["kind"] == "primary"]
    secondary = [t for t in tilesets if t["kind"] == "secondary"]

    healthy = 0
    problem_tilesets = []
    for ts in tilesets:
        issues = _check_tileset_health(game_path, ts)
        if issues:
            problem_tilesets.append((ts, issues))
        else:
            healthy += 1

    orphans = _check_orphaned_registrations(game_path)

    print(f"  {DIM}Primary:{RST} {len(primary)}  {DIM}Secondary:{RST} {len(secondary)}  {DIM}Total:{RST} {len(tilesets)}")
    print()

    if healthy == len(tilesets) and not orphans:
        print(f"  {GREEN}All {len(tilesets)} tilesets healthy.{RST}")
    else:
        print(f"  {GREEN}{healthy} healthy{RST}")
        _print_health_problems(problem_tilesets, orphans)

    input(f"\n  {DIM}Press Enter{RST} > ")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli_new(game_path, args):
    """Handle 'torch tileset new <name>'."""
    name = " ".join(args) if args else None
    if not name:
        print("  Usage: torch tileset new <name>")
        return
    ok, camel, dir_name, msgs = create_tileset_scaffold(game_path, name)
    print()
    _print_result_msgs(ok, msgs, ("Created", "Registered"))
    if ok:
        print(f"\n  {GREEN}Done!{RST} Edit in Porymap: data/tilesets/secondary/{dir_name}/")


def _cli_copy(game_path, args):
    """Handle 'torch tileset copy <source> <name>'."""
    if len(args) < 2:
        print("  Usage: torch tileset copy <source> <new_name>")
        return
    source = args[0]
    new_name = " ".join(args[1:])
    ok, camel, dir_name, msgs = create_tileset_copy(game_path, source, new_name)
    print()
    _print_result_msgs(ok, msgs, ("Copied", "Registered"))
    if ok:
        print(f"\n  {GREEN}Done!{RST} Edit in Porymap: data/tilesets/secondary/{dir_name}/")


def _cli_import(game_path, args):
    """Handle 'torch tileset import <source_path> [name]'."""
    if not args:
        print("  Usage: torch tileset import <source_path> [name]")
        print()
        print("  Import a tileset from another decomp project with automatic")
        print("  format conversion (metatile padding, attribute truncation).")
        print()
        print("  Examples:")
        print("    torch tileset import ~/Documents/pokefirered/data/tilesets/secondary/silph_co")
        print("    torch tileset import ~/Documents/pokefirered/data/tilesets/secondary/silph_co silph_co")
        return
    source_path = os.path.expanduser(args[0])
    new_name = " ".join(args[1:]) if len(args) > 1 else None
    ok, camel, dir_name, msgs = import_tileset(game_path, source_path, new_name)
    print()
    _print_result_msgs(ok, msgs, ("Copied", "Converted", "Registered", "Shared", "Source", "Target"))
    if ok:
        print(f"\n  {GREEN}Tileset imported as gTileset_{camel}{RST}")
        print(f"  Directory: data/tilesets/secondary/{dir_name}/")
        print(f"  Open Porymap to review metatiles and assign to a map layout.")


def _cli_repair(game_path, args):
    """CLI handler for 'torch tileset repair <name> <source_path>'."""
    if len(args) < 2:
        print("  Usage: torch tileset repair <tileset_name> <source_path>")
        print()
        print("  Re-convert metatile_attributes.bin from the original source")
        print("  to fix layer type data lost during a broken import.")
        print()
        print("  Example:")
        print("    torch tileset repair silph_co "
              "~/Documents/pokefirered/data/tilesets/secondary/silph_co")
        return

    tileset_name = args[0]
    source_path = os.path.expanduser(args[1])

    if not os.path.isdir(source_path):
        print(f"  {RED}Source path not found: {source_path}{RST}")
        return

    print(f"  Repairing {tileset_name} from {source_path} ...")
    print()
    ok, msgs = repair_metatile_attributes(game_path, tileset_name, source_path)
    for msg in msgs:
        tag = GREEN if ok else RED
        print(f"  {tag}{msg}{RST}" if "fixed" in msg.lower() or "processed" in msg.lower()
              else f"  {DIM}{msg}{RST}")
    print()
    if ok:
        print(f"  {GREEN}Repair complete.{RST}")
    else:
        print(f"  {RED}Repair failed.{RST}")


def _cli_usage():
    """Print CLI usage help."""
    print("  Usage:")
    print("    torch tileset                       Main menu")
    print("    torch tileset new <name>            Scaffold new tileset")
    print("    torch tileset copy <src> <name>     Copy tileset")
    print("    torch tileset import <path> [name]  Import from another decomp")
    print("    torch tileset repair <name> <src>   Fix broken attribute conversion")
    print("    torch tileset check                 Health check")


def tileset_command(game_path, settings, args=None, proj_name=None):
    """CLI entry point for 'torch tileset'."""
    if args is None:
        args = []

    if not args:
        tileset_assistant_menu(game_path, settings, proj_name=proj_name)
        return

    sub = args[0].lower()

    if sub == "new":
        _cli_new(game_path, args[1:])
    elif sub == "copy":
        _cli_copy(game_path, args[1:])
    elif sub == "import":
        _cli_import(game_path, args[1:])
    elif sub == "repair":
        _cli_repair(game_path, args[1:])
    elif sub == "check":
        _health_check(game_path, {}, proj_name=proj_name)
    else:
        print(f"  Unknown tileset subcommand: {sub}")
        print()
        _cli_usage()
