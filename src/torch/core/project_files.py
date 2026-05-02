"""Centralized game JSON file loaders with session-level caching.

Provides cached loaders for the standard game JSON files that multiple
TORCH modules need.  All results are cached for the process lifetime.
Call clear_project_cache() to force a re-read.

Also provides structured encounter data functions (get_all_encounters,
get_encounters_for_map, etc.) that sit on top of the raw loader.
"""
# TORCH_MODULE: Project Files
# TORCH_GROUP: Core
import os
import json
import glob as _glob
import re
import tempfile

PROJECT_FILES_VERSION = "1.0"

# Cache keyed by (os.path.realpath(game_path), kind)
_CACHE = {}

# Deprecated: kept for import compatibility only.
# Use vanilla_maps.get_vanilla_map_names() for name-based classification.
_LAST_VANILLA_GROUP = "gMapGroup_IndoorRoute124"

# ---------------------------------------------------------------------------
# Relative path constants
# ---------------------------------------------------------------------------

PATH_MAP_GROUPS = os.path.join("data", "maps", "map_groups.json")
PATH_LAYOUTS = os.path.join("data", "layouts", "layouts.json")
PATH_WILD_ENCOUNTERS = os.path.join("src", "data", "wild_encounters.json")
PATH_HEAL_LOCATIONS = os.path.join("src", "data", "heal_locations.json")


def _cache_key(game_path, kind):
    """Build a cache key from game_path and a kind tag."""
    try:
        return (os.path.realpath(game_path), kind)
    except OSError:
        return (game_path, kind)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_map_groups(game_path):
    """Load data/maps/map_groups.json.

    Returns the full parsed dict, or None on error.
    Cached by game_path.
    """
    key = _cache_key(game_path, "map_groups")
    if key in _CACHE:
        return _CACHE[key]

    filepath = os.path.join(game_path, PATH_MAP_GROUPS)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        _CACHE[key] = None
        return None

    _CACHE[key] = data
    return data


def classify_maps(game_path):
    """Classify maps as vanilla or custom by name.

    Returns (vanilla_maps: set, custom_maps: set).
    Uses load_map_groups() internally.

    Classification is based on membership in the frozen vanilla map name
    set from vanilla_maps.py.  This works correctly even after SCORCH
    Phoenix removes vanilla map groups from map_groups.json.

    Also scans data/maps/ on disk: any map folder that exists on disk but
    is NOT listed in map_groups.json is treated as custom (newly added map
    that hasn't been saved into groups yet) unless it's a known vanilla name.

    On error: returns (set(), set()).
    """
    from torch.vanilla_maps import get_vanilla_map_names
    from torch.expansion_compat import detect_expansion_version

    data = load_map_groups(game_path)
    if not data:
        return set(), set()

    version = detect_expansion_version(game_path)
    known_vanilla = get_vanilla_map_names(version)

    vanilla_maps = set()
    custom_maps = set()
    all_grouped = set()
    for group_name in data.get("group_order", []):
        for map_name in data.get(group_name, []):
            all_grouped.add(map_name)
            if map_name in known_vanilla:
                vanilla_maps.add(map_name)
            else:
                custom_maps.add(map_name)

    # Scan data/maps/ for folders not in any group (newly added maps)
    maps_dir = os.path.join(game_path, "data", "maps")
    if os.path.isdir(maps_dir):
        try:
            for entry in os.listdir(maps_dir):
                if entry not in all_grouped:
                    full = os.path.join(maps_dir, entry)
                    if os.path.isdir(full) and os.path.isfile(
                            os.path.join(full, "map.json")):
                        if entry in known_vanilla:
                            vanilla_maps.add(entry)
                        else:
                            custom_maps.add(entry)
        except OSError:
            pass

    return vanilla_maps, custom_maps


def load_layouts(game_path):
    """Load data/layouts/layouts.json.

    Returns the full parsed dict (which has a "layouts" key containing the
    array), or None on error.  Cached by game_path.
    """
    key = _cache_key(game_path, "layouts")
    if key in _CACHE:
        return _CACHE[key]

    filepath = os.path.join(game_path, PATH_LAYOUTS)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        _CACHE[key] = None
        return None

    _CACHE[key] = data
    return data


def load_map_json(game_path, map_name):
    """Load a specific map's map.json.

    Path: data/maps/{map_name}/map.json
    Returns the parsed dict, or None on error.
    Cached by (game_path, map_name).
    """
    key = _cache_key(game_path, ("map_json", map_name))
    if key in _CACHE:
        return _CACHE[key]

    filepath = os.path.join(game_path, "data", "maps", map_name, "map.json")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        _CACHE[key] = None
        return None

    _CACHE[key] = data
    return data


def load_wild_encounters(game_path):
    """Load src/data/wild_encounters.json.

    Returns the full parsed dict, or None on error.
    Cached by game_path.
    """
    key = _cache_key(game_path, "wild_encounters")
    if key in _CACHE:
        return _CACHE[key]

    filepath = os.path.join(game_path, PATH_WILD_ENCOUNTERS)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        _CACHE[key] = None
        return None

    _CACHE[key] = data
    return data


def find_layout_dir(game_path, layout_id):
    """Look up the directory name for a layout by its ID string.

    Uses load_layouts() internally.
    Returns the directory name (e.g. "MauvilleCity") or None.
    """
    data = load_layouts(game_path)
    if not data:
        return None

    for entry in data.get("layouts", []):
        if entry.get("id") == layout_id:
            bd = entry.get("blockdata_filepath", "")
            if bd:
                return os.path.basename(os.path.dirname(bd))
            break

    return None


def clear_project_cache():
    """Wipe all cached data.  Call when game files change mid-session."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Structured encounter data
# ---------------------------------------------------------------------------

_ENCOUNTER_TYPES = ("land_mons", "water_mons", "rock_smash_mons", "fishing_mons")
_TIME_SUFFIXES = ("Morning", "Day", "Evening", "Night")


def get_all_encounters(game_path):
    """Flatten all encounter entries from all groups into a single list.

    Returns list[dict] — each dict is one encounter entry with 'map',
    'base_label', and encounter type keys.  Returns [] on error.
    Uses load_wild_encounters() internally (cached).
    """
    data = load_wild_encounters(game_path)
    if not data:
        return []
    encounters = []
    for group in data.get("wild_encounter_groups", []):
        for enc in group.get("encounters", []):
            encounters.append(enc)
    return encounters


def get_encounters_for_map(game_path, map_const):
    """Get all encounter entries for a specific map constant.

    Returns list[dict] — usually 1 entry (standard) or up to 4 (time-based).
    Returns [] if map not found or on error.
    """
    return [e for e in get_all_encounters(game_path)
            if e.get("map") == map_const]


def get_encounter_types(encounter_entry):
    """Return which encounter types are present in an entry.

    Returns list[str] — e.g. ["land_mons", "water_mons"].
    """
    return [t for t in _ENCOUNTER_TYPES if t in encounter_entry]


def get_encounter_species(encounter_entry, encounter_type):
    """Extract the species list for a specific encounter type.

    Returns list[dict] — each has min_level, max_level, species.
    Returns [] if the encounter type doesn't exist.
    """
    type_data = encounter_entry.get(encounter_type)
    if not isinstance(type_data, dict):
        return []
    return type_data.get("mons", [])


def extract_time_suffix(base_label):
    """Parse a base_label for a time-of-day suffix.

    Returns str or None — e.g. "Morning", "Night", or None if no suffix.
    """
    if not base_label:
        return None
    for suffix in _TIME_SUFFIXES:
        if base_label.endswith("_" + suffix):
            return suffix
    return None


def get_field_rates(game_path):
    """Get per-slot encounter rates from the field definitions.

    Returns dict[str, list[int]] mapping encounter type to rate list,
    e.g. {"land_mons": [20, 20, 10, ...], "water_mons": [60, 30, ...]}.
    Returns empty dict on error or if fields not found.
    """
    data = load_wild_encounters(game_path)
    if not data:
        return {}
    # Find first group with for_maps=True
    for group in data.get("wild_encounter_groups", []):
        if group.get("for_maps"):
            fields = group.get("fields")
            if not fields:
                return {}
            rates = {}
            for field in fields:
                ftype = field.get("type")
                frates = field.get("encounter_rates")
                if ftype and isinstance(frates, list):
                    rates[ftype] = list(frates)
            return rates
    return {}


def get_maps_with_encounters(game_path):
    """Get the set of all map constants that have encounter data.

    Returns set[str] — e.g. {"MAP_ROUTE101", "MAP_ROUTE102"}.
    """
    return {e.get("map") for e in get_all_encounters(game_path)
            if e.get("map")}


def write_encounters(game_path, data):
    """Write modified encounter data back to wild_encounters.json.

    Uses atomic write (write to temp, rename).  Calls clear_project_cache()
    after writing to invalidate the cache.
    Returns True on success, False on error.
    """
    filepath = os.path.join(game_path, PATH_WILD_ENCOUNTERS)
    try:
        dir_path = os.path.dirname(filepath)
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_path, suffix=".tmp", prefix=".wild_enc_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, filepath)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        return False
    clear_project_cache()
    return True


# ---------------------------------------------------------------------------
# Heal locations
# ---------------------------------------------------------------------------


def load_heal_locations(game_path):
    """Load src/data/heal_locations.json.

    Returns list of heal location dicts, or None on error.
    Cached per session.
    """
    key = _cache_key(game_path, "heal_locations")
    if key in _CACHE:
        return _CACHE[key]

    filepath = os.path.join(game_path, PATH_HEAL_LOCATIONS)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        _CACHE[key] = None
        return None

    locs = data.get("heal_locations")
    if not isinstance(locs, list):
        _CACHE[key] = None
        return None

    _CACHE[key] = locs
    return locs


def write_heal_locations(game_path, data):
    """Atomic write of heal locations JSON.

    *data* is the list of heal location dicts (not the wrapper dict).
    Clears cache.  Returns bool success.
    """
    filepath = os.path.join(game_path, PATH_HEAL_LOCATIONS)
    payload = {"heal_locations": data}
    try:
        dir_path = os.path.dirname(filepath)
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_path, suffix=".tmp", prefix=".heal_loc_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, filepath)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        return False
    clear_project_cache()
    return True


def write_map_groups(game_path, data):
    """Atomic write of map_groups.json.

    *data* is the full dict (group_order + group lists).
    Clears cache.  Returns bool success.
    """
    filepath = os.path.join(game_path, PATH_MAP_GROUPS)
    try:
        dir_path = os.path.dirname(filepath)
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_path, suffix=".tmp", prefix=".map_groups_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, filepath)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        return False
    clear_project_cache()
    return True


def write_layouts(game_path, data):
    """Atomic write of layouts.json.

    *data* is the full dict (layouts_table_label + layouts array).
    Clears cache.  Returns bool success.
    """
    filepath = os.path.join(game_path, PATH_LAYOUTS)
    try:
        dir_path = os.path.dirname(filepath)
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_path, suffix=".tmp", prefix=".layouts_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, filepath)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        return False
    clear_project_cache()
    return True


def write_map_json(game_path, map_name, data):
    """Atomic write of a map's map.json.

    Path: data/maps/{map_name}/map.json
    *data* is the full map dict.
    Clears cache.  Returns bool success.
    """
    filepath = os.path.join(game_path, "data", "maps", map_name, "map.json")
    try:
        dir_path = os.path.dirname(filepath)
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_path, suffix=".tmp", prefix=".map_json_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, filepath)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        return False
    clear_project_cache()
    return True


def remove_encounters_for_map(game_path, map_const):
    """Remove all encounter entries for a specific map.

    Returns int — number of entries removed.
    Calls write_encounters() internally.
    """
    data = load_wild_encounters(game_path)
    if not data:
        return 0
    removed = 0
    for group in data.get("wild_encounter_groups", []):
        encounters = group.get("encounters", [])
        original_len = len(encounters)
        group["encounters"] = [
            e for e in encounters if e.get("map") != map_const
        ]
        removed += original_len - len(group["encounters"])
    if removed > 0:
        write_encounters(game_path, data)
    return removed


# ---------------------------------------------------------------------------
# Trainer-to-map index
# ---------------------------------------------------------------------------

# Regex matching any trainerbattle_* macro with TRAINER_ constant as first arg.
# Works for both .pory (parenthesised) and .inc (space-separated) syntax.
_TRAINERBATTLE_PORY_RE = re.compile(
    r"trainerbattle_\w+\s*\(\s*(TRAINER_\w+)"
)
_TRAINERBATTLE_INC_RE = re.compile(
    r"trainerbattle_\w+\s+(TRAINER_\w+)"
)


def _scan_scripts_for_trainers(script_path):
    """Extract TRAINER_* constants from a single script file.

    Returns set of trainer constant strings found.
    """
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return set()
    if script_path.endswith(".pory"):
        return set(_TRAINERBATTLE_PORY_RE.findall(content))
    return set(_TRAINERBATTLE_INC_RE.findall(content))


def build_trainer_map_index(game_path):
    """Scan all map script files to build trainer-to-map mapping.

    Returns:
        (map_trainers, trainer_map) where:
        - map_trainers: dict[str, list[str]] -- {map_folder: [trainer_consts]}
        - trainer_map: dict[str, str] -- {trainer_const: map_folder}

    Trainer constants are extracted from trainerbattle_* calls in
    scripts.pory and scripts.inc under data/maps/.
    """
    key = _cache_key(game_path, "trainer_map_index")
    if key in _CACHE:
        return _CACHE[key]

    maps_dir = os.path.join(game_path, "data", "maps")
    map_trainers = {}  # map_folder -> [TRAINER_*]
    trainer_map = {}   # TRAINER_* -> map_folder

    # Scan .pory first (authoritative), then .inc for maps without .pory
    for ext in ("scripts.pory", "scripts.inc"):
        for fpath in _glob.glob(os.path.join(maps_dir, "**", ext),
                                recursive=True):
            map_folder = os.path.basename(os.path.dirname(fpath))
            consts = _scan_scripts_for_trainers(fpath)
            for c in consts:
                # First occurrence wins (pory scanned before inc)
                if c not in trainer_map:
                    trainer_map[c] = map_folder
                    map_trainers.setdefault(map_folder, []).append(c)

    # Sort trainer lists for stable output
    for k in map_trainers:
        map_trainers[k].sort()

    result = (map_trainers, trainer_map)
    _CACHE[key] = result
    return result


# ---------------------------------------------------------------------------
# Map name conversion
# ---------------------------------------------------------------------------

def get_map_objects(game_path, map_name):
    """Extract object events (NPCs) from a map's map.json.

    Returns list of dicts, one per NPC:
        {
            "object_id": int,       # local_id if present, else 1-based index
            "graphics_id": str,     # raw constant e.g. "OBJ_EVENT_GFX_NURSE"
            "display_name": str,    # human-readable e.g. "Nurse"
            "x": int, "y": int,
            "script": str,          # script label or "" if "0x0" or "0"
            "trainer_type": str,    # e.g. "TRAINER_TYPE_NORMAL"
            "flag": str,            # flag constant or "" if "0"
        }
    Returns [] if map.json doesn't exist or has no object_events.
    """
    from torch.names import _const_to_human_name

    data = load_map_json(game_path, map_name)
    if not data:
        return []

    events = data.get("object_events")
    if not isinstance(events, list):
        return []

    result = []
    for i, obj in enumerate(events):
        if not isinstance(obj, dict):
            continue

        # Object ID: prefer explicit local_id, fall back to 1-based index
        local_id = obj.get("local_id")
        if isinstance(local_id, int):
            obj_id = local_id
        elif isinstance(local_id, str) and local_id.isdigit():
            obj_id = int(local_id)
        else:
            obj_id = i + 1

        gfx = obj.get("graphics_id", "")
        script = obj.get("script", "")
        if script in ("0x0", "0", ""):
            script = ""

        flag = obj.get("flag", "")
        if flag == "0":
            flag = ""

        result.append({
            "object_id": obj_id,
            "graphics_id": gfx,
            "display_name": _const_to_human_name(gfx, "OBJ_EVENT_GFX_"),
            "x": obj.get("x", 0),
            "y": obj.get("y", 0),
            "script": script,
            "trainer_type": obj.get("trainer_type", "TRAINER_TYPE_NONE"),
            "flag": flag,
        })

    return result


def folder_to_map_const(folder_name):
    """Convert PascalCase folder name to MAP_UPPER_SNAKE constant.

    E.g. PetalburgCity -> MAP_PETALBURG_CITY, Route101 -> MAP_ROUTE101,
    ArtisanCave_1F -> MAP_ARTISAN_CAVE_1F.
    """
    if not folder_name:
        return ""
    # Insert underscore at lowercase->uppercase transitions only
    # (not digit->uppercase, so 1F stays together)
    snake = re.sub(r"([a-z])([A-Z])", r"\1_\2", folder_name)
    return "MAP_" + snake.upper()
