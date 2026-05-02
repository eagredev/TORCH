"""Scorch Patcher — patches C/H/S source files after vanilla removal.

After the scorch writer nukes vanilla content, many C source files still
reference now-deleted MAP_*, TRAINER_*, and other vanilla constants.
This module stubs or empties those references so the project compiles.
"""
# TORCH_MODULE: Scorch Patcher
# TORCH_GROUP: Tools
import json
import os
import re
import subprocess


# ============================================================
# MAIN ENTRY POINT
# ============================================================

class PatchReport:
    """Tracks every change made for user review."""

    def __init__(self):
        self.patches = []   # list of {"file", "action", "detail"}
        self.errors = []
        self.flags_reclaimed = 0
        self.flags_blocked = 0
        self.flags_blocked_detail = []

    def add(self, rel_path, action, detail=""):
        self.patches.append({
            "file": rel_path,
            "action": action,
            "detail": detail,
        })


def apply_patches(game_path, plan):
    """Apply all C source patches.  Returns a PatchReport."""
    report = PatchReport()

    # Each patcher is safe to call even if the file doesn't exist
    _patch_battle_setup(game_path, plan, report)
    _patch_gym_leader_rematch_h(game_path, plan, report)
    _patch_rematches_h(game_path, plan, report)
    _patch_roamer(game_path, plan, report)
    _patch_secret_base(game_path, plan, report)
    _patch_post_battle_heal(game_path, plan, report)
    _patch_heal_locations_json(game_path, plan, report)
    _patch_heal_locations_data(game_path, plan, report)
    _patch_heal_locations_h(game_path, plan, report)
    _patch_heal_locations_pkm_center(game_path, plan, report)
    _patch_overworld(game_path, plan, report)
    _patch_overworld_config(game_path, plan, report)
    _patch_field_specials(game_path, plan, report)
    _patch_region_map(game_path, plan, report)
    _patch_tileset_anims_c(game_path, plan, report)
    _patch_tileset_anims_h(game_path, plan, report)
    _patch_metatile_labels(game_path, plan, report)
    _patch_graphics_file_rules(game_path, plan, report)
    _patch_battle_frontier_stubs(game_path, plan, report)
    _patch_regions_h(game_path, plan, report)
    _clean_orphaned_encounters(game_path, report)
    _patch_wild_encounter_generator(game_path, plan, report)
    _patch_map_groups_stubs(game_path, plan, report)
    _patch_event_scripts_s(game_path, plan, report)
    _precompile_poryscript(game_path, report)
    _ensure_custom_map_scripts(game_path, plan, report)
    _stub_missing_script_labels(game_path, plan, report)
    _stub_missing_c_text_labels(game_path, plan, report)
    _stub_missing_localids(game_path, plan, report)
    _patch_trainer_slides_test(game_path, plan, report)
    _patch_map_name_popup(game_path, plan, report)

    # Generic pass: stub any remaining vanilla MAP_* refs in discovered C files
    _patch_generic_map_refs(game_path, plan, report)

    # Reclaim vanilla flags with no surviving references
    _patch_flags(game_path, plan, report)

    # Post-patch repair: un-scorch critical engine functions that may have
    # been incorrectly caught by the generic patcher's cascade logic.
    _repair_scorched_engine_functions(game_path, report)

    return report


# ============================================================
# HELPERS
# ============================================================

def _read_file(path):
    """Read a file, return content or None if not found."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _write_file(path, content):
    """Write content to file.  Returns True on success."""
    try:
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(content)
        return True
    except OSError:
        return False


def _build_vanilla_map_const_set(plan):
    """Build a set of vanilla map C constant names (UPPER_SNAKE form).

    Prefers constants extracted from map_groups.h (handles names like
    SS_TIDAL_CORRIDOR that CamelCase conversion gets wrong).
    Falls back to CamelCase conversion from folder names.
    """
    consts = getattr(plan, 'vanilla_map_consts_from_h', set())
    if consts:
        return set(consts)
    # Fallback: derive from folder names
    result = set()
    for map_name in plan.nuke_maps:
        upper = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", map_name).upper()
        result.add(upper)
    return result


def _build_vanilla_tileset_symbols(plan):
    """Build a set of vanilla tileset PascalCase symbol names.

    plan.vanilla_tilesets contains dicts with "symbol" like "gTileset_Petalburg".
    Returns set of just the name part: {"Petalburg", "BattleFrontierOutsideEast", ...}
    """
    symbols = set()
    for ts in plan.vanilla_tilesets:
        sym = ts.get("symbol", "").replace("gTileset_", "")
        if sym:
            symbols.add(sym)
    return symbols


def _symbol_to_dir_name(symbol):
    """Convert PascalCase tileset symbol to snake_case directory name.

    BattleFrontierOutsideEast -> battle_frontier_outside_east
    """
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", symbol).lower()


# ============================================================
# BATTLE_SETUP.C — Empty the rematch table
# ============================================================

def _patch_battle_setup(game_path, plan, report):
    """Empty the gRematchTable array in battle_setup.c.

    Strategy: Keep the array declaration but remove all entries.
    The engine iterates REMATCH_TABLE_ENTRIES, so we set it to 0 via
    the gym_leader_rematch.h patch.  Here we just empty the initializer.
    """
    path = os.path.join(game_path, "src", "battle_setup.c")
    content = _read_file(path)
    if content is None:
        return

    # Find the gRematchTable array and empty it
    # Pattern: "const struct RematchTrainer gRematchTable[REMATCH_TABLE_ENTRIES] =\n{\n...entries...\n};"
    pattern = re.compile(
        r"(const struct RematchTrainer gRematchTable\[REMATCH_TABLE_ENTRIES\]\s*=\s*\n\{)\n"
        r"(.*?)"
        r"(\n\};)",
        re.DOTALL
    )

    m = pattern.search(content)
    if not m:
        report.errors.append("Could not find gRematchTable in battle_setup.c")
        return

    new_content = pattern.sub(r"\1\n\3", content)

    if _write_file(path, new_content):
        report.add("src/battle_setup.c", "Emptied gRematchTable",
                    "Removed all vanilla rematch trainer entries")


# ============================================================
# GYM_LEADER_REMATCH.H — Reset enum to empty
# ============================================================

def _patch_gym_leader_rematch_h(game_path, plan, report):
    """Stub gym_leader_rematch.h — keep the defines, remove vanilla enum.

    If include/constants/rematches.h exists (v1.14+), keep the include.
    If it doesn't exist (v1.9.x and earlier), inline the stub enum directly.
    """
    path = os.path.join(game_path, "include", "gym_leader_rematch.h")
    content = _read_file(path)
    if content is None:
        return

    # Check if rematches.h exists (v1.14+ split it out)
    rematches_h = os.path.join(game_path, "include", "constants", "rematches.h")
    has_rematches_h = os.path.isfile(rematches_h)

    if has_rematches_h:
        enum_block = "#include \"constants/rematches.h\"\n"
        detail = "Kept rematches.h include, removed enum (defined in rematches.h)"
    else:
        # Inline the stub enum — extract vanilla consts first for generic patcher
        rematch_consts = set(re.findall(r"\b(REMATCH_\w+)\b", content))
        rematch_consts.discard("REMATCH_TABLE_ENTRIES")
        if not hasattr(plan, "vanilla_rematch_consts"):
            plan.vanilla_rematch_consts = set()
        plan.vanilla_rematch_consts |= rematch_consts
        enum_block = (
            "enum {\n"
            "    REMATCH_TABLE_ENTRIES // Scorched: all vanilla rematch entries removed\n"
            "};\n"
        )
        detail = "Inlined stub enum (no rematches.h in this version)"

    new_content = (
        "#ifndef GUARD_TRAINER_REMATCH_H\n"
        "#define GUARD_TRAINER_REMATCH_H\n"
        "\n"
        + enum_block +
        "\n"
        "#define REMATCH_SPECIAL_TRAINER_START   0\n"
        "#define REMATCH_ELITE_FOUR_ENTRIES      0\n"
        "\n"
        "void UpdateGymLeaderRematch(void);\n"
        "\n"
        "#endif //GUARD_TRAINER_REMATCH_H\n"
    )

    if _write_file(path, new_content):
        report.add("include/gym_leader_rematch.h", "Stubbed rematch header",
                    detail)

    # Also stub the .c file — arrays reference REMATCH_* constants
    c_path = os.path.join(game_path, "src", "gym_leader_rematch.c")
    c_content = _read_file(c_path)
    if c_content is None:
        return

    c_stub = (
        "#include \"global.h\"\n"
        "#include \"gym_leader_rematch.h\"\n"
        "\n"
        "// Scorched: vanilla gym leader rematch system removed\n"
        "void UpdateGymLeaderRematch(void) { }\n"
    )

    if _write_file(c_path, c_stub):
        report.add("src/gym_leader_rematch.c", "Stubbed rematch source",
                    "Replaced with no-op (all REMATCH_* constants removed)")


def _patch_rematches_h(game_path, plan, report):
    """Stub rematches.h — minimal enum with only REMATCH_TABLE_ENTRIES.

    Also extracts vanilla REMATCH_* constants and stores them on the plan
    so the generic patcher can catch references in other files.
    """
    path = os.path.join(game_path, "include", "constants", "rematches.h")
    content = _read_file(path)
    if content is None:
        return

    # Extract all REMATCH_* constants before overwriting
    rematch_consts = set(re.findall(r"\b(REMATCH_\w+)\b", content))
    # Don't include the meta-constant we're keeping
    rematch_consts.discard("REMATCH_TABLE_ENTRIES")
    plan.vanilla_rematch_consts = rematch_consts

    new_content = (
        "#ifndef GUARD_REMATCHES_H\n"
        "#define GUARD_REMATCHES_H\n"
        "\n"
        "enum {\n"
        "    REMATCH_TABLE_ENTRIES // Scorched: all vanilla rematch entries removed\n"
        "};\n"
        "\n"
        "#endif // GUARD_REMATCHES_H\n"
    )

    if _write_file(path, new_content):
        report.add("include/constants/rematches.h", "Stubbed rematch enum",
                    "Removed all vanilla rematch entries, kept REMATCH_TABLE_ENTRIES")


# ============================================================
# ROAMER.C — Disable roaming by emptying the location table
# ============================================================

def _patch_roamer(game_path, plan, report):
    """Replace the roamer location table with a minimal stub.

    We keep the sentinel row and one dummy row to avoid softlocks.
    The roamer system will effectively be disabled since there are
    no valid locations.
    """
    path = os.path.join(game_path, "src", "roamer.c")
    content = _read_file(path)
    if content is None:
        return

    # Replace the entire sRoamerLocations table
    pattern = re.compile(
        r"(static const u8 sRoamerLocations\[\]\[6\]\s*=\s*\n\{)\n"
        r"(.*?)"
        r"(\n\};)",
        re.DOTALL
    )

    m = pattern.search(content)
    if not m:
        report.errors.append("Could not find sRoamerLocations in roamer.c")
        return

    # Minimal stub: sentinel row + dummy to avoid division by zero
    # (NUM_LOCATION_SETS = ARRAY_COUNT - 1, so we need >= 2 rows)
    stub_rows = (
        "\n"
        "    { ___, ___, ___, ___, ___, ___ },\n"
        "    { ___, ___, ___, ___, ___, ___ },\n"
    )

    new_content = pattern.sub(r"\g<1>" + stub_rows + r"\g<3>", content)

    if _write_file(path, new_content):
        report.add("src/roamer.c", "Stubbed sRoamerLocations",
                    "Replaced vanilla route table with sentinel-only stub")


# ============================================================
# SECRET_BASE.C — Feature remains but with stubbed data
# ============================================================

def _patch_secret_base(game_path, plan, report):
    """The secret base system references SECRET_BASE_* maps which are vanilla.

    Strategy: Leave the file mostly intact.  The secret base maps themselves
    exist in the vanilla map set and their constants come from map_groups.json
    regeneration via mapjson.  After map removal, mapjson will regenerate
    constants/ without them and the build will fail on these references.

    We comment out the entrance positions array entries and replace with
    a zeroed stub so the struct compiles but the feature is inert.
    """
    path = os.path.join(game_path, "src", "secret_base.c")
    content = _read_file(path)
    if content is None:
        return

    # Replace the sSecretBaseEntrancePositions array contents
    pattern = re.compile(
        r"(static const u8 sSecretBaseEntrancePositions\[NUM_SECRET_BASE_GROUPS \* 4\]\s*=\s*\n\{)\n"
        r"(.*?)"
        r"(\n\};)",
        re.DOTALL
    )

    m = pattern.search(content)
    if not m:
        # Maybe already patched or structure changed
        return

    # Replace with zero-initialized (C allows partial init, rest becomes 0)
    stub = "\n    0,  // Stubbed — vanilla secret base maps removed\n"

    new_content = pattern.sub(r"\g<1>" + stub + r"\g<3>", content)

    if _write_file(path, new_content):
        report.add("src/secret_base.c", "Stubbed sSecretBaseEntrancePositions",
                    "Replaced vanilla secret base entries with zero stub")


# ============================================================
# POST_BATTLE_EVENT_FUNCS.C — Fix GameClear() heal location
# ============================================================

def _patch_post_battle_heal(game_path, plan, report):
    """Replace vanilla heal location refs in GameClear() with custom one."""
    path = os.path.join(game_path, "src", "post_battle_event_funcs.c")
    content = _read_file(path)
    if content is None:
        return

    # Use first custom heal location, or InsideOfTruck as universal fallback.
    # InsideOfTruck always survives Phoenix and always has a heal entry
    # (injected by _patch_heal_locations_json if not already present).
    # Only patch when we have actual heal data — on versions where the
    # scanner can't classify heals, the constants remain valid.
    if plan.custom_heal_ids:
        custom_heal = plan.custom_heal_ids[0][0]
    elif plan.vanilla_heal_ids:
        # Scanner found vanilla heals but no custom ones — use fallback
        custom_heal = "HEAL_LOCATION_INSIDE_OF_TRUCK"
    else:
        # Scanner couldn't classify heals at all — constants still intact
        return

    patched = False
    for vanilla_heal in ("HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F",
                         "HEAL_LOCATION_LITTLEROOT_TOWN_MAYS_HOUSE_2F"):
        if vanilla_heal in content:
            content = content.replace(vanilla_heal, custom_heal)
            patched = True

    if patched and _write_file(path, content):
        report.add("src/post_battle_event_funcs.c",
                    "Replaced vanilla heal locations",
                    f"GameClear() now uses {custom_heal}")


# ============================================================
# HEAL_LOCATIONS.JSON — Clean the source data (build regenerates .h files)
# ============================================================

def _patch_heal_locations_json(game_path, plan, report):
    """Clean src/data/heal_locations.json — remove vanilla entries.

    This is the source of truth: the build regenerates both
    include/constants/heal_locations.h and src/data/heal_locations.h
    from this JSON file.  Removing vanilla entries here means the build
    produces clean headers with only custom heal locations.

    Before removing, we patch any .inc script references (setrespawn)
    that still point to vanilla heal locations — redirecting them to
    HEAL_LOCATION_INSIDE_OF_TRUCK (the engine-required map that Phoenix
    always keeps).
    """
    if not hasattr(plan, 'vanilla_heal_ids') or not hasattr(plan, 'custom_heal_ids'):
        return

    path = os.path.join(game_path, "src", "data", "heal_locations.json")
    if not os.path.isfile(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    locations = data.get("heal_locations", [])
    if not locations:
        return

    vanilla_names = {name for name, _hid in plan.vanilla_heal_ids}
    if not vanilla_names:
        return

    # Fallback: InsideOfTruck is always kept by Phoenix and is the
    # engine-required map.  Use it as the universal safe redirect.
    fallback = "HEAL_LOCATION_INSIDE_OF_TRUCK"

    # Patch .inc script references before removing entries from JSON.
    # Find setrespawn commands that reference vanilla heal locations.
    _patch_heal_script_refs(game_path, vanilla_names, fallback, report)

    # Remove vanilla entries from JSON
    kept = [loc for loc in locations if loc.get("id", "") not in vanilla_names]
    removed = len(locations) - len(kept)

    # Ensure the fallback heal location exists in the kept list.
    # InsideOfTruck is engine-required but may not have had a heal entry.
    has_fallback = any(loc.get("id") == fallback for loc in kept)
    if not has_fallback:
        kept.insert(0, {
            "id": fallback,
            "map": "MAP_INSIDE_OF_TRUCK",
            "x": 0,
            "y": 0,
            "respawn_map": "MAP_INSIDE_OF_TRUCK",
            "respawn_npc": 1,
        })

    if removed == 0:
        return

    data["heal_locations"] = kept

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        report.add("src/data/heal_locations.json",
                    "Removed vanilla heal locations",
                    f"Removed {removed} vanilla entries, kept {len(kept)} custom")
        # Delete stale auto-generated .h files so build system regenerates them
        for stale in [
            os.path.join(game_path, "src", "data", "heal_locations.h"),
            os.path.join(game_path, "include", "constants", "heal_locations.h"),
        ]:
            if os.path.isfile(stale):
                try:
                    os.remove(stale)
                except OSError:
                    pass
    except OSError:
        report.errors.append("Failed to write heal_locations.json")


def _patch_heal_script_refs(game_path, vanilla_names, fallback, report):
    """Patch setrespawn references to vanilla heal locations in .inc scripts.

    Scans data/ for .inc files containing 'setrespawn HEAL_LOCATION_*'
    and redirects any vanilla references to the fallback heal location.
    """
    import glob as _glob

    data_dir = os.path.join(game_path, "data")
    if not os.path.isdir(data_dir):
        return

    patched_files = 0
    patched_refs = 0

    for inc_path in _glob.glob(os.path.join(data_dir, "**", "*.inc"), recursive=True):
        try:
            with open(inc_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue

        if "setrespawn" not in content:
            continue

        new_content = content
        file_refs = 0
        for name in vanilla_names:
            old = f"setrespawn {name}"
            if old in new_content:
                new_content = new_content.replace(old,
                    f"setrespawn {fallback}")
                file_refs += 1

        if file_refs > 0 and new_content != content:
            try:
                with open(inc_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                patched_files += 1
                patched_refs += file_refs
            except OSError:
                pass

    if patched_refs:
        report.add("data/**/*.inc",
                    f"Redirected {patched_refs} setrespawn ref(s) to {fallback}",
                    f"Patched {patched_files} script file(s)")


# ============================================================
# HEAL_LOCATIONS DATA — Remove vanilla entries (fallback for non-JSON projects)
# ============================================================

def _patch_heal_locations_data(game_path, plan, report):
    """Rewrite src/data/heal_locations.h to contain only custom heal points."""
    if not hasattr(plan, 'vanilla_heal_ids') or not hasattr(plan, 'custom_heal_ids'):
        return

    path = os.path.join(game_path, "src", "data", "heal_locations.h")
    content = _read_file(path)
    if content is None:
        return

    # Build set of custom heal location names
    custom_names = {name for name, _hid in plan.custom_heal_ids}

    # Parse the file: keep only lines with custom heal locations
    lines = content.splitlines(keepends=True)
    new_lines = []
    inside_array = False
    for line in lines:
        if "sHealLocations[" in line or "sHealLocations[]" in line:
            inside_array = True
            new_lines.append(line)
            continue
        if inside_array and line.strip() == "};":
            inside_array = False
            new_lines.append(line)
            continue
        if inside_array and line.strip() == "{":
            new_lines.append(line)
            continue

        if inside_array:
            # Check if this line contains a custom heal location
            m = re.search(r"\[(HEAL_LOCATION_\w+)", line)
            if m:
                if m.group(1) in custom_names:
                    new_lines.append(line)
                # Skip vanilla entries
                continue
            # Keep blank lines and comments
            if line.strip() == "" or line.strip().startswith("//"):
                continue

        new_lines.append(line)

    if _write_file(path, "".join(new_lines)):
        removed = len(plan.vanilla_heal_ids)
        report.add("src/data/heal_locations.h", "Stripped vanilla heal locations",
                    f"Removed {removed} vanilla entries, kept {len(plan.custom_heal_ids)} custom")


# ============================================================
# HEAL_LOCATIONS.H CONSTANTS — Remove vanilla defines
# ============================================================

def _patch_heal_locations_h(game_path, plan, report):
    """Remove vanilla #define HEAL_LOCATION_* from the constants header."""
    if not hasattr(plan, 'vanilla_heal_ids') or not hasattr(plan, 'custom_heal_ids'):
        return

    path = os.path.join(game_path, "include", "constants", "heal_locations.h")
    content = _read_file(path)
    if content is None:
        return

    vanilla_names = {name for name, _hid in plan.vanilla_heal_ids}

    lines = content.splitlines(keepends=True)
    new_lines = []
    for line in lines:
        m = re.match(r"^#define\s+(HEAL_LOCATION_\w+)\s+\d+", line)
        if m and m.group(1) in vanilla_names:
            continue
        new_lines.append(line)

    # Renumber the remaining defines sequentially (starting at 1, 0 is NONE)
    # This is needed because heal location IDs must be contiguous
    next_id = 1
    renumbered = []
    for line in new_lines:
        m = re.match(r"^(#define\s+HEAL_LOCATION_)(\w+)(\s+)\d+(.*)$", line)
        if m:
            name = m.group(2)
            if name == "NONE":
                renumbered.append(line)
                continue
            renumbered.append(f"{m.group(1)}{name}{m.group(3)}{next_id}{m.group(4)}\n")
            next_id += 1
        else:
            renumbered.append(line)

    if _write_file(path, "".join(renumbered)):
        report.add("include/constants/heal_locations.h",
                    "Stripped vanilla heal location constants",
                    f"Removed {len(vanilla_names)} vanilla defines, renumbered remaining")


# ============================================================
# HEAL_LOCATIONS_PKM_CENTER.H — Strip vanilla Pokemon Center entries
# ============================================================

def _patch_heal_locations_pkm_center(game_path, plan, report):
    """Strip vanilla entries from heal_locations_pkm_center.h (v1.10+).

    This file has two arrays (sHealLocationsPokemonCenter, sHealNpcLocalId)
    sized by HEAL_LOCATION_COUNT/NUM_HEAL_LOCATIONS and indexed by
    HEAL_LOCATION_* - 1 constants.  After heal removal, vanilla entries
    cause "excess elements" errors.
    """
    vanilla_ids = getattr(plan, 'vanilla_heal_ids', [])
    custom_ids = getattr(plan, 'custom_heal_ids', [])
    # Only run when we have actual heal location data from the scanner.
    # On versions where the scanner can't parse heals (define-based headers),
    # both lists are empty and we should skip — the file is harmless when
    # heal location constants are still fully defined.
    if not vanilla_ids and not custom_ids:
        return

    rel_path = os.path.join("src", "data", "heal_locations_pkm_center.h")
    full_path = os.path.join(game_path, rel_path)
    content = _read_file(full_path)
    if content is None:
        return

    custom_names = {name for name, _hid in custom_ids}

    lines = content.splitlines(keepends=True)
    new_lines = []
    i = 0
    removed_count = 0

    while i < len(lines):
        line = lines[i]

        # Match array *entries* like "    [HEAL_LOCATION_FOO - 1] ="
        # Must start with whitespace+[ to distinguish from array
        # declarations like "sArray[HEAL_LOCATION_COUNT - 1] ="
        m = re.match(r"^\s+\[(HEAL_LOCATION_\w+)\s*-\s*1\]\s*=", line)
        if m:
            heal_name = m.group(1)
            if heal_name not in custom_names:
                # Vanilla entry — determine if struct or simple.
                # A multi-line struct entry has "=" at end-of-line (before
                # optional whitespace), e.g. "[...] =\n".  A simple entry
                # has "= <value>," on the same line (may have comments).
                is_multiline = line.rstrip().endswith("=")
                if not is_multiline:
                    # Simple one-line entry: [HEAL_LOCATION_X - 1] = 1,
                    i += 1
                    removed_count += 1
                    continue
                # Multi-line struct entry: skip to closing },
                i += 1
                while i < len(lines):
                    cur = lines[i].strip()
                    i += 1
                    if cur.startswith("},"):
                        break
                removed_count += 1
                continue

        new_lines.append(line)
        i += 1

    if removed_count > 0 and _write_file(full_path, "".join(new_lines)):
        report.add(rel_path, "Stripped vanilla Pokemon Center heal entries",
                    f"Removed {removed_count} vanilla entries from pkm center arrays")


# ============================================================
# OVERWORLD.C — Stub vanilla music routing functions
# ============================================================

def _patch_overworld(game_path, plan, report):
    """Stub the vanilla-specific music routing functions.

    These functions check hardcoded vanilla MAP_NUM() values.
    We replace each function body with a simple `return FALSE;`.
    """
    path = os.path.join(game_path, "src", "overworld.c")
    content = _read_file(path)
    if content is None:
        return

    patched = False

    # Stub ShouldLegendaryMusicPlayAtLocation
    content, n = _stub_static_bool_function(
        content, "ShouldLegendaryMusicPlayAtLocation")
    if n:
        patched = True

    # Stub NoMusicInSotopolisWithLegendaries
    content, n = _stub_static_bool_function(
        content, "NoMusicInSotopolisWithLegendaries")
    if n:
        patched = True

    # Stub IsInfiltratedWeatherInstitute
    content, n = _stub_static_bool_function(
        content, "IsInfiltratedWeatherInstitute")
    if n:
        patched = True

    # Stub IsInflitratedSpaceCenter (note: typo in original source)
    content, n = _stub_static_bool_function(
        content, "IsInflitratedSpaceCenter")
    if n:
        patched = True

    # Stub the Route 111 sandstorm check in GetCurrLocationDefaultMusic
    # Replace the MAP_GROUP(ROUTE111) check with `if (FALSE)`
    new_content = re.sub(
        r"if\s*\(gSaveBlock1Ptr->location\.mapGroup\s*==\s*MAP_GROUP\(ROUTE111\)"
        r"\s*&&\s*gSaveBlock1Ptr->location\.mapNum\s*==\s*MAP_NUM\(ROUTE111\)"
        r"\s*&&\s*GetSavedWeather\(\)\s*==\s*WEATHER_SANDSTORM\)",
        "if (FALSE)  // Scorched: vanilla Route111 removed",
        content
    )
    if new_content != content:
        content = new_content
        patched = True

    if patched and _write_file(path, content):
        report.add("src/overworld.c", "Stubbed vanilla music routing",
                    "Replaced legend music, weather, and infiltration checks with stubs")


def _patch_overworld_config(game_path, plan, report):
    """Disable the Union Room nurse check.

    With vanilla Pokemon Centers removed, the Union Room no longer exists.
    The nurse script's BufferUnionRoomPlayerName call reads uninitialized
    memory and causes garbled text + hangs if this check is left enabled.
    """
    path = os.path.join(game_path, "include", "config", "overworld.h")
    content = _read_file(path)
    if content is None:
        return

    new_content = re.sub(
        r"(#define\s+OW_UNION_DISABLE_CHECK\s+)FALSE",
        r"\1TRUE   // Scorched: Union Room removed",
        content
    )
    if new_content != content and _write_file(path, new_content):
        report.add("include/config/overworld.h",
                    "Disabled Union Room nurse check",
                    "Set OW_UNION_DISABLE_CHECK to TRUE (no Union Room in phoenixed project)")


def _stub_static_bool_function(content, func_name):
    """Replace a static bool16 function body with `return FALSE;`.

    Returns (new_content, was_patched).
    """
    # Match: "static bool16 FuncName(params)\n{\n...body...\n}"
    # We need to find the function and replace its body
    pattern = re.compile(
        r"(static bool16 " + re.escape(func_name) + r"\([^)]*\)\s*\n)\{"
        r"(.*?)"
        r"\n\}",
        re.DOTALL
    )

    m = pattern.search(content)
    if not m:
        return content, False

    replacement = m.group(1) + "{\n    return FALSE;  // Scorched: vanilla map refs removed\n}"
    new_content = content[:m.start()] + replacement + content[m.end():]
    return new_content, True


# ============================================================
# FIELD_SPECIALS.C — Stub vanilla event checks
# ============================================================

def _patch_field_specials(game_path, plan, report):
    """Stub vanilla-specific functions in field_specials.c.

    - UpdateCyclingRoadState: references ROUTE110_SEASIDE_CYCLING_ROAD_*
    - GetSSTidalLocation: references ROUTE132/133/134
    """
    path = os.path.join(game_path, "src", "field_specials.c")
    content = _read_file(path)
    if content is None:
        return

    vanilla_consts = _build_vanilla_map_const_set(plan)
    patched = False

    # Check if ROUTE110_SEASIDE_CYCLING_ROAD_SOUTH_ENTRANCE is vanilla
    if "ROUTE110_SEASIDE_CYCLING_ROAD_SOUTH_ENTRANCE" in content:
        cycling_road_vanilla = any(
            c.startswith("ROUTE110") for c in vanilla_consts
        )
        if cycling_road_vanilla:
            # Stub UpdateCyclingRoadState to be a no-op
            pattern = re.compile(
                r"(void UpdateCyclingRoadState\(void\)\s*\n)\{"
                r"(.*?)"
                r"\n\}",
                re.DOTALL
            )
            m = pattern.search(content)
            if m:
                replacement = m.group(1) + "{\n    // Scorched: vanilla cycling road removed\n}"
                content = content[:m.start()] + replacement + content[m.end():]
                patched = True

    # Stub GetSSTidalLocation if Route132/133/134 are vanilla
    route_132_vanilla = "ROUTE132" in vanilla_consts
    if route_132_vanilla and "GetSSTidalLocation" in content:
        pattern = re.compile(
            r"(u8 GetSSTidalLocation\([^)]*\)\s*\n)\{"
            r"(.*?)"
            r"\n\}",
            re.DOTALL
        )
        m = pattern.search(content)
        if m:
            # Return SS_TIDAL_LOCATION_CURRENTS (0) with dummy values
            replacement = (
                m.group(1) + "{\n"
                "    // Scorched: vanilla SS Tidal routes removed\n"
                "    *mapGroup = 0;\n"
                "    *mapNum = 0;\n"
                "    *x = 0;\n"
                "    *y = 0;\n"
                "    return SS_TIDAL_LOCATION_CURRENTS;\n"
                "}"
            )
            content = content[:m.start()] + replacement + content[m.end():]
            patched = True

    if patched and _write_file(path, content):
        report.add("src/field_specials.c", "Stubbed vanilla event functions",
                    "Replaced cycling road and SS Tidal functions with stubs")


# ============================================================
# REGION_MAP.C — Stub vanilla region map sections
# ============================================================

def _patch_region_map(game_path, plan, report):
    """Patch region map to handle removed vanilla map sections.

    The region map data is mostly auto-generated from map headers, so
    the main concern is functions that hardcode vanilla MAP_* constants.
    We scan for and stub any such hardcodes.
    """
    path = os.path.join(game_path, "src", "region_map.c")
    content = _read_file(path)
    if content is None:
        return

    vanilla_consts = _build_vanilla_map_const_set(plan)
    patched = False

    # Find case statements or if-blocks that reference vanilla map constants
    # and replace them with comments
    for const in vanilla_consts:
        # Remove case MAP_NUM(VANILLA_MAP): lines from switch statements
        case_pattern = re.compile(
            r"^\s*case MAP_NUM\(" + re.escape(const) + r"\):\s*\n",
            re.MULTILINE
        )
        if case_pattern.search(content):
            content = case_pattern.sub("", content)
            patched = True

    if patched and _write_file(path, content):
        report.add("src/region_map.c", "Removed vanilla map case statements",
                    "Stripped case MAP_NUM() entries for deleted vanilla maps")


# ============================================================
# TILESET_ANIMS.C — Remove vanilla tileset animation code
# ============================================================

def _patch_tileset_anims_c(game_path, plan, report):
    """Strip all animation code for deleted vanilla tilesets from tileset_anims.c.

    Removes: INCBIN arrays, frame sequence arrays, VDest arrays,
    Init* functions, TilesetAnim_* callbacks, QueueAnimTiles_* helpers,
    and their forward declarations.
    """
    path = os.path.join(game_path, "src", "tileset_anims.c")
    content = _read_file(path)
    if content is None:
        return

    vanilla_symbols = _build_vanilla_tileset_symbols(plan)
    if not vanilla_symbols:
        return

    original_len = len(content)

    for sym in vanilla_symbols:
        # Remove INCBIN data arrays:
        #   const u16 gTilesetAnims_<Sym>_*[] = INCBIN_U16("...");
        content = re.sub(
            r"^const u16 gTilesetAnims_" + re.escape(sym) + r"_\w+\[\]\s*=\s*INCBIN_U16\([^)]+\);\s*\n",
            "", content, flags=re.MULTILINE
        )

        # Remove frame sequence pointer arrays:
        #   const u16 *const gTilesetAnims_<Sym>_*[] = { ... };
        content = re.sub(
            r"^const u16 \*const gTilesetAnims_" + re.escape(sym) + r"_\w+\[\]\s*=\s*\{[^}]*\};\s*\n",
            "", content, flags=re.MULTILINE
        )

        # Remove VDest arrays:
        #   u16 *const gTilesetAnims_<Sym>_*_VDests[] = { ... };
        content = re.sub(
            r"^u16 \*const gTilesetAnims_" + re.escape(sym) + r"_\w+\[\]\s*=\s*\{[^}]*\};\s*\n",
            "", content, flags=re.MULTILINE
        )

        # Remove forward declarations:
        #   static void TilesetAnim_<Sym>(u16);
        #   static void QueueAnimTiles_<Sym>_*(u16);
        #   static void QueueAnimTiles_<Sym>_*(u16, u8);
        content = re.sub(
            r"^static void (?:TilesetAnim|QueueAnimTiles)_" + re.escape(sym) + r"[^;]*;\s*\n",
            "", content, flags=re.MULTILINE
        )

        # Remove Init* function definitions (multi-line):
        #   void InitTilesetAnim_<Sym>(void)\n{\n...\n}
        content = re.sub(
            r"void InitTilesetAnim_" + re.escape(sym) + r"\(void\)\s*\n\{[^}]*\}\s*\n",
            "", content
        )

        # Remove TilesetAnim_* callback function definitions (multi-line):
        #   static void TilesetAnim_<Sym>(u16 timer)\n{\n...\n}
        content = re.sub(
            r"static void TilesetAnim_" + re.escape(sym) + r"\(u16 timer\)\s*\n\{[^}]*\}\s*\n",
            "", content
        )

        # Remove QueueAnimTiles_* helper function definitions (multi-line):
        #   static void QueueAnimTiles_<Sym>_*(u16 ...)\n{\n...\n}
        content = re.sub(
            r"static void QueueAnimTiles_" + re.escape(sym) + r"_\w+\([^)]*\)\s*\n\{[^}]*\}\s*\n",
            "", content
        )

    # Clean up excessive blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)

    if len(content) < original_len:
        if _write_file(path, content):
            report.add("src/tileset_anims.c", "Stripped vanilla tileset animations",
                        f"Removed animation code for {len(vanilla_symbols)} vanilla tilesets")


# ============================================================
# TILESET_ANIMS.H — Remove vanilla Init declarations
# ============================================================

def _patch_tileset_anims_h(game_path, plan, report):
    """Remove Init function declarations for deleted vanilla tilesets."""
    path = os.path.join(game_path, "include", "tileset_anims.h")
    content = _read_file(path)
    if content is None:
        return

    vanilla_symbols = _build_vanilla_tileset_symbols(plan)
    if not vanilla_symbols:
        return

    lines = content.splitlines(keepends=True)
    new_lines = []
    removed = 0
    for line in lines:
        m = re.match(r"void InitTilesetAnim_(\w+)\(void\);", line)
        if m and m.group(1) in vanilla_symbols:
            removed += 1
            continue
        new_lines.append(line)

    if removed:
        if _write_file(path, "".join(new_lines)):
            report.add("include/tileset_anims.h", "Stripped vanilla Init declarations",
                        f"Removed {removed} InitTilesetAnim_* declarations")


# ============================================================
# METATILE_LABELS.H — Remove vanilla metatile constants
# ============================================================

def _patch_metatile_labels(game_path, plan, report):
    """Remove metatile label constants for deleted vanilla tilesets.

    Only removes constants that aren't referenced in any C source file.
    Many metatile constants are used in field_door.c, decoration.c, etc.
    and must be kept even if the tileset is gone (they're just numbers).
    """
    path = os.path.join(game_path, "include", "constants", "metatile_labels.h")
    content = _read_file(path)
    if content is None:
        return

    vanilla_symbols = _build_vanilla_tileset_symbols(plan)
    if not vanilla_symbols:
        return

    # Build set of METATILE_* constants that are used in C source
    used_metatiles = _find_used_metatiles(game_path)

    lines = content.splitlines(keepends=True)
    new_lines = []
    removed = 0
    skip_comment = False
    section_has_kept_entries = False
    for line in lines:
        # Check for tileset section comment: "// gTileset_<Name>"
        cm = re.match(r"^// gTileset_(\w+)\s*$", line)
        if cm:
            if cm.group(1) in vanilla_symbols:
                skip_comment = True
                section_has_kept_entries = False
                # Don't remove yet — check if any entries are kept
                continue
            else:
                skip_comment = False
                new_lines.append(line)
                continue

        # Check for metatile constant: "#define METATILE_<Name>_..."
        dm = re.match(r"^#define\s+(METATILE_(\w+?)_\w+)", line)
        if dm and dm.group(2) in vanilla_symbols:
            const_name = dm.group(1)
            if const_name in used_metatiles:
                # Keep it — referenced in C source
                if not section_has_kept_entries and skip_comment:
                    # Re-add the section comment since we're keeping entries
                    new_lines.append(f"// gTileset_{dm.group(2)} (kept: referenced in source)\n")
                    section_has_kept_entries = True
                new_lines.append(line)
            else:
                removed += 1
            continue

        # Skip blank lines in removed sections with no kept entries
        if skip_comment and not section_has_kept_entries and line.strip() == "":
            continue

        skip_comment = False
        section_has_kept_entries = False
        new_lines.append(line)

    # Clean up excessive blank lines
    result = "".join(new_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)

    if removed:
        if _write_file(path, result):
            report.add("include/constants/metatile_labels.h",
                        "Stripped unused vanilla metatile labels",
                        f"Removed {removed} unreferenced vanilla metatile constants")


def _find_used_metatiles(game_path):
    """Scan all .c/.h files in src/ for METATILE_* constant usage."""
    used = set()
    pattern = re.compile(r"\bMETATILE_(\w+)")
    src_dir = os.path.join(game_path, "src")
    if not os.path.isdir(src_dir):
        return used
    for dirpath, _dirs, files in os.walk(src_dir):
        for fname in files:
            if not fname.endswith((".c", ".h")):
                continue
            fpath = os.path.join(dirpath, fname)
            content = _read_file(fpath)
            if content is None:
                continue
            for m in pattern.finditer(content):
                used.add(f"METATILE_{m.group(1)}")
    return used


# ============================================================
# GRAPHICS_FILE_RULES.MK — Remove vanilla tileset build rules
# ============================================================

def _patch_graphics_file_rules(game_path, plan, report):
    """Remove Makefile build rules for deleted vanilla tileset directories."""
    path = os.path.join(game_path, "graphics_file_rules.mk")
    content = _read_file(path)
    if content is None:
        return

    vanilla_symbols = _build_vanilla_tileset_symbols(plan)
    if not vanilla_symbols:
        return

    # Build set of directory names from symbols
    vanilla_dirs = {_symbol_to_dir_name(sym) for sym in vanilla_symbols}

    lines = content.splitlines(keepends=True)
    new_lines = []
    removed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if this line references a vanilla tileset directory
        # Pattern: $(TILESETGFXDIR)/secondary/<dir_name>/...
        skip = False
        for vdir in vanilla_dirs:
            if f"secondary/{vdir}/" in line:
                skip = True
                break

        if skip:
            removed += 1
            i += 1
            # Skip continuation lines (indented command lines following the rule)
            while i < len(lines) and lines[i].startswith("\t"):
                i += 1
            # Skip blank line after rule
            if i < len(lines) and lines[i].strip() == "":
                i += 1
            continue

        new_lines.append(line)
        i += 1

    if removed:
        if _write_file(path, "".join(new_lines)):
            report.add("graphics_file_rules.mk",
                        "Stripped vanilla tileset build rules",
                        f"Removed {removed} Makefile rules for deleted tilesets")


# ============================================================
# BATTLE FRONTIER STUBS — Missing symbol declarations
# ============================================================

# Stub blocks keyed by relative path.  Inserted after the last #include.
# Frontier layout constants removed by Phoenix — needed by multiple frontier files.
# Using #ifndef guards so they're safe on versions where layouts still exist.
_FRONTIER_LAYOUT_STUBS = (
    "#ifndef LAYOUT_BATTLE_FRONTIER_BATTLE_FACTORY_PRE_BATTLE_ROOM\n"
    "#define LAYOUT_BATTLE_FRONTIER_BATTLE_FACTORY_PRE_BATTLE_ROOM 0\n"
    "#define LAYOUT_BATTLE_FRONTIER_BATTLE_FACTORY_BATTLE_ROOM 0\n"
    "#define LAYOUT_BATTLE_FRONTIER_BATTLE_PIKE_THREE_PATH_ROOM 0\n"
    "#define LAYOUT_BATTLE_FRONTIER_BATTLE_PIKE_ROOM_NORMAL 0\n"
    "#define LAYOUT_BATTLE_FRONTIER_BATTLE_PIKE_ROOM_WILD_MONS 0\n"
    "#define LAYOUT_BATTLE_FRONTIER_BATTLE_PIKE_ROOM_UNUSED 0\n"
    "#define LAYOUT_BATTLE_FRONTIER_BATTLE_PYRAMID_FLOOR 0\n"
    "#define LAYOUT_BATTLE_FRONTIER_BATTLE_PYRAMID_TOP 0\n"
    "#endif\n"
)

_FRONTIER_STUBS = {
    "src/battle_pike.c": (
        "// Scorched: stub declarations for removed Battle Frontier symbols\n"
        + _FRONTIER_LAYOUT_STUBS +
        "\n"
    ),
    "src/battle_pyramid.c": (
        "// Scorched: stub declarations for removed Battle Frontier symbols\n"
        + _FRONTIER_LAYOUT_STUBS +
        "#ifndef BATTLE_PYRAMID_FUNC_IS_IN\n"
        "#define BATTLE_PYRAMID_FUNC_IS_IN 12\n"
        "#endif\n"
        "#ifndef BATTLE_PYRAMID_FUNC_CURRENT_LOCATION\n"
        "#define BATTLE_PYRAMID_FUNC_CURRENT_LOCATION BATTLE_PYRAMID_FUNC_IS_IN\n"
        "#endif\n"
        "u8 InBattlePyramid(void);\n"
        "#pragma GCC diagnostic ignored \"-Wunused-variable\"\n"
        "#pragma GCC diagnostic ignored \"-Wunused-but-set-variable\"\n"
        "#pragma GCC diagnostic ignored \"-Wunused-function\"\n"
        "#pragma GCC diagnostic ignored \"-Wuninitialized\"\n"
        "#pragma GCC diagnostic ignored \"-Wmaybe-uninitialized\"\n"
        "#pragma GCC diagnostic ignored \"-Wreturn-type\"\n"
        "\n"
    ),
    "src/battle_tower.c": (
        "// Scorched: suppress warnings for cascaded scorch in Battle Tower\n"
        "#pragma GCC diagnostic ignored \"-Wunused-variable\"\n"
        "#pragma GCC diagnostic ignored \"-Wunused-but-set-variable\"\n"
        "#pragma GCC diagnostic ignored \"-Wunused-function\"\n"
        "#pragma GCC diagnostic ignored \"-Wuninitialized\"\n"
        "#pragma GCC diagnostic ignored \"-Wmaybe-uninitialized\"\n"
        "#pragma GCC diagnostic ignored \"-Wreturn-type\"\n"
        "\n"
    ),
    "src/battle_tent.c": (
        "// Scorched: stub layout constants for removed Battle Tent maps\n"
        "#ifndef LAYOUT_BATTLE_TENT_CORRIDOR\n"
        "#define LAYOUT_BATTLE_TENT_CORRIDOR 0\n"
        "#define LAYOUT_BATTLE_TENT_BATTLE_ROOM 0\n"
        "#endif\n"
        "\n"
    ),
    "src/battle_setup.c": (
        "// Scorched: stub rematch constant + suppress dead code warnings\n"
        "#pragma GCC diagnostic ignored \"-Wuninitialized\"\n"
        "#pragma GCC diagnostic ignored \"-Wmaybe-uninitialized\"\n"
        "#pragma GCC diagnostic ignored \"-Wunused-function\"\n"
        "#pragma GCC diagnostic ignored \"-Warray-bounds\"\n"
        "#pragma GCC diagnostic ignored \"-Wdangling-else\"\n"
        "\n"
    ),
    "src/field_player_avatar.c": (
        "// Scorched: suppress warnings for orphaned declarations\n"
        "#pragma GCC diagnostic ignored \"-Wunused-function\"\n"
        "\n"
    ),
    "src/field_specials.c": (
        "// Scorched: stub LOCALIDs + suppress warnings for dead code\n"
        "#ifndef LOCALID_BIRTH_ISLAND_EXTERIOR_ROCK\n"
        "#define LOCALID_BIRTH_ISLAND_EXTERIOR_ROCK 1\n"
        "#endif\n"
        "#pragma GCC diagnostic ignored \"-Wswitch-unreachable\"\n"
        "#pragma GCC diagnostic ignored \"-Warray-bounds\"\n"
        "\n"
    ),
    "src/heal_location.c": (
        "// Scorched: suppress warnings for functions orphaned by heal location removal\n"
        "#pragma GCC diagnostic ignored \"-Wunused-function\"\n"
        "#pragma GCC diagnostic ignored \"-Warray-bounds\"\n"
        "\n"
    ),
    "src/region_map.c": (
        "// Scorched: stub MAP_SS_TIDAL + suppress warnings\n"
        "#ifndef MAP_SS_TIDAL_CORRIDOR\n"
        "#define MAP_SS_TIDAL_CORRIDOR MAP_INSIDE_OF_TRUCK\n"
        "#define MAP_SS_TIDAL_LOWER_DECK MAP_INSIDE_OF_TRUCK\n"
        "#define MAP_SS_TIDAL_ROOMS MAP_INSIDE_OF_TRUCK\n"
        "#endif\n"
        "#pragma GCC diagnostic ignored \"-Warray-bounds\"\n"
        "\n"
    ),
    "src/match_call.c": (
        "// Scorched: suppress warnings for dead code after rematch removal\n"
        "#pragma GCC diagnostic ignored \"-Wuninitialized\"\n"
        "#pragma GCC diagnostic ignored \"-Wmaybe-uninitialized\"\n"
        "#pragma GCC diagnostic ignored \"-Warray-bounds\"\n"
        "\n"
    ),
    "src/pokenav_match_call_data.c": (
        "// Scorched: stub E4/champion registration flags (rematch system removed)\n"
        "#ifndef FLAG_REMATCH_SIDNEY\n"
        "#define FLAG_REMATCH_SIDNEY 0\n"
        "#define FLAG_REMATCH_PHOEBE 0\n"
        "#define FLAG_REMATCH_GLACIA 0\n"
        "#define FLAG_REMATCH_DRAKE 0\n"
        "#define FLAG_REMATCH_WALLACE 0\n"
        "#endif\n"
        "#ifndef FLAG_REGISTERED_SIDNEY\n"
        "#define FLAG_REGISTERED_SIDNEY 0\n"
        "#define FLAG_REGISTERED_PHOEBE 0\n"
        "#define FLAG_REGISTERED_GLACIA 0\n"
        "#define FLAG_REGISTERED_DRAKE 0\n"
        "#define FLAG_REGISTERED_WALLACE 0\n"
        "#endif\n"
        "#pragma GCC diagnostic ignored \"-Warray-bounds\"\n"
        "\n"
    ),
    "src/secret_base.c": (
        "// Scorched: suppress warnings for dead code after map removal\n"
        "#pragma GCC diagnostic ignored \"-Wreturn-type\"\n"
        "#pragma GCC diagnostic ignored \"-Wmaybe-uninitialized\"\n"
        "\n"
    ),
    "src/pokemon.c": (
        "// Scorched: suppress warnings for dead code after vanilla removal\n"
        "#pragma GCC diagnostic ignored \"-Wreturn-type\"\n"
        "\n"
    ),
    "src/trainer_hill.c": (
        "// Scorched: suppress warnings for dead code after Battle Frontier removal\n"
        "#pragma GCC diagnostic ignored \"-Wreturn-type\"\n"
        "\n"
    ),
    "src/tv.c": (
        "// Scorched: stub LOCALIDs + suppress warnings for dead code after vanilla removal\n"
        "#ifndef LOCALID_ROUTE111_GABBY_1\n"
        "#define LOCALID_ROUTE111_GABBY_1 1\n"
        "#define LOCALID_ROUTE111_TY_1 2\n"
        "#define LOCALID_ROUTE111_GABBY_2 1\n"
        "#define LOCALID_ROUTE111_TY_2 2\n"
        "#define LOCALID_ROUTE111_GABBY_3 1\n"
        "#define LOCALID_ROUTE111_TY_3 2\n"
        "#define LOCALID_ROUTE118_GABBY_1 1\n"
        "#define LOCALID_ROUTE118_TY_1 2\n"
        "#define LOCALID_ROUTE118_GABBY_2 1\n"
        "#define LOCALID_ROUTE118_TY_2 2\n"
        "#define LOCALID_ROUTE118_GABBY_3 1\n"
        "#define LOCALID_ROUTE118_TY_3 2\n"
        "#define LOCALID_ROUTE120_GABBY_1 1\n"
        "#define LOCALID_ROUTE120_TY_1 2\n"
        "#define LOCALID_ROUTE120_GABBY_2 1\n"
        "#define LOCALID_ROUTE120_TY_2 2\n"
        "#define LOCALID_TOWER_LOBBY_REPORTER 1\n"
        "#endif\n"
        "#pragma GCC diagnostic ignored \"-Wswitch-unreachable\"\n"
        "#pragma GCC diagnostic ignored \"-Warray-bounds\"\n"
        "\n"
    ),
    "src/vs_seeker.c": (
        "// Scorched: suppress warnings for empty rematch table access\n"
        "#pragma GCC diagnostic ignored \"-Warray-bounds\"\n"
        "#pragma GCC diagnostic ignored \"-Wmaybe-uninitialized\"\n"
        "\n"
    ),
    "src/pokenav_match_call_list.c": (
        "// Scorched: suppress warnings for empty rematch table access\n"
        "#pragma GCC diagnostic ignored \"-Warray-bounds\"\n"
        "\n"
    ),
    "src/faraway_island.c": (
        "// Scorched: stub LOCALID for removed Faraway Island map\n"
        "#ifndef LOCALID_FARAWAY_ISLAND_MEW\n"
        "#define LOCALID_FARAWAY_ISLAND_MEW 1\n"
        "#endif\n"
        "\n"
    ),
    "src/contest_util.c": (
        "// Scorched: stub LOCALIDs for removed Contest Hall map\n"
        "#ifndef LOCALID_CONTESTANT_1\n"
        "#define LOCALID_CONTESTANT_1 1\n"
        "#define LOCALID_CONTESTANT_2 2\n"
        "#define LOCALID_CONTESTANT_3 3\n"
        "#define LOCALID_CONTESTANT_4 4\n"
        "#endif\n"
        "\n"
    ),
    "src/mirage_tower.c": (
        "// Scorched: stub LOCALID for removed Route 111 map\n"
        "#ifndef LOCALID_ROUTE111_PLAYER_FALLING\n"
        "#define LOCALID_ROUTE111_PLAYER_FALLING 1\n"
        "#endif\n"
        "\n"
    ),
    "src/union_room_player_avatar.c": (
        "// Scorched: stub LOCALIDs for removed Union Room map\n"
        "#ifndef LOCALID_UNION_ROOM_PLAYER_1\n"
        "#define LOCALID_UNION_ROOM_PLAYER_1 1\n"
        "#define LOCALID_UNION_ROOM_PLAYER_2 2\n"
        "#define LOCALID_UNION_ROOM_PLAYER_3 3\n"
        "#define LOCALID_UNION_ROOM_PLAYER_4 4\n"
        "#define LOCALID_UNION_ROOM_PLAYER_5 5\n"
        "#define LOCALID_UNION_ROOM_PLAYER_6 6\n"
        "#define LOCALID_UNION_ROOM_PLAYER_7 7\n"
        "#define LOCALID_UNION_ROOM_PLAYER_8 8\n"
        "#endif\n"
        "\n"
    ),
}


def _patch_battle_frontier_stubs(game_path, plan, report):
    """Add stub declarations for missing Battle Frontier symbols.

    battle_pike.c and battle_pyramid.c reference symbols that were removed
    in expansion upgrades.  These stubs make the code compile without
    modifying the function bodies.
    """
    # Build dynamic stubs for battle_factory.c based on expansion version.
    # Older expansions (pre-v1.10) have FacilityMon with itemTableId/evSpread
    # and gBattleFrontierHeldItems.  Newer ones merged into TrainerMon.
    stubs = dict(_FRONTIER_STUBS)
    tower_h = _read_file(os.path.join(game_path, "include", "battle_tower.h"))
    has_facility_mon = tower_h is not None and "struct FacilityMon" in tower_h

    # Common stubs needed by both old and new expansions: warning suppression
    # for dead code + frontier layout constants (handled by _FRONTIER_LAYOUT_STUBS).
    _factory_common = (
        "#pragma GCC diagnostic ignored \"-Wunused-variable\"\n"
        "#pragma GCC diagnostic ignored \"-Wunused-but-set-variable\"\n"
        "#pragma GCC diagnostic ignored \"-Wunused-function\"\n"
        "#pragma GCC diagnostic ignored \"-Wreturn-type\"\n"
        + _FRONTIER_LAYOUT_STUBS
    )

    if has_facility_mon:
        # Old expansion: symbols exist, just suppress warnings + stub layouts
        stubs["src/battle_factory.c"] = (
            "// Scorched: suppress warnings for dead Battle Factory code\n"
            + _factory_common +
            "\n"
        )
    else:
        # New expansion: FacilityMon merged into TrainerMon, need compat stubs
        stubs["src/battle_factory.c"] = (
            "// Scorched: stub declarations for removed Battle Frontier symbols\n"
            + _factory_common +
            "static u16 _scorched_opponent_a;\n"
            "#define gTrainerBattleOpponent_A _scorched_opponent_a\n"
            "static const u16 gBattleFrontierHeldItems[] = {0};\n"
            "#define itemTableId heldItem\n"
            "#define evSpread ev[0]\n"
            "\n"
        )

    for rel_path, stub_block in stubs.items():
        full_path = os.path.join(game_path, rel_path)
        content = _read_file(full_path)
        if content is None:
            continue

        # Skip if already patched (exact match or variant with different values)
        first_line = stub_block.split("\n", 1)[0]
        if stub_block in content or first_line in content:
            continue

        # Find the end of the top-level #include block (not inline data includes)
        lines = content.splitlines(keepends=True)
        insert_idx = 0
        found_include = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#include"):
                insert_idx = i + 1
                found_include = True
            elif found_include and (stripped == "" or stripped.startswith("//")):
                continue  # allow blank lines and comments within include block
            elif found_include:
                break  # first non-include, non-blank, non-comment line ends block

        # Insert stubs after last #include
        lines.insert(insert_idx, "\n" + stub_block)
        if _write_file(full_path, "".join(lines)):
            report.add(rel_path, "Added Battle Frontier stub declarations",
                        "Stub declarations for symbols removed in expansion upgrade")

    # Fix GetAiScriptsInBattleFactory return type mismatch (header vs source)
    factory_h = os.path.join(game_path, "include", "battle_factory.h")
    factory_c = os.path.join(game_path, "src", "battle_factory.c")
    header_content = _read_file(factory_h)
    factory_content = _read_file(factory_c)
    if header_content and factory_content:
        # Detect what the header declares and fix source to match
        if "u64 GetAiScriptsInBattleFactory" in header_content and \
           "u32 GetAiScriptsInBattleFactory" in factory_content:
            factory_content = factory_content.replace(
                "u32 GetAiScriptsInBattleFactory",
                "u64 GetAiScriptsInBattleFactory")
            if _write_file(factory_c, factory_content):
                report.add("src/battle_factory.c",
                            "Fixed GetAiScriptsInBattleFactory return type (u32 -> u64)",
                            "Header declares u64, source had u32")
        elif "u32 GetAiScriptsInBattleFactory" in header_content and \
             "u64 GetAiScriptsInBattleFactory" in factory_content:
            factory_content = factory_content.replace(
                "u64 GetAiScriptsInBattleFactory",
                "u32 GetAiScriptsInBattleFactory")
            if _write_file(factory_c, factory_content):
                report.add("src/battle_factory.c",
                            "Fixed GetAiScriptsInBattleFactory return type (u64 -> u32)",
                            "Header declares u32, source had u64")


# ============================================================
# REGIONS.H — stub Kanto MAPSEC range macros (v1.15.0+)
# ============================================================

_KANTO_MAPSEC_STUB = (
    "// Scorched: stub Kanto MAPSEC range macros removed by Phoenix\n"
    "#ifndef KANTO_MAPSEC_START\n"
    "#define KANTO_MAPSEC_START 0\n"
    "#define KANTO_MAPSEC_END   0\n"
    "#define KANTO_MAPSEC_COUNT 0\n"
    "#endif\n"
    "#ifndef MAPSEC_SPECIAL_AREA\n"
    "#define MAPSEC_SPECIAL_AREA 0\n"
    "#endif\n"
)


def _patch_regions_h(game_path, plan, report):
    """Stub KANTO_MAPSEC_START/END/COUNT in include/regions.h.

    Expansion v1.15.0+ rewrote regions.h to add GetRegionForSectionId()
    which references KANTO_MAPSEC_START.  After Phoenix removes all Kanto
    map sections from the JSON source, the auto-generated header no longer
    defines these macros.  We inject #ifndef stubs so the code compiles.

    Content-detected: only patches if the file actually references
    KANTO_MAPSEC_START.  Older expansions (v1.14.x and below) don't
    need this and are skipped automatically.
    """
    rel_path = "include/regions.h"
    full_path = os.path.join(game_path, rel_path)
    content = _read_file(full_path)
    if content is None:
        return

    # Content-based gate: only patch if the file references Kanto/MAPSEC
    # constants that Phoenix removes.  No need to check vanilla_mapsecs —
    # these constants aren't tied to map directories so they're not in
    # plan.vanilla_mapsecs.  They get removed from the JSON whenever
    # Phoenix runs, which breaks this header.
    if "KANTO_MAPSEC_START" not in content and "MAPSEC_SPECIAL_AREA" not in content:
        return

    # Skip if already patched
    if _KANTO_MAPSEC_STUB in content:
        return

    # Insert stubs after the last #include line
    lines = content.splitlines(keepends=True)
    insert_idx = 0
    found_include = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#include"):
            insert_idx = i + 1
            found_include = True
        elif found_include and (stripped == "" or stripped.startswith("//")):
            continue
        elif found_include:
            break

    lines.insert(insert_idx, "\n" + _KANTO_MAPSEC_STUB)
    if _write_file(full_path, "".join(lines)):
        report.add(rel_path, "Added Kanto MAPSEC stub defines",
                    "Stub #defines for KANTO_MAPSEC_START/END/COUNT removed by Phoenix")


# ============================================================
# ORPHANED ENCOUNTER CLEANUP — remove entries for deleted maps
# ============================================================

def _clean_orphaned_encounters(game_path, report):
    """Remove encounter entries from wild_encounters.json for deleted maps.

    The scorch scanner may miss some vanilla encounters (e.g. Magma Hideout
    sub-floors, Mirage Tower floors).  After map directories are deleted,
    any encounter referencing a map whose folder no longer exists is orphaned.
    wild_encounters.h is auto-generated from the JSON, so cleaning the JSON
    prevents undefined MAP_* errors at compile time.
    """
    enc_path = os.path.join(game_path, "src", "data", "wild_encounters.json")
    if not os.path.isfile(enc_path):
        return

    try:
        with open(enc_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    maps_dir = os.path.join(game_path, "data", "maps")

    # Build set of map constants that still have directories on disk
    surviving_map_consts = set()
    if os.path.isdir(maps_dir):
        for entry in os.listdir(maps_dir):
            if os.path.isdir(os.path.join(maps_dir, entry)):
                upper = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", entry).upper()
                surviving_map_consts.add(f"MAP_{upper}")

    groups = data.get("wild_encounter_groups", [])
    total_removed = 0
    for group in groups:
        encounters = group.get("encounters", [])
        kept = []
        for enc in encounters:
            map_const = enc.get("map", "")
            if not map_const:
                kept.append(enc)
                continue
            # Extract the map name from MAP_CONSTANT — need to check if
            # the map directory exists.  The constant format is MAP_MAP_NAME
            # but the directory is in CamelCase.  Cross-check with surviving set.
            if map_const in surviving_map_consts:
                kept.append(enc)
            else:
                total_removed += 1
        group["encounters"] = kept

    if total_removed == 0:
        return

    try:
        with open(enc_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        report.add("src/data/wild_encounters.json",
                   f"Removed {total_removed} orphaned encounter(s) for deleted maps")
    except OSError:
        report.errors.append("Failed to write wild_encounters.json")


def _patch_wild_encounter_generator(game_path, plan, report):
    """Patch the wild encounter header generator for empty gWildMonHeaders.

    Pre-1.14 versions of the generator script don't emit a definition for
    gWildMonHeaders when the encounters list is empty.  This causes a linker
    error because src/wild_encounter.c references the extern symbol.  The fix:
    patch the Python generator script to emit an empty array with a terminator
    entry when a group has no encounters.
    """
    # Check if gWildMonHeaders encounters are actually empty
    enc_path = os.path.join(game_path, "src", "data", "wild_encounters.json")
    if not os.path.isfile(enc_path):
        return

    try:
        with open(enc_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    has_empty_group = False
    for group in data.get("wild_encounter_groups", []):
        if group.get("for_maps") and len(group.get("encounters", [])) == 0:
            has_empty_group = True
            break

    if not has_empty_group:
        return

    # Check if the generator already handles empty groups (v1.14+)
    gen_path = os.path.join(game_path, "tools", "wild_encounters",
                            "wild_encounters_to_header.py")
    if not os.path.isfile(gen_path):
        return

    content = _read_file(gen_path)
    if content is None:
        return

    # v1.14+ generators handle empty groups — check for the fix marker
    if "empty_group_stub" in content or "SCORCHED" in content:
        return

    # Patch: after PrintWildMonHeadersContent's group loop, add empty group handling.
    # We inject a new function and modify PrintWildMonHeadersContent to call it.
    # The safest approach: patch the headerIndex loop to handle empty encounters.
    # Instead of modifying the complex generator, inject a post-processing step
    # at the end of ImportWildEncounterFile that adds an empty array if needed.
    patch_marker = "# Scorched: handle empty encounter groups\n"
    if patch_marker in content:
        return

    # Find the call to PrintWildMonHeadersContent() and add empty group handling
    target = "    PrintWildMonHeadersContent()\n"
    if target not in content:
        return

    # Add a post-processing check after PrintWildMonHeadersContent
    fix = (
        "    PrintWildMonHeadersContent()\n"
        "    # Scorched: handle empty encounter groups\n"
        "    for _sc_gi, _sc_g in enumerate(wData['wild_encounter_groups']):\n"
        "        _sc_label = _sc_g.get('label', '')\n"
        "        _sc_enc = _sc_g.get('encounters', [])\n"
        "        if _sc_g.get('for_maps') and len(_sc_enc) == 0 and _sc_label:\n"
        "            print(f'const struct WildPokemonHeader {_sc_label}[] =')\n"
        "            print('{')\n"
        "            print('    {0},')\n"
        "            print('};')\n"
    )

    new_content = content.replace(target, fix)
    if _write_file(gen_path, new_content):
        report.add(
            "tools/wild_encounters/wild_encounters_to_header.py",
            "Patched generator for empty encounter groups",
            "Pre-1.14 generator doesn't emit gWildMonHeaders when encounters are empty"
        )


# ============================================================
# CUSTOM CONTENT STUBS — Define missing vanilla constants
# ============================================================

def _patch_map_groups_stubs(game_path, plan, report):
    """Add .equiv stubs for removed constants used by surviving assembly.

    Handles MAP_*, HEAL_LOCATION_*, and TRAINER_* constants that were removed
    but are still referenced by custom maps or surviving shared scripts.
    Uses .equiv with .ifndef guards in event_scripts.s and map_events.s.
    """
    keep_maps = getattr(plan, 'keep_maps', set())

    vanilla_consts = _build_vanilla_map_const_set(plan)
    vanilla_heal_names = {name for name, _hid in getattr(plan, 'vanilla_heal_ids', set())}

    map_refs = set()     # vanilla MAP_* names (without MAP_ prefix)
    heal_refs = set()    # vanilla HEAL_LOCATION_* names
    trainer_refs = set() # undefined TRAINER_* names

    if vanilla_consts:
        vanilla_map_pat = re.compile(
            r'\bMAP_(' + '|'.join(re.escape(c) for c in vanilla_consts) + r')\b'
        )
    else:
        vanilla_map_pat = None

    # Build set of defined TRAINER_* constants from ALL headers.
    # opponents.h has trainer IDs, battle_setup.h has command types,
    # other headers may have more.  Any #define TRAINER_* is already
    # available to the C preprocessor and must NOT get .equiv stubs
    # (the preprocessor would expand the name before the assembler
    # sees .ifndef, causing "invalid identifier" errors).
    defined_trainers = set()
    inc_dir = os.path.join(game_path, "include")
    if os.path.isdir(inc_dir):
        for root, _dirs, files in os.walk(inc_dir):
            for fname in files:
                if not fname.endswith(".h"):
                    continue
                hcontent = _read_file(os.path.join(root, fname))
                if hcontent:
                    for m in re.finditer(r'#define\s+(TRAINER_\w+)', hcontent):
                        defined_trainers.add(m.group(1))

    # Build set of defined HEAL_LOCATION_* constants from heal_locations.h
    defined_heals = set()
    hl_path = os.path.join(game_path, "include", "constants", "heal_locations.h")
    hl_content = _read_file(hl_path)
    if hl_content:
        for m in re.finditer(r'#define\s+(HEAL_LOCATION_\w+)', hl_content):
            defined_heals.add(m.group(1))

    # Build set of defined MAP_* constants from map_groups.h
    # Handles both enum style (MAP_X = val) and #define style (#define MAP_X val)
    defined_maps = set()
    mg_path = os.path.join(game_path, "include", "constants", "map_groups.h")
    mg_content = _read_file(mg_path)
    if mg_content:
        for m in re.finditer(r'\b(MAP_\w+)\s*=', mg_content):
            defined_maps.add(m.group(1))
        for m in re.finditer(r'#define\s+(MAP_\w+)\s', mg_content):
            defined_maps.add(m.group(1))

    # Phase 1: Scan custom map .inc files for vanilla refs
    maps_dir = os.path.join(game_path, "data", "maps")
    custom_content = ""
    if keep_maps:
        for map_name in keep_maps:
            map_dir = os.path.join(maps_dir, map_name)
            if not os.path.isdir(map_dir):
                continue
            for fname in os.listdir(map_dir):
                if not fname.endswith(".inc") and not fname.endswith(".pory"):
                    continue
                fpath = os.path.join(map_dir, fname)
                fcontent = _read_file(fpath)
                if fcontent is None:
                    continue
                custom_content += fcontent
                if fname.endswith(".inc"):
                    if vanilla_map_pat:
                        for m in vanilla_map_pat.finditer(fcontent):
                            map_refs.add(m.group(1))
                    for m in re.finditer(r'\b(HEAL_LOCATION_\w+)\b', fcontent):
                        hl_name = m.group(1)
                        if hl_name not in defined_heals:
                            heal_refs.add(hl_name)

            # Phase 1b: Scan map.json for connection map refs
            mj_path = os.path.join(map_dir, "map.json")
            mj_content = _read_file(mj_path)
            if mj_content:
                for m in re.finditer(r'"map"\s*:\s*"(MAP_\w+)"', mj_content):
                    ref_name = m.group(1)
                    if ref_name not in defined_maps:
                        # Strip MAP_ prefix for map_refs set
                        map_refs.add(ref_name[4:])

    # Phase 2: Scan shared data/scripts/*.inc files that will survive
    # (either because _patch_event_scripts_s keeps them, or because they
    # don't reference vanilla MAP_* at all).  Collect their vanilla MAP_*
    # refs and undefined TRAINER_* refs for stubbing.
    scripts_dir = os.path.join(game_path, "data", "scripts")
    if os.path.isdir(scripts_dir):
        for fname in os.listdir(scripts_dir):
            if not fname.endswith(".inc"):
                continue
            fpath = os.path.join(scripts_dir, fname)
            fcontent = _read_file(fpath)
            if fcontent is None:
                continue

            # Collect vanilla MAP_* refs from scripts that will survive
            # (scripts with MAP_* refs that have labels used by custom content)
            if vanilla_map_pat and custom_content:
                if vanilla_map_pat.search(fcontent):
                    labels = re.findall(r'^(\w+):{1,2}', fcontent, re.MULTILINE)
                    if any(label in custom_content for label in labels):
                        for m in vanilla_map_pat.finditer(fcontent):
                            map_refs.add(m.group(1))

            # Collect undefined TRAINER_* refs from ALL surviving scripts
            if defined_trainers:
                for m in re.finditer(r'\b(TRAINER_\w+)\b', fcontent):
                    t = m.group(1)
                    if t not in defined_trainers:
                        trainer_refs.add(t)

            # Collect undefined HEAL_LOCATION_* refs
            for m in re.finditer(r'\b(HEAL_LOCATION_\w+)\b', fcontent):
                hl_name = m.group(1)
                if hl_name not in defined_heals:
                    heal_refs.add(hl_name)

    if not map_refs and not heal_refs and not trainer_refs:
        return

    # Add .equiv stubs to assembly source files.
    # event_scripts.s, map_events.s, and maps.s compile separately with
    # different .include sets — all need the stubs.
    for asm_file in ["data/event_scripts.s", "data/map_events.s", "data/maps.s"]:
        _add_equiv_stubs_to_asm(
            game_path, asm_file, map_refs, heal_refs, report,
            trainer_refs=trainer_refs,
        )


def _add_equiv_stubs_to_asm(game_path, rel_path, map_refs, heal_refs, report,
                            trainer_refs=None):
    """Add .equiv stubs to an assembly source file for removed constants.

    Auto-generated headers (map_groups.h, heal_locations.h, opponents.h)
    can't be patched directly.  The assembly map macro uses .ifdef which
    checks assembler symbols, not C preprocessor defines.  So we insert
    .equiv directives directly into the .s file, after the #include block.
    Each stub has a .ifndef guard so it's only emitted if the symbol isn't
    already defined by the build system.
    """
    full_path = os.path.join(game_path, rel_path)
    content = _read_file(full_path)
    if content is None:
        return

    stubs = []
    for const in sorted(map_refs):
        name = f"MAP_{const}"
        stubs.append(f".ifndef {name}\n.equiv {name}, 0\n.endif\n")
    for const in sorted(heal_refs):
        stubs.append(f".ifndef {const}\n.equiv {const}, 0\n.endif\n")
    if trainer_refs:
        for const in sorted(trainer_refs):
            stubs.append(f".ifndef {const}\n.equiv {const}, 0\n.endif\n")

    if not stubs:
        return

    stub_block = ("@ Scorched: stub constants for vanilla refs in custom content\n"
                  + "".join(stubs) + "\n")

    # Already patched?
    if "stub constants for vanilla refs" in content:
        return

    # Insert after the last #include line (before script code)
    lines = content.splitlines(keepends=True)
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("#include"):
            insert_idx = i + 1

    lines.insert(insert_idx, "\n" + stub_block)
    total = len(map_refs) + len(heal_refs)
    if _write_file(full_path, "".join(lines)):
        report.add(rel_path,
                    f"Added {total} .equiv stub(s) for vanilla refs in custom content")


# ============================================================
# EVENT_SCRIPTS.S — Comment out .includes for vanilla-only scripts
# ============================================================

def _patch_event_scripts_s(game_path, plan, report):
    """Comment out .include lines in event_scripts.s for vanilla-only .inc files.

    After Phoenix removes vanilla maps, shared scripts like safari_zone.inc
    and battle_pike.inc still reference removed MAP_* constants.  Comment out
    their .include directives — but only if no labels in the .inc file are
    referenced by custom content.

    Note: only MAP_* references trigger comment-out.  TRAINER_* and other
    constant refs in shared scripts are handled via .equiv stubs instead,
    because core engine scripts (trainer_battle.inc) define labels needed
    by the gStdScripts table and other engine infrastructure.
    """
    es_path = os.path.join(game_path, "data", "event_scripts.s")
    content = _read_file(es_path)
    if content is None:
        return

    # Build set of vanilla map constants for reference checking
    vanilla_consts = _build_vanilla_map_const_set(plan)
    if not vanilla_consts:
        return

    # Build a pattern to detect vanilla map refs in .inc files
    vanilla_map_pat = re.compile(
        r'\bMAP_(' + '|'.join(re.escape(c) for c in vanilla_consts) + r')\b'
    )

    # Collect all custom map content for cross-referencing
    keep_maps = getattr(plan, 'keep_maps', set())
    custom_content = ""
    maps_dir = os.path.join(game_path, "data", "maps")
    for map_name in keep_maps:
        map_dir = os.path.join(maps_dir, map_name)
        if not os.path.isdir(map_dir):
            continue
        for fname in os.listdir(map_dir):
            if not fname.endswith(".inc") and not fname.endswith(".pory"):
                continue
            fc = _read_file(os.path.join(map_dir, fname))
            if fc:
                custom_content += fc

    lines = content.splitlines(keepends=True)
    changed = False
    for i, line in enumerate(lines):
        m = re.match(r'(\s*)\.include\s+"(data/scripts/[^"]+\.inc)"', line)
        if not m:
            continue
        inc_rel = m.group(2)
        inc_path = os.path.join(game_path, inc_rel)
        inc_content = _read_file(inc_path)
        if inc_content is None:
            continue
        # Check if the script references any vanilla map constants
        if not vanilla_map_pat.search(inc_content):
            continue
        # Check if any labels from this .inc are referenced by custom content
        labels = re.findall(r'^(\w+):{1,2}', inc_content, re.MULTILINE)
        referenced = any(label in custom_content for label in labels)
        if referenced:
            continue  # Don't comment out — custom content needs this script
        lines[i] = f"{m.group(1)}@ Scorched: {line.strip()}\n"
        changed = True

    if changed:
        if _write_file(es_path, "".join(lines)):
            report.add("data/event_scripts.s",
                        "Commented out .includes for vanilla-only scripts")


# ============================================================
# PORYSCRIPT PRE-COMPILATION — compile .pory to .inc before build
# ============================================================

def _precompile_poryscript(game_path, report):
    """Compile all .pory files to .inc so the assembler can find them.

    The pokeemerald Makefile has no rule to compile .pory -> .inc;
    ``make clean`` deletes all generated .inc files.  After Phoenix
    removes vanilla maps, surviving custom maps with .pory scripts
    must be compiled before ``make`` can assemble event_scripts.s.
    """
    compiler = os.path.join(game_path, "tools", "poryscript", "poryscript")
    if not os.path.isfile(compiler):
        return

    font_cfg = os.path.join(game_path, "font_config.json")
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return

    compiled = []
    for root, _dirs, files in os.walk(maps_dir):
        for fname in files:
            if not fname.endswith(".pory"):
                continue
            pory_path = os.path.join(root, fname)
            inc_path = pory_path[:-5] + ".inc"
            if os.path.isfile(inc_path):
                continue
            cmd = [compiler, "-i", pory_path, "-o", inc_path]
            if os.path.isfile(font_cfg):
                cmd.extend(["-fc", font_cfg])
            try:
                subprocess.run(
                    cmd, cwd=game_path, capture_output=True,
                    text=True, timeout=30,
                )
            except Exception:
                report.errors.append(f"Failed to compile {pory_path}")
                continue
            if os.path.isfile(inc_path):
                rel = os.path.relpath(inc_path, game_path)
                compiled.append(rel)

    if compiled:
        report.add("poryscript",
                    f"Pre-compiled {len(compiled)} .pory file(s)",
                    ", ".join(compiled))


# ============================================================
# CUSTOM MAP SCRIPT INCLUDES — ensure all custom maps are included
# ============================================================

def _ensure_custom_map_scripts(game_path, plan, report):
    """Ensure all custom maps have their scripts.inc included in event_scripts.s.

    After Phoenix removes vanilla .include lines, custom maps that were added
    to map_groups but never had their scripts included (a common Porymap
    workflow oversight) would fail at link time with undefined references.

    Scans BOTH plan.keep_maps AND the data/maps/ directory on disk to catch
    maps added after Phoenix ran.
    """
    es_path = os.path.join(game_path, "data", "event_scripts.s")
    content = _read_file(es_path)
    if content is None:
        return

    keep_maps = set(getattr(plan, 'keep_maps', set()))

    # Also scan data/maps/ on disk — catches maps added after Phoenix
    maps_dir = os.path.join(game_path, "data", "maps")
    if os.path.isdir(maps_dir):
        for entry in os.listdir(maps_dir):
            entry_path = os.path.join(maps_dir, entry)
            if os.path.isdir(entry_path) and entry != ".git":
                keep_maps.add(entry)

    if not keep_maps:
        return

    missing = []
    for map_name in sorted(keep_maps):
        scripts_inc = os.path.join(maps_dir, map_name, "scripts.inc")
        if not os.path.isfile(scripts_inc):
            continue
        include_line = f'data/maps/{map_name}/scripts.inc'
        if include_line in content:
            continue
        missing.append(map_name)

    if not missing:
        return

    # Find the last .include "data/maps/..." line and insert after it
    lines = content.splitlines(keepends=True)
    insert_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if '.include "data/maps/' in lines[i]:
            insert_idx = i + 1
            break

    for map_name in missing:
        lines.insert(insert_idx, f'\t.include "data/maps/{map_name}/scripts.inc"\n')

    if _write_file(es_path, "".join(lines)):
        report.add("data/event_scripts.s",
                    f"Added {len(missing)} missing custom map script include(s): "
                    + ", ".join(missing))


# ============================================================
# MISSING SCRIPT LABEL STUBS — linker stubs for vanilla labels
# ============================================================

def _stub_missing_script_labels(game_path, plan, report):
    """Create stub labels for script/text references that can't be resolved.

    After Phoenix removes vanilla maps, many label references remain:
    - Custom maps referencing vanilla event scripts or text
    - Surviving shared scripts referencing deleted map scripts
    - Inline event_scripts.s code referencing deleted labels
    - C code (extern const u8) referencing script labels

    This creates minimal stub labels at the end of event_scripts.s with
    .ifndef guards.  EventScript stubs use 'return', Text stubs use
    '.string "$"' (empty string with terminator).
    """
    keep_maps = getattr(plan, 'keep_maps', set())

    # Pattern for script/text label references in assembly.
    # gText_* excluded — those are C strings defined in .c files,
    # not assembly labels.  Stubbing them causes "multiple definition."
    label_pat = re.compile(
        r'\b(\w+_EventScript_\w+|EventScript_\w+'
        r'|\w+_Text_\w+'
        r'|Std_\w+|Common_\w+)\b'
    )

    # Collect all label references
    referenced_labels = set()

    # From custom map data
    maps_dir = os.path.join(game_path, "data", "maps")
    if keep_maps:
        for map_name in keep_maps:
            map_dir = os.path.join(maps_dir, map_name)
            if not os.path.isdir(map_dir):
                continue
            for fname in os.listdir(map_dir):
                if not fname.endswith(".inc") and not fname.endswith(".pory"):
                    continue
                fc = _read_file(os.path.join(map_dir, fname))
                if fc:
                    for m in label_pat.finditer(fc):
                        referenced_labels.add(m.group(1))

    # From event_scripts.s inline content and surviving shared scripts
    es_path = os.path.join(game_path, "data", "event_scripts.s")
    es_content = _read_file(es_path)
    surviving_incs = set()
    if es_content:
        # Scan event_scripts.s itself (inline code, not just .includes)
        for m in label_pat.finditer(es_content):
            referenced_labels.add(m.group(1))
        # Find surviving .includes
        for m in re.finditer(
            r'^\s*\.include\s+"(data/scripts/[^"]+\.inc)"', es_content,
            re.MULTILINE
        ):
            surviving_incs.add(m.group(1))

    for inc_rel in surviving_incs:
        inc_path = os.path.join(game_path, inc_rel)
        fc = _read_file(inc_path)
        if fc:
            for m in label_pat.finditer(fc):
                referenced_labels.add(m.group(1))

    # From C/H source files (extern const u8 references, data struct refs)
    # Scan src/ and include/ — both can reference script/text labels
    for scan_dir in ["src", "include"]:
        full_dir = os.path.join(game_path, scan_dir)
        if not os.path.isdir(full_dir):
            continue
        for root, _dirs, files in os.walk(full_dir):
            for fname in files:
                if not fname.endswith(".c") and not fname.endswith(".h"):
                    continue
                fc = _read_file(os.path.join(root, fname))
                if fc:
                    for m in label_pat.finditer(fc):
                        referenced_labels.add(m.group(1))

    # Also scan event_scripts.h for ALL extern const u8 declarations.
    # These reference assembly script/text labels regardless of naming
    # convention (e.g. BattlePyramid_Retire, BattlePyramid_WarpToNextFloor).
    es_h = os.path.join(game_path, "include", "event_scripts.h")
    es_h_content = _read_file(es_h)
    if es_h_content:
        for m in re.finditer(
            r'extern\s+const\s+u8\s+(\w+)\s*\[\]', es_h_content
        ):
            referenced_labels.add(m.group(1))

    if not referenced_labels:
        return

    # Collect all labels defined across surviving .inc files
    defined_labels = set()
    # From event_scripts.s inline definitions
    if es_content:
        for m in re.findall(r'^(\w+):{1,2}', es_content, re.MULTILINE):
            defined_labels.add(m)
    # From custom maps
    if keep_maps:
        for map_name in keep_maps:
            map_dir = os.path.join(maps_dir, map_name)
            if not os.path.isdir(map_dir):
                continue
            for fname in os.listdir(map_dir):
                if not fname.endswith(".inc"):
                    continue
                fc = _read_file(os.path.join(map_dir, fname))
                if fc:
                    for m in re.findall(r'^(\w+):{1,2}', fc, re.MULTILINE):
                        defined_labels.add(m)
    # From surviving shared scripts (including nested .includes)
    for inc_rel in surviving_incs:
        inc_path = os.path.join(game_path, inc_rel)
        fc = _read_file(inc_path)
        if fc:
            for m in re.findall(r'^(\w+):{1,2}', fc, re.MULTILINE):
                defined_labels.add(m)
            # Also check nested .includes
            for nested in re.finditer(r'\.include\s+"([^"]+)"', fc):
                nested_path = os.path.join(game_path, nested.group(1))
                nfc = _read_file(nested_path)
                if nfc:
                    for m in re.findall(r'^(\w+):{1,2}', nfc, re.MULTILINE):
                        defined_labels.add(m)

    # Find undefined labels
    missing = referenced_labels - defined_labels
    if not missing:
        return

    # Build stubs — placed at end of file so .ifndef guards work
    # (all surviving .inc files are processed first)
    stubs = []
    for label in sorted(missing):
        if "_Text_" in label:
            stubs.append(
                f".ifndef {label}\n"
                f"\t.global {label}\n{label}:\n"
                f"\t.string \"$\"\n"
                f".endif\n"
            )
        else:
            stubs.append(
                f".ifndef {label}\n"
                f"\t.global {label}\n{label}:\n"
                f"\treturn\n"
                f".endif\n"
            )

    stub_block = (
        "\n@ Scorched: stub labels for vanilla scripts referenced by custom content\n"
        + "\n".join(stubs) + "\n"
    )

    # Append to event_scripts.s
    es_path = os.path.join(game_path, "data", "event_scripts.s")
    content = _read_file(es_path)
    if content is None:
        return

    if "stub labels for vanilla scripts" in content:
        return  # Already patched

    if _write_file(es_path, content + stub_block):
        report.add("data/event_scripts.s",
                    f"Added {len(missing)} stub label(s) for vanilla scripts "
                    "referenced by custom content")


# ============================================================
# C TEXT STUB GENERATOR — empty strings for removed gText_*
# ============================================================

def _stub_missing_c_text_labels(game_path, plan, report):
    """Create a C stub file for gText_* labels removed by Phoenix.

    gText_* are C strings (defined in .c files like strings.c), not assembly
    labels.  They can't be stubbed in event_scripts.s — that causes "multiple
    definition" linker errors.  Instead we generate a small .c file with empty
    string definitions for any gText_* still referenced by surviving code.
    """
    # Collect all gText_* declarations from strings.h
    strings_h = os.path.join(game_path, "include", "strings.h")
    sh_content = _read_file(strings_h)
    if not sh_content:
        return

    declared = set()
    for m in re.finditer(
        r'extern\s+const\s+u8\s+(gText_\w+)\s*\[\]', sh_content
    ):
        declared.add(m.group(1))

    if not declared:
        return

    # Find which gText_* are still defined in surviving source files.
    # Use a simple word-boundary search for the label name followed by
    # an array bracket, which catches any definition format (ALIGNED,
    # static, etc.).  Also check assembly files for label definitions.
    defined = set()
    gtext_word_pat = re.compile(r'\b(gText_\w+)\b')
    # Match definitions but NOT extern declarations.  We match the line
    # and then reject it if "extern" appears before "const" on that line.
    c_def_raw = re.compile(
        r'\bconst\s+u8\s+(gText_\w+)\s*\[', re.MULTILINE
    )
    asm_def_pat = re.compile(r'^(gText_\w+):{1,2}', re.MULTILINE)
    for scan_dir in ["src", "include"]:
        full_dir = os.path.join(game_path, scan_dir)
        if not os.path.isdir(full_dir):
            continue
        for root, _dirs, files in os.walk(full_dir):
            for fname in files:
                if not fname.endswith((".c", ".h")):
                    continue
                # Skip our own stub file
                if fname == "scorched_text_stubs.c":
                    continue
                fc = _read_file(os.path.join(root, fname))
                if fc:
                    for line in fc.splitlines():
                        # Skip extern declarations — they're not definitions
                        stripped = line.lstrip()
                        if stripped.startswith("extern"):
                            continue
                        for m in c_def_raw.finditer(line):
                            defined.add(m.group(1))
    # Also check assembly files (event_scripts.s and its includes)
    for asm_dir in ["data", "data/scripts", "data/text"]:
        full_dir = os.path.join(game_path, asm_dir)
        if not os.path.isdir(full_dir):
            continue
        for fname in os.listdir(full_dir):
            if not fname.endswith((".s", ".inc")):
                continue
            fc = _read_file(os.path.join(full_dir, fname))
            if fc:
                for m in asm_def_pat.finditer(fc):
                    defined.add(m.group(1))

    # Find which declared gText_* are actually referenced in surviving code
    referenced = set()
    text_pat = re.compile(r'\b(gText_\w+)\b')
    for scan_dir in ["src", "include"]:
        full_dir = os.path.join(game_path, scan_dir)
        if not os.path.isdir(full_dir):
            continue
        for root, _dirs, files in os.walk(full_dir):
            for fname in files:
                if not fname.endswith(".c") and not fname.endswith(".h"):
                    continue
                fc = _read_file(os.path.join(root, fname))
                if fc:
                    for m in text_pat.finditer(fc):
                        referenced.add(m.group(1))

    # Missing = declared + referenced but not defined
    missing = (declared & referenced) - defined
    if not missing:
        return

    # Generate stub C file
    lines = [
        "// Auto-generated by SCORCH Phoenix — stub empty strings for",
        "// vanilla gText_* labels removed during content cleanup.",
        '#include "global.h"',
        "",
    ]
    for label in sorted(missing):
        lines.append(f'const u8 {label}[] = _("");')

    stub_path = os.path.join(game_path, "src", "scorched_text_stubs.c")
    if _write_file(stub_path, "\n".join(lines) + "\n"):
        report.add("src/scorched_text_stubs.c",
                    f"Created C stub file with {len(missing)} empty gText_* "
                    "string(s) for removed vanilla content")


# ============================================================
# LOCALID STUB GENERATOR — stubs for auto-generated map event IDs
# ============================================================

def _stub_missing_localids(game_path, plan, report):
    """Generate stubs for LOCALID_* constants lost when map dirs are deleted.

    map_event_ids.h is auto-generated from data/maps/*/map.json.  When Phoenix
    deletes vanilla map directories, a clean rebuild regenerates this header
    WITHOUT vanilla LOCALID_* constants.  Engine C files still reference them.

    Writes scorched_localid_stubs.h with #ifndef guards for every referenced
    LOCALID that will vanish, and includes it from event_objects.h.
    """
    # Step 1: Build complete LOCALID inventory from all available sources.
    #
    # Source A: map_event_ids.h (only exists on built projects, gitignored
    # on fresh clones).
    # Source B: plan.vanilla_localids (extracted from map JSONs by the
    # scanner before the writer deletes map directories).
    all_localids = {}

    mei_path = os.path.join(game_path, "include", "constants", "map_event_ids.h")
    mei_content = _read_file(mei_path) or ""
    for m in re.finditer(r'^#define\s+(LOCALID_\w+)\s+(\d+)', mei_content, re.MULTILINE):
        all_localids[m.group(1)] = int(m.group(2))

    # Merge LOCALIDs from vanilla map JSONs (scanner extracts these
    # before the writer deletes maps — essential on fresh clones where
    # map_event_ids.h doesn't exist yet).
    vanilla_localids = getattr(plan, 'vanilla_localids', {})
    for name, val in vanilla_localids.items():
        if name not in all_localids:
            all_localids[name] = val

    if not all_localids:
        return

    # Step 2: Determine which LOCALIDs will survive regeneration.
    # LOCALIDs are generated per-map — a LOCALID from a kept map survives.
    keep_maps = getattr(plan, 'keep_maps', set())
    surviving_localids = set()

    # From header: parse "// MAP_<MapName>" section comments
    if mei_content:
        current_map = None
        for line in mei_content.splitlines():
            section_m = re.match(r'^// (\w+)', line)
            if section_m:
                current_map = section_m.group(1)
                continue
            def_m = re.match(r'^#define\s+(LOCALID_\w+)', line)
            if def_m and current_map:
                if current_map in keep_maps:
                    surviving_localids.add(def_m.group(1))

    # Vanilla LOCALIDs from the scanner are ALL from nuke_maps, so
    # none of them survive.  (If we had keep-map LOCALIDs they'd
    # already be in surviving_localids from the header parse above.)

    # Engine constants that are always available (not map-specific)
    engine_localids = {"LOCALID_PLAYER", "LOCALID_NONE", "LOCALID_CAMERA",
                       "LOCALID_FOLLOWING_POKEMON"}
    surviving_localids.update(engine_localids)

    # Step 3: Scan C files AND assembly scripts for LOCALID_* references
    referenced = set()
    localid_pat = re.compile(r'\b(LOCALID_\w+)\b')
    src_dir = os.path.join(game_path, "src")
    if os.path.isdir(src_dir):
        for root, _dirs, files in os.walk(src_dir):
            for fname in files:
                if not fname.endswith(".c"):
                    continue
                fc = _read_file(os.path.join(root, fname))
                if fc:
                    for m in localid_pat.finditer(fc):
                        referenced.add(m.group(1))

    # Also scan assembly scripts (.inc and .s files in data/)
    data_dir = os.path.join(game_path, "data")
    if os.path.isdir(data_dir):
        for root, _dirs, files in os.walk(data_dir):
            for fname in files:
                if not (fname.endswith(".inc") or fname.endswith(".s")):
                    continue
                fc = _read_file(os.path.join(root, fname))
                if fc:
                    for m in localid_pat.finditer(fc):
                        referenced.add(m.group(1))

    # Step 3b: LOCALIDs defined via .set/.equ in surviving assembly scripts
    # (data/scripts/*.inc) must NOT get C #define stubs — the preprocessor
    # would expand the #define BEFORE the assembler sees .set, turning
    # ".set LOCALID_FOO, 1" into ".set 1, 1" and causing "expected symbol name".
    set_pat = re.compile(r'\.(?:equ|set)\s+(LOCALID_\w+)\s*,')
    scripts_dir = os.path.join(game_path, "data", "scripts")
    if os.path.isdir(scripts_dir):
        for fname in os.listdir(scripts_dir):
            if not fname.endswith(".inc"):
                continue
            fc = _read_file(os.path.join(scripts_dir, fname))
            if fc:
                for m in set_pat.finditer(fc):
                    surviving_localids.add(m.group(1))

    # Step 4: Find LOCALIDs that are referenced but won't survive
    missing = (referenced & set(all_localids.keys())) - surviving_localids
    if not missing:
        return

    # Step 5: Generate stub header
    lines = [
        "#ifndef GUARD_SCORCHED_LOCALID_STUBS_H",
        "#define GUARD_SCORCHED_LOCALID_STUBS_H",
        "",
        "// Auto-generated by SCORCH Phoenix -- stub LOCALID_* constants for",
        "// vanilla map event IDs removed during content cleanup.",
        "// These are referenced by engine C files but the vanilla map.json",
        "// files that generate them were deleted.",
        "",
    ]
    for name in sorted(missing):
        val = all_localids.get(name, 1)
        lines.append(f"#ifndef {name}")
        lines.append(f"#define {name} {val}")
        lines.append(f"#endif")
        lines.append("")

    lines.append("#endif // GUARD_SCORCHED_LOCALID_STUBS_H")
    lines.append("")

    stub_path = os.path.join(game_path, "include", "constants",
                             "scorched_localid_stubs.h")
    if not _write_file(stub_path, "\n".join(lines)):
        report.errors.append("Failed to write scorched_localid_stubs.h")
        return

    report.add("include/constants/scorched_localid_stubs.h",
               f"Created LOCALID stub header with {len(missing)} stub(s)")

    # Step 6: Include from event_objects.h (which already includes map_event_ids.h)
    eo_path = os.path.join(game_path, "include", "constants", "event_objects.h")
    eo_content = _read_file(eo_path)
    if eo_content is None:
        return

    include_line = '#include "constants/scorched_localid_stubs.h"'
    if include_line in eo_content:
        return  # already included

    # Insert after the map_event_ids.h include
    anchor = '#include "constants/map_event_ids.h"'
    if anchor in eo_content:
        eo_content = eo_content.replace(
            anchor,
            anchor + "\n" + include_line
        )
    else:
        # Fallback: insert after last #include
        eo_lines = eo_content.splitlines(keepends=True)
        insert_idx = 0
        for i, line in enumerate(eo_lines):
            if line.strip().startswith("#include"):
                insert_idx = i + 1
        eo_lines.insert(insert_idx, include_line + "\n")
        eo_content = "".join(eo_lines)

    if _write_file(eo_path, eo_content):
        report.add("include/constants/event_objects.h",
                   "Added #include for scorched_localid_stubs.h")


# ============================================================
# ENGINE FUNCTION REPAIR — un-scorch incorrectly cascaded functions
# ============================================================

# Functions that must never be scorched — they're engine infrastructure
# referenced from function pointer tables (gMovementTypeFuncs, etc.).
# The generic patcher's cascade logic can incorrectly scorch these when
# nearby code has vanilla MAP_* references.
_PROTECTED_FUNCTIONS = {
    "src/field_player_avatar.c": [
        ("MovementType_Player", "void", "(struct Sprite *sprite)"),
    ],
}


def _repair_scorched_engine_functions(game_path, report):
    """Un-scorch critical engine functions incorrectly caught by cascade."""
    for rel_path, funcs in _PROTECTED_FUNCTIONS.items():
        path = os.path.join(game_path, rel_path)
        content = _read_file(path)
        if content is None:
            continue

        patched = False
        for func_name, ret_type, params in funcs:
            scorched_sig = f"// Scorched: {ret_type} {func_name}{params}"
            if scorched_sig not in content:
                continue

            # Find and un-scorch the function signature + body
            lines = content.split("\n")
            new_lines = []
            i = 0
            while i < len(lines):
                stripped = lines[i].strip()
                if stripped == scorched_sig:
                    # Un-scorch signature
                    new_lines.append(f"{ret_type} {func_name}{params}")
                    i += 1
                    # Un-scorch body lines until closing brace
                    while i < len(lines):
                        body = lines[i]
                        body_stripped = body.strip()
                        if body_stripped.startswith("// Scorched: "):
                            restored = body_stripped[len("// Scorched: "):]
                            # Preserve original indentation
                            indent = body[:len(body) - len(body.lstrip())]
                            new_lines.append(indent + restored)
                        else:
                            new_lines.append(body)
                        if restored.rstrip() == "}" if body_stripped.startswith("// Scorched: ") else body_stripped == "}":
                            i += 1
                            break
                        i += 1
                    patched = True
                else:
                    new_lines.append(lines[i])
                    i += 1

            if patched:
                content = "\n".join(new_lines)

        if patched and _write_file(path, content):
            report.add(rel_path,
                       "Repaired incorrectly scorched engine function(s)")


# ============================================================
# MAP_NAME_POPUP.C — Preserve popup background rendering
# ============================================================

def _patch_map_name_popup(game_path, plan, report):
    """Patch map_name_popup.c for phoenix compatibility.

    Handles:
    - sMapSectionToThemeId array (Gen3 popup): drop vanilla entries,
      strip KANTO_MAPSEC_COUNT from size
    - sRegionMapSectionId_To_PopUpThemeIdMapping_BW array (Gen5 popup):
      same treatment
    - LAYOUT_BATTLE_FRONTIER_BATTLE_PYRAMID_TOP reference: comment out
    - KANTO_MAPSEC_START / KANTO_MAPSEC_END remapping block: remove
    - Entries using '- KANTO_MAPSEC_COUNT' as array subscript offset:
      drop (these are all vanilla mapsecs that live past the Kanto gap)
    """
    rel_path = os.path.join("src", "map_name_popup.c")
    full_path = os.path.join(game_path, rel_path)
    content = _read_file(full_path)
    if content is None:
        return

    vanilla_mapsecs = getattr(plan, 'vanilla_mapsecs', set())

    # Names of popup theme arrays that contain [MAPSEC_*] entries
    _POPUP_ARRAYS = ("sMapSectionToThemeId", "sRegionMapSectionId_To_PopUpThemeIdMapping_BW")

    lines = content.splitlines(keepends=True)
    new_lines = []
    i = 0
    patched = False
    while i < len(lines):
        line = lines[i]

        # --- Popup theme array declarations (only if mapsecs detected) ---
        if vanilla_mapsecs and any(name in line for name in _POPUP_ARRAYS) and "static" in line:
            # Strip KANTO_MAPSEC_COUNT from size expression
            line = line.replace(" - KANTO_MAPSEC_COUNT", "")
            new_lines.append(line)
            i += 1
            # Walk array body: keep custom entries, drop vanilla
            while i < len(lines):
                entry = lines[i]
                stripped = entry.strip()
                if stripped == "};":
                    new_lines.append(entry)
                    i += 1
                    break
                # Drop any entry using '- KANTO_MAPSEC_COUNT' in subscript
                # These are always vanilla mapsecs past the Kanto gap
                if "KANTO_MAPSEC_COUNT" in entry:
                    i += 1
                    continue
                # Check if this is a [MAPSEC_*] = entry
                m = re.match(r"\s*\[(MAPSEC_\w+)\]", stripped)
                if m:
                    mapsec_name = m.group(1)
                    if mapsec_name in vanilla_mapsecs:
                        i += 1  # drop vanilla entry
                        continue
                # Keep non-vanilla entries, braces, comments, etc.
                new_lines.append(entry)
                i += 1
            patched = True
            continue

        # --- LAYOUT_BATTLE_FRONTIER_BATTLE_PYRAMID_TOP reference ---
        # This layout constant is removed when Battle Frontier maps are nuked.
        # Always patch regardless of mapsec detection.
        if "LAYOUT_BATTLE_FRONTIER_BATTLE_PYRAMID_TOP" in line:
            # Comment out the entire if-block that checks for pyramid top
            # Replace with 'if (0)' to keep the else branch valid
            new_lines.append(line.replace(
                "gMapHeader.mapLayoutId == LAYOUT_BATTLE_FRONTIER_BATTLE_PYRAMID_TOP",
                "0 /* SCORCHED: LAYOUT_BATTLE_FRONTIER_BATTLE_PYRAMID_TOP removed */"))
            i += 1
            patched = True
            continue

        # --- KANTO_MAPSEC_START / KANTO_MAPSEC_END remapping block ---
        # This block remaps regionMapSectionId for Kanto mapsecs.
        # With Kanto removed, the entire block is dead code.
        # Always patch regardless of mapsec detection.
        if "KANTO_MAPSEC_START" in line or "KANTO_MAPSEC_END" in line:
            # Comment out lines referencing these constants
            new_lines.append("    // SCORCHED: Kanto mapsec remapping removed\n")
            # Skip the entire if-block (up to and including closing brace)
            brace_depth = 0
            found_open = False
            while i < len(lines):
                cur = lines[i].strip()
                if "{" in cur:
                    brace_depth += cur.count("{")
                    found_open = True
                if "}" in cur:
                    brace_depth -= cur.count("}")
                if found_open and brace_depth <= 0:
                    i += 1
                    break
                i += 1
            patched = True
            continue

        new_lines.append(line)
        i += 1

    if patched and _write_file(full_path, "".join(new_lines)):
        report.add(rel_path,
                   "Patched popup theme tables and removed Kanto/frontier references",
                   "Gen3 + Gen5 arrays cleaned, KANTO remap block removed")


# ============================================================
# GENERIC MAP_* REF PATCHER — Catch-all for remaining C files
# ============================================================

# Files fully handled by dedicated patchers (skip in generic pass)
_DEDICATED_PATCH_FILES = {
    "src/roamer.c",
    # Note: secret_base.c is NOT here — dedicated patcher handles the array,
    # then generic patcher handles remaining MAP_SECRET_BASE_* refs
    "src/post_battle_event_funcs.c",
    "src/data/heal_locations.h",
    "src/data/heal_locations.json",
    "include/constants/heal_locations.h",
    "include/gym_leader_rematch.h",
    "src/gym_leader_rematch.c",
    "include/constants/rematches.h",
    "data/event_scripts.s",
    "src/tileset_anims.c",
    "include/tileset_anims.h",
    "include/constants/metatile_labels.h",
    "graphics_file_rules.mk",
    # Auto-generated files that mapjson/make will regenerate
    "include/constants/map_groups.h",
    "include/constants/region_map_sections.h",
    # Inja template (patched by scorch_writer)
    "src/data/region_map/region_map_sections.constants.json.txt",
    # Map name popup (dedicated patcher preserves theme table + rendering)
    "src/map_name_popup.c",
    # Region header (dedicated patcher handles KANTO_MAPSEC_START stubs)
    "include/regions.h",
    # Trainer data files (already handled by scorch_writer)
    "include/constants/opponents.h",
    "src/data/trainers.party",
    "src/data/trainers.h",
}


def _word_boundary_alt(consts):
    """Build a word-boundary alternation regex fragment for a set of constants."""
    return r"\b(?:" + "|".join(re.escape(c) for c in consts) + r")\b"


def _build_generic_const_pattern(plan):
    """Build a compiled regex matching vanilla MAP_*/TRAINER_*/LAYOUT_*/MAPSEC_* refs.

    Returns compiled pattern, or None if no vanilla constants exist.
    """
    vanilla_map_consts = _build_vanilla_map_const_set(plan)
    vanilla_trainer_consts = {const for const, _tid in plan.vanilla_trainers}
    vanilla_layout_consts = getattr(plan, 'vanilla_layout_consts', set())
    vanilla_heal_consts = {name for name, _hid in getattr(plan, 'vanilla_heal_ids', set())}
    vanilla_rematch_consts = getattr(plan, 'vanilla_rematch_consts', set())
    vanilla_mapsec_consts = getattr(plan, 'vanilla_mapsecs', set())

    const_sets = [vanilla_map_consts, vanilla_trainer_consts,
                  vanilla_layout_consts, vanilla_heal_consts,
                  vanilla_rematch_consts, vanilla_mapsec_consts]
    if not any(const_sets):
        return None

    patterns = []
    if vanilla_map_consts:
        alt = "|".join(re.escape(c) for c in vanilla_map_consts)
        patterns.append(r"\bMAP_(?:GROUP|NUM)\s*\(\s*(?:" + alt + r")\s*\)")
        patterns.append(r"\bMAP_(?:" + alt + r")\b")
        # MATCH_MAP(CONST) without MAP_ prefix (v1.11.x follower_helper.c)
        patterns.append(r"\bMATCH_MAP\s*\(\s*(?:" + alt + r")\s*\)")

    for cset in [vanilla_trainer_consts, vanilla_layout_consts,
                 vanilla_heal_consts, vanilla_rematch_consts,
                 vanilla_mapsec_consts]:
        if cset:
            patterns.append(_word_boundary_alt(cset))

    # Kanto range macros are removed when all Kanto MAPSECs are gone
    if vanilla_mapsec_consts:
        kanto_ids = {"MAPSEC_PALLET_TOWN", "MAPSEC_SPECIAL_AREA"}
        if kanto_ids.issubset(vanilla_mapsec_consts):
            patterns.append(r"\bKANTO_MAPSEC_(?:START|END|COUNT)\b")

    return re.compile("|".join(patterns))


def _classify_vanilla_line(line, stripped):
    """Classify a C source line containing a vanilla ref and return replacement.

    Returns (action, replacement_line):
    - ("remove", None)        — line should be deleted
    - ("replace", new_line)   — line should be replaced
    """
    # Case 1: switch case label — remove it
    if re.match(r"case\s+(MAP_NUM\(|TRAINER_|REMATCH_|LAYOUT_|HEAL_LOCATION_|MAPSEC_)", stripped):
        return "remove", None

    # Case 2: array/struct initializer line — remove it
    if stripped.startswith("{") and stripped.endswith("},"):
        return "remove", None
    # Comma-prefixed entries in macro arg lists (e.g. EVOLUTION(,{...}))
    # Replace with a stub entry to preserve comma chain in multi-line macros.
    # Preserve trailing comma if the original had one.
    if (stripped.startswith(",{") or stripped.startswith(", {")):
        indent_match = re.match(r"(\s*)", line)
        indent = indent_match.group(1) if indent_match else ""
        trail = "," if stripped.rstrip().endswith(",") else ""
        return "replace", f"{indent},{{0}}{trail}  // Scorched: vanilla ref removed\n"
    if re.match(r"\[(?:MAP_|TRAINER_|REMATCH_|LAYOUT_|HEAL_LOCATION_|MAPSEC_)", stripped):
        return "remove", None
    if stripped.startswith(".map"):
        return "remove", None

    # Case 3: #define line — stub value with unique counter (keeps symbol
    # defined for dependents like switch cases that reference it)
    if stripped.startswith("#define"):
        define_match = re.match(r"(\s*#define\s+\w+)\s+.+", line)
        if define_match:
            indent_match = re.match(r"(\s*)", line)
            indent = indent_match.group(1) if indent_match else ""
            name = re.match(r"\s*#define\s+(\w+)", line).group(1)
            return "replace", f"{indent}#define {name} __COUNTER__  // Scorched: vanilla ref removed\n"
        return "remove", None

    # Case 4: if/else if condition — replace condition with FALSE
    if_match = re.match(r"(\s*)(else\s+)?if\s*\(", line)
    if if_match:
        indent = if_match.group(1)
        else_prefix = if_match.group(2) or ""
        return "replace", f"{indent}{else_prefix}if (FALSE)  // Scorched: vanilla ref removed\n"

    # Case 5: return statement — stub to 0
    if re.match(r"\s*return\s+", line):
        indent_match = re.match(r"(\s*)", line)
        indent = indent_match.group(1) if indent_match else ""
        return "replace", f"{indent}return 0;  // Scorched: vanilla ref removed\n"

    # Case 6: assignment with gTrainers[TRAINER_*] — comment out
    assign_match = re.match(r"(\s*)(\w.*?=\s*)", line)
    if assign_match and "gTrainers[" in line:
        indent = assign_match.group(1)
        return "replace", f"{indent}// Scorched: {stripped}\n"

    # Case 7: anything else — comment out
    indent_match = re.match(r"(\s*)", line)
    indent = indent_match.group(1) if indent_match else ""
    return "replace", f"{indent}// Scorched: {stripped}\n"


def _extract_declared_var(line):
    """If line is a variable declaration or simple assignment, return the variable name."""
    # Type-prefixed declaration: int foo = ..., const struct Bar *baz = ...
    m = re.match(r"\s*(?:(?:static|extern|volatile)\s+)*(?:const\s+)?(?:struct\s+)?\w+\s+\**(\w+)(?:\s*\[.*?\])?\s*=", line)
    if m:
        return m.group(1)
    # Simple assignment: foo = ...(no brackets, arrows, or dots before =)
    m = re.match(r"\s*([a-zA-Z_]\w*)\s*=[^=]", line)
    if m:
        return m.group(1)
    return None


def _patch_trainer_slides_test(game_path, plan, report):
    """Empty the test trainer slides data file after all trainers are removed.

    test/battle/trainer_slides.h contains initializer data for a trainer
    array.  After scorch removes all trainers, the array bounds are wrong
    and the build fails with 'array index exceeds bounds'.  We empty the
    file so the test data compiles (empty initializer).
    """
    if not plan.vanilla_trainers:
        return  # no trainers removed, nothing to do

    rel_path = os.path.join("test", "battle", "trainer_slides.h")
    full_path = os.path.join(game_path, rel_path)
    if not os.path.isfile(full_path):
        return

    content = _read_file(full_path)
    if not content or content.strip() == "":
        return  # already empty

    stub = (
        "// Emptied by SCORCH Phoenix — all trainers removed.\n"
        "// Original data referenced removed trainer slots.\n"
    )
    if _write_file(full_path, stub):
        report.add(rel_path, "Emptied test trainer slides data",
                   "All trainers removed, test data was out of bounds")


def _patch_generic_map_refs(game_path, plan, report):
    """Generic pass: patch lines with vanilla MAP_*/TRAINER_*/REMATCH_*/LAYOUT_* refs.

    This catches remaining files the dedicated patchers don't handle.
    Runs AFTER dedicated patchers so it can clean up anything they missed.
    """
    const_pattern = _build_generic_const_pattern(plan)
    if const_pattern is None:
        return

    for target in plan.c_patch_targets:
        rel_path = target.get("rel_path", "")
        if rel_path in _DEDICATED_PATCH_FILES:
            continue

        full_path = target.get("path", os.path.join(game_path, rel_path))
        content = _read_file(full_path)
        if content is None:
            continue

        if not const_pattern.search(content):
            continue

        lines = content.splitlines(keepends=True)
        new_lines = []
        patched_count = 0

        # Pass 1: patch vanilla refs + consume continuation lines
        i = 0
        while i < len(lines):
            line = lines[i]
            if not const_pattern.search(line):
                new_lines.append(line)
                i += 1
                continue

            stripped = line.strip()

            # Never scorch #include lines — removing a header declaration
            # cascades to undefined function/type errors elsewhere.
            if stripped.startswith("#include"):
                new_lines.append(line)
                i += 1
                continue

            # Never scorch preprocessor guards (#ifndef/#ifdef/#if defined)
            # — they check symbol existence, not usage.  Removing them
            # orphans the matching #endif and causes compile errors.
            if stripped.startswith(("#ifndef", "#ifdef", "#if ")):
                new_lines.append(line)
                i += 1
                continue

            # Bug 5e: special handling for .evolutions = EVOLUTION(...) macros.
            # Parse individual entries and only remove vanilla ones.
            if re.match(r"\s*\.evolutions\s*=\s*EVOLUTION\s*\(", line):
                evo_result = _handle_evolution_macro(lines, i, const_pattern)
                if evo_result is not None:
                    evo_lines, evo_consumed = evo_result
                    new_lines.extend(evo_lines)
                    patched_count += 1
                    i += evo_consumed + 1
                    continue

            action, replacement = _classify_vanilla_line(line, stripped)
            patched_count += 1

            # If this vanilla line IS a continuation (starts with && or ||),
            # the expression head above is now broken — fix it.
            if stripped.startswith("&&") or stripped.startswith("||"):
                _fix_broken_expression_head(new_lines)

            # Bug 5a: If the PREVIOUS line ends with && or || (expecting this
            # line as continuation), fix the previous line's dangling operator.
            _fix_trailing_operator_on_prev_line(new_lines)

            if action == "replace":
                new_lines.append(replacement)
            # else: action == "remove", line is dropped

            # Consume continuation lines (|| or && on following lines)
            j, consumed = _consume_continuations(lines, i, new_lines)
            patched_count += consumed
            i = j
            continue

        # Pass 1b: fix guard clause inversions (if (FALSE) return; → return;)
        new_lines, guard_count = _fix_guard_clause_inversions(new_lines)
        patched_count += guard_count

        # Pass 2: comment out orphaned variable references
        new_lines, orphan_count = _fix_orphaned_var_refs(new_lines)
        patched_count += orphan_count

        # Pass 3: fix orphaned else/else-if blocks
        new_lines, else_count = _fix_orphaned_else_blocks(new_lines)
        patched_count += else_count

        # Pass 4: fix continue/break outside loop (from scorched for/while headers)
        new_lines, loop_count = _fix_orphaned_loop_stmts(new_lines)
        patched_count += loop_count

        # Pass 5: fix case/default labels outside live switch
        new_lines, switch_count = _fix_orphaned_switch_cases(new_lines)
        patched_count += switch_count

        # Pass 5b: fix unreachable statements inside live switches
        new_lines, unreach_count = _fix_unreachable_switch_stmts(new_lines)
        patched_count += unreach_count

        # Pass 6: fix orphaned block bodies (signature/declaration/loop scorched, body remains)
        new_lines, body_count = _fix_orphaned_block_bodies(new_lines)
        patched_count += body_count

        # Pass 7: fix braceless if/else with scorched body (add no-op statement)
        new_lines, noop_count = _fix_braceless_scorched_bodies(new_lines)
        patched_count += noop_count

        if patched_count:
            # Inject warning suppression pragmas for cascading scorch effects.
            # Only inject into .c files — .h files may be #included inside
            # struct initializers where #pragma is invalid syntax.
            if rel_path.endswith(".c"):
                new_lines = _inject_scorch_pragmas(new_lines)
            result = "".join(new_lines)
            if _write_file(full_path, result):
                report.add(rel_path, "Patched vanilla references",
                            f"Handled {patched_count} lines with vanilla constants")


def _inject_scorch_pragmas(lines):
    """Inject warning suppression pragmas at the top of a generically-patched file.

    Scorching variable assignments and return statements leaves variables
    potentially uninitialized and functions without return values.  Rather
    than tracking which warnings each individual scorch triggers, inject a
    standard set of suppression pragmas after the last #include.
    """
    _SCORCH_PRAGMA_MARKER = "// SCORCH: suppress cascading warnings\n"
    pragmas = (
        _SCORCH_PRAGMA_MARKER
        + "#pragma GCC diagnostic ignored \"-Wmaybe-uninitialized\"\n"
        + "#pragma GCC diagnostic ignored \"-Wuninitialized\"\n"
        + "#pragma GCC diagnostic ignored \"-Wreturn-type\"\n"
        + "#pragma GCC diagnostic ignored \"-Wunused-variable\"\n"
        + "#pragma GCC diagnostic ignored \"-Wunused-but-set-variable\"\n"
        + "#pragma GCC diagnostic ignored \"-Wunused-function\"\n"
    )

    # Already injected?
    for line in lines:
        if _SCORCH_PRAGMA_MARKER in line:
            return lines

    # Find the first #include line — insert just before it so the pragmas
    # cover all code in the file (some files have late #includes after
    # function definitions).
    first_include = -1
    for idx, line in enumerate(lines):
        if line.strip().startswith("#include"):
            first_include = idx
            break

    result = list(lines)
    if first_include >= 0:
        result.insert(first_include, pragmas)
    else:
        result.insert(0, pragmas)
    return result


def _fix_broken_expression_head(new_lines):
    """Fix an expression head whose continuation was just scorched.

    When we're about to comment out a line starting with && or ||, the
    previous non-comment, non-blank line (the expression head) has an
    incomplete expression.  We need to close it properly.

    For 'if (expr' -> add closing ')' so it becomes 'if (expr)'
    For 'return expr' -> add ';' so it becomes 'return expr;'
    """
    # Walk backward to find the expression head (skip continuations and comments)
    # Collect all continuation + head indices to calculate total paren balance
    continuation_indices = []
    head_idx = -1
    for k in range(len(new_lines) - 1, -1, -1):
        head_stripped = new_lines[k].strip()
        if head_stripped == "" or head_stripped.startswith("//"):
            continue

        if head_stripped.startswith("&&") or head_stripped.startswith("||"):
            continuation_indices.append(k)
            continue

        # This is the expression head
        head_idx = k
        break

    if head_idx < 0:
        return

    # Calculate total paren imbalance across head + all live continuations
    total_opens = 0
    for idx in [head_idx] + continuation_indices:
        line_content = new_lines[idx].strip()
        total_opens += line_content.count("(") - line_content.count(")")

    if total_opens <= 0:
        return  # Expression is already balanced

    close_parens = ")" * total_opens

    # Apply fix to the LAST live line (last continuation, or head if no continuations)
    fix_idx = continuation_indices[0] if continuation_indices else head_idx
    fix_stripped = new_lines[fix_idx].strip()
    fix_indent = re.match(r"(\s*)", new_lines[fix_idx])
    indent = fix_indent.group(1) if fix_indent else ""

    head_content = new_lines[head_idx].strip()
    if head_content.startswith("if ") or head_content.startswith("if("):
        new_lines[fix_idx] = f"{indent}{fix_stripped.rstrip()}{close_parens}\n"
    elif head_content.startswith("return "):
        if not fix_stripped.rstrip().endswith(";"):
            new_lines[fix_idx] = f"{indent}{fix_stripped.rstrip()}{close_parens};\n"
    elif re.search(r"[^!=<>]=[^=]", head_content) and not fix_stripped.rstrip().endswith(";"):
        new_lines[fix_idx] = f"{indent}{fix_stripped.rstrip()}{close_parens};\n"


def _handle_evolution_macro(lines, start_idx, const_pattern):
    """Handle .evolutions = EVOLUTION(...) macros with selective entry removal.

    Collects the full multi-line EVOLUTION() macro, splits into individual
    evolution entries ({...}), removes only entries containing vanilla refs,
    and reconstructs the macro with surviving entries.

    Returns (replacement_lines, lines_consumed) or None if not applicable.
    """
    # Collect all lines of the macro (until parens balance)
    macro_text = ""
    consumed = 0
    paren_depth = 0
    for j in range(start_idx, len(lines)):
        macro_text += lines[j]
        paren_depth += lines[j].count("(") - lines[j].count(")")
        if j > start_idx:
            consumed += 1
        if paren_depth <= 0:
            break

    # Extract the indent from the first line
    indent_match = re.match(r"(\s*)", lines[start_idx])
    indent = indent_match.group(1) if indent_match else ""

    # Extract individual evolution entries: each {...} block
    entries = _split_evolution_entries(macro_text)
    if not entries:
        return None  # Fall through to normal classification

    # Classify entries: keep those without vanilla refs
    kept = []
    removed = []
    for entry in entries:
        if const_pattern.search(entry):
            removed.append(entry)
        else:
            kept.append(entry)

    if not removed:
        return None  # No vanilla entries, let normal processing handle it

    if not kept:
        # All entries are vanilla — scorch the whole macro
        result_lines = []
        for j in range(start_idx, start_idx + consumed + 1):
            line = lines[j]
            li = re.match(r"(\s*)", line)
            li_indent = li.group(1) if li else ""
            result_lines.append(f"{li_indent}// Scorched: {line.strip()}\n")
        return result_lines, consumed

    # Reconstruct with surviving entries
    reconstructed = f"{indent}.evolutions = EVOLUTION({', '.join(kept)}),\n"
    return [reconstructed], consumed


def _split_evolution_entries(macro_text):
    """Split EVOLUTION(...) macro text into individual {...} entries.

    Each entry is a top-level {...} block inside the EVOLUTION() call.
    Returns list of entry strings like '{EVO_ITEM, ITEM_X, SPECIES_Y}'.
    """
    # Find the opening of EVOLUTION(
    m = re.search(r"EVOLUTION\s*\(", macro_text)
    if not m:
        return []

    content = macro_text[m.end():]
    entries = []
    depth = 0
    current = ""
    i = 0
    # Track the overall paren depth from EVOLUTION(
    evo_paren_depth = 1

    while i < len(content):
        ch = content[i]

        if ch == "(":
            evo_paren_depth += 1
            current += ch
        elif ch == ")":
            evo_paren_depth -= 1
            if evo_paren_depth <= 0:
                # End of EVOLUTION() — flush any current entry
                if current.strip():
                    entry = current.strip().rstrip(",").strip()
                    if entry:
                        entries.append(entry)
                break
            current += ch
        elif ch == "{":
            depth += 1
            current += ch
        elif ch == "}":
            depth -= 1
            current += ch
            if depth == 0:
                # End of an entry
                entry = current.strip().rstrip(",").strip()
                if entry:
                    entries.append(entry)
                current = ""
        else:
            if depth > 0:
                current += ch
            elif ch == "," and depth == 0:
                # Comma between entries at top level — skip
                pass
            else:
                current += ch

        i += 1

    return entries


def _fix_trailing_operator_on_prev_line(new_lines):
    """Fix a previous line whose trailing && / || expects a now-scorched continuation.

    When a vanilla ref appears on a continuation line (the operand AFTER && or ||
    on the previous line), scorching the continuation leaves the previous line
    with a dangling operator and unclosed expression.

    Example:
        return (exprA &&          <-- previous line, dangling &&
                // Scorched: exprB);  <-- this line just got scorched

    Fix: remove the trailing operator from the previous line and close parens.
    """
    # Find the last non-blank, non-comment line in new_lines
    prev_idx = -1
    for k in range(len(new_lines) - 1, -1, -1):
        s = new_lines[k].strip()
        if s == "" or s.startswith("//"):
            continue
        prev_idx = k
        break

    if prev_idx < 0:
        return

    prev_line = new_lines[prev_idx]
    prev_stripped = prev_line.rstrip()

    # Check if the line ends with && or || (possibly with trailing whitespace)
    trailing_op = re.search(r"(&&|\|\|)\s*$", prev_stripped)
    if not trailing_op:
        return

    # Remove the trailing operator
    trimmed = prev_stripped[:trailing_op.start()].rstrip()

    # Count paren imbalance on the trimmed line
    open_parens = trimmed.count("(") - trimmed.count(")")

    # Close any unclosed parens
    if open_parens > 0:
        trimmed += ")" * open_parens

    # Add semicolon if this is a statement (return, assignment) and doesn't have one
    if not trimmed.rstrip().endswith(";") and not trimmed.rstrip().endswith(")"):
        trimmed += ";"
    elif not trimmed.rstrip().endswith(";"):
        # Check if the expression head is a return or assignment that needs ';'
        head_content = trimmed.lstrip()
        if (head_content.startswith("return ")
                or head_content.startswith("return(")
                or re.search(r"[^!=<>]=[^=]", head_content)):
            trimmed += ";"

    indent_match = re.match(r"(\s*)", prev_line)
    indent = indent_match.group(1) if indent_match else ""
    content = trimmed.lstrip()
    new_lines[prev_idx] = f"{indent}{content}\n"


def _consume_continuations(lines, i, new_lines):
    """Consume continuation lines after a patched line.

    Continuation lines are part of the same expression as the patched line.
    Since the expression head is dead (stubbed/removed), all continuations
    are dead too and get commented out.

    Handles three continuation patterns:
    - Lines starting with || or && (standard continuation)
    - Lines following a consumed line that ends with && or || (chained)
    - Unclosed parens/braces from the patched line (multi-line macro args)

    Returns (next_index, consumed_count).
    """
    # Check if the patched line has unclosed brackets
    patched_line = lines[i].strip()
    # Strip // Scorched: prefix to get the original content
    content = patched_line
    if content.startswith("// Scorched:"):
        content = content[len("// Scorched:"):].strip()
    paren_depth = content.count("(") - content.count(")")
    brace_depth = content.count("{") - content.count("}")

    j = i + 1
    consumed = 0
    chain_continues = False  # previous consumed line ended with && or ||
    while j < len(lines):
        next_line = lines[j]
        next_stripped = next_line.strip()
        is_continuation = (next_stripped.startswith("||")
                           or next_stripped.startswith("&&")
                           or next_stripped.startswith("?"))
        brackets_open = paren_depth > 0 or brace_depth > 0
        if is_continuation or chain_continues or brackets_open:
            indent_match = re.match(r"(\s*)", next_line)
            indent = indent_match.group(1) if indent_match else ""
            new_lines.append(f"{indent}// Scorched: {next_stripped}\n")
            # Update bracket tracking
            paren_depth += next_stripped.count("(") - next_stripped.count(")")
            brace_depth += next_stripped.count("{") - next_stripped.count("}")
            # Check if this consumed line ends with && or || (chained)
            chain_continues = (next_stripped.endswith("&&")
                               or next_stripped.endswith("||"))
            consumed += 1
            j += 1
        else:
            break
    return j, consumed


def _fix_guard_clause_inversions(lines):
    """Pass 1b: fix guard clause inversions.

    When the generic patcher replaces a vanilla condition with if (FALSE),
    it's correct for conditional branches but INVERTED for guard clauses.
    A guard clause is 'if (condition) return;' — replacing condition with
    FALSE disables the guard, making the function run unconditionally.

    This pass detects if (FALSE) lines followed by a bare return statement
    (with no else branch) and converts them to unconditional returns.

    Returns (fixed_lines, count_of_fixes).
    """
    result = list(lines)
    fix_count = 0
    i = 0
    while i < len(result):
        fixed, consumed = _try_fix_guard_clause(result, i)
        if fixed:
            fix_count += 1
            # _try_fix_guard_clause already modified result in-place
        i += 1
    return result, fix_count


def _try_fix_guard_clause(lines, idx):
    """Check if lines[idx] starts a guard clause pattern and fix it in-place.

    Returns (was_fixed, lines_consumed).
    A guard clause is: if (FALSE) [scorched comments...] return [value];
    with NO else branch, and NOT an else-if.
    """
    line = lines[idx]
    stripped = line.strip()

    # Must be an 'if (FALSE)' line (with optional scorched comment)
    if not re.match(r"(else\s+)?if\s*\(\s*FALSE\s*\)", stripped):
        return False, 0
    # Skip 'else if (FALSE)' — part of if/else chains
    if re.match(r"else\s+if", stripped):
        return False, 0

    indent_match = re.match(r"(\s*)", line)
    indent = indent_match.group(1) if indent_match else ""

    # Extract any scorched comment on the if (FALSE) line itself
    scorched_comment = ""
    sc_match = re.search(r"//\s*Scorched:\s*(.*)", stripped)
    if sc_match:
        scorched_comment = sc_match.group(1).strip()

    # Scan forward past scorched comment lines to find the body
    j = idx + 1
    extra_comments = []
    while j < len(lines):
        next_stripped = lines[j].strip()
        if next_stripped == "":
            j += 1
            continue
        if next_stripped.startswith("// Scorched:") or next_stripped.startswith("//Scorched:"):
            extra_comments.append(next_stripped)
            j += 1
            continue
        break

    if j >= len(lines):
        return False, 0

    body_line = lines[j]
    body_stripped = body_line.strip()

    # Check for braced guard: if (FALSE) { return; }
    if body_stripped == "{":
        return _try_fix_braced_guard(lines, idx, j, indent)

    # Check for bare return (same line as body, no brace)
    if not _is_bare_return(body_stripped):
        return False, 0

    # Check there's no else branch after the return
    if _has_else_after(lines, j + 1):
        return False, 0

    # This IS a guard clause — remove it.
    # For value returns (return 0; return FALSE;): delete entirely so the
    # fallback return at the end of the function survives (Bug 5f).
    # For void returns (return;): keep the return to stub the function,
    # since void functions have no fallback return — removing the guard
    # would let the function body execute unconditionally (Bug 11).
    return_value = _extract_return_value(body_stripped)
    lines[idx] = f"{indent}// Scorched: guard clause removed -- vanilla condition\n"

    # Blank out intermediate lines (scorched comments between if and return)
    for k in range(idx + 1, j):
        if lines[k].strip().startswith("// Scorched:") or lines[k].strip() == "":
            lines[k] = ""

    if return_value is None:
        # Void return — keep it to stub the function
        pass
    else:
        # Value return — remove (fallback return at function end survives)
        lines[j] = ""

    return True, j - idx


def _try_fix_braced_guard(lines, if_idx, brace_idx, indent):
    """Handle braced guard: if (FALSE) { return; }

    Only a guard if the braced block contains nothing but return (+ comments).
    """
    j = brace_idx + 1
    found_return = False
    return_value = None

    while j < len(lines):
        s = lines[j].strip()
        if s == "" or s.startswith("// Scorched:") or s.startswith("//Scorched:"):
            j += 1
            continue
        if s == "}":
            # End of block — check if we found exactly one return
            if not found_return:
                return False, 0
            # Check no else after closing brace
            if _has_else_after(lines, j + 1):
                return False, 0
            # Fix: remove guard block.
            # Void returns: keep `return;` to stub the function (Bug 11).
            # Value returns: remove entirely (fallback return survives).
            lines[if_idx] = f"{indent}// Scorched: guard clause removed -- vanilla condition\n"
            for k in range(if_idx + 1, j + 1):
                k_stripped = lines[k].strip()
                if return_value is None and _is_bare_return(k_stripped):
                    # Keep void return — it stubs the function
                    continue
                lines[k] = ""
            return True, j - if_idx
        if _is_bare_return(s) and not found_return:
            found_return = True
            return_value = _extract_return_value(s)
            j += 1
            continue
        # Non-return, non-comment statement — not a guard
        return False, 0

    return False, 0


def _is_bare_return(stripped):
    """Check if a stripped line is a bare return statement."""
    return bool(re.match(r"return\s*(\S.*)?;$", stripped))


def _extract_return_value(stripped):
    """Extract the return value from a return statement, or None for bare return."""
    m = re.match(r"return\s*;$", stripped)
    if m:
        return None
    m = re.match(r"return\s+(.+);$", stripped)
    if m:
        return m.group(1).strip()
    return None


def _has_else_after(lines, start_idx):
    """Check if there's an else/else-if on the next non-blank, non-comment line."""
    j = start_idx
    while j < len(lines):
        s = lines[j].strip()
        if s == "" or s.startswith("//"):
            j += 1
            continue
        return s.startswith("else")
    return False


def _fix_orphaned_var_refs(new_lines):
    """Pass 2: comment out lines that reference variables whose declarations were scorched.

    When a variable declaration is commented out (e.g. because it referenced a
    vanilla layout constant), downstream lines using that variable become orphaned.
    This pass iterates until convergence to handle chained dependencies (variable A
    declared with vanilla ref, variable B declared using A, code using B).

    IMPORTANT: Variable scoping is function-local.  A scorched declaration of
    ``playerX`` inside ``FuncA`` must NOT cascade to a different function
    ``FuncB`` that happens to have a parameter or local also named ``playerX``.
    We track brace depth to detect function boundaries (depth returns to 0).

    Returns (fixed_lines, count_of_orphaned_lines).
    """
    total_orphans = 0
    current_lines = new_lines

    for _iteration in range(10):  # safety cap
        # Build per-function-scope map: scope_id -> set of scorched var names.
        # scope_id is the line index of the function's opening '{'.
        func_vars = _collect_scoped_vars(current_lines)

        all_vars = set()
        for vs in func_vars.values():
            all_vars |= vs
        if not all_vars:
            break

        # Build scope ranges: scope_id -> (start_line, end_line)
        scope_ranges = _build_scope_ranges(current_lines, func_vars)

        var_patterns = {v: re.compile(r"\b" + re.escape(v) + r"\b") for v in all_vars}
        final_lines = []
        orphan_count = 0
        for idx, line in enumerate(current_lines):
            stripped = line.strip()
            if stripped.startswith("//") or stripped == "":
                final_lines.append(line)
                continue
            orphaned = False
            for var_name, pat in var_patterns.items():
                if pat.search(line):
                    # Check that this line is within the scope where var was declared
                    if _var_in_scope(var_name, idx, func_vars, scope_ranges):
                        indent_match = re.match(r"(\s*)", line)
                        indent = indent_match.group(1) if indent_match else ""
                        final_lines.append(f"{indent}// Scorched: {stripped}\n")
                        orphan_count += 1
                        orphaned = True
                        break
            if not orphaned:
                final_lines.append(line)

        total_orphans += orphan_count
        current_lines = final_lines
        if orphan_count == 0:
            break

    return current_lines, total_orphans


def _collect_scoped_vars(lines):
    """Collect scorched variable names grouped by their enclosing function scope.

    Returns {scope_start_line: set_of_var_names}.  scope_start_line is the
    index of the '{' that opens the function body, or -1 for file-scope
    (static/global declarations outside any function).
    """
    func_vars = {}
    depth = 0
    current_scope = -1  # file scope

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track brace depth (rough but sufficient for C)
        # Skip braces inside comments/strings — scorched lines use "// Scorched:"
        if not stripped.startswith("//"):
            opens = stripped.count("{")
            closes = stripped.count("}")
            if depth == 0 and opens > 0:
                current_scope = i
            depth += opens - closes
            if depth <= 0:
                depth = 0
                current_scope = -1

        # Collect scorched var declarations
        if stripped.startswith("// Scorched:"):
            original = stripped[len("// Scorched:"):].strip()
            var_name = _extract_declared_var(original)
            if var_name:
                func_vars.setdefault(current_scope, set()).add(var_name)

    return func_vars


def _build_scope_ranges(lines, func_vars):
    """Build line ranges for each function scope that has scorched vars.

    Returns {scope_start_line: (start, end)} where start/end are line indices.
    For file scope (-1), the range covers the entire file.
    """
    scope_ranges = {}
    if -1 in func_vars:
        scope_ranges[-1] = (0, len(lines) - 1)

    # For function scopes, find the matching closing brace
    scope_starts = {s for s in func_vars if s != -1}
    if not scope_starts:
        return scope_ranges

    depth = 0
    current_scope = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("//"):
            opens = stripped.count("{")
            closes = stripped.count("}")
            if depth == 0 and opens > 0:
                current_scope = i
            depth += opens - closes
            if depth <= 0:
                if current_scope in scope_starts:
                    scope_ranges[current_scope] = (current_scope, i)
                depth = 0
                current_scope = -1

    return scope_ranges


def _var_in_scope(var_name, line_idx, func_vars, scope_ranges):
    """Check if var_name is in scope at line_idx."""
    for scope_id, var_set in func_vars.items():
        if var_name not in var_set:
            continue
        if scope_id not in scope_ranges:
            continue
        start, end = scope_ranges[scope_id]
        if start <= line_idx <= end:
            return True
    return False


def _fix_orphaned_else_blocks(lines):
    """Pass 3: comment out else/else-if when the preceding if was scorched.

    When the generic patcher or orphan pass comments out an 'if (...)' line,
    the matching 'else if' and 'else' blocks become syntactically invalid.
    This scans for else/else-if lines and checks if their controlling if
    was scorched by looking backward through braces and comments.

    Returns (fixed_lines, count_of_orphaned_lines).
    """
    result = list(lines)  # mutable copy
    orphan_count = 0

    for idx, line in enumerate(result):
        stripped = line.strip()
        if not (stripped.startswith("else if") or stripped == "else"
                or stripped.startswith("else {")):
            continue
        # Already commented?
        if stripped.startswith("//"):
            continue

        # Look backward: skip }, whitespace, and // comments to find the
        # preceding statement.  If it's a "// Scorched: if" or
        # "// Scorched: else if", this else is orphaned.
        if _is_else_orphaned(result, idx):
            indent_match = re.match(r"(\s*)", line)
            indent = indent_match.group(1) if indent_match else ""
            result[idx] = f"{indent}// Scorched: {stripped}\n"
            orphan_count += 1

    return result, orphan_count


def _is_else_orphaned(lines, else_idx):
    """Check if the else at else_idx has a scorched controlling if.

    Walks backward from else_idx, skipping closing braces (with brace
    matching), blank lines, and comments, to find the controlling if.
    Returns True if that if was scorched.
    """
    i = else_idx - 1
    brace_depth = 0

    while i >= 0:
        stripped = lines[i].strip()

        # Skip blank lines
        if stripped == "":
            i -= 1
            continue

        # Brace tracking: skip matched { } blocks
        if stripped == "}" or stripped.endswith("}"):
            brace_depth += 1
            i -= 1
            continue
        if stripped == "{" or stripped.endswith("{"):
            if brace_depth > 0:
                brace_depth -= 1
                i -= 1
                continue
            # Unmatched opening brace — stop
            break

        if brace_depth > 0:
            i -= 1
            continue

        # At brace_depth 0: this is the statement before the else
        if stripped.startswith("// Scorched:"):
            original = stripped[len("// Scorched:"):].strip()
            if (original.startswith("if ") or original.startswith("if(")
                    or original.startswith("else if")
                    or original.startswith("else")):
                return True
        break

    return False


def _count_line_braces(stripped):
    """Count opening and closing braces on a line, ignoring strings and comments.

    Returns (open_count, close_count).  Inline constructs like ``{}``
    or ``for (...) {}`` correctly return (1, 1).  Braces inside string
    literals or after ``//`` comments are not counted.
    """
    opens = 0
    closes = 0
    in_string = False
    string_char = None
    i = 0
    while i < len(stripped):
        ch = stripped[i]
        if in_string:
            if ch == '\\':
                i += 2  # skip escaped character
                continue
            if ch == string_char:
                in_string = False
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            i += 1
            continue
        if ch == '/' and i + 1 < len(stripped) and stripped[i + 1] == '/':
            break  # rest is comment
        if ch == '{':
            opens += 1
        elif ch == '}':
            closes += 1
        i += 1
    return opens, closes


def _is_loop_header(stripped):
    """Check if a stripped line is a live loop header (for/while/do)."""
    return (stripped.startswith("for ") or stripped.startswith("for(")
            or stripped.startswith("while ") or stripped.startswith("while(")
            or stripped.startswith("do ") or stripped.startswith("do{")
            or stripped == "do")


def _update_brace_type_stack(brace_type, opens, closes, pending_loop, pending_switch):
    """Update the brace type stack for Pass 4's loop/switch depth tracking.

    Returns (live_loop_delta, live_switch_delta, pending_loop, pending_switch).
    """
    loop_delta = 0
    switch_delta = 0

    for _ in range(opens):
        if pending_loop:
            loop_delta += 1
            brace_type.append("loop")
            pending_loop = False
            pending_switch = False
        elif pending_switch:
            switch_delta += 1
            brace_type.append("switch")
            pending_switch = False
            pending_loop = False
        else:
            brace_type.append(None)

    for _ in range(closes):
        if brace_type:
            kind = brace_type.pop()
            if kind == "loop":
                loop_delta -= 1
            elif kind == "switch":
                switch_delta -= 1
        pending_loop = False
        pending_switch = False

    return loop_delta, switch_delta, pending_loop, pending_switch


def _fix_orphaned_loop_stmts(lines):
    """Pass 4: comment out continue/break statements outside any loop/switch.

    When a for/while loop header is scorched, continue and break statements
    inside the (now un-looped) block become syntax errors.  Uses a simple
    per-line scan: track live loop depth via for/while/do braces.

    Also tracks live switch depth so that break statements inside live
    switch cases are preserved (break is valid in both loops and switches).
    Only continue is loop-exclusive; break is valid in either context.

    Returns (fixed_lines, count_of_orphaned_statements).
    """
    result = list(lines)
    orphan_count = 0

    live_loop_depth = 0
    live_switch_depth = 0
    brace_type = []
    pending_loop = False
    pending_switch = False

    for idx, line in enumerate(result):
        stripped = line.strip()

        if stripped.startswith("//") or stripped == "":
            continue

        opens, closes = _count_line_braces(stripped)

        if _is_loop_header(stripped):
            pending_loop = True
            pending_switch = False
        elif _is_switch_header_line(stripped):
            pending_switch = True
            pending_loop = False

        ld, sd, pending_loop, pending_switch = _update_brace_type_stack(
            brace_type, opens, closes, pending_loop, pending_switch)
        live_loop_depth += ld
        live_switch_depth += sd

        # Clear pending if line has no braces and isn't a header
        if opens == 0 and closes == 0:
            if not _is_loop_header(stripped) and not _is_switch_header_line(stripped):
                pending_loop = False
                pending_switch = False

        # Check for orphaned continue/break
        if stripped.startswith("continue;") and live_loop_depth == 0:
            indent_match = re.match(r"(\s*)", line)
            indent = indent_match.group(1) if indent_match else ""
            result[idx] = f"{indent}// Scorched: {stripped}\n"
            orphan_count += 1
        elif (stripped.startswith("break;")
                and live_loop_depth == 0 and live_switch_depth == 0):
            indent_match = re.match(r"(\s*)", line)
            indent = indent_match.group(1) if indent_match else ""
            result[idx] = f"{indent}// Scorched: {stripped}\n"
            orphan_count += 1

    return result, orphan_count


def _fix_orphaned_switch_cases(lines):
    """Pass 5: comment out case/default labels outside any live switch.

    When a switch(expr) is scorched, case and default labels inside the
    (now switchless) block become syntax errors.  Uses live switch depth
    tracking analogous to _fix_orphaned_loop_stmts.

    Returns (fixed_lines, count_of_orphaned_labels).
    """
    result = list(lines)
    orphan_count = 0

    live_switch_depth = 0
    brace_is_switch = []
    pending_switch = False

    for idx, line in enumerate(result):
        stripped = line.strip()

        if stripped.startswith("//") or stripped == "":
            continue

        opens, closes = _count_line_braces(stripped)

        # Detect live switch headers
        if stripped.startswith("switch ") or stripped.startswith("switch("):
            pending_switch = True

        # Process opening braces
        for _ in range(opens):
            if pending_switch:
                live_switch_depth += 1
                brace_is_switch.append(True)
                pending_switch = False
            else:
                brace_is_switch.append(False)

        # Process closing braces
        for _ in range(closes):
            if brace_is_switch:
                was_switch = brace_is_switch.pop()
                if was_switch:
                    live_switch_depth -= 1
            pending_switch = False

        # Clear pending if line has no braces and isn't a switch header
        if opens == 0 and closes == 0:
            if not (stripped.startswith("switch ") or stripped.startswith("switch(")):
                pending_switch = False

        # Check for case/default outside any live switch
        if (live_switch_depth == 0
                and (re.match(r"case\s+", stripped) or stripped.startswith("default:"))):
            indent_match = re.match(r"(\s*)", line)
            indent = indent_match.group(1) if indent_match else ""
            result[idx] = f"{indent}// Scorched: {stripped}\n"
            orphan_count += 1

    return result, orphan_count


def _fix_unreachable_switch_stmts(lines):
    """Pass 5b: scorch unreachable statements inside live switch blocks.

    When the patcher removes individual case labels (e.g. `case MAPSEC_X:`)
    from a live switch, the body statements following that label become
    unreachable code.  This pass detects two patterns:

    1. Statements before the first case/default label in a switch body
       (no label above them — unreachable at switch top).
    2. Statements after a break/return and before the next case/default
       label (dead code between cases).

    Only operates at the CURRENT switch depth — nested switches are
    tracked but their internals are not modified by the outer scan.

    Returns (fixed_lines, count_of_scorched_statements).
    """
    result = list(lines)
    scorch_count = 0

    # State object passed through helpers
    state = {
        "depth": 0,              # live switch nesting depth
        "brace_is_switch": [],   # stack: True if brace belongs to a switch
        "pending": False,        # next '{' belongs to a switch
        "reachable": [],         # stack: is current position reachable?
        "inner_depth": [],       # stack: nested non-switch brace depth
    }

    for idx, line in enumerate(result):
        stripped = line.strip()
        if stripped.startswith("//") or stripped == "":
            continue

        opens, closes = _count_line_braces(stripped)

        if _is_switch_header_line(stripped):
            state["pending"] = True

        # Process opening braces
        for _ in range(opens):
            _handle_open_brace(state)

        # Process closing braces
        for _ in range(closes):
            _handle_close_brace(state)

        # Clear pending if line has no braces and isn't a switch header
        if opens == 0 and closes == 0 and not _is_switch_header_line(stripped):
            if state["depth"] > 0 and state["inner_depth"] and state["inner_depth"][-1] == 0:
                scorch_count += _process_switch_stmt(result, idx, line, stripped, state)
            else:
                state["pending"] = False
        elif state["depth"] > 0 and state["inner_depth"] and state["inner_depth"][-1] == 0:
            # Lines with braces that also contain statements at switch depth
            # (e.g. "} else {" doesn't need processing, but statement-only
            # parts within brace lines are rare — skip processing for safety)
            pass

    return result, scorch_count


def _is_switch_header_line(stripped):
    """Check if a stripped line is a live switch header."""
    return stripped.startswith("switch ") or stripped.startswith("switch(")


def _push_switch_scope(state):
    """Push a new switch scope onto the tracking stacks."""
    state["depth"] += 1
    state["brace_is_switch"].append(True)
    state["pending"] = False
    state["reachable"].append(False)  # no label yet
    state["inner_depth"].append(0)


def _handle_open_brace(state):
    """Handle an opening brace — either starts a switch body or a nested block."""
    if state["pending"]:
        _push_switch_scope(state)
    else:
        state["brace_is_switch"].append(False)
        if state["depth"] > 0 and state["inner_depth"]:
            state["inner_depth"][-1] += 1


def _handle_close_brace(state):
    """Handle a closing brace — pop switch scope or decrement inner depth."""
    if state["depth"] > 0 and state["inner_depth"] and state["inner_depth"][-1] > 0:
        state["inner_depth"][-1] -= 1
    if state["brace_is_switch"]:
        was_switch = state["brace_is_switch"].pop()
        if was_switch:
            state["depth"] -= 1
            if state["reachable"]:
                state["reachable"].pop()
            if state["inner_depth"]:
                state["inner_depth"].pop()
    state["pending"] = False


def _is_conditional_stmt(lines, idx):
    """Check if the statement at idx is inside a braceless if/else body.

    A braceless if/else is a single-statement body without braces:
        if (cond)
            return X;    <-- this return is conditional

    Returns True if the previous non-blank, non-comment line is a braceless
    if/else-if/else (no opening brace on that line).
    """
    k = idx - 1
    while k >= 0:
        prev = lines[k].strip()
        if prev == "" or prev.startswith("//"):
            k -= 1
            continue
        # Braceless if/else-if: "if (...)" or "else if (...)" with no '{'
        if re.match(r"(else\s+)?if\s*\(.*\)\s*(//.*)?\s*$", prev) and "{" not in prev:
            return True
        # Braceless else: just "else" with no '{'
        if prev == "else":
            return True
        return False
    return False


def _is_complete_statement(stripped):
    """Check if a return/break statement is complete on a single line.

    Returns True when the statement ends with ';' and has balanced
    parentheses.  Multi-line returns (unclosed parens or trailing
    operators like && || , + - * / ? : \\) are incomplete — their
    continuation lines are part of the same statement, not separate
    unreachable code.

    break; always returns True.  return; and return VALUE; return True.
    return (expr && returns False (unclosed paren + trailing operator).
    """
    if not stripped.endswith(";"):
        return False
    # Even with trailing ';', check paren balance — a line like
    # "return (foo(bar);" would be malformed but let's be safe
    if stripped.count("(") != stripped.count(")"):
        return False
    return True


def _process_switch_stmt(result, idx, line, stripped, state):
    """Process a statement inside a live switch at top depth.

    Returns 1 if the line was scorched, 0 otherwise.
    """
    # case/default label → mark reachable
    if re.match(r"case\s+", stripped) or stripped.startswith("default:") or stripped == "default":
        if state["reachable"]:
            state["reachable"][-1] = True
        return 0

    # In unreachable state: scorch any statement (including orphaned break/return)
    if state["reachable"] and not state["reachable"][-1]:
        indent_match = re.match(r"(\s*)", line)
        indent = indent_match.group(1) if indent_match else ""
        result[idx] = f"{indent}// Scorched: {stripped}\n"
        return 1

    # break/return in reachable state → mark unreachable for subsequent stmts
    # But NOT if the return/break is inside a braceless if/else (conditional)
    # Bug 6: Also NOT if the return spans multiple lines (incomplete statement)
    if stripped.startswith("break;") or stripped.startswith("return"):
        if state["reachable"] and not _is_conditional_stmt(result, idx):
            if _is_complete_statement(stripped):
                state["reachable"][-1] = False
    return 0


def _fix_orphaned_block_bodies(lines):
    """Pass 6: scorch block bodies whose headers were scorched.

    When the generic patcher comments out a header line, the brace-delimited
    body block that follows becomes orphaned code.  This handles three patterns:

    1. Function signatures:  // Scorched: void Func(...)  followed by { ... }
    2. Variable declarations: // Scorched: static const u8 arr[X] =  followed by { ... };
    3. Loop headers:         // Scorched: for (...)  or  while (...)  followed by { ... }

    Returns (fixed_lines, count_of_scorched_body_lines).
    """
    result = list(lines)
    orphan_count = 0

    i = 0
    while i < len(result):
        stripped = result[i].strip()

        if stripped.startswith("// Scorched:"):
            original = stripped[len("// Scorched:"):].strip()
            if _is_orphaned_block_header(original):
                count = _scorch_following_brace_block(result, i)
                if count > 0:
                    orphan_count += count
                    # Skip past the scorched body
                    i = _find_end_of_brace_block(result, i) + 1
                    continue
        i += 1

    return result, orphan_count


def _is_orphaned_block_header(original):
    """Check if a scorched line's original text is a block header.

    Returns True if the original text (after '// Scorched:') matches
    a function signature, variable declaration with initializer, or
    a for/while loop header.
    """
    # Pattern 1: function signature — type name(params)
    if re.match(r"(?:static\s+)?(?:const\s+)?(?:struct\s+)?\w+[\s*]+\w+\s*\(", original):
        return True
    # Pattern 2: variable declaration ending with = (initializer follows)
    if re.match(r"(?:static\s+)?(?:const\s+)?(?:struct\s+)?\w+[\s*]+\w+\s*(\[.*\])?\s*=$",
                original.rstrip()):
        return True
    # Pattern 3: for/while loop header
    if re.match(r"(?:for|while)\s*\(", original):
        return True
    return False


def _scorch_following_brace_block(result, header_idx):
    """Scorch the brace block following a scorched header at header_idx.

    Looks for the next '{' after header_idx, then scorches everything
    through the matching '}'.  Returns count of lines scorched, or 0
    if no brace block follows.
    """
    j = header_idx + 1
    while j < len(result) and result[j].strip() == "":
        j += 1
    if j >= len(result) or result[j].strip() != "{":
        return 0

    count = 0
    # Scorch the opening brace
    indent_match = re.match(r"(\s*)", result[j])
    indent = indent_match.group(1) if indent_match else ""
    result[j] = f"{indent}// Scorched: {result[j].strip()}\n"
    count += 1

    brace_depth = 1
    k = j + 1
    while k < len(result) and brace_depth > 0:
        body_stripped = result[k].strip()
        if not body_stripped.startswith("//"):
            brace_depth += body_stripped.count("{") - body_stripped.count("}")
            body_indent = re.match(r"(\s*)", result[k])
            bi = body_indent.group(1) if body_indent else ""
            result[k] = f"{bi}// Scorched: {body_stripped}\n"
            count += 1
        k += 1
    return count


def _find_end_of_brace_block(result, header_idx):
    """Find the index of the closing '}' for the block after header_idx."""
    j = header_idx + 1
    while j < len(result) and result[j].strip() == "":
        j += 1
    if j >= len(result):
        return header_idx

    brace_depth = 0
    k = j
    while k < len(result):
        stripped = result[k].strip()
        # Count braces in both live and scorched lines
        if stripped.startswith("// Scorched:"):
            inner = stripped[len("// Scorched:"):].strip()
            brace_depth += inner.count("{") - inner.count("}")
        else:
            brace_depth += stripped.count("{") - stripped.count("}")
        if brace_depth <= 0:
            return k
        k += 1
    return k - 1 if k > j else header_idx


def _fix_braceless_scorched_bodies(lines):
    """Pass 7: add no-op statement to scorched bodies in braceless if/else.

    When an if or else body (without braces) is replaced with a // Scorched:
    comment, the comment is not a valid C statement. A comment is never a
    valid statement body, so this always needs a (void)0; no-op regardless
    of what follows.

    This pass detects:
        if (cond)
            // Scorched: ...
    and replaces the comment with:
        if (cond)
            (void)0; // Scorched: ...

    Returns (fixed_lines, count_of_fixes).
    """
    result = list(lines)
    fix_count = 0

    for idx in range(len(result) - 1):
        stripped = result[idx].strip()
        if not stripped.startswith("// Scorched:"):
            continue

        # Extract the original scorched content
        scorched_content = stripped[len("// Scorched:"):].strip()

        # Skip condition continuations — these are part of the if() condition,
        # not the body. Adding (void)0; here would make the continuation the
        # body and disconnect the real body from the if/else chain.
        if scorched_content.startswith("||") or scorched_content.startswith("&&"):
            continue

        # Check if the line BEFORE this scorched line is a braceless if/else-if/else
        k = idx - 1
        while k >= 0 and result[k].strip() == "":
            k -= 1
        if k < 0:
            continue
        prev_stripped = result[k].strip()
        is_braceless_ctrl = (
            re.match(r"(else\s+)?if\s*\(.*\)\s*(//.*)?$", prev_stripped)
            or re.match(r"(for|while)\s*\(.*\)\s*(//.*)?$", prev_stripped)
            or prev_stripped == "else"
        )
        if is_braceless_ctrl:
            indent_match = re.match(r"(\s*)", result[idx])
            indent = indent_match.group(1) if indent_match else ""
            result[idx] = f"{indent}(void)0; // Scorched: {scorched_content}\n"
            fix_count += 1

    return result, fix_count


# ============================================================
# FLAG CLEANUP
# ============================================================

def _patch_flags(game_path, plan, report):
    """Reclaim vanilla event flags that have no surviving references.

    After Phoenix removes all vanilla maps/scripts/trainers, many named flags
    like FLAG_HIDE_LITTLEROOT_TOWN_BRENDAN still have their #define lines in
    flags.h but nothing references them. This converts them back to
    FLAG_UNUSED_0xNNN format, freeing them for the user's custom content.
    """
    try:
        from torch.flag_scanner import parse_flags_h, scan_all_flags_bulk
    except ImportError:
        report.errors.append("flag_scanner not available — skipping flag cleanup")
        return

    flags_h_path = os.path.join(game_path, "include", "constants", "flags.h")
    if not os.path.isfile(flags_h_path):
        return

    parsed = parse_flags_h(game_path)
    event_entries = parsed["event"]
    alias_names = {alias for alias, _ in parsed["custom_aliases"]}

    # Find candidate flags: vanilla named event flags that aren't custom or already unused
    candidates = []
    for name, val, comment, is_unused in event_entries:
        if is_unused:
            continue  # already FLAG_UNUSED_*
        if name in alias_names:
            continue  # user's custom flag — never touch
        candidates.append(name)

    if not candidates:
        return

    # Bulk scan for surviving references
    ref_map = scan_all_flags_bulk(game_path, candidates)

    # Classify: reclaimable vs blocked
    reclaimable = []  # (flag_name,)
    blocked = []  # (flag_name, reason)

    for flag_name in candidates:
        refs = ref_map.get(flag_name, [])
        # Filter to only non-header references (surviving references in actual code)
        non_header = [r for r in refs
                      if r["category"] not in ("header_define", "header_alias")]
        if non_header:
            # Has surviving references — blocked
            files = sorted(set(r["file"] for r in non_header))
            reason = f"referenced in: {', '.join(files[:3])}"
            if len(files) > 3:
                reason += f" (+{len(files) - 3} more)"
            blocked.append((flag_name, reason))
        else:
            reclaimable.append(flag_name)

    if not reclaimable:
        if blocked:
            report.add("include/constants/flags.h", "flags_blocked",
                        f"{len(blocked)} flags have surviving references")
        return

    # Rewrite flags.h — convert reclaimable flags to FLAG_UNUSED format
    content = _read_file(flags_h_path)
    if content is None:
        return

    reclaimable_set = set(reclaimable)
    lines = content.split("\n")
    new_lines = []
    converted = 0

    for line in lines:
        m = re.match(r'^#define\s+(FLAG_\w+)\s+(0x[0-9A-Fa-f]+)\b', line)
        if m and m.group(1) in reclaimable_set:
            flag_name = m.group(1)
            hex_val = m.group(2)
            # Convert hex value to 3-digit zero-padded format for the name
            try:
                int_val = int(hex_val, 16)
                padded = f"0x{int_val:03X}"
            except ValueError:
                new_lines.append(line)
                continue
            # Build replacement line with consistent alignment
            new_name = f"FLAG_UNUSED_{padded}"
            define_part = f"#define {new_name}"
            # Pad to align the value at a consistent column
            padding = max(1, 42 - len(define_part))
            new_line = f"{define_part}{' ' * padding}{hex_val} // Unused Flag"
            new_lines.append(new_line)
            converted += 1
            reclaimable_set.discard(flag_name)
        else:
            new_lines.append(line)

    if converted > 0:
        _write_file(flags_h_path, "\n".join(new_lines))
        report.add("include/constants/flags.h", "flags_reclaimed",
                    f"Converted {converted} vanilla flags to FLAG_UNUSED_* (reclaimed)")

    if blocked:
        report.add("include/constants/flags.h", "flags_blocked",
                    f"{len(blocked)} flags have surviving references")

    # Store detail in report for later display
    report.flags_reclaimed = converted
    report.flags_blocked = len(blocked)
    report.flags_blocked_detail = blocked
