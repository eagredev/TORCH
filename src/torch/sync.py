"""Sync engine, Map Guard, label validation, snapshot/restore."""
# TORCH_MODULE: Sync Engine
# TORCH_GROUP: Script Studio
import os
import re
import json
import zipfile
from datetime import datetime

from torch.compiler import compile_script
from torch.ui import _offer_build, _get_auto_build_setting
from torch.names import _detect_trainer_format
from torch.registry import update_last_written
from torch.gamedata import (
    load_flags, load_vars, load_trainers, load_songs, load_sound,
    load_species, load_specials,
)


def get_workspace_files(source_dir):
    """Get all .txt and .pory source files in a workspace folder (excludes backups/)."""
    files = []
    for fname in os.listdir(source_dir):
        if fname.endswith(".txt") or fname.endswith(".pory"):
            files.append(fname)
    return sorted(files)


def create_snapshot(source_dir, snapshot_dir, map_name, max_snapshots=10):
    """Create a ZIP snapshot of the workspace. Returns the snapshot filename."""
    os.makedirs(snapshot_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{map_name}_{timestamp}.zip"
    zip_path = os.path.join(snapshot_dir, zip_name)

    files = get_workspace_files(source_dir)
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in files:
                zf.write(os.path.join(source_dir, fname), fname)
    except OSError as e:
        print(f"  WARNING: Could not create snapshot: {e}")
        return None

    # Prune old snapshots (pinned snapshots are exempt from the limit)
    snapshots = sorted([
        f for f in os.listdir(snapshot_dir)
        if f.startswith(f"{map_name}_") and f.endswith(".zip")
    ])
    unpinned = [f for f in snapshots if not os.path.exists(os.path.join(snapshot_dir, f + ".pin"))]
    while len(unpinned) > max_snapshots:
        old = unpinned.pop(0)
        os.remove(os.path.join(snapshot_dir, old))
        snapshots.remove(old)

    return zip_name


_global_label_cache = {}  # game_path -> set of labels


def clear_label_cache():
    """Clear the global label cache. Call when scripts may have changed externally."""
    _global_label_cache.clear()


def _load_global_labels(game_path):
    """Scan data/scripts/*.inc for globally defined labels (LabelName: or LabelName::).
    Results are cached per game_path for the session."""
    if not game_path:
        return set()
    if game_path in _global_label_cache:
        return _global_label_cache[game_path]
    labels = set()
    scripts_dir = os.path.join(game_path, "data", "scripts")
    if os.path.isdir(scripts_dir):
        label_re = re.compile(r'^([A-Za-z_]\w*)::?$')
        for fname in os.listdir(scripts_dir):
            if not fname.endswith(".inc"):
                continue
            fpath = os.path.join(scripts_dir, fname)
            try:
                with open(fpath, "r") as f:
                    for line in f:
                        m = label_re.match(line.strip())
                        if m:
                            labels.add(m.group(1))
            except OSError:
                continue
    _global_label_cache[game_path] = labels
    return labels


def _validate_labels(assembled, regions, game_path=None):
    """
    Scan assembled Poryscript for label definitions and references.
    Reports warnings for goto/call/gotoif targets that don't exist as defined
    script/text/movement/mapscripts blocks. Returns list of warning strings.
    """
    # Collect all defined labels: script X {, text X {, movement X {, mapscripts X {
    defined = set()
    label_def_re = re.compile(
        r'^\s*(?:script|text|movement|mapscripts)\s+(\w+)\s*(?:\{|$)', re.MULTILINE
    )
    for m in label_def_re.finditer(assembled):
        defined.add(m.group(1))

    # Include globally defined labels from data/scripts/*.inc
    defined.update(_load_global_labels(game_path))

    # Collect all referenced labels
    references = []  # (target_label, source_region, context_hint)
    # goto(Label), call(Label)
    goto_call_re = re.compile(r'(?:goto|call)\((\w+)\)')
    # trainerbattle refs: trainerbattle_single(TRAINER, Intro, Defeat)
    #                     trainerbattle_double(TRAINER, Intro, Defeat, NotEnough, After)
    tb_single_re = re.compile(
        r'trainerbattle_single\(\s*\w+\s*,\s*(\w+)\s*,\s*(\w+)\s*\)'
    )
    tb_double_re = re.compile(
        r'trainerbattle_double\(\s*\w+\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*\)'
    )
    # do(Label) from movement blocks — compiled form: applymovement ... Label
    do_re = re.compile(r'applymovement\([^,]+,\s*(\w+)\)')

    # Track which region each reference comes from
    for region_name, content, _ in regions:
        for m in goto_call_re.finditer(content):
            references.append((m.group(1), region_name, m.group(0)))
        for m in tb_single_re.finditer(content):
            references.append((m.group(1), region_name, "trainerbattle intro"))
            references.append((m.group(2), region_name, "trainerbattle defeat"))
        for m in tb_double_re.finditer(content):
            references.append((m.group(1), region_name, "trainerbattle intro"))
            references.append((m.group(2), region_name, "trainerbattle defeat"))
            references.append((m.group(3), region_name, "trainerbattle not-enough"))
            references.append((m.group(4), region_name, "trainerbattle after"))
        for m in do_re.finditer(content):
            references.append((m.group(1), region_name, "movement block"))

    # Find undefined references
    warnings = []
    seen = set()  # avoid duplicate warnings for same target
    for target, region, context in references:
        if target not in defined and target not in seen:
            seen.add(target)
            warnings.append(f"    '{target}' referenced in {region} ({context}) -- not defined in this map")

    return warnings


def _validate_constants(assembled, game_path):
    """
    Scan assembled Poryscript for game constants and check they exist in
    the relevant header files.  Returns list of warning strings.

    Validates: FLAG_, VAR_, TRAINER_, SE_, MUS_, FANFARE_, SPECIES_, specials.
    Skips constants that look like local labels (no prefix) or are known
    builtins (OBJ_EVENT_ID_PLAYER, etc.).
    """
    if not game_path:
        return []

    # ---- Build known-constant sets (cached by gamedata module) ----
    _known_sets = {
        "FLAG":    {n for n, _ in load_flags(game_path)},
        "VAR":     {n for n, _ in load_vars(game_path)},
        "TRAINER": {n for n, _ in load_trainers(game_path)},
        "SE":      {n for n, _ in load_songs(game_path, "SE_")},
        "MUS":     {n for n, _ in load_songs(game_path, "MUS_")},
        "FANFARE": {n for n, _ in load_sound(game_path, "FANFARE_")},
        "SPECIES": {n for n, _ in load_species(game_path)},
        "SPECIAL": set(load_specials(game_path)),
    }

    def _known(kind):
        return _known_sets.get(kind, set())

    # ---- Extract constants from assembled output ----
    warnings = []
    seen = set()

    def _check(const, kind, context):
        if const in seen:
            return
        seen.add(const)
        known = _known(kind)
        if not known:
            return  # header not found / empty — skip silently
        if const not in known:
            warnings.append(f"    {kind} '{const}' ({context}) -- not found in game headers")

    # Flags: setflag(X), clearflag(X), flag(X)
    for m in re.finditer(r'(?:setflag|clearflag|flag)\((\w+)\)', assembled):
        c = m.group(1)
        if c.startswith("FLAG_"):
            _check(c, "FLAG", "flag")

    # Vars: setvar(X, ...), addvar(X, ...), compare(X, ...)
    for m in re.finditer(r'(?:setvar|addvar|compare)\((\w+)', assembled):
        c = m.group(1)
        if c.startswith("VAR_"):
            _check(c, "VAR", "variable")

    # Sound effects: playse(X)
    for m in re.finditer(r'playse\((\w+)\)', assembled):
        c = m.group(1)
        if c.startswith("SE_"):
            _check(c, "SE", "sound effect")

    # Music: playbgm(X, ...)
    for m in re.finditer(r'playbgm\((\w+)', assembled):
        c = m.group(1)
        if c.startswith("MUS_"):
            _check(c, "MUS", "music")

    # Fanfare: playfanfare(X)
    for m in re.finditer(r'playfanfare\((\w+)\)', assembled):
        c = m.group(1)
        if c.startswith("FANFARE_"):
            _check(c, "FANFARE", "fanfare")

    # Species: playmoncry(X, ...)
    for m in re.finditer(r'playmoncry\((\w+)', assembled):
        c = m.group(1)
        if c.startswith("SPECIES_"):
            _check(c, "SPECIES", "species")

    # Trainers: trainerbattle_single(X, ...) / trainerbattle_double(X, ...)
    for m in re.finditer(r'trainerbattle_(?:single|double)\((\w+)', assembled):
        c = m.group(1)
        if c.startswith("TRAINER_"):
            _check(c, "TRAINER", "trainer")

    # Specials: special(X)
    for m in re.finditer(r'special\((\w+)\)', assembled):
        c = m.group(1)
        # Specials don't have a fixed prefix — check all of them
        if c not in ("0", "1"):  # skip numeric args
            _check(c, "SPECIAL", "special function")

    return warnings


def _scan_map_mapsecs(maps_dir):
    """Scan data/maps/*/map.json and return {map_name: mapsec_id}."""
    result = {}
    try:
        for map_name in os.listdir(maps_dir):
            map_json = os.path.join(maps_dir, map_name, "map.json")
            if not os.path.isfile(map_json):
                continue
            try:
                with open(map_json, "r") as f:
                    mdata = json.load(f)
                mapsec = mdata.get("region_map_section", "")
                if mapsec:
                    result[map_name] = mapsec
            except (json.JSONDecodeError, OSError):
                continue
    except OSError:
        pass
    return result


def _load_region_map_entries(region_map_file):
    """Load region_map_sections.json and return {mapsec_id: entry_dict}."""
    entries = {}
    if os.path.isfile(region_map_file):
        try:
            with open(region_map_file, "r") as f:
                rdata = json.load(f)
            for entry in rdata.get("map_sections", []):
                mapsec_id = entry.get("id") or entry.get("map_section", "")
                if mapsec_id:
                    entries[mapsec_id] = entry
        except (json.JSONDecodeError, OSError):
            pass
    return entries


def _merge_mapsec_backup(backup_dir, custom_mapsecs, mapsecs):
    """Merge new data with any existing backup (monotonic — never lose entries).

    Modifies custom_mapsecs (list) and mapsecs (dict) in place.
    """
    custom_file = os.path.join(backup_dir, "custom_mapsecs.json")
    mapsecs_file = os.path.join(backup_dir, "mapsecs.json")

    if os.path.isfile(custom_file):
        try:
            with open(custom_file, "r") as f:
                existing = json.load(f)
            current_ids = set()
            for e in custom_mapsecs:
                current_ids.add(e.get("id") or e.get("map_section", ""))
            for old in existing:
                old_id = old.get("id") or old.get("map_section", "")
                if old_id and old_id not in current_ids:
                    custom_mapsecs.append(old)
        except (json.JSONDecodeError, OSError):
            pass

    if os.path.isfile(mapsecs_file):
        try:
            with open(mapsecs_file, "r") as f:
                existing = json.load(f)
            for k, v in existing.items():
                if k not in mapsecs:
                    mapsecs[k] = v
                elif mapsecs[k] == "MAPSEC_NONE" and v != "MAPSEC_NONE":
                    mapsecs[k] = v
        except (json.JSONDecodeError, OSError):
            pass


def _auto_generate_mapsec_backup(game_path):
    """
    Scan the project and auto-generate a per-project mapsec backup.

    Reads every data/maps/*/map.json to collect region_map_section values,
    cross-references with region_map_sections.json to build the backup files:
      - custom_mapsecs.json: region map section entries for custom maps
      - mapsecs.json: map_name -> mapsec_id mapping for custom maps

    Returns the backup directory path ({game_path}/.torch/mapsec_backup/).
    """
    maps_dir = os.path.join(game_path, "data", "maps")
    region_map_file = os.path.join(
        game_path, "src", "data", "region_map", "region_map_sections.json"
    )
    backup_dir = os.path.join(game_path, ".torch", "mapsec_backup")

    if not os.path.isdir(maps_dir):
        return backup_dir

    map_mapsec = _scan_map_mapsecs(maps_dir)
    if not map_mapsec:
        return backup_dir

    region_entries = _load_region_map_entries(region_map_file)

    # Build custom_mapsecs.json — region map entries for all used mapsecs
    used_mapsecs = set(map_mapsec.values())
    custom_mapsecs = [region_entries[m] for m in sorted(used_mapsecs)
                      if m in region_entries]

    # Build mapsecs.json — map_name -> mapsec_id for all maps
    mapsecs = {k: v for k, v in sorted(map_mapsec.items())}

    # Merge with existing backup (never lose previously saved entries)
    _merge_mapsec_backup(backup_dir, custom_mapsecs, mapsecs)

    # Write backup files
    if custom_mapsecs or mapsecs:
        os.makedirs(backup_dir, exist_ok=True)
        custom_file = os.path.join(backup_dir, "custom_mapsecs.json")
        mapsecs_file = os.path.join(backup_dir, "mapsecs.json")
        if custom_mapsecs:
            with open(custom_file, "w") as f:
                json.dump(custom_mapsecs, f, indent=2)
        if mapsecs:
            with open(mapsecs_file, "w") as f:
                json.dump(mapsecs, f, indent=2)

    return backup_dir


def _run_map_guard(game_path, mapsec_backup_dir=None):
    """
    Map Guard — detect and fix the three known Porymap save bugs.
    Runs automatically before every sync to ensure game data is clean.
    Returns the number of fixes applied (0 = nothing broken).

    Args:
        game_path: Path to the game project root.
        mapsec_backup_dir: Directory containing mapsec backup files
            (mapsecs.json, custom_mapsecs.json). If None, auto-generates
            a per-project backup from the project's own map data.
    """
    fixes = 0

    if mapsec_backup_dir is None:
        mapsec_backup_dir = _auto_generate_mapsec_backup(game_path)

    region_map_file = os.path.join(
        game_path, "src", "data", "region_map", "region_map_sections.json"
    )
    custom_mapsecs_file = os.path.join(mapsec_backup_dir, "custom_mapsecs.json")
    mapsecs_backup_file = os.path.join(mapsec_backup_dir, "mapsecs.json")
    maps_dir = os.path.join(game_path, "data", "maps")

    # --- Fix 1: Normalize mapsec key to match what the template expects ---
    # The template (*.json.txt) uses either "map_section.id" (≥1.14) or
    # "map_section.map_section" (older).  Porymap sometimes writes entries
    # with the wrong key — e.g. new maps added by Porymap on ≥1.14 use
    # "map_section" instead of "id".  Detect which key the template wants
    # and rename any mismatched entries.
    if os.path.exists(region_map_file):
        template = region_map_file.replace(".json", ".json.txt")
        expects_old_key = False
        if os.path.exists(template):
            try:
                with open(template, "r") as f:
                    tpl = f.read()
                expects_old_key = "map_section.map_section" in tpl
            except OSError:
                expects_old_key = False
        else:
            # No template found — assume old format for safety
            expects_old_key = True

        if expects_old_key:
            with open(region_map_file, "r") as f:
                raw = f.read()
            if '"id":' in raw:
                raw = raw.replace('"id":', '"map_section":')
                with open(region_map_file, "w") as f:
                    f.write(raw)
                fixes += 1
        else:
            # New format: template expects "id".  Porymap may write
            # "map_section" for newly added maps — rename to "id".
            try:
                with open(region_map_file, "r") as f:
                    data = json.load(f)
                key_fixed = False
                for entry in data.get("map_sections", []):
                    if "map_section" in entry and "id" not in entry:
                        entry["id"] = entry.pop("map_section")
                        key_fixed = True
                if key_fixed:
                    with open(region_map_file, "w") as f:
                        json.dump(data, f, indent=2)
                    fixes += 1
            except (json.JSONDecodeError, OSError):
                pass

    # --- Fix 2: Restore missing "name" fields + custom mapsec entries ---
    if os.path.exists(region_map_file):
        try:
            with open(region_map_file, "r") as f:
                data = json.load(f)
            changed = False

            # Ensure every entry has a "name" field
            for entry in data.get("map_sections", []):
                if "name" not in entry:
                    entry["name"] = ""
                    changed = True

            # Restore custom mapsec entries if backup exists
            if os.path.exists(custom_mapsecs_file):
                with open(custom_mapsecs_file, "r") as f:
                    custom = json.load(f)
                existing = set()
                for e in data.get("map_sections", []):
                    existing.add(e.get("map_section") or e.get("id", ""))
                for entry in custom:
                    mapsec_val = entry.get("map_section") or entry.get("id", "")
                    if mapsec_val and mapsec_val not in existing:
                        data["map_sections"].append(entry)
                        changed = True

            if changed:
                with open(region_map_file, "w") as f:
                    json.dump(data, f, indent=2)
                fixes += 1
        except (json.JSONDecodeError, KeyError):
            pass  # Don't crash sync over a JSON parse error

    # --- Fix 3: Restore custom map mapsec assignments ---
    if os.path.exists(mapsecs_backup_file):
        try:
            with open(mapsecs_backup_file, "r") as f:
                mapsecs = json.load(f)
            restored = 0
            for map_name_fix, mapsec in mapsecs.items():
                map_json = os.path.join(maps_dir, map_name_fix, "map.json")
                if not os.path.exists(map_json):
                    continue
                with open(map_json, "r") as f:
                    mdata = json.load(f)
                if mdata.get("region_map_section") != mapsec:
                    mdata["region_map_section"] = mapsec
                    with open(map_json, "w") as f:
                        json.dump(mdata, f, indent=2)
                    restored += 1
            if restored:
                fixes += 1
        except (json.JSONDecodeError, KeyError):
            pass

    return fixes


def _sync_prep_and_backup(map_name, source_dir, game_map_dir, game_path,
                          target_path, max_snapshots, quiet=False,
                          skip_snapshot=False):
    """Phase 1: Verify dirs, run Map Guard, migrate legacy, create snapshot.
    Returns True to continue, False to abort."""
    if not os.path.isdir(source_dir):
        if not os.path.isdir(game_map_dir):
            if not quiet:
                print(f"  ERROR: Game map folder not found: {game_map_dir}")
                print(f"  (Check that '{map_name}' exists in your game's data/maps/ folder)")
            return False
        os.makedirs(source_dir, exist_ok=True)
        if not quiet:
            print(f"  Created workspace: {source_dir}")

    if not os.path.isdir(game_map_dir):
        if not quiet:
            print(f"  ERROR: Game map folder not found: {game_map_dir}")
        return False

    # Map Guard: fix Porymap save bugs
    guard_fixes = _run_map_guard(game_path)
    if guard_fixes and not quiet:
        print(f"  Map Guard: fixed {guard_fixes} Porymap issue{'s' if guard_fixes != 1 else ''}")

    # Auto-migrate legacy .inc if needed
    legacy_path = os.path.join(source_dir, "legacy.pory")
    setup_path = os.path.join(source_dir, "setup.pory")
    inc_path = os.path.join(game_map_dir, "scripts.inc")
    if not os.path.exists(legacy_path) and os.path.exists(inc_path) and not os.path.exists(target_path):
        if not quiet:
            print(f"  Migrating legacy scripts.inc -> legacy.pory")
        try:
            with open(inc_path, "r") as f:
                inc_content = f.read()
            with open(legacy_path, "w") as f:
                f.write("// Legacy code migrated from scripts.inc\n")
                f.write("raw `\n")
                f.write(inc_content)
                f.write("`\n")
        except OSError as e:
            if not quiet:
                print(f"  ERROR: Could not migrate legacy scripts.inc: {e}")
            return False

    # Auto-generate setup.pory if it doesn't exist
    if not os.path.exists(setup_path):
        has_legacy = os.path.exists(legacy_path)
        try:
            with open(setup_path, "w") as f:
                f.write(f"// {map_name} -- mapscripts, shared text & movement data\n")
                if has_legacy:
                    f.write("// mapscripts provided by legacy.pory\n")
                else:
                    ms_label = f"{map_name}_MapScripts"
                    if os.path.exists(inc_path):
                        with open(inc_path, "r") as f2:
                            for line in f2:
                                m = re.match(r'^(\w+_MapScripts)::', line)
                                if m:
                                    ms_label = m.group(1)
                                    break
                    f.write(f"\nmapscripts {ms_label} {{}}\n")
        except OSError as e:
            if not quiet:
                print(f"  ERROR: Could not create setup.pory: {e}")
            return False
        if not quiet:
            if has_legacy:
                print(f"  Created: setup.pory (mapscripts in legacy.pory)")
            else:
                print(f"  Created: setup.pory (mapscripts: {ms_label})")

    # Snapshot: ZIP the current workspace before syncing
    if not skip_snapshot:
        workspace_files = get_workspace_files(source_dir)
        if workspace_files:
            snapshot_dir = os.path.join(source_dir, "backups", "snapshots")
            zip_name = create_snapshot(source_dir, snapshot_dir, map_name, max_snapshots)
            if not quiet:
                if zip_name:
                    print(f"  Snapshot: {len(workspace_files)} files -> backups/snapshots/{zip_name}")
                else:
                    print(f"  Snapshot: skipped (write failed)")

    return True


def _sync_collect_aliases(source_dir, source_files, quiet=False,
                          game_path=None, map_name=None):
    """Phase 2a: Scan .txt files for alias definitions (auto-constants).
    Returns alias_map dict, or None on conflict.

    When game_path and map_name are provided, auto-repairs stale alias
    NPC IDs by matching alias names to NPC script labels in map.json.
    """
    # Build label→object_id lookup for auto-repair
    label_to_objid = {}
    if game_path and map_name:
        try:
            from torch.project_files import get_map_objects
            for npc in get_map_objects(game_path, map_name):
                label = npc.get("script", "")
                if label:
                    label_to_objid[label] = npc["object_id"]
        except Exception:
            pass

    alias_map = {}  # alias_name -> (npc_id, first_file_that_defined_it)
    for fname in sorted(source_files):
        if not fname.endswith(".txt"):
            continue
        filepath = os.path.join(source_dir, fname)
        try:
            with open(filepath, "r") as f:
                lines = f.readlines()
        except OSError as e:
            if not quiet:
                print(f"  ERROR: Could not read {fname}: {e}")
            return None

        # Auto-repair stale aliases before collecting
        if label_to_objid:
            _sync_repair_aliases(filepath, lines, label_to_objid)
            try:
                with open(filepath, "r") as f:
                    lines = f.readlines()
            except OSError:
                pass

        for line in lines:
            line = line.strip()
            tokens = line.split()
            if len(tokens) >= 3 and tokens[0] == "alias":
                alias_name = tokens[1]
                target = tokens[2]
                m = re.match(r"^npc(\d+)$", target)
                if not m:
                    continue
                npc_id = int(m.group(1))
                if alias_name in alias_map:
                    prev_id, prev_file = alias_map[alias_name]
                    if prev_id != npc_id:
                        if not quiet:
                            print(f"  ERROR: Conflicting alias '{alias_name}' -- "
                                  f"npc{prev_id} in {prev_file} vs npc{npc_id} in {fname}")
                        return None
                else:
                    alias_map[alias_name] = (npc_id, fname)

    if alias_map and not quiet:
        print(f"  Auto-constants: {', '.join(name.upper() for name in sorted(alias_map))}")

    return alias_map


def _sync_collect_pokemon(source_dir, source_files, quiet=False):
    """Scan .txt files for 'pokemon species npcN' declarations.
    Returns dict: {species_name: (npc_id, filename)} or empty dict.
    """
    pokemon_map = {}
    for fname in sorted(source_files):
        if not fname.endswith(".txt"):
            continue
        filepath = os.path.join(source_dir, fname)
        try:
            with open(filepath, "r") as f:
                file_lines = f.readlines()
        except OSError:
            continue
        for line in file_lines:
            line = line.strip()
            tokens = line.split()
            if len(tokens) >= 3 and tokens[0] == "pokemon":
                species = tokens[1].lower()
                target = tokens[2]
                m = re.match(r"^npc(\d+)$", target)
                if not m:
                    continue
                npc_id = int(m.group(1))
                if species not in pokemon_map:
                    pokemon_map[species] = (npc_id, fname)
    return pokemon_map


def _sync_apply_pokemon_graphics(pokemon_map, game_path, map_name, quiet=False):
    """Update map.json object events for declared Pokemon actors.

    Sets graphics_id to OBJ_EVENT_GFX_SPECIES(SPECIES) and movement_type
    to WALK_IN_PLACE if currently static.
    """
    from torch.data import POKEMON_DEFAULT_MOVEMENT, POKEMON_STATIC_MOVEMENTS
    map_json_path = os.path.join(game_path, "data", "maps", map_name, "map.json")
    if not os.path.isfile(map_json_path):
        return

    try:
        with open(map_json_path, "r") as f:
            map_data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    obj_events = map_data.get("object_events", [])
    modified = False

    for species, (npc_id, _fname) in pokemon_map.items():
        idx = npc_id - 1  # map.json is 0-indexed, npc IDs are 1-indexed
        if idx < 0 or idx >= len(obj_events):
            if not quiet:
                print(f"  WARNING: Pokemon '{species}' references npc{npc_id} "
                      f"but map only has {len(obj_events)} object events")
            continue

        obj = obj_events[idx]
        expected_gfx = f"OBJ_EVENT_GFX_SPECIES({species.upper()})"

        if obj.get("graphics_id") != expected_gfx:
            obj["graphics_id"] = expected_gfx
            modified = True

        # Only override movement type if it's a static type
        current_mt = obj.get("movement_type", "")
        if current_mt in POKEMON_STATIC_MOVEMENTS:
            obj["movement_type"] = POKEMON_DEFAULT_MOVEMENT
            modified = True

    if modified:
        try:
            with open(map_json_path, "w") as f:
                json.dump(map_data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            if not quiet:
                names = [s.upper() for s in pokemon_map]
                print(f"  Pokemon actors: set graphics for {', '.join(names)}")
        except OSError as e:
            if not quiet:
                print(f"  WARNING: Could not update map.json: {e}")


def _sync_repair_aliases(filepath, lines, label_to_objid):
    """Fix stale alias NPC IDs in a script file before sync.

    Matches alias names against NPC script labels (case-insensitive
    suffix match) and corrects any mismatched IDs in place.
    """
    aliases = []  # [(line_idx, alias_name, old_npc_id)]
    for li, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r'^alias\s+(\w+)\s+npc(\d+)\s*$', stripped)
        if m:
            aliases.append((li, m.group(1), int(m.group(2))))
        elif not stripped.startswith("alias"):
            break

    if not aliases:
        return

    modified = False
    new_lines = list(lines)
    for li, alias_name, old_id in aliases:
        for label, obj_id in label_to_objid.items():
            suffix = f"_{alias_name}"
            if label.lower().endswith(suffix.lower()):
                if old_id != obj_id:
                    new_lines[li] = re.sub(
                        r'(alias\s+' + re.escape(alias_name) + r'\s+npc)\d+',
                        rf'\g<1>{obj_id}',
                        new_lines[li],
                    )
                    modified = True
                break

    if modified:
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except OSError:
            pass


def _sync_compile_sources(source_dir, source_files, emotes_conf,
                          quiet=False, map_id=None, game_path=None,
                          map_name=None):
    """Phase 2b: Compile .txt and read .pory source files.
    Returns list of (region_name, content, had_errors)."""
    regions = []
    for fname in source_files:
        stem = os.path.splitext(fname)[0]
        ext = os.path.splitext(fname)[1]
        filepath = os.path.join(source_dir, fname)

        if ext == ".pory":
            try:
                with open(filepath, "r") as f:
                    content = f.read().rstrip("\n")
            except OSError as e:
                if not quiet:
                    print(f"  ERROR: Could not read {fname}: {e}")
                continue
            regions.append((stem, content, False))
            if not quiet:
                print(f"  Read: {fname}")
        elif ext == ".txt":
            label_prefix = stem
            try:
                content, errors = compile_script(filepath, label_prefix,
                                                 emotes_conf, map_id=map_id,
                                                 game_path=game_path,
                                                 map_name=map_name)
                # Strip const lines -- auto-constants region provides them
                lines = content.split("\n")
                lines = [l for l in lines if not l.startswith("const ")]
                while lines and not lines[0].strip():
                    lines.pop(0)
                content = "\n".join(lines)
                had_errors = len(errors) > 0
                if had_errors and not quiet:
                    print(f"  COMPILE ERRORS in {fname}:")
                    for err in errors:
                        print(f"    {err}")
                    print(f"  (included with errors -- check carefully)")
                elif not had_errors and not quiet:
                    print(f"  Compiled: {fname}")
                regions.append((stem, content.rstrip("\n"), had_errors))
            except Exception as e:
                if not quiet:
                    print(f"  ERROR compiling {fname}: {e}")
                    print(f"  (skipped)")

    return regions


def _extract_unmanaged_content(target_path):
    """Read existing scripts.pory and extract content outside REGION markers.

    Returns (segments: list[str], has_torch_header: bool).
    Each segment is a non-empty block of text that was outside any
    ``// # REGION:`` / ``// # END REGION:`` or
    ``// # UNMANAGED`` / ``// # END UNMANAGED`` boundary.
    """
    if not os.path.isfile(target_path):
        return ([], False)
    try:
        with open(target_path, "r") as f:
            lines = f.readlines()
    except OSError:
        return ([], False)

    # Detect TORCH header
    has_torch_header = any("AUTO-GENERATED by TORCH" in l for l in lines[:5])

    # Header lines to skip (regenerated by TORCH)
    _header_patterns = (
        "// ====",
        "// AUTO-GENERATED by TORCH",
        "// Source:",
    )

    state = "outside"   # "outside" | "inside_region" | "inside_unmanaged"
    current = []
    segments = []

    def _flush():
        text = "".join(current).strip("\n")
        if text.strip():
            segments.append(text)
        current.clear()

    for line in lines:
        stripped = line.rstrip("\n")
        # Detect boundary markers
        if re.match(r'^// # REGION:', stripped):
            _flush()
            state = "inside_region"
            continue
        if re.match(r'^// # END REGION:', stripped):
            state = "outside"
            current.clear()
            continue
        if re.match(r'^// # UNMANAGED', stripped):
            _flush()
            state = "inside_unmanaged"
            continue
        if re.match(r'^// # END UNMANAGED', stripped):
            _flush()
            state = "outside"
            continue

        if state == "outside":
            # Skip TORCH header lines
            if has_torch_header and any(stripped.startswith(p) for p in _header_patterns):
                continue
            current.append(line)
        elif state == "inside_unmanaged":
            # Skip the explanatory comment lines inside UNMANAGED blocks
            if stripped.startswith("// # These scripts were") or stripped.startswith("// # To bring them"):
                continue
            current.append(line)
        # inside_region: skip (TORCH-managed content)

    _flush()
    return (segments, has_torch_header)


def _import_unmanaged_to_workspace(segments, source_dir, map_name, quiet=False):
    """Write unmanaged content segments to a .pory file in the workspace."""
    from torch.colours import GREEN, RST
    content = "\n\n".join(segments) + "\n"

    # Find a filename that doesn't collide
    stem = "custom"
    candidate = f"{stem}.pory"
    counter = 1
    while os.path.exists(os.path.join(source_dir, candidate)):
        candidate = f"{stem}_{counter}.pory"
        counter += 1

    out_path = os.path.join(source_dir, candidate)
    try:
        with open(out_path, "w") as f:
            f.write(content)
        if not quiet:
            print(f"  {GREEN}Imported:{RST} {candidate}")
            print(f"  These scripts are now managed by TORCH.")
        return candidate
    except OSError as e:
        if not quiet:
            print(f"  ERROR: Could not write {candidate}: {e}")
        return None


def _detect_label_collisions(unmanaged_segments, regions):
    """Check for label definitions in unmanaged content that conflict with workspace regions.
    Returns list of warning strings."""
    label_re = re.compile(r'^(script|text|movement|mapscripts)\s+(\w+)\s*\{', re.MULTILINE)

    # Collect workspace-defined labels
    workspace_labels = {}  # label -> region_name
    for region_name, content, _had_errors in regions:
        for m in label_re.finditer(content):
            workspace_labels[m.group(2)] = region_name

    # Scan unmanaged content for conflicts
    warnings = []
    for segment in unmanaged_segments:
        for m in label_re.finditer(segment):
            label = m.group(2)
            if label in workspace_labels:
                warnings.append(
                    f"    WARNING: '{label}' defined in both unmanaged content "
                    f"and workspace region '{workspace_labels[label]}'"
                )
    return warnings


def _sync_assemble_and_write(regions, alias_map, source_display, map_name,
                             target_path, game_path, quiet=False,
                             unmanaged_content=None):
    """Phase 3: Sort, dedup, assemble, validate, and write scripts.pory.
    Returns True on success, False on write failure."""
    # Sort: setup first, legacy second, then alphabetical
    def sort_key(region):
        name = region[0]
        if name == "setup":
            return (0, name)
        elif name == "legacy":
            return (1, name)
        else:
            return (2, name.lower())

    regions.sort(key=sort_key)

    # Deduplicate text labels across regions
    _text_block_re = re.compile(
        r'^(text\s+(\w+)\s*\{[^}]*\})',
        re.MULTILINE
    )
    seen_labels = {}  # label -> region_name that first defined it
    dedup_warnings = []
    deduped_regions = []
    for region_name, content, had_errors in regions:
        new_content = content
        for match in reversed(list(_text_block_re.finditer(content))):
            label = match.group(2)
            if label in seen_labels:
                start, end = match.span(1)
                before = new_content[:start].rstrip('\n')
                after = new_content[end:].lstrip('\n')
                if before and after:
                    new_content = before + '\n\n' + after
                elif before:
                    new_content = before
                else:
                    new_content = after
                dedup_warnings.append(
                    f"    Stripped duplicate 'text {label}' from {region_name}.pory"
                    f" (already in {seen_labels[label]}.pory)"
                )
            else:
                seen_labels[label] = region_name
        deduped_regions.append((region_name, new_content.rstrip('\n'), had_errors))
    if dedup_warnings and not quiet:
        print("  Dedup: removed duplicate text labels:")
        for w in dedup_warnings:
            print(w)
    regions = deduped_regions

    # Build output
    parts = []
    parts.append("// ============================================")
    parts.append("// AUTO-GENERATED by TORCH -- do not hand-edit")
    parts.append(f"// Source: {source_display}/{map_name}/")
    parts.append("// ============================================")
    parts.append("")

    if alias_map:
        parts.append("// # REGION: Auto-Generated Constants")
        for name, (npc_id, _) in sorted(alias_map.items()):
            parts.append(f"const LOCALID_{name.upper()} = {npc_id}")
        parts.append("// # END REGION: Auto-Generated Constants")
        parts.append("")

    for region_name, content, had_errors in regions:
        parts.append(f"// # REGION: {region_name}")
        parts.append(content)
        parts.append(f"// # END REGION: {region_name}")
        parts.append("")

    # Preserve unmanaged content (scripts written outside TORCH)
    if unmanaged_content:
        # Check for label collisions
        collision_warnings = _detect_label_collisions(unmanaged_content, regions)
        if collision_warnings and not quiet:
            print("  Label collision with unmanaged content:")
            for w in collision_warnings:
                print(w)

        parts.append("// # UNMANAGED: Preserved content (not managed by TORCH)")
        parts.append("// # To bring them under TORCH management, move them to a .pory file in the workspace.")
        for i, segment in enumerate(unmanaged_content):
            if i > 0:
                parts.append("")
            parts.append(segment)
        parts.append("// # END UNMANAGED")
        parts.append("")

        if not quiet:
            count = len(unmanaged_content)
            print(f"  Preserved: {count} unmanaged script block(s) found outside TORCH regions")
            print(f"    Tip: move these to a .pory file in the workspace to manage them with TORCH")

    assembled = "\n".join(parts)

    # Label validation
    label_warnings = _validate_labels(assembled, regions, game_path)
    if label_warnings and not quiet:
        print("  Label check: undefined references found:")
        for w in label_warnings:
            print(w)
        print("  (these will cause build errors -- check spelling or add missing labels)")

    # Constant validation
    const_warnings = _validate_constants(assembled, game_path)
    if const_warnings and not quiet:
        print("  Constant check: unrecognised constants found:")
        for w in const_warnings:
            print(w)
        print("  (check spelling or define them in the relevant header file)")

    # Write
    try:
        with open(target_path, "w") as f:
            f.write(assembled)
    except OSError as e:
        if not quiet:
            print(f"  ERROR: Could not write scripts.pory — {target_path} was NOT updated: {e}")
        return False

    error_count = sum(1 for _, _, e in regions if e)
    if not quiet:
        print(f"  Wrote: {target_path}")
        print(f"  Regions: {len(regions)} ({error_count} with warnings)")
    return True


def sync_map(map_name, project_dir, game_path, emotes_conf, source_display,
             max_snapshots=10, quiet=False, skip_snapshot=False):
    """Sync a single map folder from project workspace to the game.

    When quiet=True, suppresses all print() output.
    When skip_snapshot=True, skips ZIP snapshot creation (faster for auto-sync).
    Pristine and locked maps are skipped (not a failure).
    """
    # State guard — only sync claimed maps
    from torch.registry import get_map_state, STATE_PRISTINE, STATE_LOCKED
    state = get_map_state(project_dir, map_name)
    if state == STATE_PRISTINE:
        if not quiet:
            print(f"  {map_name}: pristine (read-only) — skipping sync")
        return True
    if state == STATE_LOCKED:
        if not quiet:
            print(f"  {map_name}: locked — skipping sync")
        return True

    source_dir = os.path.join(project_dir, map_name)
    game_map_dir = os.path.join(game_path, "data", "maps", map_name)
    target_path = os.path.join(game_map_dir, "scripts.pory")

    if not _sync_prep_and_backup(map_name, source_dir, game_map_dir, game_path,
                                 target_path, max_snapshots, quiet=quiet,
                                 skip_snapshot=skip_snapshot):
        return False

    # Scan for source files
    source_files = [f for f in os.listdir(source_dir)
                    if f.endswith(".txt") or f.endswith(".pory")]

    if not source_files:
        if not quiet:
            print(f"  WARNING: No .txt or .pory files in {source_dir}")
        return False

    # Collision check: same stem with both .txt and .pory
    stems = {}
    for fname in source_files:
        stem = os.path.splitext(fname)[0]
        if stem in stems:
            if not quiet:
                print(f"  ERROR: Collision -- both {stem}.txt and {stem}.pory exist. Remove one.")
            return False
        stems[stem] = os.path.splitext(fname)[1]

    alias_map = _sync_collect_aliases(source_dir, source_files, quiet=quiet,
                                      game_path=game_path, map_name=map_name)
    if alias_map is None:
        return False

    # Collect Pokemon actor declarations and update map.json graphics
    pokemon_map = _sync_collect_pokemon(source_dir, source_files, quiet=quiet)
    if pokemon_map:
        # Merge Pokemon actors into alias_map so their consts appear
        for species, (npc_id, fname) in pokemon_map.items():
            if species not in alias_map:
                alias_map[species] = (npc_id, fname)
        # Update map.json with correct graphics_id and movement_type
        _sync_apply_pokemon_graphics(pokemon_map, game_path, map_name,
                                     quiet=quiet)

    # Read map constant from map.json for camera reset support
    map_id = None
    map_json_path = os.path.join(game_map_dir, "map.json")
    if os.path.isfile(map_json_path):
        try:
            with open(map_json_path, "r") as f:
                _mdata = json.load(f)
            map_id = _mdata.get("id")
        except (OSError, json.JSONDecodeError):
            pass

    regions = _sync_compile_sources(source_dir, source_files, emotes_conf,
                                    quiet=quiet, map_id=map_id,
                                    game_path=game_path,
                                    map_name=map_name)

    # Auto-apply camera engine patch if any script uses ScriptResetCameraOffset
    _needs_patch = any("ScriptResetCameraOffset" in content
                       for _, content, _ in regions)
    if _needs_patch:
        from torch.camera_patch import detect_camera_patch, apply_camera_patch
        if not detect_camera_patch(game_path):
            if not quiet:
                try:
                    answer = input("  Camera controls require a small engine "
                                   "patch (field_camera.c). Apply? [Y/n] > ")
                except EOFError:
                    answer = "y"
                if answer.strip().lower() in ("", "y", "yes"):
                    ok, msg = apply_camera_patch(game_path)
                    if not quiet:
                        print(f"  {msg}")
                else:
                    if not quiet:
                        print("  Skipped. camera reset may not work correctly "
                              "without the engine patch.")

    # Auto-apply Pokemon actor engine patch if any script uses ScriptUnfreezePokemonActor
    _needs_pokemon_patch = any("ScriptUnfreezePokemonActor" in content
                               for _, content, _ in regions)
    if _needs_pokemon_patch:
        from torch.pokemon_patch import detect_pokemon_patch, apply_pokemon_patch
        if not detect_pokemon_patch(game_path):
            if not quiet:
                try:
                    answer = input("  Pokemon actors require a small engine "
                                   "patch (event_object_movement.c). Apply? [Y/n] > ")
                except EOFError:
                    answer = "y"
                if answer.strip().lower() in ("", "y", "yes"):
                    ok, msg = apply_pokemon_patch(game_path)
                    if not quiet:
                        print(f"  {msg}")
                else:
                    if not quiet:
                        print("  Skipped. Pokemon actors may freeze during "
                              "cutscenes without the engine patch.")

    # Extract unmanaged content from existing scripts.pory before overwriting
    unmanaged, _had_header = _extract_unmanaged_content(target_path)

    if not _sync_assemble_and_write(regions, alias_map, source_display,
                                    map_name, target_path, game_path,
                                    quiet=quiet,
                                    unmanaged_content=unmanaged):
        return False

    # Offer to import unmanaged content into workspace
    if unmanaged and not quiet:
        from torch.colours import GOLD, RST
        try:
            choice = input(f"  {GOLD}Import unmanaged scripts to workspace? [y/N]{RST} > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = ""
        if choice in ("y", "yes"):
            _import_unmanaged_to_workspace(unmanaged, source_dir, map_name,
                                           quiet=quiet)

    update_last_written(project_dir, map_name)
    return True


def ensure_synced(map_name, project_dir, game_path, emotes_conf,
                  source_display, max_snapshots=10, quiet=True):
    """Check map health and auto-sync if stale or never written.

    Lightweight gate for automatic sync at every entry point.
    - "ok": no-op (fast path, just stat calls)
    - "stale" / "never_written": quiet sync (skip snapshot)
    - "drift": warn but don't overwrite (protects external edits)
    - "orphan" / "missing_workspace" / empty workspace: skip silently

    Returns (did_sync: bool, errors: list[str]).
    Never crashes, never blocks navigation.
    """
    try:
        from torch.registry import (
            get_map_health, is_enrolled, enroll_map,
            get_map_state, STATE_PRISTINE, STATE_LOCKED,
        )
        from torch.colours import DIM, RST, GOLD

        # Auto-enroll if workspace + game folder exist but not enrolled
        ws_dir = os.path.join(project_dir, map_name)
        game_map_dir = os.path.join(game_path, "data", "maps", map_name)
        if (os.path.isdir(ws_dir) and os.path.isdir(game_map_dir)
                and not is_enrolled(project_dir, map_name)):
            enroll_map(project_dir, map_name)

        # State guard — skip locked maps, re-decompile pristine_stale
        state = get_map_state(project_dir, map_name)
        if state == STATE_LOCKED:
            return (False, [])

        health = get_map_health(project_dir, map_name, game_path)

        if health == "pristine_stale":
            try:
                from torch.bulk_decompile import re_decompile_pristine
                re_decompile_pristine(game_path, map_name, project_dir)
                print(f"  {DIM}Re-decompiled {map_name} (pristine){RST}")
                return (True, [])
            except Exception:
                return (False, [])

        # Pristine maps that are "ok" need no action
        if state == STATE_PRISTINE:
            return (False, [])

        if health == "ok":
            return (False, [])

        if health in ("orphan", "missing_workspace"):
            return (False, [])

        # Check for empty workspace
        ws_dir = os.path.join(project_dir, map_name)
        if os.path.isdir(ws_dir):
            has_sources = any(
                f.endswith(".txt") or f.endswith(".pory")
                for f in os.listdir(ws_dir)
            )
            if not has_sources:
                return (False, [])

        if health == "drift":
            print(f"  {DIM}{map_name}: game scripts edited externally"
                  f" (run torch sync to overwrite){RST}")
            return (False, [])

        # stale or never_written — auto-sync quietly
        success = sync_map(map_name, project_dir, game_path, emotes_conf,
                           source_display, max_snapshots,
                           quiet=True, skip_snapshot=True)
        errors = []
        if success:
            print(f"  {DIM}Compiled {map_name}{RST}")
        else:
            msg = f"Auto-sync failed for {map_name}"
            errors.append(msg)
            if not quiet:
                print(f"  {GOLD}{msg}{RST}")
        return (success, errors)

    except Exception:
        return (False, [])


def sync_all(project_dir, game_path, emotes_conf, source_display, max_snapshots=10):
    """Sync all enrolled maps from the project workspace to the game."""
    from torch.registry import (
        load_registry, get_enrolled_maps, bulk_enroll,
        get_unenrolled_workspace_dirs, get_map_health,
        get_maps_by_state, STATE_PRISTINE, STATE_CLAIMED, STATE_LOCKED,
    )

    if not os.path.isdir(project_dir):
        print(f"  Error: Project workspace not found: {project_dir}")
        return False

    # Auto-migration: if registry is empty but workspace folders exist, bulk-enroll
    registry = load_registry(project_dir)
    if not registry["maps"]:
        from torch.map_scanner import _SKIP_WORKSPACE_DIRS
        ws_folders = [
            d for d in os.listdir(project_dir)
            if os.path.isdir(os.path.join(project_dir, d))
            and d not in _SKIP_WORKSPACE_DIRS
            and not d.startswith(".")
        ]
        if ws_folders:
            print("  First-time setup: enrolling workspace maps...")
            count, skipped = bulk_enroll(project_dir, game_path)
            if count:
                print(f"  Enrolled {count} map(s).")
            if skipped:
                print(f"  Skipped (no game folder): {', '.join(skipped)}")
            print()

    enrolled = get_enrolled_maps(project_dir)

    if not enrolled:
        print(f"  No enrolled maps. Use 'torch enroll --all' to enroll workspace maps.")
        return False

    # Partition by state — only sync claimed maps
    by_state = get_maps_by_state(project_dir)
    claimed = set(by_state.get(STATE_CLAIMED, []))
    pristine_maps = by_state.get(STATE_PRISTINE, [])
    locked_maps = by_state.get(STATE_LOCKED, [])

    # Re-decompile pristine_stale maps
    if pristine_maps:
        from torch.bulk_decompile import re_decompile_pristine
        stale_count = 0
        for pm in pristine_maps:
            h = get_map_health(project_dir, pm, game_path)
            if h == "pristine_stale":
                try:
                    re_decompile_pristine(game_path, pm, project_dir)
                    stale_count += 1
                except Exception:
                    pass
        if stale_count:
            print(f"  Re-decompiled {stale_count} pristine map(s)")

    # Filter to claimed maps only
    enrolled = [m for m in enrolled if m in claimed]

    # Warn about unenrolled workspace folders
    unenrolled = get_unenrolled_workspace_dirs(project_dir)
    if unenrolled:
        print(f"  NOTE: {len(unenrolled)} unenrolled workspace folder(s): {', '.join(unenrolled)}")
        print(f"  (use 'torch enroll <name>' to include them)")
        print()

    if pristine_maps or locked_maps:
        parts = []
        if pristine_maps:
            parts.append(f"{len(pristine_maps)} pristine (read-only)")
        if locked_maps:
            parts.append(f"{len(locked_maps)} locked")
        print(f"  Skipping {', '.join(parts)}")

    if not enrolled:
        print(f"  No claimed maps to sync.")
        return True

    print(f"Writing {len(enrolled)} claimed map(s)...")
    print()

    written = []
    skipped = []  # (name, reason)
    failed = []
    maps_with_unmanaged = []
    for map_name in enrolled:
        health = get_map_health(project_dir, map_name, game_path)
        if health == "orphan":
            skipped.append((map_name, "orphan (no game folder)"))
            continue
        if health == "missing_workspace":
            skipped.append((map_name, "missing workspace folder"))
            continue

        # Pre-check for unmanaged content (for batch summary)
        target_path = os.path.join(game_path, "data", "maps", map_name, "scripts.pory")
        unmanaged_pre, _ = _extract_unmanaged_content(target_path)
        if unmanaged_pre:
            maps_with_unmanaged.append(map_name)

        print(f"[{map_name}]")
        if sync_map(map_name, project_dir, game_path, emotes_conf, source_display,
                    max_snapshots):
            written.append(map_name)
        else:
            failed.append(map_name)
        print()

    # Summary
    parts = []
    parts.append(f"{len(written)} written")
    if skipped:
        parts.append(f"{len(skipped)} skipped")
    if failed:
        parts.append(f"{len(failed)} failed")
    if maps_with_unmanaged:
        parts.append(f"{len(maps_with_unmanaged)} with unmanaged scripts")
    summary = f"Done: {', '.join(parts)} (of {len(enrolled)} enrolled)."
    print(summary)
    for name, reason in skipped:
        print(f"  - {name}: {reason}")
    if failed:
        print(f"  Failed: {', '.join(failed)}")
    _offer_build(game_path, trigger="sync", safe=True, auto_build=_get_auto_build_setting())


def restore_map(map_name, project_dir, game_path, emotes_conf, source_display,
                max_snapshots=10, snapshot_idx=None):
    """Restore workspace and game scripts from a snapshot.
    If snapshot_idx is given (0-based), skip the interactive menu."""
    source_dir = os.path.join(project_dir, map_name)
    snapshot_dir = os.path.join(source_dir, "backups", "snapshots")
    overwritten_dir = os.path.join(source_dir, "backups", "overwritten")

    if not os.path.isdir(snapshot_dir):
        print(f"  No snapshots found for {map_name}.")
        return

    # List available snapshots (newest first)
    prefix = f"{map_name}_"
    snapshots = sorted([
        f for f in os.listdir(snapshot_dir)
        if f.startswith(prefix) and f.endswith(".zip")
    ], reverse=True)

    if not snapshots:
        print(f"  No snapshots found for {map_name}.")
        return

    if snapshot_idx is not None:
        # Direct selection -- skip interactive menu
        if snapshot_idx < 0 or snapshot_idx >= len(snapshots):
            print(f"  Invalid snapshot index.")
            return
        selected = snapshots[snapshot_idx]
    else:
        # Display interactive menu
        print(f"TORCH snapshots for {map_name}:")
        print()
        for i, fname in enumerate(snapshots):
            fpath = os.path.join(snapshot_dir, fname)
            size = os.path.getsize(fpath)
            # Parse timestamp from filename
            ts = fname[len(prefix):-4]  # strip prefix and ".zip"
            try:
                dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
                display_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                display_time = ts
            # Peek inside to list files
            try:
                with zipfile.ZipFile(fpath, "r") as zf:
                    file_count = len(zf.namelist())
            except zipfile.BadZipFile:
                file_count = "?"
            print(f"  [{i + 1}] {display_time}  ({file_count} files, {size} bytes)")

        print()
        print(f"  [0] Cancel")
        print()

        try:
            choice = input("Restore which snapshot? ")
            choice = int(choice)
        except (ValueError, EOFError):
            print("Cancelled.")
            return

        if choice == 0:
            print("Cancelled.")
            return

        if choice < 1 or choice > len(snapshots):
            print("Invalid choice.")
            return

        selected = snapshots[choice - 1]
    selected_path = os.path.join(snapshot_dir, selected)

    # Show what will be restored
    with zipfile.ZipFile(selected_path, "r") as zf:
        restoring_files = sorted(zf.namelist())
    current_files = get_workspace_files(source_dir)

    print()
    print(f"Restoring {len(restoring_files)} files: {', '.join(restoring_files)}")

    # Show diff summary
    restoring_set = set(restoring_files)
    current_set = set(current_files)
    added = restoring_set - current_set
    removed = current_set - restoring_set
    kept = restoring_set & current_set
    if added:
        print(f"  Returning:  {', '.join(sorted(added))}")
    if removed:
        print(f"  Removing:   {', '.join(sorted(removed))}")
    if kept:
        print(f"  Replacing:  {', '.join(sorted(kept))}")
    print()

    # ---- Safety swap: save broken state ----
    os.makedirs(overwritten_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    broken_name = f"{map_name}_BROKEN_{timestamp}.zip"
    broken_path = os.path.join(overwritten_dir, broken_name)

    # Save current state (the one we're about to replace)
    if current_files:
        with zipfile.ZipFile(broken_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in current_files:
                zf.write(os.path.join(source_dir, fname), fname)
        # Keep only the latest broken zip (single rolling)
        for f in os.listdir(overwritten_dir):
            if f.endswith(".zip") and f != broken_name:
                os.remove(os.path.join(overwritten_dir, f))
        print(f"  Saved current state -> backups/overwritten/{broken_name}")

    # ---- Wipe and restore ----
    try:
        # Wipe current workspace files
        for fname in current_files:
            os.remove(os.path.join(source_dir, fname))

        # Unzip snapshot into workspace
        with zipfile.ZipFile(selected_path, "r") as zf:
            zf.extractall(source_dir)

    except Exception as e:
        # Atomic rollback: if unzip fails, restore the broken state
        print(f"  ERROR during restore: {e}")
        print(f"  Rolling back...")
        if os.path.exists(broken_path):
            # Wipe any partial restore
            for fname in get_workspace_files(source_dir):
                os.remove(os.path.join(source_dir, fname))
            with zipfile.ZipFile(broken_path, "r") as zf:
                zf.extractall(source_dir)
            print(f"  Rollback complete. Workspace unchanged.")
        return

    print(f"  Workspace restored from snapshot.")

    # ---- Check if battle format migration happened since this snapshot ----
    fmt = _detect_trainer_format(game_path)
    if fmt == "party":
        migration_backup_dir = os.path.join(game_path, "backups", "migrations")
        if os.path.isdir(migration_backup_dir):
            backups = sorted([
                f for f in os.listdir(migration_backup_dir)
                if f.startswith("pre_migration_") and f.endswith(".zip")
            ])
            if backups:
                print()
                print("  NOTE: A battle format migration (.h -> .party) has")
                print("  occurred since this snapshot was taken.")
                print()
                undo = input("  Undo migration too? [y/N] > ").strip().lower()
                if undo == "y":
                    from torch.battle_migrator import _restore_migration_backup
                    latest_path = os.path.join(migration_backup_dir, backups[-1])
                    restored = _restore_migration_backup(game_path, latest_path)
                    if restored is not None:
                        print("  Migration undone. Files restored:")
                        for r in restored:
                            print(f"    {r}")
                        print()
                        print("  WARNING: A rebuild is required after migration undo.")

    # ---- Auto-sync to push restored state to game ----
    print()
    print(f"  Auto-syncing to game folder...")
    if sync_map(map_name, project_dir, game_path, emotes_conf, source_display,
                max_snapshots):
        print()
        print(f"  Restore complete.")
        _offer_build(game_path, trigger="restore", safe=True, auto_build=_get_auto_build_setting())
