"""Vault — toggle pin, restore pre-check, gather maps with snapshots."""
import io
import os
import sys
import tempfile
import shutil
from datetime import datetime

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Vault")

    try:
        from torch.vault import (
            _toggle_pin, _restore_pre_check, _gather_maps_with_snapshots,
        )
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # ==================================================================
    # _toggle_pin (~3 tests)
    # ==================================================================

    # 1. Pin a snapshot file (creates .pin)
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        snap_file = "TestMap_20260301_120000.zip"
        # Create a fake snapshot file so the directory is valid
        open(os.path.join(tmpdir, snap_file), "w").close()

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        _toggle_pin(tmpdir, snap_file)
        sys.stdout = old_stdout

        pin_path = os.path.join(tmpdir, snap_file + ".pin")
        _assert("_toggle_pin: pin creates .pin file",
                os.path.exists(pin_path),
                ".pin file was not created")
    except Exception as e:
        sys.stdout = sys.__stdout__
        _fail("_toggle_pin: pin creates .pin file", str(e))

    # 2. Unpin (removes .pin)
    try:
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        _toggle_pin(tmpdir, snap_file)
        sys.stdout = old_stdout

        pin_path = os.path.join(tmpdir, snap_file + ".pin")
        _assert("_toggle_pin: unpin removes .pin file",
                not os.path.exists(pin_path),
                ".pin file still exists after unpin")
    except Exception as e:
        sys.stdout = sys.__stdout__
        _fail("_toggle_pin: unpin removes .pin file", str(e))

    # 3. Pin again to verify toggle cycle
    try:
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        _toggle_pin(tmpdir, snap_file)
        sys.stdout = old_stdout

        pin_path = os.path.join(tmpdir, snap_file + ".pin")
        _assert("_toggle_pin: re-pin creates .pin again",
                os.path.exists(pin_path),
                ".pin file was not re-created")
    except Exception as e:
        sys.stdout = sys.__stdout__
        _fail("_toggle_pin: re-pin creates .pin again", str(e))
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir)

    # ==================================================================
    # _restore_pre_check (~2 tests)
    # ==================================================================

    # 4. Map dir exists -> returns True
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        game_path = tmpdir
        map_name = "TestMap"
        map_dir = os.path.join(game_path, "data", "maps", map_name)
        os.makedirs(map_dir)

        result = _restore_pre_check(map_name, game_path)
        _assert("_restore_pre_check: existing map dir -> True",
                result is True, f"got {result!r}")
    except Exception as e:
        _fail("_restore_pre_check: existing map dir -> True", str(e))
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir)

    # 5. Map dir missing -> returns False when user types 'n'
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        game_path = tmpdir
        # Don't create the map dir

        old_stdin = sys.stdin
        old_stdout = sys.stdout
        sys.stdin = io.StringIO("n\n")
        sys.stdout = io.StringIO()
        result = _restore_pre_check("NonexistentMap", game_path)
        sys.stdin = old_stdin
        sys.stdout = old_stdout

        _assert("_restore_pre_check: missing map dir + 'n' -> False",
                result is False, f"got {result!r}")
    except Exception as e:
        sys.stdin = sys.__stdin__
        sys.stdout = sys.__stdout__
        _fail("_restore_pre_check: missing map dir + 'n' -> False", str(e))
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir)

    # ==================================================================
    # _gather_maps_with_snapshots (~5 tests)
    # ==================================================================

    # 6. Proper structure with snapshot files
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        map_name = "TestMap"
        snap_dir = os.path.join(tmpdir, map_name, "backups", "snapshots")
        os.makedirs(snap_dir)
        # Create fake snapshot zips with proper naming
        ts1 = "20260301_120000"
        ts2 = "20260302_140000"
        open(os.path.join(snap_dir, f"{map_name}_{ts1}.zip"), "w").close()
        open(os.path.join(snap_dir, f"{map_name}_{ts2}.zip"), "w").close()

        result = _gather_maps_with_snapshots(tmpdir)
        _assert("_gather_maps_with_snapshots: finds map with snapshots",
                len(result) == 1, f"expected 1, got {len(result)}")
        _assert("_gather_maps_with_snapshots: correct map name",
                result[0]["name"] == map_name,
                f"got {result[0]['name']!r}")
        _assert("_gather_maps_with_snapshots: correct count",
                result[0]["count"] == 2,
                f"expected 2, got {result[0]['count']}")
        _assert("_gather_maps_with_snapshots: latest is most recent date",
                result[0]["latest"] == "2026-03-02",
                f"got {result[0]['latest']!r}")
    except Exception as e:
        _fail("_gather_maps_with_snapshots: proper structure", str(e))
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir)

    # 10. Empty directory -> returns empty list
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        result = _gather_maps_with_snapshots(tmpdir)
        _assert("_gather_maps_with_snapshots: empty dir -> empty list",
                result == [], f"got {result!r}")
    except Exception as e:
        _fail("_gather_maps_with_snapshots: empty dir -> empty list", str(e))
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir)

    # 11. Dir with map folder but no snapshots -> returns empty list
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        map_name = "EmptyMap"
        snap_dir = os.path.join(tmpdir, map_name, "backups", "snapshots")
        os.makedirs(snap_dir)
        # No zip files

        result = _gather_maps_with_snapshots(tmpdir)
        _assert("_gather_maps_with_snapshots: no snapshots -> empty list",
                result == [], f"got {result!r}")
    except Exception as e:
        _fail("_gather_maps_with_snapshots: no snapshots -> empty list", str(e))
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir)
