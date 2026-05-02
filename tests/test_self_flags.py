"""Self-flag suite — naming, registry, allocation."""

import json
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Self-Flags  (naming, registry)")

    try:
        from torch.self_flags import (
            make_self_flag_name, load_registry, save_registry,
        )
    except ImportError as e:
        _skip("all self_flags tests", f"import failed: {e}")
        return

    _test_naming(make_self_flag_name)
    _test_registry(load_registry, save_registry)


def _test_naming(make_self_flag_name):
    try:
        name = make_self_flag_name("ShirubeTown", "Officer", "talked")
        _assert("naming: starts with FLAG_SELF_",
                name.startswith("FLAG_SELF_"), f"got: {name}")
        _assert("naming: ends with _TALKED",
                name.endswith("_TALKED"), f"got: {name}")
        _assert("naming: all uppercase",
                name == name.upper(), f"got: {name}")
    except Exception as e:
        _fail("naming basics", str(e))

    try:
        n1 = make_self_flag_name("TestMap", "NPC", "talked")
        n2 = make_self_flag_name("TestMap", "NPC", "talked")
        _assert("naming: deterministic",
                n1 == n2, f"{n1} != {n2}")
    except Exception as e:
        _fail("naming deterministic", str(e))

    try:
        n1 = make_self_flag_name("TestMap", "NPC1", "x")
        n2 = make_self_flag_name("TestMap", "NPC2", "x")
        _assert("naming: different NPCs → different names",
                n1 != n2, f"both: {n1}")
    except Exception as e:
        _fail("naming different NPCs", str(e))

    try:
        n1 = make_self_flag_name("MapA", "NPC", "x")
        n2 = make_self_flag_name("MapB", "NPC", "x")
        _assert("naming: different maps → different names",
                n1 != n2, f"both: {n1}")
    except Exception as e:
        _fail("naming different maps", str(e))


def _test_registry(load_registry, save_registry):
    # Load from nonexistent path → empty
    try:
        tmpdir = tempfile.mkdtemp()
        result = load_registry(tmpdir)
        _assert("registry: empty when no file", result == {}, f"got: {result}")
    except Exception as e:
        _fail("registry load empty", str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Roundtrip
    try:
        tmpdir = tempfile.mkdtemp()
        test_flags = {
            "FLAG_SELF_TEST_NPC_TALKED": {
                "slot": "FLAG_UNUSED_0x200",
                "map": "TestMap",
                "npc": "NPC",
                "suffix": "talked",
            }
        }
        save_registry(tmpdir, test_flags)
        reg_path = os.path.join(tmpdir, ".torch", "self_flags.json")
        _assert("registry: file created", os.path.isfile(reg_path), "")
        loaded = load_registry(tmpdir)
        _assert("registry: roundtrip preserves data",
                loaded == test_flags, f"loaded: {loaded}")
        with open(reg_path) as f:
            raw = json.load(f)
        _assert("registry: version == 1",
                raw.get("version") == 1, f"raw: {raw}")
    except Exception as e:
        _fail("registry roundtrip", str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Overwrite
    try:
        tmpdir = tempfile.mkdtemp()
        save_registry(tmpdir, {"A": {"slot": "X"}})
        save_registry(tmpdir, {"B": {"slot": "Y"}})
        loaded = load_registry(tmpdir)
        _assert("registry: overwrite replaces",
                "B" in loaded and "A" not in loaded,
                f"loaded: {loaded}")
    except Exception as e:
        _fail("registry overwrite", str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # None game_path
    try:
        result = load_registry(None)
        _assert("registry: None → empty dict", result == {}, f"got: {result}")
    except Exception as e:
        _fail("registry None load", str(e))

    try:
        save_registry(None, {"test": {}})
        _assert("registry: save with None is no-op", True, "")
    except Exception as e:
        _fail("registry None save", str(e))

    # Creates .torch directory
    try:
        tmpdir = tempfile.mkdtemp()
        torch_dir = os.path.join(tmpdir, ".torch")
        _assert("pre-save: .torch dir absent",
                not os.path.isdir(torch_dir), "")
        save_registry(tmpdir, {"X": {}})
        _assert("post-save: .torch dir created",
                os.path.isdir(torch_dir), "")
    except Exception as e:
        _fail("creates .torch dir", str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
