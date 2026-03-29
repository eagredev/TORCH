"""Verified Snapshots suite -- create, prune, list, restore."""
import os
import tempfile
import shutil
import zipfile
import json
import time

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Verified Snapshots")

    try:
        from torch.verified_snapshots import (
            create_verified_snapshot, prune_verified_snapshots,
            list_verified_snapshots, restore_verified_snapshot,
            METADATA_FILENAME,
        )
    except ImportError as e:
        _skip("all verified snapshot tests", f"import failed: {e}")
        return

    import json

    # Helper: create a fake game directory with test files
    def _make_fake_game(base):
        subdirs = [
            os.path.join("data", "maps", "TestMap"),
            os.path.join("data", "layouts"),
            os.path.join("src", "data"),
            os.path.join("include", "constants"),
        ]
        for sd in subdirs:
            os.makedirs(os.path.join(base, sd), exist_ok=True)
        files = {
            os.path.join("data", "maps", "TestMap", "scripts.pory"): "script content",
            os.path.join("data", "maps", "TestMap", "map.json"): '{"id": "test"}',
            os.path.join("data", "layouts", "layouts.json"): '{"layouts": []}',
            os.path.join("src", "data", "trainers.party"): "trainer data",
            os.path.join("include", "constants", "opponents.h"): "#define FOO 1",
            os.path.join("data", "event_scripts.s"): ".include scripts",
        }
        for rel, content in files.items():
            with open(os.path.join(base, rel), "w") as f:
                f.write(content)
        return files

    # Test 1: create_verified_snapshot creates a valid ZIP
    tmp_dir = tempfile.mkdtemp()
    try:
        _make_fake_game(tmp_dir)
        path = create_verified_snapshot(tmp_dir, trigger="test")
        _assert(
            "create: produces a valid ZIP",
            path is not None and os.path.isfile(path) and path.endswith(".zip"),
            f"got path: {path}"
        )
        # Verify it's in the right directory
        if path:
            expected_dir = os.path.join(tmp_dir, "backups", "verified")
            _assert(
                "create: ZIP is in backups/verified/",
                os.path.dirname(path) == expected_dir,
                f"dir: {os.path.dirname(path)}"
            )
    except Exception as e:
        _fail("create: produces a valid ZIP", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 2: ZIP contains expected files with correct relative paths
    tmp_dir = tempfile.mkdtemp()
    try:
        fake_files = _make_fake_game(tmp_dir)
        path = create_verified_snapshot(tmp_dir, trigger="test")
        if path:
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
                # Check that game files are present (not just metadata)
                game_names = [n for n in names if n != METADATA_FILENAME]
                has_scripts = any("scripts.pory" in n for n in game_names)
                has_trainers = any("trainers.party" in n for n in game_names)
                has_event = any("event_scripts.s" in n for n in game_names)
                _assert(
                    "create: ZIP contains expected game files",
                    has_scripts and has_trainers and has_event,
                    f"names: {game_names[:5]}..."
                )
        else:
            _fail("create: ZIP contains expected game files", "snapshot creation returned None")
    except Exception as e:
        _fail("create: ZIP contains expected game files", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 3: metadata inside ZIP has required fields
    tmp_dir = tempfile.mkdtemp()
    try:
        _make_fake_game(tmp_dir)
        path = create_verified_snapshot(tmp_dir, trigger="test-meta")
        if path:
            with zipfile.ZipFile(path, "r") as zf:
                _assert(
                    "create: ZIP contains metadata file",
                    METADATA_FILENAME in zf.namelist(),
                    f"names: {zf.namelist()[:5]}"
                )
                if METADATA_FILENAME in zf.namelist():
                    meta = json.loads(zf.read(METADATA_FILENAME))
                    has_fields = all(k in meta for k in
                                     ("torch_version", "timestamp", "file_count"))
                    _assert(
                        "create: metadata has required fields",
                        has_fields and meta.get("trigger") == "test-meta",
                        f"meta keys: {list(meta.keys())}, trigger: {meta.get('trigger')}"
                    )
        else:
            _fail("create: ZIP contains metadata file", "snapshot creation returned None")
    except Exception as e:
        _fail("create: metadata has required fields", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 4: prune keeps only max_count newest
    tmp_dir = tempfile.mkdtemp()
    try:
        verified_dir = os.path.join(tmp_dir, "backups", "verified")
        os.makedirs(verified_dir, exist_ok=True)
        # Create 5 fake ZIP files with ascending timestamps
        for i in range(1, 6):
            fname = f"verified_20260101_00000{i}.zip"
            fpath = os.path.join(verified_dir, fname)
            with zipfile.ZipFile(fpath, "w") as zf:
                zf.writestr("dummy.txt", f"content {i}")
        deleted = prune_verified_snapshots(tmp_dir, max_count=3)
        remaining = sorted(os.listdir(verified_dir))
        _assert(
            "prune: keeps only max_count newest",
            deleted == 2 and len(remaining) == 3
            and remaining == [
                "verified_20260101_000003.zip",
                "verified_20260101_000004.zip",
                "verified_20260101_000005.zip",
            ],
            f"deleted={deleted}, remaining={remaining}"
        )
    except Exception as e:
        _fail("prune: keeps only max_count newest", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 5: list returns sorted list newest-first with correct metadata
    tmp_dir = tempfile.mkdtemp()
    try:
        _make_fake_game(tmp_dir)
        create_verified_snapshot(tmp_dir, trigger="first")
        import time; time.sleep(1.1)  # ensure different timestamp
        create_verified_snapshot(tmp_dir, trigger="second")
        result = list_verified_snapshots(tmp_dir)
        _assert(
            "list: returns newest-first with metadata",
            len(result) == 2
            and result[0]["trigger"] == "second"
            and result[1]["trigger"] == "first"
            and result[0]["file_count"] > 0
            and result[0]["size_mb"] > 0,
            f"count={len(result)}, triggers={[r['trigger'] for r in result]}"
        )
    except Exception as e:
        _fail("list: returns newest-first with metadata", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 6: restore extracts files to correct locations
    tmp_dir = tempfile.mkdtemp()
    try:
        fake_files = _make_fake_game(tmp_dir)
        path = create_verified_snapshot(tmp_dir, trigger="restore-test")
        # Delete a file, then restore
        test_file = os.path.join(tmp_dir, "data", "maps", "TestMap", "scripts.pory")
        os.remove(test_file)
        if path:
            restored = restore_verified_snapshot(tmp_dir, path)
            _assert(
                "restore: extracts files to correct locations",
                restored is not None and len(restored) > 0
                and os.path.isfile(test_file),
                f"restored={restored is not None}, file_exists={os.path.isfile(test_file)}"
            )
            if os.path.isfile(test_file):
                with open(test_file) as f:
                    content = f.read()
                _assert(
                    "restore: content matches original",
                    content == "script content",
                    f"got: {content!r}"
                )
        else:
            _fail("restore: extracts files to correct locations", "snapshot was None")
    except Exception as e:
        _fail("restore: extracts files to correct locations", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 7: restore returns None for non-existent ZIP
    try:
        result = restore_verified_snapshot("/tmp", "/nonexistent/path.zip")
        _assert(
            "restore: returns None for missing ZIP",
            result is None,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("restore: returns None for missing ZIP", str(e))

    # Test 8: list returns empty list for nonexistent dir
    try:
        result = list_verified_snapshots("/tmp/nonexistent_game_path_xyz")
        _assert(
            "list: returns empty list for nonexistent dir",
            result == [],
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("list: returns empty list for nonexistent dir", str(e))
