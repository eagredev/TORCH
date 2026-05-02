"""Tests for template_stamper.py — stamper engine."""
import copy
import json
import os
import shutil
import tempfile

from torch.tests.harness import _begin_suite, _assert
from torch.project_files import clear_project_cache


# ---------------------------------------------------------------------------
# Test fixture helpers
# ---------------------------------------------------------------------------

def _make_game(extra_groups=None, parent_warps=None, parent_map_type=None,
               heal_locations=None, extra_layouts=None, parent_name="TestTown",
               parent_width=20, parent_height=20):
    """Create a minimal fake game directory.

    Returns (game_path, cleanup_fn).
    """
    tmp = tempfile.mkdtemp(prefix="torch_stamp_test_")

    # map_groups.json
    groups = {
        "group_order": ["gMapGroup_TestTown", "gMapGroup_IndoorTestTown"],
        "gMapGroup_TestTown": [parent_name],
        "gMapGroup_IndoorTestTown": [],
    }
    if extra_groups:
        groups.update(extra_groups)
        for k in extra_groups:
            if k != "group_order" and k not in groups["group_order"]:
                groups["group_order"].append(k)
    mg_dir = os.path.join(tmp, "data", "maps")
    os.makedirs(mg_dir, exist_ok=True)
    with open(os.path.join(mg_dir, "map_groups.json"), "w") as f:
        json.dump(groups, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Parent map
    parent_dir = os.path.join(mg_dir, parent_name)
    os.makedirs(parent_dir, exist_ok=True)
    parent_json = {
        "id": f"MAP_{parent_name.upper()}",
        "name": parent_name,
        "layout": f"LAYOUT_{parent_name.upper()}",
        "music": "MUS_LITTLEROOT_TOWN",
        "region_map_section": f"MAPSEC_{parent_name.upper()}",
        "requires_flash": False,
        "weather": "WEATHER_NONE",
        "map_type": parent_map_type or "MAP_TYPE_TOWN",
        "allow_cycling": True,
        "allow_escaping": True,
        "allow_running": True,
        "show_map_name": True,
        "battle_scene": "MAP_BATTLE_SCENE_NORMAL",
        "connections": None,
        "object_events": [],
        "warp_events": parent_warps or [],
        "coord_events": [],
        "bg_events": [],
    }
    with open(os.path.join(parent_dir, "map.json"), "w") as f:
        json.dump(parent_json, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # layouts.json
    layouts = {
        "layouts_table_label": "gMapLayouts",
        "layouts": [
            {
                "id": f"LAYOUT_{parent_name.upper()}",
                "name": f"{parent_name}_Layout",
                "width": parent_width,
                "height": parent_height,
                "primary_tileset": "gTileset_General",
                "secondary_tileset": "gTileset_Petalburg",
                "border_filepath": f"data/layouts/{parent_name}/border.bin",
                "blockdata_filepath": f"data/layouts/{parent_name}/map.bin",
            }
        ],
    }
    if extra_layouts:
        layouts["layouts"].extend(extra_layouts)
    lay_dir = os.path.join(tmp, "data", "layouts")
    os.makedirs(lay_dir, exist_ok=True)
    with open(os.path.join(lay_dir, "layouts.json"), "w") as f:
        json.dump(layouts, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # heal_locations.json
    hl_dir = os.path.join(tmp, "src", "data")
    os.makedirs(hl_dir, exist_ok=True)
    hl_data = {
        "heal_locations_type": "HEAL_LOCATION_TYPE_MAP_CONST",
        "heal_locations": heal_locations or [],
    }
    with open(os.path.join(hl_dir, "heal_locations.json"), "w") as f:
        json.dump(hl_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # event_scripts.s
    es_path = os.path.join(tmp, "data", "event_scripts.s")
    with open(es_path, "w", encoding="utf-8") as f:
        f.write('\t.include "asm/macros.inc"\n')
        f.write('\t.include "constants/constants.inc"\n')
        f.write('\n')
        f.write(f'\t.include "data/maps/{parent_name}/scripts.inc"\n')
        f.write('\n')

    def cleanup():
        clear_project_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    return tmp, cleanup


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("Template Stamper")

    from torch.template_stamper import (
        stamp_pokecenter, stamp_pokemart, validate_stamp,
    )

    # ==================================================================
    # VALIDATION TESTS
    # ==================================================================

    # ── Missing parent map ───────────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokecenter", "NoSuchMap", 5, 5)
        _assert("validate: missing parent -> invalid",
                not r["valid"] and any("not found" in e for e in r["errors"]),
                f"errors={r['errors']}")
    finally:
        cleanup()

    # ── Door coords out of bounds ────────────────────────────────
    gp, cleanup = _make_game(parent_width=10, parent_height=10)
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokecenter", "TestTown", 15, 5)
        _assert("validate: coords out of bounds -> error",
                not r["valid"] and any("outside" in e for e in r["errors"]),
                f"errors={r['errors']}")
    finally:
        cleanup()

    # ── Negative coords ──────────────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokecenter", "TestTown", -1, 5)
        _assert("validate: negative coords -> error",
                not r["valid"] and any("outside" in e for e in r["errors"]),
                f"errors={r['errors']}")
    finally:
        cleanup()

    # ── Target map already exists ────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        # Create target dir
        os.makedirs(os.path.join(gp, "data", "maps",
                                 "TestTown_PokemonCenter_1F"))
        r = validate_stamp(gp, "pokecenter", "TestTown", 5, 5)
        _assert("validate: target exists -> error",
                not r["valid"] and any("already exists" in e for e in r["errors"]),
                f"errors={r['errors']}")
    finally:
        cleanup()

    # ── Parent is indoor -> warning ──────────────────────────────
    gp, cleanup = _make_game(parent_map_type="MAP_TYPE_INDOOR")
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokecenter", "TestTown", 5, 5)
        _assert("validate: indoor parent -> warning",
                r["valid"] and any("INDOOR" in w for w in r["warnings"]),
                f"warnings={r['warnings']}")
    finally:
        cleanup()

    # ── Warp already at coords -> warning ────────────────────────
    gp, cleanup = _make_game(parent_warps=[
        {"x": 5, "y": 5, "elevation": 0, "dest_map": "MAP_X", "dest_warp_id": "0"}
    ])
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokecenter", "TestTown", 5, 5)
        _assert("validate: warp at coords -> warning",
                r["valid"] and any("warp already exists" in w.lower() for w in r["warnings"]),
                f"warnings={r['warnings']}")
    finally:
        cleanup()

    # ── Valid input -> no errors ─────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokecenter", "TestTown", 5, 5)
        _assert("validate: valid input -> valid",
                r["valid"] and len(r["errors"]) == 0,
                f"errors={r['errors']}")
    finally:
        cleanup()

    # ── Unknown template type ────────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = validate_stamp(gp, "gym", "TestTown", 5, 5)
        _assert("validate: unknown template -> error",
                not r["valid"] and any("Unknown" in e for e in r["errors"]),
                f"errors={r['errors']}")
    finally:
        cleanup()

    # ── Validate pokemart type ───────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokemart", "TestTown", 5, 5)
        _assert("validate: pokemart -> valid",
                r["valid"],
                f"errors={r['errors']}")
        _assert("validate: pokemart preview has Mart",
                "TestTown_Mart" in r["preview"]["maps_to_create"],
                f"maps={r['preview']['maps_to_create']}")
    finally:
        cleanup()

    # ── Validate preview shows heal_location_id for pokecenter ───
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokecenter", "TestTown", 5, 5)
        _assert("validate: preview has heal_location_id",
                r["preview"]["heal_location_id"] == "HEAL_LOCATION_TEST_TOWN",
                f"got {r['preview']['heal_location_id']}")
    finally:
        cleanup()

    # ── Validate preview shows no heal for pokemart ──────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokemart", "TestTown", 5, 5)
        _assert("validate: pokemart no heal_location_id",
                r["preview"]["heal_location_id"] is None,
                f"got {r['preview']['heal_location_id']}")
    finally:
        cleanup()

    # ── Validate does not create files ───────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        validate_stamp(gp, "pokecenter", "TestTown", 5, 5)
        pc_dir = os.path.join(gp, "data", "maps", "TestTown_PokemonCenter_1F")
        _assert("validate: no files created",
                not os.path.exists(pc_dir),
                "map folder was created during validate")
    finally:
        cleanup()

    # ==================================================================
    # POKECENTER STAMP TESTS
    # ==================================================================

    # ── Basic stamp creates 1F folder ────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = stamp_pokecenter(gp, "TestTown", 5, 5)
        _assert("pc: stamp succeeds",
                r["success"], f"error={r.get('error')}")
        pc1f_dir = os.path.join(gp, "data", "maps",
                                "TestTown_PokemonCenter_1F")
        _assert("pc: 1F folder exists",
                os.path.isdir(pc1f_dir), "1F folder missing")
        mj = _load_json(os.path.join(pc1f_dir, "map.json"))
        _assert("pc: 1F map.json has correct id",
                mj["id"] == "MAP_TEST_TOWN_POKEMON_CENTER_1F",
                f"got {mj['id']}")
    finally:
        cleanup()

    # ── Creates 2F when include_2f=True ──────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = stamp_pokecenter(gp, "TestTown", 5, 5, include_2f=True)
        pc2f_dir = os.path.join(gp, "data", "maps",
                                "TestTown_PokemonCenter_2F")
        _assert("pc: 2F folder exists when include_2f=True",
                os.path.isdir(pc2f_dir), "2F folder missing")
        _assert("pc: 2F in maps_created",
                "TestTown_PokemonCenter_2F" in r["maps_created"],
                f"maps_created={r['maps_created']}")
    finally:
        cleanup()

    # ── Does NOT create 2F when include_2f=False ─────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = stamp_pokecenter(gp, "TestTown", 5, 5, include_2f=False)
        pc2f_dir = os.path.join(gp, "data", "maps",
                                "TestTown_PokemonCenter_2F")
        _assert("pc: no 2F when include_2f=False",
                not os.path.exists(pc2f_dir), "2F folder exists")
        _assert("pc: 2F not in maps_created",
                "TestTown_PokemonCenter_2F" not in r["maps_created"],
                f"maps_created={r['maps_created']}")
    finally:
        cleanup()

    # ── Shared layout directories created when missing ───────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        lay1f = os.path.join(gp, "data", "layouts", "PokemonCenter_1F")
        lay2f = os.path.join(gp, "data", "layouts", "PokemonCenter_2F")
        _assert("pc: layout dir PokemonCenter_1F created",
                os.path.isdir(lay1f), "layout dir missing")
        _assert("pc: layout dir PokemonCenter_2F created",
                os.path.isdir(lay2f), "layout dir missing")
        _assert("pc: map.bin exists in 1F layout",
                os.path.isfile(os.path.join(lay1f, "map.bin")),
                "map.bin missing")
    finally:
        cleanup()

    # ── Shared layout NOT duplicated when already present ────────
    from torch.building_templates import TEMPLATES as _TMPLS
    existing_layouts = [
        {
            "id": "LAYOUT_POKEMON_CENTER_1F",
            "name": "PokemonCenter_1F_Layout",
            "width": 14, "height": 9,
            "primary_tileset": "gTileset_Building",
            "secondary_tileset": "gTileset_PokemonCenter",
            "border_filepath": "data/layouts/PokemonCenter_1F/border.bin",
            "blockdata_filepath": "data/layouts/PokemonCenter_1F/map.bin",
        },
        {
            "id": "LAYOUT_POKEMON_CENTER_2F",
            "name": "PokemonCenter_2F_Layout",
            "width": 14, "height": 10,
            "primary_tileset": "gTileset_Building",
            "secondary_tileset": "gTileset_PokemonCenter",
            "border_filepath": "data/layouts/PokemonCenter_2F/border.bin",
            "blockdata_filepath": "data/layouts/PokemonCenter_2F/map.bin",
        },
    ]
    gp, cleanup = _make_game(extra_layouts=existing_layouts)
    try:
        clear_project_cache()
        # Pre-create layout dirs so stamper doesn't write binaries
        for d in ("PokemonCenter_1F", "PokemonCenter_2F"):
            dpath = os.path.join(gp, "data", "layouts", d)
            os.makedirs(dpath, exist_ok=True)
        stamp_pokecenter(gp, "TestTown", 5, 5)
        layouts = _load_json(os.path.join(gp, "data", "layouts",
                                          "layouts.json"))
        count = sum(1 for l in layouts["layouts"]
                    if l["id"] == "LAYOUT_POKEMON_CENTER_1F")
        _assert("pc: layout not duplicated",
                count == 1, f"found {count} entries")
    finally:
        cleanup()

    # ── layouts.json NOT modified when entries already exist ──────
    gp, cleanup = _make_game(extra_layouts=existing_layouts)
    try:
        clear_project_cache()
        for d in ("PokemonCenter_1F", "PokemonCenter_2F"):
            dpath = os.path.join(gp, "data", "layouts", d)
            os.makedirs(dpath, exist_ok=True)
        r = stamp_pokecenter(gp, "TestTown", 5, 5)
        _assert("pc: layouts.json not in modified when pre-existing",
                "data/layouts/layouts.json" not in r["modified_files"],
                f"modified={r['modified_files']}")
    finally:
        cleanup()

    # ── Nurse NPC in 1F ──────────────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_1F", "map.json"))
        objs = mj.get("object_events", [])
        _assert("pc: 1F has nurse NPC",
                len(objs) == 1 and objs[0]["graphics_id"] == "OBJ_EVENT_GFX_NURSE",
                f"got {len(objs)} objects")
        _assert("pc: nurse script label correct",
                objs[0]["script"] == "TestTown_PokemonCenter_1F_EventScript_Nurse",
                f"got {objs[0]['script']}")
        _assert("pc: nurse position correct",
                objs[0]["x"] == 7 and objs[0]["y"] == 2,
                f"got ({objs[0]['x']}, {objs[0]['y']})")
    finally:
        cleanup()

    # ── 2F has 3 attendant NPCs ──────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5, include_2f=True)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_2F", "map.json"))
        objs = mj.get("object_events", [])
        _assert("pc: 2F has 3 NPCs",
                len(objs) == 3, f"got {len(objs)}")
        scripts = [o["script"] for o in objs]
        _assert("pc: 2F NPCs use common scripts",
                all(s.startswith("Common_EventScript_") for s in scripts),
                f"scripts={scripts}")
    finally:
        cleanup()

    # ── 1F has 3 warps (with 2F) ─────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5, include_2f=True)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_1F", "map.json"))
        warps = mj.get("warp_events", [])
        _assert("pc: 1F has 3 warps with 2F",
                len(warps) == 3, f"got {len(warps)}")
    finally:
        cleanup()

    # ── 1F has 2 warps (without 2F) ──────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5, include_2f=False)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_1F", "map.json"))
        warps = mj.get("warp_events", [])
        _assert("pc: 1F has 2 warps without 2F",
                len(warps) == 2, f"got {len(warps)}")
    finally:
        cleanup()

    # ── Exit warps point back to parent ──────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_1F", "map.json"))
        warps = mj["warp_events"]
        _assert("pc: exit warp 0 dest is parent",
                warps[0]["dest_map"] == "MAP_TEST_TOWN",
                f"got {warps[0]['dest_map']}")
        _assert("pc: exit warp 0 dest_warp_id is '0' (new parent warp)",
                warps[0]["dest_warp_id"] == "0",
                f"got {warps[0]['dest_warp_id']}")
    finally:
        cleanup()

    # ── Stairs warp points to 2F ─────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5, include_2f=True)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_1F", "map.json"))
        stairs = mj["warp_events"][2]
        _assert("pc: stairs warp dest is 2F",
                stairs["dest_map"] == "MAP_TEST_TOWN_POKEMON_CENTER_2F",
                f"got {stairs['dest_map']}")
    finally:
        cleanup()

    # ── Parent map gets new warp ─────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        clear_project_cache()
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown", "map.json"))
        warps = mj.get("warp_events", [])
        _assert("pc: parent has new warp",
                len(warps) == 1, f"got {len(warps)}")
        _assert("pc: parent warp at door coords",
                warps[0]["x"] == 5 and warps[0]["y"] == 5,
                f"got ({warps[0]['x']}, {warps[0]['y']})")
        _assert("pc: parent warp dest_warp_id is '0'",
                warps[0]["dest_warp_id"] == "0",
                f"got {warps[0]['dest_warp_id']}")
    finally:
        cleanup()

    # ── scripts.pory generated with correct substitution ─────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        spath = os.path.join(gp, "data", "maps",
                             "TestTown_PokemonCenter_1F", "scripts.pory")
        with open(spath, "r") as f:
            content = f.read()
        _assert("pc: scripts.pory has correct label",
                "TestTown_PokemonCenter_1F_EventScript_Nurse" in content,
                "nurse label not found")
        _assert("pc: scripts.pory has no {map_name} placeholder",
                "{map_name}" not in content,
                "unsubstituted placeholder found")
    finally:
        cleanup()

    # ── Heal location created ────────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = stamp_pokecenter(gp, "TestTown", 5, 5)
        _assert("pc: heal_location_id returned",
                r["heal_location_id"] == "HEAL_LOCATION_TEST_TOWN",
                f"got {r['heal_location_id']}")
        hl = _load_json(os.path.join(gp, "src", "data",
                                      "heal_locations.json"))
        heals = hl["heal_locations"]
        _assert("pc: heal location in file",
                len(heals) == 1 and heals[0]["id"] == "HEAL_LOCATION_TEST_TOWN",
                f"got {heals}")
        _assert("pc: heal location coords match door",
                heals[0]["x"] == 5 and heals[0]["y"] == 5,
                f"got ({heals[0]['x']}, {heals[0]['y']})")
        _assert("pc: heal respawn_map is 1F",
                heals[0]["respawn_map"] == "MAP_TEST_TOWN_POKEMON_CENTER_1F",
                f"got {heals[0]['respawn_map']}")
    finally:
        cleanup()

    # ── Heal location skipped if exists ──────────────────────────
    gp, cleanup = _make_game(heal_locations=[
        {"id": "HEAL_LOCATION_TEST_TOWN", "map": "MAP_TEST_TOWN",
         "x": 1, "y": 1, "respawn_map": "MAP_X", "respawn_npc": "1"}
    ])
    try:
        clear_project_cache()
        r = stamp_pokecenter(gp, "TestTown", 5, 5)
        _assert("pc: heal skipped when exists",
                r["heal_location_id"] is None,
                f"got {r['heal_location_id']}")
        _assert("pc: heal skip warning",
                any("already exists" in w for w in r["warnings"]),
                f"warnings={r['warnings']}")
    finally:
        cleanup()

    # ── Maps added to specified group ────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5,
                         map_group="gMapGroup_IndoorTestTown")
        clear_project_cache()
        mg = _load_json(os.path.join(gp, "data", "maps",
                                      "map_groups.json"))
        indoor = mg.get("gMapGroup_IndoorTestTown", [])
        _assert("pc: maps in specified group",
                "TestTown_PokemonCenter_1F" in indoor
                and "TestTown_PokemonCenter_2F" in indoor,
                f"indoor group={indoor}")
    finally:
        cleanup()

    # ── Maps added to parent's group when map_group=None ─────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5, map_group=None)
        clear_project_cache()
        mg = _load_json(os.path.join(gp, "data", "maps",
                                      "map_groups.json"))
        town_group = mg.get("gMapGroup_TestTown", [])
        _assert("pc: maps in parent's group when None",
                "TestTown_PokemonCenter_1F" in town_group,
                f"group={town_group}")
    finally:
        cleanup()

    # ── Region map section inherited ─────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_1F", "map.json"))
        _assert("pc: region_map_section inherited",
                mj["region_map_section"] == "MAPSEC_TESTTOWN",
                f"got {mj['region_map_section']}")
    finally:
        cleanup()

    # ── All dest_warp_id values are strings ──────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        for mn in ("TestTown_PokemonCenter_1F", "TestTown_PokemonCenter_2F",
                    "TestTown"):
            mj = _load_json(os.path.join(gp, "data", "maps", mn, "map.json"))
            for w in mj.get("warp_events", []):
                _assert(f"pc: {mn} warp dest_warp_id is string",
                        isinstance(w["dest_warp_id"], str),
                        f"got {type(w['dest_warp_id']).__name__}")
    finally:
        cleanup()

    # ── No 'conditional' key in written map.json ─────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_1F", "map.json"))
        for w in mj.get("warp_events", []):
            _assert("pc: no conditional key in warps",
                    "conditional" not in w,
                    f"found conditional in warp: {w}")
    finally:
        cleanup()

    # ==================================================================
    # POKEMART STAMP TESTS
    # ==================================================================

    # ── Basic mart stamp ─────────────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = stamp_pokemart(gp, "TestTown", 8, 8)
        _assert("mart: stamp succeeds",
                r["success"], f"error={r.get('error')}")
        mart_dir = os.path.join(gp, "data", "maps", "TestTown_Mart")
        _assert("mart: folder exists",
                os.path.isdir(mart_dir), "mart folder missing")
    finally:
        cleanup()

    # ── No 2F created ────────────────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokemart(gp, "TestTown", 8, 8)
        _assert("mart: no 2F folder",
                not os.path.exists(os.path.join(gp, "data", "maps",
                                                 "TestTown_Mart_2F")),
                "2F folder exists")
    finally:
        cleanup()

    # ── No heal location ─────────────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = stamp_pokemart(gp, "TestTown", 8, 8)
        _assert("mart: no heal_location_id",
                r["heal_location_id"] is None,
                f"got {r['heal_location_id']}")
    finally:
        cleanup()

    # ── Clerk NPC at correct position ────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokemart(gp, "TestTown", 8, 8)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_Mart", "map.json"))
        objs = mj.get("object_events", [])
        _assert("mart: has clerk NPC",
                len(objs) == 1
                and objs[0]["graphics_id"] == "OBJ_EVENT_GFX_MART_EMPLOYEE",
                f"got {len(objs)} objects")
        _assert("mart: clerk position",
                objs[0]["x"] == 1 and objs[0]["y"] == 3,
                f"got ({objs[0]['x']}, {objs[0]['y']})")
    finally:
        cleanup()

    # ── Mart script template has item list ───────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokemart(gp, "TestTown", 8, 8)
        spath = os.path.join(gp, "data", "maps", "TestTown_Mart",
                             "scripts.pory")
        with open(spath, "r") as f:
            content = f.read()
        _assert("mart: script has mart items",
                "MartItems" in content and "ITEM_POKE_BALL" in content,
                "mart items missing from script")
        _assert("mart: script has clerk label",
                "TestTown_Mart_EventScript_Clerk" in content,
                "clerk label missing")
    finally:
        cleanup()

    # ── Shared LAYOUT_POKEMART created ───────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokemart(gp, "TestTown", 8, 8)
        lay = os.path.join(gp, "data", "layouts", "Mart")
        _assert("mart: shared layout dir created",
                os.path.isdir(lay), "Mart layout dir missing")
    finally:
        cleanup()

    # ── Exit warps point to parent ───────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokemart(gp, "TestTown", 8, 8)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_Mart", "map.json"))
        warps = mj["warp_events"]
        _assert("mart: 2 exit warps",
                len(warps) == 2, f"got {len(warps)}")
        _assert("mart: exit warp dest is parent",
                warps[0]["dest_map"] == "MAP_TEST_TOWN",
                f"got {warps[0]['dest_map']}")
    finally:
        cleanup()

    # ── Parent gets warp for mart ────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokemart(gp, "TestTown", 8, 8)
        clear_project_cache()
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown", "map.json"))
        warps = mj["warp_events"]
        _assert("mart: parent has new warp",
                len(warps) == 1, f"got {len(warps)}")
        _assert("mart: parent warp dest is mart",
                warps[0]["dest_map"] == "MAP_TEST_TOWN_MART",
                f"got {warps[0]['dest_map']}")
    finally:
        cleanup()

    # ==================================================================
    # EDGE CASE TESTS
    # ==================================================================

    # ── Town name override ───────────────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = stamp_pokecenter(gp, "TestTown", 5, 5, town_name="FooVille")
        _assert("edge: town_name override",
                "FooVille_PokemonCenter_1F" in r["maps_created"],
                f"maps={r['maps_created']}")
        _assert("edge: override folder exists",
                os.path.isdir(os.path.join(gp, "data", "maps",
                                            "FooVille_PokemonCenter_1F")),
                "folder missing")
    finally:
        cleanup()

    # ── Parent with no existing warps (warp_id = 0) ──────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_1F", "map.json"))
        _assert("edge: exit warp id is '0' when parent had no warps",
                mj["warp_events"][0]["dest_warp_id"] == "0",
                f"got {mj['warp_events'][0]['dest_warp_id']}")
    finally:
        cleanup()

    # ── Parent with existing warps (warp_id = N) ─────────────────
    existing_warps = [
        {"x": 1, "y": 1, "elevation": 0, "dest_map": "MAP_A", "dest_warp_id": "0"},
        {"x": 2, "y": 2, "elevation": 0, "dest_map": "MAP_B", "dest_warp_id": "0"},
    ]
    gp, cleanup = _make_game(parent_warps=existing_warps)
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_1F", "map.json"))
        _assert("edge: exit warp id is '2' when parent had 2 warps",
                mj["warp_events"][0]["dest_warp_id"] == "2",
                f"got {mj['warp_events'][0]['dest_warp_id']}")
        # Verify parent's new warp is at index 2
        clear_project_cache()
        pmj = _load_json(os.path.join(gp, "data", "maps",
                                       "TestTown", "map.json"))
        _assert("edge: parent now has 3 warps",
                len(pmj["warp_events"]) == 3,
                f"got {len(pmj['warp_events'])}")
    finally:
        cleanup()

    # ── New map group created when doesn't exist ─────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5,
                         map_group="gMapGroup_NewGroup")
        clear_project_cache()
        mg = _load_json(os.path.join(gp, "data", "maps",
                                      "map_groups.json"))
        _assert("edge: new group created",
                "gMapGroup_NewGroup" in mg["group_order"],
                f"order={mg['group_order']}")
        _assert("edge: maps in new group",
                "TestTown_PokemonCenter_1F" in mg["gMapGroup_NewGroup"],
                f"group={mg['gMapGroup_NewGroup']}")
    finally:
        cleanup()

    # ── Parent not in any group -> warning ───────────────────────
    gp, cleanup = _make_game()
    try:
        # Remove parent from its group
        clear_project_cache()
        mg_path = os.path.join(gp, "data", "maps", "map_groups.json")
        mg = _load_json(mg_path)
        mg["gMapGroup_TestTown"] = []
        with open(mg_path, "w") as f:
            json.dump(mg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        clear_project_cache()
        r = stamp_pokecenter(gp, "TestTown", 5, 5, map_group=None)
        _assert("edge: warning when parent not in group",
                any("not found in any" in w for w in r["warnings"]),
                f"warnings={r['warnings']}")
    finally:
        cleanup()

    # ── Validate with town_name override ─────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokecenter", "TestTown", 5, 5,
                           town_name="Override")
        _assert("edge: validate with town override",
                "Override_PokemonCenter_1F" in r["preview"]["maps_to_create"],
                f"maps={r['preview']['maps_to_create']}")
    finally:
        cleanup()

    # ── 2F warp back to 1F at correct warp ID ────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5, include_2f=True)
        mj2f = _load_json(os.path.join(gp, "data", "maps",
                                        "TestTown_PokemonCenter_2F",
                                        "map.json"))
        w0 = mj2f["warp_events"][0]
        _assert("edge: 2F warp 0 goes back to 1F",
                w0["dest_map"] == "MAP_TEST_TOWN_POKEMON_CENTER_1F",
                f"got {w0['dest_map']}")
        _assert("edge: 2F warp 0 dest_warp_id is '2' (stairs in 1F)",
                w0["dest_warp_id"] == "2",
                f"got {w0['dest_warp_id']}")
    finally:
        cleanup()

    # ── Stamp failure returns created_files so far ───────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = stamp_pokecenter(gp, "NoSuchParent", 5, 5)
        _assert("edge: failure returns created_files list",
                isinstance(r["created_files"], list),
                f"type={type(r['created_files'])}")
        _assert("edge: failure success is False",
                r["success"] is False,
                f"success={r['success']}")
    finally:
        cleanup()

    # ── Map type is MAP_TYPE_INDOOR ──────────────────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokecenter(gp, "TestTown", 5, 5)
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "TestTown_PokemonCenter_1F", "map.json"))
        _assert("pc: map_type is INDOOR",
                mj["map_type"] == "MAP_TYPE_INDOOR",
                f"got {mj['map_type']}")
    finally:
        cleanup()

    # ── Validate with include_2f=False preview ───────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokecenter", "TestTown", 5, 5,
                           include_2f=False)
        _assert("validate: no 2F in preview when disabled",
                len(r["preview"]["maps_to_create"]) == 1
                and "2F" not in r["preview"]["maps_to_create"][0],
                f"maps={r['preview']['maps_to_create']}")
    finally:
        cleanup()

    # ==================================================================
    # EVENT_SCRIPTS.S REGISTRATION TESTS
    # ==================================================================

    # ── PokéCenter stamp registers includes in event_scripts.s ───
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = stamp_pokecenter(gp, "TestTown", 5, 5)
        es_path = os.path.join(gp, "data", "event_scripts.s")
        with open(es_path, "r") as f:
            content = f.read()
        _assert("es: pokecenter 1F include added",
                "data/maps/TestTown_PokemonCenter_1F/scripts.inc" in content,
                "1F include missing from event_scripts.s")
        _assert("es: pokecenter 2F include added",
                "data/maps/TestTown_PokemonCenter_2F/scripts.inc" in content,
                "2F include missing from event_scripts.s")
        _assert("es: event_scripts.s in modified_files",
                "data/event_scripts.s" in r["modified_files"],
                f"modified={r['modified_files']}")
    finally:
        cleanup()

    # ── Mart stamp registers include in event_scripts.s ──────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = stamp_pokemart(gp, "TestTown", 8, 8)
        es_path = os.path.join(gp, "data", "event_scripts.s")
        with open(es_path, "r") as f:
            content = f.read()
        _assert("es: mart include added",
                "data/maps/TestTown_Mart/scripts.inc" in content,
                "mart include missing from event_scripts.s")
    finally:
        cleanup()

    # ── Duplicate registration doesn't double-add ────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokemart(gp, "TestTown", 8, 8)
        from torch.template_stamper import _register_event_scripts_include
        _register_event_scripts_include(gp, "TestTown_Mart", [])
        es_path = os.path.join(gp, "data", "event_scripts.s")
        with open(es_path, "r") as f:
            content = f.read()
        count = content.count("data/maps/TestTown_Mart/scripts.inc")
        _assert("es: no duplicate include",
                count == 1, f"found {count} includes")
    finally:
        cleanup()

    # ── Include inserted after last map include ──────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokemart(gp, "TestTown", 8, 8)
        es_path = os.path.join(gp, "data", "event_scripts.s")
        with open(es_path, "r") as f:
            lines = f.readlines()
        parent_idx = -1
        mart_idx = -1
        for i, line in enumerate(lines):
            if "data/maps/TestTown/scripts.inc" in line:
                parent_idx = i
            if "data/maps/TestTown_Mart/scripts.inc" in line:
                mart_idx = i
        _assert("es: mart include after parent include",
                mart_idx > parent_idx and parent_idx >= 0,
                f"parent={parent_idx}, mart={mart_idx}")
    finally:
        cleanup()

    # ── Validate preview includes event_scripts.s ────────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        r = validate_stamp(gp, "pokecenter", "TestTown", 5, 5)
        _assert("validate: preview includes event_scripts.s",
                "data/event_scripts.s" in r["preview"]["files_to_modify"],
                f"files_to_modify={r['preview']['files_to_modify']}")
    finally:
        cleanup()

    # ── Scripts.pory content correct after mart stamp ────────────
    gp, cleanup = _make_game()
    try:
        clear_project_cache()
        stamp_pokemart(gp, "TestTown", 8, 8)
        pory = os.path.join(gp, "data", "maps", "TestTown_Mart",
                            "scripts.pory")
        _assert("mart: scripts.pory exists",
                os.path.isfile(pory), "scripts.pory not found")
        with open(pory, "r") as f:
            content = f.read()
        _assert("mart: scripts.pory has mapscripts",
                "mapscripts" in content, "mapscripts missing")
        _assert("mart: scripts.pory has raw block",
                "raw `" in content, "raw block missing")
        _assert("mart: scripts.pory has ITEM_NONE",
                "ITEM_NONE" in content, "ITEM_NONE missing")
    finally:
        cleanup()

    # ==================================================================
    # CUSTOM STAMP TESTS
    # ==================================================================

    from torch.template_stamper import (
        stamp_custom, validate_custom_stamp,
        _deparameterize_events, _create_unique_layout,
    )
    from torch.custom_stamps import create_stamp, STAMPS_DIR

    def _make_stamp_game(stamp_name="TestStamp", stamp_script=None,
                         parent_name="TestTown", **kwargs):
        """Create a game dir with a source map suitable for stamp capture.

        Returns (game_path, stamp_id, cleanup_fn).
        """
        gp, cleanup_base = _make_game(parent_name=parent_name, **kwargs)

        # Create a source map to capture as a stamp
        source_name = "SourceInterior"
        src_dir = os.path.join(gp, "data", "maps", source_name)
        os.makedirs(src_dir, exist_ok=True)

        src_map_json = {
            "id": "MAP_SOURCE_INTERIOR",
            "name": source_name,
            "layout": "LAYOUT_SOURCE_INTERIOR",
            "music": "MUS_POKE_CENTER",
            "region_map_section": "MAPSEC_NONE",
            "requires_flash": False,
            "weather": "WEATHER_NONE",
            "map_type": "MAP_TYPE_INDOOR",
            "allow_cycling": False,
            "allow_escaping": False,
            "allow_running": False,
            "show_map_name": False,
            "battle_scene": "MAP_BATTLE_SCENE_NORMAL",
            "connections": None,
            "object_events": [
                {
                    "graphics_id": "OBJ_EVENT_GFX_WOMAN_1",
                    "x": 3, "y": 2, "elevation": 3,
                    "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                    "movement_range_x": 0, "movement_range_y": 0,
                    "trainer_type": "TRAINER_TYPE_NONE",
                    "trainer_sight_or_berry_tree_id": "0",
                    "script": "SourceInterior_EventScript_NPC",
                    "flag": "0",
                },
            ],
            "warp_events": [
                {"x": 4, "y": 7, "elevation": 0,
                 "dest_map": "MAP_TEST_TOWN", "dest_warp_id": "0"},
                {"x": 5, "y": 7, "elevation": 0,
                 "dest_map": "MAP_TEST_TOWN", "dest_warp_id": "0"},
            ],
            "coord_events": [],
            "bg_events": [],
        }
        with open(os.path.join(src_dir, "map.json"), "w") as f:
            json.dump(src_map_json, f, indent=2, ensure_ascii=False)

        # Write a scripts.pory for the source
        pory_content = stamp_script or (
            "mapscripts SourceInterior_MapScripts {}\n\n"
            "script SourceInterior_EventScript_NPC {\n"
            "    lock\n    faceplayer\n"
            '    msgbox(format("Hello!"), MSGBOX_DEFAULT)\n'
            "    release\n    end\n}\n"
        )
        with open(os.path.join(src_dir, "scripts.pory"), "w") as f:
            f.write(pory_content)

        # Add source layout to layouts.json
        clear_project_cache()
        layouts_path = os.path.join(gp, "data", "layouts", "layouts.json")
        with open(layouts_path, "r") as f:
            layouts = json.load(f)

        # Create source layout directory with binaries
        src_lay_dir = os.path.join(gp, "data", "layouts", source_name)
        os.makedirs(src_lay_dir, exist_ok=True)
        with open(os.path.join(src_lay_dir, "map.bin"), "wb") as f:
            f.write(b"\\x00" * 64)
        with open(os.path.join(src_lay_dir, "border.bin"), "wb") as f:
            f.write(b"\\x00" * 8)

        layouts["layouts"].append({
            "id": "LAYOUT_SOURCE_INTERIOR",
            "name": "SourceInterior_Layout",
            "width": 10,
            "height": 8,
            "primary_tileset": "gTileset_Building",
            "secondary_tileset": "gTileset_PokemonCenter",
            "border_filepath": "data/layouts/SourceInterior/border.bin",
            "blockdata_filepath": "data/layouts/SourceInterior/map.bin",
        })
        with open(layouts_path, "w") as f:
            json.dump(layouts, f, indent=2, ensure_ascii=False)

        # Create tileset dirs so validation passes
        for sub, name in [("primary", "building"),
                          ("secondary", "pokemoncenter")]:
            os.makedirs(
                os.path.join(gp, "data", "tilesets", sub, name),
                exist_ok=True)

        # Capture the stamp
        clear_project_cache()
        stamp = create_stamp(
            gp, source_name, stamp_name,
            exit_warp_indices=[0, 1],
            include_scripts=bool(stamp_script is not None
                                 or stamp_script is None),
            description="Test stamp",
        )
        stamp_id = stamp["id"]

        def cleanup():
            clear_project_cache()
            shutil.rmtree(gp, ignore_errors=True)

        return gp, stamp_id, cleanup

    # ── stamp_custom creates map + unique layout ────────────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r = stamp_custom(gp, sid, "TestTown", 5, 5)
        _assert("custom: stamp succeeds",
                r["success"], f"errors={r.get('errors')}")
        map_name = r["map_name"]
        map_dir = os.path.join(gp, "data", "maps", map_name)
        _assert("custom: map folder created",
                os.path.isdir(map_dir), f"missing {map_dir}")
        lay_dir = os.path.join(gp, "data", "layouts", map_name)
        _assert("custom: unique layout dir created",
                os.path.isdir(lay_dir), f"missing {lay_dir}")
        _assert("custom: layout map.bin exists",
                os.path.isfile(os.path.join(lay_dir, "map.bin")),
                "map.bin missing")
        _assert("custom: layout border.bin exists",
                os.path.isfile(os.path.join(lay_dir, "border.bin")),
                "border.bin missing")
    finally:
        cleanup()

    # ── stamp_custom warp cross-linking ─────────────────────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r = stamp_custom(gp, sid, "TestTown", 5, 5)
        map_name = r["map_name"]
        # Child exit warps point to parent
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      map_name, "map.json"))
        warps = mj["warp_events"]
        _assert("custom: exit warp points to parent",
                warps[0]["dest_map"] == "MAP_TEST_TOWN",
                f"got {warps[0]['dest_map']}")
        _assert("custom: exit warp dest_warp_id correct",
                warps[0]["dest_warp_id"] == "0",
                f"got {warps[0]['dest_warp_id']}")
        # Parent map gets new warp
        clear_project_cache()
        pmj = _load_json(os.path.join(gp, "data", "maps",
                                       "TestTown", "map.json"))
        pwarps = pmj["warp_events"]
        _assert("custom: parent has new warp",
                len(pwarps) == 1, f"got {len(pwarps)}")
        _assert("custom: parent warp at door coords",
                pwarps[0]["x"] == 5 and pwarps[0]["y"] == 5,
                f"got ({pwarps[0]['x']}, {pwarps[0]['y']})")
    finally:
        cleanup()

    # ── stamp_custom with script_template ───────────────────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r = stamp_custom(gp, sid, "TestTown", 5, 5)
        map_name = r["map_name"]
        spath = os.path.join(gp, "data", "maps", map_name, "scripts.pory")
        _assert("custom: scripts.pory exists",
                os.path.isfile(spath), "scripts.pory missing")
        with open(spath, "r") as f:
            content = f.read()
        _assert("custom: scripts.pory has no {map_name} placeholder",
                "{map_name}" not in content,
                "unsubstituted placeholder found")
        _assert("custom: scripts.pory has actual map name",
                map_name in content,
                f"{map_name} not found in scripts.pory")
    finally:
        cleanup()

    # ── stamp_custom with no script_template (default stub) ─────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        # Modify stamp manifest to remove script_template
        manifest_path = os.path.join(
            gp, STAMPS_DIR, sid, "manifest.json")
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
        manifest["script_template"] = ""
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        r = stamp_custom(gp, sid, "TestTown", 5, 5)
        map_name = r["map_name"]
        spath = os.path.join(gp, "data", "maps", map_name, "scripts.pory")
        with open(spath, "r") as f:
            content = f.read()
        _assert("custom: default stub has mapscripts",
                "mapscripts" in content and "_MapScripts" in content,
                f"content={content!r}")
    finally:
        cleanup()

    # ── _create_unique_layout adds entry to layouts.json ────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        from torch.custom_stamps import load_stamp as _load_stamp
        stamp = _load_stamp(gp, sid)
        stamp_dir = os.path.join(gp, STAMPS_DIR, sid)
        result = _create_unique_layout(
            gp, "MyCustomMap", stamp, stamp_dir)
        _assert("layout: returns layout name",
                result == "MyCustomMap_Layout",
                f"got {result}")
        # Check layouts.json
        layouts = _load_json(os.path.join(
            gp, "data", "layouts", "layouts.json"))
        ids = [l["id"] for l in layouts["layouts"]]
        _assert("layout: LAYOUT_MY_CUSTOM_MAP in layouts.json",
                "LAYOUT_MY_CUSTOM_MAP" in ids,
                f"ids={ids}")
        # Check directory
        lay_dir = os.path.join(gp, "data", "layouts", "MyCustomMap")
        _assert("layout: directory created",
                os.path.isdir(lay_dir), "dir missing")
    finally:
        cleanup()

    # ── _deparameterize_events replaces placeholders ────────────
    events = [
        {"script": "{map_name}_EventScript_NPC",
         "dest_map": "MAP_{MAP_CONST}", "x": 1},
        {"script": "Common_EventScript_Foo", "y": 2},
    ]
    result = _deparameterize_events(events, "MyMap", "MY_MAP")
    _assert("deparam: {map_name} replaced",
            result[0]["script"] == "MyMap_EventScript_NPC",
            f"got {result[0]['script']}")
    _assert("deparam: {MAP_CONST} replaced",
            result[0]["dest_map"] == "MAP_MY_MAP",
            f"got {result[0]['dest_map']}")
    _assert("deparam: non-placeholder unchanged",
            result[1]["script"] == "Common_EventScript_Foo",
            f"got {result[1]['script']}")
    _assert("deparam: original not modified",
            events[0]["script"] == "{map_name}_EventScript_NPC",
            "original was modified")

    # ── Two stamps from same source create independent layouts ──
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r1 = stamp_custom(gp, sid, "TestTown", 5, 5,
                          map_name="Interior_A")
        _assert("custom: first stamp succeeds",
                r1["success"], f"errors={r1.get('errors')}")
        r2 = stamp_custom(gp, sid, "TestTown", 6, 6,
                          map_name="Interior_B")
        _assert("custom: second stamp succeeds",
                r2["success"], f"errors={r2.get('errors')}")
        lay_a = os.path.join(gp, "data", "layouts", "Interior_A")
        lay_b = os.path.join(gp, "data", "layouts", "Interior_B")
        _assert("custom: layout A exists",
                os.path.isdir(lay_a), "layout A missing")
        _assert("custom: layout B exists",
                os.path.isdir(lay_b), "layout B missing")
        # Both have separate entries in layouts.json
        layouts = _load_json(os.path.join(
            gp, "data", "layouts", "layouts.json"))
        ids = [l["id"] for l in layouts["layouts"]]
        _assert("custom: both layouts in layouts.json",
                "LAYOUT_INTERIOR_A" in ids
                and "LAYOUT_INTERIOR_B" in ids,
                f"ids={ids}")
    finally:
        cleanup()

    # ── validate_custom_stamp delegates correctly ───────────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r = validate_custom_stamp(gp, sid, "TestTown", 5, 5)
        _assert("validate_custom: returns valid",
                r["valid"], f"errors={r['errors']}")
        _assert("validate_custom: has suggested_name",
                len(r["suggested_name"]) > 0,
                f"suggested_name={r['suggested_name']}")
    finally:
        cleanup()

    # ── stamp_custom with map_name override ─────────────────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r = stamp_custom(gp, sid, "TestTown", 5, 5,
                         map_name="CustomNamedMap")
        _assert("custom: name override accepted",
                r["map_name"] == "CustomNamedMap",
                f"got {r['map_name']}")
        _assert("custom: override dir exists",
                os.path.isdir(os.path.join(
                    gp, "data", "maps", "CustomNamedMap")),
                "directory missing")
    finally:
        cleanup()

    # ── Error: missing stamp ────────────────────────────────────
    gp, cleanup_base = _make_game()
    try:
        clear_project_cache()
        r = stamp_custom(gp, "nonexistent_stamp", "TestTown", 5, 5)
        _assert("custom: missing stamp -> failure",
                not r["success"],
                f"success={r['success']}")
        _assert("custom: missing stamp error message",
                any("not found" in e for e in r["errors"]),
                f"errors={r['errors']}")
    finally:
        cleanup_base()

    # ── Error: invalid parent map ───────────────────────────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r = stamp_custom(gp, sid, "NoSuchParent", 5, 5)
        _assert("custom: invalid parent -> failure",
                not r["success"],
                f"success={r['success']}")
        _assert("custom: invalid parent error message",
                any("not found" in e.lower() for e in r["errors"]),
                f"errors={r['errors']}")
    finally:
        cleanup()

    # ── stamp_custom adds map to map_groups.json ────────────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r = stamp_custom(gp, sid, "TestTown", 5, 5,
                         map_group="gMapGroup_IndoorTestTown")
        map_name = r["map_name"]
        clear_project_cache()
        mg = _load_json(os.path.join(gp, "data", "maps",
                                      "map_groups.json"))
        indoor = mg.get("gMapGroup_IndoorTestTown", [])
        _assert("custom: map in specified group",
                map_name in indoor,
                f"indoor group={indoor}")
    finally:
        cleanup()

    # ── stamp_custom registers event_scripts.s ──────────────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r = stamp_custom(gp, sid, "TestTown", 5, 5)
        map_name = r["map_name"]
        es_path = os.path.join(gp, "data", "event_scripts.s")
        with open(es_path, "r") as f:
            content = f.read()
        _assert("custom: event_scripts.s include added",
                f"data/maps/{map_name}/scripts.inc" in content,
                "include missing from event_scripts.s")
    finally:
        cleanup()

    # ── stamp_custom map.json has correct layout id ─────────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r = stamp_custom(gp, sid, "TestTown", 5, 5,
                         map_name="MyRoom")
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "MyRoom", "map.json"))
        _assert("custom: map.json layout is unique",
                mj["layout"] == "LAYOUT_MY_ROOM",
                f"got {mj['layout']}")
        _assert("custom: map.json id correct",
                mj["id"] == "MAP_MY_ROOM",
                f"got {mj['id']}")
        _assert("custom: map.json inherits region_map_section",
                mj["region_map_section"] == "MAPSEC_TESTTOWN",
                f"got {mj['region_map_section']}")
    finally:
        cleanup()

    # ── stamp_custom NPC script labels deparameterized ──────────
    gp, sid, cleanup = _make_stamp_game()
    try:
        clear_project_cache()
        r = stamp_custom(gp, sid, "TestTown", 5, 5,
                         map_name="CoolRoom")
        mj = _load_json(os.path.join(gp, "data", "maps",
                                      "CoolRoom", "map.json"))
        objs = mj.get("object_events", [])
        _assert("custom: has NPC",
                len(objs) >= 1, f"got {len(objs)} objects")
        # The script label should contain the actual map name, not {map_name}
        script = objs[0].get("script", "")
        _assert("custom: NPC script has actual name",
                "CoolRoom" in script and "{map_name}" not in script,
                f"got {script}")
    finally:
        cleanup()
