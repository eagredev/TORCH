# TORCH_MODULE: Move API
# TORCH_GROUP: Web
"""API endpoints for the TORCH Move Editor web view.

Provides browse, detail, and edit endpoints for game moves.
Routes are registered via the shared api_route decorator from torch.web.api.
"""

import json
import os

from torch.web.api import (
    api_route,
    ok_response,
    error_response,
    _read_json_body,
)
from torch.move_editor import (
    parse_moves,
    _moves_h_path,
    _write_field,
    _type_label,
    _category_label,
    _target_label,
    _TYPES,
    _CATEGORIES,
    _TARGETS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_move(move):
    """Convert an internal move dict to the API response format.

    Strips internal-only fields (line_start, line_end) and adds
    display-friendly labels alongside raw constants.
    """
    return {
        "constant": move["constant"],
        "id": move["id"],
        "name": move["name"],
        "type": _type_label(move["type"]),
        "type_raw": move.get("type_raw", move["type"]),
        "category": _category_label(move["category"]),
        "category_raw": move["category"],
        "power": move["power"],
        "power_raw": move.get("power_raw", str(move["power"])),
        "accuracy": move["accuracy"],
        "accuracy_raw": move.get("accuracy_raw", str(move["accuracy"])),
        "pp": move["pp"],
        "pp_raw": move.get("pp_raw", str(move["pp"])),
        "priority": move["priority"],
        "target": _target_label(move.get("target", "MOVE_TARGET_SELECTED")),
        "target_raw": move.get("target_raw", move.get("target", "MOVE_TARGET_SELECTED")),
        "effect": move.get("effect", ""),
        "description": move.get("description", ""),
        "flags": move.get("flags", []),
        "has_additional_effects": move.get("has_additional_effects", False),
    }


def _find_move(moves, constant):
    """Find a move by its constant name. Returns (move, index) or (None, -1)."""
    for i, mv in enumerate(moves):
        if mv["constant"] == constant:
            return mv, i
    return None, -1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_FIELD_VALIDATORS = {
    "name": lambda v: (isinstance(v, str) and 0 < len(v) <= 16,
                       "Name must be 1-16 characters"),
    "power": lambda v: (_is_int_in_range(v, 0, 250),
                        "Power must be 0-250"),
    "accuracy": lambda v: (_is_int_in_range(v, 0, 100),
                           "Accuracy must be 0-100"),
    "pp": lambda v: (_is_int_in_range(v, 1, 40),
                     "PP must be 1-40"),
    "priority": lambda v: (_is_int_in_range(v, -7, 5),
                           "Priority must be -7 to 5"),
    "type": lambda v: (isinstance(v, str) and v in _TYPES,
                       f"Type must be one of: {', '.join(_TYPES)}"),
    "category": lambda v: (isinstance(v, str) and v in _CATEGORIES,
                           f"Category must be one of: {', '.join(_CATEGORIES)}"),
    "target": lambda v: (isinstance(v, str) and v in _TARGETS,
                         f"Target must be one of: {', '.join(_TARGETS)}"),
    "description": lambda v: (isinstance(v, str) and len(v) <= 200,
                              "Description must be a string (max 200 chars)"),
}

_VALID_FIELDS = set(_FIELD_VALIDATORS.keys())


def _is_int_in_range(v, lo, hi):
    """Check if v (string) represents an integer in [lo, hi]."""
    if not isinstance(v, str):
        return False
    try:
        n = int(v)
    except ValueError:
        return False
    return lo <= n <= hi


def _validate_edit(field, value):
    """Validate a field edit. Returns (ok, error_message)."""
    validator = _FIELD_VALIDATORS.get(field)
    if not validator:
        return False, f"Unknown field: {field}. Valid: {', '.join(sorted(_VALID_FIELDS))}"
    ok, msg = validator(value)
    return ok, msg


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", "/api/moves/browse")
def handle_moves_browse(handler, match, query_params):
    """Return all moves with full parsed fields."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    moves_path = _moves_h_path(game_path)
    if not os.path.isfile(moves_path):
        return error_response("Move data file not found. Requires pokeemerald-expansion.", 404)

    moves = parse_moves(game_path)

    # Optional search filter
    q = query_params.get("q", [""])[0].strip().lower()
    if q:
        moves = [mv for mv in moves
                 if q in mv["name"].lower()
                 or q in mv["constant"].lower()
                 or q in _type_label(mv["type"]).lower()]

    serialized = [_serialize_move(mv) for mv in moves]

    return ok_response({
        "moves": serialized,
        "types": list(_TYPES),
        "categories": list(_CATEGORIES),
        "targets": list(_TARGETS),
    })


@api_route("GET", r"/api/moves/browse/(?P<constant>MOVE_[A-Z0-9_]+)")
def handle_move_detail(handler, match, query_params):
    """Return a single move by constant name."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    constant = match.group("constant")
    moves = parse_moves(game_path)
    move, _ = _find_move(moves, constant)

    if not move:
        return error_response(f"Move not found: {constant}", 404)

    return ok_response(_serialize_move(move))


@api_route("POST", r"/api/moves/browse/(?P<constant>MOVE_[A-Z0-9_]+)")
def handle_move_edit(handler, match, query_params):
    """Edit a single field on a move."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    constant = match.group("constant")

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if body is None:
        return error_response("Request body required", 400)

    field = body.get("field")
    value = body.get("value")

    if not field or not isinstance(field, str):
        return error_response("'field' is required and must be a string", 400)
    if value is None:
        return error_response("'value' is required", 400)
    value = str(value)

    # Validate field and value
    ok, msg = _validate_edit(field, value)
    if not ok:
        return error_response(msg, 400)

    # Parse moves to get line info
    moves = parse_moves(game_path)
    move, _ = _find_move(moves, constant)
    if not move:
        return error_response(f"Move not found: {constant}", 404)

    # Write the field
    success = _write_field(game_path, move, field, value)
    if not success:
        return error_response(f"Failed to write field '{field}'", 500)

    # Re-parse to get updated data
    moves = parse_moves(game_path)
    updated, _ = _find_move(moves, constant)
    if not updated:
        return error_response("Move saved but re-parse failed", 500)

    return ok_response(_serialize_move(updated))
