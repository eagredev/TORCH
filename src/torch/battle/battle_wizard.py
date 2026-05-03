"""Trainer creation wizard with Pokemon Showdown import.

Guided wizard for creating new trainers: species picker, moveset
builder, EV/IV entry, held items, AI flag selection, and intro/defeat
dialogue with GBA text preview. Also parses Showdown team exports
for quick trainer setup.
"""
# TORCH_MODULE: Battle Wizard
# TORCH_GROUP: Trainers
import os
import sys
import re
import configparser

from torch.names import _parse_stat_spread
from torch.ui import _k, clear_screen
from torch.config import _nav_keys
from torch.gamedata import parse_defines_set as _gamedata_parse_defines_set, load_ai_flags
from torch.textutils import wrap_gba_text as _wrap_gba_text, count_text_boxes as _count_text_boxes
from torch.colours import GOLD, WHITE, GREEN, DIM, RST, strip_ansi
try:
    from torch.data_files.vanilla_asset_sets import VANILLA_TRAINER_PICS
except ImportError:
    VANILLA_TRAINER_PICS = set()


# ============================================================
# BATTLE SETUP WIZARD
# ============================================================

def _battle_prompt(label, default=None, required=True):
    """Print a prompt and return stripped input. Loops on empty if required."""
    while True:
        if default:
            val = input(f"  {label} [{default}] > ").strip()
            return val if val else default
        else:
            val = input(f"  {label} > ").strip()
            if required and not val:
                print("  This field is required. Please enter a value.")
                print()
                continue
            return val


def _confirm_value(label, value):
    """Show auto-corrected value and ask user to confirm. Returns True if accepted."""
    print(f"  -> {label}: {value}")
    yn = input("     Is that correct? [Y/n] > ").strip().lower()
    return yn in ("", "y", "yes")


def _parse_defines(header_path, prefix):
    """Return a set of constant names matching prefix from a .h file.

    Delegates to gamedata.parse_defines_set for session-level caching.
    """
    return _gamedata_parse_defines_set(header_path, prefix)


def _to_pascal_case(s):
    """Convert 'lake elix south' -> 'LakeElixSouth'. Preserves existing capitalisation within words."""
    return "".join(w[0].upper() + w[1:] for w in re.split(r"[\s_\-]+", s) if w)


def _wrap_dialogue(text, line_len=38):
    """Wrap text into GBA textbox format.

    Delegates to textutils.wrap_gba_text for shared implementation.
    Backward-compat alias kept so battle_manager imports still work.
    """
    return _wrap_gba_text(text, line_len=line_len)


def _load_battle_menus(config_dir):
    """
    Load battle_menus.conf. Returns (music_items, sprite_items).
    Each is an OrderedDict of {label: CONSTANT_SUFFIX}.
    Falls back to hardcoded defaults if file missing.
    """
    conf_path = os.path.join(config_dir, "battle_menus.conf")

    default_music = [
        ("Male",         "MALE"),
        ("Female",       "FEMALE"),
        ("Girl",         "GIRL"),
        ("Suspicious",   "SUSPICIOUS"),
        ("Intense",      "INTENSE"),
        ("Cool",         "COOL"),
        ("Aqua",         "AQUA"),
        ("Magma",        "MAGMA"),
        ("Swimmer",      "SWIMMER"),
        ("Twins",        "TWINS"),
        ("Elite Four",   "ELITE_FOUR"),
        ("Hiker",        "HIKER"),
        ("Interviewer",  "INTERVIEWER"),
        ("Rich",         "RICH"),
    ]
    default_sprites = [
        ("Aqua Grunt M",   "AQUA_GRUNT_M"),
        ("Aqua Grunt F",   "AQUA_GRUNT_F"),
        ("Magma Grunt M",  "MAGMA_GRUNT_M"),
        ("Magma Grunt F",  "MAGMA_GRUNT_F"),
        ("Cooltrainer M",  "COOLTRAINER_M"),
        ("Cooltrainer F",  "COOLTRAINER_F"),
        ("Youngster",      "YOUNGSTER"),
        ("Lass",           "LASS"),
        ("Bug Catcher",    "BUG_CATCHER"),
        ("Bug Maniac",     "BUG_MANIAC"),
        ("Hiker",          "HIKER"),
        ("Swimmer M",      "SWIMMER_M"),
        ("Black Belt",     "BLACK_BELT"),
        ("Psychic M",      "PSYCHIC_M"),
        ("Psychic F",      "PSYCHIC_F"),
        ("School Kid M",   "SCHOOL_KID_M"),
        ("School Kid F",   "SCHOOL_KID_F"),
        ("Gentleman",      "GENTLEMAN"),
        ("Beauty",         "BEAUTY"),
        ("Expert M",       "EXPERT_M"),
    ]

    if not os.path.exists(conf_path):
        return default_music, default_sprites

    cfg = configparser.ConfigParser()
    cfg.read(conf_path)

    def read_section(section, default):
        if section not in cfg:
            return default
        return [(k.title(), v.strip()) for k, v in cfg.items(section)]

    music_items = read_section("encounter_music", default_music)
    sprite_items = read_section("trainer_sprites", default_sprites)
    return music_items, sprite_items


def _split_custom_vanilla(all_constants, config_items, prefix,
                          vanilla_set=None):
    """Split game constants into custom and vanilla lists.

    Args:
        all_constants: set of all constants from game headers (from _parse_defines)
        config_items: list of (label, SUFFIX) from battle_menus.conf (the known vanilla set)
        prefix: Constant prefix (e.g., "TRAINER_ENCOUNTER_MUSIC_")
        vanilla_set: optional set of full constant names known to be vanilla.
            When provided, classification uses this instead of config_items.

    Returns: (custom_items, vanilla_items) — each a list of (label, SUFFIX)
    """
    if vanilla_set:
        # Authoritative vanilla detection — classify every header constant
        custom = []
        vanilla = []
        for c in sorted(all_constants):
            if not c.startswith(prefix):
                continue
            suffix = c[len(prefix):]
            if suffix == "COUNT":
                continue
            label = suffix.replace("_", " ").title()
            if c in vanilla_set:
                vanilla.append((label, suffix))
            else:
                custom.append((label, suffix))
        return custom, vanilla

    # Fallback: config-based split (encounter music, etc.)
    config_suffixes = {suffix for _, suffix in config_items}
    vanilla = [(label, suffix) for label, suffix in config_items
               if f"{prefix}{suffix}" in all_constants]
    custom_suffixes = sorted(
        suffix
        for c in all_constants
        if c.startswith(prefix)
        for suffix in [c[len(prefix):]]
        if suffix not in config_suffixes
    )
    custom = [(suffix.replace("_", " ").title(), suffix) for suffix in custom_suffixes]
    return custom, vanilla


def _numbered_menu(title, items, prefix, valid_set, default_idx=0, settings=None):
    """
    Show a scrollable menu and return the resolved constant (with full prefix).
    items: list of (label, SUFFIX)
    prefix: e.g. "TRAINER_ENCOUNTER_MUSIC_"
    valid_set: set of full constant names (for validation)
    default_idx: 0-based index for the default choice (shown on Enter)
    Returns a validated constant string.
    """
    if settings is None:
        settings = {}
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)


    selected = default_idx

    def _resolve_and_return(idx):
        suffix = items[idx][1]
        const = f"{prefix}{suffix}"
        if valid_set and const not in valid_set:
            print(f"  Warning: '{const}' not found in game headers. Using it anyway.")
        print(f"  -> {const}")
        print()
        return const

    while True:
        clear_screen()
        print(f"  {WHITE}{title}{RST}")
        print()
        for i, (label, suffix) in enumerate(items):
            cursor = f"{GOLD}>>{RST}" if i == selected else "  "
            is_default = (i == default_idx)
            default_mark = f" {DIM}*default{RST}" if is_default else ""
            label_col = WHITE if i == selected else ""
            print(f"  {cursor} {DIM}{i + 1:2}.{RST} {label_col}{label}{RST}{default_mark}")
        print()
        default_label = items[default_idx][0]
        print(f"  {_k(NK_OPEN)}/{_k('Enter')} {DIM}select{RST}  "
              f"{_k(NK_UP)} {DIM}up{RST}  {_k(NK_DOWN)} {DIM}down{RST}  "
              f"{_k('#')} {DIM}jump{RST}  "
              f"{_k('c')} {DIM}custom{RST}  "
              f"{DIM}bare Enter = default ({default_label}){RST}")
        print()

        raw = input(f"  {GOLD}>{RST} ").strip()

        if raw == "":
            return _resolve_and_return(default_idx)

        cmd = raw.lower()

        if cmd in (NK_UP, "k"):
            selected = max(0, selected - 1)
            continue

        if cmd == NK_DOWN:
            selected = min(len(items) - 1, selected + 1)
            continue

        if cmd == NK_OPEN:
            return _resolve_and_return(selected)

        if cmd == "c":
            while True:
                custom = input(f"  Type the full constant name ({prefix}...) > ").strip()
                if not custom:
                    print("  Cancelled, returning to menu.")
                    print()
                    break
                custom_up = custom.strip().upper()
                if not custom_up.startswith(prefix):
                    custom_up = f"{prefix}{custom_up}"
                if valid_set and custom_up not in valid_set:
                    print(f"  Warning: '{custom_up}' not found in game headers.")
                    yn = input("  Use it anyway? [y/N] > ").strip().lower()
                    if yn != "y":
                        continue
                print(f"  -> {custom_up}")
                print()
                return custom_up
            continue

        if raw.isdigit():
            choice_num = int(raw)
            if 1 <= choice_num <= len(items):
                selected = choice_num - 1
                return _resolve_and_return(selected)
            else:
                print(f"  Please enter a number between 1 and {len(items)}.")
                print()
        else:
            print(f"  Press {NK_OPEN} to select, {NK_UP}/{NK_DOWN} to navigate, or a number to jump.")
            print()


# ============================================================
# DUAL-LIST PICKER
# ============================================================

def _format_cell(label, idx, sel_idx, is_active, is_default):
    """Format one cell in a dual-list or single-list column.

    Returns an ANSI-formatted string for one row entry.
    """
    dm = f" {DIM}*default{RST}" if is_default else ""
    if is_active and idx == sel_idx:
        return f"{GOLD}>>{RST} {WHITE}{label}{RST}{dm}"
    if is_active:
        return f"   {label}{dm}"
    return f"   {DIM}{label}{RST}"


def _overflow_str(top, end, total, direction):
    """Return overflow indicator string, or empty if not needed."""
    if direction == "above" and top > 0:
        return f"\u2191 {top} more above"
    if direction == "below" and end < total:
        return f"\u2193 {total - end} more below"
    return ""


def _render_dual_columns(custom_items, vanilla_items, c_sel, v_sel, c_top, v_top,
                         active, page_size, default_idx, default_list):
    """Render two side-by-side columns for the dual-list picker."""
    col_width = 30

    if not custom_items:
        # --- Single column (vanilla only) ---
        print(f"  {WHITE}VANILLA ({len(vanilla_items)}){RST}")
        print()
        v_end = min(v_top + page_size, len(vanilla_items))
        above = _overflow_str(v_top, 0, 0, "above")
        if v_top > 0:
            print(f"  {DIM}  \u2191 {v_top} more above{RST}")
        for vi in range(v_top, v_end):
            is_def = (default_list == "vanilla" and vi == default_idx)
            cell = _format_cell(vanilla_items[vi][0], vi, v_sel, True, is_def)
            print(f"  {cell}")
        if v_end < len(vanilla_items):
            print(f"  {DIM}  \u2193 {len(vanilla_items) - v_end} more below{RST}")
        return

    # --- Dual column ---
    c_style = WHITE if active == "custom" else DIM
    v_style = WHITE if active == "vanilla" else DIM
    print(f"  {c_style}CUSTOM ({len(custom_items)}){' ' * (col_width - len(f'CUSTOM ({len(custom_items)})'))}{RST}"
          f" {DIM}\u2502{RST} {v_style}VANILLA ({len(vanilla_items)}){RST}")
    print()

    # Overflow above
    c_above = _overflow_str(c_top, 0, 0, "above") if c_top > 0 else ""
    v_above = _overflow_str(v_top, 0, 0, "above") if v_top > 0 else ""
    if c_above or v_above:
        print(f"  {DIM}  {c_above:<{col_width}}{RST} {DIM}\u2502   {v_above}{RST}")

    c_end = min(c_top + page_size, len(custom_items))
    v_end = min(v_top + page_size, len(vanilla_items))

    for row in range(max(c_end - c_top, v_end - v_top)):
        ci = c_top + row
        left = ""
        if ci < c_end:
            is_def = (default_list == "custom" and ci == default_idx)
            left = _format_cell(custom_items[ci][0], ci, c_sel, active == "custom", is_def)

        vi = v_top + row
        right = ""
        if vi < v_end:
            is_def = (default_list == "vanilla" and vi == default_idx)
            right = _format_cell(vanilla_items[vi][0], vi, v_sel, active == "vanilla", is_def)

        visible_len = len(strip_ansi(left))
        padding = col_width - visible_len
        print(f"  {left}{' ' * max(0, padding)} {DIM}\u2502{RST} {right}")

    # Overflow below
    c_below = _overflow_str(c_top, c_end, len(custom_items), "below")
    v_below = _overflow_str(v_top, v_end, len(vanilla_items), "below")
    if c_below or v_below:
        print(f"  {DIM}  {c_below:<{col_width}}{RST} {DIM}\u2502   {v_below}{RST}")


def _handle_dual_input(cmd, active, c_sel, v_sel, custom_items, vanilla_items,
                       NK_UP, NK_DOWN):
    """Process navigation input for dual-list picker.

    Returns: (active, c_sel, v_sel, action)
        action is one of: "continue", "select", "custom_entry", "cancel"
    """
    if cmd == "`" and custom_items:
        active = "vanilla" if active == "custom" else "custom"
        return active, c_sel, v_sel, "continue"

    items = custom_items if active == "custom" else vanilla_items
    sel = c_sel if active == "custom" else v_sel
    max_idx = len(items) - 1

    if cmd in (NK_UP, "k"):
        sel = max(0, sel - 1)
    elif cmd == NK_DOWN:
        sel = min(max_idx, sel + 1)
    elif cmd == "":
        # Enter = scroll down with wrap
        sel = (sel + 1) % len(items) if items else 0
    elif cmd in ("v", "f"):
        if active == "custom":
            c_sel = sel
        else:
            v_sel = sel
        return active, c_sel, v_sel, "select"
    elif cmd == "c":
        return active, c_sel, v_sel, "custom_entry"
    elif cmd == "q":
        return active, c_sel, v_sel, "cancel"

    if active == "custom":
        c_sel = sel
    else:
        v_sel = sel
    return active, c_sel, v_sel, "continue"


def _clamp_scroll(sel, top, page_size, count):
    """Clamp selection to valid range and adjust scroll offset. Returns (sel, top)."""
    if count == 0:
        return 0, 0
    sel = max(0, min(sel, count - 1))
    if sel < top:
        top = sel
    if sel >= top + page_size:
        top = sel - page_size + 1
    return sel, top


def _custom_entry_prompt(prefix, valid_set):
    """Prompt user to type a custom constant name. Returns full constant or None."""
    while True:
        custom_val = input(f"  Type constant name ({prefix}...) > ").strip()
        if not custom_val:
            print("  Cancelled, returning to menu.")
            print()
            return None
        custom_up = custom_val.strip().upper()
        if not custom_up.startswith(prefix):
            custom_up = f"{prefix}{custom_up}"
        if valid_set and custom_up not in valid_set:
            print(f"  Warning: '{custom_up}' not found in game headers.")
            yn = input("  Use it anyway? [y/N] > ").strip().lower()
            if yn != "y":
                continue
        print(f"  -> {custom_up}")
        print()
        return custom_up


def _resolve_pick(items, idx, prefix, valid_set):
    """Resolve a picked item to its full constant string."""
    suffix = items[idx][1]
    const = f"{prefix}{suffix}"
    if valid_set and const not in valid_set:
        print(f"  Warning: '{const}' not found in game headers. Using it anyway.")
    print(f"  -> {const}")
    print()
    return const


def _dual_list_picker(title, custom_items, vanilla_items, prefix, valid_set,
                      default_idx=None, default_list=None, settings=None):
    """Dual-list picker for game constants.

    Shows custom items (left) alongside vanilla items (right) with independent
    scrolling. If no custom items exist, shows vanilla only in full width.

    Args:
        title: Header text
        custom_items: list of (label, SUFFIX) tuples for custom entries (may be empty)
        vanilla_items: list of (label, SUFFIX) tuples for vanilla entries
        prefix: Constant prefix (e.g., "TRAINER_ENCOUNTER_MUSIC_")
        valid_set: Set of valid full constant names from game headers
        default_idx: Index of the *default marker in default_list (None = no marker)
        default_list: Which list contains the default ("vanilla" or "custom")
        settings: Config dict for nav keys

    Returns: Full constant string (prefix + suffix), or None if cancelled
    """
    if settings is None:
        settings = {}
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)

    page_size = int(settings.get("trainer_list_page_size", 15))
    has_custom = len(custom_items) > 0

    if not vanilla_items and not custom_items:
        print("  No items available.")
        return None

    # Start on custom side when available, otherwise vanilla
    active = "custom" if has_custom else "vanilla"
    c_sel = 0
    v_sel = 0
    # If a default was specified, position the cursor there
    if default_idx is not None and default_list == "custom" and has_custom:
        c_sel = default_idx
        active = "custom"
    elif default_idx is not None and default_list == "vanilla" and vanilla_items:
        v_sel = default_idx
        active = "vanilla"
    c_top = 0
    v_top = 0

    while True:
        c_sel, c_top = _clamp_scroll(c_sel, c_top, page_size, len(custom_items))
        v_sel, v_top = _clamp_scroll(v_sel, v_top, page_size, len(vanilla_items))

        clear_screen()
        print(f"  {WHITE}{title}{RST}")
        print()

        _render_dual_columns(custom_items, vanilla_items, c_sel, v_sel,
                             c_top, v_top, active, page_size,
                             default_idx, default_list)
        print()

        # Footer
        parts = []
        if has_custom:
            parts.append(f"{_k('`')} {DIM}switch list{RST}")
        parts.append(f"{_k('Enter')} {DIM}scroll{RST}")
        parts.append(f"{_k(NK_UP)} {DIM}up{RST}")
        parts.append(f"{_k(NK_DOWN)} {DIM}down{RST}")
        parts.append(f"{_k(NK_OPEN)} {DIM}select{RST}")
        parts.append(f"{_k('c')} {DIM}custom{RST}")
        parts.append(f"{_k('q')} {DIM}cancel{RST}")
        print(f"  {'  '.join(parts)}")
        print()

        raw = input(f"  {GOLD}>{RST} ").strip()
        cmd = raw.lower()

        active, c_sel, v_sel, action = _handle_dual_input(
            cmd, active, c_sel, v_sel, custom_items, vanilla_items,
            NK_UP, NK_DOWN)

        if action == "select":
            items = custom_items if active == "custom" else vanilla_items
            sel = c_sel if active == "custom" else v_sel
            if items:
                return _resolve_pick(items, sel, prefix, valid_set)
        elif action == "custom_entry":
            result = _custom_entry_prompt(prefix, valid_set)
            if result is not None:
                return result
        elif action == "cancel":
            return None


# ============================================================
# DUAL-LIST PICKER WRAPPERS
# ============================================================

def pick_encounter_music(config_dir, constants_dir, game_path, settings=None):
    """Music picker with dual-list support."""
    music_items, _ = _load_battle_menus(config_dir)
    trainers_h = os.path.join(constants_dir, "trainers.h")
    music_set = _parse_defines(trainers_h, "TRAINER_ENCOUNTER_MUSIC_")
    custom, vanilla = _split_custom_vanilla(music_set, music_items,
                                            "TRAINER_ENCOUNTER_MUSIC_")
    default_idx = next((i for i, (_, s) in enumerate(vanilla) if s == "SUSPICIOUS"), 0)
    return _dual_list_picker("Pick encounter music:", custom, vanilla,
                             "TRAINER_ENCOUNTER_MUSIC_", music_set,
                             default_idx=default_idx, default_list="vanilla",
                             settings=settings)


def pick_trainer_sprite(config_dir, constants_dir, game_path, settings=None):
    """Sprite picker with dual-list support."""
    _, sprite_items = _load_battle_menus(config_dir)
    trainers_h = os.path.join(constants_dir, "trainers.h")
    pic_set = _parse_defines(trainers_h, "TRAINER_PIC_")
    custom, vanilla = _split_custom_vanilla(pic_set, sprite_items, "TRAINER_PIC_",
                                            vanilla_set=VANILLA_TRAINER_PICS)
    return _dual_list_picker("Pick trainer sprite:", custom, vanilla,
                             "TRAINER_PIC_", pic_set, settings=settings)


# AI flags — minimal fallback for when battle_ai.h can't be read
_AI_FLAGS_FALLBACK = [
    ("CHECK_BAD_MOVE",    "Won't use ineffective moves"),
    ("TRY_TO_FAINT",      "Prioritizes KO moves"),
    ("CHECK_VIABILITY",   "Considers move effectiveness"),
    ("OMNISCIENT",        "Knows all player data"),
]


def _load_ai_flag_menu(game_path):
    """Build AI flag menu from the user's game headers.

    Returns [(suffix, description), ...] with composite presets first.
    Falls back to a minimal hardcoded list if the header can't be read.
    """
    if not game_path:
        return list(_AI_FLAGS_FALLBACK)
    flags = load_ai_flags(game_path)
    if not flags:
        return list(_AI_FLAGS_FALLBACK)

    # Separate presets from individual flags — presets go first
    presets = []
    individual = []
    _PRESET_NAMES = {"BASIC_TRAINER", "SMART_TRAINER", "PREDICTION", "ASSUMPTIONS"}
    for suffix, desc in flags:
        if suffix in _PRESET_NAMES:
            presets.append((suffix, desc))
        else:
            individual.append((suffix, desc))
    return presets + individual


def _render_ai_flags_menu(menu_items, toggled, selected, preset_count,
                          nk_up, nk_down, nk_open):
    """Render the AI flags toggle menu to the terminal."""

    clear_screen()
    print(f"  {WHITE}AI FLAGS{RST}  {DIM}(toggle flags on/off, then press Enter to confirm){RST}")
    print()
    for i, (flag_suffix, desc) in enumerate(menu_items):
        if i == preset_count and preset_count > 0:
            print(f"  {DIM}{'─' * 44}{RST}")
        cursor = f"{GOLD}>>{RST}" if i == selected else "  "
        on = toggled[i]
        state = f"{GREEN}[ON] {RST}" if on else f"{DIM}[off]{RST}"
        flag_col = WHITE if on else DIM
        default_mark = f"  {DIM}*default{RST}" if flag_suffix == "CHECK_BAD_MOVE" else ""
        print(f"  {cursor} {state} {flag_col}AI_FLAG_{flag_suffix}{RST}{default_mark}")
        print(f"         {DIM}{desc}{RST}")
    print()
    active_flags = [f"AI_FLAG_{menu_items[i][0]}" for i in range(len(menu_items)) if toggled[i]]
    preview = " | ".join(active_flags) if active_flags else "0  (no flags)"
    print(f"  {DIM}Result:{RST} {preview}")
    print()
    print(f"  {_k(nk_open)} {DIM}toggle{RST}  "
          f"{_k(nk_up)} {DIM}up{RST}  {_k(nk_down)} {DIM}down{RST}  "
          f"{_k('#')} {DIM}jump{RST}  "
          f"{_k('c')} {DIM}custom expr{RST}  "
          f"{_k('Enter')} {DIM}confirm{RST}")
    print()
    return active_flags, preview


def _handle_ai_flags_input(raw, menu_items, toggled, selected, ai_set,
                           nk_up, nk_down, nk_open):
    """Process one input in the AI flags menu.

    Returns:
        ("return", result_string) — caller should return the value.
        ("continue", new_selected, new_toggled) — loop continues.
    """
    if raw == "":
        active_flags = [f"AI_FLAG_{menu_items[i][0]}" for i in range(len(menu_items)) if toggled[i]]
        result = " | ".join(active_flags) if active_flags else "0"
        print(f"  -> {result}")
        print()
        return ("return", result)

    cmd = raw.lower()

    if cmd in (nk_up, "k"):
        return ("continue", max(0, selected - 1), toggled)

    if cmd == nk_down:
        return ("continue", min(len(menu_items) - 1, selected + 1), toggled)

    if cmd == nk_open:
        toggled[selected] = not toggled[selected]
        return ("continue", selected, toggled)

    if cmd == "c":
        print()
        print("  Enter a full AI_FLAG_* expression.")
        print("  Example: AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT | AI_FLAG_HP_AWARE")
        print()
        custom = input("  Expression > ").strip()
        if not custom:
            return ("continue", selected, toggled)
        flag_names = [p.strip() for p in re.split(r'\|', custom)]
        unknown = [f for f in flag_names if f and f not in ai_set and ai_set]
        if unknown:
            print(f"  Warning: Unknown flags: {', '.join(unknown)}")
            yn = input("  Use anyway? [y/N] > ").strip().lower()
            if yn != "y":
                return ("continue", selected, toggled)
        print(f"  -> {custom}")
        print()
        return ("return", custom)

    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(menu_items):
            selected = idx
            toggled[selected] = not toggled[selected]
        else:
            print(f"  {raw} is out of range.")
        return ("continue", selected, toggled)

    return ("continue", selected, toggled)


def _ai_flags_menu(ai_set, settings=None, game_path=None):
    """
    Multi-select AI flags menu with scrollable toggle list.
    Loads flags dynamically from game headers via _load_ai_flag_menu().
    Navigate with u/j, toggle with v, confirm with Enter.
    AI_FLAG_CHECK_BAD_MOVE is ON by default; toggling it turns it off.
    Returns the final AI flags string.
    """
    if settings is None:
        settings = {}
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)

    menu_items = _load_ai_flag_menu(game_path)

    # Find preset boundary for visual separator
    _PRESET_NAMES = {"BASIC_TRAINER", "SMART_TRAINER", "PREDICTION", "ASSUMPTIONS"}
    preset_count = sum(1 for s, _ in menu_items if s in _PRESET_NAMES)

    # Initial state: only CHECK_BAD_MOVE is ON
    toggled = {i: (suffix == "CHECK_BAD_MOVE") for i, (suffix, _) in enumerate(menu_items)}
    selected = 0

    while True:
        _render_ai_flags_menu(menu_items, toggled, selected, preset_count,
                              NK_UP, NK_DOWN, NK_OPEN)
        raw = input(f"  {GOLD}>{RST} ").strip()
        action = _handle_ai_flags_input(raw, menu_items, toggled, selected, ai_set,
                                        NK_UP, NK_DOWN, NK_OPEN)
        if action[0] == "return":
            return action[1]
        _, selected, toggled = action


# ============================================================
# CONSTANT INPUT NORMALISATION & VALIDATION
# ============================================================

def _normalise_constant_input(raw, prefix):
    """
    Normalise free-form input to a constant name suffix.
    Converts spaces/hyphens to underscores, uppercases, strips the prefix if present.
    e.g. "sitrus berry" -> "SITRUS_BERRY", "ITEM_SITRUS_BERRY" -> "SITRUS_BERRY"
    """
    up = re.sub(r"[\s\-]+", "_", raw.strip()).upper()
    # Strip any accidental full prefix the user typed
    if up.startswith(prefix):
        up = up[len(prefix):]
    return up


def _validate_and_prompt(prompt_label, raw_input, prefix, valid_set, examples_count=3,
                         desc_lookup=None):
    """
    Auto-prefix raw_input with prefix, validate against valid_set.
    Returns the validated constant string. Re-prompts on failure.
    desc_lookup: optional {CONST: description} shown alongside suggestions.
    """
    val = raw_input
    while True:
        suffix = _normalise_constant_input(val, prefix)
        const = f"{prefix}{suffix}"
        if not valid_set or const in valid_set:
            return const
        # Not found — show suggestions
        entered_suffix = const[len(prefix):]
        suggestions = sorted([
            c[len(prefix):]
            for c in valid_set
            if c[len(prefix):].startswith(entered_suffix[:3])
        ])[:examples_count]
        print(f"  Not found: {const}")
        if suggestions:
            if desc_lookup:
                print(f"  Check your spelling. Known examples:")
                for s in suggestions:
                    full_const = f"{prefix}{s}"
                    desc = desc_lookup.get(full_const, "")
                    print(f"    {s}: {desc}" if desc else f"    {s}")
            else:
                print(f"  Check your spelling. Known examples: {', '.join(suggestions)}")
        else:
            print(f"  Check your spelling or use the full {prefix}* name.")
        print()
        val = input(f"  {prompt_label} > ").strip()
        if not val:
            # Allow skipping validation on blank re-entry
            return const


# ============================================================
# SHOWDOWN TEAM PARSER
# ============================================================

def _is_showdown_continuation(line, raw_line=None):
    """Return True if *line* is a Showdown detail line (not a new pokemon header).

    If raw_line is provided and starts with whitespace, it's an indented line
    (moves in Showdown format), so treat it as a continuation.
    """
    if line.startswith("- "):
        return True
    if line.startswith(("Ability:", "Level:", "EVs:", "IVs:", "Shiny:")):
        return True
    if line.endswith(" Nature"):
        return True
    # Indented lines in Showdown exports are always moves (possibly without dash prefix)
    if raw_line and raw_line != raw_line.lstrip():
        return True
    return False


def _parse_showdown_team(text, species_set, items_set, moves_set, abilities_set,
                         warnings=None):
    """
    Parse a Showdown team export into a list of mon dicts.
    Each dict: {"species", "level", "held_item", "moves", "ability",
                "evs", "ivs", "nature", "shiny", "gender"}
    Validates against the given sets; prints warnings and uses None for failed lookups.

    If *warnings* is a list, warning messages are appended to it instead of
    being printed to stdout.  This allows callers (e.g. the web API) to
    collect warnings without side effects.

    Handles pastes that contain extra blank lines between fields (common when
    pasting through a terminal) by detecting whether a line after a gap is a
    continuation field (move, ability, EVs, etc.) rather than a new pokemon.
    """
    def _warn(msg):
        if warnings is not None:
            warnings.append(msg)
        else:
            print(msg)

    # Strip all lines, drop empties, then re-group into pokemon blocks.
    # A new block starts when we see a non-continuation line that isn't blank.
    raw_lines = text.strip().splitlines()
    blocks = []          # list of list-of-lines
    current_block = []
    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue  # skip blank lines entirely; grouping is semantic
        if current_block and not _is_showdown_continuation(line, raw):
            # Looks like a new pokemon header — start a new block
            blocks.append(current_block)
            current_block = [line]
        else:
            current_block.append(line)
    if current_block:
        blocks.append(current_block)

    mons = []
    for lines in blocks:
        if not lines:
            continue
        mon = {"species": None, "level": 100, "held_item": None, "moves": [], "ability": None, "gender": None}

        # Line 1: "Nickname (Species) @ Item" or "Species @ Item" or just "Species"
        first = lines[0]
        item_part = None
        if " @ " in first:
            name_part, item_part = first.rsplit(" @ ", 1)
        else:
            name_part = first
        # Extract gender suffix (M)/(F) before species parsing
        gender_match = re.search(r"\(([MF])\)\s*$", name_part)
        if gender_match:
            mon["gender"] = "male" if gender_match.group(1) == "M" else "female"
            name_part = name_part[:gender_match.start()].strip()
        # Extract species from parentheses if present
        paren = re.search(r"\(([^)]+)\)", name_part)
        if paren:
            species_raw = paren.group(1).strip()
        else:
            species_raw = name_part.strip()

        # Validate species
        suffix = _normalise_constant_input(species_raw, "SPECIES_")
        species_const = f"SPECIES_{suffix}"
        if species_set and species_const not in species_set:
            _warn(f"  Warning: species '{species_raw}' -> {species_const} not found, skipping pokemon.")
            continue
        mon["species"] = species_const

        # Validate item
        if item_part:
            suffix = _normalise_constant_input(item_part, "ITEM_")
            item_const = f"ITEM_{suffix}"
            if items_set and item_const not in items_set:
                _warn(f"  Warning: item '{item_part}' -> {item_const} not found, skipping item.")
            else:
                mon["held_item"] = item_const

        # Remaining lines
        for line in lines[1:]:
            if line.startswith("Ability:"):
                ab_raw = line.split(":", 1)[1].strip()
                suffix = _normalise_constant_input(ab_raw, "ABILITY_")
                ab_const = f"ABILITY_{suffix}"
                if abilities_set and ab_const not in abilities_set:
                    _warn(f"  Warning: ability '{ab_raw}' -> {ab_const} not found, skipping ability.")
                else:
                    mon["ability"] = ab_const
            elif line.startswith("Level:"):
                try:
                    mon["level"] = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("- "):
                move_raw = line[2:].strip()
                suffix = _normalise_constant_input(move_raw, "MOVE_")
                move_const = f"MOVE_{suffix}"
                if moves_set and move_const not in moves_set:
                    _warn(f"  Warning: move '{move_raw}' -> {move_const} not found, skipping move.")
                else:
                    mon["moves"].append(move_const)
            elif line.startswith("EVs:"):
                mon["evs"] = _parse_stat_spread(line.split(":", 1)[1].strip())
            elif line.startswith("IVs:"):
                mon["ivs"] = _parse_stat_spread(line.split(":", 1)[1].strip())
            elif line.endswith(" Nature"):
                nature_raw = line.replace(" Nature", "").strip()
                mon["nature"] = "NATURE_" + nature_raw.upper()
            elif line.startswith("Shiny: Yes"):
                mon["shiny"] = True
            else:
                # Unrecognised continuation line — treat as a move without dash prefix
                # (some Showdown pastes lose the "- " prefix through terminal handling)
                move_raw = line.lstrip("- ").strip()
                if move_raw:
                    suffix = _normalise_constant_input(move_raw, "MOVE_")
                    move_const = f"MOVE_{suffix}"
                    if moves_set and move_const not in moves_set:
                        _warn(f"  Warning: move '{move_raw}' -> {move_const} not found, skipping move.")
                    else:
                        mon["moves"].append(move_const)

        if not mon["moves"]:
            mon["moves"] = ["MOVE_TACKLE"]
        mons.append(mon)
    return mons


# ============================================================
# OPPONENTS.H / TRAINER FILE I/O
# ============================================================

def _read_opponents_h(opponents_path):
    """
    Parse opponents.h to find the next trainer ID and the TRAINERS_COUNT line.
    Returns (trainers_count, max_trainers_count, lines) or prints error and exits.
    """
    if not os.path.exists(opponents_path):
        print(f"  ERROR: File not found: {opponents_path}")
        sys.exit(1)
    with open(opponents_path, "r") as f:
        lines = f.readlines()
    trainers_count = None
    max_trainers = None
    for line in lines:
        m = re.match(r"^#define\s+TRAINERS_COUNT\s+(\d+)", line.strip())
        if m:
            trainers_count = int(m.group(1))
        m2 = re.match(r"^#define\s+MAX_TRAINERS_COUNT\s+(\d+)", line.strip())
        if m2:
            max_trainers = int(m2.group(1))
    if trainers_count is None:
        print("  ERROR: Could not find TRAINERS_COUNT in opponents.h")
        sys.exit(1)
    return trainers_count, max_trainers, lines


def _write_opponents_h(opponents_path, lines, trainer_const, trainer_id, new_count):
    """
    Insert new trainer #define before TRAINERS_COUNT, then update TRAINERS_COUNT.
    Writes in-place.
    """
    new_lines = []
    inserted = False
    for line in lines:
        if not inserted and re.match(r"^#define\s+TRAINERS_COUNT\s+", line.strip()):
            # Insert the new trainer define before this line
            new_lines.append(f"#define {trainer_const:<36}{trainer_id}\n")
            inserted = True
            # Update TRAINERS_COUNT value (replace the trailing number, preserve newline)
            updated = re.sub(r"(\d+)(\s*)$", lambda m: str(new_count) + m.group(2), line.rstrip("\n")) + "\n"
            new_lines.append(updated)
        else:
            new_lines.append(line)
    try:
        with open(opponents_path, "w") as f:
            f.writelines(new_lines)
    except OSError as e:
        print(f"  ERROR: Could not write opponents.h: {e}")
        return False


def _emit_mon_block_lines(mon, is_last):
    """Generate the C struct lines for one mon entry in trainer_parties.h.
    Shared by _append_party and _replace_party.
    """
    lines = []
    lines.append("    {\n")
    lines.append(f"    .lvl = {mon['level']},\n")
    lines.append(f"    .species = {mon['species']},\n")
    if mon.get("held_item"):
        lines.append(f"    .heldItem = {mon['held_item']},\n")
    if mon.get("ability"):
        lines.append(f"    .ability = {mon['ability']},\n")
    if mon.get("moves"):
        moves_str = ", ".join(mon["moves"])
        lines.append(f"    .moves = {{{moves_str}}},\n")
    # Extended fields (IVs, EVs, nature) — emitted if present
    if mon.get("ivs"):
        iv = mon["ivs"]
        lines.append(f"    .iv = TRAINER_PARTY_IVS({iv.get('hp', 0)}, {iv.get('atk', 0)}, {iv.get('def', 0)}, {iv.get('spe', 0)}, {iv.get('spatk', 0)}, {iv.get('spdef', 0)}),\n")
    if mon.get("evs"):
        ev = mon["evs"]
        lines.append(f"    .ev = TRAINER_PARTY_EVS({ev.get('hp', 0)}, {ev.get('atk', 0)}, {ev.get('def', 0)}, {ev.get('spe', 0)}, {ev.get('spatk', 0)}, {ev.get('spdef', 0)}),\n")
    if mon.get("nature"):
        lines.append(f"    .nature = TRAINER_PARTY_NATURE({mon['nature']}),\n")
    if mon.get("shiny"):
        lines.append("    .isShiny = TRUE,\n")
    if mon.get("gender"):
        gender_const = "TRAINER_MON_MALE" if mon["gender"] == "male" else "TRAINER_MON_FEMALE"
        lines.append(f"    .gender = {gender_const},\n")
    if is_last:
        lines.append("    }\n")
    else:
        lines.append("    },\n")
    return lines


def _append_party(trainer_parties_path, party_const, mons):
    """
    Append a new party array to trainer_parties.h.
    mons is a list of dicts: {species, level, moves (list or None), held_item (or None), ability (or None)}
    """
    lines = []
    lines.append(f"\nstatic const struct TrainerMon {party_const}[] = {{\n")
    for i, mon in enumerate(mons):
        lines.extend(_emit_mon_block_lines(mon, i == len(mons) - 1))
    lines.append("};\n")
    with open(trainer_parties_path, "a") as f:
        f.writelines(lines)


def _insert_trainer(trainers_path, trainer_const, trainer_class, encounter_music,
                    trainer_pic, trainer_name, is_double, ai_flags, party_const):
    """
    Insert a new trainer entry into gTrainers[] before the final '};'.
    """
    with open(trainers_path, "r") as f:
        content = f.read()

    entry_lines = [
        f"    [{trainer_const}] =\n",
        "    {\n",
        f"        .trainerClass = {trainer_class},\n",
        f"        .encounterMusic_gender = {encounter_music},\n",
        f"        .trainerPic = {trainer_pic},\n",
        f"        .trainerName = _(\"{trainer_name}\"),\n",
        "        .items = {},\n",
        f"        .doubleBattle = {'TRUE' if is_double else 'FALSE'},\n",
        f"        .aiFlags = {ai_flags},\n",
        f"        .party = TRAINER_PARTY({party_const}),\n",
        "    },\n",
    ]
    new_entry = "".join(entry_lines)

    # Find the last "};" in the file (closing of gTrainers[])
    last_close = content.rfind("\n};")
    if last_close == -1:
        print("  ERROR: Could not find closing '};' in trainers.h")
        sys.exit(1)

    # Insert our new entry before it
    new_content = content[:last_close + 1] + new_entry + content[last_close + 1:]
    with open(trainers_path, "w") as f:
        f.write(new_content)
