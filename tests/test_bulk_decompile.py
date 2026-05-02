"""Bulk decompile suite — extraction, round-trip, project-wide decompile."""
import os
import json
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Bulk Decompile  (extraction, round-trip, project-wide)")

    try:
        from torch.bulk_decompile import (
            find_script, classify_script, classify_inc_script,
            strip_script_prefix, _extract_brace_block,
            expand_battle_beats, _resolve_inc_text,
            decompile_script_to_workspace, decompile_mapscripts,
            decompile_map_to_workspace, validate_round_trip,
            bulk_decompile_all_maps, re_decompile_pristine,
            PRISTINE_HEADER,
        )
    except ImportError as e:
        _skip("all bulk_decompile tests", f"import failed: {e}")
        return

    # 1. _extract_brace_block
    try:
        content = "mapscripts Foo { bar_handler }"
        result = _extract_brace_block(content, 0)
        _assert(
            "_extract_brace_block: extracts body",
            result is not None and "bar_handler" in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("_extract_brace_block", str(e))

    # 2. strip_script_prefix
    try:
        _assert(
            "strip_script_prefix: removes EventScript prefix",
            strip_script_prefix("FortreeCity_EventScript_GameboyKid", "FortreeCity") == "GameboyKid",
            ""
        )
        _assert(
            "strip_script_prefix: removes map prefix",
            strip_script_prefix("FortreeCity_Trainer", "FortreeCity") == "Trainer",
            ""
        )
        _assert(
            "strip_script_prefix: no prefix returns label",
            strip_script_prefix("SomeLabel", "FortreeCity") == "SomeLabel",
            ""
        )
    except Exception as e:
        _fail("strip_script_prefix", str(e))

    # 3. classify_script — pory format
    try:
        pory = 'script MyMap_EventScript_Npc {\n    msgbox("Hello$", MSGBOX_NPC)\n}\n'
        _assert(
            "classify_script: flavor NPC",
            classify_script(pory, "MyMap_EventScript_Npc") == "flavor",
            f"got: {classify_script(pory, 'MyMap_EventScript_Npc')}"
        )
        sign = 'script MyMap_Sign {\n    msgbox("Read me$", MSGBOX_SIGN)\n}\n'
        _assert(
            "classify_script: sign",
            classify_script(sign, "MyMap_Sign") == "sign",
            f"got: {classify_script(sign, 'MyMap_Sign')}"
        )
    except Exception as e:
        _fail("classify_script", str(e))

    # 4. classify_inc_script — assembly format
    try:
        inc = (
            "MyMap_NPC::\n"
            "\tlock\n"
            "\tfaceplayer\n"
            "\tmsgbox MyMap_Text, MSGBOX_NPC\n"
            "\trelease\n"
            "\tend\n"
        )
        _assert(
            "classify_inc_script: flavor NPC",
            classify_inc_script(inc, "MyMap_NPC") == "flavor",
            f"got: {classify_inc_script(inc, 'MyMap_NPC')}"
        )
    except Exception as e:
        _fail("classify_inc_script", str(e))

    # 5. _resolve_inc_text
    try:
        inc = (
            "MyLabel:\n"
            '\t.string "Hello world$"\n'
        )
        _assert(
            "_resolve_inc_text: resolves text label",
            _resolve_inc_text(inc, "MyLabel") == "Hello world$",
            f"got: {_resolve_inc_text(inc, 'MyLabel')!r}"
        )
        _assert(
            "_resolve_inc_text: missing label returns None",
            _resolve_inc_text(inc, "NonExistent") is None,
            ""
        )
    except Exception as e:
        _fail("_resolve_inc_text", str(e))

    # 6. expand_battle_beats
    try:
        ts = (
            'trainerbattle_single TRAINER_FOO, "Get ready!$", "You won!$"\n'
            'msg "Good fight!$"\n'
            'end\n'
        )
        result = expand_battle_beats(ts)
        _assert(
            "expand_battle_beats: expands to multi-line",
            "intro" in result and "defeated" in result and "postbattle" in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("expand_battle_beats", str(e))

    # 7. find_script with a .pory file
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    try:
        map_dir = os.path.join(game_dir, "data", "maps", "TestMap")
        os.makedirs(map_dir)
        pory_path = os.path.join(map_dir, "scripts.pory")
        with open(pory_path, "w") as f:
            f.write('script TestMap_EventScript_Npc {\n    msgbox("Hi$", MSGBOX_NPC)\n}\n')
        fp, ft = find_script(game_dir, "TestMap", "TestMap_EventScript_Npc")
        _assert(
            "find_script: locates .pory script",
            fp == pory_path and ft == "pory",
            f"got: ({fp!r}, {ft!r})"
        )
        fp2, ft2 = find_script(game_dir, "TestMap", "NonExistent")
        _assert(
            "find_script: missing label returns None",
            fp2 is None and ft2 is None,
            f"got: ({fp2!r}, {ft2!r})"
        )
    except Exception as e:
        _fail("find_script", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)

    # 8. decompile_script_to_workspace
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        map_dir = os.path.join(game_dir, "data", "maps", "TestMap")
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
            f.write('script TestMap_EventScript_Npc {\n    msgbox("Hi$", MSGBOX_NPC)\n}\n')
        name, ts, warns = decompile_script_to_workspace(
            game_dir, "TestMap", "TestMap_EventScript_Npc", proj_dir)
        _assert(
            "decompile_script_to_workspace: returns short name",
            name == "Npc",
            f"got: {name!r}"
        )
        out_path = os.path.join(proj_dir, "TestMap", "Npc.txt")
        _assert(
            "decompile_script_to_workspace: creates .txt file",
            os.path.isfile(out_path),
            f"file not found: {out_path}"
        )
    except Exception as e:
        _fail("decompile_script_to_workspace", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 9. decompile_script_to_workspace with pristine header
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        map_dir = os.path.join(game_dir, "data", "maps", "TestMap")
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
            f.write('script TestMap_EventScript_Npc {\n    msgbox("Hi$", MSGBOX_NPC)\n}\n')
        decompile_script_to_workspace(
            game_dir, "TestMap", "TestMap_EventScript_Npc", proj_dir,
            header=PRISTINE_HEADER)
        out_path = os.path.join(proj_dir, "TestMap", "Npc.txt")
        with open(out_path, "r") as f:
            content = f.read()
        _assert(
            "decompile_script_to_workspace: pristine header prepended",
            content.startswith(PRISTINE_HEADER),
            f"starts with: {content[:80]!r}"
        )
    except Exception as e:
        _fail("decompile_script_to_workspace pristine header", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 10. decompile_script_to_workspace: does not overwrite existing file
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        map_dir = os.path.join(game_dir, "data", "maps", "TestMap")
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
            f.write('script TestMap_EventScript_Npc {\n    msgbox("Hi$", MSGBOX_NPC)\n}\n')
        # Pre-create file with user content
        ws_dir = os.path.join(proj_dir, "TestMap")
        os.makedirs(ws_dir)
        out_path = os.path.join(ws_dir, "Npc.txt")
        with open(out_path, "w") as f:
            f.write("my custom content\n")
        decompile_script_to_workspace(
            game_dir, "TestMap", "TestMap_EventScript_Npc", proj_dir)
        with open(out_path, "r") as f:
            content = f.read()
        _assert(
            "decompile_script_to_workspace: does not overwrite existing file",
            content == "my custom content\n",
            f"got: {content!r}"
        )
    except Exception as e:
        _fail("decompile_script_to_workspace no overwrite", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 11. decompile_mapscripts
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        map_dir = os.path.join(game_dir, "data", "maps", "TestMap")
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
            f.write('mapscripts TestMap_MapScripts {\n    MAP_SCRIPT_ON_LOAD { }\n}\n')
        result = decompile_mapscripts(game_dir, "TestMap", proj_dir)
        _assert(
            "decompile_mapscripts: returns 'created'",
            result == "created",
            f"got: {result!r}"
        )
        setup_path = os.path.join(proj_dir, "TestMap", "setup.pory")
        _assert(
            "decompile_mapscripts: creates setup.pory",
            os.path.isfile(setup_path),
            ""
        )
        # Second call should return 'exists'
        result2 = decompile_mapscripts(game_dir, "TestMap", proj_dir)
        _assert(
            "decompile_mapscripts: returns 'exists' on second call",
            result2 == "exists",
            f"got: {result2!r}"
        )
    except Exception as e:
        _fail("decompile_mapscripts", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 12. decompile_map_to_workspace
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        map_name = "TestMap"
        map_dir = os.path.join(game_dir, "data", "maps", map_name)
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
            f.write('script TestMap_EventScript_Npc {\n    msgbox("Hi$", MSGBOX_NPC)\n}\n')
        with open(os.path.join(map_dir, "map.json"), "w") as f:
            json.dump({
                "object_events": [
                    {"script": "TestMap_EventScript_Npc", "local_id": "1"},
                ],
                "bg_events": [],
            }, f)
        result = decompile_map_to_workspace(game_dir, map_name, proj_dir, pristine=True)
        _assert(
            "decompile_map_to_workspace: imports scripts",
            "Npc" in result["imported"],
            f"got imported: {result['imported']!r}"
        )
        txt_path = os.path.join(proj_dir, map_name, "Npc.txt")
        _assert(
            "decompile_map_to_workspace: .txt file exists",
            os.path.isfile(txt_path),
            ""
        )
        with open(txt_path, "r") as f:
            content = f.read()
        _assert(
            "decompile_map_to_workspace: pristine header in file",
            content.startswith(PRISTINE_HEADER),
            f"starts with: {content[:80]!r}"
        )
    except Exception as e:
        _fail("decompile_map_to_workspace", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 13. decompile_map_to_workspace: map with no scripts
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        map_name = "EmptyMap"
        map_dir = os.path.join(game_dir, "data", "maps", map_name)
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "map.json"), "w") as f:
            json.dump({"object_events": [], "bg_events": []}, f)
        result = decompile_map_to_workspace(game_dir, map_name, proj_dir)
        _assert(
            "decompile_map_to_workspace: empty map creates workspace dir",
            os.path.isdir(os.path.join(proj_dir, map_name)),
            ""
        )
        _assert(
            "decompile_map_to_workspace: empty map has no imports",
            result["imported"] == [],
            f"got: {result['imported']!r}"
        )
    except Exception as e:
        _fail("decompile_map_to_workspace empty map", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 14. validate_round_trip — clean case
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        map_name = "TestMap"
        ws_dir = os.path.join(proj_dir, map_name)
        os.makedirs(ws_dir)
        # Write a simple valid TorScript file
        with open(os.path.join(ws_dir, "Npc.txt"), "w") as f:
            f.write("script TestMap_EventScript_Npc\nmsgnpc \"Hello$\"\nrelease\nend\n")
        # Create minimal emotes config
        emotes_path = os.path.join(proj_dir, "emotes.conf")
        with open(emotes_path, "w") as f:
            f.write("")
        is_clean, mismatches = validate_round_trip(game_dir, map_name, proj_dir, emotes_path)
        _assert(
            "validate_round_trip: clean case passes",
            is_clean is True,
            f"got: is_clean={is_clean}, mismatches={mismatches!r}"
        )
    except Exception as e:
        _fail("validate_round_trip clean", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 15. validate_round_trip — bad case (syntax error)
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        map_name = "TestMap"
        ws_dir = os.path.join(proj_dir, map_name)
        os.makedirs(ws_dir)
        with open(os.path.join(ws_dir, "Bad.txt"), "w") as f:
            f.write("this is not valid torscript at all\n")
        emotes_path = os.path.join(proj_dir, "emotes.conf")
        with open(emotes_path, "w") as f:
            f.write("")
        is_clean, mismatches = validate_round_trip(game_dir, map_name, proj_dir, emotes_path)
        _assert(
            "validate_round_trip: bad case fails",
            is_clean is False and "Bad.txt" in mismatches,
            f"got: is_clean={is_clean}, mismatches={mismatches!r}"
        )
    except Exception as e:
        _fail("validate_round_trip bad", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 16. bulk_decompile_all_maps
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        # Create two game maps
        for mname in ("MapA", "MapB"):
            map_dir = os.path.join(game_dir, "data", "maps", mname)
            os.makedirs(map_dir)
            with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
                f.write(f'script {mname}_EventScript_Npc {{\n    msgbox("Hi$", MSGBOX_NPC)\n}}\n')
            with open(os.path.join(map_dir, "map.json"), "w") as f:
                json.dump({
                    "object_events": [{"script": f"{mname}_EventScript_Npc", "local_id": "1"}],
                    "bg_events": [],
                }, f)
        # Create emotes config
        emotes_path = os.path.join(proj_dir, "emotes.conf")
        with open(emotes_path, "w") as f:
            f.write("")
        counts = bulk_decompile_all_maps(game_dir, proj_dir, emotes_path)
        _assert(
            "bulk_decompile_all_maps: enrolls maps",
            counts["pristine"] + counts["locked"] >= 2,
            f"got: {counts!r}"
        )
        # Check workspace folders created
        _assert(
            "bulk_decompile_all_maps: MapA workspace exists",
            os.path.isdir(os.path.join(proj_dir, "MapA")),
            ""
        )
        _assert(
            "bulk_decompile_all_maps: MapB workspace exists",
            os.path.isdir(os.path.join(proj_dir, "MapB")),
            ""
        )
        # Check registry was written
        from torch.registry import load_registry
        reg = load_registry(proj_dir)
        _assert(
            "bulk_decompile_all_maps: registry has both maps",
            "MapA" in reg["maps"] and "MapB" in reg["maps"],
            f"maps: {list(reg['maps'].keys())}"
        )
    except Exception as e:
        _fail("bulk_decompile_all_maps", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 17. bulk_decompile_all_maps: skips already-enrolled maps
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        from torch.registry import enroll_map
        map_dir = os.path.join(game_dir, "data", "maps", "MapA")
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "map.json"), "w") as f:
            json.dump({"object_events": [], "bg_events": []}, f)
        enroll_map(proj_dir, "MapA")  # pre-enroll
        emotes_path = os.path.join(proj_dir, "emotes.conf")
        with open(emotes_path, "w") as f:
            f.write("")
        counts = bulk_decompile_all_maps(game_dir, proj_dir, emotes_path)
        _assert(
            "bulk_decompile_all_maps: skips already-enrolled",
            counts["skipped"] == 1,
            f"got: {counts!r}"
        )
    except Exception as e:
        _fail("bulk_decompile_all_maps skip enrolled", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 18. bulk_decompile_all_maps: existing user files → claimed
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        map_dir = os.path.join(game_dir, "data", "maps", "MapA")
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "map.json"), "w") as f:
            json.dump({"object_events": [], "bg_events": []}, f)
        # Pre-create workspace with user .txt
        ws = os.path.join(proj_dir, "MapA")
        os.makedirs(ws)
        with open(os.path.join(ws, "MyScript.txt"), "w") as f:
            f.write("script my_script\nend\n")
        emotes_path = os.path.join(proj_dir, "emotes.conf")
        with open(emotes_path, "w") as f:
            f.write("")
        counts = bulk_decompile_all_maps(game_dir, proj_dir, emotes_path)
        _assert(
            "bulk_decompile_all_maps: existing user files → claimed",
            counts["claimed"] == 1,
            f"got: {counts!r}"
        )
        from torch.registry import load_registry
        reg = load_registry(proj_dir)
        _assert(
            "bulk_decompile_all_maps: claimed map has state=claimed",
            reg["maps"]["MapA"]["state"] == "claimed",
            f"got: {reg['maps']['MapA'].get('state')!r}"
        )
    except Exception as e:
        _fail("bulk_decompile_all_maps user files claimed", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 19. re_decompile_pristine
    game_dir = tempfile.mkdtemp(prefix="torch_bd_game_")
    proj_dir = tempfile.mkdtemp(prefix="torch_bd_proj_")
    try:
        from torch.registry import enroll_map, mark_decompiled, load_registry, STATE_PRISTINE
        map_name = "TestMap"
        map_dir = os.path.join(game_dir, "data", "maps", map_name)
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
            f.write(f'script {map_name}_EventScript_Npc {{\n    msgbox("Hi$", MSGBOX_NPC)\n}}\n')
        with open(os.path.join(map_dir, "map.json"), "w") as f:
            json.dump({
                "object_events": [{"script": f"{map_name}_EventScript_Npc", "local_id": "1"}],
                "bg_events": [],
            }, f)
        # Initial decompile
        enroll_map(proj_dir, map_name, state=STATE_PRISTINE)
        decompile_map_to_workspace(game_dir, map_name, proj_dir, pristine=True)
        mark_decompiled(proj_dir, map_name)

        # Modify the game file
        with open(os.path.join(map_dir, "scripts.pory"), "w") as f:
            f.write(f'script {map_name}_EventScript_Npc {{\n    msgbox("Updated!$", MSGBOX_NPC)\n}}\n')

        # Re-decompile
        re_decompile_pristine(game_dir, map_name, proj_dir)
        txt_path = os.path.join(proj_dir, map_name, "Npc.txt")
        with open(txt_path, "r") as f:
            content = f.read()
        _assert(
            "re_decompile_pristine: overwrites with new content",
            "Updated!" in content,
            f"got: {content!r}"
        )
        _assert(
            "re_decompile_pristine: pristine header preserved",
            content.startswith(PRISTINE_HEADER),
            f"starts with: {content[:80]!r}"
        )
        # Check decompiled_at was updated
        reg = load_registry(proj_dir)
        _assert(
            "re_decompile_pristine: decompiled_at updated",
            reg["maps"][map_name]["decompiled_at"] is not None,
            ""
        )
    except Exception as e:
        _fail("re_decompile_pristine", str(e))
    finally:
        shutil.rmtree(game_dir, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)

    # 20. PRISTINE_HEADER constant
    try:
        _assert(
            "PRISTINE_HEADER: starts with comment",
            PRISTINE_HEADER.startswith("#"),
            f"got: {PRISTINE_HEADER!r}"
        )
    except Exception as e:
        _fail("PRISTINE_HEADER", str(e))
