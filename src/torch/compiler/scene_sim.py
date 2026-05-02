"""
scene_sim.py — Headless scene simulation engine.

Pure-logic module: takes parsed scripts + actor positions, produces frame
snapshots. No HTTP, no filesystem, no GUI dependencies.

Extracted from web/api.py so that:
  1. The web visualiser and the headless test harness share one engine.
  2. Updating simulation logic in one place updates both.

Public API:
  simulate_scene()   — beat-by-beat simulation → list of frames
  facing_toward()    — cardinal direction from source to target
  parse_and_simulate() — convenience: TorScript text → frames (no files)

Data constants (also public):
  DIRECTION_OFFSETS, OPPOSITE_DIR, MOVEMENT_CMD_MAP, MOVEMENT_CMD_NOOP
"""

import copy

from torch.data import WALKTO_COMMANDS
from torch.script_model import parse_script_text


# ---------------------------------------------------------------------------
# Direction / facing constants
# ---------------------------------------------------------------------------

DIRECTION_OFFSETS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}

OPPOSITE_DIR = {"up": "down", "down": "up", "left": "right", "right": "left"}

# Mapping from Poryscript movement commands to (dx, dy, facing, tiles)
MOVEMENT_CMD_MAP = {
    # Walk (1 tile)
    "walk_down": (0, 1, "down", 1),
    "walk_up": (0, -1, "up", 1),
    "walk_left": (-1, 0, "left", 1),
    "walk_right": (1, 0, "right", 1),
    "walk_slow_down": (0, 1, "down", 1),
    "walk_slow_up": (0, -1, "up", 1),
    "walk_slow_left": (-1, 0, "left", 1),
    "walk_slow_right": (1, 0, "right", 1),
    "walk_fast_down": (0, 1, "down", 1),
    "walk_fast_up": (0, -1, "up", 1),
    "walk_fast_left": (-1, 0, "left", 1),
    "walk_fast_right": (1, 0, "right", 1),
    # Slide (1 tile, no walk animation)
    "slide_down": (0, 1, "down", 1),
    "slide_up": (0, -1, "up", 1),
    "slide_left": (-1, 0, "left", 1),
    "slide_right": (1, 0, "right", 1),
    # Jump (1 tile)
    "jump_down": (0, 1, "down", 1),
    "jump_up": (0, -1, "up", 1),
    "jump_left": (-1, 0, "left", 1),
    "jump_right": (1, 0, "right", 1),
    # Jump (2 tiles)
    "jump_2_down": (0, 1, "down", 2),
    "jump_2_up": (0, -1, "up", 2),
    "jump_2_left": (-1, 0, "left", 2),
    "jump_2_right": (1, 0, "right", 2),
    # Face (no movement)
    "face_down": (0, 0, "down", 0),
    "face_up": (0, 0, "up", 0),
    "face_left": (0, 0, "left", 0),
    "face_right": (0, 0, "right", 0),
}

# Commands that don't affect position or facing — just skip them
MOVEMENT_CMD_NOOP = {
    "walk_in_place_down", "walk_in_place_up", "walk_in_place_left", "walk_in_place_right",
    "walk_in_place_fast_down", "walk_in_place_fast_up",
    "walk_in_place_fast_left", "walk_in_place_fast_right",
    "jump_in_place_down", "jump_in_place_up",
    "jump_in_place_left", "jump_in_place_right",
    "delay_1", "delay_2", "delay_4", "delay_8", "delay_16",
    "lock_facing_direction", "unlock_facing_direction",
    "disable_anim", "enable_anim",
    "emote_exclamation_mark", "emote_question_mark",
    "emote_double_exclamation_mark", "emote_x",
    "emote_heart", "emote_dot_dot_dot",
    "step_end",
}


# ---------------------------------------------------------------------------
# Facing helper
# ---------------------------------------------------------------------------

def facing_toward(src_x, src_y, tgt_x, tgt_y):
    """Return the cardinal direction from (src) facing toward (tgt)."""
    dx = tgt_x - src_x
    dy = tgt_y - src_y
    if abs(dx) >= abs(dy):
        return "right" if dx >= 0 else "left"
    return "down" if dy >= 0 else "up"


# ---------------------------------------------------------------------------
# Movement helpers
# ---------------------------------------------------------------------------

def apply_move_action(action, actors, movement_blocks=None):
    """Apply a single move action to the actor state."""
    actor = action.get("actor", "")
    if actor not in actors:
        return

    verb = action.get("verb", "")
    direction = action.get("direction", "")

    if verb == "face":
        if direction == "player":
            player = actors.get("player")
            if player:
                actors[actor]["facing"] = facing_toward(
                    actors[actor]["x"], actors[actor]["y"],
                    player["x"], player["y"])
        elif direction == "away":
            player = actors.get("player")
            if player:
                toward = facing_toward(
                    actors[actor]["x"], actors[actor]["y"],
                    player["x"], player["y"])
                actors[actor]["facing"] = OPPOSITE_DIR.get(toward, toward)
        elif direction:
            actors[actor]["facing"] = direction
        return

    if verb == "emote":
        return

    if verb in WALKTO_COMMANDS:
        # Walk to a target position (absolute or relative to another actor)
        a = actors[actor]
        if "ref_actor" in action:
            ref = action["ref_actor"]
            ref_actor = actors.get(ref)
            if not ref_actor:
                return
            try:
                ox = int(action.get("offset_x", 0))
                oy = int(action.get("offset_y", 0))
            except (ValueError, TypeError):
                ox, oy = 0, 0
            tx = ref_actor["x"] + ox
            ty = ref_actor["y"] + oy
        else:
            try:
                tx = int(action.get("target_x", a["x"]))
                ty = int(action.get("target_y", a["y"]))
            except (ValueError, TypeError):
                return
        # Move to target (simulator resolves instantly)
        if tx != a["x"] or ty != a["y"]:
            a["facing"] = facing_toward(a["x"], a["y"], tx, ty)
            a["x"] = tx
            a["y"] = ty
        return

    if verb == "do":
        # Execute a named movement block
        label = action.get("label", "")
        if movement_blocks and label in movement_blocks:
            apply_movement_commands(actor, movement_blocks[label], actors)
        return

    # Movement verbs: walk, walkfast, walkslow, run, slide, jump
    if direction in DIRECTION_OFFSETS:
        actors[actor]["facing"] = direction
        try:
            count = int(action.get("count", "1"))
        except (ValueError, TypeError):
            count = 1
        dx, dy = DIRECTION_OFFSETS[direction]
        actors[actor]["x"] += dx * count
        actors[actor]["y"] += dy * count


def apply_movement_commands(actor_name, commands, actors):
    """Apply a list of Poryscript movement commands to an actor.

    Args:
        actor_name: which actor to move
        commands: list of command strings (e.g., ["walk_up", "walk_up", "face_left"])
        actors: the mutable actors dict
    """
    if actor_name not in actors:
        return

    actor = actors[actor_name]

    for raw_cmd in commands:
        # Handle repeat syntax: "walk_up * 3"
        parts = raw_cmd.strip().split("*")
        cmd = parts[0].strip()
        try:
            repeat = int(parts[1].strip()) if len(parts) > 1 else 1
        except (ValueError, IndexError):
            repeat = 1

        if cmd in MOVEMENT_CMD_NOOP:
            continue

        if cmd == "face_player":
            player = actors.get("player")
            if player:
                actor["facing"] = facing_toward(
                    actor["x"], actor["y"], player["x"], player["y"])
            continue

        if cmd == "face_away_player":
            player = actors.get("player")
            if player:
                toward = facing_toward(
                    actor["x"], actor["y"], player["x"], player["y"])
                actor["facing"] = OPPOSITE_DIR.get(toward, toward)
            continue

        if cmd == "set_invisible":
            actor["visible"] = False
            continue

        if cmd == "set_visible":
            actor["visible"] = True
            continue

        entry = MOVEMENT_CMD_MAP.get(cmd)
        if entry:
            dx, dy, facing, tiles = entry
            if facing:
                actor["facing"] = facing
            actor["x"] += dx * tiles * repeat
            actor["y"] += dy * tiles * repeat


# ---------------------------------------------------------------------------
# Main simulation engine
# ---------------------------------------------------------------------------

def simulate_scene(parsed_script, initial_positions, setup_movements=None):
    """Simulate a scene beat-by-beat, producing a frame snapshot per beat.

    Args:
        parsed_script: dict with 'cast' and 'beats' (from parse_script_text
                       or _parse_script)
        initial_positions: dict mapping actor name -> {x, y, facing,
                           graphics_id, visible}
        setup_movements: optional dict mapping label -> [commands] from
                         setup.pory

    Returns:
        list of frame dicts, one per beat.  Each frame:
        {
            "beat_index": int,
            "beat": dict,
            "actors": {name: {x, y, facing, visible, graphics_id}},
            "dialogue": str or None,
            "effects": [str],
            "flags_set": [str],
            "vars_set": {str: str},
        }
    """
    actors = copy.deepcopy(initial_positions)
    frames = []
    dialogue = None
    effects = []
    flags_set = []
    vars_set = {}
    trainer_approached = False

    beats = parsed_script.get("beats", [])
    cast = parsed_script.get("cast", {})
    first_alias = next(iter(cast), None) if cast else None

    # Build movement block lookup: setup.pory blocks + inline movement beats
    movement_blocks = dict(setup_movements) if setup_movements else {}
    for b in beats:
        if b.get("type") == "movement":
            label = b.get("data", {}).get("label", "")
            if label:
                movement_blocks[label] = b.get("data", {}).get("commands", [])

    for idx, beat in enumerate(beats):
        btype = beat.get("type", "")
        data = beat.get("data", {})

        # Trainer approach: when a battle beat is encountered as the first
        # significant action, the triggering NPC walks from their position
        # to one tile adjacent to the player.
        has_prior_movement = any(
            b.get("type") in ("move", "setpos", "movement")
            for b in beats[:idx]
        )
        if (btype == "battle" and not trainer_approached
                and first_alias and not has_prior_movement):
            trainer_approached = True
            effects = [e for e in effects
                       if not e.startswith("battle_emote:")]
            effects.append(f"battle_emote:{first_alias}")
            npc = actors.get(first_alias)
            player = actors.get("player")
            if npc and player:
                facing = npc.get("facing", "down")
                dx, dy = DIRECTION_OFFSETS.get(facing, (0, 0))
                if dx != 0 or dy != 0:
                    target_x = player["x"] - dx
                    target_y = player["y"] - dy
                    npc["x"] = target_x
                    npc["y"] = target_y
                    npc["facing"] = facing
                player["facing"] = facing_toward(
                    player["x"], player["y"], npc["x"], npc["y"])

        # Show post-battle dialogue from expanded battle beat
        if btype == "battle" and data.get("postbattle"):
            dialogue = data["postbattle"]

        # Apply beat effects to state
        if btype == "move":
            for action in data.get("actions", []):
                apply_move_action(action, actors, movement_blocks)
        elif btype == "movement":
            pass  # Block definition — applied on "actor do Label"
        elif btype == "setpos":
            actor = data.get("actor", "")
            if actor in actors:
                try:
                    actors[actor]["x"] = int(data.get("x", actors[actor]["x"]))
                except (ValueError, TypeError):
                    pass
                try:
                    actors[actor]["y"] = int(data.get("y", actors[actor]["y"]))
                except (ValueError, TypeError):
                    pass
        elif btype == "hide":
            actor = data.get("actor", "")
            if actor in actors:
                actors[actor]["visible"] = False
        elif btype == "show":
            actor = data.get("actor", "")
            if actor in actors:
                actors[actor]["visible"] = True
        elif btype == "faint":
            actor = data.get("actor", "")
            if actor in actors:
                actors[actor]["facing"] = "down"
                effects.append(f"faint:{actor}")
        elif btype == "revive":
            actor = data.get("actor", "")
            if actor in actors:
                effects.append(f"revive:{actor}")
        elif btype == "faceplayer":
            player = actors.get("player")
            if player:
                for name, state in actors.items():
                    if name != "player":
                        state["facing"] = facing_toward(
                            state["x"], state["y"],
                            player["x"], player["y"])
        elif btype == "emote":
            actor = data.get("actor", "")
            effects = [e for e in effects if not e.startswith("emote:")]
            effects.append(f"emote:{actor}:{data.get('emote_name', '?')}")
        elif btype == "text":
            dialogue = data.get("content")
        elif btype == "dialogue":
            dialogue = data.get("text")
        elif btype == "closemessage":
            dialogue = None
        elif btype == "fade":
            fade_type = data.get("fade_type", "")
            if fade_type in ("in", "from_black", "from_white"):
                effects = [e for e in effects if not e.startswith("fade_")]
            else:
                effects = [e for e in effects if not e.startswith("fade_")]
                effects.append(f"fade_{fade_type}")
        elif btype == "sound":
            effects.append(f"sound:{data.get('constant', '')}")
        elif btype == "music":
            effects = [e for e in effects if not e.startswith("music:")]
            effects.append(f"music:{data.get('constant', '')}")
        elif btype == "fanfare":
            effects.append(f"fanfare:{data.get('constant', '')}")
        elif btype == "shake":
            effects.append("shake")
        elif btype == "flag":
            action = data.get("action", "")
            flag_name = data.get("flag_name", "")
            if action == "set" and flag_name not in flags_set:
                flags_set.append(flag_name)
            elif action == "clear" and flag_name in flags_set:
                flags_set.remove(flag_name)
        elif btype == "var":
            vars_set[data.get("var_name", "")] = data.get("value", "")

        # Build frame snapshot
        frames.append({
            "beat_index": idx,
            "beat": beat,
            "actors": copy.deepcopy(actors),
            "dialogue": dialogue,
            "effects": list(effects),
            "flags_set": list(flags_set),
            "vars_set": dict(vars_set),
        })

        # Clear transient effects after snapshot
        effects = [e for e in effects
                   if e.startswith("fade_") or e.startswith("music:")]

    # Always produce at least one frame (initial state)
    if not frames:
        frames.append({
            "beat_index": 0,
            "beat": {"type": "empty", "data": {}},
            "actors": copy.deepcopy(actors),
            "dialogue": None,
            "effects": [],
            "flags_set": [],
            "vars_set": {},
        })

    return frames


# ---------------------------------------------------------------------------
# Convenience: text → frames (no files needed)
# ---------------------------------------------------------------------------

def make_actor(x=0, y=0, facing="down", visible=True, graphics_id="",
               is_pokemon=False, species=""):
    """Build an actor state dict — convenience for test scripts."""
    return {
        "x": x, "y": y, "facing": facing,
        "visible": visible, "graphics_id": graphics_id,
        "is_pokemon": is_pokemon, "species": species,
    }


def parse_and_simulate(source_text, actors=None, setup_movements=None):
    """Parse TorScript source text and simulate it in one call.

    Args:
        source_text: raw TorScript string (with alias lines, beats, etc.)
        actors: dict of actor name -> {x, y, facing, visible, graphics_id}.
                If None, creates a default player at (0, 0).  Actors named
                in script aliases are auto-created at (0, 0) if missing.
        setup_movements: optional movement block dict

    Returns:
        list of frame dicts (same as simulate_scene)
    """
    parsed = parse_script_text(source_text)

    # Build initial positions
    positions = {}
    if actors:
        positions = copy.deepcopy(actors)

    # Ensure player exists
    if "player" not in positions:
        positions["player"] = make_actor(0, 0, "up")

    # Auto-create cast actors that weren't provided
    pokemon = parsed.get("pokemon", {})
    for alias in parsed.get("cast", {}):
        if alias not in positions:
            is_poke = alias in pokemon
            positions[alias] = make_actor(0, 0, "down",
                                          is_pokemon=is_poke,
                                          species=pokemon.get(alias, ""))

    return simulate_scene(parsed, positions, setup_movements)
