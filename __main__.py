"""
TORCH — The Open ROM Creation Hub for pokeemerald-expansion.

Compiles simplified script notation (.txt) into Poryscript (.pory),
then syncs assembled scripts into the game's map folders.

Usage:
    torch init                   First-time setup (creates ~/.config/torch/torch.conf)
    torch update [source]        Update TORCH from a stable release zip
    torch <script_name>          Compile a single .txt file (standalone)
    torch sync [MapName]         Sync workspace to game folder
    torch build                  Build ROM with auto-sync and error diagnosis
    torch restore                Restore from a verified build snapshot
    torch restore <MapName>      Restore from a workspace snapshot
    torch backup [tag]           Backup torch.py with tiered retention
    torch backup list            Show all torch.py backups with tier labels
    torch backup prune           Prune backups according to retention policy
    torch script                 Script Studio — browse and edit map scripts
    torch scene                  Script Studio (alias for torch script)
    torch map                    Script Studio (alias for torch script)
    torch status                 Show enrolled maps with health indicators
    torch enroll [MapName|--all] Enroll maps in the registry
    torch unenroll <MapName>     Remove a map from the registry
    torch scorch                 SCORCH — scan & remove vanilla content
    torch scorch <category>      Category-specific removal (maps, trainers, etc.)
    torch scorch report          Scan-only report
    torch scorch restore         Restore from SCORCH snapshot
    torch scorch phoenix         Phoenix — remove ALL vanilla maps/trainers/encounters
    torch scorch phoenix plan    Phoenix dry-run report
    torch scorch phoenix restore Restore from Phoenix snapshot
    torch wild                   Encounter Editor — edit wild Pokemon encounters
    torch tweak                  Settings — browse and edit game settings
    torch settings               Settings (alias for torch tweak)
    torch dex                    Dex — browse & look up Pokemon data
    torch heal                   Heal Location Manager — edit heal locations
    torch assets                 Asset Manager — import custom game assets
    torch items                  Item Editor — browse and edit game items
    torch learnsets              Learnset Editor — view & edit Pokemon learnsets
    torch tileset                Tileset Assistant — create & manage tilesets
    torch explore                Map Explorer — browse connectivity & find paths
    torch explore <MapName>      Map detail view for a specific map
    torch new                    Create a fresh project from GitHub
    torch upgrade                Upgrade pokeemerald-expansion to a newer version
    torch upgrade --check        Show current version and available updates
    torch upgrade --to X.Y.Z    Upgrade to a specific version
    torch gui                    Launch the TORCH web GUI in your browser
"""
# TORCH_MODULE: Entry Point
# TORCH_GROUP: Core

import sys
import os
import importlib.util

# Ensure the parent directory (containing the torch_dev package) is on sys.path.
# Also register torch_dev as 'torch' in sys.modules so that internal
# `from torch.xxx import ...` statements resolve to torch_dev's modules.
_this_dir = os.path.dirname(os.path.realpath(os.path.abspath(__file__)))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
# Pre-register the package under the 'torch' name before any imports.
import importlib
_pkg = importlib.import_module("torch_dev")  # TORCH_PKG: torch_dev
if "torch" not in sys.modules:
    sys.modules["torch"] = _pkg

from torch.colours import GOLD, WHITE, CYAN, GREEN, RED, DIM, RST, BAR

# ── Core imports — always required ──────────────────────────────────────────
from torch.config import load_config, resolve_project
from torch.ui import print_logo, _set_terminal_title, _offer_build, _k, _get_auto_build_setting, clear_screen
from torch.init import init_command
from torch.backup import (
    _list_torch_backups, _prune_torch_backups, _create_torch_backup,
    TORCH_BACKUP_DIR,
)
from torch.compiler import compile_script
from torch.sync import sync_map, sync_all, restore_map

# ── Optional module availability — checked once at startup ───────────────────
# Check the package directory directly, not sys.path.  This ensures that
# modules absent from an experimental/partial install are never shown, even
# if stale .py files from a previous install still exist on disk elsewhere.

_PACKAGE_DIR = os.path.dirname(os.path.realpath(os.path.abspath(__file__)))

def _module_available(name):
    """Return True if the module's .py file exists in this package's directory.

    name must be a dotted torch.xxx name; only the leaf filename is checked.
    """
    leaf = name.split(".")[-1] + ".py"
    return os.path.isfile(os.path.join(_PACKAGE_DIR, leaf))

_HAS_STUDIO   = _module_available("torch.studio")
_HAS_SCRIPT   = _module_available("torch.script_hub")
_HAS_BATTLE   = _module_available("torch.battle_manager")
_HAS_VAULT    = _module_available("torch.vault")
_HAS_CONFIG   = _module_available("torch.config_ui")
_HAS_REGISTRY = _module_available("torch.registry")
_HAS_CLEANUP  = _module_available("torch.cleanup")
_HAS_SCORCH   = _module_available("torch.scorch")
_HAS_VERIFIED = _module_available("torch.verified_snapshots")
_HAS_FORK     = _module_available("torch.fork")
_HAS_SANDBOX  = _HAS_FORK  # backward compat
_HAS_NEW_PROJECT = _module_available("torch.new_project")
_HAS_UPGRADE    = _module_available("torch.upgrade")
_HAS_ENCOUNTER  = _module_available("torch.encounter_editor")
_HAS_TUNER      = _module_available("torch.config_tuner")
_HAS_DEX        = _module_available("torch.dex")
_HAS_HEAL       = _module_available("torch.heal_locations")
_HAS_ASSET      = _module_available("torch.asset_manager")
_HAS_NPC        = _module_available("torch.npc_editor")
_HAS_ITEM       = _module_available("torch.item_editor")
_HAS_MOVE       = _module_available("torch.move_editor")
_HAS_LEARNSET   = _module_available("torch.learnset_editor")
_HAS_TILESET    = _module_available("torch.tileset_assistant")
_HAS_EXPLORE    = _module_available("torch.map_explorer")
_HAS_COMPAT     = _module_available("torch.expansion_compat")
_HAS_DECOMPILER = _module_available("torch.decompiler")
_HAS_TEMPLATE   = _module_available("torch.template_stamper")
_HAS_WEB        = os.path.isdir(os.path.join(_PACKAGE_DIR, "web"))
_IS_DEV = _pkg.BUILD_TRACK == "dev"

# ── Build switcher ───────────────────────────────────────────────────────────

ACTIVE_BUILD_PATH = os.path.expanduser("~/.config/torch/active_build.txt")


def _detect_other_builds():
    """Return list of (key, label, track) for each other installed build.

    Keys are assigned in order: 'x' for the first, 'y' for the second.
    Dev build (~/.torch_dev/) is offered when not currently running it.
    """
    stable_dir = os.path.expanduser("~/torch_stable")
    exp_dir    = os.path.expanduser("~/torch_exp")
    dev_dir    = os.path.expanduser("~/torch_dev")
    current    = os.path.realpath(_PACKAGE_DIR)

    candidates = []
    # Offer other installed builds depending on which one we're running
    if current == os.path.realpath(stable_dir):
        if os.path.isfile(os.path.join(exp_dir, "__init__.py")):
            candidates.append(("experimental", "experimental"))
    elif current == os.path.realpath(exp_dir):
        if os.path.isfile(os.path.join(stable_dir, "__init__.py")):
            candidates.append(("stable", "stable"))
    elif current == os.path.realpath(dev_dir):
        if os.path.isfile(os.path.join(stable_dir, "__init__.py")):
            candidates.append(("stable", "stable"))
        if os.path.isfile(os.path.join(exp_dir, "__init__.py")):
            candidates.append(("experimental", "experimental"))

    # Offer dev if installed and not currently running it
    if current != os.path.realpath(dev_dir):
        if os.path.isfile(os.path.join(dev_dir, "__init__.py")):
            candidates.append(("dev", "dev"))

    keys = ["x", "y"]
    return [(keys[i], label, track) for i, (track, label) in enumerate(candidates)]


def _switch_build(track):
    """Write active_build.txt and re-exec the launcher so the new build starts fresh."""
    os.makedirs(os.path.dirname(ACTIVE_BUILD_PATH), exist_ok=True)
    with open(ACTIVE_BUILD_PATH, "w") as f:
        f.write(track + "\n")
    launcher = os.path.expanduser("~/torch_launcher.py")
    if os.path.isfile(launcher):
        os.execv(sys.executable, [sys.executable, launcher])
    else:
        print(f"  Switched to {track}. Run `torch` to start it.")
        sys.exit(0)


# ── Menu option handlers ────────────────────────────────────────────────────


def _menu_studio(project_dir, game_path, emotes_conf, source_display,
                 settings, proj_name, workspace_expanded=""):
    """Handle menu option [1] Studio."""
    if not _HAS_SCRIPT:
        print("  Studio is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.script_hub import script_builder_menu
    except ImportError:
        print("  Studio is not available in this release.")
        input("  Press Enter > ")
        return
    script_builder_menu(project_dir, game_path, emotes_conf, source_display,
                       settings, proj_name=proj_name)


def _menu_map_studio(project_dir, game_path, emotes_conf, source_display,
                     settings, proj_name):
    """Handle menu option [1] Map Studio (deprecated wrapper)."""
    _menu_studio(project_dir, game_path, emotes_conf, source_display,
                 settings, proj_name)


def _menu_game_settings(project_dir, game_path, workspace_expanded, settings,
                        emotes_conf, source_display, proj_name):
    """Handle menu option [3] Game Settings."""
    while True:
        clear_screen()
        print_logo("Game Settings", proj_name)
        print(BAR)
        print()
        print(f"  {_k('1')} {WHITE}Expansion Options{RST}  {DIM}Battle, species & overworld toggles{RST}")
        print(f"  {_k('2')} {WHITE}ROM Metadata{RST}       {DIM}Title, game code, filename{RST}")
        print(f"  {_k('3')} {WHITE}Tilesets{RST}            {DIM}Create & manage custom tilesets{RST}")
        print(f"  {_k('4')} {WHITE}Assets{RST}             {DIM}Import sprites, music & sounds{RST}")
        print()
        print(f"  {_k('q')} {DIM}Back{RST}")
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if raw == "q" or raw == "":
            return
        elif raw == "1":
            _menu_settings(project_dir, game_path, workspace_expanded,
                           settings, emotes_conf, source_display, proj_name)
        elif raw == "2":
            _cmd_studio(game_path, settings, proj_name)
        elif raw == "3":
            _menu_tileset(game_path, settings, proj_name)
        elif raw == "4":
            _menu_assets(game_path, settings, proj_name, workspace_expanded)


def _menu_project(project_dir, game_path, emotes_conf, source_display,
                  settings, proj_name, workspace_expanded):
    """Handle menu option [4] Project. Returns switch tuple or None."""
    while True:
        clear_screen()
        print_logo("Project", proj_name)
        print(BAR)
        print()
        print(f"  {_k('1')} {WHITE}Backups{RST}          {DIM}Build & workspace snapshots{RST}")
        print(f"  {_k('2')} {WHITE}SCORCH{RST}           {DIM}Remove vanilla content{RST}")
        print(f"  {_k('3')} {WHITE}Upgrade{RST}          {DIM}Update expansion version{RST}")
        print(f"  {_k('4')} {WHITE}Fork{RST}             {DIM}Create project copies{RST}")
        print(f"  {_k('5')} {WHITE}New Project{RST}      {DIM}Clone from GitHub{RST}")
        print(f"  {_k('6')} {WHITE}Map Registry{RST}     {DIM}Enroll maps, view status{RST}")
        print(f"  {_k('7')} {WHITE}Versions{RST}         {DIM}Game version control{RST}")
        print()
        print(f"  {_k('q')} {DIM}Back{RST}")
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw == "q" or raw == "":
            return None
        elif raw == "1":
            switch_result = _menu_vault(project_dir, game_path, emotes_conf,
                                        source_display, settings, proj_name,
                                        workspace_expanded)
            if switch_result:
                return switch_result
        elif raw == "2":
            _menu_scorch(game_path, settings, proj_name)
        elif raw == "3":
            _menu_upgrade(game_path, settings, proj_name)
        elif raw == "4":
            new_proj = _menu_fork(game_path, settings, proj_name)
            if new_proj:
                return ("fork", new_proj)
        elif raw == "5":
            new_proj = _menu_new(settings)
            if new_proj:
                return ("new", new_proj)
        elif raw == "6":
            _menu_registry(project_dir, game_path)
        elif raw == "7":
            try:
                from torch.game_versions import versions_menu
                versions_menu(game_path, project_dir, settings, proj_name)
            except ImportError:
                print("  Game Version Control is not available.")
                input("  Press Enter > ")


def _menu_registry(project_dir, game_path):
    """Handle Project > Map Registry."""
    _cmd_status(project_dir, game_path)
    input(f"  {DIM}Press Enter to return{RST} > ")


def _menu_trainers(project_dir, game_path, workspace_expanded, settings,
                   emotes_conf, source_display, proj_name):
    """Handle menu option [3] Trainers."""
    if not _HAS_BATTLE:
        print("  Trainers is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.battle_manager import battle_command
    except ImportError:
        print("  Trainers is not available in this release.")
        input("  Press Enter > ")
        return
    battle_command([], project_dir, game_path, workspace_expanded, settings,
                   emotes_conf=emotes_conf, source_display=source_display,
                   proj_name=proj_name)


def _menu_vault(project_dir, game_path, emotes_conf, source_display,
                settings, proj_name, workspace_expanded=""):
    """Handle menu option [4] TORCH Vault. Returns switch tuple or None."""
    if not _HAS_VAULT:
        print("  TORCH Vault is not available in this release.")
        input("  Press Enter > ")
        return None
    try:
        from torch.vault import backup_manager_menu
    except ImportError:
        print("  TORCH Vault is not available in this release.")
        input("  Press Enter > ")
        return None
    result = backup_manager_menu(project_dir, game_path, emotes_conf, source_display,
                                 settings, proj_name=proj_name)
    if result and result[0] == "fork" and workspace_expanded:
        new_proj = result[1]
        cfg = load_config()
        if cfg:
            _, projects, _ = cfg
            if new_proj in projects:
                new_info = projects[new_proj]
                new_project_dir = os.path.join(workspace_expanded, new_proj)
                new_game_path = os.path.expanduser(new_info["game_path"])
                new_source_display = f"{workspace_expanded}/{new_proj}"
                return (new_proj, new_info, new_project_dir, new_game_path,
                        new_source_display)
    return None


def _menu_scorch(game_path, settings, proj_name):
    """Handle menu option [5] SCORCH."""
    if not _HAS_CLEANUP:
        print("  SCORCH is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.cleanup import cleanup_command
    except ImportError:
        print("  SCORCH is not available in this release.")
        input("  Press Enter > ")
        return
    cleanup_command(game_path, settings, proj_name=proj_name)


def _menu_encounters(project_dir, game_path, workspace_expanded, settings,
                     emotes_conf, source_display, proj_name):
    """Handle menu option [6] Encounters."""
    if not _HAS_ENCOUNTER:
        print("  Encounter Editor is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.encounter_editor import encounter_command
    except ImportError:
        print("  Encounter Editor is not available in this release.")
        input("  Press Enter > ")
        return
    encounter_command([], project_dir, game_path, workspace_expanded, settings,
                      emotes_conf=emotes_conf, source_display=source_display,
                      proj_name=proj_name)


def _menu_settings(project_dir, game_path, workspace_expanded, settings,
                   emotes_conf, source_display, proj_name):
    """Handle menu option [5] Settings."""
    if not _HAS_TUNER:
        print("  Settings is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.config_tuner import config_command
    except ImportError:
        print("  Settings is not available in this release.")
        input("  Press Enter > ")
        return
    config_command([], project_dir, game_path, workspace_expanded, settings,
                   emotes_conf=emotes_conf, source_display=source_display,
                   proj_name=proj_name)


def _menu_dex(project_dir, game_path, workspace_expanded, settings,
              emotes_conf, source_display, proj_name):
    """Handle menu option [8] Dex."""
    if not _HAS_DEX:
        print("  Dex is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.dex import dex_command
    except ImportError:
        print("  Dex is not available in this release.")
        input("  Press Enter > ")
        return
    dex_command([], project_dir, game_path, workspace_expanded, settings,
                    emotes_conf=emotes_conf, source_display=source_display,
                    proj_name=proj_name)


def _menu_assets(game_path, settings, proj_name, workspace_expanded):
    """Handle menu option [a] Assets."""
    if not _HAS_ASSET:
        print("  Asset Manager is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.asset_manager import assets_command
    except ImportError:
        print("  Asset Manager is not available in this release.")
        input("  Press Enter > ")
        return
    assets_command(game_path, settings, proj_name=proj_name,
                   workspace_expanded=workspace_expanded)


def _menu_items(game_path, settings, proj_name):
    """Handle menu option [i] Items."""
    if not _HAS_ITEM:
        print("  Item Editor is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.item_editor import item_editor_menu
    except ImportError:
        print("  Item Editor is not available in this release.")
        input("  Press Enter > ")
        return
    item_editor_menu(game_path, settings=settings, proj_name=proj_name)


def _menu_moves(game_path, settings, proj_name):
    """Handle menu option [m] Moves."""
    if not _HAS_MOVE:
        print("  Move Editor is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.move_editor import move_editor_menu
    except ImportError:
        print("  Move Editor is not available in this release.")
        input("  Press Enter > ")
        return
    move_editor_menu(game_path, settings=settings, proj_name=proj_name)


def _menu_learnsets(game_path, settings, proj_name):
    """Handle menu option [l] Learnsets."""
    if not _HAS_LEARNSET:
        print("  Learnset Editor is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.learnset_editor import learnset_editor_menu
    except ImportError:
        print("  Learnset Editor is not available in this release.")
        input("  Press Enter > ")
        return
    learnset_editor_menu(game_path, settings=settings, proj_name=proj_name)


def _menu_tileset(game_path, settings, proj_name):
    """Handle menu option [t] Tilesets."""
    if not _HAS_TILESET:
        print("  Tileset Assistant is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.tileset_assistant import tileset_assistant_menu
    except ImportError:
        print("  Tileset Assistant is not available in this release.")
        input("  Press Enter > ")
        return
    tileset_assistant_menu(game_path, settings=settings, proj_name=proj_name)


def _menu_explore(game_path, settings, proj_name):
    """Handle menu option [e] Map Explorer."""
    if not _HAS_EXPLORE:
        print("  Map Explorer is not available in this release.")
        input("  Press Enter > ")
        return
    try:
        from torch.map_explorer import map_explorer_menu
    except ImportError:
        print("  Map Explorer is not available in this release.")
        input("  Press Enter > ")
        return
    map_explorer_menu(game_path, settings, proj_name=proj_name)


def _menu_fork(game_path, settings, proj_name):
    """Handle menu option [f] Fork. Returns new project name or None."""
    if not _HAS_FORK:
        print("  Fork is not available in this release.")
        input("  Press Enter > ")
        return None
    try:
        from torch.fork import fork_command
    except ImportError:
        print("  Fork is not available in this release.")
        input("  Press Enter > ")
        return None
    return fork_command([], game_path, settings, proj_name=proj_name)


def _menu_new(settings):
    """Handle menu option [n] New Project. Returns new project name or None."""
    if not _HAS_NEW_PROJECT:
        print("  New Project is not available in this release.")
        input("  Press Enter > ")
        return None
    try:
        from torch.new_project import new_project_command
    except ImportError:
        print("  New Project is not available in this release.")
        input("  Press Enter > ")
        return None
    return new_project_command([], settings)


def _menu_restore(game_path):
    """Handle menu option [r] Restore from verified build snapshot."""
    if not _HAS_VERIFIED:
        print("  Verified Build Snapshots not available.")
        input("  Press Enter > ")
        return
    from torch.verified_snapshots import list_verified_snapshots, restore_verified_snapshot
    snapshots = list_verified_snapshots(game_path)
    if not snapshots:
        print()
        print("  No verified build snapshots found.")
        print("  Build through TORCH to create one.")
        input(f"\n  {DIM}Press Enter to return{RST} > ")
        return
    print()
    print("  Verified build snapshots:")
    print()
    for i, snap in enumerate(snapshots):
        marker = ">> " if i == 0 else "   "
        print(f"  {marker}{i + 1}.  {snap['display_time']}    [{snap['trigger']}]")
        print(f"       {snap['file_count']} files  --  {snap['size_mb']:.1f} MB")
        print()
    try:
        snap_choice = input("  Restore which snapshot? [1] > ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    idx = 0
    if snap_choice.isdigit():
        idx = int(snap_choice) - 1
    elif snap_choice == "":
        idx = 0
    else:
        print("  Cancelled.")
        input(f"\n  {DIM}Press Enter to return{RST} > ")
        return
    if not (0 <= idx < len(snapshots)):
        print(f"  No snapshot #{idx + 1}.")
        input(f"\n  {DIM}Press Enter to return{RST} > ")
        return
    snap = snapshots[idx]
    restored = restore_verified_snapshot(game_path, snap["path"])
    if restored:
        print(f"  Restored {len(restored)} files from verified snapshot.")
        print()
        _offer_build(game_path, trigger="verified-restore")
    input(f"\n  {DIM}Press Enter to return{RST} > ")


def _menu_config(workspace_parent, projects, settings, workspace_expanded,
                 game_path, proj_name):
    """Handle menu option [c] Config. Returns (proj_name, proj_info, project_dir, game_path, source_display) or None."""
    if not _HAS_CONFIG:
        print("  Config Manager is not available in this release.")
        input("  Press Enter > ")
        return None
    try:
        from torch.config_ui import config_manager_menu
    except ImportError:
        print("  Config Manager is not available in this release.")
        input("  Press Enter > ")
        return None
    result = config_manager_menu(workspace_parent, projects, settings,
                                 workspace_expanded, game_path=game_path,
                                 proj_name=proj_name)
    if result and result[0] == "switch":
        new_proj_name = result[1]
        new_proj_info = projects[new_proj_name]
        new_project_dir = os.path.join(workspace_expanded, new_proj_name)
        new_game_path = os.path.expanduser(new_proj_info["game_path"])
        new_source_display = f"{workspace_expanded}/{new_proj_name}"
        return (new_proj_name, new_proj_info, new_project_dir, new_game_path,
                new_source_display)
    return None


def _menu_upgrade(game_path, settings, proj_name):
    """Handle menu option [u] Upgrade."""
    if not _HAS_UPGRADE:
        print("  Expansion Upgrade is not available in this release.")
        input(f"\n  {DIM}Press Enter to return{RST} > ")
        return
    try:
        from torch.upgrade import _upgrade_wizard
    except ImportError:
        print("  Expansion Upgrade is not available.")
        input(f"\n  {DIM}Press Enter to return{RST} > ")
        return
    _upgrade_wizard(game_path, settings, proj_name)


def _menu_sync(project_dir, game_path, emotes_conf, source_display, settings):
    """Handle menu option [s] Sync."""
    sync_all(project_dir, game_path, emotes_conf, source_display,
             settings["max_snapshots"])
    input(f"\n  {DIM}Press Enter to return{RST} > ")


def _menu_build(game_path, project_dir, emotes_conf, source_display, settings):
    """Handle menu option [b] Build."""
    _offer_build(
        game_path=game_path,
        trigger="auto",
        safe=False,
        auto_build=False,
        project_dir=project_dir,
        emotes_conf=emotes_conf,
        source_display=source_display,
        max_snapshots=settings["max_snapshots"],
    )


def _menu_help(proj_name, BAR):
    """Handle menu option [?] Help."""
    clear_screen()
    print_logo(proj_name)
    print(BAR)
    print(f"  {WHITE}GETTING STARTED{RST}")
    print(BAR)
    print()
    print(f"  TORCH is a toolkit for pokeemerald-expansion ROM hacks.")
    print()
    print(f"  {GOLD}Main Menu{RST}")
    print(f"    {_k('1')} {WHITE}{'Studio':<14}{RST} {DIM}Maps, trainers, items, scripts, encounters{RST}")
    print(f"    {_k('2')} {WHITE}{'Dex':<14}{RST} {DIM}Pokemon species, moves & learnsets{RST}")
    print(f"    {_k('3')} {WHITE}{'Game Settings':<14}{RST} {DIM}Expansion options, ROM, tilesets, assets{RST}")
    print(f"    {_k('4')} {WHITE}{'Project':<14}{RST} {DIM}Backups, SCORCH, fork, upgrade{RST}")
    print()
    print(f"  {GOLD}Quick Actions{RST}")
    print(f"    {_k('b')} {WHITE}{'Build':<14}{RST} {DIM}Build ROM with auto-sync{RST}")
    print(f"    {_k('r')} {WHITE}{'Restore':<14}{RST} {DIM}Restore from verified snapshot{RST}")
    print(f"    {_k('c')} {WHITE}{'Config':<14}{RST} {DIM}Manage projects & preferences{RST}")
    print()
    print(f"  {GOLD}Navigation{RST}")
    print(f"    {DIM}u/j = navigate up/down   Enter = scroll   q = back{RST}")
    print()
    print(f"  {GOLD}First Time?{RST}")
    print(f"    {DIM}Run{RST} {CYAN}torch init{RST} {DIM}to set up your project.{RST}")
    print(f"    {DIM}User guide:{RST} {CYAN}~/ROMHacking/TORCH/guide.md{RST}")
    print()
    print(BAR)
    input(f"  {DIM}Press Enter to return{RST} > ")


def _render_info_panel(game_path, project_dir, BAR, _info_row, _info_row2,
                       expansion_version=None):
    """Render the project info panel below the logo."""
    from torch.names import _detect_project_variant
    variant = _detect_project_variant(game_path)
    if _HAS_COMPAT and expansion_version:
        from torch.expansion_compat import version_str
        ver_display = f"v{version_str(expansion_version)}"
    else:
        ver_display = None
    if _HAS_STUDIO:
        try:
            from torch.studio import _read_project_info
            pinfo = _read_project_info(game_path, project_dir)
            print(BAR)
            print(_info_row2("ROM Title :", pinfo['title'], "Game Code :", pinfo['game_code']))
            print(_info_row2("Filename  :", pinfo['rom_name'], "Revision  :", pinfo['revision']))
            if ver_display:
                print(_info_row2("Project   :", variant, "Version   :", ver_display))
            else:
                print(_info_row("Project   :", variant))
            print(_info_row("Game Path :", pinfo['game_path_display']))
            maps = pinfo['map_count']
            scripts = pinfo['script_count']
            enrolled = pinfo.get('enrolled_count', 0)
            ws_val = (f"{maps} map{'s' if maps != 1 else ''}, "
                      f"{scripts} script{'s' if scripts != 1 else ''}, "
                      f"{enrolled} enrolled")
            print(_info_row("Workspace :", ws_val, value_colour=GREEN))
            print(BAR)
        except Exception:
            print(BAR)
            if ver_display:
                print(_info_row2("Project   :", variant, "Version   :", ver_display))
            else:
                print(_info_row("Project   :", variant))
            print(_info_row("Game Path :", game_path))
            print(BAR)
    else:
        print(BAR)
        if ver_display:
            print(_info_row2("Project   :", variant, "Version   :", ver_display))
        else:
            print(_info_row("Project   :", variant))
        print(_info_row("Game Path :", game_path))
        print(BAR)


def _render_menu_options(_menu_row, other_builds):
    """Render the module options, action shortcuts, and footer."""
    print()
    for group_name, items in _MENU_GROUPS:
        if group_name:
            print(f"  {DIM}{group_name}{RST}")
        for key, label, desc_line1, desc_line2, available, *_ in items:
            if available:
                # Two-line description: name + first desc line, then indented second line
                pad = 16  # alignment width for label column
                print(f"  {_k(key)} {WHITE}{label:<{pad}}{RST}  {DIM}{desc_line1}{RST}")
                indent = 2 + 3 + 1 + pad + 2  # "  " + "[k]" + " " + label_pad + "  "
                print(f"{' ' * indent}{DIM}{desc_line2}{RST}")
        print()

    # Quick actions
    for key, label, desc, *_ in _ACTION_ENTRIES:
        print(_menu_row(key, label, desc))
    print()

    # Footer — utility links
    footer_parts = []
    for key, label, _desc, available, *_ in _FOOTER_ENTRIES:
        if available:
            footer_parts.append(_k(key) + f" {DIM}{label}{RST}")
    footer_parts.append(_k("?") + f" {DIM}Help{RST}")
    footer_parts.append(_k("q") + f" {DIM}Quit{RST}")
    print("  " + f"   ".join(footer_parts))
    if other_builds:
        switch_parts = [_k(key) + f" {DIM}Switch to {label}{RST}"
                        for key, label, track in other_builds]
        print("  " + f"   ".join(switch_parts))
    print()


def main_menu(proj_name, proj_info, workspace_expanded, project_dir,
              game_path, emotes_conf, source_display, workspace_parent,
              projects, settings, expansion_version=None):
    """Top-level interactive menu shown when torch is run with no arguments or torch menu."""
    _set_terminal_title("TORCH")
    other_builds = _detect_other_builds()  # [(key, label, track), ...] — checked once

    def _menu_row(key, name, desc):
        """Render one menu item: [key] Name   dim description."""
        return f"  {_k(key)} {WHITE}{name:<16}{RST}  {DIM}{desc}{RST}"

    def _info_row(label, value, value_colour=None):
        """Render one info panel row: dim label, coloured value."""
        vc = value_colour or CYAN
        return f"  {DIM}{label}{RST}  {vc}{value}{RST}"

    def _info_row2(label1, value1, label2, value2, col_width=20):
        """Two-column info row."""
        left = f"{DIM}{label1}{RST}  {CYAN}{value1:<{col_width}}{RST}"
        right = f"{DIM}{label2}{RST}  {CYAN}{value2}{RST}"
        return f"  {left}{right}"

    while True:
        clear_screen()
        print_logo(proj_name)
        _render_info_panel(game_path, project_dir, BAR, _info_row, _info_row2,
                           expansion_version)
        _render_menu_options(_menu_row, other_builds)
        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if choice in ("q", ""):
            return

        # Build switch check
        for key, label, track in other_builds:
            if choice == key:
                _switch_build(track)
                return  # unreachable if execv succeeds

        # Menu dispatch table — maps choice key to handler callable.
        # Project ("4") and Config ("c") can return switch results that
        # update project state, so they are handled as special cases below.
        menu_dispatch = {
            "1": lambda: _menu_studio(project_dir, game_path, emotes_conf,
                                      source_display, settings, proj_name,
                                      workspace_expanded),
            "2": lambda: _menu_dex(project_dir, game_path, workspace_expanded,
                                   settings, emotes_conf, source_display,
                                   proj_name),
            "3": lambda: _menu_game_settings(project_dir, game_path,
                                             workspace_expanded, settings,
                                             emotes_conf, source_display,
                                             proj_name),
            "b": lambda: _menu_build(game_path, project_dir, emotes_conf,
                                     source_display, settings),
            "r": lambda: _menu_restore(game_path),
            "?": lambda: _menu_help(proj_name, BAR),
        }

        handler = menu_dispatch.get(choice)
        if handler:
            handler()
            continue

        # Special cases: handlers that can switch the active project
        if choice == "4":
            result = _menu_project(project_dir, game_path, emotes_conf,
                                   source_display, settings, proj_name,
                                   workspace_expanded)
            if result:
                if isinstance(result, tuple) and len(result) == 2 and result[0] in ("fork", "new"):
                    new_proj = result[1]
                    cfg = load_config()
                    if cfg:
                        _, projects, _ = cfg
                        if new_proj in projects:
                            proj_name = new_proj
                            proj_info = projects[new_proj]
                            project_dir = os.path.join(workspace_expanded, new_proj)
                            game_path = os.path.expanduser(proj_info["game_path"])
                            source_display = f"{workspace_expanded}/{new_proj}"
                else:
                    # Vault-style switch tuple
                    (proj_name, proj_info, project_dir, game_path,
                     source_display) = result
                    projects = load_config()[1] if load_config() else projects
        elif choice == "c":
            switch_result = _menu_config(workspace_parent, projects, settings,
                                         workspace_expanded, game_path, proj_name)
            if switch_result:
                (proj_name, proj_info, project_dir, game_path,
                 source_display) = switch_result
        else:
            print("  Invalid choice.")


# ── CLI subcommand handlers ─────────────────────────────────────────────────

def _cmd_config(args, proj_name, projects, workspace_expanded, workspace_parent,
                game_path, settings):
    """Handle 'torch config'. Returns updated (proj_name, proj_info, project_dir, game_path, source_display) or None."""
    if not _HAS_CONFIG:
        print("  Config Manager is not available in this release.")
        sys.exit(1)
    try:
        from torch.config_ui import config_manager_menu
    except ImportError:
        print("  Config Manager is not available in this release.")
        sys.exit(1)
    result = config_manager_menu(workspace_parent, projects, settings,
                                 workspace_expanded, game_path=game_path,
                                 proj_name=proj_name)
    if result and result[0] == "switch":
        new_name = result[1]
        new_info = projects[new_name]
        return (new_name, new_info,
                os.path.join(workspace_expanded, new_name),
                os.path.expanduser(new_info["game_path"]))
    return None


def _cmd_studio(game_path, settings, proj_name):
    """Handle 'torch studio'. Redirects to Settings (ROM Studio merged in S136)."""
    if not _HAS_STUDIO:
        print("  ROM Studio is not available in this release.")
        sys.exit(1)
    try:
        from torch.studio import studio_command
    except ImportError:
        print("  ROM Studio is not available in this release.")
        sys.exit(1)
    studio_command(game_path, settings, proj_name=proj_name)


def _cmd_battle(args, project_dir, game_path, workspace_expanded, settings,
                emotes_conf, source_display, proj_name):
    """Handle 'torch battle'."""
    if not _HAS_BATTLE:
        print("  Trainers is not available in this release.")
        sys.exit(1)
    try:
        from torch.battle_manager import battle_command
    except ImportError:
        print("  Trainers is not available in this release.")
        sys.exit(1)
    battle_command(args[1:], project_dir, game_path, workspace_expanded,
                   settings, emotes_conf=emotes_conf,
                   source_display=source_display, proj_name=proj_name)


def _cmd_script(args, project_dir, game_path, emotes_conf, source_display,
                settings, proj_name):
    """Handle 'torch script' / 'torch scene' / 'torch map'."""
    if not _HAS_SCRIPT:
        print("  Map Studio is not available in this release.")
        sys.exit(1)
    try:
        from torch.script_hub import script_command
    except ImportError:
        print("  Map Studio is not available in this release.")
        sys.exit(1)
    script_command(args[1:], project_dir, game_path, emotes_conf,
                   source_display, settings, proj_name=proj_name)


def _cmd_backup(args, proj_name):
    """Handle 'torch backup'."""
    sub = args[1] if len(args) >= 2 else None
    if sub == "list":
        _list_torch_backups()
    elif sub == "prune":
        pruned = _prune_torch_backups(TORCH_BACKUP_DIR)
        print(f"  Pruned {pruned or 0} backup(s).")
    else:
        tag = sub or "manual"
        path = _create_torch_backup(tag, project_name=proj_name)
        print(f"  Backup: {os.path.basename(path)}")
        _list_torch_backups()


def _cmd_restore(args, game_path, project_dir, emotes_conf, source_display,
                 settings):
    """Handle 'torch restore'."""
    if len(args) < 2:
        # No MapName given — verified build restore
        if not _HAS_VERIFIED:
            print("  Verified Build Snapshots not available.")
            sys.exit(1)
        from torch.verified_snapshots import list_verified_snapshots, restore_verified_snapshot
        snapshots = list_verified_snapshots(game_path)
        if not snapshots:
            print("  No verified build snapshots found.")
            print("  Build through TORCH to create one.")
            sys.exit(0)
        print()
        print("  Verified build snapshots:")
        print()
        for i, snap in enumerate(snapshots):
            marker = ">> " if i == 0 else "   "
            print(f"  {marker}{i + 1}.  {snap['display_time']}    [{snap['trigger']}]")
            print(f"       {snap['file_count']} files  --  {snap['size_mb']:.1f} MB")
            print()
        try:
            choice = input("  Restore which snapshot? [1] > ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)
        idx = 0
        if choice.isdigit():
            idx = int(choice) - 1
        elif choice == "":
            idx = 0
        else:
            print("  Cancelled.")
            sys.exit(0)
        if not (0 <= idx < len(snapshots)):
            print(f"  No snapshot #{idx + 1}.")
            sys.exit(1)
        snap = snapshots[idx]
        restored = restore_verified_snapshot(game_path, snap["path"])
        if restored is None:
            sys.exit(1)
        if not restored:
            sys.exit(0)  # User declined
        print(f"  Restored {len(restored)} files from verified snapshot.")
        print()
        _offer_build(game_path, trigger="verified-restore")
    else:
        restore_map(args[1], project_dir, game_path, emotes_conf, source_display,
                    settings["max_snapshots"])


def _cmd_build(game_path, project_dir, emotes_conf, source_display, settings):
    """Handle 'torch build'."""
    _offer_build(
        game_path=game_path,
        trigger="cli",
        safe=False,
        auto_build=False,
        project_dir=project_dir,
        emotes_conf=emotes_conf,
        source_display=source_display,
        max_snapshots=settings["max_snapshots"],
    )


def _cmd_sync(args, project_dir, game_path, emotes_conf, source_display,
              settings):
    """Handle 'torch sync'."""
    if len(args) >= 2:
        map_name = args[1]
        print(f"[{map_name}]")
        if sync_map(map_name, project_dir, game_path, emotes_conf, source_display,
                    settings["max_snapshots"]):
            print()
            _offer_build(game_path)
        else:
            sys.exit(1)
    else:
        sync_all(project_dir, game_path, emotes_conf, source_display,
                 settings["max_snapshots"])


def _cmd_status(project_dir, game_path):
    """Handle 'torch status'."""
    if not _HAS_REGISTRY:
        print("  Map Registry is not available in this release.")
        sys.exit(1)
    from torch.registry import (
        get_enrolled_maps, get_map_health, get_unenrolled_workspace_dirs,
        load_registry,
    )

    enrolled = get_enrolled_maps(project_dir)
    print()
    print(f"  {WHITE}Map Registry{RST}  --  {CYAN}{len(enrolled)} enrolled{RST}")
    print(f"  {GOLD}{'=' * 49}{RST}")
    print()

    _BADGE = {
        "ok":                (f"{GREEN}[     OK     ]{RST}",  GREEN),
        "stale":             (f"{GOLD}[   STALE    ]{RST}",   GOLD),
        "drift":             (f"{RED}[   DRIFT    ]{RST}",    RED),
        "orphan":            (f"{RED}[  ORPHAN    ]{RST}",    RED),
        "missing_workspace": (f"{RED}[ MISSING WS ]{RST}",   RED),
        "never_written":     (f"{CYAN}[    NEW     ]{RST}",   CYAN),
    }

    registry = load_registry(project_dir)
    for name in enrolled:
        health = get_map_health(project_dir, name, game_path)
        badge, colour = _BADGE.get(health, (f"[{health}]", DIM))
        print(f"  {badge}  {WHITE}{name}{RST}")
        entry = registry["maps"].get(name, {})
        lw = entry.get("last_written")
        if lw:
            print(f"  {'':>16}{DIM}last written: {lw}{RST}")
        else:
            print(f"  {'':>16}{DIM}never written{RST}")
        print()

    unenrolled = get_unenrolled_workspace_dirs(project_dir)
    if unenrolled:
        print(f"  {DIM}Unenrolled workspace folders:{RST}")
        for name in unenrolled:
            print(f"    {DIM}{name}{RST}")
        print()

    # Chain status
    try:
        from torch.chain_model import list_chains
        chains = list_chains(project_dir)
        if chains:
            print(f"  {WHITE}Script Chains{RST}  --  {CYAN}{len(chains)} chain(s){RST}")
            print(f"  {GOLD}{'=' * 49}{RST}")
            print()
            for c in chains:
                synced = c.get("synced_at")
                badge = f"{GREEN}[   SYNCED   ]{RST}" if synced else f"{GOLD}[  UNSYNCED  ]{RST}"
                maps = ", ".join(c.get("maps", []))
                print(f"  {badge}  {WHITE}{c['name']}{RST}")
                print(f"  {'':>16}{DIM}{c['script_count']} scripts | {maps}{RST}")
                print()
    except ImportError:
        pass


def _cmd_enroll(args, project_dir, game_path):
    """Handle 'torch enroll'."""
    if not _HAS_REGISTRY:
        print("  Map Registry is not available in this release.")
        sys.exit(1)
    from torch.registry import (
        enroll_map, bulk_enroll, get_unenrolled_workspace_dirs,
    )
    if len(args) >= 2 and args[1] == "--all":
        count, skipped = bulk_enroll(project_dir, game_path)
        if count:
            print(f"  Enrolled {count} map(s).")
        else:
            print(f"  No new maps to enroll.")
        if skipped:
            print(f"  Skipped (no game folder): {', '.join(skipped)}")
    elif len(args) >= 2:
        map_name = args[1]
        if enroll_map(project_dir, map_name):
            print(f"  Enrolled: {map_name}")
        else:
            print(f"  '{map_name}' is already enrolled.")
    else:
        # Interactive: show unenrolled folders, let user pick
        unenrolled = get_unenrolled_workspace_dirs(project_dir)
        if not unenrolled:
            print(f"  All workspace folders are enrolled.")
        else:
            print(f"  Unenrolled workspace folders:")
            for i, name in enumerate(unenrolled):
                game_map_dir = os.path.join(game_path, "data", "maps", name)
                has_game = os.path.isdir(game_map_dir)
                tag = "" if has_game else "  (no game folder)"
                print(f"    [{i + 1}] {name}{tag}")
            print(f"    [a] Enroll all with game folders")
            print(f"    [0] Cancel")
            print()
            choice = input("  Enroll which? > ").strip().lower()
            if choice == "a":
                count, skipped = bulk_enroll(project_dir, game_path)
                if count:
                    print(f"  Enrolled {count} map(s).")
                if skipped:
                    print(f"  Skipped (no game folder): {', '.join(skipped)}")
            elif choice.isdigit() and int(choice) > 0:
                idx = int(choice) - 1
                if 0 <= idx < len(unenrolled):
                    name = unenrolled[idx]
                    if enroll_map(project_dir, name):
                        print(f"  Enrolled: {name}")
                    else:
                        print(f"  '{name}' is already enrolled.")
                else:
                    print("  Invalid choice.")
            elif choice != "0":
                print("  Cancelled.")


def _cmd_unenroll(args, project_dir):
    """Handle 'torch unenroll'."""
    if not _HAS_REGISTRY:
        print("  Map Registry is not available in this release.")
        sys.exit(1)
    from torch.registry import unenroll_map
    if len(args) < 2:
        print("Usage: torch unenroll <MapName>")
        sys.exit(1)
    map_name = args[1]
    if unenroll_map(project_dir, map_name):
        print(f"  Unenrolled: {map_name}")
    else:
        print(f"  '{map_name}' is not enrolled.")


def _cmd_scorch(args, game_path, settings, proj_name):
    """Handle 'torch scorch/clean/cleanup'."""
    # Check for Phoenix subcommand
    if len(args) > 1 and args[1].lower() == "phoenix":
        if not _HAS_SCORCH:
            print("  Phoenix is not available in this release.")
            sys.exit(1)
        try:
            from torch.scorch import scorch_command
        except ImportError:
            print("  Phoenix is not available in this release.")
            sys.exit(1)
        phoenix_args = args[2:] if len(args) > 2 else None
        scorch_command(game_path, settings, phoenix_args, proj_name=proj_name)
        return

    if not _HAS_CLEANUP:
        print("  SCORCH is not available in this release.")
        sys.exit(1)
    try:
        from torch.cleanup import cleanup_command
    except ImportError:
        print("  SCORCH is not available in this release.")
        sys.exit(1)
    cleanup_command(game_path, settings, args[1:], proj_name=proj_name)


def _cmd_sandbox(args, game_path, settings, proj_name):
    """Handle 'torch sandbox' / 'torch fork'."""
    try:
        from torch.fork import fork_command
    except ImportError:
        print("  Fork is not available in this release.")
        sys.exit(1)
    fork_command(args[1:], game_path, settings, proj_name=proj_name)


def _cmd_new(args, settings):
    """Handle 'torch new'."""
    if not _HAS_NEW_PROJECT:
        print("  New Project is not available in this release.")
        sys.exit(1)
    try:
        from torch.new_project import new_project_command
    except ImportError:
        print("  New Project is not available in this release.")
        sys.exit(1)
    new_project_command(args[1:], settings)


def _cmd_upgrade(args, game_path, settings, proj_name):
    """Handle 'torch upgrade'."""
    if not _HAS_UPGRADE:
        print("  Expansion Upgrade is not available in this release.")
        sys.exit(1)
    try:
        from torch.upgrade import upgrade_command
    except ImportError:
        print("  Expansion Upgrade is not available in this release.")
        sys.exit(1)
    upgrade_command(args[1:], game_path, settings, proj_name)


def _cmd_wild(args, project_dir, game_path, workspace_expanded, settings,
              emotes_conf, source_display, proj_name):
    """Handle 'torch wild'."""
    if not _HAS_ENCOUNTER:
        print("  Encounter Editor is not available in this release.")
        sys.exit(1)
    try:
        from torch.encounter_editor import encounter_command
    except ImportError:
        print("  Encounter Editor is not available in this release.")
        sys.exit(1)
    encounter_command(args[1:], project_dir, game_path, workspace_expanded,
                      settings, emotes_conf=emotes_conf,
                      source_display=source_display, proj_name=proj_name)


def _cmd_tweak(args, project_dir, game_path, workspace_expanded, settings,
               emotes_conf, source_display, proj_name):
    """Handle 'torch tweak' / 'torch settings'."""
    if not _HAS_TUNER:
        print("  Settings is not available in this release.")
        sys.exit(1)
    try:
        from torch.config_tuner import config_command
    except ImportError:
        print("  Settings is not available in this release.")
        sys.exit(1)
    config_command(args[1:], project_dir, game_path, workspace_expanded,
                   settings, emotes_conf=emotes_conf,
                   source_display=source_display, proj_name=proj_name)


def _cmd_dex(args, project_dir, game_path, workspace_expanded, settings,
             emotes_conf, source_display, proj_name):
    """Handle 'torch dex'."""
    if not _HAS_DEX:
        print("  Dex is not available in this release.")
        sys.exit(1)
    try:
        from torch.dex import dex_command
    except ImportError:
        print("  Dex is not available in this release.")
        sys.exit(1)
    dex_command(args[1:], project_dir, game_path, workspace_expanded,
                    settings, emotes_conf=emotes_conf,
                    source_display=source_display, proj_name=proj_name)


def _cmd_heal(args, game_path, project_dir, settings, proj_name):
    """Handle 'torch heal'."""
    if not _HAS_HEAL:
        print("  Heal Location Manager is not available in this release.")
        sys.exit(1)
    try:
        from torch.heal_locations import heal_command
    except ImportError:
        print("  Heal Location Manager is not available in this release.")
        sys.exit(1)
    heal_command(args[1:], game_path, project_dir, settings=settings,
                 proj_name=proj_name)


def _cmd_assets(game_path, settings, proj_name, workspace_expanded):
    """Handle 'torch assets'."""
    if not _HAS_ASSET:
        print("  Asset Manager is not available in this release.")
        sys.exit(1)
    try:
        from torch.asset_manager import assets_command
    except ImportError:
        print("  Asset Manager is not available in this release.")
        sys.exit(1)
    assets_command(game_path, settings, proj_name=proj_name,
                   workspace_expanded=workspace_expanded)


def _cmd_npc(args, project_dir, game_path, settings, proj_name):
    """Handle 'torch npc [MapName]'."""
    if not _HAS_NPC:
        print("  NPC Editor is not available in this release.")
        sys.exit(1)
    try:
        from torch.npc_editor import npc_editor_menu
    except ImportError:
        print("  NPC Editor is not available in this release.")
        sys.exit(1)
    if not args:
        print("  Usage: torch npc <MapName>")
        sys.exit(1)
    map_name = args[0]
    npc_editor_menu(game_path, map_name, settings=settings,
                    proj_name=proj_name, project_dir=project_dir)


def _cmd_items(game_path, settings, proj_name):
    """Handle 'torch items'."""
    if not _HAS_ITEM:
        print("  Item Editor is not available in this release.")
        sys.exit(1)
    try:
        from torch.item_editor import item_editor_menu
    except ImportError:
        print("  Item Editor is not available in this release.")
        sys.exit(1)
    item_editor_menu(game_path, settings=settings, proj_name=proj_name)


def _cmd_moves(game_path, settings, proj_name):
    """Handle 'torch moves'."""
    if not _HAS_MOVE:
        print("  Move Editor is not available in this release.")
        sys.exit(1)
    try:
        from torch.move_editor import move_editor_menu
    except ImportError:
        print("  Move Editor is not available in this release.")
        sys.exit(1)
    move_editor_menu(game_path, settings=settings, proj_name=proj_name)


def _cmd_learnsets(game_path, settings, proj_name):
    """Handle 'torch learnsets'."""
    if not _HAS_LEARNSET:
        print("  Learnset Editor is not available in this release.")
        sys.exit(1)
    try:
        from torch.learnset_editor import learnset_editor_menu
    except ImportError:
        print("  Learnset Editor is not available in this release.")
        sys.exit(1)
    learnset_editor_menu(game_path, settings=settings, proj_name=proj_name)


def _cmd_template(args, game_path, settings, proj_name):
    """Handle 'torch template'."""
    if not _HAS_TEMPLATE:
        print("  Building Templates is not available in this release.")
        sys.exit(1)
    try:
        from torch.template_stamper import (
            validate_stamp, stamp_pokecenter, stamp_pokemart,
        )
    except ImportError:
        print("  Building Templates is not available in this release.")
        sys.exit(1)

    sub = args[1:] if len(args) > 1 else []
    if sub:
        _template_cli(sub, game_path, settings, proj_name)
    else:
        _template_wizard(game_path, settings, proj_name)


def _template_cli(sub, game_path, settings, proj_name):
    """Handle CLI mode: torch template pokecenter <Map> --door X,Y [flags]."""
    from torch.template_stamper import stamp_pokecenter, stamp_pokemart

    ttype = sub[0].lower() if sub else ""
    if ttype not in ("pokecenter", "pokemart"):
        print("  Usage: torch template pokecenter|pokemart <ParentMap> "
              "--door X,Y [--no-2f] [--group NAME] [--name NAME]")
        return

    if len(sub) < 2:
        print(f"  Missing parent map. Usage: torch template {ttype} "
              "<ParentMap> --door X,Y")
        return

    parent_map = sub[1]
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(os.path.join(maps_dir, parent_map)):
        print(f"  Map not found: {parent_map}")
        return

    # Parse flags
    door_x, door_y = None, None
    include_2f = True
    group_name = None
    town_name = None
    i = 2
    while i < len(sub):
        flag = sub[i].lower()
        if flag == "--door" and i + 1 < len(sub):
            parts = sub[i + 1].replace(",", " ").split()
            if len(parts) == 2:
                try:
                    door_x, door_y = int(parts[0]), int(parts[1])
                except ValueError:
                    print("  Door coordinates must be integers.")
                    return
            i += 2
        elif flag == "--no-2f":
            include_2f = False
            i += 1
        elif flag == "--group" and i + 1 < len(sub):
            group_name = sub[i + 1]
            i += 2
        elif flag == "--name" and i + 1 < len(sub):
            town_name = sub[i + 1]
            i += 2
        else:
            i += 1

    if door_x is None or door_y is None:
        print("  Missing --door X,Y flag.")
        return

    if ttype == "pokecenter":
        result = stamp_pokecenter(game_path, parent_map, door_x, door_y,
                                  include_2f=include_2f,
                                  map_group=group_name,
                                  town_name=town_name)
    else:
        result = stamp_pokemart(game_path, parent_map, door_x, door_y,
                                map_group=group_name,
                                town_name=town_name)

    _template_show_result(result, ttype, parent_map)


def _template_show_result(result, ttype, parent_map):
    """Display stamp result."""
    label = "PokéCenter" if ttype == "pokecenter" else "PokéMart"
    if not result["success"]:
        print(f"\n  {RED}Error:{RST} {result['error']}")
        return
    print(f"\n  Creating {label} for {parent_map}...\n")
    for f in result["created_files"]:
        print(f"    {GREEN}\u2713{RST} Created {f}")
    for f in result["modified_files"]:
        print(f"    {GREEN}\u2713{RST} Modified {f}")
    for m in result["maps_created"]:
        print(f"    {GREEN}\u2713{RST} Map: {m}")
    if result.get("heal_location_id"):
        print(f"    {GREEN}\u2713{RST} Registered {result['heal_location_id']}")
    for w in result.get("warnings", []):
        print(f"    {DIM}! {w}{RST}")
    print(f"\n  Run {WHITE}torch build{RST} or {WHITE}bb{RST} to build.\n")


def _template_wizard(game_path, settings, proj_name):
    """Interactive wizard for building templates."""
    from torch.template_stamper import (
        validate_stamp, stamp_pokecenter, stamp_pokemart,
    )

    clear_screen()
    print_logo("Building Templates", proj_name)
    print(BAR)
    print()
    print(f"  {_k('1')} {WHITE}PokéCenter{RST}")
    print(f"  {_k('2')} {WHITE}PokéMart{RST}")
    print()
    print(f"  {_k('q')} {DIM}Back{RST}")
    print()

    try:
        choice = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if choice == "1":
        ttype = "pokecenter"
    elif choice == "2":
        ttype = "pokemart"
    elif choice in ("q", ""):
        return
    else:
        return

    _template_wizard_steps(game_path, settings, proj_name, ttype)


def _template_prompt_coords():
    """Prompt for door tile coordinates. Returns (x, y) or None."""
    try:
        coords = input("  Door tile coordinates (x y): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    parts = coords.replace(",", " ").split()
    if len(parts) != 2:
        print(f"  {RED}Expected two integers for x y.{RST}")
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        print(f"  {RED}Coordinates must be integers.{RST}")
        return None


def _template_prompt_2f(settings):
    """Prompt for 2F inclusion. Returns bool or None on cancel."""
    default_2f = settings.get("template_include_2f", True)
    prompt = "  Include 2F? [Y/n]: " if default_2f else "  Include 2F? [y/N]: "
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if default_2f:
        include_2f = answer not in ("n", "no")
    else:
        include_2f = answer in ("y", "yes")
    if include_2f != default_2f:
        settings["template_include_2f"] = include_2f
        _template_save_settings(settings)
    return include_2f


def _template_show_preview(preview):
    """Display stamp preview. Returns False if user declines on warnings."""
    p = preview["preview"]
    print(f"  {WHITE}Preview:{RST}")
    if p.get("maps_to_create"):
        print(f"    Maps to create:  {', '.join(p['maps_to_create'])}")
    if p.get("files_to_create"):
        print(f"    Files to create: {', '.join(p['files_to_create'][:4])}")
        for f in p["files_to_create"][4:]:
            print(f"                     {f}")
    if p.get("files_to_modify"):
        print(f"    Files to modify: {', '.join(p['files_to_modify'])}")
    if p.get("heal_location_id"):
        print(f"    Heal location:   {p['heal_location_id']}")

    for w in preview["warnings"]:
        print(f"    {DIM}! {w}{RST}")
        try:
            cont = input("  Continue? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if cont in ("n", "no"):
            return False
    return True


def _template_wizard_steps(game_path, settings, proj_name, ttype):
    """Run through wizard prompts for a template stamp."""
    from torch.template_stamper import (
        validate_stamp, stamp_pokecenter, stamp_pokemart,
    )

    label = "PokéCenter" if ttype == "pokecenter" else "PokéMart"
    maps_dir = os.path.join(game_path, "data", "maps")

    # 1. Parent map
    print()
    try:
        parent_map = input("  Parent map folder: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not parent_map:
        return
    if not os.path.isdir(os.path.join(maps_dir, parent_map)):
        print(f"  {RED}Map not found:{RST} {parent_map}")
        return

    # 2. Door coordinates
    result = _template_prompt_coords()
    if result is None:
        return
    door_x, door_y = result

    # 3. Include 2F? (PokéCenter only)
    include_2f = True
    if ttype == "pokecenter":
        include_2f = _template_prompt_2f(settings)
        if include_2f is None:
            return

    # 4. Map group
    groups_path = os.path.join(maps_dir, "map_groups.json")
    group_name = _template_pick_group(groups_path)

    # 5. Preview
    preview = validate_stamp(game_path, ttype, parent_map, door_x, door_y,
                             include_2f=include_2f)
    print()
    if preview["errors"]:
        for e in preview["errors"]:
            print(f"  {RED}Error:{RST} {e}")
        return
    if not _template_show_preview(preview):
        return

    # 6. Stamp
    print()
    try:
        go = input(f"  Stamp {label}? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if go in ("n", "no"):
        return

    if ttype == "pokecenter":
        stamp_result = stamp_pokecenter(game_path, parent_map, door_x, door_y,
                                        include_2f=include_2f,
                                        map_group=group_name)
    else:
        stamp_result = stamp_pokemart(game_path, parent_map, door_x, door_y,
                                      map_group=group_name)

    _template_show_result(stamp_result, ttype, parent_map)

    # 7. Build offer
    if stamp_result["success"]:
        try:
            build = input("  Build now? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if build not in ("n", "no"):
            _offer_build(game_path=game_path)


def _template_save_settings(settings):
    """Save current settings to config file."""
    from torch.config import load_config, save_config
    config = load_config()
    if config:
        workspace, projects, _ = config
        workspace_parent = os.path.dirname(os.path.expanduser(workspace))
        save_config(workspace_parent, projects, settings)


def _template_pick_group(groups_path):
    """Show map groups and let user pick one, or return None for auto."""
    if not os.path.isfile(groups_path):
        return None
    try:
        import json
        with open(groups_path) as f:
            groups_data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    group_names = list(groups_data.keys())
    if not group_names:
        return None

    print()
    print(f"  {WHITE}Map group:{RST}")
    for i, name in enumerate(group_names, 1):
        count = len(groups_data[name])
        print(f"    {_k(str(i))} {name} {DIM}({count} maps){RST}")
    print(f"    {_k('n')} {DIM}New group...{RST}")
    print(f"    {_k('')}  {DIM}(Enter = auto){RST}")
    print()

    try:
        pick = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not pick:
        return None
    if pick.lower() == "n":
        try:
            name = input("  New group name: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return name if name else None
    try:
        idx = int(pick) - 1
        if 0 <= idx < len(group_names):
            return group_names[idx]
    except ValueError:
        pass
    return None


def _cmd_tileset(args, game_path, settings, proj_name):
    """Handle 'torch tileset'."""
    if not _HAS_TILESET:
        print("  Tileset Assistant is not available in this release.")
        sys.exit(1)
    try:
        from torch.tileset_assistant import tileset_command
    except ImportError:
        print("  Tileset Assistant is not available in this release.")
        sys.exit(1)
    tileset_command(game_path, settings, args=args[1:], proj_name=proj_name)


def _cmd_explore(args, game_path, settings, proj_name):
    """Handle 'torch explore [MapName]'."""
    if not _HAS_EXPLORE:
        print("  Map Explorer is not available in this release.")
        sys.exit(1)
    try:
        from torch.map_explorer import explore_command
    except ImportError:
        print("  Map Explorer is not available in this release.")
        sys.exit(1)
    explore_command(args[1:], game_path, settings, proj_name=proj_name)


def _cmd_decompile(args):
    """Handle 'torch decompile <file> [MapName]'."""
    if not _HAS_DECOMPILER:
        print("  Decompiler is not available in this release.")
        sys.exit(1)
    if not args:
        print("  Usage: torch decompile <file.pory> [MapName]")
        print("  Output goes to stdout. Redirect with > to save:")
        print("    torch decompile scripts.pory > scripts.txt")
        sys.exit(1)
    path = args[0]
    map_name = args[1] if len(args) > 1 else ""
    if not os.path.isfile(path):
        print(f"  File not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        from torch.decompiler import decompile_file
        torscript, warnings = decompile_file(path, map_name)
        if warnings:
            for w in warnings:
                print(f"warning: {w}", file=sys.stderr)
        print(torscript, end="")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_gui(game_path, project_dir, settings, proj_name, args=None):
    """Handle 'torch gui' — launch the web GUI server."""
    if not _HAS_WEB:
        print("  Web GUI is not available in this release.")
        sys.exit(1)
    try:
        from torch.web.server import start_gui_server
    except ImportError:
        print("  Web GUI is not available in this release.")
        sys.exit(1)

    # Parse optional CLI flags (session-only overrides, don't modify config)
    extra = args[1:] if args and len(args) > 1 else []
    if "--lan" in extra or "--port" in extra:
        settings = dict(settings)  # shallow copy to avoid mutating caller
    if "--lan" in extra:
        settings["_lan_override"] = True
    if "--port" in extra:
        idx = extra.index("--port")
        if idx + 1 < len(extra):
            try:
                settings["gui_port"] = int(extra[idx + 1])
            except ValueError:
                print(f"  ERROR: Invalid port: {extra[idx + 1]}")
                sys.exit(1)

    start_gui_server(game_path, project_dir, settings, proj_name)


def _cmd_project(project_dir, game_path, emotes_conf, source_display,
                 settings, proj_name, workspace_expanded):
    """Handle 'torch project'."""
    _menu_project(project_dir, game_path, emotes_conf, source_display,
                  settings, proj_name, workspace_expanded)


def _cmd_settings_menu(project_dir, game_path, workspace_expanded, settings,
                       emotes_conf, source_display, proj_name):
    """Handle 'torch settings' -> Game Settings submenu."""
    _menu_game_settings(project_dir, game_path, workspace_expanded, settings,
                        emotes_conf, source_display, proj_name)


def _cmd_flags(args, game_path, settings, proj_name):
    """Handle 'torch flags'."""
    try:
        from torch.flag_browser import flag_browser
    except ImportError:
        print("  Flag Browser is not available.")
        sys.exit(1)
    flag_browser(game_path, settings, proj_name=proj_name)


def _cmd_shops(args, game_path, settings, proj_name, project_dir):
    """Handle 'torch shops [MapName]'."""
    try:
        from torch.shop_editor import shop_editor_menu
    except ImportError:
        print("  Shop Editor is not available.")
        sys.exit(1)
    map_name = args[1] if len(args) > 1 else None
    shop_editor_menu(game_path, map_name, settings=settings,
                     proj_name=proj_name, project_dir=project_dir)


def _cmd_versions(args, game_path, project_dir, settings, proj_name):
    """Handle 'torch versions [subcommand]'."""
    try:
        from torch.game_versions import (
            create_version, list_versions, get_version_info,
            restore_version, delete_version, bump_major, versions_menu,
        )
    except ImportError:
        print("  Game Version Control is not available.")
        sys.exit(1)

    sub = args[1] if len(args) >= 2 else None

    if sub is None or sub == "":
        # Interactive TUI
        versions_menu(game_path, project_dir, settings, proj_name)
        return

    sub = sub.lower()
    if sub == "list":
        versions = list_versions(game_path)
        if not versions:
            print("  No saved versions.")
            return
        print()
        for v in versions:
            rom_tag = "  [ROM]" if v.get("rom_filename") else ""
            print(f"  v{v['version']:<8} {v.get('label', '') or '(unnamed)'}{rom_tag}")
            print(f"           {v['display_time']}  |  {v['file_count']} files  |  "
                  f"{v['size_mb']:.1f} MB")
        print()

    elif sub == "save":
        label = " ".join(args[2:]) if len(args) > 2 else ""
        if not label:
            try:
                label = input("  Version label: ").strip()
            except (EOFError, KeyboardInterrupt):
                return
        print(f"  Creating version...")
        entry = create_version(game_path, project_dir, label=label)
        if entry:
            print(f"  Saved v{entry['version']} \u2014 {entry.get('label', '')} "
                  f"({entry['size_bytes'] / 1048576:.1f} MB)")

    elif sub == "restore":
        ver = args[2] if len(args) > 2 else None
        if not ver:
            versions = list_versions(game_path)
            if not versions:
                print("  No saved versions.")
                return
            print()
            for i, v in enumerate(versions):
                print(f"  {i + 1}.  v{v['version']}  {v.get('label', '')}")
            print()
            try:
                choice = input("  Restore which version? > ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            if not choice.isdigit() or int(choice) < 1 or int(choice) > len(versions):
                return
            ver = versions[int(choice) - 1]["version"]
        restore_version(game_path, project_dir, ver)

    elif sub == "bump":
        new_ver = bump_major(game_path)
        print(f"  Major version bumped. Next save will be v{new_ver}.")

    elif sub == "info":
        ver = args[2] if len(args) > 2 else None
        if not ver:
            print("  Usage: torch versions info <version>")
            return
        info = get_version_info(game_path, ver)
        if not info:
            print(f"  Version {ver} not found.")
            return
        print()
        print(f"  Version:    v{info['version']}")
        print(f"  Label:      {info.get('label', '') or '(unnamed)'}")
        print(f"  Saved:      {info['display_time']}")
        print(f"  Files:      {info['file_count']}")
        print(f"  Size:       {info['size_mb']:.1f} MB")
        if info.get("rom_filename"):
            print(f"  ROM:        {info['rom_filename']}")
        print(f"  TORCH:      v{info.get('torch_version', '?')}")
        if info.get("expansion_version"):
            print(f"  Expansion:  v{info['expansion_version']}")
        if info.get("notes"):
            print(f"  Notes:      {info['notes']}")
        print()

    elif sub == "delete":
        ver = args[2] if len(args) > 2 else None
        if not ver:
            print("  Usage: torch versions delete <version>")
            return
        info = get_version_info(game_path, ver)
        if not info:
            print(f"  Version {ver} not found.")
            return
        print(f"  Delete v{ver} \u2014 {info.get('label', '')}?")
        try:
            confirm = input("  Type 'delete' to confirm > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if confirm == "delete":
            if delete_version(game_path, ver):
                print(f"  Deleted v{ver}.")
        else:
            print("  Cancelled.")

    else:
        print(f"  Unknown subcommand: {sub}")
        print("  Usage: torch versions [save|restore|bump|info|delete|list]")


def _cmd_standalone_compile(args, workspace_expanded, output_dir, emotes_conf):
    """Handle standalone script compilation (no recognized subcommand)."""
    script_name = args[0]

    # Strip extensions if provided
    if script_name.endswith(".txt"):
        script_name = script_name[:-4]

    input_path = os.path.join(workspace_expanded, f"{script_name}.txt")
    output_path = os.path.join(output_dir, f"{script_name}.pory")

    if not os.path.exists(input_path):
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Derive label prefix from script name (PascalCase, basename only)
    base_name = os.path.basename(script_name)
    label_prefix = "".join(word.capitalize() for word in base_name.split("_"))

    output, errors = compile_script(input_path, label_prefix, emotes_conf)

    if errors:
        print(f"Errors in {script_name}.txt:")
        for err in errors:
            print(f"  {err}")
        print()
        print("Output generated with errors (check carefully).")

    with open(output_path, "w") as f:
        f.write(output)

    print(f"Compiled: {input_path}")
    print(f"Output:   {output_path}")

    if not errors:
        print("No errors.")


def _handle_pre_config_commands():
    """Handle subcommands that work without config (init, update, test, delete).

    Returns True if a command was handled (caller should return).
    """
    if len(sys.argv) < 2:
        return False
    cmd = sys.argv[1]
    if cmd == "init":
        init_command()
        return True
    if cmd == "update":
        from torch.update import update_command
        update_command(sys.argv[2:])
        return True
    if cmd == "test":
        from torch.tests.run_tests import run_all_tests
        # Parse test args: flags (--quiet, --fail-fast) and optional suite filter
        test_args = [a for a in sys.argv[2:] if a != "--"]
        quiet = False
        fail_fast = False
        suite_filter = None
        for arg in test_args:
            if arg in ("--quiet", "-q"):
                quiet = True
            elif arg in ("--fail-fast", "-x"):
                fail_fast = True
            elif not arg.startswith("-"):
                suite_filter = arg
        ok = run_all_tests(suite_filter=suite_filter, quiet=quiet, fail_fast=fail_fast)
        sys.exit(0 if ok else 1)
    if cmd == "check":
        from torch.check import run_check
        ok = run_check()
        sys.exit(0 if ok else 1)
    if cmd == "delete":
        from torch.fork import _delete_fork, _pick_fork_to_delete
        if len(sys.argv) >= 3:
            _delete_fork(sys.argv[2], {})
        else:
            name = _pick_fork_to_delete()
            if name:
                _delete_fork(name, {})
        return True
    return False


def _parse_project_flag():
    """Extract --project flag from argv, return (args, project_name)."""
    project_name = None
    args = list(sys.argv[1:])
    if "--project" in args:
        idx = args.index("--project")
        if idx + 1 < len(args):
            project_name = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
        else:
            print("Error: --project requires a name.")
            sys.exit(1)
    return args, project_name


# ── Module registry ────────────────────────────────────────────────────────
#
# Each group: (group_name, [(key, label, description, available), ...])
# The registry drives menu rendering, help screen, and dispatch tables.
# Menu dispatch and CLI dispatch build lookup dicts from these at call time,
# since handler arguments vary per entry.

_MENU_GROUPS = [
    ("", [
        ("1", "Studio",        "Your maps, trainers,",   "items & scripts",                  True),
        ("2", "Dex",           "Pokemon species,",       "moves & learnsets",                _HAS_DEX),
        ("3", "Game Settings", "Expansion options, ROM,", "tilesets & assets",               _HAS_TUNER),
        ("4", "Project",       "Backups, SCORCH,",       "fork & upgrade",                  _HAS_VAULT),
    ]),
]

_ACTION_ENTRIES = [
    ("b", "Build",   "Build ROM with auto-sync & error diagnosis"),
    ("r", "Restore", "Restore from a verified build snapshot"),
]

_FOOTER_ENTRIES = [
    ("c", "Config",  "Manage projects & preferences",   _HAS_CONFIG),
]

# CLI command name -> (handler_key, show_menu)
# handler_key is looked up in a dict built at dispatch time.
_CLI_DISPATCH_TABLE = {
    # New canonical names
    "maps":       ("script",   True),    # torch maps -> Studio
    "script":     ("script",   True),    # torch script -> Studio
    "trainers":   ("battle",   True),    # torch trainers -> Trainers
    "encounters": ("wild",     False),   # torch encounters -> Encounters
    "project":    ("project",  True),    # torch project -> Project submenu
    "rom":        ("rom",      True),    # torch rom -> ROM metadata
    "flags":      ("flags",    False),   # torch flags -> Flag browser
    "shops":      ("shops",    False),   # torch shops -> Shop editor

    # Existing commands (backward-compatible aliases)
    "studio":   ("script",   True),    # torch studio -> Studio (was ROM metadata)
    "battle":   ("battle",   True),
    "scene":    ("script",   True),    # backward compat: torch scene -> Studio
    "map":      ("script",   True),
    "backup":   ("backup",   True),
    "restore":  ("restore",  True),
    "build":    ("build",    True),
    "sync":     ("sync",     True),
    "status":   ("status",   False),
    "enroll":   ("enroll",   False),
    "unenroll": ("unenroll", False),
    "scorch":   ("scorch",   False),
    "clean":    ("scorch",   False),
    "cleanup":  ("scorch",   False),
    "sandbox":  ("sandbox",  False),
    "fork":     ("sandbox",  False),
    "upgrade":  ("upgrade",  False),
    "wild":     ("wild",     False),
    "tweak":    ("tweak",    False),
    "settings": ("settings_menu", False),  # torch settings -> Game Settings submenu
    "dex":      ("dex",      False),
    "heal":     ("heal",     False),
    "assets":   ("assets",   True),
    "new":      ("new",      False),
    "npc":      ("npc",      True),
    "items":    ("items",    True),
    "moves":    ("moves",    True),
    "learnsets": ("learnsets", True),
    "template": ("template", False),
    "tileset":  ("tileset",  True),
    "tilesets": ("tileset",  True),
    "explore":  ("explore",  False),
    "decompile": ("decompile", False),
    "gui":       ("gui",       False),
    "web":       ("gui",       False),
    "versions":  ("versions",  True),
    "version":   ("versions",  True),
}


def _dispatch_subcommand(cmd, args, proj_name, proj_info, projects, settings,
                         workspace, workspace_expanded, workspace_parent,
                         project_dir, game_path, emotes_conf, output_dir,
                         source_display, expansion_version=None):
    """Route a CLI subcommand.

    Returns (show_menu, proj_name, proj_info, project_dir, game_path, source_display).
    show_menu=True means the caller should show main_menu afterwards.
    """
    result = (proj_name, proj_info, project_dir, game_path, source_display)

    # Special cases that affect project state
    if cmd == "menu":
        _set_terminal_title("TORCH")
        main_menu(proj_name, proj_info, workspace_expanded, project_dir,
                  game_path, emotes_conf, source_display, workspace_parent,
                  projects, settings, expansion_version)
        return (False,) + result

    if cmd == "config":
        updated = _cmd_config(args, proj_name, projects, workspace_expanded,
                              workspace_parent, game_path, settings)
        if updated:
            proj_name, proj_info, project_dir, game_path = updated
            source_display = f"{workspace}/{proj_name}"
            result = (proj_name, proj_info, project_dir, game_path, source_display)
        return (True,) + result

    # Build handler lookup — maps handler_key to a callable
    cli_handlers = {
        "rom":      lambda: _cmd_studio(game_path, settings, proj_name),
        "studio":   lambda: _cmd_studio(game_path, settings, proj_name),
        "battle":   lambda: _cmd_battle(args, project_dir, game_path,
                                        workspace_expanded, settings,
                                        emotes_conf, source_display, proj_name),
        "script":   lambda: _cmd_script(args, project_dir, game_path, emotes_conf,
                                       source_display, settings, proj_name),
        "backup":   lambda: _cmd_backup(args, proj_name),
        "restore":  lambda: _cmd_restore(args, game_path, project_dir,
                                         emotes_conf, source_display, settings),
        "build":    lambda: _cmd_build(game_path, project_dir, emotes_conf,
                                       source_display, settings),
        "sync":     lambda: _cmd_sync(args, project_dir, game_path, emotes_conf,
                                      source_display, settings),
        "status":   lambda: _cmd_status(project_dir, game_path),
        "enroll":   lambda: _cmd_enroll(args, project_dir, game_path),
        "unenroll": lambda: _cmd_unenroll(args, project_dir),
        "scorch":   lambda: _cmd_scorch(args, game_path, settings, proj_name),
        "sandbox":  lambda: _cmd_sandbox(args, game_path, settings, proj_name),
        "upgrade":  lambda: _cmd_upgrade(args, game_path, settings, proj_name),
        "wild":     lambda: _cmd_wild(args, project_dir, game_path,
                                      workspace_expanded, settings, emotes_conf,
                                      source_display, proj_name),
        "tweak":    lambda: _cmd_tweak(args, project_dir, game_path,
                                       workspace_expanded, settings, emotes_conf,
                                       source_display, proj_name),
        "dex":      lambda: _cmd_dex(args, project_dir, game_path,
                                     workspace_expanded, settings, emotes_conf,
                                     source_display, proj_name),
        "heal":     lambda: _cmd_heal(args, game_path, project_dir, settings,
                                      proj_name),
        "assets":   lambda: _cmd_assets(game_path, settings, proj_name,
                                        workspace_expanded),
        "new":      lambda: _cmd_new(args, settings),
        "npc":      lambda: _cmd_npc(args, project_dir, game_path, settings,
                                     proj_name),
        "items":    lambda: _cmd_items(game_path, settings, proj_name),
        "moves":    lambda: _cmd_moves(game_path, settings, proj_name),
        "learnsets": lambda: _cmd_learnsets(game_path, settings, proj_name),
        "template": lambda: _cmd_template(args, game_path, settings, proj_name),
        "tileset": lambda: _cmd_tileset(args, game_path, settings, proj_name),
        "explore": lambda: _cmd_explore(args, game_path, settings, proj_name),
        "decompile": lambda: _cmd_decompile(args),
        "gui":      lambda: _cmd_gui(game_path, project_dir, settings, proj_name, args),
        "project": lambda: _cmd_project(project_dir, game_path, emotes_conf,
                                         source_display, settings, proj_name,
                                         workspace_expanded),
        "settings_menu": lambda: _cmd_settings_menu(project_dir, game_path,
                                                     workspace_expanded, settings,
                                                     emotes_conf, source_display,
                                                     proj_name),
        "flags": lambda: _cmd_flags(args, game_path, settings, proj_name),
        "shops": lambda: _cmd_shops(args, game_path, settings, proj_name,
                                    project_dir),
        "versions": lambda: _cmd_versions(args, game_path, project_dir,
                                          settings, proj_name),
    }

    entry = _CLI_DISPATCH_TABLE.get(cmd)
    if entry:
        handler_key, show_menu = entry
        cli_handlers[handler_key]()
        return (show_menu,) + result

    # Standalone compile — no menu after
    _cmd_standalone_compile(args, workspace_expanded, output_dir, emotes_conf)
    return (False,) + result


def main():
    # ---- Pre-config subcommands (init, update, test) ----
    if _handle_pre_config_commands():
        return

    # ---- Load config ----
    config = load_config()
    if config is None:
        print("TORCH is not configured yet.")
        print("Run 'torch init' to set up.")
        sys.exit(1)

    workspace, projects, settings = config
    args, project_name = _parse_project_flag()

    # Resolve project and paths
    proj_name, proj_info = resolve_project(projects, project_name, settings)
    workspace_expanded = os.path.expanduser(workspace)
    workspace_parent = os.path.dirname(workspace_expanded)
    project_dir = os.path.join(workspace_expanded, proj_name)
    game_path = os.path.expanduser(proj_info["game_path"])
    emotes_conf = os.path.join(workspace_expanded, "config", "emotes.conf")
    output_dir = os.path.join(workspace_expanded, "output")
    source_display = f"{workspace}/{proj_name}"

    # ---- Detect expansion version ----
    expansion_version = None
    if _HAS_COMPAT:
        from torch.expansion_compat import detect_expansion_version
        expansion_version = detect_expansion_version(game_path)

    # ---- No args: show main menu ----
    if not args:
        _set_terminal_title("TORCH")
        main_menu(proj_name, proj_info, workspace_expanded, project_dir,
                  game_path, emotes_conf, source_display, workspace_parent,
                  projects, settings, expansion_version)
        return

    # ---- Dispatch subcommand ----
    (show_menu, proj_name, proj_info, project_dir, game_path,
     source_display) = _dispatch_subcommand(
        args[0], args, proj_name, proj_info, projects, settings,
        workspace, workspace_expanded, workspace_parent,
        project_dir, game_path, emotes_conf, output_dir, source_display,
        expansion_version,
    )

    # Interactive subcommands fall through to the main menu
    if show_menu:
        main_menu(proj_name, proj_info, workspace_expanded, project_dir,
                  game_path, emotes_conf, source_display, workspace_parent,
                  projects, settings, expansion_version)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        print("Please report this with the steps that caused it.")
        sys.exit(1)
