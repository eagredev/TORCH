# TORCH_MODULE: Web API — Map Explorer
# TORCH_GROUP: Web
"""Map Explorer API endpoints for the TORCH web GUI.

Provides graph, detail, path-finding, region, and stats endpoints
for the interactive map connectivity explorer.  Backed by the pure
functions in map_explorer.py.

Routes are registered via the shared api_route decorator so they merge
into the global route list automatically once this module is imported.
"""

import os

from torch.web.api import api_route, ok_response, error_response
from torch.map_explorer import (
    _build_map_graph,
    _find_path,
    _find_orphans,
    _find_dead_ends,
    _find_islands,
    _map_groups_view,
    _reverse_warp_lookup,
)
from torch.project_files import load_map_json, load_layouts, load_map_groups


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_game_path(handler):
    """Extract game_path from the server, returning (path, error_response)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return None, error_response("No game path configured", 500)
    return game_path, None


# Cache the graph so it is not rebuilt on every request within one server run.
# The cache is a dict keyed by game_path.  Invalidated when data/maps/ mtime
# changes (catches map addition/deletion in Porymap).
_graph_cache = {}
_cache_time = {}   # game_path -> mtime of data/maps/ at cache time


def _get_graph(game_path):
    """Build or return cached graph data for the given game path.

    Returns (warp_graph, conn_graph, all_maps, warp_detail, conn_detail,
             orphans, dead_ends, islands).
    """
    maps_dir = os.path.join(game_path, "data", "maps")
    try:
        current_mtime = os.stat(maps_dir).st_mtime
    except OSError:
        current_mtime = 0

    if game_path in _graph_cache:
        cached_mtime = _cache_time.get(game_path, 0)
        if current_mtime <= cached_mtime:
            return _graph_cache[game_path]

    wg, cg, am, wd, cd = _build_map_graph(game_path)
    orphans = _find_orphans(wg, cg, am)
    dead_ends = _find_dead_ends(wg, cg, am)
    islands = _find_islands(wg, cg, am)

    bundle = (wg, cg, am, wd, cd, orphans, dead_ends, islands)
    _graph_cache[game_path] = bundle
    _cache_time[game_path] = current_mtime
    return bundle


def _serialize_graph(wg, cg, am, wd, cd, orphans, dead_ends, islands):
    """Serialize graph data into JSON-safe dicts/lists."""
    # Convert warp_graph (dict[str, set]) -> dict[str, list]
    warp_graph_json = {k: sorted(v) for k, v in wg.items()}
    # Convert conn_graph (dict[str, dict[str,str]]) -> already JSON-safe
    conn_graph_json = cg
    # islands is list[list[str]], already JSON-safe
    return {
        "warp_graph": warp_graph_json,
        "conn_graph": conn_graph_json,
        "all_maps": sorted(am),
        "warp_detail": wd,
        "conn_detail": cd,
        "orphans": list(orphans),
        "dead_ends": list(dead_ends),
        "islands": islands,
    }


def _classify_map(map_name, wg, cg, orphans, dead_ends, island_set):
    """Return a classification string for a map node."""
    if map_name in orphans:
        return "orphan"
    if map_name in dead_ends:
        return "dead_end"
    if map_name in island_set:
        return "island"
    return "normal"


# ---------------------------------------------------------------------------
# GET /api/explorer/graph — Full connectivity graph
# ---------------------------------------------------------------------------

@api_route("GET", "/api/explorer/graph")
def handle_explorer_graph(handler, match, query_params):
    """Return the full map connectivity graph with analysis."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    wg, cg, am, wd, cd, orphans, dead_ends, islands = _get_graph(game_path)

    # Build a flat set of all island maps for quick lookup
    island_set = set()
    for cluster in islands:
        island_set.update(cluster)

    # Build regions for grouping
    regions = _map_groups_view(game_path)
    # Map -> region lookup
    map_to_region = {}
    for group_name, maps in regions:
        for m in maps:
            map_to_region[m] = group_name

    # Build node list with classification and region
    nodes = []
    orphan_set = set(orphans)
    dead_end_set = set(dead_ends)
    for m in sorted(am):
        node = {
            "name": m,
            "type": _classify_map(m, wg, cg, orphan_set, dead_end_set, island_set),
            "region": map_to_region.get(m, ""),
            "warp_count": len(wg.get(m, set())),
            "conn_count": len(cg.get(m, {})),
        }
        nodes.append(node)

    # Build edge list
    edges = []
    seen_edges = set()
    for src, dests in wg.items():
        for dest in dests:
            key = tuple(sorted([src, dest]))
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"source": src, "target": dest, "type": "warp"})
    for src, dests_dict in cg.items():
        for dest, direction in dests_dict.items():
            # Use ordered key (src, dest) to dedup but preserve direction
            # Direction means "src's <direction> side connects to dest"
            # i.e. dest is physically <direction> of src
            key = (src, dest)
            rev_key = (dest, src)
            if key not in seen_edges and rev_key not in seen_edges:
                seen_edges.add(key)
                edges.append({
                    "source": src,
                    "target": dest,
                    "type": "connection",
                    "direction": direction,
                })

    # Region list for grouping
    region_list = [{"name": g, "maps": ms} for g, ms in regions]

    return ok_response({
        "nodes": nodes,
        "edges": edges,
        "regions": region_list,
        "stats": {
            "total": len(am),
            "connected": len(am) - len(orphans),
            "orphans": len(orphans),
            "dead_ends": len(dead_ends),
            "islands": len(islands),
            "edges": len(edges),
        },
    })


# ---------------------------------------------------------------------------
# GET /api/explorer/map/<map_name> — Single map detail
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/explorer/map/(?P<map_name>[A-Za-z0-9_]+)")
def handle_explorer_map(handler, match, query_params):
    """Return detail for a single map: warps, connections, layout."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    map_name = match.group("map_name")
    wg, cg, am, wd, cd, orphans, dead_ends, islands = _get_graph(game_path)

    if map_name not in am:
        return error_response(f"Map '{map_name}' not found", 404)

    # Layout info
    data = load_map_json(game_path, map_name)
    layout_info = {}
    if data:
        layout_id = data.get("layout", "")
        layout_info["layout_id"] = layout_id
        layouts = load_layouts(game_path)
        if layouts:
            for lay in layouts.get("layouts", []):
                if lay.get("id") == layout_id:
                    layout_info["width"] = lay.get("width", 0)
                    layout_info["height"] = lay.get("height", 0)
                    layout_info["primary_tileset"] = lay.get("primary_tileset", "")
                    layout_info["secondary_tileset"] = lay.get("secondary_tileset", "")
                    break

        layout_info["npc_count"] = len(data.get("object_events") or [])
        layout_info["warp_event_count"] = len(data.get("warp_events") or [])
        layout_info["trigger_count"] = len(data.get("coord_events") or [])
        layout_info["sign_count"] = len(data.get("bg_events") or [])

    # Region
    region = ""
    groups = load_map_groups(game_path)
    if groups:
        for group_name in groups.get("group_order", []):
            if map_name in groups.get(group_name, []):
                region = group_name
                break

    # Classification
    island_set = set()
    for cluster in islands:
        island_set.update(cluster)
    classification = _classify_map(
        map_name, wg, cg, set(orphans), set(dead_ends), island_set
    )

    # Reverse warps (maps that warp INTO this map)
    reverse = _reverse_warp_lookup(wg)
    warps_in = sorted(reverse.get(map_name, set()))

    # Connections in (maps with connections TO this map)
    conns_in = []
    for src, dests_dict in cg.items():
        if map_name in dests_dict:
            conns_in.append({"map": src, "direction": dests_dict[map_name]})
    conns_in.sort(key=lambda c: c["map"])

    return ok_response({
        "name": map_name,
        "type": classification,
        "region": region,
        "layout": layout_info,
        "warps_out": wd.get(map_name, []),
        "warps_in": warps_in,
        "connections_out": cd.get(map_name, []),
        "connections_in": conns_in,
    })


# ---------------------------------------------------------------------------
# GET /api/explorer/path?from=X&to=Y — Shortest path
# ---------------------------------------------------------------------------

@api_route("GET", "/api/explorer/path")
def handle_explorer_path(handler, match, query_params):
    """Return the shortest path between two maps."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    from_map = (query_params.get("from", [""])[0] or "").strip()
    to_map = (query_params.get("to", [""])[0] or "").strip()

    if not from_map or not to_map:
        return error_response("Both 'from' and 'to' query params required", 400)

    wg, cg, am, wd, cd, orphans, dead_ends, islands = _get_graph(game_path)

    if from_map not in am:
        return error_response(f"Map '{from_map}' not found", 404)
    if to_map not in am:
        return error_response(f"Map '{to_map}' not found", 404)

    path = _find_path(wg, cg, from_map, to_map)
    if path is None:
        return ok_response({
            "found": False,
            "from": from_map,
            "to": to_map,
            "path": [],
            "hops": 0,
        })

    steps = [{"map": node, "transition": trans} for node, trans in path]
    return ok_response({
        "found": True,
        "from": from_map,
        "to": to_map,
        "path": steps,
        "hops": len(path) - 1,
    })


# ---------------------------------------------------------------------------
# GET /api/explorer/regions — Map groups / regions
# ---------------------------------------------------------------------------

@api_route("GET", "/api/explorer/regions")
def handle_explorer_regions(handler, match, query_params):
    """Return map groups (regions) with their maps."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    regions = _map_groups_view(game_path)
    result = []
    for group_name, maps in regions:
        result.append({
            "name": group_name,
            "maps": maps,
            "count": len(maps),
        })

    return ok_response({"regions": result})


# ---------------------------------------------------------------------------
# GET /api/explorer/stats — Summary statistics
# ---------------------------------------------------------------------------

@api_route("GET", "/api/explorer/stats")
def handle_explorer_stats(handler, match, query_params):
    """Return summary connectivity statistics."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    wg, cg, am, wd, cd, orphans, dead_ends, islands = _get_graph(game_path)

    # Count total edges
    edge_count = 0
    seen = set()
    for src, dests in wg.items():
        for dest in dests:
            key = tuple(sorted([src, dest]))
            if key not in seen:
                seen.add(key)
                edge_count += 1
    for src, dests_dict in cg.items():
        for dest in dests_dict:
            key = tuple(sorted([src, dest]))
            if key not in seen:
                seen.add(key)
                edge_count += 1

    return ok_response({
        "total_maps": len(am),
        "connected": len(am) - len(orphans),
        "orphans": len(orphans),
        "dead_ends": len(dead_ends),
        "islands": len(islands),
        "edges": edge_count,
        "warp_edges": sum(len(v) for v in wg.values()),
        "connection_edges": sum(len(v) for v in cg.values()),
    })
