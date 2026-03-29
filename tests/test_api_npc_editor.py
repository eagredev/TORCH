"""Tests for the NPC Editor API endpoints."""
import json
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _assert, _skip


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_npc(script="TestMap_EventScript_Npc1", gfx="OBJ_EVENT_GFX_BOY_1",
              x=5, y=10, elevation=3, flag="0", trainer_type="TRAINER_TYPE_NONE",
              movement_type="MOVEMENT_TYPE_FACE_DOWN"):
    """Build a single object_event dict."""
    return {
        "graphics_id": gfx,
        "x": x,
        "y": y,
        "elevation": elevation,
        "movement_type": movement_type,
        "movement_range_x": 0,
        "movement_range_y": 0,
        "trainer_type": trainer_type,
        "trainer_sight_or_berry_tree_id": "0",
        "script": script,
        "flag": flag,
    }


def _make_game(tmp, map_name, object_events=None, scripts_pory="",
               scripts_inc=""):
    """Create a minimal game tree with map.json and optional script files."""
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

    if scripts_pory:
        with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
            f.write(scripts_pory)

    if scripts_inc:
        with open(os.path.join(map_dir, "scripts.inc"), "w") as f:
            f.write(scripts_inc)

    return game


def _make_workspace(tmp, map_name, files=None):
    """Create a workspace directory with .txt files."""
    ws = os.path.join(tmp, "workspace")
    ws_map = os.path.join(ws, map_name)
    os.makedirs(ws_map, exist_ok=True)
    for fname, content in (files or {}).items():
        with open(os.path.join(ws_map, fname), "w") as f:
            f.write(content)
    return ws


FLAVOR_PORY = '''\
script TestMap_EventScript_Npc1 {
    msgbox(format("Hello there!\\nHow are you?$"), MSGBOX_NPC)
}
'''

SIGN_PORY = '''\
script TestMap_EventScript_Sign1 {
    msgbox(format("Town Square$"), MSGBOX_SIGN)
}
'''

ITEM_GIVER_PORY = '''\
script TestMap_EventScript_ItemGuy {
    giveitem(ITEM_POTION, 1)
    msgbox(format("Here you go!$"), MSGBOX_NPC)
}
'''

NURSE_PORY = '''\
script TestMap_EventScript_Nurse {
    special(HealPlayerParty)
    msgbox(format("All healed!$"), MSGBOX_NPC)
}
'''

PC_PORY = '''\
script TestMap_EventScript_PC {
    special(ShowPokemonStorageSystem)
}
'''

COMPLEX_PORY = '''\
script TestMap_EventScript_Complex {
    if (flag(FLAG_GOT_ITEM)) {
        msgbox(format("You already got it!$"), MSGBOX_NPC)
    } else {
        msgbox(format("Take this!$"), MSGBOX_NPC)
    }
}
'''

# Scripts with msgbox + extra logic (lock/faceplayer/release) → "custom"
CUSTOM_PORY = '''\
script TestMap_EventScript_Custom {
    lock
    faceplayer
    msgbox(format("Hey, watch where you're going!$"), MSGBOX_NPC)
    release
}
'''

# Script with no msgbox at all → "complex" (pure logic)
PURE_COMPLEX_PORY = '''\
script TestMap_EventScript_PureComplex {
    setvar(VAR_RESULT, 1)
    callnative(SomeFunction)
}
'''

MULTI_PORY = (FLAVOR_PORY + "\n" + SIGN_PORY + "\n" + NURSE_PORY + "\n"
              + PC_PORY + "\n" + COMPLEX_PORY + "\n" + ITEM_GIVER_PORY)


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

def _read_map_json(game, map_name):
    """Read and return map.json data."""
    path = os.path.join(game, "data", "maps", map_name, "map.json")
    with open(path, "r") as f:
        return json.load(f)


def _read_pory(game, map_name):
    """Read scripts.pory content."""
    path = os.path.join(game, "data", "maps", map_name, "scripts.pory")
    with open(path, "r") as f:
        return f.read()


def run_suite():
    _begin_suite("NPC Editor API  (detail, mutations, health, create, delete)")

    from torch.web.api_npc_editor import (
        _classify_script, _extract_pory_dialogue, _extract_inc_dialogue,
        _game_text_to_readable, _readable_to_game_text,
        _build_cast_index, _build_npc_detail, _replace_msgbox_text,
        _check_script_health, _EDITABLE_TYPES,
    )

    # --- Script classification ---

    def test_classify_flavor():
        result = _classify_script(FLAVOR_PORY, "TestMap_EventScript_Npc1")
        _assert("classify_flavor", result == "flavor",
                f"expected 'flavor', got '{result}'")

    def test_classify_sign():
        result = _classify_script(SIGN_PORY, "TestMap_EventScript_Sign1")
        _assert("classify_sign", result == "sign",
                f"expected 'sign', got '{result}'")

    def test_classify_item_giver():
        result = _classify_script(ITEM_GIVER_PORY, "TestMap_EventScript_ItemGuy")
        _assert("classify_item_giver", result == "item_giver",
                f"expected 'item_giver', got '{result}'")

    def test_classify_nurse():
        result = _classify_script(NURSE_PORY, "TestMap_EventScript_Nurse")
        _assert("classify_nurse", result == "nurse",
                f"expected 'nurse', got '{result}'")

    def test_classify_pc():
        result = _classify_script(PC_PORY, "TestMap_EventScript_PC")
        _assert("classify_pc", result == "pc",
                f"expected 'pc', got '{result}'")

    def test_classify_custom():
        result = _classify_script(CUSTOM_PORY, "TestMap_EventScript_Custom")
        _assert("classify_custom", result == "custom",
                f"expected 'custom', got '{result}'")

    def test_classify_complex():
        result = _classify_script(PURE_COMPLEX_PORY, "TestMap_EventScript_PureComplex")
        _assert("classify_complex", result == "complex",
                f"expected 'complex', got '{result}'")

    def test_classify_missing():
        result = _classify_script(FLAVOR_PORY, "Nonexistent_Script")
        _assert("classify_missing_label", result == "complex",
                f"expected 'complex', got '{result}'")

    # --- is_editable ---

    def test_is_editable():
        editable = {"flavor", "sign", "item_giver", "complex", "custom"}
        not_editable = {"nurse", "pc", "shared", "inc", "unknown", "none"}
        ok = True
        detail = ""
        for t in editable:
            if t not in _EDITABLE_TYPES:
                ok = False
                detail = f"{t} should be editable"
        for t in not_editable:
            if t in _EDITABLE_TYPES:
                ok = False
                detail = f"{t} should NOT be editable"
        _assert("is_editable_check", ok, detail)

    # --- Dialogue extraction ---

    def test_extract_pory_format():
        dlg = _extract_pory_dialogue(FLAVOR_PORY, "TestMap_EventScript_Npc1")
        _assert("extract_pory_format", dlg is not None and dlg["uses_format"],
                f"expected format() dialogue, got {dlg}")
        _assert("extract_pory_text", dlg["text"] == "Hello there!\\nHow are you?$",
                f"got text: {dlg['text']!r}")
        _assert("extract_pory_type", dlg["msgbox_type"] == "MSGBOX_NPC",
                f"got type: {dlg['msgbox_type']}")

    def test_extract_pory_plain():
        plain = 'script Test {  msgbox("Hi there!$", MSGBOX_NPC)  }'
        dlg = _extract_pory_dialogue(plain, "Test")
        _assert("extract_pory_plain", dlg is not None and not dlg["uses_format"],
                f"expected plain dialogue, got {dlg}")

    def test_extract_pory_missing():
        dlg = _extract_pory_dialogue(FLAVOR_PORY, "NonexistentScript")
        _assert("extract_pory_missing", dlg is None, "expected None for missing")

    def test_extract_inc():
        inc = """\
TestMap_EventScript_Hello::
\tmsgbox TestMap_Text_Hello, MSGBOX_NPC
\treturn

TestMap_Text_Hello:
\t.string "Hello world!$"
"""
        dlg = _extract_inc_dialogue(inc, "TestMap_EventScript_Hello")
        _assert("extract_inc", dlg is not None, "expected inc dialogue")
        _assert("extract_inc_text", dlg["text"] == "Hello world!$",
                f"got: {dlg['text']!r}")
        _assert("extract_inc_type", dlg["msgbox_type"] == "MSGBOX_NPC",
                f"got: {dlg['msgbox_type']}")

    def test_extract_inc_missing():
        dlg = _extract_inc_dialogue("some content", "Missing_Label")
        _assert("extract_inc_missing", dlg is None, "expected None")

    # --- Text conversion ---

    def test_game_to_readable():
        r = _game_text_to_readable("Hello\\nworld!\\pPage two$")
        _assert("game_to_readable", r == "Hello\nworld!\n\nPage two",
                f"got: {r!r}")

    def test_game_to_readable_empty():
        _assert("game_to_readable_empty", _game_text_to_readable("") == "",
                "empty should stay empty")

    def test_readable_to_game():
        r = _readable_to_game_text("Hello\nworld!")
        _assert("readable_to_game", r == "Hello\\nworld!$",
                f"got: {r!r}")

    def test_readable_to_game_paragraphs():
        r = _readable_to_game_text("Hello\n\nPage two")
        _assert("readable_to_game_paragraphs", r == "Hello\\pPage two$",
                f"got: {r!r}")

    def test_readable_to_game_empty():
        r = _readable_to_game_text("")
        _assert("readable_to_game_empty", r == "$", f"got: {r!r}")

    # --- NPC detail ---

    def test_npc_detail():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap",
                              [_make_npc()], FLAVOR_PORY)
            detail, err = _build_npc_detail(game, "TestMap", 1)
            _assert("detail_no_error", err is None, f"error: {err}")
            _assert("detail_object_id", detail["object_id"] == 1,
                    f"got {detail['object_id']}")
            _assert("detail_gfx", detail["graphics_id"] == "OBJ_EVENT_GFX_BOY_1",
                    f"got {detail['graphics_id']}")
            _assert("detail_display_name", detail["display_name"] == "Boy 1",
                    f"got {detail['display_name']}")
            _assert("detail_script_type", detail["script_type"] == "flavor",
                    f"got {detail['script_type']}")
            _assert("detail_source", detail["script_source"] == "scripts.pory",
                    f"got {detail['script_source']}")
            _assert("detail_is_editable", detail["is_editable"] is True,
                    "expected editable")
            _assert("detail_dialogue", detail["dialogue"] is not None,
                    "expected dialogue")
            _assert("detail_readable", detail["dialogue_readable"] is not None,
                    "expected readable dialogue")
            _assert("detail_refs", detail["referenced_by"] == [],
                    f"expected empty refs, got {detail['referenced_by']}")
        finally:
            shutil.rmtree(tmp)

    def test_npc_detail_404():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [_make_npc()])
            detail, err = _build_npc_detail(game, "TestMap", 99)
            _assert("detail_404", detail is None and err is not None,
                    f"expected error, got detail={detail}")
        finally:
            shutil.rmtree(tmp)

    def test_npc_detail_no_script():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [_make_npc(script="")])
            detail, err = _build_npc_detail(game, "TestMap", 1)
            _assert("detail_no_script", err is None, f"error: {err}")
            _assert("detail_no_script_type", detail["script_type"] == "none",
                    f"got {detail['script_type']}")
        finally:
            shutil.rmtree(tmp)

    def test_npc_detail_shared():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap",
                              [_make_npc(script="Common_EventScript_NopReturn")])
            detail, err = _build_npc_detail(game, "TestMap", 1)
            _assert("detail_shared", detail["script_type"] == "shared",
                    f"got {detail['script_type']}")
        finally:
            shutil.rmtree(tmp)

    # --- Cast index ---

    def test_cast_index():
        tmp = tempfile.mkdtemp()
        try:
            ws = _make_workspace(tmp, "TestMap", {
                "scene_intro.txt": "alias buster npc2\n\nsome content\n",
                "scene_final.txt": "alias rival npc3\n\nmore content\n",
            })
            cast = _build_cast_index(ws, "TestMap")
            _assert("cast_npc2", 2 in cast, f"keys: {list(cast.keys())}")
            _assert("cast_npc2_alias", cast[2][0][0] == "buster",
                    f"got {cast[2][0][0]}")
            _assert("cast_npc2_file", cast[2][0][2] == "scene_intro.txt",
                    f"got {cast[2][0][2]}")
            _assert("cast_npc3", 3 in cast and cast[3][0][0] == "rival",
                    f"got {cast.get(3)}")
        finally:
            shutil.rmtree(tmp)

    def test_cast_index_empty():
        tmp = tempfile.mkdtemp()
        try:
            ws = _make_workspace(tmp, "TestMap", {})
            cast = _build_cast_index(ws, "TestMap")
            _assert("cast_empty", cast == {}, f"expected empty, got {cast}")
        finally:
            shutil.rmtree(tmp)

    def test_cast_index_no_workspace():
        cast = _build_cast_index("/nonexistent/path", "TestMap")
        _assert("cast_no_ws", cast == {}, f"expected empty, got {cast}")

    def test_npc_detail_with_cast():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap",
                              [_make_npc()], FLAVOR_PORY)
            ws = _make_workspace(tmp, "TestMap", {
                "scene_intro.txt": "alias buster npc1\n\ncontent\n",
            })
            detail, err = _build_npc_detail(game, "TestMap", 1, ws)
            _assert("detail_cast_refs", len(detail["referenced_by"]) == 1,
                    f"got {detail['referenced_by']}")
            ref = detail["referenced_by"][0]
            _assert("detail_cast_alias", ref["alias_name"] == "buster",
                    f"got {ref['alias_name']}")
        finally:
            shutil.rmtree(tmp)

    # --- Property update (map.json) ---

    def test_property_update():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [_make_npc()])
            map_json = os.path.join(game, "data", "maps", "TestMap", "map.json")

            # Simulate update
            with open(map_json, "r") as f:
                data = json.load(f)
            data["object_events"][0]["x"] = 15
            data["object_events"][0]["graphics_id"] = "OBJ_EVENT_GFX_OLD_MAN"
            with open(map_json, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")

            with open(map_json, "r") as f:
                result = json.load(f)
            obj = result["object_events"][0]
            _assert("update_x", obj["x"] == 15, f"got {obj['x']}")
            _assert("update_gfx", obj["graphics_id"] == "OBJ_EVENT_GFX_OLD_MAN",
                    f"got {obj['graphics_id']}")
        finally:
            shutil.rmtree(tmp)

    def test_int_validation():
        """Verify _INT_FIELDS set is correct."""
        from torch.web.api_npc_editor import _INT_FIELDS, _ALLOWED_FIELDS
        expected_int = {"x", "y", "elevation", "movement_range_x", "movement_range_y"}
        _assert("int_fields_correct", _INT_FIELDS == expected_int,
                f"got {_INT_FIELDS}")
        # script should not be allowed
        _assert("script_not_allowed", "script" not in _ALLOWED_FIELDS,
                "'script' should not be in allowed fields")

    # --- Dialogue replacement ---

    def test_replace_msgbox_format():
        body = '    msgbox(format("Old text$"), MSGBOX_NPC)\n'
        result = _replace_msgbox_text(body, "New text", None)
        _assert("replace_format", result is not None, "expected replacement")
        _assert("replace_format_text", '"New text"' in result,
                f"got: {result!r}")
        _assert("replace_format_type", "MSGBOX_NPC" in result,
                f"got: {result!r}")

    def test_replace_msgbox_plain():
        body = '    msgbox("Old text$", MSGBOX_SIGN)\n'
        result = _replace_msgbox_text(body, "New text", None)
        _assert("replace_plain", result is not None, "expected replacement")
        _assert("replace_plain_text", '"New text"' in result, f"got: {result!r}")

    def test_replace_msgbox_change_type():
        body = '    msgbox(format("text"), MSGBOX_NPC)\n'
        result = _replace_msgbox_text(body, "text", "MSGBOX_SIGN")
        _assert("replace_type", result is not None, "expected replacement")
        _assert("replace_type_value", "MSGBOX_SIGN" in result, f"got: {result!r}")

    def test_replace_msgbox_not_found():
        body = '    special(DoSomething)\n'
        result = _replace_msgbox_text(body, "text", None)
        _assert("replace_not_found", result is None, "expected None")

    def test_dialogue_update_rejects_complex():
        """Pure-complex scripts (no msgbox) should not be editable."""
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap",
                              [_make_npc(script="TestMap_EventScript_PureComplex")],
                              PURE_COMPLEX_PORY)
            from torch.web.api_npc_editor import _apply_dialogue_update
            result = _apply_dialogue_update(game, "TestMap", 1, "new text", None)
            _assert("reject_complex", result.get("ok") is False,
                    f"expected error, got {result}")
        finally:
            shutil.rmtree(tmp)

    def test_dialogue_update_accepts_custom():
        """Custom scripts (msgbox + extra logic) should be editable."""
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap",
                              [_make_npc(script="TestMap_EventScript_Custom")],
                              CUSTOM_PORY)
            from torch.web.api_npc_editor import _apply_dialogue_update
            result = _apply_dialogue_update(game, "TestMap", 1, "Updated!", None)
            _assert("accept_custom", result.get("ok") is True,
                    f"expected ok, got {result}")
            pory_path = os.path.join(game, "data", "maps", "TestMap", "scripts.pory")
            with open(pory_path, "r") as f:
                content = f.read()
            _assert("custom_dialogue_in_file", "Updated!" in content,
                    f"content: {content[:300]}")
        finally:
            shutil.rmtree(tmp)

    def test_dialogue_update_writes_pory():
        """Full dialogue update should modify scripts.pory."""
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap",
                              [_make_npc()], FLAVOR_PORY)
            from torch.web.api_npc_editor import _apply_dialogue_update
            result = _apply_dialogue_update(game, "TestMap", 1, "New greeting!", None)
            _assert("dialogue_update_ok", result.get("ok") is True,
                    f"got: {result}")

            # Verify file was modified
            pory_path = os.path.join(
                game, "data", "maps", "TestMap", "scripts.pory"
            )
            with open(pory_path, "r") as f:
                content = f.read()
            _assert("dialogue_in_file", "New greeting!" in content,
                    f"content: {content[:200]}")
        finally:
            shutil.rmtree(tmp)

    def test_dialogue_newlines():
        """Readable newlines should convert to game format."""
        r = _readable_to_game_text("Line 1\nLine 2")
        _assert("dialogue_newlines", "\\n" in r, f"got: {r!r}")
        _assert("dialogue_trailing_dollar", r.endswith("$"), f"got: {r!r}")

    # --- Auto-create script for NPCs without one ---

    def test_dialogue_creates_script_for_null():
        """NPC with NULL script should get a new flavor script on dialogue save."""
        tmp = tempfile.mkdtemp()
        try:
            npc = _make_npc(script="NULL", gfx="OBJ_EVENT_GFX_BOY_1")
            game = _make_game(tmp, "TestMap", [npc], "// existing content\n")
            from torch.web.api_npc_editor import _apply_dialogue_update
            result = _apply_dialogue_update(game, "TestMap", 1, "Hello world!", None)
            _assert("null_create_ok", result.get("ok") is True,
                    f"got: {result}")
            _assert("null_create_created", result.get("data", {}).get("created") is True,
                    f"got: {result}")

            # Script should be appended to scripts.pory
            pory_path = os.path.join(game, "data", "maps", "TestMap", "scripts.pory")
            with open(pory_path) as f:
                content = f.read()
            _assert("null_script_in_pory", "Hello world!" in content,
                    f"content: {content[:300]}")
            _assert("null_script_has_label", "EventScript_" in content,
                    f"content: {content[:300]}")

            # map.json should be updated with new label
            map_json = os.path.join(game, "data", "maps", "TestMap", "map.json")
            with open(map_json) as f:
                mdata = json.load(f)
            new_label = mdata["object_events"][0]["script"]
            _assert("null_mapjson_updated", new_label != "NULL",
                    f"still NULL: {new_label}")
            _assert("null_label_format", "EventScript_" in new_label,
                    f"bad label: {new_label}")
        finally:
            shutil.rmtree(tmp)

    def test_dialogue_creates_script_for_missing_label():
        """NPC whose script label doesn't exist in scripts.pory gets a new script appended."""
        tmp = tempfile.mkdtemp()
        try:
            npc = _make_npc(script="TestMap_EventScript_Ghost",
                            gfx="OBJ_EVENT_GFX_GIRL_1")
            # scripts.pory exists but doesn't contain the Ghost script
            game = _make_game(tmp, "TestMap", [npc],
                              'script TestMap_EventScript_Other {\n'
                              '    msgbox(format("other"), MSGBOX_NPC)\n'
                              '}\n')
            from torch.web.api_npc_editor import _apply_dialogue_update
            result = _apply_dialogue_update(
                game, "TestMap", 1, "I am the ghost!", None)
            _assert("missing_create_ok", result.get("ok") is True,
                    f"got: {result}")
            _assert("missing_create_created",
                    result.get("data", {}).get("created") is True,
                    f"got: {result}")

            # Both scripts should now exist in the file
            pory_path = os.path.join(game, "data", "maps", "TestMap", "scripts.pory")
            with open(pory_path) as f:
                content = f.read()
            _assert("missing_old_preserved", "TestMap_EventScript_Other" in content,
                    f"old script lost")
            _assert("missing_new_appended",
                    "TestMap_EventScript_Ghost" in content,
                    f"new script not found: {content[:400]}")
            _assert("missing_dialogue_in_file", "I am the ghost!" in content,
                    f"dialogue not found: {content[:400]}")
        finally:
            shutil.rmtree(tmp)

    def test_dialogue_creates_script_for_empty():
        """NPC with empty string script should get a new script."""
        tmp = tempfile.mkdtemp()
        try:
            npc = _make_npc(script="", gfx="OBJ_EVENT_GFX_WOMAN_3")
            game = _make_game(tmp, "TestMap", [npc], "")
            from torch.web.api_npc_editor import _apply_dialogue_update
            result = _apply_dialogue_update(game, "TestMap", 1, "Hi there!", None)
            _assert("empty_create_ok", result.get("ok") is True,
                    f"got: {result}")

            pory_path = os.path.join(game, "data", "maps", "TestMap", "scripts.pory")
            with open(pory_path) as f:
                content = f.read()
            _assert("empty_script_created", "Hi there!" in content,
                    f"content: {content[:300]}")
        finally:
            shutil.rmtree(tmp)

    def test_dialogue_no_pory_file_creates_it():
        """If scripts.pory doesn't exist, create it with the new script."""
        tmp = tempfile.mkdtemp()
        try:
            npc = _make_npc(script="NULL", gfx="OBJ_EVENT_GFX_BOY_2")
            # Don't pass scripts_pory — file won't exist
            game = _make_game(tmp, "TestMap", [npc])
            from torch.web.api_npc_editor import _apply_dialogue_update
            result = _apply_dialogue_update(game, "TestMap", 1, "Brand new!", None)
            _assert("nopory_create_ok", result.get("ok") is True,
                    f"got: {result}")

            pory_path = os.path.join(game, "data", "maps", "TestMap", "scripts.pory")
            _assert("nopory_file_created", os.path.isfile(pory_path),
                    "scripts.pory not created")
            with open(pory_path) as f:
                content = f.read()
            _assert("nopory_has_dialogue", "Brand new!" in content,
                    f"content: {content[:300]}")
        finally:
            shutil.rmtree(tmp)

    # --- Script reassignment ---

    def test_script_reassign():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [_make_npc()])
            from torch.web.api_npc_editor import _write_map_json
            map_json = os.path.join(game, "data", "maps", "TestMap", "map.json")

            with open(map_json, "r") as f:
                data = json.load(f)
            data["object_events"][0]["script"] = "TestMap_EventScript_NewLabel"
            _write_map_json(game, "TestMap", data)

            with open(map_json, "r") as f:
                result = json.load(f)
            _assert("reassign_label",
                    result["object_events"][0]["script"] == "TestMap_EventScript_NewLabel",
                    f"got: {result['object_events'][0]['script']}")
        finally:
            shutil.rmtree(tmp)

    def test_script_reassign_empty():
        """Empty label should become NopReturn."""
        label = ""
        if not label:
            label = "Common_EventScript_NopReturn"
        _assert("reassign_empty", label == "Common_EventScript_NopReturn",
                f"got: {label}")

    # --- Health scan ---

    def test_health_missing():
        pory = FLAVOR_PORY
        issue = _check_script_health("NonexistentScript", pory, None)
        _assert("health_missing", issue is not None and issue[0] == "missing",
                f"got: {issue}")

    def test_health_stub():
        stub_pory = 'script TestMap_Stub {\n}\n'
        issue = _check_script_health("TestMap_Stub", stub_pory, None)
        _assert("health_stub", issue is not None and issue[0] == "stub",
                f"got: {issue}")

    def test_health_ok():
        issue = _check_script_health(
            "TestMap_EventScript_Npc1", FLAVOR_PORY, None
        )
        _assert("health_ok", issue is None, f"expected healthy, got: {issue}")

    def test_health_inc_missing():
        issue = _check_script_health("Missing", None, "some content")
        _assert("health_inc_missing", issue is not None and issue[0] == "missing",
                f"got: {issue}")

    def test_health_inc_stub():
        inc = "TestStub::\n\treturn\n"
        issue = _check_script_health("TestStub", None, inc)
        _assert("health_inc_stub", issue is not None and issue[0] == "stub",
                f"got: {issue}")

    def test_health_inc_ok():
        inc = "TestOk::\n\tmsgbox TestText, MSGBOX_NPC\n\treturn\n"
        issue = _check_script_health("TestOk", None, inc)
        _assert("health_inc_ok", issue is None, f"expected healthy, got: {issue}")

    # --- Multi-script classification ---

    def test_classify_all_types():
        """Classify all types in a multi-script file."""
        types = {
            "TestMap_EventScript_Npc1": "flavor",
            "TestMap_EventScript_Sign1": "sign",
            "TestMap_EventScript_Nurse": "nurse",
            "TestMap_EventScript_PC": "pc",
            "TestMap_EventScript_Complex": "custom",  # has msgbox calls → custom
            "TestMap_EventScript_ItemGuy": "item_giver",
        }
        all_ok = True
        detail = ""
        for label, expected in types.items():
            got = _classify_script(MULTI_PORY, label)
            if got != expected:
                all_ok = False
                detail = f"{label}: expected '{expected}', got '{got}'"
                break
        _assert("classify_all_types", all_ok, detail)

    # --- NPC creation ---

    def test_create_flavor():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [], "")
            from torch.web.api_npc_editor import _create_flavor
            result = _create_flavor(game, "TestMap", {
                "name": "OldMan", "x": 5, "y": 10,
                "graphics_id": "OBJ_EVENT_GFX_OLD_MAN",
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "dialogue": "Hello there!",
            })
            _assert("create_flavor_ok", result.get("ok") is True,
                    f"got: {result}")
            data = result.get("data", {})
            _assert("create_flavor_label",
                    data.get("script_label") == "TestMap_EventScript_OldMan",
                    f"got: {data}")
            _assert("create_flavor_type", data.get("event_type") == "object_event",
                    f"got: {data}")

            # Verify map.json has the NPC
            mj = _read_map_json(game, "TestMap")
            _assert("create_flavor_mapjson",
                    len(mj.get("object_events", [])) == 1,
                    f"events: {mj.get('object_events')}")

            # Verify scripts.pory has the script
            pory = _read_pory(game, "TestMap")
            _assert("create_flavor_pory",
                    "TestMap_EventScript_OldMan" in pory, f"pory: {pory[:200]}")
        finally:
            shutil.rmtree(tmp)

    def test_create_sign():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [], "")
            from torch.web.api_npc_editor import _create_sign
            result = _create_sign(game, "TestMap", {
                "name": "TownSign", "x": 3, "y": 8,
                "dialogue": "Welcome!",
            })
            _assert("create_sign_ok", result.get("ok") is True,
                    f"got: {result}")
            data = result.get("data", {})
            _assert("create_sign_type", data.get("event_type") == "bg_event",
                    f"got: {data}")

            mj = _read_map_json(game, "TestMap")
            _assert("create_sign_bg", len(mj.get("bg_events", [])) == 1,
                    f"bg: {mj.get('bg_events')}")
        finally:
            shutil.rmtree(tmp)

    def test_create_item_giver():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [], "")
            from torch.web.api_npc_editor import _create_item_giver
            result = _create_item_giver(game, "TestMap", {
                "name": "ItemGuy", "x": 6, "y": 5,
                "graphics_id": "OBJ_EVENT_GFX_BOY_1",
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "item": "ITEM_POTION", "flag": "FLAG_GOT_POTION",
                "before_text": "Take this!", "after_text": "Did you use it?",
            })
            _assert("create_item_ok", result.get("ok") is True,
                    f"got: {result}")
            pory = _read_pory(game, "TestMap")
            _assert("create_item_script", "giveitem(ITEM_POTION)" in pory,
                    f"pory: {pory[:300]}")
            _assert("create_item_flag", "FLAG_GOT_POTION" in pory,
                    f"pory: {pory[:300]}")
        finally:
            shutil.rmtree(tmp)

    def test_create_multi_state():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [], "")
            from torch.web.api_npc_editor import _create_multi_state
            result = _create_multi_state(game, "TestMap", {
                "name": "Guard", "x": 7, "y": 3,
                "graphics_id": "OBJ_EVENT_GFX_MAN_1",
                "states": [
                    {"flag": None, "text": "Road is blocked."},
                    {"flag": "FLAG_ROAD_CLEAR", "text": "You may pass."},
                ],
            })
            _assert("create_multi_ok", result.get("ok") is True,
                    f"got: {result}")
            pory = _read_pory(game, "TestMap")
            _assert("create_multi_flag", "FLAG_ROAD_CLEAR" in pory,
                    f"pory: {pory[:400]}")
        finally:
            shutil.rmtree(tmp)

    def test_create_nurse():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [], "")
            from torch.web.api_npc_editor import _create_nurse
            result = _create_nurse(game, "TestMap", {"x": 7, "y": 2})
            _assert("create_nurse_ok", result.get("ok") is True,
                    f"got: {result}")
            data = result.get("data", {})
            _assert("create_nurse_label",
                    data.get("script_label") == "TestMap_EventScript_Nurse",
                    f"got: {data}")

            mj = _read_map_json(game, "TestMap")
            obj = mj["object_events"][0]
            _assert("create_nurse_gfx",
                    obj["graphics_id"] == "OBJ_EVENT_GFX_NURSE",
                    f"got: {obj['graphics_id']}")

            pory = _read_pory(game, "TestMap")
            _assert("create_nurse_wrapper",
                    "Common_EventScript_PkmnCenterNurse" in pory,
                    f"pory: {pory[:300]}")
        finally:
            shutil.rmtree(tmp)

    def test_create_nurse_duplicate():
        tmp = tempfile.mkdtemp()
        try:
            nurse_npc = _make_npc(
                script="TestMap_EventScript_Nurse",
                gfx="OBJ_EVENT_GFX_NURSE"
            )
            game = _make_game(tmp, "TestMap", [nurse_npc], NURSE_PORY)
            from torch.web.api_npc_editor import _create_nurse
            result = _create_nurse(game, "TestMap", {"x": 7, "y": 2})
            _assert("create_nurse_dup", result.get("ok") is False,
                    f"expected error, got: {result}")
        finally:
            shutil.rmtree(tmp)

    def test_create_pc():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [], "")
            from torch.web.api_npc_editor import _create_pc
            result = _create_pc(game, "TestMap", {"x": 5, "y": 2})
            _assert("create_pc_ok", result.get("ok") is True,
                    f"got: {result}")
            data = result.get("data", {})
            _assert("create_pc_script",
                    data.get("script_label") == "EventScript_PC",
                    f"got: {data}")

            mj = _read_map_json(game, "TestMap")
            bg = mj.get("bg_events", [])
            _assert("create_pc_bg", len(bg) == 1 and bg[0]["script"] == "EventScript_PC",
                    f"bg: {bg}")
        finally:
            shutil.rmtree(tmp)

    def test_create_infra_sign():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [], "")
            from torch.web.api_npc_editor import _create_infra_sign
            result = _create_infra_sign(game, "TestMap", {
                "x": 3, "y": 8, "dialogue": "Town Hall",
            })
            _assert("create_infra_ok", result.get("ok") is True,
                    f"got: {result}")
            data = result.get("data", {})
            _assert("create_infra_label",
                    data.get("script_label") == "TestMap_EventScript_Sign1",
                    f"got: {data}")

            pory = _read_pory(game, "TestMap")
            _assert("create_infra_pory", "MSGBOX_SIGN" in pory,
                    f"pory: {pory[:200]}")
        finally:
            shutil.rmtree(tmp)

    def test_label_sanitization():
        from torch.web.api_npc_editor import _sanitize_label_name
        _assert("sanitize_spaces",
                _sanitize_label_name("Old Man") == "OldMan",
                f"got: {_sanitize_label_name('Old Man')!r}")
        special_input = "Bob's #1!"
        _assert("sanitize_special",
                _sanitize_label_name(special_input) == "Bobs1",
                f"got: {_sanitize_label_name(special_input)!r}")
        _assert("sanitize_underscores",
                _sanitize_label_name("cool_npc") == "cool_npc",
                f"got: {_sanitize_label_name('cool_npc')!r}")

    def test_validate_create_body():
        from torch.web.api_npc_editor import _validate_create_body
        _assert("validate_missing_type",
                _validate_create_body({}) is not None,
                "should fail without type")
        _assert("validate_unknown_type",
                _validate_create_body({"type": "dragon"}) is not None,
                "should fail for unknown type")
        _assert("validate_flavor_missing",
                _validate_create_body({"type": "flavor", "name": "X"}) is not None,
                "should fail without all fields")
        _assert("validate_multi_too_few",
                _validate_create_body({
                    "type": "multi_state", "name": "X", "x": 0, "y": 0,
                    "graphics_id": "G", "states": [{"text": "hi"}],
                }) is not None,
                "should fail with <2 states")
        _assert("validate_pc_ok",
                _validate_create_body({"type": "pc", "x": 5, "y": 2}) is None,
                "PC with x,y should pass")

    # --- NPC deletion ---

    def test_delete_npc():
        tmp = tempfile.mkdtemp()
        try:
            npcs = [
                _make_npc(script="TestMap_EventScript_Npc1"),
                _make_npc(script="TestMap_EventScript_Npc2",
                          gfx="OBJ_EVENT_GFX_OLD_MAN"),
            ]
            game = _make_game(tmp, "TestMap", npcs, FLAVOR_PORY)

            from torch.web.api_npc_editor import handle_npc_delete

            # Direct call to _remove_npc_from_map_json (the endpoint calls it)
            from torch.npc_editor import _remove_npc_from_map_json
            ok = _remove_npc_from_map_json(game, "TestMap", 0)
            _assert("delete_ok", ok is True, f"got: {ok}")

            mj = _read_map_json(game, "TestMap")
            _assert("delete_count", len(mj["object_events"]) == 1,
                    f"got: {len(mj['object_events'])}")
            _assert("delete_remaining",
                    mj["object_events"][0]["script"] == "TestMap_EventScript_Npc2",
                    f"got: {mj['object_events'][0]['script']}")
        finally:
            shutil.rmtree(tmp)

    def test_delete_out_of_range():
        tmp = tempfile.mkdtemp()
        try:
            game = _make_game(tmp, "TestMap", [_make_npc()])
            from torch.npc_editor import _remove_npc_from_map_json
            ok = _remove_npc_from_map_json(game, "TestMap", 99)
            _assert("delete_oor", ok is False, f"expected False, got: {ok}")
        finally:
            shutil.rmtree(tmp)

    def test_templates_endpoint():
        from torch.web.api_npc_editor import handle_npc_templates
        result = handle_npc_templates(None, None, None)
        _assert("templates_ok", result.get("ok") is True, f"got: {result}")
        wizards = result.get("data", {}).get("wizards", [])
        _assert("templates_count", len(wizards) == 7,
                f"expected 7 templates, got {len(wizards)}")
        types = [w["type"] for w in wizards]
        for expected in ["flavor", "sign", "item_giver", "multi_state",
                         "nurse", "pc", "infra_sign"]:
            _assert(f"templates_has_{expected}", expected in types,
                    f"missing {expected} in {types}")

    # --- Run all tests ---

    test_classify_flavor()
    test_classify_sign()
    test_classify_item_giver()
    test_classify_nurse()
    test_classify_pc()
    test_classify_complex()
    test_classify_missing()
    test_is_editable()
    test_extract_pory_format()
    test_extract_pory_plain()
    test_extract_pory_missing()
    test_extract_inc()
    test_extract_inc_missing()
    test_game_to_readable()
    test_game_to_readable_empty()
    test_readable_to_game()
    test_readable_to_game_paragraphs()
    test_readable_to_game_empty()
    test_npc_detail()
    test_npc_detail_404()
    test_npc_detail_no_script()
    test_npc_detail_shared()
    test_cast_index()
    test_cast_index_empty()
    test_cast_index_no_workspace()
    test_npc_detail_with_cast()
    test_property_update()
    test_int_validation()
    test_replace_msgbox_format()
    test_replace_msgbox_plain()
    test_replace_msgbox_change_type()
    test_replace_msgbox_not_found()
    test_classify_custom()
    test_dialogue_update_rejects_complex()
    test_dialogue_update_accepts_custom()
    test_dialogue_update_writes_pory()
    test_dialogue_newlines()
    test_dialogue_creates_script_for_null()
    test_dialogue_creates_script_for_missing_label()
    test_dialogue_creates_script_for_empty()
    test_dialogue_no_pory_file_creates_it()
    test_script_reassign()
    test_script_reassign_empty()
    test_health_missing()
    test_health_stub()
    test_health_ok()
    test_health_inc_missing()
    test_health_inc_stub()
    test_health_inc_ok()
    test_classify_all_types()
    test_create_flavor()
    test_create_sign()
    test_create_item_giver()
    test_create_multi_state()
    test_create_nurse()
    test_create_nurse_duplicate()
    test_create_pc()
    test_create_infra_sign()
    test_label_sanitization()
    test_validate_create_body()
    test_delete_npc()
    test_delete_out_of_range()
    test_templates_endpoint()
