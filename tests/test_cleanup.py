"""Cleanup Interface Contracts suite -- verifies SCORCH remover contracts."""
import os
import tempfile
import shutil
import zipfile

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Cleanup Interface Contracts")

    try:
        from torch.cleanup_writer import (
            remove_maps, remove_trainers, remove_encounters,
            remove_frontier, remove_scripts, remove_tilesets,
            execute_removal, _restore_cleanup_snapshot,
        )
        from torch.cleanup_scanner import RemovalPlan, RemovalItem, SAFE, BLOCKED
    except ImportError as e:
        _skip("all cleanup interface tests", f"import failed: {e}")
        return

    # Helper: verify (int, list) contract
    def _check_remover_contract(name, result):
        _assert(
            f"{name}: returns tuple",
            isinstance(result, tuple),
            f"type={type(result).__name__}, value={result!r}"
        )
        if not isinstance(result, tuple):
            return
        _assert(
            f"{name}: tuple[0] is int",
            isinstance(result[0], int),
            f"type={type(result[0]).__name__}, value={result[0]!r}"
        )
        _assert(
            f"{name}: tuple[1] is list",
            isinstance(result[1], list),
            f"type={type(result[1]).__name__}, value={result[1]!r}"
        )

    # -- Test 1: remove_maps(game_path, []) --
    tmp_dir = tempfile.mkdtemp(prefix="torch_clean_test_")
    try:
        result = remove_maps(tmp_dir, [])
        _check_remover_contract("remove_maps([])", result)
        _assert(
            "remove_maps([]): count is 0",
            result == (0, []),
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("remove_maps([])", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 2: remove_trainers(game_path, []) --
    tmp_dir = tempfile.mkdtemp(prefix="torch_clean_test_")
    try:
        result = remove_trainers(tmp_dir, [])
        _check_remover_contract("remove_trainers([])", result)
        _assert(
            "remove_trainers([]): count is 0",
            result == (0, []),
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("remove_trainers([])", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 3: remove_encounters(game_path, []) --
    # encounters reads wild_encounters.json; missing file returns (0, [error])
    tmp_dir = tempfile.mkdtemp(prefix="torch_clean_test_")
    try:
        result = remove_encounters(tmp_dir, [])
        _check_remover_contract("remove_encounters([])", result)
        _assert(
            "remove_encounters([]): count is 0",
            result[0] == 0,
            f"got count: {result[0]!r}"
        )
    except Exception as e:
        _fail("remove_encounters([])", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 4: remove_frontier(game_path, []) --
    tmp_dir = tempfile.mkdtemp(prefix="torch_clean_test_")
    try:
        result = remove_frontier(tmp_dir, [])
        _check_remover_contract("remove_frontier([])", result)
        _assert(
            "remove_frontier([]): count is 0",
            result == (0, []),
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("remove_frontier([])", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 5: remove_scripts(game_path, []) --
    tmp_dir = tempfile.mkdtemp(prefix="torch_clean_test_")
    try:
        result = remove_scripts(tmp_dir, [])
        _check_remover_contract("remove_scripts([])", result)
        _assert(
            "remove_scripts([]): count is 0",
            result == (0, []),
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("remove_scripts([])", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 6: remove_tilesets(game_path, []) --
    tmp_dir = tempfile.mkdtemp(prefix="torch_clean_test_")
    try:
        result = remove_tilesets(tmp_dir, [])
        _check_remover_contract("remove_tilesets([])", result)
        _assert(
            "remove_tilesets([]): count is 0",
            result == (0, []),
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("remove_tilesets([])", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 7: execute_removal with empty plan --
    tmp_dir = tempfile.mkdtemp(prefix="torch_clean_test_")
    try:
        plan = RemovalPlan()
        result = execute_removal(tmp_dir, plan)
        _assert(
            "execute_removal(empty plan): returns dict",
            isinstance(result, dict),
            f"type={type(result).__name__}"
        )
        _assert(
            "execute_removal(empty plan): dict is empty",
            result == {},
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("execute_removal(empty plan)", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 8: execute_removal with only BLOCKED items --
    tmp_dir = tempfile.mkdtemp(prefix="torch_clean_test_")
    try:
        plan = RemovalPlan()
        plan.add(RemovalItem("maps", "BlockedMap", status=BLOCKED,
                             detail="test", data={}))
        plan.add(RemovalItem("trainers", "TRAINER_BLOCKED", status=BLOCKED,
                             detail="test", data={}))
        result = execute_removal(tmp_dir, plan)
        _assert(
            "execute_removal(all BLOCKED): returns empty dict",
            result == {},
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("execute_removal(all BLOCKED)", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 9: _restore_cleanup_snapshot with non-existent ZIP --
    tmp_dir = tempfile.mkdtemp(prefix="torch_clean_test_")
    try:
        result = _restore_cleanup_snapshot(
            tmp_dir, os.path.join(tmp_dir, "nonexistent.zip"))
        _assert(
            "restore(bad ZIP): returns None",
            result is None,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("restore(bad ZIP)", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 10: _restore_cleanup_snapshot with valid ZIP --
    tmp_dir = tempfile.mkdtemp(prefix="torch_clean_test_")
    try:
        # Create a small ZIP with a known file using relative paths
        zip_path = os.path.join(tmp_dir, "test_snapshot.zip")
        test_content = b"hello from snapshot"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data/test_file.txt", test_content)

        # The target file does NOT exist on disk yet, so the modified-file
        # check is skipped (no input() call).
        result = _restore_cleanup_snapshot(tmp_dir, zip_path)
        _assert(
            "restore(valid ZIP): returns list",
            isinstance(result, list),
            f"type={type(result).__name__}, value={result!r}"
        )
        if isinstance(result, list):
            _assert(
                "restore(valid ZIP): list has 1 entry",
                len(result) == 1 and result[0] == "data/test_file.txt",
                f"got: {result!r}"
            )
        # Verify the file exists on disk with correct content
        restored_path = os.path.join(tmp_dir, "data", "test_file.txt")
        _assert(
            "restore(valid ZIP): file exists on disk",
            os.path.isfile(restored_path),
            f"exists={os.path.exists(restored_path)}"
        )
        if os.path.isfile(restored_path):
            with open(restored_path, "rb") as f:
                disk_content = f.read()
            _assert(
                "restore(valid ZIP): content matches",
                disk_content == test_content,
                f"got: {disk_content!r}"
            )
    except Exception as e:
        _fail("restore(valid ZIP)", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
