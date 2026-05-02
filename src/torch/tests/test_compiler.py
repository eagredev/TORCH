"""Compiler suite -- verifies script compilation from .txt fixtures."""
import os
import tempfile

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert, _fixture


def run_suite():
    _begin_suite("Compiler")

    try:
        from torch.compiler import compile_script
    except ImportError as e:
        _skip("all compiler tests", f"import failed: {e}")
        return

    emotes_conf = ""   # no emotes.conf needed for these fixtures

    fixtures = ["Officer.txt", "Buster.txt", "Clyde.txt", "ClydeArrives.txt"]

    for fname in fixtures:
        path = _fixture(fname)
        label = fname.replace(".txt", "")
        try:
            output, errors = compile_script(path, label, emotes_conf)
            _assert(
                f"{fname}: compiles without errors",
                len(errors) == 0,
                f"errors: {errors}"
            )
            _assert(
                f"{fname}: output is non-empty",
                bool(output and output.strip()),
                "compile_script returned empty output"
            )
        except Exception as e:
            _fail(f"{fname}: compile_script raised", str(e))

    # Spot-check: Officer.txt must contain its label
    try:
        path = _fixture("Officer.txt")
        output, _ = compile_script(path, "Officer", emotes_conf)
        _assert(
            "Officer.txt: output contains LakeElixSouth_Officer label",
            "LakeElixSouth_Officer" in output,
            "label not found in compiled output"
        )
    except Exception as e:
        _fail("Officer.txt: spot-check label", str(e))

    # Spot-check: ClydeArrives.txt must contain the battle command
    try:
        path = _fixture("ClydeArrives.txt")
        output, _ = compile_script(path, "ClydeArrives", emotes_conf)
        _assert(
            "ClydeArrives.txt: output contains trainerbattle",
            "trainerbattle" in output,
            "trainerbattle command not found in compiled output"
        )
    except Exception as e:
        _fail("ClydeArrives.txt: spot-check trainerbattle", str(e))

    # ---- Camera pan tests ----
    def _compile_tmp(script_text, prefix="CamTest", map_id=None):
        """Helper: write script_text to a temp file, compile, return (output, errors)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as tmp:
            tmp.write(script_text)
            tmp_path = tmp.name
        try:
            return compile_script(tmp_path, prefix, emotes_conf, map_id=map_id)
        finally:
            os.unlink(tmp_path)

    # camera pan all 4 directions
    for direction in ("down", "up", "left", "right"):
        try:
            output, errors = _compile_tmp(
                f"label TestPan\nlock\ncamera pan {direction} 3\nend\n"
            )
            _assert(
                f"camera pan {direction}: no errors",
                len(errors) == 0,
                f"errors: {errors}"
            )
            _assert(
                f"camera pan {direction}: emits SpawnCameraObject",
                "special(SpawnCameraObject)" in output,
                "SpawnCameraObject not found"
            )
            _assert(
                f"camera pan {direction}: emits applymovement(OBJ_EVENT_ID_CAMERA",
                "applymovement(OBJ_EVENT_ID_CAMERA" in output,
                "applymovement not found"
            )
            _assert(
                f"camera pan {direction}: emits waitmovement(OBJ_EVENT_ID_CAMERA)",
                "waitmovement(OBJ_EVENT_ID_CAMERA)" in output,
                "waitmovement not found"
            )
            _assert(
                f"camera pan {direction}: movement block has walk_{direction}",
                f"walk_{direction}" in output,
                f"walk_{direction} not in output"
            )
        except Exception as e:
            _fail(f"camera pan {direction}", str(e))

    # camera pan with count > 1 uses multiplier
    try:
        output, errors = _compile_tmp(
            "label TestPanMulti\nlock\ncamera pan down 5\nend\n"
        )
        _assert(
            "camera pan count > 1: uses multiplier",
            "walk_down * 5" in output,
            f"expected 'walk_down * 5' in output"
        )
    except Exception as e:
        _fail("camera pan count > 1", str(e))

    # camera reset
    try:
        output, errors = _compile_tmp(
            "label TestReset\nlock\ncamera pan down 2\ncamera reset\nend\n"
        )
        _assert(
            "camera reset: no errors",
            len(errors) == 0,
            f"errors: {errors}"
        )
        _assert(
            "camera reset: emits RemoveCameraObject",
            "special(RemoveCameraObject)" in output,
            "RemoveCameraObject not found"
        )
    except Exception as e:
        _fail("camera reset", str(e))

    # camera pan auto-spawns (no prior spawn needed)
    try:
        output, errors = _compile_tmp(
            "label TestAutoSpawn\nlock\ncamera pan left 1\nend\n"
        )
        _assert(
            "camera auto-spawn: SpawnCameraObject emitted before applymovement",
            output.index("SpawnCameraObject") < output.index("applymovement"),
            "SpawnCameraObject should come before applymovement"
        )
    except Exception as e:
        _fail("camera auto-spawn", str(e))

    # camera pan second call should NOT re-spawn
    try:
        output, errors = _compile_tmp(
            "label TestNoReSpawn\nlock\ncamera pan up 1\ncamera pan down 1\nend\n"
        )
        _assert(
            "camera no re-spawn: only one SpawnCameraObject",
            output.count("special(SpawnCameraObject)") == 1,
            f"expected 1 SpawnCameraObject, got {output.count('special(SpawnCameraObject)')}"
        )
    except Exception as e:
        _fail("camera no re-spawn", str(e))

    # camera reset without spawn still emits RemoveCameraObject
    # (camera may have been spawned in a prior script via goto)
    try:
        output, errors = _compile_tmp(
            "label TestResetNoSpawn\nlock\ncamera reset\nend\n"
        )
        _assert(
            "camera reset without spawn: no errors",
            len(errors) == 0,
            f"errors: {errors}"
        )
        _assert(
            "camera reset without spawn: emits RemoveCameraObject",
            "special(RemoveCameraObject)" in output,
            "RemoveCameraObject should always be emitted (engine no-ops safely)"
        )
    except Exception as e:
        _fail("camera reset without spawn", str(e))

    # camera reset in a different label than spawn still emits (cross-goto scenario)
    try:
        output, errors = _compile_tmp(
            "label ScriptA\nlock\ncamera pan down 2\ngoto ScriptB\nend\n"
            "label ScriptB\nlock\ncamera reset\nend\n"
        )
        _assert(
            "camera cross-label reset: no errors",
            len(errors) == 0,
            f"errors: {errors}"
        )
        _assert(
            "camera cross-label reset: emits RemoveCameraObject in ScriptB",
            "special(RemoveCameraObject)" in output,
            "RemoveCameraObject not found — reset in second label must still emit"
        )
    except Exception as e:
        _fail("camera cross-label reset", str(e))

    # camera in parallel movement produces error
    try:
        output, errors = _compile_tmp(
            "alias buster npc5\nlabel TestParallel\nlock\nbuster walk down 2 + camera pan up 1\nend\n"
        )
        _assert(
            "camera in parallel: reports error",
            len(errors) > 0,
            "expected error for camera in parallel movement"
        )
        _assert(
            "camera in parallel: error mentions camera",
            any("camera" in e.lower() for e in errors),
            f"error should mention camera: {errors}"
        )
    except Exception as e:
        _fail("camera in parallel", str(e))

    # camera state resets at new label
    try:
        output, errors = _compile_tmp(
            "label First\nlock\ncamera pan down 2\nend\n"
            "label Second\nlock\ncamera pan up 1\nend\n"
        )
        _assert(
            "camera state reset at label: two SpawnCameraObject calls",
            output.count("special(SpawnCameraObject)") == 2,
            f"expected 2 SpawnCameraObject, got {output.count('special(SpawnCameraObject)')}"
        )
    except Exception as e:
        _fail("camera state reset at label", str(e))

    # camera follow produces informative error
    try:
        output, errors = _compile_tmp(
            "label TestFollow\nlock\ncamera follow buster\nend\n"
        )
        _assert(
            "camera follow: reports not-yet-supported error",
            len(errors) > 0 and any("not yet supported" in e for e in errors),
            f"expected 'not yet supported' error: {errors}"
        )
    except Exception as e:
        _fail("camera follow", str(e))

    # camera with bad direction
    try:
        output, errors = _compile_tmp(
            "label TestBadDir\nlock\ncamera pan diagonal 2\nend\n"
        )
        _assert(
            "camera bad direction: reports error",
            len(errors) > 0,
            "expected error for bad direction"
        )
    except Exception as e:
        _fail("camera bad direction", str(e))

    # camera with missing args
    try:
        output, errors = _compile_tmp(
            "label TestMissingArgs\nlock\ncamera\nend\n"
        )
        _assert(
            "camera missing args: reports error",
            len(errors) > 0,
            "expected error for missing args"
        )
    except Exception as e:
        _fail("camera missing args", str(e))

    # camera pan missing tile count
    try:
        output, errors = _compile_tmp(
            "label TestMissingCount\nlock\ncamera pan down\nend\n"
        )
        _assert(
            "camera pan missing count: reports error",
            len(errors) > 0,
            "expected error for missing tile count"
        )
    except Exception as e:
        _fail("camera pan missing count", str(e))

    # ---- Camera reset with offset correction tests ----

    # Pan down 2 + reset: emits callnative ScriptResetCameraOffset
    try:
        output, errors = _compile_tmp(
            "label Test\ncamera pan down 2\ncamera reset\n")
        _assert("camera reset after pan: no errors", len(errors) == 0,
                f"got errors: {errors}")
        _assert("camera reset after pan: emits setvar 0x8005",
                "setvar(VAR_0x8005, 2)" in output, output)
        _assert("camera reset after pan: emits callnative",
                "callnative(ScriptResetCameraOffset)" in output, output)
    except Exception as e:
        _fail("camera reset after pan", str(e))

    # Multi-directional pan: down 3 + right 2 + reset
    try:
        output, errors = _compile_tmp(
            "label Test\ncamera pan down 3\ncamera pan right 2\ncamera reset\n")
        _assert("camera multi-pan reset: setvar 0x8004=2",
                "setvar(VAR_0x8004, 2)" in output, output)
        _assert("camera multi-pan reset: setvar 0x8005=3",
                "setvar(VAR_0x8005, 3)" in output, output)
    except Exception as e:
        _fail("camera multi-pan reset", str(e))

    # Opposing pans cancel (net zero): no callnative emitted
    try:
        output, errors = _compile_tmp(
            "label Test\ncamera pan down 2\ncamera pan up 2\ncamera reset\n")
        _assert("camera net-zero reset: no callnative",
                "ScriptResetCameraOffset" not in output, output)
        _assert("camera net-zero reset: still has RemoveCameraObject",
                "RemoveCameraObject" in output, output)
    except Exception as e:
        _fail("camera net-zero reset", str(e))

    # Negative offset (pan up 3): emits u16 hex for -3
    try:
        output, errors = _compile_tmp(
            "label Test\ncamera pan up 3\ncamera reset\n")
        _assert("camera negative offset: setvar 0x8005=0xFFFD",
                "setvar(VAR_0x8005, 0xFFFD)" in output, output)
        _assert("camera negative offset: setvar 0x8004=0",
                "setvar(VAR_0x8004, 0)" in output, output)
    except Exception as e:
        _fail("camera negative offset", str(e))

    # Reset with manual offset: camera reset 0 2
    try:
        output, errors = _compile_tmp(
            "label Test\ncamera reset 0 2\n")
        _assert("camera manual offset: no errors", len(errors) == 0,
                f"got errors: {errors}")
        _assert("camera manual offset: emits setvar 0x8005=2",
                "setvar(VAR_0x8005, 2)" in output, output)
        _assert("camera manual offset: emits callnative",
                "callnative(ScriptResetCameraOffset)" in output, output)
    except Exception as e:
        _fail("camera manual offset", str(e))

    # Reset warp form: camera reset warp MAP_TEST 10 20
    try:
        output, errors = _compile_tmp(
            "label Test\ncamera reset warp MAP_TEST 10 20\n")
        _assert("camera reset warp: no errors", len(errors) == 0,
                f"got errors: {errors}")
        _assert("camera reset warp: emits warpsilent",
                "warpsilent(MAP_TEST, WARP_ID_NONE, 10, 20)" in output, output)
        _assert("camera reset warp: emits waitstate",
                "waitstate" in output, output)
        _assert("camera reset warp: no callnative",
                "ScriptResetCameraOffset" not in output, output)
    except Exception as e:
        _fail("camera reset warp", str(e))

    # Pan + trainerbattle + pan: second SpawnCameraObject emitted
    try:
        output, errors = _compile_tmp(
            "label Test\ncamera pan down 2\n"
            "trainerbattle_single TRAINER_TEST, Text1, Text2\n"
            "camera pan down 1\ncamera reset\n")
        spawn_count = output.count("SpawnCameraObject")
        _assert("camera re-spawn after battle: two SpawnCameraObject",
                spawn_count == 2, f"got {spawn_count}")
        # Total offset: down 2 + down 1 = 3
        _assert("camera re-spawn after battle: accumulated offset 3",
                "setvar(VAR_0x8005, 3)" in output, output)
    except Exception as e:
        _fail("camera re-spawn after battle", str(e))

    # Offsets reset at new label boundary
    try:
        output, errors = _compile_tmp(
            "label ScriptA\ncamera pan down 5\ncamera reset\n"
            "label ScriptB\ncamera pan right 1\ncamera reset\n")
        # ScriptB should only have offset_x=1, not carry ScriptA's offset
        # Find the second callnative — it should have 0x8004=1, 0x8005=0
        parts = output.split("ScriptResetCameraOffset")
        _assert("camera label reset: two callnative calls",
                len(parts) == 3, f"expected 3 parts, got {len(parts)}")
    except Exception as e:
        _fail("camera label reset", str(e))

    # ---- End camera tests ----

    # Error case: compiler must report an error on a malformed line
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as tmp:
            tmp.write("label BadScript\n")
            tmp.write("msg\n")          # msg with no text — should produce an error
            tmp_path = tmp.name
        output, errors = compile_script(tmp_path, "BadScript", emotes_conf)
        _assert(
            "malformed msg: compiler reports error",
            len(errors) > 0,
            "expected at least one error but got none"
        )
    except Exception as e:
        _fail("malformed msg: compiler raised unexpectedly", str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    # ---- Pokemon unfreeze tests ----

    # pokemon_unfreeze_after_lock: lock should emit callnative unfreeze
    try:
        output, errors = _compile_tmp(
            "pokemon koffing npc3\n"
            "label TestLock\n"
            "lock\n"
            "end\n"
        )
        _assert("pokemon unfreeze after lock: no errors",
                len(errors) == 0, f"errors: {errors}")
        _assert("pokemon unfreeze after lock: emits callnative",
                "callnative(ScriptUnfreezePokemonActor)" in output,
                f"callnative not found in output:\n{output}")
        _assert("pokemon unfreeze after lock: sets VAR_0x8004",
                "setvar(VAR_0x8004, LOCALID_KOFFING)" in output,
                f"setvar not found in output:\n{output}")
        # callnative should come after lockall
        lockall_pos = output.index("lockall")
        callnative_pos = output.index("callnative(ScriptUnfreezePokemonActor)")
        _assert("pokemon unfreeze after lock: callnative after lockall",
                callnative_pos > lockall_pos,
                "callnative should come after lockall")
    except Exception as e:
        _fail("pokemon unfreeze after lock", str(e))

    # pokemon_unfreeze_after_face: face command should emit callnative after waitmovement
    try:
        output, errors = _compile_tmp(
            "pokemon koffing npc3\n"
            "label TestFace\n"
            "lock\n"
            "koffing face left\n"
            "end\n"
        )
        _assert("pokemon unfreeze after face: no errors",
                len(errors) == 0, f"errors: {errors}")
        # Should have callnative after the face waitmovement
        lines = output.split("\n")
        # Find waitmovement for koffing face command
        wait_indices = [i for i, l in enumerate(lines) if "waitmovement(LOCALID_KOFFING)" in l]
        callnative_indices = [i for i, l in enumerate(lines) if "callnative(ScriptUnfreezePokemonActor)" in l]
        # There should be at least one callnative after a waitmovement
        _assert("pokemon unfreeze after face: has callnative after waitmovement",
                any(ci > wi for wi in wait_indices for ci in callnative_indices),
                f"callnative should follow waitmovement\nwait_indices={wait_indices}\ncallnative_indices={callnative_indices}\n{output}")
    except Exception as e:
        _fail("pokemon unfreeze after face", str(e))

    # pokemon_no_unfreeze_for_regular_npc: regular alias should not emit callnative
    try:
        output, errors = _compile_tmp(
            "alias buster npc5\n"
            "label TestNoUnfreeze\n"
            "lock\n"
            "buster face left\n"
            "end\n"
        )
        _assert("no unfreeze for regular NPC: no errors",
                len(errors) == 0, f"errors: {errors}")
        _assert("no unfreeze for regular NPC: no callnative",
                "ScriptUnfreezePokemonActor" not in output,
                f"callnative should NOT appear for regular NPC:\n{output}")
    except Exception as e:
        _fail("no unfreeze for regular NPC", str(e))

    # pokemon_unfreeze_after_show: show should emit callnative after addobject
    try:
        output, errors = _compile_tmp(
            "pokemon koffing npc3\n"
            "label TestShow\n"
            "lock\n"
            "hide koffing\n"
            "show koffing\n"
            "end\n"
        )
        _assert("pokemon unfreeze after show: no errors",
                len(errors) == 0, f"errors: {errors}")
        lines = output.split("\n")
        add_indices = [i for i, l in enumerate(lines) if "addobject(LOCALID_KOFFING)" in l]
        callnative_indices = [i for i, l in enumerate(lines) if "callnative(ScriptUnfreezePokemonActor)" in l]
        _assert("pokemon unfreeze after show: has callnative after addobject",
                any(ci > ai for ai in add_indices for ci in callnative_indices),
                f"callnative should follow addobject\n{output}")
    except Exception as e:
        _fail("pokemon unfreeze after show", str(e))

    # pokemon_hide_no_unfreeze: hide should NOT emit callnative
    try:
        output, errors = _compile_tmp(
            "pokemon koffing npc3\n"
            "label TestHide\n"
            "lock\n"
            "hide koffing\n"
            "end\n"
        )
        _assert("pokemon hide no unfreeze: no errors",
                len(errors) == 0, f"errors: {errors}")
        lines = output.split("\n")
        # Find where removeobject is
        remove_idx = None
        for i, l in enumerate(lines):
            if "removeobject(LOCALID_KOFFING)" in l:
                remove_idx = i
                break
        # There should be NO callnative after the removeobject
        # (there will be callnatives from the lock, but none after removeobject)
        callnative_after_remove = any(
            "callnative(ScriptUnfreezePokemonActor)" in l
            for l in lines[remove_idx + 1:] if remove_idx is not None
        )
        _assert("pokemon hide no unfreeze: no callnative after removeobject",
                not callnative_after_remove,
                f"callnative should NOT appear after removeobject:\n{output}")
    except Exception as e:
        _fail("pokemon hide no unfreeze", str(e))

    # pokemon_no_old_idle_blocks: output should NOT contain walk_in_place idle movement blocks
    try:
        output, errors = _compile_tmp(
            "pokemon koffing npc3\n"
            "label TestNoIdle\n"
            "lock\n"
            "koffing face left\n"
            "end\n"
        )
        _assert("pokemon no idle blocks: no errors",
                len(errors) == 0, f"errors: {errors}")
        _assert("pokemon no idle blocks: no PokemonIdle movement block",
                "PokemonIdle" not in output,
                f"PokemonIdle movement block should not exist:\n{output}")
    except Exception as e:
        _fail("pokemon no idle blocks", str(e))

    # pokemon_multiple_actors: lock unfreezes all visible pokemon actors
    try:
        output, errors = _compile_tmp(
            "pokemon koffing npc3\n"
            "pokemon weezing npc4\n"
            "label TestMulti\n"
            "lock\n"
            "end\n"
        )
        _assert("pokemon multiple actors: no errors",
                len(errors) == 0, f"errors: {errors}")
        _assert("pokemon multiple actors: unfreezes koffing",
                "setvar(VAR_0x8004, LOCALID_KOFFING)" in output,
                f"LOCALID_KOFFING not found:\n{output}")
        _assert("pokemon multiple actors: unfreezes weezing",
                "setvar(VAR_0x8004, LOCALID_WEEZING)" in output,
                f"LOCALID_WEEZING not found:\n{output}")
        _assert("pokemon multiple actors: two callnative calls (from lock)",
                output.count("callnative(ScriptUnfreezePokemonActor)") >= 2,
                f"expected >= 2 callnative calls:\n{output}")
    except Exception as e:
        _fail("pokemon multiple actors", str(e))

    # pokemon_hidden_not_unfrozen: hidden pokemon should not be unfrozen on lock
    try:
        output, errors = _compile_tmp(
            "pokemon koffing npc3\n"
            "pokemon weezing npc4\n"
            "label TestHiddenLock\n"
            "lock\n"
            "hide koffing\n"
            "end\n"
        )
        _assert("pokemon hidden not unfrozen: no errors",
                len(errors) == 0, f"errors: {errors}")
        # Both should be unfrozen at lock (both visible at that point),
        # but after hide koffing, no more unfreeze for koffing
        lines = output.split("\n")
        remove_idx = None
        for i, l in enumerate(lines):
            if "removeobject(LOCALID_KOFFING)" in l:
                remove_idx = i
                break
        # No setvar LOCALID_KOFFING after remove
        koffing_after_remove = any(
            "setvar(VAR_0x8004, LOCALID_KOFFING)" in l
            for l in lines[remove_idx + 1:] if remove_idx is not None
        )
        _assert("pokemon hidden not unfrozen: no koffing unfreeze after hide",
                not koffing_after_remove,
                f"should not unfreeze koffing after hide:\n{output}")
    except Exception as e:
        _fail("pokemon hidden not unfrozen", str(e))

    # ---- End pokemon unfreeze tests ----

    # ---- Conditional compilation tests ----

    # Simple if FLAG / endif
    try:
        output, errors = _compile_tmp(
            "label TestIf\nlock\nif FLAG_TEST\nmsg \"yes$\"\nendif\nend\n",
            prefix="CondTest"
        )
        _assert("if FLAG: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("if FLAG: emits if (flag(FLAG_TEST))",
                "if (flag(FLAG_TEST))" in output,
                f"output:\n{output}")
        _assert("if FLAG: emits closing brace",
                output.count("}") >= 2,  # script block + if block
                f"output:\n{output}")
    except Exception as e:
        _fail("if FLAG", str(e))

    # Negated flag: if not FLAG_X
    try:
        output, errors = _compile_tmp(
            "label TestNot\nlock\nif not FLAG_TEST\nmsg \"no$\"\nendif\nend\n",
            prefix="CondTest"
        )
        _assert("if not FLAG: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("if not FLAG: emits !flag()",
                "!flag(FLAG_TEST)" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("if not FLAG", str(e))

    # Variable comparison: if VAR_X >= 5
    try:
        output, errors = _compile_tmp(
            "label TestVar\nlock\nif VAR_STORY >= 5\nmsg \"yes$\"\nendif\nend\n",
            prefix="CondTest"
        )
        _assert("if VAR >= N: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("if VAR >= N: emits var() comparison",
                "var(VAR_STORY) >= 5" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("if VAR >= N", str(e))

    # All 6 comparison operators
    for op in ("==", "!=", ">", "<", ">=", "<="):
        try:
            output, errors = _compile_tmp(
                f"label TestOp\nlock\nif VAR_X {op} 3\nmsg \"ok$\"\nendif\nend\n",
                prefix="CondTest"
            )
            _assert(f"if VAR {op}: no errors", len(errors) == 0, f"errors: {errors}")
            _assert(f"if VAR {op}: emits correct operator",
                    f"var(VAR_X) {op} 3" in output,
                    f"output:\n{output}")
        except Exception as e:
            _fail(f"if VAR {op}", str(e))

    # Defeated trainer: if defeated TRAINER_X
    try:
        output, errors = _compile_tmp(
            "label TestDefeated\nlock\nif defeated TRAINER_ROXANNE\nmsg \"beaten$\"\nendif\nend\n",
            prefix="CondTest"
        )
        _assert("if defeated: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("if defeated: emits defeated()",
                "defeated(TRAINER_ROXANNE)" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("if defeated", str(e))

    # elif chain
    try:
        output, errors = _compile_tmp(
            "label TestElif\nlock\n"
            "if FLAG_A\nmsg \"a$\"\n"
            "elif FLAG_B\nmsg \"b$\"\n"
            "else\nmsg \"c$\"\n"
            "endif\nend\n",
            prefix="CondTest"
        )
        _assert("elif chain: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("elif chain: emits if",
                "if (flag(FLAG_A))" in output,
                f"output:\n{output}")
        _assert("elif chain: emits elif",
                "elif (flag(FLAG_B))" in output,
                f"output:\n{output}")
        _assert("elif chain: emits else",
                "} else {" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("elif chain", str(e))

    # Compound condition: and
    try:
        output, errors = _compile_tmp(
            "label TestAnd\nlock\n"
            "if FLAG_A and VAR_X >= 3\nmsg \"yes$\"\nendif\nend\n",
            prefix="CondTest"
        )
        _assert("compound and: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("compound and: emits &&",
                "&&" in output,
                f"output:\n{output}")
        _assert("compound and: has flag(FLAG_A)",
                "flag(FLAG_A)" in output,
                f"output:\n{output}")
        _assert("compound and: has var(VAR_X) >= 3",
                "var(VAR_X) >= 3" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("compound and", str(e))

    # Compound condition: or
    try:
        output, errors = _compile_tmp(
            "label TestOr\nlock\n"
            "if FLAG_A or FLAG_B\nmsg \"yes$\"\nendif\nend\n",
            prefix="CondTest"
        )
        _assert("compound or: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("compound or: emits ||",
                "||" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("compound or", str(e))

    # Nested if blocks
    try:
        output, errors = _compile_tmp(
            "label TestNested\nlock\n"
            "if FLAG_A\n"
            "if VAR_X == 1\nmsg \"inner$\"\nendif\n"
            "endif\nend\n",
            prefix="CondTest"
        )
        _assert("nested if: no errors", len(errors) == 0, f"errors: {errors}")
        # Should have two if ( ... ) { blocks
        _assert("nested if: two if blocks",
                output.count("if (") >= 2,
                f"output:\n{output}")
    except Exception as e:
        _fail("nested if", str(e))

    # Error: elif without if
    try:
        output, errors = _compile_tmp(
            "label TestBadElif\nlock\nelif FLAG_A\nend\n",
            prefix="CondTest"
        )
        _assert("elif without if: produces error",
                len(errors) > 0,
                "expected error for elif without if")
        _assert("elif without if: error mentions elif",
                any("elif" in e for e in errors),
                f"errors: {errors}")
    except Exception as e:
        _fail("elif without if", str(e))

    # Error: else without if
    try:
        output, errors = _compile_tmp(
            "label TestBadElse\nlock\nelse\nend\n",
            prefix="CondTest"
        )
        _assert("else without if: produces error",
                len(errors) > 0,
                "expected error for else without if")
    except Exception as e:
        _fail("else without if", str(e))

    # Error: endif without if
    try:
        output, errors = _compile_tmp(
            "label TestBadEndif\nlock\nendif\nend\n",
            prefix="CondTest"
        )
        _assert("endif without if: produces error",
                len(errors) > 0,
                "expected error for endif without if")
    except Exception as e:
        _fail("endif without if", str(e))

    # Error: unclosed if at end of script
    try:
        output, errors = _compile_tmp(
            "label TestUnclosed\nlock\nif FLAG_A\nmsg \"yes$\"\nend\n",
            prefix="CondTest"
        )
        _assert("unclosed if: produces error",
                len(errors) > 0,
                "expected error for unclosed if")
        _assert("unclosed if: error mentions unclosed",
                any("nclosed" in e.lower() for e in errors),
                f"errors: {errors}")
    except Exception as e:
        _fail("unclosed if", str(e))

    # Empty condition (error)
    try:
        output, errors = _compile_tmp(
            "label TestEmpty\nlock\nif\nmsg \"yes$\"\nendif\nend\n",
            prefix="CondTest"
        )
        _assert("empty condition: produces error",
                len(errors) > 0,
                "expected error for empty if condition")
    except Exception as e:
        _fail("empty condition", str(e))

    # Bare VAR_X (truthiness — var != 0)
    try:
        output, errors = _compile_tmp(
            "label TestVarTruth\nlock\nif VAR_X\nmsg \"truthy$\"\nendif\nend\n",
            prefix="CondTest"
        )
        _assert("bare VAR truthiness: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("bare VAR truthiness: emits var(VAR_X)",
                "var(VAR_X)" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("bare VAR truthiness", str(e))

    # ---- End conditional compilation tests ----

    # ---- Switch/case/endswitch tests ----

    # Basic switch
    try:
        output, errors = _compile_tmp(
            "label TestSwitch\nlock\n"
            "switch VAR_QUEST\n"
            "case 0\nmsg \"start$\"\n"
            "case 1\nmsg \"mid$\"\n"
            "default\nmsg \"done$\"\n"
            "endswitch\nend\n",
            prefix="SwitchTest"
        )
        _assert("switch basic: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("switch basic: emits switch (var(...))",
                "switch (var(VAR_QUEST))" in output,
                f"output:\n{output}")
        _assert("switch basic: emits case 0",
                "case 0:" in output,
                f"output:\n{output}")
        _assert("switch basic: emits case 1",
                "case 1:" in output,
                f"output:\n{output}")
        _assert("switch basic: emits default",
                "default:" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("switch basic", str(e))

    # Error: case without switch
    try:
        output, errors = _compile_tmp(
            "label TestBadCase\nlock\ncase 1\nend\n",
            prefix="SwitchTest"
        )
        _assert("case without switch: produces error",
                len(errors) > 0,
                "expected error for case without switch")
    except Exception as e:
        _fail("case without switch", str(e))

    # Error: endswitch without switch
    try:
        output, errors = _compile_tmp(
            "label TestBadEndswitch\nlock\nendswitch\nend\n",
            prefix="SwitchTest"
        )
        _assert("endswitch without switch: produces error",
                len(errors) > 0,
                "expected error")
    except Exception as e:
        _fail("endswitch without switch", str(e))

    # Error: unclosed switch
    try:
        output, errors = _compile_tmp(
            "label TestUnclosedSwitch\nlock\nswitch VAR_X\ncase 0\nmsg \"a$\"\nend\n",
            prefix="SwitchTest"
        )
        _assert("unclosed switch: produces error",
                len(errors) > 0,
                "expected error for unclosed switch")
    except Exception as e:
        _fail("unclosed switch", str(e))

    # ---- Choice/option/endchoice tests ----

    # 2-option choice (YESNO)
    try:
        output, errors = _compile_tmp(
            'label TestChoice\nlock\n'
            'choice "What do you want?"\n'
            'option "Yes"\n'
            'option "No"\n'
            'endchoice\nend\n',
            prefix="ChoiceTest"
        )
        _assert("choice 2-opt: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("choice 2-opt: emits MSGBOX_YESNO",
                "MSGBOX_YESNO" in output,
                f"output:\n{output}")
        _assert("choice 2-opt: emits VAR_RESULT",
                "VAR_RESULT" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("choice 2-opt", str(e))

    # 3-option choice (dynmultichoice)
    try:
        output, errors = _compile_tmp(
            'label TestChoice3\nlock\n'
            'choice "Pick one"\n'
            'option "A"\n'
            'option "B"\n'
            'option "C"\n'
            'endchoice\nend\n',
            prefix="ChoiceTest"
        )
        _assert("choice 3-opt: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("choice 3-opt: emits dynmultichoice",
                "dynmultichoice" in output,
                f"output:\n{output}")
        _assert("choice 3-opt: contains all options",
                '"A"' in output and '"B"' in output and '"C"' in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("choice 3-opt", str(e))

    # Error: option without choice
    try:
        output, errors = _compile_tmp(
            'label TestBadOption\nlock\noption "test"\nend\n',
            prefix="ChoiceTest"
        )
        _assert("option without choice: produces error",
                len(errors) > 0,
                "expected error")
    except Exception as e:
        _fail("option without choice", str(e))

    # Error: endchoice without choice
    try:
        output, errors = _compile_tmp(
            "label TestBadEndchoice\nlock\nendchoice\nend\n",
            prefix="ChoiceTest"
        )
        _assert("endchoice without choice: produces error",
                len(errors) > 0,
                "expected error")
    except Exception as e:
        _fail("endchoice without choice", str(e))

    # ---- Check command tests ----

    # check item
    try:
        output, errors = _compile_tmp(
            "label TestCheckItem\nlock\ncheck item ITEM_POTION\nend\n",
            prefix="CheckTest"
        )
        _assert("check item: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("check item: emits checkitem()",
                "checkitem(ITEM_POTION)" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("check item", str(e))

    # check partysize
    try:
        output, errors = _compile_tmp(
            "label TestCheckParty\nlock\ncheck partysize\nend\n",
            prefix="CheckTest"
        )
        _assert("check partysize: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("check partysize: emits getpartysize",
                "getpartysize" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("check partysize", str(e))

    # check money
    try:
        output, errors = _compile_tmp(
            "label TestCheckMoney\nlock\ncheck money 500\nend\n",
            prefix="CheckTest"
        )
        _assert("check money: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("check money: emits checkmoney()",
                "checkmoney(500)" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("check money", str(e))

    # check badge
    try:
        output, errors = _compile_tmp(
            "label TestCheckBadge\nlock\ncheck badge 3\nend\n",
            prefix="CheckTest"
        )
        _assert("check badge: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("check badge: emits checkbadge()",
                "checkbadge(3)" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("check badge", str(e))

    # Error: check with unknown type
    try:
        output, errors = _compile_tmp(
            "label TestBadCheck\nlock\ncheck foo\nend\n",
            prefix="CheckTest"
        )
        _assert("check unknown type: produces error",
                len(errors) > 0,
                "expected error for unknown check type")
    except Exception as e:
        _fail("check unknown type", str(e))

    # Error: check item without argument
    try:
        output, errors = _compile_tmp(
            "label TestCheckNoArg\nlock\ncheck item\nend\n",
            prefix="CheckTest"
        )
        _assert("check item no arg: produces error",
                len(errors) > 0,
                "expected error for missing argument")
    except Exception as e:
        _fail("check item no arg", str(e))

    # Combined: check + if (typical usage pattern)
    try:
        output, errors = _compile_tmp(
            "label TestCheckIf\nlock\n"
            "check item ITEM_BADGE_CASE\n"
            "if VAR_RESULT == TRUE\n"
            "msg \"You have it!$\"\n"
            "endif\nend\n",
            prefix="CheckTest"
        )
        _assert("check+if combo: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("check+if combo: emits checkitem",
                "checkitem(ITEM_BADGE_CASE)" in output,
                f"output:\n{output}")
        _assert("check+if combo: emits var(VAR_RESULT)",
                "var(VAR_RESULT) == TRUE" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("check+if combo", str(e))

    # ---- End S281 tests ----

    # ================================================================
    # S285 — NPC Pages
    # ================================================================

    # --- Basic page compilation ---

    # Two pages: default + conditional flag
    try:
        output, errors = _compile_tmp(
            "alias jenny npc3\n"
            "\n"
            "page 1\n"
            "label TestMap_Jenny\n"
            "lock\n"
            'msg "Hello.$"\n'
            "end\n"
            "\n"
            "page 2 if FLAG_BEAT_GYM\n"
            "label TestMap_Jenny\n"
            "lock\n"
            'msg "You beat the gym!$"\n'
            "end\n",
            prefix="TestMap"
        )
        _assert("two pages: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("two pages: single script block",
                output.count("script TestMap_Jenny {") == 1,
                f"output:\n{output}")
        _assert("two pages: page 2 has if wrapper",
                "if (flag(FLAG_BEAT_GYM))" in output,
                f"output:\n{output}")
        _assert("two pages: page 1 default comment",
                "Page 1 (default)" in output,
                f"output:\n{output}")
        # Page 2 should appear before page 1 (descending priority)
        p2_pos = output.find("Page 2")
        p1_pos = output.find("Page 1")
        _assert("two pages: page 2 before page 1 (descending priority)",
                p2_pos < p1_pos,
                f"p2={p2_pos}, p1={p1_pos}")
    except Exception as e:
        _fail("two pages", str(e))

    # Three pages with descending priority
    try:
        output, errors = _compile_tmp(
            "alias npc1 npc1\n"
            "\n"
            "page 1\n"
            "label TestMap_NPC\n"
            'msg "Default.$"\n'
            "end\n"
            "\n"
            "page 2 if FLAG_A\n"
            "label TestMap_NPC\n"
            'msg "After A.$"\n'
            "end\n"
            "\n"
            "page 3 if FLAG_B\n"
            "label TestMap_NPC\n"
            'msg "After B.$"\n'
            "end\n",
            prefix="TestMap"
        )
        _assert("three pages: no errors", len(errors) == 0, f"errors: {errors}")
        # Check order: page 3, page 2, page 1
        p3 = output.find("Page 3")
        p2 = output.find("Page 2")
        p1 = output.find("Page 1")
        _assert("three pages: 3 before 2 before 1",
                p3 < p2 < p1,
                f"positions: {p3}, {p2}, {p1}")
    except Exception as e:
        _fail("three pages", str(e))

    # Page with compound condition (and)
    try:
        output, errors = _compile_tmp(
            "page 1\n"
            "label TestMap_Guard\n"
            'msg "Blocked.$"\n'
            "end\n"
            "\n"
            "page 2 if FLAG_A and VAR_STORY >= 5\n"
            "label TestMap_Guard\n"
            'msg "Go ahead.$"\n'
            "end\n",
            prefix="TestMap"
        )
        _assert("compound page condition: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("compound page condition: has && in output",
                "&&" in output,
                f"output:\n{output}")
        _assert("compound page condition: flag(FLAG_A)",
                "flag(FLAG_A)" in output,
                f"output:\n{output}")
        _assert("compound page condition: var(VAR_STORY) >= 5",
                "var(VAR_STORY) >= 5" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("compound page condition", str(e))

    # Page with defeated condition
    try:
        output, errors = _compile_tmp(
            "page 1\n"
            "label TestMap_Trainer\n"
            'msg "Let us battle!$"\n'
            "end\n"
            "\n"
            "page 2 if defeated TRAINER_FOE\n"
            "label TestMap_Trainer\n"
            'msg "You won.$"\n'
            "end\n",
            prefix="TestMap"
        )
        _assert("defeated page: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("defeated page: defeated(TRAINER_FOE)",
                "defeated(TRAINER_FOE)" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("defeated page condition", str(e))

    # Page with negated condition
    try:
        output, errors = _compile_tmp(
            "page 1\n"
            "label TestMap_NPC\n"
            'msg "Default.$"\n'
            "end\n"
            "\n"
            "page 2 if not FLAG_HIDDEN\n"
            "label TestMap_NPC\n"
            'msg "Visible.$"\n'
            "end\n",
            prefix="TestMap"
        )
        _assert("negated page: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("negated page: !flag(FLAG_HIDDEN)",
                "!flag(FLAG_HIDDEN)" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("negated page condition", str(e))

    # --- Page with hide ---

    # Hide directive (pure visibility page)
    try:
        output, errors = _compile_tmp(
            "alias jenny npc3\n"
            "\n"
            "page 1\n"
            "label TestMap_Jenny\n"
            'msg "Hello.$"\n'
            "end\n"
            "\n"
            "page 2 if FLAG_GONE\n"
            "hide jenny\n"
            "label TestMap_Jenny\n"
            "end\n",  # label needed but body empty — hide is page-level
            prefix="TestMap"
        )
        _assert("hide page: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("hide page: removeobject in output",
                "removeobject(LOCALID_JENNY)" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("hide page", str(e))

    # --- Multiple NPCs ---

    # Two different NPCs with pages in same file
    try:
        output, errors = _compile_tmp(
            "alias npc1 npc1\n"
            "alias npc2 npc2\n"
            "\n"
            "page 1\n"
            "label TestMap_NPC1\n"
            'msg "NPC1 default.$"\n'
            "end\n"
            "\n"
            "page 2 if FLAG_A\n"
            "label TestMap_NPC1\n"
            'msg "NPC1 page 2.$"\n'
            "end\n"
            "\n"
            "page 1\n"
            "label TestMap_NPC2\n"
            'msg "NPC2 default.$"\n'
            "end\n"
            "\n"
            "page 2 if FLAG_B\n"
            "label TestMap_NPC2\n"
            'msg "NPC2 page 2.$"\n'
            "end\n",
            prefix="TestMap"
        )
        _assert("multi-NPC pages: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("multi-NPC pages: script TestMap_NPC1",
                "script TestMap_NPC1 {" in output,
                f"output:\n{output}")
        _assert("multi-NPC pages: script TestMap_NPC2",
                "script TestMap_NPC2 {" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("multi-NPC pages", str(e))

    # --- Page body with nested features ---

    # Page containing if/elif/else/endif
    try:
        output, errors = _compile_tmp(
            "page 1\n"
            "label TestMap_NPC\n"
            "lock\n"
            "if FLAG_X\n"
            '    msg "X set.$"\n'
            "else\n"
            '    msg "X not set.$"\n'
            "endif\n"
            "end\n"
            "\n"
            "page 2 if FLAG_Y\n"
            "label TestMap_NPC\n"
            'msg "Page 2.$"\n'
            "end\n",
            prefix="TestMap"
        )
        _assert("nested if in page: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("nested if in page: has flag(FLAG_X)",
                "flag(FLAG_X)" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("nested if in page", str(e))

    # --- Error cases ---

    # Page without number
    try:
        output, errors = _compile_tmp("page\nlabel Test\nend\n", prefix="Test")
        _assert("page no number: has error", len(errors) > 0, f"errors: {errors}")
    except Exception as e:
        _fail("page no number", str(e))

    # Duplicate page number for same label
    try:
        output, errors = _compile_tmp(
            "page 1\nlabel TestMap_NPC\nend\n"
            "page 1\nlabel TestMap_NPC\nend\n",
            prefix="TestMap"
        )
        _assert("duplicate page number: has error", len(errors) > 0, f"errors: {errors}")
    except Exception as e:
        _fail("duplicate page number", str(e))

    # Page 1 with condition
    try:
        output, errors = _compile_tmp(
            "page 1 if FLAG_X\nlabel Test\nend\n",
            prefix="Test"
        )
        _assert("page 1 with condition: has error", len(errors) > 0, f"errors: {errors}")
    except Exception as e:
        _fail("page 1 with condition", str(e))

    # Page 2+ without condition
    try:
        output, errors = _compile_tmp(
            "page 1\nlabel Test\nend\n"
            "page 2\nlabel Test\nend\n",
            prefix="Test"
        )
        _assert("page 2 no condition: has error", len(errors) > 0, f"errors: {errors}")
    except Exception as e:
        _fail("page 2 no condition", str(e))

    # --- Self-flags ---

    # self.talked in if condition
    try:
        output, errors = _compile_tmp(
            "page 1\n"
            "label TestMap_NPC\n"
            "lock\n"
            "if self.talked\n"
            '    msg "Again.$"\n'
            "else\n"
            '    msg "First time!$"\n'
            "    flag set self.talked\n"
            "endif\n"
            "end\n",
            prefix="TestMap"
        )
        _assert("self-flag: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("self-flag: FLAG_SELF_ in condition",
                "flag(FLAG_SELF_" in output,
                f"output:\n{output}")
        _assert("self-flag: setflag(FLAG_SELF_ in output",
                "setflag(FLAG_SELF_" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("self-flag", str(e))

    # Self-flag deterministic naming
    try:
        from torch.self_flags import make_self_flag_name
        name = make_self_flag_name("ShirubeTown", "Officer", "talked")
        _assert("self-flag naming: starts with FLAG_SELF_",
                name.startswith("FLAG_SELF_"),
                f"got: {name}")
        _assert("self-flag naming: ends with TALKED",
                name.endswith("_TALKED"),
                f"got: {name}")
        _assert("self-flag naming: is uppercase",
                name == name.upper(),
                f"got: {name}")
    except Exception as e:
        _fail("self-flag naming", str(e))

    # --- Mixing pages and regular scripts ---

    # File with a paged NPC and a regular non-paged script
    try:
        output, errors = _compile_tmp(
            "alias npc1 npc1\n"
            "\n"
            "page 1\n"
            "label TestMap_PagedNPC\n"
            'msg "Paged default.$"\n'
            "end\n"
            "\n"
            "page 2 if FLAG_X\n"
            "label TestMap_PagedNPC\n"
            'msg "Paged conditional.$"\n'
            "end\n"
            "\n"
            "label TestMap_RegularScript\n"
            "lock\n"
            'msg "Regular script.$"\n'
            "end\n",
            prefix="TestMap"
        )
        _assert("mixed pages+regular: no errors", len(errors) == 0, f"errors: {errors}")
        _assert("mixed: paged script exists",
                "script TestMap_PagedNPC {" in output,
                f"output:\n{output}")
        _assert("mixed: regular script exists",
                "script TestMap_RegularScript {" in output,
                f"output:\n{output}")
    except Exception as e:
        _fail("mixed pages and regular scripts", str(e))

    # ---- End S285 tests ----
