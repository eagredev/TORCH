# TORCH_MODULE: Web API — Map Event CRUD
# TORCH_GROUP: Web
"""Generic CRUD endpoints for map events (object_events, warp_events,
coord_events, bg_events).

These are low-level map.json manipulation endpoints used by the IDE's
direct map editing canvas.  Higher-level NPC creation with scripts and
dialogue stays in api_npc_editor.py.
"""

import json

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
