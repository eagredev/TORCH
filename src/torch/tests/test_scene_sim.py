"""Headless scene simulation tests.

Tests the simulation engine directly via parse_and_simulate() — no web
server, no files, no GUI.  When the visualiser is updated, these tests
automatically use the new logic because they import from scene_sim.py.

Run:  python3 ~/torch_dev/ test          (runs all suites including this one)
      python3 ~/torch_dev/ test scene_sim (runs just this suite)
"""

import os
import sys

from torch.tests.harness import _begin_suite, _ok, _fail, _assert, _skip
from torch.scene_sim import (
    simulate_scene, facing_toward, parse_and_simulate,
    make_actor, apply_move_action, apply_movement_commands,
    DIRECTION_OFFSETS, OPPOSITE_DIR, MOVEMENT_CMD_MAP,
)
from torch.script_model import parse_script_text


# ===================================================================
# Helpers
# ===================================================================

def _actor_at(frames, frame_idx, actor_name):
    """Shorthand: return actor state dict at a given frame."""
    return frames[frame_idx]["actors"][actor_name]


def _pos(frames, frame_idx, actor_name):
    """Shorthand: return (x, y) tuple for an actor at a given frame."""
    a = _actor_at(frames, frame_idx, actor_name)
    return (a["x"], a["y"])


# ===================================================================
# Test entry point
# ===================================================================

def run_suite():
    _begin_suite("Scene Sim")
    _test_parse_script_text()
    _test_basic_simulation()
    _test_movement_verbs()
    _test_movement_blocks()
    _test_facing()
    _test_visibility()
    _test_setpos_convergence()
    _test_parallel_actions()
    _test_dialogue_lifecycle()
    _test_flags_and_vars()
    _test_effects()
    _test_trainer_approach()
    _test_parse_and_simulate()
    _test_multi_beat_sequence()
    _test_edge_cases()
    _test_setpos_preserves_state()
    _test_walk_zero_count()
    _test_real_script_fixture()


# ===================================================================
# Tests: parse_script_text
# ===================================================================

def _test_parse_script_text():
    """Verify parsing from string produces same structure as file-based."""
    parsed = parse_script_text("""
alias buster npc1
label MyScript
lock
buster walk down 3
msg "Hello there!"
release
""")
    _assert("parse_text: cast has buster",
            "buster" in parsed["cast"],
            f"cast = {parsed['cast']}")
    _assert("parse_text: cast buster = npc1",
            parsed["cast"]["buster"] == 1,
            f"got {parsed['cast']['buster']}")
    _assert("parse_text: label is MyScript",
            parsed["label"] == "MyScript",
            f"got {parsed['label']}")
    _assert("parse_text: has beats",
            len(parsed["beats"]) > 0,
            f"got {len(parsed['beats'])} beats")

    # Check beat types
    types = [b["type"] for b in parsed["beats"]]
    _assert("parse_text: label beat present",
            "label" in types,
            f"types = {types}")
    _assert("parse_text: lock beat present",
            "lock" in types,
            f"types = {types}")
    _assert("parse_text: move beat present",
            "move" in types,
            f"types = {types}")
    _assert("parse_text: dialogue beat present",
            "dialogue" in types,
            f"types = {types}")

    # Source line tracking
    for beat in parsed["beats"]:
        _assert(f"parse_text: {beat['type']} has source_line",
                "source_line" in beat,
                f"beat = {beat}")


# ===================================================================
# Tests: basic simulation
# ===================================================================

def _test_basic_simulation():
    """Core simulation: empty scripts, single beats."""

    # Empty script → one frame
    parsed = {"cast": {}, "beats": []}
    initial = {"player": make_actor(5, 5)}
    frames = simulate_scene(parsed, initial)
    _assert("sim: empty script -> 1 frame",
            len(frames) == 1,
            f"got {len(frames)}")
    _assert("sim: empty frame has player",
            "player" in frames[0]["actors"],
            f"actors = {list(frames[0]['actors'])}")
    _assert("sim: empty frame player at (5,5)",
            _pos(frames, 0, "player") == (5, 5),
            f"got {_pos(frames, 0, 'player')}")

    # Single move beat
    parsed = {
        "cast": {"npc": 1},
        "beats": [
            {"type": "move", "data": {"actions": [
                {"actor": "npc", "verb": "walk", "direction": "right", "count": "3"}
            ]}}
        ]
    }
    initial = {
        "player": make_actor(0, 0),
        "npc": make_actor(5, 5),
    }
    frames = simulate_scene(parsed, initial)
    _assert("sim: walk right 3 -> x=8",
            _actor_at(frames, 0, "npc")["x"] == 8,
            f"got x={_actor_at(frames, 0, 'npc')['x']}")
    _assert("sim: walk right updates facing",
            _actor_at(frames, 0, "npc")["facing"] == "right",
            f"got facing={_actor_at(frames, 0, 'npc')['facing']}")

    # Setpos teleports
    parsed = {
        "cast": {},
        "beats": [
            {"type": "setpos", "data": {"actor": "player", "x": 10, "y": 20}}
        ]
    }
    initial = {"player": make_actor(0, 0)}
    frames = simulate_scene(parsed, initial)
    _assert("sim: setpos teleports to (10, 20)",
            _pos(frames, 0, "player") == (10, 20),
            f"got {_pos(frames, 0, 'player')}")


# ===================================================================
# Tests: movement verbs
# ===================================================================

def _test_movement_verbs():
    """Test all movement verb variants."""

    def _test_verb(verb, direction, count, start_x, start_y, expect_x, expect_y):
        parsed = {
            "cast": {},
            "beats": [{"type": "move", "data": {"actions": [
                {"actor": "player", "verb": verb, "direction": direction, "count": str(count)}
            ]}}]
        }
        initial = {"player": make_actor(start_x, start_y)}
        frames = simulate_scene(parsed, initial)
        label = f"verb {verb} {direction} {count}"
        _assert(f"verb: {label} -> ({expect_x},{expect_y})",
                _pos(frames, 0, "player") == (expect_x, expect_y),
                f"got {_pos(frames, 0, 'player')}")

    # Walk in all directions
    _test_verb("walk", "up", 2, 5, 5, 5, 3)
    _test_verb("walk", "down", 3, 5, 5, 5, 8)
    _test_verb("walk", "left", 1, 5, 5, 4, 5)
    _test_verb("walk", "right", 4, 5, 5, 9, 5)

    # Other movement verbs behave identically to walk for position
    _test_verb("walkfast", "up", 2, 10, 10, 10, 8)
    _test_verb("walkslow", "down", 1, 10, 10, 10, 11)
    _test_verb("run", "left", 3, 10, 10, 7, 10)
    _test_verb("slide", "right", 2, 10, 10, 12, 10)
    _test_verb("jump", "up", 1, 10, 10, 10, 9)


# ===================================================================
# Tests: movement blocks (Poryscript movement commands)
# ===================================================================

def _test_movement_blocks():
    """Test movement block execution via 'do' verb."""

    # Inline movement block
    parsed = {
        "cast": {"npc": 1},
        "beats": [
            {"type": "movement", "data": {
                "label": "MyBlock",
                "commands": ["walk_up", "walk_up", "walk_right", "face_down"]
            }},
            {"type": "move", "data": {"actions": [
                {"actor": "npc", "verb": "do", "label": "MyBlock"}
            ]}}
        ]
    }
    initial = {
        "player": make_actor(0, 0),
        "npc": make_actor(5, 10),
    }
    frames = simulate_scene(parsed, initial)
    # After do MyBlock: walk_up*2 (y-2), walk_right (+1x), face_down
    _assert("mvblock: do applies walk_up*2 + walk_right",
            _pos(frames, 1, "npc") == (6, 8),
            f"got {_pos(frames, 1, 'npc')}")
    _assert("mvblock: do applies face_down",
            _actor_at(frames, 1, "npc")["facing"] == "down",
            f"got {_actor_at(frames, 1, 'npc')['facing']}")

    # Repeat syntax: "walk_up * 3"
    parsed = {
        "cast": {},
        "beats": [
            {"type": "movement", "data": {
                "label": "RepeatBlock",
                "commands": ["walk_left * 5"]
            }},
            {"type": "move", "data": {"actions": [
                {"actor": "player", "verb": "do", "label": "RepeatBlock"}
            ]}}
        ]
    }
    initial = {"player": make_actor(10, 10)}
    frames = simulate_scene(parsed, initial)
    _assert("mvblock: walk_left*5 -> x=5",
            _pos(frames, 1, "player") == (5, 10),
            f"got {_pos(frames, 1, 'player')}")

    # Setup movements (external movement blocks from setup.pory)
    parsed = {
        "cast": {"npc": 1},
        "beats": [
            {"type": "move", "data": {"actions": [
                {"actor": "npc", "verb": "do", "label": "ExternalBlock"}
            ]}}
        ]
    }
    initial = {
        "player": make_actor(0, 0),
        "npc": make_actor(5, 5),
    }
    setup = {"ExternalBlock": ["walk_down", "walk_down", "walk_right"]}
    frames = simulate_scene(parsed, initial, setup_movements=setup)
    _assert("mvblock: external setup block applies",
            _pos(frames, 0, "npc") == (6, 7),
            f"got {_pos(frames, 0, 'npc')}")

    # Movement block with visibility commands
    parsed = {
        "cast": {"npc": 1},
        "beats": [
            {"type": "movement", "data": {
                "label": "HideWalkShow",
                "commands": ["set_invisible", "walk_right", "walk_right", "set_visible"]
            }},
            {"type": "move", "data": {"actions": [
                {"actor": "npc", "verb": "do", "label": "HideWalkShow"}
            ]}}
        ]
    }
    initial = {"player": make_actor(0, 0), "npc": make_actor(3, 3, visible=True)}
    frames = simulate_scene(parsed, initial)
    # After set_visible at end, npc should be visible and moved right 2
    _assert("mvblock: set_visible at end -> visible",
            _actor_at(frames, 1, "npc")["visible"] is True,
            f"got {_actor_at(frames, 1, 'npc')['visible']}")
    _assert("mvblock: walk_right*2 in block",
            _pos(frames, 1, "npc") == (5, 3),
            f"got {_pos(frames, 1, 'npc')}")

    # Noop commands (delays, walk-in-place, emotes) should not affect position
    parsed = {
        "cast": {},
        "beats": [
            {"type": "movement", "data": {
                "label": "NoopBlock",
                "commands": ["walk_in_place_down", "delay_8", "emote_exclamation_mark", "step_end"]
            }},
            {"type": "move", "data": {"actions": [
                {"actor": "player", "verb": "do", "label": "NoopBlock"}
            ]}}
        ]
    }
    initial = {"player": make_actor(7, 7)}
    frames = simulate_scene(parsed, initial)
    _assert("mvblock: noop commands don't move",
            _pos(frames, 1, "player") == (7, 7),
            f"got {_pos(frames, 1, 'player')}")


# ===================================================================
# Tests: facing
# ===================================================================

def _test_facing():
    """Test facing_toward and face-related beats."""

    # facing_toward basic cardinal directions
    _assert("facing: right", facing_toward(0, 0, 5, 0) == "right", "")
    _assert("facing: left", facing_toward(10, 5, 0, 5) == "left", "")
    _assert("facing: up", facing_toward(5, 10, 5, 0) == "up", "")
    _assert("facing: down", facing_toward(5, 0, 5, 10) == "down", "")

    # Diagonal: X bias wins when equal
    _assert("facing: diagonal right-down",
            facing_toward(0, 0, 5, 5) == "right",
            f"got {facing_toward(0, 0, 5, 5)}")

    # Face verb changes direction without moving
    parsed = {
        "cast": {},
        "beats": [{"type": "move", "data": {"actions": [
            {"actor": "player", "verb": "face", "direction": "left"}
        ]}}]
    }
    initial = {"player": make_actor(5, 5, "down")}
    frames = simulate_scene(parsed, initial)
    _assert("facing: face verb changes direction",
            _actor_at(frames, 0, "player")["facing"] == "left",
            f"got {_actor_at(frames, 0, 'player')['facing']}")
    _assert("facing: face verb doesn't move",
            _pos(frames, 0, "player") == (5, 5),
            f"got {_pos(frames, 0, 'player')}")

    # Face player
    parsed = {
        "cast": {"npc": 1},
        "beats": [{"type": "move", "data": {"actions": [
            {"actor": "npc", "verb": "face", "direction": "player"}
        ]}}]
    }
    initial = {
        "player": make_actor(10, 5),
        "npc": make_actor(5, 5, "down"),
    }
    frames = simulate_scene(parsed, initial)
    _assert("facing: face player -> right",
            _actor_at(frames, 0, "npc")["facing"] == "right",
            f"got {_actor_at(frames, 0, 'npc')['facing']}")

    # Face away from player
    parsed = {
        "cast": {"npc": 1},
        "beats": [{"type": "move", "data": {"actions": [
            {"actor": "npc", "verb": "face", "direction": "away"}
        ]}}]
    }
    initial = {
        "player": make_actor(10, 5),
        "npc": make_actor(5, 5, "down"),
    }
    frames = simulate_scene(parsed, initial)
    _assert("facing: face away -> left",
            _actor_at(frames, 0, "npc")["facing"] == "left",
            f"got {_actor_at(frames, 0, 'npc')['facing']}")

    # Faceplayer beat: all NPCs face toward player
    parsed = {
        "cast": {},
        "beats": [{"type": "faceplayer", "data": {}}]
    }
    initial = {
        "player": make_actor(10, 5),
        "npc_a": make_actor(10, 10, "down"),
        "npc_b": make_actor(5, 5, "down"),
    }
    frames = simulate_scene(parsed, initial)
    _assert("faceplayer: npc_a faces up",
            _actor_at(frames, 0, "npc_a")["facing"] == "up",
            f"got {_actor_at(frames, 0, 'npc_a')['facing']}")
    _assert("faceplayer: npc_b faces right",
            _actor_at(frames, 0, "npc_b")["facing"] == "right",
            f"got {_actor_at(frames, 0, 'npc_b')['facing']}")

    # face_player in movement block
    parsed = {
        "cast": {"npc": 1},
        "beats": [
            {"type": "movement", "data": {
                "label": "FaceBlock",
                "commands": ["walk_right", "face_player"]
            }},
            {"type": "move", "data": {"actions": [
                {"actor": "npc", "verb": "do", "label": "FaceBlock"}
            ]}}
        ]
    }
    initial = {
        "player": make_actor(0, 0),
        "npc": make_actor(5, 5),
    }
    frames = simulate_scene(parsed, initial)
    # After walk_right: npc at (6,5), then face_player -> face toward (0,0) = left
    _assert("mvblock: face_player after walk",
            _actor_at(frames, 1, "npc")["facing"] == "left",
            f"got {_actor_at(frames, 1, 'npc')['facing']}")


# ===================================================================
# Tests: visibility
# ===================================================================

def _test_visibility():
    """Test hide/show beats."""

    parsed = {
        "cast": {},
        "beats": [
            {"type": "hide", "data": {"actor": "npc"}},
            {"type": "show", "data": {"actor": "npc"}},
        ]
    }
    initial = {
        "player": make_actor(0, 0),
        "npc": make_actor(5, 5, visible=True),
    }
    frames = simulate_scene(parsed, initial)
    _assert("vis: hide sets visible=False",
            _actor_at(frames, 0, "npc")["visible"] is False,
            f"got {_actor_at(frames, 0, 'npc')['visible']}")
    _assert("vis: show restores visible=True",
            _actor_at(frames, 1, "npc")["visible"] is True,
            f"got {_actor_at(frames, 1, 'npc')['visible']}")

    # Hide unknown actor is a no-op (doesn't crash)
    parsed = {
        "cast": {},
        "beats": [{"type": "hide", "data": {"actor": "nonexistent"}}]
    }
    initial = {"player": make_actor(0, 0)}
    frames = simulate_scene(parsed, initial)
    _assert("vis: hide unknown actor = no-op",
            len(frames) == 1,
            f"got {len(frames)} frames")


# ===================================================================
# Tests: setpos convergence (the core use case)
# ===================================================================

def _test_setpos_convergence():
    """NPCs starting at different positions converge after setpos."""

    script_text = """\
alias buster npc1
lock
buster walk down 3
setpos buster 10 10
release
"""
    # Simulate from three different starting positions
    results = []
    for start_x, start_y in [(5, 3), (5, 4), (5, 5)]:
        actors = {
            "player": make_actor(0, 0, "up"),
            "buster": make_actor(start_x, start_y, "down"),
        }
        frames = parse_and_simulate(script_text, actors)

        # Find the setpos beat
        setpos_idx = None
        for i, f in enumerate(frames):
            if f["beat"]["type"] == "setpos":
                setpos_idx = i
                break

        results.append({
            "start": (start_x, start_y),
            "after_walk": _pos(frames, setpos_idx - 1, "buster") if setpos_idx else None,
            "after_setpos": _pos(frames, setpos_idx, "buster") if setpos_idx is not None else None,
        })

    # After walk down 3: y should be start_y + 3 in each case
    for r in results:
        sx, sy = r["start"]
        _assert(f"converge: walk from ({sx},{sy}) -> y+3",
                r["after_walk"] == (sx, sy + 3),
                f"got {r['after_walk']}")

    # After setpos: ALL should be at (10, 10) regardless of start
    for r in results:
        sx, sy = r["start"]
        _assert(f"converge: setpos from ({sx},{sy}) -> (10,10)",
                r["after_setpos"] == (10, 10),
                f"got {r['after_setpos']}")


# ===================================================================
# Tests: parallel actions
# ===================================================================

def _test_parallel_actions():
    """Multiple actors moving simultaneously in one beat."""

    parsed = {
        "cast": {},
        "beats": [{"type": "move", "data": {"actions": [
            {"actor": "player", "verb": "walk", "direction": "up", "count": "2"},
            {"actor": "npc", "verb": "walk", "direction": "down", "count": "1"},
        ]}}]
    }
    initial = {
        "player": make_actor(0, 10),
        "npc": make_actor(5, 5),
    }
    frames = simulate_scene(parsed, initial)
    _assert("parallel: player moved up 2",
            _pos(frames, 0, "player") == (0, 8),
            f"got {_pos(frames, 0, 'player')}")
    _assert("parallel: npc moved down 1",
            _pos(frames, 0, "npc") == (5, 6),
            f"got {_pos(frames, 0, 'npc')}")


# ===================================================================
# Tests: dialogue lifecycle
# ===================================================================

def _test_dialogue_lifecycle():
    """Dialogue appears, persists, and clears correctly."""

    parsed = {
        "cast": {},
        "beats": [
            {"type": "dialogue", "data": {"text": "Hello!"}},
            {"type": "pause", "data": {"duration": "30"}},
            {"type": "closemessage", "data": {}},
        ]
    }
    initial = {"player": make_actor(0, 0)}
    frames = simulate_scene(parsed, initial)
    _assert("dlg: appears in frame 0",
            frames[0]["dialogue"] == "Hello!",
            f"got {frames[0]['dialogue']}")
    _assert("dlg: persists in frame 1",
            frames[1]["dialogue"] == "Hello!",
            f"got {frames[1]['dialogue']}")
    _assert("dlg: cleared by closemessage",
            frames[2]["dialogue"] is None,
            f"got {frames[2]['dialogue']}")


# ===================================================================
# Tests: flags and vars
# ===================================================================

def _test_flags_and_vars():
    """Flag set/clear and variable assignment."""

    parsed = {
        "cast": {},
        "beats": [
            {"type": "flag", "data": {"action": "set", "flag_name": "FLAG_A"}},
            {"type": "var", "data": {"var_name": "VAR_X", "value": "5"}},
            {"type": "flag", "data": {"action": "set", "flag_name": "FLAG_B"}},
            {"type": "flag", "data": {"action": "clear", "flag_name": "FLAG_A"}},
        ]
    }
    initial = {"player": make_actor(0, 0)}
    frames = simulate_scene(parsed, initial)

    _assert("flags: A set in frame 0",
            "FLAG_A" in frames[0]["flags_set"],
            f"got {frames[0]['flags_set']}")
    _assert("flags: B set in frame 2",
            frames[2]["flags_set"] == ["FLAG_A", "FLAG_B"],
            f"got {frames[2]['flags_set']}")
    _assert("flags: A cleared in frame 3",
            frames[3]["flags_set"] == ["FLAG_B"],
            f"got {frames[3]['flags_set']}")
    _assert("vars: VAR_X = 5",
            frames[1]["vars_set"] == {"VAR_X": "5"},
            f"got {frames[1]['vars_set']}")


# ===================================================================
# Tests: effects (emotes, sounds, fades)
# ===================================================================

def _test_effects():
    """Transient vs persistent effects."""

    parsed = {
        "cast": {},
        "beats": [
            {"type": "emote", "data": {"actor": "npc", "emote_name": "!"}},
            {"type": "pause", "data": {}},  # emote should be gone
            {"type": "music", "data": {"constant": "MUS_BATTLE"}},
            {"type": "pause", "data": {}},  # music should persist
            {"type": "fade", "data": {"fade_type": "to_black"}},
            {"type": "pause", "data": {}},  # fade should persist
            {"type": "fade", "data": {"fade_type": "from_black"}},
        ]
    }
    initial = {"player": make_actor(0, 0), "npc": make_actor(5, 5)}
    frames = simulate_scene(parsed, initial)

    _assert("fx: emote in frame 0",
            any("emote:npc:!" in e for e in frames[0]["effects"]),
            f"got {frames[0]['effects']}")
    _assert("fx: emote gone in frame 1 (transient)",
            not any("emote:" in e for e in frames[1]["effects"]),
            f"got {frames[1]['effects']}")
    _assert("fx: music set in frame 2",
            "music:MUS_BATTLE" in frames[2]["effects"],
            f"got {frames[2]['effects']}")
    _assert("fx: music persists in frame 3",
            "music:MUS_BATTLE" in frames[3]["effects"],
            f"got {frames[3]['effects']}")
    _assert("fx: fade_to_black in frame 4",
            "fade_to_black" in frames[4]["effects"],
            f"got {frames[4]['effects']}")
    _assert("fx: fade persists in frame 5",
            "fade_to_black" in frames[5]["effects"],
            f"got {frames[5]['effects']}")
    _assert("fx: from_black clears fade in frame 6",
            not any(e.startswith("fade_") for e in frames[6]["effects"]),
            f"got {frames[6]['effects']}")


# ===================================================================
# Tests: trainer approach
# ===================================================================

def _test_trainer_approach():
    """Trainer sight-trigger auto-approach before battle."""

    # Battle as first significant action → NPC walks to player
    parsed = {
        "cast": {"grunt": 1},
        "beats": [
            {"type": "lock", "data": {}},
            {"type": "battle", "data": {"trainer_id": "TRAINER_GRUNT"}},
        ]
    }
    initial = {
        "player": make_actor(5, 10, "up"),
        "grunt": make_actor(5, 5, "down"),  # facing down toward player
    }
    frames = simulate_scene(parsed, initial)
    # Grunt should walk to one tile above player (5, 9)
    battle_frame = frames[1]
    _assert("trainer: NPC approaches to adjacent tile",
            battle_frame["actors"]["grunt"]["y"] == 9,
            f"got y={battle_frame['actors']['grunt']['y']}")
    _assert("trainer: NPC x stays same (vertical approach)",
            battle_frame["actors"]["grunt"]["x"] == 5,
            f"got x={battle_frame['actors']['grunt']['x']}")
    _assert("trainer: battle emote effect",
            any("battle_emote:grunt" in e for e in battle_frame["effects"]),
            f"got {battle_frame['effects']}")
    _assert("trainer: player faces toward NPC",
            battle_frame["actors"]["player"]["facing"] == "up",
            f"got {battle_frame['actors']['player']['facing']}")

    # Battle AFTER movement → no auto-approach
    parsed = {
        "cast": {"grunt": 1},
        "beats": [
            {"type": "move", "data": {"actions": [
                {"actor": "grunt", "verb": "walk", "direction": "down", "count": "1"}
            ]}},
            {"type": "battle", "data": {"trainer_id": "TRAINER_GRUNT"}},
        ]
    }
    initial = {
        "player": make_actor(5, 10, "up"),
        "grunt": make_actor(5, 5, "down"),
    }
    frames = simulate_scene(parsed, initial)
    # After manual walk down 1, grunt at (5,6). Battle should NOT auto-approach.
    _assert("trainer: no approach after prior movement",
            frames[1]["actors"]["grunt"]["y"] == 6,
            f"got y={frames[1]['actors']['grunt']['y']}")


# ===================================================================
# Tests: parse_and_simulate convenience
# ===================================================================

def _test_parse_and_simulate():
    """End-to-end: TorScript text → frames."""

    frames = parse_and_simulate("""\
alias buster npc1
lock
buster walk right 2
buster walk down 1
msg "Hey there!"
release
""", actors={
        "player": make_actor(0, 0, "up"),
        "buster": make_actor(5, 5, "down"),
    })

    _assert("e2e: multiple frames",
            len(frames) >= 4,
            f"got {len(frames)} frames")

    # Find the move beats
    move_frames = [f for f in frames if f["beat"]["type"] == "move"]
    _assert("e2e: 2 move beats",
            len(move_frames) == 2,
            f"got {len(move_frames)}")

    # After first move (right 2): buster at (7, 5)
    _assert("e2e: buster after walk right 2",
            move_frames[0]["actors"]["buster"]["x"] == 7,
            f"got x={move_frames[0]['actors']['buster']['x']}")

    # After second move (down 1): buster at (7, 6)
    _assert("e2e: buster after walk down 1",
            (move_frames[1]["actors"]["buster"]["x"],
             move_frames[1]["actors"]["buster"]["y"]) == (7, 6),
            f"got {(move_frames[1]['actors']['buster']['x'], move_frames[1]['actors']['buster']['y'])}")

    # Auto-created actors when not provided
    frames = parse_and_simulate("""\
alias npc npc1
npc walk left 1
""")
    _assert("e2e: auto-created player exists",
            "player" in frames[0]["actors"],
            f"actors = {list(frames[0]['actors'])}")
    _assert("e2e: auto-created npc exists",
            "npc" in frames[0]["actors"],
            f"actors = {list(frames[0]['actors'])}")


# ===================================================================
# Tests: multi-beat sequence (realistic script)
# ===================================================================

def _test_multi_beat_sequence():
    """Realistic multi-beat cutscene with position tracking."""

    frames = parse_and_simulate("""\
alias buster npc1
alias jenny npc2
label CutsceneTest
lock
faceplayer
buster walk right 3
buster walk down 2
jenny walk left 1
jenny walk up 1
setpos buster 10 10
hide jenny
msg "Buster appeared at the meeting point!"
closemessage
show jenny
release
""", actors={
        "player": make_actor(15, 15, "up"),
        "buster": make_actor(5, 5, "down"),
        "jenny": make_actor(20, 10, "left"),
    })

    # Find specific beat frames
    beats_by_type = {}
    for f in frames:
        bt = f["beat"]["type"]
        if bt not in beats_by_type:
            beats_by_type[bt] = []
        beats_by_type[bt].append(f)

    # After faceplayer: both NPCs face toward player at (15,15)
    fp = beats_by_type["faceplayer"][0]
    _assert("sequence: buster faces player after faceplayer",
            fp["actors"]["buster"]["facing"] == "right",
            f"got {fp['actors']['buster']['facing']}")

    # After buster's moves: started (5,5), walk right 3 (+3x), walk down 2 (+2y)
    buster_moves = beats_by_type["move"]
    # Frame after walk right 3
    _assert("sequence: buster after walk right 3",
            buster_moves[0]["actors"]["buster"]["x"] == 8,
            f"got x={buster_moves[0]['actors']['buster']['x']}")
    # Frame after walk down 2
    _assert("sequence: buster after walk down 2",
            (buster_moves[1]["actors"]["buster"]["x"],
             buster_moves[1]["actors"]["buster"]["y"]) == (8, 7),
            f"got {(buster_moves[1]['actors']['buster']['x'], buster_moves[1]['actors']['buster']['y'])}")

    # After setpos: buster at (10, 10) regardless
    sp = beats_by_type["setpos"][0]
    _assert("sequence: setpos buster to (10,10)",
            (sp["actors"]["buster"]["x"], sp["actors"]["buster"]["y"]) == (10, 10),
            f"got {(sp['actors']['buster']['x'], sp['actors']['buster']['y'])}")

    # After hide jenny
    hide = beats_by_type["hide"][0]
    _assert("sequence: jenny hidden",
            hide["actors"]["jenny"]["visible"] is False,
            f"got {hide['actors']['jenny']['visible']}")

    # After show jenny
    show = beats_by_type["show"][0]
    _assert("sequence: jenny shown again",
            show["actors"]["jenny"]["visible"] is True,
            f"got {show['actors']['jenny']['visible']}")

    # Dialogue appears and then clears
    dlg = beats_by_type["dialogue"][0]
    _assert("sequence: dialogue text set",
            dlg["dialogue"] == "Buster appeared at the meeting point!",
            f"got {dlg['dialogue']}")
    cm = beats_by_type["closemessage"][0]
    _assert("sequence: dialogue cleared",
            cm["dialogue"] is None,
            f"got {cm['dialogue']}")


# ===================================================================
# Tests: edge cases
# ===================================================================

def _test_edge_cases():
    """Edge cases: unknown actors, bad counts, empty scripts."""

    # Move on unknown actor is a no-op
    parsed = {
        "cast": {},
        "beats": [{"type": "move", "data": {"actions": [
            {"actor": "ghost", "verb": "walk", "direction": "up", "count": "5"}
        ]}}]
    }
    initial = {"player": make_actor(0, 0)}
    frames = simulate_scene(parsed, initial)
    _assert("edge: unknown actor = no crash",
            len(frames) == 1,
            f"got {len(frames)}")
    _assert("edge: unknown actor not in actors",
            "ghost" not in frames[0]["actors"],
            f"actors = {list(frames[0]['actors'])}")

    # Invalid count defaults to 1
    parsed = {
        "cast": {},
        "beats": [{"type": "move", "data": {"actions": [
            {"actor": "player", "verb": "walk", "direction": "right", "count": "abc"}
        ]}}]
    }
    initial = {"player": make_actor(10, 10)}
    frames = simulate_scene(parsed, initial)
    _assert("edge: bad count defaults to 1 step",
            _pos(frames, 0, "player") == (11, 10),
            f"got {_pos(frames, 0, 'player')}")

    # Setpos with missing coordinates keeps current
    parsed = {
        "cast": {},
        "beats": [{"type": "setpos", "data": {"actor": "player", "x": 99}}]
    }
    initial = {"player": make_actor(5, 5)}
    frames = simulate_scene(parsed, initial)
    _assert("edge: setpos missing y keeps y",
            _pos(frames, 0, "player") == (99, 5),
            f"got {_pos(frames, 0, 'player')}")

    # Frame snapshots are independent (deep copy)
    parsed = {
        "cast": {},
        "beats": [
            {"type": "move", "data": {"actions": [
                {"actor": "player", "verb": "walk", "direction": "right", "count": "1"}
            ]}},
            {"type": "move", "data": {"actions": [
                {"actor": "player", "verb": "walk", "direction": "right", "count": "1"}
            ]}},
        ]
    }
    initial = {"player": make_actor(0, 0)}
    frames = simulate_scene(parsed, initial)
    _assert("edge: frames are independent snapshots",
            _pos(frames, 0, "player") != _pos(frames, 1, "player"),
            f"frame0={_pos(frames, 0, 'player')}, frame1={_pos(frames, 1, 'player')}")
    _assert("edge: frame 0 at (1,0)",
            _pos(frames, 0, "player") == (1, 0),
            f"got {_pos(frames, 0, 'player')}")
    _assert("edge: frame 1 at (2,0)",
            _pos(frames, 1, "player") == (2, 0),
            f"got {_pos(frames, 1, 'player')}")


# ===================================================================
# Tests: setpos preserves other state
# ===================================================================

def _test_setpos_preserves_state():
    """Setpos changes position but keeps facing and visibility."""

    # Setpos preserves facing
    frames = parse_and_simulate("""\
alias npc npc1
npc face left
setpos npc 20 20
""", actors={"player": make_actor(0, 0), "npc": make_actor(10, 10, "up")})
    move_f = [f for f in frames if f["beat"]["type"] == "move"]
    setpos_f = [f for f in frames if f["beat"]["type"] == "setpos"]
    _assert("setpos: preserves facing after face change",
            setpos_f[0]["actors"]["npc"]["facing"] == "left",
            f"got {setpos_f[0]['actors']['npc']['facing']}")
    _assert("setpos: position changed to (20,20)",
            _pos(frames, -1, "npc") == (20, 20),
            f"got {_pos(frames, -1, 'npc')}")

    # Setpos preserves hidden state
    frames = parse_and_simulate("""\
alias npc npc1
hide npc
setpos npc 20 20
""", actors={"player": make_actor(0, 0), "npc": make_actor(10, 10)})
    setpos_f = [f for f in frames if f["beat"]["type"] == "setpos"]
    _assert("setpos: preserves hidden state",
            setpos_f[0]["actors"]["npc"]["visible"] is False,
            f"got {setpos_f[0]['actors']['npc']['visible']}")
    _assert("setpos: hidden npc moved to (20,20)",
            (setpos_f[0]["actors"]["npc"]["x"],
             setpos_f[0]["actors"]["npc"]["y"]) == (20, 20),
            f"got ({setpos_f[0]['actors']['npc']['x']}, {setpos_f[0]['actors']['npc']['y']})")

    # Setpos with string coordinates (from parser) coerces to int
    parsed = {
        "cast": {},
        "beats": [{"type": "setpos", "data": {"actor": "player", "x": "15", "y": "25"}}]
    }
    initial = {"player": make_actor(0, 0)}
    frames = simulate_scene(parsed, initial)
    _assert("setpos: string coords coerced to int",
            _pos(frames, 0, "player") == (15, 25),
            f"got {_pos(frames, 0, 'player')}")
    _assert("setpos: x is int not string",
            isinstance(frames[0]["actors"]["player"]["x"], int),
            f"got type {type(frames[0]['actors']['player']['x'])}")


# ===================================================================
# Tests: walk with count=0
# ===================================================================

def _test_walk_zero_count():
    """Walk with count=0 updates facing but doesn't move."""

    parsed = {
        "cast": {},
        "beats": [{"type": "move", "data": {"actions": [
            {"actor": "player", "verb": "walk", "direction": "right", "count": "0"}
        ]}}]
    }
    initial = {"player": make_actor(10, 10, "down")}
    frames = simulate_scene(parsed, initial)
    _assert("walk0: position unchanged",
            _pos(frames, 0, "player") == (10, 10),
            f"got {_pos(frames, 0, 'player')}")
    _assert("walk0: facing updated to right",
            _actor_at(frames, 0, "player")["facing"] == "right",
            f"got {_actor_at(frames, 0, 'player')['facing']}")


# ===================================================================
# Tests: real script fixture (ClydeArrives)
# ===================================================================

def _test_real_script_fixture():
    """End-to-end simulation of ClydeArrives.txt fixture."""

    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "ClydeArrives.txt")
    if not os.path.exists(fixture):
        _skip("real_script: ClydeArrives.txt not found")
        return

    with open(fixture) as f:
        script = f.read()

    # Place actors at realistic positions
    actors = {
        "player": make_actor(23, 60, "right"),
        "buster": make_actor(31, 60, "left"),
        "clyde":  make_actor(28, 69, "up"),
    }
    frames = parse_and_simulate(script, actors)

    _assert("real: produces frames",
            len(frames) > 20,
            f"got {len(frames)} frames")

    # Buster never moves in this script (only faces and emotes)
    for f in frames:
        if f["beat"]["type"] not in ("hide",):
            bx = f["actors"]["buster"]["x"]
            by = f["actors"]["buster"]["y"]
            _assert("real: buster stays at (31,60)",
                    (bx, by) == (31, 60),
                    f"frame {f['beat_index']}: buster at ({bx},{by})")
            break  # Just check first non-hide frame is enough

    # Clyde walks up 7: from y=69 to y=62
    move_frames = [f for f in frames if f["beat"]["type"] == "move"]
    # Find the walkfast up 7 frame (first move affecting clyde's y)
    for mf in move_frames:
        cy = mf["actors"]["clyde"]["y"]
        if cy != 69:  # Position changed
            _assert("real: clyde walkfast up 7 -> y=62",
                    cy == 62,
                    f"got y={cy}")
            break

    # After hide buster + hide clyde: both invisible
    hide_frames = [f for f in frames if f["beat"]["type"] == "hide"]
    if len(hide_frames) >= 2:
        _assert("real: buster hidden at end",
                hide_frames[0]["actors"]["buster"]["visible"] is False,
                f"got {hide_frames[0]['actors']['buster']['visible']}")
        _assert("real: clyde hidden at end",
                hide_frames[1]["actors"]["clyde"]["visible"] is False,
                f"got {hide_frames[1]['actors']['clyde']['visible']}")

    # FLAG_BEAT_ROCKET_DUO_1 should be set
    last_frame = frames[-1]
    _assert("real: FLAG_BEAT_ROCKET_DUO_1 set",
            "FLAG_BEAT_ROCKET_DUO_1" in last_frame["flags_set"],
            f"got {last_frame['flags_set']}")
