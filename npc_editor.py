"""NPC Script Editor — edit simple dialogue NPCs without touching code.

Handles the 90% of NPCs that don't need the full Scene Editor: villagers,
sign posts, item givers, multi-state NPCs. Parses existing scripts from
.inc and .pory files, edits dialogue with GBA textbox preview, and generates
new scripts via wizard templates.

Entry points:
    npc_editor_menu(game_path, map_name, conf)  -- from Map Studio or CLI
"""
# TORCH_MODULE: NPC Editor
# TORCH_GROUP: Map Studio
import os
import re
import json
import subprocess

from torch.ui import print_logo, _set_terminal_title, _k, clear_screen, _truncate_dialogue
from torch.colours import GOLD, WHITE, CYAN, DIM, RST, GREEN, RED, BOLD_RED, BAR
from torch.project_files import get_map_objects
from torch.textutils import (
    wrap_gba_text, count_text_boxes, textbox_preview, dialogue_prompt,
    GBA_LINE_LEN,
)

NPC_EDITOR_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Script file location
# ---------------------------------------------------------------------------

def _find_script_file(game_path, map_name, label):
    """Locate which file contains a script label.

    Returns (filepath, file_type) where file_type is 'pory', 'inc', or None.
    Checks scripts.pory first (takes precedence), then scripts.inc.
    """
    if not label:
        return None, None

    map_dir = os.path.join(game_path, "data", "maps", map_name)

    # Check scripts.pory first — Poryscript labels take precedence
    pory_path = os.path.join(map_dir, "scripts.pory")
    if os.path.isfile(pory_path):
        try:
            with open(pory_path, "r", encoding="utf-8") as f:
                content = f.read()
            if re.search(rf'\bscript\s+{re.escape(label)}\b', content):
                return pory_path, "pory"
        except OSError:
            pass

    # Check scripts.inc
    inc_path = os.path.join(map_dir, "scripts.inc")
    if os.path.isfile(inc_path):
        try:
            with open(inc_path, "r", encoding="utf-8") as f:
                content = f.read()
            if re.search(rf'^{re.escape(label)}::', content, re.MULTILINE):
                return inc_path, "inc"
        except OSError:
            pass

    return None, None


def _find_workspace_script(project_dir, map_name, label):
    """Check if a script label matches a .txt file in the TORCH workspace.

    Returns the .txt path if found, else None.
    """
    ws_dir = os.path.join(project_dir, map_name) if project_dir else None
    if not ws_dir or not os.path.isdir(ws_dir):
        return None
    for fname in os.listdir(ws_dir):
        if fname.endswith(".txt"):
            script_name = os.path.splitext(fname)[0]
            if script_name == label or label.endswith(f"_{script_name}"):
                return os.path.join(ws_dir, fname)
    return None


# ---------------------------------------------------------------------------
# Cast index — map NPC IDs to workspace scenes
# ---------------------------------------------------------------------------

def _build_cast_index(project_dir, map_name, game_path=None):
    """Scan all .txt scenes in workspace, return cast mapping.

    Returns: {npc_id: [(alias_name, script_name, filepath), ...]}
    where alias_name is the cast alias (or script name if no alias).

    When game_path is provided, auto-repairs stale alias NPC IDs by
    matching script labels to NPC script fields in map.json.  This
    handles the case where NPCs are added/removed in Porymap, shifting
    object indices without updating workspace alias directives.
    """
    cast_index = {}
    ws_dir = os.path.join(project_dir, map_name) if project_dir else None
    if not ws_dir or not os.path.isdir(ws_dir):
        return cast_index

    # Build label→object_id lookup from map.json for auto-repair
    label_to_objid = {}
    if game_path:
        npcs = get_map_objects(game_path, map_name)
        for npc in npcs:
            label = npc.get("script", "")
            if label:
                label_to_objid[label] = npc["object_id"]

    for fname in sorted(os.listdir(ws_dir)):
        if not fname.endswith(".txt"):
            continue
        script_name = os.path.splitext(fname)[0]
        fpath = os.path.join(ws_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue

        # Collect aliases and first label from file
        aliases = []   # [(line_idx, alias_name, old_npc_id)]
        first_label = None
        alias_block_end = False
        for li, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not alias_block_end:
                m = re.match(r'^alias\s+(\w+)\s+npc(\d+)\s*$', stripped)
                if m:
                    aliases.append((li, m.group(1), int(m.group(2))))
                    continue
                elif not stripped.startswith("alias"):
                    alias_block_end = True
            # Collect all labels (not just first) for matching
            if first_label is None:
                lm = re.match(r'^label\s+(\w+)', stripped)
                if lm:
                    first_label = lm.group(1)

        # Auto-repair: if we have a label→NPC match and aliases reference
        # stale IDs, fix the aliases in the file
        if aliases and label_to_objid and first_label:
            _repair_stale_aliases(fpath, lines, aliases, label_to_objid,
                                  map_name)
            # Re-read aliases after repair
            aliases = []
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError:
                continue
            for li, line in enumerate(lines):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                m = re.match(r'^alias\s+(\w+)\s+npc(\d+)\s*$', stripped)
                if m:
                    aliases.append((li, m.group(1), int(m.group(2))))
                elif not stripped.startswith("alias"):
                    break

        # Register aliases in cast_index
        for _li, alias_name, npc_id in aliases:
            cast_index.setdefault(npc_id, [])
            entry = (alias_name, script_name, fpath)
            if entry not in cast_index[npc_id]:
                cast_index[npc_id].append(entry)

    return cast_index


def _repair_stale_aliases(fpath, lines, aliases, label_to_objid, map_name):
    """Fix alias NPC IDs that no longer match map.json object positions.

    Uses the script label (e.g. ``label MapName_Buster``) to look up which
    NPC in map.json has that script assigned, then corrects any alias whose
    npc ID doesn't match.  Operates on all aliases whose name appears as a
    substring of any label's script field (case-insensitive), so
    ``alias buster npc5`` will match NPC with script ``LakeElixSouth_Buster``.
    """
    # Build alias_name → correct_npc_id mapping by matching alias names
    # against NPC script labels.  e.g. alias "buster" matches
    # script "LakeElixSouth_Buster" (case-insensitive suffix match).
    alias_corrections = {}
    for _li, alias_name, old_id in aliases:
        for label, obj_id in label_to_objid.items():
            # Match: label ends with _AliasName (case-insensitive)
            suffix = f"_{alias_name}"
            if label.lower().endswith(suffix.lower()):
                if old_id != obj_id:
                    alias_corrections[alias_name] = (old_id, obj_id)
                break

    if not alias_corrections:
        return

    # Rewrite stale alias lines in place
    modified = False
    new_lines = list(lines)
    for li, alias_name, old_id in aliases:
        if alias_name not in alias_corrections:
            continue
        _old, new_id = alias_corrections[alias_name]
        new_lines[li] = re.sub(
            r'(alias\s+' + re.escape(alias_name) + r'\s+npc)\d+',
            rf'\g<1>{new_id}',
            new_lines[li],
        )
        modified = True

    if modified:
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Script classification — categorise .pory scripts
# ---------------------------------------------------------------------------

def _classify_pory_script(content, label):
    """Classify a .pory script block.

    Returns: "flavor" | "sign" | "item_giver" | "nurse" | "pc" | "complex"
    """
    pat = rf'\bscript\s+{re.escape(label)}\s*\{{'
    match = re.search(pat, content)
    if not match:
        return "complex"

    body = _extract_brace_block(content, match.start())
    if not body:
        return "complex"

    body_stripped = body.strip()

    # Check for specific patterns
    if "special(ShowPokemonStorageSystem)" in body_stripped:
        return "pc"
    if ("special(HealPlayerParty)" in body_stripped
            or "HealPlayerTeam" in body_stripped):
        return "nurse"
    if "giveitem(" in body_stripped:
        return "item_giver"

    # Count meaningful statements (skip blank lines, comments)
    stmts = [l.strip() for l in body_stripped.split("\n")
             if l.strip() and not l.strip().startswith("//")]

    # Single msgbox check
    msgbox_calls = [s for s in stmts if s.startswith("msgbox(")]
    non_msgbox = [s for s in stmts if not s.startswith("msgbox(")
                  and s != "}" and s != "{"]

    if len(msgbox_calls) == 1 and len(non_msgbox) == 0:
        # Pure single-msgbox script
        if "MSGBOX_SIGN" in msgbox_calls[0]:
            return "sign"
        if "MSGBOX_NPC" in msgbox_calls[0]:
            return "flavor"

    return "complex"


# ---------------------------------------------------------------------------
# Script parsing — .inc (assembly)
# ---------------------------------------------------------------------------

def _extract_inc_strings(content, text_label):
    """Collect .string lines for a text label from .inc content.

    Returns the joined game-format text (with \\n, \\p, $), or None.
    """
    # Find the text label (e.g., MyMap_Text_Hello:)
    pattern = rf'^{re.escape(text_label)}:\s*$'
    match = re.search(pattern, content, re.MULTILINE)
    if not match:
        return None

    result = []
    pos = match.end()
    lines = content[pos:].split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("@"):
            continue
        # Match .string "..."
        m = re.match(r'\.string\s+"(.*)"', stripped)
        if m:
            result.append(m.group(1))
        else:
            # End of .string block
            break

    return "".join(result) if result else None


def _parse_inc_dialogue(content, label):
    """Extract dialogue from a .inc assembly script.

    Returns dict: {
        "text": str (game format with \\n, \\p, $),
        "text_label": str,
        "msgbox_type": str (e.g., "MSGBOX_NPC"),
    } or None.
    """
    # Find the script label (label::)
    script_pat = rf'^{re.escape(label)}::'
    if not re.search(script_pat, content, re.MULTILINE):
        return None

    # Extract the script body (until next label:: or end of file)
    body_match = re.search(
        rf'^{re.escape(label)}::(.+?)(?=^\w+::|\Z)',
        content, re.MULTILINE | re.DOTALL
    )
    if not body_match:
        return None

    body = body_match.group(1)

    # Find msgbox command: msgbox TextLabel, MSGBOX_TYPE
    msgbox_m = re.search(r'msgbox\s+(\w+)\s*,\s*(\w+)', body)
    if not msgbox_m:
        return None

    text_label = msgbox_m.group(1)
    msgbox_type = msgbox_m.group(2)

    text = _extract_inc_strings(content, text_label)
    if text is None:
        return None

    return {
        "text": text,
        "text_label": text_label,
        "msgbox_type": msgbox_type,
    }


# ---------------------------------------------------------------------------
# Script parsing — .pory (Poryscript)
# ---------------------------------------------------------------------------

def _extract_pory_msgbox(content, label):
    """Extract msgbox text from a Poryscript script block.

    Returns dict: {
        "text": str (game format),
        "msgbox_type": str,
        "uses_format": bool,
    } or None.
    """
    # Find script block: script Label { ... }
    # Use a simple brace-counting parser
    pat = rf'\bscript\s+{re.escape(label)}\s*\{{'
    match = re.search(pat, content)
    if not match:
        return None

    # Extract block body via brace counting
    body = _extract_brace_block(content, match.start())
    if body is None:
        return None

    # Find msgbox — two forms:
    # msgbox(format("text"), TYPE)
    # msgbox("text", TYPE)
    fmt_m = re.search(
        r'msgbox\s*\(\s*format\s*\(\s*"((?:[^"\\]|\\.)*)"\s*\)\s*,\s*(\w+)\s*\)',
        body
    )
    if fmt_m:
        return {
            "text": fmt_m.group(1),
            "msgbox_type": fmt_m.group(2),
            "uses_format": True,
        }

    plain_m = re.search(
        r'msgbox\s*\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*(\w+)\s*\)',
        body
    )
    if plain_m:
        return {
            "text": plain_m.group(1),
            "msgbox_type": plain_m.group(2),
            "uses_format": False,
        }

    return None


def _extract_brace_block(content, start):
    """Extract the body between { and } starting from a match position.

    Returns the content between braces (exclusive), or None.
    """
    brace_start = content.find("{", start)
    if brace_start < 0:
        return None

    depth = 0
    for i in range(brace_start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return content[brace_start + 1:i]
    return None


# ---------------------------------------------------------------------------
# Text conversion
# ---------------------------------------------------------------------------

def _game_text_to_readable(text):
    """Convert game-format text to readable paragraphs.

    Strips \\n, \\p, \\l, and $ → readable multi-line text.
    """
    if not text:
        return ""
    clean = text.rstrip("$")
    # Replace control codes with readable separators
    clean = clean.replace("\\l", "\\n")  # \\l is just scroll (treat as \\n)
    clean = clean.replace("\\p", "\n\n")  # page break → paragraph break
    clean = clean.replace("\\n", "\n")    # line break → newline
    return clean.strip()


def _readable_to_game_text(text):
    """Convert readable paragraphs to game-format text.

    Paragraph breaks (blank lines) → \\p, line breaks → auto-wrapped.
    Returns formatted string ready for Poryscript (no trailing $).
    """
    if not text:
        return ""
    # Split into paragraphs on blank lines
    paragraphs = re.split(r'\n\s*\n', text.strip())
    wrapped_parts = []
    for para in paragraphs:
        # Collapse internal newlines to spaces
        flat = " ".join(para.split())
        wrapped_parts.append(wrap_gba_text(flat))
    return "\\p".join(wrapped_parts)


# ---------------------------------------------------------------------------
# NPC script resolution
# ---------------------------------------------------------------------------

def _parse_npc_scripts(game_path, map_name, npcs, project_dir=None):
    """Find and parse scripts for each NPC.

    Returns list of dicts parallel to npcs:
        {
            "filepath": str or None,
            "file_type": "pory" | "inc" | "workspace" | None,
            "text": str (game format) or None,
            "msgbox_type": str or None,
            "text_label": str or None (inc only),
            "uses_format": bool (pory only),
        }
    """
    results = []
    # Cache file contents to avoid re-reading
    _file_cache = {}

    for npc in npcs:
        label = npc.get("script", "")
        info = {
            "filepath": None, "file_type": None, "text": None,
            "msgbox_type": None, "text_label": None, "uses_format": True,
        }

        if not label:
            results.append(info)
            continue

        # Check workspace first (Scene Editor managed)
        if project_dir:
            ws_path = _find_workspace_script(project_dir, map_name, label)
            if ws_path:
                info["filepath"] = ws_path
                info["file_type"] = "workspace"
                results.append(info)
                continue

        # Find in game files
        filepath, file_type = _find_script_file(game_path, map_name, label)
        info["filepath"] = filepath
        info["file_type"] = file_type

        if filepath and file_type:
            if filepath not in _file_cache:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        _file_cache[filepath] = f.read()
                except OSError:
                    _file_cache[filepath] = ""

            content = _file_cache[filepath]

            if file_type == "inc":
                parsed = _parse_inc_dialogue(content, label)
                if parsed:
                    info["text"] = parsed["text"]
                    info["msgbox_type"] = parsed["msgbox_type"]
                    info["text_label"] = parsed["text_label"]
            elif file_type == "pory":
                parsed = _extract_pory_msgbox(content, label)
                if parsed:
                    info["text"] = parsed["text"]
                    info["msgbox_type"] = parsed["msgbox_type"]
                    info["uses_format"] = parsed["uses_format"]

        results.append(info)
    return results


# ---------------------------------------------------------------------------
# NPC list rendering
# ---------------------------------------------------------------------------

def _strip_label_prefix(label, map_name):
    """Remove map name prefix from a script label for cleaner display."""
    for prefix in (f"{map_name}_EventScript_", f"{map_name}_"):
        if label.startswith(prefix):
            return label[len(prefix):]
    return label


def _npc_script_entries(npc, script_info, cast_index):
    """Get workspace script entries for an NPC.

    Returns list of (alias_name, script_name, filepath) tuples.
    """
    obj_id = npc.get("object_id")
    script_entries = list(cast_index.get(obj_id, [])) if cast_index and obj_id is not None else []

    # Include direct workspace match not already in cast_index
    if script_info.get("file_type") == "workspace" and script_info.get("filepath"):
        ws_path = script_info["filepath"]
        if not any(fp == ws_path for _, _, fp in script_entries):
            sname = os.path.splitext(os.path.basename(ws_path))[0]
            script_entries.append((sname, sname, ws_path))

    return script_entries


def _build_flat_entries(npcs, script_infos, cast_index, map_name):
    """Build a flat list of selectable sub-entries across all NPCs.

    Returns list of dicts:
        {
            "npc_idx": int,          # index into npcs list
            "entry_type": str,       # "script"|"flavor"|"sign"|...|"none"
            "display": str,          # rendered sub-entry text (no cursor)
            "script_name": str|None,  # for script entries
            "script_path": str|None,  # for script entries
        }
    """
    flat = []
    _pory_cache = {}

    for i, (npc, info) in enumerate(zip(npcs, script_infos)):
        # Check for workspace scenes first
        scenes = _npc_script_entries(npc, info, cast_index)
        if scenes:
            from torch.script_editor import _script_info
            for _alias, script_name, fpath in scenes:
                beat_count, _desc = _script_info(fpath)
                beat_str = f"[{beat_count} beat{'s' if beat_count != 1 else ''}]"
                flat.append({
                    "npc_idx": i,
                    "entry_type": "script",
                    "display": f"Script - {script_name:<20} {DIM}{beat_str}{RST}",
                    "script_name": script_name,
                    "script_path": fpath,
                })
            continue

        # Game file scripts
        label = npc.get("script", "")
        if info.get("file_type") == "pory" and info.get("filepath"):
            fp = info["filepath"]
            if fp not in _pory_cache:
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        _pory_cache[fp] = f.read()
                except OSError:
                    _pory_cache[fp] = ""
            category = _classify_pory_script(_pory_cache[fp], label)
            # Detect placeholder scripts (flavor NPCs with "..." text)
            if category == "flavor" and info.get("text") == "...":
                category = "placeholder"
            stripped = _strip_label_prefix(label, map_name)
            preview = ""
            if info.get("text"):
                preview = f' {DIM}"{_truncate_dialogue(info["text"], 30)}"{RST}'
            _CAT_LABELS = {
                "flavor": "Flavor NPC", "sign": "Sign",
                "item_giver": "Item Giver", "complex": "Script",
                "placeholder": "Placeholder",
            }
            if category in ("nurse", "pc"):
                tag = "Nurse Joy" if category == "nurse" else "PC"
                display = tag
            else:
                tag = _CAT_LABELS.get(category, "Script")
                display = f"{tag} - {stripped}{preview}"
            flat.append({
                "npc_idx": i, "entry_type": category, "display": display,
                "script_name": None, "script_path": None,
            })
            continue

        if info.get("file_type") == "inc":
            stripped = _strip_label_prefix(label, map_name)
            preview = ""
            if info.get("text"):
                preview = f' {DIM}"{_truncate_dialogue(info["text"], 30)}"{RST}'
            flat.append({
                "npc_idx": i, "entry_type": "inc",
                "display": f"Script - {stripped}{preview}",
                "script_name": None, "script_path": None,
            })
            continue

        if not label:
            flat.append({
                "npc_idx": i, "entry_type": "none",
                "display": f"{DIM}(no script assigned){RST}",
                "script_name": None, "script_path": None,
            })
        else:
            flat.append({
                "npc_idx": i, "entry_type": "none",
                "display": f"{DIM}(no dialogue found){RST}",
                "script_name": None, "script_path": None,
            })

    return flat


def _npc_display_name(npc, cast_index):
    """Build display name: alias (graphics) or just graphics name."""
    obj_id = npc.get("object_id")
    gfx_name = npc.get("display_name", "?")

    if cast_index and obj_id is not None and obj_id in cast_index:
        alias = cast_index[obj_id][0][0]
        alias_title = alias.title()
        if alias_title.lower() == gfx_name.lower():
            return f"{WHITE}{alias_title}{RST}"
        return f"{WHITE}{alias_title}{RST} {DIM}({gfx_name}){RST}"

    return f"{WHITE}{gfx_name}{RST}"


def _render_npc_list(npcs, script_infos, selected_idx, map_name, proj_name,
                     cast_index=None, flat_entries=None, page_size=10):
    """Render the NPC list with cursor on sub-entries (scenes/scripts).

    selected_idx indexes into flat_entries, NOT npcs.
    Returns (scroll_top, total_flat_entries).
    """
    clear_screen()
    print_logo(f"NPC Editor  v{NPC_EDITOR_VERSION}", proj_name)
    print(BAR)
    print(f"   {WHITE}NPC EDITOR{RST}  {DIM}{map_name}{RST}")
    print(BAR)
    print()

    if not npcs or not flat_entries:
        print("  (no NPCs found on this map)")
        print()
        return 0, 0

    total = len(flat_entries)
    num_w = len(str(len(npcs)))

    # Scroll window based on selected flat entry
    scroll_top = max(0, selected_idx - page_size + 1)
    if selected_idx < scroll_top:
        scroll_top = selected_idx
    end = min(scroll_top + page_size, total)

    # Determine which NPC headers are needed in the visible range
    last_npc_idx = -1
    for fi in range(scroll_top, end):
        entry = flat_entries[fi]
        npc_idx = entry["npc_idx"]

        if npc_idx != last_npc_idx:
            # Print NPC header (dimmed, non-selectable)
            if last_npc_idx >= 0:
                print()  # blank line between NPC groups
            npc = npcs[npc_idx]
            display = _npc_display_name(npc, cast_index)
            num = f"{npc_idx + 1:>{num_w}}."
            trainer_tag = ""
            if npc.get("trainer_type", "TRAINER_TYPE_NONE") != "TRAINER_TYPE_NONE":
                trainer_tag = f"  {RED}[Trainer]{RST}"
            print(f"     {DIM}{num}{RST} {display}{trainer_tag}")
            last_npc_idx = npc_idx

        # Print sub-entry with cursor
        is_sel = fi == selected_idx
        cursor = f"{GOLD}>>{RST}" if is_sel else "  "
        print(f"  {cursor}  {'':>{num_w}}  {entry['display']}")

    if scroll_top > 0:
        print(f"\n  {DIM}  \u2191 {scroll_top} more above{RST}")
    remaining = total - end
    if remaining > 0:
        print(f"  {DIM}  \u2193 {remaining} more below{RST}")

    print()

    # Command bar
    cmd_parts = [
        f"{_k('e')}{DIM}dit{RST}",
        f"{_k('d')}{DIM}el{RST}",
        f"{_k('n')}{DIM}ew{RST}",
        f"{_k('w')}{DIM}izard{RST}",
        f"{_k('v')}{DIM}iew{RST}",
        f"{_k('Enter')} {DIM}scroll{RST}",
        f"{_k('q')} {DIM}back{RST}",
    ]
    print("  " + "  ".join(cmd_parts))
    print()

    return scroll_top, total


# ---------------------------------------------------------------------------
# Open in external editor
# ---------------------------------------------------------------------------

def _open_in_vim(filepath):
    """Open a file in vim. Gracefully handles vim not being installed."""
    import shutil
    if not shutil.which("vim"):
        print(f"\n  {DIM}vim is not installed on this system.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return
    try:
        subprocess.call(["vim", filepath])
    except OSError as e:
        print(f"\n  {DIM}Could not open vim: {e}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")


# ---------------------------------------------------------------------------
# Decompile-to-workspace helper
# ---------------------------------------------------------------------------

def _offer_decompile_import(filepath, file_type, label, map_name, project_dir,
                            game_path=None, emotes_conf=None, source_display=None,
                            settings=None, proj_name=None, open_editor=False):
    """Offer to decompile a .pory script and import to workspace as TorScript.

    If open_editor is True, opens the Script Editor on the new file after import.
    """
    try:
        from torch.decompiler import decompile
    except ImportError:
        print(f"\n  {DIM}Decompiler not available.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        print(f"\n  {DIM}Could not read script file.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    torscript, warnings = decompile(content, map_name)
    if not torscript or not torscript.strip():
        print(f"\n  {DIM}Decompiler produced no output for this script.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    print()
    if warnings:
        print(f"  {GOLD}Decompiler warnings:{RST}")
        for w in warnings:
            print(f"    {DIM}- {w}{RST}")
        print()

    # Derive script name from label
    script_name = _strip_label_prefix(label, map_name) if label else "scripts"
    # Sanitise for filename
    script_name = re.sub(r'[^A-Za-z0-9_]', '', script_name)
    if not script_name:
        script_name = "imported"

    workspace_dir = os.path.join(project_dir, map_name)
    dest_path = os.path.join(workspace_dir, f"{script_name}.txt")

    if os.path.exists(dest_path):
        print(f"  {DIM}Workspace file already exists:{RST} {script_name}.txt")
        print(f"  {DIM}Delete or rename it first to re-import.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    try:
        confirm = input(f"  Import to workspace as {WHITE}{script_name}.txt{RST}? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm not in ("", "y", "yes"):
        return

    os.makedirs(workspace_dir, exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(torscript)

    # Ensure setup.pory exists
    try:
        from torch.script_model import _ensure_setup_pory
        _ensure_setup_pory(workspace_dir, map_name)
    except ImportError:
        pass

    print(f"\n  {GREEN}Imported:{RST} {script_name}.txt")

    if open_editor:
        try:
            from torch.script_model import _parse_script
            from torch.script_editor import _script_editor_loop
            script_data = _parse_script(dest_path, emotes_conf)
            _script_editor_loop(script_data, map_name, dest_path,
                               project_dir, game_path, emotes_conf,
                               source_display, settings, proj_name)
        except Exception as e:
            print(f"\n  {RED}Error opening editor: {e}{RST}")
            input(f"  {DIM}Press Enter{RST} > ")
    else:
        input(f"  {DIM}Press Enter{RST} > ")


# ---------------------------------------------------------------------------
# View full script
# ---------------------------------------------------------------------------

def _view_full_script(script_info, label, emotes_conf=None, game_path=None,
                      settings=None, project_dir=None, map_name=None):
    """Show the complete script source for an NPC."""
    clear_screen()
    print()
    print(f"  {WHITE}Script: {GOLD}{label}{RST}")
    print(BAR)

    filepath = script_info.get("filepath")
    file_type = script_info.get("file_type")

    if not filepath or not os.path.isfile(filepath):
        print(f"  {DIM}(script file not found){RST}")
        print()
        input(f"  {DIM}Press Enter{RST} > ")
        return

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        print(f"  {DIM}(could not read file){RST}")
        print()
        input(f"  {DIM}Press Enter{RST} > ")
        return

    if file_type == "pory":
        _view_pory_script(content, label)
    elif file_type == "inc":
        _view_inc_script(content, label)
    else:
        print(f"  {DIM}File: {filepath}{RST}")
        print()
        for line in content.split("\n")[:40]:
            print(f"  {line}")

    print()
    print(f"  {DIM}File: {filepath}{RST}")
    print()
    # Build prompt — add [i]mport option for .pory/.inc files with workspace configured
    can_import = (project_dir and file_type in ("pory", "inc") and filepath)
    import_hint = f"  {_k('i')}{DIM}mport{RST}" if can_import else ""
    choice = input(f"  {DIM}[Enter] back  {_k('v')}{DIM}im{RST}{import_hint} > ").strip().lower()
    if choice == "i" and can_import:
        resolved_map = map_name or os.path.basename(os.path.dirname(filepath))
        _offer_decompile_import(
            filepath, file_type, label, resolved_map, project_dir,
            game_path=game_path, emotes_conf=emotes_conf,
            settings=settings, open_editor=False)
    elif choice == "v" and filepath:
        if file_type == "workspace":
            # Use Scene Editor's validated vim with backup/restore safety net
            from torch.script_model import _parse_script
            from torch.script_editor import _handle_vim_edit
            try:
                script_data = _parse_script(filepath, emotes_conf)
                vim_map = map_name or os.path.basename(os.path.dirname(filepath))
                _handle_vim_edit(script_data, filepath, emotes_conf, vim_map,
                                    game_path, settings)
            except Exception as e:
                print(f"\n  {RED}Error: {e}{RST}")
                input(f"  {DIM}Press Enter{RST} > ")
        else:
            _open_in_vim(filepath)


def _view_pory_script(content, label):
    """Display a Poryscript script block."""
    pat = rf'\bscript\s+{re.escape(label)}\s*\{{'
    match = re.search(pat, content)
    if not match:
        print(f"  {DIM}(script label not found in file){RST}")
        return

    body = _extract_brace_block(content, match.start())
    if body is None:
        print(f"  {DIM}(could not parse script block){RST}")
        return

    print(f"  {CYAN}script{RST} {WHITE}{label}{RST} {{")
    for line in body.strip().split("\n"):
        print(f"    {line.strip()}")
    print("  }")


def _view_inc_script(content, label):
    """Display an .inc assembly script block."""
    pat = rf'^{re.escape(label)}::'
    match = re.search(pat, content, re.MULTILINE)
    if not match:
        print(f"  {DIM}(script label not found in file){RST}")
        return

    # Show lines until next label:: or end
    lines = content[match.start():].split("\n")
    for line in lines[:30]:
        if line.strip() and not line.startswith(label) and re.match(r'^\w+::', line):
            break
        print(f"  {line}")


# ---------------------------------------------------------------------------
# Dialogue editor
# ---------------------------------------------------------------------------

def _edit_npc_dialogue(game_path, map_name, npc, script_info):
    """Edit dialogue for an existing NPC. Returns True if changed."""
    label = npc.get("script", "")
    old_text = script_info.get("text", "")
    file_type = script_info.get("file_type")
    filepath = script_info.get("filepath")

    clear_screen()
    print()
    print(f"  {WHITE}Editing:{RST} {GOLD}{label}{RST}  "
          f"{DIM}({npc.get('display_name', '?')}){RST}")
    print(BAR)

    if old_text:
        readable = _game_text_to_readable(old_text)
        print(f"  {WHITE}Current dialogue:{RST}")
        print()
        for line in readable.split("\n"):
            print(f"    {line}")
        print()
        textbox_preview(old_text)
        print()

    # Prompt for new dialogue
    print(f"  {WHITE}Type new dialogue{RST} {DIM}(or Enter to keep current):{RST}")
    try:
        raw = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return False

    if not raw:
        print(f"  {DIM}(no changes){RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Auto-wrap and preview
    new_text = _readable_to_game_text(raw)
    print()
    textbox_preview(new_text)
    print()

    confirm = input("  Use this? [Y/n] > ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print(f"  {DIM}(cancelled){RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Write back
    return _write_edited_dialogue(game_path, map_name, label, new_text,
                                  script_info)


def _write_edited_dialogue(game_path, map_name, label, new_text, script_info):
    """Write edited dialogue back to the source file. Returns True on success."""
    file_type = script_info.get("file_type")
    filepath = script_info.get("filepath")

    if file_type == "pory" and filepath:
        return _update_pory_dialogue(filepath, label, new_text)
    elif file_type == "inc" and filepath:
        return _update_inc_dialogue(filepath, script_info.get("text_label", ""),
                                    new_text)
    else:
        # No existing file — write new script to scripts.pory
        script_text = _generate_flavor_npc(map_name, label, new_text)
        return _write_script_to_pory(game_path, map_name, script_text)


def _update_pory_dialogue(filepath, label, new_text):
    """Surgical replacement of msgbox text in a .pory file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        print(f"  {RED}Error reading {filepath}: {e}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Find the script block
    pat = rf'\bscript\s+{re.escape(label)}\s*\{{'
    match = re.search(pat, content)
    if not match:
        print(f"  {RED}Could not find script {label} in {filepath}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    block_body = _extract_brace_block(content, match.start())
    if block_body is None:
        print(f"  {RED}Could not parse script block{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Replace msgbox text in the block
    # Try format() form first, then plain form
    new_block = _replace_msgbox_text(block_body, new_text)
    if new_block == block_body:
        print(f"  {RED}Could not find msgbox to update{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Reconstruct — find exact brace positions
    brace_start = content.find("{", match.start())
    depth, brace_end = 0, brace_start
    for i in range(brace_start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                brace_end = i
                break

    updated = content[:brace_start + 1] + new_block + content[brace_end:]

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(updated)
    except OSError as e:
        print(f"  {RED}Error writing {filepath}: {e}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    print(f"  {GREEN}Updated {label} in {os.path.basename(filepath)}{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return True


def _replace_msgbox_text(block_body, new_text):
    """Replace the first msgbox text in a script block body."""
    # Try format() form: msgbox(format("..."), TYPE)
    fmt_pat = r'(msgbox\s*\(\s*format\s*\(\s*)"(?:[^"\\]|\\.)*"(\s*\)\s*,\s*\w+\s*\))'
    fmt_m = re.search(fmt_pat, block_body)
    if fmt_m:
        return (block_body[:fmt_m.start()] +
                fmt_m.group(1) + '"' + new_text + '"' + fmt_m.group(2) +
                block_body[fmt_m.end():])

    # Try plain form: msgbox("...", TYPE)
    plain_pat = r'(msgbox\s*\(\s*)"(?:[^"\\]|\\.)*"(\s*,\s*\w+\s*\))'
    plain_m = re.search(plain_pat, block_body)
    if plain_m:
        return (block_body[:plain_m.start()] +
                plain_m.group(1) + '"' + new_text + '"' + plain_m.group(2) +
                block_body[plain_m.end():])

    return block_body


def _update_inc_dialogue(filepath, text_label, new_text):
    """Surgical replacement of .string lines in a .inc file."""
    if not text_label:
        print(f"  {RED}No text label found for this script{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"  {RED}Error reading {filepath}: {e}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Find the text label line
    label_idx = None
    for i, line in enumerate(lines):
        if line.strip() == f"{text_label}:":
            label_idx = i
            break

    if label_idx is None:
        print(f"  {RED}Could not find {text_label}: in {filepath}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Find the range of .string lines after the label
    string_start = None
    string_end = None
    for i in range(label_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("@"):
            continue
        if stripped.startswith('.string'):
            if string_start is None:
                string_start = i
            string_end = i + 1
        else:
            break

    if string_start is None:
        print(f"  {RED}No .string lines found after {text_label}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Build new .string lines from the new text
    new_string_lines = _text_to_inc_strings(new_text)

    # Replace
    new_lines = lines[:string_start] + new_string_lines + lines[string_end:]

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except OSError as e:
        print(f"  {RED}Error writing {filepath}: {e}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    print(f"  {GREEN}Updated {text_label} in {os.path.basename(filepath)}{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return True


def _text_to_inc_strings(text):
    """Convert game-format text to .string assembly lines.

    Splits on \\p and \\n to produce readable .string lines.
    Adds trailing $ to the last line.
    """
    if not text:
        return ['    .string "$"\n']

    # Ensure text ends with $
    clean = text.rstrip("$")
    # Split into chunks at \\p and \\n, keeping delimiters at end of each chunk
    parts = re.split(r'(\\[np])', clean)

    string_lines = []
    current = ""
    for part in parts:
        if part in ("\\n", "\\p"):
            current += part
            string_lines.append(current)
            current = ""
        else:
            current += part

    if current:
        string_lines.append(current)

    # Build .string lines
    result = []
    for i, chunk in enumerate(string_lines):
        is_last = (i == len(string_lines) - 1)
        suffix = "$" if is_last else ""
        result.append(f'    .string "{chunk}{suffix}"\n')

    return result


# ---------------------------------------------------------------------------
# Wizard — template generation
# ---------------------------------------------------------------------------

def _npc_wizard(game_path, map_name, proj_name):
    """Template picker + wizard for creating new NPC scripts."""
    clear_screen()
    print()
    print(f"  {WHITE}NPC Wizard{RST}  {DIM}{map_name}{RST}")
    print(BAR)
    print()

    # Check for dead scripts and scriptless NPCs
    dead = _scan_dead_scripts(game_path, map_name)
    scriptless = _scan_scriptless_npcs(game_path, map_name)
    if dead:
        print(f"  {BOLD_RED}{len(dead)} NPC(s) with dead script references{RST}")
        print(f"  {GOLD}[f]{RST} {WHITE}Fix dead scripts{RST}")
        print()
    if scriptless:
        from torch.names import _const_to_human_name
        print(f"  {RED}{len(scriptless)} NPC(s) with no script assigned{RST}")
        for idx, obj in scriptless:
            gfx = obj.get("graphics_id", "")
            name = _const_to_human_name(gfx, "OBJ_EVENT_GFX_")
            x, y = obj.get("x", "?"), obj.get("y", "?")
            print(f"    {DIM}#{idx + 1} {name} at ({x}, {y}){RST}")
        print(f"  {GOLD}[p]{RST} {WHITE}Add placeholder scripts{RST}")
        print()

    print(f"  {DIM}--- Infrastructure ---{RST}")
    print(f"  {GOLD}[1]{RST} {WHITE}Nurse Joy{RST}     {DIM}Pokemon Center healing{RST}")
    print(f"  {GOLD}[2]{RST} {WHITE}PC{RST}            {DIM}Storage system access point{RST}")
    print(f"  {GOLD}[3]{RST} {WHITE}Sign{RST}          {DIM}Readable sign or plaque{RST}")
    print(f"  {DIM}[4] Mart Clerk    (coming soon){RST}")
    print(f"  {DIM}[5] Item Ball     (coming soon){RST}")
    print()
    print(f"  {DIM}--- Script Only ---{RST}")
    print(f"  {GOLD}[6]{RST} {WHITE}Flavor NPC{RST}    {DIM}Just says something{RST}")
    print(f"  {GOLD}[7]{RST} {WHITE}Multi-state{RST}   {DIM}Different dialogue based on flags{RST}")
    print(f"  {GOLD}[8]{RST} {WHITE}Item Giver{RST}    {DIM}Gives the player an item once{RST}")
    print()

    try:
        choice = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if choice == "f" and dead:
        _show_dead_script_fixer(game_path, map_name, dead, proj_name)
        try:
            from torch.project_files import clear_project_cache
            clear_project_cache()
        except ImportError:
            pass
        return True
    elif choice == "p" and scriptless:
        _fix_scriptless_npcs(game_path, map_name, scriptless)
        try:
            from torch.project_files import clear_project_cache
            clear_project_cache()
        except ImportError:
            pass
        return True
    elif choice == "1":
        return _wizard_nurse(game_path, map_name, proj_name)
    elif choice == "2":
        return _wizard_pc(game_path, map_name, proj_name)
    elif choice == "3":
        return _wizard_infra_sign(game_path, map_name, proj_name)
    elif choice == "6":
        return _wizard_flavor(game_path, map_name)
    elif choice == "7":
        return _wizard_multi_state(game_path, map_name)
    elif choice == "8":
        return _wizard_item_giver(game_path, map_name)
    else:
        return False


def _wizard_prompt_name(map_name, npc_type="NPC"):
    """Prompt for an NPC name and return the script label."""
    print(f"  {WHITE}{npc_type} name{RST} {DIM}(used in script label){RST}")
    print(f"  {DIM}Example: Villager, Kid, OldMan{RST}")
    try:
        name = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not name:
        return None
    # Sanitize — PascalCase, no spaces
    safe = re.sub(r'[^A-Za-z0-9]', '', name)
    if not safe:
        return None
    return f"{map_name}_{safe}"


def _wizard_flavor(game_path, map_name):
    """Wizard: Flavor NPC — just says something."""
    print()
    label = _wizard_prompt_name(map_name, "NPC")
    if not label:
        return False

    print()
    text = dialogue_prompt("What does this NPC say?")
    if not text:
        return False

    script = _generate_flavor_npc(map_name, label, text)
    return _wizard_write_and_confirm(game_path, map_name, label, script)


def _wizard_sign(game_path, map_name):
    """Wizard: Sign / Readable."""
    print()
    label = _wizard_prompt_name(map_name, "Sign")
    if not label:
        return False

    print()
    text = dialogue_prompt("What does the sign say?")
    if not text:
        return False

    script = _generate_sign(map_name, label, text)
    return _wizard_write_and_confirm(game_path, map_name, label, script)


def _wizard_item_giver(game_path, map_name):
    """Wizard: Item Giver."""
    print()
    label = _wizard_prompt_name(map_name, "NPC")
    if not label:
        return False

    print()
    before_text = dialogue_prompt("Dialogue before giving the item?")
    if not before_text:
        return False

    print()
    try:
        from torch.pickers import pick_item
        item = pick_item(game_path)
    except ImportError:
        item = None
    if not item:
        print(f"  {WHITE}Item constant{RST} {DIM}(e.g., ITEM_POTION, ITEM_TM01){RST}")
        try:
            item = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return False
    if not item:
        return False

    print()
    print(f"  {WHITE}Flag constant{RST} {DIM}(to track if item was given){RST}")
    try:
        from torch.pickers import pick_flag
        flag = pick_flag(game_path)
    except ImportError:
        print(f"  {DIM}(Flag picker not available, type manually){RST}")
        try:
            flag = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return False
    if not flag:
        return False

    print()
    after_text = dialogue_prompt("Dialogue after giving the item?")
    if not after_text:
        return False

    script = _generate_item_giver(map_name, label, item, flag,
                                  before_text, after_text)
    return _wizard_write_and_confirm(game_path, map_name, label, script)


def _wizard_multi_state(game_path, map_name):
    """Wizard: Multi-state NPC."""
    print()
    label = _wizard_prompt_name(map_name, "NPC")
    if not label:
        return False

    print()
    print(f"  {WHITE}How many states?{RST} {DIM}(2-4){RST}")
    try:
        num_str = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return False

    try:
        num_states = int(num_str)
    except ValueError:
        print(f"  {RED}Invalid number{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    if num_states < 2 or num_states > 4:
        print(f"  {RED}Must be 2-4 states{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    states = []
    try:
        from torch.pickers import pick_flag
        has_picker = True
    except ImportError:
        has_picker = False

    # Collect states (initial state has no flag)
    print()
    initial_text = dialogue_prompt("Initial dialogue (before any flags set)?")
    if not initial_text:
        return False
    states.append({"flag": None, "text": initial_text})

    for i in range(1, num_states):
        print()
        print(f"  {WHITE}State {i + 1} of {num_states}{RST}")
        if has_picker:
            flag = pick_flag(game_path)
        else:
            print(f"  {WHITE}Flag that activates this state:{RST}")
            flag = input("  > ").strip()
        if not flag:
            return False

        text = dialogue_prompt(f"Dialogue for state {i + 1}?")
        if not text:
            return False
        states.append({"flag": flag, "text": text})

    script = _generate_multi_state(map_name, label, states)
    return _wizard_write_and_confirm(game_path, map_name, label, script)


def _wizard_write_and_confirm(game_path, map_name, label, script):
    """Preview and confirm a wizard-generated script, then write it."""
    print()
    print(f"  {WHITE}Generated script:{RST}")
    print(BAR)
    for line in script.strip().split("\n"):
        print(f"  {line}")
    print(BAR)
    print()

    try:
        confirm = input("  Write to scripts.pory? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if confirm not in ("", "y", "yes"):
        print(f"  {DIM}(cancelled){RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    ok = _write_script_to_pory(game_path, map_name, script)
    if ok:
        _compile_pory(game_path, map_name)
        _offer_map_json_wiring(game_path, map_name, label)
    return ok


def _offer_map_json_wiring(game_path, map_name, label):
    """Offer to update an NPC's script field in map.json."""
    print()
    print(f"  {DIM}To wire this script to an NPC, set the NPC's Script field to:{RST}")
    print(f"  {GOLD}{label}{RST}")
    print()
    try:
        wire = input("  Update map.json automatically? [y/N] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if wire not in ("y", "yes"):
        print(f"  {DIM}(Set it manually in Porymap's NPC properties){RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    # Show NPC picker
    npcs = get_map_objects(game_path, map_name)
    if not npcs:
        print(f"  {RED}No NPCs found on {map_name}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    print()
    print(f"  {WHITE}Which NPC should use this script?{RST}")
    for i, npc in enumerate(npcs, 1):
        script_lbl = npc.get("script", "") or "(no script)"
        print(f"  {GOLD}[{i}]{RST} {npc['display_name']:<16} {DIM}{script_lbl}{RST}")
    print()

    try:
        pick = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    try:
        idx = int(pick) - 1
    except ValueError:
        return

    if idx < 0 or idx >= len(npcs):
        return

    _update_map_json_script(game_path, map_name, idx, label)


def _update_map_json_script(game_path, map_name, npc_idx, label):
    """Update an NPC's script field in map.json."""
    map_json_path = os.path.join(game_path, "data", "maps", map_name, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  {RED}Error reading map.json: {e}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    events = data.get("object_events", [])
    if npc_idx >= len(events):
        print(f"  {RED}NPC index out of range{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    events[npc_idx]["script"] = label

    try:
        with open(map_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        print(f"  {RED}Error writing map.json: {e}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    print(f"  {GREEN}Updated NPC #{npc_idx + 1} script to {label}{RST}")
    input(f"  {DIM}Press Enter{RST} > ")


# ---------------------------------------------------------------------------
# Template generators
# ---------------------------------------------------------------------------

def _generate_flavor_npc(map_name, label, text):
    """Generate a simple Flavor NPC script."""
    return (
        f'script {label} {{\n'
        f'    msgbox(format("{text}"), MSGBOX_NPC)\n'
        f'}}\n'
    )


def _generate_sign(map_name, label, text):
    """Generate a Sign / Readable script."""
    return (
        f'script {label} {{\n'
        f'    msgbox(format("{text}"), MSGBOX_SIGN)\n'
        f'}}\n'
    )


def _generate_item_giver(map_name, label, item, flag, before_text, after_text):
    """Generate an Item Giver script."""
    return (
        f'script {label} {{\n'
        f'    lock\n'
        f'    faceplayer\n'
        f'    if (flag({flag})) {{\n'
        f'        msgbox(format("{after_text}"), MSGBOX_DEFAULT)\n'
        f'        release\n'
        f'        end\n'
        f'    }}\n'
        f'    msgbox(format("{before_text}"), MSGBOX_DEFAULT)\n'
        f'    giveitem({item})\n'
        f'    if (var(VAR_RESULT) == FALSE) {{\n'
        f'        msgbox(format("Your bag is too full."), MSGBOX_DEFAULT)\n'
        f'        release\n'
        f'        end\n'
        f'    }}\n'
        f'    setflag({flag})\n'
        f'    release\n'
        f'    end\n'
        f'}}\n'
    )


def _generate_multi_state(map_name, label, states):
    """Generate a Multi-state NPC script.

    states: list of {"flag": str|None, "text": str}
    First state has flag=None (initial/default state).
    """
    lines = [
        f'script {label} {{',
        '    lock',
        '    faceplayer',
    ]

    # Add flag checks in reverse order (highest flag first)
    for state in reversed(states[1:]):
        lines.append(f'    if (flag({state["flag"]})) {{')
        lines.append(f'        msgbox(format("{state["text"]}"), MSGBOX_DEFAULT)')
        lines.append('        release')
        lines.append('        end')
        lines.append('    }')

    # Default/initial state (no flag check)
    lines.append(f'    msgbox(format("{states[0]["text"]}"), MSGBOX_DEFAULT)')
    lines.append('    release')
    lines.append('    end')
    lines.append('}')

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Infrastructure templates — registry
# ---------------------------------------------------------------------------

INFRA_TEMPLATES = [
    {
        "name": "Nurse Joy",
        "key": "nurse",
        "description": "Pokemon Center healing",
        "event_type": "object_event",
        "defaults": {
            "graphics_id": "OBJ_EVENT_GFX_NURSE",
            "x": 7, "y": 2,
            "elevation": 3,
            "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
            "movement_range_x": 0, "movement_range_y": 0,
            "trainer_type": "TRAINER_TYPE_NONE",
            "trainer_sight_or_berry_tree_id": "0",
            "flag": "0",
        },
        "shared_script": "Common_EventScript_PkmnCenterNurse",
        "needs_wrapper": True,
    },
    {
        "name": "PC",
        "key": "pc",
        "description": "Storage system access point",
        "event_type": "bg_event",
        "defaults": {
            "type": "sign",
            "elevation": 0,
            "player_facing_dir": "BG_EVENT_PLAYER_FACING_ANY",
        },
        "shared_script": "EventScript_PC",
        "needs_wrapper": False,
    },
    {
        "name": "Sign",
        "key": "sign",
        "description": "Readable sign or plaque",
        "event_type": "bg_event",
        "defaults": {
            "type": "sign",
            "elevation": 0,
            "player_facing_dir": "BG_EVENT_PLAYER_FACING_ANY",
        },
        "shared_script": None,
        "needs_wrapper": True,
    },
]


# ---------------------------------------------------------------------------
# Infrastructure — map.json writers
# ---------------------------------------------------------------------------

def _add_object_event(game_path, map_name, obj_data):
    """Append a new object_event to map.json.

    Returns the 1-based index of the new NPC, or None on failure.
    """
    map_json_path = os.path.join(
        game_path, "data", "maps", map_name, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    events = data.get("object_events")
    if not isinstance(events, list):
        events = []
        data["object_events"] = events

    events.append(obj_data)
    new_index = len(events)  # 1-based

    try:
        with open(map_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError:
        return None

    _clear_project_cache()
    return new_index


def _add_bg_event(game_path, map_name, bg_data):
    """Append a new bg_event to map.json.

    Returns the 1-based index of the new bg_event, or None on failure.
    """
    map_json_path = os.path.join(
        game_path, "data", "maps", map_name, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    events = data.get("bg_events")
    if not isinstance(events, list):
        events = []
        data["bg_events"] = events

    events.append(bg_data)
    new_index = len(events)  # 1-based

    try:
        with open(map_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError:
        return None

    _clear_project_cache()
    return new_index


def _clear_project_cache():
    """Clear the project_files cache after map.json changes."""
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Dead script scanner
# ---------------------------------------------------------------------------

def _scan_dead_scripts(game_path, map_name):
    """Scan a map's object_events for NPCs with dead/missing scripts.

    Returns list of (index, npc_dict, reason) for each dead-script NPC.
    index is 0-based position in object_events.
    """
    map_dir = os.path.join(game_path, "data", "maps", map_name)
    map_json_path = os.path.join(map_dir, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    events = data.get("object_events", [])
    if not events:
        return []

    # Load local script files for checking
    local_labels = _collect_local_labels(map_dir)

    dead = []
    for i, obj in enumerate(events):
        script = obj.get("script", "")
        if not script or script in ("0x0", "0"):
            continue
        if _is_shared_script(script):
            continue
        if script in local_labels:
            continue
        reason = _classify_dead_reason(script, local_labels, map_name)
        dead.append((i, obj, reason))

    return dead


def _scan_scriptless_npcs(game_path, map_name):
    """Scan a map's object_events for NPCs with no script assigned.

    Returns list of (index, npc_dict) for each scriptless NPC.
    index is 0-based position in object_events.
    """
    map_json_path = os.path.join(game_path, "data", "maps", map_name, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    events = data.get("object_events", [])
    scriptless = []
    for i, obj in enumerate(events):
        script = obj.get("script", "")
        if not script or script in ("0x0", "0"):
            scriptless.append((i, obj))

    return scriptless


def _collect_local_labels(map_dir):
    """Collect all script labels defined in a map's script files."""
    labels = set()

    # Check scripts.pory
    pory_path = os.path.join(map_dir, "scripts.pory")
    if os.path.isfile(pory_path):
        try:
            with open(pory_path, "r", encoding="utf-8") as f:
                content = f.read()
            for m in re.finditer(r'\bscript\s+(\w+)\s*\{', content):
                labels.add(m.group(1))
        except OSError:
            pass

    # Check scripts.inc — real labels (not return stubs)
    inc_path = os.path.join(map_dir, "scripts.inc")
    if os.path.isfile(inc_path):
        try:
            with open(inc_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for idx, line in enumerate(lines):
                m = re.match(r'^(\w+)::', line)
                if m:
                    label = m.group(1)
                    # Check if it's a return stub (next non-empty line is just "return")
                    if not _is_return_stub(lines, idx):
                        labels.add(label)
        except OSError:
            pass

    return labels


def _is_return_stub(lines, label_idx):
    """Check if a label at label_idx is just a return stub."""
    for i in range(label_idx + 1, min(label_idx + 5, len(lines))):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("@"):
            continue
        return stripped == "return"
    return False


def _is_shared_script(script):
    """Check if a script label refers to a known shared/global script."""
    shared_prefixes = (
        "Common_EventScript_",
        "EventScript_PC",
        "ProfileMan_EventScript_",
        "EventScript_Pokemon",
    )
    return script.startswith(shared_prefixes)


def _classify_dead_reason(script, local_labels, map_name):
    """Classify why a script is dead."""
    # Check if it references a different map's scripts (vanilla leftover)
    parts = script.split("_EventScript_")
    if len(parts) == 2:
        script_map = parts[0]
        if script_map != map_name:
            return f"references removed map: {script_map}"
    return "script not found in local files"


# ---------------------------------------------------------------------------
# Dead script fix workflow
# ---------------------------------------------------------------------------

def _show_dead_script_fixer(game_path, map_name, dead_scripts, proj_name):
    """Show dead script fix menu and handle rewiring."""
    clear_screen()
    print()
    print(f"  {WHITE}Dead Script Fixer{RST}  {DIM}{map_name}{RST}")
    print(BAR)
    print()
    print(f"  {BOLD_RED}{len(dead_scripts)} NPC(s) with dead script references{RST}")
    print()

    for i, (idx, obj, reason) in enumerate(dead_scripts):
        gfx = obj.get("graphics_id", "?")
        script = obj.get("script", "?")
        x, y = obj.get("x", "?"), obj.get("y", "?")
        print(f"  {GOLD}[{i + 1}]{RST} {WHITE}#{idx + 1}{RST} "
              f"{gfx} at ({x}, {y})")
        print(f"       {DIM}{script}{RST}")
        print(f"       {RED}{reason}{RST}")
        print()

    print(f"  {GOLD}[a]{RST} {WHITE}Fix all{RST}  {DIM}auto-rewire where possible{RST}")
    print(f"  {DIM}[q] back{RST}")
    print()

    try:
        choice = input(f"  {GOLD}>{RST} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if choice == "q":
        return

    if choice == "a":
        _fix_all_dead_scripts(game_path, map_name, dead_scripts)
        return

    try:
        pick = int(choice) - 1
    except ValueError:
        return

    if 0 <= pick < len(dead_scripts):
        idx, obj, reason = dead_scripts[pick]
        _fix_single_dead_script(game_path, map_name, idx, obj)


def _fix_all_dead_scripts(game_path, map_name, dead_scripts):
    """Auto-fix all dead scripts where possible."""
    fixed = 0
    for idx, obj, reason in dead_scripts:
        gfx = obj.get("graphics_id", "")
        if gfx == "OBJ_EVENT_GFX_NURSE":
            if _rewire_nurse(game_path, map_name, idx, obj, auto=True):
                fixed += 1
        else:
            # Create a placeholder flavor script
            if _create_placeholder_script(game_path, map_name, idx, obj):
                fixed += 1

    # Compile .pory -> .inc so the build system picks up new scripts
    if fixed:
        _compile_pory(game_path, map_name)

    print()
    print(f"  {GREEN}Fixed {fixed}/{len(dead_scripts)} dead scripts{RST}")
    input(f"  {DIM}Press Enter{RST} > ")


def _fix_single_dead_script(game_path, map_name, idx, obj):
    """Fix a single dead script interactively."""
    gfx = obj.get("graphics_id", "")

    print()
    if gfx == "OBJ_EVENT_GFX_NURSE":
        print(f"  {WHITE}Detected: Nurse NPC{RST}")
        print(f"  {GOLD}[1]{RST} Rewire to working nurse script")
        print(f"  {GOLD}[2]{RST} Assign new flavor dialogue")
        print(f"  {DIM}[q] skip{RST}")
    else:
        print(f"  {WHITE}NPC: {gfx}{RST}")
        print(f"  {GOLD}[1]{RST} Assign new flavor dialogue")
        print(f"  {GOLD}[2]{RST} Enter script label manually")
        print(f"  {DIM}[q] skip{RST}")

    print()
    try:
        pick = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if pick == "q":
        return

    wrote = False
    if gfx == "OBJ_EVENT_GFX_NURSE":
        if pick == "1":
            wrote = _rewire_nurse(game_path, map_name, idx, obj, auto=False)
        elif pick == "2":
            wrote = _create_placeholder_script(game_path, map_name, idx, obj)
    else:
        if pick == "1":
            wrote = _create_placeholder_script(game_path, map_name, idx, obj)
        elif pick == "2":
            _manual_rewire(game_path, map_name, idx)

    if wrote:
        _compile_pory(game_path, map_name)


def _rewire_nurse(game_path, map_name, npc_idx, obj, auto=False):
    """Rewire a nurse NPC to use the shared nurse script.

    Creates a wrapper script and updates map.json.
    Returns True on success.
    """
    # Determine the local_id for the nurse (1-based array position)
    local_id = npc_idx + 1

    label = f"{map_name}_EventScript_Nurse"
    wrapper = _generate_nurse_wrapper(map_name, label, local_id)

    if not auto:
        print()
        print(f"  {WHITE}Will create:{RST}")
        for line in wrapper.strip().split("\n"):
            print(f"    {line}")
        print()
        try:
            confirm = input("  Proceed? [Y/n] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if confirm not in ("", "y", "yes"):
            return False

    # Write wrapper script
    ok = _write_script_to_pory(game_path, map_name, wrapper)
    if not ok:
        return False

    # Update map.json script field
    _update_map_json_script(game_path, map_name, npc_idx, label)
    if not auto:
        print(f"  {GREEN}Nurse rewired successfully{RST}")
    return True


def _create_placeholder_script(game_path, map_name, npc_idx, obj):
    """Create a placeholder flavor script for a dead-script NPC."""
    gfx = obj.get("graphics_id", "NPC")
    from torch.names import _const_to_human_name
    name = _const_to_human_name(gfx, "OBJ_EVENT_GFX_")
    safe_name = re.sub(r'[^A-Za-z0-9]', '', name)
    label = f"{map_name}_EventScript_{safe_name}"

    script = _generate_flavor_npc(
        map_name, label, "..."
    )

    ok = _write_script_to_pory(game_path, map_name, script)
    if not ok:
        return False

    _update_map_json_script(game_path, map_name, npc_idx, label)
    print(f"  {GREEN}Created placeholder for {name}: {label}{RST}")
    return True


def _fix_scriptless_npcs(game_path, map_name, scriptless):
    """Add placeholder scripts to all scriptless NPCs."""
    from torch.names import _const_to_human_name
    print()
    print(f"  {WHITE}Adding placeholder scripts to {len(scriptless)} NPC(s)...{RST}")
    print()

    fixed = 0
    for idx, obj in scriptless:
        if _create_placeholder_script(game_path, map_name, idx, obj):
            fixed += 1

    if fixed:
        _compile_pory(game_path, map_name)

    print()
    print(f"  {GREEN}Fixed {fixed}/{len(scriptless)} scriptless NPCs{RST}")
    print(f"  {DIM}Reload Porymap to see changes.{RST}")
    input(f"  {DIM}Press Enter{RST} > ")


def _manual_rewire(game_path, map_name, npc_idx):
    """Let user type a script label to rewire an NPC to."""
    print()
    print(f"  {WHITE}Enter script label:{RST}")
    try:
        label = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not label:
        return
    _update_map_json_script(game_path, map_name, npc_idx, label)


# ---------------------------------------------------------------------------
# Nurse template — wrapper generator
# ---------------------------------------------------------------------------

def _generate_nurse_wrapper(map_name, label, local_id):
    """Generate a thin wrapper that calls the vanilla shared nurse script.

    Sets VAR_0x800B to the nurse's local object ID so the shared script
    can animate the correct NPC, then delegates to
    Common_EventScript_PkmnCenterNurse which handles greeting, Gold Card
    detection, heal animation, Pokerus check, and farewell.
    """
    return (
        f'script {label} {{\n'
        f'    lock\n'
        f'    faceplayer\n'
        f'    setvar(VAR_0x800B, {local_id})\n'
        f'    call(Common_EventScript_PkmnCenterNurse)\n'
        f'    waitmessage\n'
        f'    waitbuttonpress\n'
        f'    release\n'
        f'    end\n'
        f'}}\n'
    )


# ---------------------------------------------------------------------------
# Infrastructure template wizards
# ---------------------------------------------------------------------------

def _prompt_coordinate(label, default=None):
    """Prompt for a coordinate value. Returns int or None."""
    hint = f" {DIM}[{default}]{RST}" if default is not None else ""
    print(f"    {WHITE}{label}{RST}{hint}")
    try:
        raw = input("    > ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw and default is not None:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"    {RED}Invalid number{RST}")
        return None


def _wizard_nurse(game_path, map_name, proj_name):
    """Infrastructure wizard: Nurse Joy."""
    tmpl = next(t for t in INFRA_TEMPLATES if t["key"] == "nurse")
    clear_screen()
    print()
    print(f"  {WHITE}Nurse Joy{RST}")
    print(BAR)
    print()
    print(f"  {DIM}{tmpl['description']}. Uses the shared nurse script{RST}")
    print(f"  {DIM}with heal animation and Pokerus check.{RST}")
    print()

    # Check for existing nurse NPC
    existing = _find_existing_nurse(game_path, map_name)
    if existing is not None:
        idx, obj, script_alive = existing
        script = obj.get("script", "")
        x, y = obj.get("x", "?"), obj.get("y", "?")
        if script_alive:
            print(f"  {GREEN}Nurse already exists at ({x}, {y}){RST}")
            print(f"  {DIM}Script: {script}{RST}")
            print()
            input(f"  {DIM}Press Enter{RST} > ")
            return False
        print(f"  {GOLD}Found existing Nurse at ({x}, {y}){RST}")
        print(f"  {DIM}Current script: {script} (missing){RST}")
        print()
        try:
            rewire = input("  Rewire to working nurse script? [Y/n] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if rewire in ("", "y", "yes"):
            result = _rewire_nurse(game_path, map_name, idx, obj, auto=False)
            if result:
                _compile_pory(game_path, map_name)
            return result
        print(f"  {DIM}(creating new nurse NPC instead){RST}")
        print()

    # Prompt for coordinates
    print(f"  {WHITE}Position:{RST}")
    defaults = tmpl["defaults"]
    x = _prompt_coordinate("X", defaults["x"])
    if x is None:
        return False
    y = _prompt_coordinate("Y", defaults["y"])
    if y is None:
        return False

    # Build object_event data
    obj_data = dict(defaults)
    obj_data["x"] = x
    obj_data["y"] = y
    # script will be set after we know the index
    obj_data["script"] = f"{map_name}_EventScript_Nurse"

    # Preview
    print()
    print(f"  {WHITE}Preview:{RST}")
    print(f"    map.json: New object_event "
          f"({defaults['graphics_id']} at {x},{y})")
    print(f"    scripts.pory: {obj_data['script']}")
    print(f"      {DIM}-> calls {tmpl['shared_script']}{RST}")
    print()

    try:
        confirm = input("  Write? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if confirm not in ("", "y", "yes"):
        return False

    # Add object_event to map.json
    new_idx = _add_object_event(game_path, map_name, obj_data)
    if new_idx is None:
        print(f"  {RED}Failed to write map.json{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Generate wrapper script with the correct local_id
    label = obj_data["script"]
    wrapper = _generate_nurse_wrapper(map_name, label, new_idx)
    ok = _write_script_to_pory(game_path, map_name, wrapper)
    if not ok:
        return False

    _compile_pory(game_path, map_name)

    print(f"  {GREEN}Nurse added as NPC #{new_idx}{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return True


def _find_existing_nurse(game_path, map_name):
    """Check if the map already has a nurse NPC.

    Returns (index, obj_dict, script_alive) or None.
    script_alive is True if the nurse's script file exists.
    """
    map_json_path = os.path.join(
        game_path, "data", "maps", map_name, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    events = data.get("object_events", [])
    for i, obj in enumerate(events):
        if obj.get("graphics_id") == "OBJ_EVENT_GFX_NURSE":
            script = obj.get("script", "")
            _, ftype = _find_script_file(game_path, map_name, script)
            return (i, obj, ftype is not None)
    return None


# ---------------------------------------------------------------------------
# Public nurse script validation and fix
# ---------------------------------------------------------------------------

def validate_nurse_script(game_path, map_name):
    """Check nurse NPC script health in a map.

    Returns a dict with:
        found (bool): Whether a nurse NPC exists
        npc_index (int): 0-based index in object_events
        local_id (int): 1-based local ID
        script (str): The script label assigned to the nurse
        script_ok (bool): Whether the script resolves to a real definition
        fixable (bool): Whether TORCH can auto-fix the script

    Returns None if no nurse NPC exists in the map.
    """
    map_json_path = os.path.join(
        game_path, "data", "maps", map_name, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    events = data.get("object_events", [])
    for i, obj in enumerate(events):
        if obj.get("graphics_id") != "OBJ_EVENT_GFX_NURSE":
            continue

        script = obj.get("script", "")
        local_id = i + 1

        # Empty / null script
        if not script or script in ("0", "0x0", "NULL",
                                    "Common_EventScript_NopReturn"):
            return {
                "found": True, "npc_index": i, "local_id": local_id,
                "script": script, "script_ok": False, "fixable": True,
            }

        # Shared scripts are globally available — always ok
        if _is_shared_script(script):
            return {
                "found": True, "npc_index": i, "local_id": local_id,
                "script": script, "script_ok": True, "fixable": False,
            }

        # Check if script definition exists in local files
        _, ftype = _find_script_file(game_path, map_name, script)
        script_ok = ftype is not None

        return {
            "found": True, "npc_index": i, "local_id": local_id,
            "script": script, "script_ok": script_ok,
            "fixable": not script_ok,
        }

    return None


def fix_nurse_script(game_path, map_name):
    """Auto-fix a broken nurse script in the given map.

    Generates the wrapper script, writes to scripts.pory, compiles to
    scripts.inc, and updates map.json.  Returns True on success.
    """
    map_json_path = os.path.join(
        game_path, "data", "maps", map_name, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False

    events = data.get("object_events", [])
    nurse_idx = None
    for i, obj in enumerate(events):
        if obj.get("graphics_id") == "OBJ_EVENT_GFX_NURSE":
            nurse_idx = i
            break
    if nurse_idx is None:
        return False

    local_id = nurse_idx + 1
    label = f"{map_name}_EventScript_Nurse"
    wrapper = _generate_nurse_wrapper(map_name, label, local_id)

    ok = _write_script_to_pory(game_path, map_name, wrapper)
    if not ok:
        return False

    # Update map.json script field directly (non-interactive)
    events[nurse_idx]["script"] = label
    try:
        with open(map_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError:
        return False

    _compile_pory(game_path, map_name)
    return True


def _wizard_pc(game_path, map_name, proj_name):
    """Infrastructure wizard: PC storage access point."""
    tmpl = next(t for t in INFRA_TEMPLATES if t["key"] == "pc")
    clear_screen()
    print()
    print(f"  {WHITE}PC{RST}")
    print(BAR)
    print()
    print(f"  {DIM}{tmpl['description']}.{RST}")
    print(f"  {DIM}BG event — uses map tileset for the PC graphic.{RST}")
    print()

    # Prompt for coordinates
    print(f"  {WHITE}Position:{RST}")
    x = _prompt_coordinate("X", None)
    if x is None:
        return False
    y = _prompt_coordinate("Y", None)
    if y is None:
        return False

    # Build bg_event
    bg_data = dict(tmpl["defaults"])
    bg_data["x"] = x
    bg_data["y"] = y
    bg_data["script"] = tmpl["shared_script"]

    # Preview
    print()
    print(f"  {WHITE}Preview:{RST}")
    print(f"    map.json: New bg_event (sign at {x},{y})")
    print(f"    script: {tmpl['shared_script']} (shared, no wrapper needed)")
    print()

    try:
        confirm = input("  Write? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if confirm not in ("", "y", "yes"):
        return False

    new_idx = _add_bg_event(game_path, map_name, bg_data)
    if new_idx is None:
        print(f"  {RED}Failed to write map.json{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    print(f"  {GREEN}PC added as bg_event #{new_idx}{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return True


def _wizard_infra_sign(game_path, map_name, proj_name):
    """Infrastructure wizard: Sign (bg_event + script)."""
    clear_screen()
    print()
    print(f"  {WHITE}Sign{RST}")
    print(BAR)
    print()
    print(f"  {DIM}Readable sign or plaque. Creates bg_event + script.{RST}")
    print()

    # Sign name
    print(f"  {WHITE}Sign name{RST} {DIM}(used in script label){RST}")
    print(f"  {DIM}Example: TownSign, Plaque, Notice{RST}")
    try:
        name = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not name:
        return False
    safe = re.sub(r'[^A-Za-z0-9]', '', name)
    if not safe:
        return False

    # Coordinates
    print()
    print(f"  {WHITE}Position:{RST}")
    x = _prompt_coordinate("X", None)
    if x is None:
        return False
    y = _prompt_coordinate("Y", None)
    if y is None:
        return False

    # Facing direction
    print()
    print(f"  {WHITE}Facing direction:{RST}")
    print(f"  {GOLD}[1]{RST} Any direction {DIM}(default){RST}")
    print(f"  {GOLD}[2]{RST} North")
    print(f"  {GOLD}[3]{RST} South")
    print(f"  {GOLD}[4]{RST} East")
    print(f"  {GOLD}[5]{RST} West")
    try:
        dir_pick = input(f"  {GOLD}>{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return False

    facing_map = {
        "": "BG_EVENT_PLAYER_FACING_ANY",
        "1": "BG_EVENT_PLAYER_FACING_ANY",
        "2": "BG_EVENT_PLAYER_FACING_NORTH",
        "3": "BG_EVENT_PLAYER_FACING_SOUTH",
        "4": "BG_EVENT_PLAYER_FACING_EAST",
        "5": "BG_EVENT_PLAYER_FACING_WEST",
    }
    facing = facing_map.get(dir_pick, "BG_EVENT_PLAYER_FACING_ANY")

    # Sign text
    print()
    text = dialogue_prompt("What does the sign say?")
    if not text:
        return False

    label = f"{map_name}_EventScript_{safe}"

    # Build bg_event
    bg_data = {
        "type": "sign",
        "x": x,
        "y": y,
        "elevation": 0,
        "player_facing_dir": facing,
        "script": label,
    }

    # Generate script
    script = _generate_sign(map_name, label, text)

    # Preview
    print()
    print(f"  {WHITE}Preview:{RST}")
    print(f"    map.json: New bg_event (sign at {x},{y})")
    print(f"    scripts.pory: {label}")
    print(f"      {DIM}MSGBOX_SIGN{RST}")
    print()

    try:
        confirm = input("  Write? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if confirm not in ("", "y", "yes"):
        return False

    # Write bg_event
    new_idx = _add_bg_event(game_path, map_name, bg_data)
    if new_idx is None:
        print(f"  {RED}Failed to write map.json{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Write script
    ok = _write_script_to_pory(game_path, map_name, script)
    if not ok:
        return False

    print(f"  {GREEN}Sign added as bg_event #{new_idx}{RST}")
    input(f"  {DIM}Press Enter{RST} > ")
    return True


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------

def _write_script_to_pory(game_path, map_name, script_text):
    """Append a generated script to scripts.pory. Returns True on success."""
    map_dir = os.path.join(game_path, "data", "maps", map_name)
    pory_path = os.path.join(map_dir, "scripts.pory")

    # Read existing content (if any)
    existing = ""
    if os.path.isfile(pory_path):
        try:
            with open(pory_path, "r", encoding="utf-8") as f:
                existing = f.read()
        except OSError:
            pass

    # Append with separator
    separator = "\n\n" if existing.rstrip() else ""
    new_content = existing.rstrip() + separator + script_text

    try:
        os.makedirs(map_dir, exist_ok=True)
        with open(pory_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except OSError as e:
        print(f"  {RED}Error writing {pory_path}: {e}{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    print(f"  {GREEN}Script written to {os.path.basename(pory_path)}{RST}")
    return True


def _compile_pory(game_path, map_name):
    """Compile scripts.pory to scripts.inc via Poryscript compiler.

    The build system only reads scripts.inc (assembly).  After writing
    Poryscript to scripts.pory, this must be called to produce the
    matching .inc so the next ``make`` picks up the new scripts.
    """
    compiler = os.path.join(game_path, "tools", "poryscript", "poryscript")
    if not os.path.isfile(compiler):
        return False
    map_dir = os.path.join(game_path, "data", "maps", map_name)
    pory_path = os.path.join(map_dir, "scripts.pory")
    inc_path = os.path.join(map_dir, "scripts.inc")
    if not os.path.isfile(pory_path):
        return False
    cmd = [compiler, "-i", pory_path, "-o", inc_path]
    font_cfg = os.path.join(game_path, "font_config.json")
    if os.path.isfile(font_cfg):
        cmd.extend(["-fc", font_cfg])
    try:
        subprocess.run(cmd, cwd=game_path, capture_output=True,
                       text=True, timeout=30)
    except Exception:
        return False
    return os.path.isfile(inc_path)


# ---------------------------------------------------------------------------
# Script block removal from .pory files
# ---------------------------------------------------------------------------

def _remove_pory_script_block(pory_path, label):
    """Remove a script block and its orphaned text blocks from scripts.pory.

    Removes the `script <label> { ... }` block and any `text` blocks that
    are only referenced by this script.  Returns True if anything was removed.
    """
    try:
        with open(pory_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return False

    # --- 1. Find and extract the script block ---
    pat = re.compile(
        rf'^(\s*script\s+{re.escape(label)}\s*\{{)',
        re.MULTILINE,
    )
    m = pat.search(content)
    if not m:
        return False

    # Use brace-counting to find the matching closing brace
    brace_start = content.index("{", m.start())
    depth = 0
    block_end = None
    for i in range(brace_start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                block_end = i + 1
                break
    if block_end is None:
        return False

    # Capture the script body (for text-label scanning)
    script_body = content[brace_start + 1:block_end - 1]

    # Extend removal range to include preceding blank lines
    removal_start = m.start()
    while removal_start > 0 and content[removal_start - 1] == "\n":
        removal_start -= 1
        # Keep at most one newline before the block
        if removal_start > 0 and content[removal_start - 1] == "\n":
            continue
        else:
            break

    # Remove the script block
    remaining = content[:removal_start] + content[block_end:]

    # --- 2. Find text labels referenced by this script ---
    text_labels = set(re.findall(r'msgbox\s*\(\s*(\w+)\s*,', script_body))

    # --- 3. Remove orphaned text blocks ---
    for tl in text_labels:
        # Only remove if no other reference exists in remaining content
        # (check for any occurrence of the label outside text block definitions)
        other_refs = re.findall(rf'\b{re.escape(tl)}\b', remaining)
        # Count how many are in text block headers vs. actual references
        text_header_pat = re.compile(
            rf'^\s*text\s+{re.escape(tl)}\s*\{{', re.MULTILINE
        )
        header_count = len(text_header_pat.findall(remaining))
        if len(other_refs) - header_count > 0:
            continue  # still referenced elsewhere

        # Remove the text block
        tm = text_header_pat.search(remaining)
        if tm:
            tb_start = tm.start()
            tb_brace = remaining.index("{", tb_start)
            td = 0
            tb_end = None
            for j in range(tb_brace, len(remaining)):
                if remaining[j] == "{":
                    td += 1
                elif remaining[j] == "}":
                    td -= 1
                    if td == 0:
                        tb_end = j + 1
                        break
            if tb_end is not None:
                # Extend backward over blank lines
                ts = tb_start
                while ts > 0 and remaining[ts - 1] == "\n":
                    ts -= 1
                    if ts > 0 and remaining[ts - 1] == "\n":
                        continue
                    else:
                        break
                remaining = remaining[:ts] + remaining[tb_end:]

    # Collapse runs of 3+ newlines down to 2
    remaining = re.sub(r'\n{3,}', '\n\n', remaining)
    # Ensure trailing newline
    remaining = remaining.rstrip("\n") + "\n" if remaining.strip() else ""

    try:
        with open(pory_path, "w", encoding="utf-8") as f:
            f.write(remaining)
    except OSError:
        return False

    return True


# ---------------------------------------------------------------------------
# Delete script (`d` command)
# ---------------------------------------------------------------------------

def _handle_delete_script(game_path, map_name, npc, npc_i, sel_entry,
                          script_info, project_dir, emotes_conf,
                          source_display, settings, proj_name):
    """Handle the `d` command — delete the selected script.

    Returns True if data changed (needs rebuild).
    """
    entry_type = sel_entry["entry_type"]

    # Refuse infrastructure scripts
    if entry_type in ("nurse", "pc"):
        print(f"\n  {DIM}Cannot delete infrastructure scripts (Nurse/PC).{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    if entry_type == "inc":
        print(f"\n  {DIM}Cannot auto-delete legacy assembly (.inc) scripts.{RST}")
        print(f"  {DIM}Edit data/maps/{map_name}/scripts.inc manually.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    if entry_type == "none":
        print(f"\n  {DIM}Nothing to delete — this NPC has no script.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # --- Path A: Workspace .txt script → delegate to script_hub ---
    if entry_type == "script" and sel_entry.get("script_path"):
        script_path = sel_entry["script_path"]
        script_name = sel_entry.get("script_name") or os.path.splitext(
            os.path.basename(script_path))[0]
        try:
            from torch.script_hub import _delete_script
            return _delete_script(
                script_name, script_path, map_name, project_dir, game_path,
                emotes_conf, source_display, settings, proj_name=proj_name)
        except ImportError as e:
            print(f"\n  {RED}Script deletion not available: {e}{RST}")
            input(f"  {DIM}Press Enter{RST} > ")
            return False

    # --- Path B: Game-file .pory script ---
    if entry_type in ("flavor", "sign", "item_giver", "placeholder", "complex"):
        return _delete_pory_script(game_path, map_name, npc, npc_i, script_info)

    return False


def _delete_pory_script(game_path, map_name, npc, npc_i, script_info):
    """Delete a .pory script block from scripts.pory and clear map.json reference.

    Returns True if script was deleted.
    """
    label = npc.get("script", "")
    pory_path = script_info.get("filepath")

    if not label or not pory_path or not os.path.isfile(pory_path):
        print(f"\n  {DIM}Could not locate script to delete.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # Preview
    print()
    print(f"  {RED}Delete script:{RST} {WHITE}{label}{RST}")
    preview = ""
    if script_info.get("text"):
        preview = _game_text_to_readable(script_info["text"])
        if preview:
            first_line = preview.split("\n")[0]
            if len(first_line) > 50:
                first_line = first_line[:47] + "..."
            print(f"  {DIM}\"{first_line}\"{RST}")
    print()
    print(f"  {WHITE}TORCH will:{RST}")
    print(f"    {DIM}1. Remove script block from scripts.pory{RST}")
    print(f"    {DIM}2. Clear NPC #{npc_i + 1} script field in map.json{RST}")
    print(f"    {DIM}3. Recompile scripts.pory{RST}")
    print()

    try:
        confirm = input(f"  Delete? [y/N] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if confirm not in ("y", "yes"):
        print(f"  {DIM}Cancelled.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # 1. Remove script block from scripts.pory
    if _remove_pory_script_block(pory_path, label):
        print(f"  {GREEN}Removed{RST} script block from scripts.pory")
    else:
        print(f"  {RED}Could not remove script block from scripts.pory{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # 2. Clear map.json script field
    _update_map_json_script(game_path, map_name, npc_i, "")

    # 3. Recompile
    _compile_pory(game_path, map_name)

    # Clear cache
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()
    except ImportError:
        pass

    print()
    print(f"  {GREEN}Done.{RST} Script deleted, NPC kept (no script assigned).")

    # Offer build
    from torch.ui import _offer_build
    _offer_build(game_path=game_path, trigger="npc_delete_script")

    input(f"  {DIM}Press Enter{RST} > ")
    return True


# ---------------------------------------------------------------------------
# Delete NPC entirely (`gd` command)
# ---------------------------------------------------------------------------

def _handle_delete_npc(game_path, map_name, npc, npc_i, sel_entry,
                       script_info, project_dir, emotes_conf,
                       source_display, settings, proj_name):
    """Handle the `gd` command — delete the NPC and all associated data.

    Returns True if data changed (needs rebuild).
    """
    label = npc.get("script", "")
    gfx = npc.get("display_name", "?")
    x, y = npc.get("x", "?"), npc.get("y", "?")
    is_trainer = npc.get("trainer_type", "TRAINER_TYPE_NONE") != "TRAINER_TYPE_NONE"

    # Show what will be deleted
    print()
    print(f"  {RED}Delete NPC #{npc_i + 1}{RST}")
    print(f"    {DIM}Graphics:{RST} {gfx}")
    print(f"    {DIM}Position:{RST} ({x}, {y})")
    if label:
        print(f"    {DIM}Script:{RST}   {label}")
    if is_trainer:
        print(f"    {RED}[T]{RST} {DIM}Trainer NPC — trainer data will also be cleaned up{RST}")
    print()

    entry_type = sel_entry["entry_type"]
    if label:
        if entry_type in ("nurse", "pc"):
            print(f"  {RED}Cannot delete infrastructure NPCs (Nurse/PC).{RST}")
            input(f"  {DIM}Press Enter{RST} > ")
            return False

    print(f"  {WHITE}TORCH will:{RST}")
    step = 1
    if label and entry_type not in ("none", "inc"):
        print(f"    {DIM}{step}. Delete script ({entry_type}){RST}")
        step += 1
    if is_trainer:
        print(f"    {DIM}{step}. Clean up trainer data{RST}")
        step += 1
    print(f"    {DIM}{step}. Remove NPC from map.json{RST}")
    print()

    try:
        confirm = input(f"  Delete NPC #{npc_i + 1} and all associated data? [y/N] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if confirm not in ("y", "yes"):
        print(f"  {DIM}Cancelled.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return False

    # --- 1. Delete script ---
    if label and entry_type not in ("none", "inc", "nurse", "pc"):
        if entry_type == "script" and sel_entry.get("script_path"):
            # Workspace script
            try:
                from torch.script_hub import _delete_script
                _delete_script(
                    sel_entry.get("script_name") or os.path.splitext(
                        os.path.basename(sel_entry["script_path"]))[0],
                    sel_entry["script_path"], map_name, project_dir,
                    game_path, emotes_conf, source_display, settings,
                    proj_name=proj_name)
            except ImportError:
                print(f"  {DIM}Could not delete workspace script (import error).{RST}")
        elif entry_type in ("flavor", "sign", "item_giver", "placeholder", "complex"):
            # Pory script — check if other NPCs reference the same label
            npcs_all = get_map_objects(game_path, map_name)
            shared = sum(1 for n in npcs_all if n.get("script") == label)
            if shared <= 1:
                pory_path = script_info.get("filepath")
                if pory_path and os.path.isfile(pory_path):
                    if _remove_pory_script_block(pory_path, label):
                        print(f"  {GREEN}Removed{RST} script block from scripts.pory")
                    else:
                        print(f"  {DIM}Could not remove script block.{RST}")
            else:
                print(f"  {DIM}Script {label} is shared by {shared} NPCs — keeping script block.{RST}")

    # --- 2. Trainer cleanup ---
    if is_trainer and label:
        _cleanup_trainer_data(game_path, map_name, label, script_info, project_dir)

    # --- 3. Remove NPC from map.json ---
    _remove_npc_from_map_json(game_path, map_name, npc_i)

    # Recompile if we had a pory script
    if label and entry_type in ("flavor", "sign", "item_giver", "placeholder", "complex"):
        _compile_pory(game_path, map_name)

    # Clear cache
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()
    except ImportError:
        pass

    print()
    print(f"  {GREEN}Done.{RST} NPC #{npc_i + 1} removed.")
    print(f"  {DIM}Reload Porymap to see changes.{RST}")

    # Offer build
    from torch.ui import _offer_build
    _offer_build(game_path=game_path, trigger="npc_delete")

    input(f"  {DIM}Press Enter{RST} > ")
    return True


def _cleanup_trainer_data(game_path, map_name, label, script_info, project_dir):
    """Extract trainer constant from script and clean up trainer files."""
    # Read the script body to find the trainerbattle call
    pory_path = script_info.get("filepath")
    trainer_const = None

    if pory_path and os.path.isfile(pory_path):
        try:
            with open(pory_path, "r", encoding="utf-8") as f:
                content = f.read()
            pat = re.compile(
                rf'\bscript\s+{re.escape(label)}\s*\{{', re.MULTILINE
            )
            m = pat.search(content)
            if m:
                body = _extract_brace_block(content, m.start())
                if body:
                    tb = re.search(r'trainerbattle_\w+\(\s*(\w+)', body)
                    if tb:
                        trainer_const = tb.group(1)
        except OSError:
            pass

    if not trainer_const:
        print(f"  {DIM}Could not detect trainer constant — skipping trainer cleanup.{RST}")
        print(f"  {DIM}Check opponents.h / trainers.party manually.{RST}")
        return

    print(f"  {DIM}Cleaning up trainer: {trainer_const}{RST}")

    # Determine format via expansion_compat
    try:
        from torch.expansion_compat import check_feature, PARTY_FORMAT
        use_party = check_feature(game_path, PARTY_FORMAT)
    except ImportError:
        use_party = False

    opponents_path = os.path.join(game_path, "src", "data", "trainer_parties.h")
    if not os.path.isfile(opponents_path):
        opponents_path = os.path.join(game_path, "include", "constants",
                                       "opponents.h")

    # Find the actual opponents.h
    for p in [
        os.path.join(game_path, "include", "constants", "opponents.h"),
    ]:
        if os.path.isfile(p):
            opponents_path = p
            break

    if use_party:
        party_path = os.path.join(game_path, "src", "data", "trainers.party")
        try:
            from torch.battle_manager import _delete_trainer_party
            _delete_trainer_party(
                trainer_const, party_path, opponents_path,
                pory_path=None, game_path=game_path)
        except ImportError:
            print(f"  {DIM}battle_manager not available — manual cleanup needed.{RST}")
    else:
        trainers_h_path = os.path.join(game_path, "src", "data", "trainers.h")
        trainer_parties_path = os.path.join(game_path, "src", "data",
                                             "trainer_parties.h")
        # Get party constant (typically same but with _PARTY_ prefix)
        party_const = trainer_const.replace("TRAINER_", "TRAINER_PARTY_", 1)
        try:
            from torch.battle_manager import _delete_trainer
            _delete_trainer(
                trainer_const, party_const,
                opponents_path, trainers_h_path, trainer_parties_path,
                pory_path=None, game_path=game_path)
        except ImportError:
            print(f"  {DIM}battle_manager not available — manual cleanup needed.{RST}")


def _sanitize_empty_scripts(object_events):
    """Replace empty script fields with a no-op fallback.

    mapjson crashes with "Value for 'script' cannot be empty" when an NPC
    has an empty string as its script value. This happens when SCORCH removes
    vanilla script references or when NPCs are created without scripts.
    """
    for obj in object_events:
        if not obj.get("script"):
            obj["script"] = "Common_EventScript_NopReturn"


def _remove_npc_from_map_json(game_path, map_name, npc_idx):
    """Remove an NPC (object_event) from map.json by index."""
    map_json_path = os.path.join(game_path, "data", "maps", map_name, "map.json")
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  {RED}Error reading map.json: {e}{RST}")
        return False

    events = data.get("object_events", [])
    if npc_idx >= len(events):
        print(f"  {RED}NPC index out of range{RST}")
        return False

    removed = events.pop(npc_idx)
    gfx = removed.get("graphics_id", "?")

    # Sanitize remaining NPCs — mapjson crashes on empty "script" fields
    _sanitize_empty_scripts(events)

    try:
        with open(map_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        print(f"  {RED}Error writing map.json: {e}{RST}")
        return False

    print(f"  {GREEN}Removed{RST} NPC #{npc_idx + 1} ({gfx}) from map.json")
    return True


# ---------------------------------------------------------------------------
# Main menu loop
# ---------------------------------------------------------------------------

def npc_editor_menu(game_path, map_name, settings=None, proj_name=None,
                    project_dir=None, emotes_conf=None, source_display=None):
    """NPC Editor main menu — list NPCs, edit, create, view."""
    if settings is None:
        from torch.config import SETTINGS_DEFAULTS
        settings = dict(SETTINGS_DEFAULTS)

    _set_terminal_title(f"TORCH -- NPC Editor: {map_name}")

    selected_idx = 0
    page_size = settings.get("map_list_page_size", 10)

    # Build cast index (workspace scene → NPC mapping)
    cast_index = _build_cast_index(project_dir, map_name, game_path)

    while True:
        # Load NPCs and their scripts
        npcs = get_map_objects(game_path, map_name)
        script_infos = _parse_npc_scripts(game_path, map_name, npcs,
                                          project_dir)

        # Build flat entry list (cursor navigates these)
        flat_entries = _build_flat_entries(npcs, script_infos, cast_index,
                                          map_name)
        if flat_entries:
            selected_idx = min(selected_idx, len(flat_entries) - 1)

        _render_npc_list(npcs, script_infos, selected_idx, map_name,
                         proj_name, cast_index, flat_entries, page_size)

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            return

        raw = raw.rstrip("\n")

        # Empty → scroll
        if raw == "":
            if flat_entries:
                selected_idx = (selected_idx + 1) % len(flat_entries)
            continue

        cmd = raw.strip().lower()

        if cmd == "q":
            return

        # Navigate with configurable keys
        from torch.config import _nav_keys
        _nk_scroll, nk_up, nk_down, _nk_open = _nav_keys(settings)
        if cmd == nk_up:
            if flat_entries:
                selected_idx = max(0, selected_idx - 1)
            continue
        if cmd == nk_down:
            if flat_entries:
                selected_idx = min(len(flat_entries) - 1, selected_idx + 1)
            continue

        # Number → jump to NPC's first sub-entry
        if raw.strip().isdigit():
            target_npc = int(raw.strip()) - 1
            if 0 <= target_npc < len(npcs):
                for fi, fe in enumerate(flat_entries):
                    if fe["npc_idx"] == target_npc:
                        selected_idx = fi
                        break
            continue

        if not flat_entries:
            continue

        sel_entry = flat_entries[selected_idx]
        npc_i = sel_entry["npc_idx"]
        sel_npc, sel_info = npcs[npc_i], script_infos[npc_i]

        edited = _handle_npc_command(
            cmd, game_path, map_name, sel_npc, sel_info, sel_entry,
            project_dir, emotes_conf, source_display, settings, proj_name)
        if edited:
            try:
                from torch.project_files import clear_project_cache
                clear_project_cache()
            except ImportError:
                pass
            cast_index = _build_cast_index(project_dir, map_name, game_path)


def _handle_npc_command(cmd, game_path, map_name, npc, script_info, sel_entry,
                        project_dir, emotes_conf, source_display, settings,
                        proj_name):
    """Handle a single command in the NPC editor loop.

    Returns True if the command may have changed cast data (needs rebuild).
    """
    if cmd == "e":
        _dispatch_edit(game_path, map_name, npc, script_info,
                       sel_entry=sel_entry, project_dir=project_dir,
                       emotes_conf=emotes_conf,
                       source_display=source_display,
                       settings=settings, proj_name=proj_name)
        return True
    if cmd == "d":
        return _handle_delete_script(
            game_path, map_name, npc, sel_entry["npc_idx"], sel_entry,
            script_info, project_dir, emotes_conf, source_display,
            settings, proj_name)
    if cmd == "gd":
        return _handle_delete_npc(
            game_path, map_name, npc, sel_entry["npc_idx"], sel_entry,
            script_info, project_dir, emotes_conf, source_display,
            settings, proj_name)
    if cmd == "v" and npc.get("script"):
        _view_full_script(script_info, npc["script"], emotes_conf=emotes_conf,
                          game_path=game_path, settings=settings,
                          project_dir=project_dir, map_name=map_name)
    elif cmd == "n":
        _wizard_new_script(game_path, map_name, npc)
    elif cmd == "w":
        _npc_wizard(game_path, map_name, proj_name)
    return False


def _dispatch_edit(game_path, map_name, npc, script_info, sel_entry=None,
                   project_dir=None, emotes_conf=None, source_display=None,
                   settings=None, proj_name=None):
    """Route edit action based on selected flat entry."""
    # Scene entry — open Scene Editor directly
    if sel_entry and sel_entry["entry_type"] == "script" and sel_entry.get("script_path"):
        if not project_dir:
            print(f"\n  {DIM}Script Editor requires a project directory.{RST}")
            input(f"  {DIM}Press Enter{RST} > ")
            return
        try:
            from torch.script_model import _parse_script
            from torch.script_editor import _script_editor_loop
            script_data = _parse_script(sel_entry["script_path"], emotes_conf)
            _script_editor_loop(script_data, map_name, sel_entry["script_path"],
                               project_dir, game_path, emotes_conf,
                               source_display, settings, proj_name)
        except Exception as e:
            print(f"\n  {RED}Error opening script: {e}{RST}")
            input(f"  {DIM}Press Enter{RST} > ")
        return

    if not npc.get("script"):
        print()
        print(f"  {DIM}This NPC has no script assigned.{RST}")
        print(f"  {DIM}Use [w] Wizard to create one.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    if not script_info.get("text"):
        # Offer decompile-to-workspace for complex .pory/.inc scripts
        file_type = script_info.get("file_type")
        filepath = script_info.get("filepath")
        if project_dir and file_type in ("pory", "inc") and filepath:
            _offer_decompile_import(
                filepath, file_type, npc.get("script", ""),
                map_name, project_dir, game_path, emotes_conf,
                source_display, settings, proj_name, open_editor=True)
            return
        print()
        print(f"  {DIM}Could not parse dialogue for this script.{RST}")
        print(f"  {DIM}Use [v] to view the raw script.{RST}")
        input(f"  {DIM}Press Enter{RST} > ")
        return

    # Clear the project_files cache so we get fresh data after edit
    _edit_npc_dialogue(game_path, map_name, npc, script_info)
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()
    except ImportError:
        pass


def _wizard_new_script(game_path, map_name, npc):
    """Create a new simple script for an NPC that has none or needs replacing."""
    label = npc.get("script", "")
    if not label:
        # Generate a label from map name and display name
        safe_name = re.sub(r'[^A-Za-z0-9]', '', npc.get("display_name", "Npc"))
        label = f"{map_name}_{safe_name}"

    print()
    print(f"  {WHITE}New script for:{RST} {GOLD}{npc.get('display_name', '?')}{RST}")
    print(f"  {WHITE}Label:{RST} {CYAN}{label}{RST}")
    print()

    text = dialogue_prompt("What should this NPC say?")
    if not text:
        return

    script = _generate_flavor_npc(map_name, label, text)

    print()
    print(f"  {WHITE}Generated:{RST}")
    for line in script.strip().split("\n"):
        print(f"  {line}")
    print()

    try:
        confirm = input("  Write to scripts.pory? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if confirm not in ("", "y", "yes"):
        return

    ok = _write_script_to_pory(game_path, map_name, script)
    if ok and not npc.get("script"):
        _offer_map_json_wiring(game_path, map_name, label)
