"""TORCH Template Stamper — creates build-ready maps from building templates.

Core engine that takes template data + user input and creates all files,
registrations, and cross-references needed for a build-ready map.
"""
# TORCH_MODULE: Template Stamper
# TORCH_GROUP: Editors
import copy
import os
import subprocess

from torch.building_templates import TEMPLATES, INDOOR_DEFAULTS
from torch.project_files import (
    load_map_groups, load_layouts, load_map_json, load_heal_locations,
    write_map_groups, write_layouts, write_map_json, write_heal_locations,
    folder_to_map_const, clear_project_cache,
)

STAMPER_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _map_const_to_heal_id(map_const):
    """MAP_X -> HEAL_LOCATION_X."""
    if map_const.startswith("MAP_"):
        return "HEAL_LOCATION_" + map_const[4:]
    return "HEAL_LOCATION_" + map_const


def _layout_exists(layouts_data, layout_id):
    """Check if a layout ID is already in layouts.json."""
    for entry in layouts_data.get("layouts", []):
        if entry.get("id") == layout_id:
            return True
    return False


def _get_parent_layout_bounds(layouts_data, layout_id):
    """Get (width, height) for a layout ID, or None."""
    for entry in layouts_data.get("layouts", []):
        if entry.get("id") == layout_id:
            w = entry.get("width")
            h = entry.get("height")
            if isinstance(w, int) and isinstance(h, int):
                return (w, h)
    return None


def _find_parent_group(groups_data, parent_map):
    """Find the first group containing parent_map. Returns group name or None."""
    for group_name in groups_data.get("group_order", []):
        if parent_map in groups_data.get(group_name, []):
            return group_name
    return None


def _substitute_warps(template_warps, replacements, include_2f):
    """Process template warps: filter by conditional, substitute placeholders."""
    result = []
    for warp in template_warps:
        warp = dict(warp)  # shallow copy
        cond = warp.pop("conditional", None)
        if cond == "include_2f" and not include_2f:
            continue
        for key in ("dest_map", "dest_warp_id"):
            val = warp.get(key, "")
            for placeholder, replacement in replacements.items():
                val = val.replace(placeholder, replacement)
            warp[key] = val
        result.append(warp)
    return result


def _substitute_objects(template_objects, map_name):
    """Substitute {map_name} in NPC script labels."""
    result = []
    for obj in template_objects:
        obj = dict(obj)
        if "{map_name}" in obj.get("script", ""):
            obj["script"] = obj["script"].replace("{map_name}", map_name)
        result.append(obj)
    return result


def _build_map_json(template_key, map_name, layout_id, music,
                    region_map_section, warps, parent_map_data):
    """Build a complete map.json dict from template + computed values."""
    data = dict(INDOOR_DEFAULTS)
    data["id"] = folder_to_map_const(map_name)
    data["name"] = map_name
    data["layout"] = layout_id
    data["music"] = music
    data["region_map_section"] = region_map_section
    tmpl = TEMPLATES[template_key]
    data["object_events"] = _substitute_objects(tmpl["object_events"], map_name)
    data["warp_events"] = warps
    return data


def _ensure_shared_layout(game_path, template_key, layouts_data,
                          created_files):
    """Ensure the shared layout directory + layouts.json entry exist.

    Modifies layouts_data in place if an entry is added.
    Returns True on success, error string on failure.
    """
    tmpl = TEMPLATES[template_key]
    layout_id = tmpl["shared_layout_id"]
    layout_dir = tmpl["shared_layout_dir"]
    layout_path = os.path.join(game_path, "data", "layouts", layout_dir)

    # Create layout directory + binaries if missing
    if not os.path.isdir(layout_path):
        try:
            os.makedirs(layout_path, exist_ok=True)
        except OSError as e:
            return f"Failed to create layout dir {layout_dir}: {e}"
        map_bin_path = os.path.join(layout_path, "map.bin")
        border_bin_path = os.path.join(layout_path, "border.bin")
        try:
            with open(map_bin_path, "wb") as f:
                f.write(tmpl["map_bin"])
            created_files.append(
                f"data/layouts/{layout_dir}/map.bin")
            with open(border_bin_path, "wb") as f:
                f.write(tmpl["border_bin"])
            created_files.append(
                f"data/layouts/{layout_dir}/border.bin")
        except OSError as e:
            return f"Failed to write layout binaries for {layout_dir}: {e}"

    # Add layouts.json entry if missing
    if not _layout_exists(layouts_data, layout_id):
        layouts_data.setdefault("layouts", []).append({
            "id": layout_id,
            "name": tmpl["shared_layout_name"],
            "width": tmpl["width"],
            "height": tmpl["height"],
            "primary_tileset": tmpl["primary_tileset"],
            "secondary_tileset": tmpl["secondary_tileset"],
            "border_filepath": f"data/layouts/{layout_dir}/border.bin",
            "blockdata_filepath": f"data/layouts/{layout_dir}/map.bin",
        })

    return True


def _register_event_scripts_include(game_path, map_name, warnings):
    """Add .include line for a map's scripts.inc to data/event_scripts.s.

    Inserts after the last existing data/maps/ include line.
    Returns True if the line was added or already present.
    """
    es_path = os.path.join(game_path, "data", "event_scripts.s")
    inc_path_str = f"data/maps/{map_name}/scripts.inc"
    inc_line = f'\t.include "{inc_path_str}"\n'

    if not os.path.isfile(es_path):
        warnings.append(
            f"data/event_scripts.s not found -- skipping script "
            f"registration for {map_name}. Add the include manually.")
        return False

    try:
        with open(es_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        warnings.append(f"Could not read event_scripts.s: {e}")
        return False

    # Already present?
    for line in lines:
        if inc_path_str in line:
            return True

    # Insert after the last .include "data/maps/..." line
    last_map_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(".include") and "data/maps/" in stripped:
            last_map_idx = i

    if last_map_idx >= 0:
        lines.insert(last_map_idx + 1, inc_line)
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(inc_line)

    try:
        with open(es_path, "w", encoding="utf-8", errors="replace") as f:
            f.writelines(lines)
    except OSError as e:
        warnings.append(f"Could not write event_scripts.s: {e}")
        return False

    return True


def _compile_poryscript(game_path, map_name):
    """Compile scripts.pory -> scripts.inc via the Poryscript compiler.

    Best-effort: returns True if scripts.inc was produced, False otherwise.
    """
    compiler = os.path.join(game_path, "tools", "poryscript", "poryscript")
    if not os.path.isfile(compiler):
        return False
    map_dir = os.path.join(game_path, "data", "maps", map_name)
    pory_path = os.path.join(map_dir, "scripts.pory")
    inc_path = os.path.join(map_dir, "scripts.inc")
    if not os.path.isfile(pory_path):
        return False
    cmd = [compiler, "-i", pory_path, "-o", inc_path]
    font_cfg = os.path.join(game_path, "font_config.json")
    if os.path.isfile(font_cfg):
        cmd.extend(["-fc", font_cfg])
    try:
        subprocess.run(cmd, cwd=game_path, capture_output=True,
                       text=True, timeout=30)
    except Exception:
        return False
    return os.path.isfile(inc_path)


def _create_map_folder(game_path, map_name, map_json_data,
                       script_content, created_files):
    """Create map folder with map.json, scripts.pory, and compiled scripts.inc.

    Returns True on success, error string on failure.
    """
    map_dir = os.path.join(game_path, "data", "maps", map_name)
    try:
        os.makedirs(map_dir, exist_ok=True)
    except OSError as e:
        return f"Failed to create map dir {map_name}: {e}"

    # Write map.json
    if not write_map_json(game_path, map_name, map_json_data):
        return f"Failed to write map.json for {map_name}"
    created_files.append(f"data/maps/{map_name}/map.json")

    # Write scripts.pory
    script_path = os.path.join(map_dir, "scripts.pory")
    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)
    except OSError as e:
        return f"Failed to write scripts.pory for {map_name}: {e}"
    created_files.append(f"data/maps/{map_name}/scripts.pory")

    # Compile scripts.pory -> scripts.inc (best-effort)
    if _compile_poryscript(game_path, map_name):
        created_files.append(f"data/maps/{map_name}/scripts.inc")

    return True


def _add_maps_to_group(groups_data, map_names, map_group, parent_map,
                       warnings):
    """Add maps to a group in groups_data. Returns True or error string."""
    if map_group:
        if map_group not in groups_data.get("group_order", []):
            groups_data.setdefault("group_order", []).append(map_group)
            groups_data[map_group] = []
        for name in map_names:
            groups_data[map_group].append(name)
    else:
        found_group = _find_parent_group(groups_data, parent_map)
        if found_group:
            for name in map_names:
                groups_data[found_group].append(name)
        else:
            warnings.append(
                f"Parent map '{parent_map}' not found in any map group. "
                "Maps not added to map_groups.json."
            )
    return True


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_common(game_path, parent_map, door_x, door_y,
                     target_names):
    """Shared validation for all stamp types.

    Returns (errors, warnings, parent_data, layouts_data, groups_data).
    """
    errors = []
    warnings = []

    # Parent map folder exists
    parent_dir = os.path.join(game_path, "data", "maps", parent_map)
    if not os.path.isdir(parent_dir):
        errors.append(f"Parent map '{parent_map}' not found in data/maps/")

    # Load parent map.json
    clear_project_cache()
    parent_data = load_map_json(game_path, parent_map)
    if not parent_data:
        if not errors:
            errors.append(f"Could not load map.json for '{parent_map}'")
    else:
        # Indoor warning
        if parent_data.get("map_type") == "MAP_TYPE_INDOOR":
            warnings.append(
                f"'{parent_map}' is MAP_TYPE_INDOOR — building templates "
                "are typically placed on outdoor/town maps."
            )
        # Check warp at coords
        for warp in parent_data.get("warp_events", []):
            if warp.get("x") == door_x and warp.get("y") == door_y:
                warnings.append(
                    f"A warp already exists at ({door_x}, {door_y}) "
                    f"in {parent_map}."
                )
                break

    # Load layouts for bounds check
    layouts_data = load_layouts(game_path)
    if not layouts_data:
        errors.append("Could not load layouts.json")
    elif parent_data:
        layout_id = parent_data.get("layout", "")
        bounds = _get_parent_layout_bounds(layouts_data, layout_id)
        if bounds:
            w, h = bounds
            if door_x < 0 or door_x >= w or door_y < 0 or door_y >= h:
                errors.append(
                    f"Coordinates ({door_x}, {door_y}) are outside "
                    f"'{parent_map}' layout bounds ({w}x{h})"
                )

    # Target maps don't already exist
    for name in target_names:
        target_dir = os.path.join(game_path, "data", "maps", name)
        if os.path.isdir(target_dir):
            errors.append(f"Map '{name}' already exists")

    # Load groups
    groups_data = load_map_groups(game_path)
    if not groups_data:
        errors.append("Could not load map_groups.json")

    return errors, warnings, parent_data, layouts_data, groups_data


def validate_stamp(game_path, template_type, parent_map, door_x, door_y,
                   include_2f=True, town_name=None):
    """Dry-run validation. Returns preview without creating anything."""
    town = town_name or parent_map

    if template_type == "pokecenter":
        targets = [f"{town}_PokemonCenter_1F"]
        if include_2f:
            targets.append(f"{town}_PokemonCenter_2F")
    elif template_type == "pokemart":
        targets = [f"{town}_Mart"]
    else:
        return {"valid": False, "errors": [f"Unknown template: {template_type}"],
                "warnings": [], "preview": {}}

    errors, warnings, parent_data, layouts_data, groups_data = \
        _validate_common(game_path, parent_map, door_x, door_y, targets)

    # Build preview
    files_to_create = []
    files_to_modify = []

    for t in targets:
        files_to_create.append(f"data/maps/{t}/map.json")
        files_to_create.append(f"data/maps/{t}/scripts.pory")

    # Check if shared layouts need creating
    if layouts_data:
        if template_type == "pokecenter":
            tmpl_keys = ["pokecenter_1f"]
            if include_2f:
                tmpl_keys.append("pokecenter_2f")
        else:
            tmpl_keys = ["pokemart"]
        for tk in tmpl_keys:
            tmpl = TEMPLATES[tk]
            lid = tmpl["shared_layout_id"]
            ldir = tmpl["shared_layout_dir"]
            if not _layout_exists(layouts_data, lid):
                files_to_create.append(f"data/layouts/{ldir}/map.bin")
                files_to_create.append(f"data/layouts/{ldir}/border.bin")
                if "data/layouts/layouts.json" not in files_to_modify:
                    files_to_modify.append("data/layouts/layouts.json")

    files_to_modify.append("data/maps/map_groups.json")
    files_to_modify.append(f"data/maps/{parent_map}/map.json")
    files_to_modify.append("data/event_scripts.s")

    heal_id = None
    if template_type == "pokecenter":
        parent_const = folder_to_map_const(parent_map)
        heal_id = _map_const_to_heal_id(parent_const)
        files_to_modify.append("src/data/heal_locations.json")
        # Check if heal already exists
        heals = load_heal_locations(game_path)
        if heals:
            for h in heals:
                if h.get("id") == heal_id:
                    warnings.append(
                        f"Heal location '{heal_id}' already exists. "
                        "Will skip heal location creation."
                    )
                    break

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "preview": {
            "maps_to_create": targets,
            "files_to_create": files_to_create,
            "files_to_modify": files_to_modify,
            "heal_location_id": heal_id,
        },
    }


# ---------------------------------------------------------------------------
# Stampers
# ---------------------------------------------------------------------------

def stamp_pokecenter(game_path, parent_map, door_x, door_y,
                     include_2f=True, map_group=None, town_name=None):
    """Stamp a complete PokéCenter (1F + optional 2F).

    Returns result dict with success, created_files, modified_files, etc.
    """
    town = town_name or parent_map
    pc1f_name = f"{town}_PokemonCenter_1F"
    pc2f_name = f"{town}_PokemonCenter_2F"
    targets = [pc1f_name]
    if include_2f:
        targets.append(pc2f_name)

    errors, warnings, parent_data, layouts_data, groups_data = \
        _validate_common(game_path, parent_map, door_x, door_y, targets)

    if errors:
        return {"success": False, "error": "; ".join(errors),
                "created_files": [], "modified_files": [],
                "maps_created": [], "heal_location_id": None,
                "warnings": warnings}

    created_files = []
    modified_files = []
    maps_created = []

    parent_const = folder_to_map_const(parent_map)
    pc1f_const = folder_to_map_const(pc1f_name)
    pc2f_const = folder_to_map_const(pc2f_name)

    # Calculate parent warp ID before generating interior warps
    parent_warp_id = str(len(parent_data.get("warp_events", [])))

    region_map_section = parent_data.get("region_map_section",
                                         "MAPSEC_NONE")

    # ── Step 3: Ensure shared layouts ────────────────────────────
    layouts_modified = False
    layouts_before = len(layouts_data.get("layouts", []))

    res = _ensure_shared_layout(game_path, "pokecenter_1f",
                                layouts_data, created_files)
    if res is not True:
        return _error_result(res, created_files, modified_files,
                             maps_created, warnings)

    if include_2f:
        res = _ensure_shared_layout(game_path, "pokecenter_2f",
                                    layouts_data, created_files)
        if res is not True:
            return _error_result(res, created_files, modified_files,
                                 maps_created, warnings)

    if len(layouts_data.get("layouts", [])) != layouts_before:
        if not write_layouts(game_path, layouts_data):
            return _error_result("Failed to write layouts.json",
                                 created_files, modified_files,
                                 maps_created, warnings)
        modified_files.append("data/layouts/layouts.json")

    # ── Step 4: Create 1F map folder ─────────────────────────────
    replacements = {
        "{parent_map_const}": parent_const,
        "{parent_warp_id}": parent_warp_id,
        "{pc2f_map_const}": pc2f_const,
    }
    warps_1f = _substitute_warps(
        TEMPLATES["pokecenter_1f"]["warp_events"],
        replacements, include_2f,
    )
    map_json_1f = _build_map_json(
        "pokecenter_1f", pc1f_name,
        TEMPLATES["pokecenter_1f"]["shared_layout_id"],
        TEMPLATES["pokecenter_1f"]["music"],
        region_map_section, warps_1f, parent_data,
    )
    script_1f = TEMPLATES["pokecenter_1f"]["script_template"].replace(
        "{map_name}", pc1f_name)

    res = _create_map_folder(game_path, pc1f_name, map_json_1f,
                             script_1f, created_files)
    if res is not True:
        return _error_result(res, created_files, modified_files,
                             maps_created, warnings)
    maps_created.append(pc1f_name)

    # ── Step 4b: Create 2F map folder (if enabled) ───────────────
    if include_2f:
        replacements_2f = {
            "{pc1f_map_const}": pc1f_const,
        }
        warps_2f = _substitute_warps(
            TEMPLATES["pokecenter_2f"]["warp_events"],
            replacements_2f, True,
        )
        map_json_2f = _build_map_json(
            "pokecenter_2f", pc2f_name,
            TEMPLATES["pokecenter_2f"]["shared_layout_id"],
            TEMPLATES["pokecenter_2f"]["music"],
            region_map_section, warps_2f, parent_data,
        )
        script_2f = TEMPLATES["pokecenter_2f"]["script_template"]

        res = _create_map_folder(game_path, pc2f_name, map_json_2f,
                                 script_2f, created_files)
        if res is not True:
            return _error_result(res, created_files, modified_files,
                                 maps_created, warnings)
        maps_created.append(pc2f_name)

    # ── Step 5: Add maps to map_groups.json ──────────────────────
    _add_maps_to_group(groups_data, maps_created, map_group,
                       parent_map, warnings)
    if not write_map_groups(game_path, groups_data):
        return _error_result("Failed to write map_groups.json",
                             created_files, modified_files,
                             maps_created, warnings)
    modified_files.append("data/maps/map_groups.json")

    # ── Step 6: Add warp to parent map ───────────────────────────
    clear_project_cache()
    parent_data_fresh = load_map_json(game_path, parent_map)
    if not parent_data_fresh:
        parent_data_fresh = parent_data
    parent_data_fresh.setdefault("warp_events", []).append({
        "x": door_x,
        "y": door_y,
        "elevation": 0,
        "dest_map": pc1f_const,
        "dest_warp_id": "0",
    })
    if not write_map_json(game_path, parent_map, parent_data_fresh):
        return _error_result("Failed to update parent map.json",
                             created_files, modified_files,
                             maps_created, warnings)
    modified_files.append(f"data/maps/{parent_map}/map.json")

    # ── Step 7: Register in event_scripts.s ───────────────────────
    for mn in maps_created:
        if _register_event_scripts_include(game_path, mn, warnings):
            if "data/event_scripts.s" not in modified_files:
                modified_files.append("data/event_scripts.s")

    # ── Step 8: Register heal location ──────────────────────────
    heal_id = _register_heal_location(
        game_path, parent_map, parent_const, pc1f_const,
        door_x, door_y, warnings,
    )
    if heal_id:
        modified_files.append("src/data/heal_locations.json")

    return {
        "success": True,
        "error": None,
        "created_files": created_files,
        "modified_files": modified_files,
        "maps_created": maps_created,
        "heal_location_id": heal_id,
        "warnings": warnings,
    }


def stamp_pokemart(game_path, parent_map, door_x, door_y,
                   map_group=None, town_name=None):
    """Stamp a complete PokéMart.

    Returns result dict with success, created_files, modified_files, etc.
    """
    town = town_name or parent_map
    mart_name = f"{town}_Mart"
    targets = [mart_name]

    errors, warnings, parent_data, layouts_data, groups_data = \
        _validate_common(game_path, parent_map, door_x, door_y, targets)

    if errors:
        return {"success": False, "error": "; ".join(errors),
                "created_files": [], "modified_files": [],
                "maps_created": [], "heal_location_id": None,
                "warnings": warnings}

    created_files = []
    modified_files = []
    maps_created = []

    parent_const = folder_to_map_const(parent_map)
    parent_warp_id = str(len(parent_data.get("warp_events", [])))
    region_map_section = parent_data.get("region_map_section",
                                         "MAPSEC_NONE")

    # ── Ensure shared layout ─────────────────────────────────────
    layouts_before = len(layouts_data.get("layouts", []))
    res = _ensure_shared_layout(game_path, "pokemart",
                                layouts_data, created_files)
    if res is not True:
        return _error_result(res, created_files, modified_files,
                             maps_created, warnings)

    if len(layouts_data.get("layouts", [])) != layouts_before:
        if not write_layouts(game_path, layouts_data):
            return _error_result("Failed to write layouts.json",
                                 created_files, modified_files,
                                 maps_created, warnings)
        modified_files.append("data/layouts/layouts.json")

    # ── Create mart map folder ───────────────────────────────────
    replacements = {
        "{parent_map_const}": parent_const,
        "{parent_warp_id}": parent_warp_id,
    }
    warps = _substitute_warps(
        TEMPLATES["pokemart"]["warp_events"],
        replacements, False,
    )
    map_json = _build_map_json(
        "pokemart", mart_name,
        TEMPLATES["pokemart"]["shared_layout_id"],
        TEMPLATES["pokemart"]["music"],
        region_map_section, warps, parent_data,
    )
    script = TEMPLATES["pokemart"]["script_template"].replace(
        "{map_name}", mart_name)

    res = _create_map_folder(game_path, mart_name, map_json,
                             script, created_files)
    if res is not True:
        return _error_result(res, created_files, modified_files,
                             maps_created, warnings)
    maps_created.append(mart_name)

    # ── Add to map_groups.json ───────────────────────────────────
    _add_maps_to_group(groups_data, maps_created, map_group,
                       parent_map, warnings)
    if not write_map_groups(game_path, groups_data):
        return _error_result("Failed to write map_groups.json",
                             created_files, modified_files,
                             maps_created, warnings)
    modified_files.append("data/maps/map_groups.json")

    # ── Add warp to parent map ───────────────────────────────────
    clear_project_cache()
    parent_data_fresh = load_map_json(game_path, parent_map)
    if not parent_data_fresh:
        parent_data_fresh = parent_data
    mart_const = folder_to_map_const(mart_name)
    parent_data_fresh.setdefault("warp_events", []).append({
        "x": door_x,
        "y": door_y,
        "elevation": 0,
        "dest_map": mart_const,
        "dest_warp_id": "0",
    })
    if not write_map_json(game_path, parent_map, parent_data_fresh):
        return _error_result("Failed to update parent map.json",
                             created_files, modified_files,
                             maps_created, warnings)
    modified_files.append(f"data/maps/{parent_map}/map.json")

    # ── Register in event_scripts.s ─────────────────────────────
    for mn in maps_created:
        if _register_event_scripts_include(game_path, mn, warnings):
            if "data/event_scripts.s" not in modified_files:
                modified_files.append("data/event_scripts.s")

    return {
        "success": True,
        "error": None,
        "created_files": created_files,
        "modified_files": modified_files,
        "maps_created": maps_created,
        "heal_location_id": None,
        "warnings": warnings,
    }


def _register_heal_location(game_path, parent_map, parent_const,
                            pc1f_const, door_x, door_y, warnings):
    """Register a heal location for a PokéCenter.

    Returns the heal_id on success, None if skipped.
    """
    heal_id = _map_const_to_heal_id(parent_const)
    heals = load_heal_locations(game_path)
    if heals is None:
        warnings.append("Could not load heal_locations.json — skipping.")
        return None

    for h in heals:
        if h.get("id") == heal_id:
            warnings.append(
                f"Heal location '{heal_id}' already exists. Skipped."
            )
            return None

    heals.append({
        "id": heal_id,
        "map": parent_const,
        "x": door_x,
        "y": door_y,
        "respawn_map": pc1f_const,
        "respawn_npc": "1",
    })
    if not write_heal_locations(game_path, heals):
        warnings.append("Failed to write heal_locations.json.")
        return None
    return heal_id


def _error_result(error_msg, created_files, modified_files,
                  maps_created, warnings):
    """Build a failure result dict."""
    return {
        "success": False,
        "error": error_msg,
        "created_files": created_files,
        "modified_files": modified_files,
        "maps_created": maps_created,
        "heal_location_id": None,
        "warnings": warnings,
    }
