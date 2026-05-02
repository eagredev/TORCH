"""Gamedata parser suite -- inline temp file, no ROM needed."""
import os
import tempfile

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Gamedata parser  (inline fixture, no ROM needed)")

    try:
        from torch.gamedata import parse_defines, parse_defines_set, clear_gamedata_cache
    except ImportError as e:
        _skip("all gamedata tests", f"import failed: {e}")
        return

    # Write a minimal header file to a temp location
    header_content = """\
#ifndef TEST_H
#define TEST_H

#define FLAG_TEST_ALPHA   0x100  // First test flag
#define FLAG_TEST_BETA    0x101  // Second test flag
#define VAR_TEST_COUNTER  0x4000 // A counter variable
#define SOMETHING_ELSE    0x200  // Not a flag

#endif
"""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".h",
                                         delete=False) as tmp:
            tmp.write(header_content)
            tmp_path = tmp.name

        clear_gamedata_cache()

        # parse_defines with FLAG_ prefix — should get 2 results
        results = parse_defines(tmp_path, prefix="FLAG_")
        _assert(
            "parse_defines: returns 2 FLAG_ entries",
            len(results) == 2,
            f"expected 2, got {len(results)}: {results}"
        )
        names = [r[0] for r in results]
        _assert(
            "parse_defines: FLAG_TEST_ALPHA present",
            "FLAG_TEST_ALPHA" in names,
            f"names: {names}"
        )
        _assert(
            "parse_defines: FLAG_TEST_BETA present",
            "FLAG_TEST_BETA" in names,
            f"names: {names}"
        )

        # parse_defines_set — should return a set of just the names
        result_set = parse_defines_set(tmp_path, prefix="FLAG_")
        _assert(
            "parse_defines_set: returns a set with 2 items",
            isinstance(result_set, set) and len(result_set) == 2,
            f"got: {result_set!r}"
        )

        # No prefix — all 4 defines should be returned
        clear_gamedata_cache()
        all_results = parse_defines(tmp_path)
        _assert(
            "parse_defines: no prefix returns all 4 defines",
            len(all_results) == 4,
            f"expected 4, got {len(all_results)}: {all_results}"
        )

        # Inline comment captured
        comments = {r[0]: r[1] for r in all_results}
        _assert(
            "parse_defines: inline comment captured for FLAG_TEST_ALPHA",
            "First test flag" in (comments.get("FLAG_TEST_ALPHA") or ""),
            f"comment was: {comments.get('FLAG_TEST_ALPHA')!r}"
        )

        # Multi-token define values (e.g. composite expressions)
        clear_gamedata_cache()
        multi_content = """\
#define AI_FLAG_CHECK_BAD_MOVE (1 << 0) // Check bad moves
#define AI_FLAG_BASIC (AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT) // Basic AI
#define AI_FLAG_HP_AWARE (1 << 5)
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".h",
                                         delete=False) as tmp2:
            tmp2.write(multi_content)
            multi_path = tmp2.name
        try:
            multi_results = parse_defines(multi_path, prefix="AI_FLAG_")
            _assert(
                "parse_defines: multi-token value captured (3 entries)",
                len(multi_results) == 3,
                f"expected 3, got {len(multi_results)}: {multi_results}"
            )
            multi_comments = {r[0]: r[1] for r in multi_results}
            _assert(
                "parse_defines: multi-token value has comment",
                multi_comments.get("AI_FLAG_BASIC") == "Basic AI",
                f"comment was: {multi_comments.get('AI_FLAG_BASIC')!r}"
            )
            _assert(
                "parse_defines: single-token value with comment still works",
                multi_comments.get("AI_FLAG_CHECK_BAD_MOVE") == "Check bad moves",
                f"comment was: {multi_comments.get('AI_FLAG_CHECK_BAD_MOVE')!r}"
            )
            _assert(
                "parse_defines: no-comment define still matched",
                "AI_FLAG_HP_AWARE" in multi_comments,
                f"names: {list(multi_comments.keys())}"
            )
        finally:
            try:
                os.unlink(multi_path)
            except Exception:
                pass
            clear_gamedata_cache()

        # Non-existent file returns empty list (not an error)
        clear_gamedata_cache()
        empty = parse_defines("/tmp/torch_nonexistent_file_xyz.h")
        _assert(
            "parse_defines: missing file returns [] gracefully",
            empty == [],
            f"got: {empty!r}"
        )

    except Exception as e:
        _fail("gamedata suite raised", str(e))
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        try:
            clear_gamedata_cache()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Trainer ID loader tests
    # ------------------------------------------------------------------
    _begin_suite("Trainer ID loader  (unified trainer parsers)")
    _test_trainer_ids(clear_gamedata_cache)

    # ------------------------------------------------------------------
    # C struct initializer parser tests
    # ------------------------------------------------------------------
    _begin_suite("Struct parser  (C struct initializer arrays)")

    try:
        from torch.gamedata import (
            parse_struct_entries, parse_struct_entry,
            parse_unnamed_struct_array, extract_field_value,
        )
    except ImportError as e:
        _skip("all struct parser tests", f"import failed: {e}")
        return

    _test_struct_entries(parse_struct_entries, parse_struct_entry,
                         clear_gamedata_cache)
    _test_unnamed_struct_array(parse_unnamed_struct_array,
                                clear_gamedata_cache)
    _test_extract_field_value(extract_field_value)
    _test_struct_comments(parse_struct_entries, clear_gamedata_cache)
    _test_struct_caching(parse_struct_entries, clear_gamedata_cache)
    _test_struct_real_world(parse_struct_entries, clear_gamedata_cache)


def _write_tmp(content, suffix=".h"):
    """Write content to a temp file and return the path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix,
                                     delete=False) as f:
        f.write(content)
        return f.name


def _test_trainer_ids(clear_cache):
    """Test load_trainer_ids, load_trainer_ids_custom, load_trainer_metadata,
    and classify_trainers."""
    from torch.gamedata import (
        load_trainer_ids, load_trainer_ids_custom,
        load_trainer_metadata, classify_trainers,
    )

    header_content = """\
#define TRAINER_NONE 0
#define TRAINER_BROCK 1
#define TRAINER_MISTY 2
#define TRAINER_SAWYER_1 854
#define TRAINER_CUSTOM_1 855
#define TRAINERS_COUNT 856
#define MAX_TRAINERS_COUNT 1024
#define TRAINER_PARTNER(x) (x | 0x100)
"""
    tmp_dir = tempfile.mkdtemp()
    try:
        # Build the expected directory structure
        inc_dir = os.path.join(tmp_dir, "include", "constants")
        os.makedirs(inc_dir)
        opp_path = os.path.join(inc_dir, "opponents.h")
        with open(opp_path, "w") as f:
            f.write(header_content)

        # --- load_trainer_ids ---
        clear_cache()
        ids = load_trainer_ids(tmp_dir)
        _assert(
            "trainer_ids: returns 4 trainers",
            len(ids) == 4,
            f"expected 4, got {len(ids)}: {ids}"
        )
        _assert(
            "trainer_ids: BROCK=1",
            ids.get("TRAINER_BROCK") == 1,
            f"got: {ids.get('TRAINER_BROCK')!r}"
        )
        _assert(
            "trainer_ids: MISTY=2",
            ids.get("TRAINER_MISTY") == 2,
            f"got: {ids.get('TRAINER_MISTY')!r}"
        )
        _assert(
            "trainer_ids: SAWYER_1=854",
            ids.get("TRAINER_SAWYER_1") == 854,
            f"got: {ids.get('TRAINER_SAWYER_1')!r}"
        )
        _assert(
            "trainer_ids: CUSTOM_1=855",
            ids.get("TRAINER_CUSTOM_1") == 855,
            f"got: {ids.get('TRAINER_CUSTOM_1')!r}"
        )
        # Meta-defines excluded
        _assert(
            "trainer_ids: TRAINERS_COUNT excluded",
            "TRAINERS_COUNT" not in ids,
            f"keys: {list(ids.keys())}"
        )
        _assert(
            "trainer_ids: MAX_TRAINERS_COUNT excluded",
            "MAX_TRAINERS_COUNT" not in ids,
            f"keys: {list(ids.keys())}"
        )
        _assert(
            "trainer_ids: TRAINER_NONE excluded",
            "TRAINER_NONE" not in ids,
            f"keys: {list(ids.keys())}"
        )
        _assert(
            "trainer_ids: TRAINER_PARTNER excluded (macro-style)",
            "TRAINER_PARTNER" not in ids,
            f"keys: {list(ids.keys())}"
        )

        # Missing file returns {}
        clear_cache()
        _assert(
            "trainer_ids: missing file returns {}",
            load_trainer_ids("/tmp/torch_nonexistent_game_dir") == {},
            "did not return {}"
        )

        # --- load_trainer_ids_custom ---
        clear_cache()
        custom = load_trainer_ids_custom(tmp_dir)
        _assert(
            "trainer_ids_custom: default threshold returns 1 trainer",
            len(custom) == 1 and "TRAINER_CUSTOM_1" in custom,
            f"got: {custom}"
        )
        _assert(
            "trainer_ids_custom: CUSTOM_1=855",
            custom.get("TRAINER_CUSTOM_1") == 855,
            f"got: {custom.get('TRAINER_CUSTOM_1')!r}"
        )

        # Custom threshold
        custom_low = load_trainer_ids_custom(tmp_dir, threshold=1)
        _assert(
            "trainer_ids_custom: threshold=1 returns 3 trainers",
            len(custom_low) == 3,
            f"expected 3, got {len(custom_low)}: {custom_low}"
        )
        _assert(
            "trainer_ids_custom: threshold=1 includes MISTY",
            "TRAINER_MISTY" in custom_low,
            f"keys: {list(custom_low.keys())}"
        )

        # --- load_trainer_metadata ---
        clear_cache()
        tc, mx = load_trainer_metadata(tmp_dir)
        _assert(
            "trainer_metadata: TRAINERS_COUNT=856",
            tc == 856,
            f"got: {tc}"
        )
        _assert(
            "trainer_metadata: MAX_TRAINERS_COUNT=1024",
            mx == 1024,
            f"got: {mx}"
        )

        # Missing file returns (0, 0)
        clear_cache()
        _assert(
            "trainer_metadata: missing file returns (0, 0)",
            load_trainer_metadata("/tmp/torch_nonexistent_game_dir") == (0, 0),
            "did not return (0, 0)"
        )

        # File without meta-defines returns (0, 0)
        clear_cache()
        no_meta_content = "#define TRAINER_BROCK 1\n"
        with open(opp_path, "w") as f:
            f.write(no_meta_content)
        _assert(
            "trainer_metadata: no meta-defines returns (0, 0)",
            load_trainer_metadata(tmp_dir) == (0, 0),
            "did not return (0, 0)"
        )

        # Restore original for classify test
        clear_cache()
        with open(opp_path, "w") as f:
            f.write(header_content)

        # --- classify_trainers ---
        clear_cache()
        vanilla, custom_c = classify_trainers(tmp_dir)
        _assert(
            "classify: vanilla has 3 trainers",
            len(vanilla) == 3,
            f"expected 3, got {len(vanilla)}: {vanilla}"
        )
        _assert(
            "classify: custom has 1 trainer",
            len(custom_c) == 1,
            f"expected 1, got {len(custom_c)}: {custom_c}"
        )
        _assert(
            "classify: vanilla contains BROCK, MISTY, SAWYER_1",
            all(k in vanilla for k in ("TRAINER_BROCK", "TRAINER_MISTY", "TRAINER_SAWYER_1")),
            f"vanilla keys: {list(vanilla.keys())}"
        )
        _assert(
            "classify: custom contains CUSTOM_1",
            "TRAINER_CUSTOM_1" in custom_c and custom_c["TRAINER_CUSTOM_1"] == 855,
            f"custom: {custom_c}"
        )

        # --- classify_trainers: comment-marker detection ---
        marker_content = """\
#define TRAINER_NONE 0
#define TRAINER_BROCK 1
#define TRAINER_MISTY 2
// Custom Seihoku trainers
#define TRAINER_ROCKET_BUSTER_1 3
#define TRAINERS_COUNT 4
"""
        clear_cache()
        with open(opp_path, "w") as f:
            f.write(marker_content)
        vanilla_m, custom_m = classify_trainers(tmp_dir)
        _assert(
            "classify marker: vanilla has 2 (BROCK, MISTY)",
            len(vanilla_m) == 2,
            f"expected 2, got {len(vanilla_m)}: {vanilla_m}"
        )
        _assert(
            "classify marker: custom has 1 (ROCKET_BUSTER_1)",
            len(custom_m) == 1 and "TRAINER_ROCKET_BUSTER_1" in custom_m,
            f"custom: {custom_m}"
        )
        _assert(
            "classify marker: custom ID=3 (below old threshold)",
            custom_m.get("TRAINER_ROCKET_BUSTER_1") == 3,
            f"got: {custom_m.get('TRAINER_ROCKET_BUSTER_1')!r}"
        )

        # Restore original for remaining tests
        clear_cache()
        with open(opp_path, "w") as f:
            f.write(header_content)

        # --- Caching ---
        clear_cache()
        ids1 = load_trainer_ids(tmp_dir)
        ids2 = load_trainer_ids(tmp_dir)
        _assert(
            "trainer_ids: caching returns same object",
            ids1 is ids2,
            "second call returned different object"
        )
        clear_cache()
        ids3 = load_trainer_ids(tmp_dir)
        _assert(
            "trainer_ids: after clear_cache returns fresh object",
            ids3 is not ids1,
            "returned same object after cache clear"
        )

    except Exception as e:
        _fail("trainer_ids suite raised", str(e))
    finally:
        import shutil
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass
        clear_cache()


def _test_struct_entries(parse_struct_entries, parse_struct_entry,
                          clear_cache):
    """Test parse_struct_entries and parse_struct_entry."""
    species_data = """\
const struct SpeciesInfo gSpeciesInfo[] = {
    [SPECIES_BULBASAUR] = {
        .baseHP = 45,
        .baseAttack = 49,
        .type1 = TYPE_GRASS,
        .type2 = TYPE_POISON,
        .genderRatio = PERCENT_FEMALE(12.5),
        .abilities = { ABILITY_OVERGROW, ABILITY_NONE, ABILITY_CHLOROPHYLL },
        .bodyColor = BODY_COLOR_GREEN,
        .noFlip = FALSE,
        .speciesName = _("Bulbasaur"),
    },
    [SPECIES_IVYSAUR] = {
        .baseHP = 60,
        .baseAttack = 62,
        .type1 = TYPE_GRASS,
        .type2 = TYPE_POISON,
    },
    [TRAINER_SAWYER_1] = {
        .trainerName = _("SAWYER"),
        .trainerClass = TRAINER_CLASS_HIKER,
    },
};
"""
    path = _write_tmp(species_data)
    try:
        clear_cache()

        # All entries returned
        all_entries = parse_struct_entries(path)
        _assert(
            "struct_entries: returns 3 entries",
            len(all_entries) == 3,
            f"expected 3, got {len(all_entries)}: {list(all_entries.keys())}"
        )

        # Correct field values
        bulba = all_entries.get("SPECIES_BULBASAUR", {})
        _assert(
            "struct_entries: baseHP is '45'",
            bulba.get("baseHP") == "45",
            f"got: {bulba.get('baseHP')!r}"
        )
        _assert(
            "struct_entries: type1 is 'TYPE_GRASS'",
            bulba.get("type1") == "TYPE_GRASS",
            f"got: {bulba.get('type1')!r}"
        )

        # Macro value preserved as-is
        _assert(
            "struct_entries: genderRatio macro preserved",
            bulba.get("genderRatio") == "PERCENT_FEMALE(12.5)",
            f"got: {bulba.get('genderRatio')!r}"
        )

        # Nested brace value preserved
        abilities = bulba.get("abilities", "")
        _assert(
            "struct_entries: nested brace value preserved",
            "ABILITY_OVERGROW" in abilities and abilities.startswith("{"),
            f"got: {abilities!r}"
        )

        # String macro preserved
        _assert(
            "struct_entries: string macro _() preserved",
            bulba.get("speciesName") == '_("Bulbasaur")',
            f"got: {bulba.get('speciesName')!r}"
        )

        # index_prefix filtering
        clear_cache()
        species_only = parse_struct_entries(path, index_prefix="SPECIES_")
        _assert(
            "struct_entries: prefix filter returns 2 SPECIES_ entries",
            len(species_only) == 2,
            f"expected 2, got {len(species_only)}: {list(species_only.keys())}"
        )
        _assert(
            "struct_entries: prefix filter excludes TRAINER_",
            "TRAINER_SAWYER_1" not in species_only,
            f"keys: {list(species_only.keys())}"
        )

        # Missing file returns {}
        clear_cache()
        _assert(
            "struct_entries: missing file returns {}",
            parse_struct_entries("/tmp/torch_nonexistent_struct.h") == {},
            "did not return {}"
        )

        # File with no matching entries
        clear_cache()
        empty_path = _write_tmp("int x = 5;\n")
        try:
            _assert(
                "struct_entries: no entries returns {}",
                parse_struct_entries(empty_path) == {},
                "did not return {}"
            )
        finally:
            os.unlink(empty_path)

        # parse_struct_entry single lookup
        clear_cache()
        single = parse_struct_entry(path, "SPECIES_IVYSAUR")
        _assert(
            "struct_entry: returns dict for existing entry",
            isinstance(single, dict) and single.get("baseHP") == "60",
            f"got: {single!r}"
        )
        _assert(
            "struct_entry: returns None for non-existent entry",
            parse_struct_entry(path, "SPECIES_CHARMANDER") is None,
            "did not return None"
        )

    except Exception as e:
        _fail("struct_entries tests raised", str(e))
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
        clear_cache()


def _test_unnamed_struct_array(parse_unnamed_struct_array, clear_cache):
    """Test parse_unnamed_struct_array."""
    party_data = """\
static const struct TrainerMon gTrainerParty_Sawyer1[] = {
    {
        .species = SPECIES_GEODUDE,
        .lvl = 21,
        .moves = {MOVE_ROCK_THROW, MOVE_CURSE, MOVE_NONE, MOVE_NONE},
    },
    {
        .species = SPECIES_ONIX,
        .lvl = 23,
        .iv = TRAINER_PARTY_IVS(0, 0, 0, 0, 0, 0),
    },
};
"""
    path = _write_tmp(party_data)
    try:
        clear_cache()
        result = parse_unnamed_struct_array(path, "gTrainerParty_Sawyer1")
        _assert(
            "unnamed_array: returns 2 elements",
            len(result) == 2,
            f"expected 2, got {len(result)}"
        )
        _assert(
            "unnamed_array: first element species",
            result[0].get("species") == "SPECIES_GEODUDE",
            f"got: {result[0].get('species')!r}"
        )
        _assert(
            "unnamed_array: first element lvl",
            result[0].get("lvl") == "21",
            f"got: {result[0].get('lvl')!r}"
        )
        moves = result[0].get("moves", "")
        _assert(
            "unnamed_array: nested moves brace preserved",
            "MOVE_ROCK_THROW" in moves and moves.startswith("{"),
            f"got: {moves!r}"
        )
        _assert(
            "unnamed_array: second element species",
            result[1].get("species") == "SPECIES_ONIX",
            f"got: {result[1].get('species')!r}"
        )
        _assert(
            "unnamed_array: macro value preserved",
            result[1].get("iv") == "TRAINER_PARTY_IVS(0, 0, 0, 0, 0, 0)",
            f"got: {result[1].get('iv')!r}"
        )

        # Missing file returns []
        clear_cache()
        _assert(
            "unnamed_array: missing file returns []",
            parse_unnamed_struct_array("/tmp/torch_nonexistent.h", "x") == [],
            "did not return []"
        )

        # Non-existent array name returns []
        clear_cache()
        _assert(
            "unnamed_array: wrong array name returns []",
            parse_unnamed_struct_array(path, "gNonExistent") == [],
            "did not return []"
        )

    except Exception as e:
        _fail("unnamed_array tests raised", str(e))
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
        clear_cache()


def _test_extract_field_value(extract_field_value):
    """Test extract_field_value helper."""
    # Unwrap string macro
    _assert(
        "extract_field: unwrap _() string macro",
        extract_field_value('_("SAWYER")', unwrap_macro="_") == "SAWYER",
        f"got: {extract_field_value('_(' + '\"SAWYER\")', unwrap_macro='_')!r}"
    )

    # Unwrap numeric macro
    _assert(
        "extract_field: unwrap PERCENT_FEMALE macro",
        extract_field_value('PERCENT_FEMALE(12.5)',
                            unwrap_macro="PERCENT_FEMALE") == "12.5",
        f"got: {extract_field_value('PERCENT_FEMALE(12.5)', unwrap_macro='PERCENT_FEMALE')!r}"
    )

    # Brace list without unwrap returns as-is (stripped)
    brace_val = "{ MOVE_A, MOVE_B }"
    _assert(
        "extract_field: brace list returned as-is",
        extract_field_value(brace_val) == brace_val,
        f"got: {extract_field_value(brace_val)!r}"
    )

    # Simple value
    _assert(
        "extract_field: simple value stripped",
        extract_field_value("  45  ") == "45",
        f"got: {extract_field_value('  45  ')!r}"
    )

    # Macro that doesn't match unwrap_macro is returned as-is
    _assert(
        "extract_field: non-matching macro returned as-is",
        extract_field_value("PERCENT_FEMALE(12.5)",
                            unwrap_macro="OTHER") == "PERCENT_FEMALE(12.5)",
        f"got: {extract_field_value('PERCENT_FEMALE(12.5)', unwrap_macro='OTHER')!r}"
    )


def _test_struct_comments(parse_struct_entries, clear_cache):
    """Test that C comments are stripped from parsed values."""
    data_with_comments = """\
const struct Foo gFoo[] = {
    [FOO_ALPHA] = {
        .val1 = 10, // this is a comment
        .val2 = TYPE_GRASS, /* block comment */
        .val3 = 30,
        /* this whole line is a comment */
        .val4 = 40,
    },
};
"""
    path = _write_tmp(data_with_comments)
    try:
        clear_cache()
        entries = parse_struct_entries(path)
        alpha = entries.get("FOO_ALPHA", {})
        _assert(
            "comments: line comment stripped from val1",
            alpha.get("val1") == "10",
            f"got: {alpha.get('val1')!r}"
        )
        _assert(
            "comments: block comment stripped from val2",
            alpha.get("val2") == "TYPE_GRASS",
            f"got: {alpha.get('val2')!r}"
        )
        _assert(
            "comments: val3 unaffected",
            alpha.get("val3") == "30",
            f"got: {alpha.get('val3')!r}"
        )
        _assert(
            "comments: val4 after block comment line",
            alpha.get("val4") == "40",
            f"got: {alpha.get('val4')!r}"
        )
    except Exception as e:
        _fail("comments tests raised", str(e))
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
        clear_cache()


def _test_struct_caching(parse_struct_entries, clear_cache):
    """Test that caching works correctly."""
    data_v1 = """\
const struct X gX[] = {
    [X_ALPHA] = {
        .val = 100,
    },
};
"""
    data_v2 = """\
const struct X gX[] = {
    [X_ALPHA] = {
        .val = 999,
    },
};
"""
    path = _write_tmp(data_v1)
    try:
        clear_cache()
        result1 = parse_struct_entries(path)
        _assert(
            "caching: first read gets val=100",
            result1.get("X_ALPHA", {}).get("val") == "100",
            f"got: {result1!r}"
        )

        # Overwrite file, should still get cached result
        with open(path, "w") as f:
            f.write(data_v2)
        result2 = parse_struct_entries(path)
        _assert(
            "caching: second read returns cached val=100",
            result2.get("X_ALPHA", {}).get("val") == "100",
            f"got: {result2!r}"
        )

        # Clear cache, should get new result
        clear_cache()
        result3 = parse_struct_entries(path)
        _assert(
            "caching: after clear gets val=999",
            result3.get("X_ALPHA", {}).get("val") == "999",
            f"got: {result3!r}"
        )
    except Exception as e:
        _fail("caching tests raised", str(e))
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
        clear_cache()


def _test_struct_real_world(parse_struct_entries, clear_cache):
    """Test with patterns from real pokeemerald-expansion data."""
    # Real species data pattern (with #if, COMPOUND_STRING, ternary, etc.)
    real_species = """\
#if P_FAMILY_BULBASAUR
    [SPECIES_BULBASAUR] =
    {
        .baseHP        = 45,
        .baseAttack    = 49,
        .types = MON_TYPES(TYPE_GRASS, TYPE_POISON),
        .expYield = (P_UPDATED_EXP_YIELDS >= GEN_5) ? 64 : 63,
        .genderRatio = PERCENT_FEMALE(12.5),
        .abilities = { ABILITY_OVERGROW, ABILITY_NONE, ABILITY_CHLOROPHYLL },
        .speciesName = _("Bulbasaur"),
        .description = COMPOUND_STRING(
            "Bulbasaur can be seen napping in bright\\n"
            "sunlight. There is a seed on its back."),
        .frontPicSize = P_GBA_STYLE_SPECIES_GFX ? MON_COORDS_SIZE(32, 40) : MON_COORDS_SIZE(40, 40),
        .evolutions = EVOLUTION({EVO_LEVEL, 16, SPECIES_IVYSAUR}),
    },
#endif
"""
    path = _write_tmp(real_species)
    try:
        clear_cache()
        entries = parse_struct_entries(path, index_prefix="SPECIES_")
        _assert(
            "real_world: Bulbasaur parsed through #if",
            "SPECIES_BULBASAUR" in entries,
            f"keys: {list(entries.keys())}"
        )
        bulba = entries.get("SPECIES_BULBASAUR", {})
        _assert(
            "real_world: baseHP correct",
            bulba.get("baseHP") == "45",
            f"got: {bulba.get('baseHP')!r}"
        )
        _assert(
            "real_world: ternary expression preserved",
            "P_UPDATED_EXP_YIELDS" in bulba.get("expYield", ""),
            f"got: {bulba.get('expYield')!r}"
        )
        _assert(
            "real_world: MON_TYPES macro preserved",
            bulba.get("types") == "MON_TYPES(TYPE_GRASS, TYPE_POISON)",
            f"got: {bulba.get('types')!r}"
        )
        _assert(
            "real_world: COMPOUND_STRING preserved",
            "COMPOUND_STRING" in bulba.get("description", ""),
            f"got: {bulba.get('description')!r}"
        )
        _assert(
            "real_world: nested EVOLUTION macro preserved",
            "EVOLUTION" in bulba.get("evolutions", ""),
            f"got: {bulba.get('evolutions')!r}"
        )
    except Exception as e:
        _fail("real_world tests raised", str(e))
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
        clear_cache()
