"""Battle Wizard tests -- Showdown parser, constant normalisation, struct emitter."""

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Battle Wizard")

    try:
        from torch.battle_wizard import (
            _to_pascal_case,
            _normalise_constant_input,
            _is_showdown_continuation,
            _parse_showdown_team,
            _emit_mon_block_lines,
        )
    except ImportError as e:
        _skip("all battle wizard tests", f"import failed: {e}")
        return

    # ==================================================================
    # A. _to_pascal_case  (~4 assertions)
    # ==================================================================

    _assert(
        "pascal_case: multi-word spaces",
        _to_pascal_case("lake elix south") == "LakeElixSouth",
        f"got {_to_pascal_case('lake elix south')!r}"
    )

    _assert(
        "pascal_case: single word",
        _to_pascal_case("petalburg") == "Petalburg",
        f"got {_to_pascal_case('petalburg')!r}"
    )

    _assert(
        "pascal_case: hyphenated input",
        _to_pascal_case("Already-Pascal") == "AlreadyPascal",
        f"got {_to_pascal_case('Already-Pascal')!r}"
    )

    _assert(
        "pascal_case: empty string",
        _to_pascal_case("") == "",
        f"got {_to_pascal_case('')!r}"
    )

    # ==================================================================
    # B. _normalise_constant_input  (~5 assertions)
    # ==================================================================

    _assert(
        "normalise: spaces to underscores + uppercase",
        _normalise_constant_input("sitrus berry", "ITEM_") == "SITRUS_BERRY",
        f"got {_normalise_constant_input('sitrus berry', 'ITEM_')!r}"
    )

    _assert(
        "normalise: strips prefix if already present",
        _normalise_constant_input("ITEM_SITRUS_BERRY", "ITEM_") == "SITRUS_BERRY",
        f"got {_normalise_constant_input('ITEM_SITRUS_BERRY', 'ITEM_')!r}"
    )

    _assert(
        "normalise: hyphens to underscores",
        _normalise_constant_input("Sitrus-Berry", "ITEM_") == "SITRUS_BERRY",
        f"got {_normalise_constant_input('Sitrus-Berry', 'ITEM_')!r}"
    )

    _assert(
        "normalise: single word species",
        _normalise_constant_input("poochyena", "SPECIES_") == "POOCHYENA",
        f"got {_normalise_constant_input('poochyena', 'SPECIES_')!r}"
    )

    _assert(
        "normalise: empty input",
        _normalise_constant_input("", "ITEM_") == "",
        f"got {_normalise_constant_input('', 'ITEM_')!r}"
    )

    # ==================================================================
    # C. _is_showdown_continuation  (~6 assertions)
    # ==================================================================

    _assert(
        "continuation: move line (- Earthquake)",
        _is_showdown_continuation("- Earthquake") is True,
        "expected True for move line"
    )

    _assert(
        "continuation: Ability line",
        _is_showdown_continuation("Ability: Intimidate") is True,
        "expected True for Ability line"
    )

    _assert(
        "continuation: EVs line",
        _is_showdown_continuation("EVs: 252 Atk / 4 SpD / 252 Spe") is True,
        "expected True for EVs line"
    )

    _assert(
        "continuation: IVs line",
        _is_showdown_continuation("IVs: 0 Atk") is True,
        "expected True for IVs line"
    )

    _assert(
        "continuation: Nature line",
        _is_showdown_continuation("Adamant Nature") is True,
        "expected True for Nature line"
    )

    _assert(
        "continuation: new pokemon header returns False",
        _is_showdown_continuation("Tyranitar (M) @ Choice Band") is False,
        "expected False for new pokemon header"
    )

    # ==================================================================
    # D. _parse_showdown_team  (~8 assertions)
    # ==================================================================

    single_mon_text = """\
Tyranitar (M) @ Choice Band
Ability: Sand Stream
EVs: 252 Atk / 4 SpD / 252 Spe
Adamant Nature
- Stone Edge
- Crunch
- Earthquake
- Fire Punch"""

    # Pass empty sets = no validation, accept everything
    team = _parse_showdown_team(single_mon_text, set(), set(), set(), set())

    _assert(
        "showdown: single mon returns list of 1",
        len(team) == 1,
        f"got {len(team)} mons"
    )

    mon = team[0]

    _assert(
        "showdown: species is SPECIES_TYRANITAR",
        mon["species"] == "SPECIES_TYRANITAR",
        f"got {mon['species']!r}"
    )

    _assert(
        "showdown: held_item is ITEM_CHOICE_BAND",
        mon["held_item"] == "ITEM_CHOICE_BAND",
        f"got {mon['held_item']!r}"
    )

    _assert(
        "showdown: 4 moves parsed",
        len(mon["moves"]) == 4,
        f"got {len(mon['moves'])} moves: {mon['moves']}"
    )

    _assert(
        "showdown: nature is NATURE_ADAMANT",
        mon["nature"] == "NATURE_ADAMANT",
        f"got {mon['nature']!r}"
    )

    _assert(
        "showdown: EVs parsed correctly (atk=252, spe=252)",
        mon.get("evs") == {"atk": 252, "spdef": 4, "spe": 252},
        f"got {mon.get('evs')!r}"
    )

    _assert(
        "showdown: gender is male",
        mon["gender"] == "male",
        f"got {mon['gender']!r}"
    )

    # Multi-mon team
    two_mon_text = """\
Tyranitar (M) @ Choice Band
Ability: Sand Stream
Adamant Nature
- Stone Edge
- Crunch
- Earthquake
- Fire Punch

Salamence (F) @ Life Orb
Ability: Intimidate
Jolly Nature
- Dragon Dance
- Outrage
- Earthquake
- Fire Fang"""

    team2 = _parse_showdown_team(two_mon_text, set(), set(), set(), set())

    _assert(
        "showdown: two mons parsed from multi-block text",
        len(team2) == 2,
        f"got {len(team2)} mons"
    )

    # ==================================================================
    # E. _emit_mon_block_lines  (~3 assertions)
    # ==================================================================

    test_mon = {
        "species": "SPECIES_TYRANITAR",
        "level": 50,
        "held_item": "ITEM_CHOICE_BAND",
        "moves": ["MOVE_STONE_EDGE", "MOVE_CRUNCH"],
        "ability": "ABILITY_SAND_STREAM",
        "nature": "NATURE_ADAMANT",
        "gender": "male",
    }

    lines_not_last = _emit_mon_block_lines(test_mon, is_last=False)
    lines_last = _emit_mon_block_lines(test_mon, is_last=True)

    _assert(
        "emit_mon: returns list of strings",
        isinstance(lines_not_last, list) and all(isinstance(l, str) for l in lines_not_last),
        f"got {type(lines_not_last).__name__}"
    )

    joined = "".join(lines_not_last)
    _assert(
        "emit_mon: output contains species constant",
        "SPECIES_TYRANITAR" in joined,
        f"species not found in output"
    )

    # is_last=False should end with "},\n", is_last=True with "    }\n"
    last_line_not_last = lines_not_last[-1]
    last_line_last = lines_last[-1]
    _assert(
        "emit_mon: is_last=True vs False differ in closing",
        last_line_not_last.strip() == "}," and last_line_last.strip() == "}",
        f"not_last ends with {last_line_not_last!r}, last ends with {last_line_last!r}"
    )
