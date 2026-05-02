"""Build Assistant suite -- error diagnosis, auto-build settings, and build command selection."""
from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Build Assistant")

    try:
        from torch.ui import _diagnose_build_error, _get_auto_build_setting, _build_command
    except ImportError as e:
        _skip("all build assistant tests", f"import failed: {e}")
        return

    # -- Test 1: undeclared pattern --
    try:
        result = _diagnose_build_error("error: 'FLAG_MY_THING' undeclared")
        _assert(
            "diagnose: undeclared constant",
            result is not None and "Undeclared constant" in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("diagnose: undeclared constant", str(e))

    # -- Test 2: stddef.h pattern --
    try:
        result = _diagnose_build_error("fatal error: stddef.h: No such file or directory")
        _assert(
            "diagnose: stddef.h missing",
            result is not None and "fixdev" in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("diagnose: stddef.h missing", str(e))

    # -- Test 3: rom overflowed pattern --
    try:
        result = _diagnose_build_error("error: region 'rom' overflowed by 1234 bytes")
        _assert(
            "diagnose: ROM overflowed",
            result is not None and "ROM too large" in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("diagnose: ROM overflowed", str(e))

    # -- Test 4: pory error pattern --
    try:
        result = _diagnose_build_error("data/maps/MyMap/scripts.pory: 42: error: undefined label")
        _assert(
            "diagnose: Poryscript error",
            result is not None and "Poryscript error" in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("diagnose: Poryscript error", str(e))

    # -- Test 5: missing map file pattern --
    try:
        result = _diagnose_build_error("No rule to make target 'data/maps/OldMap/scripts.inc'")
        _assert(
            "diagnose: missing map file",
            result is not None and "Missing map" in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("diagnose: missing map file", str(e))

    # -- Test 6: unknown error returns None --
    try:
        result = _diagnose_build_error("some random error text")
        _assert(
            "diagnose: unknown error returns None",
            result is None,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("diagnose: unknown error returns None", str(e))

    # -- Test 7: undefined reference to map script --
    try:
        stderr = (
            "arm-none-eabi-ld: data/map_events.o: in function `MyMap_ObjectEvents':\n"
            "(.rodata+0x100): undefined reference to `MyMap_NpcScript'\n"
        )
        result = _diagnose_build_error(stderr)
        _assert(
            "diagnose: undefined script reference",
            result == "undefined_script_references",
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("diagnose: undefined script reference", str(e))

    # -- Test 8: multiple undefined refs grouped by map --
    try:
        stderr = (
            "arm-none-eabi-ld: data/map_events.o: in function `TownA_ObjectEvents':\n"
            "(.rodata+0x100): undefined reference to `TownA_Npc1'\n"
            "(.rodata+0x110): undefined reference to `TownA_Npc2'\n"
            "arm-none-eabi-ld: data/map_events.o: in function `TownB_ObjectEvents':\n"
            "(.rodata+0x200): undefined reference to `TownB_Npc1'\n"
        )
        result = _diagnose_build_error(stderr)
        _assert(
            "diagnose: multiple undefined refs grouped by map",
            result == "undefined_script_references",
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("diagnose: multiple undefined refs grouped by map", str(e))

    # -- Test 9: duplicate symbol pattern --
    try:
        stderr = (
            "data/maps/PlayerHome/scripts.inc:5: Error: "
            "symbol `PlayerHome_MapScripts' is already defined\n"
        )
        result = _diagnose_build_error(stderr)
        _assert(
            "diagnose: duplicate symbol",
            result == "duplicate_symbols",
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("diagnose: duplicate symbol", str(e))

    # -- Test 10: _get_auto_build_setting defaults to True --
    try:
        import torch.config as _cfg_mod
        original_path = _cfg_mod.CONFIG_PATH
        _cfg_mod.CONFIG_PATH = "/tmp/torch_test_nonexistent_auto_build.conf"
        result = _get_auto_build_setting()
        _cfg_mod.CONFIG_PATH = original_path
        _assert(
            "_get_auto_build_setting: defaults to True",
            result is True,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("_get_auto_build_setting default", str(e))

    # -- Test 11: _build_command pre-1.14 --
    try:
        cmd = _build_command((1, 7, 4))
        _assert(
            "_build_command: pre-1.14",
            cmd[0] == "make" and len(cmd) == 2 and cmd[1].startswith("-j"),
            f"got: {cmd!r}"
        )
    except Exception as e:
        _fail("_build_command: pre-1.14", str(e))

    # -- Test 12: _build_command 1.14.0 --
    try:
        cmd = _build_command((1, 14, 0))
        _assert(
            "_build_command: 1.14.0",
            cmd[0] == "make" and cmd[1] == "release" and cmd[2].startswith("-j"),
            f"got: {cmd!r}"
        )
    except Exception as e:
        _fail("_build_command: 1.14.0", str(e))

    # -- Test 13: _build_command 1.14.3 --
    try:
        cmd = _build_command((1, 14, 3))
        _assert(
            "_build_command: 1.14.3",
            cmd[0] == "make" and cmd[1] == "release" and cmd[2].startswith("-j"),
            f"got: {cmd!r}"
        )
    except Exception as e:
        _fail("_build_command: 1.14.3", str(e))

    # -- Test 14: _build_command None --
    try:
        cmd = _build_command(None)
        _assert(
            "_build_command: None (safe default)",
            cmd[0] == "make" and len(cmd) == 2 and cmd[1].startswith("-j"),
            f"got: {cmd!r}"
        )
    except Exception as e:
        _fail("_build_command: None", str(e))
