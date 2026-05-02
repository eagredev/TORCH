# TORCH_MODULE: Stamp API
# TORCH_GROUP: Web
"""Custom stamp API endpoints for the TORCH web GUI.

Provides endpoints to list, create, preview, place, and delete custom
stamps, plus helpers for source map and warp discovery.
"""

import json
import os

from torch.web.api import api_route, ok_response, error_response, _read_json_body
from torch.project_files import load_map_json, load_layouts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INDOOR_TYPES = {
    "MAP_TYPE_INDOOR", "MAP_TYPE_SECRET_BASE",
    "MAP_TYPE_UNDERGROUND",
}

# Types that could be stamp sources (anything with warps)
_STAMPABLE_TYPES = _INDOOR_TYPES | {
    "MAP_TYPE_TOWN", "MAP_TYPE_CITY", "MAP_TYPE_ROUTE",
}


def _scan_source_maps(game_path):
    """Scan data/maps/ for maps suitable as custom stamp sources.

    Returns maps that have at least one warp (needed for exit warp selection).
    Focuses on indoor/underground types but includes any map with warps.
    """
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return []

    layouts_data = load_layouts(game_path)
    results = []
    for name in sorted(os.listdir(maps_dir)):
        map_dir = os.path.join(maps_dir, name)
        if not os.path.isdir(map_dir) or name.startswith("."):
            continue
        data = load_map_json(game_path, name)
        if not data:
            continue

        warps = data.get("warp_events", [])
        objects = data.get("object_events", [])
        map_type = data.get("map_type", "")

        # Only include maps with at least one warp (for exit selection)
        if not warps:
            continue

        width = None
        height = None
        if layouts_data:
            layout_id = data.get("layout", "")
            for entry in layouts_data.get("layouts", []):
                if entry.get("id") == layout_id:
                    width = entry.get("width")
                    height = entry.get("height")
                    break

        results.append({
            "name": name,
            "type": map_type,
            "width": width,
            "height": height,
            "warp_count": len(warps),
            "object_count": len(objects),
        })

    return results


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", "/api/stamps")
def handle_list_stamps(handler, match, query_params):
    """List all custom stamps."""
    from torch.custom_stamps import list_stamps

    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    stamps = list_stamps(game_path)
    return ok_response({"stamps": stamps})


@api_route("GET", r"/api/stamps/preview")
def handle_stamp_preview(handler, match, query_params):
    """Dry-run validation for custom stamp placement."""
    from urllib.parse import parse_qs, urlparse
    from torch.custom_stamps import validate_stamp_placement

    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    parsed = urlparse(handler.path)
    params = parse_qs(parsed.query)

    stamp_id = params.get("stamp_id", [""])[0]
    parent_map = params.get("parent_map", [""])[0]
    door_x_str = params.get("door_x", [""])[0]
    door_y_str = params.get("door_y", [""])[0]
    map_name = params.get("map_name", [""])[0] or None

    if not stamp_id or not parent_map:
        return error_response(
            "Missing required params: stamp_id, parent_map", 400)

    try:
        door_x = int(door_x_str)
        door_y = int(door_y_str)
    except (ValueError, TypeError):
        return error_response("door_x and door_y must be integers", 400)

    result = validate_stamp_placement(
        game_path, stamp_id, parent_map, door_x, door_y,
        map_name_override=map_name,
    )
    return ok_response(result)


@api_route("GET", "/api/stamps/source-maps")
def handle_source_maps(handler, match, query_params):
    """List maps suitable as custom stamp sources."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    maps = _scan_source_maps(game_path)
    return ok_response({"maps": maps})


@api_route("GET", r"/api/stamps/source-map/(?P<name>[A-Za-z0-9_]+)/warps")
def handle_source_map_warps(handler, match, query_params):
    """Get warp events for a source map (for exit warp selection)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("name")
    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map '{map_name}' not found", 404)

    warps = []
    for i, warp in enumerate(data.get("warp_events", [])):
        warps.append({
            "index": i,
            "x": warp.get("x", 0),
            "y": warp.get("y", 0),
            "dest_map": warp.get("dest_map", ""),
            "dest_warp_id": warp.get("dest_warp_id", ""),
        })

    return ok_response({"warps": warps})


@api_route("GET", r"/api/stamps/(?P<stamp_id>[A-Za-z0-9_]+)")
def handle_get_stamp(handler, match, query_params):
    """Get full stamp manifest by ID."""
    from torch.custom_stamps import load_stamp

    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    stamp_id = match.group("stamp_id")
    stamp = load_stamp(game_path, stamp_id)
    if stamp is None:
        return error_response(f"Stamp '{stamp_id}' not found", 404)

    return ok_response(stamp)


@api_route("POST", "/api/stamps/create")
def handle_create_stamp(handler, match, query_params):
    """Create a custom stamp from an existing map."""
    from torch.custom_stamps import create_stamp

    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    body = _read_json_body(handler)
    if body is None:
        return error_response("Invalid JSON body", 400)

    source_map = body.get("source_map", "")
    name = body.get("name", "")
    exit_warp_indices = body.get("exit_warp_indices")

    if not source_map or not name:
        return error_response(
            "Missing required fields: source_map, name", 400)
    if not isinstance(exit_warp_indices, list):
        return error_response(
            "exit_warp_indices must be a list of integers", 400)

    include_scripts = body.get("include_scripts", False)
    description = body.get("description", "")
    tags = body.get("tags")

    try:
        manifest = create_stamp(
            game_path, source_map, name, exit_warp_indices,
            include_scripts=include_scripts,
            description=description,
            tags=tags,
        )
    except ValueError as exc:
        return error_response(str(exc), 400)

    return ok_response({"success": True, "stamp": manifest})


@api_route("POST", "/api/stamps/place")
def handle_place_stamp(handler, match, query_params):
    """Execute a custom stamp placement."""
    from torch.template_stamper import stamp_custom
    from torch.project_files import clear_project_cache

    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    body = _read_json_body(handler)
    if body is None:
        return error_response("Invalid JSON body", 400)

    stamp_id = body.get("stamp_id", "")
    parent_map = body.get("parent_map", "")
    door_x = body.get("door_x")
    door_y = body.get("door_y")

    if not stamp_id or not parent_map:
        return error_response(
            "Missing required fields: stamp_id, parent_map", 400)
    if not isinstance(door_x, int) or not isinstance(door_y, int):
        return error_response("door_x and door_y must be integers", 400)

    map_name = body.get("map_name") or None
    map_group = body.get("map_group") or None

    clear_project_cache()

    result = stamp_custom(
        game_path, stamp_id, parent_map, door_x, door_y,
        map_name=map_name, map_group=map_group,
    )

    return ok_response(result)


@api_route("DELETE", r"/api/stamps/(?P<stamp_id>[A-Za-z0-9_]+)")
def handle_delete_stamp(handler, match, query_params):
    """Delete a custom stamp."""
    from torch.custom_stamps import delete_stamp

    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    stamp_id = match.group("stamp_id")
    deleted = delete_stamp(game_path, stamp_id)
    if not deleted:
        return error_response(f"Stamp '{stamp_id}' not found", 404)

    return ok_response({"success": True})
