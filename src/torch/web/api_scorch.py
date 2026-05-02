# TORCH_MODULE: Web API — SCORCH
# TORCH_GROUP: Web
"""SCORCH (vanilla content removal) API endpoints for the TORCH web GUI.

Provides scan, remove, snapshot, and restore endpoints for both
SCORCH Singe (selective) and SCORCH Phoenix (total) operations.
Delegates to cleanup_scanner.py, cleanup_writer.py, scorch_scanner.py,
and scorch_writer.py — no logic is duplicated here.

Routes are registered via the shared api_route decorator.
"""

import os
import traceback

from torch.web.api import (
    api_route, ok_response, error_response, _read_json_body,
)
from torch.cleanup_scanner import (
    full_scan, scan_category, CATEGORIES, CATEGORY_IDS,
    RemovalPlan, RemovalItem, SAFE, BLOCKED, CAUTION,
    has_sentinel,
)
from torch.cleanup_writer import (
    _create_cleanup_snapshot, _list_cleanup_snapshots,
    _restore_cleanup_snapshot,
    remove_maps, remove_trainers, remove_encounters,
    remove_frontier, remove_scripts, remove_tilesets,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _game_path(handler):
    """Extract game_path from server, returning (path, error_response)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return None, error_response("No game path configured", 500)
    return game_path, None


def _plan_to_items_list(plan, category_id=None):
    """Convert a RemovalPlan's items to JSON-serialisable dicts."""
    items = plan.by_category(category_id) if category_id else plan.items
    result = []
    for item in items:
        d = {
            "name": item.name,
            "category": item.category,
            "status": item.status,
            "detail": item.detail,
            "refs": item.refs,
        }
        # Include select data fields that are useful for the GUI
        if item.data:
            if "trainer_id" in item.data:
                d["trainer_id"] = item.data["trainer_id"]
            if "map_const" in item.data:
                d["map_const"] = item.data["map_const"]
            if "base_label" in item.data:
                d["base_label"] = item.data["base_label"]
            if "song_const" in item.data:
                d["song_const"] = item.data["song_const"]
            if "pic_const" in item.data:
                d["pic_const"] = item.data["pic_const"]
            if "tileset_name" in item.data:
                d["tileset_name"] = item.data["tileset_name"]
            if "path" in item.data:
                d["file_path"] = item.data["path"]
            if "labels" in item.data:
                d["labels"] = item.data["labels"]
        result.append(d)
    return result


def _plan_category_summary(plan):
    """Build category summary list from a RemovalPlan."""
    return plan.category_summary()


# Category -> writer function mapping
_CATEGORY_REMOVERS = {
    "maps": remove_maps,
    "trainers": remove_trainers,
    "encounters": remove_encounters,
    "frontier": remove_frontier,
    "scripts": remove_scripts,
    "tilesets": remove_tilesets,
    # graphics and music don't have file-level removal in Singe
}


# ---------------------------------------------------------------------------
# GET /api/scorch/status — Preflight check
# ---------------------------------------------------------------------------

@api_route("GET", "/api/scorch/status")
def handle_scorch_status(handler, match, query_params):
    """Check whether SCORCH can run on the active project."""
    game_path, err = _game_path(handler)
    if err:
        return err

    issues = []

    if not os.path.isdir(game_path):
        issues.append(f"Game path not found: {game_path}")
        return ok_response({"ready": False, "issues": issues})

    groups_file = os.path.join(game_path, "data", "maps", "map_groups.json")
    if not os.path.isfile(groups_file):
        issues.append("map_groups.json not found -- cannot detect vanilla maps")
    elif not has_sentinel(game_path):
        issues.append(
            "Vanilla map sentinel not found in map_groups.json. "
            "The project may already be scorched."
        )

    # Check for git uncommitted changes
    git_dir = os.path.join(game_path, ".git")
    if os.path.isdir(git_dir):
        try:
            import subprocess
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=game_path, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                n_changed = len(result.stdout.strip().splitlines())
                issues.append(
                    f"Git repo has {n_changed} uncommitted change(s) -- "
                    "consider committing before removing content"
                )
        except Exception:
            pass

    # Phoenix version warning
    try:
        from torch.expansion_compat import (
            detect_expansion_version, version_str, FRLG_BUILD,
        )
        version = detect_expansion_version(game_path)
        if version and version >= FRLG_BUILD:
            issues.append(
                f"Expansion v{version_str(version)} detected -- Phoenix is "
                "validated up to v1.14.x. v1.15.0+ may not build cleanly."
            )
    except Exception:
        pass

    return ok_response({
        "ready": len(issues) == 0 or all(
            "uncommitted" in i.lower() or "v1.15" in i for i in issues
        ),
        "issues": issues,
    })


# ---------------------------------------------------------------------------
# GET /api/scorch/scan — Full scan (all categories)
# ---------------------------------------------------------------------------

@api_route("GET", "/api/scorch/scan")
def handle_scorch_scan(handler, match, query_params):
    """Run a full SCORCH scan and return summary + items for all categories."""
    game_path, err = _game_path(handler)
    if err:
        return err

    try:
        plan = full_scan(game_path)
    except Exception as e:
        return error_response(f"Scan failed: {e}", 500)

    summary = _plan_category_summary(plan)
    items = _plan_to_items_list(plan)

    return ok_response({
        "categories": summary,
        "items": items,
        "scan_errors": plan.scan_errors,
        "total_safe": plan.total_safe(),
        "total_blocked": len(plan.blocked_items()),
    })


# ---------------------------------------------------------------------------
# GET /api/scorch/scan/<category> — Single category scan
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/scorch/scan/(?P<category>[a-z]+)")
def handle_scorch_scan_category(handler, match, query_params):
    """Scan a single SCORCH category."""
    game_path, err = _game_path(handler)
    if err:
        return err

    category = match.group("category")
    if category not in CATEGORY_IDS:
        return error_response(
            f"Unknown category: {category}. "
            f"Valid: {', '.join(CATEGORY_IDS)}",
            400,
        )

    try:
        plan = scan_category(game_path, category)
    except Exception as e:
        return error_response(f"Scan failed: {e}", 500)

    items = _plan_to_items_list(plan, category)
    safe_count = len([i for i in items if i["status"] == SAFE])
    blocked_count = len([i for i in items if i["status"] == BLOCKED])

    # Find category label
    label = category
    for cat in CATEGORIES:
        if cat["id"] == category:
            label = cat["label"]
            break

    return ok_response({
        "category": category,
        "label": label,
        "items": items,
        "total": len(items),
        "safe": safe_count,
        "blocked": blocked_count,
        "scan_errors": plan.scan_errors,
    })


# ---------------------------------------------------------------------------
# POST /api/scorch/remove — Execute selective removal
# ---------------------------------------------------------------------------

@api_route("POST", "/api/scorch/remove")
def handle_scorch_remove(handler, match, query_params):
    """Remove selected SAFE items from a category.

    Body: {category: str, items: [str]}
    Each item in the list is the item name (e.g. map name, trainer const).
    Creates a snapshot automatically before removal.
    """
    game_path, err = _game_path(handler)
    if err:
        return err

    body = _read_json_body(handler)
    if not body or not isinstance(body, dict):
        return error_response("Request body must be a JSON object", 400)

    category = (body.get("category") or "").strip()
    item_names = body.get("items", [])
    confirm = (body.get("confirm") or "").strip()

    if not category:
        return error_response("Missing 'category' field", 400)
    if category not in CATEGORY_IDS:
        return error_response(f"Unknown category: {category}", 400)
    if not item_names or not isinstance(item_names, list):
        return error_response("Missing or empty 'items' list", 400)
    if confirm.lower() != category.lower():
        return error_response(
            f"Confirmation mismatch: expected '{category}'", 400
        )

    remover = _CATEGORY_REMOVERS.get(category)
    if not remover:
        return error_response(
            f"Category '{category}' does not support selective removal", 400
        )

    # Re-scan the category to get current state
    try:
        plan = scan_category(game_path, category)
    except Exception as e:
        return error_response(f"Re-scan failed: {e}", 500)

    # Build a filtered plan with only the requested SAFE items
    requested = set(item_names)
    selected_items = []
    blocked_requested = []

    for item in plan.items:
        if item.name not in requested:
            continue
        if item.status != SAFE:
            blocked_requested.append(item.name)
        else:
            selected_items.append(item)

    if blocked_requested:
        return error_response(
            f"Cannot remove BLOCKED items: {', '.join(blocked_requested[:5])}"
            + (f" (and {len(blocked_requested) - 5} more)"
               if len(blocked_requested) > 5 else ""),
            400,
        )

    if not selected_items:
        return error_response("No valid items to remove", 400)

    # Create snapshot before removal
    snapshot_plan = RemovalPlan()
    snapshot_plan.items = selected_items
    try:
        snapshot_path = _create_cleanup_snapshot(
            game_path, snapshot_plan, category_hint=category
        )
    except Exception as e:
        return error_response(f"Snapshot failed: {e}", 500)

    if snapshot_path is None:
        return error_response("Failed to create safety snapshot", 500)

    # Execute removal
    try:
        removed_count, errors = remover(game_path, selected_items)
    except Exception as e:
        return error_response(f"Removal failed: {e}", 500)

    snapshot_name = ""
    if snapshot_path and snapshot_path != "skip":
        snapshot_name = os.path.basename(snapshot_path)

    return ok_response({
        "removed_count": removed_count,
        "errors": errors,
        "snapshot": snapshot_name,
        "category": category,
    })


# ---------------------------------------------------------------------------
# GET /api/scorch/snapshots — List SCORCH snapshots
# ---------------------------------------------------------------------------

@api_route("GET", "/api/scorch/snapshots")
def handle_scorch_snapshots(handler, match, query_params):
    """List all SCORCH snapshots (Singe + Phoenix) available for restore."""
    game_path, err = _game_path(handler)
    if err:
        return err

    # Singe snapshots (backups/cleanup/)
    singe_snapshots = []
    try:
        singe_snapshots = _list_cleanup_snapshots(game_path)
    except Exception:
        pass

    # Phoenix snapshots (backups/scorch/)
    phoenix_snapshots = []
    try:
        from torch.scorch_writer import list_scorch_snapshots
        phoenix_snapshots = list_scorch_snapshots(game_path)
    except Exception:
        pass

    # Combine and tag with source type
    all_snapshots = []
    for s in singe_snapshots:
        all_snapshots.append({
            "path": s["path"],
            "filename": s["filename"],
            "display_time": s["display_time"],
            "category_hint": s.get("category_hint", ""),
            "type": "singe",
        })
    for s in phoenix_snapshots:
        all_snapshots.append({
            "path": s["path"],
            "filename": s["filename"],
            "display_time": s["display_time"],
            "type": "phoenix",
        })

    # Sort newest first by filename (timestamps are in the filename)
    all_snapshots.sort(key=lambda s: s["filename"], reverse=True)

    return ok_response({"snapshots": all_snapshots})


# ---------------------------------------------------------------------------
# POST /api/scorch/restore — Restore from a snapshot
# ---------------------------------------------------------------------------

@api_route("POST", "/api/scorch/restore")
def handle_scorch_restore(handler, match, query_params):
    """Restore from a SCORCH snapshot.

    Body: {path: str, type: "singe"|"phoenix"}
    """
    game_path, err = _game_path(handler)
    if err:
        return err

    body = _read_json_body(handler)
    if not body or not isinstance(body, dict):
        return error_response("Request body must be a JSON object", 400)

    snapshot_path = (body.get("path") or "").strip()
    snap_type = (body.get("type") or "singe").strip()

    if not snapshot_path:
        return error_response("Missing 'path' field", 400)

    # Safety: verify path is within the game's backups directory
    backups_base = os.path.join(game_path, "backups")
    real_snap = os.path.realpath(snapshot_path)
    real_base = os.path.realpath(backups_base)
    if not real_snap.startswith(real_base + os.sep):
        return error_response("Snapshot path must be within game backups", 400)

    if not os.path.isfile(snapshot_path):
        return error_response("Snapshot file not found", 404)

    try:
        if snap_type == "phoenix":
            from torch.scorch_writer import restore_scorch_snapshot
            restored = restore_scorch_snapshot(game_path, snapshot_path)
        else:
            restored = _restore_cleanup_snapshot(game_path, snapshot_path)
    except Exception as e:
        return error_response(f"Restore failed: {e}", 500)

    if restored is None:
        return error_response("Restore failed (unknown error)", 500)

    return ok_response({
        "restored_count": len(restored),
        "type": snap_type,
    })


# ---------------------------------------------------------------------------
# GET /api/scorch/phoenix/plan — Preview Phoenix removal
# ---------------------------------------------------------------------------

@api_route("GET", "/api/scorch/phoenix/plan")
def handle_phoenix_plan(handler, match, query_params):
    """Build and return a Phoenix plan summary (dry run)."""
    game_path, err = _game_path(handler)
    if err:
        return err

    try:
        from torch.scorch_scanner import build_scorch_plan
        plan = build_scorch_plan(game_path)
    except Exception as e:
        return error_response(f"Phoenix scan failed: {e}", 500)

    if plan.errors:
        return ok_response({
            "errors": plan.errors,
            "summary": {},
            "ready": False,
        })

    summary = plan.summary()

    # Convert to serialisable format
    summary_data = {}
    for cat_id, (nuke, keep) in summary.items():
        summary_data[cat_id] = {"nuke": nuke, "keep": keep}

    return ok_response({
        "summary": summary_data,
        "errors": plan.errors,
        "ready": len(plan.errors) == 0,
        "nuke_maps_sample": sorted(list(plan.nuke_maps))[:20],
        "keep_maps": sorted(list(plan.keep_maps)),
    })


# ---------------------------------------------------------------------------
# POST /api/scorch/phoenix/execute — Execute Phoenix
# ---------------------------------------------------------------------------

@api_route("POST", "/api/scorch/phoenix/execute")
def handle_phoenix_execute(handler, match, query_params):
    """Execute SCORCH Phoenix (total vanilla removal).

    Body: {confirm: str}
    The confirm field must match the project name exactly.
    """
    game_path, err = _game_path(handler)
    if err:
        return err

    body = _read_json_body(handler)
    if not body or not isinstance(body, dict):
        return error_response("Request body must be a JSON object", 400)

    # Require project name as confirmation token
    proj_name = getattr(handler.server, "proj_name", "")
    confirm = (body.get("confirm") or "").strip()

    if not confirm:
        return error_response("Missing 'confirm' field (project name)", 400)
    if confirm.lower() != proj_name.lower():
        return error_response(
            f"Confirmation mismatch: expected '{proj_name}'", 400
        )

    # Build plan
    try:
        from torch.scorch_scanner import build_scorch_plan
        plan = build_scorch_plan(game_path)
    except Exception as e:
        return error_response(f"Phoenix scan failed: {e}", 500)

    if plan.errors:
        return error_response(
            f"Phoenix plan has errors: {'; '.join(plan.errors)}", 400
        )

    # Create snapshot
    try:
        from torch.scorch_writer import create_scorch_snapshot
        snapshot_path = create_scorch_snapshot(game_path, plan)
    except Exception as e:
        return error_response(f"Snapshot failed: {e}", 500)

    if not snapshot_path:
        return error_response("Failed to create safety snapshot", 500)

    # Execute scorch
    try:
        from torch.scorch_writer import execute_scorch
        scorch_result = execute_scorch(game_path, plan)
    except Exception as e:
        return error_response(f"Phoenix execution failed: {e}", 500)

    # Apply patches
    patch_count = 0
    patch_errors = []
    try:
        from torch.scorch_patcher import apply_patches
        patch_report = apply_patches(game_path, plan)
        patch_count = len(patch_report.patches)
        patch_errors = patch_report.errors
    except Exception as e:
        patch_errors = [f"Patching failed: {e}"]

    return ok_response({
        "maps_removed": scorch_result.maps_removed,
        "layouts_removed": scorch_result.layouts_removed,
        "trainers_removed": scorch_result.trainers_removed,
        "encounters_removed": scorch_result.encounters_removed,
        "scripts_removed": scorch_result.scripts_removed,
        "tilesets_removed": scorch_result.tilesets_removed,
        "mapsecs_removed": scorch_result.mapsecs_removed,
        "patches_applied": patch_count,
        "errors": scorch_result.errors + patch_errors,
        "snapshot": os.path.basename(snapshot_path),
    })
