# TORCH_MODULE: Web API — Building Templates
# TORCH_GROUP: Web
"""Building template API endpoints for the TORCH web GUI.

Provides endpoints to list available templates, preview stamp operations,
and execute stamps to create PokéCenter/PokéMart interiors.
"""

import json
import os

from torch.web.api import api_route, ok_response, error_response, _read_json_body
from torch.project_files import load_map_json, load_layouts, load_map_groups


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OUTDOOR_TYPES = {
    "MAP_TYPE_TOWN", "MAP_TYPE_CITY", "MAP_TYPE_ROUTE",
    "MAP_TYPE_UNDERWATER", "MAP_TYPE_OCEAN",
}


def _scan_parent_maps(game_path):
    """Scan data/maps/ for maps suitable as building template parents."""
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
        map_type = data.get("map_type", "")
        if map_type not in _OUTDOOR_TYPES:
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
            "map_type": map_type,
            "warp_count": len(data.get("warp_events", [])),
            "width": width,
            "height": height,
        })

    return results


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", "/api/templates")
def handle_list_templates(handler, match, query_params):
    """List available building templates."""
    templates = [
        {
            "id": "pokecenter",
            "name": "PokéCenter",
            "description": (
                "Standard PokéCenter with Nurse Joy. "
                "Optional 2F with Cable Club."
            ),
            "includes": ["1F (14\u00d79)", "2F (14\u00d710, optional)"],
            "creates_heal_location": True,
        },
        {
            "id": "pokemart",
            "name": "PokéMart",
            "description": (
                "Standard PokéMart with shop clerk and default item list."
            ),
            "includes": ["Single floor (11\u00d78)"],
            "creates_heal_location": False,
        },
    ]
    return ok_response({"templates": templates})


@api_route("GET", "/api/templates/maps")
def handle_template_maps(handler, match, query_params):
    """List maps suitable as parent maps for building templates."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)
    maps = _scan_parent_maps(game_path)
    return ok_response({"maps": maps})


@api_route("GET", "/api/templates/groups")
def handle_template_groups(handler, match, query_params):
    """List map groups for the group dropdown."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)
    groups_data = load_map_groups(game_path)
    if not groups_data:
        return ok_response({"groups": []})
    return ok_response({"groups": groups_data.get("group_order", [])})


@api_route("GET", "/api/templates/preview")
def handle_template_preview(handler, match, query_params):
    """Dry-run validation for a stamp operation."""
    from urllib.parse import parse_qs, urlparse
    from torch.template_stamper import validate_stamp

    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    parsed = urlparse(handler.path)
    params = parse_qs(parsed.query)

    template = params.get("template", [""])[0]
    parent = params.get("parent", [""])[0]
    door_x_str = params.get("door_x", [""])[0]
    door_y_str = params.get("door_y", [""])[0]
    include_2f_str = params.get("include_2f", ["true"])[0]
    town_name = params.get("town_name", [""])[0] or None

    if not template or not parent:
        return error_response("Missing required params: template, parent", 400)

    try:
        door_x = int(door_x_str)
        door_y = int(door_y_str)
    except (ValueError, TypeError):
        return error_response("door_x and door_y must be integers", 400)

    include_2f = include_2f_str.lower() not in ("false", "0", "no")

    result = validate_stamp(game_path, template, parent, door_x, door_y,
                            include_2f=include_2f, town_name=town_name)
    return ok_response(result)


@api_route("POST", "/api/templates/stamp")
def handle_template_stamp(handler, match, query_params):
    """Execute a stamp operation to create a building."""
    from torch.template_stamper import stamp_pokecenter, stamp_pokemart
    from torch.project_files import clear_project_cache

    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    body = _read_json_body(handler)
    if body is None:
        return error_response("Invalid JSON body", 400)

    template = body.get("template", "")
    parent_map = body.get("parent_map", "")
    door_x = body.get("door_x")
    door_y = body.get("door_y")
    map_group = body.get("map_group") or None
    town_name = body.get("town_name") or None

    if not template or not parent_map:
        return error_response("Missing required fields: template, parent_map", 400)
    if not isinstance(door_x, int) or not isinstance(door_y, int):
        return error_response("door_x and door_y must be integers", 400)

    clear_project_cache()

    if template == "pokecenter":
        include_2f = body.get("include_2f", True)
        result = stamp_pokecenter(
            game_path, parent_map, door_x, door_y,
            include_2f=include_2f, map_group=map_group,
            town_name=town_name,
        )
    elif template == "pokemart":
        result = stamp_pokemart(
            game_path, parent_map, door_x, door_y,
            map_group=map_group, town_name=town_name,
        )
    else:
        return error_response(f"Unknown template: {template}", 400)

    return ok_response(result)
