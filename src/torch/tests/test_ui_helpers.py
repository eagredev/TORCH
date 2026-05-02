"""UI Helpers suite -- pure formatters, file parsers, build diagnostics."""
import os
import io
import sys
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("UI Helpers")

    try:
        from torch.ui import (
            _fmt_class, _fmt_music, _fmt_sprite, _fmt_ai_flags,
            _truncate_dialogue, _fmt_const_name, _k,
            _parse_ability_names, _parse_ability_descriptions,
            _parse_move_names, _diagnose_build_error,
        )
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # ---------------------------------------------------------------
    # _fmt_class
    # ---------------------------------------------------------------
    try:
        _assert("_fmt_class: TRAINER_CLASS_TEAM_ROCKET -> 'Team Rocket'",
                _fmt_class("TRAINER_CLASS_TEAM_ROCKET") == "Team Rocket",
                f"got: {_fmt_class('TRAINER_CLASS_TEAM_ROCKET')!r}")
    except Exception as e:
        _fail("_fmt_class: TRAINER_CLASS_TEAM_ROCKET", str(e))

    try:
        _assert("_fmt_class: empty string -> '?'",
                _fmt_class("") == "?",
                f"got: {_fmt_class('')!r}")
    except Exception as e:
        _fail("_fmt_class: empty string", str(e))

    try:
        _assert("_fmt_class: None -> '?'",
                _fmt_class(None) == "?",
                f"got: {_fmt_class(None)!r}")
    except Exception as e:
        _fail("_fmt_class: None", str(e))

    try:
        _assert("_fmt_class: TRAINER_CLASS_HIKER -> 'Hiker'",
                _fmt_class("TRAINER_CLASS_HIKER") == "Hiker",
                f"got: {_fmt_class('TRAINER_CLASS_HIKER')!r}")
    except Exception as e:
        _fail("_fmt_class: TRAINER_CLASS_HIKER", str(e))

    # ---------------------------------------------------------------
    # _fmt_music
    # ---------------------------------------------------------------
    try:
        _assert("_fmt_music: TRAINER_ENCOUNTER_MUSIC_FEMALE -> 'Female'",
                _fmt_music("TRAINER_ENCOUNTER_MUSIC_FEMALE") == "Female",
                f"got: {_fmt_music('TRAINER_ENCOUNTER_MUSIC_FEMALE')!r}")
    except Exception as e:
        _fail("_fmt_music: TRAINER_ENCOUNTER_MUSIC_FEMALE", str(e))

    try:
        _assert("_fmt_music: empty string -> '?'",
                _fmt_music("") == "?",
                f"got: {_fmt_music('')!r}")
    except Exception as e:
        _fail("_fmt_music: empty string", str(e))

    # ---------------------------------------------------------------
    # _fmt_sprite
    # ---------------------------------------------------------------
    try:
        _assert("_fmt_sprite: TRAINER_PIC_HIKER -> 'Hiker'",
                _fmt_sprite("TRAINER_PIC_HIKER") == "Hiker",
                f"got: {_fmt_sprite('TRAINER_PIC_HIKER')!r}")
    except Exception as e:
        _fail("_fmt_sprite: TRAINER_PIC_HIKER", str(e))

    try:
        _assert("_fmt_sprite: empty string -> '?'",
                _fmt_sprite("") == "?",
                f"got: {_fmt_sprite('')!r}")
    except Exception as e:
        _fail("_fmt_sprite: empty string", str(e))

    try:
        _assert("_fmt_sprite: TRAINER_PIC_COOL_TRAINER_F -> 'Cool Trainer F'",
                _fmt_sprite("TRAINER_PIC_COOL_TRAINER_F") == "Cool Trainer F",
                f"got: {_fmt_sprite('TRAINER_PIC_COOL_TRAINER_F')!r}")
    except Exception as e:
        _fail("_fmt_sprite: TRAINER_PIC_COOL_TRAINER_F", str(e))

    # ---------------------------------------------------------------
    # _fmt_ai_flags
    # ---------------------------------------------------------------
    try:
        result = _fmt_ai_flags("AI_FLAG_CHECK_VIABILITY|AI_FLAG_TRY_TO_FAINT")
        _assert("_fmt_ai_flags: two flags joined",
                result == "Check Viability, Try To Faint",
                f"got: {result!r}")
    except Exception as e:
        _fail("_fmt_ai_flags: two flags", str(e))

    try:
        _assert("_fmt_ai_flags: empty string -> '?'",
                _fmt_ai_flags("") == "?",
                f"got: {_fmt_ai_flags('')!r}")
    except Exception as e:
        _fail("_fmt_ai_flags: empty string", str(e))

    try:
        result = _fmt_ai_flags("AI_FLAG_SMART_SWITCHING")
        _assert("_fmt_ai_flags: single flag",
                result == "Smart Switching",
                f"got: {result!r}")
    except Exception as e:
        _fail("_fmt_ai_flags: single flag", str(e))

    # ---------------------------------------------------------------
    # _truncate_dialogue
    # ---------------------------------------------------------------
    try:
        _assert("_truncate_dialogue: strips \\\\n",
                "\\n" not in _truncate_dialogue("Hello\\nworld"),
                f"got: {_truncate_dialogue('Hello\\nworld')!r}")
    except Exception as e:
        _fail("_truncate_dialogue: strips \\\\n", str(e))

    try:
        _assert("_truncate_dialogue: strips \\\\p",
                "\\p" not in _truncate_dialogue("Hello\\pworld"),
                f"got: {_truncate_dialogue('Hello\\pworld')!r}")
    except Exception as e:
        _fail("_truncate_dialogue: strips \\\\p", str(e))

    try:
        _assert("_truncate_dialogue: strips $",
                "$" not in _truncate_dialogue("Hello world$"),
                f"got: {_truncate_dialogue('Hello world$')!r}")
    except Exception as e:
        _fail("_truncate_dialogue: strips $", str(e))

    try:
        long_text = "A" * 100
        result = _truncate_dialogue(long_text)
        _assert("_truncate_dialogue: truncates long text with '...'",
                result.endswith("...") and len(result) <= 45,
                f"got: {result!r} (len={len(result)})")
    except Exception as e:
        _fail("_truncate_dialogue: truncates long text", str(e))

    try:
        _assert("_truncate_dialogue: None -> '(none)'",
                _truncate_dialogue(None) == "(none)",
                f"got: {_truncate_dialogue(None)!r}")
    except Exception as e:
        _fail("_truncate_dialogue: None", str(e))

    try:
        short = "Short text"
        _assert("_truncate_dialogue: short text unchanged",
                _truncate_dialogue(short) == short,
                f"got: {_truncate_dialogue(short)!r}")
    except Exception as e:
        _fail("_truncate_dialogue: short text", str(e))

    # ---------------------------------------------------------------
    # _fmt_const_name
    # ---------------------------------------------------------------
    try:
        lookup = {"ABILITY_BLAZE": "Blaze"}
        _assert("_fmt_const_name: lookup hit",
                _fmt_const_name("ABILITY_BLAZE", lookup) == "Blaze",
                f"got: {_fmt_const_name('ABILITY_BLAZE', lookup)!r}")
    except Exception as e:
        _fail("_fmt_const_name: lookup hit", str(e))

    try:
        lookup = {}
        result = _fmt_const_name("ABILITY_THICK_FAT", lookup)
        _assert("_fmt_const_name: lookup miss with prefix strip",
                result == "Thick Fat",
                f"got: {result!r}")
    except Exception as e:
        _fail("_fmt_const_name: lookup miss with prefix strip", str(e))

    try:
        lookup = {}
        result = _fmt_const_name("SOME_UNKNOWN_CONST", lookup)
        _assert("_fmt_const_name: no matching prefix returns raw",
                result == "SOME_UNKNOWN_CONST",
                f"got: {result!r}")
    except Exception as e:
        _fail("_fmt_const_name: no matching prefix", str(e))

    try:
        _assert("_fmt_const_name: empty/None -> '?'",
                _fmt_const_name("", {}) == "?" and _fmt_const_name(None, {}) == "?",
                "did not return '?'")
    except Exception as e:
        _fail("_fmt_const_name: empty/None", str(e))

    # ---------------------------------------------------------------
    # _k
    # ---------------------------------------------------------------
    try:
        result = _k("q")
        _assert("_k: '[q]' present in output",
                "[q]" in result,
                f"got: {result!r}")
    except Exception as e:
        _fail("_k: '[q]' present", str(e))

    try:
        result = _k("Enter")
        _assert("_k: '[Enter]' present in output",
                "[Enter]" in result,
                f"got: {result!r}")
    except Exception as e:
        _fail("_k: '[Enter]' present", str(e))

    # ---------------------------------------------------------------
    # _parse_ability_names (tempdir)
    # ---------------------------------------------------------------
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="torch_ui_test_")
        abilities_dir = os.path.join(tmp_dir, "src", "data", "text")
        os.makedirs(abilities_dir)
        abilities_h = os.path.join(abilities_dir, "abilities.h")
        with open(abilities_h, "w") as f:
            f.write('    [ABILITY_BLAZE] = _("Blaze"),\n')
            f.write('    [ABILITY_OVERGROW] = _("Overgrow"),\n')
        result = _parse_ability_names(tmp_dir)
        _assert("_parse_ability_names: parses ability names",
                result.get("ABILITY_BLAZE") == "Blaze" and result.get("ABILITY_OVERGROW") == "Overgrow",
                f"got: {result!r}")
    except Exception as e:
        _fail("_parse_ability_names: parses ability names", str(e))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        result = _parse_ability_names("/tmp/torch_nonexistent_path_xyz")
        _assert("_parse_ability_names: missing file -> empty dict",
                result == {},
                f"got: {result!r}")
    except Exception as e:
        _fail("_parse_ability_names: missing file", str(e))

    # ---------------------------------------------------------------
    # _parse_ability_descriptions (tempdir)
    # ---------------------------------------------------------------
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="torch_ui_test_")
        abilities_dir = os.path.join(tmp_dir, "src", "data", "text")
        os.makedirs(abilities_dir)
        abilities_h = os.path.join(abilities_dir, "abilities.h")
        with open(abilities_h, "w") as f:
            f.write('static const u8 sBlazeDescription[] = _("Powers up Fire-type moves.");\n')
            f.write('    [ABILITY_BLAZE] = sBlazeDescription,\n')
        result = _parse_ability_descriptions(tmp_dir)
        _assert("_parse_ability_descriptions: parses descriptions",
                result.get("ABILITY_BLAZE") == "Powers up Fire-type moves.",
                f"got: {result!r}")
    except Exception as e:
        _fail("_parse_ability_descriptions: parses descriptions", str(e))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        result = _parse_ability_descriptions("/tmp/torch_nonexistent_path_xyz")
        _assert("_parse_ability_descriptions: missing file -> empty dict",
                result == {},
                f"got: {result!r}")
    except Exception as e:
        _fail("_parse_ability_descriptions: missing file", str(e))

    # ---------------------------------------------------------------
    # _parse_move_names (tempdir)
    # ---------------------------------------------------------------
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="torch_ui_test_")
        moves_dir = os.path.join(tmp_dir, "src", "data", "text")
        os.makedirs(moves_dir)
        moves_h = os.path.join(moves_dir, "move_names.h")
        with open(moves_h, "w") as f:
            f.write('    [MOVE_POUND] = _("Pound"),\n')
            f.write('    [MOVE_KARATE_CHOP] = _("Karate Chop"),\n')
        result = _parse_move_names(tmp_dir)
        _assert("_parse_move_names: parses move names",
                result.get("MOVE_POUND") == "Pound" and result.get("MOVE_KARATE_CHOP") == "Karate Chop",
                f"got: {result!r}")
    except Exception as e:
        _fail("_parse_move_names: parses move names", str(e))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        result = _parse_move_names("/tmp/torch_nonexistent_path_xyz")
        _assert("_parse_move_names: missing file -> empty dict",
                result == {},
                f"got: {result!r}")
    except Exception as e:
        _fail("_parse_move_names: missing file", str(e))

    # ---------------------------------------------------------------
    # _diagnose_build_error
    # ---------------------------------------------------------------

    # Capture stdout for diagnostics (they print)
    def _capture_diagnose(stderr_text):
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            result = _diagnose_build_error(stderr_text)
        finally:
            sys.stdout = old_stdout
        return result

    try:
        result = _capture_diagnose("fatal error: stddef.h: No such file or directory")
        _assert("_diagnose_build_error: GCC header missing",
                result is not None and "GCC" in result,
                f"got: {result!r}")
    except Exception as e:
        _fail("_diagnose_build_error: GCC header", str(e))

    try:
        result = _capture_diagnose("error: region 'rom' overflowed by 12345 bytes")
        _assert("_diagnose_build_error: ROM overflow",
                result is not None and "ROM" in result,
                f"got: {result!r}")
    except Exception as e:
        _fail("_diagnose_build_error: ROM overflow", str(e))

    try:
        result = _capture_diagnose("No rule to make target 'data/maps/MyMap/scripts.inc'")
        _assert("_diagnose_build_error: missing file",
                result is not None and isinstance(result, str),
                f"got: {result!r}")
    except Exception as e:
        _fail("_diagnose_build_error: missing file", str(e))

    try:
        result = _capture_diagnose("data/maps/Test/scripts.pory: 5 error: unexpected token")
        _assert("_diagnose_build_error: poryscript error",
                result is not None and isinstance(result, str),
                f"got: {result!r}")
    except Exception as e:
        _fail("_diagnose_build_error: poryscript error", str(e))

    try:
        result = _capture_diagnose("error: 'FLAG_MY_CUSTOM' undeclared (first use)")
        _assert("_diagnose_build_error: undeclared constant",
                result is not None and isinstance(result, str),
                f"got: {result!r}")
    except Exception as e:
        _fail("_diagnose_build_error: undeclared constant", str(e))

    try:
        result = _capture_diagnose("error: expected ';' before 'u8'")
        _assert("_diagnose_build_error: syntax error",
                result is not None and isinstance(result, str),
                f"got: {result!r}")
    except Exception as e:
        _fail("_diagnose_build_error: syntax error", str(e))

    try:
        stderr = "data/maps/Test/scripts.inc:5: Error: symbol `TestScript' is already defined"
        result = _capture_diagnose(stderr)
        _assert("_diagnose_build_error: duplicate symbol",
                result == "duplicate_symbols",
                f"got: {result!r}")
    except Exception as e:
        _fail("_diagnose_build_error: duplicate symbol", str(e))

    try:
        stderr = ("in function `PlayerHome_ObjectEvents':\n"
                  "undefined reference to `PlayerHome_EventScript_NPC1'")
        result = _capture_diagnose(stderr)
        _assert("_diagnose_build_error: undefined reference",
                result == "undefined_script_references",
                f"got: {result!r}")
    except Exception as e:
        _fail("_diagnose_build_error: undefined reference", str(e))

    try:
        result = _capture_diagnose("everything is fine, no errors here")
        _assert("_diagnose_build_error: no match -> None",
                result is None,
                f"got: {result!r}")
    except Exception as e:
        _fail("_diagnose_build_error: no match", str(e))
