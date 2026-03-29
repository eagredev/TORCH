"""Scorch Writer — bulk vanilla content removal.

Takes a ScorchPlan and removes all vanilla content from the game tree.
Reuses cleanup_writer functions where possible.
"""
# TORCH_MODULE: Scorch Writer
# TORCH_GROUP: Tools
import copy
import os
import re
import json
import shutil
import zipfile
from datetime import datetime

from torch.project_files import (
    load_map_json, load_layouts, load_wild_encounters,
    find_layout_dir, clear_project_cache,
)
from torch.battle_card import _recalculate_trainers_count


# ============================================================
# SNAPSHOT (scorch-specific — backs up EVERYTHING that will be touched)
# ============================================================

SCORCH_BACKUP_DIR_NAME = "scorch"


def _get_scorch_backup_dir(game_path):
    """Return the scorch backup directory path, creating it if needed."""
    backup_dir = os.path.join(game_path, "backups", SCORCH_BACKUP_DIR_NAME)
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def create_scorch_snapshot(game_path, plan):
    """Create a comprehensive snapshot before scorching.

    Backs up ALL files that will be touched — maps, trainers, encounters,
    scripts, tilesets, C source files, event_scripts.s, etc.

    Returns snapshot_path or None on error.
    """
    backup_dir = _get_scorch_backup_dir(game_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_name = f"scorch_{timestamp}.zip"
    snapshot_path = os.path.join(backup_dir, snapshot_name)

    files_to_backup = set()

    # Maps — back up all vanilla map dirs + map_groups.json
    maps_dir = os.path.join(game_path, "data", "maps")
    files_to_backup.add(os.path.join("data", "maps", "map_groups.json"))
    for map_name in plan.nuke_maps:
        map_dir = os.path.join(maps_dir, map_name)
        if os.path.isdir(map_dir):
            _collect_dir(game_path, map_dir, files_to_backup)

    # Layouts dir — back up all layouts (nuked maps have layouts)
    layouts_dir = os.path.join(game_path, "data", "layouts")
    if os.path.isdir(layouts_dir):
        _collect_dir(game_path, layouts_dir, files_to_backup)

    # Trainers
    for rel in [
        os.path.join("src", "data", "trainers.party"),
        os.path.join("src", "data", "trainers.h"),
        os.path.join("src", "data", "trainer_parties.h"),
        os.path.join("include", "constants", "opponents.h"),
    ]:
        _add_if_exists(game_path, rel, files_to_backup)

    # Encounters
    _add_if_exists(game_path, os.path.join("src", "data", "wild_encounters.json"),
                   files_to_backup)

    # Scripts / assembly source
    _add_if_exists(game_path, os.path.join("data", "event_scripts.s"), files_to_backup)
    _add_if_exists(game_path, os.path.join("data", "map_events.s"), files_to_backup)
    _add_if_exists(game_path, os.path.join("data", "maps.s"), files_to_backup)
    for script in plan.vanilla_scripts:
        spath = script.get("path", "")
        if spath and os.path.isfile(spath):
            files_to_backup.add(os.path.relpath(spath, game_path))

    # Tilesets C source files
    for rel in [
        os.path.join("src", "data", "tilesets", "graphics.h"),
        os.path.join("src", "data", "tilesets", "metatiles.h"),
        os.path.join("src", "data", "tilesets", "headers.h"),
        os.path.join("src", "data", "tilesets", "overrides.h"),
    ]:
        _add_if_exists(game_path, rel, files_to_backup)

    # Tileset data dirs
    for ts in plan.vanilla_tilesets:
        ts_path = ts.get("path", "")
        if ts_path and os.path.isdir(ts_path):
            _collect_dir(game_path, ts_path, files_to_backup)

    # Region map sections (MAPSECs)
    for rel in [
        os.path.join("src", "data", "region_map", "region_map_sections.json"),
        os.path.join("src", "data", "region_map",
                     "region_map_sections.constants.json.txt"),
        os.path.join("include", "constants", "region_map_sections.h"),
    ]:
        _add_if_exists(game_path, rel, files_to_backup)

    # C source patch targets
    for target in plan.c_patch_targets:
        _add_if_exists(game_path, target["rel_path"], files_to_backup)

    # new_game.inc (flag stripping)
    _add_if_exists(game_path,
                   os.path.join("data", "scripts", "new_game.inc"),
                   files_to_backup)

    # post_battle_event_funcs.c (heal location patching)
    _add_if_exists(game_path,
                   os.path.join("src", "post_battle_event_funcs.c"),
                   files_to_backup)

    # maps.h (custom content stubs added by scorch_patcher)
    _add_if_exists(game_path,
                   os.path.join("include", "constants", "maps.h"),
                   files_to_backup)

    # Heal locations
    _add_if_exists(game_path,
                   os.path.join("include", "constants", "heal_locations.h"),
                   files_to_backup)

    # Heal locations data
    _add_if_exists(game_path,
                   os.path.join("src", "data", "heal_locations.h"),
                   files_to_backup)
    _add_if_exists(game_path,
                   os.path.join("src", "data", "heal_locations.json"),
                   files_to_backup)

    # Battle Frontier source files (stub declarations added by scorch_patcher)
    for rel in [
        os.path.join("src", "battle_pike.c"),
        os.path.join("src", "battle_pyramid.c"),
        os.path.join("src", "battle_tent.c"),
    ]:
        _add_if_exists(game_path, rel, files_to_backup)

    # Tileset animation files (patched by scorch_patcher)
    for rel in [
        os.path.join("src", "tileset_anims.c"),
        os.path.join("include", "tileset_anims.h"),
        os.path.join("include", "constants", "metatile_labels.h"),
        "graphics_file_rules.mk",
        os.path.join("include", "gym_leader_rematch.h"),
        os.path.join("include", "constants", "rematches.h"),
        os.path.join("include", "constants", "event_objects.h"),
    ]:
        _add_if_exists(game_path, rel, files_to_backup)

    if not files_to_backup:
        return None

    try:
        with zipfile.ZipFile(snapshot_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path in sorted(files_to_backup):
                abs_path = os.path.join(game_path, rel_path)
                if os.path.exists(abs_path):
                    zf.write(abs_path, rel_path)
        return snapshot_path
    except Exception as e:
        return None


def restore_scorch_snapshot(game_path, snapshot_path):
    """Restore all files from a scorch snapshot.

    Returns list of restored relative paths, or None on error.
    """
    try:
        restored = []
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for member in zf.namelist():
                target = os.path.join(game_path, member)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                restored.append(member)
        return restored
    except Exception as e:
        return None


def list_scorch_snapshots(game_path):
    """Return list of scorch snapshot dicts, newest first."""
    backup_dir = _get_scorch_backup_dir(game_path)
    snapshots = []
    try:
        entries = os.listdir(backup_dir)
    except OSError:
        return snapshots
    for fname in sorted(entries, reverse=True):
        if not fname.startswith("scorch_") or not fname.endswith(".zip"):
            continue
        fpath = os.path.join(backup_dir, fname)
        ts_str = fname[len("scorch_"):-len(".zip")][:15]
        try:
            dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            display_time = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            display_time = ts_str
        snapshots.append({
            "path": fpath,
            "filename": fname,
            "display_time": display_time,
        })
    return snapshots


def _collect_dir(game_path, dir_path, file_set):
    """Walk a directory and add all file relative paths to file_set."""
    for root, _dirs, files in os.walk(dir_path):
        for f in files:
            abs_path = os.path.join(root, f)
            rel_path = os.path.relpath(abs_path, game_path)
            file_set.add(rel_path)


def _add_if_exists(game_path, rel_path, file_set):
    """Add rel_path to file_set if the file exists."""
    if os.path.exists(os.path.join(game_path, rel_path)):
        file_set.add(rel_path)


# ============================================================
# REMOVAL EXECUTION
# ============================================================

class ScorchResult:
    """Tracks what was done during scorch execution."""

    def __init__(self):
        self.maps_removed = 0
        self.layouts_removed = 0
        self.trainers_removed = 0
        self.encounters_removed = 0
        self.scripts_removed = 0
        self.tilesets_removed = 0
        self.mapsecs_removed = 0
        self.mapsecs_created = 0
        self.mapsecs_reassigned = 0
        self.errors = []

    def total_removed(self):
        return (self.maps_removed + self.trainers_removed +
                self.encounters_removed + self.scripts_removed +
                self.tilesets_removed + self.mapsecs_removed)


def execute_scorch(game_path, plan):
    """Execute all removal phases.  Returns a ScorchResult."""
    result = ScorchResult()

    # Phase 1: Rewrite map_groups.json (remove vanilla groups + maps)
    _scorch_map_groups(game_path, plan, result)

    # Phase 2: Remove vanilla map directories + their layouts
    _scorch_map_dirs(game_path, plan, result)

    # Phase 2b: Reassign surviving maps, remove vanilla MAPSECs from JSON
    _scorch_mapsecs(game_path, plan, result)

    # Phase 3: Remove vanilla trainers from trainers.party + opponents.h
    _scorch_trainers(game_path, plan, result)

    # Phase 4: Remove vanilla encounters from wild_encounters.json
    _scorch_encounters(game_path, plan, result)

    # Phase 5: Remove vanilla scripts
    _scorch_scripts(game_path, plan, result)

    # Phase 6: Remove vanilla tilesets
    _scorch_tilesets(game_path, plan, result)

    # Phase 7: Clean up event_scripts.s (remove .includes for deleted scripts/maps)
    _scorch_event_scripts(game_path, plan, result)

    # Phase 8: Clean up layouts.json (remove orphaned layouts)
    _scorch_layouts_json(game_path, plan, result)

    # Phase 9: Strip dead vanilla flags from new_game.inc
    _scorch_new_game_inc(game_path, plan, result)

    return result


# ============================================================
# PHASE 1: MAP GROUPS JSON
# ============================================================

def _scorch_map_groups(game_path, plan, result):
    """Rewrite map_groups.json to remove nuked maps.

    Iterates all groups and filters out maps in plan.nuke_maps.
    Groups that become empty are removed entirely.
    Rescued maps (keep_maps not in any surviving group) get a
    gMapGroup_EngineRequired entry so the build system generates
    their MAP_* constants.
    """
    from torch.project_files import load_map_groups as _load_mg

    data = _load_mg(game_path)
    if not data:
        result.errors.append("Failed to read map_groups.json")
        return

    nuke_set = set(plan.nuke_maps)
    group_order = data.get("group_order", [])

    # Filter nuked maps from every group
    new_data = {"group_order": list(group_order)}
    for group_name in group_order:
        original = data.get(group_name, [])
        filtered = [m for m in original if m not in nuke_set]
        new_data[group_name] = filtered

    # Rescue kept maps not in any surviving group (e.g. InsideOfTruck)
    all_surviving = set()
    for group_name in new_data["group_order"]:
        all_surviving.update(new_data.get(group_name, []))

    rescued = sorted(m for m in plan.keep_maps if m not in all_surviving)
    if rescued:
        rescue_group = "gMapGroup_EngineRequired"
        new_data["group_order"].insert(0, rescue_group)
        new_data[rescue_group] = rescued

    # Filter out empty map groups — an empty group produces a dangling
    # pointer in the compiled gMapGroups[] array, causing runtime crashes
    empty_groups = [g for g in new_data["group_order"]
                    if not new_data.get(g)]
    if empty_groups:
        new_data["group_order"] = [
            g for g in new_data["group_order"] if g not in empty_groups
        ]
        for g in empty_groups:
            new_data.pop(g, None)
        result.errors.append(
            f"Filtered {len(empty_groups)} empty map group(s): "
            + ", ".join(empty_groups)
        )

    groups_file = os.path.join(game_path, "data", "maps", "map_groups.json")
    try:
        with open(groups_file, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=2)
            f.write("\n")
        clear_project_cache()
    except Exception as e:
        result.errors.append(f"Failed to write map_groups.json: {e}")


# ============================================================
# PHASE 2: MAP DIRECTORIES
# ============================================================

def _scorch_map_dirs(game_path, plan, result):
    """Delete all vanilla map directories and their layouts."""
    maps_dir = os.path.join(game_path, "data", "maps")

    # Collect layout dirs used by custom maps (protect these)
    custom_layout_dirs = set()
    for map_name in plan.keep_maps:
        layout_dir = _find_layout_dir(game_path, map_name)
        if layout_dir:
            custom_layout_dirs.add(os.path.realpath(layout_dir))

    # Delete vanilla map dirs
    for map_name in sorted(plan.nuke_maps):
        map_dir = os.path.join(maps_dir, map_name)
        if not os.path.isdir(map_dir):
            continue

        # Check if this map's layout is shared with custom maps
        layout_dir = _find_layout_dir(game_path, map_name)

        try:
            shutil.rmtree(map_dir)
            result.maps_removed += 1
        except OSError as e:
            result.errors.append(f"Failed to remove map dir {map_name}: {e}")
            continue

        # Remove layout dir if not shared with custom maps
        if layout_dir and os.path.isdir(layout_dir):
            real_layout = os.path.realpath(layout_dir)
            if real_layout not in custom_layout_dirs:
                try:
                    shutil.rmtree(layout_dir)
                    result.layouts_removed += 1
                except OSError:
                    pass


def _find_layout_dir(game_path, map_name):
    """Find layout directory for a map.  Returns path or None."""
    mdata = load_map_json(game_path, map_name)
    if not mdata:
        return None
    layout_id = mdata.get("layout")
    if not layout_id:
        return None
    dir_name = find_layout_dir(game_path, layout_id)
    if not dir_name:
        return None
    layout_dir = os.path.join(game_path, "data", "layouts", dir_name)
    if os.path.isdir(layout_dir):
        return layout_dir
    return None


# ============================================================
# PHASE 2b: MAPSECs (Region Map Sections)
# ============================================================

def _scorch_mapsecs(game_path, plan, result):
    """Reassign surviving maps off vanilla MAPSECs, then remove vanilla entries.

    Steps:
    1. Find surviving maps using vanilla MAPSECs and reassign them
    2. Create new MAPSECs in the JSON as needed
    3. Remove all vanilla MAPSEC entries from region_map_sections.json
    4. Patch the Inja template to remove Kanto range macros
    """
    if not plan.vanilla_mapsecs:
        return

    rms_path = os.path.join(
        game_path, "src", "data", "region_map", "region_map_sections.json"
    )
    if not os.path.isfile(rms_path):
        return

    try:
        with open(rms_path, "r", encoding="utf-8", errors="replace") as f:
            rms_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        result.errors.append(f"Failed to read region_map_sections.json: {e}")
        return

    sections = rms_data.get("map_sections", [])
    existing_ids = {s["id"] for s in sections if "id" in s}

    # Step 1: Reassign surviving maps that use vanilla MAPSECs
    new_mapsecs = _reassign_surviving_maps(
        game_path, plan, sections, existing_ids, result
    )

    # Step 2: Add newly created MAPSECs to the sections list
    for new_sec in new_mapsecs:
        sections.append(new_sec)
        existing_ids.add(new_sec["id"])
        result.mapsecs_created += 1

    # Step 3: Remove vanilla MAPSECs from JSON
    keep_ids = existing_ids - plan.vanilla_mapsecs
    new_sections = [s for s in sections if s.get("id", "") in keep_ids]
    removed_count = len(sections) - len(new_sections)
    rms_data["map_sections"] = new_sections

    try:
        with open(rms_path, "w", encoding="utf-8") as f:
            json.dump(rms_data, f, indent=2)
            f.write("\n")
        result.mapsecs_removed = removed_count
    except OSError as e:
        result.errors.append(f"Failed to write region_map_sections.json: {e}")
        return

    # Step 4: Remove Kanto range macros from the Inja template
    _patch_kanto_macros(game_path, result)


def _reassign_surviving_maps(game_path, plan, sections, existing_ids, result):
    """Find surviving maps using vanilla MAPSECs and reassign them.

    Returns a list of new MAPSEC dicts to add to the JSON.
    """
    maps_dir = os.path.join(game_path, "data", "maps")
    new_mapsecs = []
    already_created = set()

    for map_name in sorted(plan.keep_maps):
        mdata = load_map_json(game_path, map_name)
        if not mdata:
            continue

        current_rms = mdata.get("region_map_section", "")
        if not current_rms or current_rms not in plan.vanilla_mapsecs:
            continue

        # This map uses a vanilla MAPSEC — try name matching
        new_id = _name_to_mapsec(map_name)
        if new_id and new_id not in existing_ids and new_id not in already_created:
            # Create a new MAPSEC based on the map name
            new_entry = _make_mapsec_entry(new_id, map_name)
            new_mapsecs.append(new_entry)
            already_created.add(new_id)
            _update_map_json(game_path, map_name, new_id)
            result.mapsecs_reassigned += 1
        elif new_id and (new_id in existing_ids or new_id in already_created):
            # MAPSEC already exists (or was just created) — just reassign
            _update_map_json(game_path, map_name, new_id)
            result.mapsecs_reassigned += 1
        else:
            # No name match — fall back to MAPSEC_NONE
            _update_map_json(game_path, map_name, "MAPSEC_NONE")
            result.mapsecs_reassigned += 1

    return new_mapsecs


def _name_to_mapsec(map_name):
    """Convert a CamelCase map name to MAPSEC_UPPER_SNAKE format.

    Route33 -> MAPSEC_ROUTE_33
    MountainPass -> MAPSEC_MOUNTAIN_PASS
    PlayerBedroom -> MAPSEC_PLAYER_BEDROOM
    LakeElixSouth -> MAPSEC_LAKE_ELIX_SOUTH

    Returns the MAPSEC ID string, or None if conversion fails.
    """
    if not map_name:
        return None
    # Insert underscore before uppercase letters (CamelCase to UPPER_SNAKE)
    snake = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", map_name)
    # Insert underscore before digit sequences preceded by a letter
    snake = re.sub(r"(?<=[a-zA-Z])(?=\d)", "_", snake)
    return "MAPSEC_" + snake.upper()


def _make_mapsec_entry(mapsec_id, map_name):
    """Create a new MAPSEC JSON entry with placeholder coordinates."""
    # Derive display name: MAPSEC_ROUTE_33 -> "ROUTE 33"
    display = mapsec_id.replace("MAPSEC_", "").replace("_", " ")
    return {
        "id": mapsec_id,
        "name": display,
        "x": 0,
        "y": 0,
        "width": 1,
        "height": 1,
    }


def _update_map_json(game_path, map_name, new_mapsec):
    """Update a map's map.json with a new region_map_section value."""
    map_json_path = os.path.join(
        game_path, "data", "maps", map_name, "map.json"
    )
    if not os.path.isfile(map_json_path):
        return

    try:
        with open(map_json_path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        data["region_map_section"] = new_mapsec
        with open(map_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    except (json.JSONDecodeError, OSError):
        pass


def _patch_kanto_macros(game_path, result):
    """Remove Kanto range macro lines from the Inja template.

    The template has static lines:
        #define KANTO_MAPSEC_START  MAPSEC_PALLET_TOWN
        #define KANTO_MAPSEC_END    MAPSEC_SPECIAL_AREA
        #define KANTO_MAPSEC_COUNT (KANTO_MAPSEC_END - KANTO_MAPSEC_START + 1)

    Since all Kanto MAPSECs are removed, these reference nonexistent
    constants.  Remove them — any C code referencing KANTO_MAPSEC_COUNT
    will be caught by the generic patcher.
    """
    template_path = os.path.join(
        game_path, "src", "data", "region_map",
        "region_map_sections.constants.json.txt"
    )
    if not os.path.isfile(template_path):
        return

    try:
        with open(template_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return

    new_lines = []
    removed = 0
    for line in lines:
        if re.match(r"^#define\s+KANTO_MAPSEC_", line):
            removed += 1
            continue
        new_lines.append(line)

    if removed:
        try:
            with open(template_path, "w", encoding="utf-8", errors="replace") as f:
                f.writelines(new_lines)
        except OSError:
            result.errors.append("Failed to patch Kanto macros in Inja template")


# ============================================================
# PHASE 3: TRAINERS
# ============================================================

def _scorch_trainers(game_path, plan, result):
    """Remove all vanilla trainers from trainers.party and opponents.h."""
    if not plan.vanilla_trainers:
        return

    vanilla_consts = {const for const, _tid in plan.vanilla_trainers}

    # --- trainers.party ---
    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    if os.path.isfile(party_path):
        try:
            with open(party_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Remove each vanilla trainer section
            for const in vanilla_consts:
                # Pattern: === TRAINER_NAME ===\n...\n\n (or end of file)
                pattern = re.compile(
                    r"^=== " + re.escape(const) + r" ===\s*$.*?"
                    r"(?=^=== \S+ ===\s*$|\Z)",
                    re.MULTILINE | re.DOTALL
                )
                content = pattern.sub("", content)

            # Clean up excessive blank lines
            content = re.sub(r"\n{3,}", "\n\n", content)

            with open(party_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(content)
            result.trainers_removed += len(vanilla_consts)

            # Regenerate trainers.h from the scorched .party using
            # trainerproc (same pipeline as the Makefile rule).  We do this
            # ourselves because: (a) deleting .h causes a race condition in
            # parallel builds where data.c compiles before trainerproc runs;
            # (b) leaving the old .h causes timestamp issues.
            _regenerate_trainers_h(game_path)
        except Exception as e:
            result.errors.append(f"Failed to modify trainers.party: {e}")

    # --- opponents.h ---
    opponents_path = os.path.join(game_path, "include", "constants", "opponents.h")
    if os.path.isfile(opponents_path):
        try:
            with open(opponents_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                m = re.match(r"^#define\s+(TRAINER_\w+)\s+\d+", line)
                if m and m.group(1) in vanilla_consts:
                    continue
                new_lines.append(line)

            with open(opponents_path, "w", encoding="utf-8", errors="replace") as f:
                f.writelines(new_lines)

            # Recalculate TRAINERS_COUNT after removing vanilla defines
            new_count = _recalculate_trainers_count(opponents_path)
            if new_count is not None:
                print(f"  Updated TRAINERS_COUNT to {new_count}")
        except Exception as e:
            result.errors.append(f"Failed to modify opponents.h: {e}")

    # --- trainers.h (legacy format, only when .party doesn't exist) ---
    # When .party exists, trainers.h is auto-generated from it.
    # The .party handler above already scorched + regenerated .h.
    trainers_h = os.path.join(game_path, "src", "data", "trainers.h")
    if os.path.isfile(trainers_h) and not os.path.isfile(party_path):
        try:
            with open(trainers_h, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            for const in vanilla_consts:
                pattern = re.compile(
                    r"\n?\s*\[" + re.escape(const) + r"\]\s*=\s*\n\s*\{.*?\n\s*\},",
                    re.DOTALL
                )
                content = pattern.sub("", content)

            with open(trainers_h, "w", encoding="utf-8", errors="replace") as f:
                f.write(content)
        except Exception as e:
            result.errors.append(f"Failed to modify trainers.h: {e}")


def _regenerate_trainers_h(game_path):
    """Regenerate trainers.h from trainers.party using trainerproc.

    Replicates the Makefile rule:
      $(CPP) $(CPPFLAGS) -traditional-cpp - < $< | $(TRAINERPROC) -o $@ -i $< -

    Falls back silently if trainerproc hasn't been compiled yet (the build
    system will handle it).
    """
    party = os.path.join(game_path, "src", "data", "trainers.party")
    gen_h = os.path.join(game_path, "src", "data", "trainers.h")
    trainerproc = os.path.join(game_path, "tools", "trainerproc", "trainerproc")

    if not os.path.isfile(party):
        return

    # Build trainerproc if needed
    if not os.path.isfile(trainerproc):
        try:
            import subprocess
            subprocess.run(
                ["make", "-C", os.path.join(game_path, "tools", "trainerproc")],
                capture_output=True, timeout=30
            )
        except Exception:
            # Fall back: delete .h and hope the build system catches it
            if os.path.isfile(gen_h):
                try:
                    os.remove(gen_h)
                except OSError:
                    pass
            return

    if not os.path.isfile(trainerproc):
        if os.path.isfile(gen_h):
            try:
                os.remove(gen_h)
            except OSError:
                pass
        return

    # Run the pipeline: cpp | trainerproc
    try:
        import subprocess
        cpp_cmd = [
            "arm-none-eabi-cpp",
            "-I", os.path.join(game_path, "include"),
            "-I", os.path.join(game_path, "tools", "agbcc", "include"),
            "-traditional-cpp", "-"
        ]
        with open(party, "r") as party_f:
            cpp_result = subprocess.run(
                cpp_cmd, stdin=party_f, capture_output=True, text=True, timeout=15
            )
        if cpp_result.returncode != 0:
            # Fallback: delete .h
            if os.path.isfile(gen_h):
                os.remove(gen_h)
            return

        proc_cmd = [trainerproc, "-o", gen_h, "-i", party, "-"]
        subprocess.run(
            proc_cmd, input=cpp_result.stdout, capture_output=True,
            text=True, timeout=15
        )
    except Exception:
        # Fallback: delete .h
        if os.path.isfile(gen_h):
            try:
                os.remove(gen_h)
            except OSError:
                pass


# ============================================================
# PHASE 4: ENCOUNTERS
# ============================================================

def _scorch_encounters(game_path, plan, result):
    """Remove all vanilla encounters from wild_encounters.json."""
    data = load_wild_encounters(game_path)
    if not data:
        return
    data = copy.deepcopy(data)

    vanilla_map_consts = set()
    for enc in plan.vanilla_encounters:
        vanilla_map_consts.add(enc.get("map", ""))

    groups = data.get("wild_encounter_groups", [])
    for group in groups:
        encounters = group.get("encounters", [])
        group["encounters"] = [
            e for e in encounters if e.get("map", "") not in vanilla_map_consts
        ]

    removed_count = len(plan.vanilla_encounters)

    enc_path = os.path.join(game_path, "src", "data", "wild_encounters.json")
    try:
        with open(enc_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        clear_project_cache()
        result.encounters_removed += removed_count
    except Exception as e:
        result.errors.append(f"Failed to write wild_encounters.json: {e}")


# ============================================================
# PHASE 5: SCRIPTS
# ============================================================

def _scorch_scripts(game_path, plan, result):
    """Delete vanilla shared scripts from data/scripts/."""
    for script in plan.vanilla_scripts:
        spath = script.get("path", "")
        if spath and os.path.isfile(spath):
            try:
                os.remove(spath)
                result.scripts_removed += 1
            except OSError as e:
                result.errors.append(f"Failed to remove script {script['filename']}: {e}")

            # Also remove .pory if it exists
            pory_path = spath.replace(".inc", ".pory")
            if pory_path != spath and os.path.isfile(pory_path):
                try:
                    os.remove(pory_path)
                except OSError:
                    pass


# ============================================================
# PHASE 6: TILESETS
# ============================================================

def _scorch_tilesets(game_path, plan, result):
    """Remove vanilla tileset dirs and update C source headers."""
    if not plan.vanilla_tilesets:
        return

    ts_data_dir = os.path.join(game_path, "src", "data", "tilesets")
    graphics_h = os.path.join(ts_data_dir, "graphics.h")
    metatiles_h = os.path.join(ts_data_dir, "metatiles.h")
    headers_h = os.path.join(ts_data_dir, "headers.h")
    overrides_h = os.path.join(ts_data_dir, "overrides.h")

    # Collect all vanilla tileset dir names and symbols
    vanilla_dirs = set()
    vanilla_symbols = set()
    for ts in plan.vanilla_tilesets:
        vanilla_dirs.add(ts["dir_name"])
        sym = ts["symbol"].replace("gTileset_", "")
        vanilla_symbols.add(sym)

    # Delete tileset directories
    for ts in plan.vanilla_tilesets:
        ts_path = ts.get("path", "")
        if ts_path and os.path.isdir(ts_path):
            try:
                shutil.rmtree(ts_path)
                result.tilesets_removed += 1
            except OSError as e:
                result.errors.append(f"Failed to remove tileset dir {ts['dir_name']}: {e}")

    # Clean up graphics.h — remove lines referencing vanilla tileset dirs
    if os.path.isfile(graphics_h):
        _strip_lines_matching_dirs(graphics_h, vanilla_dirs, "data/tilesets/secondary/")
        _strip_symbol_lines(graphics_h, vanilla_symbols, "gTilesetTiles_", "gTilesetPalettes_")

    # Clean up metatiles.h
    if os.path.isfile(metatiles_h):
        _strip_lines_matching_dirs(metatiles_h, vanilla_dirs, "data/tilesets/secondary/")
        _strip_symbol_lines(metatiles_h, vanilla_symbols, "gMetatiles_", "gMetatileAttributes_")

    # Clean up headers.h — remove struct blocks for vanilla tilesets
    if os.path.isfile(headers_h):
        _strip_tileset_structs(headers_h, vanilla_symbols)

    # Clean up overrides.h
    if os.path.isfile(overrides_h):
        _strip_lines_matching_dirs(overrides_h, vanilla_dirs, "data/tilesets/secondary/")
        _strip_override_blocks(overrides_h, vanilla_symbols)


def _strip_lines_matching_dirs(file_path, dir_names, prefix):
    """Remove any lines containing prefix + dir_name + '/' for any dir in dir_names."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return

    markers = {f"{prefix}{d}/" for d in dir_names}
    new_lines = [l for l in lines if not any(m in l for m in markers)]

    if len(new_lines) < len(lines):
        try:
            with open(file_path, "w", encoding="utf-8", errors="replace") as f:
                f.writelines(new_lines)
        except OSError:
            pass


def _strip_symbol_lines(file_path, symbols, *prefixes):
    """Remove lines containing any of the given symbol prefixes + symbol name."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return

    patterns = []
    for prefix in prefixes:
        for sym in symbols:
            patterns.append(f"{prefix}{sym}")

    new_lines = [l for l in lines if not any(p in l for p in patterns)]

    if len(new_lines) < len(lines):
        try:
            with open(file_path, "w", encoding="utf-8", errors="replace") as f:
                f.writelines(new_lines)
        except OSError:
            pass


def _strip_tileset_structs(headers_h_path, vanilla_symbols):
    """Remove 'const struct Tileset gTileset_<Name>' blocks from headers.h."""
    try:
        with open(headers_h_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return

    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if this starts a vanilla tileset struct
        m = re.match(r"\s*const struct Tileset gTileset_(\w+)\s*=", line)
        if m and m.group(1) in vanilla_symbols:
            # Skip blank lines before the struct
            while new_lines and new_lines[-1].strip() == "":
                new_lines.pop()
            # Skip past the closing "};"
            while i < len(lines):
                if lines[i].strip() == "};":
                    i += 1
                    break
                i += 1
            continue

        # Also remove gTilesetPointer_* lines for vanilla tilesets
        m = re.match(r"\s*const struct Tileset \*\s*const gTilesetPointer_(\w+)", line)
        if m and m.group(1) in vanilla_symbols:
            i += 1
            continue

        new_lines.append(line)
        i += 1

    try:
        with open(headers_h_path, "w", encoding="utf-8", errors="replace") as f:
            f.writelines(new_lines)
    except OSError:
        pass


def _strip_override_blocks(overrides_h_path, vanilla_symbols):
    """Remove palette override entries and structs for vanilla tilesets."""
    try:
        with open(overrides_h_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return

    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Static INCBIN lines: sTilesetPalOverride_<Name><digits>
        m = re.match(r"\s*static\s+const\s+u16\s+sTilesetPalOverride_(\w+?)(\d)", line)
        if m and m.group(1) in vanilla_symbols:
            i += 1
            continue

        # Struct blocks: gTilesetPalOverrides_<Name>[]
        m = re.match(r"\s*const struct PaletteOverride gTilesetPalOverrides_(\w+)\[\]", line)
        if m and m.group(1) in vanilla_symbols:
            while i < len(lines):
                if lines[i].strip() == "};":
                    i += 1
                    break
                i += 1
            continue

        new_lines.append(line)
        i += 1

    try:
        with open(overrides_h_path, "w", encoding="utf-8", errors="replace") as f:
            f.writelines(new_lines)
    except OSError:
        pass


# ============================================================
# PHASE 7: EVENT_SCRIPTS.S
# ============================================================

def _scorch_event_scripts(game_path, plan, result):
    """Clean up data/event_scripts.s — remove .include lines for deleted content.

    Keeps gStdScripts table (indices 0-10) and any includes for custom content.
    """
    es_path = os.path.join(game_path, "data", "event_scripts.s")
    if not os.path.isfile(es_path):
        return

    try:
        with open(es_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return

    # Build set of filenames that were deleted (scripts + map scripts)
    deleted_script_files = set()
    for script in plan.vanilla_scripts:
        deleted_script_files.add(script["filename"])

    # Build set of vanilla map folder names for .include path matching
    vanilla_map_folders = set(plan.nuke_maps)

    new_lines = []
    for line in lines:
        # Check .include directives
        m = re.match(r'\s*\.include\s+"([^"]+)"', line)
        if m:
            inc_path = m.group(1)
            # Remove includes for deleted scripts
            inc_basename = os.path.basename(inc_path)
            if inc_basename in deleted_script_files:
                continue
            # Remove includes for vanilla map scripts
            # Pattern: data/maps/MapName/scripts.inc
            for vmap in vanilla_map_folders:
                if f"data/maps/{vmap}/" in inc_path:
                    break
            else:
                new_lines.append(line)
                continue
            # If we matched a vanilla map, skip this line
            continue

        new_lines.append(line)

    # Clean up excessive blank lines
    cleaned = []
    prev_blank = False
    for line in new_lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank

    try:
        with open(es_path, "w", encoding="utf-8", errors="replace") as f:
            f.writelines(cleaned)
    except OSError:
        pass


# ============================================================
# PHASE 8: LAYOUTS.JSON
# ============================================================

def _scorch_layouts_json(game_path, plan, result):
    """Remove orphaned layout entries from layouts.json.

    Uses the reference-based strategy from Phase 7b: a layout survives
    only if it is referenced by a surviving map (via map.json "layout"
    field or setmaplayoutindex in scripts).  Falls back to the legacy
    blockdata-exists check if the scanner didn't populate
    referenced_layouts (defensive; shouldn't happen in practice).
    """
    data = load_layouts(game_path)
    if not data:
        return
    data = copy.deepcopy(data)

    layouts = data.get("layouts", [])
    if not layouts:
        return

    use_ref_strategy = bool(plan.referenced_layouts)

    kept_layouts = []
    removed_dirs = set()

    for layout in layouts:
        lid = layout.get("id", "")

        if use_ref_strategy:
            # Reference-based: keep only if referenced by a surviving map
            if lid and lid in plan.referenced_layouts:
                kept_layouts.append(layout)
            else:
                result.layouts_removed += 1
                # Track layout dir for deletion
                bd = layout.get("blockdata_filepath", "")
                if bd:
                    parts = bd.replace("\\", "/").split("/")
                    if len(parts) >= 3:
                        removed_dirs.add(
                            os.path.join(game_path, parts[0], parts[1], parts[2])
                        )
        else:
            # Fallback: blockdata-exists check (legacy strategy)
            bd = layout.get("blockdata_filepath", "")
            if bd:
                bd_path = os.path.join(game_path, bd)
                if os.path.exists(bd_path):
                    kept_layouts.append(layout)
                else:
                    result.layouts_removed += 1
            else:
                kept_layouts.append(layout)

    if len(kept_layouts) < len(layouts):
        data["layouts"] = kept_layouts
        layouts_file = os.path.join(game_path, "data", "layouts", "layouts.json")
        try:
            with open(layouts_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            clear_project_cache()
        except Exception:
            pass

    # Delete orphaned layout directories
    for layout_dir in removed_dirs:
        if os.path.isdir(layout_dir):
            try:
                shutil.rmtree(layout_dir)
            except OSError:
                pass


# ============================================================
# PHASE 9: NEW_GAME.INC FLAG STRIPPING
# ============================================================

def _scorch_new_game_inc(game_path, plan, result):
    """Strip dead vanilla flags from data/scripts/new_game.inc.

    After Phoenix nukes vanilla maps, EventScript_ResetAllMapFlags still
    sets ~161 flags for vanilla Hoenn NPCs that no longer exist.
    We strip setflag lines whose flag name contains a vanilla map fragment
    (e.g. FLAG_HIDE_LITTLEROOT_TOWN_* when LittlerootTown is nuked),
    but keep flags for maps in keep_maps (e.g. InsideOfTruck).
    """
    inc_path = os.path.join(game_path, "data", "scripts", "new_game.inc")
    if not os.path.isfile(inc_path):
        return

    try:
        with open(inc_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return

    # Build UPPER_SNAKE fragments for nuked maps (not in keep_maps)
    nuke_fragments = set()
    for map_name in plan.nuke_maps:
        if map_name not in plan.keep_maps:
            upper = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", map_name).upper()
            nuke_fragments.add(upper)

    # Build UPPER_SNAKE fragments for kept maps (never strip these)
    keep_fragments = set()
    for map_name in plan.keep_maps:
        upper = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", map_name).upper()
        keep_fragments.add(upper)

    stripped = 0
    new_lines = []
    for line in lines:
        if _should_strip_flag_line(line, nuke_fragments, keep_fragments):
            stripped += 1
            continue
        new_lines.append(line)

    if not stripped:
        return

    # Collapse runs of 3+ blank lines to 2
    cleaned = _collapse_blank_runs(new_lines)

    try:
        with open(inc_path, "w", encoding="utf-8", errors="replace") as f:
            f.writelines(cleaned)
    except OSError:
        result.errors.append("Failed to write new_game.inc")
        return

    result.scripts_removed += stripped  # reuse counter for flag lines


def _should_strip_flag_line(line, nuke_fragments, keep_fragments):
    """Return True if this setflag line should be stripped.

    Strips all FLAG_HIDE_* and FLAG_BERRY_TREE_* setflags except
    those referencing maps in keep_maps.  This is safe because
    Phoenix removes all vanilla maps — all vanilla hide flags and
    berry flags are dead code.
    """
    stripped = line.strip()
    if not stripped.startswith("setflag "):
        return False
    flag_name = stripped.split(None, 1)[1] if " " in stripped else ""

    # Only strip hide flags and berry tree flags
    if not (flag_name.startswith("FLAG_HIDE_") or flag_name.startswith("FLAG_BERRY_TREE_")):
        return False

    # Never strip flags that reference a kept map
    for kf in keep_fragments:
        if kf in flag_name:
            return False

    # Strip all other hide/berry flags (all vanilla maps are gone)
    return True


def _collapse_blank_runs(lines):
    """Collapse runs of 3+ consecutive blank lines to 2."""
    result = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)
    return result
