"""Shop Editor — detect, view, and edit Pokemart item lists."""
# TORCH_MODULE: Shop Editor
# TORCH_GROUP: Map Studio
import json
import os
import re

from torch.colours import GOLD, WHITE, CYAN, DIM, RST, GREEN, RED, BAR
from torch.ui import print_logo, _set_terminal_title, _k, clear_screen
from torch.names import _const_to_item_name

SHOP_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Detection — NPC-based
# ---------------------------------------------------------------------------

def detect_shop_npcs(game_path, map_name):
    """Scan map.json for MART_EMPLOYEE NPCs.

    Returns list of dicts: {object_id, x, y, script_label, local_id}
    """
    map_json_path = os.path.join(
        game_path, "data", "maps", map_name, "map.json"
    )
    if not os.path.isfile(map_json_path):
        return []

    try:
        with open(map_json_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    results = []
    for i, obj in enumerate(data.get("object_events", [])):
        gfx = obj.get("graphics_id", "")
        if "MART_EMPLOYEE" in str(gfx):
            results.append({
                "object_id": i + 1,
                "x": obj.get("x", 0),
                "y": obj.get("y", 0),
                "script_label": obj.get("script", ""),
                "local_id": obj.get("local_id", ""),
            })
    return results


# ---------------------------------------------------------------------------
# Detection — script-based
# ---------------------------------------------------------------------------

def find_shop_scripts(game_path, map_name):
    """Scan scripts.inc and .pory files for shop item lists.

    Returns list of dicts:
        {label, items: [str], file_path, line_start, line_end, format: "inc"|"pory"}
    """
    map_dir = os.path.join(game_path, "data", "maps", map_name)
    results = []

    # Scan .inc files
    inc_path = os.path.join(map_dir, "scripts.inc")
    if os.path.isfile(inc_path):
        results.extend(_scan_inc_shops(inc_path))

    # Scan .pory files
    for fname in sorted(os.listdir(map_dir)) if os.path.isdir(map_dir) else []:
        if fname.endswith(".pory"):
            pory_path = os.path.join(map_dir, fname)
            results.extend(_scan_pory_shops(pory_path))

    return results


def _scan_inc_shops(file_path):
    """Find all pokemart item lists in an .inc file."""
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
    except OSError:
        return []

    results = []
    # Find pokemart data labels by looking for .2byte ITEM_ blocks
    # ending with pokemartlistend
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        # Look for a label line (ends with :, not ::)
        label_match = re.match(r'^(\w+):$', stripped)
        if label_match:
            label = label_match.group(1)
            # Check if next non-blank, non-.align lines are .2byte ITEM_
            items, end_line = _parse_inc_shop(lines, i + 1)
            if items is not None:
                results.append({
                    "label": label,
                    "items": items,
                    "file_path": file_path,
                    "line_start": i + 1,  # first .2byte line (0-indexed)
                    "line_end": end_line,  # pokemartlistend line (0-indexed)
                    "format": "inc",
                })
        i += 1

    return results


def _parse_inc_shop(lines, start_idx):
    """Parse a .2byte ITEM_* block starting at given line.

    Skips .align directives and blank lines before the item block.
    Returns (items_list, end_line_idx) or (None, None) if not a shop block.
    """
    idx = start_idx
    total = len(lines)

    # Skip .align and blank lines
    while idx < total:
        s = lines[idx].strip()
        if not s or s.startswith(".align"):
            idx += 1
            continue
        break

    if idx >= total:
        return None, None

    # Now we expect .2byte ITEM_ lines
    items = []
    item_start = idx
    while idx < total:
        s = lines[idx].strip()
        # Strip inline comments
        s_no_comment = s.split("@")[0].strip() if "@" in s else s

        if re.match(r'^\.2byte\s+ITEM_\w+', s_no_comment):
            item_match = re.match(r'^\.2byte\s+(ITEM_\w+)', s_no_comment)
            if item_match:
                items.append(item_match.group(1))
            idx += 1
        elif s_no_comment == "pokemartlistend" or s_no_comment.startswith("pokemartlistend"):
            if items:
                return items, idx
            return None, None
        else:
            # Not a shop block
            break

    return None, None


def _scan_pory_shops(file_path):
    """Find all mart() blocks in a .pory file."""
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
    except OSError:
        return []

    results = []
    i = 0
    while i < len(lines):
        # Match: mart("LabelName") { or mart(LabelName) {
        m = re.match(r'^\s*mart\s*\(\s*"?(\w+)"?\s*\)\s*\{', lines[i])
        if m:
            label = m.group(1)
            items, end_line = _parse_pory_shop(lines, i + 1)
            if items is not None:
                results.append({
                    "label": label,
                    "items": items,
                    "file_path": file_path,
                    "line_start": i,    # mart( line (0-indexed)
                    "line_end": end_line,  # closing } line (0-indexed)
                    "format": "pory",
                })
        i += 1

    return results


def _parse_pory_shop(lines, start_idx):
    """Parse a mart { ITEM_X, ITEM_Y, ... } block.

    Returns (items_list, end_line_idx) or (None, None) if parse fails.
    """
    items = []
    idx = start_idx
    total = len(lines)

    while idx < total:
        s = lines[idx].strip()
        if s == "}":
            return items, idx
        # Match ITEM_ constants (possibly with trailing comma)
        item_match = re.match(r'^(ITEM_\w+)\s*,?\s*$', s)
        if item_match:
            items.append(item_match.group(1))
        elif s and not s.startswith("//"):
            # Non-empty, non-comment, non-item line inside mart block — bail
            return None, None
        idx += 1

    return None, None


# ---------------------------------------------------------------------------
# Linking — connect NPCs to their shop scripts
# ---------------------------------------------------------------------------

def _link_shops(npcs, scripts, game_path, map_name):
    """Match shopkeeper NPCs to their item lists.

    Traces the NPC's script label through scripts.inc to find which
    pokemart data label it references, then matches that to a parsed shop.

    Returns list of dicts:
        {npc, shop, linked: bool}
    """
    # Build lookup: pokemart data label -> shop dict
    shop_by_label = {s["label"]: s for s in scripts}

    # Read scripts.inc to trace pokemart references
    inc_path = os.path.join(game_path, "data", "maps", map_name, "scripts.inc")
    pokemart_refs = _trace_pokemart_refs(inc_path)

    results = []
    for npc in npcs:
        script = npc.get("script_label", "")
        # Check if this NPC's script references a pokemart
        linked_labels = pokemart_refs.get(script, [])
        for label in linked_labels:
            if label in shop_by_label:
                results.append({
                    "npc": npc,
                    "shop": shop_by_label[label],
                    "linked": True,
                })
        if not linked_labels:
            results.append({
                "npc": npc,
                "shop": None,
                "linked": False,
            })

    # Also add any unlinked shops (shops without a detected NPC)
    linked_shop_labels = {r["shop"]["label"] for r in results if r["shop"]}
    for s in scripts:
        if s["label"] not in linked_shop_labels:
            results.append({
                "npc": None,
                "shop": s,
                "linked": False,
            })

    return results


def _trace_pokemart_refs(inc_path):
    """Trace which script labels call `pokemart <data_label>`.

    Returns dict: {script_label: [data_label, ...]}
    Also follows goto/call chains within the same file.
    """
    if not inc_path or not os.path.isfile(inc_path):
        return {}

    try:
        with open(inc_path, "r") as f:
            lines = f.readlines()
    except OSError:
        return {}

    # Pass 1: collect direct pokemart references per script label
    current_label = None
    label_refs = {}       # label -> [pokemart data labels]
    label_jumps = {}      # label -> [labels jumped to via goto/call]

    for line in lines:
        s = line.strip()
        label_m = re.match(r'^(\w+)::?\s*$', s)
        if label_m:
            current_label = label_m.group(1)
            continue

        if current_label is None:
            continue

        pm = re.match(r'^\s*pokemart\s+(\w+)', s)
        if pm:
            label_refs.setdefault(current_label, []).append(pm.group(1))

        jmp = re.match(r'^\s*(?:goto|call|goto_if_set\s+\w+,)\s+(\w+)', s)
        if jmp:
            label_jumps.setdefault(current_label, []).append(jmp.group(1))

    # Pass 2: resolve one level of jumps
    result = {}
    for label, refs in label_refs.items():
        result[label] = refs

    for label, jumps in label_jumps.items():
        for target in jumps:
            if target in label_refs:
                result.setdefault(label, []).extend(label_refs[target])

    return result


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _format_item_name(const):
    """ITEM_POKE_BALL -> 'Poke Ball'. Delegates to names module."""
    return _const_to_item_name(const)


def _view_shop(shop_data):
    """Display a shop's items with formatted names."""
    items = shop_data.get("items", [])
    label = shop_data.get("label", "Unknown")

    print()
    print(f"  {WHITE}{label}{RST}  {DIM}({len(items)} items, {shop_data.get('format', '?')} format){RST}")
    print(BAR)

    if not items:
        print(f"  {DIM}(empty shop){RST}")
    else:
        for i, item in enumerate(items, 1):
            name = _format_item_name(item)
            print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{name}{RST}  {DIM}{item}{RST}")

    print()


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------

def _edit_shop(game_path, shop_data, settings):
    """Interactive shop editor.

    Returns new items list if changes were saved, or None if cancelled.
    """
    items = list(shop_data.get("items", []))
    label = shop_data.get("label", "Unknown")

    while True:
        clear_screen()
        print()
        print(f"  {WHITE}Editing: {label}{RST}")
        print(BAR)

        if items:
            for i, item in enumerate(items, 1):
                name = _format_item_name(item)
                print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{name}{RST}  {DIM}{item}{RST}")
        else:
            print(f"  {DIM}(empty — add items with [a]){RST}")
        print()

        parts = [
            f"{_k('a')}{DIM}dd{RST}",
        ]
        if items:
            parts.append(f"{_k('d')}{DIM}elete{RST}")
            parts.append(f"{_k('m')}{DIM}ove{RST}")
        parts.append(f"{_k('c')}{DIM}onfirm{RST}")
        parts.append(f"{_k('q')}{DIM}uit{RST}")
        print("  " + "  ".join(parts))
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw == "q":
            return None
        elif raw == "c":
            return items
        elif raw == "a":
            items = _editor_add_item(game_path, items)
        elif raw == "d" and items:
            items = _editor_delete_item(items)
        elif raw == "m" and items:
            items = _editor_move_item(items)


def _editor_add_item(game_path, items):
    """Add an item via the picker. Returns updated list."""
    try:
        from torch.pickers import pick_item
        item = pick_item(game_path)
        if item:
            items.append(item)
            print(f"  {GREEN}Added {_format_item_name(item)}{RST}")
    except ImportError:
        print(f"  {DIM}Item picker not available. Enter constant manually:{RST}")
        manual = input("  ITEM_ > ").strip()
        if manual:
            if not manual.startswith("ITEM_"):
                manual = "ITEM_" + manual.upper().replace(" ", "_")
            items.append(manual)
    return items


def _editor_delete_item(items):
    """Delete an item by number. Returns updated list."""
    try:
        raw = input(f"  Delete # > ").strip()
        idx = int(raw) - 1
        if 0 <= idx < len(items):
            removed = items.pop(idx)
            print(f"  {RED}Removed {_format_item_name(removed)}{RST}")
        else:
            print(f"  {DIM}Invalid number{RST}")
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    return items


def _editor_move_item(items):
    """Move an item to a new position. Returns updated list."""
    try:
        raw = input(f"  Move # > ").strip()
        src = int(raw) - 1
        if not (0 <= src < len(items)):
            print(f"  {DIM}Invalid number{RST}")
            return items
        raw2 = input(f"  To position # > ").strip()
        dst = int(raw2) - 1
        if not (0 <= dst < len(items)):
            print(f"  {DIM}Invalid position{RST}")
            return items
        item = items.pop(src)
        items.insert(dst, item)
        print(f"  {GREEN}Moved {_format_item_name(item)} to #{dst + 1}{RST}")
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    return items


# ---------------------------------------------------------------------------
# Write-back
# ---------------------------------------------------------------------------

def _write_shop_changes(game_path, shop_data, new_items):
    """Write modified item list back to the script file.

    Uses surgical line-based replacement — only changes the item lines.
    Returns True on success, False on error.
    """
    file_path = shop_data.get("file_path")
    fmt = shop_data.get("format")

    if not file_path or not os.path.isfile(file_path):
        return False

    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
    except OSError:
        return False

    if fmt == "inc":
        return _write_inc_shop(lines, file_path, shop_data, new_items)
    elif fmt == "pory":
        return _write_pory_shop(lines, file_path, shop_data, new_items)

    return False


def _write_inc_shop(lines, file_path, shop_data, new_items):
    """Replace .2byte ITEM_* lines in an .inc file."""
    label = shop_data["label"]

    # Find the label line
    label_idx = None
    for i, line in enumerate(lines):
        if re.match(rf'^{re.escape(label)}:\s*$', line.strip()):
            label_idx = i
            break

    if label_idx is None:
        return False

    # Find the .2byte block: skip .align and blanks after label
    start = label_idx + 1
    total = len(lines)
    while start < total:
        s = lines[start].strip()
        if not s or s.startswith(".align"):
            start += 1
            continue
        break

    # Find end: walk .2byte lines until pokemartlistend
    end = start
    while end < total:
        s = lines[end].strip()
        s_no_comment = s.split("@")[0].strip() if "@" in s else s
        if s_no_comment.startswith("pokemartlistend"):
            break
        end += 1
    else:
        return False

    # Detect indentation from original lines (or default to tab)
    indent = "\t"
    if start < total and lines[start].startswith(("\t", " ")):
        ws_match = re.match(r'^(\s+)', lines[start])
        if ws_match:
            indent = ws_match.group(1)

    # Build replacement lines
    new_lines = [f"{indent}.2byte {item}\n" for item in new_items]

    lines[start:end] = new_lines

    return _atomic_write(file_path, lines)


def _write_pory_shop(lines, file_path, shop_data, new_items):
    """Replace items inside a mart { } block in a .pory file."""
    line_start = shop_data["line_start"]
    line_end = shop_data["line_end"]

    if line_start >= len(lines) or line_end >= len(lines):
        return False

    # Detect indentation from original content lines
    indent = "    "
    for i in range(line_start + 1, min(line_end, len(lines))):
        ws_match = re.match(r'^(\s+)', lines[i])
        if ws_match:
            indent = ws_match.group(1)
            break

    # Build replacement: keep the mart(...) { line and closing }
    new_content = [f"{indent}{item}\n" for item in new_items]
    lines[line_start + 1:line_end] = new_content

    return _atomic_write(file_path, lines)


def _atomic_write(file_path, lines):
    """Write lines to file atomically (write to tmp, then rename)."""
    tmp_path = file_path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.writelines(lines)
        os.replace(tmp_path, file_path)
        return True
    except OSError:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False


# ---------------------------------------------------------------------------
# Main TUI
# ---------------------------------------------------------------------------

def _render_shop_list(shops, linked, map_name):
    """Render the shop listing screen. Returns the shops list for selection."""
    clear_screen()
    print()
    print(f"  {WHITE}Shops: {map_name}{RST}")
    print(BAR)

    if not shops:
        print(f"  {DIM}No shops found in this map.{RST}")
        print()
        return

    for i, shop in enumerate(shops, 1):
        npc_info = ""
        for entry in linked:
            if entry["shop"] is shop and entry["npc"]:
                npc = entry["npc"]
                npc_info = f"  {DIM}NPC at ({npc['x']}, {npc['y']}){RST}"
                break
        count = len(shop["items"])
        print(f"    {GOLD}[{i}]{RST} {WHITE}{shop['label']}{RST}  "
              f"{DIM}({count} item{'s' if count != 1 else ''}, "
              f"{shop['format']}){RST}{npc_info}")

    print()
    print(f"  {DIM}Enter number to view/edit, {_k('q')} back{RST}")
    print()


def shop_editor_menu(game_path, map_name, settings=None, proj_name=None,
                     project_dir=None):
    """Shop editor TUI — detect shops, view/edit item lists."""
    if settings is None:
        settings = {}

    _set_terminal_title(f"TORCH -- Shops: {map_name}")

    while True:
        npcs = detect_shop_npcs(game_path, map_name)
        scripts = find_shop_scripts(game_path, map_name)
        linked = _link_shops(npcs, scripts, game_path, map_name)

        # Collect unique shops
        shops = []
        for entry in linked:
            if entry["shop"] and entry["shop"] not in shops:
                shops.append(entry["shop"])

        _render_shop_list(shops, linked, map_name)

        if not shops:
            input(f"  {DIM}Press Enter to return{RST} > ")
            return

        try:
            raw = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if raw == "q":
            return

        try:
            idx = int(raw) - 1
            if 0 <= idx < len(shops):
                _shop_detail(game_path, shops[idx], settings, map_name)
        except ValueError:
            pass


def _shop_detail(game_path, shop, settings, map_name):
    """View a single shop and offer editing."""
    while True:
        clear_screen()
        _view_shop(shop)

        print(f"  {_k('e')}{DIM}dit{RST}    {_k('q')}{DIM} back{RST}")
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if raw == "q":
            return
        elif raw == "e":
            new_items = _edit_shop(game_path, shop, settings)
            if new_items is not None:
                ok = _write_shop_changes(game_path, shop, new_items)
                if ok:
                    print(f"\n  {GREEN}Shop saved successfully.{RST}")
                    # Refresh shop data
                    shop["items"] = new_items
                else:
                    print(f"\n  {RED}Failed to save changes.{RST}")
                input(f"  {DIM}Press Enter{RST} > ")
