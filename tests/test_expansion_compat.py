"""Expansion Compatibility suite -- version detection, comparison, and feature checks."""
import os
import tempfile
from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def _make_expansion_h(tmpdir, major, minor, patch=None):
    """Create a mock expansion.h inside tmpdir with given version defines."""
    hdir = os.path.join(tmpdir, "include", "constants")
    os.makedirs(hdir, exist_ok=True)
    lines = [f"#define EXPANSION_VERSION_MAJOR {major}\n",
             f"#define EXPANSION_VERSION_MINOR {minor}\n"]
    if patch is not None:
        lines.append(f"#define EXPANSION_VERSION_PATCH {patch}\n")
    with open(os.path.join(hdir, "expansion.h"), "w") as f:
        f.writelines(lines)


def _test_detection(detect_expansion_version):
    """Version detection tests (mocked filesystem)."""
    try:
        with tempfile.TemporaryDirectory() as td:
            _make_expansion_h(td, 1, 14, 3)
            result = detect_expansion_version(td)
            _assert("detect: valid version", result == (1, 14, 3), f"got: {result!r}")
    except Exception as e:
        _fail("detect: valid version", str(e))

    try:
        result = detect_expansion_version("/tmp/torch_test_nonexistent_path_xyzzy")
        _assert("detect: missing file", result is None, f"got: {result!r}")
    except Exception as e:
        _fail("detect: missing file", str(e))

    try:
        with tempfile.TemporaryDirectory() as td:
            hdir = os.path.join(td, "include", "constants")
            os.makedirs(hdir)
            with open(os.path.join(hdir, "expansion.h"), "w") as f:
                f.write("// just a comment, no defines\n")
            result = detect_expansion_version(td)
            _assert("detect: malformed", result is None, f"got: {result!r}")
    except Exception as e:
        _fail("detect: malformed", str(e))

    try:
        with tempfile.TemporaryDirectory() as td:
            _make_expansion_h(td, 1, 9)  # no patch
            result = detect_expansion_version(td)
            _assert("detect: partial (no patch)", result is None, f"got: {result!r}")
    except Exception as e:
        _fail("detect: partial (no patch)", str(e))


def _test_comparison(requires_version):
    """Version comparison tests."""
    try:
        _assert("requires: meets", requires_version((1, 14, 3), (1, 9, 0)) is True)
    except Exception as e:
        _fail("requires: meets", str(e))
    try:
        _assert("requires: exact", requires_version((1, 9, 0), (1, 9, 0)) is True)
    except Exception as e:
        _fail("requires: exact", str(e))
    try:
        _assert("requires: below", requires_version((1, 7, 4), (1, 9, 0)) is False)
    except Exception as e:
        _fail("requires: below", str(e))
    try:
        _assert("requires: None", requires_version(None, (1, 9, 0)) is False)
    except Exception as e:
        _fail("requires: None", str(e))
    try:
        _assert("requires: major higher", requires_version((2, 0, 0), (1, 14, 0)) is True)
    except Exception as e:
        _fail("requires: major higher", str(e))
    try:
        _assert("requires: minor higher", requires_version((1, 14, 0), (1, 13, 5)) is True)
    except Exception as e:
        _fail("requires: minor higher", str(e))
    try:
        _assert("requires: patch below", requires_version((1, 14, 2), (1, 14, 3)) is False)
    except Exception as e:
        _fail("requires: patch below", str(e))


def _test_strings(version_str, parse_version_str):
    """String conversion tests."""
    try:
        _assert("version_str: tuple", version_str((1, 14, 3)) == "1.14.3")
    except Exception as e:
        _fail("version_str: tuple", str(e))
    try:
        _assert("version_str: zero version", version_str((0, 0, 0)) == "0.0.0")
    except Exception as e:
        _fail("version_str: zero version", str(e))
    try:
        _assert("parse_version_str: valid", parse_version_str("1.14.3") == (1, 14, 3))
    except Exception as e:
        _fail("parse_version_str: valid", str(e))
    try:
        _assert("parse_version_str: invalid", parse_version_str("not.a.version") is None)
    except Exception as e:
        _fail("parse_version_str: invalid", str(e))
    try:
        _assert("parse_version_str: empty", parse_version_str("") is None)
    except Exception as e:
        _fail("parse_version_str: empty", str(e))
    try:
        _assert("parse_version_str: two parts", parse_version_str("1.14") is None)
    except Exception as e:
        _fail("parse_version_str: two parts", str(e))


def _test_features(check_feature):
    """Feature check tests."""
    try:
        with tempfile.TemporaryDirectory() as td:
            _make_expansion_h(td, 1, 14, 3)
            result = check_feature(td, (1, 9, 0))
            _assert("check_feature: available", result is True)
    except Exception as e:
        _fail("check_feature: available", str(e))

    try:
        with tempfile.TemporaryDirectory() as td:
            _make_expansion_h(td, 1, 7, 0)
            result = check_feature(td, (1, 9, 0))
            _assert("check_feature: unavailable", result is False)
    except Exception as e:
        _fail("check_feature: unavailable", str(e))

    try:
        result = check_feature("/tmp/torch_test_nonexistent_path_xyzzy", (1, 9, 0))
        _assert("check_feature: unknown version", result is False)
    except Exception as e:
        _fail("check_feature: unknown version", str(e))


def _test_v115_constants():
    """Verify v1.15.0 feature gate constants exist and have correct thresholds."""
    from torch.expansion_compat import (
        TRAINER_BALL_ENUM, TRAINER_PIC_ENUM, TEACHABLE_LEARNSET_JSON,
        STARTING_STATUS_SYSTEM, INGAME_TRADE_MACRO, MOVE_TUTOR_MACRO,
        FRLG_BUILD, requires_version,
    )
    v115 = (1, 15, 0)
    try:
        _assert("v1.15 const: TRAINER_BALL_ENUM", TRAINER_BALL_ENUM == v115)
        _assert("v1.15 const: TRAINER_PIC_ENUM", TRAINER_PIC_ENUM == v115)
        _assert("v1.15 const: TEACHABLE_LEARNSET_JSON", TEACHABLE_LEARNSET_JSON == v115)
        _assert("v1.15 const: STARTING_STATUS_SYSTEM", STARTING_STATUS_SYSTEM == v115)
        _assert("v1.15 const: INGAME_TRADE_MACRO", INGAME_TRADE_MACRO == v115)
        _assert("v1.15 const: MOVE_TUTOR_MACRO", MOVE_TUTOR_MACRO == v115)
        _assert("v1.15 const: FRLG_BUILD", FRLG_BUILD == v115)
    except Exception as e:
        _fail("v1.15 constants", str(e))

    # v1.14.3 should NOT meet v1.15 features
    try:
        _assert("v1.15 gate: 1.14.3 below", requires_version((1, 14, 3), v115) is False)
        _assert("v1.15 gate: 1.15.0 meets", requires_version((1, 15, 0), v115) is True)
        _assert("v1.15 gate: 1.15.1 above", requires_version((1, 15, 1), v115) is True)
    except Exception as e:
        _fail("v1.15 version gating", str(e))


def _test_ball_name_conversion():
    """Verify ball name conversion handles both Item and Pokeball enum formats."""
    from torch.names import _const_to_ball_name, _human_name_to_const
    # Pre-1.15: Item enum format
    try:
        _assert("ball name: ITEM_ to human",
                _const_to_ball_name("ITEM_ULTRA_BALL") == "Ultra Ball")
        _assert("ball name: ITEM_ roundtrip",
                _human_name_to_const("Ultra Ball", "ITEM_") == "ITEM_ULTRA_BALL")
    except Exception as e:
        _fail("ball name: Item enum", str(e))

    # v1.15+: Pokeball enum format
    try:
        _assert("ball name: BALL_ to human",
                _const_to_ball_name("BALL_ULTRA", use_pokeball_enum=True) == "Ultra")
        _assert("ball name: BALL_ roundtrip",
                _human_name_to_const("Ultra", "BALL_") == "BALL_ULTRA")
    except Exception as e:
        _fail("ball name: Pokeball enum", str(e))

    # Auto-detect in parser (Ball: line parsing)
    try:
        # "Ultra Ball" -> old format (ends with " Ball")
        _assert("ball parse: old format",
                _human_name_to_const("Ultra Ball", "ITEM_") == "ITEM_ULTRA_BALL")
        # "Ultra" -> new format
        _assert("ball parse: new format",
                _human_name_to_const("Ultra", "BALL_") == "BALL_ULTRA")
    except Exception as e:
        _fail("ball name: auto-detect", str(e))


def run_suite():
    _begin_suite("Expansion Compat")

    try:
        from torch.expansion_compat import (
            detect_expansion_version, requires_version,
            version_str, parse_version_str, check_feature,
        )
    except ImportError as e:
        _skip("all expansion compat tests", f"import failed: {e}")
        return

    _test_detection(detect_expansion_version)
    _test_comparison(requires_version)
    _test_strings(version_str, parse_version_str)
    _test_features(check_feature)
    _test_v115_constants()
    _test_ball_name_conversion()
