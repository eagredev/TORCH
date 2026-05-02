"""Config Manager UI — projects, settings, advanced, view."""
# TORCH_MODULE: Config Manager
# TORCH_GROUP: Tools
import os
import sys
from datetime import datetime

from torch.config import (
    load_config, save_config, resolve_project,
    SETTINGS_DEFAULTS, SETTINGS_DESCRIPTIONS, DIVIDER, CONFIG_PATH,
    _nav_keys,
)
from torch.ui import print_logo, _set_terminal_title, _offer_build, _k, clear_screen
from torch.colours import GOLD, WHITE, CYAN, DIM, RST, BOLD_RED, DGOLD, BAR


def _config_projects_menu(workspace_parent, projects, settings, workspace, proj_name=None):
    """Project CRUD — list, switch, add, edit, remove projects."""

    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)

    selected = 0

    while True:
        clear_screen()
        print_logo("Config \u2014 Projects", proj_name)
        print(BAR)
        print(f"   {WHITE}PROJECTS{RST}")
        print(BAR)
        print()
        proj_list = list(projects.keys())
        favourite = settings.get("favourite_project", "")
        for i, name in enumerate(proj_list):
            path_display = projects[name]["game_path"].replace(os.path.expanduser("~"), "~")
            cursor = f"{GOLD}>>{RST}" if i == selected else "  "
            name_col = WHITE if i == selected else DIM
            fav_star = f" {GOLD}*{RST}" if name == favourite else ""
            print(f"  {cursor} {name_col}{name}{RST}{fav_star}")
            print(f"       {DIM}{path_display}{RST}")
            print()
        if favourite:
            print(f"  {GOLD}*{RST} {DIM}= favourite (auto-loaded on launch){RST}")
            print()
        print(BAR)
        print()
        print(f"  {_k(NK_OPEN)} {DIM}switch{RST}  "
              f"{_k('Enter')} {DIM}scroll{RST}  "
              f"{_k(NK_UP)} {DIM}up{RST}  {_k(NK_DOWN)} {DIM}down{RST}  "
              f"{_k('#')} {DIM}jump{RST}  "
              f"{_k('*')} {DIM}favourite{RST}  "
              f"{_k('a')} {DIM}add{RST}  {_k('e')} {DIM}edit{RST}  {_k('r')} {DIM}remove{RST}  {_k('q')} {DIM}back{RST}")
        print()
        raw = input(f"  {GOLD}>{RST} ").strip()

        if not raw:
            # Enter = scroll down with wrap
            if proj_list:
                selected = (selected + 1) % len(proj_list)
            continue

        cmd = raw.lower()

        if cmd == "q":
            return None

        if cmd == NK_SCROLL:
            # Secondary scroll key (same as Enter)
            if proj_list:
                selected = (selected + 1) % len(proj_list)
            continue

        if cmd == NK_UP:
            selected = max(0, selected - 1)
            continue

        if cmd == NK_DOWN:
            selected = min(len(proj_list) - 1, selected + 1)
            continue

        if cmd == NK_OPEN or cmd == "f":
            if proj_list:
                return ("switch", proj_list[selected])
            continue

        if cmd == "*":
            if not proj_list:
                continue
            target = proj_list[selected]
            current_fav = settings.get("favourite_project", "")
            if current_fav == target:
                # Toggle off
                settings["favourite_project"] = ""
                save_config(workspace_parent, projects, settings)
                print(f"  '{target}' is no longer the favourite.")
            else:
                settings["favourite_project"] = target
                save_config(workspace_parent, projects, settings)
                print(f"  '{target}' set as favourite. TORCH will auto-load it on launch.")
            input("  Press Enter > ")
            continue

        # Jump by number — move cursor; if already there, act
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(proj_list):
                if selected == idx:
                    return ("switch", proj_list[selected])
                selected = idx
            else:
                print(f"  No project #{raw}.")
                input("  Press Enter > ")
            continue

        choice = cmd
        if choice == "a":
            print()
            new_name = input("  Project name > ").strip()
            if not new_name:
                print("  Cancelled.")
                input("  Press Enter > ")
                continue
            if new_name in projects:
                print(f"  Project '{new_name}' already exists.")
                input("  Press Enter > ")
                continue
            new_path = input("  Game path (absolute) > ").strip()
            if not new_path:
                print("  Cancelled.")
                input("  Press Enter > ")
                continue
            new_path = os.path.expanduser(new_path)
            if not os.path.isdir(new_path):
                print(f"  Directory not found: {new_path}")
                input("  Press Enter > ")
                continue
            projects[new_name] = {"game_path": new_path}
            # Create workspace directory for new project
            new_proj_dir = os.path.join(workspace, new_name)
            os.makedirs(new_proj_dir, exist_ok=True)
            save_config(workspace_parent, projects, settings)
            print(f"  Project '{new_name}' added.")
            input("  Press Enter > ")
            continue

        if choice == "e":
            print()
            edit_idx = selected
            old_name = proj_list[edit_idx]
            print(f"  Editing: {old_name}")
            print()
            new_name = input(f"  New name (Enter to keep '{old_name}') > ").strip()
            if not new_name:
                new_name = old_name
            old_path = projects[old_name]["game_path"]
            old_path_display = old_path.replace(os.path.expanduser("~"), "~")
            new_path = input(f"  New game path (Enter to keep '{old_path_display}') > ").strip()
            if not new_path:
                new_path = old_path
            else:
                new_path = os.path.expanduser(new_path)
                if not os.path.isdir(new_path):
                    print(f"  Directory not found: {new_path}")
                    input("  Press Enter > ")
                    continue
            if new_name != old_name:
                if new_name in projects:
                    print(f"  A project named '{new_name}' already exists.")
                    input("  Press Enter > ")
                    continue
                del projects[old_name]
                # Rename workspace directory if it exists
                old_dir = os.path.join(workspace, old_name)
                new_dir = os.path.join(workspace, new_name)
                if os.path.isdir(old_dir) and not os.path.exists(new_dir):
                    os.rename(old_dir, new_dir)
            projects[new_name] = {"game_path": new_path}
            save_config(workspace_parent, projects, settings)
            print(f"  Project updated.")
            input("  Press Enter > ")
            continue

        if choice == "r":
            print()
            if len(proj_list) <= 1:
                print("  Cannot remove the last project.")
                input("  Press Enter > ")
                continue
            rm_name = proj_list[selected]
            confirm = input(f"  Remove '{rm_name}' from config? [y/N] > ").strip().lower()
            if confirm != "y":
                print("  Cancelled.")
                input("  Press Enter > ")
                continue
            del projects[rm_name]
            if settings.get("favourite_project", "") == rm_name:
                settings["favourite_project"] = ""
            save_config(workspace_parent, projects, settings)
            selected = max(0, selected - 1)
            print(f"  Project '{rm_name}' removed from config.")
            print("  (Workspace files were not deleted.)")
            input("  Press Enter > ")
            continue


def _config_advanced_menu(game_path, proj_name=None):
    """Advanced danger-zone options (migration rollback, etc.)."""


    migration_backup_dir = os.path.join(game_path, "backups", "migrations")
    while True:
        clear_screen()
        print_logo("Config \u2014 Advanced", proj_name)
        print(BAR)
        print(f"   {BOLD_RED}ADVANCED \u2014 DANGER ZONE{RST}")
        print(BAR)
        print()

        # Find migration backups
        backups = []
        if os.path.isdir(migration_backup_dir):
            backups = sorted([
                f for f in os.listdir(migration_backup_dir)
                if f.startswith("pre_migration_") and f.endswith(".zip")
            ])

        if backups:
            for bk in backups:
                bk_path = os.path.join(migration_backup_dir, bk)
                size_kb = os.path.getsize(bk_path) / 1024
                # Parse date from filename: pre_migration_YYYYMMDD_HHMMSS.zip
                date_str = bk.replace("pre_migration_", "").replace(".zip", "")
                try:
                    dt = datetime.strptime(date_str, "%Y%m%d_%H%M%S")
                    display_date = dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    display_date = date_str
                print(f"  {DIM}Migration backup:{RST} {CYAN}{bk}{RST}")
                print(f"    {DIM}Date:{RST} {display_date}   {DIM}Size:{RST} {size_kb:.1f} KB")
                print()
            print(f"  {_k('r')} {DIM}Restore pre-migration backup{RST}   {_k('d')} {DIM}Delete migration backup{RST}   {_k('Enter')} {DIM}Back{RST}")
        else:
            print("  No migration backups found.")
            print()
            print(f"  {_k('Enter')} {DIM}Back{RST}")
        print()
        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if not choice:
            return

        if choice == "r" and backups:
            latest = backups[-1]
            latest_path = os.path.join(migration_backup_dir, latest)
            print()
            print("  WARNING: This will OVERWRITE your current trainer files")
            print("  with the pre-migration backup.")
            print()
            c1 = input("  Continue? [y/N] > ").strip().lower()
            if c1 != "y":
                print("  Cancelled.")
                input("  Press Enter > ")
                continue
            print()
            c2 = input("  Type RESTORE to confirm > ").strip()
            if c2 != "RESTORE":
                print("  Cancelled.")
                input("  Press Enter > ")
                continue
            # Execute restore — lazy import to avoid circular dependency
            from torch.battle_migrator import _restore_migration_backup
            print()
            restored = _restore_migration_backup(game_path, latest_path)
            if restored is not None:
                print("  Restore complete. Files restored:")
                for r in restored:
                    print(f"    {r}")
                print()
                print("  WARNING: You must rebuild for these changes to take effect.")
                _offer_build(game_path)
            print()
            input("  Press Enter > ")
            continue

        if choice == "d" and backups:
            latest = backups[-1]
            latest_path = os.path.join(migration_backup_dir, latest)
            print()
            c = input(f"  Delete {latest}? [y/N] > ").strip().lower()
            if c == "y":
                os.remove(latest_path)
                print("  Deleted.")
            else:
                print("  Cancelled.")
            input("  Press Enter > ")
            continue


def _config_settings_menu(workspace_parent, projects, settings, game_path=None, proj_name=None):
    """Edit tunable settings."""


    keys = list(SETTINGS_DEFAULTS.keys())
    selected = 0
    scroll_offset = 0
    MAX_VISIBLE = 8

    def _edit_setting(idx):
        key = keys[idx]
        default = SETTINGS_DEFAULTS[key]
        current = settings[key]
        desc = SETTINGS_DESCRIPTIONS[key]
        if isinstance(default, bool):
            settings[key] = not current
            save_config(workspace_parent, projects, settings)
            new_str = "ON" if settings[key] else "OFF"
            print(f"  {key} set to {new_str}.")
            input("  Press Enter > ")
            return
        if isinstance(default, str):
            # favourite_project is set from the Projects menu, not editable directly
            if key == "favourite_project":
                val = settings.get(key, "")
                if val:
                    print(f"  favourite_project = '{val}'")
                    print()
                    print("  To change, go to Config > Projects and press [*] on a project.")
                    print("  To clear: set the current favourite as favourite again (toggles off).")
                else:
                    print("  No favourite project set.")
                    print()
                    print("  Go to Config > Projects and press [*] on a project to set one.")
                input("  Press Enter > ")
                return
            # Special handling for editor_context (choice from fixed values)
            if key == "editor_context":
                options = ["compact", "detail", "off"]
                print()
                print(f"  {key}: {desc}")
                print(f"  Current: '{current}'  (default: '{default}')")
                for oi, opt in enumerate(options, 1):
                    marker = " *" if opt == current else ""
                    print(f"    [{oi}] {opt}{marker}")
                raw = input(f"  Choice (Enter to cancel) > ").strip()
                if not raw:
                    print("  Cancelled.")
                    input("  Press Enter > ")
                    return
                try:
                    chosen = options[int(raw) - 1]
                    settings[key] = chosen
                    save_config(workspace_parent, projects, settings)
                    print(f"  {key} set to '{chosen}'.")
                except (ValueError, IndexError):
                    print("  Invalid choice.")
                input("  Press Enter > ")
                return
            # Nav key settings (single char)
            print()
            print(f"  {key}: {desc}")
            print(f"  Current: '{current}'  (default: '{default}')")
            raw = input(f"  New key (single char, Enter to cancel) > ").strip()
            if not raw:
                print("  Cancelled.")
                input("  Press Enter > ")
                return
            if len(raw) != 1 or not raw.isalpha():
                print("  Must be a single letter.")
                input("  Press Enter > ")
                return
            settings[key] = raw.lower()
            save_config(workspace_parent, projects, settings)
            print(f"  {key} set to '{raw.lower()}'.")
            input("  Press Enter > ")
            return
        print()
        print(f"  {key}: {desc}")
        print(f"  Current: {current}  (default: {default})")
        raw = input(f"  New value (Enter to cancel) > ").strip()
        if not raw:
            print("  Cancelled.")
            input("  Press Enter > ")
            return
        try:
            new_val = int(raw)
            if new_val < 1:
                print("  Value must be at least 1.")
                input("  Press Enter > ")
                return
            settings[key] = new_val
            save_config(workspace_parent, projects, settings)
            print(f"  {key} set to {new_val}.")
        except ValueError:
            print("  Please enter a number.")
        input("  Press Enter > ")

    while True:
        clear_screen()
        print_logo("Config \u2014 Preferences", proj_name)
        print(BAR)
        print(f"   {WHITE}PREFERENCES{RST}")
        print(BAR)
        print()

        # Keep scroll window centred on selection
        if selected < scroll_offset:
            scroll_offset = selected
        if selected >= scroll_offset + MAX_VISIBLE:
            scroll_offset = selected - MAX_VISIBLE + 1

        if scroll_offset > 0:
            print(f"  {DIM}  \u2191 {scroll_offset} more above{RST}")
        end = min(scroll_offset + MAX_VISIBLE, len(keys))
        for i in range(scroll_offset, end):
            key = keys[i]
            val = settings[key]
            default = SETTINGS_DEFAULTS[key]
            desc = SETTINGS_DESCRIPTIONS[key]
            modified = val != default
            if isinstance(default, bool):
                val_str = "ON" if val else "OFF"
            elif key == "favourite_project":
                val_str = val if val else "(none)"
            else:
                val_str = str(val)
            marker = f" {DGOLD}*{RST}" if modified else ""
            val_col = CYAN if modified else DIM
            cursor = f"{GOLD}>>{RST}" if i == selected else "  "
            name_col = WHITE if i == selected else DIM
            print(f"  {cursor} {name_col}{key:<25}{RST} {val_col}{val_str}{RST}{marker}")
            print(f"       {DIM}{desc}{RST}")
            print()
        remaining = len(keys) - end
        if remaining > 0:
            print(f"  {DIM}  \u2193 {remaining} more below{RST}")
            print()

        print(f"  {_k('v')} {DIM}edit{RST}  "
              f"{_k('u')} {DIM}up{RST}  {_k('j')}/{_k('Enter')} {DIM}down{RST}  "
              f"{_k('#')} {DIM}jump{RST}  "
              f"{_k('d')} {DIM}reset all{RST}  {_k('a')} {DIM}advanced{RST}  {_k('q')} {DIM}back{RST}")
        print()
        raw = input(f"  {GOLD}>{RST} ").strip()

        if not raw:
            selected = min(len(keys) - 1, selected + 1)
            continue

        cmd = raw.lower()

        if cmd == "q":
            return

        if cmd in ("u", "k"):
            selected = max(0, selected - 1)
            continue

        if cmd in ("j",):
            selected = min(len(keys) - 1, selected + 1)
            continue

        if cmd == "v":
            _edit_setting(selected)
            continue

        if cmd == "a":
            if game_path:
                _config_advanced_menu(game_path, proj_name=proj_name)
            else:
                print("  Advanced options require a loaded project.")
                input("  Press Enter > ")
            continue

        if cmd == "d":
            confirm = input("  Reset all settings to defaults? [y/N] > ").strip().lower()
            if confirm == "y":
                for key in SETTINGS_DEFAULTS:
                    settings[key] = SETTINGS_DEFAULTS[key]
                save_config(workspace_parent, projects, settings)
                print("  All settings reset to defaults.")
            else:
                print("  Cancelled.")
            input("  Press Enter > ")
            continue

        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(keys):
                selected = idx
                _edit_setting(selected)
            else:
                print(f"  No setting #{raw}.")
                input("  Press Enter > ")
            continue


def _config_view(workspace_parent, projects, settings, proj_name=None):
    """Read-only config summary."""

    clear_screen()
    print_logo("Config \u2014 View", proj_name)
    print(BAR)
    print(f"   {WHITE}CONFIG FILE{RST}")
    print(BAR)
    print()
    config_display = CONFIG_PATH.replace(os.path.expanduser("~"), "~")
    print(f"  {DIM}Path:{RST}      {CYAN}{config_display}{RST}")
    print()
    print(f"  {DIM}Workspace:{RST} {CYAN}{workspace_parent}{RST}")
    print()
    print(f"  {WHITE}Projects:{RST}")
    for name, info in projects.items():
        path_display = info["game_path"].replace(os.path.expanduser("~"), "~")
        print(f"    {CYAN}{name}{RST}  {DIM}->{RST}  {path_display}")
    print()
    print(f"  {WHITE}Preferences:{RST}")
    for key in SETTINGS_DEFAULTS:
        val = settings[key]
        default = SETTINGS_DEFAULTS[key]
        modified = val != default
        marker = f"  {DGOLD}(modified){RST}" if modified else ""
        val_col = CYAN if modified else DIM
        print(f"    {DIM}{key}{RST} = {val_col}{val}{RST}{marker}")
    print()
    print(BAR)
    print()
    input("  Press Enter to go back > ")


def config_manager_menu(workspace_parent, projects, settings, workspace, game_path=None, proj_name=None):
    """Config hub — project switching, CRUD, settings."""


    def _menu_row(key, name, desc):
        return f"  {_k(key)} {WHITE}{name:<16}{RST}  {DIM}{desc}{RST}"
    while True:
        clear_screen()
        _set_terminal_title("TORCH \u2014 Config")
        print_logo("Config", proj_name)
        print(BAR)
        print(f"   {WHITE}CONFIG{RST}")
        print(BAR)
        print()
        print(_menu_row("1", "Projects",    "Switch, add, edit or remove projects"))
        print(_menu_row("2", "Preferences", "Tune snapshot limits, page sizes & more"))
        print(_menu_row("3", "View Config", "Show current config file summary"))
        print()
        print(f"  {_k('q')} {DIM}Back{RST}")
        print()
        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if choice in ("q", ""):
            return None

        if choice == "1":
            result = _config_projects_menu(workspace_parent, projects, settings, workspace, proj_name=proj_name)
            if result and result[0] == "switch":
                return result

        elif choice == "2":
            _config_settings_menu(workspace_parent, projects, settings, game_path=game_path, proj_name=proj_name)

        elif choice == "3":
            _config_view(workspace_parent, projects, settings, proj_name=proj_name)

        else:
            print("  Invalid choice.")
