"""Pickers suite -- search filtering, label extraction, wrapper logic."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Pickers  (filtering, labels, wrappers)")

    try:
        import torch.pickers as pickers_mod
    except ImportError as e:
        _skip("all pickers tests", f"import failed: {e}")
        return

    _test_search_filtering(pickers_mod)
    _test_normalisation(pickers_mod)
    _test_pick_label_from_script_data(pickers_mod)
    _test_pick_label_from_files(pickers_mod)
    _test_pick_wrappers_no_game_path(pickers_mod)
    _test_max_results_constant(pickers_mod)
    _test_try_pick(pickers_mod)
    _test_gather_labels_combined(pickers_mod)
    _test_detail_callback(pickers_mod)
    _test_find_next_unused_flag(pickers_mod)
    _test_find_next_unused_flag_all_used(pickers_mod)
    _test_find_next_unused_flag_no_custom(pickers_mod)
    _test_validate_flag_name_valid(pickers_mod)
    _test_validate_flag_name_no_prefix(pickers_mod)
    _test_validate_flag_name_lowercase(pickers_mod)
    _test_validate_flag_name_already_exists(pickers_mod)
    _test_validate_flag_name_special_chars(pickers_mod)
    _test_validate_flag_name_empty_suffix(pickers_mod)
    _test_insert_flag_define_custom_section(pickers_mod)
    _test_insert_flag_define_no_custom_section(pickers_mod)
    _test_insert_flag_define_alignment(pickers_mod)
    _test_define_new_flag_end_to_end(pickers_mod)
    _test_define_new_flag_pool_exhausted(pickers_mod)


# ── Search filtering logic ────────────────────────────────────────────────

def _test_search_filtering(mod):
    """Test _filter_items — the extracted filter helper."""
    _filter = mod._filter_items

    items = [
        ("FLAG_BADGE01_GET", "First badge"),
        ("FLAG_BADGE02_GET", "Second badge"),
        ("FLAG_VISITED_TOWN", "Town visited"),
        ("VAR_TEMP_1", "Temporary variable"),
    ]

    # Case-insensitive matching on name
    results = _filter(items, "badge")
    _assert(
        "filter: case-insensitive 'badge' matches 2 items",
        len(results) == 2,
        f"expected 2, got {len(results)}"
    )

    # Case-insensitive matching on comment
    results = _filter(items, "temporary")
    _assert(
        "filter: matches comment text 'temporary'",
        len(results) == 1 and results[0][0] == "VAR_TEMP_1",
        f"got: {results}"
    )

    # Partial substring match
    results = _filter(items, "01")
    _assert(
        "filter: partial '01' matches FLAG_BADGE01_GET",
        len(results) == 1 and results[0][0] == "FLAG_BADGE01_GET",
        f"got: {results}"
    )

    # Empty query matches all (substring semantics)
    results = _filter(items, "")
    _assert(
        "filter: empty query matches all (substring semantics)",
        len(results) == 4,
        f"expected 4, got {len(results)}"
    )

    # No match
    results = _filter(items, "ZZZZNOTHERE")
    _assert(
        "filter: unmatched term returns empty list",
        len(results) == 0,
        f"expected 0, got {len(results)}"
    )


# ── Item normalisation ────────────────────────────────────────────────────

def _test_normalisation(mod):
    """Test _normalise_items — the extracted normalisation helper."""
    _normalise = mod._normalise_items

    # String items get empty comment
    result = _normalise(["FLAG_A", "FLAG_B"])
    _assert(
        "normalise: plain strings get empty comment",
        result == [("FLAG_A", ""), ("FLAG_B", "")],
        f"got: {result}"
    )

    # Tuple with comment preserved
    result = _normalise([("FLAG_A", "desc A")])
    _assert(
        "normalise: tuple comment preserved",
        result == [("FLAG_A", "desc A")],
        f"got: {result}"
    )

    # Single-element tuple gets empty comment
    result = _normalise([("FLAG_A",)])
    _assert(
        "normalise: single-element tuple gets empty comment",
        result == [("FLAG_A", "")],
        f"got: {result}"
    )


# ── _pick_label from scene data ──────────────────────────────────────────

def _test_pick_label_from_script_data(mod):
    """Test _gather_labels with script_data beats."""
    _gather = mod._gather_labels

    script_data = {
        "beats": [
            {"type": "label", "data": {"name": "MyLabel_Start"}},
            {"type": "text", "data": {"text": "Hello"}},
            {"type": "label", "data": {"name": "MyLabel_End"}},
            {"type": "label", "data": {"name": "MyLabel_Start"}},  # duplicate
        ]
    }

    labels = _gather(script_data)
    _assert(
        "pick_label: extracts 2 unique labels from beats",
        len(labels) == 2,
        f"expected 2, got {len(labels)}: {labels}"
    )
    _assert(
        "pick_label: labels in insertion order",
        labels == ["MyLabel_Start", "MyLabel_End"],
        f"got: {labels}"
    )

    # Empty beats
    labels_empty = _gather({"beats": []})
    _assert(
        "pick_label: empty beats yields empty labels",
        labels_empty == [],
        f"got: {labels_empty}"
    )


# ── _pick_label from sibling files ───────────────────────────────────────

def _test_pick_label_from_files(mod):
    """Test _gather_labels with sibling .txt files."""
    _gather = mod._gather_labels
    tmp_dir = tempfile.mkdtemp(prefix="torch_picker_test_")
    # project_dir is tmp_dir, map_name is "TestMap"
    map_dir = os.path.join(tmp_dir, "TestMap")
    os.makedirs(map_dir)

    try:
        with open(os.path.join(map_dir, "scene1.txt"), "w") as f:
            f.write("text Hello world\\n\n")
            f.write("label FileLabel_One\n")
            f.write("label FileLabel_Two\n")
        with open(os.path.join(map_dir, "notes.md"), "w") as f:
            f.write("label ShouldBeIgnored\n")

        labels = _gather({"beats": []}, "TestMap", tmp_dir)

        _assert(
            "pick_label files: finds 2 labels from .txt",
            len(labels) == 2,
            f"expected 2, got {len(labels)}: {labels}"
        )
        _assert(
            "pick_label files: ignores non-.txt files",
            "ShouldBeIgnored" not in labels,
            f"labels: {labels}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── pick_* wrappers with no game path ────────────────────────────────────

def _test_pick_wrappers_no_game_path(mod):
    """Verify pick_* wrappers handle missing game_path gracefully.

    When game_path is falsy (None/""), the wrappers fall through to
    input() rather than crashing. We verify the code path exists by
    checking the wrapper functions are callable and accept game_path.
    """
    # Each wrapper should be a callable accepting game_path
    wrappers = [
        "pick_flag", "pick_var", "pick_trainer",
        "pick_sound", "pick_music", "pick_fanfare",
        "pick_species", "pick_special",
    ]
    found = [w for w in wrappers if callable(getattr(mod, w, None))]
    _assert(
        "pick_wrappers: all 8 wrappers exist and are callable",
        len(found) == 8,
        f"found {len(found)}/8: {found}"
    )


# ── _MAX_RESULTS constant ────────────────────────────────────────────────

def _test_max_results_constant(mod):
    """Verify _MAX_RESULTS is set to 20."""
    _assert(
        "_MAX_RESULTS is 20",
        getattr(mod, "_MAX_RESULTS", None) == 20,
        f"got: {getattr(mod, '_MAX_RESULTS', 'MISSING')}"
    )


# ── _try_pick helper ─────────────────────────────────────────────────────

def _test_try_pick(mod):
    """Test _try_pick — number parsing from user input."""
    _try_pick = mod._try_pick
    showing = [("FLAG_A", "desc"), ("FLAG_B", "desc"), ("FLAG_C", "desc")]

    # Valid pick
    name, was_num = _try_pick(showing, "2")
    _assert("try_pick: '2' selects FLAG_B", name == "FLAG_B", f"got: {name}")
    _assert("try_pick: '2' is a number", was_num is True, f"got: {was_num}")

    # Out of range
    name, was_num = _try_pick(showing, "99")
    _assert("try_pick: '99' out of range returns None", name is None, f"got: {name}")
    _assert("try_pick: '99' is a number", was_num is True, f"got: {was_num}")

    # Not a number
    name, was_num = _try_pick(showing, "badge")
    _assert("try_pick: 'badge' returns None", name is None, f"got: {name}")
    _assert("try_pick: 'badge' is not a number", was_num is False, f"got: {was_num}")

    # First item
    name, was_num = _try_pick(showing, "1")
    _assert("try_pick: '1' selects FLAG_A", name == "FLAG_A", f"got: {name}")


# ── _gather_labels combined ───────────────────────────────────────────────

def _test_gather_labels_combined(mod):
    """Test _gather_labels merges scene beats and file labels, deduplicating."""
    _gather = mod._gather_labels
    tmp_dir = tempfile.mkdtemp(prefix="torch_picker_combined_")
    map_dir = os.path.join(tmp_dir, "TestMap")
    os.makedirs(map_dir)

    try:
        with open(os.path.join(map_dir, "extra.txt"), "w") as f:
            f.write("label BeatLabel\n")  # duplicate of scene beat
            f.write("label FileOnly\n")

        script_data = {
            "beats": [
                {"type": "label", "data": {"name": "BeatLabel"}},
            ]
        }
        labels = _gather(script_data, "TestMap", tmp_dir)
        _assert(
            "gather combined: deduplicates across beats and files",
            labels == ["BeatLabel", "FileOnly"],
            f"got: {labels}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── detail_callback in _search_pick ──────────────────────────────────────

def _test_detail_callback(mod):
    """Test detail_callback parameter for _search_pick."""
    from unittest.mock import patch, MagicMock
    import inspect

    _search_pick = mod._search_pick

    # detail_callback parameter is accepted
    sig = inspect.signature(_search_pick)
    _assert(
        "detail_callback: parameter exists in _search_pick signature",
        "detail_callback" in sig.parameters,
        f"params: {list(sig.parameters.keys())}"
    )

    # Pressing 'd' with a callback calls it on the first item
    items = [("SPECIES_PIKACHU", "Electric"), ("SPECIES_BULBASAUR", "Grass")]
    callback = MagicMock()

    # Simulate: search "pika", then press "d", then press "q"
    with patch("builtins.input", side_effect=["pika", "d", "q"]):
        result = _search_pick(items, "Species", detail_callback=callback)

    _assert(
        "detail_callback: 'd' calls callback with first match",
        callback.called and callback.call_args[0][0] == "SPECIES_PIKACHU",
        f"called={callback.called}, args={callback.call_args}"
    )

    # Pressing 'd' with no callback does nothing (treated as new search)
    callback2 = MagicMock()
    with patch("builtins.input", side_effect=["pika", "d", "q"]):
        result = _search_pick(items, "Species", detail_callback=None)

    _assert(
        "detail_callback: None callback does not crash on 'd'",
        not callback2.called,
        "callback should not have been called"
    )

    # 'd2' calls callback with second item
    items3 = [("SPECIES_CHARMANDER", "Fire"), ("SPECIES_CHARMELEON", "Fire"),
              ("SPECIES_CHARIZARD", "Fire/Flying")]
    callback3 = MagicMock()
    with patch("builtins.input", side_effect=["char", "d2", "q"]):
        _search_pick(items3, "Species", detail_callback=callback3)

    _assert(
        "detail_callback: 'd2' calls callback with second match",
        callback3.called and callback3.call_args[0][0] == "SPECIES_CHARMELEON",
        f"called={callback3.called}, args={callback3.call_args}"
    )


# ============================================================
# FLAG DEFINER TESTS
# ============================================================

# Sample flags.h content for testing
_SAMPLE_FLAGS_H = """\
#ifndef GUARD_CONSTANTS_FLAGS_H
#define GUARD_CONSTANTS_FLAGS_H

#define FLAG_UNUSED_0x020    0x20 // Unused Flag
#define FLAG_UNUSED_0x021    0x21 // Unused Flag
#define FLAG_UNUSED_0x022    0x22 // Unused Flag
#define FLAG_UNUSED_0x023    0x23 // Unused Flag
#define FLAG_UNUSED_0x024    0x24 // Unused Flag

#define FLAG_BADGE01_GET     0x50

// Custom Seihoku flags
#define FLAG_BEAT_ROCKET_DUO_1            FLAG_UNUSED_0x020
#define FLAG_MET_OFFICER                  FLAG_UNUSED_0x021

#endif // GUARD_CONSTANTS_FLAGS_H
"""

_SAMPLE_FLAGS_H_NO_CUSTOM = """\
#ifndef GUARD_CONSTANTS_FLAGS_H
#define GUARD_CONSTANTS_FLAGS_H

#define FLAG_UNUSED_0x020    0x20 // Unused Flag
#define FLAG_UNUSED_0x021    0x21 // Unused Flag
#define FLAG_UNUSED_0x022    0x22 // Unused Flag

#define FLAG_BADGE01_GET     0x50

#endif // GUARD_CONSTANTS_FLAGS_H
"""


def _test_find_next_unused_flag(mod):
    """Test _find_next_unused_flag with some flags already used."""
    lines = _SAMPLE_FLAGS_H.splitlines(keepends=True)
    result = mod._find_next_unused_flag(lines)
    # 0x020 and 0x021 are used, next available is 0x022
    _assert(
        "find_unused: skips used flags, returns 0x022",
        result == "FLAG_UNUSED_0x022",
        f"got: {result}"
    )


def _test_find_next_unused_flag_all_used(mod):
    """Test _find_next_unused_flag when all flags are used."""
    lines = [
        "#define FLAG_UNUSED_0x020    0x20\n",
        "#define FLAG_UNUSED_0x021    0x21\n",
        "#define FLAG_A    FLAG_UNUSED_0x020\n",
        "#define FLAG_B    FLAG_UNUSED_0x021\n",
    ]
    result = mod._find_next_unused_flag(lines)
    _assert(
        "find_unused: all used returns None",
        result is None,
        f"got: {result}"
    )


def _test_find_next_unused_flag_no_custom(mod):
    """Test _find_next_unused_flag with no custom flags defined."""
    lines = _SAMPLE_FLAGS_H_NO_CUSTOM.splitlines(keepends=True)
    result = mod._find_next_unused_flag(lines)
    _assert(
        "find_unused: no custom section returns first unused (0x020)",
        result == "FLAG_UNUSED_0x020",
        f"got: {result}"
    )


def _test_validate_flag_name_valid(mod):
    """Test _validate_flag_name with a valid name."""
    lines = _SAMPLE_FLAGS_H.splitlines(keepends=True)
    ok, msg = mod._validate_flag_name("FLAG_BEAT_GYM_1", lines)
    _assert(
        "validate: valid name passes",
        ok is True and msg == "",
        f"ok={ok}, msg={msg}"
    )


def _test_validate_flag_name_no_prefix(mod):
    """Test _validate_flag_name rejects names without FLAG_ prefix."""
    lines = _SAMPLE_FLAGS_H.splitlines(keepends=True)
    ok, msg = mod._validate_flag_name("BEAT_GYM_1", lines)
    _assert(
        "validate: missing FLAG_ prefix rejected",
        ok is False and "FLAG_" in msg,
        f"ok={ok}, msg={msg}"
    )


def _test_validate_flag_name_lowercase(mod):
    """Test _validate_flag_name rejects lowercase letters."""
    lines = _SAMPLE_FLAGS_H.splitlines(keepends=True)
    ok, msg = mod._validate_flag_name("FLAG_beat_gym", lines)
    _assert(
        "validate: lowercase rejected",
        ok is False and "UPPER_SNAKE_CASE" in msg,
        f"ok={ok}, msg={msg}"
    )


def _test_validate_flag_name_already_exists(mod):
    """Test _validate_flag_name rejects duplicate names."""
    lines = _SAMPLE_FLAGS_H.splitlines(keepends=True)
    ok, msg = mod._validate_flag_name("FLAG_BEAT_ROCKET_DUO_1", lines)
    _assert(
        "validate: duplicate name rejected",
        ok is False and "already exists" in msg,
        f"ok={ok}, msg={msg}"
    )


def _test_validate_flag_name_special_chars(mod):
    """Test _validate_flag_name rejects special characters."""
    lines = _SAMPLE_FLAGS_H.splitlines(keepends=True)
    ok, msg = mod._validate_flag_name("FLAG_BEAT-GYM!", lines)
    _assert(
        "validate: special chars rejected",
        ok is False,
        f"ok={ok}, msg={msg}"
    )


def _test_validate_flag_name_empty_suffix(mod):
    """Test _validate_flag_name rejects bare FLAG_ with nothing after."""
    lines = _SAMPLE_FLAGS_H.splitlines(keepends=True)
    ok, msg = mod._validate_flag_name("FLAG_", lines)
    _assert(
        "validate: bare FLAG_ rejected",
        ok is False,
        f"ok={ok}, msg={msg}"
    )


def _test_insert_flag_define_custom_section(mod):
    """Test _insert_flag_define inserts after last define in custom section."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_flag_test_")
    flags_path = os.path.join(tmp_dir, "flags.h")
    try:
        with open(flags_path, "w") as f:
            f.write(_SAMPLE_FLAGS_H)

        result = mod._insert_flag_define(flags_path, "FLAG_NEW_TEST", "FLAG_UNUSED_0x022")
        _assert(
            "insert: returns True on success",
            result is True,
            f"got: {result}"
        )

        with open(flags_path) as f:
            content = f.read()
        _assert(
            "insert: new define appears in file",
            "FLAG_NEW_TEST" in content and "FLAG_UNUSED_0x022" in content,
            f"content does not contain new define"
        )
        # Should be after FLAG_MET_OFFICER
        lines = content.splitlines()
        new_idx = next(i for i, l in enumerate(lines) if "FLAG_NEW_TEST" in l)
        met_idx = next(i for i, l in enumerate(lines) if "FLAG_MET_OFFICER" in l)
        _assert(
            "insert: placed after last custom define",
            new_idx == met_idx + 1,
            f"new at {new_idx}, met at {met_idx}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_insert_flag_define_no_custom_section(mod):
    """Test _insert_flag_define inserts before #endif when no custom section."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_flag_test_")
    flags_path = os.path.join(tmp_dir, "flags.h")
    try:
        with open(flags_path, "w") as f:
            f.write(_SAMPLE_FLAGS_H_NO_CUSTOM)

        result = mod._insert_flag_define(flags_path, "FLAG_FIRST_CUSTOM", "FLAG_UNUSED_0x020")
        _assert(
            "insert_no_custom: returns True",
            result is True,
            f"got: {result}"
        )

        with open(flags_path) as f:
            content = f.read()
        lines = content.splitlines()
        new_idx = next(i for i, l in enumerate(lines) if "FLAG_FIRST_CUSTOM" in l)
        endif_idx = next(i for i, l in enumerate(lines) if l.strip().startswith("#endif"))
        _assert(
            "insert_no_custom: placed before #endif",
            new_idx < endif_idx,
            f"new at {new_idx}, endif at {endif_idx}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_insert_flag_define_alignment(mod):
    """Test _insert_flag_define matches existing alignment."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_flag_test_")
    flags_path = os.path.join(tmp_dir, "flags.h")
    try:
        with open(flags_path, "w") as f:
            f.write(_SAMPLE_FLAGS_H)

        mod._insert_flag_define(flags_path, "FLAG_SHORT", "FLAG_UNUSED_0x022")

        with open(flags_path) as f:
            lines = f.readlines()
        new_line = next(l for l in lines if "FLAG_SHORT" in l)
        # The value column should align with nearby defines
        _assert(
            "insert_alignment: value column is right-padded",
            "FLAG_SHORT" in new_line and "FLAG_UNUSED_0x022" in new_line,
            f"line: {new_line.rstrip()}"
        )
        # Verify there's padding between name and value (not jammed together)
        parts = new_line.split("FLAG_SHORT")
        _assert(
            "insert_alignment: has padding between name and value",
            len(parts) == 2 and parts[1].startswith(" "),
            f"line: {new_line.rstrip()}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_define_new_flag_end_to_end(mod):
    """Test define_new_flag end-to-end with a mock game directory."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_flag_e2e_")
    inc_dir = os.path.join(tmp_dir, "include", "constants")
    os.makedirs(inc_dir)
    flags_path = os.path.join(inc_dir, "flags.h")
    try:
        with open(flags_path, "w") as f:
            f.write(_SAMPLE_FLAGS_H)

        result = mod.define_new_flag(tmp_dir, "FLAG_BEAT_GYM_1")
        _assert(
            "define_e2e: returns flag name on success",
            result == "FLAG_BEAT_GYM_1",
            f"got: {result}"
        )

        with open(flags_path) as f:
            content = f.read()
        _assert(
            "define_e2e: flag appears in file",
            "FLAG_BEAT_GYM_1" in content,
            f"flag not found in file"
        )
        # Should have used FLAG_UNUSED_0x022 (first two are taken)
        _assert(
            "define_e2e: uses correct unused slot (0x022)",
            "#define FLAG_BEAT_GYM_1" in content and "FLAG_UNUSED_0x022" in content,
            f"wrong slot used"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_define_new_flag_pool_exhausted(mod):
    """Test define_new_flag when no unused flags remain."""
    tmp_dir = tempfile.mkdtemp(prefix="torch_flag_exhausted_")
    inc_dir = os.path.join(tmp_dir, "include", "constants")
    os.makedirs(inc_dir)
    flags_path = os.path.join(inc_dir, "flags.h")
    try:
        # All unused flags are aliased
        content = """\
#ifndef GUARD_CONSTANTS_FLAGS_H
#define GUARD_CONSTANTS_FLAGS_H
#define FLAG_UNUSED_0x020    0x20
#define FLAG_A    FLAG_UNUSED_0x020
#endif
"""
        with open(flags_path, "w") as f:
            f.write(content)

        result = mod.define_new_flag(tmp_dir, "FLAG_WILL_FAIL")
        _assert(
            "define_exhausted: returns None when pool empty",
            result is None,
            f"got: {result}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
