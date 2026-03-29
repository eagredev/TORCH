"""Pure data constants for TORCH — emotes, movement commands, catalogs."""
# TORCH_MODULE: Data Constants
# TORCH_GROUP: Core
import re


# ============================================================
# BUILT-IN EMOTE MAPPINGS (emote TorScript -> movement command)
# ============================================================
BUILTIN_EMOTES = {
    "!": "emote_exclamation_mark",
    "?": "emote_question_mark",
    "!!": "emote_double_exclamation_mark",
    "x": "emote_x",
    "heart": "emote_heart",
}

# Emotes that have a Common_Movement shortcut (no custom block needed)
COMMON_EMOTES = {
    "!": "Common_Movement_ExclamationMark",
    "?": "Common_Movement_QuestionMark",
}

# ============================================================
# COMMON MOVEMENT MAPPINGS (single-action -> built-in labels)
# ============================================================
COMMON_FACE = {
    "down": "Common_Movement_FaceDown",
    "up": "Common_Movement_FaceUp",
    "left": "Common_Movement_FaceLeft",
    "right": "Common_Movement_FaceRight",
    "player": "Common_Movement_FacePlayer",
    "away": "Common_Movement_FaceAwayPlayer",
}

# Walk commands -> movement_command prefix
WALK_COMMANDS = {
    "walk": "walk",
    "walkfast": "walk_fast",
    "walkslow": "walk_slow",
    "run": "walk_fast",
    "slide": "slide",
}

WALKTO_COMMANDS = {
    "walkto": "walk",
    "walkfastto": "walk_fast",
    "walkslowto": "walk_slow",
    "runto": "walk_fast",
}

DIRECTIONS = ["up", "down", "left", "right"]

# Pokemon actor defaults
POKEMON_DEFAULT_MOVEMENT = "MOVEMENT_TYPE_WALK_IN_PLACE_DOWN"
POKEMON_STATIC_MOVEMENTS = {
    "MOVEMENT_TYPE_NONE",
    "MOVEMENT_TYPE_FACE_UP",
    "MOVEMENT_TYPE_FACE_DOWN",
    "MOVEMENT_TYPE_FACE_LEFT",
    "MOVEMENT_TYPE_FACE_RIGHT",
}

JUMP_COMMANDS = {
    "up": "jump_up",
    "down": "jump_down",
    "left": "jump_left",
    "right": "jump_right",
}

JUMP2_COMMANDS = {
    "up": "jump_2_up",
    "down": "jump_2_down",
    "left": "jump_2_left",
    "right": "jump_2_right",
}


# ============================================================
# MOVEMENT COMMAND CATALOG
# ============================================================
MOVEMENT_COMMAND_CATEGORIES = [
    ("Face", [
        "face_down", "face_up", "face_left", "face_right",
        "face_player", "face_away_player",
    ]),
    ("Walk", [
        "walk_down", "walk_up", "walk_left", "walk_right",
    ]),
    ("Walk (slow)", [
        "walk_slow_down", "walk_slow_up", "walk_slow_left", "walk_slow_right",
    ]),
    ("Walk (fast)", [
        "walk_fast_down", "walk_fast_up", "walk_fast_left", "walk_fast_right",
    ]),
    ("Walk in place", [
        "walk_in_place_down", "walk_in_place_up",
        "walk_in_place_left", "walk_in_place_right",
        "walk_in_place_fast_down", "walk_in_place_fast_up",
        "walk_in_place_fast_left", "walk_in_place_fast_right",
    ]),
    ("Delay", [
        "delay_1", "delay_2", "delay_4", "delay_8", "delay_16",
    ]),
    ("Jump", [
        "jump_down", "jump_up", "jump_left", "jump_right",
    ]),
    ("Jump (2 tiles)", [
        "jump_2_down", "jump_2_up", "jump_2_left", "jump_2_right",
    ]),
    ("Jump in place", [
        "jump_in_place_down", "jump_in_place_up",
        "jump_in_place_left", "jump_in_place_right",
    ]),
    ("Slide", [
        "slide_down", "slide_up", "slide_left", "slide_right",
    ]),
    ("Visibility", [
        "set_visible", "set_invisible",
    ]),
    ("Locking", [
        "lock_facing_direction", "unlock_facing_direction",
        "disable_anim", "enable_anim",
    ]),
    ("Emotes", [
        "emote_exclamation_mark", "emote_question_mark",
        "emote_double_exclamation_mark", "emote_x",
        "emote_heart", "emote_dot_dot_dot",
    ]),
    ("Other", [
        "step_end",
    ]),
]

ALL_MOVEMENT_COMMANDS = set()
for _cat_name, _cat_cmds in MOVEMENT_COMMAND_CATEGORIES:
    ALL_MOVEMENT_COMMANDS.update(_cat_cmds)

_MOVEMENT_ENGLISH = {
    "face_down": "Face down",
    "face_up": "Face up",
    "face_left": "Face left",
    "face_right": "Face right",
    "face_player": "Face player",
    "face_away_player": "Face away from player",
    "walk_down": "Walk down",
    "walk_up": "Walk up",
    "walk_left": "Walk left",
    "walk_right": "Walk right",
    "walk_slow_down": "Walk slowly down",
    "walk_slow_up": "Walk slowly up",
    "walk_slow_left": "Walk slowly left",
    "walk_slow_right": "Walk slowly right",
    "walk_fast_down": "Walk fast down",
    "walk_fast_up": "Walk fast up",
    "walk_fast_left": "Walk fast left",
    "walk_fast_right": "Walk fast right",
    "walk_in_place_down": "Walk in place (down)",
    "walk_in_place_up": "Walk in place (up)",
    "walk_in_place_left": "Walk in place (left)",
    "walk_in_place_right": "Walk in place (right)",
    "walk_in_place_fast_down": "Walk in place fast (down)",
    "walk_in_place_fast_up": "Walk in place fast (up)",
    "walk_in_place_fast_left": "Walk in place fast (left)",
    "walk_in_place_fast_right": "Walk in place fast (right)",
    "delay_1": "Delay (1 frame)",
    "delay_2": "Delay (2 frames)",
    "delay_4": "Delay (4 frames)",
    "delay_8": "Delay (8 frames)",
    "delay_16": "Delay (16 frames)",
    "jump_down": "Jump down",
    "jump_up": "Jump up",
    "jump_left": "Jump left",
    "jump_right": "Jump right",
    "jump_2_down": "Jump 2 tiles down",
    "jump_2_up": "Jump 2 tiles up",
    "jump_2_left": "Jump 2 tiles left",
    "jump_2_right": "Jump 2 tiles right",
    "jump_in_place_down": "Jump in place (down)",
    "jump_in_place_up": "Jump in place (up)",
    "jump_in_place_left": "Jump in place (left)",
    "jump_in_place_right": "Jump in place (right)",
    "slide_down": "Slide down",
    "slide_up": "Slide up",
    "slide_left": "Slide left",
    "slide_right": "Slide right",
    "set_visible": "Set visible",
    "set_invisible": "Set invisible",
    "lock_facing_direction": "Lock facing direction",
    "unlock_facing_direction": "Unlock facing direction",
    "disable_anim": "Disable animation",
    "enable_anim": "Enable animation",
    "emote_exclamation_mark": "Emote: !",
    "emote_question_mark": "Emote: ?",
    "emote_double_exclamation_mark": "Emote: !!",
    "emote_x": "Emote: X",
    "emote_heart": "Emote: heart",
    "emote_dot_dot_dot": "Emote: ...",
    "step_end": "End of movement",
}


def _movement_cmd_english(cmd):
    """Return a plain-English description for a movement command."""
    if cmd in _MOVEMENT_ENGLISH:
        return _MOVEMENT_ENGLISH[cmd]
    # Handle repeat syntax like "walk_down * 3"
    m = re.match(r'^(\w+)\s*\*\s*(\d+)$', cmd)
    if m:
        base = _MOVEMENT_ENGLISH.get(m.group(1), m.group(1))
        return f"{base} x{m.group(2)}"
    return cmd.replace("_", " ").title()
