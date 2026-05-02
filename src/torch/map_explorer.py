"""TORCH Map Explorer — browse map connectivity, find paths, detect orphans.

Builds warp + connection graphs from map.json data and provides an
interactive TUI for exploring map relationships.

Usage:
    torch explore          Map Explorer menu
    torch explore <map>    Jump to detail view for a specific map
"""
# TORCH_MODULE: Map Explorer
# TORCH_GROUP: Data

import os
import json
from collections import deque

from torch.colours import GOLD, WHITE, CYAN, GREEN, DIM, RST, RED, BAR
from torch.ui import print_logo, clear_screen, _k
from torch.config import _nav_keys
from torch.project_files import (
    load_map_json, load_map_groups, load_layouts, classify_maps,
    folder_to_map_const, clear_project_cache,
)
from torch.cleanup_scanner import map_const_to_folder, build_map_const_lookup
from torch.list_widget import (
    ListState, guard_bounds, visible_range, marker,
    handle_input, overflow_above, overflow_below, footer_hint,
)


# ============================================================
# GRAPH CONSTRUCTION
# ============================================================


def _parse_warp_events(data, map_name, const_to_name):
    """Extract warp destinations and detail from a map's JSON data.

    Returns (warp_dests: set[str], warps: list[dict]).
    """
    warps = []
    warp_dests = set()
    for event in (data.get("warp_events") or []):
        dest_const = event.get("dest_map", "")
        if not dest_const:
            continue
        folder = const_to_name.get(dest_const) or map_const_to_folder(dest_const)
        if folder and folder != map_name:
            warp_dests.add(folder)
            warps.append({
                "dest_map": folder,
                "dest_warp_id": event.get("dest_warp_id", ""),
                "x": event.get("x", 0),
                "y": event.get("y", 0),
            })
    return warp_dests, warps


def _parse_connections(data, map_name, const_to_name):
    """Extract connection destinations and detail from a map's JSON data.

    Returns (conn_dests: dict[str, str], conns: list[dict]).
    """
    conns = []
    conn_dests = {}
    for conn in (data.get("connections") or []):
        dest_const = conn.get("map", "")
        if not dest_const:
            continue
        folder = const_to_name.get(dest_const) or map_const_to_folder(dest_const)
        direction = conn.get("direction", "")
        if folder and folder != map_name:
            conn_dests[folder] = direction
            conns.append({
                "map": folder,
                "direction": direction,
                "offset": conn.get("offset", 0),
            })
    return conn_dests, conns


def _build_map_graph(game_path):
    """Build complete map connectivity graph from all maps on disk.

    Returns:
        warp_graph:  dict[str, set[str]]          — warp adjacency (undirected)
        conn_graph:  dict[str, dict[str, str]]     — connection adjacency with direction
        all_maps:    set[str]                       — all discovered map folder names
        warp_detail: dict[str, list[dict]]          — raw warp event data per map
        conn_detail: dict[str, list[dict]]          — raw connection data per map
    """
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return {}, {}, set(), {}, {}

    # Build const -> folder lookup
    group_data = load_map_groups(game_path)
    const_to_name = {}
    if group_data:
        const_to_name = build_map_const_lookup(game_path, group_data)

    # Supplement with direct map.json id -> folder name lookup.
    # build_map_const_lookup parses map_groups.h which may use enum syntax
    # that the regex doesn't match, so this catch-all ensures all maps are
    # reachable by their MAP_* constant.
    if group_data:
        for maps_list in group_data.values():
            if not isinstance(maps_list, list):
                continue
            for folder_name in maps_list:
                mj_path = os.path.join(maps_dir, folder_name, "map.json")
                if os.path.isfile(mj_path):
                    try:
                        import json as _json
                        with open(mj_path, encoding="utf-8") as _f:
                            _mdata = _json.load(_f)
                        _mid = _mdata.get("id", "")
                        if _mid and _mid not in const_to_name:
                            const_to_name[_mid] = folder_name
                    except (OSError, ValueError):
                        pass

    # Discover all map folders
    all_maps = set()
    for entry in os.listdir(maps_dir):
        map_json_path = os.path.join(maps_dir, entry, "map.json")
        if os.path.isfile(map_json_path):
            all_maps.add(entry)

    warp_graph = {}
    conn_graph = {}
    warp_detail = {}
    conn_detail = {}

    for map_name in all_maps:
        data = load_map_json(game_path, map_name)
        if not data:
            continue

        warp_dests, warps = _parse_warp_events(data, map_name, const_to_name)
        if warp_dests:
            warp_graph[map_name] = warp_dests
        if warps:
            warp_detail[map_name] = warps

        conn_dests, conns = _parse_connections(data, map_name, const_to_name)
        if conn_dests:
            conn_graph[map_name] = conn_dests
        if conns:
            conn_detail[map_name] = conns

    return warp_graph, conn_graph, all_maps, warp_detail, conn_detail


def _reverse_warp_lookup(warp_graph):
    """Build reverse warp index: dest_map -> set of source maps.

    Answers "which maps warp INTO this map?"
    """
    reverse = {}
    for src, dests in warp_graph.items():
        for dest in dests:
            reverse.setdefault(dest, set()).add(src)
    return reverse


def _merge_graph(warp_graph, conn_graph):
    """Merge warp and connection graphs into a single adjacency dict.

    Returns dict[str, set[str]] — combined undirected adjacency.
    """
    merged = {}
    for src, dests in warp_graph.items():
        merged.setdefault(src, set()).update(dests)
    for src, dests_dict in conn_graph.items():
        merged.setdefault(src, set()).update(dests_dict.keys())
    return merged


# ============================================================
# PATH FINDING
# ============================================================


def _find_path(warp_graph, conn_graph, start, end):
    """BFS shortest path from start to end across warp + connection graphs.

    Returns list of (map_name, transition_type) tuples from start to end,
    or None if no path exists.  transition_type is "start", "warp", or
    "connection <direction>".
    """
    if start == end:
        return [(start, "start")]

    merged = _merge_graph(warp_graph, conn_graph)

    visited = {start}
    parent = {}  # child -> (parent, transition_type)
    queue = deque([start])

    while queue:
        current = queue.popleft()
        for neighbour in merged.get(current, []):
            if neighbour in visited:
                continue
            visited.add(neighbour)
            # Determine transition type
            is_warp = neighbour in warp_graph.get(current, set())
            if is_warp:
                trans = "warp"
            else:
                direction = conn_graph.get(current, {}).get(neighbour, "")
                trans = f"connection {direction}" if direction else "connection"
            parent[neighbour] = (current, trans)
            if neighbour == end:
                # Reconstruct path
                path = [(end, trans)]
                node = current
                while node in parent:
                    prev, t = parent[node]
                    path.append((node, t))
                    node = prev
                path.append((node, "start"))
                path.reverse()
                return path
            queue.append(neighbour)

    return None


# ============================================================
# CONNECTIVITY ANALYSIS
# ============================================================


def _find_orphans(warp_graph, conn_graph, all_maps):
    """Find maps with no warp or connection edges at all."""
    connected = set()
    for src, dests in warp_graph.items():
        connected.add(src)
        connected.update(dests)
    for src, dests_dict in conn_graph.items():
        connected.add(src)
        connected.update(dests_dict.keys())
    return sorted(all_maps - connected)


def _find_dead_ends(warp_graph, conn_graph, all_maps):
    """Find maps with exactly 1 exit (warp or connection)."""
    # Count unique exits per map
    exits = {}
    for m in all_maps:
        dest_set = set()
        dest_set.update(warp_graph.get(m, set()))
        dest_set.update(conn_graph.get(m, {}).keys())
        exits[m] = dest_set

    return sorted(m for m, dests in exits.items() if len(dests) == 1)


def _find_islands(warp_graph, conn_graph, all_maps, start_map=None):
    """Find connected components not reachable from start_map.

    Returns list of sorted map name lists, one per disconnected island.
    """
    merged = _merge_graph(warp_graph, conn_graph)
    # Make bidirectional for reachability
    bidir = {}
    for src, dests in merged.items():
        bidir.setdefault(src, set()).update(dests)
        for d in dests:
            bidir.setdefault(d, set()).add(src)

    if start_map is None:
        # Pick first map alphabetically from all_maps
        start_map = min(all_maps) if all_maps else None

    if not start_map or start_map not in all_maps:
        return []

    # BFS from start
    visited = {start_map}
    queue = deque([start_map])
    while queue:
        current = queue.popleft()
        for nb in bidir.get(current, []):
            if nb not in visited:
                visited.add(nb)
                queue.append(nb)

    unreachable = all_maps - visited
    if not unreachable:
        return []

    # Find connected components among unreachable maps
    remaining = set(unreachable)
    islands = []
    while remaining:
        seed = min(remaining)
        component = {seed}
        q = deque([seed])
        while q:
            node = q.popleft()
            for nb in bidir.get(node, []):
                if nb in remaining and nb not in component:
                    component.add(nb)
                    q.append(nb)
        islands.append(sorted(component))
        remaining -= component

    islands.sort(key=lambda c: (-len(c), c[0]))
    return islands


def _map_groups_view(game_path):
    """Group maps by their map_groups.json region.

    Returns list of (group_name, [map_names]) sorted by group order.
    """
    group_data = load_map_groups(game_path)
    if not group_data:
        return []

    group_order = group_data.get("group_order", [])
    result = []
    for group_name in group_order:
        maps = group_data.get(group_name, [])
        if maps:
            result.append((group_name, list(maps)))
    return result


# ============================================================
# GRAPH DATA BUNDLE
# ============================================================


class GraphData:
    """Immutable bundle of all graph state for passing between views."""
    __slots__ = ("warp_graph", "conn_graph", "all_maps", "warp_detail",
                 "conn_detail", "reverse_warps", "vanilla_maps", "custom_maps")

    def __init__(self, game_path):
        wg, cg, am, wd, cd = _build_map_graph(game_path)
        self.warp_graph = wg
        self.conn_graph = cg
        self.all_maps = am
        self.warp_detail = wd
        self.conn_detail = cd
        self.reverse_warps = _reverse_warp_lookup(wg)
        try:
            v, c = classify_maps(game_path)
            self.vanilla_maps = v
            self.custom_maps = c
        except Exception:
            self.vanilla_maps = set()
            self.custom_maps = set()


# ============================================================
# FORMATTING HELPERS
# ============================================================


def _fmt_warp_summary(map_name, warp_graph):
    """Return '4 warps' style summary."""
    count = len(warp_graph.get(map_name, set()))
    return f"{count} warp{'s' if count != 1 else ''}"


def _fmt_conn_summary(map_name, conn_graph):
    """Return '2 connections (left: Route106, right: Route107)' style summary."""
    conns = conn_graph.get(map_name, {})
    if not conns:
        return "0 connections"
    count = len(conns)
    parts = []
    for dest, direction in sorted(conns.items()):
        if direction:
            parts.append(f"{direction}: {dest}")
        else:
            parts.append(dest)
    detail = ", ".join(parts[:3])
    if len(parts) > 3:
        detail += f" +{len(parts) - 3} more"
    return f"{count} connection{'s' if count != 1 else ''} ({detail})"


def _classify_label(map_name, graph_data):
    """Return coloured CUSTOM/VANILLA label for a map."""
    if map_name in graph_data.custom_maps:
        return f"{GREEN}CUSTOM{RST}"
    if map_name in graph_data.vanilla_maps:
        return f"{DIM}VANILLA{RST}"
    return ""


# ============================================================
# MAP PICKER
# ============================================================


def _pick_map(all_maps, prompt="Map name"):
    """Interactive search-pick for a map name. Returns name or None."""
    sorted_maps = sorted(all_maps)
    while True:
        query = input(f"  {prompt} (search, or 'q' to cancel): ").strip()
        if query.lower() == "q":
            return None
        if not query:
            continue
        matches = [m for m in sorted_maps if query.lower() in m.lower()]
        if not matches:
            print(f"  No maps matching '{query}'.")
            continue
        if len(matches) == 1:
            return matches[0]
        # Show matches
        show = matches[:20]
        for i, m in enumerate(show, 1):
            print(f"  {GOLD}{i:>3}{RST}  {m}")
        if len(matches) > 20:
            print(f"  {DIM}  ... {len(matches) - 20} more matches{RST}")
        pick = input("  Pick # (or new search, 'q' cancel): ").strip()
        if pick.lower() == "q":
            return None
        if pick.isdigit():
            idx = int(pick) - 1
            if 0 <= idx < len(show):
                return show[idx]
        # Treat as new search
        matches2 = [m for m in sorted_maps if pick.lower() in m.lower()]
        if len(matches2) == 1:
            return matches2[0]


# ============================================================
# TUI: BROWSE MAPS
# ============================================================


def _browse_maps(game_path, graph_data, settings, proj_name=None):
    """Scrolling list of all maps with connectivity summary."""
    nav = _nav_keys(settings)
    all_sorted = sorted(graph_data.all_maps)
    if not all_sorted:
        print("  No maps found.")
        input("  Press Enter > ")
        return

    # Filter state
    filter_mode = "all"  # all, outdoor, indoor, custom, vanilla
    filter_labels = {
        "all": "All maps",
        "outdoor": "Outdoor only (has connections)",
        "indoor": "Indoor only (warps only)",
        "custom": "Custom only",
        "vanilla": "Vanilla only",
    }
    search_query = ""

    def _apply_filters(maps):
        filtered = maps
        if filter_mode == "outdoor":
            filtered = [m for m in filtered if m in graph_data.conn_graph]
        elif filter_mode == "indoor":
            filtered = [m for m in filtered
                        if m not in graph_data.conn_graph
                        and m in graph_data.warp_graph]
        elif filter_mode == "custom":
            filtered = [m for m in filtered if m in graph_data.custom_maps]
        elif filter_mode == "vanilla":
            filtered = [m for m in filtered if m in graph_data.vanilla_maps]
        if search_query:
            filtered = [m for m in filtered
                        if search_query.lower() in m.lower()]
        return filtered

    items = _apply_filters(all_sorted)
    state = ListState(total=len(items), page_size=18)

    while True:
        items = _apply_filters(all_sorted)
        state.total = len(items)
        guard_bounds(state)

        clear_screen()
        print_logo("Map Explorer", proj_name=proj_name)
        print(BAR)
        filter_info = filter_labels.get(filter_mode, filter_mode)
        extra_info = f" | Search: '{search_query}'" if search_query else ""
        print(f"  {DIM}{filter_info}{extra_info}  "
              f"({len(items)} of {len(all_sorted)} maps){RST}")
        print()

        if not items:
            print("  No maps match current filters.")
        else:
            start, end = visible_range(state)
            above = overflow_above(state)
            if above:
                print(above)
            for i in range(start, end):
                m = items[i]
                sel = marker(state, i)
                warp_s = _fmt_warp_summary(m, graph_data.warp_graph)
                conn_s = _fmt_conn_summary(m, graph_data.conn_graph)
                name_col = f"{WHITE}{m:<30}{RST}" if len(m) <= 30 else f"{WHITE}{m}{RST}"
                print(f"  {sel} {name_col}  {DIM}{warp_s} | {conn_s}{RST}")
            below = overflow_below(state)
            if below:
                print(below)

        print()
        extra = f"  {_k('/')}search  {_k('f')}ilter"
        print(footer_hint(nav_keys=nav, extra=extra))
        raw = input(f"  {GOLD}>{RST} ").strip()

        if raw == "/":
            q = input("  Search: ").strip()
            search_query = q
            state.selected = 0
            state.scroll_top = 0
            continue

        if raw.lower() == "f":
            modes = ["all", "outdoor", "indoor", "custom", "vanilla"]
            idx = (modes.index(filter_mode) + 1) % len(modes)
            filter_mode = modes[idx]
            state.selected = 0
            state.scroll_top = 0
            continue

        action = handle_input(state, raw, nav_keys=nav)
        if action == "quit":
            return
        if action in ("open", "jump_act"):
            if items:
                _map_detail(game_path, items[state.selected], graph_data,
                            settings, proj_name)


# ============================================================
# TUI: MAP DETAIL
# ============================================================


def _print_layout_info(game_path, data):
    """Print layout, dimensions, and tileset info for a map."""
    layout_id = data.get("layout", "")
    if not layout_id:
        return
    layouts = load_layouts(game_path)
    dims = ""
    tilesets = ""
    if layouts:
        for lay in layouts.get("layouts", []):
            if lay.get("id") == layout_id:
                w = lay.get("width", "?")
                h = lay.get("height", "?")
                dims = f" ({w}x{h})"
                ts1 = lay.get("primary_tileset", "")
                ts2 = lay.get("secondary_tileset", "")
                if ts1 or ts2:
                    tilesets = f"  {DIM}Tilesets:{RST} {ts1}"
                    if ts2:
                        tilesets += f" + {ts2}"
                break
    print(f"  {DIM}Layout:{RST} {layout_id}{dims}")
    if tilesets:
        print(tilesets)


def _print_connectivity(map_name, graph_data):
    """Print warp/connection edges (in and out) for a map."""
    # Warps out
    warps_out = graph_data.warp_detail.get(map_name, [])
    print(f"  {GOLD}Warps OUT ({len(warps_out)}):{RST}")
    if warps_out:
        for w in warps_out:
            x, y = w.get("x", "?"), w.get("y", "?")
            print(f"    -> {w['dest_map']}  {DIM}(warp {w.get('dest_warp_id', '?')}, "
                  f"x:{x} y:{y}){RST}")
    else:
        print(f"    {DIM}(none){RST}")

    # Connections out
    conns_out = graph_data.conn_detail.get(map_name, [])
    print(f"  {GOLD}Connections OUT ({len(conns_out)}):{RST}")
    if conns_out:
        for c in conns_out:
            print(f"    -> {c['map']}  {DIM}({c.get('direction', '?')}){RST}")
    else:
        print(f"    {DIM}(none){RST}")

    # Reverse warps (warps IN)
    warps_in = graph_data.reverse_warps.get(map_name, set())
    print(f"  {GOLD}Warps IN ({len(warps_in)}):{RST}")
    if warps_in:
        for src in sorted(warps_in):
            print(f"    <- {src}")
    else:
        print(f"    {DIM}(none){RST}")

    # Reverse connections (connections INTO this map)
    conns_in = []
    for src, dests_dict in graph_data.conn_graph.items():
        if map_name in dests_dict:
            conns_in.append((src, dests_dict[map_name]))
    conns_in.sort()
    print(f"  {GOLD}Connections IN ({len(conns_in)}):{RST}")
    if conns_in:
        for src, direction in conns_in:
            print(f"    <- {src}  {DIM}({direction}){RST}")
    else:
        print(f"    {DIM}(none){RST}")


def _map_detail(game_path, map_name, graph_data, settings, proj_name=None):
    """Full connectivity view for a single map."""
    clear_screen()
    print_logo("Map Explorer", proj_name=proj_name)
    print(BAR)
    print(f"  {WHITE}{map_name}{RST}  {_classify_label(map_name, graph_data)}")
    print()

    data = load_map_json(game_path, map_name)
    if data:
        _print_layout_info(game_path, data)

    # Map group
    groups = load_map_groups(game_path)
    if groups:
        for group_name in groups.get("group_order", []):
            if map_name in groups.get(group_name, []):
                print(f"  {DIM}Group:{RST}  {group_name}")
                break

    print()
    _print_connectivity(map_name, graph_data)

    # NPC/trainer summary
    if data:
        npc_count = len(data.get("object_events") or [])
        warp_count = len(data.get("warp_events") or [])
        coord_count = len(data.get("coord_events") or [])
        bg_count = len(data.get("bg_events") or [])
        print()
        print(f"  {DIM}NPCs: {npc_count}  Warps: {warp_count}  "
              f"Triggers: {coord_count}  Signs: {bg_count}{RST}")

    print()
    print(f"  {_k('q')} Back")
    input(f"  {GOLD}>{RST} ")


# ============================================================
# TUI: PATH FINDER
# ============================================================


def _path_finder(game_path, graph_data, settings, proj_name=None):
    """Interactive shortest-path finder between two maps."""
    clear_screen()
    print_logo("Map Explorer — Path Finder", proj_name=proj_name)
    print(BAR)
    print()

    print(f"  {WHITE}From:{RST}")
    start = _pick_map(graph_data.all_maps, prompt="Start map")
    if not start:
        return

    print(f"  {WHITE}To:{RST}")
    end = _pick_map(graph_data.all_maps, prompt="End map")
    if not end:
        return

    print()
    path = _find_path(graph_data.warp_graph, graph_data.conn_graph, start, end)
    if not path:
        print(f"  {RED}No path found from {start} to {end}.{RST}")
        print(f"  These maps may be in disconnected regions.")
    else:
        warp_count = sum(1 for _, t in path if t == "warp")
        conn_count = sum(1 for _, t in path if t.startswith("connection"))
        steps = len(path) - 1
        print(f"  {GREEN}Path found ({steps} step{'s' if steps != 1 else ''}):{RST}")
        print()
        for i, (node, trans) in enumerate(path):
            if i == 0:
                print(f"    {GOLD}*{RST} {WHITE}{node}{RST}")
            else:
                print(f"    {DIM}({trans}){RST}")
                print(f"    {GOLD}*{RST} {WHITE}{node}{RST}")
        print()
        parts = []
        if warp_count:
            parts.append(f"{warp_count} warp{'s' if warp_count != 1 else ''}")
        if conn_count:
            parts.append(f"{conn_count} connection{'s' if conn_count != 1 else ''}")
        print(f"  {DIM}Distance: {' + '.join(parts)} = {steps} transitions{RST}")

    print()
    input(f"  Press Enter > ")


# ============================================================
# TUI: CONNECTIVITY REPORT
# ============================================================


def _connectivity_report(game_path, graph_data, settings, proj_name=None):
    """Full connectivity analysis with orphans, dead ends, and islands."""
    clear_screen()
    print_logo("Map Explorer — Connectivity Report", proj_name=proj_name)
    print(BAR)
    print()

    total = len(graph_data.all_maps)
    orphans = _find_orphans(graph_data.warp_graph, graph_data.conn_graph,
                            graph_data.all_maps)
    dead_ends = _find_dead_ends(graph_data.warp_graph, graph_data.conn_graph,
                                graph_data.all_maps)
    islands = _find_islands(graph_data.warp_graph, graph_data.conn_graph,
                            graph_data.all_maps)

    connected = total - len(orphans)
    print(f"  {WHITE}Total maps:{RST}  {total}")
    print(f"  {WHITE}Connected:{RST}   {connected} (have at least one warp or connection)")
    print(f"  {WHITE}Orphaned:{RST}    {len(orphans)} (no warps or connections)")
    print()

    if orphans:
        print(f"  {GOLD}Orphaned Maps ({len(orphans)}):{RST}")
        for m in orphans[:20]:
            label = _classify_label(m, graph_data)
            print(f"    - {m}  {label}")
        if len(orphans) > 20:
            print(f"    {DIM}... {len(orphans) - 20} more{RST}")
        print()

    if dead_ends:
        print(f"  {GOLD}Dead Ends ({len(dead_ends)}) — only 1 exit:{RST}")
        for m in dead_ends[:20]:
            # Show where it connects to
            dests = set()
            dests.update(graph_data.warp_graph.get(m, set()))
            dests.update(graph_data.conn_graph.get(m, {}).keys())
            dest_str = ", ".join(sorted(dests)) if dests else "?"
            print(f"    - {m} -> {dest_str}")
        if len(dead_ends) > 20:
            print(f"    {DIM}... {len(dead_ends) - 20} more{RST}")
        print()

    if islands:
        # Determine start map
        group_data = load_map_groups(game_path)
        start_map = None
        if group_data:
            for gn in group_data.get("group_order", []):
                maps_in_group = group_data.get(gn, [])
                if maps_in_group:
                    start_map = maps_in_group[0]
                    break
        print(f"  {GOLD}Islands ({len(islands)}) — not reachable from "
              f"{start_map or 'first map'}:{RST}")
        for i, cluster in enumerate(islands[:10]):
            preview = ", ".join(cluster[:5])
            if len(cluster) > 5:
                preview += f" +{len(cluster) - 5} more"
            print(f"    Cluster {i + 1}: [{len(cluster)} maps] {preview}")
        if len(islands) > 10:
            print(f"    {DIM}... {len(islands) - 10} more clusters{RST}")
        print()
    else:
        print(f"  {GREEN}All connected maps are reachable from the start map.{RST}")
        print()

    input(f"  Press Enter > ")


# ============================================================
# TUI: REGION VIEW
# ============================================================


def _region_view(game_path, graph_data, settings, proj_name=None):
    """Maps grouped by map_groups.json region."""
    nav = _nav_keys(settings)
    groups = _map_groups_view(game_path)
    if not groups:
        print("  No map groups found.")
        input("  Press Enter > ")
        return

    state = ListState(total=len(groups), page_size=18)

    while True:
        guard_bounds(state)
        clear_screen()
        print_logo("Map Explorer — Region View", proj_name=proj_name)
        print(BAR)
        print(f"  {DIM}{len(groups)} regions{RST}")
        print()

        start, end = visible_range(state)
        above = overflow_above(state)
        if above:
            print(above)
        for i in range(start, end):
            group_name, maps = groups[i]
            sel = marker(state, i)
            custom_count = sum(1 for m in maps if m in graph_data.custom_maps)
            label = f"{DIM}({len(maps)} maps"
            if custom_count:
                label += f", {GREEN}{custom_count} custom{DIM}"
            label += f"){RST}"
            print(f"  {sel} {WHITE}{group_name:<25}{RST}  {label}")
        below = overflow_below(state)
        if below:
            print(below)

        print()
        print(footer_hint(nav_keys=nav))
        raw = input(f"  {GOLD}>{RST} ").strip()

        action = handle_input(state, raw, nav_keys=nav)
        if action == "quit":
            return
        if action in ("open", "jump_act"):
            _region_detail(game_path, groups[state.selected], graph_data,
                           settings, proj_name)


def _region_detail(game_path, group_info, graph_data, settings, proj_name=None):
    """Show all maps within a region group."""
    group_name, maps = group_info
    nav = _nav_keys(settings)
    state = ListState(total=len(maps), page_size=18)

    while True:
        guard_bounds(state)
        clear_screen()
        print_logo("Map Explorer — Region View", proj_name=proj_name)
        print(BAR)
        print(f"  {WHITE}{group_name}{RST}  {DIM}({len(maps)} maps){RST}")
        print()

        start, end = visible_range(state)
        above = overflow_above(state)
        if above:
            print(above)
        for i in range(start, end):
            m = maps[i]
            sel = marker(state, i)
            warp_s = _fmt_warp_summary(m, graph_data.warp_graph)
            conn_s = _fmt_conn_summary(m, graph_data.conn_graph)
            print(f"  {sel} {WHITE}{m:<30}{RST}  {DIM}{warp_s} | {conn_s}{RST}")
        below = overflow_below(state)
        if below:
            print(below)

        print()
        print(footer_hint(nav_keys=nav))
        raw = input(f"  {GOLD}>{RST} ").strip()

        action = handle_input(state, raw, nav_keys=nav)
        if action == "quit":
            return
        if action in ("open", "jump_act"):
            _map_detail(game_path, maps[state.selected], graph_data,
                        settings, proj_name)


# ============================================================
# MAIN MENU
# ============================================================


def map_explorer_menu(game_path, settings, proj_name=None):
    """Map Explorer main menu — entry point from CLI and main menu."""
    # Build graph on entry
    print(f"  {DIM}Building map graph...{RST}", end="", flush=True)
    graph_data = GraphData(game_path)
    print(f"\r  {DIM}Map graph built: {len(graph_data.all_maps)} maps.{RST}")

    while True:
        clear_screen()
        print_logo("Map Explorer", proj_name=proj_name)
        print(BAR)
        print(f"  {DIM}{len(graph_data.all_maps)} maps loaded{RST}")
        print()
        print(f"  {_k('1')} {WHITE}Browse maps{RST}          "
              f"{DIM}Scrolling list with connectivity info{RST}")
        print(f"  {_k('2')} {WHITE}Find path{RST}            "
              f"{DIM}Shortest path between two maps{RST}")
        print(f"  {_k('3')} {WHITE}Map detail{RST}           "
              f"{DIM}All connections and warps for a map{RST}")
        print(f"  {_k('4')} {WHITE}Connectivity report{RST}  "
              f"{DIM}Orphans, dead ends, islands{RST}")
        print(f"  {_k('5')} {WHITE}Region view{RST}          "
              f"{DIM}Maps grouped by area/town{RST}")
        print()
        print(f"  {_k('q')} {DIM}Back{RST}")
        print()

        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if choice in ("q", ""):
            return
        if choice == "1":
            _browse_maps(game_path, graph_data, settings, proj_name)
        elif choice == "2":
            _path_finder(game_path, graph_data, settings, proj_name)
        elif choice == "3":
            clear_screen()
            print_logo("Map Explorer — Map Detail", proj_name=proj_name)
            print(BAR)
            print()
            name = _pick_map(graph_data.all_maps)
            if name:
                _map_detail(game_path, name, graph_data, settings, proj_name)
        elif choice == "4":
            _connectivity_report(game_path, graph_data, settings, proj_name)
        elif choice == "5":
            _region_view(game_path, graph_data, settings, proj_name)


# ============================================================
# CLI ENTRY POINT
# ============================================================


def explore_command(args, game_path, settings, proj_name=None):
    """CLI entry point for 'torch explore [MapName]'."""
    if args:
        # Direct map detail
        map_name = args[0]
        # Build graph
        print(f"  {DIM}Building map graph...{RST}", end="", flush=True)
        graph_data = GraphData(game_path)
        print(f"\r  {DIM}Map graph built: {len(graph_data.all_maps)} maps.{RST}")
        if map_name not in graph_data.all_maps:
            # Try fuzzy match
            matches = [m for m in graph_data.all_maps
                       if map_name.lower() in m.lower()]
            if len(matches) == 1:
                map_name = matches[0]
            elif matches:
                print(f"  Multiple matches for '{map_name}':")
                for m in matches[:10]:
                    print(f"    {m}")
                return
            else:
                print(f"  Map '{map_name}' not found.")
                return
        _map_detail(game_path, map_name, graph_data, settings, proj_name)
        return

    map_explorer_menu(game_path, settings, proj_name)
