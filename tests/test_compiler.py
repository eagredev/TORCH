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
