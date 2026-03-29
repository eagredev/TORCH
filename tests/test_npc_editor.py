"""NPC Editor suite — script parsing, text conversion, template generation."""
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
    _begin_suite("NPC Editor  (parsing, conversion, templates)")

    try:
        from torch.npc_editor import (
            _find_script_file,
            _parse_inc_dialogue,
            _extract_pory_msgbox,
            _game_text_to_readable,
            _readable_to_game_text,
            _generate_flavor_npc,
            _generate_sign,
            _generate_item_giver,
            _generate_multi_state,
            _parse_npc_scripts,
            _extract_inc_strings,
            _replace_msgbox_text,
            _text_to_inc_strings,
            _find_workspace_script,
            _add_object_event,
            _add_bg_event,
            _generate_nurse_wrapper,
            _scan_dead_scripts,
            _collect_local_labels,
            _is_return_stub,
            INFRA_TEMPLATES,
            _remove_pory_script_block,
            _remove_npc_from_map_json,
            _scan_scriptless_npcs,
            _build_cast_index,
            _repair_stale_aliases,
            validate_nurse_script,
            fix_nurse_script,
        )
    except ImportError as e:
        _skip("all npc_editor tests", f"import failed: {e}")
        return

    tmp = tempfile.mkdtemp(prefix="torch_npc_editor_test_")
    try:
        _test_inc_parsing(tmp, _parse_inc_dialogue, _extract_inc_strings)
        _test_pory_parsing(tmp, _extract_pory_msgbox)
        _test_text_conversion(_game_text_to_readable, _readable_to_game_text)
        _test_templates(_generate_flavor_npc, _generate_sign,
                        _generate_item_giver, _generate_multi_state)
        _test_script_location(tmp, _find_script_file)
        _test_npc_script_resolution(tmp, _parse_npc_scripts)
        _test_replace_msgbox(_replace_msgbox_text)
        _test_inc_string_generation(_text_to_inc_strings)
        _test_workspace_detection(tmp, _find_workspace_script)
        _test_add_object_event(tmp, _add_object_event)
        _test_add_bg_event(tmp, _add_bg_event)
        _test_nurse_template(_generate_nurse_wrapper)
        _test_dead_script_scanner(tmp, _scan_dead_scripts, _collect_local_labels)
        _test_infra_template_registry(INFRA_TEMPLATES)
        _test_json_indent_convention(tmp, _add_object_event, _add_bg_event)
        _test_remove_pory_script_block(tmp, _remove_pory_script_block)
        _test_remove_npc_from_map_json(tmp, _remove_npc_from_map_json)
        _test_scan_scriptless_npcs(tmp, _scan_scriptless_npcs)
        _test_cast_index_auto_repair(tmp, _build_cast_index)
        _test_nurse_validation(tmp, validate_nurse_script, fix_nurse_script)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# .inc parsing tests
# ---------------------------------------------------------------------------

def _test_inc_parsing(tmp, _parse_inc_dialogue, _extract_inc_strings):
    """Test .inc dialogue parsing."""

    # ---- Simple MSGBOX_NPC ----
    inc_content = (
        'TestMap_Villager::\n'
        '    msgbox TestMap_Villager_Text, MSGBOX_NPC\n'
        '    end\n'
        '\n'
        'TestMap_Villager_Text:\n'
        '    .string "Welcome to town!$"\n'
    )
    result = _parse_inc_dialogue(inc_content, "TestMap_Villager")
    _assert(
        "inc parse: simple MSGBOX_NPC",
        result is not None and result["text"] == "Welcome to town!$",
        f"got {result}"
    )
    _assert(
        "inc parse: text_label extracted",
        result["text_label"] == "TestMap_Villager_Text",
        f"got {result.get('text_label')}"
    )
    _assert(
        "inc parse: msgbox_type extracted",
        result["msgbox_type"] == "MSGBOX_NPC",
        f"got {result.get('msgbox_type')}"
    )

    # ---- Multi-string text ----
    inc_multi = (
        'Town_Kid::\n'
        '    msgbox Town_Kid_Text, MSGBOX_NPC\n'
        '    end\n'
        '\n'
        'Town_Kid_Text:\n'
        '    .string "Wow, are those your POKeMON?\\n"\n'
        '    .string "They look so cool!$"\n'
    )
    result2 = _parse_inc_dialogue(inc_multi, "Town_Kid")
    _assert(
        "inc parse: multi-string joined",
        result2 is not None
        and "Wow, are those your POKeMON?\\n" in result2["text"]
        and "They look so cool!$" in result2["text"],
        f"got {result2}"
    )

    # ---- Non-existent label ----
    result3 = _parse_inc_dialogue(inc_content, "NonExistent")
    _assert(
        "inc parse: non-existent label returns None",
        result3 is None,
        f"got {result3}"
    )

    # ---- Extract .string lines directly ----
    strings = _extract_inc_strings(inc_multi, "Town_Kid_Text")
    _assert(
        "inc extract: strings joined",
        strings is not None and "Wow" in strings and "cool!$" in strings,
        f"got {strings}"
    )


# ---------------------------------------------------------------------------
# .pory parsing tests
# ---------------------------------------------------------------------------

def _test_pory_parsing(tmp, _extract_pory_msgbox):
    """Test .pory dialogue parsing."""

    # ---- With format() ----
    pory_content = (
        'script TestMap_Villager {\n'
        '    msgbox(format("Welcome to town!\\nIt\'s nice here."), MSGBOX_NPC)\n'
        '}\n'
    )
    result = _extract_pory_msgbox(pory_content, "TestMap_Villager")
    _assert(
        "pory parse: format() msgbox",
        result is not None and "Welcome to town!" in result["text"],
        f"got {result}"
    )
    _assert(
        "pory parse: uses_format=True",
        result["uses_format"] is True,
        f"got {result.get('uses_format')}"
    )
    _assert(
        "pory parse: msgbox_type extracted",
        result["msgbox_type"] == "MSGBOX_NPC",
        f"got {result.get('msgbox_type')}"
    )

    # ---- Without format() ----
    pory_plain = (
        'script TestMap_Sign {\n'
        '    msgbox("Route 101\\nA natural trail.", MSGBOX_SIGN)\n'
        '}\n'
    )
    result2 = _extract_pory_msgbox(pory_plain, "TestMap_Sign")
    _assert(
        "pory parse: plain msgbox (no format)",
        result2 is not None and "Route 101" in result2["text"],
        f"got {result2}"
    )
    _assert(
        "pory parse: uses_format=False for plain",
        result2["uses_format"] is False,
        f"got {result2.get('uses_format')}"
    )

    # ---- Non-existent script ----
    result3 = _extract_pory_msgbox(pory_content, "NoScript")
    _assert(
        "pory parse: non-existent script returns None",
        result3 is None,
        f"got {result3}"
    )

    # ---- Nested braces (if blocks) ----
    pory_nested = (
        'script Town_NPC {\n'
        '    lock\n'
        '    faceplayer\n'
        '    if (flag(FLAG_TEST)) {\n'
        '        msgbox(format("After flag."), MSGBOX_DEFAULT)\n'
        '        release\n'
        '        end\n'
        '    }\n'
        '    msgbox(format("Before flag."), MSGBOX_DEFAULT)\n'
        '    release\n'
        '    end\n'
        '}\n'
    )
    result4 = _extract_pory_msgbox(pory_nested, "Town_NPC")
    _assert(
        "pory parse: nested braces — finds first msgbox",
        result4 is not None and "After flag." in result4["text"],
        f"got {result4}"
    )


# ---------------------------------------------------------------------------
# Text conversion tests
# ---------------------------------------------------------------------------

def _test_text_conversion(_game_text_to_readable, _readable_to_game_text):
    """Test game text <-> readable text conversion."""

    # ---- Game to readable ----
    game_text = "Hello!\\nWelcome to town.\\pThe forest is south.$"
    readable = _game_text_to_readable(game_text)
    _assert(
        "game->readable: \\n becomes newline",
        "\n" in readable and "Hello!" in readable,
        f"got '{readable}'"
    )
    _assert(
        "game->readable: \\p becomes paragraph break",
        "\n\n" in readable,
        f"got '{readable}'"
    )
    _assert(
        "game->readable: $ stripped",
        "$" not in readable,
        f"got '{readable}'"
    )

    # ---- Readable to game ----
    readable_input = "Hello!\n\nWelcome to town."
    game_out = _readable_to_game_text(readable_input)
    _assert(
        "readable->game: paragraph break becomes \\p",
        "\\p" in game_out,
        f"got '{game_out}'"
    )
    _assert(
        "readable->game: text preserved",
        "Hello!" in game_out and "Welcome to town." in game_out,
        f"got '{game_out}'"
    )

    # ---- Empty text ----
    _assert(
        "game->readable: empty returns empty",
        _game_text_to_readable("") == "",
        f"got '{_game_text_to_readable('')}'"
    )
    _assert(
        "readable->game: empty returns empty",
        _readable_to_game_text("") == "",
        f"got '{_readable_to_game_text('')}'"
    )

    # ---- Just $ ----
    _assert(
        "game->readable: just $ returns empty",
        _game_text_to_readable("$") == "",
        f"got '{_game_text_to_readable('$')}'"
    )

    # ---- \\l treated as \\n ----
    game_scroll = "Line one\\lLine two$"
    readable_scroll = _game_text_to_readable(game_scroll)
    _assert(
        "game->readable: \\l treated as newline",
        "Line one\nLine two" == readable_scroll,
        f"got '{readable_scroll}'"
    )


# ---------------------------------------------------------------------------
# Template generation tests
# ---------------------------------------------------------------------------

def _test_templates(_generate_flavor_npc, _generate_sign,
                    _generate_item_giver, _generate_multi_state):
    """Test template generation produces valid Poryscript."""

    # ---- Flavor NPC ----
    flavor = _generate_flavor_npc("TestMap", "TestMap_Villager", "Hello!")
    _assert(
        "template: flavor NPC has script keyword",
        "script TestMap_Villager {" in flavor,
        f"got: {flavor[:60]}"
    )
    _assert(
        "template: flavor NPC has MSGBOX_NPC",
        "MSGBOX_NPC" in flavor,
        f"missing MSGBOX_NPC"
    )
    _assert(
        "template: flavor NPC has format()",
        'format("Hello!")' in flavor,
        f"missing format()"
    )

    # ---- Sign ----
    sign = _generate_sign("Route1", "Route1_Sign", "Route 1")
    _assert(
        "template: sign has MSGBOX_SIGN",
        "MSGBOX_SIGN" in sign,
        f"missing MSGBOX_SIGN"
    )
    _assert(
        "template: sign has script keyword",
        "script Route1_Sign {" in sign,
        f"got: {sign[:60]}"
    )

    # ---- Item Giver ----
    item_giver = _generate_item_giver(
        "Town", "Town_Giver", "ITEM_POTION", "FLAG_GOT_POTION",
        "Take this!", "You already have one."
    )
    _assert(
        "template: item giver has lock/faceplayer",
        "lock" in item_giver and "faceplayer" in item_giver,
        f"missing lock/faceplayer"
    )
    _assert(
        "template: item giver has giveitem",
        "giveitem(ITEM_POTION)" in item_giver,
        f"missing giveitem"
    )
    _assert(
        "template: item giver has flag check",
        "flag(FLAG_GOT_POTION)" in item_giver,
        f"missing flag check"
    )
    _assert(
        "template: item giver has setflag",
        "setflag(FLAG_GOT_POTION)" in item_giver,
        f"missing setflag"
    )
    _assert(
        "template: item giver has bag full check",
        "VAR_RESULT" in item_giver and "bag is too full" in item_giver,
        f"missing bag check"
    )

    # ---- Multi-state ----
    states = [
        {"flag": None, "text": "Initial dialogue."},
        {"flag": "FLAG_BEAT_GYM", "text": "You beat the gym!"},
        {"flag": "FLAG_SAVED_TOWN", "text": "Thank you for saving us!"},
    ]
    multi = _generate_multi_state("Town", "Town_Elder", states)
    _assert(
        "template: multi-state has initial dialogue",
        "Initial dialogue." in multi,
        f"missing initial dialogue"
    )
    _assert(
        "template: multi-state checks flags in reverse order",
        multi.index("FLAG_SAVED_TOWN") < multi.index("FLAG_BEAT_GYM"),
        f"flags not in reverse order"
    )
    _assert(
        "template: multi-state has lock/faceplayer/release/end",
        "lock" in multi and "faceplayer" in multi
        and "release" in multi and "end" in multi,
        f"missing boilerplate"
    )


# ---------------------------------------------------------------------------
# Script file location tests
# ---------------------------------------------------------------------------

def _test_script_location(tmp, _find_script_file):
    """Test script file location."""
    # Clear any cached data
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()
    except ImportError:
        pass

    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    # Create game with both .inc and .pory
    inc_content = 'VillagerScript::\n    msgbox VillagerText, MSGBOX_NPC\n    end\n'
    pory_content = 'script PoryScript {\n    msgbox(format("Hi"), MSGBOX_NPC)\n}\n'

    game = _make_game_map(tmp, "Town", scripts_inc=inc_content,
                          scripts_pory=pory_content)

    # .pory should be found
    path, ftype = _find_script_file(game, "Town", "PoryScript")
    _assert(
        "find_script: finds label in .pory",
        ftype == "pory" and path is not None,
        f"got ({path}, {ftype})"
    )

    # .inc should be found
    path2, ftype2 = _find_script_file(game, "Town", "VillagerScript")
    _assert(
        "find_script: finds label in .inc",
        ftype2 == "inc" and path2 is not None,
        f"got ({path2}, {ftype2})"
    )

    # Non-existent label
    path3, ftype3 = _find_script_file(game, "Town", "NonExistent")
    _assert(
        "find_script: non-existent returns (None, None)",
        path3 is None and ftype3 is None,
        f"got ({path3}, {ftype3})"
    )

    # Empty label
    path4, ftype4 = _find_script_file(game, "Town", "")
    _assert(
        "find_script: empty label returns (None, None)",
        path4 is None and ftype4 is None,
        f"got ({path4}, {ftype4})"
    )

    # .pory takes precedence over .inc for same label
    both_content = (
        inc_content + '\n'
    )
    pory_both = pory_content + '\nscript VillagerScript {\n    msgbox(format("Hi"), MSGBOX_NPC)\n}\n'
    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)
    game2 = _make_game_map(tmp, "Town2", scripts_inc=both_content,
                           scripts_pory=pory_both)
    path5, ftype5 = _find_script_file(game2, "Town2", "VillagerScript")
    _assert(
        "find_script: .pory takes precedence over .inc",
        ftype5 == "pory",
        f"got {ftype5}"
    )


# ---------------------------------------------------------------------------
# NPC script resolution tests
# ---------------------------------------------------------------------------

def _test_npc_script_resolution(tmp, _parse_npc_scripts):
    """Test NPC list + script resolution."""
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()
    except ImportError:
        pass

    shutil.rmtree(os.path.join(tmp, "game"), ignore_errors=True)

    npcs = [
        {
            "object_id": 1, "graphics_id": "OBJ_EVENT_GFX_WOMAN_3",
            "display_name": "Woman 3", "x": 5, "y": 5,
            "script": "Town_Villager", "trainer_type": "TRAINER_TYPE_NONE",
            "flag": "",
        },
        {
            "object_id": 2, "graphics_id": "OBJ_EVENT_GFX_BOY_1",
            "display_name": "Boy 1", "x": 10, "y": 10,
            "script": "", "trainer_type": "TRAINER_TYPE_NONE",
            "flag": "",
        },
    ]

    pory = 'script Town_Villager {\n    msgbox(format("Hello!"), MSGBOX_NPC)\n}\n'
    game = _make_game_map(tmp, "Town", object_events=[
        {"graphics_id": "OBJ_EVENT_GFX_WOMAN_3", "x": 5, "y": 5,
         "script": "Town_Villager", "trainer_type": "TRAINER_TYPE_NONE", "flag": "0"},
    ], scripts_pory=pory)

    infos = _parse_npc_scripts(game, "Town", npcs)
    _assert(
        "npc_scripts: returns parallel list",
        len(infos) == 2,
        f"expected 2, got {len(infos)}"
    )
    _assert(
        "npc_scripts: first NPC has text",
        infos[0]["text"] is not None and "Hello!" in infos[0]["text"],
        f"got {infos[0].get('text')}"
    )
    _assert(
        "npc_scripts: first NPC file_type is pory",
        infos[0]["file_type"] == "pory",
        f"got {infos[0].get('file_type')}"
    )
    _assert(
        "npc_scripts: second NPC (no script) has None text",
        infos[1]["text"] is None,
        f"got {infos[1].get('text')}"
    )


# ---------------------------------------------------------------------------
# Replace msgbox text tests
# ---------------------------------------------------------------------------

def _test_replace_msgbox(_replace_msgbox_text):
    """Test surgical msgbox text replacement."""

    # format() form
    body = '    msgbox(format("Old text"), MSGBOX_NPC)\n'
    replaced = _replace_msgbox_text(body, "New text")
    _assert(
        "replace_msgbox: format() form replaced",
        "New text" in replaced and "Old text" not in replaced,
        f"got: {replaced}"
    )

    # plain form
    body2 = '    msgbox("Old text", MSGBOX_SIGN)\n'
    replaced2 = _replace_msgbox_text(body2, "New text")
    _assert(
        "replace_msgbox: plain form replaced",
        "New text" in replaced2 and "Old text" not in replaced2,
        f"got: {replaced2}"
    )

    # no msgbox — should return unchanged
    body3 = '    lock\n    faceplayer\n'
    replaced3 = _replace_msgbox_text(body3, "New text")
    _assert(
        "replace_msgbox: no msgbox returns unchanged",
        replaced3 == body3,
        f"got: {replaced3}"
    )


# ---------------------------------------------------------------------------
# .inc string generation tests
# ---------------------------------------------------------------------------

def _test_inc_string_generation(_text_to_inc_strings):
    """Test game text -> .string line conversion."""

    # Simple text
    lines = _text_to_inc_strings("Hello!\\nWorld!")
    joined = "".join(lines)
    _assert(
        "inc_strings: contains .string directives",
        '.string' in joined,
        f"got: {joined}"
    )
    _assert(
        "inc_strings: ends with $",
        '$"' in joined,
        f"got: {joined}"
    )

    # Empty text
    lines2 = _text_to_inc_strings("")
    joined2 = "".join(lines2)
    _assert(
        "inc_strings: empty text produces $ only",
        '$' in joined2,
        f"got: {joined2}"
    )


# ---------------------------------------------------------------------------
# Workspace detection tests
# ---------------------------------------------------------------------------

def _test_workspace_detection(tmp, _find_workspace_script):
    """Test TORCH workspace .txt detection."""

    # Create a workspace with a .txt scene file
    ws_dir = os.path.join(tmp, "workspace", "TestMap")
    os.makedirs(ws_dir, exist_ok=True)
    with open(os.path.join(ws_dir, "Intro.txt"), "w") as f:
        f.write("# scene\n")

    project_dir = os.path.join(tmp, "workspace")

    # Direct match
    path = _find_workspace_script(project_dir, "TestMap", "Intro")
    _assert(
        "workspace: finds .txt by direct name match",
        path is not None and path.endswith("Intro.txt"),
        f"got {path}"
    )

    # Suffix match (TestMap_Intro)
    path2 = _find_workspace_script(project_dir, "TestMap", "TestMap_Intro")
    _assert(
        "workspace: finds .txt by suffix match",
        path2 is not None and path2.endswith("Intro.txt"),
        f"got {path2}"
    )

    # No match
    path3 = _find_workspace_script(project_dir, "TestMap", "NonExistent")
    _assert(
        "workspace: no match returns None",
        path3 is None,
        f"got {path3}"
    )

    # No workspace
    path4 = _find_workspace_script(None, "TestMap", "Intro")
    _assert(
        "workspace: None project_dir returns None",
        path4 is None,
        f"got {path4}"
    )


# ---------------------------------------------------------------------------
# _add_object_event tests
# ---------------------------------------------------------------------------

def _test_add_object_event(tmp, _add_object_event):
    """Test adding object_events to map.json."""
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()
    except ImportError:
        pass

    # --- Add NPC to existing map ---
    shutil.rmtree(os.path.join(tmp, "game_obj"), ignore_errors=True)
    game = os.path.join(tmp, "game_obj")
    map_dir = os.path.join(game, "data", "maps", "TestTown")
    os.makedirs(map_dir, exist_ok=True)
    map_data = {"id": "MAP_TEST_TOWN", "name": "TestTown", "object_events": []}
    with open(os.path.join(map_dir, "map.json"), "w") as f:
        json.dump(map_data, f, indent=2)
        f.write("\n")

    obj = {
        "graphics_id": "OBJ_EVENT_GFX_NURSE",
        "x": 7, "y": 2,
        "elevation": 3,
        "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
        "movement_range_x": 0, "movement_range_y": 0,
        "trainer_type": "TRAINER_TYPE_NONE",
        "trainer_sight_or_berry_tree_id": "0",
        "script": "TestTown_EventScript_Nurse",
        "flag": "0",
    }
    idx = _add_object_event(game, "TestTown", obj)
    _assert(
        "add_object_event: returns 1-based index",
        idx == 1,
        f"expected 1, got {idx}"
    )

    # Verify map.json was written correctly
    with open(os.path.join(map_dir, "map.json"), "r") as f:
        result = json.load(f)
    _assert(
        "add_object_event: NPC in map.json",
        len(result["object_events"]) == 1
        and result["object_events"][0]["graphics_id"] == "OBJ_EVENT_GFX_NURSE",
        f"got {result.get('object_events')}"
    )

    # --- Add second NPC ---
    obj2 = dict(obj)
    obj2["graphics_id"] = "OBJ_EVENT_GFX_BOY_1"
    obj2["x"] = 3
    idx2 = _add_object_event(game, "TestTown", obj2)
    _assert(
        "add_object_event: second NPC is index 2",
        idx2 == 2,
        f"expected 2, got {idx2}"
    )

    # --- Creates object_events array if missing ---
    shutil.rmtree(os.path.join(tmp, "game_noarr"), ignore_errors=True)
    game2 = os.path.join(tmp, "game_noarr")
    map_dir2 = os.path.join(game2, "data", "maps", "EmptyMap")
    os.makedirs(map_dir2, exist_ok=True)
    with open(os.path.join(map_dir2, "map.json"), "w") as f:
        json.dump({"id": "MAP_EMPTY", "name": "EmptyMap"}, f, indent=2)
        f.write("\n")

    idx3 = _add_object_event(game2, "EmptyMap", obj)
    _assert(
        "add_object_event: creates array if missing",
        idx3 == 1,
        f"expected 1, got {idx3}"
    )
    with open(os.path.join(map_dir2, "map.json"), "r") as f:
        result2 = json.load(f)
    _assert(
        "add_object_event: array created in JSON",
        "object_events" in result2 and len(result2["object_events"]) == 1,
        f"got keys: {list(result2.keys())}"
    )


# ---------------------------------------------------------------------------
# _add_bg_event tests
# ---------------------------------------------------------------------------

def _test_add_bg_event(tmp, _add_bg_event):
    """Test adding bg_events to map.json."""
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()
    except ImportError:
        pass

    # --- Add bg_event to existing map ---
    shutil.rmtree(os.path.join(tmp, "game_bg"), ignore_errors=True)
    game = os.path.join(tmp, "game_bg")
    map_dir = os.path.join(game, "data", "maps", "TestTown")
    os.makedirs(map_dir, exist_ok=True)
    map_data = {"id": "MAP_TEST_TOWN", "name": "TestTown", "bg_events": []}
    with open(os.path.join(map_dir, "map.json"), "w") as f:
        json.dump(map_data, f, indent=2)
        f.write("\n")

    bg = {
        "type": "sign",
        "x": 4, "y": 1,
        "elevation": 0,
        "player_facing_dir": "BG_EVENT_PLAYER_FACING_ANY",
        "script": "EventScript_PC",
    }
    idx = _add_bg_event(game, "TestTown", bg)
    _assert(
        "add_bg_event: returns 1-based index",
        idx == 1,
        f"expected 1, got {idx}"
    )

    with open(os.path.join(map_dir, "map.json"), "r") as f:
        result = json.load(f)
    _assert(
        "add_bg_event: bg_event in map.json",
        len(result["bg_events"]) == 1
        and result["bg_events"][0]["script"] == "EventScript_PC",
        f"got {result.get('bg_events')}"
    )

    # --- Creates bg_events array if missing ---
    shutil.rmtree(os.path.join(tmp, "game_bg2"), ignore_errors=True)
    game2 = os.path.join(tmp, "game_bg2")
    map_dir2 = os.path.join(game2, "data", "maps", "EmptyMap")
    os.makedirs(map_dir2, exist_ok=True)
    with open(os.path.join(map_dir2, "map.json"), "w") as f:
        json.dump({"id": "MAP_EMPTY", "name": "EmptyMap"}, f, indent=2)
        f.write("\n")

    idx2 = _add_bg_event(game2, "EmptyMap", bg)
    _assert(
        "add_bg_event: creates array if missing",
        idx2 == 1,
        f"expected 1, got {idx2}"
    )


# ---------------------------------------------------------------------------
# Nurse template tests
# ---------------------------------------------------------------------------

def _test_nurse_template(_generate_nurse_wrapper):
    """Test nurse wrapper script generation."""

    wrapper = _generate_nurse_wrapper("TestTown_PokemonCenter_1F",
                                      "TestTown_PokemonCenter_1F_EventScript_Nurse",
                                      1)
    _assert(
        "nurse: wrapper has script keyword",
        "script TestTown_PokemonCenter_1F_EventScript_Nurse {" in wrapper,
        f"got: {wrapper[:80]}"
    )
    _assert(
        "nurse: wrapper sets VAR_0x800B",
        "setvar(VAR_0x800B, 1)" in wrapper,
        f"missing setvar"
    )
    _assert(
        "nurse: wrapper calls shared script",
        "call(Common_EventScript_PkmnCenterNurse)" in wrapper,
        f"missing call"
    )
    _assert(
        "nurse: wrapper has waitmessage/waitbuttonpress/release/end",
        "waitmessage" in wrapper and "waitbuttonpress" in wrapper
        and "release" in wrapper and "end" in wrapper,
        f"missing boilerplate"
    )

    # Test with different local_id
    wrapper3 = _generate_nurse_wrapper("Town", "Town_Nurse", 3)
    _assert(
        "nurse: local_id 3 in VAR_0x800B",
        "setvar(VAR_0x800B, 3)" in wrapper3,
        f"got: {wrapper3}"
    )


# ---------------------------------------------------------------------------
# Dead script scanner tests
# ---------------------------------------------------------------------------

def _test_dead_script_scanner(tmp, _scan_dead_scripts, _collect_local_labels):
    """Test dead script detection."""
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()
    except ImportError:
        pass

    shutil.rmtree(os.path.join(tmp, "game_dead"), ignore_errors=True)
    game = os.path.join(tmp, "game_dead")
    map_dir = os.path.join(game, "data", "maps", "TestTown")
    os.makedirs(map_dir, exist_ok=True)

    # Map with 3 NPCs: one with valid script, one with dead script, one shared
    map_data = {
        "id": "MAP_TEST_TOWN", "name": "TestTown",
        "object_events": [
            {"graphics_id": "OBJ_EVENT_GFX_WOMAN_3", "x": 5, "y": 5,
             "script": "TestTown_EventScript_Woman"},
            {"graphics_id": "OBJ_EVENT_GFX_NURSE", "x": 7, "y": 2,
             "script": "OldMap_PokemonCenter_1F_EventScript_Nurse"},
            {"graphics_id": "OBJ_EVENT_GFX_MAN_4", "x": 11, "y": 2,
             "script": "Common_EventScript_PkmnCenterNurse"},
        ],
    }
    with open(os.path.join(map_dir, "map.json"), "w") as f:
        json.dump(map_data, f, indent=2)
        f.write("\n")

    # Write valid script for the first NPC
    pory = 'script TestTown_EventScript_Woman {\n    msgbox(format("Hi"), MSGBOX_NPC)\n}\n'
    with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
        f.write(pory)

    dead = _scan_dead_scripts(game, "TestTown")
    _assert(
        "dead_scanner: finds dead scripts",
        len(dead) == 1,
        f"expected 1, got {len(dead)}"
    )
    _assert(
        "dead_scanner: identifies correct NPC index",
        dead[0][0] == 1,  # 0-based index of the nurse
        f"expected index 1, got {dead[0][0]}"
    )
    _assert(
        "dead_scanner: does not flag valid script",
        all(d[1].get("script") != "TestTown_EventScript_Woman" for d in dead),
        "flagged valid script"
    )
    _assert(
        "dead_scanner: does not flag shared script",
        all(d[1].get("script") != "Common_EventScript_PkmnCenterNurse" for d in dead),
        "flagged shared script"
    )

    # Test _collect_local_labels with return stubs
    shutil.rmtree(os.path.join(tmp, "game_stub"), ignore_errors=True)
    game2 = os.path.join(tmp, "game_stub")
    map_dir2 = os.path.join(game2, "data", "maps", "StubMap")
    os.makedirs(map_dir2, exist_ok=True)

    inc_content = (
        'StubMap_RealScript::\n'
        '    msgbox StubMap_Text, MSGBOX_NPC\n'
        '    end\n'
        '\n'
        'StubMap_DeadScript::\n'
        '    return\n'
    )
    with open(os.path.join(map_dir2, "scripts.inc"), "w") as f:
        f.write(inc_content)

    labels = _collect_local_labels(map_dir2)
    _assert(
        "collect_labels: includes real scripts",
        "StubMap_RealScript" in labels,
        f"missing real script, got {labels}"
    )
    _assert(
        "collect_labels: excludes return stubs",
        "StubMap_DeadScript" not in labels,
        f"should not include stub, got {labels}"
    )


# ---------------------------------------------------------------------------
# Template registry tests
# ---------------------------------------------------------------------------

def _test_infra_template_registry(INFRA_TEMPLATES):
    """Test template registry has correct structure."""

    _assert(
        "registry: has 3 templates",
        len(INFRA_TEMPLATES) == 3,
        f"expected 3, got {len(INFRA_TEMPLATES)}"
    )

    keys = [t["key"] for t in INFRA_TEMPLATES]
    _assert(
        "registry: has nurse/pc/sign keys",
        "nurse" in keys and "pc" in keys and "sign" in keys,
        f"got keys: {keys}"
    )

    nurse = next(t for t in INFRA_TEMPLATES if t["key"] == "nurse")
    _assert(
        "registry: nurse is object_event type",
        nurse["event_type"] == "object_event",
        f"got {nurse['event_type']}"
    )
    _assert(
        "registry: nurse has OBJ_EVENT_GFX_NURSE default",
        nurse["defaults"]["graphics_id"] == "OBJ_EVENT_GFX_NURSE",
        f"got {nurse['defaults'].get('graphics_id')}"
    )
    _assert(
        "registry: nurse needs wrapper",
        nurse["needs_wrapper"] is True,
        f"got {nurse['needs_wrapper']}"
    )

    pc = next(t for t in INFRA_TEMPLATES if t["key"] == "pc")
    _assert(
        "registry: pc is bg_event type",
        pc["event_type"] == "bg_event",
        f"got {pc['event_type']}"
    )
    _assert(
        "registry: pc shared script is EventScript_PC",
        pc["shared_script"] == "EventScript_PC",
        f"got {pc['shared_script']}"
    )
    _assert(
        "registry: pc does not need wrapper",
        pc["needs_wrapper"] is False,
        f"got {pc['needs_wrapper']}"
    )

    sign = next(t for t in INFRA_TEMPLATES if t["key"] == "sign")
    _assert(
        "registry: sign is bg_event type",
        sign["event_type"] == "bg_event",
        f"got {sign['event_type']}"
    )
    _assert(
        "registry: sign has no shared script",
        sign["shared_script"] is None,
        f"got {sign['shared_script']}"
    )


# ---------------------------------------------------------------------------
# JSON indent convention tests
# ---------------------------------------------------------------------------

def _test_json_indent_convention(tmp, _add_object_event, _add_bg_event):
    """Test that map.json writes use indent=2 (Porymap convention)."""
    try:
        from torch.project_files import clear_project_cache
        clear_project_cache()
    except ImportError:
        pass

    shutil.rmtree(os.path.join(tmp, "game_indent"), ignore_errors=True)
    game = os.path.join(tmp, "game_indent")
    map_dir = os.path.join(game, "data", "maps", "IndentTest")
    os.makedirs(map_dir, exist_ok=True)
    with open(os.path.join(map_dir, "map.json"), "w") as f:
        json.dump({"id": "MAP_INDENT_TEST", "name": "IndentTest",
                    "object_events": [], "bg_events": []}, f, indent=2)
        f.write("\n")

    _add_object_event(game, "IndentTest", {
        "graphics_id": "OBJ_EVENT_GFX_BOY_1",
        "x": 1, "y": 1,
        "elevation": 3,
        "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
        "movement_range_x": 0, "movement_range_y": 0,
        "trainer_type": "TRAINER_TYPE_NONE",
        "trainer_sight_or_berry_tree_id": "0",
        "script": "Test",
        "flag": "0",
    })

    with open(os.path.join(map_dir, "map.json"), "r") as f:
        raw = f.read()

    # indent=2 means 2-space indentation, not 4
    _assert(
        "json_indent: uses 2-space indent (not 4)",
        '  "id"' in raw and '    "id"' not in raw,
        f"wrong indent detected"
    )
    _assert(
        "json_indent: file ends with newline",
        raw.endswith("\n"),
        f"missing trailing newline"
    )


# ---------------------------------------------------------------------------
# _remove_pory_script_block tests
# ---------------------------------------------------------------------------

def _test_remove_pory_script_block(tmp, _remove_pory_script_block):
    """Test .pory script block removal."""

    pory_dir = os.path.join(tmp, "remove_block")
    os.makedirs(pory_dir, exist_ok=True)

    # ---- Simple single script removal ----
    pory1 = os.path.join(pory_dir, "simple.pory")
    with open(pory1, "w") as f:
        f.write(
            'script TestMap_Greeter {\n'
            '    msgbox(format("Hello!"), MSGBOX_NPC)\n'
            '}\n'
        )
    ok = _remove_pory_script_block(pory1, "TestMap_Greeter")
    _assert("remove_block: single script removed", ok, "returned False")
    with open(pory1, "r") as f:
        remaining = f.read()
    _assert(
        "remove_block: file is empty after removal",
        remaining.strip() == "",
        f"remaining: {remaining!r}"
    )

    # ---- Remove one script, keep another ----
    pory2 = os.path.join(pory_dir, "multi.pory")
    with open(pory2, "w") as f:
        f.write(
            'script TestMap_Greeter {\n'
            '    msgbox(format("Hello!"), MSGBOX_NPC)\n'
            '}\n'
            '\n'
            'script TestMap_SignPost {\n'
            '    msgbox(format("Town Square"), MSGBOX_SIGN)\n'
            '}\n'
        )
    ok = _remove_pory_script_block(pory2, "TestMap_Greeter")
    _assert("remove_block: multi - removed target", ok, "returned False")
    with open(pory2, "r") as f:
        remaining = f.read()
    _assert(
        "remove_block: kept other script",
        "TestMap_SignPost" in remaining,
        f"remaining: {remaining!r}"
    )
    _assert(
        "remove_block: target gone",
        "TestMap_Greeter" not in remaining,
        f"remaining: {remaining!r}"
    )

    # ---- Remove script with orphaned text block ----
    pory3 = os.path.join(pory_dir, "text_block.pory")
    with open(pory3, "w") as f:
        f.write(
            'script TestMap_NPC {\n'
            '    msgbox(TestMap_NPC_Text, MSGBOX_NPC)\n'
            '}\n'
            '\n'
            'text TestMap_NPC_Text {\n'
            '    "Hello there!"\n'
            '}\n'
            '\n'
            'script TestMap_Other {\n'
            '    msgbox(format("Hi"), MSGBOX_NPC)\n'
            '}\n'
        )
    ok = _remove_pory_script_block(pory3, "TestMap_NPC")
    _assert("remove_block: script+text - removed", ok, "returned False")
    with open(pory3, "r") as f:
        remaining = f.read()
    _assert(
        "remove_block: orphaned text block removed",
        "TestMap_NPC_Text" not in remaining,
        f"remaining: {remaining!r}"
    )
    _assert(
        "remove_block: other script kept",
        "TestMap_Other" in remaining,
        f"remaining: {remaining!r}"
    )

    # ---- Shared text block NOT removed ----
    pory4 = os.path.join(pory_dir, "shared_text.pory")
    with open(pory4, "w") as f:
        f.write(
            'script TestMap_A {\n'
            '    msgbox(TestMap_Shared_Text, MSGBOX_NPC)\n'
            '}\n'
            '\n'
            'script TestMap_B {\n'
            '    msgbox(TestMap_Shared_Text, MSGBOX_NPC)\n'
            '}\n'
            '\n'
            'text TestMap_Shared_Text {\n'
            '    "Shared!"\n'
            '}\n'
        )
    ok = _remove_pory_script_block(pory4, "TestMap_A")
    _assert("remove_block: shared text - removed script", ok, "returned False")
    with open(pory4, "r") as f:
        remaining = f.read()
    _assert(
        "remove_block: shared text block kept",
        "TestMap_Shared_Text" in remaining,
        f"remaining: {remaining!r}"
    )
    _assert(
        "remove_block: other script kept",
        "TestMap_B" in remaining,
        f"remaining: {remaining!r}"
    )

    # ---- Non-existent label returns False ----
    pory5 = os.path.join(pory_dir, "nope.pory")
    with open(pory5, "w") as f:
        f.write('script Exists {\n    msgbox(format("X"), MSGBOX_NPC)\n}\n')
    ok = _remove_pory_script_block(pory5, "DoesNotExist")
    _assert("remove_block: non-existent label returns False", not ok, "returned True")

    # ---- Nested braces (complex script) ----
    pory6 = os.path.join(pory_dir, "nested.pory")
    with open(pory6, "w") as f:
        f.write(
            'script TestMap_Complex {\n'
            '    if (flag(FLAG_A)) {\n'
            '        msgbox(format("Yes"), MSGBOX_NPC)\n'
            '    } else {\n'
            '        msgbox(format("No"), MSGBOX_NPC)\n'
            '    }\n'
            '}\n'
            '\n'
            'script TestMap_Keep {\n'
            '    msgbox(format("Keep me"), MSGBOX_NPC)\n'
            '}\n'
        )
    ok = _remove_pory_script_block(pory6, "TestMap_Complex")
    _assert("remove_block: nested braces removed", ok, "returned False")
    with open(pory6, "r") as f:
        remaining = f.read()
    _assert(
        "remove_block: nested - target gone",
        "TestMap_Complex" not in remaining,
        f"remaining: {remaining!r}"
    )
    _assert(
        "remove_block: nested - other kept",
        "TestMap_Keep" in remaining,
        f"remaining: {remaining!r}"
    )


# ---------------------------------------------------------------------------
# _remove_npc_from_map_json tests
# ---------------------------------------------------------------------------

def _test_remove_npc_from_map_json(tmp, _remove_npc_from_map_json):
    """Test NPC removal from map.json."""

    game = os.path.join(tmp, "game_del_npc")
    map_dir = os.path.join(game, "data", "maps", "DelTest")
    os.makedirs(map_dir, exist_ok=True)

    events = [
        {"graphics_id": "OBJ_EVENT_GFX_BOY_1", "script": "A", "x": 1, "y": 1},
        {"graphics_id": "OBJ_EVENT_GFX_GIRL_1", "script": "B", "x": 2, "y": 2},
        {"graphics_id": "OBJ_EVENT_GFX_OLD_MAN", "script": "C", "x": 3, "y": 3},
    ]
    map_json = os.path.join(map_dir, "map.json")
    with open(map_json, "w") as f:
        json.dump({"id": "MAP_DELTEST", "object_events": events}, f, indent=2)
        f.write("\n")

    # Remove middle NPC (index 1)
    ok = _remove_npc_from_map_json(game, "DelTest", 1)
    _assert("remove_npc: returns True", ok, "returned False")

    with open(map_json, "r") as f:
        data = json.load(f)

    _assert(
        "remove_npc: 2 NPCs remaining",
        len(data["object_events"]) == 2,
        f"got {len(data['object_events'])}"
    )
    _assert(
        "remove_npc: girl removed",
        all(e["graphics_id"] != "OBJ_EVENT_GFX_GIRL_1" for e in data["object_events"]),
        f"girl still present"
    )
    _assert(
        "remove_npc: boy and old man remain",
        data["object_events"][0]["script"] == "A"
        and data["object_events"][1]["script"] == "C",
        f"wrong order: {data['object_events']}"
    )

    # Verify indent=2
    with open(map_json, "r") as f:
        raw = f.read()
    _assert(
        "remove_npc: uses indent=2",
        '  "id"' in raw and '    "id"' not in raw,
        f"wrong indent"
    )
    _assert(
        "remove_npc: trailing newline",
        raw.endswith("\n"),
        f"no trailing newline"
    )

    # Out of range index
    ok = _remove_npc_from_map_json(game, "DelTest", 99)
    _assert("remove_npc: out of range returns False", not ok, "returned True")


# ---------------------------------------------------------------------------
# _scan_scriptless_npcs tests
# ---------------------------------------------------------------------------

def _test_scan_scriptless_npcs(tmp, _scan_scriptless_npcs):
    """Test scriptless NPC detection."""

    game = os.path.join(tmp, "game_scriptless")
    map_dir = os.path.join(game, "data", "maps", "TestMap")
    os.makedirs(map_dir, exist_ok=True)

    events = [
        {"graphics_id": "OBJ_EVENT_GFX_BOY_1", "script": "TestMap_Boy", "x": 1, "y": 1},
        {"graphics_id": "OBJ_EVENT_GFX_TWIN", "script": "", "x": 2, "y": 2},
        {"graphics_id": "OBJ_EVENT_GFX_GIRL_1", "script": "TestMap_Girl", "x": 3, "y": 3},
        {"graphics_id": "OBJ_EVENT_GFX_OLD_MAN", "script": "0", "x": 4, "y": 4},
    ]
    with open(os.path.join(map_dir, "map.json"), "w") as f:
        json.dump({"id": "MAP_TESTMAP", "object_events": events}, f, indent=2)

    result = _scan_scriptless_npcs(game, "TestMap")
    _assert(
        "scriptless: finds 2 scriptless NPCs",
        len(result) == 2,
        f"got {len(result)}"
    )
    _assert(
        "scriptless: first is Twin (index 1)",
        result[0][0] == 1 and result[0][1]["graphics_id"] == "OBJ_EVENT_GFX_TWIN",
        f"got index {result[0][0]}, gfx {result[0][1].get('graphics_id')}"
    )
    _assert(
        "scriptless: second is OldMan (index 3)",
        result[1][0] == 3 and result[1][1]["graphics_id"] == "OBJ_EVENT_GFX_OLD_MAN",
        f"got index {result[1][0]}, gfx {result[1][1].get('graphics_id')}"
    )

    # All NPCs have scripts — should return empty
    events2 = [
        {"graphics_id": "OBJ_EVENT_GFX_BOY_1", "script": "Script_A", "x": 1, "y": 1},
    ]
    game2 = os.path.join(tmp, "game_scriptless2")
    map_dir2 = os.path.join(game2, "data", "maps", "TestMap2")
    os.makedirs(map_dir2, exist_ok=True)
    with open(os.path.join(map_dir2, "map.json"), "w") as f:
        json.dump({"id": "MAP_TESTMAP2", "object_events": events2}, f, indent=2)

    result2 = _scan_scriptless_npcs(game2, "TestMap2")
    _assert(
        "scriptless: no scriptless NPCs returns empty",
        len(result2) == 0,
        f"got {len(result2)}"
    )


def _test_cast_index_auto_repair(tmp, _build_cast_index):
    """Test _build_cast_index with auto-repair of stale alias NPC IDs."""

    # Set up game map with 3 NPCs at known positions
    repair_events = [
        {"graphics_id": "OBJ_EVENT_GFX_BOY_1", "script": "TestMap_Officer",
         "x": 1, "y": 1, "trainer_type": "TRAINER_TYPE_NONE", "flag": "0"},
        {"graphics_id": "OBJ_EVENT_GFX_ROCKET_M", "script": "TestMap_Buster",
         "x": 2, "y": 2, "trainer_type": "TRAINER_TYPE_NONE", "flag": "0"},
        {"graphics_id": "OBJ_EVENT_GFX_ROCKET_M", "script": "TestMap_Clyde",
         "x": 3, "y": 3, "trainer_type": "TRAINER_TYPE_NONE", "flag": "0"},
    ]
    repair_game = os.path.join(tmp, "game_repair")
    repair_map_dir = os.path.join(repair_game, "data", "maps", "TestMap")
    os.makedirs(repair_map_dir, exist_ok=True)
    with open(os.path.join(repair_map_dir, "map.json"), "w") as f:
        json.dump({"id": "MAP_TESTMAP", "name": "TestMap",
                   "object_events": repair_events}, f, indent=2)

    # Set up workspace with stale alias IDs (npc5/npc6 instead of npc2/npc3)
    repair_ws = os.path.join(tmp, "ws_repair")
    repair_ws_map = os.path.join(repair_ws, "TestMap")
    os.makedirs(repair_ws_map, exist_ok=True)

    stale_script = (
        "# Cutscene\n"
        "\n"
        "alias buster npc5\n"
        "alias clyde npc6\n"
        "\n"
        "label TestMap_ClydeArrives\n"
        "msg \"hello$\"\n"
        "pory end\n"
    )
    stale_path = os.path.join(repair_ws_map, "ClydeArrives.txt")
    with open(stale_path, "w") as f:
        f.write(stale_script)

    # Without game_path: no repair, uses stale IDs
    cast_no_repair = _build_cast_index(repair_ws, "TestMap")
    _assert(
        "cast_index: no game_path uses stale IDs",
        5 in cast_no_repair and 6 in cast_no_repair,
        f"keys = {sorted(cast_no_repair.keys())}"
    )

    # Re-write stale file (previous call didn't repair)
    with open(stale_path, "w") as f:
        f.write(stale_script)

    # With game_path: auto-repair corrects npc5→npc2, npc6→npc3
    cast_repaired = _build_cast_index(repair_ws, "TestMap",
                                      game_path=repair_game)
    _assert(
        "cast_index: auto-repair corrects stale IDs",
        2 in cast_repaired and 3 in cast_repaired,
        f"keys = {sorted(cast_repaired.keys())}"
    )
    _assert(
        "cast_index: stale IDs no longer present",
        5 not in cast_repaired and 6 not in cast_repaired,
        f"keys = {sorted(cast_repaired.keys())}"
    )

    # Verify the file was actually rewritten
    with open(stale_path) as f:
        repaired_content = f.read()
    _assert(
        "cast_index: file rewritten with correct IDs",
        "alias buster npc2" in repaired_content
        and "alias clyde npc3" in repaired_content,
        f"content = {repaired_content[:100]}"
    )

    # Aliases that already match should not be modified
    correct_script = (
        "# Already correct\n"
        "\n"
        "alias buster npc2\n"
        "\n"
        "label TestMap_Buster\n"
        "msg \"hi$\"\n"
    )
    correct_path = os.path.join(repair_ws_map, "Buster.txt")
    with open(correct_path, "w") as f:
        f.write(correct_script)

    cast_correct = _build_cast_index(repair_ws, "TestMap",
                                     game_path=repair_game)
    _assert(
        "cast_index: correct aliases unchanged",
        2 in cast_correct,
        f"keys = {sorted(cast_correct.keys())}"
    )
    with open(correct_path) as f:
        unchanged = f.read()
    _assert(
        "cast_index: correct file not modified",
        unchanged == correct_script,
        f"content changed"
    )

    # Multi-script NPC: ClydeArrives should appear under both npc2 and npc3
    _assert(
        "cast_index: ClydeArrives under buster (npc2)",
        any(s == "ClydeArrives" for _, s, _ in cast_correct.get(2, [])),
        f"npc2 entries = {cast_correct.get(2, [])}"
    )
    _assert(
        "cast_index: ClydeArrives under clyde (npc3)",
        any(s == "ClydeArrives" for _, s, _ in cast_correct.get(3, [])),
        f"npc3 entries = {cast_correct.get(3, [])}"
    )


def _test_nurse_validation(tmp, validate_nurse_script, fix_nurse_script):
    """Test validate_nurse_script and fix_nurse_script."""

    # validate_nurse_script — no nurse NPC
    nv_game = _make_game_map(tmp, "TestNoNurse", object_events=[
        {"graphics_id": "OBJ_EVENT_GFX_MAN_4", "x": 5, "y": 3,
         "script": "TestNoNurse_EventScript_Man", "flag": "0"},
    ])
    result_none = validate_nurse_script(nv_game, "TestNoNurse")
    _assert("validate_nurse: no nurse returns None",
            result_none is None, f"got {result_none}")

    # validate_nurse_script — nurse with working script in pory
    nv_game2 = _make_game_map(tmp, "TestNurseOk", object_events=[
        {"graphics_id": "OBJ_EVENT_GFX_NURSE", "x": 7, "y": 2,
         "script": "TestNurseOk_EventScript_Nurse", "flag": "0"},
    ], scripts_pory="script TestNurseOk_EventScript_Nurse { lock\n end\n}\n")
    result_ok = validate_nurse_script(nv_game2, "TestNurseOk")
    _assert("validate_nurse: ok script",
            result_ok is not None and result_ok["script_ok"],
            f"got {result_ok}")

    # validate_nurse_script — nurse with broken/missing script
    nv_game3 = _make_game_map(tmp, "TestNurseBroken", object_events=[
        {"graphics_id": "OBJ_EVENT_GFX_NURSE", "x": 7, "y": 2,
         "script": "TestNurseBroken_EventScript_Nurse", "flag": "0"},
    ])
    result_broken = validate_nurse_script(nv_game3, "TestNurseBroken")
    _assert("validate_nurse: broken script",
            result_broken is not None and not result_broken["script_ok"]
            and result_broken["fixable"],
            f"got {result_broken}")

    # validate_nurse_script — shared script (Common_EventScript_PkmnCenterNurse)
    nv_game4 = _make_game_map(tmp, "TestNurseShared", object_events=[
        {"graphics_id": "OBJ_EVENT_GFX_NURSE", "x": 7, "y": 2,
         "script": "Common_EventScript_PkmnCenterNurse", "flag": "0"},
    ])
    result_shared = validate_nurse_script(nv_game4, "TestNurseShared")
    _assert("validate_nurse: shared script ok",
            result_shared is not None and result_shared["script_ok"],
            f"got {result_shared}")

    # fix_nurse_script — auto-fix a broken nurse
    nv_game5 = _make_game_map(tmp, "TestNurseFix", object_events=[
        {"graphics_id": "OBJ_EVENT_GFX_NURSE", "x": 7, "y": 2,
         "script": "TestNurseFix_EventScript_Nurse", "flag": "0"},
    ])
    fix_ok = fix_nurse_script(nv_game5, "TestNurseFix")
    _assert("fix_nurse: returns True", fix_ok)

    # Verify the wrapper was written
    fix_pory = os.path.join(nv_game5, "data", "maps", "TestNurseFix", "scripts.pory")
    _assert("fix_nurse: pory file created", os.path.isfile(fix_pory))
    with open(fix_pory, "r") as f:
        pory_content = f.read()
    _assert("fix_nurse: calls shared nurse script",
            "Common_EventScript_PkmnCenterNurse" in pory_content,
            f"content: {pory_content[:200]}")

    # After fix, validate should report ok
    result_fixed = validate_nurse_script(nv_game5, "TestNurseFix")
    _assert("fix_nurse: validate reports ok after fix",
            result_fixed is not None and result_fixed["script_ok"],
            f"got {result_fixed}")
