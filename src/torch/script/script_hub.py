"""Studio hub -- map browser, script list, new script wizard."""
# TORCH_MODULE: Script Hub
# TORCH_GROUP: Studio
import os
import re
import json

from torch import SCRIPT_VERSION
from torch.config import SETTINGS_DEFAULTS, _nav_keys
from torch.ui import print_logo, _set_terminal_title, _k, clear_screen
from torch.script_model import _parse_script, _ensure_setup_pory, _serialize_script, _script_help_screen
from torch.script_editor import _script_editor_loop, _script_info, _load_flag_log, _save_flag_log
from torch.script_movements import _movement_block_manager
from torch.map_scanner import _scan_game_maps, _import_map, _read_map_metadata, _SKIP_WORKSPACE_DIRS
from torch.sync import sync_map, create_snapshot, ensure_synced

from torch.colours import GOLD, WHITE, CYAN, DIM, RST, GREEN, DGOLD, RED, BAR

# Semantic status colours (keep local, reference palette)
_C_ACTIVE  = GREEN
_C_CUSTOM  = DGOLD
_C_ORPHAN  = RED
_C_VANILLA = DIM
_C_RESET   = RST


# Session-level cache for map metadata (never changes within a session)
_metadata_cache = {}


def _refresh_all_caches():
    """Clear all read-side caches so the next access re-reads from disk.
    Call on Studio entry and on manual [r] refresh."""
    from torch.project_files import clear_project_cache
    from torch.gamedata import clear_gamedata_cache
    from torch.sync import clear_label_cache
    clear_project_cache()
    clear_gamedata_cache()
    clear_label_cache()
    _metadata_cache.clear()


# -- Helpers promoted from script_builder_menu closures -------------------------

def _hub_status_colour(status):
    """Return ANSI colour code for a map status tag."""
    return {
        "ACTIVE":  _C_ACTIVE,
        "CUSTOM":  _C_CUSTOM,
        "ORPHAN":  _C_ORPHAN,
        "VANILLA": _C_VANILLA,
    }.get(status, "")


def _hub_sorted_maps(all_maps, show_van):
    """Sort maps into display order: ACTIVE (by mtime), CUSTOM, ORPHAN, [VANILLA]."""
    active  = sorted([m for m in all_maps if m["status"] == "ACTIVE"],
                     key=lambda m: -m["mtime"])
    custom  = sorted([m for m in all_maps if m["status"] == "CUSTOM"],
                     key=lambda m: m["name"])
    orphan  = sorted([m for m in all_maps if m["status"] == "ORPHAN"],
                     key=lambda m: m["name"])
    vanilla = sorted([m for m in all_maps if m["status"] == "VANILLA"],
                     key=lambda m: m["name"])
    if show_van:
        return active + custom + orphan + vanilla
    return active + custom + orphan


def _hub_open_active(m, project_dir, game_path, emotes_conf, source_display,
                     settings, proj_name):
    """Open the script browser for an already-imported map."""
    # Auto-sync if stale before entering the browser
    ensure_synced(m["name"], project_dir, game_path, emotes_conf,
                  source_display, settings.get("max_snapshots", 10))
    map_dir = os.path.join(project_dir, m["name"])
    scripts = []
    if os.path.isdir(map_dir):
        for fname in sorted(os.listdir(map_dir)):
            if fname.endswith(".txt"):
                sname = os.path.splitext(fname)[0]
                fpath = os.path.join(map_dir, fname)
                mtime = os.path.getmtime(fpath)
                scripts.append((sname, fpath, mtime))
        scripts.sort(key=lambda x: x[2], reverse=True)
    _script_map_browser(m["name"], scripts, project_dir, game_path,
                        emotes_conf, source_display, settings, proj_name)


def _hub_gather_map_groups(project_dir):
    """Scan workspace and return {map_name: [(script_name, path, mtime), ...]}."""
    map_groups = {}
    if os.path.isdir(project_dir):
        for entry in os.listdir(project_dir):
            map_dir = os.path.join(project_dir, entry)
            if not os.path.isdir(map_dir) or entry in _SKIP_WORKSPACE_DIRS:
                continue
            scripts = []
            for fname in sorted(os.listdir(map_dir)):
                if fname.endswith(".txt"):
                    sname = os.path.splitext(fname)[0]
                    fpath = os.path.join(map_dir, fname)
                    mtime = os.path.getmtime(fpath)
                    scripts.append((sname, fpath, mtime))
            scripts.sort(key=lambda x: x[2], reverse=True)
            map_groups[entry] = scripts
    return map_groups


# -- Dashboard header ----------------------------------------------------------

def _get_attention_maps(project_dir, game_path, active_maps):
    """Return (stale_names, drift_names) for enrolled active maps."""
    try:
        from torch.registry import get_map_health, is_enrolled
    except (ImportError, Exception):
        return [], []
    stale = []
    drift = []
    for m in active_maps:
        if not is_enrolled(project_dir, m["name"]):
            continue
        health = get_map_health(project_dir, m["name"], game_path)
        if health in ("stale", "never_written"):
            stale.append(m["name"])
        elif health == "drift":
            drift.append(m["name"])
    return stale, drift


def _get_last_build_info(game_path):
    """Return human-readable last build time and status."""
    import time as _time
    rom_path = os.path.join(game_path, "pokeemerald.gba")
    if not os.path.isfile(rom_path):
        for name in ("pokeemerald-expansion.gba", "pokeseihoku.gba"):
            p = os.path.join(game_path, name)
            if os.path.isfile(p):
                rom_path = p
                break
        else:
            return "Last built: never"
    try:
        mtime = os.path.getmtime(rom_path)
        age = _time.time() - mtime
        if age < 60:
            ago = "just now"
        elif age < 3600:
            mins = int(age / 60)
            ago = f"{mins} minute{'s' if mins != 1 else ''} ago"
        elif age < 86400:
            hours = int(age / 3600)
            ago = f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = int(age / 86400)
            ago = f"{days} day{'s' if days != 1 else ''} ago"
        return f"Last built: {ago}"
    except OSError:
        return "Last built: unknown"


def _render_dashboard_header(proj_name, game_path, project_dir, view_mode,
                             visible, all_maps, settings, show_vanilla=False):
    """Render the Studio workspace dashboard header."""
    # Logo + title
    print_logo("Studio", proj_name)
    print(BAR)

    # View mode line
    count = len(visible)
    if all_maps is None:
        all_maps = []
    if view_mode == "recent":
        view_label = f"View: RECENT ({count})"
        toggle_hint = "[r] show all maps"
    else:
        active_count = sum(1 for m in all_maps if m["status"] == "ACTIVE")
        vanilla_count = sum(1 for m in all_maps if m["status"] == "VANILLA")
        if show_vanilla and vanilla_count > 0:
            view_label = f"View: ALL ({active_count} active, {vanilla_count} vanilla shown)"
        elif vanilla_count > 0:
            view_label = f"View: ALL ({active_count} active, {vanilla_count} vanilla hidden)"
        else:
            view_label = f"View: ALL ({active_count} active)"
        toggle_hint = "[r] show recent"
    print(f"  {WHITE}{view_label}{RST} - {DIM}{toggle_hint}{RST}")

    # Status counts line: Active: N | Orphan: N | Stale: ... | Drift: ...
    active_maps = [m for m in all_maps if m["status"] == "ACTIVE"]
    active_count = len(active_maps)
    orphan_count = sum(1 for m in all_maps if m["status"] == "ORPHAN")
    stale_maps, drift_maps = _get_attention_maps(project_dir, game_path, active_maps) if project_dir else ([], [])
    status_parts = [f"Active: {active_count}"]
    if orphan_count > 0:
        status_parts.append(f"Orphan: {orphan_count}")
    if stale_maps:
        if len(stale_maps) <= 3:
            status_parts.append(f"Stale: {', '.join(stale_maps)}")
        else:
            status_parts.append(f"Stale: {', '.join(stale_maps[:3])} + {len(stale_maps) - 3} more")
    if drift_maps:
        if len(drift_maps) <= 3:
            status_parts.append(f"Drift: {', '.join(drift_maps)}")
        else:
            status_parts.append(f"Drift: {', '.join(drift_maps[:3])} + {len(drift_maps) - 3} more")
    # Hint to sync if anything needs attention
    needs_sync = len(stale_maps) + len(drift_maps)
    if needs_sync > 0:
        status_parts.append(f"[y] sync")
    print(f"  {DIM}{' | '.join(status_parts)} | {RST}")

    # Last build line
    build_info = _get_last_build_info(game_path) if game_path else "Last built: unknown"
    print(f"  {DIM}{build_info}{RST}")
    print(BAR)


# -- Display pipeline ----------------------------------------------------------

def _hub_render_table_header(num_w, name_w):
    """Print the table column header row."""
    # 3 chars for pre (>> or spaces) + name_w + 2 for marker = total name column
    name_col_w = name_w + 2
    print(f"  {DIM} {'#':>{num_w + 1}}   {'Status':<10}"
          f"   {'Name':<{name_col_w}}  NPCs  Scripts Trainers Encounters{RST}")


_NAME_ABRIDGE_THRESHOLD = 23
_NAME_ABRIDGE_SIDE = 8


def _abridge_name(name):
    """Shorten long map names: first 9 + (...) + last 9."""
    if len(name) <= _NAME_ABRIDGE_THRESHOLD:
        return name
    return name[:_NAME_ABRIDGE_SIDE] + "(...)" + name[-_NAME_ABRIDGE_SIDE:]


def _hub_render_row(m, list_i, selected_idx, num_w, map_groups,
                    game_path=None, project_dir=None, name_w=30):
    """Render a single map row in the hub list.

    ACTIVE rows show inline metadata columns (NPCs, Scripts, Trainers, Encounters).
    The selected ACTIVE row also shows a detail dropdown with names/labels.
    Cursor >> and < flank the map name on the selected row.
    """
    is_sel = list_i == selected_idx
    num = f"{list_i + 1}."
    col = _hub_status_colour(m["status"])
    tag = f"[{m['status']}]"
    name_display = _abridge_name(m["name"])
    # >> before name on selected row; spaces for alignment otherwise
    pre = f"{GOLD}>>{RST} " if is_sel else "   "
    # < tight after name, then pad remaining space.
    # Reserve 2 extra chars in the name column for the " <" marker.
    name_col_w = name_w + 2
    if is_sel:
        name_with_marker = f"{name_display} {GOLD}<{RST}"
        # visible length: len(name_display) + 2 (" <")
        pad_remaining = max(0, name_col_w - len(name_display) - 2)
        name_block = f"{col}{name_with_marker}{_C_RESET}{' ' * pad_remaining}"
    else:
        name_block = f"{col}{name_display:<{name_col_w}}{_C_RESET}"
    pipe = f"{GOLD}|{RST}"

    if m["status"] == "ACTIVE":
        # Get cached metadata for inline summary
        meta = None
        if game_path:
            meta = _metadata_cache.get(m["name"])
            if meta is None:
                meta = _read_map_metadata(game_path, m["name"])
                _metadata_cache[m["name"]] = meta

        if meta:
            scripts = m.get("torscript_count", m.get("script_count", 0))
            enc_types = meta.get("encounter_types", [])
            enc_str = "/".join(enc_types) if enc_types else ""
            print(f"  {col}  {num:>{num_w + 1}} {tag:<10}{_C_RESET}{pre}"
                  f"{name_block}"
                  f"  {meta['npc_count']:>2}  {pipe}  {scripts:>2}   "
                  f"{pipe}   {meta['trainer_count']:>2}   {pipe} {enc_str}")
        else:
            print(f"  {col}  {num:>{num_w + 1}} {tag:<10}{_C_RESET}{pre}"
                  f"{name_block}")

    elif m["status"] == "CUSTOM":
        print(f"  {col}  {num:>{num_w + 1}} {tag:<10}{_C_RESET}{pre}"
              f"{name_block}  \u2014 not imported")
    elif m["status"] == "ORPHAN":
        print(f"  {col}  {num:>{num_w + 1}} {tag:<10}{_C_RESET}{pre}"
              f"{name_block}  {DIM}no game map found{RST}")
    else:
        print(f"  {col}  {num:>{num_w + 1}} {tag:<10}{_C_RESET}{pre}"
              f"{name_block}")


def _detail_line(indent, key_char, suffix, items, limit=8, fmt="list"):
    """Print a detail panel line: [K]suffix: item1, item2 +N."""
    if fmt == "enc" and items:
        body = "[" + " | ".join(f"{k} {v}" for k, v in items.items()) + "]"
    elif items:
        shown = items[:limit]
        body = ", ".join(shown)
        if len(items) > limit:
            body += f" +{len(items) - limit}"
    else:
        body = "(none)"
    print(f"{indent}{_k(key_char)}{_C_VANILLA}{suffix}: {body}{_C_RESET}")


def _hub_render_detail_panel(sel_map, game_path, map_groups, project_dir=None):
    """Render the detail panel for the selected map below the map list."""
    if not game_path or not sel_map:
        return
    if sel_map["status"] not in ("ACTIVE",):
        return
    meta = _metadata_cache.get(sel_map["name"])
    if not meta:
        return
    indent = "    "
    print()
    # [N]PCs
    _detail_line(indent, "n", "pcs", meta["npc_names"])
    # [S]cripts
    scripts = map_groups.get(sel_map["name"], [])
    script_parts = []
    for sname, fpath, _mt in scripts[:5]:
        beat_count, _desc = _script_info(fpath)
        script_parts.append(f"{sname} [{beat_count}]")
    if len(scripts) > 5:
        script_parts.append(f"+{len(scripts) - 5}")
    _detail_line(indent, "s", "cripts", script_parts, limit=6)
    # [T]rainers
    t_names = []
    for c in meta["trainer_consts"][:6]:
        raw = c[len("TRAINER_"):] if c.startswith("TRAINER_") else c
        t_names.append(raw.replace("_", " ").title())
    if len(meta["trainer_consts"]) > 6:
        t_names.append(f"+{len(meta['trainer_consts']) - 6}")
    _detail_line(indent, "t", "rainers", t_names, limit=7)
    # [E]ncounters
    _detail_line(indent, "e", "ncounters", meta.get("encounter_detail", {}),
                 fmt="enc")
    # [H]eal Locations
    hc = meta.get("heal_count", 0)
    print(f"{indent}{_k('h')}{_C_VANILLA}eal Locations: {hc if hc else 'none'}{_C_RESET}")
    # [M]arts
    mart_names = []
    try:
        from torch.shop_editor import find_shop_scripts
        shops = find_shop_scripts(game_path, sel_map["name"])
        mart_names = [s["label"] for s in shops if s.get("label")]
    except (ImportError, Exception):
        pass
    _detail_line(indent, "m", "arts", mart_names)
    # Sync status
    if project_dir:
        sync_label = "never"
        try:
            from torch.registry import load_registry
            reg = load_registry(project_dir)
            entry = reg.get("maps", {}).get(sel_map["name"])
            if entry:
                lw = entry.get("last_written")
                if lw is not None:
                    sync_label = lw
        except (ImportError, Exception):
            pass
        print(f"{indent}{DIM}{sel_map['name']} Last Synced: {sync_label}{RST}")


def _hub_render(visible, map_groups, selected_idx, scroll_top, page_size,
                show_vanilla, vanilla_count, custom_count, proj_name,
                NK_UP, NK_DOWN, game_path=None):
    """Render the Scripts mode hub screen."""

    clear_screen()
    print_logo(f"Studio  v{SCRIPT_VERSION}", proj_name)
    print(BAR)
    print(f"   {WHITE}SCRIPTS{RST}")
    print(BAR)
    print()

    if not visible:
        print("  (no maps found \u2014 check game_path in config)")
        print()
    else:
        num_w = len(str(len(visible)))
        name_w = max((len(_abridge_name(v["name"])) for v in visible), default=20)
        name_w = max(name_w, 20)

        _hub_render_table_header(num_w, name_w)

        for list_i in range(scroll_top, min(scroll_top + page_size, len(visible))):
            _hub_render_row(visible[list_i], list_i, selected_idx, num_w,
                            map_groups, game_path=game_path, name_w=name_w)

        if scroll_top > 0:
            print(f"  {_C_VANILLA}  \u2191 {scroll_top} more above{_C_RESET}")
        remaining_below = len(visible) - (scroll_top + page_size)
        if remaining_below > 0:
            print(f"  {_C_VANILLA}  \u2193 {remaining_below} more below{_C_RESET}")

        # Detail panel for highlighted map
        if game_path and 0 <= selected_idx < len(visible):
            sel_map = visible[selected_idx]
            _hub_render_detail_panel(sel_map, game_path, map_groups)

        print()

    # Vanilla hint
    if not show_vanilla and vanilla_count > 0:
        print(f"  {_C_VANILLA}{vanilla_count} vanilla map{'s' if vanilla_count != 1 else ''} hidden -- [z] to show{_C_RESET}")
    elif show_vanilla and vanilla_count > 0:
        print(f"  {_C_VANILLA}{vanilla_count} vanilla map{'s' if vanilla_count != 1 else ''} shown -- [z] to hide{_C_RESET}")
    print()

    # Command bar
    cmd_parts = [f"{_k('#')}/{_k('v')} {DIM}open{RST}  {_k('Enter')} {DIM}scroll{RST}"]
    cmd_parts += [f"{_k(NK_UP)} {DIM}up{RST}", f"{_k(NK_DOWN)} {DIM}down{RST}"]
    if custom_count > 0:
        cmd_parts.append(f"{_k('i')}{DIM}mport{RST}")
        cmd_parts.append(f"{_k('A')}{DIM}ll{RST}")
    cmd_parts += [f"{_k('n')}{DIM}ew{RST}", f"{_k('z')}{DIM} vanilla{RST}",
                  f"{_k('/')}{DIM}search{RST}", f"{_k('?')}{DIM} help{RST}",
                  f"{_k('#')} {DIM}refresh{RST}", f"{_k('q')} {DIM}back{RST}"]
    print("  " + "  ".join(cmd_parts))
    print()


# -- Input handlers for script_builder_menu -------------------------------------

def _hub_handle_open(sel, project_dir, game_path, emotes_conf, source_display,
                     settings, proj_name):
    """Handle 'v' key — open ACTIVE map or import CUSTOM map."""
    if not sel:
        return
    if sel["status"] == "ACTIVE":
        _hub_open_active(sel, project_dir, game_path, emotes_conf,
                         source_display, settings, proj_name)
    elif sel["status"] == "CUSTOM":
        print()
        confirm = input(
            f"  Import {sel['name']} into workspace? [Y/n] "
        ).strip().lower()
        if confirm in ("", "y", "yes"):
            _import_map(sel["name"], project_dir, game_path,
                        emotes_conf, source_display, settings, proj_name)
    else:
        print(f"  {sel['name']} ({sel['status']}) \u2014 nothing to open.")
        input("  [Enter to continue] ")


def _hub_handle_number(raw, visible, project_dir, game_path, emotes_conf,
                       source_display, settings, proj_name):
    """Handle numeric input — jump to row and act. Returns new selected_idx."""
    idx = int(raw) - 1
    if 0 <= idx < len(visible):
        m = visible[idx]
        if m["status"] == "ACTIVE":
            _hub_open_active(m, project_dir, game_path, emotes_conf,
                             source_display, settings, proj_name)
        elif m["status"] == "CUSTOM":
            print()
            confirm = input(
                f"  Import {m['name']} into workspace? [Y/n] "
            ).strip().lower()
            if confirm in ("", "y", "yes"):
                _import_map(m["name"], project_dir, game_path,
                            emotes_conf, source_display, settings, proj_name)
        return idx
    return None


def _hub_handle_toggle_vanilla(show_vanilla, sel, all_maps):
    """Handle 'f' key — toggle vanilla visibility. Returns (show_vanilla, selected_idx, scroll_top)."""
    show_vanilla = not show_vanilla
    if sel:
        new_visible = _hub_sorted_maps(all_maps, show_vanilla)
        try:
            selected_idx = next(
                i for i, m in enumerate(new_visible) if m["name"] == sel["name"]
            )
        except StopIteration:
            selected_idx = 0
    else:
        selected_idx = 0
    return show_vanilla, selected_idx, 0


def _hub_handle_search(all_maps, show_vanilla):
    """Handle '/' key — search maps. Returns (selected_idx, scroll_top) or None."""
    try:
        query = input("  Search: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if query:
        new_visible = _hub_sorted_maps(all_maps, show_vanilla)
        matches = [i for i, m in enumerate(new_visible)
                   if query in m["name"].lower()]
        if matches:
            return matches[0], max(0, matches[0] - 2)
        else:
            print(f"  No maps matching '{query}'.")
            input("  [Enter to continue] ")
    return None


def _hub_parse_pick_tokens(pick, custom_maps):
    """Parse user input tokens into chosen maps and bad tokens."""
    if pick == "a":
        pick = " ".join(str(i) for i in range(1, len(custom_maps) + 1))
    tokens = pick.replace(",", " ").split()
    chosen = []
    bad = []
    for t in tokens:
        if t.isdigit():
            i = int(t) - 1
            if 0 <= i < len(custom_maps):
                chosen.append(custom_maps[i])
            else:
                bad.append(t)
        else:
            bad.append(t)
    return chosen, bad


def _hub_import_chosen(chosen, project_dir, game_path, emotes_conf,
                       source_display, settings, proj_name):
    """Import a list of chosen maps (single or batch with confirmation)."""
    if len(chosen) == 1:
        _import_map(chosen[0]["name"], project_dir, game_path,
                    emotes_conf, source_display, settings, proj_name)
        return
    print()
    print(f"  Importing {len(chosen)} map(s):")
    for m in chosen:
        print(f"    {_C_CUSTOM}{m['name']}{_C_RESET}")
    print()
    try:
        confirm = input("  Proceed? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm not in ("", "y", "yes"):
        return
    ok_count = 0
    fail_count = 0
    for m in chosen:
        if _import_map(m["name"], project_dir, game_path,
                       emotes_conf, source_display, settings, proj_name):
            ok_count += 1
        else:
            fail_count += 1
    print()
    print(f"  Done. {ok_count} imported" +
          (f", {fail_count} failed" if fail_count else "") + ".")
    input("  [Enter to continue] ")


def _hub_handle_pick_import(all_maps, project_dir, game_path, emotes_conf,
                            source_display, settings, proj_name):
    """Handle 'i' key — pick-and-import checklist sub-menu."""
    custom_maps = sorted([m for m in all_maps if m["status"] == "CUSTOM"],
                          key=lambda m: m["name"])
    if not custom_maps:
        print("\n  No custom maps to import.")
        input("  [Enter to continue] ")
        return
    clear_screen()
    print_logo(f"Studio  v{SCRIPT_VERSION}", proj_name)
    print(BAR)
    print(f"   {WHITE}IMPORT MAPS{RST}")
    print(BAR)
    print()
    for idx, m in enumerate(custom_maps, 1):
        print(f"  {_C_CUSTOM}{idx:<4} {m['name']}{_C_RESET}")
    print()
    print(f"  {DIM}Enter number(s) to import (e.g. 1  or  1 3 5),{RST}")
    print(f"  {GOLD}[a]{RST} {DIM}import all,{RST}  {GOLD}[q]{RST} {DIM}cancel{RST}")
    print()
    try:
        pick = input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if pick in ("q", ""):
        return
    chosen, bad = _hub_parse_pick_tokens(pick, custom_maps)
    if bad:
        print(f"  Unrecognised: {', '.join(bad)}")
        input("  [Enter to continue] ")
        return
    if chosen:
        _hub_import_chosen(chosen, project_dir, game_path, emotes_conf,
                           source_display, settings, proj_name)


def _hub_handle_import_all(all_maps, project_dir, game_path, emotes_conf,
                           source_display, settings, proj_name):
    """Handle 'A' key — import all CUSTOM maps."""
    custom_maps = sorted([m for m in all_maps if m["status"] == "CUSTOM"],
                          key=lambda m: m["name"])
    if not custom_maps:
        print("\n  No custom maps to import.")
        input("  [Enter to continue] ")
        return
    clear_screen()
    print_logo(f"Studio  v{SCRIPT_VERSION}", proj_name)
    print(BAR)
    print(f"   {WHITE}IMPORT ALL CUSTOM MAPS{RST}")
    print(BAR)
    print()
    print(f"  {DIM}{len(custom_maps)} custom map(s) will be imported:{RST}")
    print()
    for m in custom_maps:
        print(f"    {_C_CUSTOM}{m['name']}{_C_RESET}")
    print()
    try:
        confirm = input("  Import all? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm not in ("", "y", "yes"):
        return
    ok_count = 0
    fail_names = []
    for m in custom_maps:
        if _import_map(m["name"], project_dir, game_path,
                       emotes_conf, source_display, settings, proj_name):
            ok_count += 1
        else:
            fail_names.append(m["name"])
    print()
    print(BAR)
    print(f"  {WHITE}Import complete:{RST} {DIM}{ok_count}/{len(custom_maps)} succeeded{RST}")
    if fail_names:
        print(f"  {DIM}Failed:{RST}")
        for n in fail_names:
            print(f"    {_C_ORPHAN}{n}{_C_RESET}")
    print(BAR)
    input("  [Enter to continue] ")


# -- Main hub dispatcher -------------------------------------------------------

_QUIT = "QUIT"  # sentinel returned by _hub_dispatch to signal exit


def _hub_dispatch(raw, state, ctx):
    """Dispatch a single input command. Updates state dict in-place. Returns _QUIT to exit."""
    visible = state["visible"]
    sel = state["sel"]

    # Enter (empty) -> scroll down one row
    if raw == "":
        if visible:
            state["idx"] = (state["idx"] + 1) % len(visible)
        return

    raw = raw.strip()

    # Act key -> open/import highlighted item
    if raw.lower() == "v":
        _hub_handle_open(sel, ctx["project_dir"], ctx["game_path"], ctx["emotes_conf"],
                         ctx["source_display"], ctx["settings"], ctx["proj_name"])
        return

    # Number -> jump to that row and act immediately
    if raw.isdigit():
        new_idx = _hub_handle_number(raw, visible, ctx["project_dir"], ctx["game_path"],
                                     ctx["emotes_conf"], ctx["source_display"],
                                     ctx["settings"], ctx["proj_name"])
        if new_idx is not None:
            state["idx"] = new_idx
        return

    cmd = raw.lower()

    if cmd == "q":
        return _QUIT

    if cmd == ctx["NK_UP"]:
        if visible:
            state["idx"] = max(0, state["idx"] - 1)
    elif cmd == ctx["NK_DOWN"]:
        if visible:
            state["idx"] = min(len(visible) - 1, state["idx"] + 1)
    elif cmd == "z":
        state["show_van"], state["idx"], state["top"] = _hub_handle_toggle_vanilla(
            state["show_van"], sel, state["all_maps"])
    elif cmd == "/":
        result = _hub_handle_search(state["all_maps"], state["show_van"])
        if result is not None:
            state["idx"], state["top"] = result
    elif cmd == "n":
        _new_script_wizard(ctx["project_dir"], ctx["game_path"], ctx["emotes_conf"],
                          ctx["source_display"], ctx["settings"], ctx["proj_name"])
    elif cmd == "?":
        _script_help_screen()
    elif cmd == "i":
        _hub_handle_pick_import(state["all_maps"], ctx["project_dir"], ctx["game_path"],
                                ctx["emotes_conf"], ctx["source_display"],
                                ctx["settings"], ctx["proj_name"])
    elif raw == "A":
        _hub_handle_import_all(state["all_maps"], ctx["project_dir"], ctx["game_path"],
                               ctx["emotes_conf"], ctx["source_display"],
                               ctx["settings"], ctx["proj_name"])
    elif cmd == "r":
        _refresh_all_caches()


def _hub_guard_bounds(state, page_size):
    """Clamp selection index and adjust scroll viewport."""
    visible = state["visible"]
    if not visible:
        state["idx"] = 0
        return
    state["idx"] = max(0, min(state["idx"], len(visible) - 1))
    if state["idx"] < state["top"]:
        state["top"] = state["idx"]
    if state["idx"] >= state["top"] + page_size:
        state["top"] = state["idx"] - page_size + 1


def _scripts_map_list(project_dir, game_path, emotes_conf, source_display,
                      settings=None, proj_name=None):
    """Scripts mode — map list (ACTIVE/CUSTOM/ORPHAN) with highlight navigation."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if proj_name is None:
        proj_name = os.path.basename(project_dir) or None
    _set_terminal_title("TORCH \u2014 Studio")

    page_size = settings.get("map_list_page_size", SETTINGS_DEFAULTS["map_list_page_size"])
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)

    ctx = {
        "project_dir": project_dir, "game_path": game_path,
        "emotes_conf": emotes_conf, "source_display": source_display,
        "settings": settings, "proj_name": proj_name,
        "NK_UP": NK_UP, "NK_DOWN": NK_DOWN,
    }
    state = {"idx": 0, "top": 0, "show_van": False,
             "visible": [], "all_maps": [], "sel": None}

    while True:
        state["all_maps"] = _scan_game_maps(game_path, project_dir)
        vanilla_count = sum(1 for m in state["all_maps"] if m["status"] == "VANILLA")
        custom_count  = sum(1 for m in state["all_maps"] if m["status"] == "CUSTOM")
        state["visible"] = _hub_sorted_maps(state["all_maps"], state["show_van"])
        map_groups = _hub_gather_map_groups(project_dir)

        _hub_guard_bounds(state, page_size)
        state["sel"] = state["visible"][state["idx"]] if state["visible"] else None

        _hub_render(state["visible"], map_groups, state["idx"], state["top"], page_size,
                    state["show_van"], vanilla_count, custom_count, proj_name,
                    NK_UP, NK_DOWN, game_path)

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return
        raw = raw.rstrip("\n")

        if _hub_dispatch(raw, state, ctx) is _QUIT:
            return


# -- Landing page support functions --------------------------------------------

def _landing_trainers(project_dir, game_path, workspace_expanded, settings,
                      emotes_conf, source_display, proj_name):
    """Landing page [2] Trainers — delegate to map-centric trainer browser."""
    try:
        from torch.battle_manager import battle_map_browser
        battle_map_browser(game_path, project_dir, settings,
                           emotes_conf=emotes_conf, source_display=source_display,
                           proj_name=proj_name, workspace_expanded=workspace_expanded)
    except ImportError:
        print("  Trainers is not available in this release.")
        input("  Press Enter > ")


def _landing_trainers_flat(project_dir, game_path, workspace_expanded, settings,
                           proj_name):
    """Global trainers [gt] — open flat trainer list directly."""
    try:
        from torch.battle_manager import _list_all_trainers, _scan_custom_battles
        from torch.names import _detect_trainer_format
        fmt = _detect_trainer_format(game_path)
        battles = _scan_custom_battles(project_dir)
        opponents_path = os.path.join(game_path, "include", "constants", "opponents.h")
        trainers_h_path = os.path.join(game_path, "src", "data", "trainers.h")
        trainer_parties_path = os.path.join(game_path, "src", "data", "trainer_parties.h")
        _list_all_trainers(battles, opponents_path, trainers_h_path,
                           trainer_parties_path, project_dir, game_path,
                           workspace_expanded, settings, fmt=fmt)
    except ImportError:
        print("  Trainers is not available in this release.")
        input("  Press Enter > ")


def _landing_encounters(project_dir, game_path, workspace_expanded, settings,
                        emotes_conf, source_display, proj_name):
    """Landing page [3] Encounters — delegate to encounter_editor."""
    try:
        from torch.encounter_editor import encounter_command
        encounter_command([], project_dir, game_path, workspace_expanded, settings,
                          emotes_conf=emotes_conf, source_display=source_display,
                          proj_name=proj_name)
    except ImportError:
        print("  Encounter Editor is not available in this release.")
        input("  Press Enter > ")


def _landing_heal(project_dir, game_path, settings, proj_name):
    """Landing page [4] Heal Locations — delegate to heal_locations."""
    try:
        from torch.heal_locations import heal_command
        heal_command([], game_path, project_dir, settings=settings,
                     proj_name=proj_name)
    except ImportError:
        print("  Heal Location Manager is not available in this release.")
        input("  Press Enter > ")


def _landing_shops(game_path, settings, proj_name, project_dir):
    """Landing page [6] Shops — pick a map then open shop editor."""
    try:
        from torch.shop_editor import detect_shop_npcs, shop_editor_menu
        from torch.map_scanner import _scan_game_maps
    except ImportError:
        print("  Shop Editor is not available.")
        input("  Press Enter > ")
        return

    # Find maps that have shopkeepers
    all_maps = _scan_game_maps(game_path, None)
    shop_maps = []
    for m in all_maps:
        if m.get("status") in ("ACTIVE", "CUSTOM", "VANILLA"):
            npcs = detect_shop_npcs(game_path, m["name"])
            if npcs:
                shop_maps.append(m["name"])

    if not shop_maps:
        print(f"  {DIM}No maps with shopkeepers found.{RST}")
        input("  Press Enter > ")
        return

    clear_screen()
    print()
    print(f"  {WHITE}Maps with Shops{RST}")
    print(BAR)
    for i, name in enumerate(shop_maps, 1):
        print(f"    {GOLD}[{i}]{RST} {WHITE}{name}{RST}")
    print()
    print(f"  {DIM}Enter number to open, {_k('q')} back{RST}")
    print()

    try:
        raw = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if raw == "q":
        return
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(shop_maps):
            shop_editor_menu(game_path, shop_maps[idx], settings=settings,
                             proj_name=proj_name, project_dir=project_dir)
    except ValueError:
        pass


def _landing_build(game_path, project_dir, emotes_conf, source_display, settings):
    """Landing page [b] Build — delegate to _offer_build."""
    try:
        from torch.ui import _offer_build
        _offer_build(
            game_path=game_path,
            trigger="auto",
            safe=False,
            auto_build=False,
            project_dir=project_dir,
            emotes_conf=emotes_conf,
            source_display=source_display,
            max_snapshots=settings.get("max_snapshots", 10),
        )
    except ImportError:
        print("  Build is not available.")
        input("  Press Enter > ")


def _landing_sync(project_dir, game_path, emotes_conf, source_display, settings):
    """Landing page [s] Sync — delegate to sync_all."""
    try:
        from torch.sync import sync_all
        sync_all(project_dir, game_path, emotes_conf, source_display,
                 settings.get("max_snapshots", 10))
        input(f"\n  {DIM}Press Enter to return{RST} > ")
    except ImportError:
        print("  Sync is not available.")
        input("  Press Enter > ")


def _browse_sync_action(sel, project_dir, game_path, emotes_conf,
                        source_display, settings):
    """Studio [y] sync — sync highlighted map or all maps needing attention."""
    try:
        from torch.registry import get_map_health, get_enrolled_maps
    except ImportError:
        print("  Sync is not available.")
        input("  Press Enter > ")
        return

    max_snapshots = settings.get("max_snapshots", 10)

    # Gather all maps needing sync
    needs_sync = []
    for name in get_enrolled_maps(project_dir):
        h = get_map_health(project_dir, name, game_path)
        if h in ("stale", "drift", "never_written"):
            needs_sync.append(name)

    if not needs_sync:
        print(f"\n  {DIM}All maps are in sync.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    # If highlighted map needs sync, sync it. Offer to sync all if others too.
    sel_name = sel["name"] if sel else None
    sel_needs = sel_name in needs_sync

    if len(needs_sync) == 1 and sel_needs:
        # Only one map and it's the highlighted one — just sync it
        print(f"\n  {WHITE}Syncing {sel_name}...{RST}")
        ok = sync_map(sel_name, project_dir, game_path, emotes_conf,
                      source_display, max_snapshots, quiet=False)
        if ok:
            print(f"  {GREEN}Synced {sel_name}.{RST}")
        else:
            print(f"  {RED}Sync failed for {sel_name}.{RST}")
        input(f"\n  {DIM}Press Enter{RST} > ")
    elif len(needs_sync) > 1:
        # Multiple maps — offer choice
        print()
        if sel_needs:
            print(f"  {WHITE}{len(needs_sync)} map(s) need sync:{RST} {', '.join(needs_sync)}")
            print(f"  {_k('1')} Sync {sel_name} (highlighted)")
            print(f"  {_k('2')} Sync all {len(needs_sync)} maps")
            print(f"  {_k('q')} Cancel")
            try:
                pick = input(f"\n  {GOLD}>{RST} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return
            if pick == "1":
                targets = [sel_name]
            elif pick == "2":
                targets = needs_sync
            else:
                return
        else:
            print(f"  {WHITE}{len(needs_sync)} map(s) need sync:{RST} {', '.join(needs_sync)}")
            print(f"  {_k('y')} Sync all  {_k('q')} Cancel")
            try:
                pick = input(f"\n  {GOLD}>{RST} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return
            if pick not in ("y", ""):
                return
            targets = needs_sync

        for name in targets:
            print(f"  Syncing {name}...", end="", flush=True)
            ok = sync_map(name, project_dir, game_path, emotes_conf,
                          source_display, max_snapshots, quiet=True)
            if ok:
                print(f" {GREEN}ok{RST}")
            else:
                print(f" {RED}failed{RST}")
        input(f"\n  {DIM}Press Enter{RST} > ")
    else:
        # One map needs sync but it's not the highlighted one
        name = needs_sync[0]
        print(f"\n  {WHITE}Syncing {name}...{RST}")
        ok = sync_map(name, project_dir, game_path, emotes_conf,
                      source_display, max_snapshots, quiet=False)
        if ok:
            print(f"  {GREEN}Synced {name}.{RST}")
        else:
            print(f"  {RED}Sync failed for {name}.{RST}")
        input(f"\n  {DIM}Press Enter{RST} > ")


# -- Browse Maps mode ----------------------------------------------------------

def _browse_tool_action(tool, m, project_dir, game_path, emotes_conf,
                        source_display, settings, proj_name, workspace_expanded):
    """Execute a tool-key action on a map entry in Studio workspace mode."""
    # Auto-import prompt for CUSTOM maps (map-specific tools only)
    if tool in ("s", "e", "n", "t", "h", "m") and m["status"] == "CUSTOM":
        print()
        confirm = input(f"  {m['name']} isn't imported yet. Import now? [Y/n] ").strip().lower()
        if confirm in ("", "y", "yes"):
            _import_map(m["name"], project_dir, game_path,
                        emotes_conf, source_display, settings, proj_name)
        return  # return to refresh the map list

    if tool == "s":
        # Scripts -- open script browser for this map
        if m["status"] == "ACTIVE":
            _hub_open_active(m, project_dir, game_path, emotes_conf,
                             source_display, settings, proj_name)
        else:
            print(f"  {m['name']} ({m['status']}) -- cannot open scripts.")
            input("  Press Enter > ")
    elif tool == "t":
        # Trainers -- local, open battle_manager for this map
        _landing_trainers(project_dir, game_path, workspace_expanded, settings,
                          emotes_conf, source_display, proj_name)
    elif tool == "e":
        # Encounters -- open encounter editor with map pre-selected
        try:
            from torch.encounter_editor import encounter_command
            encounter_command([m["name"]], project_dir, game_path,
                              workspace_expanded, settings,
                              emotes_conf=emotes_conf,
                              source_display=source_display,
                              proj_name=proj_name)
        except ImportError:
            print("  Encounter Editor is not available.")
            input("  Press Enter > ")
    elif tool == "n":
        # NPC Editor -- open NPC script editor for this map
        try:
            from torch.npc_editor import npc_editor_menu
            npc_editor_menu(game_path, m["name"], settings=settings,
                            proj_name=proj_name, project_dir=project_dir,
                            emotes_conf=emotes_conf,
                            source_display=source_display)
        except ImportError:
            print("  NPC Editor is not available.")
            input("  Press Enter > ")
    elif tool == "h":
        # Heal locations for this map
        try:
            from torch.heal_locations import heal_command
            heal_command([], game_path, project_dir, settings, proj_name)
        except ImportError:
            print("  Heal Location Manager is not available.")
            input("  Press Enter > ")
    elif tool == "m":
        # Marts -- open shop editor for this map
        try:
            from torch.shop_editor import shop_editor_menu
            shop_editor_menu(game_path, m["name"], settings=settings,
                             proj_name=proj_name, project_dir=project_dir)
        except ImportError:
            print("  Shop Editor is not available.")
            input("  Press Enter > ")


def _browse_render(visible, map_groups, selected_idx, scroll_top, page_size,
                   show_vanilla, vanilla_count, custom_count, proj_name,
                   NK_UP, NK_DOWN, game_path=None, project_dir=None,
                   view_mode="all", all_maps=None, settings=None):
    """Render the Studio workspace screen."""

    clear_screen()
    _render_dashboard_header(proj_name, game_path, project_dir, view_mode,
                             visible, all_maps, settings,
                             show_vanilla=show_vanilla)

    if not visible:
        print("  (no maps found -- check game_path in config)")
        print()
    else:
        num_w = len(str(len(visible)))
        # Compute name column width from visible maps
        name_w = max((len(_abridge_name(v["name"])) for v in visible), default=20)
        name_w = max(name_w, 20)  # minimum 20

        # Table header
        _hub_render_table_header(num_w, name_w)

        for list_i in range(scroll_top, min(scroll_top + page_size, len(visible))):
            _hub_render_row(visible[list_i], list_i, selected_idx, num_w,
                            map_groups, game_path=game_path,
                            project_dir=project_dir, name_w=name_w)

        if scroll_top > 0:
            print(f"  {_C_VANILLA}  \u2191 {scroll_top} more above{_C_RESET}")
        remaining_below = len(visible) - (scroll_top + page_size)
        if remaining_below > 0:
            print(f"  {_C_VANILLA}  \u2193 {remaining_below} more below{_C_RESET}")

        # Detail panel for highlighted map
        if game_path and 0 <= selected_idx < len(visible):
            sel_map = visible[selected_idx]
            _hub_render_detail_panel(sel_map, game_path, map_groups,
                                     project_dir=project_dir)

        print()

    # Vanilla hint (only in ALL mode)
    if view_mode != "recent":
        if not show_vanilla and vanilla_count > 0:
            print(f"  {_C_VANILLA}{vanilla_count} vanilla map{'s' if vanilla_count != 1 else ''} hidden -- [z] to show{_C_RESET}")
        elif show_vanilla and vanilla_count > 0:
            print(f"  {_C_VANILLA}{vanilla_count} vanilla map{'s' if vanilla_count != 1 else ''} shown -- [z] to hide{_C_RESET}")
    print()

    # Command bar: 2 rows (local keys visible in dropdown, no Map row needed)
    global_parts = [
        f"{_k('gt')}{DIM} trainers{RST}",
        f"{_k('gh')}{DIM} heal locs{RST}",
        f"{_k('gm')}{DIM} marts{RST}",
        f"{_k('i')}{DIM}tems{RST}",
        f"{_k('gf')}{DIM} flags{RST}",
        f"{_k('x')}{DIM} explore{RST}",
    ]
    print(f"  {DIM}Global:{RST} {'  '.join(global_parts)}")

    go_parts = [
        f"{_k('/')}{DIM}search{RST}",
        f"{_k('y')}{DIM} sync{RST}",
        f"{_k('b')}{DIM} build{RST}",
        f"{_k('z')}{DIM} vanilla{RST}",
        f"{_k('?')}{DIM} help{RST}",
        f"{_k('q')}{DIM} back{RST}",
    ]
    print(f"  {DIM}Go:{RST}     {'  '.join(go_parts)}")
    print()


def _nav_dispatch(cmd, raw, state, ctx):
    """Handle common navigation keys (up/down/f/search/number). Shared by hub and browse."""
    visible = state["visible"]
    sel = state["sel"]
    if cmd == ctx["NK_UP"]:
        if visible:
            state["idx"] = max(0, state["idx"] - 1)
    elif cmd == ctx["NK_DOWN"]:
        if visible:
            state["idx"] = min(len(visible) - 1, state["idx"] + 1)
    elif cmd == "z":
        # Vanilla toggle only in ALL mode
        if state.get("view_mode", "all") == "recent":
            return  # no-op in RECENT mode
        state["show_van"], state["idx"], state["top"] = _hub_handle_toggle_vanilla(
            state["show_van"], sel, state["all_maps"])
    elif cmd == "/":
        result = _hub_handle_search(state["all_maps"], state["show_van"])
        if result is not None:
            state["idx"], state["top"] = result
    elif raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(visible):
            state["idx"] = idx


def _browse_parse_tool_key(raw, visible):
    """Parse a tool-key input (compound like s3 or single like s). Returns (tool, map_entry) or None."""
    if len(raw) >= 2 and raw[0] in "stenhm" and raw[1:].isdigit():
        idx = int(raw[1:]) - 1
        if 0 <= idx < len(visible):
            return raw[0], visible[idx]
        return raw[0], None  # out of range
    return None


def _browse_help():
    """Show Studio workspace help screen."""
    clear_screen()
    print(f"  {GOLD}Studio Workspace Help{RST}")
    print()
    print(f"  {WHITE}Map Tools{RST} {DIM}(act on highlighted map){RST}")
    print(f"    {_k('s')} Scripts       {DIM}Open script browser for this map{RST}")
    print(f"    {_k('e')} Encounters    {DIM}Edit wild Pokemon for this map{RST}")
    print(f"    {_k('n')} NPC           {DIM}Edit NPCs for this map{RST}")
    print(f"    {_k('t')} Trainers      {DIM}Edit trainers on this map{RST}")
    print(f"    {_k('h')} Heal          {DIM}Manage heal/respawn for this map{RST}")
    print(f"    {_k('m')} Marts         {DIM}Edit Pokemarts for this map{RST}")
    print(f"    {_k('f')} Flags         {DIM}Browse flags{RST}")
    print()
    print(f"  {WHITE}Global Tools{RST} {DIM}(g prefix){RST}")
    print(f"    {_k('gt')} Trainers     {DIM}Browse & edit all trainers{RST}")
    print(f"    {_k('gh')} Heal locs    {DIM}All heal locations{RST}")
    print(f"    {_k('gm')} Marts        {DIM}All shops{RST}")
    print(f"    {_k('gf')} Flags        {DIM}All game flags{RST}")
    print(f"    {_k('i')}  Items        {DIM}Browse & edit game items{RST}")
    print(f"    {_k('x')}  Explore      {DIM}Map connectivity & paths{RST}")
    print()
    print(f"  {WHITE}Navigation{RST}")
    print(f"    {_k('r')}  View toggle  {DIM}Switch RECENT / ALL view{RST}")
    print(f"    {_k('/')}  Search       {DIM}Filter maps by name{RST}")
    print(f"    {_k('z')}  Vanilla      {DIM}Show/hide vanilla maps{RST}")
    print(f"    {_k('A')}  Import all   {DIM}Import all unimported maps{RST}")
    print(f"    {_k('y')}  Sync         {DIM}Sync stale/drift maps to game{RST}")
    print(f"    {_k('b')}  Build        {DIM}Build ROM{RST}")
    print(f"    {_k('#')}  Refresh      {DIM}Clear caches, rescan{RST}")
    print(f"    {_k('q')}  Back         {DIM}Return to main menu{RST}")
    print()
    input(f"  {DIM}Press Enter to return{RST} > ")


def _browse_dispatch(raw, state, ctx):
    """Dispatch a single input in Studio workspace mode. Returns _QUIT to exit."""
    visible = state["visible"]
    sel = state["sel"]

    # Enter (empty) -> scroll down one row
    if raw == "":
        if visible:
            state["idx"] = (state["idx"] + 1) % len(visible)
        return

    raw = raw.strip()
    cmd = raw.lower()

    # Compound tool-key shortcuts: s3, e2, n1, m4, t2, h1
    parsed = _browse_parse_tool_key(raw, visible)
    if parsed is not None:
        tool, target = parsed
        if target is not None:
            _browse_tool_action(tool, target, ctx["project_dir"],
                                ctx["game_path"], ctx["emotes_conf"],
                                ctx["source_display"], ctx["settings"],
                                ctx["proj_name"], ctx["workspace_expanded"])
        return

    # G-prefix global keys: gt, gh, gm, gf
    if cmd in ("gt", "gh", "gm", "gf"):
        if cmd == "gt":
            _landing_trainers_flat(ctx["project_dir"], ctx["game_path"],
                                   ctx["workspace_expanded"], ctx["settings"],
                                   ctx["proj_name"])
        elif cmd == "gh":
            try:
                from torch.heal_locations import heal_command
                heal_command([], ctx["game_path"], ctx["project_dir"],
                             ctx["settings"], ctx["proj_name"])
            except ImportError:
                print("  Heal Location Manager is not available.")
                input("  Press Enter > ")
        elif cmd == "gm":
            try:
                from torch.shop_editor import shop_editor_menu
                shop_editor_menu(ctx["game_path"], None, settings=ctx["settings"],
                                 proj_name=ctx["proj_name"],
                                 project_dir=ctx["project_dir"])
            except ImportError:
                print("  Shop Editor is not available.")
                input("  Press Enter > ")
        elif cmd == "gf":
            try:
                from torch.flag_browser import flag_browser
                flag_browser(ctx["game_path"], ctx["settings"], ctx["proj_name"])
            except ImportError:
                print("  Flag Browser is not available.")
                input("  Press Enter > ")
        return

    # Local tool keys on highlighted map (per-map)
    if cmd in ("s", "e", "n", "t", "h", "m") and sel:
        _browse_tool_action(cmd, sel, ctx["project_dir"], ctx["game_path"],
                            ctx["emotes_conf"], ctx["source_display"],
                            ctx["settings"], ctx["proj_name"],
                            ctx["workspace_expanded"])
        return

    # Flags -- local (open flag browser)
    if cmd == "f" and sel:
        try:
            from torch.flag_browser import flag_browser
            flag_browser(ctx["game_path"], ctx["settings"], ctx["proj_name"])
        except ImportError:
            print("  Flag Browser is not available.")
            input("  Press Enter > ")
        return

    # Items -- global item browser
    if cmd == "i":
        try:
            from torch.item_editor import item_editor_menu
            item_editor_menu(ctx["game_path"], ctx["settings"], ctx["proj_name"])
        except ImportError:
            print("  Item Editor is not available.")
            input("  Press Enter > ")
        return

    # Explore -- map explorer
    if cmd == "x":
        try:
            from torch.map_explorer import map_explorer_menu
            map_explorer_menu(ctx["game_path"], ctx["settings"], ctx["proj_name"])
        except ImportError:
            print("  Map Explorer is not available.")
            input("  Press Enter > ")
        return

    # Sync
    if cmd == "y":
        _browse_sync_action(sel, ctx["project_dir"], ctx["game_path"],
                            ctx["emotes_conf"], ctx["source_display"],
                            ctx["settings"])
        return

    # Build
    if cmd == "b":
        _landing_build(ctx["game_path"], ctx["project_dir"],
                       ctx["emotes_conf"], ctx["source_display"],
                       ctx["settings"])
        return

    # Help
    if cmd == "?":
        _browse_help()
        return

    # View toggle (RECENT <-> ALL)
    if cmd == "r":
        if state["view_mode"] == "recent":
            state["view_mode"] = "all"
        else:
            state["view_mode"] = "recent"
        state["idx"] = 0
        state["top"] = 0
        # Save sticky preference in settings dict
        ctx["settings"]["maps_view"] = state["view_mode"]
        return

    # Import all (hidden power-user key)
    if raw == "A":
        _hub_handle_import_all(state["all_maps"], ctx["project_dir"],
                               ctx["game_path"], ctx["emotes_conf"],
                               ctx["source_display"], ctx["settings"],
                               ctx["proj_name"])
        return

    # Refresh caches
    if raw == "#":
        _refresh_all_caches()
        return

    if cmd == "q":
        return _QUIT

    _nav_dispatch(cmd, raw, state, ctx)


def _browse_maps(project_dir, game_path, emotes_conf, source_display,
                 settings, proj_name, workspace_expanded=""):
    """Studio workspace -- map list with tool-key navigation and project dashboard."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if proj_name is None:
        proj_name = os.path.basename(project_dir) or None
    _set_terminal_title("TORCH -- Studio")

    page_size = settings.get("map_list_page_size", SETTINGS_DEFAULTS["map_list_page_size"])
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)

    # Load sticky view preference
    view_mode = settings.get("maps_view", "recent")

    ctx = {
        "project_dir": project_dir, "game_path": game_path,
        "emotes_conf": emotes_conf, "source_display": source_display,
        "settings": settings, "proj_name": proj_name,
        "NK_UP": NK_UP, "NK_DOWN": NK_DOWN,
        "workspace_expanded": workspace_expanded,
    }
    state = {"idx": 0, "top": 0, "show_van": False,
             "visible": [], "all_maps": [], "sel": None,
             "view_mode": view_mode}

    while True:
        state["all_maps"] = _scan_game_maps(game_path, project_dir)
        vanilla_count = sum(1 for m in state["all_maps"] if m["status"] == "VANILLA")
        custom_count  = sum(1 for m in state["all_maps"] if m["status"] == "CUSTOM")

        if state["view_mode"] == "recent":
            # RECENT: show only maps the user has worked on, sorted by mtime, limit 10
            worked = [m for m in state["all_maps"]
                      if m["status"] in ("ACTIVE", "ORPHAN") and m.get("mtime", 0) > 0]
            worked.sort(key=lambda m: -m["mtime"])
            state["visible"] = worked[:10]
        else:
            # ALL: existing behavior
            state["visible"] = _hub_sorted_maps(state["all_maps"], state["show_van"])

        map_groups = _hub_gather_map_groups(project_dir)

        _hub_guard_bounds(state, page_size)
        state["sel"] = state["visible"][state["idx"]] if state["visible"] else None

        _browse_render(state["visible"], map_groups, state["idx"], state["top"],
                       page_size, state["show_van"], vanilla_count, custom_count,
                       proj_name, NK_UP, NK_DOWN, game_path,
                       project_dir=project_dir,
                       view_mode=state["view_mode"],
                       all_maps=state["all_maps"],
                       settings=settings)

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return
        raw = raw.rstrip("\n")

        if _browse_dispatch(raw, state, ctx) is _QUIT:
            return


# -- Legacy landing page -- kept for rollback, not called. ---------------------

def _landing_page(project_dir, game_path, emotes_conf, source_display,
                  settings, proj_name, workspace_expanded=""):
    """Legacy landing page -- kept for rollback, not called."""
    while True:
        clear_screen()
        print_logo("Map Studio", proj_name)
        print(BAR)
        print()
        print(f"  {_k('1')} {WHITE}Scripts{RST}          {DIM}Write & edit TorScript scripts{RST}")
        print(f"  {_k('2')} {WHITE}Trainers{RST}         {DIM}Manage trainer battles{RST}")
        print(f"  {_k('3')} {WHITE}Encounters{RST}       {DIM}Edit wild Pokemon tables{RST}")
        print(f"  {_k('4')} {WHITE}Heal Locations{RST}   {DIM}Manage respawn points{RST}")
        print(f"  {_k('5')} {WHITE}Browse Maps{RST}      {DIM}View all maps with tools{RST}")
        print(f"  {_k('6')} {WHITE}Shops{RST}            {DIM}View & edit Pokemart items{RST}")
        print(f"  {_k('7')} {WHITE}Flags{RST}            {DIM}Browse & manage game flags{RST}")
        print()
        print(f"  {_k('b')} {DIM}Build{RST}    {_k('r')} {DIM}Refresh{RST}    {_k('q')} {DIM}Back{RST}")
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if raw == "q":
            return
        elif raw == "1":
            _scripts_map_list(project_dir, game_path, emotes_conf,
                              source_display, settings, proj_name)
        elif raw == "2":
            _landing_trainers(project_dir, game_path, workspace_expanded,
                              settings, emotes_conf, source_display, proj_name)
        elif raw == "3":
            _landing_encounters(project_dir, game_path, workspace_expanded,
                                settings, emotes_conf, source_display, proj_name)
        elif raw == "4":
            _landing_heal(project_dir, game_path, settings, proj_name)
        elif raw == "5":
            _browse_maps(project_dir, game_path, emotes_conf, source_display,
                         settings, proj_name, workspace_expanded)
        elif raw == "6":
            _landing_shops(game_path, settings, proj_name, project_dir)
        elif raw == "7":
            try:
                from torch.flag_browser import flag_browser
            except ImportError:
                print(f"  {DIM}Flag browser not available.{RST}")
                input("  [Enter] ")
                continue
            flag_browser(game_path, settings, proj_name)
        elif raw == "b":
            _landing_build(game_path, project_dir, emotes_conf,
                           source_display, settings)
        elif raw == "r":
            _refresh_all_caches()


def script_builder_menu(project_dir, game_path, emotes_conf, source_display,
                       settings=None, proj_name=None, workspace_expanded=""):
    """Studio hub -- entry point from main menu. Opens the workspace directly."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if proj_name is None:
        proj_name = os.path.basename(project_dir) or None
    _refresh_all_caches()
    _set_terminal_title("TORCH -- Studio")
    _browse_maps(project_dir, game_path, emotes_conf, source_display,
                 settings, proj_name, workspace_expanded)


# -- Import from game scripts --------------------------------------------------

def _import_pory_scripts(map_name, project_dir, game_path):
    """Import scripts.pory from game files into workspace as TorScript.

    Returns True if a file was imported.
    """
    try:
        from torch.decompiler import decompile
    except ImportError:
        print(f"\n  {DIM}Decompiler not available.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    pory_path = os.path.join(game_path, "data", "maps", map_name, "scripts.pory")
    if not os.path.isfile(pory_path):
        print(f"\n  {DIM}No game scripts found for this map.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Check for collision
    workspace_dir = os.path.join(project_dir, map_name)
    dest_path = os.path.join(workspace_dir, "scripts.txt")
    if os.path.exists(dest_path):
        print(f"\n  {DIM}scripts.txt already exists in workspace.{RST}")
        print(f"  {DIM}Delete or rename it first to re-import.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    try:
        with open(pory_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        print(f"\n  {DIM}Could not read {pory_path}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    torscript, warnings = decompile(content, map_name)
    if not torscript or not torscript.strip():
        print(f"\n  {DIM}Decompiler produced no output for this file.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Count script labels in output
    script_count = len(re.findall(r'^script\s+', torscript, re.MULTILINE))
    label_count = len(re.findall(r'^label\s+', torscript, re.MULTILINE))
    total = script_count + label_count

    if warnings:
        print(f"\n  {GOLD}Decompiler warnings:{RST}")
        for w in warnings:
            print(f"    {DIM}- {w}{RST}")

    try:
        confirm = input(f"\n  Import {WHITE}{total} script(s){RST} from scripts.pory? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if confirm not in ("", "y", "yes"):
        return False

    os.makedirs(workspace_dir, exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(torscript)

    _ensure_setup_pory(workspace_dir, map_name)

    print(f"\n  {GREEN}Imported:{RST} scripts.txt ({total} script(s))")
    input(f"  {DIM}Press Enter{RST} > ")
    return True


# -- Script map browser (level 2) ----------------------------------------------

def _browser_rescan(project_dir, map_name):
    """Rescan a map directory for script files."""
    new_scripts = []
    map_dir = os.path.join(project_dir, map_name)
    if os.path.isdir(map_dir):
        for fname in sorted(os.listdir(map_dir)):
            if fname.endswith(".txt"):
                sname = os.path.splitext(fname)[0]
                fpath = os.path.join(map_dir, fname)
                mtime = os.path.getmtime(fpath)
                new_scripts.append((sname, fpath, mtime))
        new_scripts.sort(key=lambda x: x[2], reverse=True)
    return new_scripts


def _browser_render(map_name, scripts, selected_idx, proj_name, NK_UP, NK_DOWN):
    """Render the script map browser screen."""

    clear_screen()
    print_logo("Studio", proj_name)
    print(BAR)
    print(f"   {DIM}SCRIPTS  \u2014{RST}  {WHITE}{map_name}{RST}")
    print(BAR)
    print()

    if not scripts:
        print(f"  {DIM}No scripts yet \u2014 [n] to create one.{RST}")
    else:
        num_w = len(str(len(scripts)))
        for i, (sname, fpath, _mt) in enumerate(scripts):
            cursor = f"{GOLD}>>{RST}" if i == selected_idx else "  "
            num = f"{i + 1}."
            beat_count, desc = _script_info(fpath)
            info = f"{beat_count} beats"
            if desc:
                info += f" \u2014 {desc}"
            name_col = WHITE if i == selected_idx else ""
            print(f"  {cursor} {DIM}{num:<{num_w + 1}}{RST} {name_col}{sname:<22}{RST if name_col else ''}  {DIM}{info}{RST}")

    print()
    print(f"  {_k('#')}/{_k('v')} {DIM}open{RST}  {_k('Enter')} {DIM}scroll{RST}  "
          f"{_k(NK_UP)} {DIM}up{RST}  {_k(NK_DOWN)} {DIM}down{RST}  "
          f"{_k('n')}{DIM}ew{RST}  {_k('d')}{DIM}elete{RST}  {_k('i')}{DIM}mport{RST}  {_k('q')} {DIM}back{RST}")
    print()


def _script_map_browser(map_name, scripts, project_dir, game_path, emotes_conf, source_display, settings, proj_name=None):
    """Level 2 — browse all scripts in a single map folder."""
    selected_idx = 0
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)

    while True:
        if not scripts:
            selected_idx = 0
        else:
            selected_idx = max(0, min(selected_idx, len(scripts) - 1))

        _browser_render(map_name, scripts, selected_idx, proj_name, NK_UP, NK_DOWN)

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return
        raw = raw.rstrip("\n")

        if raw == "":
            if scripts:
                selected_idx = (selected_idx + 1) % len(scripts)
            continue

        raw = raw.strip()
        cmd = raw.lower()

        if cmd in ("q", "b", ""):
            return

        elif cmd == NK_UP:
            if scripts:
                selected_idx = max(0, selected_idx - 1)

        elif cmd == NK_DOWN:
            if scripts:
                selected_idx = min(len(scripts) - 1, selected_idx + 1)

        elif cmd == "v":
            if scripts:
                sname, fpath, _ = scripts[selected_idx]
                script_data = _parse_script(fpath, emotes_conf)
                _script_editor_loop(script_data, map_name, fpath,
                                    project_dir, game_path, emotes_conf, source_display,
                                    settings, proj_name)

        elif cmd == "n":
            _new_script_wizard(project_dir, game_path, emotes_conf, source_display,
                              settings, proj_name, map_name=map_name)
            scripts = _browser_rescan(project_dir, map_name)
            selected_idx = max(0, len(scripts) - 1)

        elif cmd == "d":
            if scripts:
                sname, fpath, _ = scripts[selected_idx]
                deleted = _delete_script(sname, fpath, map_name, project_dir,
                                        game_path, emotes_conf, source_display,
                                        settings, proj_name)
                if deleted:
                    scripts = _browser_rescan(project_dir, map_name)

        elif cmd == "i":
            imported = _import_pory_scripts(map_name, project_dir, game_path)
            if imported:
                scripts = _browser_rescan(project_dir, map_name)
                selected_idx = max(0, len(scripts) - 1)

        elif raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(scripts):
                selected_idx = idx
            else:
                print(f"  No script #{raw}.")
                input("  Press Enter > ")

        else:
            print(f"  Unknown command '{raw}'.")
            input("  Press Enter > ")


# -- Script deletion ------------------------------------------------------------

def _extract_script_flags(script_data):
    """Extract all flag names referenced in a script's beats."""
    flags = set()
    for beat in script_data.get("beats", []):
        data = beat.get("data", {})
        # Direct flag beats
        if beat["type"] == "flag" and data.get("flag_name"):
            flags.add(data["flag_name"])
        # Gotoif beats
        if beat["type"] == "gotoif" and data.get("flag"):
            flags.add(data["flag"])
        # Pory beats that reference flags
        if beat["type"] == "pory":
            raw = data.get("raw_line", "")
            for m in re.finditer(r'\b(FLAG_[A-Z0-9_]+)\b', raw):
                flags.add(m.group(1))
    return flags


def _delete_script(script_name, filepath, map_name, project_dir, game_path,
                  emotes_conf, source_display, settings, proj_name=None):
    """Delete a script and clean up all references.

    Returns True if the script was deleted, False if cancelled.
    """
    from torch.script_model import _parse_setup_movement_blocks, _find_movement_references

    print()
    print(f"  {RED}Delete script:{RST} {WHITE}{script_name}{RST}")

    # Parse the script to extract labels
    if not os.path.exists(filepath):
        print(f"  {DIM}File already deleted from disk.{RST}")
        input("  [Enter] ")
        return True  # nothing to do

    script_data = _parse_script(filepath)
    script_labels = script_data.get("labels", [])
    if not script_labels and script_data.get("label"):
        script_labels = [script_data["label"]]

    # Preview what will be cleaned up
    map_dir = os.path.join(project_dir, map_name)
    setup_path = os.path.join(map_dir, "setup.pory")
    game_map_dir = os.path.join(game_path, "data", "maps", map_name)
    map_json_path = os.path.join(game_map_dir, "map.json")

    # Check for references before confirming
    setup_refs = _scan_setup_for_labels(setup_path, script_labels)
    event_refs = _scan_map_json_for_labels(map_json_path, script_labels)
    script_refs = _scan_scripts_for_labels(map_dir, filepath, script_labels)
    orphaned_movements = _scan_orphaned_movements(setup_path, map_dir, filepath, script_labels)
    orphaned_battle_pory = _scan_orphaned_battle_pory(map_dir, filepath, script_data)

    # -- Show action plan --
    print()
    print(f"  {WHITE}TORCH will:{RST}")
    step = 1
    print(f"    {DIM}{step}. Create a safety snapshot (restorable via torch restore {map_name}){RST}")
    step += 1
    print(f"    {DIM}{step}. Delete {script_name}.txt from your workspace{RST}")
    if orphaned_battle_pory:
        step += 1
        print(f"    {DIM}{step}. Delete {len(orphaned_battle_pory)} companion battle"
              f" file{'s' if len(orphaned_battle_pory) != 1 else ''}{RST}")
        for bp in orphaned_battle_pory:
            print(f"       {DIM}{bp}{RST}")
    if event_refs:
        step += 1
        ev_count = len(event_refs)
        print(f"    {DIM}{step}. Clear {ev_count} NPC/event script{'s' if ev_count != 1 else ''}"
              f" in Porymap's map.json that point{'s' if ev_count == 1 else ''} to this script{RST}")
        for ref in event_refs:
            ev_desc = _humanize_event_ref(ref)
            print(f"       {DIM}{ev_desc}{RST}")
    if setup_refs:
        step += 1
        print(f"    {DIM}{step}. Remove mapscript trigger{'s' if len(setup_refs) != 1 else ''}"
              f" from setup.pory{RST}")
        for ref in setup_refs:
            print(f"       {DIM}{ref}{RST}")
    step += 1
    print(f"    {DIM}{step}. Re-sync {map_name} so the compiled scripts.pory is updated{RST}")

    if orphaned_movements:
        print()
        print(f"  {DGOLD}Note:{RST} {DIM}These movement blocks in setup.pory will no longer be used:{RST}")
        for label in orphaned_movements:
            print(f"    {DIM}{label}{RST}")
        print(f"  {DIM}You'll be offered the option to remove them.{RST}")

    # Cross-script references require patching or block deletion
    patch_scripts = False
    if script_refs:
        print()
        print(f"  {RED}Problem:{RST} {WHITE}Other scripts jump into this one:{RST}")
        for ref in script_refs:
            print(f"    {CYAN}{ref}{RST}")
        print()
        print(f"  {DIM}TORCH can patch those files by replacing the goto/call{RST}")
        print(f"  {DIM}with a clean script ending (release + end).{RST}")
        print()
        try:
            patch = input(f"  Patch and delete? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if patch not in ("y", "yes"):
            print()
            print(f"  {DIM}Delete blocked. Remove the goto/call references first,{RST}")
            print(f"  {DIM}or delete the referencing scripts before this one.{RST}")
            input("  [Enter] ")
            return False
        patch_scripts = True
    else:
        print()
        try:
            confirm = input(f"  Delete {script_name}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if confirm not in ("y", "yes"):
            print(f"  {DIM}Cancelled.{RST}")
            input("  [Enter] ")
            return False

    # -- Safety snapshot before deleting --
    snapshot_dir = os.path.join(map_dir, "backups", "snapshots")
    snap = create_snapshot(os.path.join(project_dir, map_name), snapshot_dir, map_name)
    if snap:
        print(f"  {DIM}Snapshot created.{RST}")
    else:
        print(f"  {RED}WARNING:{RST} Snapshot failed -- no safety backup.")
        try:
            abort = input("  Continue anyway? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if abort not in ("y", "yes"):
            return False

    # -- 0. Patch cross-script references --
    if patch_scripts:
        patched = _patch_script_references(map_dir, filepath, script_labels)
        for pname, count in patched:
            print(f"  {GREEN}Patched{RST} {pname}: {count} reference{'s' if count != 1 else ''} replaced with release+end.")

    # -- 1. Clean setup.pory mapscript entries --
    if setup_refs and os.path.exists(setup_path):
        _remove_labels_from_setup(setup_path, script_labels)
        print(f"  {GREEN}Cleaned{RST} setup.pory mapscript entries.")

    # -- 2. Clean map.json event references --
    if event_refs and os.path.exists(map_json_path):
        cleared = _clear_map_json_references(map_json_path, script_labels)
        if cleared:
            print(f"  {GREEN}Cleared{RST} {cleared} event reference{'s' if cleared != 1 else ''} in map.json.")

    # -- 3. Clean flags.json --
    if proj_name:
        flag_log = _load_flag_log(proj_name)
        removed_flags = [k for k, v in flag_log.items() if v == script_name]
        if removed_flags:
            for k in removed_flags:
                del flag_log[k]
            _save_flag_log(proj_name, flag_log)
            print(f"  {GREEN}Cleaned{RST} {len(removed_flags)} flag log entr{'ies' if len(removed_flags) != 1 else 'y'}.")

    # -- 3b. Offer flag reclamation for custom flags with no surviving references --
    try:
        from torch.flag_scanner import scan_flag_references, delete_flag_from_header, parse_flags_h
        script_flags = _extract_script_flags(script_data)
        if script_flags:
            parsed = parse_flags_h(game_path)
            alias_names = {alias for alias, _ in parsed["custom_aliases"]}
            # Exclude refs from: (1) this map's compiled scripts.pory (will
            # be recompiled or deleted at step 6, so refs there are stale),
            # and (2) the header itself (filtered below by category).
            map_scripts_rel = os.path.join("data", "maps", map_name, "scripts.pory")
            for flag_name in sorted(script_flags):
                if flag_name not in alias_names:
                    continue  # not a custom alias -- skip
                refs = scan_flag_references(flag_name, game_path)
                # Filter out refs from the compiled output that's about to change
                surviving = [r for r in refs
                             if r["file"] != map_scripts_rel]
                # Also filter out the header define itself
                surviving_non_header = [r for r in surviving
                                        if r["category"] not in ("header_define", "header_alias")]
                if not surviving_non_header:
                    try:
                        reclaim = input(
                            f"  Flag {GOLD}{flag_name}{RST} has no other references. "
                            f"Reclaim slot? [y/N] ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        continue
                    if reclaim in ("y", "yes"):
                        if delete_flag_from_header(game_path, flag_name):
                            print(f"  {GREEN}Reclaimed{RST} {flag_name}")
                        else:
                            print(f"  {DIM}Could not reclaim {flag_name}.{RST}")
    except ImportError:
        pass  # flag_scanner not available

    # -- 4. Offer to remove orphaned movement blocks --
    if orphaned_movements and os.path.exists(setup_path):
        for mv_label in orphaned_movements:
            try:
                reclaim = input(
                    f"  Movement {GOLD}{mv_label}{RST} has no other references. "
                    f"Remove from setup.pory? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                continue
            if reclaim in ("y", "yes"):
                if _remove_movement_from_setup(setup_path, mv_label):
                    print(f"  {GREEN}Removed{RST} {mv_label}")
                else:
                    print(f"  {DIM}Could not remove {mv_label}.{RST}")

    # -- 5. Delete the .txt file and companion battle files --
    os.remove(filepath)
    print(f"  {GREEN}Deleted{RST} {script_name}.txt")
    for bp in orphaned_battle_pory:
        bp_path = os.path.join(map_dir, bp)
        if os.path.exists(bp_path):
            os.remove(bp_path)
            print(f"  {GREEN}Deleted{RST} {bp}")

    # -- 6. Auto-sync --
    print()
    remaining = [f for f in os.listdir(map_dir)
                 if f.endswith(".txt") or f.endswith(".pory")]
    if remaining:
        print(f"  {DIM}Syncing {map_name}...{RST}")
        sync_map(map_name, project_dir, game_path, emotes_conf, source_display)
        print()
        # Offer build (never auto — user may be deleting multiple scripts)
        from torch.ui import _offer_build
        _offer_build(game_path=game_path, project_dir=project_dir,
                     emotes_conf=emotes_conf, source_display=source_display)
    else:
        # No sources left -- remove stale scripts.pory from game folder
        stale_pory = os.path.join(game_path, "data", "maps", map_name, "scripts.pory")
        if os.path.exists(stale_pory):
            os.remove(stale_pory)
            print(f"  {DIM}No scripts remaining -- removed scripts.pory from game folder.{RST}")
        else:
            print(f"  {DIM}No scripts remaining.{RST}")

    print()
    input("  [Enter] ")
    return True


def _humanize_event_ref(ref):
    """Turn 'object_events[3].script = Label' into readable text."""
    m = re.match(r'(\w+)\[(\d+)\]\.script = (\w+)', ref)
    if not m:
        return ref
    event_type, idx, label = m.group(1), m.group(2), m.group(3)
    names = {
        "object_events": "Object (NPC)",
        "coord_events": "Coord (walk-on trigger)",
        "bg_events": "BG (sign/hidden item)",
    }
    friendly = names.get(event_type, event_type)
    return f"{friendly} #{idx} -> {label}"


def _scan_setup_for_labels(setup_path, labels):
    """Scan setup.pory for mapscript table entries referencing any of the given labels."""
    if not os.path.exists(setup_path):
        return []
    with open(setup_path, "r") as f:
        content = f.read()
    refs = []
    for label in labels:
        # Match inside any MAP_SCRIPT_ON_*_TABLE block
        for m in re.finditer(r'(MAP_SCRIPT_ON_\w+_TABLE)\s*\[', content):
            table_name = m.group(1)
            # Find the matching ]
            start = m.end()
            bracket_end = content.find(']', start)
            if bracket_end == -1:
                continue
            block = content[start:bracket_end]
            if re.search(r'\b' + re.escape(label) + r'\b', block):
                refs.append(f"{table_name} -> {label}")
    return refs


def _remove_labels_from_setup(setup_path, labels):
    """Remove mapscript table entries that reference any of the given labels from setup.pory."""
    with open(setup_path, "r") as f:
        lines = f.readlines()

    label_pattern = '|'.join(re.escape(l) for l in labels)

    # Remove lines inside MAP_SCRIPT table blocks that reference the labels.
    # Table entries look like:
    #     MAP_SCRIPT_ON_FRAME_TABLE [
    #         VAR_TEMP_1, 0, SceneLabel
    #     ]
    # or:
    #     MAP_SCRIPT_ON_RESUME_TABLE [
    #         SceneLabel
    #     ]
    # Strategy: find table blocks and remove matching entry lines.
    # If a table block becomes empty after removal, remove the whole block.
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Detect start of a MAP_SCRIPT table block
        if re.match(r'MAP_SCRIPT_ON_\w+_TABLE\s*\[', stripped):
            # Collect the full block
            block_lines = [line]
            i += 1
            while i < len(lines):
                block_lines.append(lines[i])
                if lines[i].strip() == "]":
                    i += 1
                    break
                i += 1
            # Filter out entry lines that reference our labels
            # Entry lines are those between [ and ] that aren't the header or closer
            header = block_lines[0]
            closer = block_lines[-1] if block_lines[-1].strip() == "]" else None
            inner = block_lines[1:-1] if closer else block_lines[1:]
            kept_inner = [l for l in inner
                          if not re.search(r'\b(' + label_pattern + r')\b', l)]
            # If all inner entries removed, drop the whole block
            if not any(l.strip() for l in kept_inner):
                continue  # skip entire block
            result.append(header)
            result.extend(kept_inner)
            if closer:
                result.append(closer)
        else:
            result.append(line)
            i += 1

    with open(setup_path, "w") as f:
        f.writelines(result)


def _scan_scripts_for_labels(map_dir, deleted_filepath, labels):
    """Scan other .txt and .pory files in the map for references to any of the given labels."""
    if not os.path.isdir(map_dir):
        return []
    refs = []
    deleted_basename = os.path.basename(deleted_filepath)
    label_alts = '|'.join(re.escape(l) for l in labels)
    # TorScript: goto Label, call Label, gotoif FLAG Label
    torscript_re = re.compile(
        r'\b(?:goto|call)\s+(' + label_alts + r')\b'
        r'|\bgotoif\s+\S+\s+(' + label_alts + r')\b'
    )
    # Poryscript: goto(Label), call(Label)
    poryscript_re = re.compile(
        r'\b(?:goto|call)\((' + label_alts + r')\)'
    )
    for fname in sorted(os.listdir(map_dir)):
        if fname == deleted_basename:
            continue
        is_txt = fname.endswith(".txt")
        is_pory = fname.endswith(".pory") and fname != "setup.pory"
        if not is_txt and not is_pory:
            continue
        fpath = os.path.join(map_dir, fname)
        script_name = os.path.splitext(fname)[0]
        pattern = torscript_re if is_txt else poryscript_re
        try:
            with open(fpath, "r") as f:
                for line_num, line in enumerate(f, 1):
                    if pattern.search(line):
                        refs.append(f"{script_name} line {line_num}: {line.strip()}")
        except OSError:
            continue
    return refs


def _patch_script_references(map_dir, deleted_filepath, labels):
    """Replace goto/call/gotoif lines referencing deleted labels with release+end.

    Handles both .txt (TorScript) and .pory (Poryscript) files.
    Returns list of (script_name, patch_count) for each patched file.
    """
    patched = []
    deleted_basename = os.path.basename(deleted_filepath)
    label_alts = '|'.join(re.escape(l) for l in labels)
    # TorScript: goto Label, call Label, gotoif FLAG Label
    ts_re = re.compile(
        r'^(?:goto|call)\s+(' + label_alts + r')\b'
        r'|^gotoif\s+\S+\s+(' + label_alts + r')\b'
    )
    # Poryscript: goto(Label), call(Label)
    ps_re = re.compile(
        r'(?:goto|call)\((' + label_alts + r')\)'
    )
    for fname in sorted(os.listdir(map_dir)):
        if fname == deleted_basename:
            continue
        is_txt = fname.endswith(".txt")
        is_pory = fname.endswith(".pory") and fname != "setup.pory"
        if not is_txt and not is_pory:
            continue
        fpath = os.path.join(map_dir, fname)
        try:
            with open(fpath, "r") as f:
                lines = f.readlines()
        except OSError:
            continue
        new_lines = []
        count = 0
        for line in lines:
            stripped = line.strip()
            if is_txt and ts_re.match(stripped):
                new_lines.append(f"# [removed: {stripped}]\n")
                new_lines.append("pory release\n")
                new_lines.append("pory end\n")
                count += 1
            elif is_pory and ps_re.search(stripped):
                new_lines.append(f"// [removed: {stripped}]\n")
                new_lines.append("    release;\n")
                new_lines.append("    end;\n")
                count += 1
            else:
                new_lines.append(line)
        if count:
            with open(fpath, "w") as f:
                f.writelines(new_lines)
            patched.append((os.path.splitext(fname)[0], count))
    return patched


def _scan_map_json_for_labels(map_json_path, labels):
    """Scan map.json for event script fields matching any of the given labels."""
    if not os.path.exists(map_json_path):
        return []
    try:
        with open(map_json_path, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    refs = []
    label_set = set(labels)
    for event_type in ("object_events", "coord_events", "bg_events"):
        for i, ev in enumerate(data.get(event_type, [])):
            script = ev.get("script", "")
            if script in label_set:
                refs.append(f"{event_type}[{i}].script = {script}")
    return refs


def _clear_map_json_references(map_json_path, labels):
    """Clean up event references to deleted script labels in map.json.

    - object_events: script field set to "" (NPC persists, may serve other purposes)
    - coord_events / bg_events: entries removed entirely (empty-script triggers are
      useless noise -- they do nothing at runtime and clutter Porymap)

    Returns the number of references cleared/removed.
    """
    try:
        with open(map_json_path, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0
    label_set = set(labels)
    cleared = 0

    # Object events: clear script but keep the NPC entry
    for ev in data.get("object_events", []):
        if ev.get("script", "") in label_set:
            ev["script"] = "Common_EventScript_NopReturn"
            cleared += 1

    # Coord and BG events: remove entirely (empty-script entries are dead weight)
    for event_type in ("coord_events", "bg_events"):
        original = data.get(event_type, [])
        filtered = [ev for ev in original if ev.get("script", "") not in label_set]
        removed = len(original) - len(filtered)
        if removed:
            data[event_type] = filtered
            cleared += removed
    if cleared:
        with open(map_json_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        from torch.project_files import clear_project_cache
        clear_project_cache()
        _metadata_cache.clear()
    return cleared


def _scan_orphaned_battle_pory(map_dir, deleted_filepath, script_data):
    """Find companion battle_TRAINER_*.pory files that would be orphaned by deleting a script.

    A companion file is orphaned if no OTHER script in the map references the same trainer.
    """
    # Extract trainer IDs from the script's trainerbattle commands
    trainer_ids = set()
    for beat in script_data.get("beats", []):
        if beat.get("type") == "pory":
            line = beat.get("data", {}).get("raw", "")
        elif beat.get("type") == "trainerbattle":
            line = beat.get("data", {}).get("raw", "")
        else:
            continue
        for m in re.finditer(r'trainerbattle_\w+\(\s*(\w+)', line):
            trainer_ids.add(m.group(1))

    # Also scan the raw file for trainerbattle commands (TorScript form)
    try:
        with open(deleted_filepath, "r") as f:
            for line in f:
                m = re.match(r'\s*trainerbattle_\w+\s+(\w+)', line)
                if m:
                    trainer_ids.add(m.group(1))
    except OSError:
        pass

    if not trainer_ids:
        return []

    # Check which companion files exist and are orphaned
    orphaned = []
    deleted_basename = os.path.basename(deleted_filepath)
    for trainer_id in sorted(trainer_ids):
        companion = f"battle_{trainer_id}.pory"
        if not os.path.exists(os.path.join(map_dir, companion)):
            continue
        # Check if any OTHER script also references this trainer
        used_elsewhere = False
        for fname in os.listdir(map_dir):
            if fname == deleted_basename or fname == companion:
                continue
            if not fname.endswith(".txt") and not fname.endswith(".pory"):
                continue
            fpath = os.path.join(map_dir, fname)
            try:
                with open(fpath, "r") as f:
                    content = f.read()
                if re.search(r'\b' + re.escape(trainer_id) + r'\b', content):
                    used_elsewhere = True
                    break
            except OSError:
                continue
        if not used_elsewhere:
            orphaned.append(companion)
    return orphaned


def _scan_orphaned_movements(setup_path, map_dir, deleted_filepath, script_labels):
    """Find movement blocks in setup.pory that would be orphaned by deleting a script.

    A movement block is orphaned if:
    - It's only referenced by the script being deleted (no other .txt files use it)
    - Its label starts with the map name prefix (convention for script-generated movements)
    """
    from torch.script_model import _parse_setup_movement_blocks, _find_movement_references
    if not os.path.exists(setup_path):
        return []
    blocks = _parse_setup_movement_blocks(setup_path)
    if not blocks:
        return []

    orphaned = []
    deleted_basename = os.path.basename(deleted_filepath)
    for block in blocks:
        refs = _find_movement_references(block["label"], map_dir)
        # Filter: only count references from files OTHER than the one being deleted
        other_refs = [r for r in refs if r[0] != deleted_basename]
        if not other_refs and refs:
            # Was referenced only by the deleted script
            orphaned.append(block["label"])
    return orphaned


def _remove_movement_from_setup(setup_path, label):
    """Remove a named movement block from setup.pory. Returns True on success."""
    from torch.script_model import _parse_setup_movement_blocks
    if not os.path.exists(setup_path):
        return False

    blocks = _parse_setup_movement_blocks(setup_path)
    target = None
    for b in blocks:
        if b["label"] == label:
            target = b
            break
    if target is None:
        return False

    try:
        with open(setup_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False

    start = target["start_line"]
    end = target["end_line"]

    # Remove the block lines (start through end inclusive)
    del lines[start:end + 1]

    # Clean up: if removal left consecutive blank lines, collapse to one
    cleaned = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank

    # Strip trailing blank lines (keep one trailing newline)
    while len(cleaned) > 1 and cleaned[-1].strip() == "":
        cleaned.pop()
    if cleaned and not cleaned[-1].endswith("\n"):
        cleaned[-1] += "\n"

    try:
        with open(setup_path, "w", encoding="utf-8") as f:
            f.writelines(cleaned)
    except OSError:
        return False

    return True


# -- Porymap instructions box --------------------------------------------------

def _print_porymap_instructions(instructions):
    """Print boxed Porymap instructions for the user."""
    print()
    print(f"  {DIM}\u2504\u2504\u2504 Porymap Instructions \u2504\u2504\u2504{RST}")
    for line in instructions:
        print(f"  {CYAN}{line}{RST}")
    print(f"  {DIM}\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504\u2504{RST}")
    print()


# -- Trigger scaffolding -------------------------------------------------------

def _auto_wire_npc_script(game_path, map_name, object_id, script_label):
    """Write the script label into an NPC's script field in map.json.

    Finds the NPC by matching object_id against local_id in object_events.
    Returns True on success, False on failure.
    """
    map_json_path = os.path.join(
        game_path, "data", "maps", map_name, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False

    events = data.get("object_events", [])
    # Find array index by matching local_id to object_id
    target_idx = None
    for i, obj in enumerate(events):
        local_id = obj.get("local_id")
        if isinstance(local_id, int) and local_id == object_id:
            target_idx = i
            break
        if isinstance(local_id, str) and local_id.isdigit() and int(local_id) == object_id:
            target_idx = i
            break
    if target_idx is None:
        # Fallback: try 0-based index (object_id is 1-based)
        idx = object_id - 1
        if 0 <= idx < len(events):
            target_idx = idx
    if target_idx is None:
        return False

    events[target_idx]["script"] = script_label

    try:
        with open(map_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError:
        return False

    from torch.project_files import clear_project_cache
    clear_project_cache()
    _metadata_cache.clear()
    return True


def _auto_wire_coord_event(game_path, map_name, coords, elevation, var_name, var_value, script_label):
    """Write coord trigger event(s) directly into map.json. Returns True on success."""
    map_json_path = os.path.join(
        game_path, "data", "maps", map_name, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False

    coord_events = data.get("coord_events", [])

    try:
        elev_int = int(elevation)
    except ValueError:
        elev_int = 0

    try:
        var_val_int = int(var_value)
    except ValueError:
        var_val_int = 0

    for cx, cy in coords:
        entry = {
            "type": "trigger",
            "x": cx,
            "y": cy,
            "elevation": elev_int,
            "var": var_name,
            "var_value": str(var_val_int),
            "script": script_label,
        }
        coord_events.append(entry)

    data["coord_events"] = coord_events

    try:
        with open(map_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError:
        return False

    from torch.project_files import clear_project_cache
    clear_project_cache()
    _metadata_cache.clear()
    return True


def _trigger_npc(map_name, script_label, cast, game_path):
    """NPC interaction trigger — returns (prepend_beats, append_beats, instructions) or _WIZARD_CANCEL."""
    from torch.pickers import pick_flag, pick_map_npc
    print()
    print(f"  {DIM}Which NPC triggers this script?{RST}")
    selected = pick_map_npc(game_path, map_name)
    if selected:
        npc_id = str(selected["object_id"])
    else:
        # Fall through to manual entry
        npc_id = _wizard_input("  Object ID > ")
        if npc_id is _WIZARD_CANCEL:
            return _WIZARD_CANCEL
    if not npc_id:
        return [], [], []

    print()
    print(f"  {DIM}Flag to prevent replay? (Enter to skip, or pick one){RST}")
    flag_choice = _wizard_input("  [Enter] skip  [p] pick flag > ")
    if flag_choice is _WIZARD_CANCEL:
        return _WIZARD_CANCEL
    flag_choice = flag_choice.lower()
    flag_name = None
    if flag_choice == "p":
        flag_name = pick_flag(game_path)

    # Build scaffolding beats
    prepend = [
        {"type": "lock", "data": {}},
        {"type": "faceplayer", "data": {}},
    ]
    append = []
    if flag_name:
        append.append({"type": "flag", "data": {"action": "set", "flag_name": flag_name}})
    append.append({"type": "flow", "data": {"flow_type": "release"}})

    # Auto-wire: write the script field directly into map.json
    instructions = []
    auto_wired = False
    if selected:
        auto_wired = _auto_wire_npc_script(
            game_path, map_name, selected["object_id"], script_label)
    if auto_wired:
        npc_name = selected.get("display_name", f"NPC #{npc_id}")
        print()
        print(f"  {GREEN}Wired {npc_name} -> {script_label}{RST}")
        if flag_name:
            instructions = [
                f'(Optional) Set NPC #{npc_id} "Flag" field to: {flag_name} in Porymap',
            ]
    else:
        # Fallback: manual instructions for manual entry or failed auto-wire
        instructions = [
            f"1. Open {map_name} in Porymap",
            f"2. Select object event #{npc_id}",
            f'3. Set "Script" field to: {script_label}',
        ]
        if flag_name:
            instructions.append(f'4. (Optional) Set "Flag" field to: {flag_name}')

    return prepend, append, instructions


def _trigger_coord(map_name, script_label, game_path):
    """Walk-on coord trigger — returns (prepend_beats, append_beats, instructions) or _WIZARD_CANCEL."""
    from torch.pickers import pick_flag
    print()
    print(f"  {DIM}Trigger tile coordinates:{RST}")
    x = _wizard_input("  X > ")
    if x is _WIZARD_CANCEL:
        return _WIZARD_CANCEL
    y = _wizard_input("  Y > ")
    if y is _WIZARD_CANCEL:
        return _WIZARD_CANCEL
    if not x or not y:
        return [], [], []

    # Elevation (0 = any/ground level)
    elev = _wizard_input("  Elevation (0 = any/ground) [0] > ")
    if elev is _WIZARD_CANCEL:
        return _WIZARD_CANCEL
    elev = elev or "0"

    # Multi-tile range (replaces the old width/height which didn't actually exist in coord events)
    print()
    print(f"  {DIM}Cover multiple tiles? Enter end coords, or Enter for single tile.{RST}")
    end_x = _wizard_input("  End X [Enter = single tile] > ")
    if end_x is _WIZARD_CANCEL:
        return _WIZARD_CANCEL
    coords = []
    if end_x:
        end_y = _wizard_input("  End Y > ")
        if end_y is _WIZARD_CANCEL:
            return _WIZARD_CANCEL
        if end_y:
            try:
                x1, y1 = int(x), int(y)
                x2, y2 = int(end_x), int(end_y)
                for cx in range(min(x1, x2), max(x1, x2) + 1):
                    for cy in range(min(y1, y2), max(y1, y2) + 1):
                        coords.append((cx, cy))
            except ValueError:
                coords = [(int(x), int(y))]
        else:
            coords = [(int(x), int(y))]
    else:
        try:
            coords = [(int(x), int(y))]
        except ValueError:
            return [], [], []

    # Trigger variable (REQUIRED for coord events to fire)
    print()
    print(f"  {DIM}Trigger variable (the trigger fires when this var equals the value below):{RST}")
    var_name = _wizard_input("  Variable [VAR_TEMP_1] > ")
    if var_name is _WIZARD_CANCEL:
        return _WIZARD_CANCEL
    var_name = var_name or "VAR_TEMP_1"
    var_value = _wizard_input("  Value [0] > ")
    if var_value is _WIZARD_CANCEL:
        return _WIZARD_CANCEL
    var_value = var_value or "0"

    # Optional flag gate
    print()
    print(f"  {DIM}Flag gate? (script only plays once if flag is unset){RST}")
    flag_choice = _wizard_input("  [Enter] skip  [p] pick flag > ")
    if flag_choice is _WIZARD_CANCEL:
        return _WIZARD_CANCEL
    flag_choice = flag_choice.lower()
    flag_name = None
    if flag_choice == "p":
        flag_name = pick_flag(game_path)

    prepend = [
        {"type": "lock", "data": {}},
    ]
    append = []
    if flag_name:
        append.append({"type": "flag", "data": {"action": "set", "flag_name": flag_name}})
    # Auto-set var to non-matching value to prevent re-triggering
    # If var_value is "0", set to "1". Otherwise set to "0".
    deactivate_value = "1" if var_value == "0" else "0"
    append.append({"type": "var", "data": {"var_name": var_name, "value": deactivate_value}})
    append.append({"type": "flow", "data": {"flow_type": "release"}})

    # Auto-wire coord events into map.json
    auto_wired = _auto_wire_coord_event(
        game_path, map_name, coords, elev, var_name, var_value, script_label)

    instructions = []
    if auto_wired:
        tile_desc = f"({len(coords)} tile{'s' if len(coords) != 1 else ''})"
        print()
        print(f"  {GREEN}Wired coord trigger {tile_desc} -> {script_label}{RST}")
    else:
        # Fallback: manual instructions
        instructions = [
            f"1. Open {map_name} in Porymap -> Events tab",
            f"2. Add a Coord Event at X:{x}, Y:{y}",
            f'3. Set "Script" field to: {script_label}',
            f'4. Set "Var" to: {var_name}, "Var Value" to: {var_value}',
        ]
        if len(coords) > 1:
            instructions.append(
                f"5. Add {len(coords) - 1} more coord event(s) for each additional tile")

    return prepend, append, instructions


def _trigger_map_entry_write_setup(map_name, setup_path, setup_content, frame_entry):
    """Insert a MAP_SCRIPT entry into setup.pory content. Returns updated content."""
    ms_pattern = rf'mapscripts\s+{re.escape(map_name)}_MapScripts\s*\{{'
    ms_match = re.search(ms_pattern, setup_content)

    if ms_match:
        # Find the closing } of the mapscripts block
        brace_start = ms_match.end() - 1  # the { position
        depth = 0
        pos = brace_start
        for pos in range(brace_start, len(setup_content)):
            if setup_content[pos] == "{":
                depth += 1
            elif setup_content[pos] == "}":
                depth -= 1
                if depth == 0:
                    break

        # Check if the block is empty (just {})
        inner = setup_content[brace_start + 1:pos].strip()
        if not inner:
            new_block = (
                f"mapscripts {map_name}_MapScripts {{\n"
                f"{frame_entry}\n"
                f"}}"
            )
            setup_content = setup_content[:ms_match.start()] + new_block + setup_content[pos + 1:]
        else:
            insert_pos = pos
            setup_content = (
                setup_content[:insert_pos] +
                f"\n{frame_entry}\n" +
                setup_content[insert_pos:]
            )
    else:
        setup_content = setup_content.rstrip("\n") + (
            f"\n\nmapscripts {map_name}_MapScripts {{\n"
            f"{frame_entry}\n"
            f"}}\n"
        )

    return setup_content


def _trigger_map_entry(map_name, script_label, project_dir, game_path):
    """Map-entry trigger — returns (prepend_beats, append_beats, instructions) or _WIZARD_CANCEL. Writes to setup.pory."""
    from torch.pickers import pick_flag, pick_var
    print()
    print(f"  {GOLD}[1]{RST} {DIM}Once only (use a flag to prevent replay){RST}")
    print(f"  {GOLD}[2]{RST} {DIM}Every entry (plays each time){RST}")
    print()
    freq = _wizard_input("  > ")
    if freq is _WIZARD_CANCEL:
        return _WIZARD_CANCEL
    once_only = freq != "2"

    flag_name = None
    var_name = "VAR_TEMP_1"

    if once_only:
        print()
        print(f"  {DIM}Flag for once-only:{RST}")
        flag_name = pick_flag(game_path)
        if not flag_name:
            print("  No flag selected. Using manual mode.")
            return [], [], []

        print()
        print(f"  {DIM}VAR for the trigger (Enter for VAR_TEMP_1):{RST}")
        var_input = _wizard_input("  > ")
        if var_input is _WIZARD_CANCEL:
            return _WIZARD_CANCEL
        if var_input:
            var_name = var_input

    # Build the frame entry text
    setup_path = _ensure_setup_pory(map_name, project_dir)
    with open(setup_path, "r") as f:
        setup_content = f.read()

    if once_only:
        frame_entry = (
            f"    MAP_SCRIPT_ON_FRAME_TABLE [\n"
            f"        {var_name}, 0, {script_label}\n"
            f"    ]"
        )
    else:
        frame_entry = (
            f"    MAP_SCRIPT_ON_RESUME_TABLE [\n"
            f"        {script_label}\n"
            f"    ]"
        )

    setup_content = _trigger_map_entry_write_setup(
        map_name, setup_path, setup_content, frame_entry)

    with open(setup_path, "w") as f:
        f.write(setup_content)

    print()
    print(f"  {DIM}Added MAP_SCRIPT entry to setup.pory{RST}")

    # Build scaffolding beats
    prepend = [
        {"type": "lock", "data": {}},
    ]
    append = []
    if once_only:
        append.append({"type": "var", "data": {"var_name": var_name, "value": "1"}})
        if flag_name:
            append.append({"type": "flag", "data": {"action": "set", "flag_name": flag_name}})
    append.append({"type": "flow", "data": {"flow_type": "release"}})

    instructions = [
        "No Porymap changes needed \u2014 the trigger is in setup.pory.",
    ]

    return prepend, append, instructions


# -- New script wizard ----------------------------------------------------------

_WIZARD_CANCEL = object()  # sentinel for q-to-cancel in wizard steps


def _wizard_input(prompt):
    """Input helper for wizard steps. Returns the stripped input, or _WIZARD_CANCEL if 'q'."""
    try:
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return _WIZARD_CANCEL
    if raw.lower() == "q":
        return _WIZARD_CANCEL
    return raw


def _wizard_step_map_name(project_dir):
    """Wizard step 1: ask for map name. Returns map_name or None if cancelled."""
    print("  Which map is this script for?")
    print()
    if os.path.isdir(project_dir):
        existing = sorted([d for d in os.listdir(project_dir)
                          if os.path.isdir(os.path.join(project_dir, d))
                          and d not in ("backups", "config", "output")])
        if existing:
            print("  Existing maps:")
            for m in existing:
                print(f"    {m}")
            print()
    map_name = _wizard_input("  Map name (e.g. MapName) > ")
    if map_name is _WIZARD_CANCEL or not map_name:
        return None
    return map_name


def _wizard_step_script_name():
    """Wizard step 2: ask for script name. Returns script_name or None if cancelled."""
    print()
    print("  Script name (becomes the filename).")
    print("  e.g. 'ScriptName' -> ScriptName.txt")
    print()
    script_name = _wizard_input("  Script name > ")
    if script_name is _WIZARD_CANCEL or not script_name:
        return None
    return script_name


def _wizard_step_cast(game_path=None, map_name=None):
    """Wizard step 5: build cast dict. Returns cast dict or _WIZARD_CANCEL."""
    from torch.project_files import get_map_objects

    print()
    print("  Set up the cast (player is always present).")
    cast = {}

    # Offer NPC auto-detection if map data is available
    if game_path and map_name:
        npcs = get_map_objects(game_path, map_name)
        if npcs:
            print()
            print(f"  {DIM}NPCs on {map_name}:{RST}")
            print()
            for i, npc in enumerate(npcs, 1):
                parts = [f"at ({npc['x']},{npc['y']})"]
                if npc["trainer_type"] != "TRAINER_TYPE_NONE":
                    parts.append("trainer")
                if npc["script"]:
                    parts.append(f"script: {npc['script']}")
                else:
                    parts.append("no script")
                detail = " \u2014 ".join(parts)
                print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{npc['display_name']}{RST}  {DIM}{detail}{RST}")
            print()
            print(f"  {DIM}Enter NPC numbers to add to cast (comma-separated), or Enter to skip.{RST}")
            picks = _wizard_input("  Add NPCs > ")
            if picks is _WIZARD_CANCEL:
                return _WIZARD_CANCEL
            if picks:
                for token in picks.split(","):
                    token = token.strip()
                    try:
                        idx = int(token) - 1
                        if 0 <= idx < len(npcs):
                            npc = npcs[idx]
                            actor = npc["display_name"].lower().replace(" ", "_")
                            if actor == "player":
                                print(f"  {DIM}'player' is always present, skipping.{RST}")
                                continue
                            cast[actor] = npc["object_id"]
                            print(f"  Added: {actor} = npc{npc['object_id']}")
                    except ValueError:
                        pass
            print()

    # Manual actor entry (also for adding beyond auto-detected)
    if cast:
        print(f"  {DIM}Add more actors manually, or Enter when done.{RST}")
    while True:
        name = _wizard_input("  Actor name (Enter when done) > ")
        if name is _WIZARD_CANCEL:
            return _WIZARD_CANCEL
        if not name:
            break
        name = name.lower()
        original = name
        name = re.sub(r'\s+', '_', name)
        if name != original:
            print(f"  (spaces converted to underscores: {name})")
        if name == "player":
            print("  'player' is always present.")
            continue
        npc_raw = _wizard_input(f"  NPC object ID for {name} > ")
        if npc_raw is _WIZARD_CANCEL:
            return _WIZARD_CANCEL
        try:
            cast[name] = int(npc_raw)
            print(f"  Added: {name} = npc{cast[name]}")
        except ValueError:
            print("  Invalid number, skipping.")
    return cast


def _wizard_step_trigger(map_name, label, cast, project_dir, game_path):
    """Wizard step 6: choose trigger type and gather scaffolding. Returns _WIZARD_CANCEL or tuple."""
    print()
    print(BAR)
    print(f"   {WHITE}TRIGGER SETUP{RST}")
    print(BAR)
    print()
    print("  How will this script be triggered in-game?")
    print()
    print(f"    {GOLD}[1]{RST} NPC interaction    {DIM}Player talks to an NPC{RST}")
    print(f"    {GOLD}[2]{RST} Walk-on trigger    {DIM}Player steps on a tile zone{RST}")
    print(f"    {GOLD}[3]{RST} Map entry          {DIM}Script plays when entering the map{RST}")
    print(f"    {GOLD}[4]{RST} Manual             {DIM}No scaffolding (advanced){RST}")
    print()
    trigger_choice = _wizard_input("  > ")
    if trigger_choice is _WIZARD_CANCEL:
        return _WIZARD_CANCEL

    if trigger_choice == "1":
        return _trigger_npc(map_name, label, cast, game_path)
    elif trigger_choice == "2":
        return _trigger_coord(map_name, label, game_path)
    elif trigger_choice == "3":
        return _trigger_map_entry(map_name, label, project_dir, game_path)
    return [], [], []


def _new_script_wizard(project_dir, game_path, emotes_conf, source_display,
                      settings=None, proj_name=None, map_name=None):
    """Guided setup for creating a new script."""

    clear_screen()
    print_logo("Studio", proj_name)
    print(BAR)
    print(f"   {WHITE}NEW SCRIPT{RST}")
    print(BAR)
    print()

    # Step 1: Map name (skip if already known from browser)
    if not map_name:
        map_name = _wizard_step_map_name(project_dir)
        if not map_name:
            return
    else:
        print(f"  Map: {WHITE}{map_name}{RST}")
        print()

    # Step 2: Script name
    script_name = _wizard_step_script_name()
    if not script_name:
        return

    # Check if file exists
    map_dir = os.path.join(project_dir, map_name)
    filepath = os.path.join(map_dir, f"{script_name}.txt")
    if os.path.exists(filepath):
        print(f"  File already exists: {script_name}.txt")
        print("  Opening existing file instead.")
        input("  Press Enter > ")
        script_data = _parse_script(filepath, emotes_conf)
        _script_editor_loop(script_data, map_name, filepath,
                            project_dir, game_path, emotes_conf, source_display,
                            settings)
        return

    # Step 3: Header comment
    print()
    header = _wizard_input("  One-line description (e.g. 'NPC arrives after player victory') > ")
    if header is _WIZARD_CANCEL:
        return
    if not header:
        header = ""

    # Step 4: Label
    suggested_label = f"{map_name}_{script_name}"
    print()
    print(f"  Suggested label: {suggested_label}")
    label_raw = _wizard_input("  Label (Enter to accept) > ")
    if label_raw is _WIZARD_CANCEL:
        return
    label = label_raw if label_raw else suggested_label

    # Step 5: Cast
    cast = _wizard_step_cast(game_path, map_name)
    if cast is _WIZARD_CANCEL:
        return

    # Step 6: Trigger setup
    trigger_result = _wizard_step_trigger(
        map_name, label, cast, project_dir, game_path)
    if trigger_result is _WIZARD_CANCEL:
        return
    prepend_beats, append_beats, porymap_instructions = trigger_result

    # Step 7: Optional template
    print()
    print(f"  {DIM}Start from a template? (Enter to skip){RST}")
    print()
    from torch.templates import run_template_wizard
    template_beats = run_template_wizard(game_path, map_name, label, cast)

    # Build initial script data
    initial_beats = [{"type": "label", "data": {"name": label}}]
    initial_beats.extend(prepend_beats)
    if template_beats:
        initial_beats.extend(template_beats)
    elif prepend_beats:
        initial_beats.append({"type": "comment", "data": {"text": "--- your beats here ---"}})
    initial_beats.extend(append_beats)

    script_data = {
        "label": label,
        "labels": [label],
        "cast": cast,
        "beats": initial_beats,
        "header_comment": header,
    }

    # Create directory if needed
    os.makedirs(map_dir, exist_ok=True)

    # Save initial file
    output = _serialize_script(script_data)
    with open(filepath, "w") as f:
        f.write(output)

    # Auto-sync so the new script is compiled immediately
    ensure_synced(map_name, project_dir, game_path, emotes_conf,
                  source_display, settings.get("max_snapshots", 10) if settings else 10)

    if prepend_beats:
        print()
        scaffold_count = len(prepend_beats) + len(append_beats)
        print(f"  Scaffolding added: {scaffold_count} beat{'s' if scaffold_count != 1 else ''}")

    if porymap_instructions:
        _print_porymap_instructions(porymap_instructions)

    print()
    print(f"  Created: {filepath}")
    print()
    input("  Press Enter to open in editor > ")

    # Open in editor
    _script_editor_loop(script_data, map_name, filepath,
                        project_dir, game_path, emotes_conf, source_display,
                        settings)


# -- CLI entry point -----------------------------------------------------------

def _cmd_chain_sync(project_dir, game_path, chain_name=None):
    """CLI: torch script sync [ChainName] — sync one or all chains."""
    from torch.chain_model import list_chains, load_chain, save_chain
    from torch.chain_sync import sync_chain

    chains = list_chains(project_dir)
    if not chains:
        print("  No chains found.")
        return

    targets = chains
    if chain_name:
        targets = [c for c in chains if c["name"] == chain_name]
        if not targets:
            print(f"  Chain '{chain_name}' not found.")
            return

    for summary in targets:
        name = summary["name"]
        data = load_chain(project_dir, name)
        if not data:
            print(f"  Could not load chain: {name}")
            continue

        print(f"  Syncing chain: {name}...")
        result = sync_chain(project_dir, game_path, data,
                           progress_callback=lambda seg, i, total: print(
                               f"    [{i+1}/{total}] {seg}"))
        save_chain(project_dir, data)

        synced = result.get("segments_synced", 0)
        skipped = result.get("segments_skipped", 0)
        warnings = result.get("warnings", [])
        print(f"    Synced {synced}, skipped {skipped}")
        for w in warnings:
            print(f"    Warning: {w}")

    print("  Done.")


def script_command(args, project_dir, game_path, emotes_conf, source_display,
                  settings=None, proj_name=None):
    """CLI entry point for 'torch scene/maps/studio [MapName] [ScriptName]'."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)

    # Handle 'torch script sync [ChainName]'
    if len(args) >= 1 and args[0] == "sync":
        chain_name = args[1] if len(args) >= 2 else None
        _cmd_chain_sync(project_dir, game_path, chain_name)
        return

    if len(args) >= 2:
        map_name = args[0]
        script_name = args[1]
        if script_name.endswith(".txt"):
            script_name = script_name[:-4]
        filepath = os.path.join(project_dir, map_name, f"{script_name}.txt")
        if os.path.exists(filepath):
            script_data = _parse_script(filepath, emotes_conf)
            _script_editor_loop(script_data, map_name, filepath,
                                project_dir, game_path, emotes_conf, source_display,
                                settings, proj_name)
        else:
            print(f"  Script not found: {filepath}")
            print("  Use 'torch maps' to open Studio.")
    elif len(args) == 1:
        # torch maps MapName -- open workspace (could pre-select map in future)
        if proj_name is None:
            proj_name = os.path.basename(project_dir) or None
        _set_terminal_title("TORCH -- Studio")
        _browse_maps(project_dir, game_path, emotes_conf, source_display,
                     settings, proj_name)
    else:
        if proj_name is None:
            proj_name = os.path.basename(project_dir) or None
        _set_terminal_title("TORCH -- Studio")
        _browse_maps(project_dir, game_path, emotes_conf, source_display,
                     settings, proj_name)
