"""Tests for Dex — extended species parser (gamedata.py) and UI logic (dex.py).

Covers:
  - load_species_data extended fields (abilities, catch_rate, egg_groups,
    gender_ratio, growth_rate, evs, name, category, height, weight,
    evolutions, is_mega, is_gmax)
  - Learnset loaders (level-up, teachable, egg moves)
  - Name resolvers (move names, ability names)
  - Dex filter logic (_filter_species and sub-filters)
  - Form folding (_build_folded_list)
  - Form label extraction (_form_label)
  - Name jump

Tests run against a real game project if TORCH_TEST_GAME_PATH is set,
or ~/Documents/pokemon-seihoku exists. All tests are skipped gracefully
if the game path is unavailable.
"""
import os

from torch.tests.harness import _begin_suite, _assert, _ok, _fail, _skip

GAME_PATH = os.environ.get(
    "TORCH_TEST_GAME_PATH",
    os.path.expanduser("~/Documents/pokemon-seihoku")
)


def run_suite():
    _begin_suite("Dex  (species data browser)")

    # Gate: check game path exists
    if not os.path.isdir(GAME_PATH):
        _skip("all dex tests", f"game path not found: {GAME_PATH}")
        return

    species_dir = os.path.join(GAME_PATH, "src", "data", "pokemon", "species_info")
    if not os.path.isdir(species_dir):
        _skip("all dex tests", "species_info directory not found")
        return

    # Import modules
    try:
        from torch.gamedata import (
            load_species_data, load_level_up_learnset,
            load_teachable_learnset, load_egg_moves,
            load_move_names, load_ability_names,
            load_form_tables,
        )
    except ImportError as e:
        _skip("all dex tests", f"gamedata import failed: {e}")
        return

    try:
        from torch.dex import (
            _filter_species, _build_folded_list, _form_label,
            _build_species_order, _name_or_dex_jump,
            _build_evolution_chain, _evo_arrow,
        )
    except ImportError as e:
        _skip("all filter tests", f"dex import failed: {e}")
        # Still run gamedata tests
        _test_species_data(GAME_PATH, load_species_data)
        _test_learnsets(GAME_PATH, load_level_up_learnset,
                        load_teachable_learnset, load_egg_moves)
        _test_name_resolvers(GAME_PATH, load_move_names, load_ability_names)
        return

    # Load species data once for all tests
    data = load_species_data(GAME_PATH)
    if not data:
        _skip("all dex tests", "load_species_data returned empty dict")
        return

    _test_species_data(GAME_PATH, load_species_data, data)
    _test_learnsets(GAME_PATH, load_level_up_learnset,
                    load_teachable_learnset, load_egg_moves)
    _test_name_resolvers(GAME_PATH, load_move_names, load_ability_names)
    _test_filters(data, _filter_species)

    # New tests: form folding, form labels, name jump
    form_tables = load_form_tables(GAME_PATH)
    species_order = _build_species_order(GAME_PATH, data)
    _test_form_folding(species_order, form_tables, data, _build_folded_list)
    _test_form_labels(_form_label)
    _test_name_or_dex_jump(species_order, form_tables, _build_folded_list, _name_or_dex_jump)
    _test_evolution_chains(species_order, data, _build_evolution_chain,
                           _evo_arrow)
    _test_show_species_card(GAME_PATH)


# ---------------------------------------------------------------------------
# A. Extended Species Data
# ---------------------------------------------------------------------------

def _test_species_data(gp, load_fn, data=None):
    """Tests 1-14: species data fields and correctness."""
    if data is None:
        data = load_fn(gp)

    # 1. Non-empty dict
    _assert("species data is non-empty",
            len(data) > 0,
            f"got {len(data)} entries")

    # 2-9: Bulbasaur field checks
    bulba = data.get("SPECIES_BULBASAUR")
    if not bulba:
        _skip("bulbasaur field checks (2-9)", "SPECIES_BULBASAUR not found")
    else:
        # 2. All expected fields
        expected_fields = [
            "hp", "atk", "def", "spa", "spd", "spe", "bst", "types",
            "abilities", "catch_rate", "egg_groups", "gender_ratio",
            "growth_rate", "evs", "name", "category", "height", "weight",
            "evolutions",
        ]
        missing = [f for f in expected_fields if f not in bulba]
        _assert("bulbasaur has all expected fields",
                len(missing) == 0,
                f"missing: {missing}")

        # 3. Types
        _assert("bulbasaur types are [Grass, Poison]",
                bulba.get("types") == ["Grass", "Poison"],
                f"got: {bulba.get('types')}")

        # 4. Ability slot 0
        abilities = bulba.get("abilities", [])
        _assert("bulbasaur ability 0 is Overgrow",
                len(abilities) > 0 and abilities[0] == "Overgrow",
                f"got: {abilities}")

        # 5. At least 1 evolution (to Ivysaur)
        evos = bulba.get("evolutions", [])
        _assert("bulbasaur has >= 1 evolution",
                len(evos) >= 1,
                f"got {len(evos)} evolutions")

        # 6. catch_rate is int > 0
        cr = bulba.get("catch_rate")
        _assert("bulbasaur catch_rate is int > 0",
                isinstance(cr, int) and cr > 0,
                f"got: {cr!r}")

        # 7. egg_groups is non-empty list
        eg = bulba.get("egg_groups")
        _assert("bulbasaur egg_groups is non-empty list",
                isinstance(eg, list) and len(eg) > 0,
                f"got: {eg!r}")

        # 8. gender_ratio is a string
        gr = bulba.get("gender_ratio")
        _assert("bulbasaur gender_ratio is a string",
                isinstance(gr, str),
                f"got: {gr!r}")

        # 9. name is "Bulbasaur"
        _assert("bulbasaur name is 'Bulbasaur'",
                bulba.get("name") == "Bulbasaur",
                f"got: {bulba.get('name')!r}")

    # 10. Eevee has >= 8 evolutions
    eevee = data.get("SPECIES_EEVEE")
    if not eevee:
        _skip("eevee >= 8 evolutions", "SPECIES_EEVEE not found")
    else:
        evos = eevee.get("evolutions", [])
        _assert("eevee has >= 8 evolutions",
                len(evos) >= 8,
                f"got {len(evos)} evolutions")

    # 11. Charizard Mega X is_mega
    mega_x = data.get("SPECIES_CHARIZARD_MEGA_X")
    if not mega_x:
        _skip("charizard mega X is_mega", "SPECIES_CHARIZARD_MEGA_X not found")
    else:
        _assert("charizard mega X has is_mega=True",
                mega_x.get("is_mega") is True,
                f"got: {mega_x.get('is_mega')!r}")

    # 12. Gigantamax form has is_gmax
    gmax_key = None
    for k, v in data.items():
        if v.get("is_gmax"):
            gmax_key = k
            break
    if not gmax_key:
        # Try specific keys
        for candidate in ("SPECIES_CHARIZARD_GIGANTAMAX",
                          "SPECIES_PIKACHU_GIGANTAMAX",
                          "SPECIES_MEOWTH_GIGANTAMAX"):
            if candidate in data:
                gmax_key = candidate
                break

    if not gmax_key:
        _skip("gigantamax form has is_gmax", "no gigantamax species found")
    else:
        _assert("gigantamax form has is_gmax=True",
                data[gmax_key].get("is_gmax") is True,
                f"{gmax_key}: is_gmax={data[gmax_key].get('is_gmax')!r}")

    # 13. Species with no evolutions has evolutions == []
    no_evo_key = None
    for k, v in data.items():
        if v.get("evolutions") == []:
            no_evo_key = k
            break
    if not no_evo_key:
        _skip("species with no evolutions", "no species with empty evolutions found")
    else:
        _assert("species with no evolutions has evolutions=[]",
                data[no_evo_key].get("evolutions") == [],
                f"{no_evo_key}: evolutions={data[no_evo_key].get('evolutions')!r}")

    # 14. BST equals sum of 6 stats (verify for 3 species)
    check_species = ["SPECIES_BULBASAUR", "SPECIES_PIKACHU", "SPECIES_CHARIZARD"]
    check_species = [s for s in check_species if s in data]
    if len(check_species) < 3:
        # Grab whatever we have
        for k in list(data.keys())[:3]:
            if k not in check_species:
                check_species.append(k)
            if len(check_species) >= 3:
                break

    bst_ok = True
    bst_detail = ""
    for sp in check_species[:3]:
        d = data[sp]
        calc = d["hp"] + d["atk"] + d["def"] + d["spa"] + d["spd"] + d["spe"]
        if calc != d["bst"]:
            bst_ok = False
            bst_detail = f"{sp}: sum={calc} but bst={d['bst']}"
            break
    _assert("BST equals sum of 6 stats (3 species checked)",
            bst_ok, bst_detail or "all matched")


# ---------------------------------------------------------------------------
# B. Learnset Tests
# ---------------------------------------------------------------------------

def _test_learnsets(gp, load_levelup, load_teachable, load_eggs):
    """Tests 15-25: learnset loaders."""
    # 15. Level-up learnset for Bulbasaur is non-empty
    lu = load_levelup(gp, "SPECIES_BULBASAUR")
    _assert("level-up learnset for bulbasaur is non-empty",
            len(lu) > 0,
            f"got {len(lu)} entries")

    if lu:
        # 16. Entries are (int, str) tuples
        first = lu[0]
        _assert("level-up entries are (int, str) tuples",
                isinstance(first, tuple) and len(first) == 2
                and isinstance(first[0], int) and isinstance(first[1], str),
                f"first entry: {first!r}")

        # 17. Sorted by level
        levels = [entry[0] for entry in lu]
        _assert("level-up entries are sorted by level",
                levels == sorted(levels),
                f"first 5 levels: {levels[:5]}")

        # 18. First entry has level >= 1
        _assert("first level-up entry has level >= 1",
                lu[0][0] >= 1,
                f"first level: {lu[0][0]}")

    # 19. Teachable learnset for Bulbasaur is non-empty
    tm = load_teachable(gp, "SPECIES_BULBASAUR")
    _assert("teachable learnset for bulbasaur is non-empty",
            len(tm) > 0,
            f"got {len(tm)} entries")

    if tm:
        # 20. Entries are strings starting with MOVE_
        all_move = all(isinstance(m, str) and m.startswith("MOVE_") for m in tm)
        _assert("teachable entries are MOVE_ strings",
                all_move,
                f"first non-MOVE entry: {next((m for m in tm if not m.startswith('MOVE_')), 'n/a')}")

    # 21. Egg moves for Bulbasaur is non-empty
    em = load_eggs(gp, "SPECIES_BULBASAUR")
    _assert("egg moves for bulbasaur is non-empty",
            len(em) > 0,
            f"got {len(em)} entries")

    if em:
        # 22. Entries are strings starting with MOVE_
        all_move = all(isinstance(m, str) and m.startswith("MOVE_") for m in em)
        _assert("egg move entries are MOVE_ strings",
                all_move,
                f"first non-MOVE entry: {next((m for m in em if not m.startswith('MOVE_')), 'n/a')}")

    # 23-25. Nonexistent species returns []
    _assert("level-up for nonexistent species returns []",
            load_levelup(gp, "SPECIES_ZZZZNOTREAL") == [],
            f"got: {load_levelup(gp, 'SPECIES_ZZZZNOTREAL')!r}")

    _assert("teachable for nonexistent species returns []",
            load_teachable(gp, "SPECIES_ZZZZNOTREAL") == [],
            f"got: {load_teachable(gp, 'SPECIES_ZZZZNOTREAL')!r}")

    _assert("egg moves for nonexistent species returns []",
            load_eggs(gp, "SPECIES_ZZZZNOTREAL") == [],
            f"got: {load_eggs(gp, 'SPECIES_ZZZZNOTREAL')!r}")


# ---------------------------------------------------------------------------
# C. Name Resolvers
# ---------------------------------------------------------------------------

def _test_name_resolvers(gp, load_moves, load_abilities):
    """Tests 26-30: move and ability name resolvers."""
    # 26. Move names is non-empty
    mn = load_moves(gp)
    _assert("load_move_names returns non-empty dict",
            len(mn) > 0,
            f"got {len(mn)} entries")

    # 27. MOVE_TACKLE -> "Tackle"
    _assert("MOVE_TACKLE maps to 'Tackle'",
            mn.get("MOVE_TACKLE") == "Tackle",
            f"got: {mn.get('MOVE_TACKLE')!r}")

    # 28. MOVE_VINE_WHIP -> "Vine Whip"
    _assert("MOVE_VINE_WHIP maps to 'Vine Whip'",
            mn.get("MOVE_VINE_WHIP") == "Vine Whip",
            f"got: {mn.get('MOVE_VINE_WHIP')!r}")

    # 29. Ability names is non-empty
    an = load_abilities(gp)
    _assert("load_ability_names returns non-empty dict",
            len(an) > 0,
            f"got {len(an)} entries")

    # 30. ABILITY_OVERGROW -> "Overgrow"
    _assert("ABILITY_OVERGROW maps to 'Overgrow'",
            an.get("ABILITY_OVERGROW") == "Overgrow",
            f"got: {an.get('ABILITY_OVERGROW')!r}")


# ---------------------------------------------------------------------------
# D. Dex Filter Logic
# ---------------------------------------------------------------------------

def _test_filters(data, filter_fn):
    """Tests 31-40: _filter_species filter logic."""
    # Build the items list from loaded data
    items = list(data.items())

    # 31. Name filter "char" matches >= 3 (Charmander, Charmeleon, Charizard)
    char_results = filter_fn(items, "char")
    _assert("name filter 'char' matches >= 3 species",
            len(char_results) >= 3,
            f"got {len(char_results)} matches")

    # 32. Nonsense name returns empty
    nonsense = filter_fn(items, "zzzznotaspecies")
    _assert("name filter 'zzzznotaspecies' returns empty",
            len(nonsense) == 0,
            f"got {len(nonsense)} matches")

    # 33. type:fire returns > 0 and all have Fire type
    fire = filter_fn(items, "type:fire")
    fire_ok = len(fire) > 0 and all(
        "Fire" in (d.get("types") or []) for _, d in fire
    )
    _assert("type:fire returns fire-typed species",
            fire_ok,
            f"count={len(fire)}, non-fire found" if not fire_ok else "")

    # 34. type:fire/dragon returns > 0
    fire_dragon = filter_fn(items, "type:fire/dragon")
    _assert("type:fire/dragon returns > 0 results",
            len(fire_dragon) > 0,
            f"got {len(fire_dragon)} matches")

    # 35. ability:intimidate returns > 0
    intim = filter_fn(items, "ability:intimidate")
    _assert("ability:intimidate returns > 0 results",
            len(intim) > 0,
            f"got {len(intim)} matches")

    # 36. egg:dragon returns > 0
    egg_dragon = filter_fn(items, "egg:dragon")
    _assert("egg:dragon returns > 0 results",
            len(egg_dragon) > 0,
            f"got {len(egg_dragon)} matches")

    # 37. bst>600 returns > 0 and all BST > 600
    high_bst = filter_fn(items, "bst>600")
    high_ok = len(high_bst) > 0 and all(
        d.get("bst", 0) > 600 for _, d in high_bst
    )
    _assert("bst>600 returns species with BST > 600",
            high_ok,
            f"count={len(high_bst)}")

    # 38. bst<300 returns > 0 and all BST < 300
    low_bst = filter_fn(items, "bst<300")
    low_ok = len(low_bst) > 0 and all(
        d.get("bst", 0) < 300 for _, d in low_bst
    )
    _assert("bst<300 returns species with BST < 300",
            low_ok,
            f"count={len(low_bst)}")

    # 39. bst=600 returns > 0 and all BST == 600
    exact_bst = filter_fn(items, "bst=600")
    exact_ok = len(exact_bst) > 0 and all(
        d.get("bst", 0) == 600 for _, d in exact_bst
    )
    _assert("bst=600 returns species with BST == 600",
            exact_ok,
            f"count={len(exact_bst)}")

    # 40. Case insensitive: type:FIRE and type:fire return same count
    fire_upper = filter_fn(items, "type:FIRE")
    fire_lower = filter_fn(items, "type:fire")
    _assert("type:FIRE and type:fire return same count",
            len(fire_upper) == len(fire_lower),
            f"FIRE={len(fire_upper)}, fire={len(fire_lower)}")


# ---------------------------------------------------------------------------
# E. Form Folding
# ---------------------------------------------------------------------------

def _test_form_folding(species_order, form_tables, data, build_fn):
    """Tests 41-47: _build_folded_list grouping and sorting."""
    folded = build_fn(species_order, form_tables)

    # 41. Folded list is non-empty
    _assert("folded list is non-empty",
            len(folded) > 0,
            f"got {len(folded)} entries")

    # 42. Folded list is shorter than species_order (forms collapsed)
    _assert("folded list is shorter than species_order",
            len(folded) < len(species_order),
            f"folded={len(folded)}, order={len(species_order)}")

    # 43. Charizard forms are folded into one entry
    char_entries = [
        (bc, bd, fc) for bc, bd, fc in folded if bc == "SPECIES_CHARIZARD"
    ]
    _assert("charizard appears exactly once in folded list",
            len(char_entries) == 1,
            f"got {len(char_entries)} charizard entries")

    if char_entries:
        _bc, _bd, fc = char_entries[0]
        # 44. Charizard form_consts includes Mega X, Mega Y, Gigantamax
        _assert("charizard form_consts has > 1 entry",
                len(fc) > 1,
                f"got {len(fc)} forms: {fc}")

        # 45. First entry in form_consts is the base form
        _assert("charizard base form is first in form_consts",
                fc[0] == "SPECIES_CHARIZARD",
                f"first form: {fc[0]}")

    # 46. Single-form Pokemon has form_consts length 1
    single_form = None
    for bc, bd, fc in folded:
        if len(fc) == 1:
            single_form = (bc, bd, fc)
            break
    if single_form:
        _assert("single-form Pokemon has form_consts length 1",
                len(single_form[2]) == 1,
                f"{single_form[0]}: {len(single_form[2])} forms")
    else:
        _skip("single-form Pokemon check", "no single-form species found")

    # 47. Sorted by dex number (first few entries have ascending dex nums)
    dex_nums = []
    for bc, bd, fc in folded[:20]:
        dn = bd.get("nat_dex_num") or 0
        if dn > 0:
            dex_nums.append(dn)
    _assert("first 20 entries sorted by dex number",
            dex_nums == sorted(dex_nums),
            f"first dex nums: {dex_nums[:10]}")


# ---------------------------------------------------------------------------
# F. Form Labels
# ---------------------------------------------------------------------------

def _test_form_labels(form_label_fn):
    """Tests 48-52: _form_label extraction."""
    # 48. Base form returns empty string
    _assert("form_label for base form is empty",
            form_label_fn("SPECIES_CHARIZARD", "SPECIES_CHARIZARD") == "",
            f"got: {form_label_fn('SPECIES_CHARIZARD', 'SPECIES_CHARIZARD')!r}")

    # 49. Mega X
    result = form_label_fn("SPECIES_CHARIZARD_MEGA_X", "SPECIES_CHARIZARD")
    _assert("form_label for MEGA_X is 'Mega X'",
            result == "Mega X",
            f"got: {result!r}")

    # 50. Alola
    result = form_label_fn("SPECIES_RATTATA_ALOLA", "SPECIES_RATTATA")
    _assert("form_label for ALOLA is 'Alola'",
            result == "Alola",
            f"got: {result!r}")

    # 51. Gigantamax
    result = form_label_fn("SPECIES_CHARIZARD_GIGANTAMAX", "SPECIES_CHARIZARD")
    _assert("form_label for GIGANTAMAX is 'Gigantamax'",
            result == "Gigantamax",
            f"got: {result!r}")

    # 52. Mega (no suffix)
    result = form_label_fn("SPECIES_VENUSAUR_MEGA", "SPECIES_VENUSAUR")
    _assert("form_label for MEGA is 'Mega'",
            result == "Mega",
            f"got: {result!r}")


# ---------------------------------------------------------------------------
# G. Name Jump
# ---------------------------------------------------------------------------

def _test_name_or_dex_jump(species_order, form_tables, build_fn, name_jump_fn):
    """Tests 53-55: name jump in browser."""
    from torch.list_widget import ListState, guard_bounds

    folded = build_fn(species_order, form_tables)

    # 53. Searching "pikachu" jumps to Pikachu's entry
    state = ListState(len(folded))
    name_jump_fn("pikachu", folded, state)
    if state.selected < len(folded):
        bc, bd, fc = folded[state.selected]
        _assert("name jump 'pikachu' lands on Pikachu",
                "pikachu" in bc.lower() or
                "Pikachu" in (bd.get("name") or ""),
                f"landed on: {bc}")
    else:
        _fail("name jump 'pikachu' out of bounds",
              f"selected={state.selected}")

    # 54. Searching nonsense doesn't crash, stays at 0
    state2 = ListState(len(folded))
    name_jump_fn("zzzznotreal", folded, state2)
    _assert("name jump 'zzzznotreal' stays at index 0",
            state2.selected == 0,
            f"selected={state2.selected}")

    # 55. Searching "char" lands on Charmander or Charizard
    state3 = ListState(len(folded))
    name_jump_fn("char", folded, state3)
    if state3.selected < len(folded):
        bc, bd, fc = folded[state3.selected]
        name_lower = (bd.get("name") or bc).lower()
        _assert("name jump 'char' lands on a Char* species",
                "char" in name_lower,
                f"landed on: {bc} ({bd.get('name')})")
    else:
        _fail("name jump 'char' out of bounds",
              f"selected={state3.selected}")


# ---------------------------------------------------------------------------
# H. Evolution Chains
# ---------------------------------------------------------------------------

def _test_evolution_chains(species_order, species_data, build_chain_fn,
                           evo_arrow_fn):
    """Tests 56-63: evolution chain building and form deduplication."""
    # 56. Pikachu chain has exactly 3 entries (Pichu -> Pikachu -> Raichu)
    pika_chain = build_chain_fn("SPECIES_PIKACHU", species_order, species_data)
    _assert("pikachu chain has exactly 3 entries",
            len(pika_chain) == 3,
            f"got {len(pika_chain)}: {[e[0] for e in pika_chain]}")

    # 57. Pikachu chain starts with Pichu
    if pika_chain:
        _assert("pikachu chain starts with Pichu",
                pika_chain[0][0] == "SPECIES_PICHU",
                f"first entry: {pika_chain[0][0]}")

    # 58. Raichu Alola is NOT in the chain
    chain_consts = [e[0] for e in pika_chain]
    _assert("raichu alola not in pikachu chain",
            "SPECIES_RAICHU_ALOLA" not in chain_consts,
            f"chain: {chain_consts}")

    # 59. Raichu IS in the chain
    _assert("raichu is in pikachu chain",
            "SPECIES_RAICHU" in chain_consts,
            f"chain: {chain_consts}")

    # 60. Bulbasaur chain has exactly 3 entries
    bulba_chain = build_chain_fn("SPECIES_BULBASAUR", species_order,
                                 species_data)
    _assert("bulbasaur chain has exactly 3 entries",
            len(bulba_chain) == 3,
            f"got {len(bulba_chain)}: {[e[0] for e in bulba_chain]}")

    # 61. Evo arrow for LEVEL method with param "16"
    arrow = evo_arrow_fn("LEVEL", "16")
    _assert("evo arrow for LEVEL/16 shows Lv.16",
            "Lv.16" in arrow,
            f"got: {arrow!r}")

    # 62. Evo arrow for ITEM method with ITEM_THUNDER_STONE
    arrow = evo_arrow_fn("ITEM", "ITEM_THUNDER_STONE")
    _assert("evo arrow for ITEM/THUNDER_STONE shows Thunder Stone",
            "Thunder Stone" in arrow,
            f"got: {arrow!r}")

    # 63. Evo arrow for LEVEL method with param "0" (generic level evo)
    arrow = evo_arrow_fn("LEVEL", "0")
    _assert("evo arrow for LEVEL/0 does not show 'Lv.0'",
            "Lv.0" not in arrow,
            f"got: {arrow!r}")


# ---------------------------------------------------------------------------
# I. show_species_card (public callable utility)
# ---------------------------------------------------------------------------

def _test_show_species_card(game_path):
    """Tests 64-68: show_species_card public wrapper."""
    try:
        from torch.dex import show_species_card
    except ImportError as e:
        _skip("show_species_card tests", f"import failed: {e}")
        return

    from unittest.mock import patch
    import io

    # 64. show_species_card is importable and callable
    _assert("show_species_card is callable",
            callable(show_species_card),
            "not callable")

    # 65. Invalid species const returns gracefully (no exception)
    try:
        with patch("sys.stdout", new_callable=io.StringIO):
            show_species_card("SPECIES_ZZZZNOTREAL", game_path)
        _ok("show_species_card: invalid species returns gracefully")
    except Exception as exc:
        _fail("show_species_card: invalid species should not raise",
              f"raised: {exc}")

    # 66. None species const returns without error
    try:
        show_species_card(None, game_path)
        _ok("show_species_card: None species_const returns without error")
    except Exception as exc:
        _fail("show_species_card: None species_const should not raise",
              f"raised: {exc}")

    # 67. None game_path returns without error
    try:
        show_species_card("SPECIES_PIKACHU", None)
        _ok("show_species_card: None game_path returns without error")
    except Exception as exc:
        _fail("show_species_card: None game_path should not raise",
              f"raised: {exc}")

    # 68. Valid species calls _card_view (mock it to avoid interactive input)
    try:
        with patch("torch.dex._card_view") as mock_card:
            show_species_card("SPECIES_PIKACHU", game_path)
            _assert("show_species_card: calls _card_view for valid species",
                    mock_card.called,
                    "mock_card was not called")
    except Exception as exc:
        _fail("show_species_card: valid species should call _card_view",
              f"raised: {exc}")
