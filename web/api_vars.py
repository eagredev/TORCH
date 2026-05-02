# TORCH_MODULE: Web API — Variables
# TORCH_GROUP: Web
"""Variable browser API endpoints for the TORCH web GUI.

Provides list and cross-reference endpoints for game variables.
Backed by var_scanner.py.

Routes are registered via the shared api_route decorator.
"""

import re

from torch.web.api import (
    api_route, ok_response, error_response,
)
from torch.var_scanner import (
    parse_vars_h, count_free_var_slots, scan_var_references,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_hex_value(value_str):
    """Try to resolve a value string to an int for sorting."""
    s = value_str.strip()
    try:
        return int(s, 0)
    except (ValueError, TypeError):
        pass
    m = re.search(r"0x[0-9A-Fa-f]+$", s)
    if m:
        try:
            return int(m.group(), 16)
        except ValueError:
            pass
    # Try to resolve expressions like (TEMP_VARS_START + 0xA)
    m = re.search(r"\+\s*(0x[0-9A-Fa-f]+)", s)
    if m:
        try:
            return int(m.group(1), 16)
        except ValueError:
            pass
    return 0


def _classify_var(name, is_unused, section):
    """Determine variable type label."""
    if is_unused:
        return "free"
    if section == "temp":
        return "temp"
    if section == "graphics":
        return "graphics"
    if section == "special":
        return "special"
    return "persistent"


def _build_var_list(parsed):
    """Build a flat list of variable dicts from parsed vars.h data.

    Returns (vars_list, stats_dict).
    """
    variables = []
    stats = {"total": 0, "temp": 0, "graphics": 0, "persistent": 0,
             "special": 0, "free": 0}

    for section_name in ("temp", "graphics", "persistent", "special"):
        for name, val, comment, is_unused in parsed.get(section_name, []):
            vtype = _classify_var(name, is_unused, section_name)
            variables.append({
                "name": name,
                "value": val,
                "comment": comment,
                "type": vtype,
                "section": section_name,
                "_sort_key": _resolve_hex_value(val),
            })
            stats["total"] += 1
            stats[vtype] += 1

    variables.sort(key=lambda v: v["_sort_key"])
    for v in variables:
        del v["_sort_key"]

    return variables, stats


# ---------------------------------------------------------------------------
# GET /api/vars — List all variables with metadata
# ---------------------------------------------------------------------------

@api_route("GET", "/api/vars")
def handle_vars_list(handler, match, query_params):
    """Return all variables from vars.h with type classification and stats."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    parsed = parse_vars_h(game_path)
    variables, stats = _build_var_list(parsed)

    free_count, total_persistent = count_free_var_slots(game_path)
    stats["free_persistent"] = free_count
    stats["total_persistent"] = total_persistent

    return ok_response({
        "vars": variables,
        "stats": stats,
    })


# ---------------------------------------------------------------------------
# GET /api/vars/<var_name>/references — Cross-reference scan
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/vars/(?P<var_name>VAR_[A-Za-z0-9_]+)/references")
def handle_var_references(handler, match, query_params):
    """Return cross-references for a single variable."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    var_name = match.group("var_name")
    refs = scan_var_references(var_name, game_path)

    return ok_response({
        "var": var_name,
        "references": refs,
        "count": len(refs),
    })
