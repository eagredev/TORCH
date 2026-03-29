# TORCH_MODULE: Chain Model
# TORCH_GROUP: Core
"""Script Chains — data model, CRUD operations, and validation.

A chain is an ordered sequence of scripts that form a continuous narrative flow.
One .chain.json file per chain stores the full sequence's state data, enabling
accurate cross-script position tracking with auto-calculated ranges and manual
overrides.

Chain files live in {workspace}/chains/{ChainName}.chain.json.
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHAIN_SCHEMA_VERSION = 1
CHAIN_DIR_NAME = "chains"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _chains_dir(workspace_dir):
    """Return the chains/ directory path, creating it on first use."""
    d = os.path.join(workspace_dir, CHAIN_DIR_NAME)
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    return d


def _chain_path(workspace_dir, name):
    """Return the .chain.json path for the given chain name."""
    return os.path.join(_chains_dir(workspace_dir), f"{name}.chain.json")


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def create_chain(workspace_dir, name, head_script, head_map):
    """Create a new chain file with the given head script.

    Returns the full chain data dict.
    """
    now = datetime.now().isoformat(timespec="seconds")
    chain_data = {
        "version": CHAIN_SCHEMA_VERSION,
        "chain": name,
        "created_at": now,
        "sequence": [
            {"script": head_script, "map": head_map},
        ],
        "cast": {},
        "anchor": {
            "actors": {},
            "player": None,
            "flags": {},
            "vars": {},
        },
        "segments": {
            head_script: {
                "position": 0,
                "map": head_map,
                "trigger": None,
                "introduces": {},
                "output": {
                    "actors": {},
                    "flags": {},
                    "vars": {},
                },
            },
        },
        "manual_overrides": {},
        "sync": {
            "synced_at": None,
            "input_hashes": {},
            "map_snapshots": {},
        },
    }
    save_chain(workspace_dir, chain_data)
    return chain_data


def load_chain(workspace_dir, name):
    """Load a chain file by name. Returns dict or None if not found."""
    path = _chain_path(workspace_dir, name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_chain(workspace_dir, chain_data):
    """Write chain data to its .chain.json file (atomic write)."""
    name = chain_data.get("chain", "")
    if not name:
        raise ValueError("Chain data missing 'chain' name field")
    path = _chain_path(workspace_dir, name)
    content = json.dumps(chain_data, indent=2, ensure_ascii=False) + "\n"
    dir_path = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def delete_chain(workspace_dir, name):
    """Delete a chain file. Returns True if deleted, False if not found."""
    path = _chain_path(workspace_dir, name)
    if os.path.isfile(path):
        os.unlink(path)
        return True
    return False


def list_chains(workspace_dir):
    """List all chains as summary dicts (name, script count, maps involved)."""
    chains_dir = os.path.join(workspace_dir, CHAIN_DIR_NAME)
    if not os.path.isdir(chains_dir):
        return []
    summaries = []
    for fname in sorted(os.listdir(chains_dir)):
        if not fname.endswith(".chain.json"):
            continue
        path = os.path.join(chains_dir, fname)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        seq = data.get("sequence", [])
        maps = list(dict.fromkeys(s.get("map", "") for s in seq))
        synced_at = (data.get("sync") or {}).get("synced_at")
        summaries.append({
            "name": data.get("chain", fname.replace(".chain.json", "")),
            "script_count": len(seq),
            "maps": maps,
            "head_script": seq[0]["script"] if seq else "",
            "head_map": seq[0]["map"] if seq else "",
            "synced_at": synced_at,
        })
    return summaries


def find_chains_for_script(workspace_dir, map_name, script_name):
    """Find all chains containing the given script on the given map.

    Returns list of dicts: {name, position, segment_count}.
    """
    chains_dir = os.path.join(workspace_dir, CHAIN_DIR_NAME)
    if not os.path.isdir(chains_dir):
        return []
    results = []
    for fname in sorted(os.listdir(chains_dir)):
        if not fname.endswith(".chain.json"):
            continue
        path = os.path.join(chains_dir, fname)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        seq = data.get("sequence", [])
        for i, entry in enumerate(seq):
            if entry.get("script") == script_name and entry.get("map") == map_name:
                results.append({
                    "name": data.get("chain", ""),
                    "position": i,
                    "segment_count": len(seq),
                })
                break
    return results


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_chain(chain_data):
    """Validate chain data structure. Returns list of error strings (empty = valid)."""
    errors = []
    if not isinstance(chain_data, dict):
        return ["Chain data must be a dict"]

    if "chain" not in chain_data:
        errors.append("Missing 'chain' name field")
    if "sequence" not in chain_data:
        errors.append("Missing 'sequence' field")
    elif not isinstance(chain_data["sequence"], list):
        errors.append("'sequence' must be a list")
    elif len(chain_data["sequence"]) == 0:
        errors.append("'sequence' must have at least one entry")
    else:
        for i, entry in enumerate(chain_data["sequence"]):
            if not isinstance(entry, dict):
                errors.append(f"sequence[{i}] must be a dict")
            elif "script" not in entry or "map" not in entry:
                errors.append(f"sequence[{i}] missing 'script' or 'map'")

    segments = chain_data.get("segments", {})
    if not isinstance(segments, dict):
        errors.append("'segments' must be a dict")
    else:
        seq = chain_data.get("sequence", [])
        seq_scripts = {e.get("script") for e in seq if isinstance(e, dict)}
        for script_name in segments:
            if script_name not in seq_scripts:
                errors.append(f"Segment '{script_name}' not in sequence")

    return errors


# ---------------------------------------------------------------------------
# Segment operations
# ---------------------------------------------------------------------------

def add_segment(chain_data, script_name, map_name, position=None):
    """Add a script as a new segment. Returns the updated chain data."""
    seq = chain_data.setdefault("sequence", [])
    segments = chain_data.setdefault("segments", {})

    # Determine position (default: append to end)
    if position is None:
        position = len(seq)
    position = max(0, min(position, len(seq)))

    # Insert into sequence
    seq.insert(position, {"script": script_name, "map": map_name})

    # Create segment entry
    segments[script_name] = {
        "position": position,
        "map": map_name,
        "trigger": None,
        "introduces": {},
        "output": {"actors": {}, "flags": {}, "vars": {}},
    }

    # Reindex positions
    _reindex_positions(chain_data)
    return chain_data


def remove_segment(chain_data, script_name):
    """Remove a script from the chain. Returns the updated chain data."""
    seq = chain_data.get("sequence", [])
    chain_data["sequence"] = [e for e in seq if e.get("script") != script_name]
    chain_data.get("segments", {}).pop(script_name, None)
    chain_data.get("manual_overrides", {}).pop(script_name, None)

    # Clean up sync hashes
    sync = chain_data.get("sync", {})
    hashes = sync.get("input_hashes", {})
    hashes.pop(script_name, None)

    _reindex_positions(chain_data)
    return chain_data


def reorder_segments(chain_data, new_order):
    """Reorder segments. new_order is a list of script names in desired order.

    Returns the updated chain data.
    """
    seq = chain_data.get("sequence", [])
    # Build lookup: script_name -> sequence entry
    by_name = {e["script"]: e for e in seq}
    new_seq = []
    for name in new_order:
        if name in by_name:
            new_seq.append(by_name[name])
    # Append any scripts not in new_order (shouldn't happen, but defensive)
    seen = set(new_order)
    for e in seq:
        if e["script"] not in seen:
            new_seq.append(e)
    chain_data["sequence"] = new_seq
    _reindex_positions(chain_data)
    return chain_data


def _reindex_positions(chain_data):
    """Update position fields in segments to match sequence order."""
    segments = chain_data.get("segments", {})
    for i, entry in enumerate(chain_data.get("sequence", [])):
        script_name = entry.get("script", "")
        if script_name in segments:
            segments[script_name]["position"] = i


# ---------------------------------------------------------------------------
# Cast operations
# ---------------------------------------------------------------------------

def update_cast(chain_data, cast_id, events_map):
    """Update or add a cast member's events mapping.

    cast_id: e.g. "buster"
    events_map: dict of {map_name: {object_event_index, graphics_id, display_name?}}

    Returns the updated chain data.
    """
    cast = chain_data.setdefault("cast", {})
    if cast_id not in cast:
        cast[cast_id] = {"display_name": cast_id, "events": {}}

    # Extract display_name if provided at top level of events_map
    if "display_name" in events_map:
        cast[cast_id]["display_name"] = events_map.pop("display_name")

    cast[cast_id]["events"].update(events_map)
    return chain_data


# ---------------------------------------------------------------------------
# Manual override operations
# ---------------------------------------------------------------------------

def set_manual_override(chain_data, segment, actor, overrides):
    """Set a manual position override for an actor in a segment.

    overrides: dict with fields to override, e.g. {"y": [62, 62], "note": "..."}
    Returns the updated chain data.
    """
    mo = chain_data.setdefault("manual_overrides", {})
    seg_overrides = mo.setdefault(segment, {})
    actors = seg_overrides.setdefault("actors", {})
    actors[actor] = overrides
    return chain_data


def clear_manual_override(chain_data, segment, actor):
    """Remove a manual override for an actor in a segment.

    Returns the updated chain data.
    """
    mo = chain_data.get("manual_overrides", {})
    seg = mo.get(segment, {})
    actors = seg.get("actors", {})
    actors.pop(actor, None)
    # Clean up empty nesting
    if not actors:
        seg.pop("actors", None)
    if not seg:
        mo.pop(segment, None)
    return chain_data


# ---------------------------------------------------------------------------
# Input hashing (for incremental sync)
# ---------------------------------------------------------------------------

def compute_input_hash(chain_data, segment_name, workspace_dir):
    """Compute a hash of a segment's inputs for change detection.

    Inputs: script source file + previous segment output (or anchor) +
    introduced actors' map.json positions.

    Returns hex digest string.
    """
    h = hashlib.sha256()

    # Find segment data and its position in the sequence
    seg = chain_data.get("segments", {}).get(segment_name)
    if not seg:
        return ""
    position = seg.get("position", 0)
    map_name = seg.get("map", "")

    # Hash the script source
    script_path = os.path.join(workspace_dir, map_name, f"{segment_name}.txt")
    if os.path.isfile(script_path):
        try:
            with open(script_path, "rb") as f:
                h.update(f.read())
        except OSError:
            pass

    # Hash previous segment's output (or anchor for head)
    if position == 0:
        anchor = chain_data.get("anchor", {})
        h.update(json.dumps(anchor, sort_keys=True).encode())
    else:
        seq = chain_data.get("sequence", [])
        if position > 0 and position <= len(seq):
            prev_script = seq[position - 1].get("script", "")
            prev_seg = chain_data.get("segments", {}).get(prev_script, {})
            prev_output = prev_seg.get("output", {})
            h.update(json.dumps(prev_output, sort_keys=True).encode())

    # Hash trigger data (affects simulation results)
    trigger = seg.get("trigger")
    if trigger:
        h.update(json.dumps(trigger, sort_keys=True).encode())

    # Hash introduced actors
    introduces = seg.get("introduces", {})
    if introduces:
        h.update(json.dumps(introduces, sort_keys=True).encode())

    return h.hexdigest()


# ---------------------------------------------------------------------------
# Auto-discovery (goto/call reference scanning)
# ---------------------------------------------------------------------------

def discover_chains(workspace_dir):
    """Scan all workspace scripts for goto/call references to build a
    dependency graph and suggest potential chains.

    Returns list of suggested chains:
    [{"head": script_name, "map": map_name, "sequence": [...]}, ...]
    """
    import re

    # Scan all .txt files across all map dirs
    script_refs = {}  # (map, script) -> [(target_map, target_script), ...]
    script_set = set()

    for entry in os.listdir(workspace_dir):
        map_dir = os.path.join(workspace_dir, entry)
        if not os.path.isdir(map_dir) or entry == CHAIN_DIR_NAME:
            continue
        for fname in os.listdir(map_dir):
            if not fname.endswith(".txt"):
                continue
            script_name = fname[:-4]
            key = (entry, script_name)
            script_set.add(key)
            fpath = os.path.join(map_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue

            refs = []
            # Match: flow goto MapName_ScriptName or flow call MapName_ScriptName
            for m in re.finditer(r'\bflow\s+(?:goto|call)\s+(\w+)', content):
                target_label = m.group(1)
                # Try to resolve MapName_ScriptName pattern
                parts = target_label.split("_", 1)
                if len(parts) == 2:
                    t_map, t_script = parts
                    refs.append((t_map, t_script))
                else:
                    # Same-map reference
                    refs.append((entry, target_label))
            if refs:
                script_refs[key] = refs

    # Build adjacency: (map, script) -> set of (map, script) targets
    edges = {}
    for src, targets in script_refs.items():
        for t_map, t_script in targets:
            if (t_map, t_script) in script_set:
                edges.setdefault(src, set()).add((t_map, t_script))

    # Find chain heads: scripts that are referenced by no one (or only by themselves)
    referenced = set()
    for targets in edges.values():
        referenced.update(targets)

    suggestions = []
    visited = set()

    for src in edges:
        if src in referenced or src in visited:
            continue
        # Walk the chain linearly
        chain_seq = []
        current = src
        while current and current not in visited:
            visited.add(current)
            chain_seq.append({"script": current[1], "map": current[0]})
            targets = edges.get(current, set())
            if len(targets) == 1:
                current = next(iter(targets))
            else:
                break  # Branching — stop here

        if len(chain_seq) >= 2:
            suggestions.append({
                "head": chain_seq[0]["script"],
                "map": chain_seq[0]["map"],
                "sequence": chain_seq,
            })

    return suggestions
