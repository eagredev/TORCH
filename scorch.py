"""Scorched Earth — nuclear vanilla removal wizard.

Unlike the conservative `torch clean` tool which only removes items that
are safely unreferenced, scorch nukes ALL vanilla content and patches
C source files so the engine can still boot.

Usage:
    torch scorch          Interactive wizard (scan -> confirm -> nuke -> patch -> build)
    torch scorch plan     Dry-run: show what would be removed without touching files
    torch scorch restore  Restore from a scorch snapshot
"""
# TORCH_MODULE: Scorched Earth
# TORCH_GROUP: Tools
import os
from datetime import datetime

from torch.ui import print_logo, _set_terminal_title, _offer_build, _k, clear_screen
from torch.cleanup_scanner import has_sentinel
from torch.scorch_scanner import build_scorch_plan, ScorchPlan
from torch.scorch_writer import (
    create_scorch_snapshot, restore_scorch_snapshot,
    list_scorch_snapshots, execute_scorch, ScorchResult,
)
from torch.scorch_patcher import apply_patches, PatchReport
from torch.colours import GOLD, DGOLD, WHITE, CYAN, GREEN, RED, DIM, RST, BAR


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def scorch_command(game_path, settings, args=None, proj_name=None):
    """Main entry point for torch scorch."""
    if args is None:
        args = []

    _set_terminal_title("TORCH \u2014 Scorched Earth")

    if not args:
        _scorch_wizard(game_path, settings, proj_name=proj_name)
        return

    sub = args[0].lower()
    if sub == "plan":
        _plan_mode(game_path, settings, proj_name=proj_name)
    elif sub == "restore":
        _restore_menu(game_path, settings, proj_name=proj_name)
    else:
        print(f"  Unknown scorch subcommand: {sub}")
        print()
        print("  Usage:")
        print("    torch scorch              Interactive wizard")
        print("    torch scorch plan         Dry-run report (no changes)")
        print("    torch scorch restore      Restore from snapshot")


# ============================================================
# PRE-FLIGHT CHECKS
# ============================================================

def _preflight_checks(game_path):
    """Run pre-flight checks.  Returns list of warning strings."""
    warnings = []

    if not os.path.isdir(game_path):
        warnings.append(f"Game path not found: {game_path}")
        return warnings

    groups_file = os.path.join(game_path, "data", "maps", "map_groups.json")
    if not os.path.isfile(groups_file):
        warnings.append("map_groups.json not found -- cannot detect vanilla maps")
    elif not has_sentinel(game_path):
        warnings.append("Vanilla map sentinel not found in map_groups.json")

    # Version check: Phoenix is validated up to v1.14.x.
    # v1.15.0+ adds FRLG content that requires additional patcher work.
    from torch.expansion_compat import detect_expansion_version, version_str, FRLG_BUILD
    version = detect_expansion_version(game_path)
    if version and version >= FRLG_BUILD:
        warnings.append(
            f"Expansion v{version_str(version)} detected -- Phoenix is "
            f"validated up to v1.14.x.  v1.15.0+ adds FRLG content that "
            f"may not build cleanly after scorch.  Proceed with caution"
        )

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
                n_changed = len(result.stdout.strip().splitlines())
                warnings.append(
                    f"Git repo has {n_changed} uncommitted change(s) -- "
                    "strongly recommend committing first"
                )
        except Exception:
            pass

    return warnings


# ============================================================
# PLAN DISPLAY
# ============================================================

def _display_plan(plan):
    """Pretty-print the scorch plan summary."""
    summary = plan.summary()

    print(f"  {WHITE}{'Category':<16} {'Nuke':>8}   {'Keep':>8}{RST}")
    print(f"  {DIM}" + "\u2500" * 36 + f"{RST}")

    labels = {
        "maps":       "Maps",
        "layouts":    "Layouts",
        "trainers":   "Trainers",
        "encounters": "Encounters",
        "scripts":    "Scripts",
        "tilesets":   "Tilesets",
        "mapsecs":    "Map Sections",
        "heal_locs":  "Heal Locations",
        "c_patches":  "C Source Patches",
    }

    total_nuke = 0
    total_keep = 0
    for cat_id, (nuke, keep) in summary.items():
        label = labels.get(cat_id, cat_id)
        nuke_str = f"{RED}{nuke:>8}{RST}" if nuke > 0 else f"{DIM}{'0':>8}{RST}"
        keep_str = f"{GREEN}{keep:>8}{RST}" if keep > 0 else f"{DIM}{'0':>8}{RST}"
        print(f"  {label:<16} {nuke_str}   {keep_str}")
        total_nuke += nuke
        total_keep += keep

    print(f"  {DIM}" + "\u2500" * 36 + f"{RST}")
    print(f"  {WHITE}{'Total':<16}{RST} "
          f"{RED}{total_nuke:>8}{RST}   "
          f"{GREEN}{total_keep:>8}{RST}")
    print()


def _display_patch_targets(plan):
    """Show C source files that will be patched."""
    if not plan.c_patch_targets:
        return
    print(f"  {WHITE}C Source Patches:{RST}")
    for target in plan.c_patch_targets:
        print(f"    {DGOLD}\u2022{RST} {target['rel_path']}")
        print(f"      {DIM}{target['reason']}{RST}")
    print()


# ============================================================
# PLAN MODE (dry run)
# ============================================================

def _plan_mode(game_path, settings, proj_name=None):
    """Scan and show the scorch plan without touching any files."""
    clear_screen()
    print_logo("Scorched Earth", proj_name)
    print(BAR)
    print(f"   {WHITE}SCORCHED EARTH \u2014 DRY RUN{RST}")
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

    print(f"  {WHITE}Scanning...{RST}")
    plan = build_scorch_plan(game_path)
    print()

    if plan.errors:
        for err in plan.errors:
            print(f"  {RED}! {err}{RST}")
        print()

    _display_plan(plan)
    _display_patch_targets(plan)

    # Save report to file
    report_path = _save_plan_report(game_path, plan)
    if report_path:
        print(f"  {DIM}Report saved: {report_path}{RST}")
        print()

    print(f"  {DIM}This is a dry run. No files were changed.{RST}")
    print(f"  {DIM}Run {GOLD}torch scorch{DIM} to execute.{RST}")
    print()
    input("  Press Enter to go back > ")


def _save_plan_report(game_path, plan):
    """Save a text report of the scorch plan."""
    report_dir = os.path.join(game_path, "backups", "scorch")
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"scorch_plan_{timestamp}.txt")

    lines = []
    lines.append(f"TORCH Scorched Earth Plan -- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)
    lines.append("")

    summary = plan.summary()
    for cat_id, (nuke, keep) in summary.items():
        lines.append(f"  {cat_id:<16}  nuke: {nuke:>6}   keep: {keep:>6}")
    lines.append("")

    lines.append("MAPS TO NUKE:")
    for name in sorted(plan.nuke_maps):
        lines.append(f"  - {name}")
    lines.append("")

    lines.append("MAPS TO KEEP:")
    for name in sorted(plan.keep_maps):
        lines.append(f"  + {name}")
    lines.append("")

    lines.append("VANILLA TRAINERS TO REMOVE:")
    for const, tid in plan.vanilla_trainers[:20]:
        lines.append(f"  - {const} (ID {tid})")
    if len(plan.vanilla_trainers) > 20:
        lines.append(f"  ... and {len(plan.vanilla_trainers) - 20} more")
    lines.append("")

    lines.append("C SOURCE PATCHES:")
    for target in plan.c_patch_targets:
        lines.append(f"  {target['rel_path']}: {target['reason']}")
    lines.append("")

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return report_path
    except OSError:
        return None


# ============================================================
# INTERACTIVE WIZARD
# ============================================================

def _scorch_wizard(game_path, settings, proj_name=None):
    """Full interactive wizard: scan -> confirm -> snapshot -> nuke -> patch -> build."""
    clear_screen()
    print_logo("Scorched Earth", proj_name)
    print(BAR)
    print(f"   {RED}SCORCHED EARTH{RST}")
    print(BAR)
    print()
    print(f"  {RED}WARNING:{RST} This will {RED}permanently remove ALL vanilla content{RST}")
    print(f"  from your game project.  A snapshot will be created first, but")
    print(f"  this operation is designed to be irreversible in practice.")
    print()
    print(f"  This is a {WHITE}one-shot nuclear option{RST} -- use {GOLD}torch clean{RST} for")
    print(f"  conservative, item-by-item removal instead.")
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

    # Scan
    print(f"  {WHITE}Scanning all content...{RST}")
    plan = build_scorch_plan(game_path)
    print()

    if plan.errors:
        for err in plan.errors:
            print(f"  {RED}! {err}{RST}")
        print()
        if any("at least one custom map" in e for e in plan.errors):
            print("  Cannot proceed without custom maps.")
            print()
            input("  Press Enter to go back > ")
            return

    _display_plan(plan)
    _display_patch_targets(plan)

    # Confirm
    print(f"  {_k('y')} {DIM}Execute scorch{RST}    "
          f"{_k('p')} {DIM}Save plan report{RST}    "
          f"{_k('q')} {DIM}Cancel{RST}")
    print()

    try:
        choice = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if choice == "p":
        rpath = _save_plan_report(game_path, plan)
        if rpath:
            print(f"  Report saved: {rpath}")
        print()
        input("  Press Enter to go back > ")
        return

    if choice != "y":
        return

    # Double-confirm
    print()
    print(f"  {RED}Are you sure?{RST}  Type '{WHITE}SCORCH{RST}' to confirm:")
    print()
    try:
        confirm = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if confirm != "SCORCH":
        print("  Aborted.")
        print()
        input("  Press Enter to go back > ")
        return

    # Execute
    print()
    _execute_scorch(game_path, plan, settings)


def _execute_scorch(game_path, plan, settings):
    """Run the scorch pipeline: snapshot -> remove -> patch -> build."""

    # Step 1: Snapshot
    print(f"  {WHITE}[1/4] Creating snapshot...{RST}")
    snapshot_path = create_scorch_snapshot(game_path, plan)
    if not snapshot_path:
        print(f"  {RED}Failed to create snapshot.  Aborting.{RST}")
        print()
        input("  Press Enter to go back > ")
        return
    print(f"  {GREEN}Snapshot:{RST} {os.path.basename(snapshot_path)}")
    print()

    # Step 2: Remove vanilla content
    print(f"  {WHITE}[2/4] Removing vanilla content...{RST}")
    scorch_result = execute_scorch(game_path, plan)
    print(f"  {GREEN}Removed:{RST} "
          f"{scorch_result.maps_removed} maps, "
          f"{scorch_result.trainers_removed} trainers, "
          f"{scorch_result.encounters_removed} encounters, "
          f"{scorch_result.scripts_removed} scripts, "
          f"{scorch_result.tilesets_removed} tilesets, "
          f"{scorch_result.mapsecs_removed} map sections")
    if scorch_result.errors:
        for err in scorch_result.errors:
            print(f"  {RED}! {err}{RST}")
    print()

    # Step 3: Patch C source
    print(f"  {WHITE}[3/4] Patching C source files...{RST}")
    patch_report = apply_patches(game_path, plan)
    print(f"  {GREEN}Patched:{RST} {len(patch_report.patches)} file(s)")
    for patch in patch_report.patches:
        print(f"    {DGOLD}\u2022{RST} {patch['file']}: {patch['action']}")
    if patch_report.errors:
        for err in patch_report.errors:
            print(f"  {RED}! {err}{RST}")
    print()

    # Step 4: Save execution report
    _save_execution_report(game_path, scorch_result, patch_report)

    # Offer build
    print(f"  {WHITE}[4/4] Done.{RST}")
    print()
    print(f"  {DIM}Restore with: {GOLD}torch scorch restore{RST}")
    print()
    _offer_build(game_path)


def _save_execution_report(game_path, scorch_result, patch_report):
    """Save a text report of what was done."""
    report_dir = os.path.join(game_path, "backups", "scorch")
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"scorch_exec_{timestamp}.txt")

    lines = []
    lines.append(f"TORCH Scorched Earth Execution -- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Maps removed:       {scorch_result.maps_removed}")
    lines.append(f"Layouts removed:    {scorch_result.layouts_removed}")
    lines.append(f"Trainers removed:   {scorch_result.trainers_removed}")
    lines.append(f"Encounters removed: {scorch_result.encounters_removed}")
    lines.append(f"Scripts removed:    {scorch_result.scripts_removed}")
    lines.append(f"Tilesets removed:   {scorch_result.tilesets_removed}")
    lines.append(f"Map sections removed: {scorch_result.mapsecs_removed}")
    lines.append(f"Map sections created: {scorch_result.mapsecs_created}")
    lines.append(f"Maps reassigned:    {scorch_result.mapsecs_reassigned}")
    lines.append("")

    if scorch_result.errors:
        lines.append("REMOVAL ERRORS:")
        for err in scorch_result.errors:
            lines.append(f"  ! {err}")
        lines.append("")

    lines.append("C SOURCE PATCHES:")
    for patch in patch_report.patches:
        lines.append(f"  {patch['file']}: {patch['action']}")
        if patch["detail"]:
            lines.append(f"    {patch['detail']}")
    lines.append("")

    if patch_report.errors:
        lines.append("PATCH ERRORS:")
        for err in patch_report.errors:
            lines.append(f"  ! {err}")
        lines.append("")

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass


# ============================================================
# RESTORE
# ============================================================

def _restore_menu(game_path, settings, proj_name=None):
    """List and restore from scorch snapshots."""
    clear_screen()
    print_logo("Scorched Earth", proj_name)
    print(BAR)
    print(f"   {WHITE}RESTORE FROM SNAPSHOT{RST}")
    print(BAR)
    print()

    snapshots = list_scorch_snapshots(game_path)
    if not snapshots:
        print(f"  {DIM}No scorch snapshots found.{RST}")
        print()
        input("  Press Enter to go back > ")
        return

    for i, snap in enumerate(snapshots):
        print(f"  {_k(str(i + 1))} {snap['display_time']}  {DIM}{snap['filename']}{RST}")
    print()
    print(f"  {_k('q')} {DIM}Cancel{RST}")
    print()

    try:
        choice = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if choice in ("q", ""):
        return

    try:
        idx = int(choice) - 1
    except ValueError:
        print("  Invalid choice.")
        input("  Press Enter > ")
        return

    if idx < 0 or idx >= len(snapshots):
        print("  Invalid choice.")
        input("  Press Enter > ")
        return

    snap = snapshots[idx]
    print()
    print(f"  Restoring from {WHITE}{snap['filename']}{RST}...")
    restored = restore_scorch_snapshot(game_path, snap["path"])
    if restored is not None:
        print(f"  {GREEN}Restored {len(restored)} file(s).{RST}")
        print()
        _offer_build(game_path)
    else:
        print(f"  {RED}Restore failed.{RST}")
        print()
        input("  Press Enter to go back > ")
