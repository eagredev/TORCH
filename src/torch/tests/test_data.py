"""Tests for data.py — movement constants and command translation."""
from torch.tests.harness import _begin_suite, _assert


def run_suite():
    _begin_suite("Data Constants (movements, emotes)")

    from torch.data import (
        BUILTIN_EMOTES,
        COMMON_EMOTES,
        COMMON_FACE,
        WALK_COMMANDS,
        DIRECTIONS,
        MOVEMENT_COMMAND_CATEGORIES,
        ALL_MOVEMENT_COMMANDS,
        _MOVEMENT_ENGLISH,
        _movement_cmd_english,
    )

    # ── A. Constant integrity ──────────────────────────────────────

    _assert("BUILTIN_EMOTES is non-empty",
            len(BUILTIN_EMOTES) > 0,
            f"got {len(BUILTIN_EMOTES)} entries")

    _assert("COMMON_EMOTES is subset of BUILTIN_EMOTES keys",
            set(COMMON_EMOTES.keys()).issubset(set(BUILTIN_EMOTES.keys())),
            f"extra keys: {set(COMMON_EMOTES.keys()) - set(BUILTIN_EMOTES.keys())}")

    _assert("COMMON_FACE has 4 directions + player + away",
            len(COMMON_FACE) >= 6,
            f"got {len(COMMON_FACE)} entries")

    _assert("DIRECTIONS has 4 entries",
            DIRECTIONS == ["up", "down", "left", "right"],
            f"got {DIRECTIONS}")

    _assert("ALL_MOVEMENT_COMMANDS matches category totals",
            len(ALL_MOVEMENT_COMMANDS) == sum(
                len(cmds) for _, cmds in MOVEMENT_COMMAND_CATEGORIES),
            f"set has {len(ALL_MOVEMENT_COMMANDS)}, categories total "
            f"{sum(len(c) for _, c in MOVEMENT_COMMAND_CATEGORIES)}")

    # Every command in ALL_MOVEMENT_COMMANDS has an English translation
    missing = ALL_MOVEMENT_COMMANDS - set(_MOVEMENT_ENGLISH.keys())
    _assert("all movement commands have English translations",
            len(missing) == 0,
            f"missing translations: {missing}")

    # No duplicate commands across categories
    seen = set()
    dupes = set()
    for _, cmds in MOVEMENT_COMMAND_CATEGORIES:
        for cmd in cmds:
            if cmd in seen:
                dupes.add(cmd)
            seen.add(cmd)
    _assert("no duplicate commands across categories",
            len(dupes) == 0,
            f"duplicates: {dupes}")

    # ── B. _movement_cmd_english ───────────────────────────────────

    _assert("known command returns English",
            _movement_cmd_english("face_down") == "Face down",
            f"got {_movement_cmd_english('face_down')!r}")

    _assert("emote command returns English",
            _movement_cmd_english("emote_exclamation_mark") == "Emote: !",
            f"got {_movement_cmd_english('emote_exclamation_mark')!r}")

    _assert("repeat syntax returns multiplied form",
            _movement_cmd_english("walk_down * 3") == "Walk down x3",
            f"got {_movement_cmd_english('walk_down * 3')!r}")

    _assert("unknown command returns title-cased fallback",
            _movement_cmd_english("some_custom_move") == "Some Custom Move",
            f"got {_movement_cmd_english('some_custom_move')!r}")
