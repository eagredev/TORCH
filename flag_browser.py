"""Flag browser — browse, search, create, and manage game flags."""
# TORCH_MODULE: Flag Browser
# TORCH_GROUP: Shared Infrastructure
import os

from torch.config import SETTINGS_DEFAULTS, _nav_keys
from torch.colours import GOLD, WHITE, CYAN, GREEN, RED, DIM, RST, DGOLD, BAR
from torch.ui import print_logo, _set_terminal_title, _k, clear_screen
from torch.flag_scanner import parse_flags_h, count_free_slots, scan_flag_references, delete_flag_from_header
from torch.pickers import define_new_flag


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

def _build_flag_rows(parsed):
    """Build a flat list of flag rows from parsed flags.h data.

    Each row is a dict with keys: name, value, comment, row_type.
    row_type is one of: "custom", "free", "event".

    Custom aliases (FLAG_MY_THING -> FLAG_UNUSED_0xXXX) appear as "custom".
    FLAG_UNUSED_0xXXX entries that are aliased are skipped (the alias is shown
    instead).  Remaining FLAG_UNUSED_0xXXX entries are "free".  Everything
    else is "event" (named vanilla flags).
    """
    alias_names = {alias for alias, _ in parsed["custom_aliases"]}
    aliased_targets = {target for _, target in parsed["custom_aliases"]}

    rows = []
    for name, val, comment, is_unused in parsed["event"]:
        if name in alias_names:
            row_type = "custom"
        elif is_unused and name not in aliased_targets:
            row_type = "free"
        elif is_unused and name in aliased_targets:
            # This FLAG_UNUSED slot has been claimed by a custom alias -- skip
            continue
        else:
            row_type = "event"
        rows.append({
            "name": name,
            "value": val,
            "comment": comment,
            "row_type": row_type,
        })
    return rows


# ---------------------------------------------------------------------------
# Filter / search helpers
# ---------------------------------------------------------------------------

_FILTER_MODES = ["all", "custom", "event", "free"]


def _apply_filters(rows, filter_mode, search_query):
    """Return a filtered copy of the row list."""
    result = rows
    if filter_mode != "all":
        result = [r for r in result if r["row_type"] == filter_mode]
    if search_query:
        q = search_query.upper()
        result = [r for r in result if q in r["name"].upper() or q in r["comment"].upper()]
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _type_colour(row_type):
    """Return ANSI colour for a flag row type."""
    if row_type == "custom":
        return GREEN
    elif row_type == "event":
        return WHITE
    else:
        return DIM


def _type_label(row_type):
    """Short label for display in the list."""
    if row_type == "custom":
        return "custom"
    elif row_type == "event":
        return "event"
    else:
        return "free"


def _render_list(visible, total, selected_idx, scroll_top, page_size,
                 filter_mode, search_query, free_count, total_event,
                 NK_UP, NK_DOWN, proj_name):
    """Render the flag browser screen."""
    clear_screen()
    print_logo("Flag Browser", proj_name)
    print(BAR)

    # Status bar: filter + slot counts
    mode_label = filter_mode.upper()
    print(f"   {DIM}Filter:{RST} {CYAN}{mode_label}{RST}"
          f"          {DIM}[{free_count} free / {total_event} event slots]{RST}")
    if search_query:
        print(f"   {DIM}Search:{RST} {CYAN}\"{search_query}\"{RST}")
    print(BAR)
    print()

    if total == 0:
        if search_query:
            print(f"  {DIM}No flags match the search.{RST}")
        elif filter_mode != "all":
            print(f"  {DIM}No {filter_mode} flags found.{RST}")
        else:
            print(f"  {DIM}No flags found. Is flags.h present?{RST}")
        print()
    else:
        num_w = len(str(total))
        # Column header
        print(f"  {DIM}     {'#':<{num_w + 1}} {'Flag Name':<34} {'Slot':<9} Type{RST}")

        # Overflow above
        if scroll_top > 0:
            print(f"  {DIM}  \u2191 {scroll_top} more above{RST}")

        end = min(scroll_top + page_size, total)
        for idx in range(scroll_top, end):
            row = visible[idx]
            marker = f"{GOLD}>>{RST}" if idx == selected_idx else "  "
            row_num = f"{idx + 1}."
            col = _type_colour(row["row_type"])
            label = _type_label(row["row_type"])

            # Truncate long flag names
            fname = row["name"]
            if len(fname) > 32:
                fname = fname[:29] + "..."

            print(f"  {marker} {row_num:<{num_w + 1}} {col}{fname:<34}{RST} {DIM}{row['value']:<9}{RST} {col}{label}{RST}")

        # Overflow below
        if end < total:
            print(f"  {DIM}  \u2193 {total - end} more below{RST}")
        print()

    # Footer command bar
    nav_parts = [
        f"{_k(NK_UP)} {DIM}up{RST}",
        f"{_k(NK_DOWN)} {DIM}down{RST}",
        f"{_k('Enter')} {DIM}scroll{RST}",
    ]
    if search_query:
        nav_parts.append(f"{_k('c')} {DIM}clear search{RST}")
    else:
        nav_parts.append(f"{_k('/')} {DIM}search{RST}")
    nav_parts.append(f"{_k('f')} {DIM}detail{RST}")
    nav_parts.append(f"{_k('+')} {DIM}create{RST}")
    nav_parts.append(f"{_k('d')} {DIM}delete{RST}")
    nav_parts.append(f"{_k('x')} {DIM}filter{RST}")
    nav_parts.append(f"{_k('q')} {DIM}back{RST}")
    print("  " + "  ".join(nav_parts))
    print()


# ---------------------------------------------------------------------------
# Detail view
# ---------------------------------------------------------------------------

def _show_detail(row, game_path):
    """Show cross-references for a flag."""
    clear_screen()
    name = row["name"]
    col = _type_colour(row["row_type"])

    print()
    print(BAR)
    print(f"   {WHITE}Flag Detail{RST}")
    print(BAR)
    print()
    print(f"  {DIM}Name:{RST}    {col}{name}{RST}")
    print(f"  {DIM}Value:{RST}   {row['value']}")
    print(f"  {DIM}Type:{RST}    {col}{_type_label(row['row_type'])}{RST}")
    if row["comment"]:
        print(f"  {DIM}Comment:{RST} {row['comment']}")
    print()

    print(f"  {DIM}Scanning cross-references...{RST}")
    refs = scan_flag_references(name, game_path)

    if not refs:
        print(f"  {DIM}No references found outside flags.h.{RST}")
    else:
        # Group by category
        by_cat = {}
        for ref in refs:
            cat = ref["category"]
            by_cat.setdefault(cat, []).append(ref)

        cat_labels = {
            "header_define": "Header (define)",
            "header_alias": "Header (alias)",
            "script_pory": "Poryscript",
            "script_inc": "Assembly script",
            "map_json": "Map JSON",
            "c_source": "C source",
            "other": "Other",
        }

        print(f"  {WHITE}{len(refs)} reference(s) found:{RST}")
        print()
        for cat, cat_refs in sorted(by_cat.items()):
            label = cat_labels.get(cat, cat)
            print(f"  {DGOLD}{label}{RST}  ({len(cat_refs)})")
            for ref in cat_refs[:20]:  # cap per category to avoid flooding
                print(f"    {DIM}{ref['file']}:{ref['line_num']}{RST}")
                print(f"      {ref['line_text'][:80]}")
            if len(cat_refs) > 20:
                print(f"    {DIM}... and {len(cat_refs) - 20} more{RST}")
            print()

    print()
    input(f"  {DIM}[Enter] back{RST} ")


# ---------------------------------------------------------------------------
# Delete flow
# ---------------------------------------------------------------------------

def _handle_delete(row, game_path):
    """Delete a custom flag after confirmation. Returns True if deleted."""
    name = row["name"]

    if row["row_type"] != "custom":
        print()
        print(f"  {DIM}Only custom flags can be deleted.{RST}")
        input(f"  {DIM}[Enter] back{RST} ")
        return False

    # Scan references first
    print()
    print(f"  {DIM}Scanning references for {name}...{RST}")
    refs = scan_flag_references(name, game_path)

    # Filter out the header define itself
    non_header = [r for r in refs if r["category"] not in ("header_define", "header_alias")]

    if non_header:
        print()
        print(f"  {RED}Warning:{RST} {WHITE}{name}{RST} has {len(non_header)} reference(s) in game files:")
        print()
        for ref in non_header[:10]:
            print(f"    {DIM}{ref['file']}:{ref['line_num']}{RST}")
            print(f"      {ref['line_text'][:80]}")
        if len(non_header) > 10:
            print(f"    {DIM}... and {len(non_header) - 10} more{RST}")
        print()
        print(f"  {RED}Deleting this flag will NOT remove these references.{RST}")
        print(f"  {DIM}You will need to update scripts/code manually.{RST}")
        print()

    confirm = input(f"  Delete {WHITE}{name}{RST}? [y/N] > ").strip().lower()
    if confirm not in ("y", "yes"):
        print(f"  {DIM}Cancelled.{RST}")
        input(f"  {DIM}[Enter] back{RST} ")
        return False

    ok = delete_flag_from_header(game_path, name)
    if ok:
        print(f"  {GREEN}Deleted:{RST} {name}")
    else:
        print(f"  {RED}Failed to delete {name}.{RST}")
    input(f"  {DIM}[Enter] back{RST} ")
    return ok


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _reload_flag_data(game_path):
    """Reload flags.h data and rebuild rows + counts."""
    parsed = parse_flags_h(game_path)
    rows = _build_flag_rows(parsed)
    free_count, total_event = count_free_slots(game_path)
    return rows, free_count, total_event


def _handle_create(game_path, st):
    """Handle [+] create command. Returns updated (all_rows, free_count, total_event) or None."""
    result = define_new_flag(game_path)
    if result:
        all_rows, free_count, total_event = _reload_flag_data(game_path)
        # Try to select the newly created flag
        for i, r in enumerate(_apply_filters(all_rows, st["filter_mode"], st["search_query"])):
            if r["name"] == result:
                st["selected_idx"] = i
                break
        input(f"  {DIM}[Enter] back{RST} ")
        return all_rows, free_count, total_event
    input(f"  {DIM}[Enter] back{RST} ")
    return None


def _handle_numeric_jump(choice, visible, total, selected_idx, game_path):
    """Handle numeric row jump. Returns new selected_idx."""
    if choice.isdigit():
        num = int(choice)
        if 1 <= num <= total:
            if selected_idx == num - 1:
                _show_detail(visible[selected_idx], game_path)
            else:
                return num - 1
    return selected_idx


def _dispatch_command(cmd, choice, st, visible, total, game_path, nav_keys):
    """Process a single command. Returns 'quit' to exit, 'reload' after data changes, or None."""
    NK_UP, NK_DOWN, NK_OPEN = nav_keys

    if cmd == "q":
        return "quit"

    if cmd in (NK_UP, "k"):
        if total > 0:
            st["selected_idx"] = max(0, st["selected_idx"] - 1)

    elif cmd == NK_DOWN:
        if total > 0:
            st["selected_idx"] = min(total - 1, st["selected_idx"] + 1)

    elif cmd in ("f", NK_OPEN):
        if total > 0:
            _show_detail(visible[st["selected_idx"]], game_path)

    elif cmd == "+":
        result = _handle_create(game_path, st)
        if result:
            return "reload", result

    elif cmd == "d":
        if total > 0:
            deleted = _handle_delete(visible[st["selected_idx"]], game_path)
            if deleted:
                return "reload", _reload_flag_data(game_path)

    elif cmd == "/" and not st["search_query"]:
        q = input(f"  {GOLD}Search:{RST} ").strip()
        if q:
            st["search_query"] = q
            st["selected_idx"] = 0
            st["scroll_top"] = 0

    elif cmd == "c" and st["search_query"]:
        st["search_query"] = ""
        st["selected_idx"] = 0
        st["scroll_top"] = 0

    elif cmd == "x":
        idx = _FILTER_MODES.index(st["filter_mode"])
        st["filter_mode"] = _FILTER_MODES[(idx + 1) % len(_FILTER_MODES)]
        st["selected_idx"] = 0
        st["scroll_top"] = 0

    else:
        st["selected_idx"] = _handle_numeric_jump(
            choice, visible, total, st["selected_idx"], game_path)

    return None


def flag_browser(game_path, settings=None, proj_name=None):
    """Flag Browser -- browse, search, create, and manage game flags."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)

    _set_terminal_title("TORCH -- Flag Browser")
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)
    page_size = settings.get("trainer_list_page_size", 20)

    all_rows, free_count, total_event = _reload_flag_data(game_path)

    st = {"selected_idx": 0, "scroll_top": 0,
          "filter_mode": "all", "search_query": ""}

    while True:
        visible = _apply_filters(all_rows, st["filter_mode"], st["search_query"])
        total = len(visible)

        # Clamp selection
        if total == 0:
            st["selected_idx"] = 0
        else:
            st["selected_idx"] = max(0, min(st["selected_idx"], total - 1))

        # Adjust scroll to keep selected in view
        if total > 0:
            if st["selected_idx"] < st["scroll_top"]:
                st["scroll_top"] = st["selected_idx"]
            if st["selected_idx"] >= st["scroll_top"] + page_size:
                st["scroll_top"] = st["selected_idx"] - page_size + 1

        _render_list(visible, total, st["selected_idx"], st["scroll_top"],
                     page_size, st["filter_mode"], st["search_query"],
                     free_count, total_event, NK_UP, NK_DOWN, proj_name)

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return

        raw = raw.rstrip("\n")

        # Enter: scroll down, wrap
        if raw == "" or raw == " " or raw.lower() == NK_SCROLL:
            if total > 0:
                st["selected_idx"] = (st["selected_idx"] + 1) % total
            continue

        choice = raw.strip()
        cmd = choice.lower()

        result = _dispatch_command(
            cmd, choice, st, visible, total, game_path,
            (NK_UP, NK_DOWN, NK_OPEN))

        if result == "quit":
            return
        if isinstance(result, tuple) and result[0] == "reload":
            all_rows, free_count, total_event = result[1]
