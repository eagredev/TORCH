"""TORCH Custom Stamps — capture and manage reusable map templates.

Lets users capture any existing interior map as a reusable stamp and
manage their stamp collection.  Stamps are stored in the game project
under .torch/stamps/{stamp_id}/.
"""
# TORCH_MODULE: Custom Stamps
# TORCH_GROUP: Core
import copy
import json
import os
import re
import shutil
import tempfile

STAMPS_DIR = ".torch/stamps"
STAMP_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name):
    """Convert display name to a valid stamp ID.

    Lowercase, underscores for spaces/special chars, no leading/trailing
    underscores, collapsed runs.
    """
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    # collapse consecutive underscores
    s = re.sub(r"_+", "_", s)
    return s


def _map_name_to_const(map_name):
    """Convert folder name to MAP_CONST form (without MAP_ prefix).

    E.g. 'LittlerootTown_House1' -> 'LITTLEROOT_TOWN_HOUSE1'.
    Insert underscores before uppercase letters that follow lowercase.
    """
    if not map_name:
        return ""
    snake = re.sub(r"([a-z])([A-Z])", r"\1_\2", map_name)
    return snake.upper()


def _parameterize_events(events, source_map):
    """Replace source map name references in event script fields with {map_name}.

    Deep-copies the event list before modification.  Replaces both the
    PascalCase map name and the UPPER_SNAKE MAP_CONST form.
    """
    result = []
    const_form = _map_name_to_const(source_map)
    map_const = "MAP_" + const_form

    for evt in events:
        evt = copy.deepcopy(evt)
        for key in ("script", "dest_map"):
            val = evt.get(key, "")
            if isinstance(val, str) and val:
                val = val.replace(source_map, "{map_name}")
                val = val.replace(map_const, "MAP_{MAP_CONST}")
                evt[key] = val
        result.append(evt)
    return result


def _parameterize_scripts(pory_text, source_map):
    """Replace source map name in .pory script text with {map_name} placeholder."""
    if not pory_text:
        return pory_text
    const_form = _map_name_to_const(source_map)
    map_const = "MAP_" + const_form
    text = pory_text.replace(source_map, "{map_name}")
    text = text.replace(map_const, "MAP_{MAP_CONST}")
    return text


# ---------------------------------------------------------------------------
# Stamp directory
# ---------------------------------------------------------------------------

def get_stamps_dir(game_path):
    """Return the stamps directory path, creating it if needed."""
    stamps_dir = os.path.join(game_path, STAMPS_DIR)
    os.makedirs(stamps_dir, exist_ok=True)
    return stamps_dir


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def list_stamps(game_path):
    """Return list of stamp summary dicts.

    Each dict has: id, name, description, width, height, tags, created_from.
    Returns empty list if stamps dir doesn't exist or is empty.
    """
    stamps_dir = os.path.join(game_path, STAMPS_DIR)
    if not os.path.isdir(stamps_dir):
        return []

    result = []
    try:
        entries = sorted(os.listdir(stamps_dir))
    except OSError:
        return []

    for entry in entries:
        manifest_path = os.path.join(stamps_dir, entry, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        result.append({
            "id": data.get("id", entry),
            "name": data.get("name", entry),
            "description": data.get("description", ""),
            "width": data.get("width"),
            "height": data.get("height"),
            "tags": data.get("tags", []),
            "created_from": data.get("created_from", ""),
        })
    return result


def load_stamp(game_path, stamp_id):
    """Load full manifest for a stamp. Returns None if not found."""
    manifest_path = os.path.join(game_path, STAMPS_DIR, stamp_id, "manifest.json")
    if not os.path.isfile(manifest_path):
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def create_stamp(game_path, source_map, name, exit_warp_indices,
                 include_scripts=False, description="", tags=None):
    """Capture an existing map as a reusable stamp.

    Steps:
    1. Load source map's map.json
    2. Look up layout in layouts.json to find blockdata/border paths
    3. Copy binary files to stamp directory
    4. Extract and parameterize events
    5. Tag specified warp indices as exit warps
    6. Optionally parameterize scripts.pory
    7. Write manifest + binaries
    8. Return the manifest dict

    Raises ValueError on missing source data.
    """
    # Load map.json
    map_json_path = os.path.join(game_path, "data", "maps", source_map, "map.json")
    if not os.path.isfile(map_json_path):
        raise ValueError(f"Source map not found: {source_map}")
    with open(map_json_path, "r", encoding="utf-8") as f:
        map_data = json.load(f)

    # Load layouts.json and find the layout
    layouts_path = os.path.join(game_path, "data", "layouts", "layouts.json")
    if not os.path.isfile(layouts_path):
        raise ValueError("layouts.json not found")
    with open(layouts_path, "r", encoding="utf-8") as f:
        layouts_data = json.load(f)

    layout_id = map_data.get("layout", "")
    layout_entry = None
    for entry in layouts_data.get("layouts", []):
        if entry.get("id") == layout_id:
            layout_entry = entry
            break
    if layout_entry is None:
        raise ValueError(f"Layout {layout_id} not found in layouts.json")

    # Read binary files
    blockdata_path = os.path.join(game_path, layout_entry.get("blockdata_filepath", ""))
    border_path = os.path.join(game_path, layout_entry.get("border_filepath", ""))

    if not os.path.isfile(blockdata_path):
        raise ValueError(f"Blockdata file not found: {blockdata_path}")
    if not os.path.isfile(border_path):
        raise ValueError(f"Border file not found: {border_path}")

    with open(blockdata_path, "rb") as f:
        map_bin = f.read()
    with open(border_path, "rb") as f:
        border_bin = f.read()

    # Parameterize events
    object_events = _parameterize_events(
        map_data.get("object_events", []), source_map)
    warp_events = _parameterize_events(
        map_data.get("warp_events", []), source_map)
    coord_events = _parameterize_events(
        map_data.get("coord_events", []), source_map)
    bg_events = _parameterize_events(
        map_data.get("bg_events", []), source_map)

    # Tag exit warps
    for i, warp in enumerate(warp_events):
        if i in exit_warp_indices:
            warp["role"] = "exit_warp"

    # Build door_positions from exit warps
    door_positions = []
    for warp in warp_events:
        if warp.get("role") == "exit_warp":
            door_positions.append({
                "x": warp.get("x", 0),
                "y": warp.get("y", 0),
                "elevation": warp.get("elevation", 0),
                "role": "exit",
            })

    # Optional script parameterization
    script_template = ""
    if include_scripts:
        pory_path = os.path.join(
            game_path, "data", "maps", source_map, "scripts.pory")
        if os.path.isfile(pory_path):
            with open(pory_path, "r", encoding="utf-8") as f:
                pory_text = f.read()
            script_template = _parameterize_scripts(pory_text, source_map)
    if not script_template:
        script_template = "mapscripts {map_name}_MapScripts {}\n"

    # Build manifest
    stamp_id = _slugify(name)
    manifest = {
        "stamp_version": STAMP_VERSION,
        "id": stamp_id,
        "name": name,
        "description": description,
        "created_from": source_map,
        "width": layout_entry.get("width"),
        "height": layout_entry.get("height"),
        "primary_tileset": layout_entry.get("primary_tileset", ""),
        "secondary_tileset": layout_entry.get("secondary_tileset", ""),
        "music": map_data.get("music", ""),
        "door_positions": door_positions,
        "object_events": object_events,
        "warp_events": warp_events,
        "coord_events": coord_events,
        "bg_events": bg_events,
        "script_template": script_template,
        "tags": tags or [],
    }

    # Write to stamp directory (atomic: write to temp, rename)
    stamps_dir = get_stamps_dir(game_path)
    stamp_dir = os.path.join(stamps_dir, stamp_id)
    tmp_dir = stamp_dir + ".tmp"

    # Clean up any leftover temp dir
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)

    os.makedirs(tmp_dir, exist_ok=True)

    # Write binaries
    with open(os.path.join(tmp_dir, "map.bin"), "wb") as f:
        f.write(map_bin)
    with open(os.path.join(tmp_dir, "border.bin"), "wb") as f:
        f.write(border_bin)

    # Write manifest
    manifest_path = os.path.join(tmp_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Atomic swap: remove old dir if exists, rename temp into place
    if os.path.exists(stamp_dir):
        shutil.rmtree(stamp_dir)
    os.rename(tmp_dir, stamp_dir)

    return manifest


def delete_stamp(game_path, stamp_id):
    """Delete a stamp directory. Returns True if deleted, False if not found."""
    stamp_dir = os.path.join(game_path, STAMPS_DIR, stamp_id)
    if not os.path.isdir(stamp_dir):
        return False
    shutil.rmtree(stamp_dir)
    return True


def validate_stamp_placement(game_path, stamp_id, parent_map,
                              door_x, door_y, map_name_override=None):
    """Dry-run validation for stamp placement.

    Returns dict with:
    - valid: bool
    - errors: list of blocking issues
    - warnings: list of non-blocking issues
    - suggested_name: auto-generated map name
    """
    errors = []
    warnings = []

    # Load stamp
    stamp = load_stamp(game_path, stamp_id)
    if stamp is None:
        errors.append(f"Stamp '{stamp_id}' not found")
        return {
            "valid": False,
            "errors": errors,
            "warnings": warnings,
            "suggested_name": "",
        }

    # Check parent map exists
    parent_json_path = os.path.join(
        game_path, "data", "maps", parent_map, "map.json")
    if not os.path.isfile(parent_json_path):
        errors.append(f"Parent map '{parent_map}' not found")
    else:
        # Check coordinates within parent map bounds via layout
        layouts_path = os.path.join(game_path, "data", "layouts", "layouts.json")
        if os.path.isfile(layouts_path):
            try:
                with open(layouts_path, "r", encoding="utf-8") as f:
                    layouts_data = json.load(f)
                with open(parent_json_path, "r", encoding="utf-8") as f:
                    parent_data = json.load(f)

                parent_layout_id = parent_data.get("layout", "")
                for entry in layouts_data.get("layouts", []):
                    if entry.get("id") == parent_layout_id:
                        pw = entry.get("width", 0)
                        ph = entry.get("height", 0)
                        if door_x < 0 or door_x >= pw:
                            errors.append(
                                f"door_x={door_x} out of bounds "
                                f"(parent width={pw})")
                        if door_y < 0 or door_y >= ph:
                            errors.append(
                                f"door_y={door_y} out of bounds "
                                f"(parent height={ph})")
                        break

                # Check for existing warp at those coords
                for warp in parent_data.get("warp_events", []):
                    if warp.get("x") == door_x and warp.get("y") == door_y:
                        warnings.append(
                            f"Parent map already has a warp at "
                            f"({door_x}, {door_y})")
                        break
            except (OSError, json.JSONDecodeError):
                pass

    # Check required tilesets exist
    primary = stamp.get("primary_tileset", "")
    secondary = stamp.get("secondary_tileset", "")
    tilesets_dir = os.path.join(game_path, "data", "tilesets")
    if primary:
        # gTileset_Building -> data/tilesets/primary/building or secondary/building
        tileset_name = primary.replace("gTileset_", "").lower()
        found = False
        for sub in ("primary", "secondary"):
            if os.path.isdir(os.path.join(tilesets_dir, sub, tileset_name)):
                found = True
                break
        if not found:
            errors.append(f"Required tileset '{primary}' not found in project")

    if secondary:
        tileset_name = secondary.replace("gTileset_", "").lower()
        found = False
        for sub in ("primary", "secondary"):
            if os.path.isdir(os.path.join(tilesets_dir, sub, tileset_name)):
                found = True
                break
        if not found:
            errors.append(
                f"Required tileset '{secondary}' not found in project")

    # Generate suggested name
    if map_name_override:
        suggested = map_name_override
    else:
        # Auto-generate from parent map + stamp name
        slug = stamp.get("name", stamp_id).replace(" ", "")
        slug = re.sub(r"[^A-Za-z0-9_]", "", slug)
        suggested = f"{parent_map}_{slug}"

    # Check name collision
    existing_map_dir = os.path.join(game_path, "data", "maps", suggested)
    if os.path.isdir(existing_map_dir):
        errors.append(f"Map '{suggested}' already exists")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "suggested_name": suggested,
    }
