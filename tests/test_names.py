"""Names suite -- C constant to human-readable conversions."""
from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Names")

    try:
        from torch.names import (
            _parse_stat_spread, _format_stat_spread,
            _const_to_human_name, _human_name_to_const,
            _const_to_species_name, _const_to_move_name,
            _ai_flags_to_party_format,
        )
    except ImportError as e:
        _skip("all names tests", f"import failed: {e}")
        return

    # -- Test 1: _parse_stat_spread basic --
    try:
        result = _parse_stat_spread("252 HP / 128 Spe")
        _assert(
            "_parse_stat_spread: '252 HP / 128 Spe'",
            result == {"hp": 252, "spe": 128},
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("_parse_stat_spread basic", str(e))

    # -- Test 2: _format_stat_spread basic --
    try:
        result = _format_stat_spread({"hp": 252, "spe": 128})
        _assert(
            "_format_stat_spread: hp=252, spe=128",
            result == "252 HP / 128 Spe",
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("_format_stat_spread basic", str(e))

    # -- Test 3: parse + format round-trip with all 6 stats --
    try:
        all_stats = {"hp": 252, "atk": 100, "def": 50, "spatk": 200, "spdef": 80, "spe": 128}
        formatted = _format_stat_spread(all_stats)
        parsed = _parse_stat_spread(formatted)
        _assert(
            "stat spread round-trip (all 6 stats)",
            parsed == all_stats,
            f"formatted={formatted!r}, parsed back={parsed!r}"
        )
    except Exception as e:
        _fail("stat spread round-trip", str(e))

    # -- Test 4: _const_to_human_name --
    try:
        result = _const_to_human_name("TRAINER_CLASS_TEAM_ROCKET", "TRAINER_CLASS_")
        _assert(
            "_const_to_human_name: TRAINER_CLASS_TEAM_ROCKET",
            result == "Team Rocket",
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("_const_to_human_name", str(e))

    # -- Test 5: _human_name_to_const --
    try:
        result = _human_name_to_const("Team Rocket", "TRAINER_CLASS_")
        _assert(
            "_human_name_to_const: 'Team Rocket'",
            result == "TRAINER_CLASS_TEAM_ROCKET",
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("_human_name_to_const", str(e))

    # -- Test 6: const<->human round-trip --
    try:
        original = "TRAINER_CLASS_TEAM_ROCKET"
        prefix = "TRAINER_CLASS_"
        human = _const_to_human_name(original, prefix)
        back = _human_name_to_const(human, prefix)
        _assert(
            "const<->human round-trip",
            back == original,
            f"original={original!r}, human={human!r}, back={back!r}"
        )
    except Exception as e:
        _fail("const<->human round-trip", str(e))

    # -- Test 7: _const_to_species_name basic --
    try:
        result = _const_to_species_name("SPECIES_GEODUDE")
        _assert(
            "_const_to_species_name: SPECIES_GEODUDE -> 'Geodude'",
            result == "Geodude",
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("_const_to_species_name basic", str(e))

    # -- Test 8: _const_to_species_name Mr. Mime special case --
    try:
        result = _const_to_species_name("SPECIES_MR_MIME")
        _assert(
            "_const_to_species_name: SPECIES_MR_MIME contains 'Mr.'",
            "Mr." in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("_const_to_species_name Mr. Mime", str(e))

    # -- Test 9: _const_to_move_name --
    try:
        result = _const_to_move_name("MOVE_AIR_SLASH")
        _assert(
            "_const_to_move_name: MOVE_AIR_SLASH -> 'Air Slash'",
            result == "Air Slash",
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("_const_to_move_name", str(e))

    # -- Test 10: _ai_flags_to_party_format --
    try:
        result = _ai_flags_to_party_format("AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT")
        _assert(
            "_ai_flags_to_party_format: two flags",
            "Check Bad Move" in result and "Try To Faint" in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("_ai_flags_to_party_format", str(e))

    # -- Test 11: _const_to_human_name preserves acronyms --
    try:
        result = _const_to_human_name("TRAINER_CLASS_RS_GRUNT", "TRAINER_CLASS_")
        _assert(
            "_const_to_human_name: RS_GRUNT -> 'RS Grunt' (acronym preserved)",
            result == "RS Grunt",
            "got: %r" % result
        )
    except Exception as e:
        _fail("_const_to_human_name acronym", str(e))

    # -- Test 12: _ai_flags_to_party_format preserves acronyms --
    try:
        result = _ai_flags_to_party_format("AI_FLAG_HP_AWARE")
        _assert(
            "_ai_flags_to_party_format: HP_AWARE -> 'HP Aware' (acronym preserved)",
            result == "HP Aware",
            "got: %r" % result
        )
    except Exception as e:
        _fail("_ai_flags_to_party_format acronym", str(e))

    # -- Test 13: empty string edge cases --
    try:
        _assert(
            "_const_to_human_name: empty -> ''",
            _const_to_human_name("", "PREFIX_") == "",
            f"got: {_const_to_human_name('', 'PREFIX_')!r}"
        )
        _assert(
            "_human_name_to_const: empty -> ''",
            _human_name_to_const("", "PREFIX_") == "",
            f"got: {_human_name_to_const('', 'PREFIX_')!r}"
        )
        _assert(
            "_const_to_species_name: empty -> ''",
            _const_to_species_name("") == "",
            f"got: {_const_to_species_name('')!r}"
        )
        _assert(
            "_const_to_move_name: empty -> ''",
            _const_to_move_name("") == "",
            f"got: {_const_to_move_name('')!r}"
        )
    except Exception as e:
        _fail("empty string edge cases", str(e))
