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

_EDITABLE_TYPES = {"flavor", "sign", "item_giver", "complex", "custom"}


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
    if not script_label:
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

        dlg = _extract_inc_dialogue(content, script_label)
        dialogue = dlg["text"] if dlg else None
        dialogue_readable = _game_text_to_readable(dialogue) if dialogue else None
        return "inc", "scripts.inc", dialogue, dialogue_readable

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


def _create_flavor(game_path, map_name, body):
    """Create a flavor NPC (object_event + script)."""
    safe_name = _sanitize_label_name(body["name"])
    if not safe_name:
        return error_response("Name produces empty label after sanitization", 400)
    label = f"{map_name}_EventScript_{safe_name}"
    text = body["dialogue"].rstrip("$") + "$"

    script = _generate_flavor_npc(map_name, label, text)
    _write_script_to_pory(game_path, map_name, script)

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


def _create_sign(game_path, map_name, body):
    """Create a sign (bg_event + script)."""
    safe_name = _sanitize_label_name(body["name"])
    if not safe_name:
        return error_response("Name produces empty label after sanitization", 400)
    label = f"{map_name}_EventScript_{safe_name}"
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
        "type": "sign",
        "event_type": "bg_event",
    })


def _create_item_giver(game_path, map_name, body):
    """Create an item giver NPC (object_event + script)."""
    safe_name = _sanitize_label_name(body["name"])
    if not safe_name:
        return error_response("Name produces empty label after sanitization", 400)
    label = f"{map_name}_EventScript_{safe_name}"
    text_before = body["before_text"].rstrip("$") + "$"
    text_after = body["after_text"].rstrip("$") + "$"

    script = _generate_item_giver(
        map_name, label, body["item"], body["flag"], text_before, text_after
    )
    _write_script_to_pory(game_path, map_name, script)

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

    return _apply_dialogue_update(
        game_path, map_name, npc_id, text, new_msgbox_type
    )


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
