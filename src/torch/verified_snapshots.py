"""Verified Build Snapshots — auto-snapshot game files after successful builds."""
# TORCH_MODULE: Verified Build Snapshots
# TORCH_GROUP: Tools

import os
import zipfile
import json
from datetime import datetime

from torch import VERSION
from torch.colours import DGOLD, DIM, RST

# ============================================================
# CONSTANTS
# ============================================================

SNAPSHOT_DIRS = ["data/maps", "data/layouts", "src/data", "include/constants"]
SNAPSHOT_FILES = ["data/event_scripts.s"]
METADATA_FILENAME = "_torch_metadata.json"
VERIFIED_BACKUP_DIR_NAME = "verified"


# ============================================================
# HELPERS
# ============================================================

def _get_verified_backup_dir(game_path):
    """Return the verified backup directory path, creating it if needed."""
    backup_dir = os.path.join(game_path, "backups", VERIFIED_BACKUP_DIR_NAME)
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def _format_size_mb(byte_count):
    """Format a byte count as MB with one decimal."""
    return byte_count / (1024 * 1024)


# ============================================================
# SNAPSHOT CREATION
# ============================================================

def create_verified_snapshot(game_path, trigger="manual", max_count=3):
    """Create a verified build snapshot of all TORCH-managed game files.

    Walks SNAPSHOT_DIRS and SNAPSHOT_FILES, creates a ZIP in
    <game_path>/backups/verified/ with metadata.

    Returns snapshot path on success, None on error.
    Never raises — all errors are caught and printed as warnings.
    """
    try:
        backup_dir = _get_verified_backup_dir(game_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_name = f"verified_{timestamp}.zip"
        snapshot_path = os.path.join(backup_dir, snapshot_name)

        # Collect all files as relative paths
        files_to_backup = []

        for snap_dir in SNAPSHOT_DIRS:
            abs_dir = os.path.join(game_path, snap_dir)
            if os.path.isdir(abs_dir):
                for root, dirs, files in os.walk(abs_dir):
                    for f in files:
                        abs_path = os.path.join(root, f)
                        rel_path = os.path.relpath(abs_path, game_path)
                        files_to_backup.append(rel_path)

        for snap_file in SNAPSHOT_FILES:
            abs_path = os.path.join(game_path, snap_file)
            if os.path.isfile(abs_path):
                files_to_backup.append(snap_file)

        files_to_backup.sort()

        # Build metadata
        metadata = {
            "torch_version": VERSION,
            "timestamp": datetime.now().isoformat(),
            "trigger": trigger,
            "file_count": len(files_to_backup),
            "dirs_included": list(SNAPSHOT_DIRS),
        }

        # Create ZIP
        with zipfile.ZipFile(snapshot_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path in files_to_backup:
                abs_path = os.path.join(game_path, rel_path)
                if os.path.exists(abs_path):
                    zf.write(abs_path, rel_path)
            # Write metadata into the ZIP
            zf.writestr(METADATA_FILENAME, json.dumps(metadata, indent=2))

        # Prune old snapshots
        pruned = prune_verified_snapshots(game_path, max_count=max_count)

        # Status line
        size_bytes = os.path.getsize(snapshot_path)
        size_mb = _format_size_mb(size_bytes)
        # Count retained snapshots
        retained = len([
            f for f in os.listdir(backup_dir)
            if f.startswith("verified_") and f.endswith(".zip")
        ])
        print(f"  Verified snapshot saved: {snapshot_name} "
              f"({size_mb:.1f} MB, {retained} retained)")

        return snapshot_path

    except Exception as e:
        print(f"  Warning: Could not create verified snapshot: {e}")
        return None


# ============================================================
# PRUNING
# ============================================================

def prune_verified_snapshots(game_path, max_count=3):
    """Keep only the newest max_count verified snapshots.

    Returns the number of snapshots deleted.
    """
    backup_dir = os.path.join(game_path, "backups", VERIFIED_BACKUP_DIR_NAME)
    if not os.path.isdir(backup_dir):
        return 0

    zips = sorted([
        f for f in os.listdir(backup_dir)
        if f.startswith("verified_") and f.endswith(".zip")
    ])

    if len(zips) <= max_count:
        return 0

    to_delete = zips[:len(zips) - max_count]
    deleted = 0
    for fname in to_delete:
        try:
            os.remove(os.path.join(backup_dir, fname))
            deleted += 1
        except OSError:
            pass

    return deleted


# ============================================================
# LISTING
# ============================================================

def list_verified_snapshots(game_path):
    """List all verified snapshots, newest first.

    Returns a list of dicts:
        {path, filename, timestamp, display_time, trigger, file_count, size_mb}
    Returns empty list if directory doesn't exist or has no snapshots.
    """
    backup_dir = os.path.join(game_path, "backups", VERIFIED_BACKUP_DIR_NAME)
    if not os.path.isdir(backup_dir):
        return []

    zips = sorted([
        f for f in os.listdir(backup_dir)
        if f.startswith("verified_") and f.endswith(".zip")
    ], reverse=True)

    result = []
    for fname in zips:
        fpath = os.path.join(backup_dir, fname)

        # Parse timestamp from filename: verified_YYYYMMDD_HHMMSS.zip
        ts_raw = fname[len("verified_"):-len(".zip")]
        try:
            dt = datetime.strptime(ts_raw, "%Y%m%d_%H%M%S")
            display_time = dt.strftime("%Y-%m-%d %H:%M")
            timestamp = dt.isoformat()
        except ValueError:
            display_time = ts_raw
            timestamp = ts_raw

        # Read metadata from ZIP if present
        trigger = "unknown"
        file_count = 0
        try:
            with zipfile.ZipFile(fpath, "r") as zf:
                if METADATA_FILENAME in zf.namelist():
                    meta_raw = zf.read(METADATA_FILENAME)
                    meta = json.loads(meta_raw)
                    trigger = meta.get("trigger", "unknown")
                    file_count = meta.get("file_count", 0)
                else:
                    # Count files excluding metadata
                    file_count = len(zf.namelist())
        except (zipfile.BadZipFile, json.JSONDecodeError, OSError):
            pass

        # File size
        try:
            size_bytes = os.path.getsize(fpath)
        except OSError:
            size_bytes = 0

        result.append({
            "path": fpath,
            "filename": fname,
            "timestamp": timestamp,
            "display_time": display_time,
            "trigger": trigger,
            "file_count": file_count,
            "size_mb": _format_size_mb(size_bytes),
        })

    return result


# ============================================================
# RESTORE
# ============================================================

def restore_verified_snapshot(game_path, snapshot_path):
    """Restore all files from a verified build snapshot ZIP.

    Checks for files modified since the snapshot was taken and warns
    before overwriting them.  Skips _torch_metadata.json (internal).

    Returns list of restored relative paths on success,
    empty list if user declined, or None on error.
    """
    if not os.path.isfile(snapshot_path):
        print(f"  ERROR: Snapshot not found: {snapshot_path}")
        return None

    try:
        # Pre-extract check: find files modified since the snapshot
        modified = []
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for member in zf.namelist():
                if member == METADATA_FILENAME:
                    continue
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

        # Extract all files (skip metadata)
        restored = []
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for member in zf.namelist():
                if member == METADATA_FILENAME:
                    continue
                target = os.path.join(game_path, member)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                restored.append(member)
        return restored

    except Exception as e:
        print(f"  ERROR during verified snapshot restore: {e}")
        return None


# ============================================================
# PER-MAP UTILITIES
# ============================================================

def list_maps_in_snapshot(snapshot_path):
    """Return sorted unique map names found in a verified snapshot ZIP.

    Scans for data/maps/<MapName>/<file> paths in the namelist.
    Only includes entries that are inside a subdirectory (not loose files
    like .gitignore sitting directly in data/maps/).
    Pure read — no extraction.  Returns empty list on error.
    """
    try:
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            maps = set()
            for name in zf.namelist():
                if name.startswith("data/maps/"):
                    remainder = name[len("data/maps/"):]
                    parts = remainder.split("/", 1)
                    # Must have a subdirectory component (MapName/something)
                    if len(parts) == 2 and parts[0] and parts[1]:
                        maps.add(parts[0])
            return sorted(maps)
    except (zipfile.BadZipFile, OSError):
        return []


def preview_map_in_snapshot(game_path, snapshot_path, map_name):
    """Preview what restoring a map from a snapshot would do.

    Returns a dict with:
        total_files  — number of files in the snapshot for this map
        modified     — list of relative paths that differ from current disk
        missing      — list of relative paths not currently on disk (would be added)
        unchanged    — count of files identical to disk
    Returns None on error.
    """
    if not os.path.isfile(snapshot_path):
        return None

    prefixes = (f"data/maps/{map_name}/", f"data/layouts/{map_name}/")

    try:
        members = []
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for name in zf.namelist():
                if name == METADATA_FILENAME:
                    continue
                if any(name.startswith(p) for p in prefixes):
                    members.append(name)

        if not members:
            return None

        modified = []
        missing = []
        unchanged = 0
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for member in members:
                target = os.path.join(game_path, member)
                if not os.path.exists(target):
                    missing.append(member)
                    continue
                snap_data = zf.read(member)
                try:
                    with open(target, "rb") as f:
                        disk_data = f.read()
                except OSError:
                    modified.append(member)
                    continue
                if disk_data != snap_data:
                    modified.append(member)
                else:
                    unchanged += 1

        return {
            "total_files": len(members),
            "modified": modified,
            "missing": missing,
            "unchanged": unchanged,
        }
    except (zipfile.BadZipFile, OSError):
        return None


def restore_map_from_verified(game_path, snapshot_path, map_name):
    """Restore only a single map from a verified build snapshot.

    Extracts data/maps/{map_name}/ and data/layouts/{map_name}/ from the ZIP.
    Does NOT restore src/data/ or include/constants/ (shared across maps).

    Same modification-warning logic as restore_verified_snapshot().

    Returns list of restored relative paths on success,
    empty list if user declined, or None on error.
    """
    if not os.path.isfile(snapshot_path):
        print(f"  ERROR: Snapshot not found: {snapshot_path}")
        return None

    prefixes = (f"data/maps/{map_name}/", f"data/layouts/{map_name}/")

    try:
        # Collect matching members
        members = []
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for name in zf.namelist():
                if name == METADATA_FILENAME:
                    continue
                if any(name.startswith(p) for p in prefixes):
                    members.append(name)

        if not members:
            print(f"  Map '{map_name}' not found in this snapshot.")
            return None

        # Pre-extract check: find files modified since the snapshot
        modified = []
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for member in members:
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

        # Extract matching files
        restored = []
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for member in members:
                target = os.path.join(game_path, member)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                restored.append(member)
        return restored

    except Exception as e:
        print(f"  ERROR during per-map restore: {e}")
        return None
