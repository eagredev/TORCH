# TORCH_MODULE: Web API — Map Event CRUD
# TORCH_GROUP: Web
"""Generic CRUD endpoints for map events (object_events, warp_events,
coord_events, bg_events).

These are low-level map.json manipulation endpoints used by the IDE's
direct map editing canvas.  Higher-level NPC creation with scripts and
dialogue stays in api_npc_editor.py.
"""

import json
import os
import re

from torch.web.api import (
    api_route, ok_response, error_response, _read_json_body,
)
from torch.project_files import load_map_json, write_map_json


# ---------------------------------------------------------------------------
# Event type mapping
# ---------------------------------------------------------------------------

_EVENT_TYPE_KEY = {
    "object": "object_events",
    "warp":   "warp_events",
    "coord":  "coord_events",
    "bg":     "bg_events",
}

# Default values for new events (minimal valid entries for Porymap)
_DEFAULTS = {
    "object": {
        "graphics_id": "OBJ_EVENT_GFX_WOMAN_1",
        "elevation": 0,
        "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
        "movement_range_x": 0,
        "movement_range_y": 0,
        "trainer_type": "TRAINER_TYPE_NONE",
        "trainer_sight_or_berry_tree_id": "0",
        "script": "",
        "flag": "0",
    },
    "warp": {
        "elevation": 0,
        "dest_map": "",
        "dest_warp_id": "0",
    },
    "coord": {
        "type": "trigger",
        "elevation": 0,
        "var": "0",
        "var_value": "0",
        "script": "",
    },
    "bg": {
        "type": "sign",
        "elevation": 0,
        "player_facing_dir": "BG_EVENT_PLAYER_FACING_ANY",
        "script": "",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_game_path(handler):
    """Extract game_path from the server."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return None, error_response("No game path configured", 500)
    return game_path, None


def _parse_type(type_str):
    """Validate and return the JSON key for an event type string."""
    key = _EVENT_TYPE_KEY.get(type_str)
    if not key:
        return None, error_response(
            f"Invalid event type: {type_str!r}. "
            f"Must be one of: {', '.join(_EVENT_TYPE_KEY)}", 400)
    return key, None


# ---------------------------------------------------------------------------
# POST /api/map/<name>/events/<type> — Create event
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/events/(?P<event_type>[a-z]+)")
def handle_event_create(handler, match, query_params):
    """Create a new event on the map.

    Body: JSON with at least ``x`` and ``y``.  Additional fields are merged
    with sensible defaults.  Returns the new event index.
    """
    game_path, err = _get_game_path(handler)
    if err:
        return err

    map_name = match.group("map_name")
    event_type = match.group("event_type")

    json_key, err = _parse_type(event_type)
    if err:
        return err

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body or not isinstance(body, dict):
        return error_response("Request body must be a JSON object with x, y", 400)

    if "x" not in body or "y" not in body:
        return error_response("Fields 'x' and 'y' are required", 400)

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    # Build the new event from defaults + body overrides
    defaults = dict(_DEFAULTS.get(event_type, {}))
    defaults["x"] = int(body["x"])
    defaults["y"] = int(body["y"])

    # Merge any extra fields from the request
    for k, v in body.items():
        if k in ("x", "y"):
            continue
        defaults[k] = v

    events = data.setdefault(json_key, [])
    events.append(defaults)

    if not write_map_json(game_path, map_name, data):
        return error_response("Failed to write map.json", 500)

    return ok_response({
        "index": len(events) - 1,
        "event": defaults,
    })


# ---------------------------------------------------------------------------
# POST /api/map/<name>/events/<type>/<index> — Update event
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/events/(?P<event_type>[a-z]+)/(?P<index>\d+)")
def handle_event_update(handler, match, query_params):
    """Update properties of an existing event.

    Body: JSON with fields to merge into the existing event.
    """
    game_path, err = _get_game_path(handler)
    if err:
        return err

    map_name = match.group("map_name")
    event_type = match.group("event_type")
    index = int(match.group("index"))

    json_key, err = _parse_type(event_type)
    if err:
        return err

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body or not isinstance(body, dict):
        return error_response("Request body must be a JSON object", 400)

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get(json_key, [])
    if index < 0 or index >= len(events):
        return error_response(
            f"Event index {index} out of range (0..{len(events)-1})", 404)

    # Merge fields
    event = events[index]
    for k, v in body.items():
        event[k] = v

    if not write_map_json(game_path, map_name, data):
        return error_response("Failed to write map.json", 500)

    return ok_response({"index": index, "event": event})


# ---------------------------------------------------------------------------
# DELETE /api/map/<name>/events/<type>/<index> — Delete event
# ---------------------------------------------------------------------------

@api_route("DELETE", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/events/(?P<event_type>[a-z]+)/(?P<index>\d+)")
def handle_event_delete(handler, match, query_params):
    """Delete an event by index."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    map_name = match.group("map_name")
    event_type = match.group("event_type")
    index = int(match.group("index"))

    json_key, err = _parse_type(event_type)
    if err:
        return err

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get(json_key, [])
    if index < 0 or index >= len(events):
        return error_response(
            f"Event index {index} out of range (0..{len(events)-1})", 404)

    deleted = events.pop(index)

    # Sanitize empty script fields on object_events (build safety)
    if json_key == "object_events":
        for obj in events:
            if not obj.get("script"):
                obj["script"] = ""

    if not write_map_json(game_path, map_name, data):
        return error_response("Failed to write map.json", 500)

    return ok_response({"deleted_index": index, "deleted": deleted})


# ---------------------------------------------------------------------------
# POST /api/map/<name>/events/<type>/<index>/position — Move event
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/events/(?P<event_type>[a-z]+)/(?P<index>\d+)/position")
def handle_event_move(handler, match, query_params):
    """Move an event to new coordinates. Body: ``{"x": N, "y": N}``."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    map_name = match.group("map_name")
    event_type = match.group("event_type")
    index = int(match.group("index"))

    json_key, err = _parse_type(event_type)
    if err:
        return err

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body or "x" not in body or "y" not in body:
        return error_response("Body must include 'x' and 'y'", 400)

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get(json_key, [])
    if index < 0 or index >= len(events):
        return error_response(
            f"Event index {index} out of range (0..{len(events)-1})", 404)

    events[index]["x"] = int(body["x"])
    events[index]["y"] = int(body["y"])

    if not write_map_json(game_path, map_name, data):
        return error_response("Failed to write map.json", 500)

    return ok_response({
        "index": index,
        "x": events[index]["x"],
        "y": events[index]["y"],
    })


# ---------------------------------------------------------------------------
# GET /api/map/<name>/sign-text/<script_label> — Resolve sign text
# ---------------------------------------------------------------------------

def _resolve_sign_text(game_path, map_name, script_label):
    """Resolve a basic sign script to its text content.

    Returns (text, text_label) if it's a basic msgbox+end sign, else (None, None).
    """
    inc_path = os.path.join(game_path, "data", "maps", map_name, "scripts.inc")
    if not os.path.isfile(inc_path):
        return None, None

    with open(inc_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the script label and check it's a basic msgbox + end
    pat = rf'^{re.escape(script_label)}::?\s*$'
    m = re.search(pat, content, re.MULTILINE)
    if not m:
        return None, None

    # Read script body lines until next label or EOF
    body_lines = []
    for line in content[m.end():].split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r'^\w+:{1,2}\s*$', stripped):
            break  # next label
        body_lines.append(stripped)

    # Check pattern: msgbox LABEL, MSGBOX_SIGN (or MSGBOX_DEFAULT) + end
    if len(body_lines) < 1:
        return None, None
    msgbox_m = re.match(r'^msgbox\s+(\w+),\s*MSGBOX_\w+$', body_lines[0])
    if not msgbox_m:
        return None, None

    text_label = msgbox_m.group(1)

    # Find the text label and extract .string content
    text_pat = rf'^{re.escape(text_label)}:\s*$'
    text_m = re.search(text_pat, content, re.MULTILINE)
    if not text_m:
        return None, None

    strings = []
    for line in content[text_m.end():].split("\n"):
        stripped = line.strip()
        if stripped.startswith(".string "):
            str_m = re.match(r'^\.string\s+"(.*)"$', stripped)
            if str_m:
                strings.append(str_m.group(1))
        elif stripped and not stripped.startswith("."):
            break
        elif not stripped:
            continue

    if not strings:
        return None, None

    return "".join(strings), text_label


@api_route("GET", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/sign-text/(?P<script_label>[A-Za-z0-9_]+)")
def handle_sign_text(handler, match, game_path, **kw):
    """Resolve a sign script label to its text content."""
    map_name = match.group("map_name")
    script_label = match.group("script_label")

    text, text_label = _resolve_sign_text(game_path, map_name, script_label)
    if text is None:
        return ok_response({"simple": False})

    return ok_response({
        "simple": True,
        "text": text,
        "text_label": text_label,
    })


# ---------------------------------------------------------------------------
# POST /api/map/<name>/sign-text/<script_label> — Save sign text
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/sign-text/(?P<script_label>[A-Za-z0-9_]+)")
def handle_sign_text_save(handler, match, game_path, **kw):
    """Save updated text for a basic sign script."""
    map_name = match.group("map_name")
    script_label = match.group("script_label")

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)

    new_text = body.get("text", "")
    if not new_text:
        return error_response("text is required", 400)

    inc_path = os.path.join(game_path, "data", "maps", map_name, "scripts.inc")
    if not os.path.isfile(inc_path):
        return error_response("scripts.inc not found", 404)

    # Resolve current text label
    text, text_label = _resolve_sign_text(game_path, map_name, script_label)
    if text is None or text_label is None:
        return error_response("Not a simple sign script", 400)

    with open(inc_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the text label block and replace .string lines
    text_pat = rf'^{re.escape(text_label)}:\s*$'
    text_m = re.search(text_pat, content, re.MULTILINE)
    if not text_m:
        return error_response(f"Text label {text_label} not found", 404)

    # Find extent of .string lines after the label
    after = content[text_m.end():]
    string_lines_end = 0
    for line in after.split("\n"):
        stripped = line.strip()
        if stripped.startswith(".string ") or not stripped:
            string_lines_end += len(line) + 1  # +1 for newline
        else:
            break

    # Build new .string lines (split on \p for multi-line)
    if not new_text.endswith("$"):
        new_text += "$"
    new_string_lines = f'\t.string "{new_text}"\n'

    # Replace
    new_content = content[:text_m.end()] + "\n" + new_string_lines + content[text_m.end() + string_lines_end:]

    with open(inc_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return ok_response({"saved": True})
