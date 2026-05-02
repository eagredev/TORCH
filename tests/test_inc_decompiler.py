"""Tests for inc_decompiler — .inc assembly to .pory Poryscript."""
from torch.tests.harness import _begin_suite, _assert, _fail, _ok, _skip


def _decompile(inc_text, map_name="TestMap"):
    from torch.inc_decompiler import decompile_inc
    return decompile_inc(inc_text, map_name)


# ============================================================
# STRUCTURE PARSING
# ============================================================

def test_empty_file():
    pory, w = _decompile("")
    _assert("empty file", pory == "", f"expected empty, got: {pory!r}")

def test_simple_npc_msgbox():
    inc = '''
Town_NPC::
\tmsgbox Town_NPC_Text, MSGBOX_NPC
\tend

Town_NPC_Text:
\t.string "Hello there!$"
'''
    pory, _ = _decompile(inc, "Town")
    _assert("npc msgbox script block", "script Town_NPC {" in pory, pory)
    _assert("npc msgbox inlined", 'msgbox("Hello there!$", MSGBOX_NPC)' in pory, pory)
    _assert("npc msgbox end", "end" in pory, pory)

def test_sign_script():
    inc = '''
Route1_Sign::
\tmsgbox Route1_Sign_Text, MSGBOX_SIGN
\tend

Route1_Sign_Text:
\t.string "ROUTE 1\\n{UP_ARROW} TOWN$"
'''
    pory, _ = _decompile(inc, "Route1")
    _assert("sign inlined", 'MSGBOX_SIGN' in pory, pory)
    _assert("sign text", '{UP_ARROW}' in pory, pory)

def test_multiline_text():
    inc = '''
NPC::
\tmsgbox NPC_Text, MSGBOX_DEFAULT
\tend

NPC_Text:
\t.string "Line one.\\n"
\t.string "Line two.\\p"
\t.string "Line three.$"
'''
    pory, _ = _decompile(inc)
    _assert("multiline text joined", "Line one.\\nLine two.\\pLine three.$" in pory, pory)

def test_shared_text_multi_ref():
    inc = '''
NPC1::
\tmsgbox Shared_Text, MSGBOX_DEFAULT
\tend

NPC2::
\tmsgbox Shared_Text, MSGBOX_DEFAULT
\tend

Shared_Text:
\t.string "Shared!$"
'''
    pory, _ = _decompile(inc)
    _assert("shared text not inlined", "msgbox(Shared_Text, MSGBOX_DEFAULT)" in pory, pory)
    _assert("shared text block emitted", 'text Shared_Text {' in pory, pory)


# ============================================================
# MOVEMENT BLOCKS
# ============================================================

def test_movement_block():
    inc = '''
Move1:
\twalk_up
\twalk_up
\twalk_right
\tstep_end
'''
    pory, _ = _decompile(inc)
    _assert("movement block", "movement Move1 {" in pory, pory)
    _assert("movement compressed", "walk_up * 2" in pory, pory)
    _assert("movement single", "    walk_right" in pory, pory)
    _assert("no step_end", "step_end" not in pory, pory)

def test_single_movement():
    inc = '''
Move1:
\twalk_down
\tstep_end
'''
    pory, _ = _decompile(inc)
    _assert("single movement", "walk_down" in pory, pory)
    _assert("single no repeat", "* " not in pory, pory)


# ============================================================
# MAPSCRIPTS
# ============================================================

def test_mapscripts_empty():
    inc = '''
TestMap_MapScripts::
\t.byte 0
'''
    pory, _ = _decompile(inc)
    _assert("empty mapscripts", "mapscripts TestMap_MapScripts {" in pory, pory)
    _assert("empty mapscripts close", "}" in pory, pory)

def test_mapscripts_with_handlers():
    inc = '''
Town_MapScripts::
\tmap_script MAP_SCRIPT_ON_TRANSITION, Town_OnTransition
\tmap_script MAP_SCRIPT_ON_LOAD, Town_OnLoad
\t.byte 0

Town_OnTransition:
\tsetflag FLAG_VISITED
\tend
'''
    pory, _ = _decompile(inc)
    _assert("mapscripts transition", "MAP_SCRIPT_ON_TRANSITION: Town_OnTransition" in pory, pory)
    _assert("mapscripts load", "MAP_SCRIPT_ON_LOAD: Town_OnLoad" in pory, pory)

def test_mapscript_table():
    inc = '''
Town_OnFrame:
\tmap_script_2 VAR_STATE, 1, Town_EventScript_Scene1
\tmap_script_2 VAR_STATE, 2, Town_EventScript_Scene2
\t.2byte 0
'''
    pory, _ = _decompile(inc)
    _assert("mapscript table raw", "raw `" in pory, pory)
    _assert("mapscript table content", "map_script_2 VAR_STATE, 1, Town_EventScript_Scene1" in pory, pory)


# ============================================================
# SIMPLE COMMANDS
# ============================================================

def test_no_arg_commands():
    inc = '''
Test::
\tlock
\tfaceplayer
\tclosemessage
\twaitstate
\trelease
\tend
'''
    pory, _ = _decompile(inc)
    _assert("lock", "    lock" in pory, pory)
    _assert("faceplayer", "    faceplayer" in pory, pory)
    _assert("closemessage", "    closemessage" in pory, pory)
    _assert("waitstate", "    waitstate" in pory, pory)
    _assert("release", "    release" in pory, pory)
    _assert("end", "    end" in pory, pory)

def test_arg_commands():
    inc = '''
Test::
\tsetflag FLAG_X
\tclearflag FLAG_Y
\tsetvar VAR_A, 5
\tcopyvar VAR_B, VAR_C
\tspecial MyFunc
\tspecialvar VAR_RESULT, GetStuff
\tdelay 16
\tplayse SE_BUMP
\tremoveobject 5
\taddobject 3
\tend
'''
    pory, _ = _decompile(inc)
    _assert("setflag", "setflag(FLAG_X)" in pory, pory)
    _assert("clearflag", "clearflag(FLAG_Y)" in pory, pory)
    _assert("setvar", "setvar(VAR_A, 5)" in pory, pory)
    _assert("copyvar", "copyvar(VAR_B, VAR_C)" in pory, pory)
    _assert("special", "special(MyFunc)" in pory, pory)
    _assert("specialvar", "specialvar(VAR_RESULT, GetStuff)" in pory, pory)
    _assert("delay", "delay(16)" in pory, pory)
    _assert("playse", "playse(SE_BUMP)" in pory, pory)
    _assert("removeobject", "removeobject(5)" in pory, pory)
    _assert("addobject", "addobject(3)" in pory, pory)

def test_warp_commands():
    inc = '''
Test::
\twarp MAP_TOWN, 5, 3
\twarpsilent MAP_HOUSE, 2, 8
\tend
'''
    pory, _ = _decompile(inc)
    _assert("warp", "warp(MAP_TOWN, 5, 3)" in pory, pory)
    _assert("warpsilent", "warpsilent(MAP_HOUSE, 2, 8)" in pory, pory)

def test_door_commands():
    inc = '''
Test::
\topendoor 5, 8
\twaitdooranim
\tclosedoor 5, 8
\twaitdooranim
\tend
'''
    pory, _ = _decompile(inc)
    _assert("opendoor", "opendoor(5, 8)" in pory, pory)
    _assert("closedoor", "closedoor(5, 8)" in pory, pory)
    _assert("waitdooranim", "    waitdooranim" in pory, pory)

def test_setmetatile():
    inc = '''
Test::
\tsetmetatile 9, 6, METATILE_Door_Closed, TRUE
\treturn
'''
    pory, _ = _decompile(inc)
    _assert("setmetatile", "setmetatile(9, 6, METATILE_Door_Closed, TRUE)" in pory, pory)

def test_trainerbattle():
    inc = '''
Test::
\ttrainerbattle_single TRAINER_MISTY, Text_Intro, Text_Defeat
\tend
'''
    pory, _ = _decompile(inc)
    _assert("trainerbattle", "trainerbattle_single(TRAINER_MISTY, Text_Intro, Text_Defeat)" in pory, pory)


# ============================================================
# CONTROL FLOW
# ============================================================

def test_goto_if_set():
    inc = '''
Test::
\tgoto_if_set FLAG_MET, Test_Met
\tmsgbox Test_Text, MSGBOX_DEFAULT
\tend

Test_Met::
\tend

Test_Text:
\t.string "Hi$"
'''
    pory, _ = _decompile(inc)
    _assert("goto_if_set", "if (flag(FLAG_MET))" in pory, pory)
    _assert("goto_if_set target", "goto(Test_Met)" in pory, pory)

def test_goto_if_unset():
    inc = '''
Test::
\tgoto_if_unset FLAG_X, Test_Else
\tend
'''
    pory, _ = _decompile(inc)
    _assert("goto_if_unset", "if (!flag(FLAG_X))" in pory, pory)

def test_goto_if_eq():
    inc = '''
Test::
\tgoto_if_eq VAR_STATE, 5, Test_Five
\tend
'''
    pory, _ = _decompile(inc)
    _assert("goto_if_eq", "if (var(VAR_STATE) == 5)" in pory, pory)

def test_goto_if_ne():
    inc = '''
Test::
\tgoto_if_ne VAR_RESULT, FALSE, Test_NotFalse
\tend
'''
    pory, _ = _decompile(inc)
    _assert("goto_if_ne", "if (var(VAR_RESULT) != FALSE)" in pory, pory)

def test_goto_if_comparisons():
    inc = '''
Test::
\tgoto_if_lt VAR_X, 3, Test_A
\tgoto_if_le VAR_X, 5, Test_B
\tgoto_if_gt VAR_X, 7, Test_C
\tgoto_if_ge VAR_X, 9, Test_D
\tend
'''
    pory, _ = _decompile(inc)
    _assert("lt", "var(VAR_X) < 3" in pory, pory)
    _assert("le", "var(VAR_X) <= 5" in pory, pory)
    _assert("gt", "var(VAR_X) > 7" in pory, pory)
    _assert("ge", "var(VAR_X) >= 9" in pory, pory)

def test_call_if_eq():
    inc = '''
Test::
\tcall_if_eq VAR_RESULT, MALE, Test_Male
\tcall_if_eq VAR_RESULT, FEMALE, Test_Female
\tend
'''
    pory, _ = _decompile(inc)
    _assert("call_if_eq male", "if (var(VAR_RESULT) == MALE)" in pory, pory)
    _assert("call_if_eq male call", "call(Test_Male)" in pory, pory)
    _assert("call_if_eq female", "if (var(VAR_RESULT) == FEMALE)" in pory, pory)

def test_call_if_set_unset():
    inc = '''
Test::
\tcall_if_set FLAG_A, Test_A
\tcall_if_unset FLAG_B, Test_B
\tend
'''
    pory, _ = _decompile(inc)
    _assert("call_if_set", "if (flag(FLAG_A))" in pory, pory)
    _assert("call_if_unset", "if (!flag(FLAG_B))" in pory, pory)

def test_goto_if_defeated():
    inc = '''
Test::
\tgoto_if_defeated TRAINER_X, Test_Won
\tgoto_if_not_defeated TRAINER_Y, Test_NotWon
\tend
'''
    pory, _ = _decompile(inc)
    _assert("defeated", "if (defeated(TRAINER_X))" in pory, pory)
    _assert("not_defeated", "if (!defeated(TRAINER_Y))" in pory, pory)

def test_switch_case():
    inc = '''
Test::
\tswitch VAR_RESULT
\tcase 0, Test_Zero
\tcase 1, Test_One
\tcase MULTI_B_PRESSED, Test_Cancel
\tend
'''
    pory, _ = _decompile(inc)
    _assert("switch", "switch (var(VAR_RESULT)) {" in pory, pory)
    _assert("case 0", "case 0:" in pory, pory)
    _assert("case 0 goto", "goto(Test_Zero)" in pory, pory)
    _assert("case 1", "case 1:" in pory, pory)
    _assert("case cancel", "case MULTI_B_PRESSED:" in pory, pory)
    _assert("switch close", "    }" in pory, pory)


# ============================================================
# DATA BLOCKS
# ============================================================

def test_mart_data():
    inc = '''
\t.align 2
Shop_Items:
\t.2byte ITEM_POKE_BALL
\t.2byte ITEM_POTION
\t.2byte ITEM_ANTIDOTE
\t.2byte ITEM_NONE
\trelease
\tend
'''
    pory, _ = _decompile(inc)
    _assert("mart block", "mart Shop_Items {" in pory, pory)
    _assert("mart items", "ITEM_POKE_BALL" in pory, pory)
    _assert("mart no ITEM_NONE", "ITEM_NONE" not in pory, pory)

def test_comments():
    inc = '''
Test::
\t@ This is a comment
\tlock
\tend
'''
    pory, _ = _decompile(inc)
    _assert("comment converted", "// This is a comment" in pory, pory)


# ============================================================
# REAL-WORLD FILES
# ============================================================

def test_bulk_decompile_all_vanilla():
    """Smoke test: all 468 vanilla scripts.inc files decompile without error."""
    import os, glob
    from torch.inc_decompiler import decompile_inc_file

    corpus = os.path.expanduser('~/Documents/torch-dev/data/maps')
    if not os.path.isdir(corpus):
        _skip("bulk vanilla", "torch-dev corpus not found")
        return

    files = glob.glob(os.path.join(corpus, '*/scripts.inc'))
    if not files:
        _skip("bulk vanilla", "no scripts.inc files found")
        return

    errors = []
    for f in files:
        map_name = os.path.basename(os.path.dirname(f))
        try:
            pory, warnings = decompile_inc_file(f, map_name)
            if pory is None:
                errors.append(f"{map_name}: returned None")
        except Exception as e:
            errors.append(f"{map_name}: {e}")

    _assert("bulk decompile all vanilla", len(errors) == 0,
            f"{len(errors)} failures:\n" + "\n".join(errors[:10]))
    _ok(f"bulk decompile: {len(files)} files OK")

def test_route101_structure():
    """Route101: mapscripts, movements, text inlining, control flow."""
    import os
    from torch.inc_decompiler import decompile_inc_file

    f = os.path.expanduser('~/Documents/torch-dev/data/maps/Route101/scripts.inc')
    if not os.path.isfile(f):
        _skip("route101 structure", "file not found")
        return

    pory, _ = decompile_inc_file(f, "Route101")
    _assert("r101 mapscripts", "mapscripts Route101_MapScripts {" in pory, pory[:200])
    _assert("r101 on_transition", "MAP_SCRIPT_ON_TRANSITION: Route101_OnTransition" in pory, pory[:300])
    _assert("r101 birch script", "Route101_EventScript_StartBirchRescue" in pory, pory[:1000])
    _assert("r101 movement compressed", "walk_fast_right * 4" in pory, pory)
    _assert("r101 text inlined", 'msgbox("H-help me!$"' in pory, pory[:2000])
    _assert("r101 call_if_eq", "call(Route101_EventScript_HideMayInBedroom)" in pory, pory)

def test_sootopolis_control_flow():
    """SootopolisCity: heavy control flow (58 goto_if commands)."""
    import os
    from torch.inc_decompiler import decompile_inc_file

    f = os.path.expanduser('~/Documents/torch-dev/data/maps/SootopolisCity/scripts.inc')
    if not os.path.isfile(f):
        _skip("sootopolis control flow", "file not found")
        return

    pory, _ = decompile_inc_file(f, "SootopolisCity")
    _assert("soot mapscripts", "mapscripts SootopolisCity_MapScripts {" in pory, pory[:200])
    _assert("soot 5 handlers", pory.count("MAP_SCRIPT_ON_") == 5, f"expected 5 MAP_SCRIPT_ON_, got {pory.count('MAP_SCRIPT_ON_')}")
    _assert("soot goto_if_set", "if (flag(FLAG_" in pory, pory)
    _assert("soot goto_if_eq", "if (var(VAR_SOOTOPOLIS_CITY_STATE) == " in pory, pory)
    _assert("soot goto_if_ge", ">=" in pory, pory)
    _assert("soot setmetatile", "setmetatile(" in pory, pory)

def test_decompile_block_single():
    """decompile_inc_block extracts a single script."""
    from torch.inc_decompiler import decompile_inc_block
    inc = '''
NPC1::
\tlock
\tmsgbox NPC1_Text, MSGBOX_NPC
\trelease
\tend

NPC2::
\tlock
\tend

NPC1_Text:
\t.string "Hello$"
'''
    pory, _ = decompile_inc_block(inc, "NPC1", "TestMap")
    _assert("block has NPC1", "NPC1" in pory, pory)
    _assert("block no NPC2", "NPC2" not in pory or "NPC2" in pory.split("NPC1")[0] is False, pory)
    _assert("block text inlined", 'msgbox("Hello$"' in pory, pory)

def test_decompile_block_not_found():
    """decompile_inc_block returns None for missing label."""
    from torch.inc_decompiler import decompile_inc_block
    pory, warnings = decompile_inc_block("Test::\n\tend\n", "Missing", "TestMap")
    _assert("block not found", pory is None, f"expected None, got: {pory!r}")
    _assert("block warning", any("not found" in w for w in warnings), str(warnings))


# ============================================================
# REGISTRATION
# ============================================================

def run_suite():
    _begin_suite("Inc Decompiler")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t()
        except Exception as e:
            _fail(t.__name__, str(e))
