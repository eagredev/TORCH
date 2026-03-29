"""Trainer list, card flow, deletion, recovery, and battle menus."""
# TORCH_MODULE: Trainer Manager
# TORCH_GROUP: Trainers
import os
import re
import sys
from datetime import datetime

from torch import VERSION, BATTLE_VERSION
from torch.config import load_config, save_config, SETTINGS_DEFAULTS, _nav_keys, DIVIDER
from torch.expansion_compat import BATTLE_TYPE_TWO_TRAINERS_NO_INTRO
from torch.ui import (
    print_logo, _set_terminal_title, _offer_build, _k,
    _fmt_class, _fmt_const_name, _truncate_dialogue,
    _parse_ability_names, _parse_ability_descriptions, _parse_move_names,
    _count_dialogue_boxes, _dialogue_prompt, clear_screen,
)
from torch.names import (
    _detect_trainer_format, _detect_project_variant,
    _const_to_human_name, _human_name_to_const,
    _const_to_species_name, _const_to_move_name, _const_to_item_name,
    _const_to_ability_name, _const_to_nature_name,
    _format_stat_spread, _format_stat_spread_full, _parse_stat_spread,
    _ai_flags_to_party_format, _party_ai_to_const, _party_gender_to_const,
)
from torch.battle_wizard import (
    _battle_prompt, _confirm_value, _parse_defines, _to_pascal_case,
    _wrap_dialogue, _ai_flags_menu,
    _normalise_constant_input, _validate_and_prompt,
    _parse_showdown_team,
    _read_opponents_h, _write_opponents_h, _emit_mon_block_lines,
    _append_party, _insert_trainer,
    pick_encounter_music, pick_trainer_sprite,
)
from torch.battle_io import (
    _get_custom_trainer_consts, _find_trainer_map_refs,
    _recovery_scan, _scan_custom_battles,
    _parse_party_header_only, _load_all_trainers,
    _read_trainer_record, _read_party_file, _parse_party_section,
    _read_trainer_record_party,
    _serialize_party_mon, _serialize_party_trainer,
    _append_trainer_to_party_file, _replace_trainer_in_party_file,
    _patch_party_file_field, _replace_party_in_party_file,
    _delete_from_party_file, _read_pory_dialogue,
    _ensure_map_workspace, _build_recovery_stub,
)
from torch.battle_card import (
    _display_trainer_card, _patch_trainers_h_field, _replace_party,
    _parse_species_abilities, _scan_all_references, _write_deletion_report,
    _find_lowest_available_id, _recalculate_trainers_count, _change_trainer_id,
)
from torch.battle_migrator import (
    _run_battle_format_migrator, _read_record_dispatch,
    _is_orphaned_trainer, _handle_orphan_prompt,
)
from torch.project_files import build_trainer_map_index, classify_maps
from torch.sync import sync_map, ensure_synced
from torch.colours import GOLD, WHITE, CYAN, GREEN, DIM, RST, BAR


# ============================================================
# BATTLE TYPES — Full catalogue with version requirements
# ============================================================

# (type_name, poryscript_macro, min_version, description)
# min_version of None = available on all supported versions (1.6.0+)
BATTLE_TYPES = [
    ("single", "trainerbattle_single", None, "Standard 1v1"),
    ("double", "trainerbattle_double", None, "2v2 double battle"),
    ("continue_script", "trainerbattle_single", None, "Battle with post-battle script (music continues)"),
    ("continue_script_no_music", "trainerbattle_single", None, "Battle with post-battle script (music stops)"),
    ("single_no_intro", "trainerbattle_no_intro", None, "1v1 without trainer intro text"),
    ("rematch", "trainerbattle_rematch", None, "Rematch battle (VS Seeker / gym leader)"),
    ("continue_script_double", "trainerbattle_double", None, "Double battle with post-battle script (music continues)"),
    ("rematch_double", "trainerbattle_rematch_double", None, "Double rematch battle"),
    ("continue_script_double_no_music", "trainerbattle_double", None, "Double battle with post-battle script (music stops)"),
    ("two_trainers", "trainerbattle_two_trainers", BATTLE_TYPE_TWO_TRAINERS_NO_INTRO, "Two trainers, no intro text"),
]


def _available_battle_types(expansion_version=None):
    """Return the list of battle types available for a given expansion version.
    If expansion_version is None (unknown), return all types."""
    if expansion_version is None:
        return list(BATTLE_TYPES)
    return [bt for bt in BATTLE_TYPES if bt[2] is None or expansion_version >= bt[2]]


def _pick_battle_type(expansion_version=None):
    """Show a numbered menu of battle types and return (type_name, macro, is_double).
    Returns None if the user cancels."""
    available = _available_battle_types(expansion_version)
    print(f"  {DIM}Available battle types:{RST}")
    print()
    for idx, (type_name, macro, min_ver, desc) in enumerate(available, 1):
        ver_note = ""
        if min_ver:
            ver_note = f" {DIM}(v{min_ver[0]}.{min_ver[1]}.{min_ver[2]}+){RST}"
        print(f"    {GOLD}[{idx}]{RST} {type_name:<35} {DIM}{desc}{RST}{ver_note}")
    print()
    while True:
        raw = input("  Battle type (number, or Enter for single) > ").strip()
        if not raw:
            return available[0]  # default to single
        try:
            pick = int(raw)
            if 1 <= pick <= len(available):
                chosen = available[pick - 1]
                # Check version gate (shouldn't happen since we filtered, but safety)
                if chosen[2] is not None and expansion_version is not None and expansion_version < chosen[2]:
                    v = chosen[2]
                    print(f"  This battle type requires expansion v{v[0]}.{v[1]}.{v[2]}+.")
                    print()
                    continue
                return chosen
        except ValueError:
            pass
        print(f"  Please enter a number 1-{len(available)}.")
        print()


# ============================================================
# TRAINER LIST — Handlers for list input actions
# ============================================================

def _list_handle_open(visible, selected_idx, fmt, opponents_path, trainers_h_path,
                      trainer_parties_path, party_path, project_dir, game_path,
                      workspace_expanded, settings, battles):
    """Handle opening a trainer card from the list. Returns (battles, all_trainers) refreshed."""
    t = visible[selected_idx]
    if t["is_custom"]:
        rec = _read_record_dispatch(t["trainer_const"], fmt, opponents_path,
                                    trainers_h_path, trainer_parties_path, party_path)
        if _is_orphaned_trainer(rec):
            if _handle_orphan_prompt(t["trainer_const"], t["pory_path"]):
                battles = _scan_custom_battles(project_dir)
                return battles, _load_all_trainers(opponents_path, party_path, battles)
        else:
            _trainer_card_flow(rec, t["map_folder"], t["pory_path"],
                               project_dir, game_path, workspace_expanded,
                               settings, fmt=fmt)
            battles = _scan_custom_battles(project_dir)
            return battles, _load_all_trainers(opponents_path, party_path, battles)
    else:
        rec = _read_record_dispatch(t["trainer_const"], fmt, opponents_path,
                                    trainers_h_path, trainer_parties_path, party_path)
        if rec:
            _trainer_card_flow(rec, "vanilla", None,
                               project_dir, game_path, workspace_expanded,
                               settings, fmt=fmt)
            return battles, _load_all_trainers(opponents_path, party_path, battles)
    return battles, _load_all_trainers(opponents_path, party_path, battles)


def _list_handle_delete(visible, selected_idx, fmt, opponents_path, trainers_h_path,
                        trainer_parties_path, party_path, project_dir, game_path,
                        workspace_expanded, settings, battles):
    """Handle delete action from the list. Returns (battles, all_trainers) refreshed."""
    t = visible[selected_idx]
    rec = _read_record_dispatch(t["trainer_const"], fmt, opponents_path,
                                trainers_h_path, trainer_parties_path, party_path)
    if rec is None:
        print(f"  Could not load trainer record for {t['trainer_const']}.")
        input("  Press Enter > ")
    else:
        _trainer_card_flow(rec, t.get("map_folder") or "vanilla", t.get("pory_path"),
                           project_dir, game_path, workspace_expanded,
                           settings, fmt=fmt, jump_to_delete=True)
    battles = _scan_custom_battles(project_dir)
    return battles, _load_all_trainers(opponents_path, party_path, battles)


def _list_handle_numeric(choice, visible, selected_idx, total):
    """Handle numeric input in the trainer list. Returns new selected_idx."""
    try:
        num = int(choice)
        if num >= 100 and total > 0:
            for i, t in enumerate(visible):
                if t["trainer_id"] == num:
                    return i
            row_idx = num - 1
            if 0 <= row_idx < total:
                return row_idx
            print(f"  No trainer with ID {num} in current view.")
            input("  Press Enter > ")
        elif 1 <= num <= total:
            return num - 1
        else:
            print(f"  Please enter 1-{total}.")
            input("  Press Enter > ")
    except ValueError:
        pass
    return selected_idx


def _list_render(visible, total, selected_idx, scroll_offset, max_visible,
                 show_vanilla, search_filter, NK_SCROLL, NK_UP, NK_DOWN):
    """Render the trainer list display."""
    clear_screen()
    print()
    print(BAR)
    mode_label = "ALL TRAINERS" if show_vanilla else "CUSTOM ONLY"
    print(f"   {WHITE}TRAINER LIST{RST}  {DIM}({mode_label}){RST}")
    if search_filter:
        print(f"   {DIM}Filter:{RST} {CYAN}\"{search_filter}\"{RST}")
    print(BAR)
    print()

    if total == 0:
        if search_filter:
            print(f"  {DIM}No trainers match the filter.{RST}")
        elif not show_vanilla:
            print(f"  {DIM}No custom battles found.{RST}")
        else:
            print(f"  {DIM}No trainers found.{RST}")
        print()
    else:
        num_w = len(str(total))
        print(f"  {DIM}  {'#':<{num_w + 1}}  {'ID':>4}  {'Class':<22}{'Name':<13}Location{RST}")

        if scroll_offset > 0:
            print(f"  {DIM}  \u2191 {scroll_offset} more above{RST}")

        end = min(scroll_offset + max_visible, total)
        for idx in range(scroll_offset, end):
            t = visible[idx]
            marker = f"{GOLD}>>{RST}" if idx == selected_idx else "  "
            row_num = f"{idx + 1}."
            tid = t["trainer_id"]
            class_str = _fmt_class(t["trainer_class"]) if t["trainer_class"] else "?"
            name_str = f'"{t["trainer_name"]}"' if t["trainer_name"] else ""
            location = t["map_folder"] if t["map_folder"] else ""

            if t["is_vanilla"]:
                if not t["map_folder"]:
                    location = f"{DIM}vanilla{RST}"
                print(f"  {marker} {DIM}{row_num:<{num_w + 1}}  {tid:>4}  {class_str:<22}{name_str:<13}{RST}{location}")
            else:
                print(f"  {marker} {row_num:<{num_w + 1}}  {tid:>4}  {class_str:<22}{name_str:<13}{location}")

        if end < total:
            print(f"  {DIM}  \u2193 {total - end} more below{RST}")
        print()

    # Command bar
    nav_parts = [f"{_k('#')}/{_k('v')} {DIM}open{RST}"]
    if NK_SCROLL:
        nav_parts.append(f"{_k(NK_SCROLL)} {DIM}scroll{RST}")
    nav_parts.extend([f"{_k(NK_UP)} {DIM}up{RST}", f"{_k(NK_DOWN)} {DIM}down{RST}"])
    nav_parts.append(f"{_k('x')} {DIM}" + ("custom" if show_vanilla else "all") + RST)
    if search_filter:
        nav_parts.append(f"{_k('c')} {DIM}clear filter{RST}")
    else:
        nav_parts.append(f"{_k('/')} {DIM}search{RST}")
    nav_parts.append(f"{_k('p')} {DIM}partners{RST}")
    nav_parts.append(f"{_k('d')} {DIM}delete{RST}")
    nav_parts.append(f"{_k('q')} {DIM}back{RST}")
    print("  " + "  ".join(nav_parts))
    print()


def _list_handle_input(raw, visible, total, selected_idx, scroll_offset,
                       show_vanilla, search_filter, NK_SCROLL, NK_UP, NK_DOWN,
                       fmt, opponents_path, trainers_h_path, trainer_parties_path,
                       party_path, project_dir, game_path, workspace_expanded,
                       settings, battles):
    """Process one input in the trainer list. Returns None to quit, or updated state tuple."""
    all_trainers = None  # only refreshed on open/delete

    if raw in ("", " ", NK_SCROLL):
        if total > 0:
            selected_idx = (selected_idx + 1) % total
        return selected_idx, scroll_offset, show_vanilla, search_filter, battles, None

    choice = raw.strip()

    if choice.lower() in ("b", NK_UP):
        if total > 0:
            selected_idx = max(0, selected_idx - 1)
        return selected_idx, scroll_offset, show_vanilla, search_filter, battles, None

    if choice.lower() == NK_DOWN:
        if total > 0:
            selected_idx = min(total - 1, selected_idx + 1)
        return selected_idx, scroll_offset, show_vanilla, search_filter, battles, None

    if choice.lower() == "v":
        if total > 0:
            battles, all_trainers = _list_handle_open(
                visible, selected_idx, fmt, opponents_path, trainers_h_path,
                trainer_parties_path, party_path, project_dir, game_path,
                workspace_expanded, settings, battles)
        return selected_idx, scroll_offset, show_vanilla, search_filter, battles, all_trainers

    if choice.lower() == "q":
        return None

    if choice.lower() == "x":
        return 0, 0, not show_vanilla, search_filter, battles, None

    if choice.lower() == "/" and not search_filter:
        q = input("  Search > ").strip()
        if q:
            return 0, 0, show_vanilla, q, battles, None
        return selected_idx, scroll_offset, show_vanilla, search_filter, battles, None

    if choice.lower() == "c" and search_filter:
        return 0, 0, show_vanilla, "", battles, None

    if choice.lower() == "p":
        from torch.battle_partners import partner_menu
        from torch.expansion_compat import detect_expansion_version
        ev = detect_expansion_version(game_path)
        partner_menu(game_path, expansion_version=ev, settings=settings)
        return selected_idx, scroll_offset, show_vanilla, search_filter, battles, None

    if choice.lower() == "d":
        if total > 0:
            battles, all_trainers = _list_handle_delete(
                visible, selected_idx, fmt, opponents_path, trainers_h_path,
                trainer_parties_path, party_path, project_dir, game_path,
                workspace_expanded, settings, battles)
        return selected_idx, scroll_offset, show_vanilla, search_filter, battles, all_trainers

    # Try numeric
    selected_idx = _list_handle_numeric(choice, visible, selected_idx, total)
    return selected_idx, scroll_offset, show_vanilla, search_filter, battles, None


# ============================================================
# TRAINER LIST — Scrolling list with vanilla toggle
# ============================================================

def _list_all_trainers(battles, opponents_path, trainers_h_path, trainer_parties_path,
                       project_dir, game_path, workspace_expanded, settings=None, fmt=None):
    """Scrolling trainer list with vanilla toggle, selection marker, and overflow indicators."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if fmt is None:
        fmt = _detect_trainer_format(game_path)
    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    max_visible = settings["trainer_list_page_size"]
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)

    # Bulk-load all trainers once
    all_trainers = _load_all_trainers(opponents_path, party_path, battles)
    if not all_trainers:
        print("  No trainers found.")
        print()
        input("  Press Enter to go back > ")
        return

    show_vanilla = bool(settings.get("show_all_trainers", False))
    selected_idx = 0
    scroll_offset = 0
    search_filter = ""

    def _filtered_list():
        """Return the currently visible trainer list based on filters."""
        lst = all_trainers
        if not show_vanilla:
            lst = [t for t in lst if t["is_custom"]]
        if search_filter:
            q = search_filter.upper()
            lst = [t for t in lst if q in t["trainer_const"] or
                   (t["trainer_name"] and q in t["trainer_name"].upper()) or
                   (t["trainer_class"] and q in _fmt_class(t["trainer_class"]).upper())]
        return lst

    while True:
        visible = _filtered_list()
        total = len(visible)

        # Clamp selection
        if total == 0:
            selected_idx = 0
        else:
            selected_idx = max(0, min(selected_idx, total - 1))

        # Adjust scroll to keep selected in view
        if total > 0:
            if selected_idx < scroll_offset:
                scroll_offset = selected_idx
            if selected_idx >= scroll_offset + max_visible:
                scroll_offset = selected_idx - max_visible + 1

        _list_render(visible, total, selected_idx, scroll_offset, max_visible,
                     show_vanilla, search_filter, NK_SCROLL, NK_UP, NK_DOWN)

        raw = input(f"  {GOLD}>{RST} ")
        raw = raw.rstrip("\n")

        result = _list_handle_input(raw, visible, total, selected_idx, scroll_offset,
                                    show_vanilla, search_filter, NK_SCROLL, NK_UP, NK_DOWN,
                                    fmt, opponents_path, trainers_h_path, trainer_parties_path,
                                    party_path, project_dir, game_path, workspace_expanded,
                                    settings, battles)
        if result is None:
            return
        selected_idx, scroll_offset, show_vanilla, search_filter, battles, refreshed = result
        if refreshed is not None:
            all_trainers = refreshed


# ============================================================
# MAP-CENTRIC TRAINER BROWSER
# ============================================================

def _map_browser_build_rows(game_path, show_vanilla):
    """Build the map row list for the map browser.

    Returns list of dicts: [{name, trainer_count, is_vanilla}, ...]
    Custom maps first (sorted by name), vanilla optionally appended.
    """
    map_trainers, _ = build_trainer_map_index(game_path)
    vanilla_maps, custom_maps = classify_maps(game_path)

    # Also include map folders from the index that aren't in either set
    all_map_folders = set(map_trainers.keys())

    rows = []
    # Custom maps with trainers first
    custom_names = sorted(
        n for n in all_map_folders
        if n not in vanilla_maps
    )
    for name in custom_names:
        rows.append({
            "name": name,
            "trainer_count": len(map_trainers.get(name, [])),
            "is_vanilla": False,
        })

    # Vanilla maps (only if toggled on)
    if show_vanilla:
        vanilla_names = sorted(
            n for n in all_map_folders
            if n in vanilla_maps
        )
        for name in vanilla_names:
            rows.append({
                "name": name,
                "trainer_count": len(map_trainers.get(name, [])),
                "is_vanilla": True,
            })

    return rows


def _map_browser_trainer_detail(map_folder, game_path, all_trainers):
    """Get trainer summaries for a specific map folder.

    Returns list of dicts from all_trainers that belong to this map,
    plus any from the trainer_map_index not in all_trainers.
    """
    map_trainers, _ = build_trainer_map_index(game_path)
    consts_on_map = set(map_trainers.get(map_folder, []))
    if not consts_on_map:
        return []

    # Build lookup from all_trainers
    by_const = {t["trainer_const"]: t for t in all_trainers}

    result = []
    for c in sorted(consts_on_map):
        if c in by_const:
            result.append(by_const[c])
        else:
            # Trainer in scripts but not in opponents.h yet (stub)
            result.append({
                "trainer_const": c,
                "trainer_id": None,
                "trainer_name": None,
                "trainer_class": None,
                "is_vanilla": False,
                "is_custom": False,
                "map_folder": map_folder,
                "pory_path": None,
            })
    return result


def _map_browser_render(rows, selected_idx, scroll_top, page_size,
                        show_vanilla, vanilla_count, trainer_details,
                        NK_UP, NK_DOWN, NK_SCROLL, proj_name,
                        trainer_count_display, slots_remaining):
    """Render the map-centric trainer browser screen."""
    clear_screen()
    print_logo(f"Trainers  v{BATTLE_VERSION}  (Map View)", proj_name)
    print(BAR)
    slots_col = GREEN if isinstance(slots_remaining, int) and slots_remaining > 5 else CYAN
    print(f"   {WHITE}{trainer_count_display}{RST} {DIM}registered{RST}  {DIM}|{RST}  {slots_col}{slots_remaining}{RST} {DIM}slots free{RST}")
    print(BAR)
    print()

    if not rows:
        print(f"  {DIM}No maps with trainers found.{RST}")
        print()
    else:
        # Overflow above
        if scroll_top > 0:
            print(f"  {DIM}  \u2191 {scroll_top} more above{RST}")

        end = min(scroll_top + page_size, len(rows))
        for idx in range(scroll_top, end):
            r = rows[idx]
            marker = f"{GOLD}>>{RST}" if idx == selected_idx else "  "
            count_str = f"{r['trainer_count']} trainer{'s' if r['trainer_count'] != 1 else ''}"
            if r["is_vanilla"]:
                print(f"  {marker} {DIM}{r['name']:<35}{count_str}{RST}")
            else:
                print(f"  {marker} {r['name']:<35}{DIM}{count_str}{RST}")

        # Overflow below
        if end < len(rows):
            print(f"  {DIM}  \u2193 {len(rows) - end} more below{RST}")

        # Trainer detail for highlighted map
        if trainer_details:
            print()
            sel_name = rows[selected_idx]["name"] if 0 <= selected_idx < len(rows) else ""
            print(f"  {DIM}Trainers on {sel_name}:{RST}")
            for t in trainer_details[:8]:
                cls = _fmt_class(t["trainer_class"]) if t["trainer_class"] else "?"
                name = f'"{t["trainer_name"]}"' if t["trainer_name"] else ""
                tid = t["trainer_id"] if t["trainer_id"] else "---"
                print(f"    {DIM}{t['trainer_const']:<28}{RST} {cls:<18}{name}")
            if len(trainer_details) > 8:
                print(f"    {DIM}... {len(trainer_details) - 8} more{RST}")
        print()

    # Vanilla hint
    if not show_vanilla and vanilla_count > 0:
        print(f"  {DIM}{vanilla_count} vanilla maps hidden{RST}")
    print()

    # Footer
    parts = []
    if NK_SCROLL:
        parts.append(f"{_k(NK_SCROLL)} {DIM}scroll{RST}")
    parts.extend([
        f"{_k(NK_UP)} {DIM}up{RST}",
        f"{_k(NK_DOWN)} {DIM}down{RST}",
        f"{_k('v')} {DIM}open{RST}",
        f"{_k('a')} {DIM}flat list{RST}",
        f"{_k('n')} {DIM}new{RST}",
        f"{_k('f')} {DIM}" + ("hide vanilla" if show_vanilla else "show vanilla") + RST,
        f"{_k('q')} {DIM}back{RST}",
    ])
    print("  " + "  ".join(parts))
    print()


def _map_browser_pick_trainer(trainer_details):
    """Quick picker for trainers on a map. Returns index or None."""
    if not trainer_details:
        return None
    if len(trainer_details) == 1:
        return 0
    print()
    for i, t in enumerate(trainer_details, 1):
        name = f'"{t["trainer_name"]}"' if t["trainer_name"] else ""
        cls = _fmt_class(t["trainer_class"]) if t["trainer_class"] else ""
        print(f"    {GOLD}{i}{RST}  {t['trainer_const']:<28} {cls}  {name}")
    print()
    pick = input(f"  Pick trainer {DIM}(1-{len(trainer_details)}, q=cancel){RST} > ").strip()
    if pick.lower() == "q":
        return None
    try:
        idx = int(pick) - 1
        if 0 <= idx < len(trainer_details):
            return idx
    except ValueError:
        pass
    return None


def _map_browser_handle_input(raw, rows, selected_idx, scroll_top, show_vanilla,
                              NK_SCROLL, NK_UP, NK_DOWN):
    """Process one input in the map browser.

    Returns None to quit, "flat" for flat list, "new" for new wizard,
    or (selected_idx, scroll_top, show_vanilla) tuple.
    """
    total = len(rows)
    if raw in ("", " ", NK_SCROLL):
        if total > 0:
            selected_idx = (selected_idx + 1) % total
        return selected_idx, scroll_top, show_vanilla

    choice = raw.strip().lower()

    if choice in ("b", NK_UP):
        if total > 0:
            selected_idx = max(0, selected_idx - 1)
        return selected_idx, scroll_top, show_vanilla

    if choice == NK_DOWN:
        if total > 0:
            selected_idx = min(total - 1, selected_idx + 1)
        return selected_idx, scroll_top, show_vanilla

    if choice == "q":
        return None

    if choice == "a":
        return "flat"

    if choice == "n":
        return "new"

    if choice == "v":
        return "select"

    if choice == "f":
        return 0, 0, not show_vanilla

    return selected_idx, scroll_top, show_vanilla


def _map_browser_slot_count(opponents_path):
    """Read trainer slot counts from opponents.h.

    Returns (trainer_count_display, slots_remaining) — both may be "?" on error.
    """
    try:
        trainers_count, max_trainers, opp_lines = _read_opponents_h(opponents_path)
    except SystemExit:
        return "?", "?"
    if not max_trainers:
        return "?", "?"
    meta = {"TRAINERS_COUNT", "MAX_TRAINERS_COUNT", "TRAINER_NONE"}
    used = sum(1 for ln in opp_lines
               if re.match(r"^#define\s+(TRAINER_\w+)\s+\d+", ln)
               and re.match(r"^#define\s+(TRAINER_\w+)\s+\d+", ln).group(1) not in meta)
    return used, max_trainers - used - 1


def _map_browser_vanilla_count(game_path):
    """Count how many vanilla maps have trainers."""
    map_trainers_dict, _ = build_trainer_map_index(game_path)
    vanilla_maps_set, _ = classify_maps(game_path)
    return sum(1 for n in map_trainers_dict if n in vanilla_maps_set)


def battle_map_browser(game_path, project_dir, settings, emotes_conf=None,
                       source_display=None, proj_name=None, workspace_expanded=""):
    """Map-centric trainer browser -- view trainers grouped by map.

    Entry point from Map Studio landing page.
    """
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if proj_name is None:
        proj_name = os.path.basename(project_dir) or None

    # Check for expansion
    if _detect_project_variant(game_path) == "vanilla":
        clear_screen()
        print()
        print("  \u2718 Trainers requires pokeemerald-expansion.")
        print()
        input("  Press Enter to return > ")
        return

    _set_terminal_title("TORCH \u2014 Trainers (Map View)")
    fmt = _detect_trainer_format(game_path)
    opponents_path = os.path.join(game_path, "include", "constants", "opponents.h")
    trainers_h_path = os.path.join(game_path, "src", "data", "trainers.h")
    trainer_parties_path = os.path.join(game_path, "src", "data", "trainer_parties.h")
    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)
    page_size = settings.get("trainer_list_page_size", 16)

    show_vanilla = False
    selected_idx = 0
    scroll_top = 0

    # Load trainer data once (refreshed on return from sub-screens)
    battles = _scan_custom_battles(project_dir)
    all_trainers = _load_all_trainers(opponents_path, party_path, battles)

    while True:
        rows = _map_browser_build_rows(game_path, show_vanilla)
        total = len(rows)
        vanilla_count = _map_browser_vanilla_count(game_path)

        # Clamp selection
        selected_idx = max(0, min(selected_idx, total - 1)) if total else 0

        # Adjust scroll
        if total > 0:
            if selected_idx < scroll_top:
                scroll_top = selected_idx
            if selected_idx >= scroll_top + page_size:
                scroll_top = selected_idx - page_size + 1

        # Get trainer details for highlighted map
        trainer_details = []
        if 0 <= selected_idx < total:
            trainer_details = _map_browser_trainer_detail(
                rows[selected_idx]["name"], game_path, all_trainers)

        trainer_count_display, slots_remaining = _map_browser_slot_count(opponents_path)

        _map_browser_render(
            rows, selected_idx, scroll_top, page_size,
            show_vanilla, vanilla_count, trainer_details,
            NK_UP, NK_DOWN, NK_SCROLL, proj_name,
            trainer_count_display, slots_remaining)

        raw = input(f"  {GOLD}>{RST} ")
        raw = raw.rstrip("\n")

        result = _map_browser_handle_input(
            raw, rows, selected_idx, scroll_top, show_vanilla,
            NK_SCROLL, NK_UP, NK_DOWN)

        if result is None:
            return
        if result == "flat":
            _list_all_trainers(battles, opponents_path, trainers_h_path,
                               trainer_parties_path, project_dir, game_path,
                               workspace_expanded, settings, fmt=fmt)
            battles = _scan_custom_battles(project_dir)
            all_trainers = _load_all_trainers(opponents_path, party_path, battles)
            continue
        if result == "new":
            _run_new_battle_wizard([], project_dir, game_path, workspace_expanded,
                                   settings, emotes_conf=emotes_conf,
                                   source_display=source_display, fmt=fmt,
                                   proj_name=proj_name)
            battles = _scan_custom_battles(project_dir)
            all_trainers = _load_all_trainers(opponents_path, party_path, battles)
            continue
        if result == "select":
            if trainer_details:
                pick = _map_browser_pick_trainer(trainer_details)
                if pick is not None:
                    battles, all_trainers = _list_handle_open(
                        trainer_details, pick, fmt, opponents_path, trainers_h_path,
                        trainer_parties_path, party_path, project_dir, game_path,
                        workspace_expanded, settings, battles)
            continue

        selected_idx, scroll_top, show_vanilla = result


# ============================================================
# TRAINER DELETION
# ============================================================

def _delete_trainer(trainer_const, party_const,
                    opponents_path, trainers_h_path, trainer_parties_path, pory_path,
                    game_path=None, workspace_expanded=None, record=None):
    """
    Remove a trainer from all three game files and delete the workspace .pory file.
    If game_path provided, scans for all references and writes a deletion report.
    Recalculates TRAINERS_COUNT after removal.
    """
    errors = []
    auto_cleaned = []
    refs = []

    # Pre-scan all references (before any deletion)
    if game_path:
        refs = _scan_all_references(trainer_const, game_path)

    # opponents.h: remove #define TRAINER_CONST N line
    if os.path.exists(opponents_path):
        with open(opponents_path) as f:
            lines = f.readlines()
        new_lines = [l for l in lines if not re.match(r"^#define\s+" + re.escape(trainer_const) + r"\s+", l)]
        if len(new_lines) == len(lines):
            errors.append(f"  WARNING: {trainer_const} define not found in opponents.h")
        else:
            with open(opponents_path, "w") as f:
                f.writelines(new_lines)
            auto_cleaned.append(("opponents.h", f"Removed #define {trainer_const}"))
            print(f"  Removed from opponents.h")
            # Recalculate TRAINERS_COUNT
            new_count = _recalculate_trainers_count(opponents_path)
            auto_cleaned.append(("TRAINERS_COUNT", f"Recalculated to {new_count}"))
            print(f"  TRAINERS_COUNT recalculated to {new_count}")
    else:
        errors.append(f"  WARNING: opponents.h not found")

    # trainers.h: remove the [TRAINER_CONST] = { ... }, block
    if os.path.exists(trainers_h_path):
        with open(trainers_h_path) as f:
            content = f.read()
        block_pattern = (
            r"\n?\s*\[" + re.escape(trainer_const) + r"\]\s*=\s*\n\s*\{"
            r".*?"
            r"\n\s*\},"
        )
        new_content, count = re.subn(block_pattern, "", content, flags=re.DOTALL)
        if count == 0:
            errors.append(f"  WARNING: [{trainer_const}] block not found in trainers.h")
        else:
            with open(trainers_h_path, "w") as f:
                f.write(new_content)
            auto_cleaned.append(("trainers.h", f"Removed [{trainer_const}] gTrainers block"))
            print(f"  Removed from trainers.h")
    else:
        errors.append(f"  WARNING: trainers.h not found")

    # trainer_parties.h: remove the party array block
    if party_const and os.path.exists(trainer_parties_path):
        with open(trainer_parties_path) as f:
            content = f.read()
        pp = (
            r"static\s+const\s+struct\s+TrainerMon\s+" + re.escape(party_const)
            + r"\[\]\s*=\s*\{.*?\};\n?"
        )
        new_content, count = re.subn(pp, "", content, flags=re.DOTALL)
        if count == 0:
            errors.append(f"  WARNING: Party '{party_const}' not found in trainer_parties.h")
        else:
            with open(trainer_parties_path, "w") as f:
                f.write(new_content)
            auto_cleaned.append(("trainer_parties.h", f"Removed {party_const} party array"))
            print(f"  Removed from trainer_parties.h")
    elif not party_const:
        errors.append(f"  WARNING: Could not determine party const -- skipping trainer_parties.h")
    else:
        errors.append(f"  WARNING: trainer_parties.h not found")

    # workspace .pory (skip for vanilla trainers where pory_path is None)
    if pory_path:
        if os.path.exists(pory_path):
            os.remove(pory_path)
            auto_cleaned.append(("workspace", f"Deleted {os.path.basename(pory_path)}"))
            print(f"  Deleted: {pory_path}")
        else:
            errors.append(f"  WARNING: .pory file not found: {pory_path}")

    for e in errors:
        print(e)

    # Write deletion report
    if game_path and workspace_expanded and record:
        report_path = _write_deletion_report(trainer_const, record, refs,
                                             auto_cleaned, workspace_expanded)
        print()
        print(f"  Deletion report saved: {report_path}")


def _delete_trainer_party(trainer_const, party_path, opponents_path, pory_path,
                          game_path=None, workspace_expanded=None, record=None):
    """Remove a trainer from trainers.party + opponents.h + workspace .pory file."""
    errors = []
    auto_cleaned = []
    refs = []

    if game_path:
        refs = _scan_all_references(trainer_const, game_path)

    # opponents.h
    if os.path.exists(opponents_path):
        with open(opponents_path) as f:
            lines = f.readlines()
        new_lines = [l for l in lines if not re.match(r"^#define\s+" + re.escape(trainer_const) + r"\s+", l)]
        if len(new_lines) == len(lines):
            errors.append(f"  WARNING: {trainer_const} define not found in opponents.h")
        else:
            with open(opponents_path, "w") as f:
                f.writelines(new_lines)
            auto_cleaned.append(("opponents.h", f"Removed #define {trainer_const}"))
            print(f"  Removed from opponents.h")
            new_count = _recalculate_trainers_count(opponents_path)
            auto_cleaned.append(("TRAINERS_COUNT", f"Recalculated to {new_count}"))
            print(f"  TRAINERS_COUNT recalculated to {new_count}")
    else:
        errors.append(f"  WARNING: opponents.h not found")

    # trainers.party
    if os.path.exists(party_path):
        if _delete_from_party_file(party_path, trainer_const):
            auto_cleaned.append(("trainers.party", f"Removed === {trainer_const} === section"))
            print(f"  Removed from trainers.party")
        else:
            errors.append(f"  WARNING: === {trainer_const} === not found in trainers.party")
    else:
        errors.append(f"  WARNING: trainers.party not found")

    # workspace .pory (skip for vanilla trainers where pory_path is None)
    if pory_path:
        if os.path.exists(pory_path):
            os.remove(pory_path)
            auto_cleaned.append(("workspace", f"Deleted {os.path.basename(pory_path)}"))
            print(f"  Deleted: {pory_path}")
        else:
            errors.append(f"  WARNING: .pory file not found: {pory_path}")

    for e in errors:
        print(e)

    if game_path and workspace_expanded and record:
        report_path = _write_deletion_report(trainer_const, record, refs,
                                             auto_cleaned, workspace_expanded)
        print()
        print(f"  Deletion report saved: {report_path}")


# ============================================================
# TRAINER CARD FLOW — Extracted edit handlers
# ============================================================

def _handle_change_id(record, opponents_path, game_path):
    """Handle the 'change trainer ID' action."""
    trainer_const = record["trainer_const"]
    old_id = record["trainer_id"]
    if old_id is None:
        print("  ERROR: Could not determine current ID.")
        return
    print()
    print(f"  Current ID: {old_id}")
    id_raw = input(f"  Enter new ID (855+), or Enter to cancel > ").strip()
    if not id_raw:
        print("  Cancelled.")
        return
    try:
        new_id = int(id_raw)
    except ValueError:
        print("  Please enter a number.")
        return
    if new_id == old_id:
        print("  That's the same ID.")
        return
    result = _change_trainer_id(trainer_const, old_id, new_id, opponents_path)
    if result is True:
        print(f"  ID changed: {old_id} -> {new_id}")
        print("  TRAINERS_COUNT recalculated.")
        _offer_build(game_path)
    else:
        print(f"  ERROR: {result}")


def _handle_delete_flow(record, is_vanilla, pory_path, fmt, opponents_path,
                        trainers_h_path, trainer_parties_path, party_path,
                        game_path, workspace_expanded):
    """Handle the delete action. Returns True if trainer was deleted."""
    trainer_const = record["trainer_const"]
    party_const = record.get("party_const")
    print()

    if is_vanilla:
        print(f"  {GOLD}WARNING: This is a vanilla Emerald trainer.{RST}")
        print("  Deleting it may break vanilla game content (routes, events, scripts).")
        print("  This frees the trainer ID slot for a custom trainer.")
        print()

    print(f"  Delete {trainer_const}?")
    print()
    print("  Scanning for all references...")
    refs = _scan_all_references(trainer_const, game_path) if game_path else []
    print()

    print("  Will auto-remove:")
    print(f"    - opponents.h      : #define {trainer_const}")
    if fmt == "party":
        print(f"    - trainers.party   : === {trainer_const} === section")
    else:
        print(f"    - trainers.h       : [{trainer_const}] gTrainers block")
        if party_const:
            print(f"    - trainer_parties.h: {party_const} party array")
    if pory_path:
        print(f"    - workspace        : {os.path.basename(pory_path)}")
    try:
        tc_val, _, _ = _read_opponents_h(opponents_path)
        print(f"    - TRAINERS_COUNT   : will be recalculated (ID {record['trainer_id']} freed)")
    except SystemExit:
        pass
    print()

    skip_cats = {"opponents.h"}
    if fmt == "party":
        skip_cats.add("trainers.party")
    else:
        skip_cats.update({"trainers.h", "trainer_parties.h"})
    manual_refs = [r for r in refs if r["category"] not in skip_cats]
    if manual_refs:
        by_file = {}
        for r in manual_refs:
            by_file.setdefault(r["file"], []).append(r)
        print(f"  Manual cleanup needed in {len(by_file)} file(s) (see deletion report):")
        for fpath in sorted(by_file.keys()):
            count = len(by_file[fpath])
            print(f"    - {fpath}  ({count} reference{'s' if count != 1 else ''})")
    else:
        print("  No manual cleanup needed.")
    print()

    if workspace_expanded:
        ts_preview = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"  A detailed report will be saved to:")
        print(f"    config/deletion_reports/{trainer_const}_{ts_preview}.txt")
        print()

    confirm_name = record.get("trainer_name") or trainer_const
    confirm_del = input(f"  Type {confirm_name.upper()} to confirm deletion, or Enter to cancel > ").strip()
    if confirm_del.upper() == confirm_name.upper():
        print()
        print("  Deleting...")
        if fmt == "party":
            _delete_trainer_party(trainer_const, party_path, opponents_path,
                                 pory_path, game_path=game_path,
                                 workspace_expanded=workspace_expanded, record=record)
        else:
            _delete_trainer(trainer_const, party_const,
                            opponents_path, trainers_h_path, trainer_parties_path, pory_path,
                            game_path=game_path, workspace_expanded=workspace_expanded,
                            record=record)
        print()
        print("  Done. Deletion report saved.")
        print("  Review the report and fix manual cleanup items.")
        _offer_build(game_path)
        return True
    else:
        print()
        print("  Cancelled.")
    return False


def _handle_edit_name(record, fmt, party_path, trainers_h_path, pory_path, game_path):
    """Handle editing the trainer's display name."""
    trainer_const = record["trainer_const"]
    max_len = 10 if fmt == "party" else 7
    while True:
        new_name = input(f"  New display name (max {max_len} chars) > ").strip()
        if not new_name:
            print("  Cancelled.")
            break
        if len(new_name) > max_len:
            print(f"  '{new_name}' is {len(new_name)} characters -- limit is {max_len}.")
            continue
        yn = input(f"  Set name to '{new_name}'? [Y/n] > ").strip().lower()
        if yn not in ("", "y", "yes"):
            continue
        if fmt == "party":
            if _patch_party_file_field(party_path, trainer_const, "Name", new_name):
                print(f"  Updated Name to '{new_name}' in trainers.party")
                if pory_path and os.path.exists(pory_path):
                    os.utime(pory_path, None)
                _offer_build(game_path)
        else:
            if _patch_trainers_h_field(trainers_h_path, trainer_const,
                                       "trainerName", f'_("{new_name}")'):
                print(f"  Updated trainerName to '{new_name}' in trainers.h")
                _offer_build(game_path)
        break


def _handle_edit_class(record, fmt, party_path, trainers_h_path, pory_path,
                       game_path, constants_dir):
    """Handle editing the trainer class."""
    trainer_const = record["trainer_const"]
    class_set = _parse_defines(os.path.join(constants_dir, "trainers.h"), "TRAINER_CLASS_")
    while True:
        raw = input("  New trainer class > ").strip()
        if not raw:
            print("  Cancelled.")
            break
        up = raw.upper().replace(" ", "_").replace("-", "_")
        if not up.startswith("TRAINER_CLASS_"):
            up = "TRAINER_CLASS_" + up
        if class_set and up not in class_set:
            yn = input(f"  '{up}' not found in headers. Use anyway? [y/N] > ").strip().lower()
            if yn != "y":
                continue
        yn = input(f"  Set class to '{up}'? [Y/n] > ").strip().lower()
        if yn not in ("", "y", "yes"):
            continue
        if fmt == "party":
            human_class = _const_to_human_name(up, "TRAINER_CLASS_")
            if _patch_party_file_field(party_path, trainer_const, "Class", human_class):
                print(f"  Updated Class to '{human_class}' in trainers.party")
                if pory_path and os.path.exists(pory_path):
                    os.utime(pory_path, None)
                _offer_build(game_path)
        else:
            if _patch_trainers_h_field(trainers_h_path, trainer_const, "trainerClass", up):
                print(f"  Updated trainerClass to '{up}' in trainers.h")
                _offer_build(game_path)
        break


def _handle_edit_music(record, fmt, party_path, trainers_h_path, pory_path,
                       game_path, constants_dir, workspace_expanded, settings):
    """Handle editing encounter music."""
    trainer_const = record["trainer_const"]
    config_dir = os.path.join(workspace_expanded, "config")
    new_music = pick_encounter_music(config_dir, constants_dir, game_path,
                                     settings=settings)
    if new_music is None:
        new_music = "TRAINER_ENCOUNTER_MUSIC_SUSPICIOUS"
    yn = input(f"  Set music to '{new_music}'? [Y/n] > ").strip().lower()
    if yn in ("", "y", "yes"):
        if fmt == "party":
            human_music = _const_to_human_name(new_music, "TRAINER_ENCOUNTER_MUSIC_")
            if _patch_party_file_field(party_path, trainer_const, "Music", human_music):
                print(f"  Updated Music to '{human_music}' in trainers.party")
                if pory_path and os.path.exists(pory_path):
                    os.utime(pory_path, None)
                _offer_build(game_path)
        else:
            if _patch_trainers_h_field(trainers_h_path, trainer_const,
                                       "encounterMusic_gender", new_music):
                print(f"  Updated encounterMusic_gender to '{new_music}' in trainers.h")
                _offer_build(game_path)


def _handle_edit_sprite(record, fmt, party_path, trainers_h_path, pory_path,
                        game_path, constants_dir, workspace_expanded, settings):
    """Handle editing trainer sprite."""
    trainer_const = record["trainer_const"]
    config_dir = os.path.join(workspace_expanded, "config")
    new_pic = pick_trainer_sprite(config_dir, constants_dir, game_path,
                                  settings=settings)
    if new_pic is None:
        new_pic = "TRAINER_PIC_HIKER"
    yn = input(f"  Set sprite to '{new_pic}'? [Y/n] > ").strip().lower()
    if yn in ("", "y", "yes"):
        if fmt == "party":
            human_pic = _const_to_human_name(new_pic, "TRAINER_PIC_")
            if _patch_party_file_field(party_path, trainer_const, "Pic", human_pic):
                print(f"  Updated Pic to '{human_pic}' in trainers.party")
                if pory_path and os.path.exists(pory_path):
                    os.utime(pory_path, None)
                _offer_build(game_path)
        else:
            if _patch_trainers_h_field(trainers_h_path, trainer_const,
                                       "trainerPic", new_pic):
                print(f"  Updated trainerPic to '{new_pic}' in trainers.h")
                _offer_build(game_path)


def _handle_edit_battle_type(record, fmt, party_path, trainers_h_path, pory_path, game_path):
    """Handle editing battle type (single/double)."""
    trainer_const = record["trainer_const"]
    while True:
        bt = input("  Single or Double? [s/d] > ").strip().lower()
        if bt in ("s", "single"):
            new_double = "FALSE"
            break
        elif bt in ("d", "double"):
            new_double = "TRUE"
            break
        else:
            print("  Please type s or d.")
    yn = input(f"  Set doubleBattle to {new_double}? [Y/n] > ").strip().lower()
    if yn in ("", "y", "yes"):
        if fmt == "party":
            human_val = "Yes" if new_double == "TRUE" else "No"
            if _patch_party_file_field(party_path, trainer_const, "Double Battle", human_val):
                print(f"  Updated Double Battle to '{human_val}' in trainers.party")
                if pory_path and os.path.exists(pory_path):
                    os.utime(pory_path, None)
                _offer_build(game_path)
        else:
            if _patch_trainers_h_field(trainers_h_path, trainer_const,
                                       "doubleBattle", new_double):
                print(f"  Updated doubleBattle to {new_double} in trainers.h")
                _offer_build(game_path)


def _handle_edit_ai(record, fmt, party_path, trainers_h_path, pory_path,
                    game_path, constants_dir, settings):
    """Handle editing AI flags."""
    trainer_const = record["trainer_const"]
    ai_set = _parse_defines(os.path.join(constants_dir, "battle_ai.h"), "AI_FLAG_")
    new_ai = _ai_flags_menu(ai_set, settings=settings, game_path=game_path)
    yn = input(f"  Set AI flags to '{new_ai}'? [Y/n] > ").strip().lower()
    if yn in ("", "y", "yes"):
        if fmt == "party":
            human_ai = _ai_flags_to_party_format(new_ai)
            if _patch_party_file_field(party_path, trainer_const, "AI", human_ai):
                print(f"  Updated AI in trainers.party")
                if pory_path and os.path.exists(pory_path):
                    os.utime(pory_path, None)
                _offer_build(game_path)
        else:
            if _patch_trainers_h_field(trainers_h_path, trainer_const,
                                       "aiFlags", new_ai):
                print(f"  Updated aiFlags in trainers.h")
                _offer_build(game_path)


def _mon_edit_species(mon, species_set):
    """Edit mon species. Returns True if changed."""
    sp_raw = input(f"  Species (current: {mon['species']}) > ").strip()
    if sp_raw:
        mon["species"] = _validate_and_prompt("Species", sp_raw, "SPECIES_", species_set)
        print(f"  Species updated to {mon['species']}.")
        return True
    return False


def _mon_edit_level(mon, level_cap):
    """Edit mon level. Returns True if changed."""
    while True:
        lvl_raw = input(f"  Level (current: {mon['level']}) > ").strip()
        if not lvl_raw:
            return False
        try:
            new_level = int(lvl_raw)
            if 1 <= new_level <= level_cap:
                mon["level"] = new_level
                return True
            print(f"  Level must be 1-{level_cap}.")
        except ValueError:
            print("  Please enter a number.")


def _mon_edit_held_item(mon, items_set):
    """Edit mon held item. Returns True if changed."""
    current_item = mon.get("held_item") or "(none)"
    held_raw = input(f"  Held item (current: {current_item}), Enter to keep, or 'c' to clear > ").strip()
    if held_raw.lower() == "c":
        mon["held_item"] = None
        print("  Held item cleared.")
        return True
    elif held_raw:
        mon["held_item"] = _validate_and_prompt("Held item", held_raw, "ITEM_", items_set)
        return True
    return False


def _mon_edit_moves(mon, moves_set):
    """Edit mon moves. Returns True if changed."""
    current_moves = ", ".join(mon["moves"]) if mon.get("moves") else "(none)"
    moves_input = input(f"  Moves (current: {current_moves}), comma-separated, or Enter to keep > ").strip()
    if moves_input:
        raw_moves = [mv.strip() for mv in moves_input.split(",") if mv.strip()]
        mon["moves"] = [_validate_and_prompt("Move", mv, "MOVE_", moves_set) for mv in raw_moves]
        return True
    return False


def _mon_edit_ability(mon, abilities_set, game_path):
    """Edit mon ability. Returns True if changed."""
    species_abilities = _parse_species_abilities(mon["species"], game_path)
    current_ability = mon.get("ability") or "(none)"
    if species_abilities:
        print(f"  Abilities for {mon['species']}:")
        slot_labels = ["Ability 1", "Ability 2", "Hidden"]
        for aidx, ab in enumerate(species_abilities, 1):
            slot = slot_labels[aidx - 1] if aidx <= 3 else f"Ability {aidx}"
            print(f"    [{aidx}] {ab}  ({slot})")
        print(f"    [c] Clear ability override")
        print(f"    [Enter] Keep current ({current_ability})")
        ab_raw = input("  Pick ability > ").strip().lower()
    else:
        ab_raw = input(f"  Ability (current: {current_ability}), or Enter to keep, or 'c' to clear > ").strip().lower()

    if ab_raw == "c":
        mon["ability"] = None
        return True
    elif ab_raw.isdigit() and species_abilities:
        ab_idx = int(ab_raw) - 1
        if 0 <= ab_idx < len(species_abilities):
            mon["ability"] = species_abilities[ab_idx]
            return True
    elif ab_raw:
        mon["ability"] = _validate_and_prompt("Ability", ab_raw, "ABILITY_", abilities_set)
        return True
    return False


def _mon_edit_nature(mon):
    """Edit mon nature (.party only). Returns True if changed."""
    natures = ["HARDY", "LONELY", "BRAVE", "ADAMANT", "NAUGHTY",
               "BOLD", "DOCILE", "RELAXED", "IMPISH", "LAX",
               "TIMID", "HASTY", "SERIOUS", "JOLLY", "NAIVE",
               "MODEST", "MILD", "QUIET", "BASHFUL", "RASH",
               "CALM", "GENTLE", "SASSY", "CAREFUL", "QUIRKY"]
    print("  Natures:")
    for ni, nat in enumerate(natures, 1):
        print(f"    [{ni:>2}] {nat.title()}")
    print(f"    [c] Clear nature")
    nat_raw = input("  Pick nature > ").strip()
    if nat_raw.lower() == "c":
        mon["nature"] = None
        return True
    elif nat_raw.isdigit():
        ni = int(nat_raw) - 1
        if 0 <= ni < len(natures):
            mon["nature"] = f"NATURE_{natures[ni]}"
            return True
    return False


def _mon_edit_ivs(mon):
    """Edit mon IVs (.party only). Returns True if changed."""
    current_ivs = _format_stat_spread(mon.get('ivs')) if mon.get('ivs') else '(default)'
    print(f"  Current IVs: {current_ivs}")
    print("  Enter IVs as: 31 HP / 31 Atk / 31 Def / 31 SpA / 31 SpD / 31 Spe")
    print("  Or 'c' to clear, or Enter to keep.")
    iv_raw = input("  IVs > ").strip()
    if iv_raw.lower() == "c":
        mon["ivs"] = None
        return True
    elif iv_raw:
        mon["ivs"] = _parse_stat_spread(iv_raw)
        return True
    return False


def _mon_edit_evs(mon):
    """Edit mon EVs (.party only). Returns True if changed."""
    current_evs = _format_stat_spread(mon.get('evs')) if mon.get('evs') else '(none)'
    print(f"  Current EVs: {current_evs}")
    print("  Enter EVs as: 252 Atk / 252 Spe / 6 HP")
    print("  Or 'c' to clear, or Enter to keep.")
    ev_raw = input("  EVs > ").strip()
    if ev_raw.lower() == "c":
        mon["evs"] = None
        return True
    elif ev_raw:
        mon["evs"] = _parse_stat_spread(ev_raw)
        return True
    return False


def _mon_edit_gender(mon):
    """Edit mon gender (.party only). Returns True if changed."""
    print("  [m] Male  [f] Female  [c] Clear (auto)")
    g_raw = input("  Gender > ").strip().lower()
    if g_raw in ("m", "male"):
        mon["gender"] = "male"
        return True
    elif g_raw in ("f", "female"):
        mon["gender"] = "female"
        return True
    elif g_raw == "c":
        mon["gender"] = None
        return True
    return False


def _mon_edit_shiny(mon):
    """Edit mon shiny flag (.party only). Returns True if changed."""
    sh = input("  Shiny? [y/n] > ").strip().lower()
    if sh in ("y", "yes"):
        mon["shiny"] = True
        return True
    elif sh in ("n", "no"):
        mon["shiny"] = None
        return True
    return False


def _handle_edit_party_mon(mon, fchoice, fmt, species_set, moves_set, items_set,
                           abilities_set, ability_names, move_names, game_path,
                           level_cap):
    """Handle editing a single field on a party mon. Returns True if the mon was modified."""
    # Base fields (both formats)
    base_handlers = {
        "1": lambda: _mon_edit_species(mon, species_set),
        "2": lambda: _mon_edit_level(mon, level_cap),
        "3": lambda: _mon_edit_held_item(mon, items_set),
        "4": lambda: _mon_edit_moves(mon, moves_set),
        "5": lambda: _mon_edit_ability(mon, abilities_set, game_path),
    }
    # Extended fields (.party format only)
    party_handlers = {
        "6": lambda: _mon_edit_nature(mon),
        "7": lambda: _mon_edit_ivs(mon),
        "8": lambda: _mon_edit_evs(mon),
        "9": lambda: _mon_edit_gender(mon),
        "10": lambda: _mon_edit_shiny(mon),
    }
    handler = base_handlers.get(fchoice)
    if handler is None and fmt == "party":
        handler = party_handlers.get(fchoice)
    if handler is not None:
        return handler()
    print("  Invalid choice.")
    return False


def _mon_field_submenu(mon, fmt, species_set, moves_set, items_set,
                       abilities_set, ability_names, move_names, game_path, level_cap):
    """Show the mon field editor and loop until the user exits. Returns True if any field changed."""
    dirty = False
    while True:
        clear_screen()
        species_display = _fmt_const_name(mon['species'], {})
        item_display = _fmt_const_name(mon['held_item'], {}) if mon.get('held_item') else '(none)'
        moves_display = ', '.join(_fmt_const_name(mv, move_names) for mv in mon['moves']) if mon.get('moves') else '(none)'
        ability_display = _fmt_const_name(mon['ability'], ability_names) if mon.get('ability') else '(none)'
        MON_BAR = "  " + "\u2501" * 49
        print()
        print(MON_BAR)
        print(f"   MON EDITOR \u2014 {species_display}")
        print(MON_BAR)
        print()
        print(f"  [1] Species   : {species_display}")
        print(f"  [2] Level     : {mon['level']}")
        print(f"  [3] Held item : {item_display}")
        print(f"  [4] Moves     : {moves_display}")
        print(f"  [5] Ability   : {ability_display}")
        if fmt == "party":
            nature_display = _const_to_nature_name(mon.get('nature')) if mon.get('nature') else '(none)'
            ivs_display = _format_stat_spread(mon.get('ivs')) if mon.get('ivs') else '(default)'
            evs_display = _format_stat_spread(mon.get('evs')) if mon.get('evs') else '(none)'
            gender_display = mon.get('gender', '(auto)') or '(auto)'
            shiny_display = 'Yes' if mon.get('shiny') else 'No'
            print(f"  [6] Nature    : {nature_display}")
            print(f"  [7] IVs       : {ivs_display}")
            print(f"  [8] EVs       : {evs_display}")
            print(f"  [9] Gender    : {gender_display}")
            print(f"  [10] Shiny    : {shiny_display}")
            print()
            fchoice = input("  Edit field [1-10] or Enter to go back > ").strip()
        else:
            print()
            fchoice = input("  Edit field [1-5] or Enter to go back > ").strip()
        if not fchoice:
            break

        if _handle_edit_party_mon(mon, fchoice, fmt, species_set, moves_set, items_set,
                                  abilities_set, ability_names, move_names, game_path,
                                  level_cap):
            dirty = True
    return dirty


def _handle_edit_party(record, fmt, party_path, trainers_h_path, trainer_parties_path,
                       pory_path, game_path, constants_dir, ability_names, move_names,
                       level_cap, settings):
    """Handle the party editor sub-menu."""
    trainer_const = record["trainer_const"]
    species_set  = _parse_defines(os.path.join(constants_dir, "species.h"), "SPECIES_")
    moves_set    = _parse_defines(os.path.join(constants_dir, "moves.h"), "MOVE_")
    items_set    = _parse_defines(os.path.join(constants_dir, "items.h"), "ITEM_")
    abilities_set = _parse_defines(os.path.join(game_path, "include", "constants", "abilities.h"), "ABILITY_")

    if fmt == "legacy":
        party_const = record["party_const"]
        if not party_const:
            print("  ERROR: Could not determine party const -- cannot update.")
            return

    mons = list(record["mons"])

    def _party_mon_summary(mon):
        shiny_mark = "\u2605 " if mon.get("shiny") else ""
        s = f"{shiny_mark}{_fmt_const_name(mon['species'], {})}  lv.{mon['level']}"
        if mon.get("held_item"):
            s += f" @ {_fmt_const_name(mon['held_item'], {})}"
        if mon.get("ability"):
            s += f"  [{_fmt_const_name(mon['ability'], ability_names)}]"
        if mon.get("moves"):
            s += f"  {{{', '.join(_fmt_const_name(mv, move_names) for mv in mon['moves'])}}}"
        return s

    trainer_name = record['trainer_name'] or '?'
    party_dirty = False
    while True:
        clear_screen()
        BAR = "  " + "\u2501" * 49
        print()
        print(BAR)
        print(f"   PARTY EDITOR \u2014 {trainer_name}")
        print(BAR)
        print()
        for idx, mon in enumerate(mons, 1):
            print(f"  [{idx}] {_party_mon_summary(mon)}")
        print()
        print("  [a] Add pokemon   [r #] Remove pokemon   [p] Paste Showdown   [Enter] Done")
        pchoice = input("  Pick a mon to edit, or command > ").strip().lower()

        if not pchoice:
            break

        if pchoice == "p":
            party_dirty = _handle_party_paste(mons, species_set, items_set,
                                              moves_set, abilities_set,
                                              _party_mon_summary) or party_dirty
            continue

        if pchoice == "a":
            if len(mons) >= 6:
                print("  Party is full (max 6).")
                continue
            party_dirty = _handle_party_add(mons, species_set, level_cap) or party_dirty
            continue

        if pchoice.startswith("r "):
            party_dirty = _handle_party_remove(pchoice, mons) or party_dirty
            continue

        try:
            mon_idx = int(pchoice) - 1
        except ValueError:
            print("  Invalid choice.")
            continue

        if not (0 <= mon_idx < len(mons)):
            print(f"  Please enter a number between 1 and {len(mons)}.")
            continue

        mon = mons[mon_idx]
        if _mon_field_submenu(mon, fmt, species_set, moves_set, items_set,
                              abilities_set, ability_names, move_names, game_path,
                              level_cap):
            party_dirty = True

    if party_dirty:
        if fmt == "party":
            if _replace_party_in_party_file(party_path, trainer_const, mons):
                print(f"  Party saved to trainers.party.")
                if pory_path and os.path.exists(pory_path):
                    os.utime(pory_path, None)
                _offer_build(game_path)
            else:
                input("  Press Enter to continue > ")
        else:
            party_const = record["party_const"]
            if _replace_party(trainer_parties_path, party_const, mons):
                print(f"  Party saved to trainer_parties.h.")
                _offer_build(game_path)
            else:
                input("  Press Enter to continue > ")


def _handle_party_paste(mons, species_set, items_set, moves_set, abilities_set,
                        summary_fn):
    """Handle pasting a Showdown team into the party editor. Returns True if party changed."""
    print()
    print("  Paste a Showdown team export below.")
    print("  End with a blank line or '.' on its own line:")
    paste_lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        if line.strip() == "":
            if paste_lines and paste_lines[-1].strip() == "":
                break
            paste_lines.append(line)
        else:
            paste_lines.append(line)
    paste_text = "\n".join(paste_lines)
    if paste_text.strip():
        parsed = _parse_showdown_team(paste_text, species_set, items_set,
                                       moves_set, abilities_set)
        if parsed:
            print()
            print(f"  Parsed {len(parsed)} Pokemon:")
            for pi, pm in enumerate(parsed, 1):
                print(f"  [{pi}] {summary_fn(pm)}")
            print()
            yn = input("  Replace current party with this team? [Y/n] > ").strip().lower()
            if yn in ("", "y", "yes"):
                mons[:] = parsed
                print("  Party replaced.")
                return True
            else:
                print("  Cancelled.")
        else:
            print("  Could not parse any Pokemon from paste.")
    else:
        print("  Empty paste, cancelled.")
    return False


def _handle_party_add(mons, species_set, level_cap):
    """Handle adding a new pokemon to the party. Returns True if party changed."""
    print()
    sp_raw = input("  New pokemon species > ").strip()
    if not sp_raw:
        print("  Cancelled.")
        return False
    new_species = _validate_and_prompt("Species", sp_raw, "SPECIES_", species_set)
    while True:
        lvl_raw = input(f"  Level (1-{level_cap}) > ").strip()
        try:
            new_level = int(lvl_raw)
            if 1 <= new_level <= level_cap:
                break
            print(f"  Level must be 1-{level_cap}.")
        except ValueError:
            print(f"  Please enter a number.")
    mons.append({"species": new_species, "level": new_level,
                 "held_item": None, "moves": ["MOVE_TACKLE"], "ability": None})
    print(f"  Added {new_species} lv.{new_level}. Edit it to set more fields.")
    return True


def _handle_party_remove(pchoice, mons):
    """Handle removing a pokemon from the party. Returns True if party changed."""
    try:
        rm_idx = int(pchoice[2:].strip()) - 1
        if 0 <= rm_idx < len(mons):
            if len(mons) <= 1:
                print("  At least one Pokemon is required.")
            else:
                removed = mons.pop(rm_idx)
                print(f"  Removed {removed['species']}.")
                return True
        else:
            print(f"  No mon #{rm_idx + 1}.")
    except (ValueError, IndexError):
        print("  Usage: r 2  (to remove mon #2)")
    return False


def _handle_edit_dialogue(record, pory_path, game_path, settings):
    """Handle editing trainer dialogue."""
    textbox_warning = settings["textbox_warning"]
    print(" Re-enter battle dialogue.")
    print()
    is_double = record["is_double"]
    print(" INTRO -- What does the trainer shout when they spot the player?")
    print()
    new_intro = _dialogue_prompt("Intro line", is_double, textbox_warning)
    print()
    print(" DEFEAT -- What do they say after losing?")
    print()
    new_defeat = _dialogue_prompt("Defeat line", is_double, textbox_warning)
    new_not_enough = None
    if is_double:
        print()
        print(" NOT ENOUGH POKEMON -- What if the player only has one Pokemon?")
        print()
        new_not_enough = _dialogue_prompt("Not-enough line", is_double, textbox_warning)
    yn = input("  Write updated dialogue? [Y/n] > ").strip().lower()
    if yn not in ("", "y", "yes"):
        print("  Cancelled.")
        return

    # Read existing file to preserve TODO comments at top
    existing_lines = []
    if os.path.exists(pory_path):
        with open(pory_path) as f:
            for line in f:
                if line.startswith("//"):
                    existing_lines.append(line.rstrip())
                else:
                    break

    # Derive label base from the existing pory file text blocks or from the trainer const
    label_base = None
    if os.path.exists(pory_path):
        with open(pory_path) as f:
            old_content = f.read()
        lm = re.search(r'text\s+(\w+)_Intro\b', old_content)
        if lm:
            label_base = lm.group(1) + "_" + lm.group(1).split("_")[-1]
            lm2 = re.search(r'text\s+(\S+)_Intro\b', old_content)
            if lm2:
                label_base = lm2.group(1)

    if not label_base:
        stem = record["trainer_const"].replace("TRAINER_", "").title().replace("_", "")
        label_base = stem

    pory_out = []
    for cl in existing_lines:
        pory_out.append(cl)
    if existing_lines:
        pory_out.append("")
    pory_out.append(f"text {label_base}_Intro {{")
    pory_out.append(f'    "{new_intro}$"')
    pory_out.append("}")
    pory_out.append("")
    pory_out.append(f"text {label_base}_Defeat {{")
    pory_out.append(f'    "{new_defeat}$"')
    pory_out.append("}")
    if is_double and new_not_enough:
        pory_out.append("")
        not_enough_label = label_base + "_NotEnough"
        if os.path.exists(pory_path):
            with open(pory_path) as f:
                oc = f.read()
            nem = re.search(r'text\s+(\S+NotEnough\S*)\s*\{', oc, re.IGNORECASE)
            if nem:
                not_enough_label = nem.group(1)
        pory_out.append(f"text {not_enough_label} {{")
        pory_out.append(f'    "{new_not_enough}$"')
        pory_out.append("}")
    pory_out.append("")
    with open(pory_path, "w") as f:
        f.write("\n".join(pory_out))
    print(f"  Written: {pory_path}")
    print("  Run: torch sync to update the game files.")


def _handle_edit_items(record, fmt, party_path, pory_path, game_path, constants_dir):
    """Handle editing trainer bag items (.party format only)."""
    trainer_const = record["trainer_const"]
    current_items = record.get("trainer_items") or []
    if current_items:
        print(f"  Current items: {', '.join(_const_to_item_name(it) for it in current_items)}")
    else:
        print("  Current items: (none)")
    print("  Enter up to 4 items, comma-separated (e.g. 'Full Restore, Hyper Potion')")
    print("  Or 'c' to clear, or Enter to keep.")
    items_raw = input("  Items > ").strip()
    if items_raw.lower() == "c":
        _patch_party_file_field(party_path, trainer_const, "Items", "")
        print("  Items cleared.")
        if pory_path and os.path.exists(pory_path):
            os.utime(pory_path, None)
        _offer_build(game_path)
    elif items_raw:
        items_set_edit = _parse_defines(os.path.join(constants_dir, "items.h"), "ITEM_")
        raw_items = [it.strip() for it in items_raw.split(",") if it.strip()][:4]
        item_consts = [_validate_and_prompt("Item", it, "ITEM_", items_set_edit) for it in raw_items]
        human_items = " / ".join(_const_to_item_name(it) for it in item_consts)
        if _patch_party_file_field(party_path, trainer_const, "Items", human_items):
            print(f"  Updated Items in trainers.party")
            if pory_path and os.path.exists(pory_path):
                os.utime(pory_path, None)
            _offer_build(game_path)


# ============================================================
# TRAINER CARD FLOW — View/edit/delete trainer details
# ============================================================

def _trainer_card_flow(record, map_folder, pory_path,
                       project_dir, game_path, workspace_expanded,
                       settings=None, fmt=None, jump_to_delete=False):
    """
    Show the trainer card and handle edit/delete actions.
    Loops until user presses Enter to go back.
    When pory_path is None, the card is read-only (vanilla trainer).
    When jump_to_delete is True, skip straight to the delete flow.
    """
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if fmt is None:
        fmt = _detect_trainer_format(game_path)
    level_cap = settings["level_cap"]
    opponents_path = os.path.join(game_path, "include", "constants", "opponents.h")
    trainers_h_path = os.path.join(game_path, "src", "data", "trainers.h")
    trainer_parties_path = os.path.join(game_path, "src", "data", "trainer_parties.h")
    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    constants_dir = os.path.join(game_path, "include", "constants")

    is_vanilla = pory_path is None

    # Load name lookup tables once for this session
    ability_names = _parse_ability_names(game_path)
    move_names = _parse_move_names(game_path)
    trainer_const = record["trainer_const"]

    while True:
        # Re-read record and dialogue on each loop iteration (reflects edits)
        record = _read_record_dispatch(
            trainer_const, fmt, opponents_path, trainers_h_path,
            trainer_parties_path, party_path
        )
        # Safety net: if record became orphaned mid-session, bail out
        if _is_orphaned_trainer(record):
            if not is_vanilla:
                _handle_orphan_prompt(trainer_const, pory_path)
            return
        dialogue = _read_pory_dialogue(pory_path) if pory_path else {}
        _display_trainer_card(record, map_folder, dialogue, ability_names, move_names, fmt=fmt)
        print()

        if jump_to_delete:
            choice = "d"
            jump_to_delete = False  # Only auto-trigger once
        elif is_vanilla:
            choice = input("  (d)elete, or Enter to go back > ").strip().lower()
        elif fmt == "party":
            choice = input("  Edit [1-9], (i)d, (d)elete, or Enter to go back > ").strip().lower()
        else:
            choice = input("  Edit [1-8], (i)d, (d)elete, or Enter to go back > ").strip().lower()

        if not choice:
            return

        # Block edits and ID changes for vanilla trainers
        if is_vanilla and choice not in ("d",):
            print("  Vanilla trainers are read-only. Use (d) to delete.")
            input("  Press Enter > ")
            continue

        # --- Change ID ---
        if choice == "i":
            _handle_change_id(record, opponents_path, game_path)
            continue

        # --- Delete ---
        if choice == "d":
            deleted = _handle_delete_flow(record, is_vanilla, pory_path, fmt,
                                          opponents_path, trainers_h_path,
                                          trainer_parties_path, party_path,
                                          game_path, workspace_expanded)
            if deleted:
                return
            continue

        # --- Edit sections (dispatch table) ---
        section_handlers = {
            "1": lambda: _handle_edit_name(record, fmt, party_path, trainers_h_path, pory_path, game_path),
            "2": lambda: _handle_edit_class(record, fmt, party_path, trainers_h_path, pory_path, game_path, constants_dir),
            "3": lambda: _handle_edit_music(record, fmt, party_path, trainers_h_path, pory_path, game_path, constants_dir, workspace_expanded, settings),
            "4": lambda: _handle_edit_sprite(record, fmt, party_path, trainers_h_path, pory_path, game_path, constants_dir, workspace_expanded, settings),
            "5": lambda: _handle_edit_battle_type(record, fmt, party_path, trainers_h_path, pory_path, game_path),
            "6": lambda: _handle_edit_ai(record, fmt, party_path, trainers_h_path, pory_path, game_path, constants_dir, settings),
            "7": lambda: _handle_edit_party(record, fmt, party_path, trainers_h_path, trainer_parties_path, pory_path, game_path, constants_dir, ability_names, move_names, level_cap, settings),
            "8": lambda: _handle_edit_dialogue(record, pory_path, game_path, settings),
        }
        if fmt == "party":
            section_handlers["9"] = lambda: _handle_edit_items(record, fmt, party_path, pory_path, game_path, constants_dir)
        handler = section_handlers.get(choice)
        if handler is None:
            print("  Invalid choice.")
            continue
        print()
        handler()

        print()


# ============================================================
# BATTLE MANAGER MENU — Extracted helpers
# ============================================================

def _menu_find_by_id(opponents_path, battles, fmt, trainers_h_path,
                     trainer_parties_path, party_path, project_dir, game_path,
                     workspace_expanded, settings):
    """Handle the 'find by ID' flow in the battle manager menu."""
    print()
    id_raw = input("  Enter trainer ID > ").strip()
    try:
        target_id = int(id_raw)
    except ValueError:
        print("  Please enter a number.")
        print()
        return
    # Build id -> const map
    defines = {}
    if os.path.exists(opponents_path):
        with open(opponents_path) as f:
            for line in f:
                m = re.match(r"^#define\s+(TRAINER_\w+)\s+(\d+)", line)
                if m:
                    defines[int(m.group(2))] = m.group(1)
    if target_id not in defines:
        print(f"  No trainer with ID {target_id}")
        print()
        return
    found_const = defines[target_id]
    matching = [b for b in battles if b["trainer_const"] == found_const]
    if matching:
        b = matching[0]
        rec = _read_record_dispatch(found_const, fmt, opponents_path, trainers_h_path,
                                    trainer_parties_path, party_path)
        if _is_orphaned_trainer(rec):
            _handle_orphan_prompt(found_const, b["pory_path"])
        else:
            _trainer_card_flow(rec, b["map_folder"], b["pory_path"],
                               project_dir, game_path, workspace_expanded,
                               settings, fmt=fmt)
    else:
        rec = _read_record_dispatch(found_const, fmt, opponents_path, trainers_h_path,
                                    trainer_parties_path, party_path)
        if rec:
            _trainer_card_flow(rec, "vanilla", None,
                               project_dir, game_path, workspace_expanded,
                               settings, fmt=fmt)
        else:
            print(f"  Could not load data for {found_const}.")
            print()


def _menu_open_numeric(choice, recent, fmt, opponents_path, trainers_h_path,
                       trainer_parties_path, party_path, project_dir, game_path,
                       workspace_expanded, settings):
    """Handle numeric trainer selection in the battle manager menu."""
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(recent):
            b = recent[idx]
            rec = _read_record_dispatch(b["trainer_const"], fmt, opponents_path,
                                        trainers_h_path, trainer_parties_path, party_path)
            if _is_orphaned_trainer(rec):
                _handle_orphan_prompt(b["trainer_const"], b["pory_path"])
            else:
                _trainer_card_flow(rec, b["map_folder"], b["pory_path"],
                                   project_dir, game_path, workspace_expanded,
                                   settings, fmt=fmt)
        else:
            print(f"  Please enter a number between 1 and {len(recent)}.")
            print()
    except ValueError:
        print("  Invalid choice.")
        print()


def _menu_render_recent(recent, fmt, opponents_path, trainers_h_path,
                        trainer_parties_path, party_path):
    """Render the recent trainers section of the battle manager menu."""
    if recent:
        print(f"  {WHITE}Recent trainers:{RST}")
        print()
        for i, b in enumerate(recent, 1):
            tc = b["trainer_const"]
            mf = b["map_folder"]
            rec = _read_record_dispatch(tc, fmt, opponents_path, trainers_h_path,
                                        trainer_parties_path, party_path)
            if _is_orphaned_trainer(rec):
                print(f"  {_k(i)} {DIM}[ORPHAN]  {mf}{RST}")
            else:
                name_str = rec["trainer_name"].title() if rec and rec.get("trainer_name") else "?"
                class_str = _fmt_class(rec["trainer_class"]) if rec else "?"
                tid = rec.get("trainer_id")
                tid_str = f"#{tid}" if tid is not None else ""
                print(f"  {_k(i)} {WHITE}{class_str} {name_str}{RST}  {DIM}{tid_str}  {mf}{RST}")
                if rec.get("mons"):
                    party_parts = []
                    for mon in rec["mons"]:
                        species = _fmt_const_name(mon["species"], {})
                        party_parts.append(f"{species} lv.{mon['level']}")
                    print(f"        {DIM}{', '.join(party_parts)}{RST}")
        print()
    else:
        print(f"  {DIM}No custom trainers found in workspace.{RST}")


# ============================================================
# BATTLE MANAGER MENU — Top-level Trainers menu
# ============================================================

def battle_manager_menu(args, project_dir, game_path, workspace_expanded,
                        settings=None, emotes_conf=None, source_display=None, fmt=None,
                        proj_name=None):
    """Top-level Trainers menu."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if fmt is None:
        fmt = _detect_trainer_format(game_path)
    opponents_path = os.path.join(game_path, "include", "constants", "opponents.h")
    trainers_h_path = os.path.join(game_path, "src", "data", "trainers.h")
    trainer_parties_path = os.path.join(game_path, "src", "data", "trainer_parties.h")
    party_path = os.path.join(game_path, "src", "data", "trainers.party")

    fmt_label = "trainers.party" if fmt == "party" else "legacy .h format"

    while True:
        clear_screen()
        battles = _scan_custom_battles(project_dir)
        recent = battles[:8]

        # Refresh slot count each iteration (may change after deletions)
        slots_remaining = "?"
        trainer_count_display = "?"
        try:
            trainers_count, max_trainers, opp_lines = _read_opponents_h(opponents_path)
            if max_trainers:
                # Count actual trainer defines (not TRAINERS_COUNT/MAX_TRAINERS_COUNT/TRAINER_NONE)
                meta = {"TRAINERS_COUNT", "MAX_TRAINERS_COUNT", "TRAINER_NONE"}
                used = sum(1 for ln in opp_lines
                           if re.match(r"^#define\s+(TRAINER_\w+)\s+\d+", ln)
                           and re.match(r"^#define\s+(TRAINER_\w+)\s+\d+", ln).group(1) not in meta)
                slots_remaining = max_trainers - used - 1  # -1 for TRAINER_NONE at 0
                trainer_count_display = used
        except SystemExit:
            pass


        print_logo(f"Trainers  v{BATTLE_VERSION}", proj_name)
        print(BAR)
        slots_col = GREEN if isinstance(slots_remaining, int) and slots_remaining > 5 else CYAN
        print(f"   {WHITE}{trainer_count_display}{RST} {DIM}registered{RST}  {DIM}|{RST}  {slots_col}{slots_remaining}{RST} {DIM}slots free{RST}")
        print(BAR)

        _menu_render_recent(recent, fmt, opponents_path, trainers_h_path,
                            trainer_parties_path, party_path)
        print()
        if fmt == "legacy":
            print(f"  {_k('l')} {DIM}List{RST}   {_k('n')} {DIM}New{RST}   {_k('f')} {DIM}Find{RST}   {_k('p')} {DIM}Partners{RST}   {_k('r')} {DIM}Recover{RST}   {_k('m')} {DIM}Migrate{RST}   {_k('q')} {DIM}Quit{RST}")
        else:
            print(f"  {_k('l')} {DIM}List{RST}   {_k('n')} {DIM}New{RST}   {_k('f')} {DIM}Find{RST}   {_k('p')} {DIM}Partners{RST}   {_k('r')} {DIM}Recover{RST}   {_k('q')} {DIM}Quit{RST}")
        print()
        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if choice == "q" or choice == "":
            return

        if choice == "n":
            print()
            _run_new_battle_wizard(args, project_dir, game_path, workspace_expanded,
                                   settings, emotes_conf=emotes_conf,
                                   source_display=source_display, fmt=fmt,
                                   proj_name=proj_name)
            continue

        if choice == "l":
            _list_all_trainers(battles, opponents_path, trainers_h_path, trainer_parties_path,
                               project_dir, game_path, workspace_expanded, settings, fmt=fmt)
            continue

        if choice == "f":
            _menu_find_by_id(opponents_path, battles, fmt, trainers_h_path,
                             trainer_parties_path, party_path, project_dir, game_path,
                             workspace_expanded, settings)
            continue

        if choice == "p":
            from torch.battle_partners import partner_menu
            from torch.expansion_compat import detect_expansion_version
            ev = detect_expansion_version(game_path)
            partner_menu(game_path, expansion_version=ev, settings=settings,
                         proj_name=proj_name)
            continue

        if choice == "r":
            _recovery_scan(project_dir, game_path, workspace_expanded)
            continue

        if choice == "m" and fmt == "legacy":
            _run_battle_format_migrator(game_path)
            # Re-detect format after migration
            fmt = _detect_trainer_format(game_path)
            fmt_label = "trainers.party" if fmt == "party" else "legacy .h format"
            continue

        # Numeric: open trainer card
        _menu_open_numeric(choice, recent, fmt, opponents_path, trainers_h_path,
                           trainer_parties_path, party_path, project_dir, game_path,
                           workspace_expanded, settings)


def battle_command(args, project_dir, game_path, workspace_expanded, settings=None,
                   emotes_conf=None, source_display=None, proj_name=None):
    """Entry point for torch battle — opens the Trainers module."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if proj_name is None:
        proj_name = os.path.basename(project_dir) or None
    _set_terminal_title("TORCH \u2014 Trainers")
    # Battle Manager requires pokeemerald-expansion (different trainer struct + opponents.h)
    if _detect_project_variant(game_path) == "vanilla":
        clear_screen()
        print()
        print("  \u2718 Battle Manager requires pokeemerald-expansion.")
        print()
        print("  This project appears to be vanilla pokeemerald, which uses a different")
        print("  trainer struct that TORCH does not support. Battle Manager is designed")
        print("  for pokeemerald-expansion projects only.")
        print()
        print("  If this is an expansion project, check that game_path in your config")
        print("  points to the correct directory.")
        print()
        input("  Press Enter to return > ")
        return
    # Direct subcommand: torch battle migrate
    if args and args[0] == "migrate":
        _run_battle_format_migrator(game_path, proj_name=proj_name)
        return
    fmt = _detect_trainer_format(game_path)
    battle_manager_menu(args, project_dir, game_path, workspace_expanded, settings,
                        emotes_conf=emotes_conf, source_display=source_display, fmt=fmt,
                        proj_name=proj_name)


# ============================================================
# NEW BATTLE WIZARD — Extracted step functions
# ============================================================

def _wizard_prompt_ability(species, game_path):
    """Prompt for an ability in the wizard. Returns ability const or None."""
    species_abilities = _parse_species_abilities(species, game_path)
    if species_abilities:
        print(f"  Abilities for {species}:")
        for idx, ab in enumerate(species_abilities, 1):
            slot = ["Ability 1", "Ability 2", "Hidden"][idx - 1] if idx <= 3 else f"Ability {idx}"
            print(f"    [{idx}] {ab}  ({slot})")
        print(f"    [Enter] Skip (no ability override)")
        ab_raw = input(f"  Pick ability > ").strip()
        if ab_raw.isdigit():
            ab_idx = int(ab_raw) - 1
            if 0 <= ab_idx < len(species_abilities):
                return species_abilities[ab_idx]
        elif ab_raw:
            return _validate_and_prompt("Ability", ab_raw, "ABILITY_",
                                        _parse_defines(os.path.join(game_path, "include", "constants", "abilities.h"), "ABILITY_"))
    else:
        ab_raw = input(f"  Ability  (e.g. STATIC)  or Enter to skip > ").strip()
        if ab_raw:
            return _validate_and_prompt("Ability", ab_raw, "ABILITY_",
                                        _parse_defines(os.path.join(game_path, "include", "constants", "abilities.h"), "ABILITY_"))
    return None


def _wizard_enter_mon(mon_num_label, species_set, items_set, moves_set,
                      abilities_set, game_path, settings, existing=None):
    """Prompt for one Pokemon's details. If existing is provided, pre-fill defaults."""
    print(f" --- Pokemon #{mon_num_label} ---")
    if existing:
        print(f"  Current: {existing['species']}  lv.{existing['level']}", end="")
        if existing.get("held_item"):
            print(f" @ {existing['held_item']}", end="")
        if existing.get("ability"):
            print(f"  [{existing['ability']}]", end="")
        if existing.get("moves"):
            print(f"  {{{', '.join(existing['moves'])}}}", end="")
        print()
        print()

    species_raw = input(f"  Name  (e.g. Koffing, Zubat) > ").strip()
    species = _validate_and_prompt("Name", species_raw, "SPECIES_", species_set)

    while True:
        level_cap = settings["level_cap"]
        level_raw = input(f"  Level  (1-{level_cap}) > ").strip()
        try:
            level = int(level_raw)
            if 1 <= level <= level_cap:
                break
            print(f"  Level must be between 1 and {level_cap}. You entered {level}.")
            print()
        except ValueError:
            print(f"  Please enter a number (e.g. 12).")
            print()

    held_raw = input(f"  Held item  (e.g. sitrus berry)  or Enter to skip > ").strip()
    held_item = None
    if held_raw:
        held_item = _validate_and_prompt("Held item", held_raw, "ITEM_", items_set)

    moves_input = input(f"  Moves  (e.g. Smog, Tackle)  comma-separated, or Enter to skip > ").strip()
    if moves_input:
        raw_moves = [m.strip() for m in moves_input.split(",") if m.strip()]
        moves = [_validate_and_prompt("Move", raw_m, "MOVE_", moves_set) for raw_m in raw_moves]
    else:
        moves = ["MOVE_TACKLE"]
        print(f"  (no moves entered — defaulting to MOVE_TACKLE)")

    ability = _wizard_prompt_ability(species, game_path)

    mon = {"species": species, "level": level, "held_item": held_item, "moves": moves, "ability": ability}
    if existing:
        for key in ("evs", "ivs", "nature", "shiny", "gender"):
            if existing.get(key) is not None:
                mon[key] = existing[key]

    # Show summary and confirm
    print()
    print(f"  Review: {species}  lv.{level}", end="")
    if held_item:
        print(f" @ {held_item}", end="")
    if ability:
        print(f"  [{ability}]", end="")
    print(f"  {{{', '.join(moves)}}}", end="")
    print()
    print()
    yn = input("  Looks good? [Y/re-enter] > ").strip().lower()
    if yn in ("", "y", "yes"):
        return mon
    print()
    return _wizard_enter_mon(mon_num_label, species_set, items_set, moves_set,
                             abilities_set, game_path, settings)  # re-enter same slot


def _wizard_print_team(mons):
    """Print the current team summary."""
    print()
    print("  Current team:")
    for i, mon in enumerate(mons):
        line = f"  [{i + 1}] {mon['species']}  lv.{mon['level']}"
        if mon.get("held_item"):
            line += f" @ {mon['held_item']}"
        if mon.get("ability"):
            line += f"  [{mon['ability']}]"
        if mon.get("moves"):
            line += f"  {{{', '.join(mon['moves'])}}}"
        print(line)
    print()


def _wizard_prompt_class(class_set):
    """Prompt for trainer class. Returns (trainer_class, trainer_class_is_custom)."""
    print()
    print(" TRAINER CLASS")
    print(" Their job title, shown before their name on the battle screen.")
    print(" e.g. 'Team Rocket' + 'Buster' appears as 'Team Rocket Buster'.")
    print()
    trainer_class_is_custom = False
    while True:
        raw_class = _battle_prompt("Trainer class", default="TRAINER_CLASS_TEAM_ROCKET")
        raw_class_up = raw_class.strip().upper().replace(" ", "_").replace("-", "_")
        if not raw_class_up.startswith("TRAINER_CLASS_"):
            trainer_class = f"TRAINER_CLASS_{raw_class_up}"
        else:
            trainer_class = raw_class_up
        if class_set and trainer_class not in class_set:
            print(f"  Warning: '{trainer_class}' not found in game headers.")
            print(f"  If this is a new class, you will need to add it to the game manually.")
            print(f"  TORCH will include instructions in your output file.")
            yn = input("  Use it anyway? [y/N] > ").strip().lower()
            if yn != "y":
                print("  Let's try again.")
                print()
                continue
            trainer_class_is_custom = True
        else:
            trainer_class_is_custom = False
        if _confirm_value("Trainer class", trainer_class):
            break
        print("  Let's try again.")
        print()
    return trainer_class, trainer_class_is_custom


def _wizard_prompt_display_name(trainer_class, fmt="party"):
    """Prompt for trainer display name, showing selected class in example."""
    max_len = 10 if fmt == "party" else 7
    class_display = _fmt_class(trainer_class)
    print()
    print(" DISPLAY NAME")
    print(f" Their name in battle dialogue (max {max_len} characters).")
    print(f" Example: {class_display} [NAME] wants to battle!")
    print()
    while True:
        trainer_name = _battle_prompt(f"Display name  (max {max_len} chars)")
        if len(trainer_name) > max_len:
            print(f"  '{trainer_name}' is {len(trainer_name)} characters -- the limit is {max_len}.")
            print(f"  Try something shorter, like '{trainer_name[:max_len]}'.")
            print()
            continue
        break
    return trainer_name


def _wizard_step_details(opponents_path, constants_dir, config_dir, game_path,
                         class_set, ai_set, settings, expansion_version=None,
                         fmt="party"):
    """Run step 1 of the wizard: trainer details. Returns a dict or None if cancelled."""
    # ---- Trainer ID & slot check ----
    trainers_count, max_trainers, wiz_opp_lines = _read_opponents_h(opponents_path)
    if max_trainers:
        meta = {"TRAINERS_COUNT", "MAX_TRAINERS_COUNT", "TRAINER_NONE"}
        used = sum(1 for ln in wiz_opp_lines
                   if re.match(r"^#define\s+(TRAINER_\w+)\s+\d+", ln)
                   and re.match(r"^#define\s+(TRAINER_\w+)\s+\d+", ln).group(1) not in meta)
        slots_remaining = max_trainers - used - 1
    else:
        slots_remaining = "?"
    new_trainer_id = _find_lowest_available_id(opponents_path)

    print()
    print(f"  Next trainer ID : {new_trainer_id}")
    print(f"  Slots remaining : {slots_remaining}  (before flag overflow)")
    print()

    if max_trainers and trainers_count >= max_trainers:
        print(" WARNING: You are at or past MAX_TRAINERS_COUNT.")
        print(" Continuing may cause flag overflow issues.")
        print()
        go = input("  Continue anyway? [y/N] > ").strip().lower()
        if go != "y":
            print(" Cancelled.")
            return None

    print(DIVIDER)
    print()
    print(" [ STEP 1 OF 4 ]  Trainer Details")
    print()

    # Codename
    print(" CODENAME")
    print(" A behind-the-scenes label the game uses to identify this trainer.")
    print(" The player never sees it. Don't worry about the format -- TORCH")
    print(" will clean it up automatically. Just type something like:")
    print()
    print("   rocket guy 1     youngster joey     rival 1")
    print()
    while True:
        raw_input_val = _battle_prompt("Codename")
        stripped_code = re.sub(r"^TRAINER_", "", raw_input_val.strip().upper())
        normalized = re.sub(r"[^A-Z0-9_]", "", re.sub(r"[\s\-\.]+", "_", stripped_code))
        normalized = normalized.strip("_")
        if not normalized:
            print("  That didn't produce a valid codename. Please try again.")
            print()
            continue
        raw_const = normalized
        trainer_const = f"TRAINER_{raw_const}"
        existing_trainers = _parse_defines(opponents_path, "TRAINER_")
        if trainer_const in existing_trainers:
            print(f"  '{trainer_const}' already exists in opponents.h. Choose a different name.")
            print()
            continue
        if _confirm_value("Will be registered as", trainer_const):
            break
        print("  Let's try again.")
        print()

    # Trainer class (before display name so the example can use it)
    trainer_class, trainer_class_is_custom = _wizard_prompt_class(class_set)

    # Display name (uses selected class for example)
    trainer_name = _wizard_prompt_display_name(trainer_class, fmt=fmt)

    # Encounter music
    print()
    print(" ENCOUNTER MUSIC")
    print(" The jingle that plays when this trainer spots the player.")
    print()
    encounter_music = pick_encounter_music(config_dir, constants_dir, game_path,
                                           settings=settings)
    if encounter_music is None:
        encounter_music = "TRAINER_ENCOUNTER_MUSIC_SUSPICIOUS"

    # Trainer sprite
    print()
    print(" TRAINER SPRITE")
    print(" Which character model this trainer uses in battle.")
    print()
    trainer_pic = pick_trainer_sprite(config_dir, constants_dir, game_path,
                                      settings=settings)
    if trainer_pic is None:
        trainer_pic = "TRAINER_PIC_HIKER"

    # Battle type
    print()
    print(" BATTLE TYPE")
    print()
    chosen_bt = _pick_battle_type(expansion_version)
    bt_name = chosen_bt[0]
    is_double = "double" in bt_name
    print(f"  -> {chosen_bt[3]}")
    print()

    # Trainer AI
    print()
    print(" TRAINER AI")
    print(" How smart this trainer is in battle.")
    print()
    ai_flags = _ai_flags_menu(ai_set, settings=settings, game_path=game_path)

    return {
        "raw_const": raw_const,
        "trainer_const": trainer_const,
        "trainer_name": trainer_name,
        "trainer_class": trainer_class,
        "trainer_class_is_custom": trainer_class_is_custom,
        "encounter_music": encounter_music,
        "trainer_pic": trainer_pic,
        "is_double": is_double,
        "battle_type_name": bt_name,
        "ai_flags": ai_flags,
        "new_trainer_id": new_trainer_id,
    }


def _wizard_manual_party_entry(mons, species_set, items_set, moves_set, settings):
    """Manual one-by-one Pokemon entry loop for the wizard. Returns the mons list."""
    print()
    print(" Just type the Pokemon's name -- you don't need to include SPECIES_.")
    print(" Press Enter with nothing typed when you're done adding Pokemon.")
    print()
    mon_num = len(mons) + 1
    while True:
        species_check = input(f"  Pokemon #{mon_num} name  (or Enter to finish) > ").strip()
        if not species_check:
            if not mons:
                print("  You need at least one Pokemon. Try again.")
                print()
                continue
            break
        print()
        print(f" --- Pokemon #{mon_num} ---")
        species = _validate_and_prompt("Name", species_check, "SPECIES_", species_set)

        while True:
            level_cap = settings["level_cap"]
            level_raw = input(f"  Level  (1-{level_cap}) > ").strip()
            try:
                level = int(level_raw)
                if 1 <= level <= level_cap:
                    break
                print(f"  Level must be between 1 and {level_cap}. You entered {level}.")
                print()
            except ValueError:
                print(f"  Please enter a number (e.g. 12).")
                print()

        held_raw = input(f"  Held item  (e.g. sitrus berry)  or Enter to skip > ").strip()
        held_item = None
        if held_raw:
            held_item = _validate_and_prompt("Held item", held_raw, "ITEM_", items_set)

        moves_input = input(f"  Moves  (e.g. Smog, Tackle)  comma-separated, or Enter to skip > ").strip()
        if moves_input:
            raw_moves = [m.strip() for m in moves_input.split(",") if m.strip()]
            moves = []
            for raw_m in raw_moves:
                validated_move = _validate_and_prompt("Move", raw_m, "MOVE_", moves_set)
                moves.append(validated_move)
        else:
            moves = ["MOVE_TACKLE"]
            print(f"  Defaulting to Tackle")

        mon = {"species": species, "level": level, "held_item": held_item, "moves": moves}

        print()
        print(f"  Review #{mon_num}: {species}  lv.{level}", end="")
        if held_item:
            print(f" @ {held_item}", end="")
        if moves:
            print(f"  [{', '.join(moves)}]", end="")
        print()
        print()
        yn = input("  Looks good? [Y/re-enter this pokemon] > ").strip().lower()
        if yn in ("", "y", "yes"):
            mons.append(mon)
            mon_num += 1
            print()
        else:
            print()
            print("  Let's redo that one.")
            print()
    return mons


def _wizard_step_party(species_set, items_set, moves_set, abilities_set,
                       game_path, settings):
    """Run step 2 of the wizard: build the Pokemon party. Returns list of mons."""
    print()
    print(DIVIDER)
    print()
    print(" [ STEP 2 OF 4 ]  Pokemon Party")
    print()
    print(" Enter Pokemon one at a time, or paste a Showdown team.")
    print()
    print("  [1] Enter manually")
    print("  [2] Paste Showdown team")
    print()
    party_mode = input("  Choose > ").strip()

    mons = []

    if party_mode == "2":
        print()
        print("  Paste a Showdown team export below.")
        print("  End with a blank line or '.' on its own line:")
        paste_lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == ".":
                break
            if line.strip() == "":
                if paste_lines and paste_lines[-1].strip() == "":
                    break
                paste_lines.append(line)
            else:
                paste_lines.append(line)
        paste_text = "\n".join(paste_lines)
        if paste_text.strip():
            mons = _parse_showdown_team(paste_text, species_set, items_set,
                                         moves_set, abilities_set)
        if not mons:
            print("  Could not parse any Pokemon. Switching to manual entry.")
            party_mode = "1"

    if party_mode != "2":
        mons = _wizard_manual_party_entry(mons, species_set, items_set, moves_set, settings)

    # Full team review with edit-by-number
    while True:
        _wizard_print_team(mons)
        print("  Enter a number to edit that Pokemon, or Enter to continue.")
        edit_raw = input("  Edit > ").strip()
        if not edit_raw:
            break
        try:
            edit_idx = int(edit_raw) - 1
            if 0 <= edit_idx < len(mons):
                print()
                updated = _wizard_enter_mon(edit_idx + 1, species_set, items_set, moves_set,
                                            abilities_set, game_path, settings,
                                            existing=mons[edit_idx])
                mons[edit_idx] = updated
            else:
                print(f"  Please enter a number between 1 and {len(mons)}.")
                print()
        except ValueError:
            print(f"  Please enter a number between 1 and {len(mons)}.")
            print()

    return mons


def _wizard_prompt_map(project_dir, game_path):
    """Show a numbered list of workspace maps, or fall back to typed input. Returns map name."""

    # Gather workspace map folders
    workspace_maps = []
    if os.path.isdir(project_dir):
        workspace_maps = sorted(
            d for d in os.listdir(project_dir)
            if os.path.isdir(os.path.join(project_dir, d)) and not d.startswith(".")
        )

    # Known game maps for validation
    maps_dir = os.path.join(game_path, "data", "maps")
    known_maps = set()
    if os.path.isdir(maps_dir):
        known_maps = set(os.listdir(maps_dir))

    print(" MAP NAME")
    print(" Which map will this trainer appear on?")
    print()

    if workspace_maps:
        for i, m in enumerate(workspace_maps, 1):
            print(f"  [{i}] {m}")
        print(f"  {DIM}[c] Custom (type a map name){RST}")
        print()

    while True:
        if workspace_maps:
            raw = input("  Choose > ").strip()
            if raw.lower() == "c":
                map_name_for_text = _wizard_prompt_map_typed(known_maps)
                break
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(workspace_maps):
                    map_name_for_text = workspace_maps[idx]
                    print(f"  -> {map_name_for_text}")
                    break
                print(f"  Please enter 1-{len(workspace_maps)} or 'c' for custom.")
                print()
                continue
            # Try as a typed name
            map_name_for_text = _wizard_validate_map_name(raw, known_maps)
            if map_name_for_text:
                break
        else:
            map_name_for_text = _wizard_prompt_map_typed(known_maps)
            break

    return map_name_for_text


def _wizard_prompt_map_typed(known_maps):
    """Free-text map name entry with validation. Returns map name."""
    print(' Type the map name naturally -- e.g. "lake elix south" -> LakeElixSouth')
    print()
    while True:
        raw = _battle_prompt("Map name")
        result = _wizard_validate_map_name(raw, known_maps)
        if result:
            return result


def _wizard_validate_map_name(raw, known_maps):
    """Validate and normalize a map name. Returns name or None if invalid."""
    map_name_for_text = _to_pascal_case(raw)
    if not map_name_for_text:
        print("  That didn't produce a valid map name. Please try again.")
        print()
        return None
    if not re.match(r"^[A-Za-z0-9_]+$", map_name_for_text):
        print("  Map names should only contain letters, numbers, and underscores.")
        print()
        return None
    if map_name_for_text != raw:
        print(f"  -> Map name: {map_name_for_text}")
        yn = input("     Is that correct? [Y/n] > ").strip().lower()
        if yn not in ("", "y", "yes"):
            print("  Let's try again.")
            print()
            return None
    if known_maps and map_name_for_text not in known_maps:
        suggestions = sorted([m for m in known_maps if map_name_for_text.lower() in m.lower()])[:4]
        print(f"  Warning: '{map_name_for_text}' is not a recognised map in data/maps/.")
        if suggestions:
            print(f"  Did you mean: {', '.join(suggestions)}?")
        print(f"  (If this is a brand-new map that doesn't exist yet, that's OK.)")
        yn = input("  Use it anyway? [y/N] > ").strip().lower()
        if yn != "y":
            print("  Let's try again.")
            print()
            return None
    return map_name_for_text


def _wizard_step_dialogue(raw_const, is_double, game_path, project_dir, settings):
    """Run step 3 of the wizard: map assignment + battle dialogue. Returns dict."""
    print()
    print(DIVIDER)
    print()
    print(" [ STEP 3 OF 4 ]  Map & Dialogue")
    print()

    const_stem = raw_const.title().replace("_", "")

    # Map selection
    map_name_for_text = _wizard_prompt_map(project_dir, game_path)

    text_label_base = f"{map_name_for_text}_{const_stem}"

    # Dialogue explanation before prompts
    print()
    print(" BATTLE DIALOGUE")
    print(" These are the text boxes the player sees during the battle.")
    print("   Intro:  What the trainer says when battle starts.")
    print("   Defeat: What the trainer says after losing.")
    print(" Use \\n to break to a new line, \\p to open a new text box.")
    print(" Long lines will be auto-wrapped and shown for your approval.")
    print()

    tw = settings["textbox_warning"]

    print(f" INTRO  (label: {text_label_base}_Intro)")
    print(" What does the trainer shout when they spot the player?")
    print()
    intro_text = _dialogue_prompt("Intro line", is_double, tw)

    print()
    print(f" DEFEAT  (label: {text_label_base}_Defeat)")
    print(" What do they say after losing the battle?")
    print()
    defeat_text = _dialogue_prompt("Defeat line", is_double, tw)

    not_enough_text = None
    not_enough_label = None
    after_label = None
    if is_double:
        not_enough_label = f"{text_label_base}_NotEnough"
        after_label = f"{text_label_base}_After"
        print()
        print(f" NOT ENOUGH POKEMON  (label: {not_enough_label})")
        print(" For double battles: what do they say if the player only has one Pokemon?")
        print()
        not_enough_text = _dialogue_prompt("Not-enough line", is_double, tw)

    return {
        "const_stem": const_stem,
        "map_name_for_text": map_name_for_text,
        "text_label_base": text_label_base,
        "intro_text": intro_text,
        "defeat_text": defeat_text,
        "not_enough_text": not_enough_text,
        "not_enough_label": not_enough_label,
        "after_label": after_label,
    }


def _wizard_step_script_output(details, dialogue, project_dir):
    """Run step 4: optional raw script data output. Returns script_output_path or None."""
    print()
    print(DIVIDER)
    print()
    print(" [ STEP 4 OF 4 ]  Script Output  (optional)")
    print()

    raw = input("  Advanced: Output trainer as raw script data? [y/N] > ").strip().lower()
    if raw != "y":
        return None

    trainer_const = details["trainer_const"]
    text_label_base = dialogue["text_label_base"]
    is_double = details["is_double"]
    not_enough_label = dialogue["not_enough_label"]
    after_label = dialogue["after_label"]

    tb_line = _wizard_build_tb_line(trainer_const, text_label_base, is_double,
                                    not_enough_label, after_label)

    # Write to Trainer Scripts/ directory
    scripts_dir = os.path.join(project_dir, "Trainer Scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    output_path = os.path.join(scripts_dir, f"{trainer_const}.txt")

    lines = []
    lines.append(f"// Trainer: {trainer_const}")
    lines.append(f"// Battle type: {'double' if is_double else 'single'}")
    lines.append(f"// Text labels: {text_label_base}_Intro, {text_label_base}_Defeat")
    if is_double and not_enough_label:
        lines.append(f"//               {not_enough_label}")
    lines.append("")
    lines.append(tb_line)
    lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    print(f"  Script data saved to: {output_path}")
    print()

    return output_path


def _wizard_build_tb_line(trainer_const, text_label_base, is_double,
                          not_enough_label, after_label):
    """Build the trainerbattle script line."""
    if is_double:
        return (f"trainerbattle_double {trainer_const}, "
                f"{text_label_base}_Intro, {text_label_base}_Defeat, "
                f"{not_enough_label}, {after_label}")
    return (f"trainerbattle_single {trainer_const}, "
            f"{text_label_base}_Intro, {text_label_base}_Defeat")


def _wizard_build_pory_content(trainer_class, trainer_class_is_custom,
                               text_label_base, intro_text, defeat_text,
                               is_double, not_enough_text, not_enough_label):
    """Build the .pory file content lines."""
    pory_lines = []
    if trainer_class_is_custom:
        pory_lines.append(f"// TODO: New trainer class '{trainer_class}' needs to be added to the game.")
        pory_lines.append(f"//")
        pory_lines.append(f"// 1. In include/constants/trainers.h, add:")
        pory_lines.append(f"//      #define {trainer_class}  <next_available_number>")
        pory_lines.append(f"//")
        pory_lines.append(f"// 2. In src/data/trainer_classes.h, add a gTrainerClassInfo entry for it.")
        pory_lines.append(f"//")
        pory_lines.append(f"// 3. In graphics/trainers/palettes/, add a palette file for the class.")
        pory_lines.append(f"//    (Can copy an existing one as a placeholder.)")
        pory_lines.append(f"//")
        pory_lines.append(f"// 4. In src/battle_main.c or the relevant class name table,")
        pory_lines.append(f"//    add the display name for the class.")
        pory_lines.append(f"//")
        pory_lines.append(f"// See CLAUDE.md or the romhack briefing for examples of existing custom classes.")
        pory_lines.append("")
    pory_lines.append(f"text {text_label_base}_Intro {{")
    pory_lines.append(f'    "{intro_text}$"')
    pory_lines.append("}")
    pory_lines.append("")
    pory_lines.append(f"text {text_label_base}_Defeat {{")
    pory_lines.append(f'    "{defeat_text}$"')
    pory_lines.append("}")
    if is_double and not_enough_text:
        pory_lines.append("")
        pory_lines.append(f"text {not_enough_label} {{")
        pory_lines.append(f'    "{not_enough_text}$"')
        pory_lines.append("}")
    pory_lines.append("")
    return pory_lines


def _wizard_write_game_files(details, mons, dialogue, fmt, game_path, project_dir):
    """Write all game files for the new trainer. Returns (pory_path, pory_map_folder, pory_filename)."""
    trainer_const = details["trainer_const"]
    trainer_name = details["trainer_name"]
    trainer_class = details["trainer_class"]
    trainer_class_is_custom = details["trainer_class_is_custom"]
    encounter_music = details["encounter_music"]
    trainer_pic = details["trainer_pic"]
    is_double = details["is_double"]
    ai_flags = details["ai_flags"]
    new_trainer_id = details["new_trainer_id"]

    const_stem = dialogue["const_stem"]
    text_label_base = dialogue["text_label_base"]
    map_name_for_text = dialogue["map_name_for_text"]
    intro_text = dialogue["intro_text"]
    defeat_text = dialogue["defeat_text"]
    not_enough_text = dialogue["not_enough_text"]
    not_enough_label = dialogue["not_enough_label"]

    opponents_path = os.path.join(game_path, "include", "constants", "opponents.h")
    trainers_h_path = os.path.join(game_path, "src", "data", "trainers.h")
    trainer_parties_path = os.path.join(game_path, "src", "data", "trainer_parties.h")
    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    party_const = f"sParty_{const_stem}"

    print()
    print(DIVIDER)
    print()

    # opponents.h
    trainers_count2, _, lines2 = _read_opponents_h(opponents_path)
    max_existing = trainers_count2 - 1
    new_count = max(max_existing, new_trainer_id) + 1
    _write_opponents_h(opponents_path, lines2, trainer_const, new_trainer_id, new_count)
    final_count = _recalculate_trainers_count(opponents_path)
    print(f" Written: opponents.h  (#define {trainer_const} {new_trainer_id}, TRAINERS_COUNT -> {final_count})")

    # Trainer data file
    if fmt == "party":
        new_record = {
            "trainer_const": trainer_const, "trainer_name": trainer_name,
            "trainer_class": trainer_class, "trainer_pic": trainer_pic,
            "encounter_music": encounter_music, "is_double": is_double,
            "ai_flags": ai_flags, "mons": mons, "trainer_items": None, "mugshot": None,
        }
        _append_trainer_to_party_file(party_path, new_record)
        print(f" Written: trainers.party  (=== {trainer_const} ===, {len(mons)} mon(s))")
    else:
        _append_party(trainer_parties_path, party_const, mons)
        print(f" Written: trainer_parties.h  ({party_const}, {len(mons)} mon(s))")
        _insert_trainer(trainers_h_path, trainer_const, trainer_class, encounter_music,
                        trainer_pic, trainer_name, is_double, ai_flags, party_const)
        print(f" Written: trainers.h  ([{trainer_const}])")

    # .pory text file
    pory_map_folder = map_name_for_text
    pory_dir = os.path.join(project_dir, pory_map_folder)
    pory_filename = f"battle_{trainer_const}.pory"
    pory_path = os.path.join(pory_dir, pory_filename)
    os.makedirs(pory_dir, exist_ok=True)
    pory_lines = _wizard_build_pory_content(trainer_class, trainer_class_is_custom,
                                            text_label_base, intro_text, defeat_text,
                                            is_double, not_enough_text, not_enough_label)
    with open(pory_path, "w") as f:
        f.write("\n".join(pory_lines))
    print(f" Written: {pory_path}")
    if trainer_class_is_custom:
        print(f"   ^ Contains TODO instructions for adding '{trainer_class}' to the game.")

    return pory_path, pory_map_folder, pory_filename


def _wizard_build_record(details, mons):
    """Build a record dict suitable for _display_trainer_card from wizard data."""
    return {
        "trainer_id": details["new_trainer_id"],
        "trainer_const": details["trainer_const"],
        "trainer_name": details["trainer_name"],
        "trainer_class": details["trainer_class"],
        "encounter_music": details["encounter_music"],
        "trainer_pic": details["trainer_pic"],
        "is_double": details["is_double"],
        "ai_flags": details["ai_flags"],
        "mons": mons,
        "trainer_items": None,
    }


def _wizard_build_dialogue_dict(dialogue):
    """Build a dialogue dict suitable for _display_trainer_card from wizard data."""
    d = {
        "intro": dialogue["intro_text"],
        "defeat": dialogue["defeat_text"],
    }
    if dialogue.get("not_enough_text"):
        d["not_enough"] = dialogue["not_enough_text"]
    return d


def _wizard_show_preview(details, mons, dialogue, fmt):
    """Display the trainer card preview. Returns the record used."""
    record = _wizard_build_record(details, mons)
    card_dialogue = _wizard_build_dialogue_dict(dialogue)
    map_folder = dialogue["map_name_for_text"]
    _display_trainer_card(record, map_folder, card_dialogue, fmt=fmt)
    return record


_WIZARD_EDIT_FIELDS = [
    ("1", "Display name"),
    ("2", "Trainer class"),
    ("3", "Party"),
    ("4", "Intro dialogue"),
    ("5", "Defeat dialogue"),
]


def _wizard_edit_field(choice, details, mons, dialogue, class_set, species_set,
                       items_set, moves_set, abilities_set, game_path, settings):
    """Edit a single wizard field by number. Returns updated (details, mons, dialogue)."""
    tw = settings["textbox_warning"]
    is_double = details["is_double"]

    if choice == "1":
        details["trainer_name"] = _wizard_prompt_display_name(details["trainer_class"])
    elif choice == "2":
        tc, custom = _wizard_prompt_class(class_set)
        details["trainer_class"] = tc
        details["trainer_class_is_custom"] = custom
    elif choice == "3":
        mons = _wizard_step_party(species_set, items_set, moves_set, abilities_set,
                                  game_path, settings)
    elif choice == "4":
        print()
        print(f" INTRO  (label: {dialogue['text_label_base']}_Intro)")
        print()
        dialogue["intro_text"] = _dialogue_prompt("Intro line", is_double, tw)
    elif choice == "5":
        print()
        print(f" DEFEAT  (label: {dialogue['text_label_base']}_Defeat)")
        print()
        dialogue["defeat_text"] = _dialogue_prompt("Defeat line", is_double, tw)

    return details, mons, dialogue


def _wizard_preview_and_write(details, mons, dialogue, script_output_path,
                              fmt, game_path, project_dir,
                              workspace_expanded, emotes_conf, source_display, settings):
    """Show trainer card preview with edit/confirm/cancel flow, then write files."""

    # Load validation sets for edit flow
    constants_dir = os.path.join(game_path, "include", "constants")
    class_set = _parse_defines(os.path.join(constants_dir, "trainers.h"), "TRAINER_CLASS_")
    species_set = _parse_defines(os.path.join(constants_dir, "species.h"), "SPECIES_")
    items_set = _parse_defines(os.path.join(constants_dir, "items.h"), "ITEM_")
    moves_set = _parse_defines(os.path.join(constants_dir, "moves.h"), "MOVE_")
    abilities_set = _parse_defines(os.path.join(constants_dir, "abilities.h"), "ABILITY_")

    while True:
        _wizard_show_preview(details, mons, dialogue, fmt)
        print()
        print(f"  {_k('e')} {DIM}Edit a field{RST}    "
              f"{_k('c')} {DIM}Confirm and save{RST}    "
              f"{_k('q')} {DIM}Cancel{RST}")
        print()
        action = input("  > ").strip().lower()

        if action == "c":
            break
        elif action == "q":
            yn = input("  Trainer will not be saved. Are you sure? [y/N] > ").strip().lower()
            if yn == "y":
                print()
                print(" Cancelled. No files were changed.")
                return
            continue
        elif action == "e":
            print()
            for num, label in _WIZARD_EDIT_FIELDS:
                print(f"  [{num}] {label}")
            print()
            field_choice = input("  Which field? > ").strip()
            valid = [num for num, _ in _WIZARD_EDIT_FIELDS]
            if field_choice in valid:
                details, mons, dialogue = _wizard_edit_field(
                    field_choice, details, mons, dialogue, class_set,
                    species_set, items_set, moves_set, abilities_set,
                    game_path, settings)

    # ---- Write files ----
    pory_path, pory_map_folder, pory_filename = _wizard_write_game_files(
        details, mons, dialogue, fmt, game_path, project_dir)

    print()
    print(DIVIDER)
    print()
    print(" Battle setup complete.")

    # --- Auto-sync ---
    if emotes_conf and source_display:
        ensure_synced(pory_map_folder, project_dir, game_path,
                      emotes_conf, source_display,
                      settings.get("max_snapshots", 10))

    trainer_class_is_custom = details["trainer_class_is_custom"]
    trainer_class = details["trainer_class"]
    print(" Next steps:")
    step = 1
    if trainer_class_is_custom:
        print(f"   {step}. Add '{trainer_class}' to the game (see TODO in {pory_filename})")
        step += 1
    print(f"   {step}. Add the trainerbattle line to your .txt script")
    step += 1
    print(f"   {step}. Build:")
    _offer_build(game_path)
    print()


# ============================================================
# NEW BATTLE WIZARD
# ============================================================

def _run_new_battle_wizard(args, project_dir, game_path, workspace_expanded,
                           settings=None, emotes_conf=None, source_display=None, fmt=None,
                           proj_name=None):
    """Interactive wizard to create a new trainer battle."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if fmt is None:
        fmt = _detect_trainer_format(game_path)
    clear_screen()

    opponents_path      = os.path.join(game_path, "include", "constants", "opponents.h")
    config_dir          = os.path.join(workspace_expanded, "config")

    # ---- Parse game headers once ----
    constants_dir = os.path.join(game_path, "include", "constants")
    species_set = _parse_defines(os.path.join(constants_dir, "species.h"),   "SPECIES_")
    moves_set   = _parse_defines(os.path.join(constants_dir, "moves.h"),     "MOVE_")
    items_set   = _parse_defines(os.path.join(constants_dir, "items.h"),     "ITEM_")
    class_set   = _parse_defines(os.path.join(constants_dir, "trainers.h"),  "TRAINER_CLASS_")
    ai_set      = _parse_defines(os.path.join(constants_dir, "battle_ai.h"), "AI_FLAG_")
    abilities_set = _parse_defines(os.path.join(constants_dir, "abilities.h"), "ABILITY_")

    print_logo(f"Battle Wizard  v{BATTLE_VERSION}", proj_name)
    print(" This wizard registers a new trainer in the game and sets up their battle.")
    print(" It will write to three game files automatically.")
    print(" A .pory text file will be saved to your workspace map folder.")
    print()
    print(DIVIDER)

    # Step 1: Trainer details
    details = _wizard_step_details(opponents_path, constants_dir, config_dir,
                                   game_path, class_set, ai_set, settings,
                                   fmt=fmt)
    if details is None:
        return

    # Step 2: Party
    mons = _wizard_step_party(species_set, items_set, moves_set, abilities_set,
                              game_path, settings)

    # Step 3: Dialogue
    dialogue = _wizard_step_dialogue(details["raw_const"], details["is_double"],
                                     game_path, project_dir, settings)

    # Step 4: Raw script output (optional)
    script_output_path = _wizard_step_script_output(details, dialogue, project_dir)

    # Preview & Write
    _wizard_preview_and_write(details, mons, dialogue, script_output_path,
                              fmt, game_path, project_dir,
                              workspace_expanded, emotes_conf, source_display, settings)
