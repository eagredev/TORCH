"""Trainer card display, species abilities, reference scanner, ID operations."""
# TORCH_MODULE: Trainer Card
# TORCH_GROUP: Trainers
import os
import re
import glob as _glob
from datetime import datetime

from torch.ui import (
    _fmt_class, _fmt_music, _fmt_sprite, _fmt_ai_flags,
    _truncate_dialogue, _fmt_const_name, _k, clear_screen,
)
from torch.names import (
    _const_to_species_name, _const_to_move_name, _const_to_item_name,
    _const_to_ability_name, _const_to_nature_name, _const_to_ball_name,
    _format_stat_spread, _ai_flags_to_party_format,
)
from torch.battle_io import _read_pory_dialogue
from torch.colours import GOLD, WHITE, CYAN, GREEN, DIM, RST, BAR


def _display_trainer_card(record, map_folder, dialogue, ability_names=None, move_names=None, fmt=None):
    """Print redesigned trainer card with two-column layout and human-readable names."""
    clear_screen()
    if ability_names is None:
        ability_names = {}
    if move_names is None:
        move_names = {}

    SEP = f"  {DIM}" + "\u2500" * 49 + RST
    def _lv(label, value): return f"  {_k(label[0])} {DIM}{label[1:]}{RST} {CYAN}{value}{RST}"

    tid = record["trainer_id"]
    name_val   = record['trainer_name'] or '?'
    class_val  = _fmt_class(record['trainer_class'])

    print()
    print(BAR)
    print(f"   {WHITE}{name_val}{RST}  {DIM}\u2014{RST}  {CYAN}{class_val}{RST}")
    print(BAR)
    print()

    # Two-column layout for fields 1-6
    music_val  = _fmt_music(record['encounter_music'])
    sprite_val = _fmt_sprite(record['trainer_pic'])
    battle_val = 'Double' if record['is_double'] else 'Single'
    ai_val     = _fmt_ai_flags(record['ai_flags'])

    print(f"  {_k(1)} {DIM}Name  :{RST} {WHITE}{name_val:<18}{RST}  {_k(2)} {DIM}Class  :{RST} {CYAN}{class_val}{RST}")
    print(f"  {_k(3)} {DIM}Music :{RST} {CYAN}{music_val:<18}{RST}  {_k(4)} {DIM}Sprite :{RST} {CYAN}{sprite_val}{RST}")
    print(f"  {_k(5)} {DIM}Battle:{RST} {CYAN}{battle_val:<18}{RST}  {_k(6)} {DIM}AI     :{RST} {CYAN}{ai_val}{RST}")

    # Trainer bag items (party format only)
    if fmt == "party" and record.get("trainer_items"):
        items_display = ", ".join(_const_to_item_name(it) for it in record["trainer_items"])
        print(f"  {_k(9)} {DIM}Items :{RST} {CYAN}{items_display}{RST}")
    elif fmt == "party":
        print(f"  {_k(9)} {DIM}Items :{RST} {DIM}(none){RST}")

    print()
    print(SEP)

    # Party
    party_count = len(record["mons"]) if record["mons"] else 0
    print(f"  {_k(7)} {DIM}Party ({party_count} Pokemon){RST}")
    if record["mons"]:
        for i, mon in enumerate(record["mons"], 1):
            species_name = _fmt_const_name(mon["species"], {})
            shiny_mark = f"{GOLD}\u2605 {RST}" if mon.get("shiny") else ""
            ab_part = ""
            if mon.get("ability"):
                ab_part = f"  {DIM}[{_fmt_const_name(mon['ability'], ability_names)}]{RST}"
            item_part = ""
            if mon.get("held_item"):
                item_part = f" {DIM}@ {_fmt_const_name(mon['held_item'], {})}{RST}"
            print(f"      {DIM}{i}.{RST} {shiny_mark}{WHITE}{species_name}{RST} {DIM}lv.{mon['level']}{RST}{item_part}{ab_part}")
            if mon.get("moves"):
                moves_display = ", ".join(_fmt_const_name(mv, move_names) for mv in mon["moves"])
                print(f"         {DIM}{moves_display}{RST}")
    else:
        print(f"      {DIM}(none){RST}")
    print()
    print(SEP)

    # Dialogue
    print(f"  {_k(8)} {DIM}Dialogue{RST}")
    intro_preview = _truncate_dialogue(dialogue.get("intro"))
    defeat_preview = _truncate_dialogue(dialogue.get("defeat"))
    print(f"      {DIM}Intro:{RST}  {intro_preview}")
    print(f"      {DIM}Defeat:{RST} {defeat_preview}")
    if dialogue.get("not_enough"):
        ne_preview = _truncate_dialogue(dialogue["not_enough"])
        print(f"      {DIM}NotEnough:{RST} {ne_preview}")
    print()

    # Footer
    tid_str = f"ID: {tid}" if tid is not None else "ID: unknown"
    print(f"  {DIM}{record['trainer_const']}  ({tid_str})  Map: {map_folder}{RST}")
    print(BAR)


def _patch_trainers_h_field(trainers_h_path, trainer_const, field_key, new_value):
    """
    Find the [TRAINER_CONST] = { ... }, block in trainers.h and replace one field line.
    field_key is the C field name (e.g. 'trainerName', 'trainerClass').
    new_value is the full RHS string (e.g. '_(\"BUSTER\")' or 'TRAINER_CLASS_TEAM_ROCKET').
    """
    with open(trainers_h_path) as f:
        content = f.read()

    block_pattern = (
        r"(\[" + re.escape(trainer_const) + r"\]\s*=\s*\n\s*\{)"
        r"(.*?)"
        r"(\n\s*\},)"
    )
    m = re.search(block_pattern, content, re.DOTALL)
    if not m:
        print(f"  ERROR: Could not find [{trainer_const}] block in trainers.h")
        return False

    block_start = m.group(1)
    block_body = m.group(2)
    block_end = m.group(3)

    # Replace the field line within the block body
    field_pattern = r"(\." + re.escape(field_key) + r"\s*=\s*)([^,\n]+)"
    new_body, count = re.subn(field_pattern, r"\g<1>" + new_value, block_body)
    if count == 0:
        print(f"  ERROR: Could not find field '.{field_key}' in [{trainer_const}] block")
        return False

    new_content = content[:m.start()] + block_start + new_body + block_end + content[m.end():]
    with open(trainers_h_path, "w") as f:
        f.write(new_content)
    return True


def _replace_party(trainer_parties_path, party_const, new_mons):
    """
    Replace the existing party array block in trainer_parties.h with new_mons.
    new_mons is a list of dicts: {species, level, held_item, moves, ability}
    """
    # Lazy import to avoid circular dependency
    from torch.battle_wizard import _emit_mon_block_lines

    with open(trainer_parties_path) as f:
        content = f.read()

    pattern = (
        r"static\s+const\s+struct\s+TrainerMon\s+" + re.escape(party_const)
        + r"\[\]\s*=\s*\{.*?\};"
    )
    m = re.search(pattern, content, re.DOTALL)
    if not m:
        print(f"  ERROR: Could not find party array '{party_const}' in trainer_parties.h")
        return False

    # Build the replacement block using shared helper
    block_lines = []
    block_lines.append(f"static const struct TrainerMon {party_const}[] = {{\n")
    for i, mon in enumerate(new_mons):
        block_lines.extend(_emit_mon_block_lines(mon, i == len(new_mons) - 1))
    block_lines.append("};")
    new_block = "".join(block_lines)

    new_content = content[:m.start()] + new_block + content[m.end():]
    with open(trainer_parties_path, "w") as f:
        f.write(new_content)
    return True


def _parse_species_abilities(species_const, game_path):
    """
    Parse the .abilities = { A, B, C } line for the given species from species_info files.
    Returns a list of unique, non-NONE ability constants (strings).
    Returns [] if not found or on error.
    """
    if not game_path:
        return []
    pokemon_data_dir = os.path.join(game_path, "src", "data", "pokemon")
    if not os.path.isdir(pokemon_data_dir):
        return []

    # Normalize: ensure it starts with SPECIES_
    if not species_const.upper().startswith("SPECIES_"):
        species_const = "SPECIES_" + species_const.upper()
    else:
        species_const = species_const.upper()

    # Walk all .h files in pokemon_data_dir looking for [SPECIES_CONST] blocks
    abilities_pattern = re.compile(r'\.abilities\s*=\s*\{([^}]+)\}')
    species_header_pattern = re.compile(r'\[' + re.escape(species_const) + r'\]')

    for fname in os.listdir(pokemon_data_dir):
        if not fname.endswith(".h"):
            continue
        fpath = os.path.join(pokemon_data_dir, fname)
        try:
            with open(fpath) as f:
                content = f.read()
        except OSError:
            continue
        if species_const not in content:
            continue
        # Also check subdirectory files
        pass

    # Broader search including subdirs
    results = []
    for root, dirs, files in os.walk(pokemon_data_dir):
        dirs[:] = [d for d in dirs if d not in (".git",)]
        for fname in files:
            if not fname.endswith(".h"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath) as f:
                    content = f.read()
            except OSError:
                continue
            if species_const not in content:
                continue
            # Find the species block and extract abilities
            # Pattern: [SPECIES_X] = \n { ... .abilities = {...} ... }
            block_pattern = re.compile(
                r'\[' + re.escape(species_const) + r'\]\s*=\s*\{(.*?)\n\}',
                re.DOTALL
            )
            for bm in block_pattern.finditer(content):
                block = bm.group(1)
                am = abilities_pattern.search(block)
                if am:
                    raw = [x.strip() for x in am.group(1).split(",") if x.strip()]
                    for ab in raw:
                        if ab and ab != "ABILITY_NONE" and ab not in results:
                            results.append(ab)
            if results:
                return results

    return results


def _scan_all_references(trainer_const, game_path):
    """
    Grep entire game project for trainer_const string.
    Returns list of dicts: {file, line_num, line_text, category}
    """
    refs = []
    opponents_rel = os.path.join("include", "constants", "opponents.h")
    trainers_rel = os.path.join("src", "data", "trainers.h")
    parties_rel = os.path.join("src", "data", "trainer_parties.h")
    party_file_rel = os.path.join("src", "data", "trainers.party")
    flags_rel = os.path.join("include", "constants", "flags.h")

    for dirpath, dirnames, filenames in os.walk(game_path):
        # Skip .git and build dirs
        dirnames[:] = [d for d in dirnames if d not in (".git", "build")]
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, game_path)
            try:
                with open(fpath, "r", errors="ignore") as f:
                    for line_num, line_text in enumerate(f, 1):
                        if trainer_const in line_text:
                            # Categorize
                            if rel == opponents_rel:
                                cat = "opponents.h"
                            elif rel == trainers_rel:
                                cat = "trainers.h"
                            elif rel == parties_rel:
                                cat = "trainer_parties.h"
                            elif rel == party_file_rel:
                                cat = "trainers.party"
                            elif rel == flags_rel:
                                cat = "flag_define"
                            elif fname in ("scripts.pory", "scripts.inc"):
                                cat = "map_script"
                            else:
                                cat = "other"
                            refs.append({
                                "file": rel,
                                "line_num": line_num,
                                "line_text": line_text.rstrip(),
                                "category": cat,
                            })
            except (OSError, UnicodeDecodeError):
                continue
    return refs


def _write_deletion_report(trainer_const, record, refs, auto_cleaned, workspace_expanded):
    """
    Write a detailed deletion report to config/deletion_reports/.
    auto_cleaned: list of (category_label, description) for items already removed.
    Returns the report file path.
    """
    reports_dir = os.path.join(workspace_expanded, "config", "deletion_reports")
    os.makedirs(reports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_name = f"{trainer_const}_{ts}.txt"
    report_path = os.path.join(reports_dir, report_name)

    trainer_id = record.get("trainer_id", "?")
    trainer_name = record.get("trainer_name", "?")

    lines = []
    lines.append("TORCH Deletion Report")
    lines.append("=" * 50)
    lines.append(f'Trainer: {trainer_const}  (ID: {trainer_id}, Name: "{trainer_name}")')
    lines.append(f"Deleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Report: {report_path}")
    lines.append("")

    lines.append("AUTO-CLEANED (already removed by TORCH):")
    for label, desc in auto_cleaned:
        lines.append(f"  {label:<20}: {desc}")
    lines.append("")

    # Group manual refs by file
    manual_refs = [r for r in refs if r["category"] not in ("opponents.h", "trainers.h", "trainer_parties.h", "trainers.party")]
    # Also exclude workspace .pory refs
    manual_refs = [r for r in manual_refs if not r["file"].startswith("battle_")]

    if manual_refs:
        lines.append("MANUAL CLEANUP REQUIRED:")
        lines.append("  These references still exist in your game files and must be fixed by hand.")
        lines.append("")

        by_file = {}
        for r in manual_refs:
            by_file.setdefault(r["file"], []).append(r)

        for fpath in sorted(by_file.keys()):
            lines.append(f"  {fpath}")
            for r in by_file[fpath]:
                lines.append(f"    Line {r['line_num']}: {r['line_text'].strip()}")
                # Add guidance based on category
                if r["category"] == "map_script":
                    if "trainerbattle" in r["line_text"].lower():
                        lines.append("      -> Remove or replace this trainerbattle line and its surrounding script logic.")
                    elif "setflag" in r["line_text"].lower() or "checkflag" in r["line_text"].lower():
                        lines.append("      -> This flag may track beating this trainer. Remove if no longer needed.")
                    elif "applymovement" in r["line_text"].lower():
                        lines.append("      -> References the trainer's NPC. Update or remove.")
                    else:
                        lines.append("      -> Review and update or remove this reference.")
                elif r["category"] == "flag_define":
                    lines.append("      -> Remove this flag define if no longer needed.")
                else:
                    lines.append("      -> Review and update or remove this reference.")
            lines.append("")

        # Note about .inc files
        has_inc = any(r["file"].endswith(".inc") for r in manual_refs)
        if has_inc:
            lines.append("  NOTE: scripts.inc files are auto-generated. Fix the corresponding scripts.pory")
            lines.append("  and rebuild (bb) -- the .inc file will be regenerated automatically.")
            lines.append("")
    else:
        lines.append("No manual cleanup required -- all references were auto-cleaned.")
        lines.append("")

    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    return report_path


def _find_lowest_available_id(opponents_path, vanilla_threshold=854):
    """
    Find the first unused trainer ID starting from 1.
    Skips all IDs already in use. When vanilla trainers are present,
    IDs 1-854 are occupied so this naturally returns 855+.
    After Phoenix, those IDs are free so this returns 1.
    """
    used_ids = set()
    if os.path.exists(opponents_path):
        with open(opponents_path) as f:
            for line in f:
                m = re.match(r"^#define\s+TRAINER_\w+\s+(\d+)", line)
                if m:
                    tid = int(m.group(1))
                    # Skip meta-defines like TRAINERS_COUNT, MAX_TRAINERS_COUNT
                    if "TRAINERS_COUNT" not in line:
                        used_ids.add(tid)
    candidate = 1
    while candidate in used_ids:
        candidate += 1
    return candidate


def _recalculate_trainers_count(opponents_path):
    """
    Read all trainer IDs from opponents.h, set TRAINERS_COUNT = max + 1.
    Returns the new TRAINERS_COUNT value.
    """
    max_id = 0
    lines = []
    try:
        with open(opponents_path) as f:
            lines = f.readlines()
    except OSError as e:
        print(f"  ERROR: Could not read opponents.h: {e}")
        return None
    for line in lines:
        m = re.match(r"^#define\s+TRAINER_\w+\s+(\d+)", line)
        if m and "TRAINERS_COUNT" not in line and "MAX_TRAINERS_COUNT" not in line:
            tid = int(m.group(1))
            if tid > max_id:
                max_id = tid
    new_count = max_id + 1
    # Update TRAINERS_COUNT line
    new_lines = []
    for line in lines:
        if re.match(r"^#define\s+TRAINERS_COUNT\s+", line.strip()):
            new_lines.append(re.sub(r"(\d+)", str(new_count), line, count=1))
        else:
            new_lines.append(line)
    try:
        with open(opponents_path, "w") as f:
            f.writelines(new_lines)
    except OSError as e:
        print(f"  ERROR: Could not write opponents.h: {e}")
        return None
    return new_count


def _change_trainer_id(trainer_const, old_id, new_id, opponents_path):
    """
    Update a trainer's numeric ID in opponents.h.
    Returns True on success, error message string on failure.
    """
    # Validate new_id not already in use
    used_ids = {}
    with open(opponents_path) as f:
        lines = f.readlines()
    for line in lines:
        m = re.match(r"^#define\s+(TRAINER_\w+)\s+(\d+)", line)
        if m and "TRAINERS_COUNT" not in line and "MAX_TRAINERS_COUNT" not in line:
            used_ids[int(m.group(2))] = m.group(1)

    if new_id in used_ids:
        return f"ID {new_id} is already used by {used_ids[new_id]}"
    if new_id < 1:
        return "ID must be at least 1"

    # Check MAX_TRAINERS_COUNT
    max_trainers = None
    for line in lines:
        m2 = re.match(r"^#define\s+MAX_TRAINERS_COUNT\s+(\d+)", line.strip())
        if m2:
            max_trainers = int(m2.group(1))
    if max_trainers and new_id >= max_trainers:
        return f"ID {new_id} is at or above MAX_TRAINERS_COUNT ({max_trainers})"

    # Update the #define line
    new_lines = []
    found = False
    for line in lines:
        if re.match(r"^#define\s+" + re.escape(trainer_const) + r"\s+\d+", line):
            new_lines.append(re.sub(r"(\d+)", str(new_id), line, count=1))
            found = True
        else:
            new_lines.append(line)
    if not found:
        return f"{trainer_const} not found in opponents.h"
    with open(opponents_path, "w") as f:
        f.writelines(new_lines)
    # Recalculate TRAINERS_COUNT
    _recalculate_trainers_count(opponents_path)
    return True
