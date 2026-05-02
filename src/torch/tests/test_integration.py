"""Integration suite -- multi-module workflows crossing module boundaries."""
import os
import tempfile
import shutil
import zipfile

from torch.tests.harness import _begin_suite, _ok, _fail, _assert, _fixture


def run_suite():
    _begin_suite("Integration  (multi-module workflows)")

    # ================================================================
    # A. Compile + Validate pipeline
    # ================================================================

    try:
        from torch.compiler import compile_script
        from torch.sync import _validate_labels, _validate_constants
    except ImportError as e:
        _fail("import compile+validate", str(e))
        return

    # A1-A4: Compile valid script, validate labels and constants (no warnings)
    tmp_dir = tempfile.mkdtemp(prefix="torch_integ_compile_")
    try:
        # Create a simple .txt script
        script_path = os.path.join(tmp_dir, "TestScene.txt")
        with open(script_path, "w") as f:
            f.write('script TestScene\n')
            f.write('lock\n')
            f.write('msg "Hello world$"\n')
            f.write('release\n')
            f.write('end\n')

        # A1: compile_script returns output with no errors
        output, errors = compile_script(script_path, "TestMap_TestScene", "")
        _assert(
            "compile+validate: valid script compiles without errors",
            len(errors) == 0,
            f"expected 0 errors, got {len(errors)}: {errors}"
        )

        # A2: _validate_labels finds 0 warnings (all labels self-contained)
        regions = [("TestScene", output, False)]
        label_warnings = _validate_labels(output, regions)
        _assert(
            "compile+validate: label validation finds 0 warnings",
            len(label_warnings) == 0,
            f"expected 0 warnings, got {len(label_warnings)}: {label_warnings}"
        )

        # A3: _validate_constants finds 0 warnings (no FLAG/VAR refs)
        game_path = _fixture("mini_game")
        const_warnings = _validate_constants(output, game_path)
        _assert(
            "compile+validate: constant validation finds 0 warnings for basic script",
            len(const_warnings) == 0,
            f"expected 0 warnings, got {len(const_warnings)}: {const_warnings}"
        )

    except Exception as e:
        _fail("compile+validate pipeline (basic)", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # A4: Compile script with bad FLAG, verify constant validation catches it
    tmp_dir = tempfile.mkdtemp(prefix="torch_integ_badconst_")
    try:
        script_path = os.path.join(tmp_dir, "BadConst.txt")
        with open(script_path, "w") as f:
            f.write('script BadConst\n')
            f.write('lock\n')
            f.write('flag set FLAG_NONEXISTENT\n')
            f.write('msg "Flagged$"\n')
            f.write('release\n')
            f.write('end\n')

        output, errors = compile_script(script_path, "TestMap_BadConst", "")
        game_path = _fixture("mini_game")
        const_warnings = _validate_constants(output, game_path)
        _assert(
            "compile+validate: FLAG_NONEXISTENT triggers constant warning",
            len(const_warnings) >= 1,
            f"expected 1+ warnings, got {len(const_warnings)}: {const_warnings}"
        )

    except Exception as e:
        _fail("compile+validate pipeline (bad constant)", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ================================================================
    # B. Registry enrollment lifecycle
    # ================================================================

    try:
        from torch.registry import load_registry, enroll_map, get_enrolled_maps
    except ImportError as e:
        _fail("import registry", str(e))
        return

    tmp_dir = tempfile.mkdtemp(prefix="torch_integ_registry_")
    try:
        # B1: Fresh directory returns empty registry
        reg = load_registry(tmp_dir)
        _assert(
            "registry lifecycle: empty dir returns default registry",
            reg["maps"] == {},
            f"expected empty maps, got: {reg['maps']}"
        )

        # B2: Enroll returns True for new map
        result = enroll_map(tmp_dir, "TestMap")
        _assert(
            "registry lifecycle: enroll_map returns True for new map",
            result is True,
            f"got: {result!r}"
        )

        # B3: Map appears in loaded registry
        reg = load_registry(tmp_dir)
        _assert(
            "registry lifecycle: TestMap appears after enrollment",
            "TestMap" in reg["maps"],
            f"maps: {list(reg['maps'].keys())}"
        )

        # B4: Duplicate enrollment returns False
        result2 = enroll_map(tmp_dir, "TestMap")
        _assert(
            "registry lifecycle: duplicate enroll returns False",
            result2 is False,
            f"got: {result2!r}"
        )

        # B5: get_enrolled_maps returns list containing TestMap
        enrolled = get_enrolled_maps(tmp_dir)
        _assert(
            "registry lifecycle: get_enrolled_maps includes TestMap",
            "TestMap" in enrolled,
            f"enrolled: {enrolled}"
        )

    except Exception as e:
        _fail("registry lifecycle", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ================================================================
    # C. Verified snapshot lifecycle
    # ================================================================

    try:
        from torch.verified_snapshots import (
            create_verified_snapshot, list_verified_snapshots,
            prune_verified_snapshots,
        )
    except ImportError as e:
        _fail("import verified_snapshots", str(e))
        return

    tmp_dir = tempfile.mkdtemp(prefix="torch_integ_vsnapshot_")
    try:
        # Copy mini_game fixture to temp dir so we can write snapshots
        game_path = os.path.join(tmp_dir, "game")
        shutil.copytree(_fixture("mini_game"), game_path)

        # C1: create_verified_snapshot returns a path string
        snap_path = create_verified_snapshot(game_path, trigger="test", max_count=3)
        _assert(
            "verified snapshot lifecycle: create returns path string",
            isinstance(snap_path, str) and len(snap_path) > 0,
            f"got: {snap_path!r}"
        )

        # C2: The ZIP file exists at the returned path
        _assert(
            "verified snapshot lifecycle: ZIP file exists at returned path",
            os.path.isfile(snap_path),
            f"file does not exist: {snap_path}"
        )

        # C3: list_verified_snapshots returns 1 entry
        snaps = list_verified_snapshots(game_path)
        _assert(
            "verified snapshot lifecycle: list returns 1 entry after first create",
            len(snaps) == 1,
            f"expected 1, got {len(snaps)}"
        )

        # C4: Create 4 more (total 5), prune to 3, verify prune count
        # Timestamps are second-resolution, so create ZIPs directly with
        # distinct names to avoid collisions without slow sleeps.
        backup_dir = os.path.join(game_path, "backups", "verified")
        for i in range(4):
            fake_name = f"verified_20260101_00000{i + 1}.zip"
            fake_path = os.path.join(backup_dir, fake_name)
            with zipfile.ZipFile(fake_path, "w") as zf:
                zf.writestr("_torch_metadata.json", '{"trigger":"test"}')

        # Now prune to 3
        deleted = prune_verified_snapshots(game_path, max_count=3)
        _assert(
            "verified snapshot lifecycle: prune deletes 2 oldest (5 -> 3)",
            deleted == 2,
            f"expected 2 deleted, got {deleted}"
        )

        # C5: list now returns 3 entries
        snaps_after = list_verified_snapshots(game_path)
        _assert(
            "verified snapshot lifecycle: 3 snapshots remain after prune",
            len(snaps_after) == 3,
            f"expected 3, got {len(snaps_after)}"
        )

    except Exception as e:
        _fail("verified snapshot lifecycle", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
