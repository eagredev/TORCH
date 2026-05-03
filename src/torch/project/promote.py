"""Non-interactive build promotion.

Copies the dev package to the experimental or stable install location
without interactive menus. Used for automated promotion after version
bumps. Equivalent to vc.py's Promote Build flow.
"""
# TORCH_MODULE: Build Promoter
# TORCH_GROUP: Dev Tools
import os
import sys
import zipfile

_DEV_ONLY_DIRS = {"tests", "__pycache__"}
_TORCH_DEV = os.path.expanduser("~/torch_dev")
_RELEASES_DIR = os.path.expanduser("~/torch_releases")
_EXPERIMENTAL_DIR = os.path.expanduser("~/torch_experimental")


def _detect_version():
    """Read VERSION from __init__.py."""
    init_path = os.path.join(_TORCH_DEV, "__init__.py")
    with open(init_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("VERSION"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _collect_files():
    """Collect all files to promote (mirrors vc.py logic + web static)."""
    files = []
    for root, dirs, filenames in os.walk(_TORCH_DEV):
        dirs[:] = [d for d in dirs if d not in _DEV_ONLY_DIRS
                   and not d.startswith(".")]
        rel_root = os.path.relpath(root, _TORCH_DEV)
        for fname in sorted(filenames):
            # Include .py files everywhere
            if fname.endswith(".py"):
                rel_path = fname if rel_root == "." else f"{rel_root}/{fname}"
                files.append(rel_path)
            # Include web static assets (.js, .css, .html)
            elif rel_root.startswith("web/static") or rel_root.startswith("web" + os.sep + "static"):
                rel_path = f"{rel_root}/{fname}"
                files.append(rel_path)
            # Include data_files/ contents
            elif rel_root == "data_files" or rel_root.startswith("data_files" + os.sep):
                rel_path = f"{rel_root}/{fname}"
                files.append(rel_path)
    return files


def promote(track="experimental"):
    """Create a release zip for the given track."""
    version = _detect_version()
    if not version:
        print("ERROR: Could not detect VERSION from __init__.py")
        return False

    if track == "stable":
        out_dir = _RELEASES_DIR
    else:
        out_dir = _EXPERIMENTAL_DIR

    os.makedirs(out_dir, exist_ok=True)
    out_fname = f"torch_v{version}_{track}.zip"
    out_path = os.path.join(out_dir, out_fname)

    files = _collect_files()
    if not files:
        print("ERROR: No files found to promote")
        return False

    # Check for existing release with same version
    if os.path.isfile(out_path):
        print(f"  Overwriting existing {out_fname}")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in files:
            full = os.path.join(_TORCH_DEV, rel_path)
            if os.path.isfile(full):
                zf.write(full, rel_path)

    py_count = sum(1 for f in files if f.endswith(".py"))
    static_count = sum(1 for f in files if not f.endswith(".py"))
    print(f"  {track.title()} release created: {out_fname}")
    print(f"  {py_count} Python modules + {static_count} static assets")
    return True


if __name__ == "__main__":
    track = "stable" if "--stable" in sys.argv else "experimental"
    success = promote(track)
    sys.exit(0 if success else 1)
