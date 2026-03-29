"""Game Version Control suite -- create, list, restore, delete, bump, repair."""
import os
import tempfile
import shutil
import zipfile
import json

from torch.tests.harness import _begin_suite, _ok, _fail, _assert


def run_suite():
    _begin_suite("Game Version Control")

    try:
        from torch.game_versions import (
            create_version, list_versions, get_version_info,
            restore_version, delete_version, bump_major,
            get_disk_usage, repair_manifest,
            _load_manifest, _save_manifest, _slugify, _next_version,
            _get_version_dir, _collect_game_files, _collect_workspace_files,
            METADATA_FILE, ROM_PREFIX, WORKSPACE_PREFIX,
            VERSION_DIR, MANIFEST_FILE, WORKSPACE_EXCLUDE,
        )
    except ImportError as e:
        from torch.tests.harness import _skip
        _skip("all game version tests", f"import failed: {e}")
        return

    # ================================================================
    # Helpers
    # ================================================================

    def _make_fake_game(base):
        """Create a fake game directory with test files. Returns dict of rel->content."""
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

    def _make_fake_rom(base, name="pokeemerald.gba"):
        """Create a fake ROM file. Returns path."""
        rom_path = os.path.join(base, name)
        with open(rom_path, "wb") as f:
            f.write(b"\x00" * 1024)  # 1KB fake ROM
        return rom_path

    def _make_fake_workspace(base):
        """Create a fake TORCH workspace. Returns dict of rel->content."""
        os.makedirs(os.path.join(base, "TestMap"), exist_ok=True)
        os.makedirs(os.path.join(base, "TestMap", "backups", "snapshots"), exist_ok=True)
        os.makedirs(os.path.join(base, "OtherMap"), exist_ok=True)
        files = {
            os.path.join("TestMap", "setup.txt"): "setup content",
            os.path.join("TestMap", "npc.txt"): "npc content",
            os.path.join("TestMap", "backups", "snapshots", "old.zip"): "should be excluded",
            os.path.join("OtherMap", "setup.txt"): "other setup",
        }
        for rel, content in files.items():
            with open(os.path.join(base, rel), "w") as f:
                f.write(content)
        return files

    # ================================================================
    # _slugify tests
    # ================================================================

    _assert("slugify: basic label", _slugify("First Gym Complete") == "first-gym-complete")
    _assert("slugify: special chars", _slugify("Pre-E4 (rewrite)!") == "pre-e4-rewrite")
    _assert("slugify: empty string", _slugify("") == "unnamed")
    _assert("slugify: only special chars", _slugify("!!!") == "unnamed")
    _assert("slugify: numbers preserved", _slugify("Version 2.0 beta") == "version-2-0-beta")
    _assert("slugify: leading/trailing hyphens stripped",
            _slugify("  --hello world--  ") == "hello-world")

    # ================================================================
    # Manifest helpers
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        # Load default manifest when none exists
        m = _load_manifest(tmp)
        _assert("manifest: default when missing",
                m["schema_version"] == 1 and m["next_major"] == 0
                and m["next_minor"] == 1 and m["versions"] == [])

        # Save and reload
        m["versions"].append({"version": "0.1", "label": "test"})
        m["next_minor"] = 2
        _save_manifest(tmp, m)

        m2 = _load_manifest(tmp)
        _assert("manifest: round-trip",
                m2["next_minor"] == 2 and len(m2["versions"]) == 1
                and m2["versions"][0]["label"] == "test")

        # Verify atomic write produced valid JSON
        manifest_path = os.path.join(tmp, "backups", VERSION_DIR, MANIFEST_FILE)
        with open(manifest_path) as f:
            raw = json.load(f)
        _assert("manifest: valid JSON on disk", raw["next_minor"] == 2)

    except Exception as e:
        _fail("manifest helpers", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Corrupt manifest falls back to default
    tmp = tempfile.mkdtemp()
    try:
        vdir = os.path.join(tmp, "backups", VERSION_DIR)
        os.makedirs(vdir, exist_ok=True)
        with open(os.path.join(vdir, MANIFEST_FILE), "w") as f:
            f.write("NOT JSON{{{")
        m = _load_manifest(tmp)
        _assert("manifest: fallback on corrupt", m["schema_version"] == 1 and m["versions"] == [])
    except Exception as e:
        _fail("manifest: fallback on corrupt", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # _next_version
    # ================================================================

    _assert("next_version: default",
            _next_version({"next_major": 0, "next_minor": 1}) == ("0.1", 0, 1))
    _assert("next_version: after bump",
            _next_version({"next_major": 2, "next_minor": 0}) == ("2.0", 2, 0))
    _assert("next_version: incremented",
            _next_version({"next_major": 1, "next_minor": 5}) == ("1.5", 1, 5))

    # ================================================================
    # create_version — basic
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        project_dir = os.path.join(tmp, "workspace")
        os.makedirs(game_path)
        os.makedirs(project_dir)
        _make_fake_game(game_path)
        _make_fake_rom(game_path)
        _make_fake_workspace(project_dir)

        entry = create_version(game_path, project_dir, label="Test Version", notes="some notes")
        _assert("create: returns entry dict",
                entry is not None and entry["version"] == "0.1"
                and entry["label"] == "Test Version")
        _assert("create: correct filename",
                entry["filename"] == "v0.1_test-version.zip")
        _assert("create: has ROM info",
                entry["rom_filename"] == "pokeemerald.gba"
                and entry["rom_size_bytes"] > 0)
        _assert("create: has size",
                entry["size_bytes"] > 0)
        _assert("create: has notes", entry["notes"] == "some notes")

        # Verify ZIP exists
        zip_path = os.path.join(game_path, "backups", VERSION_DIR, entry["filename"])
        _assert("create: ZIP exists on disk", os.path.isfile(zip_path))

        # Verify ZIP contents
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            has_meta = METADATA_FILE in names
            has_rom = any(n.startswith(f"{ROM_PREFIX}/") for n in names)
            has_workspace = any(n.startswith(f"{WORKSPACE_PREFIX}/") for n in names)
            has_game = any("scripts.pory" in n for n in names)
            # Workspace backups should be excluded
            has_excluded = any("backups" in n for n in names
                               if n.startswith(f"{WORKSPACE_PREFIX}/"))
            _assert("create: ZIP has metadata", has_meta)
            _assert("create: ZIP has ROM", has_rom)
            _assert("create: ZIP has workspace", has_workspace)
            _assert("create: ZIP has game files", has_game)
            _assert("create: workspace excludes backups/", not has_excluded)

        # Verify manifest updated
        m = _load_manifest(game_path)
        _assert("create: manifest updated",
                len(m["versions"]) == 1 and m["next_minor"] == 2)

    except Exception as e:
        _fail("create_version basic", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # create_version — without ROM
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)
        # No ROM created

        entry = create_version(game_path, "", label="No ROM")
        _assert("create without ROM: succeeds",
                entry is not None and entry["rom_filename"] == "")
    except Exception as e:
        _fail("create without ROM", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # create_version — sequential versions auto-increment
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)

        e1 = create_version(game_path, "", label="First")
        e2 = create_version(game_path, "", label="Second")
        e3 = create_version(game_path, "", label="Third")
        _assert("auto-increment: sequential versions",
                e1["version"] == "0.1" and e2["version"] == "0.2"
                and e3["version"] == "0.3")

        m = _load_manifest(game_path)
        _assert("auto-increment: manifest next_minor",
                m["next_minor"] == 4)
    except Exception as e:
        _fail("auto-increment", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # list_versions
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)

        create_version(game_path, "", label="Alpha")
        create_version(game_path, "", label="Beta")
        create_version(game_path, "", label="Gamma")

        versions = list_versions(game_path)
        _assert("list: returns 3 versions", len(versions) == 3)
        _assert("list: newest first",
                versions[0]["version"] == "0.3"
                and versions[1]["version"] == "0.2"
                and versions[2]["version"] == "0.1")
        _assert("list: has display_time", all("display_time" in v for v in versions))
        _assert("list: has size_mb", all("size_mb" in v for v in versions))
        _assert("list: has path", all("path" in v for v in versions))
    except Exception as e:
        _fail("list_versions", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # list_versions — missing ZIP filtered out
    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)

        create_version(game_path, "", label="Exists")
        create_version(game_path, "", label="Will Delete")

        # Manually delete the ZIP for v0.2
        vdir = os.path.join(game_path, "backups", VERSION_DIR)
        for f in os.listdir(vdir):
            if f.startswith("v0.2") and f.endswith(".zip"):
                os.remove(os.path.join(vdir, f))

        versions = list_versions(game_path)
        _assert("list: missing ZIP filtered", len(versions) == 1
                and versions[0]["version"] == "0.1")
    except Exception as e:
        _fail("list: missing ZIP filtered", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # get_version_info
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)

        create_version(game_path, "", label="Info Test")
        info = get_version_info(game_path, "0.1")
        _assert("get_info: found", info is not None and info["label"] == "Info Test")

        info2 = get_version_info(game_path, "99.99")
        _assert("get_info: not found returns None", info2 is None)
    except Exception as e:
        _fail("get_version_info", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # delete_version
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)

        create_version(game_path, "", label="Keep")
        create_version(game_path, "", label="Delete Me")

        result = delete_version(game_path, "0.2")
        _assert("delete: returns True", result is True)

        # ZIP gone
        vdir = os.path.join(game_path, "backups", VERSION_DIR)
        remaining_zips = [f for f in os.listdir(vdir) if f.endswith(".zip")]
        _assert("delete: ZIP removed", len(remaining_zips) == 1)

        # Manifest updated
        m = _load_manifest(game_path)
        _assert("delete: manifest entry removed", len(m["versions"]) == 1
                and m["versions"][0]["version"] == "0.1")

        # next_minor NOT decremented (never reuse)
        _assert("delete: next_minor unchanged", m["next_minor"] == 3)

        # Delete nonexistent
        result2 = delete_version(game_path, "99.99")
        _assert("delete: nonexistent returns False", result2 is False)
    except Exception as e:
        _fail("delete_version", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # bump_major
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)

        create_version(game_path, "", label="Pre-bump")
        new_ver = bump_major(game_path)
        _assert("bump: returns new version string", new_ver == "1.0")

        m = _load_manifest(game_path)
        _assert("bump: manifest updated",
                m["next_major"] == 1 and m["next_minor"] == 0)

        # Next create uses bumped version
        entry = create_version(game_path, "", label="Post-bump")
        _assert("bump: next create uses new major",
                entry["version"] == "1.0" and entry["major"] == 1)

        # Second create after bump
        entry2 = create_version(game_path, "", label="Another")
        _assert("bump: subsequent versions increment minor",
                entry2["version"] == "1.1")
    except Exception as e:
        _fail("bump_major", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # get_disk_usage
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)

        total, count = get_disk_usage(game_path)
        _assert("disk_usage: empty", total == 0 and count == 0)

        create_version(game_path, "", label="DU Test")
        total, count = get_disk_usage(game_path)
        _assert("disk_usage: one version", count == 1 and total > 0)
    except Exception as e:
        _fail("get_disk_usage", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # repair_manifest
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)

        create_version(game_path, "", label="Repair A")
        create_version(game_path, "", label="Repair B")

        # Delete manifest
        vdir = os.path.join(game_path, "backups", VERSION_DIR)
        mpath = os.path.join(vdir, MANIFEST_FILE)
        os.remove(mpath)
        _assert("repair: manifest deleted", not os.path.exists(mpath))

        count = repair_manifest(game_path)
        _assert("repair: found 2 versions", count == 2)

        # Manifest restored
        m = _load_manifest(game_path)
        _assert("repair: manifest has 2 entries", len(m["versions"]) == 2)
        _assert("repair: next_minor set correctly", m["next_minor"] == 3)

        # Versions still listable
        versions = list_versions(game_path)
        _assert("repair: versions listable after repair", len(versions) == 2)
    except Exception as e:
        _fail("repair_manifest", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # No auto-deletion — creating many versions keeps all
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)

        for i in range(10):
            create_version(game_path, "", label=f"Version {i}")

        versions = list_versions(game_path)
        _assert("no auto-delete: all 10 versions kept", len(versions) == 10)

        vdir = os.path.join(game_path, "backups", VERSION_DIR)
        zips = [f for f in os.listdir(vdir) if f.endswith(".zip")]
        _assert("no auto-delete: all 10 ZIPs on disk", len(zips) == 10)
    except Exception as e:
        _fail("no auto-delete", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # _collect_workspace_files excludes backups
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        _make_fake_workspace(tmp)
        files = _collect_workspace_files(tmp)
        # Should include setup.txt and npc.txt but not backups/snapshots/old.zip
        has_setup = any("setup.txt" in f for f in files)
        has_excluded = any("backups" in f for f in files)
        _assert("workspace collect: includes source files", has_setup)
        _assert("workspace collect: excludes backups/", not has_excluded)
    except Exception as e:
        _fail("workspace collect", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # _collect_workspace_files — empty/missing dir
    # ================================================================

    files = _collect_workspace_files("")
    _assert("workspace collect: empty path returns []", files == [])

    files = _collect_workspace_files("/nonexistent/path/xyz")
    _assert("workspace collect: nonexistent returns []", files == [])

    # ================================================================
    # create_version with metadata inside ZIP
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        game_path = os.path.join(tmp, "game")
        os.makedirs(game_path)
        _make_fake_game(game_path)
        _make_fake_rom(game_path)

        entry = create_version(game_path, "", label="Meta Check")
        zip_path = os.path.join(game_path, "backups", VERSION_DIR, entry["filename"])
        with zipfile.ZipFile(zip_path, "r") as zf:
            meta = json.loads(zf.read(METADATA_FILE))
            _assert("meta in ZIP: has version", meta["version"] == "0.1")
            _assert("meta in ZIP: has label", meta["label"] == "Meta Check")
            _assert("meta in ZIP: has rom_filename", meta["rom_filename"] == "pokeemerald.gba")
            _assert("meta in ZIP: has dirs_included",
                    "data/maps" in meta["dirs_included"])
    except Exception as e:
        _fail("metadata in ZIP", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # _get_version_dir creates directory
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        vdir = _get_version_dir(tmp)
        _assert("get_version_dir: creates dir", os.path.isdir(vdir))
        _assert("get_version_dir: correct path",
                vdir == os.path.join(tmp, "backups", VERSION_DIR))
    except Exception as e:
        _fail("_get_version_dir", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # Empty game path returns empty list
    # ================================================================

    tmp = tempfile.mkdtemp()
    try:
        _assert("list: empty game returns []", list_versions(tmp) == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
