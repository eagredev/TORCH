"""Scorch Scanner — scorched-earth analysis engine.

Determines what vanilla content to nuke and what custom content to protect.
Builds a ScorchPlan that the scorch_writer and scorch_patcher consume.
"""
# TORCH_MODULE: Scorch Scanner
# TORCH_GROUP: Tools
import json
import os
import re
import glob as _glob

from torch.cleanup_scanner import (
    _classify_trainers, _map_const_to_folder, has_sentinel,
)
from torch.project_files import (
    classify_maps, load_map_groups, load_layouts,
    load_map_json, get_all_encounters,
)
from torch.scorch_writer import list_scorch_snapshots


# Maps that must survive Phoenix even though they're in vanilla groups.
# InsideOfTruck: the moving van intro map — needed for game bootability.
_ENGINE_KEEP_MAPS = {"InsideOfTruck"}


# ============================================================
# DATA STRUCTURES
# ============================================================

class ScorchPlan:
    """Everything the writer and patcher need to execute a scorch."""

    def __init__(self):
        # Sets of names (folder-style: "Route101", "PetalburgCity")
        self.vanilla_maps = set()
        self.custom_maps = set()
        self.nuke_maps = set()          # vanilla_maps to delete
        self.keep_maps = set()          # custom_maps + engine deps

        # Map groups data for JSON rewrite
        self.map_groups_data = {}

        # Trainers: lists of (const_name, trainer_id)
        self.vanilla_trainers = []
        self.custom_trainers = []

        # Encounters: raw encounter dicts from wild_encounters.json
        self.vanilla_encounters = []
        self.custom_encounters = []

        # Scripts: list of {"path", "filename"} for vanilla .inc files
        self.vanilla_scripts = []
        self.custom_script_labels = set()  # labels referenced by custom content

        # Tilesets: {"dir_name", "symbol", "path"} dicts
        self.vanilla_tilesets = []
        self.custom_tilesets = []         # used by custom maps

        # Heal locations
        self.vanilla_heal_ids = []        # (name, id) tuples
        self.custom_heal_ids = []

        # LOCALID_* constants from vanilla maps (for stub generation)
        # dict: {"LOCALID_FOO": value, ...}
        self.vanilla_localids = {}

        # C source files needing patches: list of {"path", "reason"}
        self.c_patch_targets = []

        # LAYOUT_* constant names being removed (for patcher)
        self.vanilla_layout_consts = set()

        # Layouts: referenced vs orphaned
        self.referenced_layouts = set()   # LAYOUT_* IDs used by surviving maps
        self.orphaned_layouts = set()     # LAYOUT_* IDs to remove

        # MAPSECs: vanilla MAPSEC IDs to remove from region_map_sections.json
        self.vanilla_mapsecs = set()      # e.g. {"MAPSEC_LITTLEROOT_TOWN", ...}
        self.custom_mapsecs = set()       # e.g. {"MAPSEC_SHIRUBE_TOWN", ...}
        self.system_mapsecs = {"MAPSEC_NONE", "MAPSEC_DYNAMIC", "MAPSEC_COUNT"}

        # Engine requirements (never remove)
        self.engine_deps = set()

        # Summary counters
        self.errors = []

    def summary(self):
        """Return a dict of category -> (nuke_count, keep_count)."""
        return {
            "maps":       (len(self.nuke_maps), len(self.keep_maps)),
            "layouts":    (len(self.orphaned_layouts), len(self.referenced_layouts)),
            "trainers":   (len(self.vanilla_trainers), len(self.custom_trainers)),
            "encounters": (len(self.vanilla_encounters), len(self.custom_encounters)),
            "scripts":    (len(self.vanilla_scripts), 0),
            "tilesets":   (len(self.vanilla_tilesets), len(self.custom_tilesets)),
            "mapsecs":    (len(self.vanilla_mapsecs), len(self.custom_mapsecs)),
            "heal_locs":  (len(self.vanilla_heal_ids), len(self.custom_heal_ids)),
            "c_patches":  (len(self.c_patch_targets), 0),
        }


# ============================================================
# RE-ENTRANCY DETECTION
# ============================================================

def _is_already_scorched(game_path, plan):
    """Multi-signal detector for already-scorched projects.

    Check 1 (strongest): scorched_text_stubs.c exists (written by scorch_patcher).
    Check 2: vanilla sentinel is gone from map_groups.json.
    Check 3: scorch backup zips exist.
    Check 4: fewer than 20 total maps (original weak guard).

    Check 1 alone triggers.  Checks 2-4 need 2+ signals.
    """
    signals = 0

    # Check 1: stub file (strongest — only exists after a scorch)
    stubs_path = os.path.join(game_path, "src", "scorched_text_stubs.c")
    if os.path.isfile(stubs_path):
        return True

    # Check 2: sentinel removed
    if not has_sentinel(game_path):
        signals += 1

    # Check 3: scorch backup zips exist
    if list_scorch_snapshots(game_path):
        signals += 1

    # Check 4: low map count (original guard)
    total_maps = len(plan.nuke_maps) + len(plan.keep_maps)
    if total_maps < 20:
        signals += 1

    return signals >= 2


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def build_scorch_plan(game_path):
    """Analyse the game project and return a complete ScorchPlan.

    This is the only function the UI needs to call.
    """
    plan = ScorchPlan()

    # Phase 1: Maps
    _scan_maps(game_path, plan)

    # Re-entrancy guard: refuse to run on an already-scorched project
    if _is_already_scorched(game_path, plan):
        total_maps = len(plan.nuke_maps) + len(plan.keep_maps)
        plan.errors.append(
            f"Only {total_maps} maps found (expected 500+). "
            "The project may already be scorched. "
            "Refusing to proceed -- restore from snapshot first."
        )
        return plan

    # Phase 2: Trainers
    _scan_trainers(game_path, plan)

    # Phase 3: Encounters
    _scan_encounters(game_path, plan)

    # Phase 4: Scripts — SKIPPED
    # Phoenix removes map geography, not reusable gameplay scripts.
    # All data/scripts/*.inc files survive.  The writer's Phase 7
    # (_scorch_event_scripts) still strips .includes for deleted map scripts.
    # _scan_scripts(game_path, plan)

    # Phase 5: Tilesets — SKIPPED
    # User wants to keep ALL tilesets as reusable art assets.
    # plan.vanilla_tilesets stays empty, so writer/patcher no-op on tilesets.
    # _scan_tilesets(game_path, plan)

    # Phase 6: Heal locations
    _scan_heal_locations(game_path, plan)

    # Phase 6b: Extract LOCALIDs from vanilla map JSONs (before writer deletes them)
    _scan_vanilla_localids(game_path, plan)

    # Phase 7: MAPSECs (region map sections)
    _scan_mapsecs(game_path, plan)

    # Phase 7b: Referenced layouts (identifies orphans for writer Phase 8)
    _scan_referenced_layouts(game_path, plan)

    # Phase 8: C source patch targets
    _scan_c_patch_targets(game_path, plan)

    return plan


# ============================================================
# PHASE 1: MAPS
# ============================================================

def _scan_maps(game_path, plan):
    """Identify vanilla vs custom maps.  Everything vanilla gets nuked.

    Name-based classification from classify_maps() handles FRLG and other
    expansion-added maps automatically — no positional reclassification needed.
    """
    vanilla, custom = classify_maps(game_path)

    plan.vanilla_maps = vanilla
    plan.custom_maps = custom
    plan.map_groups_data = load_map_groups(game_path) or {}
    plan.nuke_maps = set(vanilla)
    plan.keep_maps = set(custom)

    # Protect engine-required maps
    for keep_map in _ENGINE_KEEP_MAPS:
        if keep_map in plan.nuke_maps:
            plan.nuke_maps.discard(keep_map)
            plan.keep_maps.add(keep_map)

    # Engine deps: we need at least one valid map in keep_maps.
    # InsideOfTruck (from _ENGINE_KEEP_MAPS) always satisfies this.
    if not plan.keep_maps:
        plan.errors.append(
            "No maps to keep -- scorch needs at least one map "
            "(InsideOfTruck should be present)"
        )


# ============================================================
# PHASE 2: TRAINERS
# ============================================================

def _scan_trainers(game_path, plan):
    """Split trainers by the vanilla threshold."""
    vanilla, custom = _classify_trainers(game_path)
    plan.vanilla_trainers = vanilla
    plan.custom_trainers = custom


# ============================================================
# PHASE 3: ENCOUNTERS
# ============================================================

def _scan_encounters(game_path, plan):
    """Split encounters by whether their map is vanilla."""
    all_enc = get_all_encounters(game_path)
    for enc in all_enc:
        map_const = enc.get("map", "")
        folder = _map_const_to_folder(map_const)
        if folder in plan.vanilla_maps and folder not in plan.keep_maps:
            plan.vanilla_encounters.append(enc)
        else:
            plan.custom_encounters.append(enc)


# ============================================================
# PHASE 4: SCRIPTS
# ============================================================

def _scan_scripts(game_path, plan):
    """Find vanilla .inc scripts in data/scripts/.

    A script is vanilla if it is NOT referenced by any custom map script.
    We also build a set of labels used by custom content, so the patcher
    knows which event_scripts.s includes to keep.
    """
    scripts_dir = os.path.join(game_path, "data", "scripts")
    if not os.path.isdir(scripts_dir):
        return

    # Collect all custom map script content for cross-referencing
    custom_content = _collect_custom_script_content(game_path, plan.custom_maps)

    for inc_file in sorted(_glob.glob(os.path.join(scripts_dir, "*.inc"))):
        filename = os.path.basename(inc_file)
        labels = _extract_labels(inc_file)

        # Check if any label is referenced by custom content
        referenced = False
        for label in labels:
            if label in custom_content:
                referenced = True
                plan.custom_script_labels.add(label)

        if not referenced:
            plan.vanilla_scripts.append({
                "path": inc_file,
                "filename": filename,
            })


def _collect_custom_script_content(game_path, custom_maps):
    """Extract all identifiers from custom map script files as a set.

    Returns a set of word-tokens so that label lookups use exact set
    membership instead of substring matching against a raw string.
    """
    identifiers = set()
    maps_dir = os.path.join(game_path, "data", "maps")
    for map_name in custom_maps:
        map_dir = os.path.join(maps_dir, map_name)
        if not os.path.isdir(map_dir):
            continue
        for ext in ("*.inc", "*.pory"):
            for f in _glob.glob(os.path.join(map_dir, "scripts", ext)):
                try:
                    with open(f, "r", encoding="utf-8", errors="replace") as fh:
                        identifiers.update(re.findall(r"\w+", fh.read()))
                except OSError:
                    pass
            # Also check scripts directly in map dir
            for f in _glob.glob(os.path.join(map_dir, ext)):
                try:
                    with open(f, "r", encoding="utf-8", errors="replace") as fh:
                        identifiers.update(re.findall(r"\w+", fh.read()))
                except OSError:
                    pass
    return identifiers


def _extract_labels(inc_path):
    """Extract all script labels (Name: or Name::) from an .inc file."""
    labels = set()
    try:
        with open(inc_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"^(\w+):{1,2}\s*$", line)
                if m:
                    labels.add(m.group(1))
    except OSError:
        pass
    return labels


# ============================================================
# PHASE 5: TILESETS
# ============================================================

def _scan_tilesets(game_path, plan):
    """Identify vanilla vs custom tilesets.

    A tileset is custom if any custom map uses it.
    gTileset_General is always kept (engine requirement).
    """
    # Build map -> layout -> tileset mapping
    layouts_data = load_layouts(game_path)
    if not layouts_data:
        return

    # Build layout_id -> (primary_tileset, secondary_tileset)
    layout_tilesets = {}
    layouts = layouts_data.get("layouts", [])
    for layout in layouts:
        lid = layout.get("id", "")
        primary = layout.get("primary_tileset", "")
        secondary = layout.get("secondary_tileset", "")
        layout_tilesets[lid] = (primary, secondary)

    # Build map_name -> layout_id by reading each map's map.json
    custom_tilesets = set()
    custom_tilesets.add("gTileset_General")  # always keep
    vanilla_tilesets = set()
    all_tilesets = set()

    for map_name in plan.custom_maps | plan.vanilla_maps:
        mdata = load_map_json(game_path, map_name)
        if not mdata:
            continue

        layout_id = mdata.get("layout", "")
        ts_pair = layout_tilesets.get(layout_id, (None, None))
        for ts in ts_pair:
            if not ts:
                continue
            all_tilesets.add(ts)
            if map_name in plan.custom_maps:
                custom_tilesets.add(ts)

    # Anything not used by custom maps is vanilla
    for ts in all_tilesets:
        if ts in custom_tilesets:
            continue
        vanilla_tilesets.add(ts)

    # Resolve to directory info from graphics.h
    graphics_h = os.path.join(game_path, "src", "data", "tilesets", "graphics.h")
    ts_symbol_to_dir = _build_tileset_dir_map(graphics_h)
    ts_data_root = os.path.join(game_path, "data", "tilesets", "secondary")

    for ts_symbol in vanilla_tilesets:
        # Strip "gTileset_" prefix to get symbol name
        sym = ts_symbol.replace("gTileset_", "")
        dir_name = ts_symbol_to_dir.get(sym, sym.lower())
        ts_path = os.path.join(ts_data_root, dir_name)
        plan.vanilla_tilesets.append({
            "symbol": ts_symbol,
            "dir_name": dir_name,
            "path": ts_path,
        })

    for ts_symbol in custom_tilesets:
        sym = ts_symbol.replace("gTileset_", "")
        plan.custom_tilesets.append(ts_symbol)


def _build_tileset_dir_map(graphics_h_path):
    """Parse graphics.h to map tileset symbol names to directory names.

    Returns dict: symbol_name (e.g. "Petalburg") -> dir_name (e.g. "petalburg").
    """
    result = {}
    if not os.path.isfile(graphics_h_path):
        return result
    try:
        with open(graphics_h_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                # Pattern: gTilesetTiles_<Name>[] = INCBIN_U32("data/tilesets/secondary/<dir>/tiles.4bpp.lz");
                m = re.search(
                    r"gTilesetTiles_(\w+)\[\].*?data/tilesets/secondary/(\w+)/",
                    line
                )
                if m:
                    result[m.group(1)] = m.group(2)
    except OSError:
        pass
    return result


# ============================================================
# PHASE 6: HEAL LOCATIONS
# ============================================================

def _scan_heal_locations(game_path, plan):
    """Identify vanilla vs custom heal locations.

    Parses the enum in heal_locations.h (auto-generated from JSON).
    Skips HEAL_LOCATION_NONE and NUM_HEAL_LOCATIONS.
    Classifies by checking if the location name contains a custom map fragment.
    """
    heal_path = os.path.join(game_path, "include", "constants", "heal_locations.h")
    if not os.path.isfile(heal_path):
        # The header is auto-generated by the build system from the JSON.
        # On a fresh clone it won't exist yet.  Fall back to scanning the
        # JSON directly to classify heal locations.
        _scan_heal_locations_from_json(game_path, plan)
        return

    # Build UPPER_SNAKE fragments for custom maps + keep_maps
    custom_fragments = set()
    for map_name in plan.custom_maps | plan.keep_maps:
        upper = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", map_name).upper()
        custom_fragments.add(upper)

    # Parse enum members from the header
    members = _parse_heal_enum(heal_path)

    for idx, name in enumerate(members):
        is_custom = _heal_matches_custom(name, custom_fragments)
        if is_custom:
            plan.custom_heal_ids.append((name, idx + 1))
        else:
            plan.vanilla_heal_ids.append((name, idx + 1))


def _parse_heal_enum(heal_path):
    """Extract HEAL_LOCATION_* member names from the enum in heal_locations.h.

    Returns list of member names in order, excluding HEAL_LOCATION_NONE
    and NUM_HEAL_LOCATIONS.
    """
    members = []
    in_enum = False
    try:
        with open(heal_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("enum"):
                    in_enum = True
                    continue
                if not in_enum:
                    continue
                if stripped.startswith("};"):
                    break
                # Extract member name (may have trailing comma or comment)
                m = re.match(r"(HEAL_LOCATION_\w+)", stripped)
                if m:
                    name = m.group(1)
                    if name == "HEAL_LOCATION_NONE":
                        continue
                    members.append(name)
                # Also skip NUM_HEAL_LOCATIONS
                if stripped.startswith("NUM_HEAL_LOCATIONS"):
                    continue
    except OSError:
        pass
    return members


def _heal_matches_custom(heal_name, custom_fragments):
    """Check if a heal location name matches any custom map fragment."""
    loc_upper = heal_name.replace("HEAL_LOCATION_", "")
    for frag in custom_fragments:
        if loc_upper.startswith(frag):
            return True
    return False


def _scan_heal_locations_from_json(game_path, plan):
    """Fallback: classify heal locations from the JSON when the header
    hasn't been generated yet (fresh clone, never built).

    Reads heal_locations.json and classifies each entry by checking
    whether its map field references a vanilla (nuked) or custom map.
    """
    json_path = os.path.join(game_path, "src", "data", "heal_locations.json")
    if not os.path.isfile(json_path):
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    locations = data.get("heal_locations", [])
    if not locations:
        return

    # Build a set of vanilla MAP_* constants from nuke_maps
    vanilla_map_consts = set()
    for map_name in plan.nuke_maps:
        vanilla_map_consts.add(f"MAP_{re.sub(r'(?<=[a-z])(?=[A-Z])', '_', map_name).upper()}")

    for idx, loc in enumerate(locations):
        loc_id = loc.get("id", "")
        loc_map = loc.get("map", "")
        if not loc_id:
            continue

        # A heal location is custom if its map isn't being nuked
        is_vanilla = loc_map in vanilla_map_consts
        if is_vanilla:
            plan.vanilla_heal_ids.append((loc_id, idx + 1))
        else:
            plan.custom_heal_ids.append((loc_id, idx + 1))


def _scan_vanilla_localids(game_path, plan):
    """Extract named LOCALID_* constants from vanilla map JSONs and scripts.

    The build system generates include/constants/map_event_ids.h from
    data/maps/*/map.json.  On fresh clones this header may be minimal
    (only InsideOfTruck).  We scan the map JSONs directly to build a
    dict of named LOCALIDs and their sequential values, so the patcher
    can generate stubs after the writer deletes the map directories.

    Also scans .inc files for .equ LOCALID_* definitions (used in older
    expansion versions where LOCALIDs are assembly-local equates).
    """
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return

    equ_pat = re.compile(r'\.(?:equ|set)\s+(LOCALID_\w+)\s*,\s*(\d+)')

    for map_name in plan.nuke_maps:
        map_dir = os.path.join(maps_dir, map_name)

        # Source A: map.json object events (named LOCALIDs)
        map_json = os.path.join(map_dir, "map.json")
        if os.path.isfile(map_json):
            try:
                with open(map_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for idx, evt in enumerate(data.get("object_events", []), start=1):
                    local_id = evt.get("local_id")
                    if local_id and isinstance(local_id, str) \
                            and local_id.startswith("LOCALID_"):
                        plan.vanilla_localids[local_id] = idx
            except (OSError, json.JSONDecodeError):
                pass

        # Source B: .inc files with .equ/.set LOCALID_* definitions
        if os.path.isdir(map_dir):
            for fname in os.listdir(map_dir):
                if not fname.endswith(".inc"):
                    continue
                try:
                    with open(os.path.join(map_dir, fname), "r",
                              encoding="utf-8", errors="replace") as f:
                        for line in f:
                            m = equ_pat.match(line.strip())
                            if m:
                                plan.vanilla_localids[m.group(1)] = int(m.group(2))
                except OSError:
                    pass


# ============================================================
# PHASE 7: MAPSECs
# ============================================================

def _scan_mapsecs(game_path, plan):
    """Identify vanilla vs custom MAPSECs from region_map_sections.json.

    A MAPSEC is custom if it is referenced by a surviving (kept) map.
    System MAPSECs (NONE, DYNAMIC, INSIDE_OF_TRUCK) are always preserved.
    Everything else is vanilla and will be removed.
    """
    rms_path = os.path.join(
        game_path, "src", "data", "region_map", "region_map_sections.json"
    )
    if not os.path.isfile(rms_path):
        return

    try:
        with open(rms_path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        plan.errors.append("Failed to parse region_map_sections.json")
        return

    # Key name varies by version: "id" (v1.9+) or "map_section" (older)
    all_ids = set()
    for s in data.get("map_sections", []):
        sid = s.get("id") or s.get("map_section")
        if sid:
            all_ids.add(sid)

    # Collect MAPSECs referenced by surviving maps
    referenced = _collect_surviving_mapsecs(game_path, plan.keep_maps)

    # System MAPSECs — always preserved regardless of reference
    always_keep = set(plan.system_mapsecs)
    always_keep.add("MAPSEC_INSIDE_OF_TRUCK")

    plan.custom_mapsecs = (referenced | always_keep) & all_ids
    plan.vanilla_mapsecs = all_ids - plan.custom_mapsecs


def _collect_surviving_mapsecs(game_path, keep_maps):
    """Read map.json for each surviving map, collect referenced MAPSECs."""
    referenced = set()
    maps_dir = os.path.join(game_path, "data", "maps")
    for map_name in keep_maps:
        mdata = load_map_json(game_path, map_name)
        if not mdata:
            continue
        rms = mdata.get("region_map_section", "")
        if rms:
            referenced.add(rms)
    return referenced


# ============================================================
# PHASE 7b: REFERENCED LAYOUTS
# ============================================================

_SETMAPLAYOUTINDEX_PAT = re.compile(r'\bsetmaplayoutindex\s+(LAYOUT_\w+)')


def _scan_referenced_layouts(game_path, plan):
    """Identify which layouts are referenced by surviving maps.

    A layout is referenced if:
    - Any surviving map's map.json has "layout": "LAYOUT_*" pointing to it, OR
    - Any surviving map's script files (.inc, .pory) contain
      ``setmaplayoutindex LAYOUT_*``

    Everything else in layouts.json is orphaned and will be removed by the
    writer's Phase 8.
    """
    referenced = set()
    maps_dir = os.path.join(game_path, "data", "maps")

    for map_name in plan.keep_maps:
        # Source A: map.json "layout" field
        mdata = load_map_json(game_path, map_name)
        if mdata:
            layout_id = mdata.get("layout", "")
            if layout_id:
                referenced.add(layout_id)

        # Source B: script files — setmaplayoutindex LAYOUT_*
        map_dir = os.path.join(maps_dir, map_name)
        if not os.path.isdir(map_dir):
            continue
        for fname in os.listdir(map_dir):
            if not fname.endswith((".inc", ".pory")):
                continue
            try:
                with open(os.path.join(map_dir, fname), "r",
                          encoding="utf-8", errors="replace") as f:
                    for line in f:
                        m = _SETMAPLAYOUTINDEX_PAT.search(line)
                        if m:
                            referenced.add(m.group(1))
            except OSError:
                pass

    # Load all layout IDs from layouts.json
    data = load_layouts(game_path)
    all_layout_ids = set()
    if data:
        for layout in data.get("layouts", []):
            lid = layout.get("id", "")
            if lid:
                all_layout_ids.add(lid)

    plan.referenced_layouts = referenced
    plan.orphaned_layouts = all_layout_ids - referenced


# ============================================================
# PHASE 8: C SOURCE PATCH TARGETS
# ============================================================

# Files that definitely contain hardcoded vanilla references
_C_PATCH_FILES = [
    ("src/battle_setup.c",       "Rematch trainer table with vanilla MAP_*/TRAINER_* refs"),
    ("src/roamer.c",             "Roaming pokemon route table with vanilla MAP_NUM() refs"),
    ("src/secret_base.c",        "Secret base map table with vanilla SECRET_BASE_* refs"),
    ("src/overworld.c",          "Music routing with hardcoded vanilla MAP_NUM() checks"),
    ("src/battle_pike.c",        "Battle Frontier with missing symbol declarations"),
    ("src/battle_pyramid.c",     "Battle Frontier with missing symbol declarations"),
    ("src/battle_tent.c",        "Battle Tent with missing layout declarations"),
    ("src/field_player_avatar.c", "Faraway Island with vanilla MAP_NUM() refs"),
    ("src/field_specials.c",     "Cycling road + SS Tidal with hardcoded vanilla MAP_NUM() refs"),
    ("src/pokemon_storage_system.c", "Wallpaper references"),
    ("src/region_map.c",         "Region map section layout with vanilla map sections"),
    ("src/map_name_popup.c",     "Map name popup themes with vanilla MAPSEC_* refs and KANTO_MAPSEC_COUNT math"),
    ("src/frontier_pass.c",      "Battle frontier map section checks"),
    ("src/landmark.c",           "Landmark names referencing vanilla MAPSEC_* constants"),
    ("src/post_battle_event_funcs.c", "GameClear() heal location references"),
    ("src/heal_location.c",      "Heal location functions referencing vanilla HEAL_LOCATION_* constants"),
    ("include/constants/rematches.h", "Rematch enum with vanilla trainer entries"),
    ("src/data/heal_locations.json", "Auto-generated heal location source data"),
    ("data/event_scripts.s",     "Vanilla event script .includes (keep gStdScripts intact)"),
    ("include/regions.h",        "GetRegionForSectionId uses KANTO_MAPSEC_START (v1.15.0+)"),
]


def _scan_c_patch_targets(game_path, plan):
    """Identify C source files that need patching."""
    for rel_path, reason in _C_PATCH_FILES:
        full_path = os.path.join(game_path, rel_path)
        if os.path.isfile(full_path):
            plan.c_patch_targets.append({
                "path": full_path,
                "rel_path": rel_path,
                "reason": reason,
            })

    # Also scan for additional files with MAP_* refs from nuked maps
    _scan_for_additional_refs(game_path, plan)


def _build_vanilla_layout_consts(game_path, plan):
    """Build set of LAYOUT_* constant names that will be removed.

    A layout is removed if its blockdata file lives in a vanilla map
    directory that Phoenix will delete.
    """
    data = load_layouts(game_path)
    if not data:
        return set()

    nuke_names = set()
    for map_name in plan.nuke_maps:
        nuke_names.add(map_name)

    removed = set()
    for layout in data.get("layouts", []):
        bd = layout.get("blockdata_filepath", "")
        if not bd:
            continue
        # Normalise path separators and extract the directory name.
        # Blockdata paths: "data/layouts/Route101/map.bin" or "data/maps/Route101/map.bin"
        parts = bd.replace("\\", "/").split("/")
        if len(parts) >= 3:
            dir_name = parts[2]  # e.g. "Route101" from "data/layouts/Route101/map.bin"
            if dir_name in nuke_names:
                layout_id = layout.get("id", "")
                if layout_id:
                    removed.add(layout_id)
    return removed


def _build_ref_patterns(plan):
    """Build compiled regex patterns for vanilla constant refs.

    Matches MAP_*, TRAINER_*, LAYOUT_*, HEAL_LOCATION_*, REMATCH_*,
    and MAPSEC_* references.
    Returns list of compiled regexes (may be empty).
    """
    patterns = []

    # MAP_GROUP/MAP_NUM/MAP_<const> patterns
    # Prefer constants extracted from map_groups.h (handles names like SS_TIDAL_CORRIDOR)
    vanilla_map_consts = getattr(plan, 'vanilla_map_consts_from_h', set())
    if not vanilla_map_consts:
        # Fallback: derive from folder names via CamelCase conversion
        for map_name in plan.nuke_maps:
            upper = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", map_name).upper()
            vanilla_map_consts.add(upper)
    if vanilla_map_consts:
        patterns.append(re.compile(
            r"\bMAP_(?:GROUP|NUM)\s*\(\s*(" + "|".join(re.escape(c) for c in vanilla_map_consts) + r")\s*\)"
            r"|\bMAP_(" + "|".join(re.escape(c) for c in vanilla_map_consts) + r")\b"
        ))
        # MATCH_MAP(CONST) without MAP_ prefix (v1.11.x follower_helper.c)
        patterns.append(re.compile(
            r"\bMATCH_MAP\s*\(\s*(" + "|".join(re.escape(c) for c in vanilla_map_consts) + r")\s*\)"
        ))

    # TRAINER_* patterns
    vanilla_trainer_consts = set()
    for const, _tid in plan.vanilla_trainers:
        vanilla_trainer_consts.add(const)
    if vanilla_trainer_consts:
        patterns.append(re.compile(
            r"\b(" + "|".join(re.escape(c) for c in vanilla_trainer_consts) + r")\b"
        ))

    # LAYOUT_* patterns
    vanilla_layout_consts = plan.vanilla_layout_consts
    if vanilla_layout_consts:
        patterns.append(re.compile(
            r"\b(" + "|".join(re.escape(c) for c in vanilla_layout_consts) + r")\b"
        ))

    # HEAL_LOCATION_* patterns
    vanilla_heal_consts = {name for name, _hid in getattr(plan, 'vanilla_heal_ids', set())}
    if vanilla_heal_consts:
        patterns.append(re.compile(
            r"\b(" + "|".join(re.escape(c) for c in vanilla_heal_consts) + r")\b"
        ))

    # REMATCH_* patterns (extracted from rematches.h before it's overwritten)
    vanilla_rematch_consts = getattr(plan, 'vanilla_rematch_consts', set())
    if vanilla_rematch_consts:
        patterns.append(re.compile(
            r"\b(" + "|".join(re.escape(c) for c in vanilla_rematch_consts) + r")\b"
        ))

    # MAPSEC_* patterns (vanilla region map sections)
    vanilla_mapsec_consts = getattr(plan, 'vanilla_mapsecs', set())
    if vanilla_mapsec_consts:
        patterns.append(re.compile(
            r"\b(" + "|".join(re.escape(c) for c in vanilla_mapsec_consts) + r")\b"
        ))

    return patterns


def _scan_for_additional_refs(game_path, plan):
    """Quick scan of src/ and include/ for files referencing nuked constants.

    Checks for vanilla MAP_*, TRAINER_*, REMATCH_*, HEAL_LOCATION_*,
    LAYOUT_*, and MAPSEC_* references.
    """
    # Discover vanilla layout constants and store on plan
    plan.vanilla_layout_consts = _build_vanilla_layout_consts(game_path, plan)

    # Union orphaned layouts (from Phase 7b reference scan) into the
    # layout constants set — safety net so the C patcher catches any
    # stray references to orphaned layout constants.
    plan.vanilla_layout_consts |= plan.orphaned_layouts

    # Extract vanilla MAP_* constants from map_groups.h (before mapjson overwrites it).
    # Parsing the header is more reliable than CamelCase folder-name conversion,
    # which fails on names like SSTidalCorridor -> SSTIDAL_CORRIDOR (should be SS_TIDAL_CORRIDOR).
    map_groups_h = os.path.join(game_path, "include", "constants", "map_groups.h")
    plan.vanilla_map_consts_from_h = set()
    try:
        with open(map_groups_h, "r", encoding="utf-8", errors="replace") as f:
            mg_content = f.read()
        # Extract all MAP_* constant names (without MAP_ prefix) from the enum
        all_map_consts = set()
        for m in re.finditer(r"\bMAP_(\w+)\s*=\s*\(", mg_content):
            const_suffix = m.group(1)  # e.g. SS_TIDAL_CORRIDOR
            if const_suffix not in ("GROUPS_COUNT", "UNDEFINED", "GROUP_COUNT"):
                all_map_consts.add(const_suffix)
        # Build set of custom map constant suffixes to exclude
        keep_consts = set()
        for map_name in plan.keep_maps:
            keep_consts.add(re.sub(r"(?<=[a-z])(?=[A-Z])", "_", map_name).upper())
        # Vanilla = all constants minus custom
        plan.vanilla_map_consts_from_h = all_map_consts - keep_consts
    except OSError:
        pass

    # Extract vanilla REMATCH_* constants from rematches.h (v1.14+) or
    # gym_leader_rematch.h (v1.9.x where enum is inline)
    rematches_path = os.path.join(game_path, "include", "constants", "rematches.h")
    glr_path = os.path.join(game_path, "include", "gym_leader_rematch.h")
    rematch_consts = set()
    for rp in (rematches_path, glr_path):
        try:
            with open(rp, "r", encoding="utf-8", errors="replace") as f:
                rc = f.read()
            rematch_consts |= set(re.findall(r"\b(REMATCH_\w+)\b", rc))
        except OSError:
            pass
    rematch_consts.discard("REMATCH_TABLE_ENTRIES")
    plan.vanilla_rematch_consts = rematch_consts

    patterns = _build_ref_patterns(plan)
    if not patterns:
        return

    known_paths = {t["path"] for t in plan.c_patch_targets}

    for root_dir in ("src", "include"):
        scan_root = os.path.join(game_path, root_dir)
        if not os.path.isdir(scan_root):
            continue
        for dirpath, _dirs, files in os.walk(scan_root):
            for fname in files:
                if not fname.endswith((".c", ".h")):
                    continue
                fpath = os.path.join(dirpath, fname)
                if fpath in known_paths:
                    continue
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    for pattern in patterns:
                        if pattern.search(content):
                            rel = os.path.relpath(fpath, game_path)
                            plan.c_patch_targets.append({
                                "path": fpath,
                                "rel_path": rel,
                                "reason": "Contains vanilla MAP_*/TRAINER_*/LAYOUT_* references",
                            })
                            known_paths.add(fpath)
                            break
                except OSError:
                    pass
