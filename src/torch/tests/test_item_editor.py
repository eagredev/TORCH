"""Tests for item_editor module."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


# -- Mock items.h content for tests ----------------------------------------

_MOCK_CONSTANTS_H = """\
#ifndef GUARD_CONSTANTS_ITEMS_H
#define GUARD_CONSTANTS_ITEMS_H

#define ITEM_NONE 0
#define ITEM_POKE_BALL 1
#define ITEM_RARE_CANDY 2
#define ITEM_LEFTOVERS 3
#define ITEM_MASTER_BALL 4
#define ITEM_ORAN_BERRY 5

#define ITEMS_COUNT 6
#endif
"""

_MOCK_ITEMS_H = """\
#define ITEM_NAME(str) COMPOUND_STRING_SIZE_LIMIT(str, ITEM_NAME_LENGTH)
#define ITEM_PLURAL_NAME(str) COMPOUND_STRING_SIZE_LIMIT(str, ITEM_NAME_PLURAL_LENGTH)

const struct Item gItemsInfo[] =
{
    [ITEM_NONE] =
    {
        .name = gQuestionMarksItemName,
        .price = 0,
        .description = sQuestionMarksDesc,
        .pocket = POCKET_ITEMS,
        .sortType = ITEM_TYPE_UNCATEGORIZED,
        .type = ITEM_USE_BAG_MENU,
        .fieldUseFunc = ItemUseOutOfBattle_CannotUse,
        .iconPic = gItemIcon_QuestionMark,
        .iconPalette = gItemIconPalette_QuestionMark,
    },

    [ITEM_POKE_BALL] =
    {
        .name = ITEM_NAME("Poke Ball"),
        .price = 200,
        .description = COMPOUND_STRING(
            "A tool used for\\n"
            "catching wild\\n"
            "Pokemon."),
        .pocket = POCKET_POKE_BALLS,
        .type = ITEM_USE_BAG_MENU,
        .battleUsage = EFFECT_ITEM_THROW_BALL,
        .secondaryId = BALL_POKE,
        .flingPower = 15,
        .iconPic = gItemIcon_PokeBall,
        .iconPalette = gItemIconPalette_PokeBall,
    },

    [ITEM_RARE_CANDY] =
    {
        .name = ITEM_NAME("Rare Candy"),
        .pluralName = ITEM_PLURAL_NAME("Rare Candies"),
        .price = (I_PRICE >= GEN_7) ? 10000 : 4800,
        .description = COMPOUND_STRING(
            "Raises the level\\n"
            "of a Pokemon by\\n"
            "one."),
        .pocket = POCKET_ITEMS,
        .sortType = ITEM_TYPE_LEVEL_UP_ITEM,
        .type = ITEM_USE_PARTY_MENU,
        .fieldUseFunc = ItemUseOutOfBattle_RareCandy,
        .flingPower = 30,
        .iconPic = gItemIcon_RareCandy,
        .iconPalette = gItemIconPalette_RareCandy,
    },

    [ITEM_LEFTOVERS] =
    {
        .name = ITEM_NAME("Leftovers"),
        .pluralName = ITEM_PLURAL_NAME("Leftovers"),
        .price = 4000,
        .holdEffect = HOLD_EFFECT_LEFTOVERS,
        .holdEffectParam = 16,
        .description = COMPOUND_STRING(
            "An item to be held\\n"
            "by a Pokemon. It\\n"
            "restores HP."),
        .pocket = POCKET_ITEMS,
        .sortType = ITEM_TYPE_HELD_ITEM,
        .type = ITEM_USE_BAG_MENU,
        .flingPower = 10,
        .iconPic = gItemIcon_Leftovers,
        .iconPalette = gItemIconPalette_Leftovers,
    },

    [ITEM_MASTER_BALL] =
    {
        .name = ITEM_NAME("Master Ball"),
        .price = 0,
        .description = COMPOUND_STRING(
            "The best Ball that\\n"
            "catches a Pokemon\\n"
            "without fail."),
        .pocket = POCKET_POKE_BALLS,
        .type = ITEM_USE_BAG_MENU,
        .battleUsage = EFFECT_ITEM_THROW_BALL,
        .iconPic = gItemIcon_MasterBall,
        .iconPalette = gItemIconPalette_MasterBall,
    },

    [ITEM_ORAN_BERRY] =
    {
        .name = ITEM_NAME("Oran Berry"),
        .pluralName = ITEM_PLURAL_NAME("Oran Berries"),
        .price = 20,
        .holdEffect = HOLD_EFFECT_RESTORE_HP,
        .holdEffectParam = 10,
        .description = COMPOUND_STRING(
            "A Berry to be held\\n"
            "by a Pokemon. It\\n"
            "heals 10 HP."),
        .pocket = POCKET_BERRIES,
        .sortType = ITEM_TYPE_BERRY,
        .type = ITEM_USE_PARTY_MENU,
        .flingPower = 10,
        .iconPic = gItemIcon_OranBerry,
        .iconPalette = gItemIconPalette_OranBerry,
    },
};
"""

_MOCK_HOLD_EFFECTS_H = """\
enum __attribute__((packed)) HoldEffect
{
    HOLD_EFFECT_NONE,
    HOLD_EFFECT_RESTORE_HP,
    HOLD_EFFECT_LEFTOVERS,
    HOLD_EFFECT_CURE_PAR,
    HOLD_EFFECT_CURE_SLP,
};
"""


def _make_mock_project(tmp):
    """Create a mock game project with items.h, constants, etc."""
    src_data = os.path.join(tmp, "src", "data")
    inc_const = os.path.join(tmp, "include", "constants")
    os.makedirs(src_data, exist_ok=True)
    os.makedirs(inc_const, exist_ok=True)

    with open(os.path.join(src_data, "items.h"), "w") as f:
        f.write(_MOCK_ITEMS_H)
    with open(os.path.join(inc_const, "items.h"), "w") as f:
        f.write(_MOCK_CONSTANTS_H)
    with open(os.path.join(inc_const, "hold_effects.h"), "w") as f:
        f.write(_MOCK_HOLD_EFFECTS_H)
    return tmp


def run_suite():
    """Entry point called by run_tests.py."""
    _begin_suite("Item Editor")

    try:
        from torch.item_editor import (
            parse_items, _extract_price_display, _extract_compound_string,
            _apply_filters, _write_field, _load_hold_effects,
            _load_item_ids, _pocket_label, _sort_label, _hold_label,
            _format_description_value, _py_to_c_field,
        )
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # -- Price display extraction ------------------------------------------

    try:
        result = _extract_price_display("4800")
        _assert("price_display: simple int", result == "4800", f"got {result}")
    except Exception as e:
        _fail("price_display: simple int", str(e))

    try:
        result = _extract_price_display("(I_PRICE >= GEN_7) ? 10000 : 4800")
        _assert("price_display: ternary", result == "10000", f"got {result}")
    except Exception as e:
        _fail("price_display: ternary", str(e))

    try:
        result = _extract_price_display("0")
        _assert("price_display: zero", result == "0", f"got {result}")
    except Exception as e:
        _fail("price_display: zero", str(e))

    # -- Compound string extraction ----------------------------------------

    try:
        lines = [
            '        .description = COMPOUND_STRING(\n',
            '            "Raises the level\\n"\n',
            '            "of a Pokemon by\\n"\n',
            '            "one."),\n',
        ]
        text, end_i = _extract_compound_string(lines, 0)
        _assert("compound_string: basic",
                "Raises the level" in text and "one." in text,
                f"got '{text}'")
    except Exception as e:
        _fail("compound_string: basic", str(e))

    # -- Label helpers -----------------------------------------------------

    try:
        _assert("pocket_label: POCKET_ITEMS",
                _pocket_label("POCKET_ITEMS") == "Items")
        _assert("pocket_label: POCKET_POKE_BALLS",
                _pocket_label("POCKET_POKE_BALLS") == "Balls")
    except Exception as e:
        _fail("pocket_label", str(e))

    try:
        _assert("sort_label: present",
                _sort_label("ITEM_TYPE_HELD_ITEM") == "Held Item")
        _assert("sort_label: empty",
                _sort_label("") == "(none)")
    except Exception as e:
        _fail("sort_label", str(e))

    try:
        _assert("hold_label: present",
                _hold_label("HOLD_EFFECT_LEFTOVERS") == "Leftovers")
        _assert("hold_label: empty",
                _hold_label("") == "(none)")
    except Exception as e:
        _fail("hold_label", str(e))

    # -- Field name mapping ------------------------------------------------

    try:
        _assert("py_to_c: sort_type", _py_to_c_field("sort_type") == "sortType")
        _assert("py_to_c: hold_effect",
                _py_to_c_field("hold_effect") == "holdEffect")
        _assert("py_to_c: name", _py_to_c_field("name") == "name")
    except Exception as e:
        _fail("py_to_c_field", str(e))

    # -- Parser (mock project) ---------------------------------------------

    tmp = tempfile.mkdtemp(prefix="torch_item_test_")
    try:
        _make_mock_project(tmp)

        # Parse item IDs
        try:
            ids = _load_item_ids(tmp)
            _assert("load_item_ids: count", len(ids) >= 5,
                    f"got {len(ids)} ids")
            _assert("load_item_ids: ITEM_POKE_BALL",
                    ids.get("ITEM_POKE_BALL") == 1,
                    f"got {ids.get('ITEM_POKE_BALL')}")
        except Exception as e:
            _fail("load_item_ids", str(e))

        # Parse hold effects
        try:
            effects = _load_hold_effects(tmp)
            _assert("load_hold_effects: count", len(effects) >= 4,
                    f"got {len(effects)}")
            _assert("load_hold_effects: contains LEFTOVERS",
                    "HOLD_EFFECT_LEFTOVERS" in effects)
        except Exception as e:
            _fail("load_hold_effects", str(e))

        # Parse all items
        try:
            items = parse_items(tmp)
            _assert("parse_items: count", len(items) == 5,
                    f"got {len(items)} (expected 5, ITEM_NONE excluded)")
        except Exception as e:
            _fail("parse_items: count", str(e))
            items = []

        # Parse item names
        if items:
            try:
                names = [it["name"] for it in items]
                _assert("parse: Poke Ball name", "Poke Ball" in names,
                        f"names: {names}")
                _assert("parse: Rare Candy name", "Rare Candy" in names,
                        f"names: {names}")
            except Exception as e:
                _fail("parse: item names", str(e))

        # Parse conditional price
        if items:
            try:
                rc = next(it for it in items if it["constant"] == "ITEM_RARE_CANDY")
                _assert("parse: conditional price raw",
                        "I_PRICE" in rc["price"],
                        f"got '{rc['price']}'")
                _assert("parse: conditional price display",
                        rc["price_display"] == "10000",
                        f"got '{rc['price_display']}'")
            except Exception as e:
                _fail("parse: conditional price", str(e))

        # Parse hold effect
        if items:
            try:
                lf = next(it for it in items if it["constant"] == "ITEM_LEFTOVERS")
                _assert("parse: hold effect",
                        lf["hold_effect"] == "HOLD_EFFECT_LEFTOVERS",
                        f"got '{lf['hold_effect']}'")
                _assert("parse: hold effect param",
                        lf["hold_effect_param"] == 16,
                        f"got {lf['hold_effect_param']}")
            except Exception as e:
                _fail("parse: hold effect", str(e))

        # Parse description
        if items:
            try:
                pb = next(it for it in items if it["constant"] == "ITEM_POKE_BALL")
                _assert("parse: description contains text",
                        "catching wild" in pb["description"],
                        f"got '{pb['description']}'")
            except Exception as e:
                _fail("parse: description", str(e))

        # Parse plural name
        if items:
            try:
                rc = next(it for it in items if it["constant"] == "ITEM_RARE_CANDY")
                _assert("parse: plural name",
                        rc["plural_name"] == "Rare Candies",
                        f"got '{rc['plural_name']}'")
            except Exception as e:
                _fail("parse: plural name", str(e))

        # Parse pocket
        if items:
            try:
                pb = next(it for it in items if it["constant"] == "ITEM_POKE_BALL")
                _assert("parse: pocket",
                        pb["pocket"] == "POCKET_POKE_BALLS",
                        f"got '{pb['pocket']}'")
            except Exception as e:
                _fail("parse: pocket", str(e))

        # Parse sort type
        if items:
            try:
                rc = next(it for it in items if it["constant"] == "ITEM_RARE_CANDY")
                _assert("parse: sort type",
                        rc["sort_type"] == "ITEM_TYPE_LEVEL_UP_ITEM",
                        f"got '{rc['sort_type']}'")
            except Exception as e:
                _fail("parse: sort type", str(e))

        # Parse fling power
        if items:
            try:
                rc = next(it for it in items if it["constant"] == "ITEM_RARE_CANDY")
                _assert("parse: fling power",
                        rc["fling_power"] == 30,
                        f"got {rc['fling_power']}")
            except Exception as e:
                _fail("parse: fling power", str(e))

        # Minimal entry (no optional fields)
        if items:
            try:
                mb = next(it for it in items if it["constant"] == "ITEM_MASTER_BALL")
                _assert("parse: minimal entry name",
                        mb["name"] == "Master Ball",
                        f"got '{mb['name']}'")
                _assert("parse: minimal entry no hold effect",
                        mb["hold_effect"] == "",
                        f"got '{mb['hold_effect']}'")
                _assert("parse: minimal entry no sort type",
                        mb["sort_type"] == "",
                        f"got '{mb['sort_type']}'")
            except Exception as e:
                _fail("parse: minimal entry", str(e))

        # -- Filter tests --------------------------------------------------

        if items:
            try:
                balls = _apply_filters(items, "", "POCKET_POKE_BALLS", "")
                _assert("filter: pocket POKE_BALLS",
                        len(balls) == 2,
                        f"got {len(balls)}")
                _assert("filter: pocket POKE_BALLS names",
                        all(it["pocket"] == "POCKET_POKE_BALLS" for it in balls))
            except Exception as e:
                _fail("filter: pocket", str(e))

            try:
                held = _apply_filters(items, "", "", "ITEM_TYPE_HELD_ITEM")
                _assert("filter: sort type HELD_ITEM",
                        len(held) == 1 and held[0]["constant"] == "ITEM_LEFTOVERS",
                        f"got {len(held)} items")
            except Exception as e:
                _fail("filter: sort type", str(e))

            try:
                searched = _apply_filters(items, "candy", "", "")
                _assert("filter: search 'candy'",
                        len(searched) == 1 and searched[0]["name"] == "Rare Candy",
                        f"got {len(searched)} items")
            except Exception as e:
                _fail("filter: search name", str(e))

            try:
                searched = _apply_filters(items, "LEFTOVERS", "", "")
                _assert("filter: search constant",
                        len(searched) == 1 and searched[0]["constant"] == "ITEM_LEFTOVERS",
                        f"got {len(searched)} items")
            except Exception as e:
                _fail("filter: search constant", str(e))

            try:
                combined = _apply_filters(items, "ball", "POCKET_POKE_BALLS", "")
                _assert("filter: combined pocket + search",
                        len(combined) == 2,
                        f"got {len(combined)} items")
            except Exception as e:
                _fail("filter: combined", str(e))

        # -- Write tests ---------------------------------------------------

        # Write name
        if items:
            try:
                pb = next(it for it in items if it["constant"] == "ITEM_POKE_BALL")
                ok = _write_field(tmp, pb, "name", "Great Ball")
                _assert("write: name success", ok)
                # Re-parse and verify
                items2 = parse_items(tmp)
                pb2 = next(it for it in items2 if it["constant"] == "ITEM_POKE_BALL")
                _assert("write: name persisted",
                        pb2["name"] == "Great Ball",
                        f"got '{pb2['name']}'")
                # Restore
                _write_field(tmp, pb2, "name", "Poke Ball")
            except Exception as e:
                _fail("write: name", str(e))

        # Write price
        if items:
            try:
                pb = next(it for it in parse_items(tmp)
                          if it["constant"] == "ITEM_POKE_BALL")
                ok = _write_field(tmp, pb, "price", "500")
                _assert("write: price success", ok)
                items2 = parse_items(tmp)
                pb2 = next(it for it in items2 if it["constant"] == "ITEM_POKE_BALL")
                _assert("write: price persisted",
                        pb2["price_display"] == "500",
                        f"got '{pb2['price_display']}'")
                _write_field(tmp, pb2, "price", "200")
            except Exception as e:
                _fail("write: price", str(e))

        # Write pocket
        if items:
            try:
                pb = next(it for it in parse_items(tmp)
                          if it["constant"] == "ITEM_POKE_BALL")
                ok = _write_field(tmp, pb, "pocket", "POCKET_ITEMS")
                _assert("write: pocket success", ok)
                items2 = parse_items(tmp)
                pb2 = next(it for it in items2 if it["constant"] == "ITEM_POKE_BALL")
                _assert("write: pocket persisted",
                        pb2["pocket"] == "POCKET_ITEMS",
                        f"got '{pb2['pocket']}'")
                _write_field(tmp, pb2, "pocket", "POCKET_POKE_BALLS")
            except Exception as e:
                _fail("write: pocket", str(e))

        # Write hold effect
        if items:
            try:
                lf = next(it for it in parse_items(tmp)
                          if it["constant"] == "ITEM_LEFTOVERS")
                ok = _write_field(tmp, lf, "hold_effect", "HOLD_EFFECT_RESTORE_HP")
                _assert("write: hold effect success", ok)
                items2 = parse_items(tmp)
                lf2 = next(it for it in items2 if it["constant"] == "ITEM_LEFTOVERS")
                _assert("write: hold effect persisted",
                        lf2["hold_effect"] == "HOLD_EFFECT_RESTORE_HP",
                        f"got '{lf2['hold_effect']}'")
                _write_field(tmp, lf2, "hold_effect", "HOLD_EFFECT_LEFTOVERS")
            except Exception as e:
                _fail("write: hold effect", str(e))

        # Write description
        if items:
            try:
                pb = next(it for it in parse_items(tmp)
                          if it["constant"] == "ITEM_POKE_BALL")
                ok = _write_field(tmp, pb, "description", "A new description for testing.")
                _assert("write: description success", ok)
                items2 = parse_items(tmp)
                pb2 = next(it for it in items2 if it["constant"] == "ITEM_POKE_BALL")
                _assert("write: description persisted",
                        "new description" in pb2["description"],
                        f"got '{pb2['description']}'")
            except Exception as e:
                _fail("write: description", str(e))

        # Preserve conditional price when editing different field
        if items:
            try:
                rc = next(it for it in parse_items(tmp)
                          if it["constant"] == "ITEM_RARE_CANDY")
                ok = _write_field(tmp, rc, "fling_power", "50")
                _assert("write: fling power success", ok)
                items2 = parse_items(tmp)
                rc2 = next(it for it in items2 if it["constant"] == "ITEM_RARE_CANDY")
                _assert("write: conditional price preserved",
                        "I_PRICE" in rc2["price"],
                        f"price became '{rc2['price']}'")
                _assert("write: fling power changed",
                        rc2["fling_power"] == 50,
                        f"got {rc2['fling_power']}")
            except Exception as e:
                _fail("write: preserve conditional price", str(e))

        # Preserve surrounding entries when editing
        if items:
            try:
                items_before = parse_items(tmp)
                rc = next(it for it in items_before
                          if it["constant"] == "ITEM_RARE_CANDY")
                _write_field(tmp, rc, "name", "Super Candy")
                items_after = parse_items(tmp)
                # Check that other items are unchanged
                lf_before = next(it for it in items_before
                                 if it["constant"] == "ITEM_LEFTOVERS")
                lf_after = next(it for it in items_after
                                if it["constant"] == "ITEM_LEFTOVERS")
                _assert("write: surrounding entries preserved (name)",
                        lf_before["name"] == lf_after["name"],
                        f"Leftovers name changed: {lf_before['name']} -> {lf_after['name']}")
                _assert("write: surrounding entries preserved (price)",
                        lf_before["price"] == lf_after["price"])
                # Restore
                rc2 = next(it for it in items_after
                           if it["constant"] == "ITEM_RARE_CANDY")
                _write_field(tmp, rc2, "name", "Rare Candy")
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
