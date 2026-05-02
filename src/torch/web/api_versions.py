# TORCH_MODULE: Web API — Game Versions
# TORCH_GROUP: Web
"""Game Version Control API endpoints for the TORCH web GUI.

Provides version listing, creation, restore, deletion, and major bump.
Backed by game_versions.py.

Routes are registered via the shared api_route decorator so they merge
into the global route list automatically once this module is imported.
"""

from torch.web.api import (
    api_route, ok_response, error_response, _read_json_body,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_paths(handler):
    """Extract game_path and project_dir from the server."""
    game_path = getattr(handler.server, "game_path", "")
    project_dir = getattr(handler.server, "project_dir", "")
    if not game_path:
        return None, None, error_response("No game path configured", 500)
    return game_path, project_dir, None


def _validate_version_str(version_str):
    """Validate version string format (N.M)."""
    import re
    return bool(re.match(r'^\d+\.\d+$', version_str))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", "/api/versions")
def handle_versions_list(handler, match, query_params):
    """List all saved game versions."""
    game_path, _, err = _get_paths(handler)
    if err:
        return err

    from torch.game_versions import list_versions, get_disk_usage, _load_manifest, _next_version

    versions = list_versions(game_path)
    total_bytes, count = get_disk_usage(game_path)
    manifest = _load_manifest(game_path)
    next_ver, _, _ = _next_version(manifest)

    return ok_response({
        "versions": versions,
        "next_version": next_ver,
        "disk_usage_mb": round(total_bytes / (1024 * 1024), 1),
        "version_count": count,
    })


@api_route("POST", "/api/versions")
def handle_version_create(handler, match, query_params):
    """Create a new game version."""
    game_path, project_dir, err = _get_paths(handler)
    if err:
        return err

    body = _read_json_body(handler)
    if body is None:
        body = {}

    label = body.get("label", "")
    notes = body.get("notes", "")

    from torch.game_versions import create_version

    entry = create_version(game_path, project_dir, label=label, notes=notes)
    if entry is None:
        return error_response("Failed to create version")

    return ok_response({
        "version": entry["version"],
        "filename": entry["filename"],
        "label": entry.get("label", ""),
        "size_mb": round(entry.get("size_bytes", 0) / (1024 * 1024), 1),
        "file_count": entry.get("file_count", 0),
        "rom_filename": entry.get("rom_filename", ""),
    })


@api_route("GET", r"/api/versions/(?P<version>\d+\.\d+)")
def handle_version_info(handler, match, query_params):
    """Get details about a specific version."""
    game_path, _, err = _get_paths(handler)
    if err:
        return err

    version_str = match.group("version")
    if not _validate_version_str(version_str):
        return error_response("Invalid version format")

    from torch.game_versions import get_version_info

    info = get_version_info(game_path, version_str)
    if info is None:
        return error_response("Version not found", 404)

    return ok_response(info)


@api_route("POST", r"/api/versions/(?P<version>\d+\.\d+)/restore")
def handle_version_restore(handler, match, query_params):
    """Restore from a game version."""
    game_path, project_dir, err = _get_paths(handler)
    if err:
        return err

    version_str = match.group("version")
    if not _validate_version_str(version_str):
        return error_response("Invalid version format")

    body = _read_json_body(handler)
    if body is None:
        body = {}

    restore_game = body.get("game", True)
    restore_rom = body.get("rom", True)
    restore_workspace = body.get("workspace", True)

    from torch.game_versions import get_version_info

    info = get_version_info(game_path, version_str)
    if info is None:
        return error_response("Version not found", 404)

    # Web restore skips interactive confirmation — extract directly
    import zipfile
    zip_path = info["path"]

    from torch.game_versions import ROM_PREFIX, WORKSPACE_PREFIX, METADATA_FILE
    import os

    try:
        restored = 0
        with zipfile.ZipFile(zip_path, "r") as zf:
            for m in zf.namelist():
                if m == METADATA_FILE:
                    continue
                is_rom = m.startswith(f"{ROM_PREFIX}/")
                is_workspace = m.startswith(f"{WORKSPACE_PREFIX}/")
                is_game = not is_rom and not is_workspace

                if is_game and not restore_game:
                    continue
                if is_rom and not restore_rom:
                    continue
                if is_workspace and not restore_workspace:
                    continue

                if is_rom:
                    rom_name = m[len(f"{ROM_PREFIX}/"):]
                    target = os.path.join(game_path, rom_name)
                elif is_workspace:
                    rel = m[len(f"{WORKSPACE_PREFIX}/"):]
                    if not project_dir:
                        continue
                    target = os.path.join(project_dir, rel)
                else:
                    target = os.path.join(game_path, m)

                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(m) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                restored += 1

        return ok_response({
            "restored": True,
            "version": version_str,
            "file_count": restored,
        })
    except Exception as e:
        return error_response(f"Restore failed: {e}", 500)


@api_route("DELETE", r"/api/versions/(?P<version>\d+\.\d+)")
def handle_version_delete(handler, match, query_params):
    """Delete a game version."""
    game_path, _, err = _get_paths(handler)
    if err:
        return err

    version_str = match.group("version")
    if not _validate_version_str(version_str):
        return error_response("Invalid version format")

    from torch.game_versions import delete_version

    if delete_version(game_path, version_str):
        return ok_response({"deleted": True, "version": version_str})
    return error_response("Version not found or could not be deleted", 404)


@api_route("POST", "/api/versions/bump")
def handle_version_bump(handler, match, query_params):
    """Bump major version number."""
    game_path, _, err = _get_paths(handler)
    if err:
        return err

    from torch.game_versions import bump_major

    new_version = bump_major(game_path)
    return ok_response({"new_version": new_version})
