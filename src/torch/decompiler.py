"""Pory-to-TorScript decompiler — converts .pory Poryscript back to .txt TorScript."""
# TORCH_MODULE: Script Decompiler
# TORCH_GROUP: Script Studio
import re

from torch.data import (
    BUILTIN_EMOTES, COMMON_EMOTES, COMMON_FACE,
    COMMON_WALK_IN_PLACE_FASTER, COMMON_WALK, COMMON_WALK_SLOW,
    COMMON_WALK_FAST, COMMON_WALK_FASTER, COMMON_DELAY,
    WALK_COMMANDS, JUMP_COMMANDS, JUMP2_COMMANDS,
)

# Known Poryscript commands that should be treated as explicit pory passthrough
# rather than accidental fallthrough. Mirrors inc_decompiler's command tables.
_KNOWN_PORY_COMMANDS = {
    # Variable ops (copyvar/addvar/subvar now have native TorScript)
    "setorcopyvar", "callnative",
    # Object/actor ops (actor resolution applied)
    "turnobject", "turnvobject",
    "setobjectxyperm", "setobjectmovementtype", "setobjectsubpriority",
    "resetobjectsubpriority",
    # Warps
    "warp", "warpsilent", "warpdoor", "warphole", "warpteleport", "warpwhitefade",
    "setwarp", "setdynamicwarp", "setescapewarp", "setholewarp", "setdivewarp",
    # Map manipulation (setmetatile now has native `tile` command)
    "setweather", "setmaplayoutindex",
    # Messages (non-msgbox) — multichoice stays pory (hardcoded list IDs)
    "multichoice", "multichoicedefault",
    # Items / money / coins (checkitem/removeitem/pokemart now native)
    "additem", "checkitemtype",
    "addmoney", "removemoney",
    "checkcoins", "addcoins", "removecoins",
    # Audio (extended)
    "fadescreenspeed", "fadescreenswapbuffers",
    # Visuals (showmonpic now native `showmon`)
    "createvobject",
    "dofieldeffect", "dofieldeffectsparkle", "waitfieldeffect",
    "setfieldeffectargument",
    "animateflash", "setflashlevel",
    # Pokemon (setwildbattle/dowildbattle now native)
    "givemon", "giveegg", "seteventmon",
    # Trainer flags
    "cleartrainerflag", "settrainerflag",
    # Buffers (common ones now native `buffer` command)
    "bufferitemnameplural", "bufferstdstring", "bufferpartymonnick",
    # Misc
    "setstepcallback", "register_matchcall",
    "setrespawn", "compare", "hidefollower",
    # Minigames
    "playslotmachine",
    # (pokemartdecoration now handled as shop LIST decoration)
    # Frontier
    "frontier_results", "frontier_get", "frontier_checkvisittrainer",
    "dome_get", "dome_getwinnersname", "dome_showprevtourneytree",
    "pike_gethint", "pike_getroomtype",
    "trainerhill_getownerstate", "trainerhill_inchallenge", "trainerhill_settrainerflags",
    "fallarbortent_getprize", "verdanturftent_getprize", "slateporttent_getprize",
    "showcontestpainting", "givedecoration", "getpokenewsactive",
}

# Known Poryscript bare keywords (no args) that should be explicit pory passthrough
# (only truly niche commands that have no TorScript equivalent)
_KNOWN_BARE_COMMANDS = {
    "doweather", "hideplayer", "showplayer",
    "dotimebasedevents",
}

# Actor-reference argument positions for known commands (0-indexed positions
# that contain LOCALID_* references needing resolution)
_ACTOR_ARG_POSITIONS = {
    "turnobject": [0], "turnvobject": [0],
    "hideobjectat": [0], "showobjectat": [0],
    "setobjectxyperm": [0], "setobjectmovementtype": [0],
    "setobjectsubpriority": [0], "resetobjectsubpriority": [0],
    "copyobjectxytoperm": [0],
}

# ============================================================
# REVERSE LOOKUP TABLES (auto-derived from data.py)
# ============================================================

_REV_COMMON_FACE = {v: k for k, v in COMMON_FACE.items()}
_REV_COMMON_EMOTES = {v: k for k, v in COMMON_EMOTES.items()}
_REV_BUILTIN_EMOTES = {v: k for k, v in BUILTIN_EMOTES.items()}
_REV_WALK_IN_PLACE_FASTER = {v: k for k, v in COMMON_WALK_IN_PLACE_FASTER.items()}
_REV_COMMON_WALK = {v: ("walk", k) for k, v in COMMON_WALK.items()}
_REV_COMMON_WALK.update({v: ("walkslow", k) for k, v in COMMON_WALK_SLOW.items()})
_REV_COMMON_WALK.update({v: ("walkfast", k) for k, v in COMMON_WALK_FAST.items()})
_REV_COMMON_WALK.update({v: ("walkfast", k) for k, v in COMMON_WALK_FASTER.items()})

# WALK_COMMANDS maps TorScript name -> pory prefix: {"walk": "walk", "walkfast": "walk_fast", ...}
# We want pory prefix -> canonical TorScript name (skip "run" since it's an alias for walkfast)
_REV_WALK_PREFIX = {}
for _ts_name, _pory_prefix in WALK_COMMANDS.items():
    if _ts_name == "run":
        continue  # skip alias — canonical is "walkfast"
    _REV_WALK_PREFIX[_pory_prefix] = _ts_name

_REV_JUMP = {v: k for k, v in JUMP_COMMANDS.items()}
_REV_JUMP2 = {v: k for k, v in JUMP2_COMMANDS.items()}

_REV_FADE = {
    "FADE_TO_BLACK": "black",
    "FADE_FROM_BLACK": "in",
    "FADE_TO_WHITE": "white",
    "FADE_FROM_WHITE": "from white",
}


# ============================================================
# CONDITION EXPRESSION REVERSAL
# ============================================================

def _reverse_condition(expr):
    """Convert a Poryscript condition expression back to TorScript.

    flag(FLAG_X)           -> FLAG_X
    !flag(FLAG_X)          -> not FLAG_X
    var(VAR_X) == VALUE    -> VAR_X == VALUE
    !(var(VAR_X) == VALUE) -> not VAR_X == VALUE
    defeated(TRAINER_X)    -> defeated TRAINER_X
    !defeated(TRAINER_X)   -> not defeated TRAINER_X
    A && B                 -> A and B
    A || B                 -> A or B
    """
    expr = expr.strip()

    # Compound: A && B or A || B (split on top-level operator only)
    parts, op = _split_compound(expr)
    if parts:
        left = _reverse_condition(parts[0])
        right = _reverse_condition(parts[1])
        ts_op = "and" if op == "&&" else "or"
        return f"{left} {ts_op} {right}"

    # Negated wrapper: !(...)
    if expr.startswith("!(") and expr.endswith(")"):
        inner = expr[2:-1]
        return f"not {_reverse_condition(inner)}"

    # Negated flag: !flag(X)
    m = re.match(r'^!flag\((\w+)\)$', expr)
    if m:
        return f"not {m.group(1)}"

    # flag(X)
    m = re.match(r'^flag\((\w+)\)$', expr)
    if m:
        return m.group(1)

    # Negated defeated: !defeated(X)
    m = re.match(r'^!defeated\((\w+)\)$', expr)
    if m:
        return f"not defeated {m.group(1)}"

    # defeated(X)
    m = re.match(r'^defeated\((\w+)\)$', expr)
    if m:
        return f"defeated {m.group(1)}"

    # var(VAR_X) OP VALUE
    m = re.match(r'^var\((\w+)\)\s*(==|!=|<=|>=|<|>)\s*(\w+)$', expr)
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"

    # Fallback — return as-is (handles already-simple expressions)
    return expr


def _split_compound(expr):
    """Split a compound condition on top-level && or ||.

    Returns (parts_list, operator) or (None, None) if not compound.
    Only splits on the first top-level operator to allow recursive handling.
    """
    depth = 0
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif depth == 0:
            if expr[i:i+2] == '&&':
                return [expr[:i].strip(), expr[i+2:].strip()], '&&'
            if expr[i:i+2] == '||':
                return [expr[:i].strip(), expr[i+2:].strip()], '||'
        i += 1
    return None, None


# ============================================================
# ACTOR RESOLUTION HELPERS
# ============================================================

def _resolve_actors_in_args(args_str, state, positions=None):
    """Resolve LOCALID_* and OBJ_EVENT_ID_PLAYER in comma-separated args.

    If positions is given, only resolve args at those 0-indexed positions.
    Otherwise resolve all args that look like actor references.
    """
    parts = [a.strip() for a in args_str.split(',')]
    resolved = []
    for idx, part in enumerate(parts):
        if positions is not None:
            if idx in positions:
                resolved.append(_resolve_actor_reverse(part, state))
            else:
                resolved.append(part)
        elif part.startswith('LOCALID_') or part == 'OBJ_EVENT_ID_PLAYER':
            resolved.append(_resolve_actor_reverse(part, state))
        else:
            resolved.append(part)
    return ', '.join(resolved)


# ============================================================
# DECOMPILER STATE
# ============================================================

class DecompilerState:
    def __init__(self, map_name):
        self.map_name = map_name
        self.aliases = {}            # "LOCALID_BUSTER" -> "buster"
        self.npc_ids = {}            # "LOCALID_BUSTER" -> 5
        self.movement_blocks = {}    # label -> [commands]
        self.text_blocks = {}        # label -> content
        self.auto_move_labels = set()  # MapName_Move_N labels
        self.auto_labels = set()     # MapName_BagFull etc.
        self.auto_text_labels = set()  # text blocks consumed by trainerbattle inlining
        self.call_targets = {}       # label → list of caller labels
        self.script_blocks_raw = []  # [(label, [body_lines])] from Pass 1
        self.script_blocks_decompiled = []  # [(label, [torscript_lines])]
        self.mapscripts_labels = []
        self.warnings = []

    def warn(self, msg):
        self.warnings.append(msg)


# ============================================================
# PASS 1: PARSE .PORY STRUCTURE
# ============================================================

def _extract_block_body(lines, start):
    """Extract lines inside braces starting at `start` (the line with `{`).

    Returns (body_lines, end_index) where end_index is the line with `}`.
    """
    depth = 0
    body = []
    for i in range(start, len(lines)):
        line = lines[i]
        # Count braces
        for ch in line:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    # Grab anything before the closing brace on this line
                    before_close = line[:line.rindex('}')].strip()
                    if before_close:
                        body.append(before_close)
                    return body, i
        # After counting, if we're past the opening brace line, add content
        if i == start:
            # First line — grab content after the opening brace
            brace_pos = line.index('{')
            after = line[brace_pos + 1:].strip()
            if after:
                body.append(after)
        else:
            body.append(line.strip())
    return body, len(lines) - 1


def _parse_pory_structure(pory_text, state):
    """Pass 1: Parse top-level .pory blocks into state."""
    lines = pory_text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # const LOCALID_X = N
        m = re.match(r'^const\s+(LOCALID_\w+)\s*=\s*(\d+)$', line)
        if m:
            const_name = m.group(1)
            npc_id = int(m.group(2))
            # Derive alias: LOCALID_BUSTER -> buster
            alias = const_name[len("LOCALID_"):].lower()
            state.aliases[const_name] = alias
            state.npc_ids[const_name] = npc_id
            i += 1
            continue

        # mapscripts Label { ... }
        m = re.match(r'^mapscripts\s+(\w+)\s*\{', line)
        if m:
            label = m.group(1)
            if label not in state.mapscripts_labels:
                state.mapscripts_labels.append(label)
            _, end = _extract_block_body(lines, i)
            i = end + 1
            continue

        # movement Label { ... }
        m = re.match(r'^movement\s+(\w+)\s*\{', line)
        if m:
            label = m.group(1)
            body, end = _extract_block_body(lines, i)
            cmds = [b for b in body if b and b != 'step_end']
            state.movement_blocks[label] = cmds
            # Auto-move detection: MapName_Move_N
            if state.map_name and re.match(
                rf'^{re.escape(state.map_name)}_Move_\d+$', label
            ):
                state.auto_move_labels.add(label)
            i = end + 1
            continue

        # text Label { "..." }
        m = re.match(r'^text\s+(\w+)\s*\{', line)
        if m:
            label = m.group(1)
            body, end = _extract_block_body(lines, i)
            # Join text body and strip quotes
            text_content = ""
            for tline in body:
                tline = tline.strip()
                if tline.startswith('"') and tline.endswith('"'):
                    text_content += tline[1:-1]
                elif tline.startswith('"'):
                    text_content += tline[1:]
                elif tline.endswith('"'):
                    text_content += tline[:-1]
                else:
                    text_content += tline
            state.text_blocks[label] = text_content
            i = end + 1
            continue

        # script Label { ... }
        m = re.match(r'^script\s+(\w+)\s*\{', line)
        if m:
            label = m.group(1)
            body, end = _extract_block_body(lines, i)
            # Detect auto-labels: MapName_BagFull
            if state.map_name and label == f"{state.map_name}_BagFull":
                state.auto_labels.add(label)
            state.script_blocks_raw.append((label, body))
            i = end + 1
            continue

        i += 1


# ============================================================
# ACTOR RESOLUTION (reverse)
# ============================================================

def _resolve_actor_reverse(pory_ref, state):
    """Convert a Poryscript actor reference back to TorScript."""
    if pory_ref == "OBJ_EVENT_ID_PLAYER":
        return "player"
    if pory_ref in state.aliases:
        return state.aliases[pory_ref]
    # Numeric literal -> npcN
    if pory_ref.isdigit():
        return f"npc{pory_ref}"
    # LOCALID_ that we don't have an alias for
    if pory_ref.startswith("LOCALID_"):
        return pory_ref[len("LOCALID_"):].lower()
    # 0 used in waitmovement(0) — not a real actor
    return pory_ref


# ============================================================
# MOVEMENT RESOLUTION
# ============================================================

def _decompile_movement_cmds(cmds):
    """Convert a list of movement commands to TorScript movement parts.

    Returns list of (torscript_suffix) strings like "walk up 3", "walkfast down",
    or None if too complex to inline.
    """
    results = []
    for cmd in cmds:
        # Handle repeat syntax: "walk_down * 3"
        m = re.match(r'^(\w+)\s*\*\s*(\d+)$', cmd)
        if m:
            base_cmd = m.group(1)
            count = int(m.group(2))
        else:
            base_cmd = cmd
            count = 1

        # Try walk/walkfast/walkslow/slide
        m2 = re.match(r'^(walk|walk_fast|walk_slow|slide)_(up|down|left|right)$', base_cmd)
        if m2:
            prefix = m2.group(1)
            direction = m2.group(2)
            ts_cmd = _REV_WALK_PREFIX.get(prefix, prefix)
            results.append(f"{ts_cmd} {direction} {count}")
            continue

        # Try jump (1 tile)
        if base_cmd in _REV_JUMP:
            direction = _REV_JUMP[base_cmd]
            if count > 1:
                return None  # Can't repeat jumps
            results.append(f"jump {direction}")
            continue

        # Try jump (2 tiles)
        if base_cmd in _REV_JUMP2:
            direction = _REV_JUMP2[base_cmd]
            if count > 1:
                return None
            results.append(f"jump {direction} 2")
            continue

        # Emote commands
        if base_cmd in _REV_BUILTIN_EMOTES:
            emote_name = _REV_BUILTIN_EMOTES[base_cmd]
            results.append(f"emote {emote_name}")
            continue

        # Face commands (in movement blocks)
        face_map = {
            "face_down": "face down", "face_up": "face up",
            "face_left": "face left", "face_right": "face right",
            "face_player": "face player", "face_away_player": "face away",
        }
        if base_cmd in face_map:
            results.append(face_map[base_cmd])
            continue

        # Unknown — can't inline
        return None

    return results


def _resolve_movement(actor_ts, label, state):
    """Resolve a movement label to TorScript beat(s).

    Returns a list of TorScript lines.
    """
    # Common_Movement face shortcuts
    if label in _REV_COMMON_FACE:
        direction = _REV_COMMON_FACE[label]
        return [f"{actor_ts} face {direction}"]

    # Common_Movement emote shortcuts
    if label in _REV_COMMON_EMOTES:
        emote = _REV_COMMON_EMOTES[label]
        return [f"{actor_ts} emote {emote}"]

    # Common_Movement WalkInPlaceFaster → face (visually equivalent)
    if label in _REV_WALK_IN_PLACE_FASTER:
        direction = _REV_WALK_IN_PLACE_FASTER[label]
        return [f"{actor_ts} face {direction}"]

    # Common_Movement single-step walks (Walk, WalkSlow, WalkFast, WalkFaster)
    if label in _REV_COMMON_WALK:
        cmd, direction = _REV_COMMON_WALK[label]
        return [f"{actor_ts} {cmd} {direction} 1"]

    # Common_Movement delays
    if label in COMMON_DELAY:
        frames = COMMON_DELAY[label]
        return [f"pause {frames}"]

    # Auto-generated movement blocks — try to inline
    if label in state.auto_move_labels and label in state.movement_blocks:
        cmds = state.movement_blocks[label]
        parts = _decompile_movement_cmds(cmds)
        if parts is not None and len(parts) == 1:
            return [f"{actor_ts} {parts[0]}"]
        # Multi-command or complex — can't inline, use do
        return [f"{actor_ts} do {label}"]

    # User-defined movement block
    return [f"{actor_ts} do {label}"]


# ============================================================
# MSGBOX HANDLING
# ============================================================

def _strip_msgbox_text(raw):
    """Strip format() wrapper and trailing $ from msgbox text."""
    text = raw.strip()
    # Strip format() wrapper
    if text.startswith("format(") and text.endswith(")"):
        text = text[7:-1]
    # Strip surrounding quotes
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    # Strip trailing $
    if text.endswith("$"):
        text = text[:-1]
    return text


def _parse_msgbox(line):
    """Parse a msgbox line. Returns (text, msg_type) or None."""
    # msgbox("text", MSGBOX_TYPE) — may have multi-line text joined
    m = re.match(r'^msgbox\(\s*(.+),\s*(MSGBOX_\w+)\s*\)$', line, re.DOTALL)
    if m:
        return _strip_msgbox_text(m.group(1)), m.group(2)
    # msgbox(format("text"), MSGBOX_TYPE)
    m = re.match(r'^msgbox\(\s*format\((.+)\),\s*(MSGBOX_\w+)\s*\)$', line, re.DOTALL)
    if m:
        return _strip_msgbox_text(m.group(1)), m.group(2)
    return None


# ============================================================
# MULTI-LINE PATTERN MATCHERS
# ============================================================

def _try_shake(body, i, state):
    """Match: setvar(VAR_0x8004,I) + setvar(VAR_0x8005,C) + special(ShakeCamera)"""
    if i + 2 >= len(body):
        return None, 0
    l0, l1, l2 = body[i], body[i + 1], body[i + 2]
    m0 = re.match(r'^setvar\(VAR_0x8004,\s*(\S+)\)$', l0)
    m1 = re.match(r'^setvar\(VAR_0x8005,\s*(\S+)\)$', l1)
    if m0 and m1 and l2 == "special(ShakeCamera)":
        return f"shake {m0.group(1)} {m1.group(1)}", 3
    return None, 0


def _try_give(body, i, state):
    """Match: giveitem(...) + compare(VAR_RESULT, FALSE) + goto_if_eq(BagFull)"""
    if i + 2 >= len(body):
        return None, 0
    l0, l1, l2 = body[i], body[i + 1], body[i + 2]
    m0 = re.match(r'^giveitem\((\w+)(?:,\s*(\w+))?\)$', l0)
    if not m0:
        return None, 0
    if l1 != "compare(VAR_RESULT, FALSE)":
        return None, 0
    m2 = re.match(r'^goto_if_eq\((\w+)\)$', l2)
    if not m2:
        return None, 0
    item = m0.group(1)
    qty = m0.group(2)
    bag_label = m2.group(1)
    # Mark bag-full label as auto
    state.auto_labels.add(bag_label)
    if qty and qty != "1":
        return f"give {item} {qty}", 3
    return f"give {item}", 3


def _try_fanfare(body, i, state):
    """Match: playfanfare(X) + waitfanfare"""
    if i + 1 >= len(body):
        return None, 0
    l0, l1 = body[i], body[i + 1]
    m = re.match(r'^playfanfare\((\w+)\)$', l0)
    if m and l1 == "waitfanfare":
        return f"fanfare {m.group(1)}", 2
    return None, 0


def _try_end(body, i, state):
    """Match: releaseall + end"""
    if i + 1 >= len(body):
        return None, 0
    if body[i] == "releaseall" and body[i + 1] == "end":
        return "end", 2
    return None, 0


def _try_release(body, i, state):
    """Match: release + end"""
    if i + 1 >= len(body):
        return None, 0
    if body[i] == "release" and body[i + 1] == "end":
        return "release", 2
    return None, 0


def _try_conditional_jump(body, i, state):
    """Match conditional goto/call patterns:

    if (CONDITION) {
        goto(LABEL)
    }
    → gotoif CONDITION LABEL

    if (CONDITION) {
        call(LABEL)
    }
    → if CONDITION / call LABEL / endif

    Also handles } elif and } else chains for full if/elif/else/endif blocks.
    """
    l0 = body[i].strip()

    # Must start with if (...)
    m = re.match(r'^if\s*\((.+)\)\s*\{$', l0)
    if not m:
        return None, 0

    condition_expr = m.group(1)

    # Collect branches: [(condition_or_None, body_lines)]
    # Must track brace depth to handle nested if/switch blocks
    branches = []
    j = i + 1
    current_body = []
    depth = 0  # extra depth from nested braces within the body

    while j < len(body):
        line = body[j].strip()

        # Count braces to track nesting depth
        line_opens = line.count('{')
        line_closes = line.count('}')

        if depth > 0:
            # We're inside a nested block — just collect lines
            current_body.append(line)
            depth += line_opens - line_closes
            j += 1
            continue

        # At top level of this if-block
        if line_opens > 0 and not re.match(r'^\}\s*(elif|else)\s', line):
            # Opening a nested block (inner if, switch, etc.)
            current_body.append(line)
            depth += line_opens - line_closes
            j += 1
            continue

        # Check for } (end of block), } elif (...) {, or } else {
        if line == '}':
            branches.append((condition_expr, current_body))
            j += 1
            break
        elif re.match(r'^\}\s*elif\s*\((.+)\)\s*\{$', line):
            branches.append((condition_expr, current_body))
            current_body = []
            condition_expr = re.match(r'^\}\s*elif\s*\((.+)\)\s*\{$', line).group(1)
            j += 1
            continue
        elif re.match(r'^\}\s*else\s*\{$', line):
            branches.append((condition_expr, current_body))
            current_body = []
            condition_expr = None  # else branch
            j += 1
            continue
        else:
            current_body.append(line)
            j += 1
            continue

    if not branches:
        return None, 0

    consumed = j - i

    # Special case: single branch with single goto → gotoif
    if len(branches) == 1:
        cond, body_lines = branches[0]
        body_lines = [l for l in body_lines if l.strip()]
        if len(body_lines) == 1:
            m_goto = re.match(r'^goto\((\w+)\)$', body_lines[0])
            if m_goto:
                ts_cond = _reverse_condition(cond)
                return f"gotoif {ts_cond} {m_goto.group(1)}", consumed
            m_call = re.match(r'^call\((\w+)\)$', body_lines[0])
            if m_call:
                ts_cond = _reverse_condition(cond)
                return [
                    f"if {ts_cond}",
                    f"call {m_call.group(1)}",
                    "endif",
                ], consumed

    # General case: full if/elif/else/endif block
    result = []
    for idx, (cond, branch_body) in enumerate(branches):
        if idx == 0:
            ts_cond = _reverse_condition(cond)
            result.append(f"if {ts_cond}")
        elif cond is None:
            result.append("else")
        else:
            ts_cond = _reverse_condition(cond)
            result.append(f"elif {ts_cond}")

        # Recursively decompile the branch body
        branch_ts = _decompile_body(branch_body, state)
        result.extend(branch_ts)

    result.append("endif")
    return result, consumed


def _try_movement(body, i, state):
    """Match: applymovement(A,L) + waitmovement(...) sequences.

    Handles single and parallel movement.
    """
    if i >= len(body):
        return None, 0
    m = re.match(r'^applymovement\((\w+),\s*(\w+)\)$', body[i])
    if not m:
        return None, 0

    # Collect consecutive applymovement lines
    moves = []  # [(actor_ref, label)]
    j = i
    while j < len(body):
        mm = re.match(r'^applymovement\((\w+),\s*(\w+)\)$', body[j])
        if mm:
            moves.append((mm.group(1), mm.group(2)))
            j += 1
        else:
            break

    # Expect waitmovement(s)
    waits_consumed = 0
    if j < len(body):
        # Single: waitmovement(0)
        if body[j] == "waitmovement(0)":
            waits_consumed = 1
        else:
            # Per-actor waits
            for actor_ref, _ in moves:
                if j + waits_consumed < len(body):
                    wm = re.match(r'^waitmovement\((\w+)\)$', body[j + waits_consumed])
                    if wm:
                        waits_consumed += 1

    total = len(moves) + waits_consumed

    if len(moves) == 1:
        actor_ref, label = moves[0]
        actor_ts = _resolve_actor_reverse(actor_ref, state)
        lines = _resolve_movement(actor_ts, label, state)
        return lines, total
    else:
        # Parallel movement — try to join with +
        parts = []
        for actor_ref, label in moves:
            actor_ts = _resolve_actor_reverse(actor_ref, state)
            resolved = _resolve_movement(actor_ts, label, state)
            if len(resolved) == 1:
                parts.append(resolved[0])
            else:
                # Complex — fall back to separate lines
                all_lines = []
                for actor_ref2, label2 in moves:
                    a = _resolve_actor_reverse(actor_ref2, state)
                    all_lines.extend(_resolve_movement(a, label2, state))
                return all_lines, total
        return [" + ".join(parts)], total


def _try_switch(body, i, state):
    """Match: switch (var(VAR)) { case N: ... default: ... }"""
    l0 = body[i].strip()
    m = re.match(r'^switch\s*\(var\((\w+)\)\)\s*\{$', l0)
    if not m:
        return None, 0

    var_name = m.group(1)
    result = [f"switch {var_name}"]

    j = i + 1
    current_case_label = None
    current_body = []

    while j < len(body):
        line = body[j].strip()

        if line == '}':
            # Flush last case
            if current_case_label is not None:
                result.append(current_case_label)
                branch_ts = _decompile_body(current_body, state)
                result.extend(branch_ts)
            j += 1
            break

        m_case = re.match(r'^case\s+(\w+):$', line)
        m_default = line == 'default:'

        if m_case or m_default:
            # Flush previous case
            if current_case_label is not None:
                result.append(current_case_label)
                branch_ts = _decompile_body(current_body, state)
                result.extend(branch_ts)
            current_body = []
            if m_case:
                current_case_label = f"case {m_case.group(1)}"
            else:
                current_case_label = "default"
            j += 1
            continue

        current_body.append(line)
        j += 1

    result.append("endswitch")
    consumed = j - i
    return result, consumed


def _try_choice_yesno(body, i, state):
    """Match: msgbox("text", MSGBOX_YESNO) + if/else → choice/option/endchoice"""
    l0 = body[i].strip()
    parsed = _parse_msgbox(l0)
    if not parsed:
        return None, 0
    text, msg_type = parsed
    if msg_type != "MSGBOX_YESNO":
        return None, 0

    # Must be followed by if (var(VAR_RESULT) == YES) { ... } else { ... }
    if i + 1 >= len(body):
        return None, 0
    l1 = body[i + 1].strip()
    m = re.match(r'^if\s*\(var\(VAR_RESULT\)\s*==\s*YES\)\s*\{$', l1)
    if not m:
        return None, 0

    # Use _try_conditional_jump to parse the if/else block
    ts_block, block_consumed = _try_conditional_jump(body, i + 1, state)
    if ts_block is None:
        return None, 0

    # ts_block should be a list: ["if ...", ...body..., "else", ...body..., "endif"]
    if not isinstance(ts_block, list):
        return None, 0

    # Extract branches from the ts_block
    result = [f'choice "{text}"']
    in_yes = False
    in_no = False
    for line in ts_block:
        stripped = line.strip() if isinstance(line, str) else line
        if stripped.startswith("if "):
            result.append('option "Yes"')
            in_yes = True
            continue
        if stripped == "else":
            result.append('option "No"')
            in_yes = False
            in_no = True
            continue
        if stripped == "endif":
            continue
        result.append(stripped)
    result.append("endchoice")

    consumed = 1 + block_consumed  # msgbox line + if/else block
    return result, consumed


def _try_compare_goto(body, i, state):
    """Match: compare(VAR, VALUE) + goto_if_OP(LABEL) → gotoif VAR OP VALUE LABEL"""
    if i + 1 >= len(body):
        return None, 0
    l0 = body[i].strip()
    l1 = body[i + 1].strip()

    m0 = re.match(r'^compare\((\w+),\s*(\w+)\)$', l0)
    if not m0:
        return None, 0

    var_name = m0.group(1)
    value = m0.group(2)

    # Map goto_if_OP to comparison operator
    op_map = {
        'goto_if_eq': '==', 'goto_if_ne': '!=',
        'goto_if_lt': '<', 'goto_if_le': '<=',
        'goto_if_gt': '>', 'goto_if_ge': '>=',
    }
    m1 = re.match(r'^(goto_if_\w+)\((\w+)\)$', l1)
    if not m1:
        return None, 0
    op_name = m1.group(1)
    label = m1.group(2)
    op = op_map.get(op_name)
    if not op:
        return None, 0
    return f"gotoif {var_name} {op} {value} {label}", 2


def _try_trainerbattle_text(body, i, state):
    """Match trainerbattle_*(TRAINER, TextLabel1, TextLabel2) and inline text if available.

    Also detects postbattle: trainerbattle + msgbox(..., MSGBOX_AUTOCLOSE).
    """
    l0 = body[i].strip()
    m = re.match(r'^(trainerbattle_\w+)\((.+)\)$', l0)
    if not m:
        return None, 0

    battle_type = m.group(1)
    args = [a.strip() for a in m.group(2).split(',')]

    # Only inline text for battle types with 2+ text label args
    # trainerbattle_single(TRAINER, IntroLabel, DefeatLabel)
    # trainerbattle_double(TRAINER, IntroLabel, DefeatLabel, OnlyOneMonLabel)
    if len(args) < 3:
        return None, 0

    trainer = args[0]
    intro_label = args[1]
    defeat_label = args[2]

    # Look up text blocks
    intro_text = state.text_blocks.get(intro_label)
    defeat_text = state.text_blocks.get(defeat_label)

    if intro_text is None and defeat_text is None:
        return None, 0  # Can't inline — keep original form

    consumed = 1
    result_lines = [f"{battle_type} {trainer}"]

    def _strip_text(t):
        if t.endswith("$"):
            t = t[:-1]
        return t

    if intro_text is not None:
        result_lines.append(f'  intro "{_strip_text(intro_text)}"')
        state.auto_text_labels.add(intro_label)
    else:
        result_lines.append(f'  intro {intro_label}')

    if defeat_text is not None:
        result_lines.append(f'  defeated "{_strip_text(defeat_text)}"')
        state.auto_text_labels.add(defeat_label)
    else:
        result_lines.append(f'  defeated {defeat_label}')

    # Check for postbattle: msgbox(..., MSGBOX_AUTOCLOSE) on next line
    if i + 1 < len(body):
        next_line = body[i + 1].strip()
        parsed = _parse_msgbox(next_line)
        if parsed:
            post_text, post_type = parsed
            if post_type == "MSGBOX_AUTOCLOSE":
                result_lines.append(f'  postbattle "{post_text}"')
                consumed = 2

    return result_lines, consumed


# Multi-line handlers in priority order
_MULTI_LINE_HANDLERS = [
    _try_shake,
    _try_give,
    _try_fanfare,
    _try_end,
    _try_release,
    _try_choice_yesno,
    _try_compare_goto,
    _try_trainerbattle_text,
    _try_movement,
    _try_switch,
    _try_conditional_jump,
]


# ============================================================
# SINGLE-LINE HANDLERS
# ============================================================

def _handle_single_line(line, state):
    """Try to decompile a single .pory line to TorScript. Returns str or None."""

    if line == "lockall":
        return "lock"
    if line == "lock":
        return "lock"
    if line == "faceplayer":
        return "faceplayer"
    if line == "closemessage":
        return "closemessage"
    if line == "waitstate":
        return "waitstate"
    if line == "return":
        return "return"
    if line == "end":
        return "end"
    if line == "release":
        return "release"
    if line == "releaseall":
        return "end"
    # Wait/sync commands → first-class beat types
    if line == "waitmessage":
        return "waitmessage"
    if line == "waitbuttonpress":
        return "waitbutton"
    if line == "waitse":
        return "waitse"
    if line == "waitmoncry":
        return "waitmoncry"
    if line == "waitdooranim":
        return "door wait"
    if line == "checkplayergender":
        return "check gender"
    if line == "getpartysize":
        return "check partysize"
    if line == "hidemonpic":
        return "hidemon"
    if line == "dowildbattle":
        return "wildbattle start"
    if line == "waitfanfare":
        return "waitfanfare"

    # Known bare Poryscript commands → explicit pory passthrough
    if line in _KNOWN_BARE_COMMANDS:
        return f"pory {line}"

    # msgbox
    parsed = _parse_msgbox(line)
    if parsed:
        text, msg_type = parsed
        if msg_type == "MSGBOX_NPC":
            return f'msgnpc "{text}"'
        return f'msg "{text}"'

    # fadescreen
    m = re.match(r'^fadescreen\((\w+)\)$', line)
    if m:
        fade_const = m.group(1)
        ts = _REV_FADE.get(fade_const)
        if ts:
            return f"fade {ts}"
        return f"pory {line}"

    # playse
    m = re.match(r'^playse\((\w+)\)$', line)
    if m:
        return f"sound {m.group(1)}"

    # playbgm
    m = re.match(r'^playbgm\((\w+),\s*FALSE\)$', line)
    if m:
        return f"music {m.group(1)}"

    # playmoncry (extended: CRY_MODE_NORMAL, ENCOUNTER, FAINT)
    m = re.match(r'^playmoncry\((\w+),\s*(\w+)\)$', line)
    if m:
        species, mode = m.group(1), m.group(2)
        if mode == "CRY_MODE_NORMAL":
            return f"cry {species}"
        elif mode == "CRY_MODE_ENCOUNTER":
            return f"cry {species} encounter"
        elif mode == "CRY_MODE_FAINT":
            return f"cry {species} faint"
        return f"pory playmoncry({species}, {mode})"

    # delay
    m = re.match(r'^delay\((\d+)\)$', line)
    if m:
        frames = int(m.group(1))
        if frames == 16:
            return "pause"
        elif frames == 32:
            return "pause long"
        else:
            return f"pause {frames}"

    # setflag
    m = re.match(r'^setflag\((\w+)\)$', line)
    if m:
        return f"flag set {m.group(1)}"

    # clearflag
    m = re.match(r'^clearflag\((\w+)\)$', line)
    if m:
        return f"flag clear {m.group(1)}"

    # setvar (but NOT the VAR_0x800x pattern consumed by shake)
    m = re.match(r'^setvar\((\w+),\s*(\w+)\)$', line)
    if m:
        return f"var {m.group(1)} {m.group(2)}"

    # removeobject
    m = re.match(r'^removeobject\((\w+)\)$', line)
    if m:
        actor = _resolve_actor_reverse(m.group(1), state)
        return f"hide {actor}"

    # addobject
    m = re.match(r'^addobject\((\w+)\)$', line)
    if m:
        actor = _resolve_actor_reverse(m.group(1), state)
        return f"show {actor}"

    # setobjectxy
    m = re.match(r'^setobjectxy\((\w+),\s*(\w+),\s*(\w+)\)$', line)
    if m:
        actor = _resolve_actor_reverse(m.group(1), state)
        return f"setpos {actor} {m.group(2)} {m.group(3)}"

    # special (but not ShakeCamera — that's handled by multi-line)
    m = re.match(r'^special\((\w+)\)$', line)
    if m:
        return f"special {m.group(1)}"

    # goto
    m = re.match(r'^goto\((\w+)\)$', line)
    if m:
        return f"goto {m.group(1)}"

    # call
    m = re.match(r'^call\((\w+)\)$', line)
    if m:
        return f"call {m.group(1)}"

    # trainerbattle_* — native TorScript battle beat
    # TorScript script_model.py already parses trainerbattle_* as a battle beat,
    # and compiler.py passes them through to Poryscript.  Strip parens to match
    # the TorScript syntax: trainerbattle_single TRAINER_ID, IntroLabel, DefeatLabel
    m = re.match(r'^(trainerbattle_\w+)\((.+)\)$', line)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    if line.startswith("trainerbattle_"):
        return line  # already in TorScript form (no parens)

    # Follower commands
    m = re.match(r'^setfollowernpc\((\w+),\s*(\w+),\s*(\w+),\s*(\w+)\)$', line)
    if m:
        return f"follower add local {m.group(1)} {m.group(4)} {m.group(2)}"
    m = re.match(r'^createfollowernpc\((\w+),\s*(\w+),\s*(\w+),\s*(\w+)\)$', line)
    if m:
        return f"follower add dynamic {m.group(1)} {m.group(4)} {m.group(2)}"
    if line == "destroyfollowernpc":
        return "follower remove"
    if line == "facefollowernpc":
        return "follower face"
    m = re.match(r'^hidefollowernpc(?:\((\w+)\))?$', line)
    if m:
        if m.group(1):
            return f"follower hide {m.group(1)}"
        return "follower hide"
    if line == "checkfollowernpc":
        return "follower check"
    m = re.match(r'^changefollowerbattler\((\w+)\)$', line)
    if m:
        return f"follower change {m.group(1)}"

    # multi_* battle macros
    m = re.match(r'^multi_2_vs_2\((.+)\)$', line)
    if m:
        args = [a.strip() for a in m.group(1).split(',')]
        if len(args) == 5:
            return f"multi 2v2 {' '.join(args)}"
    m = re.match(r'^multi_2_vs_1\((.+)\)$', line)
    if m:
        args = [a.strip() for a in m.group(1).split(',')]
        if len(args) == 3:
            return f"multi 2v1 {' '.join(args)}"
    m = re.match(r'^multi_fixed_2_vs_2\((.+)\)$', line)
    if m:
        args = [a.strip() for a in m.group(1).split(',')]
        if len(args) == 5:
            return f"multi 2v2_fixed {' '.join(args)}"
    m = re.match(r'^multi_fixed_2_vs_1\((.+)\)$', line)
    if m:
        args = [a.strip() for a in m.group(1).split(',')]
        if len(args) == 3:
            return f"multi 2v1_fixed {' '.join(args)}"

    # ── New TorScript reversals ──────────────────────────────────

    # specialvar(VAR, Func) → special Func VAR (with optional @ comment)
    m = re.match(r'^specialvar\((\w+),\s*(\w+)(?:\s*@.*)?\)$', line)
    if m:
        return f"special {m.group(2)} {m.group(1)}"

    # message(Label) → message "text" if text block available, else message Label
    m = re.match(r'^message\((\w+)\)$', line)
    if m:
        label = m.group(1)
        text = state.text_blocks.get(label)
        if text:
            state.auto_text_labels.add(label)
            return f'message "{text.rstrip("$")}"'
        return f"message {label}"

    # copyvar(A, B) → var A = B
    m = re.match(r'^copyvar\((\w+),\s*(\w+)\)$', line)
    if m:
        return f"var {m.group(1)} = {m.group(2)}"

    # addvar(A, N) → var A + N
    m = re.match(r'^addvar\((\w+),\s*(\w+)\)$', line)
    if m:
        return f"var {m.group(1)} + {m.group(2)}"

    # subvar(A, N) → var A - N
    m = re.match(r'^subvar\((\w+),\s*(\w+)\)$', line)
    if m:
        return f"var {m.group(1)} - {m.group(2)}"

    # checkitem(ITEM) or checkitem(ITEM, COUNT) → check item ITEM
    m = re.match(r'^checkitem\((\w+)(?:,\s*\w+)?\)$', line)
    if m:
        return f"check item {m.group(1)}"

    # checkmoney(AMOUNT) → check money AMOUNT
    m = re.match(r'^checkmoney\((\w+)\)$', line)
    if m:
        return f"check money {m.group(1)}"

    # checkbadge(BADGE) → check badge BADGE
    m = re.match(r'^checkbadge\((\w+)\)$', line)
    if m:
        return f"check badge {m.group(1)}"

    # setwildbattle(SPECIES, LEVEL) → wildbattle SPECIES LEVEL
    m = re.match(r'^setwildbattle\((.+)\)$', line)
    if m:
        args = [a.strip() for a in m.group(1).split(',')]
        if len(args) >= 2:
            return f"wildbattle {' '.join(args)}"

    # removeitem(ITEM) or removeitem(ITEM, QTY) → take ITEM [QTY]
    m = re.match(r'^removeitem\((\w+)(?:,\s*(\w+))?\)$', line)
    if m:
        item = m.group(1)
        qty = m.group(2)
        if qty and qty != "1":
            return f"take {item} {qty}"
        return f"take {item}"

    # giveitem(ITEM) standalone (no compare/goto) → give ITEM
    m = re.match(r'^giveitem\((\w+)(?:,\s*(\w+))?\)$', line)
    if m:
        item = m.group(1)
        qty = m.group(2)
        if qty and qty != "1":
            return f"give {item} {qty}"
        return f"give {item}"

    # random(N) → random N
    m = re.match(r'^random\((\w+)\)$', line)
    if m:
        return f"random {m.group(1)}"

    # pokemart(LIST) → shop LIST
    m = re.match(r'^pokemart\((\w+)\)$', line)
    if m:
        return f"shop {m.group(1)}"

    # braillemsgbox(Label) → braille "text" if available, else braille Label
    m = re.match(r'^braillemsgbox\((\w+)\)$', line)
    if m:
        label = m.group(1)
        text = state.text_blocks.get(label)
        if text:
            state.auto_text_labels.add(label)
            return f'braille "{text.rstrip("$")}"'
        return f"braille {label}"

    # braillemessage(Label) → same treatment
    m = re.match(r'^braillemessage\((\w+)\)$', line)
    if m:
        label = m.group(1)
        text = state.text_blocks.get(label)
        if text:
            state.auto_text_labels.add(label)
            return f'braille "{text.rstrip("$")}"'
        return f"braille {label}"

    # showmonpic(SPECIES, X, Y) → showmon SPECIES
    m = re.match(r'^showmonpic\((\w+),\s*\w+,\s*\w+\)$', line)
    if m:
        return f"showmon {m.group(1)}"

    # showmoneybox(X, Y) → showmoney
    m = re.match(r'^showmoneybox\(\w+,\s*\w+\)$', line)
    if m:
        return "showmoney"

    # showcoinsbox(X, Y) → showcoins
    m = re.match(r'^showcoinsbox\(\w+,\s*\w+\)$', line)
    if m:
        return "showcoins"

    # opendoor(X, Y) → door open X Y
    m = re.match(r'^opendoor\((\w+),\s*(\w+)\)$', line)
    if m:
        return f"door open {m.group(1)} {m.group(2)}"

    # closedoor(X, Y) → door close X Y
    m = re.match(r'^closedoor\((\w+),\s*(\w+)\)$', line)
    if m:
        return f"door close {m.group(1)} {m.group(2)}"

    # setmetatile(X, Y, TILE, COLLISION) → tile X Y TILE COLLISION
    m = re.match(r'^setmetatile\((.+)\)$', line)
    if m:
        args = [a.strip() for a in m.group(1).split(',')]
        if len(args) >= 4:
            return f"tile {' '.join(args)}"

    # incrementgamestat(STAT) → stat STAT
    m = re.match(r'^incrementgamestat\((\w+)\)$', line)
    if m:
        return f"stat {m.group(1)}"

    # playslotmachine(VAR) → slots VAR
    m = re.match(r'^playslotmachine\((\w+)\)$', line)
    if m:
        return f"slots {m.group(1)}"

    # buffer commands → buffer N type ARG
    m = re.match(r'^bufferspeciesname\((\w+),\s*(\w+)\)$', line)
    if m:
        slot = m.group(1).replace("STR_VAR_", "")
        return f"buffer {slot} species {m.group(2)}"
    m = re.match(r'^bufferitemname\((\w+),\s*(\w+)\)$', line)
    if m:
        slot = m.group(1).replace("STR_VAR_", "")
        return f"buffer {slot} item {m.group(2)}"
    m = re.match(r'^buffermovename\((\w+),\s*(\w+)\)$', line)
    if m:
        slot = m.group(1).replace("STR_VAR_", "")
        return f"buffer {slot} move {m.group(2)}"
    m = re.match(r'^buffernumberstring\((\w+),\s*(\w+)\)$', line)
    if m:
        slot = m.group(1).replace("STR_VAR_", "")
        return f"buffer {slot} number {m.group(2)}"
    m = re.match(r'^bufferleadmonspeciesname\((\w+)\)$', line)
    if m:
        slot = m.group(1).replace("STR_VAR_", "")
        return f"buffer {slot} leadmon"
    m = re.match(r'^bufferstring\((\w+),\s*(\w+)\)$', line)
    if m:
        slot = m.group(1).replace("STR_VAR_", "")
        return f"buffer {slot} string {m.group(2)}"

    # hideobjectat(OBJ, MAP) → hide actor MAP
    m = re.match(r'^hideobjectat\((\w+),\s*(\w+)\)$', line)
    if m:
        actor = _resolve_actor_reverse(m.group(1), state)
        return f"hide {actor} {m.group(2)}"

    # showobjectat(OBJ, MAP) → show actor MAP
    m = re.match(r'^showobjectat\((\w+),\s*(\w+)\)$', line)
    if m:
        actor = _resolve_actor_reverse(m.group(1), state)
        return f"show {actor} {m.group(2)}"

    # copyobjectxytoperm(OBJ) → setpos actor perm
    m = re.match(r'^copyobjectxytoperm\((\w+)\)$', line)
    if m:
        actor = _resolve_actor_reverse(m.group(1), state)
        return f"setpos {actor} perm"

    # Standalone playfanfare(X) → fanfare X (without waitfanfare pair)
    m = re.match(r'^playfanfare\((\w+)\)$', line)
    if m:
        return f"fanfare {m.group(1)}"

    # pokemartdecoration(LIST) / pokemartdecoration2(LIST) → shop LIST decoration
    m = re.match(r'^pokemartdecoration2?\((\w+)\)$', line)
    if m:
        return f"shop {m.group(1)} decoration"

    # checkitemspace(ITEM) → check itemspace ITEM
    m = re.match(r'^checkitemspace\((\w+)\)$', line)
    if m:
        return f"check itemspace {m.group(1)}"

    # getplayerxy(VAR_X, VAR_Y) → getpos player VAR_X VAR_Y
    m = re.match(r'^getplayerxy\((\w+),\s*(\w+)\)$', line)
    if m:
        return f"getpos player {m.group(1)} {m.group(2)}"

    # showcontestpainting(WINNER_ID) → pory (niche, keep as-is)
    # givedecoration(DECOR) → pory (niche)
    # giveegg(SPECIES) → pory (niche)
    # seteventmon(SPECIES, LEVEL) → pory (niche)

    # goto_if_eq with parenthesized expressions (e.g. (NUM - 1))
    m = re.match(r'^goto_if_eq\((\w+),\s*(.+),\s*(\w+)\)$', line)
    if m:
        var = m.group(1)
        val = m.group(2).strip()
        label = m.group(3)
        return f"gotoif {var} == {val} {label}"

    # setvar/setflag with inline @ comment
    m = re.match(r'^setvar\((\w+),\s*(\w+)\s*@.*\)$', line)
    if m:
        return f"var {m.group(1)} {m.group(2)}"
    m = re.match(r'^setflag\((\w+)\s*@.*\)$', line)
    if m:
        return f"flag set {m.group(1)}"

    # fadeinbgm / fadeoutbgm → native
    m = re.match(r'^fadeoutbgm\((\w+)\)$', line)
    if m:
        return f"pory fadeoutbgm({m.group(1)})"
    m = re.match(r'^fadeinbgm\((\w+)\)$', line)
    if m:
        return f"pory fadeinbgm({m.group(1)})"

    # dofieldeffectsparkle(X, Y, Z) → pory (niche visual)
    m = re.match(r'^dofieldeffectsparkle\((.+)\)$', line)
    if m:
        return f"pory dofieldeffectsparkle({m.group(1)})"

    # Comments
    if line.startswith("//"):
        comment_text = line[2:].strip()
        return f"// {comment_text}"

    # Generic known-command handler (pory passthrough with actor resolution)
    m = re.match(r'^(\w+)\((.+)\)$', line)
    if m:
        cmd = m.group(1)
        if cmd in _KNOWN_PORY_COMMANDS:
            args = m.group(2)
            positions = _ACTOR_ARG_POSITIONS.get(cmd)
            resolved = _resolve_actors_in_args(args, state, positions)
            return f"pory {cmd}({resolved})"

    return None


# ============================================================
# PASS 2: DECOMPILE SCRIPT BODIES
# ============================================================

def _decompile_body(body, state):
    """Decompile a list of .pory body lines to TorScript lines."""
    result = []
    i = 0
    while i < len(body):
        line = body[i].strip()

        # Skip blank lines
        if not line:
            result.append("")
            i += 1
            continue

        # Try multi-line patterns first
        matched = False
        for handler in _MULTI_LINE_HANDLERS:
            ts, consumed = handler(body, i, state)
            if ts is not None:
                if isinstance(ts, list):
                    result.extend(ts)
                else:
                    result.append(ts)
                i += consumed
                matched = True
                break

        if matched:
            continue

        # Try single-line handlers
        ts = _handle_single_line(line, state)
        if ts is not None:
            result.append(ts)
        else:
            # Fallthrough — wrap as pory passthrough with actor resolution
            m_fb = re.match(r'^(\w+)\((.+)\)$', line)
            if m_fb:
                resolved = _resolve_actors_in_args(m_fb.group(2), state)
                result.append(f"pory {m_fb.group(1)}({resolved})")
            else:
                result.append(f"pory {line}")

        i += 1

    return result


# ============================================================
# PASS 3: CALL-SITE TRACKING
# ============================================================

def _track_call_sites(state):
    """Scan decompiled scripts for goto/call targets to enable annotations."""
    for caller_label, ts_lines in state.script_blocks_decompiled:
        for line in ts_lines:
            stripped = line.strip()
            # Match goto/call/gotoif targets
            for pattern in (
                r'^goto\s+(\w+)',
                r'^call\s+(\w+)',
                r'^gotoif\s+.+\s+(\w+)$',
            ):
                m = re.match(pattern, stripped)
                if m:
                    target = m.group(1)
                    if target not in state.call_targets:
                        state.call_targets[target] = []
                    state.call_targets[target].append(caller_label)


# ============================================================
# OUTPUT ASSEMBLY
# ============================================================

def _assemble_output(state):
    """Assemble final TorScript output from decompiled state."""
    parts = []

    # 1. Alias declarations (sorted by npc_id)
    alias_items = sorted(state.npc_ids.items(), key=lambda x: x[1])
    for const_name, npc_id in alias_items:
        alias = state.aliases[const_name]
        parts.append(f"alias {alias} npc{npc_id}")
    if alias_items:
        parts.append("")

    # 2. Mapscripts declarations
    for label in state.mapscripts_labels:
        parts.append(f"mapscripts {label}")
    if state.mapscripts_labels:
        parts.append("")

    # 3. Script blocks (suppressing auto-labels, annotating leaf scripts)
    for label, ts_lines in state.script_blocks_decompiled:
        if label in state.auto_labels:
            continue
        # Annotate leaf scripts (called from exactly one place, short body)
        callers = state.call_targets.get(label, [])
        annotation = ""
        if len(callers) == 1:
            # Extract a short caller name for readability
            caller = callers[0]
            # Strip common map prefix to keep annotation short
            short_caller = caller
            if state.map_name and caller.startswith(f"{state.map_name}_EventScript_"):
                short_caller = caller[len(f"{state.map_name}_EventScript_"):]
            elif caller.startswith(f"{state.map_name}_"):
                short_caller = caller[len(f"{state.map_name}_"):]
            body_lines = [l for l in ts_lines if l.strip()]
            if len(body_lines) <= 4:
                annotation = f"  // from {short_caller}"
        parts.append(f"script {label}{annotation}")
        for line in ts_lines:
            parts.append(line)
        parts.append("")

    # 4. Named text blocks (suppressing those consumed by trainerbattle inlining)
    emitted_text = False
    for label, content in state.text_blocks.items():
        if label in state.auto_text_labels:
            continue
        parts.append(f'text {label} "{content}"')
        emitted_text = True
    if emitted_text:
        parts.append("")

    # 5. Named movement blocks (suppressing auto-generated)
    for label, cmds in state.movement_blocks.items():
        if label in state.auto_move_labels:
            continue
        parts.append(f"movement {label}")
        for cmd in cmds:
            parts.append(cmd)
        parts.append("endmovement")
        parts.append("")

    # Remove trailing blank line
    while parts and parts[-1] == "":
        parts.pop()

    return "\n".join(parts)


# ============================================================
# PUBLIC API
# ============================================================

def decompile(pory_text, map_name=""):
    """Full .pory -> .txt TorScript. Returns (torscript_text, warnings)."""
    state = DecompilerState(map_name)

    # Pass 1: Parse structure
    _parse_pory_structure(pory_text, state)

    # Pass 2: Decompile each script body
    for label, body in state.script_blocks_raw:
        ts_lines = _decompile_body(body, state)
        state.script_blocks_decompiled.append((label, ts_lines))

    # Pass 3: Track call sites for annotation
    _track_call_sites(state)

    # Assemble output
    output = _assemble_output(state)
    return output, state.warnings


def decompile_block(pory_text, label, map_name=""):
    """Decompile a single script block (+ its text/movement deps) from a .pory file.

    Returns (torscript_text, warnings) or (None, ["label not found"]) if the label
    doesn't exist in the file.
    """
    state = DecompilerState(map_name)
    _parse_pory_structure(pory_text, state)

    # Filter to only the requested script label
    target = [(lbl, body) for lbl, body in state.script_blocks_raw if lbl == label]
    if not target:
        return None, [f"Script label '{label}' not found in source"]

    state.script_blocks_raw = target

    # Decompile the single block (text/movement blocks are still available for ref)
    for lbl, body in state.script_blocks_raw:
        ts_lines = _decompile_body(body, state)
        state.script_blocks_decompiled.append((lbl, ts_lines))

    output = _assemble_output(state)
    return output, state.warnings


def decompile_file(pory_path, map_name=""):
    """Read .pory file and decompile. Returns (torscript_text, warnings)."""
    with open(pory_path, "r") as f:
        pory_text = f.read()
    # Auto-detect map name from filename if not provided
    if not map_name:
        import os
        base = os.path.basename(pory_path)
        if base.endswith(".pory"):
            map_name = base[:-5]
    return decompile(pory_text, map_name)
