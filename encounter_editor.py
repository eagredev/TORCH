"""Encounter Editor — visual editor for wild_encounters.json.

``torch wild`` — browse maps, view encounter tables, edit species/levels/rates.
Supports classic and time-based encounters (expansion v1.12.0+).
"""
# TORCH_MODULE: Encounter Editor
# TORCH_GROUP: Editors
import os
import re
import copy

from torch.project_files import (
    load_wild_encounters, get_all_encounters, get_encounters_for_map,
    get_encounter_types, get_encounter_species, get_maps_with_encounters,
    write_encounters, extract_time_suffix, load_map_groups,
    get_field_rates, remove_encounters_for_map, classify_maps,
    _ENCOUNTER_TYPES, _TIME_SUFFIXES, clear_project_cache,
    folder_to_map_const,
)
from torch.list_widget import (
    ListState, handle_input, visible_range,
    overflow_above, overflow_below, marker, footer_hint, guard_bounds,
)
from torch.pickers import pick_species
from torch.expansion_compat import (
    detect_expansion_version, check_feature, TIME_BASED_ENCOUNTERS,
)
from torch.colours import GOLD, WHITE, CYAN, DIM, RED, GREEN, RST, BAR
from torch.ui import clear_screen, print_logo
from torch.config import _nav_keys, SETTINGS_DEFAULTS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TYPE_LABELS = {
    "land_mons":       "Land",
    "water_mons":      "Water",
    "fishing_mons":    "Fishing",
    "rock_smash_mons": "Rock Smash",
}

_TYPE_SLOT_COUNTS = {
    "land_mons": 12,
    "water_mons": 5,
    "rock_smash_mons": 5,
    "fishing_mons": 10,
}

_FALLBACK_RATES = {
    "land_mons":       [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1],
    "water_mons":      [60, 30, 5, 4, 1],
    "rock_smash_mons": [60, 30, 5, 4, 1],
    "fishing_mons":    [70, 30, 60, 20, 20, 40, 40, 15, 4, 1],
}
_DEFAULT_RATES = _FALLBACK_RATES  # backward compat for tests

_FISHING_GROUPS = {"old_rod": (0, 2), "good_rod": (2, 5), "super_rod": (5, 10)}

_DEFAULT_ENCOUNTER_RATE = 20

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _species_display(species):
    """Strip SPECIES_ prefix for display."""
    if species and species.startswith("SPECIES_"):
        return species[8:]
    return species or "NONE"


def _level_display(mn, mx):
    """Format level range."""
    if mn == mx:
        return str(mn)
    return f"{mn}-{mx}"


_folder_to_map_const = folder_to_map_const  # backward compat alias


def _map_display(map_const):
    """Convert map identifiers to display form.

    MAP_ROUTE_101 -> Route 101 (MAP_CONSTANT form)
    ROUTE_101     -> Route 101 (UPPER_SNAKE without MAP_ prefix)
    PetalburgCity -> Petalburg City (PascalCase form from map_groups.json)
    """
    name = map_const
    if name.startswith("MAP_"):
        name = name[4:]
        return name.replace("_", " ").title()
    # UPPER_SNAKE (all uppercase) — title-case it
    if name == name.upper() and "_" in name:
        return name.replace("_", " ").title()
    # PascalCase: insert spaces at lowercase->uppercase transitions
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return spaced.replace("_", " ")


def _base_label_from_map(map_const):
    """Auto-generate base_label: MAP_MY_TOWN -> gMyTown."""
    name = map_const
    if name.startswith("MAP_"):
        name = name[4:]
    parts = name.split("_")
    return "g" + "".join(p.capitalize() for p in parts)


def _empty_slot():
    """Return a blank encounter slot."""
    return {"min_level": 1, "max_level": 1, "species": "SPECIES_NONE"}


def _make_encounter_type(etype, field_rates=None):
    """Create a default encounter type block with empty slots."""
    if field_rates and etype in field_rates:
        count = len(field_rates[etype])
    else:
        count = _TYPE_SLOT_COUNTS.get(etype, 12)
    return {
        "encounter_rate": _DEFAULT_ENCOUNTER_RATE,
        "mons": [_empty_slot() for _ in range(count)],
    }


def _all_map_constants(game_path):
    """Gather all map constants from map_groups.json."""
    mg = load_map_groups(game_path)
    if not mg:
        return []
    maps = []
    for group_name in mg.get("group_order", []):
        for m in mg.get(group_name, []):
            if m not in maps:
                maps.append(m)
    return maps


def _find_encounter_group(data):
    """Return the first encounter group with for_maps=True, or None."""
    for g in data.get("wild_encounter_groups", []):
        if g.get("for_maps"):
            return g
    return None


def _find_entry_in_group(group, map_const):
    """Find the encounter entry for a map in a group. Returns (index, entry) or (-1, None)."""
    for i, entry in enumerate(group.get("encounters", [])):
        if entry.get("map") == map_const:
            return i, entry
    return -1, None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def encounter_command(args, project_dir, game_path, workspace_expanded,
                      settings, emotes_conf=None, source_display=None, proj_name=None):
    """Entry point for ``torch wild``."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)

    if not game_path or not os.path.isdir(game_path):
        print()
        print(f"  {RED}Error:{RST} Game path not found.")
        print(f"  {DIM}Run torch config to set up your project.{RST}")
        print()
        input("  Press Enter > ")
        return

    # Direct map access: torch wild Route101
    if args:
        map_name = args[0].upper()
        if not map_name.startswith("MAP_"):
            map_name = "MAP_" + map_name
        _map_editor(map_name, game_path, settings)
        return

    _map_picker(game_path, settings)


# ---------------------------------------------------------------------------
# Map picker
# ---------------------------------------------------------------------------


def _map_picker(game_path, settings):
    """Scrolling map picker — select a map to edit encounters."""
    nav = _nav_keys(settings)
    page_size = settings.get("map_list_page_size", 20)

    # Classify maps: default to custom-only if custom maps exist
    _vanilla, custom_maps = classify_maps(game_path)
    show_all = [not custom_maps]  # mutable; default to all if no custom maps

    while True:
        maps_with_enc = get_maps_with_encounters(game_path)
        all_maps = _all_map_constants(game_path)
        if not all_maps:
            all_maps = sorted(maps_with_enc)

        if show_all[0]:
            visible_maps = all_maps
        else:
            visible_maps = [m for m in all_maps if m in custom_maps]

        items = _build_map_list(visible_maps, maps_with_enc)
        if not items:
            clear_screen()
            print()
            print(f"  {DIM}No maps found. Check your project path.{RST}")
            print()
            input("  Press Enter > ")
            return

        state = ListState(len(items), page_size=page_size)
        result = _map_picker_loop(items, state, nav, game_path, settings,
                                  show_all, custom_maps)
        if result == "quit":
            return


def _build_map_list(all_maps, maps_with_enc):
    """Build sorted list of (map_const, has_encounters) tuples.

    Handles format mismatch: all_maps may be PascalCase (from map_groups.json)
    while maps_with_enc uses MAP_CONSTANT form (from wild_encounters.json).
    """
    # Build a normalized lookup set (all MAP_CONSTANT form)
    enc_upper = {m.upper() for m in maps_with_enc if m}
    items = []
    for m in all_maps:
        # Try direct match first, then convert PascalCase -> MAP_CONSTANT
        if m in maps_with_enc:
            has = True
        else:
            const = folder_to_map_const(m) if not m.startswith("MAP_") else m
            has = const.upper() in enc_upper
        items.append((m, has))
    # Sort: maps with encounters first, then alphabetical
    items.sort(key=lambda x: (not x[1], x[0]))
    return items


def _has_filter(show_all, custom_maps):
    """Return True if the map picker has an active filter toggle."""
    return show_all is not None and bool(custom_maps)


def _render_picker_header(items, show_all, custom_maps):
    """Render the encounter editor header and filter indicator."""
    print()
    print(BAR)
    print(f"   {WHITE}ENCOUNTER EDITOR{RST}  {DIM}(wild_encounters.json){RST}")
    print(BAR)
    print()
    if _has_filter(show_all, custom_maps):
        label = "Showing all maps" if show_all[0] else "Custom maps only"
        print(f"  {DIM}{label} ({len(items)}){RST}")
        print()


def _picker_footer_extra(show_all, custom_maps):
    """Build the extra footer hints for the map picker."""
    extra = "  [n] new"
    if _has_filter(show_all, custom_maps):
        toggle = "custom only" if show_all[0] else "show all"
        extra += f"  [a] {DIM}{toggle}{RST}"
    return extra


def _map_picker_loop(items, state, nav, game_path, settings,
                     show_all=None, custom_maps=None):
    """Inner loop for the map picker. Returns 'quit' or 'refresh'."""
    while True:
        state.total = len(items)
        guard_bounds(state)

        clear_screen()
        _render_picker_header(items, show_all, custom_maps)
        _render_map_list(items, state)

        hint = footer_hint(nav, _picker_footer_extra(show_all, custom_maps))
        print(hint)
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").rstrip("\n")
        except (EOFError, KeyboardInterrupt):
            return "quit"

        action = handle_input(state, raw, nav)

        if action == "quit":
            return "quit"
        if action in ("open", "jump_act"):
            if state.total > 0:
                map_name = items[state.selected][0]
                map_const = folder_to_map_const(map_name) if not map_name.startswith("MAP_") else map_name
                _map_editor(map_const, game_path, settings)
                return "refresh"
        if action in ("scroll", "up", "down", "jump"):
            continue

        cmd = raw.strip().lower()
        if cmd == "n":
            _add_new_map(game_path, settings)
            return "refresh"
        if cmd == "a" and _has_filter(show_all, custom_maps):
            show_all[0] = not show_all[0]
            return "refresh"
        if cmd == "f":
            _map_search(items, state)


def _render_map_list(items, state):
    """Render the map list with encounter indicators."""
    above = overflow_above(state)
    if above:
        print(above)

    start, end = visible_range(state)
    num_w = len(str(len(items)))

    for i in range(start, end):
        map_const, has_enc = items[i]
        mk = marker(state, i)
        row_num = f"{i + 1}."
        name = _map_display(map_const)

        if has_enc:
            tag = f"{GREEN}*{RST}"
        else:
            tag = f"{DIM}-{RST}"

        print(f"  {mk} {row_num:<{num_w + 1}}  {tag} {name}")

    below = overflow_below(state)
    if below:
        print(below)
    print()


def _map_search(items, state):
    """Quick search filter — jump to first matching map."""
    try:
        q = input(f"  {DIM}Search:{RST} ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        return
    if not q:
        return
    for i, (map_const, _) in enumerate(items):
        if q in map_const:
            state.selected = i
            guard_bounds(state)
            return


# ---------------------------------------------------------------------------
# Map editor — encounter table view
# ---------------------------------------------------------------------------


def _load_editor_state(map_const, game_path):
    """Load and validate data for the map editor.

    Returns (data, group, field_rates, entry) or None on error.
    """
    data = load_wild_encounters(game_path)
    if not data:
        print(f"  {RED}Error:{RST} Could not load wild_encounters.json")
        input("  Press Enter > ")
        return None

    group = _find_encounter_group(data)
    if not group:
        print(f"  {RED}Error:{RST} No map encounter group found in data.")
        input("  Press Enter > ")
        return None

    field_rates = get_field_rates(game_path)

    idx, entry = _find_entry_in_group(group, map_const)
    if idx < 0:
        yn = input(f"  {_map_display(map_const)} has no encounters. Create? [Y/n] > ").strip().lower()
        if yn not in ("", "y", "yes"):
            return None
        entry = _create_entry(map_const, field_rates)
        group.setdefault("encounters", []).append(entry)

    return data, group, field_rates, entry


def _map_editor(map_const, game_path, settings):
    """Edit encounters for a single map.

    Returns True if the map's encounters were deleted (caller should
    refresh the map picker), False/None otherwise.
    """
    state = _load_editor_state(map_const, game_path)
    if not state:
        return False

    data, group, field_rates, entry = state
    dirty = [False]  # mutable flag for nested functions
    has_time = check_feature(game_path, TIME_BASED_ENCOUNTERS)
    active_tab = _first_encounter_type(entry)
    nav = _nav_keys(settings)
    slot_state = ListState(0)  # slot cursor; total set each frame

    while True:
        clear_screen()
        etypes = get_encounter_types(entry)
        if not active_tab or active_tab not in etypes:
            active_tab = etypes[0] if etypes else None

        # Update slot_state.total for active tab
        mons = entry.get(active_tab, {}).get("mons", []) if active_tab else []
        slot_state.total = len(mons)
        guard_bounds(slot_state)

        _render_table_header(map_const, entry, etypes, active_tab, has_time)

        if active_tab:
            _render_slots(entry, active_tab, field_rates, slot_state)

        _render_table_footer(has_time, nav)
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").rstrip("\n").strip()
        except (EOFError, KeyboardInterrupt):
            raw = "q"

        if raw.lower() == "q":
            if dirty[0]:
                _save_and_exit(data, game_path)
            return False

        if raw.lower() == "x":
            if _delete_all_encounters(map_const, game_path, dirty):
                return True
            continue

        result = _handle_table_input(raw, entry, active_tab, etypes, dirty,
                                     game_path, has_time, data, map_const,
                                     group, field_rates, nav, slot_state)
        if result and result in etypes and result != active_tab:
            active_tab = result
            slot_state.selected = 0  # reset cursor on tab switch


def _first_encounter_type(entry):
    """Return the first encounter type key present, or None."""
    etypes = get_encounter_types(entry)
    return etypes[0] if etypes else None


def _create_entry(map_const, field_rates=None):
    """Create a new encounter entry with land_mons as default."""
    return {
        "map": map_const,
        "base_label": _base_label_from_map(map_const),
        "land_mons": _make_encounter_type("land_mons", field_rates),
    }


def _handle_slot_nav(cmd, slot_state, nav):
    """Handle cursor navigation keys for the slot list.

    Returns True if the key was a navigation action, False otherwise.
    """
    if not slot_state or slot_state.total <= 0:
        return False
    _, up_key, down_key, _ = nav
    if cmd == up_key or cmd == "k":
        slot_state.selected = max(0, slot_state.selected - 1)
        guard_bounds(slot_state)
        return True
    if cmd == down_key:
        slot_state.selected = min(slot_state.total - 1, slot_state.selected + 1)
        guard_bounds(slot_state)
        return True
    if cmd == "":  # Enter
        slot_state.selected = (slot_state.selected + 1) % slot_state.total
        guard_bounds(slot_state)
        return True
    return False


def _handle_slot_edit(cmd, entry, active_tab, game_path, dirty,
                      slot_state, open_key):
    """Handle slot edit/clear commands. Returns True if handled."""
    if not active_tab:
        return False

    # v / open_key = edit highlighted slot
    if cmd == open_key and slot_state:
        if _edit_slot(entry, active_tab, slot_state.selected + 1, game_path):
            dirty[0] = True
        return True

    # Bare number = edit that slot directly
    if cmd.isdigit():
        slot_num = int(cmd)
        mons = entry.get(active_tab, {}).get("mons", [])
        if 1 <= slot_num <= len(mons):
            if _edit_slot(entry, active_tab, slot_num, game_path):
                dirty[0] = True
        return True

    # d alone = clear highlighted; d# = clear specific
    if cmd.startswith("d"):
        _handle_slot_command(cmd, entry, active_tab, game_path, dirty,
                             slot_state)
        return True

    return False


def _handle_table_input(raw, entry, active_tab, etypes, dirty,
                         game_path, has_time, data, map_const, group,
                         field_rates=None, nav=None, slot_state=None):
    """Dispatch a single input in the encounter table view.

    Returns the new active tab key when a tab switch is requested,
    or None for all other actions.
    """
    if nav is None:
        nav = ("p", "u", "j", "v")
    _, _, _, open_key = nav
    cmd = raw.lower()

    # Navigation: u/k = up, j = down, Enter = scroll (wrap)
    if _handle_slot_nav(cmd, slot_state, nav):
        return None

    # n = cycle to next encounter type tab
    if cmd == "n" and etypes:
        idx = etypes.index(active_tab) if active_tab in etypes else -1
        return etypes[(idx + 1) % len(etypes)]

    # Slot edit/clear commands
    if _handle_slot_edit(cmd, entry, active_tab, game_path, dirty,
                         slot_state, open_key):
        return None

    # Simple commands
    if cmd == "r" and active_tab:
        if _edit_encounter_rate(entry, active_tab):
            dirty[0] = True
    elif cmd == "a":
        if _add_encounter_type(entry, etypes, field_rates):
            dirty[0] = True
    elif cmd == "t" and has_time:
        _time_of_day_menu(entry, data, map_const, group, game_path, dirty)
    return None


def _handle_slot_command(cmd, entry, active_tab, game_path, dirty,
                         slot_state=None):
    """Handle d (clear highlighted) and d# (clear specific) slot commands."""
    if not active_tab:
        return

    if cmd == "d" and slot_state and slot_state.total > 0:
        if _clear_slot(entry, active_tab, slot_state.selected + 1):
            dirty[0] = True
        return

    if cmd.startswith("d") and cmd[1:].isdigit():
        if _clear_slot(entry, active_tab, int(cmd[1:])):
            dirty[0] = True


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_table_header(map_const, entry, etypes, active_tab, has_time):
    """Render the tab bar and map title."""
    name = _map_display(map_const)
    print()
    print(BAR)
    print(f"   {WHITE}{name}{RST}")
    print(BAR)
    print()

    # Tab bar
    tabs = []
    for i, et in enumerate(etypes):
        label = _TYPE_LABELS.get(et, et)
        mons = entry.get(et, {}).get("mons", [])
        count = len(mons)
        if et == active_tab:
            tabs.append(f" {WHITE}[{i + 1}] {label} ({count}){RST} ")
        else:
            tabs.append(f" {DIM}[{i + 1}] {label} ({count}){RST} ")
    print("  " + " ".join(tabs))
    print()


def _render_slots(entry, etype, field_rates=None, slot_state=None):
    """Render the slot table for an encounter type."""
    block = entry.get(etype, {})
    mons = block.get("mons", [])
    rate = block.get("encounter_rate", 0)
    rates = _resolve_rates(etype, field_rates)

    label = _TYPE_LABELS.get(etype, etype)
    print(f"  {CYAN}{label} Encounters{RST} {DIM}(rate: {rate}){RST}")
    print(f"  {DIM}{'─' * 50}{RST}")

    # Header
    print(f"  {DIM}     #  {'Species':<20} {'Lv':<6} {'Rate':>5}{RST}")

    if etype == "fishing_mons":
        _render_fishing_slots(mons, rates, slot_state)
    else:
        _render_plain_slots(mons, rates, slot_state)

    print(f"  {DIM}{'─' * 50}{RST}")

    # Rate sum check — fishing rates are per rod group, not global
    if etype == "fishing_mons":
        for rod_name, (start, end) in _FISHING_GROUPS.items():
            group_total = sum(_get_slot_rate(rates, i)
                              for i in range(start, min(end, len(mons))))
            if group_total != 100 and group_total > 0:
                rod_label = rod_name.replace("_", " ").title()
                print(f"  {GOLD}{rod_label} rate total: {group_total}%"
                      f" (expected 100%){RST}")
    else:
        total_rate = sum(_get_slot_rate(rates, i) for i in range(len(mons)))
        if total_rate != 100 and total_rate > 0:
            print(f"  {GOLD}Rate total: {total_rate}% (expected 100%){RST}")


def _render_plain_slots(mons, rates, slot_state=None):
    """Render non-fishing slots."""
    for i, slot in enumerate(mons):
        _print_slot_row(i, slot, rates, slot_state)


def _render_fishing_slots(mons, rates, slot_state=None):
    """Render fishing slots with rod sub-headers."""
    for rod_name, (start, end) in _FISHING_GROUPS.items():
        rod_label = rod_name.replace("_", " ").title()
        print(f"  {DIM}--- {rod_label} ---{RST}")
        for i in range(start, min(end, len(mons))):
            _print_slot_row(i, mons[i], rates, slot_state)


def _print_slot_row(index, slot, rates, slot_state=None):
    """Print a single encounter slot row."""
    species = slot.get("species", "SPECIES_NONE")
    mn = slot.get("min_level", 0)
    mx = slot.get("max_level", 0)
    rate = _get_slot_rate(rates, index)

    display = _species_display(species)
    lvl = _level_display(mn, mx)

    if species == "SPECIES_NONE" or not species:
        color = DIM
    else:
        color = ""

    mk = marker(slot_state, index) if slot_state else "  "
    num = f"{index + 1:>2}"
    print(f"  {mk}{color} {num}  {display:<20} {lvl:<6} {rate:>4}%{RST}")


def _resolve_rates(etype, field_rates):
    """Get the rate list for an encounter type, preferring field rates."""
    if field_rates and etype in field_rates:
        return field_rates[etype]
    return _FALLBACK_RATES.get(etype, [])


def _get_slot_rate(rates, index):
    """Look up the encounter rate percentage for a slot index."""
    if index < len(rates):
        return rates[index]
    return 0


def _slot_rate(mons, index):
    """Legacy lookup by slot count — backward compat for tests."""
    count = len(mons)
    for _etype, rates in _FALLBACK_RATES.items():
        if len(rates) == count:
            if index < len(rates):
                return rates[index]
            break
    return 0


def _render_table_footer(has_time, nav=None):
    """Render the command bar."""
    if nav is None:
        nav = ("p", "u", "j", "v")
    _, up_key, down_key, open_key = nav
    print()
    parts = [
        f"  [#] {DIM}edit slot{RST}",
        f"  [{open_key}] {DIM}edit{RST}",
        f"  [n] {DIM}next type{RST}",
        f"  [r] {DIM}rate{RST}",
        f"  [a] {DIM}add type{RST}",
    ]
    parts2 = [
        f"  [d] {DIM}clear slot{RST}",
        f"  [d]# {DIM}clear #{RST}",
    ]
    if has_time:
        parts2.append(f"  [t] {DIM}time{RST}")
    parts2.append(f"  [x] {DIM}delete map{RST}")
    parts2.append(f"  [q] {DIM}back{RST}")

    print("".join(parts))
    print("".join(parts2))
    print(f"  {DIM}[{up_key}]p  [{down_key}] down  Enter scroll{RST}")


# ---------------------------------------------------------------------------
# Slot editing
# ---------------------------------------------------------------------------


def _edit_slot(entry, etype, slot_num, game_path):
    """Edit a single encounter slot. Returns True if changed."""
    block = entry.get(etype, {})
    mons = block.get("mons", [])

    idx = slot_num - 1
    if idx < 0 or idx >= len(mons):
        print(f"  {RED}Invalid slot number.{RST} Range: 1-{len(mons)}")
        input("  Press Enter > ")
        return False

    slot = mons[idx]
    current = _species_display(slot.get("species", "SPECIES_NONE"))
    print()
    print(f"  {DIM}Editing slot {slot_num} (currently: {current}){RST}")

    # Species
    print()
    species = pick_species(game_path)
    if species is None:
        print(f"  {DIM}Cancelled.{RST}")
        input("  Press Enter > ")
        return False

    # Min level
    cur_min = slot.get("min_level", 1)
    mn = _prompt_int(f"  Min level [{cur_min}] > ", cur_min, 1, 100)
    if mn is None:
        return False

    # Max level
    cur_max = slot.get("max_level", mn)
    if cur_max < mn:
        cur_max = mn
    mx = _prompt_int(f"  Max level [{cur_max}] > ", cur_max, mn, 100)
    if mx is None:
        return False

    slot["species"] = species
    slot["min_level"] = mn
    slot["max_level"] = mx
    print(f"  {GREEN}Updated slot {slot_num}: {_species_display(species)} Lv{_level_display(mn, mx)}{RST}")
    input("  Press Enter > ")
    return True


def _clear_slot(entry, etype, slot_num):
    """Clear a slot to SPECIES_NONE. Returns True if changed."""
    block = entry.get(etype, {})
    mons = block.get("mons", [])

    idx = slot_num - 1
    if idx < 0 or idx >= len(mons):
        print(f"  {RED}Invalid slot number.{RST} Range: 1-{len(mons)}")
        input("  Press Enter > ")
        return False

    current = _species_display(mons[idx].get("species", "SPECIES_NONE"))
    if current == "NONE":
        print(f"  {DIM}Slot {slot_num} is already empty.{RST}")
        input("  Press Enter > ")
        return False

    yn = input(f"  Clear slot {slot_num} ({current})? [y/N] > ").strip().lower()
    if yn not in ("y", "yes"):
        return False

    mons[idx]["species"] = "SPECIES_NONE"
    mons[idx]["min_level"] = 0
    mons[idx]["max_level"] = 0
    print(f"  {DIM}Slot {slot_num} cleared.{RST}")
    return True


def _edit_encounter_rate(entry, etype):
    """Edit the encounter_rate for an encounter type. Returns True if changed."""
    block = entry.get(etype, {})
    current = block.get("encounter_rate", _DEFAULT_ENCOUNTER_RATE)

    label = _TYPE_LABELS.get(etype, etype)
    print()
    print(f"  {DIM}{label} encounter rate (controls how often encounters trigger){RST}")
    new_rate = _prompt_int(f"  Encounter rate [{current}] > ", current, 1, 255)
    if new_rate is None:
        return False

    block["encounter_rate"] = new_rate
    print(f"  {GREEN}Encounter rate set to {new_rate}.{RST}")
    return True


# ---------------------------------------------------------------------------
# Add / remove encounter type
# ---------------------------------------------------------------------------


def _add_encounter_type(entry, current_types, field_rates=None):
    """Add a missing encounter type to the entry. Returns True if added."""
    missing = [et for et in _ENCOUNTER_TYPES if et not in current_types]
    if not missing:
        print(f"  {DIM}All encounter types are already present.{RST}")
        input("  Press Enter > ")
        return False

    print()
    print(f"  {WHITE}Add encounter type:{RST}")
    for i, et in enumerate(missing):
        label = _TYPE_LABELS.get(et, et)
        if field_rates and et in field_rates:
            count = len(field_rates[et])
        else:
            count = _TYPE_SLOT_COUNTS.get(et, 0)
        print(f"  [{i + 1}] {label} ({count} slots)")
    print(f"  [q] Cancel")
    print()

    try:
        choice = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if choice == "q" or not choice.isdigit():
        return False

    idx = int(choice) - 1
    if idx < 0 or idx >= len(missing):
        print(f"  {RED}Invalid choice.{RST}")
        return False

    etype = missing[idx]
    entry[etype] = _make_encounter_type(etype, field_rates)
    label = _TYPE_LABELS.get(etype, etype)
    print(f"  {GREEN}Added {label} encounters.{RST}")
    input("  Press Enter > ")
    return True


# ---------------------------------------------------------------------------
# Time-of-day
# ---------------------------------------------------------------------------


def _time_of_day_menu(entry, data, map_const, group, game_path, dirty):
    """Manage time-of-day encounter variants."""
    encounters = group.get("encounters", [])
    base = entry.get("base_label", "")

    # Find existing time entries
    existing = {}
    for e in encounters:
        suffix = extract_time_suffix(e.get("base_label", ""))
        if suffix and e.get("map") == map_const:
            existing[suffix] = e

    print()
    print(f"  {WHITE}Time-of-Day Encounters{RST}")
    print(f"  {DIM}Base: {base}{RST}")
    print()

    for suffix in _TIME_SUFFIXES:
        if suffix in existing:
            print(f"  {GREEN}*{RST} {suffix}")
        else:
            print(f"  {DIM}-{RST} {suffix}")
    print()

    print(f"  [c] Copy current to a time slot")
    print(f"  [d] Delete a time slot")
    print(f"  [q] Back")
    print()

    try:
        choice = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if choice == "c":
        _copy_to_time_slot(entry, map_const, group, existing, dirty)
    elif choice == "d":
        _delete_time_slot(map_const, group, existing, dirty)


def _copy_to_time_slot(entry, map_const, group, existing, dirty):
    """Copy current encounters to a time-of-day variant."""
    available = [s for s in _TIME_SUFFIXES if s not in existing]
    if not available:
        print(f"  {DIM}All time slots are filled.{RST}")
        input("  Press Enter > ")
        return

    print()
    for i, s in enumerate(available):
        print(f"  [{i + 1}] {s}")
    print()

    try:
        choice = input(f"  {GOLD}Copy to:{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if not choice.isdigit():
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(available):
        return

    suffix = available[idx]
    new_entry = copy.deepcopy(entry)
    new_entry["base_label"] = entry.get("base_label", "") + "_" + suffix
    group.setdefault("encounters", []).append(new_entry)
    dirty[0] = True
    print(f"  {GREEN}Copied encounters to {suffix} slot.{RST}")
    input("  Press Enter > ")


def _delete_time_slot(map_const, group, existing, dirty):
    """Delete a time-of-day variant."""
    if not existing:
        print(f"  {DIM}No time slots to delete.{RST}")
        input("  Press Enter > ")
        return

    keys = list(existing.keys())
    print()
    for i, s in enumerate(keys):
        print(f"  [{i + 1}] {s}")
    print()

    try:
        choice = input(f"  {GOLD}Delete:{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if not choice.isdigit():
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(keys):
        return

    suffix = keys[idx]
    target = existing[suffix]
    yn = input(f"  Delete {suffix} encounters? [y/N] > ").strip().lower()
    if yn not in ("y", "yes"):
        return

    encounters = group.get("encounters", [])
    if target in encounters:
        encounters.remove(target)
        dirty[0] = True
        print(f"  {GREEN}Deleted {suffix} slot.{RST}")
    input("  Press Enter > ")


# ---------------------------------------------------------------------------
# Add encounters to new map
# ---------------------------------------------------------------------------


def _add_new_map(game_path, settings):
    """Wizard to add encounters to a map that has none."""
    print()
    print(f"  {WHITE}Add Encounters to Map{RST}")
    print()

    try:
        map_const = input(f"  Map constant (e.g. MAP_MY_TOWN) > ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        return

    if not map_const:
        return
    if not map_const.startswith("MAP_"):
        map_const = "MAP_" + map_const

    # Check if already has encounters
    existing = get_maps_with_encounters(game_path)
    if map_const in existing:
        print(f"  {DIM}{map_const} already has encounters. Opening editor...{RST}")
        input("  Press Enter > ")
        _map_editor(map_const, game_path, settings)
        return

    base_label = _base_label_from_map(map_const)
    print(f"  {DIM}Base label: {base_label}{RST}")
    print()

    # Choose encounter types
    etypes = _pick_encounter_types()
    if not etypes:
        return

    # Build the entry
    field_rates = get_field_rates(game_path)
    entry = {"map": map_const, "base_label": base_label}
    for et in etypes:
        entry[et] = _make_encounter_type(et, field_rates)

    # Add to data
    data = load_wild_encounters(game_path)
    if not data:
        print(f"  {RED}Error:{RST} Could not load wild_encounters.json")
        input("  Press Enter > ")
        return

    group = _find_encounter_group(data)
    if not group:
        print(f"  {RED}Error:{RST} No map encounter group found.")
        input("  Press Enter > ")
        return

    group.setdefault("encounters", []).append(entry)

    if write_encounters(game_path, data):
        print(f"  {GREEN}Created encounters for {_map_display(map_const)}.{RST}")
        _offer_build_prompt(game_path)
    else:
        print(f"  {RED}Error writing encounters.{RST}")
    input("  Press Enter > ")


def _pick_encounter_types():
    """Multi-select encounter types. Returns list of selected type keys."""
    print(f"  {WHITE}Select encounter types:{RST}")
    for i, et in enumerate(_ENCOUNTER_TYPES):
        label = _TYPE_LABELS.get(et, et)
        count = _TYPE_SLOT_COUNTS.get(et, 0)
        print(f"  [{i + 1}] {label} ({count} slots)")
    print()
    print(f"  {DIM}Enter numbers separated by spaces (e.g. 1 3), or 'a' for all{RST}")
    print()

    try:
        raw = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return []

    if not raw:
        return []
    if raw == "a":
        return list(_ENCOUNTER_TYPES)

    selected = []
    for token in raw.split():
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(_ENCOUNTER_TYPES):
                et = _ENCOUNTER_TYPES[idx]
                if et not in selected:
                    selected.append(et)
    return selected


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def _save_and_exit(data, game_path):
    """Prompt to save dirty data before exiting the table view."""
    print()
    yn = input(f"  Save changes? [Y/n] > ").strip().lower()
    if yn not in ("", "y", "yes"):
        print(f"  {DIM}Changes discarded.{RST}")
        input("  Press Enter > ")
        return

    if write_encounters(game_path, data):
        print(f"  {GREEN}Saved.{RST}")
        _offer_build_prompt(game_path)
    else:
        print(f"  {RED}Error saving encounters.{RST}")
    input("  Press Enter > ")


def _delete_all_encounters(map_const, game_path, dirty):
    """Prompt to remove all encounters for a map. Returns True if deleted."""
    name = _map_display(map_const)
    print()
    try:
        yn = input(
            f"  Remove ALL encounters for {name}? "
            f"This clears all encounter types. [y/N] > "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if yn not in ("y", "yes"):
        return False

    removed = remove_encounters_for_map(game_path, map_const)
    if removed > 0:
        dirty[0] = True
        print(f"  {GREEN}Removed {removed} encounter entry(s) for {name}.{RST}")
        _offer_build_prompt(game_path)
    else:
        print(f"  {DIM}No encounters found to remove.{RST}")
    input("  Press Enter > ")
    return removed > 0


def _offer_build_prompt(game_path):
    """Simple build offer after encounter changes."""
    from torch.ui import _offer_build
    _offer_build(game_path=game_path, trigger="encounter_editor")


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def _prompt_int(prompt, default, lo, hi):
    """Prompt for an integer with a default. Returns int or None on cancel."""
    try:
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        print(f"  {RED}Not a number.{RST}")
        return None
    if val < lo or val > hi:
        print(f"  {RED}Must be {lo}-{hi}.{RST}")
        return None
    return val
