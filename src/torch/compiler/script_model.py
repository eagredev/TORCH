"""Script data model - beat types, parser, serializer, and help system.

Defines the beat abstraction (dialogue, movement, emote, flag, give,
camera, etc.) that both the TUI script editor and web script editor
operate on. Parses .txt workspace files into beat lists and serializes
them back. Also provides the inline help/reference system.
"""
# TORCH_MODULE: Script Model
# TORCH_GROUP: Script Studio
import os
import re

from torch.data import WALK_COMMANDS, WALKTO_COMMANDS
from torch.ui import clear_screen

# ============================================================
# SCRIPT EDITOR — DATA MODEL & PARSER
# ============================================================

# Beat type tags used in the editor display
BEAT_TAGS = {
    "label": "LBL", "dialogue": "DLG", "move": "MOV", "emote": "EMO",
    "fade": "FAD", "sound": "SND", "pause": "PAU", "flag": "FLG",
    "battle": "BTL", "hide": "HID", "show": "SHW", "setpos": "POS",
    "flow": "FLW", "pory": "POR", "comment": "REM", "lock": "LCK",
    "faceplayer": "FPL", "special": "SPC", "waitstate": "WAI",
    "gotoif": "GIF", "var": "VAR", "shake": "SHK", "closemessage": "CLM",
    "music": "MUS", "fanfare": "FAN", "cry": "CRY", "text": "TXT",
    "movement": "BLK", "raw": "RAW", "follower": "FOL", "multi": "MLT",
    "give": "GIV", "page": "PAG", "condition": "CND", "endif": "END",
    "switch": "SWC", "case": "CAS", "endswitch": "ESW",
    "choice": "CHC", "option": "OPT", "endchoice": "ECH",
    "check": "CHK",
    # Wait/sync commands
    "waitmessage": "WMS", "waitbutton": "WBT", "waitse": "WSE",
    "waitmoncry": "WCR", "waitfanfare": "WFN",
    # Extended commands
    "message": "MSG", "wildbattle": "WLD", "take": "TAK",
    "random": "RND", "shop": "SHP", "braille": "BRL",
    "showmon": "SMN", "hidemon": "HMN",
    "showmoney": "MON", "showcoins": "COI",
    "buffer": "BUF", "tile": "TIL", "door": "DOR",
    "stat": "STA", "slots": "SLT", "getpos": "GPO",
}

from torch.colours import GOLD, WHITE, CYAN, GREEN, RED, BLUE, DIM, RST, BOLD_RED, DGOLD
_TAG_COLOURS = {
    # Dialogue / text (cyan)
    "DLG": CYAN, "TXT": CYAN, "CLM": CYAN,
    # Movement / position (green)
    "MOV": GREEN, "POS": GREEN, "FPL": GREEN,
    # Movement blocks (bold green — distinct from regular MOV)
    "BLK": "\033[1;32m",
    # Emotion / effects (yellow)
    "EMO": DGOLD, "SHK": DGOLD, "CRY": DGOLD, "FAN": DGOLD,
    # Flow / logic (magenta)
    "FLW": "\033[35m", "GIF": "\033[35m", "FLG": "\033[35m", "VAR": "\033[35m", "GIV": "\033[35m",
    "CND": "\033[35m", "END": "\033[35m",
    "SWC": "\033[35m", "CAS": "\033[35m", "ESW": "\033[35m",
    "CHC": "\033[35m", "OPT": "\033[35m", "ECH": "\033[35m",
    "CHK": "\033[35m",
    # Battle (red bold)
    "BTL": BOLD_RED,
    # Scene / atmosphere (blue)
    "FAD": BLUE, "SND": BLUE, "MUS": BLUE, "PAU": BLUE,
    "HID": BLUE, "SHW": BLUE,
    # Structure (bold white)
    "LBL": WHITE, "LCK": WHITE, "SPC": WHITE, "WAI": WHITE, "PAG": WHITE,
    # Meta (dim)
    "REM": DIM, "POR": DIM, "RAW": DIM,
    # Follower NPC (cyan — movement-adjacent)
    "FOL": CYAN,
    # Multi battle (bold red — battle-adjacent)
    "MLT": BOLD_RED,
}


def _coloured_tag(tag):
    """Wrap a beat tag like [DLG] with ANSI colour, plus trailing spacing."""
    colour = _TAG_COLOURS.get(tag, "")
    if colour:
        return f"{colour}[{tag}]{RST}  "
    return f"[{tag}]  "


# ============================================================
# PARSE HELPERS — extracted from _parse_script
# ============================================================

def _parse_continuation_lines(lines, start_idx):
    """Consume continuation lines (quoted strings) after a msg/text command.

    Returns (collected_text, new_index) where new_index is the first
    non-continuation line.
    """
    idx = start_idx
    parts = []
    while idx < len(lines):
        next_line = lines[idx].strip()
        if next_line.startswith('"') and next_line.endswith('"'):
            parts.append(next_line[1:-1])
            idx += 1
        else:
            break
    return "".join(parts), idx


def _parse_beat_msg(tokens, stripped, lines, i, cast):
    """Parse msg / msgnpc command."""
    cmd = tokens[0]
    style = "msgnpc" if cmd == "msgnpc" else "msg"
    m2 = re.match(rf'^{cmd}\s+"(.*)"$', stripped)
    if m2:
        text_parts = [m2.group(1)]
        continuation, idx = _parse_continuation_lines(lines, i + 1)
        if continuation:
            text_parts.append(continuation)
        full_text = "".join(text_parts)
        if full_text.endswith("$"):
            full_text = full_text[:-1]
        beat = {"type": "dialogue", "data": {"text": full_text, "style": style}}
        return beat, idx
    return {"type": "pory", "data": {"raw_line": stripped}}, i + 1


def _parse_beat_text(tokens, stripped, lines, i, cast):
    """Parse text (named text block) command."""
    m2 = re.match(r'^text\s+(\S+)\s+"(.*)"$', stripped)
    if m2:
        text_label = m2.group(1)
        text_content = m2.group(2)
        continuation, idx = _parse_continuation_lines(lines, i + 1)
        if continuation:
            text_content += continuation
        beat = {"type": "text", "data": {"label": text_label, "content": text_content}}
        return beat, idx
    return {"type": "pory", "data": {"raw_line": stripped}}, i + 1


def _parse_beat_movement(tokens, stripped, lines, i, cast):
    """Parse movement (named movement block) command."""
    move_label = tokens[1] if len(tokens) >= 2 else ""
    move_cmds = []
    brace_match = re.match(r'^movement\s+\S+\s*\{(.+)\}$', stripped)
    if brace_match:
        inner = brace_match.group(1).strip()
        move_cmds = [c.strip() for c in inner.split(",")]
        beat = {"type": "movement", "data": {"label": move_label, "commands": move_cmds}}
        return beat, i + 1
    idx = i + 1
    while idx < len(lines):
        mline = lines[idx].strip()
        if mline == "endmovement":
            idx += 1
            break
        if mline and not mline.startswith("#"):
            move_cmds.append(mline)
        idx += 1
    beat = {"type": "movement", "data": {"label": move_label, "commands": move_cmds}}
    return beat, idx


def _parse_beat_lock(tokens, stripped, lines, i, cast):
    return {"type": "lock", "data": {}}, i + 1


def _parse_beat_end(tokens, stripped, lines, i, cast):
    return {"type": "flow", "data": {"flow_type": "end"}}, i + 1


def _parse_beat_release(tokens, stripped, lines, i, cast):
    return {"type": "flow", "data": {"flow_type": "release"}}, i + 1


def _parse_beat_closemessage(tokens, stripped, lines, i, cast):
    return {"type": "closemessage", "data": {}}, i + 1


def _parse_beat_goto(tokens, stripped, lines, i, cast):
    target = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "flow", "data": {"flow_type": "goto", "target": target}}, i + 1


def _parse_beat_call(tokens, stripped, lines, i, cast):
    target = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "flow", "data": {"flow_type": "call", "target": target}}, i + 1


def _parse_beat_return(tokens, stripped, lines, i, cast):
    return {"type": "flow", "data": {"flow_type": "return"}}, i + 1


def _parse_beat_fade(tokens, stripped, lines, i, cast):
    fade_type = " ".join(tokens[1:])
    return {"type": "fade", "data": {"fade_type": fade_type}}, i + 1


def _parse_beat_sound(tokens, stripped, lines, i, cast):
    constant = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "sound", "data": {"constant": constant}}, i + 1


def _parse_beat_music(tokens, stripped, lines, i, cast):
    constant = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "music", "data": {"constant": constant}}, i + 1


def _parse_beat_fanfare(tokens, stripped, lines, i, cast):
    constant = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "fanfare", "data": {"constant": constant}}, i + 1


def _parse_beat_cry(tokens, stripped, lines, i, cast):
    species = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "cry", "data": {"species": species}}, i + 1


def _parse_beat_pause(tokens, stripped, lines, i, cast):
    duration = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "pause", "data": {"duration": duration}}, i + 1


def _parse_beat_flag(tokens, stripped, lines, i, cast):
    action = tokens[1] if len(tokens) >= 2 else ""
    flag_name = tokens[2] if len(tokens) >= 3 else ""
    return {"type": "flag", "data": {"action": action, "flag_name": flag_name}}, i + 1


def _parse_beat_var(tokens, stripped, lines, i, cast):
    var_name = tokens[1] if len(tokens) >= 2 else ""
    op_or_val = tokens[2] if len(tokens) >= 3 else ""
    if op_or_val in ('=', '+', '-') and len(tokens) >= 4:
        return {"type": "var", "data": {"var_name": var_name, "op": op_or_val, "value": tokens[3]}}, i + 1
    return {"type": "var", "data": {"var_name": var_name, "value": op_or_val}}, i + 1


def _parse_beat_hide(tokens, stripped, lines, i, cast):
    actor = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "hide", "data": {"actor": actor}}, i + 1


def _parse_beat_show(tokens, stripped, lines, i, cast):
    actor = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "show", "data": {"actor": actor}}, i + 1


def _parse_beat_faint(tokens, stripped, lines, i, cast):
    actor = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "faint", "data": {"actor": actor}}, i + 1


def _parse_beat_revive(tokens, stripped, lines, i, cast):
    actor = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "revive", "data": {"actor": actor}}, i + 1


def _parse_beat_setpos(tokens, stripped, lines, i, cast):
    actor = tokens[1] if len(tokens) >= 2 else ""
    x = tokens[2] if len(tokens) >= 3 else ""
    y = tokens[3] if len(tokens) >= 4 else ""
    return {"type": "setpos", "data": {"actor": actor, "x": x, "y": y}}, i + 1


def _parse_beat_shake(tokens, stripped, lines, i, cast):
    intensity = tokens[1] if len(tokens) >= 2 else ""
    count = tokens[2] if len(tokens) >= 3 else ""
    return {"type": "shake", "data": {"intensity": intensity, "count": count}}, i + 1


def _parse_beat_faceplayer(tokens, stripped, lines, i, cast):
    return {"type": "faceplayer", "data": {}}, i + 1


def _parse_beat_special(tokens, stripped, lines, i, cast):
    func = tokens[1] if len(tokens) >= 2 else ""
    result_var = tokens[2] if len(tokens) >= 3 else ""
    return {"type": "special", "data": {"function": func, "result_var": result_var}}, i + 1


def _parse_beat_waitstate(tokens, stripped, lines, i, cast):
    return {"type": "waitstate", "data": {}}, i + 1


def _parse_beat_gotoif(tokens, stripped, lines, i, cast):
    flag = tokens[1] if len(tokens) >= 2 else ""
    target = tokens[2] if len(tokens) >= 3 else ""
    return {"type": "gotoif", "data": {"flag": flag, "target": target}}, i + 1


def _parse_beat_page(tokens, stripped, lines, i, cast):
    """Parse 'page N [if CONDITION]' into a page beat."""
    page_num = int(tokens[1]) if len(tokens) >= 2 else 1
    raw_condition = ""
    if len(tokens) >= 3 and tokens[2] == "if":
        raw_condition = " ".join(tokens[3:])
    return {"type": "page", "data": {"page_num": page_num, "condition": raw_condition}}, i + 1


def _parse_beat_condition(tokens, stripped, lines, i, cast):
    """Parse if/elif/else into a condition beat."""
    branch = tokens[0]  # "if", "elif", or "else"
    raw_cond = stripped[len(branch):].strip() if branch != "else" else ""
    return {"type": "condition", "data": {"branch": branch, "raw_condition": raw_cond}}, i + 1


def _parse_beat_endif(tokens, stripped, lines, i, cast):
    return {"type": "endif", "data": {}}, i + 1


def _parse_beat_switch(tokens, stripped, lines, i, cast):
    var_name = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "switch", "data": {"var": var_name}}, i + 1


def _parse_beat_case(tokens, stripped, lines, i, cast):
    value = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "case", "data": {"value": value}}, i + 1


def _parse_beat_endswitch(tokens, stripped, lines, i, cast):
    return {"type": "endswitch", "data": {}}, i + 1


def _parse_beat_choice(tokens, stripped, lines, i, cast):
    prompt = stripped[7:].strip().strip('"').rstrip('"') if len(stripped) > 7 else ""
    return {"type": "choice", "data": {"prompt": prompt}}, i + 1


def _parse_beat_option(tokens, stripped, lines, i, cast):
    text = stripped[7:].strip().strip('"').rstrip('"') if len(stripped) > 7 else ""
    return {"type": "option", "data": {"text": text}}, i + 1


def _parse_beat_endchoice(tokens, stripped, lines, i, cast):
    return {"type": "endchoice", "data": {}}, i + 1


def _parse_beat_check(tokens, stripped, lines, i, cast):
    check_type = tokens[1] if len(tokens) >= 2 else ""
    argument = tokens[2] if len(tokens) >= 3 else ""
    return {"type": "check", "data": {"check_type": check_type, "argument": argument}}, i + 1


def _parse_beat_battle(tokens, stripped, lines, i, cast):
    cmd = tokens[0]
    args_str = stripped[len(cmd):].strip()
    data = {"battle_type": cmd, "args": args_str}

    # Check for expanded multi-line battle syntax:
    #   trainerbattle_single TRAINER_X
    #     intro "text$"
    #     defeated "text$"
    #     postbattle "text$"
    # Look ahead for indented sub-fields
    j = i + 1
    while j < len(lines):
        sub = lines[j].strip()
        if not sub:
            j += 1
            continue
        m = re.match(r'^(intro|defeated|postbattle)\s+"(.*)"$', sub)
        if m:
            field, text = m.group(1), m.group(2)
            # Collect continuation lines (multi-line text)
            continuation, j = _parse_continuation_lines(lines, j + 1)
            if continuation:
                text += continuation
            data[field] = text
        else:
            break  # Not a sub-field — stop consuming
    return {"type": "battle", "data": data}, j


def _parse_beat_follower(tokens, stripped, lines, i, cast):
    action = tokens[1] if len(tokens) >= 2 else "add"
    args_str = stripped[len("follower"):].strip()
    data = {"action": action, "raw_args": args_str}
    return {"type": "follower", "data": data}, i + 1


def _parse_beat_multi(tokens, stripped, lines, i, cast):
    variant = tokens[1] if len(tokens) >= 2 else "2v2"
    args_str = stripped[len("multi"):].strip()
    data = {"variant": variant, "raw_args": args_str}
    return {"type": "multi", "data": data}, i + 1


def _parse_beat_give(tokens, stripped, lines, i, cast):
    item = tokens[1] if len(tokens) >= 2 else ""
    qty = tokens[2] if len(tokens) >= 3 else "1"
    return {"type": "give", "data": {"item": item, "quantity": qty}}, i + 1


def _parse_beat_raw(tokens, stripped, lines, i, cast):
    raw_content = stripped[4:].strip()
    return {"type": "raw", "data": {"raw_line": raw_content}}, i + 1


def _parse_beat_pory(tokens, stripped, lines, i, cast):
    pory_content = stripped[5:].strip()
    return {"type": "pory", "data": {"raw_line": pory_content}}, i + 1


# Simple keyword beat parsers (no args)
def _parse_beat_keyword(beat_type):
    def parser(tokens, stripped, lines, i, cast):
        return {"type": beat_type, "data": {}}, i + 1
    return parser

_parse_beat_waitmessage = _parse_beat_keyword("waitmessage")
_parse_beat_waitbutton = _parse_beat_keyword("waitbutton")
_parse_beat_waitse = _parse_beat_keyword("waitse")
_parse_beat_waitmoncry = _parse_beat_keyword("waitmoncry")
_parse_beat_waitfanfare = _parse_beat_keyword("waitfanfare")
_parse_beat_hidemon = _parse_beat_keyword("hidemon")

# Single-arg beat parsers
def _parse_beat_single_arg(beat_type, field):
    def parser(tokens, stripped, lines, i, cast):
        val = tokens[1] if len(tokens) >= 2 else ""
        return {"type": beat_type, "data": {field: val}}, i + 1
    return parser

_parse_beat_message_cmd = _parse_beat_single_arg("message", "label")
_parse_beat_random = _parse_beat_single_arg("random", "max")
_parse_beat_braille = _parse_beat_single_arg("braille", "label")
_parse_beat_stat = _parse_beat_single_arg("stat", "stat_name")
_parse_beat_slots = _parse_beat_single_arg("slots", "machine_var")

def _parse_beat_wildbattle(tokens, stripped, lines, i, cast):
    if len(tokens) >= 2 and tokens[1] == "start":
        return {"type": "wildbattle", "data": {"action": "start"}}, i + 1
    species = tokens[1] if len(tokens) >= 2 else ""
    level = tokens[2] if len(tokens) >= 3 else ""
    item = tokens[3] if len(tokens) >= 4 else ""
    return {"type": "wildbattle", "data": {"species": species, "level": level, "item": item}}, i + 1

def _parse_beat_take(tokens, stripped, lines, i, cast):
    item = tokens[1] if len(tokens) >= 2 else ""
    qty = tokens[2] if len(tokens) >= 3 else "1"
    return {"type": "take", "data": {"item": item, "qty": qty}}, i + 1

def _parse_beat_shop(tokens, stripped, lines, i, cast):
    label = tokens[1] if len(tokens) >= 2 else ""
    variant = tokens[2] if len(tokens) >= 3 else ""
    return {"type": "shop", "data": {"label": label, "variant": variant}}, i + 1

def _parse_beat_showmon(tokens, stripped, lines, i, cast):
    species = tokens[1] if len(tokens) >= 2 else ""
    return {"type": "showmon", "data": {"species": species}}, i + 1

def _parse_beat_showmoney(tokens, stripped, lines, i, cast):
    return {"type": "showmoney", "data": {}}, i + 1

def _parse_beat_showcoins(tokens, stripped, lines, i, cast):
    return {"type": "showcoins", "data": {}}, i + 1

def _parse_beat_buffer(tokens, stripped, lines, i, cast):
    slot = tokens[1] if len(tokens) >= 2 else ""
    buf_type = tokens[2] if len(tokens) >= 3 else ""
    arg = tokens[3] if len(tokens) >= 4 else ""
    return {"type": "buffer", "data": {"slot": slot, "buf_type": buf_type, "arg": arg}}, i + 1

def _parse_beat_tile(tokens, stripped, lines, i, cast):
    x = tokens[1] if len(tokens) >= 2 else ""
    y = tokens[2] if len(tokens) >= 3 else ""
    metatile = tokens[3] if len(tokens) >= 4 else ""
    collision = tokens[4] if len(tokens) >= 5 else ""
    return {"type": "tile", "data": {"x": x, "y": y, "metatile": metatile, "collision": collision}}, i + 1

def _parse_beat_door(tokens, stripped, lines, i, cast):
    action = tokens[1] if len(tokens) >= 2 else ""
    x = tokens[2] if len(tokens) >= 3 else ""
    y = tokens[3] if len(tokens) >= 4 else ""
    return {"type": "door", "data": {"action": action, "x": x, "y": y}}, i + 1

def _parse_beat_getpos(tokens, stripped, lines, i, cast):
    target = tokens[1] if len(tokens) >= 2 else ""
    var_x = tokens[2] if len(tokens) >= 3 else ""
    var_y = tokens[3] if len(tokens) >= 4 else ""
    return {"type": "getpos", "data": {"target": target, "var_x": var_x, "var_y": var_y}}, i + 1


# Dispatch table: command keyword -> parser function
# Each parser: (tokens, stripped, lines, i, cast) -> (beat_dict, new_i)
_PARSE_CMD_DISPATCH = {
    "msg": _parse_beat_msg,
    "msgnpc": _parse_beat_msg,
    "text": _parse_beat_text,
    "movement": _parse_beat_movement,
    "lock": _parse_beat_lock,
    "end": _parse_beat_end,
    "release": _parse_beat_release,
    "closemessage": _parse_beat_closemessage,
    "goto": _parse_beat_goto,
    "call": _parse_beat_call,
    "return": _parse_beat_return,
    "fade": _parse_beat_fade,
    "sound": _parse_beat_sound,
    "music": _parse_beat_music,
    "fanfare": _parse_beat_fanfare,
    "cry": _parse_beat_cry,
    "pause": _parse_beat_pause,
    "flag": _parse_beat_flag,
    "var": _parse_beat_var,
    "hide": _parse_beat_hide,
    "remove": _parse_beat_hide,
    "show": _parse_beat_show,
    "add": _parse_beat_show,
    "faint": _parse_beat_faint,
    "revive": _parse_beat_revive,
    "setpos": _parse_beat_setpos,
    "shake": _parse_beat_shake,
    "faceplayer": _parse_beat_faceplayer,
    "special": _parse_beat_special,
    "waitstate": _parse_beat_waitstate,
    "gotoif": _parse_beat_gotoif,
    "page": _parse_beat_page,
    "if": _parse_beat_condition,
    "elif": _parse_beat_condition,
    "else": _parse_beat_condition,
    "endif": _parse_beat_endif,
    "switch": _parse_beat_switch,
    "case": _parse_beat_case,
    "default": _parse_beat_case,
    "endswitch": _parse_beat_endswitch,
    "choice": _parse_beat_choice,
    "option": _parse_beat_option,
    "endchoice": _parse_beat_endchoice,
    "check": _parse_beat_check,
    "trainerbattle_double": _parse_beat_battle,
    "trainerbattle_single": _parse_beat_battle,
    "trainerbattle_no_intro": _parse_beat_battle,
    "raw": _parse_beat_raw,
    "pory": _parse_beat_pory,
    "follower": _parse_beat_follower,
    "multi": _parse_beat_multi,
    "give": _parse_beat_give,
    # Wait/sync
    "waitmessage": _parse_beat_waitmessage,
    "waitbutton": _parse_beat_waitbutton,
    "waitse": _parse_beat_waitse,
    "waitmoncry": _parse_beat_waitmoncry,
    "waitfanfare": _parse_beat_waitfanfare,
    # Extended commands
    "message": _parse_beat_message_cmd,
    "wildbattle": _parse_beat_wildbattle,
    "take": _parse_beat_take,
    "random": _parse_beat_random,
    "shop": _parse_beat_shop,
    "braille": _parse_beat_braille,
    "showmon": _parse_beat_showmon,
    "hidemon": _parse_beat_hidemon,
    "showmoney": _parse_beat_showmoney,
    "showcoins": _parse_beat_showcoins,
    "buffer": _parse_beat_buffer,
    "tile": _parse_beat_tile,
    "door": _parse_beat_door,
    "stat": _parse_beat_stat,
    "slots": _parse_beat_slots,
    "getpos": _parse_beat_getpos,
}


def _parse_actor_segment(seg_tokens):
    """Parse a single actor segment (one actor's action) from a move line.

    Returns an action dict.
    """
    actor = seg_tokens[0]
    action_parts = seg_tokens[1:] if len(seg_tokens) > 1 else []
    if not action_parts:
        return {"actor": actor, "verb": "?", "raw": " ".join(seg_tokens)}
    verb = action_parts[0]
    if verb == "emote":
        emote_name = action_parts[1] if len(action_parts) >= 2 else ""
        return {"actor": actor, "verb": "emote", "emote_name": emote_name}
    if verb == "face":
        direction = action_parts[1] if len(action_parts) >= 2 else ""
        return {"actor": actor, "verb": "face", "direction": direction}
    if verb in WALK_COMMANDS:
        direction = action_parts[1] if len(action_parts) >= 2 else ""
        count = action_parts[2] if len(action_parts) >= 3 else "1"
        return {"actor": actor, "verb": verb, "direction": direction, "count": count}
    if verb in WALKTO_COMMANDS:
        # walkto X Y  OR  walkto <ref_actor> OX OY
        target = action_parts[1] if len(action_parts) >= 2 else ""
        arg2 = action_parts[2] if len(action_parts) >= 3 else "0"
        arg3 = action_parts[3] if len(action_parts) >= 4 else "0"
        try:
            # Absolute mode: walkto X Y
            int(target)
            return {"actor": actor, "verb": verb, "target_x": target,
                    "target_y": arg2}
        except ValueError:
            # Relative mode: walkto <ref> OX OY
            return {"actor": actor, "verb": verb, "ref_actor": target,
                    "offset_x": arg2, "offset_y": arg3}
    if verb == "jump":
        direction = action_parts[1] if len(action_parts) >= 2 else ""
        count = action_parts[2] if len(action_parts) >= 3 else "1"
        return {"actor": actor, "verb": "jump", "direction": direction, "count": count}
    if verb == "do":
        label = action_parts[1] if len(action_parts) >= 2 else ""
        return {"actor": actor, "verb": "do", "label": label}
    return {"actor": actor, "verb": verb, "raw": " ".join(seg_tokens)}


def _parse_actor_line(stripped, cast):
    """Parse an actor-first line (movement/emote with possible + parallel actions).

    Returns a beat dict (either 'emote' or 'move' type).
    """
    segments = [s.strip() for s in stripped.split("+")]
    actions = []
    for seg in segments:
        seg_tokens = seg.split()
        actions.append(_parse_actor_segment(seg_tokens))
    if len(actions) == 1 and actions[0]["verb"] == "emote":
        return {
            "type": "emote",
            "data": {"actor": actions[0]["actor"], "emote_name": actions[0]["emote_name"]}
        }
    return {"type": "move", "data": {"actions": actions}}


def parse_script_text(source_text, emotes_conf=None):
    """Parse TorScript source text (string) into a structured beat list.

    Same output as _parse_script(), but operates on a string instead of a file.
    Used by the headless simulation harness and resimulate API.
    """
    lines = [l.rstrip("\n") for l in source_text.split("\n")]
    return _parse_lines(lines, emotes_conf)


def _parse_script(filepath, emotes_conf=None):
    """
    Parse a TORCH .txt file into a structured beat list.

    Returns:
        {
            "label": str or None,        # first label encountered
            "labels": [str, ...],        # all labels (for multi-label scripts)
            "cast": {name: npc_id, ...}, # alias name -> npc number
            "beats": [beat_dict, ...],   # ordered list of beat dicts
            "header_comment": str or "",  # first # comment before any command
        }

    Each beat is: {"type": str, "data": dict, "source_line": int, "source_end_line": int}
    """
    with open(filepath, "r") as f:
        raw_lines = f.readlines()
    lines = [l.rstrip("\n") for l in raw_lines]
    return _parse_lines(lines, emotes_conf)


def _parse_lines(lines, emotes_conf=None):
    """Internal: parse a list of source lines into a structured beat list."""

    cast = {}           # alias_name -> npc_id (int)
    pokemon_actors = {}  # name -> species (both lowercase)
    beats = []
    labels = []
    header_comment = ""
    found_first_command = False  # tracks whether we've hit any real command

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # --- Blank lines ---
        if not stripped:
            i += 1
            continue

        # --- Header comments (# at top of file, before any command) ---
        if stripped.startswith("#"):
            if not found_first_command:
                comment_text = stripped[1:].strip()
                if header_comment:
                    header_comment += "\n" + comment_text
                else:
                    header_comment = comment_text
            else:
                beats.append({
                    "type": "comment",
                    "data": {"text": stripped[1:].strip()},
                    "source_line": i,
                    "source_end_line": i,
                })
            i += 1
            continue

        found_first_command = True
        tokens = stripped.split()
        cmd = tokens[0]

        # --- alias ---
        if cmd == "alias" and len(tokens) >= 3:
            alias_name = tokens[1]
            target = tokens[2]
            m = re.match(r"^npc(\d+)$", target)
            if m:
                cast[alias_name] = int(m.group(1))
            i += 1
            continue

        # --- pokemon actor ---
        if cmd == "pokemon" and len(tokens) >= 3:
            poke_name = tokens[1].lower()
            target = tokens[2]
            m = re.match(r"^npc(\d+)$", target)
            if m:
                cast[poke_name] = int(m.group(1))
                pokemon_actors[poke_name] = poke_name
            i += 1
            continue

        # --- label ---
        if cmd == "label":
            label_name = tokens[1].rstrip(":") if len(tokens) >= 2 else ""
            labels.append(label_name)
            beats.append({"type": "label", "data": {"name": label_name}, "source_line": i, "source_end_line": i})
            i += 1
            continue

        # --- // or @ comment pass-through ---
        if cmd.startswith("//") or cmd.startswith("@"):
            beats.append({
                "type": "comment",
                "data": {"text": stripped.lstrip("/@").strip()},
                "source_line": i,
                "source_end_line": i,
            })
            i += 1
            continue

        # --- Dispatch table lookup ---
        parser = _PARSE_CMD_DISPATCH.get(cmd)
        if parser:
            src_line = i
            beat, i = parser(tokens, stripped, lines, i, cast)
            beat["source_line"] = src_line
            beat["source_end_line"] = i - 1  # i is next line; end is inclusive
            beats.append(beat)
            continue

        # --- Try to interpret as movement/emote (actor-first line) ---
        known_actors = set(cast.keys()) | {"player"}
        is_actor = cmd in known_actors or re.match(r"^npc\d+$", cmd)
        if is_actor:
            beat = _parse_actor_line(stripped, cast)
            beat["source_line"] = i
            beat["source_end_line"] = i
            beats.append(beat)
            i += 1
            continue

        # --- Fallthrough: unknown -> pory passthrough ---
        beats.append({"type": "pory", "data": {"raw_line": stripped}, "source_line": i, "source_end_line": i})
        i += 1

    return {
        "label": labels[0] if labels else None,
        "labels": labels,
        "cast": cast,
        "pokemon": pokemon_actors,
        "beats": beats,
        "header_comment": header_comment,
    }


# ============================================================
# SERIALIZE HELPERS — extracted from _serialize_script
# ============================================================

def _serialize_move_action(action):
    """Serialize a single move action dict to its text representation."""
    verb = action["verb"]
    actor = action["actor"]
    if verb == "face":
        return f"{actor} face {action['direction']}"
    if verb in WALK_COMMANDS:
        return f"{actor} {verb} {action['direction']} {action['count']}"
    if verb == "jump":
        count = action.get("count", "1")
        if count == "1":
            return f"{actor} jump {action['direction']}"
        return f"{actor} jump {action['direction']} {count}"
    if verb in WALKTO_COMMANDS:
        if "ref_actor" in action:
            return (f"{actor} {verb} {action['ref_actor']} "
                    f"{action['offset_x']} {action['offset_y']}")
        return f"{actor} {verb} {action['target_x']} {action['target_y']}"
    if verb == "do":
        return f"{actor} do {action['label']}"
    if verb == "emote":
        return f"{actor} emote {action['emote_name']}"
    if "raw" in action:
        return action["raw"]
    return f"{actor} {verb}"


def _serialize_beat_label(data, lines):
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(f"label {data['name']}")


def _serialize_beat_comment(data, lines):
    lines.append(f"# {data['text']}")


def _serialize_beat_dialogue(data, lines):
    text = data["text"]
    if not text.endswith("$"):
        text += "$"
    style = data.get("style", "msg")
    lines.append(f'{style} "{text}"')


def _serialize_beat_move(data, lines):
    parts = [_serialize_move_action(a) for a in data["actions"]]
    lines.append(" + ".join(parts))


def _serialize_beat_emote(data, lines):
    lines.append(f"{data['actor']} emote {data['emote_name']}")


def _serialize_beat_fade(data, lines):
    lines.append(f"fade {data['fade_type']}")


def _serialize_beat_sound(data, lines):
    lines.append(f"sound {data['constant']}")


def _serialize_beat_music(data, lines):
    lines.append(f"music {data['constant']}")


def _serialize_beat_fanfare(data, lines):
    lines.append(f"fanfare {data['constant']}")


def _serialize_beat_cry(data, lines):
    lines.append(f"cry {data['species']}")


def _serialize_beat_pause(data, lines):
    if data["duration"]:
        lines.append(f"pause {data['duration']}")
    else:
        lines.append("pause")


def _serialize_beat_flag(data, lines):
    lines.append(f"flag {data['action']} {data['flag_name']}")


def _serialize_beat_var(data, lines):
    lines.append(f"var {data['var_name']} {data['value']}")


def _serialize_beat_hide(data, lines):
    lines.append(f"hide {data['actor']}")


def _serialize_beat_show(data, lines):
    lines.append(f"show {data['actor']}")


def _serialize_beat_faint(data, lines):
    lines.append(f"faint {data['actor']}")


def _serialize_beat_revive(data, lines):
    lines.append(f"revive {data['actor']}")


def _serialize_beat_setpos(data, lines):
    lines.append(f"setpos {data['actor']} {data['x']} {data['y']}")


def _serialize_beat_shake(data, lines):
    lines.append(f"shake {data['intensity']} {data['count']}")


def _serialize_beat_lock(data, lines):
    lines.append("lock")


def _serialize_beat_faceplayer(data, lines):
    lines.append("faceplayer")


def _serialize_beat_closemessage(data, lines):
    lines.append("closemessage")


def _serialize_beat_special(data, lines):
    lines.append(f"special {data['function']}")


def _serialize_beat_waitstate(data, lines):
    lines.append("waitstate")


def _serialize_beat_gotoif(data, lines):
    lines.append(f"gotoif {data['flag']} {data['target']}")


def _serialize_beat_page(data, lines):
    pnum = data.get("page_num", 1)
    cond = data.get("condition", "")
    if cond:
        lines.append(f"page {pnum} if {cond}")
    else:
        lines.append(f"page {pnum}")


def _serialize_beat_condition(data, lines):
    branch = data["branch"]
    raw_cond = data.get("raw_condition", "")
    if branch == "else":
        lines.append("else")
    else:
        lines.append(f"{branch} {raw_cond}".rstrip())


def _serialize_beat_endif(data, lines):
    lines.append("endif")


def _serialize_beat_switch(data, lines):
    lines.append(f"switch {data['var']}")


def _serialize_beat_case(data, lines):
    lines.append(f"case {data['value']}")


def _serialize_beat_endswitch(data, lines):
    lines.append("endswitch")


def _serialize_beat_choice(data, lines):
    lines.append(f'choice "{data["prompt"]}"')


def _serialize_beat_option(data, lines):
    lines.append(f'option "{data["text"]}"')


def _serialize_beat_endchoice(data, lines):
    lines.append("endchoice")


def _serialize_beat_check(data, lines):
    ct = data["check_type"]
    arg = data.get("argument", "")
    if arg:
        lines.append(f"check {ct} {arg}")
    else:
        lines.append(f"check {ct}")


def _serialize_beat_flow(data, lines):
    ft = data["flow_type"]
    if ft in ("goto", "call"):
        lines.append(f"{ft} {data.get('target', '')}")
    elif ft in ("end", "release", "return"):
        lines.append(ft)


def _serialize_beat_battle(data, lines):
    # Expanded form: has inline intro/defeated/postbattle text fields
    if any(k in data for k in ("intro", "defeated", "postbattle")):
        lines.append(f"{data['battle_type']} {data['args']}")
        for field in ("intro", "defeated", "postbattle"):
            if field in data and data[field]:
                lines.append(f'  {field} "{data[field]}"')
    else:
        lines.append(f"{data['battle_type']} {data['args']}")


def _serialize_beat_text(data, lines):
    lines.append(f"text {data['label']} \"{data['content']}\"")


def _serialize_beat_movement(data, lines):
    cmds = data.get("commands", [])
    if len(cmds) == 1:
        lines.append(f"movement {data['label']} {{{cmds[0]}}}")
    else:
        lines.append(f"movement {data['label']}")
        for mc in cmds:
            lines.append(f"    {mc}")
        lines.append("endmovement")


def _serialize_beat_follower(data, lines):
    lines.append(f"follower {data['raw_args']}")


def _serialize_beat_multi(data, lines):
    lines.append(f"multi {data['raw_args']}")


def _serialize_beat_give(data, lines):
    qty = data.get("quantity", "1")
    if qty != "1":
        lines.append(f"give {data['item']} {qty}")
    else:
        lines.append(f"give {data['item']}")


def _serialize_beat_pory(data, lines):
    lines.append(f"pory {data['raw_line']}")


def _serialize_beat_raw(data, lines):
    lines.append(f"raw {data['raw_line']}")


# Dispatch table: beat type -> serializer function
# Each serializer: (data, lines) -> None (appends to lines)
_SERIALIZE_DISPATCH = {
    "label": _serialize_beat_label,
    "comment": _serialize_beat_comment,
    "dialogue": _serialize_beat_dialogue,
    "move": _serialize_beat_move,
    "emote": _serialize_beat_emote,
    "fade": _serialize_beat_fade,
    "sound": _serialize_beat_sound,
    "music": _serialize_beat_music,
    "fanfare": _serialize_beat_fanfare,
    "cry": _serialize_beat_cry,
    "pause": _serialize_beat_pause,
    "flag": _serialize_beat_flag,
    "var": _serialize_beat_var,
    "hide": _serialize_beat_hide,
    "show": _serialize_beat_show,
    "faint": _serialize_beat_faint,
    "revive": _serialize_beat_revive,
    "setpos": _serialize_beat_setpos,
    "shake": _serialize_beat_shake,
    "lock": _serialize_beat_lock,
    "faceplayer": _serialize_beat_faceplayer,
    "closemessage": _serialize_beat_closemessage,
    "special": _serialize_beat_special,
    "waitstate": _serialize_beat_waitstate,
    "gotoif": _serialize_beat_gotoif,
    "page": _serialize_beat_page,
    "condition": _serialize_beat_condition,
    "endif": _serialize_beat_endif,
    "switch": _serialize_beat_switch,
    "case": _serialize_beat_case,
    "endswitch": _serialize_beat_endswitch,
    "choice": _serialize_beat_choice,
    "option": _serialize_beat_option,
    "endchoice": _serialize_beat_endchoice,
    "check": _serialize_beat_check,
    "flow": _serialize_beat_flow,
    "battle": _serialize_beat_battle,
    "text": _serialize_beat_text,
    "movement": _serialize_beat_movement,
    "pory": _serialize_beat_pory,
    "raw": _serialize_beat_raw,
    "follower": _serialize_beat_follower,
    "multi": _serialize_beat_multi,
    "give": _serialize_beat_give,
}


def _serialize_script(script_data):
    """
    Convert a script data structure back into a TORCH .txt file.

    Args:
        script_data: dict from _parse_script() with keys:
            header_comment, cast, beats

    Returns:
        String content of the .txt file.
    """
    lines = []

    # Header comment
    if script_data.get("header_comment"):
        for comment_line in script_data["header_comment"].split("\n"):
            lines.append(f"# {comment_line}")
        lines.append("")

    # Cast (alias and pokemon lines)
    pokemon = script_data.get("pokemon", {})
    if script_data.get("cast"):
        for name, npc_id in script_data["cast"].items():
            if name in pokemon:
                lines.append(f"pokemon {pokemon[name]} npc{npc_id}")
            else:
                lines.append(f"alias {name} npc{npc_id}")
        lines.append("")

    # Beats
    for beat in script_data.get("beats", []):
        serializer = _SERIALIZE_DISPATCH.get(beat["type"])
        if serializer:
            serializer(beat["data"], lines)

    # Ensure file ends with newline
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result


def _serialize_script_tagged(script_data):
    """Serialize script with [TAG] prefixes on beat lines for vim editing.

    Same as _serialize_script, but each beat line gets a [TAG] prefix
    matching the Script Editor's beat type display. Multi-line beats
    (movement blocks) tag only the first line; continuation lines are
    indented under it.

    Use _strip_tags() to remove prefixes before re-parsing.
    """
    lines = []

    # Header comment (no tag — structural)
    if script_data.get("header_comment"):
        for comment_line in script_data["header_comment"].split("\n"):
            lines.append(f"# {comment_line}")
        lines.append("")

    # Cast (no tag — structural)
    pokemon = script_data.get("pokemon", {})
    if script_data.get("cast"):
        for name, npc_id in script_data["cast"].items():
            if name in pokemon:
                lines.append(f"pokemon {pokemon[name]} npc{npc_id}")
            else:
                lines.append(f"alias {name} npc{npc_id}")
        lines.append("")

    # Beats — serialize each, then prepend tag to first line
    for beat in script_data.get("beats", []):
        serializer = _SERIALIZE_DISPATCH.get(beat["type"])
        if not serializer:
            continue
        beat_lines = []
        serializer(beat["data"], beat_lines)
        if not beat_lines:
            continue
        tag = BEAT_TAGS.get(beat["type"], "???")
        # Tag the first line, leave continuation lines as-is
        beat_lines[0] = f"[{tag}]  {beat_lines[0]}"
        lines.extend(beat_lines)

    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result


_TAG_PREFIX_RE = re.compile(r'^\[[A-Z]{3}\]  ')


def _strip_tags(content):
    """Strip [TAG] prefixes from tagged script content for re-parsing."""
    lines = []
    for line in content.split("\n"):
        if _TAG_PREFIX_RE.match(line):
            lines.append(line[6:])  # len("[XXX]  ") == 6
        else:
            lines.append(line)
    return "\n".join(lines)


# ============================================================
# SUMMARY HELPERS — extracted from _script_beat_summary
# ============================================================

def _summary_dialogue(data, ctag):
    text = data["text"]
    if len(text) > 55:
        text = text[:52] + "..."
    style_hint = "" if data.get("style", "msg") == "msg" else " (npc)"
    return f"{ctag}{style_hint}{text}"


def _summary_move(data, ctag):
    parts = []
    all_do = True
    for a in data["actions"]:
        verb = a["verb"]
        actor = a["actor"]
        if verb == "face":
            parts.append(f"{actor} face {a['direction']}")
            all_do = False
        elif verb in WALK_COMMANDS:
            parts.append(f"{actor} {verb} {a['direction']} {a['count']}")
            all_do = False
        elif verb in WALKTO_COMMANDS:
            if "ref_actor" in a:
                parts.append(f"{actor} {verb} {a['ref_actor']} "
                             f"{a['offset_x']} {a['offset_y']}")
            else:
                parts.append(f"{actor} {verb} {a['target_x']} {a['target_y']}")
            all_do = False
        elif verb == "do":
            parts.append(f"{actor} do {a['label']}")
        elif verb == "jump":
            parts.append(f"{actor} jump {a['direction']}")
            all_do = False
        elif verb == "emote":
            parts.append(f"{actor} emote {a['emote_name']}")
            all_do = False
        else:
            parts.append(a.get("raw", f"{actor} {verb}"))
            all_do = False
    if all_do and parts:
        use_tag = _coloured_tag("BLK")
    else:
        use_tag = ctag
    return f"{use_tag}{' + '.join(parts)}"


def _summary_emote(data, ctag):
    return f"{ctag}{data['actor']} emote {data['emote_name']}"


def _summary_fade(data, ctag):
    return f"{ctag}fade {data['fade_type']}"


def _summary_sound(data, ctag):
    return f"{ctag}sound {data['constant']}"


def _summary_music(data, ctag):
    return f"{ctag}music {data['constant']}"


def _summary_fanfare(data, ctag):
    return f"{ctag}fanfare {data['constant']}"


def _summary_cry(data, ctag):
    return f"{ctag}cry {data['species']}"


def _summary_pause(data, ctag):
    dur = data["duration"] or "short"
    return f"{ctag}pause {dur}"


def _summary_flag(data, ctag):
    return f"{ctag}flag {data['action']} {data['flag_name']}"


def _summary_var(data, ctag):
    return f"{ctag}var {data['var_name']} {data['value']}"


def _summary_hide(data, ctag):
    return f"{ctag}hide {data['actor']}"


def _summary_show(data, ctag):
    return f"{ctag}show {data['actor']}"


def _summary_faint(data, ctag):
    return f"{ctag}faint {data['actor']}"


def _summary_revive(data, ctag):
    return f"{ctag}revive {data['actor']}"


def _summary_setpos(data, ctag):
    return f"{ctag}setpos {data['actor']} {data['x']} {data['y']}"


def _summary_shake(data, ctag):
    return f"{ctag}shake {data['intensity']} {data['count']}"


def _summary_lock(data, ctag):
    return f"{ctag}lock"


def _summary_faceplayer(data, ctag):
    return f"{ctag}faceplayer"


def _summary_closemessage(data, ctag):
    return f"{ctag}closemessage"


def _summary_special(data, ctag):
    return f"{ctag}special {data['function']}"


def _summary_waitstate(data, ctag):
    return f"{ctag}waitstate"


def _summary_gotoif(data, ctag):
    return f"{ctag}gotoif {data['flag']} {data['target']}"


def _summary_page(data, ctag):
    pnum = data.get("page_num", 1)
    cond = data.get("condition", "")
    if cond:
        cond_short = cond if len(cond) <= 30 else cond[:27] + "..."
        return f"{ctag}Page {pnum} if {cond_short}"
    return f"{ctag}Page {pnum} (default)"


def _summary_condition(data, ctag):
    branch = data["branch"]
    raw_cond = data.get("raw_condition", "")
    if branch == "else":
        return f"{ctag}else"
    cond_short = raw_cond if len(raw_cond) <= 40 else raw_cond[:37] + "..."
    return f"{ctag}{branch} {cond_short}"


def _summary_endif(data, ctag):
    return f"{ctag}endif"


def _summary_switch(data, ctag):
    return f"{ctag}switch {data['var']}"


def _summary_case(data, ctag):
    return f"{ctag}case {data['value']}"


def _summary_endswitch(data, ctag):
    return f"{ctag}endswitch"


def _summary_choice(data, ctag):
    prompt = data.get("prompt", "")
    if len(prompt) > 35:
        prompt = prompt[:32] + "..."
    return f'{ctag}choice "{prompt}"'


def _summary_option(data, ctag):
    return f'{ctag}option "{data.get("text", "")}"'


def _summary_endchoice(data, ctag):
    return f"{ctag}endchoice"


def _summary_check(data, ctag):
    ct = data.get("check_type", "")
    arg = data.get("argument", "")
    if arg:
        return f"{ctag}check {ct} {arg}"
    return f"{ctag}check {ct}"


def _summary_flow(data, ctag):
    ft = data["flow_type"]
    t = data.get("target", "")
    return f"{ctag}{ft} {t}".rstrip()


def _summary_battle(data, ctag):
    return f"{ctag}{data['battle_type']} {data['args'][:45]}"


def _summary_label(data, ctag):
    return f"{_coloured_tag('LBL')}{data['name']}"


def _summary_text(data, ctag):
    content = data["content"]
    if len(content) > 45:
        content = content[:42] + "..."
    return f"{ctag}text {data['label']} \"{content}\""


def _summary_movement(data, ctag):
    cmds = data.get("commands", [])
    preview = ", ".join(cmds[:2])
    if len(cmds) > 2:
        preview += f" (+{len(cmds)-2})"
    return f"{ctag}movement {data['label']} {{{preview}}}"


def _summary_follower(data, ctag):
    detail = data.get("raw_args", "")[:40]
    return f"{ctag}follower {detail}"


def _summary_multi(data, ctag):
    detail = data.get("raw_args", "")[:40]
    return f"{ctag}multi {detail}"


def _summary_give(data, ctag):
    item = data.get("item", "?")
    qty = data.get("quantity", "1")
    suffix = f" x{qty}" if qty != "1" else ""
    return f"{ctag}give {item}{suffix}"


def _summary_pory(data, ctag):
    return f"{ctag}pory {data['raw_line']}"


def _summary_raw(data, ctag):
    return f"{ctag}raw {data['raw_line']}"


def _summary_comment(data, ctag):
    text = data["text"]
    if len(text) > 50:
        text = text[:47] + "..."
    return f"{ctag}# {text}"


# Dispatch table: beat type -> summary formatter
# Each formatter: (data, ctag) -> str
_SUMMARY_DISPATCH = {
    "dialogue": _summary_dialogue,
    "move": _summary_move,
    "emote": _summary_emote,
    "fade": _summary_fade,
    "sound": _summary_sound,
    "music": _summary_music,
    "fanfare": _summary_fanfare,
    "cry": _summary_cry,
    "pause": _summary_pause,
    "flag": _summary_flag,
    "var": _summary_var,
    "hide": _summary_hide,
    "show": _summary_show,
    "faint": _summary_faint,
    "revive": _summary_revive,
    "setpos": _summary_setpos,
    "shake": _summary_shake,
    "lock": _summary_lock,
    "faceplayer": _summary_faceplayer,
    "closemessage": _summary_closemessage,
    "special": _summary_special,
    "waitstate": _summary_waitstate,
    "gotoif": _summary_gotoif,
    "page": _summary_page,
    "condition": _summary_condition,
    "endif": _summary_endif,
    "switch": _summary_switch,
    "case": _summary_case,
    "endswitch": _summary_endswitch,
    "choice": _summary_choice,
    "option": _summary_option,
    "endchoice": _summary_endchoice,
    "check": _summary_check,
    "flow": _summary_flow,
    "battle": _summary_battle,
    "label": _summary_label,
    "text": _summary_text,
    "movement": _summary_movement,
    "pory": _summary_pory,
    "raw": _summary_raw,
    "comment": _summary_comment,
    "follower": _summary_follower,
    "multi": _summary_multi,
    "give": _summary_give,
}


def _script_beat_summary(beat):
    """Return a compact one-line summary for a beat (used in editor display)."""
    btype = beat["type"]
    data = beat["data"]
    tag = BEAT_TAGS.get(btype, "???")
    ctag = _coloured_tag(tag)

    formatter = _SUMMARY_DISPATCH.get(btype)
    if formatter:
        return formatter(data, ctag)
    return f"{_coloured_tag('???')}{btype}: {data}"


# Help categories — grouped to match the 6 add-beat menu categories
_SCRIPT_HELP_CATEGORIES = [
    {
        "title": "Dialogue",
        "types": ["dialogue", "closemessage", "text"],
        "desc": "Textboxes, dialogue, and named text blocks.",
        "usage": [
            'msg "BUSTER: Hello there!$"',
            'msg "BUSTER: This is a long\\npiece of dialogue.\\pAnd it continues.$"',
            'msgnpc "SIGN: Welcome to Lake Elix!$"',
            "closemessage",
            'text LabelName "Dialogue text$"',
        ],
        "tips": [
            "Use \\n for line break, \\p for new textbox, $ to end.",
            "msgnpc skips the button-wait (good for signs/NPCs).",
            "Auto-adds $ at end if you forget it.",
            "closemessage closes the textbox without waiting.",
            "Named text blocks (text) are used for trainer battle dialogue.",
        ],
    },
    {
        "title": "Movement",
        "types": ["move", "setpos", "hide", "show", "faceplayer"],
        "desc": "Actor positions, movement, and visibility.",
        "usage": [
            "buster walk up 3",
            "buster face player",
            "buster walk up 3 + player face down",
            "buster do MyMoveLabel",
            "setpos clyde 28 62",
            "hide buster / show buster",
            "faceplayer",
        ],
        "tips": [
            "Directions: up, down, left, right, player (toward), away (from).",
            "walkfast = run speed. walkslow = slow walk. slide/jump also available.",
            "'do Label' plays a named movement block.",
            "Use + to move multiple actors at the same time.",
            "setpos teleports an actor to map tile coordinates.",
            "hide/show despawns/spawns actors. faceplayer makes NPC face player.",
        ],
    },
    {
        "title": "Reaction",
        "types": ["emote", "shake", "cry", "fanfare"],
        "desc": "Visual and audio reactions — emotes, camera shake, cries, jingles.",
        "usage": [
            "buster emote !",
            "buster emote ?  /  heart  /  ...  /  !!  /  x",
            "shake 3 2          (intensity, count)",
            "cry SPECIES_KOFFING",
            "fanfare MUS_OBTAIN_ITEM",
        ],
        "tips": [
            "Built-in emotes: !  ?  !!  x  heart  ...",
            "Custom emotes: add to ~/ROMHacking/TORCH/config/emotes.conf",
            "Shake: intensity 1=light, 3=medium, 5=heavy.",
            "Fanfare plays a short jingle and waits for it to finish.",
        ],
    },
    {
        "title": "Screen",
        "types": ["fade", "sound", "music", "pause"],
        "desc": "Screen effects, sound, music, and timing.",
        "usage": [
            "fade black / fade in / fade white / fade from white",
            "sound SE_EXIT",
            "music MUS_ROUTE101",
            "pause / pause long / pause 60",
        ],
        "tips": [
            "'fade black' = fade to black. 'fade in' = fade from black.",
            "Sound plays an SE. Music changes the BGM.",
            "Pause default ~0.27s. 'long' ~0.53s. Number = frame count (60 = 1s).",
        ],
    },
    {
        "title": "Logic",
        "types": ["flag", "var", "gotoif", "flow", "special", "waitstate", "battle"],
        "desc": "Game state, control flow, battles, and engine functions.",
        "usage": [
            "flag set FLAG_MY_FLAG / flag clear FLAG_MY_FLAG",
            "var VAR_TEMP_1 1",
            "gotoif FLAG_NAME LabelName",
            "goto / call / end / release / return",
            "special HealPlayerParty",
            "waitstate",
            "trainerbattle_single TRAINER_ID, IntroLabel, DefeatLabel",
        ],
        "tips": [
            "Flags are persistent on/off switches. Vars hold numeric values.",
            "gotoif: jump to label if flag is set.",
            "'end' stops the script. 'release' unlocks the NPC and ends.",
            "special calls engine functions. waitstate waits for them.",
            "Battle wizard auto-generates text labels for you.",
        ],
    },
    {
        "title": "Structure",
        "types": ["lock", "label", "pory", "raw", "comment"],
        "desc": "Script structure, labels, raw code, and comments.",
        "usage": [
            "lock",
            "label SceneName",
            "pory applymovement(LOCALID_CLYDE, MyMovement)",
            "# This is a comment",
        ],
        "tips": [
            "'lock' should usually be the first beat after a label.",
            "Labels start new script blocks. Use for branching scenes.",
            "pory/raw pass-through lines directly into the .pory file.",
            "Comments starting with # are ignored in compiled output.",
        ],
    },
    {
        "title": "Movement Blocks",
        "types": [],
        "desc": "Press [m] in the editor to open the Movement Block Manager.",
        "usage": [
            "[m] mblocks        Open the Movement Block Editor",
            "buster do MyBlock   Use a block in a move beat (do verb)",
        ],
        "tips": [
            "Movement blocks live in setup.pory and define reusable sequences.",
            "The manager lets you create, edit, rename, and delete blocks.",
            "When adding a 'do' move beat, existing blocks appear as a picker.",
            "Blocks are auto-prefixed with the map name (e.g. MapName_BlockName).",
        ],
    },
    {
        "title": "Quick-Entry",
        "types": [],
        "desc": "Type TorScript directly at the editor prompt with a : prefix.",
        "usage": [
            ":buster emote !",
            ":fade black",
            ':msg "Hello!$"',
            ":buster walk up 3",
            ":pause long",
            ":flag set FLAG_MY_CUSTOM_FLAG",
        ],
        "tips": [
            "Anything you'd type in a .txt file works after the : prefix.",
            "The beat is inserted after the currently selected beat.",
        ],
    },
]


def _script_help_screen():
    """Paginated help screen for Script Editor beat types."""
    while True:
        clear_screen()
        BAR = "  " + "\u2501" * 49
        SEP = "  " + "\u2500" * 49
        print()
        print(BAR)
        print("   SCRIPT EDITOR  \u2014  Help")
        print(BAR)
        print()
        print("  Beat Types")
        print(SEP)
        print()

        for idx, cat in enumerate(_SCRIPT_HELP_CATEGORIES, 1):
            desc_short = cat["desc"]
            if len(desc_short) > 45:
                desc_short = desc_short[:42] + "..."
            print(f"  [{idx:>2}]  {cat['title']:<14} {desc_short}")

        print()
        print("  [#] View details   [q] Back")
        print()
        choice = input("  Select > ").strip()

        if not choice or choice.lower() == "q":
            return

        try:
            cat_idx = int(choice) - 1
            if 0 <= cat_idx < len(_SCRIPT_HELP_CATEGORIES):
                _script_help_detail(_SCRIPT_HELP_CATEGORIES[cat_idx])
            else:
                print(f"  Please enter 1-{len(_SCRIPT_HELP_CATEGORIES)}.")
                input("  Press Enter > ")
        except ValueError:
            print("  Invalid choice.")
            input("  Press Enter > ")


def _script_help_detail(category):
    """Show detailed help for one category."""
    clear_screen()
    BAR = "  " + "\u2501" * 49
    SEP = "  " + "\u2500" * 49
    print()
    print(BAR)
    print(f"   Help  \u2014  {category['title']}")
    print(BAR)
    print()
    print(f"  {category['desc']}")
    print()
    print(SEP)
    print("  Usage")
    print(SEP)
    print()
    for line in category["usage"]:
        print(f"    {line}")
    print()
    if category.get("tips"):
        print(SEP)
        print("  Tips")
        print(SEP)
        print()
        for tip in category["tips"]:
            print(f"    {tip}")
        print()
    input("  Press Enter to go back > ")


# ============================================================
# MOVEMENT BLOCK PARSING / WRITING (setup.pory)
# ============================================================

def _parse_setup_movement_blocks(setup_path):
    """
    Read setup.pory and extract movement blocks.

    Returns:
        list of dicts: [{"label": str, "commands": [str], "start_line": int, "end_line": int}]
    """
    if not os.path.exists(setup_path):
        return []
    with open(setup_path, "r") as f:
        lines = f.readlines()

    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        m = re.match(r'^movement\s+(\w+)\s*\{', line)
        if m:
            label = m.group(1)
            start_line = i
            # Check for single-line block: movement Label { cmd, cmd }
            if "}" in line:
                inner = line[line.index("{") + 1:line.index("}")].strip()
                cmds = [c.strip() for c in inner.split("\n") if c.strip()]
                if not cmds and inner:
                    cmds = [c.strip() for c in inner.split(",") if c.strip()]
                elif not cmds:
                    cmds = []
                # Re-parse: for single-line, commands are newline-separated in pory
                # Actually in setup.pory they're newline-separated inside { }
                cmds = [c.strip() for c in inner.split(",") if c.strip()]
                blocks.append({
                    "label": label,
                    "commands": cmds if cmds else [],
                    "start_line": start_line,
                    "end_line": i,
                })
                i += 1
                continue
            # Multi-line: read until closing }
            cmds = []
            i += 1
            while i < len(lines):
                cline = lines[i].rstrip("\n").strip()
                if cline == "}":
                    blocks.append({
                        "label": label,
                        "commands": cmds,
                        "start_line": start_line,
                        "end_line": i,
                    })
                    i += 1
                    break
                if cline and not cline.startswith("//"):
                    cmds.append(cline)
                i += 1
            continue
        i += 1
    return blocks


def _format_movement_block(label, commands):
    """Format a movement block as Poryscript source lines."""
    lines = [f"movement {label} {{"]
    for cmd in commands:
        lines.append(f"    {cmd}")
    lines.append("}")
    return "\n".join(lines)


def _write_setup_movement_blocks(setup_path, blocks, original_lines=None):
    """
    Surgical write-back: replace movement block region in setup.pory.
    Preserves all non-movement content.

    Args:
        setup_path: path to setup.pory
        blocks: list of {"label": str, "commands": [str]} dicts
        original_lines: if provided, the original file lines (for preservation)
    """
    if original_lines is None:
        if os.path.exists(setup_path):
            with open(setup_path, "r") as f:
                original_lines = f.readlines()
        else:
            original_lines = []

    raw_lines = [l.rstrip("\n") for l in original_lines]

    # Find existing movement block regions to remove
    remove_ranges = []
    i = 0
    while i < len(raw_lines):
        m = re.match(r'^movement\s+\w+\s*\{', raw_lines[i])
        if m:
            start = i
            # Find the end
            if "}" in raw_lines[i] and raw_lines[i].index("{") < raw_lines[i].index("}"):
                remove_ranges.append((start, i))
                i += 1
                continue
            while i < len(raw_lines):
                if raw_lines[i].strip() == "}":
                    remove_ranges.append((start, i))
                    i += 1
                    break
                i += 1
            continue
        i += 1

    # Also remove the "// Named movement blocks" comment if it exists,
    # and any blank line right after the last non-movement content before it
    # (We'll re-add it with the new blocks)
    comment_line = None
    for idx, line in enumerate(raw_lines):
        if line.strip() == "// Named movement blocks":
            comment_line = idx
            break

    # Build new file content: keep everything except movement blocks + comment
    skip_lines = set()
    for start, end in remove_ranges:
        for j in range(start, end + 1):
            skip_lines.add(j)
    if comment_line is not None:
        skip_lines.add(comment_line)

    kept_lines = []
    for idx, line in enumerate(raw_lines):
        if idx not in skip_lines:
            kept_lines.append(line)

    # Strip trailing blank lines
    while kept_lines and kept_lines[-1].strip() == "":
        kept_lines.pop()

    # Append movement blocks if any
    if blocks:
        kept_lines.append("")
        kept_lines.append("// Named movement blocks")
        for block in blocks:
            kept_lines.append(_format_movement_block(block["label"], block["commands"]))

    kept_lines.append("")  # trailing newline

    with open(setup_path, "w") as f:
        f.write("\n".join(kept_lines))


def _rebuild_setup_without_block(setup_path, label_to_remove):
    """Remove a single movement block by label from setup.pory."""
    blocks = _parse_setup_movement_blocks(setup_path)
    remaining = [b for b in blocks if b["label"] != label_to_remove]
    with open(setup_path, "r") as f:
        original_lines = f.readlines()
    _write_setup_movement_blocks(setup_path, remaining, original_lines)


def _ensure_setup_pory(map_name, project_dir):
    """Ensure setup.pory exists for a map. Creates it if missing."""
    map_dir = os.path.join(project_dir, map_name)
    setup_path = os.path.join(map_dir, "setup.pory")
    if os.path.exists(setup_path):
        return setup_path
    os.makedirs(map_dir, exist_ok=True)
    with open(setup_path, "w") as f:
        f.write(f"// {map_name} -- mapscripts, shared text & movement data\n")
        f.write(f"\nmapscripts {map_name}_MapScripts {{}}\n")
    return setup_path


def _find_movement_references(label, map_dir):
    """
    Scan .txt files in a map directory for 'do Label' references.

    Returns:
        list of (filename, line_number, line_text) tuples
    """
    refs = []
    if not os.path.isdir(map_dir):
        return refs
    for fname in sorted(os.listdir(map_dir)):
        if not fname.endswith(".txt"):
            continue
        fpath = os.path.join(map_dir, fname)
        with open(fpath, "r") as f:
            for line_num, line in enumerate(f, 1):
                if re.search(r'\bdo\s+' + re.escape(label) + r'\b', line):
                    refs.append((fname, line_num, line.rstrip()))
    return refs
