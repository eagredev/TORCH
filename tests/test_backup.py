"""Tests for backup.py — regex patterns, parsing, pruning, and creation."""
import os
import tempfile
import shutil
import zipfile

from torch.tests.harness import _begin_suite, _assert
from torch.backup import (
    _TORCH_BACKUP_RE_GZ,
    _TORCH_BACKUP_RE_ZIP,
    _parse_torch_backups,
    _prune_torch_backups,
    _create_torch_backup,
    _DATA_DIR,
    HOT_TIER_SIZE,
)


def run_suite():
    _begin_suite("Backup (regex, parse, prune, create)")

    # ── A. Regex pattern matching ──────────────────────────────────

    m_zip = _TORCH_BACKUP_RE_ZIP.match("torch_v3.5_20260221_auto.zip")
    _assert("ZIP regex matches valid filename",
            m_zip is not None and m_zip.group(1) == "3.5" and m_zip.group(2) == "20260221",
            f"got {m_zip}")

    m_gz = _TORCH_BACKUP_RE_GZ.match("porysync_v2.1_2026-02-21_backup.py.gz")
    _assert("GZ regex matches legacy filename",
            m_gz is not None and m_gz.group(1) == "2.1" and m_gz.group(2) == "2026-02-21",
            f"got {m_gz}")

    m_none_zip = _TORCH_BACKUP_RE_ZIP.match("random_file.txt")
    m_none_gz = _TORCH_BACKUP_RE_GZ.match("random_file.txt")
    _assert("Neither regex matches random_file.txt",
            m_none_zip is None and m_none_gz is None)

    # A2: Semver format (three segments, no suffix)
    m_semver = _TORCH_BACKUP_RE_ZIP.match("torch_v0.1.0_20260222_tag.zip")
    _assert("ZIP regex matches semver filename (no suffix)",
            m_semver is not None and m_semver.group(1) == "0.1.0" and m_semver.group(2) == "20260222",
            f"got {m_semver}")

    # A3: Semver format with suffix
    m_alpha = _TORCH_BACKUP_RE_ZIP.match("torch_v0.1.0-alpha_20260222_tag.zip")
    _assert("ZIP regex matches semver-alpha filename",
            m_alpha is not None and m_alpha.group(1) == "0.1.0-alpha" and m_alpha.group(2) == "20260222",
            f"got {m_alpha}")

    # A4: Legacy GZ with old format still works
    m_legacy = _TORCH_BACKUP_RE_GZ.match("porysync_v3.5_20260219_pre-map-scanner.py.gz")
    _assert("GZ regex matches legacy porysync filename",
            m_legacy is not None and m_legacy.group(1) == "3.5",
            f"got {m_legacy}")

    # ── B. _parse_torch_backups ────────────────────────────────────

    tmpdir = tempfile.mkdtemp(prefix="torch_test_backup_")
    try:
        # B1: empty directory
        _assert("parse: empty dir returns []",
                _parse_torch_backups(tmpdir) == [])

        # B2: one valid .zip backup
        fname1 = "torch_v3.5_20260221_auto.zip"
        path1 = os.path.join(tmpdir, fname1)
        open(path1, "w").close()
        result = _parse_torch_backups(tmpdir)
        _assert("parse: one valid zip -> 1 entry with correct fields",
                len(result) == 1
                and result[0]["version"] == "3.5"
                and result[0]["date_str"] == "20260221"
                and result[0]["filename"] == fname1,
                f"got {result}")

        # B3: mixed valid and unrecognized files
        # Add a .zip that doesn't match the pattern -> version=None
        fname_bad = "something_weird.zip"
        open(os.path.join(tmpdir, fname_bad), "w").close()
        result2 = _parse_torch_backups(tmpdir)
        unrecognized = [e for e in result2 if e["version"] is None]
        recognized = [e for e in result2 if e["version"] is not None]
        _assert("parse: unrecognized .zip gets version=None, recognized keeps version",
                len(unrecognized) == 1 and unrecognized[0]["filename"] == fname_bad
                and len(recognized) == 1 and recognized[0]["version"] == "3.5",
                f"got unrecognized={unrecognized}, recognized={recognized}")

        # Clean up for mtime test
        os.remove(path1)
        os.remove(os.path.join(tmpdir, fname_bad))

        # B4: sorted by mtime (oldest first)
        fname_old = "torch_v3.0_20260101_old.zip"
        fname_new = "torch_v3.1_20260201_new.zip"
        path_old = os.path.join(tmpdir, fname_old)
        path_new = os.path.join(tmpdir, fname_new)
        open(path_old, "w").close()
        open(path_new, "w").close()
        os.utime(path_old, (1000.0, 1000.0))
        os.utime(path_new, (2000.0, 2000.0))
        result3 = _parse_torch_backups(tmpdir)
        _assert("parse: results sorted oldest first by mtime",
                len(result3) == 2
                and result3[0]["filename"] == fname_old
                and result3[1]["filename"] == fname_new,
                f"got order: {[e['filename'] for e in result3]}")

        # Clean up for subdir test
        os.remove(path_old)
        os.remove(path_new)

        # B5: subdirectories are ignored
        subdir = os.path.join(tmpdir, "torch_v9.9_20260101_subdir.zip")
        os.makedirs(subdir)
        _assert("parse: subdirectories are ignored",
                _parse_torch_backups(tmpdir) == [],
                f"got {_parse_torch_backups(tmpdir)}")
        os.rmdir(subdir)

    finally:
        shutil.rmtree(tmpdir)

    # ── C. _prune_torch_backups ────────────────────────────────────

    tmpdir2 = tempfile.mkdtemp(prefix="torch_test_prune_")
    try:
        # C1: empty directory returns 0
        result_empty = _prune_torch_backups(tmpdir2)
        _assert("prune: empty dir returns 0 (no entries)",
                result_empty == 0,
                f"got {result_empty}")

        # C2: single backup is preserved
        single = os.path.join(tmpdir2, "torch_v3.5_20260101_auto.zip")
        open(single, "w").close()
        count_single = _prune_torch_backups(tmpdir2)
        _assert("prune: single backup preserved, returns 0",
                count_single == 0 and os.path.exists(single),
                f"got count={count_single}, exists={os.path.exists(single)}")
        os.remove(single)

        # C3: 8 backups of same version — cold keeps newest, hot keeps 5 most recent
        # Total 8 same-version: 1 cold (newest) + 5 hot + 2 pruned = 8
        base_mtime = 10000.0
        for i in range(8):
            fname = f"torch_v3.5_2026020{i}_auto.zip"
            p = os.path.join(tmpdir2, fname)
            open(p, "w").close()
            os.utime(p, (base_mtime + i * 100, base_mtime + i * 100))

        deleted_count = _prune_torch_backups(tmpdir2)
        remaining = os.listdir(tmpdir2)
        # 8 total - 1 cold (newest=idx7) = 7 hot candidates
        # Keep HOT_TIER_SIZE=5 -> delete 2
        _assert("prune: 8 same-version backups -> 2 pruned, 6 remain",
                deleted_count == 2 and len(remaining) == 6,
                f"deleted={deleted_count}, remaining={len(remaining)}: {sorted(remaining)}")

        # Clean up for C4
        for f in os.listdir(tmpdir2):
            os.remove(os.path.join(tmpdir2, f))

        # C4: unrecognized files (version=None) are never pruned
        # Add an unrecognized .zip + 8 normal backups of same version
        unrec = os.path.join(tmpdir2, "unknown_backup.zip")
        open(unrec, "w").close()
        os.utime(unrec, (1.0, 1.0))  # very old mtime
        for i in range(8):
            fname = f"torch_v4.0_2026030{i}_auto.zip"
            p = os.path.join(tmpdir2, fname)
            open(p, "w").close()
            os.utime(p, (5000.0 + i * 100, 5000.0 + i * 100))

        _prune_torch_backups(tmpdir2)
        _assert("prune: unrecognized file survives pruning",
                os.path.exists(unrec),
                "unrecognized file was deleted")

    finally:
        shutil.rmtree(tmpdir2)

    # ── D. _create_torch_backup ────────────────────────────────────

    tmpdir3 = tempfile.mkdtemp(prefix="torch_test_create_")
    try:
        import torch.backup as backup_mod
        orig_dir = backup_mod.TORCH_BACKUP_DIR
        backup_mod.TORCH_BACKUP_DIR = tmpdir3

        # D1: tag=None -> filename contains _auto.zip
        path_auto = _create_torch_backup(tag=None)
        _assert("create: tag=None -> filename contains _auto.zip",
                "_auto.zip" in os.path.basename(path_auto),
                f"got {os.path.basename(path_auto)}")

        # D2: tag="my release" -> spaces become hyphens
        path_tagged = _create_torch_backup(tag="my release")
        _assert("create: tag='my release' -> _my-release.zip in filename",
                "_my-release.zip" in os.path.basename(path_tagged),
                f"got {os.path.basename(path_tagged)}")

        # D3: created file actually exists
        _assert("create: backup zip file exists on disk",
                os.path.isfile(path_tagged),
                f"file not found: {path_tagged}")

        backup_mod.TORCH_BACKUP_DIR = orig_dir
    finally:
        shutil.rmtree(tmpdir3)

    # ── E. data_files inclusion in backups ─────────────────────

    tmpdir4 = tempfile.mkdtemp(prefix="torch_test_datafiles_")
    try:
        import torch.backup as backup_mod
        orig_dir2 = backup_mod.TORCH_BACKUP_DIR
        orig_pkg = backup_mod.TORCH_PACKAGE_DIR
        backup_mod.TORCH_BACKUP_DIR = tmpdir4

        # Create a fake package dir with .py files, data_files/, tests/, __pycache__/
        fake_pkg = os.path.join(tmpdir4, "fake_pkg")
        os.makedirs(fake_pkg)
        backup_mod.TORCH_PACKAGE_DIR = fake_pkg

        # .py file at root
        with open(os.path.join(fake_pkg, "__init__.py"), "w") as f:
            f.write("VERSION = '0.0.1'\n")

        # data_files/ with files and subdirectory
        df_root = os.path.join(fake_pkg, "data_files")
        os.makedirs(df_root)
        with open(os.path.join(df_root, "README.txt"), "w") as f:
            f.write("test data")
        df_sub = os.path.join(df_root, "patches")
        os.makedirs(df_sub)
        with open(os.path.join(df_sub, "patch1.json"), "w") as f:
            f.write('{"test": true}')

        # tests/ and __pycache__/ should be excluded
        os.makedirs(os.path.join(fake_pkg, "tests"))
        with open(os.path.join(fake_pkg, "tests", "test_foo.py"), "w") as f:
            f.write("# test")
        os.makedirs(os.path.join(fake_pkg, "__pycache__"))
        with open(os.path.join(fake_pkg, "__pycache__", "foo.pyc"), "w") as f:
            f.write("bytecode")

        # E1: backup includes data_files/ and .py but not tests/ or __pycache__/
        bk_path = _create_torch_backup(tag="datatest")
        with zipfile.ZipFile(bk_path, "r") as zf:
            names = set(zf.namelist())

        _assert("backup includes __init__.py",
                "__init__.py" in names,
                f"zip contents: {sorted(names)}")

        _assert("backup includes data_files/README.txt",
                "data_files/README.txt" in names,
                f"zip contents: {sorted(names)}")

        _assert("backup includes data_files/patches/patch1.json",
                "data_files/patches/patch1.json" in names,
                f"zip contents: {sorted(names)}")

        _assert("backup excludes tests/test_foo.py",
                "tests/test_foo.py" not in names,
                f"zip contents: {sorted(names)}")

        _assert("backup excludes __pycache__/foo.pyc",
                "__pycache__/foo.pyc" not in names,
                f"zip contents: {sorted(names)}")

        # E2: empty data_files/ (only .gitkeep) still works
        shutil.rmtree(df_root)
        os.makedirs(df_root)
        with open(os.path.join(df_root, ".gitkeep"), "w") as f:
            pass
        bk_path2 = _create_torch_backup(tag="emptydata")
        with zipfile.ZipFile(bk_path2, "r") as zf:
            names2 = set(zf.namelist())
        _assert("backup with .gitkeep-only data_files/ includes .gitkeep",
                "data_files/.gitkeep" in names2,
                f"zip contents: {sorted(names2)}")

        backup_mod.TORCH_BACKUP_DIR = orig_dir2
        backup_mod.TORCH_PACKAGE_DIR = orig_pkg
    finally:
        shutil.rmtree(tmpdir4)
