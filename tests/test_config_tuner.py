"""Tests for config_tuner.py (Settings) and gamedata.parse_defines_full().

Covers value classification, config file registry, pending changes tracker,
display helpers, settings list builder, search functions, config discovery,
ROM Metadata integration, and the parse_defines_full() parser in gamedata.py.
"""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _assert, _ok, _fail, _skip


def run_suite():
    _begin_suite("Settings  (pure-logic helpers)")

    try:
        import torch.config_tuner as ct
    except ImportError as e:
        _skip("all config_tuner tests", f"import failed: {e}")
        return

    try:
        from torch.gamedata import parse_defines_full, clear_gamedata_cache
    except ImportError as e:
        _skip("all gamedata parse_defines_full tests", f"import failed: {e}")
        return

    _test_classify_gen(ct)
    _test_classify_bool(ct)
    _test_classify_int(ct)
    _test_classify_flag_var(ct)
    _test_classify_const(ct)
    _test_classify_edge_cases(ct)
    _test_gen_values_list(ct)
    _test_gen_keys_mapping(ct)
    _test_config_files_registry(ct)
    _test_pending_changes(ct)
    _test_coloured_value(ct)
    _test_raw_value_for_display(ct)
    _test_config_dir(ct)
    _test_build_settings_list(ct)
    _test_search_all(ct)
    _test_parse_defines_full(parse_defines_full, clear_gamedata_cache)
    _test_parse_defines_full_prefix(parse_defines_full, clear_gamedata_cache)
    _test_parse_defines_full_edge(parse_defines_full, clear_gamedata_cache)
    _test_discover_extra_files(ct)
    _test_rom_metadata_category(ct)
    _test_rom_metadata_in_discover(ct)
    _test_coloured_value_rom_field(ct)
    _test_raw_value_rom_field(ct)
    _test_search_all_rom_fields(ct)


# ── _classify_value: gen ─────────────────────────────────────────────────

def _test_classify_gen(ct):
    """GEN_3 through GEN_9 and GEN_LATEST classify as gen."""
    for gen in ("GEN_3", "GEN_4", "GEN_5", "GEN_6", "GEN_7", "GEN_8",
                "GEN_9", "GEN_LATEST"):
        kind, val = ct._classify_value("ANY_NAME", gen)
        _assert(
            f"classify_value: {gen} -> gen",
            kind == "gen" and val == gen,
            f"got: ({kind}, {val})"
        )

    # With whitespace
    kind, val = ct._classify_value("NAME", "  GEN_7  ")
    _assert(
        "classify_value: GEN_7 with whitespace -> gen",
        kind == "gen" and val == "GEN_7",
        f"got: ({kind}, {val})"
    )


# ── _classify_value: bool ────────────────────────────────────────────────

def _test_classify_bool(ct):
    """TRUE/FALSE classify as bool."""
    kind, val = ct._classify_value("SOME_TOGGLE", "TRUE")
    _assert(
        "classify_value: TRUE -> bool True",
        kind == "bool" and val is True,
        f"got: ({kind}, {val})"
    )

    kind, val = ct._classify_value("SOME_TOGGLE", "FALSE")
    _assert(
        "classify_value: FALSE -> bool False",
        kind == "bool" and val is False,
        f"got: ({kind}, {val})"
    )


# ── _classify_value: int ─────────────────────────────────────────────────

def _test_classify_int(ct):
    """Numeric strings classify as int."""
    kind, val = ct._classify_value("MAX_LEVEL", "100")
    _assert(
        "classify_value: 100 -> int 100",
        kind == "int" and val == 100,
        f"got: ({kind}, {val})"
    )

    kind, val = ct._classify_value("MIN_LEVEL", "0")
    _assert(
        "classify_value: 0 (non-flag name) -> int 0",
        kind == "int" and val == 0,
        f"got: ({kind}, {val})"
    )

    kind, val = ct._classify_value("NEGATIVE", "-5")
    _assert(
        "classify_value: -5 -> int -5",
        kind == "int" and val == -5,
        f"got: ({kind}, {val})"
    )


# ── _classify_value: flag_var ────────────────────────────────────────────

def _test_classify_flag_var(ct):
    """FLAG/VAR names with 0 or constant values classify as flag_var."""
    kind, val = ct._classify_value("USE_FLAG_SOMETHING", "0")
    _assert(
        "classify_value: FLAG name + 0 -> flag_var",
        kind == "flag_var" and val == "0",
        f"got: ({kind}, {val})"
    )

    kind, val = ct._classify_value("USE_VAR_SOMETHING", "0")
    _assert(
        "classify_value: VAR name + 0 -> flag_var",
        kind == "flag_var" and val == "0",
        f"got: ({kind}, {val})"
    )

    kind, val = ct._classify_value("USE_FLAG_TOGGLE", "FLAG_CUSTOM_01")
    _assert(
        "classify_value: FLAG name + non-zero const -> flag_var",
        kind == "flag_var" and val == "FLAG_CUSTOM_01",
        f"got: ({kind}, {val})"
    )

    kind, val = ct._classify_value("SOME_VAR_CONTROL", "VAR_CUSTOM")
    _assert(
        "classify_value: VAR name + non-zero const -> flag_var",
        kind == "flag_var" and val == "VAR_CUSTOM",
        f"got: ({kind}, {val})"
    )


# ── _classify_value: const ───────────────────────────────────────────────

def _test_classify_const(ct):
    """Complex expressions classify as const."""
    kind, val = ct._classify_value("CALC", "(1 << 3)")
    _assert(
        "classify_value: bit shift expression -> const",
        kind == "const" and val == "(1 << 3)",
        f"got: ({kind}, {val})"
    )

    kind, val = ct._classify_value("COMBO", "FOO | BAR")
    _assert(
        "classify_value: OR expression -> const",
        kind == "const" and val == "FOO | BAR",
        f"got: ({kind}, {val})"
    )


# ── _classify_value: edge cases ─────────────────────────────────────────

def _test_classify_edge_cases(ct):
    """Edge cases for classify_value."""
    # Empty string
    kind, val = ct._classify_value("NAME", "")
    _assert(
        "classify_value: empty string -> const",
        kind == "const" and val == "",
        f"got: ({kind}, {val})"
    )

    # Whitespace-only
    kind, val = ct._classify_value("NAME", "   ")
    _assert(
        "classify_value: whitespace-only -> const",
        kind == "const" and val == "",
        f"got: ({kind}, {val})"
    )

    # Case sensitivity: 'true' (lowercase) is not a bool
    kind, val = ct._classify_value("NAME", "true")
    _assert(
        "classify_value: lowercase true -> const (not bool)",
        kind == "const",
        f"got: ({kind}, {val})"
    )

    # 'GEN_10' is not a recognized gen
    kind, val = ct._classify_value("NAME", "GEN_10")
    _assert(
        "classify_value: GEN_10 -> const (not gen)",
        kind == "const",
        f"got: ({kind}, {val})"
    )


# ── _GEN_VALUES / _GEN_KEYS ─────────────────────────────────────────────

def _test_gen_values_list(ct):
    """_GEN_VALUES has all 8 expected entries in order."""
    _assert(
        "gen_values: has 8 entries",
        len(ct._GEN_VALUES) == 8,
        f"got: {len(ct._GEN_VALUES)}"
    )
    _assert(
        "gen_values: starts with GEN_3",
        ct._GEN_VALUES[0] == "GEN_3",
        f"got: {ct._GEN_VALUES[0]}"
    )
    _assert(
        "gen_values: ends with GEN_LATEST",
        ct._GEN_VALUES[-1] == "GEN_LATEST",
        f"got: {ct._GEN_VALUES[-1]}"
    )


def _test_gen_keys_mapping(ct):
    """_GEN_KEYS maps digits 1-7 + l to correct gen constants."""
    _assert(
        "gen_keys: '1' -> GEN_3",
        ct._GEN_KEYS["1"] == "GEN_3",
        f"got: {ct._GEN_KEYS.get('1')}"
    )
    _assert(
        "gen_keys: '7' -> GEN_9",
        ct._GEN_KEYS["7"] == "GEN_9",
        f"got: {ct._GEN_KEYS.get('7')}"
    )
    _assert(
        "gen_keys: 'l' -> GEN_LATEST",
        ct._GEN_KEYS["l"] == "GEN_LATEST",
        f"got: {ct._GEN_KEYS.get('l')}"
    )
    _assert(
        "gen_keys: has 8 entries",
        len(ct._GEN_KEYS) == 8,
        f"got: {len(ct._GEN_KEYS)}"
    )


# ── _CONFIG_FILES registry ───────────────────────────────────────────────

def _test_config_files_registry(ct):
    """_CONFIG_FILES dict has expected categories and valid filenames."""
    expected_keys = {
        "Battle", "Pokemon", "Items", "Overworld", "Species Toggle",
        "AI", "DexNav", "Fishing", "Text", "Summary Screen", "Debug",
        "General", "Caps", "Save", "Contest", "Follower NPC", "Name Box",
    }
    _assert(
        "config_files: has all expected categories",
        set(ct._CONFIG_FILES.keys()) == expected_keys,
        f"missing: {expected_keys - set(ct._CONFIG_FILES.keys())}, "
        f"extra: {set(ct._CONFIG_FILES.keys()) - expected_keys}"
    )

    # All values end with .h
    all_h = all(v.endswith(".h") for v in ct._CONFIG_FILES.values())
    _assert(
        "config_files: all filenames end with .h",
        all_h,
        f"non-.h files: {[v for v in ct._CONFIG_FILES.values() if not v.endswith('.h')]}"
    )

    # Battle maps to battle.h
    _assert(
        "config_files: Battle -> battle.h",
        ct._CONFIG_FILES["Battle"] == "battle.h",
        f"got: {ct._CONFIG_FILES.get('Battle')}"
    )


# ── _PendingChanges ─────────────────────────────────────────────────────

def _test_pending_changes(ct):
    """PendingChanges tracker: set, get, discard, count, items, files, clear."""
    pc = ct._PendingChanges()

    _assert("pending: initial count is 0", pc.count() == 0,
            f"got: {pc.count()}")

    # Set and get
    pc.set("/path/a.h", "CONST_A", "TRUE")
    _assert("pending: count after 1 set is 1", pc.count() == 1,
            f"got: {pc.count()}")
    _assert("pending: get returns set value",
            pc.get("/path/a.h", "CONST_A") == "TRUE",
            f"got: {pc.get('/path/a.h', 'CONST_A')}")

    # Get missing returns None
    _assert("pending: get missing returns None",
            pc.get("/path/a.h", "MISSING") is None,
            f"got: {pc.get('/path/a.h', 'MISSING')}")

    # Set another in different file
    pc.set("/path/b.h", "CONST_B", "42")
    _assert("pending: count after 2 sets is 2", pc.count() == 2,
            f"got: {pc.count()}")

    # Files returns both paths
    _assert("pending: files returns 2 paths",
            pc.files() == {"/path/a.h", "/path/b.h"},
            f"got: {pc.files()}")

    # Items returns all entries
    _assert("pending: items returns 2 entries",
            len(pc.items()) == 2,
            f"got: {len(pc.items())}")

    # Overwrite existing
    pc.set("/path/a.h", "CONST_A", "FALSE")
    _assert("pending: overwrite keeps count at 2", pc.count() == 2,
            f"got: {pc.count()}")
    _assert("pending: overwrite updates value",
            pc.get("/path/a.h", "CONST_A") == "FALSE",
            f"got: {pc.get('/path/a.h', 'CONST_A')}")

    # Discard
    pc.discard("/path/a.h", "CONST_A")
    _assert("pending: count after discard is 1", pc.count() == 1,
            f"got: {pc.count()}")
    _assert("pending: get after discard returns None",
            pc.get("/path/a.h", "CONST_A") is None,
            f"got: {pc.get('/path/a.h', 'CONST_A')}")

    # Discard missing does not error
    pc.discard("/path/x.h", "NOPE")
    _assert("pending: discard missing does not raise", pc.count() == 1,
            f"got: {pc.count()}")

    # Clear
    pc.clear()
    _assert("pending: count after clear is 0", pc.count() == 0,
            f"got: {pc.count()}")
    _assert("pending: files after clear is empty",
            pc.files() == set(),
            f"got: {pc.files()}")


# ── _coloured_value ──────────────────────────────────────────────────────

def _test_coloured_value(ct):
    """Coloured value returns a string (contains ANSI codes)."""
    # We just check it returns a string and contains the value text
    result = ct._coloured_value(("gen", "GEN_7"))
    _assert("coloured_value: gen contains GEN_7",
            "GEN_7" in result, f"got: {repr(result)}")

    result = ct._coloured_value(("bool", True))
    _assert("coloured_value: bool True contains TRUE",
            "TRUE" in result, f"got: {repr(result)}")

    result = ct._coloured_value(("bool", False))
    _assert("coloured_value: bool False contains FALSE",
            "FALSE" in result, f"got: {repr(result)}")

    result = ct._coloured_value(("int", 42))
    _assert("coloured_value: int contains 42",
            "42" in result, f"got: {repr(result)}")

    result = ct._coloured_value(("flag_var", "0"))
    _assert("coloured_value: flag_var 0 contains disabled",
            "disabled" in result, f"got: {repr(result)}")

    result = ct._coloured_value(("flag_var", "FLAG_X"))
    _assert("coloured_value: flag_var non-zero contains FLAG_X",
            "FLAG_X" in result, f"got: {repr(result)}")

    result = ct._coloured_value(("const", "(1 << 3)"))
    _assert("coloured_value: const contains expression",
            "(1 << 3)" in result, f"got: {repr(result)}")


# ── _raw_value_for_display ───────────────────────────────────────────────

def _test_raw_value_for_display(ct):
    """Raw value for display returns uncoloured text."""
    _assert("raw_display: bool True -> 'TRUE'",
            ct._raw_value_for_display(("bool", True)) == "TRUE",
            f"got: {ct._raw_value_for_display(('bool', True))}")

    _assert("raw_display: bool False -> 'FALSE'",
            ct._raw_value_for_display(("bool", False)) == "FALSE",
            f"got: {ct._raw_value_for_display(('bool', False))}")

    _assert("raw_display: gen -> GEN_7",
            ct._raw_value_for_display(("gen", "GEN_7")) == "GEN_7",
            f"got: {ct._raw_value_for_display(('gen', 'GEN_7'))}")

    _assert("raw_display: int -> str(42)",
            ct._raw_value_for_display(("int", 42)) == "42",
            f"got: {ct._raw_value_for_display(('int', 42))}")

    _assert("raw_display: const -> as-is",
            ct._raw_value_for_display(("const", "(1 << 3)")) == "(1 << 3)",
            f"got: {ct._raw_value_for_display(('const', '(1 << 3)'))}")


# ── _config_dir ──────────────────────────────────────────────────────────

def _test_config_dir(ct):
    """Config dir returns correct path."""
    result = ct._config_dir("/home/user/project")
    expected = os.path.join("/home/user/project", "include", "config")
    _assert("config_dir: returns include/config/ path",
            result == expected,
            f"got: {result}")


# ── _build_settings_list ─────────────────────────────────────────────────

def _test_build_settings_list(ct):
    """Build settings list filters guards and classifies values."""
    raw = [
        ("GUARD_CONFIG_BATTLE_H", "", ""),
        ("B_SOME_TOGGLE", "TRUE", "Enables something"),
        ("B_MAX_LEVEL", "100", ""),
        ("#pragma once", "", ""),
        ("B_USE_FLAG", "0", ""),
    ]
    result = ct._build_settings_list(raw, "/fake/path.h")

    _assert("build_settings: filters GUARD_ prefix",
            not any(n.startswith("GUARD_") for n, _, _, _ in result),
            f"found GUARD_ in: {[n for n, _, _, _ in result]}")

    _assert("build_settings: filters # prefix",
            not any(n.startswith("#") for n, _, _, _ in result),
            f"found # in: {[n for n, _, _, _ in result]}")

    _assert("build_settings: keeps valid entries",
            len(result) == 3,
            f"got {len(result)} entries: {[n for n, _, _, _ in result]}")

    # Check classification is attached
    names = {n: vt for n, _, _, vt in result}
    _assert("build_settings: B_SOME_TOGGLE classified as bool",
            names["B_SOME_TOGGLE"][0] == "bool",
            f"got: {names['B_SOME_TOGGLE']}")

    _assert("build_settings: B_MAX_LEVEL classified as int",
            names["B_MAX_LEVEL"][0] == "int",
            f"got: {names['B_MAX_LEVEL']}")


# ── _search_all ──────────────────────────────────────────────────────────

def _test_search_all(ct):
    """Search across categories by name or comment."""
    categories = [
        ("Battle", "/fake/battle.h", [
            ("B_SPEED_CLAUSE", "TRUE", "speed clause toggle", ("bool", True)),
            ("B_MAX_LEVEL", "100", "max level cap", ("int", 100)),
        ]),
        ("Pokemon", "/fake/pokemon.h", [
            ("P_SHINY_ODDS", "4096", "shiny encounter odds", ("int", 4096)),
        ]),
    ]

    # Search by name
    results = ct._search_all(categories, "SPEED")
    _assert("search_all: finds SPEED in name",
            len(results) == 1 and results[0][1] == "B_SPEED_CLAUSE",
            f"got: {[(r[1]) for r in results]}")

    # Search by comment
    results = ct._search_all(categories, "shiny")
    _assert("search_all: finds shiny in comment (case-insensitive)",
            len(results) == 1 and results[0][1] == "P_SHINY_ODDS",
            f"got: {[(r[1]) for r in results]}")

    # Search matching multiple
    results = ct._search_all(categories, "level")
    _assert("search_all: finds 'level' in name and comment",
            len(results) == 1 and results[0][1] == "B_MAX_LEVEL",
            f"got: {[(r[1]) for r in results]}")

    # No match
    results = ct._search_all(categories, "zzzznotfound")
    _assert("search_all: no match returns empty",
            len(results) == 0,
            f"got: {len(results)} results")

    # Results are sorted by name
    results = ct._search_all(categories, "")  # matches all
    names = [r[1] for r in results]
    _assert("search_all: results sorted by name",
            names == sorted(names),
            f"got: {names}")


# ── parse_defines_full ───────────────────────────────────────────────────

def _test_parse_defines_full(parse_fn, clear_cache):
    """parse_defines_full: basic parsing with name, value, comment."""
    clear_cache()
    content = """\
#ifndef GUARD_CONFIG_BATTLE_H
#define GUARD_CONFIG_BATTLE_H

#define B_SPEED_CLAUSE TRUE  // Enable speed clause
#define B_MAX_LEVEL 100
#define B_SHIFT_EXPR (1 << 3)  // Bitwise shift
#define B_BARE_DEFINE
#define B_MULTI_VAL FOO | BAR  // Combined flags

#endif
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".h", delete=False) as f:
        f.write(content)
        tmp = f.name

    try:
        results = parse_fn(tmp)

        # parse_defines_full is a raw parser — it does NOT filter guards.
        # Guard filtering happens in _build_settings_list.
        names = [r[0] for r in results]
        _assert("parse_defines_full: finds all 6 defines (including guard)",
                len(results) == 6,
                f"got {len(results)}: {names}")

        # Check specific entries (sorted by name)
        by_name = {r[0]: (r[1], r[2]) for r in results}

        _assert("parse_defines_full: B_BARE_DEFINE has empty value",
                by_name["B_BARE_DEFINE"][0] == "",
                f"got: {repr(by_name['B_BARE_DEFINE'][0])}")

        _assert("parse_defines_full: B_MAX_LEVEL value is '100'",
                by_name["B_MAX_LEVEL"][0] == "100",
                f"got: {repr(by_name['B_MAX_LEVEL'][0])}")

        _assert("parse_defines_full: B_MAX_LEVEL has no comment",
                by_name["B_MAX_LEVEL"][1] == "",
                f"got: {repr(by_name['B_MAX_LEVEL'][1])}")

        _assert("parse_defines_full: B_SPEED_CLAUSE value is 'TRUE'",
                by_name["B_SPEED_CLAUSE"][0] == "TRUE",
                f"got: {repr(by_name['B_SPEED_CLAUSE'][0])}")

        _assert("parse_defines_full: B_SPEED_CLAUSE comment captured",
                by_name["B_SPEED_CLAUSE"][1] == "Enable speed clause",
                f"got: {repr(by_name['B_SPEED_CLAUSE'][1])}")

        _assert("parse_defines_full: B_SHIFT_EXPR captures multi-token value",
                by_name["B_SHIFT_EXPR"][0] == "(1 << 3)",
                f"got: {repr(by_name['B_SHIFT_EXPR'][0])}")

        _assert("parse_defines_full: B_MULTI_VAL captures OR expression",
                by_name["B_MULTI_VAL"][0] == "FOO | BAR",
                f"got: {repr(by_name['B_MULTI_VAL'][0])}")

        # Results are sorted by name
        _assert("parse_defines_full: results sorted by name",
                names == sorted(names),
                f"got: {names}")
    finally:
        os.unlink(tmp)
        clear_cache()


def _test_parse_defines_full_prefix(parse_fn, clear_cache):
    """parse_defines_full: prefix filtering."""
    clear_cache()
    content = """\
#define B_SPEED TRUE
#define P_SHINY 4096
#define B_LEVEL 50
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".h", delete=False) as f:
        f.write(content)
        tmp = f.name

    try:
        results = parse_fn(tmp, prefix="B_")
        names = [r[0] for r in results]
        _assert("parse_defines_full prefix: only B_ defines returned",
                all(n.startswith("B_") for n in names),
                f"got: {names}")
        _assert("parse_defines_full prefix: finds 2 B_ defines",
                len(results) == 2,
                f"got: {len(results)}")
    finally:
        os.unlink(tmp)
        clear_cache()


def _test_parse_defines_full_edge(parse_fn, clear_cache):
    """parse_defines_full: edge cases — missing file, empty file."""
    clear_cache()

    # Missing file returns empty list
    result = parse_fn("/nonexistent/path/fake.h")
    _assert("parse_defines_full: missing file returns []",
            result == [],
            f"got: {result}")

    # None path returns empty list
    result = parse_fn(None)
    _assert("parse_defines_full: None path returns []",
            result == [],
            f"got: {result}")

    # Empty file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".h", delete=False) as f:
        f.write("")
        tmp = f.name
    try:
        result = parse_fn(tmp)
        _assert("parse_defines_full: empty file returns []",
                result == [],
                f"got: {result}")
    finally:
        os.unlink(tmp)
        clear_cache()


# ── _discover_extra_files ────────────────────────────────────────────────

def _test_discover_extra_files(ct):
    """Discover .h files not in _CONFIG_FILES registry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a known .h file from the registry
        with open(os.path.join(tmpdir, "battle.h"), "w") as f:
            f.write("#define B_THING TRUE\n")

        # Create an extra .h file NOT in the registry
        with open(os.path.join(tmpdir, "custom_feature.h"), "w") as f:
            f.write("#define CUSTOM_TOGGLE TRUE  // A custom toggle\n")

        # Create a non-.h file (should be ignored)
        with open(os.path.join(tmpdir, "readme.txt"), "w") as f:
            f.write("not a header\n")

        categories = []
        ct._discover_extra_files(tmpdir, categories)

        names = [c[0] for c in categories]
        _assert("discover_extra: finds custom_feature.h",
                "Custom Feature" in names,
                f"got: {names}")

        # Should NOT include battle.h (it's in the registry)
        _assert("discover_extra: skips registry files",
                not any("battle" in n.lower() for n in names),
                f"got: {names}")

        # Should NOT include readme.txt
        _assert("discover_extra: skips non-.h files",
                not any("readme" in n.lower() for n in names),
                f"got: {names}")

    # Non-existent directory doesn't crash
    categories_empty = []
    ct._discover_extra_files("/nonexistent/path", categories_empty)
    _assert("discover_extra: missing dir returns nothing",
            len(categories_empty) == 0,
            f"got: {len(categories_empty)}")


# ── ROM Metadata category ──────────────────────────────────────────────

def _test_rom_metadata_category(ct):
    """ROM Metadata category builds from studio.py read_rom_fields."""
    if not ct._HAS_ROM_FIELDS:
        _skip("rom_metadata_category", "studio.py not available")
        return

    tmpdir = tempfile.mkdtemp(prefix="torch_test_ct_rom_")
    try:
        game_path = os.path.join(tmpdir, "game")
        os.makedirs(os.path.join(game_path, "src"), exist_ok=True)
        mf = os.path.join(game_path, "Makefile")
        with open(mf, "w") as f:
            f.write("TITLE       := TESTROM\n")
            f.write("GAME_CODE   := ABCD\n")
            f.write("MAKER_CODE  := 01\n")
            f.write("REVISION    := 0\n")
            f.write("ROM_NAME    := test.gba\n")
        hdr = os.path.join(game_path, "src", "rom_header_gf.c")
        with open(hdr, "w") as f:
            f.write('.gameName = "TEST ROM",\n')

        cat = ct._build_rom_metadata_category(game_path, None)
        _assert("rom_metadata: returns tuple",
                cat is not None and len(cat) == 3,
                f"got: {cat}")

        name, fpath, slist = cat
        _assert("rom_metadata: name is ROM Metadata",
                name == "ROM Metadata",
                f"got: {name}")
        _assert("rom_metadata: path is sentinel",
                fpath == ct._ROM_METADATA_PATH,
                f"got: {fpath}")
        _assert("rom_metadata: has 6 fields",
                len(slist) == 6,
                f"got: {len(slist)}")

        # Check structure of first field
        field_name, field_value, field_comment, field_vtype = slist[0]
        _assert("rom_metadata: first field key is TITLE",
                field_name == "TITLE",
                f"got: {field_name}")
        _assert("rom_metadata: first field vtype is rom_field",
                field_vtype[0] == "rom_field",
                f"got: {field_vtype[0]}")
        _assert("rom_metadata: first field dict has value",
                field_vtype[1]["value"] == "TESTROM",
                f"got: {field_vtype[1].get('value')}")
    finally:
        shutil.rmtree(tmpdir)


def _test_rom_metadata_in_discover(ct):
    """ROM Metadata appears first in _discover_categories when available."""
    if not ct._HAS_ROM_FIELDS:
        _skip("rom_metadata_in_discover", "studio.py not available")
        return

    tmpdir = tempfile.mkdtemp(prefix="torch_test_ct_disc_")
    try:
        game_path = os.path.join(tmpdir, "game")
        os.makedirs(os.path.join(game_path, "src"), exist_ok=True)
        mf = os.path.join(game_path, "Makefile")
        with open(mf, "w") as f:
            f.write("TITLE       := TESTROM\n")
            f.write("GAME_CODE   := ABCD\n")
            f.write("MAKER_CODE  := 01\n")
            f.write("REVISION    := 0\n")
            f.write("ROM_NAME    := test.gba\n")
        hdr = os.path.join(game_path, "src", "rom_header_gf.c")
        with open(hdr, "w") as f:
            f.write('.gameName = "TEST ROM",\n')

        # No config dir — should still get ROM Metadata
        cats = ct._discover_categories(game_path, None)
        _assert("discover: ROM Metadata present without config dir",
                len(cats) >= 1,
                f"got {len(cats)} categories")
        _assert("discover: first category is ROM Metadata",
                cats[0][0] == "ROM Metadata",
                f"got: {cats[0][0]}")

        # With a config dir
        cfg_dir = os.path.join(game_path, "include", "config")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "battle.h"), "w") as f:
            f.write("#define B_SPEED_CLAUSE TRUE  // speed\n")
        cats = ct._discover_categories(game_path, None)
        _assert("discover: ROM Metadata still first with config",
                cats[0][0] == "ROM Metadata",
                f"got: {cats[0][0]}")
        _assert("discover: config categories also present",
                len(cats) >= 2,
                f"got {len(cats)} categories")
    finally:
        shutil.rmtree(tmpdir)


def _test_coloured_value_rom_field(ct):
    """Coloured value handles rom_field type."""
    field = {"key": "TITLE", "label": "ROM Title", "value": "MY ROM"}
    result = ct._coloured_value(("rom_field", field))
    _assert("coloured_value: rom_field contains value",
            "MY ROM" in result,
            f"got: {repr(result)}")


def _test_raw_value_rom_field(ct):
    """Raw value for display handles rom_field type."""
    field = {"key": "TITLE", "label": "ROM Title", "value": "MY ROM"}
    result = ct._raw_value_for_display(("rom_field", field))
    _assert("raw_display: rom_field returns value",
            result == "MY ROM",
            f"got: {repr(result)}")


def _test_search_all_rom_fields(ct):
    """Search across categories finds ROM Metadata by label."""
    field = {"key": "TITLE", "label": "ROM Title", "value": "MY ROM",
             "max_len": 12, "validator": "title"}
    categories = [
        ("ROM Metadata", ct._ROM_METADATA_PATH, [
            ("TITLE", "MY ROM", "GBA header title",
             ("rom_field", field)),
        ]),
    ]
    # Search by label
    results = ct._search_all(categories, "ROM Title")
    _assert("search_all: finds rom_field by label",
            len(results) == 1 and results[0][1] == "TITLE",
            f"got: {[(r[1]) for r in results]}")

    # Search by key
    results = ct._search_all(categories, "TITLE")
    _assert("search_all: finds rom_field by key",
            len(results) == 1,
            f"got: {len(results)} results")

    # Search by comment
    results = ct._search_all(categories, "GBA header")
    _assert("search_all: finds rom_field by comment",
            len(results) == 1,
            f"got: {len(results)} results")
