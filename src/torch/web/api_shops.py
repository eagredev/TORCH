# TORCH_MODULE: Web API — Shops
# TORCH_GROUP: Web
"""Shop API endpoints for the TORCH web GUI.

Provides endpoints to list maps with shops, get shop details for a map,
and save modified shop item lists.
"""

import json
import os
import re

from torch.web.api import api_route, ok_response, error_response, _read_json_body
from torch.names import _const_to_item_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_enrolled_maps(handler):
    """Return list of enrolled map names, or all maps under data/maps/."""
    server = handler.server
    project_dir = getattr(server, "project_dir", "")
    game_path = getattr(server, "game_path", "")

    enrolled = []
    if project_dir:
        try:
            from torch.registry import load_registry
            reg = load_registry(project_dir)
            enrolled = sorted(reg.get("maps", {}).keys())
        except Exception:
            pass

    if enrolled:
        return enrolled

    # Fallback: scan data/maps/ on disk
    maps_dir = os.path.join(game_path, "data", "maps")
    if os.path.isdir(maps_dir):
        return sorted(
            d for d in os.listdir(maps_dir)
            if os.path.isdir(os.path.join(maps_dir, d))
            and not d.startswith(".")
        )
    return []


def _build_shop_entry(shop, npc=None):
    """Build a shop dict for the API response."""
    items = shop.get("items", [])
    entry = {
        "label": shop.get("label", ""),
        "items": items,
        "item_names": [_const_to_item_name(c) for c in items],
        "format": shop.get("format", ""),
    }
    if npc:
        entry["npc"] = {
            "object_id": npc.get("object_id", 0),
            "x": npc.get("x", 0),
            "y": npc.get("y", 0),
            "script_label": npc.get("script_label", ""),
        }
    else:
        entry["npc"] = None
    return entry


def _get_linked_shops(game_path, map_name):
    """Detect NPCs and scripts, link them, return structured shop list."""
    from torch.shop_editor import detect_shop_npcs, find_shop_scripts, _link_shops

    npcs = detect_shop_npcs(game_path, map_name)
    scripts = find_shop_scripts(game_path, map_name)
    linked = _link_shops(npcs, scripts, game_path, map_name)

    shops = []
    seen_labels = set()
    for entry in linked:
        shop = entry.get("shop")
        if not shop:
            continue
        label = shop.get("label", "")
        if label in seen_labels:
            continue
        seen_labels.add(label)
        shops.append(_build_shop_entry(shop, entry.get("npc")))

    return shops


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", "/api/shops")
def handle_shops_list(handler, match, query_params):
    """List all maps that have shops."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_names = _get_enrolled_maps(handler)
    maps_with_shops = []

    for map_name in map_names:
        shops = _get_linked_shops(game_path, map_name)
        if shops:
            maps_with_shops.append({
                "name": map_name,
                "shops": shops,
                "shop_count": len(shops),
            })

    return ok_response({"maps": maps_with_shops})


@api_route("GET", r"/api/shops/(?P<map_name>[A-Za-z0-9_]+)")
def handle_shops_detail(handler, match, query_params):
    """Get shops for a specific map."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    map_dir = os.path.join(game_path, "data", "maps", map_name)
    if not os.path.isdir(map_dir):
        return error_response(f"Map not found: {map_name}", 404)

    shops = _get_linked_shops(game_path, map_name)
    return ok_response({
        "name": map_name,
        "shops": shops,
        "shop_count": len(shops),
    })


@api_route("POST", r"/api/shops/(?P<map_name>[A-Za-z0-9_]+)/(?P<shop_label>[A-Za-z0-9_]+)")
def handle_shops_save(handler, match, query_params):
    """Save modified shop items."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    shop_label = match.group("shop_label")

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body:
        return error_response("Request body required", 400)

    items = body.get("items")
    if not isinstance(items, list):
        return error_response("'items' must be a list", 400)

    # Validate: all items must start with ITEM_
    for item in items:
        if not isinstance(item, str) or not item.startswith("ITEM_"):
            return error_response(
                f"Invalid item constant: {item!r} (must start with ITEM_)", 400
            )

    # Find the shop by scanning the map
    from torch.shop_editor import (
        detect_shop_npcs, find_shop_scripts, _link_shops, _write_shop_changes,
    )

    npcs = detect_shop_npcs(game_path, map_name)
    scripts = find_shop_scripts(game_path, map_name)
    linked = _link_shops(npcs, scripts, game_path, map_name)

    # Find the matching shop data
    target_shop = None
    for entry in linked:
        shop = entry.get("shop")
        if shop and shop.get("label") == shop_label:
            target_shop = shop
            break

    if not target_shop:
        return error_response(f"Shop not found: {shop_label}", 404)

    ok = _write_shop_changes(game_path, target_shop, items)
    if not ok:
        return error_response("Failed to write shop changes", 500)

    return ok_response({
        "saved": True,
        "label": shop_label,
        "items": items,
        "item_names": [_const_to_item_name(c) for c in items],
    })
