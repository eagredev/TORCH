# TORCH_MODULE: Web API — NPC Editor
# TORCH_GROUP: Web
"""NPC Editor API endpoints for the TORCH web GUI.

Provides endpoints for NPC detail view, property updates, dialogue editing,
script reassignment, cast index lookup, health scanning, NPC creation
(wizard), and NPC deletion.
"""

import json
import os
import re

from torch.web.api import api_route, ok_response, error_response, _read_json_body
from torch.web.api import _safe_path, _atomic_write
from torch.names import _const_to_human_name
from torch.project_files import load_map_json, clear_project_cache
from torch.npc_editor import (
    _generate_flavor_npc, _generate_sign, _generate_item_giver,
    _generate_multi_state, _write_script_to_pory, _add_object_event,
    _add_bg_event, _remove_npc_from_map_json, _find_existing_nurse,
)


# ---------------------------------------------------------------------------
# Helpers — script file resolution
# ---------------------------------------------------------------------------

def _find_script(game_path, map_name, label):
    """Locate which file contains a script label.

    Returns (filepath, file_type) where file_type is 'pory', 'inc', or None.
    """
    if not label:
        return None, None

    map_dir = os.path.join(game_path, "data", "maps", map_name)

    pory_path = os.path.join(map_dir, "scripts.pory")
    if os.path.isfile(pory_path):
        try:
            with open(pory_path, "r", encoding="utf-8") as f:
                content = f.read()
            if re.search(rf'\bscript\s+{re.escape(label)}\b', content):
                return pory_path, "pory"
        except OSError:
            pass

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


# ---------------------------------------------------------------------------
# Helpers — brace block extraction
# ---------------------------------------------------------------------------

def _extract_brace_block(content, start):
    """Extract body between { and } starting from a match position."""
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
# Helpers — script classification
# ---------------------------------------------------------------------------

def _classify_script(content, label):
    """Classify a .pory script block.

    Returns: "flavor" | "sign" | "item_giver" | "nurse" | "pc" | "custom" | "complex"
    """
    pat = rf'\bscript\s+{re.escape(label)}\s*\{{'
    match = re.search(pat, content)
    if not match:
        return "complex"

    body = _extract_brace_block(content, match.start())
    if not body:
        return "complex"

    body_stripped = body.strip()

    if "special(ShowPokemonStorageSystem)" in body_stripped:
        return "pc"
    if ("special(HealPlayerParty)" in body_stripped
            or "HealPlayerTeam" in body_stripped):
        return "nurse"
    if "giveitem(" in body_stripped:
        return "item_giver"

    stmts = [l.strip() for l in body_stripped.split("\n")
             if l.strip() and not l.strip().startswith("//")]

    msgbox_calls = [s for s in stmts if s.startswith("msgbox(")]
    non_msgbox = [s for s in stmts if not s.startswith("msgbox(")
                  and s != "}" and s != "{"]

    if len(msgbox_calls) == 1 and len(non_msgbox) == 0:
        if "MSGBOX_SIGN" in msgbox_calls[0]:
            return "sign"
        if "MSGBOX_NPC" in msgbox_calls[0]:
            return "flavor"

    # Has at least one msgbox? → custom (editable but has extra logic)
    if msgbox_calls:
        return "custom"

    # No msgbox at all → complex (not safely editable)
    return "complex"


def _classify_inc_script(content, label):
    """Classify an assembly (.inc) script block.

    Returns same types as _classify_script: flavor/sign/custom/complex/nurse/pc.
    """
    # Extract the body between label:: and the next label or end of file
    pat = rf'^{re.escape(label)}::?\s*$'
    m = re.search(pat, content, re.MULTILINE)
    if not m:
        return "complex"

    # Get lines until next label (line starting without whitespace ending with :)
    rest = content[m.end():]
    body_lines = []
    for line in rest.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if not line[0:1].isspace() and stripped.endswith(":"):
            break  # next label
        if not line[0:1].isspace() and "::" in stripped:
            break  # next label
        body_lines.append(stripped)

    if not body_lines:
        return "complex"

    # Check patterns
    body_text = " ".join(body_lines)

    if "special ShowPokemonStorageSystem" in body_text:
        return "pc"
    if "special HealPlayerParty" in body_text or "HealPlayerTeam" in body_text:
        return "nurse"
    if "giveitem" in body_text.lower():
        return "item_giver"

    # Simple msgbox + end (with optional lock/faceplayer/release)
    cmds = [l for l in body_lines if l not in ("lock", "faceplayer", "release",
                                                "end", "return")]
    msgbox_cmds = [c for c in cmds if c.startswith("msgbox ")]

    if len(msgbox_cmds) == 1 and len(cmds) == 1:
        if "MSGBOX_SIGN" in msgbox_cmds[0]:
            return "sign"
        if "MSGBOX_NPC" in msgbox_cmds[0]:
            return "flavor"

    if msgbox_cmds:
        return "custom"

    return "complex"


# ---------------------------------------------------------------------------
# Helpers — dialogue extraction
# ---------------------------------------------------------------------------

def _extract_pory_dialogue(content, label):
    """Extract msgbox text from a Poryscript script block.

    Returns dict with text, msgbox_type, uses_format, or None.
    """
    pat = rf'\bscript\s+{re.escape(label)}\s*\{{'
    match = re.search(pat, content)
    if not match:
        return None

    body = _extract_brace_block(content, match.start())
    if body is None:
        return None

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


def _extract_inc_dialogue(content, label):
    """Extract dialogue from a .inc assembly script.

    Returns dict with text, text_label, msgbox_type, or None.
    """
    script_pat = rf'^{re.escape(label)}::'
    if not re.search(script_pat, content, re.MULTILINE):
        return None

    body_match = re.search(
        rf'^{re.escape(label)}::(.+?)(?=^\w+::|\Z)',
        content, re.MULTILINE | re.DOTALL
    )
    if not body_match:
        return None

    body = body_match.group(1)
    msgbox_m = re.search(r'msgbox\s+(\w+)\s*,\s*(\w+)', body)
    if not msgbox_m:
        return None

    text_label = msgbox_m.group(1)
    msgbox_type = msgbox_m.group(2)

    # Extract .string lines for the text label
    pattern = rf'^{re.escape(text_label)}:\s*$'
    label_match = re.search(pattern, content, re.MULTILINE)
    if not label_match:
        return None

    result = []
    lines = content[label_match.end():].split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("@"):
            continue
        m = re.match(r'\.string\s+"(.*)"', stripped)
        if m:
            result.append(m.group(1))
        else:
            break

    if not result:
        return None

    return {
        "text": "".join(result),
        "text_label": text_label,
        "msgbox_type": msgbox_type,
    }


# ---------------------------------------------------------------------------
# Helpers — text conversion
# ---------------------------------------------------------------------------

def _game_text_to_readable(text):
    """Convert game-format text to readable paragraphs."""
    if not text:
        return ""
    clean = text.rstrip("$")
    clean = clean.replace("\\l", "\\n")
    clean = clean.replace("\\p", "\n\n")
    clean = clean.replace("\\n", "\n")
    return clean.strip()


def _readable_to_game_text(text):
    """Convert readable text to game-format text.

    Newlines -> \\n, paragraph breaks (blank lines) -> \\p.
    Adds trailing $.
    """
    if not text:
        return "$"
    # Split paragraphs on blank lines
    paragraphs = re.split(r'\n\s*\n', text.strip())
    parts = []
    for para in paragraphs:
        lines = [l.strip() for l in para.strip().split("\n") if l.strip()]
        parts.append("\\n".join(lines))
    return "\\p".join(parts) + "$"


# ---------------------------------------------------------------------------
# Helpers — cast index
# ---------------------------------------------------------------------------

def _build_cast_index(project_dir, map_name):
    """Scan .txt files in workspace for alias directives.

    Returns: {npc_id: [(alias_name, script_name, filename), ...]}
    """
    cast_index = {}
    ws_dir = os.path.join(project_dir, map_name) if project_dir else None
    if not ws_dir or not os.path.isdir(ws_dir):
        return cast_index

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

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # alias <name> npc<N>
            m = re.match(r'^alias\s+(\w+)\s+npc(\d+)', stripped, re.IGNORECASE)
            if m:
                alias_name = m.group(1)
                npc_id = int(m.group(2))
                cast_index.setdefault(npc_id, []).append(
                    (alias_name, script_name, fname)
                )
            elif not stripped.startswith("alias"):
                # Past the alias block
                break

    return cast_index


# ---------------------------------------------------------------------------
# Helpers — NPC detail builder
# ---------------------------------------------------------------------------

_EDITABLE_TYPES = {"flavor", "sign", "item_giver", "complex", "custom", "none"}
_DECOMPILABLE_TYPES = {"flavor", "sign", "item_giver", "custom", "complex"}


def _build_npc_detail(game_path, map_name, npc_id, project_dir=None):
    """Build full detail dict for a single NPC.

    npc_id is 1-based. Returns (detail_dict, error_string).
    """
    data = load_map_json(game_path, map_name)
    if not data:
        return None, f"Map not found: {map_name}"

    events = data.get("object_events", [])
    idx = npc_id - 1
    if idx < 0 or idx >= len(events):
        return None, f"NPC #{npc_id} not found (map has {len(events)} NPCs)"

    obj = events[idx]
    gfx = obj.get("graphics_id", "")
    script_label = obj.get("script", "")
    if script_label in ("0x0", "0", ""):
        script_label = ""

    # Resolve script
    script_type, script_source, dialogue, dialogue_readable = (
        _resolve_script_info(game_path, map_name, script_label)
    )

    msgbox_type = None
    if dialogue is not None:
        # dialogue extraction already got the type
        pass

    # Build detail — delegate dialogue/msgbox extraction
    detail = _assemble_npc_detail(
        obj, npc_id, gfx, script_label, script_type, script_source,
        game_path, map_name, project_dir
    )
    return detail, None


def _resolve_script_info(game_path, map_name, script_label):
    """Resolve script type, source, and dialogue for a label.

    Returns (script_type, script_source, dialogue, dialogue_readable).
    """
    if not script_label or script_label in ("NULL", "0", "0x0"):
        return "none", None, None, None

    # Shared scripts
    if script_label.startswith("Common_EventScript_"):
        return "shared", None, None, None

    filepath, file_type = _find_script(game_path, map_name, script_label)

    if file_type == "pory":
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return "complex", "scripts.pory", None, None

        stype = _classify_script(content, script_label)
        dlg = _extract_pory_dialogue(content, script_label)
        dialogue = dlg["text"] if dlg else None
        dialogue_readable = _game_text_to_readable(dialogue) if dialogue else None
        return stype, "scripts.pory", dialogue, dialogue_readable

    if file_type == "inc":
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return "inc", "scripts.inc", None, None

        stype = _classify_inc_script(content, script_label)
        dlg = _extract_inc_dialogue(content, script_label)
        dialogue = dlg["text"] if dlg else None
        dialogue_readable = _game_text_to_readable(dialogue) if dialogue else None
        return stype, "scripts.inc", dialogue, dialogue_readable

    return "unknown", None, None, None


def _assemble_npc_detail(obj, npc_id, gfx, script_label, script_type,
                         script_source, game_path, map_name, project_dir):
    """Assemble the final NPC detail dict."""
    flag = obj.get("flag", "0")

    # Dialogue and msgbox_type
    dialogue = None
    dialogue_readable = None
    msgbox_type = None

    if script_label and script_type not in ("none", "shared", "unknown"):
        filepath, file_type = _find_script(game_path, map_name, script_label)
        if file_type == "pory":
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                dlg = _extract_pory_dialogue(content, script_label)
                if dlg:
                    dialogue = dlg["text"]
                    dialogue_readable = _game_text_to_readable(dialogue)
                    msgbox_type = dlg["msgbox_type"]
            except OSError:
                pass
        elif file_type == "inc":
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                dlg = _extract_inc_dialogue(content, script_label)
                if dlg:
                    dialogue = dlg["text"]
                    dialogue_readable = _game_text_to_readable(dialogue)
                    msgbox_type = dlg["msgbox_type"]
            except OSError:
                pass

    # is_workspace_managed
    is_ws = False
    if project_dir:
        ws_dir = os.path.join(project_dir, map_name)
        if os.path.isdir(ws_dir):
            for fname in os.listdir(ws_dir):
                if fname.endswith(".txt"):
                    sname = os.path.splitext(fname)[0]
                    if (script_label and
                            (sname == script_label
                             or script_label.endswith(f"_{sname}"))):
                        is_ws = True
                        break

    # Cast index
    refs = []
    if project_dir:
        cast = _build_cast_index(project_dir, map_name)
        for alias_name, sname, fname in cast.get(npc_id, []):
            refs.append({
                "alias_name": alias_name,
                "script_name": sname,
                "file": fname,
            })

    trainer_type = obj.get("trainer_type", "TRAINER_TYPE_NONE")
    is_trainer = trainer_type not in ("TRAINER_TYPE_NONE", "0", "")

    return {
        "object_id": npc_id,
        "graphics_id": gfx,
        "display_name": _const_to_human_name(gfx, "OBJ_EVENT_GFX_"),
        "x": obj.get("x", 0),
        "y": obj.get("y", 0),
        "elevation": obj.get("elevation", 0),
        "movement_type": obj.get("movement_type", "MOVEMENT_TYPE_FACE_DOWN"),
        "movement_range_x": obj.get("movement_range_x", 0),
        "movement_range_y": obj.get("movement_range_y", 0),
        "trainer_type": trainer_type,
        "trainer_sight_or_berry_tree_id": str(
            obj.get("trainer_sight_or_berry_tree_id", "0")
        ),
        "flag": flag,
        "script": script_label,
        "script_type": script_type,
        "script_source": script_source,
        "dialogue": dialogue,
        "dialogue_readable": dialogue_readable,
        "msgbox_type": msgbox_type,
        "is_editable": script_type in _EDITABLE_TYPES,
        "has_extra_logic": script_type in ("custom",),
        "is_trainer": is_trainer,
        "is_workspace_managed": is_ws,
        "can_decompile": (
            bool(script_label)
            and script_source in ("scripts.pory", "scripts.inc")
            and not is_ws
            and script_type in _DECOMPILABLE_TYPES
        ),
        "referenced_by": refs,
    }


# ---------------------------------------------------------------------------
# Helpers — map.json write
# ---------------------------------------------------------------------------

def _write_map_json(game_path, map_name, data):
    """Write map.json with indent=2, ensure_ascii=False, trailing newline."""
    map_json_path = os.path.join(
        game_path, "data", "maps", map_name, "map.json"
    )
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    _atomic_write(map_json_path, content)


# ---------------------------------------------------------------------------
# Allowed update fields
# ---------------------------------------------------------------------------

_ALLOWED_FIELDS = {
    "graphics_id", "x", "y", "elevation",
    "movement_type", "movement_range_x", "movement_range_y",
    "flag", "trainer_type", "trainer_sight_or_berry_tree_id",
}

_INT_FIELDS = {"x", "y", "elevation", "movement_range_x", "movement_range_y"}


# ---------------------------------------------------------------------------
# Helpers — label sanitization
# ---------------------------------------------------------------------------

def _sanitize_label_name(name):
    """Sanitize a name for use in a script label (alphanumeric + underscore)."""
    return re.sub(r'[^A-Za-z0-9_]', '', name)


def _next_sign_number(game_path, map_name):
    """Find the next available sign number for auto-labelling."""
    map_dir = os.path.join(game_path, "data", "maps", map_name)
    pory_path = os.path.join(map_dir, "scripts.pory")
    max_n = 0
    if os.path.isfile(pory_path):
        try:
            with open(pory_path, "r", encoding="utf-8") as f:
                content = f.read()
            for m in re.finditer(
                rf'{re.escape(map_name)}_EventScript_Sign(\d+)', content
            ):
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
        except OSError:
            pass
    return max_n + 1


# ---------------------------------------------------------------------------
# Helpers — NPC creation by type
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {
    "flavor": ["name", "x", "y", "graphics_id", "dialogue"],
    "sign": ["name", "x", "y", "dialogue"],
    "item_giver": ["name", "x", "y", "graphics_id", "item", "flag",
                   "before_text", "after_text"],
    "multi_state": ["name", "x", "y", "graphics_id", "states"],
    "nurse": ["x", "y"],
    "pc": ["x", "y"],
    "infra_sign": ["x", "y", "dialogue"],
}


def _validate_create_body(body):
    """Validate required fields for NPC creation. Returns error string or None."""
    npc_type = body.get("type")
    if not npc_type:
        return "Missing 'type' field"
    required = _REQUIRED_FIELDS.get(npc_type)
    if required is None:
        return f"Unknown NPC type: {npc_type}"
    missing = [f for f in required if f not in body or body[f] is None]
    if missing:
        return f"Missing required fields for {npc_type}: {', '.join(missing)}"
    if npc_type == "multi_state":
        states = body.get("states")
        if not isinstance(states, list) or len(states) < 2:
            return "multi_state requires at least 2 states"
    return None


def _write_torscript_or_pory(game_path, map_name, pory_script, torscript, name,
                             project_dir=None):
    """Write script to workspace (.txt TorScript + sync) if enrolled, else raw pory.

    Args:
        game_path: Game project path
        map_name: Map name
        pory_script: Poryscript text (for non-enrolled fallback)
        torscript: TorScript text (for workspace)
        name: Short script name (e.g. "OldMan") for the .txt filename
        project_dir: Project workspace dir (None = skip workspace check)
    """
    if project_dir:
        from torch.registry import is_enrolled
        if is_enrolled(project_dir, map_name):
            ws_dir = os.path.join(project_dir, map_name)
            os.makedirs(ws_dir, exist_ok=True)
            out_path = os.path.join(ws_dir, f"{name}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(torscript + "\n")
            _quiet_sync(project_dir, map_name, game_path)
            return

    # Fallback: write Poryscript directly to scripts.pory
    _write_script_to_pory(game_path, map_name, pory_script)


def _create_flavor(game_path, map_name, body, project_dir=None):
    """Create a flavor NPC (object_event + script)."""
    safe_name = _sanitize_label_name(body["name"])
    if not safe_name:
        return error_response("Name produces empty label after sanitization", 400)
    label = f"{map_name}_EventScript_{safe_name}"
    text = body["dialogue"].rstrip("$") + "$"

    pory_script = _generate_flavor_npc(map_name, label, text)
    # TorScript equivalent for workspace
    torscript = f'script {label}\nlock\nfaceplayer\nmsgnpc "{text}"\nrelease\nend'
    _write_torscript_or_pory(game_path, map_name, pory_script, torscript, safe_name,
                             project_dir=project_dir)

    obj_data = _build_object_data(body, label)
    new_idx = _add_object_event(game_path, map_name, obj_data)
    if new_idx is None:
        return error_response("Failed to write map.json", 500)

    return ok_response({
        "object_id": new_idx,
        "script_label": label,
        "type": "flavor",
        "event_type": "object_event",
    })


def _create_sign(game_path, map_name, body, project_dir=None):
    """Create a sign (bg_event + script)."""
    safe_name = _sanitize_label_name(body["name"])
    if not safe_name:
        return error_response("Name produces empty label after sanitization", 400)
    label = f"{map_name}_EventScript_{safe_name}"
    text = body["dialogue"].rstrip("$") + "$"

    pory_script = _generate_sign(map_name, label, text)
    torscript = f'script {label}\nmsg "{text}"\nend'
    _write_torscript_or_pory(game_path, map_name, pory_script, torscript, safe_name,
                             project_dir=project_dir)

    bg_data = {
        "type": "sign",
        "x": body["x"], "y": body["y"],
        "elevation": 0,
        "player_facing_dir": "BG_EVENT_PLAYER_FACING_ANY",
        "script": label,
    }
    new_idx = _add_bg_event(game_path, map_name, bg_data)
    if new_idx is None:
        return error_response("Failed to write map.json", 500)

    return ok_response({
        "object_id": new_idx,
        "script_label": label,
        "type": "sign",
        "event_type": "bg_event",
    })


def _create_item_giver(game_path, map_name, body, project_dir=None):
    """Create an item giver NPC (object_event + script)."""
    safe_name = _sanitize_label_name(body["name"])
    if not safe_name:
        return error_response("Name produces empty label after sanitization", 400)
    label = f"{map_name}_EventScript_{safe_name}"
    text_before = body["before_text"].rstrip("$") + "$"
    text_after = body["after_text"].rstrip("$") + "$"

    pory_script = _generate_item_giver(
        map_name, label, body["item"], body["flag"], text_before, text_after
    )
    torscript = (
        f'script {label}\nlock\nfaceplayer\n'
        f'gotoif flag {body["flag"]} {label}_Already\n'
        f'msgnpc "{text_before}"\n'
        f'give {body["item"]} 1\n'
        f'flag set {body["flag"]}\nrelease\nend\n\n'
        f'script {label}_Already\n'
        f'msgnpc "{text_after}"\nrelease\nend'
    )
    _write_torscript_or_pory(game_path, map_name, pory_script, torscript, safe_name,
                             project_dir=project_dir)

    obj_data = _build_object_data(body, label)
    new_idx = _add_object_event(game_path, map_name, obj_data)
    if new_idx is None:
        return error_response("Failed to write map.json", 500)

    return ok_response({
        "object_id": new_idx,
        "script_label": label,
        "type": "item_giver",
        "event_type": "object_event",
    })


def _create_multi_state(game_path, map_name, body):
    """Create a multi-state NPC (object_event + script)."""
    safe_name = _sanitize_label_name(body["name"])
    if not safe_name:
        return error_response("Name produces empty label after sanitization", 400)
    label = f"{map_name}_EventScript_{safe_name}"

    states = []
    for s in body["states"]:
        text = s.get("text", "").rstrip("$") + "$"
        states.append({"flag": s.get("flag"), "text": text})

    script = _generate_multi_state(map_name, label, states)
    _write_script_to_pory(game_path, map_name, script)

    obj_data = _build_object_data(body, label)
    new_idx = _add_object_event(game_path, map_name, obj_data)
    if new_idx is None:
        return error_response("Failed to write map.json", 500)

    return ok_response({
        "object_id": new_idx,
        "script_label": label,
        "type": "multi_state",
        "event_type": "object_event",
    })


def _create_nurse(game_path, map_name, body):
    """Create a nurse NPC (object_event + wrapper script)."""
    existing = _find_existing_nurse(game_path, map_name)
    if existing is not None:
        return error_response("Map already has a Nurse NPC", 409)

    label = f"{map_name}_EventScript_Nurse"
    obj_data = {
        "graphics_id": "OBJ_EVENT_GFX_NURSE",
        "x": body.get("x", 7), "y": body.get("y", 2),
        "elevation": 3,
        "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
        "movement_range_x": 0, "movement_range_y": 0,
        "trainer_type": "TRAINER_TYPE_NONE",
        "trainer_sight_or_berry_tree_id": "0",
        "script": label,
        "flag": "0",
    }

    new_idx = _add_object_event(game_path, map_name, obj_data)
    if new_idx is None:
        return error_response("Failed to write map.json", 500)

    # Import wrapper generator (uses local_id for VAR_0x800B)
    from torch.npc_editor import _generate_nurse_wrapper
    wrapper = _generate_nurse_wrapper(map_name, label, new_idx)
    _write_script_to_pory(game_path, map_name, wrapper)

    return ok_response({
        "object_id": new_idx,
        "script_label": label,
        "type": "nurse",
        "event_type": "object_event",
    })


def _create_pc(game_path, map_name, body):
    """Create a PC (bg_event, no script generation)."""
    bg_data = {
        "type": "sign",
        "x": body.get("x", 5), "y": body.get("y", 2),
        "elevation": 0,
        "player_facing_dir": "BG_EVENT_PLAYER_FACING_ANY",
        "script": "EventScript_PC",
    }
    new_idx = _add_bg_event(game_path, map_name, bg_data)
    if new_idx is None:
        return error_response("Failed to write map.json", 500)

    return ok_response({
        "object_id": new_idx,
        "script_label": "EventScript_PC",
        "type": "pc",
        "event_type": "bg_event",
    })


def _create_infra_sign(game_path, map_name, body):
    """Create an infrastructure sign (bg_event + script)."""
    n = _next_sign_number(game_path, map_name)
    label = f"{map_name}_EventScript_Sign{n}"
    text = body["dialogue"].rstrip("$") + "$"

    script = _generate_sign(map_name, label, text)
    _write_script_to_pory(game_path, map_name, script)

    bg_data = {
        "type": "sign",
        "x": body["x"], "y": body["y"],
        "elevation": 0,
        "player_facing_dir": "BG_EVENT_PLAYER_FACING_ANY",
        "script": label,
    }
    new_idx = _add_bg_event(game_path, map_name, bg_data)
    if new_idx is None:
        return error_response("Failed to write map.json", 500)

    return ok_response({
        "object_id": new_idx,
        "script_label": label,
        "type": "infra_sign",
        "event_type": "bg_event",
    })


def _build_object_data(body, script_label):
    """Build object_event dict from creation body."""
    return {
        "graphics_id": body["graphics_id"],
        "x": body["x"], "y": body["y"],
        "elevation": body.get("elevation", 3),
        "movement_type": body.get("movement_type", "MOVEMENT_TYPE_FACE_DOWN"),
        "movement_range_x": body.get("movement_range_x", 0),
        "movement_range_y": body.get("movement_range_y", 0),
        "trainer_type": "TRAINER_TYPE_NONE",
        "trainer_sight_or_berry_tree_id": "0",
        "script": script_label,
        "flag": "0",
    }


_CREATE_DISPATCH = {
    "flavor": _create_flavor,
    "sign": _create_sign,
    "item_giver": _create_item_giver,
    "multi_state": _create_multi_state,
    "nurse": _create_nurse,
    "pc": _create_pc,
    "infra_sign": _create_infra_sign,
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", "/api/npcs/templates")
def handle_npc_templates(handler, match, query_params):
    """Available wizard template types for NPC creation."""
    wizards = [
        {"type": "flavor", "name": "Flavor NPC",
         "description": "Simple dialogue NPC", "event_type": "object_event"},
        {"type": "sign", "name": "Sign",
         "description": "Readable sign or plaque", "event_type": "bg_event"},
        {"type": "item_giver", "name": "Item Giver",
         "description": "NPC that gives an item once",
         "event_type": "object_event"},
        {"type": "multi_state", "name": "Multi-State NPC",
         "description": "NPC with flag-based dialogue states",
         "event_type": "object_event"},
        {"type": "nurse", "name": "Nurse Joy",
         "description": "Pokemon Center healing",
         "event_type": "object_event"},
        {"type": "pc", "name": "PC",
         "description": "Storage system access point",
         "event_type": "bg_event"},
        {"type": "infra_sign", "name": "Infrastructure Sign",
         "description": "Standard sign BG event",
         "event_type": "bg_event"},
    ]
    return ok_response({"wizards": wizards})


@api_route("GET", r"/api/npcs/(?P<map_name>[A-Za-z0-9_]+)/health")
def handle_npc_health(handler, match, query_params):
    """Health scan: detect dead/stub scripts for NPCs in a map."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get("object_events", [])
    issues = []

    # Read script files once
    pory_content, inc_content = _read_script_files(game_path, map_name)

    for i, obj in enumerate(events):
        label = obj.get("script", "")
        if not label or label in ("0x0", "0"):
            continue
        if label.startswith("Common_EventScript_"):
            continue

        issue = _check_script_health(label, pory_content, inc_content)
        if issue:
            issues.append({
                "object_id": i + 1,
                "script": label,
                "issue": issue[0],
                "description": issue[1],
            })

    return ok_response({
        "map_name": map_name,
        "issues": issues,
        "total_npcs": len(events),
        "healthy_count": len(events) - len(issues),
    })


def _read_script_files(game_path, map_name):
    """Read scripts.pory and scripts.inc content for a map."""
    map_dir = os.path.join(game_path, "data", "maps", map_name)
    pory_content = None
    inc_content = None

    pory_path = os.path.join(map_dir, "scripts.pory")
    if os.path.isfile(pory_path):
        try:
            with open(pory_path, "r", encoding="utf-8") as f:
                pory_content = f.read()
        except OSError:
            pass

    inc_path = os.path.join(map_dir, "scripts.inc")
    if os.path.isfile(inc_path):
        try:
            with open(inc_path, "r", encoding="utf-8") as f:
                inc_content = f.read()
        except OSError:
            pass

    return pory_content, inc_content


def _check_script_health(label, pory_content, inc_content):
    """Check if a script label is healthy.

    Returns None if healthy, or (issue_type, description) tuple.
    """
    found_in_pory = False
    found_in_inc = False

    if pory_content:
        if re.search(rf'\bscript\s+{re.escape(label)}\b', pory_content):
            found_in_pory = True
            # Check for stub
            body = _get_pory_body(pory_content, label)
            if body is not None and _is_stub_body(body):
                return ("stub", "Script body is empty or only contains end/return")

    if inc_content:
        if re.search(rf'^{re.escape(label)}::', inc_content, re.MULTILINE):
            found_in_inc = True
            body = _get_inc_body(inc_content, label)
            if body is not None and _is_stub_inc(body):
                return ("stub", "Script body is empty or only contains end/return")

    if not found_in_pory and not found_in_inc:
        return ("missing", "Script label not found in scripts.pory or scripts.inc")

    return None


def _get_pory_body(content, label):
    """Get the body of a pory script block."""
    pat = rf'\bscript\s+{re.escape(label)}\s*\{{'
    match = re.search(pat, content)
    if not match:
        return None
    return _extract_brace_block(content, match.start())


def _get_inc_body(content, label):
    """Get the body of an inc script block."""
    body_match = re.search(
        rf'^{re.escape(label)}::(.+?)(?=^\w+::|\Z)',
        content, re.MULTILINE | re.DOTALL
    )
    return body_match.group(1) if body_match else None


def _is_stub_body(body):
    """Check if a pory script body is just a stub."""
    stmts = [l.strip() for l in body.strip().split("\n")
             if l.strip() and not l.strip().startswith("//")]
    meaningful = [s for s in stmts if s not in ("{", "}", "end", "return")]
    return len(meaningful) == 0


def _is_stub_inc(body):
    """Check if an inc script body is just a stub."""
    stmts = [l.strip() for l in body.strip().split("\n")
             if l.strip() and not l.strip().startswith("@")]
    meaningful = [s for s in stmts if s not in ("end", "return")]
    return len(meaningful) == 0


@api_route("GET", r"/api/npcs/(?P<map_name>[A-Za-z0-9_]+)/(?P<npc_id>\d+)")
def handle_npc_detail(handler, match, query_params):
    """Single NPC detail with parsed dialogue and cast index."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    npc_id = int(match.group("npc_id"))

    project_dir = getattr(handler.server, "project_dir", "")

    detail, err = _build_npc_detail(game_path, map_name, npc_id, project_dir)
    if err:
        status = 404 if "not found" in err.lower() else 400
        return error_response(err, status)

    return ok_response({"npc": detail})


@api_route("POST", r"/api/npcs/(?P<map_name>[A-Za-z0-9_]+)/create")
def handle_npc_create(handler, match, query_params):
    """Create a new NPC via wizard."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")

    # Verify map exists
    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body:
        return error_response("Request body required", 400)

    err = _validate_create_body(body)
    if err:
        return error_response(err, 400)

    creator = _CREATE_DISPATCH.get(body["type"])
    if not creator:
        return error_response(f"Unknown NPC type: {body['type']}", 400)

    clear_project_cache()
    project_dir = getattr(handler.server, "project_dir", "")
    # Pass project_dir for workspace-aware creation (creators that accept it)
    import inspect
    params = inspect.signature(creator).parameters
    if "project_dir" in params:
        return creator(game_path, map_name, body, project_dir=project_dir)
    return creator(game_path, map_name, body)


@api_route("POST", r"/api/npcs/(?P<map_name>[A-Za-z0-9_]+)/(?P<npc_id>\d+)/dialogue")
def handle_npc_dialogue(handler, match, query_params):
    """Update NPC dialogue text in scripts.pory."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    npc_id = int(match.group("npc_id"))

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body:
        return error_response("Request body required", 400)

    text = body.get("text")
    if text is None:
        return error_response("'text' field is required", 400)

    new_msgbox_type = body.get("msgbox_type")

    project_dir = getattr(handler.server, "project_dir", "")

    # Try workspace-first update for managed scripts
    if project_dir:
        ws_result = _try_workspace_dialogue_update(
            project_dir, game_path, map_name, npc_id, text, new_msgbox_type
        )
        if ws_result is not None:
            return ws_result

        # For NULL/new scripts on enrolled maps, create workspace .txt directly
        from torch.registry import is_enrolled
        if is_enrolled(project_dir, map_name):
            return _create_workspace_dialogue(
                project_dir, game_path, map_name, npc_id, text, new_msgbox_type
            )

    return _apply_dialogue_update(
        game_path, map_name, npc_id, text, new_msgbox_type
    )


def _try_workspace_dialogue_update(project_dir, game_path, map_name, npc_id,
                                   text, new_msgbox_type):
    """Try to update dialogue in a workspace .txt file. Returns response or None."""
    data = load_map_json(game_path, map_name)
    if not data:
        return None

    events = data.get("object_events", [])
    idx = npc_id - 1
    if idx < 0 or idx >= len(events):
        return None

    script_label = events[idx].get("script", "")
    if not script_label:
        return None

    # Check if this script is in a workspace .txt file
    ws_dir = os.path.join(project_dir, map_name)
    if not os.path.isdir(ws_dir):
        return None

    target_file = None
    for fname in os.listdir(ws_dir):
        if not fname.endswith(".txt"):
            continue
        fpath = os.path.join(ws_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            if f"script {script_label}" in content:
                target_file = fpath
                break
        except OSError:
            continue

    if not target_file:
        return None

    # Found the workspace file — update msg/msgnpc line
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None

    # Ensure text ends with $
    if not text.endswith("$"):
        text = text + "$"

    updated = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("msgnpc ") or stripped.startswith('msgnpc "'):
            indent = line[:len(line) - len(line.lstrip())]
            lines[i] = f'{indent}msgnpc "{text}"\n'
            updated = True
            break
        if stripped.startswith("msg ") or stripped.startswith('msg "'):
            indent = line[:len(line) - len(line.lstrip())]
            cmd = "msg"
            if new_msgbox_type == "MSGBOX_NPC":
                cmd = "msgnpc"
            lines[i] = f'{indent}{cmd} "{text}"\n'
            updated = True
            break

    if not updated:
        return None

    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError as e:
        return error_response(f"Failed to write workspace file: {e}", 500)

    # Sync to scripts.pory
    _quiet_sync(project_dir, map_name, game_path)
    clear_project_cache()

    return ok_response({
        "updated": True,
        "label": script_label,
        "workspace_file": os.path.basename(target_file),
    })


def _create_workspace_dialogue(project_dir, game_path, map_name, npc_id,
                               text, new_msgbox_type):
    """Create a new script in workspace for an NPC that has no script (NULL).

    Generates label, writes .txt, updates map.json, syncs.
    """
    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get("object_events", [])
    idx = npc_id - 1
    if idx < 0 or idx >= len(events):
        return error_response(f"NPC #{npc_id} not found", 404)

    # Generate label from NPC graphics or position
    obj = events[idx]
    gfx = obj.get("graphics_id", "")
    short = _const_to_human_name(gfx, "OBJ_EVENT_GFX_").replace(" ", "")
    if not short:
        short = f"Npc{npc_id}"
    label = f"{map_name}_EventScript_{short}"

    # Ensure unique label
    counter = 1
    base_label = label
    while any(e.get("script") == label for e in events if e is not obj):
        label = f"{base_label}{counter}"
        counter += 1
        short = f"{short}{counter - 1}"

    # Ensure text ends with $
    if not text.endswith("$"):
        text = text + "$"

    # Determine command
    cmd = "msgnpc" if (new_msgbox_type or "MSGBOX_NPC") == "MSGBOX_NPC" else "msg"

    # Write workspace .txt
    torscript = f"script {label}\nlock\nfaceplayer\n{cmd} \"{text}\"\nrelease\nend"
    ws_dir = os.path.join(project_dir, map_name)
    os.makedirs(ws_dir, exist_ok=True)
    out_path = os.path.join(ws_dir, f"{short}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(torscript + "\n")

    # Update map.json with the new label
    events[idx]["script"] = label
    _write_map_json(game_path, map_name, data)

    # Sync
    _quiet_sync(project_dir, map_name, game_path)
    clear_project_cache()

    return ok_response({
        "updated": True,
        "label": label,
        "created": True,
        "workspace_file": f"{short}.txt",
    })


def _apply_dialogue_update(game_path, map_name, npc_id, text, new_msgbox_type):
    """Apply a dialogue text update to scripts.pory.

    Handles three cases:
    1. NPC has NULL/empty script → generate label, create script, update map.json
    2. Script label not found in scripts.pory → append new script block
    3. Script label found → replace msgbox text in existing script
    """
    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get("object_events", [])
    idx = npc_id - 1
    if idx < 0 or idx >= len(events):
        return error_response(f"NPC #{npc_id} not found", 404)

    script_label = events[idx].get("script", "")
    needs_label = not script_label or script_label in ("0x0", "0", "NULL")

    # Only support .pory editing
    pory_path = os.path.join(
        game_path, "data", "maps", map_name, "scripts.pory"
    )

    # Read existing content (create file if it doesn't exist)
    if os.path.isfile(pory_path):
        try:
            with open(pory_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            return error_response(f"Cannot read scripts.pory: {e}", 500)
    else:
        content = ""

    # Case 1: NPC has no script label — generate one and create a new script
    if needs_label:
        script_label = _generate_npc_label(map_name, events[idx], npc_id)
        return _create_and_assign_script(
            game_path, map_name, data, idx, script_label,
            pory_path, content, text, new_msgbox_type
        )

    # Case 2: Label exists but not found in scripts.pory — append new script
    pat = rf'\bscript\s+{re.escape(script_label)}\s*\{{'
    if not re.search(pat, content):
        return _create_and_assign_script(
            game_path, map_name, data, idx, script_label,
            pory_path, content, text, new_msgbox_type,
            update_map_json=False  # label already correct in map.json
        )

    # Case 3: Script found — check type and replace msgbox text
    stype = _classify_script(content, script_label)
    if stype not in _EDITABLE_TYPES:
        return error_response(
            f"Script type '{stype}' is not editable via the web editor",
            400
        )

    return _replace_dialogue_in_pory(
        pory_path, content, script_label, text, new_msgbox_type
    )


def _generate_npc_label(map_name, event, npc_id):
    """Generate a script label for an NPC that doesn't have one."""
    gfx = event.get("graphics_id", "")
    # Try to derive a name from the graphics ID
    name = _const_to_human_name(gfx, "OBJ_EVENT_GFX_")
    if name:
        clean = _sanitize_label_name(name.replace(" ", "_"))
    else:
        clean = f"NPC{npc_id}"
    return f"{map_name}_EventScript_{clean}"


def _create_and_assign_script(
    game_path, map_name, data, idx, script_label,
    pory_path, content, text, new_msgbox_type, update_map_json=True
):
    """Create a new flavor script, append to scripts.pory, optionally update map.json."""
    game_text = _readable_to_game_text(text)
    pory_text = game_text.rstrip("$")

    msgbox_type = new_msgbox_type or "MSGBOX_NPC"
    script_block = (
        f'script {script_label} {{\n'
        f'    msgbox(format("{pory_text}"), {msgbox_type})\n'
        f'}}\n'
    )

    # Append to scripts.pory
    separator = "\n\n" if content.rstrip() else ""
    new_content = content.rstrip() + separator + script_block

    try:
        _atomic_write(pory_path, new_content)
    except OSError as e:
        return error_response(f"Failed to write scripts.pory: {e}", 500)

    # Update map.json if needed (NPC had NULL/empty script)
    if update_map_json:
        data["object_events"][idx]["script"] = script_label
        try:
            _write_map_json(game_path, map_name, data)
        except OSError as e:
            return error_response(f"Failed to update map.json: {e}", 500)
        clear_project_cache()

    return ok_response({
        "updated": True,
        "created": True,
        "script_label": script_label,
        "dialogue": pory_text,
        "dialogue_readable": _game_text_to_readable(pory_text),
    })


def _replace_dialogue_in_pory(pory_path, content, label, text, new_msgbox_type):
    """Find and replace msgbox text in a .pory file."""
    # Convert readable text to game format
    game_text = _readable_to_game_text(text)
    # Strip trailing $ for Poryscript source (it's added by the game engine)
    pory_text = game_text.rstrip("$")

    # Find the script block
    pat = rf'\bscript\s+{re.escape(label)}\s*\{{'
    script_match = re.search(pat, content)
    if not script_match:
        return error_response(
            f"Script '{label}' not found in scripts.pory", 404
        )

    body = _extract_brace_block(content, script_match.start())
    if body is None:
        return error_response("Could not parse script block", 500)

    # Find msgbox in body — try format() form first
    body_start = content.find("{", script_match.start()) + 1
    body_section = content[body_start:body_start + len(body)]

    new_body = _replace_msgbox_text(body_section, pory_text, new_msgbox_type)
    if new_body is None:
        return error_response(
            "Could not find msgbox() call in script — manual edit required",
            400
        )

    new_content = content[:body_start] + new_body + content[body_start + len(body):]

    try:
        _atomic_write(pory_path, new_content)
    except OSError as e:
        return error_response(f"Failed to write scripts.pory: {e}", 500)

    return ok_response({
        "updated": True,
        "dialogue": pory_text,
        "dialogue_readable": _game_text_to_readable(pory_text),
    })


def _replace_msgbox_text(body, new_text, new_msgbox_type):
    """Replace msgbox text and optionally type in a script body.

    Returns the modified body, or None if no msgbox found.
    """
    # Try format() form: msgbox(format("text"), TYPE)
    fmt_pat = (
        r'(msgbox\s*\(\s*format\s*\(\s*)"((?:[^"\\]|\\.)*)"'
        r'(\s*\)\s*,\s*)(\w+)(\s*\))'
    )
    fmt_m = re.search(fmt_pat, body)
    if fmt_m:
        mtype = new_msgbox_type if new_msgbox_type else fmt_m.group(4)
        replacement = (
            fmt_m.group(1) + '"' + new_text + '"'
            + fmt_m.group(3) + mtype + fmt_m.group(5)
        )
        return body[:fmt_m.start()] + replacement + body[fmt_m.end():]

    # Try plain form: msgbox("text", TYPE)
    plain_pat = (
        r'(msgbox\s*\(\s*)"((?:[^"\\]|\\.)*)"(\s*,\s*)(\w+)(\s*\))'
    )
    plain_m = re.search(plain_pat, body)
    if plain_m:
        mtype = new_msgbox_type if new_msgbox_type else plain_m.group(4)
        replacement = (
            plain_m.group(1) + '"' + new_text + '"'
            + plain_m.group(3) + mtype + plain_m.group(5)
        )
        return body[:plain_m.start()] + replacement + body[plain_m.end():]

    return None


@api_route("POST", r"/api/npcs/(?P<map_name>[A-Za-z0-9_]+)/(?P<npc_id>\d+)/script")
def handle_npc_script(handler, match, query_params):
    """Reassign NPC script label in map.json."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    npc_id = int(match.group("npc_id"))

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body:
        return error_response("Request body required", 400)

    label = body.get("script_label", "")
    if not label:
        label = "Common_EventScript_NopReturn"

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get("object_events", [])
    idx = npc_id - 1
    if idx < 0 or idx >= len(events):
        return error_response(f"NPC #{npc_id} not found", 404)

    events[idx]["script"] = label
    _write_map_json(game_path, map_name, data)
    clear_project_cache()

    return ok_response({"updated": True, "script": label})


@api_route("POST", r"/api/npcs/(?P<map_name>[A-Za-z0-9_]+)/(?P<npc_id>\d+)")
def handle_npc_update(handler, match, query_params):
    """Update NPC properties in map.json."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    npc_id = int(match.group("npc_id"))

    try:
        body = _read_json_body(handler)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)
    if not body:
        return error_response("Request body required", 400)

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get("object_events", [])
    idx = npc_id - 1
    if idx < 0 or idx >= len(events):
        return error_response(f"NPC #{npc_id} not found", 404)

    obj = events[idx]

    # Validate and apply updates
    for field, value in body.items():
        if field not in _ALLOWED_FIELDS:
            continue
        if field in _INT_FIELDS:
            if not isinstance(value, int):
                return error_response(
                    f"Field '{field}' must be an integer, got {type(value).__name__}",
                    400
                )
        if field == "trainer_sight_or_berry_tree_id":
            value = str(value)
        obj[field] = value

    _write_map_json(game_path, map_name, data)
    clear_project_cache()

    # Return updated NPC summary
    gfx = obj.get("graphics_id", "")
    return ok_response({
        "npc": {
            "object_id": npc_id,
            "graphics_id": gfx,
            "display_name": _const_to_human_name(gfx, "OBJ_EVENT_GFX_"),
            "x": obj.get("x", 0),
            "y": obj.get("y", 0),
            "elevation": obj.get("elevation", 0),
            "movement_type": obj.get("movement_type", ""),
            "movement_range_x": obj.get("movement_range_x", 0),
            "movement_range_y": obj.get("movement_range_y", 0),
            "trainer_type": obj.get("trainer_type", "TRAINER_TYPE_NONE"),
            "trainer_sight_or_berry_tree_id": str(
                obj.get("trainer_sight_or_berry_tree_id", "0")
            ),
            "flag": obj.get("flag", "0"),
            "script": obj.get("script", ""),
        }
    })


@api_route("DELETE", r"/api/npcs/(?P<map_name>[A-Za-z0-9_]+)/(?P<npc_id>\d+)")
def handle_npc_delete(handler, match, query_params):
    """Delete an NPC (object_event) from map.json."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    npc_id = int(match.group("npc_id"))

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get("object_events", [])
    idx = npc_id - 1
    if idx < 0 or idx >= len(events):
        return error_response(f"NPC #{npc_id} not found (map has {len(events)} NPCs)", 404)

    # Capture info before deletion
    obj = events[idx]
    deleted_gfx = obj.get("graphics_id", "")
    deleted_script = obj.get("script", "")

    _remove_npc_from_map_json(game_path, map_name, idx)
    clear_project_cache()

    return ok_response({
        "deleted_id": npc_id,
        "deleted_graphics_id": deleted_gfx,
        "deleted_script": deleted_script,
    })


# ---------------------------------------------------------------------------
# Decompile — single NPC script to workspace
# ---------------------------------------------------------------------------

def _inject_aliases_from_localids(ts_text, inc_content, script_label, game_path, map_name):
    """Add alias directives for LOCALID references used in the script.

    Scans the original .inc for LOCALID_ references in the script body,
    resolves them to NPC indices via map.json local_id fields, and prepends
    alias lines to the TorScript output.
    """
    import re
    from torch.project_files import load_map_json

    # Find LOCALIDs referenced in the script block's .inc body
    body_match = re.search(
        rf'^{re.escape(script_label)}::(.+?)(?=^\w+::|\Z)',
        inc_content, re.MULTILINE | re.DOTALL)
    if not body_match:
        return ts_text

    body = body_match.group(1)
    localids = set(re.findall(r'LOCALID_\w+', body))
    # Also check for LOCALID_PLAYER which isn't a real NPC
    localids.discard("LOCALID_PLAYER")
    if not localids:
        return ts_text

    # Look up each LOCALID in map.json's object_events
    data = load_map_json(game_path, map_name)
    if not data:
        return ts_text

    alias_lines = []
    for i, obj in enumerate(data.get("object_events", [])):
        lid = obj.get("local_id", "")
        if lid in localids:
            alias_name = lid[len("LOCALID_"):].lower()
            npc_num = i + 1
            alias_lines.append(f"alias {alias_name} npc{npc_num}")
            localids.discard(lid)

    if not alias_lines:
        return ts_text

    # Prepend aliases before the script directive
    alias_block = "\n".join(sorted(alias_lines)) + "\n\n"

    # Insert before the first "script" line
    m = re.match(r'^(script\s+)', ts_text)
    if m:
        return alias_block + ts_text
    return alias_block + ts_text


def _strip_script_prefix(label, map_name):
    """Strip MapName_EventScript_ prefix from a label to get a short name."""
    prefix = f"{map_name}_EventScript_"
    if label.startswith(prefix):
        return label[len(prefix):]
    prefix2 = f"{map_name}_"
    if label.startswith(prefix2):
        return label[len(prefix2):]
    return label


def _decompile_inc_to_torscript(content, script_label):
    """Convert a simple .inc assembly script to TorScript.

    Handles: msgbox LABEL, TYPE + end patterns.
    Returns (torscript_text, warnings) or (None, [error]).
    """
    # Extract body
    pat = rf'^{re.escape(script_label)}::?\s*$'
    m = re.search(pat, content, re.MULTILINE)
    if not m:
        return None, [f"Label '{script_label}' not found in .inc"]

    rest = content[m.end():]
    body_lines = []
    for line in rest.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if not line[0:1].isspace() and (stripped.endswith(":") or "::" in stripped):
            break
        body_lines.append(stripped)

    if not body_lines:
        return None, ["Empty script body"]

    # Parse msgbox commands and resolve text labels
    ts_lines = [f"script {script_label}"]
    warnings = []
    has_lock = "lock" in body_lines
    has_faceplayer = "faceplayer" in body_lines

    if has_lock:
        ts_lines.append("lock")
    if has_faceplayer:
        ts_lines.append("faceplayer")

    for line in body_lines:
        if line in ("lock", "faceplayer", "release", "end", "return"):
            continue

        # msgbox TEXT_LABEL, MSGBOX_TYPE
        msg_m = re.match(r'^msgbox\s+(\w+),\s*(MSGBOX_\w+)$', line)
        if msg_m:
            text_label = msg_m.group(1)
            msgbox_type = msg_m.group(2)
            # Resolve text from .string blocks
            text = _resolve_inc_text(content, text_label)
            if text:
                cmd = "msgnpc" if msgbox_type == "MSGBOX_NPC" else "msg"
                ts_lines.append(f'{cmd} "{text}"')
            else:
                warnings.append(f"Could not resolve text label: {text_label}")
                ts_lines.append(f"pory msgbox({text_label}, {msgbox_type})")
            continue

        # trainerbattle
        tb_m = re.match(r'^trainerbattle_(\w+)\s+(.+)$', line)
        if tb_m:
            ts_lines.append(f"trainerbattle_{tb_m.group(1)} {tb_m.group(2)}")
            continue

        # Unknown → pory passthrough
        warnings.append(f"Unknown .inc command: {line}")
        ts_lines.append(f"pory {line}")

    if "release" in body_lines:
        ts_lines.append("release")
    ts_lines.append("end")

    return "\n".join(ts_lines), warnings


def _expand_battle_beats(ts_text):
    """Post-process TorScript to expand battle beats into multi-line form.

    Detects the pattern:
      trainerbattle_single TRAINER_X, "intro$", "defeated$"
      msg "postbattle$"
      end

    And collapses to:
      trainerbattle_single TRAINER_X
        intro "intro$"
        defeated "defeated$"
        postbattle "postbattle$"
      end
    """
    lines = ts_text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Match trainerbattle_* with quoted text args
        m = re.match(
            r'^(trainerbattle_\w+)\s+(TRAINER_\w+),\s*"(.+?)",\s*"(.+?)"(.*)$',
            stripped)
        if m:
            macro = m.group(1)
            trainer = m.group(2)
            intro_text = m.group(3)
            defeated_text = m.group(4)
            remaining = m.group(5).strip()  # extra args like callback labels

            # Look ahead for msg "postbattle" on next non-blank line
            postbattle_text = None
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                msg_m = re.match(r'^msg\w*\s+"(.+)"$', lines[j].strip())
                if msg_m:
                    postbattle_text = msg_m.group(1)
                    j += 1  # consume the msg line

            # Build expanded format
            if remaining:
                result.append(f"{macro} {trainer}, {remaining}")
            else:
                result.append(f"{macro} {trainer}")
            result.append(f'  intro "{intro_text}"')
            result.append(f'  defeated "{defeated_text}"')
            if postbattle_text:
                result.append(f'  postbattle "{postbattle_text}"')
            i = j
            continue

        result.append(line)
        i += 1

    return "\n".join(result)


def _resolve_external_text_labels(pory_text, game_path, map_name):
    """Resolve text label references in .pory output using external text files.

    Trainer text is typically defined in data/text/trainers.inc, not in the
    map's scripts.inc.  This function finds unresolved msgbox(LABEL, TYPE)
    patterns and inlines the actual text.
    """
    # Collect candidate text files
    text_files = []
    trainers_inc = os.path.join(game_path, "data", "text", "trainers.inc")
    if os.path.isfile(trainers_inc):
        text_files.append(trainers_inc)
    # Also check the map's own scripts.inc for any missed text
    scripts_inc = os.path.join(game_path, "data", "maps", map_name, "scripts.inc")
    if os.path.isfile(scripts_inc):
        text_files.append(scripts_inc)

    if not text_files:
        return pory_text

    # Cache loaded content
    text_content = {}
    for tf in text_files:
        try:
            with open(tf, "r", encoding="utf-8") as f:
                text_content[tf] = f.read()
        except OSError:
            pass

    def _try_resolve(label):
        for content in text_content.values():
            result = _resolve_inc_text(content, label)
            if result is not None:
                return result
        return None

    lines = pory_text.split("\n")
    resolved = []
    for line in lines:
        # Match trainerbattle_*(TRAINER, IntroLabel, DefeatedLabel, ...) — resolve text labels
        tb_m = re.match(r'^(\s*)(trainerbattle_\w+)\((.+)\)$', line)
        if tb_m:
            indent, macro, tb_args = tb_m.group(1), tb_m.group(2), tb_m.group(3)
            parts = [p.strip() for p in tb_args.split(",")]
            new_parts = []
            for p in parts:
                if re.match(r'^[A-Za-z_]\w*$', p) and not p.startswith("TRAINER_") and not p.startswith("TRUE") and not p.startswith("FALSE"):
                    text = _try_resolve(p)
                    if text is not None:
                        new_parts.append(f'"{text}"')
                        continue
                new_parts.append(p)
            resolved.append(f'{indent}{macro}({", ".join(new_parts)})')
            continue

        # Match msgbox(LABEL, TYPE) where LABEL is not quoted
        m = re.match(r'^(\s*)msgbox\(([A-Za-z_]\w*),\s*(\w+)\)$', line)
        if m:
            indent, label, msg_type = m.group(1), m.group(2), m.group(3)
            text = _try_resolve(label)
            if text is not None:
                resolved.append(f'{indent}msgbox("{text}", {msg_type})')
                continue
        resolved.append(line)
    return "\n".join(resolved)


def _resolve_inc_text(content, text_label):
    """Resolve a text label to its .string content from .inc file."""
    pat = rf'^{re.escape(text_label)}:\s*$'
    m = re.search(pat, content, re.MULTILINE)
    if not m:
        return None

    strings = []
    for line in content[m.end():].split("\n"):
        stripped = line.strip()
        if stripped.startswith(".string "):
            # Extract quoted text
            str_m = re.match(r'^\.string\s+"(.*)"$', stripped)
            if str_m:
                strings.append(str_m.group(1))
        elif stripped and not stripped.startswith("."):
            break  # Next label or directive
        elif not stripped:
            continue

    return "".join(strings) if strings else None


def _decompile_script_to_workspace(game_path, map_name, script_label, project_dir,
                                   overwrite=False):
    """Decompile a single script to a workspace .txt file.

    Handles both .pory (via decompiler) and .inc (via inc_decompiler pipeline).
    When *overwrite* is True, always re-decompile even if a workspace file
    already exists (used for auto-refresh on preview access).
    Returns (script_name, torscript_text, warnings) on success.
    Raises ValueError on failure.
    """
    filepath, file_type = _find_script(game_path, map_name, script_label)
    if not filepath:
        raise ValueError(f"Script '{script_label}' not found in game files")

    with open(filepath, "r", encoding="utf-8") as f:
        file_content = f.read()

    if file_type == "pory":
        stype = _classify_script(file_content, script_label)
    elif file_type == "inc":
        stype = _classify_inc_script(file_content, script_label)
    else:
        raise ValueError(f"Unsupported script format: {file_type}")

    if stype in ("nurse", "pc"):
        raise ValueError(f"System script ({stype}) — cannot be decompiled to workspace")
    if stype == "shared":
        raise ValueError("Shared/common script — cannot be decompiled to workspace")

    # Decompile based on format
    if file_type == "pory":
        from torch.decompiler import decompile_block
        ts_text, warnings = decompile_block(file_content, script_label, map_name)
    else:
        # .inc → .pory → TorScript (full pipeline)
        try:
            from torch.inc_decompiler import decompile_inc_block
            from torch.decompiler import decompile
            pory_text, inc_warnings = decompile_inc_block(file_content, script_label, map_name)
            if pory_text:
                # Resolve external text labels (e.g. trainer text in data/text/trainers.inc)
                pory_text = _resolve_external_text_labels(pory_text, game_path, map_name)
                ts_text, pory_warnings = decompile(pory_text, map_name)
                warnings = inc_warnings + pory_warnings
            else:
                ts_text = None
                warnings = inc_warnings
        except Exception:
            # Fallback to legacy pattern matcher
            ts_text, warnings = _decompile_inc_to_torscript(file_content, script_label)

    if ts_text is None:
        raise ValueError(warnings[0] if warnings else "Decompilation failed")

    # Expand battle beats: collapse trainerbattle + msg + end into multi-line form
    ts_text = _expand_battle_beats(ts_text)

    # Inject alias directives for LOCALID references found in the script.
    # The decompiler converts LOCALID_X to actor name "x" but doesn't emit
    # alias lines because it doesn't know the NPC index.  Look up in map.json.
    ts_text = _inject_aliases_from_localids(
        ts_text, file_content, script_label, game_path, map_name)

    # Determine output filename
    short_name = _strip_script_prefix(script_label, map_name)
    ws_dir = os.path.join(project_dir, map_name)
    os.makedirs(ws_dir, exist_ok=True)

    out_path = os.path.join(ws_dir, f"{short_name}.txt")
    if not overwrite and os.path.exists(out_path):
        # Don't overwrite user-edited files — skip with current content
        return short_name, ts_text, warnings

    # Write with warning header if applicable
    header = ""
    if warnings:
        header = "".join(f"# WARNING: {w}\n" for w in warnings) + "\n"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + ts_text + "\n")

    return short_name, ts_text, warnings


@api_route("POST", r"/api/npcs/(?P<map_name>[A-Za-z0-9_]+)/(?P<npc_id>\d+)/decompile")
def handle_npc_decompile(handler, match, query_params):
    """Decompile a single NPC's script to the workspace."""
    game_path = getattr(handler.server, "game_path", "")
    project_dir = getattr(handler.server, "project_dir", "")
    if not game_path or not project_dir:
        return error_response("Game/project path not configured", 500)

    map_name = match.group("map_name")
    npc_id = int(match.group("npc_id"))

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    events = data.get("object_events", [])
    idx = npc_id - 1
    if idx < 0 or idx >= len(events):
        return error_response(f"NPC #{npc_id} not found", 404)

    script_label = events[idx].get("script", "")
    if not script_label or script_label.startswith("Common_EventScript_"):
        return error_response("No decompilable script on this NPC", 400)

    try:
        script_name, ts_text, warnings = _decompile_script_to_workspace(
            game_path, map_name, script_label, project_dir,
        )
    except ValueError as e:
        return error_response(str(e), 400)

    # Auto-sync so scripts.pory gets REGION markers
    sync_ok = _quiet_sync(project_dir, map_name, game_path)

    clear_project_cache()
    return ok_response({
        "script_name": script_name,
        "torscript": ts_text,
        "warnings": warnings,
        "synced": sync_ok,
    })


# ---------------------------------------------------------------------------
# Decompile — all scripts on a map
# ---------------------------------------------------------------------------

@api_route("POST", r"/api/npcs/(?P<map_name>[A-Za-z0-9_]+)/decompile-all")
def handle_npc_decompile_all(handler, match, query_params):
    """Decompile all eligible scripts on a map to the workspace."""
    game_path = getattr(handler.server, "game_path", "")
    project_dir = getattr(handler.server, "project_dir", "")
    if not game_path or not project_dir:
        return error_response("Game/project path not configured", 500)

    map_name = match.group("map_name")

    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    # Ensure enrolled
    from torch.registry import enroll_map
    enroll_map(project_dir, map_name)

    # Collect unique script labels from object_events + bg_events
    labels = set()
    for obj in data.get("object_events", []):
        lbl = obj.get("script", "")
        if lbl and not lbl.startswith("Common_EventScript_"):
            labels.add(lbl)
    for bg in data.get("bg_events", []):
        lbl = bg.get("script", "")
        if lbl and not lbl.startswith("Common_EventScript_"):
            labels.add(lbl)

    imported = []
    skipped = []
    all_warnings = []

    for lbl in sorted(labels):
        try:
            script_name, _, warnings = _decompile_script_to_workspace(
                game_path, map_name, lbl, project_dir,
            )
            imported.append(script_name)
            all_warnings.extend(warnings)
        except ValueError as e:
            skipped.append({"label": lbl, "reason": str(e)})

    # Also decompile mapscripts to setup.pory if not already present
    ms_result = _decompile_mapscripts(game_path, map_name, project_dir)

    # Auto-sync
    sync_ok = _quiet_sync(project_dir, map_name, game_path)

    clear_project_cache()
    return ok_response({
        "imported": imported,
        "skipped": skipped,
        "mapscripts": ms_result,
        "warnings": all_warnings,
        "synced": sync_ok,
    })


def _decompile_mapscripts(game_path, map_name, project_dir):
    """Extract mapscripts block from scripts.pory and write to setup.pory."""
    pory_path = os.path.join(game_path, "data", "maps", map_name, "scripts.pory")
    if not os.path.isfile(pory_path):
        return None

    try:
        with open(pory_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    # Find mapscripts block
    m = re.search(r'mapscripts\s+(\w+)\s*\{', content)
    if not m:
        return None

    ws_dir = os.path.join(project_dir, map_name)
    setup_path = os.path.join(ws_dir, "setup.pory")

    # Don't overwrite existing setup.pory
    if os.path.exists(setup_path):
        return "exists"

    os.makedirs(ws_dir, exist_ok=True)

    # Extract from 'mapscripts' to matching '}'
    body = _extract_brace_block(content, m.start())
    if body is None:
        return None

    label = m.group(1)
    with open(setup_path, "w", encoding="utf-8") as f:
        f.write(f"mapscripts {label} {{\n")
        if body.strip():
            for line in body.strip().split("\n"):
                f.write(f"    {line.strip()}\n")
        f.write("}\n")

    return "created"


def _quiet_sync(project_dir, map_name, game_path):
    """Run a quiet sync from the web API (no TUI prompts)."""
    try:
        from torch.sync import sync_map
        from torch.web.api import _derive_sync_params
        emotes_conf, source_display = _derive_sync_params(project_dir)
        sync_map(map_name, project_dir, game_path,
                 emotes_conf, source_display,
                 quiet=True, skip_snapshot=True)
        return True
    except Exception:
        return False
