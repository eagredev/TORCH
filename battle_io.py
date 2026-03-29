"""Trainer I/O — .party + legacy .h reader/writer, format dispatch."""
# TORCH_MODULE: Trainer I/O
# TORCH_GROUP: Trainers
import os
import re
import glob as _glob

from torch.names import (
    _human_name_to_const, _const_to_human_name,
    _const_to_species_name, _const_to_move_name, _const_to_item_name,
    _const_to_ability_name, _const_to_nature_name, _const_to_ball_name,
    _ai_flags_to_party_format, _party_ai_to_const,
    _parse_stat_spread, _format_stat_spread, _format_stat_spread_full,
)


# ---------- Recovery helpers ----------

_META_DEFINES = {"TRAINERS_COUNT", "MAX_TRAINERS_COUNT", "TRAINER_PARTNER", "TRAINER_NONE"}


def _get_custom_trainer_consts(opponents_path, vanilla_threshold=854):
    """
    Read opponents.h and return list of (trainer_const, trainer_id) tuples
    where trainer_id > vanilla_threshold and const is not a meta-define.
    """
    results = []
    if not os.path.exists(opponents_path):
        return results
    with open(opponents_path) as f:
        for line in f:
            m = re.match(r"^#define\s+(TRAINER_\w+)\s+(\d+)", line)
            if not m:
                continue
            const = m.group(1)
            tid = int(m.group(2))
            if const in _META_DEFINES:
                continue
            if tid > vanilla_threshold:
                results.append((const, tid))
    return results


# All known trainerbattle macros and their parameter signatures.
# Maps macro name -> (is_double, param_names_after_trainer_const)
# The first param is always the trainer constant (used for matching).
_TRAINERBATTLE_MACROS = {
    "trainerbattle_single": (False, ["intro", "defeat"]),
    "trainerbattle_double": (True, ["intro", "defeat", "not_enough"]),
    "trainerbattle_rematch": (False, ["intro", "defeat"]),
    "trainerbattle_rematch_double": (True, ["intro", "defeat", "not_enough"]),
    "trainerbattle_no_intro": (False, ["defeat"]),
    "trainerbattle_two_trainers": (False, ["defeat_a", "trainer_b", "defeat_b"]),
}

# Reverse map: macro name -> type_name (matches battle_manager.BATTLE_TYPES)
_MACRO_TO_TYPE_NAME = {
    "trainerbattle_single": "single",
    "trainerbattle_double": "double",
    "trainerbattle_rematch": "rematch",
    "trainerbattle_rematch_double": "rematch_double",
    "trainerbattle_no_intro": "single_no_intro",
    "trainerbattle_two_trainers": "two_trainers",
}


def _build_trainerbattle_patterns(trainer_const):
    """Build regex patterns for all trainerbattle macros referencing a trainer const.
    Returns list of (macro_name, pory_regex, inc_regex) tuples."""
    patterns = []
    tc_escaped = re.escape(trainer_const)
    for macro, (is_double, params) in _TRAINERBATTLE_MACROS.items():
        # .pory format: macro(TRAINER_CONST, param1, param2, ...)
        pory_args = r"\s*,\s*".join([r"(\w+)"] * len(params))
        pory_pat = re.compile(
            re.escape(macro) + r"\s*\(\s*" + tc_escaped +
            (r"\s*,\s*" + pory_args if params else "") +
            r"(?:\s*,\s*\w+)*\s*\)"  # allow optional trailing params
        )
        # .inc format: macro TRAINER_CONST, param1, param2, ...
        inc_args = r"\s*,\s*".join([r"(\w+)"] * len(params))
        inc_pat = re.compile(
            re.escape(macro) + r"\s+" + tc_escaped +
            (r"\s*,\s*" + inc_args if params else "")
        )
        patterns.append((macro, pory_pat, inc_pat))
    return patterns


def _extract_ref_from_match(macro, m, map_folder, fpath):
    """Build a map-ref dict from a regex match for a trainerbattle macro."""
    is_double, params = _TRAINERBATTLE_MACROS[macro]
    ref = {
        "map_folder": map_folder,
        "script_path": fpath,
        "is_double": is_double,
        "battle_type": _MACRO_TO_TYPE_NAME.get(macro, "single"),
        "intro_label": None,
        "defeat_label": None,
        "not_enough_label": None,
        "after_label": None,
    }
    for i, pname in enumerate(params):
        val = m.group(i + 1) if (i + 1) <= len(m.groups()) else None
        if "intro" in pname:
            ref["intro_label"] = val
        elif pname == "defeat" or pname == "defeat_a":
            ref["defeat_label"] = val
        elif "not_enough" in pname:
            ref["not_enough_label"] = val
    return ref


def _find_trainer_map_refs(trainer_const, maps_dir):
    """
    Search all scripts.pory and scripts.inc files under maps_dir for trainerbattle
    lines referencing trainer_const.
    Returns list of dicts with map_folder, script_path, is_double, battle_type,
    and label fields.
    """
    refs = []
    pory_files = _glob.glob(os.path.join(maps_dir, "**", "scripts.pory"), recursive=True)
    inc_files  = _glob.glob(os.path.join(maps_dir, "**", "scripts.inc"),  recursive=True)
    patterns = _build_trainerbattle_patterns(trainer_const)

    for fpath in pory_files:
        with open(fpath) as f:
            content = f.read()
        map_folder = os.path.basename(os.path.dirname(fpath))
        for macro, pory_pat, _ in patterns:
            m = pory_pat.search(content)
            if m:
                refs.append(_extract_ref_from_match(macro, m, map_folder, fpath))
                break  # one match per file is enough

    for fpath in inc_files:
        with open(fpath) as f:
            content = f.read()
        map_folder = os.path.basename(os.path.dirname(fpath))
        for macro, _, inc_pat in patterns:
            m = inc_pat.search(content)
            if m:
                refs.append(_extract_ref_from_match(macro, m, map_folder, fpath))
                break

    # Deduplicate: if the same map_folder appears in both .pory and .inc,
    # keep the .pory entry (it's the authoritative source for text extraction).
    seen = {}
    deduped = []
    for r in refs:
        mf = r["map_folder"]
        if mf not in seen:
            seen[mf] = r
            deduped.append(r)
        else:
            # Prefer .pory over .inc
            if r["script_path"].endswith(".pory"):
                # Replace existing entry with this .pory one
                idx = deduped.index(seen[mf])
                deduped[idx] = r
                seen[mf] = r
    return deduped


def _extract_text_label(script_path, label):
    """
    Try to read the string content of a text label from a .pory or .inc script file.
    Returns the text string, or None if not found.
    """
    if not os.path.exists(script_path):
        return None
    with open(script_path) as f:
        content = f.read()
    if script_path.endswith(".pory"):
        m = re.search(
            r"text\s+" + re.escape(label) + r'\s*\{\s*"([^"]*)"\s*\}',
            content, re.DOTALL
        )
        return m.group(1) if m else None
    else:
        m = re.search(
            re.escape(label) + r"::\s*\n\s*\.string\s*\"([^\"]*)\"",
            content
        )
        return m.group(1) if m else None


def _build_recovery_stub(trainer_const, ref):
    """
    Build the .pory stub content string for a recovered trainer.
    ref is a map-ref dict or None (orphan trainer).
    """
    if ref is None:
        intro_label    = f"{trainer_const}_Intro"
        defeat_label   = f"{trainer_const}_Defeat"
        not_enough_label = None
        script_path    = None
        map_folder     = "_unassigned"
        source_comment = "// No map reference found — placed in _unassigned/."
    else:
        intro_label      = ref["intro_label"]
        defeat_label     = ref["defeat_label"]
        not_enough_label = ref.get("not_enough_label")
        script_path      = ref["script_path"]
        map_folder       = ref["map_folder"]
        rel_path         = os.path.join("data", "maps", map_folder,
                                        os.path.basename(script_path))
        source_comment   = (
            "// Recovered by TORCH Trainers from game files.\n"
            f"// Original battle text sourced from: {rel_path}\n"
            "// Edit this file to update dialogue, then run: torch sync " + map_folder
        )

    def _get_text(label):
        if script_path:
            t = _extract_text_label(script_path, label)
            if t:
                return t
        return "..."

    intro_text   = _get_text(intro_label)
    defeat_text  = _get_text(defeat_label)

    lines = [source_comment, ""]
    lines.append(f'text {intro_label} {{')
    lines.append(f'    "{intro_text}$"')
    lines.append('}')
    lines.append('')
    lines.append(f'text {defeat_label} {{')
    lines.append(f'    "{defeat_text}$"')
    lines.append('}')

    if not_enough_label:
        not_enough_text = _get_text(not_enough_label)
        lines.append('')
        lines.append(f'text {not_enough_label} {{')
        lines.append(f'    "{not_enough_text}$"')
        lines.append('}')

    lines.append('')
    return "\n".join(lines)


def _ensure_map_workspace(project_dir, map_folder, game_path):
    """
    Create workspace folder + setup.pory (if absent) + backups dirs.
    Returns the map folder path.
    Skips setup.pory creation for _unassigned/ folder.
    """
    map_dir = os.path.join(project_dir, map_folder)
    os.makedirs(map_dir, exist_ok=True)

    if map_folder != "_unassigned":
        setup_path = os.path.join(map_dir, "setup.pory")
        if not os.path.exists(setup_path):
            game_map_dir = os.path.join(game_path, "data", "maps", map_folder)
            inc_path = os.path.join(game_map_dir, "scripts.inc")
            has_legacy = os.path.exists(inc_path) and os.path.getsize(inc_path) > 0
            with open(setup_path, "w") as f:
                f.write(f"// {map_folder} -- mapscripts, shared text & movement data\n")
                if has_legacy:
                    f.write("// mapscripts provided by legacy.pory\n")
                else:
                    f.write(f"\nmapscripts {map_folder}_MapScripts {{}}\n")
            if has_legacy:
                print(f"    Created: {map_folder}/setup.pory  (mapscripts in legacy.pory)")
            else:
                print(f"    Created: {map_folder}/setup.pory")

    snapshots_dir = os.path.join(map_dir, "backups", "snapshots")
    os.makedirs(snapshots_dir, exist_ok=True)
    return map_dir


def _recovery_scan(project_dir, game_path, workspace_expanded):
    """
    Top-level recovery runner. Finds custom trainers with no workspace stub,
    locates their map references, and creates stub files.
    """
    opponents_path = os.path.join(game_path, "include", "constants", "opponents.h")
    maps_dir       = os.path.join(game_path, "data", "maps")

    print()
    print("  Scanning for unmanaged custom trainers...")
    print()

    # 1. All custom trainer consts from opponents.h
    all_custom = _get_custom_trainer_consts(opponents_path)
    if not all_custom:
        print("  No custom trainers found in opponents.h  (ID > 854).")
        print()
        return

    # 2. Already-managed (have a workspace stub)
    managed = _scan_custom_battles(project_dir)
    managed_consts = {b["trainer_const"] for b in managed}

    # 3. Unrecovered = custom - managed
    unrecovered = [(c, tid) for c, tid in all_custom if c not in managed_consts]
    if not unrecovered:
        print("  All custom battles are already managed.")
        print()
        return

    print(f"  Found {len(unrecovered)} unmanaged trainer(s):")
    print()

    # 4. Resolve map refs for each
    plan = []  # list of (trainer_const, trainer_id, ref_or_None)
    for trainer_const, trainer_id in unrecovered:
        refs = _find_trainer_map_refs(trainer_const, maps_dir)
        if not refs:
            plan.append((trainer_const, trainer_id, None))
        elif len(refs) == 1:
            plan.append((trainer_const, trainer_id, refs[0]))
        else:
            # Genuinely multiple different maps — ask user to pick one
            print(f"  {trainer_const} appears in multiple maps:")
            for i, r in enumerate(refs, 1):
                print(f"    [{i}] {r['map_folder']}  ({os.path.basename(r['script_path'])})")
            print(f"    [{len(refs)+1}] _unassigned/  (skip for now)")
            print()
            while True:
                raw = input(f"  Which map should own {trainer_const}? > ").strip()
                try:
                    pick = int(raw)
                    if 1 <= pick <= len(refs):
                        plan.append((trainer_const, trainer_id, refs[pick - 1]))
                        break
                    elif pick == len(refs) + 1:
                        plan.append((trainer_const, trainer_id, None))
                        break
                except ValueError:
                    pass
                print("  Please enter a valid number.")

    # 5. Print full plan
    print()
    print("  Will create the following files:")
    print()
    for trainer_const, trainer_id, ref in plan:
        map_folder = ref["map_folder"] if ref else "_unassigned"
        stub_name  = f"battle_{trainer_const}.pory"
        print(f"    {map_folder}/{stub_name}  (ID: {trainer_id})")
        if ref:
            rel = os.path.join("data", "maps", map_folder, os.path.basename(ref["script_path"]))
            print(f"      text sourced from: {rel}")
        else:
            print(f"      no map reference found — placeholder dialogue")
    print()

    # 6. Confirmation
    answer = input(f"  Recover these {len(plan)} battle(s)? [Y/n] > ").strip().lower()
    if answer == "n":
        print()
        print("  Recovery cancelled.")
        print()
        return

    # 7. Execute
    print()
    for trainer_const, trainer_id, ref in plan:
        map_folder = ref["map_folder"] if ref else "_unassigned"
        _ensure_map_workspace(project_dir, map_folder, game_path)
        stub_content = _build_recovery_stub(trainer_const, ref)
        stub_path = os.path.join(project_dir, map_folder, f"battle_{trainer_const}.pory")
        with open(stub_path, "w") as f:
            f.write(stub_content)
        print(f"    Written: {map_folder}/battle_{trainer_const}.pory")

    print()
    print(f"  Recovery complete. {len(plan)} stub(s) created.")
    print()


def _scan_custom_battles(project_dir):
    """
    Find all battle_TRAINER_*.pory files anywhere in workspace subfolders.
    Returns list of dicts: {trainer_const, map_folder, pory_path, mtime}
    sorted by mtime descending (newest first).
    """
    pattern = os.path.join(project_dir, "**", "battle_TRAINER_*.pory")
    found = []
    for path in _glob.glob(pattern, recursive=True):
        basename = os.path.basename(path)
        # e.g. battle_TRAINER_ROCKET_BUSTER_1.pory -> TRAINER_ROCKET_BUSTER_1
        trainer_const = basename[len("battle_"):-len(".pory")]
        map_folder = os.path.basename(os.path.dirname(path))
        mtime = os.path.getmtime(path)
        found.append({
            "trainer_const": trainer_const,
            "map_folder": map_folder,
            "pory_path": path,
            "mtime": mtime,
        })
    found.sort(key=lambda x: x["mtime"], reverse=True)
    return found


# ============================================================
# BATTLE MANAGER — TRAINER LIST / HEADER-ONLY PARSER
# ============================================================

def _parse_party_header_only(section_text):
    """Fast header-only parser — extracts Name and Class from a trainers.party section.
    Returns (name, class_const) tuple."""
    name = None
    class_const = None
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("==="):
            continue
        if ":" not in stripped:
            if name is not None or class_const is not None:
                break  # Hit pokemon section
            continue
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()
        if key == "Name":
            name = val if val else None
        elif key == "Class":
            class_const = _human_name_to_const(val, "TRAINER_CLASS_") if val else None
            break  # Got both, done
    return name, class_const


def _load_all_trainers(opponents_path, party_path, battles=None):
    """Bulk-load all trainers from opponents.h + trainers.party.
    Returns a list of summary dicts sorted by trainer ID:
    [{trainer_const, trainer_id, trainer_name, trainer_class, is_vanilla, is_custom,
      map_folder, pory_path}, ...]
    """
    # Build ID map from opponents.h
    id_map = {}  # const -> id
    if os.path.exists(opponents_path):
        with open(opponents_path) as f:
            for line in f:
                m = re.match(r"^#define\s+(TRAINER_\w+)\s+(\d+)", line)
                if m:
                    cname = m.group(1)
                    if cname not in ("TRAINERS_COUNT", "TRAINER_PARTNER"):
                        id_map[cname] = int(m.group(2))

    # Build workspace lookup from battles list
    workspace_map = {}  # const -> {map_folder, pory_path}
    if battles:
        for b in battles:
            workspace_map[b["trainer_const"]] = {
                "map_folder": b["map_folder"],
                "pory_path": b["pory_path"],
            }

    # Read all party sections (header-only for speed)
    party_headers = {}  # const -> (name, class_const)
    if os.path.exists(party_path):
        sections = _read_party_file(party_path)
        for tc, section_text in sections.items():
            party_headers[tc] = _parse_party_header_only(section_text)

    # Merge into unified list
    all_consts = set(id_map.keys()) | set(party_headers.keys())
    result = []
    for tc in all_consts:
        tid = id_map.get(tc)
        if tid is None or tid == 0:
            continue  # Skip TRAINER_NONE (id 0) and unresolved
        name, class_const = party_headers.get(tc, (None, None))
        ws = workspace_map.get(tc)
        is_custom = tc in workspace_map
        # Vanilla = has an ID and is NOT in workspace
        is_vanilla = not is_custom
        result.append({
            "trainer_const": tc,
            "trainer_id": tid,
            "trainer_name": name,
            "trainer_class": class_const,
            "is_vanilla": is_vanilla,
            "is_custom": is_custom,
            "map_folder": ws["map_folder"] if ws else None,
            "pory_path": ws["pory_path"] if ws else None,
        })

    result.sort(key=lambda x: x["trainer_id"])
    return result


# ============================================================
# BATTLE MANAGER — LEGACY .h FORMAT READER
# ============================================================

def _read_trainer_record(trainer_const, opponents_path, trainers_h_path, trainer_parties_path):
    """
    Parse trainer card data from the three game files.
    Returns a dict with all fields, or None if not found.
    """
    # --- ID from opponents.h ---
    trainer_id = None
    if os.path.exists(opponents_path):
        with open(opponents_path) as f:
            for line in f:
                m = re.match(r"^#define\s+" + re.escape(trainer_const) + r"\s+(\d+)", line)
                if m:
                    trainer_id = int(m.group(1))
                    break

    # --- trainers.h block ---
    trainer_class = None
    encounter_music = None
    trainer_pic = None
    trainer_name = None
    is_double = False
    ai_flags = None
    party_const = None

    if os.path.exists(trainers_h_path):
        with open(trainers_h_path) as f:
            content = f.read()
        # Match the [TRAINER_CONST] = \n    { ... }, block
        pattern = (
            r"\[" + re.escape(trainer_const) + r"\]\s*=\s*\n\s*\{"
            r"(.*?)"
            r"\n\s*\},"
        )
        m = re.search(pattern, content, re.DOTALL)
        if m:
            block = m.group(1)
            def _field(key):
                fm = re.search(r"\." + re.escape(key) + r"\s*=\s*([^,\n]+)", block)
                return fm.group(1).strip() if fm else None

            trainer_class = _field("trainerClass")
            encounter_music = _field("encounterMusic_gender")
            trainer_pic = _field("trainerPic")
            # trainerName = _("NAME") -> extract NAME
            nm = re.search(r'\.trainerName\s*=\s*_\("([^"]*)"\)', block)
            trainer_name = nm.group(1) if nm else None
            db = _field("doubleBattle")
            is_double = (db == "TRUE") if db else False
            ai_flags = _field("aiFlags")
            # party = TRAINER_PARTY(CONST)
            pm = re.search(r'\.party\s*=\s*TRAINER_PARTY\((\w+)\)', block)
            party_const = pm.group(1) if pm else None

    # --- trainer_parties.h ---
    mons = []
    if party_const and os.path.exists(trainer_parties_path):
        with open(trainer_parties_path) as f:
            party_content = f.read()
        pp = (
            r"static\s+const\s+struct\s+TrainerMon\s+" + re.escape(party_const)
            + r"\[\]\s*=\s*\{(.*?)\};"
        )
        pm2 = re.search(pp, party_content, re.DOTALL)
        if pm2:
            block2 = pm2.group(1)
            # Each mon is a { ... } sub-block (may contain nested {moves})
            for mon_m in re.finditer(r"\{((?:[^{}]|\{[^}]*\})+)\}", block2, re.DOTALL):
                mon_block = mon_m.group(1)
                def _mf(key):
                    fm = re.search(r"\." + re.escape(key) + r"\s*=\s*([^,\n]+)", mon_block)
                    return fm.group(1).strip() if fm else None
                species = _mf("species")
                lvl = _mf("lvl")
                held_item = _mf("heldItem")
                ability = _mf("ability")
                # moves: .moves = {MOVE_A, MOVE_B}
                moves_m = re.search(r'\.moves\s*=\s*\{([^}]+)\}', mon_block)
                moves = [x.strip() for x in moves_m.group(1).split(",") if x.strip()] if moves_m else None
                # Extended fields: IVs, EVs, nature
                ivs = None
                iv_m = re.search(r'\.iv\s*=\s*TRAINER_PARTY_IVS\(([^)]+)\)', mon_block)
                if iv_m:
                    try:
                        iv_vals = [int(x.strip()) for x in iv_m.group(1).split(",")]
                        if len(iv_vals) == 6:
                            ivs = {"hp": iv_vals[0], "atk": iv_vals[1], "def": iv_vals[2],
                                   "spe": iv_vals[3], "spatk": iv_vals[4], "spdef": iv_vals[5]}
                    except ValueError:
                        pass
                evs = None
                ev_m = re.search(r'\.ev\s*=\s*TRAINER_PARTY_EVS\(([^)]+)\)', mon_block)
                if ev_m:
                    try:
                        ev_vals = [int(x.strip()) for x in ev_m.group(1).split(",")]
                        if len(ev_vals) == 6:
                            evs = {"hp": ev_vals[0], "atk": ev_vals[1], "def": ev_vals[2],
                                   "spe": ev_vals[3], "spatk": ev_vals[4], "spdef": ev_vals[5]}
                    except ValueError:
                        pass
                nature = None
                nat_m = re.search(r'\.nature\s*=\s*TRAINER_PARTY_NATURE\((\w+)\)', mon_block)
                if nat_m:
                    nature = nat_m.group(1)
                if species:
                    mons.append({
                        "species": species,
                        "level": lvl or "?",
                        "held_item": held_item,
                        "moves": moves,
                        "ability": ability,
                        "ivs": ivs,
                        "evs": evs,
                        "nature": nature,
                    })

    return {
        "trainer_const": trainer_const,
        "trainer_id": trainer_id,
        "trainer_class": trainer_class,
        "encounter_music": encounter_music,
        "trainer_pic": trainer_pic,
        "trainer_name": trainer_name,
        "is_double": is_double,
        "ai_flags": ai_flags,
        "party_const": party_const,
        "mons": mons,
    }


# ============================================================
# BATTLE MANAGER — .party FORMAT READER
# ============================================================

def _read_party_file(party_path):
    """Read entire trainers.party, split on === HEADER ===, return {TRAINER_CONST: raw_text}."""
    sections, _ = _read_party_file_full(party_path)
    return sections


def _read_party_file_full(party_path):
    """Read entire trainers.party, return ({TRAINER_CONST: raw_text}, preamble_str).

    The preamble is everything before the first === HEADER === line.
    Returns ({}, "") on missing/unreadable files.
    """
    if not os.path.exists(party_path):
        return {}, ""
    try:
        with open(party_path) as f:
            content = f.read()
    except OSError as e:
        print(f"  ERROR: Could not read trainers.party: {e}")
        return {}, ""
    sections = {}
    parts = re.split(r"^(=== \S+ ===)\s*$", content, flags=re.MULTILINE)
    # parts[0] = preamble, then alternating header/body
    preamble = parts[0] if parts else ""
    i = 1
    while i < len(parts) - 1:
        header = parts[i].strip()
        body = parts[i + 1]
        # Extract trainer const from === TRAINER_CONST ===
        m = re.match(r"=== (\S+) ===", header)
        if m:
            sections[m.group(1)] = body
        i += 2
    return sections, preamble


# Map .party header keys to (hdr_field, converter) pairs.
# converter: None = store val as-is (or None if empty), callable = apply to non-empty val.
_HEADER_FIELD_MAP = {
    "Name":            ("trainer_name",    None),
    "Class":           ("trainer_class",   lambda v: _human_name_to_const(v, "TRAINER_CLASS_")),
    "Pic":             ("trainer_pic",     lambda v: _human_name_to_const(v, "TRAINER_PIC_")),
    "Music":           ("encounter_music", lambda v: _human_name_to_const(v, "TRAINER_ENCOUNTER_MUSIC_")),
    "Gender":          ("trainer_gender",  None),
    "Mugshot":         ("mugshot",         None),
    "Back Pic":        ("back_pic",        None),
    "Starting Status": ("starting_status", None),
}


def _parse_header_field(key, val, hdr):
    """Parse one trainer header key/value pair into the hdr dict.

    Known fields are stored by their canonical key; unknown fields are
    appended to hdr["header_extra"] for round-trip preservation.
    """
    simple = _HEADER_FIELD_MAP.get(key)
    if simple:
        field, converter = simple
        if val and converter:
            hdr[field] = converter(val)
        else:
            hdr[field] = val if val else None
    elif key == "Double Battle" or key == "Battle Type":
        hdr["is_double"] = val.lower() in ("yes", "true", "double", "doubles")
    elif key == "AI":
        hdr["ai_flags"] = _party_ai_to_const(val) if val else None
    elif key == "Items":
        items_raw = [it.strip() for it in val.split("/") if it.strip()]
        hdr["trainer_items"] = [_human_name_to_const(it, "ITEM_") for it in items_raw] if items_raw else None
    else:
        hdr["header_extra"].append((key, val))


def _find_header_end(lines):
    """Find the line index where the trainer header ends.

    Returns the index of the first blank line (or non-field line) after
    at least one header field has been seen, or 0 if no boundary found.
    """
    seen_field = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if seen_field:
                return idx
            continue
        if ":" in stripped or stripped.startswith("==="):
            seen_field = True
        elif seen_field:
            return idx
    return 0


def _parse_party_section(section_text, trainer_const):
    """Parse one trainer section from trainers.party into a record dict.
    Returns a dict matching the format of _read_trainer_record().
    """
    lines = section_text.splitlines()

    hdr = {
        "trainer_name": None, "trainer_class": None, "trainer_pic": None,
        "encounter_music": None, "is_double": False, "ai_flags": None,
        "trainer_gender": None, "mugshot": None, "trainer_items": None,
        "back_pic": None, "starting_status": None,
        "header_extra": [],
    }

    header_end = _find_header_end(lines)

    # Parse header fields
    for line in lines[:header_end if header_end else len(lines)]:
        stripped = line.strip()
        if not stripped or stripped.startswith("==="):
            continue
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        _parse_header_field(key.strip(), val.strip(), hdr)

    # Handle encounter_music with gender flag
    gender = hdr.pop("trainer_gender", None)
    if gender and gender.lower() in ("f", "female") and hdr["encounter_music"]:
        hdr["encounter_music"] = f"F_TRAINER_FEMALE | {hdr['encounter_music']}"

    # Parse Pokemon section (everything after header)
    mons = []
    if header_end > 0:
        mon_text = "\n".join(lines[header_end:])
        mon_blocks = re.split(r"\n\s*\n", mon_text.strip())
        for mb in mon_blocks:
            mb_lines = [l.strip() for l in mb.strip().splitlines() if l.strip()]
            if not mb_lines:
                continue
            mon = _parse_party_mon_block(mb_lines)
            if mon:
                mons.append(mon)

    return {
        "trainer_const": trainer_const,
        "trainer_id": None,
        "trainer_class": hdr["trainer_class"],
        "encounter_music": hdr["encounter_music"],
        "trainer_pic": hdr["trainer_pic"],
        "trainer_name": hdr["trainer_name"],
        "is_double": hdr["is_double"],
        "ai_flags": hdr["ai_flags"],
        "party_const": None,
        "mons": mons,
        "trainer_items": hdr["trainer_items"],
        "mugshot": hdr["mugshot"],
        "back_pic": hdr["back_pic"],
        "starting_status": hdr["starting_status"],
        "header_extra": hdr["header_extra"],
    }


def _parse_party_mon_block(lines):
    """Parse a single Pokemon block from .party format.
    First line: [Nickname] Species [(Gender)] [@ Item]
    Remaining: attribute lines and - Move lines.
    """
    if not lines:
        return None

    first = lines[0]
    species = None
    held_item = None
    nickname = None
    mon_gender = None

    # Parse first line: Species [@Item], or Nickname (Species) [@Item]
    item_part = None
    if " @ " in first:
        name_part, item_part = first.rsplit(" @ ", 1)
    else:
        name_part = first

    # Check for gender suffix (M) or (F)
    gender_m = re.search(r"\s*\(([MF])\)\s*$", name_part)
    if gender_m:
        mon_gender = "male" if gender_m.group(1) == "M" else "female"
        name_part = name_part[:gender_m.start()].strip()

    # Check for nickname — if there are parens with species name inside
    paren_m = re.search(r"^(.+?)\s*\(([^)]+)\)$", name_part)
    if paren_m:
        nickname = paren_m.group(1).strip()
        species_raw = paren_m.group(2).strip()
    else:
        species_raw = name_part.strip()

    # Convert species name to constant
    species = _human_name_to_const(species_raw, "SPECIES_")

    # Convert held item
    if item_part:
        held_item = _human_name_to_const(item_part.strip(), "ITEM_")

    mon = {
        "species": species,
        "level": "?",
        "held_item": held_item,
        "moves": [],
        "ability": None,
        "ivs": None,
        "evs": None,
        "nature": None,
        "gender": mon_gender,
        "shiny": None,
        "ball": None,
        "nickname": nickname,
        "happiness": None,
        "tera_type": None,
        "dynamax_level": None,
        "gigantamax": None,
        "extra_fields": [],  # [(key, value), ...] for unrecognized fields
    }

    # Parse remaining lines
    for line in lines[1:]:
        _parse_mon_field(line, mon)

    return mon


def _parse_mon_field(line, mon):
    """Parse one attribute line from a .party mon block into the mon dict.

    Handles moves (- prefix), known Key: Value fields, the standalone
    'Nature' suffix format, and unknown fields (preserved in extra_fields).
    """
    if line.startswith("- "):
        move_name = line[2:].strip()
        mon["moves"].append(_human_name_to_const(move_name, "MOVE_"))
    elif line.startswith("Level:"):
        try:
            mon["level"] = int(line.split(":", 1)[1].strip())
        except ValueError:
            pass
    elif line.startswith("Ability:"):
        ab_name = line.split(":", 1)[1].strip()
        mon["ability"] = _human_name_to_const(ab_name, "ABILITY_")
    elif line.startswith("IVs:"):
        mon["ivs"] = _parse_stat_spread(line.split(":", 1)[1].strip())
    elif line.startswith("EVs:"):
        mon["evs"] = _parse_stat_spread(line.split(":", 1)[1].strip())
    elif line.startswith("Nature:"):
        nat = line.split(":", 1)[1].strip()
        mon["nature"] = "NATURE_" + nat.upper()
    elif line.endswith(" Nature"):
        nat = line.replace(" Nature", "").strip()
        mon["nature"] = "NATURE_" + nat.upper()
    elif line.startswith("Shiny:"):
        mon["shiny"] = line.split(":", 1)[1].strip().lower() in ("yes", "true")
    elif line.startswith("Ball:"):
        ball_name = line.split(":", 1)[1].strip()
        # v1.15+ uses Pokeball enum (e.g. "Ultra" -> BALL_ULTRA)
        # Pre-1.15 uses Item enum (e.g. "Ultra Ball" -> ITEM_ULTRA_BALL)
        # Auto-detect: if name ends with " Ball", it's the old Item format
        if ball_name.lower().endswith(" ball") or ball_name.lower() == "poke ball":
            mon["ball"] = _human_name_to_const(ball_name, "ITEM_")
        else:
            mon["ball"] = _human_name_to_const(ball_name, "BALL_")
    elif line.startswith("Happiness:"):
        try:
            mon["happiness"] = int(line.split(":", 1)[1].strip())
        except ValueError:
            pass
    elif line.startswith("Tera Type:"):
        mon["tera_type"] = line.split(":", 1)[1].strip() or None
    elif line.startswith("Dynamax Level:"):
        try:
            mon["dynamax_level"] = int(line.split(":", 1)[1].strip())
        except ValueError:
            pass
    elif line.startswith("Gigantamax:"):
        val = line.split(":", 1)[1].strip().lower()
        mon["gigantamax"] = val in ("yes", "true")
    elif ":" in line:
        key, _, val = line.partition(":")
        mon["extra_fields"].append((key.strip(), val.strip()))


def _read_trainer_record_party(trainer_const, party_path, opponents_path):
    """Read one trainer from trainers.party + opponents.h.
    Returns a record dict matching the format of _read_trainer_record().
    """
    sections = _read_party_file(party_path)
    if trainer_const not in sections:
        return None

    record = _parse_party_section(sections[trainer_const], trainer_const)

    # Get ID from opponents.h
    if os.path.exists(opponents_path):
        with open(opponents_path) as f:
            for line in f:
                m = re.match(r"^#define\s+" + re.escape(trainer_const) + r"\s+(\d+)", line)
                if m:
                    record["trainer_id"] = int(m.group(1))
                    break

    return record


# ============================================================
# BATTLE MANAGER — .party FORMAT WRITER
# ============================================================

def _serialize_party_mon(mon, use_pokeball_enum=False):
    """Convert a mon dict to .party format lines."""
    lines = []
    # Species line: [Nickname] Species [(Gender)] [@ Item]
    species_name = _const_to_species_name(mon["species"])
    first = ""
    if mon.get("nickname"):
        first = f"{mon['nickname']} ({species_name})"
    else:
        first = species_name
    if mon.get("gender"):
        g = mon["gender"].lower()
        if g in ("male", "m"):
            first += " (M)"
        elif g in ("female", "f"):
            first += " (F)"
    if mon.get("held_item"):
        first += f" @ {_const_to_item_name(mon['held_item'])}"
    lines.append(first)

    # Level
    lines.append(f"Level: {mon.get('level', '?')}")
    # Ability
    if mon.get("ability"):
        lines.append(f"Ability: {_const_to_ability_name(mon['ability'])}")
    # IVs
    if mon.get("ivs"):
        lines.append(f"IVs: {_format_stat_spread_full(mon['ivs'], 31)}")
    # EVs
    if mon.get("evs"):
        lines.append(f"EVs: {_format_stat_spread(mon['evs'])}")
    # Nature
    if mon.get("nature"):
        lines.append(f"{_const_to_nature_name(mon['nature'])} Nature")
    # Shiny
    if mon.get("shiny"):
        lines.append("Shiny: Yes")
    # Ball — auto-detect format from constant prefix if not explicitly set
    if mon.get("ball"):
        ball_is_pokeball = use_pokeball_enum or mon["ball"].startswith("BALL_")
        lines.append(f"Ball: {_const_to_ball_name(mon['ball'], ball_is_pokeball)}")
    # Happiness
    if mon.get("happiness") is not None:
        lines.append(f"Happiness: {mon['happiness']}")
    # Tera Type
    if mon.get("tera_type"):
        lines.append(f"Tera Type: {mon['tera_type']}")
    # Dynamax Level
    if mon.get("dynamax_level") is not None:
        lines.append(f"Dynamax Level: {mon['dynamax_level']}")
    # Gigantamax
    if mon.get("gigantamax"):
        lines.append("Gigantamax: Yes")
    # Unknown preserved fields
    for key, val in mon.get("extra_fields", []):
        lines.append(f"{key}: {val}")
    # Moves (always last per .party spec)
    if mon.get("moves"):
        for mv in mon["moves"]:
            lines.append(f"- {_const_to_move_name(mv)}")

    return lines


def _serialize_party_trainer(record, use_pokeball_enum=False, expansion_version=None):
    """Convert a record dict to a full .party format text block."""
    lines = []
    tc = record["trainer_const"]
    lines.append(f"=== {tc} ===")

    # Header fields
    name = record.get('trainer_name') or ''
    lines.append(f"Name: {name}" if name else "Name:")
    if record.get("trainer_class"):
        lines.append(f"Class: {_const_to_human_name(record['trainer_class'], 'TRAINER_CLASS_')}")
    if record.get("trainer_pic"):
        lines.append(f"Pic: {_const_to_human_name(record['trainer_pic'], 'TRAINER_PIC_')}")

    # Gender — extract from encounter_music if it has F_TRAINER_FEMALE
    enc_music = record.get("encounter_music") or ""
    if "F_TRAINER_FEMALE" in enc_music:
        lines.append("Gender: Female")
        # Strip the gender flag from music
        music_val = enc_music.replace("F_TRAINER_FEMALE", "").replace("|", "").strip()
        if music_val:
            lines.append(f"Music: {_const_to_human_name(music_val, 'TRAINER_ENCOUNTER_MUSIC_')}")
    else:
        lines.append("Gender: Male")
        if enc_music:
            lines.append(f"Music: {_const_to_human_name(enc_music, 'TRAINER_ENCOUNTER_MUSIC_')}")

    # Back Pic (after Music, before Items/Battle Type per .party spec)
    if record.get("back_pic"):
        lines.append(f"Back Pic: {record['back_pic']}")
        if expansion_version is not None:
            from torch.expansion_compat import requires_version, version_str as _vs, TRAINER_BACK_PIC
            if not requires_version(expansion_version, TRAINER_BACK_PIC):
                print(f"  Warning: 'Back Pic' field requires expansion v{_vs(TRAINER_BACK_PIC)}+ "
                      f"(you have v{_vs(expansion_version)}). The field will be written but may be ignored.")

    # Items
    if record.get("trainer_items"):
        item_names = [_const_to_item_name(it) for it in record["trainer_items"]]
        lines.append(f"Items: {' / '.join(item_names)}")

    # Double Battle
    lines.append(f"Double Battle: {'Yes' if record.get('is_double') else 'No'}")

    # AI
    if record.get("ai_flags"):
        lines.append(f"AI: {_ai_flags_to_party_format(record['ai_flags'])}")

    # Mugshot
    if record.get("mugshot"):
        lines.append(f"Mugshot: {record['mugshot']}")

    # Starting Status
    if record.get("starting_status"):
        lines.append(f"Starting Status: {record['starting_status']}")
        if expansion_version is not None:
            from torch.expansion_compat import requires_version, version_str as _vs, STARTING_STATUS_SYSTEM
            if not requires_version(expansion_version, STARTING_STATUS_SYSTEM):
                print(f"  Warning: 'Starting Status' field requires expansion v{_vs(STARTING_STATUS_SYSTEM)}+ "
                      f"(you have v{_vs(expansion_version)}). The field will be written but may be ignored.")

    # Unknown preserved header fields
    for key, val in record.get("header_extra", []):
        lines.append(f"{key}: {val}")

    # Pokemon
    if record.get("mons"):
        for mon in record["mons"]:
            lines.append("")  # Blank line before each mon
            lines.extend(_serialize_party_mon(mon, use_pokeball_enum))

    lines.append("")  # Trailing newline
    return "\n".join(lines)


def _append_trainer_to_party_file(party_path, record, expansion_version=None):
    """Append a serialized trainer section to end of trainers.party."""
    block = _serialize_party_trainer(record, expansion_version=expansion_version)
    try:
        with open(party_path, "a") as f:
            f.write("\n" + block + "\n")
    except OSError as e:
        print(f"  ERROR: Could not write to trainers.party: {e}")
        return False


def _replace_trainer_in_party_file(party_path, trainer_const, record, expansion_version=None):
    """Replace an entire trainer section in trainers.party."""
    try:
        with open(party_path) as f:
            content = f.read()
    except OSError as e:
        print(f"  ERROR: Could not read trainers.party: {e}")
        return False

    # Find the section boundaries
    pattern = (
        r"(^=== " + re.escape(trainer_const) + r" ===\s*$)"
        r"(.*?)"
        r"(?=^=== \S+ ===\s*$|\Z)"
    )
    m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if not m:
        print(f"  ERROR: Could not find === {trainer_const} === section in trainers.party")
        return False

    new_block = _serialize_party_trainer(record, expansion_version=expansion_version) + "\n"
    new_content = content[:m.start()] + new_block + content[m.end():]
    try:
        with open(party_path, "w") as f:
            f.write(new_content)
    except OSError as e:
        print(f"  ERROR: Could not write trainers.party: {e}")
        return False
    return True


def _patch_party_file_field(party_path, trainer_const, field_key, new_value):
    """Find the trainer section and replace one header field line.
    field_key is the .party field name (e.g. 'Name', 'Class').
    new_value is the human-readable value.
    """
    with open(party_path) as f:
        content = f.read()

    # Find the section
    section_pattern = (
        r"(^=== " + re.escape(trainer_const) + r" ===\s*\n)"
        r"(.*?)"
        r"(?=^=== \S+ ===\s*$|\Z)"
    )
    m = re.search(section_pattern, content, re.MULTILINE | re.DOTALL)
    if not m:
        print(f"  ERROR: Could not find === {trainer_const} === section")
        return False

    header = m.group(1)
    body = m.group(2)

    # Replace the field line within the body
    field_pattern = r"^" + re.escape(field_key) + r":.*$"
    new_body, count = re.subn(field_pattern, f"{field_key}: {new_value}", body,
                               count=1, flags=re.MULTILINE)
    if count == 0:
        # Field doesn't exist yet — add it after the last header field (before first blank line)
        lines = body.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.strip() and ":" in line.strip():
                insert_idx = i + 1
            elif not line.strip() and insert_idx > 0:
                break
        lines.insert(insert_idx, f"{field_key}: {new_value}")
        new_body = "\n".join(lines)

    new_content = content[:m.start()] + header + new_body + content[m.end():]
    with open(party_path, "w") as f:
        f.write(new_content)
    return True


def _replace_party_in_party_file(party_path, trainer_const, new_mons):
    """Replace just the Pokemon section of a trainer in trainers.party.
    Reads the existing section, preserves header fields, replaces mons.
    """
    sections = _read_party_file(party_path)
    if trainer_const not in sections:
        print(f"  ERROR: Could not find === {trainer_const} === in trainers.party")
        return False

    # Re-read the existing record to preserve header fields
    old_record = _parse_party_section(sections[trainer_const], trainer_const)
    old_record["mons"] = new_mons
    return _replace_trainer_in_party_file(party_path, trainer_const, old_record)


def _delete_from_party_file(party_path, trainer_const):
    """Remove entire trainer section from trainers.party."""
    with open(party_path) as f:
        content = f.read()

    pattern = (
        r"^=== " + re.escape(trainer_const) + r" ===\s*$"
        r".*?"
        r"(?=^=== \S+ ===\s*$|\Z)"
    )
    new_content, count = re.subn(pattern, "", content, count=1,
                                  flags=re.MULTILINE | re.DOTALL)
    if count == 0:
        print(f"  WARNING: === {trainer_const} === not found in trainers.party")
        return False

    # Clean up any resulting double blank lines
    new_content = re.sub(r"\n{3,}", "\n\n", new_content)
    with open(party_path, "w") as f:
        f.write(new_content)
    return True


# ============================================================
# PUBLIC API — full-file read/write for round-trip workflows
# ============================================================

def read_party_file(party_path):
    """Read all trainers from a .party file and return a list of record dicts.

    Each record is the same shape returned by _parse_party_section(), including
    header_extra and per-mon extra_fields for round-trip fidelity.
    The file preamble (comments before the first trainer) is stored as
    _preamble on each record list — attach it back via write_party_file's
    preamble parameter.

    Returns (records_list, preamble_str).
    """
    sections, preamble = _read_party_file_full(party_path)
    records = []
    for trainer_const, section_text in sections.items():
        records.append(_parse_party_section(section_text, trainer_const))
    return records, preamble


def write_party_file(party_path, records, preamble="", expansion_version=None):
    """Write a list of trainer record dicts to a .party file.

    Overwrites the file completely. Records are written in list order.
    If preamble is provided, it's written before the first trainer section
    (for round-trip preservation of file comments).
    """
    blocks = [_serialize_party_trainer(r, expansion_version=expansion_version) for r in records]
    with open(party_path, "w") as f:
        if preamble:
            f.write(preamble)
        f.write("\n".join(blocks))
        f.write("\n")


def _read_pory_dialogue(pory_path):
    """
    Extract intro/defeat/not_enough text from a battle_TRAINER_*.pory file.
    Returns dict: {intro, defeat, not_enough}. Values are None if not found.
    """
    result = {"intro": None, "defeat": None, "not_enough": None}
    if not os.path.exists(pory_path):
        return result
    with open(pory_path) as f:
        content = f.read()
    # Match: text LABEL { "content" }
    for m in re.finditer(r'text\s+(\w+)\s*\{\s*"([^"]*)"\s*\}', content, re.DOTALL):
        label = m.group(1).lower()
        text = m.group(2)
        if "intro" in label:
            result["intro"] = text
        elif "defeat" in label:
            result["defeat"] = text
        elif "notenough" in label or "not_enough" in label or "enough" in label:
            result["not_enough"] = text
    return result
