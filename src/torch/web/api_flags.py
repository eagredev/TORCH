# TORCH_MODULE: Web API — Flags
# TORCH_GROUP: Web
"""Flag browser API endpoints for the TORCH web GUI.

Provides list, detail (cross-reference), create, and delete endpoints
for game flags.  Backed by flag_scanner.py and pickers.py.

Routes are registered via the shared api_route decorator so they merge
into the global route list automatically once this module is imported.
"""

import os
import re

from torch.web.api import (
    api_route, ok_response, error_response, _read_json_body, _safe_path,
)
from torch.flag_scanner import (
    parse_flags_h, count_free_slots, scan_flag_references,
    delete_flag_from_header,
)
from torch.gamedata import HEADER_FLAGS, clear_gamedata_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_flag(name, alias_names, aliased_targets, is_unused):
    """Determine flag type: custom, free, or event."""
    if name in alias_names:
        return "custom"
    if is_unused and name not in aliased_targets:
        return "free"
    return "event"


def _resolve_hex_value(value_str):
    """Try to resolve a value string to an int for sorting.

    Handles plain hex (0x820), decimal, and expressions like
    (TRAINER_FLAGS_START + 0x...).  Returns 0 on failure.
    """
    s = value_str.strip()
    try:
        return int(s, 0)
    except (ValueError, TypeError):
        pass
    # Try extracting a trailing hex/decimal from an expression
    m = re.search(r"0x[0-9A-Fa-f]+$", s)
    if m:
        try:
            return int(m.group(), 16)
        except ValueError:
            pass
    return 0


def _build_flag_list(parsed):
    """Build a flat list of flag dicts from parsed flags.h data.

    Returns (flags_list, stats_dict).
    """
    alias_names = {alias for alias, _ in parsed["custom_aliases"]}
    aliased_targets = {target for _, target in parsed["custom_aliases"]}

    flags = []
    stats = {"total": 0, "custom": 0, "event": 0, "free": 0}

    for name, val, comment, is_unused in parsed["event"]:
        ftype = _classify_flag(name, alias_names, aliased_targets, is_unused)

        # Skip FLAG_UNUSED slots that are claimed by custom aliases
        if is_unused and name in aliased_targets:
            continue

        flags.append({
            "name": name,
            "value": val,
            "comment": comment,
            "type": ftype,
            "_sort_key": _resolve_hex_value(val),
        })
        stats["total"] += 1
        stats[ftype] += 1

    # Sort by hex value ascending
    flags.sort(key=lambda f: f["_sort_key"])

    # Strip internal sort key
    for f in flags:
        del f["_sort_key"]

    return flags, stats


# ---------------------------------------------------------------------------
# GET /api/flags — List all flags with metadata
# ---------------------------------------------------------------------------

@api_route("GET", "/api/flags")
def handle_flags_list(handler, match, query_params):
    """Return all flags from flags.h with type classification and stats."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    parsed = parse_flags_h(game_path)
    flags, stats = _build_flag_list(parsed)

    return ok_response({
        "flags": flags,
        "stats": stats,
    })


# ---------------------------------------------------------------------------
# GET /api/flags/<flag_name>/references — Cross-reference scan
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/flags/(?P<flag_name>FLAG_[A-Za-z0-9_]+)/references")
def handle_flag_references(handler, match, query_params):
    """Return cross-references for a single flag."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    flag_name = match.group("flag_name")
    refs = scan_flag_references(flag_name, game_path)

    return ok_response({
        "flag": flag_name,
        "references": refs,
        "count": len(refs),
    })


# ---------------------------------------------------------------------------
# POST /api/flags — Create a new custom flag
# ---------------------------------------------------------------------------

_FLAG_NAME_RE = re.compile(r"^FLAG_[A-Z][A-Z0-9_]*$")


def _validate_create_request(body, lines):
    """Validate a flag creation request.

    Returns (flag_name, target, error_msg).  error_msg is None on success.
    """
    if not body or not isinstance(body, dict):
        return None, None, "Request body must be a JSON object"

    name = body.get("name", "").strip()
    if not name:
        return None, None, "Missing 'name' field"

    # Auto-prepend FLAG_ if missing
    if not name.startswith("FLAG_"):
        name = "FLAG_" + name
    name = name.upper()

    if not _FLAG_NAME_RE.match(name):
        return None, None, "Name must be FLAG_ followed by uppercase alphanumeric/underscores"

    # Check for duplicates
    define_pat = re.compile(r"^#define\s+" + re.escape(name) + r"\s")
    for line in lines:
        if define_pat.match(line):
            return None, None, f"{name} already exists in flags.h"

    target = body.get("target", "").strip() if body.get("target") else ""
    return name, target or None, None


@api_route("POST", "/api/flags")
def handle_flag_create(handler, match, query_params):
    """Create a new custom flag alias in flags.h."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    body = _read_json_body(handler)

    flags_h = os.path.join(game_path, HEADER_FLAGS)
    if not os.path.isfile(flags_h):
        return error_response("flags.h not found", 404)

    try:
        with open(flags_h, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        return error_response(f"Cannot read flags.h: {e}", 500)

    flag_name, target, err = _validate_create_request(body, lines)
    if err:
        return error_response(err, 400)

    # Resolve target
    if target:
        # Verify target exists and is unused
        if not re.match(r"^FLAG_UNUSED_0x[0-9A-Fa-f]+$", target):
            return error_response("Target must be a FLAG_UNUSED_0xXXX slot", 400)
        # Check target isn't already aliased
        alias_pat = re.compile(
            r"^#define\s+FLAG_\w+\s+" + re.escape(target) + r"(\s|$)"
        )
        for line in lines:
            m = alias_pat.match(line)
            if m:
                existing = line.split()[1]
                if existing != target:
                    return error_response(
                        f"{target} is already aliased by {existing}", 400
                    )
    else:
        # Auto-pick first free slot
        from torch.pickers import _find_next_unused_flag
        target = _find_next_unused_flag(lines)
        if not target:
            return error_response("No free flag slots remaining", 400)

    # Insert the define
    from torch.pickers import _insert_flag_define
    if not _insert_flag_define(flags_h, flag_name, target):
        return error_response("Failed to insert flag define", 500)

    clear_gamedata_cache()

    return ok_response({
        "created": flag_name,
        "target": target,
    })


# ---------------------------------------------------------------------------
# POST /api/flags/delete — Delete a custom flag
# ---------------------------------------------------------------------------

@api_route("POST", "/api/flags/delete")
def handle_flag_delete(handler, match, query_params):
    """Delete a custom flag alias from flags.h."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    body = _read_json_body(handler)
    if not body or not body.get("name"):
        return error_response("Missing 'name' field", 400)

    flag_name = body["name"].strip()

    # Only allow deletion of custom aliases, not pool entries or event flags
    if re.match(r"^FLAG_UNUSED_0x[0-9A-Fa-f]+$", flag_name):
        return error_response("Cannot delete pool entries (FLAG_UNUSED_*)", 400)

    # Verify it's actually a custom alias before deleting
    parsed = parse_flags_h(game_path)
    alias_names = {alias for alias, _ in parsed["custom_aliases"]}
    if flag_name not in alias_names:
        return error_response(
            f"{flag_name} is not a custom flag alias (only custom flags can be deleted)",
            400,
        )

    ok = delete_flag_from_header(game_path, flag_name)
    if not ok:
        return error_response(f"Failed to delete {flag_name}", 500)

    return ok_response({"deleted": flag_name})
