# TORCH_MODULE: Bulk Decompile
# TORCH_GROUP: Core
"""Shared decompilation pipeline for maps — used by both CLI and web GUI.

Provides per-map and project-wide decompilation from game files (.pory/.inc)
to TorScript workspace (.txt) files.  Extracted from web/api_npc_editor.py
to allow CLI access without web dependencies.
"""

import os
import re

from torch.project_files import load_map_json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRISTINE_HEADER = "# Auto-decompiled by TORCH -- edit this file to claim the map\n"


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
# Script discovery
# ---------------------------------------------------------------------------

def find_script(game_path, map_name, label):
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
# Script classification
# ---------------------------------------------------------------------------

def classify_script(content, label):
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

    if msgbox_calls:
        return "custom"

    return "complex"


def classify_inc_script(content, label):
    """Classify an assembly (.inc) script block.

    Returns same types as classify_script: flavor/sign/custom/complex/nurse/pc.
    """
    pat = rf'^{re.escape(label)}::?\s*$'
    m = re.search(pat, content, re.MULTILINE)
    if not m:
        return "complex"

    rest = content[m.end():]
    body_lines = []
    for line in rest.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if not line[0:1].isspace() and stripped.endswith(":"):
            break
        if not line[0:1].isspace() and "::" in stripped:
            break
        body_lines.append(stripped)

    if not body_lines:
        return "complex"

    body_text = " ".join(body_lines)

    if "special ShowPokemonStorageSystem" in body_text:
        return "pc"
    if "special HealPlayerParty" in body_text or "HealPlayerTeam" in body_text:
        return "nurse"
    if "giveitem" in body_text.lower():
        return "item_giver"

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
# Label helpers
# ---------------------------------------------------------------------------

def strip_script_prefix(label, map_name):
    """Strip MapName_EventScript_ prefix from a label to get a short name."""
    prefix = f"{map_name}_EventScript_"
    if label.startswith(prefix):
        return label[len(prefix):]
    prefix2 = f"{map_name}_"
    if label.startswith(prefix2):
        return label[len(prefix2):]
    return label


# ---------------------------------------------------------------------------
# Text resolution
# ---------------------------------------------------------------------------

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
            str_m = re.match(r'^\.string\s+"(.*)"$', stripped)
            if str_m:
                strings.append(str_m.group(1))
        elif stripped and not stripped.startswith("."):
            break
        elif not stripped:
            continue

    return "".join(strings) if strings else None


def resolve_external_text_labels(pory_text, game_path, map_name):
    """Resolve text label references in .pory output using external text files.

    Trainer text is typically defined in data/text/trainers.inc, not in the
    map's scripts.inc.  This function finds unresolved msgbox(LABEL, TYPE)
    patterns and inlines the actual text.
    """
    text_files = []
    trainers_inc = os.path.join(game_path, "data", "text", "trainers.inc")
    if os.path.isfile(trainers_inc):
        text_files.append(trainers_inc)
    scripts_inc = os.path.join(game_path, "data", "maps", map_name, "scripts.inc")
    if os.path.isfile(scripts_inc):
        text_files.append(scripts_inc)

    if not text_files:
        return pory_text

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
        tb_m = re.match(r'^(\s*)(trainerbattle_\w+)\((.+)\)$', line)
        if tb_m:
            indent, macro, tb_args = tb_m.group(1), tb_m.group(2), tb_m.group(3)
            parts = [p.strip() for p in tb_args.split(",")]
            new_parts = []
            for p in parts:
                if (re.match(r'^[A-Za-z_]\w*$', p)
                        and not p.startswith("TRAINER_")
                        and not p.startswith("TRUE")
                        and not p.startswith("FALSE")):
                    text = _try_resolve(p)
                    if text is not None:
                        new_parts.append(f'"{text}"')
                        continue
                new_parts.append(p)
            resolved.append(f'{indent}{macro}({", ".join(new_parts)})')
            continue

        m = re.match(r'^(\s*)msgbox\(([A-Za-z_]\w*),\s*(\w+)\)$', line)
        if m:
            indent, label, msg_type = m.group(1), m.group(2), m.group(3)
            text = _try_resolve(label)
            if text is not None:
                resolved.append(f'{indent}msgbox("{text}", {msg_type})')
                continue
        resolved.append(line)
    return "\n".join(resolved)


# ---------------------------------------------------------------------------
# .inc → TorScript fallback decompiler
# ---------------------------------------------------------------------------

def decompile_inc_to_torscript(content, script_label):
    """Convert a simple .inc assembly script to TorScript.

    Handles: msgbox LABEL, TYPE + end patterns.
    Returns (torscript_text, warnings) or (None, [error]).
    """
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

        msg_m = re.match(r'^msgbox\s+(\w+),\s*(MSGBOX_\w+)$', line)
        if msg_m:
            text_label = msg_m.group(1)
            msgbox_type = msg_m.group(2)
            text = _resolve_inc_text(content, text_label)
            if text:
                cmd = "msgnpc" if msgbox_type == "MSGBOX_NPC" else "msg"
                ts_lines.append(f'{cmd} "{text}"')
            else:
                warnings.append(f"Could not resolve text label: {text_label}")
                ts_lines.append(f"pory msgbox({text_label}, {msgbox_type})")
            continue

        tb_m = re.match(r'^trainerbattle_(\w+)\s+(.+)$', line)
        if tb_m:
            ts_lines.append(f"trainerbattle_{tb_m.group(1)} {tb_m.group(2)}")
            continue

        warnings.append(f"Unknown .inc command: {line}")
        ts_lines.append(f"pory {line}")

    if "release" in body_lines:
        ts_lines.append("release")
    ts_lines.append("end")

    return "\n".join(ts_lines), warnings


# ---------------------------------------------------------------------------
# Battle beat expansion
# ---------------------------------------------------------------------------

def expand_battle_beats(ts_text):
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

        m = re.match(
            r'^(trainerbattle_\w+)\s+(TRAINER_\w+),\s*"(.+?)",\s*"(.+?)"(.*)$',
            stripped)
        if m:
            macro = m.group(1)
            trainer = m.group(2)
            intro_text = m.group(3)
            defeated_text = m.group(4)
            remaining = m.group(5).strip()

            postbattle_text = None
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                msg_m = re.match(r'^msg\w*\s+"(.+)"$', lines[j].strip())
                if msg_m:
                    postbattle_text = msg_m.group(1)
                    j += 1

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


# ---------------------------------------------------------------------------
# Alias injection
# ---------------------------------------------------------------------------

def inject_aliases_from_localids(ts_text, inc_content, script_label, game_path, map_name):
    """Add alias directives for LOCALID references used in the script.

    Scans the original .inc for LOCALID_ references in the script body,
    resolves them to NPC indices via map.json local_id fields, and prepends
    alias lines to the TorScript output.
    """
    body_match = re.search(
        rf'^{re.escape(script_label)}::(.+?)(?=^\w+::|\Z)',
        inc_content, re.MULTILINE | re.DOTALL)
    if not body_match:
        return ts_text

    body = body_match.group(1)
    localids = set(re.findall(r'LOCALID_\w+', body))
    localids.discard("LOCALID_PLAYER")
    if not localids:
        return ts_text

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

    alias_block = "\n".join(sorted(alias_lines)) + "\n\n"

    m = re.match(r'^(script\s+)', ts_text)
    if m:
        return alias_block + ts_text
    return alias_block + ts_text


# ---------------------------------------------------------------------------
# Per-script decompilation to workspace
# ---------------------------------------------------------------------------

def decompile_script_to_workspace(game_path, map_name, script_label, project_dir,
                                  overwrite=False, header=""):
    """Decompile a single script to a workspace .txt file.

    Handles both .pory (via decompiler) and .inc (via inc_decompiler pipeline).
    When *overwrite* is True, always re-decompile even if a workspace file
    already exists (used for auto-refresh on preview access).
    When *header* is non-empty, prepend it to the file content.
    Returns (script_name, torscript_text, warnings) on success.
    Raises ValueError on failure.
    """
    filepath, file_type = find_script(game_path, map_name, script_label)
    if not filepath:
        raise ValueError(f"Script '{script_label}' not found in game files")

    with open(filepath, "r", encoding="utf-8") as f:
        file_content = f.read()

    if file_type == "pory":
        stype = classify_script(file_content, script_label)
    elif file_type == "inc":
        stype = classify_inc_script(file_content, script_label)
    else:
        raise ValueError(f"Unsupported script format: {file_type}")

    if stype in ("nurse", "pc"):
        raise ValueError(f"System script ({stype}) -- cannot be decompiled to workspace")
    if stype == "shared":
        raise ValueError("Shared/common script -- cannot be decompiled to workspace")

    # Decompile based on format
    if file_type == "pory":
        from torch.decompiler import decompile_block
        ts_text, warnings = decompile_block(file_content, script_label, map_name)
    else:
        # .inc -> .pory -> TorScript (full pipeline)
        try:
            from torch.inc_decompiler import decompile_inc_block
            from torch.decompiler import decompile
            pory_text, inc_warnings = decompile_inc_block(file_content, script_label, map_name)
            if pory_text:
                pory_text = resolve_external_text_labels(pory_text, game_path, map_name)
                ts_text, pory_warnings = decompile(pory_text, map_name)
                warnings = inc_warnings + pory_warnings
            else:
                ts_text = None
                warnings = inc_warnings
        except Exception:
            # Fallback to legacy pattern matcher
            ts_text, warnings = decompile_inc_to_torscript(file_content, script_label)

    if ts_text is None:
        raise ValueError(warnings[0] if warnings else "Decompilation failed")

    ts_text = expand_battle_beats(ts_text)

    ts_text = inject_aliases_from_localids(
        ts_text, file_content, script_label, game_path, map_name)

    # Determine output filename
    short_name = strip_script_prefix(script_label, map_name)
    ws_dir = os.path.join(project_dir, map_name)
    os.makedirs(ws_dir, exist_ok=True)

    out_path = os.path.join(ws_dir, f"{short_name}.txt")
    if not overwrite and os.path.exists(out_path):
        return short_name, ts_text, warnings

    # Write with warning header if applicable
    file_header = header
    if warnings:
        file_header += "".join(f"# WARNING: {w}\n" for w in warnings) + "\n"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(file_header + ts_text + "\n")

    return short_name, ts_text, warnings


# ---------------------------------------------------------------------------
# Mapscripts decompilation
# ---------------------------------------------------------------------------

def decompile_mapscripts(game_path, map_name, project_dir):
    """Extract mapscripts block from scripts.pory and write to setup.pory."""
    pory_path = os.path.join(game_path, "data", "maps", map_name, "scripts.pory")
    if not os.path.isfile(pory_path):
        return None

    try:
        with open(pory_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    m = re.search(r'mapscripts\s+(\w+)\s*\{', content)
    if not m:
        return None

    ws_dir = os.path.join(project_dir, map_name)
    setup_path = os.path.join(ws_dir, "setup.pory")

    if os.path.exists(setup_path):
        return "exists"

    os.makedirs(ws_dir, exist_ok=True)

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


# ---------------------------------------------------------------------------
# Per-map bulk decompile
# ---------------------------------------------------------------------------

def decompile_map_to_workspace(game_path, map_name, project_dir, pristine=False):
    """Decompile all scripts on a map to workspace .txt files.

    When pristine=True, prepends PRISTINE_HEADER to each generated file.
    Skips files that already exist (preserves user edits).
    Returns {"imported": [...], "skipped": [...], "warnings": [...], "mapscripts": result}
    """
    data = load_map_json(game_path, map_name)
    if not data:
        # Map exists but has no map.json — create empty workspace folder
        ws_dir = os.path.join(project_dir, map_name)
        os.makedirs(ws_dir, exist_ok=True)
        return {"imported": [], "skipped": [], "warnings": [], "mapscripts": None}

    # Ensure workspace folder exists even if map has no scripts
    ws_dir = os.path.join(project_dir, map_name)
    os.makedirs(ws_dir, exist_ok=True)

    header = PRISTINE_HEADER if pristine else ""

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
            script_name, _, warnings = decompile_script_to_workspace(
                game_path, map_name, lbl, project_dir, header=header,
            )
            imported.append(script_name)
            all_warnings.extend(warnings)
        except ValueError as e:
            skipped.append({"label": lbl, "reason": str(e)})

    ms_result = decompile_mapscripts(game_path, map_name, project_dir)

    return {
        "imported": imported,
        "skipped": skipped,
        "warnings": all_warnings,
        "mapscripts": ms_result,
    }


# ---------------------------------------------------------------------------
# Round-trip validation
# ---------------------------------------------------------------------------

def validate_round_trip(game_path, map_name, project_dir, emotes_conf):
    """Compile workspace .txt back to .pory and check for compilation errors.

    Returns (is_clean: bool, mismatches: list[str]) where mismatches lists
    filenames that failed to compile cleanly.
    """
    from torch.compiler import compile_script

    ws_dir = os.path.join(project_dir, map_name)
    if not os.path.isdir(ws_dir):
        return True, []

    mismatches = []
    for fname in sorted(os.listdir(ws_dir)):
        if not fname.endswith(".txt"):
            continue
        txt_path = os.path.join(ws_dir, fname)
        try:
            _, errors = compile_script(txt_path, map_name, emotes_conf)
            if errors:
                mismatches.append(fname)
        except Exception:
            mismatches.append(fname)

    return len(mismatches) == 0, mismatches


# ---------------------------------------------------------------------------
# Project-wide bulk decompile
# ---------------------------------------------------------------------------

def bulk_decompile_all_maps(game_path, project_dir, emotes_conf, progress_cb=None):
    """Decompile every game map into the workspace.

    For each map in data/maps/ with a map.json:
    1. If workspace already has user .txt files -> enroll as claimed, don't overwrite
    2. Otherwise -> decompile with pristine=True
    3. Validate round-trip -> auto-lock on mismatch
    4. Enroll in registry with appropriate state

    *progress_cb*, if provided, is called with (map_name, state, index, total).

    Returns {"pristine": N, "locked": M, "claimed": K, "skipped": S, "errors": [...]}.
    """
    from torch.registry import (
        load_registry, save_registry, mark_decompiled,
        STATE_PRISTINE, STATE_CLAIMED, STATE_LOCKED,
    )
    from torch.map_scanner import _SKIP_WORKSPACE_DIRS
    from datetime import datetime

    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return {"pristine": 0, "locked": 0, "claimed": 0, "skipped": 0, "errors": ["data/maps/ not found"]}

    # Discover all game maps (any directory under data/maps/)
    game_maps = sorted(
        d for d in os.listdir(maps_dir)
        if os.path.isdir(os.path.join(maps_dir, d))
    )

    registry = load_registry(project_dir)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    total = len(game_maps)
    counts = {"pristine": 0, "locked": 0, "claimed": 0, "skipped": 0}
    errors = []

    for idx, map_name in enumerate(game_maps):
        # Skip already-enrolled maps
        if map_name in registry["maps"]:
            counts["skipped"] += 1
            if progress_cb:
                progress_cb(map_name, "skipped", idx, total)
            continue

        ws_dir = os.path.join(project_dir, map_name)

        # Check if workspace already has user-authored .txt files
        # (files starting with PRISTINE_HEADER are auto-generated, not user-authored)
        has_user_files = False
        if os.path.isdir(ws_dir):
            for f in os.listdir(ws_dir):
                if not f.endswith(".txt"):
                    continue
                fpath = os.path.join(ws_dir, f)
                if not os.path.isfile(fpath):
                    continue
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        first_line = fh.readline()
                    if not first_line.startswith("# Auto-decompiled by TORCH"):
                        has_user_files = True
                        break
                except OSError:
                    pass

        if has_user_files:
            # User already created scripts here — enroll as claimed
            registry["maps"][map_name] = {
                "enrolled_at": now,
                "last_written": None,
                "state": STATE_CLAIMED,
                "decompiled_at": None,
                "lock_reason": None,
            }
            counts["claimed"] += 1
            if progress_cb:
                progress_cb(map_name, "claimed", idx, total)
            continue

        # Decompile as pristine
        try:
            decompile_map_to_workspace(game_path, map_name, project_dir, pristine=True)
        except Exception as e:
            errors.append(f"{map_name}: {e}")
            if progress_cb:
                progress_cb(map_name, "error", idx, total)
            continue

        # Validate round-trip
        is_clean, mismatches = validate_round_trip(
            game_path, map_name, project_dir, emotes_conf)

        if is_clean:
            state = STATE_PRISTINE
            lock_reason = None
            counts["pristine"] += 1
        else:
            state = STATE_LOCKED
            lock_reason = f"round-trip validation failed: {', '.join(mismatches)}"
            counts["locked"] += 1

        registry["maps"][map_name] = {
            "enrolled_at": now,
            "last_written": None,
            "state": state,
            "decompiled_at": now,
            "lock_reason": lock_reason,
        }

        if progress_cb:
            progress_cb(map_name, state, idx, total)

    save_registry(project_dir, registry)
    counts["errors"] = errors
    return counts


# ---------------------------------------------------------------------------
# Re-decompile pristine maps
# ---------------------------------------------------------------------------

def re_decompile_pristine(game_path, map_name, project_dir):
    """Re-decompile a pristine map whose game files changed.

    Overwrites workspace .txt files (they're views, not sources).
    Updates decompiled_at timestamp.
    """
    from torch.registry import mark_decompiled

    ws_dir = os.path.join(project_dir, map_name)

    # Remove existing .txt files (they are just generated views)
    if os.path.isdir(ws_dir):
        for fname in os.listdir(ws_dir):
            if fname.endswith(".txt"):
                try:
                    os.remove(os.path.join(ws_dir, fname))
                except OSError:
                    pass

    # Also remove setup.pory so it can be regenerated
    setup_path = os.path.join(ws_dir, "setup.pory")
    if os.path.exists(setup_path):
        try:
            os.remove(setup_path)
        except OSError:
            pass

    decompile_map_to_workspace(game_path, map_name, project_dir, pristine=True)
    mark_decompiled(project_dir, map_name)
