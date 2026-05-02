"""TORCH self-backup system with tiered retention."""
# TORCH_MODULE: Self-Backup
# TORCH_GROUP: Tools
# BACKUP_VERSION = "1.2"
import os
import re
import gzip
import shutil
import zipfile
from datetime import datetime

from torch import VERSION
from torch.colours import GOLD, WHITE, CYAN, DIM, RST, BLUE, BAR

# ============================================================
# TORCH SELF-BACKUP (tiered retention for torch package upgrades)
# ============================================================

TORCH_BACKUP_DIR = os.path.expanduser("~/torch_backups")
_LEGACY_BACKUP_DIR = os.path.expanduser("~/porysync_backups")
TORCH_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))

_DEV_ONLY_DIRS = {"tests", "__pycache__"}  # top-level dirs never included in backups
_DATA_DIR = "data_files"  # non-code assets shipped alongside .py modules

_TORCH_BACKUP_RE_GZ = re.compile(
    r'^(?:porysync|torch)_v(\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9]+)?)_(\d{8}|\d{4}-\d{2}-\d{2}).*\.py\.gz$'
)
_TORCH_BACKUP_RE_ZIP = re.compile(
    r'^(?:porysync|torch)_v(\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9]+)?)_(\d{8}|\d{4}-\d{2}-\d{2}).*\.zip$'
)
# New format: torch_{project}_{version}_{date}_{tag}.zip
_TORCH_BACKUP_RE_ZIP_PROJECT = re.compile(
    r'^torch_([a-z0-9-]+)_(\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9]+)?)_(\d{8})_(.+)\.zip$'
)
HOT_TIER_SIZE = 5  # most recent non-milestone backups to keep

_MIGRATION_DONE = False  # module-level flag to run migration once per session


def _migrate_backup_dir():
    """One-time migration: rename ~/porysync_backups -> ~/torch_backups if needed."""
    global _MIGRATION_DONE
    if _MIGRATION_DONE:
        return
    _MIGRATION_DONE = True

    old_exists = os.path.isdir(_LEGACY_BACKUP_DIR)
    new_exists = os.path.isdir(TORCH_BACKUP_DIR)

    if old_exists and not new_exists:
        os.rename(_LEGACY_BACKUP_DIR, TORCH_BACKUP_DIR)
        print(f"  Migrated backup directory: ~/porysync_backups \u2192 ~/torch_backups")
    elif old_exists and new_exists:
        print(f"  WARNING: Both ~/porysync_backups and ~/torch_backups exist.")
        print(f"  Merge manually to avoid data loss. Using ~/torch_backups.")


def _sanitize_project_name(name):
    """Convert project name to safe filename component: lowercase, spaces to hyphens."""
    return name.lower().replace(" ", "-").replace("/", "-").replace("\\", "-")


def _parse_torch_backups(backup_dir):
    """Return list of dicts for every backup in backup_dir, sorted oldest->newest.

    Recognises legacy .py.gz, old .zip (no project), and new project-aware .zip formats.
    Keys: path, filename, version (str), date_str (YYYYMMDD), mtime (float), project (str).
    Only .zip and .py.gz files are considered; other files are silently skipped.
    """
    _migrate_backup_dir()
    if not os.path.isdir(backup_dir):
        return []
    entries = []
    for fname in os.listdir(backup_dir):
        fpath = os.path.join(backup_dir, fname)
        if not os.path.isfile(fpath):
            continue
        project = "legacy"
        # Try new project-aware format first
        if fname.endswith(".zip"):
            m_proj = _TORCH_BACKUP_RE_ZIP_PROJECT.match(fname)
            if m_proj:
                project = m_proj.group(1)
                version = m_proj.group(2)
                date_str = m_proj.group(3)
                mtime = os.path.getmtime(fpath)
                entries.append({
                    "path":     fpath,
                    "filename": fname,
                    "version":  version,
                    "date_str": date_str,
                    "mtime":    mtime,
                    "project":  project,
                })
                continue
        # Fall back to old format (no project name)
        if fname.endswith(".py.gz"):
            m = _TORCH_BACKUP_RE_GZ.match(fname)
        elif fname.endswith(".zip"):
            m = _TORCH_BACKUP_RE_ZIP.match(fname)
        else:
            continue
        version   = m.group(1) if m else None
        date_str  = m.group(2) if m else "00000000"
        mtime     = os.path.getmtime(fpath)
        entries.append({
            "path":     fpath,
            "filename": fname,
            "version":  version,
            "date_str": date_str,
            "mtime":    mtime,
            "project":  project,
        })
    entries.sort(key=lambda e: e["mtime"])
    return entries


def _prune_torch_backups(backup_dir):
    """Enforce tiered retention on backup directory:

    Cold tier  -- last backup *per version number*, never pruned (auto-milestone).
    Hot tier   -- up to HOT_TIER_SIZE most recent non-milestone backups kept;
                 older ones deleted.
    Unrecognised filenames (version=None) are never touched.
    """
    entries = _parse_torch_backups(backup_dir)
    if not entries:
        return 0

    # Identify cold-tier milestones: for each version, the *newest* entry is
    # the "last known build" of that version -- preserve it unconditionally.
    version_newest = {}
    for e in entries:
        if e["version"] is None:
            continue
        if e["version"] not in version_newest or e["mtime"] > version_newest[e["version"]]["mtime"]:
            version_newest[e["version"]] = e

    milestone_paths = {v["path"] for v in version_newest.values()}

    # Hot tier: non-milestone entries, sorted newest first
    hot = [e for e in reversed(entries) if e["path"] not in milestone_paths and e["version"] is not None]

    # Keep first HOT_TIER_SIZE, delete the rest
    to_delete = hot[HOT_TIER_SIZE:]
    for e in to_delete:
        try:
            os.remove(e["path"])
        except OSError:
            pass

    return len(to_delete)


def _create_torch_backup(tag=None, project_name=None):
    """Zip the torch/ package into ~/torch_backups/ and prune old backups.

    Filename format (with project): torch_{project}_{version}_{date}_{tag}.zip
    Filename format (no project):   torch_v{version}_{date}_{tag}.zip
    If tag is omitted, uses 'auto'.
    Returns the path of the created backup.
    """
    os.makedirs(TORCH_BACKUP_DIR, exist_ok=True)
    safe_tag = (tag or "auto").replace(" ", "-").replace("/", "-")
    date_str  = datetime.now().strftime("%Y%m%d")
    if project_name:
        safe_proj = _sanitize_project_name(project_name)
        fname     = f"torch_{safe_proj}_{VERSION}_{date_str}_{safe_tag}.zip"
    else:
        fname     = f"torch_v{VERSION}_{date_str}_{safe_tag}.zip"
    out_path  = os.path.join(TORCH_BACKUP_DIR, fname)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(TORCH_PACKAGE_DIR):
            # Prune dev-only dirs in place so os.walk doesn't descend into them
            dirs[:] = [d for d in dirs if d not in _DEV_ONLY_DIRS and not d.startswith(".")]
            rel_root = os.path.relpath(root, TORCH_PACKAGE_DIR)
            in_data = (rel_root == _DATA_DIR
                       or rel_root.startswith(_DATA_DIR + os.sep))
            for f in files:
                if f.endswith(".py") or in_data:
                    full = os.path.join(root, f)
                    arcname = f if rel_root == "." else f"{rel_root}/{f}"
                    zf.write(full, arcname)

    _prune_torch_backups(TORCH_BACKUP_DIR)
    return out_path


def _get_tier_info(entries):
    """Compute cold-tier milestones and hot-tier keep sets. Returns (milestone_paths, hot_keep)."""
    version_newest = {}
    for e in entries:
        if e["version"] is None:
            continue
        if e["version"] not in version_newest or e["mtime"] > version_newest[e["version"]]["mtime"]:
            version_newest[e["version"]] = e
    milestone_paths = {v["path"] for v in version_newest.values()}
    hot = [e for e in reversed(entries) if e["path"] not in milestone_paths and e["version"] is not None]
    hot_keep = set(e["path"] for e in hot[:HOT_TIER_SIZE])
    return milestone_paths, hot_keep


def _list_torch_backups(project_name=None):
    """Print a formatted table of current torch backups with tier labels.

    If project_name is given, only show backups matching that project.
    Legacy backups (old format, no project) are always shown but marked.
    """
    entries = _parse_torch_backups(TORCH_BACKUP_DIR)
    if not entries:
        print("  No backups found in ~/torch_backups/")
        return

    # Filter by project if requested
    if project_name:
        safe_proj = _sanitize_project_name(project_name)
        filtered = [e for e in entries if e["project"] == safe_proj or e["project"] == "legacy"]
    else:
        filtered = entries

    if not filtered:
        print(f"  No backups found for project '{project_name}'.")
        return

    milestone_paths, hot_keep = _get_tier_info(entries)

    print(BAR)
    header = f"  {WHITE}TORCH BACKUPS{RST}  {DIM}({len(filtered)} files in ~/torch_backups/){RST}"
    if project_name:
        header += f"  {DIM}[filter: {project_name}]{RST}"
    print(header)
    print(BAR)
    print(f"  {DIM}{'Tier':<10} {'Version':<14} {'Filename'}{RST}")
    print(f"  {DIM}{'-'*10} {'-'*14} {'-'*30}{RST}")
    for e in reversed(filtered):
        if e["path"] in milestone_paths:
            tier_str = f"{BLUE}COLD{RST}"
            fname_col = CYAN
        elif e["path"] in hot_keep:
            tier_str = f"{GOLD}hot{RST} "
            fname_col = ""
        else:
            tier_str = f"{DIM}old{RST} "
            fname_col = DIM
        ver_str = f"{e['version'] or '?'}"
        legacy_tag = f"  {DIM}(legacy){RST}" if e["project"] == "legacy" and project_name else ""
        print(f"  {tier_str}       {DIM}{ver_str:<14}{RST} {fname_col}{e['filename']}{RST if fname_col else ''}{legacy_tag}")
    print()
