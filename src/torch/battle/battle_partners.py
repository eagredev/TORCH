"""Battle partner manager — list, add, edit, remove partner definitions."""
# TORCH_MODULE: Battle Partners
# TORCH_GROUP: Trainers
import os
import re

from torch.config import SETTINGS_DEFAULTS, _nav_keys, DIVIDER
from torch.colours import GOLD, WHITE, CYAN, GREEN, DIM, RST, BAR, BOLD_RED
from torch.ui import print_logo, _k, clear_screen
from torch.expansion_compat import (
    detect_expansion_version, requires_version, version_str,
    FOLLOWER_NPC_PARTNERS,
)
from torch.names import (
    _const_to_human_name, _human_name_to_const,
    _ai_flags_to_party_format, _party_ai_to_const,
)


# ============================================================
# VANILLA PARTNERS — never delete these
# ============================================================

_VANILLA_PARTNERS = {"PARTNER_NONE", "PARTNER_STEVEN"}


def _is_custom_partner(const_name):
    """Returns True if not in the vanilla partner set."""
    return const_name not in _VANILLA_PARTNERS


# ============================================================
# FILE PATHS
# ============================================================

def _partner_header_path(game_path):
    return os.path.join(game_path, "include", "constants", "battle_partner.h")


def _partner_party_path(game_path):
    return os.path.join(game_path, "src", "data", "battle_partners.party")


def _follower_config_path(game_path):
    return os.path.join(game_path, "include", "config", "follower_npc.h")


# ============================================================
# PARTNER I/O — read constants and party data
# ============================================================

def _read_partner_constants(game_path):
    """Parse battle_partner.h -> list of (name, id) tuples.

    Returns: [("PARTNER_NONE", 0), ("PARTNER_STEVEN", 1), ...]
    Excludes PARTNER_COUNT.
    """
    path = _partner_header_path(game_path)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return []
    results = []
    for m in re.finditer(r"^#define\s+(PARTNER_\w+)\s+(\d+)", content, re.MULTILINE):
        name = m.group(1)
        if name == "PARTNER_COUNT":
            continue
        results.append((name, int(m.group(2))))
    results.sort(key=lambda x: x[1])
    return results


def _read_partner_count(game_path):
    """Read PARTNER_COUNT from battle_partner.h -> int or None."""
    path = _partner_header_path(game_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None
    m = re.search(r"^#define\s+PARTNER_COUNT\s+(\d+)", content, re.MULTILINE)
    return int(m.group(1)) if m else None


def _read_all_partners(game_path):
    """Read battle_partners.party using battle_io parser.

    Returns: list of record dicts (same format as trainer records).
    """
    from torch.battle_io import _read_party_file, _parse_party_section
    path = _partner_party_path(game_path)
    if not os.path.isfile(path):
        return []
    sections = _read_party_file(path)
    records = []
    for const_name, raw_text in sections.items():
        record = _parse_party_section(raw_text, const_name)
        records.append(record)
    return records


# ============================================================
# HEADER FILE OPERATIONS
# ============================================================

def _insert_partner_constant(game_path, const_name):
    """Add #define PARTNER_X N before PARTNER_COUNT, bump count.

    Returns: assigned ID (int) or None on error.
    """
    path = _partner_header_path(game_path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        print(f"  Error reading {path}: {e}")
        return None

    # Find current PARTNER_COUNT
    m = re.search(r"^(#define\s+PARTNER_COUNT\s+)(\d+)", content, re.MULTILINE)
    if not m:
        print("  Error: PARTNER_COUNT not found in battle_partner.h")
        return None

    current_count = int(m.group(2))
    new_id = current_count
    new_count = current_count + 1

    # Insert the new define before PARTNER_COUNT line
    new_define = f"#define {const_name} {new_id}\n"
    insert_pos = m.start()
    new_content = content[:insert_pos] + new_define + content[insert_pos:]

    # Update PARTNER_COUNT (it's shifted by len(new_define))
    new_content = re.sub(
        r"^(#define\s+PARTNER_COUNT\s+)\d+",
        f"\\g<1>{new_count}",
        new_content,
        count=1,
        flags=re.MULTILINE,
    )

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except OSError as e:
        print(f"  Error writing {path}: {e}")
        return None

    return new_id


def _remove_partner_constant(game_path, const_name):
    """Remove #define and decrement PARTNER_COUNT.

    Returns: True on success, False on error.
    """
    path = _partner_header_path(game_path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        print(f"  Error reading {path}: {e}")
        return False

    # Remove the #define line
    pattern = r"^#define\s+" + re.escape(const_name) + r"\s+\d+\s*\n?"
    new_content, n = re.subn(pattern, "", content, count=1, flags=re.MULTILINE)
    if n == 0:
        print(f"  Warning: {const_name} not found in battle_partner.h")
        return False

    # Decrement PARTNER_COUNT
    m = re.search(r"^(#define\s+PARTNER_COUNT\s+)(\d+)", new_content, re.MULTILINE)
    if m:
        new_count = max(0, int(m.group(2)) - 1)
        new_content = re.sub(
            r"^(#define\s+PARTNER_COUNT\s+)\d+",
            f"\\g<1>{new_count}",
            new_content,
            count=1,
            flags=re.MULTILINE,
        )

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except OSError as e:
        print(f"  Error writing {path}: {e}")
        return False

    return True


# ============================================================
# PARTNER PICKER — reusable by beat prompts
# ============================================================

def pick_partner(game_path):
    """Partner picker — numbered list of defined partners.

    Returns: PARTNER_* constant string or None.
    """
    constants = _read_partner_constants(game_path)
    if not constants:
        print("  No partners defined.")
        return None

    print()
    for i, (name, pid) in enumerate(constants):
        vanilla_tag = f" {DIM}(vanilla){RST}" if not _is_custom_partner(name) else ""
        print(f"    {GOLD}[{i}]{RST} {name}{vanilla_tag}")
    print()
    raw = input("  Partner > ").strip()
    if not raw:
        return None
    if raw.startswith("PARTNER_"):
        # Direct constant input
        for name, _ in constants:
            if name == raw:
                return name
        print(f"  Unknown partner: {raw}")
        return None
    if raw.isdigit():
        idx = int(raw)
        if 0 <= idx < len(constants):
            return constants[idx][0]
    print("  Invalid selection.")
    return None


# ============================================================
# CONFIG TOGGLE GATE — check/enable follower NPCs
# ============================================================

def _check_follower_config(game_path):
    """Check if FNPC_ENABLE_NPC_FOLLOWERS is TRUE.

    If FALSE, offer to enable it with save-compat warning.
    Returns True if enabled (or just enabled), False if user declined.
    """
    config_path = _follower_config_path(game_path)
    if not os.path.isfile(config_path):
        print("  Warning: follower_npc.h not found. Follower NPCs may not be available.")
        return False

    try:
        with open(config_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        print("  Error reading follower config.")
        return False

    m = re.search(r"^(#define\s+FNPC_ENABLE_NPC_FOLLOWERS\s+)(TRUE|FALSE)",
                  content, re.MULTILINE)
    if not m:
        print("  Warning: FNPC_ENABLE_NPC_FOLLOWERS not found in config.")
        return False

    if m.group(2) == "TRUE":
        return True

    # It's FALSE — prompt to enable
    print()
    print("  NPC Followers are currently disabled in your project.")
    print()
    print("  Enabling this feature changes the save format -- existing save files")
    print("  will not be compatible. This is fine for development (you can always")
    print("  start a new save), but be aware of it.")
    print()
    choice = input("  Enable NPC followers? [y/n] > ").strip().lower()
    if choice != "y":
        return False

    # Flip FALSE to TRUE
    new_content = content[:m.start(2)] + "TRUE" + content[m.end(2):]
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except OSError as e:
        print(f"  Error writing config: {e}")
        return False

    print()
    print(f"  {GREEN}NPC Followers enabled.{RST}")
    print()
    print("  Recommended settings (in include/config/follower_npc.h):")
    print("    FNPC_FLAG_PARTNER_WILD_BATTLES = FNPC_ALWAYS")
    print("      (partner joins wild battles too -- good for story segments)")
    print("    FNPC_FLAG_HEAL_AFTER_FOLLOWER_BATTLE = FNPC_ALWAYS")
    print("      (auto-heal after every battle -- prevents getting stuck)")
    print("    FNPC_NPC_FOLLOWER_PARTY_PREVIEW = TRUE")
    print("      (shows both teams before trainer battles)")
    print()
    print("  You can change these anytime in the config file.")
    print()
    return True


# ============================================================
# PARTNER CRUD — Add / Edit / Remove
# ============================================================

def _prompt_partner_party():
    """Prompt for partner Pokemon one at a time. Returns list of mon dicts."""
    print()
    print("  PARTY SETUP")
    print("  Enter Pokemon one at a time. Empty species to finish.")
    print()
    mons = []
    while True:
        species_raw = input(f"  Pokemon #{len(mons)+1} species (or Enter to finish): ").strip()
        if not species_raw:
            break
        species = _human_name_to_const(species_raw.title(), "SPECIES_")
        level_raw = input(f"    Level: ").strip()
        level = int(level_raw) if level_raw.isdigit() else 50

        print("    Moves (up to 4, empty to skip):")
        moves = []
        for mi in range(4):
            move_raw = input(f"      Move {mi+1}: ").strip()
            if not move_raw:
                break
            moves.append(_human_name_to_const(move_raw.replace(" ", "_").title(), "MOVE_"))

        mons.append({
            "species": species, "level": level, "moves": moves,
            "held_item": None, "ability": None, "ivs": None, "evs": None,
            "nature": None, "gender": None, "shiny": None, "ball": None,
            "nickname": None, "happiness": None, "tera_type": None,
            "dynamax_level": None, "gigantamax": None, "extra_fields": [],
        })
    return mons


def _add_partner(game_path, expansion_version=None):
    """Wizard flow to create a new battle partner.

    Returns: partner constant name (str) or None on cancel.
    """
    from torch.battle_io import _serialize_party_trainer, _append_trainer_to_party_file
    from torch.battle_wizard import (
        _ai_flags_menu, pick_encounter_music, pick_trainer_sprite,
        _parse_defines,
    )

    print()
    print("  NEW BATTLE PARTNER")
    print(BAR)

    # 1. Name
    name = input("  Partner name: ").strip().upper()
    if not name:
        return None
    const_name = f"PARTNER_{name.replace(' ', '_')}"

    # Check for duplicates
    existing = _read_partner_constants(game_path)
    for ename, _ in existing:
        if ename == const_name:
            print(f"  Error: {const_name} already exists.")
            return None

    # 2. Trainer class
    constants_dir = os.path.join(game_path, "include", "constants")
    config_dir = os.path.join(game_path, "include", "config")
    classes = _parse_defines(
        os.path.join(constants_dir, "trainers.h"), "TRAINER_CLASS_"
    )
    print()
    class_input = input("  Trainer class (e.g. Psychic): ").strip()
    if not class_input:
        class_input = "Pkmn Trainer 1"
    trainer_class = _human_name_to_const(class_input, "TRAINER_CLASS_")

    # 3. Trainer pic
    print()
    pic_input = input("  Trainer pic (e.g. Sabrina): ").strip()
    if not pic_input:
        pic_input = name.capitalize()
    trainer_pic = _human_name_to_const(pic_input, "TRAINER_PIC_")

    # 4. Back pic
    print()
    back_pic_input = input(f"  Back pic [{pic_input}]: ").strip()
    if not back_pic_input:
        back_pic_input = pic_input
    back_pic = back_pic_input

    # 5. Gender
    print()
    print("  Gender: [1] Male  [2] Female")
    gender_choice = input("  > ").strip()
    gender = "Female" if gender_choice == "2" else "Male"

    # 6. Music
    print()
    music_input = input(f"  Encounter music [{gender}]: ").strip()
    if not music_input:
        music_input = gender
    encounter_music = _human_name_to_const(music_input, "TRAINER_ENCOUNTER_MUSIC_")
    if gender == "Female":
        encounter_music = f"F_TRAINER_FEMALE | {encounter_music}"

    # 7. AI
    print()
    print("  AI level: [1] Basic  [2] Smart  [3] Expert")
    ai_choice = input("  > ").strip()
    if ai_choice == "3":
        ai_flags = "AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT | AI_FLAG_CHECK_VIABILITY | AI_FLAG_SMART_SWITCHING | AI_FLAG_ACE_POKEMON | AI_FLAG_OMNISCIENT"
    elif ai_choice == "2":
        ai_flags = "AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT | AI_FLAG_CHECK_VIABILITY"
    else:
        ai_flags = "AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT"

    # 8. Party
    mons = _prompt_partner_party()

    if not mons:
        print("  No Pokemon added. Partner creation cancelled.")
        return None

    # Build record
    record = {
        "trainer_const": const_name,
        "trainer_id": None,
        "trainer_class": trainer_class,
        "encounter_music": encounter_music,
        "trainer_pic": trainer_pic,
        "trainer_name": name,
        "is_double": False,
        "ai_flags": ai_flags,
        "party_const": None,
        "mons": mons,
        "trainer_items": None,
        "mugshot": None,
        "back_pic": back_pic,
        "starting_status": None,
        "header_extra": [],
    }

    # Write to files
    partner_id = _insert_partner_constant(game_path, const_name)
    if partner_id is None:
        return None

    party_path = _partner_party_path(game_path)
    success = _append_trainer_to_party_file(party_path, record, expansion_version)
    if not success:
        print("  Error writing partner to .party file.")
        # Rollback the constant
        _remove_partner_constant(game_path, const_name)
        return None

    print()
    print(f"  {GREEN}Created {const_name} (ID {partner_id}){RST}")
    print(f"  Added party to battle_partners.party")
    print()
    return const_name


def _edit_partner(game_path, partner_const, expansion_version=None):
    """Edit an existing partner's party.

    Uses battle_io._replace_trainer_in_party_file() for the .party file.
    """
    from torch.battle_io import (
        _read_party_file, _parse_party_section,
        _serialize_party_trainer, _replace_trainer_in_party_file,
    )

    party_path = _partner_party_path(game_path)
    sections = _read_party_file(party_path)
    if partner_const not in sections:
        print(f"  {partner_const} not found in battle_partners.party")
        return

    record = _parse_party_section(sections[partner_const], partner_const)

    print()
    print(f"  Editing {partner_const}")
    print(BAR)
    print(f"  Name: {record.get('trainer_name', '?')}")
    print(f"  Class: {_const_to_human_name(record.get('trainer_class', ''), 'TRAINER_CLASS_')}")
    print(f"  Mons: {len(record.get('mons', []))}")
    print()
    print(f"  [1] Edit name  [2] Edit AI  [3] Edit party  [q] Back")
    choice = input("  > ").strip()

    if choice == "1":
        new_name = input("  New name: ").strip().upper()
        if new_name:
            record["trainer_name"] = new_name
    elif choice == "2":
        print("  AI level: [1] Basic  [2] Smart  [3] Expert")
        ai_choice = input("  > ").strip()
        if ai_choice == "3":
            record["ai_flags"] = "AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT | AI_FLAG_CHECK_VIABILITY | AI_FLAG_SMART_SWITCHING | AI_FLAG_ACE_POKEMON | AI_FLAG_OMNISCIENT"
        elif ai_choice == "2":
            record["ai_flags"] = "AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT | AI_FLAG_CHECK_VIABILITY"
        else:
            record["ai_flags"] = "AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT"
    elif choice == "3":
        print("  (Replacing entire party)")
        mons = []
        while True:
            species_raw = input(f"  Pokemon #{len(mons)+1} species (Enter to finish): ").strip()
            if not species_raw:
                break
            species = _human_name_to_const(species_raw.title(), "SPECIES_")
            level_raw = input(f"    Level: ").strip()
            level = int(level_raw) if level_raw.isdigit() else 50
            moves = []
            for mi in range(4):
                move_raw = input(f"      Move {mi+1}: ").strip()
                if not move_raw:
                    break
                moves.append(_human_name_to_const(move_raw.replace(" ", "_").title(), "MOVE_"))
            mons.append({
                "species": species, "level": level, "moves": moves,
                "held_item": None, "ability": None, "ivs": None, "evs": None,
                "nature": None, "gender": None, "shiny": None, "ball": None,
                "nickname": None, "happiness": None, "tera_type": None,
                "dynamax_level": None, "gigantamax": None, "extra_fields": [],
            })
        if mons:
            record["mons"] = mons
    else:
        return

    success = _replace_trainer_in_party_file(party_path, partner_const, record, expansion_version)
    if success:
        print(f"  {GREEN}Updated {partner_const}{RST}")
    else:
        print(f"  Error updating partner.")


def _remove_partner(game_path, partner_const):
    """Remove a custom partner.

    Returns: True on success, False on error.
    """
    from torch.battle_io import _delete_from_party_file

    if not _is_custom_partner(partner_const):
        print(f"  Cannot remove vanilla partner {partner_const}.")
        return False

    print()
    print(f"  {BOLD_RED}Remove {partner_const}?{RST}")
    print("  This will delete the partner from both battle_partner.h and battle_partners.party.")
    confirm = input("  Type 'yes' to confirm: ").strip().lower()
    if confirm != "yes":
        print("  Cancelled.")
        return False

    # Remove from .party file
    party_path = _partner_party_path(game_path)
    if os.path.isfile(party_path):
        _delete_from_party_file(party_path, partner_const)

    # Remove from header
    success = _remove_partner_constant(game_path, partner_const)
    if success:
        print(f"  {GREEN}Removed {partner_const}{RST}")
    return success


# ============================================================
# PARTNER MENU — embedded in battle_manager
# ============================================================

def _partner_card(game_path, partner_const, expansion_version=None):
    """Display a partner card with edit/remove options for custom partners."""
    from torch.battle_io import _read_party_file, _parse_party_section
    from torch.names import (
        _const_to_species_name, _const_to_move_name,
    )

    party_path = _partner_party_path(game_path)
    sections = _read_party_file(party_path)
    if partner_const not in sections:
        print(f"  {partner_const} not found.")
        input("  Press Enter > ")
        return

    record = _parse_party_section(sections[partner_const], partner_const)

    clear_screen()
    print()
    print(f"  {WHITE}{partner_const}{RST}")
    print(BAR)
    print(f"  Name:     {record.get('trainer_name', '?')}")
    print(f"  Class:    {_const_to_human_name(record.get('trainer_class', ''), 'TRAINER_CLASS_')}")
    print(f"  Pic:      {_const_to_human_name(record.get('trainer_pic', ''), 'TRAINER_PIC_')}")
    back_pic = record.get("back_pic")
    if back_pic:
        print(f"  Back Pic: {back_pic}")
    ai = record.get("ai_flags", "")
    if ai:
        ai_display = _ai_flags_to_party_format(ai)
        print(f"  AI:       {ai_display}")
    print()

    mons = record.get("mons", [])
    for j, mon in enumerate(mons):
        species = _const_to_species_name(mon.get("species", "?"))
        level = mon.get("level", "?")
        moves = [_const_to_move_name(m) for m in mon.get("moves", [])]
        moves_str = " / ".join(moves) if moves else "no moves"
        print(f"  {CYAN}{species}{RST} Lv.{level}  {DIM}{moves_str}{RST}")

    print()
    is_custom = _is_custom_partner(partner_const)
    if is_custom:
        print(f"  {_k('e')} {DIM}Edit{RST}   {_k('d')} {DIM}Delete{RST}   {_k('q')} {DIM}Back{RST}")
    else:
        print(f"  {DIM}(vanilla partner -- read only){RST}")
        print(f"  {_k('q')} {DIM}Back{RST}")
    print()
    choice = input(f"  {GOLD}>{RST} ").strip().lower()

    if is_custom and choice == "e":
        _edit_partner(game_path, partner_const, expansion_version)
    elif is_custom and choice == "d":
        _remove_partner(game_path, partner_const)


def partner_menu(game_path, expansion_version=None, settings=None, proj_name=None):
    """Battle Partners sub-menu — list, add, edit/remove partners."""
    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)

    while True:
        clear_screen()
        constants = _read_partner_constants(game_path)
        records = _read_all_partners(game_path)

        # Build a quick party summary per partner
        party_summaries = {}
        for rec in records:
            const = rec.get("trainer_const", "")
            mons = rec.get("mons", [])
            if mons:
                from torch.names import _const_to_species_name
                names = [_const_to_species_name(m.get("species", "?")) for m in mons[:3]]
                summary = " / ".join(names)
                if len(mons) > 3:
                    summary += f" +{len(mons)-3}"
                party_summaries[const] = summary
            else:
                party_summaries[const] = "(no party)"

        print()
        print_logo("Battle Partners", proj_name)
        print(BAR)

        for i, (name, pid) in enumerate(constants):
            vanilla_tag = f" {DIM}(vanilla){RST}" if not _is_custom_partner(name) else ""
            party_info = party_summaries.get(name, "")
            if name == "PARTNER_NONE":
                print(f"    {GOLD}[{i}]{RST} {name:<25} {DIM}(placeholder){RST}")
            else:
                print(f"    {GOLD}[{i}]{RST} {name:<25} {DIM}{party_info}{RST}{vanilla_tag}")

        print()
        print(f"  {_k('n')} {DIM}New partner{RST}   {_k('q')} {DIM}Back{RST}")
        print()
        choice = input(f"  {GOLD}>{RST} ").strip().lower()

        if choice == "q" or choice == "":
            return

        if choice == "n":
            _add_partner(game_path, expansion_version)
            continue

        # Numeric selection — open partner card
        if choice.isdigit():
            idx = int(choice)
            if 0 <= idx < len(constants):
                _partner_card(game_path, constants[idx][0], expansion_version)
            continue
