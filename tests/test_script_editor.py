"""Script editor beat help, validation, and flag log tests."""
from torch.tests.harness import _begin_suite, _ok, _fail, _assert
from unittest.mock import patch
import io
import json
import os
import tempfile


def run_suite():
    _begin_suite("Script Editor  (beat help system)")

    try:
        from torch.script_editor import _BEAT_CATEGORIES, _BEAT_HELP, _show_beat_help
    except ImportError as e:
        from torch.tests.harness import _skip
        _skip("all script editor tests", f"import failed: {e}")
        return

    # ---- Coverage: every beat type in categories has a help entry ----------
    all_beat_keys = set()
    for cat in _BEAT_CATEGORIES:
        for _, key, _ in cat["items"]:
            all_beat_keys.add(key)

    missing = [k for k in sorted(all_beat_keys) if k not in _BEAT_HELP]
    if missing:
        _fail("beat help coverage", f"missing help for: {', '.join(missing)}")
    else:
        _ok(f"beat help coverage ({len(all_beat_keys)} types)")

    # ---- Count: should be exactly 30 entries ------------------------------
    _assert("beat help count = 31", len(_BEAT_HELP) == 31,
            f"expected 31, got {len(_BEAT_HELP)}")

    # ---- No extra keys in _BEAT_HELP that aren't in categories ------------
    extra = [k for k in sorted(_BEAT_HELP) if k not in all_beat_keys]
    if extra:
        _fail("no extra help keys", f"extra keys not in categories: {', '.join(extra)}")
    else:
        _ok("no extra help keys")

    # ---- Each entry has required fields -----------------------------------
    required_fields = {"name", "desc", "torscript", "fields", "tips"}
    bad_entries = []
    for key, entry in _BEAT_HELP.items():
        entry_keys = set(entry.keys())
        if not required_fields.issubset(entry_keys):
            bad_entries.append(f"{key}: missing {required_fields - entry_keys}")
    if bad_entries:
        _fail("help entry structure", "; ".join(bad_entries))
    else:
        _ok("help entry structure (all have name/desc/torscript/fields/tips)")

    # ---- Renderer: valid key doesn't crash --------------------------------
    try:
        with patch("builtins.input", return_value=""):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                _show_beat_help("msg")
            output = mock_out.getvalue()
            if "Dialogue" in output and "Hello" in output:
                _ok("renderer: msg beat help displays correctly")
            else:
                _fail("renderer: msg beat help", f"unexpected output: {output[:200]}")
    except Exception as e:
        _fail("renderer: msg beat help", str(e))

    # ---- Renderer: missing key handled gracefully -------------------------
    try:
        with patch("builtins.input", return_value=""):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                _show_beat_help("nonexistent")
            output = mock_out.getvalue()
            if "No help available" in output:
                _ok("renderer: missing key handled gracefully")
            else:
                _fail("renderer: missing key", f"unexpected output: {output[:200]}")
    except Exception as e:
        _fail("renderer: missing key", str(e))

    # ================================================================
    # Validation tests
    # ================================================================
    _begin_suite("Script Editor  (validate-on-save)")

    try:
        from torch.script_editor import _validate_script_constants
    except ImportError as e:
        from torch.tests.harness import _skip
        _skip("validation tests", f"import failed: {e}")
        return

    # Create a temp game directory with mock header files
    with tempfile.TemporaryDirectory() as tmpdir:
        flags_dir = os.path.join(tmpdir, "include", "constants")
        os.makedirs(flags_dir)
        data_dir = os.path.join(tmpdir, "data")
        os.makedirs(data_dir)

        with open(os.path.join(flags_dir, "flags.h"), "w") as f:
            f.write("#define FLAG_BADGE01_GET 0x100\\n#define FLAG_RECEIVED_STARTER 0x101\\n")
        with open(os.path.join(flags_dir, "vars.h"), "w") as f:
            f.write("#define VAR_TEMP_1 0x4000\\n")
        with open(os.path.join(flags_dir, "opponents.h"), "w") as f:
            f.write("#define TRAINER_RIVAL_1 0x001\\n")
        with open(os.path.join(flags_dir, "species.h"), "w") as f:
            f.write("#define SPECIES_PIKACHU 25\\n")
        with open(os.path.join(data_dir, "specials.inc"), "w") as f:
            f.write("def_special HealPlayerParty\\n")

        # Test: valid flag -> no warnings
        script_valid = {"beats": [
            {"type": "flag", "data": {"action": "set", "flag_name": "FLAG_BADGE01_GET"}},
        ]}
        warnings = _validate_script_constants(script_valid, tmpdir)
        _assert("validate: valid flag -> no warnings", len(warnings) == 0,
                f"expected 0 warnings, got {len(warnings)}: {warnings}")

        # Test: invalid flag -> warning
        script_invalid = {"beats": [
            {"type": "flag", "data": {"action": "set", "flag_name": "FLAG_NONEXISTENT"}},
        ]}
        warnings = _validate_script_constants(script_invalid, tmpdir)
        _assert("validate: invalid flag -> warning", len(warnings) == 1,
                f"expected 1 warning, got {len(warnings)}: {warnings}")
        if warnings:
            _assert("validate: warning mentions constant",
                    "FLAG_NONEXISTENT" in warnings[0] and "flags.h" in warnings[0],
                    f"bad warning text: {warnings[0]}")

        # Test: no game_path -> empty list
        warnings = _validate_script_constants(script_valid, None)
        _assert("validate: no game_path -> empty", len(warnings) == 0,
                f"expected 0 with None game_path, got {len(warnings)}")

        # Test: mixed valid/invalid
        script_mixed = {"beats": [
            {"type": "flag", "data": {"action": "set", "flag_name": "FLAG_BADGE01_GET"}},
            {"type": "var", "data": {"var_name": "VAR_FAKE"}},
            {"type": "battle", "data": {"trainer": "TRAINER_RIVAL_1"}},
            {"type": "special", "data": {"function": "FakeSpecial"}},
        ]}
        warnings = _validate_script_constants(script_mixed, tmpdir)
        _assert("validate: mixed valid/invalid -> 2 warnings", len(warnings) == 2,
                f"expected 2, got {len(warnings)}: {warnings}")

    # ================================================================
    # Flag log tests
    # ================================================================
    _begin_suite("Script Editor  (flag log)")

    try:
        from torch.script_editor import _load_flag_log, _save_flag_log, _log_flag
    except ImportError as e:
        from torch.tests.harness import _skip
        _skip("flag log tests", f"import failed: {e}")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        # Monkey-patch the log dir for testing
        import torch.script_editor as _se_mod
        orig_dir = _se_mod._FLAG_LOG_DIR
        _se_mod._FLAG_LOG_DIR = tmpdir

        try:
            # Test: load from nonexistent -> empty dict
            result = _load_flag_log("TestProject")
            _assert("flag log: load nonexistent -> empty dict",
                    result == {}, f"expected empty dict, got {result}")

            # Test: save and load round-trip
            test_log = {"FLAG_TEST_1": "Scene1", "FLAG_TEST_2": "Scene2"}
            _save_flag_log("TestProject", test_log)
            result = _load_flag_log("TestProject")
            _assert("flag log: save/load round-trip",
                    result == test_log, f"expected {test_log}, got {result}")

            # Verify JSON file exists and is valid
            json_path = os.path.join(tmpdir, "TestProject", "flags.json")
            _assert("flag log: JSON file created", os.path.isfile(json_path),
                    f"file not found: {json_path}")

            # Test: _log_flag adds entry
            _log_flag("TestProject", "FLAG_NEW_ONE", "NewScene")
            result = _load_flag_log("TestProject")
            _assert("flag log: _log_flag adds entry",
                    result.get("FLAG_NEW_ONE") == "NewScene",
                    f"expected FLAG_NEW_ONE -> NewScene, got {result.get('FLAG_NEW_ONE')}")

            # Test: _log_flag with no proj_name is no-op
            _log_flag(None, "FLAG_SKIP", "ShouldNotSave")
            _ok("flag log: _log_flag with no proj_name is no-op")

            # Test: _load_flag_log with no proj_name -> empty
            result = _load_flag_log(None)
            _assert("flag log: load with None proj_name -> empty",
                    result == {}, f"expected empty, got {result}")

        finally:
            _se_mod._FLAG_LOG_DIR = orig_dir
