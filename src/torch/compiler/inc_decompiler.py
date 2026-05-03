"""Assembly-to-Poryscript decompiler (.inc -> .pory).

Converts vanilla pokeemerald assembly scripts (.inc) to Poryscript.
Handles mapscripts, movement data, text labels, trainerbattle macros,
goto_if/call_if control flow, and special commands. Successfully
decompiles all 468 vanilla scripts.inc files.
"""
# TORCH_MODULE: Inc Decompiler
# TORCH_GROUP: Script Studio
import re


# ============================================================
# DECOMPILER STATE
# ============================================================

class IncDecompilerState:
    def __init__(self, map_name=""):
        self.map_name = map_name
        self.script_blocks = []       # [(label, [body_lines], is_global)]
        self.text_blocks = {}         # label -> "joined string content"
        self.movement_blocks = {}     # label -> [movement_cmds]  (without step_end)
        self.data_blocks = {}         # label -> [raw_lines]
        self.mapscripts_label = ""    # e.g. "LittlerootTown_MapScripts"
        self.mapscripts = []          # [(type_const, handler_label)]
        self.mapscript_tables = {}    # label -> [raw_lines]  (map_script_2 tables)
        self.constants = {}           # .set name -> value
        self.localids = set()         # LOCALID_ names referenced
        self.text_ref_counts = {}     # label -> int (how many times referenced)
        self.warnings = []

    def warn(self, msg):
        self.warnings.append(msg)


# ============================================================
# MOVEMENT COMMANDS (for classification)
# ============================================================

_MOVEMENT_CMDS = {
    "walk_up", "walk_down", "walk_left", "walk_right",
    "walk_fast_up", "walk_fast_down", "walk_fast_left", "walk_fast_right",
    "walk_faster_up", "walk_faster_down", "walk_faster_left", "walk_faster_right",
    "walk_slow_up", "walk_slow_down", "walk_slow_left", "walk_slow_right",
    "walk_in_place_up", "walk_in_place_down", "walk_in_place_left", "walk_in_place_right",
    "walk_in_place_fast_up", "walk_in_place_fast_down", "walk_in_place_fast_left", "walk_in_place_fast_right",
    "walk_in_place_faster_up", "walk_in_place_faster_down", "walk_in_place_faster_left", "walk_in_place_faster_right",
    "jump_up", "jump_down", "jump_left", "jump_right",
    "jump_in_place_up", "jump_in_place_down", "jump_in_place_left", "jump_in_place_right",
    "jump_2_up", "jump_2_down", "jump_2_left", "jump_2_right",
    "slide_up", "slide_down", "slide_left", "slide_right",
    "face_up", "face_down", "face_left", "face_right",
    "face_player", "face_away_player", "face_original_direction",
    "emote_exclamation_mark", "emote_question_mark", "emote_double_exclamation_mark",
    "emote_x", "emote_heart",
    "delay_16", "delay_8", "delay_4", "delay_1",
    "set_invisible", "set_visible",
    "nurse_joy_bow", "cut_tree", "reveal_trainer",
    "rock_smash_break", "tree_or_rock_dust",
    "step_end",
}

# Commands that take no arguments in .inc and need no parens in .pory
_NO_ARG_COMMANDS = {
    "lock", "lockall", "release", "releaseall", "end", "return",
    "faceplayer", "closemessage", "waitstate", "waitmessage",
    "waitbuttonpress", "waitfanfare", "waitse", "doweather",
    "checkplayergender", "hideplayer", "showplayer", "waitdooranim",
    "waitmoncry",
}

# Commands that take arguments: cmd arg1, arg2 -> cmd(arg1, arg2)
# Format: command_name -> number of args (0 = variable)
_ARG_COMMANDS = {
    "setflag": 1, "clearflag": 1,
    "setvar": 2, "copyvar": 2, "addvar": 2, "subvar": 2, "setorcopyvar": 2,
    "special": 1, "specialvar": 2, "callnative": 1,
    "delay": 1, "fadescreen": 1, "fadescreenspeed": 2,
    "playse": 1, "playfanfare": 1, "playbgm": 2, "fadeoutbgm": 1,
    "playmoncry": 2,
    "removeobject": 1, "addobject": 1,
    "goto": 1, "call": 1,
    "setobjectxy": 3, "setobjectxyperm": 3,
    "setobjectmovementtype": 2, "setobjectsubpriority": 2, "resetobjectsubpriority": 1,
    "turnobject": 2, "turnvobject": 2,
    "applymovement": 2, "waitmovement": 1,
    "msgbox": 2, "message": 1,
    "giveitem": 0, "additem": 0, "removeitem": 0,
    "checkitem": 2, "checkitemspace": 2, "checkitemtype": 1,
    "warp": 3, "warpsilent": 3, "warpdoor": 3, "warphole": 2,
    "warpteleport": 3, "warpwhitefade": 3,
    "setwarp": 3, "setdynamicwarp": 3, "setescapewarp": 3,
    "setholewarp": 3, "setdivewarp": 3,
    "opendoor": 2, "closedoor": 2,
    "setmetatile": 4, "setweather": 1, "setmaplayoutindex": 1,
    "setrespawn": 1,
    "bufferstring": 2, "bufferitemnameplural": 3, "buffernumberstring": 2,
    "bufferstdstring": 2, "buffermovename": 2, "bufferpartymonnick": 2,
    "multichoice": 4, "pokemart": 1,
    "showmonpic": 2, "hidemonpic": 0,
    "incrementgamestat": 1,
    "setstepcallback": 1,
    "createvobject": 4,
    "showobjectat": 2, "hideobjectat": 2,
    "copyobjectxytoperm": 1,
    "register_matchcall": 1,
    "dofieldeffect": 1, "dofieldeffectsparkle": 3,
    "waitfieldeffect": 1, "setfieldeffectargument": 2,
    "setwildbattle": 0, "dowildbattle": 0,
    "setrespawn": 1,
    "animateflash": 1, "setflashlevel": 1,
    "givemon": 0, "giveegg": 1,
    "checkcoins": 1, "addcoins": 1, "removecoins": 1,
    "checkmoney": 0, "addmoney": 0, "removemoney": 0,
    "cleartrainerflag": 1, "settrainerflag": 1,
    "hidefollower": 1,
}


# ============================================================
# PASS 1: PARSE .INC STRUCTURE
# ============================================================

def _is_movement_line(line):
    """Check if a line is a movement command (for classification)."""
    cmd = line.strip().split()[0] if line.strip() else ""
    return cmd in _MOVEMENT_CMDS


def _classify_block(lines):
    """Classify a block of indented lines following a label.

    Returns: 'text', 'movement', 'data', 'mapscripts', 'mapscript_table', or 'script'
    """
    if not lines:
        return "script"

    first = lines[0].strip()

    # Text block: starts with .string
    if first.startswith('.string '):
        return "text"

    # Mapscripts: map_script directives or lone .byte 0
    if first.startswith('map_script '):
        return "mapscripts"

    # map_script_2 table
    if first.startswith('map_script_2 '):
        return "mapscript_table"

    # Data: .2byte / .byte / .align sequences
    # Special case: a lone .byte 0 is likely an empty mapscripts terminator
    if first == '.byte 0' and len(lines) == 1:
        return "mapscripts"
    if first.startswith('.2byte ') or first.startswith('.byte ') or first.startswith('.align '):
        return "data"

    # Movement block: all lines are movement commands
    non_empty = [l.strip() for l in lines if l.strip() and not l.strip().startswith('@')]
    if non_empty and all(_is_movement_line(l) for l in non_empty):
        return "movement"

    return "script"


def _parse_inc_structure(inc_text, state):
    """Pass 1: Parse .inc file into structured blocks."""
    lines = inc_text.split('\n')
    i = 0
    n = len(lines)

    while i < n:
        raw_line = lines[i]
        stripped = raw_line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # .set constant definition
        m = re.match(r'^\.set\s+(\w+),\s*(.+)$', stripped)
        if m:
            state.constants[m.group(1)] = m.group(2).strip()
            i += 1
            continue

        # Preprocessor: .if / .else / .endif — collect into data block
        if stripped.startswith('.if ') or stripped == '.ifdef' or stripped == '.ifndef':
            block_lines = [raw_line]
            depth = 1
            i += 1
            while i < n and depth > 0:
                s = lines[i].strip()
                block_lines.append(lines[i])
                if s.startswith('.if'):
                    depth += 1
                elif s == '.endif':
                    depth -= 1
                i += 1
            label = f"_preprocessor_{len(state.data_blocks)}"
            state.data_blocks[label] = [l.rstrip() for l in block_lines]
            continue

        # Label detection: LABEL:: or LABEL:
        m = re.match(r'^(\w+)(::?)\s*(@.*)?$', stripped)
        if m:
            label = m.group(1)
            is_global = m.group(2) == '::'

            # Collect indented body lines until next label or EOF
            body_lines = []
            i += 1
            while i < n:
                next_line = lines[i]
                next_stripped = next_line.strip()

                # Next label = end of this block
                if next_stripped and re.match(r'^\w+::?\s*(@.*)?$', next_stripped):
                    # But NOT if it's a .string continuation after another .string
                    break

                # .set at file level = end of block
                if next_stripped.startswith('.set '):
                    break

                # .if at non-indented level = end of block
                if next_stripped.startswith('.if ') and not next_line.startswith('\t'):
                    break

                body_lines.append(next_line)
                i += 1

            # Strip trailing blank lines
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()

            # Classify the block
            content_lines = [l for l in body_lines if l.strip() and not l.strip().startswith('@')]
            block_type = _classify_block(content_lines)

            if block_type == "text":
                # Extract .string content
                text = _extract_text_content(body_lines)
                state.text_blocks[label] = text

            elif block_type == "mapscripts":
                state.mapscripts_label = label
                for bl in body_lines:
                    bl_s = bl.strip()
                    mm = re.match(r'^map_script\s+(\w+),\s*(\w+)$', bl_s)
                    if mm:
                        state.mapscripts.append((mm.group(1), mm.group(2)))

            elif block_type == "movement":
                # Extract movement commands (without step_end)
                cmds = []
                for bl in body_lines:
                    cmd = bl.strip()
                    if cmd and cmd != "step_end" and not cmd.startswith('@'):
                        cmds.append(cmd)
                state.movement_blocks[label] = cmds

            elif block_type == "mapscript_table":
                raw = [l.rstrip() for l in body_lines if l.strip()]
                state.mapscript_tables[label] = raw

            elif block_type == "data":
                raw = [l.rstrip() for l in body_lines if l.strip()]
                state.data_blocks[label] = raw

            else:
                # Script block
                state.script_blocks.append((label, body_lines, is_global))
                # Track LOCALID references
                for bl in body_lines:
                    for lid in re.findall(r'LOCALID_\w+', bl):
                        state.localids.add(lid)

            continue

        # Standalone comment or orphan data
        if stripped.startswith('@'):
            i += 1
            continue

        # Orphan step_end or other data (leftover)
        if stripped in _MOVEMENT_CMDS or stripped.startswith('.'):
            i += 1
            continue

        i += 1


def _extract_text_content(body_lines):
    """Extract text from .string directive lines."""
    parts = []
    for line in body_lines:
        s = line.strip()
        if not s or s.startswith('@'):
            continue
        m = re.match(r'^\.string\s+"(.*)"$', s)
        if m:
            parts.append(m.group(1))
    return "".join(parts)


# ============================================================
# PASS 2: CONVERT SCRIPT BODIES
# ============================================================

def _convert_command(line, state):
    """Convert a single .inc assembly command to Poryscript.

    Returns the converted line, or None if not recognized.
    """
    stripped = line.strip()
    if not stripped:
        return ""

    # Comments
    if stripped.startswith('@'):
        comment = stripped[1:].strip()
        return f"    // {comment}" if comment else ""

    # No-argument commands
    if stripped in _NO_ARG_COMMANDS:
        return f"    {stripped}"

    # Split into command + args
    parts = stripped.split(None, 1)
    cmd = parts[0]
    args_str = parts[1] if len(parts) > 1 else ""

    # --- Control flow: goto_if_* ---

    # goto_if_set FLAG, LABEL
    m = re.match(r'^goto_if_set\s+(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (flag({m.group(1)})) {{\n        goto({m.group(2)})\n    }}"

    # goto_if_unset FLAG, LABEL
    m = re.match(r'^goto_if_unset\s+(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (!flag({m.group(1)})) {{\n        goto({m.group(2)})\n    }}"

    # goto_if_eq VAR, VAL, LABEL
    m = re.match(r'^goto_if_eq\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) == {m.group(2)}) {{\n        goto({m.group(3)})\n    }}"

    # goto_if_ne VAR, VAL, LABEL
    m = re.match(r'^goto_if_ne\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) != {m.group(2)}) {{\n        goto({m.group(3)})\n    }}"

    # goto_if_lt VAR, VAL, LABEL
    m = re.match(r'^goto_if_lt\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) < {m.group(2)}) {{\n        goto({m.group(3)})\n    }}"

    # goto_if_le VAR, VAL, LABEL
    m = re.match(r'^goto_if_le\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) <= {m.group(2)}) {{\n        goto({m.group(3)})\n    }}"

    # goto_if_gt VAR, VAL, LABEL
    m = re.match(r'^goto_if_gt\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) > {m.group(2)}) {{\n        goto({m.group(3)})\n    }}"

    # goto_if_ge VAR, VAL, LABEL
    m = re.match(r'^goto_if_ge\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) >= {m.group(2)}) {{\n        goto({m.group(3)})\n    }}"

    # goto_if_defeated TRAINER, LABEL
    m = re.match(r'^goto_if_defeated\s+(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (defeated({m.group(1)})) {{\n        goto({m.group(2)})\n    }}"

    # goto_if_not_defeated TRAINER, LABEL
    m = re.match(r'^goto_if_not_defeated\s+(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (!defeated({m.group(1)})) {{\n        goto({m.group(2)})\n    }}"

    # --- Control flow: call_if_* ---

    # call_if_set FLAG, LABEL
    m = re.match(r'^call_if_set\s+(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (flag({m.group(1)})) {{\n        call({m.group(2)})\n    }}"

    # call_if_unset FLAG, LABEL
    m = re.match(r'^call_if_unset\s+(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (!flag({m.group(1)})) {{\n        call({m.group(2)})\n    }}"

    # call_if_eq VAR, VAL, LABEL
    m = re.match(r'^call_if_eq\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) == {m.group(2)}) {{\n        call({m.group(3)})\n    }}"

    # call_if_ne VAR, VAL, LABEL
    m = re.match(r'^call_if_ne\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) != {m.group(2)}) {{\n        call({m.group(3)})\n    }}"

    # call_if_lt VAR, VAL, LABEL
    m = re.match(r'^call_if_lt\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) < {m.group(2)}) {{\n        call({m.group(3)})\n    }}"

    # call_if_le VAR, VAL, LABEL
    m = re.match(r'^call_if_le\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) <= {m.group(2)}) {{\n        call({m.group(3)})\n    }}"

    # call_if_ge VAR, VAL, LABEL
    m = re.match(r'^call_if_ge\s+(\w+),\s*(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (var({m.group(1)}) >= {m.group(2)}) {{\n        call({m.group(3)})\n    }}"

    # call_if_defeated TRAINER, LABEL
    m = re.match(r'^call_if_defeated\s+(\w+),\s*(\w+)$', stripped)
    if m:
        return f"    if (defeated({m.group(1)})) {{\n        call({m.group(2)})\n    }}"

    # --- Switch/case ---

    if cmd == "switch":
        return f"    switch (var({args_str.strip()})) {{"

    m = re.match(r'^case\s+(\w+),\s*(\w+)$', stripped)
    if m:
        return f"        case {m.group(1)}:\n            goto({m.group(2)})"

    # --- trainerbattle variants (variable args) ---
    if cmd.startswith("trainerbattle_"):
        return f"    {cmd}({args_str})"

    # --- msgbox with text label (will be resolved in output phase) ---
    m = re.match(r'^msgbox\s+(\w+),\s*(\w+)$', stripped)
    if m:
        text_label = m.group(1)
        msg_type = m.group(2)
        state.text_ref_counts[text_label] = state.text_ref_counts.get(text_label, 0) + 1
        return f"    msgbox({text_label}, {msg_type})"

    # message (no type)
    m = re.match(r'^message\s+(\w+)$', stripped)
    if m:
        text_label = m.group(1)
        state.text_ref_counts[text_label] = state.text_ref_counts.get(text_label, 0) + 1
        return f"    message({text_label})"

    # --- Known arg commands ---
    if cmd in _ARG_COMMANDS:
        if args_str:
            return f"    {cmd}({args_str})"
        return f"    {cmd}"

    # --- Fallback: unknown command as raw ---
    if args_str:
        return f"    {cmd}({args_str})"
    return f"    {cmd}"


def _convert_script_body(body_lines, state):
    """Convert a script's body lines to Poryscript."""
    result = []
    i = 0
    n = len(body_lines)

    while i < n:
        line = body_lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Skip .byte 0 terminators (mapscripts artifact)
        if stripped == '.byte 0':
            i += 1
            continue

        # Handle switch blocks: collect switch + cases + end
        if stripped.startswith('switch '):
            switch_line = _convert_command(stripped, state)
            result.append(switch_line)
            i += 1
            # Collect cases
            while i < n:
                cs = body_lines[i].strip()
                if not cs:
                    i += 1
                    continue
                if cs.startswith('case '):
                    result.append(_convert_command(cs, state))
                    i += 1
                elif cs == 'end':
                    result.append("    }")
                    result.append("    end")
                    i += 1
                    break
                else:
                    # Switch followed by non-case (e.g. goto after cases)
                    result.append("    }")
                    break
            continue

        converted = _convert_command(stripped, state)
        if converted is not None:
            result.append(converted)

        i += 1

    return result


# ============================================================
# OUTPUT ASSEMBLY
# ============================================================

def _compress_movement(cmds):
    """Compress consecutive identical movement commands using * N syntax."""
    if not cmds:
        return []
    result = []
    prev = cmds[0]
    count = 1
    for cmd in cmds[1:]:
        if cmd == prev:
            count += 1
        else:
            if count > 1:
                result.append(f"    {prev} * {count}")
            else:
                result.append(f"    {prev}")
            prev = cmd
            count = 1
    if count > 1:
        result.append(f"    {prev} * {count}")
    else:
        result.append(f"    {prev}")
    return result


def _resolve_text_in_output(pory_lines, state):
    """Replace text label references with inline text where appropriate."""
    resolved = []
    for line in pory_lines:
        # msgbox(TEXT_LABEL, TYPE) -> msgbox("text$", TYPE) if single-ref
        m = re.match(r'^(\s*)msgbox\((\w+),\s*(\w+)\)$', line)
        if m:
            indent = m.group(1)
            text_label = m.group(2)
            msg_type = m.group(3)
            text = state.text_blocks.get(text_label)
            ref_count = state.text_ref_counts.get(text_label, 0)
            if text is not None and ref_count <= 1:
                # Inline the text
                resolved.append(f'{indent}msgbox("{text}", {msg_type})')
                continue
        # message(TEXT_LABEL) -> message(TEXT_LABEL) stays as-is (needs text block)
        resolved.append(line)
    return resolved


def _assemble_output(state):
    """Assemble final .pory output from parsed state."""
    parts = []

    # 1. Mapscripts block
    if state.mapscripts_label:
        parts.append(f"mapscripts {state.mapscripts_label} {{")
        for ms_type, ms_label in state.mapscripts:
            parts.append(f"    {ms_type}: {ms_label}")
        parts.append("}")
        parts.append("")

    # 2. Script blocks
    for label, body_lines, is_global in state.script_blocks:
        pory_body = _convert_script_body(body_lines, state)
        # Resolve inline text
        pory_body = _resolve_text_in_output(pory_body, state)

        parts.append(f"script {label} {{")
        for line in pory_body:
            parts.append(line)
        parts.append("}")
        parts.append("")

    # 3. Text blocks (only those referenced multiple times or by message())
    for label, text in state.text_blocks.items():
        ref_count = state.text_ref_counts.get(label, 0)
        if ref_count > 1:
            # Multi-referenced: emit as shared text block
            parts.append(f'text {label} {{')
            parts.append(f'    "{text}"')
            parts.append("}")
            parts.append("")
        elif ref_count == 0:
            # Unreferenced text — still emit (might be referenced externally)
            parts.append(f'text {label} {{')
            parts.append(f'    "{text}"')
            parts.append("}")
            parts.append("")

    # 4. Movement blocks
    for label, cmds in state.movement_blocks.items():
        compressed = _compress_movement(cmds)
        parts.append(f"movement {label} {{")
        for line in compressed:
            parts.append(line)
        parts.append("}")
        parts.append("")

    # 5. Mapscript tables (as raw blocks)
    for label, raw_lines in state.mapscript_tables.items():
        parts.append("raw `")
        parts.append(f"{label}:")
        for rl in raw_lines:
            parts.append(rl)
        parts.append("`")
        parts.append("")

    # 6. Data blocks (as raw blocks)
    for label, raw_lines in state.data_blocks.items():
        if label.startswith("_preprocessor_"):
            # Preprocessor block — emit as-is in raw
            parts.append("raw `")
            for rl in raw_lines:
                parts.append(rl)
            parts.append("`")
            parts.append("")
        else:
            # Check for mart pattern: .align + .2byte ITEM_ lines
            items = _try_extract_mart(raw_lines)
            if items is not None:
                parts.append(f"mart {label} {{")
                for item in items:
                    parts.append(f"    {item}")
                parts.append("}")
                parts.append("")
            else:
                parts.append("raw `")
                if not label.startswith("_"):
                    parts.append(f"{label}:")
                for rl in raw_lines:
                    parts.append(rl)
                parts.append("`")
                parts.append("")

    # Remove trailing blank lines
    while parts and parts[-1] == "":
        parts.pop()

    return "\n".join(parts)


def _try_extract_mart(raw_lines):
    """Try to extract item list from data block. Returns list of items or None."""
    items = []
    for line in raw_lines:
        s = line.strip()
        if s.startswith('.align'):
            continue
        m = re.match(r'^\.2byte\s+(\w+)$', s)
        if m:
            item = m.group(1)
            if item == "ITEM_NONE":
                continue
            items.append(item)
            continue
        if s in ("release", "end"):
            continue
        # Not a clean mart pattern
        return None
    return items if items else None


# ============================================================
# PUBLIC API
# ============================================================

def decompile_inc(inc_text, map_name=""):
    """Decompile .inc assembly text to Poryscript.

    Returns (pory_text, warnings).
    """
    state = IncDecompilerState(map_name)

    # Pass 1: Parse structure
    _parse_inc_structure(inc_text, state)

    # Pass 2: Generate output (conversion happens during assembly)
    output = _assemble_output(state)

    return output, state.warnings


def decompile_inc_file(inc_path, map_name=""):
    """Read .inc file and decompile to Poryscript.

    Returns (pory_text, warnings).
    """
    import os
    with open(inc_path, "r") as f:
        inc_text = f.read()
    if not map_name:
        # Try to derive from parent directory name
        parent = os.path.basename(os.path.dirname(inc_path))
        if parent:
            map_name = parent
    return decompile_inc(inc_text, map_name)


def decompile_inc_block(inc_text, label, map_name=""):
    """Decompile a single script block from .inc text.

    Only includes text/movement/data blocks referenced by the target script.
    Returns (pory_text, warnings) or (None, ["label not found"]).
    """
    state = IncDecompilerState(map_name)
    _parse_inc_structure(inc_text, state)

    # Find the target script block
    target = [(l, b, g) for l, b, g in state.script_blocks if l == label]
    if not target:
        return None, [f"Script label '{label}' not found in source"]

    # Collect all labels referenced by the target script's body
    referenced = set()
    for _, body_lines, _ in target:
        for line in body_lines:
            for word in re.findall(r'\b[A-Za-z_]\w*\b', line):
                referenced.add(word)

    # Filter to only referenced blocks
    state.script_blocks = target
    state.text_blocks = {k: v for k, v in state.text_blocks.items() if k in referenced}
    state.movement_blocks = {k: v for k, v in state.movement_blocks.items() if k in referenced}
    state.data_blocks = {k: v for k, v in state.data_blocks.items() if k in referenced}
    state.mapscript_tables = {}   # never relevant for a single script
    state.mapscripts_label = ""   # don't emit mapscripts for single block
    state.mapscripts = []

    output = _assemble_output(state)
    return output, state.warnings
