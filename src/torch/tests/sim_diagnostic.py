#!/usr/bin/env python3
"""Diagnostic script: run TorScript through the headless simulation engine.

Usage:
    python3 ~/torch_dev/ test sim_diag        (via test harness)
    python3 tests/sim_diagnostic.py           (standalone, from torch_dev/)

Exercises the simulation engine against real and synthetic scripts,
printing frame-by-frame actor state to make simulation behavior visible.
"""
import os
import sys

# Bootstrap the 'torch' module alias (same trick as __main__.py)
_this = os.path.dirname(os.path.abspath(__file__))
_pkg_dir = os.path.dirname(_this)
_parent = os.path.dirname(_pkg_dir)
if _parent not in sys.path:
    sys.path.insert(0, _parent)
_pkg_name = os.path.basename(_pkg_dir)
if _pkg_name != "torch":
    import importlib
    _pkg = importlib.import_module(_pkg_name)
    if "torch" not in sys.modules:
        sys.modules["torch"] = _pkg

from torch.scene_sim import parse_and_simulate, make_actor, simulate_scene
from torch.script_model import parse_script_text


# ===================================================================
# Pretty-printer
# ===================================================================

def dump_frames(frames, title=""):
    """Print frame-by-frame actor state in a readable table."""
    if title:
        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}")

    print(f"  {len(frames)} frames total\n")

    for i, f in enumerate(frames):
        bt = f["beat"]["type"]
        data = f["beat"].get("data", {})

        # Build actor summary
        parts = []
        for name in sorted(f["actors"]):
            a = f["actors"][name]
            vis = "" if a.get("visible", True) else ",HID"
            parts.append(f"{name}({a['x']},{a['y']},{a['facing'][:1]}{vis})")
        actors_str = "  ".join(parts)

        # Build extras
        fx = [e for e in f["effects"]
              if not e.startswith("music:") and not e.startswith("fade_")]
        dlg = f["dialogue"]
        if dlg and len(dlg) > 40:
            dlg = dlg[:37] + "..."

        extra = ""
        if fx:
            extra += f"  fx={fx}"
        if dlg:
            extra += f'  "{dlg}"'
        if f["flags_set"]:
            extra += f"  flags={f['flags_set']}"

        print(f"  [{i:2d}] {bt:15s} | {actors_str}{extra}")

    print()


# ===================================================================
# Diagnostic scenarios
# ===================================================================

def diag_clyde_arrives():
    """Real script: ClydeArrives cutscene."""
    fixture = os.path.join(_this, "fixtures", "ClydeArrives.txt")
    if not os.path.exists(fixture):
        print("  [SKIP] ClydeArrives.txt not found")
        return

    with open(fixture) as f:
        script = f.read()

    actors = {
        "player": make_actor(10, 15, "up"),
        "buster": make_actor(10, 12, "down"),
        "clyde":  make_actor(10, 5, "up"),
    }
    frames = parse_and_simulate(script, actors)
    dump_frames(frames, "ClydeArrives (real cutscene)")

    # Verify key moments
    _check("Clyde walks up 7: y should decrease by 7",
           frames, "clyde", lambda a: a["y"],
           find_beat_type="move", expected_delta=-7,
           first_move_only=True)


def diag_movement_math():
    """Synthetic: verify movement math in all directions."""
    script = """\
alias npc npc1
lock
npc walk right 3
npc walk down 2
npc walk left 1
npc walk up 4
release
"""
    actors = {
        "player": make_actor(0, 0, "up"),
        "npc": make_actor(10, 10, "down"),
    }
    frames = parse_and_simulate(script, actors)
    dump_frames(frames, "Movement math: right 3, down 2, left 1, up 4")

    # Expected positions after each move:
    # Start: (10, 10)
    # right 3: (13, 10)
    # down 2: (13, 12)
    # left 1: (12, 12)
    # up 4: (12, 8)
    move_frames = [f for f in frames if f["beat"]["type"] == "move"]
    expectations = [(13, 10), (13, 12), (12, 12), (12, 8)]
    for idx, (ex, ey) in enumerate(expectations):
        ax = move_frames[idx]["actors"]["npc"]["x"]
        ay = move_frames[idx]["actors"]["npc"]["y"]
        status = "OK" if (ax, ay) == (ex, ey) else "MISMATCH"
        print(f"  Move {idx}: expected ({ex},{ey}), got ({ax},{ay}) [{status}]")
    print()


def diag_setpos_convergence():
    """The key scenario: NPCs at different starts converge via setpos."""
    script = """\
alias npc npc1
lock
npc walk down 3
setpos npc 20 20
npc walk right 1
release
"""
    print(f"\n{'=' * 60}")
    print(f"  Setpos Convergence")
    print(f"{'=' * 60}")

    for start_x, start_y in [(5, 3), (5, 8), (12, 1)]:
        actors = {
            "player": make_actor(0, 0, "up"),
            "npc": make_actor(start_x, start_y, "down"),
        }
        frames = parse_and_simulate(script, actors)

        # Track NPC position through each frame
        print(f"\n  Start: ({start_x}, {start_y})")
        for i, f in enumerate(frames):
            bt = f["beat"]["type"]
            nx = f["actors"]["npc"]["x"]
            ny = f["actors"]["npc"]["y"]
            print(f"    [{i}] {bt:12s} -> npc({nx},{ny})")

    print()


def diag_parallel_actions():
    """Multiple actors moving simultaneously."""
    script = """\
alias buster npc1
alias clyde npc2
lock
buster walk right 2 + clyde walk left 3
buster walk down 1 + clyde walk up 1 + player walk right 1
release
"""
    actors = {
        "player": make_actor(10, 10, "up"),
        "buster": make_actor(5, 5, "down"),
        "clyde":  make_actor(20, 20, "left"),
    }
    frames = parse_and_simulate(script, actors)
    dump_frames(frames, "Parallel actions: 3 actors moving simultaneously")


def diag_facing_interactions():
    """Face verb, faceplayer, face player, face away."""
    script = """\
alias npc npc1
lock
faceplayer
npc face left
npc face player
npc face away
release
"""
    actors = {
        "player": make_actor(15, 10, "up"),
        "npc": make_actor(10, 10, "down"),
    }
    frames = parse_and_simulate(script, actors)
    dump_frames(frames, "Facing: faceplayer, face left, face player, face away")

    # Player is to the RIGHT of NPC (x=15 vs x=10)
    # faceplayer: NPC should face right
    # face left: NPC faces left
    # face player: NPC faces right again
    # face away: NPC faces left (opposite of toward player)
    move_frames = [f for f in frames if f["beat"]["type"] in ("faceplayer", "move")]
    expectations = ["right", "left", "right", "left"]
    for idx, expected in enumerate(expectations):
        actual = move_frames[idx]["actors"]["npc"]["facing"]
        status = "OK" if actual == expected else "MISMATCH"
        print(f"  Step {idx}: expected {expected}, got {actual} [{status}]")
    print()


def diag_visibility_sequence():
    """Hide/show with position changes in between."""
    script = """\
alias npc npc1
lock
hide npc
npc walk right 5
show npc
release
"""
    actors = {
        "player": make_actor(0, 0, "up"),
        "npc": make_actor(10, 10, "down"),
    }
    frames = parse_and_simulate(script, actors)
    dump_frames(frames, "Visibility: hide, walk while hidden, show")

    # Key question: does walking while hidden still update position?
    move_f = [f for f in frames if f["beat"]["type"] == "move"]
    if move_f:
        nx = move_f[0]["actors"]["npc"]["x"]
        vis = move_f[0]["actors"]["npc"]["visible"]
        print(f"  After walk while hidden: x={nx} (expected 15), visible={vis} (expected False)")
    show_f = [f for f in frames if f["beat"]["type"] == "show"]
    if show_f:
        nx = show_f[0]["actors"]["npc"]["x"]
        vis = show_f[0]["actors"]["npc"]["visible"]
        print(f"  After show: x={nx} (expected 15), visible={vis} (expected True)")
    print()


def diag_emote_transience():
    """Emotes should appear for one frame only."""
    script = """\
alias npc npc1
lock
npc emote !
pause
npc emote ?
pause
release
"""
    actors = {
        "player": make_actor(0, 0, "up"),
        "npc": make_actor(5, 5, "down"),
    }
    frames = parse_and_simulate(script, actors)
    dump_frames(frames, "Emote transience: ! then pause, ? then pause")


def diag_movement_block():
    """Movement blocks via 'do' verb."""
    script = """\
alias npc npc1
movement WalkSquare
  walk_right
  walk_right
  walk_down
  walk_down
  walk_left
  walk_left
  walk_up
  walk_up

lock
npc do WalkSquare
release
"""
    actors = {
        "player": make_actor(0, 0, "up"),
        "npc": make_actor(5, 5, "down"),
    }
    frames = parse_and_simulate(script, actors)
    dump_frames(frames, "Movement block: walk a square (should return to start)")

    # After walking a 2x2 square: should be back at (5, 5)
    do_frames = [f for f in frames if f["beat"]["type"] == "move"]
    if do_frames:
        nx = do_frames[0]["actors"]["npc"]["x"]
        ny = do_frames[0]["actors"]["npc"]["y"]
        status = "OK" if (nx, ny) == (5, 5) else "MISMATCH"
        print(f"  After square walk: ({nx},{ny}), expected (5,5) [{status}]")
    print()


def diag_dialogue_flow():
    """Dialogue appears, persists through pauses, clears on closemessage."""
    script = """\
alias npc npc1
lock
msg "Hello world!$"
pause
msg "Second message.$"
closemessage
pause
release
"""
    actors = {
        "player": make_actor(0, 0, "up"),
        "npc": make_actor(5, 5, "down"),
    }
    frames = parse_and_simulate(script, actors)
    dump_frames(frames, "Dialogue flow: msg, pause, msg, closemessage, pause")


# ===================================================================
# Helpers
# ===================================================================

def _check(label, frames, actor, getter, find_beat_type=None,
           expected_delta=None, first_move_only=False):
    """Simple assertion helper for diagnostics."""
    if find_beat_type:
        matches = [f for f in frames if f["beat"]["type"] == find_beat_type]
        if first_move_only and matches:
            matches = matches[:1]
    else:
        matches = frames

    if not matches:
        print(f"  [{label}] SKIP — no matching frames")
        return

    for f in matches:
        val = getter(f["actors"][actor])
        print(f"  [{label}] {actor} = {val}")


# ===================================================================
# Main
# ===================================================================

def main():
    print("\n" + "=" * 60)
    print("  TORCH Scene Sim — Diagnostic Run")
    print("=" * 60)

    diag_movement_math()
    diag_setpos_convergence()
    diag_parallel_actions()
    diag_facing_interactions()
    diag_visibility_sequence()
    diag_emote_transience()
    diag_movement_block()
    diag_dialogue_flow()
    diag_clyde_arrives()

    print("=" * 60)
    print("  Diagnostic run complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
