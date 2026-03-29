"""Shop Editor suite — detection, parsing, write-back."""
import os
import json
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_game_map(tmp, map_name, object_events=None, scripts_inc="",
                   scripts_pory=""):
    """Create a game tree with map.json and optional script files."""
    game = os.path.join(tmp, "game")
    map_dir = os.path.join(game, "data", "maps", map_name)
    os.makedirs(map_dir, exist_ok=True)

    map_data = {
        "id": f"MAP_{map_name.upper()}",
        "name": map_name,
        "object_events": object_events or [],
    }
    with open(os.path.join(map_dir, "map.json"), "w") as f:
        json.dump(map_data, f, indent=2)

    if scripts_inc:
        with open(os.path.join(map_dir, "scripts.inc"), "w") as f:
            f.write(scripts_inc)

    if scripts_pory:
        with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
            f.write(scripts_pory)

    return game


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("Shop Editor  (detection, parsing, write-back)")

    try:
        from torch.shop_editor import (
            detect_shop_npcs,
            find_shop_scripts,
            _parse_inc_shop,
            _parse_pory_shop,
            _write_shop_changes,
            _format_item_name,
            _link_shops,
            _trace_pokemart_refs,
        )
    except ImportError as e:
        _skip("all shop_editor tests", f"import failed: {e}")
        return

    tmp = tempfile.mkdtemp(prefix="torch_shop_editor_test_")
    try:
        _test_detect_npcs(tmp, detect_shop_npcs)
        _test_find_scripts_inc(tmp, find_shop_scripts)
        _test_find_scripts_pory(tmp, find_shop_scripts)
        _test_parse_inc(_parse_inc_shop)
        _test_parse_pory(_parse_pory_shop)
        _test_write_inc(tmp, find_shop_scripts, _write_shop_changes)
        _test_write_pory(tmp, find_shop_scripts, _write_shop_changes)
        _test_multiple_shops(tmp, find_shop_scripts)
        _test_empty_shop(tmp, find_shop_scripts)
        _test_format_item(_format_item_name)
        _test_trace_pokemart_refs(tmp, _trace_pokemart_refs)
        _test_no_shops(tmp, detect_shop_npcs, find_shop_scripts)
        _test_inc_with_comments(_parse_inc_shop)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# NPC detection tests
# ---------------------------------------------------------------------------

def _test_detect_npcs(tmp, detect_shop_npcs):
    """Test shopkeeper NPC detection in map.json."""
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    # Map with MART_EMPLOYEE NPC
    game = _make_game_map(tmp, "TestMart", object_events=[
        {
            "local_id": "LOCALID_CLERK",
            "graphics_id": "OBJ_EVENT_GFX_MART_EMPLOYEE",
            "x": 1, "y": 3,
            "script": "TestMart_EventScript_Clerk",
            "flag": "0",
        },
        {
            "graphics_id": "OBJ_EVENT_GFX_WOMAN_3",
            "x": 5, "y": 5,
            "script": "TestMart_EventScript_Woman",
            "flag": "0",
        },
    ])

    npcs = detect_shop_npcs(game, "TestMart")
    _assert(
        "detect NPCs: finds MART_EMPLOYEE",
        len(npcs) == 1,
        f"expected 1, got {len(npcs)}"
    )
    _assert(
        "detect NPCs: correct script label",
        npcs[0]["script_label"] == "TestMart_EventScript_Clerk",
        f"got {npcs[0].get('script_label')}"
    )
    _assert(
        "detect NPCs: correct position",
        npcs[0]["x"] == 1 and npcs[0]["y"] == 3,
        f"got ({npcs[0]['x']}, {npcs[0]['y']})"
    )

    # Map with no shops
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)
    game2 = _make_game_map(tmp, "NoShopMap", object_events=[
        {"graphics_id": "OBJ_EVENT_GFX_BOY_1", "x": 5, "y": 5,
         "script": "Boy_Script", "flag": "0"},
    ])
    npcs2 = detect_shop_npcs(game2, "NoShopMap")
    _assert(
        "detect NPCs: no shops returns empty",
        len(npcs2) == 0,
        f"expected 0, got {len(npcs2)}"
    )

    # Detect by string match (numeric graphics_id should not match)
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)
    game3 = _make_game_map(tmp, "NumericMap", object_events=[
        {"graphics_id": 83, "x": 1, "y": 1, "script": "Clerk", "flag": "0"},
    ])
    npcs3 = detect_shop_npcs(game3, "NumericMap")
    _assert(
        "detect NPCs: numeric 83 not matched (string check)",
        len(npcs3) == 0,
        f"expected 0, got {len(npcs3)}"
    )


# ---------------------------------------------------------------------------
# .inc shop script detection
# ---------------------------------------------------------------------------

def _test_find_scripts_inc(tmp, find_shop_scripts):
    """Test finding shop scripts in .inc files."""
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    inc_content = (
        "TestMart_EventScript_Clerk::\n"
        "\tlock\n"
        "\tfaceplayer\n"
        "\tpokemart TestMart_Pokemart\n"
        "\trelease\n"
        "\tend\n"
        "\n"
        "\t.align 2\n"
        "TestMart_Pokemart:\n"
        "\t.2byte ITEM_POTION\n"
        "\t.2byte ITEM_ANTIDOTE\n"
        "\t.2byte ITEM_POKE_BALL\n"
        "\tpokemartlistend\n"
    )
    game = _make_game_map(tmp, "TestMart", scripts_inc=inc_content)

    shops = find_shop_scripts(game, "TestMart")
    _assert(
        "find inc shops: finds one shop",
        len(shops) == 1,
        f"expected 1, got {len(shops)}"
    )
    _assert(
        "find inc shops: correct label",
        shops[0]["label"] == "TestMart_Pokemart",
        f"got {shops[0].get('label')}"
    )
    _assert(
        "find inc shops: correct items",
        shops[0]["items"] == ["ITEM_POTION", "ITEM_ANTIDOTE", "ITEM_POKE_BALL"],
        f"got {shops[0].get('items')}"
    )
    _assert(
        "find inc shops: format is inc",
        shops[0]["format"] == "inc",
        f"got {shops[0].get('format')}"
    )


# ---------------------------------------------------------------------------
# .pory shop script detection
# ---------------------------------------------------------------------------

def _test_find_scripts_pory(tmp, find_shop_scripts):
    """Test finding shop scripts in .pory files."""
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    pory_content = (
        'script TestMart_Clerk {\n'
        '    lock\n'
        '    faceplayer\n'
        '}\n'
        '\n'
        'mart("TestMart_Pokemart") {\n'
        '    ITEM_SUPER_POTION\n'
        '    ITEM_REVIVE\n'
        '}\n'
    )
    game = _make_game_map(tmp, "TestMart", scripts_pory=pory_content)

    shops = find_shop_scripts(game, "TestMart")
    _assert(
        "find pory shops: finds one shop",
        len(shops) == 1,
        f"expected 1, got {len(shops)}"
    )
    _assert(
        "find pory shops: correct label",
        shops[0]["label"] == "TestMart_Pokemart",
        f"got {shops[0].get('label')}"
    )
    _assert(
        "find pory shops: correct items",
        shops[0]["items"] == ["ITEM_SUPER_POTION", "ITEM_REVIVE"],
        f"got {shops[0].get('items')}"
    )
    _assert(
        "find pory shops: format is pory",
        shops[0]["format"] == "pory",
        f"got {shops[0].get('format')}"
    )


# ---------------------------------------------------------------------------
# .inc parser tests
# ---------------------------------------------------------------------------

def _test_parse_inc(_parse_inc_shop):
    """Test .inc shop block parsing."""
    lines = [
        "\t.align 2\n",
        "\t.2byte ITEM_POTION\n",
        "\t.2byte ITEM_ANTIDOTE\n",
        "\tpokemartlistend\n",
    ]
    items, end = _parse_inc_shop(lines, 0)
    _assert(
        "parse inc: basic block",
        items == ["ITEM_POTION", "ITEM_ANTIDOTE"],
        f"got {items}"
    )
    _assert(
        "parse inc: end line correct",
        end == 3,
        f"got {end}"
    )


def _test_inc_with_comments(_parse_inc_shop):
    """Test .inc parser with inline comments."""
    lines = [
        "\t.2byte ITEM_POTION @ healing\n",
        "\t.2byte ITEM_ANTIDOTE @ status\n",
        "\tpokemartlistend\n",
    ]
    items, end = _parse_inc_shop(lines, 0)
    _assert(
        "parse inc: comments stripped",
        items == ["ITEM_POTION", "ITEM_ANTIDOTE"],
        f"got {items}"
    )


# ---------------------------------------------------------------------------
# .pory parser tests
# ---------------------------------------------------------------------------

def _test_parse_pory(_parse_pory_shop):
    """Test .pory mart block parsing."""
    lines = [
        "    ITEM_SUPER_POTION\n",
        "    ITEM_REVIVE\n",
        "}\n",
    ]
    items, end = _parse_pory_shop(lines, 0)
    _assert(
        "parse pory: basic block",
        items == ["ITEM_SUPER_POTION", "ITEM_REVIVE"],
        f"got {items}"
    )
    _assert(
        "parse pory: end line is closing brace",
        end == 2,
        f"got {end}"
    )


# ---------------------------------------------------------------------------
# Write-back tests (.inc)
# ---------------------------------------------------------------------------

def _test_write_inc(tmp, find_shop_scripts, _write_shop_changes):
    """Test writing modified item list back to .inc file."""
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    inc_content = (
        "Header_Script::\n"
        "\tlock\n"
        "\tend\n"
        "\n"
        "\t.align 2\n"
        "TestMart_Pokemart:\n"
        "\t.2byte ITEM_POTION\n"
        "\t.2byte ITEM_ANTIDOTE\n"
        "\tpokemartlistend\n"
        "\n"
        "Footer_Script::\n"
        "\tend\n"
    )
    game = _make_game_map(tmp, "WriteMart", scripts_inc=inc_content)

    shops = find_shop_scripts(game, "WriteMart")
    _assert(
        "write inc: found shop to modify",
        len(shops) == 1,
        f"expected 1, got {len(shops)}"
    )

    # Add an item
    ok = _write_shop_changes(game, shops[0],
                             ["ITEM_POTION", "ITEM_ANTIDOTE", "ITEM_POKE_BALL"])
    _assert("write inc: add item returns True", ok, "returned False")

    # Read back and verify
    with open(shops[0]["file_path"], "r") as f:
        content = f.read()
    _assert(
        "write inc: new item present",
        "ITEM_POKE_BALL" in content,
        f"ITEM_POKE_BALL not found"
    )
    _assert(
        "write inc: pokemartlistend preserved",
        "pokemartlistend" in content,
        f"pokemartlistend missing"
    )
    _assert(
        "write inc: footer preserved",
        "Footer_Script" in content,
        f"Footer_Script missing"
    )

    # Remove an item (re-parse since line numbers changed)
    shops2 = find_shop_scripts(game, "WriteMart")
    ok2 = _write_shop_changes(game, shops2[0], ["ITEM_POTION"])
    _assert("write inc: remove items returns True", ok2, "returned False")

    with open(shops2[0]["file_path"], "r") as f:
        content2 = f.read()
    _assert(
        "write inc: removed items gone",
        "ITEM_ANTIDOTE" not in content2 and "ITEM_POKE_BALL" not in content2,
        f"removed items still present"
    )
    _assert(
        "write inc: remaining item present",
        "ITEM_POTION" in content2,
        f"ITEM_POTION missing"
    )


# ---------------------------------------------------------------------------
# Write-back tests (.pory)
# ---------------------------------------------------------------------------

def _test_write_pory(tmp, find_shop_scripts, _write_shop_changes):
    """Test writing modified item list back to .pory file."""
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    pory_content = (
        'script Header {\n'
        '    lock\n'
        '}\n'
        '\n'
        'mart("ShopItems") {\n'
        '    ITEM_SUPER_POTION\n'
        '    ITEM_REVIVE\n'
        '}\n'
        '\n'
        'script Footer {\n'
        '    end\n'
        '}\n'
    )
    game = _make_game_map(tmp, "WritePory", scripts_pory=pory_content)

    shops = find_shop_scripts(game, "WritePory")
    _assert(
        "write pory: found shop to modify",
        len(shops) == 1,
        f"expected 1, got {len(shops)}"
    )

    # Modify items
    ok = _write_shop_changes(game, shops[0],
                             ["ITEM_HYPER_POTION", "ITEM_FULL_RESTORE"])
    _assert("write pory: returns True", ok, "returned False")

    with open(shops[0]["file_path"], "r") as f:
        content = f.read()
    _assert(
        "write pory: new items present",
        "ITEM_HYPER_POTION" in content and "ITEM_FULL_RESTORE" in content,
        f"new items not found"
    )
    _assert(
        "write pory: old items removed",
        "ITEM_SUPER_POTION" not in content and "ITEM_REVIVE" not in content,
        f"old items still present"
    )
    _assert(
        "write pory: footer preserved",
        "Footer" in content,
        f"Footer missing"
    )


# ---------------------------------------------------------------------------
# Multiple shops in one map
# ---------------------------------------------------------------------------

def _test_multiple_shops(tmp, find_shop_scripts):
    """Test detection of multiple shops in one map."""
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    inc_content = (
        "\t.align 2\n"
        "DeptStore_Pokemart1:\n"
        "\t.2byte ITEM_POTION\n"
        "\t.2byte ITEM_SUPER_POTION\n"
        "\tpokemartlistend\n"
        "\n"
        "\t.align 2\n"
        "DeptStore_Pokemart2:\n"
        "\t.2byte ITEM_POKE_BALL\n"
        "\t.2byte ITEM_GREAT_BALL\n"
        "\tpokemartlistend\n"
    )
    game = _make_game_map(tmp, "DeptStore", scripts_inc=inc_content)

    shops = find_shop_scripts(game, "DeptStore")
    _assert(
        "multiple shops: finds both",
        len(shops) == 2,
        f"expected 2, got {len(shops)}"
    )
    labels = {s["label"] for s in shops}
    _assert(
        "multiple shops: correct labels",
        labels == {"DeptStore_Pokemart1", "DeptStore_Pokemart2"},
        f"got {labels}"
    )


# ---------------------------------------------------------------------------
# Empty shop
# ---------------------------------------------------------------------------

def _test_empty_shop(tmp, find_shop_scripts):
    """Test shop with no items (just pokemartlistend)."""
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    inc_content = (
        "EmptyShop:\n"
        "\tpokemartlistend\n"
    )
    game = _make_game_map(tmp, "EmptyMap", scripts_inc=inc_content)

    shops = find_shop_scripts(game, "EmptyMap")
    _assert(
        "empty shop: not detected (no items)",
        len(shops) == 0,
        f"expected 0, got {len(shops)}"
    )


# ---------------------------------------------------------------------------
# Item name formatting
# ---------------------------------------------------------------------------

def _test_format_item(_format_item_name):
    """Test item constant to display name conversion."""
    _assert(
        "format: ITEM_POKE_BALL",
        _format_item_name("ITEM_POKE_BALL") == "Poke Ball",
        f"got '{_format_item_name('ITEM_POKE_BALL')}'"
    )
    _assert(
        "format: ITEM_SUPER_POTION",
        _format_item_name("ITEM_SUPER_POTION") == "Super Potion",
        f"got '{_format_item_name('ITEM_SUPER_POTION')}'"
    )
    _assert(
        "format: ITEM_FULL_RESTORE",
        _format_item_name("ITEM_FULL_RESTORE") == "Full Restore",
        f"got '{_format_item_name('ITEM_FULL_RESTORE')}'"
    )
    _assert(
        "format: empty string",
        _format_item_name("") == "",
        f"got '{_format_item_name('')}'"
    )


# ---------------------------------------------------------------------------
# Pokemart reference tracing
# ---------------------------------------------------------------------------

def _test_trace_pokemart_refs(tmp, _trace_pokemart_refs):
    """Test tracing pokemart references through script labels."""
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    inc_content = (
        "Mart_Clerk::\n"
        "\tlock\n"
        "\tfaceplayer\n"
        "\tpokemart Mart_Items\n"
        "\trelease\n"
        "\tend\n"
        "\n"
        "Mart_Clerk2::\n"
        "\tlock\n"
        "\tgoto_if_set FLAG_TEST, Mart_Expanded\n"
        "\tpokemart Mart_Basic\n"
        "\trelease\n"
        "\tend\n"
        "\n"
        "Mart_Expanded::\n"
        "\tpokemart Mart_Full\n"
        "\trelease\n"
        "\tend\n"
    )
    inc_path = os.path.join(tmp, "trace_test.inc")
    with open(inc_path, "w") as f:
        f.write(inc_content)

    refs = _trace_pokemart_refs(inc_path)
    _assert(
        "trace: direct reference found",
        "Mart_Items" in refs.get("Mart_Clerk", []),
        f"got {refs.get('Mart_Clerk')}"
    )
    _assert(
        "trace: goto chain resolved",
        "Mart_Full" in refs.get("Mart_Clerk2", []),
        f"got {refs.get('Mart_Clerk2')}"
    )


# ---------------------------------------------------------------------------
# No shops at all
# ---------------------------------------------------------------------------

def _test_no_shops(tmp, detect_shop_npcs, find_shop_scripts):
    """Test detection on a map with no shops whatsoever."""
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    inc_content = (
        "SomeScript::\n"
        "\tmsgbox SomeText, MSGBOX_NPC\n"
        "\tend\n"
    )
    game = _make_game_map(tmp, "NoShops", object_events=[
        {"graphics_id": "OBJ_EVENT_GFX_BOY_1", "x": 5, "y": 5,
         "script": "SomeScript", "flag": "0"},
    ], scripts_inc=inc_content)

    npcs = detect_shop_npcs(game, "NoShops")
    scripts = find_shop_scripts(game, "NoShops")
    _assert("no shops: no NPCs", len(npcs) == 0, f"got {len(npcs)}")
    _assert("no shops: no scripts", len(scripts) == 0, f"got {len(scripts)}")
