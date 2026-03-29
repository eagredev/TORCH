"""TORCH Vault — build snapshot browser, workspace snapshots, and restore."""
# TORCH_MODULE: Vault
# TORCH_GROUP: Tools
import os
import zipfile
from datetime import datetime

from torch import VERSION
from torch.config import SETTINGS_DEFAULTS, _nav_keys, DIVIDER
from torch.ui import print_logo, _set_terminal_title, clear_screen
from torch.sync import restore_map, sync_map, get_workspace_files
from torch.backup import _list_torch_backups, _create_torch_backup
from torch.registry import is_enrolled, get_map_health
from torch.colours import GOLD, WHITE, CYAN, GREEN, RED, DIM, RST, BAR

try:
    from torch.verified_snapshots import (
        list_verified_snapshots, restore_verified_snapshot,
        list_maps_in_snapshot, restore_map_from_verified,
        preview_map_in_snapshot,
    )
    _HAS_VERIFIED = True
except ImportError:
    _HAS_VERIFIED = False




# ============================================================
# HEADER
# ============================================================

def _vault_header_info(project_dir, game_path):
    """Compute summary data for the vault header. Returns a dict with display values."""
    from torch.registry import load_registry

    # Sync status: check all enrolled maps
    registry = load_registry(project_dir)
    enrolled = sorted(registry["maps"].keys())
    stale_count = 0
    for m in enrolled:
        health = get_map_health(project_dir, m, game_path)
        if health in ("stale", "drift"):
            stale_count += 1
    if not enrolled:
        sync_label = "no maps enrolled"
    elif stale_count:
        sync_label = f"{stale_count} stale"
    else:
        sync_label = "synced"

    return {
        "sync_label": sync_label,
        "stale_count": stale_count,
    }


def _render_vault_header(proj_name, info):
    """Print the slim vault header — just build version and sync status."""
    sync_col = GREEN if info["stale_count"] == 0 else GOLD
    print(f"  {WHITE}TORCH Vault{RST} \u2014 {proj_name or 'Unknown Project'}")
    print(f"  {DIM}" + "\u2500" * 37 + f"{RST}")
    print(f"  Current build: {CYAN}v{VERSION}{RST}  ({sync_col}{info['sync_label']}{RST})")
    print(f"  {DIM}" + "\u2500" * 37 + f"{RST}")
    print()


# ============================================================
# BUILD SNAPSHOTS — PRIMARY LIST
# ============================================================

_VAULT_MAX_VISIBLE = 8  # max entries visible before windowed scrolling kicks in


def _render_build_snapshots(verified_snaps, selected_idx, scroll_offset):
    """Render the verified build snapshots list (main vault view).

    Uses windowed scrolling. Returns updated scroll_offset.
    """
    if not verified_snaps:
        print(f"  {WHITE}BUILD SNAPSHOTS{RST}")
        print()
        print(f"  {DIM}No build snapshots yet. Build through TORCH to create one.{RST}")
        print()
        return 0

    total = len(verified_snaps)
    max_vis = _VAULT_MAX_VISIBLE

    # Adjust scroll window to keep selected in view
    if selected_idx < scroll_offset:
        scroll_offset = selected_idx
    if selected_idx >= scroll_offset + max_vis:
        scroll_offset = selected_idx - max_vis + 1

    print(f"  {WHITE}BUILD SNAPSHOTS{RST}")
    print()

    if scroll_offset > 0:
        print(f"  {DIM}  \u2191 {scroll_offset} more above{RST}")
    else:
        print()  # consistent height

    num_w = len(str(total))
    end = min(scroll_offset + max_vis, total)
    for i in range(scroll_offset, end):
        snap = verified_snaps[i]
        is_selected = i == selected_idx
        cursor = f"{GOLD}>>{RST}" if is_selected else "  "
        num = f"{i + 1}."
        tag = f"  {GREEN}\u2190 latest{RST}" if i == 0 else ""
        time_col = WHITE if is_selected else CYAN
        print(f"  {cursor} {num:<{num_w + 1}} {time_col}{snap['display_time']}{RST}"
              f"    [{snap['trigger']}]{tag}")
        print(f"  {'':>{num_w + 5}} {DIM}{snap['file_count']} files  "
              f"\u2014  {snap['size_mb']:.1f} MB{RST}")
        print()

    remaining = total - end
    if remaining > 0:
        print(f"  {DIM}  \u2193 {remaining} more below{RST}")
    else:
        print()  # consistent height

    return scroll_offset


# ============================================================
# MAIN VAULT SCREEN
# ============================================================

def _render_vault_screen(project_dir, game_path, proj_name, verified_snaps,
                         selected_idx, scroll_offset, nav_keys):
    """Draw the full vault main screen. Returns updated scroll_offset."""
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = nav_keys
    clear_screen()
    print_logo("TORCH Vault", proj_name)
    print(BAR)

    header_info = _vault_header_info(project_dir, game_path)
    _render_vault_header(proj_name, header_info)
    scroll_offset = _render_build_snapshots(verified_snaps, selected_idx,
                                            scroll_offset)

    print(f"  {GOLD}[#]{RST}/{GOLD}[{NK_OPEN}]{RST} {DIM}open{RST}  "
          f"{GOLD}[Enter]{RST} {DIM}scroll{RST}  "
          f"{GOLD}[{NK_UP}]{RST} {DIM}up{RST}  "
          f"{GOLD}[{NK_DOWN}]{RST} {DIM}down{RST}  "
          f"{GOLD}[w]{RST} {DIM}workspace{RST}  "
          f"{GOLD}[t]{RST} {DIM}backup{RST}  "
          f"{GOLD}[k]{RST} {DIM}fork{RST}  "
          f"{GOLD}[v]{RST} {DIM}versions{RST}  "
          f"{GOLD}[q]{RST} {DIM}back{RST}")
    print()

    return scroll_offset


def backup_manager_menu(project_dir, game_path, emotes_conf, source_display,
                        settings=None, proj_name=None):
    """TORCH Vault — browse build snapshots and restore.

    Returns ("fork", new_proj_name) if user forked the project, None otherwise.
    """
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    if proj_name is None:
        proj_name = os.path.basename(project_dir) or None
    _set_terminal_title("TORCH \u2014 Vault")
    selected_idx = 0
    scroll_offset = 0
    nav_keys = _nav_keys(settings)
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = nav_keys

    while True:
        verified_snaps = list_verified_snapshots(game_path) if _HAS_VERIFIED else []
        if not verified_snaps:
            selected_idx = 0
        else:
            selected_idx = max(0, min(selected_idx, len(verified_snaps) - 1))

        scroll_offset = _render_vault_screen(project_dir, game_path, proj_name,
                             verified_snaps, selected_idx, scroll_offset,
                             nav_keys)

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return None
        raw = raw.rstrip("\n")

        if raw == "":
            if verified_snaps:
                selected_idx = (selected_idx + 1) % len(verified_snaps)
            continue

        raw = raw.strip()
        cmd = raw.lower()

        if cmd in ("q", ""):
            return None
        elif cmd == NK_UP:
            if verified_snaps:
                selected_idx = max(0, selected_idx - 1)
        elif cmd == NK_DOWN:
            if verified_snaps:
                selected_idx = min(len(verified_snaps) - 1, selected_idx + 1)
        elif cmd == NK_OPEN:
            if verified_snaps:
                _snapshot_detail_menu(verified_snaps[selected_idx], game_path,
                                     settings, proj_name)
        elif cmd == "w":
            _workspace_snapshots_menu(project_dir, game_path, emotes_conf,
                                      source_display, settings, proj_name)
        elif cmd == "t":
            _handle_torch_backup(proj_name)
        elif cmd == "k":
            result = _handle_fork(game_path, settings, proj_name)
            if result:
                return ("fork", result)
        elif cmd == "v":
            try:
                from torch.game_versions import versions_menu
                versions_menu(game_path, project_dir, settings, proj_name)
            except ImportError:
                print("  Game Version Control is not available.")
                input("  Press Enter > ")
        elif raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(verified_snaps):
                selected_idx = idx
            else:
                print(f"  No snapshot #{raw}.")
                input("  Press Enter > ")
        else:
            print("  Invalid choice.")


# ============================================================
# SNAPSHOT DETAIL SCREEN
# ============================================================

def _snapshot_detail_menu(snap, game_path, settings=None, proj_name=None):
    """Drill-down into a single verified build snapshot.

    Shows metadata, offers full restore or per-map restore.
    """
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)

    while True:
        clear_screen()
        print_logo("TORCH Vault", proj_name)
        print(BAR)
        print(f"   {WHITE}BUILD SNAPSHOT{RST}")
        print(BAR)
        print()
        print(f"  Timestamp:  {CYAN}{snap['display_time']}{RST}")
        print(f"  Trigger:    {snap['trigger']}")
        print(f"  Files:      {snap['file_count']}")
        print(f"  Size:       {snap['size_mb']:.1f} MB")

        # Read TORCH version from metadata if available
        try:
            import json
            with zipfile.ZipFile(snap["path"], "r") as zf:
                from torch.verified_snapshots import METADATA_FILENAME
                if METADATA_FILENAME in zf.namelist():
                    meta = json.loads(zf.read(METADATA_FILENAME))
                    tv = meta.get("torch_version")
                    if tv:
                        print(f"  TORCH ver:  {DIM}v{tv}{RST}")
        except (zipfile.BadZipFile, OSError, KeyError):
            pass

        print()
        print(f"  {GOLD}[r]{RST} {DIM}Full restore{RST}  "
              f"{GOLD}[m]{RST} {DIM}Map browser{RST}  "
              f"{GOLD}[q]{RST} {DIM}back{RST}")
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if raw in ("q", ""):
            return
        elif raw == "r":
            restored = restore_verified_snapshot(game_path, snap["path"])
            if restored is None:
                input("  Press Enter to continue > ")
            elif not restored:
                pass  # User declined
            else:
                print(f"  Restored {len(restored)} files from verified snapshot.")
                print()
                from torch.ui import _offer_build
                _offer_build(game_path, trigger="verified-restore")
                return
        elif raw == "m":
            _map_browser_menu(snap, game_path, settings, proj_name)
        else:
            print("  Invalid choice.")


# ============================================================
# MAP BROWSER — DRILL INTO A SNAPSHOT
# ============================================================

_MAP_BROWSER_MAX_VISIBLE = 16


def _get_custom_maps(game_path):
    """Return set of custom map names using the sentinel boundary, or None if unavailable."""
    try:
        from torch.project_files import classify_maps
        _, custom = classify_maps(game_path)
        return custom if custom else None
    except (ImportError, Exception):
        return None


def _map_browser_menu(snap, game_path, settings=None, proj_name=None):
    """Browse and restore individual maps from a verified build snapshot."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    nav_keys = _nav_keys(settings)
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = nav_keys
    selected_idx = 0
    scroll_offset = 0

    all_maps = list_maps_in_snapshot(snap["path"])
    custom_set = _get_custom_maps(game_path)
    show_all = custom_set is None  # If detection unavailable, show all

    while True:
        if show_all or custom_set is None:
            map_names = all_maps
        else:
            map_names = [m for m in all_maps if m in custom_set]

        if not map_names:
            selected_idx = 0
        else:
            selected_idx = max(0, min(selected_idx, len(map_names) - 1))

        # Render
        clear_screen()
        print_logo("TORCH Vault", proj_name)
        print(BAR)
        print(f"   {WHITE}MAPS IN SNAPSHOT{RST}  {DIM}\u2014  {snap['display_time']}{RST}")
        print(BAR)
        print()

        # Filter indicator
        if custom_set is not None:
            if show_all:
                print(f"  {DIM}Showing all {len(all_maps)} maps{RST}")
            else:
                print(f"  {DIM}Showing {len(map_names)} custom maps "
                      f"({len(all_maps)} total){RST}")
            print()

        if not map_names:
            if not show_all and custom_set is not None:
                print(f"  {DIM}No custom maps in this snapshot.{RST}")
                print(f"  {DIM}Press [a] to show all maps.{RST}")
            else:
                print(f"  {DIM}No maps found in this snapshot.{RST}")
            print()
        else:
            total = len(map_names)
            max_vis = _MAP_BROWSER_MAX_VISIBLE

            if selected_idx < scroll_offset:
                scroll_offset = selected_idx
            if selected_idx >= scroll_offset + max_vis:
                scroll_offset = selected_idx - max_vis + 1

            if scroll_offset > 0:
                print(f"  {DIM}  \u2191 {scroll_offset} more above{RST}")
            else:
                print()

            num_w = len(str(total))
            end = min(scroll_offset + max_vis, total)
            for i in range(scroll_offset, end):
                is_selected = i == selected_idx
                cursor = f"{GOLD}>>{RST}" if is_selected else "  "
                num = f"{i + 1}."
                name_col = WHITE if is_selected else ""
                rst = RST if name_col else ""
                print(f"  {cursor} {num:<{num_w + 1}} {name_col}{map_names[i]}{rst}")

            # Pad to consistent height
            for _ in range(end - scroll_offset, max_vis):
                print()

            remaining = total - end
            if remaining > 0:
                print(f"  {DIM}  \u2193 {remaining} more below{RST}")
            else:
                print()
            print()

        # Footer — toggle label reflects current state
        if custom_set is not None:
            toggle_label = "all" if not show_all else "custom"
        else:
            toggle_label = None
        toggle_hint = f"  {GOLD}[a]{RST} {DIM}{toggle_label}{RST}" if toggle_label else ""
        print(f"  {GOLD}[#]{RST}/{GOLD}[{NK_OPEN}]{RST} {DIM}restore{RST}  "
              f"{GOLD}[Enter]{RST} {DIM}scroll{RST}  "
              f"{GOLD}[{NK_UP}]{RST} {DIM}up{RST}  "
              f"{GOLD}[{NK_DOWN}]{RST} {DIM}down{RST}"
              f"{toggle_hint}  "
              f"{GOLD}[q]{RST} {DIM}back{RST}")
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return
        raw = raw.rstrip("\n")

        if raw == "":
            if map_names:
                selected_idx = (selected_idx + 1) % len(map_names)
            continue

        raw = raw.strip()
        cmd = raw.lower()

        if cmd in ("q", ""):
            return
        elif cmd == NK_UP:
            if map_names:
                selected_idx = max(0, selected_idx - 1)
        elif cmd == NK_DOWN:
            if map_names:
                selected_idx = min(len(map_names) - 1, selected_idx + 1)
        elif cmd == NK_OPEN:
            if map_names:
                _handle_map_restore(snap, map_names[selected_idx], game_path)
        elif cmd == "a" and custom_set is not None:
            show_all = not show_all
            selected_idx = 0
            scroll_offset = 0
        elif raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(map_names):
                _handle_map_restore(snap, map_names[idx], game_path)
            else:
                print(f"  No map #{raw}.")
                input("  Press Enter > ")
        else:
            print("  Invalid choice.")


def _handle_map_restore(snap, map_name, game_path):
    """Show restore preview, confirm, and execute a per-map restore."""
    print()
    print(f"  {WHITE}{map_name}{RST}  {DIM}\u2014  {snap['display_time']}{RST}")

    preview = preview_map_in_snapshot(game_path, snap["path"], map_name)
    if preview is None:
        print(f"  {DIM}Map not found in this snapshot.{RST}")
        input("  Press Enter > ")
        return

    n_mod = len(preview["modified"])
    n_miss = len(preview["missing"])
    n_same = preview["unchanged"]
    total = preview["total_files"]

    print(f"  {DIM}{total} files in snapshot{RST}")
    if n_same == total:
        print(f"  {GREEN}All files match current project — nothing to restore.{RST}")
        input("  Press Enter > ")
        return
    if n_mod:
        print(f"  {GOLD}{n_mod} modified{RST} {DIM}(will be overwritten){RST}")
    if n_miss:
        print(f"  {CYAN}{n_miss} missing{RST} {DIM}(will be added){RST}")
    if n_same:
        print(f"  {DIM}{n_same} unchanged{RST}")
    print()

    try:
        confirm = input(f"  Restore? [y/N] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm != "y":
        return
    restored = restore_map_from_verified(game_path, snap["path"], map_name)
    if restored is None:
        input("  Press Enter to continue > ")
    elif not restored:
        pass  # User declined (modification warning)
    else:
        print(f"  Restored {len(restored)} files for {map_name}.")
        print()
        from torch.ui import _offer_build
        _offer_build(game_path, trigger="map-restore")


# ============================================================
# WORKSPACE SNAPSHOTS — SUB-SCREEN
# ============================================================

def _workspace_snapshots_menu(project_dir, game_path, emotes_conf, source_display,
                              settings=None, proj_name=None):
    """Workspace (per-map) snapshot browser — accessible via [w] from main vault."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    nav_keys = _nav_keys(settings)
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = nav_keys
    selected_idx = 0
    scroll_offset = 0

    while True:
        maps_with_snapshots = _gather_maps_with_snapshots(project_dir)
        if not maps_with_snapshots:
            selected_idx = 0
        else:
            selected_idx = max(0, min(selected_idx, len(maps_with_snapshots) - 1))

        # Render
        clear_screen()
        print_logo("TORCH Vault", proj_name)
        print(BAR)

        header_info = _vault_header_info(project_dir, game_path)
        _render_vault_header(proj_name, header_info)
        scroll_offset = _render_map_list(maps_with_snapshots, selected_idx,
                                          scroll_offset, project_dir, game_path)

        print(f"  {GOLD}[#]{RST}/{GOLD}[{NK_OPEN}]{RST} {DIM}open{RST}  "
              f"{GOLD}[Enter]{RST} {DIM}scroll{RST}  "
              f"{GOLD}[{NK_UP}]{RST} {DIM}up{RST}  "
              f"{GOLD}[{NK_DOWN}]{RST} {DIM}down{RST}  "
              f"{GOLD}[q]{RST} {DIM}back{RST}")
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return
        raw = raw.rstrip("\n")

        if raw == "":
            if maps_with_snapshots:
                selected_idx = (selected_idx + 1) % len(maps_with_snapshots)
            continue

        raw = raw.strip()
        cmd = raw.lower()

        if cmd in ("q", ""):
            return
        elif cmd == NK_UP:
            if maps_with_snapshots:
                selected_idx = max(0, selected_idx - 1)
        elif cmd == NK_DOWN:
            if maps_with_snapshots:
                selected_idx = min(len(maps_with_snapshots) - 1, selected_idx + 1)
        elif cmd == NK_OPEN:
            if maps_with_snapshots:
                _backup_map_menu(maps_with_snapshots[selected_idx], project_dir,
                                 game_path, emotes_conf, source_display, settings, proj_name)
        elif raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(maps_with_snapshots):
                selected_idx = idx
            else:
                print(f"  No map #{raw}.")
                input("  Press Enter > ")
        else:
            print("  Invalid choice.")


# ============================================================
# WORKSPACE — GATHER & RENDER HELPERS
# ============================================================

def _gather_maps_with_snapshots(project_dir):
    """Scan project workspace for maps that have snapshot backups.

    Returns list of dicts: name, snap_dir, count, latest (date string).
    """
    result = []
    if not os.path.isdir(project_dir):
        return result
    for entry in sorted(os.listdir(project_dir)):
        map_dir = os.path.join(project_dir, entry)
        snap_dir = os.path.join(map_dir, "backups", "snapshots")
        if not os.path.isdir(snap_dir):
            continue
        snaps = sorted([
            f for f in os.listdir(snap_dir)
            if f.startswith(entry + "_") and f.endswith(".zip")
        ], reverse=True)
        if not snaps:
            continue
        ts_raw = snaps[0][len(entry) + 1:-4]
        try:
            dt = datetime.strptime(ts_raw, "%Y%m%d_%H%M%S")
            latest = dt.strftime("%Y-%m-%d")
        except ValueError:
            latest = ts_raw
        result.append({
            "name": entry,
            "snap_dir": snap_dir,
            "count": len(snaps),
            "latest": latest,
        })
    return result


def _render_map_list(maps_with_snapshots, selected_idx, scroll_offset,
                     project_dir, game_path):
    """Render the workspace snapshots list with health badges.

    Uses windowed scrolling to keep output height consistent across redraws.

    Returns the updated scroll_offset.
    """
    if not maps_with_snapshots:
        print(f"  {DIM}No maps with snapshots found.{RST}")
        print()
        return 0

    total = len(maps_with_snapshots)
    max_vis = _VAULT_MAX_VISIBLE

    # Adjust scroll window to keep selected in view
    if selected_idx < scroll_offset:
        scroll_offset = selected_idx
    if selected_idx >= scroll_offset + max_vis:
        scroll_offset = selected_idx - max_vis + 1

    print(f"  {WHITE}WORKSPACE SNAPSHOTS{RST}")
    print()

    if scroll_offset > 0:
        print(f"  {DIM}  \u2191 {scroll_offset} more above{RST}")
    else:
        print()  # consistent height

    num_w = len(str(total))
    end = min(scroll_offset + max_vis, total)
    for i in range(scroll_offset, end):
        info = maps_with_snapshots[i]
        is_selected = i == selected_idx
        cursor = f"{GOLD}>>{RST}" if is_selected else "  "
        num = f"{i + 1}."
        count = info["count"]
        snap_word = "snapshots" if count != 1 else "snapshot"
        map_name_str = info["name"]
        badge = _map_health_badge(project_dir, map_name_str, game_path)
        name_col = WHITE if is_selected else ""
        rst = RST if name_col else ""
        print(f"  {cursor} {num:<{num_w + 1}} {name_col}{info['name']}{rst}{badge}")
        print(f"  {'':>{num_w + 5}} {GREEN}{count} {snap_word}{RST}  {DIM}\u2014  latest: {info['latest']}{RST}")
        if is_selected:
            _render_script_files(info["snap_dir"], num_w)
        print()

    remaining = total - end
    if remaining > 0:
        print(f"  {DIM}  \u2193 {remaining} more below{RST}")
    else:
        print()  # consistent height

    return scroll_offset


def _map_health_badge(project_dir, map_name, game_path):
    """Return an ANSI-colored health badge string for a map."""
    if is_enrolled(project_dir, map_name):
        health = get_map_health(project_dir, map_name, game_path)
        if health == "stale":
            return f"  {GOLD}[STALE]{RST}"
        elif health == "drift":
            return f"  {RED}[DRIFT]{RST}"
        return ""
    return f"  {DIM}[not enrolled]{RST}"


def _render_script_files(snap_dir, num_w):
    """Render compact script file list under a map entry."""
    map_dir = os.path.dirname(os.path.dirname(snap_dir))
    script_files = sorted([
        os.path.splitext(f)[0]
        for f in os.listdir(map_dir)
        if f.endswith(".txt") or f.endswith(".pory")
    ])
    shown = script_files[:6]
    for fname in shown:
        print(f"  {'':>{num_w + 5}} {DIM}{fname}{RST}")
    if len(script_files) > 6:
        print(f"  {'':>{num_w + 5}} {DIM}+{len(script_files) - 6} more{RST}")


# ============================================================
# PER-MAP SNAPSHOT BROWSER (workspace drill-down)
# ============================================================

def _render_snapshot_list(snaps, snap_dir, map_name, selected_idx):
    """Render per-map snapshot entries."""
    if not snaps:
        print(f"  {DIM}(no snapshots){RST}")
        print()
        return
    num_w = len(str(len(snaps)))
    for i, fname in enumerate(snaps):
        cursor = f"{GOLD}>>{RST}" if i == selected_idx else "  "
        num = f"{i + 1}."
        fpath = os.path.join(snap_dir, fname)
        size_kb = os.path.getsize(fpath) // 1024
        ts_raw = fname[len(map_name) + 1:-4]
        try:
            dt = datetime.strptime(ts_raw, "%Y%m%d_%H%M%S")
            display_time = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            display_time = ts_raw
        try:
            with zipfile.ZipFile(fpath, "r") as zf:
                file_count = len(zf.namelist())
        except zipfile.BadZipFile:
            file_count = "?"
        pin_path = os.path.join(snap_dir, fname + ".pin")
        is_pinned = os.path.exists(pin_path)
        tag = f"  {GREEN}\u2190 latest{RST}" if i == 0 else ""
        if is_pinned:
            tag += f"  {GOLD}\u2605 PINNED{RST}"
        time_col = WHITE if i == selected_idx else CYAN
        print(f"  {cursor} {num:<{num_w + 1}} {time_col}{display_time}{RST}{tag}")
        print(f"  {'':>{num_w + 5}} {DIM}{file_count} files  \u2014  {size_kb} KB{RST}")
        print()


def _render_map_snapshot_screen(map_name, snap_dir, snaps, selected_idx, proj_name, nav_keys):
    """Draw the per-map snapshot screen."""
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = nav_keys
    clear_screen()
    print_logo("TORCH Vault", proj_name)
    print(BAR)
    print(f"   {WHITE}SNAPSHOTS{RST}  {DIM}\u2014  {map_name}{RST}")
    print(BAR)
    print()
    _render_snapshot_list(snaps, snap_dir, map_name, selected_idx)
    print(f"  {GOLD}[#]{RST}/{GOLD}[{NK_OPEN}]{RST} {DIM}restore{RST}  "
          f"{GOLD}[Enter]{RST} {DIM}scroll{RST}  "
          f"{GOLD}[{NK_UP}]{RST} {DIM}up{RST}  "
          f"{GOLD}[{NK_DOWN}]{RST} {DIM}down{RST}  "
          f"{GOLD}[p]{RST} {DIM}pin/unpin{RST}  "
          f"{GOLD}[s]{RST} {DIM}sync now{RST}  "
          f"{GOLD}[q]{RST} {DIM}back{RST}")
    print()


def _handle_snapshot_restore(map_name, selected_idx, project_dir, game_path,
                             emotes_conf, source_display, max_snapshots):
    """Handle restore action with pre-check, confirmation, and execution."""
    if not _restore_pre_check(map_name, game_path):
        input("  Press Enter to continue > ")
        return
    confirm = input(f"  Restore snapshot [{selected_idx + 1}]? [y/N] > ").strip().lower()
    if confirm == "y":
        restore_map(map_name, project_dir, game_path, emotes_conf, source_display,
                    max_snapshots, snapshot_idx=selected_idx)
        input("  Press Enter to continue > ")


def _backup_map_menu(map_info, project_dir, game_path, emotes_conf, source_display,
                     settings=None, proj_name=None):
    """Per-map snapshot browser."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    map_name = map_info["name"]
    snap_dir = map_info["snap_dir"]
    selected_idx = 0
    nav_keys = _nav_keys(settings)
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = nav_keys

    while True:
        snaps = sorted([
            f for f in os.listdir(snap_dir)
            if f.startswith(map_name + "_") and f.endswith(".zip")
        ], reverse=True)

        if not snaps:
            selected_idx = 0
        else:
            selected_idx = max(0, min(selected_idx, len(snaps) - 1))

        _render_map_snapshot_screen(map_name, snap_dir, snaps, selected_idx, proj_name, nav_keys)

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return
        raw = raw.rstrip("\n")

        if raw == "":
            if snaps:
                selected_idx = (selected_idx + 1) % len(snaps)
            continue

        raw = raw.strip()
        cmd = raw.lower()

        if cmd in ("q", ""):
            return
        elif cmd == NK_UP:
            if snaps:
                selected_idx = max(0, selected_idx - 1)
        elif cmd == NK_DOWN:
            if snaps:
                selected_idx = min(len(snaps) - 1, selected_idx + 1)
        elif cmd == NK_OPEN:
            if snaps:
                _handle_snapshot_restore(map_name, selected_idx, project_dir, game_path,
                                         emotes_conf, source_display, settings["max_snapshots"])
        elif cmd == "p":
            if snaps:
                _toggle_pin(snap_dir, snaps[selected_idx])
        elif cmd == "s":
            print()
            sync_map(map_name, project_dir, game_path, emotes_conf, source_display,
                     settings["max_snapshots"])
            print()
            input("  Press Enter to continue > ")
        elif raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(snaps):
                selected_idx = idx
            else:
                print(f"  No snapshot #{raw}.")
                input("  Press Enter > ")
        else:
            print("  Invalid choice.")


def _toggle_pin(snap_dir, fname):
    """Toggle pin status on a snapshot file."""
    pin_path = os.path.join(snap_dir, fname + ".pin")
    if os.path.exists(pin_path):
        os.remove(pin_path)
        print(f"  Unpinned.")
    else:
        open(pin_path, "w").close()
        print(f"  Pinned -- this snapshot will not be auto-deleted.")


def _restore_pre_check(map_name, game_path):
    """Check that the target map folder exists in the game project before restoring.

    Returns True if safe to proceed, False if user declines after warning.
    """
    game_map_dir = os.path.join(game_path, "data", "maps", map_name)
    if not os.path.isdir(game_map_dir):
        print()
        print(f"  {GOLD}Warning:{RST} Map folder '{map_name}' not found in game project.")
        print(f"  The snapshot may reference a map that no longer exists.")
        confirm = input(f"  Restore anyway? [y/N] > ").strip().lower()
        return confirm == "y"
    return True


# ============================================================
# UTILITY HANDLERS (unchanged)
# ============================================================

def _handle_fork(game_path, settings, proj_name):
    """Fork the current project. Returns new project name or None."""
    try:
        from torch.fork import fork_command
    except ImportError:
        print("  Fork is not available in this release.")
        input("  Press Enter > ")
        return None
    return fork_command([], game_path, settings, proj_name=proj_name)


def _handle_torch_backup(proj_name):
    """Create a TORCH package backup and display the list."""
    print()
    path = _create_torch_backup("manual", project_name=proj_name)
    print(f"  Backup created: {os.path.basename(path)}")
    print()
    _list_torch_backups(project_name=proj_name)
    print()
    input("  Press Enter to continue > ")
