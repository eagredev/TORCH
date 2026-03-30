# TORCH_MODULE: Web API
# TORCH_GROUP: Web
"""JSON API framework for the TORCH web GUI.

Provides response helpers, route registration, and the initial /api/status
endpoint.
"""

import copy
import json
import os
import random
import re
import struct
import subprocess
import tempfile
import threading
import zlib
from datetime import datetime
from urllib.parse import parse_qs


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def ok_response(data):
    """Return a success envelope dict."""
    return {"ok": True, "data": data}


def error_response(message, status=400):
    """Return an error envelope dict with HTTP status."""
    return {"ok": False, "error": message, "_status": status}


# ---------------------------------------------------------------------------
# Path & file safety helpers
# ---------------------------------------------------------------------------

def _safe_path(base_dir, *parts):
    """Join path parts and verify result is within base_dir."""
    full = os.path.normpath(os.path.join(base_dir, *parts))
    base = os.path.normpath(base_dir)
    if not (full == base or full.startswith(base + os.sep)):
        raise ValueError(f"Path escapes base directory: {full}")
    return full


def _atomic_write(filepath, content, encoding="utf-8"):
    """Write content to filepath atomically via temp file + rename."""
    dir_path = os.path.dirname(filepath)
    fd, tmp = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, filepath)
    except:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Route registry
# ---------------------------------------------------------------------------

# Each entry: (method, compiled_regex, handler_function)
_API_ROUTES = []


def api_route(method, pattern):
    """Decorator to register an API route handler."""
    compiled = re.compile(f"^{pattern}$")
    def decorator(fn):
        _API_ROUTES.append((method, compiled, fn))
        return fn
    return decorator


def match_api_route(method, path):
    """Find a matching API route for the given method and path.

    Returns (pattern, handler, match_object) or None.
    """
    for route_method, regex, handler in _API_ROUTES:
        if route_method != method:
            continue
        m = regex.match(path)
        if m:
            return (regex, handler, m)
    return None


def handle_api_request(handler, api_handler, match, query_params):
    """Execute an API handler and send the JSON response.

    If the handler returns None, it has already written its own response
    (e.g. binary data like sprites).
    """
    try:
        result = api_handler(handler, match, query_params)
    except Exception as exc:
        import traceback; traceback.print_exc()
        result = error_response(f"Internal error: {type(exc).__name__}", 500)

    if result is None:
        return  # handler wrote its own response

    status = result.pop("_status", 200) if isinstance(result, dict) else 200
    body = json.dumps(result, ensure_ascii=False)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body.encode("utf-8"))))
    handler.end_headers()
    handler.wfile.write(body.encode("utf-8"))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", "/api/status")
def handle_status(handler, match, query_params):
    """Return project status information."""
    import torch

    server = handler.server
    proj_name = getattr(server, "proj_name", "Unknown")
    expansion_version = getattr(server, "expansion_version", None)

    # Count modules in the package
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    module_count = len([f for f in os.listdir(package_dir)
                        if f.endswith(".py") and not f.startswith("_")])

    # Enrolled / custom map counts
    enrolled_count = 0
    custom_count = 0
    project_dir = getattr(server, "project_dir", "")
    game_path = getattr(server, "game_path", "")
    try:
        from torch.registry import load_registry
        reg = load_registry(project_dir)
        enrolled_count = len(reg.get("maps", {}))
    except Exception:
        pass
    try:
        from torch.project_files import classify_maps
        _, custom_set = classify_maps(game_path)
        custom_count = len(custom_set)
    except Exception:
        pass

    # LAN URL for status bar display
    lan_url = None
    lan_user = None
    if getattr(server, "lan_mode", False) and getattr(server, "lan_ip", None):
        lan_url = f"http://{server.lan_ip}:{getattr(server, 'port', 8642)}/"
        settings = getattr(server, "settings", {})
        u = settings.get("gui_username", "")
        if u:
            lan_user = u

    # Parse version tuple for frontend gating
    version_tuple = None
    if expansion_version and expansion_version != "N/A":
        parts = expansion_version.split(".")
        if len(parts) == 3:
            try:
                version_tuple = [int(p) for p in parts]
            except ValueError:
                pass

    # Map health summary (quick count of each state)
    map_health = {}
    if enrolled_count > 0:
        try:
            from torch.registry import load_registry, get_map_health
            reg2 = load_registry(project_dir)
            for map_name in reg2.get("maps", {}):
                h = get_map_health(project_dir, map_name, game_path)
                map_health[h] = map_health.get(h, 0) + 1
        except Exception:
            pass

    return ok_response({
        "project_name": proj_name,
        "torch_version": torch.VERSION,
        "expansion_version": expansion_version or "N/A",
        "expansion_version_tuple": version_tuple,
        "module_count": module_count,
        "enrolled_map_count": enrolled_count,
        "custom_map_count": custom_count,
        "map_health": map_health,
        "build_available": True,
        "lan_url": lan_url,
        "lan_user": lan_user,
    })


# ---------------------------------------------------------------------------
# Dex endpoints
# ---------------------------------------------------------------------------

def _species_to_sprite_path(const, form_tables, game_path=""):
    """Derive the sprite path from a SPECIES_ constant.

    Base forms: SPECIES_BULBASAUR -> bulbasaur/anim_front.png
    Form variants: SPECIES_CHARIZARD_MEGA_X -> charizard/mega_x/anim_front.png

    Handles species whose base form has a suffix (e.g. SPECIES_CASTFORM_NORMAL
    maps to castform/, not castform_normal/).  Uses the filesystem to resolve
    ambiguous cases.
    """
    if not const.startswith("SPECIES_"):
        return ""
    stem = const[8:].lower()  # e.g. "bulbasaur" or "charizard_mega_x"

    base_dir = stem
    group = form_tables.get(const)
    if group and len(group) > 1:
        base_const = group[0]
        base_stem = base_const[8:].lower() if base_const.startswith("SPECIES_") else ""
        if const == base_const:
            # This IS the base form.  The directory might be the full stem
            # (castform_normal) or a shorter prefix (castform).  Check filesystem.
            base_dir = _resolve_sprite_dir(game_path, stem)
        elif base_stem and stem.startswith(base_stem + "_"):
            # Simple case: SPECIES_CHARIZARD_MEGA_X, base=SPECIES_CHARIZARD
            suffix = stem[len(base_stem) + 1:]
            base_dir = f"{base_stem}/{suffix}"
        else:
            # Base form has a suffix that doesn't prefix ours cleanly
            # (e.g. base=castform_normal, self=castform_sunny).
            # Find the shared prefix directory from the filesystem.
            real_base = _resolve_sprite_dir(game_path, base_stem)
            # Derive suffix: strip the shared root from our stem
            root = real_base.split("/")[0]  # e.g. "castform"
            if stem.startswith(root + "_"):
                suffix = stem[len(root) + 1:]
                base_dir = f"{root}/{suffix}"

    return f"{base_dir}/{_pick_front_sprite(game_path, base_dir)}"


def _resolve_sprite_dir(game_path, stem):
    """Find the actual sprite directory for a stem, checking the filesystem.

    For 'castform_normal', if graphics/pokemon/castform_normal/ doesn't exist
    but graphics/pokemon/castform/ does, returns 'castform'.
    """
    if not game_path:
        return stem
    gfx_base = os.path.join(game_path, "graphics", "pokemon")
    # Try the full stem first
    if os.path.isdir(os.path.join(gfx_base, stem)):
        return stem
    # Try progressively shorter prefixes by stripping _suffix
    parts = stem.split("_")
    for i in range(len(parts) - 1, 0, -1):
        candidate = "_".join(parts[:i])
        if os.path.isdir(os.path.join(gfx_base, candidate)):
            return candidate
    return stem


def _pick_front_sprite(game_path, sprite_dir):
    """Return 'anim_front.png' or 'front.png' depending on what exists."""
    if game_path:
        gfx = os.path.join(game_path, "graphics", "pokemon", sprite_dir)
        if os.path.isfile(os.path.join(gfx, "anim_front.png")):
            return "anim_front.png"
        if os.path.isfile(os.path.join(gfx, "front.png")):
            return "front.png"
    return "anim_front.png"


def _format_species_item(const, data, form_consts, form_tables, game_path=""):
    """Build a lean species dict for the grid list."""
    from torch.dex import _species_display_name
    return {
        "const": const,
        "name": _species_display_name(const, data),
        "types": data.get("types") or [],
        "bst": data.get("bst") or 0,
        "nat_dex_num": data.get("nat_dex_num") or 0,
        "forms": form_consts,
        "sprite_path": _species_to_sprite_path(const, form_tables, game_path),
    }


_species_list_cache = {}  # game_path -> list of formatted dicts


@api_route("GET", "/api/species")
def handle_species_list(handler, match, query_params):
    """Return species list for the Dex grid."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    from torch.gamedata import load_species_data, load_form_tables
    from torch.dex import _build_species_order, _build_folded_list, _filter_species

    # Cache the full unfiltered list across requests
    if game_path not in _species_list_cache:
        species_data = load_species_data(game_path)
        if not species_data:
            return ok_response([])
        species_order = _build_species_order(game_path, species_data)
        form_tables = load_form_tables(game_path)
        folded = _build_folded_list(species_order, form_tables)

        # Build evolution indices
        # evo_from: target_const -> {method, param} (how this species was reached)
        # evo_to: source_const -> lowest level evo param (when this species evolves next)
        evo_from_index = {}
        evo_to_index = {}  # const -> lowest level-based evo param
        for sp_const, sp_data in species_data.items():
            for evo in (sp_data.get("evolutions") or []):
                target = evo.get("target", "")
                if target and target not in evo_from_index:
                    evo_from_index[target] = {
                        "method": evo.get("method", ""),
                        "param": evo.get("param", ""),
                    }
                # Track lowest level evolution for this species
                method = evo.get("method", "")
                param = evo.get("param", "")
                if method == "LEVEL" and param and param != "0":
                    try:
                        lv = int(param)
                        prev = evo_to_index.get(sp_const)
                        if prev is None or lv < prev:
                            evo_to_index[sp_const] = lv
                    except ValueError:
                        pass

        items = []
        for bc, bd, fc in folded:
            item = _format_species_item(bc, bd, fc, form_tables, game_path)
            item["evo_from"] = evo_from_index.get(bc)  # None if base form
            evo_to_lv = evo_to_index.get(bc)
            item["evo_to_level"] = evo_to_lv  # None if no level-based evo
            items.append(item)
        _species_list_cache[game_path] = items

    q = query_params.get("q", [""])[0]
    if q:
        species_data = load_species_data(game_path)
        form_tables = load_form_tables(game_path)
        species_order = _build_species_order(game_path, species_data)
        folded = _build_folded_list(species_order, form_tables)
        folded = _filter_species(folded, q)
        result = [
            _format_species_item(bc, bd, fc, form_tables, game_path)
            for bc, bd, fc in folded
        ]
        return ok_response(result)

    return ok_response(_species_list_cache[game_path])


@api_route("GET", r"/api/species/(?P<const>[^/]+)")
def handle_species_detail(handler, match, query_params):
    """Return full detail for a single species."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    const = match.group("const")
    from torch.gamedata import (
        load_species_data, load_form_tables, load_ability_names,
        load_ability_descriptions,
    )
    from torch.dex import (
        _build_species_order, _build_evolution_chain, _species_display_name,
    )

    species_data = load_species_data(game_path)
    entry = species_data.get(const)
    if entry is None:
        return error_response(f"Species '{const}' not found", 404)

    form_tables = load_form_tables(game_path)
    ability_names = load_ability_names(game_path)
    ability_descs = load_ability_descriptions(game_path)
    species_order = _build_species_order(game_path, species_data)

    abilities_named = []
    abilities_described = []
    # Reverse map: display name -> ABILITY_CONSTANT (for description lookup)
    name_to_const = {v: k for k, v in ability_names.items()}
    for a in (entry.get("abilities") or []):
        if a:
            # a may be display name ("Overgrow") or constant ("ABILITY_OVERGROW")
            ability_const = name_to_const.get(a) or a
            display_name = ability_names.get(a, a)
            abilities_named.append(display_name)
            abilities_described.append({
                "name": display_name,
                "const": ability_const,
                "description": ability_descs.get(ability_const, ""),
            })

    chain_raw = _build_evolution_chain(const, species_order, species_data)
    chain = []
    for sp_const, method, param in chain_raw:
        sp_data = species_data.get(sp_const) or {}
        chain.append({
            "const": sp_const,
            "name": _species_display_name(sp_const, sp_data),
            "method": method,
            "param": param,
        })

    # Form navigation data
    forms_list = form_tables.get(const, [const])
    form_names = [
        _species_display_name(fc, species_data.get(fc, {}))
        for fc in forms_list
    ]
    form_sprites = [
        _species_to_sprite_path(fc, form_tables, game_path)
        for fc in forms_list
    ]

    data = dict(entry)
    data["const"] = const
    data["name"] = _species_display_name(const, entry)
    data["abilities_named"] = abilities_named
    data["abilities_described"] = abilities_described
    data["evolution_chain"] = chain
    data["sprite_path"] = _species_to_sprite_path(const, form_tables, game_path)
    data["forms"] = forms_list
    data["form_names"] = form_names
    data["form_sprites"] = form_sprites

    return ok_response(data)


@api_route("GET", r"/api/species/(?P<const>[^/]+)/learnset/(?P<ltype>[^/]+)")
def handle_learnset(handler, match, query_params):
    """Return learnset data for a species."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    const = match.group("const")
    ltype = match.group("ltype")

    valid_types = ("level_up", "teachable", "egg")
    if ltype not in valid_types:
        return error_response(
            f"Invalid learnset type '{ltype}'. Must be one of: {', '.join(valid_types)}",
            400,
        )

    # Version-gate teachable learnsets (require expansion v1.14.0+)
    if ltype == "teachable":
        from torch.expansion_compat import parse_version_str, MOVESET_REFACTOR, requires_version
        exp_ver = getattr(handler.server, "expansion_version", None)
        ver_tuple = parse_version_str(exp_ver) if exp_ver else None
        if not requires_version(ver_tuple, MOVESET_REFACTOR):
            return ok_response({
                "entries": [],
                "note": "TM/Tutor learnsets require expansion v1.14.0+ (MOVESET_REFACTOR).",
            })

    from torch.gamedata import (
        load_species_data, load_move_names, load_move_data,
        load_level_up_learnset, load_teachable_learnset, load_egg_moves,
    )

    species_data = load_species_data(game_path)
    if const not in species_data:
        return error_response(f"Species '{const}' not found", 404)

    move_names = load_move_names(game_path)
    move_data = load_move_data(game_path)

    def _enrich(mc, extra=None):
        entry = {"move": mc, "name": move_names.get(mc, _move_display(mc))}
        info = move_data.get(mc, {})
        entry["type"] = info.get("type", "Normal")
        entry["category"] = info.get("category", "Physical")
        entry["power"] = info.get("power", 0)
        entry["accuracy"] = info.get("accuracy", 0)
        entry["pp"] = info.get("pp", 0)
        entry["description"] = info.get("description", "")
        if extra:
            entry.update(extra)
        return entry

    if ltype == "level_up":
        raw = _learnset_with_form_fallback(
            game_path, const, load_level_up_learnset
        )
        data = [_enrich(mc, {"level": lvl}) for lvl, mc in raw]
    elif ltype == "teachable":
        raw = _learnset_with_form_fallback(
            game_path, const, load_teachable_learnset
        )
        data = [_enrich(mc) for mc in raw]
    else:  # egg
        raw = load_egg_moves(game_path, const)
        if not raw:
            raw = _egg_moves_from_base_form(game_path, const, species_data)
        if not raw:
            raw = _learnset_with_form_fallback(
                game_path, const, load_egg_moves
            )
        data = [_enrich(mc) for mc in raw]

    return ok_response(data)


def _is_mega_or_gmax(species_const):
    """Check if a species constant represents a Mega, Gmax, or Primal form."""
    upper = species_const.upper()
    return ("_MEGA" in upper or "_GMAX" in upper or "_GIGANTAMAX" in upper
            or "_PRIMAL" in upper)


def _learnset_with_form_fallback(game_path, species_const, load_fn):
    """Load learnset, falling back to base form for Mega/Gmax/Primal forms."""
    result = load_fn(game_path, species_const)
    if result:
        return result

    if not _is_mega_or_gmax(species_const):
        return result

    from torch.gamedata import load_form_tables
    form_tables = load_form_tables(game_path)
    forms = form_tables.get(species_const)
    if not forms or len(forms) < 2:
        return result

    base_form = forms[0]
    if base_form == species_const:
        return result

    return load_fn(game_path, base_form)


def _move_display(move_const):
    """Fallback move display name from constant."""
    if move_const.startswith("MOVE_"):
        return move_const[5:].replace("_", " ").title()
    return move_const


_pre_evo_cache = {}  # game_path -> {species -> pre_evo_species}


def _egg_moves_from_base_form(game_path, species_const, species_data):
    """Walk backward through evolution chains to find egg moves.

    Egg moves are only defined for base forms (e.g. Bulbasaur, not Ivysaur).
    This function finds the base form and returns its egg moves.
    """
    if game_path not in _pre_evo_cache:
        pre_evo = {}
        for sp, data in species_data.items():
            for evo in (data.get("evolutions") or []):
                target = evo.get("target")
                if target:
                    pre_evo[target] = sp
        _pre_evo_cache[game_path] = pre_evo

    pre_evo = _pre_evo_cache[game_path]
    from torch.gamedata import load_egg_moves

    current = species_const
    visited = {current}
    while current in pre_evo:
        current = pre_evo[current]
        if current in visited:
            break  # cycle guard
        visited.add(current)
        moves = load_egg_moves(game_path, current)
        if moves:
            return moves
    return []


@api_route("GET", "/api/species/learnset-types")
def handle_learnset_types(handler, match, query_params):
    """Return which learnset types are available for this expansion version."""
    from torch.expansion_compat import parse_version_str, MOVESET_REFACTOR, requires_version
    exp_ver = getattr(handler.server, "expansion_version", None)
    ver_tuple = parse_version_str(exp_ver) if exp_ver else None

    types = ["level_up", "egg"]  # always available
    if requires_version(ver_tuple, MOVESET_REFACTOR):
        types.append("teachable")

    return ok_response({"types": types})


@api_route("GET", "/api/random-sprites")
def handle_random_sprites(handler, match, query_params):
    """Return N random species with sprite paths (for hub display)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return ok_response([])

    from torch.gamedata import load_species_data, load_form_tables
    from torch.dex import _species_display_name

    count = 1
    try:
        count = int(query_params.get("count", ["1"])[0])
    except (ValueError, IndexError):
        pass
    count = max(1, min(count, 10))

    species_data = load_species_data(game_path)
    form_tables = load_form_tables(game_path)
    if not species_data:
        return ok_response([])

    # Filter to species that have a sprite on disk
    gfx_dir = os.path.join(game_path, "graphics", "pokemon")
    candidates = []
    for const, data in species_data.items():
        sp = _species_to_sprite_path(const, form_tables, game_path)
        if sp and os.path.isfile(os.path.join(gfx_dir, sp)):
            candidates.append((const, data, sp))

    if not candidates:
        return ok_response([])

    picks = random.sample(candidates, min(count, len(candidates)))
    result = []
    for const, data, sp in picks:
        types = data.get("types") or []
        result.append({
            "const": const,
            "name": _species_display_name(const, data),
            "sprite_path": sp,
            "types": types,
        })
    return ok_response(result)


@api_route("GET", "/api/random-items")
def handle_random_items(handler, match, query_params):
    """Return N random items with icon paths (for hub display)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return ok_response([])

    count = 1
    try:
        count = int(query_params.get("count", ["1"])[0])
    except (ValueError, IndexError):
        pass
    count = max(1, min(count, 10))

    # Build or reuse item list cache
    if game_path not in _item_list_cache:
        from torch.gamedata import load_items
        from torch.names import _const_to_item_name
        raw = load_items(game_path)
        _item_list_cache[game_path] = [
            {"const": name, "name": _const_to_item_name(name),
             "icon": f"/api/items/icons/{name}"}
            for name, _comment in raw
        ]

    items = _item_list_cache[game_path]
    if not items:
        return ok_response([])

    # Filter out ITEM_NONE and common placeholder items
    filtered = [i for i in items if i["const"] not in ("ITEM_NONE",)]
    if not filtered:
        filtered = items

    picks = random.sample(filtered, min(count, len(filtered)))
    return ok_response(picks)


@api_route("GET", r"/api/sprites/(?P<path>.+)")
def handle_sprite(handler, match, query_params):
    """Serve a Pokemon sprite PNG from the game graphics directory.

    Query params:
        shiny=1  -- re-palette the sprite with the shiny .gbapal colours.
    """
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        handler.send_error(404, "Not Found")
        return None

    sprite_rel = match.group("path")

    # Security: reject non-PNG
    if not sprite_rel.endswith(".png"):
        handler.send_error(403, "Forbidden")
        return None

    gfx_dir = os.path.join(game_path, "graphics", "pokemon")
    try:
        full_path = _safe_path(gfx_dir, sprite_rel)
    except ValueError:
        handler.send_error(403, "Forbidden")
        return None

    if not os.path.isfile(full_path):
        handler.send_error(404, "Not Found")
        return None

    try:
        with open(full_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_error(500, "Read error")
        return None

    # Shiny palette swap: replace the PLTE chunk with shiny.gbapal colours
    want_shiny = query_params.get("shiny", [""])[0] == "1"
    if want_shiny:
        shiny_pal_path = os.path.join(os.path.dirname(full_path), "shiny.gbapal")
        if os.path.isfile(shiny_pal_path):
            try:
                data = _apply_shiny_palette(data, shiny_pal_path)
            except Exception:
                pass  # Serve normal sprite on failure

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)
    return None


def _apply_shiny_palette(png_bytes, shiny_gbapal_path):
    """Replace the PLTE chunk in an indexed PNG with colours from a .gbapal file.

    GBA palettes are 32 bytes: 16 entries of 2-byte little-endian RGB555.
    PNG PLTE chunks store N entries of 3-byte RGB888.
    """
    with open(shiny_gbapal_path, "rb") as f:
        pal_data = f.read()

    # Parse RGB555 -> RGB888
    colours = []
    for i in range(0, min(len(pal_data), 32), 2):
        val = int.from_bytes(pal_data[i:i + 2], "little")
        r = (val & 0x1F) << 3
        g = ((val >> 5) & 0x1F) << 3
        b = ((val >> 10) & 0x1F) << 3
        colours.append(bytes((r, g, b)))

    # Pad to 16 entries if short
    while len(colours) < 16:
        colours.append(b"\x00\x00\x00")

    new_plte_data = b"".join(colours)
    return _replace_png_plte(png_bytes, new_plte_data)


def _replace_png_plte(png_bytes, new_plte_data):
    """Replace the PLTE chunk in PNG bytes with new palette data."""
    sig = png_bytes[:8]
    result = bytearray(sig)
    pos = 8
    while pos < len(png_bytes):
        length = struct.unpack(">I", png_bytes[pos:pos + 4])[0]
        chunk_type = png_bytes[pos + 4:pos + 8]
        chunk_data = png_bytes[pos + 8:pos + 8 + length]

        if chunk_type == b"PLTE":
            chunk_data = new_plte_data
            length = len(chunk_data)

        result += struct.pack(">I", length)
        result += chunk_type
        result += chunk_data
        crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        result += struct.pack(">I", crc)
        pos += 12 + struct.unpack(">I", png_bytes[pos:pos + 4])[0]

    return bytes(result)


# ---------------------------------------------------------------------------
# Cry audio endpoint
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/cries/(?P<species_const>[A-Za-z0-9_]+)")
def handle_cry(handler, match, query_params):
    """Serve a Pokemon cry WAV file."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        handler.send_error(404, "Not Found")
        return None

    species_const = match.group("species_const")
    # SPECIES_BULBASAUR -> bulbasaur
    name = species_const
    if name.startswith("SPECIES_"):
        name = name[8:]
    name = name.lower()

    # Security: reject traversal
    if ".." in name or "/" in name or "\\" in name:
        handler.send_error(403, "Forbidden")
        return None

    cries_dir = os.path.join(game_path, "sound", "direct_sound_samples", "cries")
    wav_path = os.path.join(cries_dir, name + ".wav")

    if not os.path.isfile(wav_path):
        handler.send_error(404, "Not Found")
        return None

    try:
        with open(wav_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_error(500, "Read error")
        return None

    handler.send_response(200)
    handler.send_header("Content-Type", "audio/wav")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)
    return None


# ---------------------------------------------------------------------------
# Category icons endpoint
# ---------------------------------------------------------------------------

@api_route("GET", "/api/category-icons")
def handle_category_icons(handler, match, query_params):
    """Serve the Physical/Special/Status category icon spritesheet."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        handler.send_error(404, "Not Found")
        return None

    icon_path = os.path.join(game_path, "graphics", "interface",
                             "category_icons.png")
    if not os.path.isfile(icon_path):
        handler.send_error(404, "Not Found")
        return None

    try:
        with open(icon_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_error(500, "Read error")
        return None

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)
    return None


# ---------------------------------------------------------------------------
# Maps endpoint
# ---------------------------------------------------------------------------

@api_route("GET", "/api/maps")
def handle_maps(handler, match, query_params):
    """Return enrolled maps with health status."""
    server = handler.server
    project_dir = getattr(server, "project_dir", "")
    game_path = getattr(server, "game_path", "")

    from torch.registry import load_registry, get_map_health
    from torch.project_files import classify_maps

    registry = load_registry(project_dir)
    vanilla_set, custom_set = classify_maps(game_path)

    enrolled = []
    for map_name in sorted(registry.get("maps", {})):
        entry = registry["maps"][map_name]
        health = get_map_health(project_dir, map_name, game_path)
        enrolled.append({
            "name": map_name,
            "health": health,
            "is_custom": map_name in custom_set,
            "enrolled_at": entry.get("enrolled_at", ""),
            "last_written": entry.get("last_written", ""),
        })

    return ok_response({
        "enrolled": enrolled,
        "total_maps": len(vanilla_set) + len(custom_set),
        "custom_count": len(custom_set),
        "vanilla_count": len(vanilla_set),
    })


# ---------------------------------------------------------------------------
# Write locks
# ---------------------------------------------------------------------------

_chain_lock = threading.Lock()
_scene_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Build endpoint
# ---------------------------------------------------------------------------

_build_lock = threading.Lock()


@api_route("POST", "/api/build")
def handle_build(handler, match, query_params):
    """Trigger a ROM build with progress streaming via SSE.

    Query params:
        mode=dev  — force a dev build (plain 'make'), enabling debug menus.
                     Outputs pokeemerald.gba (not pokeemerald-release.gba).
        (default) — release build ('make release' on v1.14+).
    """
    if not _build_lock.acquire(blocking=False):
        return error_response("Build already in progress", 409)

    server = handler.server
    game_path = getattr(server, "game_path", "")
    project_dir = getattr(server, "project_dir", "")
    settings = getattr(server, "settings", {})
    dev_mode = query_params.get("mode", [""])[0] == "dev"

    t = threading.Thread(
        target=_run_build,
        args=(game_path, dev_mode, project_dir, settings),
        daemon=True,
    )
    t.start()

    mode_label = "dev" if dev_mode else "release"
    return ok_response({"status": "started", "mode": mode_label})


def _ensure_mode_clean(game_path, dev_mode, broadcaster):
    """Clean stale build objects when switching between dev and release modes.

    make uses separate obj dirs (build/<name> vs build/<name>-release) but
    won't recompile if the obj dir is already up-to-date — even when the
    output ROM was produced by the other mode.  We track the last build mode
    in a marker file and wipe the target obj dir on mode switch so make does
    a full rebuild with the correct flags.
    """
    # Store marker outside the game tree so it doesn't pollute git
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "torch")
    os.makedirs(config_dir, exist_ok=True)
    proj_id = os.path.basename(game_path)
    marker = os.path.join(config_dir, f".build_mode_{proj_id}")
    current = "dev" if dev_mode else "release"
    previous = None
    if os.path.isfile(marker):
        try:
            previous = open(marker).read().strip()
        except OSError:
            pass

    if previous and previous != current:
        # Resolve BUILD_NAME and FILE_NAME to find the obj dir and outputs
        from torch.studio import _read_makefile_var
        makefile = os.path.join(game_path, "Makefile")
        build_name = _read_makefile_var(makefile, "BUILD_NAME") or "emerald"
        if "$(" in build_name:
            build_name = "emerald"
        file_name = _read_makefile_var(makefile, "FILE_NAME") or "pokeemerald"
        if "$(" in file_name:
            file_name = "pokeemerald"
        build_dir = os.path.join(game_path, "build")
        if dev_mode:
            obj_dir = os.path.join(build_dir, build_name)
            rom_base = file_name
        else:
            obj_dir = os.path.join(build_dir, build_name + "-release")
            rom_base = file_name + "-release"
        if os.path.isdir(obj_dir):
            import shutil
            broadcaster.broadcast("build_output",
                                  {"line": f"[TORCH] Mode switch ({previous} -> {current}), cleaning {os.path.basename(obj_dir)}/"})
            shutil.rmtree(obj_dir)
        # Remove stale output files so make doesn't skip the rebuild
        for ext in (".gba", ".elf", ".map", ".sym"):
            stale = os.path.join(game_path, rom_base + ext)
            if os.path.isfile(stale):
                os.remove(stale)

    # Write current mode
    try:
        with open(marker, "w") as f:
            f.write(current)
    except OSError:
        pass


def _run_build(game_path, dev_mode=False, project_dir="", settings=None):
    """Execute the build in a background thread, streaming output via SSE.

    Args:
        dev_mode: If True, use plain 'make' instead of 'make release'.
                  Outputs pokeemerald.gba (not pokeemerald-release.gba).
        project_dir: TORCH workspace directory (for auto-sync).
        settings: TORCH settings dict (for emotes_conf, source_display).
    """
    from torch.web.events import broadcaster
    if settings is None:
        settings = {}

    try:
        broadcaster.broadcast("build_start", {"dev_mode": dev_mode})

        # Auto-sync stale maps before building
        if project_dir and game_path:
            _auto_sync_before_build(project_dir, game_path, settings,
                                    broadcaster)

        # Clean stale objects when switching build modes
        _ensure_mode_clean(game_path, dev_mode, broadcaster)

        # Pre-build steps
        _run_prebuild(game_path)

        if dev_mode:
            nproc = os.cpu_count() or 4
            cmd = ["make", f"-j{nproc}"]
        else:
            # Detect expansion version for build command
            exp_ver = _detect_version(game_path)
            from torch.ui import _build_command
            cmd = _build_command(exp_ver)

        mode_label = "DEV" if dev_mode else "RELEASE"
        broadcaster.broadcast("build_output",
                              {"line": f"$ {' '.join(cmd)}  [{mode_label}]"})

        _stream_build(cmd, game_path, broadcaster)
    except Exception as exc:
        broadcaster.broadcast("build_complete", {
            "success": False,
            "exit_code": -1,
            "error": str(exc),
        })
    finally:
        _build_lock.release()


def _derive_sync_params(project_dir):
    """Derive emotes_conf path and source_display string from project_dir.

    project_dir is like ~/ROMHacking/TORCH/ProjectName.
    The workspace root (parent) holds config/emotes.conf.
    """
    workspace = os.path.dirname(project_dir) if project_dir else ""
    emotes_conf = os.path.join(workspace, "config", "emotes.conf") if workspace else ""
    proj_name = os.path.basename(project_dir) if project_dir else ""
    source_display = f"TORCH/{proj_name}" if proj_name else "TORCH"
    return emotes_conf, source_display


def _auto_sync_before_build(project_dir, game_path, settings, broadcaster):
    """Auto-sync stale enrolled maps before building (mirrors CLI behavior)."""
    try:
        from torch.registry import load_registry, get_map_health
        from torch.sync import sync_map
    except ImportError:
        return

    try:
        registry = load_registry(project_dir)
    except Exception:
        return

    emotes_conf, source_display = _derive_sync_params(project_dir)

    stale = []
    for map_name in sorted(registry.get("maps", {})):
        try:
            health = get_map_health(project_dir, map_name, game_path)
            if health in ("stale", "never_written"):
                stale.append(map_name)
        except Exception:
            pass

    if not stale:
        return

    broadcaster.broadcast("build_output",
                          {"line": f"[TORCH] Auto-syncing {len(stale)} stale map(s)..."})
    for map_name in stale:
        broadcaster.broadcast("build_output",
                              {"line": f"[TORCH]   Syncing {map_name}"})
        try:
            sync_map(map_name, project_dir, game_path,
                     emotes_conf, source_display, quiet=True)
        except Exception as exc:
            broadcaster.broadcast("build_output",
                                  {"line": f"[TORCH]   WARN: sync failed for {map_name}: {exc}"})


def _run_prebuild(game_path):
    """Run pre-build sanitisation steps."""
    from torch.ui import (
        _sanitize_map_scripts, _regenerate_map_incs, _precompile_poryscript,
    )
    _sanitize_map_scripts(game_path)
    _regenerate_map_incs(game_path)
    _precompile_poryscript(game_path)


def _detect_version(game_path):
    """Detect expansion version tuple, or None."""
    try:
        from torch.expansion_compat import detect_expansion_version
        return detect_expansion_version(game_path)
    except Exception:
        return None


def _stream_build(cmd, game_path, broadcaster):
    """Run the build subprocess and stream stdout lines as SSE events."""
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=game_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        broadcaster.broadcast("build_output", {
            "line": "ERROR: 'make' not found. Is devkitARM in PATH?",
        })
        broadcaster.broadcast("build_complete", {
            "success": False, "exit_code": -1,
        })
        return

    while True:
        line = proc.stdout.readline()
        if not line:
            break
        broadcaster.broadcast("build_output", {"line": line.rstrip("\n")})

    proc.wait()
    success = proc.returncode == 0

    # Auto-snapshot on successful build (mirrors ui.py _execute_build)
    if success:
        try:
            from torch.verified_snapshots import create_verified_snapshot
            from torch.config import load_config as _vs_load_config
            _vs_cfg = _vs_load_config()
            _vs_max = 3
            if _vs_cfg:
                _, _, _vs_settings = _vs_cfg
                _vs_max = int(_vs_settings.get("max_verified_snapshots", 3))
            snap = create_verified_snapshot(
                game_path, trigger="web_build", max_count=_vs_max,
            )
            if snap:
                broadcaster.broadcast("build_output", {
                    "line": f"Verified snapshot saved: {os.path.basename(snap)}",
                })
        except Exception:
            pass  # Never let snapshot failure block the build result

    broadcaster.broadcast("build_complete", {
        "success": success,
        "exit_code": proc.returncode,
    })


# ---------------------------------------------------------------------------
# ROM download endpoint
# ---------------------------------------------------------------------------


def _find_rom_variants(game_path):
    """Scan game_path for .gba files and classify into dev / release.

    Returns (dev_path, release_path, latest_path).  Any may be None.
    A file whose name contains ``-release`` is the release build; the other
    .gba file (if any) is the dev build.  ``latest_path`` is whichever was
    most recently modified.
    """
    dev_path = None
    release_path = None
    latest_path = None
    latest_mtime = 0
    try:
        entries = os.listdir(game_path)
    except OSError:
        return None, None, None
    for entry in entries:
        if not entry.endswith(".gba"):
            continue
        fpath = os.path.join(game_path, entry)
        try:
            mt = os.path.getmtime(fpath)
        except OSError:
            continue
        if mt > latest_mtime:
            latest_mtime = mt
            latest_path = fpath
        if "-release" in entry:
            release_path = fpath
        else:
            dev_path = fpath
    return dev_path, release_path, latest_path


@api_route("GET", "/api/download/rom")
def handle_download_rom(handler, match, query_params):
    """Serve a built .gba ROM as a file download.

    Optional query param ``variant=dev`` or ``variant=release`` to pick a
    specific build.  Without the param the most recently modified .gba is
    returned (original behaviour).
    """
    game_path = getattr(handler.server, "game_path", "")
    if not game_path or not os.path.isdir(game_path):
        handler.send_response(404)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.end_headers()
        handler.wfile.write(json.dumps({"ok": False, "error": "Game path not found"}).encode())
        return None

    variant = query_params.get("variant", [""])[0]

    # Scan for .gba files and classify by variant
    dev_path, release_path, latest_path = _find_rom_variants(game_path)

    target_path = None
    if variant == "release":
        target_path = release_path
    elif variant == "dev":
        target_path = dev_path
    else:
        target_path = latest_path

    if not target_path:
        handler.send_response(404)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.end_headers()
        handler.wfile.write(json.dumps({"ok": False, "error": "No ROM found — build first"}).encode())
        return None

    try:
        with open(target_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_response(500)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.end_headers()
        handler.wfile.write(json.dumps({"ok": False, "error": "Failed to read ROM file"}).encode())
        return None

    filename = os.path.basename(target_path)
    handler.send_response(200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(data)
    return None


@api_route("GET", "/api/download/rom/info")
def handle_rom_info(handler, match, query_params):
    """Return metadata about all available ROM builds.

    Returns a ``builds`` list with entries for dev (pokeemerald.gba) and
    release (pokeemerald-release.gba), each with availability, size, and
    modification timestamp.  Also returns a legacy ``available`` flag for
    backward compatibility.
    """
    game_path = getattr(handler.server, "game_path", "")
    if not game_path or not os.path.isdir(game_path):
        return error_response("Game path not found", 404)

    dev_path, release_path, _ = _find_rom_variants(game_path)

    def _rom_entry(fpath, label, variant):
        if not fpath:
            return {"variant": variant, "label": label, "available": False}
        try:
            st = os.stat(fpath)
            return {
                "variant": variant,
                "label": label,
                "available": True,
                "filename": os.path.basename(fpath),
                "size_mb": round(st.st_size / (1024 * 1024), 1),
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
            }
        except OSError:
            return {"variant": variant, "label": label, "available": False}

    builds = [
        _rom_entry(dev_path, "Dev Build", "dev"),
        _rom_entry(release_path, "Release Build", "release"),
    ]

    any_available = any(b["available"] for b in builds)

    # Legacy compat: keep top-level available/filename/size_mb/modified for
    # any code that still reads the old single-ROM shape.
    legacy = {}
    if any_available:
        best = max((b for b in builds if b["available"]),
                   key=lambda b: b.get("modified", ""))
        legacy = {
            "available": True,
            "filename": best["filename"],
            "size_mb": best["size_mb"],
            "modified": best["modified"],
        }
    else:
        legacy = {"available": False}

    return ok_response({**legacy, "builds": builds})


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------

@api_route("GET", "/api/stats")
def handle_stats(handler, match, query_params):
    """Return aggregate project statistics for the dashboard."""
    server = handler.server
    game_path = getattr(server, "game_path", "")
    project_dir = getattr(server, "project_dir", "")

    data = {}
    _gather_species_count(data, game_path)
    _gather_trainer_counts(data, game_path)
    _gather_move_count(data, game_path)
    _gather_item_count(data, game_path)
    _gather_map_counts(data, game_path)
    _gather_flag_counts(data, game_path)
    _gather_encounter_count(data, game_path)
    _gather_enrolled_count(data, project_dir)

    return ok_response(data)


def _gather_species_count(data, game_path):
    try:
        from torch.gamedata import load_species_data
        data["species_count"] = len(load_species_data(game_path))
    except Exception:
        data["species_count"] = 0


def _gather_trainer_counts(data, game_path):
    try:
        from torch.gamedata import classify_trainers, parse_defines
        vanilla, custom = classify_trainers(game_path)
        data["trainer_count_custom"] = len(custom)
        data["trainer_count_vanilla"] = len(vanilla)
        data["trainer_count_total"] = len(vanilla) + len(custom)
    except Exception:
        data["trainer_count_custom"] = 0
        data["trainer_count_vanilla"] = 0
        data["trainer_count_total"] = 0
    # Max trainer slots from opponents.h
    try:
        from torch.gamedata import parse_defines_full
        opponents_h = os.path.join(game_path, "include", "constants", "opponents.h")
        defs = parse_defines_full(opponents_h, prefix="MAX_TRAINERS_COUNT")
        if defs:
            data["trainer_slots_max"] = int(defs[0][1])
        else:
            data["trainer_slots_max"] = 0
    except Exception:
        data["trainer_slots_max"] = 0


def _gather_move_count(data, game_path):
    try:
        from torch.gamedata import load_move_names
        data["move_count"] = len(load_move_names(game_path))
    except Exception:
        data["move_count"] = 0


def _gather_item_count(data, game_path):
    try:
        from torch import gamedata
        from torch.gamedata import parse_defines
        items = parse_defines(
            os.path.join(game_path, gamedata.HEADER_ITEMS), "ITEM_")
        data["item_count"] = len(items)
    except Exception:
        data["item_count"] = 0


def _gather_map_counts(data, game_path):
    try:
        from torch.project_files import classify_maps
        vanilla, custom = classify_maps(game_path)
        data["map_count_custom"] = len(custom)
        data["map_count_vanilla"] = len(vanilla)
        data["map_count_total"] = len(vanilla) + len(custom)
    except Exception:
        data["map_count_custom"] = 0
        data["map_count_vanilla"] = 0
        data["map_count_total"] = 0


def _gather_flag_counts(data, game_path):
    try:
        from torch.flag_scanner import count_free_slots
        free, total = count_free_slots(game_path)
        data["flag_free"] = free
        data["flag_total"] = total
    except Exception:
        data["flag_free"] = 0
        data["flag_total"] = 0


def _gather_encounter_count(data, game_path):
    try:
        from torch.project_files import load_wild_encounters
        enc = load_wild_encounters(game_path)
        if enc and "wild_encounter_groups" in enc:
            groups = enc["wild_encounter_groups"]
            if groups and "encounters" in groups[0]:
                data["encounter_map_count"] = len(groups[0]["encounters"])
            else:
                data["encounter_map_count"] = 0
        else:
            data["encounter_map_count"] = 0
    except Exception:
        data["encounter_map_count"] = 0


def _gather_enrolled_count(data, project_dir):
    try:
        from torch.registry import load_registry
        reg = load_registry(project_dir)
        data["enrolled_count"] = len(reg.get("maps", {}))
    except Exception:
        data["enrolled_count"] = 0


# ---------------------------------------------------------------------------
# Maps attention endpoint
# ---------------------------------------------------------------------------

@api_route("GET", "/api/maps/attention")
def handle_maps_attention(handler, match, query_params):
    """Return maps that need attention (stale, drift, orphan, unenrolled)."""
    server = handler.server
    project_dir = getattr(server, "project_dir", "")
    game_path = getattr(server, "game_path", "")

    needs_sync = []
    try:
        from torch.registry import load_registry, get_map_health
        registry = load_registry(project_dir)
        for map_name in sorted(registry.get("maps", {})):
            health = get_map_health(project_dir, map_name, game_path)
            if health not in ("ok",):
                needs_sync.append({"name": map_name, "health": health})
    except Exception:
        pass

    unenrolled = []
    try:
        from torch.registry import get_unenrolled_workspace_dirs
        unenrolled = get_unenrolled_workspace_dirs(project_dir)
    except Exception:
        pass

    return ok_response({
        "needs_sync": needs_sync,
        "unenrolled": unenrolled,
    })


# ---------------------------------------------------------------------------
# Sync endpoint
# ---------------------------------------------------------------------------

_sync_lock = threading.Lock()


@api_route("POST", "/api/sync")
def handle_sync(handler, match, query_params):
    """Sync all stale/never_written enrolled maps."""
    if not _sync_lock.acquire(blocking=False):
        return error_response("Sync already in progress", 409)

    server = handler.server
    project_dir = getattr(server, "project_dir", "")
    game_path = getattr(server, "game_path", "")
    emotes_conf, source_display = _derive_sync_params(project_dir)

    # Find maps needing sync
    to_sync = []
    try:
        from torch.registry import load_registry, get_map_health
        registry = load_registry(project_dir)
        for map_name in sorted(registry.get("maps", {})):
            health = get_map_health(project_dir, map_name, game_path)
            if health in ("stale", "never_written", "drift"):
                to_sync.append(map_name)
    except Exception:
        _sync_lock.release()
        return error_response("Failed to read registry", 500)

    if not to_sync:
        _sync_lock.release()
        return ok_response({"status": "nothing_to_sync", "count": 0})

    t = threading.Thread(
        target=_run_sync,
        args=(to_sync, project_dir, game_path, emotes_conf, source_display),
        daemon=True,
    )
    t.start()

    return ok_response({"status": "started", "count": len(to_sync)})


def _run_sync(to_sync, project_dir, game_path, emotes_conf, source_display):
    """Execute sync in a background thread, broadcasting SSE events."""
    from torch.web.events import broadcaster

    failures = []
    try:
        from torch.sync import sync_map
        for map_name in to_sync:
            broadcaster.broadcast("sync_start", {"map": map_name})
            try:
                sync_map(map_name, project_dir, game_path,
                         emotes_conf, source_display, quiet=True)
                broadcaster.broadcast("sync_complete",
                                      {"map": map_name, "success": True})
            except Exception as exc:
                failures.append(map_name)
                broadcaster.broadcast("sync_complete",
                                      {"map": map_name, "success": False,
                                       "error": str(exc)})
        broadcaster.broadcast("sync_all_done", {
            "total": len(to_sync),
            "failed": len(failures),
            "failures": failures,
        })
    finally:
        _sync_lock.release()


# ---------------------------------------------------------------------------
# Encounter endpoints
# ---------------------------------------------------------------------------

def _enc_map_display(map_const):
    """Convert MAP_ROUTE_101 to 'Route 101' for display."""
    name = map_const
    if name.startswith("MAP_"):
        name = name[4:]
    if name == name.upper() and "_" in name:
        return name.replace("_", " ").title()
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return spaced.replace("_", " ")


def _enc_base_label(map_const):
    """MAP_ROUTE_101 -> gRoute101."""
    name = map_const
    if name.startswith("MAP_"):
        name = name[4:]
    parts = name.split("_")
    return "g" + "".join(p.capitalize() for p in parts)


def _enc_species_name(species):
    """Strip SPECIES_ prefix."""
    if species and species.startswith("SPECIES_"):
        return species[8:].replace("_", " ").title()
    return species or "None"


# Static reference data (mirrors encounter_editor.py constants)
_ENC_TYPE_LABELS = {
    "land_mons": "Land",
    "water_mons": "Water",
    "fishing_mons": "Fishing",
    "rock_smash_mons": "Rock Smash",
}
_ENC_TYPE_SLOT_COUNTS = {
    "land_mons": 12,
    "water_mons": 5,
    "rock_smash_mons": 5,
    "fishing_mons": 10,
}
_ENC_FALLBACK_RATES = {
    "land_mons": [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1],
    "water_mons": [60, 30, 5, 4, 1],
    "rock_smash_mons": [60, 30, 5, 4, 1],
    "fishing_mons": [70, 30, 60, 20, 20, 40, 40, 15, 4, 1],
}
_ENC_FISHING_GROUPS = {"old_rod": [0, 2], "good_rod": [2, 5], "super_rod": [5, 10]}
_ENC_DEFAULT_RATE = 20
_ENC_TIME_SUFFIXES = ("Morning", "Day", "Evening", "Night")


@api_route("GET", "/api/encounters")
def handle_encounter_list(handler, match, query_params):
    """List all maps with encounter data."""
    game_path = getattr(handler.server, "game_path", "")

    from torch.project_files import (
        get_maps_with_encounters, get_encounters_for_map,
        get_encounter_types, classify_maps,
    )

    try:
        map_consts = get_maps_with_encounters(game_path)
    except Exception:
        map_consts = set()

    if not map_consts:
        has_time = False
        try:
            from torch.expansion_compat import check_feature, TIME_BASED_ENCOUNTERS
            has_time = check_feature(game_path, TIME_BASED_ENCOUNTERS)
        except Exception:
            pass
        return ok_response({"maps": [], "has_time_encounters": has_time, "total_count": 0})

    try:
        _, custom_set = classify_maps(game_path)
    except Exception:
        custom_set = set()

    # Check time-based encounter support
    has_time = False
    try:
        from torch.expansion_compat import check_feature, TIME_BASED_ENCOUNTERS
        has_time = check_feature(game_path, TIME_BASED_ENCOUNTERS)
    except Exception:
        pass

    # Deduplicate: time-of-day variants share the same map constant
    seen = set()
    maps_out = []
    for mc in sorted(map_consts):
        if mc in seen:
            continue
        seen.add(mc)
        entries = get_encounters_for_map(game_path, mc)
        # Collect all types across all entries for this map
        all_types = set()
        for entry in entries:
            all_types.update(get_encounter_types(entry))
        maps_out.append({
            "map": mc,
            "name": _enc_map_display(mc),
            "types": sorted(all_types),
            "is_custom": mc in custom_set,
        })

    return ok_response({
        "maps": maps_out,
        "has_time_encounters": has_time,
        "total_count": len(maps_out),
    })


@api_route("GET", r"/api/encounters/types")
def handle_encounter_types(handler, match, query_params):
    """Return static encounter type reference data."""
    return ok_response({
        "type_labels": _ENC_TYPE_LABELS,
        "type_slot_counts": _ENC_TYPE_SLOT_COUNTS,
        "fallback_rates": _ENC_FALLBACK_RATES,
        "fishing_groups": _ENC_FISHING_GROUPS,
        "default_encounter_rate": _ENC_DEFAULT_RATE,
    })


@api_route("GET", r"/api/encounters/(?P<map_const>[A-Z][A-Z0-9_]+)")
def handle_encounter_detail(handler, match, query_params):
    """Full encounter detail for one map."""
    game_path = getattr(handler.server, "game_path", "")
    map_const = match.group("map_const")

    from torch.project_files import (
        get_encounters_for_map, get_encounter_types,
        get_encounter_species, get_field_rates, extract_time_suffix,
    )

    entries = get_encounters_for_map(game_path, map_const)
    if not entries:
        # Return a valid response with empty types so the frontend can show
        # the creation wizard instead of a dead-end error page
        return ok_response({
            "map": map_const,
            "name": _enc_map_display(map_const),
            "base_label": _enc_base_label(map_const),
            "types": {},
            "has_time_variants": False,
            "time_variants": [],
            "field_rates": _ENC_FALLBACK_RATES,
            "empty": True,
        })

    field_rates = get_field_rates(game_path)

    # Find the primary (non-time-variant) entry and any time variants
    primary = entries[0]
    time_variants = []
    for entry in entries:
        bl = entry.get("base_label", "")
        suffix = extract_time_suffix(bl)
        if suffix:
            time_variants.append(suffix)
        elif len(entries) > 1:
            # First entry without time suffix is the primary
            primary = entry

    # Load species data for type lookups
    species_types = {}
    try:
        from torch.gamedata import load_species_data
        sp_data = load_species_data(game_path)
        if sp_data:
            for sp_const, sp_info in sp_data.items():
                species_types[sp_const] = sp_info.get("types") or []
    except Exception:
        pass

    # Build types dict from the primary entry
    types_out = {}
    for etype in get_encounter_types(primary):
        mons = get_encounter_species(primary, etype)
        rates = field_rates.get(etype) or _ENC_FALLBACK_RATES.get(etype, [])
        encounter_rate = primary.get(etype, {}).get("encounter_rate", _ENC_DEFAULT_RATE)
        mons_out = []
        for i, mon in enumerate(mons):
            sp = mon.get("species", "SPECIES_NONE")
            mons_out.append({
                "index": i,
                "species": sp,
                "species_name": _enc_species_name(sp),
                "species_types": species_types.get(sp, []),
                "min_level": mon.get("min_level", 1),
                "max_level": mon.get("max_level", 1),
                "rate_pct": rates[i] if i < len(rates) else 0,
            })
        types_out[etype] = {
            "encounter_rate": encounter_rate,
            "mons": mons_out,
        }

    return ok_response({
        "map": map_const,
        "name": _enc_map_display(map_const),
        "base_label": primary.get("base_label", _enc_base_label(map_const)),
        "types": types_out,
        "has_time_variants": len(time_variants) > 0,
        "time_variants": time_variants,
        "field_rates": field_rates or _ENC_FALLBACK_RATES,
    })


# ---------------------------------------------------------------------------
# Encounter write-back endpoints
# ---------------------------------------------------------------------------

_ENC_KNOWN_TYPES = set(_ENC_TYPE_LABELS.keys())


def _read_json_body(handler):
    """Read and parse a JSON body from the request."""
    length = int(handler.headers.get("Content-Length", 0))
    if length <= 0:
        return None
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def _validate_encounter_payload(payload, map_const):
    """Validate a POST encounter save payload.

    Returns (cleaned_data, error_message).  error_message is None on success.
    """
    if not isinstance(payload, dict):
        return None, "Payload must be a JSON object"

    if payload.get("map") != map_const:
        return None, f"Payload 'map' field must match URL ({map_const})"

    # Validate each encounter type
    for key in list(payload.keys()):
        if key in ("map", "base_label"):
            continue
        if key not in _ENC_KNOWN_TYPES:
            return None, f"Unknown encounter type: {key}"
        etype_data = payload[key]
        if not isinstance(etype_data, dict):
            return None, f"Encounter type '{key}' must be an object"

        rate = etype_data.get("encounter_rate")
        if rate is not None:
            if not isinstance(rate, int) or rate < 1 or rate > 255:
                return None, f"encounter_rate for '{key}' must be int 1-255"

        mons = etype_data.get("mons")
        if mons is not None:
            if not isinstance(mons, list):
                return None, f"'mons' for '{key}' must be a list"
            for i, slot in enumerate(mons):
                if not isinstance(slot, dict):
                    return None, f"Slot {i} in '{key}' must be an object"
                species = slot.get("species")
                if not isinstance(species, str) or not species:
                    return None, f"Slot {i} in '{key}': species must be a non-empty string"
                min_lv = slot.get("min_level")
                max_lv = slot.get("max_level")
                if not isinstance(min_lv, int) or min_lv < 1 or min_lv > 100:
                    return None, f"Slot {i} in '{key}': min_level must be int 1-100"
                if not isinstance(max_lv, int) or max_lv < min_lv or max_lv > 100:
                    return None, f"Slot {i} in '{key}': max_level must be int >= min_level and <= 100"

    return payload, None


@api_route("POST", r"/api/encounters/(?P<map_const>[A-Z][A-Z0-9_]+)")
def handle_encounter_save(handler, match, query_params):
    """Save encounter changes for a map."""
    game_path = getattr(handler.server, "game_path", "")
    map_const = match.group("map_const")

    try:
        payload = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if payload is None:
        return error_response("Request body required", 400)

    cleaned, err = _validate_encounter_payload(payload, map_const)
    if err:
        return error_response(err, 400)

    from torch.project_files import load_wild_encounters, write_encounters

    data = load_wild_encounters(game_path)
    if not data or "wild_encounter_groups" not in data:
        return error_response("No encounter data found in project", 500)

    # Find the for_maps group
    group = None
    for g in data["wild_encounter_groups"]:
        if g.get("for_maps"):
            group = g
            break
    if group is None:
        return error_response("No for_maps encounter group found", 500)

    encounters = group.setdefault("encounters", [])

    # Find existing entry for this map
    entry = None
    for e in encounters:
        if e.get("map") == map_const:
            entry = e
            break

    if entry is None:
        # Create new entry
        entry = {"map": map_const, "base_label": cleaned.get("base_label", _enc_base_label(map_const))}
        encounters.append(entry)
    elif "base_label" in cleaned:
        entry["base_label"] = cleaned["base_label"]

    # Update encounter types — sync to match exactly what was sent
    for etype in _ENC_KNOWN_TYPES:
        if etype in cleaned:
            entry[etype] = cleaned[etype]
        elif etype in entry:
            # Type was removed by the user — delete it
            del entry[etype]

    # If no encounter types remain, remove the entry entirely
    remaining_types = [k for k in entry if k not in ("map", "base_label")]
    if not remaining_types:
        group["encounters"] = [
            e for e in encounters if e.get("map") != map_const
        ]

    if not write_encounters(game_path, data):
        return error_response("Failed to write encounters file", 500)

    return ok_response({"saved": True, "map": map_const})


@api_route("POST", "/api/encounters/new")
def handle_encounter_new(handler, match, query_params):
    """Create encounters for a new map."""
    game_path = getattr(handler.server, "game_path", "")

    try:
        payload = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if payload is None:
        return error_response("Request body required", 400)

    map_const = payload.get("map")
    if not isinstance(map_const, str) or not map_const.startswith("MAP_"):
        return error_response("'map' must be a valid map constant (e.g. MAP_MY_TOWN)", 400)

    requested_types = payload.get("types", [])
    if not isinstance(requested_types, list):
        return error_response("'types' must be a list", 400)
    for t in requested_types:
        if t not in _ENC_KNOWN_TYPES:
            return error_response(f"Unknown encounter type: {t}", 400)
    if not requested_types:
        return error_response("At least one encounter type required", 400)

    from torch.project_files import load_wild_encounters, write_encounters

    data = load_wild_encounters(game_path)
    if not data or "wild_encounter_groups" not in data:
        return error_response("No encounter data found in project", 500)

    group = None
    for g in data["wild_encounter_groups"]:
        if g.get("for_maps"):
            group = g
            break
    if group is None:
        return error_response("No for_maps encounter group found", 500)

    encounters = group.setdefault("encounters", [])

    # Check if map already has encounters
    for e in encounters:
        if e.get("map") == map_const:
            return error_response(f"Map '{map_const}' already has encounters", 400)

    # Create new entry with default empty slots
    entry = {
        "map": map_const,
        "base_label": _enc_base_label(map_const),
    }
    for etype in requested_types:
        slot_count = _ENC_TYPE_SLOT_COUNTS.get(etype, 5)
        entry[etype] = {
            "encounter_rate": _ENC_DEFAULT_RATE,
            "mons": [
                {"min_level": 5, "max_level": 5, "species": "SPECIES_NONE"}
                for _ in range(slot_count)
            ],
        }
    encounters.append(entry)

    if not write_encounters(game_path, data):
        return error_response("Failed to write encounters file", 500)

    return ok_response({"saved": True, "map": map_const, "entry": entry})


@api_route("DELETE", r"/api/encounters/(?P<map_const>[A-Z][A-Z0-9_]+)")
def handle_encounter_delete(handler, match, query_params):
    """Delete all encounters for a map, or a single encounter type."""
    game_path = getattr(handler.server, "game_path", "")
    map_const = match.group("map_const")

    # Optional: delete only a specific type (e.g. ?type=land_mons)
    etype = query_params.get("type", [None])[0]
    if etype and etype not in _ENC_KNOWN_TYPES:
        return error_response(f"Unknown encounter type: {etype}", 400)

    from torch.project_files import (
        load_wild_encounters, write_encounters, remove_encounters_for_map,
    )

    if not etype:
        # Delete ALL encounters for this map
        removed = remove_encounters_for_map(game_path, map_const)
        if removed == 0:
            return error_response(f"No encounters found for '{map_const}'", 404)
        return ok_response({"deleted": True, "map": map_const, "removed": removed})

    # Delete a single encounter type from this map
    data = load_wild_encounters(game_path)
    if not data:
        return error_response("No encounter data found in project", 500)

    found = False
    for group in data.get("wild_encounter_groups", []):
        for entry in group.get("encounters", []):
            if entry.get("map") == map_const and etype in entry:
                del entry[etype]
                found = True
                # If this was the last type, remove the entry entirely
                remaining = [k for k in entry if k not in ("map", "base_label")]
                if not remaining:
                    group["encounters"] = [
                        e for e in group["encounters"]
                        if e.get("map") != map_const
                    ]
                break
        if found:
            break

    if not found:
        return error_response(
            f"No '{etype}' encounters found for '{map_const}'", 404
        )

    if not write_encounters(game_path, data):
        return error_response("Failed to write encounters file", 500)

    return ok_response({"deleted": True, "map": map_const, "type": etype})


# ---------------------------------------------------------------------------
# Trainer endpoints
# ---------------------------------------------------------------------------

_trainer_list_cache = {}  # game_path -> (trainers_list, total, custom_count, vanilla_count)
_trainer_incbin_cache = {}  # game_path -> {TRAINER_PIC_X: "filename.png", ...}


def _get_trainer_sprite_map(game_path):
    """Get authoritative TRAINER_PIC_* -> filename mapping via INCBIN declarations.

    Caches the result per game_path.  Falls back to naive constant-derived
    name when no INCBIN entry exists.
    """
    if game_path in _trainer_incbin_cache:
        return _trainer_incbin_cache[game_path]

    from torch.asset_browser import _build_trainer_incbin_map
    incbin = _build_trainer_incbin_map(game_path)
    # Normalise to bare filenames (the sprite endpoint serves from front_pics/)
    sprite_map = {}
    for const, rel_path in incbin.items():
        sprite_map[const] = os.path.basename(rel_path)
    _trainer_incbin_cache[game_path] = sprite_map
    return sprite_map


def _resolve_trainer_sprite(pic_const, game_path):
    """Resolve a TRAINER_PIC_* constant to a sprite filename.

    Uses the INCBIN map for accuracy, falls back to constant-derived name.
    """
    if not pic_const or not pic_const.startswith("TRAINER_PIC_"):
        return ""
    sprite_map = _get_trainer_sprite_map(game_path)
    if pic_const in sprite_map:
        return sprite_map[pic_const]
    # Fallback: naive conversion (works for vanilla sprites where name == constant)
    return pic_const[len("TRAINER_PIC_"):].lower() + ".png"


def _check_party_format(handler):
    """Check if the project supports .party trainer format (v1.9.0+).

    Returns (True, None) if supported, or (False, error_response) if not.
    """
    from torch.expansion_compat import parse_version_str, PARTY_FORMAT, requires_version
    exp_ver = getattr(handler.server, "expansion_version", None)
    if exp_ver is None:
        return False, error_response(
            "Vanilla pokeemerald detected. Web trainer editing requires "
            "pokeemerald-expansion v1.9.0+ (.party format).",
            400
        )
    ver_tuple = parse_version_str(exp_ver)
    if not requires_version(ver_tuple, PARTY_FORMAT):
        return False, error_response(
            f"Expansion v{exp_ver} uses legacy .h trainer format. "
            f"Web trainer editing requires v1.9.0+ (.party format). "
            f"Use the CLI trainer editor for legacy projects.",
            400
        )
    return True, None


def _build_trainer_list(game_path):
    """Build the full trainer list with header data, caching the result."""
    if game_path in _trainer_list_cache:
        return _trainer_list_cache[game_path]

    from torch.gamedata import load_trainer_ids, classify_trainers
    from torch.battle_io import read_party_file
    from torch.names import _const_to_human_name

    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    all_ids = load_trainer_ids(game_path)
    vanilla_ids, custom_ids = classify_trainers(game_path)

    # Load full party data to get party_size and pic info
    records = []
    if os.path.isfile(party_path):
        records, _ = read_party_file(party_path)

    # Index records by trainer_const
    record_map = {}
    for r in records:
        tc = r.get("trainer_const")
        if tc:
            record_map[tc] = r

    trainers = []
    for tc, tid in sorted(all_ids.items(), key=lambda x: x[1]):
        if tid == 0:
            continue
        rec = record_map.get(tc)
        class_const = rec.get("trainer_class") if rec else None
        pic_const = rec.get("trainer_pic") if rec else None
        name = rec.get("trainer_name") if rec else None
        mons = rec.get("mons", []) if rec else []

        # Resolve sprite filename via INCBIN map
        sprite_path = _resolve_trainer_sprite(pic_const, game_path)

        trainers.append({
            "const": tc,
            "id": tid,
            "name": name,
            "class": _const_to_human_name(class_const, "TRAINER_CLASS_") if class_const else None,
            "class_const": class_const,
            "pic_const": pic_const,
            "sprite_path": sprite_path,
            "is_double": rec.get("is_double", False) if rec else False,
            "is_custom": tc in custom_ids,
            "party_size": len(mons),
        })

    total = len(trainers)
    custom_count = sum(1 for t in trainers if t["is_custom"])
    vanilla_count = total - custom_count

    result = (trainers, total, custom_count, vanilla_count)
    _trainer_list_cache[game_path] = result
    return result


@api_route("GET", "/api/trainers")
def handle_trainer_list(handler, match, query_params):
    """Return list of all trainers (header-only data)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    has_party, party_err = _check_party_format(handler)
    if not has_party:
        # Return empty list with format warning instead of hard error,
        # so the frontend can display the message gracefully
        return ok_response({
            "trainers": [],
            "total": 0,
            "custom_count": 0,
            "vanilla_count": 0,
            "format": "legacy_h",
            "format_warning": party_err.get("error", "Legacy .h format not supported in web GUI"),
        })

    try:
        trainers, total, custom_count, vanilla_count = _build_trainer_list(game_path)
    except Exception as exc:
        return error_response(f"Failed to load trainers: {exc}", 500)

    # Filter: ?filter=custom
    filt = query_params.get("filter", [""])[0]
    result = trainers
    if filt == "custom":
        result = [t for t in trainers if t["is_custom"]]

    # Search: ?q=<search>
    q = query_params.get("q", [""])[0].lower()
    if q:
        result = [
            t for t in result
            if q in (t.get("const") or "").lower()
            or q in (t.get("name") or "").lower()
            or q in (t.get("class") or "").lower()
        ]

    return ok_response({
        "trainers": result,
        "total": total,
        "custom_count": custom_count,
        "vanilla_count": vanilla_count,
        "format": "party",
        "format_warning": None,
    })


@api_route("GET", r"/api/trainers/sprites/(?P<path>.+)")
def handle_trainer_sprite(handler, match, query_params):
    """Serve a trainer front sprite PNG."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        handler.send_error(404, "Not Found")
        return None

    sprite_rel = match.group("path")

    # Security: reject non-PNG
    if not sprite_rel.endswith(".png"):
        handler.send_error(403, "Forbidden")
        return None

    gfx_dir = os.path.join(game_path, "graphics", "trainers", "front_pics")
    try:
        full_path = _safe_path(gfx_dir, sprite_rel)
    except ValueError:
        handler.send_error(403, "Forbidden")
        return None

    if not os.path.isfile(full_path):
        handler.send_error(404, "Not Found")
        return None

    try:
        with open(full_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_error(500, "Read error")
        return None

    # Ensure palette index 0 is transparent (custom sprites may lack tRNS)
    data = _ensure_png_transparency(data)

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)
    return None


def _load_encounter_music(trainers_h, parse_defines, human_name):
    """Parse TRAINER_ENCOUNTER_MUSIC_* defines from trainers.h."""
    if not os.path.isfile(trainers_h):
        return []
    music = []
    for music_const, _comment in parse_defines(trainers_h, "TRAINER_ENCOUNTER_MUSIC_"):
        if music_const.endswith("_COUNT") or music_const.endswith("_NUM"):
            continue
        music.append({
            "const": music_const,
            "name": human_name(music_const, "TRAINER_ENCOUNTER_MUSIC_"),
        })
    return music


_BALL_ITEMS = [
    "ITEM_POKE_BALL", "ITEM_GREAT_BALL", "ITEM_ULTRA_BALL",
    "ITEM_MASTER_BALL", "ITEM_PREMIER_BALL", "ITEM_HEAL_BALL",
    "ITEM_NET_BALL", "ITEM_NEST_BALL", "ITEM_REPEAT_BALL",
    "ITEM_TIMER_BALL", "ITEM_LUXURY_BALL", "ITEM_DIVE_BALL",
    "ITEM_DUSK_BALL", "ITEM_QUICK_BALL", "ITEM_LEVEL_BALL",
    "ITEM_LURE_BALL", "ITEM_MOON_BALL", "ITEM_FRIEND_BALL",
    "ITEM_LOVE_BALL", "ITEM_HEAVY_BALL", "ITEM_FAST_BALL",
    "ITEM_SPORT_BALL", "ITEM_SAFARI_BALL", "ITEM_DREAM_BALL",
    "ITEM_BEAST_BALL",
]


def _load_ball_constants(game_path, parse_defines):
    """Parse ball constants — newer ball.h or fallback to items.h."""
    ball_h = os.path.join(game_path, "include", "constants", "ball.h")
    if os.path.isfile(ball_h):
        balls = []
        for ball_const, _comment in parse_defines(ball_h, "BALL_"):
            if ball_const.endswith("_COUNT") or ball_const.endswith("_NUM"):
                continue
            if ball_const == "BALL_NONE":
                continue
            name = ball_const[len("BALL_"):].replace("_", " ").title()
            item_key = "ITEM_" + ball_const[len("BALL_"):] + "_BALL"
            balls.append({"const": ball_const, "name": name,
                          "icon": f"/api/items/icons/{item_key}"})
        return balls
    # Older versions: known ball ITEM_* constants from items.h
    items_h = os.path.join(game_path, "include", "constants", "items.h")
    existing = set()
    if os.path.isfile(items_h):
        existing = {c for c, _ in parse_defines(items_h, "ITEM_")}
    balls = []
    for ball_const in _BALL_ITEMS:
        if not existing or ball_const in existing:
            name = ball_const[len("ITEM_"):].replace("_", " ").title()
            balls.append({"const": ball_const, "name": name,
                          "icon": f"/api/items/icons/{ball_const}"})
    return balls


@api_route("GET", r"/api/trainers/ref")
def handle_trainer_ref(handler, match, query_params):
    """Return reference data for the trainer editor."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    from torch.gamedata import load_ai_flags, parse_defines
    from torch.names import _const_to_human_name

    # Trainer classes — enum values, parse from trainers.h
    classes = []
    trainers_h = os.path.join(game_path, "include", "constants", "trainers.h")
    if os.path.isfile(trainers_h):
        try:
            with open(trainers_h, encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.strip().rstrip(",")
                    if stripped.startswith("TRAINER_CLASS_"):
                        # Strip inline comments
                        const = stripped.split("//")[0].split("/*")[0].strip().rstrip(",")
                        if const and const.startswith("TRAINER_CLASS_"):
                            name = _const_to_human_name(const, "TRAINER_CLASS_")
                            classes.append({"const": const, "name": name})
        except OSError:
            pass

    # Trainer pics — #define values
    pics = []
    if os.path.isfile(trainers_h):
        raw_pics = parse_defines(trainers_h, "TRAINER_PIC_")
        for pic_const, _comment in raw_pics:
            if pic_const == "TRAINER_PIC_COUNT":
                continue
            name = _const_to_human_name(pic_const, "TRAINER_PIC_")
            filename = _resolve_trainer_sprite(pic_const, game_path)
            pics.append({"const": pic_const, "name": name, "file": filename})

    # AI flags
    ai_flags = []
    try:
        raw_flags = load_ai_flags(game_path)
        for suffix, desc in raw_flags:
            ai_flags.append({
                "const": f"AI_FLAG_{suffix}",
                "name": _const_to_human_name(f"AI_FLAG_{suffix}", "AI_FLAG_"),
                "description": desc,
            })
    except Exception:
        pass

    # Natures — hardcoded, they never change
    _NATURE_STATS = [
        ("NATURE_HARDY", None, None), ("NATURE_LONELY", "Atk", "Def"),
        ("NATURE_BRAVE", "Atk", "Spe"), ("NATURE_ADAMANT", "Atk", "SpA"),
        ("NATURE_NAUGHTY", "Atk", "SpD"), ("NATURE_BOLD", "Def", "Atk"),
        ("NATURE_DOCILE", None, None), ("NATURE_RELAXED", "Def", "Spe"),
        ("NATURE_IMPISH", "Def", "SpA"), ("NATURE_LAX", "Def", "SpD"),
        ("NATURE_TIMID", "Spe", "Atk"), ("NATURE_HASTY", "Spe", "Def"),
        ("NATURE_SERIOUS", None, None), ("NATURE_JOLLY", "Spe", "SpA"),
        ("NATURE_NAIVE", "Spe", "SpD"), ("NATURE_MODEST", "SpA", "Atk"),
        ("NATURE_MILD", "SpA", "Def"), ("NATURE_QUIET", "SpA", "Spe"),
        ("NATURE_BASHFUL", None, None), ("NATURE_RASH", "SpA", "SpD"),
        ("NATURE_CALM", "SpD", "Atk"), ("NATURE_GENTLE", "SpD", "Def"),
        ("NATURE_SASSY", "SpD", "Spe"), ("NATURE_CAREFUL", "SpD", "SpA"),
        ("NATURE_QUIRKY", None, None),
    ]
    natures = []
    for const, plus, minus in _NATURE_STATS:
        name = const.replace("NATURE_", "").replace("_", " ").title()
        entry = {"const": const, "name": name}
        if plus:
            entry["plus"] = plus
        if minus:
            entry["minus"] = minus
        natures.append(entry)

    # Battle types (version-gated)
    from torch.expansion_compat import parse_version_str
    from torch.battle_manager import _available_battle_types
    exp_ver = getattr(handler.server, "expansion_version", None)
    ver_tuple = parse_version_str(exp_ver) if exp_ver else None
    battle_types = []
    for type_name, macro, min_ver, description in _available_battle_types(ver_tuple):
        bt = {"name": type_name, "macro": macro, "description": description}
        if min_ver:
            bt["min_version"] = f"{min_ver[0]}.{min_ver[1]}.{min_ver[2]}"
        battle_types.append(bt)

    return ok_response({
        "classes": classes,
        "pics": pics,
        "ai_flags": ai_flags,
        "natures": natures,
        "music": _load_encounter_music(trainers_h, parse_defines, _const_to_human_name),
        "balls": _load_ball_constants(game_path, parse_defines),
        "battle_types": battle_types,
        "vanilla_threshold": 854,
    })


@api_route("GET", r"/api/trainers/battle-types")
def handle_battle_types(handler, match, query_params):
    """Return available battle types for this project's expansion version."""
    from torch.expansion_compat import parse_version_str
    from torch.battle_manager import _available_battle_types

    exp_ver = getattr(handler.server, "expansion_version", None)
    ver_tuple = parse_version_str(exp_ver) if exp_ver else None

    types = _available_battle_types(ver_tuple)
    result = []
    for type_name, macro, min_ver, description in types:
        entry = {
            "name": type_name,
            "macro": macro,
            "description": description,
        }
        if min_ver:
            entry["min_version"] = f"{min_ver[0]}.{min_ver[1]}.{min_ver[2]}"
        result.append(entry)

    return ok_response({
        "battle_types": result,
        "expansion_version": exp_ver,
    })


@api_route("GET", r"/api/trainers/ai-flags")
def handle_ai_flags(handler, match, query_params):
    """Return AI flags with descriptions for this project's expansion version."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    from torch.gamedata import load_ai_flags
    from torch.names import _const_to_human_name
    from torch.expansion_compat import parse_version_str, AI_FLAGS_U64, requires_version

    raw_flags = load_ai_flags(game_path)
    flags = []
    for suffix, desc in raw_flags:
        const = f"AI_FLAG_{suffix}"
        flags.append({
            "const": const,
            "name": _const_to_human_name(const, "AI_FLAG_"),
            "description": desc,
            "suffix": suffix,
        })

    exp_ver = getattr(handler.server, "expansion_version", None)
    ver_tuple = parse_version_str(exp_ver) if exp_ver else None
    expanded = requires_version(ver_tuple, AI_FLAGS_U64)

    return ok_response({
        "flags": flags,
        "expanded_u64": expanded,
        "expansion_version": exp_ver,
    })


def _build_party_array(record, game_path, move_data, form_tables, names,
                       species_data=None):
    """Build the enriched party array for trainer detail response."""
    party = []
    for mon in (record.get("mons") or []):
        species = mon.get("species", "")
        moves = []
        for mc in (mon.get("moves") or []):
            md = move_data.get(mc, {})
            moves.append({
                "const": mc,
                "name": names["move"](mc),
                "type": md.get("type", "Normal"),
                "power": md.get("power", 0),
                "accuracy": md.get("accuracy", 0),
                "category": md.get("category", "Physical"),
            })

        # Species types (for type gradient rendering on the frontend)
        types = []
        if species_data and species in species_data:
            types = species_data[species].get("types", [])

        party.append({
            "species": species,
            "species_name": names["species"](species),
            "sprite_path": _species_to_sprite_path(species, form_tables, game_path),
            "level": mon.get("level"),
            "held_item": mon.get("held_item"),
            "held_item_name": names["item"](mon.get("held_item") or ""),
            "moves": moves,
            "ability": mon.get("ability"),
            "ability_name": names["ability"](mon.get("ability") or ""),
            "ivs": mon.get("ivs"),
            "evs": mon.get("evs"),
            "nature": mon.get("nature"),
            "nature_name": names["nature"](mon.get("nature") or ""),
            "gender": mon.get("gender"),
            "shiny": mon.get("shiny"),
            "ball": mon.get("ball"),
            "nickname": mon.get("nickname"),
            "types": types,
        })
    return party


def _parse_encounter_music(raw):
    """Parse encounter_music field, stripping F_TRAINER_FEMALE prefix."""
    is_female = "F_TRAINER_FEMALE" in raw
    music_const = raw.replace("F_TRAINER_FEMALE", "").replace("|", "").strip()
    return music_const, is_female


@api_route("GET", r"/api/trainers/(?P<const>TRAINER_[A-Za-z0-9_]+)")
def handle_trainer_detail(handler, match, query_params):
    """Return full trainer detail including party."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    ok, err = _check_party_format(handler)
    if not ok:
        return err

    trainer_const = match.group("const")

    from torch.battle_io import _read_trainer_record_party, _read_pory_dialogue
    from torch.gamedata import (
        classify_trainers, load_move_names, load_ability_names,
        load_move_data, load_form_tables, load_species_data,
    )
    from torch.names import (
        _const_to_human_name, _const_to_species_name, _const_to_move_name,
        _const_to_item_name, _const_to_ability_name, _const_to_nature_name,
        _ai_flags_to_party_format,
    )

    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    opponents_path = os.path.join(game_path, "include", "constants", "opponents.h")

    record = _read_trainer_record_party(trainer_const, party_path, opponents_path)
    if record is None:
        return error_response(f"Trainer '{trainer_const}' not found", 404)

    _, custom_ids = classify_trainers(game_path)
    is_custom = trainer_const in custom_ids

    # Format AI flags for display
    ai_raw = record.get("ai_flags") or ""
    ai_display = _ai_flags_to_party_format(ai_raw) if ai_raw else ""

    # Format items
    items_raw = record.get("trainer_items") or []
    items_display = [_const_to_item_name(i) for i in items_raw if i]

    # Resolve sprite path via INCBIN map
    pic_const = record.get("trainer_pic")
    sprite_path = _resolve_trainer_sprite(pic_const, game_path)

    # Build party array
    name_funcs = {
        "move": _const_to_move_name, "species": _const_to_species_name,
        "item": _const_to_item_name, "ability": _const_to_ability_name,
        "nature": _const_to_nature_name,
    }
    party = _build_party_array(
        record, game_path, load_move_data(game_path),
        load_form_tables(game_path), name_funcs,
        species_data=load_species_data(game_path),
    )

    # Try to read dialogue
    dialogue = {"intro": None, "defeat": None}
    if is_custom:
        project_dir = getattr(handler.server, "project_dir", "")
        if project_dir:
            pory_path = _find_pory_file(project_dir, trainer_const)
            if pory_path:
                dialogue = _read_pory_dialogue(pory_path)

    class_const = record.get("trainer_class")
    music_const, is_female_music = _parse_encounter_music(
        record.get("encounter_music") or "",
    )

    return ok_response({
        "const": trainer_const,
        "id": record.get("trainer_id"),
        "name": record.get("trainer_name"),
        "class": _const_to_human_name(class_const, "TRAINER_CLASS_") if class_const else None,
        "class_const": class_const,
        "pic_const": pic_const,
        "sprite_path": sprite_path,
        "is_double": record.get("is_double", False),
        "is_custom": is_custom,
        "ai_flags": ai_display,
        "ai_flags_raw": ai_raw,
        "items": items_display,
        "items_raw": items_raw,
        "party": party,
        "dialogue": dialogue,
        "encounter_music": music_const,
        "encounter_music_name": _const_to_human_name(music_const, "TRAINER_ENCOUNTER_MUSIC_") if music_const else None,
        "is_female_music": is_female_music,
    })


# ---------------------------------------------------------------------------
# Showdown team parser (S217)
# ---------------------------------------------------------------------------

@api_route("POST", "/api/trainers/parse-showdown")
def handle_parse_showdown(handler, match, query_params):
    """Parse a Showdown team export and return structured Pokemon data."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if body is None:
        return error_response("Request body required", 400)

    text = body.get("text", "")
    if not text.strip():
        return ok_response({"pokemon": [], "warnings": [], "count": 0})

    from torch.battle_wizard import _parse_showdown_team
    from torch.gamedata import (
        load_species_data, load_move_names, load_items,
        load_ability_names, load_form_tables,
    )
    from torch.names import (
        _const_to_species_name, _const_to_move_name,
        _const_to_item_name, _const_to_ability_name, _const_to_nature_name,
    )

    species_data = load_species_data(game_path)
    species_set = set(species_data.keys())
    move_names = load_move_names(game_path)
    moves_set = set(move_names.keys())
    items_list = load_items(game_path)
    items_set = {name for name, _ in items_list}
    ability_names = load_ability_names(game_path)
    abilities_set = set(ability_names.keys())

    warnings = []
    mons = _parse_showdown_team(
        text, species_set, items_set, moves_set, abilities_set,
        warnings=warnings,
    )

    form_tables = load_form_tables(game_path)
    result = []
    for mon in mons:
        species = mon.get("species") or ""
        moves = []
        for mc in (mon.get("moves") or []):
            moves.append({"const": mc, "name": _const_to_move_name(mc)})

        # Build EV/IV dicts with defaults
        evs = mon.get("evs") or {}
        ivs = mon.get("ivs") or {}

        result.append({
            "species": species,
            "species_name": _const_to_species_name(species),
            "sprite_path": _species_to_sprite_path(species, form_tables, game_path),
            "level": mon.get("level", 100),
            "held_item": mon.get("held_item"),
            "held_item_name": _const_to_item_name(mon.get("held_item") or ""),
            "moves": moves,
            "ability": mon.get("ability"),
            "ability_name": _const_to_ability_name(mon.get("ability") or ""),
            "evs": evs,
            "ivs": ivs,
            "nature": mon.get("nature"),
            "nature_name": _const_to_nature_name(mon.get("nature") or ""),
            "gender": mon.get("gender"),
            "shiny": mon.get("shiny", False),
        })

    return ok_response({
        "pokemon": result,
        "warnings": warnings,
        "count": len(result),
    })


# ---------------------------------------------------------------------------
# Trainer write-back (S182)
# ---------------------------------------------------------------------------

def _find_party_file_for_trainer(game_path, trainer_const):
    """Locate the .party file containing a given TRAINER_* constant.

    Scans src/data/trainers/*.party, then falls back to the monolithic
    src/data/trainers.party.  Returns the path or None.
    """
    trainers_dir = os.path.join(game_path, "src", "data", "trainers")
    if os.path.isdir(trainers_dir):
        for fname in os.listdir(trainers_dir):
            if not fname.endswith(".party"):
                continue
            fpath = os.path.join(trainers_dir, fname)
            try:
                with open(fpath, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.strip() == f"=== {trainer_const} ===":
                            return fpath
            except OSError:
                continue

    # Fallback: monolithic trainers.party
    mono = os.path.join(game_path, "src", "data", "trainers.party")
    if os.path.isfile(mono):
        try:
            with open(mono, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.strip() == f"=== {trainer_const} ===":
                        return mono
        except OSError:
            pass
    return None


def _validate_trainer_payload(payload, url_const):
    """Validate a POST trainer save payload.

    Returns (cleaned_data, error_message).  error_message is None on success.
    """
    if not isinstance(payload, dict):
        return None, "Payload must be a JSON object"

    tc = payload.get("trainer_const", "")
    if tc != url_const:
        return None, f"trainer_const must match URL ({url_const})"

    # Name
    name = payload.get("trainer_name")
    if name is not None:
        if not isinstance(name, str) or len(name) < 1 or len(name) > 15:
            return None, "trainer_name must be 1-15 characters"

    # Party
    mons = payload.get("mons")
    if not isinstance(mons, list) or len(mons) < 1 or len(mons) > 6:
        return None, "mons must be an array of 1-6 Pokemon"

    for i, mon in enumerate(mons):
        if not isinstance(mon, dict):
            return None, f"mons[{i}] must be an object"
        species = mon.get("species")
        if not isinstance(species, str) or not species.startswith("SPECIES_"):
            return None, f"mons[{i}].species must be a valid SPECIES_* constant"
        level = mon.get("level")
        if not isinstance(level, int) or level < 1 or level > 100:
            return None, f"mons[{i}].level must be 1-100"

        # Moves
        moves = mon.get("moves")
        if moves is not None:
            if not isinstance(moves, list) or len(moves) > 4:
                return None, f"mons[{i}].moves must be an array of 0-4 moves"

        # EVs
        evs = mon.get("evs")
        if evs and isinstance(evs, dict):
            for stat in ("hp", "atk", "def", "spa", "spd", "spe"):
                v = evs.get(stat, 0)
                if not isinstance(v, int) or v < 0 or v > 255:
                    return None, f"mons[{i}].evs.{stat} must be 0-255"

        # IVs
        ivs = mon.get("ivs")
        if ivs and isinstance(ivs, dict):
            for stat in ("hp", "atk", "def", "spa", "spd", "spe"):
                v = ivs.get(stat, 0)
                if not isinstance(v, int) or v < 0 or v > 31:
                    return None, f"mons[{i}].ivs.{stat} must be 0-31"

    return payload, None


def _build_record_from_payload(payload):
    """Convert a JSON payload into a record dict matching battle_io's format."""
    record = {
        "trainer_const": payload["trainer_const"],
        "trainer_name": payload.get("trainer_name", ""),
        "trainer_class": payload.get("trainer_class", ""),
        "trainer_pic": payload.get("trainer_pic", ""),
        "is_double": payload.get("is_double", False),
    }

    # AI flags: accept pipe-separated string
    ai_raw = payload.get("ai_flags", "")
    if ai_raw:
        # Normalize: strip whitespace around pipes, ensure AI_FLAG_ prefix
        parts = [f.strip() for f in ai_raw.split("|") if f.strip()]
        record["ai_flags"] = " | ".join(parts)
    else:
        record["ai_flags"] = ""

    # Encounter music
    enc_music = payload.get("encounter_music", "")
    is_female = payload.get("is_female_music", False)
    if enc_music and is_female:
        record["encounter_music"] = f"F_TRAINER_FEMALE | {enc_music}"
    elif enc_music:
        record["encounter_music"] = enc_music

    # Items
    items = payload.get("trainer_items", [])
    if isinstance(items, list):
        record["trainer_items"] = [i for i in items if i and i != "ITEM_NONE"]

    # Mons
    mons = []
    for pm in payload.get("mons", []):
        mon = {
            "species": pm["species"],
            "level": pm["level"],
        }
        if pm.get("held_item") and pm["held_item"] != "ITEM_NONE":
            mon["held_item"] = pm["held_item"]
        if pm.get("moves"):
            mon["moves"] = [m for m in pm["moves"] if m and m != "MOVE_NONE"]
        if pm.get("ability") and pm["ability"] != "ABILITY_NONE":
            mon["ability"] = pm["ability"]
        if pm.get("evs") and isinstance(pm["evs"], dict):
            mon["evs"] = pm["evs"]
        if pm.get("ivs") and isinstance(pm["ivs"], dict):
            mon["ivs"] = pm["ivs"]
        if pm.get("nature"):
            mon["nature"] = pm["nature"]
        if pm.get("gender"):
            mon["gender"] = pm["gender"]
        if pm.get("shiny"):
            mon["shiny"] = True
        if pm.get("ball"):
            mon["ball"] = pm["ball"]
        if pm.get("nickname"):
            mon["nickname"] = pm["nickname"]
        mons.append(mon)
    record["mons"] = mons

    return record


def _find_pory_file(project_dir, trainer_const):
    """Find the battle_TRAINER_*.pory file for a trainer in the workspace."""
    filename = f"battle_{trainer_const}.pory"
    for root, dirs, files in os.walk(project_dir):
        if filename in files:
            return os.path.join(root, filename)
    return None


def _save_trainer_dialogue(project_dir, trainer_const, dialogue):
    """Write dialogue (intro/defeat) back to the battle pory file.

    Updates existing text blocks in-place using regex replacement.
    If no pory file exists, does nothing (creating new battle scripts
    from scratch requires the full wizard flow).
    """
    pory_path = _find_pory_file(project_dir, trainer_const)
    if not pory_path:
        return False

    try:
        with open(pory_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return False

    # Pattern matches: text LABEL { "content" }
    pattern = re.compile(r'(text\s+(\w+)\s*\{\s*")([^"]*?)("\s*\})', re.DOTALL)

    def replacer(m):
        label = m.group(2).lower()
        new_text = None
        if "intro" in label and dialogue.get("intro"):
            new_text = dialogue["intro"]
        elif "defeat" in label and dialogue.get("defeat"):
            new_text = dialogue["defeat"]

        if new_text is not None:
            return m.group(1) + new_text + m.group(4)
        return m.group(0)

    updated = pattern.sub(replacer, content)

    if updated == content:
        return True  # nothing changed

    try:
        _atomic_write(pory_path, updated)
    except OSError:
        return False
    return True


@api_route("POST", r"/api/trainers/(?P<const>TRAINER_[A-Za-z0-9_]+)")
def handle_trainer_save(handler, match, query_params):
    """Save trainer changes (full record: header + party)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    ok, err = _check_party_format(handler)
    if not ok:
        return err

    trainer_const = match.group("const")

    try:
        payload = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if payload is None:
        return error_response("Request body required", 400)

    cleaned, err = _validate_trainer_payload(payload, trainer_const)
    if err:
        return error_response(err, 400)

    party_path = _find_party_file_for_trainer(game_path, trainer_const)
    if not party_path:
        return error_response(f"Could not find .party file for {trainer_const}", 404)

    record = _build_record_from_payload(cleaned)
    expansion_version = getattr(handler.server, "expansion_version", None)

    from torch.battle_io import _replace_trainer_in_party_file
    ok = _replace_trainer_in_party_file(party_path, trainer_const, record,
                                        expansion_version=expansion_version)
    if not ok:
        return error_response("Failed to write trainer data", 500)

    # Save dialogue if included
    dialogue = payload.get("dialogue")
    if isinstance(dialogue, dict) and (dialogue.get("intro") or dialogue.get("defeat")):
        project_dir = getattr(handler.server, "project_dir", "")
        if project_dir:
            _save_trainer_dialogue(project_dir, trainer_const, dialogue)

    # Invalidate trainer caches
    _trainer_list_cache.pop(game_path, None)
    _trainer_incbin_cache.pop(game_path, None)

    return ok_response({"saved": True, "trainer": trainer_const})


@api_route("POST", r"/api/trainers/(?P<const>TRAINER_[A-Za-z0-9_]+)/party")
def handle_trainer_party_save(handler, match, query_params):
    """Save only party changes (lighter operation, keeps headers)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    ok, err = _check_party_format(handler)
    if not ok:
        return err

    trainer_const = match.group("const")

    try:
        payload = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if payload is None:
        return error_response("Request body required", 400)

    mons = payload.get("mons")
    if not isinstance(mons, list) or len(mons) < 1 or len(mons) > 6:
        return error_response("mons must be an array of 1-6 Pokemon", 400)

    party_path = _find_party_file_for_trainer(game_path, trainer_const)
    if not party_path:
        return error_response(f"Could not find .party file for {trainer_const}", 404)

    # Build mon dicts
    new_mons = []
    for pm in mons:
        mon = {"species": pm.get("species", ""), "level": pm.get("level", 5)}
        if pm.get("held_item"): mon["held_item"] = pm["held_item"]
        if pm.get("moves"): mon["moves"] = pm["moves"]
        if pm.get("ability"): mon["ability"] = pm["ability"]
        if pm.get("evs"): mon["evs"] = pm["evs"]
        if pm.get("ivs"): mon["ivs"] = pm["ivs"]
        if pm.get("nature"): mon["nature"] = pm["nature"]
        if pm.get("gender"): mon["gender"] = pm["gender"]
        if pm.get("shiny"): mon["shiny"] = True
        if pm.get("ball"): mon["ball"] = pm["ball"]
        if pm.get("nickname"): mon["nickname"] = pm["nickname"]
        new_mons.append(mon)

    from torch.battle_io import _replace_party_in_party_file
    ok = _replace_party_in_party_file(party_path, trainer_const, new_mons)
    if not ok:
        return error_response("Failed to write party data", 500)

    _trainer_list_cache.pop(game_path, None)
    _trainer_incbin_cache.pop(game_path, None)
    return ok_response({"saved": True, "trainer": trainer_const})


# ---------------------------------------------------------------------------
# Move & Item search endpoints (S182)
# ---------------------------------------------------------------------------

_move_list_cache = {}
_item_list_cache = {}
_ability_list_cache = {}
_item_icon_map_cache = {}  # game_path -> {ITEM_CONST: "filename.png"}
_holdable_items_cache = {}  # game_path -> set of ITEM_CONST with holdEffect


@api_route("GET", "/api/abilities")
def handle_ability_list(handler, match, query_params):
    """Return ability list with descriptions."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    if game_path not in _ability_list_cache:
        from torch.gamedata import load_ability_names, load_ability_descriptions
        names = load_ability_names(game_path)
        descs = load_ability_descriptions(game_path)
        _ability_list_cache[game_path] = [
            {"const": c, "name": n, "description": descs.get(c, "")}
            for c, n in sorted(names.items(), key=lambda x: x[1])
            if c != "ABILITY_NONE"
        ]

    q = query_params.get("q", [""])[0].lower()
    result = _ability_list_cache[game_path]
    if q:
        result = [a for a in result
                  if q in a["name"].lower() or q in a["const"].lower()
                  or q in a.get("description", "").lower()]

    return ok_response(result)


@api_route("GET", "/api/moves")
def handle_move_list(handler, match, query_params):
    """Return move list with full data for the move browser."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    if game_path not in _move_list_cache:
        from torch.gamedata import load_move_names, load_move_data
        names = load_move_names(game_path)
        data = load_move_data(game_path)
        items = []
        for c, n in sorted(names.items(), key=lambda x: x[1]):
            if c == "MOVE_NONE":
                continue
            d = data.get(c, {})
            items.append({
                "const": c,
                "name": d.get("name") or n,
                "type": d.get("type", "Normal"),
                "category": d.get("category", "Physical"),
                "power": d.get("power", 0),
                "accuracy": d.get("accuracy", 0),
                "pp": d.get("pp", 0),
                "description": d.get("description", ""),
            })
        _move_list_cache[game_path] = items

    q = query_params.get("q", [""])[0].lower()
    result = _move_list_cache[game_path]
    if q:
        result = [m for m in result
                  if q in m["name"].lower() or q in m["const"].lower()
                  or q in m.get("type", "").lower()]

    return ok_response(result)


@api_route("GET", "/api/items")
def handle_item_list(handler, match, query_params):
    """Return item list for the item/held item picker."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    if game_path not in _item_list_cache:
        from torch.gamedata import load_items
        from torch.names import _const_to_item_name
        raw = load_items(game_path)
        _item_list_cache[game_path] = [
            {"const": name, "name": _const_to_item_name(name),
             "icon": f"/api/items/icons/{name}"}
            for name, _comment in raw
        ]

    q = query_params.get("q", [""])[0].lower()
    holdable_only = query_params.get("holdable", [""])[0] == "1"
    result = _item_list_cache[game_path]

    if holdable_only:
        if game_path not in _holdable_items_cache:
            _holdable_items_cache[game_path] = (
                _build_holdable_items_set(game_path))
        holdable = _holdable_items_cache[game_path]
        result = [i for i in result if i["const"] in holdable]

    if q:
        result = [i for i in result
                  if q in i["name"].lower() or q in i["const"].lower()]

    return ok_response(result)


def _build_item_icon_map(game_path):
    """Build ITEM_CONST -> icon filename mapping from game source files.

    Parses items.h for ITEM_X -> gItemIcon_Y associations, then
    graphics/items.h for gItemIcon_Y -> filename.png associations.
    Falls back to naive ITEM_X -> x.png for items not found.
    """
    icon_map = {}

    # Step 1: gItemIcon_X -> filename from graphics/items.h
    symbol_to_file = {}
    gfx_items_h = os.path.join(
        game_path, "src", "data", "graphics", "items.h")
    if os.path.isfile(gfx_items_h):
        try:
            text = open(gfx_items_h, encoding="utf-8",
                        errors="replace").read()
            for m in re.findall(
                    r'const u32 (\w+)\[\]\s*=\s*INCBIN_U32\('
                    r'"graphics/items/icons/(\w+)\.', text):
                symbol_to_file[m[0]] = m[1] + ".png"
        except OSError:
            pass

    # Step 2: ITEM_X -> gItemIcon_Y from items.h
    items_h = os.path.join(game_path, "src", "data", "items.h")
    if os.path.isfile(items_h):
        try:
            text = open(items_h, encoding="utf-8",
                        errors="replace").read()
            for m in re.findall(
                    r'\[(\w+)\]\s*=\s*\{[^}]*?\.iconPic\s*=\s*(\w+)',
                    text, re.DOTALL):
                item_const, icon_sym = m
                filename = symbol_to_file.get(icon_sym)
                if filename:
                    icon_map[item_const] = filename
        except OSError:
            pass

    return icon_map


def _build_holdable_items_set(game_path):
    """Return set of ITEM_X constants that have a meaningful holdEffect."""
    holdable = set()
    items_h = os.path.join(game_path, "src", "data", "items.h")
    if not os.path.isfile(items_h):
        return holdable
    try:
        text = open(items_h, encoding="utf-8", errors="replace").read()
        for m in re.findall(
                r'\[(\w+)\]\s*=\s*\{([^}]+)\}', text, re.DOTALL):
            item_const, body = m
            if ".holdEffect =" in body and "HOLD_EFFECT_NONE" not in body:
                holdable.add(item_const)
    except OSError:
        pass
    return holdable


@api_route("GET", r"/api/items/icons/(?P<item_const>[A-Za-z0-9_]+)")
def handle_item_icon(handler, match, query_params):
    """Serve an item icon PNG from the game graphics directory."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        handler.send_error(404, "Not Found")
        return None

    item_const = match.group("item_const")

    # Build or retrieve the icon mapping
    if game_path not in _item_icon_map_cache:
        _item_icon_map_cache[game_path] = _build_item_icon_map(game_path)
    icon_map = _item_icon_map_cache[game_path]

    # Look up proper filename; fall back to naive ITEM_X -> x.png
    filename = icon_map.get(item_const)
    if not filename:
        name = item_const
        if name.startswith("ITEM_"):
            name = name[5:]
        filename = name.lower() + ".png"

    icons_dir = os.path.join(game_path, "graphics", "items", "icons")
    try:
        full_path = _safe_path(icons_dir, filename)
    except ValueError:
        handler.send_error(403, "Forbidden")
        return None

    if not full_path.endswith(".png"):
        handler.send_error(403, "Forbidden")
        return None

    # Fallback to question_mark.png if icon not found
    if not os.path.isfile(full_path):
        full_path = _safe_path(icons_dir, "question_mark.png")
        if not os.path.isfile(full_path):
            handler.send_error(404, "Not Found")
            return None

    try:
        with open(full_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_error(500, "Read error")
        return None

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)
    return None


# ---------------------------------------------------------------------------
# Studio endpoints
# ---------------------------------------------------------------------------

_studio_maps_cache = {}  # game_path -> (maps_list, counts_dict)


def _build_studio_map_list(game_path, project_dir):
    """Build the enriched studio map list, caching the result."""
    cache_key = game_path
    if cache_key in _studio_maps_cache:
        return _studio_maps_cache[cache_key]

    from torch.map_scanner import _scan_game_maps
    from torch.project_files import classify_maps, load_wild_encounters, folder_to_map_const
    from torch.registry import get_map_health

    scan = _scan_game_maps(game_path, project_dir)
    _, custom_set = classify_maps(game_path)

    # Build trainer count per map (bulk, one scan)
    trainer_index = {}
    try:
        from torch.project_files import build_trainer_map_index
        trainer_index, _ = build_trainer_map_index(game_path)
    except Exception:
        pass

    # Build encounter presence set (bulk, one load)
    enc_maps = set()
    try:
        encounters_data = load_wild_encounters(game_path)
        if encounters_data:
            for group in encounters_data.get("wild_encounter_groups", []):
                for entry in group.get("encounters", []):
                    enc_maps.add(entry.get("map", ""))
    except Exception:
        pass

    maps_out = []
    counts = {"total": 0, "active": 0, "custom": 0, "vanilla": 0, "orphan": 0}

    for m in scan:
        name = m["name"]
        status = m.get("status", "VANILLA")
        is_custom = name in custom_set
        enrolled = m.get("enrolled", False)

        health = None
        if enrolled:
            try:
                health = get_map_health(project_dir, name, game_path)
            except Exception:
                pass

        map_const = folder_to_map_const(name)
        has_encounters = map_const in enc_maps
        trainer_count = len(trainer_index.get(name, []))

        maps_out.append({
            "name": name,
            "status": status,
            "is_custom": is_custom,
            "enrolled": enrolled,
            "health": health,
            "script_count": m.get("script_count", 0),
            "trainer_count": trainer_count,
            "has_encounters": has_encounters,
        })

        counts["total"] += 1
        key = status.lower()
        if key in counts:
            counts[key] += 1

    # Sort: active first, then custom, then vanilla, orphan last
    status_order = {"ACTIVE": 0, "CUSTOM": 1, "VANILLA": 2, "ORPHAN": 3}
    maps_out.sort(key=lambda m: (status_order.get(m["status"], 9), m["name"]))

    result = (maps_out, counts)
    _studio_maps_cache[cache_key] = result
    return result


@api_route("GET", "/api/studio/maps")
def handle_studio_maps(handler, match, query_params):
    """Enriched map list for the Studio Hub."""
    server = handler.server
    game_path = getattr(server, "game_path", "")
    project_dir = getattr(server, "project_dir", "")

    if not game_path:
        return error_response("No game path configured", 500)

    try:
        maps_list, counts = _build_studio_map_list(game_path, project_dir)
    except Exception as exc:
        return error_response(f"Failed to scan maps: {exc}", 500)

    return ok_response({"maps": maps_list, "counts": counts})


@api_route("GET", r"/api/studio/maps/(?P<map_name>[A-Za-z0-9_]+)")
def handle_studio_map_detail(handler, match, query_params):
    """Full detail for one map."""
    server = handler.server
    game_path = getattr(server, "game_path", "")
    project_dir = getattr(server, "project_dir", "")
    map_name = match.group("map_name")

    if not game_path:
        return error_response("No game path configured", 500)

    from torch.project_files import load_map_json, load_map_groups, classify_maps
    from torch.registry import get_map_health, is_enrolled

    data = load_map_json(game_path, map_name)
    if data is None:
        return error_response(f"Map '{map_name}' not found", 404)

    # Rich metadata
    try:
        from torch.map_scanner import _read_map_metadata
        meta = _read_map_metadata(game_path, map_name)
    except Exception:
        meta = {}

    _, custom_set = classify_maps(game_path)
    enrolled = is_enrolled(project_dir, map_name)

    # Auto-enroll maps when loaded in Studio (idempotent, fast)
    if not enrolled and project_dir:
        try:
            from torch.registry import enroll_map
            enroll_map(project_dir, map_name)
            enrolled = True
        except Exception:
            pass

    health = None
    if enrolled:
        try:
            health = get_map_health(project_dir, map_name, game_path)
        except Exception:
            pass

    # Parse connectivity from map JSON
    connections = []
    warps = []
    try:
        from torch.map_explorer import _parse_warp_events, _parse_connections
        from torch.cleanup_scanner import build_map_const_lookup

        group_data = load_map_groups(game_path)
        const_to_name = {}
        if group_data:
            try:
                const_to_name = build_map_const_lookup(game_path, group_data)
            except Exception:
                pass

        _, raw_warps = _parse_warp_events(data, map_name, const_to_name)
        warps = [{"dest_map": w.get("dest_map", ""), "x": w.get("x", 0), "y": w.get("y", 0)}
                 for w in raw_warps if w.get("dest_map")]

        _, raw_conns = _parse_connections(data, map_name, const_to_name)
        connections = [{"map": c.get("map", ""), "direction": c.get("direction", "")}
                       for c in raw_conns if c.get("map")]
    except Exception:
        pass

    return ok_response({
        "name": map_name,
        "is_custom": map_name in custom_set,
        "enrolled": enrolled,
        "health": health,
        "npc_count": meta.get("npc_count", 0),
        "npc_names": meta.get("npc_names", []),
        "trainer_count": meta.get("trainer_count", 0),
        "trainer_consts": meta.get("trainer_consts", []),
        "encounter_types": meta.get("encounter_types", []),
        "encounter_detail": meta.get("encounter_detail", {}),
        "heal_count": meta.get("heal_count", 0),
        "connections": connections,
        "warps": warps,
    })


@api_route("POST", r"/api/studio/maps/(?P<map_name>[A-Za-z0-9_]+)/enroll")
def handle_map_enroll(handler, match, query_params):
    """Enroll a map in the TORCH registry."""
    map_name = match.group("map_name")
    project_dir = getattr(handler.server, "project_dir", "")
    if not project_dir:
        return error_response("No project directory configured", 500)

    from torch.registry import enroll_map
    newly_enrolled = enroll_map(project_dir, map_name)

    # Invalidate studio maps cache so next list fetch reflects the change
    _studio_maps_cache.clear()

    return ok_response({
        "map_name": map_name,
        "enrolled": True,
        "newly_enrolled": newly_enrolled,
    })


@api_route("POST", r"/api/studio/maps/(?P<map_name>[A-Za-z0-9_]+)/unenroll")
def handle_map_unenroll(handler, match, query_params):
    """Remove a map from the TORCH registry."""
    map_name = match.group("map_name")
    project_dir = getattr(handler.server, "project_dir", "")
    if not project_dir:
        return error_response("No project directory configured", 500)

    from torch.registry import unenroll_map
    was_enrolled = unenroll_map(project_dir, map_name)

    # Invalidate studio maps cache so next list fetch reflects the change
    _studio_maps_cache.clear()

    if not was_enrolled:
        return ok_response({
            "map_name": map_name,
            "enrolled": False,
            "message": f"{map_name} was not enrolled.",
        })

    return ok_response({
        "map_name": map_name,
        "enrolled": False,
        "message": f"{map_name} unenrolled.",
    })


# ---------------------------------------------------------------------------
# Settings (Config Tuner) endpoints
# ---------------------------------------------------------------------------

def _filter_enum_constants(settings_list):
    """Remove noise from settings lists: enum value constants, cascading
    child defines, bare identity defines, and GEN_ aliases.

    Keeps: settings with direct values (TRUE/FALSE/int/GEN_X) and settings
    whose value is a const expression but that are NOT themselves used only
    as an option for another setting.
    """
    # 1. Collect names referenced in [OPTION_A, OPTION_B, ...] comment patterns
    enum_names = set()
    bracket_re = re.compile(r'\[([A-Z_][A-Z0-9_, ]+)\]')
    for _name, _value, comment, _vtype in settings_list:
        for m in bracket_re.finditer(comment):
            for opt in m.group(1).split(","):
                opt = opt.strip()
                if opt:
                    enum_names.add(opt)

    # 2. Build a lookup: name -> (value, vtype) for cross-referencing
    by_name = {name: (value.strip(), vtype) for name, value, _c, vtype in settings_list}

    # 3. Identify cascading child defines whose value references another
    #    define. These inherit from a parent toggle and aren't directly
    #    editable — filter them all. The parent toggles (with direct
    #    TRUE/FALSE/GEN_*/int values) are the ones users should edit.
    cascading_children = set()
    for name, value, _comment, vtype in settings_list:
        v = value.strip()
        if re.match(r'^[A-Z][A-Z0-9_]+$', v) and v in by_name:
            cascading_children.add(name)

    # 4. Identify enum value constants: names referenced in bracket lists
    #    OR names whose value is a small integer AND they're referenced as
    #    the value of another setting
    setting_values = set()
    for _name, value, _comment, _vtype in settings_list:
        v = value.strip()
        if re.match(r'^[A-Z][A-Z0-9_]+$', v):
            setting_values.add(v)

    enum_int_consts = set()
    for name, value, _comment, vtype in settings_list:
        if name in setting_values and vtype[0] == "int":
            enum_int_consts.add(name)

    return [s for s in settings_list
            if s[0] not in enum_names
            and s[0] not in enum_int_consts
            and s[0] not in cascading_children
            and s[1].strip() != ""          # bare #define NAME (identity/guard)
            and not s[0].startswith("GEN_") # GEN_ aliases, not user settings
            ]


def _serialize_parsed(kind, parsed):
    """Convert a config_tuner parsed value to a JSON-safe representation."""
    if kind == "bool":
        return parsed  # True/False -> native JSON bool
    if kind == "int":
        return parsed  # int
    if kind == "rom_field":
        # parsed is the field dict from studio.read_rom_fields
        return {
            "key": parsed.get("key", ""),
            "label": parsed.get("label", ""),
            "value": parsed.get("value", ""),
            "max_len": parsed.get("max_len", 0),
        }
    # gen, flag_var, const — all strings
    return str(parsed)


@api_route("GET", "/api/settings/categories")
def handle_settings_categories(handler, match, query_params):
    """Return all config categories with their settings."""
    game_path = getattr(handler.server, "game_path", "")
    project_dir = getattr(handler.server, "project_dir", "")

    from torch.config_tuner import _discover_categories

    try:
        categories = _discover_categories(game_path, project_dir)
    except Exception as exc:
        return error_response(f"Failed to load settings: {exc}", 500)

    # Skip test.h — it's a test harness that re-defines everything, not user config
    _SKIP_FILES = {"test.h"}

    result = []
    for display_name, filepath, settings_list in categories:
        if isinstance(filepath, str) and os.path.basename(filepath) in _SKIP_FILES:
            continue
        filtered = _filter_enum_constants(settings_list)
        items = []
        for name, value, comment, vtype in filtered:
            kind, parsed = vtype
            items.append({
                "name": name,
                "value": value,
                "comment": comment,
                "type": kind,
                "parsed": _serialize_parsed(kind, parsed),
            })
        result.append({
            "name": display_name,
            "file": filepath,
            "count": len(items),
            "settings": items,
        })
    return ok_response({"categories": result})


@api_route("GET", "/api/settings/search")
def handle_settings_search(handler, match, query_params):
    """Search across all config categories."""
    q = query_params.get("q", [""])[0]
    if not q:
        return error_response("Missing search query 'q'")

    game_path = getattr(handler.server, "game_path", "")
    project_dir = getattr(handler.server, "project_dir", "")

    from torch.config_tuner import _discover_categories, _search_all

    try:
        categories = _discover_categories(game_path, project_dir)
        # Filter enum constants before searching
        filtered_cats = [(name, fpath, _filter_enum_constants(slist))
                         for name, fpath, slist in categories]
        results = _search_all(filtered_cats, q)
    except Exception as exc:
        return error_response(f"Search failed: {exc}", 500)

    items = []
    for cat, name, value, comment, vtype, fpath in results:
        kind, parsed = vtype
        items.append({
            "category": cat,
            "name": name,
            "value": value,
            "comment": comment,
            "type": kind,
            "parsed": _serialize_parsed(kind, parsed),
            "file": fpath,
        })
    return ok_response({"query": q, "results": items})


@api_route("POST", "/api/settings/save")
def handle_settings_save(handler, match, query_params):
    """Save config setting changes."""
    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if body is None:
        return error_response("Request body required", 400)

    changes = body.get("changes", [])
    if not changes:
        return error_response("No changes provided")

    game_path = getattr(handler.server, "game_path", "")

    from torch.filewriter import patch_define
    from torch.gamedata import clear_gamedata_cache

    config_dir = os.path.join(game_path, "include", "config")

    results = []
    for change in changes:
        filepath = change.get("file", "")
        name = change.get("name", "")
        new_value = change.get("value", "")

        # Security: only allow writing to files under include/config/
        if not os.path.realpath(filepath).startswith(
            os.path.realpath(config_dir) + os.sep
        ):
            results.append({"name": name, "ok": False, "error": "Invalid file path"})
            continue

        ok = patch_define(filepath, name, new_value)
        results.append({"name": name, "ok": ok})

    clear_gamedata_cache()

    success = sum(1 for r in results if r.get("ok"))
    failed = sum(1 for r in results if not r.get("ok"))
    return ok_response({"saved": success, "failed": failed, "results": results})


@api_route("POST", "/api/settings/rom")
def handle_settings_rom_save(handler, match, query_params):
    """Save a ROM metadata field."""
    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if body is None:
        return error_response("Request body required", 400)

    key = body.get("key", "")
    value = body.get("value", "")
    if not key:
        return error_response("Missing 'key'")

    game_path = getattr(handler.server, "game_path", "")
    project_dir = getattr(handler.server, "project_dir", "")

    try:
        from torch.studio import write_rom_field
        ok, msg = write_rom_field(game_path, project_dir, key, value)
        if ok:
            return ok_response({"key": key, "message": msg})
        return error_response(msg)
    except ImportError:
        return error_response("ROM field support not available", 501)


# ---------------------------------------------------------------------------
# Data Endpoints — Pickers for flags, sounds, music, emotes, specials
# ---------------------------------------------------------------------------

_data_cache = {}  # key -> list


def _parse_defines(game_path, filepath, prefix):
    """Parse #define lines matching a prefix from a header file.

    Returns list of constant names (strings).
    """
    cache_key = (game_path, filepath, prefix)
    if cache_key in _data_cache:
        return _data_cache[cache_key]

    full = os.path.join(game_path, filepath)
    results = []
    try:
        with open(full, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("#define "):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1].startswith(prefix):
                    results.append(parts[1])
    except OSError:
        pass

    _data_cache[cache_key] = results
    return results


def _display_name(const, prefix):
    """Strip prefix and title-case: SE_BALL_OPEN -> Ball Open."""
    name = const[len(prefix):]
    return name.replace("_", " ").title()


@api_route("GET", "/api/data/emotes")
def handle_data_emotes(handler, match, query_params):
    """Return available emote constants (builtin + custom)."""
    from torch.data import BUILTIN_EMOTES

    emotes = []
    for name, movement in BUILTIN_EMOTES.items():
        emotes.append({"name": name, "movement": movement, "builtin": True})

    # Read custom emotes from emotes.conf
    conf_path = os.path.expanduser("~/ROMHacking/TORCH/config/emotes.conf")
    try:
        with open(conf_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    parts = line.split("=", 1)
                    name = parts[0].strip()
                    movement = parts[1].strip()
                    if name and movement:
                        emotes.append({"name": name, "movement": movement,
                                       "builtin": False})
    except OSError:
        pass

    return ok_response({"emotes": emotes})


@api_route("GET", "/api/data/sounds")
def handle_data_sounds(handler, match, query_params):
    """Return SE_* sound effect constants from songs.h."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    consts = _parse_defines(game_path, "include/constants/songs.h", "SE_")
    sounds = [{"const": c, "display": _display_name(c, "SE_")} for c in consts]
    return ok_response({"sounds": sounds})


@api_route("GET", "/api/data/music")
def handle_data_music(handler, match, query_params):
    """Return MUS_* music constants from songs.h."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    consts = _parse_defines(game_path, "include/constants/songs.h", "MUS_")
    music = [{"const": c, "display": _display_name(c, "MUS_")} for c in consts]
    return ok_response({"music": music})


@api_route("GET", "/api/data/flags")
def handle_data_flags(handler, match, query_params):
    """Return FLAG_* constants from flags.h."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    consts = _parse_defines(game_path, "include/constants/flags.h", "FLAG_")
    # Skip raw hex system flags (FLAG_0x000 through FLAG_0x0FF)
    hex_pat = re.compile(r"^FLAG_0x[0-9A-Fa-f]+$")
    flags = []
    for c in consts:
        if hex_pat.match(c):
            continue
        flags.append({"const": c, "display": c[len("FLAG_"):].replace("_", " ")})
    return ok_response({"flags": flags})


@api_route("GET", "/api/data/specials")
def handle_data_specials(handler, match, query_params):
    """Return special function names from data/specials.inc."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    cache_key = (game_path, "specials")
    if cache_key in _data_cache:
        specials = _data_cache[cache_key]
    else:
        specials = []
        filepath = os.path.join(game_path, "data", "specials.inc")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("def_special "):
                        parts = line.split()
                        if len(parts) >= 2:
                            specials.append(parts[1])
        except OSError:
            pass
        _data_cache[cache_key] = specials

    return ok_response({"specials": [{"name": s} for s in specials]})


@api_route("GET", "/api/data/items")
def handle_data_items(handler, match, query_params):
    """Return ITEM_* constants from items.h."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    consts = _parse_defines(game_path, "include/constants/items.h", "ITEM_")
    items = []
    skip = {"ITEM_NONE", "ITEM_USE_MAIL_EDIT"}
    for c in consts:
        if c in skip:
            continue
        items.append({"const": c, "display": c[len("ITEM_"):].replace("_", " ").title()})
    return ok_response({"items": items})


# ---------------------------------------------------------------------------
# Scene Visualizer — State Engine (delegated to scene_sim.py)
# ---------------------------------------------------------------------------

from torch.scene_sim import (
    simulate_scene, facing_toward, apply_move_action, apply_movement_commands,
    DIRECTION_OFFSETS, OPPOSITE_DIR, MOVEMENT_CMD_MAP, MOVEMENT_CMD_NOOP,
)

# Backward-compat aliases (underscore-prefixed names used by existing code)
_DIRECTION_OFFSETS = DIRECTION_OFFSETS
_OPPOSITE_DIR = OPPOSITE_DIR
_MOVEMENT_CMD_MAP = MOVEMENT_CMD_MAP
_MOVEMENT_CMD_NOOP = MOVEMENT_CMD_NOOP
_facing_toward = facing_toward
_apply_move_action = apply_move_action
_apply_movement_commands = apply_movement_commands


# ---------------------------------------------------------------------------
# Scene Visualizer — Sprite Resolver
# ---------------------------------------------------------------------------

_sprite_index_cache = {}  # game_path -> (timestamp, dict)
_SPRITE_INDEX_TTL = 30  # seconds


def build_sprite_index(game_path):
    """Build a lookup: graphics_id -> {png, width, height}.

    Parses the 4 header files in the object_events data directory.
    Cache is invalidated after 30 seconds to pick up new sprites.
    """
    import time
    cached = _sprite_index_cache.get(game_path)
    if cached is not None:
        ts, index = cached
        if time.time() - ts < _SPRITE_INDEX_TTL:
            return index

    base = os.path.join(game_path, "src", "data", "object_events")

    # Step 1: OBJ_EVENT_GFX_* -> gObjectEventGraphicsInfo_* name
    gfx_to_info = {}  # "OBJ_EVENT_GFX_BOY_1" -> "Boy1"
    pointers_h = os.path.join(base, "object_event_graphics_info_pointers.h")
    if os.path.isfile(pointers_h):
        pat = re.compile(
            r'\[(\w+)\]\s*=\s*&gObjectEventGraphicsInfo_(\w+)')
        with open(pointers_h, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.search(line)
                if m:
                    gfx_to_info[m.group(1)] = m.group(2)

    # Step 2: info name -> (pic_table_name, width, height)
    info_to_pic = {}  # "Boy1" -> ("sPicTable_Boy1", 16, 32)
    info_h = os.path.join(base, "object_event_graphics_info.h")
    if os.path.isfile(info_h):
        with open(info_h, encoding="utf-8", errors="replace") as f:
            content = f.read()
        # Match each struct
        struct_pat = re.compile(
            r'gObjectEventGraphicsInfo_(\w+)\s*=\s*\{([^}]+)\}',
            re.DOTALL)
        width_pat = re.compile(r'\.width\s*=\s*(\d+)')
        height_pat = re.compile(r'\.height\s*=\s*(\d+)')
        images_pat = re.compile(r'\.images\s*=\s*(\w+)')
        for m in struct_pat.finditer(content):
            name = m.group(1)
            body = m.group(2)
            w_m = width_pat.search(body)
            h_m = height_pat.search(body)
            i_m = images_pat.search(body)
            if i_m:
                width = int(w_m.group(1)) if w_m else 16
                height = int(h_m.group(1)) if h_m else 32
                info_to_pic[name] = (i_m.group(1), width, height)

    # Step 3: pic table name -> gObjectEventPic_* name
    pic_to_global = {}  # "sPicTable_Boy1" -> "gObjectEventPic_Boy1"
    pic_tables_h = os.path.join(base, "object_event_pic_tables.h")
    if os.path.isfile(pic_tables_h):
        pat = re.compile(
            r'(\w+)\[\]\s*=\s*\{[^}]*?(gObjectEventPic_\w+)',
            re.DOTALL)
        with open(pic_tables_h, encoding="utf-8", errors="replace") as f:
            content = f.read()
        for m in pat.finditer(content):
            pic_to_global[m.group(1)] = m.group(2)

    # Step 4: global pic name -> INCBIN path
    global_to_path = {}  # "gObjectEventPic_Boy1" -> "graphics/.../boy_1.4bpp"
    graphics_h = os.path.join(base, "object_event_graphics.h")
    if os.path.isfile(graphics_h):
        pat = re.compile(
            r'(gObjectEventPic_\w+)\[\]\s*=\s*INCBIN_U32\("([^"]+)"')
        with open(graphics_h, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.search(line)
                if m:
                    global_to_path[m.group(1)] = m.group(2)

    # Chain it all together
    index = {}
    for gfx_const, info_name in gfx_to_info.items():
        pic_info = info_to_pic.get(info_name)
        if not pic_info:
            continue
        pic_table, width, height = pic_info
        global_name = pic_to_global.get(pic_table)
        if not global_name:
            continue
        bpp_path = global_to_path.get(global_name)
        if not bpp_path:
            continue
        # Replace .4bpp with .png
        png_path = re.sub(r'\.\w+$', '.png', bpp_path)
        index[gfx_const] = {
            "png": png_path,
            "width": width,
            "height": height,
        }

    import time
    _sprite_index_cache[game_path] = (time.time(), index)
    return index


def _build_scene_sprites(game_path, initial, frames):
    """Build sprite_index dict for all graphics_ids used in a scene.

    Scans both the initial state and all simulation frames, so actors
    introduced mid-scene (or whose NPC index was out of bounds in
    load_scene_initial_state) still get resolved sprite data.
    """
    sprite_index = build_sprite_index(game_path) if game_path else {}
    gfx_ids = set()

    # Collect from initial positions
    for actor_state in initial.values():
        gfx = actor_state.get("graphics_id", "")
        if gfx:
            gfx_ids.add(gfx)

    # Collect from simulation frames (catches actors not in initial)
    for frame in frames:
        for actor_state in (frame.get("actors") or {}).values():
            gfx = actor_state.get("graphics_id", "")
            if gfx:
                gfx_ids.add(gfx)

    scene_sprites = {}
    for gfx_id in gfx_ids:
        if gfx_id in sprite_index:
            info = sprite_index[gfx_id]
            scene_sprites[gfx_id] = {
                "png": f"/api/overworld-sprites/{gfx_id}",
                "width": info["width"],
                "height": info["height"],
            }
    return scene_sprites


# Standing frame indices for each facing direction (standard 9-frame strip)
SPRITE_STANDING_FRAMES = {
    "down": 1,
    "up": 4,
    "left": 7,
    "right": 7,  # right = left mirrored
}


# ---------------------------------------------------------------------------
# Scene Visualizer — Initial Position Loader
# ---------------------------------------------------------------------------

def _facing_from_movement_type(movement_type):
    """Derive facing direction from a map.json movement_type constant."""
    if not movement_type:
        return "down"
    mt = movement_type.upper()
    if "FACE_UP" in mt:
        return "up"
    if "FACE_LEFT" in mt:
        return "left"
    if "FACE_RIGHT" in mt:
        return "right"
    return "down"


def _apply_mapscript_positions(game_path, map_name, object_events, positions):
    """Override NPC positions using setobjectxyperm from mapscripts.

    Vanilla maps frequently reposition NPCs via mapscript ON_TRANSITION /
    ON_LOAD handlers.  Scan scripts.inc for setobjectxyperm calls and apply
    the LAST position found for each NPC (last = most specific game state).
    Also picks up setobjectmovementtype for facing direction.
    """
    import os
    inc_path = os.path.join(game_path, "data", "maps", map_name, "scripts.inc")
    if not os.path.isfile(inc_path):
        return

    try:
        with open(inc_path, "r", encoding="utf-8") as f:
            inc_text = f.read()
    except OSError:
        return

    # Build LOCALID -> alias lookup from object_events + current positions
    localid_to_alias = {}
    for alias, pos_data in positions.items():
        if alias == "player":
            continue
        # Find the object_event this alias refers to
        m = re.match(r'^npc(\d+)$', alias)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(object_events):
                lid = object_events[idx].get("local_id", "")
                if lid:
                    localid_to_alias[lid] = alias

    if not localid_to_alias:
        return

    # Scan for setobjectxyperm LOCALID, X, Y
    for line in inc_text.split('\n'):
        stripped = line.strip()
        m = re.match(
            r'^setobjectxyperm\s+(\w+),\s*(\d+),\s*(\d+)$', stripped)
        if m:
            lid, x, y = m.group(1), int(m.group(2)), int(m.group(3))
            alias = localid_to_alias.get(lid)
            if alias and alias in positions:
                positions[alias]["x"] = x
                positions[alias]["y"] = y

        # Also pick up setobjectmovementtype for facing
        m2 = re.match(
            r'^setobjectmovementtype\s+(\w+),\s*(\w+)$', stripped)
        if m2:
            lid, mtype = m2.group(1), m2.group(2)
            alias = localid_to_alias.get(lid)
            if alias and alias in positions:
                positions[alias]["facing"] = _facing_from_movement_type(mtype)


def load_scene_initial_state(game_path, map_name, parsed_script,
                             script_name=""):
    """Load initial actor positions from map.json for the script's cast.

    *script_name* is the workspace short name (e.g. "FootprintsMan") used to
    auto-detect the NPC when the cast is empty.

    Returns: dict suitable for simulate_scene()'s initial_positions param.
    """
    from torch.project_files import load_map_json

    data = load_map_json(game_path, map_name)
    if not data:
        return {"player": {"x": 0, "y": 0, "facing": "down",
                           "visible": True, "graphics_id": "OBJ_EVENT_GFX_BRENDAN_NORMAL"}}

    object_events = data.get("object_events", [])
    cast = parsed_script.get("cast", {})
    positions = {}

    # Track the first NPC's raw object event for player placement
    first_npc_obj = None
    for alias_name, npc_id in cast.items():
        # npcN -> object_events[N-1]
        idx = npc_id - 1
        if 0 <= idx < len(object_events):
            obj = object_events[idx]
            if first_npc_obj is None:
                first_npc_obj = obj
            positions[alias_name] = {
                "x": obj.get("x", 0),
                "y": obj.get("y", 0),
                "facing": _facing_from_movement_type(obj.get("movement_type", "")),
                "visible": True,
                "graphics_id": obj.get("graphics_id", ""),
            }

    # Auto-detect NPC when cast is empty — match script label against map.json
    if not cast and not first_npc_obj:
        # Strategy 1: match by label beat in parsed script
        first_label = ""
        for beat in parsed_script.get("beats", []):
            if beat.get("type") == "label":
                first_label = beat.get("data", {}).get("name", "")
                break

        # Strategy 2: reconstruct possible labels from script_name
        candidate_labels = []
        if first_label:
            candidate_labels.append(first_label)
        if script_name:
            candidate_labels.append(f"{map_name}_EventScript_{script_name}")
            candidate_labels.append(f"{map_name}_{script_name}")
            candidate_labels.append(script_name)

        for label in candidate_labels:
            for i, obj in enumerate(object_events):
                if obj.get("script", "") == label:
                    first_npc_obj = obj
                    alias = f"npc{i + 1}"
                    positions[alias] = {
                        "x": obj.get("x", 0),
                        "y": obj.get("y", 0),
                        "facing": _facing_from_movement_type(
                            obj.get("movement_type", "")),
                        "visible": True,
                        "graphics_id": obj.get("graphics_id", ""),
                    }
                    break
            if first_npc_obj:
                break

    # Override NPC positions from mapscript setobjectxyperm calls.
    # Vanilla maps often reposition NPCs via mapscripts based on game state.
    # The mapscript position is where the player actually encounters the NPC.
    if game_path and positions:
        _apply_mapscript_positions(game_path, map_name, object_events, positions)

    # Add player at a sensible default position.
    # Priority: coord_event trigger > trainer sight > adjacent to NPC > warp.
    # Use the (possibly overridden) position from `positions` for NPC coords.
    if "player" not in positions:
        px, py, pf = 0, 0, "up"

        # Resolve first NPC's actual position (after mapscript overrides)
        first_alias = None
        for name in positions:
            if name != "player":
                first_alias = name
                break
        npc_pos = positions.get(first_alias, {}) if first_alias else {}
        nx = npc_pos.get("x", first_npc_obj.get("x", 0) if first_npc_obj else 0)
        ny = npc_pos.get("y", first_npc_obj.get("y", 0) if first_npc_obj else 0)
        npc_facing = npc_pos.get("facing", _facing_from_movement_type(
            first_npc_obj.get("movement_type", "") if first_npc_obj else ""))

        # Check if any coord_event triggers this script's first label
        first_label = ""
        for beat in parsed_script.get("beats", []):
            if beat.get("type") == "label":
                first_label = beat.get("data", {}).get("name", "")
                break

        coord_events = data.get("coord_events", [])
        coord_match = None
        if first_label:
            for ce in coord_events:
                if ce.get("script", "") == first_label:
                    coord_match = ce
                    break

        if coord_match is not None:
            # Coord event trigger: player stands on the trigger tile
            px = coord_match.get("x", 0)
            py = coord_match.get("y", 0)
            if first_npc_obj is not None or first_alias:
                from torch.scene_sim import facing_toward
                pf = facing_toward(px, py, nx, ny)
            else:
                pf = "down"
        elif first_npc_obj is not None or first_alias:

            # Direction offsets: (dx, dy, player_facing_back)
            dir_offsets = {"left": (-1, 0, "right"), "right": (1, 0, "left"),
                           "up": (0, -1, "down"), "down": (0, 1, "up")}
            dx, dy, pf = dir_offsets.get(npc_facing, (0, 1, "up"))

            # Check for trainer sight range
            sight = 0
            if first_npc_obj:
                try:
                    sight = int(first_npc_obj.get(
                        "trainer_sight_or_berry_tree_id", "0"))
                except (ValueError, TypeError):
                    pass

            if sight > 0:
                # Trainer: place player at edge of sight range
                px, py = nx + dx * sight, ny + dy * sight
            else:
                # Talk-to NPC: place player one tile away
                px, py = nx + dx, ny + dy
        else:
            # No cast — fall back to first warp
            warp_events = data.get("warp_events", [])
            if warp_events:
                px = warp_events[0].get("x", 0)
                py = warp_events[0].get("y", 0)
        positions["player"] = {
            "x": px, "y": py, "facing": pf,
            "visible": True,
            "graphics_id": "OBJ_EVENT_GFX_BRENDAN_NORMAL",
        }

    return positions


def _build_trigger_info(game_path, map_name, cast, object_events,
                        map_data=None, parsed_script=None):
    """Build trigger info for the first cast NPC — sight range, direction, valid positions.

    If the NPC is not a trainer with sight range, falls back to coord_event
    detection when map_data and parsed_script are provided.
    """
    if not cast or not object_events:
        # Even without cast, coord_events might still apply
        if map_data and parsed_script:
            return _build_coord_trigger_info(map_data, parsed_script, object_events)
        return None
    first_alias = next(iter(cast))
    npc_id = cast[first_alias]
    idx = npc_id - 1
    if idx < 0 or idx >= len(object_events):
        return None
    obj = object_events[idx]
    trainer_type = obj.get("trainer_type", "")
    sight_raw = obj.get("trainer_sight_or_berry_tree_id", "0")
    try:
        sight = int(sight_raw)
    except (ValueError, TypeError):
        sight = 0
    # Only treat as trainer if trainer_type is set — sight value alone is not
    # enough (Porymap leaves stale sight values when type is changed to NONE)
    is_trainer = (
        trainer_type and trainer_type.upper() not in ("", "TRAINER_TYPE_NONE"))
    if not is_trainer:
        # Not a trainer — check for coord_event triggers, then fall back
        # to a "talk" trigger so the user can pick approach direction.
        if map_data and parsed_script:
            coord = _build_coord_trigger_info(map_data, parsed_script, object_events)
            if coord:
                return coord
        # Talk-to NPC: let user pick N/E/S/W approach direction
        # Directions = where the player STANDS relative to the NPC
        npc_facing = _facing_from_movement_type(obj.get("movement_type", ""))
        nx, ny = obj.get("x", 0), obj.get("y", 0)
        # Default: player stands opposite the NPC's facing direction
        # (NPC faces down → player stands south)
        default_pos = {"left": "left", "right": "right",
                       "up": "up", "down": "down"}.get(npc_facing, "down")
        positions_list = ["north", "south", "west", "east"]
        default_idx = {"up": 0, "down": 1, "left": 2, "right": 3}.get(default_pos, 1)
        return {
            "type": "talk",
            "alias": first_alias,
            "npc_x": nx, "npc_y": ny,
            "directions": positions_list,
            "min_distance": 0,
            "max_distance": 3,
            "default_distance": default_idx,
        }
    nx, ny = obj.get("x", 0), obj.get("y", 0)

    # Compute all valid NPC patrol positions + facings from movement_type.
    npc_positions = _compute_patrol_positions(obj)

    # Default facing for the sight line
    default_facing = npc_positions[0]["facing"] if npc_positions else "down"
    dir_offsets = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
    dx, dy = dir_offsets.get(default_facing, (0, 1))

    return {
        "type": "sight",
        "alias": first_alias,
        "npc_x": nx, "npc_y": ny,
        "facing": default_facing,
        "dx": dx, "dy": dy,
        "sight_range": sight,
        "min_distance": 1,
        "max_distance": max(sight, 1),
        "default_distance": max(sight, 1),
        "npc_positions": npc_positions,
    }


def _compute_patrol_positions(obj):
    """Compute all tiles an NPC could stand on + which way they face.

    Returns a list of {x, y, facing} dicts derived from the NPC's
    movement_type and movement_range_x/y.  For stationary NPCs, returns
    a single entry at the origin.
    """
    nx = obj.get("x", 0)
    ny = obj.get("y", 0)
    mt = (obj.get("movement_type", "") or "").upper()
    try:
        rx = int(obj.get("movement_range_x", 0))
    except (ValueError, TypeError):
        rx = 0
    try:
        ry = int(obj.get("movement_range_y", 0))
    except (ValueError, TypeError):
        ry = 0

    positions = []

    if "WALK_UP_AND_DOWN" in mt or "WALK_DOWN_AND_UP" in mt:
        # Patrol vertically: origin ± range_y, faces up or down
        for dy in range(-ry, ry + 1):
            facing = "up" if dy < 0 else "down" if dy > 0 else "down"
            positions.append({"x": nx, "y": ny + dy, "facing": facing})

    elif "WALK_LEFT_AND_RIGHT" in mt or "WALK_RIGHT_AND_LEFT" in mt:
        # Patrol horizontally: origin ± range_x, faces left or right
        for dx in range(-rx, rx + 1):
            facing = "left" if dx < 0 else "right" if dx > 0 else "right"
            positions.append({"x": nx + dx, "y": ny, "facing": facing})

    elif "WALK_SEQUENCE" in mt or "WALK_AROUND" in mt or "WANDER" in mt or "WALK_RANDOMLY" in mt:
        # Roam within range_x × range_y rectangle, could face any direction
        for dy in range(-ry, ry + 1):
            for dx in range(-rx, rx + 1):
                # At each tile, they could face any direction
                positions.append({"x": nx + dx, "y": ny + dy, "facing": "down"})

    elif "LOOK_AROUND" in mt:
        # Stays at origin, faces all 4 directions
        for f in ("down", "up", "left", "right"):
            positions.append({"x": nx, "y": ny, "facing": f})

    else:
        # Stationary: single position, facing from movement_type
        facing = _facing_from_movement_type(obj.get("movement_type", ""))
        positions.append({"x": nx, "y": ny, "facing": facing})

    return positions


def _build_coord_trigger_info(map_data, parsed_script, object_events):
    """Build trigger info from coord_events matching the script's first label.

    Returns a trigger_info dict with type="coord_event" and a list of tile
    positions.  Single tile = fixed player position (no slider).  Multiple
    tiles = discrete position picker.
    """
    # Find the script's first label
    first_label = ""
    for beat in parsed_script.get("beats", []):
        if beat.get("type") == "label":
            first_label = beat.get("data", {}).get("name", "")
            break
    if not first_label:
        return None

    coord_events = map_data.get("coord_events", [])
    tiles = []
    for ce in coord_events:
        if ce.get("script", "") == first_label:
            tiles.append({"x": ce.get("x", 0), "y": ce.get("y", 0)})
    if not tiles:
        return None

    # Determine player facing: toward the first cast NPC
    cast = parsed_script.get("cast", {})
    facing = "down"
    if cast and object_events:
        first_npc_id = next(iter(cast.values()))
        idx = first_npc_id - 1
        if 0 <= idx < len(object_events):
            npc_obj = object_events[idx]
            nx, ny = npc_obj.get("x", 0), npc_obj.get("y", 0)
            from torch.scene_sim import facing_toward
            facing = facing_toward(tiles[0]["x"], tiles[0]["y"], nx, ny)

    return {
        "type": "coord_event",
        "tiles": tiles,
        "facing": facing,
        "min_distance": 0,
        "max_distance": max(len(tiles) - 1, 0),
        "default_distance": 0,
    }


def _apply_npc_patrol(positions, trigger_info, patrol_index):
    """Override the NPC position from the patrol positions list.

    Updates both the positions dict (for simulation) and the trigger_info
    (for subsequent player distance calculation).
    """
    npc_positions = trigger_info.get("npc_positions", [])
    if not npc_positions or patrol_index < 0 or patrol_index >= len(npc_positions):
        return
    pos = npc_positions[patrol_index]
    alias = trigger_info.get("alias", "")
    if alias and alias in positions:
        positions[alias]["x"] = pos["x"]
        positions[alias]["y"] = pos["y"]
        positions[alias]["facing"] = pos["facing"]
    # Update trigger_info so _apply_player_distance uses the patrol position
    trigger_info["npc_x"] = pos["x"]
    trigger_info["npc_y"] = pos["y"]
    trigger_info["facing"] = pos["facing"]
    dir_offsets = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
    dx, dy = dir_offsets.get(pos["facing"], (0, 1))
    trigger_info["dx"] = dx
    trigger_info["dy"] = dy


def _apply_player_distance(positions, trigger_info, distance):
    """Override the player position based on distance from the trigger NPC."""
    if not trigger_info or "player" not in positions:
        return

    if trigger_info.get("type") == "coord_event":
        # Coord event: select tile from the tiles list by index
        tiles = trigger_info.get("tiles", [])
        if not tiles:
            return
        idx = max(0, min(distance, len(tiles) - 1))
        tile = tiles[idx]
        positions["player"]["x"] = tile["x"]
        positions["player"]["y"] = tile["y"]
        positions["player"]["facing"] = trigger_info.get("facing", "down")
        return

    if trigger_info.get("type") == "talk":
        # Talk-to NPC: distance is an index into [north, south, west, east]
        # representing where the player STANDS relative to the NPC.
        directions = trigger_info.get("directions", ["north", "south", "west", "east"])
        idx = max(0, min(distance, len(directions) - 1))
        chosen = directions[idx]
        nx, ny = trigger_info["npc_x"], trigger_info["npc_y"]
        # Player position offset from NPC, and player facing toward NPC
        pos_data = {
            "north": (0, -1, "down"),   # player above NPC, faces down
            "south": (0,  1, "up"),     # player below NPC, faces up
            "west":  (-1, 0, "right"),  # player left of NPC, faces right
            "east":  (1,  0, "left"),   # player right of NPC, faces left
        }
        dx, dy, player_facing = pos_data.get(chosen, (0, 1, "up"))
        positions["player"]["x"] = nx + dx
        positions["player"]["y"] = ny + dy
        positions["player"]["facing"] = player_facing
        # NPC turns to face the player
        npc_facing = {"down": "up", "up": "down", "right": "left", "left": "right"}
        alias = trigger_info.get("alias", "")
        if alias and alias in positions:
            positions[alias]["facing"] = npc_facing.get(player_facing, "down")
        return

    d = max(trigger_info["min_distance"], min(distance, trigger_info["max_distance"]))
    nx, ny = trigger_info["npc_x"], trigger_info["npc_y"]
    dx, dy = trigger_info["dx"], trigger_info["dy"]
    opposite = {"left": "right", "right": "left", "up": "down", "down": "up"}
    positions["player"]["x"] = nx + dx * d
    positions["player"]["y"] = ny + dy * d
    positions["player"]["facing"] = opposite.get(trigger_info["facing"], "up")


def _enrich_trigger(trigger, chain_data, game_path, map_name, script_name):
    """Populate computed trigger fields (npc_origin, range, actor, etc.)
    from map data, preserving user-set fields like excluded_distances."""
    from torch.project_files import load_map_json

    # Find the first cast member for this script
    map_data = load_map_json(game_path, map_name) or {}
    object_events = map_data.get("object_events", [])
    cast = chain_data.get("cast", {})
    first_alias = None
    first_obj = None
    for alias, info in cast.items():
        events = info.get("events", {}).get(map_name, {})
        idx = events.get("object_event_index")
        if idx is not None and 0 < idx <= len(object_events):
            first_alias = alias
            first_obj = object_events[idx - 1]
            break

    if not first_obj:
        return

    nx = first_obj.get("x", 0)
    ny = first_obj.get("y", 0)
    facing = _facing_from_movement_type(first_obj.get("movement_type", ""))

    trigger["actor"] = first_alias
    trigger["npc_origin"] = {"x": nx, "y": ny, "facing": facing}
    trigger["facing"] = facing

    if trigger.get("type") == "sight":
        radius = trigger.get("radius", 1)
        try:
            sight = int(first_obj.get("trainer_sight_or_berry_tree_id", "0"))
        except (ValueError, TypeError):
            sight = 0
        max_dist = radius if radius else max(sight, 1)
        trigger["range"] = [1, max_dist]
        trigger["axis"] = "vertical" if facing in ("up", "down") else "horizontal"

    elif trigger.get("type") == "talk":
        # Build approach tiles (4 cardinal directions around NPC)
        existing_tiles = trigger.get("approach_tiles")
        if not existing_tiles:
            trigger["approach_tiles"] = [
                {"x": nx, "y": ny - 1, "player_facing": "down", "enabled": True},
                {"x": nx + 1, "y": ny, "player_facing": "left", "enabled": True},
                {"x": nx, "y": ny + 1, "player_facing": "up", "enabled": True},
                {"x": nx - 1, "y": ny, "player_facing": "right", "enabled": True},
            ]
        else:
            # Preserve user-set enabled flags, update positions in case NPC moved
            cardinals = [
                {"x": nx, "y": ny - 1, "player_facing": "down"},
                {"x": nx + 1, "y": ny, "player_facing": "left"},
                {"x": nx, "y": ny + 1, "player_facing": "up"},
                {"x": nx - 1, "y": ny, "player_facing": "right"},
            ]
            for i, c in enumerate(cardinals):
                if i < len(existing_tiles):
                    c["enabled"] = existing_tiles[i].get("enabled", True)
                else:
                    c["enabled"] = True
            trigger["approach_tiles"] = cardinals

    elif trigger.get("type") in ("walk_over", "coord_event"):
        # Populate coord tile positions from map.json coord_events
        coord_events = map_data.get("coord_events", [])
        script_label = trigger.get("script", "")
        if not script_label:
            # Try to find the label from the first obj's script field
            script_label = first_obj.get("script", "")
        tiles = []
        for ce in coord_events:
            if ce.get("script", "") == script_label:
                tiles.append({"x": ce.get("x", 0), "y": ce.get("y", 0)})
        if tiles:
            trigger["coord_tiles"] = tiles


def _chain_head_trigger_info(project_dir, game_path, chain_data):
    """Build trigger_info from the chain's head script.

    Used so the distance slider appears for every script in the chain,
    sourced from the head script's trainer NPC — the one that actually
    determines where the player stands when the sequence begins.
    """
    sequence = chain_data.get("sequence", [])
    if not sequence:
        return None
    head = sequence[0]
    head_map = head.get("map", "")
    head_script = head.get("script", "")
    if not head_map or not head_script:
        return None

    # Parse the head script to get its cast
    filepath = os.path.join(project_dir, head_map, f"{head_script}.txt")
    if not os.path.isfile(filepath):
        return None
    try:
        from torch.script_model import _parse_script
        parsed = _parse_script(filepath)
    except Exception:
        return None

    from torch.project_files import load_map_json
    map_data = load_map_json(game_path, head_map) or {}
    object_events = map_data.get("object_events", [])
    cast = parsed.get("cast", {})
    return _build_trigger_info(game_path, head_map, cast, object_events,
                               map_data=map_data, parsed_script=parsed)


def _load_setup_movements(workspace_dir, map_name):
    """Load named movement blocks from setup.pory for a map.

    Returns: dict mapping label -> [command_strings]
    """
    setup_path = os.path.join(workspace_dir, map_name, "setup.pory")
    if not os.path.isfile(setup_path):
        return {}
    try:
        from torch.script_model import _parse_setup_movement_blocks
        blocks = _parse_setup_movement_blocks(setup_path)
        return {b["label"]: b["commands"] for b in blocks if b.get("label")}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Scene Visualizer — Workspace Helpers
# ---------------------------------------------------------------------------

def _get_workspace_path(handler):
    """Derive the TORCH workspace base path from server config."""
    server = handler.server
    project_dir = getattr(server, "project_dir", "")
    if not project_dir:
        return None
    # project_dir is like ~/ROMHacking/TORCH/Pokemon Seihoku
    return project_dir


def _get_script_path(project_dir, map_name, script_name):
    """Get validated path to a TorScript .txt file in the workspace.

    Returns the safe path string.  Raises ValueError if the path would
    escape the project directory.
    """
    return _safe_path(project_dir, map_name, f"{script_name}.txt")


def _auto_decompile_for_preview(game_path, project_dir, map_name, script_name):
    """Find a vanilla script by short name and decompile to workspace.

    Always re-decompiles to keep the workspace file in sync with the game
    source.  Workspace .txt files for vanilla scripts are treated as a cache —
    TORCH regenerates them automatically so the user never sees stale data.

    Returns the workspace filepath on success, None on failure.
    """
    if not game_path or not project_dir:
        return None

    try:
        from torch.web.api_npc_editor import (
            _find_script, _decompile_script_to_workspace,
        )
    except ImportError:
        return None

    # Try common label patterns: MapName_EventScript_Name, MapName_Name
    candidates = [
        f"{map_name}_EventScript_{script_name}",
        f"{map_name}_{script_name}",
        script_name,  # might be a full label already
    ]

    for label in candidates:
        filepath, file_type = _find_script(game_path, map_name, label)
        if filepath and file_type:
            try:
                short, ts_text, warnings = _decompile_script_to_workspace(
                    game_path, map_name, label, project_dir,
                    overwrite=True,
                )
                ws_path = _safe_path(project_dir, map_name, f"{short}.txt")
                if os.path.isfile(ws_path):
                    return ws_path
            except (ValueError, OSError):
                continue

    return None


def _list_scene_scripts(project_dir, map_name):
    """List .txt TorScript files in the workspace for a given map."""
    map_dir = _safe_path(project_dir, map_name)
    if not os.path.isdir(map_dir):
        return []
    scripts = []
    for fname in sorted(os.listdir(map_dir)):
        if fname.endswith(".txt") and not fname.startswith("."):
            scripts.append(fname)
    return scripts


# ---------------------------------------------------------------------------
# Scene Visualizer — API Endpoints (sub-routes first for correct matching)
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/npcs")
def handle_scene_npcs(handler, match, query_params):
    """Return NPC object_events from the map's map.json."""
    map_name = match.group("map_name")
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    from torch.project_files import load_map_json
    data = load_map_json(game_path, map_name)
    if data is None:
        return error_response(f"Map '{map_name}' not found", 404)

    object_events = data.get("object_events", [])
    npcs = []
    for i, obj in enumerate(object_events):
        npcs.append({
            "id": i + 1,
            "graphics_id": obj.get("graphics_id", ""),
            "x": obj.get("x", 0),
            "y": obj.get("y", 0),
            "movement_type": obj.get("movement_type", ""),
            "script": obj.get("script", ""),
        })

    return ok_response({"map": map_name, "npcs": npcs})


@api_route("GET", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/(?P<script_name>[A-Za-z0-9_]+)/beats")
def handle_scene_beats(handler, match, query_params):
    """Return parsed beats as structured JSON."""
    map_name = match.group("map_name")
    script_name = match.group("script_name")
    project_dir = _get_workspace_path(handler)

    if not project_dir:
        return error_response("No project directory configured", 500)

    filepath = _get_script_path(project_dir, map_name, script_name)
    if not os.path.isfile(filepath):
        return error_response(f"Script '{script_name}' not found for map '{map_name}'", 404)

    from torch.script_model import _parse_script, BEAT_TAGS

    try:
        parsed = _parse_script(filepath)
    except Exception as exc:
        return error_response(f"Failed to parse script: {exc}", 500)

    beats_out = []
    for beat in parsed.get("beats", []):
        btype = beat.get("type", "")
        beats_out.append({
            "type": btype,
            "data": beat.get("data", {}),
            "source_line": beat.get("source_line"),
            "source_end_line": beat.get("source_end_line"),
            "tag": BEAT_TAGS.get(btype, "???"),
        })

    labels = [b.get("data", {}).get("name", "")
              for b in parsed.get("beats", []) if b.get("type") == "label"]

    return ok_response({
        "beats": beats_out,
        "cast": parsed.get("cast", {}),
        "labels": labels,
    })


@api_route("POST", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/(?P<script_name>[A-Za-z0-9_]+)/validate")
def handle_scene_validate(handler, match, query_params):
    """Parse TorScript source and return structured errors/warnings."""
    map_name = match.group("map_name")
    script_name = match.group("script_name")

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body or "source" not in body:
        return error_response("Request body must contain 'source'", 400)

    source = body["source"]
    tmp = None
    errors = []
    warnings = []

    try:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                          delete=False, encoding="utf-8")
        tmp.write(source)
        tmp.close()

        from torch.script_model import _parse_script
        parsed = _parse_script(tmp.name)

        # Check for duplicate labels
        labels = [b.get("data", {}).get("name", "")
                  for b in parsed.get("beats", []) if b.get("type") == "label"]
        seen = set()
        for lbl in labels:
            if lbl in seen:
                errors.append({"line": None,
                               "message": f"Duplicate label '{lbl}'"})
            seen.add(lbl)

        # Check alias references
        cast = parsed.get("cast", {})
        for beat in parsed.get("beats", []):
            data = beat.get("data", {})
            actor = data.get("actor", "")
            if actor and actor != "player" and actor not in cast:
                warnings.append({
                    "line": beat.get("source_line"),
                    "message": f"Unknown alias '{actor}' -- not in cast",
                })

    except Exception as exc:
        msg = str(exc)
        line_num = None
        # Try to extract line number from common error format "Line N: ..."
        line_match = re.match(r"[Ll]ine\s+(\d+)", msg)
        if line_match:
            line_num = int(line_match.group(1))
        errors.append({"line": line_num, "message": msg})
    finally:
        if tmp:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    valid = len(errors) == 0
    return ok_response({"valid": valid, "errors": errors, "warnings": warnings})


@api_route("GET", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)")
def handle_scene_list(handler, match, query_params):
    """List available TorScript files for a map."""
    map_name = match.group("map_name")
    project_dir = _get_workspace_path(handler)
    if not project_dir:
        return error_response("No project directory configured", 500)

    txt_files = _list_scene_scripts(project_dir, map_name)
    if not txt_files:
        return ok_response({"map": map_name, "scripts": []})

    from torch.script_model import _parse_script

    scripts = []
    map_dir = _safe_path(project_dir, map_name)
    for fname in txt_files:
        filepath = os.path.join(map_dir, fname)
        beat_count = 0
        cast_count = 0
        last_modified = ""
        try:
            parsed = _parse_script(filepath)
            beat_count = len(parsed.get("beats", []))
        except Exception:
            pass
        try:
            stat = os.stat(filepath)
            last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
            with open(filepath, "r", encoding="utf-8") as f:
                source_lines = f.read().split("\n")
            cast_count = sum(
                1 for ln in source_lines if ln.strip().startswith("alias ")
            )
        except OSError:
            pass
        script_name = fname[:-4]  # strip .txt
        scripts.append({
            "name": script_name,
            "filename": fname,
            "beat_count": beat_count,
            "cast_count": cast_count,
            "last_modified": last_modified,
        })

    return ok_response({"map": map_name, "scripts": scripts})


# ---------------------------------------------------------------------------
# Scene CRUD — Script Browser endpoints
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/create")
def handle_scene_create(handler, match, query_params):
    """Create a new TorScript file with a basic template."""
    map_name = match.group("map_name")
    body = _read_json_body(handler)
    if not body or not body.get("name"):
        return error_response("Script name is required")

    name = body["name"].strip()

    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", name):
        return error_response(
            "Script name must start with a letter and contain only "
            "letters, numbers, and underscores"
        )

    project_dir = _get_workspace_path(handler)
    if not project_dir:
        return error_response("No workspace configured", 500)

    with _scene_lock:
        map_dir = _safe_path(project_dir, map_name)
        os.makedirs(map_dir, exist_ok=True)

        filepath = _get_script_path(project_dir, map_name, name)
        if os.path.exists(filepath):
            return error_response(f"Script '{name}' already exists")

        template = (
            f"# {name}\n"
            f"# Created by TORCH Script Browser\n"
            f"\n"
            f"label Main\n"
            f"lock\n"
            f"faceplayer\n"
            f'msg "Hello!$"\n'
            f"closemessage\n"
            f"end\n"
        )
        _atomic_write(filepath, template)

        return ok_response({"name": name, "path": filepath})


@api_route("POST", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/import")
def handle_scene_import(handler, match, query_params):
    """Import a game script by decompiling from .pory to TorScript."""
    map_name = match.group("map_name")
    body = _read_json_body(handler)
    if not body:
        return error_response("Request body required")

    script_path = body.get("script_path", "")
    script_name = body.get("script_name", "")
    if not script_path or not script_name:
        return error_response("script_path and script_name are required")

    game_path = getattr(handler.server, "game_path", "")
    project_dir = _get_workspace_path(handler)
    if not game_path or not project_dir:
        return error_response("No workspace configured", 500)

    # Security: reject path traversal in script_path
    try:
        script_path = _safe_path(game_path, os.path.relpath(script_path, game_path))
    except ValueError:
        return error_response("Invalid script path", 400)

    if not os.path.isfile(script_path):
        return error_response(f"Source file not found: {script_path}", 404)

    # Try to decompile using the decompiler
    source = None
    try:
        from torch.decompiler import decompile
        with open(script_path, "r", encoding="utf-8") as f:
            pory_text = f.read()
        # Extract just this script's block from the .pory file
        block = _extract_pory_block(pory_text, script_name)
        if block is not None:
            # Wrap as a standalone script so the decompiler can parse it
            wrapped = f"script {script_name} {{\n{block}\n}}\n"
            ts_text, _warnings = decompile(wrapped, map_name)
            if ts_text.strip():
                source = ts_text
    except Exception:
        pass

    # Fallback: raw extraction if decompiler failed
    if source is None:
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                pory_text = f.read()
            block = _extract_pory_block(pory_text, script_name)
            if block is not None:
                lines = [
                    f"# Imported from game source",
                    f"# Original: {script_name}",
                    "",
                ]
                for line in block.split("\n"):
                    stripped = line.strip()
                    if stripped:
                        lines.append(f"raw {stripped}")
                source = "\n".join(lines) + "\n"
        except OSError as e:
            return error_response(f"Failed to read source: {e}")

    if source is None:
        return error_response(
            f"Script '{script_name}' not found in {os.path.basename(script_path)}"
        )

    # Clean up the name for the workspace file
    clean_name = script_name
    if clean_name.startswith(f"{map_name}_"):
        clean_name = clean_name[len(f"{map_name}_"):]
    if clean_name.startswith("EventScript_"):
        clean_name = clean_name[len("EventScript_"):]
    if not clean_name:
        clean_name = script_name

    # Write to workspace
    with _scene_lock:
        map_dir = _safe_path(project_dir, map_name)
        os.makedirs(map_dir, exist_ok=True)
        filepath = _get_script_path(project_dir, map_name, clean_name)

        if os.path.exists(filepath):
            return error_response(f"Script '{clean_name}' already exists in workspace")

        _atomic_write(filepath, source)

        return ok_response({"name": clean_name, "source": source})


def _extract_pory_block(pory_text, script_name):
    """Extract a single script's body from a .pory file.

    Returns the body text (between outer braces) or None.
    """
    pattern = rf"script\s+{re.escape(script_name)}\s*\{{"
    m = re.search(pattern, pory_text)
    if not m:
        return None
    # Find matching closing brace
    start = m.end()
    depth = 1
    i = start
    while i < len(pory_text) and depth > 0:
        if pory_text[i] == "{":
            depth += 1
        elif pory_text[i] == "}":
            depth -= 1
        i += 1
    if depth != 0:
        return None
    return pory_text[start:i - 1].strip()


_game_scripts_cache = {}  # (game_path, map_name) -> {"mtime": float, "scripts": list}


def _get_game_scripts_cached(game_path, map_name):
    """Return game script labels for a map, cached by file mtime.

    Checks both scripts.pory and scripts.inc.  The cache is keyed on
    (game_path, map_name) and invalidated when the pory file's mtime
    changes (or the inc file, whichever is newer).
    """
    key = (game_path, map_name)
    map_scripts_dir = os.path.join(game_path, "data", "maps", map_name)
    pory_path = os.path.join(map_scripts_dir, "scripts.pory")
    inc_path = os.path.join(map_scripts_dir, "scripts.inc")

    # Determine current mtime (use max of both files)
    current_mtime = 0
    for p in (pory_path, inc_path):
        try:
            current_mtime = max(current_mtime, os.path.getmtime(p))
        except OSError:
            pass

    cached = _game_scripts_cache.get(key)
    if cached and cached["mtime"] == current_mtime:
        return cached["scripts"]

    scripts = []

    # Parse scripts.pory
    if os.path.isfile(pory_path):
        try:
            with open(pory_path, "r", encoding="utf-8") as f:
                content = f.read()
            for m in re.finditer(r"script\s+(\w+)\s*\{", content):
                scripts.append({
                    "name": m.group(1),
                    "path": pory_path,
                    "decompilable": True,
                })
        except OSError:
            pass

    # Parse scripts.inc
    if os.path.isfile(inc_path):
        try:
            with open(inc_path, "r", encoding="utf-8") as f:
                content = f.read()
            for m in re.finditer(r"^(\w+)::?\s*$", content, re.MULTILINE):
                label = m.group(1)
                if "EventScript" in label or "Script" in label:
                    scripts.append({
                        "name": label,
                        "path": inc_path,
                        "decompilable": False,
                    })
        except OSError:
            pass

    _game_scripts_cache[key] = {"mtime": current_mtime, "scripts": scripts}
    return scripts


@api_route("GET", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/game-scripts")
def handle_scene_game_scripts(handler, match, query_params):
    """List script labels in the game's source files for a map (for import)."""
    map_name = match.group("map_name")
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    scripts = _get_game_scripts_cached(game_path, map_name)
    return ok_response({"scripts": scripts})


@api_route("GET", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/(?P<script_name>[A-Za-z0-9_]+)")
def handle_scene_detail(handler, match, query_params):
    """Full scene data for visualization."""
    map_name = match.group("map_name")
    script_name = match.group("script_name")
    game_path = getattr(handler.server, "game_path", "")
    project_dir = _get_workspace_path(handler)

    if not project_dir:
        return error_response("No project directory configured", 500)

    filepath = _get_script_path(project_dir, map_name, script_name)

    # Always refresh vanilla scripts from game source so previews stay in sync.
    # This is cheap (<10ms) and ensures the workspace .txt is never stale.
    refreshed = _auto_decompile_for_preview(
        game_path, project_dir, map_name, script_name)
    if refreshed:
        filepath = refreshed
    elif not os.path.isfile(filepath):
        return error_response(
            f"Script '{script_name}' not found for map '{map_name}'", 404)

    from torch.script_model import _parse_script

    try:
        parsed = _parse_script(filepath)
    except Exception as exc:
        return error_response(f"Failed to parse script: {exc}", 500)

    # Load initial positions, build trigger info, and simulate
    from torch.project_files import load_map_json
    map_data = load_map_json(game_path, map_name) or {}
    object_events = map_data.get("object_events", [])
    cast = parsed.get("cast", {})

    initial = load_scene_initial_state(game_path, map_name, parsed,
                                       script_name=script_name)

    # Build effective cast: parsed cast + any auto-detected NPCs
    effective_cast = dict(cast)
    for name in initial:
        if name != "player" and name not in effective_cast:
            # Auto-detected NPC (e.g. "npc5") -> extract ID from name
            m_npc = re.match(r"^npc(\d+)$", name)
            if m_npc:
                effective_cast[name] = int(m_npc.group(1))

    trigger_info = _build_trigger_info(game_path, map_name, effective_cast,
                                       object_events,
                                       map_data=map_data, parsed_script=parsed)
    setup_moves = _load_setup_movements(project_dir, map_name)
    frames = simulate_scene(parsed, initial, setup_moves)

    # Read source text
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError:
        source = ""

    scene_sprites = _build_scene_sprites(game_path, initial, frames)

    resp = {
        "map": map_name,
        "script": script_name,
        "source": source,
        "cast": effective_cast,
        "frames": frames,
        "sprite_index": scene_sprites,
    }
    if trigger_info:
        resp["trigger_info"] = trigger_info
    return ok_response(resp)


@api_route("POST", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/(?P<script_name>[A-Za-z0-9_]+)/simulate")
def handle_scene_simulate(handler, match, query_params):
    """Parse and simulate raw TorScript source from POST body."""
    map_name = match.group("map_name")
    script_name = match.group("script_name")
    game_path = getattr(handler.server, "game_path", "")

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body or "source" not in body:
        return error_response("Request body must contain 'source'", 400)

    source = body["source"]

    # Write to a temp file to reuse _parse_script (it reads from file)
    tmp = None
    try:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                          delete=False, encoding="utf-8")
        tmp.write(source)
        tmp.close()

        from torch.script_model import _parse_script
        parsed = _parse_script(tmp.name)
    except Exception as exc:
        return error_response(f"Parse error: {exc}", 400)
    finally:
        if tmp:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    # Chain support: merge provided initial_positions on top of map.json defaults.
    # Only adopt chain positions for actors in the script's cast + player.
    # This ensures the chain doesn't inject actors that the script never uses
    # (e.g. Clyde appearing in Buster's simulation because the chain knows about Clyde).
    initial = load_scene_initial_state(game_path, map_name, parsed,
                                       script_name=script_name)
    if "initial_positions" in body and isinstance(body["initial_positions"], dict):
        chain_pos = body["initial_positions"]
        cast_aliases = set(parsed.get("cast", {}).keys())
        cast_aliases.add("player")
        for name, pos in chain_pos.items():
            if name in cast_aliases:
                initial[name] = pos

    # Build effective cast: parsed cast + auto-detected NPCs
    from torch.project_files import load_map_json
    map_data = load_map_json(game_path, map_name) or {}
    object_events = map_data.get("object_events", [])
    cast = parsed.get("cast", {})
    effective_cast = dict(cast)
    for name in initial:
        if name != "player" and name not in effective_cast:
            m_npc = re.match(r"^npc(\d+)$", name)
            if m_npc:
                effective_cast[name] = int(m_npc.group(1))

    # Apply player distance override if provided
    trigger_info = _build_trigger_info(game_path, map_name, effective_cast,
                                       object_events,
                                       map_data=map_data, parsed_script=parsed)
    # Apply NPC patrol position override (walking trainers)
    npc_patrol_index = body.get("npc_patrol_index")
    if trigger_info and npc_patrol_index is not None:
        try:
            _apply_npc_patrol(initial, trigger_info, int(npc_patrol_index))
        except (ValueError, TypeError):
            pass

    player_distance = body.get("player_distance")
    if trigger_info and player_distance is not None:
        try:
            _apply_player_distance(initial, trigger_info, int(player_distance))
        except (ValueError, TypeError):
            pass

    project_dir = _get_workspace_path(handler)
    setup_moves = _load_setup_movements(project_dir, map_name) if project_dir else {}
    frames = simulate_scene(parsed, initial, setup_moves)

    scene_sprites = _build_scene_sprites(game_path, initial, frames)

    return ok_response({
        "map": map_name,
        "script": script_name,
        "source": source,
        "cast": effective_cast,
        "frames": frames,
        "sprite_index": scene_sprites,
    })


@api_route("POST", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/(?P<script_name>[A-Za-z0-9_]+)/save")
def handle_scene_save(handler, match, query_params):
    """Save TorScript source to the workspace file."""
    map_name = match.group("map_name")
    script_name = match.group("script_name")
    project_dir = _get_workspace_path(handler)

    if not project_dir:
        return error_response("No project directory configured", 500)

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body or "source" not in body:
        return error_response("Request body must contain 'source'", 400)

    with _scene_lock:
        map_dir = _safe_path(project_dir, map_name)
        if not os.path.isdir(map_dir):
            return error_response(f"Map directory '{map_name}' not found", 404)

        filepath = _get_script_path(project_dir, map_name, script_name)
        try:
            _atomic_write(filepath, body["source"])
        except OSError as exc:
            return error_response(f"Failed to save: {exc}", 500)

        return ok_response({"saved": True, "path": filepath})


@api_route("POST", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/(?P<script_name>[A-Za-z0-9_]+)/analyze-delete")
def handle_scene_analyze_delete(handler, match, query_params):
    """Analyze the impact of deleting a script."""
    map_name = match.group("map_name")
    script_name = match.group("script_name")
    project_dir = _get_workspace_path(handler)
    if not project_dir:
        return error_response("No workspace configured", 500)

    filepath = _get_script_path(project_dir, map_name, script_name)
    if not os.path.isfile(filepath):
        return error_response(f"Script '{script_name}' not found", 404)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError as e:
        return error_response(str(e))

    lines = source.split("\n")
    cast = []
    flags_used = []
    movements = []
    beat_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("alias "):
            parts = stripped.split()
            if len(parts) >= 2:
                cast.append(parts[1])
        elif stripped.startswith("flag "):
            parts = stripped.split()
            if len(parts) >= 3:
                flags_used.append(parts[2])
        elif stripped.startswith("movement "):
            parts = stripped.split()
            if len(parts) >= 3:
                movements.append(parts[2])
        else:
            beat_count += 1

    # Cross-references: check if other scripts in the same map mention this one
    cross_refs = []
    map_dir = _safe_path(project_dir, map_name)
    if os.path.isdir(map_dir):
        for fname in os.listdir(map_dir):
            if fname.endswith(".txt") and fname != f"{script_name}.txt":
                try:
                    with open(os.path.join(map_dir, fname), "r",
                              encoding="utf-8") as f:
                        other_source = f.read()
                    if script_name in other_source:
                        cross_refs.append(fname[:-4])
                except OSError:
                    pass

    return ok_response({
        "beat_count": beat_count,
        "cast": cast,
        "flags_used": list(set(flags_used)),
        "movements": list(set(movements)),
        "cross_refs": cross_refs,
        "companions": [],
    })


@api_route("POST", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/(?P<script_name>[A-Za-z0-9_]+)/delete")
def handle_scene_delete(handler, match, query_params):
    """Delete a script file from the workspace."""
    map_name = match.group("map_name")
    script_name = match.group("script_name")
    project_dir = _get_workspace_path(handler)
    if not project_dir:
        return error_response("No workspace configured", 500)

    with _scene_lock:
        filepath = _get_script_path(project_dir, map_name, script_name)
        if not os.path.isfile(filepath):
            return error_response(f"Script '{script_name}' not found", 404)

        try:
            os.remove(filepath)
        except OSError as e:
            return error_response(f"Failed to delete: {e}")

        return ok_response(None)


@api_route("POST", r"/api/scenes/(?P<map_name>[A-Za-z0-9_]+)/(?P<script_name>[A-Za-z0-9_]+)/rename")
def handle_scene_rename(handler, match, query_params):
    """Rename a script file in the workspace."""
    map_name = match.group("map_name")
    script_name = match.group("script_name")
    body = _read_json_body(handler)
    if not body or not body.get("new_name"):
        return error_response("New script name is required")

    new_name = body["new_name"].strip()

    # Validate new name format (same rules as create)
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", new_name):
        return error_response(
            "Script name must start with a letter and contain only "
            "letters, numbers, and underscores"
        )

    # Reasonable length limit
    if len(new_name) > 64:
        return error_response("Script name too long (max 64 characters)")

    # No-op if same name
    if new_name == script_name:
        return error_response("New name is the same as the current name")

    project_dir = _get_workspace_path(handler)
    if not project_dir:
        return error_response("No workspace configured", 500)

    with _scene_lock:
        old_path = _get_script_path(project_dir, map_name, script_name)
        if not os.path.isfile(old_path):
            return error_response(f"Script '{script_name}' not found", 404)

        new_path = _get_script_path(project_dir, map_name, new_name)
        if os.path.exists(new_path):
            return error_response(
                f"Script '{new_name}' already exists", 409
            )

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            return error_response(f"Failed to rename: {e}")

    # Check for chain references (outside lock — read-only scan)
    warnings = []
    try:
        from torch.chain_model import find_chains_for_script
        chains = find_chains_for_script(project_dir, map_name, script_name)
        if chains:
            chain_names = [c["name"] for c in chains]
            warnings.append(
                f"Chain(s) still reference the old name '{script_name}': "
                + ", ".join(chain_names)
                + ". Update them manually in the Chain Builder."
            )
    except Exception:
        pass  # chain lookup is best-effort

    result = {
        "old_name": script_name,
        "new_name": new_name,
        "path": new_path,
    }
    if warnings:
        result["warnings"] = warnings

    return ok_response(result)


@api_route("GET", r"/api/overworld-sprites/(?P<gfx_id>OBJ_EVENT_GFX_\w+)")
def handle_overworld_sprite(handler, match, query_params):
    """Serve the PNG sprite sheet for a given OBJ_EVENT_GFX_ constant."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        handler.send_error(404, "Not Found")
        return None

    gfx_id = match.group("gfx_id")
    sprite_index = build_sprite_index(game_path)
    entry = sprite_index.get(gfx_id)
    if not entry:
        handler.send_error(404, "Not Found")
        return None

    png_rel = entry["png"]
    try:
        full_path = _safe_path(game_path, png_rel)
    except ValueError:
        handler.send_error(403, "Forbidden")
        return None

    if not os.path.isfile(full_path):
        handler.send_error(404, "Not Found")
        return None

    try:
        with open(full_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_error(500, "Read error")
        return None

    # GBA sprites: indexed PNG, palette index 0 = transparent.
    # Add tRNS chunk if missing so browsers render transparency correctly.
    data = _ensure_png_transparency(data)

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)
    return None


def _ensure_png_transparency(data):
    """Add tRNS chunk to indexed PNG if missing, marking palette index 0 as transparent."""
    # Only process indexed PNGs (color type 3)
    if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n':
        return data
    # Read IHDR color type (byte 25: offset 8 + 4 len + 4 'IHDR' + 8 w/h + 1 depth)
    color_type = data[25]
    if color_type != 3:  # Not indexed
        return data
    # Check if tRNS already exists
    if b'tRNS' in data:
        return data
    # Find PLTE chunk to get palette size, then insert tRNS after it
    pos = 8  # after PNG signature
    plte_end = None
    palette_entries = 0
    while pos < len(data) - 4:
        chunk_len = struct.unpack('>I', data[pos:pos+4])[0]
        chunk_type = data[pos+4:pos+8]
        chunk_end = pos + 12 + chunk_len  # 4 len + 4 type + data + 4 crc
        if chunk_type == b'PLTE':
            palette_entries = chunk_len // 3
            plte_end = chunk_end
            break
        pos = chunk_end
    if not plte_end or palette_entries == 0:
        return data
    # Build tRNS chunk: index 0 = fully transparent, rest = fully opaque
    trns_data = b'\x00' + b'\xff' * (palette_entries - 1)
    trns_crc = zlib.crc32(b'tRNS' + trns_data) & 0xffffffff
    trns_chunk = struct.pack('>I', len(trns_data)) + b'tRNS' + trns_data + struct.pack('>I', trns_crc)
    # Insert after PLTE
    return data[:plte_end] + trns_chunk + data[plte_end:]


# ---------------------------------------------------------------------------
# TORCH Config / Preferences
# ---------------------------------------------------------------------------

@api_route("GET", "/api/config/preferences")
def handle_get_preferences(handler, match, query_params):
    """Return current TORCH preferences with defaults and descriptions."""
    from torch.config import SETTINGS_DEFAULTS, SETTINGS_DESCRIPTIONS

    server = handler.server
    settings = getattr(server, "settings", {})

    items = []
    for key, default in SETTINGS_DEFAULTS.items():
        current = settings.get(key, default)
        vtype = "bool" if isinstance(default, bool) else (
            "int" if isinstance(default, int) else "string"
        )
        items.append({
            "key": key,
            "value": current,
            "default": default,
            "type": vtype,
            "description": SETTINGS_DESCRIPTIONS.get(key, ""),
        })

    return ok_response({"preferences": items})


@api_route("POST", "/api/config/preferences")
def handle_save_preferences(handler, match, query_params):
    """Save one or more TORCH preferences. Body: {changes: [{key, value}]}."""
    from torch.config import SETTINGS_DEFAULTS, load_config, save_config

    content_length = int(handler.headers.get("Content-Length", 0))
    body = json.loads(handler.rfile.read(content_length))
    changes = body.get("changes", [])

    if not changes:
        return error_response("No changes provided")

    # Load fresh config from disk
    result = load_config()
    if result is None:
        return error_response("Could not load config", 500)
    workspace_parent, projects, settings = result

    saved = 0
    errors = []
    restart_required = False
    for change in changes:
        key = change.get("key", "")
        value = change.get("value")
        if key not in SETTINGS_DEFAULTS:
            errors.append(f"Unknown setting: {key}")
            continue

        default = SETTINGS_DEFAULTS[key]
        # Coerce value to correct type
        if isinstance(default, bool):
            if isinstance(value, str):
                value = value.lower() in ("true", "1", "yes")
            else:
                value = bool(value)
        elif isinstance(default, int):
            try:
                value = int(value)
            except (ValueError, TypeError):
                errors.append(f"Invalid integer for {key}: {value}")
                continue
        else:
            value = str(value)

        settings[key] = value
        saved += 1

        # Track if LAN/port/auth settings changed (require restart)
        if key in ("gui_lan_enabled", "gui_port", "gui_host",
                    "gui_username", "gui_password"):
            restart_required = True

    # Persist to disk
    save_config(workspace_parent, projects, settings)

    # Update live server settings
    handler.server.settings = settings

    return ok_response({
        "saved": saved,
        "errors": errors,
        "restart_required": restart_required,
    })


@api_route("GET", "/api/config/projects")
def handle_get_projects(handler, match, query_params):
    """Return configured projects list."""
    from torch.config import load_config

    result = load_config()
    if result is None:
        return error_response("Could not load config", 500)
    _workspace_parent, projects, settings = result

    active_project = getattr(handler.server, "proj_name", "")
    favourite = settings.get("favourite_project", "")

    items = []
    for name, info in projects.items():
        items.append({
            "name": name,
            "game_path": info.get("game_path", ""),
            "active": name == active_project,
            "favourite": name == favourite,
        })

    return ok_response({"projects": items})


@api_route("POST", "/api/config/delete-project")
def handle_delete_project(handler, match, query_params):
    """Remove a project from TORCH configuration (does NOT delete game files)."""
    from torch.config import load_config, save_config

    body = _read_json_body(handler)
    if not body or "project_name" not in body:
        return error_response("Missing 'project_name' in request body")

    target_name = body["project_name"]

    result = load_config()
    if result is None:
        return error_response("Could not load config", 500)
    workspace, projects, settings = result

    # Cannot delete active project
    active_name = getattr(handler.server, "proj_name", "")
    if target_name == active_name:
        return error_response(
            "Cannot delete the active project. Switch to a different project first."
        )

    if target_name not in projects:
        return error_response(f"Project '{target_name}' not found in config", 404)

    del projects[target_name]
    save_config(workspace, projects, settings)

    return ok_response({
        "message": f"Project '{target_name}' removed from TORCH configuration. "
                   f"Game files were NOT deleted.",
    })


@api_route("POST", "/api/config/switch-project")
def handle_switch_project(handler, match, query_params):
    """Switch the active project without restarting the server."""
    from torch.config import load_config
    from torch.web.events import broadcaster

    body = _read_json_body(handler)
    if not body or "project" not in body:
        return error_response("Missing 'project' in request body")

    target_name = body["project"]

    # Validate the project exists in config
    result = load_config()
    if result is None:
        return error_response("Could not load config", 500)
    workspace, projects, _settings = result

    if target_name not in projects:
        return error_response(f"Project '{target_name}' not found in config", 404)

    # Derive paths (workspace already includes /TORCH from load_config)
    new_game_path = projects[target_name].get("game_path", "")
    new_project_dir = os.path.join(workspace, target_name)

    if not new_game_path or not os.path.isdir(new_game_path):
        return error_response(
            f"Game path for '{target_name}' does not exist: {new_game_path}", 400
        )

    # Update server state
    server = handler.server
    server.game_path = new_game_path
    server.project_dir = new_project_dir
    server.proj_name = target_name

    # Re-detect expansion version for the new project
    try:
        from torch.expansion_compat import detect_expansion_version, version_str
        ver = detect_expansion_version(new_game_path)
        server.expansion_version = version_str(ver) if ver else None
    except ImportError:
        server.expansion_version = None

    # Clear all cached data so new project's data loads fresh
    _species_list_cache.clear()
    _pre_evo_cache.clear()
    _trainer_list_cache.clear()
    _trainer_incbin_cache.clear()
    _move_list_cache.clear()
    _item_list_cache.clear()
    _item_icon_map_cache.clear()
    _holdable_items_cache.clear()
    _ability_list_cache.clear()
    _studio_maps_cache.clear()
    _data_cache.clear()
    _sprite_index_cache.clear()
    _game_scripts_cache.clear()

    try:
        from torch.gamedata import clear_gamedata_cache
        clear_gamedata_cache()
    except ImportError:
        pass

    # Broadcast status update so all connected clients refresh
    broadcaster.broadcast("project_switched", {
        "project": target_name,
        "game_path": new_game_path,
    })

    return ok_response({"project": target_name})


# ---------------------------------------------------------------------------
# Script Chains — API Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", "/api/chains")
def handle_chains_list(handler, match, query_params):
    """List all chains with summary data."""
    project_dir = _get_workspace_path(handler)
    if not project_dir:
        return error_response("No project directory configured", 500)

    from torch.chain_model import list_chains
    chains = list_chains(project_dir)
    return ok_response({"chains": chains})


@api_route("GET", r"/api/chains/discover")
def handle_chains_discover(handler, match, query_params):
    """Auto-discover potential chains from goto/call references."""
    project_dir = _get_workspace_path(handler)
    if not project_dir:
        return error_response("No project directory configured", 500)

    from torch.chain_model import discover_chains
    suggestions = discover_chains(project_dir)
    return ok_response({"suggestions": suggestions})


@api_route("GET", r"/api/chains/by-script/(?P<map_name>[A-Za-z0-9_]+)/(?P<script_name>[A-Za-z0-9_]+)")
def handle_chains_by_script(handler, match, query_params):
    """Find chains containing a specific script (or _all for any script on a map)."""
    map_name = match.group("map_name")
    script_name = match.group("script_name")
    project_dir = _get_workspace_path(handler)
    if not project_dir:
        return error_response("No project directory configured", 500)

    from torch.chain_model import find_chains_for_script, list_chains

    if script_name == "_all":
        # Return all chains that include any script on this map
        all_chains = list_chains(project_dir)
        chains = [c for c in all_chains if map_name in (c.get("maps") or [])]
        return ok_response({"chains": chains})

    chains = find_chains_for_script(project_dir, map_name, script_name)
    return ok_response({"chains": chains})


@api_route("GET", r"/api/chains/(?P<name>[A-Za-z0-9_]+)")
def handle_chain_get(handler, match, query_params):
    """Get full chain data by name."""
    name = match.group("name")
    project_dir = _get_workspace_path(handler)
    game_path = getattr(handler.server, "game_path", "")
    if not project_dir:
        return error_response("No project directory configured", 500)

    from torch.chain_model import load_chain
    chain_data = load_chain(project_dir, name)
    if chain_data is None:
        return error_response(f"Chain '{name}' not found", 404)

    # Enrich any incomplete triggers with computed fields from map data
    sequence = chain_data.get("sequence", [])
    segments = chain_data.get("segments", {})
    for entry in sequence:
        seg = segments.get(entry.get("script", ""))
        if seg and seg.get("trigger") and not seg["trigger"].get("npc_origin"):
            t = seg["trigger"]
            if t.get("type") in ("sight", "interact", "walk_over", "coord_event"):
                _enrich_trigger(t, chain_data, game_path,
                                seg.get("map", entry.get("map", "")),
                                entry.get("script", ""))

    # Include the head script's trigger_info so the slider works
    # for any script in the chain, not just the head.
    trigger_info = _chain_head_trigger_info(project_dir, game_path, chain_data)
    if trigger_info:
        # Merge chain trigger constraints into trigger_info
        if sequence:
            head_seg = segments.get(sequence[0].get("script", ""), {})
            head_trigger = head_seg.get("trigger") or {}
            # Sight: merge excluded distances
            excluded = head_trigger.get("excluded_distances", [])
            if excluded:
                trigger_info["excluded_distances"] = excluded
            # Talk: filter directions based on approach_tiles enabled state
            approach_tiles = head_trigger.get("approach_tiles", [])
            if approach_tiles and trigger_info.get("type") == "talk":
                # Map approach tile index → direction name
                dir_map = {0: "north", 1: "east", 2: "south", 3: "west"}
                enabled_dirs = []
                for i, tile in enumerate(approach_tiles):
                    if tile.get("enabled", True):
                        d = dir_map.get(i, "")
                        if d:
                            enabled_dirs.append(d)
                if enabled_dirs:
                    trigger_info["directions"] = enabled_dirs
                    # If only one direction remains, set it as the default
                    if len(enabled_dirs) == 1:
                        all_dirs = ["north", "south", "west", "east"]
                        trigger_info["default_distance"] = all_dirs.index(enabled_dirs[0]) if enabled_dirs[0] in all_dirs else 0
        chain_data["trigger_info"] = trigger_info

    return ok_response(chain_data)


@api_route("POST", "/api/chains")
def handle_chain_create(handler, match, query_params):
    """Create a new chain."""
    project_dir = _get_workspace_path(handler)
    if not project_dir:
        return error_response("No project directory configured", 500)

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)

    name = (body or {}).get("name", "").strip()
    head_script = (body or {}).get("head_script", "").strip()
    head_map = (body or {}).get("head_map", "").strip()
    if not name or not head_script or not head_map:
        return error_response("Required fields: name, head_script, head_map", 400)

    with _chain_lock:
        from torch.chain_model import load_chain, create_chain
        if load_chain(project_dir, name) is not None:
            return error_response(f"Chain '{name}' already exists", 409)

        chain_data = create_chain(project_dir, name, head_script, head_map)
        return ok_response(chain_data)


@api_route("POST", r"/api/chains/(?P<name>[A-Za-z0-9_]+)")
def handle_chain_update(handler, match, query_params):
    """Update an existing chain (full replacement or partial operations)."""
    name = match.group("name")
    project_dir = _get_workspace_path(handler)
    game_path = getattr(handler.server, "game_path", "")
    if not project_dir:
        return error_response("No project directory configured", 500)

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)

    if not body:
        return error_response("Empty request body", 400)

    with _chain_lock:
        from torch.chain_model import (
            load_chain, save_chain, add_segment, remove_segment,
            reorder_segments, update_cast, set_manual_override,
            clear_manual_override, validate_chain,
        )

        chain_data = load_chain(project_dir, name)
        if chain_data is None:
            return error_response(f"Chain '{name}' not found", 404)

        action = body.get("action", "replace")

        if action == "replace":
            # Full chain data replacement
            chain_data = body.get("data", chain_data)
            chain_data["chain"] = name  # Preserve name
            errors = validate_chain(chain_data)
            if errors:
                return error_response(f"Validation errors: {'; '.join(errors)}", 400)
            save_chain(project_dir, chain_data)

        elif action == "add_segment":
            script = body.get("script", "").strip()
            map_name = body.get("map", "").strip()
            position = body.get("position")
            if not script or not map_name:
                return error_response("add_segment requires 'script' and 'map'", 400)
            chain_data = add_segment(chain_data, script, map_name, position)
            save_chain(project_dir, chain_data)

        elif action == "remove_segment":
            script = body.get("script", "").strip()
            if not script:
                return error_response("remove_segment requires 'script'", 400)
            chain_data = remove_segment(chain_data, script)
            save_chain(project_dir, chain_data)

        elif action == "reorder":
            new_order = body.get("order", [])
            if not isinstance(new_order, list):
                return error_response("reorder requires 'order' as a list", 400)
            chain_data = reorder_segments(chain_data, new_order)
            save_chain(project_dir, chain_data)

        elif action == "update_cast":
            cast_id = body.get("cast_id", "").strip()
            events_map = body.get("events", {})
            if not cast_id:
                return error_response("update_cast requires 'cast_id'", 400)
            # Support removal via _remove flag
            if events_map.get("_remove"):
                cast = chain_data.get("cast", {})
                cast.pop(cast_id, None)
                save_chain(project_dir, chain_data)
            else:
                chain_data = update_cast(chain_data, cast_id, events_map)
                save_chain(project_dir, chain_data)

        elif action == "set_trigger":
            script = body.get("script", "").strip()
            trigger = body.get("trigger")
            if not script:
                return error_response("set_trigger requires 'script'", 400)
            seg = chain_data.get("segments", {}).get(script)
            if not seg:
                return error_response(f"Segment '{script}' not found", 404)

            # Enrich trigger with computed fields from map data
            if trigger and trigger.get("type") in ("sight", "talk", "interact"):
                # Normalize legacy "interact" to "talk"
                if trigger.get("type") == "interact":
                    trigger["type"] = "talk"
                map_name = seg.get("map", "")
                if map_name and game_path:
                    _enrich_trigger(trigger, chain_data, game_path, map_name, script)

            seg["trigger"] = trigger
            save_chain(project_dir, chain_data)

        elif action == "set_override":
            segment = body.get("segment", "").strip()
            actor = body.get("actor", "").strip()
            overrides = body.get("overrides", {})
            if not segment or not actor:
                return error_response("set_override requires 'segment' and 'actor'", 400)
            chain_data = set_manual_override(chain_data, segment, actor, overrides)
            save_chain(project_dir, chain_data)

        elif action == "clear_override":
            segment = body.get("segment", "").strip()
            actor = body.get("actor", "").strip()
            if not segment or not actor:
                return error_response("clear_override requires 'segment' and 'actor'", 400)
            chain_data = clear_manual_override(chain_data, segment, actor)
            save_chain(project_dir, chain_data)

        else:
            return error_response(f"Unknown action: {action}", 400)

        return ok_response(chain_data)


@api_route("POST", r"/api/chains/(?P<name>[A-Za-z0-9_]+)/sync")
def handle_chain_sync(handler, match, query_params):
    """Trigger a full sync of a chain."""
    name = match.group("name")
    project_dir = _get_workspace_path(handler)
    game_path = getattr(handler.server, "game_path", "")
    if not project_dir:
        return error_response("No project directory configured", 500)

    with _chain_lock:
        from torch.chain_model import load_chain, save_chain
        chain_data = load_chain(project_dir, name)
        if chain_data is None:
            return error_response(f"Chain '{name}' not found", 404)

        from torch.chain_sync import sync_chain
        result = sync_chain(project_dir, game_path, chain_data)

        if result.get("ok"):
            save_chain(project_dir, chain_data)

        return ok_response(result)


@api_route("GET", r"/api/chains/(?P<name>[A-Za-z0-9_]+)/sync-status")
def handle_chain_sync_status(handler, match, query_params):
    """Check staleness of a chain without running sync."""
    name = match.group("name")
    project_dir = _get_workspace_path(handler)
    game_path = getattr(handler.server, "game_path", "")
    if not project_dir:
        return error_response("No project directory configured", 500)

    from torch.chain_model import load_chain
    chain_data = load_chain(project_dir, name)
    if chain_data is None:
        return error_response(f"Chain '{name}' not found", 404)

    from torch.chain_sync import check_staleness
    result = check_staleness(project_dir, game_path, chain_data)
    return ok_response(result)


@api_route("POST", r"/api/chains/(?P<name>[A-Za-z0-9_]+)/simulate-at")
def handle_chain_simulate_at(handler, match, query_params):
    """Simulate through a chain at a specific player trigger distance.

    POST body: {script_name, player_distance}
    Returns the simulation frames for the target script, with all
    upstream scripts simulated at the given distance first.
    """
    name = match.group("name")
    project_dir = _get_workspace_path(handler)
    game_path = getattr(handler.server, "game_path", "")
    if not project_dir:
        return error_response("No project directory configured", 500)

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)

    script_name = body.get("script_name", "")
    player_distance = body.get("player_distance")
    if not script_name:
        return error_response("script_name is required", 400)
    if player_distance is None:
        return error_response("player_distance is required", 400)

    from torch.chain_model import load_chain
    chain_data = load_chain(project_dir, name)
    if chain_data is None:
        return error_response(f"Chain '{name}' not found", 404)

    from torch.chain_sync import simulate_chain_at_distance
    result = simulate_chain_at_distance(
        project_dir, game_path, chain_data, script_name, player_distance)

    if not result.get("ok"):
        return error_response(result.get("error", "Simulation failed"), 500)

    return ok_response({
        "frames": result["frames"],
        "cast": result["cast"],
        "sprite_index": result["sprite_index"],
    })


@api_route("DELETE", r"/api/chains/(?P<name>[A-Za-z0-9_]+)")
def handle_chain_delete(handler, match, query_params):
    """Delete a chain."""
    name = match.group("name")
    project_dir = _get_workspace_path(handler)
    if not project_dir:
        return error_response("No project directory configured", 500)

    with _chain_lock:
        from torch.chain_model import delete_chain
        if delete_chain(project_dir, name):
            return ok_response({"deleted": name})
        return error_response(f"Chain '{name}' not found", 404)


# ---------------------------------------------------------------------------
# Project Management — Backups, Forks
# ---------------------------------------------------------------------------

@api_route("GET", "/api/project/backups")
def handle_backup_list(handler, match, query_params):
    """List TORCH backups for the current project."""
    proj_name = getattr(handler.server, "proj_name", "")

    from torch.backup import (
        TORCH_BACKUP_DIR, _parse_torch_backups, _get_tier_info,
        _sanitize_project_name,
    )

    if not os.path.isdir(TORCH_BACKUP_DIR):
        return ok_response({"backups": [], "backup_dir": TORCH_BACKUP_DIR})

    entries = _parse_torch_backups(TORCH_BACKUP_DIR)

    # Filter to current project if available
    if proj_name:
        safe_proj = _sanitize_project_name(proj_name)
        entries = [e for e in entries
                   if e.get("project") == safe_proj or e.get("project") == "legacy"]

    milestone_paths, hot_keep = _get_tier_info(entries)

    backups = []
    for entry in reversed(entries):  # newest first
        path = entry.get("path", "")
        if path in milestone_paths:
            tier = "cold"
        elif path in hot_keep:
            tier = "hot"
        elif entry.get("version") is None:
            tier = "unknown"
        else:
            tier = "old"
        try:
            size_bytes = os.path.getsize(path) if os.path.isfile(path) else 0
        except OSError:
            size_bytes = 0
        backups.append({
            "filename": entry.get("filename", ""),
            "version": entry.get("version", ""),
            "date": entry.get("date_str", ""),
            "project": entry.get("project", ""),
            "tier": tier,
            "size_mb": round(size_bytes / (1024 * 1024), 1),
        })

    return ok_response({
        "backups": backups,
        "backup_dir": TORCH_BACKUP_DIR,
    })


@api_route("POST", "/api/project/backups/create")
def handle_backup_create(handler, match, query_params):
    """Create a new TORCH backup."""
    proj_name = getattr(handler.server, "proj_name", "")

    body = _read_json_body(handler)
    tag = body.get("tag", "") if body else ""

    from torch.backup import _create_torch_backup
    try:
        result = _create_torch_backup(
            tag=tag or None, project_name=proj_name or None)
        return ok_response({"created": True, "path": str(result) if result else None})
    except Exception as e:
        return error_response(f"Backup failed: {e}", 500)


@api_route("GET", "/api/project/forks")
def handle_fork_list(handler, match, query_params):
    """List project forks from the fork registry."""
    from torch.fork import _load_registry

    forks = _load_registry()

    result = []
    for fk in forks:
        dest = fk.get("game_path", "")
        exists = os.path.isdir(dest) if dest else False
        result.append({
            "name": fk.get("name", ""),
            "source_project": fk.get("source_project", ""),
            "game_path": dest,
            "created": fk.get("created", ""),
            "exists": exists,
        })

    return ok_response({
        "forks": sorted(result, key=lambda f: f.get("created", ""), reverse=True),
    })


@api_route("POST", "/api/project/forks/delete")
def handle_fork_delete(handler, match, query_params):
    """Delete a project fork by name."""
    import shutil
    from torch.fork import (
        _load_registry, _save_registry, _unregister_fork_project,
    )

    body = _read_json_body(handler)
    if not body or not body.get("name"):
        return error_response("Missing fork name", 400)

    fork_name = body["name"]
    forks = _load_registry()

    # Find the entry
    entry = None
    for fk in forks:
        if fk.get("name") == fork_name:
            entry = fk
            break

    if entry is None:
        return error_response(f"Fork '{fork_name}' not found", 404)

    dest = entry.get("game_path", "")

    # Delete the fork directory if it exists
    if dest and os.path.isdir(dest):
        try:
            shutil.rmtree(dest)
        except OSError as e:
            return error_response(f"Failed to delete fork directory: {e}", 500)

    # Remove from registry
    cleaned = [fk for fk in forks if fk.get("name") != fork_name]
    try:
        _save_registry(cleaned)
    except OSError as e:
        return error_response(f"Failed to update fork registry: {e}", 500)

    # Unregister from TORCH config
    settings = getattr(handler.server, "settings", {})
    try:
        _unregister_fork_project(fork_name, settings)
    except Exception:
        pass  # best-effort config cleanup

    return ok_response({"deleted": True, "name": fork_name})


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

@api_route("POST", "/api/shutdown")
def handle_shutdown(handler, match, query_params):
    """Shut down the web server gracefully."""
    event = getattr(handler.server, "shutdown_event", None)
    if event:
        event.set()  # signal the main loop to exit
    return ok_response({"status": "shutting_down"})


# ---------------------------------------------------------------------------
# Modular API extensions — import at end so @api_route registers into _API_ROUTES
# ---------------------------------------------------------------------------

import torch.web.api_flags      # noqa: E402,F401
import torch.web.api_items      # noqa: E402,F401
import torch.web.api_moves      # noqa: E402,F401
import torch.web.api_shops      # noqa: E402,F401
import torch.web.api_learnsets  # noqa: E402,F401
import torch.web.api_heals     # noqa: E402,F401
import torch.web.api_assets    # noqa: E402,F401
import torch.web.api_explorer  # noqa: E402,F401
import torch.web.api_scorch   # noqa: E402,F401
import torch.web.api_vault    # noqa: E402,F401
import torch.web.api_metatiles  # noqa: E402,F401
import torch.web.api_tilesets  # noqa: E402,F401
import torch.web.api_npcs      # noqa: E402,F401
import torch.web.api_npc_editor  # noqa: E402,F401
import torch.web.api_templates  # noqa: E402,F401
import torch.web.api_versions  # noqa: E402,F401
import torch.web.api_map_render  # noqa: E402,F401
import torch.web.api_events  # noqa: E402,F401
import torch.web.api_music  # noqa: E402,F401
import torch.web.api_stamps  # noqa: E402,F401
