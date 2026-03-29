# TORCH_MODULE: Web API — Items
# TORCH_GROUP: Web
"""Item Editor API endpoints for the TORCH web GUI.

Provides browse, detail, edit, and hold-effects list endpoints.
Delegates to torch.item_editor for parsing and write-back.
"""

import json
import os

from torch.web.api import api_route, ok_response, error_response, _read_json_body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_game_path(handler):
    """Return game_path from server, or None."""
    return getattr(handler.server, "game_path", "") or None


def _check_expansion(game_path):
    """Return error_response if items.h is missing, else None."""
    items_h = os.path.join(game_path, "src", "data", "items.h")
    if not os.path.isfile(items_h):
        return error_response(
            "Item editor requires pokeemerald-expansion", 400
        )
    return None


def _item_to_dict(item):
    """Convert an item dict to the API response format (strip internal keys)."""
    return {
        "constant": item["constant"],
        "id": item["id"],
        "name": item["name"],
        "price": item["price"],
        "price_display": item["price_display"],
        "description": item["description"],
        "pocket": item["pocket"],
        "sort_type": item["sort_type"],
        "hold_effect": item["hold_effect"],
        "hold_effect_param": item["hold_effect_param"],
        "fling_power": item["fling_power"],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_FIELDS = {
    "name", "price", "description", "pocket",
    "sort_type", "hold_effect", "hold_effect_param", "fling_power",
}


def _validate_string(value, label, max_len=None, required=False):
    """Validate a string field. Returns error or None."""
    if not isinstance(value, str):
        return f"{label} must be a string"
    if required and not value.strip():
        return f"{label} must be non-empty"
    if max_len and len(value) > max_len:
        return f"{label} must be {max_len} characters or fewer"
    return None


def _validate_int_range(value, label, min_val, max_val):
    """Validate an integer field within a range. Returns error or None."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return f"{label} must be an integer"
    if n < min_val or n > max_val:
        return f"{label} must be {min_val}-{max_val}"
    return None


def _validate_enum(value, label, allowed):
    """Validate value is in an allowed set. Returns error or None."""
    if value not in allowed:
        return f"Invalid {label}: {value}"
    return None


def _validate_edit(field, value, pockets, sort_types):
    """Validate a field edit. Returns error string or None."""
    if field not in _VALID_FIELDS:
        return f"Unknown field: {field}"

    validators = {
        "name":              lambda v: _validate_string(v, "Name", 19, True),
        "price":             lambda v: None if str(v).strip().isdigit()
                             else "Price must be a non-negative integer",
        "description":       lambda v: _validate_string(v, "Description"),
        "pocket":            lambda v: _validate_enum(v, "pocket", pockets),
        "sort_type":         lambda v: _validate_enum(v, "sort type", sort_types),
        "hold_effect":       lambda v: _validate_string(v, "Hold effect"),
        "hold_effect_param": lambda v: _validate_int_range(v, "hold_effect_param", 0, 255),
        "fling_power":       lambda v: _validate_int_range(v, "fling_power", 0, 150),
    }

    validator = validators.get(field)
    return validator(value) if validator else None


# ---------------------------------------------------------------------------
# GET /api/items/browse — full item list for the editor
# ---------------------------------------------------------------------------

@api_route("GET", "/api/items/browse")
def handle_items_browse(handler, match, query_params):
    """Return all items with full fields for the item editor view."""
    game_path = _get_game_path(handler)
    if not game_path:
        return error_response("No game path configured", 500)

    err = _check_expansion(game_path)
    if err:
        return err

    from torch.item_editor import parse_items, _POCKETS, _SORT_TYPES

    items = parse_items(game_path)

    # Optional search filter
    q = query_params.get("q", [""])[0].strip().lower()
    if q:
        items = [it for it in items
                 if q in it["name"].lower() or q in it["constant"].lower()]

    return ok_response({
        "items": [_item_to_dict(it) for it in items],
        "pockets": list(_POCKETS),
        "sort_types": list(_SORT_TYPES),
    })


# ---------------------------------------------------------------------------
# GET /api/items/browse/<constant> — single item detail
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/items/browse/(?P<constant>ITEM_[A-Za-z0-9_]+)")
def handle_item_detail(handler, match, query_params):
    """Return a single item by constant name."""
    game_path = _get_game_path(handler)
    if not game_path:
        return error_response("No game path configured", 500)

    err = _check_expansion(game_path)
    if err:
        return err

    constant = match.group("constant")

    from torch.item_editor import parse_items

    items = parse_items(game_path)
    for item in items:
        if item["constant"] == constant:
            return ok_response({"item": _item_to_dict(item)})

    return error_response(f"Item not found: {constant}", 404)


# ---------------------------------------------------------------------------
# POST /api/items/browse/<constant> — edit a single field
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/items/browse/(?P<constant>ITEM_[A-Za-z0-9_]+)")
def handle_item_edit(handler, match, query_params):
    """Edit a single field on an item."""
    game_path = _get_game_path(handler)
    if not game_path:
        return error_response("No game path configured", 500)

    err = _check_expansion(game_path)
    if err:
        return err

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if body is None:
        return error_response("Request body required", 400)

    field = body.get("field")
    value = body.get("value")
    if not field:
        return error_response("Missing 'field' in request body", 400)

    constant = match.group("constant")

    from torch.item_editor import parse_items, _write_field, _POCKETS, _SORT_TYPES

    # Validate
    val_err = _validate_edit(field, value, _POCKETS, _SORT_TYPES)
    if val_err:
        return error_response(val_err, 400)

    # Find the item
    items = parse_items(game_path)
    target = None
    for item in items:
        if item["constant"] == constant:
            target = item
            break
    if target is None:
        return error_response(f"Item not found: {constant}", 404)

    # Coerce numeric fields
    write_value = value
    if field in ("hold_effect_param", "fling_power"):
        write_value = str(int(value))
    elif field == "price":
        write_value = str(value).strip()

    # Write
    ok = _write_field(game_path, target, field, write_value)
    if not ok:
        return error_response("Failed to write field", 500)

    # Re-read and return updated item
    items = parse_items(game_path)
    for item in items:
        if item["constant"] == constant:
            return ok_response({"item": _item_to_dict(item)})

    return ok_response({"item": _item_to_dict(target)})


# ---------------------------------------------------------------------------
# GET /api/items/hold-effects — list available hold effects
# ---------------------------------------------------------------------------

@api_route("GET", "/api/items/hold-effects")
def handle_hold_effects(handler, match, query_params):
    """Return available hold effect constants."""
    game_path = _get_game_path(handler)
    if not game_path:
        return error_response("No game path configured", 500)

    err = _check_expansion(game_path)
    if err:
        return err

    from torch.item_editor import _load_hold_effects

    effects = _load_hold_effects(game_path)
    return ok_response({"effects": effects})
