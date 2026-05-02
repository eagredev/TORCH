"""TORCH New Project — create a fresh project by cloning from GitHub."""
# TORCH_MODULE: New Project
# TORCH_GROUP: Core

import os
import re
import shutil
import sys

from torch.config import CONFIG_PATH, load_config, save_config
from torch.colours import GOLD, WHITE, DIM, RED, GREEN, RST

# ── Constants ────────────────────────────────────────────────────────────────

VANILLA_REPO = "https://github.com/pret/pokeemerald.git"
EXPANSION_REPO = "https://github.com/rh-hideout/pokeemerald-expansion.git"
EXPANSION_TAGS_API = "https://api.github.com/repos/rh-hideout/pokeemerald-expansion/tags"
EXPANSION_TAG_PATTERN = re.compile(r"^expansion/(\d+)\.(\d+)\.(\d+)$")

_PAGE_SIZE = 20  # versions shown per page in picker


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sanitize_name(raw):
    """Sanitize project name: lowercase, alphanumeric + hyphens, max 30 chars."""
    name = raw.strip().lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:30]


def _get_workspace_parent():
    """Read workspace_parent from torch.conf."""
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    if "torch" in cfg:
        return cfg["torch"].get("workspace_parent", "~")
    return "~"


# ── Entry point ──────────────────────────────────────────────────────────────

def new_project_command(args, settings):
    """Create a fresh project by cloning pokeemerald or pokeemerald-expansion."""
    from torch.gitops import git_available, git_clone
    from torch.netops import check_connectivity, fetch_github_tags

    # Pre-flight checks
    if not git_available():
        print()
        print(f"  {RED}git is not installed or not on PATH.{RST}")
        print(f"  {DIM}Install git and try again.{RST}")
        print()
        return

    print()
    print(f"  {GOLD}+-- New Project ----------------------------+{RST}")
    print()
    print(f"  Create a fresh project from GitHub.")
    print()

    # Source picker
    print(f"  {WHITE}Select source:{RST}")
    print(f"    [1] pokeemerald {DIM}(vanilla, no expansion){RST}")
    print(f"    [2] pokeemerald-expansion {DIM}(recommended){RST}")
    print(f"    [3] pokeemerald-expansion {DIM}(Phoenixed — vanilla content removed){RST}")
    print()

    try:
        raw = input(f"  Source [2]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print("  Cancelled.")
        return

    phoenix = False
    if raw == "1":
        source = "vanilla"
        repo_url = VANILLA_REPO
        branch = None
    elif raw in ("2", ""):
        source = "expansion"
        repo_url = EXPANSION_REPO
        branch = None
    elif raw == "3":
        source = "expansion"
        repo_url = EXPANSION_REPO
        branch = None
        phoenix = True
    else:
        print("  Invalid selection.")
        return

    # Version picker for expansion
    if source == "expansion":
        print()
        print(f"  Checking for available versions... ", end="", flush=True)

        if not check_connectivity():
            print(f"failed")
            print()
            print(f"  {RED}No internet connection.{RST}")
            print(f"  {DIM}Check your network and try again.{RST}")
            print()
            return

        versions = fetch_github_tags(EXPANSION_TAGS_API, EXPANSION_TAG_PATTERN)
        if versions is None or len(versions) == 0:
            print(f"failed")
            print()
            print(f"  {RED}Could not fetch version list from GitHub.{RST}")
            print()
            return

        print(f"done ({len(versions)} versions)")
        print()

        # Show version list (newest first, paged)
        branch = _pick_version(versions, phoenix=phoenix)
        if branch is None:
            return

    # Name prompt
    print()
    default_name = "my-project"
    try:
        raw = input(f"  Project name [{default_name}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print("  Cancelled.")
        return

    name = _sanitize_name(raw) if raw else default_name
    if not name:
        print("  Invalid name.")
        return

    # Check for collisions with existing projects
    config = load_config()
    if config is not None:
        _, projects, _ = config
        if name in projects:
            print(f"  A project named '{name}' already exists in config.")
            return

    # Determine destination
    projects_dir = os.path.expanduser(settings.get("projects_directory", "~/Documents"))
    dest = os.path.join(projects_dir, name)

    if os.path.exists(dest):
        dest_display = dest.replace(os.path.expanduser("~"), "~")
        print(f"  Directory already exists: {dest_display}")
        return

    # Clone
    print()
    tag_label = f" @ {branch}" if branch else ""
    source_label = "pokeemerald-expansion" if source == "expansion" else "pokeemerald"
    print(f"  Cloning {source_label}{tag_label}...")
    print(f"  {DIM}This may take a few minutes for a full clone.{RST}")
    print()

    ok, msg = git_clone(repo_url, dest, depth=1, branch=branch)
    if not ok:
        print(f"  {RED}Clone failed: {msg}{RST}")
        # Clean up partial clone
        if os.path.exists(dest):
            shutil.rmtree(dest, ignore_errors=True)
        print()
        return

    # Register in torch.conf
    config = load_config()
    if config is None:
        print(f"  {RED}Could not load config to register project.{RST}")
        print(f"  {DIM}Run 'torch init' first.{RST}")
        print()
        return

    _, projects, loaded_settings = config
    workspace_parent = _get_workspace_parent()
    projects[name] = {"game_path": dest}

    # Create workspace directory
    workspace_root = os.path.join(os.path.expanduser(workspace_parent), "TORCH")
    project_ws = os.path.join(workspace_root, name)
    os.makedirs(project_ws, exist_ok=True)

    # Set as favourite project
    loaded_settings["favourite_project"] = name
    save_config(workspace_parent, projects, loaded_settings)

    # Summary
    dest_display = dest.replace(os.path.expanduser("~"), "~")
    print(f"  {GREEN}Project created: {name}{RST}")
    print(f"  Location: {dest_display}")
    print(f"  Source: {source_label}{tag_label}")
    print()

    if phoenix:
        print(f"  Starting SCORCH Phoenix...")
        print()
        from torch.scorch import scorch_command
        scorch_command(dest, settings, proj_name=name)
        return name

    print(f"  Run {WHITE}torch build{RST} to compile your ROM.")
    print()

    return name


def _pick_version(versions, phoenix=False):
    """Show a paginated version list and return the selected tag string, or None."""
    # Phoenix ceiling: versions >= FRLG_BUILD are not yet supported
    from torch.expansion_compat import FRLG_BUILD
    _PHOENIX_CEILING = FRLG_BUILD

    def _is_blocked(v):
        return phoenix and v >= _PHOENIX_CEILING

    # Find the default version (latest, or latest supported in phoenix mode)
    default_idx = 0
    if phoenix:
        for i, v in enumerate(versions):
            if v < _PHOENIX_CEILING:
                default_idx = i
                break

    total = len(versions)
    offset = 0

    while True:
        page = versions[offset:offset + _PAGE_SIZE]
        end = min(offset + _PAGE_SIZE, total)

        print(f"  {WHITE}Select version{RST} {DIM}({offset + 1}-{end} of {total}){RST}:")
        print()

        for i, (major, minor, patch) in enumerate(page):
            idx = offset + i + 1
            label = f"{major}.{minor}.{patch}"
            if _is_blocked((major, minor, patch)):
                print(f"    {DIM}[{idx}] {label} (Phoenix not yet supported){RST}")
            elif phoenix and idx == default_idx + 1:
                print(f"    [{idx}] {label} {GREEN}(latest supported){RST}")
            elif not phoenix and idx == 1:
                print(f"    [{idx}] {label} {GREEN}(latest){RST}")
            else:
                print(f"    [{idx}] {label}")

        print()

        # Navigation hint
        hints = []
        if end < total:
            hints.append("Enter = more")
        if offset > 0:
            hints.append("b = back")
        hint_str = f" {DIM}({', '.join(hints)}){RST}" if hints else ""

        default_label = default_idx + 1
        try:
            raw = input(f"  Version [{default_label}]{hint_str}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print("  Cancelled.")
            return None

        if not raw:
            if offset == 0:
                v = versions[default_idx]
                return f"expansion/{v[0]}.{v[1]}.{v[2]}"
            else:
                # Scroll forward
                if end < total:
                    offset = end
                continue

        if raw.lower() == "b" and offset > 0:
            offset = max(0, offset - _PAGE_SIZE)
            continue

        try:
            choice = int(raw)
        except ValueError:
            print("  Invalid selection.")
            continue

        if choice < 1 or choice > total:
            print(f"  Enter a number from 1 to {total}.")
            continue

        v = versions[choice - 1]
        if _is_blocked(v):
            print(f"  Phoenix does not yet support v{v[0]}.{v[1]}.{v[2]}.")
            continue

        return f"expansion/{v[0]}.{v[1]}.{v[2]}"
