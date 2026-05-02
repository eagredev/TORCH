"""Settings — browse and edit ROM metadata + expansion config flags.

``torch tweak`` / ``torch settings`` — the RPG Maker equivalent of a
System Settings tab.  Browse ROM metadata fields and 2000+ ``#define``
config flags across 19 header files, view current values, and edit
them without opening a text editor.

Supports any pokeemerald-expansion project (v1.6.0+) and vanilla
pokeemerald.  Missing config files are skipped gracefully.
"""
# TORCH_MODULE: Settings
# TORCH_GROUP: Editors
import os
import re
import textwrap

from torch.gamedata import parse_defines_full, clear_gamedata_cache
from torch.filewriter import patch_define
from torch.list_widget import (
    ListState, handle_input, visible_range,
    overflow_above, overflow_below, marker, footer_hint, guard_bounds,
)
from torch.pickers import pick_flag, pick_var
from torch.colours import GOLD, WHITE, CYAN, GREEN, DIM, RED, RST, BAR
from torch.ui import clear_screen, print_logo, _offer_build, _set_terminal_title
from torch.config import _nav_keys, SETTINGS_DEFAULTS

# Optional ROM metadata support from studio.py
try:
    from torch.studio import read_rom_fields, write_rom_field
    _HAS_ROM_FIELDS = True
except ImportError:
    _HAS_ROM_FIELDS = False


# ---------------------------------------------------------------------------
# Config file registry — display name -> filename in include/config/
# ---------------------------------------------------------------------------

_CONFIG_FILES = {
    "Battle":          "battle.h",
    "Pokemon":         "pokemon.h",
    "Items":           "item.h",
    "Overworld":       "overworld.h",
    "Species Toggle":  "species_enabled.h",
    "AI":              "ai.h",
    "DexNav":          "dexnav.h",
    "Fishing":         "fishing.h",
    "Text":            "text.h",
    "Summary Screen":  "summary_screen.h",
    "Debug":           "debug.h",
    "General":         "general.h",
    "Caps":            "caps.h",
    "Save":            "save.h",
    "Contest":         "contest.h",
    "Follower NPC":    "follower_npc.h",
    "Name Box":        "name_box.h",
}

# GEN_ constants in ascending order
_GEN_VALUES = [
    "GEN_3", "GEN_4", "GEN_5", "GEN_6", "GEN_7", "GEN_8", "GEN_9",
    "GEN_LATEST",
]

_GEN_KEYS = {
    "1": "GEN_3", "2": "GEN_4", "3": "GEN_5", "4": "GEN_6",
    "5": "GEN_7", "6": "GEN_8", "7": "GEN_9", "l": "GEN_LATEST",
}

_GEN_SET = frozenset(_GEN_VALUES)


# ---------------------------------------------------------------------------
# Value type classification
# ---------------------------------------------------------------------------

_FLAG_VAR_HINT_RE = re.compile(r"FLAG|VAR", re.IGNORECASE)


def _classify_value(name, value):
    """Classify a #define value for editing.

    Returns one of:
        ("gen", value_str)        — generation constant
        ("bool", True/False)      — boolean toggle
        ("int", int_value)        — numeric value
        ("flag_var", value_str)   — flag/var reference (0 = disabled)
        ("const", value_str)      — complex expression (display only)
    """
    v = value.strip()
    if v in _GEN_SET:
        return ("gen", v)
    if v == "TRUE":
        return ("bool", True)
    if v == "FALSE":
        return ("bool", False)
    # Check flag/var pattern before general int so FLAG=0 is typed correctly
    if v == "0" and _FLAG_VAR_HINT_RE.search(name):
        return ("flag_var", v)
    # Pure integer (includes 0 for non-flag contexts)
    try:
        return ("int", int(v))
    except ValueError:
        pass
    # Named flag/var references (non-zero, already assigned)
    if _FLAG_VAR_HINT_RE.search(name) and v:
        return ("flag_var", v)
    return ("const", v)


# ---------------------------------------------------------------------------
# Config discovery — load all categories from the project
# ---------------------------------------------------------------------------

def _config_dir(game_path):
    """Return the include/config/ directory path."""
    return os.path.join(game_path, "include", "config")


_ROM_METADATA_PATH = "__rom_metadata__"


def _build_rom_metadata_category(game_path, project_dir):
    """Build a synthetic ROM Metadata category from studio.py fields.

    Returns a category tuple compatible with the config category format,
    or None if ROM fields are unavailable.
    """
    if not _HAS_ROM_FIELDS:
        return None
    try:
        fields = read_rom_fields(game_path, project_dir)
    except Exception:
        return None
    if not fields:
        return None

    _FIELD_DESCRIPTIONS = {
        "TITLE":         "GBA header, max 12 chars -- shown in emulator title bar",
        "GAME_CODE":     "4-char ROM ID used by save managers, e.g. BPEE",
        "MAKER_CODE":    "2-char publisher code, usually 01 for Nintendo",
        "REVISION":      "ROM version number (0-255), usually 0",
        "ROM_FILENAME":  "Output .gba filename when you build",
        "INTERNAL_NAME": "Stored in ROM data -- seen by some tools",
    }

    settings = []
    for f in fields:
        name = f["key"]
        value = f["value"]
        comment = _FIELD_DESCRIPTIONS.get(name, "")
        vtype = ("rom_field", f)
        settings.append((name, value, comment, vtype))
    return ("ROM Metadata", _ROM_METADATA_PATH, settings)


def _discover_categories(game_path, project_dir=None):
    """Discover available config categories from the project.

    Returns list of (display_name, filepath, settings_list) sorted by
    setting count descending.  Each setting is (name, value, comment, vtype).
    ROM Metadata is always first when available.
    """
    cfg_dir = _config_dir(game_path)

    categories = []

    # ROM Metadata always comes first
    rom_cat = _build_rom_metadata_category(game_path, project_dir)
    if rom_cat:
        categories.append(rom_cat)

    if not os.path.isdir(cfg_dir):
        return categories

    config_categories = []
    for display_name, filename in _CONFIG_FILES.items():
        fpath = os.path.join(cfg_dir, filename)
        if not os.path.isfile(fpath):
            continue
        raw = parse_defines_full(fpath)
        settings = _build_settings_list(raw, fpath)
        if settings:
            config_categories.append((display_name, fpath, settings))

    # Also discover files not in the registry
    _discover_extra_files(cfg_dir, config_categories)

    config_categories.sort(key=lambda c: (-len(c[2]), c[0]))
    categories.extend(config_categories)
    return categories


def _build_settings_list(raw, fpath):
    """Convert raw (name, value, comment) tuples into enriched settings."""
    settings = []
    for name, value, comment in raw:
        # Skip include guards and meta-defines
        if name.startswith("GUARD_") or name.startswith("GUARD_CONFIG"):
            continue
        if name.startswith("#"):
            continue
        vtype = _classify_value(name, value)
        settings.append((name, value, comment, vtype))
    return settings


def _discover_extra_files(cfg_dir, categories):
    """Discover .h files in config/ not covered by _CONFIG_FILES."""
    known_files = set(_CONFIG_FILES.values())
    # Also skip files already discovered
    discovered_paths = {c[1] for c in categories}
    try:
        for fname in sorted(os.listdir(cfg_dir)):
            if not fname.endswith(".h"):
                continue
            if fname in known_files:
                continue
            fpath = os.path.join(cfg_dir, fname)
            if fpath in discovered_paths:
                continue
            raw = parse_defines_full(fpath)
            settings = _build_settings_list(raw, fpath)
            if settings:
                display_name = fname[:-2].replace("_", " ").title()
                categories.append((display_name, fpath, settings))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Pending changes tracker
# ---------------------------------------------------------------------------

class _PendingChanges:
    """Track unsaved changes to config defines."""
    __slots__ = ("_changes",)

    def __init__(self):
        self._changes = {}  # (filepath, const_name) -> new_value

    def set(self, filepath, const_name, new_value):
        self._changes[(filepath, const_name)] = new_value

    def get(self, filepath, const_name):
        return self._changes.get((filepath, const_name))

    def discard(self, filepath, const_name):
        self._changes.pop((filepath, const_name), None)

    def count(self):
        return len(self._changes)

    def items(self):
        return list(self._changes.items())

    def files(self):
        return {fp for fp, _ in self._changes}

    def clear(self):
        self._changes.clear()


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _coloured_value(vtype):
    """Return the value string coloured by type."""
    kind, val = vtype
    if kind == "rom_field":
        return f"{CYAN}{val.get('value', '?')}{RST}"
    if kind == "gen":
        return f"{GOLD}{val}{RST}"
    if kind == "bool":
        label = "TRUE" if val else "FALSE"
        colour = GREEN if val else RED
        return f"{colour}{label}{RST}"
    if kind == "int":
        return f"{CYAN}{val}{RST}"
    if kind == "flag_var":
        if val == "0":
            return f"{DIM}0 (disabled){RST}"
        return f"{CYAN}{val}{RST}"
    return f"{DIM}{val}{RST}"


def _raw_value_for_display(vtype):
    """Return uncoloured value text for display in edit prompts."""
    kind, val = vtype
    if kind == "rom_field":
        return val.get("value", "?")
    if kind == "bool":
        return "TRUE" if val else "FALSE"
    return str(val)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def config_command(args, project_dir, game_path, workspace_expanded,
                   settings, emotes_conf=None, source_display=None, proj_name=None):
    """Entry point for ``torch tweak`` / ``torch settings``."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)

    _set_terminal_title("TORCH \u2014 Settings")

    if not game_path or not os.path.isdir(game_path):
        print()
        print(f"  {RED}Error:{RST} Game path not found.")
        print(f"  {DIM}Run torch config to set up your project.{RST}")
        print()
        input("  Press Enter > ")
        return

    cfg_dir = _config_dir(game_path)
    has_config = os.path.isdir(cfg_dir)

    # If no config dir AND no ROM fields, nothing to show
    if not has_config and not _HAS_ROM_FIELDS:
        print()
        print(f"  {RED}Error:{RST} No include/config/ directory found.")
        print(f"  {DIM}Is this a pokeemerald-expansion project?{RST}")
        print()
        input("  Press Enter > ")
        return

    pending = _PendingChanges()

    # Direct search: torch tweak <search_term>
    if args:
        search_term = " ".join(args)
        categories = _discover_categories(game_path, project_dir)
        _search_mode(categories, search_term, pending, game_path, settings,
                     project_dir)
        _write_if_pending(pending, game_path)
        return

    _category_browser(game_path, settings, pending, project_dir)


# ---------------------------------------------------------------------------
# Category browser
# ---------------------------------------------------------------------------

def _category_browser(game_path, settings, pending, project_dir=None):
    """Top-level scrolling list of config categories."""
    nav = _nav_keys(settings)
    page_size = settings.get("map_list_page_size", 20)

    while True:
        categories = _discover_categories(game_path, project_dir)
        if not categories:
            clear_screen()
            print()
            print(f"  {DIM}No settings found.{RST}")
            print()
            input("  Press Enter > ")
            return

        state = ListState(len(categories), page_size=page_size)
        result = _category_browser_loop(categories, state, nav, pending,
                                        game_path, settings)
        if result == "quit":
            _write_if_pending(pending, game_path)
            return


def _category_browser_loop(categories, state, nav, pending, game_path, settings):
    """Inner loop for category browser."""
    while True:
        state.total = len(categories)
        guard_bounds(state)

        clear_screen()
        print()
        print(BAR)
        print(f"   {WHITE}SETTINGS{RST}  {DIM}(ROM metadata + config flags){RST}")
        print(BAR)
        print()

        _render_category_list(categories, state)

        above = overflow_above(state)
        if above:
            print(above)
        start, end = visible_range(state)
        for i in range(start, end):
            name, _, slist = categories[i]
            mk = marker(state, i)
            count = len(slist)
            print(f"  {mk} {WHITE}{name:<22}{RST} {DIM}{count} settings{RST}")
        below = overflow_below(state)
        if below:
            print(below)

        print()
        change_hint = ""
        if pending.count() > 0:
            change_hint = f"  {GOLD}[w]{RST} write {pending.count()} changes"
        search_hint = f"  {DIM}[/] search{RST}"
        print(footer_hint(nav, extra=search_hint + change_hint))
        if pending.count() > 0:
            print(f"  {DIM}{pending.count()} pending change(s){RST}")

        raw = input("  > ").strip()

        if raw == "/":
            _search_prompt(categories, pending, game_path, settings)
            continue
        if raw.lower() == "w" and pending.count() > 0:
            _write_changes(pending, game_path)
            # Reload after writes
            clear_gamedata_cache()
            return "refresh"

        action = handle_input(state, raw, nav)
        if action == "quit":
            return "quit"
        if action in ("open", "jump_act"):
            name, fpath, slist = categories[state.selected]
            _settings_list(name, fpath, slist, nav, pending, game_path, settings)


def _render_category_list(categories, state):
    """Placeholder — actual rendering is inline in the loop."""
    pass


# ---------------------------------------------------------------------------
# Settings list (within a category)
# ---------------------------------------------------------------------------

def _settings_list(cat_name, filepath, slist, nav, pending, game_path, settings):
    """Scrolling list of settings within a category."""
    page_size = settings.get("map_list_page_size", 20)
    state = ListState(len(slist), page_size=page_size)

    while True:
        state.total = len(slist)
        guard_bounds(state)

        clear_screen()
        print()
        print(BAR)
        print(f"   {WHITE}{cat_name}{RST}  {DIM}({len(slist)} settings){RST}")
        print(BAR)
        print()

        above = overflow_above(state)
        if above:
            print(above)

        start, end = visible_range(state)
        _render_settings_rows(slist, state, start, end, filepath, pending)

        below = overflow_below(state)
        if below:
            print(below)

        print()
        change_hint = ""
        if pending.count() > 0:
            change_hint = f"  {GOLD}[w]{RST} write {pending.count()}"
        extra = f"  {DIM}[e] edit  [/] search{RST}" + change_hint
        print(footer_hint(nav, extra=extra))

        raw = input("  > ").strip()

        if raw == "/":
            _search_in_category(slist, filepath, pending, game_path, settings)
            continue
        if raw.lower() == "e":
            name, value, comment, vtype = slist[state.selected]
            _edit_setting(name, value, comment, vtype, filepath, pending,
                          game_path)
            # Refresh the value display after edit
            slist = _reload_category(filepath, game_path)
            state.total = len(slist)
            continue
        if raw.lower() == "w" and pending.count() > 0:
            _write_changes(pending, game_path)
            clear_gamedata_cache()
            slist = _reload_category(filepath, game_path)
            state.total = len(slist)
            continue

        action = handle_input(state, raw, nav)
        if action == "quit":
            return
        if action in ("open", "jump_act"):
            name, value, comment, vtype = slist[state.selected]
            _edit_setting(name, value, comment, vtype, filepath, pending,
                          game_path)
            slist = _reload_category(filepath, game_path)
            state.total = len(slist)


def _render_settings_rows(slist, state, start, end, filepath, pending):
    """Render visible setting rows with value colouring."""
    for i in range(start, end):
        name, value, comment, vtype = slist[i]
        mk = marker(state, i)
        kind = vtype[0]
        # ROM fields use label as display name and are written immediately
        if kind == "rom_field":
            display_name = vtype[1].get("label", name)
            val_str = _coloured_value(vtype)
        else:
            display_name = name
            # Show pending value if it exists
            pending_val = pending.get(filepath, name)
            if pending_val is not None:
                display_vtype = _classify_value(name, pending_val)
                val_str = _coloured_value(display_vtype)
                val_str += f"  {GOLD}*{RST}"
            else:
                val_str = _coloured_value(vtype)
        print(f"  {mk} {WHITE}{display_name:<40}{RST} {val_str}")
        if comment:
            wrapped = textwrap.fill(comment, width=68)
            for wline in wrapped.splitlines():
                print(f"       {DIM}{wline}{RST}")
        elif i == state.selected:
            print(f"       {DIM}(no description){RST}")
        print()


def _reload_category(filepath, game_path=None):
    """Reload a single category's settings after edits."""
    if filepath == _ROM_METADATA_PATH and game_path:
        cat = _build_rom_metadata_category(game_path, None)
        return cat[2] if cat else []
    raw = parse_defines_full(filepath)
    return _build_settings_list(raw, filepath)


# ---------------------------------------------------------------------------
# Edit flow
# ---------------------------------------------------------------------------

def _edit_setting(name, value, comment, vtype, filepath, pending, game_path):
    """Interactive editor for a single setting."""
    kind, val = vtype
    if kind == "rom_field":
        _edit_rom_field(val, game_path)
    elif kind == "gen":
        _edit_gen(name, value, comment, vtype, filepath, pending)
    elif kind == "bool":
        _edit_bool(name, value, comment, vtype, filepath, pending)
    elif kind == "int":
        _edit_int(name, value, comment, vtype, filepath, pending)
    elif kind == "flag_var":
        _edit_flag_var(name, value, comment, vtype, filepath, pending,
                       game_path)
    else:
        _edit_const(name, value, comment, vtype)


def _edit_gen(name, value, comment, vtype, filepath, pending):
    """Generation constant picker."""
    clear_screen()
    print()
    print(f"  {WHITE}{name}{RST} = {_coloured_value(vtype)}")
    if comment:
        wrapped = textwrap.fill(comment, width=68)
        for wline in wrapped.splitlines():
            print(f"  {DIM}{wline}{RST}")
    print()
    print(f"  Pick generation:")
    print(f"    {GOLD}[1]{RST} GEN_3     {GOLD}[2]{RST} GEN_4     {GOLD}[3]{RST} GEN_5")
    print(f"    {GOLD}[4]{RST} GEN_6     {GOLD}[5]{RST} GEN_7     {GOLD}[6]{RST} GEN_8")
    print(f"    {GOLD}[7]{RST} GEN_9     {GOLD}[L]{RST} GEN_LATEST")
    print()
    current_display = _raw_value_for_display(vtype)
    print(f"  {DIM}Current: {current_display}{RST}")

    raw = input("  > ").strip().lower()
    if raw == "q" or not raw:
        return
    new_val = _GEN_KEYS.get(raw)
    if new_val and new_val != value:
        pending.set(filepath, name, new_val)
        print(f"  {GREEN}Staged:{RST} {name} = {new_val}")
        input(f"  {DIM}Press Enter{RST} > ")
    elif new_val == value:
        print(f"  {DIM}No change.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")


def _edit_bool(name, value, comment, vtype, filepath, pending):
    """Boolean toggle."""
    clear_screen()
    print()
    print(f"  {WHITE}{name}{RST} = {_coloured_value(vtype)}")
    if comment:
        wrapped = textwrap.fill(comment, width=68)
        for wline in wrapped.splitlines():
            print(f"  {DIM}{wline}{RST}")
    print()
    print(f"  {GOLD}[t]{RST} TRUE   {GOLD}[f]{RST} FALSE")
    print()
    current_display = _raw_value_for_display(vtype)
    print(f"  {DIM}Current: {current_display}{RST}")

    raw = input("  > ").strip().lower()
    if raw == "q" or not raw:
        return
    new_val = None
    if raw == "t":
        new_val = "TRUE"
    elif raw == "f":
        new_val = "FALSE"
    if new_val and new_val != value:
        pending.set(filepath, name, new_val)
        print(f"  {GREEN}Staged:{RST} {name} = {new_val}")
        input(f"  {DIM}Press Enter{RST} > ")
    elif new_val == value:
        print(f"  {DIM}No change.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")


def _edit_int(name, value, comment, vtype, filepath, pending):
    """Numeric value editor."""
    clear_screen()
    print()
    print(f"  {WHITE}{name}{RST} = {_coloured_value(vtype)}")
    if comment:
        wrapped = textwrap.fill(comment, width=68)
        for wline in wrapped.splitlines():
            print(f"  {DIM}{wline}{RST}")
    print()
    current_display = _raw_value_for_display(vtype)
    print(f"  Enter new value {DIM}(current: {current_display}){RST}:")

    raw = input("  > ").strip()
    if raw.lower() == "q" or not raw:
        return
    try:
        new_int = int(raw)
    except ValueError:
        print(f"  {RED}Not a valid integer.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return
    new_val = str(new_int)
    if new_val != value:
        pending.set(filepath, name, new_val)
        print(f"  {GREEN}Staged:{RST} {name} = {new_val}")
        input(f"  {DIM}Press Enter{RST} > ")
    else:
        print(f"  {DIM}No change.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")


def _edit_flag_var(name, value, comment, vtype, filepath, pending, game_path):
    """Flag/var reference editor."""
    clear_screen()
    print()
    print(f"  {WHITE}{name}{RST} = {_coloured_value(vtype)}")
    if comment:
        wrapped = textwrap.fill(comment, width=68)
        for wline in wrapped.splitlines():
            print(f"  {DIM}{wline}{RST}")
    print()
    print(f"  {GOLD}[0]{RST} Disabled   {GOLD}[p]{RST} Pick a flag/var")
    print()
    current_display = _raw_value_for_display(vtype)
    print(f"  {DIM}Current: {current_display}{RST}")

    raw = input("  > ").strip().lower()
    if raw == "q" or not raw:
        return
    if raw == "0":
        if value != "0":
            pending.set(filepath, name, "0")
            print(f"  {GREEN}Staged:{RST} {name} = 0 (disabled)")
            input(f"  {DIM}Press Enter{RST} > ")
        else:
            print(f"  {DIM}Already disabled.{RST}")
            input(f"  {DIM}Press Enter{RST} > ")
        return
    if raw == "p":
        picked = _pick_flag_or_var(name, game_path)
        if picked and picked != value:
            pending.set(filepath, name, picked)
            print(f"  {GREEN}Staged:{RST} {name} = {picked}")
            input(f"  {DIM}Press Enter{RST} > ")
        return


def _pick_flag_or_var(name, game_path):
    """Pick a flag or var based on the define name."""
    name_upper = name.upper()
    if "VAR" in name_upper:
        return pick_var(game_path)
    return pick_flag(game_path)


def _edit_const(name, value, comment, vtype):
    """Display-only for complex expressions."""
    clear_screen()
    print()
    print(f"  {WHITE}{name}{RST} = {_coloured_value(vtype)}")
    if comment:
        wrapped = textwrap.fill(comment, width=68)
        for wline in wrapped.splitlines():
            print(f"  {DIM}{wline}{RST}")
    print()
    print(f"  {DIM}Advanced -- edit manually in the header file.{RST}")
    print()
    input(f"  {DIM}Press Enter{RST} > ")


def _edit_rom_field(field, game_path):
    """Interactive editor for a ROM metadata field."""
    clear_screen()
    print()
    label = field["label"]
    key = field["key"]
    current = field["value"]
    max_len = field["max_len"]
    print(f"  {WHITE}{label}{RST} = {CYAN}{current}{RST}")
    if max_len:
        print(f"  {DIM}Max {max_len} characters{RST}")
    print()
    new_val = input(f"  New value {DIM}(current: {current}){RST} > ").strip()
    if not new_val:
        return
    ok, msg = write_rom_field(game_path, None, key, new_val)
    if ok:
        print(f"  {GREEN}{msg}{RST}")
        _offer_build_after_write(game_path)
    else:
        print(f"  {RED}{msg}{RST}")
    input(f"  {DIM}Press Enter{RST} > ")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _search_prompt(categories, pending, game_path, settings):
    """Global search across all categories."""
    print()
    term = input(f"  {GOLD}Search{RST} > ").strip()
    if not term:
        return
    _search_mode(categories, term, pending, game_path, settings)


def _search_mode(categories, term, pending, game_path, settings,
                 project_dir=None):
    """Show search results and allow editing."""
    results = _search_all(categories, term)
    if not results:
        print(f"  {DIM}No matches for '{term}'.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    nav = _nav_keys(settings)
    page_size = settings.get("map_list_page_size", 20)
    state = ListState(len(results), page_size=page_size)

    while True:
        state.total = len(results)
        guard_bounds(state)

        clear_screen()
        print()
        print(BAR)
        print(f"   {WHITE}SEARCH:{RST} \"{term}\"  {DIM}({len(results)} matches){RST}")
        print(BAR)
        print()

        above = overflow_above(state)
        if above:
            print(above)

        start, end = visible_range(state)
        _render_search_rows(results, state, start, end, pending)

        below = overflow_below(state)
        if below:
            print(below)

        print()
        change_hint = ""
        if pending.count() > 0:
            change_hint = f"  {GOLD}[w]{RST} write {pending.count()}"
        extra = f"  {DIM}[e] edit{RST}" + change_hint
        print(footer_hint(nav, extra=extra))

        raw = input("  > ").strip()

        if raw.lower() == "e":
            cat, name, value, comment, vtype, fpath = results[state.selected]
            _edit_setting(name, value, comment, vtype, fpath, pending,
                          game_path)
            results = _search_all(categories, term)
            state.total = len(results)
            continue
        if raw.lower() == "w" and pending.count() > 0:
            _write_changes(pending, game_path)
            clear_gamedata_cache()
            categories_new = _discover_categories(game_path, project_dir)
            categories.clear()
            categories.extend(categories_new)
            results = _search_all(categories, term)
            state.total = len(results)
            continue

        action = handle_input(state, raw, nav)
        if action == "quit":
            return
        if action in ("open", "jump_act"):
            cat, name, value, comment, vtype, fpath = results[state.selected]
            _edit_setting(name, value, comment, vtype, fpath, pending,
                          game_path)
            results = _search_all(categories, term)
            state.total = len(results)


def _search_all(categories, term):
    """Search across all categories by name or comment.

    Returns list of (category, name, value, comment, vtype, filepath).
    """
    q = term.lower()
    results = []
    for cat_name, fpath, slist in categories:
        for name, value, comment, vtype in slist:
            match = q in name.lower() or q in comment.lower()
            # ROM fields: also search by display label
            if not match and vtype[0] == "rom_field":
                label = vtype[1].get("label", "")
                match = q in label.lower()
            if match:
                results.append((cat_name, name, value, comment, vtype, fpath))
    results.sort(key=lambda r: r[1])
    return results


def _render_search_rows(results, state, start, end, pending):
    """Render search result rows."""
    for i in range(start, end):
        cat, name, value, comment, vtype, fpath = results[i]
        mk = marker(state, i)
        kind = vtype[0]
        if kind == "rom_field":
            display_name = vtype[1].get("label", name)
            val_str = _coloured_value(vtype)
            print(f"  {mk} {WHITE}{display_name:<40}{RST} {val_str}")
            cat_tag = f"[{cat}]"
            if comment:
                desc = textwrap.shorten(comment, width=55, placeholder="...")
                print(f"       {DIM}{cat_tag} {desc}{RST}")
            else:
                print(f"       {DIM}{cat_tag}{RST}")
            print()
            continue
        pending_val = pending.get(fpath, name)
        if pending_val is not None:
            display_vtype = _classify_value(name, pending_val)
            val_str = _coloured_value(display_vtype)
            val_str += f"  {GOLD}*{RST}"
        else:
            val_str = _coloured_value(vtype)
        print(f"  {mk} {WHITE}{name:<40}{RST} {val_str}")
        cat_tag = f"[{cat}]"
        if comment:
            desc = textwrap.shorten(comment, width=55, placeholder="...")
            print(f"       {DIM}{cat_tag} {desc}{RST}")
        else:
            print(f"       {DIM}{cat_tag}{RST}")
        print()


def _search_in_category(slist, filepath, pending, game_path, settings):
    """Search within a single category."""
    print()
    term = input(f"  {GOLD}Search{RST} > ").strip()
    if not term:
        return
    q = term.lower()
    matches = []
    for name, value, comment, vtype in slist:
        if q in name.lower() or q in comment.lower():
            matches.append((name, value, comment, vtype))

    if not matches:
        print(f"  {DIM}No matches for '{term}'.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    nav = _nav_keys(settings)
    page_size = settings.get("map_list_page_size", 20)
    state = ListState(len(matches), page_size=page_size)

    while True:
        state.total = len(matches)
        guard_bounds(state)

        clear_screen()
        print()
        print(f"  {WHITE}Search:{RST} \"{term}\"  {DIM}({len(matches)} matches){RST}")
        print()

        above = overflow_above(state)
        if above:
            print(above)
        start, end = visible_range(state)
        _render_settings_rows(matches, state, start, end, filepath, pending)
        below = overflow_below(state)
        if below:
            print(below)

        print()
        extra = f"  {DIM}[e] edit{RST}"
        print(footer_hint(nav, extra=extra))

        raw = input("  > ").strip()

        if raw.lower() == "e":
            name, value, comment, vtype = matches[state.selected]
            _edit_setting(name, value, comment, vtype, filepath, pending,
                          game_path)
            matches = _reload_search_matches(filepath, term, game_path)
            state.total = len(matches)
            continue

        action = handle_input(state, raw, nav)
        if action == "quit":
            return
        if action in ("open", "jump_act"):
            name, value, comment, vtype = matches[state.selected]
            _edit_setting(name, value, comment, vtype, filepath, pending,
                          game_path)
            matches = _reload_search_matches(filepath, term, game_path)
            state.total = len(matches)


def _reload_search_matches(filepath, term, game_path=None):
    """Reload search matches after an edit."""
    slist = _reload_category(filepath, game_path)
    q = term.lower()
    return [(n, v, c, vt) for n, v, c, vt in slist
            if q in n.lower() or q in c.lower()]


# ---------------------------------------------------------------------------
# Write-back
# ---------------------------------------------------------------------------

def _write_changes(pending, game_path):
    """Show pending changes summary and write them on confirmation."""
    if pending.count() == 0:
        return

    clear_screen()
    print()
    print(f"  {WHITE}Pending Changes{RST}")
    print(BAR)
    print()

    for (fpath, const_name), new_value in pending.items():
        # Get old value for display
        old_value = _get_current_value(fpath, const_name)
        rel = os.path.relpath(fpath, game_path)
        print(f"  {WHITE}{const_name}{RST}: "
              f"{DIM}{old_value}{RST} -> {GREEN}{new_value}{RST}")
        print(f"    {DIM}in {rel}{RST}")
    print()

    n_changes = pending.count()
    n_files = len(pending.files())
    confirm = input(
        f"  Write {n_changes} change(s) to {n_files} file(s)? "
        f"{DIM}[Y/n]{RST} > "
    ).strip().lower()

    if confirm and confirm != "y":
        print(f"  {DIM}Cancelled.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    success = 0
    fail = 0
    for (fpath, const_name), new_value in pending.items():
        if patch_define(fpath, const_name, new_value):
            success += 1
        else:
            fail += 1
            print(f"  {RED}Failed:{RST} {const_name} in {os.path.basename(fpath)}")

    pending.clear()
    clear_gamedata_cache()

    print()
    if fail == 0:
        print(f"  {GREEN}Written {success} change(s) successfully.{RST}")
    else:
        print(f"  {GREEN}Written {success},{RST} {RED}failed {fail}.{RST}")

    print()
    _offer_build_after_write(game_path)


def _offer_build_after_write(game_path):
    """Offer a ROM build after writing config changes."""
    raw = input(f"  Build ROM? {DIM}[Y/n]{RST} > ").strip().lower()
    if raw and raw != "y":
        return
    _offer_build(game_path=game_path, trigger="config_tuner")


def _write_if_pending(pending, game_path):
    """If there are unsaved changes when exiting, prompt to write."""
    if pending.count() == 0:
        return
    print()
    print(f"  {GOLD}You have {pending.count()} unsaved change(s).{RST}")
    raw = input(f"  Write before exiting? {DIM}[Y/n]{RST} > ").strip().lower()
    if not raw or raw == "y":
        _write_changes(pending, game_path)


def _get_current_value(filepath, const_name):
    """Get the current value of a define from the file (for display)."""
    results = parse_defines_full(filepath)
    for name, value, _ in results:
        if name == const_name:
            return value
    return "?"
