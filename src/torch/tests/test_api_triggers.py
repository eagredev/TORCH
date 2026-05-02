"""Tests for the Trigger API endpoints (api_triggers.py)."""
import json
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _assert, _skip


# ---------------------------------------------------------------------------
# Test fixture helpers
# ---------------------------------------------------------------------------

def _make_game_tree(tmp):
    """Create a minimal game directory with a map that has coord_events."""
    map_dir = os.path.join(tmp, "data", "maps", "TestRoute")
    os.makedirs(map_dir)
    map_json = {
        "object_events": [],
        "warp_events": [],
        "coord_events": [
            {
                "type": "trigger",
                "x": 5,
                "y": 10,
                "elevation": 0,
                "var": "VAR_TEMP_1",
                "var_value": "0",
                "script": "TestRoute_Trigger_Rain",
            },
            {
                "type": "trigger",
                "x": 12,
                "y": 3,
                "elevation": 3,
                "var": "0",
                "var_value": "0",
                "script": "TestRoute_Trigger_Cutscene",
            },
        ],
        "bg_events": [],
    }
    with open(os.path.join(map_dir, "map.json"), "w") as f:
        json.dump(map_json, f, indent=2)

    # Scripts file
    with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
        f.write(
            'script TestRoute_Trigger_Rain {\n'
            '    lock\n'
            '    setweather(WEATHER_RAIN)\n'
            '    doweather\n'
            '    release\n'
            '}\n'
        )

    # Empty map
    empty_dir = os.path.join(tmp, "data", "maps", "EmptyMap")
    os.makedirs(empty_dir)
    with open(os.path.join(empty_dir, "map.json"), "w") as f:
        json.dump({"object_events": [], "coord_events": []}, f)

    return tmp


def _load_map_json(tmp, map_name):
    """Load map.json from the test game tree."""
    path = os.path.join(tmp, "data", "maps", map_name, "map.json")
    with open(path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Direct function tests (no HTTP server needed)
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("API Triggers")

    # 1. Import test
    try:
        from torch.web.api_triggers import (
            _generate_script_label,
            _sanitize_label,
            _TEMPLATES,
            _TEMPLATE_META,
            _torscript_to_pory_skeleton,
        )
        _ok("import api_triggers")
    except Exception as exc:
        _fail("import api_triggers", str(exc))
        return

    # 2. Label generation -- default (no custom)
    label = _generate_script_label("TestRoute", 5, 10)
    _assert("label_default",
            label == "TestRoute_Trigger_5_10",
            f"got {label}")

    # 3. Label generation -- with custom label
    label = _generate_script_label("TestRoute", 5, 10, "RainTrigger")
    _assert("label_custom",
            label == "TestRoute_EventScript_RainTrigger",
            f"got {label}")

    # 4. Label generation -- custom label with special chars
    label = _generate_script_label("TestRoute", 5, 10, "Rain Trigger!")
    _assert("label_custom_sanitized",
            label == "TestRoute_EventScript_RainTrigger",
            f"got {label}")

    # 5. Label generation -- empty custom falls back to coordinate
    label = _generate_script_label("TestRoute", 5, 10, "")
    _assert("label_empty_custom_fallback",
            label == "TestRoute_Trigger_5_10",
            f"got {label}")

    # 6. Sanitize label
    _assert("sanitize_label_removes_specials",
            _sanitize_label("Hello World!") == "HelloWorld")
    _assert("sanitize_label_keeps_valid",
            _sanitize_label("abc_123") == "abc_123")

    # 7. Template registry has expected templates
    template_ids = [t["id"] for t in _TEMPLATE_META]
    for expected_id in ["basic", "cutscene", "weather_change", "warp", "item_check", "one_time"]:
        _assert(f"template_{expected_id}_registered",
                expected_id in template_ids,
                f"missing from {template_ids}")

    # 8. Templates all have proper keys
    for tpl in _TEMPLATE_META:
        _assert(f"template_{tpl['id']}_has_keys",
                "id" in tpl and "name" in tpl and "description" in tpl,
                f"keys: {list(tpl.keys())}")

    # 9. TorScript templates contain {label} placeholder
    for tpl_id, tpl_text in _TEMPLATES.items():
        _assert(f"template_{tpl_id}_has_label_placeholder",
                "{label}" in tpl_text)

    # 10. Pory skeleton generation -- basic
    pory = _torscript_to_pory_skeleton("Test_Script", "basic")
    _assert("pory_basic_has_label",
            "script Test_Script" in pory,
            f"got: {pory[:80]}")
    _assert("pory_basic_has_lock_release",
            "lock" in pory and "release" in pory)

    # 11. Pory skeleton -- cutscene
    pory = _torscript_to_pory_skeleton("Test_Cut", "cutscene")
    _assert("pory_cutscene_lockall",
            "lockall" in pory and "releaseall" in pory)

    # 12. Pory skeleton -- weather
    pory = _torscript_to_pory_skeleton("Test_Weather", "weather_change")
    _assert("pory_weather_commands",
            "setweather" in pory and "doweather" in pory)

    # 13. Pory skeleton -- warp
    pory = _torscript_to_pory_skeleton("Test_Warp", "warp")
    _assert("pory_warp_command",
            "warpsilent" in pory)

    # 14. Pory skeleton -- one_time
    pory = _torscript_to_pory_skeleton("Test_Once", "one_time", "FLAG_TEMP_5")
    _assert("pory_onetime_flag",
            "setflag(FLAG_TEMP_5)" in pory,
            f"got: {pory}")

    # 15. Pory skeleton -- item_check
    pory = _torscript_to_pory_skeleton("Test_Item", "item_check")
    _assert("pory_itemcheck_commands",
            "checkitem" in pory and "VAR_RESULT" in pory)

    # --- Direct API function tests (mock handler) ---
    from torch.web.api_triggers import (
        handle_trigger_list,
        handle_trigger_create,
        handle_trigger_update,
        handle_trigger_delete,
        handle_trigger_templates,
    )
    from torch.project_files import clear_project_cache
    import re

    tmp = tempfile.mkdtemp()
    try:
        _make_game_tree(tmp)
        clear_project_cache()

        # Mock handler with server attribute
        class MockServer:
            def __init__(self):
                self.game_path = tmp
                self.project_dir = ""

        class MockHandler:
            def __init__(self):
                self.server = MockServer()
                self._body = None

            def _set_body(self, data):
                self._body = json.dumps(data).encode()

        handler = MockHandler()

        # 16. List triggers
        match = re.match(
            r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
            "/api/map/TestRoute/triggers"
        )
        result = handle_trigger_list(handler, match, {})
        _assert("list_triggers_ok", result["ok"] is True)
        _assert("list_triggers_count",
                result["data"]["count"] == 2,
                f"got {result['data']['count']}")
        triggers = result["data"]["triggers"]
        _assert("list_triggers_first_coords",
                triggers[0]["x"] == 5 and triggers[0]["y"] == 10)
        _assert("list_triggers_first_script",
                triggers[0]["script"] == "TestRoute_Trigger_Rain")
        _assert("list_triggers_second_var",
                triggers[1]["var"] == "0")

        # 17. List triggers -- empty map
        clear_project_cache()
        match = re.match(
            r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
            "/api/map/EmptyMap/triggers"
        )
        result = handle_trigger_list(handler, match, {})
        _assert("list_triggers_empty_ok", result["ok"] is True)
        _assert("list_triggers_empty_count", result["data"]["count"] == 0)

        # 18. List triggers -- nonexistent map
        clear_project_cache()
        match = re.match(
            r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
            "/api/map/NoSuchMap/triggers"
        )
        result = handle_trigger_list(handler, match, {})
        _assert("list_triggers_404", result["ok"] is False)

        # 19. Templates endpoint
        result = handle_trigger_templates(handler, None, {})
        _assert("templates_ok", result["ok"] is True)
        _assert("templates_count",
                len(result["data"]["templates"]) >= 6,
                f"got {len(result['data']['templates'])}")

        # 20. Create trigger -- mock _read_json_body
        clear_project_cache()
        import torch.web.api_triggers as api_mod
        try:
            from torch.web import api as api_base
            _orig_read_base = api_base._read_json_body
            _orig_read_mod = api_mod._read_json_body

            def _mock_read(handler):
                return json.loads(handler._body)

            api_base._read_json_body = _mock_read
            api_mod._read_json_body = _mock_read

            handler._body = json.dumps({
                "x": 8, "y": 15,
                "elevation": 2,
                "var": "VAR_TEMP_3",
                "var_value": "1",
                "template": "basic",
                "script_label": "TestRainEvent",
            }).encode()

            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
                "/api/map/TestRoute/triggers"
            )
            result = handle_trigger_create(handler, match, {})
            _assert("create_trigger_ok",
                    result["ok"] is True,
                    f"got: {result}")
            _assert("create_trigger_index",
                    result["data"]["index"] == 2,
                    f"got {result['data']['index']}")
            _assert("create_trigger_label",
                    result["data"]["script_label"] == "TestRoute_EventScript_TestRainEvent",
                    f"got {result['data']['script_label']}")
            _assert("create_trigger_var",
                    result["data"]["event"]["var"] == "VAR_TEMP_3")

            # Verify it was written to map.json
            clear_project_cache()
            data = _load_map_json(tmp, "TestRoute")
            _assert("create_trigger_persisted",
                    len(data["coord_events"]) == 3,
                    f"got {len(data['coord_events'])}")
            new_evt = data["coord_events"][2]
            _assert("create_trigger_coords_persisted",
                    new_evt["x"] == 8 and new_evt["y"] == 15)
            _assert("create_trigger_script_persisted",
                    new_evt["script"] == "TestRoute_EventScript_TestRainEvent")

            # 21. Create trigger -- auto-generated label
            clear_project_cache()
            handler._body = json.dumps({
                "x": 3, "y": 7,
            }).encode()
            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
                "/api/map/TestRoute/triggers"
            )
            result = handle_trigger_create(handler, match, {})
            _assert("create_trigger_autolabel_ok", result["ok"] is True)
            _assert("create_trigger_autolabel",
                    result["data"]["script_label"] == "TestRoute_Trigger_3_7",
                    f"got {result['data']['script_label']}")

            # 22. Create trigger -- missing x,y
            clear_project_cache()
            handler._body = json.dumps({"elevation": 0}).encode()
            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
                "/api/map/TestRoute/triggers"
            )
            result = handle_trigger_create(handler, match, {})
            _assert("create_trigger_missing_xy", result["ok"] is False)

            # 23. Create trigger -- nonexistent map
            clear_project_cache()
            handler._body = json.dumps({"x": 1, "y": 1}).encode()
            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
                "/api/map/NoSuchMap/triggers"
            )
            result = handle_trigger_create(handler, match, {})
            _assert("create_trigger_404", result["ok"] is False)

            # 24. Update trigger
            clear_project_cache()
            handler._body = json.dumps({
                "var": "VAR_TEMP_5",
                "var_value": "2",
            }).encode()
            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers/(?P<index>\d+)",
                "/api/map/TestRoute/triggers/0"
            )
            result = handle_trigger_update(handler, match, {})
            _assert("update_trigger_ok", result["ok"] is True)
            _assert("update_trigger_var",
                    result["data"]["event"]["var"] == "VAR_TEMP_5")
            _assert("update_trigger_value",
                    result["data"]["event"]["var_value"] == "2")

            # Verify persistence
            clear_project_cache()
            data = _load_map_json(tmp, "TestRoute")
            _assert("update_trigger_persisted",
                    data["coord_events"][0]["var"] == "VAR_TEMP_5")

            # 25. Update trigger -- out of range
            clear_project_cache()
            handler._body = json.dumps({"var": "0"}).encode()
            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers/(?P<index>\d+)",
                "/api/map/TestRoute/triggers/99"
            )
            result = handle_trigger_update(handler, match, {})
            _assert("update_trigger_out_of_range", result["ok"] is False)

            # 26. Delete trigger
            clear_project_cache()
            data = _load_map_json(tmp, "TestRoute")
            initial_count = len(data["coord_events"])

            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers/(?P<index>\d+)",
                "/api/map/TestRoute/triggers/0"
            )
            result = handle_trigger_delete(handler, match, {})
            _assert("delete_trigger_ok", result["ok"] is True)
            _assert("delete_trigger_index",
                    result["data"]["deleted_index"] == 0)

            # Verify persistence
            clear_project_cache()
            data = _load_map_json(tmp, "TestRoute")
            _assert("delete_trigger_persisted",
                    len(data["coord_events"]) == initial_count - 1,
                    f"expected {initial_count - 1}, got {len(data['coord_events'])}")

            # 27. Delete trigger -- out of range
            clear_project_cache()
            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers/(?P<index>\d+)",
                "/api/map/TestRoute/triggers/99"
            )
            result = handle_trigger_delete(handler, match, {})
            _assert("delete_trigger_out_of_range", result["ok"] is False)

            # 28. Delete trigger -- nonexistent map
            clear_project_cache()
            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers/(?P<index>\d+)",
                "/api/map/NoSuchMap/triggers/0"
            )
            result = handle_trigger_delete(handler, match, {})
            _assert("delete_trigger_404", result["ok"] is False)

            # 29. Create with one_time template
            clear_project_cache()
            handler._body = json.dumps({
                "x": 20, "y": 20,
                "template": "one_time",
            }).encode()
            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
                "/api/map/TestRoute/triggers"
            )
            result = handle_trigger_create(handler, match, {})
            _assert("create_onetime_ok", result["ok"] is True)
            _assert("create_onetime_template",
                    result["data"]["template"] == "one_time")

            # 30. Create with each template type
            for tpl in ["basic", "cutscene", "weather_change", "warp", "item_check"]:
                clear_project_cache()
                handler._body = json.dumps({
                    "x": 1, "y": 1, "template": tpl,
                }).encode()
                match = re.match(
                    r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
                    "/api/map/TestRoute/triggers"
                )
                result = handle_trigger_create(handler, match, {})
                _assert(f"create_template_{tpl}_ok",
                        result["ok"] is True,
                        f"got: {result}")

            # 31. No game_path returns error
            handler_no_path = MockHandler()
            handler_no_path.server.game_path = ""
            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
                "/api/map/TestRoute/triggers"
            )
            result = handle_trigger_list(handler_no_path, match, {})
            _assert("list_no_gamepath_error", result["ok"] is False)

            # 32. Script skeleton written to scripts.pory
            clear_project_cache()
            pory_path = os.path.join(tmp, "data", "maps", "TestRoute", "scripts.pory")
            with open(pory_path, "r") as f:
                content = f.read()
            _assert("script_skeleton_written",
                    "TestRoute_EventScript_TestRainEvent" in content or
                    "TestRoute_Trigger_" in content,
                    f"pory content length: {len(content)}")

            # 33. Default var/var_value when not specified
            clear_project_cache()
            handler._body = json.dumps({"x": 0, "y": 0}).encode()
            match = re.match(
                r"/api/map/(?P<map_name>[A-Za-z0-9_]+)/triggers",
                "/api/map/TestRoute/triggers"
            )
            result = handle_trigger_create(handler, match, {})
            _assert("create_default_vars_ok", result["ok"] is True)
            _assert("default_var_is_0",
                    result["data"]["event"]["var"] == "0")
            _assert("default_var_value_is_0",
                    result["data"]["event"]["var_value"] == "0")

        finally:
            api_base._read_json_body = _orig_read_base
            api_mod._read_json_body = _orig_read_mod

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
