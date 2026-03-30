"""Decompiler suite -- verifies .pory -> TorScript decompilation."""
import os
import tempfile

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert, _fixture


def run_suite():
    _begin_suite("Decompiler")

    try:
        from torch.decompiler import decompile, decompile_file
        from torch.compiler import compile_script
    except ImportError as e:
        _skip("all decompiler tests", f"import failed: {e}")
        return

    emotes_conf = ""

    # ── Round-trip tests ──────────────────────────────────────────
    # Compile TorScript -> .pory, decompile back, recompile, compare .pory output

    fixtures = ["Officer.txt", "Buster.txt", "ClydeArrives.txt",
                "GiveItem.txt", "GiveItemQty.txt"]

    for fname in fixtures:
        path = _fixture(fname)
        label = fname.replace(".txt", "")
        try:
            # Compile original
            pory1, errs1 = compile_script(path, label, emotes_conf)
            _assert(
                f"round-trip {fname}: compile OK",
                len(errs1) == 0,
                f"compile errors: {errs1}"
            )
            # Decompile
            ts, warnings = decompile(pory1, label)
            _assert(
                f"round-trip {fname}: decompile produces output",
                bool(ts and ts.strip()),
                "decompile returned empty"
            )
            # Recompile from decompiled TorScript
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as tmp:
                tmp.write(ts)
                tmp_path = tmp.name
            try:
                pory2, errs2 = compile_script(tmp_path, label, emotes_conf)
                _assert(
                    f"round-trip {fname}: recompile OK",
                    len(errs2) == 0,
                    f"recompile errors: {errs2}"
                )
                # Normalize and compare: strip blank lines + whitespace,
                # and equate lock/lockall and release+end/releaseall+end
                # since TorScript 'lock' compiles to 'lockall' in Poryscript.
                def normalize(text):
                    lines = [l.strip() for l in text.strip().split('\n')]
                    out = []
                    for l in lines:
                        if not l:
                            continue
                        # Normalize: TorScript 'lock' compiles to 'lockall'
                        if l == "lock":
                            l = "lockall"
                        # Normalize: standalone 'end'/'release' become pairs
                        if l == "end" and (not out or out[-1] != "releaseall"):
                            out.append("releaseall")
                        if l == "release" and (not out or out[-1] not in ("release",)):
                            out.append("release")
                            l = "end"
                        out.append(l)
                    return '\n'.join(out)
                n1 = normalize(pory1)
                n2 = normalize(pory2)
                _assert(
                    f"round-trip {fname}: pory output matches",
                    n1 == n2,
                    f"pory mismatch:\n--- original ---\n{n1[:500]}\n--- recompiled ---\n{n2[:500]}"
                )
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            _fail(f"round-trip {fname}", str(e))

    # ── Single-line handler tests ─────────────────────────────────

    # lock / end / release
    _test_snippet(
        "lock -> lockall",
        'script Test {\n    lockall\n}',
        "Test",
        lambda ts: "lock" in ts and "lockall" not in ts
    )

    _test_snippet(
        "releaseall+end -> end",
        'script Test {\n    releaseall\n    end\n}',
        "Test",
        lambda ts: ts.strip().endswith("end") and "releaseall" not in ts
    )

    _test_snippet(
        "release+end -> release",
        'script Test {\n    release\n    end\n}',
        "Test",
        lambda ts: "release" in ts and "end" not in ts.replace("release", "")
    )

    # faceplayer
    _test_snippet(
        "faceplayer passthrough",
        'script Test {\n    faceplayer\n}',
        "Test",
        lambda ts: "faceplayer" in ts
    )

    # msgbox DEFAULT
    _test_snippet(
        'msgbox DEFAULT -> msg',
        'script Test {\n    msgbox("Hello there$", MSGBOX_DEFAULT)\n}',
        "Test",
        lambda ts: 'msg "Hello there"' in ts
    )

    # msgbox NPC
    _test_snippet(
        'msgbox NPC -> msgnpc',
        'script Test {\n    msgbox("Hey$", MSGBOX_NPC)\n}',
        "Test",
        lambda ts: 'msgnpc "Hey"' in ts
    )

    # msgbox with format() wrapper
    _test_snippet(
        'msgbox format() -> msg',
        'script Test {\n    msgbox(format("Wrapped$"), MSGBOX_DEFAULT)\n}',
        "Test",
        lambda ts: 'msg "Wrapped"' in ts
    )

    # fadescreen
    _test_snippet(
        "fadescreen FADE_TO_BLACK -> fade black",
        'script Test {\n    fadescreen(FADE_TO_BLACK)\n}',
        "Test",
        lambda ts: "fade black" in ts
    )

    _test_snippet(
        "fadescreen FADE_FROM_BLACK -> fade in",
        'script Test {\n    fadescreen(FADE_FROM_BLACK)\n}',
        "Test",
        lambda ts: "fade in" in ts
    )

    # sound / music / cry
    _test_snippet(
        "playse -> sound",
        'script Test {\n    playse(SE_EXIT)\n}',
        "Test",
        lambda ts: "sound SE_EXIT" in ts
    )

    _test_snippet(
        "playbgm -> music",
        'script Test {\n    playbgm(MUS_CAVE, FALSE)\n}',
        "Test",
        lambda ts: "music MUS_CAVE" in ts
    )

    _test_snippet(
        "playmoncry -> cry",
        'script Test {\n    playmoncry(SPECIES_PIKACHU, CRY_MODE_NORMAL)\n}',
        "Test",
        lambda ts: "cry SPECIES_PIKACHU" in ts
    )

    # delay -> pause
    _test_snippet(
        "delay(16) -> pause",
        'script Test {\n    delay(16)\n}',
        "Test",
        lambda ts: "pause" in ts and "16" not in ts
    )

    _test_snippet(
        "delay(32) -> pause long",
        'script Test {\n    delay(32)\n}',
        "Test",
        lambda ts: "pause long" in ts
    )

    _test_snippet(
        "delay(8) -> pause 8",
        'script Test {\n    delay(8)\n}',
        "Test",
        lambda ts: "pause 8" in ts
    )

    # flag set / clear
    _test_snippet(
        "setflag -> flag set",
        'script Test {\n    setflag(FLAG_TEST)\n}',
        "Test",
        lambda ts: "flag set FLAG_TEST" in ts
    )

    _test_snippet(
        "clearflag -> flag clear",
        'script Test {\n    clearflag(FLAG_TEST)\n}',
        "Test",
        lambda ts: "flag clear FLAG_TEST" in ts
    )

    # setvar -> var
    _test_snippet(
        "setvar -> var",
        'script Test {\n    setvar(VAR_TEMP, 5)\n}',
        "Test",
        lambda ts: "var VAR_TEMP 5" in ts
    )

    # removeobject / addobject with alias
    _test_snippet(
        "removeobject with alias -> hide",
        'const LOCALID_BUSTER = 5\n\nscript Test {\n    removeobject(LOCALID_BUSTER)\n}',
        "Test",
        lambda ts: "hide buster" in ts
    )

    _test_snippet(
        "addobject with alias -> show",
        'const LOCALID_BUSTER = 5\n\nscript Test {\n    addobject(LOCALID_BUSTER)\n}',
        "Test",
        lambda ts: "show buster" in ts
    )

    _test_snippet(
        "removeobject player -> hide player",
        'script Test {\n    removeobject(OBJ_EVENT_ID_PLAYER)\n}',
        "Test",
        lambda ts: "hide player" in ts
    )

    # setobjectxy -> setpos
    _test_snippet(
        "setobjectxy -> setpos",
        'const LOCALID_NPC = 3\n\nscript Test {\n    setobjectxy(LOCALID_NPC, 10, 20)\n}',
        "Test",
        lambda ts: "setpos npc 10 20" in ts
    )

    # special
    _test_snippet(
        "special -> special",
        'script Test {\n    special(HealPlayerParty)\n}',
        "Test",
        lambda ts: "special HealPlayerParty" in ts
    )

    # goto / call
    _test_snippet(
        "goto -> goto",
        'script Test {\n    goto(SomeLabel)\n}',
        "Test",
        lambda ts: "goto SomeLabel" in ts
    )

    _test_snippet(
        "call -> call",
        'script Test {\n    call(SomeLabel)\n}',
        "Test",
        lambda ts: "call SomeLabel" in ts
    )

    # return
    _test_snippet(
        "return -> return",
        'script Test {\n    return\n}',
        "Test",
        lambda ts: "return" in ts
    )

    # ── Multi-line pattern tests ──────────────────────────────────

    # shake (3-line)
    _test_snippet(
        "shake pattern",
        'script Test {\n    setvar(VAR_0x8004, 4)\n    setvar(VAR_0x8005, 2)\n    special(ShakeCamera)\n}',
        "Test",
        lambda ts: "shake 4 2" in ts
    )

    # give with bag-full suppression
    _test_snippet(
        "give pattern with BagFull",
        ('script Test {\n    giveitem(ITEM_POTION)\n    compare(VAR_RESULT, FALSE)\n'
         '    goto_if_eq(Test_BagFull)\n}\n\n'
         'script Test_BagFull {\n    msgbox(format("Your bag is too full!"), MSGBOX_DEFAULT)\n'
         '    release\n    end\n}'),
        "Test",
        lambda ts: "give ITEM_POTION" in ts and "BagFull" not in ts
    )

    # give with quantity
    _test_snippet(
        "give with quantity",
        ('script Test {\n    giveitem(ITEM_RARE_CANDY, 3)\n    compare(VAR_RESULT, FALSE)\n'
         '    goto_if_eq(Test_BagFull)\n}'),
        "Test",
        lambda ts: "give ITEM_RARE_CANDY 3" in ts
    )

    # fanfare (2-line)
    _test_snippet(
        "fanfare pattern",
        'script Test {\n    playfanfare(MUS_FANFARE1)\n    waitfanfare\n}',
        "Test",
        lambda ts: "fanfare MUS_FANFARE1" in ts
    )

    # gotoif (3-line if/goto/brace)
    _test_snippet(
        "gotoif pattern",
        'script Test {\n    if (flag(FLAG_TEST)) {\n        goto(SomeLabel)\n    }\n}',
        "Test",
        lambda ts: "gotoif FLAG_TEST SomeLabel" in ts
    )

    # ── Movement tests ────────────────────────────────────────────

    # Common_Movement face
    _test_snippet(
        "movement: Common_Movement_FaceDown",
        'const LOCALID_NPC = 1\n\nscript Test {\n    applymovement(LOCALID_NPC, Common_Movement_FaceDown)\n    waitmovement(0)\n}',
        "Test",
        lambda ts: "npc face down" in ts
    )

    # Common_Movement emote
    _test_snippet(
        "movement: Common_Movement_ExclamationMark",
        'const LOCALID_NPC = 1\n\nscript Test {\n    applymovement(LOCALID_NPC, Common_Movement_ExclamationMark)\n    waitmovement(0)\n}',
        "Test",
        lambda ts: "npc emote !" in ts
    )

    # Auto movement block — walk
    _test_snippet(
        "movement: auto walk block",
        ('const LOCALID_NPC = 1\n\n'
         'script Test {\n    applymovement(LOCALID_NPC, Test_Move_1)\n    waitmovement(0)\n}\n\n'
         'movement Test_Move_1 {\n    walk_up * 3\n}'),
        "Test",
        lambda ts: "npc walk up 3" in ts and "Move_1" not in ts
    )

    # Player movement
    _test_snippet(
        "movement: player face",
        'script Test {\n    applymovement(OBJ_EVENT_ID_PLAYER, Common_Movement_FaceUp)\n    waitmovement(0)\n}',
        "Test",
        lambda ts: "player face up" in ts
    )

    # Parallel movement
    _test_snippet(
        "movement: parallel with +",
        ('const LOCALID_BUSTER = 5\n\n'
         'script Test {\n'
         '    applymovement(LOCALID_BUSTER, Common_Movement_FaceDown)\n'
         '    applymovement(OBJ_EVENT_ID_PLAYER, Common_Movement_FaceDown)\n'
         '    waitmovement(LOCALID_BUSTER)\n'
         '    waitmovement(OBJ_EVENT_ID_PLAYER)\n}'),
        "Test",
        lambda ts: "+" in ts and "buster face down" in ts and "player face down" in ts
    )

    # ── Alias + const tests ───────────────────────────────────────

    _test_snippet(
        "const -> alias declaration",
        'const LOCALID_CLYDE = 6\n\nscript Test {\n    lockall\n}',
        "Test",
        lambda ts: "alias clyde npc6" in ts
    )

    # ── Mapscripts test ───────────────────────────────────────────

    _test_snippet(
        "mapscripts passthrough",
        'mapscripts TestMap_MapScripts {}\n\nscript Test {\n    lockall\n}',
        "TestMap",
        lambda ts: "mapscripts TestMap_MapScripts" in ts
    )

    # ── Trainerbattle passthrough ─────────────────────────────────

    _test_snippet(
        "trainerbattle native beat",
        'script Test {\n    trainerbattle_single(TRAINER_X, Text1, Text2)\n}',
        "Test",
        lambda ts: "trainerbattle_single TRAINER_X, Text1, Text2" in ts
            and "pory " not in ts
    )

    # ── Fallthrough to pory ───────────────────────────────────────

    _test_snippet(
        "unknown line -> pory fallthrough",
        'script Test {\n    somecustomcommand(arg1, arg2)\n}',
        "Test",
        lambda ts: "pory somecustomcommand(arg1, arg2)" in ts
    )

    # ── Follower commands ─────────────────────────────────────────

    _test_snippet(
        "follower remove",
        'script Test {\n    destroyfollowernpc\n}',
        "Test",
        lambda ts: "follower remove" in ts
    )

    _test_snippet(
        "follower face",
        'script Test {\n    facefollowernpc\n}',
        "Test",
        lambda ts: "follower face" in ts
    )

    # ── decompile_file test ───────────────────────────────────────

    try:
        # Write a small .pory file and decompile it
        pory_content = 'script FileTest {\n    lockall\n    faceplayer\n    releaseall\n    end\n}\n'
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pory", prefix="TestMap_",
            delete=False
        ) as tmp:
            tmp.write(pory_content)
            tmp_path = tmp.name
        try:
            ts, warnings = decompile_file(tmp_path)
            _assert(
                "decompile_file: produces output",
                bool(ts and ts.strip()),
                "decompile_file returned empty"
            )
            _assert(
                "decompile_file: has lock",
                "lock" in ts,
                f"expected 'lock' in output: {ts}"
            )
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        _fail("decompile_file", str(e))


    # ── Integration: multi-script whole-file import ─────────────────
    try:
        multi_pory = (
            'const LOCALID_GUARD = 1\n'
            'const LOCALID_NURSE = 2\n\n'
            'script TestMap_EventScript_Guard {\n'
            '    lock\n'
            '    faceplayer\n'
            '    msgbox("Halt!$", MSGBOX_NPC)\n'
            '    release\n'
            '    end\n'
            '}\n\n'
            'script TestMap_EventScript_Nurse {\n'
            '    lock\n'
            '    faceplayer\n'
            '    msgbox("Need healing?$", MSGBOX_NPC)\n'
            '    release\n'
            '    end\n'
            '}\n'
        )
        ts, warnings = decompile(multi_pory, "TestMap")
        _assert(
            "multi-script import: both scripts present",
            "EventScript_Guard" in ts and "EventScript_Nurse" in ts,
            f"expected both Guard and Nurse scripts in output:\n{ts}"
        )
        _assert(
            "multi-script import: dialogue preserved",
            "Halt!" in ts and "Need healing?" in ts,
            f"expected dialogue in output:\n{ts}"
        )
    except Exception as e:
        _fail("multi-script import", str(e))

    # ── Integration: CLI decompile_file smoke test ────────────────
    try:
        pory_content = (
            'script CLITest_EventScript_Hello {\n'
            '    lockall\n'
            '    msgbox("Hi there$", MSGBOX_DEFAULT)\n'
            '    releaseall\n'
            '    end\n'
            '}\n'
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pory", prefix="CLITest_",
            delete=False
        ) as tmp:
            tmp.write(pory_content)
            tmp_path = tmp.name
        try:
            ts, warnings = decompile_file(tmp_path, "CLITest")
            _assert(
                "CLI smoke: produces valid TorScript",
                "script Hello" in ts or "script CLITest_EventScript_Hello" in ts,
                f"script label not found in output:\n{ts}"
            )
            _assert(
                "CLI smoke: dialogue intact",
                "Hi there" in ts,
                f"expected dialogue in output:\n{ts}"
            )
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        _fail("CLI decompile smoke", str(e))

    # ── Integration: round-trip complex script through decompile ──
    try:
        complex_pory = (
            'const LOCALID_NPC = 3\n\n'
            'script TestMap_EventScript_Complex {\n'
            '    lock\n'
            '    faceplayer\n'
            '    setflag(FLAG_TEST)\n'
            '    msgbox("Complex test$", MSGBOX_NPC)\n'
            '    removeobject(LOCALID_NPC)\n'
            '    release\n'
            '    end\n'
            '}\n'
        )
        ts, warnings = decompile(complex_pory, "TestMap")
        _assert(
            "complex script: decompiles to TorScript",
            bool(ts and ts.strip()),
            "decompile returned empty"
        )
        # Recompile the decompiled TorScript
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as tmp:
            tmp.write(ts)
            tmp_path = tmp.name
        try:
            pory2, errs = compile_script(tmp_path, "Complex", emotes_conf)
            _assert(
                "complex script: recompile succeeds",
                len(errs) == 0,
                f"recompile errors: {errs}"
            )
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        _fail("complex script round-trip", str(e))


def _test_snippet(name, pory_input, map_name, check_fn):
    """Helper: decompile a .pory snippet and check the output."""
    try:
        from torch.decompiler import decompile
        ts, warnings = decompile(pory_input, map_name)
        _assert(name, check_fn(ts), f"check failed on output:\n{ts}")
    except Exception as e:
        _fail(name, str(e))
