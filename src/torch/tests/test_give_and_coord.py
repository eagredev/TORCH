"""Tests for give beat, item gift qty, coord auto-wire, and flag browser."""
import json
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert, _fixture


def run_suite():
    _begin_suite("Give Beat & Coord Trigger  (Phase 1+2 features)")

    _test_give_beat_parser()
    _test_give_beat_serializer()
    _test_give_beat_round_trip()
    _test_give_beat_compiler()
    _test_give_beat_compiler_qty()
    _test_give_beat_auto_label()
    _test_item_gift_template_qty()
    _test_item_gift_template_default_qty()
    _test_coord_auto_wire()
    _test_coord_auto_wire_multi_tile()
    _test_clear_map_json_removes_coord()
    _test_clear_map_json_keeps_npc()
    _test_remove_movement_from_setup()
    _test_remove_movement_preserves_others()
    _test_flag_browser_import()
    _test_flag_scanner_import()


# ── Give Beat: Parser ─────────────────────────────────────────────

def _test_give_beat_parser():
    """give beat parser extracts item and quantity."""
    try:
        from torch.script_model import _parse_beat_give
        beat, idx = _parse_beat_give(
            ["give", "ITEM_POTION"], "give ITEM_POTION", [], 0, {})
        _assert(
            "give parser: type is 'give'",
            beat["type"] == "give",
            f"type: {beat['type']}"
        )
        _assert(
            "give parser: item is ITEM_POTION",
            beat["data"]["item"] == "ITEM_POTION",
            f"item: {beat['data']['item']}"
        )
        _assert(
            "give parser: default quantity is '1'",
            beat["data"]["quantity"] == "1",
            f"qty: {beat['data']['quantity']}"
        )

        # With quantity
        beat2, _ = _parse_beat_give(
            ["give", "ITEM_RARE_CANDY", "3"], "give ITEM_RARE_CANDY 3", [], 0, {})
        _assert(
            "give parser: quantity=3 parsed correctly",
            beat2["data"]["quantity"] == "3",
            f"qty: {beat2['data']['quantity']}"
        )
    except Exception as e:
        _fail("give parser", str(e))


def _test_give_beat_serializer():
    """give beat serializer produces correct TorScript."""
    try:
        from torch.script_model import _serialize_beat_give
        lines = []
        _serialize_beat_give({"item": "ITEM_POTION", "quantity": "1"}, lines)
        _assert(
            "give serializer: qty=1 omits quantity",
            lines == ["give ITEM_POTION"],
            f"lines: {lines}"
        )

        lines2 = []
        _serialize_beat_give({"item": "ITEM_RARE_CANDY", "quantity": "3"}, lines2)
        _assert(
            "give serializer: qty=3 includes quantity",
            lines2 == ["give ITEM_RARE_CANDY 3"],
            f"lines: {lines2}"
        )
    except Exception as e:
        _fail("give serializer", str(e))


def _test_give_beat_round_trip():
    """give beat round-trips through parse → serialize."""
    try:
        from torch.script_model import _parse_script, _serialize_script
        path = _fixture("GiveItem.txt")
        script = _parse_script(path)
        give_beats = [b for b in script["beats"] if b["type"] == "give"]
        _assert(
            "give round-trip: parsed give beat",
            len(give_beats) == 1,
            f"give beat count: {len(give_beats)}"
        )
        _assert(
            "give round-trip: item is ITEM_POTION",
            give_beats[0]["data"]["item"] == "ITEM_POTION",
            f"item: {give_beats[0]['data']['item']}"
        )

        # Serialize and verify
        serialized = _serialize_script(script)
        _assert(
            "give round-trip: serialized contains 'give ITEM_POTION'",
            "give ITEM_POTION" in serialized,
            f"serialized: {serialized[:200]}"
        )
    except Exception as e:
        _fail("give round-trip", str(e))


# ── Give Beat: Compiler ───────────────────────────────────────────

def _test_give_beat_compiler():
    """give beat compiles to giveitem + bag-full check."""
    try:
        from torch.compiler import compile_script
        path = _fixture("GiveItem.txt")
        output, errors = compile_script(path, "GiveItem", "")
        _assert(
            "give compiler: no errors",
            len(errors) == 0,
            f"errors: {errors}"
        )
        _assert(
            "give compiler: output contains giveitem(ITEM_POTION)",
            "giveitem(ITEM_POTION)" in output,
            f"output: {output[:300]}"
        )
        _assert(
            "give compiler: output contains compare(VAR_RESULT, FALSE)",
            "compare(VAR_RESULT, FALSE)" in output,
            f"output: {output[:300]}"
        )
        _assert(
            "give compiler: output contains goto_if_eq(*_BagFull)",
            "goto_if_eq(GiveItem_BagFull)" in output,
            f"output: {output[:400]}"
        )
    except Exception as e:
        _fail("give compiler", str(e))


def _test_give_beat_compiler_qty():
    """give beat with quantity compiles to giveitem(ITEM, QTY)."""
    try:
        from torch.compiler import compile_script
        path = _fixture("GiveItemQty.txt")
        output, errors = compile_script(path, "GiveItemQty", "")
        _assert(
            "give compiler qty: no errors",
            len(errors) == 0,
            f"errors: {errors}"
        )
        _assert(
            "give compiler qty: output contains giveitem(ITEM_RARE_CANDY, 3)",
            "giveitem(ITEM_RARE_CANDY, 3)" in output,
            f"output: {output[:300]}"
        )
    except Exception as e:
        _fail("give compiler qty", str(e))


def _test_give_beat_auto_label():
    """give beat auto-generates BagFull label in output."""
    try:
        from torch.compiler import compile_script
        path = _fixture("GiveItem.txt")
        output, errors = compile_script(path, "GiveItem", "")
        _assert(
            "give auto-label: BagFull script block generated",
            "script GiveItem_BagFull {" in output,
            f"output tail: {output[-300:]}"
        )
        _assert(
            "give auto-label: contains bag full message",
            "bag is too full" in output.lower(),
            f"output tail: {output[-300:]}"
        )
    except Exception as e:
        _fail("give auto-label", str(e))


# ── Item Gift Template: Quantity ──────────────────────────────────

def _test_item_gift_template_qty():
    """Item gift template with quantity > 1 emits giveitem(ITEM, QTY)."""
    try:
        import torch.templates as tmpl
        ctx = {"label": "TestMap_Gift", "map_name": "TestMap",
               "game_path": "/fake", "cast": {}}
        vs = {"item": "ITEM_RARE_CANDY", "quantity": "5",
              "flag": None, "dialogue": "Here!"}
        beats = tmpl._build_item_gift(vs, ctx)
        pory_beats = [b for b in beats if b["type"] == "pory"]
        giveitem_lines = [b["data"]["raw_line"] for b in pory_beats
                          if "giveitem" in b["data"]["raw_line"]]
        _assert(
            "item_gift qty=5: giveitem includes quantity",
            any("giveitem(ITEM_RARE_CANDY, 5)" in line for line in giveitem_lines),
            f"giveitem lines: {giveitem_lines}"
        )
    except Exception as e:
        _fail("item_gift qty", str(e))


def _test_item_gift_template_default_qty():
    """Item gift template with default qty=1 emits giveitem(ITEM) without qty."""
    try:
        import torch.templates as tmpl
        ctx = {"label": "TestMap_Gift", "map_name": "TestMap",
               "game_path": "/fake", "cast": {}}
        vs = {"item": "ITEM_POTION", "quantity": "1",
              "flag": None, "dialogue": "Here!"}
        beats = tmpl._build_item_gift(vs, ctx)
        pory_beats = [b for b in beats if b["type"] == "pory"]
        giveitem_lines = [b["data"]["raw_line"] for b in pory_beats
                          if "giveitem" in b["data"]["raw_line"]]
        _assert(
            "item_gift qty=1: giveitem without quantity suffix",
            any(line == "giveitem(ITEM_POTION)" for line in giveitem_lines),
            f"giveitem lines: {giveitem_lines}"
        )
    except Exception as e:
        _fail("item_gift default qty", str(e))


# ── Coord Trigger: Auto-Wire ─────────────────────────────────────

def _test_coord_auto_wire():
    """_auto_wire_coord_event writes coord events to map.json."""
    try:
        from torch.script_hub import _auto_wire_coord_event
        tmpdir = tempfile.mkdtemp()
        map_dir = os.path.join(tmpdir, "data", "maps", "TestMap")
        os.makedirs(map_dir)
        map_json = os.path.join(map_dir, "map.json")
        with open(map_json, "w") as f:
            json.dump({"object_events": [], "coord_events": [], "bg_events": []},
                      f, indent=2)

        ok = _auto_wire_coord_event(
            tmpdir, "TestMap", [(5, 10)], "0", "VAR_TEMP_1", "0",
            "TestMap_TriggerScript")

        _assert(
            "coord wire: returns True",
            ok,
            "returned False"
        )

        with open(map_json) as f:
            data = json.load(f)
        coords = data["coord_events"]
        _assert(
            "coord wire: 1 coord event added",
            len(coords) == 1,
            f"count: {len(coords)}"
        )
        _assert(
            "coord wire: event has correct x/y",
            coords[0]["x"] == 5 and coords[0]["y"] == 10,
            f"event: {coords[0]}"
        )
        _assert(
            "coord wire: event has correct script",
            coords[0]["script"] == "TestMap_TriggerScript",
            f"script: {coords[0].get('script')}"
        )
        _assert(
            "coord wire: event has var/var_value",
            coords[0]["var"] == "VAR_TEMP_1" and coords[0]["var_value"] == "0",
            f"var: {coords[0].get('var')}, var_value: {coords[0].get('var_value')}"
        )
    except Exception as e:
        _fail("coord wire", str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _test_coord_auto_wire_multi_tile():
    """_auto_wire_coord_event writes multiple coord events for multi-tile range."""
    try:
        from torch.script_hub import _auto_wire_coord_event
        tmpdir = tempfile.mkdtemp()
        map_dir = os.path.join(tmpdir, "data", "maps", "TestMap")
        os.makedirs(map_dir)
        map_json = os.path.join(map_dir, "map.json")
        with open(map_json, "w") as f:
            json.dump({"object_events": [], "coord_events": [], "bg_events": []},
                      f, indent=2)

        # 2x2 grid: (3,4), (3,5), (4,4), (4,5)
        coords = [(3, 4), (3, 5), (4, 4), (4, 5)]
        ok = _auto_wire_coord_event(
            tmpdir, "TestMap", coords, "0", "VAR_TEMP_1", "0",
            "TestMap_WideZone")

        _assert(
            "coord multi: returns True",
            ok,
            "returned False"
        )

        with open(map_json) as f:
            data = json.load(f)
        _assert(
            "coord multi: 4 coord events added",
            len(data["coord_events"]) == 4,
            f"count: {len(data['coord_events'])}"
        )

        xy_pairs = {(e["x"], e["y"]) for e in data["coord_events"]}
        _assert(
            "coord multi: all 4 positions covered",
            xy_pairs == {(3, 4), (3, 5), (4, 4), (4, 5)},
            f"positions: {xy_pairs}"
        )
    except Exception as e:
        _fail("coord multi", str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Deletion Cleanup ─────────────────────────────────────────────

def _test_clear_map_json_removes_coord():
    """_clear_map_json_references fully removes coord and bg events."""
    try:
        from torch.script_hub import _clear_map_json_references
        tmpdir = tempfile.mkdtemp()
        map_json = os.path.join(tmpdir, "map.json")
        data = {
            "object_events": [
                {"script": "TestMap_NPC", "x": 1, "y": 1},
            ],
            "coord_events": [
                {"script": "TestMap_Trigger", "x": 5, "y": 10, "var": "VAR_TEMP_1"},
                {"script": "TestMap_Other", "x": 3, "y": 3, "var": "VAR_TEMP_2"},
            ],
            "bg_events": [
                {"script": "TestMap_Sign", "x": 2, "y": 2},
                {"script": "TestMap_Trigger", "x": 7, "y": 7},
            ],
        }
        with open(map_json, "w") as f:
            json.dump(data, f, indent=2)

        cleared = _clear_map_json_references(map_json, ["TestMap_Trigger"])

        with open(map_json) as f:
            result = json.load(f)

        _assert(
            "clear coord: 2 refs cleared (1 coord + 1 bg)",
            cleared == 2,
            f"cleared: {cleared}"
        )
        _assert(
            "clear coord: coord_events has 1 remaining (Other kept)",
            len(result["coord_events"]) == 1,
            f"coord count: {len(result['coord_events'])}"
        )
        _assert(
            "clear coord: surviving coord is TestMap_Other",
            result["coord_events"][0]["script"] == "TestMap_Other",
            f"script: {result['coord_events'][0].get('script')}"
        )
        _assert(
            "clear coord: bg_events has 1 remaining (Sign kept)",
            len(result["bg_events"]) == 1,
            f"bg count: {len(result['bg_events'])}"
        )
    except Exception as e:
        _fail("clear coord removal", str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _test_clear_map_json_keeps_npc():
    """_clear_map_json_references clears NPC script but keeps the entry."""
    try:
        from torch.script_hub import _clear_map_json_references
        tmpdir = tempfile.mkdtemp()
        map_json = os.path.join(tmpdir, "map.json")
        data = {
            "object_events": [
                {"script": "TestMap_NPC", "x": 1, "y": 1, "graphics_id": "OBJ_EVENT_GFX_BOY"},
                {"script": "TestMap_Other", "x": 5, "y": 5, "graphics_id": "OBJ_EVENT_GFX_GIRL"},
            ],
            "coord_events": [],
            "bg_events": [],
        }
        with open(map_json, "w") as f:
            json.dump(data, f, indent=2)

        cleared = _clear_map_json_references(map_json, ["TestMap_NPC"])

        with open(map_json) as f:
            result = json.load(f)

        _assert(
            "clear NPC: 1 ref cleared",
            cleared == 1,
            f"cleared: {cleared}"
        )
        _assert(
            "clear NPC: object_events still has 2 entries (NPC preserved)",
            len(result["object_events"]) == 2,
            f"obj count: {len(result['object_events'])}"
        )
        _assert(
            "clear NPC: first NPC script is NopReturn",
            result["object_events"][0]["script"] == "Common_EventScript_NopReturn",
            f"script: {result['object_events'][0].get('script')}"
        )
        _assert(
            "clear NPC: NPC entry still has graphics_id",
            result["object_events"][0]["graphics_id"] == "OBJ_EVENT_GFX_BOY",
            f"gfx: {result['object_events'][0].get('graphics_id')}"
        )
    except Exception as e:
        _fail("clear NPC preserved", str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Movement Block Removal ───────────────────────────────────────

def _test_remove_movement_from_setup():
    """_remove_movement_from_setup removes a movement block from setup.pory."""
    try:
        from torch.script_hub import _remove_movement_from_setup
        tmpdir = tempfile.mkdtemp()
        setup = os.path.join(tmpdir, "setup.pory")
        with open(setup, "w") as f:
            f.write("// Map setup\n\n")
            f.write("mapscripts TestMap_MapScripts {}\n\n")
            f.write("movement TestMap_Walk {\n")
            f.write("    walk_left\n")
            f.write("    walk_right\n")
            f.write("}\n")

        ok = _remove_movement_from_setup(setup, "TestMap_Walk")
        _assert(
            "mv remove: returns True",
            ok,
            "returned False"
        )
        with open(setup) as f:
            content = f.read()
        _assert(
            "mv remove: movement block gone",
            "movement TestMap_Walk" not in content,
            f"content: {content}"
        )
        _assert(
            "mv remove: mapscripts preserved",
            "mapscripts TestMap_MapScripts" in content,
            f"content: {content}"
        )
    except Exception as e:
        _fail("mv remove", str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _test_remove_movement_preserves_others():
    """_remove_movement_from_setup removes only the target block."""
    try:
        from torch.script_hub import _remove_movement_from_setup
        tmpdir = tempfile.mkdtemp()
        setup = os.path.join(tmpdir, "setup.pory")
        with open(setup, "w") as f:
            f.write("mapscripts TestMap_MapScripts {}\n\n")
            f.write("movement TestMap_WalkA {\n")
            f.write("    walk_left\n")
            f.write("}\n\n")
            f.write("movement TestMap_WalkB {\n")
            f.write("    walk_right\n")
            f.write("}\n")

        ok = _remove_movement_from_setup(setup, "TestMap_WalkA")
        _assert(
            "mv preserve: returns True",
            ok,
            "returned False"
        )
        with open(setup) as f:
            content = f.read()
        _assert(
            "mv preserve: WalkA removed",
            "TestMap_WalkA" not in content,
            f"content: {content}"
        )
        _assert(
            "mv preserve: WalkB still present",
            "movement TestMap_WalkB" in content and "walk_right" in content,
            f"content: {content}"
        )
        _assert(
            "mv preserve: no double blank lines",
            "\n\n\n" not in content,
            f"content has triple blank"
        )
    except Exception as e:
        _fail("mv preserve", str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Module Imports ────────────────────────────────────────────────

def _test_flag_browser_import():
    """flag_browser module is importable."""
    try:
        from torch.flag_browser import flag_browser
        _assert(
            "flag_browser: importable and callable",
            callable(flag_browser),
            "not callable"
        )
    except ImportError as e:
        _fail("flag_browser: importable", str(e))


def _test_flag_scanner_import():
    """flag_scanner module is importable with all public functions."""
    try:
        from torch.flag_scanner import (
            scan_flag_references, scan_all_flags_bulk,
            parse_flags_h, count_free_slots, delete_flag_from_header,
        )
        _assert(
            "flag_scanner: all 5 functions importable",
            all(callable(f) for f in (scan_flag_references, scan_all_flags_bulk,
                                       parse_flags_h, count_free_slots,
                                       delete_flag_from_header)),
            "not all callable"
        )
    except ImportError as e:
        _fail("flag_scanner: importable", str(e))
