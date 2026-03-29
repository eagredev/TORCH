"""SCORCH — Selective Content Obliteration and Refactoring for Clean Hacks.

Scan, report, and remove vanilla content from any pokeemerald-expansion
project.  Provides a full-scan wizard, per-category scrolling lists,
report-only mode, and snapshot restore.
"""
# TORCH_MODULE: SCORCH
# TORCH_GROUP: Tools
import os
import sys
from datetime import datetime

from torch import VERSION
from torch.config import SETTINGS_DEFAULTS, _nav_keys
from torch.ui import print_logo, _set_terminal_title, _offer_build, _k, clear_screen
from torch.cleanup_scanner import (
    CATEGORIES, CATEGORY_IDS, full_scan, scan_category, has_sentinel,
    RemovalPlan, SAFE, BLOCKED, CAUTION, _category_by_id, _load_map_groups,
)
from torch.cleanup_writer import (
    _create_cleanup_snapshot, _restore_cleanup_snapshot,
    _list_cleanup_snapshots, execute_removal,
)
from torch.cleanup_packages import (
    discover_packages, build_indexes, compute_cross_package_deps,
)
from torch.colours import GOLD, DGOLD, WHITE, CYAN, GREEN, RED, DIM, RST, BAR

# Categories with working removers (graphics/music are scan-only for now)
_IMPLEMENTED_REMOVERS = {"maps", "trainers", "encounters", "frontier", "scripts", "tilesets"}




def _badge(status):
    if status == SAFE:
        return f"{GREEN}[  SAFE  ]{RST}"
    elif status == BLOCKED:
        return f"{RED}[BLOCKED ]{RST}"
    elif status == CAUTION:
        return f"{DGOLD}[CAUTION ]{RST}"
    return f"{DIM}[  ???   ]{RST}"



# ============================================================
# MAIN ENTRY POINT
# ============================================================

def cleanup_command(game_path, settings, args=None, proj_name=None):
    """Main entry point for SCORCH (torch scorch / torch clean).

    args is the remaining argument list after the command word.
    """
    if args is None:
        args = []

    _set_terminal_title("TORCH \u2014 SCORCH")

    # Route to sub-mode
    if not args:
        _scorch_hub(game_path, settings, proj_name=proj_name)
        return

    sub = args[0].lower()

    if sub == "report":
        _report_mode(game_path, settings, proj_name=proj_name)
    elif sub == "restore":
        _restore_menu(game_path, settings, proj_name=proj_name)
    elif sub in CATEGORY_IDS:
        _category_menu(game_path, settings, sub, proj_name=proj_name)
    else:
        print(f"  Unknown SCORCH subcommand: {sub}")
        print()
        print("  Usage:")
        print("    torch scorch                 Full-scan wizard")
        print("    torch scorch <category>      Category mode")
        print("    torch scorch report          Scan-only report")
        print("    torch scorch restore         Restore from snapshot")
        print("    torch scorch phoenix         Phoenix — remove ALL vanilla content")
        print("    torch scorch phoenix plan    Phoenix dry-run report")
        print("    torch scorch phoenix restore Restore from Phoenix snapshot")
        print()
        print("  Categories: " + ", ".join(CATEGORY_IDS))


# ============================================================
# SCORCH HUB MENU
# ============================================================

def _scorch_hub(game_path, settings, proj_name=None):
    """Top-level SCORCH hub menu. Dispatches to scan, report, or restore."""
    while True:
        clear_screen()
        print_logo("SCORCH", proj_name)
        print(BAR)
        print(f"   {WHITE}SCORCH{RST}  {DIM}Selective Content Obliteration and Refactoring for Clean Hacks{RST}")
        print(BAR)
        print(f"  {DIM}Also available as: torch clean{RST}")
        print()

        print(f"  {_k('1')} {WHITE}Singe{RST}          {DIM}Scan and selectively remove vanilla content{RST}")
        print(f"  {_k('2')} {WHITE}Phoenix{RST}        {DIM}Remove ALL vanilla maps, trainers, and encounters{RST}")
        print(f"  {_k('3')} {WHITE}Report{RST}         {DIM}Scan-only report (saved to file){RST}")
        print(f"  {_k('4')} {WHITE}Restore{RST}        {DIM}Restore from a SCORCH snapshot{RST}")
        print()
        print(f"  {_k('q')} {DIM}Back{RST}")
        print()

        try:
            choice = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if choice == "1":
            _full_scan_wizard(game_path, settings, proj_name=proj_name)
        elif choice == "2":
            try:
                from torch.scorch import scorch_command
                scorch_command(game_path, settings, proj_name=proj_name)
            except ImportError:
                print("  Phoenix is not available in this release.")
                input("  Press Enter > ")
        elif choice == "3":
            _report_mode(game_path, settings, proj_name=proj_name)
        elif choice == "4":
            _restore_menu(game_path, settings, proj_name=proj_name)
        elif choice == "q" or choice == "":
            return


# ============================================================
# PRE-FLIGHT CHECKS
# ============================================================

def _preflight_checks(game_path):
    """Run pre-flight checks. Returns list of warning strings (empty = all good)."""
    warnings = []

    # Check game path exists
    if not os.path.isdir(game_path):
        warnings.append(f"Game path not found: {game_path}")
        return warnings

    # Check map_groups.json exists and has sentinel
    groups_file = os.path.join(game_path, "data", "maps", "map_groups.json")
    if not os.path.isfile(groups_file):
        warnings.append("map_groups.json not found -- cannot detect vanilla maps")
    elif not has_sentinel(game_path):
        warnings.append("Vanilla map sentinel not found in map_groups.json")

    # Check for git and uncommitted changes
    git_dir = os.path.join(game_path, ".git")
    if os.path.isdir(git_dir):
        try:
            import subprocess
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=game_path, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                warnings.append(
                    "Your project has unsaved changes. "
                    "Consider backing up before removing content."
                )
        except Exception:
            pass

    return warnings


# ============================================================
# FULL-SCAN WIZARD
# ============================================================

def _full_scan_wizard(game_path, settings, proj_name=None):
    """Full scan -> report -> approve -> execute wizard."""

    clear_screen()
    print_logo("SCORCH", proj_name)
    print(BAR)
    print(f"   {WHITE}SCORCH{RST}  {DIM}Selective Content Obliteration and Refactoring for Clean Hacks{RST}")
    print(BAR)
    print()

    # Pre-flight
    warnings = _preflight_checks(game_path)
    if warnings:
        for w in warnings:
            blocking = "not found" in w.lower()
            icon = f"{RED}!{RST}" if blocking else f"{DGOLD}!{RST}"
            print(f"  {icon} {w}")
        print()
        if any("not found" in w.lower() for w in warnings):
            print("  Cannot proceed -- fix the above errors first.")
            print()
            input("  Press Enter to go back > ")
            return

    # Scan once — reused across the loop
    print(f"  {GOLD}Scanning all content categories... this may take 30-60 seconds.{RST}")
    print()
    sys.stdout.flush()
    plan = full_scan(game_path)
    print(f"  {DIM}Scan complete.{RST}")
    print()

    # Main results loop — submenus return here instead of exiting
    while True:
        clear_screen()
        print_logo("SCORCH", proj_name)
        print(BAR)
        print(f"   {WHITE}SCORCH \u2014 SCAN RESULTS{RST}")
        print(BAR)
        print()

        if plan.scan_errors:
            for err in plan.scan_errors:
                print(f"  {RED}Scan error: {err}{RST}")
            print()

        # Display report
        _display_scan_report(plan)

        if plan.total_safe() == 0:
            print(f"  {DIM}No safe-to-remove items found.{RST}")
            print()
            snapshots = _list_cleanup_snapshots(game_path)
            if snapshots:
                print(f"  {_k('s')} {DIM}Restore from snapshot{RST}    "
                      f"{_k('q')} {DIM}Back{RST}")
                print()
                try:
                    choice = input(f"  {GOLD}>{RST} ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    return
                if choice == "s":
                    _restore_menu(game_path, settings, proj_name=proj_name)
                    continue  # Return to results after restore menu
                return
            input("  Press Enter to go back > ")
            return

        # Options
        print()
        print(f"  {_k('a')} {DIM}Remove all safe items{RST}    "
              f"{_k('p')} {DIM}Map groups{RST}    "
              f"{_k('c')} {DIM}Review by category{RST}    "
              f"{_k('r')} {DIM}Save report{RST}    "
              f"{_k('s')} {DIM}Restore snapshot{RST}    "
              f"{_k('q')} {DIM}Exit SCORCH{RST}")
        print()

        try:
            choice = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if choice == "a":
            result = _confirm_and_execute(game_path, plan, settings)
            if result == "rescan":
                print(f"  {GOLD}Rescanning... this may take 30-60 seconds.{RST}")
                sys.stdout.flush()
                plan = full_scan(game_path)
                print(f"  {DIM}Scan complete.{RST}")
            elif result == "exit":
                return
            continue
        elif choice == "p":
            _package_browser(game_path, plan, settings, proj_name=proj_name)
            continue
        elif choice == "c":
            _category_picker(game_path, plan, settings, proj_name=proj_name)
            continue
        elif choice == "r":
            _save_report(game_path, plan)
            continue
        elif choice == "s":
            _restore_menu(game_path, settings, proj_name=proj_name)
            continue
        elif choice == "q" or choice == "":
            return
        else:
            print("  Invalid choice.")
            input("  Press Enter > ")


def _category_picker(game_path, plan, settings, proj_name=None):
    """Let user pick a category to review from the scan results."""
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)
    page_size = settings.get("map_list_page_size", SETTINGS_DEFAULTS["map_list_page_size"])

    summary = plan.category_summary()
    if not summary:
        print("  No categories with results.")
        input("  Press Enter > ")
        return

    cursor_idx = 0
    scroll_top = 0

    while True:
        # Guard bounds
        cursor_idx = max(0, min(cursor_idx, len(summary) - 1))
        if cursor_idx < scroll_top:
            scroll_top = cursor_idx
        if cursor_idx >= scroll_top + page_size:
            scroll_top = cursor_idx - page_size + 1

        clear_screen()
        print_logo("SCORCH", proj_name)
        print(BAR)
        print(f"   {WHITE}SCORCH \u2014 REVIEW BY CATEGORY{RST}")
        print(BAR)
        print()

        end = min(scroll_top + page_size, len(summary))

        if scroll_top > 0:
            print(f"  {DIM}  \u2191 {scroll_top} more above{RST}")

        for li in range(scroll_top, end):
            s = summary[li]
            cursor = f"{GOLD}>>{RST}" if li == cursor_idx else "  "
            name_col = WHITE if li == cursor_idx else ""
            name_rst = RST if name_col else ""

            safe_str = f"{GREEN}{s['safe']} safe{RST}" if s["safe"] > 0 else f"{DIM}0 safe{RST}"
            blocked_str = f"{RED}{s['blocked']} blocked{RST}" if s["blocked"] > 0 else f"{DIM}0 blocked{RST}"
            scan_only = s["id"] not in _IMPLEMENTED_REMOVERS
            marker = f"  {DIM}*{RST}" if scan_only else ""

            print(f"  {cursor} {name_col}{s['label']:<20}{name_rst}  "
                  f"{s['total']:>4} total   {safe_str}   {blocked_str}{marker}")

        remaining = len(summary) - end
        if remaining > 0:
            print(f"  {DIM}  \u2193 {remaining} more below{RST}")

        print()

        # Command bar
        cmd_parts = [
            f"{_k('Enter')} {DIM}scroll{RST}",
            f"{_k(NK_UP)}/{_k(NK_DOWN)} {DIM}navigate{RST}",
            f"{_k('f')} {DIM}open{RST}",
            f"{_k('q')} {DIM}back{RST}",
        ]
        print("  " + "  ".join(cmd_parts))
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if raw == "":
            cursor_idx = (cursor_idx + 1) % len(summary)
            continue

        if raw == "q":
            return

        elif raw == NK_UP:
            cursor_idx = max(0, cursor_idx - 1)

        elif raw == NK_DOWN:
            cursor_idx = min(len(summary) - 1, cursor_idx + 1)

        elif raw == "f" or raw == NK_OPEN:
            cat_id = summary[cursor_idx]["id"]
            _category_menu(game_path, settings, cat_id, preloaded_plan=plan, proj_name=proj_name)

        elif raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(summary):
                cursor_idx = idx


# ============================================================
# SCAN REPORT DISPLAY
# ============================================================

def _display_scan_report(plan):
    """Print a formatted summary table of the scan results."""
    summary = plan.category_summary()
    if not summary:
        print(f"  {DIM}No results to display.{RST}")
        return

    # Header
    print(f"  {WHITE}{'Category':<20}  {'Total':>6}  {'Safe':>6}  {'Blocked':>8}{RST}")
    print(f"  {DIM}{'─' * 20}  {'─' * 6}  {'─' * 6}  {'─' * 8}{RST}")

    total_all = 0
    safe_all = 0
    blocked_all = 0
    has_scan_only = False

    for s in summary:
        total_all += s["total"]
        safe_all += s["safe"]
        blocked_all += s["blocked"]

        safe_col = GREEN if s["safe"] > 0 else DIM
        blocked_col = RED if s["blocked"] > 0 else DIM
        scan_only = s["id"] not in _IMPLEMENTED_REMOVERS
        marker = f"  {DIM}*{RST}" if scan_only else ""
        if scan_only:
            has_scan_only = True

        print(f"  {s['label']:<20}  {s['total']:>6}  "
              f"{safe_col}{s['safe']:>6}{RST}  "
              f"{blocked_col}{s['blocked']:>8}{RST}{marker}")

    print(f"  {DIM}{'─' * 20}  {'─' * 6}  {'─' * 6}  {'─' * 8}{RST}")
    print(f"  {WHITE}{'TOTAL':<20}  {total_all:>6}  "
          f"{GREEN}{safe_all:>6}{RST}  "
          f"{RED}{blocked_all:>8}{RST}")
    if has_scan_only:
        print(f"  {DIM}* Scan only — removal not yet implemented{RST}")
    print()


# ============================================================
# CATEGORY SCROLLING LIST
# ============================================================

def _category_render_header(cat, items, selected, search_filter, visible, proj_name):
    """Render the category menu header: logo, stats bar, and search filter."""
    clear_screen()
    print_logo("SCORCH", proj_name)
    print(BAR)
    cat_label = cat["label"]
    n_safe = sum(1 for i in items if i.status == SAFE)
    n_blocked = sum(1 for i in items if i.status == BLOCKED)
    n_selected = len(selected)
    print(f"   {WHITE}{cat_label}{RST}  "
          f"{DIM}{len(items)} total{RST}  "
          f"{GREEN}{n_safe} safe{RST}  "
          f"{RED}{n_blocked} blocked{RST}  "
          f"{CYAN}{n_selected} selected{RST}")
    print(BAR)

    if search_filter:
        print(f"  {DIM}Filter: \"{search_filter}\"  ({len(visible)} matches){RST}")

    print()


def _category_render_items(visible, items, selected, cursor_idx, scroll_top, page_size):
    """Render the scrollable item list with badges, selections, and scroll indicators."""
    if not visible:
        print(f"  {DIM}No matching items.{RST}")
        return

    for li in range(scroll_top, min(scroll_top + page_size, len(visible))):
        item = visible[li]
        orig_idx = items.index(item)
        is_selected = orig_idx in selected

        cursor = f"{GOLD}>>{RST}" if li == cursor_idx else "  "
        badge_str = _badge(item.status)
        sel_mark = f"{CYAN}[x]{RST}" if is_selected else f"{DIM}[ ]{RST}"

        name_col = WHITE if li == cursor_idx else ""
        name_rst = RST if name_col else ""

        print(f"  {cursor} {sel_mark} {badge_str} {name_col}{item.name}{name_rst}")

        if li == cursor_idx and item.detail:
            print(f"  {'':>8}        {DIM}{item.detail}{RST}")

    if scroll_top > 0:
        print(f"  {DIM}  \u2191 {scroll_top} more above{RST}")
    remaining = len(visible) - (scroll_top + page_size)
    if remaining > 0:
        print(f"  {DIM}  \u2193 {remaining} more below{RST}")


def _category_toggle_item(visible, items, selected, cursor_idx):
    """Toggle selection on the current item. Only SAFE items can be selected."""
    if not visible:
        return
    item = visible[cursor_idx]
    orig_idx = items.index(item)
    if item.status == SAFE:
        if orig_idx in selected:
            selected.discard(orig_idx)
        else:
            selected.add(orig_idx)
    else:
        print(f"  {RED}Cannot select BLOCKED items.{RST}")
        input("  Press Enter > ")


def _category_execute(game_path, items, selected, settings, category_id):
    """Execute removal for selected items. Returns True if execution happened."""
    if not selected:
        print(f"  {DIM}Nothing selected.{RST}")
        input("  Press Enter > ")
        return False
    sel_items = [items[i] for i in sorted(selected)]
    exec_plan = RemovalPlan()
    exec_plan.items = sel_items
    _confirm_and_execute(game_path, exec_plan, settings,
                         category_hint=category_id)
    return True


def _category_load_items(game_path, cat, category_id, preloaded_plan, proj_name):
    """Load items for a category from preloaded plan or by scanning. Returns list or None."""
    if preloaded_plan:
        return preloaded_plan.by_category(category_id)
    clear_screen()
    print_logo("SCORCH", proj_name)
    print(f"  {GOLD}Scanning {cat['label']}... this may take a moment.{RST}")
    sys.stdout.flush()
    cat_plan = scan_category(game_path, category_id)
    print(f"  {DIM}Scan complete.{RST}")
    return cat_plan.items


def _category_apply_filter(items, search_filter, cursor_idx, scroll_top, page_size):
    """Apply search filter and guard cursor/scroll bounds. Returns (visible, cursor_idx, scroll_top)."""
    if search_filter:
        visible = [i for i in items if search_filter.lower() in i.name.lower()]
    else:
        visible = items

    if not visible:
        cursor_idx = 0
    else:
        cursor_idx = max(0, min(cursor_idx, len(visible) - 1))
    if cursor_idx < scroll_top:
        scroll_top = cursor_idx
    if cursor_idx >= scroll_top + page_size:
        scroll_top = cursor_idx - page_size + 1

    return visible, cursor_idx, scroll_top


def _category_menu(game_path, settings, category_id, preloaded_plan=None, proj_name=None):
    """Per-category scrolling list with SAFE/BLOCKED badges and selection."""
    cat = _category_by_id(category_id)
    if not cat:
        print(f"  Unknown category: {category_id}")
        return

    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)
    page_size = settings.get("map_list_page_size", SETTINGS_DEFAULTS["map_list_page_size"])

    items = _category_load_items(game_path, cat, category_id, preloaded_plan, proj_name)

    if not items:
        print()
        print(f"  {DIM}No {cat['label'].lower()} found to scan.{RST}")
        print()
        input("  Press Enter to go back > ")
        return

    # Sort: SAFE first, then BLOCKED, alphabetically within each
    items.sort(key=lambda x: (0 if x.status == SAFE else 1, x.name))

    selected = set()  # indices of items toggled for removal
    cursor_idx = 0
    scroll_top = 0
    search_filter = ""

    while True:
        visible, cursor_idx, scroll_top = _category_apply_filter(
            items, search_filter, cursor_idx, scroll_top, page_size)

        _category_render_header(cat, items, selected, search_filter, visible, proj_name)
        _category_render_items(visible, items, selected, cursor_idx, scroll_top, page_size)

        print()

        # Command bar
        cmd_parts = [
            f"{_k('Enter')} {DIM}scroll{RST}",
            f"{_k(NK_UP)}/{_k(NK_DOWN)} {DIM}navigate{RST}",
            f"{_k('v')} {DIM}toggle{RST}",
            f"{_k('a')} {DIM}all safe{RST}",
            f"{_k('n')} {DIM}none{RST}",
            f"{_k('f')} {DIM}details{RST}",
            f"{_k('/')} {DIM}search{RST}",
            f"{_k('c')} {DIM}execute{RST}",
            f"{_k('q')} {DIM}back{RST}",
        ]
        print("  " + "  ".join(cmd_parts))
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").strip()
        except (EOFError, KeyboardInterrupt):
            return

        # Empty = scroll down
        if raw == "":
            if visible:
                cursor_idx = (cursor_idx + 1) % len(visible)
            continue

        cmd = raw.lower()

        if cmd == "q":
            return

        elif cmd == NK_UP:
            cursor_idx = max(0, cursor_idx - 1)

        elif cmd == NK_DOWN:
            if visible:
                cursor_idx = min(len(visible) - 1, cursor_idx + 1)

        elif cmd == "v":
            _category_toggle_item(visible, items, selected, cursor_idx)

        elif cmd == "a":
            selected = {i for i, item in enumerate(items) if item.status == SAFE}

        elif cmd == "n":
            selected.clear()

        elif cmd == "f":
            if visible:
                _show_item_details(visible[cursor_idx])

        elif cmd == "/":
            try:
                new_filter = input(f"  {DIM}Filter (empty to clear): {RST}").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            search_filter = new_filter
            cursor_idx = 0
            scroll_top = 0

        elif cmd == "c":
            if _category_execute(game_path, items, selected, settings, category_id):
                return

        elif cmd.isdigit():
            idx = int(cmd) - 1
            if 0 <= idx < len(visible):
                cursor_idx = idx


# ============================================================
# PACKAGE BROWSER
# ============================================================

def _package_browser(game_path, plan, settings, proj_name=None):
    """Read-only map group explorer showing vanilla map clusters and connections."""
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)
    page_size = settings.get("map_list_page_size",
                             SETTINGS_DEFAULTS["map_list_page_size"])

    clear_screen()
    print_logo("SCORCH", proj_name)
    print(f"  {WHITE}Discovering map groups...{RST}")

    # Load map data and discover packages
    vanilla_maps, custom_maps, group_data = _load_map_groups(game_path)
    if not vanilla_maps:
        print(f"  {RED}No vanilla maps found.{RST}")
        input("  Press Enter > ")
        return

    packages = discover_packages(game_path, vanilla_maps, custom_maps,
                                 group_data)
    indexes = build_indexes(game_path, vanilla_maps, custom_maps, group_data)
    compute_cross_package_deps(packages, indexes["warp_index"],
                               indexes["connection_index"])

    # Sort alphabetically by display name (stable, no status sorting needed)
    packages.sort(key=lambda p: p.display_name)

    warp_idx = indexes["warp_index"]
    conn_idx = indexes["connection_index"]
    expanded_pkg = None  # name of currently expanded group (or None)
    cursor_idx = 0
    scroll_top = 0

    while True:
        # Guard bounds
        cursor_idx = max(0, min(cursor_idx, len(packages) - 1))
        if cursor_idx < scroll_top:
            scroll_top = cursor_idx
        if cursor_idx >= scroll_top + page_size:
            scroll_top = cursor_idx - page_size + 1

        clear_screen()
        print_logo("SCORCH", proj_name)
        print(BAR)
        print(f"   {WHITE}SCORCH \u2014 MAP GROUPS{RST}   "
              f"{DIM}{len(packages)} groups{RST}")
        print(BAR)

        # Inline help
        print(f"  {DIM}Vanilla maps grouped by location. Expand a group to see its maps and connections.{RST}")
        print()

        # Render visible groups
        end = min(scroll_top + page_size, len(packages))

        if scroll_top > 0:
            print(f"  {DIM}  \u2191 {scroll_top} more above{RST}")

        for li in range(scroll_top, end):
            pkg = packages[li]
            is_expanded = expanded_pkg == pkg.name
            cursor = f"{GOLD}>>{RST}" if li == cursor_idx else "  "
            expand_icon = f"{DIM}[-]{RST}" if is_expanded else f"{DIM}[+]{RST}"

            name_col = WHITE if li == cursor_idx else ""
            name_rst = RST if name_col else ""

            n_maps = len(pkg.maps)
            n_conns = len(pkg.depends_on)
            maps_str = f"{n_maps} map{'s' if n_maps != 1 else ''}"
            conns_str = (f"   {DIM}{n_conns} connection{'s' if n_conns != 1 else ''}{RST}"
                         if n_conns > 0 else "")

            print(f"  {cursor} {expand_icon} "
                  f"{name_col}{pkg.display_name:<28}{name_rst} "
                  f"{DIM}{maps_str:>8}{RST}{conns_str}")

            # In-place expansion: show maps with warp/connection destinations
            if is_expanded:
                _render_expanded_maps(pkg, warp_idx, conn_idx)

        remaining = len(packages) - end
        if remaining > 0:
            print(f"  {DIM}  \u2193 {remaining} more below{RST}")

        print()

        # Command bar
        cmd_parts = [
            f"{_k('Enter')} {DIM}scroll{RST}",
            f"{_k(NK_UP)}/{_k(NK_DOWN)} {DIM}navigate{RST}",
            f"{_k('f')} {DIM}expand{RST}",
            f"{_k('q')} {DIM}back{RST}",
        ]
        print("  " + "  ".join(cmd_parts))
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").strip()
        except (EOFError, KeyboardInterrupt):
            return

        if raw == "":
            cursor_idx = (cursor_idx + 1) % len(packages)
            continue

        cmd = raw.lower()

        if cmd == "q":
            if expanded_pkg:
                expanded_pkg = None
            else:
                return

        elif cmd == NK_UP:
            cursor_idx = max(0, cursor_idx - 1)

        elif cmd == NK_DOWN:
            cursor_idx = min(len(packages) - 1, cursor_idx + 1)

        elif cmd == "f":
            pkg = packages[cursor_idx]
            if expanded_pkg == pkg.name:
                expanded_pkg = None
            else:
                expanded_pkg = pkg.name

        elif cmd.isdigit():
            idx = int(cmd) - 1
            if 0 <= idx < len(packages):
                cursor_idx = idx


def _render_expanded_maps(pkg, warp_idx, conn_idx):
    """Render map list with warp/connection destinations for an expanded group."""
    for map_name in sorted(pkg.maps):
        dests = set()
        for d in warp_idx.get(map_name, set()):
            dests.add(d)
        for d in conn_idx.get(map_name, set()):
            dests.add(d)
        if dests:
            dest_str = f"  {DIM}\u2192 {', '.join(sorted(dests))}{RST}"
        else:
            dest_str = ""
        print(f"         {DIM}{map_name}{RST}{dest_str}")




def _show_item_details(item):
    """Show detailed info for a RemovalItem."""
    clear_screen()
    print()
    print(f"  {WHITE}{item.name}{RST}")
    print(f"  {DIM}{'─' * 49}{RST}")
    print(f"  Status: {_badge(item.status)}")
    if item.detail:
        print(f"  {item.detail}")
    print()
    if item.refs:
        print(f"  {WHITE}References:{RST}")
        for ref in item.refs[:20]:
            print(f"    {DIM}{ref}{RST}")
        if len(item.refs) > 20:
            print(f"    {DIM}...and {len(item.refs) - 20} more{RST}")
    print()
    input("  Press Enter to go back > ")


# ============================================================
# CONFIRM & EXECUTE
# ============================================================

def _confirm_and_execute(game_path, plan, settings, category_hint=""):
    """Confirmation -> snapshot -> removal -> report -> build offer.

    Returns "rescan" if the user wants to rescan after removal,
    "exit" to leave SCORCH, or None for cancelled/no-op.
    """
    safe = plan.safe_items()
    if not safe:
        print(f"  {DIM}Nothing to remove.{RST}")
        input("  Press Enter > ")
        return None

    # Group counts for display
    by_cat = {}
    for item in safe:
        by_cat.setdefault(item.category, 0)
        by_cat[item.category] += 1

    print()
    print(f"  {WHITE}Ready to remove:{RST}")
    for cat_id, count in sorted(by_cat.items()):
        cat = _category_by_id(cat_id)
        label = cat["label"] if cat else cat_id
        if cat_id in _IMPLEMENTED_REMOVERS:
            print(f"    {label}: {CYAN}{count}{RST} item(s)")
        else:
            print(f"    {label}: {CYAN}{count}{RST} item(s)  {DIM}(scan only — removal not yet implemented){RST}")
    total = sum(c for cid, c in by_cat.items() if cid in _IMPLEMENTED_REMOVERS)
    pending = sum(c for cid, c in by_cat.items() if cid not in _IMPLEMENTED_REMOVERS)
    print()
    print(f"  {WHITE}Total: {total} item(s) will be removed.{RST}")
    if pending:
        print(f"  {DIM}{pending} item(s) from unimplemented categories will be skipped.{RST}")
    print()

    try:
        confirm = input(f"  Proceed? [y/N] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if confirm != "y":
        print("  Cancelled.")
        print()
        input("  Press Enter > ")
        return None

    # Snapshot
    print()
    print(f"  {WHITE}Creating pre-removal snapshot...{RST}")
    snapshot_path = _create_cleanup_snapshot(game_path, plan, category_hint)
    if snapshot_path == "skip":
        # Nothing needed snapshotting (e.g. graphics/music only)
        snapshot_path = None
        print(f"    {DIM}No files require snapshotting.{RST}")
    elif snapshot_path:
        print(f"    {GREEN}Snapshot: {os.path.basename(snapshot_path)}{RST}")
    else:
        print(f"    {RED}WARNING: Snapshot creation failed.{RST}")
        try:
            proceed = input("  Continue anyway? [y/N] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if proceed != "y":
            print("  Cancelled.")
            return

    # Execute
    print()
    print(f"  {WHITE}Removing vanilla content...{RST}")
    print()

    results = execute_removal(game_path, plan)

    # Report
    print()
    print(BAR)
    print(f"   {WHITE}REMOVAL COMPLETE{RST}")
    total_removed = 0
    all_errors = []
    for cat_id, (count, errors) in results.items():
        cat = _category_by_id(cat_id)
        label = cat["label"] if cat else cat_id
        if cat_id not in _IMPLEMENTED_REMOVERS:
            print(f"    {label}: {DIM}skipped (not yet implemented){RST}")
        else:
            print(f"    {label}: {GREEN}{count}{RST} removed")
            total_removed += count
            all_errors.extend(errors)
    print(BAR)
    print()

    if all_errors:
        print(f"  {RED}Errors ({len(all_errors)}):{RST}")
        for err in all_errors:
            print(f"    {RED}{err}{RST}")
        print()

    if snapshot_path:
        print(f"  {DIM}Restore with: torch scorch restore{RST}")
        print()

    # Build offer (only if something was actually removed)
    if total_removed > 0:
        _offer_build(game_path)

        # Offer rescan or exit
        print()
        print(f"  {_k('r')} {DIM}Rescan (continue removing){RST}    "
              f"{_k('q')} {DIM}Exit SCORCH{RST}")
        print()
        try:
            post = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "exit"
        if post == "r":
            return "rescan"
        return "exit"
    else:
        input("  Press Enter to continue > ")
        return None


# ============================================================
# REPORT MODE
# ============================================================

def _report_mode(game_path, settings, proj_name=None):
    """Scan-only mode: generate and optionally save a report."""
    clear_screen()
    print_logo("SCORCH", proj_name)
    print(BAR)
    print(f"   {WHITE}SCORCH \u2014 SCAN REPORT{RST}")
    print(BAR)
    print()

    # Pre-flight
    warnings = _preflight_checks(game_path)
    for w in warnings:
        icon = f"{RED}!{RST}" if "not found" in w.lower() else f"{DGOLD}!{RST}"
        print(f"  {icon} {w}")
    if any("not found" in w.lower() for w in warnings):
        print()
        print("  Cannot scan -- fix the above errors first.")
        input("  Press Enter > ")
        return

    print(f"  {GOLD}Scanning all content categories... this may take 30-60 seconds.{RST}")
    print()
    sys.stdout.flush()
    plan = full_scan(game_path)
    print(f"  {DIM}Scan complete.{RST}")
    print()
    _display_scan_report(plan)

    if plan.scan_errors:
        print(f"  {RED}Scan errors:{RST}")
        for err in plan.scan_errors:
            print(f"    {err}")
        print()

    # Offer to save
    _save_report(game_path, plan)


def _save_report(game_path, plan):
    """Save scan report to a text file."""
    try:
        save = input(f"  Save report to file? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if save in ("n", "no"):
        return

    backup_dir = os.path.join(game_path, "backups", "cleanup")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(backup_dir, f"scorch_report_{timestamp}.txt")

    lines = []
    lines.append("TORCH SCORCH — Scan Report")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Game Path: {game_path}")
    lines.append("=" * 60)
    lines.append("")

    summary = plan.category_summary()
    lines.append(f"{'Category':<20}  {'Total':>6}  {'Safe':>6}  {'Blocked':>8}")
    lines.append(f"{'─' * 20}  {'─' * 6}  {'─' * 6}  {'─' * 8}")

    for s in summary:
        lines.append(f"{s['label']:<20}  {s['total']:>6}  {s['safe']:>6}  {s['blocked']:>8}")

    lines.append("")
    lines.append("=" * 60)
    lines.append("")

    # Detailed listing per category
    for cat in CATEGORIES:
        cat_items = plan.by_category(cat["id"])
        if not cat_items:
            continue
        lines.append(f"--- {cat['label']} ---")
        lines.append("")
        for item in sorted(cat_items, key=lambda x: x.name):
            status_tag = f"[{item.status}]"
            lines.append(f"  {status_tag:<10} {item.name}")
            if item.detail:
                lines.append(f"  {'':>10} {item.detail}")
            if item.refs:
                for ref in item.refs[:5]:
                    lines.append(f"  {'':>10}   -> {ref}")
                if len(item.refs) > 5:
                    lines.append(f"  {'':>10}   ...and {len(item.refs) - 5} more")
        lines.append("")

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"  {GREEN}Report saved: {report_path}{RST}")
    except OSError as e:
        print(f"  {RED}Failed to save report: {e}{RST}")
    print()
    input("  Press Enter to continue > ")


# ============================================================
# RESTORE MODE
# ============================================================

def _restore_menu(game_path, settings, proj_name=None):
    """List and restore cleanup snapshots (Singe + Phoenix)."""
    clear_screen()
    print_logo("SCORCH", proj_name)
    print(BAR)
    print(f"   {WHITE}SCORCH \u2014 RESTORE FROM SNAPSHOT{RST}")
    print(BAR)
    print()

    # Gather Singe snapshots
    singe_snapshots = _list_cleanup_snapshots(game_path)
    for s in singe_snapshots:
        s["_type"] = "singe"

    # Gather Phoenix snapshots (if available)
    phoenix_snapshots = []
    try:
        from torch.scorch_writer import list_scorch_snapshots
        phoenix_snapshots = list_scorch_snapshots(game_path)
        for s in phoenix_snapshots:
            s["_type"] = "phoenix"
    except ImportError:
        pass

    # Combine and sort by display_time descending
    all_snapshots = singe_snapshots + phoenix_snapshots
    all_snapshots.sort(key=lambda x: x.get("display_time", ""), reverse=True)

    if not all_snapshots:
        print(f"  {DIM}No SCORCH snapshots found.{RST}")
        print()
        input("  Press Enter to go back > ")
        return

    for i, snap in enumerate(all_snapshots):
        if snap["_type"] == "phoenix":
            label = f"{CYAN}Phoenix{RST}"
        elif snap.get("legacy"):
            label = f"{DIM}(legacy){RST}"
        else:
            cat = snap.get('category_hint') or "full"
            label = f"{WHITE}Singe: {cat}{RST}"
        print(f"  {_k(i + 1)} {label} {DIM}\u2014{RST} {snap['display_time']}  "
              f"{DIM}{snap['filename']}{RST}")
    print()
    print(f"  {_k('q')} {DIM}Back{RST}")
    print()

    try:
        raw = input(f"  {GOLD}Restore which? >{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if raw == "q" or raw == "":
        return

    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(all_snapshots):
            _execute_restore(game_path, all_snapshots[idx])
            return

    print("  Invalid choice.")
    input("  Press Enter > ")


def _execute_restore(game_path, snap):
    """Execute a snapshot restore (Singe or Phoenix)."""
    print()
    try:
        confirm = input(
            f"  Restore from {snap['filename']}? "
            f"This will overwrite current files. [y/N] > "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm != "y":
        print("  Cancelled.")
        input("  Press Enter > ")
        return

    print()
    print(f"  {WHITE}Restoring...{RST}")

    if snap["_type"] == "phoenix":
        from torch.scorch_writer import restore_scorch_snapshot
        restored = restore_scorch_snapshot(game_path, snap["path"])
    else:
        restored = _restore_cleanup_snapshot(game_path, snap["path"])

    if restored is not None:
        print(f"  {GREEN}Restored {len(restored)} file(s).{RST}")
        for rel in restored[:10]:
            print(f"    {DIM}{rel}{RST}")
        if len(restored) > 10:
            print(f"    {DIM}...and {len(restored) - 10} more{RST}")
        print()
        _offer_build(game_path)
    else:
        print(f"  {RED}Restore failed -- check error messages above.{RST}")
        input("  Press Enter > ")
