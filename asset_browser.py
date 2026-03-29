"""Asset Browser — read-only catalogue of game assets.

Browse all assets in the game, filterable by custom vs vanilla,
organized by type.  Supports trainer sprites, overworld sprites,
music tracks, sound effects, and tilesets.

Accessed via ``torch assets`` -> ``[2] Browse assets``.
"""
# TORCH_MODULE: Asset Browser
# TORCH_GROUP: Data

import os
import re

from torch.colours import GOLD, WHITE, CYAN, GREEN, RED, DIM, RST, BAR
from torch.ui import print_logo, clear_screen, _k
from torch.list_widget import (
    ListState, guard_bounds, visible_range, handle_input, marker,
    overflow_above, overflow_below, footer_hint,
)
from torch.config import _nav_keys

# Load vanilla reference sets from shared data file.
try:
    from torch.data_files.vanilla_asset_sets import (
        VANILLA_MUSIC, VANILLA_SOUND_EFFECTS, VANILLA_TILESETS,
        VANILLA_ITEM_ICONS, VANILLA_TRAINER_PICS, VANILLA_OVERWORLD_SPRITES,
    )
except ImportError:
    VANILLA_MUSIC = set()
    VANILLA_SOUND_EFFECTS = set()
    VANILLA_TILESETS = set()
    VANILLA_ITEM_ICONS = set()
    VANILLA_TRAINER_PICS = set()
    VANILLA_OVERWORLD_SPRITES = set()

# ============================================================
# GENERIC HEADER PARSER
# ============================================================

_DEFINE_RE = re.compile(r"^#define\s+(\w+)\s+(\d+)")


def _parse_defines(filepath, prefix):
    """Parse #define lines matching *prefix* from a C header.

    Returns list of (name, id_int) sorted by ID.
    Skips lines where the name equals the prefix + "COUNT"
    (e.g. TRAINER_PIC_COUNT).
    """
    count_name = prefix + "COUNT"
    results = []
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _DEFINE_RE.match(line)
                if not m:
                    continue
                name = m.group(1)
                if not name.startswith(prefix):
                    continue
                if name == count_name:
                    continue
                results.append((name, int(m.group(2))))
    except OSError:
        pass
    results.sort(key=lambda x: x[1])
    return results


# ============================================================
# DISPLAY NAME FORMATTING
# ============================================================

def _fmt_name(const, prefix):
    """Strip *prefix* from a constant name and title-case the rest."""
    if not const:
        return "?"
    tail = const
    if const.startswith(prefix):
        tail = const[len(prefix):]
    return tail.replace("_", " ").title()


# ============================================================
# ASSET SCANNERS
# ============================================================

def _scan_trainer_sprites(game_path):
    """Scan trainer sprites from constants/trainers.h.

    Returns list of dicts: {name, constant, id, is_custom, file}.
    """
    header = os.path.join(game_path, "include", "constants", "trainers.h")
    entries = _parse_defines(header, "TRAINER_PIC_")
    pics_dir = os.path.join(game_path, "graphics", "trainers", "front_pics")

    # Build INCBIN lookup for actual file paths (handles imported assets
    # where the constant name doesn't perfectly match the filename).
    incbin_map = _build_trainer_incbin_map(game_path)

    results = []
    for const, pic_id in entries:
        is_custom = const not in VANILLA_TRAINER_PICS
        # Try INCBIN lookup first, fall back to constant-derived name
        file_rel = incbin_map.get(const, "")
        if not file_rel:
            stem = const.replace("TRAINER_PIC_", "").lower()
            png_path = os.path.join(pics_dir, f"{stem}.png")
            file_rel = f"graphics/trainers/front_pics/{stem}.png"
            if not os.path.isfile(png_path):
                file_rel = ""
        elif not os.path.isfile(os.path.join(game_path, file_rel)):
            file_rel = ""
        results.append({
            "name": _fmt_name(const, "TRAINER_PIC_"),
            "constant": const,
            "id": pic_id,
            "is_custom": is_custom,
            "file": file_rel,
        })
    return results


def _build_trainer_incbin_map(game_path):
    """Parse src/data/graphics/trainers.h to map TRAINER_PIC_* -> PNG path.

    Uses the TRAINER_SPRITE() macro table to get the authoritative mapping
    from TRAINER_PIC_X to gTrainerFrontPic_Y, then resolves the INCBIN
    declaration for the actual file path.

    Returns dict: {"TRAINER_PIC_BROCK": "graphics/trainers/front_pics/brock.png", ...}
    """
    gfx_h = os.path.join(game_path, "src", "data", "graphics", "trainers.h")
    if not os.path.isfile(gfx_h):
        return {}

    try:
        text = open(gfx_h, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}

    # Step 1: symbol -> file path from INCBIN declarations
    symbol_to_path = {}
    for m in re.findall(
            r'const u32 (gTrainerFrontPic_\w+)\[\]\s*=\s*INCBIN_U32\("([^"]+)"',
            text):
        png_path = re.sub(r'\.\w+(\.\w+)?$', '.png', m[1])
        symbol_to_path[m[0]] = png_path

    # Step 2: TRAINER_PIC_X -> gTrainerFrontPic_Y from TRAINER_SPRITE() macros
    result = {}
    for m in re.findall(
            r'TRAINER_SPRITE\(\s*(TRAINER_PIC_\w+)\s*,\s*(gTrainerFrontPic_\w+)',
            text):
        pic_const, sym = m
        if sym in symbol_to_path:
            result[pic_const] = symbol_to_path[sym]

    return result


def _build_trainer_back_incbin_map(game_path):
    """Parse src/data/graphics/trainers.h to map TRAINER_BACK_PIC_* -> PNG path.

    Same approach as front sprites: uses TRAINER_BACK_SPRITE() macros for
    the authoritative constant-to-symbol mapping, then resolves INCBIN paths.
    """
    gfx_h = os.path.join(game_path, "src", "data", "graphics", "trainers.h")
    if not os.path.isfile(gfx_h):
        return {}

    try:
        text = open(gfx_h, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}

    # Step 1: symbol -> file path from INCBIN (back pics use u8 + INCBIN_U8)
    symbol_to_path = {}
    for m in re.findall(
            r'const u\d+ (gTrainerBackPic_\w+)\[\]\s*=\s*INCBIN_U\d+\("([^"]+)"',
            text):
        png_path = re.sub(r'\.\w+(\.\w+)?$', '.png', m[1])
        symbol_to_path[m[0]] = png_path

    # Step 2: TRAINER_BACK_PIC_X -> gTrainerBackPic_Y from TRAINER_BACK_SPRITE()
    # Macro: TRAINER_BACK_SPRITE(pic_const, yOffset, sprite_symbol, pal, anim)
    result = {}
    for m in re.findall(
            r'TRAINER_BACK_SPRITE\(\s*(TRAINER_BACK_PIC_\w+)\s*,'
            r'\s*\w+\s*,\s*(gTrainerBackPic_\w+)',
            text):
        pic_const, sym = m
        if sym in symbol_to_path:
            result[pic_const] = symbol_to_path[sym]

    return result


def _scan_overworld_sprites(game_path):
    """Scan overworld sprites from constants/event_objects.h.

    Returns list of dicts: {name, constant, id, is_custom, file}.
    """
    header = os.path.join(game_path, "include", "constants", "event_objects.h")
    entries = _parse_defines(header, "OBJ_EVENT_GFX_")
    # Skip NUM_OBJ_EVENT_GFX sentinel
    entries = [(n, i) for n, i in entries if n != "NUM_OBJ_EVENT_GFX"]

    results = []
    for const, gfx_id in entries:
        is_custom = const not in VANILLA_OVERWORLD_SPRITES
        results.append({
            "name": _fmt_name(const, "OBJ_EVENT_GFX_"),
            "constant": const,
            "id": gfx_id,
            "is_custom": is_custom,
            "file": "",
        })
    return results


def _scan_music_tracks(game_path):
    """Scan music tracks (MUS_*) from constants/songs.h.

    Returns list of dicts: {name, constant, id, is_custom, file}.
    """
    header = os.path.join(game_path, "include", "constants", "songs.h")
    entries = _parse_defines(header, "MUS_")
    # Filter: MUS_NONE (0xFFFF) and MUS_DUMMY (0) are not real tracks
    entries = [(n, i) for n, i in entries
               if n not in ("MUS_NONE", "MUS_DUMMY")]
    # MUS_ROUTE118 = 0x7FFF is a dynamic lookup, skip it
    entries = [(n, i) for n, i in entries if i < 0x7FFF]

    songs_dir = os.path.join(game_path, "sound", "songs")
    results = []
    for const, mus_id in entries:
        is_custom = const not in VANILLA_MUSIC
        stem = const.replace("MUS_", "").lower()
        song_dir = os.path.join(songs_dir, stem)
        file_rel = f"sound/songs/{stem}/" if os.path.isdir(song_dir) else ""
        results.append({
            "name": _fmt_name(const, "MUS_"),
            "constant": const,
            "id": mus_id,
            "is_custom": is_custom,
            "file": file_rel,
        })
    return results


def _scan_sound_effects(game_path):
    """Scan sound effects (SE_*) from constants/songs.h.

    Returns list of dicts: {name, constant, id, is_custom, file}.
    """
    header = os.path.join(game_path, "include", "constants", "songs.h")
    entries = _parse_defines(header, "SE_")

    results = []
    for const, se_id in entries:
        is_custom = const not in VANILLA_SOUND_EFFECTS
        results.append({
            "name": _fmt_name(const, "SE_"),
            "constant": const,
            "id": se_id,
            "is_custom": is_custom,
            "file": "",
        })
    return results


def _scan_tilesets(game_path):
    """Scan secondary tilesets from data/tilesets/secondary/.

    Returns list of dicts: {name, constant, id, is_custom, file}.
    """
    ts_dir = os.path.join(game_path, "data", "tilesets", "secondary")
    if not os.path.isdir(ts_dir):
        return []

    results = []
    try:
        dirs = sorted(os.listdir(ts_dir))
    except OSError:
        return []

    for i, name in enumerate(dirs):
        full = os.path.join(ts_dir, name)
        if not os.path.isdir(full):
            continue
        is_custom = name not in VANILLA_TILESETS
        results.append({
            "name": name.replace("_", " ").title(),
            "constant": name,
            "id": i,
            "is_custom": is_custom,
            "file": f"data/tilesets/secondary/{name}/",
        })
    return results


def _scan_trainer_back_sprites(game_path):
    """Scan trainer back sprites from constants/trainers.h.

    Returns list of dicts: {name, constant, id, is_custom, file}.
    """
    header = os.path.join(game_path, "include", "constants", "trainers.h")
    entries = _parse_defines(header, "TRAINER_BACK_PIC_")
    pics_dir = os.path.join(game_path, "graphics", "trainers", "back_pics")

    # Build INCBIN lookup for actual file paths
    back_incbin = _build_trainer_back_incbin_map(game_path)

    # Vanilla back pics (base pokeemerald has 8)
    vanilla_back = {
        "TRAINER_BACK_PIC_BRENDAN", "TRAINER_BACK_PIC_MAY",
        "TRAINER_BACK_PIC_RED", "TRAINER_BACK_PIC_LEAF",
        "TRAINER_BACK_PIC_RUBY_SAPPHIRE_BRENDAN",
        "TRAINER_BACK_PIC_RUBY_SAPPHIRE_MAY",
        "TRAINER_BACK_PIC_WALLY", "TRAINER_BACK_PIC_STEVEN",
    }
    results = []
    for const, pic_id in entries:
        is_custom = const not in vanilla_back
        # Try INCBIN lookup first, fall back to constant-derived name
        file_rel = back_incbin.get(const, "")
        if not file_rel:
            stem = const.replace("TRAINER_BACK_PIC_", "").lower()
            png_path = os.path.join(pics_dir, f"{stem}.png")
            file_rel = f"graphics/trainers/back_pics/{stem}.png"
            if not os.path.isfile(png_path):
                file_rel = ""
        elif not os.path.isfile(os.path.join(game_path, file_rel)):
            file_rel = ""
        results.append({
            "name": _fmt_name(const, "TRAINER_BACK_PIC_"),
            "constant": const,
            "id": pic_id,
            "is_custom": is_custom,
            "file": file_rel,
        })
    return results


def _scan_item_icons(game_path):
    """Scan item icons from src/data/graphics/items.h.

    Returns list of dicts: {name, constant, id, is_custom, file}.
    """
    items_h = os.path.join(game_path, "src", "data", "graphics", "items.h")
    if not os.path.isfile(items_h):
        return []

    # Parse gItemIcon_* INCBIN lines
    pat = re.compile(r"^const\s+u32\s+(gItemIcon_(\w+))\[\]")
    results = []
    try:
        with open(items_h, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                m = pat.match(line)
                if m:
                    full_name = m.group(1)
                    camel = m.group(2)
                    is_custom = full_name not in VANILLA_ITEM_ICONS
                    results.append({
                        "name": camel.replace("_", " "),
                        "constant": full_name,
                        "id": i,
                        "is_custom": is_custom,
                        "file": "",
                    })
    except OSError:
        pass
    return results


# ============================================================
# PALETTE INFO (overworld sprites)
# ============================================================

_TORCH_PAL_TAG_RE = re.compile(
    r"#define\s+(OBJ_EVENT_PAL_TAG_\w+)\s+(0x[0-9A-Fa-f]+)")

# Shared NPC palette tags (not custom)
_SHARED_NPC_TAGS = {
    "OBJ_EVENT_PAL_TAG_NPC_1", "OBJ_EVENT_PAL_TAG_NPC_2",
    "OBJ_EVENT_PAL_TAG_NPC_3", "OBJ_EVENT_PAL_TAG_NPC_4",
}

# TORCH custom tag range
_TORCH_TAG_MIN = 0x1125
_TORCH_TAG_MAX = 0x114F
_TORCH_TAG_CAPACITY = _TORCH_TAG_MAX - _TORCH_TAG_MIN + 1  # 43


def _count_custom_palettes(game_path):
    """Count TORCH-range custom palette tags in event_objects.h.

    Returns (count, max_capacity).
    """
    header = os.path.join(game_path, "include", "constants", "event_objects.h")
    count = 0
    try:
        with open(header, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _TORCH_PAL_TAG_RE.match(line)
                if m:
                    val = int(m.group(2), 16)
                    if _TORCH_TAG_MIN <= val <= _TORCH_TAG_MAX:
                        count += 1
    except OSError:
        pass
    return count, _TORCH_TAG_CAPACITY


def _get_sprite_palette_info(game_path, const_name):
    """Read palette tag and slot from a sprite's graphics info struct.

    const_name: OBJ_EVENT_GFX_* constant name
    Returns (tag_name, slot_name, is_custom) or (None, None, False).
    """
    info_h = os.path.join(game_path, "src", "data", "object_events",
                          "object_event_graphics_info.h")
    # Derive CamelCase struct name from constant
    # OBJ_EVENT_GFX_ROCKET_M -> RocketM
    suffix = const_name.replace("OBJ_EVENT_GFX_", "")
    camel = "".join(part.capitalize() for part in suffix.split("_") if part)
    struct_name = f"gObjectEventGraphicsInfo_{camel}"

    try:
        with open(info_h, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None, None, False

    pat = re.compile(
        rf"{re.escape(struct_name)}\s*=\s*\{{(.*?)\}};", re.DOTALL)
    m = pat.search(content)
    if not m:
        return None, None, False

    body = m.group(1)
    tag_m = re.search(r"\.paletteTag\s*=\s*(\w+)", body)
    slot_m = re.search(r"\.paletteSlot\s*=\s*(\w+)", body)
    if not tag_m:
        return None, None, False

    tag = tag_m.group(1)
    slot = slot_m.group(1) if slot_m else "?"
    is_custom = tag not in _SHARED_NPC_TAGS
    return tag, slot, is_custom


def _find_sprites_using_palette(game_path, tag_name):
    """Find all overworld sprites using a given palette tag.

    Scans object_event_graphics_info.h for structs with .paletteTag = tag_name.
    Returns list of CamelCase sprite names.
    """
    info_h = os.path.join(game_path, "src", "data", "object_events",
                          "object_event_graphics_info.h")
    try:
        with open(info_h, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return []

    results = []
    struct_pat = re.compile(
        r"gObjectEventGraphicsInfo_(\w+)\s*=\s*\{(.*?)\};", re.DOTALL)
    for m in struct_pat.finditer(content):
        body = m.group(2)
        tag_m = re.search(r"\.paletteTag\s*=\s*(\w+)", body)
        if tag_m and tag_m.group(1) == tag_name:
            results.append(m.group(1))
    return results


# ============================================================
# ASSET CATEGORIES
# ============================================================

_CATEGORIES = [
    {
        "key": "trainer_sprites",
        "name": "Front Sprites",
        "browse_name": "Trainer Front Sprites",
        "scanner": _scan_trainer_sprites,
        "prefix": "TRAINER_PIC_",
        "has_custom_detection": True,
        "detail_fn": "_trainer_sprite_detail",
    },
    {
        "key": "trainer_back_sprites",
        "name": "Back Sprites",
        "browse_name": "Trainer Back Sprites",
        "scanner": _scan_trainer_back_sprites,
        "prefix": "TRAINER_BACK_PIC_",
        "has_custom_detection": True,
        "detail_fn": None,
    },
    {
        "key": "overworld_sprites",
        "name": "Sprites",
        "browse_name": "Overworld Sprites",
        "scanner": _scan_overworld_sprites,
        "prefix": "OBJ_EVENT_GFX_",
        "has_custom_detection": True,
        "detail_fn": None,
    },
    {
        "key": "tilesets",
        "name": "Tilesets",
        "browse_name": "Tilesets",
        "scanner": _scan_tilesets,
        "prefix": "",
        "has_custom_detection": True,
        "detail_fn": None,
    },
    {
        "key": "music_tracks",
        "name": "Music Tracks",
        "browse_name": "Music Tracks",
        "scanner": _scan_music_tracks,
        "prefix": "MUS_",
        "has_custom_detection": True,
        "detail_fn": None,
    },
    {
        "key": "sound_effects",
        "name": "Sound Effects",
        "browse_name": "Sound Effects",
        "scanner": _scan_sound_effects,
        "prefix": "SE_",
        "has_custom_detection": True,
        "detail_fn": None,
    },
    {
        "key": "item_icons",
        "name": "Item Icons",
        "browse_name": "Item Icons",
        "scanner": _scan_item_icons,
        "prefix": "gItemIcon_",
        "has_custom_detection": True,
        "detail_fn": None,
    },
]

# Grouped layout for the category picker menu.
# Each tuple: (group_label, [category_key, ...])
_CATEGORY_GROUPS = [
    ("Trainers", ["trainer_sprites", "trainer_back_sprites"]),
    ("Overworld", ["overworld_sprites", "tilesets"]),
    ("Audio", ["music_tracks", "sound_effects"]),
    ("Items", ["item_icons"]),
]

# Build lookup from key -> category dict for fast access.
_CAT_BY_KEY = {c["key"]: c for c in _CATEGORIES}


# ============================================================
# CAPACITY BAR
# ============================================================

def _render_bar(used, total, width=20):
    """Render a mini ASCII progress bar.

    Returns a string like:  ``████░░░░░░░░░░░░░░░░``
    Coloured green / yellow / red based on usage percentage.
    """
    if total <= 0:
        return f"{DIM}{'░' * width}{RST}"
    ratio = min(used / total, 1.0)
    filled = round(ratio * width)
    empty = width - filled
    pct = used / total
    if pct >= 0.93:
        colour = RED
    elif pct >= 0.80:
        colour = GOLD
    else:
        colour = GREEN
    return f"{colour}{'█' * filled}{DIM}{'░' * empty}{RST}"


# ============================================================
# FILTERING
# ============================================================

_FILTER_MODES = ("all", "custom", "vanilla")


def _filter_assets(assets, filter_mode):
    """Filter asset list by mode.  Returns a new list."""
    if filter_mode == "all":
        return list(assets)
    if filter_mode == "custom":
        return [a for a in assets if a["is_custom"]]
    if filter_mode == "vanilla":
        return [a for a in assets if not a["is_custom"]]
    return list(assets)


def _search_assets(assets, query):
    """Filter assets whose name or constant contains *query* (case-insensitive)."""
    q = query.lower()
    return [a for a in assets
            if q in a["name"].lower() or q in a["constant"].lower()]


# ============================================================
# TRAINER SPRITE CROSS-REFERENCE
# ============================================================

def _build_sprite_trainer_map(game_path):
    """Build mapping from TRAINER_PIC_* constant to list of trainers using it.

    Parses src/data/trainers.h for .trainerPic assignments.
    Returns dict: {pic_const: [(trainer_const, map_folder)]}.
    """
    trainers_h = os.path.join(game_path, "src", "data", "trainers.h")
    if not os.path.isfile(trainers_h):
        return {}

    pic_re = re.compile(r"\.trainerPic\s*=\s*(TRAINER_PIC_\w+)")
    trainer_re = re.compile(r"\[(?:DIFFICULTY_\w+)\]\[(\w+)\]")

    pic_to_trainers = {}
    current_trainer = None

    try:
        with open(trainers_h, encoding="utf-8", errors="replace") as f:
            for line in f:
                tm = trainer_re.search(line)
                if tm:
                    current_trainer = tm.group(1)
                pm = pic_re.search(line)
                if pm and current_trainer and current_trainer != "TRAINER_NONE":
                    pic_const = pm.group(1)
                    pic_to_trainers.setdefault(pic_const, []).append(
                        current_trainer
                    )
    except OSError:
        pass

    # Deduplicate trainer entries per pic
    for pic in pic_to_trainers:
        pic_to_trainers[pic] = sorted(set(pic_to_trainers[pic]))

    # Add map locations
    try:
        from torch.project_files import build_trainer_map_index
        _, trainer_map = build_trainer_map_index(game_path)
    except (ImportError, Exception):
        trainer_map = {}

    result = {}
    for pic, trainers in pic_to_trainers.items():
        entries = []
        for t in trainers:
            map_folder = trainer_map.get(t, "")
            entries.append((t, map_folder))
        result[pic] = entries
    return result


# ============================================================
# DETAIL VIEW
# ============================================================

def _asset_detail(game_path, asset, category, sprite_map=None):
    """Show detail view for a selected asset.  Blocks until user presses Enter."""
    clear_screen()
    print()
    browse = category.get("browse_name", category["name"])
    print(f"  {WHITE}{browse}: {asset['name']}{RST}")
    print(BAR)
    print()
    print(f"  {DIM}Constant:{RST}  {WHITE}{asset['constant']}{RST}")
    print(f"  {DIM}ID:{RST}       {asset['id']}")
    if asset["file"]:
        print(f"  {DIM}File:{RST}     {CYAN}{asset['file']}{RST}")
    if category["has_custom_detection"]:
        status = f"{GREEN}Custom{RST}" if asset["is_custom"] else f"{DIM}Vanilla{RST}"
        print(f"  {DIM}Status:{RST}   {status}")

    # Trainer sprite cross-reference
    if category["key"] == "trainer_sprites" and sprite_map:
        trainers = sprite_map.get(asset["constant"], [])
        if trainers:
            print()
            print(f"  {DIM}Used by trainers:{RST}")
            for trainer_const, map_folder in trainers:
                t_name = _fmt_name(trainer_const, "TRAINER_")
                loc = f" ({_fmt_name(map_folder, '')})" if map_folder else ""
                print(f"    {WHITE}{t_name}{RST}{DIM}{loc}{RST}")
        else:
            print()
            print(f"  {DIM}Not used by any trainer.{RST}")

    # Overworld sprite palette info
    if category["key"] == "overworld_sprites":
        tag, slot, is_custom = _get_sprite_palette_info(game_path, asset["constant"])
        if tag:
            print()
            if is_custom:
                print(f"  {DIM}Palette:{RST}  {WHITE}{tag}{RST} {DIM}(custom){RST}")
                print(f"  {DIM}Slot:{RST}     {slot}")
                # Show which sprites share this palette
                shared = _find_sprites_using_palette(game_path, tag)
                # Remove this sprite itself from the list
                suffix = asset["constant"].replace("OBJ_EVENT_GFX_", "")
                self_camel = "".join(
                    p.capitalize() for p in suffix.split("_") if p)
                others = [s for s in shared if s != self_camel]
                if others:
                    print(f"  {DIM}Shared with:{RST}")
                    for s in others:
                        print(f"    {WHITE}{s}{RST}")
            else:
                # Shared NPC palette — show how many sprites use it
                users = _find_sprites_using_palette(game_path, tag)
                tag_short = tag.replace("OBJ_EVENT_PAL_TAG_", "")
                print(f"  {DIM}Palette:{RST}  {tag_short}"
                      f" {DIM}(shared by {len(users)} sprites){RST}")
                print(f"  {DIM}Slot:{RST}     {slot}")

    print()
    input(f"  {DIM}Press Enter to return{RST} > ")


# ============================================================
# SCROLLING LIST BROWSER
# ============================================================

def _browse_category(game_path, category, settings):
    """Scrolling list browser for a single asset category."""
    all_assets = category["scanner"](game_path)
    if not all_assets:
        print(f"\n  {DIM}No {category['name'].lower()} found.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    has_filter = category["has_custom_detection"]
    filter_mode = "all"
    search_query = ""
    nav = _nav_keys(settings)
    page_size = settings.get("map_list_page_size", 20)

    # Pre-build sprite map for trainer cross-reference
    sprite_map = None
    if category["key"] == "trainer_sprites":
        sprite_map = _build_sprite_trainer_map(game_path)

    while True:
        # Apply filter and search
        view = _filter_assets(all_assets, filter_mode) if has_filter else list(all_assets)
        if search_query:
            view = _search_assets(view, search_query)

        state = ListState(len(view), page_size=page_size)
        _browse_list_loop(
            game_path, category, view, state, nav,
            all_assets, has_filter, filter_mode, search_query,
            sprite_map, settings,
        )
        # _browse_list_loop returns a tuple: (action, new_filter, new_search)
        # We re-enter the loop with updated filter/search, or break on quit
        break


def _render_summary(all_assets, has_filter, filter_mode, search_query):
    """Build the summary line for the browser header."""
    total = len(all_assets)
    if has_filter:
        n_custom = sum(1 for a in all_assets if a["is_custom"])
        n_vanilla = total - n_custom
        summary = f"  {DIM}{total} total ({n_custom} custom, {n_vanilla} vanilla){RST}"
    else:
        summary = f"  {DIM}{total} total{RST}"
    if search_query:
        summary += f"  {DIM}search: \"{search_query}\"{RST}"
    if filter_mode != "all":
        summary += f"  {DIM}filter: {filter_mode}{RST}"
    return summary


def _render_asset_list(view, state, has_filter):
    """Render the visible slice of the asset list."""
    if not view:
        print(f"\n  {DIM}No matching assets.{RST}")
        return
    above = overflow_above(state)
    if above:
        print(above)
    start, end = visible_range(state)
    for i in range(start, end):
        asset = view[i]
        mk = marker(state, i)
        idx = f"{i + 1}.".rjust(5)
        tag = ""
        if has_filter and asset["is_custom"]:
            tag = f" {GREEN}[CUSTOM]{RST}"
        print(f"  {mk} {idx}{tag} {WHITE}{asset['name']}{RST}"
              f"  {DIM}{asset['constant']}{RST}")
    below = overflow_below(state)
    if below:
        print(below)


def _rebuild_view(all_assets, has_filter, filter_mode, search_query):
    """Apply current filter and search to produce the visible list."""
    view = _filter_assets(all_assets, filter_mode) if has_filter else list(all_assets)
    if search_query:
        view = _search_assets(view, search_query)
    return view


def _browse_list_loop(game_path, category, view, state, nav,
                      all_assets, has_filter, filter_mode, search_query,
                      sprite_map, settings):
    """Inner interactive loop for the scrolling list."""
    page_size = state.page_size

    while True:
        clear_screen()
        print_logo(None)
        print(BAR)
        print(f"  {WHITE}{category.get('browse_name', category['name'])}{RST}")
        print(_render_summary(all_assets, has_filter, filter_mode, search_query))
        print(BAR)
        _render_asset_list(view, state, has_filter)

        # Footer
        print()
        extra = f"  {_k('/')}search"
        if has_filter:
            extra += f"  {_k('f')}ilter"
        extra += f"  {_k('v')}iew"
        print(footer_hint(nav, extra=extra))
        print()

        raw = input(f"  {GOLD}>{RST} ").strip()

        # Search
        if raw == "/":
            search_query = input(f"  {DIM}Search:{RST} ").strip()
            view = _rebuild_view(all_assets, has_filter, filter_mode, search_query)
            state = ListState(len(view), page_size=page_size)
            continue

        # Filter toggle
        if raw.lower() == "f" and has_filter:
            idx = _FILTER_MODES.index(filter_mode)
            filter_mode = _FILTER_MODES[(idx + 1) % len(_FILTER_MODES)]
            view = _rebuild_view(all_assets, has_filter, filter_mode, search_query)
            state = ListState(len(view), page_size=page_size)
            continue

        # Detail view on 'v' or open key
        action = handle_input(state, raw, nav)
        if action in ("open", "jump_act"):
            if view and 0 <= state.selected < len(view):
                _asset_detail(game_path, view[state.selected], category,
                              sprite_map)
            continue

        if action == "quit":
            return

        # scroll, up, down, jump all handled by handle_input mutating state


# ============================================================
# CATEGORY PICKER
# ============================================================

def asset_browser_menu(game_path, settings, proj_name=None):
    """Asset Browser category picker and dispatch."""
    # Column layout constants
    _NAME_W = 20   # category name column width
    _NUM_W = 7     # vanilla/custom number column width

    while True:
        clear_screen()
        print_logo(proj_name)
        print(BAR)
        print(f"  {WHITE}Asset Browser{RST}")
        print(BAR)

        # Pre-scan all categories once per render
        scan_cache = {}
        for cat in _CATEGORIES:
            assets = cat["scanner"](game_path)
            total = len(assets)
            n_custom = sum(1 for a in assets if a["is_custom"])
            n_vanilla = total - n_custom
            scan_cache[cat["key"]] = (total, n_vanilla, n_custom)

        # Render grouped categories with column headers
        num = 0  # running menu number
        for group_label, cat_keys in _CATEGORY_GROUPS:
            print()
            # Group header with column labels
            pad = " " * (_NAME_W - len(group_label))
            print(f"  {WHITE}{group_label}{RST}{pad}"
                  f"  {DIM}{'Vanilla':>{_NUM_W}}{'Custom':>{_NUM_W}}{RST}")
            for key in cat_keys:
                cat = _CAT_BY_KEY[key]
                num += 1
                total, n_vanilla, n_custom = scan_cache[key]
                name_pad = " " * max(0, _NAME_W - len(cat["name"]) - 4)
                custom_str = str(n_custom) if cat["has_custom_detection"] else "-"
                vanilla_str = str(n_vanilla) if cat["has_custom_detection"] else str(total)
                print(f"  {_k(str(num))} {WHITE}{cat['name']}{RST}{name_pad}"
                      f"  {vanilla_str:>{_NUM_W}}{custom_str:>{_NUM_W}}")

        # Capacity section
        pal_count, pal_max = _count_custom_palettes(game_path)
        print()
        print(f"  {DIM}{'─' * 3} Capacity {'─' * 37}{RST}")
        bar = _render_bar(pal_count, pal_max)
        print(f"  {DIM}OW Palette Tags{RST}"
              f"    {WHITE}{pal_count:>2}{RST}{DIM} / {pal_max}{RST}"
              f"  {bar}")

        print()
        print(f"  {_k('q')} {DIM}Back{RST}")
        print()

        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if choice in ("q", ""):
            return

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(_CATEGORIES):
                _browse_category(game_path, _CATEGORIES[idx], settings)
