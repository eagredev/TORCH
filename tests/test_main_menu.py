"""Main menu restructure tests — 4-category layout, dispatch, CLI routing."""
from torch.tests.harness import _begin_suite, _ok, _fail, _assert, _skip
from unittest.mock import patch, MagicMock


def run_suite():
    _begin_suite("Main Menu  (restructured 4-category layout)")

    # ---- Import test --------------------------------------------------------
    try:
        from torch.__main__ import (
            _menu_game_settings, _menu_project, _menu_studio,
            _menu_registry, _menu_help,
            _CLI_DISPATCH_TABLE, _MENU_GROUPS,
            _ACTION_ENTRIES, _FOOTER_ENTRIES,
        )
    except ImportError as e:
        _skip("all main menu tests", f"import failed: {e}")
        return

    # 1. _menu_game_settings exists and is callable
    _assert("_menu_game_settings is callable",
            callable(_menu_game_settings),
            "_menu_game_settings should be callable")

    # 2. _menu_project exists and is callable
    _assert("_menu_project is callable",
            callable(_menu_project),
            "_menu_project should be callable")

    # 3. _menu_game_settings dispatch — "1" calls _menu_settings
    with patch("torch.__main__._menu_settings") as mock_settings, \
         patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["1", "q"]):
        _menu_game_settings("/tmp/proj", "/tmp/game", "/tmp/ws", {},
                            "", "", "Test")
        _assert("game_settings [1] calls _menu_settings",
                mock_settings.called,
                "expected _menu_settings to be called")

    # 3b. _menu_game_settings dispatch — "2" calls _cmd_studio
    with patch("torch.__main__._cmd_studio") as mock_rom, \
         patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["2", "q"]):
        _menu_game_settings("/tmp/proj", "/tmp/game", "/tmp/ws", {},
                            "", "", "Test")
        _assert("game_settings [2] calls _cmd_studio (ROM metadata)",
                mock_rom.called,
                "expected _cmd_studio to be called")

    # 3c. _menu_game_settings dispatch — "3" calls _menu_tileset
    with patch("torch.__main__._menu_tileset") as mock_tile, \
         patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["3", "q"]):
        _menu_game_settings("/tmp/proj", "/tmp/game", "/tmp/ws", {},
                            "", "", "Test")
        _assert("game_settings [3] calls _menu_tileset",
                mock_tile.called,
                "expected _menu_tileset to be called")

    # 3d. _menu_game_settings dispatch — "4" calls _menu_assets
    with patch("torch.__main__._menu_assets") as mock_assets, \
         patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["4", "q"]):
        _menu_game_settings("/tmp/proj", "/tmp/game", "/tmp/ws", {},
                            "", "", "Test")
        _assert("game_settings [4] calls _menu_assets",
                mock_assets.called,
                "expected _menu_assets to be called")

    # 4. _menu_project dispatch — "1" calls _menu_vault
    with patch("torch.__main__._menu_vault", return_value=None) as mock_vault, \
         patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["1", "q"]):
        _menu_project("/tmp/proj", "/tmp/game", "", "", {}, "Test", "/tmp/ws")
        _assert("project [1] calls _menu_vault",
                mock_vault.called,
                "expected _menu_vault to be called")

    # 4b. _menu_project dispatch — "2" calls _menu_scorch
    with patch("torch.__main__._menu_scorch") as mock_scorch, \
         patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["2", "q"]):
        _menu_project("/tmp/proj", "/tmp/game", "", "", {}, "Test", "/tmp/ws")
        _assert("project [2] calls _menu_scorch",
                mock_scorch.called,
                "expected _menu_scorch to be called")

    # 4c. _menu_project dispatch — "3" calls _menu_upgrade
    with patch("torch.__main__._menu_upgrade") as mock_upgrade, \
         patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["3", "q"]):
        _menu_project("/tmp/proj", "/tmp/game", "", "", {}, "Test", "/tmp/ws")
        _assert("project [3] calls _menu_upgrade",
                mock_upgrade.called,
                "expected _menu_upgrade to be called")

    # 4d. _menu_project dispatch — "4" calls _menu_fork
    with patch("torch.__main__._menu_fork", return_value=None) as mock_fork, \
         patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["4", "q"]):
        _menu_project("/tmp/proj", "/tmp/game", "", "", {}, "Test", "/tmp/ws")
        _assert("project [4] calls _menu_fork",
                mock_fork.called,
                "expected _menu_fork to be called")

    # 4e. _menu_project dispatch — "5" calls _menu_new
    with patch("torch.__main__._menu_new", return_value=None) as mock_new, \
         patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["5", "q"]):
        _menu_project("/tmp/proj", "/tmp/game", "", "", {}, "Test", "/tmp/ws")
        _assert("project [5] calls _menu_new",
                mock_new.called,
                "expected _menu_new to be called")

    # 4f. _menu_project dispatch — "6" calls _menu_registry
    with patch("torch.__main__._menu_registry") as mock_reg, \
         patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["6", "q"]):
        _menu_project("/tmp/proj", "/tmp/game", "", "", {}, "Test", "/tmp/ws")
        _assert("project [6] calls _menu_registry",
                mock_reg.called,
                "expected _menu_registry to be called")

    # 4g. _menu_project dispatch — "q" returns None
    with patch("torch.__main__.clear_screen"), \
         patch("torch.__main__.print_logo"), \
         patch("builtins.input", side_effect=["q"]):
        result = _menu_project("/tmp/proj", "/tmp/game", "", "", {}, "Test", "/tmp/ws")
        _assert("project [q] returns None", result is None,
                f"expected None, got {result}")

    # 5. Menu groups has single unnamed group with 4 items
    _assert("_MENU_GROUPS has 1 group",
            len(_MENU_GROUPS) == 1,
            f"expected 1 group, got {len(_MENU_GROUPS)}")
    _assert("group name is empty",
            _MENU_GROUPS[0][0] == "",
            f"expected empty group name, got '{_MENU_GROUPS[0][0]}'")
    _assert("4 category items",
            len(_MENU_GROUPS[0][1]) == 4,
            f"expected 4 items, got {len(_MENU_GROUPS[0][1])}")

    # 6. _ACTION_ENTRIES has 2 entries (no Upgrade)
    _assert("_ACTION_ENTRIES has 2 entries",
            len(_ACTION_ENTRIES) == 2,
            f"expected 2, got {len(_ACTION_ENTRIES)}")
    action_keys = [e[0] for e in _ACTION_ENTRIES]
    _assert("action keys are b, r",
            action_keys == ["b", "r"],
            f"expected ['b', 'r'], got {action_keys}")

    # 7. _FOOTER_ENTRIES has 1 entry (Config only)
    _assert("_FOOTER_ENTRIES has 1 entry",
            len(_FOOTER_ENTRIES) == 1,
            f"expected 1, got {len(_FOOTER_ENTRIES)}")
    _assert("footer key is c",
            _FOOTER_ENTRIES[0][0] == "c",
            f"expected 'c', got '{_FOOTER_ENTRIES[0][0]}'")

    # 8. CLI dispatch has all new aliases
    new_aliases = ["maps", "trainers", "encounters", "project", "rom",
                   "flags", "shops"]
    for alias in new_aliases:
        _assert(f"CLI dispatch has '{alias}'",
                alias in _CLI_DISPATCH_TABLE,
                f"'{alias}' not in _CLI_DISPATCH_TABLE")

    # 9. "maps" routes to script handler
    _assert("'maps' routes to script",
            _CLI_DISPATCH_TABLE["maps"][0] == "script",
            f"expected 'script', got '{_CLI_DISPATCH_TABLE['maps'][0]}'")

    # 10. "trainers" routes to battle handler
    _assert("'trainers' routes to battle",
            _CLI_DISPATCH_TABLE["trainers"][0] == "battle",
            f"expected 'battle', got '{_CLI_DISPATCH_TABLE['trainers'][0]}'")

    # 11. "rom" routes to rom handler
    _assert("'rom' routes to rom",
            _CLI_DISPATCH_TABLE["rom"][0] == "rom",
            f"expected 'rom', got '{_CLI_DISPATCH_TABLE['rom'][0]}'")

    # 12. "studio" now routes to script (not studio/ROM metadata)
    _assert("'studio' routes to script (not rom)",
            _CLI_DISPATCH_TABLE["studio"][0] == "script",
            f"expected 'script', got '{_CLI_DISPATCH_TABLE['studio'][0]}'")

    # 13. "settings" routes to settings_menu handler
    _assert("'settings' routes to settings_menu",
            _CLI_DISPATCH_TABLE["settings"][0] == "settings_menu",
            f"expected 'settings_menu', got '{_CLI_DISPATCH_TABLE['settings'][0]}'")
