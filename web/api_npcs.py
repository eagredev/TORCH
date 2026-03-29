# TORCH_MODULE: Web API — NPCs
# TORCH_GROUP: Web
"""NPC API endpoints for the TORCH web GUI.

Provides endpoints to list maps with NPCs, get NPC details with parsed
dialogue, enumerate valid constants (movement types, graphics IDs), and
resolve NPC overworld sprite paths.
"""

import json
import os
import re

from torch.web.api import api_route, ok_response, error_response, _safe_path
from torch.names import _const_to_human_name
from torch.gamedata import parse_defines
from torch.project_files import load_map_json


# ---------------------------------------------------------------------------
# Constants cache
# ---------------------------------------------------------------------------

_constants_cache = None
_constants_game_path = None


# ---------------------------------------------------------------------------
# Sprite index cache
# ---------------------------------------------------------------------------

_sprite_index = None
_sprite_game_path = None


# ---------------------------------------------------------------------------
# Helpers — map scanning
# ---------------------------------------------------------------------------

def _get_all_maps(game_path):
    """Return sorted list of map directory names under data/maps/."""
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return []
    return sorted(
        d for d in os.listdir(maps_dir)
        if os.path.isdir(os.path.join(maps_dir, d))
        and not d.startswith(".")
    )


def _count_map_npcs(data):
    """Count NPCs, trainers, and detect nurse from a map.json dict."""
    events = data.get("object_events")
    if not isinstance(events, list):
        return 0, 0, False

    npc_count = len(events)
    trainer_count = 0
    has_nurse = False
    for obj in events:
        if not isinstance(obj, dict):
            continue
        if obj.get("trainer_type", "TRAINER_TYPE_NONE") != "TRAINER_TYPE_NONE":
            trainer_count += 1
        if obj.get("graphics_id", "") == "OBJ_EVENT_GFX_NURSE":
            has_nurse = True
    return npc_count, trainer_count, has_nurse


# ---------------------------------------------------------------------------
# Helpers — dialogue preview
# ---------------------------------------------------------------------------

# Match msgbox(format("text"), ...) or msgbox("text", ...)
_MSGBOX_RE = re.compile(
    r'msgbox\s*\(\s*(?:format\s*\(\s*)?'
    r'"([^"]*)"',
    re.DOTALL,
)


def _extract_dialogue_preview(game_path, map_name, script_label):
    """Extract a short dialogue preview from a script label in scripts.pory.

    Returns a cleaned string (max 80 chars) or None.
    """
    if not script_label:
        return None

    pory_path = os.path.join(
        game_path, "data", "maps", map_name, "scripts.pory"
    )
    try:
        with open(pory_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None

    return _find_dialogue_in_content(content, script_label)


def _find_dialogue_in_content(content, script_label):
    """Find a msgbox dialogue for a given script label in pory content."""
    # Find the script block
    label_pat = re.compile(
        r'script\s+' + re.escape(script_label) + r'\s*\{',
    )
    m = label_pat.search(content)
    if not m:
        return None

    # Extract text from the block (next ~2000 chars should be enough)
    block_start = m.end()
    block_text = content[block_start:block_start + 2000]

    msg = _MSGBOX_RE.search(block_text)
    if not msg:
        return None

    text = msg.group(1)
    # Clean GBA formatting
    text = text.replace("\\n", " ").replace("\\p", " ").replace("\\l", " ")
    text = text.replace("$", "")
    # Collapse whitespace
    text = " ".join(text.split())
    if len(text) > 80:
        text = text[:77] + "..."
    return text if text else None


# ---------------------------------------------------------------------------
# Helpers — sprite resolution
# ---------------------------------------------------------------------------

def _build_sprite_index(game_path):
    """Build a mapping from OBJ_EVENT_GFX_* → relative PNG path.

    Chains through four header files:
    1. pointers.h: OBJ_EVENT_GFX_X → gObjectEventGraphicsInfo_X
    2. graphics_info.h: gObjectEventGraphicsInfo_X → sPicTable_X
    3. pic_tables.h: sPicTable_X → gObjectEventPic_X
    4. graphics.h: gObjectEventPic_X → INCBIN path → .png
    """
    global _sprite_index, _sprite_game_path
    if _sprite_index is not None and _sprite_game_path == game_path:
        return _sprite_index

    base = os.path.join(game_path, "src", "data", "object_events")
    index = {}

    # Step 1: OBJ_EVENT_GFX_X → InfoName (e.g. "BrendanNormal")
    gfx_to_info = _parse_gfx_pointers(
        os.path.join(base, "object_event_graphics_info_pointers.h")
    )

    # Step 2: InfoName → PicTableName
    info_to_pic = _parse_info_to_pictable(
        os.path.join(base, "object_event_graphics_info.h")
    )

    # Step 3: PicTableName → PicName (gObjectEventPic_X symbol)
    pic_to_sym = _parse_pictable_to_symbol(
        os.path.join(base, "object_event_pic_tables.h")
    )

    # Step 4: PicName → INCBIN path
    sym_to_path = _parse_incbin_paths(
        os.path.join(base, "object_event_graphics.h")
    )

    # Chain: GFX → Info → PicTable → Symbol → path
    for gfx_const, info_name in gfx_to_info.items():
        pic_name = info_to_pic.get(info_name)
        if not pic_name:
            continue
        sym_name = pic_to_sym.get(pic_name)
        if not sym_name:
            continue
        incbin_path = sym_to_path.get(sym_name)
        if not incbin_path:
            continue
        # Convert .4bpp → .png
        png_path = re.sub(r'\.\w+$', '.png', incbin_path)
        full_path = os.path.join(game_path, png_path)
        if os.path.isfile(full_path):
            index[gfx_const] = png_path

    _sprite_index = index
    _sprite_game_path = game_path
    return index


def _parse_gfx_pointers(filepath):
    """Parse pointers.h: [OBJ_EVENT_GFX_X] = &gObjectEventGraphicsInfo_Y."""
    result = {}
    pat = re.compile(
        r'\[(\w+)\]\s*=\s*&gObjectEventGraphicsInfo_(\w+)'
    )
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.search(line)
                if m:
                    result[m.group(1)] = m.group(2)
    except OSError:
        pass
    return result


def _parse_info_to_pictable(filepath):
    """Parse graphics_info.h: gObjectEventGraphicsInfo_X has .images = sPicTable_Y."""
    result = {}
    current_info = None
    info_pat = re.compile(
        r'gObjectEventGraphicsInfo_(\w+)\s*='
    )
    pic_pat = re.compile(r'\.images\s*=\s*sPicTable_(\w+)')
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = info_pat.search(line)
                if m:
                    current_info = m.group(1)
                if current_info:
                    m2 = pic_pat.search(line)
                    if m2:
                        result[current_info] = m2.group(1)
                        current_info = None
    except OSError:
        pass
    return result


def _parse_pictable_to_symbol(filepath):
    """Parse pic_tables.h: sPicTable_X references gObjectEventPic_Y."""
    result = {}
    current_table = None
    table_pat = re.compile(r'sPicTable_(\w+)\s*\[\]')
    sym_pat = re.compile(r'gObjectEventPic_(\w+)')
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = table_pat.search(line)
                if m:
                    current_table = m.group(1)
                if current_table:
                    m2 = sym_pat.search(line)
                    if m2:
                        result[current_table] = m2.group(1)
                        current_table = None
    except OSError:
        pass
    return result


def _parse_incbin_paths(filepath):
    """Parse graphics.h: gObjectEventPic_X = INCBIN("path")."""
    result = {}
    pat = re.compile(
        r'gObjectEventPic_(\w+)\s*\[\]\s*=\s*INCBIN_U\d+\(\s*"([^"]+)"'
    )
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.search(line)
                if m:
                    result[m.group(1)] = m.group(2)
    except OSError:
        pass
    return result


def _get_sprite_url(game_path, graphics_id):
    """Resolve a graphics_id to a single-frame sprite URL, or None."""
    if not graphics_id or not graphics_id.startswith("OBJ_EVENT_GFX_"):
        return None
    return f"/api/assets/overworld-frame/{graphics_id}"


# ---------------------------------------------------------------------------
# Helpers — NPC building
# ---------------------------------------------------------------------------

def _build_npc_entry(obj, i, game_path, map_name, sprite_index):
    """Build a single NPC dict from an object_event entry."""
    local_id = obj.get("local_id")
    if isinstance(local_id, int):
        obj_id = local_id
    elif isinstance(local_id, str) and local_id.isdigit():
        obj_id = int(local_id)
    else:
        obj_id = i + 1

    gfx = obj.get("graphics_id", "")
    script = obj.get("script", "")
    if script in ("0x0", "0", ""):
        script = ""

    trainer_type = obj.get("trainer_type", "TRAINER_TYPE_NONE")
    is_trainer = trainer_type != "TRAINER_TYPE_NONE"

    flag = obj.get("flag", "")
    if flag == "0":
        flag = ""

    # Script type classification (lightweight — no npc_editor import)
    script_type = _classify_script_type(script, gfx)

    # Dialogue preview
    dialogue_preview = _extract_dialogue_preview(
        game_path, map_name, script
    ) if script else None

    # Sprite URL
    sprite_url = _get_sprite_url(game_path, gfx)

    return {
        "object_id": obj_id,
        "graphics_id": gfx,
        "display_name": _const_to_human_name(gfx, "OBJ_EVENT_GFX_"),
        "x": obj.get("x", 0),
        "y": obj.get("y", 0),
        "elevation": obj.get("elevation", 0),
        "movement_type": obj.get("movement_type", "MOVEMENT_TYPE_NONE"),
        "movement_range_x": obj.get("movement_range_x", 0),
        "movement_range_y": obj.get("movement_range_y", 0),
        "trainer_type": trainer_type,
        "trainer_sight_or_berry_tree_id": obj.get(
            "trainer_sight_or_berry_tree_id", "0"
        ),
        "flag": flag,
        "script": script,
        "script_type": script_type,
        "dialogue_preview": dialogue_preview,
        "sprite_url": sprite_url,
        "is_trainer": is_trainer,
    }


def _classify_script_type(script, graphics_id):
    """Lightweight script type classification without importing npc_editor."""
    if not script:
        return "none"
    s = script.lower()
    gfx = graphics_id.lower()
    if "nurse" in gfx:
        return "nurse"
    if "clerk" in gfx or "mart" in s:
        return "shop"
    if "sign" in s or "signpost" in s:
        return "sign"
    if "trainer" in s and "npc" not in s:
        return "trainer"
    if s in ("eventscript_pc", "common_eventscript_pc"):
        return "pc"
    if "item" in s or "give" in s:
        return "item_giver"
    if s.startswith("common_eventscript_"):
        return "shared"
    # Default: an NPC with a script is most likely a flavor NPC
    return "flavor"


def _build_bg_event(obj, i):
    """Build a bg_event dict from a bg_events entry."""
    return {
        "index": i,
        "type": obj.get("type", "sign"),
        "x": obj.get("x", 0),
        "y": obj.get("y", 0),
        "elevation": obj.get("elevation", 0),
        "player_facing_dir": obj.get(
            "player_facing_dir", "BG_EVENT_PLAYER_FACING_ANY"
        ),
        "script": obj.get("script", ""),
    }


# ---------------------------------------------------------------------------
# Helpers — constants
# ---------------------------------------------------------------------------

def _load_constants(game_path):
    """Load and cache NPC-related constants from game headers."""
    global _constants_cache, _constants_game_path
    if _constants_cache is not None and _constants_game_path == game_path:
        return _constants_cache

    movement_types = _load_const_list(
        game_path, "include/constants/event_object_movement.h",
        "MOVEMENT_TYPE_",
    )
    graphics_ids = _load_const_list(
        game_path, "include/constants/event_objects.h",
        "OBJ_EVENT_GFX_",
    )
    trainer_types = _load_const_list(
        game_path, "include/constants/trainer_types.h",
        "TRAINER_TYPE_",
    )

    _constants_cache = {
        "movement_types": movement_types,
        "graphics_ids": graphics_ids,
        "trainer_types": trainer_types,
    }
    _constants_game_path = game_path
    return _constants_cache


def _load_const_list(game_path, rel_header, prefix):
    """Parse defines from a header and return [{const, label}, ...]."""
    header_path = os.path.join(game_path, rel_header)
    defines = parse_defines(header_path, prefix)
    return [
        {"const": name, "label": _const_to_human_name(name, prefix)}
        for name, _comment in defines
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", "/api/npcs")
def handle_npc_maps(handler, match, query_params):
    """List all maps that have NPCs, with counts."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    q = (query_params.get("q", [""])[0] or "").lower()
    map_names = _get_all_maps(game_path)
    maps = []

    for map_name in map_names:
        if q and q not in map_name.lower():
            continue
        data = load_map_json(game_path, map_name)
        if not data:
            continue
        npc_count, trainer_count, has_nurse = _count_map_npcs(data)
        if npc_count == 0:
            continue
        maps.append({
            "name": map_name,
            "npc_count": npc_count,
            "trainer_count": trainer_count,
            "has_nurse": has_nurse,
        })

    return ok_response({"maps": maps})


@api_route("GET", "/api/npcs/constants")
def handle_npc_constants(handler, match, query_params):
    """Enumerate valid movement types, graphics IDs, and trainer types."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    constants = _load_constants(game_path)
    return ok_response(constants)


@api_route("GET", r"/api/npcs/(?P<map_name>[A-Za-z0-9_]+)")
def handle_npc_list(handler, match, query_params):
    """List all NPCs and BG events for a specific map."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    map_dir = os.path.join(game_path, "data", "maps", map_name)
    if not os.path.isdir(map_dir):
        return error_response(f"Map not found: {map_name}", 404)

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Cannot load map.json for: {map_name}", 500)

    # Build NPC list
    events = data.get("object_events", [])
    sprite_index = _build_sprite_index(game_path)
    npcs = []
    for i, obj in enumerate(events):
        if not isinstance(obj, dict):
            continue
        npcs.append(_build_npc_entry(obj, i, game_path, map_name, sprite_index))

    # Build BG events list
    bg_raw = data.get("bg_events", [])
    bg_events = []
    for i, obj in enumerate(bg_raw):
        if not isinstance(obj, dict):
            continue
        bg_events.append(_build_bg_event(obj, i))

    return ok_response({
        "name": map_name,
        "npcs": npcs,
        "bg_events": bg_events,
    })


@api_route("GET", r"/api/npc_sprites/(?P<path>.+)")
def handle_npc_sprite(handler, match, query_params):
    """Serve NPC overworld sprite PNG files."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    rel_path = match.group("path")
    base_dir = os.path.join(game_path, "graphics", "object_events", "pics")

    try:
        full_path = _safe_path(base_dir, rel_path)
    except ValueError:
        return error_response("Invalid path", 400)

    if not os.path.isfile(full_path):
        return error_response("Sprite not found", 404)

    # Read and serve the file directly
    try:
        with open(full_path, "rb") as f:
            data = f.read()
    except OSError:
        return error_response("Cannot read sprite file", 500)

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)
    return None
