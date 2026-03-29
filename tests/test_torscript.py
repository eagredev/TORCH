"""TorScript parser suite -- tests _parse_torscript_beat (pure string->dict)."""

from torch.tests.harness import _begin_suite, _ok, _fail, _assert


def run_suite():
    _begin_suite("TorScript Parser")

    try:
        from torch.script_editor import _parse_torscript_beat
    except ImportError as e:
        from torch.tests.harness import _skip
        _skip("all TorScript tests", f"import failed: {e}")
        return

    # Minimal script_data with cast for actor recognition
    script_data = {"cast": {"guard": "1", "npc1": "2"}}

    # ── Dialogue ──────────────────────────────────────────────
    r = _parse_torscript_beat('msg "Hello world"', script_data)
    _assert("msg quoted: type=dialogue",
            r and r["type"] == "dialogue", f"got {r}")
    _assert("msg quoted: text + style",
            r and r["data"]["text"] == "Hello world" and r["data"]["style"] == "msg",
            f"got {r}")

    r = _parse_torscript_beat('msgnpc "Greetings"', script_data)
    _assert("msgnpc quoted: type=dialogue, style=msgnpc",
            r and r["type"] == "dialogue" and r["data"]["style"] == "msgnpc",
            f"got {r}")

    # ── Fade ──────────────────────────────────────────────────
    r = _parse_torscript_beat("fade to_black", script_data)
    _assert("fade to_black",
            r == {"type": "fade", "data": {"fade_type": "to_black"}},
            f"got {r}")

    # ── Sound / Music / Fanfare / Cry ─────────────────────────
    r = _parse_torscript_beat("sound SE_SELECT", script_data)
    _assert("sound SE_SELECT",
            r and r["type"] == "sound" and r["data"]["constant"] == "SE_SELECT",
            f"got {r}")

    r = _parse_torscript_beat("music MUS_INTRO", script_data)
    _assert("music MUS_INTRO",
            r and r["type"] == "music" and r["data"]["constant"] == "MUS_INTRO",
            f"got {r}")

    r = _parse_torscript_beat("fanfare MUS_FANFARE", script_data)
    _assert("fanfare MUS_FANFARE",
            r and r["type"] == "fanfare" and r["data"]["constant"] == "MUS_FANFARE",
            f"got {r}")

    r = _parse_torscript_beat("cry SPECIES_PIKACHU", script_data)
    _assert("cry SPECIES_PIKACHU",
            r and r["type"] == "cry" and r["data"]["species"] == "SPECIES_PIKACHU",
            f"got {r}")

    # ── Shake / Pause ─────────────────────────────────────────
    r = _parse_torscript_beat("shake 3", script_data)
    _assert("shake 3: default count=2",
            r and r["type"] == "shake" and r["data"]["intensity"] == "3"
            and r["data"]["count"] == "2",
            f"got {r}")

    r = _parse_torscript_beat("pause 30", script_data)
    _assert("pause 30",
            r and r["type"] == "pause" and r["data"]["duration"] == "30",
            f"got {r}")

    # ── Flag ──────────────────────────────────────────────────
    r = _parse_torscript_beat("flag set FLAG_TEST", script_data)
    _assert("flag set FLAG_TEST",
            r and r["type"] == "flag"
            and r["data"]["action"] == "set" and r["data"]["flag_name"] == "FLAG_TEST",
            f"got {r}")

    # ── Hide / Show ───────────────────────────────────────────
    r = _parse_torscript_beat("hide guard", script_data)
    _assert("hide guard",
            r == {"type": "hide", "data": {"actor": "guard"}},
            f"got {r}")

    r = _parse_torscript_beat("show npc1", script_data)
    _assert("show npc1",
            r == {"type": "show", "data": {"actor": "npc1"}},
            f"got {r}")

    # ── Setpos ────────────────────────────────────────────────
    r = _parse_torscript_beat("setpos guard 5 10", script_data)
    _assert("setpos guard 5 10",
            r and r["type"] == "setpos"
            and r["data"]["actor"] == "guard"
            and r["data"]["x"] == "5" and r["data"]["y"] == "10",
            f"got {r}")

    # ── Flow control ──────────────────────────────────────────
    r = _parse_torscript_beat("goto TargetLabel", script_data)
    _assert("goto TargetLabel",
            r and r["type"] == "flow"
            and r["data"]["flow_type"] == "goto" and r["data"]["target"] == "TargetLabel",
            f"got {r}")

    r = _parse_torscript_beat("call SubRoutine", script_data)
    _assert("call SubRoutine",
            r and r["type"] == "flow"
            and r["data"]["flow_type"] == "call" and r["data"]["target"] == "SubRoutine",
            f"got {r}")

    r = _parse_torscript_beat("end", script_data)
    _assert("end",
            r and r["type"] == "flow" and r["data"]["flow_type"] == "end",
            f"got {r}")

    r = _parse_torscript_beat("release", script_data)
    _assert("release",
            r and r["type"] == "flow" and r["data"]["flow_type"] == "release",
            f"got {r}")

    # ── Simple commands ───────────────────────────────────────
    r = _parse_torscript_beat("lock", script_data)
    _assert("lock",
            r and r["type"] == "lock",
            f"got {r}")

    r = _parse_torscript_beat("faceplayer", script_data)
    _assert("faceplayer",
            r and r["type"] == "faceplayer",
            f"got {r}")

    r = _parse_torscript_beat("closemessage", script_data)
    _assert("closemessage",
            r and r["type"] == "closemessage",
            f"got {r}")

    # ── Gotoif ────────────────────────────────────────────────
    r = _parse_torscript_beat("gotoif FLAG_TEST TargetLabel", script_data)
    _assert("gotoif FLAG_TEST TargetLabel",
            r and r["type"] == "gotoif"
            and r["data"]["flag"] == "FLAG_TEST"
            and r["data"]["target"] == "TargetLabel",
            f"got {r}")

    # ── Pory passthrough ──────────────────────────────────────
    r = _parse_torscript_beat("pory raw_poryscript_here", script_data)
    _assert("pory passthrough",
            r and r["type"] == "pory"
            and "raw_poryscript_here" in r["data"]["raw_line"],
            f"got {r}")

    # ── Comment ───────────────────────────────────────────────
    r = _parse_torscript_beat("# this is a comment", script_data)
    _assert("comment",
            r and r["type"] == "comment"
            and "this is a comment" in r["data"]["text"],
            f"got {r}")

    # ── Actor movement ────────────────────────────────────────
    r = _parse_torscript_beat("guard walk up 3", script_data)
    _assert("guard walk up 3: type=move",
            r and r["type"] == "move",
            f"got {r}")
    _assert("guard walk up 3: action details",
            r and r["data"]["actions"][0] == {
                "actor": "guard", "verb": "walk", "direction": "up", "count": "3"
            },
            f"got {r}")

    r = _parse_torscript_beat("npc1 face left", script_data)
    _assert("npc1 face left: type=move",
            r and r["type"] == "move",
            f"got {r}")
    _assert("npc1 face left: action details",
            r and r["data"]["actions"][0] == {
                "actor": "npc1", "verb": "face", "direction": "left"
            },
            f"got {r}")

    # Parallel movement
    r = _parse_torscript_beat("guard walk up 2 + npc1 walk down 1", script_data)
    _assert("parallel move: type=move",
            r and r["type"] == "move",
            f"got {r}")
    _assert("parallel move: 2 actions",
            r and len(r["data"]["actions"]) == 2,
            f"got {r}")

    # Emote (single actor = emote beat, not move)
    r = _parse_torscript_beat("guard emote exclaim", script_data)
    _assert("guard emote exclaim: type=emote",
            r and r["type"] == "emote"
            and r["data"]["actor"] == "guard"
            and r["data"]["emote_name"] == "exclaim",
            f"got {r}")

    # ── Edge cases ────────────────────────────────────────────
    r = _parse_torscript_beat("", script_data)
    _assert("empty string returns None",
            r is None,
            f"got {r}")

    r = _parse_torscript_beat("   ", script_data)
    _assert("whitespace-only returns None",
            r is None,
            f"got {r}")

    r = _parse_torscript_beat("unknowncommand xyz", script_data)
    _assert("unknown command returns None",
            r is None,
            f"got {r}")

    # msg without quotes (quick entry)
    r = _parse_torscript_beat("msg Hello there", script_data)
    _assert("msg unquoted: text=Hello there",
            r and r["type"] == "dialogue"
            and r["data"]["text"] == "Hello there"
            and r["data"]["style"] == "msg",
            f"got {r}")

    # return is treated as flow
    r = _parse_torscript_beat("return", script_data)
    _assert("return: flow_type=return",
            r and r["type"] == "flow" and r["data"]["flow_type"] == "return",
            f"got {r}")
