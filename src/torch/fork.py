"""TORCH Fork — create, list, and delete project copies."""
# TORCH_MODULE: Fork
# TORCH_GROUP: Core

import os
import sys
import json
import shutil
import re
import tempfile
import configparser
from datetime import datetime
from pathlib import Path

import subprocess

from torch.config import CONFIG_PATH, load_config, save_config
from torch.colours import GOLD, WHITE, DIM, RED, GREEN, RST

# ── Paths ────────────────────────────────────────────────────────────────────
_FORKS_JSON = os.path.expanduser("~/.config/torch/forks.json")
_SANDBOXES_JSON_LEGACY = os.path.expanduser("~/.config/torch/sandboxes.json")


# ── JSON registry helpers ────────────────────────────────────────────────────

def _load_registry():
    """Load the forks registry from JSON.  Returns a list of dicts.

    On first call, auto-migrates from sandboxes.json if it exists.
    """
    if not os.path.isfile(_FORKS_JSON):
        if os.path.isfile(_SANDBOXES_JSON_LEGACY):
            _migrate_sandboxes()
    if not os.path.isfile(_FORKS_JSON):
        return []
    try:
        with open(_FORKS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("forks", [])
    except (json.JSONDecodeError, OSError):
        return []


def _save_registry(forks):
    """Atomically write the forks list to JSON."""
    os.makedirs(os.path.dirname(_FORKS_JSON), exist_ok=True)
    payload = json.dumps({"forks": forks}, indent=2)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_FORKS_JSON), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload + "\n")
        os.replace(tmp, _FORKS_JSON)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _dir_size_mb(path):
    """Return total size of all files under *path* in MB."""
    total = 0
    for f in Path(path).rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total // (1024 * 1024)


def _next_default_name(forks):
    """Return 'test-N' where N is the next unused number."""
    used = set()
    for fk in forks:
        m = re.match(r"^test-(\d+)$", fk.get("name", ""))
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return f"test-{n}"


def _sanitize_name(raw):
    """Sanitize fork name: lowercase, alphanumeric + hyphens, max 30 chars."""
    name = raw.strip().lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:30]


# ── Migration ────────────────────────────────────────────────────────────────

def _migrate_sandboxes():
    """One-time migration from sandboxes.json to forks.json.

    For each entry:
      1. Rename sandbox-{name}/ to {name}/ on disk (if exists and target free)
      2. Update torch.conf: rename [project:Sandbox: name] to [project:name],
         update game_path, favourite_project
      3. Save as forks.json, delete sandboxes.json
    """
    try:
        with open(_SANDBOXES_JSON_LEGACY, encoding="utf-8") as f:
            data = json.load(f)
        old_entries = data.get("sandboxes", [])
    except (json.JSONDecodeError, OSError):
        return

    if not old_entries:
        # Empty registry — just rename
        try:
            os.rename(_SANDBOXES_JSON_LEGACY, _FORKS_JSON)
        except OSError:
            pass
        return

    # Load config for project renaming
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)

    # Collect all existing project names for collision detection
    existing_projects = set()
    for section in cfg.sections():
        if section.startswith("project:"):
            existing_projects.add(section[len("project:"):])

    workspace_parent = "~"
    if "torch" in cfg:
        workspace_parent = cfg["torch"].get("workspace_parent", "~")
    workspace_root = os.path.join(os.path.expanduser(workspace_parent), "TORCH")

    migrated = []
    for entry in old_entries:
        name = entry.get("name", "")
        old_path = entry.get("game_path", "")
        old_proj_name = f"Sandbox: {name}"

        # Determine new project name (collision guard)
        new_proj_name = name
        if new_proj_name in existing_projects and old_proj_name != new_proj_name:
            new_proj_name = f"{name}-fork"
            # Still collides? Add number
            counter = 2
            while new_proj_name in existing_projects:
                new_proj_name = f"{name}-fork-{counter}"
                counter += 1

        # Rename directory: sandbox-{name}/ -> {name}/
        new_path = old_path
        if old_path:
            parent_dir = os.path.dirname(old_path.rstrip("/"))
            old_basename = os.path.basename(old_path.rstrip("/"))
            if old_basename.startswith("sandbox-"):
                new_basename = old_basename[len("sandbox-"):]
                candidate_path = os.path.join(parent_dir, new_basename)
                if os.path.isdir(old_path) and not os.path.exists(candidate_path):
                    try:
                        os.rename(old_path, candidate_path)
                        new_path = candidate_path
                    except OSError:
                        new_path = old_path  # keep old path if rename fails

        # Update torch.conf project section
        old_section = f"project:{old_proj_name}"
        new_section = f"project:{new_proj_name}"
        if cfg.has_section(old_section):
            cfg.remove_section(old_section)
        if not cfg.has_section(new_section):
            cfg.add_section(new_section)
        cfg.set(new_section, "game_path", new_path)

        # Rename workspace directory
        old_ws = os.path.join(workspace_root, old_proj_name)
        new_ws = os.path.join(workspace_root, new_proj_name)
        if os.path.isdir(old_ws) and not os.path.exists(new_ws):
            try:
                os.rename(old_ws, new_ws)
            except OSError:
                pass

        # Update favourite_project if it pointed to the old name
        if "torch" in cfg:
            fav = cfg["torch"].get("favourite_project", "")
            if fav == old_proj_name:
                cfg.set("torch", "favourite_project", new_proj_name)

        existing_projects.add(new_proj_name)

        migrated.append({
            "name": name,
            "source_project": entry.get("source_project", ""),
            "game_path": new_path,
            "created": entry.get("created", ""),
        })

    # Write updated config
    try:
        with open(CONFIG_PATH, "w") as f:
            cfg.write(f)
    except OSError:
        pass

    # Save new registry
    os.makedirs(os.path.dirname(_FORKS_JSON), exist_ok=True)
    payload = json.dumps({"forks": migrated}, indent=2)
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_FORKS_JSON), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload + "\n")
        os.replace(tmp, _FORKS_JSON)
    except OSError:
        return

    # Remove old registry
    try:
        os.remove(_SANDBOXES_JSON_LEGACY)
    except OSError:
        pass

    count = len(migrated)
    label = "fork" if count == 1 else "forks"
    print(f"  {DIM}Migrated {count} {label} from sandboxes.json{RST}")


# ── Entry point ──────────────────────────────────────────────────────────────

def fork_command(args, game_path, settings, proj_name=""):
    """Route fork subcommands."""
    sub = args[0] if args else "create"

    if sub == "create":
        return _create_fork(game_path, settings, proj_name)
    elif sub == "list":
        _list_forks()
    elif sub == "delete":
        if len(args) < 2:
            print("  Usage: torch fork delete <name>")
            sys.exit(1)
        _delete_fork(args[1], settings)
    elif sub == "open":
        if len(args) < 2:
            print("  Usage: torch fork open <name>")
            sys.exit(1)
        _open_fork(args[1], settings)
    else:
        print(f"  Unknown command: {sub}")
        print()
        print(f"  Usage:")
        print(f"    torch fork                 Create a new fork")
        print(f"    torch fork create          Create a new fork")
        print(f"    torch fork list            List all forks")
        print(f"    torch fork delete <name>   Delete a fork")
        print(f"    torch fork open <name>     Switch to a fork")
        sys.exit(1)


# ── Create ───────────────────────────────────────────────────────────────────

def _pick_source_project(game_path, proj_name):
    """Show project picker if multiple projects exist.

    Returns (game_path, proj_name, multi) or None on cancel.
    *multi* is True when the picker was displayed (2+ projects).
    """
    home = os.path.expanduser("~")
    config = load_config()
    if config is None:
        return game_path, proj_name, False

    _, projects, _ = config
    if len(projects) < 2:
        return game_path, proj_name, False

    # Sort alphabetically, default to the currently active project
    sorted_names = sorted(projects.keys())
    default_idx = 0
    for i, name in enumerate(sorted_names):
        if name == proj_name:
            default_idx = i
            break

    print(f"  Select source project {DIM}({len(sorted_names)} available){RST}:")
    for i, name in enumerate(sorted_names):
        path_display = projects[name]["game_path"].replace(home, "~")
        print(f"    [{i + 1}] {WHITE}{name}{RST}    {DIM}{path_display}{RST}")
    print()

    try:
        raw = input(f"  Source [{default_idx + 1}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print("  Cancelled.")
        return None

    if not raw:
        choice = default_idx
    else:
        try:
            choice = int(raw) - 1
        except ValueError:
            print("  Invalid selection.")
            return None
        if choice < 0 or choice >= len(sorted_names):
            print("  Invalid selection.")
            return None

    chosen_name = sorted_names[choice]
    chosen_path = projects[chosen_name]["game_path"]
    return chosen_path, chosen_name, True


def _select_source_and_name(game_path, proj_name, default_name):
    """Run the source picker + name prompt loop.

    Returns (game_path, proj_name, name) or None on cancel.
    Blank input at the name prompt loops back to the picker (multi-project only).
    """
    while True:
        result = _pick_source_project(game_path, proj_name)
        if result is None:
            return None
        chosen_path, chosen_name, multi = result

        gp_display = chosen_path.replace(os.path.expanduser("~"), "~")
        source_label = chosen_name or os.path.basename(chosen_path.rstrip("/"))

        print(f"  Source: {WHITE}{source_label}{RST} {DIM}({gp_display}){RST}")
        print()

        back_hint = f" {DIM}(blank = back){RST}" if multi else ""
        try:
            raw = input(f"  Fork name [{default_name}]{back_hint}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print("  Cancelled.")
            return None

        if not raw and multi:
            print()
            continue  # back to project picker

        name = _sanitize_name(raw) if raw else default_name
        if not name:
            print("  Invalid name.")
            return None

        return chosen_path, chosen_name, name


def _name_collides(name, forks):
    """Check if *name* collides with any fork or any config project."""
    # Check fork registry
    for fk in forks:
        if fk.get("name") == name:
            return True, "fork"
    # Check all projects in config
    config = load_config()
    if config is not None:
        _, projects, _ = config
        if name in projects:
            return True, "project"
    return False, None


def _git_baseline_commit(dest, source_name):
    """Stage and commit all changes in a forked repo so it starts clean.

    After copytree (which skips build/ and backups/), the fork may have
    dirty git state: uncommitted changes from the source project, plus
    deleted files from the ignored directories.  This commits everything
    so downstream tools (like SCORCH Phoenix) see a clean working tree.

    Non-fatal — failures are printed as warnings.
    """
    git_dir = os.path.join(dest, ".git")
    if not os.path.isdir(git_dir):
        return

    try:
        # Stage everything (catches modifications, deletions, new files)
        subprocess.run(
            ["git", "add", "-A"],
            cwd=dest, capture_output=True, text=True, timeout=30,
        )
        # Check if there's actually anything to commit
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=dest, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return  # Nothing to commit or git error

        n = len(result.stdout.strip().splitlines())
        subprocess.run(
            ["git", "commit", "-m",
             f"Fork baseline from {source_name}\n\n"
             f"Auto-committed {n} change(s) inherited from source project."],
            cwd=dest, capture_output=True, text=True, timeout=30,
        )
        print(f"  Committed {n} inherited change(s)")
    except Exception:
        print(f"  {DIM}(could not auto-commit — git state may be dirty){RST}")


def _create_fork(game_path, settings, proj_name):
    """Interactive wizard to create a project copy."""
    forks = _load_registry()
    default_name = _next_default_name(forks)

    print()
    print(f"  {GOLD}+-- Fork Project ----------------------------+{RST}")
    print()
    print(f"  Create an independent copy of your project.")
    print()

    selection = _select_source_and_name(game_path, proj_name, default_name)
    if selection is None:
        return
    game_path, proj_name, name = selection

    # Check for duplicates — auto-clean stale entries (directory gone)
    for fk in forks:
        if fk.get("name") == name:
            existing_path = fk.get("game_path", "")
            if existing_path and not os.path.isdir(existing_path):
                # Stale entry: directory was deleted outside TORCH
                forks = [f for f in forks if f.get("name") != name]
                try:
                    _save_registry(forks)
                except OSError:
                    pass
                print(f"  {DIM}Removed stale entry for '{name}' (directory missing){RST}")
                break
            print(f"  A fork named '{name}' already exists.")
            return

    # Check against all config projects too
    config = load_config()
    if config is not None:
        _, projects, _ = config
        if name in projects:
            print(f"  A project named '{name}' already exists in config.")
            return

    projects_dir = os.path.expanduser(settings.get("projects_directory", "~/Documents"))
    dest = os.path.join(projects_dir, name)
    if os.path.exists(dest):
        print(f"  Directory already exists: {dest}")
        return

    # Verify source exists
    if not os.path.isdir(game_path):
        print(f"  Source project not found: {game_path}")
        return

    # Copy project (excluding build/ and backups/)
    print()
    print(f"  Copying project... ", end="", flush=True)
    try:
        shutil.copytree(
            game_path, dest, dirs_exist_ok=False,
            ignore=shutil.ignore_patterns("build", "backups"),
        )
    except (shutil.Error, OSError, PermissionError) as e:
        print(f"failed")
        print(f"  ERROR: {e}")
        return

    size_mb = _dir_size_mb(dest)
    print(f"done ({size_mb} MB)")

    # Baseline commit — ensure fork starts with a clean git state
    source_label = proj_name or os.path.basename(game_path.rstrip("/"))
    _git_baseline_commit(dest, source_label)

    # Register in forks.json
    entry = {
        "name": name,
        "source_project": proj_name or os.path.basename(game_path.rstrip("/")),
        "game_path": dest,
        "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    forks.append(entry)
    try:
        _save_registry(forks)
    except OSError as e:
        print(f"  WARNING: Could not save registry: {e}")

    # Register as TORCH project (plain name, no prefix)
    _register_fork_project(name, dest, settings, source_proj_name=proj_name)

    # Auto-enroll workspace maps (copy source registry if available)
    workspace_parent = _get_workspace_parent()
    workspace_root = os.path.join(os.path.expanduser(workspace_parent), "TORCH")
    fork_project_dir = os.path.join(workspace_root, name)
    source_project_dir = os.path.join(workspace_root, proj_name) if proj_name else None
    enrolled_count = _auto_enroll_fork(fork_project_dir, dest, source_project_dir)

    # Persist project switch to config (match _open_fork pattern)
    config = load_config()
    if config is not None:
        _, projects, loaded_settings = config
        workspace_parent = _get_workspace_parent()
        loaded_settings["favourite_project"] = name
        save_config(workspace_parent, projects, loaded_settings)

    # Summary
    dest_display = dest.replace(os.path.expanduser("~"), "~")
    print()
    print(f"  {GREEN}Fork created: {name}{RST}")
    print(f"  Location: {dest_display}")
    print(f"  Size: ~{size_mb} MB")
    if enrolled_count:
        print(f"  Enrolled: {enrolled_count} map(s)")
    print(f"  Switching to: {name}")
    print()

    return name


def _auto_enroll_fork(project_dir, game_path, source_project_dir=None):
    """Auto-enroll workspace maps in a newly forked project.

    If the source project has a registry, copies it so that sync state
    (OK, NEW, STALE, etc.) is preserved faithfully.  Otherwise falls back
    to bulk_enroll with no sync assumption.

    Returns the number of maps enrolled.
    """
    try:
        from torch.registry import (
            REGISTRY_FILENAME, load_registry, save_registry, bulk_enroll,
        )
        # Try to copy the source registry first
        if source_project_dir:
            source_reg_path = os.path.join(source_project_dir, REGISTRY_FILENAME)
            if os.path.isfile(source_reg_path):
                dest_reg_path = os.path.join(project_dir, REGISTRY_FILENAME)
                shutil.copy2(source_reg_path, dest_reg_path)
                registry = load_registry(project_dir)
                return len(registry.get("maps", {}))
        # No source registry — enroll from scratch (no sync assumption)
        count, _ = bulk_enroll(project_dir, game_path)
        return count
    except Exception:
        return 0


def _register_fork_project(fork_proj_name, dest, settings,
                            source_proj_name=""):
    """Add a fork as a TORCH project in torch.conf.

    When *source_proj_name* is provided, copy the source project's TORCH
    workspace (script .txt files, setup.pory, etc.) into the fork's own
    workspace so that Script Studio has full script data from the start.
    """
    config = load_config()
    if config is None:
        print(f"  WARNING: Could not load config to register project.")
        return
    _, projects, loaded_settings = config
    workspace_parent = _get_workspace_parent()
    if fork_proj_name in projects:
        return  # already registered
    projects[fork_proj_name] = {"game_path": dest}
    workspace_root = os.path.join(os.path.expanduser(workspace_parent), "TORCH")
    fork_ws = os.path.join(workspace_root, fork_proj_name)
    # Copy source workspace content if available
    if source_proj_name:
        source_ws = os.path.join(workspace_root, source_proj_name)
        _copy_workspace(source_ws, fork_ws)
    else:
        os.makedirs(fork_ws, exist_ok=True)
    save_config(workspace_parent, projects, loaded_settings)
    print(f"  Registered as TORCH project: {fork_proj_name}")


def _get_workspace_parent():
    """Read workspace_parent from torch.conf."""
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    if "torch" in cfg:
        return cfg["torch"].get("workspace_parent", "~")
    return "~"


def _copy_workspace(source_ws, dest_ws):
    """Copy a project's TORCH workspace into *dest_ws*.

    Only copies map subdirectories (those containing script .txt files or
    setup.pory).  Skips top-level non-directory items and the backups/
    directory inside each map folder (those are source-project snapshots).
    Falls back to creating an empty directory if the source doesn't exist.
    """
    if not os.path.isdir(source_ws):
        os.makedirs(dest_ws, exist_ok=True)
        return
    try:
        shutil.copytree(
            source_ws, dest_ws, dirs_exist_ok=False,
            ignore=shutil.ignore_patterns("backups"),
        )
    except (shutil.Error, OSError, PermissionError):
        # Best-effort: ensure the directory at least exists
        os.makedirs(dest_ws, exist_ok=True)


# ── List ─────────────────────────────────────────────────────────────────────

def _list_forks():
    """Display all registered forks with size and status."""
    forks = _load_registry()

    print()
    print(f"  {GOLD}+-- Project Forks --------------------------+{RST}")
    print()

    if not forks:
        print(f"  {DIM}No forks found.{RST}")
        print(f"  {DIM}Create one from TORCH Vault or: torch fork{RST}")
        print()
        return

    # Column headers
    print(f"  {DIM}{'Name':<14}{'Source':<20}{'Size':>8}   {'Created'}{RST}")
    print()

    total_mb = 0
    missing = []

    for fk in forks:
        name = fk.get("name", "?")
        source = fk.get("source_project", "?")
        fk_path = fk.get("game_path", "")
        created_raw = fk.get("created", "")

        # Format created date
        created_display = _format_created(created_raw)

        # Truncate source for display
        if len(source) > 18:
            source = source[:17] + "..."

        if os.path.isdir(fk_path):
            size = _dir_size_mb(fk_path)
            total_mb += size
            size_str = f"{size} MB"
            print(f"  {WHITE}{name:<14}{RST}{source:<20}{size_str:>8}   {created_display}")
        else:
            missing.append(name)
            print(f"  {RED}{name:<14}{RST}{source:<20}{'[MISSING]':>8}   {created_display}")

    print()
    active = len(forks) - len(missing)
    label = "fork" if active == 1 else "forks"
    print(f"  {active} {label}  |  {total_mb} MB total")

    if missing:
        print()
        _offer_cleanup(forks, missing)

    print()


def _format_created(raw):
    """Format ISO timestamp to short display like 'Feb 22, 10:30'."""
    try:
        dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%b %d, %H:%M")
    except (ValueError, TypeError):
        return raw or "?"


def _offer_cleanup(forks, missing_names):
    """Offer to remove registry entries for missing forks."""
    names = ", ".join(missing_names)
    print(f"  {DIM}Missing on disk: {names}{RST}")
    try:
        ans = input(f"  Remove missing entries from registry? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if ans != "y":
        return
    cleaned = [fk for fk in forks if fk.get("name") not in missing_names]
    try:
        _save_registry(cleaned)
        print(f"  Cleaned {len(missing_names)} missing entry(s).")
    except OSError as e:
        print(f"  ERROR: Could not save registry: {e}")


# ── Delete ───────────────────────────────────────────────────────────────────

def _pick_fork_to_delete():
    """Show a menu of existing forks and return the selected name, or None."""
    forks = _load_registry()
    if not forks:
        print()
        print(f"  {DIM}No forks found.{RST}")
        print()
        return None

    print()
    print(f"  {GOLD}Select a fork to delete:{RST}")
    print()
    for i, fk in enumerate(forks):
        name = fk.get("name", "?")
        source = fk.get("source_project", "?")
        path_display = fk.get("game_path", "").replace(os.path.expanduser("~"), "~")
        print(f"  {GOLD}[{i + 1}]{RST} {WHITE}{name}{RST}  {DIM}(from {source}){RST}")
        print(f"       {DIM}{path_display}{RST}")
    print()

    try:
        raw = input(f"  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print("  Cancelled.")
        return None

    if not raw:
        print("  Cancelled.")
        return None

    try:
        idx = int(raw) - 1
    except ValueError:
        print("  Invalid selection.")
        return None

    if idx < 0 or idx >= len(forks):
        print("  Invalid selection.")
        return None

    return forks[idx].get("name")


def _delete_fork(name, settings):
    """Delete a fork from disk and registry."""
    forks = _load_registry()
    entry = None
    for fk in forks:
        if fk.get("name") == name:
            entry = fk
            break

    if entry is None:
        print(f"  Fork '{name}' not found in registry.")
        return

    fk_path = entry.get("game_path", "")
    path_display = fk_path.replace(os.path.expanduser("~"), "~")

    print()
    try:
        confirm = input(
            f"  Delete fork '{name}' at {path_display}?\n"
            f"  This cannot be undone. [y/N] "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        print("  Cancelled.")
        return

    if confirm != "y":
        print("  Cancelled.")
        return

    # Calculate size before deleting
    size_mb = 0
    if os.path.isdir(fk_path):
        size_mb = _dir_size_mb(fk_path)
        try:
            shutil.rmtree(fk_path)
        except (OSError, PermissionError) as e:
            print(f"  ERROR: Could not delete directory: {e}")
            return

    # Remove from registry
    cleaned = [fk for fk in forks if fk.get("name") != name]
    try:
        _save_registry(cleaned)
    except OSError as e:
        print(f"  WARNING: Could not update registry: {e}")

    # Remove TORCH project registration if it exists
    _unregister_fork_project(name, settings)

    print(f"  Deleted fork: {name} (freed ~{size_mb} MB)")
    print()


def _unregister_fork_project(name, settings):
    """Remove fork project from torch.conf and clean up its workspace.

    Checks both new-style (plain name) and legacy (Sandbox: name) registrations.
    """
    config = load_config()
    if config is None:
        return
    _, projects, loaded_settings = config
    workspace_parent = _get_workspace_parent()

    # Check both plain name and legacy Sandbox: prefix
    proj_name = None
    if name in projects:
        proj_name = name
    elif f"Sandbox: {name}" in projects:
        proj_name = f"Sandbox: {name}"

    if proj_name is None:
        return

    del projects[proj_name]
    # Clear favourite if it pointed to this fork
    if loaded_settings.get("favourite_project", "") == proj_name:
        loaded_settings["favourite_project"] = ""
    save_config(workspace_parent, projects, loaded_settings)
    # Clean up workspace directory
    workspace_root = os.path.join(os.path.expanduser(workspace_parent), "TORCH")
    fork_ws = os.path.join(workspace_root, proj_name)
    if os.path.isdir(fork_ws):
        try:
            shutil.rmtree(fork_ws)
        except (OSError, PermissionError):
            pass  # best-effort cleanup


# ── Open ─────────────────────────────────────────────────────────────────────

def _open_fork(name, settings):
    """Switch active project to a fork."""
    forks = _load_registry()
    entry = None
    for fk in forks:
        if fk.get("name") == name:
            entry = fk
            break

    if entry is None:
        print(f"  Fork '{name}' not found in registry.")
        return

    fk_path = entry.get("game_path", "")
    if not os.path.isdir(fk_path):
        print(f"  Fork directory not found: {fk_path}")
        return

    # Auto-register if not already a TORCH project (plain name)
    config = load_config()
    if config is None:
        print(f"  ERROR: Could not load config.")
        return
    _, projects, loaded_settings = config

    if name not in projects:
        source_proj = entry.get("source_project", "")
        _register_fork_project(name, fk_path, loaded_settings,
                                source_proj_name=source_proj)
        # Reload after registration
        config = load_config()
        if config is None:
            return
        _, projects, loaded_settings = config

    # Set as favourite project
    workspace_parent = _get_workspace_parent()
    loaded_settings["favourite_project"] = name
    save_config(workspace_parent, projects, loaded_settings)

    print()
    print(f"  {GREEN}Active project switched to: {name}{RST}")
    print()
