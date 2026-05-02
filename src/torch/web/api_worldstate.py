"""
api_worldstate.py — Worldstate simulation data endpoints.
TORCH_MODULE

Provides map-level worldstate data: NPC pages, visibility flags,
referenced flags/vars — everything the client-side WorldState
simulator needs.
"""

import os

from torch.web.api import api_route, ok_response, error_response
from torch.project_files import load_map_json, build_trainer_map_index


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/worldstate-data")
def handle_worldstate_data(handler, match, query_params):
    """Return worldstate simulation data for a map.

    Response:
    {
        "npcs": [
            {
                "npc_id": 1,
                "name": "Guard",
                "visibility_flag": "FLAG_HIDE_ROUTE1_GUARD",
                "pages": [
                    {"page_num": 1, "condition": "", "dialogue_preview": "Stop!"},
                    {"page_num": 2, "condition": "FLAG_BEAT_GYM",
                     "dialogue_preview": "Go ahead.", "hide": false}
                ]
            }
        ],
        "referenced_flags": ["FLAG_BEAT_GYM", "FLAG_HIDE_ROUTE1_GUARD"],
        "referenced_vars": ["VAR_STORY_PROGRESS"]
    }
    """
    game_path = getattr(handler.server, "game_path", "")
    project_dir = getattr(handler.server, "project_dir", "")
    if not game_path:
        return error_response("No game path configured", 500)

    map_name = match.group("map_name")
    data = load_map_json(game_path, map_name)
    if not data:
        return error_response(f"Map not found: {map_name}", 404)

    npcs = []
    ref_flags = set()
    ref_vars = set()

    events = data.get("object_events", [])
    for idx, obj in enumerate(events):
        npc_id = idx + 1
        gfx = obj.get("graphics_id", "")
        # Resolve local_id constant name (LOCALID_* string or numeric)
        local_id_raw = obj.get("local_id", "")
        local_id_const = ""
        if isinstance(local_id_raw, str) and local_id_raw.startswith("LOCALID_"):
            local_id_const = local_id_raw
        elif isinstance(local_id_raw, int):
            local_id_const = str(local_id_raw)
        script_label = obj.get("script", "")
        if script_label in ("0x0", "0", ""):
            script_label = ""

        # Visibility flag
        vis_flag = obj.get("flag", "")
        if vis_flag in ("0", "0x0", ""):
            vis_flag = ""
        if vis_flag:
            ref_flags.add(vis_flag)

        # Detect pages from workspace (TorScript page directives)
        pages = _detect_pages(project_dir, map_name, script_label)
        for p in pages:
            _collect_condition_refs(p.get("condition", ""), ref_flags, ref_vars)

        # If no workspace pages, detect implicit pages from Poryscript branches
        if not pages and script_label:
            pages = _detect_pory_branches(game_path, map_name, script_label)
            for p in pages:
                _collect_condition_refs(p.get("condition", ""), ref_flags, ref_vars)

        # Dialogue preview for page-less NPCs
        dialogue_preview = ""
        if not pages:
            dialogue_preview = _get_dialogue_preview(
                game_path, map_name, script_label)

        # Human-readable name
        name = _gfx_to_name(gfx)

        npcs.append({
            "npc_id": npc_id,
            "name": name,
            "graphics_id": gfx,
            "local_id_const": local_id_const,
            "visibility_flag": vis_flag,
            "pages": pages,
            "dialogue_preview": dialogue_preview,
            "x": obj.get("x", 0),
            "y": obj.get("y", 0),
        })

    # Parse ON_TRANSITION script for NPC position/visibility overrides
    transition_rules = _parse_transition_script(game_path, map_name)
    for rule in transition_rules:
        _collect_condition_refs(rule.get("condition", ""), ref_flags, ref_vars)

    # Scan map scripts for additional flag/var references
    _scan_script_refs(game_path, map_name, ref_flags, ref_vars)

    # Also scan workspace .txt files for flag/var usage
    _scan_workspace_refs(project_dir, map_name, ref_flags, ref_vars)

    # Load global worldstate conditions
    global_conditions = _load_global_conditions(game_path)

    # Build sprite URL map for variable sprite overrides
    sprite_url_map = _build_sprite_url_map(game_path, transition_rules, global_conditions)

    return ok_response({
        "npcs": npcs,
        "sprite_url_map": sprite_url_map,
        "transition_rules": transition_rules,
        "global_conditions": global_conditions,
        "referenced_flags": sorted(ref_flags),
        "referenced_vars": sorted(ref_vars),
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_pages(project_dir, map_name, script_label):
    """Scan workspace .txt files for page directives targeting this NPC."""
    if not project_dir or not script_label:
        return []
    ws_dir = os.path.join(project_dir, map_name)
    if not os.path.isdir(ws_dir):
        return []

    pages = []
    current_page = None
    for fname in sorted(os.listdir(ws_dir)):
        if not fname.endswith(".txt"):
            continue
        try:
            with open(os.path.join(ws_dir, fname), "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    tokens = stripped.split()
                    cmd = tokens[0]
                    if cmd == "page" and len(tokens) >= 2:
                        try:
                            pnum = int(tokens[1])
                        except ValueError:
                            continue
                        cond = ""
                        hide = False
                        if len(tokens) >= 4 and tokens[2] == "if":
                            cond = " ".join(tokens[3:])
                        current_page = {
                            "page_num": pnum,
                            "condition": cond,
                            "hide": hide,
                            "dialogue_preview": "",
                        }
                    elif cmd in ("hide", "remove") and current_page and not current_page.get("_has_label"):
                        current_page["hide"] = True
                    elif cmd in ("label", "script") and len(tokens) >= 2:
                        label = tokens[1].rstrip(":")
                        if label == script_label and current_page:
                            current_page["_has_label"] = True
                    elif cmd in ("msg", "msgnpc") and current_page and current_page.get("_has_label"):
                        # Extract dialogue preview
                        import re
                        m = re.match(r'^(?:msg|msgnpc)\s+"(.*)"', stripped)
                        if m and not current_page["dialogue_preview"]:
                            text = m.group(1).replace("\\n", " ").replace("\\p", " ")
                            text = text.rstrip("$")
                            if len(text) > 60:
                                text = text[:57] + "..."
                            current_page["dialogue_preview"] = text
                    elif cmd == "end" and current_page and current_page.get("_has_label"):
                        # Page body ended — finalize
                        pg = dict(current_page)
                        pg.pop("_has_label", None)
                        if label == script_label:
                            pages.append(pg)
                        current_page = None
        except OSError:
            continue

    pages.sort(key=lambda p: p["page_num"])
    return pages


def _detect_pory_branches(game_path, map_name, script_label):
    """Detect implicit NPC pages from Poryscript flag/var/defeated branches.

    Parses scripts.pory for patterns like:
      script Label {
          if (flag(FLAG_X)) { goto(Label_After) }
          msgbox("default dialogue", ...)
      }
      script Label_After { msgbox("after dialogue", ...) }

    Returns page-like dicts compatible with the worldstate simulator.
    """
    import re

    pory_path = os.path.join(game_path, "data", "maps", map_name, "scripts.pory")
    if not os.path.isfile(pory_path):
        return []

    try:
        with open(pory_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return []

    # Find the script block for this label
    # Pattern: script Label { ... }
    script_pat = re.compile(
        r'script\s+' + re.escape(script_label) + r'\s*\{',
        re.MULTILINE,
    )
    m = script_pat.search(content)
    if not m:
        return []

    # Extract the script body (brace matching)
    start = m.end()
    body = _extract_brace_body(content, start)
    if not body:
        return []

    # Find condition branches in the body
    pages = []
    page_num = 2  # page 1 is always the default

    # Pattern: if (flag(FLAG_X)) { ... }
    # Pattern: if (defeated(TRAINER_X)) { ... }
    # Pattern: if (var(VAR_X) op N) { ... }
    branch_pat = re.compile(
        r'if\s*\('
        r'(?:'
        r'flag\((\w+)\)'                              # group 1: flag name
        r'|defeated\((\w+)\)'                          # group 2: trainer
        r'|var\((\w+)\)\s*(==|!=|>=?|<=?)\s*(\w+)'    # groups 3,4,5: var/op/val
        r'|!flag\((\w+)\)'                             # group 6: negated flag
        r')'
        r'\s*\)',
    )

    for bm in branch_pat.finditer(body):
        flag_name = bm.group(1)
        trainer = bm.group(2)
        var_name = bm.group(3)
        var_op = bm.group(4)
        var_val = bm.group(5)
        neg_flag = bm.group(6)

        condition = ""
        if flag_name:
            condition = flag_name
        elif trainer:
            condition = f"defeated {trainer}"
        elif var_name:
            condition = f"{var_name} {var_op} {var_val}"
        elif neg_flag:
            condition = f"not {neg_flag}"

        if not condition:
            continue

        # Try to extract dialogue from the branch body
        branch_start = bm.end()
        branch_body = _extract_brace_body(content, branch_start)
        dialogue_preview = _extract_pory_dialogue_preview(branch_body or "")

        # Also check for goto(Label) pattern — follow the goto target
        if not dialogue_preview and branch_body:
            goto_m = re.search(r'goto\((\w+)\)', branch_body)
            if goto_m:
                target = goto_m.group(1)
                target_body = _find_script_body(content, target)
                if target_body:
                    dialogue_preview = _extract_pory_dialogue_preview(target_body)

        pages.append({
            "page_num": page_num,
            "condition": condition,
            "hide": False,
            "dialogue_preview": dialogue_preview,
            "source": "pory",  # mark as auto-detected, not TorScript
        })
        page_num += 1

    if not pages:
        return []

    # Add default page (page 1) with the fallback dialogue
    default_dialogue = _extract_pory_dialogue_preview(body)
    pages.insert(0, {
        "page_num": 1,
        "condition": "",
        "hide": False,
        "dialogue_preview": default_dialogue,
        "source": "pory",
    })

    return pages


def _extract_brace_body(content, start_after_open_brace):
    """Extract content between { } starting after the opening brace position."""
    depth = 1
    i = start_after_open_brace
    while i < len(content) and depth > 0:
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
        i += 1
    if depth != 0:
        return None
    return content[start_after_open_brace:i - 1]


def _find_script_body(content, label):
    """Find and extract a script body by label name."""
    import re
    pat = re.compile(r'script\s+' + re.escape(label) + r'\s*\{')
    m = pat.search(content)
    if not m:
        return None
    return _extract_brace_body(content, m.end())


def _extract_pory_dialogue_preview(body):
    """Extract first msgbox text from a Poryscript body."""
    import re
    m = re.search(r'msgbox\s*\(\s*(?:format\s*\(\s*)?["\'](.+?)["\']', body)
    if not m:
        return ""
    text = m.group(1)
    text = text.replace("\\n", " ").replace("\\p", " ").replace("\\l", " ")
    text = text.rstrip("$")
    if len(text) > 60:
        text = text[:57] + "..."
    return text


def _parse_transition_script(game_path, map_name):
    """Parse ON_TRANSITION scripts for NPC position/visibility changes.

    Scans scripts.pory and scripts.inc for patterns like:
      call_if_set FLAG_X, Label
      call_if_unset FLAG_X, Label
      ...
      Label::
        setobjectxyperm LOCALID_X, X, Y
        setobjectmovementtype LOCALID_X, TYPE
        removeobject LOCALID_X
        addobject LOCALID_X

    Returns list of transition rules:
    [
      {
        "condition": "FLAG_X" or "not FLAG_X",
        "actions": [
          {"type": "setpos", "local_id": "LOCALID_X", "x": 1, "y": 11},
          {"type": "setmovement", "local_id": "LOCALID_X", "movement": "MOVEMENT_TYPE_FACE_LEFT"},
          {"type": "remove", "local_id": "LOCALID_X"},
          {"type": "add", "local_id": "LOCALID_X"},
        ]
      }
    ]
    """
    import re

    # Try scripts.pory first, then scripts.inc
    content = None
    for fname in ("scripts.pory", "scripts.inc"):
        fpath = os.path.join(game_path, "data", "maps", map_name, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                break
            except OSError:
                continue
    if not content:
        return []

    # Also scan shared scripts (data/scripts/*.inc) for called labels
    scripts_dir = os.path.join(game_path, "data", "scripts")
    if os.path.isdir(scripts_dir):
        for fname in os.listdir(scripts_dir):
            if fname.endswith((".inc", ".pory")):
                try:
                    with open(os.path.join(scripts_dir, fname), "r",
                              encoding="utf-8") as f:
                        content += "\n" + f.read()
                except OSError:
                    pass

    # Find the ON_TRANSITION entry point
    # Pattern: map_script MAP_SCRIPT_ON_TRANSITION, LabelName
    m = re.search(r'MAP_SCRIPT_ON_TRANSITION\s*,\s*(\w+)', content)
    if not m:
        # Try Poryscript format: MAP_SCRIPT_ON_TRANSITION [ Label ]
        m = re.search(r'MAP_SCRIPT_ON_TRANSITION\s*\[\s*(\w+)', content)
    if not m:
        return []

    transition_label = m.group(1)

    # Parse labels into a dict: label_name -> [lines]
    labels = _parse_labels(content)
    if transition_label not in labels:
        return []

    rules = []
    transition_body = labels[transition_label]

    for line in transition_body:
        stripped = line.strip()

        # call_if_set FLAG_X, Label -> condition: FLAG_X
        cm = re.match(r'call_if_set\s+(\w+)\s*,\s*(\w+)', stripped)
        if cm:
            flag, target = cm.group(1), cm.group(2)
            actions = _extract_actions(labels.get(target, []))
            if actions:
                rules.append({"condition": flag, "actions": actions})
            continue

        # call_if_unset FLAG_X, Label -> condition: not FLAG_X
        cm = re.match(r'call_if_unset\s+(\w+)\s*,\s*(\w+)', stripped)
        if cm:
            flag, target = cm.group(1), cm.group(2)
            actions = _extract_actions(labels.get(target, []))
            if actions:
                rules.append({"condition": f"not {flag}", "actions": actions})
            continue

        # goto_if_set FLAG_X, Label
        cm = re.match(r'goto_if_set\s+(\w+)\s*,\s*(\w+)', stripped)
        if cm:
            flag, target = cm.group(1), cm.group(2)
            actions = _extract_actions(labels.get(target, []))
            if actions:
                rules.append({"condition": flag, "actions": actions})
            continue

        # goto_if_unset FLAG_X, Label
        cm = re.match(r'goto_if_unset\s+(\w+)\s*,\s*(\w+)', stripped)
        if cm:
            flag, target = cm.group(1), cm.group(2)
            actions = _extract_actions(labels.get(target, []))
            if actions:
                rules.append({"condition": f"not {flag}", "actions": actions})
            continue

        # Poryscript: if (flag(FLAG_X)) { ... }
        cm = re.match(r'if\s*\(\s*flag\((\w+)\)\s*\)', stripped)
        if cm:
            flag = cm.group(1)
            # Collect actions from the if-block body (simple heuristic)
            actions = _extract_actions(transition_body)
            if actions:
                rules.append({"condition": flag, "actions": actions})
            continue

        # Unconditional call — follow the target and extract its actions
        # (handles patterns like: call Common_EventScript_SetupRivalGfxId)
        cm = re.match(r'call\s+(\w+)', stripped)
        if cm:
            target = cm.group(1)
            target_lines = labels.get(target, [])

            # Check for checkplayergender pattern:
            #   checkplayergender
            #   goto_if_eq VAR_RESULT, MALE, LabelMale
            #   goto_if_eq VAR_RESULT, FEMALE, LabelFemale
            has_gender_check = any("checkplayergender" in tl for tl in target_lines)
            if has_gender_check:
                for tl in target_lines:
                    tl_stripped = tl.strip()
                    sm = re.match(
                        r'goto_if_eq\s+VAR_RESULT\s*,\s*(MALE|FEMALE)\s*,\s*(\w+)',
                        tl_stripped
                    )
                    if sm:
                        gender, sub_label = sm.group(1), sm.group(2)
                        sub_actions = _extract_actions(labels.get(sub_label, []))
                        if sub_actions:
                            cond = f"PLAYER_GENDER_{gender}"
                            rules.append({"condition": cond, "actions": sub_actions})
            else:
                # Generic unconditional call — follow all sub-branches
                actions = _extract_actions(target_lines)
                for tl in target_lines:
                    tl_stripped = tl.strip()
                    sm = re.match(r'goto_if_eq\s+\w+\s*,\s*\w+\s*,\s*(\w+)', tl_stripped)
                    if sm:
                        sub_actions = _extract_actions(labels.get(sm.group(1), []))
                        actions.extend(sub_actions)
                if actions:
                    rules.append({"condition": "", "actions": actions})
            continue

        # Unconditional actions in the transition body itself
        action = _parse_single_action(stripped)
        if action:
            rules.append({"condition": "", "actions": [action]})

    return rules


def _parse_labels(content):
    """Parse assembly labels from script content.

    Returns dict: label_name -> [body_lines]
    """
    import re
    labels = {}
    current_label = None
    current_lines = []

    for line in content.split("\n"):
        stripped = line.strip()
        # Label definition: Name: or Name::
        m = re.match(r'^(\w+)::?\s*$', stripped)
        if m:
            if current_label:
                labels[current_label] = current_lines
            current_label = m.group(1)
            current_lines = []
            continue
        if current_label:
            if stripped in ("", ".byte 0"):
                continue
            if stripped.startswith("@") or stripped.startswith("//"):
                continue
            if stripped in ("end", "return"):
                current_lines.append(stripped)
                labels[current_label] = current_lines
                current_label = None
                current_lines = []
                continue
            current_lines.append(stripped)

    if current_label:
        labels[current_label] = current_lines

    return labels


def _extract_actions(lines):
    """Extract NPC position/visibility actions from a label's body."""
    actions = []
    for line in lines:
        action = _parse_single_action(line.strip())
        if action:
            actions.append(action)
    return actions


def _parse_single_action(line):
    """Parse a single line for NPC position/visibility commands."""
    import re

    # setobjectxyperm LOCALID_X, X, Y
    m = re.match(r'setobjectxyperm\s+(\w+)\s*,\s*(\d+)\s*,\s*(\d+)', line)
    if m:
        return {"type": "setpos", "local_id": m.group(1),
                "x": int(m.group(2)), "y": int(m.group(3))}

    # setobjectxy LOCALID_X, X, Y
    m = re.match(r'setobjectxy\s+(\w+)\s*,\s*(\d+)\s*,\s*(\d+)', line)
    if m:
        return {"type": "setpos", "local_id": m.group(1),
                "x": int(m.group(2)), "y": int(m.group(3))}

    # setobjectmovementtype LOCALID_X, MOVEMENT_TYPE_X
    m = re.match(r'setobjectmovementtype\s+(\w+)\s*,\s*(\w+)', line)
    if m:
        return {"type": "setmovement", "local_id": m.group(1),
                "movement": m.group(2)}

    # removeobject LOCALID_X
    m = re.match(r'removeobject\s+(\w+)', line)
    if m:
        return {"type": "remove", "local_id": m.group(1)}

    # addobject LOCALID_X
    m = re.match(r'addobject\s+(\w+)', line)
    if m:
        return {"type": "add", "local_id": m.group(1)}

    # setvar VAR_OBJ_GFX_ID_N, OBJ_EVENT_GFX_* (sprite variable assignment)
    m = re.match(r'setvar\s*\(?\s*(VAR_OBJ_GFX_ID_\d)\s*,\s*(OBJ_EVENT_GFX_\w+)', line)
    if m:
        return {"type": "setsprite", "var": m.group(1), "gfx": m.group(2)}

    return None


def _build_sprite_url_map(game_path, transition_rules, global_conditions=None):
    """Build a mapping from OBJ_EVENT_GFX_* constants to sprite URLs.

    Includes constants referenced by setsprite actions in transition rules,
    plus the player/rival sprites when PLAYER_GENDER is a global condition.
    """
    gfx_constants = set()
    for rule in transition_rules:
        for action in rule.get("actions", []):
            if action.get("type") == "setsprite":
                gfx_constants.add(action["gfx"])
    # Always include Brendan and May sprites when PLAYER_GENDER is configured,
    # since VAR_OBJ_GFX_ID_0 (rival) is set based on player gender at game start.
    has_gender_cond = any(
        c.get("variable") == "PLAYER_GENDER"
        for c in (global_conditions or [])
    )
    if has_gender_cond:
        gfx_constants.add("OBJ_EVENT_GFX_BRENDAN_NORMAL")
        gfx_constants.add("OBJ_EVENT_GFX_MAY_NORMAL")
    if not gfx_constants:
        return {}

    try:
        from torch.web.api import build_sprite_index
        sprite_index = build_sprite_index(game_path)
    except Exception:
        return {}

    url_map = {}
    prefix = "graphics/object_events/pics/"
    for gfx in gfx_constants:
        entry = sprite_index.get(gfx, {})
        if entry.get("png", "").startswith(prefix):
            url_map[gfx] = {
                "url": "/api/npc_sprites/" + entry["png"][len(prefix):],
                "width": entry.get("width", 16),
                "height": entry.get("height", 32),
            }
    return url_map


def _scan_script_refs(game_path, map_name, flags_set, vars_set):
    """Scan the map's scripts.pory for flag/var references."""
    import re
    pory_path = os.path.join(game_path, "data", "maps", map_name, "scripts.pory")
    if not os.path.isfile(pory_path):
        return
    try:
        with open(pory_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return

    # Find flag references: flag(FLAG_X), setflag(FLAG_X), clearflag(FLAG_X),
    # goto_if_set(FLAG_X, ...), etc.
    for m in re.finditer(r'\bFLAG_[A-Z0-9_]+\b', content):
        name = m.group(0)
        # Skip common noise flags
        if name in ("FLAG_TEMP_1", "FLAG_TEMP_2", "FLAG_TEMP_3"):
            continue
        flags_set.add(name)

    # Find var references: var(VAR_X), setvar(VAR_X, ...), etc.
    for m in re.finditer(r'\bVAR_[A-Z0-9_]+\b', content):
        name = m.group(0)
        # Skip scratch vars
        if name.startswith("VAR_0x80") or name in ("VAR_RESULT", "VAR_TEMP_0"):
            continue
        vars_set.add(name)


def _scan_workspace_refs(project_dir, map_name, flags_set, vars_set):
    """Scan workspace .txt files for flag/var references."""
    import re
    if not project_dir:
        return
    ws_dir = os.path.join(project_dir, map_name)
    if not os.path.isdir(ws_dir):
        return
    for fname in os.listdir(ws_dir):
        if not fname.endswith(".txt"):
            continue
        try:
            with open(os.path.join(ws_dir, fname), "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        for m in re.finditer(r'\bFLAG_[A-Z0-9_]+\b', content):
            name = m.group(0)
            if name not in ("FLAG_TEMP_1", "FLAG_TEMP_2", "FLAG_TEMP_3"):
                flags_set.add(name)
        for m in re.finditer(r'\bVAR_[A-Z0-9_]+\b', content):
            name = m.group(0)
            if not name.startswith("VAR_0x80") and name not in ("VAR_RESULT", "VAR_TEMP_0"):
                vars_set.add(name)


def _collect_condition_refs(condition_str, flags_set, vars_set):
    """Extract FLAG_ and VAR_ references from a raw condition string."""
    if not condition_str:
        return
    for token in condition_str.split():
        if token.startswith("FLAG_"):
            flags_set.add(token)
        elif token.startswith("VAR_"):
            vars_set.add(token)


def _get_dialogue_preview(game_path, map_name, script_label):
    """Get a short dialogue preview for a non-paged NPC."""
    if not script_label:
        return ""
    try:
        from torch.bulk_decompile import find_script
        filepath, ftype = find_script(game_path, map_name, script_label)
        if not filepath:
            return ""
        import re
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        # Look for msgbox("...", in Poryscript
        m = re.search(r'msgbox\s*\(\s*(?:format\s*\(\s*)?["\'](.+?)["\']', content)
        if m:
            text = m.group(1).replace("\\n", " ").replace("\\p", " ").rstrip("$")
            if len(text) > 60:
                text = text[:57] + "..."
            return text
    except Exception:
        pass
    return ""


def _gfx_to_name(gfx):
    """Convert OBJ_EVENT_GFX_FOO to 'Foo'."""
    if not gfx:
        return "NPC"
    name = gfx.replace("OBJ_EVENT_GFX_", "")
    return name.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Global Worldstate Conditions
# ---------------------------------------------------------------------------

_GLOBAL_WS_FILE = "global_worldstate.json"

# Default conditions that ship with every project
_DEFAULT_GLOBAL_CONDITIONS = [
    {
        "id": "player_gender",
        "name": "Player Gender",
        "variable": "PLAYER_GENDER",
        "type": "choice",
        "options": [
            {"label": "Male", "value": "MALE"},
            {"label": "Female", "value": "FEMALE"},
        ],
        "default": "MALE",
        "current": "MALE",
        "builtin": True,
    },
]


def _global_ws_path(game_path):
    return os.path.join(game_path, ".torch", _GLOBAL_WS_FILE)


def _load_global_conditions(game_path):
    """Load global worldstate conditions from project config."""
    if not game_path:
        return list(_DEFAULT_GLOBAL_CONDITIONS)

    path = _global_ws_path(game_path)
    if not os.path.isfile(path):
        return list(_DEFAULT_GLOBAL_CONDITIONS)

    try:
        import json
        with open(path, "r") as f:
            data = json.load(f)
        if data.get("version") != 1:
            return list(_DEFAULT_GLOBAL_CONDITIONS)
        conditions = data.get("conditions", [])
        # Ensure builtins are present
        builtin_ids = {c["id"] for c in conditions if c.get("builtin")}
        for default in _DEFAULT_GLOBAL_CONDITIONS:
            if default["id"] not in builtin_ids:
                conditions.insert(0, dict(default))
        return conditions
    except (json.JSONDecodeError, OSError):
        return list(_DEFAULT_GLOBAL_CONDITIONS)


def _save_global_conditions(game_path, conditions):
    """Save global worldstate conditions to project config."""
    if not game_path:
        return
    import json
    import tempfile

    dir_path = os.path.join(game_path, ".torch")
    os.makedirs(dir_path, exist_ok=True)
    path = _global_ws_path(game_path)
    data = {"version": 1, "conditions": conditions}
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@api_route("GET", r"/api/worldstate/global-conditions")
def handle_get_global_conditions(handler, match, query_params):
    """Get all global worldstate conditions."""
    game_path = getattr(handler.server, "game_path", "")
    conditions = _load_global_conditions(game_path)
    return ok_response({"conditions": conditions})


@api_route("POST", r"/api/worldstate/global-conditions")
def handle_save_global_conditions(handler, match, query_params):
    """Save global worldstate conditions (full replace)."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    import json
    try:
        length = int(handler.headers.get("Content-Length", 0))
        body = json.loads(handler.rfile.read(length)) if length else {}
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)

    conditions = body.get("conditions", [])
    _save_global_conditions(game_path, conditions)
    return ok_response({"saved": True})


@api_route("POST", r"/api/worldstate/global-conditions/set-value")
def handle_set_condition_value(handler, match, query_params):
    """Update a single condition's current value."""
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return error_response("No game path configured", 500)

    import json
    try:
        length = int(handler.headers.get("Content-Length", 0))
        body = json.loads(handler.rfile.read(length)) if length else {}
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON body", 400)

    cond_id = body.get("id", "")
    value = body.get("value", "")
    if not cond_id:
        return error_response("Missing condition id", 400)

    conditions = _load_global_conditions(game_path)
    found = False
    for c in conditions:
        if c["id"] == cond_id:
            c["current"] = value
            found = True
            break

    if not found:
        return error_response(f"Condition '{cond_id}' not found", 404)

    _save_global_conditions(game_path, conditions)
    return ok_response({"updated": True})


# ---------------------------------------------------------------------------
# Per-map trainer constants
# ---------------------------------------------------------------------------

@api_route("GET", r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/trainers")
def handle_map_trainers(handler, match, query_params):
    """Return TRAINER_* constants referenced in a specific map's scripts.

    Uses the cached build_trainer_map_index from project_files.py — same
    scan that powers the trainer editor's map associations.

    Returns: { trainers: ["TRAINER_FOO", ...] } sorted.
    """
    map_name = match.group("map_name")
    game_path = getattr(handler.server, "game_path", "")
    if not game_path:
        return ok_response({"trainers": []})

    map_trainers, _ = build_trainer_map_index(game_path)
    trainers = map_trainers.get(map_name, [])
    return ok_response({"trainers": trainers})
