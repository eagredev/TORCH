"""Script editor loop, renderer, cast editor, beat prompts, storyboard."""
# TORCH_MODULE: Script Editor
# TORCH_GROUP: Script Studio
import json
import os
import re
import shutil
import subprocess

from torch.config import SETTINGS_DEFAULTS, _nav_keys
from torch.colours import GOLD, WHITE, CYAN, DIM, RST, BAR, BOLD_RED
from torch.ui import print_logo, _offer_build, _set_terminal_title, _k, clear_screen
from torch.data import WALK_COMMANDS, BUILTIN_EMOTES, DIRECTIONS
from torch.compiler import load_emotes, compile_script
from torch.textutils import (
    GBA_LINE_LEN,
    count_text_boxes as _count_dialogue_boxes,
    wrap_gba_text as _wrap_dialogue,
    textbox_preview as _textbox_preview_impl,
    storyboard_display as _storyboard_display_impl,
)
from torch.script_model import (
    BEAT_TAGS, _coloured_tag, _script_beat_summary, _script_help_screen,
    _parse_script, _serialize_script, _serialize_script_tagged, _strip_tags,
    _parse_setup_movement_blocks, _ensure_setup_pory,
)
from torch.script_movements import _movement_block_manager
from torch.sync import sync_map, ensure_synced
from torch.pickers import (
    pick_flag, pick_var, pick_trainer, pick_sound, pick_music,
    pick_fanfare, pick_species, pick_special, _pick_label, pick_item,
)


def _render_script_editor(script_data, map_name, filepath, scroll_offset, selected_idx, dirty, settings=None, view_mode="focused", proj_name=None):
    """Render the Script Editor screen."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)


    clear_screen()
    print_logo("Script Studio", proj_name)
    print(BAR)

    # Scene name from filename
    script_name = os.path.splitext(os.path.basename(filepath))[0]
    label = script_data.get("label") or script_name
    dirty_mark = f" {GOLD}*{RST}" if dirty else ""
    print(f"   {DIM}{map_name} /{RST} {WHITE}{script_name}{RST}{dirty_mark}")
    print(BAR)
    print()

    # Cast line
    cast = script_data.get("cast", {})
    if cast:
        cast_parts = [f"{name}({nid})" for name, nid in cast.items()]
        cast_parts.append("player")
        print(f"  {DIM}Cast:{RST} {', '.join(cast_parts)}")
    else:
        print(f"  {DIM}Cast: player{RST}")
    print()

    # Beat list
    beats = script_data.get("beats", [])
    if not beats:
        print(f"  {DIM}(no beats yet){RST}")
        print()
    else:
        print(f"  {DIM}     #   Type   Content{RST}")
        total = len(beats)

        if view_mode == "full":
            # Full scene — show every beat, no scrolling
            for idx in range(total):
                beat = beats[idx]
                summary = _script_beat_summary(beat)
                num = idx + 1
                if idx == selected_idx:
                    marker = f"{GOLD}>>{RST}"
                else:
                    marker = "  "
                print(f"  {marker} {num:>3}  {summary}")
            scroll_offset = 0
        else:
            # Focused view — scrollable window
            max_visible = settings["editor_visible_beats"]

            # Adjust scroll to keep selected in view
            if selected_idx < scroll_offset:
                scroll_offset = selected_idx
            if selected_idx >= scroll_offset + max_visible:
                scroll_offset = selected_idx - max_visible + 1

            if scroll_offset > 0:
                print(f"  {DIM}  \u2191 {scroll_offset} more above{RST}")

            end = min(scroll_offset + max_visible, total)
            for idx in range(scroll_offset, end):
                beat = beats[idx]
                summary = _script_beat_summary(beat)
                num = idx + 1
                if idx == selected_idx:
                    marker = f"{GOLD}>>{RST}"
                else:
                    marker = "  "
                print(f"  {marker} {num:>3}  {summary}")

            if end < total:
                print(f"  {DIM}  \u2193 {total - end} more below{RST}")
        print()

    # Compact command bar (2 lines: commands + context)
    print(f"  {_k('a')}{DIM}dd{RST}  {_k('e')}{DIM}dit{RST}  {_k('d')}{DIM}el{RST}  {_k('i')}{DIM}ns{RST}  {_k(':')}{DIM} quick{RST}  {_k('s')}{DIM}ave{RST}  {_k('w')}{DIM} build{RST}  {_k('v')}{DIM}im{RST}  {_k('t')}{DIM}imeline{RST}  {_k('?')}{DIM} more{RST}  {_k('q')}{DIM}uit{RST}")
    _render_context_bar(settings, beats, selected_idx, script_data, map_name)
    print()

    return scroll_offset


def _ctx_dialogue(tag, data):
    text = data["text"]
    style = data.get("style", "msg")
    box_count = _count_dialogue_boxes(text)
    trunc = text if len(text) <= 45 else text[:42] + "..."
    return f'{tag}: "{trunc}" \u2014 {style}, {box_count} box{"es" if box_count != 1 else ""}'


def _ctx_move(tag, data):
    parts = []
    for a in data["actions"]:
        verb = a["verb"]
        actor = a["actor"]
        if verb == "face":
            parts.append(f"{actor} face {a['direction']}")
        elif verb in WALK_COMMANDS:
            parts.append(f"{actor} {verb} {a['direction']} {a['count']}")
        elif verb == "do":
            parts.append(f"{actor} do {a['label']}")
        elif verb == "jump":
            parts.append(f"{actor} jump {a['direction']}")
        elif verb == "emote":
            parts.append(f"{actor} emote {a['emote_name']}")
        else:
            parts.append(f"{actor} {verb}")
    torscript = " + ".join(parts)
    if len(torscript) > 50:
        torscript = torscript[:47] + "..."
    return f"{tag}: {torscript}"


def _ctx_battle(tag, data):
    args_parts = [a.strip() for a in data["args"].split(",")]
    trainer = args_parts[0] if args_parts else "?"
    bt = "double" if "double" in data["battle_type"] else "single"
    from torch.names import _const_to_human_name
    trainer_short = _const_to_human_name(trainer, "TRAINER_")
    return f"{tag}: {bt} vs {trainer_short}"


def _ctx_pause(tag, data):
    dur = data["duration"] or "default"
    return f"{tag}: {dur}"


def _ctx_flow(tag, data):
    ft = data["flow_type"]
    t = data.get("target", "")
    return f"{tag}: {ft} {t}".rstrip()


def _ctx_comment(tag, data):
    text = data["text"]
    if len(text) > 45:
        text = text[:42] + "..."
    return f"REM: # {text}"


_CONTEXT_RENDERERS = {
    "dialogue": _ctx_dialogue,
    "move": _ctx_move,
    "emote": lambda tag, data: f"{tag}: {data['actor']} emote {data['emote_name']}",
    "fade": lambda tag, data: f"{tag}: fade {data['fade_type']}",
    "flag": lambda tag, data: f"{tag}: {data['action']} {data['flag_name']}",
    "battle": _ctx_battle,
    "sound": lambda tag, data: f"{tag}: {data['constant']}",
    "music": lambda tag, data: f"{tag}: {data['constant']}",
    "fanfare": lambda tag, data: f"{tag}: {data['constant']}",
    "cry": lambda tag, data: f"{tag}: {data['species']}",
    "pause": _ctx_pause,
    "flow": _ctx_flow,
    "var": lambda tag, data: f"{tag}: {data['var_name']} = {data['value']}",
    "gotoif": lambda tag, data: f"{tag}: if {data['flag']} \u2192 {data['target']}",
    "hide": lambda tag, data: f"{tag}: hide {data['actor']}",
    "show": lambda tag, data: f"{tag}: show {data['actor']}",
    "setpos": lambda tag, data: f"{tag}: {data['actor']} at ({data['x']}, {data['y']})",
    "shake": lambda tag, data: f"{tag}: intensity {data['intensity']}, {data['count']}x",
    "label": lambda tag, data: f"LBL: {data['name']}",
    "lock": lambda tag, data: f"{tag}: lock",
    "faceplayer": lambda tag, data: f"{tag}: faceplayer",
    "special": lambda tag, data: f"{tag}: {data['function']}",
    "waitstate": lambda tag, data: f"{tag}: waitstate",
    "closemessage": lambda tag, data: f"{tag}: closemessage",
    "comment": _ctx_comment,
    "pory": lambda tag, data: f"{tag}: {data['raw_line']}",
    "text": lambda tag, data: f"{tag}: {data['label']}",
    "follower": lambda tag, data: f"{tag}: follower {data.get('action', '?')} {data.get('raw_args', '')[:30]}",
    "multi": lambda tag, data: f"{tag}: multi {data.get('variant', '?')} {data.get('raw_args', '')[:30]}",
}


def _render_context_bar(settings, beats, selected_idx, script_data, map_name):
    """Render the TV/context info bar below the command bar."""
    ctx_mode = settings.get("editor_context", "compact")
    print(f"  {_k('tv')}{DIM} view: {ctx_mode}{RST}")

    if ctx_mode == "timeline" and beats:
        excerpt = _timeline_excerpt(beats, selected_idx, map_name)
        if excerpt:
            print()
            for line in excerpt:
                print(line)
    elif ctx_mode != "off" and beats:
        sel_beat = beats[selected_idx] if 0 <= selected_idx < len(beats) else None
        if sel_beat:
            ctx = _beat_context_line(sel_beat, script_data, ctx_mode)
            if ctx:
                count_str = f"{len(beats)} beat{'s' if len(beats) != 1 else ''}"
                print(f"  {DIM}{count_str}  |  >> {ctx}{RST}")
                if ctx_mode == "detail":
                    detail = _beat_context_detail(sel_beat, script_data)
                    if detail:
                        print(f"  {DIM}   {detail}{RST}")


def _beat_context_line(beat, script_data, mode="compact"):
    """Format a compact context summary for the selected beat. Returns a string."""
    btype = beat["type"]
    data = beat["data"]
    tag = BEAT_TAGS.get(btype, "???")
    renderer = _CONTEXT_RENDERERS.get(btype)
    if renderer:
        return renderer(tag, data)
    return f"{tag}: {btype}"


def _beat_context_detail(beat, script_data):
    """Return extra detail line for 'detail' context mode. Returns string or empty."""
    btype = beat["type"]
    data = beat["data"]

    if btype == "dialogue":
        text = data["text"]
        # Count chars per line in each box
        segments = re.split(r'\\n|\\p', text)
        line_lens = [len(s) for s in segments]
        long_lines = [l for l in line_lens if l > GBA_LINE_LEN]
        box_count = _count_dialogue_boxes(text)
        info = f"{box_count} box{'es' if box_count != 1 else ''}, {len(segments)} line{'s' if len(segments) != 1 else ''}"
        if long_lines:
            info += f", {len(long_lines)} auto-wrapped"
        return info

    if btype == "battle":
        args_parts = [a.strip() for a in data["args"].split(",")]
        labels = []
        for part in args_parts[1:]:
            labels.append(part)
        bt = data["battle_type"].replace("trainerbattle_", "")
        return f"{bt} \u2014 labels: {', '.join(labels)}" if labels else ""

    if btype == "move":
        parts = []
        for a in data["actions"]:
            verb = a["verb"]
            actor = a["actor"]
            if verb == "face":
                parts.append(f"{actor} face {a['direction']}")
            elif verb in WALK_COMMANDS:
                parts.append(f"{actor} {verb} {a['direction']} {a['count']}")
            elif verb == "do":
                parts.append(f"{actor} do {a['label']}")
            elif verb == "jump":
                parts.append(f"{actor} jump {a['direction']}")
            elif verb == "emote":
                parts.append(f"{actor} emote {a['emote_name']}")
            else:
                parts.append(f"{actor} {verb}")
        full = " + ".join(parts)
        # Only show detail if truncated in compact
        return full if len(full) > 50 else ""

    return ""


def _timeline_excerpt(beats, selected_idx, map_name, radius=1):
    """Generate a small storyboard excerpt around the selected beat.

    Returns list of formatted lines (with > marker on current beat).
    Skips comment/label beats in the numbering (matches storyboard).
    """
    if not beats:
        return []

    # Build storyboard lines for all beats, tracking which map to which index
    sb_entries = []  # [(beat_idx, [lines...])]
    beat_num = 0
    for bi, beat in enumerate(beats):
        btype = beat["type"]
        data = beat["data"]
        if btype == "label":
            continue
        if btype == "comment":
            continue
        beat_num += 1
        renderer = _SB_RENDERERS.get(btype)
        if renderer:
            rendered = renderer(beat_num, data, map_name)
        else:
            rendered = [f"  {beat_num:>3}. {btype}: {data}"]
        sb_entries.append((bi, rendered))

    # Find where selected_idx falls in sb_entries
    sel_pos = None
    for si, (bi, _lines) in enumerate(sb_entries):
        if bi == selected_idx:
            sel_pos = si
            break

    if sel_pos is None:
        return []

    # Window around selected
    start = max(0, sel_pos - radius)
    end = min(len(sb_entries), sel_pos + radius + 1)

    result = []
    for si in range(start, end):
        bi, lines = sb_entries[si]
        marker = f"{GOLD}>{RST}" if bi == selected_idx else " "
        for li, line in enumerate(lines):
            # Strip leading spaces from storyboard line, re-indent
            clean = line.lstrip()
            if li == 0:
                result.append(f"  {marker} {clean}")
            else:
                result.append(f"    {clean}")

    return result


def _show_full_commands():
    """Display the full command reference screen (triggered by [?])."""

    clear_screen()
    print(BAR)
    print(f"   {WHITE}COMMANDS{RST}")
    print(BAR)
    print()
    print(f"  {WHITE}Navigation{RST}                    {WHITE}Editing{RST}")
    print(f"  {DIM}\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500{RST}                    {DIM}\u2500\u2500\u2500\u2500\u2500\u2500\u2500{RST}")
    print(f"  {GOLD}Enter{RST}    {DIM}step forward{RST}         {GOLD}[a]{RST}  {DIM}add beat after selection{RST}")
    print(f"  {GOLD}[b]{RST}      {DIM}step backward{RST}        {GOLD}[i]{RST}  {DIM}insert beat before{RST}")
    print(f"  {GOLD}[#]{RST}      {DIM}jump to beat #{RST}       {GOLD}[e]{RST}  {DIM}edit selected beat{RST}")
    print(f"  {GOLD}[u]{RST}      {DIM}shift beat up{RST}        {GOLD}[d]{RST}  {DIM}delete beat{RST}")
    print(f"  {GOLD}[j]{RST}      {DIM}shift beat down{RST}      {GOLD}[x]{RST}  {DIM}move beat (x # #){RST}")
    print()
    print(f"  {WHITE}Script{RST}                        {WHITE}File{RST}")
    print(f"  {DIM}\u2500\u2500\u2500\u2500\u2500{RST}                         {DIM}\u2500\u2500\u2500\u2500{RST}")
    print(f"  {GOLD}[c]{RST}  {DIM}cast editor{RST}              {GOLD}[s]{RST}  {DIM}save{RST}")
    print(f"  {GOLD}[l]{RST}  {DIM}rename label{RST}             {GOLD}[w]{RST}  {DIM}save + build{RST}")
    print(f"  {GOLD}[n]{RST}  {DIM}edit header note{RST}         {GOLD}[q]{RST}  {DIM}quit{RST}")
    print(f"  {GOLD}[m]{RST}  {DIM}movement blocks{RST}          {GOLD}[f]{RST}  {DIM}toggle focused/full view{RST}")
    print(f"  {GOLD}[v]{RST}  {DIM}open in vim{RST}              {GOLD}[t]{RST}  {DIM}timeline view{RST}")
    print(f"  {GOLD}[tv]{RST} {DIM}cycle context line{RST}")
    print()
    print(f"  {WHITE}Quick entry:{RST} {DIM}type{RST} {GOLD}:{RST} {DIM}followed by TorScript{RST}")
    print(f"    {DIM}:buster walk up 3    :fade black    :msg \"Hello!\"{RST}")
    print()
    print(f"  {GOLD}[?]{RST} {DIM}this screen{RST}       {GOLD}[Enter]{RST} {DIM}back to editor{RST}")
    print()
    input("  Press Enter > ")


def _edit_cast(script_data, proj_name=None):
    """Interactive cast editor — add/remove/rename aliases."""


    while True:
        clear_screen()
        print_logo("Script Studio", proj_name)
        print(BAR)
        print(f"   {WHITE}CAST EDITOR{RST}")
        print(BAR)
        print()

        cast = script_data.get("cast", {})
        if cast:
            print(f"  {DIM}Current cast:{RST}")
            for i, (name, nid) in enumerate(cast.items(), 1):
                print(f"    {_k(i)} {WHITE}{name}{RST} = {CYAN}npc{nid}{RST}")
            print(f"    {_k('+')} {DIM}player (always present){RST}")
        else:
            print(f"  {DIM}No actors defined (player is always present){RST}")
        print()
        print(f"  {_k('a')} {DIM}Add actor{RST}  {_k('d')} {DIM}Remove actor{RST}  {_k('q')} {DIM}Done{RST}")
        print()
        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if choice in ("q", ""):
            return

        if choice == "a":
            print()
            name = input("  Actor name (e.g. buster) > ").strip().lower()
            if not name:
                continue
            original = name
            name = re.sub(r'\s+', '_', name)
            if name != original:
                print(f"  (spaces converted to underscores: {name})")
            if name == "player":
                print("  'player' is always present, no alias needed.")
                input("  Press Enter > ")
                continue
            npc_raw = input(f"  NPC object ID for {name} (e.g. 5) > ").strip()
            try:
                npc_id = int(npc_raw)
                cast[name] = npc_id
                script_data["cast"] = cast
                print(f"  Added: {name} = npc{npc_id}")
            except ValueError:
                print("  Invalid number.")
            input("  Press Enter > ")
            continue

        if choice == "d":
            if not cast:
                print("  No actors to remove.")
                input("  Press Enter > ")
                continue
            print()
            names = list(cast.keys())
            for i, n in enumerate(names, 1):
                print(f"    [{i}] {n}")
            raw = input("  Remove which? [#] > ").strip()
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(names):
                    removed = names[idx]
                    del cast[removed]
                    script_data["cast"] = cast
                    print(f"  Removed: {removed}")
                else:
                    print("  Invalid number.")
            except ValueError:
                print("  Invalid input.")
            input("  Press Enter > ")
            continue


_BEAT_CATEGORIES = [
    {
        "key": "1", "name": "Dialogue",
        "items": [
            ("1", "msg",          "Normal dialogue with textbox"),
            ("2", "msgnpc",       "NPC/sign text (no button wait)"),
            ("3", "text",         "Named text block (for battles)"),
            ("4", "closemessage", "Close the current textbox"),
        ],
    },
    {
        "key": "2", "name": "Movement",
        "items": [
            ("1", "move",       "Walk, run, face, jump, slide an actor"),
            ("2", "setpos",     "Teleport actor to coordinates"),
            ("3", "hide",       "Despawn actor from the map"),
            ("4", "show",       "Spawn actor on the map"),
            ("5", "faceplayer", "NPC turns to face the player"),
            ("6", "follower",   "Add/remove NPC follower"),
        ],
    },
    {
        "key": "3", "name": "Reaction",
        "items": [
            ("1", "emote",   "Show reaction bubble above actor"),
            ("2", "shake",   "Shake the camera"),
            ("3", "cry",     "Play a Pokemon's cry"),
            ("4", "fanfare", "Play a short jingle"),
        ],
    },
    {
        "key": "4", "name": "Screen",
        "items": [
            ("1", "fade",  "Fade screen to/from black or white"),
            ("2", "sound", "Play a sound effect"),
            ("3", "music", "Change background music"),
            ("4", "pause", "Wait for a duration"),
        ],
    },
    {
        "key": "5", "name": "Logic",
        "items": [
            ("1", "flag",      "Set or clear a game flag"),
            ("2", "var",       "Set a game variable"),
            ("3", "gotoif",    "Conditional jump (if flag set)"),
            ("4", "flow",      "goto / call / end / release / return"),
            ("5", "special",   "Call engine special function"),
            ("6", "waitstate", "Wait for special to finish"),
            ("7", "battle",    "Trigger a trainer battle"),
            ("8", "multi",     "Scripted multi-battle (player+partner)"),
            ("9", "give",      "Give item to player (with bag check)"),
        ],
    },
    {
        "key": "6", "name": "Structure",
        "items": [
            ("1", "lock",    "Lock player movement"),
            ("2", "label",   "Start a new script label"),
            ("3", "pory",    "Raw Poryscript line"),
            ("4", "comment", "Remark (not compiled)"),
        ],
    },
]

# Per-beat-type help cards — comprehensive help for each of the 28 beat types
_BEAT_HELP = {
    "msg": {
        "name": "Dialogue",
        "desc": "Show a dialogue textbox spoken by an actor.",
        "torscript": ':buster "Hello there!\\p"',
        "fields": [
            "actor -- who speaks (cast member name)",
            "text -- dialogue content (supports \\n, \\p, {COLOR})",
        ],
        "tips": [
            "\\n = line break within textbox, \\p = start a new page",
            "GBA textbox fits ~36 chars/line, 2 lines per box",
            "Use \\p for long messages that need multiple boxes",
        ],
    },
    "msgnpc": {
        "name": "NPC/Sign Text",
        "desc": "Show text with no button prompt (auto-closes).",
        "torscript": ':sign "READ ME"',
        "fields": [
            "text -- message content",
        ],
        "tips": [
            "Auto-closes after display, no A-button wait",
            "Good for signs, posters, and flavour text",
        ],
    },
    "text": {
        "name": "Text Block",
        "desc": "Named text block (used by trainer battles).",
        "torscript": 'text MyLabel { "content$" }',
        "fields": [
            "label -- name for this text block",
            "content -- text string (must end with $)",
        ],
        "tips": [
            "Must end with $ (string terminator)",
            "Referenced by trainerbattle macros for intro/defeat text",
        ],
    },
    "closemessage": {
        "name": "Close Message",
        "desc": "Close the current textbox.",
        "torscript": "closemessage",
        "fields": [],
        "tips": [
            "Use after a dialogue chain before movement or fades",
            "Not needed if the script ends immediately after dialogue",
        ],
    },
    "move": {
        "name": "Movement",
        "desc": "Walk, run, face, jump, or slide an actor.",
        "torscript": ':buster walk_left * 3',
        "fields": [
            "actor -- who moves (cast member name)",
            "movement -- type (walk_left, run_up, jump_down, etc.)",
            "steps -- how many tiles to move",
        ],
        "tips": [
            "Movements are queued and play in sequence",
            "Use faceplayer for a quick turn without walking",
            "Available movements: walk/run/jump/slide + direction",
        ],
    },
    "setpos": {
        "name": "Set Position",
        "desc": "Teleport an actor to coordinates instantly.",
        "torscript": "setobjectxyperm(npc, x, y)",
        "fields": [
            "actor -- who to move",
            "x -- map X coordinate",
            "y -- map Y coordinate",
        ],
        "tips": [
            "Instant, no walking animation",
            "Use before show to pre-position a hidden actor",
        ],
    },
    "hide": {
        "name": "Hide Actor",
        "desc": "Despawn an actor from the map.",
        "torscript": "removeobject(npc)",
        "fields": [
            "actor -- who to hide",
        ],
        "tips": [
            "Persists until show or map reload",
            "Use with flags to keep NPCs hidden permanently",
        ],
    },
    "show": {
        "name": "Show Actor",
        "desc": "Spawn an actor on the map.",
        "torscript": "addobject(npc)",
        "fields": [
            "actor -- who to show",
        ],
        "tips": [
            "Actor must be hidden first (or start hidden)",
            "Appears at their original or setpos position",
        ],
    },
    "faceplayer": {
        "name": "Face Player",
        "desc": "NPC turns to face the player.",
        "torscript": "faceplayer",
        "fields": [],
        "tips": [
            "Automatic in most NPC interaction scripts",
            "Use explicitly in coord triggers or after movement",
        ],
    },
    "emote": {
        "name": "Emote Bubble",
        "desc": "Show a reaction bubble above an actor.",
        "torscript": ':buster !',
        "fields": [
            "actor -- who shows the emote",
            "emote -- reaction type (!, ?, ..., etc.)",
        ],
        "tips": [
            "Available emotes are listed in emotes.conf",
            "Common: ! (surprise), ? (confused), ... (thinking)",
        ],
    },
    "shake": {
        "name": "Screen Shake",
        "desc": "Shake the camera for dramatic effect.",
        "torscript": "special(ShakeCamera)",
        "fields": [
            "intensity -- shake strength (1-3)",
        ],
        "tips": [
            "Use for explosions, earthquakes, dramatic moments",
            "Pair with sound effects for impact",
        ],
    },
    "cry": {
        "name": "Pokemon Cry",
        "desc": "Play a Pokemon's cry sound.",
        "torscript": "cry(SPECIES_PIKACHU)",
        "fields": [
            "species -- which Pokemon's cry to play",
        ],
        "tips": [
            "For Pokemon encounters and story moments",
            "Use waitstate after if you need to wait for it",
        ],
    },
    "fanfare": {
        "name": "Fanfare Jingle",
        "desc": "Play a short victory/event jingle.",
        "torscript": "playfanfare(MUS_OBTAIN_ITEM)",
        "fields": [
            "fanfare -- jingle ID (MUS_OBTAIN_ITEM, etc.)",
        ],
        "tips": [
            "Common: item get, badge get, quest complete",
            "Short one-shot sound, doesn't replace BGM",
        ],
    },
    "fade": {
        "name": "Screen Fade",
        "desc": "Fade the screen to/from black or white.",
        "torscript": "fadescreen(FADE_TO_BLACK)",
        "fields": [
            "direction -- in (from black) or out (to black)",
            "color -- black or white",
        ],
        "tips": [
            "Use for scene transitions and dramatic pauses",
            "Pair fade-out with fade-in around scene changes",
        ],
    },
    "sound": {
        "name": "Sound Effect",
        "desc": "Play a one-shot sound effect.",
        "torscript": "playse(SE_PIN)",
        "fields": [
            "sound -- sound effect ID (SE_PIN, SE_DOOR, etc.)",
        ],
        "tips": [
            "One-shot, does not loop",
            "Use for doors, buttons, impacts, alerts",
        ],
    },
    "music": {
        "name": "Background Music",
        "desc": "Change the background music track.",
        "torscript": "playbgm(MUS_PETALBURG, TRUE)",
        "fields": [
            "track -- music ID (MUS_PETALBURG, etc.)",
        ],
        "tips": [
            "TRUE = crossfade, FALSE = instant switch",
            "Persists until another playbgm or map change",
        ],
    },
    "pause": {
        "name": "Pause/Delay",
        "desc": "Wait for a duration before continuing.",
        "torscript": "delay(30)",
        "fields": [
            "frames -- wait time (60 = 1 second on GBA)",
        ],
        "tips": [
            "60 frames = 1 second on GBA",
            "Use for dramatic timing between actions",
        ],
    },
    "flag": {
        "name": "Set/Clear Flag",
        "desc": "Set or clear a boolean game flag.",
        "torscript": "setflag(FLAG_BADGE01_GET)",
        "fields": [
            "flag -- flag constant (FLAG_BADGE01_GET, etc.)",
            "action -- set or clear",
        ],
        "tips": [
            "Flags are booleans (on/off)",
            "Check with goto_if_set / goto_if_unset",
        ],
    },
    "var": {
        "name": "Set Variable",
        "desc": "Set a game variable to a numeric value.",
        "torscript": "setvar(VAR_TEMP_1, 1)",
        "fields": [
            "var -- variable constant (VAR_TEMP_1, etc.)",
            "value -- number (0-65535)",
        ],
        "tips": [
            "Vars hold numbers 0-65535",
            "VAR_TEMP_* are safe for temporary use",
        ],
    },
    "gotoif": {
        "name": "Conditional Jump",
        "desc": "Branch the script based on a flag's state.",
        "torscript": "goto_if_set(FLAG_X, Label)",
        "fields": [
            "flag -- which flag to check",
            "label -- where to jump if condition is true",
        ],
        "tips": [
            "Branches the script flow",
            "Combine with flag/var for story progression gates",
        ],
    },
    "flow": {
        "name": "Flow Control",
        "desc": "Script flow: goto, call, end, release, return.",
        "torscript": "goto(MyLabel)",
        "fields": [
            "flow_type -- goto / call / end / release / return",
            "target -- label name (for goto/call)",
        ],
        "tips": [
            "end = stop script execution",
            "release = unlock player movement + end",
            "call = jump to label, then return back",
        ],
    },
    "special": {
        "name": "Engine Special",
        "desc": "Call an engine-level special function.",
        "torscript": "special(HealPlayerParty)",
        "fields": [
            "special -- function name (HealPlayerParty, etc.)",
        ],
        "tips": [
            "Engine-level functions for healing, shops, etc.",
            "Use waitstate after async specials",
        ],
    },
    "waitstate": {
        "name": "Wait State",
        "desc": "Wait for an async special to finish.",
        "torscript": "waitstate",
        "fields": [],
        "tips": [
            "Always pair with async specials",
            "Script pauses until the special completes",
        ],
    },
    "battle": {
        "name": "Trainer Battle",
        "desc": "Trigger a trainer battle encounter.",
        "torscript": 'trainerbattle_single(TRAINER_ID, "intro", "defeat")',
        "fields": [
            "trainer -- trainer ID constant",
            "intro -- text shown before battle",
            "defeat -- text shown when trainer loses",
        ],
        "tips": [
            "Different macros for single/double battles",
            "Trainer ID must be defined in trainers data",
        ],
    },
    "lock": {
        "name": "Lock Player",
        "desc": "Lock player movement during a script.",
        "torscript": "lock",
        "fields": [],
        "tips": [
            "Use at the start of NPC interaction scripts",
            "Always pair with release at the end",
        ],
    },
    "label": {
        "name": "Script Label",
        "desc": "Start a new named label in the script.",
        "torscript": "MyLabel:",
        "fields": [
            "name -- label identifier (target for goto/call)",
        ],
        "tips": [
            "Target for goto and call jumps",
            "Use descriptive names (e.g. GiveItem, BattleDone)",
        ],
    },
    "pory": {
        "name": "Raw Poryscript",
        "desc": "Insert a raw Poryscript line directly.",
        "torscript": "(whatever you type)",
        "fields": [
            "code -- raw Poryscript code",
        ],
        "tips": [
            "Escape hatch for anything the wizard doesn't cover",
            "Line is inserted as-is into the compiled output",
        ],
    },
    "comment": {
        "name": "Comment",
        "desc": "A remark that won't be compiled.",
        "torscript": "# Comment text",
        "fields": [
            "text -- your note or reminder",
        ],
        "tips": [
            "Notes for yourself, ignored by compiler",
            "Good for marking sections or TODOs",
        ],
    },
    "follower": {
        "name": "NPC Follower",
        "desc": "Add, remove, or control an NPC follower.",
        "torscript": "follower add local LOCALID_X PARTNER_Y FNPC_ALL",
        "fields": [
            "action -- add/remove/face/hide/check/change",
            "source -- local (existing NPC) or dynamic (spawn)",
            "partner -- PARTNER_* constant",
            "flags -- behavior flags (FNPC_ALL, FNPC_ALL_LAND)",
        ],
        "tips": [
            "Requires expansion v1.12.0+ and FNPC_ENABLE_NPC_FOLLOWERS = TRUE",
            "Only one follower NPC at a time (engine limit)",
            "follower remove = destroyfollowernpc macro",
        ],
    },
    "multi": {
        "name": "Multi Battle",
        "desc": "Scripted multi-battle (player + partner vs trainers).",
        "torscript": "multi 2v2 TRAINER_A TextA TRAINER_B TextB PARTNER_X",
        "fields": [
            "variant -- 2v2/2v1/2v2_fixed/2v1_fixed",
            "opponents -- TRAINER_* constants",
            "defeat text -- text labels for defeated trainers",
            "partner -- PARTNER_* constant for ally",
        ],
        "tips": [
            "Does not require follower system to be enabled",
            "2v2 = player+partner vs 2 trainers, 2v1 = vs 1 trainer",
            "'fixed' variants skip party selection (first 3 mons used)",
        ],
    },
    "give": {
        "name": "Give Item",
        "desc": "Give an item to the player with automatic bag-full safety check.",
        "torscript": "give ITEM_POTION 3",
        "fields": [
            "item -- item constant (ITEM_POTION, etc.)",
            "quantity -- how many to give (default 1)",
        ],
        "tips": [
            "Compiles to giveitem() + VAR_RESULT check + BagFull branch",
            "BagFull label auto-generated if not already defined",
            "Supports quantity: give ITEM_POTION 3 gives 3 potions",
        ],
    },
}

def _show_beat_help(beat_type_key):
    """Display a formatted help card for a single beat type."""
    entry = _BEAT_HELP.get(beat_type_key)
    if not entry:
        print(f"  No help available for this beat type.")
        input("  Press any key to return > ")
        return
    clear_screen()
    print(f"  {WHITE}TORCH -- Beat Help{RST}")
    print(BAR)
    print()
    print(f"  {GOLD}{entry['name']}{RST}  ({beat_type_key})")
    print()
    print(f"  {entry['desc']}")
    print()
    print(f"  {DIM}TorScript:{RST}  {CYAN}{entry['torscript']}{RST}")
    if entry["fields"]:
        print()
        print(f"  {DIM}Fields:{RST}")
        for field in entry["fields"]:
            print(f"    {field}")
    if entry["tips"]:
        print()
        print(f"  {DIM}Tips:{RST}")
        for tip in entry["tips"]:
            print(f"    {DIM}* {tip}{RST}")
    print()
    print(BAR)
    input("  Press any key to return > ")


def _show_category_summary(cat):
    """Display a quick-reference summary of all beat types in a category."""
    print()
    print(f"  {GOLD}{cat['name']}:{RST}")
    for _item_key, item_name, item_desc in cat["items"]:
        print(f"    {WHITE}{item_name:<14}{RST} {DIM}{item_desc}{RST}")
    print()
    input("  Press Enter to return > ")


# Map old single-key shortcuts to beat type names for direct access
_DIRECT_BEAT_KEYS = {
    "1": "msg", "2": "move", "3": "emote", "4": "fade",
    "5": "sound", "6": "pause", "7": "flag", "8": "battle",
    "9": "hide", "0": "show", "s": "setpos", "g": "flow",
    "p": "pory", "c": "comment", "l": "lock", "f": "faceplayer",
    "k": "special", "w": "waitstate", "i": "gotoif", "v": "var",
    "m": "music", "n": "fanfare", "y": "cry", "t": "shake",
    "b": "label",
}


def _prompt_give_beat(game_path):
    """Prompt for a give beat."""
    print()
    item = pick_item(game_path)
    if not item:
        return None
    while True:
        raw_qty = input("  Quantity [1] > ").strip()
        if not raw_qty:
            qty = "1"
            break
        if raw_qty.isdigit() and int(raw_qty) >= 1:
            qty = raw_qty
            break
        print(f"  {DIM}Enter a number >= 1, or press Enter for 1.{RST}")
    return {"type": "give", "data": {"item": item, "quantity": qty}}


def _dispatch_text_beat():
    """Prompt for a text block beat."""
    print()
    label = input("  Text label name > ").strip()
    if not label:
        return None
    content = input("  Text content > ").strip()
    if not content:
        return None
    if not content.endswith("$"):
        content += "$"
    return {"type": "text", "data": {"label": label, "content": content}}


def _dispatch_label_beat():
    """Prompt for a label beat."""
    print()
    name = input("  Label name > ").strip()
    if name:
        return {"type": "label", "data": {"name": name}}
    return None


def _dispatch_beat_type(beat_type, script_data, emotes_conf, textbox_warning,
                        map_name, project_dir, game_path, expansion_version=None,
                        proj_name=None):
    """Given a beat type name, run the appropriate prompt and return a beat dict or None."""
    _BEAT_DISPATCHERS = {
        "msg": lambda: _prompt_dialogue_beat(script_data, textbox_warning),
        "msgnpc": lambda: _prompt_dialogue_beat(script_data, textbox_warning, default_style="msgnpc"),
        "text": _dispatch_text_beat,
        "closemessage": lambda: {"type": "closemessage", "data": {}},
        "move": lambda: _prompt_move_beat(script_data, map_name, project_dir),
        "setpos": lambda: _prompt_setpos_beat(script_data),
        "hide": lambda: _prompt_hide_beat(script_data),
        "show": lambda: _prompt_show_beat(script_data),
        "faceplayer": lambda: {"type": "faceplayer", "data": {}},
        "emote": lambda: _prompt_emote_beat(script_data, emotes_conf),
        "shake": _prompt_shake_beat,
        "cry": lambda: _prompt_cry_beat(game_path),
        "fanfare": lambda: _prompt_fanfare_beat(game_path),
        "fade": _prompt_fade_beat,
        "sound": lambda: _prompt_sound_beat(game_path),
        "music": lambda: _prompt_music_beat(game_path),
        "pause": _prompt_pause_beat,
        "flag": lambda: _prompt_flag_beat(game_path, proj_name),
        "var": lambda: _prompt_var_beat(game_path),
        "gotoif": lambda: _prompt_gotoif_beat(game_path, script_data, map_name, project_dir, proj_name),
        "flow": lambda: _prompt_flow_beat(script_data, map_name, project_dir),
        "special": lambda: _prompt_special_beat(game_path),
        "waitstate": lambda: {"type": "waitstate", "data": {}},
        "battle": lambda: _prompt_battle_beat(script_data, map_name, game_path, expansion_version),
        "follower": lambda: _prompt_follower_beat(script_data, game_path, expansion_version),
        "multi": lambda: _prompt_multi_beat(script_data, map_name, game_path, expansion_version),
        "give": lambda: _prompt_give_beat(game_path),
        "lock": lambda: {"type": "lock", "data": {}},
        "label": _dispatch_label_beat,
        "pory": _prompt_pory_beat,
        "comment": _prompt_comment_beat,
    }
    handler = _BEAT_DISPATCHERS.get(beat_type)
    if handler:
        return handler()
    return None


def _category_sub_menu(cat, script_data, emotes_conf, textbox_warning,
                       map_name, project_dir, game_path, expansion_version,
                       proj_name=None):
    """Show a category sub-menu with per-beat help. Returns a beat dict or None."""
    while True:
        print()
        print(f"  {cat['name']}:")
        for item_key, item_name, item_desc in cat["items"]:
            print(f"    {GOLD}[{item_key}]{RST} {item_name:<14} {DIM}{item_desc}{RST}")
        print()
        print(f"    {GOLD}[?N]{RST} {DIM}help (e.g. ?1){RST}")
        print(f"    {GOLD}[q]{RST} back")
        print()
        sub = input("  > ").strip()
        if not sub or sub.lower() == "q":
            return None

        # Per-beat help: ?1, ?2, etc.
        if sub.startswith("?") and len(sub) > 1:
            help_key = sub[1:]
            for item_key, item_name, _item_desc in cat["items"]:
                if help_key == item_key:
                    _show_beat_help(item_name)
                    break
            continue

        # Find item in category
        for item_key, item_name, item_desc in cat["items"]:
            if sub == item_key:
                return _dispatch_beat_type(item_name, script_data, emotes_conf,
                                           textbox_warning, map_name, project_dir,
                                           game_path, expansion_version, proj_name)

        # Not found in sub-menu — re-show
        continue


def _add_beat_prompt(script_data, emotes_conf=None, textbox_warning=3,
                     map_name=None, project_dir=None, game_path=None,
                     expansion_version=None, proj_name=None):
    """Prompt user to create a new beat via categorized menu.

    Returns a beat dict, a list of beat dicts (from templates), or None.
    """
    while True:
        print()
        print("  Add beat:")
        for cat in _BEAT_CATEGORIES:
            print(f"    {GOLD}[{cat['key']}]{RST} {cat['name']:<12}", end="")
            if int(cat["key"]) % 3 == 0:
                print()
        print(f"    {GOLD}[7]{RST} {'Templates':<12}")
        print()
        print(f"    {GOLD}[:]{RST} {DIM}TorScript{RST}    {GOLD}[?]{RST} {DIM}help{RST}  {GOLD}[?N]{RST} {DIM}category help{RST}")
        print()
        print(f"    {GOLD}[q]{RST} cancel")
        print()
        choice = input("  > ").strip()
        if not choice:
            return None

        low = choice.lower()

        # Cancel
        if low == "q":
            return None

        # Help
        if low == "?":
            _script_help_screen()
            continue

        # Category help summary: ?1 through ?6
        if low.startswith("?") and len(low) > 1:
            cat_key = low[1:]
            for c in _BEAT_CATEGORIES:
                if c["key"] == cat_key:
                    _show_category_summary(c)
                    break
            continue

        # Templates
        if choice == "7":
            from torch.templates import run_template_wizard
            label = script_data.get("label", map_name or "Script")
            cast = script_data.get("cast")
            beats = run_template_wizard(game_path, map_name or "", label, cast)
            if beats:
                return beats
            continue

        # Quick TorScript at category level
        if choice.startswith(":"):
            torscript = choice[1:].strip()
            if torscript:
                beat = _parse_torscript_beat(torscript, script_data)
                if beat:
                    return beat
                print(f"  Could not parse: {torscript}")
                input("  Press Enter > ")
            continue

        # Direct-access: old single-key shortcuts bypass categories
        if low in _DIRECT_BEAT_KEYS:
            beat_type = _DIRECT_BEAT_KEYS[low]
            return _dispatch_beat_type(beat_type, script_data, emotes_conf,
                                       textbox_warning, map_name, project_dir,
                                       game_path, expansion_version, proj_name)

        # Category selection
        cat = None
        for c in _BEAT_CATEGORIES:
            if c["key"] == choice:
                cat = c
                break
        if not cat:
            return None

        # Sub-menu with per-beat help
        result = _category_sub_menu(cat, script_data, emotes_conf, textbox_warning,
                                     map_name, project_dir, game_path, expansion_version,
                                     proj_name)
        if result is not None:
            return result


def _get_actor_list(script_data):
    """Return list of actor names available in this scene."""
    cast = script_data.get("cast", {})
    actors = list(cast.keys()) + ["player"]
    return actors


def _pick_actor(script_data, prompt="Actor"):
    """Let user pick an actor from the cast. Returns name or None."""
    actors = _get_actor_list(script_data)
    print(f"  {prompt}:")
    for i, name in enumerate(actors, 1):
        nid = script_data.get("cast", {}).get(name, "")
        suffix = f" (npc{nid})" if nid else ""
        print(f"    [{i}] {name}{suffix}")
    print()
    raw = input(f"  {prompt} > ").strip()
    if not raw:
        return None
    # Accept number or name
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(actors):
            return actors[idx]
    except ValueError:
        if raw.lower() in [a.lower() for a in actors]:
            return raw.lower()
        # Allow freeform actor name
        return raw
    return None


def _dialogue_textbox_preview(text, textbox_warning=3):
    """Show a GBA textbox preview of dialogue text with box markers and char counts.

    Thin wrapper around textutils.textbox_preview.
    Returns (display_text, was_wrapped).
    """
    return _textbox_preview_impl(text, textbox_warning=textbox_warning)


def _prompt_dialogue_beat(script_data, textbox_warning=3, default_style=None):
    """Prompt for a dialogue beat with live GBA textbox preview."""
    print()
    print("  DIALOGUE EDITOR")
    print("  Use \\n for line break, \\p for new text box.")
    print("  Include a speaker prefix if needed: 'BUSTER: text here'")
    print("  GBA textbox: 38 chars/line, 2 lines/box.")
    print()

    while True:
        text = input("  Text > ").strip()
        if not text:
            return None

        print()
        wrapped_text, was_wrapped = _dialogue_textbox_preview(text, textbox_warning)
        print()

        if was_wrapped:
            print("  [y] Use auto-wrapped version")
            print("  [k] Keep original (no wrap)")
            print("  [r] Re-type")
            choice = input("  > ").strip().lower()
            if choice == "r":
                print()
                continue
            elif choice == "k":
                final_text = text
            else:
                final_text = wrapped_text
        else:
            print("  [y] Accept  [r] Re-type")
            choice = input("  > ").strip().lower()
            if choice == "r":
                print()
                continue
            final_text = text

        if default_style:
            style = default_style
        else:
            print()
            print("  Style:")
            print("    [1] msg (default \u2014 normal dialogue)")
            print("    [2] msgnpc (NPC trainer battle context)")
            style_choice = input("  Style [1] > ").strip()
            style = "msgnpc" if style_choice == "2" else "msg"
        return {"type": "dialogue", "data": {"text": final_text, "style": style}}


def _pick_direction(include_player=False):
    """Numbered direction picker. Returns direction string or None."""
    if include_player:
        print("  Direction:")
        print("    [1] up    [2] down   [3] left")
        print("    [4] right [5] player [6] away")
        dmap = {"1": "up", "2": "down", "3": "left",
                "4": "right", "5": "player", "6": "away"}
    else:
        print("  Direction:")
        print("    [1] up  [2] down  [3] left  [4] right")
        dmap = {"1": "up", "2": "down", "3": "left", "4": "right"}
    pick = input("  > ").strip().lower()
    return dmap.get(pick, pick if pick in dmap.values() else None)


def _prompt_move_beat(script_data, map_name=None, project_dir=None):
    """Prompt for a movement beat (face/walk/do, with optional parallel)."""
    print()
    print(f"  {DIM}Movement \u2014 type TorScript or press Enter for guided mode:{RST}")
    print(f"  {DIM}  e.g. buster walk up 3 / buster face player / buster do MyBlock{RST}")
    print(f"  {DIM}  parallel: buster walk up 3 + player face down{RST}")
    print()
    torscript = input("  > ").strip()
    if torscript:
        beat = _parse_torscript_beat(torscript, script_data)
        if beat and beat["type"] == "move":
            return beat
        # Might be an emote parsed from actor-first
        if beat:
            return beat
        print(f"  Could not parse as movement. Entering guided mode.")
        print()

    actions = []
    while True:
        print()
        actor = _pick_actor(script_data, "Actor")
        if not actor:
            break
        print()
        print("  Movement type:")
        print("    [1] face     [2] walk      [3] walkfast")
        print("    [4] walkslow [5] run       [6] slide")
        print("    [7] jump     [8] do (named block)")
        print()
        verb_choice = input("  Type > ").strip()
        verb_map = {"1": "face", "2": "walk", "3": "walkfast", "4": "walkslow",
                     "5": "run", "6": "slide", "7": "jump", "8": "do"}
        verb = verb_map.get(verb_choice, verb_choice)

        if verb == "face":
            direction = _pick_direction(include_player=True)
            if direction:
                actions.append({"actor": actor, "verb": "face", "direction": direction})
            else:
                print("  Invalid direction.")
                continue
        elif verb in WALK_COMMANDS:
            direction = _pick_direction()
            if not direction:
                print("  Invalid direction.")
                continue
            count = input("  Tiles > ").strip() or "1"
            actions.append({"actor": actor, "verb": verb, "direction": direction, "count": count})
        elif verb == "jump":
            direction = _pick_direction()
            if not direction:
                print("  Invalid direction.")
                continue
            count = input("  Tiles (1 or 2) > ").strip() or "1"
            actions.append({"actor": actor, "verb": "jump", "direction": direction, "count": count})
        elif verb == "do":
            label = None
            # Show existing blocks if we know the map
            if map_name and project_dir:
                setup_path = os.path.join(project_dir, map_name, "setup.pory")
                blocks = _parse_setup_movement_blocks(setup_path)
                if blocks:
                    print()
                    print("  Available movement blocks:")
                    for bi, blk in enumerate(blocks, 1):
                        step_count = len(blk["commands"])
                        print(f"    [{bi}] {blk['label']}  ({step_count} steps)")
                    print(f"    [t] Type label manually")
                    print()
                    pick = input("  Block > ").strip()
                    if pick.lower() == "t":
                        label = input("  Movement label > ").strip()
                    else:
                        try:
                            bi_idx = int(pick) - 1
                            if 0 <= bi_idx < len(blocks):
                                label = blocks[bi_idx]["label"]
                            else:
                                print("  Invalid number.")
                        except ValueError:
                            # Treat as a label name
                            if pick:
                                label = pick
                else:
                    label = input("  Movement label > ").strip()
            else:
                label = input("  Movement label > ").strip()
            if label:
                actions.append({"actor": actor, "verb": "do", "label": label})
        else:
            print(f"  Unknown verb '{verb}'.")
            continue

        add_more = input("  Add parallel action? [y/N] > ").strip().lower()
        if add_more != "y":
            break

    if not actions:
        return None
    return {"type": "move", "data": {"actions": actions}}


def _emote_picker(emotes_conf=None):
    """Show a numbered emote picker menu. Returns the emote TorScript or None."""
    # Build list: builtins + custom from config
    all_emotes = list(BUILTIN_EMOTES.keys())
    custom = {}
    if emotes_conf and os.path.exists(emotes_conf):
        with open(emotes_conf, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    if key not in BUILTIN_EMOTES:
                        custom[key] = val.strip()
    all_emotes += list(custom.keys())

    # Display menu
    print("  Emotes:")
    emote_display = {
        "!": "!  (exclamation)",
        "?": "?  (question)",
        "!!": "!! (double exclamation)",
        "x": "x  (angry)",
        "heart": "heart",
        "...": "... (thinking)",
    }
    for i, name in enumerate(all_emotes, 1):
        display = emote_display.get(name, name)
        marker = "" if name in BUILTIN_EMOTES else " (custom)"
        print(f"    [{i}] {display}{marker}")
    print()
    raw = input("  Emote (# or name) > ").strip()
    if not raw:
        return None
    # Accept by number
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(all_emotes):
            return all_emotes[idx]
    except ValueError:
        pass
    # Accept by name directly
    return raw


def _prompt_emote_beat(script_data, emotes_conf=None):
    """Prompt for an emote beat with emote picker."""
    print()
    actor = _pick_actor(script_data, "Actor")
    if not actor:
        return None
    print()
    emote = _emote_picker(emotes_conf)
    if not emote:
        return None
    return {"type": "emote", "data": {"actor": actor, "emote_name": emote}}


def _prompt_fade_beat():
    """Prompt for a fade beat via numbered menu."""
    _FADE_OPTIONS = [
        ("1", "black",      "Screen fades to black"),
        ("2", "in",         "Screen fades back in from black"),
        ("3", "white",      "Screen fades to white"),
        ("4", "from_white", "Screen fades in from white"),
    ]
    print()
    print("  Fade type:")
    for num, name, desc in _FADE_OPTIONS:
        print(f"    {GOLD}[{num}]{RST} {name:<14} {DIM}{desc}{RST}")
    print(f"    {GOLD}[q]{RST} {DIM}cancel{RST}")
    print()
    raw = input("  > ").strip().lower()
    if not raw or raw == "q":
        return None
    # Accept by number
    for num, name, _desc in _FADE_OPTIONS:
        if raw == num:
            return {"type": "fade", "data": {"fade_type": name}}
    # Accept by text (including legacy aliases)
    text_map = {name: name for _, name, _ in _FADE_OPTIONS}
    text_map["from white"] = "from_white"
    text_map["in white"] = "from_white"
    if raw in text_map:
        return {"type": "fade", "data": {"fade_type": text_map[raw]}}
    print(f"  Unknown fade type: {raw}")
    return None


def _prompt_sound_beat(game_path=None):
    """Prompt for a sound beat with search-and-pick wizard."""
    print()
    print(f"  {DIM}SE_ constant (e.g. SE_PIN) -- press [?] to search{RST}")
    constant = pick_sound(game_path) if game_path else input("  Sound constant (e.g. SE_EXIT) > ").strip()
    if not constant:
        return None
    return {"type": "sound", "data": {"constant": constant}}


def _prompt_pause_beat():
    """Prompt for a pause beat."""
    print()
    print("  Duration: (empty for default, 'long', or frame count)")
    dur = input("  Duration > ").strip()
    return {"type": "pause", "data": {"duration": dur}}


def _prompt_flag_beat(game_path=None, proj_name=None):
    """Prompt for a flag beat with search-and-pick wizard."""
    print()
    print("  [1] set  [2] clear")
    ac = input("  Action > ").strip()
    action = "clear" if ac == "2" else "set"
    print(f"  {DIM}FLAG_ constant (e.g. FLAG_BADGE01_GET) -- press [?] to search{RST}")
    flag_log = _load_flag_log(proj_name) if proj_name else None
    flag_name = pick_flag(game_path, flag_log) if game_path else input("  Flag constant > ").strip()
    if not flag_name:
        return None
    return {"type": "flag", "data": {"action": action, "flag_name": flag_name}}


def _prompt_battle_beat(script_data=None, map_name=None, game_path=None,
                        expansion_version=None):
    """Prompt for a battle beat — pick trainer, choose type from full catalogue."""
    from torch.battle_manager import BATTLE_TYPES, _available_battle_types
    print()
    print(f"  {DIM}TRAINER_ constant (e.g. TRAINER_RIVAL_1) -- press [?] to search{RST}")
    print()

    # Go straight to trainer picker
    trainer = pick_trainer(game_path) if game_path else input("  Trainer constant (e.g. TRAINER_MY_TRAINER_1) > ").strip()
    if not trainer:
        return None

    # Auto-detect map prefix from context
    map_prefix = map_name or ""
    if not map_prefix:
        map_prefix = input("  Map prefix for labels > ").strip()
        if not map_prefix:
            return None

    # Derive a clean stem from the trainer constant
    stem = trainer
    for prefix in ("TRAINER_ROCKET_", "TRAINER_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    stem = stem.title().replace("_", "")

    # Battle type picker
    print()
    available = _available_battle_types(expansion_version)
    print(f"  {DIM}Battle type:{RST}")
    print()
    for idx, (type_name, macro, min_ver, desc) in enumerate(available, 1):
        print(f"    {GOLD}[{idx}]{RST} {type_name:<35} {DIM}{desc}{RST}")
    print()
    while True:
        raw = input("  Type (number, or Enter for single) > ").strip()
        if not raw:
            chosen = available[0]
            break
        try:
            pick = int(raw)
            if 1 <= pick <= len(available):
                chosen = available[pick - 1]
                if chosen[2] is not None and expansion_version is not None and expansion_version < chosen[2]:
                    v = chosen[2]
                    print(f"  This battle type requires expansion v{v[0]}.{v[1]}.{v[2]}+.")
                    print()
                    continue
                break
        except ValueError:
            pass
        print(f"  Please enter a number 1-{len(available)}.")
        print()

    type_name, macro, _, desc = chosen
    battle_type = macro

    # Generate args based on type
    intro_label = f"{map_prefix}_{stem}_Intro"
    defeat_label = f"{map_prefix}_{stem}_Defeat"
    args_str = _build_battle_args(type_name, trainer, intro_label, defeat_label,
                                  map_prefix, stem)

    print()
    print(f"  Generated: {battle_type}({args_str})")
    print()
    print(f"  {GOLD}[Enter]{RST} {DIM}accept{RST}  {GOLD}[e]{RST} {DIM}edit args{RST}  {GOLD}[q]{RST} {DIM}cancel{RST}")
    print()
    choice = input("  > ").strip().lower()

    if choice == "q":
        return None

    if choice == "e":
        print()
        print(f"  {DIM}Enter args for {battle_type}(...){RST}")
        new_args = input("  Args > ").strip()
        if not new_args:
            return None
        args_str = new_args

    return {"type": "battle", "data": {"battle_type": battle_type, "args": args_str}}


def _build_battle_args(type_name, trainer, intro_label, defeat_label,
                       map_prefix, stem):
    """Build the args string for a battle beat based on its type name."""
    not_enough_label = f"{map_prefix}_NotEnoughMons"
    if type_name == "single":
        return f"{trainer}, {intro_label}, {defeat_label}"
    elif type_name == "double":
        return f"{trainer}, {intro_label}, {defeat_label}, {not_enough_label}"
    elif type_name in ("continue_script", "continue_script_no_music"):
        return f"{trainer}, {intro_label}, {defeat_label}"
    elif type_name == "single_no_intro":
        return f"{trainer}, {defeat_label}"
    elif type_name == "rematch":
        return f"{trainer}, {intro_label}, {defeat_label}"
    elif type_name in ("continue_script_double", "continue_script_double_no_music"):
        return f"{trainer}, {intro_label}, {defeat_label}, {not_enough_label}"
    elif type_name == "rematch_double":
        return f"{trainer}, {intro_label}, {defeat_label}, {not_enough_label}"
    elif type_name == "two_trainers":
        return f"{trainer}, {defeat_label}, {trainer}, {defeat_label}"
    return f"{trainer}, {intro_label}, {defeat_label}"


def _prompt_follower_add(game_path):
    """Sub-prompt for the 'add follower' action. Returns beat dict or None."""
    from torch.battle_partners import pick_partner, _check_follower_config

    # Check config toggle first
    if game_path and not _check_follower_config(game_path):
        return None

    print()
    print("  Source:")
    print(f"    {GOLD}[1]{RST} Existing NPC on this map (setfollowernpc)")
    print(f"    {GOLD}[2]{RST} Dynamic spawn (createfollowernpc)")
    print()
    src = input("  > ").strip()
    if src == "2":
        source = "dynamic"
        print()
        gfx = input("  Object GFX (e.g. OBJ_EVENT_GFX_SABRINA): ").strip()
        if not gfx:
            return None
        source_id = gfx
    else:
        source = "local"
        print()
        local_id = input("  Local ID (e.g. LOCALID_SABRINA): ").strip()
        if not local_id:
            return None
        source_id = local_id

    # Partner picker
    partner = pick_partner(game_path) if game_path else input("  Partner constant > ").strip()
    if not partner:
        return None

    # Flags
    print()
    print("  Behavior flags:")
    print(f"    {GOLD}[1]{RST} All (bike, surf, fly, whiteout)  (Recommended)")
    print(f"    {GOLD}[2]{RST} Land only (bike, fly)")
    print(f"    {GOLD}[3]{RST} Custom")
    print()
    flag_choice = input("  Flags [1] > ").strip()
    if flag_choice == "2":
        flags = "FNPC_ALL_LAND"
    elif flag_choice == "3":
        flags = input("  Custom flags: ").strip() or "FNPC_ALL"
    else:
        flags = "FNPC_ALL"

    raw_args = f"add {source} {source_id} {partner} {flags}"
    return {"type": "follower", "data": {"action": "add", "raw_args": raw_args}}


def _prompt_follower_beat(script_data=None, game_path=None, expansion_version=None):
    """Prompt for NPC follower beat."""
    from torch.expansion_compat import requires_version, FOLLOWER_NPC_PARTNERS
    from torch.battle_partners import pick_partner

    # Version gate
    if expansion_version is not None and not requires_version(expansion_version, FOLLOWER_NPC_PARTNERS):
        print()
        print(f"  Follower NPCs require expansion v1.12.0+.")
        print(f"  Your version: {expansion_version[0]}.{expansion_version[1]}.{expansion_version[2]}")
        input("  Press Enter > ")
        return None

    print()
    print("  FOLLOWER NPC")
    print()
    print(f"    {GOLD}[1]{RST} Add follower")
    print(f"    {GOLD}[2]{RST} Remove follower")
    print(f"    {GOLD}[3]{RST} Face follower")
    print(f"    {GOLD}[4]{RST} Hide follower")
    print(f"    {GOLD}[5]{RST} Check follower")
    print(f"    {GOLD}[6]{RST} Change partner")
    print()
    action_choice = input("  Action > ").strip()

    if action_choice == "1":
        return _prompt_follower_add(game_path)

    elif action_choice == "2":
        return {"type": "follower", "data": {"action": "remove", "raw_args": "remove"}}

    elif action_choice == "3":
        return {"type": "follower", "data": {"action": "face", "raw_args": "face"}}

    elif action_choice == "4":
        print()
        speed = input("  Walk speed (Enter for default): ").strip()
        if speed:
            raw_args = f"hide {speed}"
        else:
            raw_args = "hide"
        return {"type": "follower", "data": {"action": "hide", "raw_args": raw_args}}

    elif action_choice == "5":
        return {"type": "follower", "data": {"action": "check", "raw_args": "check"}}

    elif action_choice == "6":
        partner = pick_partner(game_path) if game_path else input("  Partner constant > ").strip()
        if not partner:
            return None
        raw_args = f"change {partner}"
        return {"type": "follower", "data": {"action": "change", "raw_args": raw_args}}

    return None


def _pick_multi_opponent(label, game_path, map_prefix):
    """Pick an opponent trainer and defeat text label for multi-battle.

    Returns: (trainer_const, defeat_label) or (None, None) on cancel.
    """
    print()
    trainer = pick_trainer(game_path) if game_path else input(f"  {label} constant > ").strip()
    if not trainer:
        return None, None

    stem = trainer
    for pfx in ("TRAINER_ROCKET_", "TRAINER_"):
        if stem.startswith(pfx):
            stem = stem[len(pfx):]
            break
    stem = stem.title().replace("_", "")
    defeat = f"{map_prefix}_{stem}_Defeat" if map_prefix else f"Text_{stem}Defeat"
    print(f"  Defeat text [{defeat}]: ", end="")
    custom = input().strip()
    if custom:
        defeat = custom
    return trainer, defeat


def _prompt_multi_beat(script_data=None, map_name=None, game_path=None,
                       expansion_version=None):
    """Prompt for scripted multi-battle."""
    from torch.battle_partners import pick_partner

    print()
    print("  MULTI BATTLE SETUP")
    print()
    print(f"    {GOLD}[1]{RST} 2 vs 2 (player+partner vs 2 trainers)  (Recommended)")
    print(f"    {GOLD}[2]{RST} 2 vs 1 (player+partner vs 1 trainer)")
    print(f"    {GOLD}[3]{RST} 2 vs 2 fixed (no mon selection)")
    print(f"    {GOLD}[4]{RST} 2 vs 1 fixed (no mon selection)")
    print()
    variant_choice = input("  Format > ").strip()

    variant_map = {"1": "2v2", "2": "2v1", "3": "2v2_fixed", "4": "2v1_fixed"}
    variant = variant_map.get(variant_choice, "2v2")

    map_prefix = map_name or ""
    is_2v2 = variant in ("2v2", "2v2_fixed")

    trainer_a, defeat_a = _pick_multi_opponent("Opponent A", game_path, map_prefix)
    if not trainer_a:
        return None

    if is_2v2:
        trainer_b, defeat_b = _pick_multi_opponent("Opponent B", game_path, map_prefix)
        if not trainer_b:
            return None

    # Partner
    print()
    partner = pick_partner(game_path) if game_path else input("  Partner constant > ").strip()
    if not partner:
        return None

    # Build args
    if is_2v2:
        raw_args = f"{variant} {trainer_a} {defeat_a} {trainer_b} {defeat_b} {partner}"
    else:
        raw_args = f"{variant} {trainer_a} {defeat_a} {partner}"

    return {"type": "multi", "data": {"variant": variant, "raw_args": raw_args}}


def _prompt_hide_beat(script_data):
    """Prompt for a hide beat."""
    print()
    actor = _pick_actor(script_data, "Actor to hide")
    if not actor:
        return None
    return {"type": "hide", "data": {"actor": actor}}


def _prompt_show_beat(script_data):
    """Prompt for a show beat."""
    print()
    actor = _pick_actor(script_data, "Actor to show")
    if not actor:
        return None
    return {"type": "show", "data": {"actor": actor}}


def _prompt_setpos_beat(script_data):
    """Prompt for a setpos beat."""
    print()
    actor = _pick_actor(script_data, "Actor")
    if not actor:
        return None
    x = input("  X coordinate > ").strip()
    y = input("  Y coordinate > ").strip()
    if not x or not y:
        return None
    return {"type": "setpos", "data": {"actor": actor, "x": x, "y": y}}


def _prompt_flow_beat(script_data=None, map_name=None, project_dir=None):
    """Prompt for a flow/control beat with label picker."""
    print()
    print(f"  {DIM}Control script flow. goto/call jump to another label; end/release stop.{RST}")
    print("  [1] goto  [2] call  [3] end  [4] release  [5] return")
    fc = input("  Type > ").strip()
    flow_map = {"1": "goto", "2": "call", "3": "end", "4": "release", "5": "return"}
    flow_type = flow_map.get(fc)
    if not flow_type:
        return None
    if flow_type in ("goto", "call"):
        if script_data:
            target = _pick_label(script_data, map_name, project_dir)
        else:
            target = input("  Target label > ").strip()
        if not target:
            return None
        return {"type": "flow", "data": {"flow_type": flow_type, "target": target}}
    return {"type": "flow", "data": {"flow_type": flow_type}}


def _prompt_special_beat(game_path=None):
    """Prompt for a special beat with search-and-pick wizard."""
    print()
    print(f"  {DIM}Special function name (e.g. HealPlayerParty) -- press [?] to search{RST}")
    func = pick_special(game_path) if game_path else input("  Special function name > ").strip()
    if func:
        return {"type": "special", "data": {"function": func}}
    return None


def _prompt_gotoif_beat(game_path=None, script_data=None, map_name=None, project_dir=None,
                        proj_name=None):
    """Prompt for a gotoif beat with flag picker + label picker."""
    print()
    print(f"  {DIM}Conditional jump: if a flag is set, skip to a label.{RST}")
    print(f"  {DIM}Step 1: FLAG_ constant for condition -- press [?] to search{RST}")
    flag_log = _load_flag_log(proj_name) if proj_name else None
    flag = pick_flag(game_path, flag_log) if game_path else input("  Flag constant > ").strip()
    if not flag:
        return None
    print(f"  {DIM}Step 2: Pick the label to jump to if the flag is set.{RST}")
    if script_data:
        target = _pick_label(script_data, map_name, project_dir)
    else:
        target = input("  Target label > ").strip()
    if not target:
        return None
    return {"type": "gotoif", "data": {"flag": flag, "target": target}}


def _prompt_var_beat(game_path=None):
    """Prompt for a var beat with search-and-pick wizard."""
    print()
    print(f"  {DIM}VAR_ constant (e.g. VAR_TEMP_1) -- press [?] to search{RST}")
    var_name = pick_var(game_path) if game_path else input("  Variable name > ").strip()
    if not var_name:
        return None
    print(f"  {DIM}Numeric value to assign (e.g. 1, 0, 5).{RST}")
    value = input("  Value > ").strip()
    if not value:
        return None
    return {"type": "var", "data": {"var_name": var_name, "value": value}}


def _prompt_music_beat(game_path=None):
    """Prompt for a music beat with search-and-pick wizard."""
    print()
    print(f"  {DIM}MUS_ constant (e.g. MUS_PETALBURG) -- press [?] to search{RST}")
    constant = pick_music(game_path) if game_path else input("  Music constant (e.g. MUS_ROUTE101) > ").strip()
    if not constant:
        return None
    return {"type": "music", "data": {"constant": constant}}


def _prompt_fanfare_beat(game_path=None):
    """Prompt for a fanfare beat with search-and-pick wizard."""
    print()
    print(f"  {DIM}MUS_ constant (e.g. MUS_OBTAIN_ITEM) -- press [?] to search{RST}")
    constant = pick_fanfare(game_path) if game_path else input("  Fanfare constant > ").strip()
    if not constant:
        return None
    return {"type": "fanfare", "data": {"constant": constant}}


def _prompt_cry_beat(game_path=None):
    """Prompt for a cry beat with species search-and-pick wizard."""
    print()
    print(f"  {DIM}SPECIES_ constant (e.g. SPECIES_PIKACHU) -- press [?] to search{RST}")
    species = pick_species(game_path) if game_path else input("  Species constant (e.g. SPECIES_KOFFING) > ").strip()
    if not species:
        return None
    return {"type": "cry", "data": {"species": species}}


def _prompt_shake_beat():
    """Prompt for a camera shake beat with sensible defaults."""
    print()
    print("  Camera shake intensity (1=light, 3=medium, 5=heavy)")
    intensity = input("  Intensity [3] > ").strip() or "3"
    count = input("  Count [2] > ").strip() or "2"
    return {"type": "shake", "data": {"intensity": intensity, "count": count}}


def _prompt_pory_beat():
    """Prompt for a raw pory passthrough beat."""
    print()
    print("  Enter a raw Poryscript line (e.g. 'release', 'end', 'lock').")
    raw = input("  > ").strip()
    if not raw:
        return None
    return {"type": "pory", "data": {"raw_line": raw}}


def _prompt_comment_beat():
    """Prompt for a remark/comment beat (shows as [REM] in the editor)."""
    print()
    print("  Add a remark \u2014 a note to yourself that doesn't appear in the game.")
    print("  Useful for organising your scene (e.g. '--- BATTLE PHASE ---').")
    print()
    text = input("  Remark > ").strip()
    if not text:
        return None
    return {"type": "comment", "data": {"text": text}}


def _parse_ts_msg(stripped, tokens, script_data):
    cmd = tokens[0]
    style = "msgnpc" if cmd == "msgnpc" else "msg"
    m = re.match(rf'^{cmd}\s+"(.*)"$', stripped)
    if m:
        text = m.group(1)
        if text.endswith("$"):
            text = text[:-1]
        return {"type": "dialogue", "data": {"text": text, "style": style}}
    rest = stripped[len(cmd):].strip()
    if rest:
        if rest.endswith("$"):
            rest = rest[:-1]
        return {"type": "dialogue", "data": {"text": rest, "style": style}}
    return None


def _parse_ts_fade(stripped, tokens, script_data):
    fade_type = " ".join(tokens[1:])
    if fade_type:
        return {"type": "fade", "data": {"fade_type": fade_type}}
    return None


def _parse_ts_constant(beat_type, key):
    def parser(stripped, tokens, script_data):
        if len(tokens) >= 2:
            return {"type": beat_type, "data": {key: tokens[1]}}
        return None
    return parser


def _parse_ts_shake(stripped, tokens, script_data):
    if len(tokens) >= 2:
        intensity = tokens[1]
        count = tokens[2] if len(tokens) >= 3 else "2"
        return {"type": "shake", "data": {"intensity": intensity, "count": count}}
    return None


def _parse_ts_pause(stripped, tokens, script_data):
    dur = tokens[1] if len(tokens) >= 2 else "16"
    return {"type": "pause", "data": {"duration": dur}}


def _parse_ts_flag(stripped, tokens, script_data):
    if len(tokens) >= 3:
        return {"type": "flag", "data": {"action": tokens[1], "flag_name": tokens[2]}}
    return None


def _parse_ts_hide(stripped, tokens, script_data):
    if len(tokens) >= 2:
        return {"type": "hide", "data": {"actor": tokens[1]}}
    return None


def _parse_ts_show(stripped, tokens, script_data):
    if len(tokens) >= 2:
        return {"type": "show", "data": {"actor": tokens[1]}}
    return None


def _parse_ts_setpos(stripped, tokens, script_data):
    if len(tokens) >= 4:
        return {"type": "setpos", "data": {"actor": tokens[1], "x": tokens[2], "y": tokens[3]}}
    return None


def _parse_ts_flow_target(flow_type):
    def parser(stripped, tokens, script_data):
        if len(tokens) >= 2:
            return {"type": "flow", "data": {"flow_type": flow_type, "target": tokens[1]}}
        return None
    return parser


def _parse_ts_simple(beat_type):
    def parser(stripped, tokens, script_data):
        return {"type": beat_type, "data": {}}
    return parser


def _parse_ts_flow_simple(stripped, tokens, script_data):
    return {"type": "flow", "data": {"flow_type": tokens[0]}}


def _parse_ts_gotoif(stripped, tokens, script_data):
    if len(tokens) >= 3:
        return {"type": "gotoif", "data": {"flag": tokens[1], "target": tokens[2]}}
    return None


def _parse_ts_pory(stripped, tokens, script_data):
    return {"type": "pory", "data": {"raw_line": stripped[5:].strip()}}


_TORSCRIPT_PARSERS = {
    "msg": _parse_ts_msg,
    "msgnpc": _parse_ts_msg,
    "fade": _parse_ts_fade,
    "sound": _parse_ts_constant("sound", "constant"),
    "music": _parse_ts_constant("music", "constant"),
    "fanfare": _parse_ts_constant("fanfare", "constant"),
    "cry": _parse_ts_constant("cry", "species"),
    "shake": _parse_ts_shake,
    "pause": _parse_ts_pause,
    "flag": _parse_ts_flag,
    "hide": _parse_ts_hide,
    "remove": _parse_ts_hide,
    "show": _parse_ts_show,
    "add": _parse_ts_show,
    "setpos": _parse_ts_setpos,
    "goto": _parse_ts_flow_target("goto"),
    "call": _parse_ts_flow_target("call"),
    "end": _parse_ts_flow_simple,
    "release": _parse_ts_flow_simple,
    "return": _parse_ts_flow_simple,
    "lock": _parse_ts_simple("lock"),
    "faceplayer": _parse_ts_simple("faceplayer"),
    "closemessage": _parse_ts_simple("closemessage"),
    "gotoif": _parse_ts_gotoif,
    "pory": _parse_ts_pory,
}


def _parse_ts_actor_segment(seg, segments_count):
    """Parse a single actor segment from a movement/emote TorScript line."""
    seg_tokens = seg.split()
    actor = seg_tokens[0]
    action_parts = seg_tokens[1:] if len(seg_tokens) > 1 else []
    if not action_parts:
        return None, None
    verb = action_parts[0]
    if verb == "emote" and len(action_parts) >= 2:
        emote_name = action_parts[1]
        if segments_count == 1:
            return "emote_beat", {"type": "emote", "data": {"actor": actor, "emote_name": emote_name}}
        return "action", {"actor": actor, "verb": "emote", "emote_name": emote_name}
    if verb == "face" and len(action_parts) >= 2:
        return "action", {"actor": actor, "verb": "face", "direction": action_parts[1]}
    if verb in WALK_COMMANDS and len(action_parts) >= 3:
        return "action", {"actor": actor, "verb": verb, "direction": action_parts[1], "count": action_parts[2]}
    if verb in WALK_COMMANDS and len(action_parts) >= 2:
        return "action", {"actor": actor, "verb": verb, "direction": action_parts[1], "count": "1"}
    if verb == "jump" and len(action_parts) >= 2:
        count = action_parts[2] if len(action_parts) >= 3 else "1"
        return "action", {"actor": actor, "verb": "jump", "direction": action_parts[1], "count": count}
    if verb == "do" and len(action_parts) >= 2:
        return "action", {"actor": actor, "verb": "do", "label": action_parts[1]}
    return "action", {"actor": actor, "verb": verb, "raw": seg}


def _parse_torscript_beat(line, script_data):
    """
    Parse a single TorScript line into a beat dict.
    Used for quick-entry in the editor (: prefix).
    Returns a beat dict or None if parsing fails.
    """
    stripped = line.strip()
    if not stripped:
        return None

    tokens = stripped.split()
    cmd = tokens[0]
    cast = script_data.get("cast", {})
    known_actors = set(cast.keys()) | {"player"}

    # Command-first dispatch
    parser = _TORSCRIPT_PARSERS.get(cmd)
    if parser:
        return parser(stripped, tokens, script_data)

    # --- # comment ---
    if cmd.startswith("#"):
        return {"type": "comment", "data": {"text": stripped[1:].strip()}}

    # --- Actor-first lines (movement/emote) ---
    is_actor = cmd in known_actors or re.match(r"^npc\d+$", cmd)
    if is_actor:
        segments = [s.strip() for s in stripped.split("+")]
        actions = []
        for seg in segments:
            kind, result = _parse_ts_actor_segment(seg, len(segments))
            if kind == "emote_beat":
                return result
            if kind == "action" and result:
                actions.append(result)
        if actions:
            return {"type": "move", "data": {"actions": actions}}

    return None


def _handle_quit(script_data, filepath, dirty, map_name, project_dir, game_path,
                 emotes_conf, source_display, settings):
    """Handle quit command. Returns (action, dirty) where action is 'quit', 'stay', or 'continue'."""
    if not dirty:
        return "quit", dirty
    print()
    print("  You have unsaved changes.")
    print()
    print("  [0] Don't quit \u2014 go back to editor")
    print("  [1] Save and quit")
    print("  [2] Save, rebuild and quit")
    print("  [3] Quit without saving")
    print()
    qc = input("  > ").strip()
    if qc == "0" or not qc:
        return "continue", dirty
    if qc == "1":
        output = _serialize_script(script_data)
        with open(filepath, "w") as f:
            f.write(output)
        print(f"  Saved: {os.path.basename(filepath)}")
        # Auto-sync to game folder
        ensure_synced(map_name, project_dir, game_path, emotes_conf,
                      source_display,
                      settings.get("max_snapshots", 10) if settings else 10)
        return "quit", False
    if qc == "2":
        output = _serialize_script(script_data)
        with open(filepath, "w") as f:
            f.write(output)
        print(f"  Saved: {os.path.basename(filepath)}")
        print()
        sync_map(map_name, project_dir, game_path, emotes_conf,
                 source_display, settings["max_snapshots"])
        print()
        _offer_build(game_path)
        return "quit", False
    if qc == "3":
        return "quit", dirty
    return "continue", dirty


# ── Flag log ─────────────────────────────────────────────────────────────

_FLAG_LOG_DIR = os.path.join(os.path.expanduser("~"), ".config", "torch")


def _load_flag_log(proj_name):
    """Load flags.json for this project. Returns dict {flag: script_name}."""
    if not proj_name:
        return {}
    path = os.path.join(_FLAG_LOG_DIR, proj_name, "flags.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_flag_log(proj_name, log):
    """Write flags.json for this project."""
    if not proj_name:
        return
    proj_dir = os.path.join(_FLAG_LOG_DIR, proj_name)
    os.makedirs(proj_dir, exist_ok=True)
    path = os.path.join(proj_dir, "flags.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, sort_keys=True)


def _log_flag(proj_name, flag_const, script_name):
    """Record a flag assignment in the project flag log."""
    if not proj_name or not flag_const:
        return
    log = _load_flag_log(proj_name)
    log[flag_const] = script_name
    _save_flag_log(proj_name, log)


def _log_script_flags(script_data, proj_name, filepath):
    """Scan all beats for flag constants and log them for this scene."""
    if not proj_name:
        return
    script_name = os.path.splitext(os.path.basename(filepath))[0]
    log = _load_flag_log(proj_name)
    changed = False
    for beat in script_data.get("beats", []):
        btype = beat.get("type")
        if btype == "flag":
            flag = beat.get("data", {}).get("flag_name", "")
            if flag and log.get(flag) != script_name:
                log[flag] = script_name
                changed = True
        elif btype == "gotoif":
            flag = beat.get("data", {}).get("flag", "")
            if flag and flag not in log:
                log[flag] = script_name
                changed = True
    if changed:
        _save_flag_log(proj_name, log)


def _validate_script_constants(script_data, game_path):
    """Scan all beats for constant references and check they exist.

    Returns list of warning strings (empty = all good).
    """
    if not game_path:
        return []

    warnings = []
    # Map beat types to (data_key, header_subpath, label)
    checks = {
        "flag":    ("flag_name", os.path.join("include", "constants", "flags.h"), "flags.h"),
        "gotoif":  ("flag",     os.path.join("include", "constants", "flags.h"), "flags.h"),
        "var":     ("var_name", os.path.join("include", "constants", "vars.h"), "vars.h"),
        "battle":  ("trainer",  os.path.join("include", "constants", "opponents.h"), "opponents.h"),
        "cry":     ("species",  os.path.join("include", "constants", "species.h"), "species.h"),
        "special": ("function", os.path.join("data", "specials.inc"), "specials.inc"),
    }

    # Cache file contents so we only read each file once
    file_cache = {}

    for idx, beat in enumerate(script_data.get("beats", []), 1):
        btype = beat.get("type")
        if btype not in checks:
            continue
        data_key, header_rel, file_label = checks[btype]
        constant = beat.get("data", {}).get(data_key, "")
        if not constant:
            continue

        if header_rel not in file_cache:
            hpath = os.path.join(game_path, header_rel)
            try:
                with open(hpath, encoding="utf-8", errors="replace") as f:
                    file_cache[header_rel] = f.read()
            except OSError:
                file_cache[header_rel] = None

        contents = file_cache[header_rel]
        if contents is None:
            continue  # can't read file, skip silently
        if constant not in contents:
            warnings.append(f"{constant} not found in {file_label} (used in beat #{idx})")

    return warnings


def _show_vim_primer(settings):
    """Show a one-time vim quick-start guide. Returns True if dismissed permanently."""
    if settings.get("vim_help_dismissed", False):
        return False

    clear_screen()
    print(BAR)
    print(f"   {WHITE}VIM QUICK START{RST}")
    print(BAR)
    print()
    print(f"  You're about to edit your scene in {WHITE}vim{RST}, a text editor.")
    print(f"  Here's everything you need to know:")
    print()
    print(f"  {GOLD}i{RST}         Start typing (enters insert mode)")
    print(f"  {GOLD}Esc{RST}       Stop typing (back to command mode)")
    print(f"  {GOLD}:w Enter{RST}   Save your changes")
    print(f"  {GOLD}:q Enter{RST}   Quit back to TORCH")
    print(f"  {GOLD}:wq Enter{RST}  Save and quit (both at once)")
    print()
    print(f"  {DIM}Use arrow keys to move around. That's it.{RST}")
    print(f"  {DIM}If you break something, TORCH will catch it and let you fix it.{RST}")
    print()

    try:
        raw = input(f"  {DIM}Enter = continue   |   type {RST}{GOLD}skip{RST}{DIM} = don't show this again{RST}  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if raw == "skip":
        settings["vim_help_dismissed"] = True
        # Persist the setting
        try:
            from torch.config import load_config, save_config
            cfg = load_config()
            if cfg:
                _ws, projects, saved_settings = cfg
                saved_settings["vim_help_dismissed"] = True
                ws_parent = os.path.dirname(_ws)
                save_config(ws_parent, projects, saved_settings)
        except Exception:
            pass  # setting still works for this session
        return True

    return False


def _validate_poryscript(pory_content, game_path):
    """Run the Poryscript compiler on generated .pory content.

    Returns list of error strings, or empty list if valid.
    Silently skips if compiler not found (not all setups have it).
    """
    if not game_path or not pory_content:
        return []
    compiler = os.path.join(game_path, "tools", "poryscript", "poryscript")
    if not os.path.isfile(compiler):
        return []

    import tempfile
    tmp_pory = None
    tmp_inc = None
    try:
        # Write pory content to a temp file
        tmp_fd, tmp_pory = tempfile.mkstemp(suffix=".pory")
        os.close(tmp_fd)
        with open(tmp_pory, "w") as f:
            f.write(pory_content)

        tmp_inc = tmp_pory.replace(".pory", ".inc")
        cmd = [compiler, "-i", tmp_pory, "-o", tmp_inc]
        font_cfg = os.path.join(game_path, "font_config.json")
        if os.path.isfile(font_cfg):
            cmd.extend(["-fc", font_cfg])

        result = subprocess.run(cmd, cwd=game_path, capture_output=True,
                                text=True, timeout=30)
        if result.returncode != 0:
            errors = []
            for line in (result.stderr or result.stdout or "").strip().split("\n"):
                line = line.strip()
                if line:
                    # Strip temp file path for cleaner display
                    line = line.replace(tmp_pory, "<scene>")
                    errors.append(line)
            return errors if errors else ["Poryscript compilation failed"]
        return []
    except (OSError, subprocess.TimeoutExpired):
        return []
    finally:
        if tmp_pory and os.path.exists(tmp_pory):
            os.unlink(tmp_pory)
        if tmp_inc and os.path.exists(tmp_inc):
            os.unlink(tmp_inc)


def _handle_vim_edit(script_data, filepath, emotes_conf, map_name,
                     game_path=None, settings=None):
    """Open scene in vim with tagged TorScript and validation loop.

    Shows [TAG] prefixes on beat lines for visual structure.
    Strips tags before re-parsing. Validates TorScript compilation
    and optionally Poryscript compilation. Returns (new_script_data, changed).
    """
    if settings is None:
        settings = {}
    if not shutil.which("vim"):
        print(f"\n  {DIM}vim is not installed on this system.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return script_data, False

    # Show one-time vim primer
    _show_vim_primer(settings)

    # Save current state as backup (clean TorScript, no tags)
    backup = _serialize_script(script_data)

    # Write tagged version for vim
    tagged = _serialize_script_tagged(script_data)
    with open(filepath, "w") as f:
        f.write(tagged)

    old_mtime = os.path.getmtime(filepath)

    # Open vim
    try:
        subprocess.call(["vim", filepath])
    except OSError as e:
        print(f"\n  {DIM}Could not open vim: {e}{RST}")
        # Restore clean version
        with open(filepath, "w") as f:
            f.write(backup)
        input(f"  {DIM}Press Enter{RST} > ")
        return script_data, False

    # Check if file was modified
    new_mtime = os.path.getmtime(filepath)
    if new_mtime == old_mtime:
        # No changes — restore clean version
        with open(filepath, "w") as f:
            f.write(backup)
        return script_data, False

    # Validation loop — strip tags, parse, compile
    label = script_data.get("label") or os.path.splitext(os.path.basename(filepath))[0]
    while True:
        # Read whatever vim left, strip tags, write clean version for parsing
        try:
            with open(filepath, "r") as f:
                raw = f.read()
            clean = _strip_tags(raw)
            with open(filepath, "w") as f:
                f.write(clean)
        except OSError as e:
            print(f"\n  {BOLD_RED}FILE ERROR:{RST} {e}")
            with open(filepath, "w") as f:
                f.write(backup)
            return script_data, False

        # Try parsing
        try:
            new_data = _parse_script(filepath, emotes_conf)
        except Exception as e:
            print(f"\n  {BOLD_RED}PARSE ERROR:{RST} {e}")
            if _vim_retry_or_discard(filepath, raw):
                continue
            with open(filepath, "w") as f:
                f.write(backup)
            return script_data, False

        # Try TorScript compilation
        pory_output, errors = compile_script(filepath, label, emotes_conf)
        if errors:
            print(f"\n  {BOLD_RED}COMPILE ERRORS:{RST}")
            for err in errors:
                print(f"    {err}")
            if _vim_retry_or_discard(filepath, raw):
                continue
            with open(filepath, "w") as f:
                f.write(backup)
            return script_data, False

        # Try Poryscript compilation (catches bad pory beats)
        pory_errors = _validate_poryscript(pory_output, game_path)
        if pory_errors:
            print(f"\n  {BOLD_RED}PORYSCRIPT ERRORS:{RST}")
            for err in pory_errors:
                print(f"    {err}")
            if _vim_retry_or_discard(filepath, raw):
                continue
            with open(filepath, "w") as f:
                f.write(backup)
            return script_data, False

        # All checks passed — file already has clean content on disk
        return new_data, True


def _vim_retry_or_discard(filepath, last_raw):
    """Offer vim retry or discard after validation error.

    Writes the user's last edit back to disk for re-editing.
    Returns True to retry, False to discard.
    """
    choice = input(f"\n  {_k('v')}{DIM} back to vim{RST}  {_k('q')}{DIM} discard changes{RST}  > ").strip().lower()
    if choice == "v":
        # Restore user's last edit (may still have tags, that's fine)
        try:
            with open(filepath, "w") as f:
                f.write(last_raw)
            subprocess.call(["vim", filepath])
        except OSError:
            pass
        return True
    return False


def _handle_save(script_data, filepath, game_path=None, proj_name=None,
                 map_name=None, project_dir=None, emotes_conf=None,
                 source_display=None, settings=None):
    """Save the scene file and auto-sync. Returns new dirty state."""
    # Validate constants if game path available
    if game_path:
        warnings = _validate_script_constants(script_data, game_path)
        if warnings:
            print()
            print(f"  {GOLD}Validation warnings:{RST}")
            for w in warnings:
                print(f"  {DIM}- {w}{RST}")
            print()

    output = _serialize_script(script_data)
    with open(filepath, "w") as f:
        f.write(output)
    print(f"  Saved: {os.path.basename(filepath)}")

    # Log flag assignments
    _log_script_flags(script_data, proj_name, filepath)

    # Auto-sync to game folder
    if map_name and project_dir and emotes_conf and source_display:
        max_snap = settings.get("max_snapshots", 10) if settings else 10
        ensure_synced(map_name, project_dir, game_path, emotes_conf,
                      source_display, max_snap)

    input("  Press Enter > ")
    return False


def _handle_save_sync(script_data, filepath, map_name, project_dir, game_path,
                      emotes_conf, source_display, settings):
    """Save + sync + offer build. Returns new dirty state."""
    output = _serialize_script(script_data)
    with open(filepath, "w") as f:
        f.write(output)
    print(f"  Saved: {os.path.basename(filepath)}")
    print()
    sync_map(map_name, project_dir, game_path, emotes_conf, source_display,
             settings["max_snapshots"])
    print()
    _offer_build(game_path)
    return False


def _handle_label_rename(script_data, beats):
    """Handle label rename. Returns True if scene was modified."""
    print()
    current_labels = script_data.get("labels", [])
    if current_labels:
        print(f"  Current labels: {', '.join(current_labels)}")
    new_label = input("  New primary label > ").strip()
    if new_label:
        for b in beats:
            if b["type"] == "label":
                old = b["data"]["name"]
                b["data"]["name"] = new_label
                if old in script_data.get("labels", []):
                    idx = script_data["labels"].index(old)
                    script_data["labels"][idx] = new_label
                if script_data.get("label") == old:
                    script_data["label"] = new_label
                print(f"  Renamed: {old} -> {new_label}")
                input("  Press Enter > ")
                return True
        print("  No label beat found to rename.")
    input("  Press Enter > ")
    return False


def _handle_edit_cmd(low, beats, selected_idx, script_data, emotes_conf, settings,
                     map_name, project_dir, game_path, expansion_version=None):
    """Handle edit beat command. Returns (selected_idx, dirty_changed)."""
    parts = low.split()
    edit_idx = selected_idx
    if len(parts) > 1:
        try:
            edit_idx = int(parts[1]) - 1
        except ValueError:
            print("  Usage: e or e #")
            input("  Press Enter > ")
            return selected_idx, False
    if 0 <= edit_idx < len(beats):
        result = _edit_beat(beats[edit_idx], script_data, emotes_conf,
                            settings["textbox_warning"],
                            map_name, project_dir, game_path,
                            expansion_version)
        if result:
            beats[edit_idx] = result
            return selected_idx, True
    else:
        print("  Invalid beat number.")
        input("  Press Enter > ")
    return selected_idx, False


def _handle_delete_cmd(low, beats, selected_idx):
    """Handle delete beat command. Returns (selected_idx, dirty_changed)."""
    parts = low.split()
    del_idx = selected_idx
    if len(parts) > 1:
        try:
            del_idx = int(parts[1]) - 1
        except ValueError:
            print("  Usage: d or d #")
            input("  Press Enter > ")
            return selected_idx, False
    if 0 <= del_idx < len(beats):
        summary = _script_beat_summary(beats[del_idx])
        print(f"  Delete beat {del_idx+1}? {summary}")
        yn = input("  Confirm [y/N] > ").strip().lower()
        if yn == "y":
            beats.pop(del_idx)
            if selected_idx >= len(beats) and beats:
                selected_idx = len(beats) - 1
            return selected_idx, True
    else:
        print("  Invalid beat number.")
        input("  Press Enter > ")
    return selected_idx, False


def _handle_move_cmd(low, beats, selected_idx):
    """Handle move beat command (x). Returns (selected_idx, dirty_changed)."""
    parts = low.split()
    if len(parts) == 3:
        try:
            from_idx = int(parts[1]) - 1
            to_idx = int(parts[2]) - 1
            if 0 <= from_idx < len(beats) and 0 <= to_idx < len(beats):
                beat = beats.pop(from_idx)
                beats.insert(to_idx, beat)
                return to_idx, True
            else:
                print("  Invalid beat numbers.")
                input("  Press Enter > ")
        except ValueError:
            print("  Usage: x <from> <to>")
            input("  Press Enter > ")
    elif len(parts) == 1:
        from_str = input("  Move beat # > ").strip()
        to_str = input("  To position # > ").strip()
        try:
            from_idx = int(from_str) - 1
            to_idx = int(to_str) - 1
            if 0 <= from_idx < len(beats) and 0 <= to_idx < len(beats):
                beat = beats.pop(from_idx)
                beats.insert(to_idx, beat)
                return to_idx, True
            else:
                print("  Invalid beat numbers.")
                input("  Press Enter > ")
        except ValueError:
            print("  Enter numbers.")
            input("  Press Enter > ")
    else:
        print("  Usage: x <from> <to>")
        input("  Press Enter > ")
    return selected_idx, False


def _handle_shift(low, beats, selected_idx, direction):
    """Handle shift beat up/down. Returns (selected_idx, dirty_changed)."""
    parts = low.split()
    target = selected_idx
    if len(parts) > 1:
        try:
            target = int(parts[1]) - 1
        except ValueError:
            pass
    if direction == "up" and 0 < target < len(beats):
        beats[target], beats[target-1] = beats[target-1], beats[target]
        return target - 1, True
    if direction == "down" and 0 <= target < len(beats) - 1:
        beats[target], beats[target+1] = beats[target+1], beats[target]
        return target + 1, True
    return selected_idx, False


def _handle_note(script_data):
    """Handle header note edit. Returns True if modified."""
    print()
    current = script_data.get("header_comment", "")
    if current:
        print(f"  Current: {current}")
    new_note = input("  New header comment > ").strip()
    if new_note:
        script_data["header_comment"] = new_note
        input("  Press Enter > ")
        return True
    input("  Press Enter > ")
    return False


def _handle_context_cycle(settings):
    """Cycle editor_context: compact -> detail -> timeline -> off -> compact."""
    cycle = {"compact": "detail", "detail": "timeline", "timeline": "off",
             "off": "compact"}
    current = settings.get("editor_context", "compact")
    settings["editor_context"] = cycle.get(current, "compact")


def _handle_add_beat(script_data, beats, selected_idx, emotes_conf, settings,
                     map_name, project_dir, game_path, before=False,
                     expansion_version=None, proj_name=None):
    """Prompt for a new beat and insert it. Returns (new_selected_idx, dirty_changed)."""
    result = _add_beat_prompt(script_data, emotes_conf, settings["textbox_warning"],
                              map_name, project_dir, game_path, expansion_version,
                              proj_name)
    if result:
        insert_pos = (selected_idx if before else selected_idx + 1) if beats else 0
        if isinstance(result, list):
            for i, beat in enumerate(result):
                beats.insert(insert_pos + i, beat)
            new_idx = insert_pos + len(result) - 1
        else:
            beats.insert(insert_pos, result)
            new_idx = insert_pos
        return new_idx if not before else selected_idx, True
    return selected_idx, False


def _handle_torscript_entry(raw, script_data, beats, selected_idx):
    """Handle quick-entry TorScript (: prefix). Returns (selected_idx, dirty_changed)."""
    torscript = raw[1:].strip()
    if torscript:
        new_beat = _parse_torscript_beat(torscript, script_data)
        if new_beat:
            insert_pos = selected_idx + 1 if beats else 0
            beats.insert(insert_pos, new_beat)
            return insert_pos, True
        print(f"  Could not parse: {torscript}")
        input("  Press Enter > ")
    return selected_idx, False


def _script_editor_loop(script_data, map_name, filepath, project_dir, game_path,
                       emotes_conf, source_display, settings=None, proj_name=None,
                       expansion_version=None):
    """Main Script Editor editor loop."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)
    _set_terminal_title("TORCH \u2014 Script Studio")
    selected_idx = 0
    scroll_offset = 0
    dirty = False
    view_mode = "focused"

    while True:
        beats = script_data.get("beats", [])
        scroll_offset = _render_script_editor(script_data, map_name, filepath,
                                              scroll_offset, selected_idx, dirty, settings, view_mode, proj_name)

        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            if dirty:
                yn = input("  Unsaved changes. Quit anyway? [y/N] > ").strip().lower()
                if yn != "y":
                    continue
            return

        if not raw:
            if beats:
                selected_idx = (selected_idx + 1) % len(beats)
            continue

        low = raw.lower()

        # --- Navigation ---
        if low == "b":
            if beats:
                selected_idx = (selected_idx - 1) % len(beats)
            continue

        # --- File operations ---
        if low == "q":
            action, dirty = _handle_quit(script_data, filepath, dirty, map_name,
                                         project_dir, game_path, emotes_conf,
                                         source_display, settings)
            if action == "quit":
                return
            continue

        if low == "s":
            dirty = _handle_save(script_data, filepath, game_path, proj_name,
                                 map_name, project_dir, emotes_conf,
                                 source_display, settings)
            continue

        if low == "w":
            dirty = _handle_save_sync(script_data, filepath, map_name, project_dir,
                                      game_path, emotes_conf, source_display, settings)
            continue

        # --- Scene metadata ---
        if low == "c":
            _edit_cast(script_data, proj_name)
            dirty = True
            continue

        if low == "l":
            if _handle_label_rename(script_data, beats):
                dirty = True
            continue

        if low == "n":
            if _handle_note(script_data):
                dirty = True
            continue

        # --- Display ---
        if low == "?":
            _show_full_commands()
            continue


        if low == "tv":
            _handle_context_cycle(settings)
            continue

        if low == "t":
            _render_storyboard(script_data, map_name, settings)
            continue

        if low == "v":
            new_data, changed = _handle_vim_edit(script_data, filepath, emotes_conf, map_name, game_path, settings)
            if changed:
                script_data.update(new_data)
                dirty = True
                selected_idx = min(selected_idx, max(0, len(script_data.get("beats", [])) - 1))
            continue

        if low == "f":
            view_mode = "full" if view_mode == "focused" else "focused"
            continue

        if low == "m":
            _movement_block_manager(map_name, project_dir, settings)
            continue

        # --- Beat editing ---
        if low == "a":
            selected_idx, changed = _handle_add_beat(script_data, beats, selected_idx,
                                                     emotes_conf, settings, map_name,
                                                     project_dir, game_path,
                                                     expansion_version=expansion_version,
                                                     proj_name=proj_name)
            if changed:
                dirty = True
            continue

        if low == "i":
            selected_idx, changed = _handle_add_beat(script_data, beats, selected_idx,
                                                     emotes_conf, settings, map_name,
                                                     project_dir, game_path, before=True,
                                                     expansion_version=expansion_version,
                                                     proj_name=proj_name)
            if changed:
                dirty = True
            continue

        if low.startswith("e"):
            selected_idx, changed = _handle_edit_cmd(low, beats, selected_idx, script_data,
                                                     emotes_conf, settings, map_name,
                                                     project_dir, game_path,
                                                     expansion_version)
            if changed:
                dirty = True
            continue

        if low.startswith("d"):
            selected_idx, changed = _handle_delete_cmd(low, beats, selected_idx)
            if changed:
                dirty = True
            continue

        # --- Beat reordering ---
        if low == "x" or low.startswith("x ") or low.startswith("x\t"):
            selected_idx, changed = _handle_move_cmd(low, beats, selected_idx)
            if changed:
                dirty = True
            continue

        if low.startswith("u"):
            selected_idx, changed = _handle_shift(low, beats, selected_idx, "up")
            if changed:
                dirty = True
            continue

        if low.startswith("j"):
            selected_idx, changed = _handle_shift(low, beats, selected_idx, "down")
            if changed:
                dirty = True
            continue

        # --- Quick-entry TorScript ---
        if raw.startswith(":"):
            selected_idx, changed = _handle_torscript_entry(raw, script_data, beats, selected_idx)
            if changed:
                dirty = True
            continue

        # --- Number: jump to beat ---
        try:
            num = int(raw)
            if beats:
                selected_idx = max(0, min(num - 1, len(beats) - 1))
        except ValueError:
            print(f"  Unknown command: {raw}")
            input("  Press Enter > ")


def _edit_dialogue_beat(beat, data, textbox_warning):
    print("  Current text:")
    _dialogue_textbox_preview(data["text"], textbox_warning)
    print(f"  Style: {data.get('style', 'msg')}")
    print()
    print("  Enter new text, or press Enter to keep current.")
    new_text = input("  Text > ").strip()
    if new_text:
        print()
        wrapped_text, was_wrapped = _dialogue_textbox_preview(new_text, textbox_warning)
        print()
        if was_wrapped:
            print("  [y] Use auto-wrapped  [k] Keep original  [c] Cancel edit")
            choice = input("  > ").strip().lower()
            if choice == "c":
                return beat
            elif choice == "k":
                data["text"] = new_text
            else:
                data["text"] = wrapped_text
        else:
            data["text"] = new_text
    print()
    print("  [1] msg  [2] msgnpc  [Enter] keep")
    sc = input("  Style > ").strip()
    if sc == "2":
        data["style"] = "msgnpc"
    elif sc == "1":
        data["style"] = "msg"
    return beat


def _edit_move_beat(beat, data, script_data, map_name, project_dir):
    parts = []
    for a in data["actions"]:
        verb = a["verb"]
        actor = a["actor"]
        if verb == "face":
            parts.append(f"{actor} face {a['direction']}")
        elif verb in WALK_COMMANDS:
            parts.append(f"{actor} {verb} {a['direction']} {a['count']}")
        elif verb == "do":
            parts.append(f"{actor} do {a['label']}")
        elif verb == "jump":
            parts.append(f"{actor} jump {a['direction']}")
        elif verb == "emote":
            parts.append(f"{actor} emote {a['emote_name']}")
        else:
            parts.append(a.get("raw", f"{actor} {verb}"))
    current_torscript = " + ".join(parts)
    print(f"  Current: {current_torscript}")
    print()
    new_sh = input("  New (TorScript, or Enter to keep) > ").strip()
    if new_sh:
        new_beat = _parse_torscript_beat(new_sh, script_data)
        if new_beat and new_beat["type"] in ("move", "emote"):
            return new_beat
        if new_beat:
            return new_beat
        print("  Could not parse. Opening guided mode.")
        result = _prompt_move_beat(script_data, map_name, project_dir)
        return result if result else beat
    return beat


def _edit_emote_beat(beat, data, script_data, emotes_conf):
    print(f"  Current: {data['actor']} emote {data['emote_name']}")
    print()
    actor = _pick_actor(script_data, "Actor (Enter to keep)")
    if actor:
        data["actor"] = actor
    print()
    print("  Pick new emote or Enter to keep current:")
    emote = _emote_picker(emotes_conf)
    if emote:
        data["emote_name"] = emote
    return beat


def _edit_fade_beat(beat, data):
    print(f"  Current: fade {data['fade_type']}")
    print("  Types: black / in / white / from white / in white")
    new_fade = input("  New type (Enter to keep) > ").strip().lower()
    if new_fade:
        data["fade_type"] = new_fade
    return beat


def _edit_sound_beat(beat, data, game_path):
    print(f"  Current: sound {data['constant']}")
    print(f"  {DIM}Sound effect from songs.h (e.g. SE_EXIT). 'q' to keep current.{RST}")
    new_const = pick_sound(game_path) if game_path else input("  New constant (Enter to keep) > ").strip()
    if new_const:
        data["constant"] = new_const
    return beat


def _edit_flag_beat(beat, data, game_path):
    print(f"  Current: flag {data['action']} {data['flag_name']}")
    print("  [1] set  [2] clear  [Enter] keep")
    ac = input("  Action > ").strip()
    if ac == "1":
        data["action"] = "set"
    elif ac == "2":
        data["action"] = "clear"
    print(f"  {DIM}Flag from flags.h (e.g. FLAG_BEAT_BUSTER_1). 'q' to keep current.{RST}")
    new_flag = pick_flag(game_path) if game_path else input("  Flag constant (Enter to keep) > ").strip()
    if new_flag:
        data["flag_name"] = new_flag
    return beat


def _edit_actor_beat(beat, data, script_data, label):
    print(f"  Current: {label} {data['actor']}")
    actor = _pick_actor(script_data, "New actor (Enter to keep)")
    if actor:
        data["actor"] = actor
    return beat


def _edit_flow_beat(beat, data, script_data, map_name, project_dir):
    ft = data["flow_type"]
    t = data.get("target", "")
    print(f"  Current: {ft} {t}")
    if ft in ("goto", "call"):
        print(f"  {DIM}Target label to jump/call. 'q' to keep current.{RST}")
        new_target = _pick_label(script_data, map_name, project_dir) if script_data else input("  New target (Enter to keep) > ").strip()
        if new_target:
            data["target"] = new_target
    return beat


def _edit_simple_text_beat(beat, data, field, prompt_label, current_prefix):
    print(f"  Current: {current_prefix} {data[field]}")
    new_val = input(f"  New {prompt_label} (Enter to keep) > ").strip()
    if new_val:
        data[field] = new_val
    return beat


def _edit_battle_beat(beat, data, expansion_version=None):
    from torch.battle_manager import BATTLE_TYPES, _available_battle_types
    print(f"  Current: {data['battle_type']}")
    args_parts = [a.strip() for a in data["args"].split(",")]
    for i, part in enumerate(args_parts):
        print(f"    Arg{i+1}: {part}")
    print()
    available = _available_battle_types(expansion_version)
    print(f"  {DIM}Change battle type:{RST}")
    for idx, (type_name, macro, min_ver, desc) in enumerate(available, 1):
        print(f"    {GOLD}[{idx}]{RST} {macro:<40} {DIM}{desc}{RST}")
    print(f"    {GOLD}[Enter]{RST} {DIM}keep current{RST}")
    print()
    bt = input("  Type > ").strip()
    if bt:
        try:
            pick = int(bt)
            if 1 <= pick <= len(available):
                chosen = available[pick - 1]
                data["battle_type"] = chosen[1]
        except ValueError:
            pass
    print("  Enter new args, or Enter to keep:")
    new_args = input("  Args > ").strip()
    if new_args:
        data["args"] = new_args
    return beat


def _edit_pause_beat(beat, data):
    print(f"  Current duration: {data['duration'] or '(default)'}")
    new_dur = input("  New duration (Enter to keep) > ").strip()
    if new_dur:
        data["duration"] = new_dur
    return beat


def _edit_gotoif_beat(beat, data, script_data, map_name, project_dir, game_path):
    print(f"  Current: gotoif {data['flag']} {data['target']}")
    print(f"  {DIM}Flag to check (from flags.h). 'q' to keep current.{RST}")
    new_flag = pick_flag(game_path) if game_path else input("  Flag (Enter to keep) > ").strip()
    if new_flag:
        data["flag"] = new_flag
    print(f"  {DIM}Label to jump to if flag is set. 'q' to keep current.{RST}")
    new_target = _pick_label(script_data, map_name, project_dir) if script_data else input("  Target (Enter to keep) > ").strip()
    if new_target:
        data["target"] = new_target
    return beat


def _edit_setpos_beat(beat, data, script_data):
    print(f"  Current: setpos {data['actor']} {data['x']} {data['y']}")
    actor = _pick_actor(script_data, "Actor (Enter to keep)")
    if actor:
        data["actor"] = actor
    new_x = input("  X (Enter to keep) > ").strip()
    if new_x:
        data["x"] = new_x
    new_y = input("  Y (Enter to keep) > ").strip()
    if new_y:
        data["y"] = new_y
    return beat


def _edit_picker_beat(beat, data, field, current_prefix, hint, picker, game_path):
    print(f"  Current: {current_prefix} {data[field]}")
    print(f"  {DIM}{hint}. 'q' to keep current.{RST}")
    new_val = picker(game_path) if game_path else input(f"  {current_prefix.capitalize()} (Enter to keep) > ").strip()
    if new_val:
        data[field] = new_val
    return beat


def _edit_var_beat(beat, data, game_path):
    print(f"  Current: var {data['var_name']} = {data['value']}")
    print(f"  {DIM}Variable from vars.h (e.g. VAR_TEMP_1). 'q' to keep current.{RST}")
    new_var = pick_var(game_path) if game_path else input("  Variable (Enter to keep) > ").strip()
    if new_var:
        data["var_name"] = new_var
    new_val = input("  Value (Enter to keep) > ").strip()
    if new_val:
        data["value"] = new_val
    return beat


def _edit_shake_beat(beat, data):
    print(f"  Current: shake {data['intensity']} {data['count']}")
    new_intensity = input("  Intensity (Enter to keep) > ").strip()
    if new_intensity:
        data["intensity"] = new_intensity
    new_count = input("  Count (Enter to keep) > ").strip()
    if new_count:
        data["count"] = new_count
    return beat


def _edit_beat(beat, script_data, emotes_conf=None, textbox_warning=3,
               map_name=None, project_dir=None, game_path=None,
               expansion_version=None):
    """Edit an existing beat in-place. Returns the modified beat or None to cancel."""
    btype = beat["type"]
    data = beat["data"]

    print()
    print(f"  Editing: {_script_beat_summary(beat)}")
    print()

    _EDIT_HANDLERS = {
        "dialogue": lambda: _edit_dialogue_beat(beat, data, textbox_warning),
        "move": lambda: _edit_move_beat(beat, data, script_data, map_name, project_dir),
        "emote": lambda: _edit_emote_beat(beat, data, script_data, emotes_conf),
        "fade": lambda: _edit_fade_beat(beat, data),
        "sound": lambda: _edit_sound_beat(beat, data, game_path),
        "flag": lambda: _edit_flag_beat(beat, data, game_path),
        "hide": lambda: _edit_actor_beat(beat, data, script_data, "hide"),
        "show": lambda: _edit_actor_beat(beat, data, script_data, "show"),
        "flow": lambda: _edit_flow_beat(beat, data, script_data, map_name, project_dir),
        "comment": lambda: _edit_simple_text_beat(beat, data, "text", "comment", "#"),
        "label": lambda: _edit_simple_text_beat(beat, data, "name", "label name", "label"),
        "pory": lambda: _edit_simple_text_beat(beat, data, "raw_line", "line", "pory"),
        "battle": lambda: _edit_battle_beat(beat, data, expansion_version),
        "pause": lambda: _edit_pause_beat(beat, data),
        "gotoif": lambda: _edit_gotoif_beat(beat, data, script_data, map_name, project_dir, game_path),
        "setpos": lambda: _edit_setpos_beat(beat, data, script_data),
        "special": lambda: _edit_picker_beat(beat, data, "function", "special", "Engine function from specials.inc", pick_special, game_path),
        "var": lambda: _edit_var_beat(beat, data, game_path),
        "music": lambda: _edit_picker_beat(beat, data, "constant", "music", "BGM from songs.h (e.g. MUS_ROUTE101)", pick_music, game_path),
        "fanfare": lambda: _edit_picker_beat(beat, data, "constant", "fanfare", "Jingle from sound.h (e.g. FANFARE_LEVEL_UP)", pick_fanfare, game_path),
        "cry": lambda: _edit_picker_beat(beat, data, "species", "cry", "Species whose cry to play", pick_species, game_path),
        "shake": lambda: _edit_shake_beat(beat, data),
    }

    handler = _EDIT_HANDLERS.get(btype)
    if handler:
        return handler()

    # Fallback — generic edit
    print(f"  No specialized editor for '{btype}'. Edit the raw data:")
    for key, val in data.items():
        new_val = input(f"  {key} [{val}] > ").strip()
        if new_val:
            data[key] = new_val
    return beat


def _storyboard_move_desc(verb, direction, count="1"):
    """Return a human-readable movement description for storyboard."""
    verb_english = {
        "walk": "walks",
        "walkfast": "walks quickly",
        "walkslow": "walks slowly",
        "run": "runs",
        "slide": "slides",
    }
    v = verb_english.get(verb, verb + "s")
    tiles = f" {count} tile{'s' if count != '1' else ''}" if verb != "face" else ""
    return f"{v} {direction}{tiles}"


def _storyboard_dialogue_display(text, max_len=68):
    """Format dialogue for storyboard — render \\n as line breaks, \\p as box markers.

    Thin wrapper around textutils.storyboard_display.
    """
    return _storyboard_display_impl(text, max_len=max_len)


def _sb_render_dialogue(beat_num, data, map_name):
    lines = []
    text = data["text"]
    display = _storyboard_dialogue_display(text)
    first_line = display.split("\n")[0]
    lines.append(f"  {beat_num:>3}. \"{first_line}\"")
    for extra in display.split("\n")[1:]:
        lines.append(f"       {extra}")
    return lines


def _sb_render_move(beat_num, data, map_name):
    parts = []
    for a in data["actions"]:
        actor = a["actor"].upper()
        verb = a["verb"]
        if verb == "face":
            parts.append(f"{actor} faces {a['direction']}")
        elif verb in WALK_COMMANDS:
            count = a.get("count", "1")
            parts.append(f"{actor} {_storyboard_move_desc(verb, a['direction'], count)}")
        elif verb == "do":
            label_name = a.get("label", "")
            short = label_name
            if "_" in label_name and label_name.startswith(map_name + "_"):
                short = label_name[len(map_name) + 1:]
            parts.append(f"{actor} performs {short}")
        elif verb == "jump":
            parts.append(f"{actor} jumps {a['direction']}")
        elif verb == "emote":
            parts.append(f"{actor} reacts with {a['emote_name']}")
        else:
            parts.append(f"{actor} {verb}")
    connector = " and " if len(parts) == 2 else ", "
    return [f"  {beat_num:>3}. {connector.join(parts)}"]


def _sb_render_emote(beat_num, data, map_name):
    emote_words = {"!": "surprised", "?": "confused", "!!": "shocked",
                   "x": "angry", "heart": "love", "...": "thinking"}
    emotion = emote_words.get(data["emote_name"], data["emote_name"])
    return [f"  {beat_num:>3}. {data['actor'].upper()} reacts ({emotion})"]


def _sb_render_fade(beat_num, data, map_name):
    fade_english = {
        "black": "Screen fades to black",
        "in": "Screen fades in",
        "white": "Screen fades to white",
        "from black": "Screen fades in from black",
        "from white": "Screen fades in from white",
        "in white": "Screen fades in from white",
    }
    return [f"  {beat_num:>3}. {fade_english.get(data['fade_type'], 'Fade ' + data['fade_type'])}"]


def _sb_render_sound(beat_num, data, map_name):
    snd = data["constant"].replace("SE_", "").replace("_", " ").lower()
    return [f"  {beat_num:>3}. Sound effect: {snd}"]


def _sb_render_cry(beat_num, data, map_name):
    species = data["species"].replace("SPECIES_", "").replace("_", " ").title()
    return [f"  {beat_num:>3}. {species} cry plays"]


def _sb_render_pause(beat_num, data, map_name):
    dur = data["duration"]
    if dur == "long":
        return [f"  {beat_num:>3}. Long pause"]
    if dur:
        return [f"  {beat_num:>3}. Pause ({dur} frames)"]
    return [f"  {beat_num:>3}. Brief pause"]


def _sb_render_battle(beat_num, data, map_name):
    args_parts = [a.strip() for a in data["args"].split(",")]
    trainer = args_parts[0] if args_parts else "?"
    trainer_short = trainer.replace("TRAINER_", "").replace("_", " ").title()
    bt = "Double" if "double" in data["battle_type"] else "Single"
    return [f"  {beat_num:>3}. \u2694 BATTLE ({bt}) \u2014 vs. {trainer_short}"]


def _sb_render_flow(beat_num, data, map_name):
    ft = data["flow_type"]
    t = data.get("target", "")
    _FLOW_FORMATS = {
        "goto": "\u2192 Continue to {t}",
        "call": "\u2192 Call {t}",
        "end": "\u2014 Script ends",
        "release": "\u2014 Release player, scene ends",
        "return": "\u2192 Return",
    }
    fmt = _FLOW_FORMATS.get(ft)
    if fmt:
        return [f"  {beat_num:>3}. {fmt.format(t=t)}"]
    return [f"  {beat_num:>3}. {ft} {t}"]


def _sb_render_pory(beat_num, data, map_name):
    raw = data["raw_line"]
    pory_english = {
        "lock": "Player is locked in place",
        "lockall": "Player is locked in place",
        "release": "\u2014 Release player, scene ends",
        "end": "\u2014 Script ends",
        "releaseall": "\u2014 Release all",
    }
    if raw in pory_english:
        return [f"  {beat_num:>3}. {pory_english[raw]}"]
    return [f"  {beat_num:>3}. [script] {raw}"]


_SB_RENDERERS = {
    "dialogue": _sb_render_dialogue,
    "move": _sb_render_move,
    "emote": _sb_render_emote,
    "fade": _sb_render_fade,
    "sound": _sb_render_sound,
    "music": lambda n, d, m: [f"  {n:>3}. Music changes to {d['constant']}"],
    "fanfare": lambda n, d, m: [f"  {n:>3}. Fanfare: {d['constant']}"],
    "cry": _sb_render_cry,
    "pause": _sb_render_pause,
    "flag": lambda n, d, m: [f"  {n:>3}. {'Set' if d['action'] == 'set' else 'Clear'} flag {d['flag_name']}"],
    "hide": lambda n, d, m: [f"  {n:>3}. {d['actor'].upper()} exits the scene"],
    "show": lambda n, d, m: [f"  {n:>3}. {d['actor'].upper()} appears"],
    "battle": _sb_render_battle,
    "flow": _sb_render_flow,
    "lock": lambda n, d, m: [f"  {n:>3}. Player is locked in place"],
    "faceplayer": lambda n, d, m: [f"  {n:>3}. NPC turns to face player"],
    "gotoif": lambda n, d, m: [f"  {n:>3}. If {d['flag']} \u2192 jump to {d['target']}"],
    "pory": _sb_render_pory,
    "raw": lambda n, d, m: [f"  {n:>3}. [raw] {d['raw_line']}"],
    "setpos": lambda n, d, m: [f"  {n:>3}. {d['actor'].upper()} moved to ({d['x']}, {d['y']})"],
    "var": lambda n, d, m: [f"  {n:>3}. Set {d['var_name']} = {d['value']}"],
    "shake": lambda n, d, m: [f"  {n:>3}. Camera shakes (intensity {d['intensity']}, {d['count']}x)"],
    "special": lambda n, d, m: [f"  {n:>3}. Special: {d['function']}"],
    "waitstate": lambda n, d, m: [f"  {n:>3}. Wait for state"],
    "closemessage": lambda n, d, m: [f"  {n:>3}. Close text box"],
    "text": lambda n, d, m: [f"  {n:>3}. Text block: {d['label']}"],
    "movement": lambda n, d, m: [f"  {n:>3}. Movement block: {d['label']}"],
}


def _render_storyboard(script_data, map_name, settings=None):
    """Show a clean, readable storyboard summary of the scene."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)

    clear_screen()
    print(BAR)
    label = script_data.get("label") or "Untitled"
    print(f"   {WHITE}STORYBOARD{RST}  {DIM}\u2014  {label}{RST}")
    print(BAR)
    print()

    # Cast
    cast = script_data.get("cast", {})
    if cast:
        cast_parts = [f"{name.upper()} (npc{nid})" for name, nid in cast.items()]
        cast_parts.append("PLAYER")
        print(f"  Cast: {', '.join(cast_parts)}")
    else:
        print("  Cast: PLAYER")
    print()

    # Collect lines into a list for scrolling
    sb_lines = []
    beats = script_data.get("beats", [])
    beat_num = 0
    for beat in beats:
        btype = beat["type"]
        data = beat["data"]
        beat_num += 1

        # Label and comment are structural — they don't count as beats
        if btype == "label":
            sb_lines.append("")
            sb_lines.append(f"  {'':>3}  \u2500\u2500\u2500 {data['name']} \u2500\u2500\u2500")
            beat_num -= 1
            continue

        if btype == "comment":
            sb_lines.append(f"  {'':>3}  ({data['text']})")
            beat_num -= 1
            continue

        renderer = _SB_RENDERERS.get(btype)
        if renderer:
            sb_lines.extend(renderer(beat_num, data, map_name))
        else:
            sb_lines.append(f"  {beat_num:>3}. {btype}: {data}")

    # Paginated display
    page_size = settings["storyboard_page_size"]
    offset = 0
    total = len(sb_lines)

    while True:
        if offset > 0:
            clear_screen()
            print(BAR)
            print(f"   {WHITE}STORYBOARD{RST}  {DIM}\u2014  {label}{RST}")
            print(BAR)
            print()

        end = min(offset + page_size, total)
        for line in sb_lines[offset:end]:
            print(line)

        print()
        if end < total:
            remaining = total - end
            nav = input(f"  [{remaining} more] Enter=next page, q=back to editor > ").strip().lower()
            if nav == "q":
                return
            offset = end
            continue
        else:
            input("  Press Enter to return to editor > ")
            return


def _script_info(filepath):
    """Quick-parse a scene file and return (beat_count, description)."""
    try:
        sd = _parse_script(filepath)
        beat_count = len([b for b in sd["beats"] if b["type"] not in ("label", "comment")])
        desc = ""
        if sd.get("header_comment"):
            desc = sd["header_comment"].split("\n")[0]
            if len(desc) > 30:
                desc = desc[:27] + "..."
        return beat_count, desc
    except Exception:
        return 0, ""
