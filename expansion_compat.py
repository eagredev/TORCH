"""Expansion version detection and feature compatibility.

Provides shared version parsing (refactored from upgrade.py) and a
feature registry so TORCH modules can gate behaviour based on the
user's pokeemerald-expansion version.

Usage:
    from torch.expansion_compat import (
        detect_expansion_version, version_str, parse_version_str,
        requires_version, check_feature,
    )
"""
# TORCH_MODULE: Expansion Compat
# TORCH_GROUP: Core

import os
import re

# ============================================================
# VERSION DETECTION
# ============================================================

def detect_expansion_version(game_path):
    """Parse include/constants/expansion.h for version defines.

    Returns (major, minor, patch) tuple, or None if not found/parseable.
    """
    header = os.path.join(game_path, "include", "constants", "expansion.h")
    if not os.path.isfile(header):
        return None
    try:
        with open(header, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None
    major = re.search(r"#define\s+EXPANSION_VERSION_MAJOR\s+(\d+)", content)
    minor = re.search(r"#define\s+EXPANSION_VERSION_MINOR\s+(\d+)", content)
    patch = re.search(r"#define\s+EXPANSION_VERSION_PATCH\s+(\d+)", content)
    if not (major and minor and patch):
        return None
    return (int(major.group(1)), int(minor.group(1)), int(patch.group(1)))


def version_str(version_tuple):
    """Convert (1, 7, 4) to '1.7.4'."""
    return f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"


def parse_version_str(s):
    """Convert '1.7.4' to (1, 7, 4). Returns None on invalid input."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", s.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


# ============================================================
# VERSION COMPARISON
# ============================================================

def requires_version(current, minimum):
    """Check if current version meets minimum requirement.

    current: (major, minor, patch) tuple or None
    minimum: (major, minor, patch) tuple
    Returns True if current >= minimum, False otherwise.
    Returns False if current is None (unknown version).
    """
    if current is None:
        return False
    return current >= minimum


# ============================================================
# FEATURE REGISTRY — named version thresholds for TORCH features
# ============================================================

# Trainer system
PARTY_FORMAT = (1, 9, 0)                   # .party trainer format introduced
TRAINER_BATTLE_CONSOLIDATED = (1, 11, 0)    # trainerbattle param consolidation
TRAINER_PARTY_POOLS = (1, 11, 0)            # Pooled trainer parties
AI_FLAGS_U64 = (1, 12, 0)                   # AI flags expanded to u64
FOLLOWER_NPC_PARTNERS = (1, 12, 0)          # Follower NPC partner battles
POKEMON_OBJECT_EVENTS = (1, 9, 0)           # OBJ_EVENT_GFX_SPECIES() macro for Pokemon NPCs

# Encounter system
TIME_BASED_ENCOUNTERS = (1, 12, 0)          # Time-of-day encounter tables

# Asset pipeline
SMOL_COMPRESSION = (1, 13, 0)              # LZ77 -> smol sprite compression
TRAINER_BACK_PIC = (1, 13, 0)              # trainerBackPic field added
TM_ITEM_SPLIT = (1, 13, 0)                # TMs untangled from item IDs

# Build system
MAKE_RELEASE = (1, 14, 0)                  # make release for release builds

# Move/item refactors
VS_SEEKER_REFACTOR = (1, 14, 0)            # vsseeker_rematchid macro
MOVESET_REFACTOR = (1, 14, 0)              # teachingType replaces tmIlliterate

# Battle type availability
BATTLE_TYPE_MULTI = (1, 11, 0)             # SET_TRAINERS_FOR_MULTI_BATTLE
BATTLE_TYPE_TWO_TRAINERS_NO_INTRO = (1, 11, 0)  # type 13 added

# Region system
REGIONS_KANTO_MAPSEC_REF = (1, 15, 0)      # regions.h references KANTO_MAPSEC_START

# v1.15 — Trainer / data format changes
TRAINER_BALL_ENUM = (1, 15, 0)             # .party Ball: uses Pokeball enum, not Item enum
TRAINER_PIC_ENUM = (1, 15, 0)              # TRAINER_PIC_ defines -> enum TrainerPicID
TEACHABLE_LEARNSET_JSON = (1, 15, 0)       # teachable_learnsets.h auto-generated from all_learnables.json
STARTING_STATUS_SYSTEM = (1, 15, 0)        # setstartingstatus replaces B_VAR_STARTING_STATUS

# v1.15 — Overworld / scripting
INGAME_TRADE_MACRO = (1, 15, 0)            # ingame_trade macro for NPC trades
MOVE_TUTOR_MACRO = (1, 15, 0)              # move_tutor macro with optional one-time flag
FRLG_BUILD = (1, 15, 0)                    # make firered / make leafgreen support

# Minimum supported version
MIN_SUPPORTED = (1, 6, 0)


# ============================================================
# CONVENIENCE
# ============================================================

def check_feature(game_path, feature_version, feature_name=None):
    """Check if a feature is available for the project's expansion version.

    Returns True if available.
    If not available and feature_name is provided, prints a message:
        "  {feature_name} requires expansion v{version}+ (you have v{current})."
    """
    current = detect_expansion_version(game_path)
    available = requires_version(current, feature_version)
    if not available and feature_name:
        cur = version_str(current) if current else "unknown"
        req = version_str(feature_version)
        print(f"  {feature_name} requires expansion v{req}+ (you have v{cur}).")
    return available
