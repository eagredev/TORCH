"""SCORCH Scanner — vanilla content detection + cross-reference analysis.

Detects vanilla content in any pokeemerald-expansion project and checks
whether custom content references it.  Used by cleanup.py for SCORCH,
but designed as a standalone detection engine that other modules can import.
"""
# TORCH_MODULE: SCORCH Scanner
# TORCH_GROUP: Tools
import os
import re
import glob as _glob

from torch.project_files import (
    classify_maps, load_map_groups, load_wild_encounters,
    load_layouts, load_map_json, get_all_encounters,
    folder_to_map_const,
)


# ============================================================
# CATEGORY REGISTRY
# ============================================================

CATEGORIES = [
    {"id": "maps",       "label": "Maps",             "priority": 1},
    {"id": "trainers",   "label": "Trainers",         "priority": 2},
    {"id": "encounters", "label": "Wild Encounters",   "priority": 3},
    {"id": "frontier",   "label": "Battle Frontier",   "priority": 4},
    {"id": "scripts",    "label": "Shared Scripts",     "priority": 5},
    {"id": "tilesets",   "label": "Tilesets",          "priority": 7},
    {"id": "graphics",   "label": "Graphics",          "priority": 8},
    {"id": "music",      "label": "Music",             "priority": 9},
]

CATEGORY_IDS = [c["id"] for c in CATEGORIES]


def _category_by_id(cat_id):
    """Return category dict by id, or None."""
    for c in CATEGORIES:
        if c["id"] == cat_id:
            return c
    return None


# ============================================================
# VANILLA MAP DETECTION  (reuses map_scanner sentinel)
# ============================================================

def _load_map_groups(game_path):
    """Parse map_groups.json -> (vanilla_maps set, custom_maps set, group_data dict).

    Compatibility shim — delegates to project_files for cached loading.
    """
    vanilla, custom = classify_maps(game_path)
    group_data = load_map_groups(game_path) or {}
    return vanilla, custom, group_data


def has_sentinel(game_path):
    """Return True if map_groups.json still contains vanilla maps.

    Checks whether any map listed in map_groups.json is a known vanilla
    map name.  Replaces the old sentinel-group check so this works
    correctly after SCORCH Phoenix removes vanilla groups.
    """
    from torch.vanilla_maps import get_vanilla_map_names
    from torch.expansion_compat import detect_expansion_version

    data = load_map_groups(game_path)
    if not data:
        return False
    version = detect_expansion_version(game_path)
    known_vanilla = get_vanilla_map_names(version)
    for group_name in data.get("group_order", []):
        for map_name in data.get(group_name, []):
            if map_name in known_vanilla:
                return True
    return False


# ============================================================
# VANILLA TRAINER DETECTION  (threshold from battle_io)
# ============================================================

_VANILLA_TRAINER_THRESHOLD = 854
_META_DEFINES = {"TRAINERS_COUNT", "MAX_TRAINERS_COUNT", "TRAINER_PARTNER", "TRAINER_NONE"}


def _load_all_trainer_consts(game_path):
    """Read opponents.h -> list of (const, id) for ALL trainers."""
    opponents_path = os.path.join(game_path, "include", "constants", "opponents.h")
    results = []
    if not os.path.exists(opponents_path):
        return results
    with open(opponents_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"^#define\s+(TRAINER_\w+)\s+(\d+)", line)
            if m:
                const = m.group(1)
                tid = int(m.group(2))
                if const in _META_DEFINES:
                    continue
                results.append((const, tid))
    return results


def _classify_trainers(game_path):
    """Return (vanilla_trainers, custom_trainers) — each a list of (const, id)."""
    all_trainers = _load_all_trainer_consts(game_path)
    vanilla = [(c, tid) for c, tid in all_trainers if tid <= _VANILLA_TRAINER_THRESHOLD]
    custom = [(c, tid) for c, tid in all_trainers if tid > _VANILLA_TRAINER_THRESHOLD]
    return vanilla, custom


# ============================================================
# VANILLA ENCOUNTER DETECTION
# ============================================================

def _load_encounters(game_path):
    """Parse wild_encounters.json -> list of encounter group dicts.

    Compatibility shim — delegates to project_files.get_all_encounters().
    """
    return get_all_encounters(game_path)


def _classify_encounters(game_path, vanilla_maps):
    """Return (vanilla_encounters, custom_encounters) lists.

    Each entry is a dict with 'map' and 'base_label' keys from the JSON.
    """
    all_enc = _load_encounters(game_path)
    vanilla = []
    custom = []
    for enc in all_enc:
        map_name = enc.get("map", "")
        # The JSON uses MAP_MAPNAME format
        # Convert MAP_MAPNAME to the folder name: strip MAP_ prefix, title-case
        # Actually pokeemerald uses the raw constant like "MAP_ROUTE101"
        # The map folder name is the PascalCase version
        # We need to check against the vanilla_maps set which uses folder names
        folder_name = _map_const_to_folder(map_name)
        if folder_name in vanilla_maps:
            vanilla.append(enc)
        else:
            custom.append(enc)
    return vanilla, custom


def map_const_to_folder(map_const):
    """Convert MAP_ROUTE_101 or MAP_PETALBURG_CITY to Route101 / PetalburgCity.

    The JSON wild_encounters uses the C constant form.  Map folders use
    PascalCase.  We strip MAP_ prefix and convert UPPER_SNAKE to PascalCase.
    """
    if not map_const:
        return ""
    name = map_const
    if name.startswith("MAP_"):
        name = name[4:]
    # PETALBURG_CITY -> PetalburgCity
    parts = name.split("_")
    return "".join(p.capitalize() for p in parts)

_map_const_to_folder = map_const_to_folder  # backward compat alias


# ============================================================
# BATTLE FRONTIER DETECTION
# ============================================================

def _detect_frontier(game_path):
    """Return dict with frontier detection results.

    Keys: has_frontier, frontier_maps, frontier_data_dir, frontier_src_files
    """
    result = {
        "has_frontier": False,
        "frontier_maps": [],
        "frontier_data_dir": None,
        "frontier_src_files": [],
    }

    # Check for frontier data directory
    frontier_data = os.path.join(game_path, "src", "data", "battle_frontier")
    if os.path.isdir(frontier_data):
        result["has_frontier"] = True
        result["frontier_data_dir"] = frontier_data
        for f in os.listdir(frontier_data):
            if f.endswith((".h", ".c", ".inc")):
                result["frontier_src_files"].append(f)

    # Check for BattleFrontier_ maps
    maps_dir = os.path.join(game_path, "data", "maps")
    if os.path.isdir(maps_dir):
        for entry in os.listdir(maps_dir):
            if entry.startswith("BattleFrontier"):
                result["frontier_maps"].append(entry)
                result["has_frontier"] = True

    return result


# ============================================================
# SHARED SCRIPTS DETECTION
# ============================================================

def _scan_shared_scripts(game_path, vanilla_maps):
    """Find scripts in data/scripts/ that are only referenced by vanilla maps.

    Returns list of dicts: {path, filename, labels, referencing_custom_files}
    """
    scripts_dir = os.path.join(game_path, "data", "scripts")
    if not os.path.isdir(scripts_dir):
        return []

    results = []
    for fname in sorted(os.listdir(scripts_dir)):
        if not fname.endswith(".inc"):
            continue
        fpath = os.path.join(scripts_dir, fname)
        # Extract all labels from the script file
        labels = _extract_script_labels(fpath)
        if not labels:
            continue
        results.append({
            "path": fpath,
            "filename": fname,
            "labels": labels,
            "referencing_custom_files": [],  # filled by cross-ref
        })
    return results


def _extract_script_labels(inc_path):
    """Extract all script labels (Name: or Name::) from an .inc file."""
    labels = []
    try:
        with open(inc_path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^(\w+)::?", line)
                if m:
                    labels.append(m.group(1))
    except OSError:
        pass
    return labels


# ============================================================
# TILESET DETECTION
# ============================================================

def _find_tilesets_with_c_source_refs(game_path):
    """Scan C source files for INCBIN references to secondary tileset directories.

    Returns a dict: tileset_name -> [source_file, ...] for any tileset that has
    hardcoded INCBIN paths in C source (beyond graphics.h/metatiles.h/headers.h,
    which are cleaned up by the writer). These tilesets cannot be safely removed
    by directory deletion alone and must be BLOCKED.
    """
    managed_basenames = {"graphics.h", "metatiles.h", "headers.h", "overrides.h"}

    refs = {}  # tileset_name -> set of relative source paths
    ts_prefix = "data/tilesets/secondary/"
    search_dirs = [
        os.path.join(game_path, "src"),
        os.path.join(game_path, "include"),
    ]

    for sdir in search_dirs:
        if not os.path.isdir(sdir):
            continue
        for dirpath, _, filenames in os.walk(sdir):
            for fname in filenames:
                if not fname.endswith((".c", ".h")):
                    continue
                if fname in managed_basenames:
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue
                if ts_prefix not in content:
                    continue
                rel = os.path.relpath(fpath, game_path)
                idx = 0
                while True:
                    pos = content.find(ts_prefix, idx)
                    if pos == -1:
                        break
                    after = content[pos + len(ts_prefix):]
                    slash = after.find("/")
                    if slash > 0:
                        ts_name = after[:slash]
                        refs.setdefault(ts_name, set()).add(rel)
                    idx = pos + 1

    return {k: sorted(v) for k, v in refs.items()}


def _scan_tilesets(game_path, vanilla_maps):
    """Find secondary tilesets used only by vanilla map layouts.

    Returns list of dicts: {tileset_name, path, used_by_vanilla, used_by_custom,
                             c_source_refs}
    """
    tilesets_dir = os.path.join(game_path, "data", "tilesets", "secondary")
    if not os.path.isdir(tilesets_dir):
        return []

    # Step 1: Parse layouts.json to get layout_id -> gTileset_* mapping
    layout_to_tileset = {}  # LAYOUT_ID -> gTileset_Name
    layouts_data = load_layouts(game_path)
    if layouts_data:
        for entry in layouts_data.get("layouts", []):
            lid = entry.get("id")
            sec = entry.get("secondary_tileset")
            if lid and sec:
                layout_to_tileset[lid] = sec

    # Step 2: Parse all map.json files to get map_name -> layout_id
    maps_dir = os.path.join(game_path, "data", "maps")
    map_to_layout = {}  # map_name -> LAYOUT_ID
    if os.path.isdir(maps_dir):
        for map_name in os.listdir(maps_dir):
            mdata = load_map_json(game_path, map_name)
            if not mdata:
                continue
            layout_id = mdata.get("layout")
            if layout_id:
                map_to_layout[map_name] = layout_id

    # Step 3: Build gTileset_* -> {map_names} usage map
    tileset_struct_usage = {}  # "gTileset_Petalburg" -> set of map names
    for map_name, layout_id in map_to_layout.items():
        ts_struct = layout_to_tileset.get(layout_id)
        if ts_struct:
            tileset_struct_usage.setdefault(ts_struct, set()).add(map_name)

    # Step 4: Build gTileset_* -> dir_name mapping by scanning graphics.h
    # graphics.h has lines like:
    #   gTilesetTiles_Petalburg[] = INCBIN_U32("data/tilesets/secondary/petalburg/tiles.4bpp.lz");
    struct_to_dir = {}  # "gTileset_Petalburg" -> "petalburg"
    dir_to_structs = {}  # "petalburg" -> {"gTileset_Petalburg"}
    graphics_path = os.path.join(game_path, "src", "data", "tilesets", "graphics.h")
    try:
        with open(graphics_path, encoding="utf-8") as f:
            for line in f:
                if "data/tilesets/secondary/" not in line:
                    continue
                # Extract directory name from path
                m_path = re.search(r"data/tilesets/secondary/([^/]+)/", line)
                # Extract symbol name
                m_sym = re.search(r"gTileset(?:Tiles|Palettes)_(\w+?)(?:Compressed)?\[", line)
                if m_path and m_sym:
                    dir_name = m_path.group(1)
                    symbol = m_sym.group(1)
                    struct_name = f"gTileset_{symbol}"
                    struct_to_dir[struct_name] = dir_name
                    dir_to_structs.setdefault(dir_name, set()).add(struct_name)
    except OSError:
        pass

    # Step 5: Build dir_name -> {map_names} by resolving through structs
    tileset_dir_usage = {}  # dir_name -> set of map names
    for struct_name, map_names in tileset_struct_usage.items():
        dir_name = struct_to_dir.get(struct_name)
        if dir_name:
            tileset_dir_usage.setdefault(dir_name, set()).update(map_names)

    # Find tilesets with hardcoded INCBIN refs in C source files
    c_source_refs = _find_tilesets_with_c_source_refs(game_path)

    results = []
    for ts_name in sorted(os.listdir(tilesets_dir)):
        ts_path = os.path.join(tilesets_dir, ts_name)
        if not os.path.isdir(ts_path):
            continue
        using_maps = tileset_dir_usage.get(ts_name, set())
        used_by_vanilla = using_maps & vanilla_maps
        used_by_custom = using_maps - vanilla_maps
        results.append({
            "tileset_name": ts_name,
            "path": ts_path,
            "used_by_vanilla": sorted(used_by_vanilla),
            "used_by_custom": sorted(used_by_custom),
            "c_source_refs": c_source_refs.get(ts_name, []),
        })
    return results


# ============================================================
# MUSIC DETECTION
# ============================================================

def _scan_music(game_path, vanilla_maps):
    """Find BGM tracks only used by vanilla map headers.

    Returns list of dicts: {song_const, used_by_vanilla, used_by_custom}
    """
    # Parse all map.json files to find music assignments
    song_usage = {}  # song_const -> set of map names
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return []

    for map_name in os.listdir(maps_dir):
        mdata = load_map_json(game_path, map_name)
        if not mdata:
            continue
        music = mdata.get("music")
        if music:
            song_usage.setdefault(music, set()).add(map_name)

    results = []
    for song_const, using_maps in sorted(song_usage.items()):
        used_by_vanilla = using_maps & vanilla_maps
        used_by_custom = using_maps - vanilla_maps
        if used_by_vanilla and not used_by_custom:
            results.append({
                "song_const": song_const,
                "used_by_vanilla": sorted(used_by_vanilla),
                "used_by_custom": sorted(used_by_custom),
            })
    return results


# ============================================================
# GRAPHICS DETECTION
# ============================================================

def _scan_graphics(game_path, vanilla_trainer_consts):
    """Find trainer pics only used by vanilla trainers.

    Returns list of dicts: {pic_const, path, is_vanilla_only}
    """
    # For Phase A, just detect trainer pics referenced by vanilla trainers
    # Full implementation with OBJ_EVENT_GFX comes in Phase E
    vanilla_consts_set = set(vanilla_trainer_consts)
    results = []

    # Parse trainers.party or trainers.h for TRAINER_PIC_ references
    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    if os.path.exists(party_path):
        try:
            with open(party_path, encoding="utf-8") as f:
                content = f.read()
            # Find all Pic: lines with trainer const context
            sections = re.split(r"^(=== \S+ ===)\s*$", content, flags=re.MULTILINE)
            i = 1
            while i < len(sections) - 1:
                header = sections[i].strip()
                body = sections[i + 1]
                m = re.match(r"=== (\S+) ===", header)
                if m:
                    tc = m.group(1)
                    pic_m = re.search(r"^Pic:\s*(.+)$", body, re.MULTILINE)
                    if pic_m and tc in vanilla_consts_set:
                        pic_val = pic_m.group(1).strip()
                        results.append({
                            "pic_const": pic_val,
                            "trainer_const": tc,
                            "is_vanilla_only": True,
                        })
                i += 2
        except OSError:
            pass

    return results


# ============================================================
# CROSS-REFERENCE SCANNER
# ============================================================

class CrossRefScanner:
    """Scans custom content for references to vanilla content.

    Builds a dependency map so we know which vanilla items are safe to remove
    vs which are referenced by custom content.
    """

    def __init__(self, game_path, vanilla_maps, custom_maps):
        self.game_path = game_path
        self.vanilla_maps = vanilla_maps
        self.custom_maps = custom_maps
        self.maps_dir = os.path.join(game_path, "data", "maps")
        # Cache custom script content for repeated searches
        self._custom_script_cache = None

    def _get_custom_scripts(self):
        """Load and cache all custom map scripts (scripts.inc + scripts.pory)."""
        if self._custom_script_cache is not None:
            return self._custom_script_cache

        self._custom_script_cache = []
        for map_name in sorted(self.custom_maps):
            map_dir = os.path.join(self.maps_dir, map_name)
            if not os.path.isdir(map_dir):
                continue
            for fname in ("scripts.inc", "scripts.pory"):
                fpath = os.path.join(map_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, encoding="utf-8") as f:
                            content = f.read()
                        self._custom_script_cache.append({
                            "map_name": map_name,
                            "filename": fname,
                            "path": fpath,
                            "content": content,
                        })
                    except OSError:
                        pass
        return self._custom_script_cache

    def check_map_warp_refs(self, vanilla_map_name):
        """Check if any custom map has warps pointing to vanilla_map_name.

        Returns list of custom map names that reference it.
        """
        refs = []
        for map_name in sorted(self.custom_maps):
            map_json = os.path.join(self.maps_dir, map_name, "map.json")
            if not os.path.isfile(map_json):
                continue
            try:
                with open(map_json, encoding="utf-8") as f:
                    content = f.read()
                # Warp targets appear as "dest_map": "MAP_VANILLAMAPNAME"
                # Convert folder name to constant form for matching
                const_form = folder_to_map_const(vanilla_map_name)
                if const_form in content or vanilla_map_name in content:
                    refs.append(map_name)
            except OSError:
                pass
        return refs

    def check_map_connection_refs(self, vanilla_map_name):
        """Check if any custom map has connections to vanilla_map_name.

        Returns list of custom map names with connections to it.
        """
        refs = []
        const_form = folder_to_map_const(vanilla_map_name)
        for map_name in sorted(self.custom_maps):
            data = load_map_json(self.game_path, map_name)
            if not data:
                continue
            connections = data.get("connections", [])
            for conn in connections:
                dest = conn.get("map", "")
                if dest == const_form or dest == vanilla_map_name:
                    refs.append(map_name)
                    break
        return refs

    def check_map_script_refs(self, vanilla_map_name):
        """Check if any custom script references MAP_VANILLAMAPNAME."""
        refs = []
        const_form = folder_to_map_const(vanilla_map_name)
        for script_info in self._get_custom_scripts():
            if const_form in script_info["content"]:
                refs.append(script_info["map_name"])
        return list(set(refs))

    def check_trainer_refs(self, trainer_const):
        """Check if any custom script references a trainer constant.

        Returns list of dicts: {map_name, filename, path}
        """
        refs = []
        for script_info in self._get_custom_scripts():
            if trainer_const in script_info["content"]:
                refs.append({
                    "map_name": script_info["map_name"],
                    "filename": script_info["filename"],
                    "path": script_info["path"],
                })
        return refs

    def check_script_label_refs(self, label):
        """Check if any custom script references a specific label."""
        refs = []
        for script_info in self._get_custom_scripts():
            if label in script_info["content"]:
                refs.append({
                    "map_name": script_info["map_name"],
                    "filename": script_info["filename"],
                    "path": script_info["path"],
                })
        return refs

    def check_music_refs(self, song_const):
        """Check if any custom map or script uses a song constant."""
        refs = []
        # Check custom map.json music fields
        for map_name in sorted(self.custom_maps):
            data = load_map_json(self.game_path, map_name)
            if not data:
                continue
            if data.get("music") == song_const:
                refs.append({"type": "map_header", "map_name": map_name})
        # Check custom scripts for setmusic/savebgm
        for script_info in self._get_custom_scripts():
            if song_const in script_info["content"]:
                refs.append({
                    "type": "script",
                    "map_name": script_info["map_name"],
                    "filename": script_info["filename"],
                })
        return refs

    def check_frontier_refs(self):
        """Check if any custom content references Battle Frontier constants.

        Returns list of reference dicts.
        """
        frontier_patterns = [
            r"BATTLE_FRONTIER_",
            r"BattleFrontier",
            r"FACILITY_",
            r"FRONTIER_",
        ]
        refs = []
        for script_info in self._get_custom_scripts():
            for pat in frontier_patterns:
                if re.search(pat, script_info["content"]):
                    refs.append({
                        "map_name": script_info["map_name"],
                        "filename": script_info["filename"],
                        "pattern": pat,
                    })
                    break  # one match per file is enough
        return refs


_folder_to_map_const = folder_to_map_const  # backward compat alias


# ============================================================
# REMOVAL PLAN
# ============================================================

# Status constants
SAFE = "SAFE"          # no custom references, safe to remove
BLOCKED = "BLOCKED"    # custom content references this item
CAUTION = "CAUTION"    # removable but with caveats


class RemovalItem:
    """One item in a removal plan."""

    __slots__ = ("category", "name", "status", "detail", "refs", "data")

    def __init__(self, category, name, status=SAFE, detail="", refs=None, data=None):
        self.category = category   # category id string
        self.name = name           # display name (map name, trainer const, etc.)
        self.status = status       # SAFE / BLOCKED / CAUTION
        self.detail = detail       # human-readable explanation
        self.refs = refs or []     # list of reference strings for BLOCKED items
        self.data = data or {}     # category-specific extra data


class RemovalPlan:
    """Collection of RemovalItems with summary stats."""

    def __init__(self):
        self.items = []            # list of RemovalItem
        self.scan_errors = []      # list of error strings from scanning

    def add(self, item):
        self.items.append(item)

    def by_category(self, cat_id):
        return [i for i in self.items if i.category == cat_id]

    def safe_items(self, cat_id=None):
        items = self.items if cat_id is None else self.by_category(cat_id)
        return [i for i in items if i.status == SAFE]

    def blocked_items(self, cat_id=None):
        items = self.items if cat_id is None else self.by_category(cat_id)
        return [i for i in items if i.status == BLOCKED]

    def caution_items(self, cat_id=None):
        items = self.items if cat_id is None else self.by_category(cat_id)
        return [i for i in items if i.status == CAUTION]

    def category_summary(self):
        """Return list of dicts: {id, label, total, safe, blocked, caution}."""
        summary = []
        for cat in CATEGORIES:
            cat_items = self.by_category(cat["id"])
            if not cat_items:
                continue
            summary.append({
                "id": cat["id"],
                "label": cat["label"],
                "total": len(cat_items),
                "safe": len([i for i in cat_items if i.status == SAFE]),
                "blocked": len([i for i in cat_items if i.status == BLOCKED]),
                "caution": len([i for i in cat_items if i.status == CAUTION]),
            })
        return summary

    def total_safe(self):
        return len(self.safe_items())

    def total_blocked(self):
        return len(self.blocked_items())


# ============================================================
# CATEGORY SCANNERS
# ============================================================

def build_map_const_lookup(game_path, group_data):
    """Build map_const -> map_name mapping from map_groups.h + map_groups.json.

    Returns dict: MAP_CONSTANT -> MapName (e.g. MAP_PETALBURG_CITY -> PetalburgCity).
    Uses the auto-generated map_groups.h for constant names and map_groups.json
    group ordering for the index-to-name mapping.
    """
    header_path = os.path.join(game_path, "include", "constants", "map_groups.h")
    if not os.path.isfile(header_path):
        return {}

    # Parse all MAP_* defines with their (map_idx, group_idx) pairs
    consts = {}
    try:
        with open(header_path, encoding="utf-8") as f:
            for line in f:
                m = re.match(
                    r"^#define\s+(MAP_\w+)\s+\((\d+)\s*\|\s*\((\d+)\s*<<\s*8\)\)",
                    line,
                )
                if m:
                    consts[(int(m.group(3)), int(m.group(2)))] = m.group(1)
    except OSError:
        return {}

    # Map each (group_idx, map_idx) to the map name from JSON
    group_order = group_data.get("group_order", [])
    const_to_name = {}
    for gidx, group_name in enumerate(group_order):
        for midx, map_name in enumerate(group_data.get(group_name, [])):
            key = (gidx, midx)
            if key in consts:
                const_to_name[consts[key]] = map_name
    return const_to_name

_build_map_const_lookup = build_map_const_lookup  # backward compat alias


def find_map_c_source_refs(game_path, vanilla_const_set):
    """Scan C source files for references to vanilla MAP_* constants.

    Returns a dict: map_const -> [source_file, ...] for maps whose constants
    are hardcoded in C source. These maps cannot be safely removed because
    map_groups.h (which defines these constants) is auto-generated — deleting
    a map from map_groups.json removes its MAP_* constant, breaking any C
    code that references it.

    Detects both direct references (MAP_ROUTE118) and indirect references via
    MAP_GROUP()/MAP_NUM() token-pasting macros (ROUTE118 -> MAP_ROUTE118).
    """
    # map_groups.h is auto-generated so we skip it
    managed_basenames = {"map_groups.h"}

    # Build a set of bare forms: MAP_ROUTE118 -> ROUTE118
    bare_to_const = {}
    for const in vanilla_const_set:
        if const.startswith("MAP_"):
            bare = const[4:]  # strip MAP_ prefix
            bare_to_const[bare] = const

    refs = {}  # map_const -> set of relative source paths
    search_dirs = [
        os.path.join(game_path, "src"),
        os.path.join(game_path, "include"),
    ]

    # Regex for MAP_GROUP(BARE) and MAP_NUM(BARE) token-pasting patterns
    indirect_re = re.compile(r"\bMAP_(?:GROUP|NUM)\(\s*([A-Z][A-Z0-9_]+)\s*\)")

    # Build regex for bare form matching (used only in files with MAP_GROUP/MAP_NUM)
    bare_set = set(bare_to_const.keys())

    for sdir in search_dirs:
        if not os.path.isdir(sdir):
            continue
        for dirpath, _, filenames in os.walk(sdir):
            for fname in filenames:
                if not fname.endswith((".c", ".h")):
                    continue
                if fname in managed_basenames:
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue

                rel = os.path.relpath(fpath, game_path)

                # Direct: MAP_ROUTE118
                for const in re.findall(r"\bMAP_[A-Z][A-Z0-9_]+\b", content):
                    if const in vanilla_const_set:
                        refs.setdefault(const, set()).add(rel)

                # Indirect: MAP_GROUP(ROUTE118), MAP_NUM(ROUTE118)
                for m in indirect_re.finditer(content):
                    bare = m.group(1)
                    const = bare_to_const.get(bare)
                    if const:
                        refs.setdefault(const, set()).add(rel)

                # Files that define macros wrapping MAP_GROUP/MAP_NUM may pass
                # bare map names through wrapper macros (e.g. REMATCH(..., ROUTE118)).
                # In these files, scan for all bare forms as standalone words.
                if "MAP_GROUP" in content or "MAP_NUM" in content:
                    for word in re.findall(r"\b([A-Z][A-Z0-9_]+)\b", content):
                        if word in bare_set:
                            refs.setdefault(bare_to_const[word], set()).add(rel)

    return {k: sorted(v) for k, v in refs.items()}

_find_map_c_source_refs = find_map_c_source_refs  # backward compat alias


def find_layout_c_source_refs(game_path, vanilla_maps):
    """Scan C source files for references to vanilla LAYOUT_* constants.

    Returns:
        layout_c_refs: layout_id -> [source_file, ...] for layout constants
            hardcoded in C source. When a map is removed, its layout entry
            may be deleted from layouts.json, removing the LAYOUT_* constant
            from auto-generated layouts.h — breaking C code that references it.
        layout_to_maps: layout_id -> set of map_names using that layout.
            Multiple maps can share a layout. A LAYOUT_* constant only
            disappears when ALL maps using it are removed.
    """
    maps_dir = os.path.join(game_path, "data", "maps")

    # Build layout_id -> set of map_names from each vanilla map's map.json
    layout_to_maps = {}  # layout_id -> set of map names
    for map_name in vanilla_maps:
        mdata = load_map_json(game_path, map_name)
        if not mdata:
            continue
        lid = mdata.get("layout")
        if lid and lid.startswith("LAYOUT_"):
            layout_to_maps.setdefault(lid, set()).add(map_name)

    if not layout_to_maps:
        return {}, {}

    vanilla_layout_set = set(layout_to_maps.keys())

    # layouts.h is auto-generated so we skip it
    managed_basenames = {"layouts.h"}

    refs = {}  # layout_id -> set of relative source paths
    search_dirs = [
        os.path.join(game_path, "src"),
        os.path.join(game_path, "include"),
    ]

    for sdir in search_dirs:
        if not os.path.isdir(sdir):
            continue
        for dirpath, _, filenames in os.walk(sdir):
            for fname in filenames:
                if not fname.endswith((".c", ".h")):
                    continue
                if fname in managed_basenames:
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue

                rel = os.path.relpath(fpath, game_path)

                for const in re.findall(r"\bLAYOUT_[A-Z][A-Z0-9_]+\b", content):
                    if const in vanilla_layout_set:
                        refs.setdefault(const, set()).add(rel)

    return {k: sorted(v) for k, v in refs.items()}, layout_to_maps


def build_warp_connection_index(game_path, vanilla_maps, const_to_name):
    """Build warp and connection adjacency indexes for all vanilla maps.

    Parses every vanilla map's map.json for warp destinations and connections.

    Args:
        game_path: path to the pokeemerald-expansion project
        vanilla_maps: set of vanilla map folder names
        const_to_name: dict MAP_CONSTANT -> folder name (from build_map_const_lookup)

    Returns (warp_index, connection_index):
        warp_index: dict map_name -> set of dest map names
        connection_index: dict map_name -> set of connected map names
    """
    maps_dir = os.path.join(game_path, "data", "maps")
    warp_index = {}     # map_name -> set of dest map names
    conn_index = {}     # map_name -> set of connected map names

    for map_name in vanilla_maps:
        data = load_map_json(game_path, map_name)
        if not data:
            continue

        # Warps
        warp_dests = set()
        for event in (data.get("warp_events") or []):
            dest = event.get("dest_map", "")
            if dest:
                folder = const_to_name.get(dest) or map_const_to_folder(dest)
                if folder and folder != map_name:
                    warp_dests.add(folder)
        if warp_dests:
            warp_index[map_name] = warp_dests

        # Connections
        conn_dests = set()
        for conn in (data.get("connections") or []):
            dest = conn.get("map", "")
            if dest:
                folder = const_to_name.get(dest) or map_const_to_folder(dest)
                if folder and folder != map_name:
                    conn_dests.add(folder)
        if conn_dests:
            conn_index[map_name] = conn_dests

    return warp_index, conn_index


def _classify_map_items(plan, vanilla_maps, xref, map_c_refs, game_path):
    """Classify each vanilla map as SAFE or BLOCKED based on cross-references.

    Adds RemovalItems to plan for each vanilla map.
    """
    for map_name in sorted(vanilla_maps):
        warp_refs = xref.check_map_warp_refs(map_name)
        conn_refs = xref.check_map_connection_refs(map_name)
        script_refs = xref.check_map_script_refs(map_name)
        c_refs = map_c_refs.get(map_name, [])

        all_refs = []
        if warp_refs:
            all_refs.extend([f"Warp target from: {m}" for m in warp_refs])
        if conn_refs:
            all_refs.extend([f"Connection from: {m}" for m in conn_refs])
        if script_refs:
            all_refs.extend([f"Script reference from: {m}" for m in script_refs])
        if c_refs:
            all_refs.extend([f"Hardcoded in: {f}" for f in c_refs])

        if all_refs:
            item = RemovalItem(
                "maps", map_name, BLOCKED,
                detail=f"Referenced by {len(all_refs)} custom content item(s)",
                refs=all_refs,
                data={"warp_refs": warp_refs, "conn_refs": conn_refs,
                      "script_refs": script_refs, "c_source_refs": c_refs},
            )
        else:
            item = RemovalItem(
                "maps", map_name, SAFE,
                data={"map_dir": os.path.join(game_path, "data", "maps", map_name)},
            )
        plan.add(item)


def _build_map_sharing_data(game_path, vanilla_maps):
    """Build shared events/scripts targets and layout-to-map mappings.

    Returns (shared_targets, layout_to_map) where:
      shared_targets: target_name -> set of maps sharing it
      layout_to_map: LAYOUT_ID -> map_name
    """
    shared_targets = {}  # target_name -> set of maps sharing it
    for map_name in vanilla_maps:
        mdata = load_map_json(game_path, map_name)
        if not mdata:
            continue
        for key in ("shared_events_map", "shared_scripts_map"):
            target = mdata.get(key, "")
            if target:
                shared_targets.setdefault(target, set()).add(map_name)

    layout_to_map = {}  # LAYOUT_ID -> map_name
    for map_name in vanilla_maps:
        mdata = load_map_json(game_path, map_name)
        if not mdata:
            continue
        lid = mdata.get("layout")
        if lid:
            layout_to_map[lid] = map_name

    return shared_targets, layout_to_map


def _find_blocked_map_refs(maps_dir, blocked_names, safe_consts,
                           safe_layout_consts, const_to_name, map_data_re):
    """Scan blocked maps' data files for references to safe map/layout constants.

    Returns set of map names that should be newly blocked.
    """
    newly_blocked = set()
    for bmap in blocked_names:
        bmap_dir = os.path.join(maps_dir, bmap)
        if not os.path.isdir(bmap_dir):
            continue
        for fname in ("scripts.inc", "connections.inc", "events.inc"):
            fpath = os.path.join(bmap_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            for const in map_data_re.findall(content):
                if const in safe_consts:
                    ref_name = const_to_name.get(const)
                    if ref_name:
                        newly_blocked.add(ref_name)
                elif const in safe_layout_consts:
                    newly_blocked.add(safe_layout_consts[const])
    return newly_blocked


def _propagate_blocked_maps(plan, name_to_const, const_to_name,
                            layout_to_map, shared_targets, maps_dir):
    """Iteratively block SAFE maps referenced by BLOCKED maps until stable.

    Modifies plan items in place. Checks MAP_*/LAYOUT_* constants in blocked
    maps' data files and shared events/scripts targets.
    """
    map_data_re = re.compile(r"\b(?:MAP|LAYOUT)_[A-Z][A-Z0-9_]+\b")

    for _iteration in range(20):  # safety cap
        safe_names = {i.name for i in plan.items if i.status == SAFE}
        safe_consts = {name_to_const[n] for n in safe_names if n in name_to_const}
        safe_layout_consts = {}
        for lid, mname in layout_to_map.items():
            if mname in safe_names:
                safe_layout_consts[lid] = mname
        if not safe_consts and not safe_layout_consts:
            break

        blocked_names = {i.name for i in plan.items if i.status == BLOCKED}
        newly_blocked = _find_blocked_map_refs(
            maps_dir, blocked_names, safe_consts, safe_layout_consts,
            const_to_name, map_data_re)

        # Also block SAFE maps whose events/scripts are shared by BLOCKED maps
        for target, sharers in shared_targets.items():
            if target in safe_names and sharers & blocked_names:
                newly_blocked.add(target)

        if not newly_blocked:
            break  # fixed point reached

        for item in plan.items:
            if item.name in newly_blocked and item.status == SAFE:
                item.status = BLOCKED
                item.detail = "Required by remaining vanilla maps"
                item.refs = ["Referenced by blocked vanilla map data"]


def scan_vanilla_maps(game_path):
    """Scan and cross-reference vanilla maps.

    Returns (RemovalPlan, vanilla_maps_set, custom_maps_set).
    """
    plan = RemovalPlan()
    vanilla_maps, custom_maps, group_data = _load_map_groups(game_path)

    if not vanilla_maps:
        plan.scan_errors.append("No vanilla maps detected (sentinel missing?)")
        return plan, set(), set()

    xref = CrossRefScanner(game_path, vanilla_maps, custom_maps)

    # Build MAP_* constant lookup and scan C source for hardcoded refs
    const_to_name = _build_map_const_lookup(game_path, group_data)
    name_to_const = {v: k for k, v in const_to_name.items()}
    vanilla_const_set = {name_to_const[m] for m in vanilla_maps if m in name_to_const}
    c_source_refs = _find_map_c_source_refs(game_path, vanilla_const_set)

    # Invert: map_name -> [source_files] for easy lookup
    map_c_refs = {}  # map_name -> [source_files]
    for const, files in c_source_refs.items():
        mname = const_to_name.get(const)
        if mname:
            map_c_refs[mname] = files

    # Phase 1: classify each map as SAFE or BLOCKED
    _classify_map_items(plan, vanilla_maps, xref, map_c_refs, game_path)

    # Phase 2: build sharing and layout data for propagation
    shared_targets, layout_to_map = _build_map_sharing_data(
        game_path, vanilla_maps)

    # Phase 3: propagate blocks to fixed point
    maps_dir = os.path.join(game_path, "data", "maps")
    _propagate_blocked_maps(plan, name_to_const, const_to_name,
                            layout_to_map, shared_targets, maps_dir)

    return plan, vanilla_maps, custom_maps


def _find_trainer_c_source_refs(game_path, vanilla_const_set):
    """Scan C source files for references to vanilla trainer constants.

    Returns a dict: trainer_const -> [source_file, ...] for trainers that are
    hardcoded in C source files (beyond opponents.h and trainer data files which
    are updated by the writer). These trainers cannot be safely removed.
    """
    # C data files managed by the writer — skip these
    managed_files = {"trainers.h", "opponents.h", "trainer_parties.h"}

    refs = {}  # trainer_const -> set of relative source paths
    search_dirs = [
        os.path.join(game_path, "src"),
        os.path.join(game_path, "include"),
    ]

    for sdir in search_dirs:
        if not os.path.isdir(sdir):
            continue
        for dirpath, _, filenames in os.walk(sdir):
            for fname in filenames:
                if not fname.endswith((".c", ".h")):
                    continue
                if fname in managed_files:
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue

                rel = os.path.relpath(fpath, game_path)
                for const in re.findall(r"\bTRAINER_[A-Z][A-Z0-9_]+\b", content):
                    if const in vanilla_const_set:
                        refs.setdefault(const, set()).add(rel)

    return {k: sorted(v) for k, v in refs.items()}


def _find_trainer_kept_map_refs(game_path, vanilla_const_set, safe_maps):
    """Scan kept (non-removed) map scripts for trainer constant references.

    Returns a dict: trainer_const -> [map_name, ...].
    """
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return {}

    refs = {}
    for map_name in os.listdir(maps_dir):
        if map_name in safe_maps:
            continue  # This map is being removed, skip
        map_dir = os.path.join(maps_dir, map_name)
        if not os.path.isdir(map_dir):
            continue
        # Check scripts.inc and events.inc
        for fname in ("scripts.inc", "events.inc"):
            fpath = os.path.join(map_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            for const in re.findall(r"\bTRAINER_[A-Z][A-Z0-9_]+\b", content):
                if const in vanilla_const_set:
                    refs.setdefault(const, set()).add(map_name)

    return {k: sorted(v) for k, v in refs.items()}


def _find_trainer_shared_script_refs(game_path, vanilla_const_set):
    """Scan shared scripts (data/scripts/*.inc) for trainer constant references.

    Returns a dict: trainer_const -> [script_filename, ...].
    """
    scripts_dir = os.path.join(game_path, "data", "scripts")
    if not os.path.isdir(scripts_dir):
        return {}

    refs = {}
    for fname in os.listdir(scripts_dir):
        if not fname.endswith(".inc"):
            continue
        fpath = os.path.join(scripts_dir, fname)
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue
        for const in re.findall(r"\bTRAINER_[A-Z][A-Z0-9_]+\b", content):
            if const in vanilla_const_set:
                refs.setdefault(const, set()).add(fname)

    return {k: sorted(v) for k, v in refs.items()}


def scan_vanilla_trainers(game_path, custom_maps=None, safe_maps=None):
    """Scan and cross-reference vanilla trainers.

    Args:
        safe_maps: set of map names being removed (SAFE in map plan).
                   If provided, trainers referenced by kept maps are blocked.

    Returns RemovalPlan with trainer items.
    """
    plan = RemovalPlan()
    vanilla_trainers, custom_trainers = _classify_trainers(game_path)

    if not vanilla_trainers:
        return plan

    vanilla_maps = set()
    if custom_maps is None:
        vanilla_maps, custom_maps, _ = _load_map_groups(game_path)
    else:
        vanilla_maps, _, _ = _load_map_groups(game_path)

    xref = CrossRefScanner(game_path, vanilla_maps, custom_maps)

    # Build set of all vanilla trainer constants for cross-ref scans
    vanilla_const_set = {c for c, _ in vanilla_trainers}
    c_source_refs = _find_trainer_c_source_refs(game_path, vanilla_const_set)

    # Scan shared scripts (data/scripts/*.inc) for trainer refs
    shared_script_refs = _find_trainer_shared_script_refs(
        game_path, vanilla_const_set)

    # Scan kept (non-removed) map scripts for trainer refs
    kept_map_refs = {}
    if safe_maps is not None:
        kept_map_refs = _find_trainer_kept_map_refs(
            game_path, vanilla_const_set, safe_maps)

    for trainer_const, trainer_id in vanilla_trainers:
        refs = xref.check_trainer_refs(trainer_const)
        c_refs = c_source_refs.get(trainer_const, [])
        ss_refs = shared_script_refs.get(trainer_const, [])
        km_refs = kept_map_refs.get(trainer_const, [])

        if refs:
            ref_strs = [f"Referenced in: {r['map_name']}/{r['filename']}" for r in refs]
            item = RemovalItem(
                "trainers", trainer_const, BLOCKED,
                detail=f"Used by {len(refs)} custom script(s)",
                refs=ref_strs,
                data={"trainer_id": trainer_id, "script_refs": refs},
            )
        elif c_refs:
            ref_strs = [f"Hardcoded in: {f}" for f in c_refs]
            item = RemovalItem(
                "trainers", trainer_const, BLOCKED,
                detail=f"Hardcoded in {len(c_refs)} C source file(s)",
                refs=ref_strs,
                data={"trainer_id": trainer_id, "c_source_refs": c_refs},
            )
        elif ss_refs:
            ref_strs = [f"Referenced in shared script: {f}" for f in ss_refs]
            item = RemovalItem(
                "trainers", trainer_const, BLOCKED,
                detail=f"Used in {len(ss_refs)} shared script(s)",
                refs=ref_strs,
                data={"trainer_id": trainer_id, "shared_script_refs": ss_refs},
            )
        elif km_refs:
            ref_strs = [f"Referenced by kept map: {r}" for r in km_refs]
            item = RemovalItem(
                "trainers", trainer_const, BLOCKED,
                detail=f"Used by {len(km_refs)} kept map(s)",
                refs=ref_strs,
                data={"trainer_id": trainer_id, "kept_map_refs": km_refs},
            )
        else:
            item = RemovalItem(
                "trainers", trainer_const, SAFE,
                data={"trainer_id": trainer_id},
            )
        plan.add(item)

    return plan


def scan_vanilla_encounters(game_path, vanilla_maps=None):
    """Scan vanilla wild encounter entries.

    Returns RemovalPlan with encounter items.
    """
    plan = RemovalPlan()
    if vanilla_maps is None:
        vanilla_maps, _, _ = _load_map_groups(game_path)

    vanilla_enc, custom_enc = _classify_encounters(game_path, vanilla_maps)

    for enc in vanilla_enc:
        map_const = enc.get("map", "unknown")
        base_label = enc.get("base_label", "")
        display = f"{map_const}"
        if base_label:
            display += f" ({base_label})"
        item = RemovalItem(
            "encounters", display, SAFE,
            data={"map_const": map_const, "base_label": base_label,
                  "encounter_data": enc},
        )
        plan.add(item)

    return plan


def scan_vanilla_frontier(game_path, custom_maps=None):
    """Scan Battle Frontier content.

    Returns RemovalPlan with a single frontier item (system-level removal).
    """
    plan = RemovalPlan()
    info = _detect_frontier(game_path)

    if not info["has_frontier"]:
        return plan

    vanilla_maps, cm, _ = _load_map_groups(game_path)
    if custom_maps is None:
        custom_maps = cm

    xref = CrossRefScanner(game_path, vanilla_maps, custom_maps)
    frontier_refs = xref.check_frontier_refs()

    n_maps = len(info["frontier_maps"])
    n_files = len(info["frontier_src_files"])
    detail = f"{n_maps} maps, {n_files} data files"

    # The Battle Frontier is deeply embedded in C source (battle_dome.c,
    # battle_pyramid.c, battle_tower.c, frontier_util.c, battle_setup.c, etc.)
    # with hardcoded map constants, trainer constants, and data structures.
    # Safe automated removal is not possible — always mark BLOCKED.
    ref_strs = ["Deeply embedded in C source (battle_dome.c, battle_pyramid.c, etc.)"]
    if frontier_refs:
        ref_strs.extend(f"{r['map_name']}/{r['filename']} matches {r['pattern']}"
                        for r in frontier_refs)
    item = RemovalItem(
        "frontier", "Battle Frontier (complete system)", BLOCKED,
        detail=f"{detail}; requires manual C source edits to remove",
        refs=ref_strs,
        data=info,
    )
    plan.add(item)

    return plan


def scan_vanilla_scripts(game_path, vanilla_maps=None, custom_maps=None,
                         safe_maps=None):
    """Scan shared scripts for vanilla-only references.

    Args:
        safe_maps: set of map names being removed (SAFE in map plan).
                   If provided, scripts are blocked if ANY kept map uses them.

    Returns RemovalPlan with script items.
    """
    plan = RemovalPlan()
    if vanilla_maps is None or custom_maps is None:
        vanilla_maps, custom_maps, _ = _load_map_groups(game_path)

    xref = CrossRefScanner(game_path, vanilla_maps, custom_maps)
    shared_scripts = _scan_shared_scripts(game_path, vanilla_maps)

    # Build a set of ALL maps that are being kept (not removed).
    # This includes custom maps AND blocked vanilla maps.
    maps_dir = os.path.join(game_path, "data", "maps")
    if safe_maps is not None:
        all_map_dirs = set()
        if os.path.isdir(maps_dir):
            for d in os.listdir(maps_dir):
                if os.path.isdir(os.path.join(maps_dir, d, )):
                    all_map_dirs.add(d)
        kept_maps = all_map_dirs - safe_maps
    else:
        kept_maps = custom_maps

    # Build set of all labels across all shared scripts for C source check
    all_labels = set()
    for si in shared_scripts:
        all_labels.update(si["labels"])

    # Scan C source files for script label references (extern declarations)
    c_label_refs = _find_script_labels_in_c_source(game_path, all_labels)

    for script_info in shared_scripts:
        # Check each label against ALL kept maps (custom + blocked vanilla)
        # and C source files
        blocking_labels = []
        for label in script_info["labels"]:
            # First check C source files
            c_refs = c_label_refs.get(label, [])
            if c_refs:
                blocking_labels.append((label, [
                    {"map_name": "(C source)", "filename": f}
                    for f in c_refs]))
                continue
            # Then check custom maps via xref
            refs = xref.check_script_label_refs(label)
            if refs:
                blocking_labels.append((label, refs))
                continue
            # Then check kept vanilla maps' scripts/events for this label
            if safe_maps is not None:
                kept_refs = _check_label_in_kept_maps(
                    maps_dir, kept_maps, label)
                if kept_refs:
                    blocking_labels.append((label, kept_refs))

        if blocking_labels:
            ref_strs = []
            for label, refs in blocking_labels:
                for r in refs:
                    ref_strs.append(f"Label '{label}' used by: {r['map_name']}/{r['filename']}")
            item = RemovalItem(
                "scripts", script_info["filename"], BLOCKED,
                detail=f"{len(blocking_labels)} label(s) referenced by kept maps",
                refs=ref_strs,
                data={"path": script_info["path"], "labels": script_info["labels"],
                      "blocking_labels": blocking_labels},
            )
        else:
            item = RemovalItem(
                "scripts", script_info["filename"], SAFE,
                data={"path": script_info["path"], "labels": script_info["labels"]},
            )
        plan.add(item)

    return plan


def _find_script_labels_in_c_source(game_path, label_set):
    """Scan C source/header files and event_scripts.s for script label refs.

    Script labels defined in .inc files can be referenced from C code via
    extern declarations (e.g. EventScript_UseSurf in src/item_use.c) or
    from event_scripts.s via .4byte directives (e.g. gStdScripts table).

    Returns a dict: label -> [relative_source_file, ...].
    """
    refs = {}
    search_dirs = [
        os.path.join(game_path, "src"),
        os.path.join(game_path, "include"),
    ]
    for sdir in search_dirs:
        if not os.path.isdir(sdir):
            continue
        for dirpath, _, filenames in os.walk(sdir):
            for fname in filenames:
                if not fname.endswith((".c", ".h")):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue
                rel = os.path.relpath(fpath, game_path)
                for label in label_set:
                    if label in content:
                        refs.setdefault(label, set()).add(rel)

    # Also check event_scripts.s for .4byte label references
    # (gStdScripts table and other direct references)
    es_path = os.path.join(game_path, "data", "event_scripts.s")
    if os.path.isfile(es_path):
        try:
            with open(es_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            for label in label_set:
                # Check for .4byte references (not .include lines)
                if re.search(rf"\.4byte\s+{re.escape(label)}\b", content):
                    refs.setdefault(label, set()).add("data/event_scripts.s")
        except OSError:
            pass

    return {k: sorted(v) for k, v in refs.items()}


def _check_label_in_kept_maps(maps_dir, kept_maps, label):
    """Check if any kept (non-removed) map references a script label.

    Scans scripts.inc, events.inc, and map.json for the label.
    Returns list of dicts: {map_name, filename}.
    """
    refs = []
    for map_name in sorted(kept_maps):
        map_dir = os.path.join(maps_dir, map_name)
        if not os.path.isdir(map_dir):
            continue
        # Check map.json for mapscripts references
        map_json = os.path.join(map_dir, "map.json")
        if os.path.isfile(map_json):
            try:
                with open(map_json, encoding="utf-8") as f:
                    content = f.read()
                if label in content:
                    refs.append({"map_name": map_name, "filename": "map.json"})
                    continue
            except OSError:
                pass
        # Check header.inc, scripts.inc, and events.inc
        for fname in ("header.inc", "scripts.inc", "events.inc"):
            fpath = os.path.join(map_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, encoding="utf-8") as f:
                    content = f.read()
                if label in content:
                    refs.append({"map_name": map_name, "filename": fname})
                    break
            except OSError:
                pass
    return refs


def scan_vanilla_tilesets(game_path, vanilla_maps=None, safe_maps=None):
    """Scan tilesets used only by maps being removed.

    Args:
        safe_maps: set of map names that will be removed (SAFE in map plan).
                   If provided, a tileset is only SAFE if ALL maps using it
                   are in this set. If None, falls back to vanilla_maps.

    Returns RemovalPlan with tileset items.
    """
    plan = RemovalPlan()
    if vanilla_maps is None:
        vanilla_maps, _, _ = _load_map_groups(game_path)

    tilesets = _scan_tilesets(game_path, vanilla_maps)

    # If we have the actual safe map set from the map scan, use it for
    # precise classification. A tileset is only removable if every map
    # that references it is also being removed.
    check_set = safe_maps if safe_maps is not None else vanilla_maps

    for ts in tilesets:
        all_users = set(ts["used_by_vanilla"]) | set(ts["used_by_custom"])
        kept_maps = all_users - check_set  # maps NOT being removed

        if kept_maps:
            ref_strs = [f"Used by kept map: {m}" for m in sorted(kept_maps)]
            item = RemovalItem(
                "tilesets", ts["tileset_name"], BLOCKED,
                detail=f"Used by {len(kept_maps)} map(s) not being removed",
                refs=ref_strs,
                data=ts,
            )
        elif ts["c_source_refs"]:
            ref_strs = [f"Hardcoded in: {f}" for f in ts["c_source_refs"]]
            item = RemovalItem(
                "tilesets", ts["tileset_name"], BLOCKED,
                detail=f"Hardcoded INCBIN in {len(ts['c_source_refs'])} C source file(s)",
                refs=ref_strs,
                data=ts,
            )
        elif all_users:
            item = RemovalItem(
                "tilesets", ts["tileset_name"], SAFE,
                detail=f"Used by {len(all_users)} map(s) all being removed",
                data=ts,
            )
        else:
            item = RemovalItem(
                "tilesets", ts["tileset_name"], SAFE,
                detail="Not used by any map layout",
                data=ts,
            )
        plan.add(item)

    return plan


def scan_vanilla_graphics(game_path, vanilla_maps=None):
    """Scan graphics for vanilla-only usage.

    Returns RemovalPlan (stub — full implementation in Phase E).
    """
    plan = RemovalPlan()
    if vanilla_maps is None:
        vanilla_maps, _, _ = _load_map_groups(game_path)

    vanilla_trainers, _ = _classify_trainers(game_path)
    vanilla_consts = [c for c, _ in vanilla_trainers]
    gfx = _scan_graphics(game_path, vanilla_consts)

    for g in gfx:
        item = RemovalItem(
            "graphics", g["pic_const"], SAFE,
            detail=f"Used by vanilla trainer: {g.get('trainer_const', '?')}",
            data=g,
        )
        plan.add(item)

    return plan


def scan_vanilla_music(game_path, vanilla_maps=None, custom_maps=None):
    """Scan music for vanilla-only usage.

    Returns RemovalPlan with music items.
    """
    plan = RemovalPlan()
    if vanilla_maps is None or custom_maps is None:
        vanilla_maps, custom_maps, _ = _load_map_groups(game_path)

    xref = CrossRefScanner(game_path, vanilla_maps, custom_maps)
    songs = _scan_music(game_path, vanilla_maps)

    for song in songs:
        refs = xref.check_music_refs(song["song_const"])
        if refs:
            ref_strs = []
            for r in refs:
                if r["type"] == "map_header":
                    ref_strs.append(f"Custom map header: {r['map_name']}")
                else:
                    ref_strs.append(f"Custom script: {r['map_name']}/{r.get('filename', '?')}")
            item = RemovalItem(
                "music", song["song_const"], BLOCKED,
                detail=f"Referenced by {len(refs)} custom item(s)",
                refs=ref_strs,
                data=song,
            )
        else:
            item = RemovalItem(
                "music", song["song_const"], SAFE,
                detail=f"Used by {len(song['used_by_vanilla'])} vanilla map(s) only",
                data=song,
            )
        plan.add(item)

    return plan


# ============================================================
# FULL SCAN / SINGLE-CATEGORY SCAN
# ============================================================

def full_scan(game_path):
    """Run all category scanners and return a merged RemovalPlan."""
    plan = RemovalPlan()

    # Maps first (provides vanilla_maps/custom_maps for others)
    map_plan, vanilla_maps, custom_maps = scan_vanilla_maps(game_path)
    plan.items.extend(map_plan.items)
    plan.scan_errors.extend(map_plan.scan_errors)

    # Extract SAFE map names for downstream scanners
    safe_maps = {i.name for i in map_plan.items if i.status == SAFE}

    # Trainers
    trainer_plan = scan_vanilla_trainers(game_path, custom_maps,
                                         safe_maps=safe_maps)
    plan.items.extend(trainer_plan.items)

    # Encounters
    enc_plan = scan_vanilla_encounters(game_path, vanilla_maps)
    plan.items.extend(enc_plan.items)

    # Battle Frontier
    frontier_plan = scan_vanilla_frontier(game_path, custom_maps)
    plan.items.extend(frontier_plan.items)

    # Scripts — pass safe_maps so shared scripts used by kept maps are blocked
    script_plan = scan_vanilla_scripts(game_path, vanilla_maps, custom_maps,
                                       safe_maps=safe_maps)
    plan.items.extend(script_plan.items)

    # Tilesets — pass safe_maps so tilesets used by kept maps are blocked
    ts_plan = scan_vanilla_tilesets(game_path, vanilla_maps, safe_maps=safe_maps)
    plan.items.extend(ts_plan.items)

    # Graphics
    gfx_plan = scan_vanilla_graphics(game_path, vanilla_maps)
    plan.items.extend(gfx_plan.items)

    # Music
    music_plan = scan_vanilla_music(game_path, vanilla_maps, custom_maps)
    plan.items.extend(music_plan.items)

    return plan


def scan_category(game_path, category_id):
    """Run a single category scanner.

    Returns RemovalPlan for just that category.
    """
    vanilla_maps, custom_maps, _ = _load_map_groups(game_path)

    scanners = {
        "maps":       lambda: scan_vanilla_maps(game_path)[0],
        "trainers":   lambda: scan_vanilla_trainers(game_path, custom_maps),
        "encounters": lambda: scan_vanilla_encounters(game_path, vanilla_maps),
        "frontier":   lambda: scan_vanilla_frontier(game_path, custom_maps),
        "scripts":    lambda: scan_vanilla_scripts(game_path, vanilla_maps, custom_maps),
        "tilesets":   lambda: scan_vanilla_tilesets(game_path, vanilla_maps),
        "graphics":   lambda: scan_vanilla_graphics(game_path, vanilla_maps),
        "music":      lambda: scan_vanilla_music(game_path, vanilla_maps, custom_maps),
    }

    scanner = scanners.get(category_id)
    if scanner is None:
        plan = RemovalPlan()
        plan.scan_errors.append(f"Unknown category: {category_id}")
        return plan

    return scanner()
