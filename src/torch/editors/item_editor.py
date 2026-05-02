"""TORCH Item Editor — browse and edit game items.

Parses src/data/items.h to extract all item entries, presents a scrolling
browser with search/filter, and allows surgical field edits with atomic
write-back.
"""
# TORCH_MODULE: Item Editor
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

_POCKETS = [
    "POCKET_ITEMS", "POCKET_POKE_BALLS", "POCKET_TM_HM",
    "POCKET_BERRIES", "POCKET_KEY_ITEMS",
]

_POCKET_LABELS = {
    "POCKET_ITEMS": "Items",
    "POCKET_POKE_BALLS": "Balls",
    "POCKET_TM_HM": "TMs",
    "POCKET_BERRIES": "Berries",
    "POCKET_KEY_ITEMS": "Key Items",
}

# Common sort types found in items.h
_SORT_TYPES = [
    "ITEM_TYPE_UNCATEGORIZED",
    "ITEM_TYPE_HEALTH_RECOVERY",
    "ITEM_TYPE_STATUS_RECOVERY",
    "ITEM_TYPE_PP_RECOVERY",
    "ITEM_TYPE_STAT_BOOST_DRINK",
    "ITEM_TYPE_VITAMIN",
    "ITEM_TYPE_LEVEL_UP_ITEM",
    "ITEM_TYPE_FIELD_USE",
    "ITEM_TYPE_BATTLE_ITEM",
    "ITEM_TYPE_HELD_ITEM",
    "ITEM_TYPE_EVOLUTION_STONE",
    "ITEM_TYPE_SELLABLE",
    "ITEM_TYPE_PLATE",
    "ITEM_TYPE_MEMORY",
    "ITEM_TYPE_MEGA_STONE",
    "ITEM_TYPE_Z_CRYSTAL",
    "ITEM_TYPE_GEM",
    "ITEM_TYPE_BERRY",
    "ITEM_TYPE_MAIL",
    "ITEM_TYPE_TREASURE",
    "ITEM_TYPE_INCENSE",
]

_SORT_LABELS = {s: s.replace("ITEM_TYPE_", "").replace("_", " ").title()
                for s in _SORT_TYPES}

_EDITABLE_FIELDS = [
    ("name", "Name"),
    ("price", "Price"),
    ("description", "Description"),
    ("pocket", "Pocket"),
    ("sort_type", "Sort Type"),
    ("hold_effect", "Hold Effect"),
    ("hold_effect_param", "Hold Effect Param"),
    ("fling_power", "Fling Power"),
]

# ---------------------------------------------------------------------------
# Parser — regex patterns
# ---------------------------------------------------------------------------

_RE_ENTRY_START = re.compile(r'^\s*\[(ITEM_\w+)\]\s*=')
_RE_ENTRY_END = re.compile(r'^\s*\},')
_RE_NAME = re.compile(r'ITEM_NAME\("([^"]+)"\)')
_RE_PLURAL = re.compile(r'ITEM_PLURAL_NAME\("([^"]+)"\)')
_RE_PRICE = re.compile(r'\.price\s*=\s*(.+?),?\s*$')
_RE_POCKET = re.compile(r'\.pocket\s*=\s*(\w+)')
_RE_SORT = re.compile(r'\.sortType\s*=\s*(\w+)')
_RE_HOLD = re.compile(r'\.holdEffect\s*=\s*(\w+)')
_RE_HOLD_PARAM = re.compile(r'\.holdEffectParam\s*=\s*(\d+)')
_RE_FLING = re.compile(r'\.flingPower\s*=\s*(\d+)')
_RE_TYPE = re.compile(r'\.type\s*=\s*(\w+)')
_RE_BATTLE = re.compile(r'\.battleUsage\s*=\s*(\w+)')
_RE_IMPORTANCE = re.compile(r'\.importance\s*=\s*(\d+)')
_RE_COMPOUND_START = re.compile(r'COMPOUND_STRING\(')
_RE_ITEM_CONST = re.compile(r'#define\s+(ITEM_\w+)\s+(\d+)')


# ---------------------------------------------------------------------------
# Parser functions
# ---------------------------------------------------------------------------


def _items_h_path(game_path):
    """Return path to items.h."""
    return os.path.join(game_path, "src", "data", "items.h")


def _constants_h_path(game_path):
    """Return path to item constants header."""
    return os.path.join(game_path, "include", "constants", "items.h")


def _hold_effects_h_path(game_path):
    """Return path to hold_effects.h."""
    return os.path.join(game_path, "include", "constants", "hold_effects.h")


def _load_item_ids(game_path):
    """Parse include/constants/items.h for ITEM_* -> numeric ID mapping."""
    path = _constants_h_path(game_path)
    ids = {}
    if not os.path.isfile(path):
        return ids
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = _RE_ITEM_CONST.match(line)
            if m:
                ids[m.group(1)] = int(m.group(2))
    return ids


def _load_hold_effects(game_path):
    """Parse hold_effects.h and return list of HOLD_EFFECT_* constants."""
    path = _hold_effects_h_path(game_path)
    effects = []
    if not os.path.isfile(path):
        return effects
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = re.match(r'(HOLD_EFFECT_\w+)', line)
            if m:
                effects.append(m.group(1))
    return effects


def _extract_price_display(raw_price):
    """Extract a display-friendly price from a raw price expression.

    For simple integers, returns the number string.
    For ternary conditionals like '(I_PRICE >= GEN_7) ? 800 : 1200',
    returns the first value (newer gen value).
    """
    raw = raw_price.strip().rstrip(",")
    # Simple integer
    if raw.isdigit():
        return raw
    # Ternary: extract the first value after '?'
    ternary = re.search(r'\?\s*(\d+)\s*:', raw)
    if ternary:
        return ternary.group(1)
    return raw


def _extract_compound_string(lines, start_idx):
    """Extract a COMPOUND_STRING description from lines starting at start_idx.

    Returns (text, end_idx) where text has \\n replaced with spaces and
    end_idx is the last line consumed.
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
            # Check if this closes the COMPOUND_STRING
            open_count = line.count("(")
            close_count = line.count(")")
            depth += open_count - close_count
            if depth <= 0:
                break
        i += 1
    text = "".join(text_parts)
    # Replace literal \n with space for display
    text = text.replace("\\n", " ").replace("\\p", " ").strip()
    return text, i


def _extract_simple_fields(item, line):
    """Extract simple single-line fields from a line into item dict."""
    nm = _RE_NAME.search(line)
    if nm:
        item["name"] = nm.group(1)
    pm = _RE_PLURAL.search(line)
    if pm:
        item["plural_name"] = pm.group(1)
    pr = _RE_PRICE.search(line)
    if pr and ".price" in line:
        raw = pr.group(1).strip()
        item["price"] = raw
        item["price_display"] = _extract_price_display(raw)
    pk = _RE_POCKET.search(line)
    if pk:
        item["pocket"] = pk.group(1)
    st = _RE_SORT.search(line)
    if st:
        item["sort_type"] = st.group(1)
    he = _RE_HOLD.search(line)
    if he and "holdEffectParam" not in line:
        item["hold_effect"] = he.group(1)
    hp = _RE_HOLD_PARAM.search(line)
    if hp:
        item["hold_effect_param"] = int(hp.group(1))
    fp = _RE_FLING.search(line)
    if fp:
        item["fling_power"] = int(fp.group(1))
    tp = _RE_TYPE.search(line)
    if tp:
        item["type"] = tp.group(1)
    bu = _RE_BATTLE.search(line)
    if bu:
        item["battle_usage"] = bu.group(1)
    imp = _RE_IMPORTANCE.search(line)
    if imp:
        item["importance"] = int(imp.group(1))


def _parse_item_entry(lines, start, end, item_ids):
    """Parse a single [ITEM_*] = { ... } block into a dict."""
    m = _RE_ENTRY_START.match(lines[start])
    if not m:
        return None
    constant = m.group(1)

    item = {
        "constant": constant,
        "id": item_ids.get(constant, -1),
        "name": "", "plural_name": "",
        "price": "0", "price_display": "0",
        "description": "", "pocket": "", "sort_type": "",
        "hold_effect": "", "hold_effect_param": 0,
        "importance": 0, "fling_power": 0,
        "type": "", "battle_usage": "",
        "line_start": start, "line_end": end,
    }

    i = start
    while i <= end:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("#"):
            i += 1
            continue

        _extract_simple_fields(item, line)

        # Description (multi-line COMPOUND_STRING)
        if _RE_COMPOUND_START.search(line) and ".description" in line:
            desc, end_i = _extract_compound_string(lines, i)
            item["description"] = desc
            i = end_i
        elif ".description" in line and "COMPOUND_STRING" not in line:
            dm = re.search(r'\.description\s*=\s*(\w+)', line)
            if dm:
                item["description"] = f"[{dm.group(1)}]"

        i += 1

    return item


def parse_items(game_path):
    """Parse all items from src/data/items.h.

    Returns a list of item dicts sorted by numeric ID.
    """
    path = _items_h_path(game_path)
    if not os.path.isfile(path):
        return []

    item_ids = _load_item_ids(game_path)

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    items = []
    i = 0
    while i < len(lines):
        m = _RE_ENTRY_START.match(lines[i])
        if m:
            start = i
            # Skip to the opening { of the entry body
            j = i + 1
            while j < len(lines) and lines[j].strip() != "{":
                j += 1
            # j now points at the opening {, search for the closing },
            j += 1
            brace_depth = 0
            while j < len(lines):
                line_s = lines[j].strip()
                if line_s == "{":
                    brace_depth += 1
                if _RE_ENTRY_END.match(lines[j]):
                    if brace_depth == 0:
                        break
                    brace_depth -= 1
                j += 1
            end = min(j, len(lines) - 1)
            item = _parse_item_entry(lines, start, end, item_ids)
            if item and item["constant"] != "ITEM_NONE":
                items.append(item)
            i = end + 1
        else:
            i += 1

    items.sort(key=lambda x: x["id"])
    return items


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _pocket_label(pocket):
    """Human-friendly pocket name."""
    return _POCKET_LABELS.get(pocket, pocket)


def _sort_label(sort_type):
    """Human-friendly sort type name."""
    return _SORT_LABELS.get(sort_type, sort_type or "(none)")


def _hold_label(hold_effect):
    """Human-friendly hold effect name."""
    if not hold_effect:
        return "(none)"
    return hold_effect.replace("HOLD_EFFECT_", "").replace("_", " ").title()


def _render_item_row(item, state, idx):
    """Format one row for the browser list."""
    mk = marker(state, idx)
    cid = f"#{item['id']:<5d}"
    name = f"{item['name']:<22s}"
    price = f"{item['price_display']:>6s}g"
    pocket = _pocket_label(item["pocket"])
    return f"  {mk} {DIM}{cid}{RST} {WHITE}{name}{RST} {CYAN}{price}{RST}  {DIM}{pocket}{RST}"


# ---------------------------------------------------------------------------
# Filter / search
# ---------------------------------------------------------------------------


def _apply_filters(items, search, pocket_filter, sort_filter):
    """Apply search string and filters. Returns filtered list."""
    result = items
    if pocket_filter:
        result = [it for it in result if it["pocket"] == pocket_filter]
    if sort_filter:
        result = [it for it in result if it["sort_type"] == sort_filter]
    if search:
        q = search.lower()
        result = [it for it in result
                  if q in it["name"].lower() or q in it["constant"].lower()]
    return result


# ---------------------------------------------------------------------------
# Detail view
# ---------------------------------------------------------------------------


def _show_detail(item, settings, proj_name):
    """Show full detail for one item. Returns on keypress."""
    clear_screen()
    print_logo("Item Detail", proj_name=proj_name)
    print()
    print(f"  {WHITE}{item['constant']}{RST}  {DIM}(#{item['id']}){RST}")
    print()

    def _row(label, value, val_col=None):
        vc = val_col or CYAN
        print(f"  {DIM}{label:<16s}{RST} {vc}{value}{RST}")

    _row("Name:", item["name"], WHITE)
    if item["plural_name"]:
        _row("Plural:", item["plural_name"])
    _row("Price:", item["price_display"] + "g")
    if item["price"] != item["price_display"]:
        _row("Price (raw):", item["price"], DIM)
    _row("Pocket:", _pocket_label(item["pocket"]))
    _row("Sort Type:", _sort_label(item["sort_type"]))
    _row("Hold Effect:", _hold_label(item["hold_effect"]))
    if item["hold_effect"]:
        _row("Hold Param:", str(item["hold_effect_param"]))
    _row("Fling Power:", str(item["fling_power"]))
    _row("Importance:", str(item["importance"]))
    _row("Type:", item["type"] or "(none)")
    if item["battle_usage"]:
        _row("Battle Usage:", item["battle_usage"])
    print()
    desc = item["description"]
    if desc:
        _row("Description:", desc)
    print()
    print(f"  {_k('e')} Edit  {_k('q')} Back")
    print()


# ---------------------------------------------------------------------------
# Write-back — surgical field replacement
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


def _format_name_value(new_name):
    """Format a new name as ITEM_NAME(\"...\")."""
    return f'ITEM_NAME("{new_name}")'


def _format_description_value(new_desc):
    """Format a description as a COMPOUND_STRING block.

    Splits the description into lines of ~20 chars for the GBA text box
    (3 lines of ~20 chars each).
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
    # Pad to at least 1 line
    if not lines_out:
        lines_out = [""]
    # Build COMPOUND_STRING with proper escapes
    parts = []
    for j, ln in enumerate(lines_out):
        if j < len(lines_out) - 1:
            parts.append(f'            "{ln}\\n"')
        else:
            parts.append(f'            "{ln}"')
    return "COMPOUND_STRING(\n" + "\n".join(parts) + ")"


def _write_field(game_path, item, field_name, new_value):
    """Surgically replace a single field value in items.h.

    Returns True on success.
    """
    path = _items_h_path(game_path)
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start = item["line_start"]
    end = item["line_end"]

    if field_name == "description":
        return _write_description(path, lines, start, end, new_value)

    line_idx = _find_field_line(lines, start, end, field_name)

    if field_name == "name":
        if line_idx == -1:
            return False
        old = lines[line_idx]
        indent = old[:len(old) - len(old.lstrip())]
        lines[line_idx] = f"{indent}.name = {_format_name_value(new_value)},\n"

    elif field_name == "price":
        if line_idx == -1:
            return False
        old = lines[line_idx]
        indent = old[:len(old) - len(old.lstrip())]
        lines[line_idx] = f"{indent}.price = {new_value},\n"

    elif field_name in ("pocket", "sort_type", "hold_effect", "type"):
        c_field = _py_to_c_field(field_name)
        if line_idx == -1:
            # Field doesn't exist — insert it before the closing },
            insert_at = end
            indent = "        "
            lines.insert(insert_at, f"{indent}.{c_field} = {new_value},\n")
        else:
            old = lines[line_idx]
            indent = old[:len(old) - len(old.lstrip())]
            lines[line_idx] = f"{indent}.{c_field} = {new_value},\n"

    elif field_name in ("hold_effect_param", "fling_power", "importance"):
        c_field = _py_to_c_field(field_name)
        if line_idx == -1:
            insert_at = end
            indent = "        "
            lines.insert(insert_at, f"{indent}.{c_field} = {new_value},\n")
        else:
            old = lines[line_idx]
            indent = old[:len(old) - len(old.lstrip())]
            lines[line_idx] = f"{indent}.{c_field} = {new_value},\n"
    else:
        return False

    return _write_atomic(path, lines)


def _write_description(path, lines, start, end, new_desc):
    """Replace a COMPOUND_STRING description block."""
    # Find the .description line
    desc_start = -1
    for i in range(start, end + 1):
        if ".description" in lines[i] and "=" in lines[i]:
            desc_start = i
            break
    if desc_start == -1:
        return False

    # If it's a COMPOUND_STRING, find its end
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
        # Simple variable reference — replace with COMPOUND_STRING
        indent = lines[desc_start][:len(lines[desc_start]) - len(lines[desc_start].lstrip())]
        new_block = f"{indent}.description = {_format_description_value(new_desc)},\n"
        lines[desc_start] = new_block

    return _write_atomic(path, lines)


def _py_to_c_field(field_name):
    """Map Python field name to C struct field name."""
    mapping = {
        "sort_type": "sortType",
        "hold_effect": "holdEffect",
        "hold_effect_param": "holdEffectParam",
        "fling_power": "flingPower",
        "battle_usage": "battleUsage",
        "plural_name": "pluralName",
    }
    return mapping.get(field_name, field_name)


# ---------------------------------------------------------------------------
# Edit flow
# ---------------------------------------------------------------------------


def _edit_item(game_path, item, settings, proj_name):
    """Interactive edit flow for a single item. Returns True if changed."""
    while True:
        clear_screen()
        print_logo("Edit Item", proj_name=proj_name)
        print()
        print(f"  {WHITE}{item['name']}{RST}  {DIM}({item['constant']}){RST}")
        print()
        for idx, (field, label) in enumerate(_EDITABLE_FIELDS, 1):
            val = _field_display(item, field)
            print(f"  {_k(str(idx))} {label:<18s} {DIM}{val}{RST}")
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
        changed = _edit_single_field(game_path, item, field_name, label,
                                     settings, proj_name)
        if changed:
            return True
    return False


def _field_display(item, field):
    """Return display string for a field."""
    if field == "pocket":
        return _pocket_label(item["pocket"])
    if field == "sort_type":
        return _sort_label(item["sort_type"])
    if field == "hold_effect":
        return _hold_label(item["hold_effect"])
    if field == "price":
        display = item["price_display"] + "g"
        if item["price"] != item["price_display"]:
            display += f"  (conditional: {item['price']})"
        return display
    if field == "description":
        desc = item["description"]
        if len(desc) > 50:
            return desc[:47] + "..."
        return desc or "(none)"
    return str(item.get(field, ""))


def _edit_single_field(game_path, item, field_name, label, settings, proj_name):
    """Edit one field. Returns True if a write was made."""
    print()
    if field_name == "name":
        return _edit_name(game_path, item)
    elif field_name == "price":
        return _edit_price(game_path, item)
    elif field_name == "description":
        return _edit_description(game_path, item)
    elif field_name == "pocket":
        return _edit_pocket(game_path, item)
    elif field_name == "sort_type":
        return _edit_sort_type(game_path, item)
    elif field_name == "hold_effect":
        return _edit_hold_effect(game_path, item)
    elif field_name == "hold_effect_param":
        return _edit_int_field(game_path, item, "hold_effect_param",
                               "Hold Effect Param", 0, 255)
    elif field_name == "fling_power":
        return _edit_int_field(game_path, item, "fling_power",
                               "Fling Power", 0, 150)
    return False


def _edit_name(game_path, item):
    """Edit item name."""
    print(f"  Current: {WHITE}{item['name']}{RST}")
    try:
        new = input(f"  New name (max 19 chars): ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not new:
        return False
    if len(new) > 19:
        print(f"  {RED}Name too long (max 19 chars).{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False
    if _write_field(game_path, item, "name", new):
        item["name"] = new
        print(f"  {GREEN}Name updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_price(game_path, item):
    """Edit item price."""
    print(f"  Current: {CYAN}{item['price_display']}g{RST}")
    if item["price"] != item["price_display"]:
        print(f"  {DIM}Warning: this is a conditional expression:{RST}")
        print(f"  {DIM}{item['price']}{RST}")
        print(f"  {DIM}Editing will replace it with a simple value.{RST}")
    try:
        new = input(f"  New price: ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not new or not new.isdigit():
        return False
    if _write_field(game_path, item, "price", new):
        item["price"] = new
        item["price_display"] = new
        print(f"  {GREEN}Price updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_description(game_path, item):
    """Edit item description."""
    print(f"  Current: {DIM}{item['description']}{RST}")
    print(f"  {DIM}Enter plain text (no \\n needed, auto-wrapped to 3 lines).{RST}")
    try:
        new = input(f"  New description: ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not new:
        return False
    if _write_field(game_path, item, "description", new):
        item["description"] = new
        print(f"  {GREEN}Description updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_pocket(game_path, item):
    """Edit pocket via picker."""
    print(f"  Current: {CYAN}{_pocket_label(item['pocket'])}{RST}")
    print()
    for idx, pocket in enumerate(_POCKETS, 1):
        mk = "*" if pocket == item["pocket"] else " "
        print(f"  {_k(str(idx))} {mk} {_pocket_label(pocket)}")
    print()
    try:
        raw = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not raw.isdigit():
        return False
    choice = int(raw)
    if choice < 1 or choice > len(_POCKETS):
        return False
    new_pocket = _POCKETS[choice - 1]
    if new_pocket == item["pocket"]:
        return False
    if _write_field(game_path, item, "pocket", new_pocket):
        item["pocket"] = new_pocket
        print(f"  {GREEN}Pocket updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_sort_type(game_path, item):
    """Edit sort type via picker."""
    print(f"  Current: {CYAN}{_sort_label(item['sort_type'])}{RST}")
    print()
    for idx, st in enumerate(_SORT_TYPES, 1):
        mk = "*" if st == item["sort_type"] else " "
        print(f"  {_k(str(idx))} {mk} {_sort_label(st)}")
    print()
    try:
        raw = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not raw.isdigit():
        return False
    choice = int(raw)
    if choice < 1 or choice > len(_SORT_TYPES):
        return False
    new_sort = _SORT_TYPES[choice - 1]
    if new_sort == item["sort_type"]:
        return False
    if _write_field(game_path, item, "sort_type", new_sort):
        item["sort_type"] = new_sort
        print(f"  {GREEN}Sort type updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_hold_effect(game_path, item):
    """Edit hold effect via searchable picker."""
    effects = _load_hold_effects(game_path)
    if not effects:
        print(f"  {RED}Could not load hold effects.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    print(f"  Current: {CYAN}{_hold_label(item['hold_effect'])}{RST}")
    print(f"  {DIM}Search or enter number (blank to clear):{RST}")
    try:
        query = input(f"  Search: ").strip()
    except (EOFError, KeyboardInterrupt):
        return False

    if query == "":
        # Clear hold effect — remove the field
        if not item["hold_effect"]:
            return False
        # For clearing, we'd need to remove the line — set to HOLD_EFFECT_NONE
        if _write_field(game_path, item, "hold_effect", "HOLD_EFFECT_NONE"):
            item["hold_effect"] = ""
            print(f"  {GREEN}Hold effect cleared.{RST}")
            input(f"  {DIM}Press Enter{RST} > ")
            return True
        return False

    # Filter effects by query
    q = query.lower()
    matches = [e for e in effects if q in e.lower() or q in _hold_label(e).lower()]
    if not matches:
        print(f"  {RED}No matching hold effects.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False
    if len(matches) > 20:
        matches = matches[:20]
        print(f"  {DIM}Showing first 20 matches...{RST}")

    for idx, eff in enumerate(matches, 1):
        print(f"  {_k(str(idx))} {_hold_label(eff)}")
    print()
    try:
        raw = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not raw.isdigit():
        return False
    choice = int(raw)
    if choice < 1 or choice > len(matches):
        return False
    new_effect = matches[choice - 1]
    if _write_field(game_path, item, "hold_effect", new_effect):
        item["hold_effect"] = new_effect
        print(f"  {GREEN}Hold effect updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


def _edit_int_field(game_path, item, field_name, label, min_val, max_val):
    """Edit an integer field with range validation."""
    current = item.get(field_name, 0)
    print(f"  Current {label}: {CYAN}{current}{RST}")
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
    if _write_field(game_path, item, field_name, str(val)):
        item[field_name] = val
        print(f"  {GREEN}{label} updated.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return True
    print(f"  {RED}Write failed.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return False


# ---------------------------------------------------------------------------
# Browser UI
# ---------------------------------------------------------------------------


def _render_browser(filtered, all_items, state, search, pocket_filter,
                    sort_filter, nav, proj_name):
    """Render one frame of the item browser."""
    clear_screen()
    print_logo("Item Editor", proj_name=proj_name)

    parts = [f"{DIM}{len(filtered)}/{len(all_items)} items{RST}"]
    if search:
        parts.append(f"{CYAN}search: {search}{RST}")
    if pocket_filter:
        parts.append(f"{CYAN}{_pocket_label(pocket_filter)}{RST}")
    if sort_filter:
        parts.append(f"{CYAN}{_sort_label(sort_filter)}{RST}")
    print(f"  {' | '.join(parts)}")
    print()

    if not filtered:
        print(f"  {DIM}No matching items.{RST}")
    else:
        oa = overflow_above(state)
        if oa:
            print(oa)
        start, end = visible_range(state)
        for idx in range(start, end):
            print(_render_item_row(filtered[idx], state, idx))
        ob = overflow_below(state)
        if ob:
            print(ob)

    print()
    print(footer_hint(nav_keys=nav,
                       extra=f"  [/]search  [f]ilter  [t]ype  [e]dit"))
    print()


def _open_detail_or_edit(item, game_path, settings, proj_name):
    """Show detail view and optionally enter edit. Returns True if changed."""
    _show_detail(item, settings, proj_name)
    try:
        raw = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if raw == "e":
        return _edit_item(game_path, item, settings, proj_name)
    return False


def _browser(game_path, settings, proj_name):
    """Main item browser with scrolling, search, and filter."""
    nav = _nav_keys(settings)
    page_size = settings.get("map_list_page_size", 20)

    all_items = parse_items(game_path)
    if not all_items:
        print(f"  {RED}No items found in {_items_h_path(game_path)}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    search = ""
    pocket_filter = ""
    sort_filter = ""
    pocket_idx = 0
    changed = False
    state = ListState(len(all_items), page_size=page_size)

    while True:
        filtered = _apply_filters(all_items, search, pocket_filter, sort_filter)
        state.total = len(filtered)
        guard_bounds(state)
        _render_browser(filtered, all_items, state, search, pocket_filter,
                        sort_filter, nav, proj_name)

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
        elif key == "f":
            pocket_idx = (pocket_idx + 1) % (len(_POCKETS) + 1)
            pocket_filter = _POCKETS[pocket_idx - 1] if pocket_idx > 0 else ""
            state.selected = 0
            state.scroll_top = 0
        elif key == "t":
            sort_filter = _pick_sort_filter(sort_filter)
            state.selected = 0
            state.scroll_top = 0
        elif key == "e" and filtered:
            if _edit_item(game_path, filtered[state.selected], settings, proj_name):
                changed = True
                all_items = parse_items(game_path)
        else:
            action = handle_input(state, raw, nav_keys=nav)
            if action == "quit":
                break
            if action in ("open", "jump_act") and filtered:
                if _open_detail_or_edit(filtered[state.selected], game_path,
                                        settings, proj_name):
                    changed = True
                    all_items = parse_items(game_path)

    if changed:
        _offer_build(game_path=game_path, trigger="item_edit")


def _pick_sort_filter(current):
    """Quick sort type picker. Returns new filter or empty string."""
    print()
    print(f"  {DIM}Sort type filter (current: {_sort_label(current) if current else 'All'}):{RST}")
    print(f"  {_k('0')} All")
    for idx, st in enumerate(_SORT_TYPES, 1):
        mk = "*" if st == current else " "
        print(f"  {_k(str(idx))} {mk} {_sort_label(st)}")
    print()
    try:
        raw = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return current
    if raw == "0":
        return ""
    if raw.isdigit():
        choice = int(raw)
        if 1 <= choice <= len(_SORT_TYPES):
            return _SORT_TYPES[choice - 1]
    return current


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def item_editor_menu(game_path, settings=None, proj_name=None):
    """Main entry point for the Item Editor.

    Called from __main__.py via 'torch items' or main menu.
    """
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if proj_name is None:
        proj_name = ""

    # Validate game path
    if not game_path or not os.path.isdir(game_path):
        print(f"  {RED}Game path not found: {game_path}{RST}")
        return

    # Check expansion (items editor needs expansion, not vanilla)
    try:
        from torch.expansion_compat import detect_expansion_version
        version = detect_expansion_version(game_path)
        if version is None:
            print(f"  {RED}Item Editor requires pokeemerald-expansion.{RST}")
            print(f"  {DIM}Vanilla pokeemerald uses a different item struct format.{RST}")
            input(f"  {DIM}Press Enter{RST} > ")
            return
    except ImportError:
        pass

    items_path = _items_h_path(game_path)
    if not os.path.isfile(items_path):
        print(f"  {RED}items.h not found at {items_path}{RST}")
        return

    _browser(game_path, settings, proj_name)
