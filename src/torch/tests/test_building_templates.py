"""Tests for building_templates.py — template data integrity."""
from torch.tests.harness import _begin_suite, _assert


_REQUIRED_TEMPLATE_KEYS = {
    "map_bin", "border_bin", "width", "height",
    "primary_tileset", "secondary_tileset", "music", "map_type",
    "shared_layout_id", "shared_layout_name", "shared_layout_dir",
    "object_events", "warp_events", "script_template",
}

_REQUIRED_NPC_KEYS = {
    "graphics_id", "x", "y", "elevation", "movement_type",
    "movement_range_x", "movement_range_y", "trainer_type",
    "trainer_sight_or_berry_tree_id", "script", "flag",
}

_REQUIRED_WARP_KEYS = {"x", "y", "elevation", "dest_map", "dest_warp_id"}

_INDOOR_EXPECTED_KEYS = {
    "requires_flash", "weather", "map_type", "allow_cycling",
    "allow_escaping", "allow_running", "show_map_name",
    "battle_scene", "connections", "coord_events", "bg_events",
}


def run_suite():
    _begin_suite("Building Templates (data integrity)")

    from torch.building_templates import TEMPLATES, INDOOR_DEFAULTS

    # ── All three templates exist ─────────────────────────────────
    for name in ("pokecenter_1f", "pokecenter_2f", "pokemart"):
        _assert(f"template '{name}' exists",
                name in TEMPLATES,
                f"missing key '{name}'")

    # ── Required keys present ─────────────────────────────────────
    for name, tmpl in TEMPLATES.items():
        missing = _REQUIRED_TEMPLATE_KEYS - set(tmpl.keys())
        _assert(f"'{name}' has all required keys",
                len(missing) == 0,
                f"missing: {missing}")

    # ── Binary integrity: map_bin ─────────────────────────────────
    for name, tmpl in TEMPLATES.items():
        expected = tmpl["width"] * tmpl["height"] * 2
        actual = len(tmpl["map_bin"])
        _assert(f"'{name}' map_bin size = width*height*2",
                actual == expected,
                f"got {actual}, expected {expected}")

    # ── Binary integrity: border_bin ──────────────────────────────
    for name, tmpl in TEMPLATES.items():
        _assert(f"'{name}' border_bin is 8 bytes",
                len(tmpl["border_bin"]) == 8,
                f"got {len(tmpl['border_bin'])}")

    # ── Specific dimensions ───────────────────────────────────────
    _assert("pokecenter_1f is 14x9",
            TEMPLATES["pokecenter_1f"]["width"] == 14
            and TEMPLATES["pokecenter_1f"]["height"] == 9,
            f"got {TEMPLATES['pokecenter_1f']['width']}x{TEMPLATES['pokecenter_1f']['height']}")

    _assert("pokecenter_2f is 14x10",
            TEMPLATES["pokecenter_2f"]["width"] == 14
            and TEMPLATES["pokecenter_2f"]["height"] == 10,
            f"got {TEMPLATES['pokecenter_2f']['width']}x{TEMPLATES['pokecenter_2f']['height']}")

    _assert("pokemart is 11x8",
            TEMPLATES["pokemart"]["width"] == 11
            and TEMPLATES["pokemart"]["height"] == 8,
            f"got {TEMPLATES['pokemart']['width']}x{TEMPLATES['pokemart']['height']}")

    # ── Tileset references valid ──────────────────────────────────
    for name, tmpl in TEMPLATES.items():
        for key in ("primary_tileset", "secondary_tileset"):
            val = tmpl[key]
            _assert(f"'{name}' {key} starts with gTileset_",
                    isinstance(val, str) and val.startswith("gTileset_"),
                    f"got {val!r}")

    # ── Music references valid ────────────────────────────────────
    for name, tmpl in TEMPLATES.items():
        val = tmpl["music"]
        _assert(f"'{name}' music starts with MUS_",
                isinstance(val, str) and val.startswith("MUS_"),
                f"got {val!r}")

    # ── Shared layout IDs follow convention ───────────────────────
    for name, tmpl in TEMPLATES.items():
        val = tmpl["shared_layout_id"]
        _assert(f"'{name}' shared_layout_id starts with LAYOUT_",
                isinstance(val, str) and val.startswith("LAYOUT_"),
                f"got {val!r}")

    # ── NPC definitions valid ─────────────────────────────────────
    for name, tmpl in TEMPLATES.items():
        for i, npc in enumerate(tmpl["object_events"]):
            missing = _REQUIRED_NPC_KEYS - set(npc.keys())
            _assert(f"'{name}' NPC {i} has all required keys",
                    len(missing) == 0,
                    f"missing: {missing}")

    # ── Warp definitions valid ────────────────────────────────────
    for name, tmpl in TEMPLATES.items():
        for i, warp in enumerate(tmpl["warp_events"]):
            missing = _REQUIRED_WARP_KEYS - set(warp.keys())
            _assert(f"'{name}' warp {i} has all required keys",
                    len(missing) == 0,
                    f"missing: {missing}")

    # ── Script templates ──────────────────────────────────────────
    _assert("pokecenter_1f script_template is non-empty",
            len(TEMPLATES["pokecenter_1f"]["script_template"]) > 0,
            "empty script template")

    _assert("pokemart script_template is non-empty",
            len(TEMPLATES["pokemart"]["script_template"]) > 0,
            "empty script template")

    # ── Script template placeholders ──────────────────────────────
    for name in ("pokecenter_1f", "pokemart"):
        tmpl = TEMPLATES[name]
        _assert(f"'{name}' script_template has {{map_name}} placeholder",
                "{map_name}" in tmpl["script_template"],
                "missing {map_name} placeholder")

    # ── Conditional warp on pokecenter_1f ─────────────────────────
    warps = TEMPLATES["pokecenter_1f"]["warp_events"]
    stairs_warp = warps[2]
    _assert("pokecenter_1f warp 2 (stairs) has conditional key",
            stairs_warp.get("conditional") == "include_2f",
            f"got conditional={stairs_warp.get('conditional')!r}")

    # ── All templates have mapscripts declaration ──────────────────
    for name, tmpl in TEMPLATES.items():
        _assert(f"'{name}' script_template has mapscripts",
                "mapscripts" in tmpl["script_template"],
                "missing mapscripts declaration")

    # ── Pokemart script uses raw block (not invalid mart() syntax) ─
    mart_tmpl = TEMPLATES["pokemart"]["script_template"]
    _assert("pokemart script has no mart() block declaration",
            "\nmart(" not in mart_tmpl and not mart_tmpl.startswith("mart("),
            "found invalid mart() block -- Poryscript has no mart() syntax")
    _assert("pokemart script has raw block for items",
            "raw `" in mart_tmpl,
            "missing raw block for mart item data")
    _assert("pokemart script has ITEM_NONE terminator",
            "ITEM_NONE" in mart_tmpl,
            "mart item list must end with ITEM_NONE")

    # ── Pokemart msgbox uses label ref, not string literal ───────
    substituted = mart_tmpl.replace("{map_name}", "Test_Mart")
    _assert("pokemart msgbox uses label ref not string",
            "msgbox(Test_Mart_Text_Greeting" in substituted
            and 'msgbox("Test_Mart_Text_Greeting' not in substituted,
            "msgbox should reference label, not string literal")

    # ── INDOOR_DEFAULTS has all expected keys ─────────────────────
    missing = _INDOOR_EXPECTED_KEYS - set(INDOOR_DEFAULTS.keys())
    _assert("INDOOR_DEFAULTS has all expected keys",
            len(missing) == 0,
            f"missing: {missing}")
