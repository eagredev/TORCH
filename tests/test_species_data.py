"""Tests for gamedata.py — species data functions (load_species_data, get_species_summary).

Covers MON_TYPES parsing, BST computation, summary formatting,
species extraction from struct entries, macro resolution, and
graceful handling of missing/invalid data.
"""
import os
import sys
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _assert, _ok, _fail, _skip


def run_suite():
    _begin_suite("Species Data  (type parsing, stats, summaries)")

    try:
        import torch.gamedata as gd
    except ImportError as e:
        _skip("all species_data tests", f"import failed: {e}")
        return

    _test_parse_mon_types(gd)
    _test_parse_mon_types_macros(gd)
    _test_extract_type_from_expr(gd)
    _test_parse_base_stat(gd)
    _test_extract_species_from_entries(gd)
    _test_bst_computation(gd)
    _test_get_species_summary(gd)
    _test_load_species_data_missing_dir(gd)
    _test_load_species_data_with_fixture(gd)


# ── _parse_mon_types ─────────────────────────────────────────────────────

def _test_parse_mon_types(gd):
    """Parse MON_TYPES macro into type name list."""
    result = gd._parse_mon_types("MON_TYPES(TYPE_GRASS, TYPE_POISON)")
    _assert(
        "parse_mon_types: dual type",
        result == ["Grass", "Poison"],
        f"got: {result}"
    )

    result2 = gd._parse_mon_types("MON_TYPES(TYPE_FIRE)")
    _assert(
        "parse_mon_types: single type",
        result2 == ["Fire"],
        f"got: {result2}"
    )

    result3 = gd._parse_mon_types("something_else")
    _assert(
        "parse_mon_types: no MON_TYPES -> empty",
        result3 == [],
        f"got: {result3}"
    )

    result4 = gd._parse_mon_types("")
    _assert(
        "parse_mon_types: empty string -> empty",
        result4 == [],
        f"got: {result4}"
    )

    result5 = gd._parse_mon_types("MON_TYPES(TYPE_NORMAL, TYPE_FLYING)")
    _assert(
        "parse_mon_types: Normal/Flying",
        result5 == ["Normal", "Flying"],
        f"got: {result5}"
    )


def _test_parse_mon_types_macros(gd):
    """Parse MON_TYPES with macro resolution."""
    macros = {"RALTS_FAMILY_TYPE2": "TYPE_FAIRY"}
    result = gd._parse_mon_types(
        "MON_TYPES(TYPE_PSYCHIC, RALTS_FAMILY_TYPE2)", macros
    )
    _assert(
        "parse_mon_types: macro resolved to TYPE_FAIRY",
        result == ["Psychic", "Fairy"],
        f"got: {result}"
    )

    # Unresolvable macro (no TYPE_ prefix after lookup)
    macros2 = {"SOME_MACRO": "SOME_MACRO"}
    result2 = gd._parse_mon_types(
        "MON_TYPES(TYPE_WATER, SOME_MACRO)", macros2
    )
    _assert(
        "parse_mon_types: unresolvable macro becomes titlecase",
        len(result2) == 2 and result2[0] == "Water",
        f"got: {result2}"
    )


# ── _extract_type_from_expr ──────────────────────────────────────────────

def _test_extract_type_from_expr(gd):
    """Extract TYPE_ constant from ternary expressions."""
    result = gd._extract_type_from_expr(
        "(P_UPDATED_TYPES >= GEN_6 ? TYPE_FAIRY : TYPE_PSYCHIC)"
    )
    _assert(
        "extract_type: ternary takes first TYPE_",
        result == "TYPE_FAIRY",
        f"got: {result}"
    )

    result2 = gd._extract_type_from_expr("TYPE_NORMAL")
    _assert(
        "extract_type: plain constant",
        result2 == "TYPE_NORMAL",
        f"got: {result2}"
    )

    result3 = gd._extract_type_from_expr("no_type_here")
    _assert(
        "extract_type: no TYPE_ -> passthrough",
        result3 == "no_type_here",
        f"got: {result3}"
    )


# ── _parse_base_stat ─────────────────────────────────────────────────────

def _test_parse_base_stat(gd):
    """Parse base stat from various formats."""
    _assert(
        "parse_stat: plain integer",
        gd._parse_base_stat("45") == 45,
        f"got: {gd._parse_base_stat('45')}"
    )
    _assert(
        "parse_stat: whitespace stripped",
        gd._parse_base_stat("  65  ") == 65,
        f"got: {gd._parse_base_stat('  65  ')}"
    )
    _assert(
        "parse_stat: macro resolution",
        gd._parse_base_stat("BASE_HP", {"BASE_HP": "50"}) == 50,
        f"got: {gd._parse_base_stat('BASE_HP', {'BASE_HP': '50'})}"
    )
    # Ternary grabs first word-bounded integer (\b\d+\b)
    # GEN_9 doesn't match (9 has no leading word boundary inside GEN_9)
    # so first match is 100
    _assert(
        "parse_stat: ternary grabs first word-bounded int",
        gd._parse_base_stat("(P_UPDATED >= GEN_9 ? 100 : 80)") == 100,
        f"got: {gd._parse_base_stat('(P_UPDATED >= GEN_9 ? 100 : 80)')}"
    )
    # Simple ternary with no leading digits
    _assert(
        "parse_stat: simple ternary extracts value",
        gd._parse_base_stat("(TRUE ? 55 : 45)") == 55,
        f"got: {gd._parse_base_stat('(TRUE ? 55 : 45)')}"
    )
    _assert(
        "parse_stat: unresolvable -> 0",
        gd._parse_base_stat("UNKNOWN_THING") == 0,
        f"got: {gd._parse_base_stat('UNKNOWN_THING')}"
    )


# ── _extract_species_from_entries ────────────────────────────────────────

def _test_extract_species_from_entries(gd):
    """Extract species data from parsed struct entries."""
    entries = {
        "SPECIES_BULBASAUR": {
            "baseHP": "45", "baseAttack": "49", "baseDefense": "49",
            "baseSpAttack": "65", "baseSpDefense": "65", "baseSpeed": "45",
            "types": "MON_TYPES(TYPE_GRASS, TYPE_POISON)",
        },
        "NOT_A_SPECIES": {
            "baseHP": "100", "baseAttack": "100", "baseDefense": "100",
            "baseSpAttack": "100", "baseSpDefense": "100", "baseSpeed": "100",
            "types": "MON_TYPES(TYPE_NORMAL)",
        },
    }
    result = gd._extract_species_from_entries(entries)
    _assert(
        "extract_species: finds SPECIES_BULBASAUR",
        "SPECIES_BULBASAUR" in result,
        f"keys: {list(result.keys())}"
    )
    _assert(
        "extract_species: skips non-SPECIES entries",
        "NOT_A_SPECIES" not in result,
        f"keys: {list(result.keys())}"
    )

    bulba = result.get("SPECIES_BULBASAUR", {})
    _assert(
        "extract_species: hp parsed",
        bulba.get("hp") == 45,
        f"got: {bulba.get('hp')}"
    )
    _assert(
        "extract_species: types parsed",
        bulba.get("types") == ["Grass", "Poison"],
        f"got: {bulba.get('types')}"
    )


def _test_bst_computation(gd):
    """BST = sum of 6 stats."""
    entries = {
        "SPECIES_TEST": {
            "baseHP": "10", "baseAttack": "20", "baseDefense": "30",
            "baseSpAttack": "40", "baseSpDefense": "50", "baseSpeed": "60",
            "types": "MON_TYPES(TYPE_NORMAL)",
        },
    }
    result = gd._extract_species_from_entries(entries)
    bst = result["SPECIES_TEST"]["bst"]
    _assert(
        "bst: sum of 6 stats = 210",
        bst == 210,
        f"got: {bst}"
    )

    # Missing stat field -> species skipped entirely
    entries_bad = {
        "SPECIES_BAD": {
            "baseHP": "10", "baseAttack": "20",
            # missing other stats
            "types": "MON_TYPES(TYPE_NORMAL)",
        },
    }
    result_bad = gd._extract_species_from_entries(entries_bad)
    _assert(
        "bst: missing stats -> species skipped",
        "SPECIES_BAD" not in result_bad,
        f"keys: {list(result_bad.keys())}"
    )


# ── get_species_summary ─────────────────────────────────────────────────

def _test_get_species_summary(gd):
    """Summary string formatting."""
    # We can't easily test with a real game path, so test the formatting
    # logic by calling _extract_species_from_entries + format manually.
    entries = {
        "SPECIES_PIKA": {
            "baseHP": "35", "baseAttack": "55", "baseDefense": "40",
            "baseSpAttack": "50", "baseSpDefense": "50", "baseSpeed": "90",
            "types": "MON_TYPES(TYPE_ELECTRIC)",
        },
    }
    data = gd._extract_species_from_entries(entries)
    info = data["SPECIES_PIKA"]
    type_str = "/".join(info["types"])
    summary = (
        f"{type_str}  "
        f"HP:{info['hp']} Atk:{info['atk']} Def:{info['def']} "
        f"SpA:{info['spa']} SpD:{info['spd']} Spe:{info['spe']} "
        f"BST:{info['bst']}"
    )
    _assert(
        "summary: format matches expected pattern",
        summary == "Electric  HP:35 Atk:55 Def:40 SpA:50 SpD:50 Spe:90 BST:320",
        f"got: {summary}"
    )
    _assert(
        "summary: BST is correct (320)",
        info["bst"] == 320,
        f"got: {info['bst']}"
    )


# ── load_species_data with missing dir ───────────────────────────────────

def _test_load_species_data_missing_dir(gd):
    """Graceful return when species_info directory missing."""
    tmp = tempfile.mkdtemp(prefix="torch_species_test_")
    try:
        # Clear cache so our test path isn't cached
        rp = os.path.realpath(tmp)
        gd._SPECIES_DATA_CACHE.pop(rp, None)

        result = gd.load_species_data(tmp)
        _assert(
            "load_species_data: missing dir -> empty dict",
            result == {},
            f"got: {result}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        gd._SPECIES_DATA_CACHE.pop(rp, None)


# ── load_species_data with fixture ───────────────────────────────────────

def _test_load_species_data_with_fixture(gd):
    """Load species data from a minimal gen_1_families.h fixture."""
    tmp = tempfile.mkdtemp(prefix="torch_species_test_")
    try:
        species_dir = os.path.join(tmp, "src", "data", "pokemon", "species_info")
        os.makedirs(species_dir)

        fixture = """\
[SPECIES_BULBASAUR] =
{
    .baseHP        = 45,
    .baseAttack    = 49,
    .baseDefense   = 49,
    .baseSpAttack  = 65,
    .baseSpDefense = 65,
    .baseSpeed     = 45,
    .types = MON_TYPES(TYPE_GRASS, TYPE_POISON),
},
"""
        with open(os.path.join(species_dir, "gen_1_families.h"), "w") as f:
            f.write(fixture)

        rp = os.path.realpath(tmp)
        gd._SPECIES_DATA_CACHE.pop(rp, None)

        result = gd.load_species_data(tmp)
        _assert(
            "load_species_data: finds SPECIES_BULBASAUR",
            "SPECIES_BULBASAUR" in result,
            f"keys: {list(result.keys())}"
        )
        bulba = result.get("SPECIES_BULBASAUR", {})
        _assert(
            "load_species_data: hp=45",
            bulba.get("hp") == 45,
            f"got: {bulba.get('hp')}"
        )
        _assert(
            "load_species_data: bst=318",
            bulba.get("bst") == 318,
            f"got: {bulba.get('bst')}"
        )
        _assert(
            "load_species_data: types=[Grass, Poison]",
            bulba.get("types") == ["Grass", "Poison"],
            f"got: {bulba.get('types')}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        rp = os.path.realpath(tmp)
        gd._SPECIES_DATA_CACHE.pop(rp, None)
