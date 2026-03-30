"""Pory-to-TorScript decompiler — converts .pory Poryscript back to .txt TorScript."""
# TORCH_MODULE: Script Decompiler
# TORCH_GROUP: Script Studio
import re

from torch.data import (
    BUILTIN_EMOTES, COMMON_EMOTES, COMMON_FACE,
    WALK_COMMANDS, JUMP_COMMANDS, JUMP2_COMMANDS,
)

# ============================================================
# REVERSE LOOKUP TABLES (auto-derived from data.py)
# ============================================================

_REV_COMMON_FACE = {v: k for k, v in COMMON_FACE.items()}
_REV_COMMON_EMOTES = {v: k for k, v in COMMON_EMOTES.items()}
_REV_BUILTIN_EMOTES = {v: k for k, v in BUILTIN_EMOTES.items()}

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


def _try_gotoif(body, i, state):
    """Match: if (flag(F)) { / goto(L) / }"""
    if i + 2 >= len(body):
        return None, 0
    l0 = body[i]
    m = re.match(r'^if\s*\(flag\((\w+)\)\)\s*\{$', l0)
    if not m:
        return None, 0
    l1 = body[i + 1].strip()
    m1 = re.match(r'^goto\((\w+)\)$', l1)
    if not m1:
        return None, 0
    l2 = body[i + 2].strip()
    if l2 != "}":
        return None, 0
    return f"gotoif {m.group(1)} {m1.group(1)}", 3


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


# Multi-line handlers in priority order
_MULTI_LINE_HANDLERS = [
    _try_shake,
    _try_give,
    _try_fanfare,
    _try_end,
    _try_release,
    _try_movement,
    _try_gotoif,
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
    if line == "waitmessage":
        return "pory waitmessage"
    if line == "waitbuttonpress":
        return "pory waitbuttonpress"

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

    # playmoncry
    m = re.match(r'^playmoncry\((\w+),\s*CRY_MODE_NORMAL\)$', line)
    if m:
        return f"cry {m.group(1)}"

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

    # Comments
    if line.startswith("//"):
        comment_text = line[2:].strip()
        return f"// {comment_text}"

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
            # Fallthrough — wrap as pory passthrough
            result.append(f"pory {line}")

        i += 1

    return result


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

    # 3. Script blocks (suppressing auto-labels)
    for label, ts_lines in state.script_blocks_decompiled:
        if label in state.auto_labels:
            continue
        parts.append(f"script {label}")
        for line in ts_lines:
            parts.append(line)
        parts.append("")

    # 4. Named text blocks
    for label, content in state.text_blocks.items():
        parts.append(f'text {label} "{content}"')
    if state.text_blocks:
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
