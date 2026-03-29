"""Tests for studio.py — Makefile and ROM header reading/writing."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _assert


def run_suite():
    _begin_suite("ROM Studio (Makefile & header helpers)")

    from torch.studio import (
        _read_makefile_var,
        _write_makefile_var,
        _read_game_name,
        _write_game_name,
        _retire_old_rom,
        _read_project_info,
        _read_rom_filename,
        read_rom_fields,
        write_rom_field,
        _validate_rom_field,
    )

    # ── A. _read_makefile_var ──────────────────────────────────────

    tmpdir = tempfile.mkdtemp(prefix="torch_test_studio_")
    try:
        makefile = os.path.join(tmpdir, "Makefile")
        with open(makefile, "w") as f:
            f.write("TITLE       := POKEMON SEIH\n")
            f.write("GAME_CODE   := BPSE\n")
            f.write("REVISION    := 0\n")
            f.write("ROM_NAME    := pokeemerald.gba\n")

        _assert("read TITLE from Makefile",
                _read_makefile_var(makefile, "TITLE") == "POKEMON SEIH",
                f"got {_read_makefile_var(makefile, 'TITLE')!r}")

        _assert("read GAME_CODE from Makefile",
                _read_makefile_var(makefile, "GAME_CODE") == "BPSE",
                f"got {_read_makefile_var(makefile, 'GAME_CODE')!r}")

        _assert("read REVISION from Makefile",
                _read_makefile_var(makefile, "REVISION") == "0",
                f"got {_read_makefile_var(makefile, 'REVISION')!r}")

        _assert("read non-existent var returns None",
                _read_makefile_var(makefile, "NONEXISTENT") is None)

        _assert("read from non-existent file returns None",
                _read_makefile_var(os.path.join(tmpdir, "nope"), "TITLE") is None)

        # ── A2. _read_rom_filename ───────────────────────────────

        # ROM_NAME without Make variable reference → use directly
        _assert("rom_filename reads ROM_NAME directly",
                _read_rom_filename(makefile) == "pokeemerald.gba",
                f"got {_read_rom_filename(makefile)!r}")

        # ROM_NAME with Make variable reference → fall back to FILE_NAME
        mf_varref = os.path.join(tmpdir, "Makefile_varref")
        with open(mf_varref, "w") as f:
            f.write("FILE_NAME   := seihoku\n")
            f.write("ROM_NAME    := $(FILE_NAME).gba\n")
        _assert("rom_filename falls back to FILE_NAME when ROM_NAME has $()",
                _read_rom_filename(mf_varref) == "seihoku.gba",
                f"got {_read_rom_filename(mf_varref)!r}")

        # Both ROM_NAME and FILE_NAME have variable refs → resolve via BUILD_NAME
        mf_chain = os.path.join(tmpdir, "Makefile_chain")
        with open(mf_chain, "w") as f:
            f.write("BUILD_NAME  ?= emerald\n")
            f.write("FILE_NAME   := poke$(BUILD_NAME)\n")
            f.write("ROM_NAME    := $(FILE_NAME).gba\n")
        _assert("rom_filename resolves BUILD_NAME chain",
                _read_rom_filename(mf_chain) == "pokeemerald.gba",
                f"got {_read_rom_filename(mf_chain)!r}")

        # Only FILE_NAME, no ROM_NAME
        mf_fileonly = os.path.join(tmpdir, "Makefile_fileonly")
        with open(mf_fileonly, "w") as f:
            f.write("FILE_NAME   := mygame\n")
        _assert("rom_filename uses FILE_NAME + .gba when no ROM_NAME",
                _read_rom_filename(mf_fileonly) == "mygame.gba",
                f"got {_read_rom_filename(mf_fileonly)!r}")

        # Neither ROM_NAME nor FILE_NAME
        mf_empty = os.path.join(tmpdir, "Makefile_empty")
        with open(mf_empty, "w") as f:
            f.write("TITLE := FOO\n")
        _assert("rom_filename returns ? when no ROM vars exist",
                _read_rom_filename(mf_empty) == "?",
                f"got {_read_rom_filename(mf_empty)!r}")

        # Non-existent file
        _assert("rom_filename returns ? for missing file",
                _read_rom_filename(os.path.join(tmpdir, "nope")) == "?")

        # ── B. _write_makefile_var ─────────────────────────────────

        ok = _write_makefile_var(makefile, "TITLE", "SEIHOKU")
        _assert("write TITLE returns True",
                ok is True, f"got {ok}")

        _assert("written TITLE persists on re-read",
                _read_makefile_var(makefile, "TITLE") == "SEIHOKU",
                f"got {_read_makefile_var(makefile, 'TITLE')!r}")

        # Backup file should exist
        _assert("write creates .bak backup",
                os.path.isfile(makefile + ".bak"))

        # Writing same value returns False (no change)
        ok2 = _write_makefile_var(makefile, "TITLE", "SEIHOKU")
        _assert("write same value returns False",
                ok2 is False, f"got {ok2}")

        # Write to non-existent file returns False
        _assert("write to non-existent file returns False",
                _write_makefile_var(os.path.join(tmpdir, "nope"), "TITLE", "X") is False)

        # ── C. _read_game_name / _write_game_name ──────────────────

        header_path = os.path.join(tmpdir, "rom_header_gf.c")
        with open(header_path, "w") as f:
            f.write('const struct RomHeaderGF RomHeaderGF = {\n')
            f.write('    .gameName = "POKEMON EMER",\n')
            f.write('    .gameVersion = VERSION_EMERALD,\n')
            f.write('};\n')

        _assert("read gameName from header",
                _read_game_name(header_path) == "POKEMON EMER",
                f"got {_read_game_name(header_path)!r}")

        _assert("read gameName from missing file returns None",
                _read_game_name(os.path.join(tmpdir, "nope.c")) is None)

        ok = _write_game_name(header_path, "SEIHOKU")
        _assert("write gameName returns True",
                ok is True, f"got {ok}")

        _assert("written gameName persists on re-read",
                _read_game_name(header_path) == "SEIHOKU",
                f"got {_read_game_name(header_path)!r}")

        _assert("write gameName creates .bak backup",
                os.path.isfile(header_path + ".bak"))

        _assert("write same gameName returns False",
                _write_game_name(header_path, "SEIHOKU") is False)

        _assert("write gameName to missing file returns False",
                _write_game_name(os.path.join(tmpdir, "nope.c"), "X") is False)

        # ── D. _retire_old_rom ─────────────────────────────────────

        game_dir = os.path.join(tmpdir, "game_retire")
        os.makedirs(game_dir)
        old_rom = os.path.join(game_dir, "old.gba")
        with open(old_rom, "wb") as f:
            f.write(b"\x00" * 16)

        _retire_old_rom(game_dir, "old.gba", "new.gba")
        _assert("retire moves old ROM to legacy_roms",
                os.path.isfile(os.path.join(game_dir, "legacy_roms", "old.gba")),
                "old.gba not found in legacy_roms")

        _assert("retire removes original ROM",
                not os.path.isfile(old_rom),
                "old.gba still exists at original path")

        # Same-name retire is a no-op
        with open(os.path.join(game_dir, "same.gba"), "wb") as f:
            f.write(b"\x00")
        _retire_old_rom(game_dir, "same.gba", "same.gba")
        _assert("retire same name is no-op",
                os.path.isfile(os.path.join(game_dir, "same.gba")),
                "same.gba was moved when it shouldn't have been")

        # ── E. _read_project_info ──────────────────────────────────

        info_game = os.path.join(tmpdir, "info_game")
        info_ws = os.path.join(tmpdir, "info_ws")
        os.makedirs(os.path.join(info_game, "data", "maps"), exist_ok=True)
        os.makedirs(os.path.join(info_game, "src"), exist_ok=True)
        os.makedirs(info_ws)

        info_mf = os.path.join(info_game, "Makefile")
        with open(info_mf, "w") as f:
            f.write("TITLE       := TESTGAME\n")
            f.write("GAME_CODE   := TSTS\n")
            f.write("REVISION    := 1\n")
            f.write("ROM_NAME    := test.gba\n")

        # Create a workspace map with scripts
        ws_map = os.path.join(info_ws, "TestTown")
        os.makedirs(ws_map)
        with open(os.path.join(ws_map, "npc.txt"), "w") as f:
            f.write("hello")
        with open(os.path.join(ws_map, "setup.pory"), "w") as f:
            f.write("mapscripts")

        info = _read_project_info(info_game, info_ws)
        _assert("project_info title is correct",
                info["title"] == "TESTGAME",
                f"got {info['title']!r}")

        _assert("project_info map_count is 1",
                info["map_count"] == 1,
                f"got {info['map_count']}")

        _assert("project_info script_count is 2",
                info["script_count"] == 2,
                f"got {info['script_count']}")

        # ── F. read_rom_fields ──────────────────────────────────────

        fields_game = os.path.join(tmpdir, "fields_game")
        os.makedirs(os.path.join(fields_game, "src"), exist_ok=True)
        fields_mf = os.path.join(fields_game, "Makefile")
        with open(fields_mf, "w") as f:
            f.write("TITLE       := MY ROM\n")
            f.write("GAME_CODE   := ABCD\n")
            f.write("MAKER_CODE  := 01\n")
            f.write("REVISION    := 2\n")
            f.write("FILE_NAME   := myrom\n")
            f.write("ROM_NAME    := myrom.gba\n")
        fields_hdr = os.path.join(fields_game, "src", "rom_header_gf.c")
        with open(fields_hdr, "w") as f:
            f.write('.gameName = "MY ROM NAME",\n')

        fields = read_rom_fields(fields_game)
        _assert("read_rom_fields returns 6 fields",
                len(fields) == 6,
                f"got {len(fields)}")

        by_key = {f["key"]: f for f in fields}
        _assert("read_rom_fields: TITLE value",
                by_key["TITLE"]["value"] == "MY ROM",
                f"got {by_key['TITLE']['value']!r}")
        _assert("read_rom_fields: TITLE max_len",
                by_key["TITLE"]["max_len"] == 12,
                f"got {by_key['TITLE']['max_len']}")
        _assert("read_rom_fields: TITLE validator",
                by_key["TITLE"]["validator"] == "title",
                f"got {by_key['TITLE']['validator']}")
        _assert("read_rom_fields: GAME_CODE value",
                by_key["GAME_CODE"]["value"] == "ABCD",
                f"got {by_key['GAME_CODE']['value']!r}")
        _assert("read_rom_fields: ROM_FILENAME value",
                by_key["ROM_FILENAME"]["value"] == "myrom.gba",
                f"got {by_key['ROM_FILENAME']['value']!r}")
        _assert("read_rom_fields: INTERNAL_NAME value",
                by_key["INTERNAL_NAME"]["value"] == "MY ROM NAME",
                f"got {by_key['INTERNAL_NAME']['value']!r}")
        _assert("read_rom_fields: REVISION value",
                by_key["REVISION"]["value"] == "2",
                f"got {by_key['REVISION']['value']!r}")

        # ── G. _validate_rom_field ──────────────────────────────────

        ok, _ = _validate_rom_field("title", "GOOD NAME", 12)
        _assert("validate title: good value", ok is True)

        ok, msg = _validate_rom_field("title", "WAAAAAY TOO LONG", 12)
        _assert("validate title: too long", ok is False)

        ok, msg = _validate_rom_field("title", "BAD@CHAR", 12)
        _assert("validate title: invalid chars", ok is False)

        ok, _ = _validate_rom_field("game_code", "BPSE", 4)
        _assert("validate game_code: good", ok is True)

        ok, msg = _validate_rom_field("game_code", "AB", 4)
        _assert("validate game_code: wrong length", ok is False)

        ok, msg = _validate_rom_field("game_code", "AB!D", 4)
        _assert("validate game_code: non-alnum", ok is False)

        ok, _ = _validate_rom_field("maker_code", "01", 2)
        _assert("validate maker_code: good", ok is True)

        ok, msg = _validate_rom_field("maker_code", "ABC", 2)
        _assert("validate maker_code: wrong length", ok is False)

        ok, _ = _validate_rom_field("revision", "0", None)
        _assert("validate revision: 0", ok is True)

        ok, _ = _validate_rom_field("revision", "255", None)
        _assert("validate revision: 255", ok is True)

        ok, msg = _validate_rom_field("revision", "256", None)
        _assert("validate revision: out of range", ok is False)

        ok, msg = _validate_rom_field("revision", "abc", None)
        _assert("validate revision: not int", ok is False)

        ok, _ = _validate_rom_field("filename", "game.gba", None)
        _assert("validate filename: good", ok is True)

        ok, _ = _validate_rom_field("internal", "POKEMON SEIH", 31)
        _assert("validate internal: good", ok is True)

        ok, msg = _validate_rom_field("internal", 'HAS"QUOTE', 31)
        _assert("validate internal: quote rejected", ok is False)

        ok, msg = _validate_rom_field("title", "", 12)
        _assert("validate: empty rejected", ok is False)

        # ── H. write_rom_field ──────────────────────────────────────

        ok, msg = write_rom_field(fields_game, None, "TITLE", "SEIHOKU")
        _assert("write_rom_field TITLE succeeds",
                ok is True, f"got {ok}, {msg}")
        _assert("write_rom_field TITLE persists",
                _read_makefile_var(fields_mf, "TITLE") == "SEIHOKU",
                f"got {_read_makefile_var(fields_mf, 'TITLE')!r}")

        ok, msg = write_rom_field(fields_game, None, "GAME_CODE", "wxyz")
        _assert("write_rom_field GAME_CODE uppercases",
                ok is True and "WXYZ" in msg, f"got {ok}, {msg}")

        ok, msg = write_rom_field(fields_game, None, "TITLE", "WAAAAAY TOO LONG")
        _assert("write_rom_field rejects too long",
                ok is False, f"got {ok}")

        ok, msg = write_rom_field(fields_game, None, "INTERNAL_NAME", "NEW NAME")
        _assert("write_rom_field INTERNAL_NAME succeeds",
                ok is True, f"got {ok}, {msg}")
        _assert("write_rom_field INTERNAL_NAME persists",
                _read_game_name(fields_hdr) == "NEW NAME",
                f"got {_read_game_name(fields_hdr)!r}")

        ok, msg = write_rom_field(fields_game, None, "ROM_FILENAME", "seihoku")
        _assert("write_rom_field filename adds .gba",
                ok is True and "seihoku.gba" in msg, f"got {ok}, {msg}")
        # FILE_NAME should be the base name, ROM_NAME should use the variable chain
        _assert("write_rom_field filename sets FILE_NAME",
                _read_makefile_var(fields_mf, "FILE_NAME") == "seihoku",
                f"got {_read_makefile_var(fields_mf, 'FILE_NAME')!r}")
        _assert("write_rom_field filename restores ROM_NAME chain",
                _read_makefile_var(fields_mf, "ROM_NAME") == "$(FILE_NAME).gba",
                f"got {_read_makefile_var(fields_mf, 'ROM_NAME')!r}")

        ok, msg = write_rom_field(fields_game, None, "BOGUS_FIELD", "x")
        _assert("write_rom_field unknown field fails",
                ok is False, f"got {ok}")

    finally:
        shutil.rmtree(tmpdir)
