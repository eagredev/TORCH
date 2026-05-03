"""Config system - INI-based project and preference management.

Reads and writes ``~/.config/torch/torch.conf``. Handles project
resolution (single or multi-project), workspace path discovery,
navigation key preferences, and the active project selector.
"""
# TORCH_MODULE: Config System
# TORCH_GROUP: Core
import sys, os, configparser

from torch.colours import GOLD, WHITE, DIM, RST

# ============================================================
# CONFIG
# ============================================================
CONFIG_PATH = os.path.expanduser("~/.config/torch/torch.conf")
_CONFIG_PATH_LEGACY = os.path.expanduser("~/.porysync.conf")

SETTINGS_DEFAULTS = {
    "max_snapshots": 10,
    "editor_visible_beats": 20,
    "storyboard_page_size": 30,
    "trainer_list_page_size": 20,
    "textbox_warning": 3,
    "level_cap": 100,
    "show_all_trainers": False,
    "map_list_page_size": 20,
    "editor_context": "compact",
    "favourite_project": "",      # auto-load this project when multiple are configured
    # Navigation keys (single character, used in all list menus)
    "nav_scroll": "",     # secondary scroll-down key (Enter always scrolls)
    "nav_up": "u",        # move highlight up
    "nav_down": "j",      # move highlight down
    "nav_open": "v",      # open/act on highlighted item
    "max_verified_snapshots": 3,
    "auto_build": True,
    "projects_directory": "~/Documents",
    "maps_view": "recent",
    "template_include_2f": True,
    "vim_help_dismissed": False,
    "gui_port": 8642,
    "gui_host": "127.0.0.1",
    "gui_lan_enabled": False,
    "gui_username": "",
    "gui_password": "",
    "poryaaaa_path": "",
    "audio_player": "",
    "music_cache_max_mb": 200,
    "music_sample_rate": 22050,
    "music_default_duration": 180,
}

SETTINGS_DESCRIPTIONS = {
    "max_snapshots": "Snapshots kept per map before auto-prune",
    "editor_visible_beats": "Beats visible in Script Editor scroll",
    "storyboard_page_size": "Lines per page in storyboard view",
    "trainer_list_page_size": "Trainers per page in trainer list",
    "textbox_warning": "Warn when dialogue exceeds this many boxes",
    "level_cap": "Max Pokemon level in trainer parties",
    "show_all_trainers": "Show all trainers (incl. vanilla) by default in trainer list",
    "map_list_page_size": "Maps per page in Script Studio list",
    "editor_context": "Context line below command bar (compact/detail/off)",
    "favourite_project": "Auto-load this project on launch (set via Config > Projects)",
    "nav_scroll": "Secondary scroll-down key in list menus (Enter always scrolls)",
    "nav_up": "Move highlight up in list menus",
    "nav_down": "Move highlight down in list menus",
    "nav_open": "Open/act on highlighted item in list menus",
    "max_verified_snapshots": "Verified build snapshots retained (newest N kept)",
    "auto_build": "Auto-build after safe operations (sync, restore) without prompting",
    "projects_directory": "Default directory for new projects (torch new, torch fork)",
    "maps_view": "Default view in Studio workspace (recent or all)",
    "vim_help_dismissed": "Skip the vim quick-start guide before editing",
    "gui_port": "Port for TORCH web GUI server",
    "gui_host": "Bind address for web GUI (127.0.0.1 = local only, 0.0.0.0 = all interfaces)",
    "gui_lan_enabled": "Allow LAN access to web GUI (overrides gui_host to 0.0.0.0)",
    "gui_username": "HTTP Basic Auth username for web GUI (empty = no auth)",
    "gui_password": "HTTP Basic Auth password for web GUI (empty = no auth)",
    "poryaaaa_path": "Path to poryaaaa_render binary (empty = auto-detect from PATH)",
    "audio_player": "Audio player override for TUI playback (empty = auto-detect: pw-play, paplay, aplay)",
    "music_cache_max_mb": "Max disk cache for rendered .wav files (MB)",
    "music_sample_rate": "Render sample rate for music playback (22050 or 44100)",
    "music_default_duration": "Default render duration in seconds",
}


def _nav_keys(settings):
    """Return (scroll_key, up_key, down_key, open_key) from settings, with defaults."""
    d = SETTINGS_DEFAULTS
    s = settings.get("nav_scroll", d["nav_scroll"]).lower()
    u = settings.get("nav_up",     d["nav_up"]).lower()     or "u"
    j = settings.get("nav_down",   d["nav_down"]).lower()   or "j"
    o = settings.get("nav_open",   d["nav_open"]).lower()   or "v"
    return s, u, j, o


def load_config():
    """Load config from ~/.config/torch/torch.conf. Auto-migrates from legacy path."""
    # Migrate from old location if needed
    if not os.path.exists(CONFIG_PATH) and os.path.exists(_CONFIG_PATH_LEGACY):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        import shutil
        shutil.copy2(_CONFIG_PATH_LEGACY, CONFIG_PATH)
        os.remove(_CONFIG_PATH_LEGACY)
        print(f"  Config migrated: ~/.porysync.conf -> ~/.config/torch/torch.conf")
    if not os.path.exists(CONFIG_PATH):
        return None
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    if "torch" not in cfg:
        return None
    workspace_parent = os.path.expanduser(cfg["torch"].get("workspace_parent", "~"))
    # Auto-correct corruption: strip any trailing /TORCH segments from workspace_parent
    # (load_config appends /TORCH to build the workspace path, so if the stored value
    # already ends with /TORCH it gets doubled: /ROMHacking/TORCH -> /ROMHacking/TORCH/TORCH)
    while workspace_parent.rstrip("/").endswith("/TORCH"):
        workspace_parent = workspace_parent.rstrip("/")[:-len("/TORCH")]
    workspace = os.path.join(workspace_parent, "TORCH")
    projects = {}
    for section in cfg.sections():
        if section.startswith("project:"):
            name = section[len("project:"):]
            game_path = os.path.expanduser(cfg[section].get("game_path", ""))
            projects[name] = {"game_path": game_path}
    # Load settings with defaults
    settings = dict(SETTINGS_DEFAULTS)
    for key, default in SETTINGS_DEFAULTS.items():
        raw = cfg["torch"].get(key)
        if raw is not None:
            if isinstance(default, bool):
                settings[key] = raw.lower() in ("true", "1", "yes")
            elif isinstance(default, str):
                settings[key] = raw
            else:
                try:
                    settings[key] = int(raw)
                except ValueError:
                    pass  # keep default
    return workspace, projects, settings


def save_config(workspace_parent, projects, settings=None):
    """Write config to ~/.config/torch/torch.conf."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    # Ensure workspace_parent never stores the /TORCH suffix
    while workspace_parent.rstrip("/").endswith("/TORCH"):
        workspace_parent = workspace_parent.rstrip("/")[:-len("/TORCH")]
    cfg = configparser.ConfigParser()
    torch_section = {"workspace_parent": workspace_parent}
    # Only write non-default settings to keep config clean
    if settings:
        for key, default in SETTINGS_DEFAULTS.items():
            if settings.get(key, default) != default:
                torch_section[key] = str(settings[key])
    cfg["torch"] = torch_section
    for name, info in projects.items():
        cfg[f"project:{name}"] = {"game_path": info["game_path"]}
    try:
        with open(CONFIG_PATH, "w") as f:
            cfg.write(f)
    except OSError as e:
        print(f"  ERROR: Could not write config to {CONFIG_PATH}: {e}")
        return


def _pick_project(projects):
    """Interactive project picker shown when multiple projects exist and no favourite is set."""
    proj_list = list(projects.keys())
    print()
    print(f"  {WHITE}Select a project:{RST}")
    print()
    for i, name in enumerate(proj_list, 1):
        path = projects[name]["game_path"].replace(os.path.expanduser("~"), "~")
        print(f"  {GOLD}[{i}]{RST} {name}")
        print(f"       {DIM}{path}{RST}")
        print()
    print(f"  {DIM}Tip: set a favourite in {RST}{GOLD}torch config{RST}{DIM} > Projects > [f] favourite{RST}")
    print()
    while True:
        raw = input(f"  {GOLD}>{RST} ").strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(proj_list):
                name = proj_list[idx]
                return name, projects[name]
        # Allow typing the project name directly
        if raw in projects:
            return raw, projects[raw]
        print(f"  Enter a number from 1 to {len(proj_list)}.")


def resolve_project(projects, project_name=None, settings=None):
    """Pick the right project. Shows a menu when multiple projects exist."""
    if not projects:
        print("Error: No projects configured. Run 'torch init' to set up.")
        sys.exit(1)
    if project_name:
        if project_name not in projects:
            print(f"Error: Project '{project_name}' not found in config.")
            print(f"Available projects: {', '.join(projects.keys())}")
            sys.exit(1)
        return project_name, projects[project_name]
    if len(projects) == 1:
        name = list(projects.keys())[0]
        return name, projects[name]
    # Multiple projects — check for a favourite
    favourite = (settings or {}).get("favourite_project", "")
    if favourite and favourite in projects:
        return favourite, projects[favourite]
    # Show interactive picker
    return _pick_project(projects)


DIVIDER = " " + "-" * 51
