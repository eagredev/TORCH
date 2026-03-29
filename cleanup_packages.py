"""SCORCH Packages — town-cluster evaluation for bulk vanilla removal.

Groups vanilla maps into packages (town clusters) so that mutual references
within a package don't block removal.  When evaluating, all maps across all
selected packages form the proposed removal set — a map is only BLOCKED if
referenced by content *outside* that set.

Pure analysis layer: consumes scanner data, produces Package objects.
Knows nothing about file I/O or UI.
"""
# TORCH_MODULE: SCORCH Packages
# TORCH_GROUP: Tools
import os
import re
from collections import deque

from torch.cleanup_scanner import (
    RemovalPlan, RemovalItem, SAFE, BLOCKED,
    build_map_const_lookup, find_map_c_source_refs,
    find_layout_c_source_refs,
    map_const_to_folder,
    build_warp_connection_index,
)
from torch.project_files import (
    classify_maps, load_map_groups, load_layouts, load_map_json,
    load_wild_encounters, folder_to_map_const,
)


# ============================================================
# PACKAGE DATA MODEL
# ============================================================

ALL_SAFE = "ALL_SAFE"
PARTIAL = "PARTIAL"
PKG_BLOCKED = "BLOCKED"


class Package:
    """A cluster of related vanilla maps evaluated as a unit."""

    __slots__ = ('name', 'display_name', 'anchor', 'maps',
                 'status', 'safe_count', 'blocked_count',
                 'external_blockers', 'depends_on', 'depended_by',
                 'content_summary')

    def __init__(self, name, display_name, anchor, maps):
        self.name = name
        self.display_name = display_name
        self.anchor = anchor
        self.maps = list(maps)
        self.status = ALL_SAFE
        self.safe_count = len(maps)
        self.blocked_count = 0
        self.external_blockers = []   # list of {map, ref_type, ref_source}
        self.depends_on = set()       # package names
        self.depended_by = set()      # package names
        self.content_summary = {
            "trainers": 0, "encounters": 0,
            "tilesets": 0, "scripts": 0, "music": 0,
        }

    def __repr__(self):
        return f"Package({self.name!r}, {len(self.maps)} maps, {self.status})"


# ============================================================
# PACKAGE DISCOVERY
# ============================================================

def discover_packages(game_path, vanilla_maps, custom_maps, group_data):
    """Auto-discover town-cluster packages from game data.

    Returns list of Package objects covering every vanilla map.
    """
    const_to_name = build_map_const_lookup(game_path, group_data)

    # Phase A: find town anchors from Indoor group naming
    anchor_map = _find_town_anchors(group_data, vanilla_maps)
    all_anchors = set(anchor_map.keys())

    # Phase B: build adjacency graph
    # We need SEPARATE warp and connection indexes because BFS should
    # only follow warps (indoor entrances), NOT connections (route-to-route).
    # Connections create a massive web across the world map that would
    # cause one town to consume everything.
    warp_idx, conn_idx = build_warp_connection_index(
        game_path, vanilla_maps, const_to_name)
    # Make warp index symmetric for BFS: if A warps to B, add B->A too
    warp_sym = {}
    for src, dests in warp_idx.items():
        warp_sym.setdefault(src, set()).update(dests)
        for d in dests:
            warp_sym.setdefault(d, set()).add(src)

    # Build set of all indoor maps (assigned to specific anchors)
    # BFS must NOT claim indoor maps belonging to a different anchor.
    all_indoor = set()
    indoor_owner = {}  # map_name -> anchor
    for anchor_name, indoor_set in anchor_map.items():
        for m in indoor_set:
            all_indoor.add(m)
            indoor_owner[m] = anchor_name

    # IndoorDynamic maps (TradeCenter, UnionRoom, RecordCorner, etc.)
    # are shared hub maps that connect every PokemonCenter_2F together.
    # BFS must not traverse THROUGH them — they act as boundaries.
    dynamic_maps = set(group_data.get("gMapGroup_IndoorDynamic", []))

    # Phase C: BFS expansion from each anchor using WARPS ONLY.
    # This naturally picks up dungeons entered via warps (GraniteCave
    # from DewfordTown) but doesn't cascade across routes connected
    # via map connections.
    claimed = set()
    packages = []
    for anchor in sorted(anchor_map.keys()):
        indoor_maps = anchor_map[anchor]
        seeds = {anchor} | indoor_maps
        expanded = _expand_via_bfs(anchor, seeds, warp_sym, claimed,
                                   vanilla_maps, all_anchors,
                                   all_indoor, indoor_owner,
                                   dynamic_maps)
        claimed.update(expanded)
        display = _make_display_name(anchor)
        slug = _make_slug(anchor)
        pkg = Package(slug, display, anchor, sorted(expanded))
        packages.append(pkg)

    # Phase D: group unclaimed maps by prefix
    unclaimed = vanilla_maps - claimed
    if unclaimed:
        packages.extend(_group_unclaimed(unclaimed))

    return packages


def _find_town_anchors(group_data, vanilla_maps):
    """Find town/route anchors from Indoor group naming.

    Scan map_groups.json for groups matching gMapGroup_Indoor<Suffix>.
    Resolve <Suffix> to a town/route map. Skip mega-groups (Dungeons,
    Dynamic, SpecialArea).

    Returns dict: anchor_map_name -> set of indoor map names.
    """
    skip_suffixes = {"Dynamic"}
    anchor_map = {}  # anchor name -> set of indoor maps

    for group_name in group_data.get("group_order", []):
        if not group_name.startswith("gMapGroup_Indoor"):
            continue
        suffix = group_name[len("gMapGroup_Indoor"):]
        if not suffix or suffix in skip_suffixes:
            continue

        maps_in_group = set(group_data.get(group_name, []))
        anchor = _resolve_anchor(suffix, vanilla_maps)
        if anchor is None:
            continue

        # Indoor maps are the group contents (which don't include the anchor)
        indoor = maps_in_group & vanilla_maps
        anchor_map[anchor] = indoor

    return anchor_map


def _resolve_anchor(suffix, vanilla_maps):
    """Resolve an Indoor group suffix to the anchor map name.

    gMapGroup_IndoorPetalburg -> PetalburgCity
    gMapGroup_IndoorRoute104  -> Route104
    gMapGroup_IndoorRoute104Prototype -> Route104 (if Route104Prototype not found)
    """
    # Direct match: suffix IS a vanilla map (e.g. Route104)
    if suffix in vanilla_maps:
        return suffix

    # Try common town/city suffixes
    for town_suffix in ("City", "Town"):
        candidate = suffix + town_suffix
        if candidate in vanilla_maps:
            return candidate

    # Try trimming trailing qualifiers (e.g. Route104Prototype -> Route104)
    # Look for longest vanilla map that is a prefix of suffix
    best = None
    for vm in vanilla_maps:
        if suffix.startswith(vm) and (best is None or len(vm) > len(best)):
            best = vm
    if best:
        return best

    return None


def _merge_adjacency(warp_index, conn_index):
    """Merge warp and connection indexes into a single symmetric adjacency graph."""
    adj = {}  # name -> set of neighbor names
    for src, dests in warp_index.items():
        adj.setdefault(src, set()).update(dests)
        for d in dests:
            adj.setdefault(d, set()).add(src)
    for src, dests in conn_index.items():
        adj.setdefault(src, set()).update(dests)
        for d in dests:
            adj.setdefault(d, set()).add(src)
    return adj


def _expand_via_bfs(anchor, seeds, warp_index, claimed, vanilla_maps,
                    all_anchors=None, all_indoor=None,
                    indoor_owner=None, dynamic_maps=None):
    """BFS from anchor + seed maps through warp adjacency only.

    Only follows warp edges (not connections) so packages don't cascade
    across route-to-route connections. Only claims unclaimed vanilla maps.

    Stop conditions:
    1. Don't cross into another anchor (it forms its own package).
    2. Don't claim indoor maps belonging to a different anchor.
    3. Don't traverse THROUGH dynamic hub maps (TradeCenter, UnionRoom,
       etc.) — they connect every PokemonCenter_2F and would bridge
       across the entire world map.

    Returns the full set of maps in this package (seeds + reachable).
    """
    if all_anchors is None:
        all_anchors = set()
    if all_indoor is None:
        all_indoor = set()
    if indoor_owner is None:
        indoor_owner = {}
    if dynamic_maps is None:
        dynamic_maps = set()

    result = set()
    queue = deque()

    for s in seeds:
        if s in vanilla_maps and s not in claimed:
            result.add(s)
            queue.append(s)

    while queue:
        current = queue.popleft()
        # Don't traverse through dynamic hub maps (add them to the
        # package if directly connected, but don't follow THEIR warps)
        if current in dynamic_maps and current not in seeds:
            continue
        for neighbor in warp_index.get(current, set()):
            if neighbor in result or neighbor in claimed:
                continue
            if neighbor not in vanilla_maps:
                continue
            # Don't cross into another anchor (it forms its own package)
            if neighbor in all_anchors and neighbor != anchor:
                continue
            # Don't claim indoor maps belonging to a different anchor
            if neighbor in all_indoor:
                owner = indoor_owner.get(neighbor)
                if owner and owner != anchor:
                    continue
            result.add(neighbor)
            queue.append(neighbor)

    return result


def _group_unclaimed(unclaimed):
    """Group unclaimed maps by name prefix into packages.

    Maps with shared prefixes (AbandonedShip_*, BattleFrontier_*,
    Route101/Route102, ContestHall/ContestHallBeauty) form their own
    packages. Singletons go into "Miscellaneous".
    """
    # Phase 1: initial grouping by prefix
    prefix_groups = {}  # prefix -> list of maps
    for map_name in sorted(unclaimed):
        prefix = _extract_grouping_prefix(map_name)
        prefix_groups.setdefault(prefix, []).append(map_name)

    # Phase 2: merge singleton groups that share a CamelCase base.
    # E.g. ContestHall + ContestHallBeauty/Cool/etc -> one group.
    # SSTidalCorridor + SSTidalLowerDeck + SSTidalRooms -> one group.
    #
    # Strategy: split each name into CamelCase words, find the longest
    # common word-prefix between pairs, and merge when >= 2 words match.
    singles = {p for p, maps in prefix_groups.items() if len(maps) == 1}
    merge_target = {}  # original prefix -> canonical prefix

    single_names = sorted(singles)
    for i, name_a in enumerate(single_names):
        if name_a in merge_target:
            continue
        words_a = re.findall(r"[A-Z][a-z0-9]*|[A-Z]+(?=[A-Z][a-z]|\b)", name_a)
        if len(words_a) < 2:
            continue
        for name_b in single_names[i + 1:]:
            if name_b in merge_target:
                continue
            words_b = re.findall(r"[A-Z][a-z0-9]*|[A-Z]+(?=[A-Z][a-z]|\b)", name_b)
            # Find common word prefix length
            common = 0
            for wa, wb in zip(words_a, words_b):
                if wa == wb:
                    common += 1
                else:
                    break
            if common >= 2:
                # Merge both into the shared prefix
                shared = "".join(words_a[:common])
                canon_a = merge_target.get(name_a, name_a)
                # Always use the shortest prefix as canonical
                if len(shared) <= len(canon_a):
                    merge_target[name_a] = shared
                    merge_target[name_b] = shared

    # Also merge when one name is literally a prefix of another
    all_names = sorted(prefix_groups.keys())
    for i, name_a in enumerate(all_names):
        for name_b in all_names[i + 1:]:
            if name_b.startswith(name_a) and name_b != name_a:
                merge_target.setdefault(name_b, name_a)
            elif name_a.startswith(name_b) and name_a != name_b:
                merge_target.setdefault(name_a, name_b)

    # Apply merges — resolve chains
    def _resolve(name):
        seen = set()
        while name in merge_target and name not in seen:
            seen.add(name)
            name = merge_target[name]
        return name

    final_groups = {}
    for prefix, maps in prefix_groups.items():
        canonical = _resolve(prefix)
        final_groups.setdefault(canonical, []).extend(maps)

    for maps in final_groups.values():
        maps.sort()

    packages = []
    singletons = []
    for prefix in sorted(final_groups.keys()):
        maps = final_groups[prefix]
        if len(maps) >= 2:
            display = _prefix_to_display(prefix)
            slug = prefix.lower()
            pkg = Package(slug, display, maps[0], maps)
            packages.append(pkg)
        else:
            singletons.extend(maps)

    if singletons:
        pkg = Package("miscellaneous", "Miscellaneous", singletons[0],
                       singletons)
        packages.append(pkg)

    return packages


def _extract_grouping_prefix(map_name):
    """Extract the grouping prefix from a map name.

    AbandonedShip_Room1   -> AbandonedShip
    Route101              -> Route (groups all routes together)
    ContestHallBeauty     -> ContestHall
    BattlePyramidSquare01 -> BattlePyramidSquare
    SSTidalCorridor       -> SSTidal
    """
    # If there's an underscore, use everything before first underscore
    if "_" in map_name:
        return map_name.split("_")[0]

    # Strip trailing digits: Route101 -> Route
    base = re.sub(r"\d+$", "", map_name)
    if base and base != map_name:
        return base

    # For PascalCase names without underscores or trailing digits,
    # return as-is. The grouping step will naturally collect identical
    # names, and the 2-or-more threshold handles the rest.
    return map_name


def _make_display_name(anchor):
    """Convert PetalburgCity -> Petalburg City, Route104 -> Route 104."""
    # Insert space before capitals that follow lowercase or before digits
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", anchor)
    name = re.sub(r"([A-Za-z])(\d)", r"\1 \2", name)
    return name


def _make_slug(anchor):
    """Convert PetalburgCity -> petalburg, Route104 -> route104."""
    # Strip City/Town suffix, lowercase
    name = anchor
    for suffix in ("City", "Town"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    return name.lower()


def _prefix_to_display(prefix):
    """Convert a CamelCase prefix to a display name.

    AbandonedShip -> Abandoned Ship
    BattleFrontier -> Battle Frontier
    SecretBase -> Secret Bases
    SSTidal -> SS Tidal
    """
    # Handle SS prefix (SSTidal -> SS Tidal)
    name = re.sub(r"^SS([A-Z])", r"SS \1", prefix)
    # Standard CamelCase splitting
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    name = re.sub(r"([A-Za-z])(\d)", r"\1 \2", name)
    # Add plural/suffix for certain known prefixes
    if prefix == "SecretBase":
        name += "s"
    elif prefix == "Route":
        name = "Standalone Routes"
    return name


# ============================================================
# PACKAGE EVALUATION (CO-DEPENDENCY RESOLUTION)
# ============================================================

def evaluate_packages(game_path, packages, selected_names,
                      vanilla_maps, custom_maps, indexes):
    """Evaluate packages given a proposed removal set.

    Args:
        packages: list of all Package objects
        selected_names: set of package names currently selected
        vanilla_maps: set of all vanilla map folder names
        custom_maps: set of all custom map folder names
        indexes: dict with pre-built indexes:
            warp_index: map_name -> set of dest map names
            connection_index: map_name -> set of connected map names
            c_source_refs: map_const -> [source_files]
            const_to_name: MAP_CONST -> folder name
            name_to_const: folder name -> MAP_CONST
            shared_targets: target_name -> set of maps sharing it

    Mutates each package's status, safe_count, blocked_count,
    external_blockers in place.
    """
    warp_index = indexes["warp_index"]
    conn_index = indexes["connection_index"]
    c_source_refs = indexes["c_source_refs"]
    map_layout_c_refs = indexes.get("map_layout_c_refs", {})
    layout_to_maps = indexes.get("layout_to_maps", {})
    const_to_name = indexes["const_to_name"]
    name_to_const = indexes["name_to_const"]
    shared_targets = indexes.get("shared_targets", {})

    # Build proposed removal set from all selected packages
    proposed_removal = set()
    for pkg in packages:
        if pkg.name in selected_names:
            proposed_removal.update(pkg.maps)

    # Build set of all kept maps (everything not in removal set)
    all_vanilla = set(vanilla_maps)
    kept_vanilla = all_vanilla - proposed_removal

    # Phase 1: Initial per-map evaluation — which maps have external blockers?
    map_status = {}  # map_name -> SAFE or BLOCKED
    map_blockers = {}  # map_name -> list of blocker dicts

    for pkg in packages:
        if pkg.name not in selected_names:
            continue
        for map_name in pkg.maps:
            blockers = _check_map_external_refs(
                map_name, proposed_removal, kept_vanilla, custom_maps,
                warp_index, conn_index, c_source_refs,
                name_to_const, const_to_name, shared_targets,
                game_path, map_layout_c_refs, layout_to_maps)
            if blockers:
                map_status[map_name] = BLOCKED
                map_blockers[map_name] = blockers
            else:
                map_status[map_name] = SAFE
                map_blockers[map_name] = []

    # Phase 2: Reverse-reference post-pass (fixed-point cascade).
    _reverse_ref_cascade(map_status, map_blockers, warp_index, conn_index,
                         shared_targets, const_to_name, game_path,
                         layout_to_maps, kept_vanilla)

    # Phase 3: Compute package statuses from final map statuses
    for pkg in packages:
        pkg.external_blockers = []
        safe = 0
        blocked = 0

        if pkg.name in selected_names:
            for map_name in pkg.maps:
                status = map_status.get(map_name, SAFE)
                if status == BLOCKED:
                    blocked += 1
                    pkg.external_blockers.extend(
                        map_blockers.get(map_name, []))
                else:
                    safe += 1
        else:
            # Unselected packages: evaluate normally (all maps in
            # proposed_removal are from selected packages only)
            for map_name in pkg.maps:
                blockers = _check_map_external_refs(
                    map_name, proposed_removal, kept_vanilla, custom_maps,
                    warp_index, conn_index, c_source_refs,
                    name_to_const, const_to_name, shared_targets,
                    game_path, map_layout_c_refs, layout_to_maps)
                if blockers:
                    blocked += 1
                    pkg.external_blockers.extend(blockers)
                else:
                    safe += 1

        pkg.safe_count = safe
        pkg.blocked_count = blocked

        if blocked == 0:
            pkg.status = ALL_SAFE
        elif safe > 0:
            pkg.status = PARTIAL
        else:
            pkg.status = PKG_BLOCKED


def _check_map_external_refs(map_name, proposed_removal, kept_vanilla,
                             custom_maps, warp_index, conn_index,
                             c_source_refs, name_to_const, const_to_name,
                             shared_targets, game_path,
                             map_layout_c_refs=None, layout_to_maps=None):
    """Check if a map has references from outside the proposed removal set.

    Returns list of blocker dicts: {map, ref_type, ref_source}.
    Empty list = safe to remove.
    """
    blockers = []

    map_const = name_to_const.get(map_name, "")

    # 1a. MAP_* C source hardcoded refs — always blocks
    if map_const and map_const in c_source_refs:
        for src_file in c_source_refs[map_const]:
            blockers.append({
                "map": map_name,
                "ref_type": "c_source",
                "ref_source": src_file,
            })

    # 1b. LAYOUT_* C source hardcoded refs — blocks if removing this map
    #     would eliminate the layout constant (all maps sharing it are removed).
    #     Multiple maps can share the same LAYOUT_*; the constant only
    #     disappears when every map using it is removed.
    if map_layout_c_refs and layout_to_maps:
        for lid, src_files in map_layout_c_refs.get(map_name, []):
            # Check if any map sharing this layout survives outside removal set
            co_users = layout_to_maps.get(lid, set())
            surviving = co_users - proposed_removal
            if not surviving:
                # All maps using this layout are being removed — constant dies
                for src_file in src_files:
                    blockers.append({
                        "map": map_name,
                        "ref_type": "c_source_layout",
                        "ref_source": src_file,
                    })

    # 2. Custom map warps to this map — always blocks
    for custom_map in custom_maps:
        if custom_map in warp_index:
            if map_name in warp_index[custom_map]:
                blockers.append({
                    "map": map_name,
                    "ref_type": "custom_warp",
                    "ref_source": custom_map,
                })

    # 3. Custom map connections to this map — always blocks
    for custom_map in custom_maps:
        if custom_map in conn_index:
            if map_name in conn_index[custom_map]:
                blockers.append({
                    "map": map_name,
                    "ref_type": "custom_connection",
                    "ref_source": custom_map,
                })

    # 4. Custom map script references — always blocks
    const_form = folder_to_map_const(map_name)
    maps_dir = os.path.join(game_path, "data", "maps")
    for custom_map in custom_maps:
        for fname in ("scripts.inc", "scripts.pory"):
            fpath = os.path.join(maps_dir, custom_map, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if const_form in content:
                    blockers.append({
                        "map": map_name,
                        "ref_type": "custom_script",
                        "ref_source": custom_map,
                    })
                    break
            except OSError:
                continue

    # 5. Kept vanilla map warps/connections to this map — blocks
    for kept_map in kept_vanilla:
        if kept_map in warp_index and map_name in warp_index[kept_map]:
            blockers.append({
                "map": map_name,
                "ref_type": "kept_warp",
                "ref_source": kept_map,
            })
        if kept_map in conn_index and map_name in conn_index[kept_map]:
            blockers.append({
                "map": map_name,
                "ref_type": "kept_connection",
                "ref_source": kept_map,
            })

    # 6. Shared events/scripts — blocks if a kept map shares this map's data
    if map_name in shared_targets:
        sharers = shared_targets[map_name]
        kept_sharers = sharers & kept_vanilla
        for sharer in kept_sharers:
            blockers.append({
                "map": map_name,
                "ref_type": "shared_events",
                "ref_source": sharer,
            })

    # NOTE: vanilla maps INSIDE proposed_removal referencing this map
    # are intentionally NOT blockers — that's the whole point of packages.

    return blockers


_MAP_LAYOUT_CONST_RE = re.compile(r"\b(?:MAP|LAYOUT)_[A-Z][A-Z0-9_]+\b")


def _scan_script_map_refs(maps_dir, map_name, const_to_name,
                          layout_to_maps=None):
    """Scan a map's script/event files for MAP_* and LAYOUT_* references.

    Returns a set of map folder names referenced by this map's scripts.
    Used by the reverse-reference post-pass to catch script-level
    cross-references that aren't captured by the warp/connection indexes.

    Args:
        maps_dir: path to data/maps/
        map_name: folder name of the map to scan
        const_to_name: dict MAP_CONST -> folder name
        layout_to_maps: dict LAYOUT_ID -> set of map folder names
    """
    if layout_to_maps is None:
        layout_to_maps = {}
    ref_names = set()
    map_dir = os.path.join(maps_dir, map_name)
    if not os.path.isdir(map_dir):
        return ref_names

    for fname in ("scripts.inc", "scripts.pory"):
        fpath = os.path.join(map_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue
        for const in _MAP_LAYOUT_CONST_RE.findall(content):
            if const.startswith("MAP_"):
                folder = const_to_name.get(const)
                if folder and folder != map_name:
                    ref_names.add(folder)
            elif const.startswith("LAYOUT_"):
                # LAYOUT_* refs: all maps using this layout are needed
                for folder in layout_to_maps.get(const, set()):
                    if folder != map_name:
                        ref_names.add(folder)

    return ref_names


def _reverse_ref_cascade(map_status, map_blockers, warp_index, conn_index,
                         shared_targets, const_to_name, game_path,
                         layout_to_maps=None, kept_vanilla=None):
    """Iterative reverse-reference post-pass (fixed-point cascade).

    If a kept map (staying behind) warps/connects/scripts to a SAFE map
    (being removed), the SAFE map must be downgraded to BLOCKED —
    otherwise the kept map's events.inc will reference undefined
    MAP_* or LAYOUT_* constants after removal.

    Kept maps include:
    - BLOCKED maps within map_status (maps in selected packages that
      can't be removed)
    - ALL vanilla maps outside map_status (maps from unselected packages
      or maps not in any package) — passed via kept_vanilla

    Iterates until no more downgrades occur. Mutates map_status and
    map_blockers in place.
    """
    if layout_to_maps is None:
        layout_to_maps = {}
    if kept_vanilla is None:
        kept_vanilla = set()
    maps_dir = os.path.join(game_path, "data", "maps")
    script_ref_cache = {}  # map_name -> set of referenced folder names

    # Maps outside map_status that survive removal — these are kept vanilla
    # maps from unselected packages (or not in any package). They never
    # change status but their warp/connection/script refs can block SAFE maps.
    outside_kept = kept_vanilla - set(map_status.keys())

    for _iteration in range(50):  # safety cap
        safe_maps = {m for m, s in map_status.items() if s == SAFE}
        blocked_maps = {m for m, s in map_status.items() if s == BLOCKED}
        if not safe_maps:
            break

        # All kept maps whose refs must be respected: BLOCKED maps in
        # map_status PLUS all surviving maps outside the evaluation set.
        all_kept = blocked_maps | outside_kept

        newly_blocked = set()

        for bmap in all_kept:
            # Warps: does this kept map warp to any safe map?
            for dest in warp_index.get(bmap, set()):
                if dest in safe_maps:
                    newly_blocked.add(dest)

            # Connections: does this kept map connect to any safe map?
            for dest in conn_index.get(bmap, set()):
                if dest in safe_maps:
                    newly_blocked.add(dest)

            # Script references: MAP_* and LAYOUT_* constants in .inc/.pory
            if bmap not in script_ref_cache:
                script_ref_cache[bmap] = _scan_script_map_refs(
                    maps_dir, bmap, const_to_name, layout_to_maps)
            for ref_name in script_ref_cache[bmap]:
                if ref_name in safe_maps:
                    newly_blocked.add(ref_name)

        # Shared events: if a SAFE map's events are shared by a kept map
        for target, sharers in shared_targets.items():
            if target in safe_maps and sharers & all_kept:
                newly_blocked.add(target)

        if not newly_blocked:
            break  # fixed point reached

        for m in newly_blocked:
            map_status[m] = BLOCKED
            map_blockers.setdefault(m, []).append({
                "map": m,
                "ref_type": "reverse_ref",
                "ref_source": "Referenced by kept map staying behind",
            })


def build_indexes(game_path, vanilla_maps, custom_maps, group_data):
    """Build all indexes needed for package evaluation.

    Returns a dict of indexes suitable for passing to evaluate_packages().
    """
    const_to_name = build_map_const_lookup(game_path, group_data)
    name_to_const = {v: k for k, v in const_to_name.items()}
    vanilla_const_set = {name_to_const[m] for m in vanilla_maps
                         if m in name_to_const}

    warp_index, conn_index = build_warp_connection_index(
        game_path, vanilla_maps | custom_maps, const_to_name)
    c_source_refs = find_map_c_source_refs(game_path, vanilla_const_set)

    # Build LAYOUT_* C source refs: layout_id -> [source_files]
    # and layout_to_maps: layout_id -> set of map_names (multiple maps can share a layout)
    layout_c_refs, layout_to_maps = find_layout_c_source_refs(
        game_path, vanilla_maps)

    # Build reverse: map_name -> list of (layout_id, [source_files])
    # for layouts that are referenced in C source
    map_layout_c_refs = {}  # map_name -> [(layout_id, [source_files])]
    for lid, src_files in layout_c_refs.items():
        for mname in layout_to_maps.get(lid, set()):
            map_layout_c_refs.setdefault(mname, []).append((lid, src_files))

    # Build shared events/scripts targets
    shared_targets = _build_shared_targets(game_path, vanilla_maps)

    return {
        "warp_index": warp_index,
        "connection_index": conn_index,
        "c_source_refs": c_source_refs,
        "layout_c_refs": layout_c_refs,
        "layout_to_maps": layout_to_maps,
        "map_layout_c_refs": map_layout_c_refs,
        "const_to_name": const_to_name,
        "name_to_const": name_to_const,
        "shared_targets": shared_targets,
    }


def _build_shared_targets(game_path, vanilla_maps):
    """Build shared_events_map/shared_scripts_map target index.

    Returns dict: target_name -> set of maps that share it.
    """
    shared_targets = {}
    for map_name in vanilla_maps:
        mdata = load_map_json(game_path, map_name)
        if not mdata:
            continue
        for key in ("shared_events_map", "shared_scripts_map"):
            target = mdata.get(key, "")
            if target:
                shared_targets.setdefault(target, set()).add(map_name)
    return shared_targets


# ============================================================
# CROSS-PACKAGE DEPENDENCIES
# ============================================================

def compute_cross_package_deps(packages, warp_index, connection_index):
    """Compute depends_on / depended_by between packages.

    If a map in Package A warps/connects to a map in Package B,
    record A.depends_on B and B.depended_by A.
    """
    # Build map -> package name lookup
    map_to_pkg = {}
    for pkg in packages:
        for m in pkg.maps:
            map_to_pkg[m] = pkg.name

    pkg_by_name = {pkg.name: pkg for pkg in packages}

    for pkg in packages:
        pkg.depends_on = set()
        pkg.depended_by = set()

    for pkg in packages:
        for map_name in pkg.maps:
            # Check warps
            for dest in warp_index.get(map_name, set()):
                dest_pkg = map_to_pkg.get(dest)
                if dest_pkg and dest_pkg != pkg.name:
                    pkg.depends_on.add(dest_pkg)
                    pkg_by_name[dest_pkg].depended_by.add(pkg.name)
            # Check connections
            for dest in connection_index.get(map_name, set()):
                dest_pkg = map_to_pkg.get(dest)
                if dest_pkg and dest_pkg != pkg.name:
                    pkg.depends_on.add(dest_pkg)
                    pkg_by_name[dest_pkg].depended_by.add(pkg.name)


# ============================================================
# CONTENT COLLECTION
# ============================================================

def collect_package_content(game_path, package_maps, vanilla_maps,
                            custom_maps):
    """Find associated non-map content tied to package maps.

    Returns a RemovalPlan containing RemovalItems for trainers,
    encounters, tilesets, music, and scripts that are exclusively
    used by the package maps.
    """
    plan = RemovalPlan()
    package_set = set(package_maps)
    maps_dir = os.path.join(game_path, "data", "maps")

    # Add map RemovalItems for each package map
    for map_name in sorted(package_maps):
        item = RemovalItem(
            "maps", map_name, SAFE,
            data={"map_dir": os.path.join(maps_dir, map_name)},
        )
        plan.add(item)

    # Encounters: vanilla encounters for package maps
    _collect_encounters(game_path, package_set, plan)

    # Tilesets: tilesets exclusively used by package maps
    _collect_tilesets(game_path, package_set, vanilla_maps, plan)

    # Music: songs exclusively used by package maps
    _collect_music(game_path, package_set, vanilla_maps, plan)

    return plan


def _collect_encounters(game_path, package_maps, plan):
    """Add encounter RemovalItems for maps in the package."""
    data = load_wild_encounters(game_path)
    if not data:
        return

    for group in data.get("wild_encounter_groups", []):
        for enc in group.get("encounters", []):
            map_const = enc.get("map", "")
            folder = map_const_to_folder(map_const)
            if folder in package_maps:
                base_label = enc.get("base_label", "")
                display = map_const
                if base_label:
                    display += f" ({base_label})"
                item = RemovalItem(
                    "encounters", display, SAFE,
                    data={"map_const": map_const, "base_label": base_label,
                          "encounter_data": enc},
                )
                plan.add(item)


def _collect_tilesets(game_path, package_maps, vanilla_maps, plan):
    """Add tileset RemovalItems for tilesets used exclusively by package maps."""
    maps_dir = os.path.join(game_path, "data", "maps")
    tilesets_dir = os.path.join(game_path, "data", "tilesets", "secondary")

    if not os.path.isdir(tilesets_dir):
        return

    # Build layout_id -> tileset struct mapping
    layout_to_tileset = {}
    layouts_data = load_layouts(game_path)
    if not layouts_data:
        return
    for entry in layouts_data.get("layouts", []):
        lid = entry.get("id")
        sec = entry.get("secondary_tileset")
        if lid and sec:
            layout_to_tileset[lid] = sec

    # Build map -> layout mapping for all maps
    map_to_layout = {}
    if os.path.isdir(maps_dir):
        for map_name in os.listdir(maps_dir):
            mdata = load_map_json(game_path, map_name)
            if not mdata:
                continue
            lid = mdata.get("layout")
            if lid:
                map_to_layout[map_name] = lid

    # Build tileset struct -> dir name mapping from graphics.h
    graphics_path = os.path.join(game_path, "src", "data", "tilesets", "graphics.h")
    struct_to_dir = {}
    try:
        with open(graphics_path, encoding="utf-8") as f:
            for line in f:
                if "data/tilesets/secondary/" not in line:
                    continue
                m_path = re.search(r"data/tilesets/secondary/([^/]+)/", line)
                m_sym = re.search(r"gTileset(?:Tiles|Palettes)_(\w+?)(?:Compressed)?\[", line)
                if m_path and m_sym:
                    struct_name = f"gTileset_{m_sym.group(1)}"
                    struct_to_dir[struct_name] = m_path.group(1)
    except OSError:
        pass

    # Build tileset dir -> set of using maps
    tileset_usage = {}
    for map_name, lid in map_to_layout.items():
        ts_struct = layout_to_tileset.get(lid)
        if ts_struct:
            dir_name = struct_to_dir.get(ts_struct)
            if dir_name:
                tileset_usage.setdefault(dir_name, set()).add(map_name)

    # Find tilesets exclusively used by package maps
    for dir_name, using_maps in tileset_usage.items():
        if not using_maps:
            continue
        # All maps using this tileset must be in the package
        if using_maps <= package_maps:
            ts_path = os.path.join(tilesets_dir, dir_name)
            if os.path.isdir(ts_path):
                item = RemovalItem(
                    "tilesets", dir_name, SAFE,
                    detail=f"Used by {len(using_maps)} package map(s)",
                    data={"tileset_name": dir_name, "path": ts_path,
                          "used_by_vanilla": sorted(using_maps),
                          "used_by_custom": []},
                )
                plan.add(item)


def _collect_music(game_path, package_maps, vanilla_maps, plan):
    """Add music RemovalItems for songs exclusively used by package maps."""
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return

    # Build song -> set of using maps (across ALL maps)
    song_usage = {}
    for map_name in os.listdir(maps_dir):
        mdata = load_map_json(game_path, map_name)
        if not mdata:
            continue
        music = mdata.get("music")
        if music:
            song_usage.setdefault(music, set()).add(map_name)

    # Find songs exclusively used by package maps
    for song_const, using_maps in song_usage.items():
        if not using_maps:
            continue
        if using_maps <= package_maps:
            item = RemovalItem(
                "music", song_const, SAFE,
                detail=f"Used by {len(using_maps)} package map(s) only",
                data={"song_const": song_const,
                      "used_by_vanilla": sorted(using_maps & vanilla_maps),
                      "used_by_custom": []},
            )
            plan.add(item)


# ============================================================
# PER-MAP STATUS FOR DETAIL VIEW
# ============================================================

def get_map_statuses(pkg, indexes, proposed_removal, kept_vanilla,
                     custom_maps, game_path):
    """Get per-map SAFE/BLOCKED status for a package's detail view.

    Returns list of (map_name, status, blocker_summary) tuples.
    Includes reverse-reference cascade: if a blocked map references a
    safe map, the safe map is downgraded to blocked.
    """
    warp_index = indexes["warp_index"]
    conn_index = indexes["connection_index"]
    c_source_refs = indexes["c_source_refs"]
    map_layout_c_refs = indexes.get("map_layout_c_refs", {})
    layout_to_maps = indexes.get("layout_to_maps", {})
    name_to_const = indexes["name_to_const"]
    const_to_name = indexes["const_to_name"]
    shared_targets = indexes.get("shared_targets", {})

    # Phase 1: Initial evaluation for ALL maps in proposed_removal
    # (not just this package) so the cascade sees the full picture.
    map_status = {}
    map_blockers = {}
    for map_name in proposed_removal:
        blockers = _check_map_external_refs(
            map_name, proposed_removal, kept_vanilla, custom_maps,
            warp_index, conn_index, c_source_refs,
            name_to_const, const_to_name, shared_targets,
            game_path, map_layout_c_refs, layout_to_maps)
        if blockers:
            map_status[map_name] = BLOCKED
            map_blockers[map_name] = blockers
        else:
            map_status[map_name] = SAFE
            map_blockers[map_name] = []

    # Phase 2: Reverse-reference cascade
    _reverse_ref_cascade(map_status, map_blockers, warp_index, conn_index,
                         shared_targets, const_to_name, game_path,
                         layout_to_maps, kept_vanilla)

    # Phase 3: Return results for this package only
    results = []
    for map_name in sorted(pkg.maps):
        status = map_status.get(map_name, SAFE)
        if status == BLOCKED:
            bl = map_blockers.get(map_name, [])
            summary = bl[0]["ref_source"] if bl else ""
        else:
            summary = ""
        results.append((map_name, status, summary))
    return results
