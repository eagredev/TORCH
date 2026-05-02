"""SCORCH Writer — surgical removal engine with snapshot/restore.

Handles the actual file modifications for vanilla content removal.
Follows the battle_migrator pattern: snapshot -> phase-based writes.
"""
# TORCH_MODULE: SCORCH Writer
# TORCH_GROUP: Tools
import copy
import os
import re
import json
import shutil
import zipfile
from datetime import datetime

from torch.cleanup_scanner import (
    RemovalPlan, RemovalItem, SAFE, BLOCKED, CAUTION,
    _classify_trainers,
    _map_const_to_folder,
)
from torch.project_files import (
    load_map_groups, load_layouts, load_map_json, load_wild_encounters,
    find_layout_dir, clear_project_cache, folder_to_map_const,
)
from torch.colours import DGOLD, DIM, RST


# ============================================================
# SNAPSHOT / RESTORE
# ============================================================

CLEANUP_BACKUP_DIR_NAME = "cleanup"


def _get_cleanup_backup_dir(game_path):
    """Return the cleanup backup directory path, creating it if needed."""
    backup_dir = os.path.join(game_path, "backups", CLEANUP_BACKUP_DIR_NAME)
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def _list_cleanup_snapshots(game_path):
    """Return list of cleanup snapshot dicts, newest first.

    Each dict: {path, filename, timestamp, display_time, category_hint, legacy}
    Supports both old format (cleanup_YYYYMMDD_HHMMSS[_cat].zip) and
    new format (scorch_<cat>_YYYYMMDD_HHMMSS.zip).
    """
    backup_dir = _get_cleanup_backup_dir(game_path)
    snapshots = []
    for fname in sorted(os.listdir(backup_dir), reverse=True):
        if not fname.endswith(".zip"):
            continue
        fpath = os.path.join(backup_dir, fname)

        if fname.startswith("scorch_"):
            # New format: scorch_<category>_YYYYMMDD_HHMMSS.zip
            body = fname[len("scorch_"):-len(".zip")]
            # Timestamp is last 15 chars (YYYYMMDD_HHMMSS)
            ts_str = body[-15:]
            category_hint = body[:-16] if len(body) > 15 else ""
            legacy = False
        elif fname.startswith("cleanup_"):
            # Legacy format: cleanup_YYYYMMDD_HHMMSS[_category].zip
            body = fname[len("cleanup_"):-len(".zip")]
            ts_str = body[:15]
            category_hint = body[16:] if len(body) > 15 else ""
            legacy = True
        else:
            continue

        try:
            dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            display_time = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            display_time = ts_str
        snapshots.append({
            "path": fpath,
            "filename": fname,
            "timestamp": ts_str,
            "display_time": display_time,
            "category_hint": category_hint,
            "legacy": legacy,
        })
    return snapshots


def _create_cleanup_snapshot(game_path, plan, category_hint=""):
    """Create a ZIP snapshot of all files that will be touched by the removal plan.

    Returns the snapshot path, or None on error.
    """
    backup_dir = _get_cleanup_backup_dir(game_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = category_hint if category_hint else "full"
    snapshot_name = f"scorch_{label}_{timestamp}.zip"
    snapshot_path = os.path.join(backup_dir, snapshot_name)

    # Collect all files that will be affected
    files_to_backup = set()

    for item in plan.items:
        if item.status != SAFE:
            continue

        if item.category == "maps":
            map_dir = os.path.join(game_path, "data", "maps", item.name)
            if os.path.isdir(map_dir):
                for root, dirs, files in os.walk(map_dir):
                    for f in files:
                        abs_path = os.path.join(root, f)
                        rel_path = os.path.relpath(abs_path, game_path)
                        files_to_backup.add(rel_path)
            # Also backup files modified during map removal
            files_to_backup.add(os.path.join("data", "maps", "map_groups.json"))
            files_to_backup.add(os.path.join("data", "event_scripts.s"))
            files_to_backup.add(os.path.join("data", "layouts", "layouts.json"))
            # Layout dir
            layout_dir = _find_map_layout_dir(game_path, item.name)
            if layout_dir and os.path.isdir(layout_dir):
                for root, dirs, files in os.walk(layout_dir):
                    for f in files:
                        abs_path = os.path.join(root, f)
                        rel_path = os.path.relpath(abs_path, game_path)
                        files_to_backup.add(rel_path)

        elif item.category == "trainers":
            # Backup trainers.party and opponents.h
            for rel in [
                os.path.join("src", "data", "trainers.party"),
                os.path.join("src", "data", "trainers.h"),
                os.path.join("src", "data", "trainer_parties.h"),
                os.path.join("include", "constants", "opponents.h"),
            ]:
                if os.path.exists(os.path.join(game_path, rel)):
                    files_to_backup.add(rel)

        elif item.category == "encounters":
            files_to_backup.add(os.path.join("src", "data", "wild_encounters.json"))

        elif item.category == "frontier":
            info = item.data
            if info.get("frontier_data_dir"):
                data_dir = info["frontier_data_dir"]
                for root, dirs, files in os.walk(data_dir):
                    for f in files:
                        abs_path = os.path.join(root, f)
                        rel_path = os.path.relpath(abs_path, game_path)
                        files_to_backup.add(rel_path)
            for map_name in info.get("frontier_maps", []):
                map_dir = os.path.join(game_path, "data", "maps", map_name)
                if os.path.isdir(map_dir):
                    for root, dirs, files in os.walk(map_dir):
                        for f in files:
                            abs_path = os.path.join(root, f)
                            rel_path = os.path.relpath(abs_path, game_path)
                            files_to_backup.add(rel_path)

        elif item.category == "scripts":
            fpath = item.data.get("path", "")
            if fpath and os.path.exists(fpath):
                rel_path = os.path.relpath(fpath, game_path)
                files_to_backup.add(rel_path)
                # Also backup the .pory source if it exists
                pory_path = fpath.replace(".inc", ".pory")
                if pory_path != fpath and os.path.exists(pory_path):
                    files_to_backup.add(os.path.relpath(pory_path, game_path))
            files_to_backup.add(os.path.join("data", "event_scripts.s"))

        elif item.category == "tilesets":
            ts_path = item.data.get("path", "")
            if ts_path and os.path.isdir(ts_path):
                for root, dirs, files in os.walk(ts_path):
                    for f in files:
                        abs_path = os.path.join(root, f)
                        rel_path = os.path.relpath(abs_path, game_path)
                        files_to_backup.add(rel_path)
            # Always include the C source files modified during tileset removal
            files_to_backup.add(os.path.join("src", "data", "tilesets", "graphics.h"))
            files_to_backup.add(os.path.join("src", "data", "tilesets", "metatiles.h"))
            files_to_backup.add(os.path.join("src", "data", "tilesets", "headers.h"))
            files_to_backup.add(os.path.join("src", "data", "tilesets", "overrides.h"))

    if not files_to_backup:
        # Nothing to snapshot — either no safe items or only categories
        # without file-level removal (graphics, music).  Not an error.
        return "skip"

    try:
        with zipfile.ZipFile(snapshot_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path in sorted(files_to_backup):
                abs_path = os.path.join(game_path, rel_path)
                if os.path.exists(abs_path):
                    zf.write(abs_path, rel_path)
        return snapshot_path
    except Exception as e:
        print(f"  ERROR creating SCORCH snapshot: {e}")
        return None


def _restore_cleanup_snapshot(game_path, snapshot_path):
    """Restore all files from a cleanup snapshot ZIP.

    Checks for files modified since the snapshot was taken and warns
    before overwriting them.  Returns list of restored relative paths,
    or None on error.
    """
    try:
        # Pre-extract check: find files modified since the snapshot
        modified = []
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for member in zf.namelist():
                target = os.path.join(game_path, member)
                if not os.path.exists(target):
                    continue
                snap_data = zf.read(member)
                try:
                    with open(target, "rb") as f:
                        disk_data = f.read()
                except OSError:
                    continue
                if disk_data != snap_data:
                    modified.append(member)

        if modified:
            print(f"\n  {DGOLD}WARNING:{RST} {len(modified)} file(s) have been "
                  f"modified since this snapshot was taken:")
            for rel in modified[:10]:
                print(f"    {DIM}{rel}{RST}")
            if len(modified) > 10:
                print(f"    {DIM}...and {len(modified) - 10} more{RST}")
            print()
            try:
                proceed = input("  Overwrite these files? [y/N] > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return []
            if proceed != "y":
                print("  Restore cancelled.")
                return []

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
        print(f"  ERROR during SCORCH restore: {e}")
        return None


# ============================================================
# MAP REMOVAL
# ============================================================

def _find_map_layout_dir(game_path, map_name):
    """Find the layout directory for a map by reading its map.json + layouts.json.

    Returns absolute path to layout dir, or None.
    """
    map_data = load_map_json(game_path, map_name)
    if not map_data:
        return None
    layout_id = str(map_data.get("layout", map_data.get("layout_id", "")))
    if not layout_id:
        return None
    dir_name = find_layout_dir(game_path, layout_id)
    if not dir_name:
        return None
    layout_dir = os.path.join(game_path, "data", "layouts", dir_name)
    if os.path.isdir(layout_dir):
        return layout_dir
    return None


def _check_layout_shared(game_path, layout_dir, map_name):
    """Check if a layout is shared by other maps (besides the one being removed).

    Returns list of other map names using this layout, or empty list.
    """
    if not layout_dir:
        return []

    # Find the LAYOUT_ID for this layout dir from layouts.json
    layout_dir_name = os.path.basename(layout_dir)
    ldata = load_layouts(game_path)
    layout_id = None
    if ldata:
        for entry in ldata.get("layouts", []):
            bd = entry.get("blockdata_filepath", "")
            if bd and os.path.basename(os.path.dirname(bd)) == layout_dir_name:
                layout_id = entry.get("id")
                break

    if not layout_id:
        return []

    other_users = []
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return []
    for other_map in os.listdir(maps_dir):
        if other_map == map_name:
            continue
        data = load_map_json(game_path, other_map)
        if not data:
            continue
        if data.get("layout") == layout_id:
            other_users.append(other_map)
    return other_users


def _remove_map_from_groups_json(game_path, map_name):
    """Remove a map from map_groups.json.

    Removes from its group array and from group_order if the group becomes empty.
    Returns True on success.
    """
    data = load_map_groups(game_path)
    if data is None:
        return False

    # Work on a copy to avoid mutating cached data
    data = copy.deepcopy(data)

    modified = False
    group_order = data.get("group_order", [])
    groups_file = os.path.join(game_path, "data", "maps", "map_groups.json")

    for group_name in list(group_order):
        maps_list = data.get(group_name, [])
        if map_name in maps_list:
            maps_list.remove(map_name)
            data[group_name] = maps_list
            modified = True
            # If group is now empty, remove it from group_order and data
            if not maps_list:
                group_order.remove(group_name)
                del data[group_name]
            break

    if modified:
        data["group_order"] = group_order
        try:
            with open(groups_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            clear_project_cache()
            return True
        except Exception:
            return False
    return False


def _remove_map_from_encounters(game_path, map_name):
    """Remove a map's entries from wild_encounters.json.

    Returns number of entries removed.
    """
    enc_path = os.path.join(game_path, "src", "data", "wild_encounters.json")
    if not os.path.exists(enc_path):
        return 0

    data = load_wild_encounters(game_path)
    if not data:
        return 0
    data = copy.deepcopy(data)

    map_const = folder_to_map_const(map_name)
    removed_count = 0

    groups = data.get("wild_encounter_groups", [])
    for group in groups:
        encounters = group.get("encounters", [])
        original_len = len(encounters)
        group["encounters"] = [
            enc for enc in encounters
            if enc.get("map") != map_const
        ]
        removed_count += original_len - len(group["encounters"])

    if removed_count > 0:
        try:
            with open(enc_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            clear_project_cache()
        except Exception:
            pass

    return removed_count


def _remove_map_heal_locations(game_path, map_name):
    """Remove heal location entries for a map from heal_locations.json.

    Returns number of entries removed.
    """
    heal_path = os.path.join(game_path, "src", "data", "heal_locations.json")
    if not os.path.exists(heal_path):
        # Try alternate location
        heal_path = os.path.join(game_path, "src", "data", "heallocations.json")
        if not os.path.exists(heal_path):
            return 0

    try:
        with open(heal_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0

    map_const = folder_to_map_const(map_name)
    locations = data.get("heal_locations", [])
    original_len = len(locations)
    data["heal_locations"] = [
        loc for loc in locations
        if loc.get("map") != map_const and loc.get("map") != map_name
    ]
    removed = original_len - len(data["heal_locations"])

    if removed > 0:
        try:
            with open(heal_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
        except Exception:
            pass

    return removed


def remove_maps(game_path, items):
    """Remove a list of SAFE map RemovalItems.

    Returns (removed_count, errors_list).
    """
    removed = 0
    errors = []
    removed_names = []

    for item in items:
        if item.status != SAFE or item.category != "maps":
            continue

        map_name = item.name
        map_dir = os.path.join(game_path, "data", "maps", map_name)

        # Phase 1: Non-destructive updates (JSON edits)
        _remove_map_from_groups_json(game_path, map_name)
        _remove_map_from_encounters(game_path, map_name)
        _remove_map_heal_locations(game_path, map_name)

        # Phase 2: Layout removal (if not shared)
        layout_dir = _find_map_layout_dir(game_path, map_name)
        if layout_dir:
            shared_users = _check_layout_shared(game_path, layout_dir, map_name)
            if not shared_users:
                try:
                    shutil.rmtree(layout_dir)
                except OSError as e:
                    errors.append(f"Layout removal failed for {map_name}: {e}")

        # Phase 3: Delete map directory
        if os.path.isdir(map_dir):
            try:
                shutil.rmtree(map_dir)
                removed += 1
                removed_names.append(map_name)
            except OSError as e:
                errors.append(f"Map dir removal failed for {map_name}: {e}")
        else:
            removed += 1  # Already gone, count as success
            removed_names.append(map_name)

    # Phase 4: Clean up event_scripts.s and layouts.json
    if removed_names:
        _remove_maps_from_event_scripts(game_path, removed_names, errors)
        _remove_orphaned_layouts(game_path, errors)

    return removed, errors


def _remove_maps_from_event_scripts(game_path, map_names, errors):
    """Remove .include lines for deleted maps from data/event_scripts.s."""
    es_path = os.path.join(game_path, "data", "event_scripts.s")
    if not os.path.isfile(es_path):
        return

    # Build set of include patterns to remove
    remove_patterns = set()
    for name in map_names:
        remove_patterns.add(f"data/maps/{name}/scripts.inc")

    try:
        with open(es_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        errors.append(f"Failed to read event_scripts.s: {e}")
        return

    new_lines = []
    removed_count = 0
    for line in lines:
        if any(pat in line for pat in remove_patterns):
            removed_count += 1
            continue
        new_lines.append(line)

    if removed_count == 0:
        return

    try:
        with open(es_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except OSError as e:
        errors.append(f"Failed to write event_scripts.s: {e}")


def _remove_orphaned_layouts(game_path, errors):
    """Remove layout entries from layouts.json where the layout directory no longer exists."""
    data = load_layouts(game_path)
    if not data:
        return

    data = copy.deepcopy(data)
    layouts = data.get("layouts", [])
    original_count = len(layouts)

    # Keep only layouts whose blockdata_filepath directory still exists
    surviving = []
    for layout in layouts:
        blockdata = layout.get("blockdata_filepath", "")
        if blockdata:
            abs_path = os.path.join(game_path, blockdata)
            layout_dir = os.path.dirname(abs_path)
            if not os.path.isdir(layout_dir):
                continue  # layout dir is gone — remove this entry
        surviving.append(layout)

    if len(surviving) == original_count:
        return  # nothing to remove

    data["layouts"] = surviving
    layouts_json = os.path.join(game_path, "data", "layouts", "layouts.json")
    try:
        with open(layouts_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        clear_project_cache()
    except Exception as e:
        errors.append(f"Failed to write layouts.json: {e}")


# ============================================================
# TRAINER REMOVAL
# ============================================================

def _detect_trainer_format(game_path):
    """Detect whether the project uses .party or .h trainer format.

    Returns 'party' or 'legacy'.
    """
    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    if os.path.exists(party_path) and os.path.getsize(party_path) > 0:
        return "party"
    return "legacy"


def remove_trainers(game_path, items):
    """Remove a list of SAFE trainer RemovalItems.

    Handles both .party and legacy .h formats.
    Returns (removed_count, errors_list).
    """
    removed = 0
    errors = []
    fmt = _detect_trainer_format(game_path)

    opponents_path = os.path.join(game_path, "include", "constants", "opponents.h")
    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    trainers_h_path = os.path.join(game_path, "src", "data", "trainers.h")
    trainer_parties_path = os.path.join(game_path, "src", "data", "trainer_parties.h")

    # Batch-read file contents for efficiency
    opponents_content = ""
    if os.path.exists(opponents_path):
        with open(opponents_path, encoding="utf-8") as f:
            opponents_content = f.read()

    party_content = ""
    if fmt == "party" and os.path.exists(party_path):
        with open(party_path, encoding="utf-8") as f:
            party_content = f.read()

    trainers_h_content = ""
    if fmt == "legacy" and os.path.exists(trainers_h_path):
        with open(trainers_h_path, encoding="utf-8") as f:
            trainers_h_content = f.read()

    trainer_parties_content = ""
    if fmt == "legacy" and os.path.exists(trainer_parties_path):
        with open(trainer_parties_path, encoding="utf-8") as f:
            trainer_parties_content = f.read()

    for item in items:
        if item.status != SAFE or item.category != "trainers":
            continue

        trainer_const = item.name

        # Remove from opponents.h
        pattern = r"^#define\s+" + re.escape(trainer_const) + r"\s+\d+\s*\n"
        opponents_content, count = re.subn(pattern, "", opponents_content,
                                            flags=re.MULTILINE)

        if fmt == "party":
            # Remove from trainers.party
            section_pattern = (
                r"^=== " + re.escape(trainer_const) + r" ===\s*$"
                r".*?"
                r"(?=^=== \S+ ===\s*$|\Z)"
            )
            party_content, count = re.subn(section_pattern, "", party_content,
                                           flags=re.MULTILINE | re.DOTALL)
        else:
            # Remove from trainers.h
            block_pattern = (
                r"\n?\s*\[" + re.escape(trainer_const) + r"\]\s*=\s*\n\s*\{"
                r".*?"
                r"\n\s*\},"
            )
            trainers_h_content, _ = re.subn(block_pattern, "",
                                             trainers_h_content, flags=re.DOTALL)

            # Remove from trainer_parties.h (need party const name)
            # The party const is typically sParty_<suffix>
            # Extract it from the trainers.h block before removal... but we already
            # removed it. For bulk removal, we'll match by pattern.
            # Party arrays are: static const struct TrainerMon sParty_*[] = {...};

        removed += 1

    # Write back modified files
    if os.path.exists(opponents_path):
        # Clean up double blank lines
        opponents_content = re.sub(r"\n{3,}", "\n\n", opponents_content)
        with open(opponents_path, "w", encoding="utf-8") as f:
            f.write(opponents_content)

    if fmt == "party" and os.path.exists(party_path):
        party_content = re.sub(r"\n{3,}", "\n\n", party_content)
        with open(party_path, "w", encoding="utf-8") as f:
            f.write(party_content)

    if fmt == "legacy":
        if os.path.exists(trainers_h_path):
            with open(trainers_h_path, "w", encoding="utf-8") as f:
                f.write(trainers_h_content)
        if os.path.exists(trainer_parties_path):
            with open(trainer_parties_path, "w", encoding="utf-8") as f:
                f.write(trainer_parties_content)

    return removed, errors


# ============================================================
# ENCOUNTER REMOVAL
# ============================================================

def remove_encounters(game_path, items):
    """Remove vanilla encounter entries from wild_encounters.json.

    Returns (removed_count, errors_list).
    """
    data = load_wild_encounters(game_path)
    if not data:
        return 0, ["wild_encounters.json not found or empty"]
    data = copy.deepcopy(data)

    # Build set of map constants to remove and count items
    remove_maps = set()
    item_count = 0
    for item in items:
        if item.status != SAFE or item.category != "encounters":
            continue
        map_const = item.data.get("map_const", "")
        if map_const:
            remove_maps.add(map_const)
        item_count += 1

    modified = False
    groups = data.get("wild_encounter_groups", [])
    for group in groups:
        encounters = group.get("encounters", [])
        original_len = len(encounters)
        group["encounters"] = [
            enc for enc in encounters
            if enc.get("map") not in remove_maps
        ]
        if len(group["encounters"]) < original_len:
            modified = True

    if modified:
        enc_path = os.path.join(game_path, "src", "data", "wild_encounters.json")
        try:
            with open(enc_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            clear_project_cache()
        except Exception as e:
            return item_count, [f"Failed to write wild_encounters.json: {e}"]

    return item_count, []


# ============================================================
# FRONTIER REMOVAL
# ============================================================

def remove_frontier(game_path, items):
    """Remove Battle Frontier system.

    Removes frontier map directories, data directory, and updates
    map_groups.json. Returns (removed_count, errors_list).
    """
    removed = 0
    errors = []
    removed_map_names = []

    for item in items:
        if item.status != SAFE or item.category != "frontier":
            continue

        info = item.data

        # Remove frontier maps
        for map_name in info.get("frontier_maps", []):
            map_dir = os.path.join(game_path, "data", "maps", map_name)
            if os.path.isdir(map_dir):
                try:
                    shutil.rmtree(map_dir)
                    removed += 1
                    removed_map_names.append(map_name)
                except OSError as e:
                    errors.append(f"Frontier map removal failed: {map_name}: {e}")
            elif not os.path.exists(map_dir):
                removed += 1
                removed_map_names.append(map_name)
            _remove_map_from_groups_json(game_path, map_name)

        # Remove frontier data directory
        data_dir = info.get("frontier_data_dir")
        if data_dir and os.path.isdir(data_dir):
            try:
                n_files = sum(len(files) for _, _, files in os.walk(data_dir))
                shutil.rmtree(data_dir)
                removed += n_files
            except OSError as e:
                errors.append(f"Frontier data dir removal failed: {e}")

    # Clean up event_scripts.s and layouts.json for removed maps
    if removed_map_names:
        _remove_maps_from_event_scripts(game_path, removed_map_names, errors)
        _remove_orphaned_layouts(game_path, errors)

    return removed, errors


# ============================================================
# SCRIPT REMOVAL
# ============================================================

def remove_scripts(game_path, items):
    """Remove shared script files (.inc and .pory) and update event_scripts.s.

    Only removes files where all labels are unreferenced by custom content.
    Returns (removed_count, errors_list).
    """
    removed = 0
    errors = []
    removed_inc_paths = []  # relative paths for event_scripts.s cleanup

    for item in items:
        if item.status != SAFE or item.category != "scripts":
            continue
        fpath = item.data.get("path", "")
        if not fpath:
            continue

        ok = True
        # Remove the .inc file
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError as e:
                errors.append(f"Script removal failed: {item.name}: {e}")
                ok = False

        # Also remove the .pory source if it exists (build would regenerate .inc from it)
        pory_path = fpath.replace(".inc", ".pory")
        if pory_path != fpath and os.path.exists(pory_path):
            try:
                os.remove(pory_path)
            except OSError as e:
                errors.append(f"Pory removal failed: {item.name}: {e}")

        if ok:
            removed += 1
            rel_inc = os.path.relpath(fpath, game_path)
            removed_inc_paths.append(rel_inc)

    # Remove .include lines from assembly files that reference deleted scripts
    if removed_inc_paths:
        asm_files = [
            os.path.join(game_path, "data", "event_scripts.s"),
            os.path.join(game_path, "data", "mystery_gift.s"),
        ]
        remove_set = set(removed_inc_paths)
        for asm_path in asm_files:
            if not os.path.isfile(asm_path):
                continue
            try:
                with open(asm_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                new_lines = [l for l in lines
                             if not any(p in l for p in remove_set)]
                if len(new_lines) < len(lines):
                    with open(asm_path, "w", encoding="utf-8") as f:
                        f.writelines(new_lines)
            except OSError as e:
                errors.append(f"{os.path.basename(asm_path)} update failed: {e}")

    return removed, errors


# ============================================================
# TILESET REMOVAL
# ============================================================

def _tileset_dir_to_symbol(dir_name):
    """Convert a tileset directory name to its PascalCase C symbol suffix.

    e.g. 'bike_shop' -> 'BikeShop', 'battle_frontier_outside_east' -> 'BattleFrontierOutsideEast'

    Falls back to naive capitalization-split if the exact form can't be looked up.
    """
    return "".join(part.capitalize() for part in dir_name.split("_"))


def _lookup_tileset_symbol(graphics_path, dir_name):
    """Look up the actual C symbol suffix for a tileset by scanning graphics.h.

    Finds a line matching 'gTilesetTiles_<Name>[] = INCBIN_U32(".../<dir_name>/...'
    and extracts <Name>. Returns the symbol string, or the naive conversion as fallback.
    """
    path_marker = f"data/tilesets/secondary/{dir_name}/"
    fallback = _tileset_dir_to_symbol(dir_name)
    try:
        with open(graphics_path, "r", encoding="utf-8") as f:
            for line in f:
                if "gTilesetTiles_" in line and path_marker in line:
                    m = re.search(r"gTilesetTiles_(\w+)\[\]", line)
                    if m:
                        return m.group(1)
    except OSError:
        pass
    return fallback


def _lookup_all_tileset_symbols(graphics_path, dir_name):
    """Find ALL C symbol suffixes for a tileset directory in graphics.h.

    Some tilesets (e.g. secret_base) have multiple sub-variants with different
    symbol names but a shared directory. Returns a set of all unique symbol
    suffixes found, or {naive_conversion} as fallback.
    """
    path_marker = f"data/tilesets/secondary/{dir_name}/"
    symbols = set()
    try:
        with open(graphics_path, "r", encoding="utf-8") as f:
            for line in f:
                if path_marker not in line:
                    continue
                # Extract symbol from gTilesetTiles_<Name>[] or gTilesetPalettes_<Name>[]
                for m in re.finditer(r"gTileset(?:Tiles|Palettes)_(\w+?)(?:Compressed)?\[", line):
                    symbols.add(m.group(1))
    except OSError:
        pass
    if not symbols:
        symbols.add(_tileset_dir_to_symbol(dir_name))
    return symbols


def _remove_tileset_from_graphics_h(graphics_path, symbol_name, dir_name):
    """Remove all INCBIN entries and palette arrays for a tileset from graphics.h.

    Uses a multi-pass approach:
    1. Collect ALL symbol suffixes for this directory (handles multi-variant
       tilesets like secret_base with sub-variants).
    2. Remove all gTilesetTiles_<Name>[] lines for any matching symbol.
    3. Remove all gTilesetPalettes_<Name>[][16] blocks (declaration + data + };).
    4. Remove any remaining path-based lines referencing secondary/<dir_name>/.

    Returns True if anything was removed, False if nothing found.
    """
    try:
        with open(graphics_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Collect ALL symbol suffixes for this tileset directory
    all_symbols = _lookup_all_tileset_symbols(graphics_path, dir_name)
    all_symbols.add(symbol_name)  # ensure the primary symbol is included

    # Build marker sets — use regex patterns with word boundaries to prevent
    # substring collisions (e.g. PetalburgLeoB matching PetalburgLeoBSnow)
    tiles_pats = [re.compile(rf"\bgTilesetTiles_{re.escape(s)}(?:Compressed)?\b") for s in all_symbols]
    palettes_pats = [re.compile(rf"\bgTilesetPalettes_{re.escape(s)}\b") for s in all_symbols]
    path_marker = f"data/tilesets/secondary/{dir_name}/"

    original_count = len(lines)

    # First pass: remove symbol-based blocks
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if this line declares a tiles array for any matching symbol
        if any(p.search(line) for p in tiles_pats):
            i += 1
            continue

        # Check if this line starts a palettes array for any matching symbol
        if any(p.search(line) for p in palettes_pats):
            # This starts a palettes array — consume until "};"
            i += 1
            if i < len(lines) and lines[i].strip() == "{":
                while i < len(lines):
                    if lines[i].strip() == "};":
                        i += 1
                        break
                    i += 1
            continue

        new_lines.append(line)
        i += 1

    # Second pass: remove any remaining path-based lines (handles edge cases)
    cleaned = []
    skip_closing = False
    for line in new_lines:
        if path_marker in line:
            skip_closing = True
            continue
        if skip_closing and line.strip() == "};":
            skip_closing = False
            continue
        cleaned.append(line)

    # Third pass: collapse 3+ consecutive blank lines to 2
    final = []
    blank_run = 0
    for line in cleaned:
        if line.strip() == "":
            blank_run += 1
            if blank_run <= 2:
                final.append(line)
        else:
            blank_run = 0
            final.append(line)

    if len(final) == original_count:
        return False  # nothing removed

    try:
        with open(graphics_path, "w", encoding="utf-8") as f:
            f.writelines(final)
        return True
    except OSError:
        return False


def _remove_tileset_from_metatiles_h(metatiles_path, symbol_name, dir_name=None,
                                     all_symbols=None):
    """Remove metatile INCBIN lines for a tileset from metatiles.h.

    Uses symbol-based removal (gMetatiles_<Name>[] / gMetatileAttributes_<Name>[])
    for all matching symbols, plus path-based fallback for any remaining refs.
    Returns True if anything was removed, False if not found.
    """
    try:
        with open(metatiles_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False

    symbols = {symbol_name}
    if all_symbols:
        symbols.update(all_symbols)

    meta_pats = [re.compile(rf"\bgMetatiles_{re.escape(s)}\b") for s in symbols]
    attr_pats = [re.compile(rf"\bgMetatileAttributes_{re.escape(s)}\b") for s in symbols]
    path_marker = f"data/tilesets/secondary/{dir_name}/" if dir_name else None

    new_lines = []
    removed = False
    for line in lines:
        if any(p.search(line) for p in meta_pats) or any(p.search(line) for p in attr_pats):
            removed = True
            continue
        if path_marker and path_marker in line:
            removed = True
            continue
        new_lines.append(line)

    if not removed:
        return False

    try:
        with open(metatiles_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True
    except OSError:
        return False


def _remove_tileset_from_headers_h(headers_path, symbol_name):
    """Remove the 'const struct Tileset gTileset_<Name>' block from headers.h.

    Removes from the struct declaration line through its closing '};'.
    Returns True on success, False if not found.
    """
    try:
        with open(headers_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False

    struct_marker = f"gTileset_{symbol_name} ="

    start_idx = None
    for i, line in enumerate(lines):
        if struct_marker in line:
            start_idx = i
            while start_idx > 0 and lines[start_idx - 1].strip() == "":
                start_idx -= 1
            break

    if start_idx is None:
        return False

    # Find closing "};"
    end_idx = None
    for i in range(start_idx, len(lines)):
        if lines[i].strip() == "};":
            end_idx = i
            break

    if end_idx is None:
        return False

    new_lines = lines[:start_idx] + lines[end_idx + 1:]

    try:
        with open(headers_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True
    except OSError:
        return False


def _remove_orphaned_headers(headers_path, graphics_path):
    """Remove struct Tileset entries from headers.h whose .tiles symbol no longer exists in graphics.h.

    This handles tilesets with non-standard symbol naming (e.g. secret_base variants)
    where the struct name doesn't match the directory name. Any struct whose
    '.tiles = gTilesetTiles_X' value is missing from graphics.h gets removed.

    Returns count of structs removed.
    """
    import re

    # Build set of defined gTilesetTiles_ symbols from current graphics.h
    defined_symbols = set()
    try:
        with open(graphics_path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.search(r"gTilesetTiles_(\w+)\[\]", line)
                if m:
                    defined_symbols.add(m.group(1))
    except OSError:
        return 0

    # Parse headers.h and find structs referencing undefined symbols
    try:
        with open(headers_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return 0

    removed_count = 0
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect struct start
        if re.match(r"\s*const struct Tileset gTileset_\w+\s*=", line):
            # Scan ahead to find the .tiles field
            struct_start = i
            while struct_start > 0 and lines[struct_start - 1].strip() == "":
                struct_start -= 1

            # Find .tiles = gTilesetTiles_<Name> and .isSecondary
            tiles_symbol = None
            is_secondary = False
            end_idx = i
            for j in range(i, min(i + 20, len(lines))):
                m = re.search(r"\.tiles\s*=\s*(gTilesetTiles_\w+)", lines[j])
                if m:
                    tiles_symbol = m.group(1).replace("gTilesetTiles_", "")
                if ".isSecondary = TRUE" in lines[j]:
                    is_secondary = True
                if lines[j].strip() == "};":
                    end_idx = j
                    break

            if tiles_symbol and is_secondary and tiles_symbol not in defined_symbols:
                # Symbol is gone from graphics.h — remove this struct
                # Remove the struct block (from struct_start to end_idx inclusive)
                # Back out any blank lines we already added
                while new_lines and new_lines[-1].strip() == "":
                    new_lines.pop()
                removed_count += 1
                i = end_idx + 1
                continue

        new_lines.append(line)
        i += 1

    # Also remove gTilesetPointer_* lines referencing removed structs
    # Pattern: const struct Tileset * const gTilesetPointer_X = &gTileset_X;
    if removed_count > 0:
        # Build set of remaining gTileset_ struct names
        remaining_structs = set()
        for line in new_lines:
            m = re.match(r"\s*const struct Tileset gTileset_(\w+)\s*=", line)
            if m:
                remaining_structs.add(m.group(1))

        cleaned = []
        for line in new_lines:
            m = re.match(r"\s*const struct Tileset \*\s*const gTilesetPointer_\w+\s*=\s*&gTileset_(\w+)\s*;", line)
            if m and m.group(1) not in remaining_structs:
                removed_count += 1
                continue
            cleaned.append(line)
        new_lines = cleaned

    if removed_count > 0:
        try:
            with open(headers_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except OSError:
            return 0

    return removed_count


def _remove_tileset_path_lines(file_path, dir_name):
    """Remove any lines containing 'data/tilesets/secondary/<dir_name>/' from a file.

    Used for overrides.h and any other managed files with simple per-line INCBIN refs.
    Returns True if anything was removed.
    """
    path_marker = f"data/tilesets/secondary/{dir_name}/"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False

    new_lines = [l for l in lines if path_marker not in l]
    if len(new_lines) == len(lines):
        return False

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True
    except OSError:
        return False


def _remove_orphaned_overrides(overrides_path, graphics_path):
    """Remove override entries from overrides.h whose tileset struct is gone.

    Removes both static INCBIN lines (sTilesetPalOverride_*) and struct blocks
    (gTilesetPalOverrides_*) when the referenced tileset struct no longer
    exists in headers.h. Uses headers.h (not graphics.h) because primary
    tileset palettes are defined in src/graphics.c, not graphics.h.

    Returns count of blocks removed.
    """
    # Build set of remaining gTileset_ struct names from headers.h
    # This covers both primary and secondary tilesets
    headers_path = os.path.join(os.path.dirname(graphics_path), "headers.h")
    palette_symbols = set()
    try:
        with open(headers_path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*const struct Tileset gTileset_(\w+)\s*=", line)
                if m:
                    palette_symbols.add(m.group(1))
    except OSError:
        return 0

    try:
        with open(overrides_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return 0

    removed_count = 0
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for static INCBIN lines: sTilesetPalOverride_<Name>*
        m = re.match(r"\s*static\s+const\s+u16\s+sTilesetPalOverride_(\w+?)\d", line)
        if m:
            name_prefix = m.group(1)
            if name_prefix not in palette_symbols:
                removed_count += 1
                i += 1
                continue

        # Check for struct blocks: gTilesetPalOverrides_<Name>[]
        m = re.match(r"\s*const struct PaletteOverride gTilesetPalOverrides_(\w+)\[\]", line)
        if m:
            name = m.group(1)
            if name not in palette_symbols:
                # Consume until closing "};"
                while i < len(lines):
                    if lines[i].strip() == "};":
                        i += 1
                        removed_count += 1
                        break
                    i += 1
                continue

        new_lines.append(line)
        i += 1

    if removed_count > 0:
        try:
            with open(overrides_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except OSError:
            return 0

    return removed_count


def remove_tilesets(game_path, items):
    """Remove tileset directories and their C source entries.

    Updates graphics.h, metatiles.h, headers.h, and overrides.h in addition
    to deleting the tileset directory. Returns (removed_count, errors_list).
    """
    removed = 0
    errors = []

    ts_data_dir = os.path.join(game_path, "src", "data", "tilesets")
    graphics_path = os.path.join(ts_data_dir, "graphics.h")
    metatiles_path = os.path.join(ts_data_dir, "metatiles.h")
    headers_path = os.path.join(ts_data_dir, "headers.h")
    overrides_path = os.path.join(ts_data_dir, "overrides.h")

    for item in items:
        if item.status != SAFE or item.category != "tilesets":
            continue

        dir_name = item.name  # e.g. 'bike_shop'
        # Look up ALL symbol names for this tileset (handles multi-variant dirs)
        all_symbols = _lookup_all_tileset_symbols(graphics_path, dir_name)
        symbol_name = _lookup_tileset_symbol(graphics_path, dir_name)

        ts_path = item.data.get("path", "")
        dir_ok = True
        if ts_path and os.path.isdir(ts_path):
            try:
                shutil.rmtree(ts_path)
            except OSError as e:
                errors.append(f"Tileset dir removal failed: {dir_name}: {e}")
                dir_ok = False

        if not dir_ok:
            continue

        # Update managed C source files
        if os.path.isfile(graphics_path):
            if not _remove_tileset_from_graphics_h(graphics_path, symbol_name, dir_name):
                errors.append(f"graphics.h entry not found for: {dir_name}")
        if os.path.isfile(metatiles_path):
            _remove_tileset_from_metatiles_h(metatiles_path, symbol_name, dir_name,
                                             all_symbols=all_symbols)
        if os.path.isfile(headers_path):
            if not _remove_tileset_from_headers_h(headers_path, symbol_name):
                # Symbol-based removal failed (non-standard naming) — will be
                # caught by the orphaned-headers pass below
                pass
        if os.path.isfile(overrides_path):
            _remove_tileset_path_lines(overrides_path, dir_name)

        removed += 1

    # Final pass: remove orphaned entries whose tileset data is now gone
    if os.path.isfile(headers_path) and os.path.isfile(graphics_path):
        _remove_orphaned_headers(headers_path, graphics_path)
    if os.path.isfile(overrides_path) and os.path.isfile(graphics_path):
        _remove_orphaned_overrides(overrides_path, graphics_path)

    return removed, errors


# ============================================================
# DISPATCHER
# ============================================================

def execute_removal(game_path, plan, category_id=None):
    """Execute removal for all SAFE items in the plan (or just one category).

    Returns dict: {category_id: (removed_count, errors)}
    """
    results = {}

    if category_id:
        items = plan.by_category(category_id)
    else:
        items = plan.items

    safe_items = [i for i in items if i.status == SAFE]
    if not safe_items:
        return results

    # Group by category
    by_cat = {}
    for item in safe_items:
        by_cat.setdefault(item.category, []).append(item)

    removers = {
        "maps":       remove_maps,
        "trainers":   remove_trainers,
        "encounters": remove_encounters,
        "frontier":   remove_frontier,
        "scripts":    remove_scripts,
        "tilesets":   remove_tilesets,
    }

    for cat_id, cat_items in by_cat.items():
        remover = removers.get(cat_id)
        if remover:
            result = remover(game_path, cat_items)
            results[cat_id] = result
        else:
            # Category scanned but removal not yet implemented
            results[cat_id] = (0, [f"Removal not yet implemented for {cat_id}"])

    return results
