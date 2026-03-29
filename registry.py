"""Map Registry — persistent enrollment and health tracking for TORCH-managed maps."""
# TORCH_MODULE: Map Registry
# TORCH_GROUP: Core
import os
import json
from datetime import datetime


REGISTRY_FILENAME = ".torch_registry.json"
REGISTRY_VERSION = 1


def _registry_path(project_dir):
    """Return the absolute path to the registry file."""
    return os.path.join(project_dir, REGISTRY_FILENAME)


def load_registry(project_dir):
    """Load the registry from disk.  Returns a dict with 'version' and 'maps' keys.

    Gracefully degrades: returns an empty registry on missing/corrupt files.
    """
    path = _registry_path(project_dir)
    if not os.path.exists(path):
        return {"version": REGISTRY_VERSION, "maps": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "maps" not in data:
            return {"version": REGISTRY_VERSION, "maps": {}}
        return data
    except (json.JSONDecodeError, OSError):
        return {"version": REGISTRY_VERSION, "maps": {}}


def save_registry(project_dir, registry):
    """Write the registry to disk."""
    path = _registry_path(project_dir)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)
    except OSError as e:
        print(f"  WARNING: Could not save registry: {e}")


def enroll_map(project_dir, map_name):
    """Add a map to the registry.  Returns True if newly enrolled, False if already present."""
    registry = load_registry(project_dir)
    if map_name in registry["maps"]:
        return False
    registry["maps"][map_name] = {
        "enrolled_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "last_written": None,
    }
    save_registry(project_dir, registry)
    return True


def unenroll_map(project_dir, map_name):
    """Remove a map from the registry.  Returns True if removed, False if not found."""
    registry = load_registry(project_dir)
    if map_name not in registry["maps"]:
        return False
    del registry["maps"][map_name]
    save_registry(project_dir, registry)
    return True


def update_last_written(project_dir, map_name):
    """Stamp the current time as last_written for a map.

    Auto-enrolls if the map is not in the registry (defensive — never lose tracking).
    """
    registry = load_registry(project_dir)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    if map_name not in registry["maps"]:
        registry["maps"][map_name] = {
            "enrolled_at": now,
            "last_written": now,
        }
    else:
        registry["maps"][map_name]["last_written"] = now
    save_registry(project_dir, registry)


def get_enrolled_maps(project_dir):
    """Return a sorted list of enrolled map names."""
    registry = load_registry(project_dir)
    return sorted(registry["maps"].keys())


def is_enrolled(project_dir, map_name):
    """Return True if the map is enrolled."""
    registry = load_registry(project_dir)
    return map_name in registry["maps"]


def get_map_health(project_dir, map_name, game_path):
    """Compute the health status of an enrolled map.

    Returns one of:
        "ok"                — workspace and game file in sync
        "stale"             — workspace files newer than last write
        "drift"             — game's scripts.pory newer than last write
        "orphan"            — enrolled but game folder missing
        "missing_workspace" — enrolled but workspace folder missing
        "never_written"     — enrolled but never synced
    """
    registry = load_registry(project_dir)
    entry = registry["maps"].get(map_name)
    if not entry:
        return "never_written"

    ws_dir = os.path.join(project_dir, map_name)
    game_map_dir = os.path.join(game_path, "data", "maps", map_name)

    if not os.path.isdir(ws_dir):
        return "missing_workspace"

    if not os.path.isdir(game_map_dir):
        return "orphan"

    last_written = entry.get("last_written")
    if not last_written:
        return "never_written"

    # Parse last_written timestamp
    try:
        lw_time = datetime.strptime(last_written, "%Y-%m-%dT%H:%M:%S").timestamp()
    except ValueError:
        return "never_written"

    # Check workspace mtime — newest .txt or .pory file
    ws_mtime = 0.0
    for fname in os.listdir(ws_dir):
        if fname.endswith(".txt") or fname.endswith(".pory"):
            try:
                mt = os.path.getmtime(os.path.join(ws_dir, fname))
                if mt > ws_mtime:
                    ws_mtime = mt
            except OSError:
                pass

    # Check game file mtimes (scripts.pory AND map.json)
    # Porymap edits (repositioning events, adding NPCs) modify map.json,
    # not scripts.pory — we need to check both for drift detection.
    game_mtime = 0.0
    for game_file in ("scripts.pory", "map.json"):
        gf = os.path.join(game_map_dir, game_file)
        if os.path.exists(gf):
            try:
                mt = os.path.getmtime(gf)
                if mt > game_mtime:
                    game_mtime = mt
            except OSError:
                pass

    # Compare with a small tolerance (1 second) for filesystem precision
    tolerance = 1.0

    if game_mtime > lw_time + tolerance:
        return "drift"
    if ws_mtime > lw_time + tolerance:
        return "stale"
    return "ok"


def get_unenrolled_workspace_dirs(project_dir):
    """Return workspace folder names not in the registry (excluding skip dirs and dotfiles)."""
    from torch.map_scanner import _SKIP_WORKSPACE_DIRS
    registry = load_registry(project_dir)
    enrolled = set(registry["maps"].keys())
    unenrolled = []
    if os.path.isdir(project_dir):
        for entry in sorted(os.listdir(project_dir)):
            if entry.startswith("."):
                continue
            if entry in _SKIP_WORKSPACE_DIRS:
                continue
            entry_path = os.path.join(project_dir, entry)
            if os.path.isdir(entry_path) and entry not in enrolled:
                unenrolled.append(entry)
    return unenrolled


def bulk_enroll(project_dir, game_path, pre_synced=False):
    """Enroll all workspace folders that have a matching game map.

    When *pre_synced* is True, stamps last_written with the current time
    (used by fork, where the workspace and game folder are already in sync).

    Returns (enrolled_count, skipped_names) where skipped_names are workspace
    folders that don't have a corresponding game map folder.
    """
    from torch.map_scanner import _SKIP_WORKSPACE_DIRS
    registry = load_registry(project_dir)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    enrolled_count = 0
    skipped = []

    if not os.path.isdir(project_dir):
        return 0, []

    for entry in sorted(os.listdir(project_dir)):
        if entry.startswith("."):
            continue
        if entry in _SKIP_WORKSPACE_DIRS:
            continue
        entry_path = os.path.join(project_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        if entry in registry["maps"]:
            continue  # already enrolled

        game_map_dir = os.path.join(game_path, "data", "maps", entry)
        if os.path.isdir(game_map_dir):
            registry["maps"][entry] = {
                "enrolled_at": now,
                "last_written": now if pre_synced else None,
            }
            enrolled_count += 1
        else:
            skipped.append(entry)

    if enrolled_count:
        save_registry(project_dir, registry)

    return enrolled_count, skipped
