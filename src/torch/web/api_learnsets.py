# TORCH_MODULE: Web API Learnsets
# TORCH_GROUP: Web
"""Learnset editor API endpoints for the TORCH web GUI.

GET  /api/learnsets/<species_const>          — all learnsets for a species
POST /api/learnsets/<species_const>/level_up  — save modified level-up learnset
POST /api/learnsets/<species_const>/egg       — save modified egg moves
"""

import re

from torch.web.api import api_route, ok_response, error_response, _read_json_body
from torch.gamedata import (
    load_level_up_learnset,
    load_egg_moves,
    load_teachable_learnset,
    load_move_names,
    clear_gamedata_cache,
)
from torch.learnset_editor import (
    _species_to_array_name,
    _write_level_up_learnset,
    _write_egg_moves,
)
from torch.expansion_compat import (
    detect_expansion_version,
    requires_version,
    MOVESET_REFACTOR,
)

_SPECIES_RE = re.compile(r'^SPECIES_[A-Z][A-Z0-9_]*$')
_MOVE_RE = re.compile(r'^MOVE_[A-Z][A-Z0-9_]*$')


def _validate_species(species_const):
    """Validate a species constant string."""
    return bool(_SPECIES_RE.match(species_const))


def _validate_move(move_const):
    """Validate a move constant string."""
    return bool(_MOVE_RE.match(move_const))


def _get_game_path(handler):
    """Extract game_path from the server, or return an error response."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return None, error_response("No game path configured", 500)
    version = detect_expansion_version(game_path)
    if version is None:
        return None, error_response(
            "Learnset editor requires pokeemerald-expansion", 400
        )
    return game_path, None


def _move_name(move_const, names_map):
    """Get display name for a move constant."""
    return names_map.get(move_const, move_const.replace("MOVE_", "").replace("_", " ").title())


# ---------------------------------------------------------------------------
# GET /api/learnsets/<species_const>
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/learnsets/(?P<species>[A-Z][A-Z0-9_]+)")
def handle_learnset_get(handler, match, query_params):
    """Return all learnsets for a species."""
    species_const = match.group("species")
    if not _validate_species(species_const):
        return error_response("Invalid species constant", 400)

    game_path, err = _get_game_path(handler)
    if err:
        return err

    names = load_move_names(game_path)
    version = detect_expansion_version(game_path)
    teachable_available = requires_version(version, MOVESET_REFACTOR)

    level_up_raw = load_level_up_learnset(game_path, species_const)
    egg_raw = load_egg_moves(game_path, species_const)
    teachable_raw = load_teachable_learnset(game_path, species_const) if teachable_available else []

    level_up = [
        {"level": lv, "move": mv, "name": _move_name(mv, names)}
        for lv, mv in level_up_raw
    ]
    egg = [
        {"move": mv, "name": _move_name(mv, names)}
        for mv in egg_raw
    ]
    teachable = [
        {"move": mv, "name": _move_name(mv, names)}
        for mv in teachable_raw
    ]

    return ok_response({
        "species": species_const,
        "level_up": level_up,
        "egg": egg,
        "teachable": teachable,
        "teachable_available": teachable_available,
        "editable": {
            "level_up": True,
            "egg": True,
            "teachable": False,
        },
    })


# ---------------------------------------------------------------------------
# POST /api/learnsets/<species_const>/level_up
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/learnsets/(?P<species>[A-Z][A-Z0-9_]+)/level_up")
def handle_learnset_level_up_save(handler, match, query_params):
    """Save modified level-up learnset."""
    species_const = match.group("species")
    if not _validate_species(species_const):
        return error_response("Invalid species constant", 400)

    game_path, err = _get_game_path(handler)
    if err:
        return err

    try:
        body = _read_json_body(handler)
    except (ValueError,):
        return error_response("Invalid JSON body", 400)

    if not body or "moves" not in body:
        return error_response("Missing 'moves' in request body", 400)

    raw_moves = body["moves"]
    if not isinstance(raw_moves, list):
        return error_response("'moves' must be an array", 400)

    validated = []
    for i, entry in enumerate(raw_moves):
        if not isinstance(entry, dict):
            return error_response(f"Move entry {i} must be an object", 400)
        level = entry.get("level")
        move = entry.get("move", "")
        if not isinstance(level, int) or level < 1 or level > 100:
            return error_response(
                f"Move entry {i}: level must be 1-100, got {level!r}", 400
            )
        if not _validate_move(move):
            return error_response(
                f"Move entry {i}: invalid move constant {move!r}", 400
            )
        validated.append((level, move))

    species_name = _species_to_array_name(species_const)
    success = _write_level_up_learnset(game_path, species_name, validated)
    if not success:
        return error_response(
            f"Failed to write level-up learnset for {species_const}", 500
        )

    # Invalidate cached learnset data so next read picks up edits
    clear_gamedata_cache()

    return ok_response({"saved": True, "count": len(validated)})


# ---------------------------------------------------------------------------
# POST /api/learnsets/<species_const>/egg
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/learnsets/(?P<species>[A-Z][A-Z0-9_]+)/egg")
def handle_learnset_egg_save(handler, match, query_params):
    """Save modified egg moves."""
    species_const = match.group("species")
    if not _validate_species(species_const):
        return error_response("Invalid species constant", 400)

    game_path, err = _get_game_path(handler)
    if err:
        return err

    try:
        body = _read_json_body(handler)
    except (ValueError,):
        return error_response("Invalid JSON body", 400)

    if not body or "moves" not in body:
        return error_response("Missing 'moves' in request body", 400)

    raw_moves = body["moves"]
    if not isinstance(raw_moves, list):
        return error_response("'moves' must be an array", 400)

    validated = []
    for i, mv in enumerate(raw_moves):
        if not isinstance(mv, str) or not _validate_move(mv):
            return error_response(
                f"Move entry {i}: invalid move constant {mv!r}", 400
            )
        validated.append(mv)

    species_name = _species_to_array_name(species_const)
    success = _write_egg_moves(game_path, species_name, validated)
    if not success:
        return error_response(
            f"Failed to write egg moves for {species_const}", 500
        )

    clear_gamedata_cache()

    return ok_response({"saved": True, "count": len(validated)})
