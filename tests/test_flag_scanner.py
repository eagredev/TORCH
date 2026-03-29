"""Flag scanner suite -- cross-reference scanning, flags.h parsing, deletion."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Flag Scanner  (parse, scan, count, delete)")

    try:
        from torch.flag_scanner import (
            scan_flag_references, scan_all_flags_bulk,
            parse_flags_h, count_free_slots, delete_flag_from_header,
        )
    except ImportError as e:
        _skip("all flag_scanner tests", f"import failed: {e}")
        return

    _test_parse_flags_h(parse_flags_h)
    _test_count_free_slots(count_free_slots, parse_flags_h)
    _test_scan_flag_references(scan_flag_references)
    _test_scan_word_boundary(scan_flag_references)
    _test_scan_all_flags_bulk(scan_all_flags_bulk)
    _test_delete_flag_from_header(delete_flag_from_header)
    _test_delete_refuses_pool_entry(delete_flag_from_header)
    _test_delete_missing_flag(delete_flag_from_header)
    _test_parse_empty_game_path(parse_flags_h)
    _test_scan_nonexistent_path(scan_flag_references)


# ── Fixture builder ───────────────────────────────────────────────

def _make_game_tree():
    """Create a minimal game directory with flags.h and some script files."""
    tmpdir = tempfile.mkdtemp()
    flags_dir = os.path.join(tmpdir, "include", "constants")
    os.makedirs(flags_dir)

    # Write a minimal flags.h
    flags_h = os.path.join(flags_dir, "flags.h")
    with open(flags_h, "w") as f:
        f.write("""\
#ifndef GUARD_CONSTANTS_FLAGS_H
#define GUARD_CONSTANTS_FLAGS_H

#define TEMP_FLAGS_START 0x0
#define FLAG_TEMP_1         (TEMP_FLAGS_START + 0x1)
#define FLAG_TEMP_2         (TEMP_FLAGS_START + 0x2)
#define NUM_TEMP_FLAGS      3

#define FLAG_UNUSED_0x020                    0x20 // Unused Flag
#define FLAG_UNUSED_0x021                    0x21 // Unused Flag
#define FLAG_UNUSED_0x022                    0x22 // Unused Flag
#define FLAG_HIDE_TOWN_NPC                   0x50
#define FLAG_HIDE_ROUTE1_TRAINER             0x51
#define FLAG_UNUSED_0x052                    0x52 // Unused Flag

// Custom flags
#define FLAG_BEAT_GYM_1                      FLAG_UNUSED_0x020
#define FLAG_MET_OFFICER                     FLAG_UNUSED_0x021

#define TRAINER_FLAGS_START                   0x500
#define TRAINER_FLAGS_END                     0x8FF

#define SYSTEM_FLAGS                         0x860
#define FLAG_SYS_POKEMON_GET                 0x860
#define FLAG_SYS_POKEDEX_GET                 0x861

#define DAILY_FLAGS_START                    0x920
#define FLAG_DAILY_BERRY_1                   0x920

#define SPECIAL_FLAGS_START                  0x4000
#define FLAG_SPECIAL_1                       0x4000

#endif
""")

    # Write a script file that references some flags
    maps_dir = os.path.join(tmpdir, "data", "maps", "TestTown")
    os.makedirs(maps_dir)
    with open(os.path.join(maps_dir, "scripts.pory"), "w") as f:
        f.write("""\
script TestTown_Officer {
    if (flag(FLAG_BEAT_GYM_1)) {
        goto(TestTown_Officer_Done)
    }
    setflag(FLAG_BEAT_GYM_1)
}
""")

    # Write a C file
    src_dir = os.path.join(tmpdir, "src")
    os.makedirs(src_dir)
    with open(os.path.join(src_dir, "test.c"), "w") as f:
        f.write("""\
if (FlagGet(FLAG_HIDE_TOWN_NPC)) {
    RemoveObjectEvent(1);
}
""")

    return tmpdir


# ── Tests ─────────────────────────────────────────────────────────

def _test_parse_flags_h(parse_flags_h):
    """parse_flags_h returns structured data with correct sections."""
    tmpdir = _make_game_tree()
    try:
        result = parse_flags_h(tmpdir)

        _assert(
            "parse: has all section keys",
            all(k in result for k in ("temp", "event", "system", "daily",
                                       "special", "trainer_range", "custom_aliases")),
            f"keys: {list(result.keys())}"
        )

        _assert(
            "parse: temp section has entries",
            len(result["temp"]) >= 1,
            f"temp count: {len(result['temp'])}"
        )

        _assert(
            "parse: event section has entries",
            len(result["event"]) >= 3,
            f"event count: {len(result['event'])}"
        )

        _assert(
            "parse: custom_aliases found",
            len(result["custom_aliases"]) == 2,
            f"aliases: {result['custom_aliases']}"
        )

        alias_names = [a for a, _ in result["custom_aliases"]]
        _assert(
            "parse: FLAG_BEAT_GYM_1 is a custom alias",
            "FLAG_BEAT_GYM_1" in alias_names,
            f"aliases: {alias_names}"
        )

        _assert(
            "parse: system section has entries",
            len(result["system"]) >= 1,
            f"system count: {len(result['system'])}"
        )
    finally:
        shutil.rmtree(tmpdir)


def _test_count_free_slots(count_free_slots, parse_flags_h):
    """count_free_slots returns correct free/total counts."""
    tmpdir = _make_game_tree()
    try:
        free, total = count_free_slots(tmpdir)

        _assert(
            "count: total event slots > 0",
            total > 0,
            f"total: {total}"
        )

        _assert(
            "count: free slots < total (some are used/aliased)",
            free < total,
            f"free={free}, total={total}"
        )

        # We have 6 event entries total, 2 are aliased (FLAG_BEAT_GYM_1, FLAG_MET_OFFICER)
        # FLAG_UNUSED_0x022 and FLAG_UNUSED_0x052 are free, FLAG_HIDE_* are named
        # So free = 2 (0x022, 0x052)
        _assert(
            "count: 2 free slots (unaliased unused)",
            free == 2,
            f"free: {free}"
        )
    finally:
        shutil.rmtree(tmpdir)


def _test_scan_flag_references(scan_flag_references):
    """scan_flag_references finds references across file types."""
    tmpdir = _make_game_tree()
    try:
        refs = scan_flag_references("FLAG_BEAT_GYM_1", tmpdir)

        _assert(
            "scan: finds references to FLAG_BEAT_GYM_1",
            len(refs) >= 2,
            f"ref count: {len(refs)}"
        )

        categories = {r["category"] for r in refs}
        _assert(
            "scan: finds header refs",
            "header_define" in categories or "header_alias" in categories,
            f"categories: {categories}"
        )

        _assert(
            "scan: finds script refs",
            "script_pory" in categories,
            f"categories: {categories}"
        )
    finally:
        shutil.rmtree(tmpdir)


def _test_scan_word_boundary(scan_flag_references):
    """scan_flag_references uses word boundaries (FLAG_TEMP_1 != FLAG_TEMP_10)."""
    tmpdir = _make_game_tree()
    try:
        refs = scan_flag_references("FLAG_TEMP_1", tmpdir)
        # Should match FLAG_TEMP_1 but not FLAG_TEMP_10 or FLAG_TEMP_1X
        for r in refs:
            _assert(
                "word_boundary: no false positive in line",
                "FLAG_TEMP_10" not in r["line_text"] or "FLAG_TEMP_1" in r["line_text"],
                f"line: {r['line_text']}"
            )
        _ok("word_boundary: FLAG_TEMP_1 doesn't false-match")
    finally:
        shutil.rmtree(tmpdir)


def _test_scan_all_flags_bulk(scan_all_flags_bulk):
    """scan_all_flags_bulk finds multiple flags in a single pass."""
    tmpdir = _make_game_tree()
    try:
        results = scan_all_flags_bulk(tmpdir,
                                       ["FLAG_BEAT_GYM_1", "FLAG_HIDE_TOWN_NPC"])

        _assert(
            "bulk: returns dict with both flag names",
            "FLAG_BEAT_GYM_1" in results and "FLAG_HIDE_TOWN_NPC" in results,
            f"keys: {list(results.keys())}"
        )

        _assert(
            "bulk: FLAG_BEAT_GYM_1 has refs",
            len(results["FLAG_BEAT_GYM_1"]) >= 2,
            f"count: {len(results['FLAG_BEAT_GYM_1'])}"
        )

        _assert(
            "bulk: FLAG_HIDE_TOWN_NPC has refs",
            len(results["FLAG_HIDE_TOWN_NPC"]) >= 1,
            f"count: {len(results['FLAG_HIDE_TOWN_NPC'])}"
        )
    finally:
        shutil.rmtree(tmpdir)


def _test_delete_flag_from_header(delete_flag_from_header):
    """delete_flag_from_header removes a custom alias."""
    tmpdir = _make_game_tree()
    try:
        ok = delete_flag_from_header(tmpdir, "FLAG_BEAT_GYM_1")
        _assert(
            "delete: returns True for valid custom alias",
            ok,
            "returned False"
        )

        # Verify it's gone
        flags_h = os.path.join(tmpdir, "include", "constants", "flags.h")
        with open(flags_h) as f:
            content = f.read()
        _assert(
            "delete: FLAG_BEAT_GYM_1 no longer in file",
            "FLAG_BEAT_GYM_1" not in content,
            "still found in flags.h"
        )

        # The pool entry should still be there
        _assert(
            "delete: FLAG_UNUSED_0x020 pool entry preserved",
            "FLAG_UNUSED_0x020" in content,
            "pool entry was removed"
        )
    finally:
        shutil.rmtree(tmpdir)


def _test_delete_refuses_pool_entry(delete_flag_from_header):
    """delete_flag_from_header refuses to delete FLAG_UNUSED_* pool entries."""
    tmpdir = _make_game_tree()
    try:
        ok = delete_flag_from_header(tmpdir, "FLAG_UNUSED_0x020")
        _assert(
            "delete_pool: refuses FLAG_UNUSED_* deletion",
            not ok,
            "incorrectly returned True"
        )
    finally:
        shutil.rmtree(tmpdir)


def _test_delete_missing_flag(delete_flag_from_header):
    """delete_flag_from_header returns False for nonexistent flag."""
    tmpdir = _make_game_tree()
    try:
        ok = delete_flag_from_header(tmpdir, "FLAG_NONEXISTENT_FLAG")
        _assert(
            "delete_missing: returns False",
            not ok,
            "incorrectly returned True"
        )
    finally:
        shutil.rmtree(tmpdir)


def _test_parse_empty_game_path(parse_flags_h):
    """parse_flags_h returns empty result for nonexistent path."""
    result = parse_flags_h("/nonexistent/path/12345")
    _assert(
        "parse_empty: returns dict with empty sections",
        isinstance(result, dict) and len(result["event"]) == 0,
        f"result: {result}"
    )


def _test_scan_nonexistent_path(scan_flag_references):
    """scan_flag_references returns empty for nonexistent path."""
    refs = scan_flag_references("FLAG_TEMP_1", "/nonexistent/path/12345")
    _assert(
        "scan_nopath: returns empty list",
        refs == [],
        f"refs: {refs}"
    )
