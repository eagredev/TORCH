"""Game Version Control — manual versioning for ROM hack projects."""
# TORCH_MODULE: Game Version Control
# TORCH_GROUP: Tools

import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime

from torch import VERSION
from torch.colours import BAR, CYAN, DIM, DGOLD, GOLD, GREEN, RED, RST, WHITE
from torch.verified_snapshots import SNAPSHOT_DIRS, SNAPSHOT_FILES

# ============================================================
# CONSTANTS
# ============================================================

VERSION_DIR = "versions"
MANIFEST_FILE = "versions.json"
METADATA_FILE = "_version_metadata.json"
ROM_PREFIX = "_rom"
WORKSPACE_PREFIX = "_workspace"
WORKSPACE_EXCLUDE = {"backups", "__pycache__", ".git"}

_DEFAULT_MANIFEST = {
    "schema_version": 1,
    "next_major": 0,
    "next_minor": 1,
    "versions": [],
}


# ============================================================
# HELPERS
# ============================================================

def _get_version_dir(game_path):
    """Return <game_path>/backups/versions/, creating if needed."""
    d = os.path.join(game_path, "backups", VERSION_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _load_manifest(game_path):
    """Load versions.json manifest. Returns default structure if missing/corrupt."""
    version_dir = os.path.join(game_path, "backups", VERSION_DIR)
    path = os.path.join(version_dir, MANIFEST_FILE)
    if not os.path.isfile(path):
        return dict(_DEFAULT_MANIFEST, versions=[])
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "versions" not in data:
            return dict(_DEFAULT_MANIFEST, versions=[])
        return data
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_MANIFEST, versions=[])


def _save_manifest(game_path, manifest):
    """Write versions.json manifest atomically."""
    version_dir = _get_version_dir(game_path)
    target = os.path.join(version_dir, MANIFEST_FILE)
    fd, tmp = tempfile.mkstemp(dir=version_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _slugify(label):
    """Convert label to filename-safe slug: lowercase, alphanum+hyphens only."""
    if not label:
        return "unnamed"
    slug = label.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug or "unnamed"


def _next_version(manifest):
    """Return (version_str, major, minor) for the next version."""
    major = manifest.get("next_major", 0)
    minor = manifest.get("next_minor", 1)
    return f"{major}.{minor}", major, minor


def _find_rom(game_path):
    """Find the most recently modified .gba file in game_path. Returns path or None."""
    best_path = None
    best_mtime = 0
    try:
        for entry in os.listdir(game_path):
            if entry.endswith(".gba"):
                fpath = os.path.join(game_path, entry)
                try:
                    mt = os.path.getmtime(fpath)
                    if mt > best_mtime:
                        best_mtime = mt
                        best_path = fpath
                except OSError:
                    pass
    except OSError:
        pass
    return best_path


def _format_size_mb(byte_count):
    """Format a byte count as MB with one decimal."""
    return byte_count / (1024 * 1024)


def _collect_game_files(game_path):
    """Collect game source files as relative paths (same dirs as verified snapshots)."""
    files = []
    for snap_dir in SNAPSHOT_DIRS:
        abs_dir = os.path.join(game_path, snap_dir)
        if os.path.isdir(abs_dir):
            for root, _dirs, fnames in os.walk(abs_dir):
                for f in fnames:
                    abs_path = os.path.join(root, f)
                    rel_path = os.path.relpath(abs_path, game_path)
                    files.append(rel_path)
    for snap_file in SNAPSHOT_FILES:
        abs_path = os.path.join(game_path, snap_file)
        if os.path.isfile(abs_path):
            files.append(snap_file)
    files.sort()
    return files


def _collect_workspace_files(project_dir):
    """Collect workspace files as relative paths, excluding backups/__pycache__/.git."""
    files = []
    if not project_dir or not os.path.isdir(project_dir):
        return files
    for root, dirs, fnames in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in WORKSPACE_EXCLUDE]
        for f in fnames:
            abs_path = os.path.join(root, f)
            rel_path = os.path.relpath(abs_path, project_dir)
            files.append(rel_path)
    files.sort()
    return files


# ============================================================
# CORE OPERATIONS
# ============================================================

def create_version(game_path, project_dir, label="", notes=""):
    """Create a new game version snapshot.

    Includes game source files (SNAPSHOT_DIRS + SNAPSHOT_FILES), ROM binary,
    and TORCH workspace. Auto-increments minor version.

    Returns version entry dict on success, None on error.
    Never raises — all errors are caught and printed as warnings.
    """
    try:
        manifest = _load_manifest(game_path)
        version_str, major, minor = _next_version(manifest)
        slug = _slugify(label)
        filename = f"v{version_str}_{slug}.zip"
        version_dir = _get_version_dir(game_path)
        zip_path = os.path.join(version_dir, filename)

        # Pre-check: estimate size and verify disk space
        game_files = _collect_game_files(game_path)
        workspace_files = _collect_workspace_files(project_dir)
        rom_path = _find_rom(game_path)

        estimated_size = 0
        for rel in game_files:
            try:
                estimated_size += os.path.getsize(os.path.join(game_path, rel))
            except OSError:
                pass
        for rel in workspace_files:
            try:
                estimated_size += os.path.getsize(os.path.join(project_dir, rel))
            except OSError:
                pass
        if rom_path:
            try:
                estimated_size += os.path.getsize(rom_path)
            except OSError:
                pass

        try:
            disk = shutil.disk_usage(version_dir)
            if disk.free < estimated_size * 2:
                print(f"  WARNING: Low disk space. Need ~{_format_size_mb(estimated_size):.0f} MB, "
                      f"only {_format_size_mb(disk.free):.0f} MB free.")
                return None
        except OSError:
            pass

        # Detect expansion version
        expansion_version = ""
        try:
            from torch.expansion_compat import detect_expansion_version
            ev = detect_expansion_version(game_path)
            if ev:
                expansion_version = ".".join(str(x) for x in ev)
        except ImportError:
            pass

        # Build ZIP
        file_count = 0
        rom_filename = ""
        rom_size = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Game source files
            for rel in game_files:
                abs_path = os.path.join(game_path, rel)
                if os.path.exists(abs_path):
                    zf.write(abs_path, rel)
                    file_count += 1

            # ROM binary
            if rom_path and os.path.isfile(rom_path):
                rom_filename = os.path.basename(rom_path)
                rom_size = os.path.getsize(rom_path)
                zf.write(rom_path, f"{ROM_PREFIX}/{rom_filename}")
                file_count += 1

            # Workspace files
            workspace_included = bool(workspace_files)
            for rel in workspace_files:
                abs_path = os.path.join(project_dir, rel)
                if os.path.exists(abs_path):
                    zf.write(abs_path, f"{WORKSPACE_PREFIX}/{rel}")
                    file_count += 1

            # Metadata
            timestamp = datetime.now().isoformat()
            metadata = {
                "version": version_str,
                "label": label,
                "timestamp": timestamp,
                "torch_version": VERSION,
                "expansion_version": expansion_version,
                "file_count": file_count,
                "rom_filename": rom_filename,
                "rom_size_bytes": rom_size,
                "dirs_included": list(SNAPSHOT_DIRS),
                "workspace_included": workspace_included,
                "notes": notes,
            }
            zf.writestr(METADATA_FILE, json.dumps(metadata, indent=2))

        # Get actual ZIP size
        zip_size = os.path.getsize(zip_path)

        # Build manifest entry
        entry = {
            "version": version_str,
            "major": major,
            "minor": minor,
            "label": label,
            "slug": slug,
            "filename": filename,
            "timestamp": timestamp,
            "torch_version": VERSION,
            "expansion_version": expansion_version,
            "file_count": file_count,
            "rom_filename": rom_filename,
            "rom_size_bytes": rom_size,
            "size_bytes": zip_size,
            "notes": notes,
        }

        # Update manifest
        manifest["versions"].append(entry)
        manifest["next_minor"] = minor + 1
        _save_manifest(game_path, manifest)

        return entry

    except Exception as e:
        print(f"  ERROR: Could not create version: {e}")
        return None


def list_versions(game_path):
    """List all saved versions, newest first.

    Validates that ZIP files still exist on disk.
    Returns list of dicts with version info.
    """
    manifest = _load_manifest(game_path)
    version_dir = os.path.join(game_path, "backups", VERSION_DIR)
    result = []
    for entry in manifest.get("versions", []):
        zip_path = os.path.join(version_dir, entry["filename"])
        if os.path.isfile(zip_path):
            # Add display_time and size_mb for convenience
            try:
                dt = datetime.fromisoformat(entry["timestamp"])
                display_time = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, KeyError):
                display_time = entry.get("timestamp", "unknown")
            e = dict(entry)
            e["display_time"] = display_time
            e["size_mb"] = _format_size_mb(entry.get("size_bytes", 0))
            e["path"] = zip_path
            result.append(e)
    # Newest first (sort by version descending)
    result.sort(key=lambda e: (e.get("major", 0), e.get("minor", 0)), reverse=True)
    return result


def get_version_info(game_path, version_str):
    """Get detailed info about a specific version. Returns dict or None."""
    for entry in list_versions(game_path):
        if entry["version"] == version_str:
            return entry
    return None


def restore_version(game_path, project_dir, version_str,
                    restore_game=True, restore_rom=True, restore_workspace=True):
    """Restore files from a version snapshot.

    Supports partial restore via boolean flags.
    Returns True on success, False on error or cancellation.
    """
    info = get_version_info(game_path, version_str)
    if not info:
        print(f"  Version {version_str} not found.")
        return False

    zip_path = info["path"]
    if not os.path.isfile(zip_path):
        print(f"  ZIP not found: {info['filename']}")
        return False

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.namelist()

            # Categorise members
            game_members = []
            rom_members = []
            workspace_members = []
            for m in members:
                if m == METADATA_FILE:
                    continue
                if m.startswith(f"{ROM_PREFIX}/"):
                    rom_members.append(m)
                elif m.startswith(f"{WORKSPACE_PREFIX}/"):
                    workspace_members.append(m)
                else:
                    game_members.append(m)

            # Build restore list based on flags
            to_restore = []
            if restore_game:
                to_restore.extend(game_members)
            if restore_rom:
                to_restore.extend(rom_members)
            if restore_workspace:
                to_restore.extend(workspace_members)

            if not to_restore:
                print("  Nothing selected to restore.")
                return False

            # Check for modified files (game files only)
            modified = []
            if restore_game:
                for m in game_members:
                    target = os.path.join(game_path, m)
                    if not os.path.exists(target):
                        continue
                    snap_data = zf.read(m)
                    try:
                        with open(target, "rb") as f:
                            if f.read() != snap_data:
                                modified.append(m)
                    except OSError:
                        continue

            # Warn about modifications
            if modified:
                print(f"\n  {DGOLD}WARNING:{RST} {len(modified)} file(s) have been "
                      f"modified since this version was saved:")
                for rel in modified[:10]:
                    print(f"    {DIM}{rel}{RST}")
                if len(modified) > 10:
                    print(f"    {DIM}...and {len(modified) - 10} more{RST}")
                print()

            # Summary
            parts = []
            if restore_game:
                parts.append(f"{len(game_members)} game files")
            if restore_rom and rom_members:
                parts.append("ROM binary")
            if restore_workspace:
                parts.append(f"{len(workspace_members)} workspace files")
            print(f"  Will restore: {', '.join(parts)}")

            try:
                proceed = input("  Proceed? [y/N] > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return False
            if proceed != "y":
                print("  Restore cancelled.")
                return False

            # Extract
            restored = 0
            for m in to_restore:
                if m.startswith(f"{ROM_PREFIX}/"):
                    # ROM goes to game_path root
                    rom_name = m[len(f"{ROM_PREFIX}/"):]
                    target = os.path.join(game_path, rom_name)
                elif m.startswith(f"{WORKSPACE_PREFIX}/"):
                    # Workspace goes to project_dir
                    rel = m[len(f"{WORKSPACE_PREFIX}/"):]
                    if not project_dir:
                        continue
                    target = os.path.join(project_dir, rel)
                else:
                    # Game source files
                    target = os.path.join(game_path, m)

                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(m) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                restored += 1

            print(f"  Restored {restored} files from v{version_str}.")
            return True

    except Exception as e:
        print(f"  ERROR during restore: {e}")
        return False


def delete_version(game_path, version_str):
    """Delete a version ZIP and remove from manifest. Returns True on success."""
    manifest = _load_manifest(game_path)
    version_dir = os.path.join(game_path, "backups", VERSION_DIR)

    found = None
    for i, entry in enumerate(manifest.get("versions", [])):
        if entry["version"] == version_str:
            found = i
            break

    if found is None:
        print(f"  Version {version_str} not found.")
        return False

    entry = manifest["versions"][found]
    zip_path = os.path.join(version_dir, entry["filename"])

    # Remove ZIP
    if os.path.isfile(zip_path):
        try:
            os.remove(zip_path)
        except OSError as e:
            print(f"  ERROR: Could not delete {entry['filename']}: {e}")
            return False

    # Remove from manifest
    manifest["versions"].pop(found)
    _save_manifest(game_path, manifest)
    return True


def bump_major(game_path):
    """Bump major version number. Returns new version string (e.g., '2.0').

    Sets next_major += 1, next_minor = 0 in manifest.
    """
    manifest = _load_manifest(game_path)
    new_major = manifest.get("next_major", 0) + 1
    manifest["next_major"] = new_major
    manifest["next_minor"] = 0
    _save_manifest(game_path, manifest)
    return f"{new_major}.0"


def get_disk_usage(game_path):
    """Return (total_bytes, version_count) for all version ZIPs."""
    version_dir = os.path.join(game_path, "backups", VERSION_DIR)
    if not os.path.isdir(version_dir):
        return 0, 0
    total = 0
    count = 0
    for fname in os.listdir(version_dir):
        if fname.startswith("v") and fname.endswith(".zip"):
            try:
                total += os.path.getsize(os.path.join(version_dir, fname))
                count += 1
            except OSError:
                pass
    return total, count


def repair_manifest(game_path):
    """Rebuild manifest from ZIP files on disk. Returns count of versions found."""
    version_dir = os.path.join(game_path, "backups", VERSION_DIR)
    if not os.path.isdir(version_dir):
        return 0

    entries = []
    max_major = 0
    max_minor = 0
    for fname in sorted(os.listdir(version_dir)):
        if not fname.startswith("v") or not fname.endswith(".zip"):
            continue
        zip_path = os.path.join(version_dir, fname)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if METADATA_FILE not in zf.namelist():
                    continue
                meta = json.loads(zf.read(METADATA_FILE))
                entry = {
                    "version": meta.get("version", ""),
                    "major": 0,
                    "minor": 0,
                    "label": meta.get("label", ""),
                    "slug": "",
                    "filename": fname,
                    "timestamp": meta.get("timestamp", ""),
                    "torch_version": meta.get("torch_version", ""),
                    "expansion_version": meta.get("expansion_version", ""),
                    "file_count": meta.get("file_count", 0),
                    "rom_filename": meta.get("rom_filename", ""),
                    "rom_size_bytes": meta.get("rom_size_bytes", 0),
                    "size_bytes": os.path.getsize(zip_path),
                    "notes": meta.get("notes", ""),
                }
                # Parse version string
                parts = entry["version"].split(".")
                if len(parts) == 2:
                    try:
                        entry["major"] = int(parts[0])
                        entry["minor"] = int(parts[1])
                    except ValueError:
                        pass
                entry["slug"] = _slugify(entry["label"])
                entries.append(entry)
                if entry["major"] > max_major:
                    max_major = entry["major"]
                    max_minor = entry["minor"]
                elif entry["major"] == max_major and entry["minor"] > max_minor:
                    max_minor = entry["minor"]
        except (zipfile.BadZipFile, json.JSONDecodeError, OSError):
            continue

    manifest = {
        "schema_version": 1,
        "next_major": max_major,
        "next_minor": max_minor + 1 if entries else 1,
        "versions": entries,
    }
    _save_manifest(game_path, manifest)
    return len(entries)


# ============================================================
# TUI — INTERACTIVE MENU
# ============================================================

def versions_menu(game_path, project_dir, settings, proj_name):
    """Interactive version browser.

    Scrolling list with save/restore/bump/delete/info actions.
    """
    from torch.config import _nav_keys
    from torch.ui import print_logo, _set_terminal_title, clear_screen

    _set_terminal_title("TORCH \u2014 Versions")
    nav_keys = _nav_keys(settings)
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = nav_keys
    selected_idx = 0
    MAX_VISIBLE = 8

    while True:
        versions = list_versions(game_path)
        if versions:
            selected_idx = max(0, min(selected_idx, len(versions) - 1))
        else:
            selected_idx = 0

        clear_screen()
        print_logo("Game Versions", proj_name)
        print(BAR)

        # Disk usage header
        total_bytes, count = get_disk_usage(game_path)
        manifest = _load_manifest(game_path)
        next_ver, _, _ = _next_version(manifest)
        print(f"  {DIM}Next version:{RST} {CYAN}v{next_ver}{RST}  "
              f"{DIM}|  {count} saved  |  {_format_size_mb(total_bytes):.1f} MB total{RST}")
        print()

        if not versions:
            print(f"  {DIM}No versions saved yet.{RST}")
            print(f"  {DIM}Press {GOLD}[s]{DIM} to save your first version.{RST}")
        else:
            # Windowed scrolling
            scroll_offset = 0
            if len(versions) > MAX_VISIBLE:
                if selected_idx >= scroll_offset + MAX_VISIBLE:
                    scroll_offset = selected_idx - MAX_VISIBLE + 1
                elif selected_idx < scroll_offset:
                    scroll_offset = selected_idx
                # Ensure selected is visible
                half = MAX_VISIBLE // 2
                if selected_idx > half:
                    scroll_offset = min(selected_idx - half,
                                       len(versions) - MAX_VISIBLE)
                scroll_offset = max(0, scroll_offset)

            visible = versions[scroll_offset:scroll_offset + MAX_VISIBLE]
            for i, v in enumerate(visible):
                real_idx = scroll_offset + i
                marker = f"{GOLD}>>{RST} " if real_idx == selected_idx else "   "
                ver_col = WHITE if real_idx == selected_idx else CYAN
                num = f"{real_idx + 1}."
                ver_tag = f"v{v['version']}"
                label = v.get("label", "") or "(unnamed)"
                rom_tag = f"  {GREEN}ROM{RST}" if v.get("rom_filename") else ""
                print(f"  {marker}{num:<4} {ver_col}{ver_tag:<8}{RST} "
                      f"{WHITE}{label}{RST}{rom_tag}")
                print(f"        {DIM}{v['display_time']}  |  "
                      f"{v['file_count']} files  |  "
                      f"{v['size_mb']:.1f} MB{RST}")

            if len(versions) > MAX_VISIBLE:
                showing = f"{scroll_offset + 1}-{scroll_offset + len(visible)}"
                print(f"  {DIM}showing {showing} of {len(versions)}{RST}")

        print()
        print(f"  {GOLD}[s]{RST} {DIM}save{RST}  "
              f"{GOLD}[{NK_OPEN}]{RST} {DIM}info{RST}  "
              f"{GOLD}[r]{RST} {DIM}restore{RST}  "
              f"{GOLD}[b]{RST} {DIM}bump major{RST}  "
              f"{GOLD}[d]{RST} {DIM}delete{RST}  "
              f"{GOLD}[q]{RST} {DIM}back{RST}")
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return
        raw = raw.rstrip("\n")

        if raw == "":
            if versions:
                selected_idx = (selected_idx + 1) % len(versions)
            continue

        cmd = raw.strip().lower()

        if cmd == "q":
            return
        elif cmd == NK_UP:
            if versions:
                selected_idx = max(0, selected_idx - 1)
        elif cmd == NK_DOWN:
            if versions:
                selected_idx = min(len(versions) - 1, selected_idx + 1)
        elif cmd == "s":
            _tui_save_version(game_path, project_dir)
        elif cmd == NK_OPEN or cmd == "i":
            if versions:
                _tui_version_detail(versions[selected_idx], game_path, project_dir)
        elif cmd == "r":
            if versions:
                v = versions[selected_idx]
                _tui_restore_version(v, game_path, project_dir)
        elif cmd == "b":
            _tui_bump_major(game_path)
        elif cmd == "d":
            if versions:
                _tui_delete_version(versions[selected_idx], game_path)
        elif raw.strip().isdigit():
            idx = int(raw.strip()) - 1
            if 0 <= idx < len(versions):
                selected_idx = idx


def _tui_save_version(game_path, project_dir):
    """Prompt for label and save a new version."""
    print()
    try:
        label = input("  Version label: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not label:
        try:
            proceed = input("  Save without a label? [y/N] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if proceed != "y":
            return

    try:
        notes = input(f"  {DIM}Notes (optional):{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        notes = ""

    print(f"  {DIM}Creating version...{RST}")
    entry = create_version(game_path, project_dir, label=label, notes=notes)
    if entry:
        print(f"  {GREEN}Saved{RST} v{entry['version']} \u2014 "
              f"{entry.get('label', '')} ({_format_size_mb(entry['size_bytes']):.1f} MB)")
        rom_note = f"  ROM: {entry['rom_filename']}" if entry.get("rom_filename") else "  (no ROM found)"
        print(f"  {DIM}{rom_note}{RST}")
    input(f"  {DIM}Press Enter to continue{RST} > ")


def _tui_version_detail(v, game_path, project_dir):
    """Show version detail screen."""
    from torch.ui import clear_screen, print_logo
    clear_screen()
    print_logo("Game Versions", None)
    print(BAR)
    print(f"   {WHITE}VERSION v{v['version']}{RST}")
    print(BAR)
    print()
    print(f"  Label:      {WHITE}{v.get('label', '') or '(unnamed)'}{RST}")
    print(f"  Saved:      {CYAN}{v['display_time']}{RST}")
    print(f"  Files:      {v['file_count']}")
    print(f"  Size:       {v['size_mb']:.1f} MB")
    if v.get("rom_filename"):
        rom_mb = _format_size_mb(v.get("rom_size_bytes", 0))
        print(f"  ROM:        {GREEN}{v['rom_filename']}{RST} ({rom_mb:.1f} MB)")
    else:
        print(f"  ROM:        {DIM}not included{RST}")
    print(f"  TORCH:      {DIM}v{v.get('torch_version', '?')}{RST}")
    if v.get("expansion_version"):
        print(f"  Expansion:  {DIM}v{v['expansion_version']}{RST}")
    if v.get("notes"):
        print(f"  Notes:      {DIM}{v['notes']}{RST}")
    print()
    print(f"  {GOLD}[r]{RST} {DIM}Restore{RST}  "
          f"{GOLD}[d]{RST} {DIM}Delete{RST}  "
          f"{GOLD}[q]{RST} {DIM}Back{RST}")
    print()
    try:
        raw = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if raw == "r":
        _tui_restore_version(v, game_path, project_dir)
    elif raw == "d":
        _tui_delete_version(v, game_path)


def _tui_restore_version(v, game_path, project_dir):
    """Restore prompt with scope selection."""
    print()
    print(f"  Restore v{v['version']} — {v.get('label', '')}")
    print()
    print(f"  {GOLD}[1]{RST} Full restore (game + ROM + workspace)")
    print(f"  {GOLD}[2]{RST} Game files only")
    print(f"  {GOLD}[3]{RST} ROM only")
    print(f"  {GOLD}[4]{RST} Workspace only")
    print(f"  {GOLD}[q]{RST} Cancel")
    print()
    try:
        choice = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if choice == "1":
        restore_version(game_path, project_dir, v["version"],
                        restore_game=True, restore_rom=True, restore_workspace=True)
    elif choice == "2":
        restore_version(game_path, project_dir, v["version"],
                        restore_game=True, restore_rom=False, restore_workspace=False)
    elif choice == "3":
        restore_version(game_path, project_dir, v["version"],
                        restore_game=False, restore_rom=True, restore_workspace=False)
    elif choice == "4":
        restore_version(game_path, project_dir, v["version"],
                        restore_game=False, restore_rom=False, restore_workspace=True)
    else:
        return
    input(f"  {DIM}Press Enter to continue{RST} > ")


def _tui_bump_major(game_path):
    """Confirm and bump major version."""
    manifest = _load_manifest(game_path)
    current_major = manifest.get("next_major", 0)
    print()
    print(f"  Current major: {CYAN}{current_major}{RST}")
    print(f"  Next version after bump: {WHITE}v{current_major + 1}.0{RST}")
    try:
        proceed = input("  Bump major version? [y/N] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if proceed == "y":
        new_ver = bump_major(game_path)
        print(f"  {GREEN}Major version bumped.{RST} Next save will be v{new_ver}.")
    input(f"  {DIM}Press Enter to continue{RST} > ")


def _tui_delete_version(v, game_path):
    """Confirm and delete a version."""
    print()
    print(f"  {RED}Delete{RST} v{v['version']} \u2014 {v.get('label', '')}?")
    print(f"  {DIM}This is permanent and cannot be undone.{RST}")
    try:
        proceed = input("  Type 'delete' to confirm > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if proceed == "delete":
        if delete_version(game_path, v["version"]):
            print(f"  {GREEN}Deleted{RST} v{v['version']}.")
        else:
            print(f"  {RED}Failed to delete.{RST}")
    else:
        print("  Cancelled.")
    input(f"  {DIM}Press Enter to continue{RST} > ")
