"""TORCH in-package updater — torch update [source]"""
# TORCH_MODULE: Updater
# TORCH_GROUP: Tools
import os
import re
import sys
import shutil
import zipfile
import tempfile

from torch import VERSION
from torch.backup import _create_torch_backup, TORCH_PACKAGE_DIR
from torch.config import load_config
from torch.ui import print_logo, clear_screen

# Default locations to search for stable releases
TORCH_RELEASES_DIR = os.path.expanduser("~/torch_releases")

BAR = "  " + "\u2501" * 49
DIV = "  " + "\u2500" * 49


def _read_version_from_zip(zip_path):
    """Extract VERSION string from __init__.py inside a zip. Returns version str or None."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Find __init__.py — may be at root or inside a package subfolder
            candidates = [n for n in zf.namelist() if n.endswith("__init__.py")]
            if not candidates:
                return None
            # Prefer shortest path (most likely the package root)
            candidates.sort(key=len)
            content = zf.read(candidates[0]).decode("utf-8", errors="replace")
            m = re.search(r'VERSION\s*=\s*"([^"]+)"', content)
            return m.group(1) if m else None
    except Exception:
        return None


def _find_update_source(cli_args):
    """Return (path, version) of the best update source, or (None, None).

    Priority:
    1. Explicit CLI argument (path to a zip)
    2. Newest stable zip in ~/torch_releases/
    """
    if cli_args:
        src = os.path.expanduser(cli_args[0])
        if os.path.isfile(src):
            ver = _read_version_from_zip(src)
            return src, ver
        else:
            print(f"  Error: file not found: {src}")
            return None, None

    # Scan ~/torch_releases/ for stable zips
    if not os.path.isdir(TORCH_RELEASES_DIR):
        return None, None

    _stable_re = re.compile(r'^torch_v(\d+\.\d+)_stable\.zip$')
    candidates = []
    for fname in os.listdir(TORCH_RELEASES_DIR):
        m = _stable_re.match(fname)
        if m:
            fpath = os.path.join(TORCH_RELEASES_DIR, fname)
            ver = _read_version_from_zip(fpath) or m.group(1)
            candidates.append((fpath, ver))

    if not candidates:
        return None, None

    # Sort by version tuple, pick newest
    def _vtuple(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except Exception:
            return (0,)

    candidates.sort(key=lambda c: _vtuple(c[1]), reverse=True)
    return candidates[0]


def _compare_versions(current, new):
    """Return -1/0/1 as current < new / equal / current > new."""
    def _vt(v):
        try:
            return tuple(int(x) for x in str(v).split("."))
        except Exception:
            return (0,)
    a, b = _vt(current), _vt(new)
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def _find_package_root(extracted_dir):
    """Return the directory inside extracted_dir that contains __init__.py.

    Handles zips that wrap the package in a single parent dir (e.g. torch-3.6/).
    """
    # Check directly
    if os.path.isfile(os.path.join(extracted_dir, "__init__.py")):
        return extracted_dir
    # Check one level down
    for entry in os.listdir(extracted_dir):
        sub = os.path.join(extracted_dir, entry)
        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "__init__.py")):
            return sub
    return extracted_dir


def _do_update(zip_path, install_path):
    """Extract zip to a staging dir, copy .py files into install_path.

    Does NOT rmtree the install — copies files individually so a running process
    isn't broken mid-update. Returns list of files copied.
    """
    staging = tempfile.mkdtemp(prefix="torch_update_")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(staging)

        pkg_root = _find_package_root(staging)
        copied = []
        for entry in os.listdir(pkg_root):
            if entry.endswith(".py"):
                src = os.path.join(pkg_root, entry)
                dst = os.path.join(install_path, entry)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    copied.append(entry)
        return copied
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def update_command(cli_args):
    """Entry point for `torch update [source]`."""
    clear_screen()
    print_logo("Updater")
    print(BAR)
    print("  TORCH  Updater")
    print(BAR)
    print()

    # 1. Find update source
    src_path, new_version = _find_update_source(cli_args)

    if src_path is None:
        print("  No stable release found.")
        print()
        print("  To update TORCH:")
        print("  1. Place a torch_v<X.X>_stable.zip in ~/torch_releases/")
        print("  2. Or run: torch update /path/to/torch_vX.X_stable.zip")
        print()
        print("  To create a stable release from a dev backup:")
        print("  Run: python3 ~/install.py  →  [3] Manage releases")
        print()
        input("  Press Enter to return > ")
        return

    print(f"  Installed : v{VERSION}")
    print(f"  Available : v{new_version}  ({os.path.basename(src_path)})")
    print()

    # 2. Compare versions
    cmp = _compare_versions(VERSION, new_version)
    if cmp == 0:
        print("  You already have this version installed.")
        yn = input("  Re-install anyway? [y/N] > ").strip().lower()
        if yn != "y":
            print("  Cancelled.")
            return
        print()
    elif cmp > 0:
        print(f"  Warning: source (v{new_version}) is OLDER than installed (v{VERSION}).")
        yn = input("  Downgrade anyway? [y/N] > ").strip().lower()
        if yn != "y":
            print("  Cancelled.")
            return
        print()
    else:
        print("  New version available. Proceeding with update.")
        print()

    # 3. Confirmation
    print(f"  Source    : {src_path}")
    print(f"  Install   : {TORCH_PACKAGE_DIR}")
    print(f"  Backup    : will be created before files are changed")
    print()
    yn = input("  Proceed? [Y/n] > ").strip().lower()
    if yn not in ("", "y", "yes"):
        print("  Cancelled.")
        return

    print()

    # 4. Backup BEFORE any files touched
    _project_name = None
    try:
        _upd_cfg = load_config()
        if _upd_cfg:
            _, _upd_projects, _ = _upd_cfg
            if _upd_projects:
                _project_name = list(_upd_projects.keys())[0]
    except Exception:
        pass
    print("  Creating backup...", end=" ", flush=True)
    try:
        backup_path = _create_torch_backup("pre-update", project_name=_project_name)
        print(f"done  ({os.path.basename(backup_path)})")
    except Exception as e:
        print(f"FAILED ({e})")
        print("  Aborting — no files changed.")
        return

    # 5. Do the update
    print("  Copying files...", end=" ", flush=True)
    try:
        copied = _do_update(src_path, TORCH_PACKAGE_DIR)
        print(f"done  ({len(copied)} files)")
    except Exception as e:
        print(f"FAILED ({e})")
        print()
        print("  Update failed. Backup is available:")
        print(f"  {backup_path}")
        return

    # 6. Report
    print()
    print(BAR)
    print(f"  TORCH updated: v{VERSION} -> v{new_version}")
    print(BAR)
    print()
    print("  Note: current session still has the old version in memory.")
    print("  Run `torch` again to use the updated version.")
    print()
    input("  Press Enter > ")
