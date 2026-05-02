"""Heal Location Manager -- view, add, and remove heal locations."""
# TORCH_MODULE: Heal Locations
# TORCH_GROUP: Map Tools
import os
import json
import re

from torch.colours import GOLD, WHITE, CYAN, DIM, RST, GREEN, RED, BAR
from torch.ui import print_logo, _set_terminal_title, _k, clear_screen
from torch.config import SETTINGS_DEFAULTS, _nav_keys
from torch.list_widget import (
    ListState, guard_bounds, visible_range, overflow_above, overflow_below,
    marker, handle_input,
)
from torch.project_files import (
    load_heal_locations, write_heal_locations, load_map_json,
    folder_to_map_const, PATH_HEAL_LOCATIONS,
)

HEAL_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _map_const_to_heal_id(map_const):
    """Convert MAP_X to HEAL_LOCATION_X."""
    if map_const.startswith("MAP_"):
        return "HEAL_LOCATION_" + map_const[4:]
    return "HEAL_LOCATION_" + map_const


def _folder_to_heal_id(folder_name):
    """Convert PascalCase folder name to HEAL_LOCATION_UPPER_SNAKE."""
    mc = folder_to_map_const(folder_name)
    return _map_const_to_heal_id(mc)


def _validate_coordinate(raw):
    """Parse a coordinate string. Returns int or None."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _find_pokecenter_warps(game_path, map_name):
    """Scan a map's warp_events for Pokemon Center destinations.

    Returns list of dest_map strings that contain 'PokemonCenter' or
    'POKEMON_CENTER'.
    """
    data = load_map_json(game_path, map_name)
    if not data:
        return []
    results = []
    for warp in data.get("warp_events", []):
        dest = warp.get("dest_map", "")
        if "PokemonCenter" in dest or "POKEMON_CENTER" in dest:
            if dest not in results:
                results.append(dest)
    return results


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _heal_id_to_display(heal_id):
    """Convert HEAL_LOCATION_PETALBURG_CITY -> 'Petalburg City'.

    Strips prefix, splits on ``_``, title-cases each word.
    Keeps floor suffixes like ``1F`` / ``2F`` uppercase.
    """
    name = heal_id
    if name.startswith("HEAL_LOCATION_"):
        name = name[len("HEAL_LOCATION_"):]
    parts = name.split("_")
    out = []
    for p in parts:
        if re.fullmatch(r"[0-9]+[A-Z]+", p):
            out.append(p)  # keep 1F, 2F, B1F etc. as-is
        else:
            out.append(p.title())
    return " ".join(out)


def _map_const_to_display(map_const):
    """Convert MAP_PETALBURG_CITY_POKEMON_CENTER_1F -> human-readable.

    Strips ``MAP_`` prefix, then same logic as ``_heal_id_to_display``.
    """
    name = map_const
    if name.startswith("MAP_"):
        name = name[4:]
    parts = name.split("_")
    out = []
    for p in parts:
        if re.fullmatch(r"[0-9]+[A-Z]+", p):
            out.append(p)
        else:
            out.append(p.title())
    return " ".join(out)


def _map_const_to_folder(map_const, game_path=None):
    """Convert MAP_PETALBURG_CITY to PetalburgCity (PascalCase folder name).

    Inverse of ``folder_to_map_const``.  When *game_path* is provided,
    looks up the actual folder on disk (handles ambiguous underscore
    placement).  Without *game_path*, uses a heuristic that works for
    simple cases.

    MAP_PETALBURG_CITY              -> PetalburgCity
    MAP_PETALBURG_CITY_POKEMON_CENTER_1F -> PetalburgCity_PokemonCenter_1F
    """
    name = map_const
    if name.startswith("MAP_"):
        name = name[4:]

    # --- Disk lookup (preferred) ---
    if game_path:
        maps_dir = os.path.join(game_path, "data", "maps")
        if os.path.isdir(maps_dir):
            target = name.upper()
            for entry in os.listdir(maps_dir):
                if folder_to_map_const(entry) == map_const:
                    return entry

    # --- Heuristic fallback ---
    raw_parts = name.split("_")
    segments = []
    current = []
    for part in raw_parts:
        # Floor suffixes (1F, 2F, B1F, B2F) start a new underscore segment
        if re.fullmatch(r"[B]?[0-9]+[A-Z]+", part) and current:
            segments.append("".join(w.title() for w in current))
            segments.append(part)
            current = []
        else:
            current.append(part)
    if current:
        segments.append("".join(w.title() for w in current))
    return "_".join(segments)


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------


def _detect_heal_coords(game_path, map_name):
    """Auto-detect heal tile coordinates from PC warp data.

    The heal tile is always one tile south of the Pokemon Center door warp
    on the overworld.  Returns ``(x, y+1)`` or ``None``.
    """
    data = load_map_json(game_path, map_name)
    if not data:
        return None
    for warp in data.get("warp_events", []):
        dest = warp.get("dest_map", "")
        if "PokemonCenter" in dest or "POKEMON_CENTER" in dest:
            wx = warp.get("x")
            wy = warp.get("y")
            if wx is not None and wy is not None:
                return (wx, wy + 1)
    return None


def _detect_respawn_npc(game_path, respawn_map_folder):
    """Auto-detect the nurse NPC LOCALID from a Pokemon Center interior.

    Scans ``object_events`` for ``OBJ_EVENT_GFX_NURSE``.  Returns the
    object's ``local_id`` field if present, otherwise ``1`` (standard
    PC layout).  Returns ``None`` if no nurse found.
    """
    data = load_map_json(game_path, respawn_map_folder)
    if not data:
        return None
    for obj in data.get("object_events", []):
        gfx = obj.get("graphics_id", "")
        if "NURSE" in gfx.upper():
            return obj.get("local_id", 1)
    return None


# ---------------------------------------------------------------------------
# List view
# ---------------------------------------------------------------------------


def _render_list(locations, state, proj_name, nav_keys):
    """Render the heal locations list screen."""
    clear_screen()
    print_logo(f"Heal Locations  v{HEAL_VERSION}", proj_name)
    print(BAR)
    print(f"   {WHITE}{len(locations)} heal location{'s' if len(locations) != 1 else ''}{RST}")
    print(BAR)
    print()

    if not locations:
        print("  (no heal locations found)")
        print()
    else:
        above = overflow_above(state)
        if above:
            print(above)

        start, end = visible_range(state)
        for i in range(start, end):
            loc = locations[i]
            mk = marker(state, i)
            loc_id = loc.get("id", "???")
            display_name = _heal_id_to_display(loc_id)
            map_name = loc.get("map", "???")
            map_display = _map_const_to_display(map_name)
            x = loc.get("x", "?")
            y = loc.get("y", "?")

            print(f"  {mk} {GOLD}{display_name}{RST}")
            print(f"       Heal tile: {map_display} ({x}, {y})")
            if "respawn_map" in loc:
                respawn = loc.get("respawn_map", "???")
                respawn_display = _map_const_to_display(respawn)
                respawn_extra = ""
                if "respawn_x" in loc or "respawn_y" in loc:
                    rx = loc.get("respawn_x", "?")
                    ry = loc.get("respawn_y", "?")
                    respawn_extra = f" at ({rx}, {ry})"
                print(f"       Respawn: {DIM}{respawn_display}{respawn_extra}{RST}")
            else:
                print(f"       {DIM}Custom heal point{RST}")
            print()

        below = overflow_below(state)
        if below:
            print(below)

    # Command bar
    _, up_key, down_key, _ = nav_keys
    cmd_parts = [
        f"{_k('a')}{DIM}dd{RST}",
        f"{_k('v')} {DIM}edit{RST}",
        f"{_k('d')}{DIM}elete{RST}",
        f"{_k('g')} {DIM}scan{RST}",
        f"{_k('Enter')} {DIM}scroll{RST}",
        f"{_k(up_key)} {DIM}up{RST}",
        f"{_k(down_key)} {DIM}down{RST}",
        f"{_k('q')} {DIM}back{RST}",
    ]
    print("  " + "  ".join(cmd_parts))
    print()


def _list_view(game_path, settings, proj_name):
    """Main list view loop for heal locations."""
    _set_terminal_title("TORCH -- Heal Locations")
    nav = _nav_keys(settings)
    page_size = settings.get("map_list_page_size", SETTINGS_DEFAULTS.get("map_list_page_size", 15))

    # Auto-scan for drift on first open
    _checked_drift = False

    while True:
        locations = load_heal_locations(game_path) or []

        if not _checked_drift:
            _checked_drift = True
            drift = _scan_drift(game_path, locations)
            if drift:
                clear_screen()
                print_logo(f"Heal Locations  v{HEAL_VERSION}", proj_name)
                print()
                should_fix = _show_drift_report(drift)
                if should_fix:
                    count = _apply_drift_fixes(game_path, drift, locations)
                    print(f"  {GREEN}Fixed {count} location(s).{RST}")
                    input("  Press Enter > ")
                    locations = load_heal_locations(game_path) or []

        state = ListState(len(locations), page_size=page_size)
        # Inner loop (re-render without reloading data)
        while True:
            guard_bounds(state)
            _render_list(locations, state, proj_name, nav)

            try:
                raw = input(f"  {GOLD}>{RST} ")
            except (EOFError, KeyboardInterrupt):
                return

            key = raw.strip().lower()

            if key == "q":
                return
            if key == "a":
                _add_wizard(game_path, settings, proj_name)
                break  # reload data
            if key == "v":
                if locations and 0 <= state.selected < len(locations):
                    _edit_location(game_path, locations, state.selected, proj_name)
                    break  # reload data
                else:
                    print(f"  {DIM}No location selected.{RST}")
                    input("  Press Enter > ")
            elif key == "d":
                if locations and 0 <= state.selected < len(locations):
                    _delete_location(game_path, locations, state.selected, proj_name)
                    break  # reload data
                else:
                    print(f"  {DIM}No location selected.{RST}")
                    input("  Press Enter > ")
            elif key == "g":
                _global_scan(game_path, proj_name)
                break  # reload data (scan can now add entries)
            else:
                handle_input(state, raw, nav)


# ---------------------------------------------------------------------------
# Add wizard
# ---------------------------------------------------------------------------


def _pick_map_name(game_path):
    """Prompt user to enter a map folder name. Returns name or None."""
    print()
    print(f"  {WHITE}Add Heal Location{RST}")
    print(BAR)
    print()
    print(f"  Enter the map folder name (e.g. PetalburgCity).")
    print(f"  This is the map where the player heals (usually the")
    print(f"  overworld city/town map).")
    print()
    try:
        name = input(f"  Map name > ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not name:
        print(f"  {RED}Cancelled.{RST}")
        input("  Press Enter > ")
        return None
    return name


def _prompt_coordinates(label):
    """Prompt for X,Y coordinates. Returns (x, y) or None."""
    print()
    print(f"  {label}")
    print(f"  Open this map in Porymap. Hover over the heal tile")
    print(f"  (usually the Pokemon Center entrance).")
    print(f"  Enter the X,Y coordinates from the Porymap status bar.")
    print()
    try:
        raw_x = input(f"  X coordinate > ").strip()
        x = _validate_coordinate(raw_x)
        if x is None:
            print(f"  {RED}Invalid X coordinate.{RST}")
            input("  Press Enter > ")
            return None
        raw_y = input(f"  Y coordinate > ").strip()
        y = _validate_coordinate(raw_y)
        if y is None:
            print(f"  {RED}Invalid Y coordinate.{RST}")
            input("  Press Enter > ")
            return None
    except (EOFError, KeyboardInterrupt):
        return None
    return (x, y)


def _prompt_respawn_map(game_path, map_name):
    """Prompt for respawn map, auto-suggesting Pokemon Centers. Returns str or None."""
    suggestions = _find_pokecenter_warps(game_path, map_name)

    print()
    if suggestions:
        print(f"  {GREEN}Found Pokemon Center connection(s):{RST}")
        for i, s in enumerate(suggestions, 1):
            print(f"    {i}. {s}")
        print()
        print(f"  Press Enter to use the first suggestion, or type a")
        print(f"  different map constant.")
        print()
        try:
            raw = input(f"  Respawn map [{suggestions[0]}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not raw:
            return suggestions[0]
        return raw
    else:
        print(f"  No Pokemon Center warp found for {map_name}.")
        print(f"  Enter the respawn map constant manually.")
        print(f"  (e.g. MAP_PETALBURG_CITY_POKEMON_CENTER_1F)")
        print()
        try:
            raw = input(f"  Respawn map > ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not raw:
            print(f"  {RED}Cancelled.{RST}")
            input("  Press Enter > ")
            return None
        return raw


def _prompt_respawn_npc():
    """Prompt for respawn NPC LOCALID. Returns str or None."""
    print()
    print(f"  The respawn NPC is typically the nurse in the Pokemon Center.")
    print(f"  Enter the LOCALID constant (e.g. LOCALID_PETALBURG_NURSE).")
    print()
    try:
        raw = input(f"  Respawn NPC > ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw:
        print(f"  {RED}Cancelled.{RST}")
        input("  Press Enter > ")
        return None
    return raw


def _prompt_optional_respawn_coords():
    """Ask if custom respawn coordinates are needed. Returns (x, y) or None."""
    print()
    print(f"  {DIM}Most Pokemon Centers use default respawn coordinates.{RST}")
    try:
        answer = input(f"  Set custom respawn X,Y? [y/N] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer not in ("y", "yes"):
        return None
    try:
        raw_x = input(f"  Respawn X > ").strip()
        x = _validate_coordinate(raw_x)
        if x is None:
            print(f"  {RED}Invalid coordinate, skipping.{RST}")
            input("  Press Enter > ")
            return None
        raw_y = input(f"  Respawn Y > ").strip()
        y = _validate_coordinate(raw_y)
        if y is None:
            print(f"  {RED}Invalid coordinate, skipping.{RST}")
            input("  Press Enter > ")
            return None
    except (EOFError, KeyboardInterrupt):
        return None
    return (x, y)


def _wizard_coords(game_path, map_name, map_const):
    """Auto-detect or prompt for heal tile coordinates.

    Returns ``(x, y)`` or ``None`` on cancel.
    """
    auto = _detect_heal_coords(game_path, map_name)
    if auto:
        ax, ay = auto
        display = _map_const_to_display(map_const)
        print(f"\n  {GREEN}Auto-detected heal tile at ({ax}, {ay}){RST}")
        print(f"  {DIM}(one tile south of the Pokemon Center entrance on {display}){RST}")
        try:
            answer = input(f"\n  Use these coordinates? [Y/n] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if answer in ("", "y", "yes"):
            return (ax, ay)
    return _prompt_coordinates("Heal tile coordinates (on the overworld map):")


def _wizard_respawn(game_path, map_name):
    """Auto-detect or prompt for respawn map + NPC.

    Returns ``(respawn_map, respawn_npc)`` or ``None`` on cancel.
    """
    suggestions = _find_pokecenter_warps(game_path, map_name)
    if suggestions:
        respawn_map = suggestions[0]
        respawn_folder = _map_const_to_folder(respawn_map, game_path)
        auto_npc = _detect_respawn_npc(game_path, respawn_folder)
        respawn_display = _map_const_to_display(respawn_map)
        if auto_npc is not None:
            respawn_npc = str(auto_npc)
            npc_note = " (Nurse auto-detected)"
        else:
            respawn_npc = "1"
            npc_note = f" {DIM}(no nurse found, using default){RST}"

        print(f"\n  {GREEN}Respawn: {respawn_display}{npc_note}{RST}")
        try:
            answer = input(f"  Use this? [Y/n] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if answer in ("", "y", "yes"):
            return (respawn_map, respawn_npc)

    respawn_map = _prompt_respawn_map(game_path, map_name)
    if respawn_map is None:
        return None
    respawn_npc = _prompt_respawn_npc()
    if respawn_npc is None:
        return None
    return (respawn_map, respawn_npc)


def _pick_heal_type():
    """Ask what type of heal location to add.

    Returns ``"pokecenter"``, ``"custom"``, or ``None`` on cancel.
    """
    print()
    print(f"  {WHITE}What type of heal location?{RST}")
    print(BAR)
    print()
    print(f"  [1] Pokemon Center {DIM}(auto-detect from map data){RST}")
    print(f"  [2] Custom heal point {DIM}(bed, campfire, shrine, etc.){RST}")
    print()
    try:
        raw = input(f"  Type (1/2, q to cancel) > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if raw in ("q",):
        return None
    if raw in ("2",):
        return "custom"
    # Default = pokecenter (Enter or "1")
    return "pokecenter"


def _pick_custom_map_name(game_path):
    """Prompt for a map folder name for a custom heal point. Returns name or None."""
    print()
    print(f"  {WHITE}Custom Heal Point{RST}")
    print(BAR)
    print()
    print(f"  Enter the map folder name where the heal object is.")
    print(f"  This could be any map -- a house, cave, camp, etc.")
    print()
    try:
        name = input(f"  Map name > ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not name:
        print(f"  {RED}Cancelled.{RST}")
        input("  Press Enter > ")
        return None
    # Warn if folder doesn't exist (non-blocking)
    maps_dir = os.path.join(game_path, "data", "maps")
    if os.path.isdir(maps_dir) and not os.path.isdir(os.path.join(maps_dir, name)):
        print(f"  {GOLD}Warning: folder '{name}' not found in data/maps/.{RST}")
        print(f"  {DIM}(You can still add the heal location and create the map later.){RST}")
    return name


def _prompt_custom_heal_id(default_suffix):
    """Prompt for optional custom heal ID suffix.

    *default_suffix* is the auto-generated suffix from the folder name
    (e.g. ``"PLAYER_BEDROOM"``).  Returns the final suffix string.
    """
    print()
    print(f"  {DIM}Auto-generated ID suffix: {default_suffix}{RST}")
    print(f"  Useful to customise when a map has multiple heal points")
    print(f"  (e.g. a camp and a cabin on the same route).")
    print()
    try:
        raw = input(f"  Custom suffix? (blank = use '{default_suffix}') > ").strip()
    except (EOFError, KeyboardInterrupt):
        return default_suffix
    if not raw:
        return default_suffix
    # Normalise to UPPER_SNAKE
    return re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").upper()


def _prompt_custom_coordinates():
    """Prompt for manual X/Y coordinates for a custom heal point.

    Returns ``(x, y)`` or ``None`` on cancel.
    """
    print()
    print(f"  {WHITE}Heal tile coordinates{RST}")
    print(f"  These are the coordinates where the player will appear")
    print(f"  after blacking out.")
    print(f"  Open the map in Porymap, hover over the spot where the")
    print(f"  player should wake up, and read the X,Y from the status bar.")
    print()
    try:
        raw_x = input(f"  X coordinate > ").strip()
        x = _validate_coordinate(raw_x)
        if x is None:
            print(f"  {RED}Invalid X coordinate.{RST}")
            input("  Press Enter > ")
            return None
        raw_y = input(f"  Y coordinate > ").strip()
        y = _validate_coordinate(raw_y)
        if y is None:
            print(f"  {RED}Invalid Y coordinate.{RST}")
            input("  Press Enter > ")
            return None
    except (EOFError, KeyboardInterrupt):
        return None
    return (x, y)


def _prompt_custom_respawn(game_path, map_name):
    """Ask whether to add optional respawn data for a custom heal point.

    Returns ``(respawn_map, respawn_npc)`` or ``None`` (meaning no respawn).
    """
    print()
    print(f"  {DIM}Most custom heal points don't need respawn data.{RST}")
    print(f"  {DIM}Respawn data controls where the player wakes up inside{RST}")
    print(f"  {DIM}a building after blacking out (like a Pokemon Center).{RST}")
    print()
    try:
        answer = input(f"  Add respawn data? (advanced) [y/N] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer not in ("y", "yes"):
        return None
    return _wizard_respawn(game_path, map_name)


def _show_custom_next_steps(heal_id, map_name):
    """Print post-add guidance for custom heal points."""
    print()
    print(BAR)
    print(f"  {WHITE}Next Steps{RST}")
    print(BAR)
    print()
    print(f"  Your heal location is registered. Now you need two scripts:")
    print()
    print(f"  {GOLD}1. Set the respawn point (mapscript){RST}")
    print(f"     In your map's OnTransition mapscript, add:")
    print(f"     {CYAN}setrespawn({heal_id}){RST}")
    print(f"     This tells the game \"if the player blacks out, send them here.\"")
    print()
    print(f"  {GOLD}2. Heal the player's team (interaction script){RST}")
    print(f"     On the object (bed, campfire, etc.), add a script with:")
    print(f"     {CYAN}special(HealPlayerParty){RST}")
    print(f"     {CYAN}waitstate{RST}")
    print(f"     This heals all Pokemon when the player interacts with it.")
    print()
    print(f"  {DIM}Tip: Use TORCH Script Studio to write these scripts.{RST}")
    print(f"  {DIM}Run: torch script {map_name}{RST}")
    print()


def _add_custom_wizard(game_path, settings, proj_name):
    """Interactive wizard to add a custom heal point."""
    # 1. Map name
    map_name = _pick_custom_map_name(game_path)
    if not map_name:
        return

    map_const = folder_to_map_const(map_name)

    # 2. Heal ID (with optional custom suffix)
    default_suffix = map_const[4:] if map_const.startswith("MAP_") else map_const
    suffix = _prompt_custom_heal_id(default_suffix)
    heal_id = "HEAL_LOCATION_" + suffix

    existing = load_heal_locations(game_path) or []
    if any(loc.get("id") == heal_id for loc in existing):
        print(f"\n  {RED}A heal location with ID {heal_id} already exists.{RST}")
        input("  Press Enter > ")
        return

    # 3. Coordinates
    coords = _prompt_custom_coordinates()
    if coords is None:
        return
    x, y = coords

    # 4. Optional respawn data
    respawn = _prompt_custom_respawn(game_path, map_name)
    entry = {"id": heal_id, "map": map_const, "x": x, "y": y}
    if respawn is not None:
        respawn_map, respawn_npc = respawn
        entry["respawn_map"] = respawn_map
        entry["respawn_npc"] = respawn_npc

    # 5. Summary + confirm
    _show_summary(entry)
    try:
        confirm = input(f"\n  Add this heal location? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm not in ("", "y", "yes"):
        print(f"  {DIM}Cancelled.{RST}")
        input("  Press Enter > ")
        return

    existing.append(entry)
    if write_heal_locations(game_path, existing):
        print(f"\n  {GREEN}Added {_heal_id_to_display(heal_id)}.{RST}")
        _show_custom_next_steps(heal_id, map_name)
    else:
        print(f"\n  {RED}Failed to write heal_locations.json.{RST}")
    input("  Press Enter > ")


def _add_wizard(game_path, settings, proj_name):
    """Interactive wizard to add a new heal location."""
    clear_screen()
    print_logo(f"Heal Locations  v{HEAL_VERSION}", proj_name)

    # Ask what type
    heal_type = _pick_heal_type()
    if heal_type is None:
        return
    if heal_type == "custom":
        _add_custom_wizard(game_path, settings, proj_name)
        return

    # --- Pokemon Center flow (existing) ---

    # 1. Map name
    map_name = _pick_map_name(game_path)
    if not map_name:
        return

    heal_id = _folder_to_heal_id(map_name)
    existing = load_heal_locations(game_path) or []
    if any(loc.get("id") == heal_id for loc in existing):
        print(f"\n  {RED}A heal location with ID {heal_id} already exists.{RST}")
        input("  Press Enter > ")
        return

    map_const = folder_to_map_const(map_name)

    # 2. Coordinates
    coords = _wizard_coords(game_path, map_name, map_const)
    if coords is None:
        return
    x, y = coords

    # 3. Respawn
    respawn = _wizard_respawn(game_path, map_name)
    if respawn is None:
        return
    respawn_map, respawn_npc = respawn

    # 4. Confirm
    entry = {
        "id": heal_id, "map": map_const,
        "x": x, "y": y,
        "respawn_map": respawn_map, "respawn_npc": respawn_npc,
    }
    _show_summary(entry)
    try:
        confirm = input(f"\n  Add this heal location? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm not in ("", "y", "yes"):
        print(f"  {DIM}Cancelled.{RST}")
        input("  Press Enter > ")
        return

    existing.append(entry)
    if write_heal_locations(game_path, existing):
        print(f"\n  {GREEN}Added {_heal_id_to_display(heal_id)}.{RST}")
    else:
        print(f"\n  {RED}Failed to write heal_locations.json.{RST}")
    input("  Press Enter > ")


def _show_summary(entry):
    """Print a summary of a heal location entry."""
    display_name = _heal_id_to_display(entry.get("id", "???"))
    map_display = _map_const_to_display(entry.get("map", "???"))
    print()
    print(BAR)
    print(f"  {WHITE}Summary{RST}")
    print(BAR)
    print(f"  Name:        {GOLD}{display_name}{RST}")
    print(f"  Heal tile:   {map_display} ({entry['x']}, {entry['y']})")
    if "respawn_map" in entry:
        respawn_display = _map_const_to_display(entry["respawn_map"])
        respawn_line = f"  Respawn:     {respawn_display}"
        if "respawn_x" in entry:
            respawn_line += f" at ({entry['respawn_x']}, {entry['respawn_y']})"
        print(respawn_line)
    else:
        print(f"  Respawn:     {DIM}(respawns in place){RST}")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def _delete_location(game_path, locations, idx, proj_name):
    """Confirm and delete a heal location."""
    loc = locations[idx]
    loc_id = loc.get("id", "???")

    print()
    print(f"  Delete {GOLD}{loc_id}{RST}?")
    print(f"  Map: {loc.get('map', '???')}")
    print()
    try:
        confirm = input(f"  Type 'delete' to confirm > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm != "delete":
        print(f"  {DIM}Cancelled.{RST}")
        input("  Press Enter > ")
        return

    new_list = [l for i, l in enumerate(locations) if i != idx]
    if write_heal_locations(game_path, new_list):
        print(f"\n  {GREEN}Removed {loc_id}.{RST}")
    else:
        print(f"\n  {RED}Failed to write heal_locations.json.{RST}")
    input("  Press Enter > ")


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


def _validate_location(game_path, entry):
    """Validate a heal location entry against on-disk data.

    Returns list of warning strings (empty = all good).
    Skips respawn/nurse checks for custom entries without respawn data.
    """
    warnings = []
    map_const = entry.get("map", "")
    folder = _map_const_to_folder(map_const, game_path)
    maps_dir = os.path.join(game_path, "data", "maps")

    # Check overworld map exists
    if not os.path.isdir(os.path.join(maps_dir, folder)):
        warnings.append(f"Map folder '{folder}' not found on disk.")

    # Check coords match warp+1 pattern (only for PC-based entries)
    expected = _detect_heal_coords(game_path, folder)
    if expected:
        ex, ey = expected
        if entry.get("x") != ex or entry.get("y") != ey:
            warnings.append(
                f"Coordinates ({entry.get('x')}, {entry.get('y')}) don't match "
                f"the detected PC entrance ({ex}, {ey})."
            )

    # Respawn checks only apply when respawn_map is present
    if "respawn_map" in entry:
        respawn_const = entry.get("respawn_map", "")
        respawn_folder = _map_const_to_folder(respawn_const, game_path)
        if not os.path.isdir(os.path.join(maps_dir, respawn_folder)):
            warnings.append(f"Respawn map folder '{respawn_folder}' not found on disk.")

        # Check nurse NPC
        if os.path.isdir(os.path.join(maps_dir, respawn_folder)):
            nurse = _detect_respawn_npc(game_path, respawn_folder)
            if nurse is None:
                warnings.append("No nurse NPC found in respawn map.")
            else:
                # Check nurse script health
                try:
                    from torch.npc_editor import validate_nurse_script
                    nurse_health = validate_nurse_script(game_path, respawn_folder)
                    if nurse_health and not nurse_health["script_ok"]:
                        warnings.append("Nurse NPC exists but has a broken/missing script.")
                except ImportError:
                    pass

    return warnings


def _edit_heal_map(loc):
    """Edit the heal tile map field.  Returns True if changed."""
    print(f"\n  Current: {loc.get('map', '???')}")
    try:
        raw = input(f"  New map folder name (e.g. PetalburgCity) > ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if raw:
        loc["map"] = folder_to_map_const(raw)
        loc["id"] = _folder_to_heal_id(raw)
        return True
    return False


def _edit_heal_coords(game_path, loc):
    """Edit heal tile coordinates with auto-detection.  Returns True if changed."""
    auto = _detect_heal_coords(game_path, _map_const_to_folder(loc.get("map", ""), game_path))
    if auto:
        print(f"\n  {GREEN}Auto-detected: ({auto[0]}, {auto[1]}){RST}")
        try:
            use = input(f"  Use auto-detected? [Y/n] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if use in ("", "y", "yes"):
            loc["x"], loc["y"] = auto
            return True
    coords = _prompt_coordinates("New heal tile coordinates:")
    if coords:
        loc["x"], loc["y"] = coords
        return True
    return False


def _edit_respawn_map(game_path, loc):
    """Edit the respawn map field.  Returns True if changed."""
    suggestions = _find_pokecenter_warps(
        game_path, _map_const_to_folder(loc.get("map", ""), game_path)
    )
    if suggestions:
        print(f"\n  {GREEN}Detected: {_map_const_to_display(suggestions[0])}{RST}")
        try:
            use = input(f"  Use this? [Y/n] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if use in ("", "y", "yes"):
            loc["respawn_map"] = suggestions[0]
            return True
    try:
        raw = input(f"  Respawn map constant > ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if raw:
        loc["respawn_map"] = raw
        return True
    return False


def _edit_respawn_npc(game_path, loc):
    """Edit the respawn NPC field.  Returns True if changed."""
    respawn_folder = _map_const_to_folder(loc.get("respawn_map", ""), game_path)
    auto_npc = _detect_respawn_npc(game_path, respawn_folder)
    if auto_npc is not None:
        print(f"\n  {GREEN}Auto-detected nurse: {auto_npc}{RST}")
        try:
            use = input(f"  Use this? [Y/n] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if use in ("", "y", "yes"):
            loc["respawn_npc"] = str(auto_npc)
            return True
    try:
        raw = input(f"  Respawn NPC LOCALID > ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if raw:
        loc["respawn_npc"] = raw
        return True
    return False


def _edit_respawn_coords(loc):
    """Edit the respawn coordinates.  Returns True if changed."""
    print(f"\n  {DIM}Leave blank to use default respawn position.{RST}")
    try:
        raw_x = input(f"  Respawn X (blank to clear) > ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not raw_x:
        loc.pop("respawn_x", None)
        loc.pop("respawn_y", None)
        return True
    vx = _validate_coordinate(raw_x)
    if vx is None:
        print(f"  {RED}Invalid coordinate.{RST}")
        input("  Press Enter > ")
        return False
    try:
        raw_y = input(f"  Respawn Y > ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    vy = _validate_coordinate(raw_y)
    if vy is None:
        print(f"  {RED}Invalid coordinate.{RST}")
        input("  Press Enter > ")
        return False
    loc["respawn_x"] = vx
    loc["respawn_y"] = vy
    return True


def _edit_location(game_path, locations, idx, proj_name):
    """Edit a single heal location's fields."""
    loc = locations[idx]
    display_name = _heal_id_to_display(loc.get("id", "???"))

    clear_screen()
    print_logo(f"Heal Locations  v{HEAL_VERSION}", proj_name)
    print()
    print(f"  {WHITE}Editing: {display_name}{RST}")
    print(BAR)

    map_display = _map_const_to_display(loc.get("map", "???"))
    has_respawn = "respawn_map" in loc
    if has_respawn:
        respawn_display = _map_const_to_display(loc["respawn_map"])
        respawn_npc_str = loc.get("respawn_npc", "???")
    else:
        respawn_display = f"{DIM}(not set){RST}"
        respawn_npc_str = f"{DIM}(not set){RST}"
    rx = loc.get("respawn_x")
    respawn_coords_str = f"({rx}, {loc.get('respawn_y')})" if rx is not None else "(default)"

    # Check nurse script health
    nurse_broken = False
    if has_respawn:
        try:
            from torch.npc_editor import validate_nurse_script
            respawn_folder = _map_const_to_folder(loc["respawn_map"], game_path)
            nurse_health = validate_nurse_script(game_path, respawn_folder)
            if nurse_health and not nurse_health["script_ok"]:
                nurse_broken = True
        except ImportError:
            pass

    print(f"  [1] Heal tile map:    {map_display} {DIM}({loc.get('map', '???')}){RST}")
    print(f"  [2] Heal tile coords: ({loc.get('x', '?')}, {loc.get('y', '?')})")
    print(f"  [3] Respawn map:      {respawn_display}")
    print(f"  [4] Respawn NPC:      {respawn_npc_str}")
    print(f"  [5] Respawn coords:   {respawn_coords_str}")
    if nurse_broken:
        print()
        print(f"  {RED}[!] Nurse script broken{RST}")
        print(f"  [6] Fix nurse script")
    print()

    max_choice = "6" if nurse_broken else "5"
    try:
        choice = input(f"  Which field to edit? (1-{max_choice}, q to cancel) > ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if choice == "q" or not choice:
        return

    # Handle nurse fix
    if choice == "6" and nurse_broken:
        try:
            from torch.npc_editor import fix_nurse_script
            respawn_folder = _map_const_to_folder(loc["respawn_map"], game_path)
            if fix_nurse_script(game_path, respawn_folder):
                print(f"\n  {GREEN}Nurse script fixed in {respawn_folder}.{RST}")
            else:
                print(f"\n  {RED}Failed to fix nurse script.{RST}")
        except ImportError:
            print(f"\n  {RED}NPC editor not available.{RST}")
        input("  Press Enter > ")
        return

    # Dispatch to field editor
    editors = {
        "1": lambda: _edit_heal_map(loc),
        "2": lambda: _edit_heal_coords(game_path, loc),
        "3": lambda: _edit_respawn_map(game_path, loc),
        "4": lambda: _edit_respawn_npc(game_path, loc),
        "5": lambda: _edit_respawn_coords(loc),
    }
    editor = editors.get(choice)
    if not editor:
        return
    changed = editor()

    if not changed:
        print(f"  {DIM}No changes made.{RST}")
        input("  Press Enter > ")
        return

    # Validate and warn
    warns = _validate_location(game_path, loc)
    if warns:
        print()
        for w in warns:
            print(f"  {GOLD}Warning: {w}{RST}")
        try:
            save = input(f"\n  Save anyway? [y/N] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if save not in ("y", "yes"):
            print(f"  {DIM}Cancelled.{RST}")
            input("  Press Enter > ")
            return
        loc["_user_override"] = True
    else:
        loc.pop("_user_override", None)

    locations[idx] = loc
    if write_heal_locations(game_path, locations):
        print(f"\n  {GREEN}Updated {display_name}.{RST}")
    else:
        print(f"\n  {RED}Failed to write heal_locations.json.{RST}")
    input("  Press Enter > ")


# ---------------------------------------------------------------------------
# Global scan
# ---------------------------------------------------------------------------


def _scan_drift(game_path, locations=None):
    """Check existing heal locations for coordinate drift.

    Compares stored coordinates against detected warp+1 position.
    Returns list of ``(index, loc_id, old_xy, new_xy, is_override)`` tuples.
    """
    if locations is None:
        locations = load_heal_locations(game_path) or []
    findings = []
    for i, loc in enumerate(locations):
        map_const = loc.get("map", "")
        folder = _map_const_to_folder(map_const, game_path)
        expected = _detect_heal_coords(game_path, folder)
        if expected is None:
            continue  # no PC warp — can't verify
        ex, ey = expected
        stored_x = loc.get("x")
        stored_y = loc.get("y")
        if stored_x != ex or stored_y != ey:
            is_override = loc.get("_user_override", False)
            findings.append((
                i, loc.get("id", "???"),
                (stored_x, stored_y), (ex, ey), is_override
            ))
    return findings


def _scan_missing(game_path):
    """Scan for city/town maps that may need a heal location.

    Returns list of ``(folder_name, map_type, has_heal, has_pc)`` tuples.
    Only includes maps typed as town or city.  *has_pc* indicates whether
    the map has a warp to a Pokemon Center (used to separate actionable
    missing entries from maps that simply don't have a PC).
    """
    heal_types = {"MAP_TYPE_TOWN", "MAP_TYPE_CITY"}
    existing = load_heal_locations(game_path) or []
    existing_maps = {loc.get("map") for loc in existing}

    maps_dir = os.path.join(game_path, "data", "maps")
    results = []
    if not os.path.isdir(maps_dir):
        return results

    for entry in sorted(os.listdir(maps_dir)):
        map_json_path = os.path.join(maps_dir, entry, "map.json")
        if not os.path.isfile(map_json_path):
            continue
        data = load_map_json(game_path, entry)
        if not data:
            continue
        map_type = data.get("map_type", "")
        if map_type not in heal_types:
            continue
        map_const = folder_to_map_const(entry)
        has_heal = map_const in existing_maps
        has_pc = bool(_find_pokecenter_warps(game_path, entry))
        results.append((entry, map_type, has_heal, has_pc))

    return results


# Keep old name as alias for test compat
_scan_maps_for_heal = _scan_missing


def _apply_drift_fixes(game_path, drift, locations):
    """Auto-fix drifted coordinates.  Returns count of fixes applied."""
    fixed = 0
    for idx, _loc_id, _old, new_xy, _override in drift:
        if 0 <= idx < len(locations):
            locations[idx]["x"] = new_xy[0]
            locations[idx]["y"] = new_xy[1]
            locations[idx].pop("_user_override", None)
            fixed += 1
    if fixed:
        write_heal_locations(game_path, locations)
    return fixed


def _show_drift_report(drift, interactive=True):
    """Display drift findings.  If *interactive*, offer auto-fix.

    Returns ``True`` if the caller should auto-fix.
    """
    overrides = sum(1 for *_, ov in drift if ov)
    print(f"  {GOLD}Detected {len(drift)} heal location(s) with changed coordinates:{RST}")
    print()
    for _idx, loc_id, old_xy, new_xy, is_ov in drift:
        name = _heal_id_to_display(loc_id)
        tag = f" {DIM}(manual override){RST}" if is_ov else ""
        print(f"    {name}: ({old_xy[0]}, {old_xy[1]}) -> ({new_xy[0]}, {new_xy[1]}){tag}")
    if overrides:
        print(f"\n  {DIM}{overrides} ignored change(s) from manual edits.{RST}")
    print()

    if not interactive:
        return False

    try:
        fix = input(
            f"  Auto-fix {len(drift)} drifted location(s)? [Y/n] > "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return fix in ("", "y", "yes")


def _auto_add_heal(game_path, folder):
    """Fully auto-detect and add a heal location for *folder*.

    Returns the entry dict on success, or ``None`` on failure.
    """
    map_const = folder_to_map_const(folder)
    heal_id = _map_const_to_heal_id(map_const)

    coords = _detect_heal_coords(game_path, folder)
    if coords is None:
        return None
    x, y = coords

    pc_warps = _find_pokecenter_warps(game_path, folder)
    if not pc_warps:
        return None
    respawn_map = pc_warps[0]

    respawn_folder = _map_const_to_folder(respawn_map, game_path)
    npc = _detect_respawn_npc(game_path, respawn_folder)
    respawn_npc = str(npc) if npc is not None else "1"

    return {
        "id": heal_id, "map": map_const,
        "x": x, "y": y,
        "respawn_map": respawn_map, "respawn_npc": respawn_npc,
    }


def _show_scan_results(results):
    """Print the scan table.  Returns list of actionable (folder, entry_preview) tuples."""
    actionable = []
    for folder, mtype, has_heal, has_pc in results:
        display = _map_const_to_display(folder_to_map_const(folder))
        short_type = mtype.replace("MAP_TYPE_", "").title()
        if has_heal:
            status = f"{GREEN}OK{RST}"
        elif has_pc:
            idx = len(actionable) + 1
            status = f"{RED}no heal location{RST}  {GOLD}[{idx}] add{RST}"
            actionable.append(folder)
        else:
            status = f"{DIM}no Pokemon Center{RST}"
        print(f"  {display:<30s} {DIM}{short_type:<8s}{RST}  {status}")
    return actionable


def _global_scan(game_path, proj_name):
    """Run drift check + missing-map scan and display results."""
    clear_screen()
    print_logo(f"Heal Locations  v{HEAL_VERSION}", proj_name)
    print(BAR)
    print(f"   {WHITE}Heal Location Scan{RST}")
    print(BAR)
    print()

    # --- Drift check ---
    locations = load_heal_locations(game_path) or []
    drift = _scan_drift(game_path, locations)
    if drift:
        should_fix = _show_drift_report(drift)
        if should_fix:
            count = _apply_drift_fixes(game_path, drift, locations)
            print(f"  {GREEN}Fixed {count} location(s).{RST}")
        print()

    # --- Nurse script health check ---
    nurse_broken = []
    try:
        from torch.npc_editor import validate_nurse_script
        for loc in locations:
            if "respawn_map" not in loc:
                continue
            respawn_const = loc.get("respawn_map", "")
            respawn_folder = _map_const_to_folder(respawn_const, game_path)
            nurse_health = validate_nurse_script(game_path, respawn_folder)
            if nurse_health and not nurse_health["script_ok"]:
                nurse_broken.append((loc.get("id", "???"), respawn_folder))
    except ImportError:
        pass

    if nurse_broken:
        print(f"  {GOLD}Nurse script issues ({len(nurse_broken)}):{RST}")
        for loc_id, folder in nurse_broken:
            name = _heal_id_to_display(loc_id)
            print(f"    {name}: nurse in {folder} has broken/missing script")
        print()
        try:
            fix_nurses = input(
                f"  Auto-fix {len(nurse_broken)} nurse script(s)? [Y/n] > "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            fix_nurses = "n"
        if fix_nurses in ("", "y", "yes"):
            try:
                from torch.npc_editor import fix_nurse_script
                fixed = 0
                for _loc_id, folder in nurse_broken:
                    if fix_nurse_script(game_path, folder):
                        fixed += 1
                print(f"  {GREEN}Fixed {fixed} nurse script(s).{RST}")
            except ImportError:
                print(f"  {RED}NPC editor not available.{RST}")
        print()

    # --- Missing check ---
    results = _scan_missing(game_path)
    if not results:
        if not drift and not nurse_broken:
            print(f"  {DIM}No city/town maps found.{RST}")
        input("\n  Press Enter > ")
        return

    actionable = _show_scan_results(results)

    print()
    if actionable:
        print(f"  {len(actionable)} map{'s' if len(actionable) != 1 else ''} "
              f"can be auto-configured.")
    elif all(r[2] for r in results):
        print(f"  {GREEN}All city/town maps have heal locations.{RST}")

    if not actionable:
        input(f"\n  Press Enter > ")
        return

    # --- Offer to add ---
    print()
    try:
        choice = input(f"  Add a heal location? (1-{len(actionable)}, "
                       f"a=all, Enter=skip) > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if not choice:
        return

    if choice == "a":
        targets = actionable
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(actionable):
                targets = [actionable[idx]]
            else:
                return
        except ValueError:
            return

    _add_from_scan(game_path, targets)


def _add_from_scan(game_path, folders):
    """Auto-build and write heal locations for the given map folders."""
    from torch.project_files import clear_project_cache
    clear_project_cache()
    locations = load_heal_locations(game_path) or []
    existing_ids = {loc.get("id") for loc in locations}
    added = 0

    for folder in folders:
        entry = _auto_add_heal(game_path, folder)
        if entry is None:
            print(f"  {RED}Could not auto-detect for {folder}.{RST}")
            continue
        if entry["id"] in existing_ids:
            print(f"  {DIM}{_heal_id_to_display(entry['id'])} already exists, skipping.{RST}")
            continue
        display = _heal_id_to_display(entry["id"])
        map_disp = _map_const_to_display(entry["map"])
        respawn_disp = _map_const_to_display(entry["respawn_map"])
        print()
        print(f"  {GOLD}{display}{RST}")
        print(f"    Heal tile: {map_disp} ({entry['x']}, {entry['y']})")
        print(f"    Respawn:   {respawn_disp}")
        locations.append(entry)
        existing_ids.add(entry["id"])
        added += 1

    if not added:
        print(f"\n  {DIM}Nothing to add.{RST}")
        input("  Press Enter > ")
        return

    print()
    try:
        confirm = input(f"  Add {added} heal location{'s' if added != 1 else ''}? "
                        f"[Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm not in ("", "y", "yes"):
        print(f"  {DIM}Cancelled.{RST}")
        input("  Press Enter > ")
        return

    if write_heal_locations(game_path, locations):
        print(f"\n  {GREEN}Added {added} heal location{'s' if added != 1 else ''}.{RST}")
    else:
        print(f"\n  {RED}Failed to write heal_locations.json.{RST}")
    input("  Press Enter > ")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def heal_command(args, game_path, project_dir, settings=None, proj_name=None):
    """Entry point for ``torch heal``."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if proj_name is None:
        proj_name = os.path.basename(project_dir) if project_dir else None
    _list_view(game_path, settings, proj_name)
