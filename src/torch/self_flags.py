"""
self_flags.py — Per-NPC auto-allocated flags (self-flag system).
TORCH_MODULE

Provides deterministic flag naming for NPC-scoped state (e.g. self.talked),
with automatic allocation from the FLAG_UNUSED_* pool and a JSON registry
to track allocations across compilations.

Registry location: {game_path}/.torch/self_flags.json
"""

import json
import os
import re
import tempfile


# ---------------------------------------------------------------------------
# Deterministic naming
# ---------------------------------------------------------------------------

def make_self_flag_name(map_name, npc_label, suffix):
    """Generate FLAG_SELF_{MAP}_{NPC}_{SUFFIX}.

    All parts are uppercased.  CamelCase is split with underscores
    (ShirubeTown -> SHIRUBE_TOWN).

    >>> make_self_flag_name("ShirubeTown", "Officer", "talked")
    'FLAG_SELF_SHIRUBETOWN_OFFICER_TALKED'
    """
    parts = [
        _to_const(map_name),
        _to_const(npc_label),
        suffix.upper(),
    ]
    return "FLAG_SELF_" + "_".join(parts)


def _to_const(name):
    """Convert CamelCase or mixed name to UPPER_SNAKE.

    ShirubeTown -> SHIRUBETOWN
    Route_103   -> ROUTE_103
    """
    # Strip the map prefix if the npc label starts with it
    # (e.g. ShirubeTown_Officer -> just use the whole thing)
    return re.sub(r"[^A-Z0-9]", "", name.upper())


# ---------------------------------------------------------------------------
# Registry I/O
# ---------------------------------------------------------------------------

_REGISTRY_DIR = ".torch"
_REGISTRY_FILE = "self_flags.json"


def _registry_path(game_path):
    return os.path.join(game_path, _REGISTRY_DIR, _REGISTRY_FILE)


def load_registry(game_path):
    """Load the self-flag registry.  Returns dict (flags key -> entry)."""
    if not game_path:
        return {}
    path = _registry_path(game_path)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if data.get("version") != 1:
            return {}
        return data.get("flags", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_registry(game_path, flags_dict):
    """Atomic write of the self-flag registry."""
    if not game_path:
        return
    dir_path = os.path.join(game_path, _REGISTRY_DIR)
    os.makedirs(dir_path, exist_ok=True)
    path = _registry_path(game_path)
    data = {"version": 1, "flags": flags_dict}
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def allocate_self_flag(game_path, flag_name, map_name="", npc_label="",
                       suffix=""):
    """Allocate flag_name from the FLAG_UNUSED_* pool.

    Appends a #define to flags.h and updates the registry.
    Returns the FLAG_UNUSED_0xNNN slot used, or None on failure.
    """
    if not game_path:
        return None

    from torch.flag_scanner import parse_flags_h

    parsed = parse_flags_h(game_path)
    if not parsed:
        return None

    # Build set of already-used slots (custom aliases + existing self-flags)
    used_slots = set()
    for _alias_name, target_name in parsed.get("custom_aliases", []):
        used_slots.add(target_name)

    registry = load_registry(game_path)
    for entry in registry.values():
        used_slots.add(entry.get("slot", ""))

    # Also check if flag_name already exists in flags.h
    from torch.gamedata import parse_defines
    existing = parse_defines(game_path, "flags")
    if flag_name in existing:
        # Already defined — find and return its slot
        if flag_name in registry:
            return registry[flag_name].get("slot")
        return flag_name  # already a real define

    # Find first free slot
    event_flags = parsed.get("event", [])
    free_slot = None
    for name, _hex_val, _comment, is_unused in event_flags:
        if is_unused and name not in used_slots:
            free_slot = name
            break

    if not free_slot:
        return None  # no free slots

    # Append #define to flags.h
    flags_h = os.path.join(game_path, "include", "constants", "flags.h")
    if not os.path.isfile(flags_h):
        return None

    with open(flags_h, "r") as f:
        content = f.read()

    # Insert before the last #endif or at end of event section
    define_line = f"#define {flag_name}  {free_slot}\n"

    # Find the right place — after the last FLAG_UNUSED or custom alias
    lines = content.split("\n")
    insert_idx = len(lines) - 1
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx].strip()
        if line.startswith("#define FLAG_"):
            insert_idx = idx + 1
            break

    lines.insert(insert_idx, define_line.rstrip("\n"))

    with open(flags_h, "w") as f:
        f.write("\n".join(lines))

    # Update registry
    registry[flag_name] = {
        "slot": free_slot,
        "map": map_name,
        "npc": npc_label,
        "suffix": suffix,
    }
    save_registry(game_path, registry)

    # Clear caches
    try:
        from torch.gamedata import clear_gamedata_cache
        clear_gamedata_cache()
    except ImportError:
        pass

    return free_slot


def ensure_self_flag(game_path, flag_name, map_name="", npc_label="",
                     suffix=""):
    """Ensure flag_name is allocated.  No-op if game_path is None."""
    if not game_path:
        return
    registry = load_registry(game_path)
    if flag_name in registry:
        return  # already allocated
    allocate_self_flag(game_path, flag_name, map_name, npc_label, suffix)
