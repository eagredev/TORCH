"""Templates suite -- builder functions, registry, variable types."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Templates  (builders, registry, item picker)")

    try:
        import torch.templates as tmpl
    except ImportError as e:
        _skip("all template tests", f"import failed: {e}")
        return

    _test_registry_completeness(tmpl)
    _test_template_required_fields(tmpl)
    _test_builder_single_battle(tmpl)
    _test_builder_single_battle_no_flag(tmpl)
    _test_builder_double_battle(tmpl)
    _test_builder_nurse_heal(tmpl)
    _test_builder_shop(tmpl)
    _test_builder_item_gift(tmpl)
    _test_builder_sign(tmpl)
    _test_builder_weather(tmpl)
    _test_builder_trade(tmpl)
    _test_builder_move_tutor(tmpl)
    _test_all_builders_return_lists(tmpl)
    _test_all_beats_have_type_and_data(tmpl)
    _test_weather_options(tmpl)
    _test_category_labels(tmpl)
    _test_item_picker_import()
    _test_load_items_filtering()
    _test_multi_beat_insertion()


# ── Registry ────────────────────────────────────────────────────────

def _test_registry_completeness(tmpl):
    """TEMPLATES list contains all defined templates."""
    expected_ids = {
        "single_battle", "double_battle", "nurse_heal", "shop",
        "item_gift", "sign", "weather", "trade", "move_tutor",
    }
    actual_ids = {t["id"] for t in tmpl.TEMPLATES}
    _assert(
        "registry: all 9 templates present",
        actual_ids == expected_ids,
        f"missing: {expected_ids - actual_ids}, extra: {actual_ids - expected_ids}"
    )


def _test_template_required_fields(tmpl):
    """Every template has all required fields."""
    required = {"id", "name", "description", "category", "trigger", "variables", "builder"}
    for t in tmpl.TEMPLATES:
        missing = required - set(t.keys())
        _assert(
            f"template '{t.get('id', '?')}': has all required fields",
            not missing,
            f"missing: {missing}"
        )


# ── Builder functions ───────────────────────────────────────────────

def _make_ctx(label="TestMap_TestScene"):
    return {
        "label": label,
        "map_name": "TestMap",
        "game_path": "/fake/path",
        "cast": {},
    }


def _test_builder_single_battle(tmpl):
    """Single battle builder with flag produces gotoif + battle + flag set."""
    vs = {"trainer": "TRAINER_RIVAL_1", "flag": "FLAG_DEFEATED_RIVAL"}
    beats = tmpl._build_single_battle(vs, _make_ctx())
    _assert(
        "single_battle: produces beats",
        len(beats) >= 3,
        f"got {len(beats)} beats"
    )
    types = [b["type"] for b in beats]
    _assert(
        "single_battle: starts with gotoif when flag set",
        types[0] == "gotoif",
        f"first beat type: {types[0]}"
    )
    _assert(
        "single_battle: contains battle beat",
        "battle" in types,
        f"types: {types}"
    )
    _assert(
        "single_battle: contains flag set beat",
        "flag" in types,
        f"types: {types}"
    )


def _test_builder_single_battle_no_flag(tmpl):
    """Single battle without flag produces just a battle beat."""
    vs = {"trainer": "TRAINER_RIVAL_1", "flag": None}
    beats = tmpl._build_single_battle(vs, _make_ctx())
    _assert(
        "single_battle_no_flag: produces 1 beat",
        len(beats) == 1,
        f"got {len(beats)} beats"
    )
    _assert(
        "single_battle_no_flag: beat is battle type",
        beats[0]["type"] == "battle",
        f"type: {beats[0]['type']}"
    )


def _test_builder_double_battle(tmpl):
    """Double battle builder produces battle beat with double type."""
    vs = {"trainer": "TRAINER_RIVAL_1", "flag": None}
    beats = tmpl._build_double_battle(vs, _make_ctx())
    _assert(
        "double_battle: produces battle beat",
        len(beats) >= 1 and beats[0]["type"] == "battle",
        f"beats: {beats}"
    )
    _assert(
        "double_battle: battle_type is trainerbattle_double",
        beats[0]["data"]["battle_type"] == "trainerbattle_double",
        f"battle_type: {beats[0]['data']['battle_type']}"
    )


def _test_builder_nurse_heal(tmpl):
    """Nurse heal builder produces dialogue + special + waitstate + dialogue."""
    beats = tmpl._build_nurse_heal({}, _make_ctx())
    types = [b["type"] for b in beats]
    _assert(
        "nurse_heal: produces 4 beats",
        len(beats) == 4,
        f"got {len(beats)}: {types}"
    )
    _assert(
        "nurse_heal: beat types are dialogue/special/waitstate/dialogue",
        types == ["dialogue", "special", "waitstate", "dialogue"],
        f"types: {types}"
    )
    _assert(
        "nurse_heal: special function is HealPlayerParty",
        beats[1]["data"]["function"] == "HealPlayerParty",
        f"function: {beats[1]['data']['function']}"
    )


def _test_builder_shop(tmpl):
    """Shop builder produces dialogue + pory (pokemart) + dialogue."""
    vs = {"items": ["ITEM_POTION", "ITEM_ANTIDOTE"], "greeting": "Hello!"}
    beats = tmpl._build_shop(vs, _make_ctx())
    types = [b["type"] for b in beats]
    _assert(
        "shop: produces 3 beats",
        len(beats) == 3,
        f"got {len(beats)}: {types}"
    )
    _assert(
        "shop: middle beat is pory with pokemart",
        beats[1]["type"] == "pory" and "pokemart" in beats[1]["data"]["raw_line"],
        f"beat: {beats[1]}"
    )
    _assert(
        "shop: pokemart has both items",
        "ITEM_POTION" in beats[1]["data"]["raw_line"]
        and "ITEM_ANTIDOTE" in beats[1]["data"]["raw_line"],
        f"raw_line: {beats[1]['data']['raw_line']}"
    )


def _test_builder_item_gift(tmpl):
    """Item gift builder produces flag check + dialogue + giveitem + bag full branch."""
    vs = {"item": "ITEM_POTION", "flag": "FLAG_GOT_POTION", "dialogue": "Take this!"}
    beats = tmpl._build_item_gift(vs, _make_ctx())
    types = [b["type"] for b in beats]
    _assert(
        "item_gift: starts with gotoif",
        types[0] == "gotoif",
        f"first type: {types[0]}"
    )
    _assert(
        "item_gift: has BagFull label",
        any(b["type"] == "label" and "BagFull" in b["data"]["name"] for b in beats),
        f"labels: {[b['data'].get('name', '') for b in beats if b['type'] == 'label']}"
    )
    _assert(
        "item_gift: has giveitem pory beat",
        any(b["type"] == "pory" and "giveitem" in b["data"]["raw_line"] for b in beats),
        f"pory beats: {[b['data']['raw_line'] for b in beats if b['type'] == 'pory']}"
    )


def _test_builder_sign(tmpl):
    """Sign builder produces msgbox_sign pory beat."""
    vs = {"text": "Welcome to Seihoku!"}
    beats = tmpl._build_sign(vs, _make_ctx())
    _assert(
        "sign: produces 1 beat",
        len(beats) == 1,
        f"got {len(beats)} beats"
    )
    _assert(
        "sign: is pory beat with MSGBOX_SIGN",
        beats[0]["type"] == "pory" and "MSGBOX_SIGN" in beats[0]["data"]["raw_line"],
        f"beat: {beats[0]}"
    )


def _test_builder_weather(tmpl):
    """Weather builder produces setweather + doweather pory beats."""
    vs = {"weather": "WEATHER_RAIN"}
    beats = tmpl._build_weather(vs, _make_ctx())
    _assert(
        "weather: produces 2 beats",
        len(beats) == 2,
        f"got {len(beats)} beats"
    )
    _assert(
        "weather: first beat sets weather",
        "setweather" in beats[0]["data"]["raw_line"],
        f"raw_line: {beats[0]['data']['raw_line']}"
    )
    _assert(
        "weather: second beat does weather",
        "doweather" in beats[1]["data"]["raw_line"],
        f"raw_line: {beats[1]['data']['raw_line']}"
    )


def _test_builder_trade(tmpl):
    """Trade builder produces dialogue + special calls + branches."""
    vs = {"wanted_species": "SPECIES_PIKACHU", "offered_species": "SPECIES_EEVEE", "flag": "FLAG_TRADE_DONE"}
    beats = tmpl._build_trade(vs, _make_ctx())
    types = [b["type"] for b in beats]
    _assert(
        "trade: has gotoif for flag",
        "gotoif" in types,
        f"types: {types}"
    )
    _assert(
        "trade: has dialogue beats",
        "dialogue" in types,
        f"types: {types}"
    )
    _assert(
        "trade: has ChoosePartyMon special",
        any(b["type"] == "pory" and "ChoosePartyMon" in b["data"]["raw_line"] for b in beats),
        "no ChoosePartyMon found"
    )
    _assert(
        "trade: has Declined label",
        any(b["type"] == "label" and "Declined" in b["data"]["name"] for b in beats),
        "no Declined label found"
    )


def _test_builder_move_tutor(tmpl):
    """Move tutor builder produces dialogue + special calls + branches."""
    vs = {"move_name": "MOVE_THUNDERBOLT", "flag": "FLAG_TUTOR_DONE"}
    beats = tmpl._build_move_tutor(vs, _make_ctx())
    types = [b["type"] for b in beats]
    _assert(
        "move_tutor: has gotoif for flag",
        "gotoif" in types,
        f"types: {types}"
    )
    _assert(
        "move_tutor: has ChooseMonForMoveTutor special",
        any(b["type"] == "pory" and "ChooseMonForMoveTutor" in b["data"]["raw_line"] for b in beats),
        "no ChooseMonForMoveTutor found"
    )
    _assert(
        "move_tutor: has MOVE_THUNDERBOLT in setvar",
        any(b["type"] == "pory" and "MOVE_THUNDERBOLT" in b["data"]["raw_line"] for b in beats),
        "no MOVE_THUNDERBOLT found"
    )


# ── Cross-cutting checks ───────────────────────────────────────────

def _test_all_builders_return_lists(tmpl):
    """Every builder function returns a list."""
    ctx = _make_ctx()
    test_vars = {
        "single_battle": {"trainer": "TRAINER_X", "flag": None},
        "double_battle": {"trainer": "TRAINER_X", "flag": None},
        "nurse_heal": {},
        "shop": {"items": ["ITEM_POTION"], "greeting": "Hi"},
        "item_gift": {"item": "ITEM_X", "flag": None, "dialogue": "Here"},
        "sign": {"text": "Hello"},
        "weather": {"weather": "WEATHER_RAIN"},
        "trade": {"wanted_species": "SPECIES_A", "offered_species": "SPECIES_B", "flag": None},
        "move_tutor": {"move_name": "MOVE_X", "flag": None},
    }
    for t in tmpl.TEMPLATES:
        vs = test_vars.get(t["id"], {})
        result = t["builder"](vs, ctx)
        _assert(
            f"builder '{t['id']}': returns a list",
            isinstance(result, list),
            f"returned {type(result).__name__}"
        )


def _test_all_beats_have_type_and_data(tmpl):
    """Every beat from every builder has 'type' and 'data' keys."""
    ctx = _make_ctx()
    test_vars = {
        "single_battle": {"trainer": "TRAINER_X", "flag": "FLAG_Y"},
        "double_battle": {"trainer": "TRAINER_X", "flag": "FLAG_Y"},
        "nurse_heal": {},
        "shop": {"items": ["ITEM_POTION"], "greeting": "Hi"},
        "item_gift": {"item": "ITEM_X", "flag": "FLAG_Y", "dialogue": "Here"},
        "sign": {"text": "Hello"},
        "weather": {"weather": "WEATHER_RAIN"},
        "trade": {"wanted_species": "SPECIES_A", "offered_species": "SPECIES_B", "flag": "FLAG_Y"},
        "move_tutor": {"move_name": "MOVE_X", "flag": "FLAG_Y"},
    }
    all_ok = True
    bad = []
    for t in tmpl.TEMPLATES:
        vs = test_vars.get(t["id"], {})
        beats = t["builder"](vs, ctx)
        for i, b in enumerate(beats):
            if "type" not in b or "data" not in b:
                all_ok = False
                bad.append(f"{t['id']} beat {i}: missing type/data")
    _assert(
        "all beats: have 'type' and 'data' keys",
        all_ok,
        f"bad beats: {bad}"
    )


def _test_weather_options(tmpl):
    """Weather options list has entries with (name, constant) tuples."""
    opts = tmpl._WEATHER_OPTIONS
    _assert(
        "weather_options: has entries",
        len(opts) >= 4,
        f"got {len(opts)}"
    )
    _assert(
        "weather_options: each entry is (name, WEATHER_*)",
        all(isinstance(o, tuple) and len(o) == 2 and o[1].startswith("WEATHER_") for o in opts),
        f"bad entries: {[o for o in opts if not o[1].startswith('WEATHER_')]}"
    )


def _test_category_labels(tmpl):
    """All template categories have display labels."""
    cats = {t["category"] for t in tmpl.TEMPLATES}
    for cat in cats:
        _assert(
            f"category '{cat}': has display label",
            cat in tmpl._CATEGORY_LABELS,
            f"missing from _CATEGORY_LABELS"
        )


# ── Item picker ─────────────────────────────────────────────────────

def _test_item_picker_import():
    """pick_item and pick_item_list are importable from pickers."""
    try:
        from torch.pickers import pick_item, pick_item_list
        _assert(
            "item pickers: importable",
            callable(pick_item) and callable(pick_item_list),
            "not callable"
        )
    except ImportError as e:
        _fail("item pickers: importable", str(e))


def _test_load_items_filtering():
    """load_items filters out internal constants."""
    tmpdir = tempfile.mkdtemp()
    try:
        inc_dir = os.path.join(tmpdir, "include", "constants")
        os.makedirs(inc_dir)
        items_h = os.path.join(inc_dir, "items.h")
        with open(items_h, "w") as f:
            f.write("""\
#define ITEM_NONE 0
#define ITEM_POKE_BALL 1
#define ITEM_GREAT_BALL 2
#define ITEM_POTION 28
#define ITEM_ENERGY_POWDER 39
#define ITEM_ENERGYPOWDER ITEM_ENERGY_POWDER // Pre-Gen VI name
#define ITEMS_COUNT 855
#define ITEM_FIELD_ARROW ITEMS_COUNT
#define ITEM_USE_MAIL 0
#define ITEM_USE_PARTY_MENU 1
""")
        from torch.gamedata import load_items
        items = load_items(tmpdir)
        names = [n for n, c in items]
        _assert(
            "load_items: keeps regular items",
            "ITEM_POKE_BALL" in names and "ITEM_POTION" in names,
            f"names: {names}"
        )
        _assert(
            "load_items: filters ITEM_NONE",
            "ITEM_NONE" not in names,
            f"names: {names}"
        )
        _assert(
            "load_items: filters ITEM_USE_*",
            not any(n.startswith("ITEM_USE_") for n in names),
            f"names: {names}"
        )
        _assert(
            "load_items: filters ITEMS_COUNT",
            "ITEMS_COUNT" not in names,
            f"names: {names}"
        )
        _assert(
            "load_items: filters ITEM_FIELD_ARROW",
            "ITEM_FIELD_ARROW" not in names,
            f"names: {names}"
        )
        _assert(
            "load_items: filters alias lines (ITEM_ENERGYPOWDER)",
            "ITEM_ENERGYPOWDER" not in names,
            f"names: {names}"
        )
    finally:
        shutil.rmtree(tmpdir)


# ── Multi-beat insertion ────────────────────────────────────────────

def _test_multi_beat_insertion():
    """Multiple beats from template are inserted in correct order."""
    beats = [
        {"type": "label", "data": {"name": "Start"}},
        {"type": "dialogue", "data": {"actor": "player", "text": "end", "style": "msg"}},
    ]
    # Simulate inserting 3 template beats after position 0
    template_beats = [
        {"type": "dialogue", "data": {"actor": "player", "text": "A", "style": "msg"}},
        {"type": "dialogue", "data": {"actor": "player", "text": "B", "style": "msg"}},
        {"type": "dialogue", "data": {"actor": "player", "text": "C", "style": "msg"}},
    ]
    insert_pos = 1  # after first beat
    for i, beat in enumerate(template_beats):
        beats.insert(insert_pos + i, beat)

    _assert(
        "multi_insert: beats in correct order",
        [b["data"].get("text", b["data"].get("name", "")) for b in beats]
        == ["Start", "A", "B", "C", "end"],
        f"order: {[b['data'].get('text', b['data'].get('name', '')) for b in beats]}"
    )
    _assert(
        "multi_insert: total count is 5",
        len(beats) == 5,
        f"count: {len(beats)}"
    )
