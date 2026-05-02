"""Name conversion utilities and format detection for TORCH."""
# TORCH_MODULE: Name Utils
# TORCH_GROUP: Core
import os
import re


# Known acronyms/abbreviations that should stay uppercase in title-casing
_ACRONYMS = {"RS", "HP", "AI", "EV", "IV", "HM", "TM", "PP", "XD"}


def _smart_title(text):
    """Title-case but preserve known acronyms."""
    return " ".join(
        word if word in _ACRONYMS else word.capitalize()
        for word in text.split(" ")
    )


# ============================================================
# BATTLE MANAGER — FORMAT DETECTION & NAME CONVERSION
# ============================================================

def _detect_trainer_format(game_path):
    """Detect whether the project uses trainers.party (new) or .h files (legacy)."""
    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    return "party" if os.path.exists(party_path) else "legacy"


def _detect_project_variant(game_path):
    """Detect whether the project is pokeemerald-expansion or vanilla pokeemerald.

    Returns 'expansion' or 'vanilla'. The definitive marker is
    include/constants/expansion.h, which only exists in the expansion fork.
    """
    expansion_marker = os.path.join(game_path, "include", "constants", "expansion.h")
    return "expansion" if os.path.exists(expansion_marker) else "vanilla"


# --- Stat spread parsing ---

_STAT_ABBREVS = {"HP": "hp", "Atk": "atk", "Def": "def",
                 "SpA": "spatk", "SpD": "spdef", "Spe": "spe"}
_STAT_ORDER = ["hp", "atk", "def", "spatk", "spdef", "spe"]
_STAT_LABELS = {"hp": "HP", "atk": "Atk", "def": "Def",
                "spatk": "SpA", "spdef": "SpD", "spe": "Spe"}


def _parse_stat_spread(text):
    """Parse '252 HP / 128 Spe' -> {'hp': 252, 'spe': 128}."""
    result = {}
    for part in text.split("/"):
        part = part.strip()
        m = re.match(r"(\d+)\s+(\w+)", part)
        if m:
            val = int(m.group(1))
            abbr = m.group(2)
            key = _STAT_ABBREVS.get(abbr, abbr.lower())
            result[key] = val
    return result if result else None


def _format_stat_spread(stats):
    """Reverse: {'hp': 252, 'spe': 128} -> '252 HP / 128 Spe'."""
    if not stats:
        return ""
    parts = []
    for key in _STAT_ORDER:
        if key in stats:
            parts.append(f"{stats[key]} {_STAT_LABELS[key]}")
    return " / ".join(parts)


def _format_stat_spread_full(stats, default=0):
    """Format all 6 stats: '31 HP / 31 Atk / 31 Def / 31 SpA / 31 SpD / 31 Spe'."""
    parts = []
    for key in _STAT_ORDER:
        val = stats.get(key, default) if stats else default
        parts.append(f"{val} {_STAT_LABELS[key]}")
    return " / ".join(parts)


# --- Name conversion (C constants <-> human-readable .party names) ---

def _const_to_human_name(const, prefix):
    """Strip prefix, replace _ with space, title-case.
    TRAINER_CLASS_TEAM_ROCKET -> 'Team Rocket'
    """
    if not const:
        return ""
    name = const
    if name.startswith(prefix):
        name = name[len(prefix):]
    return _smart_title(name.replace("_", " "))


def _human_name_to_const(name, prefix):
    """Reverse: 'Team Rocket' -> 'TRAINER_CLASS_TEAM_ROCKET'."""
    if not name:
        return ""
    return prefix + name.strip().upper().replace(" ", "_").replace("-", "_")


def _const_to_species_name(const):
    """SPECIES_GEODUDE -> 'Geodude', SPECIES_MR_MIME -> 'Mr. Mime'."""
    if not const:
        return ""
    name = const.replace("SPECIES_", "", 1) if const.startswith("SPECIES_") else const
    # Special cases for species with periods/special chars
    name = _smart_title(name.replace("_", " "))
    # Common multi-word species fixups
    name = name.replace("Mr ", "Mr. ").replace("Ms ", "Ms. ").replace("Jr ", "Jr. ")
    return name


def _const_to_move_name(const):
    """MOVE_AIR_SLASH -> 'Air Slash'."""
    if not const:
        return ""
    name = const.replace("MOVE_", "", 1) if const.startswith("MOVE_") else const
    return _smart_title(name.replace("_", " "))


def _const_to_item_name(const):
    """ITEM_FULL_RESTORE -> 'Full Restore'."""
    if not const:
        return ""
    name = const.replace("ITEM_", "", 1) if const.startswith("ITEM_") else const
    return _smart_title(name.replace("_", " "))


def _const_to_ability_name(const):
    """ABILITY_INTIMIDATE -> 'Intimidate'."""
    if not const:
        return ""
    name = const.replace("ABILITY_", "", 1) if const.startswith("ABILITY_") else const
    return _smart_title(name.replace("_", " "))


def _const_to_nature_name(const):
    """NATURE_ADAMANT -> 'Adamant'."""
    if not const:
        return ""
    name = const.replace("NATURE_", "", 1) if const.startswith("NATURE_") else const
    return _smart_title(name.replace("_", " "))


def _const_to_ball_name(const, use_pokeball_enum=False):
    """Convert ball constant to human name.

    Pre-1.15: ITEM_ULTRA_BALL -> 'Ultra Ball' (Item enum)
    v1.15+:   BALL_ULTRA -> 'Ultra' (Pokeball enum)
    """
    if not const:
        return ""
    if use_pokeball_enum:
        name = const.replace("BALL_", "", 1) if const.startswith("BALL_") else const
        return _smart_title(name.replace("_", " "))
    return _const_to_item_name(const)


def _ai_flags_to_party_format(c_flags):
    """'AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT' -> 'Check Bad Move / Try To Faint'."""
    if not c_flags or c_flags.strip() == "0":
        return ""
    parts = [p.strip() for p in c_flags.split("|") if p.strip()]
    human = []
    for p in parts:
        name = p.replace("AI_FLAG_", "", 1) if p.startswith("AI_FLAG_") else p
        human.append(_smart_title(name.replace("_", " ")))
    return " / ".join(human)


def _party_ai_to_const(party_flags):
    """'Check Bad Move / Try To Faint' -> 'AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT'."""
    if not party_flags:
        return ""
    parts = [p.strip() for p in party_flags.split("/") if p.strip()]
    consts = []
    for p in parts:
        consts.append("AI_FLAG_" + p.upper().replace(" ", "_").replace("-", "_"))
    return " | ".join(consts)


def _party_gender_to_const(gender_str):
    """Convert .party gender field to encounterMusic_gender constant.
    'Male' -> 'TRAINER_ENCOUNTER_MUSIC_MALE', 'Female' -> 'F_TRAINER_FEMALE'
    The gender in .party is the trainer gender, not music. We handle both.
    """
    if not gender_str:
        return None
    g = gender_str.strip().lower()
    if g in ("f", "female"):
        return "F_TRAINER_FEMALE"
    return None  # Male is default (no flag)
