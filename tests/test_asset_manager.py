"""Asset Manager suite -- PNG parser, name derivation, validation, import logic."""
import os
import struct
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def _make_png(width=64, height=64, bit_depth=8, color_type=3, palette_size=16,
              trns=False, palette_colors=None):
    """Build a minimal valid PNG with IHDR + optional PLTE + empty IDAT + IEND.

    color_type=3 (indexed), color_type=2 (truecolour, no PLTE).
    trns=True adds a tRNS chunk marking palette index 0 as transparent.
    palette_colors=[(r,g,b), ...] overrides palette with specific RGB values.
    """
    import zlib

    buf = bytearray()
    # PNG signature
    buf += b"\x89PNG\r\n\x1a\n"

    def _chunk(ctype, data):
        c = struct.pack(">I", len(data)) + ctype + data
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        c += struct.pack(">I", crc)
        return c

    # IHDR: width(4) height(4) bit_depth(1) color_type(1) compression(1) filter(1) interlace(1)
    ihdr_data = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    buf += _chunk(b"IHDR", ihdr_data)

    # PLTE — only for indexed colour (type 3)
    if color_type == 3 and palette_size > 0:
        if palette_colors:
            plte_data = bytearray()
            for r, g, b in palette_colors:
                plte_data += bytes([r, g, b])
            # Pad to palette_size if needed
            while len(plte_data) < palette_size * 3:
                plte_data += b"\x00\x00\x00"
        else:
            plte_data = b"\x00\x00\x00" * palette_size  # black entries
        buf += _chunk(b"PLTE", plte_data)

    # tRNS — optional, marks palette index 0 as fully transparent
    if trns and color_type == 3:
        buf += _chunk(b"tRNS", b"\x00")

    # IDAT — minimal: empty image (single filter byte per row, all zero)
    raw_data = b""
    for _ in range(height):
        raw_data += b"\x00"  # filter = none
        if color_type == 3:
            raw_data += b"\x00" * width  # 1 byte per pixel (indexed)
        elif color_type == 2:
            raw_data += b"\x00" * (width * 3)  # 3 bytes per pixel (RGB)
        else:
            raw_data += b"\x00" * width
    compressed = zlib.compress(raw_data)
    buf += _chunk(b"IDAT", compressed)

    # IEND
    buf += _chunk(b"IEND", b"")

    return bytes(buf)


def run_suite():
    _begin_suite("AssetManager")

    try:
        from torch.asset_manager import (
            _parse_png_info,
            _derive_trainer_pic_name,
            _derive_trainer_pic_const,
            _derive_file_stem,
            _validate_trainer_sprite,
            _read_trainer_pic_count,
            _is_already_imported,
            _insert_incbin,
            _insert_sprite_entry,
            _insert_pic_constant,
        )
    except ImportError as e:
        _skip("all asset_manager tests", f"import failed: {e}")
        return

    # ── PNG parser tests ──────────────────────────────────────────────

    # Test 1: valid 64x64 indexed PNG
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "test.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(64, 64, 8, 3, 16))
        info = _parse_png_info(png_path)
        _assert("png parser: valid 64x64 indexed",
                info is not None and info["width"] == 64 and info["height"] == 64
                and info["palette_size"] == 16 and info["color_type"] == 3,
                f"got: {info}")
    except Exception as e:
        _fail("png parser: valid 64x64 indexed", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 2: valid PNG with small palette
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "small_pal.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(64, 64, 8, 3, 8))
        info = _parse_png_info(png_path)
        _assert("png parser: 8-colour palette",
                info is not None and info["palette_size"] == 8,
                f"got palette_size={info['palette_size'] if info else 'None'}")
    except Exception as e:
        _fail("png parser: 8-colour palette", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 3: truecolour PNG (no PLTE)
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "rgb.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(64, 64, 8, 2, 0))
        info = _parse_png_info(png_path)
        _assert("png parser: truecolour (no PLTE)",
                info is not None and info["color_type"] == 2
                and info["palette_size"] == 0,
                f"got: {info}")
    except Exception as e:
        _fail("png parser: truecolour", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 4: not a PNG
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        bad_path = os.path.join(tmp_dir, "bad.png")
        with open(bad_path, "wb") as f:
            f.write(b"not a png file at all")
        info = _parse_png_info(bad_path)
        _assert("png parser: rejects non-PNG",
                info is None, f"expected None, got: {info}")
    except Exception as e:
        _fail("png parser: rejects non-PNG", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 5: nonexistent file
    try:
        info = _parse_png_info("/nonexistent/file.png")
        _assert("png parser: nonexistent file",
                info is None, f"expected None, got: {info}")
    except Exception as e:
        _fail("png parser: nonexistent file", str(e))

    # ── Name derivation tests ────────────────────────────────────────

    # Test 6: CamelCase derivation
    try:
        _assert("name: rival_dawn.png -> RivalDawn",
                _derive_trainer_pic_name("rival_dawn.png") == "RivalDawn",
                f"got: {_derive_trainer_pic_name('rival_dawn.png')}")
        _assert("name: gym_leader_kai.png -> GymLeaderKai",
                _derive_trainer_pic_name("gym_leader_kai.png") == "GymLeaderKai",
                f"got: {_derive_trainer_pic_name('gym_leader_kai.png')}")
        _assert("name: elite-four-nova.png -> EliteFourNova",
                _derive_trainer_pic_name("elite-four-nova.png") == "EliteFourNova",
                f"got: {_derive_trainer_pic_name('elite-four-nova.png')}")
        _assert("name: hiker.png -> Hiker",
                _derive_trainer_pic_name("hiker.png") == "Hiker",
                f"got: {_derive_trainer_pic_name('hiker.png')}")
    except Exception as e:
        _fail("name derivation (CamelCase)", str(e))

    # Test 7: UPPER_SNAKE constant derivation
    try:
        _assert("const: RivalDawn -> TRAINER_PIC_RIVAL_DAWN",
                _derive_trainer_pic_const("RivalDawn") == "TRAINER_PIC_RIVAL_DAWN",
                f"got: {_derive_trainer_pic_const('RivalDawn')}")
        _assert("const: GymLeaderKai -> TRAINER_PIC_GYM_LEADER_KAI",
                _derive_trainer_pic_const("GymLeaderKai") == "TRAINER_PIC_GYM_LEADER_KAI",
                f"got: {_derive_trainer_pic_const('GymLeaderKai')}")
        _assert("const: Hiker -> TRAINER_PIC_HIKER",
                _derive_trainer_pic_const("Hiker") == "TRAINER_PIC_HIKER",
                f"got: {_derive_trainer_pic_const('Hiker')}")
    except Exception as e:
        _fail("name derivation (UPPER_SNAKE)", str(e))

    # Test 8: file stem derivation
    try:
        _assert("stem: rival_dawn.png -> rival_dawn",
                _derive_file_stem("rival_dawn.png") == "rival_dawn",
                f"got: {_derive_file_stem('rival_dawn.png')}")
        _assert("stem: Rival-Dawn.png -> rival_dawn",
                _derive_file_stem("Rival-Dawn.png") == "rival_dawn",
                f"got: {_derive_file_stem('Rival-Dawn.png')}")
    except Exception as e:
        _fail("file stem derivation", str(e))

    # ── Sprite validation tests ──────────────────────────────────────

    # Test 9: valid sprite
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "valid.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(64, 64, 8, 3, 12))
        ok, msg = _validate_trainer_sprite(png_path)
        _assert("validate: valid 64x64 12-colour sprite",
                ok is True and "12" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("validate: valid sprite", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 10: wrong dimensions
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "wrong_size.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(128, 128, 8, 3, 16))
        ok, msg = _validate_trainer_sprite(png_path)
        _assert("validate: rejects wrong dimensions",
                ok is False and "128x128" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("validate: wrong dimensions", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 11: too many colours
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "too_many.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(64, 64, 8, 3, 32))
        ok, msg = _validate_trainer_sprite(png_path)
        _assert("validate: rejects >16 colours",
                ok is False and "32" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("validate: too many colours", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 12: not a PNG
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        bad_path = os.path.join(tmp_dir, "bad.png")
        with open(bad_path, "wb") as f:
            f.write(b"garbage data")
        ok, msg = _validate_trainer_sprite(bad_path)
        _assert("validate: rejects non-PNG",
                ok is False, f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("validate: non-PNG", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Constant reading + duplicate detection ───────────────────────

    # Test 13: read TRAINER_PIC_COUNT
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        const_path = os.path.join(tmp_dir, "trainers.h")
        with open(const_path, "w") as f:
            f.write("#define TRAINER_PIC_HIKER                  0\n")
            f.write("#define TRAINER_PIC_RIVAL                  1\n")
            f.write("#define TRAINER_PIC_COUNT                  2\n")
        count, line = _read_trainer_pic_count(const_path)
        _assert("read count: finds TRAINER_PIC_COUNT",
                count == 2 and line == 2,
                f"count={count}, line={line}")
    except Exception as e:
        _fail("read TRAINER_PIC_COUNT", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 14: duplicate detection
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        const_path = os.path.join(tmp_dir, "trainers.h")
        with open(const_path, "w") as f:
            f.write("#define TRAINER_PIC_HIKER                  0\n")
            f.write("#define TRAINER_PIC_COUNT                  1\n")
        _assert("duplicate: detects existing constant",
                _is_already_imported("TRAINER_PIC_HIKER", const_path) is True,
                "should detect HIKER")
        _assert("duplicate: negative for new constant",
                _is_already_imported("TRAINER_PIC_RIVAL_DAWN", const_path) is False,
                "should not detect RIVAL_DAWN")
    except Exception as e:
        _fail("duplicate detection", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── INCBIN insertion test ────────────────────────────────────────

    # Test 15: insert INCBIN lines
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        trainers_h = os.path.join(tmp_dir, "trainers.h")
        with open(trainers_h, "w") as f:
            f.write('#include "constants/trainers.h"\n')
            f.write('#include "data.h"\n')
            f.write("\n")
            f.write('const u32 gTrainerFrontPic_Hiker[] = INCBIN_U32("graphics/trainers/front_pics/hiker.4bpp.smol");\n')
            f.write('const u16 gTrainerPalette_Hiker[] = INCBIN_U16("graphics/trainers/front_pics/hiker.gbapal");\n')
            f.write("\n")
            f.write('const u32 gTrainerFrontPic_Rival[] = INCBIN_U32("graphics/trainers/front_pics/rival.4bpp.smol");\n')
            f.write('const u16 gTrainerPalette_Rival[] = INCBIN_U16("graphics/trainers/front_pics/rival.gbapal");\n')
            f.write("\n")
            f.write('const u8 gTrainerBackPic_Brendan[] = INCBIN_U8("graphics/trainers/back_pics/brendan.4bpp");\n')

        ok = _insert_incbin(trainers_h, "RivalDawn", "rival_dawn")
        _assert("incbin: insertion succeeds", ok is True, f"ok={ok}")

        with open(trainers_h) as f:
            content = f.read()
        _assert("incbin: new FrontPic line present",
                "gTrainerFrontPic_RivalDawn" in content,
                "missing FrontPic line")
        _assert("incbin: new Palette line present",
                "gTrainerPalette_RivalDawn" in content,
                "missing Palette line")
        # Verify it's before the BackPic section
        fp_pos = content.index("gTrainerFrontPic_RivalDawn")
        bp_pos = content.index("gTrainerBackPic_Brendan")
        _assert("incbin: inserted before back pics",
                fp_pos < bp_pos,
                f"FrontPic at {fp_pos}, BackPic at {bp_pos}")
    except Exception as e:
        _fail("INCBIN insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Sprite entry insertion test ──────────────────────────────────

    # Test 16: insert TRAINER_SPRITE entry
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        trainers_h = os.path.join(tmp_dir, "trainers.h")
        with open(trainers_h, "w") as f:
            f.write("const struct TrainerSprite gTrainerSprites[] =\n")
            f.write("{\n")
            f.write("    TRAINER_SPRITE(TRAINER_PIC_HIKER, gTrainerFrontPic_Hiker, gTrainerPalette_Hiker),\n")
            f.write("};\n")
            f.write("\n")
            f.write("static const union AnimCmd sAnimCmd_Hoenn[] =\n")

        ok = _insert_sprite_entry(trainers_h, "TRAINER_PIC_RIVAL_DAWN", "RivalDawn")
        _assert("sprite entry: insertion succeeds", ok is True, f"ok={ok}")

        with open(trainers_h) as f:
            content = f.read()
        _assert("sprite entry: new line present",
                "TRAINER_SPRITE(TRAINER_PIC_RIVAL_DAWN, gTrainerFrontPic_RivalDawn, gTrainerPalette_RivalDawn)" in content,
                "missing entry")
        # Verify it's before the closing };
        entry_pos = content.index("TRAINER_PIC_RIVAL_DAWN")
        close_pos = content.index("};")
        _assert("sprite entry: before closing brace",
                entry_pos < close_pos,
                f"entry at {entry_pos}, close at {close_pos}")
    except Exception as e:
        _fail("sprite entry insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Constant insertion test ──────────────────────────────────────

    # Test 17: insert pic constant + increment count
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        const_path = os.path.join(tmp_dir, "trainers.h")
        with open(const_path, "w") as f:
            f.write("#define TRAINER_PIC_HIKER                  0\n")
            f.write("#define TRAINER_PIC_RIVAL                  1\n")
            f.write("#define TRAINER_PIC_COUNT                  2\n")

        pic_id = _insert_pic_constant(const_path, "TRAINER_PIC_RIVAL_DAWN")
        _assert("constant: returns correct ID",
                pic_id == 2, f"expected 2, got {pic_id}")

        with open(const_path) as f:
            content = f.read()
        _assert("constant: new define present",
                "TRAINER_PIC_RIVAL_DAWN" in content,
                "missing define")
        _assert("constant: count incremented to 3",
                "TRAINER_PIC_COUNT" in content and "3" in content.split("TRAINER_PIC_COUNT")[1].split("\n")[0],
                f"content:\n{content}")
    except Exception as e:
        _fail("constant insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 18: duplicate import blocked
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        const_path = os.path.join(tmp_dir, "trainers.h")
        with open(const_path, "w") as f:
            f.write("#define TRAINER_PIC_RIVAL_DAWN             0\n")
            f.write("#define TRAINER_PIC_COUNT                  1\n")
        _assert("duplicate: _is_already_imported detects it",
                _is_already_imported("TRAINER_PIC_RIVAL_DAWN", const_path) is True,
                "should detect existing constant")
    except Exception as e:
        _fail("duplicate import blocked", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 19: truecolour PNG validation (accepted with warning)
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "rgb.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(64, 64, 8, 2, 0))
        ok, msg = _validate_trainer_sprite(png_path)
        _assert("validate: truecolour accepted with note",
                ok is True and "non-indexed" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("validate: truecolour", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 20: PNG parser handles wrong-size IHDR gracefully
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        bad_path = os.path.join(tmp_dir, "bad_ihdr.png")
        with open(bad_path, "wb") as f:
            # Valid sig + truncated IHDR chunk
            f.write(b"\x89PNG\r\n\x1a\n")
            f.write(struct.pack(">I", 5))  # length = 5 (too short for IHDR)
            f.write(b"IHDR")
            f.write(b"\x00" * 5)
            f.write(b"\x00\x00\x00\x00")  # CRC
        info = _parse_png_info(bad_path)
        _assert("png parser: rejects truncated IHDR",
                info is None, f"expected None, got: {info}")
    except Exception as e:
        _fail("png parser: truncated IHDR", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ==================================================================
    # OVERWORLD SPRITE TESTS
    # ==================================================================

    try:
        from torch.asset_manager import (
            _derive_overworld_name,
            _derive_overworld_const,
            _validate_overworld_sprite,
            _detect_overworld_frame_size,
            _read_ow_gfx_count,
            _is_ow_already_imported,
            _insert_overworld_constant,
            _insert_overworld_incbin,
            _insert_overworld_pic_table,
            _insert_overworld_graphics_info,
            _insert_overworld_pointer,
            _ow_size_fields,
            ASSET_TYPES,
        )
    except ImportError as e:
        _skip("all overworld tests", f"import failed: {e}")
        return

    # ── Overworld name derivation ────────────────────────────────────

    # Test 21: overworld CamelCase name
    try:
        _assert("ow name: my_npc.png -> MyNpc",
                _derive_overworld_name("my_npc.png") == "MyNpc",
                f"got: {_derive_overworld_name('my_npc.png')}")
        _assert("ow name: police_officer.png -> PoliceOfficer",
                _derive_overworld_name("police_officer.png") == "PoliceOfficer",
                f"got: {_derive_overworld_name('police_officer.png')}")
        _assert("ow name: shop-keeper.png -> ShopKeeper",
                _derive_overworld_name("shop-keeper.png") == "ShopKeeper",
                f"got: {_derive_overworld_name('shop-keeper.png')}")
    except Exception as e:
        _fail("overworld name derivation", str(e))

    # Test 22: overworld constant derivation
    try:
        _assert("ow const: MyNpc -> OBJ_EVENT_GFX_MY_NPC",
                _derive_overworld_const("MyNpc") == "OBJ_EVENT_GFX_MY_NPC",
                f"got: {_derive_overworld_const('MyNpc')}")
        _assert("ow const: PoliceOfficer -> OBJ_EVENT_GFX_POLICE_OFFICER",
                _derive_overworld_const("PoliceOfficer") == "OBJ_EVENT_GFX_POLICE_OFFICER",
                f"got: {_derive_overworld_const('PoliceOfficer')}")
    except Exception as e:
        _fail("overworld constant derivation", str(e))

    # ── Frame size detection ─────────────────────────────────────────

    # Test 23: standard 16x32 NPC spritesheet (144x32 = 9 frames)
    try:
        result = _detect_overworld_frame_size(144, 32)
        _assert("frame detect: 144x32 -> 16x32, 9 frames",
                result == (16, 32, 9),
                f"got: {result}")
    except Exception as e:
        _fail("frame detect: 144x32", str(e))

    # Test 24: small 16x16 NPC (144x16 = 9 frames)
    try:
        result = _detect_overworld_frame_size(144, 16)
        _assert("frame detect: 144x16 -> 16x16, 9 frames",
                result == (16, 16, 9),
                f"got: {result}")
    except Exception as e:
        _fail("frame detect: 144x16", str(e))

    # Test 25: 4-frame 16x32 NPC (64x32)
    try:
        result = _detect_overworld_frame_size(64, 32)
        _assert("frame detect: 64x32 -> 16x32, 4 frames",
                result == (16, 32, 4),
                f"got: {result}")
    except Exception as e:
        _fail("frame detect: 64x32", str(e))

    # Test 26: 32x32 large NPC (288x32 = 9 frames)
    try:
        result = _detect_overworld_frame_size(288, 32)
        _assert("frame detect: 288x32 -> 32x32, 9 frames",
                result == (32, 32, 9),
                f"got: {result}")
    except Exception as e:
        _fail("frame detect: 288x32", str(e))

    # Test 27: unsupported dimensions
    try:
        result = _detect_overworld_frame_size(100, 50)
        _assert("frame detect: 100x50 -> None",
                result is None, f"expected None, got: {result}")
    except Exception as e:
        _fail("frame detect: unsupported", str(e))

    # ── Overworld validation ─────────────────────────────────────────

    # Test 28: valid 144x32 overworld spritesheet
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "npc.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(144, 32, 4, 3, 16))
        ok, msg = _validate_overworld_sprite(png_path)
        _assert("ow validate: valid 144x32 spritesheet",
                ok is True and "16x32" in msg and "9f" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("ow validate: valid spritesheet", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 29: invalid dimensions (not multiple of any frame size)
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "bad_size.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(100, 50, 4, 3, 16))
        ok, msg = _validate_overworld_sprite(png_path)
        _assert("ow validate: rejects bad dimensions",
                ok is False and "Unsupported" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("ow validate: bad dimensions", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 30: too many colours for overworld sprite
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "many_cols.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(144, 32, 8, 3, 32))
        ok, msg = _validate_overworld_sprite(png_path)
        _assert("ow validate: rejects >16 colours",
                ok is False and "32" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("ow validate: too many colours", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 31: non-PNG rejected
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        bad_path = os.path.join(tmp_dir, "bad.png")
        with open(bad_path, "wb") as f:
            f.write(b"not a png")
        ok, msg = _validate_overworld_sprite(bad_path)
        _assert("ow validate: rejects non-PNG",
                ok is False, f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("ow validate: non-PNG", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Overworld GFX count reading ──────────────────────────────────

    # Test 32: read NUM_OBJ_EVENT_GFX
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        eo_path = os.path.join(tmp_dir, "event_objects.h")
        with open(eo_path, "w") as f:
            f.write("#define OBJ_EVENT_GFX_BOY_1                  1\n")
            f.write("#define OBJ_EVENT_GFX_GIRL_1                 2\n")
            f.write("#define NUM_OBJ_EVENT_GFX                    3\n")
        count, line, name = _read_ow_gfx_count(eo_path)
        _assert("ow count: reads NUM_OBJ_EVENT_GFX",
                count == 3 and line == 2 and name == "NUM_OBJ_EVENT_GFX",
                f"count={count}, line={line}, name={name}")
    except Exception as e:
        _fail("read NUM_OBJ_EVENT_GFX", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 33: read OBJ_EVENT_GFX_COUNT (older naming)
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        eo_path = os.path.join(tmp_dir, "event_objects.h")
        with open(eo_path, "w") as f:
            f.write("#define OBJ_EVENT_GFX_BOY_1                  1\n")
            f.write("#define OBJ_EVENT_GFX_COUNT                  2\n")
        count, line, name = _read_ow_gfx_count(eo_path)
        _assert("ow count: reads OBJ_EVENT_GFX_COUNT",
                count == 2 and name == "OBJ_EVENT_GFX_COUNT",
                f"count={count}, name={name}")
    except Exception as e:
        _fail("read OBJ_EVENT_GFX_COUNT", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Overworld duplicate detection ────────────────────────────────

    # Test 34: detects existing OBJ_EVENT_GFX_* constant
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        eo_path = os.path.join(tmp_dir, "event_objects.h")
        with open(eo_path, "w") as f:
            f.write("#define OBJ_EVENT_GFX_MY_NPC                 5\n")
            f.write("#define NUM_OBJ_EVENT_GFX                    6\n")
        _assert("ow dup: detects existing constant",
                _is_ow_already_imported("OBJ_EVENT_GFX_MY_NPC", eo_path) is True,
                "should detect MY_NPC")
        _assert("ow dup: negative for new constant",
                _is_ow_already_imported("OBJ_EVENT_GFX_NEW_CHAR", eo_path) is False,
                "should not detect NEW_CHAR")
    except Exception as e:
        _fail("overworld duplicate detection", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Overworld constant insertion ─────────────────────────────────

    # Test 35: insert OBJ_EVENT_GFX constant + increment count
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        eo_path = os.path.join(tmp_dir, "event_objects.h")
        with open(eo_path, "w") as f:
            f.write("#define OBJ_EVENT_GFX_BOY_1                  0\n")
            f.write("#define OBJ_EVENT_GFX_GIRL_1                 1\n")
            f.write("#define NUM_OBJ_EVENT_GFX                    2\n")
        gfx_id = _insert_overworld_constant(eo_path, "OBJ_EVENT_GFX_MY_NPC")
        _assert("ow const insert: returns correct ID",
                gfx_id == 2, f"expected 2, got {gfx_id}")
        with open(eo_path) as f:
            content = f.read()
        _assert("ow const insert: new define present",
                "OBJ_EVENT_GFX_MY_NPC" in content,
                "missing define")
        _assert("ow const insert: count incremented to 3",
                "NUM_OBJ_EVENT_GFX" in content
                and "3" in content.split("NUM_OBJ_EVENT_GFX")[-1].split("\n")[0],
                f"content:\n{content}")
    except Exception as e:
        _fail("overworld constant insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Overworld INCBIN insertion ───────────────────────────────────

    # Test 36: insert gObjectEventPic_ INCBIN line
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        gfx_h = os.path.join(tmp_dir, "object_event_graphics.h")
        with open(gfx_h, "w") as f:
            f.write('const u32 gObjectEventPic_Boy1[] = INCBIN_U32("graphics/object_events/pics/people/boy_1.4bpp");\n')
            f.write('const u32 gObjectEventPic_Girl1[] = INCBIN_U32("graphics/object_events/pics/people/girl_1.4bpp");\n')
            f.write("\n")
            f.write("// end of file\n")
        ok = _insert_overworld_incbin(gfx_h, "MyNpc", "my_npc")
        _assert("ow incbin: insertion succeeds", ok is True, f"ok={ok}")
        with open(gfx_h) as f:
            content = f.read()
        _assert("ow incbin: new line present",
                'gObjectEventPic_MyNpc' in content,
                "missing INCBIN line")
        _assert("ow incbin: uses .4bpp (not .4bpp.smol)",
                'my_npc.4bpp"' in content,
                "wrong extension")
        # Verify it's after the existing pics
        girl_pos = content.index("Girl1")
        npc_pos = content.index("MyNpc")
        _assert("ow incbin: after existing entries",
                npc_pos > girl_pos,
                f"girl at {girl_pos}, npc at {npc_pos}")
    except Exception as e:
        _fail("overworld INCBIN insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Overworld pic table insertion ────────────────────────────────

    # Test 37: insert sPicTable_* definition
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        pt_h = os.path.join(tmp_dir, "object_event_pic_tables.h")
        with open(pt_h, "w") as f:
            f.write("static const struct SpriteFrameImage sPicTable_Boy1[] = {\n")
            f.write("    overworld_ascending_frames(gObjectEventPic_Boy1, 2, 4),\n")
            f.write("};\n")
            f.write("\n")
            f.write("// end\n")
        ok = _insert_overworld_pic_table(pt_h, "MyNpc", 2, 4)
        _assert("ow pic table: insertion succeeds", ok is True, f"ok={ok}")
        with open(pt_h) as f:
            content = f.read()
        _assert("ow pic table: sPicTable_MyNpc present",
                "sPicTable_MyNpc" in content,
                "missing pic table")
        _assert("ow pic table: uses overworld_ascending_frames",
                "overworld_ascending_frames(gObjectEventPic_MyNpc, 2, 4)" in content,
                "wrong macro or args")
    except Exception as e:
        _fail("overworld pic table insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Overworld graphics info insertion ────────────────────────────

    # Test 38: insert gObjectEventGraphicsInfo_* struct
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        info_h = os.path.join(tmp_dir, "object_event_graphics_info.h")
        with open(info_h, "w") as f:
            f.write("const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_Boy1 = {\n")
            f.write("    .tileTag = TAG_NONE,\n")
            f.write("    .images = sPicTable_Boy1,\n")
            f.write("};\n")
            f.write("\n")
            f.write("// end\n")
        ok = _insert_overworld_graphics_info(info_h, "MyNpc", 16, 32)
        _assert("ow gfx info: insertion succeeds", ok is True, f"ok={ok}")
        with open(info_h) as f:
            content = f.read()
        _assert("ow gfx info: struct present",
                "gObjectEventGraphicsInfo_MyNpc" in content,
                "missing struct")
        _assert("ow gfx info: correct size (256)",
                ".size = 256," in content,
                "wrong size")
        _assert("ow gfx info: correct dimensions",
                ".width = 16," in content and ".height = 32," in content,
                "wrong width/height")
        _assert("ow gfx info: correct OAM ref",
                "gObjectEventBaseOam_16x32" in content,
                "wrong OAM")
        _assert("ow gfx info: references pic table",
                "sPicTable_MyNpc" in content,
                "wrong pic table ref")
    except Exception as e:
        _fail("overworld graphics info insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Overworld pointer insertion ──────────────────────────────────

    # Test 39: insert extern + pointer table entry
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        ptrs_h = os.path.join(tmp_dir, "object_event_graphics_info_pointers.h")
        with open(ptrs_h, "w") as f:
            f.write("extern const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_Boy1;\n")
            f.write("extern const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_Girl1;\n")
            f.write("\n")
            f.write("const struct ObjectEventGraphicsInfo *const gObjectEventGraphicsInfoPointers[] = {\n")
            f.write("    [OBJ_EVENT_GFX_BOY_1] = &gObjectEventGraphicsInfo_Boy1,\n")
            f.write("    [OBJ_EVENT_GFX_GIRL_1] = &gObjectEventGraphicsInfo_Girl1,\n")
            f.write("};\n")
        ok = _insert_overworld_pointer(ptrs_h, "MyNpc", "OBJ_EVENT_GFX_MY_NPC")
        _assert("ow pointer: insertion succeeds", ok is True, f"ok={ok}")
        with open(ptrs_h) as f:
            content = f.read()
        _assert("ow pointer: extern present",
                "extern const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_MyNpc;" in content,
                "missing extern")
        _assert("ow pointer: array entry present",
                "[OBJ_EVENT_GFX_MY_NPC] = &gObjectEventGraphicsInfo_MyNpc," in content,
                "missing array entry")
        # Extern should be before the pointer table
        extern_pos = content.index("gObjectEventGraphicsInfo_MyNpc;")
        array_pos = content.index("[OBJ_EVENT_GFX_MY_NPC]")
        _assert("ow pointer: extern before array entry",
                extern_pos < array_pos,
                f"extern at {extern_pos}, array at {array_pos}")
    except Exception as e:
        _fail("overworld pointer insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Size field calculations ──────────────────────────────────────

    # Test 40: _ow_size_fields for standard 16x32
    try:
        size, oam, tw, th = _ow_size_fields(16, 32)
        _assert("ow size: 16x32 -> 256 bytes, 16x32 OAM, 2x4 tiles",
                size == 256 and oam == "16x32" and tw == 2 and th == 4,
                f"size={size}, oam={oam}, tw={tw}, th={th}")
    except Exception as e:
        _fail("ow size fields: 16x32", str(e))

    # Test 41: _ow_size_fields for 32x32
    try:
        size, oam, tw, th = _ow_size_fields(32, 32)
        _assert("ow size: 32x32 -> 512 bytes",
                size == 512 and oam == "32x32" and tw == 4 and th == 4,
                f"size={size}, oam={oam}, tw={tw}, th={th}")
    except Exception as e:
        _fail("ow size fields: 32x32", str(e))

    # ── const_from_file generalisation ───────────────────────────────

    # Test 42: ASSET_TYPES has const_from_file for both types
    try:
        trainer_fn = ASSET_TYPES["trainer_sprites"]["const_from_file"]
        ow_fn = ASSET_TYPES["overworld_sprites"]["const_from_file"]
        _assert("const_from_file: trainer derives correctly",
                trainer_fn("rival_dawn.png") == "TRAINER_PIC_RIVAL_DAWN",
                f"got: {trainer_fn('rival_dawn.png')}")
        _assert("const_from_file: overworld derives correctly",
                ow_fn("my_npc.png") == "OBJ_EVENT_GFX_MY_NPC",
                f"got: {ow_fn('my_npc.png')}")
    except Exception as e:
        _fail("const_from_file generalisation", str(e))

    # ── Overworld truecolour validation ──────────────────────────────

    # Test 43: truecolour overworld sprite accepted with note
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        png_path = os.path.join(tmp_dir, "rgb_npc.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(144, 32, 8, 2, 0))
        ok, msg = _validate_overworld_sprite(png_path)
        _assert("ow validate: truecolour accepted with note",
                ok is True and "non-indexed" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("ow validate: truecolour", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ==================================================================
    # MUSIC TRACK TESTS
    # ==================================================================

    try:
        from torch.asset_manager import (
            _derive_music_name,
            _derive_music_const,
            _validate_music_file,
            _read_end_mus_line,
            _is_music_already_imported,
            _insert_music_constant,
            _insert_song_table_entry,
            _MUSIC_MAX_SIZE,
        )
    except ImportError as e:
        _skip("all music tests", f"import failed: {e}")
        return

    # ── Music name derivation ──────────────────────────────────────

    # Test 44: music name from filename
    try:
        _assert("music name: battle_theme.mid -> battle_theme",
                _derive_music_name("battle_theme.mid") == "battle_theme",
                f"got: {_derive_music_name('battle_theme.mid')}")
        _assert("music name: Route-123-Night.mid -> route_123_night",
                _derive_music_name("Route-123-Night.mid") == "route_123_night",
                f"got: {_derive_music_name('Route-123-Night.mid')}")
        _assert("music name: MyTrack.mid -> mytrack",
                _derive_music_name("MyTrack.mid") == "mytrack",
                f"got: {_derive_music_name('MyTrack.mid')}")
    except Exception as e:
        _fail("music name derivation", str(e))

    # Test 45: music constant from name
    try:
        _assert("music const: battle_theme -> MUS_BATTLE_THEME",
                _derive_music_const("battle_theme") == "MUS_BATTLE_THEME",
                f"got: {_derive_music_const('battle_theme')}")
        _assert("music const: route_123_night -> MUS_ROUTE_123_NIGHT",
                _derive_music_const("route_123_night") == "MUS_ROUTE_123_NIGHT",
                f"got: {_derive_music_const('route_123_night')}")
    except Exception as e:
        _fail("music constant derivation", str(e))

    # ── Music validation ───────────────────────────────────────────

    # Test 46: valid .mid file
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        mid_path = os.path.join(tmp_dir, "track.mid")
        with open(mid_path, "wb") as f:
            f.write(b"MThd" + b"\x00" * 100)  # minimal MIDI-like content
        ok, msg = _validate_music_file(mid_path)
        _assert("music validate: valid .mid accepted",
                ok is True and "MIDI" in msg and "KB" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("music validate: valid .mid", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 47: empty file rejected
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        mid_path = os.path.join(tmp_dir, "empty.mid")
        with open(mid_path, "wb") as f:
            pass  # 0 bytes
        ok, msg = _validate_music_file(mid_path)
        _assert("music validate: empty file rejected",
                ok is False and "Empty" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("music validate: empty file", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 48: wrong extension rejected
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        wav_path = os.path.join(tmp_dir, "track.wav")
        with open(wav_path, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 50)
        ok, msg = _validate_music_file(wav_path)
        _assert("music validate: .wav rejected",
                ok is False and "extension" in msg.lower(),
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("music validate: wrong extension", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 49: nonexistent file rejected
    try:
        ok, msg = _validate_music_file("/nonexistent/track.mid")
        _assert("music validate: nonexistent rejected",
                ok is False and "not found" in msg.lower(),
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("music validate: nonexistent", str(e))

    # ── Music constant insertion ───────────────────────────────────

    # Test 50: read END_MUS + last MUS value
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        songs_h = os.path.join(tmp_dir, "songs.h")
        with open(songs_h, "w") as f:
            f.write("#define SE_USE_ITEM                 1\n")
            f.write("#define MUS_LITTLEROOT              350\n")
            f.write("#define MUS_ROUTE101                351\n")
            f.write("#define MUS_SURF                    352\n")
            f.write("#define END_MUS                     MUS_SURF\n")
        val, idx = _read_end_mus_line(songs_h)
        _assert("music read: finds last MUS value",
                val == 352, f"expected 352, got {val}")
        _assert("music read: finds END_MUS line",
                idx == 4, f"expected 4, got {idx}")
    except Exception as e:
        _fail("read END_MUS", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 51: insert MUS constant + update END_MUS
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        songs_h = os.path.join(tmp_dir, "songs.h")
        with open(songs_h, "w") as f:
            f.write("#define MUS_LITTLEROOT              350\n")
            f.write("#define MUS_SURF                    351\n")
            f.write("#define END_MUS                     MUS_SURF\n")
            f.write("\n")
            f.write("#define PH_TRAP_BLEND               400\n")
        music_id = _insert_music_constant(songs_h, "MUS_BATTLE_THEME")
        _assert("music const insert: returns correct ID",
                music_id == 352, f"expected 352, got {music_id}")
        with open(songs_h) as f:
            content = f.read()
        _assert("music const insert: new define present",
                "MUS_BATTLE_THEME" in content and "352" in content,
                "missing define or ID")
        _assert("music const insert: END_MUS updated",
                "END_MUS" in content
                and "MUS_BATTLE_THEME" in content.split("END_MUS")[1].split("\n")[0],
                f"END_MUS not updated:\n{content}")
        _assert("music const insert: PH_ entries preserved",
                "PH_TRAP_BLEND" in content,
                "phoneme entries lost")
    except Exception as e:
        _fail("music constant insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Song table insertion ───────────────────────────────────────

    # Test 52: insert song table entry
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        st_path = os.path.join(tmp_dir, "song_table.inc")
        with open(st_path, "w") as f:
            f.write("\t.align 2\n")
            f.write("gSongTable::\n")
            f.write("\tsong mus_dummy, MUSIC_PLAYER_BGM, 0\n")
            f.write("\tsong mus_surf, MUSIC_PLAYER_BGM, 0\n")
            f.write("\tsong mus_route101, MUSIC_PLAYER_BGM, 0\n")
            f.write("\tsong ph_trap_blend, MUSIC_PLAYER_SE2, 2\n")
            f.write("\tsong ph_trap_held, MUSIC_PLAYER_SE2, 2\n")
            f.write("\n")
            f.write("\t.align 2\n")
        ok = _insert_song_table_entry(st_path, "battle_theme")
        _assert("song table: insertion succeeds", ok is True, f"ok={ok}")
        with open(st_path) as f:
            content = f.read()
        _assert("song table: new entry present",
                "mus_battle_theme, MUSIC_PLAYER_BGM, 0" in content,
                "missing entry")
        # Verify it's between mus_route101 and ph_trap_blend
        mus_pos = content.index("mus_route101")
        new_pos = content.index("mus_battle_theme")
        ph_pos = content.index("ph_trap_blend")
        _assert("song table: correct position",
                mus_pos < new_pos < ph_pos,
                f"mus at {mus_pos}, new at {new_pos}, ph at {ph_pos}")
    except Exception as e:
        _fail("song table insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Music duplicate detection ──────────────────────────────────

    # Test 53: detects existing MUS_* constant
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        songs_h = os.path.join(tmp_dir, "songs.h")
        with open(songs_h, "w") as f:
            f.write("#define MUS_BATTLE_THEME            500\n")
            f.write("#define END_MUS                     MUS_BATTLE_THEME\n")
        _assert("music dup: detects existing constant",
                _is_music_already_imported("MUS_BATTLE_THEME", songs_h) is True,
                "should detect MUS_BATTLE_THEME")
        _assert("music dup: negative for new constant",
                _is_music_already_imported("MUS_NEW_TRACK", songs_h) is False,
                "should not detect MUS_NEW_TRACK")
    except Exception as e:
        _fail("music duplicate detection", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── ASSET_TYPES music registration ─────────────────────────────

    # Test 54: music_tracks in ASSET_TYPES with correct const_from_file
    try:
        _assert("asset type: music_tracks registered",
                "music_tracks" in ASSET_TYPES,
                "missing music_tracks key")
        mt = ASSET_TYPES["music_tracks"]
        _assert("asset type: music file pattern is *.mid",
                mt["file_pattern"] == "*.mid",
                f"got: {mt['file_pattern']}")
        cfn = mt["const_from_file"]
        _assert("asset type: const_from_file derives correctly",
                cfn("battle_theme.mid") == "MUS_BATTLE_THEME",
                f"got: {cfn('battle_theme.mid')}")
    except Exception as e:
        _fail("ASSET_TYPES music registration", str(e))

    # ── Music detect_already_imported ──────────────────────────────

    # Test 55: _detect_already_imported for music_tracks
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _detect_already_imported
        game_dir = os.path.join(tmp_dir, "game")
        const_dir = os.path.join(game_dir, "include", "constants")
        os.makedirs(const_dir)
        songs_h = os.path.join(const_dir, "songs.h")
        with open(songs_h, "w") as f:
            f.write("#define SE_USE_ITEM                 1\n")
            f.write("#define MUS_SURF                    350\n")
            f.write("#define MUS_ROUTE101                351\n")
            f.write("#define END_MUS                     MUS_ROUTE101\n")
        existing = _detect_already_imported("music_tracks", game_dir)
        _assert("detect music: finds MUS_SURF",
                "MUS_SURF" in existing,
                f"existing: {existing}")
        _assert("detect music: finds MUS_ROUTE101",
                "MUS_ROUTE101" in existing,
                f"existing: {existing}")
        _assert("detect music: excludes SE_*",
                not any(c.startswith("SE_") for c in existing),
                f"SE_ found in: {existing}")
    except Exception as e:
        _fail("detect_already_imported for music", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ==================================================================
    # SOUND EFFECT TESTS
    # ==================================================================

    try:
        from torch.asset_manager import (
            _derive_se_name,
            _derive_se_const,
            _validate_se_file,
            _read_end_se_line,
            _is_se_already_imported,
            _insert_se_constant,
            _insert_se_song_table_entry,
        )
    except ImportError as e:
        _skip("all SE tests", f"import failed: {e}")
        return

    # ── SE name derivation ────────────────────────────────────────

    # Test 56: SE name from filename
    try:
        _assert("SE name: my_sound.s -> se_my_sound",
                _derive_se_name("my_sound.s") == "se_my_sound",
                f"got: {_derive_se_name('my_sound.s')}")
        _assert("SE name: se_custom_hit.s -> se_custom_hit (no double prefix)",
                _derive_se_name("se_custom_hit.s") == "se_custom_hit",
                f"got: {_derive_se_name('se_custom_hit.s')}")
        _assert("SE name: Hit-Sound.s -> se_hit_sound",
                _derive_se_name("Hit-Sound.s") == "se_hit_sound",
                f"got: {_derive_se_name('Hit-Sound.s')}")
    except Exception as e:
        _fail("SE name derivation", str(e))

    # Test 57: SE constant from name
    try:
        _assert("SE const: se_my_sound -> SE_MY_SOUND",
                _derive_se_const("se_my_sound") == "SE_MY_SOUND",
                f"got: {_derive_se_const('se_my_sound')}")
        _assert("SE const: se_custom_hit -> SE_CUSTOM_HIT",
                _derive_se_const("se_custom_hit") == "SE_CUSTOM_HIT",
                f"got: {_derive_se_const('se_custom_hit')}")
    except Exception as e:
        _fail("SE constant derivation", str(e))

    # ── SE validation ─────────────────────────────────────────────

    # Test 58: valid .s file with MPlayDef include
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        se_path = os.path.join(tmp_dir, "se_test.s")
        with open(se_path, "w") as f:
            f.write('\t.include "MPlayDef.s"\n')
            f.write("\t.section .rodata\n")
            f.write("\t.align 2\n")
        ok, msg = _validate_se_file(se_path)
        _assert("SE validate: valid .s accepted",
                ok is True and "GBA assembly" in msg and "KB" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("SE validate: valid .s", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 59: empty file rejected
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        se_path = os.path.join(tmp_dir, "empty.s")
        with open(se_path, "wb") as f:
            pass  # 0 bytes
        ok, msg = _validate_se_file(se_path)
        _assert("SE validate: empty file rejected",
                ok is False and "Empty" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("SE validate: empty file", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 60: wrong extension rejected
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        wav_path = os.path.join(tmp_dir, "sound.wav")
        with open(wav_path, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 50)
        ok, msg = _validate_se_file(wav_path)
        _assert("SE validate: .wav rejected",
                ok is False and "extension" in msg.lower(),
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("SE validate: wrong extension", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 61: no MPlayDef include rejected
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        se_path = os.path.join(tmp_dir, "bad.s")
        with open(se_path, "w") as f:
            f.write("\t.section .rodata\n")
            f.write("\t.align 2\n")
        ok, msg = _validate_se_file(se_path)
        _assert("SE validate: no MPlayDef rejected",
                ok is False and "MPlayDef" in msg,
                f"ok={ok}, msg={msg}")
    except Exception as e:
        _fail("SE validate: no MPlayDef", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── SE constant insertion ─────────────────────────────────────

    # Test 62: read END_SE + last SE value
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        songs_h = os.path.join(tmp_dir, "songs.h")
        with open(songs_h, "w") as f:
            f.write("#define SE_USE_ITEM                 1\n")
            f.write("#define SE_PC_ON                    2\n")
            f.write("#define SE_SUDOWOODO_SHAKE          269\n")
            f.write("#define END_SE                      SE_SUDOWOODO_SHAKE\n")
        val, idx = _read_end_se_line(songs_h)
        _assert("SE read: finds last SE value",
                val == 269, f"expected 269, got {val}")
        _assert("SE read: finds END_SE line",
                idx == 3, f"expected 3, got {idx}")
    except Exception as e:
        _fail("read END_SE", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 63: insert SE constant + update END_SE
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        songs_h = os.path.join(tmp_dir, "songs.h")
        with open(songs_h, "w") as f:
            f.write("#define SE_USE_ITEM                 1\n")
            f.write("#define SE_SUDOWOODO_SHAKE          269\n")
            f.write("#define END_SE                      SE_SUDOWOODO_SHAKE\n")
            f.write("\n")
            f.write("#define START_MUS                   350\n")
        se_id = _insert_se_constant(songs_h, "SE_CUSTOM_HIT")
        _assert("SE const insert: returns correct ID",
                se_id == 270, f"expected 270, got {se_id}")
        with open(songs_h) as f:
            content = f.read()
        _assert("SE const insert: new define present",
                "SE_CUSTOM_HIT" in content and "270" in content,
                "missing define or ID")
        _assert("SE const insert: END_SE updated",
                "END_SE" in content
                and "SE_CUSTOM_HIT" in content.split("END_SE")[1].split("\n")[0],
                f"END_SE not updated:\n{content}")
        _assert("SE const insert: START_MUS preserved",
                "START_MUS" in content,
                "START_MUS lost")
    except Exception as e:
        _fail("SE constant insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── SE song table insertion ───────────────────────────────────

    # Test 64: insert SE song table entry
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        st_path = os.path.join(tmp_dir, "song_table.inc")
        with open(st_path, "w") as f:
            f.write("\t.align 2\n")
            f.write("gSongTable::\n")
            f.write("\tsong se_none, MUSIC_PLAYER_SE1, 1\n")
            f.write("\tsong se_use_item, MUSIC_PLAYER_SE1, 1\n")
            f.write("\tsong se_sudowoodo_shake, MUSIC_PLAYER_SE1, 1\n")
            f.write("\tsong mus_dummy, MUSIC_PLAYER_BGM, 0\n")
            f.write("\tsong mus_littleroot, MUSIC_PLAYER_BGM, 0\n")
        ok = _insert_se_song_table_entry(st_path, "se_custom_hit")
        _assert("SE song table: insertion succeeds", ok is True, f"ok={ok}")
        with open(st_path) as f:
            content = f.read()
        _assert("SE song table: new entry present",
                "se_custom_hit, MUSIC_PLAYER_SE1, 1" in content,
                "missing entry")
        # Verify it's between se_sudowoodo_shake and mus_dummy
        se_pos = content.index("se_sudowoodo_shake")
        new_pos = content.index("se_custom_hit")
        mus_pos = content.index("mus_dummy")
        _assert("SE song table: correct position (after last se_, before mus_)",
                se_pos < new_pos < mus_pos,
                f"se at {se_pos}, new at {new_pos}, mus at {mus_pos}")
    except Exception as e:
        _fail("SE song table insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── SE duplicate detection ────────────────────────────────────

    # Test 65: detects existing SE_* constant
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        songs_h = os.path.join(tmp_dir, "songs.h")
        with open(songs_h, "w") as f:
            f.write("#define SE_CUSTOM_HIT               270\n")
            f.write("#define END_SE                      SE_CUSTOM_HIT\n")
        _assert("SE dup: detects existing constant",
                _is_se_already_imported("SE_CUSTOM_HIT", songs_h) is True,
                "should detect SE_CUSTOM_HIT")
        _assert("SE dup: negative for new constant",
                _is_se_already_imported("SE_NEW_SOUND", songs_h) is False,
                "should not detect SE_NEW_SOUND")
    except Exception as e:
        _fail("SE duplicate detection", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── ASSET_TYPES SE registration ───────────────────────────────

    # Test 66: sound_effects in ASSET_TYPES with correct const_from_file
    try:
        _assert("asset type: sound_effects registered",
                "sound_effects" in ASSET_TYPES,
                "missing sound_effects key")
        se = ASSET_TYPES["sound_effects"]
        _assert("asset type: SE file pattern is *.s",
                se["file_pattern"] == "*.s",
                f"got: {se['file_pattern']}")
        cfn = se["const_from_file"]
        _assert("asset type: const_from_file derives correctly",
                cfn("my_sound.s") == "SE_MY_SOUND",
                f"got: {cfn('my_sound.s')}")
    except Exception as e:
        _fail("ASSET_TYPES SE registration", str(e))

    # ── SE detect_already_imported ────────────────────────────────

    # Test 67: _detect_already_imported for sound_effects
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _detect_already_imported
        game_dir = os.path.join(tmp_dir, "game")
        const_dir = os.path.join(game_dir, "include", "constants")
        os.makedirs(const_dir)
        songs_h = os.path.join(const_dir, "songs.h")
        with open(songs_h, "w") as f:
            f.write("#define SE_USE_ITEM                 1\n")
            f.write("#define SE_PC_ON                    2\n")
            f.write("#define END_SE                      SE_PC_ON\n")
            f.write("#define MUS_SURF                    350\n")
        existing = _detect_already_imported("sound_effects", game_dir)
        _assert("detect SE: finds SE_USE_ITEM",
                "SE_USE_ITEM" in existing,
                f"existing: {existing}")
        _assert("detect SE: finds SE_PC_ON",
                "SE_PC_ON" in existing,
                f"existing: {existing}")
        _assert("detect SE: excludes MUS_*",
                not any(c.startswith("MUS_") for c in existing),
                f"MUS_ found in: {existing}")
    except Exception as e:
        _fail("detect_already_imported for SE", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── PNG tRNS detection + sanitiser ────────────────────────────

    try:
        from torch.asset_manager import _sanitise_sprite_png
    except ImportError:
        _skip("sanitise_sprite_png tests", "import failed")
        _sanitise_sprite_png = None

    if _sanitise_sprite_png is not None:

        # Test 68: _parse_png_info detects tRNS chunk
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            png_with = os.path.join(tmp_dir, "with_trns.png")
            png_without = os.path.join(tmp_dir, "no_trns.png")
            with open(png_with, "wb") as f:
                f.write(_make_png(144, 32, 4, 3, 16, trns=True))
            with open(png_without, "wb") as f:
                f.write(_make_png(144, 32, 4, 3, 16, trns=False))
            info_with = _parse_png_info(png_with)
            info_without = _parse_png_info(png_without)
            _assert("png parser: has_trns True when present",
                    info_with is not None and info_with["has_trns"] is True,
                    f"got: {info_with}")
            _assert("png parser: has_trns False when absent",
                    info_without is not None and info_without["has_trns"] is False,
                    f"got: {info_without}")
        except Exception as e:
            _fail("png parser: tRNS detection", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 69: _sanitise_sprite_png strips tRNS chunk
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            src = os.path.join(tmp_dir, "source.png")
            dest = os.path.join(tmp_dir, "dest.png")
            with open(src, "wb") as f:
                f.write(_make_png(144, 32, 4, 3, 16, trns=True))
            # Confirm source has tRNS
            _assert("sanitise: source has tRNS",
                    _parse_png_info(src)["has_trns"] is True,
                    "source missing tRNS")
            stripped = _sanitise_sprite_png(src, dest)
            _assert("sanitise: returns True when tRNS stripped",
                    stripped is True,
                    f"got: {stripped}")
            # Dest should exist and have no tRNS
            dest_info = _parse_png_info(dest)
            _assert("sanitise: dest has no tRNS",
                    dest_info is not None and dest_info["has_trns"] is False,
                    f"got: {dest_info}")
            # Dimensions should be preserved
            _assert("sanitise: dimensions preserved",
                    dest_info["width"] == 144 and dest_info["height"] == 32,
                    f"got: {dest_info['width']}x{dest_info['height']}")
        except Exception as e:
            _fail("sanitise_sprite_png: strip tRNS", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 70: _sanitise_sprite_png is a no-op without tRNS
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            src = os.path.join(tmp_dir, "clean.png")
            dest = os.path.join(tmp_dir, "dest.png")
            data = _make_png(64, 64, 8, 3, 16, trns=False)
            with open(src, "wb") as f:
                f.write(data)
            stripped = _sanitise_sprite_png(src, dest)
            _assert("sanitise: returns False when no tRNS",
                    stripped is False,
                    f"got: {stripped}")
            # Dest should be byte-identical to source
            with open(dest, "rb") as f:
                dest_data = f.read()
            _assert("sanitise: byte-identical when no tRNS",
                    dest_data == data,
                    f"sizes: src={len(data)} dest={len(dest_data)}")
        except Exception as e:
            _fail("sanitise_sprite_png: no-op without tRNS", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Manifest functions ─────────────────────────────────────────

    try:
        from torch.asset_manager import (
            _manifest_path, _read_manifest, _write_manifest,
            _append_manifest,
        )
    except ImportError as e:
        _skip("manifest tests", f"import failed: {e}")
        _manifest_path = None

    if _manifest_path is not None:

        # Test 71: _manifest_path returns correct path
        try:
            p = _manifest_path("/tmp/test_base")
            _assert("manifest_path: correct path",
                    p == "/tmp/test_base/imports.manifest",
                    f"got: {p}")
        except Exception as e:
            _fail("manifest_path", str(e))

        # Test 72: _read_manifest on missing file returns empty dict
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            m = _read_manifest(tmp_dir)
            _assert("read_manifest: empty on missing file",
                    m == {},
                    f"got: {m}")
        except Exception as e:
            _fail("read_manifest: empty", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 73: _write_manifest + _read_manifest round-trip
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            manifest = {
                "trainer_sprites": {"rival_dawn.png", "gym_kai.png"},
                "music_tracks": {"battle.mid"},
            }
            _write_manifest(tmp_dir, manifest)
            result = _read_manifest(tmp_dir)
            _assert("manifest round-trip: trainer_sprites",
                    result.get("trainer_sprites") == {"rival_dawn.png", "gym_kai.png"},
                    f"got: {result.get('trainer_sprites')}")
            _assert("manifest round-trip: music_tracks",
                    result.get("music_tracks") == {"battle.mid"},
                    f"got: {result.get('music_tracks')}")
        except Exception as e:
            _fail("manifest round-trip", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 74: _append_manifest creates file and appends
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            _append_manifest(tmp_dir, "trainer_sprites", "rival.png")
            _append_manifest(tmp_dir, "trainer_sprites", "kai.png")
            _append_manifest(tmp_dir, "music_tracks", "theme.mid")
            result = _read_manifest(tmp_dir)
            _assert("append_manifest: trainer_sprites has both",
                    result.get("trainer_sprites") == {"rival.png", "kai.png"},
                    f"got: {result.get('trainer_sprites')}")
            _assert("append_manifest: music_tracks",
                    result.get("music_tracks") == {"theme.mid"},
                    f"got: {result.get('music_tracks')}")
        except Exception as e:
            _fail("append_manifest", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 75: _read_manifest ignores comments and blank lines
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            mpath = os.path.join(tmp_dir, "imports.manifest")
            with open(mpath, "w") as f:
                f.write("# TORCH asset manifest\n")
                f.write("# type:filename\n")
                f.write("\n")
                f.write("trainer_sprites:test.png\n")
                f.write("  \n")
            result = _read_manifest(tmp_dir)
            _assert("read_manifest: ignores comments/blanks",
                    result == {"trainer_sprites": {"test.png"}},
                    f"got: {result}")
        except Exception as e:
            _fail("read_manifest: comments", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── File hashing ───────────────────────────────────────────────

    try:
        from torch.asset_manager import _file_hash, _hash_sanitised_png
    except ImportError as e:
        _skip("file hash tests", f"import failed: {e}")
        _file_hash = None

    if _file_hash is not None:

        # Test 76: _file_hash returns consistent hash
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            fpath = os.path.join(tmp_dir, "test.bin")
            with open(fpath, "wb") as f:
                f.write(b"hello world")
            h1 = _file_hash(fpath)
            h2 = _file_hash(fpath)
            _assert("file_hash: consistent",
                    h1 is not None and h1 == h2 and len(h1) == 64,
                    f"got: {h1}")
        except Exception as e:
            _fail("file_hash: consistent", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 77: _file_hash returns None for missing file
        try:
            h = _file_hash("/tmp/nonexistent_torch_test_file.bin")
            _assert("file_hash: None for missing",
                    h is None,
                    f"got: {h}")
        except Exception as e:
            _fail("file_hash: missing", str(e))

        # Test 78: _file_hash detects changes
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            fpath = os.path.join(tmp_dir, "test.bin")
            with open(fpath, "wb") as f:
                f.write(b"version 1")
            h1 = _file_hash(fpath)
            with open(fpath, "wb") as f:
                f.write(b"version 2")
            h2 = _file_hash(fpath)
            _assert("file_hash: detects changes",
                    h1 != h2,
                    f"h1={h1}, h2={h2}")
        except Exception as e:
            _fail("file_hash: changes", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 79: _hash_sanitised_png matches stripped copy
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            from torch.asset_manager import _sanitise_sprite_png
            # Create PNG with tRNS
            src = os.path.join(tmp_dir, "with_trns.png")
            dest = os.path.join(tmp_dir, "stripped.png")
            with open(src, "wb") as f:
                f.write(_make_png(64, 64, 8, 3, 16, trns=True))
            _sanitise_sprite_png(src, dest)
            # Hash of source (sanitised in memory) should match dest (on disk)
            src_hash = _hash_sanitised_png(src)
            dest_hash = _file_hash(dest)
            _assert("hash_sanitised_png: matches stripped copy",
                    src_hash is not None and src_hash == dest_hash,
                    f"src={src_hash}, dest={dest_hash}")
        except Exception as e:
            _fail("hash_sanitised_png: matches stripped", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 80: _hash_sanitised_png on PNG without tRNS equals _file_hash
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            fpath = os.path.join(tmp_dir, "clean.png")
            with open(fpath, "wb") as f:
                f.write(_make_png(64, 64, 8, 3, 16, trns=False))
            h_san = _hash_sanitised_png(fpath)
            h_raw = _file_hash(fpath)
            _assert("hash_sanitised_png: no tRNS equals file_hash",
                    h_san == h_raw,
                    f"sanitised={h_san}, raw={h_raw}")
        except Exception as e:
            _fail("hash_sanitised_png: no tRNS", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Upper snake to camel ───────────────────────────────────────

    try:
        from torch.asset_manager import _upper_snake_to_camel
    except ImportError as e:
        _skip("upper_snake_to_camel tests", f"import failed: {e}")
        _upper_snake_to_camel = None

    if _upper_snake_to_camel is not None:

        # Test 81: basic conversion
        try:
            _assert("upper_snake_to_camel: RIVAL_DAWN",
                    _upper_snake_to_camel("RIVAL_DAWN") == "RivalDawn",
                    f"got: {_upper_snake_to_camel('RIVAL_DAWN')}")
            _assert("upper_snake_to_camel: GYM_LEADER_KAI",
                    _upper_snake_to_camel("GYM_LEADER_KAI") == "GymLeaderKai",
                    f"got: {_upper_snake_to_camel('GYM_LEADER_KAI')}")
            _assert("upper_snake_to_camel: single word",
                    _upper_snake_to_camel("DAWN") == "Dawn",
                    f"got: {_upper_snake_to_camel('DAWN')}")
        except Exception as e:
            _fail("upper_snake_to_camel", str(e))

    # ── Removal helpers ────────────────────────────────────────────

    try:
        from torch.asset_manager import (
            _remove_lines_matching, _remove_struct_block,
            _remove_define_and_decrement, _get_define_value,
            _remove_last_music_constant, _remove_last_se_constant,
            _can_remove_asset,
        )
    except ImportError as e:
        _skip("removal helper tests", f"import failed: {e}")
        _remove_lines_matching = None

    if _remove_lines_matching is not None:

        # Test 84: _get_define_value
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            hdr = os.path.join(tmp_dir, "test.h")
            with open(hdr, "w") as f:
                f.write("#define FOO 42\n")
                f.write("#define BAR 99\n")
            val = _get_define_value(hdr, "FOO")
            _assert("get_define_value: FOO=42",
                    val == 42,
                    f"got: {val}")
            val2 = _get_define_value(hdr, "MISSING")
            _assert("get_define_value: None for missing",
                    val2 is None,
                    f"got: {val2}")
        except Exception as e:
            _fail("get_define_value", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 85: _remove_lines_matching
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            fpath = os.path.join(tmp_dir, "test.h")
            with open(fpath, "w") as f:
                f.write("line 1\n")
                f.write("line 2 with MARKER\n")
                f.write("line 3\n")
                f.write("also has MARKER here\n")
                f.write("line 5\n")
            removed = _remove_lines_matching(fpath, ["MARKER"])
            _assert("remove_lines_matching: removed 2",
                    removed == 2,
                    f"got: {removed}")
            with open(fpath) as f:
                content = f.read()
            _assert("remove_lines_matching: content correct",
                    "MARKER" not in content and "line 1" in content and "line 5" in content,
                    f"got: {content}")
        except Exception as e:
            _fail("remove_lines_matching", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 86: _remove_struct_block
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            fpath = os.path.join(tmp_dir, "test.h")
            with open(fpath, "w") as f:
                f.write("// header\n")
                f.write("\n")
                f.write("static const struct Foo sPicTable_MyNpc[] = {\n")
                f.write("    some_data,\n")
                f.write("};\n")
                f.write("\n")
                f.write("// footer\n")
            result = _remove_struct_block(fpath, "sPicTable_MyNpc")
            _assert("remove_struct_block: returns True",
                    result is True,
                    f"got: {result}")
            with open(fpath) as f:
                content = f.read()
            _assert("remove_struct_block: block removed",
                    "sPicTable_MyNpc" not in content,
                    f"content: {content}")
            _assert("remove_struct_block: header and footer preserved",
                    "// header" in content and "// footer" in content,
                    f"content: {content}")
        except Exception as e:
            _fail("remove_struct_block", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 87: _remove_define_and_decrement
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            fpath = os.path.join(tmp_dir, "test.h")
            with open(fpath, "w") as f:
                f.write("#define TRAINER_PIC_RIVAL          10\n")
                f.write("#define TRAINER_PIC_DAWN           11\n")
                f.write("#define TRAINER_PIC_COUNT           12\n")
            result = _remove_define_and_decrement(fpath, "TRAINER_PIC_DAWN", "TRAINER_PIC_COUNT")
            _assert("remove_define_decrement: returns True",
                    result is True,
                    f"got: {result}")
            with open(fpath) as f:
                content = f.read()
            _assert("remove_define_decrement: DAWN removed",
                    "TRAINER_PIC_DAWN" not in content,
                    f"content: {content}")
            _assert("remove_define_decrement: count decremented",
                    "11" in content,  # count was 12, now 11
                    f"content: {content}")
            _assert("remove_define_decrement: RIVAL preserved",
                    "TRAINER_PIC_RIVAL" in content,
                    f"content: {content}")
        except Exception as e:
            _fail("remove_define_and_decrement", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 88: _remove_last_music_constant
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            songs_h = os.path.join(tmp_dir, "songs.h")
            with open(songs_h, "w") as f:
                f.write("#define MUS_SURF                    350\n")
                f.write("#define MUS_CUSTOM_BATTLE           351\n")
                f.write("#define END_MUS                     MUS_CUSTOM_BATTLE\n")
            result = _remove_last_music_constant(songs_h, "MUS_CUSTOM_BATTLE")
            _assert("remove_last_music: returns True",
                    result is True,
                    f"got: {result}")
            with open(songs_h) as f:
                content = f.read()
            _assert("remove_last_music: constant removed",
                    "MUS_CUSTOM_BATTLE" not in content or "END_MUS" in content,
                    f"content: {content}")
            _assert("remove_last_music: END_MUS updated",
                    "MUS_SURF" in content,
                    f"content: {content}")
        except Exception as e:
            _fail("remove_last_music_constant", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 89: _remove_last_se_constant
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            songs_h = os.path.join(tmp_dir, "songs.h")
            with open(songs_h, "w") as f:
                f.write("#define SE_USE_ITEM                 1\n")
                f.write("#define SE_CUSTOM_HIT               2\n")
                f.write("#define END_SE                      SE_CUSTOM_HIT\n")
            result = _remove_last_se_constant(songs_h, "SE_CUSTOM_HIT")
            _assert("remove_last_se: returns True",
                    result is True,
                    f"got: {result}")
            with open(songs_h) as f:
                content = f.read()
            _assert("remove_last_se: constant removed",
                    "SE_CUSTOM_HIT" not in content or "END_SE" in content,
                    f"content: {content}")
            _assert("remove_last_se: END_SE updated to SE_USE_ITEM",
                    "SE_USE_ITEM" in content,
                    f"content: {content}")
        except Exception as e:
            _fail("remove_last_se_constant", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 90: _can_remove_asset for trainer sprites (always allowed)
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            game_dir = os.path.join(tmp_dir, "game")
            os.makedirs(game_dir)
            can, reason = _can_remove_asset("trainer_sprites", "TRAINER_PIC_DAWN", game_dir)
            _assert("can_remove: trainer always True",
                    can is True and reason == "",
                    f"got: can={can}, reason={reason}")
        except Exception as e:
            _fail("can_remove_asset: trainer", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 91: _can_remove_asset for music (only last)
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            game_dir = os.path.join(tmp_dir, "game")
            const_dir = os.path.join(game_dir, "include", "constants")
            os.makedirs(const_dir)
            songs_h = os.path.join(const_dir, "songs.h")
            with open(songs_h, "w") as f:
                f.write("#define MUS_SURF                    350\n")
                f.write("#define MUS_BATTLE                  351\n")
                f.write("#define END_MUS                     MUS_BATTLE\n")
            # Last entry — should be allowed
            can1, _ = _can_remove_asset("music_tracks", "MUS_BATTLE", game_dir)
            _assert("can_remove: music last entry allowed",
                    can1 is True,
                    f"got: {can1}")
            # Non-last — should be refused
            can2, reason2 = _can_remove_asset("music_tracks", "MUS_SURF", game_dir)
            _assert("can_remove: music non-last refused",
                    can2 is False and "positional" in reason2,
                    f"got: can={can2}, reason={reason2}")
        except Exception as e:
            _fail("can_remove_asset: music", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Per-type removal ───────────────────────────────────────────

    try:
        from torch.asset_manager import _remove_trainer_sprite
    except ImportError as e:
        _skip("removal tests", f"import failed: {e}")
        _remove_trainer_sprite = None

    if _remove_trainer_sprite is not None:

        # Test 92: _remove_trainer_sprite removes all registrations
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            game_dir = os.path.join(tmp_dir, "game")
            # Create sprite file
            front_dir = os.path.join(game_dir, "graphics", "trainers", "front_pics")
            os.makedirs(front_dir)
            with open(os.path.join(front_dir, "rival_dawn.png"), "wb") as f:
                f.write(b"fake png")
            with open(os.path.join(front_dir, "rival_dawn.gbapal"), "wb") as f:
                f.write(b"fake pal")

            # Create trainers.h with INCBIN + TRAINER_SPRITE
            trainers_h_dir = os.path.join(game_dir, "src", "data", "graphics")
            os.makedirs(trainers_h_dir)
            trainers_h = os.path.join(trainers_h_dir, "trainers.h")
            with open(trainers_h, "w") as f:
                f.write('const u32 gTrainerFrontPic_RivalDawn[] = INCBIN_U32("...");\n')
                f.write('const u16 gTrainerPalette_RivalDawn[] = INCBIN_U16("...");\n')
                f.write('const u32 gTrainerFrontPic_Other[] = INCBIN_U32("...");\n')
                f.write("const struct TrainerSprite gTrainerSprites[] = {\n")
                f.write("    TRAINER_SPRITE(TRAINER_PIC_RIVAL_DAWN, gTrainerFrontPic_RivalDawn, gTrainerPalette_RivalDawn),\n")
                f.write("    TRAINER_SPRITE(TRAINER_PIC_OTHER, gTrainerFrontPic_Other, gTrainerPalette_Other),\n")
                f.write("};\n")

            # Create constants/trainers.h
            const_dir = os.path.join(game_dir, "include", "constants")
            os.makedirs(const_dir)
            trainers_const = os.path.join(const_dir, "trainers.h")
            with open(trainers_const, "w") as f:
                f.write("#define TRAINER_PIC_RIVAL_DAWN      10\n")
                f.write("#define TRAINER_PIC_OTHER           11\n")
                f.write("#define TRAINER_PIC_COUNT           12\n")

            errors = _remove_trainer_sprite("TRAINER_PIC_RIVAL_DAWN", game_dir)
            _assert("remove_trainer: no errors",
                    len(errors) == 0,
                    f"errors: {errors}")

            # Check files deleted
            _assert("remove_trainer: png deleted",
                    not os.path.exists(os.path.join(front_dir, "rival_dawn.png")),
                    "png still exists")
            _assert("remove_trainer: gbapal deleted",
                    not os.path.exists(os.path.join(front_dir, "rival_dawn.gbapal")),
                    "gbapal still exists")

            # Check INCBIN lines removed
            with open(trainers_h) as f:
                content = f.read()
            _assert("remove_trainer: INCBIN removed",
                    "RivalDawn" not in content,
                    f"content: {content}")
            _assert("remove_trainer: other preserved",
                    "gTrainerFrontPic_Other" in content,
                    f"content: {content}")

            # Check constant removed and count decremented
            with open(trainers_const) as f:
                content = f.read()
            _assert("remove_trainer: constant removed",
                    "TRAINER_PIC_RIVAL_DAWN" not in content,
                    f"content: {content}")
            _assert("remove_trainer: count decremented",
                    "11" in content,  # was 12, now 11
                    f"content: {content}")
        except Exception as e:
            _fail("remove_trainer_sprite", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Sync scanner ───────────────────────────────────────────────

    try:
        from torch.asset_manager import _scan_sync_status, ASSET_TYPES
    except ImportError as e:
        _skip("sync scanner tests", f"import failed: {e}")
        _scan_sync_status = None

    if _scan_sync_status is not None:

        # Test 93: sync scanner detects UPDATE when file changes
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            import_base = os.path.join(tmp_dir, "import")
            game_dir = os.path.join(tmp_dir, "game")

            # Create game structure with a registered trainer sprite
            const_dir = os.path.join(game_dir, "include", "constants")
            os.makedirs(const_dir)
            with open(os.path.join(const_dir, "trainers.h"), "w") as f:
                f.write("#define TRAINER_PIC_RIVAL_DAWN      10\n")
                f.write("#define TRAINER_PIC_COUNT           11\n")

            # Create the game-side sprite (version A)
            front_dir = os.path.join(game_dir, "graphics", "trainers", "front_pics")
            os.makedirs(front_dir)
            data_a = _make_png(64, 64, 8, 3, 16, trns=False)
            with open(os.path.join(front_dir, "rival_dawn.png"), "wb") as f:
                f.write(data_a)

            # Create import dir with a different version (version B)
            trainer_import = os.path.join(import_base, "trainer_sprites")
            os.makedirs(trainer_import)
            data_b = _make_png(64, 64, 8, 3, 8, trns=False)  # different palette size
            with open(os.path.join(trainer_import, "rival_dawn.png"), "wb") as f:
                f.write(data_b)

            # Create empty dirs for other types
            for key in ASSET_TYPES:
                d = os.path.join(import_base, ASSET_TYPES[key]["import_dir"])
                os.makedirs(d, exist_ok=True)

            status = _scan_sync_status(import_base, game_dir)
            _assert("sync scanner: detects update",
                    "trainer_sprites" in status
                    and len(status["trainer_sprites"]["updates"]) == 1,
                    f"status: {status}")
            if "trainer_sprites" in status:
                fname = status["trainer_sprites"]["updates"][0][0]
                _assert("sync scanner: update filename",
                        fname == "rival_dawn.png",
                        f"got: {fname}")
        except Exception as e:
            _fail("sync scanner: update", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 94: sync scanner detects NEW (unregistered file)
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            import_base = os.path.join(tmp_dir, "import")
            game_dir = os.path.join(tmp_dir, "game")

            # Empty game — no constants
            const_dir = os.path.join(game_dir, "include", "constants")
            os.makedirs(const_dir)
            with open(os.path.join(const_dir, "trainers.h"), "w") as f:
                f.write("#define TRAINER_PIC_COUNT           0\n")

            # Import dir has a file
            trainer_import = os.path.join(import_base, "trainer_sprites")
            os.makedirs(trainer_import)
            with open(os.path.join(trainer_import, "new_char.png"), "wb") as f:
                f.write(_make_png(64, 64, 8, 3, 16))

            for key in ASSET_TYPES:
                d = os.path.join(import_base, ASSET_TYPES[key]["import_dir"])
                os.makedirs(d, exist_ok=True)

            status = _scan_sync_status(import_base, game_dir)
            _assert("sync scanner: detects new",
                    "trainer_sprites" in status
                    and len(status["trainer_sprites"]["new_files"]) == 1,
                    f"status: {status}")
        except Exception as e:
            _fail("sync scanner: new", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 95: sync scanner detects REMOVED (in manifest, not in import dir)
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            import_base = os.path.join(tmp_dir, "import")
            game_dir = os.path.join(tmp_dir, "game")

            # Game has registered constant
            const_dir = os.path.join(game_dir, "include", "constants")
            os.makedirs(const_dir)
            with open(os.path.join(const_dir, "trainers.h"), "w") as f:
                f.write("#define TRAINER_PIC_DELETED_CHAR    5\n")
                f.write("#define TRAINER_PIC_COUNT           6\n")

            # Manifest says we imported it, but file is gone
            os.makedirs(import_base, exist_ok=True)
            mpath = os.path.join(import_base, "imports.manifest")
            with open(mpath, "w") as f:
                f.write("trainer_sprites:deleted_char.png\n")

            for key in ASSET_TYPES:
                d = os.path.join(import_base, ASSET_TYPES[key]["import_dir"])
                os.makedirs(d, exist_ok=True)

            status = _scan_sync_status(import_base, game_dir)
            _assert("sync scanner: detects removal",
                    "trainer_sprites" in status
                    and len(status["trainer_sprites"]["removals"]) == 1,
                    f"status: {status}")
            if "trainer_sprites" in status:
                fname = status["trainer_sprites"]["removals"][0][0]
                _assert("sync scanner: removal filename",
                        fname == "deleted_char.png",
                        f"got: {fname}")
        except Exception as e:
            _fail("sync scanner: removed", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 96: sync scanner reports nothing when in sync
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            import_base = os.path.join(tmp_dir, "import")
            game_dir = os.path.join(tmp_dir, "game")

            const_dir = os.path.join(game_dir, "include", "constants")
            os.makedirs(const_dir)
            with open(os.path.join(const_dir, "trainers.h"), "w") as f:
                f.write("#define TRAINER_PIC_RIVAL_DAWN      10\n")
                f.write("#define TRAINER_PIC_COUNT           11\n")

            # Same file in both locations
            data = _make_png(64, 64, 8, 3, 16, trns=False)

            front_dir = os.path.join(game_dir, "graphics", "trainers", "front_pics")
            os.makedirs(front_dir)
            with open(os.path.join(front_dir, "rival_dawn.png"), "wb") as f:
                f.write(data)

            trainer_import = os.path.join(import_base, "trainer_sprites")
            os.makedirs(trainer_import)
            with open(os.path.join(trainer_import, "rival_dawn.png"), "wb") as f:
                f.write(data)

            # Manifest records it
            mpath = os.path.join(import_base, "imports.manifest")
            with open(mpath, "w") as f:
                f.write("trainer_sprites:rival_dawn.png\n")

            for key in ASSET_TYPES:
                d = os.path.join(import_base, ASSET_TYPES[key]["import_dir"])
                os.makedirs(d, exist_ok=True)

            status = _scan_sync_status(import_base, game_dir)
            _assert("sync scanner: empty when in sync",
                    status == {},
                    f"status: {status}")
        except Exception as e:
            _fail("sync scanner: in sync", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── dest_from_file ─────────────────────────────────────────────

    # Test 97: dest_from_file produces correct paths
    try:
        at = ASSET_TYPES["trainer_sprites"]
        p = at["dest_from_file"]("rival_dawn.png", "/game")
        _assert("dest_from_file: trainer",
                p == "/game/graphics/trainers/front_pics/rival_dawn.png",
                f"got: {p}")

        at = ASSET_TYPES["overworld_sprites"]
        p = at["dest_from_file"]("my_npc.png", "/game")
        _assert("dest_from_file: overworld",
                p == "/game/graphics/object_events/pics/people/my_npc.png",
                f"got: {p}")

        at = ASSET_TYPES["music_tracks"]
        p = at["dest_from_file"]("battle_theme.mid", "/game")
        _assert("dest_from_file: music",
                p == "/game/sound/songs/midi/mus_battle_theme.mid",
                f"got: {p}")

        at = ASSET_TYPES["sound_effects"]
        p = at["dest_from_file"]("my_sound.s", "/game")
        _assert("dest_from_file: se",
                p == "/game/sound/songs/se_my_sound.s",
                f"got: {p}")
    except Exception as e:
        _fail("dest_from_file", str(e))

    # ── Backfill manifest ──────────────────────────────────────────

    try:
        from torch.asset_manager import _backfill_manifest
    except ImportError as e:
        _skip("backfill manifest tests", f"import failed: {e}")
        _backfill_manifest = None

    if _backfill_manifest is not None:

        # Test 98: backfill populates manifest for existing imports
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            import_base = os.path.join(tmp_dir, "import")
            game_dir = os.path.join(tmp_dir, "game")

            # Game has registered constant
            const_dir = os.path.join(game_dir, "include", "constants")
            os.makedirs(const_dir)
            with open(os.path.join(const_dir, "trainers.h"), "w") as f:
                f.write("#define TRAINER_PIC_RIVAL_DAWN      10\n")
                f.write("#define TRAINER_PIC_COUNT           11\n")

            # Import dir has the file
            trainer_import = os.path.join(import_base, "trainer_sprites")
            os.makedirs(trainer_import)
            with open(os.path.join(trainer_import, "rival_dawn.png"), "wb") as f:
                f.write(_make_png(64, 64, 8, 3, 16))

            for key in ASSET_TYPES:
                d = os.path.join(import_base, ASSET_TYPES[key]["import_dir"])
                os.makedirs(d, exist_ok=True)

            manifest = _backfill_manifest(import_base, game_dir)
            _assert("backfill: populates manifest",
                    "trainer_sprites" in manifest
                    and "rival_dawn.png" in manifest["trainer_sprites"],
                    f"manifest: {manifest}")

            # File should be written
            m2 = _read_manifest(import_base)
            _assert("backfill: written to disk",
                    "trainer_sprites" in m2
                    and "rival_dawn.png" in m2["trainer_sprites"],
                    f"m2: {m2}")
        except Exception as e:
            _fail("backfill_manifest", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Build artifact cleanup ─────────────────────────────────────

    try:
        from torch.asset_manager import _delete_build_artifacts
    except ImportError as e:
        _skip("build artifact tests", f"import failed: {e}")
        _delete_build_artifacts = None

    if _delete_build_artifacts is not None:

        # Test 99: deletes .4bpp and .4bpp.smol artifacts
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            png_path = os.path.join(tmp_dir, "rival_dawn.png")
            bpp_path = os.path.join(tmp_dir, "rival_dawn.4bpp")
            smol_path = os.path.join(tmp_dir, "rival_dawn.4bpp.smol")
            with open(png_path, "wb") as f:
                f.write(b"png data")
            with open(bpp_path, "wb") as f:
                f.write(b"4bpp data")
            with open(smol_path, "wb") as f:
                f.write(b"smol data")
            deleted = _delete_build_artifacts(png_path)
            _assert("delete_artifacts: .4bpp removed",
                    not os.path.exists(bpp_path),
                    "4bpp still exists")
            _assert("delete_artifacts: .4bpp.smol removed",
                    not os.path.exists(smol_path),
                    "smol still exists")
            _assert("delete_artifacts: png preserved",
                    os.path.exists(png_path),
                    "png was deleted")
            _assert("delete_artifacts: returns deleted paths",
                    len(deleted) == 2,
                    f"got: {deleted}")
        except Exception as e:
            _fail("delete_build_artifacts", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 100: no-op when no artifacts exist
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            png_path = os.path.join(tmp_dir, "clean.png")
            with open(png_path, "wb") as f:
                f.write(b"png data")
            deleted = _delete_build_artifacts(png_path)
            _assert("delete_artifacts: empty when none exist",
                    deleted == [],
                    f"got: {deleted}")
        except Exception as e:
            _fail("delete_build_artifacts: no-op", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Stale artifact detection ───────────────────────────────────

    try:
        from torch.asset_manager import _has_stale_artifacts
    except ImportError as e:
        _skip("stale artifact tests", f"import failed: {e}")
        _has_stale_artifacts = None

    if _has_stale_artifacts is not None:

        # Test 101: detects .4bpp older than .png
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            png_path = os.path.join(tmp_dir, "rival.png")
            bpp_path = os.path.join(tmp_dir, "rival.4bpp")
            # Create .4bpp first (older), then PNG (newer)
            with open(bpp_path, "wb") as f:
                f.write(b"4bpp data")
            old_time = os.path.getmtime(bpp_path) - 10
            os.utime(bpp_path, (old_time, old_time))
            with open(png_path, "wb") as f:
                f.write(b"png data")
            _assert("has_stale_artifacts: True when .4bpp older than .png",
                    _has_stale_artifacts(png_path) is True,
                    "expected True")
        except Exception as e:
            _fail("has_stale_artifacts: exists", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 101b: .4bpp newer than .png is NOT stale
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            png_path = os.path.join(tmp_dir, "rival.png")
            bpp_path = os.path.join(tmp_dir, "rival.4bpp")
            with open(png_path, "wb") as f:
                f.write(b"png data")
            old_time = os.path.getmtime(png_path) - 10
            os.utime(png_path, (old_time, old_time))
            with open(bpp_path, "wb") as f:
                f.write(b"4bpp data")
            _assert("has_stale_artifacts: False when .4bpp newer than .png",
                    _has_stale_artifacts(png_path) is False,
                    "expected False — .4bpp is from a successful build")
        except Exception as e:
            _fail("has_stale_artifacts: newer", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 102: no stale when no artifacts exist
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            png_path = os.path.join(tmp_dir, "clean.png")
            with open(png_path, "wb") as f:
                f.write(b"png data")
            _assert("has_stale_artifacts: False when no artifacts",
                    _has_stale_artifacts(png_path) is False,
                    "expected False")
        except Exception as e:
            _fail("has_stale_artifacts: clean", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 103: detects .4bpp.smol older than .png
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            png_path = os.path.join(tmp_dir, "rival.png")
            smol_path = os.path.join(tmp_dir, "rival.4bpp.smol")
            # Create .smol first (older), then PNG (newer)
            with open(smol_path, "wb") as f:
                f.write(b"smol data")
            old_time = os.path.getmtime(smol_path) - 10
            os.utime(smol_path, (old_time, old_time))
            with open(png_path, "wb") as f:
                f.write(b"png data")
            _assert("has_stale_artifacts: True when .4bpp.smol older than .png",
                    _has_stale_artifacts(png_path) is True,
                    "expected True")
        except Exception as e:
            _fail("has_stale_artifacts: smol", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Sync scanner: stale artifact detection ─────────────────────

    if _scan_sync_status is not None and _has_stale_artifacts is not None:

        # Test 104: sync scanner detects STALE artifacts for manifest-tracked files
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            import_base = os.path.join(tmp_dir, "import")
            game_dir = os.path.join(tmp_dir, "game")

            # Game has registered trainer sprite
            const_dir = os.path.join(game_dir, "include", "constants")
            os.makedirs(const_dir)
            with open(os.path.join(const_dir, "trainers.h"), "w") as f:
                f.write("#define TRAINER_PIC_RIVAL_DAWN      10\n")
                f.write("#define TRAINER_PIC_COUNT           11\n")

            # Create matching PNG + a .4bpp artifact that is older than the PNG
            front_dir = os.path.join(game_dir, "graphics", "trainers", "front_pics")
            os.makedirs(front_dir)
            data = _make_png(64, 64, 8, 3, 16, trns=False)
            bpp_path = os.path.join(front_dir, "rival_dawn.4bpp")
            with open(bpp_path, "wb") as f:
                f.write(b"cached 4bpp")
            # Make .4bpp older than the PNG
            old_time = os.path.getmtime(bpp_path) - 10
            os.utime(bpp_path, (old_time, old_time))
            with open(os.path.join(front_dir, "rival_dawn.png"), "wb") as f:
                f.write(data)

            trainer_import = os.path.join(import_base, "trainer_sprites")
            os.makedirs(trainer_import)
            with open(os.path.join(trainer_import, "rival_dawn.png"), "wb") as f:
                f.write(data)

            # Manifest tracks this file — stale detection applies
            mpath = os.path.join(import_base, "imports.manifest")
            with open(mpath, "w") as f:
                f.write("trainer_sprites:rival_dawn.png\n")

            for key in ASSET_TYPES:
                d = os.path.join(import_base, ASSET_TYPES[key]["import_dir"])
                os.makedirs(d, exist_ok=True)

            status = _scan_sync_status(import_base, game_dir)
            _assert("sync scanner: detects stale artifacts",
                    "trainer_sprites" in status
                    and len(status["trainer_sprites"]["stale"]) == 1,
                    f"status: {status}")
            _assert("sync scanner: stale has no updates",
                    "trainer_sprites" in status
                    and len(status["trainer_sprites"]["updates"]) == 0,
                    f"updates: {status.get('trainer_sprites', {}).get('updates', [])}")
        except Exception as e:
            _fail("sync scanner: stale", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Test 105: scanner ignores .4bpp for vanilla assets (not in import dir)
        tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
        try:
            import_base = os.path.join(tmp_dir, "import")
            game_dir = os.path.join(tmp_dir, "game")

            # Game has a vanilla sprite with .4bpp (not TORCH-imported)
            const_dir = os.path.join(game_dir, "include", "constants")
            os.makedirs(const_dir)
            with open(os.path.join(const_dir, "trainers.h"), "w") as f:
                f.write("#define TRAINER_PIC_BEAUTY          10\n")
                f.write("#define TRAINER_PIC_COUNT           11\n")

            front_dir = os.path.join(game_dir, "graphics", "trainers", "front_pics")
            os.makedirs(front_dir)
            with open(os.path.join(front_dir, "beauty.png"), "wb") as f:
                f.write(_make_png(64, 64, 8, 3, 16, trns=False))
            with open(os.path.join(front_dir, "beauty.4bpp"), "wb") as f:
                f.write(b"vanilla 4bpp")

            # Import dir is empty — no TORCH-imported files
            for key in ASSET_TYPES:
                d = os.path.join(import_base, ASSET_TYPES[key]["import_dir"])
                os.makedirs(d, exist_ok=True)

            status = _scan_sync_status(import_base, game_dir)
            # Should not flag stale — beauty is vanilla, not in import dir
            _assert("sync scanner: no stale for vanilla sprite",
                    status == {},
                    f"status: {status}")
        except Exception as e:
            _fail("sync scanner: no stale for vanilla", str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Custom palette extraction ────────────────────────────────────

    # Test 106: _extract_gbapal_from_png produces correct 32-byte file
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _extract_gbapal_from_png
        # Create PNG with known palette: index 0 = black, index 1 = pure red (255,0,0)
        # GBA BGR555 for red: R=31, G=0, B=0 -> 0x001F (little-endian: 1F 00)
        colors = [(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)]
        png_path = os.path.join(tmp_dir, "test.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(16, 16, 8, 3, 16, palette_colors=colors))
        gbapal_path = os.path.join(tmp_dir, "test.gbapal")
        ok = _extract_gbapal_from_png(png_path, gbapal_path)
        _assert("gbapal extract: succeeds", ok is True, f"ok={ok}")
        with open(gbapal_path, "rb") as f:
            data = f.read()
        _assert("gbapal extract: 32 bytes", len(data) == 32, f"len={len(data)}")
        # Check color 0 (black): 0x0000
        c0 = struct.unpack_from("<H", data, 0)[0]
        _assert("gbapal extract: color 0 is black", c0 == 0x0000, f"c0=0x{c0:04X}")
        # Check color 1 (red 255,0,0 -> R=31,G=0,B=0 -> 0x001F)
        c1 = struct.unpack_from("<H", data, 2)[0]
        _assert("gbapal extract: color 1 is red", c1 == 0x001F, f"c1=0x{c1:04X}")
        # Check color 2 (green 0,255,0 -> R=0,G=31,B=0 -> 0x03E0)
        c2 = struct.unpack_from("<H", data, 4)[0]
        _assert("gbapal extract: color 2 is green", c2 == 0x03E0, f"c2=0x{c2:04X}")
        # Check color 3 (blue 0,0,255 -> R=0,G=0,B=31 -> 0x7C00)
        c3 = struct.unpack_from("<H", data, 6)[0]
        _assert("gbapal extract: color 3 is blue", c3 == 0x7C00, f"c3=0x{c3:04X}")
    except Exception as e:
        _fail("gbapal extraction", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 107: _extract_jasc_pal_from_png produces correct JASC-PAL file
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _extract_jasc_pal_from_png
        colors = [(128, 64, 32), (200, 100, 50)]
        png_path = os.path.join(tmp_dir, "test.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(16, 16, 8, 3, 16, palette_colors=colors))
        pal_path = os.path.join(tmp_dir, "test.pal")
        ok = _extract_jasc_pal_from_png(png_path, pal_path)
        _assert("jasc pal extract: succeeds", ok is True, f"ok={ok}")
        with open(pal_path) as f:
            content = f.read()
        _assert("jasc pal: has header", content.startswith("JASC-PAL"), f"start={content[:20]}")
        _assert("jasc pal: has color 0", "128 64 32" in content, "missing color 0")
        _assert("jasc pal: has color 1", "200 100 50" in content, "missing color 1")
        # Text mode on Linux converts \r\n to \n — count non-empty lines
        lines = [l for l in content.strip().splitlines() if l.strip()]
        _assert("jasc pal: 19 lines (header + 16 colors)", len(lines) == 19,
                f"lines={len(lines)}")
    except Exception as e:
        _fail("jasc pal extraction", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Palette tag allocation ───────────────────────────────────────

    # Test 108: _next_palette_tag_value finds next after DYNAMIC
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _next_palette_tag_value
        eo_h = os.path.join(tmp_dir, "event_objects.h")
        with open(eo_h, "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_NPC_1    0x1103\n")
            f.write("#define OBJ_EVENT_PAL_TAG_DYNAMIC  0x1124\n")
            f.write("#define OBJ_EVENT_PAL_TAG_NONE     0x11FF\n")
        val = _next_palette_tag_value(eo_h)
        _assert("next pal tag: is 0x1125", val == "0x1125", f"val={val}")
    except Exception as e:
        _fail("next palette tag value", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 109: _next_palette_tag_value accounts for existing custom tags
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _next_palette_tag_value
        eo_h = os.path.join(tmp_dir, "event_objects.h")
        with open(eo_h, "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_DYNAMIC     0x1124\n")
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_M    0x1125\n")
            f.write("#define OBJ_EVENT_PAL_TAG_NONE        0x11FF\n")
        val = _next_palette_tag_value(eo_h)
        _assert("next pal tag: skips existing", val == "0x1126", f"val={val}")
    except Exception as e:
        _fail("next palette tag value with existing", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Palette tag define insertion ─────────────────────────────────

    # Test 110: _insert_palette_tag_define inserts before DYNAMIC
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _insert_palette_tag_define
        eo_h = os.path.join(tmp_dir, "event_objects.h")
        with open(eo_h, "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_RS_MAY      0x1123\n")
            f.write("#define OBJ_EVENT_PAL_TAG_DYNAMIC     0x1124\n")
            f.write("\n")
            f.write("#define OBJ_EVENT_PAL_TAG_NONE        0x11FF\n")
        ok = _insert_palette_tag_define(eo_h, "OBJ_EVENT_PAL_TAG_ROCKET_M", "0x1125")
        _assert("pal tag define: succeeds", ok is True, f"ok={ok}")
        with open(eo_h) as f:
            content = f.read()
        _assert("pal tag define: present",
                "OBJ_EVENT_PAL_TAG_ROCKET_M" in content,
                "tag not found")
        # Check it's before DYNAMIC
        lines = content.split("\n")
        rocket_idx = next(i for i, l in enumerate(lines) if "ROCKET_M" in l)
        dynamic_idx = next(i for i, l in enumerate(lines) if "DYNAMIC" in l)
        _assert("pal tag define: before DYNAMIC",
                rocket_idx < dynamic_idx,
                f"rocket={rocket_idx} dynamic={dynamic_idx}")
    except Exception as e:
        _fail("palette tag define insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Palette INCBIN insertion ─────────────────────────────────────

    # Test 111: _insert_palette_incbin adds after last palette INCBIN
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _insert_palette_incbin
        gfx_h = os.path.join(tmp_dir, "object_event_graphics.h")
        with open(gfx_h, "w") as f:
            f.write('const u16 gObjectEventPal_Npc1[] = INCBIN_U16("graphics/object_events/palettes/npc_1.gbapal");\n')
            f.write('const u16 gObjectEventPal_Npc4[] = INCBIN_U16("graphics/object_events/palettes/npc_4.gbapal");\n')
            f.write('const u32 gObjectEventPic_NinjaBoy[] = INCBIN_U32("graphics/object_events/pics/people/ninja_boy.4bpp");\n')
        ok = _insert_palette_incbin(gfx_h, "RocketM", "rocket_m")
        _assert("pal incbin: succeeds", ok is True, f"ok={ok}")
        with open(gfx_h) as f:
            content = f.read()
        _assert("pal incbin: present",
                'gObjectEventPal_RocketM[] = INCBIN_U16("graphics/object_events/palettes/rocket_m.gbapal")' in content,
                "INCBIN not found")
        # Should be after Npc4, before NinjaBoy
        lines = content.split("\n")
        pal_idx = next(i for i, l in enumerate(lines) if "RocketM" in l)
        ninja_idx = next(i for i, l in enumerate(lines) if "NinjaBoy" in l)
        _assert("pal incbin: before pic lines",
                pal_idx < ninja_idx,
                f"pal={pal_idx} ninja={ninja_idx}")
    except Exception as e:
        _fail("palette INCBIN insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Palette table entry insertion ────────────────────────────────

    # Test 112: _insert_palette_table_entry adds before pokeball block
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _insert_palette_table_entry
        mov_c = os.path.join(tmp_dir, "event_object_movement.c")
        with open(mov_c, "w") as f:
            f.write("static const struct SpritePalette sObjectEventSpritePalettes[] = {\n")
            f.write("    {gObjectEventPal_Npc1,    OBJ_EVENT_PAL_TAG_NPC_1},\n")
            f.write("    {gObjectEventPal_RubySapphireMay, OBJ_EVENT_PAL_TAG_RS_MAY},\n")
            f.write("#if OW_FOLLOWERS_POKEBALLS\n")
            f.write("    {gObjectEventPal_MasterBall, OBJ_EVENT_PAL_TAG_BALL_MASTER},\n")
            f.write("#endif\n")
            f.write("    {gObjectEventPal_Substitute, OBJ_EVENT_PAL_TAG_SUBSTITUTE},\n")
            f.write("    {NULL, OBJ_EVENT_PAL_TAG_NONE},\n")
            f.write("};\n")
        ok = _insert_palette_table_entry(mov_c, "RocketM", "OBJ_EVENT_PAL_TAG_ROCKET_M")
        _assert("pal table entry: succeeds", ok is True, f"ok={ok}")
        with open(mov_c) as f:
            content = f.read()
        _assert("pal table entry: present",
                "gObjectEventPal_RocketM," in content and "OBJ_EVENT_PAL_TAG_ROCKET_M" in content,
                "entry not found")
        # Should be before pokeball block
        lines = content.split("\n")
        rocket_idx = next(i for i, l in enumerate(lines) if "RocketM" in l)
        poke_idx = next(i for i, l in enumerate(lines) if "OW_FOLLOWERS_POKEBALLS" in l)
        _assert("pal table entry: before pokeball block",
                rocket_idx < poke_idx,
                f"rocket={rocket_idx} poke={poke_idx}")
    except Exception as e:
        _fail("palette table entry insertion", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Palette name derivation ──────────────────────────────────────

    # Test 113: _derive_palette_tag_name and _derive_palette_data_name
    try:
        from torch.asset_manager import _derive_palette_tag_name, _derive_palette_data_name
        _assert("pal tag name: RocketM",
                _derive_palette_tag_name("RocketM") == "OBJ_EVENT_PAL_TAG_ROCKET_M",
                f"got: {_derive_palette_tag_name('RocketM')}")
        _assert("pal data name: RocketM",
                _derive_palette_data_name("RocketM") == "gObjectEventPal_RocketM",
                f"got: {_derive_palette_data_name('RocketM')}")
    except Exception as e:
        _fail("palette name derivation", str(e))

    # ── Graphics info with custom palette ────────────────────────────

    # Test 114: _insert_overworld_graphics_info uses custom palette tag
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _insert_overworld_graphics_info
        info_h = os.path.join(tmp_dir, "object_event_graphics_info.h")
        with open(info_h, "w") as f:
            f.write("const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_Boy1 = {\n")
            f.write("    .tileTag = TAG_NONE,\n")
            f.write("    .images = sPicTable_Boy1,\n")
            f.write("};\n")
        ok = _insert_overworld_graphics_info(
            info_h, "RocketM", 16, 32,
            palette_tag="OBJ_EVENT_PAL_TAG_ROCKET_M",
            palette_slot="PALSLOT_NPC_SPECIAL")
        _assert("gfx info custom pal: succeeds", ok is True, f"ok={ok}")
        with open(info_h) as f:
            content = f.read()
        _assert("gfx info custom pal: has custom tag",
                "OBJ_EVENT_PAL_TAG_ROCKET_M" in content,
                "custom tag not found")
        _assert("gfx info custom pal: uses PALSLOT_NPC_SPECIAL",
                "PALSLOT_NPC_SPECIAL" in content,
                "not using PALSLOT_NPC_SPECIAL")
        _assert("gfx info custom pal: no NPC_1 fallback",
                "OBJ_EVENT_PAL_TAG_NPC_1" not in content,
                "still using NPC_1")
    except Exception as e:
        _fail("graphics info with custom palette", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 115: _insert_overworld_graphics_info defaults to NPC_1 without palette_tag
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _insert_overworld_graphics_info
        info_h = os.path.join(tmp_dir, "object_event_graphics_info.h")
        with open(info_h, "w") as f:
            f.write("const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_Boy1 = {\n")
            f.write("    .tileTag = TAG_NONE,\n")
            f.write("};\n")
        ok = _insert_overworld_graphics_info(info_h, "TestNpc", 16, 32)
        _assert("gfx info default pal: succeeds", ok is True, f"ok={ok}")
        with open(info_h) as f:
            content = f.read()
        _assert("gfx info default pal: uses NPC_1",
                "OBJ_EVENT_PAL_TAG_NPC_1" in content,
                "not using NPC_1 default")
        _assert("gfx info default pal: uses PALSLOT_NPC_1",
                "PALSLOT_NPC_1" in content,
                "not using PALSLOT_NPC_1")
    except Exception as e:
        _fail("graphics info default palette", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Removal cleans up palette ────────────────────────────────────

    # Test 116: _remove_overworld_sprite cleans up palette registrations
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _remove_overworld_sprite
        game_dir = os.path.join(tmp_dir, "game")

        # Create minimal game structure with palette registrations
        eo_h = os.path.join(game_dir, "include", "constants", "event_objects.h")
        os.makedirs(os.path.dirname(eo_h))
        with open(eo_h, "w") as f:
            f.write("#define OBJ_EVENT_GFX_ROCKET_M       42\n")
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_M   0x1125\n")
            f.write("#define NUM_OBJ_EVENT_GFX            43\n")

        gfx_h = os.path.join(game_dir, "src", "data", "object_events", "object_event_graphics.h")
        os.makedirs(os.path.dirname(gfx_h))
        with open(gfx_h, "w") as f:
            f.write('const u32 gObjectEventPic_RocketM[] = INCBIN_U32("graphics/object_events/pics/people/rocket_m.4bpp");\n')
            f.write('const u16 gObjectEventPal_RocketM[] = INCBIN_U16("graphics/object_events/palettes/rocket_m.gbapal");\n')

        pt_h = os.path.join(game_dir, "src", "data", "object_events", "object_event_pic_tables.h")
        with open(pt_h, "w") as f:
            f.write("static const struct SpriteFrameImage sPicTable_RocketM[] = {\n")
            f.write("    overworld_ascending_frames(gObjectEventPic_RocketM, 2, 4),\n")
            f.write("};\n")

        info_h = os.path.join(game_dir, "src", "data", "object_events", "object_event_graphics_info.h")
        with open(info_h, "w") as f:
            f.write("const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_RocketM = {\n")
            f.write("    .paletteTag = OBJ_EVENT_PAL_TAG_ROCKET_M,\n")
            f.write("};\n")

        ptrs_h = os.path.join(game_dir, "src", "data", "object_events", "object_event_graphics_info_pointers.h")
        with open(ptrs_h, "w") as f:
            f.write("extern const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_RocketM;\n")
            f.write("const struct ObjectEventGraphicsInfo *const gObjectEventGraphicsInfoPointers[] = {\n")
            f.write("    [OBJ_EVENT_GFX_ROCKET_M] = &gObjectEventGraphicsInfo_RocketM,\n")
            f.write("};\n")

        mov_c = os.path.join(game_dir, "src", "event_object_movement.c")
        with open(mov_c, "w") as f:
            f.write("static const struct SpritePalette sObjectEventSpritePalettes[] = {\n")
            f.write("    {gObjectEventPal_RocketM, OBJ_EVENT_PAL_TAG_ROCKET_M},\n")
            f.write("    {NULL, OBJ_EVENT_PAL_TAG_NONE},\n")
            f.write("};\n")

        # Create sprite + palette files
        sprite_dir = os.path.join(game_dir, "graphics", "object_events", "pics", "people")
        os.makedirs(sprite_dir)
        with open(os.path.join(sprite_dir, "rocket_m.png"), "wb") as f:
            f.write(_make_png(144, 32, 8, 3, 16))

        pal_dir = os.path.join(game_dir, "graphics", "object_events", "palettes")
        os.makedirs(pal_dir)
        with open(os.path.join(pal_dir, "rocket_m.gbapal"), "wb") as f:
            f.write(b"\x00" * 32)
        with open(os.path.join(pal_dir, "rocket_m.pal"), "w") as f:
            f.write("JASC-PAL\r\n0100\r\n16\r\n")

        errors = _remove_overworld_sprite("OBJ_EVENT_GFX_ROCKET_M", game_dir)
        _assert("ow removal pal: no errors", errors == [], f"errors={errors}")

        # Check palette files deleted
        _assert("ow removal pal: gbapal deleted",
                not os.path.exists(os.path.join(pal_dir, "rocket_m.gbapal")),
                "gbapal still exists")
        _assert("ow removal pal: pal deleted",
                not os.path.exists(os.path.join(pal_dir, "rocket_m.pal")),
                "pal still exists")

        # Check palette tag define removed
        with open(eo_h) as f:
            eo_content = f.read()
        _assert("ow removal pal: tag define removed",
                "OBJ_EVENT_PAL_TAG_ROCKET_M" not in eo_content,
                "tag define still present")

        # Check palette table entry removed
        with open(mov_c) as f:
            mov_content = f.read()
        _assert("ow removal pal: table entry removed",
                "gObjectEventPal_RocketM" not in mov_content,
                "table entry still present")

        # Check palette INCBIN removed
        with open(gfx_h) as f:
            gfx_content = f.read()
        _assert("ow removal pal: INCBIN removed",
                "gObjectEventPal_RocketM" not in gfx_content,
                "palette INCBIN still present")
    except Exception as e:
        _fail("overworld removal with palette cleanup", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 116b: removing sprite that shares another's palette preserves it
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _remove_overworld_sprite
        game_dir = os.path.join(tmp_dir, "game")

        # RocketM owns the palette, RocketF shares it
        eo_h = os.path.join(game_dir, "include", "constants", "event_objects.h")
        os.makedirs(os.path.dirname(eo_h))
        with open(eo_h, "w") as f:
            f.write("#define OBJ_EVENT_GFX_ROCKET_M       42\n")
            f.write("#define OBJ_EVENT_GFX_ROCKET_F       43\n")
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_M   0x1125\n")
            f.write("#define NUM_OBJ_EVENT_GFX            44\n")

        gfx_h = os.path.join(game_dir, "src", "data", "object_events", "object_event_graphics.h")
        os.makedirs(os.path.dirname(gfx_h))
        with open(gfx_h, "w") as f:
            f.write('const u32 gObjectEventPic_RocketM[] = INCBIN_U32("graphics/object_events/pics/people/rocket_m.4bpp");\n')
            f.write('const u32 gObjectEventPic_RocketF[] = INCBIN_U32("graphics/object_events/pics/people/rocket_f.4bpp");\n')
            f.write('const u16 gObjectEventPal_RocketM[] = INCBIN_U16("graphics/object_events/palettes/rocket_m.gbapal");\n')

        pt_h = os.path.join(game_dir, "src", "data", "object_events", "object_event_pic_tables.h")
        with open(pt_h, "w") as f:
            f.write("static const struct SpriteFrameImage sPicTable_RocketF[] = {\n")
            f.write("    overworld_ascending_frames(gObjectEventPic_RocketF, 2, 4),\n")
            f.write("};\n")

        # Both structs reference RocketM's palette tag
        info_h = os.path.join(game_dir, "src", "data", "object_events", "object_event_graphics_info.h")
        with open(info_h, "w") as f:
            f.write("const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_RocketM = {\n")
            f.write("    .paletteTag = OBJ_EVENT_PAL_TAG_ROCKET_M,\n")
            f.write("};\n")
            f.write("const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_RocketF = {\n")
            f.write("    .paletteTag = OBJ_EVENT_PAL_TAG_ROCKET_M,\n")
            f.write("};\n")

        ptrs_h = os.path.join(game_dir, "src", "data", "object_events", "object_event_graphics_info_pointers.h")
        with open(ptrs_h, "w") as f:
            f.write("extern const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_RocketM;\n")
            f.write("extern const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_RocketF;\n")
            f.write("const struct ObjectEventGraphicsInfo *const gObjectEventGraphicsInfoPointers[] = {\n")
            f.write("    [OBJ_EVENT_GFX_ROCKET_M] = &gObjectEventGraphicsInfo_RocketM,\n")
            f.write("    [OBJ_EVENT_GFX_ROCKET_F] = &gObjectEventGraphicsInfo_RocketF,\n")
            f.write("};\n")

        mov_c = os.path.join(game_dir, "src", "event_object_movement.c")
        with open(mov_c, "w") as f:
            f.write("static const struct SpritePalette sObjectEventSpritePalettes[] = {\n")
            f.write("    {gObjectEventPal_RocketM, OBJ_EVENT_PAL_TAG_ROCKET_M},\n")
            f.write("    {NULL, OBJ_EVENT_PAL_TAG_NONE},\n")
            f.write("};\n")

        sprite_dir = os.path.join(game_dir, "graphics", "object_events", "pics", "people")
        os.makedirs(sprite_dir)
        with open(os.path.join(sprite_dir, "rocket_f.png"), "wb") as f:
            f.write(_make_png(144, 32, 8, 3, 16))

        pal_dir = os.path.join(game_dir, "graphics", "object_events", "palettes")
        os.makedirs(pal_dir)
        with open(os.path.join(pal_dir, "rocket_m.gbapal"), "wb") as f:
            f.write(b"\x00" * 32)

        # Remove RocketF (which uses RocketM's palette)
        errors = _remove_overworld_sprite("OBJ_EVENT_GFX_ROCKET_F", game_dir)
        _assert("ow removal shared pal: no errors", errors == [], f"errors={errors}")

        # RocketM's palette must be preserved
        with open(eo_h) as f:
            eo_content = f.read()
        _assert("ow removal shared pal: keeper tag preserved",
                "OBJ_EVENT_PAL_TAG_ROCKET_M" in eo_content,
                "keeper tag was wrongly removed")

        with open(mov_c) as f:
            mov_content = f.read()
        _assert("ow removal shared pal: keeper table preserved",
                "gObjectEventPal_RocketM" in mov_content,
                "keeper table entry was wrongly removed")

        with open(gfx_h) as f:
            gfx_content = f.read()
        _assert("ow removal shared pal: keeper INCBIN preserved",
                "gObjectEventPal_RocketM" in gfx_content,
                "keeper INCBIN was wrongly removed")

        _assert("ow removal shared pal: keeper gbapal preserved",
                os.path.exists(os.path.join(pal_dir, "rocket_m.gbapal")),
                "keeper gbapal was wrongly deleted")

        # RocketF's sprite should be removed
        _assert("ow removal shared pal: sprite removed",
                "gObjectEventPic_RocketF" not in gfx_content,
                "sprite INCBIN still present")
    except Exception as e:
        _fail("ow removal shared palette", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Update palette files ─────────────────────────────────────────

    # Test 117: _update_palette_files refreshes gbapal from source PNG
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        from torch.asset_manager import _update_palette_files
        game_dir = os.path.join(tmp_dir, "game")
        pal_dir = os.path.join(game_dir, "graphics", "object_events", "palettes")
        inc_dir = os.path.join(game_dir, "include", "constants")
        os.makedirs(pal_dir)
        os.makedirs(inc_dir)

        # Register the custom palette tag so _has_own_custom_palette returns True
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_M 0x1125\n")

        # Write old palette file
        with open(os.path.join(pal_dir, "rocket_m.gbapal"), "wb") as f:
            f.write(b"\xFF" * 32)

        # Create source PNG with known palette
        colors = [(255, 0, 0)]
        png_path = os.path.join(tmp_dir, "rocket_m.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(144, 32, 8, 3, 16, palette_colors=colors))

        _update_palette_files(png_path, "rocket_m.png", game_dir)

        # Verify gbapal was updated (should not be all 0xFF any more)
        with open(os.path.join(pal_dir, "rocket_m.gbapal"), "rb") as f:
            data = f.read()
        _assert("update pal files: gbapal changed",
                data != b"\xFF" * 32,
                "gbapal not updated")
        _assert("update pal files: 32 bytes", len(data) == 32, f"len={len(data)}")

        # Verify .pal was also created
        _assert("update pal files: pal created",
                os.path.exists(os.path.join(pal_dir, "rocket_m.pal")),
                "pal not created")
    except Exception as e:
        _fail("update palette files", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Smart palette matching tests ─────────────────────────────────

    try:
        from torch.asset_manager import (
            _extract_plte_as_bgr555,
            _palettes_match,
            _read_gbapal_file,
            _find_matching_palette,
            _find_palette_slot_for_tag,
            _has_own_custom_palette,
        )
    except ImportError as e:
        _skip("palette matching tests", f"import failed: {e}")
        return

    # Test 118: _extract_plte_as_bgr555 — basic extraction
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        png_path = os.path.join(tmp_dir, "test.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(32, 32, 8, 3, 16, palette_colors=colors))
        pal, count = _extract_plte_as_bgr555(png_path)
        _assert("plte bgr555: returns bytearray",
                pal is not None and isinstance(pal, bytearray),
                f"got: {type(pal)}")
        _assert("plte bgr555: 32 bytes", len(pal) == 32, f"len={len(pal)}")
        _assert("plte bgr555: count >= 3", count >= 3, f"count={count}")
        # Verify first real color (index 0 is transparent, index 1 is red)
        # Red (255,0,0) -> r5=31, g5=0, b5=0 -> BGR555 = 0x001F
        r_val = struct.unpack_from("<H", pal, 0)[0]
        _assert("plte bgr555: index 0 is red BGR555",
                r_val == 0x001F, f"got 0x{r_val:04X}")
        # Green (0,255,0) -> r5=0, g5=31, b5=0 -> BGR555 = 0x03E0
        g_val = struct.unpack_from("<H", pal, 2)[0]
        _assert("plte bgr555: index 1 is green BGR555",
                g_val == 0x03E0, f"got 0x{g_val:04X}")
    except Exception as e:
        _fail("plte bgr555 extraction", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 119: _extract_plte_as_bgr555 — non-PNG file
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        bad_path = os.path.join(tmp_dir, "notpng.txt")
        with open(bad_path, "w") as f:
            f.write("not a png")
        pal, count = _extract_plte_as_bgr555(bad_path)
        _assert("plte bgr555: non-PNG returns None",
                pal is None and count == 0,
                f"got: pal={pal}, count={count}")
    except Exception as e:
        _fail("plte bgr555 non-PNG", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 120: _extract_plte_as_bgr555 — missing file
    try:
        pal, count = _extract_plte_as_bgr555("/nonexistent/path.png")
        _assert("plte bgr555: missing file returns None",
                pal is None and count == 0,
                f"got: pal={pal}, count={count}")
    except Exception as e:
        _fail("plte bgr555 missing file", str(e))

    # Test 121: _palettes_match — identical palettes
    try:
        pal_a = bytearray(32)
        pal_b = bytearray(32)
        for i in range(16):
            struct.pack_into("<H", pal_a, i * 2, i * 100)
            struct.pack_into("<H", pal_b, i * 2, i * 100)
        _assert("pal match: identical",
                _palettes_match(pal_a, pal_b, 16, 16),
                "should match")
    except Exception as e:
        _fail("pal match identical", str(e))

    # Test 122: _palettes_match — different at index 1
    try:
        pal_a = bytearray(32)
        pal_b = bytearray(32)
        for i in range(16):
            struct.pack_into("<H", pal_a, i * 2, i * 100)
            struct.pack_into("<H", pal_b, i * 2, i * 100)
        # Change index 1 in pal_b
        struct.pack_into("<H", pal_b, 2, 9999)
        _assert("pal match: differ at index 1",
                not _palettes_match(pal_a, pal_b, 16, 16),
                "should NOT match")
    except Exception as e:
        _fail("pal match differ", str(e))

    # Test 123: _palettes_match — index 0 differs (should still match)
    try:
        pal_a = bytearray(32)
        pal_b = bytearray(32)
        for i in range(16):
            struct.pack_into("<H", pal_a, i * 2, i * 100)
            struct.pack_into("<H", pal_b, i * 2, i * 100)
        # Change index 0 (transparent — should be ignored)
        struct.pack_into("<H", pal_b, 0, 9999)
        _assert("pal match: index 0 ignored",
                _palettes_match(pal_a, pal_b, 16, 16),
                "should match (index 0 is transparent)")
    except Exception as e:
        _fail("pal match index 0", str(e))

    # Test 124: _palettes_match — None inputs
    try:
        pal = bytearray(32)
        _assert("pal match: None pal_a", not _palettes_match(None, pal, 16, 16), "")
        _assert("pal match: None pal_b", not _palettes_match(pal, None, 16, 16), "")
        _assert("pal match: both None", not _palettes_match(None, None, 0, 0), "")
    except Exception as e:
        _fail("pal match None", str(e))

    # Test 125: _palettes_match — different count (shorter matches)
    try:
        pal_a = bytearray(32)
        pal_b = bytearray(32)
        for i in range(8):
            struct.pack_into("<H", pal_a, i * 2, (i + 1) * 50)
            struct.pack_into("<H", pal_b, i * 2, (i + 1) * 50)
        # Extra entries in pal_a at indices 8-15 don't matter
        for i in range(8, 16):
            struct.pack_into("<H", pal_a, i * 2, 7777)
        _assert("pal match: shorter count matches",
                _palettes_match(pal_a, pal_b, 16, 8),
                "should match up to min count")
    except Exception as e:
        _fail("pal match short count", str(e))

    # Test 126: _read_gbapal_file — valid file
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        pal_data = bytearray(32)
        for i in range(8):
            struct.pack_into("<H", pal_data, i * 2, (i + 1) * 100)
        gbapal_path = os.path.join(tmp_dir, "test.gbapal")
        with open(gbapal_path, "wb") as f:
            f.write(pal_data)
        read_pal, read_count = _read_gbapal_file(gbapal_path)
        _assert("read gbapal: valid",
                read_pal is not None and len(read_pal) == 32,
                f"got: {read_pal}")
        _assert("read gbapal: count >= 8",
                read_count >= 8, f"count={read_count}")
    except Exception as e:
        _fail("read gbapal valid", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 127: _read_gbapal_file — missing file
    try:
        pal, count = _read_gbapal_file("/nonexistent.gbapal")
        _assert("read gbapal: missing",
                pal is None and count == 0, "")
    except Exception as e:
        _fail("read gbapal missing", str(e))

    # Test 128: _read_gbapal_file — wrong size
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        bad_path = os.path.join(tmp_dir, "bad.gbapal")
        with open(bad_path, "wb") as f:
            f.write(b"\x00" * 16)  # only 16 bytes, not 32
        pal, count = _read_gbapal_file(bad_path)
        _assert("read gbapal: wrong size",
                pal is None and count == 0, "")
    except Exception as e:
        _fail("read gbapal wrong size", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 129: _find_palette_slot_for_tag — finds matching slot
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        info_h = os.path.join(tmp_dir, "info.h")
        with open(info_h, "w") as f:
            f.write(
                "const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_RocketM = {\n"
                "    .tileTag = TAG_NONE,\n"
                "    .paletteTag = OBJ_EVENT_PAL_TAG_ROCKET_M,\n"
                "    .paletteSlot = PALSLOT_NPC_SPECIAL,\n"
                "};\n"
            )
        slot = _find_palette_slot_for_tag(info_h, "OBJ_EVENT_PAL_TAG_ROCKET_M")
        _assert("find pal slot: found",
                slot == "PALSLOT_NPC_SPECIAL",
                f"got: {slot}")
    except Exception as e:
        _fail("find pal slot", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 130: _find_palette_slot_for_tag — tag not present
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        info_h = os.path.join(tmp_dir, "info.h")
        with open(info_h, "w") as f:
            f.write(
                "const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_Boy1 = {\n"
                "    .paletteTag = OBJ_EVENT_PAL_TAG_NPC_1,\n"
                "    .paletteSlot = PALSLOT_NPC_1,\n"
                "};\n"
            )
        slot = _find_palette_slot_for_tag(info_h, "OBJ_EVENT_PAL_TAG_ROCKET_M")
        _assert("find pal slot: not found", slot is None, f"got: {slot}")
    except Exception as e:
        _fail("find pal slot not found", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 131: _find_matching_palette — matches shared NPC palette
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        game_dir = os.path.join(tmp_dir, "game")
        pal_dir = os.path.join(game_dir, "graphics", "object_events", "palettes")
        inc_dir = os.path.join(game_dir, "include", "constants")
        src_dir = os.path.join(game_dir, "src", "data", "object_events")
        for d in (pal_dir, inc_dir, src_dir):
            os.makedirs(d, exist_ok=True)

        # Create npc_1.gbapal with known palette
        npc1_pal = bytearray(32)
        for i in range(8):
            struct.pack_into("<H", npc1_pal, i * 2, (i + 1) * 50)
        with open(os.path.join(pal_dir, "npc_1.gbapal"), "wb") as f:
            f.write(npc1_pal)
        # Create other NPC palettes (different)
        for n in range(2, 5):
            other_pal = bytearray(32)
            struct.pack_into("<H", other_pal, 2, 9999 + n)
            with open(os.path.join(pal_dir, f"npc_{n}.gbapal"), "wb") as f:
                f.write(other_pal)

        # Create event_objects.h with no custom tags
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_NPC_1 0x1100\n")

        # Create matching PNG
        # Build palette colors that convert to the same BGR555 values
        # Index 0 = (0,0,0), index 1 = 50 -> convert back
        # We need colors whose BGR555 match npc1_pal exactly
        # For i=0: val=0, for i=1: val=50
        colors = []
        for i in range(8):
            val = (i + 1) * 50
            r5 = val & 0x1F
            g5 = (val >> 5) & 0x1F
            b5 = (val >> 10) & 0x1F
            colors.append((r5 << 3, g5 << 3, b5 << 3))
        png_path = os.path.join(tmp_dir, "sprite.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(32, 32, 8, 3, 16, palette_colors=colors))

        match_type, tag, slot = _find_matching_palette(png_path, game_dir)
        _assert("find match: shared NPC_1",
                match_type == "shared" and "NPC_1" in tag,
                f"got: {match_type}, {tag}, {slot}")
    except Exception as e:
        _fail("find match shared", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 132: _find_matching_palette — no match returns "none"
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        game_dir = os.path.join(tmp_dir, "game")
        pal_dir = os.path.join(game_dir, "graphics", "object_events", "palettes")
        inc_dir = os.path.join(game_dir, "include", "constants")
        src_dir = os.path.join(game_dir, "src", "data", "object_events")
        for d in (pal_dir, inc_dir, src_dir):
            os.makedirs(d, exist_ok=True)

        # Create NPC palettes with specific values
        for n in range(1, 5):
            pal = bytearray(32)
            struct.pack_into("<H", pal, 2, 1000 + n)
            with open(os.path.join(pal_dir, f"npc_{n}.gbapal"), "wb") as f:
                f.write(pal)

        # event_objects.h with no custom tags
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_NPC_1 0x1100\n")

        # PNG with completely different palette
        colors = [(255, 128, 64)]
        png_path = os.path.join(tmp_dir, "unique.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(32, 32, 8, 3, 16, palette_colors=colors))

        match_type, tag, slot = _find_matching_palette(png_path, game_dir)
        _assert("find match: no match",
                match_type == "none" and tag is None,
                f"got: {match_type}, {tag}")
    except Exception as e:
        _fail("find match none", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 133: _find_matching_palette — matches existing custom palette
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        game_dir = os.path.join(tmp_dir, "game")
        pal_dir = os.path.join(game_dir, "graphics", "object_events", "palettes")
        inc_dir = os.path.join(game_dir, "include", "constants")
        src_dir = os.path.join(game_dir, "src", "data", "object_events")
        for d in (pal_dir, inc_dir, src_dir):
            os.makedirs(d, exist_ok=True)

        # Create NPC palettes (won't match)
        for n in range(1, 5):
            pal = bytearray(32)
            struct.pack_into("<H", pal, 2, 1000 + n)
            with open(os.path.join(pal_dir, f"npc_{n}.gbapal"), "wb") as f:
                f.write(pal)

        # Create a custom palette .gbapal for RocketM
        custom_pal = bytearray(32)
        for i in range(8):
            struct.pack_into("<H", custom_pal, i * 2, (i + 1) * 77)
        with open(os.path.join(pal_dir, "rocket_m.gbapal"), "wb") as f:
            f.write(custom_pal)

        # event_objects.h with custom tag
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_NPC_1 0x1100\n")
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_M 0x1125\n")

        # object_event_graphics.h with INCBIN for the custom palette
        with open(os.path.join(src_dir, "object_event_graphics.h"), "w") as f:
            f.write(
                'const u16 gObjectEventPal_RocketM[] = INCBIN_U16('
                '"graphics/object_events/palettes/rocket_m.gbapal");\n'
            )

        # object_event_graphics_info.h with struct using the tag
        with open(os.path.join(src_dir, "object_event_graphics_info.h"), "w") as f:
            f.write(
                "const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_RocketM = {\n"
                "    .paletteTag = OBJ_EVENT_PAL_TAG_ROCKET_M,\n"
                "    .paletteSlot = PALSLOT_NPC_SPECIAL,\n"
                "};\n"
            )

        # Create PNG whose palette matches the custom palette
        colors = []
        for i in range(8):
            val = (i + 1) * 77
            r5 = val & 0x1F
            g5 = (val >> 5) & 0x1F
            b5 = (val >> 10) & 0x1F
            colors.append((r5 << 3, g5 << 3, b5 << 3))
        png_path = os.path.join(tmp_dir, "rocket_f.png")
        with open(png_path, "wb") as f:
            f.write(_make_png(32, 32, 8, 3, 16, palette_colors=colors))

        match_type, tag, slot = _find_matching_palette(png_path, game_dir)
        _assert("find match: custom reuse",
                match_type == "custom" and tag == "OBJ_EVENT_PAL_TAG_ROCKET_M",
                f"got: {match_type}, {tag}")
        _assert("find match: custom slot",
                slot == "PALSLOT_NPC_SPECIAL",
                f"got: {slot}")
    except Exception as e:
        _fail("find match custom", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 134: _has_own_custom_palette — true for registered sprite
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        game_dir = os.path.join(tmp_dir, "game")
        inc_dir = os.path.join(game_dir, "include", "constants")
        os.makedirs(inc_dir)
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_M 0x1125\n")
        # Need _derive_palette_tag_name accessible — it's already imported
        _assert("has own custom: true",
                _has_own_custom_palette("RocketM", game_dir),
                "should have custom palette")
    except Exception as e:
        _fail("has own custom true", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 135: _has_own_custom_palette — false for NPC palette sprite
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        game_dir = os.path.join(tmp_dir, "game")
        inc_dir = os.path.join(game_dir, "include", "constants")
        os.makedirs(inc_dir)
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_NPC_1 0x1100\n")
        _assert("has own custom: false",
                not _has_own_custom_palette("Boy1", game_dir),
                "should not have custom palette")
    except Exception as e:
        _fail("has own custom false", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 136: _palettes_match — single entry palettes (only index 0)
    try:
        pal_a = bytearray(32)
        pal_b = bytearray(32)
        struct.pack_into("<H", pal_a, 0, 1234)
        struct.pack_into("<H", pal_b, 0, 5678)
        _assert("pal match: count=1 trivially true",
                _palettes_match(pal_a, pal_b, 1, 1),
                "should match (only index 0 exists)")
    except Exception as e:
        _fail("pal match count=1", str(e))

    # ── Palette deduplication tests ──────────────────────────────────

    try:
        from torch.asset_manager import (
            _scan_duplicate_palettes,
            _dedup_palette,
        )
    except ImportError as e:
        _skip("palette dedup tests", f"import failed: {e}")
        return

    # Test 137: _scan_duplicate_palettes — finds identical custom palettes
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        game_dir = os.path.join(tmp_dir, "game")
        pal_dir = os.path.join(game_dir, "graphics", "object_events", "palettes")
        inc_dir = os.path.join(game_dir, "include", "constants")
        src_dir = os.path.join(game_dir, "src", "data", "object_events")
        for d in (pal_dir, inc_dir, src_dir):
            os.makedirs(d, exist_ok=True)

        # Two custom tags with identical palettes
        pal_data = bytearray(32)
        for i in range(8):
            struct.pack_into("<H", pal_data, i * 2, (i + 1) * 77)
        with open(os.path.join(pal_dir, "rocket_m.gbapal"), "wb") as f:
            f.write(pal_data)
        with open(os.path.join(pal_dir, "rocket_f.gbapal"), "wb") as f:
            f.write(pal_data)  # identical

        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_M 0x1125\n")
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_F 0x1126\n")

        with open(os.path.join(src_dir, "object_event_graphics.h"), "w") as f:
            f.write('const u16 gObjectEventPal_RocketM[] = INCBIN_U16('
                    '"graphics/object_events/palettes/rocket_m.gbapal");\n')
            f.write('const u16 gObjectEventPal_RocketF[] = INCBIN_U16('
                    '"graphics/object_events/palettes/rocket_f.gbapal");\n')

        dupes = _scan_duplicate_palettes(game_dir)
        _assert("scan dupes: found one group",
                len(dupes) == 1, f"got {len(dupes)} groups")
        if dupes:
            keep_tag, keep_camel, dup_list = dupes[0]
            _assert("scan dupes: keep is RocketM",
                    keep_tag == "OBJ_EVENT_PAL_TAG_ROCKET_M",
                    f"keep={keep_tag}")
            _assert("scan dupes: one dup",
                    len(dup_list) == 1, f"got {len(dup_list)}")
            _assert("scan dupes: dup is RocketF",
                    dup_list[0][0] == "OBJ_EVENT_PAL_TAG_ROCKET_F",
                    f"dup={dup_list[0][0]}")
    except Exception as e:
        _fail("scan dupes", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 138: _scan_duplicate_palettes — no dupes when palettes differ
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        game_dir = os.path.join(tmp_dir, "game")
        pal_dir = os.path.join(game_dir, "graphics", "object_events", "palettes")
        inc_dir = os.path.join(game_dir, "include", "constants")
        src_dir = os.path.join(game_dir, "src", "data", "object_events")
        for d in (pal_dir, inc_dir, src_dir):
            os.makedirs(d, exist_ok=True)

        # Two custom tags with different palettes
        pal_a = bytearray(32)
        pal_b = bytearray(32)
        struct.pack_into("<H", pal_a, 2, 1111)
        struct.pack_into("<H", pal_b, 2, 2222)
        with open(os.path.join(pal_dir, "rocket_m.gbapal"), "wb") as f:
            f.write(pal_a)
        with open(os.path.join(pal_dir, "rocket_f.gbapal"), "wb") as f:
            f.write(pal_b)

        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_M 0x1125\n")
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_F 0x1126\n")

        with open(os.path.join(src_dir, "object_event_graphics.h"), "w") as f:
            f.write('const u16 gObjectEventPal_RocketM[] = INCBIN_U16('
                    '"graphics/object_events/palettes/rocket_m.gbapal");\n')
            f.write('const u16 gObjectEventPal_RocketF[] = INCBIN_U16('
                    '"graphics/object_events/palettes/rocket_f.gbapal");\n')

        dupes = _scan_duplicate_palettes(game_dir)
        _assert("scan dupes: no matches",
                len(dupes) == 0, f"got {len(dupes)} groups")
    except Exception as e:
        _fail("scan dupes no match", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 139: _dedup_palette — merges dup into keeper
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        game_dir = os.path.join(tmp_dir, "game")
        pal_dir = os.path.join(game_dir, "graphics", "object_events", "palettes")
        inc_dir = os.path.join(game_dir, "include", "constants")
        src_dir = os.path.join(game_dir, "src", "data", "object_events")
        mov_dir = os.path.join(game_dir, "src")
        for d in (pal_dir, inc_dir, src_dir, mov_dir):
            os.makedirs(d, exist_ok=True)

        # Setup: two custom palettes, RocketF uses its own tag
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_M 0x1125\n")
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_F 0x1126\n")

        with open(os.path.join(src_dir, "object_event_graphics.h"), "w") as f:
            f.write('const u16 gObjectEventPal_RocketM[] = INCBIN_U16('
                    '"graphics/object_events/palettes/rocket_m.gbapal");\n')
            f.write('const u16 gObjectEventPal_RocketF[] = INCBIN_U16('
                    '"graphics/object_events/palettes/rocket_f.gbapal");\n')

        with open(os.path.join(src_dir, "object_event_graphics_info.h"), "w") as f:
            f.write(
                "const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_RocketM = {\n"
                "    .paletteTag = OBJ_EVENT_PAL_TAG_ROCKET_M,\n"
                "    .paletteSlot = PALSLOT_NPC_SPECIAL,\n"
                "};\n"
                "const struct ObjectEventGraphicsInfo gObjectEventGraphicsInfo_RocketF = {\n"
                "    .paletteTag = OBJ_EVENT_PAL_TAG_ROCKET_F,\n"
                "    .paletteSlot = PALSLOT_NPC_SPECIAL,\n"
                "};\n"
            )

        with open(os.path.join(mov_dir, "event_object_movement.c"), "w") as f:
            f.write("    {gObjectEventPal_RocketM, OBJ_EVENT_PAL_TAG_ROCKET_M},\n")
            f.write("    {gObjectEventPal_RocketF, OBJ_EVENT_PAL_TAG_ROCKET_F},\n")

        # Create palette files for dup
        with open(os.path.join(pal_dir, "rocket_f.gbapal"), "wb") as f:
            f.write(bytearray(32))
        with open(os.path.join(pal_dir, "rocket_f.pal"), "w") as f:
            f.write("JASC-PAL\n")

        ok, msg = _dedup_palette(
            "OBJ_EVENT_PAL_TAG_ROCKET_M",
            "OBJ_EVENT_PAL_TAG_ROCKET_F",
            "RocketF", game_dir)
        _assert("dedup: succeeds", ok, f"msg={msg}")

        # Verify RocketF struct now uses RocketM's tag
        with open(os.path.join(src_dir, "object_event_graphics_info.h")) as f:
            info_content = f.read()
        _assert("dedup: struct patched",
                "OBJ_EVENT_PAL_TAG_ROCKET_F" not in info_content
                and info_content.count("OBJ_EVENT_PAL_TAG_ROCKET_M") == 2,
                "struct not patched correctly")

        # Verify dup tag removed from event_objects.h
        with open(os.path.join(inc_dir, "event_objects.h")) as f:
            eo_content = f.read()
        _assert("dedup: tag removed",
                "ROCKET_F" not in eo_content,
                "dup tag not removed")
        _assert("dedup: keeper preserved",
                "ROCKET_M" in eo_content,
                "keeper tag removed")

        # Verify dup INCBIN removed
        with open(os.path.join(src_dir, "object_event_graphics.h")) as f:
            gfx_content = f.read()
        _assert("dedup: INCBIN removed",
                "RocketF" not in gfx_content,
                "dup INCBIN not removed")

        # Verify dup palette files deleted
        _assert("dedup: gbapal deleted",
                not os.path.exists(os.path.join(pal_dir, "rocket_f.gbapal")),
                "gbapal still exists")
        _assert("dedup: pal deleted",
                not os.path.exists(os.path.join(pal_dir, "rocket_f.pal")),
                "pal still exists")

        # Verify movement.c table entry removed
        with open(os.path.join(mov_dir, "event_object_movement.c")) as f:
            mov_content = f.read()
        _assert("dedup: table entry removed",
                "RocketF" not in mov_content,
                "dup table entry not removed")
        _assert("dedup: keeper entry preserved",
                "RocketM" in mov_content,
                "keeper table entry removed")
    except Exception as e:
        _fail("dedup palette", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Test 140: _scan_duplicate_palettes — single tag returns empty
    tmp_dir = tempfile.mkdtemp(prefix="torch_asset_")
    try:
        game_dir = os.path.join(tmp_dir, "game")
        pal_dir = os.path.join(game_dir, "graphics", "object_events", "palettes")
        inc_dir = os.path.join(game_dir, "include", "constants")
        src_dir = os.path.join(game_dir, "src", "data", "object_events")
        for d in (pal_dir, inc_dir, src_dir):
            os.makedirs(d, exist_ok=True)

        with open(os.path.join(pal_dir, "rocket_m.gbapal"), "wb") as f:
            f.write(bytearray(32))
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write("#define OBJ_EVENT_PAL_TAG_ROCKET_M 0x1125\n")
        with open(os.path.join(src_dir, "object_event_graphics.h"), "w") as f:
            f.write('const u16 gObjectEventPal_RocketM[] = INCBIN_U16('
                    '"graphics/object_events/palettes/rocket_m.gbapal");\n')

        dupes = _scan_duplicate_palettes(game_dir)
        _assert("scan dupes: single tag no dupes",
                len(dupes) == 0, f"got {len(dupes)}")
    except Exception as e:
        _fail("scan dupes single", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── _ImportTransaction tests ──────────────────────────────────────

    # Test 141: rollback deletes created files and restores modified files
    try:
        from torch.asset_manager import _ImportTransaction
        tmp_dir = tempfile.mkdtemp(prefix="torch_txn_")
        try:
            # Create a pre-existing file to modify
            existing = os.path.join(tmp_dir, "existing.txt")
            with open(existing, "w") as f:
                f.write("original content")

            txn = _ImportTransaction()

            # Track creating a new file
            new_file = os.path.join(tmp_dir, "new_file.txt")
            with open(new_file, "w") as f:
                f.write("new")
            txn.track_create(new_file)

            # Track modifying existing file
            txn.track_modify(existing)
            with open(existing, "w") as f:
                f.write("modified content")

            # Verify both changes are live
            _assert("txn: new file exists before rollback",
                    os.path.isfile(new_file), "new file missing")
            with open(existing) as f:
                _assert("txn: existing modified before rollback",
                        f.read() == "modified content", "not modified")

            # Rollback
            txn.rollback()

            _assert("txn: new file deleted after rollback",
                    not os.path.isfile(new_file), "new file still exists")
            with open(existing) as f:
                _assert("txn: existing restored after rollback",
                        f.read() == "original content", "not restored")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("txn rollback", str(e))

    # Test 142: commit discards transaction cleanly
    try:
        from torch.asset_manager import _ImportTransaction
        tmp_dir = tempfile.mkdtemp(prefix="torch_txn_")
        try:
            new_file = os.path.join(tmp_dir, "committed.txt")
            with open(new_file, "w") as f:
                f.write("committed")
            txn = _ImportTransaction()
            txn.track_create(new_file)
            txn.commit()
            # After commit, file should still exist
            _assert("txn: committed file persists",
                    os.path.isfile(new_file), "file was deleted")
            # Rollback after commit should be no-op
            txn.rollback()
            _assert("txn: post-commit rollback is noop",
                    os.path.isfile(new_file), "file deleted by post-commit rollback")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("txn commit", str(e))

    # Test 143: rollback restores in LIFO order (step 3 fail restores 1-2)
    try:
        from torch.asset_manager import _ImportTransaction
        tmp_dir = tempfile.mkdtemp(prefix="torch_txn_")
        try:
            f1 = os.path.join(tmp_dir, "step1.txt")
            f2 = os.path.join(tmp_dir, "step2.txt")
            f3_target = os.path.join(tmp_dir, "step3_mod.txt")
            with open(f3_target, "w") as f:
                f.write("step3 original")

            txn = _ImportTransaction()
            # Step 1: create file
            with open(f1, "w") as f:
                f.write("step1")
            txn.track_create(f1)
            # Step 2: create file
            with open(f2, "w") as f:
                f.write("step2")
            txn.track_create(f2)
            # Step 3: modify file (simulate failure after snapshot)
            txn.track_modify(f3_target)
            with open(f3_target, "w") as f:
                f.write("step3 modified")

            # Simulate failure at step 3
            txn.rollback()

            _assert("txn lifo: step1 rolled back",
                    not os.path.isfile(f1), "step1 file still exists")
            _assert("txn lifo: step2 rolled back",
                    not os.path.isfile(f2), "step2 file still exists")
            with open(f3_target) as f:
                _assert("txn lifo: step3 restored",
                        f.read() == "step3 original", "step3 not restored")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("txn lifo rollback", str(e))

    # Test 144: rollback on palette registration cleans up .gbapal
    try:
        from torch.asset_manager import _ImportTransaction
        tmp_dir = tempfile.mkdtemp(prefix="torch_txn_")
        try:
            gbapal = os.path.join(tmp_dir, "sprite.gbapal")
            with open(gbapal, "wb") as f:
                f.write(bytearray(32))
            txn = _ImportTransaction()
            txn.track_create(gbapal)
            txn.rollback()
            _assert("txn: gbapal cleaned up",
                    not os.path.isfile(gbapal), "gbapal still exists")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("txn palette rollback", str(e))

    # ── Exact-match constant collision tests ──────────────────────────

    # Test 145: substring false positive prevention
    try:
        from torch.asset_manager import _is_already_imported
        tmp_dir = tempfile.mkdtemp(prefix="torch_exact_")
        try:
            header = os.path.join(tmp_dir, "trainers.h")
            with open(header, "w") as f:
                f.write("#define TRAINER_PIC_BRENDAN_NORMAL 5\n")
                f.write("#define TRAINER_PIC_COUNT          6\n")
            # BRENDAN should NOT match against BRENDAN_NORMAL
            result = _is_already_imported("TRAINER_PIC_BRENDAN", header)
            _assert("exact match: BRENDAN not in BRENDAN_NORMAL",
                    result is False, f"got {result}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("exact match substring", str(e))

    # Test 146: exact match still works
    try:
        from torch.asset_manager import _is_already_imported
        tmp_dir = tempfile.mkdtemp(prefix="torch_exact_")
        try:
            header = os.path.join(tmp_dir, "trainers.h")
            with open(header, "w") as f:
                f.write("#define TRAINER_PIC_HIKER 10\n")
                f.write("#define TRAINER_PIC_COUNT 11\n")
            result = _is_already_imported("TRAINER_PIC_HIKER", header)
            _assert("exact match: HIKER found on exact match",
                    result is True, f"got {result}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("exact match positive", str(e))

    # Test 147: MUS_ROUTE doesn't match MUS_ROUTE_123
    try:
        from torch.asset_manager import _is_music_already_imported
        tmp_dir = tempfile.mkdtemp(prefix="torch_exact_")
        try:
            header = os.path.join(tmp_dir, "songs.h")
            with open(header, "w") as f:
                f.write("#define MUS_ROUTE_123 100\n")
            result = _is_music_already_imported("MUS_ROUTE", header)
            _assert("exact match: MUS_ROUTE not in MUS_ROUTE_123",
                    result is False, f"got {result}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("exact match music", str(e))

    # ── PNG structural integrity tests ────────────────────────────────

    # Test 148: reject PNG with no PLTE (indexed type)
    try:
        from torch.asset_manager import _validate_png_structural_integrity
        import zlib
        tmp_dir = tempfile.mkdtemp(prefix="torch_png_")
        try:
            # Build a PNG with IHDR (indexed), IDAT, IEND but NO PLTE
            png_path = os.path.join(tmp_dir, "no_plte.png")
            buf = bytearray(b"\x89PNG\r\n\x1a\n")
            def _chunk(ctype, data):
                c = struct.pack(">I", len(data)) + ctype + data
                crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
                c += struct.pack(">I", crc)
                return c
            ihdr = struct.pack(">IIBBBBB", 8, 8, 8, 3, 0, 0, 0)
            buf += _chunk(b"IHDR", ihdr)
            raw = b"\x00" + b"\x00" * 8  # one row
            buf += _chunk(b"IDAT", zlib.compress(raw * 8))
            buf += _chunk(b"IEND", b"")
            with open(png_path, "wb") as f:
                f.write(buf)

            ok, msg = _validate_png_structural_integrity(png_path)
            _assert("png integrity: reject indexed without PLTE",
                    ok is False and "PLTE" in msg, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("png integrity no PLTE", str(e))

    # Test 149: reject PNG with no IDAT
    try:
        from torch.asset_manager import _validate_png_structural_integrity
        import zlib
        tmp_dir = tempfile.mkdtemp(prefix="torch_png_")
        try:
            png_path = os.path.join(tmp_dir, "no_idat.png")
            buf = bytearray(b"\x89PNG\r\n\x1a\n")
            def _chunk(ctype, data):
                c = struct.pack(">I", len(data)) + ctype + data
                crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
                c += struct.pack(">I", crc)
                return c
            ihdr = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)  # truecolour
            buf += _chunk(b"IHDR", ihdr)
            buf += _chunk(b"IEND", b"")
            with open(png_path, "wb") as f:
                f.write(buf)

            ok, msg = _validate_png_structural_integrity(png_path)
            _assert("png integrity: reject without IDAT",
                    ok is False and "IDAT" in msg, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("png integrity no IDAT", str(e))

    # Test 150: reject truncated file (signature only)
    try:
        from torch.asset_manager import _validate_png_structural_integrity
        tmp_dir = tempfile.mkdtemp(prefix="torch_png_")
        try:
            png_path = os.path.join(tmp_dir, "truncated.png")
            with open(png_path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")  # signature only
            ok, msg = _validate_png_structural_integrity(png_path)
            _assert("png integrity: reject truncated",
                    ok is False, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("png integrity truncated", str(e))

    # ── Dimension bounds tests ────────────────────────────────────────

    # Test 151: reject oversized spritesheet
    try:
        from torch.asset_manager import _validate_overworld_sprite
        tmp_dir = tempfile.mkdtemp(prefix="torch_dim_")
        try:
            # 1024x64 — way too wide
            png_path = os.path.join(tmp_dir, "huge.png")
            with open(png_path, "wb") as f:
                f.write(_make_png(1024, 64, 8, 3, 16))
            ok, msg = _validate_overworld_sprite(png_path)
            _assert("bounds: reject 1024x64 (too wide)",
                    ok is False, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("bounds oversized", str(e))

    # Test 152: accept large but valid sheet (288x32 = 9 frames of 32x32)
    try:
        from torch.asset_manager import _validate_overworld_sprite
        tmp_dir = tempfile.mkdtemp(prefix="torch_dim_")
        try:
            png_path = os.path.join(tmp_dir, "large_valid.png")
            with open(png_path, "wb") as f:
                f.write(_make_png(288, 32, 8, 3, 16))
            ok, msg = _validate_overworld_sprite(png_path)
            _assert("bounds: accept 288x32 (9 frames of 32x32)",
                    ok is True, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("bounds valid large", str(e))

    # ── Palette tag exhaustion tests ──────────────────────────────────

    # Test 153: count correctly with 0, 1, N tags
    try:
        from torch.asset_manager import _count_custom_palette_tags
        tmp_dir = tempfile.mkdtemp(prefix="torch_pal_")
        try:
            header = os.path.join(tmp_dir, "event_objects.h")
            # No custom tags
            with open(header, "w") as f:
                f.write("#define OBJ_EVENT_PAL_TAG_DYNAMIC 0x1124\n")
            used, total = _count_custom_palette_tags(header)
            _assert("pal count: zero tags",
                    used == 0 and total == 43, f"used={used}, total={total}")

            # Two custom tags
            with open(header, "w") as f:
                f.write("#define OBJ_EVENT_PAL_TAG_DYNAMIC 0x1124\n")
                f.write("#define OBJ_EVENT_PAL_TAG_CUSTOM_A 0x1125\n")
                f.write("#define OBJ_EVENT_PAL_TAG_CUSTOM_B 0x1126\n")
            used, total = _count_custom_palette_tags(header)
            _assert("pal count: two tags",
                    used == 2 and total == 43, f"used={used}, total={total}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("pal count", str(e))

    # Test 154: returns (0, 43) on file with no TORCH-range tags
    try:
        from torch.asset_manager import _count_custom_palette_tags
        tmp_dir = tempfile.mkdtemp(prefix="torch_pal_")
        try:
            header = os.path.join(tmp_dir, "event_objects.h")
            with open(header, "w") as f:
                f.write("#define OBJ_EVENT_PAL_TAG_NPC_1 0x1101\n")
                f.write("#define OBJ_EVENT_PAL_TAG_NPC_2 0x1102\n")
            used, total = _count_custom_palette_tags(header)
            _assert("pal count: no TORCH-range tags",
                    used == 0 and total == 43, f"used={used}, total={total}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("pal count no torch tags", str(e))

    # ── Removal UX tests ─────────────────────────────────────────────

    # Test 155: removal error includes workaround guidance
    try:
        from torch.asset_manager import _can_remove_asset
        tmp_dir = tempfile.mkdtemp(prefix="torch_rm_")
        try:
            game_dir = os.path.join(tmp_dir, "game")
            inc_dir = os.path.join(game_dir, "include", "constants")
            os.makedirs(inc_dir, exist_ok=True)
            with open(os.path.join(inc_dir, "songs.h"), "w") as f:
                f.write("#define MUS_FIRST 1\n")
                f.write("#define MUS_SECOND 2\n")
                f.write("#define END_MUS MUS_SECOND\n")
            can, reason = _can_remove_asset("music_tracks", "MUS_FIRST", game_dir)
            _assert("rm UX: cannot remove non-last",
                    can is False, f"can={can}")
            _assert("rm UX: includes workaround",
                    "reverse order" in reason or "silent track" in reason,
                    f"reason={reason}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("rm UX guidance", str(e))

    # ── Trainer back sprite tests ─────────────────────────────────────

    # Test 156: validate accepts 64x256 indexed PNG
    try:
        from torch.asset_manager import _validate_trainer_back_sprite
        tmp_dir = tempfile.mkdtemp(prefix="torch_back_")
        try:
            png_path = os.path.join(tmp_dir, "rival_back.png")
            with open(png_path, "wb") as f:
                f.write(_make_png(64, 256, 8, 3, 16))
            ok, msg = _validate_trainer_back_sprite(png_path)
            _assert("back sprite: accept 64x256",
                    ok is True, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("back sprite valid", str(e))

    # Test 157: validate rejects 64x64 (that's a front pic)
    try:
        from torch.asset_manager import _validate_trainer_back_sprite
        tmp_dir = tempfile.mkdtemp(prefix="torch_back_")
        try:
            png_path = os.path.join(tmp_dir, "front.png")
            with open(png_path, "wb") as f:
                f.write(_make_png(64, 64, 8, 3, 16))
            ok, msg = _validate_trainer_back_sprite(png_path)
            _assert("back sprite: reject 64x64 (front pic)",
                    ok is False and "front pic" in msg, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("back sprite reject front", str(e))

    # Test 158: validate rejects 64x128 (only 2 frames)
    try:
        from torch.asset_manager import _validate_trainer_back_sprite
        tmp_dir = tempfile.mkdtemp(prefix="torch_back_")
        try:
            png_path = os.path.join(tmp_dir, "two_frame.png")
            with open(png_path, "wb") as f:
                f.write(_make_png(64, 128, 8, 3, 16))
            ok, msg = _validate_trainer_back_sprite(png_path)
            _assert("back sprite: reject 64x128 (2 frames)",
                    ok is False, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("back sprite reject 2frame", str(e))

    # Test 159: back sprite constant derivation
    try:
        from torch.asset_manager import _derive_trainer_back_const
        _assert("back const: RivalDawn -> TRAINER_BACK_PIC_RIVAL_DAWN",
                _derive_trainer_back_const("RivalDawn") == "TRAINER_BACK_PIC_RIVAL_DAWN",
                f"got: {_derive_trainer_back_const('RivalDawn')}")
    except Exception as e:
        _fail("back const derivation", str(e))

    # Test 160: back sprite import creates files in back_pics/
    try:
        from torch.asset_manager import _import_trainer_back_sprite, _extract_gbapal_from_png
        tmp_dir = tempfile.mkdtemp(prefix="torch_back_")
        try:
            game_dir = os.path.join(tmp_dir, "game")
            # Create required directory structure + headers
            gfx_dir = os.path.join(game_dir, "graphics", "trainers", "back_pics")
            trainers_h = os.path.join(game_dir, "src", "data", "graphics", "trainers.h")
            trainers_const = os.path.join(game_dir, "include", "constants", "trainers.h")
            for d in (gfx_dir, os.path.dirname(trainers_h), os.path.dirname(trainers_const)):
                os.makedirs(d, exist_ok=True)

            with open(trainers_h, "w") as f:
                f.write('const u32 gTrainerBackPic_Brendan[] = INCBIN_U32("graphics/trainers/back_pics/brendan.4bpp.smol");\n')
                f.write('const u16 gTrainerBackPalette_Brendan[] = INCBIN_U16("graphics/trainers/back_pics/brendan.gbapal");\n')
                f.write("const struct CompressedSpriteSheet gTrainerBacksprites[] = {\n")
                f.write("    TRAINER_BACK_SPRITE(TRAINER_BACK_PIC_BRENDAN, 4, gTrainerBackPic_Brendan, gTrainerBackPalette_Brendan, gTrainerBackAnimTable_Brendan),\n")
                f.write("};\n")

            with open(trainers_const, "w") as f:
                f.write("#define TRAINER_BACK_PIC_BRENDAN 0\n")

            # Create a valid 64x256 PNG
            src_png = os.path.join(tmp_dir, "rival_dawn.png")
            with open(src_png, "wb") as f:
                f.write(_make_png(64, 256, 8, 3, 16))

            result = _import_trainer_back_sprite(src_png, game_dir)
            _assert("back import: returns result",
                    result is not None, "result is None")
            if result:
                _assert("back import: correct constant",
                        result["constant"] == "TRAINER_BACK_PIC_RIVAL_DAWN",
                        f"got {result['constant']}")
                # Check PNG created in back_pics/
                dest = os.path.join(gfx_dir, "rival_dawn.png")
                _assert("back import: PNG in back_pics/",
                        os.path.isfile(dest), "PNG not found")
                # Check gbapal created
                pal = os.path.join(gfx_dir, "rival_dawn.gbapal")
                _assert("back import: gbapal created",
                        os.path.isfile(pal), "gbapal not found")

            # Check INCBIN lines added to trainers.h (back section)
            with open(trainers_h) as f:
                content = f.read()
            _assert("back import: INCBIN added",
                    "gTrainerBackPic_RivalDawn" in content, "INCBIN not found")
            _assert("back import: TRAINER_BACK_SPRITE added",
                    "TRAINER_BACK_SPRITE(TRAINER_BACK_PIC_RIVAL_DAWN," in content,
                    "sprite entry not found")

            # Check constant added
            with open(trainers_const) as f:
                const_content = f.read()
            _assert("back import: constant added",
                    "TRAINER_BACK_PIC_RIVAL_DAWN" in const_content,
                    "constant not found")

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("back sprite import", str(e))

    # Test 161: back sprite removal cleans up
    try:
        from torch.asset_manager import _remove_trainer_back_sprite
        tmp_dir = tempfile.mkdtemp(prefix="torch_back_")
        try:
            game_dir = os.path.join(tmp_dir, "game")
            gfx_dir = os.path.join(game_dir, "graphics", "trainers", "back_pics")
            trainers_h = os.path.join(game_dir, "src", "data", "graphics", "trainers.h")
            trainers_const = os.path.join(game_dir, "include", "constants", "trainers.h")
            for d in (gfx_dir, os.path.dirname(trainers_h), os.path.dirname(trainers_const)):
                os.makedirs(d, exist_ok=True)

            # Create files to remove
            with open(os.path.join(gfx_dir, "rival_dawn.png"), "wb") as f:
                f.write(b"png")
            with open(os.path.join(gfx_dir, "rival_dawn.gbapal"), "wb") as f:
                f.write(bytearray(32))

            with open(trainers_h, "w") as f:
                f.write('const u32 gTrainerBackPic_RivalDawn[] = INCBIN_U32("x");\n')
                f.write('const u16 gTrainerBackPalette_RivalDawn[] = INCBIN_U16("x");\n')
                f.write("const struct CompressedSpriteSheet gTrainerBacksprites[] = {\n")
                f.write("    TRAINER_BACK_SPRITE(TRAINER_BACK_PIC_RIVAL_DAWN, 4, a, b, c),\n")
                f.write("};\n")

            with open(trainers_const, "w") as f:
                f.write("#define TRAINER_BACK_PIC_BRENDAN 0\n")
                f.write("#define TRAINER_BACK_PIC_RIVAL_DAWN 1\n")

            errors = _remove_trainer_back_sprite("TRAINER_BACK_PIC_RIVAL_DAWN", game_dir)
            _assert("back remove: no errors",
                    len(errors) == 0, f"errors: {errors}")
            _assert("back remove: PNG deleted",
                    not os.path.isfile(os.path.join(gfx_dir, "rival_dawn.png")),
                    "PNG still exists")
            with open(trainers_h) as f:
                content = f.read()
            _assert("back remove: INCBIN removed",
                    "RivalDawn" not in content, "INCBIN still present")
            with open(trainers_const) as f:
                const_content = f.read()
            _assert("back remove: constant removed",
                    "RIVAL_DAWN" not in const_content, "constant still present")
            _assert("back remove: brendan preserved",
                    "BRENDAN" in const_content, "brendan removed")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("back sprite remove", str(e))

    # ── Item icon tests ───────────────────────────────────────────────

    # Test 162: item icon name derivation
    try:
        from torch.asset_manager import _derive_item_icon_name
        _assert("item name: mystic_gem.png -> MysticGem",
                _derive_item_icon_name("mystic_gem.png") == "MysticGem",
                f"got: {_derive_item_icon_name('mystic_gem.png')}")
        _assert("item name: tm-fire.png -> TmFire",
                _derive_item_icon_name("tm-fire.png") == "TmFire",
                f"got: {_derive_item_icon_name('tm-fire.png')}")
    except Exception as e:
        _fail("item icon name", str(e))

    # Test 163: validate accepts 24x24 indexed PNG
    try:
        from torch.asset_manager import _validate_item_icon
        tmp_dir = tempfile.mkdtemp(prefix="torch_icon_")
        try:
            png_path = os.path.join(tmp_dir, "icon.png")
            with open(png_path, "wb") as f:
                f.write(_make_png(24, 24, 8, 3, 16))
            ok, msg = _validate_item_icon(png_path)
            _assert("item icon: accept 24x24",
                    ok is True, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("item icon valid", str(e))

    # Test 164: validate rejects wrong dimensions
    try:
        from torch.asset_manager import _validate_item_icon
        tmp_dir = tempfile.mkdtemp(prefix="torch_icon_")
        try:
            for w, h in [(32, 32), (16, 16)]:
                png_path = os.path.join(tmp_dir, f"icon_{w}x{h}.png")
                with open(png_path, "wb") as f:
                    f.write(_make_png(w, h, 8, 3, 16))
                ok, msg = _validate_item_icon(png_path)
                _assert(f"item icon: reject {w}x{h}",
                        ok is False, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("item icon bad dims", str(e))

    # Test 165: validate rejects >16 colours
    try:
        from torch.asset_manager import _validate_item_icon
        tmp_dir = tempfile.mkdtemp(prefix="torch_icon_")
        try:
            png_path = os.path.join(tmp_dir, "too_many.png")
            with open(png_path, "wb") as f:
                f.write(_make_png(24, 24, 8, 3, 32))
            ok, msg = _validate_item_icon(png_path)
            _assert("item icon: reject >16 colours",
                    ok is False and "Too many" in msg, f"ok={ok}, msg={msg}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("item icon too many colours", str(e))

    # Test 166: import creates PNG and palette in correct directories
    try:
        from torch.asset_manager import _import_item_icon
        tmp_dir = tempfile.mkdtemp(prefix="torch_icon_")
        try:
            game_dir = os.path.join(tmp_dir, "game")
            icon_dir = os.path.join(game_dir, "graphics", "items", "icons")
            pal_dir = os.path.join(game_dir, "graphics", "items", "icon_palettes")
            items_h = os.path.join(game_dir, "src", "data", "graphics", "items.h")
            exp_h = os.path.join(game_dir, "include", "constants", "expansion.h")
            for d in (icon_dir, pal_dir, os.path.dirname(items_h), os.path.dirname(exp_h)):
                os.makedirs(d, exist_ok=True)

            # Setup expansion.h (v1.14.0 -> uses smol)
            with open(exp_h, "w") as f:
                f.write("#define EXPANSION_VERSION_MAJOR 1\n")
                f.write("#define EXPANSION_VERSION_MINOR 14\n")
                f.write("#define EXPANSION_VERSION_PATCH 0\n")

            with open(items_h, "w") as f:
                f.write('const u32 gItemIcon_Potion[] = INCBIN_U32("graphics/items/icons/potion.4bpp.smol");\n')
                f.write('const u16 gItemIconPalette_Potion[] = INCBIN_U16("graphics/items/icon_palettes/potion.gbapal");\n')

            # Create source PNG
            src_png = os.path.join(tmp_dir, "mystic_gem.png")
            with open(src_png, "wb") as f:
                f.write(_make_png(24, 24, 8, 3, 16))

            result = _import_item_icon(src_png, game_dir)
            _assert("item import: returns result",
                    result is not None, "result is None")

            if result:
                # Check PNG in icons/
                dest = os.path.join(icon_dir, "mystic_gem.png")
                _assert("item import: PNG in icons/",
                        os.path.isfile(dest), "PNG not found")
                # Check gbapal in icon_palettes/
                pal = os.path.join(pal_dir, "mystic_gem.gbapal")
                _assert("item import: gbapal in icon_palettes/",
                        os.path.isfile(pal), "gbapal not found")
                # Check INCBIN lines
                with open(items_h) as f:
                    content = f.read()
                _assert("item import: icon INCBIN added",
                        "gItemIcon_MysticGem" in content, "icon INCBIN not found")
                _assert("item import: palette INCBIN added",
                        "gItemIconPalette_MysticGem" in content, "palette INCBIN not found")
                _assert("item import: uses smol",
                        ".4bpp.smol" in content and "MysticGem" in content,
                        "smol not used")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("item icon import", str(e))

    # Test 167: import rollback on step 3 failure
    try:
        from torch.asset_manager import _import_item_icon
        tmp_dir = tempfile.mkdtemp(prefix="torch_icon_")
        try:
            game_dir = os.path.join(tmp_dir, "game")
            icon_dir = os.path.join(game_dir, "graphics", "items", "icons")
            pal_dir = os.path.join(game_dir, "graphics", "items", "icon_palettes")
            exp_h = os.path.join(game_dir, "include", "constants", "expansion.h")
            for d in (icon_dir, pal_dir, os.path.dirname(exp_h)):
                os.makedirs(d, exist_ok=True)

            with open(exp_h, "w") as f:
                f.write("#define EXPANSION_VERSION_MAJOR 1\n")
                f.write("#define EXPANSION_VERSION_MINOR 14\n")
                f.write("#define EXPANSION_VERSION_PATCH 0\n")

            # No items.h — step 3 will fail
            src_png = os.path.join(tmp_dir, "gem.png")
            with open(src_png, "wb") as f:
                f.write(_make_png(24, 24, 8, 3, 16))

            result = _import_item_icon(src_png, game_dir)
            _assert("item rollback: returns None",
                    result is None, f"got {result}")
            # Files should be cleaned up
            _assert("item rollback: no PNG orphan",
                    not os.path.isfile(os.path.join(icon_dir, "gem.png")),
                    "PNG not cleaned up")
            _assert("item rollback: no gbapal orphan",
                    not os.path.isfile(os.path.join(pal_dir, "gem.gbapal")),
                    "gbapal not cleaned up")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("item icon rollback", str(e))

    # Test 168: remove deletes all files and INCBIN lines
    try:
        from torch.asset_manager import _remove_item_icon
        tmp_dir = tempfile.mkdtemp(prefix="torch_icon_")
        try:
            game_dir = os.path.join(tmp_dir, "game")
            icon_dir = os.path.join(game_dir, "graphics", "items", "icons")
            pal_dir = os.path.join(game_dir, "graphics", "items", "icon_palettes")
            items_h = os.path.join(game_dir, "src", "data", "graphics", "items.h")
            for d in (icon_dir, pal_dir, os.path.dirname(items_h)):
                os.makedirs(d, exist_ok=True)

            # Create files
            with open(os.path.join(icon_dir, "mystic_gem.png"), "wb") as f:
                f.write(b"png")
            with open(os.path.join(pal_dir, "mystic_gem.gbapal"), "wb") as f:
                f.write(bytearray(32))
            with open(items_h, "w") as f:
                f.write('const u32 gItemIcon_Potion[] = INCBIN_U32("x");\n')
                f.write('const u16 gItemIconPalette_Potion[] = INCBIN_U16("x");\n')
                f.write('const u32 gItemIcon_MysticGem[] = INCBIN_U32("x");\n')
                f.write('const u16 gItemIconPalette_MysticGem[] = INCBIN_U16("x");\n')

            errors = _remove_item_icon("gItemIcon_MysticGem", game_dir)
            _assert("item remove: no errors",
                    len(errors) == 0, f"errors: {errors}")
            _assert("item remove: PNG deleted",
                    not os.path.isfile(os.path.join(icon_dir, "mystic_gem.png")),
                    "PNG still exists")
            _assert("item remove: gbapal deleted",
                    not os.path.isfile(os.path.join(pal_dir, "mystic_gem.gbapal")),
                    "gbapal still exists")
            with open(items_h) as f:
                content = f.read()
            _assert("item remove: INCBIN removed",
                    "MysticGem" not in content, "INCBIN still present")
            _assert("item remove: Potion preserved",
                    "Potion" in content, "Potion removed")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("item icon remove", str(e))

    # Test 169: detection correctly identifies existing icons
    try:
        from torch.asset_manager import _is_item_icon_already_imported
        tmp_dir = tempfile.mkdtemp(prefix="torch_icon_")
        try:
            items_h = os.path.join(tmp_dir, "items.h")
            with open(items_h, "w") as f:
                f.write('const u32 gItemIcon_Potion[] = INCBIN_U32("x");\n')
            _assert("item detect: finds existing",
                    _is_item_icon_already_imported("Potion", items_h) is True,
                    "not found")
            _assert("item detect: rejects missing",
                    _is_item_icon_already_imported("MysticGem", items_h) is False,
                    "found")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        _fail("item icon detect", str(e))

    # ── Asset browser _render_bar tests ───────────────────────────────

    # Test 170: _render_bar at 0%, 50%, 100%
    try:
        from torch.asset_browser import _render_bar
        bar_0 = _render_bar(0, 43, width=20)
        bar_half = _render_bar(21, 43, width=20)
        bar_full = _render_bar(43, 43, width=20)
        # At 0%: all empty chars, green colour
        _assert("bar: 0% has 20 empty",
                bar_0.count("\u2591") == 20, f"got {bar_0.count(chr(0x2591))}")
        # At ~49%: mix of filled and empty, green colour
        _assert("bar: 50% has filled",
                "\u2588" in bar_half, "no filled blocks")
        _assert("bar: 50% has empty",
                "\u2591" in bar_half, "no empty blocks")
        # At 100%: all filled, red colour (93%+)
        _assert("bar: 100% has 20 filled",
                bar_full.count("\u2588") == 20, f"got {bar_full.count(chr(0x2588))}")
        _assert("bar: 100% is red",
                "\033[31m" in bar_full, "not red")
    except Exception as e:
        _fail("render_bar basic", str(e))

    # Test 171: _render_bar overshoot (used > total)
    try:
        from torch.asset_browser import _render_bar
        bar_over = _render_bar(50, 43, width=20)
        # Should clamp to 100% fill
        _assert("bar: overshoot clamps to 20 filled",
                bar_over.count("\u2588") == 20, f"got {bar_over.count(chr(0x2588))}")
        _assert("bar: overshoot is red",
                "\033[31m" in bar_over, "not red")
    except Exception as e:
        _fail("render_bar overshoot", str(e))

    # Test 172: _render_bar colour thresholds
    try:
        from torch.asset_browser import _render_bar
        bar_green = _render_bar(10, 43, width=20)   # 23% -> green
        bar_yellow = _render_bar(36, 43, width=20)   # 84% -> yellow
        bar_red = _render_bar(41, 43, width=20)      # 95% -> red
        _assert("bar: green at 23%",
                "\033[32m" in bar_green, "not green")
        _assert("bar: yellow at 84%",
                "\033[1;33m" in bar_yellow, "not yellow")
        _assert("bar: red at 95%",
                "\033[31m" in bar_red, "not red")
    except Exception as e:
        _fail("render_bar colours", str(e))

    # Test 173: _render_bar with total=0
    try:
        from torch.asset_browser import _render_bar
        bar_zero = _render_bar(0, 0, width=20)
        _assert("bar: total=0 has 20 empty",
                bar_zero.count("\u2591") == 20, f"got {bar_zero.count(chr(0x2591))}")
    except Exception as e:
        _fail("render_bar total zero", str(e))
