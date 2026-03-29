"""Dex — read-only species data browser for TORCH.

Provides an interactive terminal browser for Pokemon species data including
base stats, types, abilities, learnsets, and evolution chains.
Invoked via ``torch dex`` or main menu option [8].
"""
# TORCH_MODULE: Dex
# TORCH_GROUP: Data
import os
import sys
import textwrap

from torch.colours import GOLD, WHITE, CYAN, DIM, RST, BAR
from torch.ui import _k, clear_screen
from torch.config import _nav_keys
from torch.gamedata import (
    load_species, load_species_data, load_move_names, load_ability_names,
    load_level_up_learnset, load_teachable_learnset, load_egg_moves,
    load_form_tables,
)
from torch.list_widget import (
    ListState, guard_bounds, visible_range, handle_input, marker,
    overflow_above, overflow_below, footer_hint,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STAT_BAR_WIDTH = 20
_STAT_MAX = 255
_STAT_LABELS = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")
_STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")
_EV_LABELS = {"hp": "HP", "atk": "Atk", "def": "Def",
              "spa": "SpA", "spd": "SpD", "spe": "Spe"}

_EVO_METHOD_LABELS = {
    "LEVEL": "Lv.",
    "ITEM": "",
    "TRADE": "Trade",
    "TRADE_ITEM": "Trade w/",
    "FRIENDSHIP": "Friendship",
    "FRIENDSHIP_DAY": "Friendship (Day)",
    "FRIENDSHIP_NIGHT": "Friendship (Night)",
    "LEVEL_ATK_GT_DEF": "Lv. (Atk>Def)",
    "LEVEL_ATK_EQ_DEF": "Lv. (Atk=Def)",
    "LEVEL_ATK_LT_DEF": "Lv. (Atk<Def)",
    "LEVEL_SILCOON": "Lv. (Silcoon)",
    "LEVEL_CASCOON": "Lv. (Cascoon)",
    "LEVEL_NINJASK": "Lv. (Ninjask)",
    "LEVEL_SHEDINJA": "Lv. (Shedinja)",
    "BEAUTY": "Beauty",
    "MOVE": "Know",
    "MOVE_TYPE": "Know type",
    "SPECIFIC_MON_IN_PARTY": "w/ party",
    "LEVEL_RAIN": "Lv. (Rain)",
    "LEVEL_DARK_TYPE_MON_IN_PARTY": "Lv. (Dark party)",
    "LEVEL_DAY": "Lv. (Day)",
    "LEVEL_NIGHT": "Lv. (Night)",
    "LEVEL_FEMALE": "Lv. (Female)",
    "LEVEL_MALE": "Lv. (Male)",
    "USE_ITEM": "",
    "USE_ITEM_MALE": " (Male)",
    "USE_ITEM_FEMALE": " (Female)",
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def show_species_card(species_const, game_path, settings=None):
    """Show the species card for a given SPECIES_ constant.

    Loads all required data internally (gamedata caches make this efficient).
    Renders the card view and waits for [q] to return.

    Args:
        species_const: str — e.g. "SPECIES_PIKACHU"
        game_path: str — path to the game project
        settings: dict — optional settings (for nav keys); defaults to {}

    Returns:
        None — displays card and returns when user presses q
    """
    if settings is None:
        settings = {}
    if not game_path or not species_const:
        return
    try:
        species_data = load_species_data(game_path)
        if not species_data:
            print(f"\n  {GOLD}Could not load species data.{RST}\n")
            return
        entry = species_data.get(species_const)
        if entry is None:
            print(f"\n  {DIM}Species '{species_const}' not found in data.{RST}\n")
            return
        species_order = _build_species_order(game_path, species_data)
        move_names = load_move_names(game_path)
        ability_names = load_ability_names(game_path)
        form_tables = load_form_tables(game_path)
        form_consts = form_tables.get(species_const, [species_const])
        _card_view(species_const, entry, game_path, move_names,
                   ability_names, species_order, species_data,
                   form_tables, form_consts, settings)
    except Exception as exc:
        print(f"\n  {GOLD}Error showing species card: {exc}{RST}\n")


def dex_command(args, project_dir, game_path, workspace_expanded,
                    settings, emotes_conf=None, source_display=None,
                    proj_name=None):
    """Entry point for ``torch dex`` and menu option [8]."""
    if settings is None:
        settings = {}
    if not game_path:
        print(f"\n  {GOLD}No game path configured.{RST}")
        print("  Run 'torch config' to set up a project first.\n")
        return

    # Load all species data up front
    species_data = load_species_data(game_path)
    if not species_data:
        print(f"\n  {GOLD}No species data found.{RST}")
        print("  Make sure the game path points to a pokeemerald-expansion project.\n")
        return

    # Build ordered species list from species.h
    species_order = _build_species_order(game_path, species_data)
    move_names = load_move_names(game_path)
    ability_names = load_ability_names(game_path)

    # Load form tables for folding
    form_tables = load_form_tables(game_path)

    # Build the folded display list
    folded = _build_folded_list(species_order, form_tables)

    # Direct lookup: torch dex bulbasaur
    if args:
        query = " ".join(args).strip()
        target = _find_species_by_name(species_order, query)
        if target:
            const, data = target
            # Look up form group
            form_consts = form_tables.get(const, [const])
            _card_view(const, data, game_path, move_names,
                       ability_names, species_order, species_data,
                       form_tables, form_consts, settings)
        else:
            print(f"\n  No species matching '{query}' found.\n")
        return

    # Interactive browser
    _species_browser(folded, species_order, species_data, game_path,
                     move_names, ability_names, form_tables, settings)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _build_species_order(game_path, species_data):
    """Build ordered list of (SPECIES_CONST, data_dict) from species.h order.

    Only includes species that have data in species_data.
    Filters out SPECIES_NONE, SPECIES_EGG, and meta-constants.
    """
    raw = load_species(game_path)
    skip = {"SPECIES_NONE", "SPECIES_EGG", "SPECIES_UNOWN_B",
            "SPECIES_NUM", "SPECIES_COUNT"}

    result = []
    for const, _comment in raw:
        if const in skip:
            continue
        if const in species_data:
            result.append((const, species_data[const]))
    return result


def _species_display_name(const, data):
    """Return the display name for a species."""
    if data and data.get("name"):
        return data["name"]
    # Fallback: strip SPECIES_ prefix
    return const[8:].replace("_", " ").title() if const.startswith("SPECIES_") else const


def _form_label(const, base_const):
    """Extract a human-readable form label from a SPECIES_ constant.

    Given base_const ``SPECIES_CHARIZARD`` and const ``SPECIES_CHARIZARD_MEGA_X``,
    returns ``"Mega X"``.  For the base form (const == base_const) returns the
    base display name.
    """
    if const == base_const:
        return ""
    # Strip the SPECIES_ prefix from both, then strip base name portion
    if const.startswith("SPECIES_") and base_const.startswith("SPECIES_"):
        base_stem = base_const[8:]  # e.g. "CHARIZARD"
        full_stem = const[8:]       # e.g. "CHARIZARD_MEGA_X"
        if full_stem.startswith(base_stem + "_"):
            suffix = full_stem[len(base_stem) + 1:]  # e.g. "MEGA_X"
            return suffix.replace("_", " ").title()
        # No common prefix — just show the full stem
        return full_stem.replace("_", " ").title()
    return const


def _build_folded_list(species_order, form_tables):
    """Build a folded species list grouped by nat_dex_num.

    Returns list of (base_const, base_data, form_consts) tuples sorted by
    nat_dex_num.  Species with nat_dex_num 0 or None go at the end, sorted
    by constant name.
    """
    # Group by nat_dex_num
    groups = {}       # dex_num -> (base_const, base_data, form_consts)
    seen_consts = set()
    no_dex = []       # species with dex_num 0 or None

    for const, data in species_order:
        if const in seen_consts:
            continue
        dex_num = data.get("nat_dex_num") or 0
        form_group = form_tables.get(const)
        if form_group:
            # Use form table to determine group membership
            base_const = form_group[0]
            # Mark all members as seen
            for fc in form_group:
                seen_consts.add(fc)
            # Ensure we use the base form's data
            base_data = None
            for c, d in species_order:
                if c == base_const:
                    base_data = d
                    break
            if base_data is None:
                base_data = data
            form_consts = list(form_group)
        else:
            base_const = const
            base_data = data
            form_consts = [const]
            seen_consts.add(const)

        base_dex = base_data.get("nat_dex_num") or 0
        if base_dex == 0:
            no_dex.append((base_const, base_data, form_consts))
        elif base_dex not in groups:
            groups[base_dex] = (base_const, base_data, form_consts)

    # Sort numbered entries by dex number
    numbered = sorted(groups.items(), key=lambda kv: kv[0])
    result = [(bc, bd, fc) for _, (bc, bd, fc) in numbered]

    # Append no-dex entries sorted by constant name
    no_dex.sort(key=lambda t: t[0])
    result.extend(no_dex)

    return result


def _find_species_by_name(species_order, query):
    """Find a species by name query. Returns (const, data) or None."""
    q = query.lower().replace(" ", "")
    # Exact match first
    for const, data in species_order:
        name = _species_display_name(const, data).lower().replace(" ", "")
        if name == q:
            return (const, data)
    # Substring match
    for const, data in species_order:
        name = _species_display_name(const, data).lower().replace(" ", "")
        if q in name:
            return (const, data)
    # Try constant match
    q_const = "SPECIES_" + query.upper().replace(" ", "_")
    for const, data in species_order:
        if const == q_const:
            return (const, data)
    return None


# ---------------------------------------------------------------------------
# Filter / search  (operates on folded 3-tuples)
# ---------------------------------------------------------------------------


def _filter_species(items, query):
    """Filter a species list by query string.

    items: [(base_const, base_data, form_consts), ...]
           OR legacy [(const, data), ...] format (auto-detected).
    query: user search string

    Supported prefixes:
      type:fire, type:fire/dragon
      ability:intimidate
      bst>500, bst<400, bst=600
      egg:dragon
    Default: name substring match.

    Returns filtered list in the same tuple format as input.
    """
    q = query.strip()
    if not q:
        return items

    lower = q.lower()

    if lower.startswith("type:"):
        return _filter_by_type(items, lower[5:])
    if lower.startswith("ability:"):
        return _filter_by_ability(items, lower[8:])
    if lower.startswith("egg:"):
        return _filter_by_egg_group(items, lower[4:])
    if _is_bst_filter(lower):
        return _filter_by_bst(items, lower)

    # Default: name search
    return _filter_by_name(items, lower)


def _unpack_item(item):
    """Unpack a list item regardless of 2-tuple or 3-tuple format."""
    if len(item) == 3:
        return item[0], item[1]
    return item[0], item[1]


def _filter_by_name(items, query):
    """Fuzzy substring match on species name."""
    return [
        item for item in items
        if query in _species_display_name(_unpack_item(item)[0],
                                          _unpack_item(item)[1]).lower()
    ]


def _filter_by_type(items, type_query):
    """Filter by type. Supports single type or dual type:fire/dragon."""
    parts = [t.strip() for t in type_query.split("/") if t.strip()]
    results = []
    for item in items:
        c, d = _unpack_item(item)
        types_lower = [t.lower() for t in (d.get("types") or [])]
        if all(p in types_lower for p in parts):
            results.append(item)
    return results


def _filter_by_ability(items, ability_query):
    """Filter by ability name substring."""
    results = []
    for item in items:
        c, d = _unpack_item(item)
        abilities = d.get("abilities") or []
        for a in abilities:
            if a and ability_query in a.lower():
                results.append(item)
                break
    return results


def _filter_by_egg_group(items, egg_query):
    """Filter by egg group substring."""
    results = []
    for item in items:
        c, d = _unpack_item(item)
        groups = d.get("egg_groups") or []
        for g in groups:
            if g and egg_query in g.lower():
                results.append(item)
                break
    return results


def _is_bst_filter(query):
    """Check if query is a BST comparison filter."""
    return (query.startswith("bst>") or query.startswith("bst<")
            or query.startswith("bst="))


def _filter_by_bst(items, query):
    """Filter by BST comparison: bst>500, bst<400, bst=600."""
    op = query[3]
    try:
        threshold = int(query[4:])
    except (ValueError, IndexError):
        return items

    results = []
    for item in items:
        c, d = _unpack_item(item)
        bst = d.get("bst", 0)
        if op == ">" and bst > threshold:
            results.append(item)
        elif op == "<" and bst < threshold:
            results.append(item)
        elif op == "=" and bst == threshold:
            results.append(item)
    return results


# ---------------------------------------------------------------------------
# Species browser (main view)
# ---------------------------------------------------------------------------


def _species_browser(folded_list, species_order, species_data, game_path,
                     move_names, ability_names, form_tables, settings):
    """Interactive scrolling species list browser."""
    nav = _nav_keys(settings)
    active_filter = ""
    display_list = list(folded_list)

    state = ListState(len(display_list))

    while True:
        clear_screen()
        _render_browser_header(active_filter, len(display_list))

        start, end = visible_range(state)
        above = overflow_above(state)
        if above:
            print(above)

        for i in range(start, end):
            base_const, base_data, form_consts = display_list[i]
            _render_browser_row(state, i, base_const, base_data, form_consts)

        below = overflow_below(state)
        if below:
            print(below)

        print()
        extra = f"  {_k('/')} search"
        print(f"  {footer_hint(nav, extra)}")
        print()

        try:
            raw = input("  > ")
        except (EOFError, KeyboardInterrupt):
            return

        key = raw.strip().lower()

        # Search mode
        if key == "/":
            active_filter, display_list = _handle_search(
                folded_list, active_filter
            )
            state = ListState(len(display_list))
            continue

        # Dex number or name lookup — intercept before list widget
        typed = raw.strip()
        if typed and not typed.startswith("/") and key not in ("q", nav[0], nav[1], nav[2], nav[3], "k", "f", ""):
            idx = _name_or_dex_jump(typed, display_list, state)
            if idx is not None:
                base_const, base_data, form_consts = display_list[idx]
                _card_view(base_const, base_data, game_path, move_names,
                           ability_names, species_order, species_data,
                           form_tables, form_consts, settings)
                state = ListState(len(display_list),
                                  selected=state.selected,
                                  scroll_top=state.scroll_top)
            continue

        action = handle_input(state, raw, nav)

        if action == "quit":
            if active_filter:
                active_filter = ""
                display_list = list(folded_list)
                state = ListState(len(display_list))
            else:
                return
        elif action in ("open", "jump_act"):
            if display_list:
                base_const, base_data, form_consts = display_list[state.selected]
                _card_view(base_const, base_data, game_path, move_names,
                           ability_names, species_order, species_data,
                           form_tables, form_consts, settings)
                state = ListState(len(display_list),
                                  selected=state.selected,
                                  scroll_top=state.scroll_top)


def _name_or_dex_jump(query, display_list, state):
    """Find entry by name or dex number, move cursor, return index (or None).

    If query is numeric, match against nat_dex_num.
    Otherwise, substring match against species name.
    """
    # Dex number lookup
    if query.isdigit():
        target_num = int(query)
        for i, (base_const, base_data, _fc) in enumerate(display_list):
            if (base_data.get("nat_dex_num") or 0) == target_num:
                state.selected = i
                guard_bounds(state)
                return i
        return None
    # Name lookup
    q = query.lower()
    for i, (base_const, base_data, _fc) in enumerate(display_list):
        name = _species_display_name(base_const, base_data).lower()
        if q in name:
            state.selected = i
            guard_bounds(state)
            return i
    return None


def _render_browser_header(active_filter, count):
    """Print the browser header."""
    print()
    print(f"  {GOLD}Dex{RST} {DIM}--- Species Browser{RST}")
    print(BAR)
    if active_filter:
        print(f"  {CYAN}Filter: {active_filter}{RST}  ({count} matches)")
    print()


def _render_browser_row(state, index, const, data, form_consts):
    """Render a single row in the species browser list."""
    mk = marker(state, index)
    name = _species_display_name(const, data)
    types = "/".join(data.get("types") or ["???"]).ljust(16)
    dex_num = data.get("nat_dex_num") or 0
    dex_label = f"#{dex_num:03d}" if dex_num else "#---"

    extra_forms = len(form_consts) - 1
    badge = f" {DIM}+{extra_forms}{RST}" if extra_forms > 0 else ""

    print(f"  {mk} {dex_label}  {name:<18s} {DIM}{types}{RST}{badge}")


def _handle_search(folded_list, current_filter):
    """Prompt for search query and return (filter_string, filtered_list)."""
    print()
    print(f"  {CYAN}Search:{RST} name | type:fire | ability:intimidate"
          f" | bst>500 | egg:dragon")
    if current_filter:
        print(f"  {DIM}Current: {current_filter}  (Enter to clear){RST}")

    try:
        query = input(f"  {CYAN}/{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return (current_filter, _filter_species(list(folded_list),
                                                current_filter))

    if not query:
        return ("", list(folded_list))

    filtered = _filter_species(list(folded_list), query)
    return (query, filtered)


# ---------------------------------------------------------------------------
# Card view
# ---------------------------------------------------------------------------


def _card_view(const, data, game_path, move_names,
               ability_names, species_order, species_data,
               form_tables, form_consts, settings):
    """Display detailed species card view with form paging and evo navigation."""
    form_index = 0
    # Find initial form index matching const
    for i, fc in enumerate(form_consts):
        if fc == const:
            form_index = i
            break

    while True:
        cur_const = form_consts[form_index]
        cur_data = species_data.get(cur_const) or data

        clear_screen()
        chain = _build_evolution_chain(cur_const, species_order, species_data)
        _render_card(cur_const, cur_data, form_consts, form_index,
                     species_order, species_data, chain)

        footer = _build_card_footer(form_consts, chain)
        print(f"  {footer}")
        print()

        try:
            raw = input("  > ")
        except (EOFError, KeyboardInterrupt):
            return

        key = raw.strip().lower()
        if key == "q":
            return
        if key == "l":
            _learnset_view(cur_const, cur_data, game_path, move_names,
                           "level_up", settings)
            continue
        if key == "t":
            _learnset_view(cur_const, cur_data, game_path, move_names,
                           "teachable", settings)
            continue
        if key == "e":
            _learnset_view(cur_const, cur_data, game_path, move_names,
                           "egg", settings)
            continue

        result = _handle_card_input(key, form_index, form_consts, chain,
                                    species_data, form_tables)
        if result:
            form_consts, form_index, const, data = result


def _handle_card_input(key, form_index, form_consts, chain,
                       species_data, form_tables):
    """Process card view input for form paging and evo jumps.

    Returns (form_consts, form_index, const, data) if state changed,
    or None if no action taken.
    """
    if key in (">", ".") and len(form_consts) > 1:
        return (form_consts, (form_index + 1) % len(form_consts),
                form_consts[0], species_data.get(form_consts[0]))
    if key in ("<", ",") and len(form_consts) > 1:
        return (form_consts, (form_index - 1) % len(form_consts),
                form_consts[0], species_data.get(form_consts[0]))
    if key.isdigit() and chain:
        target_idx = int(key) - 1
        if 0 <= target_idx < len(chain):
            target_const = chain[target_idx][0]
            target_data = species_data.get(target_const)
            if target_data:
                new_forms = form_tables.get(target_const, [target_const])
                return (new_forms, 0, target_const, target_data)
    return None


def _build_card_footer(form_consts, chain):
    """Build the card view footer hint string (two lines)."""
    move_line = (f"{_k('l')} Learnset  {_k('t')} TM/Tutor  "
                 f"{_k('e')} Egg moves")
    nav_parts = []
    if chain and len(chain) > 1:
        nav_parts.append(f"{_k('1')}-{_k(str(len(chain)))} Evo")
    if len(form_consts) > 1:
        nav_parts.append(f"{_k('<')} {_k('>')} Forms")
    nav_parts.append(f"{_k('q')} Back")
    nav_line = "  ".join(nav_parts)
    return f"{move_line}\n  {nav_line}"


def _render_card(const, data, form_consts, form_index,
                 species_order, species_data, chain):
    """Render the species card to stdout."""
    name = _species_display_name(const, data).upper()
    category = data.get("category") or ""
    cat_display = f"{category} Pokemon" if category else ""
    types_str = " / ".join(data.get("types") or ["???"])

    # Header
    print()
    dex_num = data.get("nat_dex_num") or 0
    dex_label = f"#{dex_num:03d}" if dex_num else "#---"
    print(f"  {GOLD}\u2550" * 45 + RST)
    print(f"   {WHITE}{name}{RST}  {dex_label}"
          f"       {DIM}{cat_display}{RST}")
    print(f"   {CYAN}{types_str}{RST}")
    print(f"  {GOLD}\u2550" * 45 + RST)

    # Form indicator
    if len(form_consts) > 1:
        _render_form_indicator(const, form_consts, form_index)

    # Stats
    _render_stat_section(data)

    # Info
    _render_info_section(data)

    # Evolution
    _render_evolution_section(chain, species_data)

    # Description
    _render_description_section(data)

    print()


def _render_form_indicator(const, form_consts, form_index):
    """Render the form indicator line below the card header."""
    base_const = form_consts[0]
    label = _form_label(const, base_const)
    if label:
        display = label
    else:
        display = _species_display_name(const, None)
        if const.startswith("SPECIES_"):
            display = const[8:].replace("_", " ").title()
    pos = form_index + 1
    total = len(form_consts)
    print(f"   {DIM}Form {pos}/{total}: {RST}{display}"
          f"          {DIM}< prev  > next{RST}")


def _render_stat_section(data):
    """Render the stat bars section of the card."""
    print()
    print(f"  {DIM}\u2500\u2500 Stats "
          + "\u2500" * 38 + RST)
    for label, key in zip(_STAT_LABELS, _STAT_KEYS):
        val = data.get(key, 0)
        bar = _stat_bar(val)
        print(f"   {label:<3s} {bar} {val:>3d}")
    bst = data.get("bst", 0)
    print(f"       {DIM}\u2500" * 16 + f" BST  {bst}{RST}")


def _stat_bar(value):
    """Generate a proportional stat bar string."""
    filled = round(value / _STAT_MAX * _STAT_BAR_WIDTH)
    filled = max(0, min(filled, _STAT_BAR_WIDTH))
    empty = _STAT_BAR_WIDTH - filled
    return f"{CYAN}\u2588" * filled + f"{DIM}\u2591" * empty + RST


def _render_info_section(data):
    """Render the info section of the card."""
    print()
    print(f"  {DIM}\u2500\u2500 Info "
          + "\u2500" * 39 + RST)

    # Abilities
    abilities = data.get("abilities") or [None, None, None]
    ability_str = _format_abilities(abilities)
    print(f"   Abilities:  {ability_str}")

    # Catch rate
    catch_rate = data.get("catch_rate", "???")
    print(f"   Catch Rate: {catch_rate}")

    # Egg groups
    egg_groups = data.get("egg_groups") or []
    egg_str = ", ".join(egg_groups) if egg_groups else "---"
    print(f"   Egg Groups: {egg_str}")

    # Gender
    gender = data.get("gender_ratio") or "---"
    print(f"   Gender:     {gender}")

    # Growth rate
    growth = data.get("growth_rate") or "---"
    print(f"   Growth:     {growth}")

    # EVs
    evs = data.get("evs") or {}
    ev_str = _format_evs(evs)
    print(f"   EVs:        {ev_str}")

    # Height / Weight
    height_dm = data.get("height", 0)
    weight_hg = data.get("weight", 0)
    height_m = height_dm / 10.0
    weight_kg = weight_hg / 10.0
    print(f"   Height:     {height_m:.1f}m  Weight: {weight_kg:.1f}kg")


def _format_abilities(abilities):
    """Format ability slots into display string."""
    # Pad to 3 slots
    while len(abilities) < 3:
        abilities.append(None)

    parts = []
    # Slot 1
    a1 = abilities[0] or "---"
    parts.append(a1)

    # Slot 2 (skip if same as slot 1)
    a2 = abilities[1]
    if a2 and a2 != abilities[0]:
        parts.append(a2)

    result = " / ".join(parts)

    # Hidden ability (slot 3)
    a3 = abilities[2]
    if a3:
        result += f" / {a3} (H)"
    else:
        result += " / --- (H)"

    return result


def _format_evs(evs):
    """Format EV yields into display string."""
    if not evs:
        return "None"
    parts = []
    for key in _STAT_KEYS:
        val = evs.get(key, 0)
        if val > 0:
            label = _EV_LABELS.get(key, key)
            parts.append(f"+{val} {label}")
    return ", ".join(parts) if parts else "None"


# ---------------------------------------------------------------------------
# Evolution chain
# ---------------------------------------------------------------------------


def _render_evolution_section(chain, species_data):
    """Render the evolution chain section with numbered entries."""
    print()
    print(f"  {DIM}\u2500\u2500 Evolution "
          + "\u2500" * 34 + RST)

    if not chain:
        print(f"   {DIM}Does not evolve{RST}")
        return

    chain_str = _format_numbered_chain(chain, species_data)
    if len(chain_str) > 72:
        _print_wrapped_numbered_chain(chain, species_data)
    else:
        print(f"   {chain_str}")


def _format_numbered_chain(chain, species_data):
    """Format an evolution chain as a single-line string with numbered entries."""
    parts = []
    for i, entry in enumerate(chain):
        sp_const = entry[0]
        sp_data = species_data.get(sp_const) or {}
        name = _species_display_name(sp_const, sp_data)
        num = f"[{i + 1}] "
        if i == 0:
            parts.append(f"{num}{name}")
        else:
            method = entry[1]
            param = entry[2]
            arrow = _evo_arrow(method, param)
            parts.append(f"{arrow} {num}{name}")
    return " ".join(parts)


def _print_wrapped_numbered_chain(chain, species_data):
    """Print a long numbered evolution chain with line breaks."""
    for i, entry in enumerate(chain):
        sp_const = entry[0]
        sp_data = species_data.get(sp_const) or {}
        name = _species_display_name(sp_const, sp_data)
        num = f"[{i + 1}] "
        if i == 0:
            print(f"   {num}{name}")
        else:
            method = entry[1]
            param = entry[2]
            arrow = _evo_arrow(method, param)
            print(f"     {arrow} {num}{name}")


def _build_evolution_chain(const, species_order, species_data):
    """Build the full evolution chain starting from the base form.

    Returns list of (species_const, method, param) tuples
    in chain order. The first entry has method=None (it's the base).
    """
    # Walk backwards to find the base form
    base = _find_base_form(const, species_data)

    # Walk forward from base
    chain = [(base, None, None)]
    visited = {base}
    _walk_chain_forward(base, species_data, chain, visited)

    if len(chain) <= 1:
        # Check if current species has evolutions
        evos = (species_data.get(const) or {}).get("evolutions") or []
        if not evos:
            return []

    return chain


def _find_base_form(const, species_data):
    """Walk backwards through evolution data to find the base form."""
    current = const
    visited = {current}
    for _ in range(10):  # safety limit
        found_pre = False
        for sp_const, sp_data in species_data.items():
            if sp_const in visited:
                continue
            evos = sp_data.get("evolutions") or []
            for evo in evos:
                if evo.get("target") == current:
                    current = sp_const
                    visited.add(current)
                    found_pre = True
                    break
            if found_pre:
                break
        if not found_pre:
            break
    return current


def _walk_chain_forward(current, species_data, chain, visited):
    """Recursively walk evolution chain forward, appending to chain.

    Skips form variants — if a target shares the same nat_dex_num as an
    existing chain entry, it's a regional/alternate form, not a true evolution.
    """
    info = species_data.get(current)
    if not info:
        return
    evos = info.get("evolutions") or []
    # Build set of dex nums already represented in the chain
    chain_dex_nums = set()
    for entry in chain:
        entry_data = species_data.get(entry[0]) or {}
        dn = entry_data.get("nat_dex_num") or 0
        if dn:
            chain_dex_nums.add(dn)
    for evo in evos:
        target = evo.get("target", "")
        if not target or target in visited:
            continue
        # Check if target is a form variant of something already in the chain
        target_data = species_data.get(target) or {}
        target_dex = target_data.get("nat_dex_num") or 0
        if target_dex and target_dex in chain_dex_nums:
            visited.add(target)
            continue
        method = evo.get("method", "")
        param = evo.get("param", "")
        chain.append((target, method, param))
        visited.add(target)
        if target_dex:
            chain_dex_nums.add(target_dex)
        _walk_chain_forward(target, species_data, chain, visited)



def _evo_arrow(method, param):
    """Build an evolution arrow string from method and param."""
    if not method:
        return "\u2500>"

    label = _EVO_METHOD_LABELS.get(method, method)

    if method == "LEVEL":
        if param == "0":
            return "\u2500Level\u2500>"
        return f"\u2500Lv.{param}\u2500>"
    if method in ("ITEM", "USE_ITEM"):
        item_name = _const_to_name(param, "ITEM_")
        return f"\u2500{item_name}\u2500>"
    if method == "USE_ITEM_MALE":
        item_name = _const_to_name(param, "ITEM_")
        return f"\u2500{item_name} (M)\u2500>"
    if method == "USE_ITEM_FEMALE":
        item_name = _const_to_name(param, "ITEM_")
        return f"\u2500{item_name} (F)\u2500>"
    if method == "TRADE":
        return "\u2500Trade\u2500>"
    if method == "TRADE_ITEM":
        item_name = _const_to_name(param, "ITEM_")
        return f"\u2500Trade w/{item_name}\u2500>"
    if method == "FRIENDSHIP":
        return "\u2500Friendship\u2500>"
    if method == "MOVE":
        move_name = _const_to_name(param, "MOVE_")
        return f"\u2500Know {move_name}\u2500>"
    if label:
        if param and param.isdigit():
            return f"\u2500{label}{param}\u2500>"
        return f"\u2500{label}\u2500>"
    return f"\u2500{method}\u2500>"


def _const_to_name(const, prefix):
    """Convert a constant like ITEM_THUNDER_STONE to 'Thunder Stone'."""
    if const and const.startswith(prefix):
        return const[len(prefix):].replace("_", " ").title()
    return const or "???"


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------


def _render_description_section(data):
    """Render the description section of the card."""
    print()
    print(f"  {DIM}\u2500\u2500 Description "
          + "\u2500" * 32 + RST)
    desc = data.get("description")
    if not desc:
        print(f"   {DIM}No description available.{RST}")
        return
    # Wrap to ~74 cols (80 - 6 indent)
    wrapped = textwrap.fill(desc, width=74)
    for line in wrapped.split("\n"):
        print(f"   {line}")


# ---------------------------------------------------------------------------
# Learnset views
# ---------------------------------------------------------------------------


def _learnset_view(const, data, game_path, move_names, kind, settings):
    """Display a learnset tab (level_up, teachable, or egg)."""
    name = _species_display_name(const, data)
    nav = _nav_keys(settings)

    if kind == "level_up":
        _level_up_view(const, name, game_path, move_names, nav)
    elif kind == "teachable":
        _teachable_view(const, name, game_path, move_names, nav)
    elif kind == "egg":
        _egg_moves_view(const, name, game_path, move_names, nav)


def _level_up_view(const, name, game_path, move_names, nav):
    """Display level-up learnset with scrolling."""
    moves = load_level_up_learnset(game_path, const)
    if not moves:
        _show_empty_learnset("Level-Up Moves", name)
        return

    # Build display rows
    rows = []
    for level, move_const in moves:
        friendly = move_names.get(move_const, _const_to_name(move_const, "MOVE_"))
        rows.append(f"Lv.{level:<3d} {friendly}")

    _scrolling_learnset(f"Level-Up Moves ({name})", rows, nav)


def _teachable_view(const, name, game_path, move_names, nav):
    """Display teachable learnset with scrolling."""
    moves = load_teachable_learnset(game_path, const)
    if not moves:
        _show_empty_learnset("TM/Tutor Moves", name)
        return

    rows = []
    for move_const in moves:
        friendly = move_names.get(move_const, _const_to_name(move_const, "MOVE_"))
        rows.append(friendly)
    rows.sort()

    _scrolling_learnset(f"TM/Tutor Moves ({name})", rows, nav)


def _egg_moves_view(const, name, game_path, move_names, nav):
    """Display egg moves with scrolling."""
    moves = load_egg_moves(game_path, const)
    if not moves:
        _show_empty_learnset("Egg Moves", name)
        return

    rows = []
    for move_const in moves:
        friendly = move_names.get(move_const, _const_to_name(move_const, "MOVE_"))
        rows.append(friendly)
    rows.sort()

    _scrolling_learnset(f"Egg Moves ({name})", rows, nav)


def _show_empty_learnset(title, name):
    """Show empty learnset message and wait for key."""
    clear_screen()
    print()
    print(f"  {DIM}\u2500\u2500 {title} ({name}) "
          + "\u2500" * max(2, 40 - len(title) - len(name)) + RST)
    print()
    print(f"   {DIM}No data available.{RST}")
    print()
    print(f"  {_k('q')} Back")
    print()
    try:
        input("  > ")
    except (EOFError, KeyboardInterrupt):
        pass


def _scrolling_learnset(title, rows, nav):
    """Display a scrollable learnset list."""
    state = ListState(len(rows))

    while True:
        clear_screen()
        print()
        print(f"  {DIM}\u2500\u2500 {title} "
              + "\u2500" * max(2, 44 - len(title)) + RST)
        print()

        start, end = visible_range(state)
        above = overflow_above(state)
        if above:
            print(above)

        for i in range(start, end):
            mk = marker(state, i)
            print(f"  {mk} {rows[i]}")

        below = overflow_below(state)
        if below:
            print(below)

        print()
        print(f"  {_k('q')} Back")
        print()

        try:
            raw = input("  > ")
        except (EOFError, KeyboardInterrupt):
            return

        action = handle_input(state, raw, nav)
        if action == "quit":
            return
