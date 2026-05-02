"""Config suite -- load, save, settings, nav keys."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Config  (load, save, settings, nav keys)")

    try:
        import torch.config as config_mod
    except ImportError as e:
        _skip("all config tests", f"import failed: {e}")
        return

    original_path = config_mod.CONFIG_PATH

    # 1. load_config returns None when config doesn't exist
    try:
        config_mod.CONFIG_PATH = "/tmp/torch_test_nonexistent_config_xyz.conf"
        result = config_mod.load_config()
        _assert(
            "load_config: returns None for missing file",
            result is None,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("load_config missing file", str(e))
    finally:
        config_mod.CONFIG_PATH = original_path

    # 2. save_config + load_config round-trip
    tmp_dir = tempfile.mkdtemp(prefix="torch_cfg_test_")
    tmp_conf = os.path.join(tmp_dir, "torch.conf")
    try:
        config_mod.CONFIG_PATH = tmp_conf
        config_mod.save_config(
            "~/ROMHacking",
            {"TestProject": {"game_path": "~/Documents/pokeemerald-expansion/"}}
        )
        result = config_mod.load_config()
        _assert(
            "save/load round-trip: returns tuple",
            result is not None and len(result) == 3,
            f"got: {result!r}"
        )
        if result:
            workspace, projects, settings = result
            _assert(
                "save/load round-trip: workspace correct",
                workspace == os.path.join(os.path.expanduser("~/ROMHacking"), "TORCH"),
                f"workspace: {workspace!r}"
            )
            _assert(
                "save/load round-trip: project present",
                "TestProject" in projects,
                f"projects: {projects!r}"
            )
    except Exception as e:
        _fail("save/load round-trip", str(e))
    finally:
        config_mod.CONFIG_PATH = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 3. Settings defaults: all SETTINGS_DEFAULTS keys present
    tmp_dir = tempfile.mkdtemp(prefix="torch_cfg_test_")
    tmp_conf = os.path.join(tmp_dir, "torch.conf")
    try:
        config_mod.CONFIG_PATH = tmp_conf
        config_mod.save_config("~/ROMHacking", {"P": {"game_path": "~/game"}})
        result = config_mod.load_config()
        if result is None:
            _fail("settings defaults: load_config returned None", "")
        else:
            _, _, settings = result
            missing = [k for k in config_mod.SETTINGS_DEFAULTS if k not in settings]
            _assert(
                "settings defaults: all SETTINGS_DEFAULTS keys present",
                len(missing) == 0,
                f"missing keys: {missing}"
            )
    except Exception as e:
        _fail("settings defaults", str(e))
    finally:
        config_mod.CONFIG_PATH = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 4. Settings override: max_snapshots = 5
    tmp_dir = tempfile.mkdtemp(prefix="torch_cfg_test_")
    tmp_conf = os.path.join(tmp_dir, "torch.conf")
    try:
        config_mod.CONFIG_PATH = tmp_conf
        config_mod.save_config(
            "~/ROMHacking",
            {"P": {"game_path": "~/game"}},
            settings={"max_snapshots": 5}
        )
        result = config_mod.load_config()
        if result is None:
            _fail("settings override: load_config returned None", "")
        else:
            _, _, settings = result
            _assert(
                "settings override: max_snapshots == 5",
                settings.get("max_snapshots") == 5,
                f"got: {settings.get('max_snapshots')!r}"
            )
    except Exception as e:
        _fail("settings override", str(e))
    finally:
        config_mod.CONFIG_PATH = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 5. Boolean setting: show_all_trainers = true parsed as Python bool
    tmp_dir = tempfile.mkdtemp(prefix="torch_cfg_test_")
    tmp_conf = os.path.join(tmp_dir, "torch.conf")
    try:
        config_mod.CONFIG_PATH = tmp_conf
        config_mod.save_config(
            "~/ROMHacking",
            {"P": {"game_path": "~/game"}},
            settings={"show_all_trainers": True}
        )
        result = config_mod.load_config()
        if result is None:
            _fail("boolean setting: load_config returned None", "")
        else:
            _, _, settings = result
            val = settings.get("show_all_trainers")
            _assert(
                "boolean setting: show_all_trainers is True (Python bool)",
                val is True,
                f"got: {val!r} (type={type(val).__name__})"
            )
    except Exception as e:
        _fail("boolean setting", str(e))
    finally:
        config_mod.CONFIG_PATH = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 6. Multiple projects: save 2, load, verify both present
    tmp_dir = tempfile.mkdtemp(prefix="torch_cfg_test_")
    tmp_conf = os.path.join(tmp_dir, "torch.conf")
    try:
        config_mod.CONFIG_PATH = tmp_conf
        config_mod.save_config(
            "~/ROMHacking",
            {
                "ProjectA": {"game_path": "~/gameA"},
                "ProjectB": {"game_path": "~/gameB"},
            }
        )
        result = config_mod.load_config()
        if result is None:
            _fail("multiple projects: load_config returned None", "")
        else:
            _, projects, _ = result
            _assert(
                "multiple projects: both present",
                "ProjectA" in projects and "ProjectB" in projects,
                f"projects: {list(projects.keys())}"
            )
    except Exception as e:
        _fail("multiple projects", str(e))
    finally:
        config_mod.CONFIG_PATH = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 7. Non-default settings only written to disk
    tmp_dir = tempfile.mkdtemp(prefix="torch_cfg_test_")
    tmp_conf = os.path.join(tmp_dir, "torch.conf")
    try:
        config_mod.CONFIG_PATH = tmp_conf
        config_mod.save_config(
            "~/ROMHacking",
            {"P": {"game_path": "~/game"}},
            settings={"max_snapshots": 5}
        )
        with open(tmp_conf, "r") as f:
            contents = f.read()
        _assert(
            "non-default only: max_snapshots written to file",
            "max_snapshots = 5" in contents,
            f"file did not contain 'max_snapshots = 5'"
        )
        _assert(
            "non-default only: editor_visible_beats NOT in file",
            "editor_visible_beats" not in contents,
            "default key editor_visible_beats should not be in file"
        )
    except Exception as e:
        _fail("non-default settings only", str(e))
    finally:
        config_mod.CONFIG_PATH = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 8. _nav_keys returns correct tuple from settings and defaults
    try:
        result = config_mod._nav_keys({})
        _assert(
            "_nav_keys: defaults when keys missing",
            result == ("", "u", "j", "v"),
            f"got: {result!r}"
        )
        custom = {"nav_scroll": "s", "nav_up": "k", "nav_down": "l", "nav_open": "o"}
        result2 = config_mod._nav_keys(custom)
        _assert(
            "_nav_keys: custom keys returned",
            result2 == ("s", "k", "l", "o"),
            f"got: {result2!r}"
        )
    except Exception as e:
        _fail("_nav_keys", str(e))
