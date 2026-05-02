"""Movement Block Manager — create, edit, rename, delete movement blocks in setup.pory."""
# TORCH_MODULE: Movement Blocks
# TORCH_GROUP: Script Studio
import os
import re

from torch.data import (
    MOVEMENT_COMMAND_CATEGORIES, ALL_MOVEMENT_COMMANDS, _movement_cmd_english,
)
from torch.config import SETTINGS_DEFAULTS, _nav_keys
from torch.ui import _k, clear_screen
from torch.colours import GOLD, WHITE, CYAN, GREEN, DIM, RST, BAR
from torch.script_model import (
    _parse_setup_movement_blocks, _format_movement_block,
    _write_setup_movement_blocks, _rebuild_setup_without_block,
    _ensure_setup_pory, _find_movement_references,
)


# ============================================================
# MOVEMENT BLOCK MANAGER
# ============================================================

def _preview_movement_block(block):
    """Print a preview of a movement block's commands with English descriptions."""
    cmds = block.get("commands", [])
    if not cmds:
        print("    (empty)")
        return
    for i, cmd in enumerate(cmds, 1):
        eng = _movement_cmd_english(cmd)
        print(f"    {i:>2}. {cmd:<30s}  {eng}")


def _movement_category_picker():
    """
    Show categorized movement commands and let the user pick one.
    Returns the command string or None.
    """
    print()
    print("  Movement categories:")
    for i, (cat_name, _) in enumerate(MOVEMENT_COMMAND_CATEGORIES, 1):
        print(f"    [{i:>2}] {cat_name}")
    print(f"    [ t] Type command directly")
    print()
    choice = input("  Category > ").strip().lower()

    if choice == "t":
        cmd = input("  Command > ").strip()
        if not cmd:
            return None
        if cmd not in ALL_MOVEMENT_COMMANDS:
            print(f"  Warning: '{cmd}' is not a known command. Adding anyway.")
        return cmd

    try:
        cat_idx = int(choice) - 1
    except ValueError:
        print("  Invalid choice.")
        return None

    if cat_idx < 0 or cat_idx >= len(MOVEMENT_COMMAND_CATEGORIES):
        print("  Invalid category number.")
        return None

    cat_name, cmds = MOVEMENT_COMMAND_CATEGORIES[cat_idx]
    print()
    print(f"  {cat_name}:")
    for j, cmd in enumerate(cmds, 1):
        eng = _movement_cmd_english(cmd)
        print(f"    [{j:>2}] {cmd:<35s}  {eng}")
    print()
    pick = input("  Command # > ").strip()

    # Support #xN repeat syntax (e.g. 2x3 = command 2 repeated 3 times)
    repeat = 1
    if "x" in pick:
        parts = pick.split("x", 1)
        try:
            pick = parts[0].strip()
            repeat = int(parts[1].strip())
        except ValueError:
            print("  Invalid repeat syntax. Use #x# (e.g. 2x3).")
            return None

    try:
        cmd_idx = int(pick) - 1
    except ValueError:
        print("  Invalid choice.")
        return None

    if cmd_idx < 0 or cmd_idx >= len(cmds):
        print("  Invalid command number.")
        return None

    selected_cmd = cmds[cmd_idx]
    if repeat > 1:
        return f"{selected_cmd} * {repeat}"
    return selected_cmd


def _movement_command_builder(existing_commands=None):
    """
    Interactive command builder for movement blocks.
    Returns a list of commands or None to cancel.
    """
    commands = list(existing_commands) if existing_commands else []

    while True:
        print()
        if commands:
            print("  Current steps:")
            for i, cmd in enumerate(commands, 1):
                eng = _movement_cmd_english(cmd)
                print(f"    {i:>2}. {cmd:<30s}  {eng}")
        else:
            print("  No steps yet.")
        print()
        print(f"  {len(commands)} step{'s' if len(commands) != 1 else ''}")
        print("  [Enter] Add step  [r] Remove  [m] Move/reorder  [x] Clear all")
        print("  [d] Done  [q] Cancel")
        print()
        action = input("  > ").strip().lower()

        if action == "q":
            return None

        if action == "d":
            return commands

        if action == "x":
            commands.clear()
            print("  Cleared all steps.")
            continue

        if action == "r":
            if not commands:
                print("  Nothing to remove.")
                continue
            num = input("  Remove step # > ").strip()
            try:
                idx = int(num) - 1
                if 0 <= idx < len(commands):
                    removed = commands.pop(idx)
                    print(f"  Removed: {removed}")
                else:
                    print("  Invalid step number.")
            except ValueError:
                print("  Enter a number.")
            continue

        if action == "m":
            if len(commands) < 2:
                print("  Need at least 2 steps to reorder.")
                continue
            from_num = input("  Move step # > ").strip()
            to_num = input("  To position # > ").strip()
            try:
                from_idx = int(from_num) - 1
                to_idx = int(to_num) - 1
                if 0 <= from_idx < len(commands) and 0 <= to_idx < len(commands):
                    item = commands.pop(from_idx)
                    commands.insert(to_idx, item)
                    print(f"  Moved '{item}' to position {to_idx + 1}.")
                else:
                    print("  Invalid position.")
            except ValueError:
                print("  Enter numbers.")
            continue

        # Default action: add a step via category picker
        cmd = _movement_category_picker()
        if cmd:
            commands.append(cmd)

    return commands


def _new_movement_block(map_name, project_dir):
    """Wizard to create a new movement block."""
    setup_path = _ensure_setup_pory(map_name, project_dir)
    existing = _parse_setup_movement_blocks(setup_path)
    existing_labels = {b["label"] for b in existing}

    print()
    print("  New movement block")
    print(f"  Prefix: {map_name}_")
    print()
    short_name = input("  Short name (e.g. MovementBlockName) > ").strip()
    if not short_name:
        print("  Cancelled.")
        return

    # Auto-prefix with map name
    label = f"{map_name}_{short_name}"
    if label in existing_labels:
        print(f"  Error: '{label}' already exists.")
        input("  Press Enter > ")
        return

    print()
    print(f"  Label: {label}")
    print()
    print("  Now add movement commands.")

    commands = _movement_command_builder()
    if commands is None:
        print("  Cancelled.")
        return
    if not commands:
        print("  Error: Movement block cannot be empty.")
        input("  Press Enter > ")
        return

    # Preview and confirm
    print()
    print(f"  Preview: {label}")
    for cmd in commands:
        eng = _movement_cmd_english(cmd)
        print(f"    {cmd:<30s}  {eng}")
    print()
    confirm = input("  Save this block? [Y/n] > ").strip().lower()
    if confirm == "n":
        print("  Cancelled.")
        return

    # Write to setup.pory
    existing.append({"label": label, "commands": commands})
    with open(setup_path, "r") as f:
        original_lines = f.readlines()
    _write_setup_movement_blocks(setup_path, existing, original_lines)
    print(f"  Saved: {label} ({len(commands)} steps)")
    input("  Press Enter > ")


def _edit_movement_block(block, map_name, project_dir):
    """View/edit a single movement block."""
    setup_path = _ensure_setup_pory(map_name, project_dir)
    map_dir = os.path.join(project_dir, map_name)

    while True:
        # Re-read from disk each loop
        all_blocks = _parse_setup_movement_blocks(setup_path)
        current = None
        for b in all_blocks:
            if b["label"] == block["label"]:
                current = b
                break
        if current is None:
            print(f"  Block '{block['label']}' no longer exists.")
            input("  Press Enter > ")
            return



        print()
        print(BAR)
        print(f"   {WHITE}{current['label']}{RST}")
        print(BAR)
        print()
        _preview_movement_block(current)
        print()
        print(f"  {DIM}{len(current['commands'])} step{'s' if len(current['commands']) != 1 else ''}{RST}")
        print()

        # Check references
        refs = _find_movement_references(current["label"], map_dir)
        if refs:
            print(f"  {DIM}Referenced in {len(refs)} place{'s' if len(refs) != 1 else ''}:{RST}")
            for fname, lnum, ltext in refs[:5]:
                print(f"    {DIM}{fname}:{lnum}  {ltext.strip()}{RST}")
            if len(refs) > 5:
                print(f"    {DIM}... and {len(refs) - 5} more{RST}")
            print()

        print(f"  {_k('e')} {DIM}Edit commands{RST}  {_k('r')} {DIM}Rename{RST}  {_k('q')} {DIM}Back{RST}")
        print()
        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if choice == "q":
            return

        if choice == "e":
            new_cmds = _movement_command_builder(current["commands"])
            if new_cmds is not None:
                if not new_cmds:
                    print("  Error: Block cannot be empty.")
                    input("  Press Enter > ")
                    continue
                # Update
                for b in all_blocks:
                    if b["label"] == current["label"]:
                        b["commands"] = new_cmds
                        break
                with open(setup_path, "r") as f:
                    original_lines = f.readlines()
                _write_setup_movement_blocks(setup_path, all_blocks, original_lines)
                print(f"  Updated: {current['label']} ({len(new_cmds)} steps)")
                input("  Press Enter > ")
            continue

        if choice == "r":
            all_blocks = _parse_setup_movement_blocks(setup_path)
            existing_labels = {b["label"] for b in all_blocks}
            old_label = current["label"]

            print()
            print(f"  Current label: {old_label}")
            print(f"  Prefix: {map_name}_")
            new_short = input("  New short name > ").strip()
            if not new_short:
                print("  Cancelled.")
                input("  Press Enter > ")
                continue
            new_label = f"{map_name}_{new_short}"
            if new_label == old_label:
                print("  No change.")
                input("  Press Enter > ")
                continue
            if new_label in existing_labels:
                print(f"  Error: '{new_label}' already exists.")
                input("  Press Enter > ")
                continue

            # Warn about references
            refs = _find_movement_references(old_label, map_dir)
            if refs:
                print()
                print(f"  Warning: {len(refs)} script{'s' if len(refs) != 1 else ''} reference'{'' if len(refs) != 1 else 's'} '{old_label}':")
                for fname, lnum, ltext in refs[:5]:
                    print(f"    {fname}:{lnum}  {ltext.strip()}")
                print("  You'll need to update those references manually.")
                yn = input("  Continue renaming? [y/N] > ").strip().lower()
                if yn != "y":
                    continue

            for b in all_blocks:
                if b["label"] == old_label:
                    b["label"] = new_label
                    break
            with open(setup_path, "r") as f:
                original_lines = f.readlines()
            _write_setup_movement_blocks(setup_path, all_blocks, original_lines)
            block["label"] = new_label  # update the passed-in reference
            print(f"  Renamed: {old_label} -> {new_label}")
            input("  Press Enter > ")
            continue


def _delete_movement_block(block, map_name, project_dir):
    """Delete a movement block after checking references."""
    setup_path = _ensure_setup_pory(map_name, project_dir)
    map_dir = os.path.join(project_dir, map_name)
    label = block["label"]

    refs = _find_movement_references(label, map_dir)
    print()
    if refs:
        print(f"  Warning: '{label}' is referenced in {len(refs)} place{'s' if len(refs) != 1 else ''}:")
        for fname, lnum, ltext in refs:
            print(f"    {fname}:{lnum}  {ltext.strip()}")
        print()
        print("  Note: Only .txt files are checked (not .pory files).")
        print("  Deleting will leave broken references that you must fix manually.")
        print()
        confirm = input(f"  Type DELETE to confirm > ").strip()
        if confirm != "DELETE":
            print("  Cancelled.")
            return False
    else:
        print(f"  No scripts reference '{label}'.")
        confirm = input(f"  Delete '{label}'? [y/N] > ").strip().lower()
        if confirm != "y":
            print("  Cancelled.")
            return False

    _rebuild_setup_without_block(setup_path, label)
    print(f"  Deleted: {label}")
    return True


def _movement_block_manager(map_name, project_dir, settings=None):
    """Main Movement Block Manager screen."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    setup_path = _ensure_setup_pory(map_name, project_dir)
    selected_idx = 0
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)

    while True:
        # Re-read on each loop
        blocks = _parse_setup_movement_blocks(setup_path)

        if not blocks:
            selected_idx = 0
        else:
            selected_idx = max(0, min(selected_idx, len(blocks) - 1))



        clear_screen()
        print()
        print(BAR)
        print(f"   {WHITE}MOVEMENT BLOCKS{RST}  {DIM}\u2014  {map_name}{RST}")
        print(BAR)
        print()

        if blocks:
            num_w = len(str(len(blocks)))
            for i, block in enumerate(blocks):
                cursor = f"{GOLD}>>{RST}" if i == selected_idx else "  "
                num = f"{i + 1}."
                cmds = block["commands"]
                step_count = len(cmds)
                preview_cmds = []
                for cmd in cmds[:4]:
                    preview_cmds.append(cmd.split(" * ")[0] if " * " in cmd else cmd)
                preview = ", ".join(preview_cmds)
                if len(cmds) > 4:
                    preview += ", ..."
                name_col = WHITE if i == selected_idx else CYAN
                print(f"  {cursor} {num:<{num_w + 1}} {name_col}{block['label']:<35s}{RST}  {GREEN}{step_count} step{'s' if step_count != 1 else ''}{RST}")
                print(f"  {'':>{num_w + 5}} {DIM}{preview}{RST}")
                print()
        else:
            print(f"  {DIM}No movement blocks yet.{RST}")
            print()

        count = len(blocks)
        print(f"  {DIM}{count} movement block{'s' if count != 1 else ''} in setup.pory{RST}")
        print()
        scroll_hint = f"  {_k(NK_SCROLL)} {DIM}scroll{RST}" if NK_SCROLL else ""
        print(f"  {_k(f'#')}/{_k(NK_OPEN)} {DIM}open{RST}{scroll_hint}  {_k(NK_UP)} {DIM}up{RST}  {_k(NK_DOWN)} {DIM}down{RST}  {_k('n')} {DIM}new{RST}  {_k('d')} {DIM}delete{RST}  {_k('q')} {DIM}back{RST}")
        print()

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return
        raw = raw.rstrip("\n")

        if raw in ("", NK_SCROLL):
            if blocks:
                selected_idx = (selected_idx + 1) % len(blocks)
            continue

        raw = raw.strip()
        cmd = raw.lower()

        if cmd == "q":
            return

        elif cmd == NK_UP:
            if blocks:
                selected_idx = max(0, selected_idx - 1)

        elif cmd == NK_DOWN:
            if blocks:
                selected_idx = min(len(blocks) - 1, selected_idx + 1)

        elif cmd == NK_OPEN:
            if blocks:
                _edit_movement_block(blocks[selected_idx], map_name, project_dir)

        elif cmd == "n":
            _new_movement_block(map_name, project_dir)

        elif cmd.startswith("d"):
            parts = raw.split()
            if len(parts) > 1 and parts[1].isdigit():
                del_idx = int(parts[1]) - 1
            else:
                try:
                    num_str = input("  Delete block # > ").strip()
                    del_idx = int(num_str) - 1
                except (ValueError, EOFError):
                    print("  Enter a number.")
                    input("  Press Enter > ")
                    continue
            if 0 <= del_idx < len(blocks):
                if _delete_movement_block(blocks[del_idx], map_name, project_dir):
                    input("  Press Enter > ")
                selected_idx = min(selected_idx, max(0, len(blocks) - 2))
            else:
                print("  Invalid block number.")
                input("  Press Enter > ")

        elif raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(blocks):
                selected_idx = idx
            else:
                print(f"  No block #{raw}.")
                input("  Press Enter > ")

        else:
            print(f"  Unknown command '{raw}'.")
            input("  Press Enter > ")
