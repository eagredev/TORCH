"""Tests for learnset_editor module."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


# -- Mock file content for tests -----------------------------------------------

_MOCK_LEVEL_UP_GEN1 = """\
#define LEVEL_UP_MOVE(lvl, moveLearned) {.move = moveLearned, .level = lvl}
#define LEVEL_UP_END {.move = LEVEL_UP_MOVE_END, .level = 0}

static const struct LevelUpMove sNoneLevelUpLearnset[] = {
    LEVEL_UP_MOVE(1, MOVE_POUND),
    LEVEL_UP_END
};

#if P_FAMILY_BULBASAUR
static const struct LevelUpMove sBulbasaurLevelUpLearnset[] = {
    LEVEL_UP_MOVE( 1, MOVE_TACKLE),
    LEVEL_UP_MOVE( 1, MOVE_GROWL),
    LEVEL_UP_MOVE( 7, MOVE_LEECH_SEED),
    LEVEL_UP_MOVE(13, MOVE_VINE_WHIP),
    LEVEL_UP_MOVE(20, MOVE_POISON_POWDER),
    LEVEL_UP_END
};

static const struct LevelUpMove sIvysaurLevelUpLearnset[] = {
    LEVEL_UP_MOVE( 1, MOVE_TACKLE),
    LEVEL_UP_MOVE( 1, MOVE_GROWL),
    LEVEL_UP_MOVE(13, MOVE_VINE_WHIP),
    LEVEL_UP_END
};
#endif //P_FAMILY_BULBASAUR
"""

_MOCK_EGG_MOVES = """\
#include "constants/moves.h"

static const u16 sNoneEggMoveLearnset[] = {
    MOVE_UNAVAILABLE,
};

#if P_FAMILY_BULBASAUR
static const u16 sBulbasaurEggMoveLearnset[] = {
    MOVE_SKULL_BASH,
    MOVE_CHARM,
    MOVE_PETAL_DANCE,
    MOVE_UNAVAILABLE,
};
#endif //P_FAMILY_BULBASAUR

#if P_FAMILY_CHARMANDER
static const u16 sCharmanderEggMoveLearnset[] = {
    MOVE_BELLY_DRUM,
    MOVE_ANCIENT_POWER,
    MOVE_UNAVAILABLE,
};
#endif //P_FAMILY_CHARMANDER
"""

_MOCK_TEACHABLE = """\
// DO NOT MODIFY THIS FILE! It is auto-generated.

static const u16 sBulbasaurTeachableLearnset[] = {
    MOVE_ATTRACT,
    MOVE_BODY_SLAM,
    MOVE_TOXIC,
    MOVE_UNAVAILABLE,
};

static const u16 sCharmanderTeachableLearnset[] = {
    MOVE_FIRE_PUNCH,
    MOVE_UNAVAILABLE,
};
"""

_MOCK_SPECIES_H = """\
#define SPECIES_NONE 0
#define SPECIES_BULBASAUR 1
#define SPECIES_IVYSAUR 2
#define SPECIES_CHARMANDER 4
#define SPECIES_EGG 412
"""

_MOCK_MOVES_H = """\
#define MOVE_NONE 0
#define MOVE_TACKLE 1
#define MOVE_GROWL 2
#define MOVE_LEECH_SEED 3
#define MOVE_VINE_WHIP 4
#define MOVE_POISON_POWDER 5
#define MOVE_SKULL_BASH 6
#define MOVE_CHARM 7
#define MOVE_PETAL_DANCE 8
#define MOVE_BELLY_DRUM 9
#define MOVE_ANCIENT_POWER 10
#define MOVE_ATTRACT 11
#define MOVE_BODY_SLAM 12
#define MOVE_TOXIC 13
#define MOVE_FIRE_PUNCH 14
#define MOVE_SOLAR_BEAM 15
#define MOVE_UNAVAILABLE 0xFFFF
"""


def _make_mock_game(tmpdir):
    """Create a minimal mock game directory structure."""
    # Level-up learnsets
    lu_dir = os.path.join(tmpdir, "src", "data", "pokemon", "level_up_learnsets")
    os.makedirs(lu_dir, exist_ok=True)
    with open(os.path.join(lu_dir, "gen_1.h"), "w") as f:
        f.write(_MOCK_LEVEL_UP_GEN1)

    # Egg moves
    egg_dir = os.path.join(tmpdir, "src", "data", "pokemon")
    with open(os.path.join(egg_dir, "egg_moves.h"), "w") as f:
        f.write(_MOCK_EGG_MOVES)

    # Teachable learnsets
    with open(os.path.join(egg_dir, "teachable_learnsets.h"), "w") as f:
        f.write(_MOCK_TEACHABLE)

    # Species header
    inc_dir = os.path.join(tmpdir, "include", "constants")
    os.makedirs(inc_dir, exist_ok=True)
    with open(os.path.join(inc_dir, "species.h"), "w") as f:
        f.write(_MOCK_SPECIES_H)

    # Moves header
    with open(os.path.join(inc_dir, "moves.h"), "w") as f:
        f.write(_MOCK_MOVES_H)

    # Expansion header (so version gate passes)
    with open(os.path.join(inc_dir, "expansion.h"), "w") as f:
        f.write("#define EXPANSION_VERSION_MAJOR 1\n")
        f.write("#define EXPANSION_VERSION_MINOR 14\n")
        f.write("#define EXPANSION_VERSION_PATCH 0\n")

    return tmpdir


def run_suite():
    _begin_suite("learnset_editor")

    from torch.learnset_editor import (
        _format_move_name, _species_display, _species_to_array_name,
        _find_level_up_file, _parse_level_up_learnset, _parse_egg_moves,
        _parse_teachable_learnset, _format_level_up_array, _format_egg_move_array,
        _write_level_up_learnset, _write_egg_moves,
        _find_named_array_bounds, _ARRAY_END,
    )

    # ---- Format helpers ----

    _assert("format_move_name basic",
            _format_move_name("MOVE_VINE_WHIP") == "Vine Whip",
            f"got {_format_move_name('MOVE_VINE_WHIP')!r}")

    _assert("format_move_name single word",
            _format_move_name("MOVE_TACKLE") == "Tackle",
            f"got {_format_move_name('MOVE_TACKLE')!r}")

    _assert("format_move_name empty",
            _format_move_name("") == "",
            f"got {_format_move_name('')!r}")

    _assert("species_display",
            _species_display("SPECIES_BULBASAUR") == "Bulbasaur",
            f"got {_species_display('SPECIES_BULBASAUR')!r}")

    _assert("species_to_array_name simple",
            _species_to_array_name("SPECIES_BULBASAUR") == "Bulbasaur",
            f"got {_species_to_array_name('SPECIES_BULBASAUR')!r}")

    _assert("species_to_array_name multi-word",
            _species_to_array_name("SPECIES_MR_MIME") == "MrMime",
            f"got {_species_to_array_name('SPECIES_MR_MIME')!r}")

    # ---- Parser tests (using mock files) ----

    tmpdir = tempfile.mkdtemp(prefix="torch_test_learnset_")
    try:
        game_path = _make_mock_game(tmpdir)

        # find_level_up_file
        lu_path = _find_level_up_file(game_path, "Bulbasaur")
        _assert("find_level_up_file found",
                lu_path is not None and lu_path.endswith("gen_1.h"),
                f"got {lu_path!r}")

        lu_path_missing = _find_level_up_file(game_path, "Pikachu")
        _assert("find_level_up_file not found",
                lu_path_missing is None,
                f"got {lu_path_missing!r}")

        # parse_level_up_learnset
        with open(lu_path, encoding="utf-8") as f:
            lu_lines = f.readlines()

        moves = _parse_level_up_learnset(lu_lines, "Bulbasaur")
        _assert("parse_level_up count",
                len(moves) == 5,
                f"expected 5, got {len(moves)}")

        _assert("parse_level_up first move",
                moves[0] == (1, "MOVE_TACKLE"),
                f"got {moves[0]!r}")

        _assert("parse_level_up last move",
                moves[-1] == (20, "MOVE_POISON_POWDER"),
                f"got {moves[-1]!r}")

        # parse_level_up for Ivysaur (different species in same file)
        iv_moves = _parse_level_up_learnset(lu_lines, "Ivysaur")
        _assert("parse_level_up Ivysaur count",
                len(iv_moves) == 3,
                f"expected 3, got {len(iv_moves)}")

        # parse_level_up for nonexistent species
        none_moves = _parse_level_up_learnset(lu_lines, "Pikachu")
        _assert("parse_level_up nonexistent",
                len(none_moves) == 0,
                f"expected 0, got {len(none_moves)}")

        # parse_egg_moves
        egg = _parse_egg_moves(game_path, "Bulbasaur")
        _assert("parse_egg_moves count",
                len(egg) == 3,
                f"expected 3, got {len(egg)}")
        _assert("parse_egg_moves content",
                egg == ["MOVE_SKULL_BASH", "MOVE_CHARM", "MOVE_PETAL_DANCE"],
                f"got {egg!r}")

        # parse_egg_moves for species with no egg moves
        egg_none = _parse_egg_moves(game_path, "Ivysaur")
        _assert("parse_egg_moves no entry",
                len(egg_none) == 0,
                f"expected 0, got {len(egg_none)}")

        # parse_teachable_learnset (read-only)
        teach = _parse_teachable_learnset(game_path, "Bulbasaur")
        _assert("parse_teachable count",
                len(teach) == 3,
                f"expected 3, got {len(teach)}")
        _assert("parse_teachable content",
                teach == ["MOVE_ATTRACT", "MOVE_BODY_SLAM", "MOVE_TOXIC"],
                f"got {teach!r}")

        # ---- Editor logic tests ----

        # Add move to level-up list and verify sort
        lu_edit = list(moves)
        lu_edit.append((5, "MOVE_SOLAR_BEAM"))
        lu_edit.sort(key=lambda x: (x[0], x[1]))
        _assert("add level-up move sorted",
                lu_edit[2] == (5, "MOVE_SOLAR_BEAM"),
                f"expected (5, MOVE_SOLAR_BEAM) at index 2, got {lu_edit[2]!r}")

        # Delete move from level-up list
        lu_del = list(moves)
        removed = lu_del.pop(0)
        _assert("delete level-up move",
                removed == (1, "MOVE_TACKLE") and len(lu_del) == 4,
                f"removed {removed!r}, remaining {len(lu_del)}")

        # Edit level on existing move
        lu_lvl = list(moves)
        lu_lvl[2] = (99, lu_lvl[2][1])
        lu_lvl.sort(key=lambda x: (x[0], x[1]))
        _assert("edit level re-sorts",
                lu_lvl[-1] == (99, "MOVE_LEECH_SEED"),
                f"last entry {lu_lvl[-1]!r}")

        # Replace move
        lu_rep = list(moves)
        lu_rep[0] = (lu_rep[0][0], "MOVE_SOLAR_BEAM")
        _assert("replace move",
                lu_rep[0] == (1, "MOVE_SOLAR_BEAM"),
                f"got {lu_rep[0]!r}")

        # Add egg move
        egg_edit = list(egg)
        egg_edit.append("MOVE_SOLAR_BEAM")
        _assert("add egg move",
                len(egg_edit) == 4 and egg_edit[-1] == "MOVE_SOLAR_BEAM",
                f"got {egg_edit!r}")

        # Delete egg move
        egg_del = list(egg)
        egg_del.pop(1)
        _assert("delete egg move",
                len(egg_del) == 2 and "MOVE_CHARM" not in egg_del,
                f"got {egg_del!r}")

        # ---- Write-back tests ----

        # Write level-up learnset
        new_lu = [(1, "MOVE_TACKLE"), (7, "MOVE_VINE_WHIP"), (15, "MOVE_SOLAR_BEAM")]
        ok = _write_level_up_learnset(game_path, "Bulbasaur", new_lu)
        _assert("write_level_up success", ok, "write returned False")

        # Verify written file
        with open(lu_path, encoding="utf-8") as f:
            written = f.read()
        _assert("write_level_up format",
                "LEVEL_UP_MOVE( 1, MOVE_TACKLE)" in written
                and "LEVEL_UP_MOVE( 7, MOVE_VINE_WHIP)" in written
                and "LEVEL_UP_MOVE(15, MOVE_SOLAR_BEAM)" in written
                and "LEVEL_UP_END" in written,
                "reconstructed array has wrong format")

        # Verify Ivysaur array is unchanged
        _assert("write_level_up other species intact",
                "sIvysaurLevelUpLearnset" in written
                and "MOVE_GROWL" in written,
                "Ivysaur array was corrupted")

        # Write egg moves
        new_egg = ["MOVE_CHARM", "MOVE_SOLAR_BEAM"]
        ok = _write_egg_moves(game_path, "Bulbasaur", new_egg)
        _assert("write_egg_moves success", ok, "write returned False")

        # Verify written egg file
        egg_path = os.path.join(game_path, "src", "data", "pokemon", "egg_moves.h")
        with open(egg_path, encoding="utf-8") as f:
            egg_written = f.read()
        _assert("write_egg_moves format",
                "MOVE_CHARM," in egg_written
                and "MOVE_SOLAR_BEAM," in egg_written
                and "MOVE_UNAVAILABLE," in egg_written,
                "reconstructed egg array has wrong format")

        # Verify Charmander egg moves untouched
        _assert("write_egg_moves other species intact",
                "sCharmanderEggMoveLearnset" in egg_written
                and "MOVE_BELLY_DRUM" in egg_written,
                "Charmander egg moves were corrupted")

        # Array bounds detection
        import re
        pattern = re.compile(
            r'^static\s+const\s+struct\s+LevelUpMove\s+sIvysaurLevelUpLearnset\[\]\s*=\s*\{'
        )
        with open(lu_path, encoding="utf-8") as f:
            fresh_lines = f.readlines()
        start, end = _find_named_array_bounds(fresh_lines, pattern)
        _assert("array_bounds found",
                start is not None and end is not None and end > start,
                f"start={start}, end={end}")

        # Format arrays test
        formatted = _format_level_up_array("TestMon", [(5, "MOVE_TACKLE"), (1, "MOVE_GROWL")])
        joined = "".join(formatted)
        _assert("format_level_up sorted",
                joined.index("MOVE_GROWL") < joined.index("MOVE_TACKLE"),
                "level-up array not sorted by level")
        _assert("format_level_up has END",
                "LEVEL_UP_END" in joined,
                "missing LEVEL_UP_END")

        egg_fmt = _format_egg_move_array("TestMon", ["MOVE_CHARM"])
        egg_joined = "".join(egg_fmt)
        _assert("format_egg_moves has UNAVAILABLE",
                "MOVE_UNAVAILABLE" in egg_joined,
                "missing MOVE_UNAVAILABLE")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
