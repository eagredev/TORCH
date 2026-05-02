# TORCH_MODULE: Chain Sync Engine
# TORCH_GROUP: Core
"""Chain Sync Engine — recalculate auto positions across chain segments.

Simulates each script in sequence, propagating output positions as input to
the next segment. Handles sight triggers (multi-distance), talk-to triggers
(multi-approach), and auto triggers (single simulation). Per-segment hashing
enables incremental sync.

Cross-layer import: imports simulate_scene and load_scene_initial_state from
web/api.py. Documented as architectural debt; future: extract to shared
simulator.py.
"""

import copy
import hashlib
import json
import os
import tempfile
from datetime import datetime


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_chain(workspace_dir, game_path, chain_data, progress_callback=None):
    """Run a full sync on a chain, recalculating all auto positions.

    Args:
        workspace_dir: TORCH workspace root
        game_path: game project path
        chain_data: full chain dict (modified in place)
        progress_callback: optional fn(segment_name, index, total)

    Returns:
        dict with sync results: {ok, segments_synced, segments_skipped, warnings}
    """
    from torch.chain_model import compute_input_hash

    sequence = chain_data.get("sequence", [])
    segments = chain_data.get("segments", {})
    sync_meta = chain_data.setdefault("sync", {})
    old_hashes = sync_meta.get("input_hashes", {})
    new_hashes = {}
    warnings = []
    synced_count = 0
    skipped_count = 0

    # Detect Porymap drift first
    drift = detect_porymap_drift(workspace_dir, game_path, chain_data)
    if drift.get("drifted_maps"):
        warnings.append(f"Map positions changed since last sync: {', '.join(drift['drifted_maps'])}")

    # Always update anchor from map.json (first sync or drift detected)
    _update_anchor_from_maps(game_path, chain_data)

    prev_output = None

    for i, entry in enumerate(sequence):
        script_name = entry.get("script", "")
        map_name = entry.get("map", "")
        seg = segments.get(script_name)
        if not seg:
            continue

        if progress_callback:
            progress_callback(script_name, i, len(sequence))

        # Load and parse the script (needed for trigger detection and simulation)
        parsed = _load_and_parse_script(workspace_dir, map_name, script_name)

        # Auto-detect trigger from map.json for the head segment
        trigger_changed = False
        if i == 0 and not seg.get("trigger") and parsed:
            auto_trigger = _auto_detect_trigger(game_path, map_name, parsed, chain_data)
            if auto_trigger:
                seg["trigger"] = auto_trigger
                trigger_changed = True

        # Compute input hash for this segment
        current_hash = compute_input_hash(chain_data, script_name, workspace_dir)
        new_hashes[script_name] = current_hash

        # Check if we can skip (hash match AND all downstream also match)
        # Never skip if trigger was just auto-detected (forces resim)
        if not trigger_changed and current_hash and current_hash == old_hashes.get(script_name):
            # Only skip if this segment hasn't been invalidated by upstream changes
            if i == 0 or (sequence[i-1]["script"] in new_hashes and
                          new_hashes[sequence[i-1]["script"]] == old_hashes.get(sequence[i-1]["script"])):
                skipped_count += 1
                prev_output = seg.get("output")
                continue

        if not parsed:
            warnings.append(f"Could not parse {script_name}")
            prev_output = seg.get("output")
            continue

        # Determine initial positions for simulation
        trigger = seg.get("trigger")

        if i == 0:
            # Head script — simulate based on trigger type
            results = _simulate_head(
                game_path, map_name, parsed, trigger, workspace_dir)
        else:
            # Non-head — use previous segment's output
            results = _simulate_subsequent(
                game_path, map_name, parsed, prev_output, seg, workspace_dir)

        if not results:
            warnings.append(f"Simulation produced no results for {script_name}")
            prev_output = seg.get("output")
            continue

        # Merge results into position ranges
        output = _merge_simulation_results(results)
        seg["output"] = output
        synced_count += 1

        # Check manual overrides for staleness
        overrides = chain_data.get("manual_overrides", {}).get(script_name, {})
        if overrides:
            stale = _check_override_staleness(overrides, seg.get("output", {}))
            if stale:
                warnings.extend(stale)

        prev_output = output

    # Update sync metadata
    sync_meta["synced_at"] = datetime.now().isoformat(timespec="seconds")
    sync_meta["input_hashes"] = new_hashes
    sync_meta["map_snapshots"] = _build_map_snapshots(game_path, chain_data)

    return {
        "ok": True,
        "segments_synced": synced_count,
        "segments_skipped": skipped_count,
        "warnings": warnings,
    }


def simulate_chain_at_distance(workspace_dir, game_path, chain_data,
                               target_script, player_distance):
    """Simulate through a chain at a specific player trigger distance.

    Runs the head script with the player placed at exactly `player_distance`
    tiles from the trigger NPC, then propagates the resulting positions through
    each subsequent script until reaching `target_script`.

    Returns:
        dict with {ok, frames, cast, initial, sprite_index} or {ok: False, error}
    """
    from torch.web.api import (
        simulate_scene, load_scene_initial_state, _build_trigger_info,
        _apply_player_distance, _build_scene_sprites,
    )

    sequence = chain_data.get("sequence", [])
    segments = chain_data.get("segments", {})

    if not sequence:
        return {"ok": False, "error": "Chain has no segments"}

    # Walk the chain from head to target, simulating each step
    prev_final_actors = None

    for i, entry in enumerate(sequence):
        script_name = entry.get("script", "")
        map_name = entry.get("map", "")
        seg = segments.get(script_name)
        if not seg:
            return {"ok": False, "error": f"Missing segment: {script_name}"}

        parsed = _load_and_parse_script(workspace_dir, map_name, script_name)
        if not parsed:
            return {"ok": False, "error": f"Could not parse: {script_name}"}

        setup_moves = _load_setup_movements(workspace_dir, map_name)

        # Build initial positions for this step.
        # Always start from map.json defaults, then layer chain data on top
        # (filtered to this script's cast + player).  This ensures actors the
        # previous script didn't use still get their map positions.
        cast = parsed.get("cast", {})
        cast_aliases = set(cast.keys())
        cast_aliases.add("player")
        initial = load_scene_initial_state(game_path, map_name, parsed)

        if i == 0:
            # Head script: override player distance
            from torch.project_files import load_map_json
            map_data = load_map_json(game_path, map_name) or {}
            object_events = map_data.get("object_events", [])
            trigger_info = _build_trigger_info(
                game_path, map_name, cast, object_events)
            if trigger_info and player_distance is not None:
                _apply_player_distance(initial, trigger_info, int(player_distance))
        elif prev_final_actors:
            # Subsequent script: merge previous script's final actor positions
            chain_pos = _final_actors_to_positions(prev_final_actors, seg)
            for name, pos in chain_pos.items():
                if name in cast_aliases:
                    initial[name] = pos

        frames = simulate_scene(parsed, initial, setup_moves)

        # If this is the target script, return its results
        if script_name == target_script:
            scene_sprites = _build_scene_sprites(game_path, initial, frames)
            return {
                "ok": True,
                "frames": frames,
                "cast": parsed.get("cast", {}),
                "initial": initial,
                "sprite_index": scene_sprites,
            }

        # Extract final actor positions for the next script
        if frames:
            prev_final_actors = frames[-1].get("actors", {})
        else:
            prev_final_actors = None

    return {"ok": False, "error": f"Script {target_script} not found in chain"}


def _final_actors_to_positions(final_actors, seg):
    """Convert a simulation's final actor states to initial_positions for the
    next script in the chain.  Merges in 'introduces' from the segment."""
    positions = {}
    for name, data in final_actors.items():
        positions[name] = dict(data)
    # Add introduced actors for this segment
    for name, data in seg.get("introduces", {}).items():
        positions[name] = dict(data)
    return positions


def check_staleness(workspace_dir, game_path, chain_data):
    """Check if any segments are stale without running a full sync.

    Returns:
        dict with {stale_segments: [...], drifted_maps: [...]}
    """
    from torch.chain_model import compute_input_hash

    sequence = chain_data.get("sequence", [])
    sync_meta = chain_data.get("sync", {})
    old_hashes = sync_meta.get("input_hashes", {})

    stale = []
    for entry in sequence:
        script_name = entry["script"]
        current_hash = compute_input_hash(chain_data, script_name, workspace_dir)
        if current_hash != old_hashes.get(script_name):
            stale.append(script_name)

    drift = detect_porymap_drift(workspace_dir, game_path, chain_data)

    return {
        "stale_segments": stale,
        "drifted_maps": drift.get("drifted_maps", []),
        "is_stale": len(stale) > 0 or len(drift.get("drifted_maps", [])) > 0,
    }


def detect_porymap_drift(workspace_dir, game_path, chain_data):
    """Compare stored map_snapshots against current map.json positions.

    Returns:
        dict with {drifted_maps: [...], details: {...}}
    """
    sync_meta = chain_data.get("sync", {})
    old_snapshots = sync_meta.get("map_snapshots", {})
    drifted = []
    details = {}

    # Get unique maps from sequence
    maps = set()
    for entry in chain_data.get("sequence", []):
        maps.add(entry.get("map", ""))

    for map_name in maps:
        if not map_name:
            continue
        current = _get_map_positions(game_path, map_name)
        old = old_snapshots.get(map_name, {})
        if current != old:
            drifted.append(map_name)
            details[map_name] = {"old": old, "current": current}

    return {"drifted_maps": drifted, "details": details}


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

def _simulate_head(game_path, map_name, parsed, trigger, workspace_dir):
    """Simulate the head script across all trigger positions.

    Returns list of simulation frame-lists (one per trigger position).
    """
    from torch.web.api import simulate_scene, load_scene_initial_state

    initial = load_scene_initial_state(game_path, map_name, parsed)
    setup_moves = _load_setup_movements(workspace_dir, map_name)

    if not trigger:
        # Auto trigger: single simulation
        frames = simulate_scene(parsed, initial, setup_moves)
        return [frames]

    trigger_type = trigger.get("type", "auto")

    if trigger_type == "sight":
        # Simulate once per distance in range (sight corridor)
        sight_range = trigger.get("range", [1, 1])
        min_dist = sight_range[0] if isinstance(sight_range, list) else 1
        max_dist = sight_range[1] if isinstance(sight_range, list) else sight_range
        actor = trigger.get("actor", "")
        axis = trigger.get("axis", "horizontal")
        npc_origin = trigger.get("npc_origin", {})

        results = []
        for dist in range(min_dist, max_dist + 1):
            pos = copy.deepcopy(initial)
            # Place player at this distance from NPC
            if "player" in pos and npc_origin:
                nx = npc_origin.get("x", 0)
                ny = npc_origin.get("y", 0)
                if axis == "horizontal":
                    npc_facing = pos.get(actor, {}).get("facing", "left")
                    dx = -1 if npc_facing == "left" else 1
                    pos["player"]["x"] = nx + dx * dist
                    pos["player"]["y"] = ny
                else:
                    npc_facing = pos.get(actor, {}).get("facing", "up")
                    dy = -1 if npc_facing == "up" else 1
                    pos["player"]["x"] = nx
                    pos["player"]["y"] = ny + dy * dist
            frames = simulate_scene(parsed, pos, setup_moves)
            results.append(frames)

        # Also simulate cardinal approach positions (N/E/S/W of NPC)
        # unless excluded by user
        excluded = set(trigger.get("excluded_cardinals", []))
        if npc_origin:
            nx = npc_origin.get("x", 0)
            ny = npc_origin.get("y", 0)
            cardinal_offsets = [
                ("N", nx, ny - 1, "down"),
                ("E", nx + 1, ny, "left"),
                ("S", nx, ny + 1, "up"),
                ("W", nx - 1, ny, "right"),
            ]
            for label, cx, cy, player_facing in cardinal_offsets:
                if label in excluded:
                    continue
                pos = copy.deepcopy(initial)
                if "player" in pos:
                    pos["player"]["x"] = cx
                    pos["player"]["y"] = cy
                    pos["player"]["facing"] = player_facing
                frames = simulate_scene(parsed, pos, setup_moves)
                results.append(frames)

        return results

    elif trigger_type == "talk":
        # Simulate once per enabled approach tile
        approach_tiles = trigger.get("approach_tiles", [])
        enabled = [t for t in approach_tiles if t.get("enabled", True)]
        if not enabled:
            # Fall back to single sim
            frames = simulate_scene(parsed, initial, setup_moves)
            return [frames]

        results = []
        for tile in enabled:
            pos = copy.deepcopy(initial)
            if "player" in pos:
                pos["player"]["x"] = tile.get("x", pos["player"].get("x", 0))
                pos["player"]["y"] = tile.get("y", pos["player"].get("y", 0))
                pos["player"]["facing"] = tile.get("player_facing", "down")
            frames = simulate_scene(parsed, pos, setup_moves)
            results.append(frames)
        return results

    # Auto trigger fallback
    frames = simulate_scene(parsed, initial, setup_moves)
    return [frames]


def _simulate_subsequent(game_path, map_name, parsed, prev_output, seg, workspace_dir):
    """Simulate a non-head script using the previous segment's output.

    For efficiency with ranges: simulate at min, max, and midpoint (if range > 4).
    """
    from torch.web.api import simulate_scene

    if not prev_output:
        from torch.web.api import load_scene_initial_state
        initial = load_scene_initial_state(game_path, map_name, parsed)
        setup_moves = _load_setup_movements(workspace_dir, map_name)
        frames = simulate_scene(parsed, initial, setup_moves)
        return [frames]

    setup_moves = _load_setup_movements(workspace_dir, map_name)

    # Extract position variations from prev_output
    actors_data = prev_output.get("actors", {})
    has_ranges = any(
        isinstance(v, list) and len(v) == 2
        for actor_data in actors_data.values()
        for k, v in actor_data.items()
        if k in ("x", "y")
    )

    if not has_ranges:
        # Fixed positions — single simulation
        initial = _output_to_positions(actors_data, seg)
        frames = simulate_scene(parsed, initial, setup_moves)
        return [frames]

    # Ranges exist — simulate at min, max, and optional midpoint
    positions_list = _expand_range_positions(actors_data, seg)
    results = []
    for pos in positions_list:
        frames = simulate_scene(parsed, pos, setup_moves)
        results.append(frames)
    return results


def _output_to_positions(actors_data, seg):
    """Convert output actors dict to initial_positions format.

    Handles both fixed values and ranges (takes midpoint for ranges).
    """
    positions = {}
    introduces = seg.get("introduces", {})

    for name, data in actors_data.items():
        pos = {}
        for key, val in data.items():
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], (int, float)):
                pos[key] = round((val[0] + val[1]) / 2)
            else:
                pos[key] = val
        positions[name] = pos

    # Add introduced actors
    for name, data in introduces.items():
        positions[name] = dict(data)

    return positions


def _expand_range_positions(actors_data, seg):
    """Expand range positions into min, max, and optional midpoint sets."""
    introduces = seg.get("introduces", {})

    # Build min and max position sets
    pos_min = {}
    pos_max = {}
    pos_mid = {}
    max_range = 0

    for name, data in actors_data.items():
        pmin = {}
        pmax = {}
        pmid = {}
        for key, val in data.items():
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], (int, float)):
                pmin[key] = val[0]
                pmax[key] = val[1]
                pmid[key] = round((val[0] + val[1]) / 2)
                max_range = max(max_range, abs(val[1] - val[0]))
            else:
                pmin[key] = val
                pmax[key] = val
                pmid[key] = val
        pos_min[name] = pmin
        pos_max[name] = pmax
        pos_mid[name] = pmid

    # Add introduces to all sets
    for name, data in introduces.items():
        d = dict(data)
        pos_min[name] = d
        pos_max[name] = dict(data)
        pos_mid[name] = dict(data)

    result = [pos_min, pos_max]
    if max_range > 4:
        result.append(pos_mid)
    return result


# ---------------------------------------------------------------------------
# Result merging
# ---------------------------------------------------------------------------

def _merge_simulation_results(results_list):
    """Merge multiple simulation results into a single output with ranges.

    Each result is a list of frames. We take the final frame from each and
    compute min/max for each actor field.
    """
    if not results_list:
        return {"actors": {}, "flags": {}, "vars": {}}

    # Collect final frames
    final_frames = []
    all_flags = set()
    all_vars = {}

    for frames in results_list:
        if frames:
            final = frames[-1]
            final_frames.append(final)
            all_flags.update(final.get("flags_set", []))
            all_vars.update(final.get("vars_set", {}))

    if not final_frames:
        return {"actors": {}, "flags": {}, "vars": {}}

    # Merge actor positions
    merged_actors = {}
    all_actor_names = set()
    for frame in final_frames:
        for name in (frame.get("actors") or {}):
            all_actor_names.add(name)

    for name in all_actor_names:
        field_values = {}  # field_name -> [values across simulations]
        for frame in final_frames:
            actor = (frame.get("actors") or {}).get(name, {})
            for key, val in actor.items():
                field_values.setdefault(key, []).append(val)

        merged = {}
        for key, values in field_values.items():
            if key in ("x", "y"):
                # Numeric fields → compute range
                nums = [v for v in values if isinstance(v, (int, float))]
                if nums:
                    mn, mx = min(nums), max(nums)
                    merged[key] = [mn, mx] if mn != mx else mn
                elif values:
                    merged[key] = values[0]
            elif key == "visible":
                # Boolean — True if any simulation shows True
                merged[key] = any(values)
            elif key in ("facing", "graphics_id"):
                # String fields — take first non-empty
                merged[key] = next((v for v in values if v), values[0] if values else "")
            else:
                merged[key] = values[0] if values else None

        merged["source"] = "chain"
        merged_actors[name] = merged

    # Merge flags
    merged_flags = {f: "set" for f in sorted(all_flags)}

    return {"actors": merged_actors, "flags": merged_flags, "vars": all_vars}


# ---------------------------------------------------------------------------
# Override staleness checking
# ---------------------------------------------------------------------------

def _check_override_staleness(overrides, output):
    """Compare manual overrides against current auto values.

    Returns list of warning strings.
    """
    warnings = []
    actors_overrides = overrides.get("actors", {})
    actors_output = output.get("actors", {})

    for actor, fields in actors_overrides.items():
        auto = actors_output.get(actor, {})
        for key, manual_val in list(fields.items()):
            if key in ("note", "stale_warning"):
                continue
            auto_val = auto.get(key)
            if auto_val is not None and auto_val != manual_val:
                warnings.append(
                    f"Override for {actor}.{key} may be stale: "
                    f"manual={manual_val}, auto={auto_val}"
                )
                # Add stale_warning to the override
                fields["stale_warning"] = (
                    f"Auto value changed to {auto_val}"
                )

    return warnings


# ---------------------------------------------------------------------------
# Map helpers
# ---------------------------------------------------------------------------

def _get_map_positions(game_path, map_name):
    """Get current NPC positions from map.json as a simple dict."""
    try:
        from torch.project_files import load_map_json
    except ImportError:
        return {}

    data = load_map_json(game_path, map_name)
    if not data:
        return {}

    positions = {}
    for obj in data.get("object_events", []):
        gfx = obj.get("graphics_id", "")
        name = gfx.split("OBJ_EVENT_GFX_")[-1].lower() if "OBJ_EVENT_GFX_" in gfx else gfx
        positions[name] = {"x": obj.get("x", 0), "y": obj.get("y", 0)}

    return positions


def _build_map_snapshots(game_path, chain_data):
    """Build map_snapshots from current map.json data."""
    maps = set()
    for entry in chain_data.get("sequence", []):
        maps.add(entry.get("map", ""))
    return {m: _get_map_positions(game_path, m) for m in maps if m}


def _update_anchor_from_maps(game_path, chain_data):
    """Update chain anchor from current map.json positions.

    Scans all maps in the chain and resolves cast member positions from their
    NPC assignments. Each cast member's anchor position comes from the first
    map in the sequence where they have an NPC assignment.
    """
    seq = chain_data.get("sequence", [])
    if not seq:
        return

    cast = chain_data.get("cast", {})
    anchor = chain_data.setdefault("anchor", {"actors": {}, "player": None, "flags": {}, "vars": {}})

    try:
        from torch.project_files import load_map_json
    except ImportError:
        return

    # Collect unique maps in sequence order
    seen_maps = {}
    for entry in seq:
        map_name = entry.get("map", "")
        if map_name and map_name not in seen_maps:
            data = load_map_json(game_path, map_name)
            if data:
                seen_maps[map_name] = data.get("object_events", [])

    # Resolve each cast member's position from their first available map assignment
    for cast_id, cast_info in cast.items():
        if cast_id in anchor.get("actors", {}):
            # Already resolved — update rather than skip (in case of drift)
            pass
        events = cast_info.get("events", {})
        # Walk maps in sequence order to find first assignment
        for entry in seq:
            map_name = entry.get("map", "")
            map_event = events.get(map_name)
            if map_event and map_name in seen_maps:
                idx = map_event.get("object_event_index", 0)
                object_events = seen_maps[map_name]
                # object_event_index from the UI is 1-based (NPC #1, #2, etc.)
                oe_idx = idx - 1 if idx >= 1 else idx
                if 0 <= oe_idx < len(object_events):
                    obj = object_events[oe_idx]
                    # Determine facing from movement_type
                    facing = _facing_from_movement_type(
                        obj.get("movement_type", ""))
                    anchor["actors"][cast_id] = {
                        "x": obj.get("x", 0),
                        "y": obj.get("y", 0),
                        "facing": facing,
                        "graphics_id": obj.get("graphics_id", ""),
                        "visible": True,
                    }
                    break


def _facing_from_movement_type(movement_type):
    """Extract facing direction from Porymap movement_type string."""
    mt = (movement_type or "").upper()
    if "FACE_UP" in mt or "LOOK_UP" in mt:
        return "up"
    if "FACE_LEFT" in mt or "LOOK_LEFT" in mt:
        return "left"
    if "FACE_RIGHT" in mt or "LOOK_RIGHT" in mt:
        return "right"
    # Default to down (most common)
    return "down"


# ---------------------------------------------------------------------------
# Trigger auto-detection
# ---------------------------------------------------------------------------

def _auto_detect_trigger(game_path, map_name, parsed, chain_data):
    """Auto-detect trigger type from map.json NPC data.

    Reads the first cast NPC's object_event to determine:
    - sight trainer (trainer_sight_or_berry_tree_id > 0) → sight trigger
    - talk-to NPC (sight == 0) → talk trigger with 4 cardinal approach tiles
    - no cast → None (auto trigger)

    Returns a trigger dict or None.
    """
    cast = parsed.get("cast", {})
    if not cast:
        return None

    try:
        from torch.project_files import load_map_json
    except ImportError:
        return None

    data = load_map_json(game_path, map_name)
    if not data:
        return None

    object_events = data.get("object_events", [])
    first_alias = next(iter(cast))
    npc_id = cast[first_alias]
    idx = npc_id - 1
    if idx < 0 or idx >= len(object_events):
        return None

    obj = object_events[idx]
    nx = obj.get("x", 0)
    ny = obj.get("y", 0)
    facing = _facing_from_movement_type(obj.get("movement_type", ""))

    # Check sight range
    sight = 0
    try:
        sight = int(obj.get("trainer_sight_or_berry_tree_id", "0"))
    except (ValueError, TypeError):
        pass

    if sight > 0:
        # Sight trainer
        axis = "vertical" if facing in ("up", "down") else "horizontal"
        return {
            "type": "sight",
            "actor": first_alias,
            "range": [1, sight],
            "axis": axis,
            "npc_origin": {"x": nx, "y": ny, "facing": facing},
            "facing": facing,
        }

    # Talk-to NPC — build approach tiles (4 cardinals)
    cardinals = [
        {"x": nx,     "y": ny - 1, "player_facing": "down",  "enabled": True},
        {"x": nx + 1, "y": ny,     "player_facing": "left",  "enabled": True},
        {"x": nx,     "y": ny + 1, "player_facing": "up",    "enabled": True},
        {"x": nx - 1, "y": ny,     "player_facing": "right", "enabled": True},
    ]
    return {
        "type": "talk",
        "actor": first_alias,
        "npc_origin": {"x": nx, "y": ny, "facing": facing},
        "facing": facing,
        "approach_tiles": cardinals,
    }


# ---------------------------------------------------------------------------
# Script loading
# ---------------------------------------------------------------------------

def _load_and_parse_script(workspace_dir, map_name, script_name):
    """Load and parse a TorScript file from the workspace."""
    filepath = os.path.join(workspace_dir, map_name, f"{script_name}.txt")
    if not os.path.isfile(filepath):
        return None

    try:
        from torch.script_model import _parse_script
        return _parse_script(filepath)
    except Exception:
        return None


def _load_setup_movements(workspace_dir, map_name):
    """Load named movement blocks from setup.pory for a map.

    Returns: dict mapping label -> [command_strings]
    """
    setup_path = os.path.join(workspace_dir, map_name, "setup.pory")
    if not os.path.isfile(setup_path):
        return {}
    try:
        from torch.script_model import _parse_setup_movement_blocks
        blocks = _parse_setup_movement_blocks(setup_path)
        return {b["label"]: b["commands"] for b in blocks if b.get("label")}
    except Exception:
        return {}
