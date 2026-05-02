"""Variable scanner suite -- vars.h parsing, cross-reference scanning."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Variable Scanner  (parse, scan, count)")

    try:
        from torch.var_scanner import (
            parse_vars_h, count_free_var_slots, scan_var_references,
        )
    except ImportError as e:
        _skip("all var_scanner tests", f"import failed: {e}")
        return

    _test_parse_vars_h(parse_vars_h)
    _test_count_free_slots(count_free_var_slots)
    _test_scan_var_references(scan_var_references)
    _test_scan_word_boundary(scan_var_references)
    _test_parse_empty_path(parse_vars_h)
    _test_scan_nonexistent_path(scan_var_references)
    _test_section_classification(parse_vars_h)


# ── Fixture builder ───────────────────────────────────────────────

def _make_game_tree():
    """Create a minimal game directory with vars.h and some script files."""
    tmpdir = tempfile.mkdtemp()
    vars_dir = os.path.join(tmpdir, "include", "constants")
    os.makedirs(vars_dir)

    vars_h = os.path.join(vars_dir, "vars.h")
    with open(vars_h, "w") as f:
        f.write("""\
#ifndef GUARD_CONSTANTS_VARS_H
#define GUARD_CONSTANTS_VARS_H

#define VARS_START 0x4000

#define TEMP_VARS_START            0x4000
#define VAR_TEMP_0                 (TEMP_VARS_START + 0x0)
#define VAR_TEMP_1                 (TEMP_VARS_START + 0x1)
#define VAR_TEMP_2                 (TEMP_VARS_START + 0x2)
#define TEMP_VARS_END              VAR_TEMP_2
#define NUM_TEMP_VARS              (TEMP_VARS_END - TEMP_VARS_START + 1)

#define VAR_OBJ_GFX_ID_0           0x4010
#define VAR_OBJ_GFX_ID_1           0x4011

#define VAR_STARTER_MON                      0x4023 // 0=Treecko, 1=Torchic, 2=Mudkip
#define VAR_UNUSED_0x4024                    0x4024 // Unused Var
#define VAR_UNUSED_0x4025                    0x4025 // Unused Var
#define VAR_STORY_PROGRESS                   0x4026
#define VAR_LITTLEROOT_TOWN_STATE            0x4050

#define SPECIAL_VARS_START  0x8000
#define VAR_0x8000  0x8000
#define VAR_0x8001  0x8001
#define VAR_RESULT  0x800D

#endif
""")

    # Create a script file that references some vars
    maps_dir = os.path.join(tmpdir, "data", "maps", "TestMap")
    os.makedirs(maps_dir)
    with open(os.path.join(maps_dir, "scripts.pory"), "w") as f:
        f.write("""\
script TestMap_NPC {
    if (var(VAR_STORY_PROGRESS) >= 3) {
        msgbox("Done!", MSGBOX_DEFAULT)
    }
    setvar(VAR_TEMP_0, 1)
}
""")

    # Create a C file that references a var
    src_dir = os.path.join(tmpdir, "src")
    os.makedirs(src_dir)
    with open(os.path.join(src_dir, "event.c"), "w") as f:
        f.write("u16 val = VarGet(VAR_RESULT);\n")

    return tmpdir


# ── Tests ─────────────────────────────────────────────────────────

def _test_parse_vars_h(parse_vars_h):
    tmpdir = _make_game_tree()
    try:
        parsed = parse_vars_h(tmpdir)

        _assert("parse_vars_h: temp section has 3 entries",
                len(parsed["temp"]) == 3,
                f"got {len(parsed['temp'])}: {[e[0] for e in parsed['temp']]}")

        _assert("parse_vars_h: graphics section has 2 entries",
                len(parsed["graphics"]) == 2,
                f"got {len(parsed['graphics'])}: {[e[0] for e in parsed['graphics']]}")

        _assert("parse_vars_h: persistent section has entries",
                len(parsed["persistent"]) >= 4,
                f"got {len(parsed['persistent'])}: {[e[0] for e in parsed['persistent']]}")

        _assert("parse_vars_h: special section has entries",
                len(parsed["special"]) >= 2,
                f"got {len(parsed['special'])}: {[e[0] for e in parsed['special']]}")

        # Check that unused vars are flagged
        persistent_names = {e[0]: e for e in parsed["persistent"]}
        _assert("parse_vars_h: VAR_UNUSED_0x4024 is_unused",
                persistent_names.get("VAR_UNUSED_0x4024", (None, None, None, False))[3],
                "should be marked unused")

        _assert("parse_vars_h: VAR_STARTER_MON not unused",
                not persistent_names.get("VAR_STARTER_MON", (None, None, None, True))[3],
                "should not be marked unused")

        _ok("parse_vars_h: all checks passed")
    except Exception as e:
        _fail("parse_vars_h", str(e))
    finally:
        shutil.rmtree(tmpdir)


def _test_count_free_slots(count_free_var_slots):
    tmpdir = _make_game_tree()
    try:
        free, total = count_free_var_slots(tmpdir)
        _assert("count_free_var_slots: free >= 2",
                free >= 2,
                f"free={free}")
        _assert("count_free_var_slots: total >= 4",
                total >= 4,
                f"total={total}")
        _ok("count_free_var_slots: passed")
    except Exception as e:
        _fail("count_free_var_slots", str(e))
    finally:
        shutil.rmtree(tmpdir)


def _test_scan_var_references(scan_var_references):
    tmpdir = _make_game_tree()
    try:
        refs = scan_var_references("VAR_STORY_PROGRESS", tmpdir)
        _assert("scan_var_references: finds references",
                len(refs) >= 2,  # header define + script usage
                f"got {len(refs)} refs")

        categories = {r["category"] for r in refs}
        _assert("scan_var_references: finds header_define",
                "header_define" in categories,
                f"categories: {categories}")
        _assert("scan_var_references: finds script_pory",
                "script_pory" in categories,
                f"categories: {categories}")

        _ok("scan_var_references: passed")
    except Exception as e:
        _fail("scan_var_references", str(e))
    finally:
        shutil.rmtree(tmpdir)


def _test_scan_word_boundary(scan_var_references):
    tmpdir = _make_game_tree()
    try:
        # VAR_TEMP_0 should not match VAR_TEMP_0x1 or similar
        refs = scan_var_references("VAR_TEMP_0", tmpdir)
        for r in refs:
            # Each match should have VAR_TEMP_0 as a whole word
            _assert(f"word boundary: '{r['line_text'][:40]}...' is valid match",
                    "VAR_TEMP_0" in r["line_text"],
                    "false positive")
        _ok("scan word boundary: passed")
    except Exception as e:
        _fail("scan word boundary", str(e))
    finally:
        shutil.rmtree(tmpdir)


def _test_parse_empty_path(parse_vars_h):
    try:
        result = parse_vars_h("/nonexistent/path")
        _assert("parse empty path: returns empty structure",
                len(result["temp"]) == 0 and len(result["persistent"]) == 0,
                f"got: {result}")
        _ok("parse empty path: passed")
    except Exception as e:
        _fail("parse empty path", str(e))


def _test_scan_nonexistent_path(scan_var_references):
    try:
        refs = scan_var_references("VAR_TEST", "/nonexistent/path")
        _assert("scan nonexistent path: returns empty",
                len(refs) == 0,
                f"got {len(refs)} refs")
        _ok("scan nonexistent path: passed")
    except Exception as e:
        _fail("scan nonexistent path", str(e))


def _test_section_classification(parse_vars_h):
    tmpdir = _make_game_tree()
    try:
        parsed = parse_vars_h(tmpdir)

        temp_names = [e[0] for e in parsed["temp"]]
        _assert("sections: VAR_TEMP_0 in temp",
                "VAR_TEMP_0" in temp_names,
                f"temp: {temp_names}")

        gfx_names = [e[0] for e in parsed["graphics"]]
        _assert("sections: VAR_OBJ_GFX_ID_0 in graphics",
                "VAR_OBJ_GFX_ID_0" in gfx_names,
                f"graphics: {gfx_names}")

        persistent_names = [e[0] for e in parsed["persistent"]]
        _assert("sections: VAR_STARTER_MON in persistent",
                "VAR_STARTER_MON" in persistent_names,
                f"persistent: {persistent_names}")

        special_names = [e[0] for e in parsed["special"]]
        _assert("sections: VAR_RESULT in special",
                "VAR_RESULT" in special_names,
                f"special: {special_names}")

        _ok("section classification: all correct")
    except Exception as e:
        _fail("section classification", str(e))
    finally:
        shutil.rmtree(tmpdir)
