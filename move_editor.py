"""TORCH Move Editor --- browse and edit game moves.

Parses src/data/moves_info.h to extract all move entries, presents a scrolling
browser with search/filter, and allows surgical field edits with atomic
write-back.
"""
# TORCH_MODULE: Move Editor
# TORCH_GROUP: Data Editors

import os
import re

from torch.colours import GOLD, WHITE, CYAN, DIM, RED, GREEN, RST, BAR
from torch.ui import clear_screen, print_logo, _k, _offer_build
from torch.config import _nav_keys, SETTINGS_DEFAULTS
from torch.list_widget import (
    ListState, handle_input, visible_range,
    overflow_above, overflow_below, marker, footer_hint, guard_bounds,
)
from torch.filewriter import _write_atomic

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TYPES = [
    "TYPE_NORMAL", "TYPE_FIGHTING", "TYPE_FLYING", "TYPE_POISON",
    "TYPE_GROUND", "TYPE_ROCK", "TYPE_BUG", "TYPE_GHOST",
    "TYPE_STEEL", "TYPE_FIRE", "TYPE_WATER", "TYPE_GRASS",
    "TYPE_ELECTRIC", "TYPE_PSYCHIC", "TYPE_ICE", "TYPE_DRAGON",
    "TYPE_DARK", "TYPE_FAIRY", "TYPE_STELLAR",
]

_TYPE_LABELS = {t: t.replace("TYPE_", "").title() for t in _TYPES}

_CATEGORIES = [
    "DAMAGE_CATEGORY_PHYSICAL",
    "DAMAGE_CATEGORY_SPECIAL",
    "DAMAGE_CATEGORY_STATUS",
]

_CATEGORY_LABELS = {
    "DAMAGE_CATEGORY_PHYSICAL": "Physical",
    "DAMAGE_CATEGORY_SPECIAL": "Special",
    "DAMAGE_CATEGORY_STATUS": "Status",
}

_TARGETS = [
    "MOVE_TARGET_SELECTED",
    "MOVE_TARGET_DEPENDS",
    "MOVE_TARGET_OPPONENT",
    "MOVE_TARGET_RANDOM",
    "MOVE_TARGET_BOTH",
    "MOVE_TARGET_USER",
    "MOVE_TARGET_FOES_AND_ALLY",
    "MOVE_TARGET_OPPONENTS_FIELD",
    "MOVE_TARGET_ALLY",
    "MOVE_TARGET_ALL_BATTLERS",
]

_TARGET_LABELS = {
    "MOVE_TARGET_SELECTED": "Selected",
    "MOVE_TARGET_DEPENDS": "Depends",
    "MOVE_TARGET_OPPONENT": "Opponent",
    "MOVE_TARGET_RANDOM": "Random",
    "MOVE_TARGET_BOTH": "Both Opponents",
    "MOVE_TARGET_USER": "User",
    "MOVE_TARGET_FOES_AND_ALLY": "Foes and Ally",
    "MOVE_TARGET_OPPONENTS_FIELD": "Opponent's Field",
    "MOVE_TARGET_ALLY": "Ally",
    "MOVE_TARGET_ALL_BATTLERS": "All Battlers",
}

_EDITABLE_FIELDS = [
    ("name", "Name"),
    ("type", "Type"),
    ("category", "Category"),
    ("power", "Power"),
    ("accuracy", "Accuracy"),
    ("pp", "PP"),
    ("priority", "Priority"),
    ("target", "Target"),
    ("description", "Description"),
]

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_ENTRY_START = re.compile(r'^\s*\[(MOVE_\w+)\]\s*=')
_RE_MOVE_CONST = re.compile(r'#define\s+(MOVE_\w+)\s+(\d+)')

# Field patterns
_RE_NAME = re.compile(r'COMPOUND_STRING\("([^"]+)"\)')
_RE_POWER = re.compile(r'\.power\s*=\s*(.+?)\s*,')
_RE_TYPE = re.compile(r'\.type\s*=\s*(.+?)\s*,')
_RE_ACCURACY = re.compile(r'\.accuracy\s*=\s*(.+?)\s*,')
_RE_PP = re.compile(r'\.pp\s*=\s*(.+?)\s*,')
_RE_CATEGORY = re.compile(r'\.category\s*=\s*(\w+)')
_RE_PRIORITY = re.compile(r'\.priority\s*=\s*(-?\d+)')
_RE_TARGET = re.compile(r'\.target\s*=\s*(.+?)\s*,')
_RE_EFFECT = re.compile(r'\.effect\s*=\s*(\w+)')
_RE_BOOL_FLAG = re.compile(r'\.(\w+)\s*=\s*TRUE')

# Struct array name variants
_STRUCT_NAMES = ["gMovesInfo", "gBattleMoves"]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _moves_h_path(game_path):
    """Return path to moves_info.h (or battle_moves.h on older versions)."""
    p = os.path.join(game_path, "src", "data", "moves_info.h")
    if os.path.isfile(p):
        return p
    p2 = os.path.join(game_path, "src", "data", "battle_moves.h")
    if os.path.isfile(p2):
        return p2
    return p  # default


def _constants_h_path(game_path):
    """Return path to move constants header."""
    return os.path.join(game_path, "include", "constants", "moves.h")


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


def _load_move_ids(game_path):
    """Parse include/constants/moves.h for MOVE_* -> numeric ID mapping."""
    path = _constants_h_path(game_path)
    ids = {}
    if not os.path.isfile(path):
        return ids
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = _RE_MOVE_CONST.match(line)
            if m:
                ids[m.group(1)] = int(m.group(2))
    return ids


def _find_entry_end(lines, start):
    """Find the closing }, of an entry using brace depth tracking.

    Handles nested braces from ADDITIONAL_EFFECTS and other macros.
    """
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count('{') - lines[i].count('}')
        if depth <= 0 and i > start:
            return i
    return len(lines) - 1


def _extract_conditional_value(raw):
    """Extract a display-friendly value from a raw C expression.

    For simple values like "75", returns ("75", 75).
    For ternary conditionals like "B_UPDATED_MOVE_DATA >= GEN_4 ? 90 : 70",
    returns ("90", 90) -- the newer gen value.
    For non-numeric expressions, returns (raw, None).
    """
    raw = raw.strip().rstrip(",")
    # Simple integer
    if raw.lstrip("-").isdigit():
        return raw, int(raw)
    # Ternary: extract the first value after '?'
    ternary = re.search(r'\?\s*(-?\d+)\s*:', raw)
    if ternary:
        val = ternary.group(1)
        return val, int(val)
    # Enum constant
    if re.match(r'^[A-Z_]+$', raw):
        return raw, None
    return raw, None


def _extract_compound_string(lines, start_idx):
    """Extract a COMPOUND_STRING from lines starting at start_idx.

    Returns (text, end_idx) where text has newline escapes replaced with
    spaces and end_idx is the last line consumed.
    """
    text_parts = []
    i = start_idx
    depth = 0
    while i < len(lines):
        line = lines[i]
        if "COMPOUND_STRING(" in line:
            depth += 1
        # Extract quoted strings
        for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', line):
            text_parts.append(m.group(1))
        if depth > 0 and ")" in line:
            open_count = line.count("(")
            close_count = line.count(")")
            depth += open_count - close_count
            if depth <= 0:
                break
        i += 1
    text = "".join(text_parts)
    text = text.replace("\\n", " ").replace("\\p", " ").strip()
    return text, i


def _extract_flags(lines, start, end):
    """Collect boolean flag names (.flagName = TRUE) within an entry."""
    flags = []
    for i in range(start, end + 1):
        line = lines[i].strip()
        if line.startswith("#"):
            continue
        m = _RE_BOOL_FLAG.search(line)
        if m:
            flags.append(m.group(1))
    return flags


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_numeric_field(line, pattern, move, field, raw_field):
    """Parse a numeric field with conditional support. Returns new line index delta or 0."""
    m = pattern.search(line)
    if not m:
        return
    raw = m.group(1).strip()
    move[raw_field] = raw
    _, val = _extract_conditional_value(raw)
    move[field] = val if val is not None else 0


def _parse_type_field(line, move):
    """Parse the .type field from a line."""
    tm = _RE_TYPE.search(line)
    if not tm:
        return
    raw = tm.group(1).strip()
    move["type_raw"] = raw
    if raw in _TYPES or raw.startswith("TYPE_"):
        move["type"] = raw
    else:
        display, _ = _extract_conditional_value(raw)
        move["type"] = display


def _parse_target_field(line, move):
    """Parse the .target field from a line."""
    tgm = _RE_TARGET.search(line)
    if not tgm:
        return
    raw = tgm.group(1).strip()
    move["target_raw"] = raw
    move["target"] = raw


def _parse_name_line(line, move, **_kw):
    """Extract move name from .name line."""
    nm = _RE_NAME.search(line)
    if nm:
        move["name"] = nm.group(1)


def _parse_desc_line(lines, i, move):
    """Extract description. Returns new line index or None."""
    line = lines[i]
    if ".description" not in line or "=" not in line:
        return None
    if "COMPOUND_STRING" in line:
        desc, end_i = _extract_compound_string(lines, i)
        move["description"] = desc
        return end_i + 1
    dm = re.search(r'\.description\s*=\s*(\w+)', line)
    if dm:
        move["description"] = f"[{dm.group(1)}]"
    return None


def _parse_simple_fields(line, move):
    """Parse category, priority, effect, and additional_effects from a line."""
    stripped = line.strip()
    if ".category" in line:
        cm = _RE_CATEGORY.search(line)
        if cm:
            move["category"] = cm.group(1)
    if ".priority" in line:
        prm = _RE_PRIORITY.search(line)
        if prm:
            move["priority"] = int(prm.group(1))
    if ".effect" in line and "holdEffect" not in line:
        em = _RE_EFFECT.search(line)
        if em:
            move["effect"] = em.group(1)
    if "additionalEffects" in stripped or "ADDITIONAL_EFFECTS" in stripped:
        move["has_additional_effects"] = True


def _parse_line(lines, i, move):
    """Parse a single line of a move entry. Returns updated line index."""
    line = lines[i]
    if line.strip().startswith("#"):
        return i + 1

    if ".name" in line and "=" in line:
        _parse_name_line(line, move)

    desc_jump = _parse_desc_line(lines, i, move)
    if desc_jump is not None:
        return desc_jump

    if ".power" in line and "flingPower" not in line:
        _parse_numeric_field(line, _RE_POWER, move, "power", "power_raw")
    if ".type" in line and "contestCategory" not in line:
        _parse_type_field(line, move)
    if ".accuracy" in line:
        _parse_numeric_field(line, _RE_ACCURACY, move, "accuracy", "accuracy_raw")
    if ".pp" in line and (".pp " in line or ".pp\t" in line or ".pp=" in line):
        _parse_numeric_field(line, _RE_PP, move, "pp", "pp_raw")
    if ".target" in line:
        _parse_target_field(line, move)

    _parse_simple_fields(line, move)

    return i + 1


def _new_move_dict(constant, move_ids, start, end):
    """Create a fresh move dict with default values."""
    return {
        "constant": constant,
        "id": move_ids.get(constant, -1),
        "name": "",
        "description": "",
        "power": 0,
        "power_raw": "0",
        "type": "TYPE_NORMAL",
        "type_raw": "TYPE_NORMAL",
        "accuracy": 0,
        "accuracy_raw": "0",
        "pp": 0,
        "pp_raw": "0",
        "category": "DAMAGE_CATEGORY_STATUS",
        "priority": 0,
        "target": "MOVE_TARGET_SELECTED",
        "target_raw": "MOVE_TARGET_SELECTED",
        "effect": "",
        "flags": [],
        "has_additional_effects": False,
        "line_start": start,
        "line_end": end,
    }


def _parse_move_entry(lines, start, end, move_ids):
    """Parse a single [MOVE_*] = { ... } block into a dict."""
    m = _RE_ENTRY_START.match(lines[start])
    if not m:
        return None

    move = _new_move_dict(m.group(1), move_ids, start, end)

    i = start
    while i <= end:
        i = _parse_line(lines, i, move)

    move["flags"] = _extract_flags(lines, start, end)
    return move


def parse_moves(game_path):
    """Parse all moves from moves_info.h.

    Returns a list of move dicts sorted by numeric ID.
    """
    path = _moves_h_path(game_path)
    if not os.path.isfile(path):
        return []

    move_ids = _load_move_ids(game_path)

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    moves = []
    i = 0
    while i < len(lines):
        m = _RE_ENTRY_START.match(lines[i])
        if m:
            start = i
            end = _find_entry_end(lines, start)
            move = _parse_move_entry(lines, start, end, move_ids)
            if move and move["constant"] != "MOVE_NONE":
                moves.append(move)
            i = end + 1
        else:
            i += 1

    moves.sort(key=lambda x: x["id"])
    return moves


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _type_label(type_const):
    """Human-friendly type name."""
    return _TYPE_LABELS.get(type_const, type_const.replace("TYPE_", "").title()
                            if type_const.startswith("TYPE_") else type_const)


def _category_label(cat_const):
    """Human-friendly category name."""
    return _CATEGORY_LABELS.get(cat_const, cat_const)


def _target_label(target_const):
    """Human-friendly target name."""
    return _TARGET_LABELS.get(target_const,
                              target_const.replace("MOVE_TARGET_", "")
                              .replace("_", " ").title())


def _cat_short(cat_const):
    """Short category label for list view."""
    labels = {
        "DAMAGE_CATEGORY_PHYSICAL": "Phys",
        "DAMAGE_CATEGORY_SPECIAL": "Spec",
        "DAMAGE_CATEGORY_STATUS": "Stat",
    }
    return labels.get(cat_const, "???")


def _flag_label(flag_name):
    """Format a camelCase flag name as human-readable."""
    # Insert spaces before uppercase letters
    result = re.sub(r'([a-z])([A-Z])', r'\1 \2', flag_name)
    return result.title()


def _render_move_row(move, state, idx):
    """Format one row for the browser list."""
    mk = marker(state, idx)
    cid = f"#{move['id']:<5d}"
    name = f"{move['name']:<18s}"
    typ = f"{_type_label(move['type']):<10s}"
    cat = f"{_cat_short(move['category']):<5s}"
    power = f"{move['power']:>3d} pow" if move["power"] else "  --- "
    acc = f"{move['accuracy']:>3d} acc" if move["accuracy"] else "  --- "
    pp = f"{move['pp']:>2d} pp"
    return (f"  {mk} {DIM}{cid}{RST} {WHITE}{name}{RST} "
            f"{CYAN}{typ}{RST}{DIM}{cat}{RST} "
            f"{power}  {acc}  {pp}")


# ---------------------------------------------------------------------------
# Filter / search
# ---------------------------------------------------------------------------


def _apply_filters(moves, search, cat_filter, type_filter):
    """Apply search string and filters. Returns filtered list."""
    result = moves
    if cat_filter:
        result = [mv for mv in result if mv["category"] == cat_filter]
    if type_filter:
        result = [mv for mv in result if mv["type"] == type_filter]
    if search:
        q = search.lower()
        result = [mv for mv in result
                  if q in mv["name"].lower() or q in mv["constant"].lower()]
    return result


# ---------------------------------------------------------------------------
# Detail view
# ---------------------------------------------------------------------------


def _show_detail(move, settings, proj_name):
    """Show full detail for one move. Returns on keypress."""
    clear_screen()
    print_logo("Move Detail", proj_name=proj_name)
    print()
    print(f"  {WHITE}{move['constant']}{RST}  {DIM}(#{move['id']}){RST}")
    print()

    def _row(label, value, val_col=None):
        vc = val_col or CYAN
        print(f"  {DIM}{label:<16s}{RST} {vc}{value}{RST}")

    _row("Name:", move["name"], WHITE)
    _row("Type:", _type_label(move["type"]))
    if move["type_raw"] != move["type"]:
        _row("Type (raw):", move["type_raw"], DIM)
    _row("Category:", _category_label(move["category"]))
    _row("Power:", str(move["power"]))
    if move["power_raw"] != str(move["power"]):
        _row("Power (raw):", move["power_raw"], DIM)
    _row("Accuracy:", str(move["accuracy"]))
    if move["accuracy_raw"] != str(move["accuracy"]):
        _row("Accuracy (raw):", move["accuracy_raw"], DIM)
    _row("PP:", str(move["pp"]))
    if move["pp_raw"] != str(move["pp"]):
        _row("PP (raw):", move["pp_raw"], DIM)
    _row("Priority:", str(move["priority"]))
    _row("Target:", _target_label(move["target"]))
    _row("Effect:", move["effect"] or "(none)")
    if move["flags"]:
        labels = ", ".join(_flag_label(f) for f in move["flags"])
        _row("Flags:", labels)
    if move["has_additional_effects"]:
        _row("Secondary:", "Yes (see source)")
    print()
    desc = move["description"]
    if desc:
        _row("Description:", desc)
    print()
    print(f"  {_k('e')} Edit  {_k('q')} Back")
    print()


# ---------------------------------------------------------------------------
# Write-back --- surgical field replacement
# ---------------------------------------------------------------------------


def _find_field_line(lines, start, end, field_name):
    """Find the line index for a .field_name assignment within an entry.

    Returns the line index or -1 if not found.
    Skips lines inside #if/#else blocks if the field is duplicated.
    """
    for i in range(start, end + 1):
        stripped = lines[i].strip()
        if stripped.startswith("#"):
            continue
        if f".{field_name}" in stripped and "=" in stripped:
            return i
    return -1


def _format_compound_name(new_name):
    """Format a new name as COMPOUND_STRING(\"...\")."""
    return f'COMPOUND_STRING("{new_name}")'


def _format_description_value(new_desc):
    """Format a description as a COMPOUND_STRING block.

    Splits the description into lines of ~20 chars for the GBA text box.
    """
    words = new_desc.split()
    lines_out = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        if len(test) > 20 and current:
            lines_out.append(current)
            current = word
        else:
            current = test
    if current:
        lines_out.append(current)
    if not lines_out:
        lines_out = [""]
    parts = []
    for j, ln in enumerate(lines_out):
        if j < len(lines_out) - 1:
            parts.append(f'            "{ln}\\n"')
        else:
            parts.append(f'            "{ln}"')
    return "COMPOUND_STRING(\n" + "\n".join(parts) + ")"


def _write_field(game_path, move, field_name, new_value):
    """Surgically replace a single field value in moves_info.h.

    Returns True on success.
    """
    path = _moves_h_path(game_path)
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start = move["line_start"]
    end = move["line_end"]

    if field_name == "description":
        return _write_description(path, lines, start, end, new_value)

    line_idx = _find_field_line(lines, start, end, field_name)

    if field_name == "name":
        if line_idx == -1:
            return False
        old = lines[line_idx]
        indent = old[:len(old) - len(old.lstrip())]
        lines[line_idx] = f"{indent}.name = {_format_compound_name(new_value)},\n"

    elif field_name in ("power", "accuracy", "pp"):
        if line_idx == -1:
            return False
        old = lines[line_idx]
        indent = old[:len(old) - len(old.lstrip())]
        lines[line_idx] = f"{indent}.{field_name} = {new_value},\n"

    elif field_name == "priority":
        if line_idx == -1:
            return False
        old = lines[line_idx]
        indent = old[:len(old) - len(old.lstrip())]
        lines[line_idx] = f"{indent}.priority = {new_value},\n"

    elif field_name in ("type", "category", "target"):
        if line_idx == -1:
            return False
        old = lines[line_idx]
        indent = old[:len(old) - len(old.lstrip())]
        lines[line_idx] = f"{indent}.{field_name} = {new_value},\n"

    else:
        return False

    return _write_atomic(path, lines)


def _write_description(path, lines, start, end, new_desc):
    """Replace a COMPOUND_STRING description block."""
    desc_start = -1
    for i in range(start, end + 1):
        if ".description" in lines[i] and "=" in lines[i]:
            desc_start = i
            break
    if desc_start == -1:
        return False

    if "COMPOUND_STRING" in lines[desc_start]:
        desc_end = desc_start
        depth = 0
        for i in range(desc_start, end + 1):
            depth += lines[i].count("(") - lines[i].count(")")
            if depth <= 0:
                desc_end = i
                break
        indent = lines[desc_start][:len(lines[desc_start]) - len(lines[desc_start].lstrip())]
        new_block = f"{indent}.description = {_format_description_value(new_desc)},\n"
        lines[desc_start:desc_end + 1] = [new_block]
    else:
        indent = lines[desc_start][:len(lines[desc_start]) - len(lines[desc_start].lstrip())]
        new_block = f"{indent}.description = {_format_description_value(new_desc)},\n"
        lines[desc_start] = new_block

    return _write_atomic(path, lines)


# ---------------------------------------------------------------------------
# Edit flow
# ---------------------------------------------------------------------------


def _edit_move(game_path, move, settings, proj_name):
    """Interactive edit flow for a single move. Returns True if changed."""
    while True:
        clear_screen()
        print_logo("Edit Move", proj_name=proj_name)
        print()
        print(f"  {WHITE}{move['name']}{RST}  {DIM}({move['constant']}){RST}")
        print()
        for idx, (field, label) in enumerate(_EDITABLE_FIELDS, 1):
            val = _field_display(move, field)
            print(f"  {_k(str(idx))} {label:<14s} {DIM}{val}{RST}")
        print()
        print(f"  {_k('q')} Cancel")
        print()
        try:
            raw = input(f"  {GOLD}>{RST} ").strip()
        except (EOFError, KeyboardInterrupt):
            return False
        if raw.lower() == "q" or raw == "":
            return False

        if not raw.isdigit():
            continue
        choice = int(raw)
        if choice < 1 or choice > len(_EDITABLE_FIELDS):
            continue

        field_name, label = _EDITABLE_FIELDS[choice - 1]
        changed = _edit_single_field(game_path, move, field_name, label,
                                     settings, proj_name)
        if changed:
            return True
    return False


def _display_conditional(move, field, raw_field, formatter=str):
    """Display a field that may have a conditional raw value."""
    display = formatter(move[field])
    if move[raw_field] != str(move[field]):
        display += "  (conditional)"
    return display


def _field_display(move, field):
    """Return display string for a field."""
    if field == "name":
        return move["name"]
    if field == "type":
        return _display_conditional(move, "type", "type_raw", _type_label)
    if field == "category":
        return _category_label(move["category"])
    if field == "target":
        return _target_label(move["target"])
    if field in ("power", "accuracy", "pp"):
        return _display_conditional(move, field, f"{field}_raw")
    if field == "priority":
        return str(move["priority"])
    if field == "description":
        desc = move["description"]
        if len(desc) > 50:
            return desc[:47] + "..."
        return desc or "(none)"
    return str(move.get(field, ""))


def _edit_single_field(game_path, move, field_name, label, settings, proj_name):
    """Edit one field. Returns True if a write was made."""
    print()
    if field_name == "name":
        return _edit_name(game_path, move)
    elif field_name == "type":
        return _edit_type(game_path, move)
    elif field_name == "category":
        return _edit_category(game_path, move)
    elif field_name == "power":
        return _edit_int_field(game_path, move, "power", "Power", 0, 250)
    elif field_name == "accuracy":
        return _edit_int_field(game_path, move, "accuracy", "Accuracy", 0, 100)
    elif field_name == "pp":
        return _edit_int_field(game_path, move, "pp", "PP", 1, 40)
    elif field_name == "priority":
        return _edit_priority(game_path, move)
    elif field_name == "target":
        return _edit_target(game_path, move)
    elif field_name == "description":
        return _edit_description(game_path, move)
    return False


def _edit_name(game_path, move):
    """Edit move name."""
    print(f"  Current: {WHITE}{move['name']}{RST}")
    try:
        new = input(f"  New name (max 16 chars): ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not new:
        return False
    if len(new) > 16:
        print(f"  {RED}Name too long (max 16 chars).{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False
    if _write_field(game_path, move, "name", new):
        move["name"] = new
        print(f"  {GREEN}Name updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_type(game_path, move):
    """Edit move type via picker."""
    print(f"  Current: {CYAN}{_type_label(move['type'])}{RST}")
    if move["type_raw"] != move["type"]:
        print(f"  {DIM}Warning: this is a conditional expression:{RST}")
        print(f"  {DIM}{move['type_raw']}{RST}")
        print(f"  {DIM}Editing will replace it with a simple value.{RST}")
    print()
    for idx, t in enumerate(_TYPES, 1):
        mk = "*" if t == move["type"] else " "
        print(f"  {_k(str(idx)):>5s} {mk} {_type_label(t)}")
    print()
    try:
        raw = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not raw.isdigit():
        return False
    choice = int(raw)
    if choice < 1 or choice > len(_TYPES):
        return False
    new_type = _TYPES[choice - 1]
    if new_type == move["type"] and move["type_raw"] == move["type"]:
        return False
    if _write_field(game_path, move, "type", new_type):
        move["type"] = new_type
        move["type_raw"] = new_type
        print(f"  {GREEN}Type updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_category(game_path, move):
    """Edit move category via picker."""
    print(f"  Current: {CYAN}{_category_label(move['category'])}{RST}")
    print()
    for idx, cat in enumerate(_CATEGORIES, 1):
        mk = "*" if cat == move["category"] else " "
        print(f"  {_k(str(idx))} {mk} {_category_label(cat)}")
    print()
    try:
        raw = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not raw.isdigit():
        return False
    choice = int(raw)
    if choice < 1 or choice > len(_CATEGORIES):
        return False
    new_cat = _CATEGORIES[choice - 1]
    if new_cat == move["category"]:
        return False
    if _write_field(game_path, move, "category", new_cat):
        move["category"] = new_cat
        print(f"  {GREEN}Category updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_priority(game_path, move):
    """Edit move priority."""
    print(f"  Current: {CYAN}{move['priority']}{RST}")
    try:
        raw = input(f"  New priority (-7 to +5): ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not raw:
        return False
    # Handle optional + prefix
    try:
        val = int(raw)
    except ValueError:
        return False
    if val < -7 or val > 5:
        print(f"  {RED}Priority must be -7 to +5.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False
    if _write_field(game_path, move, "priority", str(val)):
        move["priority"] = val
        print(f"  {GREEN}Priority updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_target(game_path, move):
    """Edit move target via picker."""
    print(f"  Current: {CYAN}{_target_label(move['target'])}{RST}")
    print()
    for idx, tgt in enumerate(_TARGETS, 1):
        mk = "*" if tgt == move["target"] else " "
        print(f"  {_k(str(idx)):>5s} {mk} {_target_label(tgt)}")
    print()
    try:
        raw = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not raw.isdigit():
        return False
    choice = int(raw)
    if choice < 1 or choice > len(_TARGETS):
        return False
    new_target = _TARGETS[choice - 1]
    if new_target == move["target"] and move["target_raw"] == move["target"]:
        return False
    if _write_field(game_path, move, "target", new_target):
        move["target"] = new_target
        move["target_raw"] = new_target
        print(f"  {GREEN}Target updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_int_field(game_path, move, field_name, label, min_val, max_val):
    """Edit an integer field with range validation."""
    current = move.get(field_name, 0)
    raw_field = f"{field_name}_raw"
    current_raw = move.get(raw_field, str(current))
    print(f"  Current {label}: {CYAN}{current}{RST}")
    if current_raw != str(current):
        print(f"  {DIM}Warning: this is a conditional expression:{RST}")
        print(f"  {DIM}{current_raw}{RST}")
        print(f"  {DIM}Editing will replace it with a simple value.{RST}")
    try:
        raw = input(f"  New value ({min_val}-{max_val}): ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not raw or not raw.isdigit():
        return False
    val = int(raw)
    if val < min_val or val > max_val:
        print(f"  {RED}Value must be {min_val}-{max_val}.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False
    if _write_field(game_path, move, field_name, str(val)):
        move[field_name] = val
        move[raw_field] = str(val)
        print(f"  {GREEN}{label} updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_description(game_path, move):
    """Edit move description."""
    print(f"  Current: {DIM}{move['description']}{RST}")
    print(f"  {DIM}Enter plain text (no \\n needed, auto-wrapped to ~20 char lines).{RST}")
    try:
        new = input(f"  New description: ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not new:
        return False
    if _write_field(game_path, move, "description", new):
        move["description"] = new
        print(f"  {GREEN}Description updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


# ---------------------------------------------------------------------------
# Browser UI
# ---------------------------------------------------------------------------


def _render_status_bar(filtered, all_moves, search, cat_filter, type_filter):
    """Print the status bar with active filters."""
    parts = [f"{DIM}{len(filtered)}/{len(all_moves)} moves{RST}"]
    if search:
        parts.append(f"{CYAN}search: {search}{RST}")
    if cat_filter:
        parts.append(f"{CYAN}{_category_label(cat_filter)}{RST}")
    if type_filter:
        parts.append(f"{CYAN}{_type_label(type_filter)}{RST}")
    print(f"  {' | '.join(parts)}")
    print()


def _render_list(filtered, state, nav):
    """Render the scrolling move list."""
    if not filtered:
        print(f"  {DIM}No matching moves.{RST}")
    else:
        oa = overflow_above(state)
        if oa:
            print(oa)
        start, end = visible_range(state)
        for idx in range(start, end):
            print(_render_move_row(filtered[idx], state, idx))
        ob = overflow_below(state)
        if ob:
            print(ob)
    print()
    print(footer_hint(nav_keys=nav,
                       extra=f"  [/]search  [f]ilter  [t]ype  [e]dit"))
    print()


def _handle_detail_view(move, game_path, settings, proj_name):
    """Show detail view with optional edit. Returns True if changed."""
    _show_detail(move, settings, proj_name)
    try:
        detail_raw = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if detail_raw == "e":
        return _edit_move(game_path, move, settings, proj_name)
    return False


def _browser(game_path, settings, proj_name):
    """Main move browser with scrolling, search, and filter."""
    nav = _nav_keys(settings)
    page_size = settings.get("map_list_page_size", 20)

    all_moves = parse_moves(game_path)
    if not all_moves:
        print(f"  {RED}No moves found in {_moves_h_path(game_path)}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    search = ""
    cat_filter = ""
    type_filter = ""
    cat_idx = 0
    type_idx = 0
    changed = False

    filtered = _apply_filters(all_moves, search, cat_filter, type_filter)
    state = ListState(len(filtered), page_size=page_size)

    while True:
        filtered = _apply_filters(all_moves, search, cat_filter, type_filter)
        state.total = len(filtered)
        guard_bounds(state)

        clear_screen()
        print_logo("Move Editor", proj_name=proj_name)
        _render_status_bar(filtered, all_moves, search, cat_filter, type_filter)
        _render_list(filtered, state, nav)

        try:
            raw = input(f"  {GOLD}>{RST} ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        key = raw.lower()

        if key == "/":
            try:
                search = input(f"  Search: ").strip()
            except (EOFError, KeyboardInterrupt):
                search = ""
            state.selected = 0
            state.scroll_top = 0
            continue

        if key == "f":
            cat_idx = (cat_idx + 1) % (len(_CATEGORIES) + 1)
            cat_filter = _CATEGORIES[cat_idx - 1] if cat_idx > 0 else ""
            state.selected = 0
            state.scroll_top = 0
            continue

        if key == "t":
            type_idx = (type_idx + 1) % (len(_TYPES) + 1)
            type_filter = _TYPES[type_idx - 1] if type_idx > 0 else ""
            state.selected = 0
            state.scroll_top = 0
            continue

        if key == "e" and filtered:
            if _edit_move(game_path, filtered[state.selected], settings, proj_name):
                changed = True
                all_moves = parse_moves(game_path)
            continue

        action = handle_input(state, raw, nav_keys=nav)
        if action == "quit":
            break
        if action in ("open", "jump_act") and filtered:
            if _handle_detail_view(filtered[state.selected], game_path,
                                   settings, proj_name):
                changed = True
                all_moves = parse_moves(game_path)

    if changed:
        _offer_build(game_path=game_path, trigger="move_edit")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def move_editor_menu(game_path, settings=None, proj_name=None):
    """Main entry point for the Move Editor.

    Called from __main__.py via 'torch moves' or main menu.
    """
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if proj_name is None:
        proj_name = ""

    if not game_path or not os.path.isdir(game_path):
        print(f"  {RED}Game path not found: {game_path}{RST}")
        return

    # Check expansion (move editor needs expansion, not vanilla)
    try:
        from torch.expansion_compat import detect_expansion_version
        version = detect_expansion_version(game_path)
        if version is None:
            print(f"  {RED}Move Editor requires pokeemerald-expansion.{RST}")
            print(f"  {DIM}Vanilla pokeemerald uses a different move struct format.{RST}")
            input(f"  {DIM}Press Enter{RST} > ")
            return
    except ImportError:
        pass

    moves_path = _moves_h_path(game_path)
    if not os.path.isfile(moves_path):
        print(f"  {RED}moves_info.h not found at {moves_path}{RST}")
        return

    _browser(game_path, settings, proj_name)
