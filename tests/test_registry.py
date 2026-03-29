"""Registry suite -- enrollment, round-trip, lookup."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Registry  (enrollment, round-trip, lookup)")

    try:
        from torch.registry import (
            load_registry, save_registry, enroll_map, unenroll_map,
            update_last_written, get_enrolled_maps, is_enrolled,
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
            reg == {"version": 1, "maps": {}},
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
            reg == {"version": 1, "maps": {}},
            f"got: {reg!r}"
        )
    except Exception as e:
        _fail("load_registry corrupt JSON", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 3. save_registry + load_registry round-trip
    tmp_dir = tempfile.mkdtemp(prefix="torch_reg_test_")
    try:
        test_reg = {"version": 1, "maps": {"MapA": {"enrolled_at": "2026-01-01T00:00:00", "last_written": None}}}
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
