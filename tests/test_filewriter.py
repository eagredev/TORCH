"""FileWriter suite -- atomic writes, block replace, patch, insert."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("FileWriter")

    try:
        from torch.filewriter import _write_atomic, replace_block, patch_define, insert_after_marker
    except ImportError as e:
        _skip("all filewriter tests", f"import failed: {e}")
        return

    # -- Test 1: _write_atomic creates a new file --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "new.txt")
        ok = _write_atomic(path, ["line one\n", "line two\n"])
        _assert(
            "_write_atomic: creates new file",
            ok and os.path.exists(path),
            f"ok={ok}, exists={os.path.exists(path)}"
        )
        with open(path) as f:
            content = f.read()
        _assert(
            "_write_atomic: contents match",
            content == "line one\nline two\n",
            f"got: {content!r}"
        )
    except Exception as e:
        _fail("_write_atomic create", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 2: _write_atomic overwrites existing file --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "overwrite.txt")
        with open(path, "w") as f:
            f.write("old content\n")
        ok = _write_atomic(path, ["new content\n"])
        with open(path) as f:
            content = f.read()
        _assert(
            "_write_atomic: overwrites existing file",
            ok and content == "new content\n",
            f"ok={ok}, content={content!r}"
        )
    except Exception as e:
        _fail("_write_atomic overwrite", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 3: replace_block replaces a marked region --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "block.h")
        with open(path, "w") as f:
            f.write("// HEADER\n// BEGIN_SECTION\nold stuff\n// END_SECTION\n// FOOTER\n")
        ok = replace_block(path, r"// BEGIN_SECTION", r"// END_SECTION",
                           "// BEGIN_SECTION\nnew stuff\n// END_SECTION\n")
        with open(path) as f:
            content = f.read()
        _assert(
            "replace_block: replaces marked region",
            ok and "new stuff" in content and "old stuff" not in content,
            f"ok={ok}, content={content!r}"
        )
        _assert(
            "replace_block: preserves surrounding content",
            content.startswith("// HEADER\n") and content.rstrip().endswith("// FOOTER"),
            f"content={content!r}"
        )
    except Exception as e:
        _fail("replace_block replace", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 4: replace_block region not found, create_if_missing=False --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "noblock.h")
        with open(path, "w") as f:
            f.write("// just a header\n")
        with open(path) as f:
            original = f.read()
        ok = replace_block(path, r"// BEGIN_MISSING", r"// END_MISSING",
                           "new content\n", create_if_missing=False)
        with open(path) as f:
            after = f.read()
        _assert(
            "replace_block: not found + create_if_missing=False -> False",
            ok is False and after == original,
            f"ok={ok}, changed={after != original}"
        )
    except Exception as e:
        _fail("replace_block not found", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 5: replace_block region not found, create_if_missing=True --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "append.h")
        with open(path, "w") as f:
            f.write("// existing\n")
        ok = replace_block(path, r"// BEGIN_MISSING", r"// END_MISSING",
                           "appended content\n", create_if_missing=True)
        with open(path) as f:
            content = f.read()
        _assert(
            "replace_block: not found + create_if_missing=True -> appends",
            ok and "appended content" in content and "// existing" in content,
            f"ok={ok}, content={content!r}"
        )
    except Exception as e:
        _fail("replace_block append", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 6: patch_define changes value, preserves comment --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "defines.h")
        with open(path, "w") as f:
            f.write("#define MY_CONST 10 // important comment\n#define OTHER 20\n")
        ok = patch_define(path, "MY_CONST", 42)
        with open(path) as f:
            content = f.read()
        _assert(
            "patch_define: value changed to 42",
            ok and "42" in content and "10" not in content.split("\n")[0],
            f"ok={ok}, first line={content.split(chr(10))[0]!r}"
        )
        _assert(
            "patch_define: comment preserved",
            "// important comment" in content,
            f"content={content!r}"
        )
    except Exception as e:
        _fail("patch_define", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 7: patch_define with missing constant -> False --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "defines2.h")
        with open(path, "w") as f:
            f.write("#define EXISTING 100\n")
        with open(path) as f:
            original = f.read()
        ok = patch_define(path, "MISSING", 5)
        with open(path) as f:
            after = f.read()
        _assert(
            "patch_define: missing constant -> False, file unchanged",
            ok is False and after == original,
            f"ok={ok}, changed={after != original}"
        )
    except Exception as e:
        _fail("patch_define missing", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 8: insert_after_marker inserts lines in correct position --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "marker.h")
        with open(path, "w") as f:
            f.write("// HEADER\n// MARKER\n// FOOTER\n")
        ok = insert_after_marker(path, r"// MARKER",
                                 ["inserted line 1\n", "inserted line 2\n"])
        with open(path) as f:
            lines = f.readlines()
        _assert(
            "insert_after_marker: returns True",
            ok is True,
            f"ok={ok}"
        )
        # Expected order: HEADER, MARKER, inserted1, inserted2, FOOTER
        stripped = [l.strip() for l in lines]
        marker_idx = stripped.index("// MARKER")
        _assert(
            "insert_after_marker: lines inserted after marker",
            stripped[marker_idx + 1] == "inserted line 1"
            and stripped[marker_idx + 2] == "inserted line 2"
            and stripped[-1] == "// FOOTER",
            f"lines={stripped}"
        )
    except Exception as e:
        _fail("insert_after_marker", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # =====================================================================
    # patch_struct_field tests
    # =====================================================================
    try:
        from torch.filewriter import patch_struct_field
    except ImportError as e:
        _skip("all patch_struct_field tests", f"import failed: {e}")
        return

    # -- Test 9: Simple value replacement --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "species.h")
        with open(path, "w") as f:
            f.write(
                "[SPECIES_BULBASAUR] = {\n"
                "    .baseHP = 45,\n"
                "    .baseAttack = 49,\n"
                "},\n"
            )
        ok = patch_struct_field(path, "SPECIES_BULBASAUR", "baseHP", "100")
        with open(path) as f:
            content = f.read()
        _assert(
            "patch_struct_field: simple value replacement",
            ok and ".baseHP = 100," in content,
            f"ok={ok}, content={content!r}"
        )
        _assert(
            "patch_struct_field: other field unchanged",
            ".baseAttack = 49," in content,
            f"content={content!r}"
        )
    except Exception as e:
        _fail("patch_struct_field simple", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 10: Macro value replacement --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "species.h")
        with open(path, "w") as f:
            f.write(
                "[SPECIES_BULBASAUR] = {\n"
                "    .type1 = TYPE_GRASS,\n"
                "},\n"
            )
        ok = patch_struct_field(path, "SPECIES_BULBASAUR", "type1", "TYPE_FIRE")
        with open(path) as f:
            content = f.read()
        _assert(
            "patch_struct_field: macro value replacement",
            ok and ".type1 = TYPE_FIRE," in content
            and "TYPE_GRASS" not in content,
            f"ok={ok}, content={content!r}"
        )
    except Exception as e:
        _fail("patch_struct_field macro", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 11: String macro replacement --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "trainers.h")
        with open(path, "w") as f:
            f.write(
                "[TRAINER_SAWYER_1] = {\n"
                '    .trainerName = _("SAWYER"),\n'
                "},\n"
            )
        ok = patch_struct_field(path, "TRAINER_SAWYER_1", "trainerName", '_("BUSTER")')
        with open(path) as f:
            content = f.read()
        _assert(
            "patch_struct_field: string macro replacement",
            ok and '_("BUSTER"),' in content
            and '_("SAWYER")' not in content,
            f"ok={ok}, content={content!r}"
        )
    except Exception as e:
        _fail("patch_struct_field string macro", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 12: Brace list value replacement --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "species.h")
        with open(path, "w") as f:
            f.write(
                "[SPECIES_BULBASAUR] = {\n"
                "    .abilities = { ABILITY_OVERGROW, ABILITY_NONE, ABILITY_CHLOROPHYLL },\n"
                "},\n"
            )
        ok = patch_struct_field(path, "SPECIES_BULBASAUR", "abilities",
                                "{ ABILITY_THICK_FAT, ABILITY_NONE, ABILITY_SNOW_WARNING }")
        with open(path) as f:
            content = f.read()
        _assert(
            "patch_struct_field: brace list replacement",
            ok and "ABILITY_THICK_FAT" in content
            and "ABILITY_OVERGROW" not in content,
            f"ok={ok}, content={content!r}"
        )
    except Exception as e:
        _fail("patch_struct_field brace list", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 13: Function call with parens --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "species.h")
        with open(path, "w") as f:
            f.write(
                "[SPECIES_BULBASAUR] = {\n"
                "    .genderRatio = PERCENT_FEMALE(12.5),\n"
                "},\n"
            )
        ok = patch_struct_field(path, "SPECIES_BULBASAUR", "genderRatio",
                                "PERCENT_FEMALE(25.0)")
        with open(path) as f:
            content = f.read()
        _assert(
            "patch_struct_field: function call with parens",
            ok and "PERCENT_FEMALE(25.0)," in content
            and "12.5" not in content,
            f"ok={ok}, content={content!r}"
        )
    except Exception as e:
        _fail("patch_struct_field parens", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 14: Comment preservation --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "species.h")
        with open(path, "w") as f:
            f.write(
                "[SPECIES_BULBASAUR] = {\n"
                "    .baseHP = 45,  // hit points\n"
                "},\n"
            )
        ok = patch_struct_field(path, "SPECIES_BULBASAUR", "baseHP", "100")
        with open(path) as f:
            content = f.read()
        _assert(
            "patch_struct_field: comment preserved",
            ok and ".baseHP = 100," in content
            and "// hit points" in content,
            f"ok={ok}, content={content!r}"
        )
    except Exception as e:
        _fail("patch_struct_field comment", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 15: Multiple structs — only patch the named one --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "species.h")
        with open(path, "w") as f:
            f.write(
                "[SPECIES_BULBASAUR] = {\n"
                "    .baseHP = 45,\n"
                "},\n"
                "[SPECIES_IVYSAUR] = {\n"
                "    .baseHP = 60,\n"
                "},\n"
            )
        ok = patch_struct_field(path, "SPECIES_BULBASAUR", "baseHP", "100")
        with open(path) as f:
            content = f.read()
        _assert(
            "patch_struct_field: only named struct patched",
            ok and ".baseHP = 100," in content
            and ".baseHP = 60," in content,
            f"ok={ok}, content={content!r}"
        )
    except Exception as e:
        _fail("patch_struct_field multiple structs", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 16: Struct not found -> False --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "species.h")
        with open(path, "w") as f:
            f.write(
                "[SPECIES_BULBASAUR] = {\n"
                "    .baseHP = 45,\n"
                "},\n"
            )
        ok = patch_struct_field(path, "SPECIES_CHARMANDER", "baseHP", "100")
        _assert(
            "patch_struct_field: struct not found -> False",
            ok is False,
            f"ok={ok}"
        )
    except Exception as e:
        _fail("patch_struct_field struct not found", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 17: Field not found -> False --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "species.h")
        with open(path, "w") as f:
            f.write(
                "[SPECIES_BULBASAUR] = {\n"
                "    .baseHP = 45,\n"
                "},\n"
            )
        ok = patch_struct_field(path, "SPECIES_BULBASAUR", "baseDefense", "100")
        _assert(
            "patch_struct_field: field not found -> False",
            ok is False,
            f"ok={ok}"
        )
    except Exception as e:
        _fail("patch_struct_field field not found", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 18: File not found -> False --
    try:
        ok = patch_struct_field("/tmp/nonexistent_torch_fw_test.h",
                                "SPECIES_BULBASAUR", "baseHP", "100")
        _assert(
            "patch_struct_field: file not found -> False",
            ok is False,
            f"ok={ok}"
        )
    except Exception as e:
        _fail("patch_struct_field file not found", str(e))

    # -- Test 19: Trailing comma preserved --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "species.h")
        with open(path, "w") as f:
            f.write(
                "[SPECIES_BULBASAUR] = {\n"
                "    .baseHP = 45,\n"
                "},\n"
            )
        ok = patch_struct_field(path, "SPECIES_BULBASAUR", "baseHP", "100")
        with open(path) as f:
            content = f.read()
        _assert(
            "patch_struct_field: trailing comma preserved",
            ok and "    .baseHP = 100,\n" in content,
            f"ok={ok}, content={content!r}"
        )
    except Exception as e:
        _fail("patch_struct_field trailing comma", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Test 20: No trailing comma preserved --
    tmp_dir = tempfile.mkdtemp(prefix="torch_fw_")
    try:
        path = os.path.join(tmp_dir, "species.h")
        with open(path, "w") as f:
            f.write(
                "[SPECIES_BULBASAUR] = {\n"
                "    .baseHP = 45\n"
                "},\n"
            )
        ok = patch_struct_field(path, "SPECIES_BULBASAUR", "baseHP", "100")
        with open(path) as f:
            content = f.read()
        _assert(
            "patch_struct_field: no trailing comma stays without comma",
            ok and "    .baseHP = 100\n" in content,
            f"ok={ok}, content={content!r}"
        )
    except Exception as e:
        _fail("patch_struct_field no comma", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
