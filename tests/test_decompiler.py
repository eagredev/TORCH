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


    # ── Stream 1: Condition reversal tests ──────────────────────

    try:
        from torch.decompiler import _reverse_condition

        # flag
        _assert("rev_cond: flag", _reverse_condition("flag(FLAG_X)") == "FLAG_X", "")
        # !flag
        _assert("rev_cond: !flag", _reverse_condition("!flag(FLAG_X)") == "not FLAG_X", "")
        # var ==
        _assert("rev_cond: var ==", _reverse_condition("var(VAR_X) == 5") == "VAR_X == 5", "")
        # var !=
        _assert("rev_cond: var !=", _reverse_condition("var(VAR_X) != 5") == "VAR_X != 5", "")
        # var <
        _assert("rev_cond: var <", _reverse_condition("var(VAR_X) < 10") == "VAR_X < 10", "")
        # var >
        _assert("rev_cond: var >", _reverse_condition("var(VAR_X) > 0") == "VAR_X > 0", "")
        # var <=
        _assert("rev_cond: var <=", _reverse_condition("var(VAR_X) <= 3") == "VAR_X <= 3", "")
        # var >=
        _assert("rev_cond: var >=", _reverse_condition("var(VAR_X) >= 7") == "VAR_X >= 7", "")
        # defeated
        _assert("rev_cond: defeated", _reverse_condition("defeated(TRAINER_X)") == "defeated TRAINER_X", "")
        # !defeated
        _assert("rev_cond: !defeated", _reverse_condition("!defeated(TRAINER_X)") == "not defeated TRAINER_X", "")
        # compound &&
        result = _reverse_condition("flag(FLAG_A) && flag(FLAG_B)")
        _assert("rev_cond: &&", result == "FLAG_A and FLAG_B", f"got: {result}")
        # compound ||
        result = _reverse_condition("flag(FLAG_A) || var(VAR_X) == 1")
        _assert("rev_cond: ||", result == "FLAG_A or VAR_X == 1", f"got: {result}")
        # negated var expression
        result = _reverse_condition("!(var(VAR_X) == 5)")
        _assert("rev_cond: negated var", result == "not VAR_X == 5", f"got: {result}")
        # var with named constant value
        result = _reverse_condition("var(VAR_RESULT) == MALE")
        _assert("rev_cond: var named const", result == "VAR_RESULT == MALE", f"got: {result}")
    except Exception as e:
        _fail("rev_cond tests", str(e))

    # ── Stream 1: Expanded conditional jump tests ────────────────

    # goto + flag (existing pattern, still works)
    _test_snippet(
        "cond_jump: goto + flag",
        'script Test {\n    if (flag(FLAG_TEST)) {\n        goto(SomeLabel)\n    }\n}',
        "Test",
        lambda ts: "gotoif FLAG_TEST SomeLabel" in ts
    )

    # goto + var condition
    _test_snippet(
        "cond_jump: goto + var ==",
        'script Test {\n    if (var(VAR_X) == 5) {\n        goto(Label5)\n    }\n}',
        "Test",
        lambda ts: "gotoif VAR_X == 5 Label5" in ts
    )

    # goto + !flag
    _test_snippet(
        "cond_jump: goto + !flag",
        'script Test {\n    if (!flag(FLAG_DONE)) {\n        goto(NotDone)\n    }\n}',
        "Test",
        lambda ts: "gotoif not FLAG_DONE NotDone" in ts
    )

    # goto + defeated
    _test_snippet(
        "cond_jump: goto + defeated",
        'script Test {\n    if (defeated(TRAINER_BROCK)) {\n        goto(PostBattle)\n    }\n}',
        "Test",
        lambda ts: "gotoif defeated TRAINER_BROCK PostBattle" in ts
    )

    # call + flag → if/call/endif
    _test_snippet(
        "cond_jump: call + flag -> if/call/endif",
        'script Test {\n    if (flag(FLAG_X)) {\n        call(SubLabel)\n    }\n}',
        "Test",
        lambda ts: "if FLAG_X" in ts and "call SubLabel" in ts and "endif" in ts
    )

    # call + var condition
    _test_snippet(
        "cond_jump: call + var ==",
        'script Test {\n    if (var(VAR_RESULT) == MALE) {\n        call(MaleHandler)\n    }\n}',
        "Test",
        lambda ts: "if VAR_RESULT == MALE" in ts and "call MaleHandler" in ts
    )

    # ── Stream 1: Mapscripts dedup ──────────────────────────────

    _test_snippet(
        "mapscripts dedup",
        ('mapscripts TestMap_MapScripts {\n    MAP_SCRIPT_ON_TRANSITION: Handler1\n}\n'
         'mapscripts TestMap_MapScripts {\n    MAP_SCRIPT_ON_RESUME: Handler2\n}\n'
         'mapscripts TestMap_MapScripts {\n    MAP_SCRIPT_ON_LOAD: Handler3\n}\n'
         'script Test {\n    lockall\n}'),
        "TestMap",
        lambda ts: ts.count("mapscripts TestMap_MapScripts") == 1
    )

    # ── Stream 2: if/elif/else/endif blocks ──────────────────────

    # Simple if block (single branch, body with multiple statements)
    _test_snippet(
        "if_block: simple if",
        ('script Test {\n'
         '    if (flag(FLAG_X)) {\n'
         '        msgbox("Inside if$", MSGBOX_DEFAULT)\n'
         '        setflag(FLAG_Y)\n'
         '    }\n}'),
        "Test",
        lambda ts: "if FLAG_X" in ts and 'msg "Inside if"' in ts
            and "flag set FLAG_Y" in ts and "endif" in ts
    )

    # if/else block
    _test_snippet(
        "if_block: if/else",
        ('script Test {\n'
         '    if (flag(FLAG_X)) {\n'
         '        msgbox("Yes$", MSGBOX_DEFAULT)\n'
         '    } else {\n'
         '        msgbox("No$", MSGBOX_DEFAULT)\n'
         '    }\n}'),
        "Test",
        lambda ts: "if FLAG_X" in ts and 'msg "Yes"' in ts
            and "else" in ts and 'msg "No"' in ts and "endif" in ts
    )

    # if/elif/else block
    _test_snippet(
        "if_block: if/elif/else",
        ('script Test {\n'
         '    if (var(VAR_X) == 1) {\n'
         '        msgbox("One$", MSGBOX_DEFAULT)\n'
         '    } elif (var(VAR_X) == 2) {\n'
         '        msgbox("Two$", MSGBOX_DEFAULT)\n'
         '    } else {\n'
         '        msgbox("Other$", MSGBOX_DEFAULT)\n'
         '    }\n}'),
        "Test",
        lambda ts: "if VAR_X == 1" in ts and "elif VAR_X == 2" in ts
            and "else" in ts and "endif" in ts
    )

    # Nested if inside if
    _test_snippet(
        "if_block: nested if",
        ('script Test {\n'
         '    if (flag(FLAG_A)) {\n'
         '        if (flag(FLAG_B)) {\n'
         '            msgbox("Both$", MSGBOX_DEFAULT)\n'
         '        }\n'
         '    }\n}'),
        "Test",
        lambda ts: ts.count("if FLAG_") == 2 and ts.count("endif") == 2
    )

    # ── Stream 2: switch/case blocks ─────────────────────────────

    # Simple switch/case
    _test_snippet(
        "switch: basic 2-case",
        ('script Test {\n'
         '    switch (var(VAR_X)) {\n'
         '        case 0:\n'
         '            goto(Label0)\n'
         '        case 1:\n'
         '            goto(Label1)\n'
         '    }\n}'),
        "Test",
        lambda ts: "switch VAR_X" in ts and "case 0" in ts and "case 1" in ts
            and "goto Label0" in ts and "goto Label1" in ts and "endswitch" in ts
    )

    # Switch with default
    _test_snippet(
        "switch: with default",
        ('script Test {\n'
         '    switch (var(VAR_RESULT)) {\n'
         '        case 0:\n'
         '            goto(Option0)\n'
         '        default:\n'
         '            goto(DefaultLabel)\n'
         '    }\n}'),
        "Test",
        lambda ts: "switch VAR_RESULT" in ts and "default" in ts
            and "goto DefaultLabel" in ts
    )

    # ── Stream 3: Choice reconstruction ──────────────────────────

    # YESNO choice
    _test_snippet(
        "choice: YESNO",
        ('script Test {\n'
         '    msgbox("Do you want to proceed?$", MSGBOX_YESNO)\n'
         '    if (var(VAR_RESULT) == YES) {\n'
         '        msgbox("Great!$", MSGBOX_DEFAULT)\n'
         '    } else {\n'
         '        msgbox("Maybe later$", MSGBOX_DEFAULT)\n'
         '    }\n}'),
        "Test",
        lambda ts: 'choice "Do you want to proceed?"' in ts
            and 'option "Yes"' in ts and 'option "No"' in ts
            and 'msg "Great!"' in ts and 'msg "Maybe later"' in ts
            and "endchoice" in ts
    )

    # ── Stream 4: Known commands with actor resolution ───────────

    # hideobjectat with alias → hide actor MAP
    _test_snippet(
        "known_cmd: hideobjectat with alias",
        'const LOCALID_MOM = 4\n\nscript Test {\n    hideobjectat(LOCALID_MOM, MAP_LITTLEROOT_TOWN)\n}',
        "Test",
        lambda ts: "hide mom MAP_LITTLEROOT_TOWN" in ts and "pory" not in ts
    )

    # showobjectat with alias → show actor MAP
    _test_snippet(
        "known_cmd: showobjectat with alias",
        'const LOCALID_GUARD = 2\n\nscript Test {\n    showobjectat(LOCALID_GUARD, MAP_ROUTE_101)\n}',
        "Test",
        lambda ts: "show guard MAP_ROUTE_101" in ts and "pory" not in ts
    )

    # turnobject with alias
    _test_snippet(
        "known_cmd: turnobject with alias",
        'const LOCALID_NPC = 3\n\nscript Test {\n    turnobject(LOCALID_NPC, DIR_SOUTH)\n}',
        "Test",
        lambda ts: "pory turnobject(npc, DIR_SOUTH)" in ts
    )

    # opendoor → door open
    _test_snippet(
        "known_cmd: opendoor",
        'script Test {\n    opendoor(VAR_0x8009, VAR_0x800A)\n}',
        "Test",
        lambda ts: "door open VAR_0x8009 VAR_0x800A" in ts
    )

    # copyvar → var A = B
    _test_snippet(
        "known_cmd: copyvar",
        'script Test {\n    copyvar(VAR_0x8004, VAR_RESULT)\n}',
        "Test",
        lambda ts: "var VAR_0x8004 = VAR_RESULT" in ts
    )

    # warp
    _test_snippet(
        "known_cmd: warp",
        'script Test {\n    warp(MAP_PETALBURG_CITY, 0, 5, 8)\n}',
        "Test",
        lambda ts: "pory warp(MAP_PETALBURG_CITY, 0, 5, 8)" in ts
    )

    # callnative
    _test_snippet(
        "known_cmd: callnative",
        'script Test {\n    callnative(SomeFunc)\n}',
        "Test",
        lambda ts: "pory callnative(SomeFunc)" in ts
    )

    # setmetatile → tile
    _test_snippet(
        "known_cmd: setmetatile",
        'script Test {\n    setmetatile(5, 10, METATILE_ID, TRUE)\n}',
        "Test",
        lambda ts: "tile 5 10 METATILE_ID TRUE" in ts
    )

    # ── Stream 4: Known bare commands ────────────────────────────

    _test_snippet(
        "bare_cmd: checkplayergender → check gender",
        'script Test {\n    checkplayergender\n}',
        "Test",
        lambda ts: "check gender" in ts and "pory" not in ts
    )

    _test_snippet(
        "bare_cmd: waitdooranim → door wait",
        'script Test {\n    waitdooranim\n}',
        "Test",
        lambda ts: "door wait" in ts and "pory" not in ts
    )

    _test_snippet(
        "bare_cmd: hideplayer",
        'script Test {\n    hideplayer\n}',
        "Test",
        lambda ts: "pory hideplayer" in ts
    )

    # ── Stream 4: Fallthrough with actor resolution ──────────────

    _test_snippet(
        "fallthrough: actor resolution in unknown cmd",
        'const LOCALID_NPC = 5\n\nscript Test {\n    unknowncmd(LOCALID_NPC, 42)\n}',
        "Test",
        lambda ts: "pory unknowncmd(npc, 42)" in ts
            or "pory unknowncmd(npc5, 42)" in ts
    )

    # ── Stream 5: compare+goto_if pattern ────────────────────────

    _test_snippet(
        "compare_goto: compare + goto_if_eq",
        'script Test {\n    compare(VAR_RESULT, FALSE)\n    goto_if_eq(BagFull)\n}',
        "Test",
        lambda ts: "gotoif VAR_RESULT == FALSE BagFull" in ts
    )

    _test_snippet(
        "compare_goto: compare + goto_if_ne",
        'script Test {\n    compare(VAR_RESULT, TRUE)\n    goto_if_ne(Other)\n}',
        "Test",
        lambda ts: "gotoif VAR_RESULT != TRUE Other" in ts
    )

    _test_snippet(
        "compare_goto: compare + goto_if_gt",
        'script Test {\n    compare(VAR_TEMP, 3)\n    goto_if_gt(MoreThan3)\n}',
        "Test",
        lambda ts: "gotoif VAR_TEMP > 3 MoreThan3" in ts
    )

    # ── Stream 6: Trainerbattle text inlining ────────────────────

    _test_snippet(
        "trainerbattle: text inlining",
        ('text TestMap_Text_Intro {\n    "I challenge you!$"\n}\n'
         'text TestMap_Text_Defeat {\n    "You beat me!$"\n}\n'
         'script Test {\n    trainerbattle_single(TRAINER_X, TestMap_Text_Intro, TestMap_Text_Defeat)\n}'),
        "TestMap",
        lambda ts: 'trainerbattle_single TRAINER_X' in ts
            and 'intro "I challenge you!"' in ts
            and 'defeated "You beat me!"' in ts
    )

    _test_snippet(
        "trainerbattle: with postbattle text",
        ('text TestMap_Text_Intro {\n    "Ready?$"\n}\n'
         'text TestMap_Text_Defeat {\n    "Argh!$"\n}\n'
         'script Test {\n'
         '    trainerbattle_single(TRAINER_X, TestMap_Text_Intro, TestMap_Text_Defeat)\n'
         '    msgbox("Good fight!$", MSGBOX_AUTOCLOSE)\n}'),
        "TestMap",
        lambda ts: 'postbattle "Good fight!"' in ts
    )

    _test_snippet(
        "trainerbattle: no text blocks → keep labels",
        'script Test {\n    trainerbattle_single(TRAINER_X, ExtText_Intro, ExtText_Defeat)\n}',
        "Test",
        lambda ts: "trainerbattle_single TRAINER_X, ExtText_Intro, ExtText_Defeat" in ts
    )

    # ── Phase 2: Wait/sync beats ───────────────────────────────

    _test_snippet(
        "wait: waitmessage",
        'script Test {\n    waitmessage\n}',
        "Test",
        lambda ts: "waitmessage" in ts and "pory" not in ts
    )

    _test_snippet(
        "wait: waitbutton",
        'script Test {\n    waitbuttonpress\n}',
        "Test",
        lambda ts: "waitbutton" in ts and "pory" not in ts
    )

    _test_snippet(
        "wait: waitse",
        'script Test {\n    waitse\n}',
        "Test",
        lambda ts: "waitse" in ts and "pory" not in ts
    )

    _test_snippet(
        "wait: waitmoncry",
        'script Test {\n    waitmoncry\n}',
        "Test",
        lambda ts: "waitmoncry" in ts and "pory" not in ts
    )

    # ── Phase 2: specialvar ──────────────────────────────────────

    _test_snippet(
        "specialvar: decompile",
        'script Test {\n    specialvar(VAR_RESULT, ShouldTryRematchBattle)\n}',
        "Test",
        lambda ts: "special ShouldTryRematchBattle VAR_RESULT" in ts
    )

    # ── Phase 2: message ─────────────────────────────────────────

    _test_snippet(
        "message: decompile",
        'script Test {\n    message(gText_Hello)\n}',
        "Test",
        lambda ts: "message gText_Hello" in ts and "pory" not in ts
    )

    # ── Phase 2: var operations ──────────────────────────────────

    _test_snippet(
        "var: copyvar → var A = B",
        'script Test {\n    copyvar(VAR_0x8004, VAR_RESULT)\n}',
        "Test",
        lambda ts: "var VAR_0x8004 = VAR_RESULT" in ts
    )

    _test_snippet(
        "var: addvar → var A + N",
        'script Test {\n    addvar(VAR_SCOTT_STATE, 1)\n}',
        "Test",
        lambda ts: "var VAR_SCOTT_STATE + 1" in ts
    )

    _test_snippet(
        "var: subvar → var A - N",
        'script Test {\n    subvar(VAR_TEMP, 5)\n}',
        "Test",
        lambda ts: "var VAR_TEMP - 5" in ts
    )

    # ── Phase 2: wildbattle ──────────────────────────────────────

    _test_snippet(
        "wildbattle: setup",
        'script Test {\n    setwildbattle(SPECIES_VOLTORB, 25)\n}',
        "Test",
        lambda ts: "wildbattle SPECIES_VOLTORB 25" in ts
    )

    _test_snippet(
        "wildbattle: start",
        'script Test {\n    dowildbattle\n}',
        "Test",
        lambda ts: "wildbattle start" in ts
    )

    # ── Phase 2: take / give standalone ──────────────────────────

    _test_snippet(
        "take: removeitem → take",
        'script Test {\n    removeitem(ITEM_POTION)\n}',
        "Test",
        lambda ts: "take ITEM_POTION" in ts
    )

    _test_snippet(
        "give: standalone giveitem",
        'script Test {\n    giveitem(ITEM_POTION)\n}',
        "Test",
        lambda ts: "give ITEM_POTION" in ts and "pory" not in ts
    )

    # ── Phase 2: random / shop / braille ─────────────────────────

    _test_snippet(
        "random: decompile",
        'script Test {\n    random(5)\n}',
        "Test",
        lambda ts: "random 5" in ts
    )

    _test_snippet(
        "shop: pokemart → shop",
        'script Test {\n    pokemart(Route110_Mart)\n}',
        "Test",
        lambda ts: "shop Route110_Mart" in ts
    )

    _test_snippet(
        "braille: decompile",
        'script Test {\n    braillemsgbox(SealedChamber_Braille)\n}',
        "Test",
        lambda ts: "braille SealedChamber_Braille" in ts
    )

    # ── Phase 2: check extensions ────────────────────────────────

    _test_snippet(
        "check: checkitem → check item",
        'script Test {\n    checkitem(ITEM_COIN_CASE)\n}',
        "Test",
        lambda ts: "check item ITEM_COIN_CASE" in ts
    )

    # ── Phase 2: display commands ────────────────────────────────

    _test_snippet(
        "showmon: decompile",
        'script Test {\n    showmonpic(SPECIES_PIKACHU, 10, 3)\n}',
        "Test",
        lambda ts: "showmon SPECIES_PIKACHU" in ts
    )

    _test_snippet(
        "showmoney: decompile",
        'script Test {\n    showmoneybox(0, 0)\n}',
        "Test",
        lambda ts: "showmoney" in ts and "pory" not in ts
    )

    # ── Phase 2: door commands ───────────────────────────────────

    _test_snippet(
        "door: opendoor → door open",
        'script Test {\n    opendoor(VAR_0x8009, VAR_0x800A)\n}',
        "Test",
        lambda ts: "door open VAR_0x8009 VAR_0x800A" in ts
    )

    _test_snippet(
        "door: closedoor → door close",
        'script Test {\n    closedoor(VAR_0x8009, VAR_0x800A)\n}',
        "Test",
        lambda ts: "door close VAR_0x8009 VAR_0x800A" in ts
    )

    # ── Phase 2: tile / stat / slots ─────────────────────────────

    _test_snippet(
        "tile: setmetatile → tile",
        'script Test {\n    setmetatile(5, 10, METATILE_General_Grass, TRUE)\n}',
        "Test",
        lambda ts: "tile 5 10 METATILE_General_Grass TRUE" in ts
    )

    _test_snippet(
        "stat: incrementgamestat → stat",
        'script Test {\n    incrementgamestat(GAME_STAT_CHECKED_CLOCK)\n}',
        "Test",
        lambda ts: "stat GAME_STAT_CHECKED_CLOCK" in ts
    )

    _test_snippet(
        "slots: playslotmachine → slots",
        'script Test {\n    playslotmachine(VAR_RESULT)\n}',
        "Test",
        lambda ts: "slots VAR_RESULT" in ts
    )

    # ── Phase 2: buffer commands ─────────────────────────────────

    _test_snippet(
        "buffer: bufferspeciesname",
        'script Test {\n    bufferspeciesname(STR_VAR_1, SPECIES_PIKACHU)\n}',
        "Test",
        lambda ts: "buffer 1 species SPECIES_PIKACHU" in ts
    )

    _test_snippet(
        "buffer: bufferleadmonspeciesname",
        'script Test {\n    bufferleadmonspeciesname(STR_VAR_1)\n}',
        "Test",
        lambda ts: "buffer 1 leadmon" in ts
    )

    # ── Phase 2: cry extensions ──────────────────────────────────

    _test_snippet(
        "cry: encounter mode",
        'script Test {\n    playmoncry(SPECIES_VOLTORB, CRY_MODE_ENCOUNTER)\n}',
        "Test",
        lambda ts: "cry SPECIES_VOLTORB encounter" in ts
    )

    # ── Round-trip: conditions ───────────────────────────────────

    try:
        # Compile TorScript with conditions, decompile, recompile
        cond_ts = (
            'script Test\n'
            'lock\n'
            'faceplayer\n'
            'gotoif FLAG_DONE SomeLabel\n'
            'end\n'
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as tmp:
            tmp.write(cond_ts)
            tmp_path = tmp.name
        try:
            pory1, errs1 = compile_script(tmp_path, "Test", emotes_conf)
            _assert("round-trip cond: compile OK", len(errs1) == 0, f"{errs1}")
            ts2, _ = decompile(pory1, "Test")
            _assert("round-trip cond: gotoif preserved", "gotoif FLAG_DONE SomeLabel" in ts2,
                     f"output:\n{ts2}")
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        _fail("round-trip conditions", str(e))


def _test_snippet(name, pory_input, map_name, check_fn):
    """Helper: decompile a .pory snippet and check the output."""
    try:
        from torch.decompiler import decompile
        ts, warnings = decompile(pory_input, map_name)
        _assert(name, check_fn(ts), f"check failed on output:\n{ts}")
    except Exception as e:
        _fail(name, str(e))
