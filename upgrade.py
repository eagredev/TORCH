"""Expansion Upgrade Module — upgrade pokeemerald-expansion to a newer version.

Uses a "Replace and Re-inject" strategy:
  1. Clone a clean baseline matching the current version
  2. Identify custom content by diffing against the baseline
  3. Replace the project with the target version
  4. Re-inject custom content back into the upgraded project

Usage:
    torch upgrade              Interactive upgrade wizard
    torch upgrade --check      Show current version and available updates
    torch upgrade --to X.Y.Z   Upgrade directly to a specific version
"""
# TORCH_MODULE: Expansion Upgrade
# TORCH_GROUP: Tools

import json
import os
import re
import shutil
import zipfile
from datetime import datetime

from torch import UPGRADE_VERSION
from torch.gitops import git_available, git_clone, _run_git
from torch.netops import fetch_json, check_connectivity, fetch_github_tags
from torch.expansion_compat import detect_expansion_version, version_str, parse_version_str
from torch.names import _detect_project_variant
from torch.ui import print_logo, _offer_build, _k, clear_screen, _diagnose_build_error
from torch.colours import GOLD, WHITE, CYAN, GREEN, RED, DIM, RST, BAR

# ============================================================
# CONSTANTS
# ============================================================

EXPANSION_REPO = "https://github.com/rh-hideout/pokeemerald-expansion.git"
TAGS_API_URL = "https://api.github.com/repos/rh-hideout/pokeemerald-expansion/tags"
TAGS_PER_PAGE = 100
TAG_PATTERN = re.compile(r"^expansion/(\d+)\.(\d+)\.(\d+)$")
MIN_DISK_SPACE_GB = 2

UPGRADE_CACHE_DIR = os.path.join(
    os.path.expanduser("~"), ".config", "torch", "upgrade_cache"
)
UPGRADE_BACKUP_DIR_NAME = "upgrade"

# Directories and file patterns excluded from backup and replace operations.
_EXCLUDE_DIRS = {".git", "backups", "build"}
_EXCLUDE_EXTENSIONS = {".gba", ".elf", ".map"}

# Focused list of vanilla files known to be commonly modified by ROM hackers.
_VANILLA_HOTSPOTS = [
    "src/birch_pokemon_data.c",
    "src/main_menu.c",
    "src/rom_header_gf.c",
    "include/constants/global.h",
    "include/constants/flags.h",
    "include/constants/vars.h",
    "include/constants/opponents.h",
    "include/constants/songs.h",
    "include/constants/weather.h",
    "include/constants/items.h",
    "include/constants/moves.h",
    "include/constants/species.h",
    "include/constants/abilities.h",
    "include/constants/maps.h",
    "include/config.h",
    "include/config/overworld.h",
    "include/config/battle.h",
    "include/config/pokemon.h",
    "include/config/item.h",
    "src/data/tilesets/headers.h",
    "src/data/tilesets/graphics.h",
    "src/data/tilesets/metatiles.h",
    "src/sound/song_table.h",
    "src/data/trainer_parties.h",
    "include/constants/event_objects.h",
    "include/constants/field_tasks.h",
    "src/data/object_events/object_event_graphics_info_pointers.h",
    "src/field_tasks.c",
    "data/specials.inc",
    "Makefile",
]


# ============================================================
# PHASE A — Version Detection & Tag Fetching
# ============================================================

def _fetch_available_versions():
    """Fetch expansion version tags from the GitHub API.

    Returns a list of (major, minor, patch) tuples sorted newest-first,
    or None on network/API error.
    """
    return fetch_github_tags(TAGS_API_URL, TAG_PATTERN, per_page=TAGS_PER_PAGE)


def _check_disk_space(game_path, min_gb=MIN_DISK_SPACE_GB):
    """Return True if the filesystem containing game_path has enough free space."""
    try:
        stat = os.statvfs(game_path)
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        return free_gb >= min_gb
    except OSError:
        return False


def _version_check_only(game_path):
    """Display current version and available updates, then exit."""
    print()
    current = detect_expansion_version(game_path)
    if not current:
        print(f"  {RED}Could not detect expansion version.{RST}")
        print(f"  {DIM}Is this a pokeemerald-expansion project?{RST}")
        return

    current_str = version_str(current)
    print(f"  {WHITE}Current version:{RST}  {CYAN}{current_str}{RST}")
    print()

    if not check_connectivity():
        print(f"  {DIM}No internet connection — cannot check for updates.{RST}")
        return

    print(f"  {DIM}Checking GitHub for available versions...{RST}")
    versions = _fetch_available_versions()
    if versions is None:
        print(f"  {RED}Could not fetch version tags from GitHub.{RST}")
        return

    if not versions:
        print(f"  {DIM}No tagged versions found.{RST}")
        return

    newest = versions[0]
    newest_str = version_str(newest)

    if newest <= current:
        print(f"  {GREEN}You're on the latest version!{RST}")
    else:
        print(f"  {WHITE}Latest version:{RST}   {GREEN}{newest_str}{RST}")
        print()
        # Show a few recent versions
        show_count = min(5, len(versions))
        print(f"  {DIM}Recent versions:{RST}")
        for v in versions[:show_count]:
            v_str = version_str(v)
            marker = " (current)" if v == current else ""
            colour = CYAN if v == current else RST
            print(f"    {colour}{v_str}{marker}{RST}")
        if len(versions) > show_count:
            print(f"    {DIM}... and {len(versions) - show_count} more{RST}")
        print()
        print(f"  {DIM}Run{RST} {CYAN}torch upgrade{RST} {DIM}to start the upgrade wizard.{RST}")
    print()


# ============================================================
# PHASE B — Snapshot + Custom Content Detection
# ============================================================

class UpgradeManifest:
    """Data holder for all information gathered during the upgrade scan."""

    def __init__(self):
        self.current_version = None       # (major, minor, patch)
        self.target_version = None        # (major, minor, patch)
        self.staging_dir = ""             # temp dir for custom content
        self.snapshot_path = ""           # path to the pre-upgrade ZIP backup
        self.baseline_path = ""           # cloned baseline directory
        self.target_path = ""             # cloned target directory
        self.custom_maps = []             # [{name, map_dir, layout_dir, has_scripts}]
        self.custom_map_groups = {}       # {group_name: [map_name, ...]}
        self.custom_layouts = []          # [layout_entry_dict, ...]
        self.custom_region_map_sections = []  # [section_entry_dict, ...]
        self.custom_heal_locations = {}   # {"format":"json","entries":[...]} or {"format":"h","files":{rel:str}} or {}
        self.custom_tilesets = []         # [{dir_name, kind, path, camel_name, c_lines}]
        self.makefile_vars = {}           # {var_name: value}
        self.modified_vanilla_files = []  # [{rel_path, reason}]
        self.scorch_detected = False      # True if backups/scorch/ exists
        self.has_enrolled_maps = False    # True if TORCH has enrolled maps to sync


def _create_upgrade_snapshot(game_path, version):
    """Create a full project ZIP backup before upgrading.

    Excludes .git/, backups/, build/, and build artifacts (.gba/.elf/.map).
    Returns the snapshot path on success, None on error.
    """
    backup_dir = os.path.join(game_path, "backups", UPGRADE_BACKUP_DIR_NAME)
    os.makedirs(backup_dir, exist_ok=True)

    ver_label = version_str(version) if version else "unknown"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"upgrade_from_{ver_label}_{timestamp}.zip"
    zip_path = os.path.join(backup_dir, zip_name)

    try:
        file_count = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, dirnames, filenames in os.walk(game_path):
                # Prune excluded directories in-place
                dirnames[:] = [
                    d for d in dirnames
                    if d not in _EXCLUDE_DIRS
                ]
                for fname in filenames:
                    _, ext = os.path.splitext(fname)
                    if ext.lower() in _EXCLUDE_EXTENSIONS:
                        continue
                    full_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(full_path, game_path)
                    # Skip anything inside backups/ (belt and suspenders)
                    if rel_path.startswith("backups"):
                        continue
                    try:
                        zf.write(full_path, rel_path)
                        file_count += 1
                    except OSError:
                        pass  # Skip unreadable files
        if file_count == 0:
            print(f"  {RED}WARNING: Backup ZIP is empty.{RST}")
            return None
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f"  {GREEN}Backup created:{RST} {zip_name}")
        print(f"  {DIM}{file_count} files, {size_mb:.1f} MB{RST}")
        return zip_path
    except Exception as e:
        print(f"  {RED}Backup failed: {e}{RST}")
        # Clean up partial ZIP
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        return None


def _clone_version(version_tag, label):
    """Shallow-clone a specific expansion version to the cache directory.

    version_tag: 'expansion/X.Y.Z' format
    label: human-readable label for messages (e.g. 'baseline 1.7.4')

    Returns the clone path on success, None on error.
    Reuses cached clones if the expansion.h version matches.
    """
    # Sanitize tag for directory name
    dir_name = version_tag.replace("/", "_")
    clone_path = os.path.join(UPGRADE_CACHE_DIR, dir_name)

    # Check cache
    if os.path.isdir(clone_path):
        cached_ver = detect_expansion_version(clone_path)
        tag_ver = parse_version_str(version_tag.split("/")[-1])
        if cached_ver and tag_ver and cached_ver == tag_ver:
            print(f"  {DIM}Using cached {label}{RST}")
            return clone_path
        # Cache is stale — remove and re-clone
        print(f"  {DIM}Cached {label} is stale, re-cloning...{RST}")
        shutil.rmtree(clone_path, ignore_errors=True)

    os.makedirs(UPGRADE_CACHE_DIR, exist_ok=True)
    print(f"  {DIM}Cloning {label}...{RST}")

    # git clone --branch <tag> --depth=1 <url> <dest>
    args = ["clone", f"--branch={version_tag}", "--depth=1",
            EXPANSION_REPO, clone_path]
    _, stderr, rc = _run_git(".", args, timeout=300)
    if rc == 0:
        print(f"  {GREEN}Cloned {label}{RST}")
        return clone_path

    print(f"  {RED}Clone failed: {stderr.strip()}{RST}")
    # Clean up partial clone
    shutil.rmtree(clone_path, ignore_errors=True)
    return None


def _detect_custom_maps(game_path, baseline_path):
    """Find maps in the user's project that don't exist in the baseline.

    Returns a list of dicts: [{name, map_dir, layout_dir, has_scripts}]
    """
    user_maps_dir = os.path.join(game_path, "data", "maps")
    base_maps_dir = os.path.join(baseline_path, "data", "maps")

    if not os.path.isdir(user_maps_dir):
        return []

    user_maps = set(os.listdir(user_maps_dir))
    base_maps = set(os.listdir(base_maps_dir)) if os.path.isdir(base_maps_dir) else set()

    custom_names = sorted(user_maps - base_maps)
    result = []
    for name in custom_names:
        map_dir = os.path.join(user_maps_dir, name)
        if not os.path.isdir(map_dir):
            continue
        # Check for matching layout directory
        layout_dir = os.path.join(game_path, "data", "layouts", name)
        has_layout = os.path.isdir(layout_dir)
        # Check for scripts
        has_scripts = any(
            f.endswith(".pory") or f.endswith(".inc")
            for f in os.listdir(map_dir)
            if os.path.isfile(os.path.join(map_dir, f))
        )
        result.append({
            "name": name,
            "map_dir": os.path.join("data", "maps", name),
            "layout_dir": os.path.join("data", "layouts", name) if has_layout else None,
            "has_scripts": has_scripts,
        })
    return result


def _detect_custom_map_groups(game_path, baseline_path):
    """Find map groups and maps in the user's map_groups.json that aren't in baseline's.

    Returns a dict: {group_name: [map_name, ...]}
    """
    user_mg = os.path.join(game_path, "data", "maps", "map_groups.json")
    base_mg = os.path.join(baseline_path, "data", "maps", "map_groups.json")

    user_data = _read_map_groups(user_mg)
    base_data = _read_map_groups(base_mg)

    if user_data is None:
        return {}

    base_groups = base_data if base_data else {}
    custom_groups = {}

    for group_name, maps in user_data.items():
        if group_name not in base_groups:
            # Entire group is custom
            custom_groups[group_name] = maps
        else:
            # Check for custom maps within a vanilla group
            base_map_set = set(base_groups[group_name])
            custom_maps = [m for m in maps if m not in base_map_set]
            if custom_maps:
                custom_groups[group_name] = custom_maps

    return custom_groups


def _read_map_groups(filepath):
    """Read map_groups.json and return the group dict (without group_order).

    Returns the parsed dict with only group_name -> [maps] entries,
    or None on error.
    """
    data = _read_json_safe(filepath)
    if data is None:
        return None
    return {k: v for k, v in data.items()
            if isinstance(v, list) and k != "group_order"}


def _read_map_groups_raw(filepath):
    """Read map_groups.json and return the complete raw JSON dict.

    Returns None on error.
    """
    return _read_json_safe(filepath)


def _detect_makefile_customizations(game_path, baseline_path):
    """Compare Makefile variables between user project and baseline.

    Returns a dict of {var_name: user_value} for variables that differ.
    """
    try:
        from torch.studio import _read_makefile_var
    except ImportError:
        return {}

    user_makefile = os.path.join(game_path, "Makefile")
    base_makefile = os.path.join(baseline_path, "Makefile")

    if not os.path.isfile(user_makefile) or not os.path.isfile(base_makefile):
        return {}

    vars_to_check = ["TITLE", "GAME_CODE", "ROM_NAME"]
    customizations = {}

    for var in vars_to_check:
        user_val = _read_makefile_var(user_makefile, var)
        base_val = _read_makefile_var(base_makefile, var)
        if user_val and base_val and user_val != base_val:
            customizations[var] = user_val

    return customizations


def _detect_modified_vanilla_files(game_path, baseline_path):
    """Check known hotspot files for modifications.

    Compares file contents between user project and baseline.
    Returns a list of [{rel_path, reason, additions}] where additions
    is a list of {context_before, lines, context_after} blocks describing
    lines added by the user.
    """
    import difflib

    modified = []
    for rel_path in _VANILLA_HOTSPOTS:
        user_file = os.path.join(game_path, rel_path)
        base_file = os.path.join(baseline_path, rel_path)

        if not os.path.isfile(user_file):
            continue
        if not os.path.isfile(base_file):
            modified.append({
                "rel_path": rel_path,
                "reason": "file not in baseline (may be custom)",
                "additions": [],
            })
            continue

        try:
            with open(user_file, encoding="utf-8", errors="replace") as f:
                user_lines = f.readlines()
            with open(base_file, encoding="utf-8", errors="replace") as f:
                base_lines = f.readlines()
            if user_lines == base_lines:
                continue

            additions = _extract_additions(base_lines, user_lines)
            modified.append({
                "rel_path": rel_path,
                "reason": "content differs from baseline",
                "additions": additions,
            })
        except OSError:
            pass  # Can't read — skip

    return modified


def _extract_additions(base_lines, user_lines):
    """Extract blocks of lines that were added by the user.

    Uses SequenceMatcher to find inserted blocks. Each block includes
    context lines (from the base) before and after for placement.
    Returns [{context_before: [str], lines: [str], context_after: [str]}].
    """
    import difflib

    sm = difflib.SequenceMatcher(None, base_lines, user_lines, autojunk=False)
    additions = []
    CONTEXT = 3  # lines of context for placement

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            added = user_lines[j1:j2]
            # Context from the base file around the insertion point
            ctx_before = base_lines[max(0, i1 - CONTEXT):i1]
            ctx_after = base_lines[i1:min(len(base_lines), i1 + CONTEXT)]
            additions.append({
                "context_before": [l.rstrip("\n") for l in ctx_before],
                "lines": [l.rstrip("\n") for l in added],
                "context_after": [l.rstrip("\n") for l in ctx_after],
            })
        elif tag == "replace":
            # Lines were changed, not just added — store as additions
            # but flag that they replace existing content
            added = user_lines[j1:j2]
            removed = base_lines[i1:i2]
            ctx_before = base_lines[max(0, i1 - CONTEXT):i1]
            ctx_after = base_lines[i2:min(len(base_lines), i2 + CONTEXT)]
            additions.append({
                "context_before": [l.rstrip("\n") for l in ctx_before],
                "lines": [l.rstrip("\n") for l in added],
                "context_after": [l.rstrip("\n") for l in ctx_after],
                "replaces": [l.rstrip("\n") for l in removed],
            })

    return additions


def _detect_custom_layouts(game_path, baseline_path):
    """Find layout entries in layouts.json that don't exist in the baseline.

    Returns a list of layout entry dicts that are custom.
    """
    user_file = os.path.join(game_path, "data", "layouts", "layouts.json")
    base_file = os.path.join(baseline_path, "data", "layouts", "layouts.json")

    user_data = _read_json_safe(user_file)
    base_data = _read_json_safe(base_file)
    if user_data is None:
        return []

    user_layouts = user_data.get("layouts", [])
    base_ids = set()
    if base_data:
        for entry in base_data.get("layouts", []):
            base_ids.add(entry.get("id", ""))

    return [entry for entry in user_layouts if entry.get("id", "") not in base_ids]


def _rms_id_key(entry):
    """Get the MAPSEC constant from a region_map_sections entry.

    Handles both old schema (key='map_section') and new schema (key='id').
    """
    return entry.get("id") or entry.get("map_section", "")


def _detect_custom_region_map_sections(game_path, baseline_path):
    """Find region map section entries that don't exist in the baseline.

    Returns a list of section entry dicts that are custom.
    Handles both old (map_section key) and new (id key) schemas.
    """
    user_file = os.path.join(
        game_path, "src", "data", "region_map", "region_map_sections.json")
    base_file = os.path.join(
        baseline_path, "src", "data", "region_map", "region_map_sections.json")

    user_data = _read_json_safe(user_file)
    base_data = _read_json_safe(base_file)
    if user_data is None:
        return []

    user_sections = user_data.get("map_sections", [])
    base_consts = set()
    if base_data:
        for entry in base_data.get("map_sections", []):
            base_consts.add(_rms_id_key(entry))

    return [
        entry for entry in user_sections
        if _rms_id_key(entry) not in base_consts
    ]


def _detect_custom_heal_locations(game_path, baseline_path):
    """Detect custom heal location entries.

    Supports two formats:
    - Old: hand-edited .h files (src/data/heal_locations.h, include/constants/heal_locations.h)
    - New: JSON file (src/data/heal_locations.json)

    Returns a dict with one of:
    - {"format": "h", "files": {rel_path: content}} for old format
    - {"format": "json", "entries": [entry_dict]} for JSON format
    - {} if no custom entries
    """
    # Check if the user project uses the old .h format
    user_h = os.path.join(game_path, "src", "data", "heal_locations.h")
    user_json = os.path.join(game_path, "src", "data", "heal_locations.json")
    base_h = os.path.join(baseline_path, "src", "data", "heal_locations.h")
    base_json = os.path.join(baseline_path, "src", "data", "heal_locations.json")

    # JSON format: diff entries by id
    if os.path.isfile(user_json) and os.path.isfile(base_json):
        user_data = _read_json_safe(user_json)
        base_data = _read_json_safe(base_json)
        if user_data and base_data:
            base_ids = {e.get("id", "") for e in base_data.get("heal_locations", [])}
            custom_entries = [
                e for e in user_data.get("heal_locations", [])
                if e.get("id", "") not in base_ids
            ]
            if custom_entries:
                return {"format": "json", "entries": custom_entries}
        return {}

    # Old .h format: store file contents for manual re-application
    if os.path.isfile(user_h) and os.path.isfile(base_h):
        heal_files = [
            os.path.join("include", "constants", "heal_locations.h"),
            os.path.join("src", "data", "heal_locations.h"),
        ]
        custom_files = {}
        for rel_path in heal_files:
            uf = os.path.join(game_path, rel_path)
            bf = os.path.join(baseline_path, rel_path)
            if not os.path.isfile(uf) or not os.path.isfile(bf):
                continue
            try:
                with open(uf, "rb") as f:
                    uc = f.read()
                with open(bf, "rb") as f:
                    bc = f.read()
                if uc != bc:
                    custom_files[rel_path] = uc.decode("utf-8", errors="replace")
            except OSError:
                pass
        if custom_files:
            return {"format": "h", "files": custom_files}

    return {}


def _detect_custom_tilesets(game_path, baseline_path):
    """Find tileset directories in the user's project that don't exist in the baseline.

    Scans data/tilesets/primary/ and data/tilesets/secondary/ in both paths.
    Any directory present in the user's project but NOT in the baseline is custom.

    Also extracts the relevant C source lines from headers.h, graphics.h, and
    metatiles.h so they can be re-registered after the upgrade replaces those files.

    Returns a list of dicts: [{dir_name, kind, path, camel_name, c_lines}]
    where c_lines is {headers_h: str, graphics_h: str, metatiles_h: str}.
    """
    result = []

    for kind in ("primary", "secondary"):
        user_dir = os.path.join(game_path, "data", "tilesets", kind)
        base_dir = os.path.join(baseline_path, "data", "tilesets", kind)

        if not os.path.isdir(user_dir):
            continue

        try:
            user_dirs = set(
                d for d in os.listdir(user_dir)
                if os.path.isdir(os.path.join(user_dir, d))
            )
        except OSError:
            continue

        if os.path.isdir(base_dir):
            try:
                base_dirs = set(
                    d for d in os.listdir(base_dir)
                    if os.path.isdir(os.path.join(base_dir, d))
                )
            except OSError:
                base_dirs = set()
        else:
            base_dirs = set()

        custom_names = sorted(user_dirs - base_dirs)
        for dir_name in custom_names:
            # Derive CamelCase from directory name
            parts = dir_name.split("_")
            camel = "".join(p.capitalize() for p in parts if p)

            c_lines = _extract_tileset_c_lines(game_path, camel)

            result.append({
                "dir_name": dir_name,
                "kind": kind,
                "path": os.path.join("data", "tilesets", kind, dir_name),
                "camel_name": camel,
                "c_lines": c_lines,
            })

    return result


def _extract_tileset_c_lines(game_path, camel_name):
    """Extract C registration lines for a tileset from headers.h, graphics.h, metatiles.h.

    Returns a dict: {headers_h: str, graphics_h: str, metatiles_h: str}
    with the relevant source lines for the named tileset, or empty strings
    if not found.
    """
    result = {
        "headers_h": "",
        "graphics_h": "",
        "metatiles_h": "",
    }

    base_dir = os.path.join(game_path, "src", "data", "tilesets")

    # headers.h: find the gTileset_<CamelName> struct block
    headers_path = os.path.join(base_dir, "headers.h")
    result["headers_h"] = _extract_c_block(
        headers_path, f"gTileset_{camel_name}")

    # graphics.h: find gTilesetTiles_<CamelName> and gTilesetPalettes_<CamelName>
    graphics_path = os.path.join(base_dir, "graphics.h")
    result["graphics_h"] = _extract_c_lines_by_name(
        graphics_path, camel_name,
        [f"gTilesetTiles_{camel_name}", f"gTilesetPalettes_{camel_name}"])

    # metatiles.h: find gMetatiles_<CamelName> and gMetatileAttributes_<CamelName>
    metatiles_path = os.path.join(base_dir, "metatiles.h")
    result["metatiles_h"] = _extract_c_lines_by_name(
        metatiles_path, camel_name,
        [f"gMetatiles_{camel_name}", f"gMetatileAttributes_{camel_name}"])

    return result


def _extract_c_block(filepath, identifier):
    """Extract a C struct block starting with 'identifier' through the closing '};'.

    Returns the matched lines as a string, or "" if not found.
    """
    if not os.path.isfile(filepath):
        return ""

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return ""

    collecting = False
    collected = []
    for line in lines:
        if not collecting and identifier in line:
            collecting = True
        if collecting:
            collected.append(line)
            if line.strip() == "};":
                break

    return "".join(collected)


def _extract_c_lines_by_name(filepath, camel_name, identifiers):
    """Extract all lines containing any of the given identifiers, plus continuation lines.

    For multi-line blocks (like palette arrays), captures from the identifier
    line through the closing '};'.

    Returns the matched lines as a string, or "" if not found.
    """
    if not os.path.isfile(filepath):
        return ""

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return ""

    collected = []
    in_block = False
    for line in lines:
        if in_block:
            collected.append(line)
            if line.strip() == "};":
                in_block = False
            continue
        for ident in identifiers:
            if ident in line:
                collected.append(line)
                # Check if this opens a multi-line block (has '{' but no '};')
                stripped = line.strip()
                if stripped.endswith("{") or (
                    "{" in stripped and "};" not in stripped
                ):
                    in_block = True
                break

    return "".join(collected)


def _read_json_safe(filepath):
    """Read a JSON file, returning None on error."""
    if not os.path.isfile(filepath):
        return None
    try:
        with open(filepath, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _extract_custom_content(game_path, baseline_path, staging_dir):
    """Orchestrate all detection functions and copy custom content to staging.

    Returns a populated UpgradeManifest.
    """
    manifest = UpgradeManifest()
    manifest.baseline_path = baseline_path
    manifest.staging_dir = staging_dir

    # Detect SCORCH usage
    scorch_dir = os.path.join(game_path, "backups", "scorch")
    manifest.scorch_detected = os.path.isdir(scorch_dir)

    # Custom maps
    print(f"  {DIM}Scanning for custom maps...{RST}")
    manifest.custom_maps = _detect_custom_maps(game_path, baseline_path)

    # Custom map groups
    print(f"  {DIM}Scanning map groups...{RST}")
    manifest.custom_map_groups = _detect_custom_map_groups(game_path, baseline_path)

    # Makefile customizations
    print(f"  {DIM}Checking Makefile customizations...{RST}")
    manifest.makefile_vars = _detect_makefile_customizations(game_path, baseline_path)

    # Custom layouts (layouts.json entries)
    print(f"  {DIM}Scanning layouts registry...{RST}")
    manifest.custom_layouts = _detect_custom_layouts(game_path, baseline_path)

    # Custom region map sections
    print(f"  {DIM}Scanning region map sections...{RST}")
    manifest.custom_region_map_sections = _detect_custom_region_map_sections(
        game_path, baseline_path)

    # Custom heal locations
    print(f"  {DIM}Checking heal locations...{RST}")
    manifest.custom_heal_locations = _detect_custom_heal_locations(
        game_path, baseline_path)

    # Custom tilesets
    print(f"  {DIM}Scanning for custom tilesets...{RST}")
    manifest.custom_tilesets = _detect_custom_tilesets(game_path, baseline_path)

    # Modified vanilla files
    print(f"  {DIM}Checking for modified vanilla files...{RST}")
    manifest.modified_vanilla_files = _detect_modified_vanilla_files(game_path, baseline_path)

    # Check for enrolled maps (for post-upgrade sync)
    try:
        from torch.registry import get_enrolled_maps
        project_dir = manifest.staging_dir  # won't have registry, but check game workspace
        # Look for the workspace-based registry — not critical if missing
        manifest.has_enrolled_maps = False
    except ImportError:
        manifest.has_enrolled_maps = False

    # Copy custom map directories to staging
    if manifest.custom_maps:
        print(f"  {DIM}Copying {len(manifest.custom_maps)} custom map(s) to staging...{RST}")
        for cmap in manifest.custom_maps:
            # Copy map directory
            src_map = os.path.join(game_path, cmap["map_dir"])
            dst_map = os.path.join(staging_dir, cmap["map_dir"])
            if os.path.isdir(src_map):
                os.makedirs(os.path.dirname(dst_map), exist_ok=True)
                shutil.copytree(src_map, dst_map)

            # Copy layout directory if it exists
            if cmap["layout_dir"]:
                src_layout = os.path.join(game_path, cmap["layout_dir"])
                dst_layout = os.path.join(staging_dir, cmap["layout_dir"])
                if os.path.isdir(src_layout):
                    os.makedirs(os.path.dirname(dst_layout), exist_ok=True)
                    shutil.copytree(src_layout, dst_layout)

    # Copy custom tileset directories to staging
    if manifest.custom_tilesets:
        print(f"  {DIM}Copying {len(manifest.custom_tilesets)} custom tileset(s) to staging...{RST}")
        for ts in manifest.custom_tilesets:
            src_ts = os.path.join(game_path, ts["path"])
            dst_ts = os.path.join(staging_dir, ts["path"])
            if os.path.isdir(src_ts):
                os.makedirs(os.path.dirname(dst_ts), exist_ok=True)
                shutil.copytree(src_ts, dst_ts)

    return manifest


# ============================================================
# PHASE C — Replace + Re-inject + Verify
# ============================================================

def _should_preserve(rel_path, custom_map_names, custom_tileset_paths=None):
    """Return True if a file/directory should be preserved during replacement."""
    parts = rel_path.replace("\\", "/").split("/")
    top = parts[0] if parts else ""

    # Always preserve these top-level directories
    if top in _EXCLUDE_DIRS:
        return True

    # Preserve custom map directories
    if len(parts) >= 3 and parts[0] == "data" and parts[1] == "maps":
        if parts[2] in custom_map_names:
            return True
    if len(parts) >= 3 and parts[0] == "data" and parts[1] == "layouts":
        if parts[2] in custom_map_names:
            return True

    # Preserve custom tileset directories
    if custom_tileset_paths:
        norm = rel_path.replace("\\", "/")
        for ts_path in custom_tileset_paths:
            if norm == ts_path or norm.startswith(ts_path.rstrip("/") + "/"):
                return True

    return False


def _replace_base(game_path, target_path, custom_map_names,
                   custom_tileset_paths=None):
    """Replace the project base with the target version.

    Two-pass approach:
      Pass 1: Walk target, copy every file to game_path (overwrite)
      Pass 2: Walk game_path, delete anything not in target AND not preserved

    Returns (files_copied, files_deleted, errors).
    """
    files_copied = 0
    files_deleted = 0
    errors = []

    # Build a set of relative paths in the target
    target_files = set()
    target_dirs = set()

    for dirpath, dirnames, filenames in os.walk(target_path):
        # Skip .git in the target clone
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, target_path)
            target_files.add(rel)
        rel_dir = os.path.relpath(dirpath, target_path)
        if rel_dir != ".":
            target_dirs.add(rel_dir)

    # Pass 1: Copy from target to game_path
    for rel in sorted(target_files):
        src = os.path.join(target_path, rel)
        dst = os.path.join(game_path, rel)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            files_copied += 1
        except OSError as e:
            errors.append(f"copy {rel}: {e}")

    # Pass 2: Delete files in game_path that aren't in target and aren't preserved
    custom_name_set = set(custom_map_names)
    ts_paths = custom_tileset_paths or []
    for dirpath, dirnames, filenames in os.walk(game_path, topdown=True):
        rel_dir = os.path.relpath(dirpath, game_path)

        # Don't descend into preserved directories
        dirnames[:] = [
            d for d in dirnames
            if not _should_preserve(
                os.path.join(rel_dir, d) if rel_dir != "." else d,
                custom_name_set,
                ts_paths,
            )
        ]

        for fname in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fname), game_path)
            _, ext = os.path.splitext(fname)
            if ext.lower() in _EXCLUDE_EXTENSIONS:
                continue
            if _should_preserve(rel, custom_name_set, ts_paths):
                continue
            if rel not in target_files:
                try:
                    os.unlink(os.path.join(dirpath, fname))
                    files_deleted += 1
                except OSError as e:
                    errors.append(f"delete {rel}: {e}")

    # Clean up empty directories (bottom-up)
    for dirpath, dirnames, filenames in os.walk(game_path, topdown=False):
        rel_dir = os.path.relpath(dirpath, game_path)
        if rel_dir == ".":
            continue
        if _should_preserve(rel_dir, custom_name_set, ts_paths):
            continue
        if not os.listdir(dirpath):
            try:
                os.rmdir(dirpath)
            except OSError:
                pass

    return files_copied, files_deleted, errors


def _reinject_custom_maps(game_path, manifest):
    """Copy custom map and layout directories from staging back to the project.

    Returns the number of maps re-injected.
    """
    count = 0
    for cmap in manifest.custom_maps:
        # Re-inject map directory
        src_map = os.path.join(manifest.staging_dir, cmap["map_dir"])
        dst_map = os.path.join(game_path, cmap["map_dir"])
        if os.path.isdir(src_map):
            if os.path.isdir(dst_map):
                shutil.rmtree(dst_map)
            os.makedirs(os.path.dirname(dst_map), exist_ok=True)
            shutil.copytree(src_map, dst_map)
            count += 1

        # Re-inject layout directory
        if cmap["layout_dir"]:
            src_layout = os.path.join(manifest.staging_dir, cmap["layout_dir"])
            dst_layout = os.path.join(game_path, cmap["layout_dir"])
            if os.path.isdir(src_layout):
                if os.path.isdir(dst_layout):
                    shutil.rmtree(dst_layout)
                os.makedirs(os.path.dirname(dst_layout), exist_ok=True)
                shutil.copytree(src_layout, dst_layout)

    return count


def _reinject_custom_tilesets(game_path, manifest):
    """Copy custom tileset directories from staging back and re-register in C headers.

    Copies the tileset directories, then appends the stored C source lines
    to headers.h, graphics.h, and metatiles.h.

    Returns the number of tilesets re-injected.
    """
    if not manifest.custom_tilesets:
        return 0

    count = 0
    for ts in manifest.custom_tilesets:
        # Re-inject tileset directory from staging
        src = os.path.join(manifest.staging_dir, ts["path"])
        dst = os.path.join(game_path, ts["path"])
        if os.path.isdir(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copytree(src, dst)
            count += 1

    # Re-register C header lines
    header_map = {
        "headers_h": os.path.join(
            game_path, "src", "data", "tilesets", "headers.h"),
        "graphics_h": os.path.join(
            game_path, "src", "data", "tilesets", "graphics.h"),
        "metatiles_h": os.path.join(
            game_path, "src", "data", "tilesets", "metatiles.h"),
    }

    for key, filepath in header_map.items():
        lines_to_append = []
        for ts in manifest.custom_tilesets:
            c_lines = ts.get("c_lines", {})
            block = c_lines.get(key, "")
            if block:
                lines_to_append.append(block)

        if lines_to_append and os.path.isfile(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if not content.endswith("\n"):
                    content += "\n"
                content += "\n" + "\n".join(lines_to_append)
                if not content.endswith("\n"):
                    content += "\n"
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
            except OSError:
                pass

    return count


def _reinject_map_groups(game_path, manifest):
    """Merge custom map groups back into the new map_groups.json.

    Reads the new (target) map_groups.json, appends custom groups
    to group_order, adds group contents, and writes back.

    Returns True on success, False on error.
    """
    if not manifest.custom_map_groups:
        return True

    mg_path = os.path.join(game_path, "data", "maps", "map_groups.json")

    # Read from target clone to guarantee correct base data
    target_raw = None
    if manifest.target_path:
        target_mg = os.path.join(
            manifest.target_path, "data", "maps", "map_groups.json")
        target_raw = _read_map_groups_raw(target_mg)

    raw = target_raw if target_raw is not None else _read_map_groups_raw(mg_path)
    if raw is None:
        print(f"  {RED}WARNING: Could not read map_groups.json for merge.{RST}")
        print(f"  {DIM}You may need to manually add your custom maps.{RST}")
        return False

    group_order = raw.get("group_order", [])

    for group_name, maps in manifest.custom_map_groups.items():
        if group_name in raw:
            # Group exists in new version — append only new maps
            existing = set(raw[group_name])
            for m in maps:
                if m not in existing:
                    raw[group_name].append(m)
        else:
            # Entirely custom group — add it
            raw[group_name] = maps
            if group_name not in group_order:
                group_order.append(group_name)

    raw["group_order"] = group_order

    try:
        # Create backup
        shutil.copy2(mg_path, mg_path + ".bak")
        with open(mg_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2)
            f.write("\n")
        return True
    except OSError as e:
        print(f"  {RED}WARNING: Could not write map_groups.json: {e}{RST}")
        return False


def _reinject_makefile_vars(game_path, manifest):
    """Re-apply Makefile variable customizations.

    Returns the number of variables re-applied.
    """
    if not manifest.makefile_vars:
        return 0

    try:
        from torch.studio import _write_makefile_var
    except ImportError:
        print(f"  {DIM}ROM Studio not available; Makefile vars not re-applied.{RST}")
        return 0

    makefile = os.path.join(game_path, "Makefile")
    count = 0
    for var, value in manifest.makefile_vars.items():
        if _write_makefile_var(makefile, var, value):
            count += 1

    # Validate that the all: target is still the first real target
    if count > 0:
        _validate_makefile_target_order(makefile)

    return count


def _validate_makefile_target_order(makefile_path):
    """Verify that `all:` is the first non-variable target in the Makefile.

    If a custom target was placed above `all: rom`, `make` with no arguments
    would silently build the wrong target.  This catches that.
    """
    import re
    try:
        with open(makefile_path, "r") as f:
            lines = f.readlines()
    except OSError:
        return

    # A target line looks like: name: [deps]  (not a variable assignment like VAR = ...)
    # Skip: comments, blank lines, variable assignments (?=, :=, =), conditionals (ifeq, etc.)
    target_pat = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:(?!=)')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("ifeq", "ifneq", "ifdef", "ifndef", "else", "endif",
                                "include", "define", "endef", "export", "unexport",
                                "override", "vpath", ".PHONY", ".SECONDARY", ".PRECIOUS")):
            continue
        m = target_pat.match(stripped)
        if m:
            target_name = m.group(1)
            if target_name == "all":
                return  # all: is the first target — correct
            # Found a non-all target before all:
            print(f"  {GOLD}Warning:{RST} Makefile target '{target_name}' appears before 'all:'")
            print(f"  {DIM}This means 'make' will build '{target_name}' instead of your ROM.{RST}")
            print(f"  {DIM}Move '{target_name}:' below 'all: rom' in {makefile_path}{RST}")
            return


def _reinject_layouts(game_path, manifest):
    """Merge custom layout entries back into the new layouts.json.

    Returns True on success, False on error.
    """
    if not manifest.custom_layouts:
        return True

    layouts_path = os.path.join(game_path, "data", "layouts", "layouts.json")

    # Read from target clone to guarantee correct base data
    target_data = None
    if manifest.target_path:
        target_layouts = os.path.join(
            manifest.target_path, "data", "layouts", "layouts.json")
        target_data = _read_json_safe(target_layouts)

    data = target_data if target_data is not None else _read_json_safe(layouts_path)
    if data is None:
        print(f"  {RED}WARNING: Could not read layouts.json for merge.{RST}")
        return False

    existing_ids = {e.get("id") for e in data.get("layouts", [])}
    added = 0
    for entry in manifest.custom_layouts:
        if entry.get("id") not in existing_ids:
            data["layouts"].append(entry)
            added += 1

    if added == 0:
        return True

    try:
        shutil.copy2(layouts_path, layouts_path + ".bak")
        with open(layouts_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        return True
    except OSError as e:
        print(f"  {RED}WARNING: Could not write layouts.json: {e}{RST}")
        return False


def _reinject_region_map_sections(game_path, manifest):
    """Merge custom region map section entries back into region_map_sections.json.

    Reads from the TARGET clone to guarantee we have the correct schema,
    then writes to game_path. Adapts custom entries to the target version's
    schema if the key name changed (e.g. 'map_section' → 'id').

    Returns True on success, False on error.
    """
    if not manifest.custom_region_map_sections:
        return True

    rms_path = os.path.join(
        game_path, "src", "data", "region_map", "region_map_sections.json")

    # Read from the target clone to ensure we have the correct schema,
    # rather than relying on _replace_base having already overwritten it.
    target_rms = None
    if manifest.target_path:
        target_rms_path = os.path.join(
            manifest.target_path, "src", "data", "region_map",
            "region_map_sections.json")
        target_rms = _read_json_safe(target_rms_path)

    data = target_rms if target_rms is not None else _read_json_safe(rms_path)
    if data is None:
        print(f"  {RED}WARNING: Could not read region_map_sections.json for merge.{RST}")
        return False

    # Detect which key the target version uses for the MAPSEC constant
    target_sections = data.get("map_sections", [])
    target_uses_id = any("id" in e for e in target_sections[:3])

    existing_consts = {_rms_id_key(e) for e in target_sections}
    added = 0
    for entry in manifest.custom_region_map_sections:
        const_val = _rms_id_key(entry)
        if const_val not in existing_consts:
            # Adapt entry to target schema
            adapted = dict(entry)
            if target_uses_id and "map_section" in adapted and "id" not in adapted:
                adapted["id"] = adapted.pop("map_section")
            elif not target_uses_id and "id" in adapted and "map_section" not in adapted:
                adapted["map_section"] = adapted.pop("id")
            data["map_sections"].append(adapted)
            added += 1

    if added == 0:
        return True

    try:
        shutil.copy2(rms_path, rms_path + ".bak")
        with open(rms_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        return True
    except OSError as e:
        print(f"  {RED}WARNING: Could not write region_map_sections.json: {e}{RST}")
        return False


def _reinject_heal_locations(game_path, manifest):
    """Merge or restore custom heal location data after an upgrade.

    Handles two formats:
    - JSON: merge custom entries into the target's heal_locations.json
    - Old .h: restore the user's .h files (only if the target still uses .h)
      If the target has migrated to JSON, warn the user instead.

    Returns the number of entries/files restored.
    """
    hl = manifest.custom_heal_locations
    if not hl:
        return 0

    fmt = hl.get("format", "")

    target_path = getattr(manifest, "target_path", None)

    if fmt == "json":
        return _reinject_heal_locations_json(
            game_path, hl.get("entries", []), target_path)

    if fmt == "h":
        return _reinject_heal_locations_h(game_path, hl.get("files", {}))

    return 0


def _reinject_heal_locations_json(game_path, custom_entries, target_path=None):
    """Merge custom heal_location entries into heal_locations.json."""
    hl_path = os.path.join(game_path, "src", "data", "heal_locations.json")

    # Read from target clone to guarantee correct base data
    target_data = None
    if target_path:
        target_hl = os.path.join(target_path, "src", "data", "heal_locations.json")
        target_data = _read_json_safe(target_hl)

    data = target_data if target_data is not None else _read_json_safe(hl_path)
    if data is None:
        print(f"  {RED}WARNING: Could not read heal_locations.json for merge.{RST}")
        return 0

    existing_ids = {e.get("id", "") for e in data.get("heal_locations", [])}
    added = 0
    for entry in custom_entries:
        if entry.get("id", "") not in existing_ids:
            data["heal_locations"].append(entry)
            added += 1

    if added == 0:
        return 0

    try:
        shutil.copy2(hl_path, hl_path + ".bak")
        with open(hl_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        return added
    except OSError as e:
        print(f"  {RED}WARNING: Could not write heal_locations.json: {e}{RST}")
        return 0


def _reinject_heal_locations_h(game_path, custom_files):
    """Restore custom .h heal_location files.

    If the target version has migrated to JSON (heal_locations.json exists),
    we can't blindly overwrite the auto-generated .h files. Warn instead.
    """
    # Check if the target has migrated to JSON
    json_path = os.path.join(game_path, "src", "data", "heal_locations.json")
    if os.path.isfile(json_path):
        print(f"  {GOLD}NOTE:{RST} The target version uses heal_locations.json instead of .h files.")
        print(f"  {DIM}Your custom heal locations need to be migrated to the JSON format.{RST}")
        print(f"  {DIM}Check your backup to see the original .h file contents.{RST}")
        return 0

    count = 0
    for rel_path, content in custom_files.items():
        dest = os.path.join(game_path, rel_path)
        try:
            if os.path.isfile(dest):
                shutil.copy2(dest, dest + ".bak")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(content)
            count += 1
        except OSError as e:
            print(f"  {RED}WARNING: Could not restore {rel_path}: {e}{RST}")

    return count


def _reinject_event_scripts(game_path, manifest):
    """Append .include lines for custom map scripts to data/event_scripts.s.

    The target version's event_scripts.s only includes vanilla maps.
    Custom maps with scripts.inc need their include lines added for the
    linker to find script labels.

    Returns the number of includes added.
    """
    if not manifest.custom_maps:
        return 0

    es_path = os.path.join(game_path, "data", "event_scripts.s")
    if not os.path.isfile(es_path):
        return 0

    with open(es_path, "r", encoding="utf-8") as f:
        content = f.read()

    added = 0
    lines_to_add = []
    for cmap in manifest.custom_maps:
        if not cmap["has_scripts"]:
            continue
        name = cmap["name"]
        inc_path = os.path.join(game_path, "data", "maps", name, "scripts.inc")
        if not os.path.isfile(inc_path):
            continue
        include_line = f'\t.include "data/maps/{name}/scripts.inc"'
        if include_line not in content:
            lines_to_add.append(include_line)
            added += 1

    if lines_to_add:
        if not content.endswith("\n"):
            content += "\n"
        content += "\n".join(lines_to_add) + "\n"
        with open(es_path, "w", encoding="utf-8") as f:
            f.write(content)

    return added


def _resolve_report_dir(game_path):
    """Resolve the TORCH workspace directory for saving upgrade reports.

    Looks up the project workspace by matching game_path against configured
    projects. Returns the workspace dir path, or None if not found.
    """
    try:
        from torch.config import load_config
    except ImportError:
        return None

    config = load_config()
    if config is None:
        return None

    workspace, projects, _ = config
    workspace_expanded = os.path.expanduser(workspace)

    for pname, pinfo in projects.items():
        gp = os.path.expanduser(pinfo["game_path"])
        if os.path.realpath(gp) == os.path.realpath(game_path):
            return os.path.join(workspace_expanded, pname)

    return None


def _report_auto_handled(manifest):
    """Build the 'automatically handled' section of the upgrade report."""
    lines = ["AUTOMATICALLY HANDLED", "-" * 45]
    if manifest.custom_maps:
        names = ", ".join(m["name"] for m in manifest.custom_maps)
        lines.append(f"- Custom maps re-injected: {names}")
    if manifest.custom_tilesets:
        ts_names = ", ".join(ts["camel_name"] for ts in manifest.custom_tilesets)
        lines.append(f"- Custom tilesets re-injected: {ts_names}")
    if manifest.custom_map_groups:
        lines.append("- map_groups.json updated")
    if manifest.custom_layouts:
        lines.append("- layouts.json updated")
    if manifest.custom_region_map_sections:
        lines.append("- region_map_sections.json updated")
    if manifest.custom_heal_locations:
        lines.append("- heal_locations updated")
    if manifest.makefile_vars:
        vars_list = ", ".join(manifest.makefile_vars.keys())
        lines.append(f"- Makefile vars re-applied: {vars_list}")
    lines.append("")
    return lines


def _report_file_entry(entry, index):
    """Build the report lines for a single modified vanilla file."""
    lines = []
    rel = entry["rel_path"]
    lines.append(f"--- File {index}: {rel} ---")

    for block in entry["additions"]:
        added = block.get("lines", [])
        ctx = block.get("context_before", [])

        if "replaces" in block:
            replaced = block["replaces"]
            lines.append(f"  REPLACED ({len(replaced)} line(s) -> {len(added)} line(s)):")
            for r in replaced:
                lines.append(f"  | - {r}")
            for a in added:
                lines.append(f"  | + {a}")
            lines.append("")
        elif added:
            ctx_hint = ""
            if ctx:
                last_ctx = ctx[-1].strip()
                if len(last_ctx) > 60:
                    last_ctx = last_ctx[:57] + "..."
                ctx_hint = f', after: "{last_ctx}"'
            lines.append(f"Your additions ({len(added)} line(s){ctx_hint}):")
            for a in added:
                lines.append(f"  | {a}")
            lines.append("")

    lines.append(f"Action: Copy your additions into the new version's {os.path.basename(rel)}.")
    lines.append(f"        Check that IDs/values don't conflict with the new version.")
    lines.append("")
    return lines


def _generate_vanilla_report(game_path, manifest, workspace_dir=None):
    """Generate a structured report of custom additions needing manual re-application.

    Writes a plain-text report listing every custom addition detected, with
    context lines, change type, and actionable instructions per file.
    The user can use this report plus the backup ZIP to re-apply changes.

    Args:
        game_path: Path to the game project.
        manifest: UpgradeManifest with extraction results.
        workspace_dir: Optional TORCH workspace dir for report storage.
            Falls back to <game_path>/backups/upgrade/ if not provided.

    Returns the report file path, or None if no files had additions.
    """
    if not manifest.modified_vanilla_files:
        return None

    entries_with_additions = [
        e for e in manifest.modified_vanilla_files if e.get("additions")
    ]
    if not entries_with_additions:
        return None

    current_str = version_str(manifest.current_version)
    target_str = version_str(manifest.target_version)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_stamp = datetime.now().strftime("%Y-%m-%d")

    # Build report path — prefer workspace, fall back to game dir
    if workspace_dir and os.path.isdir(workspace_dir):
        report_dir = workspace_dir
    else:
        report_dir = os.path.join(game_path, "backups", "upgrade")
    os.makedirs(report_dir, exist_ok=True)
    filename = f"upgrade-report-{date_stamp}.txt"
    report_path = os.path.join(report_dir, filename)

    # Build report content
    lines = []
    lines.append("TORCH Upgrade Report")
    lines.append("=" * 45)
    lines.append(f"Date: {timestamp}")
    lines.append(f"Upgraded: v{current_str} -> v{target_str}")
    if manifest.snapshot_path:
        display = manifest.snapshot_path.replace(os.path.expanduser("~"), "~")
        lines.append(f"Backup: {display}")
    lines.append("")

    lines.extend(_report_auto_handled(manifest))

    lines.append("MANUAL RE-APPLICATION NEEDED")
    lines.append("-" * 45)
    lines.append("")

    for i, entry in enumerate(entries_with_additions, 1):
        lines.extend(_report_file_entry(entry, i))

    lines.append(f"--- End of report ({len(entries_with_additions)} file(s) with changes) ---")
    lines.append("")

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        manifest.vanilla_report_path = report_path
        return report_path
    except OSError:
        return None


def _verify_upgrade(game_path, manifest, settings=None):
    """Trigger a build to verify the upgrade succeeded.

    Returns True if the build succeeded, False otherwise.
    """
    print()
    print(f"  {WHITE}Verifying upgrade with a test build...{RST}")
    print()

    result = _offer_build(
        game_path=game_path,
        trigger="upgrade",
        safe=False,
        auto_build=False,
        diagnose=False,
    )

    if result is True:
        print(f"  {GREEN}Build succeeded! Upgrade verified.{RST}")
        return True
    elif result is False:
        print()
        print(f"  {GOLD}Build failed after upgrade.{RST}")
        print(f"  {DIM}This is expected if your project has custom content in{RST}")
        print(f"  {DIM}vanilla files (flags, tilesets, music, trainers, etc.).{RST}")
        print()
        if manifest.modified_vanilla_files:
            print(f"  {WHITE}Modified files detected ({len(manifest.modified_vanilla_files)}):{RST}")
            for mvf in manifest.modified_vanilla_files[:10]:
                print(f"    {CYAN}{mvf['rel_path']}{RST}")
            if len(manifest.modified_vanilla_files) > 10:
                print(f"    {DIM}... and {len(manifest.modified_vanilla_files) - 10} more{RST}")
            print()
            print(f"  {DIM}Re-apply your custom additions using the report + backup.{RST}")
        report_path = getattr(manifest, "vanilla_report_path", None)
        if report_path:
            display = report_path.replace(os.path.expanduser("~"), "~")
            print(f"  {DIM}Changes report: {display}{RST}")
        if manifest.snapshot_path:
            display_path = manifest.snapshot_path.replace(os.path.expanduser("~"), "~")
            print(f"  {DIM}Backup ZIP:     {display_path}{RST}")
        return False
    else:
        # User declined the build
        print(f"  {DIM}Build skipped. You can build later with{RST} {CYAN}torch build{RST}")
        return True  # Not a failure — just deferred


# ============================================================
# PHASE D — Interactive Wizard & Display
# ============================================================

def _show_plan_vanilla_files(modified_files):
    """Display the modified vanilla files section of the upgrade plan."""
    if not modified_files:
        return
    with_additions = [e for e in modified_files if e.get("additions")]
    without_additions = [e for e in modified_files if not e.get("additions")]
    if with_additions:
        print(f"  {WHITE}Modified vanilla files — custom additions detected ({len(with_additions)}):{RST}")
        for entry in with_additions:
            n = sum(len(b["lines"]) for b in entry["additions"])
            has_replace = any("replaces" in b for b in entry["additions"])
            tag = f" ({n} lines)" if not has_replace else f" ({n} lines, has edits)"
            print(f"    {CYAN}{entry['rel_path']}{RST}{DIM}{tag}{RST}")
        print(f"  {DIM}A report will be generated listing all custom additions.{RST}")
        print(f"  {DIM}You can re-apply these manually after the upgrade.{RST}")
        print()
    if without_additions:
        print(f"  {WHITE}Modified vanilla files — needs manual review ({len(without_additions)}):{RST}")
        for entry in without_additions:
            print(f"    {CYAN}{entry['rel_path']}{RST}")
        print()


def _show_upgrade_plan(manifest):
    """Display everything that will happen before execution."""
    current_str = version_str(manifest.current_version)
    target_str = version_str(manifest.target_version)

    print()
    print(BAR)
    print(f"  {WHITE}Upgrade Plan{RST}")
    print(BAR)
    print()
    print(f"  {DIM}From:{RST}  {CYAN}{current_str}{RST}")
    print(f"  {DIM}To:{RST}    {GREEN}{target_str}{RST}")
    print()

    if manifest.custom_maps:
        print(f"  {WHITE}Custom maps to preserve ({len(manifest.custom_maps)}):{RST}")
        for cmap in manifest.custom_maps:
            layout_tag = " + layout" if cmap["layout_dir"] else ""
            script_tag = " + scripts" if cmap["has_scripts"] else ""
            print(f"    {CYAN}{cmap['name']}{RST}{DIM}{layout_tag}{script_tag}{RST}")
        print()

    if manifest.custom_tilesets:
        print(f"  {WHITE}Custom tilesets to preserve ({len(manifest.custom_tilesets)}):{RST}")
        for ts in manifest.custom_tilesets:
            print(f"    {CYAN}{ts['camel_name']}{RST} {DIM}({ts['kind']}){RST}")
        print()

    if manifest.custom_map_groups:
        total_maps = sum(len(maps) for maps in manifest.custom_map_groups.values())
        print(f"  {WHITE}Custom map group entries to merge ({total_maps}):{RST}")
        for group, maps in manifest.custom_map_groups.items():
            print(f"    {CYAN}{group}{RST}: {DIM}{', '.join(maps)}{RST}")
        print()

    if manifest.custom_layouts:
        print(f"  {WHITE}Custom layout entries to merge ({len(manifest.custom_layouts)}):{RST}")
        for entry in manifest.custom_layouts[:10]:
            print(f"    {CYAN}{entry.get('id', '?')}{RST}")
        if len(manifest.custom_layouts) > 10:
            print(f"    {DIM}... and {len(manifest.custom_layouts) - 10} more{RST}")
        print()

    if manifest.custom_region_map_sections:
        print(f"  {WHITE}Custom region map sections to merge ({len(manifest.custom_region_map_sections)}):{RST}")
        for entry in manifest.custom_region_map_sections:
            print(f"    {CYAN}{_rms_id_key(entry)}{RST}")
        print()

    if manifest.custom_heal_locations:
        hl = manifest.custom_heal_locations
        fmt = hl.get("format", "")
        if fmt == "json":
            entries = hl.get("entries", [])
            print(f"  {WHITE}Custom heal location entries to merge ({len(entries)}):{RST}")
            for entry in entries[:10]:
                print(f"    {CYAN}{entry.get('id', '?')}{RST}")
            if len(entries) > 10:
                print(f"    {DIM}... and {len(entries) - 10} more{RST}")
        elif fmt == "h":
            files = hl.get("files", {})
            print(f"  {WHITE}Custom heal location files to restore ({len(files)}):{RST}")
            for rel_path in files:
                print(f"    {CYAN}{rel_path}{RST}")
        print()

    if manifest.makefile_vars:
        print(f"  {WHITE}Makefile customizations to re-apply:{RST}")
        for var, val in manifest.makefile_vars.items():
            print(f"    {CYAN}{var}{RST} = {DIM}{val}{RST}")
        print()

    _show_plan_vanilla_files(manifest.modified_vanilla_files)

    if manifest.scorch_detected:
        print(f"  {GOLD}NOTE:{RST} SCORCH was previously used on this project.")
        print(f"  {DIM}The upgrade will restore vanilla content. Run{RST} {CYAN}torch scorch{RST}")
        print(f"  {DIM}again after upgrading to re-clean.{RST}")
        print()

    print(f"  {WHITE}Steps:{RST}")
    print(f"    1. Create pre-upgrade backup")
    print(f"    2. Replace project base with {target_str}")
    print(f"    3. Re-inject custom maps, layouts, groups & sections")
    print(f"    4. Re-apply Makefile customizations, heal locations & script includes")
    print(f"    5. Sync enrolled scripts")
    print(f"    6. Build to verify")
    print()


def _show_upgrade_result(manifest, stats):
    """Display the final upgrade result report."""
    files_copied, files_deleted, errors = stats
    current_str = version_str(manifest.current_version)
    target_str = version_str(manifest.target_version)

    print()
    print(BAR)
    print(f"  {WHITE}TORCH -- Upgrade Report{RST}")
    print(BAR)
    print()
    print(f"  {GREEN}Upgraded v{current_str} -> v{target_str}{RST}")
    print()

    # Auto-handled summary
    if manifest.custom_maps:
        n = len(manifest.custom_maps)
        print(f"  {DIM}Custom maps:{RST}     {n} (re-injected automatically)")
    if manifest.custom_tilesets:
        n = len(manifest.custom_tilesets)
        print(f"  {DIM}Custom tilesets:{RST} {n} (re-injected automatically)")
    if manifest.custom_map_groups:
        print(f"  {DIM}Map groups:{RST}      updated")
    if manifest.custom_layouts:
        print(f"  {DIM}Layouts:{RST}         updated")
    if manifest.custom_region_map_sections:
        print(f"  {DIM}Region sections:{RST} updated")
    if manifest.custom_heal_locations:
        print(f"  {DIM}Heal locations:{RST}  updated")
    if manifest.makefile_vars:
        print(f"  {DIM}Makefile vars:{RST}   {len(manifest.makefile_vars)} re-applied")
    print()

    # Vanilla file modifications
    with_adds = 0
    if manifest.modified_vanilla_files:
        with_adds = sum(1 for e in manifest.modified_vanilla_files if e.get("additions"))

    if with_adds:
        report_path = getattr(manifest, "vanilla_report_path", None)
        print(f"  {GOLD}Vanilla file modifications: {with_adds} file(s) need manual re-application{RST}")
        if report_path:
            display = report_path.replace(os.path.expanduser("~"), "~")
            print(f"  {DIM}Report saved: {display}{RST}")
        if manifest.snapshot_path:
            snap_display = manifest.snapshot_path.replace(os.path.expanduser("~"), "~")
            print(f"  {DIM}Backup ZIP:   {snap_display}{RST}")
        print()
        print(f"  {DIM}Open the report and backup side by side to re-apply your changes.{RST}")
    else:
        print(f"  {GREEN}No vanilla file modifications detected.{RST}")

    if errors:
        print()
        print(f"  {GOLD}Warnings ({len(errors)}):{RST}")
        for err in errors[:10]:
            print(f"    {DIM}{err}{RST}")
        if len(errors) > 10:
            print(f"    {DIM}... and {len(errors) - 10} more{RST}")

    if manifest.scorch_detected:
        print()
        print(f"  {GOLD}Reminder:{RST} Run {CYAN}torch scorch{RST} to re-clean vanilla content.")


def _prompt_target_version(current, versions):
    """Prompt the user to select a target version from the available list.

    Returns a version tuple, or None if the user cancels.
    """
    # Filter to versions newer than current
    newer = [v for v in versions if v > current]
    if not newer:
        print(f"  {GREEN}You're already on the latest version!{RST}")
        return None

    current_str = version_str(current)
    print(f"  {WHITE}Current version:{RST} {CYAN}{current_str}{RST}")
    print()

    # Show available upgrades (newest first, cap at 10)
    show_count = min(10, len(newer))
    print(f"  {WHITE}Available upgrades:{RST}")
    for i, v in enumerate(newer[:show_count]):
        v_str = version_str(v)
        latest_tag = f" {GREEN}(latest){RST}" if i == 0 else ""
        print(f"    {_k(str(i + 1))} {CYAN}{v_str}{RST}{latest_tag}")
    if len(newer) > show_count:
        print(f"    {DIM}... and {len(newer) - show_count} older versions{RST}")
    print()

    try:
        choice = input(f"  Upgrade to which version? {DIM}[1]{RST} > ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if choice == "" or choice == "1":
        return newer[0]

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(newer[:show_count]):
            return newer[idx]
        print(f"  {RED}Invalid choice.{RST}")
        return None

    # Allow direct version input like "1.8.0"
    parsed = parse_version_str(choice)
    if parsed and parsed in versions:
        if parsed <= current:
            print(f"  {RED}That version is not newer than your current version.{RST}")
            return None
        return parsed

    print(f"  {RED}Version not found.{RST}")
    return None


def _preflight_checks(game_path):
    """Run all pre-flight checks for an upgrade.

    Returns (current_version_tuple, versions_list) on success,
    or (None, None) on failure (messages already printed).
    """
    if not git_available():
        print(f"  {RED}Git is required for upgrading.{RST}")
        print(f"  {DIM}Install git and try again.{RST}")
        return None, None

    print(f"  {DIM}Checking internet connection...{RST}")
    if not check_connectivity():
        print(f"  {RED}No internet connection.{RST}")
        print(f"  {DIM}Upgrade requires GitHub access to download versions.{RST}")
        return None, None

    variant = _detect_project_variant(game_path)
    if variant != "expansion":
        print(f"  {RED}This doesn't look like a pokeemerald-expansion project.{RST}")
        print(f"  {DIM}Upgrade only works with pokeemerald-expansion.{RST}")
        return None, None

    current = detect_expansion_version(game_path)
    if not current:
        print(f"  {RED}Could not detect the current expansion version.{RST}")
        print(f"  {DIM}Check include/constants/expansion.h{RST}")
        return None, None

    if not _check_disk_space(game_path):
        print(f"  {RED}Not enough disk space (need ~{MIN_DISK_SPACE_GB} GB free).{RST}")
        return None, None

    print(f"  {DIM}Fetching available versions from GitHub...{RST}")
    versions = _fetch_available_versions()
    if versions is None:
        print(f"  {RED}Could not fetch version tags from GitHub.{RST}")
        return None, None
    if not versions:
        print(f"  {DIM}No tagged versions found.{RST}")
        return None, None

    return current, versions


def _clone_with_retry(tag, label):
    """Clone a version tag, retrying once on failure.

    Returns the clone path on success, None on failure.
    """
    path = _clone_version(tag, label)
    if path is not None:
        return path
    print(f"  {DIM}Retrying...{RST}")
    path = _clone_version(tag, label)
    if path is None:
        print(f"  {RED}Clone failed twice. Aborting.{RST}")
    return path


def _post_upgrade_sync(game_path, manifest):
    """Run torch sync to regenerate scripts after an upgrade.

    Custom maps with scripts need their .pory files recompiled to .inc
    so the linker can find the script labels.
    """
    maps_with_scripts = [m for m in manifest.custom_maps if m["has_scripts"]]
    if not maps_with_scripts:
        return

    print()
    print(f"  {WHITE}Syncing {len(maps_with_scripts)} map(s) with scripts...{RST}")

    try:
        from torch.sync import sync_map
        from torch.config import load_config
    except ImportError:
        print(f"  {DIM}Sync not available. Run{RST} {CYAN}torch sync{RST} {DIM}manually.{RST}")
        return

    config = load_config()
    if config is None:
        print(f"  {DIM}Config not loaded. Run{RST} {CYAN}torch sync{RST} {DIM}manually.{RST}")
        return

    workspace, projects, settings = config
    workspace_expanded = os.path.expanduser(workspace)

    # Find the project directory from config that matches this game_path
    project_dir = None
    emotes_conf = os.path.join(workspace_expanded, "config", "emotes.conf")
    for pname, pinfo in projects.items():
        gp = os.path.expanduser(pinfo["game_path"])
        if os.path.realpath(gp) == os.path.realpath(game_path):
            project_dir = os.path.join(workspace_expanded, pname)
            break

    if project_dir is None:
        print(f"  {DIM}Could not find project workspace. Run{RST} {CYAN}torch sync{RST} {DIM}manually.{RST}")
        return

    source_display = project_dir.replace(os.path.expanduser("~"), "~")
    max_snaps = settings.get("max_snapshots", 10)

    synced = 0
    for cmap in maps_with_scripts:
        name = cmap["name"]
        ws_dir = os.path.join(project_dir, name)
        if os.path.isdir(ws_dir):
            if sync_map(name, project_dir, game_path, emotes_conf,
                        source_display, max_snaps):
                synced += 1

    if synced:
        print(f"  {GREEN}Synced {synced} map(s){RST}")
    else:
        print(f"  {DIM}No workspace maps found to sync.{RST}")
        print(f"  {DIM}Run{RST} {CYAN}torch sync{RST} {DIM}after setting up workspaces.{RST}")


def _handle_vanilla_report(game_path, manifest):
    """Generate and display the vanilla file modifications report."""
    if not manifest.modified_vanilla_files:
        return
    with_additions = [
        e for e in manifest.modified_vanilla_files if e.get("additions")
    ]
    if not with_additions:
        return

    print()
    print(f"  {WHITE}Checking for vanilla file modifications...{RST}")
    print(f"  {DIM}Found {len(with_additions)} file(s) with custom additions.{RST}")
    print(f"  {DIM}These cannot be auto-merged (C code requires human judgment).{RST}")
    print()

    workspace_dir = _resolve_report_dir(game_path)
    report_path = _generate_vanilla_report(
        game_path, manifest, workspace_dir=workspace_dir)

    if report_path:
        display = report_path.replace(os.path.expanduser("~"), "~")
        print(f"  {GREEN}Report saved: {display}{RST}")
    if manifest.snapshot_path:
        snap_display = manifest.snapshot_path.replace(
            os.path.expanduser("~"), "~")
        print(f"  {DIM}Backup ZIP:   {snap_display}{RST}")
    print()
    print(f"  {DIM}Open the report alongside your backup to manually re-apply changes.{RST}")


def _execute_upgrade(game_path, manifest, target_path, settings):
    """Confirm, snapshot, replace, re-inject, verify.

    This is the shared execution phase used by both the interactive wizard
    and the --to targeted upgrade.
    """
    import tempfile

    target_str = version_str(manifest.target_version)

    _show_upgrade_plan(manifest)

    try:
        confirm = input(
            f"  Proceed with upgrade? {DIM}(y/N){RST} > "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return

    if confirm not in ("y", "yes"):
        print("  Cancelled.")
        return

    # Snapshot
    print()
    print(f"  {WHITE}Creating pre-upgrade backup...{RST}")
    snapshot_path = _create_upgrade_snapshot(game_path, manifest.current_version)
    if snapshot_path is None:
        print(f"  {RED}Backup failed — no files changed. Aborting.{RST}")
        return
    manifest.snapshot_path = snapshot_path

    # Replace base
    print()
    print(f"  {WHITE}Replacing project base with {target_str}...{RST}")
    custom_names = [m["name"] for m in manifest.custom_maps]
    custom_ts_paths = [ts["path"] for ts in manifest.custom_tilesets]
    stats = _replace_base(game_path, target_path, custom_names,
                           custom_tileset_paths=custom_ts_paths)
    files_copied, files_deleted, errors = stats
    print(f"  {DIM}Copied {files_copied} files, removed {files_deleted} obsolete files{RST}")
    if errors:
        print(f"  {GOLD}{len(errors)} warning(s) during replacement{RST}")

    # Re-inject custom content
    if manifest.custom_maps:
        print(f"  {DIM}Re-injecting {len(manifest.custom_maps)} custom map(s)...{RST}")
        _reinject_custom_maps(game_path, manifest)

    if manifest.custom_tilesets:
        print(f"  {DIM}Re-injecting {len(manifest.custom_tilesets)} custom tileset(s)...{RST}")
        _reinject_custom_tilesets(game_path, manifest)

    if manifest.custom_map_groups:
        print(f"  {DIM}Merging custom map groups...{RST}")
        _reinject_map_groups(game_path, manifest)

    if manifest.custom_layouts:
        print(f"  {DIM}Merging {len(manifest.custom_layouts)} custom layout(s)...{RST}")
        _reinject_layouts(game_path, manifest)

    if manifest.custom_region_map_sections:
        print(f"  {DIM}Merging {len(manifest.custom_region_map_sections)} region map section(s)...{RST}")
        _reinject_region_map_sections(game_path, manifest)

    if manifest.custom_heal_locations:
        print(f"  {DIM}Restoring heal location file(s)...{RST}")
        _reinject_heal_locations(game_path, manifest)

    if manifest.custom_maps:
        es_added = _reinject_event_scripts(game_path, manifest)
        if es_added:
            print(f"  {DIM}Added {es_added} script include(s) to event_scripts.s{RST}")

    if manifest.makefile_vars:
        print(f"  {DIM}Re-applying Makefile customizations...{RST}")
        reapplied = _reinject_makefile_vars(game_path, manifest)
        print(f"  {DIM}{reapplied} variable(s) re-applied{RST}")

    _handle_vanilla_report(game_path, manifest)

    # Sync enrolled scripts (regenerate .pory -> .inc)
    _post_upgrade_sync(game_path, manifest)

    # Report and verify
    _show_upgrade_result(manifest, stats)
    print()
    _verify_upgrade(game_path, manifest, settings)


def _upgrade_wizard(game_path, settings, proj_name):
    """The full interactive upgrade flow."""
    import tempfile

    clear_screen()
    print_logo("Expansion Upgrade", proj_name)
    print(BAR)
    print()

    current, versions = _preflight_checks(game_path)
    if current is None:
        return

    # Select target version
    print()
    target = _prompt_target_version(current, versions)
    if target is None:
        return

    target_str = version_str(target)
    current_str = version_str(current)

    # Clone baseline + target
    print()
    print(f"  {WHITE}Preparing upgrade {current_str} -> {target_str}{RST}")
    print()

    baseline_path = _clone_with_retry(
        f"expansion/{current_str}", f"baseline {current_str}")
    if baseline_path is None:
        return

    target_path = _clone_with_retry(
        f"expansion/{target_str}", f"target {target_str}")
    if target_path is None:
        return

    # Extract custom content and execute
    print()
    staging_dir = tempfile.mkdtemp(prefix="torch_upgrade_staging_")
    try:
        manifest = _extract_custom_content(game_path, baseline_path, staging_dir)
        manifest.current_version = current
        manifest.target_version = target
        manifest.target_path = target_path

        _execute_upgrade(game_path, manifest, target_path, settings)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _targeted_upgrade(game_path, settings, proj_name, target_str):
    """Handle --to X.Y.Z: validate and run the upgrade with a pre-selected target."""
    import tempfile

    target = parse_version_str(target_str)
    if target is None:
        print(f"  {RED}Invalid version format: {target_str}{RST}")
        print(f"  {DIM}Expected format: X.Y.Z (e.g. 1.8.0){RST}")
        return

    clear_screen()
    print_logo("Expansion Upgrade", proj_name)
    print(BAR)
    print()

    current, versions = _preflight_checks(game_path)
    if current is None:
        return

    if target <= current:
        current_str = version_str(current)
        print(f"  {RED}Target version {target_str} is not newer than current ({current_str}).{RST}")
        return

    if target not in versions:
        print(f"  {RED}Version {target_str} not found on GitHub.{RST}")
        newer = [v for v in versions if v > current]
        if newer:
            closest = version_str(newer[0])
            print(f"  {DIM}Latest available: {closest}{RST}")
        return

    target_str_clean = version_str(target)
    current_str = version_str(current)

    # Clone baseline + target
    print()
    print(f"  {WHITE}Preparing upgrade {current_str} -> {target_str_clean}{RST}")
    print()

    baseline_path = _clone_with_retry(
        f"expansion/{current_str}", f"baseline {current_str}")
    if baseline_path is None:
        return

    target_path = _clone_with_retry(
        f"expansion/{target_str_clean}", f"target {target_str_clean}")
    if target_path is None:
        return

    # Extract custom content and execute
    staging_dir = tempfile.mkdtemp(prefix="torch_upgrade_staging_")
    try:
        manifest = _extract_custom_content(game_path, baseline_path, staging_dir)
        manifest.current_version = current
        manifest.target_version = target
        manifest.target_path = target_path

        _execute_upgrade(game_path, manifest, target_path, settings)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


# ============================================================
# ENTRY POINT
# ============================================================

def upgrade_command(args, game_path, settings, proj_name):
    """CLI entry point for `torch upgrade`.

    Routes:
      --check       Show version info only
      --to X.Y.Z    Upgrade directly to a specific version
      (bare)        Interactive wizard
    """
    if "--check" in args:
        _version_check_only(game_path)
        return

    if "--to" in args:
        idx = args.index("--to")
        if idx + 1 < len(args):
            _targeted_upgrade(game_path, settings, proj_name, args[idx + 1])
        else:
            print(f"  {RED}--to requires a version (e.g. --to 1.8.0){RST}")
        return

    _upgrade_wizard(game_path, settings, proj_name)
