"""First-time setup wizard for TORCH."""
# TORCH_MODULE: Setup Wizard
# TORCH_GROUP: Tools
import os
import sys

from torch.config import load_config, save_config, CONFIG_PATH, DIVIDER
from torch.ui import print_logo
from torch import VERSION


def init_command():
    """Interactive first-time setup."""
    existing = load_config()

    # ---- Already configured: show status + offer to add a project ----
    if existing:
        workspace, projects, settings = existing
        print_logo(f"Setup  v{VERSION}")
        print(" TORCH is already configured.")
        print()
        print(f"  Workspace : {workspace}")
        for name, info in projects.items():
            print(f"  Project   : {name}  ->  {info['game_path']}")
        print()
        print(DIVIDER)
        print()
        print(" Would you like to add another project?")
        print(" (Each ROM hack you work on is a separate project.)")
        print()
        answer = input("  Add a new project? [y/N] > ").strip().lower()
        if answer != "y":
            print()
            print(" Nothing changed. Done.")
            return

        print()
        print(DIVIDER)
        print()
        print(" NEW PROJECT — Step 1 of 2: Project Name")
        print(" A short label for this ROM hack.")
        print(' Can be anything — e.g. "myhack", "myromhack".')
        print()
        proj_name = input("  Name > ").strip()
        if not proj_name:
            print(" Cancelled.")
            return

        print()
        print(DIVIDER)
        print()
        print(" NEW PROJECT — Step 2 of 2: Game Project Path")
        print(" The root folder of your pokeemerald-expansion repository.")
        print(" TORCH will write compiled scripts into this folder.")
        print(' Example: ~/Documents/pokeemerald-expansion')
        print()
        game_path = input("  Path > ").strip()
        if not game_path:
            print(" Cancelled.")
            return
        game_path_expanded = os.path.expanduser(game_path)
        if not os.path.isdir(game_path_expanded):
            print(f"  Warning: That path doesn't exist yet: {game_path_expanded}")

        projects[proj_name] = {"game_path": game_path}
        workspace_parent = os.path.dirname(workspace)
        save_config(workspace_parent, projects, settings)
        proj_dir = os.path.join(workspace, proj_name)
        os.makedirs(proj_dir, exist_ok=True)

        print()
        print(DIVIDER)
        print()
        print(f"  Added project : {proj_name}")
        print(f"  Workspace     : {proj_dir}/")
        print()
        print(" All done. Run 'torch sync' when you're ready.")
        return

    # ---- Fresh setup ----
    print_logo(f"Setup  v{VERSION}")
    print(" Welcome! Let's get TORCH set up.")
    print(" This only needs to be done once.")
    print()
    print(DIVIDER)
    print()
    print(" STEP 1 of 3 — Game Project Path")
    print(" The root folder of your pokeemerald-expansion repository.")
    print(" TORCH will write compiled scripts into this folder.")
    print(' Example: ~/Documents/pokeemerald-expansion')
    print()
    game_path = input("  Path > ").strip()
    if not game_path:
        print(" Error: A game project path is required.")
        sys.exit(1)
    game_path_expanded = os.path.expanduser(game_path)
    if not os.path.isdir(game_path_expanded):
        print(f"  Warning: That path doesn't exist yet: {game_path_expanded}")

    print()
    print(DIVIDER)
    print()
    print(" STEP 2 of 3 — Project Name")
    print(" A short label for this ROM hack. Used to organize your workspace.")
    print(' Can be anything — e.g. "myhack", "myromhack".')
    print()
    proj_name = input("  Name > ").strip()
    if not proj_name:
        print(" Error: A project name is required.")
        sys.exit(1)

    print()
    print(DIVIDER)
    print()
    print(" STEP 3 of 3 — Workspace Location")
    print(' TORCH will create a "TORCH/" folder here to store your')
    print(" source files (.txt scripts, .pory files, snapshots, etc.).")
    print(" Press Enter to use your home directory (~).")
    print()
    default_parent = "~"
    workspace_parent = input(f"  Location [{default_parent}] > ").strip()
    if not workspace_parent:
        workspace_parent = default_parent
    # Strip trailing /TORCH — the code creates the TORCH subfolder automatically
    while workspace_parent.rstrip("/").endswith("/TORCH"):
        workspace_parent = workspace_parent.rstrip("/")[:-len("/TORCH")]
        print("  (Stripped trailing /TORCH — it's created automatically.)")

    projects = {proj_name: {"game_path": game_path}}
    save_config(workspace_parent, projects)

    workspace = os.path.join(os.path.expanduser(workspace_parent), "TORCH")
    proj_dir = os.path.join(workspace, proj_name)
    config_dir = os.path.join(workspace, "config")
    os.makedirs(proj_dir, exist_ok=True)
    os.makedirs(config_dir, exist_ok=True)

    emotes_path = os.path.join(config_dir, "emotes.conf")
    if not os.path.exists(emotes_path):
        try:
            with open(emotes_path, "w") as f:
                f.write("# Custom emotes -- add your own below.\n")
                f.write("# Format: name=emote_constant\n")
                f.write("# Example:\n")
                f.write("#   sweat=emote_sweat_drop\n")
                f.write("#   note=emote_music_note\n")
        except OSError as e:
            print(f"  WARNING: Could not create emotes.conf: {e}")

    print()
    print(DIVIDER)
    print()
    print("  Config    : " + CONFIG_PATH)
    print("  Workspace : " + proj_dir + "/")
    print("  Emotes    : " + emotes_path)
    print()
    print(" All done. Run 'torch sync <MapName>' to sync your first map.")
