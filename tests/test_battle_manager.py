"""Battle Manager — battle types, list helpers, wizard validators, mon helpers."""
import io
import os
import sys
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Battle Manager")

    try:
        from torch.battle_manager import (
            BATTLE_TYPES, _available_battle_types, _list_handle_numeric,
            _list_render,
        )
        from torch.battle_wizard import (
            _to_pascal_case, _parse_defines, _normalise_constant_input,
            _wrap_dialogue, _emit_mon_block_lines,
        )
        from torch.names import (
            _ai_flags_to_party_format, _party_gender_to_const,
            _party_ai_to_const,
        )
        from torch.battle_io import _serialize_party_mon
        from torch.expansion_compat import BATTLE_TYPE_TWO_TRAINERS_NO_INTRO
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # ==================================================================
    # BATTLE TYPES (~5 tests)
    # ==================================================================

    # 1. BATTLE_TYPES is a list of 4-tuples
    try:
        _assert("BATTLE_TYPES is a list", isinstance(BATTLE_TYPES, list),
                f"type is {type(BATTLE_TYPES).__name__}")
    except Exception as e:
        _fail("BATTLE_TYPES is a list", str(e))

    try:
        all_4_tuples = all(
            isinstance(bt, tuple) and len(bt) == 4
            for bt in BATTLE_TYPES
        )
        _assert("BATTLE_TYPES elements are 4-tuples", all_4_tuples,
                f"some elements are not 4-tuples")
    except Exception as e:
        _fail("BATTLE_TYPES elements are 4-tuples", str(e))

    # 2. Each element: (name:str, macro:str, min_ver:tuple|None, desc:str)
    try:
        valid_shape = True
        for bt in BATTLE_TYPES:
            name, macro, min_ver, desc = bt
            if not isinstance(name, str) or not isinstance(macro, str) or not isinstance(desc, str):
                valid_shape = False
                break
            if min_ver is not None and not isinstance(min_ver, tuple):
                valid_shape = False
                break
        _assert("BATTLE_TYPES element shapes are correct", valid_shape,
                "name/macro/desc must be str, min_ver must be tuple or None")
    except Exception as e:
        _fail("BATTLE_TYPES element shapes are correct", str(e))

    # 3. _available_battle_types(None) returns all types
    try:
        result = _available_battle_types(None)
        _assert("_available_battle_types(None) returns all",
                len(result) == len(BATTLE_TYPES),
                f"expected {len(BATTLE_TYPES)}, got {len(result)}")
    except Exception as e:
        _fail("_available_battle_types(None) returns all", str(e))

    # 4. _available_battle_types((1,6,0)) filters out types with min_version > (1,6,0)
    try:
        result = _available_battle_types((1, 6, 0))
        # two_trainers requires (1,11,0) so should be excluded
        names = [bt[0] for bt in result]
        _assert("_available_battle_types((1,6,0)) excludes two_trainers",
                "two_trainers" not in names,
                f"two_trainers should be filtered out, got names: {names}")
    except Exception as e:
        _fail("_available_battle_types((1,6,0)) excludes two_trainers", str(e))

    # 5. _available_battle_types((99,0,0)) returns all types
    try:
        result = _available_battle_types((99, 0, 0))
        _assert("_available_battle_types((99,0,0)) returns all",
                len(result) == len(BATTLE_TYPES),
                f"expected {len(BATTLE_TYPES)}, got {len(result)}")
    except Exception as e:
        _fail("_available_battle_types((99,0,0)) returns all", str(e))

    # ==================================================================
    # LIST HELPERS (~8 tests)
    # ==================================================================

    # Build mock visible list for _list_handle_numeric
    mock_visible = [
        {"trainer_id": 900, "trainer_class": "TRAINER_CLASS_HIKER", "trainer_name": "Ted",
         "is_custom": True, "is_vanilla": False, "map_folder": "MyMap", "pory_path": None},
        {"trainer_id": 901, "trainer_class": "TRAINER_CLASS_LASS", "trainer_name": "Amy",
         "is_custom": True, "is_vanilla": False, "map_folder": "MyMap", "pory_path": None},
        {"trainer_id": 902, "trainer_class": "TRAINER_CLASS_YOUNGSTER", "trainer_name": "Bob",
         "is_custom": True, "is_vanilla": False, "map_folder": "MyMap", "pory_path": None},
    ]
    total = len(mock_visible)

    # 6. Valid row number "2" -> returns 1 (0-indexed)
    try:
        result = _list_handle_numeric("2", mock_visible, 0, total)
        _assert("_list_handle_numeric: valid row '2' -> 1",
                result == 1, f"expected 1, got {result}")
    except Exception as e:
        _fail("_list_handle_numeric: valid row '2' -> 1", str(e))

    # 7. Out of range "10" -> returns original selected_idx
    try:
        # Out of range low number triggers the print+input path, mock stdin
        old_stdin = sys.stdin
        sys.stdin = io.StringIO("\n")
        result = _list_handle_numeric("10", mock_visible, 1, total)
        sys.stdin = old_stdin
        _assert("_list_handle_numeric: out of range '10' -> original idx",
                result == 1, f"expected 1, got {result}")
    except Exception as e:
        sys.stdin = sys.__stdin__
        _fail("_list_handle_numeric: out of range '10' -> original idx", str(e))

    # 8. Large number (>=100) matching trainer_id -> returns matching index
    try:
        result = _list_handle_numeric("901", mock_visible, 0, total)
        _assert("_list_handle_numeric: large number matching trainer_id 901 -> idx 1",
                result == 1, f"expected 1, got {result}")
    except Exception as e:
        _fail("_list_handle_numeric: large number matching trainer_id 901 -> idx 1", str(e))

    # 9. Large number not matching any trainer_id -> falls back to row or original
    try:
        old_stdin = sys.stdin
        sys.stdin = io.StringIO("\n")
        result = _list_handle_numeric("999", mock_visible, 0, total)
        sys.stdin = old_stdin
        # 999 doesn't match any trainer_id, and row 999 is out of range -> original
        _assert("_list_handle_numeric: large number 999 not matching -> original",
                result == 0, f"expected 0, got {result}")
    except Exception as e:
        sys.stdin = sys.__stdin__
        _fail("_list_handle_numeric: large number 999 not matching -> original", str(e))

    # 10. Non-numeric string -> returns original
    try:
        result = _list_handle_numeric("abc", mock_visible, 0, total)
        _assert("_list_handle_numeric: non-numeric 'abc' -> original idx",
                result == 0, f"expected 0, got {result}")
    except Exception as e:
        _fail("_list_handle_numeric: non-numeric 'abc' -> original idx", str(e))

    # 11. Row number "1" -> returns 0
    try:
        result = _list_handle_numeric("1", mock_visible, 2, total)
        _assert("_list_handle_numeric: '1' -> 0", result == 0,
                f"expected 0, got {result}")
    except Exception as e:
        _fail("_list_handle_numeric: '1' -> 0", str(e))

    # 12-13. _list_render: capture stdout, verify TRAINER LIST header and column headers
    try:
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        _list_render(mock_visible, total, 0, 0, 20,
                     True, "", "Enter", "u", "j")
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        _assert("_list_render: output contains 'TRAINER LIST'",
                "TRAINER LIST" in output,
                "TRAINER LIST not found in output")
        _assert("_list_render: output contains column headers",
                "Class" in output and "Name" in output and "Location" in output,
                f"column headers not found")
    except Exception as e:
        sys.stdout = sys.__stdout__
        _fail("_list_render", str(e))

    # ==================================================================
    # WIZARD VALIDATORS (~12 tests)
    # ==================================================================

    # 14. _to_pascal_case: snake_case
    try:
        result = _to_pascal_case("my_map_name")
        _assert("_to_pascal_case: 'my_map_name' -> 'MyMapName'",
                result == "MyMapName", f"got {result!r}")
    except Exception as e:
        _fail("_to_pascal_case: snake_case", str(e))

    # 15. _to_pascal_case: space-separated
    try:
        result = _to_pascal_case("lake elix south")
        _assert("_to_pascal_case: 'lake elix south' -> 'LakeElixSouth'",
                result == "LakeElixSouth", f"got {result!r}")
    except Exception as e:
        _fail("_to_pascal_case: space-separated", str(e))

    # 16. _to_pascal_case: hyphenated
    try:
        result = _to_pascal_case("my-cool-map")
        _assert("_to_pascal_case: 'my-cool-map' -> 'MyCoolMap'",
                result == "MyCoolMap", f"got {result!r}")
    except Exception as e:
        _fail("_to_pascal_case: hyphenated", str(e))

    # 17. _to_pascal_case: single word
    try:
        result = _to_pascal_case("town")
        _assert("_to_pascal_case: 'town' -> 'Town'",
                result == "Town", f"got {result!r}")
    except Exception as e:
        _fail("_to_pascal_case: single word", str(e))

    # 18. _parse_defines: parse fake defines from a temp file
    try:
        tmpdir = tempfile.mkdtemp()
        fake_h = os.path.join(tmpdir, "test.h")
        with open(fake_h, "w") as f:
            f.write("#define SPECIES_PIKACHU 25\n")
            f.write("#define SPECIES_BULBASAUR 1\n")
            f.write("#define ITEM_POTION 17\n")
            f.write("#define SPECIES_CHARMANDER 4\n")
        result = _parse_defines(fake_h, "SPECIES_")
        _assert("_parse_defines: finds SPECIES_ defines",
                "SPECIES_PIKACHU" in result and "SPECIES_BULBASAUR" in result,
                f"got {result}")
        _assert("_parse_defines: excludes non-matching prefix",
                "ITEM_POTION" not in result,
                f"ITEM_POTION should not be in result")
        shutil.rmtree(tmpdir)
    except Exception as e:
        _fail("_parse_defines", str(e))
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass

    # 20. _normalise_constant_input: basic
    try:
        result = _normalise_constant_input("Blaze", "ABILITY_")
        _assert("_normalise_constant_input: 'Blaze' with ABILITY_ -> 'BLAZE'",
                result == "BLAZE", f"got {result!r}")
    except Exception as e:
        _fail("_normalise_constant_input: basic", str(e))

    # 21. _normalise_constant_input: already has prefix
    try:
        result = _normalise_constant_input("ABILITY_BLAZE", "ABILITY_")
        _assert("_normalise_constant_input: strips prefix -> 'BLAZE'",
                result == "BLAZE", f"got {result!r}")
    except Exception as e:
        _fail("_normalise_constant_input: already has prefix", str(e))

    # 22. _normalise_constant_input: spaces/hyphens
    try:
        result = _normalise_constant_input("sitrus berry", "ITEM_")
        _assert("_normalise_constant_input: 'sitrus berry' -> 'SITRUS_BERRY'",
                result == "SITRUS_BERRY", f"got {result!r}")
    except Exception as e:
        _fail("_normalise_constant_input: spaces/hyphens", str(e))

    # 23. BATTLE_TYPES[0] is the "single" type (default)
    try:
        _assert("BATTLE_TYPES[0] is 'single'",
                BATTLE_TYPES[0][0] == "single",
                f"got {BATTLE_TYPES[0][0]!r}")
    except Exception as e:
        _fail("BATTLE_TYPES[0] is 'single'", str(e))

    # ==================================================================
    # MON VALIDATORS (~10 tests)
    # ==================================================================

    # 24. _wrap_dialogue: basic wrapping
    try:
        result = _wrap_dialogue("Hello there trainer! I am going to challenge you to a battle right now!")
        _assert("_wrap_dialogue: returns string", isinstance(result, str),
                f"type is {type(result).__name__}")
        _assert("_wrap_dialogue: contains newline markers",
                "\\n" in result or "\\p" in result,
                f"no line-break markers found in: {result!r}")
    except Exception as e:
        _fail("_wrap_dialogue", str(e))

    # 26. _wrap_dialogue: short text stays on one line
    try:
        result = _wrap_dialogue("Hi!")
        _assert("_wrap_dialogue: short text stays single-line",
                result == "Hi!",
                f"got {result!r}")
    except Exception as e:
        _fail("_wrap_dialogue: short text", str(e))

    # 27. _ai_flags_to_party_format: converts AI flags
    try:
        result = _ai_flags_to_party_format("AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT")
        _assert("_ai_flags_to_party_format: converts pipe-separated flags",
                "Check Bad Move" in result and "Try To Faint" in result,
                f"got {result!r}")
    except Exception as e:
        _fail("_ai_flags_to_party_format", str(e))

    # 28. _ai_flags_to_party_format: empty/zero
    try:
        result = _ai_flags_to_party_format("0")
        _assert("_ai_flags_to_party_format: '0' -> empty",
                result == "", f"got {result!r}")
    except Exception as e:
        _fail("_ai_flags_to_party_format: empty", str(e))

    # 29. _party_gender_to_const: Female
    try:
        result = _party_gender_to_const("Female")
        _assert("_party_gender_to_const: 'Female' -> 'F_TRAINER_FEMALE'",
                result == "F_TRAINER_FEMALE", f"got {result!r}")
    except Exception as e:
        _fail("_party_gender_to_const: Female", str(e))

    # 30. _party_gender_to_const: Male -> None (default)
    try:
        result = _party_gender_to_const("Male")
        _assert("_party_gender_to_const: 'Male' -> None",
                result is None, f"got {result!r}")
    except Exception as e:
        _fail("_party_gender_to_const: Male", str(e))

    # 31. _party_ai_to_const: converts human-readable to constants
    try:
        result = _party_ai_to_const("Check Bad Move / Try To Faint")
        _assert("_party_ai_to_const: converts to pipe-separated constants",
                result == "AI_FLAG_CHECK_BAD_MOVE | AI_FLAG_TRY_TO_FAINT",
                f"got {result!r}")
    except Exception as e:
        _fail("_party_ai_to_const", str(e))

    # 32. _party_ai_to_const: empty
    try:
        result = _party_ai_to_const("")
        _assert("_party_ai_to_const: empty -> empty",
                result == "", f"got {result!r}")
    except Exception as e:
        _fail("_party_ai_to_const: empty", str(e))

    # 33. _emit_mon_block_lines: generates .h format mon lines
    try:
        mon = {
            "species": "SPECIES_PIKACHU",
            "level": 25,
            "moves": ["MOVE_THUNDERBOLT", "MOVE_QUICK_ATTACK"],
            "held_item": "ITEM_LIGHT_BALL",
            "ability": "ABILITY_STATIC",
        }
        lines = _emit_mon_block_lines(mon, is_last=True)
        joined = "".join(lines)
        _assert("_emit_mon_block_lines: contains species",
                "SPECIES_PIKACHU" in joined, f"species not found")
        _assert("_emit_mon_block_lines: contains level",
                ".lvl = 25" in joined, f"level not found")
        _assert("_emit_mon_block_lines: contains moves",
                "MOVE_THUNDERBOLT" in joined and "MOVE_QUICK_ATTACK" in joined,
                f"moves not found")
        _assert("_emit_mon_block_lines: contains held item",
                "ITEM_LIGHT_BALL" in joined, f"held_item not found")
    except Exception as e:
        _fail("_emit_mon_block_lines", str(e))

    # 37. _serialize_party_mon: basic serialization
    try:
        mon = {
            "species": "SPECIES_GEODUDE",
            "level": 12,
            "moves": [],
            "held_item": None,
            "ability": None,
        }
        lines = _serialize_party_mon(mon)
        joined = "\n".join(lines)
        _assert("_serialize_party_mon: contains species name",
                "Geodude" in joined, f"Geodude not found in: {joined!r}")
        _assert("_serialize_party_mon: contains level",
                "Level: 12" in joined, f"Level: 12 not found")
    except Exception as e:
        _fail("_serialize_party_mon", str(e))
