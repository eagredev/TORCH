"""Tileset Assistant suite -- scanning, creation, health check, registration."""
import os
import json
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _assert
from torch.tileset_assistant import (
    _derive_names, _tileset_const, _detect_compression,
    _scan_tilesets, _get_tileset_maps,
    _check_tileset_health, _check_registration, _check_orphaned_registrations,
    _create_empty_gbapal, _create_empty_pal, _create_tileset_scaffold,
    _copy_tileset_dir, _register_tileset,
    create_tileset_copy, create_tileset_scaffold,
    _convert_metatile_attributes_data,
    repair_metatile_attributes,
    _PALETTE_COUNT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_game(tmp):
    """Create a minimal game directory with tileset infrastructure."""
    game = os.path.join(tmp, "game")

    # tileset directories
    for name in ("cave", "petalburg"):
        ts_dir = os.path.join(game, "data", "tilesets", "secondary", name)
        pal_dir = os.path.join(ts_dir, "palettes")
        os.makedirs(pal_dir)
        # binary files
        with open(os.path.join(ts_dir, "metatiles.bin"), "wb") as f:
            f.write(b'\x00' * 16)
        with open(os.path.join(ts_dir, "metatile_attributes.bin"), "wb") as f:
            f.write(b'\x00' * 16)
        with open(os.path.join(ts_dir, "tiles.png"), "wb") as f:
            f.write(b'\x89PNG')  # fake PNG header
        # tiles.4bpp.fastSmol for compression detection
        with open(os.path.join(ts_dir, "tiles.4bpp.fastSmol"), "wb") as f:
            f.write(b'\x00')
        # palettes
        for i in range(16):
            with open(os.path.join(pal_dir, f"{i:02d}.gbapal"), "wb") as f:
                f.write(b'\x00' * 32)
            with open(os.path.join(pal_dir, f"{i:02d}.pal"), "w") as f:
                f.write("JASC-PAL\n0100\n16\n" + "0 0 0\n" * 16)

    # primary tileset
    gen_dir = os.path.join(game, "data", "tilesets", "primary", "general")
    os.makedirs(os.path.join(gen_dir, "palettes"))
    with open(os.path.join(gen_dir, "metatiles.bin"), "wb") as f:
        f.write(b'\x00' * 16)
    with open(os.path.join(gen_dir, "metatile_attributes.bin"), "wb") as f:
        f.write(b'\x00' * 16)
    with open(os.path.join(gen_dir, "tiles.png"), "wb") as f:
        f.write(b'\x89PNG')
    for i in range(16):
        with open(os.path.join(gen_dir, "palettes", f"{i:02d}.gbapal"), "wb") as f:
            f.write(b'\x00' * 32)

    # C headers
    src_dir = os.path.join(game, "src", "data", "tilesets")
    os.makedirs(src_dir)

    with open(os.path.join(src_dir, "graphics.h"), "w") as f:
        f.write(
            'const u32 gTilesetTiles_Cave[] = INCBIN_U32("data/tilesets/secondary/cave/tiles.4bpp.fastSmol");\n'
            '\n'
            'const u16 gTilesetPalettes_Cave[][16] =\n'
            '{\n'
        )
        for i in range(16):
            f.write(f'    INCBIN_U16("data/tilesets/secondary/cave/palettes/{i:02d}.gbapal"),\n')
        f.write('};\n\n')
        f.write(
            'const u32 gTilesetTiles_Petalburg[] = INCBIN_U32("data/tilesets/secondary/petalburg/tiles.4bpp.fastSmol");\n'
            '\n'
            'const u16 gTilesetPalettes_Petalburg[][16] =\n'
            '{\n'
        )
        for i in range(16):
            f.write(f'    INCBIN_U16("data/tilesets/secondary/petalburg/palettes/{i:02d}.gbapal"),\n')
        f.write('};\n')

    with open(os.path.join(src_dir, "metatiles.h"), "w") as f:
        f.write(
            'const u16 gMetatiles_Cave[] = INCBIN_U16("data/tilesets/secondary/cave/metatiles.bin");\n'
            'const u16 gMetatileAttributes_Cave[] = INCBIN_U16("data/tilesets/secondary/cave/metatile_attributes.bin");\n'
            '\n'
            'const u16 gMetatiles_Petalburg[] = INCBIN_U16("data/tilesets/secondary/petalburg/metatiles.bin");\n'
            'const u16 gMetatileAttributes_Petalburg[] = INCBIN_U16("data/tilesets/secondary/petalburg/metatile_attributes.bin");\n'
        )

    with open(os.path.join(src_dir, "headers.h"), "w") as f:
        f.write(
            '#include "fieldmap.h"\n'
            '\n'
            'const struct Tileset gTileset_Cave =\n'
            '{\n'
            '    .isCompressed = TRUE,\n'
            '    .isSecondary = TRUE,\n'
            '    .tiles = gTilesetTiles_Cave,\n'
            '    .palettes = gTilesetPalettes_Cave,\n'
            '    .metatiles = gMetatiles_Cave,\n'
            '    .metatileAttributes = gMetatileAttributes_Cave,\n'
            '    .callback = NULL,\n'
            '};\n'
            '\n'
            'const struct Tileset gTileset_Petalburg =\n'
            '{\n'
            '    .isCompressed = TRUE,\n'
            '    .isSecondary = TRUE,\n'
            '    .tiles = gTilesetTiles_Petalburg,\n'
            '    .palettes = gTilesetPalettes_Petalburg,\n'
            '    .metatiles = gMetatiles_Petalburg,\n'
            '    .metatileAttributes = gMetatileAttributes_Petalburg,\n'
            '    .callback = NULL,\n'
            '};\n'
        )

    # layouts.json
    layouts_dir = os.path.join(game, "data", "layouts")
    os.makedirs(layouts_dir)
    layouts = {
        "layouts_table_label": "gMapLayouts",
        "layouts": [
            {
                "id": "LAYOUT_ROUTE_101",
                "name": "Route101_Layout",
                "primary_tileset": "gTileset_General",
                "secondary_tileset": "gTileset_Cave",
            },
            {
                "id": "LAYOUT_PETALBURG",
                "name": "PetalburgCity_Layout",
                "primary_tileset": "gTileset_General",
                "secondary_tileset": "gTileset_Petalburg",
            },
            {
                "id": "LAYOUT_PETALBURG_GYM",
                "name": "PetalburgCityGym_Layout",
                "primary_tileset": "gTileset_General",
                "secondary_tileset": "gTileset_Petalburg",
            },
        ],
    }
    with open(os.path.join(layouts_dir, "layouts.json"), "w") as f:
        json.dump(layouts, f)

    return game


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def run_suite():
    _begin_suite("test_tileset_assistant")

    # 1. Name derivation: user input -> CamelCase + directory
    camel, dir_name = _derive_names("my cave")
    _assert("name_derive_basic",
            camel == "MyCave" and dir_name == "my_cave",
            f"got ({camel}, {dir_name})")

    camel2, dir2 = _derive_names("MyCave")
    _assert("name_derive_camelcase",
            camel2 == "MyCave" and dir2 == "my_cave",
            f"got ({camel2}, {dir2})")

    camel3, dir3 = _derive_names("police station")
    _assert("name_derive_multi_word",
            camel3 == "PoliceStation" and dir3 == "police_station",
            f"got ({camel3}, {dir3})")

    camel4, dir4 = _derive_names("")
    _assert("name_derive_empty", camel4 is None and dir4 is None,
            f"got ({camel4}, {dir4})")

    # 2. Tileset constant
    _assert("tileset_const", _tileset_const("MyCave") == "gTileset_MyCave")

    with tempfile.TemporaryDirectory() as tmp:
        game = _setup_game(tmp)

        # 3. Scan tilesets: finds primary + secondary
        tilesets = _scan_tilesets(game)
        names = {t["dir_name"] for t in tilesets}
        _assert("scan_finds_secondary",
                "cave" in names and "petalburg" in names,
                f"found: {names}")
        _assert("scan_finds_primary",
                "general" in names,
                f"found: {names}")
        kinds = {t["dir_name"]: t["kind"] for t in tilesets}
        _assert("scan_kind_correct",
                kinds.get("cave") == "secondary" and kinds.get("general") == "primary",
                f"kinds: {kinds}")

        # 4. Registration detection
        regs = {t["dir_name"]: t["registered"] for t in tilesets}
        _assert("scan_registration",
                regs.get("cave") is True and regs.get("petalburg") is True,
                f"regs: {regs}")
        # General is NOT in the test headers.h (only Cave and Petalburg)
        _assert("scan_unregistered",
                regs.get("general") is False,
                f"general registered: {regs.get('general')}")

        # 5. Map usage
        usage = _get_tileset_maps(game)
        _assert("map_usage_cave",
                len(usage.get("gTileset_Cave", [])) == 1,
                f"cave maps: {usage.get('gTileset_Cave')}")
        _assert("map_usage_petalburg",
                len(usage.get("gTileset_Petalburg", [])) == 2,
                f"petalburg maps: {usage.get('gTileset_Petalburg')}")

        # 6. Compression detection
        comp = _detect_compression(game)
        _assert("compression_detect",
                comp == ".4bpp.fastSmol",
                f"got: {comp}")

        # 7. Health check — healthy tileset
        cave_ts = [t for t in tilesets if t["dir_name"] == "cave"][0]
        issues = _check_tileset_health(game, cave_ts)
        _assert("health_check_healthy",
                len(issues) == 0,
                f"unexpected issues: {issues}")

        # 8. Health check — missing palette
        os.remove(os.path.join(game, "data/tilesets/secondary/cave/palettes/14.gbapal"))
        issues2 = _check_tileset_health(game, cave_ts)
        has_pal_warning = any("14.gbapal" in msg for _, msg in issues2)
        _assert("health_check_missing_palette",
                has_pal_warning,
                f"issues: {issues2}")
        # Restore it
        with open(os.path.join(game, "data/tilesets/secondary/cave/palettes/14.gbapal"), "wb") as f:
            f.write(b'\x00' * 32)

        # 9. Health check — missing metatiles.bin
        meta_path = os.path.join(game, "data/tilesets/secondary/cave/metatiles.bin")
        os.rename(meta_path, meta_path + ".bak")
        issues3 = _check_tileset_health(game, cave_ts)
        has_meta_error = any("metatiles.bin" in msg and sev == "error"
                            for sev, msg in issues3)
        _assert("health_check_missing_metatiles",
                has_meta_error,
                f"issues: {issues3}")
        os.rename(meta_path + ".bak", meta_path)

        # 10. Health check — missing C registration
        gen_ts = [t for t in tilesets if t["dir_name"] == "general"][0]
        issues4 = _check_tileset_health(game, gen_ts)
        has_reg_error = any("Not registered" in msg for _, msg in issues4)
        _assert("health_check_unregistered",
                has_reg_error,
                f"issues: {issues4}")

        # 11. Scaffold creation
        ok, camel, dir_name, msgs = create_tileset_scaffold(game, "my dungeon")
        _assert("scaffold_success", ok is True, f"msgs: {msgs}")
        scaffold_dir = os.path.join(game, "data/tilesets/secondary/my_dungeon")
        _assert("scaffold_dir_created", os.path.isdir(scaffold_dir))
        _assert("scaffold_palettes",
                os.path.isfile(os.path.join(scaffold_dir, "palettes/00.gbapal")),
                "00.gbapal not created")
        _assert("scaffold_palette_size",
                os.path.getsize(os.path.join(scaffold_dir, "palettes/00.gbapal")) == 32,
                "gbapal should be 32 bytes")
        _assert("scaffold_pal_text",
                os.path.isfile(os.path.join(scaffold_dir, "palettes/00.pal")),
                "00.pal not created")
        _assert("scaffold_metatiles_bin",
                os.path.isfile(os.path.join(scaffold_dir, "metatiles.bin")))

        # 12. Scaffold C registration
        headers_path = os.path.join(game, "src/data/tilesets/headers.h")
        with open(headers_path) as f:
            h_text = f.read()
        _assert("scaffold_registered_headers",
                "gTileset_MyDungeon" in h_text,
                "not found in headers.h")

        gfx_path = os.path.join(game, "src/data/tilesets/graphics.h")
        with open(gfx_path) as f:
            g_text = f.read()
        _assert("scaffold_registered_graphics",
                "gTilesetTiles_MyDungeon" in g_text and "gTilesetPalettes_MyDungeon" in g_text,
                "not found in graphics.h")

        meta_h_path = os.path.join(game, "src/data/tilesets/metatiles.h")
        with open(meta_h_path) as f:
            m_text = f.read()
        _assert("scaffold_registered_metatiles",
                "gMetatiles_MyDungeon" in m_text and "gMetatileAttributes_MyDungeon" in m_text,
                "not found in metatiles.h")

        # 13. Duplicate detection
        ok2, _, _, msgs2 = create_tileset_scaffold(game, "my dungeon")
        _assert("scaffold_duplicate_blocked",
                ok2 is False and any("already exists" in m for m in msgs2),
                f"msgs: {msgs2}")

        # 14. Copy tileset
        ok3, camel3, dir3, msgs3 = create_tileset_copy(game, "cave", "dark cave")
        _assert("copy_success", ok3 is True, f"msgs: {msgs3}")
        copy_dir = os.path.join(game, "data/tilesets/secondary/dark_cave")
        _assert("copy_dir_created", os.path.isdir(copy_dir))
        _assert("copy_has_tiles",
                os.path.isfile(os.path.join(copy_dir, "tiles.png")),
                "tiles.png not copied")

        # 15. Copy C registration
        with open(headers_path) as f:
            h2 = f.read()
        _assert("copy_registered_headers",
                "gTileset_DarkCave" in h2,
                "not in headers.h")

        with open(gfx_path) as f:
            g2 = f.read()
        _assert("copy_registered_graphics",
                "gTilesetTiles_DarkCave" in g2,
                "not in graphics.h")

        # 16. Copy duplicate blocked
        ok4, _, _, msgs4 = create_tileset_copy(game, "cave", "dark cave")
        _assert("copy_duplicate_blocked",
                ok4 is False,
                f"msgs: {msgs4}")

        # 17. Copy non-existent source
        ok5, _, _, msgs5 = create_tileset_copy(game, "nonexistent", "test")
        _assert("copy_bad_source",
                ok5 is False and any("not found" in m for m in msgs5),
                f"msgs: {msgs5}")

        # 18. Orphaned registration detection
        # Add a fake entry to graphics.h pointing to non-existent dir
        with open(gfx_path, "a") as f:
            f.write('\nconst u32 gTilesetTiles_Ghost[] = INCBIN_U32("data/tilesets/secondary/ghost/tiles.4bpp.fastSmol");\n')
        orphans = _check_orphaned_registrations(game)
        _assert("orphan_detection",
                any("Ghost" in c for c, _ in orphans),
                f"orphans: {orphans}")

        # 19. Empty gbapal creation
        with tempfile.NamedTemporaryFile(suffix=".gbapal", delete=False) as tf:
            pal_path = tf.name
        try:
            _create_empty_gbapal(pal_path)
            _assert("empty_gbapal_size",
                    os.path.getsize(pal_path) == 32)
            with open(pal_path, "rb") as f:
                data = f.read()
            _assert("empty_gbapal_content",
                    data == b'\x00' * 32)
        finally:
            os.unlink(pal_path)

        # 20. Empty pal text creation
        with tempfile.NamedTemporaryFile(suffix=".pal", delete=False, mode="w") as tf:
            pal_text_path = tf.name
        try:
            _create_empty_pal(pal_text_path)
            with open(pal_text_path) as f:
                content = f.read()
            _assert("empty_pal_header",
                    content.startswith("JASC-PAL\n0100\n16\n"))
            lines = content.strip().split("\n")
            _assert("empty_pal_16_colors",
                    len(lines) == 19,  # header(3) + 16 colors
                    f"got {len(lines)} lines")
        finally:
            os.unlink(pal_text_path)

        # ---------------------------------------------------------------
        # Metatile attribute conversion tests
        # ---------------------------------------------------------------
        import struct

        # 21. FR->Emerald basic: behavior=0x42, layer=0 (NORMAL)
        fr_val = 0x42  # behavior only, layer=0
        fr_data = struct.pack('<I', fr_val)
        out, warns = _convert_metatile_attributes_data(fr_data, 4, 2)
        em_val = struct.unpack('<H', out)[0]
        _assert("attr_4to2_basic",
                em_val == 0x0042,
                f"expected 0x0042, got 0x{em_val:04X}")

        # 22. FR->Emerald layer preserved: behavior=0x69, layer=1 (COVERED)
        fr_val2 = 0x69 | (1 << 29)  # behavior + COVERED
        fr_data2 = struct.pack('<I', fr_val2)
        out2, _ = _convert_metatile_attributes_data(fr_data2, 4, 2)
        em_val2 = struct.unpack('<H', out2)[0]
        _assert("attr_4to2_layer_covered",
                em_val2 == (0x69 | (1 << 12)),
                f"expected 0x{0x69 | (1 << 12):04X}, got 0x{em_val2:04X}")

        # 23. FR->Emerald layer SPLIT: layer=2
        fr_val3 = 0x01 | (2 << 29)
        fr_data3 = struct.pack('<I', fr_val3)
        out3, _ = _convert_metatile_attributes_data(fr_data3, 4, 2)
        em_val3 = struct.unpack('<H', out3)[0]
        _assert("attr_4to2_layer_split",
                em_val3 == (0x01 | (2 << 12)),
                f"expected 0x{0x01 | (2 << 12):04X}, got 0x{em_val3:04X}")

        # 24. FR->Emerald behavior clamp: behavior=0x100 (9-bit, exceeds 8-bit)
        fr_val4 = 0x100 | (1 << 29)
        fr_data4 = struct.pack('<I', fr_val4)
        out4, warns4 = _convert_metatile_attributes_data(fr_data4, 4, 2)
        em_val4 = struct.unpack('<H', out4)[0]
        _assert("attr_4to2_behavior_clamp",
                (em_val4 & 0xFF) == 0x00 and len(warns4) > 0,
                f"val=0x{em_val4:04X}, warns={warns4}")

        # 25. FR->Emerald terrain stripped: terrain+encounter set, must not
        # leak into Emerald bits 8-11
        fr_val5 = 0x42 | (3 << 9) | (1 << 24) | (1 << 29)  # behavior + terrain + encounter + layer
        fr_data5 = struct.pack('<I', fr_val5)
        out5, _ = _convert_metatile_attributes_data(fr_data5, 4, 2)
        em_val5 = struct.unpack('<H', out5)[0]
        padding_bits = (em_val5 >> 8) & 0xF  # bits 8-11 must be zero
        _assert("attr_4to2_terrain_stripped",
                padding_bits == 0,
                f"bits 8-11 = 0x{padding_bits:X}, should be 0")

        # 26. FR->Emerald multi: sequence of 5 metatiles
        layers = [0, 1, 1, 0, 2]
        multi_data = b''
        for layer in layers:
            multi_data += struct.pack('<I', 0x10 | (layer << 29))
        out6, _ = _convert_metatile_attributes_data(multi_data, 4, 2)
        _assert("attr_4to2_multi_count",
                len(out6) == 10, f"expected 10 bytes, got {len(out6)}")
        for j, expected_layer in enumerate(layers):
            v = struct.unpack_from('<H', out6, j * 2)[0]
            got_layer = (v >> 12) & 0xF
            _assert(f"attr_4to2_multi_layer_{j}",
                    got_layer == expected_layer,
                    f"metatile {j}: expected layer {expected_layer}, got {got_layer}")

        # 27. Emerald->FR basic: behavior=0x42, layer=1
        em_src = struct.pack('<H', 0x42 | (1 << 12))
        out7, _ = _convert_metatile_attributes_data(em_src, 2, 4)
        fr_result = struct.unpack('<I', out7)[0]
        _assert("attr_2to4_basic",
                fr_result == (0x42 | (1 << 29)),
                f"expected 0x{0x42 | (1 << 29):08X}, got 0x{fr_result:08X}")

        # 28. Roundtrip: 4->2->4 preserves behavior and layer
        original = struct.pack('<I', 0x55 | (2 << 29))
        mid, _ = _convert_metatile_attributes_data(original, 4, 2)
        back, _ = _convert_metatile_attributes_data(mid, 2, 4)
        orig_val = struct.unpack('<I', original)[0]
        back_val = struct.unpack('<I', back)[0]
        orig_beh = orig_val & 0x1FF
        orig_layer = (orig_val >> 29) & 0x3
        back_beh = back_val & 0x1FF
        back_layer = (back_val >> 29) & 0x3
        _assert("attr_roundtrip",
                orig_beh == back_beh and orig_layer == back_layer,
                f"orig=({orig_beh},{orig_layer}), back=({back_beh},{back_layer})")

        # 29. Same format: identity copy
        same_data = b'\x42\x10\x55\x20'
        out9, warns9 = _convert_metatile_attributes_data(same_data, 2, 2)
        _assert("attr_same_format", out9 == same_data and len(warns9) == 0)

        # 30. Empty data
        out10, warns10 = _convert_metatile_attributes_data(b'', 4, 2)
        _assert("attr_empty_data", out10 == b'' and len(warns10) == 0)

        # ---------------------------------------------------------------
        # Repair tool tests
        # ---------------------------------------------------------------

        # 31. Repair with known data
        repair_tmp = os.path.join(tmp, "repair_test")
        os.makedirs(repair_tmp)

        # Create a mock game with Emerald fieldmap.h
        repair_game = os.path.join(repair_tmp, "game")
        os.makedirs(os.path.join(repair_game, "include"))
        with open(os.path.join(repair_game, "include", "global.fieldmap.h"), "w") as f:
            f.write("#define METATILE_ATTR_LAYER_MASK 0xF000\n")

        # Create target tileset with broken (all-zero) attributes
        target_ts = os.path.join(repair_game, "data", "tilesets", "secondary", "test_ts")
        os.makedirs(target_ts)
        broken_attrs = struct.pack('<HH', 0x0042, 0x0069)  # no layer type
        with open(os.path.join(target_ts, "metatile_attributes.bin"), "wb") as f:
            f.write(broken_attrs)

        # Create source (FireRed format) with correct layer data
        source_ts = os.path.join(repair_tmp, "source_ts")
        os.makedirs(source_ts)
        fr_attrs = struct.pack('<II',
                               0x42 | (1 << 29),   # behavior=0x42, layer=COVERED
                               0x69 | (2 << 29))   # behavior=0x69, layer=SPLIT
        with open(os.path.join(source_ts, "metatile_attributes.bin"), "wb") as f:
            f.write(fr_attrs)
        # metatiles.bin to help format detection (8 tiles per metatile = 16 bytes each)
        with open(os.path.join(source_ts, "metatiles.bin"), "wb") as f:
            f.write(b'\x00' * 32)  # 2 metatiles

        ok_r, msgs_r = repair_metatile_attributes(
            repair_game, "test_ts", source_ts)
        _assert("repair_basic", ok_r, f"msgs: {msgs_r}")

        # Verify the repaired file
        with open(os.path.join(target_ts, "metatile_attributes.bin"), "rb") as f:
            repaired = f.read()
        r0 = struct.unpack_from('<H', repaired, 0)[0]
        r1 = struct.unpack_from('<H', repaired, 2)[0]
        _assert("repair_layer_0",
                (r0 >> 12) & 0xF == 1,
                f"metatile 0 layer: expected 1, got {(r0 >> 12) & 0xF}")
        _assert("repair_layer_1",
                (r1 >> 12) & 0xF == 2,
                f"metatile 1 layer: expected 2, got {(r1 >> 12) & 0xF}")

        # 32. Backup was created
        _assert("repair_backup_created",
                os.path.isfile(os.path.join(target_ts, "metatile_attributes.bin.bak")))

        # 33. Source missing
        ok_sm, _ = repair_metatile_attributes(
            repair_game, "test_ts", "/nonexistent/path")
        _assert("repair_source_missing", not ok_sm)

        # 34. Target tileset missing
        ok_tm, _ = repair_metatile_attributes(
            repair_game, "nonexistent_ts", source_ts)
        _assert("repair_tileset_missing", not ok_tm)
