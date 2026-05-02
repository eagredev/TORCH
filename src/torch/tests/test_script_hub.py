"""Script Hub tests -- Studio workspace, browse mode, CLI routing."""
from torch.tests.harness import _begin_suite, _ok, _fail, _assert, _skip
from unittest.mock import patch, MagicMock
import io


def run_suite():
    _begin_suite("Script Hub  (Studio workspace & browse mode)")

    try:
        from torch.script_hub import (
            _landing_page, _landing_heal, _browse_dispatch,
            _browse_tool_action, script_command, _scripts_map_list, _QUIT,
            _browse_help, _render_dashboard_header, _get_last_build_info,
            _get_attention_maps, script_builder_menu,
            _abridge_name, _hub_render_detail_panel,
        )
    except ImportError as e:
        _skip("all script hub tests", f"import failed: {e}")
        return

    # ---- _abridge_name: short names pass through ----------------------------
    _assert("abridge_name: short name unchanged",
            _abridge_name("PlayerHome") == "PlayerHome",
            f"got '{_abridge_name('PlayerHome')}'")

    # ---- _abridge_name: exactly at threshold passes through -----------------
    name_23 = "A" * 23
    _assert("abridge_name: 23-char name unchanged",
            _abridge_name(name_23) == name_23,
            f"got '{_abridge_name(name_23)}'")

    # ---- _abridge_name: over threshold gets abridged ------------------------
    long_name = "ShirubeTown_PokemonCenter_1F"
    abridged = _abridge_name(long_name)
    _assert("abridge_name: long name abridged",
            "(..." in abridged and len(abridged) == 21
            and abridged.startswith(long_name[:8])
            and abridged.endswith(long_name[-8:]),
            f"got '{abridged}' (len={len(abridged)})")

    # ---- Legacy landing page: input "1" calls _scripts_map_list ---------------
    with patch("torch.script_hub._scripts_map_list") as mock_scripts, \
         patch("torch.script_hub.clear_screen"), \
         patch("torch.script_hub.print_logo"), \
         patch("builtins.input", side_effect=["1", "q"]):
        _landing_page("/tmp/proj", "/tmp/game", "", "", {}, "Test")
        _assert("legacy landing [1] calls _scripts_map_list",
                mock_scripts.called,
                f"expected _scripts_map_list to be called, was not")

    # ---- Legacy landing page: input "2" calls _landing_trainers ---------------
    with patch("torch.script_hub._landing_trainers") as mock_train, \
         patch("torch.script_hub.clear_screen"), \
         patch("torch.script_hub.print_logo"), \
         patch("builtins.input", side_effect=["2", "q"]):
        _landing_page("/tmp/proj", "/tmp/game", "", "", {}, "Test")
        _assert("legacy landing [2] calls _landing_trainers",
                mock_train.called,
                "expected _landing_trainers to be called")

    # ---- Legacy landing page: input "q" returns immediately -------------------
    with patch("torch.script_hub.clear_screen"), \
         patch("torch.script_hub.print_logo"), \
         patch("builtins.input", side_effect=["q"]) as mock_input:
        _landing_page("/tmp/proj", "/tmp/game", "", "", {}, "Test")
        _assert("legacy landing [q] returns", mock_input.call_count == 1,
                f"expected 1 input call, got {mock_input.call_count}")

    # ---- Browse dispatch state with view_mode --------------------------------
    state = {
        "idx": 0, "top": 0, "show_van": False,
        "visible": [
            {"name": "Map1", "status": "ACTIVE"},
            {"name": "Map2", "status": "ACTIVE"},
            {"name": "Map3", "status": "ACTIVE"},
        ],
        "all_maps": [], "sel": {"name": "Map1", "status": "ACTIVE"},
        "view_mode": "all",
    }
    ctx = {
        "project_dir": "/tmp", "game_path": "/tmp", "emotes_conf": "",
        "source_display": "", "settings": {}, "proj_name": "Test",
        "NK_UP": "u", "NK_DOWN": "j", "workspace_expanded": "",
    }

    # ---- Browse dispatch: tool-key compound "s3" -----------------------------
    with patch("torch.script_hub._browse_tool_action") as mock_action:
        _browse_dispatch("s3", state, ctx)
        _assert("browse s3 calls tool action on item 3",
                mock_action.called and mock_action.call_args[0][0] == "s"
                and mock_action.call_args[0][1]["name"] == "Map3",
                f"expected tool=s on Map3, got {mock_action.call_args}")

    # ---- Browse dispatch: tool-key compound "e2" -----------------------------
    with patch("torch.script_hub._browse_tool_action") as mock_action:
        _browse_dispatch("e2", state, ctx)
        _assert("browse e2 calls tool action on item 2",
                mock_action.called and mock_action.call_args[0][0] == "e"
                and mock_action.call_args[0][1]["name"] == "Map2",
                f"expected tool=e on Map2, got {mock_action.call_args}")

    # ---- Browse dispatch: single "s" on highlighted --------------------------
    with patch("torch.script_hub._browse_tool_action") as mock_action:
        _browse_dispatch("s", state, ctx)
        _assert("browse [s] on highlighted map",
                mock_action.called and mock_action.call_args[0][0] == "s"
                and mock_action.call_args[0][1]["name"] == "Map1",
                f"expected tool=s on highlighted Map1")

    # ---- Browse dispatch: "q" returns _QUIT ----------------------------------
    result = _browse_dispatch("q", state, ctx)
    _assert("browse [q] returns _QUIT", result is _QUIT,
            f"expected _QUIT sentinel, got {result}")

    # ---- Browse dispatch: Enter scrolls --------------------------------------
    state_copy = dict(state)
    state_copy["idx"] = 0
    _browse_dispatch("", state_copy, ctx)
    _assert("browse Enter scrolls to next",
            state_copy["idx"] == 1,
            f"expected idx=1 after Enter, got {state_copy['idx']}")

    # ---- Browse dispatch: number jumps to row --------------------------------
    state_copy = dict(state)
    state_copy["idx"] = 0
    _browse_dispatch("2", state_copy, ctx)
    _assert("browse number jumps to row",
            state_copy["idx"] == 1,
            f"expected idx=1 after '2', got {state_copy['idx']}")

    # ---- Browse dispatch: [r] toggles view mode ------------------------------
    state_copy = dict(state)
    state_copy["view_mode"] = "all"
    _browse_dispatch("r", state_copy, ctx)
    _assert("browse [r] toggles all -> recent",
            state_copy["view_mode"] == "recent" and state_copy["idx"] == 0,
            f"expected view_mode=recent, got {state_copy['view_mode']}")

    _browse_dispatch("r", state_copy, ctx)
    _assert("browse [r] toggles recent -> all",
            state_copy["view_mode"] == "all",
            f"expected view_mode=all, got {state_copy['view_mode']}")

    # ---- Browse dispatch: [t] calls trainers ---------------------------------
    with patch("torch.script_hub._browse_tool_action") as mock_action:
        _browse_dispatch("t", state, ctx)
        _assert("browse [t] calls trainers",
                mock_action.called and mock_action.call_args[0][0] == "t",
                f"expected tool=t, got {mock_action.call_args}")

    # ---- Browse dispatch: [i] calls item editor ------------------------------
    with patch("torch.item_editor.item_editor_menu", create=True) as mock_items:
        _browse_dispatch("i", state, ctx)
        _assert("browse [i] calls item editor",
                mock_items.called,
                "expected item_editor_menu to be called")

    # ---- Browse dispatch: [gf] calls flag browser ----------------------------
    with patch("torch.flag_browser.flag_browser", create=True) as mock_flags:
        _browse_dispatch("gf", state, ctx)
        _assert("browse [gf] calls flag browser",
                mock_flags.called,
                "expected flag_browser to be called")

    # ---- Browse dispatch: [x] calls map explorer -----------------------------
    with patch("torch.map_explorer.map_explorer_menu", create=True) as mock_explore:
        _browse_dispatch("x", state, ctx)
        _assert("browse [x] calls map explorer",
                mock_explore.called,
                "expected map_explorer_menu to be called")

    # ---- Browse dispatch: [b] calls build ------------------------------------
    with patch("torch.script_hub._landing_build") as mock_build:
        _browse_dispatch("b", state, ctx)
        _assert("browse [b] calls build",
                mock_build.called,
                "expected _landing_build to be called")

    # ---- Browse dispatch: [?] calls help -------------------------------------
    with patch("torch.script_hub._browse_help") as mock_help:
        _browse_dispatch("?", state, ctx)
        _assert("browse [?] calls help",
                mock_help.called,
                "expected _browse_help to be called")

    # ---- Browse dispatch: [A] calls import all -------------------------------
    with patch("torch.script_hub._hub_handle_import_all") as mock_import_all:
        _browse_dispatch("A", state, ctx)
        _assert("browse [A] calls import all",
                mock_import_all.called,
                "expected _hub_handle_import_all to be called")

    # ---- Browse dispatch: [m] calls marts (local) --------------------------
    with patch("torch.script_hub._browse_tool_action") as mock_action:
        _browse_dispatch("m", state, ctx)
        _assert("browse [m] calls marts on highlighted map",
                mock_action.called and mock_action.call_args[0][0] == "m",
                f"expected tool=m, got {mock_action.call_args}")

    # ---- Browse dispatch: [f] calls flag browser (local) -------------------
    with patch("torch.flag_browser.flag_browser", create=True) as mock_flags:
        _browse_dispatch("f", state, ctx)
        _assert("browse [f] calls flag browser (local)",
                mock_flags.called,
                "expected flag_browser to be called")

    # ---- Browse dispatch: [gt] calls global trainers (flat list) -----------
    with patch("torch.script_hub._landing_trainers_flat") as mock_train:
        _browse_dispatch("gt", state, ctx)
        _assert("browse [gt] calls global trainers flat",
                mock_train.called,
                "expected _landing_trainers_flat to be called")

    # ---- Browse dispatch: [gh] calls global heal locations -----------------
    with patch("torch.heal_locations.heal_command", create=True) as mock_heal:
        _browse_dispatch("gh", state, ctx)
        _assert("browse [gh] calls global heal locations",
                mock_heal.called,
                "expected heal_command to be called")

    # ---- Browse dispatch: [gm] calls global marts -------------------------
    with patch("torch.shop_editor.shop_editor_menu", create=True) as mock_shop:
        _browse_dispatch("gm", state, ctx)
        _assert("browse [gm] calls global marts",
                mock_shop.called,
                "expected shop_editor_menu to be called")

    # ---- Browse dispatch: [#] calls refresh --------------------------------
    with patch("torch.script_hub._refresh_all_caches") as mock_refresh:
        _browse_dispatch("#", state, ctx)
        _assert("browse [#] calls refresh",
                mock_refresh.called,
                "expected _refresh_all_caches to be called")

    # ---- _browse_tool_action: "m" calls shop_editor_menu -------------------
    active_map = {"name": "TestMap", "status": "ACTIVE"}
    with patch("torch.shop_editor.shop_editor_menu", create=True) as mock_shop:
        _browse_tool_action("m", active_map, "/tmp", "/tmp", "", "", {}, "Test", "")
        _assert("tool_action [m] calls shop_editor_menu",
                mock_shop.called,
                "expected shop_editor_menu to be called")

    # ---- script_command with no args calls _browse_maps -----------------------
    with patch("torch.script_hub._browse_maps") as mock_browse, \
         patch("torch.script_hub._set_terminal_title"):
        script_command([], "/tmp/proj", "/tmp/game", "", "", {}, "Test")
        _assert("script_command no args -> _browse_maps",
                mock_browse.called,
                "expected _browse_maps to be called with no args")

    # ---- script_command with 1 arg calls _browse_maps -------------------------
    with patch("torch.script_hub._browse_maps") as mock_browse, \
         patch("torch.script_hub._set_terminal_title"):
        script_command(["TestMap"], "/tmp/proj", "/tmp/game", "", "", {}, "Test")
        _assert("script_command 1 arg -> _browse_maps",
                mock_browse.called,
                "expected _browse_maps to be called with 1 arg")

    # ---- script_command with 2 args opens direct script -----------------------
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        map_dir = os.path.join(tmpdir, "TestMap")
        os.makedirs(map_dir)
        scene_file = os.path.join(map_dir, "TestScene.txt")
        with open(scene_file, "w") as f:
            f.write("label TestMap_TestScene\n---\n")
        with patch("torch.script_hub._script_editor_loop") as mock_editor, \
             patch("torch.script_hub._parse_script", return_value={"test": True}):
            script_command(["TestMap", "TestScene"], tmpdir, "/tmp/game",
                          "", "", {}, "Test")
            _assert("script_command 2 args -> direct script editor",
                    mock_editor.called,
                    "expected _script_editor_loop to be called with 2 args")

    # ---- script_builder_menu calls _browse_maps directly ----------------------
    with patch("torch.script_hub._browse_maps") as mock_browse, \
         patch("torch.script_hub._refresh_all_caches"), \
         patch("torch.script_hub._set_terminal_title"):
        script_builder_menu("/tmp/proj", "/tmp/game", "", "")
        _assert("script_builder_menu calls _browse_maps directly",
                mock_browse.called,
                "expected _browse_maps to be called directly (no landing page)")

    # ---- _scripts_map_list exists and is callable ----------------------------
    _assert("_scripts_map_list is callable", callable(_scripts_map_list),
            "_scripts_map_list should be callable")

    # ---- _get_last_build_info returns string ---------------------------------
    result = _get_last_build_info("/nonexistent")
    _assert("_get_last_build_info handles missing path",
            result == "Last built: never",
            f"expected 'Last built: never', got '{result}'")

    # ---- _get_attention_maps returns tuple of lists ----------------------------
    stale, drift = _get_attention_maps("/nonexistent", "/nonexistent", [])
    _assert("_get_attention_maps handles missing registry",
            isinstance(stale, list) and isinstance(drift, list),
            f"expected (list, list), got ({type(stale)}, {type(drift)})")

    # ---- _render_dashboard_header does not crash -----------------------------
    try:
        with patch("torch.script_hub.clear_screen"), \
             patch("builtins.print"):
            _render_dashboard_header("Test", "/tmp", "/tmp", "recent", [], [], {})
        _ok("_render_dashboard_header runs without crash")
    except Exception as e:
        _fail("_render_dashboard_header runs without crash", str(e))

    # ---- _browse_help does not crash -----------------------------------------
    try:
        with patch("builtins.print"), \
             patch("builtins.input", return_value=""):
            _browse_help()
        _ok("_browse_help runs without crash")
    except Exception as e:
        _fail("_browse_help runs without crash", str(e))

    # ---- Auto-import on CUSTOM map -------------------------------------------
    custom_map = {"name": "CustomMap", "status": "CUSTOM"}
    with patch("torch.script_hub._import_map") as mock_import, \
         patch("builtins.input", return_value="y"):
        _browse_tool_action("s", custom_map, "/tmp", "/tmp", "", "", {}, "Test", "")
        _assert("auto-import on CUSTOM map calls _import_map",
                mock_import.called,
                "expected _import_map to be called for CUSTOM map")

    # ---- battle_map_browser is importable ------------------------------------
    try:
        from torch.battle_manager import battle_map_browser
        _assert("battle_map_browser is importable and callable",
                callable(battle_map_browser),
                "battle_map_browser should be callable")
    except ImportError as e:
        _fail("battle_map_browser is importable", f"import failed: {e}")

    # ---- _landing_trainers calls battle_map_browser --------------------------
    with patch("torch.battle_manager.battle_map_browser") as mock_mb:
        _landing_trainers = None
        try:
            from torch.script_hub import _landing_trainers
        except ImportError:
            pass
        if _landing_trainers:
            _landing_trainers("/tmp/proj", "/tmp/game", "", {}, "", "", "Test")
            _assert("_landing_trainers calls battle_map_browser",
                    mock_mb.called,
                    "expected battle_map_browser to be called")
        else:
            _skip("_landing_trainers calls battle_map_browser",
                  "could not import _landing_trainers")
