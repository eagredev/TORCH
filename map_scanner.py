"""Map scanner — auto-discover and import game maps."""
# TORCH_MODULE: Map Scanner
# TORCH_GROUP: Tools
import os

from torch.config import SETTINGS_DEFAULTS
from torch.project_files import (
    classify_maps, load_map_json, get_encounters_for_map,
    get_encounter_types, folder_to_map_const, build_trainer_map_index,
    load_heal_locations,
)
from torch.ui import print_logo, clear_screen
from torch.sync import sync_map


# Workspace sub-folders that are not map directories
_SKIP_WORKSPACE_DIRS = {"backups", "config", "output", "_unassigned"}


def _read_map_metadata(game_path, map_name):
    """Read metadata for a single map from its map.json and encounter data.

    Returns dict with:
      npc_count:        int -- total object_events on the map
      npc_names:        list[str] -- human-readable NPC names (grouped dupes)
      trainer_count:    int -- trainerbattle calls found in map scripts
      trainer_consts:   list[str] -- raw TRAINER_* constants for this map
      encounter_detail: dict -- e.g. {"Land": 12, "Water": 5, "Fishing": 10}
      encounter_types:  list[str] -- type labels present (e.g. ["Land", "Water"])
      heal_count:       int -- heal locations on this map
    """
    result = {
        "npc_count": 0,
        "npc_names": [],
        "trainer_count": 0,
        "trainer_consts": [],
        "encounter_detail": {},
        "encounter_types": [],
        "heal_count": 0,
    }

    # --- NPCs from map.json ---
    data = load_map_json(game_path, map_name)
    if data:
        objects = data.get("object_events", [])
        if isinstance(objects, list):
            result["npc_count"] = len(objects)
            # Build human-readable NPC names with duplicate grouping
            name_counts = {}
            for obj in objects:
                gfx = obj.get("graphics_id", "") if isinstance(obj, dict) else ""
                if gfx.startswith("OBJ_EVENT_GFX_"):
                    raw = gfx[len("OBJ_EVENT_GFX_"):]
                else:
                    raw = gfx
                name = raw.replace("_", " ").title() if raw else "Unknown"
                name_counts[name] = name_counts.get(name, 0) + 1
            npc_names = []
            for name, count in name_counts.items():
                if count > 1:
                    npc_names.append(f"{name} x{count}")
                else:
                    npc_names.append(name)
            result["npc_names"] = npc_names

    # --- Trainers from script scanning ---
    map_trainers, _ = build_trainer_map_index(game_path)
    consts = map_trainers.get(map_name, [])
    result["trainer_count"] = len(consts)
    result["trainer_consts"] = list(consts)

    # --- Encounter detail ---
    _TYPE_LABELS = {
        "land_mons": "Land",
        "water_mons": "Water",
        "rock_smash_mons": "Rock Smash",
        "fishing_mons": "Fishing",
    }
    try:
        map_const = folder_to_map_const(map_name)
        entries = get_encounters_for_map(game_path, map_const)
        for entry in entries:
            for t in get_encounter_types(entry):
                mons = entry.get(t, {}).get("mons", [])
                label = _TYPE_LABELS.get(t, t)
                # Take the max across entries (time-based may have multiple)
                if len(mons) > result["encounter_detail"].get(label, 0):
                    result["encounter_detail"][label] = len(mons)
    except Exception:
        pass  # graceful fallback -- encounter data may not exist
    result["encounter_types"] = list(result["encounter_detail"].keys())

    # --- Heal locations ---
    try:
        map_const = folder_to_map_const(map_name)
        heals = load_heal_locations(game_path)
        if heals:
            result["heal_count"] = sum(
                1 for h in heals if h.get("map") == map_const
            )
    except Exception:
        pass

    return result


def _scan_game_maps(game_path, project_dir):
    """Scan data/maps/ and the TORCH workspace; return a list of map dicts.

    Each dict has keys:
        name         — map folder name (str)
        status       — "ACTIVE", "CUSTOM", "VANILLA", or "ORPHAN"
        workspace_dir— absolute path if ACTIVE/ORPHAN, else None
        game_dir     — absolute path in data/maps/ (None for ORPHAN)
        mtime        — most recent .txt/.pory mtime (ACTIVE/ORPHAN only, else 0.0)
        torscript_count — number of .txt TorScript files in workspace dir
        script_count — number of .txt/.pory files in workspace dir
        enrolled     — True if the map is in the TORCH registry
    """
    from torch.registry import is_enrolled
    vanilla_maps, custom_maps = classify_maps(game_path)
    game_maps_dir = os.path.join(game_path, "data", "maps")

    # --- Step 1: index workspace folders ---
    workspace_index = {}  # name -> (dir, mtime, script_count)
    if os.path.isdir(project_dir):
        for entry in os.scandir(project_dir):
            if not entry.is_dir():
                continue
            if entry.name in _SKIP_WORKSPACE_DIRS:
                continue
            ws_dir = entry.path
            all_scripts = [
                f for f in os.listdir(ws_dir)
                if f.endswith(".txt") or f.endswith(".pory")
            ]
            torscript_count = sum(1 for f in all_scripts if f.endswith(".txt"))
            mtime = 0.0
            for sf in all_scripts:
                try:
                    mt = os.path.getmtime(os.path.join(ws_dir, sf))
                    if mt > mtime:
                        mtime = mt
                except OSError:
                    pass
            workspace_index[entry.name] = (ws_dir, mtime, len(all_scripts), torscript_count)

    # --- Step 2: scan game maps directory ---
    results = []
    matched_workspace_names = set()

    if os.path.isdir(game_maps_dir):
        for entry in os.scandir(game_maps_dir):
            if not entry.is_dir():
                continue
            map_name = entry.name
            game_dir = entry.path

            if map_name in workspace_index:
                ws_dir, mtime, script_count, torscript_count = workspace_index[map_name]
                matched_workspace_names.add(map_name)
                results.append({
                    "name": map_name,
                    "status": "ACTIVE",
                    "workspace_dir": ws_dir,
                    "game_dir": game_dir,
                    "mtime": mtime,
                    "script_count": script_count,
                    "torscript_count": torscript_count,
                    "enrolled": is_enrolled(project_dir, map_name),
                })
            elif map_name in custom_maps:
                results.append({
                    "name": map_name,
                    "status": "CUSTOM",
                    "workspace_dir": None,
                    "game_dir": game_dir,
                    "mtime": 0.0,
                    "script_count": 0,
                    "enrolled": is_enrolled(project_dir, map_name),
                })
            else:
                # vanilla or unknown (groups file missing)
                results.append({
                    "name": map_name,
                    "status": "VANILLA",
                    "workspace_dir": None,
                    "game_dir": game_dir,
                    "mtime": 0.0,
                    "script_count": 0,
                    "enrolled": is_enrolled(project_dir, map_name),
                })

    # --- Step 3: orphan workspaces (not matched to any game map) ---
    for ws_name, (ws_dir, mtime, script_count, torscript_count) in workspace_index.items():
        if ws_name not in matched_workspace_names:
            results.append({
                "name": ws_name,
                "status": "ORPHAN",
                "workspace_dir": ws_dir,
                "game_dir": None,
                "mtime": mtime,
                "script_count": script_count,
                "torscript_count": torscript_count,
                "enrolled": is_enrolled(project_dir, ws_name),
            })

    return results


def _import_map(map_name, project_dir, game_path, emotes_conf, source_display,
                settings, proj_name=None):
    """Bootstrap a new map workspace by calling sync_map().

    sync_map() already handles creating the workspace directory, auto-generating
    setup.pory, migrating legacy.pory, running Map Guard, and Label Validation.
    Returns True on success, False on failure.
    """
    game_map_dir = os.path.join(game_path, "data", "maps", map_name)
    if not os.path.isdir(game_map_dir):
        print(f"\n  Map folder not found: {game_map_dir}")
        print("  Cannot import a map that doesn't exist in data/maps/.")
        return False

    clear_screen()
    print_logo(f"Importing  {map_name}", proj_name)
    print(f"  {'━' * 49}")
    print(f"  IMPORTING  {map_name}")
    print(f"  {'━' * 49}")
    print()

    max_snapshots = settings.get("max_snapshots", SETTINGS_DEFAULTS["max_snapshots"])
    ok = sync_map(map_name, project_dir, game_path, emotes_conf, source_display,
                  max_snapshots)
    if ok:
        from torch.registry import enroll_map
        if enroll_map(project_dir, map_name):
            print(f"  Enrolled in registry: {map_name}")
    return bool(ok)
