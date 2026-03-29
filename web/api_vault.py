# TORCH_MODULE: Web API — Vault
# TORCH_GROUP: Web
"""Vault API endpoints for the TORCH web GUI.

Provides build snapshot listing/restore, workspace snapshot listing/restore,
and per-map sync.  Backed by verified_snapshots.py, vault.py, and sync.py.

Routes are registered via the shared api_route decorator so they merge
into the global route list automatically once this module is imported.
"""

import os
import zipfile
from datetime import datetime

from torch.web.api import (
    api_route, ok_response, error_response, _read_json_body, _safe_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_game_path(handler):
    """Extract game_path from the server; return (game_path, error_response)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return None, error_response("No game path configured", 500)
    return game_path, None


def _get_project_dir(handler):
    """Extract project_dir from the server; return (project_dir, error_response)."""
    project_dir = getattr(handler.server, "project_dir", "")
    if not project_dir:
        return None, error_response("No project directory configured", 500)
    return project_dir, None


def _validate_filename(filename):
    """Reject filenames with path traversal components."""
    if not filename:
        return False
    if "/" in filename or "\\" in filename:
        return False
    if filename in (".", "..") or filename.startswith(".."):
        return False
    return True


def _validate_map_name(map_name):
    """Validate that a map name contains only safe characters."""
    if not map_name:
        return False
    import re
    return bool(re.match(r'^[A-Za-z0-9_]+$', map_name))


# ---------------------------------------------------------------------------
# GET /api/vault/snapshots — List verified build snapshots
# ---------------------------------------------------------------------------

@api_route("GET", "/api/vault/snapshots")
def handle_vault_snapshots_list(handler, match, query_params):
    """Return all verified build snapshots, newest first."""
    game_path, err = _get_game_path(handler)
    if err:
        return err

    from torch.verified_snapshots import list_verified_snapshots

    snapshots = list_verified_snapshots(game_path)

    return ok_response({
        "snapshots": [
            {
                "filename": s["filename"],
                "date": s["display_time"],
                "timestamp": s["timestamp"],
                "trigger": s["trigger"],
                "file_count": s["file_count"],
                "size_mb": round(s["size_mb"], 1),
            }
            for s in snapshots
        ],
    })


# ---------------------------------------------------------------------------
# POST /api/vault/restore — Restore from a verified build snapshot
# ---------------------------------------------------------------------------

@api_route("POST", "/api/vault/restore")
def handle_vault_restore(handler, match, query_params):
    """Restore all files from a verified build snapshot.

    Body: {filename: str}
    Skips the interactive confirmation (web UI handles its own).
    """
    game_path, err = _get_game_path(handler)
    if err:
        return err

    body = _read_json_body(handler)
    if not body or not body.get("filename"):
        return error_response("Missing 'filename' field", 400)

    filename = body["filename"]
    if not _validate_filename(filename):
        return error_response("Invalid filename", 400)

    # Resolve and validate path is within the verified backup directory
    from torch.verified_snapshots import _get_verified_backup_dir
    backup_dir = _get_verified_backup_dir(game_path)

    try:
        snapshot_path = _safe_path(backup_dir, filename)
    except ValueError:
        return error_response("Invalid filename (path traversal)", 400)

    if not os.path.isfile(snapshot_path):
        return error_response("Snapshot not found", 404)

    # Perform the restore — extract all files (skip metadata), no interactive prompt
    from torch.verified_snapshots import METADATA_FILENAME
    try:
        restored = []
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for member in zf.namelist():
                if member == METADATA_FILENAME:
                    continue
                target = os.path.join(game_path, member)
                # Safety: ensure target stays within game_path
                norm_target = os.path.normpath(target)
                norm_base = os.path.normpath(game_path)
                if not (norm_target == norm_base or
                        norm_target.startswith(norm_base + os.sep)):
                    continue  # skip entries that escape game_path
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                restored.append(member)

        return ok_response({
            "restored": True,
            "file_count": len(restored),
            "filename": filename,
        })
    except (zipfile.BadZipFile, OSError) as e:
        return error_response(f"Restore failed: {e}", 500)


# ---------------------------------------------------------------------------
# GET /api/vault/workspace — List maps with workspace snapshots
# ---------------------------------------------------------------------------

@api_route("GET", "/api/vault/workspace")
def handle_vault_workspace_maps(handler, match, query_params):
    """Return all maps that have workspace snapshots."""
    project_dir, err = _get_project_dir(handler)
    if err:
        return err

    # Reuse the gathering logic from vault.py
    maps = _gather_workspace_maps(project_dir)

    return ok_response({"maps": maps})


def _gather_workspace_maps(project_dir):
    """Scan project workspace for maps with snapshot backups.

    Mirrors vault._gather_maps_with_snapshots but returns JSON-safe dicts.
    """
    result = []
    if not os.path.isdir(project_dir):
        return result

    for entry in sorted(os.listdir(project_dir)):
        map_dir = os.path.join(project_dir, entry)
        snap_dir = os.path.join(map_dir, "backups", "snapshots")
        if not os.path.isdir(snap_dir):
            continue
        snaps = sorted([
            f for f in os.listdir(snap_dir)
            if f.startswith(entry + "_") and f.endswith(".zip")
        ], reverse=True)
        if not snaps:
            continue

        # Parse latest timestamp
        ts_raw = snaps[0][len(entry) + 1:-4]
        try:
            dt = datetime.strptime(ts_raw, "%Y%m%d_%H%M%S")
            latest = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            latest = ts_raw

        result.append({
            "name": entry,
            "count": len(snaps),
            "latest": latest,
        })

    return result


# ---------------------------------------------------------------------------
# GET /api/vault/workspace/<map_name> — List snapshots for a specific map
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/vault/workspace/(?P<map_name>[A-Za-z0-9_]+)")
def handle_vault_workspace_snapshots(handler, match, query_params):
    """Return workspace snapshots for a specific map."""
    project_dir, err = _get_project_dir(handler)
    if err:
        return err

    map_name = match.group("map_name")
    if not _validate_map_name(map_name):
        return error_response("Invalid map name", 400)

    map_dir = os.path.join(project_dir, map_name)
    snap_dir = os.path.join(map_dir, "backups", "snapshots")

    if not os.path.isdir(snap_dir):
        return ok_response({"map_name": map_name, "snapshots": []})

    prefix = map_name + "_"
    snap_files = sorted([
        f for f in os.listdir(snap_dir)
        if f.startswith(prefix) and f.endswith(".zip")
    ], reverse=True)

    snapshots = []
    for fname in snap_files:
        fpath = os.path.join(snap_dir, fname)

        # Parse timestamp
        ts_raw = fname[len(prefix):-4]
        try:
            dt = datetime.strptime(ts_raw, "%Y%m%d_%H%M%S")
            display_time = dt.strftime("%Y-%m-%d %H:%M")
            timestamp = dt.isoformat()
        except ValueError:
            display_time = ts_raw
            timestamp = ts_raw

        # File size
        try:
            size_bytes = os.path.getsize(fpath)
        except OSError:
            size_bytes = 0

        # File count inside the ZIP
        file_count = 0
        try:
            with zipfile.ZipFile(fpath, "r") as zf:
                file_count = len(zf.namelist())
        except (zipfile.BadZipFile, OSError):
            pass

        # Pinned status
        pin_path = os.path.join(snap_dir, fname + ".pin")
        is_pinned = os.path.exists(pin_path)

        snapshots.append({
            "filename": fname,
            "date": display_time,
            "timestamp": timestamp,
            "size_kb": size_bytes // 1024,
            "file_count": file_count,
            "pinned": is_pinned,
        })

    return ok_response({
        "map_name": map_name,
        "snapshots": snapshots,
    })


# ---------------------------------------------------------------------------
# POST /api/vault/workspace/<map_name>/restore — Restore a workspace snapshot
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/vault/workspace/(?P<map_name>[A-Za-z0-9_]+)/restore")
def handle_vault_workspace_restore(handler, match, query_params):
    """Restore a workspace snapshot for a specific map.

    Body: {filename: str}
    Calls sync.restore_map with the snapshot index derived from filename.
    """
    project_dir, err = _get_project_dir(handler)
    if err:
        return err

    game_path, err = _get_game_path(handler)
    if err:
        return err

    map_name = match.group("map_name")
    if not _validate_map_name(map_name):
        return error_response("Invalid map name", 400)

    body = _read_json_body(handler)
    if not body or not body.get("filename"):
        return error_response("Missing 'filename' field", 400)

    filename = body["filename"]
    if not _validate_filename(filename):
        return error_response("Invalid filename", 400)

    # Validate the snapshot file exists in the expected directory
    map_dir = os.path.join(project_dir, map_name)
    snap_dir = os.path.join(map_dir, "backups", "snapshots")

    try:
        snapshot_path = _safe_path(snap_dir, filename)
    except ValueError:
        return error_response("Invalid filename (path traversal)", 400)

    if not os.path.isfile(snapshot_path):
        return error_response("Snapshot not found", 404)

    # Find the snapshot index (restore_map expects 0-based index into
    # the sorted-newest-first list)
    prefix = map_name + "_"
    all_snaps = sorted([
        f for f in os.listdir(snap_dir)
        if f.startswith(prefix) and f.endswith(".zip")
    ], reverse=True)

    try:
        snapshot_idx = all_snaps.index(filename)
    except ValueError:
        return error_response("Snapshot not found in listing", 404)

    # Derive sync params for restore_map
    from torch.web.api import _derive_sync_params
    emotes_conf, source_display = _derive_sync_params(project_dir)

    from torch.sync import restore_map
    try:
        restore_map(map_name, project_dir, game_path,
                     emotes_conf, source_display,
                     max_snapshots=10, snapshot_idx=snapshot_idx)
        return ok_response({
            "restored": True,
            "map_name": map_name,
            "filename": filename,
        })
    except Exception as e:
        return error_response(f"Restore failed: {e}", 500)


# ---------------------------------------------------------------------------
# POST /api/sync/<map_name> — Sync a single map
# ---------------------------------------------------------------------------

import threading

_map_sync_lock = threading.Lock()


@api_route("POST", r"/api/sync/(?P<map_name>[A-Za-z0-9_]+)")
def handle_sync_single_map(handler, match, query_params):
    """Sync a single enrolled map (compile + write to game folder)."""
    if not _map_sync_lock.acquire(blocking=False):
        return error_response("A sync operation is already in progress", 409)

    project_dir, err = _get_project_dir(handler)
    if err:
        _map_sync_lock.release()
        return err

    game_path, err = _get_game_path(handler)
    if err:
        _map_sync_lock.release()
        return err

    map_name = match.group("map_name")
    if not _validate_map_name(map_name):
        _map_sync_lock.release()
        return error_response("Invalid map name", 400)

    # Verify the map is enrolled
    try:
        from torch.registry import is_enrolled
        if not is_enrolled(project_dir, map_name):
            _map_sync_lock.release()
            return error_response(f"Map '{map_name}' is not enrolled", 400)
    except Exception:
        _map_sync_lock.release()
        return error_response("Failed to check enrollment", 500)

    from torch.web.api import _derive_sync_params
    emotes_conf, source_display = _derive_sync_params(project_dir)

    # Run sync in background thread
    t = threading.Thread(
        target=_run_single_map_sync,
        args=(map_name, project_dir, game_path, emotes_conf, source_display),
        daemon=True,
    )
    t.start()

    return ok_response({"status": "started", "map": map_name})


def _run_single_map_sync(map_name, project_dir, game_path, emotes_conf,
                          source_display):
    """Execute single-map sync in a background thread, broadcasting SSE events."""
    try:
        from torch.web.events import broadcaster
    except ImportError:
        broadcaster = None

    try:
        from torch.sync import sync_map
        if broadcaster:
            broadcaster.broadcast("sync_start", {"map": map_name})
        sync_map(map_name, project_dir, game_path,
                 emotes_conf, source_display, quiet=True)
        if broadcaster:
            broadcaster.broadcast("sync_complete",
                                  {"map": map_name, "success": True})
    except Exception as exc:
        if broadcaster:
            broadcaster.broadcast("sync_complete",
                                  {"map": map_name, "success": False,
                                   "error": str(exc)})
    finally:
        _map_sync_lock.release()
