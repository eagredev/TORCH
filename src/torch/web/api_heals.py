# TORCH_MODULE: Web API — Heals
# TORCH_GROUP: Web
"""Heal location API endpoints for the TORCH web GUI.

Provides endpoints to list, create, edit, delete heal locations,
run drift/missing scans, auto-fix drift, and auto-add missing locations.
"""

import os
import re

from torch.web.api import api_route, ok_response, error_response, _read_json_body
from torch.project_files import (
    load_heal_locations, write_heal_locations, clear_project_cache,
    folder_to_map_const,
)
from torch.heal_locations import (
    _heal_id_to_display,
    _map_const_to_heal_id,
    _map_const_to_folder,
    _detect_heal_coords,
    _detect_respawn_npc,
    _find_pokecenter_warps,
    _scan_drift,
    _scan_missing,
    _apply_drift_fixes,
    _auto_add_heal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _loc_to_dict(loc):
    """Convert an internal heal location dict to API response format."""
    loc_id = loc.get("id", "")
    return {
        "id": loc_id,
        "display_name": _heal_id_to_display(loc_id),
        "map": loc.get("map", ""),
        "x": loc.get("x"),
        "y": loc.get("y"),
        "respawn_map": loc.get("respawn_map"),
        "respawn_npc": loc.get("respawn_npc"),
        "respawn_x": loc.get("respawn_x"),
        "respawn_y": loc.get("respawn_y"),
    }


def _validate_create_body(body):
    """Validate a heal location create payload.

    Returns error message string on failure, or None on success.
    """
    heal_id = body.get("id", "")
    map_const = body.get("map", "")
    x = body.get("x")
    y = body.get("y")
    if not heal_id or not heal_id.startswith("HEAL_LOCATION_"):
        return "'id' must start with HEAL_LOCATION_"
    if not map_const or not map_const.startswith("MAP_"):
        return "'map' must start with MAP_"
    if not isinstance(x, int) or x < 0:
        return "'x' must be a non-negative integer"
    if not isinstance(y, int) or y < 0:
        return "'y' must be a non-negative integer"
    return None


_EDIT_VALID_FIELDS = {"map", "x", "y", "respawn_map", "respawn_npc"}


def _validate_edit_body(body):
    """Validate a heal location edit payload.

    Returns error message string on failure, or None on success.
    """
    field = body.get("field", "")
    value = body.get("value")
    if field not in _EDIT_VALID_FIELDS:
        return f"Invalid field '{field}'. Valid: {', '.join(sorted(_EDIT_VALID_FIELDS))}"
    if field in ("x", "y"):
        if not isinstance(value, int) or value < 0:
            return f"'{field}' must be a non-negative integer"
    elif field == "map":
        if not isinstance(value, str) or not value.startswith("MAP_"):
            return "'map' must start with MAP_"
    elif field in ("respawn_map", "respawn_npc"):
        if not isinstance(value, str):
            return f"'{field}' must be a string"
    return None


# ---------------------------------------------------------------------------
# GET /api/heals — list all heal locations
# ---------------------------------------------------------------------------

@api_route("GET", "/api/heals")
def handle_heals_list(handler, match, query_params):
    """Return all heal locations."""
    game_path = handler.server.game_path
    locations = load_heal_locations(game_path)
    if locations is None:
        return error_response("heal_locations.json not found or invalid", 404)
    data = [_loc_to_dict(loc) for loc in locations]
    return ok_response({"locations": data, "count": len(data)})


# ---------------------------------------------------------------------------
# GET /api/heals/detect?map=<folder_name> — auto-detect for a map
# ---------------------------------------------------------------------------

@api_route("GET", "/api/heals/detect")
def handle_heals_detect(handler, match, query_params):
    """Auto-detect heal coords and respawn for a map folder."""
    game_path = handler.server.game_path
    map_name = (query_params.get("map") or [""])[0]
    if not map_name:
        return error_response("'map' query parameter required")

    warnings = []

    # Detect coordinates
    coords = _detect_heal_coords(game_path, map_name)
    coords_dict = None
    if coords:
        coords_dict = {"x": coords[0], "y": coords[1]}
    else:
        warnings.append("Could not auto-detect heal tile coordinates")

    # Find Pokemon Center warp
    pc_warps = _find_pokecenter_warps(game_path, map_name)
    respawn_map = None
    respawn_npc = None
    if pc_warps:
        respawn_map = pc_warps[0]
        # Detect nurse NPC
        respawn_folder = _map_const_to_folder(respawn_map, game_path)
        npc = _detect_respawn_npc(game_path, respawn_folder)
        if npc is not None:
            respawn_npc = str(npc)
        else:
            respawn_npc = "1"
            warnings.append("Nurse NPC not found in respawn map")
    else:
        warnings.append("No Pokemon Center warp found for this map")

    return ok_response({
        "coords": coords_dict,
        "respawn_map": respawn_map,
        "respawn_npc": respawn_npc,
        "warnings": warnings,
    })


# ---------------------------------------------------------------------------
# POST /api/heals — create a new heal location
# ---------------------------------------------------------------------------

@api_route("POST", "/api/heals")
def handle_heals_create(handler, match, query_params):
    """Create a new heal location."""
    game_path = handler.server.game_path
    body = _read_json_body(handler)
    if not body:
        return error_response("JSON body required")

    err = _validate_create_body(body)
    if err:
        return error_response(err)

    heal_id = body["id"]
    map_const = body["map"]
    respawn_map = body.get("respawn_map")
    respawn_npc = body.get("respawn_npc")

    clear_project_cache()
    locations = load_heal_locations(game_path)
    if locations is None:
        return error_response("heal_locations.json not found or invalid", 404)

    if any(loc.get("id") == heal_id for loc in locations):
        return error_response(f"Heal location '{heal_id}' already exists", 409)

    entry = {"id": heal_id, "map": map_const, "x": body["x"], "y": body["y"]}
    if respawn_map:
        entry["respawn_map"] = respawn_map
    if respawn_npc:
        entry["respawn_npc"] = str(respawn_npc)

    locations.append(entry)
    if not write_heal_locations(game_path, locations):
        return error_response("Failed to write heal_locations.json", 500)

    return ok_response({"created": heal_id})


# ---------------------------------------------------------------------------
# POST /api/heals/<heal_id> — edit a heal location field
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/heals/([A-Z0-9_]+)")
def handle_heals_edit(handler, match, query_params):
    """Edit a single field of a heal location."""
    heal_id = match.group(1)
    game_path = handler.server.game_path

    # Guard against matching other sub-routes
    if heal_id in ("scan", "fix-drift", "auto-add", "fix-nurse"):
        return error_response("Not found", 404)

    body = _read_json_body(handler)
    if not body:
        return error_response("JSON body required")

    err = _validate_edit_body(body)
    if err:
        return error_response(err)

    clear_project_cache()
    locations = load_heal_locations(game_path)
    if locations is None:
        return error_response("heal_locations.json not found or invalid", 404)

    target = None
    for loc in locations:
        if loc.get("id") == heal_id:
            target = loc
            break
    if target is None:
        return error_response(f"Heal location '{heal_id}' not found", 404)

    target[body["field"]] = body["value"]
    if not write_heal_locations(game_path, locations):
        return error_response("Failed to write heal_locations.json", 500)

    return ok_response(_loc_to_dict(target))


# ---------------------------------------------------------------------------
# POST /api/heals/<heal_id>/delete — delete a heal location
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/heals/([A-Z0-9_]+)/delete")
def handle_heals_delete(handler, match, query_params):
    """Delete a heal location."""
    heal_id = match.group(1)
    game_path = handler.server.game_path

    clear_project_cache()
    locations = load_heal_locations(game_path)
    if locations is None:
        return error_response("heal_locations.json not found or invalid", 404)

    new_list = [loc for loc in locations if loc.get("id") != heal_id]
    if len(new_list) == len(locations):
        return error_response(f"Heal location '{heal_id}' not found", 404)

    if not write_heal_locations(game_path, new_list):
        return error_response("Failed to write heal_locations.json", 500)

    return ok_response({"deleted": heal_id})


# ---------------------------------------------------------------------------
# POST /api/heals/scan — run drift + missing scan
# ---------------------------------------------------------------------------

@api_route("POST", "/api/heals/scan")
def handle_heals_scan(handler, match, query_params):
    """Run drift check and missing map scan."""
    game_path = handler.server.game_path

    clear_project_cache()
    locations = load_heal_locations(game_path)
    if locations is None:
        return error_response("heal_locations.json not found or invalid", 404)

    # Drift scan
    raw_drift = _scan_drift(game_path, locations)
    drift = []
    for _idx, loc_id, old_xy, new_xy, _override in raw_drift:
        drift.append({
            "id": loc_id,
            "old_x": old_xy[0], "old_y": old_xy[1],
            "new_x": new_xy[0], "new_y": new_xy[1],
        })

    # Missing scan
    raw_missing = _scan_missing(game_path)
    missing = []
    for folder, map_type, has_heal, has_pc in raw_missing:
        if not has_heal:
            missing.append({
                "folder": folder,
                "map_type": map_type,
                "has_pc": has_pc,
            })

    # Nurse script health scan
    nurse_issues = []
    try:
        from torch.npc_editor import validate_nurse_script
        for loc in locations:
            if "respawn_map" not in loc:
                continue
            respawn_const = loc.get("respawn_map", "")
            respawn_folder = _map_const_to_folder(respawn_const, game_path)
            nurse_health = validate_nurse_script(game_path, respawn_folder)
            if nurse_health and not nurse_health["script_ok"]:
                nurse_issues.append({
                    "id": loc.get("id", ""),
                    "respawn_folder": respawn_folder,
                    "script": nurse_health.get("script", ""),
                    "fixable": nurse_health.get("fixable", False),
                })
    except ImportError:
        pass

    all_ok = len(drift) == 0 and len(missing) == 0 and len(nurse_issues) == 0
    return ok_response({
        "drift": drift,
        "missing": missing,
        "nurse_issues": nurse_issues,
        "all_ok": all_ok,
    })


# ---------------------------------------------------------------------------
# POST /api/heals/fix-drift — auto-fix all drifted coordinates
# ---------------------------------------------------------------------------

@api_route("POST", "/api/heals/fix-drift")
def handle_heals_fix_drift(handler, match, query_params):
    """Auto-fix all drifted heal location coordinates."""
    game_path = handler.server.game_path

    clear_project_cache()
    locations = load_heal_locations(game_path)
    if locations is None:
        return error_response("heal_locations.json not found or invalid", 404)

    drift = _scan_drift(game_path, locations)
    if not drift:
        return ok_response({"fixed": 0})

    count = _apply_drift_fixes(game_path, drift, locations)
    return ok_response({"fixed": count})


# ---------------------------------------------------------------------------
# POST /api/heals/auto-add — auto-add heal locations for missing maps
# ---------------------------------------------------------------------------

@api_route("POST", "/api/heals/auto-add")
def handle_heals_auto_add(handler, match, query_params):
    """Auto-add heal locations for specified map folders."""
    game_path = handler.server.game_path
    body = _read_json_body(handler)
    if not body:
        return error_response("JSON body required")

    folders = body.get("folders", [])
    if not isinstance(folders, list) or not folders:
        return error_response("'folders' must be a non-empty list")

    clear_project_cache()
    locations = load_heal_locations(game_path)
    if locations is None:
        return error_response("heal_locations.json not found or invalid", 404)

    existing_ids = {loc.get("id") for loc in locations}
    added = []
    failed = []

    for folder in folders:
        if not isinstance(folder, str):
            failed.append(str(folder))
            continue
        entry = _auto_add_heal(game_path, folder)
        if entry is None:
            failed.append(folder)
            continue
        if entry["id"] in existing_ids:
            failed.append(folder)
            continue
        locations.append(entry)
        existing_ids.add(entry["id"])
        added.append(entry["id"])

    if added:
        if not write_heal_locations(game_path, locations):
            return error_response("Failed to write heal_locations.json", 500)

    return ok_response({"added": added, "failed": failed})


# ---------------------------------------------------------------------------
# POST /api/heals/fix-nurse — auto-fix broken nurse scripts
# ---------------------------------------------------------------------------

@api_route("POST", "/api/heals/fix-nurse")
def handle_heals_fix_nurse(handler, match, query_params):
    """Auto-fix broken nurse scripts in specified respawn maps."""
    game_path = handler.server.game_path
    body = _read_json_body(handler)
    if not body:
        return error_response("JSON body required")

    folders = body.get("folders", [])
    if not isinstance(folders, list) or not folders:
        return error_response("'folders' must be a non-empty list")

    try:
        from torch.npc_editor import fix_nurse_script
    except ImportError:
        return error_response("NPC editor not available", 500)

    fixed = []
    failed = []
    for folder in folders:
        if not isinstance(folder, str):
            failed.append(str(folder))
            continue
        if fix_nurse_script(game_path, folder):
            fixed.append(folder)
        else:
            failed.append(folder)

    return ok_response({"fixed": fixed, "failed": failed})
