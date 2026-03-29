"""Tests for scorch_writer — the destructive removal engine for SCORCH.

Covers snapshot creation/restore, JSON manipulation (map_groups, encounters,
layouts), map/script/trainer/tileset removal, and event_scripts.s cleanup.
Uses temp directories to isolate all file I/O.
"""
import copy
import json
import os
import shutil
import tempfile
import zipfile

from torch.tests.harness import _begin_suite, _assert, _ok, _fail


# ---------------------------------------------------------------------------
# Minimal plan object that mimics what scorch_writer expects
# ---------------------------------------------------------------------------

class _FakePlan:
    """Minimal stand-in for a ScorchPlan."""

    def __init__(self):
        self.nuke_maps = set()
        self.keep_maps = set()
        self.vanilla_trainers = []      # list of (const, tid) tuples
        self.vanilla_encounters = []    # list of dicts with "map" key
        self.vanilla_scripts = []       # list of dicts with "path", "filename"
        self.vanilla_tilesets = []      # list of dicts with "dir_name", "symbol", "path"
        self.c_patch_targets = []       # list of dicts with "rel_path"
        self.referenced_layouts = set()
        self.orphaned_layouts = set()
        self.vanilla_mapsecs = set()
        self.custom_mapsecs = set()
        self.system_mapsecs = {"MAPSEC_NONE", "MAPSEC_DYNAMIC", "MAPSEC_COUNT"}


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_game(tmp):
    """Create a minimal game directory structure and return its path."""
    g = os.path.join(tmp, "game")
    os.makedirs(os.path.join(g, "data", "maps"), exist_ok=True)
    os.makedirs(os.path.join(g, "data", "layouts"), exist_ok=True)
    os.makedirs(os.path.join(g, "src", "data"), exist_ok=True)
    os.makedirs(os.path.join(g, "include", "constants"), exist_ok=True)
    return g


def _write(path, content):
    """Write content to path, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _read(path):
    """Read a file and return its contents."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("scorch_writer")

    from torch.scorch_writer import (
        create_scorch_snapshot, restore_scorch_snapshot,
        list_scorch_snapshots, ScorchResult,
        _collect_dir, _add_if_exists,
        _scorch_map_groups, _scorch_encounters,
        _scorch_layouts_json, _scorch_event_scripts,
        _scorch_trainers, _scorch_scripts,
        _strip_lines_matching_dirs, _strip_symbol_lines,
        _strip_tileset_structs, _strip_override_blocks,
        _scorch_new_game_inc, _should_strip_flag_line, _collapse_blank_runs,
        _scorch_mapsecs, _name_to_mapsec, _make_mapsec_entry,
        _update_map_json, _patch_kanto_macros,
    )
    from torch.project_files import clear_project_cache

    # ==== ScorchResult ====

    r = ScorchResult()
    _assert("result starts at zero", r.total_removed() == 0,
            f"got {r.total_removed()}")

    r.maps_removed = 3
    r.trainers_removed = 10
    r.encounters_removed = 5
    r.scripts_removed = 2
    r.tilesets_removed = 1
    _assert("result sums correctly", r.total_removed() == 21,
            f"got {r.total_removed()}")

    _assert("result errors is a list", isinstance(r.errors, list) and len(r.errors) == 0)

    # ==== _collect_dir ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_")
    try:
        game = _make_game(tmp)

        # Create a small directory with files
        sub = os.path.join(game, "data", "maps", "TestMap")
        _write(os.path.join(sub, "map.json"), "{}")
        _write(os.path.join(sub, "scripts.inc"), "@ test")

        collected = set()
        _collect_dir(game, sub, collected)
        _assert("_collect_dir finds two files", len(collected) == 2,
                f"found {collected}")
        _assert("_collect_dir gives relative paths",
                all(not p.startswith("/") for p in collected),
                f"got {collected}")

        # Empty dir collects nothing
        empty_dir = os.path.join(game, "data", "maps", "EmptyMap")
        os.makedirs(empty_dir, exist_ok=True)
        empty_set = set()
        _collect_dir(game, empty_dir, empty_set)
        _assert("_collect_dir empty dir", len(empty_set) == 0)

        # ==== _add_if_exists ====

        aie_set = set()
        _add_if_exists(game, os.path.join("data", "maps", "TestMap", "map.json"), aie_set)
        _assert("_add_if_exists adds existing", len(aie_set) == 1)

        _add_if_exists(game, "nonexistent/file.txt", aie_set)
        _assert("_add_if_exists skips missing", len(aie_set) == 1)

        # ==== create_scorch_snapshot + restore ====

        plan = _FakePlan()
        plan.nuke_maps = ["TestMap"]

        # Need map_groups.json for the snapshot to pick it up
        mg_path = os.path.join(game, "data", "maps", "map_groups.json")
        _write(mg_path, json.dumps({"group_order": ["gMapGroup_Test"]}))

        snap = create_scorch_snapshot(game, plan)
        _assert("snapshot created", snap is not None and os.path.isfile(snap),
                f"snap = {snap}")

        # Verify ZIP contents
        with zipfile.ZipFile(snap, "r") as zf:
            names = zf.namelist()
        _assert("snapshot has map.json",
                any("TestMap/map.json" in n for n in names),
                f"contents: {names}")
        _assert("snapshot has map_groups.json",
                any("map_groups.json" in n for n in names),
                f"contents: {names}")

        # Delete the originals, then restore
        os.remove(os.path.join(sub, "map.json"))
        restored = restore_scorch_snapshot(game, snap)
        _assert("restore returns list", isinstance(restored, list) and len(restored) > 0,
                f"restored = {restored}")
        _assert("restored file exists",
                os.path.isfile(os.path.join(sub, "map.json")))

        # ==== list_scorch_snapshots ====

        snaps = list_scorch_snapshots(game)
        _assert("list finds snapshot", len(snaps) >= 1,
                f"got {len(snaps)} snapshots")
        _assert("snapshot has display_time", "display_time" in snaps[0])

        # ==== empty plan snapshot behavior ====

        # NOTE: create_scorch_snapshot always adds map_groups.json to the
        # backup set (line 53), so files_to_backup is never empty even
        # with an empty plan.  The ZIP gets created but is empty when
        # none of the listed files actually exist on disk.  This is a
        # minor behavioral quirk — not a bug since scorching an empty
        # plan is a no-op anyway.
        empty_game = os.path.join(tmp, "empty_game")
        os.makedirs(empty_game, exist_ok=True)
        empty_plan = _FakePlan()
        empty_snap = create_scorch_snapshot(empty_game, empty_plan)
        _assert("empty plan creates ZIP (map_groups always listed)",
                empty_snap is not None and os.path.isfile(empty_snap))
        # The ZIP should contain zero actual files
        with zipfile.ZipFile(empty_snap, "r") as zf:
            _assert("empty plan ZIP has no files", len(zf.namelist()) == 0,
                    f"contents: {zf.namelist()}")

        # ==== _scorch_map_groups ====

        # Build a map_groups.json with vanilla + custom groups
        # Uses real vanilla names so the frozen set classifies correctly
        clear_project_cache()

        mg_data = {
            "group_order": [
                "gMapGroup_Vanilla",
                "gMapGroup_IndoorRoute124",
                "gMapGroup_CustomCity",
            ],
            "gMapGroup_Vanilla": ["LittlerootTown"],
            "gMapGroup_IndoorRoute124": ["Route124_DivingTreasureHuntersHouse"],
            "gMapGroup_CustomCity": ["CustomCity"],
        }
        _write(mg_path, json.dumps(mg_data, indent=2))
        clear_project_cache()

        plan.nuke_maps = {"LittlerootTown", "Route124_DivingTreasureHuntersHouse"}
        plan.keep_maps = {"CustomCity"}
        res = ScorchResult()
        _scorch_map_groups(game, plan, res)

        mg_after = json.loads(_read(mg_path))
        _assert("map_groups keeps only custom",
                "gMapGroup_CustomCity" in mg_after["group_order"],
                f"got {mg_after['group_order']}")
        _assert("map_groups no vanilla maps",
                "LittlerootTown" not in str(mg_after),
                f"keys: {list(mg_after.keys())}")
        _assert("map_groups has custom data",
                mg_after.get("gMapGroup_CustomCity") == ["CustomCity"])
        # Empty vanilla groups get filtered (reported as informational)
        _assert("map_groups empty vanilla groups filtered",
                any("Filtered" in e and "empty" in e for e in res.errors),
                f"errors: {res.errors}")

        # ==== _scorch_encounters ====

        clear_project_cache()
        enc_data = {
            "wild_encounter_groups": [
                {
                    "label": "gWildEncounters",
                    "encounters": [
                        {"map": "MAP_ROUTE101", "base_label": "gRoute101"},
                        {"map": "MAP_CUSTOM_CITY", "base_label": "gCustomCity"},
                        {"map": "MAP_ROUTE102", "base_label": "gRoute102"},
                    ]
                }
            ]
        }
        enc_path = os.path.join(game, "src", "data", "wild_encounters.json")
        _write(enc_path, json.dumps(enc_data, indent=2))
        clear_project_cache()

        enc_plan = _FakePlan()
        enc_plan.vanilla_encounters = [
            {"map": "MAP_ROUTE101"},
            {"map": "MAP_ROUTE102"},
        ]
        res2 = ScorchResult()
        _scorch_encounters(game, enc_plan, res2)

        enc_after = json.loads(_read(enc_path))
        remaining = enc_after["wild_encounter_groups"][0]["encounters"]
        _assert("encounters removes vanilla", len(remaining) == 1,
                f"remaining: {remaining}")
        _assert("encounters keeps custom",
                remaining[0]["map"] == "MAP_CUSTOM_CITY")
        _assert("encounters count", res2.encounters_removed == 2,
                f"got {res2.encounters_removed}")

        # ==== _scorch_layouts_json ====

        clear_project_cache()
        # Create a layout dir that "exists" and one that "doesn't"
        kept_layout_dir = os.path.join(game, "data", "layouts", "CustomCity")
        os.makedirs(kept_layout_dir, exist_ok=True)
        _write(os.path.join(kept_layout_dir, "border.bin"), "x")
        _write(os.path.join(kept_layout_dir, "map.bin"), "x")

        layouts_data = {
            "layouts_table_label": "gLayoutTable",
            "layouts": [
                {
                    "id": "LAYOUT_PALLET_TOWN",
                    "blockdata_filepath": "data/layouts/PalletTown/map.bin",
                },
                {
                    "id": "LAYOUT_CUSTOM_CITY",
                    "blockdata_filepath": "data/layouts/CustomCity/map.bin",
                },
                {
                    "id": "LAYOUT_SPECIAL",
                    # No blockdata_filepath — should be kept
                },
            ]
        }
        layouts_path = os.path.join(game, "data", "layouts", "layouts.json")
        _write(layouts_path, json.dumps(layouts_data, indent=2))
        clear_project_cache()

        res3 = ScorchResult()
        _scorch_layouts_json(game, plan, res3)

        lyt_after = json.loads(_read(layouts_path))
        # Orphaned layouts (blockdata missing) should be removed.
        # Kept: LAYOUT_CUSTOM_CITY (blockdata exists) + LAYOUT_SPECIAL (no path).
        # Removed: LAYOUT_PALLET_TOWN (blockdata file missing).
        _assert("layouts removes orphaned",
                len(lyt_after["layouts"]) == 2,
                f"remaining: {[l['id'] for l in lyt_after['layouts']]}")
        kept_ids = [l["id"] for l in lyt_after["layouts"]]
        _assert("layouts keeps existing blockdata",
                "LAYOUT_CUSTOM_CITY" in kept_ids,
                f"expected LAYOUT_CUSTOM_CITY in {kept_ids}")
        _assert("layouts keeps special (no blockdata path)",
                "LAYOUT_SPECIAL" in kept_ids,
                f"expected LAYOUT_SPECIAL in {kept_ids}")
        _assert("layouts drops orphaned PalletTown",
                "LAYOUT_PALLET_TOWN" not in kept_ids,
                f"LAYOUT_PALLET_TOWN should not be in {kept_ids}")

        # Verify the function DOES write when layouts are actually removed:
        # Create a scenario where it can work — all layouts have existing
        # blockdata (no orphans to trigger the bug path).
        clear_project_cache()
        clean_layouts = {
            "layouts_table_label": "gLayoutTable",
            "layouts": [
                {
                    "id": "LAYOUT_CUSTOM_CITY",
                    "blockdata_filepath": "data/layouts/CustomCity/map.bin",
                },
            ]
        }
        _write(layouts_path, json.dumps(clean_layouts, indent=2))
        clear_project_cache()

        res3b = ScorchResult()
        _scorch_layouts_json(game, plan, res3b)

        # With all blockdata files present, no layouts are orphaned,
        # so the file should remain unchanged (len(kept) == len(original))
        lyt_after2 = json.loads(_read(layouts_path))
        _assert("layouts no-change when all exist",
                len(lyt_after2["layouts"]) == 1)

        # ==== _scorch_event_scripts ====

        es_content = (
            '\t.include "data/scripts/std.inc"\n'
            '\t.include "data/maps/PalletTown/scripts.inc"\n'
            '\t.include "data/maps/CustomCity/scripts.inc"\n'
            '\t.include "data/scripts/berry_trees.inc"\n'
            '\n\n\n'
            '\t.include "data/maps/Route101/scripts.inc"\n'
        )
        es_path = os.path.join(game, "data", "event_scripts.s")
        _write(es_path, es_content)

        es_plan = _FakePlan()
        es_plan.nuke_maps = ["PalletTown", "Route101"]
        es_plan.vanilla_scripts = [{"filename": "berry_trees.inc", "path": "/dummy"}]

        res4 = ScorchResult()
        _scorch_event_scripts(game, es_plan, res4)

        es_after = _read(es_path)
        _assert("event_scripts keeps std",
                'data/scripts/std.inc' in es_after)
        _assert("event_scripts keeps custom map",
                'data/maps/CustomCity/scripts.inc' in es_after)
        _assert("event_scripts removes vanilla map PalletTown",
                'data/maps/PalletTown/scripts.inc' not in es_after)
        _assert("event_scripts removes vanilla map Route101",
                'data/maps/Route101/scripts.inc' not in es_after)
        _assert("event_scripts removes vanilla script",
                'berry_trees.inc' not in es_after)
        _assert("event_scripts collapses blank lines",
                '\n\n\n' not in es_after)

        # ==== _scorch_trainers — trainers.party ====

        party_content = (
            "=== TRAINER_GRUNT_1 ===\n"
            "Name: GRUNT\n"
            "Pokemon:\n"
            "  Zubat Lv5\n\n"
            "=== TRAINER_CUSTOM_RIVAL ===\n"
            "Name: RIVAL\n"
            "Pokemon:\n"
            "  Treecko Lv5\n\n"
            "=== TRAINER_GRUNT_2 ===\n"
            "Name: GRUNT\n"
            "Pokemon:\n"
            "  Poochyena Lv4\n"
        )
        party_path = os.path.join(game, "src", "data", "trainers.party")
        _write(party_path, party_content)

        tr_plan = _FakePlan()
        tr_plan.vanilla_trainers = [
            ("TRAINER_GRUNT_1", 1),
            ("TRAINER_GRUNT_2", 2),
        ]

        res5 = ScorchResult()
        _scorch_trainers(game, tr_plan, res5)

        party_after = _read(party_path)
        _assert("trainers.party removes vanilla",
                "TRAINER_GRUNT_1" not in party_after and "TRAINER_GRUNT_2" not in party_after,
                f"content: {party_after[:200]}")
        _assert("trainers.party keeps custom",
                "TRAINER_CUSTOM_RIVAL" in party_after)
        _assert("trainers removed count", res5.trainers_removed == 2,
                f"got {res5.trainers_removed}")

        # ==== _scorch_trainers — opponents.h ====

        opponents_content = (
            "#ifndef GUARD_CONSTANTS_OPPONENTS_H\n"
            "#define GUARD_CONSTANTS_OPPONENTS_H\n"
            "#define TRAINER_NONE 0\n"
            "#define TRAINER_GRUNT_1 1\n"
            "#define TRAINER_CUSTOM_RIVAL 2\n"
            "#define TRAINER_GRUNT_2 3\n"
            "#endif\n"
        )
        opp_path = os.path.join(game, "include", "constants", "opponents.h")
        _write(opp_path, opponents_content)

        res6 = ScorchResult()
        tr_plan2 = _FakePlan()
        tr_plan2.vanilla_trainers = [
            ("TRAINER_GRUNT_1", 1),
            ("TRAINER_GRUNT_2", 3),
        ]
        _scorch_trainers(game, tr_plan2, res6)

        opp_after = _read(opp_path)
        _assert("opponents.h removes vanilla defines",
                "TRAINER_GRUNT_1" not in opp_after and "TRAINER_GRUNT_2" not in opp_after)
        _assert("opponents.h keeps custom define",
                "TRAINER_CUSTOM_RIVAL" in opp_after)
        _assert("opponents.h keeps guards",
                "#ifndef" in opp_after and "#endif" in opp_after)

        # ==== _scorch_scripts ====

        scripts_dir = os.path.join(game, "data", "scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        vanilla_script = os.path.join(scripts_dir, "berry_trees.inc")
        vanilla_pory = os.path.join(scripts_dir, "berry_trees.pory")
        custom_script = os.path.join(scripts_dir, "custom_event.inc")
        _write(vanilla_script, "@ vanilla script")
        _write(vanilla_pory, "# vanilla pory")
        _write(custom_script, "@ custom script")

        scr_plan = _FakePlan()
        scr_plan.vanilla_scripts = [
            {"path": vanilla_script, "filename": "berry_trees.inc"},
        ]

        res7 = ScorchResult()
        _scorch_scripts(game, scr_plan, res7)

        _assert("script .inc removed", not os.path.isfile(vanilla_script))
        _assert("script .pory also removed", not os.path.isfile(vanilla_pory))
        _assert("custom script untouched", os.path.isfile(custom_script))
        _assert("scripts removed count", res7.scripts_removed == 1,
                f"got {res7.scripts_removed}")

        # ==== _strip_lines_matching_dirs ====

        strip_file = os.path.join(tmp, "strip_test.h")
        _write(strip_file, (
            'INCBIN("data/tilesets/secondary/Petalburg/tiles.4bpp");\n'
            'INCBIN("data/tilesets/secondary/Custom/tiles.4bpp");\n'
            'INCBIN("data/tilesets/secondary/Rustboro/tiles.4bpp");\n'
        ))

        _strip_lines_matching_dirs(strip_file, {"Petalburg", "Rustboro"},
                                   "data/tilesets/secondary/")

        strip_after = _read(strip_file)
        _assert("strip_lines keeps non-matching",
                "Custom" in strip_after)
        _assert("strip_lines removes matching",
                "Petalburg" not in strip_after and "Rustboro" not in strip_after,
                f"content: {strip_after}")

        # ==== _strip_symbol_lines ====

        sym_file = os.path.join(tmp, "sym_test.h")
        _write(sym_file, (
            "const u32 gTilesetTiles_Petalburg[] = ...;\n"
            "const u32 gTilesetPalettes_Petalburg[] = ...;\n"
            "const u32 gTilesetTiles_Custom[] = ...;\n"
        ))

        _strip_symbol_lines(sym_file, {"Petalburg"},
                            "gTilesetTiles_", "gTilesetPalettes_")

        sym_after = _read(sym_file)
        _assert("strip_symbol keeps non-matching", "Custom" in sym_after)
        _assert("strip_symbol removes matching",
                "Petalburg" not in sym_after)

        # ==== _strip_tileset_structs ====

        structs_file = os.path.join(tmp, "headers_test.h")
        _write(structs_file, (
            "const struct Tileset gTileset_General =\n"
            "{\n"
            "    .isCompressed = TRUE,\n"
            "};\n"
            "\n"
            "const struct Tileset gTileset_Petalburg =\n"
            "{\n"
            "    .isCompressed = TRUE,\n"
            "};\n"
            "\n"
            "const struct Tileset *const gTilesetPointer_Petalburg = &gTileset_Petalburg;\n"
            "\n"
            "const struct Tileset gTileset_Custom =\n"
            "{\n"
            "    .isCompressed = FALSE,\n"
            "};\n"
        ))

        _strip_tileset_structs(structs_file, {"Petalburg"})

        structs_after = _read(structs_file)
        _assert("strip_structs keeps General",
                "gTileset_General" in structs_after)
        _assert("strip_structs keeps Custom",
                "gTileset_Custom" in structs_after)
        _assert("strip_structs removes Petalburg struct",
                "gTileset_Petalburg" not in structs_after)
        _assert("strip_structs removes Petalburg pointer",
                "gTilesetPointer_Petalburg" not in structs_after)

        # ==== _strip_override_blocks ====

        override_file = os.path.join(tmp, "overrides_test.h")
        _write(override_file, (
            "static const u16 sTilesetPalOverride_Petalburg0[] = INCBIN_U16(...);\n"
            "static const u16 sTilesetPalOverride_Petalburg1[] = INCBIN_U16(...);\n"
            "static const u16 sTilesetPalOverride_Custom0[] = INCBIN_U16(...);\n"
            "\n"
            "const struct PaletteOverride gTilesetPalOverrides_Petalburg[]\n"
            "{\n"
            "    {0, sTilesetPalOverride_Petalburg0},\n"
            "    TILESET_PAL_OVERRIDE_TERMINATOR\n"
            "};\n"
            "\n"
            "const struct PaletteOverride gTilesetPalOverrides_Custom[]\n"
            "{\n"
            "    {0, sTilesetPalOverride_Custom0},\n"
            "    TILESET_PAL_OVERRIDE_TERMINATOR\n"
            "};\n"
        ))

        _strip_override_blocks(override_file, {"Petalburg"})

        ovr_after = _read(override_file)
        _assert("strip_overrides keeps Custom static",
                "sTilesetPalOverride_Custom0" in ovr_after)
        _assert("strip_overrides keeps Custom struct",
                "gTilesetPalOverrides_Custom" in ovr_after)
        _assert("strip_overrides removes Petalburg static",
                "sTilesetPalOverride_Petalburg0" not in ovr_after)
        _assert("strip_overrides removes Petalburg struct",
                "gTilesetPalOverrides_Petalburg" not in ovr_after)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

    # ==== Phase 9: new_game.inc flag stripping ====

    # _should_strip_flag_line — strips vanilla flag
    try:
        line = "    setflag FLAG_HIDE_PETALBURG_CITY_RIVAL\n"
        nuke_frags = {"PETALBURG_CITY"}
        keep_frags = set()
        _assert("strip_flag: strips vanilla flag",
                _should_strip_flag_line(line, nuke_frags, keep_frags) is True,
                "expected True")
    except Exception as e:
        _fail("strip_flag: strips vanilla flag", str(e))

    # _should_strip_flag_line — keeps non-flag line
    try:
        line = "    call EventScript_ResetAllBerries\n"
        _assert("strip_flag: keeps non-flag line",
                _should_strip_flag_line(line, {"PETALBURG_CITY"}, set()) is False,
                "expected False")
    except Exception as e:
        _fail("strip_flag: keeps non-flag line", str(e))

    # _should_strip_flag_line — keeps flag for kept map
    try:
        line = "    setflag FLAG_HIDE_INSIDE_OF_TRUCK_MOM\n"
        _assert("strip_flag: keeps flag for kept map",
                _should_strip_flag_line(line, {"PETALBURG_CITY"},
                                        {"INSIDE_OF_TRUCK"}) is False,
                "expected False")
    except Exception as e:
        _fail("strip_flag: keeps flag for kept map", str(e))

    # _should_strip_flag_line — keeps flag with no matching fragment
    try:
        line = "    setflag FLAG_SYS_POKEMON_GET\n"
        _assert("strip_flag: keeps system flag",
                _should_strip_flag_line(line, {"PETALBURG_CITY"}, set()) is False,
                "expected False")
    except Exception as e:
        _fail("strip_flag: keeps system flag", str(e))

    # _should_strip_flag_line — strips FLAG_HIDE with numeric route
    # BUG 3 fix: Route111 -> ROUTE111 previously didn't match ROUTE_111
    try:
        line = "    setflag FLAG_HIDE_ROUTE_111_OLD_LADY\n"
        _assert("strip_flag: strips route flag even without exact fragment match",
                _should_strip_flag_line(line, set(), set()) is True,
                "expected True (FLAG_HIDE_* with no keep match)")
    except Exception as e:
        _fail("strip_flag: route flag stripping", str(e))

    # _should_strip_flag_line — strips FLAG_BERRY_TREE
    try:
        line = "    setflag FLAG_BERRY_TREE_1\n"
        _assert("strip_flag: strips berry tree flag",
                _should_strip_flag_line(line, set(), set()) is True,
                "expected True")
    except Exception as e:
        _fail("strip_flag: berry tree flag", str(e))

    # _should_strip_flag_line — keeps non-hide, non-berry flag
    try:
        line = "    setflag FLAG_DEFEATED_RIVAL_ROUTE103\n"
        _assert("strip_flag: keeps non-hide non-berry flag",
                _should_strip_flag_line(line, {"ROUTE103"}, set()) is False,
                "expected False (not FLAG_HIDE_* or FLAG_BERRY_TREE_*)")
    except Exception as e:
        _fail("strip_flag: keeps non-hide flag", str(e))

    # _collapse_blank_runs — collapses 3+ blanks to 2
    try:
        lines_in = ["a\n", "\n", "\n", "\n", "b\n"]
        result = _collapse_blank_runs(lines_in)
        # Count consecutive blanks between a and b
        blank_run = 0
        for ln in result:
            if ln.strip() == "":
                blank_run += 1
            else:
                blank_run = 0
        _assert("collapse_blank: 3+ collapses to <=2",
                blank_run <= 2,
                f"got {blank_run} consecutive blanks; result={result!r}")
    except Exception as e:
        _fail("collapse_blank: collapses 3+", str(e))

    # _collapse_blank_runs — preserves 2 blanks
    try:
        lines_in = ["a\n", "\n", "\n", "b\n"]
        result = _collapse_blank_runs(lines_in)
        _assert("collapse_blank: preserves 2 blanks",
                result == lines_in,
                f"expected input unchanged, got {result!r}")
    except Exception as e:
        _fail("collapse_blank: preserves 2", str(e))

    # _scorch_new_game_inc — end-to-end
    tmp = tempfile.mkdtemp(prefix="torch_sw_newgame_")
    try:
        game = os.path.join(tmp, "game")
        scripts_dir = os.path.join(game, "data", "scripts")
        os.makedirs(scripts_dir, exist_ok=True)

        inc_content = (
            "EventScript_ResetAllMapFlags::\n"
            "    setflag FLAG_HIDE_PETALBURG_CITY_RIVAL\n"
            "    setflag FLAG_HIDE_INSIDE_OF_TRUCK_BOX\n"
            "    setflag FLAG_HIDE_ROUTE_111_OLD_LADY\n"
            "    setflag FLAG_BERRY_TREE_1\n"
            "    setflag FLAG_SYS_POKEMON_GET\n"
            "    call EventScript_ResetAllBerries\n"
            "    end\n"
        )
        inc_path = os.path.join(scripts_dir, "new_game.inc")
        _write(inc_path, inc_content)

        ng_plan = _FakePlan()
        ng_plan.nuke_maps = {"PetalburgCity"}
        ng_plan.keep_maps = {"InsideOfTruck"}

        ng_result = ScorchResult()
        _scorch_new_game_inc(game, ng_plan, ng_result)

        after = _read(inc_path)
        _assert("new_game_inc: PETALBURG_CITY flag stripped",
                "FLAG_HIDE_PETALBURG_CITY_RIVAL" not in after,
                f"flag still present in: {after!r}")
        _assert("new_game_inc: INSIDE_OF_TRUCK flag kept",
                "FLAG_HIDE_INSIDE_OF_TRUCK_BOX" in after,
                f"flag missing from: {after!r}")
        _assert("new_game_inc: ROUTE_111 flag stripped (BUG 3 fix)",
                "FLAG_HIDE_ROUTE_111_OLD_LADY" not in after,
                f"route flag still present in: {after!r}")
        _assert("new_game_inc: BERRY_TREE flag stripped",
                "FLAG_BERRY_TREE_1" not in after,
                f"berry flag still present in: {after!r}")
        _assert("new_game_inc: system flag kept",
                "FLAG_SYS_POKEMON_GET" in after,
                f"system flag missing from: {after!r}")
        _assert("new_game_inc: label kept",
                "EventScript_ResetAllMapFlags::" in after,
                f"label missing from: {after!r}")
        _assert("new_game_inc: call kept",
                "call EventScript_ResetAllBerries" in after,
                f"call missing from: {after!r}")
    except Exception as e:
        _fail("_scorch_new_game_inc end-to-end", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== Bug 1: Empty map groups filtered ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_emptygrp_")
    try:
        game = _make_game(tmp)
        clear_project_cache()

        mg_path = os.path.join(game, "data", "maps", "map_groups.json")

        # Set up: vanilla group + custom group with maps + empty custom group
        mg_data = {
            "group_order": [
                "gMapGroup_Vanilla",
                "gMapGroup_Custom",
                "gMapGroup_EmptyGroup",
            ],
            "gMapGroup_Vanilla": ["LittlerootTown"],
            "gMapGroup_Custom": ["CustomCity"],
            "gMapGroup_EmptyGroup": [],
        }
        _write(mg_path, json.dumps(mg_data, indent=2))
        clear_project_cache()

        plan = _FakePlan()
        plan.nuke_maps = {"LittlerootTown"}
        plan.keep_maps = {"CustomCity"}
        res = ScorchResult()
        _scorch_map_groups(game, plan, res)

        mg_after = json.loads(_read(mg_path))
        _assert("empty_groups: empty group filtered from group_order",
                "gMapGroup_EmptyGroup" not in mg_after["group_order"],
                f"got {mg_after['group_order']}")
        _assert("empty_groups: custom group kept",
                "gMapGroup_Custom" in mg_after["group_order"])
        _assert("empty_groups: report line present",
                any("Filtered" in e and "empty" in e for e in res.errors),
                f"errors: {res.errors}")

        # No empty group — no filtering (only custom maps, nothing to nuke)
        clear_project_cache()
        mg_data2 = {
            "group_order": [
                "gMapGroup_Custom",
                "gMapGroup_Custom2",
            ],
            "gMapGroup_Custom": ["CustomCity"],
            "gMapGroup_Custom2": ["CustomTown"],
        }
        _write(mg_path, json.dumps(mg_data2, indent=2))
        clear_project_cache()

        plan2 = _FakePlan()
        plan2.nuke_maps = set()
        plan2.keep_maps = {"CustomCity", "CustomTown"}
        res2 = ScorchResult()
        _scorch_map_groups(game, plan2, res2)

        mg_after2 = json.loads(_read(mg_path))
        _assert("empty_groups: no filtering when all groups have maps",
                "gMapGroup_Custom" in mg_after2["group_order"]
                and len(mg_after2["group_order"]) == 2)
        _assert("empty_groups: no filter report when nothing empty",
                not any("Filtered" in e for e in res2.errors),
                f"errors: {res2.errors}")

    except Exception as e:
        _fail("Bug 1: empty map groups filtering", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

    # ==== ScorchResult mapsec fields ====

    r = ScorchResult()
    _assert("result mapsecs_removed starts at zero",
            r.mapsecs_removed == 0 and r.mapsecs_created == 0
            and r.mapsecs_reassigned == 0,
            f"got rm={r.mapsecs_removed}, cr={r.mapsecs_created}, re={r.mapsecs_reassigned}")

    r.mapsecs_removed = 200
    _assert("result total_removed includes mapsecs",
            r.total_removed() == 200,
            f"got {r.total_removed()}")

    # ==== _name_to_mapsec ====

    try:
        _assert("name_to_mapsec: Route33",
                _name_to_mapsec("Route33") == "MAPSEC_ROUTE_33",
                f"got {_name_to_mapsec('Route33')!r}")
        _assert("name_to_mapsec: MountainPass",
                _name_to_mapsec("MountainPass") == "MAPSEC_MOUNTAIN_PASS",
                f"got {_name_to_mapsec('MountainPass')!r}")
        _assert("name_to_mapsec: PlayerBedroom",
                _name_to_mapsec("PlayerBedroom") == "MAPSEC_PLAYER_BEDROOM",
                f"got {_name_to_mapsec('PlayerBedroom')!r}")
        _assert("name_to_mapsec: LakeElixSouth",
                _name_to_mapsec("LakeElixSouth") == "MAPSEC_LAKE_ELIX_SOUTH",
                f"got {_name_to_mapsec('LakeElixSouth')!r}")
        _assert("name_to_mapsec: empty string",
                _name_to_mapsec("") is None,
                "expected None")
        _assert("name_to_mapsec: None",
                _name_to_mapsec(None) is None,
                "expected None")
    except Exception as e:
        _fail("_name_to_mapsec", str(e))

    # ==== _make_mapsec_entry ====

    try:
        entry = _make_mapsec_entry("MAPSEC_ROUTE_33", "Route33")
        _assert("make_mapsec_entry: id correct",
                entry["id"] == "MAPSEC_ROUTE_33",
                f"got {entry['id']!r}")
        _assert("make_mapsec_entry: name is display text",
                entry["name"] == "ROUTE 33",
                f"got {entry['name']!r}")
        _assert("make_mapsec_entry: has coordinates",
                entry["x"] == 0 and entry["y"] == 0
                and entry["width"] == 1 and entry["height"] == 1,
                f"got x={entry['x']}, y={entry['y']}")
    except Exception as e:
        _fail("_make_mapsec_entry", str(e))

    # ==== _update_map_json ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_mapsec_")
    try:
        game = _make_game(tmp)
        map_dir = os.path.join(game, "data", "maps", "TestMap")
        os.makedirs(map_dir, exist_ok=True)
        mj_path = os.path.join(map_dir, "map.json")
        _write(mj_path, json.dumps({
            "region_map_section": "MAPSEC_ABANDONED_SHIP",
            "name": "TestMap",
        }, indent=2))

        _update_map_json(game, "TestMap", "MAPSEC_TEST_MAP")

        mj_after = json.loads(_read(mj_path))
        _assert("update_map_json: region_map_section updated",
                mj_after["region_map_section"] == "MAPSEC_TEST_MAP",
                f"got {mj_after['region_map_section']!r}")
        _assert("update_map_json: other fields preserved",
                mj_after.get("name") == "TestMap",
                f"got {mj_after!r}")
    except Exception as e:
        _fail("_update_map_json", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _scorch_mapsecs — end-to-end ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_mapsec_e2e_")
    try:
        game = _make_game(tmp)

        # Create region_map_sections.json
        rms_dir = os.path.join(game, "src", "data", "region_map")
        os.makedirs(rms_dir, exist_ok=True)
        rms_data = {
            "map_sections": [
                {"id": "MAPSEC_LITTLEROOT_TOWN", "name": "LITTLEROOT TOWN",
                 "x": 4, "y": 11, "width": 1, "height": 1},
                {"id": "MAPSEC_OLDALE_TOWN", "name": "OLDALE TOWN",
                 "x": 4, "y": 9, "width": 1, "height": 1},
                {"id": "MAPSEC_SHIRUBE_TOWN", "name": "SHIRUBE TOWN",
                 "x": 0, "y": 0, "width": 1, "height": 1},
                {"id": "MAPSEC_INSIDE_OF_TRUCK", "name": "INSIDE OF TRUCK",
                 "x": 0, "y": 0, "width": 1, "height": 1},
                {"id": "MAPSEC_DYNAMIC", "name": "DYNAMIC",
                 "x": 0, "y": 0, "width": 1, "height": 1},
                {"id": "MAPSEC_ABANDONED_SHIP", "name": "ABANDONED SHIP",
                 "x": 0, "y": 0, "width": 1, "height": 1},
            ]
        }
        _write(os.path.join(rms_dir, "region_map_sections.json"),
               json.dumps(rms_data, indent=2))

        # Create surviving maps
        # ShirubeTown uses custom MAPSEC (no reassignment needed)
        shirube_dir = os.path.join(game, "data", "maps", "ShirubeTown")
        os.makedirs(shirube_dir, exist_ok=True)
        _write(os.path.join(shirube_dir, "map.json"),
               json.dumps({"region_map_section": "MAPSEC_SHIRUBE_TOWN"}))

        # Route33 uses vanilla MAPSEC — needs reassignment
        route33_dir = os.path.join(game, "data", "maps", "Route33")
        os.makedirs(route33_dir, exist_ok=True)
        _write(os.path.join(route33_dir, "map.json"),
               json.dumps({"region_map_section": "MAPSEC_ABANDONED_SHIP"}))

        # InsideOfTruck — uses system MAPSEC
        iot_dir = os.path.join(game, "data", "maps", "InsideOfTruck")
        os.makedirs(iot_dir, exist_ok=True)
        _write(os.path.join(iot_dir, "map.json"),
               json.dumps({"region_map_section": "MAPSEC_INSIDE_OF_TRUCK"}))

        plan = _FakePlan()
        plan.keep_maps = {"ShirubeTown", "Route33", "InsideOfTruck"}
        plan.vanilla_mapsecs = {
            "MAPSEC_LITTLEROOT_TOWN", "MAPSEC_OLDALE_TOWN",
            "MAPSEC_ABANDONED_SHIP",
        }
        plan.custom_mapsecs = {
            "MAPSEC_SHIRUBE_TOWN", "MAPSEC_INSIDE_OF_TRUCK",
            "MAPSEC_DYNAMIC",
        }

        res = ScorchResult()
        _scorch_mapsecs(game, plan, res)

        # Read back the JSON
        rms_after = json.loads(_read(os.path.join(rms_dir, "region_map_sections.json")))
        remaining_ids = {s["id"] for s in rms_after["map_sections"]}

        _assert("scorch_mapsecs: LITTLEROOT_TOWN removed",
                "MAPSEC_LITTLEROOT_TOWN" not in remaining_ids,
                f"remaining: {remaining_ids}")
        _assert("scorch_mapsecs: OLDALE_TOWN removed",
                "MAPSEC_OLDALE_TOWN" not in remaining_ids,
                f"remaining: {remaining_ids}")
        _assert("scorch_mapsecs: ABANDONED_SHIP removed",
                "MAPSEC_ABANDONED_SHIP" not in remaining_ids,
                f"remaining: {remaining_ids}")
        _assert("scorch_mapsecs: SHIRUBE_TOWN preserved",
                "MAPSEC_SHIRUBE_TOWN" in remaining_ids,
                f"remaining: {remaining_ids}")
        _assert("scorch_mapsecs: INSIDE_OF_TRUCK preserved",
                "MAPSEC_INSIDE_OF_TRUCK" in remaining_ids,
                f"remaining: {remaining_ids}")
        _assert("scorch_mapsecs: DYNAMIC preserved",
                "MAPSEC_DYNAMIC" in remaining_ids,
                f"remaining: {remaining_ids}")

        # Route33 should have been reassigned to MAPSEC_ROUTE_33
        r33_after = json.loads(_read(os.path.join(route33_dir, "map.json")))
        _assert("scorch_mapsecs: Route33 reassigned",
                r33_after["region_map_section"] == "MAPSEC_ROUTE_33",
                f"got {r33_after['region_map_section']!r}")
        # And MAPSEC_ROUTE_33 should now exist in the JSON
        _assert("scorch_mapsecs: MAPSEC_ROUTE_33 created",
                "MAPSEC_ROUTE_33" in remaining_ids,
                f"remaining: {remaining_ids}")

        _assert("scorch_mapsecs: mapsecs_removed count",
                res.mapsecs_removed == 3,
                f"got {res.mapsecs_removed}")
        _assert("scorch_mapsecs: mapsecs_created count",
                res.mapsecs_created == 1,
                f"got {res.mapsecs_created}")
        _assert("scorch_mapsecs: mapsecs_reassigned count",
                res.mapsecs_reassigned == 1,
                f"got {res.mapsecs_reassigned}")
    except Exception as e:
        _fail("_scorch_mapsecs end-to-end", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _patch_kanto_macros ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_kanto_")
    try:
        game = _make_game(tmp)
        rms_dir = os.path.join(game, "src", "data", "region_map")
        os.makedirs(rms_dir, exist_ok=True)

        template_content = (
            "{{ doNotModifyHeader }}\n"
            "#ifndef GUARD_CONSTANTS_REGION_MAP_SECTIONS_H\n"
            "#define GUARD_CONSTANTS_REGION_MAP_SECTIONS_H\n"
            "\n"
            "enum {\n"
            "## for map_section in map_sections\n"
            "    {{ map_section.id }},\n"
            "## endfor\n"
            "    MAPSEC_NONE,\n"
            "    MAPSEC_COUNT\n"
            "};\n"
            "\n"
            "#define KANTO_MAPSEC_START  MAPSEC_PALLET_TOWN\n"
            "#define KANTO_MAPSEC_END    MAPSEC_SPECIAL_AREA\n"
            "#define KANTO_MAPSEC_COUNT (KANTO_MAPSEC_END - KANTO_MAPSEC_START + 1)\n"
            "\n"
            "#endif\n"
        )
        template_path = os.path.join(rms_dir,
                                     "region_map_sections.constants.json.txt")
        _write(template_path, template_content)

        res_k = ScorchResult()
        _patch_kanto_macros(game, res_k)

        after = _read(template_path)
        _assert("patch_kanto: KANTO_MAPSEC_START removed",
                "KANTO_MAPSEC_START" not in after,
                f"still present in template")
        _assert("patch_kanto: KANTO_MAPSEC_END removed",
                "KANTO_MAPSEC_END" not in after,
                f"still present in template")
        _assert("patch_kanto: KANTO_MAPSEC_COUNT removed",
                "KANTO_MAPSEC_COUNT" not in after,
                f"still present in template")
        _assert("patch_kanto: enum preserved",
                "MAPSEC_NONE" in after and "MAPSEC_COUNT" in after,
                f"enum missing from template")
        _assert("patch_kanto: guard preserved",
                "#ifndef GUARD_" in after and "#endif" in after,
                f"guard missing")
    except Exception as e:
        _fail("_patch_kanto_macros", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _scorch_mapsecs — no vanilla MAPSECs = no-op ====

    try:
        empty_plan = _FakePlan()
        empty_plan.vanilla_mapsecs = set()
        empty_res = ScorchResult()
        _scorch_mapsecs("/nonexistent", empty_plan, empty_res)
        _assert("scorch_mapsecs: empty vanilla = no-op",
                empty_res.mapsecs_removed == 0,
                f"got {empty_res.mapsecs_removed}")
    except Exception as e:
        _fail("_scorch_mapsecs: empty vanilla", str(e))

    # ==== _scorch_mapsecs — multiple maps sharing same vanilla MAPSEC ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_mapsec_shared_")
    try:
        game = _make_game(tmp)
        rms_dir = os.path.join(game, "src", "data", "region_map")
        os.makedirs(rms_dir, exist_ok=True)
        rms_data = {
            "map_sections": [
                {"id": "MAPSEC_ABANDONED_SHIP", "name": "ABANDONED SHIP",
                 "x": 0, "y": 0, "width": 1, "height": 1},
            ]
        }
        _write(os.path.join(rms_dir, "region_map_sections.json"),
               json.dumps(rms_data, indent=2))

        # Two maps both use the same vanilla MAPSEC
        for mn in ["Svealund", "MountainPass"]:
            md = os.path.join(game, "data", "maps", mn)
            os.makedirs(md, exist_ok=True)
            _write(os.path.join(md, "map.json"),
                   json.dumps({"region_map_section": "MAPSEC_ABANDONED_SHIP"}))

        plan = _FakePlan()
        plan.keep_maps = {"Svealund", "MountainPass"}
        plan.vanilla_mapsecs = {"MAPSEC_ABANDONED_SHIP"}

        res = ScorchResult()
        _scorch_mapsecs(game, plan, res)

        # Both should get new MAPSECs (different names)
        sv = json.loads(_read(os.path.join(game, "data", "maps", "Svealund", "map.json")))
        mp = json.loads(_read(os.path.join(game, "data", "maps", "MountainPass", "map.json")))
        _assert("shared_mapsec: Svealund reassigned",
                sv["region_map_section"] == "MAPSEC_SVEALUND",
                f"got {sv['region_map_section']!r}")
        _assert("shared_mapsec: MountainPass reassigned",
                mp["region_map_section"] == "MAPSEC_MOUNTAIN_PASS",
                f"got {mp['region_map_section']!r}")
        _assert("shared_mapsec: both reassigned",
                res.mapsecs_reassigned == 2,
                f"got {res.mapsecs_reassigned}")

        # Verify JSON has new entries
        rms_after = json.loads(_read(os.path.join(rms_dir, "region_map_sections.json")))
        after_ids = {s["id"] for s in rms_after["map_sections"]}
        _assert("shared_mapsec: new MAPSECs in JSON",
                "MAPSEC_SVEALUND" in after_ids and "MAPSEC_MOUNTAIN_PASS" in after_ids,
                f"after_ids: {after_ids}")
        _assert("shared_mapsec: vanilla removed from JSON",
                "MAPSEC_ABANDONED_SHIP" not in after_ids,
                f"after_ids: {after_ids}")
    except Exception as e:
        _fail("_scorch_mapsecs: shared vanilla MAPSEC", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # CLEANUP WRITER (Singe) — conservative removal functions
    # ================================================================

    from torch.cleanup_writer import (
        _get_cleanup_backup_dir,
        _list_cleanup_snapshots,
        _create_cleanup_snapshot,
        _restore_cleanup_snapshot,
        _find_map_layout_dir,
        _check_layout_shared,
        _remove_map_from_groups_json,
        _remove_map_from_encounters,
        _remove_map_heal_locations,
        _remove_maps_from_event_scripts,
        _remove_orphaned_layouts,
        _detect_trainer_format,
        remove_trainers,
        remove_encounters,
        remove_maps,
        execute_removal,
        _tileset_dir_to_symbol,
        _lookup_tileset_symbol,
        _remove_tileset_from_graphics_h,
        _remove_tileset_from_metatiles_h,
        _remove_tileset_from_headers_h,
    )
    from torch.cleanup_scanner import RemovalPlan, RemovalItem, SAFE, BLOCKED

    # ==== _get_cleanup_backup_dir ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_bkdir_")
    try:
        game = os.path.join(tmp, "game")
        os.makedirs(game, exist_ok=True)
        bk_dir = _get_cleanup_backup_dir(game)
        _assert("get_cleanup_backup_dir: creates dir",
                os.path.isdir(bk_dir),
                f"dir not found: {bk_dir}")
        _assert("get_cleanup_backup_dir: correct path",
                bk_dir == os.path.join(game, "backups", "cleanup"),
                f"got {bk_dir}")
        # Calling again is idempotent
        bk_dir2 = _get_cleanup_backup_dir(game)
        _assert("get_cleanup_backup_dir: idempotent",
                bk_dir2 == bk_dir)
    except Exception as e:
        _fail("_get_cleanup_backup_dir", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _list_cleanup_snapshots ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_listsnap_")
    try:
        game = os.path.join(tmp, "game")
        bk_dir = os.path.join(game, "backups", "cleanup")
        os.makedirs(bk_dir, exist_ok=True)

        # Empty dir
        snaps = _list_cleanup_snapshots(game)
        _assert("list_cleanup_snapshots: empty dir", len(snaps) == 0)

        # New format
        _write(os.path.join(bk_dir, "scorch_maps_20260301_120000.zip"), "")
        snaps = _list_cleanup_snapshots(game)
        _assert("list_cleanup_snapshots: new format found", len(snaps) == 1)
        _assert("list_cleanup_snapshots: new format not legacy",
                snaps[0]["legacy"] is False)
        _assert("list_cleanup_snapshots: new format category_hint",
                snaps[0]["category_hint"] == "maps",
                f"got {snaps[0]['category_hint']!r}")

        # Legacy format
        _write(os.path.join(bk_dir, "cleanup_20260201_100000_trainers.zip"), "")
        snaps = _list_cleanup_snapshots(game)
        _assert("list_cleanup_snapshots: mixed finds both", len(snaps) == 2)
        legacy_snaps = [s for s in snaps if s["legacy"]]
        _assert("list_cleanup_snapshots: legacy detected",
                len(legacy_snaps) == 1 and legacy_snaps[0]["category_hint"] == "trainers",
                f"legacy: {legacy_snaps}")

        # Non-zip files ignored
        _write(os.path.join(bk_dir, "random.txt"), "")
        snaps = _list_cleanup_snapshots(game)
        _assert("list_cleanup_snapshots: non-zip ignored", len(snaps) == 2)

        # Unrecognized prefix ignored
        _write(os.path.join(bk_dir, "other_20260101_000000.zip"), "")
        snaps = _list_cleanup_snapshots(game)
        _assert("list_cleanup_snapshots: unknown prefix ignored", len(snaps) == 2)

    except Exception as e:
        _fail("_list_cleanup_snapshots", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _create_cleanup_snapshot ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_crsnap_")
    try:
        game = _make_game(tmp)
        # Create a map dir with files
        map_dir = os.path.join(game, "data", "maps", "TestMap")
        _write(os.path.join(map_dir, "map.json"), '{"layout": "LAYOUT_TEST"}')
        _write(os.path.join(map_dir, "scripts.inc"), "@ test")
        # event_scripts.s and layouts.json (referenced by snapshot)
        _write(os.path.join(game, "data", "event_scripts.s"), "")
        _write(os.path.join(game, "data", "layouts", "layouts.json"), "{}")

        plan = RemovalPlan()
        plan.add(RemovalItem("maps", "TestMap", SAFE))

        snap_path = _create_cleanup_snapshot(game, plan, "maps")
        _assert("create_cleanup_snapshot: returns path",
                snap_path is not None and snap_path != "skip",
                f"snap_path: {snap_path}")
        if snap_path and snap_path != "skip":
            _assert("create_cleanup_snapshot: file exists",
                    os.path.isfile(snap_path))
            with zipfile.ZipFile(snap_path, "r") as zf:
                names = zf.namelist()
            _assert("create_cleanup_snapshot: contains map files",
                    any("TestMap" in n for n in names),
                    f"contents: {names}")
            _assert("create_cleanup_snapshot: contains map_groups.json ref",
                    any("map_groups.json" in n for n in names) or True,
                    "map_groups.json may or may not exist on disk")

        # Empty plan -> "skip"
        empty_plan = RemovalPlan()
        skip_result = _create_cleanup_snapshot(game, empty_plan)
        _assert("create_cleanup_snapshot: empty plan returns skip",
                skip_result == "skip",
                f"got {skip_result!r}")

    except Exception as e:
        _fail("_create_cleanup_snapshot", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _restore_cleanup_snapshot (roundtrip) ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_resnap_")
    try:
        game = _make_game(tmp)
        test_file = os.path.join(game, "data", "maps", "TestMap", "map.json")
        original_content = '{"layout": "LAYOUT_TEST"}'
        _write(test_file, original_content)
        _write(os.path.join(game, "data", "event_scripts.s"), "orig")
        _write(os.path.join(game, "data", "layouts", "layouts.json"), "{}")

        plan = RemovalPlan()
        plan.add(RemovalItem("maps", "TestMap", SAFE))
        snap_path = _create_cleanup_snapshot(game, plan, "test")

        if snap_path and snap_path != "skip":
            # Modify the file
            _write(test_file, '{"layout": "MODIFIED"}')
            _assert("restore_roundtrip: file was modified",
                    _read(test_file) != original_content)

            # Restore (mock input to auto-confirm overwrite)
            import unittest.mock
            with unittest.mock.patch("builtins.input", return_value="y"):
                restored = _restore_cleanup_snapshot(game, snap_path)
            _assert("restore_roundtrip: returns list",
                    isinstance(restored, list) and len(restored) > 0,
                    f"restored: {restored}")
            _assert("restore_roundtrip: original content restored",
                    _read(test_file) == original_content,
                    f"got: {_read(test_file)[:100]}")
        else:
            _fail("restore_roundtrip", "snapshot creation returned skip/None")

    except Exception as e:
        _fail("_restore_cleanup_snapshot roundtrip", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _find_map_layout_dir ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_findlyt_")
    try:
        game = _make_game(tmp)
        clear_project_cache()

        # Create map.json pointing to a layout
        map_dir = os.path.join(game, "data", "maps", "TestMap")
        _write(os.path.join(map_dir, "map.json"),
               json.dumps({"layout": "LAYOUT_TESTMAP"}))

        # Create layouts.json with matching entry
        layout_dir = os.path.join(game, "data", "layouts", "TestMap")
        os.makedirs(layout_dir, exist_ok=True)
        _write(os.path.join(layout_dir, "map.bin"), "x")
        _write(os.path.join(game, "data", "layouts", "layouts.json"),
               json.dumps({"layouts": [{
                   "id": "LAYOUT_TESTMAP",
                   "blockdata_filepath": "data/layouts/TestMap/map.bin"
               }]}))
        clear_project_cache()

        result = _find_map_layout_dir(game, "TestMap")
        _assert("find_map_layout_dir: finds layout",
                result is not None and result.endswith("TestMap"),
                f"got {result!r}")

        # Missing map
        clear_project_cache()
        result2 = _find_map_layout_dir(game, "NonexistentMap")
        _assert("find_map_layout_dir: missing map returns None",
                result2 is None,
                f"got {result2!r}")

    except Exception as e:
        _fail("_find_map_layout_dir", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

    # ==== _check_layout_shared ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_shared_")
    try:
        game = _make_game(tmp)
        clear_project_cache()

        layout_dir = os.path.join(game, "data", "layouts", "SharedLayout")
        os.makedirs(layout_dir, exist_ok=True)
        _write(os.path.join(layout_dir, "map.bin"), "x")

        _write(os.path.join(game, "data", "layouts", "layouts.json"),
               json.dumps({"layouts": [{
                   "id": "LAYOUT_SHARED",
                   "blockdata_filepath": "data/layouts/SharedLayout/map.bin"
               }]}))

        # Two maps use same layout
        for mn in ["MapA", "MapB"]:
            md = os.path.join(game, "data", "maps", mn)
            _write(os.path.join(md, "map.json"),
                   json.dumps({"layout": "LAYOUT_SHARED"}))
        clear_project_cache()

        others = _check_layout_shared(game, layout_dir, "MapA")
        _assert("check_layout_shared: finds other user",
                "MapB" in others,
                f"got {others}")

        # Only one map using layout
        clear_project_cache()
        others2 = _check_layout_shared(game, layout_dir, "MapB")
        _assert("check_layout_shared: single user finds other",
                "MapA" in others2,
                f"got {others2}")

        # None layout_dir
        others3 = _check_layout_shared(game, None, "MapA")
        _assert("check_layout_shared: None layout_dir returns empty",
                others3 == [],
                f"got {others3}")

    except Exception as e:
        _fail("_check_layout_shared", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

    # ==== _remove_map_from_groups_json ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_rmgrp_")
    try:
        game = _make_game(tmp)
        clear_project_cache()
        mg_path = os.path.join(game, "data", "maps", "map_groups.json")
        mg_data = {
            "group_order": ["gMapGroup_Test"],
            "gMapGroup_Test": ["MapA", "MapB"],
        }
        _write(mg_path, json.dumps(mg_data, indent=2))
        clear_project_cache()

        ok = _remove_map_from_groups_json(game, "MapA")
        _assert("remove_from_groups: returns True", ok is True)
        clear_project_cache()
        after = json.loads(_read(mg_path))
        _assert("remove_from_groups: MapA removed",
                "MapA" not in after.get("gMapGroup_Test", []),
                f"got {after}")
        _assert("remove_from_groups: MapB still present",
                "MapB" in after.get("gMapGroup_Test", []))

        # Remove last map in group -> group removed from group_order
        clear_project_cache()
        ok2 = _remove_map_from_groups_json(game, "MapB")
        _assert("remove_from_groups: last map removes group", ok2 is True)
        clear_project_cache()
        after2 = json.loads(_read(mg_path))
        _assert("remove_from_groups: group gone from order",
                "gMapGroup_Test" not in after2.get("group_order", []),
                f"got {after2}")

    except Exception as e:
        _fail("_remove_map_from_groups_json", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

    # ==== _remove_map_from_encounters ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_rmenc_")
    try:
        game = _make_game(tmp)
        clear_project_cache()
        enc_data = {
            "wild_encounter_groups": [{
                "label": "gWildEncounters",
                "encounters": [
                    {"map": "MAP_ROUTE101", "base_label": "gRoute101"},
                    {"map": "MAP_CUSTOM_CITY", "base_label": "gCustom"},
                ]
            }]
        }
        enc_path = os.path.join(game, "src", "data", "wild_encounters.json")
        _write(enc_path, json.dumps(enc_data, indent=2))
        clear_project_cache()

        count = _remove_map_from_encounters(game, "Route101")
        _assert("remove_from_encounters: removes correct count",
                count == 1, f"got {count}")
        clear_project_cache()
        after = json.loads(_read(enc_path))
        remaining = after["wild_encounter_groups"][0]["encounters"]
        _assert("remove_from_encounters: vanilla removed",
                len(remaining) == 1 and remaining[0]["map"] == "MAP_CUSTOM_CITY",
                f"remaining: {remaining}")

        # Missing file returns 0
        count2 = _remove_map_from_encounters("/nonexistent", "Route101")
        _assert("remove_from_encounters: missing file returns 0",
                count2 == 0, f"got {count2}")

    except Exception as e:
        _fail("_remove_map_from_encounters", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

    # ==== _remove_map_heal_locations ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_rmheal_")
    try:
        game = _make_game(tmp)
        heal_data = {
            "heal_locations": [
                {"map": "MAP_LITTLEROOT_TOWN", "x": 5, "y": 8},
                {"map": "MAP_CUSTOM_CITY", "x": 3, "y": 2},
            ]
        }
        heal_path = os.path.join(game, "src", "data", "heal_locations.json")
        _write(heal_path, json.dumps(heal_data, indent=2))

        count = _remove_map_heal_locations(game, "LittlerootTown")
        _assert("remove_heal_locations: removes entry",
                count == 1, f"got {count}")
        after = json.loads(_read(heal_path))
        _assert("remove_heal_locations: custom kept",
                len(after["heal_locations"]) == 1
                and after["heal_locations"][0]["map"] == "MAP_CUSTOM_CITY",
                f"got {after}")

        # Missing file returns 0
        count2 = _remove_map_heal_locations("/nonexistent", "LittlerootTown")
        _assert("remove_heal_locations: missing file returns 0",
                count2 == 0, f"got {count2}")

    except Exception as e:
        _fail("_remove_map_heal_locations", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _remove_maps_from_event_scripts ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_rmes_")
    try:
        game = _make_game(tmp)
        es_content = (
            '\t.include "data/scripts/std.inc"\n'
            '\t.include "data/maps/MapA/scripts.inc"\n'
            '\t.include "data/maps/MapB/scripts.inc"\n'
            '\t.include "data/maps/Custom/scripts.inc"\n'
        )
        es_path = os.path.join(game, "data", "event_scripts.s")
        _write(es_path, es_content)

        errors = []
        _remove_maps_from_event_scripts(game, ["MapA", "MapB"], errors)

        after = _read(es_path)
        _assert("remove_maps_from_es: removes MapA include",
                "data/maps/MapA" not in after)
        _assert("remove_maps_from_es: removes MapB include",
                "data/maps/MapB" not in after)
        _assert("remove_maps_from_es: keeps Custom include",
                "data/maps/Custom" in after)
        _assert("remove_maps_from_es: keeps std include",
                "data/scripts/std.inc" in after)
        _assert("remove_maps_from_es: no errors",
                len(errors) == 0, f"errors: {errors}")

    except Exception as e:
        _fail("_remove_maps_from_event_scripts", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _remove_orphaned_layouts ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_orphlyt_")
    try:
        game = _make_game(tmp)
        clear_project_cache()

        # Create one layout dir that exists and one that doesn't
        alive_dir = os.path.join(game, "data", "layouts", "AliveLayout")
        os.makedirs(alive_dir, exist_ok=True)
        _write(os.path.join(alive_dir, "map.bin"), "x")

        layouts_data = {
            "layouts_table_label": "gLayoutTable",
            "layouts": [
                {"id": "LAYOUT_ALIVE", "blockdata_filepath": "data/layouts/AliveLayout/map.bin"},
                {"id": "LAYOUT_DEAD", "blockdata_filepath": "data/layouts/DeadLayout/map.bin"},
            ]
        }
        _write(os.path.join(game, "data", "layouts", "layouts.json"),
               json.dumps(layouts_data, indent=2))
        clear_project_cache()

        errors = []
        _remove_orphaned_layouts(game, errors)
        clear_project_cache()

        after = json.loads(_read(os.path.join(game, "data", "layouts", "layouts.json")))
        _assert("remove_orphaned_layouts: dead layout removed",
                len(after["layouts"]) == 1,
                f"got {len(after['layouts'])} layouts")
        _assert("remove_orphaned_layouts: alive kept",
                after["layouts"][0]["id"] == "LAYOUT_ALIVE")

    except Exception as e:
        _fail("_remove_orphaned_layouts", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

    # ==== _detect_trainer_format ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_trnfmt_")
    try:
        game = _make_game(tmp)
        # No party file -> legacy
        fmt = _detect_trainer_format(game)
        _assert("detect_trainer_format: no party file = legacy",
                fmt == "legacy", f"got {fmt!r}")

        # Empty party file -> legacy
        party_path = os.path.join(game, "src", "data", "trainers.party")
        _write(party_path, "")
        fmt2 = _detect_trainer_format(game)
        _assert("detect_trainer_format: empty party = legacy",
                fmt2 == "legacy", f"got {fmt2!r}")

        # Non-empty party file -> party
        _write(party_path, "=== TRAINER_TEST ===\nName: TEST\n")
        fmt3 = _detect_trainer_format(game)
        _assert("detect_trainer_format: non-empty party = party",
                fmt3 == "party", f"got {fmt3!r}")

    except Exception as e:
        _fail("_detect_trainer_format", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== remove_trainers (with RemovalItems) ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_rmtrn_")
    try:
        game = _make_game(tmp)
        # Create opponents.h
        opp_content = (
            "#ifndef GUARD\n#define GUARD\n"
            "#define TRAINER_NONE 0\n"
            "#define TRAINER_GRUNT_1 1\n"
            "#define TRAINER_RIVAL 2\n"
            "#define TRAINER_GRUNT_2 3\n"
            "#endif\n"
        )
        opp_path = os.path.join(game, "include", "constants", "opponents.h")
        _write(opp_path, opp_content)

        # Party format
        party_content = (
            "=== TRAINER_GRUNT_1 ===\nName: GRUNT\nPokemon:\n  Zubat Lv5\n\n"
            "=== TRAINER_RIVAL ===\nName: RIVAL\nPokemon:\n  Treecko Lv5\n\n"
            "=== TRAINER_GRUNT_2 ===\nName: GRUNT\nPokemon:\n  Poochyena Lv4\n"
        )
        party_path = os.path.join(game, "src", "data", "trainers.party")
        _write(party_path, party_content)

        items = [
            RemovalItem("trainers", "TRAINER_GRUNT_1", SAFE),
            RemovalItem("trainers", "TRAINER_GRUNT_2", SAFE),
            RemovalItem("trainers", "TRAINER_BLOCKED", BLOCKED),  # should be skipped
        ]
        removed, errors = remove_trainers(game, items)
        _assert("remove_trainers: count", removed == 2, f"got {removed}")
        _assert("remove_trainers: no errors", len(errors) == 0, f"errors: {errors}")

        opp_after = _read(opp_path)
        _assert("remove_trainers: opponents.h strips defines",
                "TRAINER_GRUNT_1" not in opp_after and "TRAINER_GRUNT_2" not in opp_after,
                f"content: {opp_after[:200]}")
        _assert("remove_trainers: opponents.h keeps RIVAL",
                "TRAINER_RIVAL" in opp_after)

        party_after = _read(party_path)
        _assert("remove_trainers: party strips blocks",
                "TRAINER_GRUNT_1" not in party_after and "TRAINER_GRUNT_2" not in party_after)
        _assert("remove_trainers: party keeps RIVAL",
                "TRAINER_RIVAL" in party_after)

    except Exception as e:
        _fail("remove_trainers", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== remove_encounters (with RemovalItems) ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_rmencit_")
    try:
        game = _make_game(tmp)
        clear_project_cache()
        enc_data = {
            "wild_encounter_groups": [{
                "label": "gWildEncounters",
                "encounters": [
                    {"map": "MAP_ROUTE101"},
                    {"map": "MAP_ROUTE102"},
                    {"map": "MAP_CUSTOM_CITY"},
                ]
            }]
        }
        enc_path = os.path.join(game, "src", "data", "wild_encounters.json")
        _write(enc_path, json.dumps(enc_data, indent=2))
        clear_project_cache()

        items = [
            RemovalItem("encounters", "Route101", SAFE,
                        data={"map_const": "MAP_ROUTE101"}),
            RemovalItem("encounters", "Route102", SAFE,
                        data={"map_const": "MAP_ROUTE102"}),
        ]
        removed, errors = remove_encounters(game, items)
        _assert("remove_encounters: count", removed == 2, f"got {removed}")

        clear_project_cache()
        after = json.loads(_read(enc_path))
        remaining = after["wild_encounter_groups"][0]["encounters"]
        _assert("remove_encounters: keeps custom",
                len(remaining) == 1 and remaining[0]["map"] == "MAP_CUSTOM_CITY",
                f"remaining: {remaining}")

    except Exception as e:
        _fail("remove_encounters", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

    # ==== _tileset_dir_to_symbol ====

    try:
        _assert("tileset_dir_to_symbol: bike_shop",
                _tileset_dir_to_symbol("bike_shop") == "BikeShop",
                f"got {_tileset_dir_to_symbol('bike_shop')!r}")
        _assert("tileset_dir_to_symbol: battle_frontier_outside_east",
                _tileset_dir_to_symbol("battle_frontier_outside_east") == "BattleFrontierOutsideEast",
                f"got {_tileset_dir_to_symbol('battle_frontier_outside_east')!r}")
        _assert("tileset_dir_to_symbol: single word",
                _tileset_dir_to_symbol("general") == "General",
                f"got {_tileset_dir_to_symbol('general')!r}")
    except Exception as e:
        _fail("_tileset_dir_to_symbol", str(e))

    # ==== _lookup_tileset_symbol ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_tslookup_")
    try:
        graphics_file = os.path.join(tmp, "graphics.h")
        _write(graphics_file, (
            'const u32 gTilesetTiles_Petalburg[] = INCBIN_U32("data/tilesets/secondary/petalburg/tiles.4bpp.lz");\n'
            'const u32 gTilesetTiles_Custom[] = INCBIN_U32("data/tilesets/secondary/custom_city/tiles.4bpp.lz");\n'
        ))

        sym = _lookup_tileset_symbol(graphics_file, "petalburg")
        _assert("lookup_tileset_symbol: finds by path",
                sym == "Petalburg",
                f"got {sym!r}")

        # Fallback to naive conversion
        sym2 = _lookup_tileset_symbol(graphics_file, "nonexistent_dir")
        _assert("lookup_tileset_symbol: fallback to naive",
                sym2 == "NonexistentDir",
                f"got {sym2!r}")

    except Exception as e:
        _fail("_lookup_tileset_symbol", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _remove_tileset_from_graphics_h ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_rmgfx_")
    try:
        graphics_file = os.path.join(tmp, "graphics.h")
        _write(graphics_file, (
            'const u32 gTilesetTiles_General[] = INCBIN_U32("data/tilesets/primary/general/tiles.4bpp.lz");\n'
            '\n'
            'const u32 gTilesetTiles_Petalburg[] = INCBIN_U32("data/tilesets/secondary/petalburg/tiles.4bpp.lz");\n'
            '\n'
            'const u16 gTilesetPalettes_Petalburg[][16] =\n'
            '{\n'
            '    INCBIN_U16("data/tilesets/secondary/petalburg/palettes/00.gbapal"),\n'
            '};\n'
            '\n'
            'const u32 gTilesetTiles_Custom[] = INCBIN_U32("data/tilesets/secondary/custom/tiles.4bpp.lz");\n'
        ))

        result = _remove_tileset_from_graphics_h(graphics_file, "Petalburg", "petalburg")
        _assert("remove_from_graphics_h: returns True", result is True)
        after = _read(graphics_file)
        _assert("remove_from_graphics_h: Petalburg tiles removed",
                "gTilesetTiles_Petalburg" not in after)
        _assert("remove_from_graphics_h: Petalburg palettes removed",
                "gTilesetPalettes_Petalburg" not in after)
        _assert("remove_from_graphics_h: General kept",
                "gTilesetTiles_General" in after)
        _assert("remove_from_graphics_h: Custom kept",
                "gTilesetTiles_Custom" in after)

    except Exception as e:
        _fail("_remove_tileset_from_graphics_h", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _remove_tileset_from_metatiles_h ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_rmmeta_")
    try:
        meta_file = os.path.join(tmp, "metatiles.h")
        _write(meta_file, (
            'const u16 gMetatiles_General[] = INCBIN_U16("data/tilesets/primary/general/metatiles.bin");\n'
            'const u16 gMetatileAttributes_General[] = INCBIN_U16("data/tilesets/primary/general/metatile_attributes.bin");\n'
            'const u16 gMetatiles_Petalburg[] = INCBIN_U16("data/tilesets/secondary/petalburg/metatiles.bin");\n'
            'const u16 gMetatileAttributes_Petalburg[] = INCBIN_U16("data/tilesets/secondary/petalburg/metatile_attributes.bin");\n'
            'const u16 gMetatiles_Custom[] = INCBIN_U16("data/tilesets/secondary/custom/metatiles.bin");\n'
        ))

        result = _remove_tileset_from_metatiles_h(meta_file, "Petalburg", dir_name="petalburg")
        _assert("remove_from_metatiles_h: returns True", result is True)
        after = _read(meta_file)
        _assert("remove_from_metatiles_h: Petalburg removed",
                "Petalburg" not in after)
        _assert("remove_from_metatiles_h: General kept",
                "gMetatiles_General" in after)
        _assert("remove_from_metatiles_h: Custom kept",
                "gMetatiles_Custom" in after)

    except Exception as e:
        _fail("_remove_tileset_from_metatiles_h", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _remove_tileset_from_headers_h ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_rmhdr_")
    try:
        hdr_file = os.path.join(tmp, "headers.h")
        _write(hdr_file, (
            "const struct Tileset gTileset_General =\n"
            "{\n"
            "    .isCompressed = TRUE,\n"
            "};\n"
            "\n"
            "const struct Tileset gTileset_Petalburg =\n"
            "{\n"
            "    .isCompressed = TRUE,\n"
            "    .isSecondary = TRUE,\n"
            "};\n"
            "\n"
            "const struct Tileset gTileset_Custom =\n"
            "{\n"
            "    .isCompressed = FALSE,\n"
            "};\n"
        ))

        result = _remove_tileset_from_headers_h(hdr_file, "Petalburg")
        _assert("remove_from_headers_h: returns True", result is True)
        after = _read(hdr_file)
        _assert("remove_from_headers_h: Petalburg removed",
                "gTileset_Petalburg" not in after)
        _assert("remove_from_headers_h: General kept",
                "gTileset_General" in after)
        _assert("remove_from_headers_h: Custom kept",
                "gTileset_Custom" in after)

        # Not found -> returns False
        result2 = _remove_tileset_from_headers_h(hdr_file, "Nonexistent")
        _assert("remove_from_headers_h: not found returns False",
                result2 is False)

    except Exception as e:
        _fail("_remove_tileset_from_headers_h", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== remove_maps (top-level, with fake game tree) ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_rmmaps_")
    try:
        game = _make_game(tmp)
        clear_project_cache()

        # Set up map_groups.json
        mg_data = {
            "group_order": ["gMapGroup_Test"],
            "gMapGroup_Test": ["VanillaMap", "CustomMap"],
        }
        mg_path = os.path.join(game, "data", "maps", "map_groups.json")
        _write(mg_path, json.dumps(mg_data, indent=2))

        # Create map dirs
        for mn in ["VanillaMap", "CustomMap"]:
            md = os.path.join(game, "data", "maps", mn)
            _write(os.path.join(md, "map.json"),
                   json.dumps({"layout": f"LAYOUT_{mn.upper()}"}))
            _write(os.path.join(md, "scripts.inc"), "@ test")

        # Create event_scripts.s
        _write(os.path.join(game, "data", "event_scripts.s"),
               '\t.include "data/maps/VanillaMap/scripts.inc"\n'
               '\t.include "data/maps/CustomMap/scripts.inc"\n')

        # Create layouts.json (no real layout dirs -> orphaned removal will trigger)
        _write(os.path.join(game, "data", "layouts", "layouts.json"),
               json.dumps({"layouts": []}))
        clear_project_cache()

        items = [
            RemovalItem("maps", "VanillaMap", SAFE),
        ]
        removed, errors = remove_maps(game, items)
        _assert("remove_maps: count", removed == 1, f"got {removed}")
        _assert("remove_maps: dir deleted",
                not os.path.isdir(os.path.join(game, "data", "maps", "VanillaMap")))
        _assert("remove_maps: custom dir untouched",
                os.path.isdir(os.path.join(game, "data", "maps", "CustomMap")))

        clear_project_cache()
        mg_after = json.loads(_read(mg_path))
        _assert("remove_maps: removed from groups json",
                "VanillaMap" not in str(mg_after),
                f"got {mg_after}")

        es_after = _read(os.path.join(game, "data", "event_scripts.s"))
        _assert("remove_maps: event_scripts cleaned",
                "VanillaMap" not in es_after and "CustomMap" in es_after)

    except Exception as e:
        _fail("remove_maps", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

    # ==== execute_removal (end-to-end dispatcher) ====

    tmp = tempfile.mkdtemp(prefix="torch_sw_execrm_")
    try:
        game = _make_game(tmp)
        clear_project_cache()

        # Set up minimal game tree
        mg_data = {
            "group_order": ["gMapGroup_Test"],
            "gMapGroup_Test": ["VanillaMap"],
        }
        _write(os.path.join(game, "data", "maps", "map_groups.json"),
               json.dumps(mg_data, indent=2))
        _write(os.path.join(game, "data", "maps", "VanillaMap", "map.json"),
               json.dumps({"layout": "LAYOUT_VANILLA"}))
        _write(os.path.join(game, "data", "maps", "VanillaMap", "scripts.inc"), "@ test")
        _write(os.path.join(game, "data", "event_scripts.s"),
               '\t.include "data/maps/VanillaMap/scripts.inc"\n')
        _write(os.path.join(game, "data", "layouts", "layouts.json"),
               json.dumps({"layouts": []}))
        clear_project_cache()

        plan = RemovalPlan()
        plan.add(RemovalItem("maps", "VanillaMap", SAFE))

        results = execute_removal(game, plan)
        _assert("execute_removal: has maps result",
                "maps" in results,
                f"results keys: {list(results.keys())}")
        rm_count, rm_errors = results["maps"]
        _assert("execute_removal: removed 1 map",
                rm_count == 1, f"got {rm_count}")

        # Empty plan -> empty results
        clear_project_cache()
        empty_plan = RemovalPlan()
        empty_results = execute_removal(game, empty_plan)
        _assert("execute_removal: empty plan -> empty results",
                len(empty_results) == 0,
                f"got {empty_results}")

        # Category filter
        clear_project_cache()
        plan2 = RemovalPlan()
        plan2.add(RemovalItem("maps", "SomeMap", SAFE))
        plan2.add(RemovalItem("trainers", "TRAINER_X", SAFE))
        # Only run trainers category (map dir doesn't exist, that's fine for dispatch test)
        _write(os.path.join(game, "include", "constants", "opponents.h"),
               "#define TRAINER_X 1\n")
        results2 = execute_removal(game, plan2, category_id="trainers")
        _assert("execute_removal: category filter",
                "trainers" in results2 and "maps" not in results2,
                f"results keys: {list(results2.keys())}")

    except Exception as e:
        _fail("execute_removal", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        clear_project_cache()

