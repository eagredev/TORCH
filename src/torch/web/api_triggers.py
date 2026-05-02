# TORCH_MODULE: Web API — Trigger Editor
# TORCH_GROUP: Web
"""Trigger (coord_event) CRUD endpoints for the TORCH web GUI.

Provides high-level trigger creation with script skeleton generation,
listing with script metadata, and deletion with optional script cleanup.
Low-level coord_event CRUD (position, update) is handled by api_events.py.
"""

import json
import os
import re

from torch.web.api import (
    api_route, ok_response, error_response, _read_json_body,
)
from torch.project_files import load_map_json, write_map_json, clear_project_cache


# ---------------------------------------------------------------------------
# Script skeleton templates
# ---------------------------------------------------------------------------

_TEMPLATES = {
    "basic": (
        'script {label}\n'
        'lock\n'
        'msgbox "Trigger text here.$"\n'
        'release\n'
        'end'
    ),
    "cutscene": (
        'script {label}\n'
        'lockall\n'
        'msgbox "Cutscene dialogue here.$"\n'
        'releaseall\n'
        'end'
    ),
    "weather_change": (
        'script {label}\n'
        'lock\n'
        'setweather WEATHER_RAIN\n'
        'doweather\n'
        'release\n'
        'end'
    ),
    "warp": (
        'script {label}\n'
        'lock\n'
        'warpsilent MAP_DESTINATION, 0, 0, 0\n'
        'release\n'
        'end'
    ),
    "item_check": (
        'script {label}\n'
        'lock\n'
        'checkitem ITEM_NONE, 1\n'
        'goto_if 1 {label}_HasItem\n'
        'msgbox "You need the item.$"\n'
        'release\n'
        'end\n'
        '\n'
        'script {label}_HasItem\n'
        'msgbox "You have the item!$"\n'
        'release\n'
        'end'
    ),
    "one_time": (
        'script {label}\n'
        'lock\n'
        'msgbox "This triggers only once.$"\n'
        'setflag {flag}\n'
        'release\n'
        'end'
    ),
}

_TEMPLATE_META = [
    {"id": "basic", "name": "Basic", "description": "Lock + message + release"},
    {"id": "cutscene", "name": "Cutscene", "description": "Lockall + dialogue + releaseall"},
    {"id": "weather_change", "name": "Weather Change", "description": "Set weather effect"},
    {"id": "warp", "name": "Warp", "description": "Silent warp to another map"},
    {"id": "item_check", "name": "Item Check", "description": "Check for item + branch"},
    {"id": "one_time", "name": "One-Time", "description": "Fire once via flag gate"},
]


def _sanitize_label(name):
    """Sanitize for use in a Poryscript label."""
    return re.sub(r'[^A-Za-z0-9_]', '', name)


def _generate_script_label(map_name, x, y, custom_label=None):
    """Generate a script label for a trigger."""
    if custom_label:
        safe = _sanitize_label(custom_label)
        if safe:
            return f"{map_name}_EventScript_{safe}"
    return f"{map_name}_Trigger_{x}_{y}"


def _next_flag_number(game_path, map_name):
    """Find a free temporary flag for one-time triggers."""
    # Use TEMP flags which are auto-cleared on map transitions
    # Just use a high offset based on existing trigger count
    data = load_map_json(game_path, map_name)
    if not data:
        return "FLAG_TEMP_1"
    coord_count = len(data.get("coord_events", []))
    return f"FLAG_TEMP_{coord_count + 1}"


def _write_trigger_script(game_path, map_name, label, template_id, project_dir=None):
    """Write a trigger script skeleton. Returns the path written, or None.

    If the map is enrolled in the workspace, writes TorScript .txt.
    Otherwise writes Poryscript to scripts.pory.
    """
    template_text = _TEMPLATES.get(template_id, _TEMPLATES["basic"])

    # Determine flag for one_time template
    flag = "FLAG_TEMP_1"
    if template_id == "one_time":
        flag = _next_flag_number(game_path, map_name)

    script_text = template_text.format(label=label, flag=flag)

    # Try workspace first
    if project_dir:
        try:
            from torch.registry import is_enrolled
            if is_enrolled(project_dir, map_name):
                ws_dir = os.path.join(project_dir, map_name)
                os.makedirs(ws_dir, exist_ok=True)
                # Extract short name from label for filename
                short_name = label
                prefix = f"{map_name}_EventScript_"
                trig_prefix = f"{map_name}_Trigger_"
                if short_name.startswith(prefix):
                    short_name = short_name[len(prefix):]
                elif short_name.startswith(trig_prefix):
                    short_name = short_name[len(trig_prefix):]
                out_path = os.path.join(ws_dir, f"{short_name}.txt")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(script_text + "\n")
                # Sync
                try:
                    from torch.sync import sync_map
                    from torch.web.api import _derive_sync_params
                    emotes_conf, source_display = _derive_sync_params(project_dir)
                    sync_map(map_name, project_dir, game_path,
                             emotes_conf, source_display,
                             quiet=True, skip_snapshot=True)
                except Exception:
                    pass
                return out_path
        except ImportError:
            pass

    # Fallback: write Poryscript directly into scripts.pory
    pory_path = os.path.join(game_path, "data", "maps", map_name, "scripts.pory")
    pory_text = _torscript_to_pory_skeleton(label, template_id, flag)

    try:
        existing = ""
        if os.path.isfile(pory_path):
            with open(pory_path, "r", encoding="utf-8") as f:
                existing = f.read()
        with open(pory_path, "w", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                existing += "\n"
            f.write(existing + "\n" + pory_text + "\n")
        return pory_path
    except OSError:
        return None


def _torscript_to_pory_skeleton(label, template_id, flag="FLAG_TEMP_1"):
    """Generate a minimal Poryscript skeleton for a trigger."""
    if template_id == "cutscene":
        return (
            f"script {label} {{\n"
            f"    lockall\n"
            f"    msgbox(\"{label}_Text\", MSGBOX_DEFAULT)\n"
            f"    releaseall\n"
            f"}}\n\n"
            f"text {label}_Text {{\n"
            f"    \"Cutscene dialogue here.$\"\n"
            f"}}"
        )
    elif template_id == "weather_change":
        return (
            f"script {label} {{\n"
            f"    lock\n"
            f"    setweather(WEATHER_RAIN)\n"
            f"    doweather\n"
            f"    release\n"
            f"}}"
        )
    elif template_id == "warp":
        return (
            f"script {label} {{\n"
            f"    lock\n"
            f"    warpsilent(MAP_DESTINATION, 0, 0, 0)\n"
            f"    release\n"
            f"}}"
        )
    elif template_id == "one_time":
        return (
            f"script {label} {{\n"
            f"    lock\n"
            f"    msgbox(\"{label}_Text\", MSGBOX_DEFAULT)\n"
            f"    setflag({flag})\n"
            f"    release\n"
            f"}}\n\n"
            f"text {label}_Text {{\n"
            f"    \"This triggers only once.$\"\n"
            f"}}"
        )
    elif template_id == "item_check":
        return (
            f"script {label} {{\n"
            f"    lock\n"
            f"    checkitem(ITEM_NONE, 1)\n"
            f"    if (var(VAR_RESULT) == TRUE) {{\n"
            f"        msgbox(\"{label}_HasText\", MSGBOX_DEFAULT)\n"
            f"    }} else {{\n"
            f"        msgbox(\"{label}_NeedText\", MSGBOX_DEFAULT)\n"
            f"    }}\n"
            f"    release\n"
            f"}}\n\n"
            f"text {label}_HasText {{\n"
            f"    \"You have the item!$\"\n"
            f"}}\n\n"
            f"text {label}_NeedText {{\n"
            f"    \"You need the item.$\"\n"
            f"}}"
        )
    else:  # basic
        return (
            f"script {label} {{\n"
            f"    lock\n"
            f"    msgbox(\"{label}_Text\", MSGBOX_DEFAULT)\n"
            f"    release\n"
            f"}}\n\n"
            f"text {label}_Text {{\n"
            f"    \"Trigger text here.$\"\n"
            f"}}"
        )


# ---------------------------------------------------------------------------
# GET /api/map/<name>/triggers — list triggers with metadata
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers")
def handle_trigger_list(handler, match, query_params):
    """List all coord_events with script resolution info."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    coord_events = data.get("coord_events", [])
    triggers = []
    for i, evt in enumerate(coord_events):
        triggers.append({
            "index": i,
            "x": evt.get("x", 0),
            "y": evt.get("y", 0),
            "elevation": evt.get("elevation", 0),
            "var": evt.get("var", "0"),
            "var_value": evt.get("var_value", "0"),
            "script": evt.get("script", ""),
            "type": evt.get("type", "trigger"),
        })

    return ok_response({"triggers": triggers, "count": len(triggers)})


# ---------------------------------------------------------------------------
# GET /api/triggers/templates — available script templates
# ---------------------------------------------------------------------------

@api_route("GET", "/api/triggers/templates")
def handle_trigger_templates(handler, match, query_params):
    """Return available trigger script templates."""
    return ok_response({"templates": _TEMPLATE_META})


# ---------------------------------------------------------------------------
# POST /api/map/<name>/triggers — create trigger
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers")
def handle_trigger_create(handler, match, query_params):
    """Create a new trigger (coord_event + script skeleton).

    Body: { x, y, elevation?, var?, var_value?, script_label?, template? }
    """
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body or not isinstance(body, dict):
        return error_response("Request body must be a JSON object", 400)

    if "x" not in body or "y" not in body:
        return error_response("Fields 'x' and 'y' are required", 400)

    try:
        x = int(body["x"])
        y = int(body["y"])
    except (ValueError, TypeError):
        return error_response("x and y must be integers", 400)

    elevation = int(body.get("elevation", 0))
    var = str(body.get("var", "0"))
    var_value = str(body.get("var_value", "0"))
    template_id = body.get("template", "basic")
    custom_label = body.get("script_label", "")

    # Generate script label
    label = _generate_script_label(map_name, x, y, custom_label)

    # Load map and add coord_event
    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    coord_event = {
        "type": "trigger",
        "x": x,
        "y": y,
        "elevation": elevation,
        "var": var,
        "var_value": var_value,
        "script": label,
    }

    events = data.setdefault("coord_events", [])
    events.append(coord_event)

    if not write_map_json(game_path, map_name, data):
        return error_response("Failed to write map.json", 500)

    clear_project_cache()

    # Generate script skeleton
    project_dir = getattr(handler.server, "project_dir", "") if handler else ""
    script_path = _write_trigger_script(
        game_path, map_name, label, template_id, project_dir=project_dir
    )

    return ok_response({
        "index": len(events) - 1,
        "event": coord_event,
        "script_label": label,
        "script_path": script_path or "",
        "template": template_id,
    })


# ---------------------------------------------------------------------------
# PUT /api/map/<name>/triggers/<index> — update trigger
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers/(?P<index>\d+)")
def handle_trigger_update(handler, match, query_params):
    """Update trigger properties.

    Body: JSON with fields to merge (x, y, elevation, var, var_value, script).
    """
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    index = int(match.group("index"))

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body or not isinstance(body, dict):
        return error_response("Request body must be a JSON object", 400)

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get("coord_events", [])
    if index < 0 or index >= len(events):
        return error_response(
            f"Trigger index {index} out of range (0..{len(events) - 1})", 404)

    event = events[index]
    for k, v in body.items():
        event[k] = v

    if not write_map_json(game_path, map_name, data):
        return error_response("Failed to write map.json", 500)

    clear_project_cache()

    return ok_response({"index": index, "event": event})


# ---------------------------------------------------------------------------
# DELETE /api/map/<name>/triggers/<index> — delete trigger
# ---------------------------------------------------------------------------

@api_route("DELETE", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers/(?P<index>\d+)")
def handle_trigger_delete(handler, match, query_params):
    """Delete a trigger by index."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    index = int(match.group("index"))

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get("coord_events", [])
    if index < 0 or index >= len(events):
        return error_response(
            f"Trigger index {index} out of range (0..{len(events) - 1})", 404)

    deleted = events.pop(index)

    if not write_map_json(game_path, map_name, data):
        return error_response("Failed to write map.json", 500)

    clear_project_cache()

    return ok_response({"deleted_index": index, "deleted": deleted})
