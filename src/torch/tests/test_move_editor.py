"""Tests for move_editor module."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


# -- Mock moves_info.h content for tests ------------------------------------

_MOCK_CONSTANTS_H = """\
#ifndef GUARD_CONSTANTS_MOVES_H
#define GUARD_CONSTANTS_MOVES_H

#define MOVE_NONE 0
#define MOVE_POUND 1
#define MOVE_FIRE_PUNCH 2
#define MOVE_ICE_BEAM 3
#define MOVE_TOXIC 4

#define MOVES_COUNT 5
#endif
"""

_MOCK_MOVES_H = """\
const struct MoveInfo gMovesInfo[MOVES_COUNT_ALL] =
{
    [MOVE_NONE] =
    {
        .name = COMPOUND_STRING("-"),
        .description = COMPOUND_STRING(""),
        .effect = EFFECT_HIT,
        .power = 0,
        .type = TYPE_NORMAL,
        .accuracy = 0,
        .pp = 0,
        .target = MOVE_TARGET_SELECTED,
        .priority = 0,
        .category = DAMAGE_CATEGORY_PHYSICAL,
        .metronomeBanned = TRUE,
        .battleAnimScript = gBattleAnimMove_None,
    },

    [MOVE_POUND] =
    {
        .name = COMPOUND_STRING("Pound"),
        .description = COMPOUND_STRING(
            "Pounds the foe with\\n"
            "forelegs or tail."),
        .effect = EFFECT_HIT,
        .power = 40,
        .type = TYPE_NORMAL,
        .accuracy = 100,
        .pp = 35,
        .target = MOVE_TARGET_SELECTED,
        .priority = 0,
        .category = DAMAGE_CATEGORY_PHYSICAL,
        .makesContact = TRUE,
        .battleAnimScript = gBattleAnimMove_Pound,
    },

    [MOVE_FIRE_PUNCH] =
    {
        .name = COMPOUND_STRING("Fire Punch"),
        .description = COMPOUND_STRING(
            "A fiery punch that may\\n"
            "burn the foe."),
        .effect = EFFECT_HIT,
        .power = 75,
        .type = TYPE_FIRE,
        .accuracy = 100,
        .pp = 15,
        .target = MOVE_TARGET_SELECTED,
        .priority = 0,
        .category = DAMAGE_CATEGORY_PHYSICAL,
        .makesContact = TRUE,
        .punchingMove = TRUE,
        .additionalEffects = ADDITIONAL_EFFECTS({
            .moveEffect = MOVE_EFFECT_BURN,
            .chance = 10,
        }),
        .battleAnimScript = gBattleAnimMove_FirePunch,
    },

    [MOVE_ICE_BEAM] =
    {
        .name = COMPOUND_STRING("Ice Beam"),
        .description = COMPOUND_STRING(
            "Fires an icy cold beam\\n"
            "that may freeze the foe."),
        .effect = EFFECT_HIT,
        .power = B_UPDATED_MOVE_DATA >= GEN_4 ? 90 : 95,
        .type = TYPE_ICE,
        .accuracy = 100,
        .pp = 10,
        .target = MOVE_TARGET_SELECTED,
        .priority = 0,
        .category = DAMAGE_CATEGORY_SPECIAL,
        .additionalEffects = ADDITIONAL_EFFECTS({
            .moveEffect = MOVE_EFFECT_FREEZE_OR_FROSTBITE,
            .chance = 10,
        }),
        .battleAnimScript = gBattleAnimMove_IceBeam,
    },

    [MOVE_TOXIC] =
    {
        .name = COMPOUND_STRING("Toxic"),
        .description = COMPOUND_STRING(
            "Poisons the foe with an\\n"
            "intensifying toxin."),
        .effect = EFFECT_TOXIC,
        .power = 0,
        .type = TYPE_POISON,
        .accuracy = B_UPDATED_MOVE_DATA >= GEN_5 ? 90 : 85,
        .pp = 10,
        .target = MOVE_TARGET_SELECTED,
        .priority = 0,
        .category = DAMAGE_CATEGORY_STATUS,
        .battleAnimScript = gBattleAnimMove_Toxic,
    },
};
"""


def _make_mock_project(tmp):
    """Create a mock game project with moves_info.h, constants, etc."""
    src_data = os.path.join(tmp, "src", "data")
    inc_const = os.path.join(tmp, "include", "constants")
    os.makedirs(src_data, exist_ok=True)
    os.makedirs(inc_const, exist_ok=True)

    with open(os.path.join(src_data, "moves_info.h"), "w") as f:
        f.write(_MOCK_MOVES_H)
    with open(os.path.join(inc_const, "moves.h"), "w") as f:
        f.write(_MOCK_CONSTANTS_H)
    return tmp


def run_suite():
    """Entry point called by run_tests.py."""
    _begin_suite("Move Editor")

    try:
        from torch.move_editor import (
            parse_moves, _extract_conditional_value,
            _extract_compound_string, _extract_flags,
            _apply_filters, _write_field, _find_entry_end,
            _load_move_ids, _type_label, _category_label,
            _target_label, _cat_short, _flag_label,
            _format_description_value, _format_compound_name,
        )
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # -- Conditional value extraction --------------------------------------

    try:
        display, val = _extract_conditional_value("75")
        _assert("conditional_value: simple int", display == "75" and val == 75,
                f"got ({display}, {val})")
    except Exception as e:
        _fail("conditional_value: simple int", str(e))

    try:
        display, val = _extract_conditional_value(
            "B_UPDATED_MOVE_DATA >= GEN_4 ? 90 : 95")
        _assert("conditional_value: ternary", display == "90" and val == 90,
                f"got ({display}, {val})")
    except Exception as e:
        _fail("conditional_value: ternary", str(e))

    try:
        display, val = _extract_conditional_value("0")
        _assert("conditional_value: zero", display == "0" and val == 0,
                f"got ({display}, {val})")
    except Exception as e:
        _fail("conditional_value: zero", str(e))

    try:
        display, val = _extract_conditional_value("TYPE_FIRE")
        _assert("conditional_value: enum", display == "TYPE_FIRE" and val is None,
                f"got ({display}, {val})")
    except Exception as e:
        _fail("conditional_value: enum", str(e))

    # -- Compound string extraction ----------------------------------------

    try:
        lines = [
            '        .description = COMPOUND_STRING(\n',
            '            "Fires an icy cold beam\\n"\n',
            '            "that may freeze the foe."),\n',
        ]
        text, end_i = _extract_compound_string(lines, 0)
        _assert("compound_string: basic",
                "icy cold beam" in text and "freeze the foe" in text,
                f"got '{text}'")
    except Exception as e:
        _fail("compound_string: basic", str(e))

    # -- Label helpers -----------------------------------------------------

    try:
        _assert("type_label: TYPE_FIRE",
                _type_label("TYPE_FIRE") == "Fire")
        _assert("type_label: TYPE_NORMAL",
                _type_label("TYPE_NORMAL") == "Normal")
        _assert("type_label: TYPE_PSYCHIC",
                _type_label("TYPE_PSYCHIC") == "Psychic")
    except Exception as e:
        _fail("type_label", str(e))

    try:
        _assert("category_label: Physical",
                _category_label("DAMAGE_CATEGORY_PHYSICAL") == "Physical")
        _assert("category_label: Special",
                _category_label("DAMAGE_CATEGORY_SPECIAL") == "Special")
        _assert("category_label: Status",
                _category_label("DAMAGE_CATEGORY_STATUS") == "Status")
    except Exception as e:
        _fail("category_label", str(e))

    try:
        _assert("target_label: SELECTED",
                _target_label("MOVE_TARGET_SELECTED") == "Selected")
        _assert("target_label: USER",
                _target_label("MOVE_TARGET_USER") == "User")
        _assert("target_label: BOTH",
                _target_label("MOVE_TARGET_BOTH") == "Both Opponents")
    except Exception as e:
        _fail("target_label", str(e))

    try:
        _assert("cat_short: Physical", _cat_short("DAMAGE_CATEGORY_PHYSICAL") == "Phys")
        _assert("cat_short: Special", _cat_short("DAMAGE_CATEGORY_SPECIAL") == "Spec")
        _assert("cat_short: Status", _cat_short("DAMAGE_CATEGORY_STATUS") == "Stat")
    except Exception as e:
        _fail("cat_short", str(e))

    try:
        _assert("flag_label: makesContact",
                _flag_label("makesContact") == "Makes Contact")
        _assert("flag_label: punchingMove",
                _flag_label("punchingMove") == "Punching Move")
    except Exception as e:
        _fail("flag_label", str(e))

    # -- Name formatting ---------------------------------------------------

    try:
        result = _format_compound_name("Fire Punch")
        _assert("format_compound_name: contains COMPOUND_STRING",
                'COMPOUND_STRING("Fire Punch")' == result,
                f"got {result}")
    except Exception as e:
        _fail("format_compound_name", str(e))

    # -- Parser (mock project) ---------------------------------------------

    tmp = tempfile.mkdtemp(prefix="torch_move_test_")
    try:
        _make_mock_project(tmp)

        # Parse move IDs
        try:
            ids = _load_move_ids(tmp)
            _assert("load_move_ids: count", len(ids) >= 4,
                    f"got {len(ids)} ids")
            _assert("load_move_ids: MOVE_POUND",
                    ids.get("MOVE_POUND") == 1,
                    f"got {ids.get('MOVE_POUND')}")
        except Exception as e:
            _fail("load_move_ids", str(e))

        # Parse all moves
        try:
            moves = parse_moves(tmp)
            _assert("parse_moves: count", len(moves) == 4,
                    f"got {len(moves)} (expected 4, MOVE_NONE excluded)")
        except Exception as e:
            _fail("parse_moves: count", str(e))
            moves = []

        # Parse move names
        if moves:
            try:
                names = [mv["name"] for mv in moves]
                _assert("parse: Pound name", "Pound" in names,
                        f"names: {names}")
                _assert("parse: Fire Punch name", "Fire Punch" in names,
                        f"names: {names}")
                _assert("parse: Ice Beam name", "Ice Beam" in names,
                        f"names: {names}")
            except Exception as e:
                _fail("parse: move names", str(e))

        # Parse core fields
        if moves:
            try:
                fp = next(mv for mv in moves if mv["constant"] == "MOVE_FIRE_PUNCH")
                _assert("parse: power", fp["power"] == 75,
                        f"got {fp['power']}")
                _assert("parse: accuracy", fp["accuracy"] == 100,
                        f"got {fp['accuracy']}")
                _assert("parse: pp", fp["pp"] == 15,
                        f"got {fp['pp']}")
                _assert("parse: type", fp["type"] == "TYPE_FIRE",
                        f"got '{fp['type']}'")
                _assert("parse: category",
                        fp["category"] == "DAMAGE_CATEGORY_PHYSICAL",
                        f"got '{fp['category']}'")
                _assert("parse: priority", fp["priority"] == 0,
                        f"got {fp['priority']}")
                _assert("parse: target",
                        fp["target"] == "MOVE_TARGET_SELECTED",
                        f"got '{fp['target']}'")
            except Exception as e:
                _fail("parse: core fields", str(e))

        # Parse conditional power
        if moves:
            try:
                ib = next(mv for mv in moves if mv["constant"] == "MOVE_ICE_BEAM")
                _assert("parse: conditional power value",
                        ib["power"] == 90,
                        f"got {ib['power']}")
                _assert("parse: conditional power raw",
                        "B_UPDATED" in ib["power_raw"],
                        f"got '{ib['power_raw']}'")
            except Exception as e:
                _fail("parse: conditional power", str(e))

        # Parse ADDITIONAL_EFFECTS
        if moves:
            try:
                fp = next(mv for mv in moves if mv["constant"] == "MOVE_FIRE_PUNCH")
                _assert("parse: has_additional_effects",
                        fp["has_additional_effects"] is True,
                        f"got {fp['has_additional_effects']}")
                # Ensure entry end was found correctly (not truncated)
                _assert("parse: entry not truncated (name present)",
                        fp["name"] == "Fire Punch")
            except Exception as e:
                _fail("parse: additional_effects", str(e))

        # Parse boolean flags
        if moves:
            try:
                fp = next(mv for mv in moves if mv["constant"] == "MOVE_FIRE_PUNCH")
                _assert("parse: flags contain makesContact",
                        "makesContact" in fp["flags"],
                        f"got {fp['flags']}")
                _assert("parse: flags contain punchingMove",
                        "punchingMove" in fp["flags"],
                        f"got {fp['flags']}")
            except Exception as e:
                _fail("parse: flags", str(e))

        # Handle MOVE_NONE exclusion
        if moves:
            try:
                none_moves = [mv for mv in moves if mv["constant"] == "MOVE_NONE"]
                _assert("parse: MOVE_NONE excluded",
                        len(none_moves) == 0,
                        f"got {len(none_moves)} MOVE_NONE entries")
            except Exception as e:
                _fail("parse: MOVE_NONE", str(e))

        # Parse description
        if moves:
            try:
                pd = next(mv for mv in moves if mv["constant"] == "MOVE_POUND")
                _assert("parse: description contains text",
                        "forelegs" in pd["description"],
                        f"got '{pd['description']}'")
            except Exception as e:
                _fail("parse: description", str(e))

        # Parse status move (power = 0, STATUS category)
        if moves:
            try:
                tx = next(mv for mv in moves if mv["constant"] == "MOVE_TOXIC")
                _assert("parse: status move power", tx["power"] == 0,
                        f"got {tx['power']}")
                _assert("parse: status category",
                        tx["category"] == "DAMAGE_CATEGORY_STATUS",
                        f"got '{tx['category']}'")
                _assert("parse: status type",
                        tx["type"] == "TYPE_POISON",
                        f"got '{tx['type']}'")
            except Exception as e:
                _fail("parse: status move", str(e))

        # -- Filter tests --------------------------------------------------

        if moves:
            try:
                phys = _apply_filters(moves, "", "DAMAGE_CATEGORY_PHYSICAL", "")
                _assert("filter: category Physical",
                        len(phys) == 2,
                        f"got {len(phys)}")
                _assert("filter: all Physical",
                        all(mv["category"] == "DAMAGE_CATEGORY_PHYSICAL"
                            for mv in phys))
            except Exception as e:
                _fail("filter: category", str(e))

            try:
                fire = _apply_filters(moves, "", "", "TYPE_FIRE")
                _assert("filter: type Fire",
                        len(fire) == 1 and fire[0]["constant"] == "MOVE_FIRE_PUNCH",
                        f"got {len(fire)} moves")
            except Exception as e:
                _fail("filter: type", str(e))

            try:
                searched = _apply_filters(moves, "punch", "", "")
                _assert("filter: search 'punch'",
                        len(searched) == 1 and searched[0]["name"] == "Fire Punch",
                        f"got {len(searched)} moves")
            except Exception as e:
                _fail("filter: search name", str(e))

            try:
                searched = _apply_filters(moves, "ICE_BEAM", "", "")
                _assert("filter: search constant",
                        len(searched) == 1
                        and searched[0]["constant"] == "MOVE_ICE_BEAM",
                        f"got {len(searched)} moves")
            except Exception as e:
                _fail("filter: search constant", str(e))

            try:
                combined = _apply_filters(moves, "punch",
                                          "DAMAGE_CATEGORY_PHYSICAL", "")
                _assert("filter: combined category + search",
                        len(combined) == 1,
                        f"got {len(combined)} moves")
            except Exception as e:
                _fail("filter: combined", str(e))

        # -- Write tests ---------------------------------------------------

        # Write power
        if moves:
            try:
                pd = next(mv for mv in parse_moves(tmp)
                          if mv["constant"] == "MOVE_POUND")
                ok = _write_field(tmp, pd, "power", "60")
                _assert("write: power success", ok)
                moves2 = parse_moves(tmp)
                pd2 = next(mv for mv in moves2 if mv["constant"] == "MOVE_POUND")
                _assert("write: power persisted",
                        pd2["power"] == 60,
                        f"got {pd2['power']}")
                _write_field(tmp, pd2, "power", "40")
            except Exception as e:
                _fail("write: power", str(e))

        # Write type
        if moves:
            try:
                pd = next(mv for mv in parse_moves(tmp)
                          if mv["constant"] == "MOVE_POUND")
                ok = _write_field(tmp, pd, "type", "TYPE_FIGHTING")
                _assert("write: type success", ok)
                moves2 = parse_moves(tmp)
                pd2 = next(mv for mv in moves2 if mv["constant"] == "MOVE_POUND")
                _assert("write: type persisted",
                        pd2["type"] == "TYPE_FIGHTING",
                        f"got '{pd2['type']}'")
                _write_field(tmp, pd2, "type", "TYPE_NORMAL")
            except Exception as e:
                _fail("write: type", str(e))

        # Write name
        if moves:
            try:
                pd = next(mv for mv in parse_moves(tmp)
                          if mv["constant"] == "MOVE_POUND")
                ok = _write_field(tmp, pd, "name", "Slam")
                _assert("write: name success", ok)
                moves2 = parse_moves(tmp)
                pd2 = next(mv for mv in moves2 if mv["constant"] == "MOVE_POUND")
                _assert("write: name persisted",
                        pd2["name"] == "Slam",
                        f"got '{pd2['name']}'")
                _write_field(tmp, pd2, "name", "Pound")
            except Exception as e:
                _fail("write: name", str(e))

        # Write description
        if moves:
            try:
                pd = next(mv for mv in parse_moves(tmp)
                          if mv["constant"] == "MOVE_POUND")
                ok = _write_field(tmp, pd, "description",
                                  "A new test description.")
                _assert("write: description success", ok)
                moves2 = parse_moves(tmp)
                pd2 = next(mv for mv in moves2 if mv["constant"] == "MOVE_POUND")
                _assert("write: description persisted",
                        "new test description" in pd2["description"],
                        f"got '{pd2['description']}'")
            except Exception as e:
                _fail("write: description", str(e))

        # Preserve conditional expression on non-edited field
        if moves:
            try:
                ib = next(mv for mv in parse_moves(tmp)
                          if mv["constant"] == "MOVE_ICE_BEAM")
                ok = _write_field(tmp, ib, "pp", "15")
                _assert("write: pp success", ok)
                moves2 = parse_moves(tmp)
                ib2 = next(mv for mv in moves2 if mv["constant"] == "MOVE_ICE_BEAM")
                _assert("write: conditional power preserved",
                        "B_UPDATED" in ib2["power_raw"],
                        f"power became '{ib2['power_raw']}'")
                _assert("write: pp changed",
                        ib2["pp"] == 15,
                        f"got {ib2['pp']}")
            except Exception as e:
                _fail("write: preserve conditional", str(e))

        # Preserve ADDITIONAL_EFFECTS block
        if moves:
            try:
                fp = next(mv for mv in parse_moves(tmp)
                          if mv["constant"] == "MOVE_FIRE_PUNCH")
                ok = _write_field(tmp, fp, "power", "80")
                _assert("write: power with effects success", ok)
                moves2 = parse_moves(tmp)
                fp2 = next(mv for mv in moves2
                           if mv["constant"] == "MOVE_FIRE_PUNCH")
                _assert("write: additional_effects preserved",
                        fp2["has_additional_effects"] is True,
                        "additional effects lost")
                _assert("write: power updated with effects",
                        fp2["power"] == 80,
                        f"got {fp2['power']}")
            except Exception as e:
                _fail("write: preserve additional_effects", str(e))

        # Preserve surrounding entries when editing
        if moves:
            try:
                moves_before = parse_moves(tmp)
                fp = next(mv for mv in moves_before
                          if mv["constant"] == "MOVE_FIRE_PUNCH")
                _write_field(tmp, fp, "name", "Blaze Punch")
                moves_after = parse_moves(tmp)
                # Check that other moves are unchanged
                pd_before = next(mv for mv in moves_before
                                 if mv["constant"] == "MOVE_POUND")
                pd_after = next(mv for mv in moves_after
                                if mv["constant"] == "MOVE_POUND")
                _assert("write: surrounding entries preserved (name)",
                        pd_before["name"] == pd_after["name"],
                        f"Pound name changed: {pd_before['name']} -> {pd_after['name']}")
                ib_before = next(mv for mv in moves_before
                                 if mv["constant"] == "MOVE_ICE_BEAM")
                ib_after = next(mv for mv in moves_after
                                if mv["constant"] == "MOVE_ICE_BEAM")
                _assert("write: surrounding entries preserved (power)",
                        ib_before["power"] == ib_after["power"])
            except Exception as e:
                _fail("write: surrounding entries", str(e))

        # -- Description formatting ----------------------------------------

        try:
            result = _format_description_value("A short test.")
            _assert("format_desc: contains COMPOUND_STRING",
                    "COMPOUND_STRING" in result)
            _assert("format_desc: contains text",
                    "A short test." in result)
        except Exception as e:
            _fail("format_desc", str(e))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
