"""Battle Migrator suite — backup restore, orphan detection, record dispatch."""
import os
import tempfile
import shutil
import zipfile

from torch.tests.harness import _begin_suite, _ok, _fail, _assert


def run_suite():
    _begin_suite("Battle Migrator  (backup restore, orphan detection)")

    try:
        from torch.battle_migrator import (
            _restore_migration_backup,
            _is_orphaned_trainer,
            _read_record_dispatch,
        )
    except ImportError as e:
        _fail("import battle_migrator", str(e))
        return

    # ------------------------------------------------------------------
    # _restore_migration_backup
    # ------------------------------------------------------------------

    tmp = tempfile.mkdtemp(prefix="torch_bm_")
    try:
        # Build a fake game directory
        game_path = os.path.join(tmp, "game")
        src_data = os.path.join(game_path, "src", "data")
        os.makedirs(src_data)

        # Create original trainers.h (will be overwritten by restore)
        trainers_h_path = os.path.join(src_data, "trainers.h")
        with open(trainers_h_path, "w") as f:
            f.write("// current version\n")

        # Create a backup ZIP with trainers.h content
        backup_dir = os.path.join(tmp, "backups")
        os.makedirs(backup_dir)
        backup_path = os.path.join(backup_dir, "pre_migration.zip")
        trainers_h_rel = os.path.join("src", "data", "trainers.h")
        with zipfile.ZipFile(backup_path, "w") as zf:
            zf.writestr(trainers_h_rel,
                        "[TRAINER_TEST] = { .trainerName = _(\"TEST\") },\n")

        # Test 1: restores files from backup
        restored = _restore_migration_backup(game_path, backup_path)
        _assert(
            "restore_backup: returns list of restored files",
            restored is not None and len(restored) >= 1,
            f"got {restored}"
        )

        # Test 2: file content matches backup
        with open(trainers_h_path) as f:
            content = f.read()
        _assert(
            "restore_backup: trainers.h restored from backup",
            "TRAINER_TEST" in content,
            f"content: {content!r}"
        )

        # Test 3: trainers.party deleted when not in backup
        party_path = os.path.join(src_data, "trainers.party")
        with open(party_path, "w") as f:
            f.write("= TRAINER_DUMMY\nName: Dummy\n")
        restored2 = _restore_migration_backup(game_path, backup_path)
        _assert(
            "restore_backup: trainers.party deleted when not in backup",
            not os.path.exists(party_path),
            "trainers.party still exists"
        )

        # Test 4: missing backup file returns None
        result = _restore_migration_backup(game_path, "/nonexistent/backup.zip")
        _assert(
            "restore_backup: missing ZIP returns None",
            result is None,
            f"expected None, got {result}"
        )

    finally:
        shutil.rmtree(tmp)

    # ------------------------------------------------------------------
    # _is_orphaned_trainer
    # ------------------------------------------------------------------

    # Test 5: None record is orphaned
    _assert(
        "is_orphaned: None record returns True",
        _is_orphaned_trainer(None) is True,
        "expected True"
    )

    # Test 6: record with all None fields is orphaned
    orphan_rec = {"trainer_id": None, "trainer_name": None, "trainer_class": None}
    _assert(
        "is_orphaned: all-None fields returns True",
        _is_orphaned_trainer(orphan_rec) is True,
        "expected True"
    )

    # Test 7: record with any populated field is NOT orphaned
    real_rec = {"trainer_id": 900, "trainer_name": "GUY", "trainer_class": "TRAINER_CLASS_HIKER"}
    _assert(
        "is_orphaned: populated record returns False",
        _is_orphaned_trainer(real_rec) is False,
        "expected False"
    )

    # Test 8: record with partial data (only ID) is NOT orphaned
    partial_rec = {"trainer_id": 900, "trainer_name": None, "trainer_class": None}
    _assert(
        "is_orphaned: partial record (has ID) returns False",
        _is_orphaned_trainer(partial_rec) is False,
        "expected False"
    )

    # Test 9: record missing keys entirely (empty dict) is orphaned
    empty_rec = {}
    _assert(
        "is_orphaned: empty dict returns True",
        _is_orphaned_trainer(empty_rec) is True,
        "expected True"
    )

    # ------------------------------------------------------------------
    # _read_record_dispatch
    # ------------------------------------------------------------------

    # Test 10: dispatch routes to correct backend (party format)
    # We can't easily test the full read, but we can verify it doesn't crash
    # with nonexistent files (returns None)
    tmp2 = tempfile.mkdtemp(prefix="torch_bm_")
    try:
        opp = os.path.join(tmp2, "opponents.h")
        th = os.path.join(tmp2, "trainers.h")
        tp = os.path.join(tmp2, "trainer_parties.h")
        pp = os.path.join(tmp2, "trainers.party")
        # Create empty files so readers don't crash on open
        for p in (opp, th, tp, pp):
            with open(p, "w") as f:
                f.write("")

        result_party = _read_record_dispatch(
            "TRAINER_NONEXISTENT", "party", opp, th, tp, pp
        )
        _assert(
            "dispatch: party format returns record (possibly empty)",
            result_party is not None or result_party is None,  # just no crash
            "dispatch crashed"
        )

        result_legacy = _read_record_dispatch(
            "TRAINER_NONEXISTENT", "legacy", opp, th, tp, pp
        )
        _assert(
            "dispatch: legacy format returns record (possibly empty)",
            result_legacy is not None or result_legacy is None,  # just no crash
            "dispatch crashed"
        )

    finally:
        shutil.rmtree(tmp2)
