"""Tests for map_explorer.py — graph construction, path finding, connectivity analysis."""
import os
import json
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _assert
from torch.project_files import clear_project_cache


def _make_game(tmpdir, maps_config):
    """Create a minimal game directory with map.json files.

    maps_config: dict of map_name -> {
        "warp_events": [...],
        "connections": [...],
        "object_events": [...],  (optional)
    }

    Returns game_path.
    """
    game_path = os.path.join(tmpdir, "game")
    maps_dir = os.path.join(game_path, "data", "maps")
    os.makedirs(maps_dir, exist_ok=True)

    # Build map_groups.json
    group_order = ["TestGroup"]
    groups = {"group_order": group_order, "TestGroup": list(maps_config.keys())}
    with open(os.path.join(maps_dir, "map_groups.json"), "w") as f:
        json.dump(groups, f)

    # Write each map's map.json
    for map_name, data in maps_config.items():
        map_dir = os.path.join(maps_dir, map_name)
        os.makedirs(map_dir, exist_ok=True)
        map_data = dict(data)
        map_data.setdefault("id", f"MAP_{map_name.upper()}")
        map_data.setdefault("name", map_name)
        with open(os.path.join(map_dir, "map.json"), "w") as f:
            json.dump(map_data, f)

    return game_path


def run_suite():
    _begin_suite("Map Explorer (graph construction)")

    from torch.map_explorer import (
        _build_map_graph, _reverse_warp_lookup, _merge_graph,
        _find_path, _find_orphans, _find_dead_ends, _find_islands,
        _map_groups_view,
    )

    # ── 1. Warp graph construction ──────────────────────────────

    tmpdir = tempfile.mkdtemp(prefix="torch_test_explore_")
    try:
        clear_project_cache()
        # Use folder names that match what map_const_to_folder produces:
        # MAP_TOWNA -> Towna, MAP_TOWNA_HOUSE1 -> TownaHouse1
        # So use folder names Towna and TownaHouse1
        game_path = _make_game(tmpdir, {
            "Towna": {
                "warp_events": [
                    {"dest_map": "MAP_TOWNA_HOUSE1", "dest_warp_id": "0",
                     "x": 5, "y": 10},
                ],
                "connections": [],
            },
            "TownaHouse1": {
                "warp_events": [
                    {"dest_map": "MAP_TOWNA", "dest_warp_id": "0",
                     "x": 3, "y": 7},
                ],
                "connections": [],
            },
        })

        wg, cg, am, wd, cd = _build_map_graph(game_path)

        _assert("warp graph has Towna -> TownaHouse1",
                "TownaHouse1" in wg.get("Towna", set()),
                f"warp_graph Towna = {wg.get('Towna')}")

        _assert("all maps discovered",
                len(am) == 2,
                f"expected 2 maps, got {len(am)}: {am}")

        _assert("warp detail has coordinate info",
                len(wd) > 0,
                f"warp_detail is empty")

    finally:
        clear_project_cache()
        shutil.rmtree(tmpdir)

    # ── 2. Connection graph with direction ──────────────────────

    _begin_suite("Map Explorer (connection graph)")

    tmpdir = tempfile.mkdtemp(prefix="torch_test_explore_conn_")
    try:
        clear_project_cache()
        game_path = _make_game(tmpdir, {
            "Route101": {
                "warp_events": [],
                "connections": [
                    {"map": "MAP_ROUTE102", "direction": "right", "offset": 0},
                    {"map": "MAP_OLDALE_TOWN", "direction": "left", "offset": 0},
                ],
            },
            "Route102": {
                "warp_events": [],
                "connections": [
                    {"map": "MAP_ROUTE101", "direction": "left", "offset": 0},
                ],
            },
            "OldaleTown": {
                "warp_events": [],
                "connections": [
                    {"map": "MAP_ROUTE101", "direction": "right", "offset": 0},
                ],
            },
        })

        wg, cg, am, wd, cd = _build_map_graph(game_path)

        _assert("connection graph Route101 has 2 connections",
                len(cg.get("Route101", {})) == 2,
                f"got {cg.get('Route101')}")

        _assert("connection preserves direction (right)",
                cg.get("Route101", {}).get("Route102") == "right",
                f"got direction={cg.get('Route101', {}).get('Route102')}")

        _assert("connection preserves direction (left)",
                cg.get("Route101", {}).get("OldaleTown") == "left",
                f"got {cg.get('Route101', {}).get('OldaleTown')}")

    finally:
        clear_project_cache()
        shutil.rmtree(tmpdir)

    # ── 3. Reverse warp lookup ──────────────────────────────────

    _begin_suite("Map Explorer (reverse warp lookup)")

    test_warp_graph = {
        "TownA": {"House1", "House2"},
        "House1": {"TownA"},
        "House2": {"TownA"},
    }
    reverse = _reverse_warp_lookup(test_warp_graph)

    _assert("reverse: TownA has warps from House1 and House2",
            reverse.get("TownA") == {"House1", "House2"},
            f"got {reverse.get('TownA')}")

    _assert("reverse: House1 has warp from TownA",
            reverse.get("House1") == {"TownA"},
            f"got {reverse.get('House1')}")

    _assert("reverse: House2 has warp from TownA",
            reverse.get("House2") == {"TownA"},
            f"got {reverse.get('House2')}")

    # ── 4. Merge graph ─────────────────────────────────────────

    _begin_suite("Map Explorer (merge graph)")

    test_conn_graph = {"Route1": {"Route2": "right"}}
    merged = _merge_graph(test_warp_graph, test_conn_graph)

    _assert("merged has warp entries",
            "House1" in merged.get("TownA", set()),
            f"got {merged.get('TownA')}")

    _assert("merged has connection entries",
            "Route2" in merged.get("Route1", set()),
            f"got {merged.get('Route1')}")

    # ── 5. Path finding — direct warp ──────────────────────────

    _begin_suite("Map Explorer (path finding)")

    path = _find_path(test_warp_graph, {}, "TownA", "House1")
    _assert("direct warp path found",
            path is not None,
            "path is None")
    _assert("direct warp path length is 2 (start + 1 step)",
            len(path) == 2,
            f"path length = {len(path)}: {path}")
    _assert("direct warp path starts at TownA",
            path[0][0] == "TownA" and path[0][1] == "start",
            f"got {path[0]}")
    _assert("direct warp path ends at House1 via warp",
            path[1][0] == "House1" and path[1][1] == "warp",
            f"got {path[1]}")

    # ── 6. Path finding — multi-hop ────────────────────────────

    multi_warp = {
        "A": {"B"},
        "B": {"C"},
        "C": {"D"},
    }
    path = _find_path(multi_warp, {}, "A", "D")
    _assert("multi-hop path found",
            path is not None,
            "path is None")
    _assert("multi-hop path length is 4 (A->B->C->D)",
            len(path) == 4,
            f"path length = {len(path)}: {[p[0] for p in path]}")

    # ── 7. Path finding — mixed warp+connection ────────────────

    # One-directional: IndoorMap has no outgoing edges, so no path
    mixed_warp_1dir = {"Town": {"IndoorMap"}}
    mixed_conn_1dir = {"Town": {"Route1": "right"}}
    path = _find_path(mixed_warp_1dir, mixed_conn_1dir, "IndoorMap", "Route1")
    _assert("no path when source has no outgoing edges",
            path is None,
            f"expected None, got {path}")

    # Bidirectional warps: IndoorMap -> Town -> Route1
    mixed_warp2 = {"Town": {"IndoorMap"}, "IndoorMap": {"Town"}}
    mixed_conn2 = {"Town": {"Route1": "right"}}
    path = _find_path(mixed_warp2, mixed_conn2, "IndoorMap", "Route1")
    _assert("mixed warp+conn path found (bidirectional warps)",
            path is not None,
            "path is None")
    _assert("mixed path goes through Town",
            len(path) == 3,
            f"path length = {len(path)}: {[p[0] for p in path]}")

    # ── 8. Path finding — no path ──────────────────────────────

    island_warp = {"A": {"B"}, "C": {"D"}}
    path = _find_path(island_warp, {}, "A", "D")
    _assert("no path between disconnected maps returns None",
            path is None,
            f"got {path}")

    # ── 9. Path finding — same start and end ───────────────────

    path = _find_path(test_warp_graph, {}, "TownA", "TownA")
    _assert("same start/end returns single-node path",
            path is not None and len(path) == 1 and path[0][0] == "TownA",
            f"got {path}")

    # ── 10. Find orphans ───────────────────────────────────────

    _begin_suite("Map Explorer (connectivity analysis)")

    all_maps = {"TownA", "House1", "House2", "Isolated1", "Isolated2"}
    orphans = _find_orphans(test_warp_graph, {}, all_maps)
    _assert("orphans detected",
            "Isolated1" in orphans and "Isolated2" in orphans,
            f"got {orphans}")
    _assert("connected maps not in orphans",
            "TownA" not in orphans and "House1" not in orphans,
            f"got {orphans}")

    # ── 11. Find dead ends ─────────────────────────────────────

    dead_end_warp = {
        "Town": {"House1", "House2"},
        "House1": {"Town"},
        "House2": {"Town"},
    }
    dead_ends = _find_dead_ends(dead_end_warp, {}, {"Town", "House1", "House2"})
    _assert("House1 is a dead end (1 exit)",
            "House1" in dead_ends,
            f"got {dead_ends}")
    _assert("House2 is a dead end (1 exit)",
            "House2" in dead_ends,
            f"got {dead_ends}")
    _assert("Town is NOT a dead end (2 exits)",
            "Town" not in dead_ends,
            f"got {dead_ends}")

    # ── 12. Find islands ───────────────────────────────────────

    island_warp2 = {
        "Main1": {"Main2"},
        "Main2": {"Main1"},
        "IslandA": {"IslandB"},
        "IslandB": {"IslandA"},
    }
    all_maps2 = {"Main1", "Main2", "IslandA", "IslandB"}
    islands = _find_islands(island_warp2, {}, all_maps2, start_map="Main1")
    _assert("one island cluster found",
            len(islands) == 1,
            f"got {len(islands)} islands: {islands}")
    _assert("island contains IslandA and IslandB",
            set(islands[0]) == {"IslandA", "IslandB"},
            f"got {islands[0]}")

    # ── 13. Find islands — all reachable ───────────────────────

    connected_warp = {
        "A": {"B"},
        "B": {"A", "C"},
        "C": {"B"},
    }
    islands = _find_islands(connected_warp, {}, {"A", "B", "C"}, start_map="A")
    _assert("no islands when all reachable",
            len(islands) == 0,
            f"got {len(islands)} islands: {islands}")

    # ── 14. Map groups view ────────────────────────────────────

    _begin_suite("Map Explorer (map groups)")

    tmpdir = tempfile.mkdtemp(prefix="torch_test_explore_groups_")
    try:
        clear_project_cache()
        game_path = os.path.join(tmpdir, "game")
        maps_dir = os.path.join(game_path, "data", "maps")
        os.makedirs(maps_dir, exist_ok=True)

        groups = {
            "group_order": ["Petalburg", "Dewford"],
            "Petalburg": ["PetalburgCity", "PetalburgCity_Gym"],
            "Dewford": ["DewfordTown"],
        }
        with open(os.path.join(maps_dir, "map_groups.json"), "w") as f:
            json.dump(groups, f)

        result = _map_groups_view(game_path)
        _assert("map groups returns 2 groups",
                len(result) == 2,
                f"got {len(result)}")
        _assert("first group is Petalburg with 2 maps",
                result[0][0] == "Petalburg" and len(result[0][1]) == 2,
                f"got {result[0]}")
        _assert("second group is Dewford with 1 map",
                result[1][0] == "Dewford" and len(result[1][1]) == 1,
                f"got {result[1]}")

    finally:
        clear_project_cache()
        shutil.rmtree(tmpdir)

    # ── 15. Empty game path ────────────────────────────────────

    _begin_suite("Map Explorer (edge cases)")

    tmpdir = tempfile.mkdtemp(prefix="torch_test_explore_empty_")
    try:
        clear_project_cache()
        empty_game = os.path.join(tmpdir, "empty_game")
        os.makedirs(empty_game)

        wg, cg, am, wd, cd = _build_map_graph(empty_game)
        _assert("empty game returns empty graph",
                len(am) == 0 and len(wg) == 0 and len(cg) == 0,
                f"got {len(am)} maps, {len(wg)} warps, {len(cg)} conns")

    finally:
        clear_project_cache()
        shutil.rmtree(tmpdir)

    # ── 16. Orphans with empty graph ───────────────────────────

    orphans = _find_orphans({}, {}, {"A", "B"})
    _assert("all maps are orphans with empty graph",
            set(orphans) == {"A", "B"},
            f"got {orphans}")

    # ── 17. Dead ends with no maps ─────────────────────────────

    dead_ends = _find_dead_ends({}, {}, set())
    _assert("no dead ends with empty map set",
            dead_ends == [],
            f"got {dead_ends}")

    # ── 18. Islands with empty map set ─────────────────────────

    islands = _find_islands({}, {}, set())
    _assert("no islands with empty map set",
            islands == [],
            f"got {islands}")
