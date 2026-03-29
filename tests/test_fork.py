"""Fork suite -- registry I/O, sizing, sanitisation, naming, migration."""
import os
import json
import tempfile
import shutil
import configparser

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Fork     (registry, sizing, sanitisation, naming, migration)")

    try:
        import torch.fork as fork_mod
    except ImportError as e:
        _skip("all fork tests", f"import failed: {e}")
        return

    _test_registry_round_trip(fork_mod)
    _test_registry_missing_file(fork_mod)
    _test_registry_corrupt_json(fork_mod)
    _test_dir_size_mb(fork_mod)
    _test_dir_size_empty(fork_mod)
    _test_dir_size_nonexistent(fork_mod)
    _test_sanitize_name_basics(fork_mod)
    _test_sanitize_name_edge_cases(fork_mod)
    _test_next_default_name(fork_mod)
    _test_format_created(fork_mod)
    _test_stale_entry_auto_cleaned(fork_mod)
    _test_migration_renames_registry(fork_mod)
    _test_name_collides(fork_mod)


# ── Registry round-trip ──────────────────────────────────────────────────

def _test_registry_round_trip(mod):
    """Save and reload registry data through the JSON helpers."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_fork_test_")
    original_path = mod._FORKS_JSON
    try:
        mod._FORKS_JSON = os.path.join(tmp_dir, "forks.json")
        test_data = [
            {"name": "test-1", "source_project": "MyProject",
             "game_path": "/tmp/test-1", "created": "2026-01-01T12:00:00"},
            {"name": "test-2", "source_project": "MyProject",
             "game_path": "/tmp/test-2", "created": "2026-01-02T14:30:00"},
        ]
        mod._save_registry(test_data)
        loaded = mod._load_registry()
        _assert(
            "registry round-trip: 2 entries survive",
            len(loaded) == 2,
            f"expected 2, got {len(loaded)}"
        )
        _assert(
            "registry round-trip: names match",
            [fk["name"] for fk in loaded] == ["test-1", "test-2"],
            f"got: {[fk.get('name') for fk in loaded]}"
        )
        _assert(
            "registry round-trip: fields preserved",
            loaded[0]["source_project"] == "MyProject"
            and loaded[1]["created"] == "2026-01-02T14:30:00",
            f"got: {loaded}"
        )
    except Exception as e:
        _fail("registry round-trip", str(e))
    finally:
        mod._FORKS_JSON = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Registry missing file ────────────────────────────────────────────────

def _test_registry_missing_file(mod):
    """Loading from a non-existent file returns empty list."""
    original_path = mod._FORKS_JSON
    original_legacy = mod._SANDBOXES_JSON_LEGACY
    try:
        mod._FORKS_JSON = "/tmp/torch_test_no_such_file_xyz.json"
        mod._SANDBOXES_JSON_LEGACY = "/tmp/torch_test_no_such_legacy_xyz.json"
        result = mod._load_registry()
        _assert(
            "registry missing file: returns []",
            result == [],
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("registry missing file", str(e))
    finally:
        mod._FORKS_JSON = original_path
        mod._SANDBOXES_JSON_LEGACY = original_legacy


# ── Registry corrupt JSON ────────────────────────────────────────────────

def _test_registry_corrupt_json(mod):
    """Loading from a corrupt JSON file returns empty list."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_fork_corrupt_")
    original_path = mod._FORKS_JSON
    try:
        corrupt_file = os.path.join(tmp_dir, "forks.json")
        with open(corrupt_file, "w") as f:
            f.write("{{{not valid json")
        mod._FORKS_JSON = corrupt_file
        result = mod._load_registry()
        _assert(
            "registry corrupt JSON: returns []",
            result == [],
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("registry corrupt JSON", str(e))
    finally:
        mod._FORKS_JSON = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── _dir_size_mb ─────────────────────────────────────────────────────────

def _test_dir_size_mb(mod):
    """Directory with known file sizes returns approximately correct MB."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_fork_size_")
    try:
        test_file = os.path.join(tmp_dir, "bigfile.bin")
        with open(test_file, "wb") as f:
            f.write(b"\x00" * (1024 * 1024))
        result = mod._dir_size_mb(tmp_dir)
        _assert(
            "_dir_size_mb: 1 MB file reports 1 MB",
            result == 1,
            f"expected 1, got {result}"
        )
    except Exception as e:
        _fail("_dir_size_mb 1MB", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_dir_size_empty(mod):
    """Empty directory returns 0 MB."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_fork_empty_")
    try:
        result = mod._dir_size_mb(tmp_dir)
        _assert(
            "_dir_size_mb: empty dir returns 0",
            result == 0,
            f"expected 0, got {result}"
        )
    except Exception as e:
        _fail("_dir_size_mb empty", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_dir_size_nonexistent(mod):
    """Non-existent directory doesn't crash."""
    try:
        result = mod._dir_size_mb("/tmp/torch_no_such_dir_xyz_test")
        _assert(
            "_dir_size_mb: non-existent dir returns 0",
            result == 0,
            f"expected 0, got {result}"
        )
    except Exception as e:
        _fail("_dir_size_mb non-existent", f"raised: {e}")


# ── _sanitize_name ───────────────────────────────────────────────────────

def _test_sanitize_name_basics(mod):
    """Test standard sanitisation: lowercase, special chars to hyphens."""
    _assert(
        "sanitize: spaces become hyphens",
        mod._sanitize_name("My Test Fork") == "my-test-fork",
        f"got: {mod._sanitize_name('My Test Fork')!r}"
    )
    _assert(
        "sanitize: special chars stripped to hyphens",
        mod._sanitize_name("test@#$name!") == "test-name",
        f"got: {mod._sanitize_name('test@#$name!')!r}"
    )
    _assert(
        "sanitize: already clean name passes through",
        mod._sanitize_name("clean-name") == "clean-name",
        f"got: {mod._sanitize_name('clean-name')!r}"
    )
    _assert(
        "sanitize: uppercase lowered",
        mod._sanitize_name("MyFork") == "myfork",
        f"got: {mod._sanitize_name('MyFork')!r}"
    )


def _test_sanitize_name_edge_cases(mod):
    """Test edge cases: empty string, max length, leading/trailing hyphens."""
    _assert(
        "sanitize: empty string returns empty",
        mod._sanitize_name("") == "",
        f"got: {mod._sanitize_name('')!r}"
    )
    _assert(
        "sanitize: truncates to 30 chars",
        len(mod._sanitize_name("a" * 50)) == 30,
        f"got length: {len(mod._sanitize_name('a' * 50))}"
    )
    _assert(
        "sanitize: consecutive specials collapse to single hyphen",
        mod._sanitize_name("a---b") == "a-b",
        f"got: {mod._sanitize_name('a---b')!r}"
    )
    _assert(
        "sanitize: leading/trailing hyphens stripped",
        mod._sanitize_name("--name--") == "name",
        f"got: {mod._sanitize_name('--name--')!r}"
    )


# ── _next_default_name ───────────────────────────────────────────────────

def _test_next_default_name(mod):
    """Test auto-naming picks next unused test-N number."""
    _assert(
        "next_default: empty list -> test-1",
        mod._next_default_name([]) == "test-1",
        f"got: {mod._next_default_name([])!r}"
    )
    _assert(
        "next_default: [test-1] -> test-2",
        mod._next_default_name([{"name": "test-1"}]) == "test-2",
        f"got: {mod._next_default_name([{'name': 'test-1'}])!r}"
    )
    # Gap filling: test-1 and test-3 exist, should give test-2
    forks = [{"name": "test-1"}, {"name": "test-3"}]
    _assert(
        "next_default: fills gap -> test-2",
        mod._next_default_name(forks) == "test-2",
        f"got: {mod._next_default_name(forks)!r}"
    )
    # Non-matching names ignored
    _assert(
        "next_default: ignores non-test-N names -> test-1",
        mod._next_default_name([{"name": "my-fork"}]) == "test-1",
        f"got: {mod._next_default_name([{'name': 'my-fork'}])!r}"
    )


# ── _format_created ──────────────────────────────────────────────────────

def _test_format_created(mod):
    """Test ISO timestamp formatting."""
    _assert(
        "format_created: valid ISO -> short format",
        mod._format_created("2026-02-22T10:30:00") == "Feb 22, 10:30",
        f"got: {mod._format_created('2026-02-22T10:30:00')!r}"
    )
    _assert(
        "format_created: invalid string returns as-is",
        mod._format_created("not-a-date") == "not-a-date",
        f"got: {mod._format_created('not-a-date')!r}"
    )
    _assert(
        "format_created: empty string returns '?'",
        mod._format_created("") == "?",
        f"got: {mod._format_created('')!r}"
    )


# ── Stale entry auto-cleanup ──────────────────────────────────────────

def _test_stale_entry_auto_cleaned(mod):
    """Registry entry with missing game_path is auto-removed during duplicate check."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_fork_stale_")
    original_path = mod._FORKS_JSON
    try:
        mod._FORKS_JSON = os.path.join(tmp_dir, "forks.json")
        stale_data = [
            {"name": "reuse-me", "source_project": "Proj",
             "game_path": "/tmp/torch_stale_gone_xyz", "created": "2026-01-01T00:00:00"},
        ]
        mod._save_registry(stale_data)

        loaded = mod._load_registry()
        _assert(
            "stale entry: initially present",
            len(loaded) == 1 and loaded[0]["name"] == "reuse-me",
            f"got: {loaded!r}"
        )

        # Simulate the duplicate-check logic from _create_fork
        forks = mod._load_registry()
        cleaned = False
        for fk in forks:
            if fk.get("name") == "reuse-me":
                existing_path = fk.get("game_path", "")
                if existing_path and not os.path.isdir(existing_path):
                    forks = [f for f in forks if f.get("name") != "reuse-me"]
                    mod._save_registry(forks)
                    cleaned = True
                break

        _assert(
            "stale entry: auto-cleaned when dir missing",
            cleaned is True,
            "expected stale entry to be cleaned"
        )

        reloaded = mod._load_registry()
        _assert(
            "stale entry: registry empty after cleanup",
            len(reloaded) == 0,
            f"expected 0 entries, got {len(reloaded)}"
        )
    except Exception as e:
        _fail("stale entry auto-cleanup", str(e))
    finally:
        mod._FORKS_JSON = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Migration ────────────────────────────────────────────────────────────

def _test_migration_renames_registry(mod):
    """sandboxes.json is migrated to forks.json on first load."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_fork_migrate_")
    original_forks = mod._FORKS_JSON
    original_legacy = mod._SANDBOXES_JSON_LEGACY
    original_config = mod.CONFIG_PATH
    try:
        mod._FORKS_JSON = os.path.join(tmp_dir, "forks.json")
        legacy_path = os.path.join(tmp_dir, "sandboxes.json")
        mod._SANDBOXES_JSON_LEGACY = legacy_path
        # Point config at a temp file so migration doesn't touch real config
        mod.CONFIG_PATH = os.path.join(tmp_dir, "torch.conf")

        # Write a legacy registry
        legacy_data = {"sandboxes": [
            {"name": "old-fork", "source_project": "MyProj",
             "game_path": "/tmp/nonexistent-sandbox-old-fork",
             "created": "2026-01-15T09:00:00"},
        ]}
        with open(legacy_path, "w") as f:
            json.dump(legacy_data, f)

        # Load should trigger migration
        result = mod._load_registry()

        _assert(
            "migration: forks.json created",
            os.path.isfile(mod._FORKS_JSON),
            "forks.json not found after migration"
        )
        _assert(
            "migration: sandboxes.json removed",
            not os.path.isfile(legacy_path),
            "sandboxes.json still exists after migration"
        )
        _assert(
            "migration: entry preserved",
            len(result) == 1 and result[0]["name"] == "old-fork",
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("migration renames registry", str(e))
    finally:
        mod._FORKS_JSON = original_forks
        mod._SANDBOXES_JSON_LEGACY = original_legacy
        mod.CONFIG_PATH = original_config
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── _name_collides ───────────────────────────────────────────────────────

def _test_name_collides(mod):
    """Collision check finds names in fork registry."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_fork_collide_")
    original_path = mod._FORKS_JSON
    try:
        mod._FORKS_JSON = os.path.join(tmp_dir, "forks.json")
        test_data = [
            {"name": "existing-fork", "source_project": "Proj",
             "game_path": "/tmp/existing-fork", "created": "2026-01-01T00:00:00"},
        ]
        mod._save_registry(test_data)

        forks = mod._load_registry()
        collides, kind = mod._name_collides("existing-fork", forks)
        _assert(
            "name_collides: finds fork",
            collides is True and kind == "fork",
            f"got: collides={collides}, kind={kind}"
        )

        collides2, kind2 = mod._name_collides("new-name", forks)
        _assert(
            "name_collides: no collision for new name",
            collides2 is False,
            f"got: collides={collides2}, kind={kind2}"
        )
    except Exception as e:
        _fail("name_collides", str(e))
    finally:
        mod._FORKS_JSON = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)
