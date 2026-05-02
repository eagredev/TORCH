"""Registry suite -- enrollment, round-trip, lookup, lifecycle states."""
import os
import time
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Registry  (enrollment, round-trip, lookup, lifecycle)")

    try:
        from torch.registry import (
            load_registry, save_registry, enroll_map, unenroll_map,
            update_last_written, get_enrolled_maps, is_enrolled,
            get_map_state, set_map_state, mark_decompiled, get_maps_by_state,
            get_map_health,
            STATE_PRISTINE, STATE_CLAIMED, STATE_LOCKED,
        )
    except ImportError as e:
        _skip("all registry tests", f"import failed: {e}")
        return

    # 1. load_registry returns empty registry when no file exists
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        reg = load_registry(tmp_dir)
        _assert(
            "load_registry: empty dir returns default registry",
            reg == {"version": 2, "maps": {}},
            f"got: {reg!r}"
        )
    except Exception as e:
        _fail("load_registry empty dir", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 2. load_registry returns empty registry on corrupt JSON file
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        reg_path = os.path.join(tmp_dir, ".torch_registry.json")
        with open(reg_path, "w") as f:
            f.write("{{{CORRUPT not valid json")
        reg = load_registry(tmp_dir)
        _assert(
            "load_registry: corrupt JSON returns default registry",
            reg == {"version": 2, "maps": {}},
            f"got: {reg!r}"
        )
    except Exception as e:
        _fail("load_registry corrupt JSON", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 3. save_registry + load_registry round-trip
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        test_reg = {"version": 2, "maps": {"MapA": {
            "enrolled_at": "2026-01-01T00:00:00", "last_written": None,
            "state": "claimed", "decompiled_at": None, "lock_reason": None,
        }}}
        save_registry(tmp_dir, test_reg)
        loaded = load_registry(tmp_dir)
        _assert(
            "save/load round-trip: data survives",
            loaded == test_reg,
            f"expected {test_reg!r}, got {loaded!r}"
        )
    except Exception as e:
        _fail("save/load round-trip", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 4. enroll_map returns True, map appears
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        result = enroll_map(tmp_dir, "TestMap")
        _assert(
            "enroll_map: returns True for new map",
            result is True,
            f"got: {result!r}"
        )
        reg = load_registry(tmp_dir)
        _assert(
            "enroll_map: map appears in registry",
            "TestMap" in reg["maps"],
            f"maps: {list(reg['maps'].keys())}"
        )
    except Exception as e:
        _fail("enroll_map new map", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 5. enroll_map twice — second call returns False
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        enroll_map(tmp_dir, "TestMap")
        result2 = enroll_map(tmp_dir, "TestMap")
        _assert(
            "enroll_map: duplicate returns False",
            result2 is False,
            f"got: {result2!r}"
        )
    except Exception as e:
        _fail("enroll_map duplicate", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 6. unenroll_map returns True, map disappears
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        enroll_map(tmp_dir, "TestMap")
        result = unenroll_map(tmp_dir, "TestMap")
        _assert(
            "unenroll_map: returns True for enrolled map",
            result is True,
            f"got: {result!r}"
        )
        reg = load_registry(tmp_dir)
        _assert(
            "unenroll_map: map removed from registry",
            "TestMap" not in reg["maps"],
            f"maps still has: {list(reg['maps'].keys())}"
        )
    except Exception as e:
        _fail("unenroll_map enrolled map", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 7. unenroll_map returns False for non-existent map
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        result = unenroll_map(tmp_dir, "NonExistent")
        _assert(
            "unenroll_map: non-existent returns False",
            result is False,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("unenroll_map non-existent", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 8. update_last_written auto-enrolls and sets last_written
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        update_last_written(tmp_dir, "NewMap")
        reg = load_registry(tmp_dir)
        _assert(
            "update_last_written: auto-enrolls missing map",
            "NewMap" in reg["maps"],
            f"maps: {list(reg['maps'].keys())}"
        )
        _assert(
            "update_last_written: last_written is non-None",
            reg["maps"]["NewMap"]["last_written"] is not None,
            f"last_written: {reg['maps']['NewMap'].get('last_written')!r}"
        )
    except Exception as e:
        _fail("update_last_written auto-enroll", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 9. get_enrolled_maps returns sorted list
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        enroll_map(tmp_dir, "Zebra")
        enroll_map(tmp_dir, "Alpha")
        enroll_map(tmp_dir, "Middle")
        maps = get_enrolled_maps(tmp_dir)
        _assert(
            "get_enrolled_maps: returns sorted list",
            maps == ["Alpha", "Middle", "Zebra"],
            f"got: {maps!r}"
        )
    except Exception as e:
        _fail("get_enrolled_maps sorted", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 10. is_enrolled True after enroll, False after unenroll
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        enroll_map(tmp_dir, "TestMap")
        _assert(
            "is_enrolled: True after enroll",
            is_enrolled(tmp_dir, "TestMap") is True,
            "expected True"
        )
        unenroll_map(tmp_dir, "TestMap")
        _assert(
            "is_enrolled: False after unenroll",
            is_enrolled(tmp_dir, "TestMap") is False,
            "expected False"
        )
    except Exception as e:
        _fail("is_enrolled enroll/unenroll", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---------------------------------------------------------------
    # Lifecycle state tests (v2 schema)
    # ---------------------------------------------------------------

    # 11. v1 registry migration: maps get state=claimed
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        v1_reg = {"version": 1, "maps": {
            "MapA": {"enrolled_at": "2026-01-01T00:00:00", "last_written": "2026-01-01T12:00:00"},
            "MapB": {"enrolled_at": "2026-01-01T00:00:00", "last_written": None},
        }}
        save_registry(tmp_dir, v1_reg)
        loaded = load_registry(tmp_dir)
        _assert(
            "v1 migration: version bumped to 2",
            loaded["version"] == 2,
            f"got version {loaded['version']}"
        )
        _assert(
            "v1 migration: map with last_written gets state=claimed",
            loaded["maps"]["MapA"]["state"] == STATE_CLAIMED,
            f"got: {loaded['maps']['MapA'].get('state')!r}"
        )
        _assert(
            "v1 migration: map without last_written gets state=claimed",
            loaded["maps"]["MapB"]["state"] == STATE_CLAIMED,
            f"got: {loaded['maps']['MapB'].get('state')!r}"
        )
        _assert(
            "v1 migration: decompiled_at defaults to None",
            loaded["maps"]["MapA"].get("decompiled_at") is None,
            f"got: {loaded['maps']['MapA'].get('decompiled_at')!r}"
        )
    except Exception as e:
        _fail("v1 migration", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 12. enroll_map with state=pristine
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        enroll_map(tmp_dir, "PristineMap", state=STATE_PRISTINE)
        reg = load_registry(tmp_dir)
        entry = reg["maps"]["PristineMap"]
        _assert(
            "enroll_map: state=pristine sets correct state",
            entry["state"] == STATE_PRISTINE,
            f"got: {entry['state']!r}"
        )
        _assert(
            "enroll_map: pristine map has decompiled_at=None",
            entry["decompiled_at"] is None,
            f"got: {entry['decompiled_at']!r}"
        )
    except Exception as e:
        _fail("enroll_map state=pristine", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 13. get_map_state / set_map_state
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        _assert(
            "get_map_state: None for unenrolled map",
            get_map_state(tmp_dir, "Missing") is None,
            "expected None"
        )
        enroll_map(tmp_dir, "TestMap")
        _assert(
            "get_map_state: claimed after enroll",
            get_map_state(tmp_dir, "TestMap") == STATE_CLAIMED,
            f"got: {get_map_state(tmp_dir, 'TestMap')!r}"
        )
        set_map_state(tmp_dir, "TestMap", STATE_LOCKED, lock_reason="round-trip failed")
        _assert(
            "set_map_state: transitions to locked",
            get_map_state(tmp_dir, "TestMap") == STATE_LOCKED,
            f"got: {get_map_state(tmp_dir, 'TestMap')!r}"
        )
        reg = load_registry(tmp_dir)
        _assert(
            "set_map_state: lock_reason preserved",
            reg["maps"]["TestMap"]["lock_reason"] == "round-trip failed",
            f"got: {reg['maps']['TestMap'].get('lock_reason')!r}"
        )
        set_map_state(tmp_dir, "TestMap", STATE_CLAIMED)
        reg = load_registry(tmp_dir)
        _assert(
            "set_map_state: lock_reason cleared on non-locked",
            reg["maps"]["TestMap"]["lock_reason"] is None,
            f"got: {reg['maps']['TestMap'].get('lock_reason')!r}"
        )
    except Exception as e:
        _fail("get_map_state / set_map_state", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 14. mark_decompiled stamps timestamp
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        enroll_map(tmp_dir, "TestMap", state=STATE_PRISTINE)
        _assert(
            "mark_decompiled: returns True",
            mark_decompiled(tmp_dir, "TestMap") is True,
            "expected True"
        )
        reg = load_registry(tmp_dir)
        _assert(
            "mark_decompiled: decompiled_at is non-None",
            reg["maps"]["TestMap"]["decompiled_at"] is not None,
            f"got: {reg['maps']['TestMap'].get('decompiled_at')!r}"
        )
        _assert(
            "mark_decompiled: returns False for unenrolled",
            mark_decompiled(tmp_dir, "NonExistent") is False,
            "expected False"
        )
    except Exception as e:
        _fail("mark_decompiled", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 15. get_maps_by_state categorises correctly
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        enroll_map(tmp_dir, "Alpha", state=STATE_PRISTINE)
        enroll_map(tmp_dir, "Beta", state=STATE_CLAIMED)
        enroll_map(tmp_dir, "Gamma", state=STATE_CLAIMED)
        enroll_map(tmp_dir, "Delta", state=STATE_PRISTINE)
        set_map_state(tmp_dir, "Delta", STATE_LOCKED, lock_reason="test")
        result = get_maps_by_state(tmp_dir)
        _assert(
            "get_maps_by_state: pristine list",
            result[STATE_PRISTINE] == ["Alpha"],
            f"got: {result[STATE_PRISTINE]!r}"
        )
        _assert(
            "get_maps_by_state: claimed list",
            result[STATE_CLAIMED] == ["Beta", "Gamma"],
            f"got: {result[STATE_CLAIMED]!r}"
        )
        _assert(
            "get_maps_by_state: locked list",
            result[STATE_LOCKED] == ["Delta"],
            f"got: {result[STATE_LOCKED]!r}"
        )
    except Exception as e:
        _fail("get_maps_by_state", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 16. get_map_health: locked map returns ok
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    game_dir = tempfile.mkdtemp(prefix="torch_reg_game_")
    try:
        map_name = "LockedMap"
        os.makedirs(os.path.join(tmp_dir, map_name))
        os.makedirs(os.path.join(game_dir, "data", "maps", map_name))
        enroll_map(tmp_dir, map_name)
        set_map_state(tmp_dir, map_name, STATE_LOCKED, lock_reason="test")
        health = get_map_health(tmp_dir, map_name, game_dir)
        _assert(
            "get_map_health: locked map returns ok",
            health == "ok",
            f"got: {health!r}"
        )
    except Exception as e:
        _fail("get_map_health locked", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(game_dir, ignore_errors=True)

    # 17. get_map_health: pristine map with no changes returns ok
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    game_dir = tempfile.mkdtemp(prefix="torch_reg_game_")
    try:
        map_name = "PristineOk"
        ws_dir = os.path.join(tmp_dir, map_name)
        os.makedirs(ws_dir)
        game_map = os.path.join(game_dir, "data", "maps", map_name)
        os.makedirs(game_map)
        # Create game file first
        with open(os.path.join(game_map, "scripts.pory"), "w") as f:
            f.write("// test")
        time.sleep(0.1)
        # Enroll as pristine and stamp decompiled_at
        enroll_map(tmp_dir, map_name, state=STATE_PRISTINE)
        mark_decompiled(tmp_dir, map_name)
        time.sleep(0.1)
        # Create workspace file with mtime BEFORE decompiled_at (simulating decompile)
        txt_path = os.path.join(ws_dir, "Npc.txt")
        with open(txt_path, "w") as f:
            f.write("script test\nend\n")
        # Set mtime to before decompiled_at
        past = time.time() - 10
        os.utime(txt_path, (past, past))
        health = get_map_health(tmp_dir, map_name, game_dir)
        _assert(
            "get_map_health: pristine map with no changes returns ok",
            health == "ok",
            f"got: {health!r}"
        )
    except Exception as e:
        _fail("get_map_health pristine ok", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(game_dir, ignore_errors=True)

    # 18. get_map_health: pristine map auto-claims on .txt edit
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    game_dir = tempfile.mkdtemp(prefix="torch_reg_game_")
    try:
        map_name = "AutoClaim"
        ws_dir = os.path.join(tmp_dir, map_name)
        os.makedirs(ws_dir)
        game_map = os.path.join(game_dir, "data", "maps", map_name)
        os.makedirs(game_map)
        with open(os.path.join(game_map, "scripts.pory"), "w") as f:
            f.write("// test")
        enroll_map(tmp_dir, map_name, state=STATE_PRISTINE)
        mark_decompiled(tmp_dir, map_name)
        time.sleep(1.5)  # Exceed tolerance
        # User edits a .txt file (mtime > decompiled_at)
        with open(os.path.join(ws_dir, "Npc.txt"), "w") as f:
            f.write("script test\nmsgnpc \"hello\"\nend\n")
        health = get_map_health(tmp_dir, map_name, game_dir)
        # Should have auto-transitioned to claimed and return never_written
        state = get_map_state(tmp_dir, map_name)
        _assert(
            "get_map_health: pristine auto-claims on .txt edit",
            state == STATE_CLAIMED,
            f"got state: {state!r}, health: {health!r}"
        )
    except Exception as e:
        _fail("get_map_health auto-claim", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(game_dir, ignore_errors=True)

    # 19. get_map_health: pristine_stale when game files change
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    game_dir = tempfile.mkdtemp(prefix="torch_reg_game_")
    try:
        map_name = "PristineStale"
        ws_dir = os.path.join(tmp_dir, map_name)
        os.makedirs(ws_dir)
        game_map = os.path.join(game_dir, "data", "maps", map_name)
        os.makedirs(game_map)
        enroll_map(tmp_dir, map_name, state=STATE_PRISTINE)
        mark_decompiled(tmp_dir, map_name)
        time.sleep(1.5)  # Exceed tolerance
        # Game file changes after decompile
        with open(os.path.join(game_map, "scripts.pory"), "w") as f:
            f.write("// updated by Porymap")
        health = get_map_health(tmp_dir, map_name, game_dir)
        _assert(
            "get_map_health: pristine_stale when game files change",
            health == "pristine_stale",
            f"got: {health!r}"
        )
    except Exception as e:
        _fail("get_map_health pristine_stale", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(game_dir, ignore_errors=True)

    # 20. bulk_enroll with state=pristine
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    game_dir = tempfile.mkdtemp(prefix="torch_reg_game_")
    try:
        from torch.registry import bulk_enroll
        # Create workspace folder + matching game map
        os.makedirs(os.path.join(tmp_dir, "TestMap"))
        os.makedirs(os.path.join(game_dir, "data", "maps", "TestMap"))
        count, skipped = bulk_enroll(tmp_dir, game_dir, state=STATE_PRISTINE)
        _assert(
            "bulk_enroll: state=pristine enrolls with correct state",
            count == 1,
            f"enrolled: {count}"
        )
        reg = load_registry(tmp_dir)
        _assert(
            "bulk_enroll: enrolled map has state=pristine",
            reg["maps"]["TestMap"]["state"] == STATE_PRISTINE,
            f"got: {reg['maps']['TestMap'].get('state')!r}"
        )
    except Exception as e:
        _fail("bulk_enroll state=pristine", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(game_dir, ignore_errors=True)

    # 21. set_map_state returns False for invalid state
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        enroll_map(tmp_dir, "TestMap")
        result = set_map_state(tmp_dir, "TestMap", "bogus_state")
        _assert(
            "set_map_state: invalid state returns False",
            result is False,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("set_map_state invalid", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 22. set_map_state returns False for unenrolled map
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        result = set_map_state(tmp_dir, "NonExistent", STATE_LOCKED)
        _assert(
            "set_map_state: unenrolled map returns False",
            result is False,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("set_map_state unenrolled", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
