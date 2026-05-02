"""Asset Browser suite -- scanners, filtering, classification, detail assembly."""
import os
import tempfile
import shutil

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def _make_trainers_h(consts):
    """Build a minimal include/constants/trainers.h with given (name, id) pairs."""
    lines = ["#ifndef GUARD_TRAINERS_H\n", "#define GUARD_TRAINERS_H\n", "\n"]
    for name, val in consts:
        lines.append(f"#define {name:<38}{val}\n")
    count = max((v for _, v in consts), default=-1) + 1
    lines.append(f"#define TRAINER_PIC_COUNT{' ' * (38 - len('TRAINER_PIC_COUNT'))}{count}\n")
    lines.append("\n#endif\n")
    return "".join(lines)


def _make_event_objects_h(consts):
    """Build a minimal include/constants/event_objects.h."""
    lines = ["#ifndef GUARD_EVENT_OBJECTS_H\n", "#define GUARD_EVENT_OBJECTS_H\n", "\n"]
    for name, val in consts:
        lines.append(f"#define {name:<42}{val}\n")
    count = max((v for _, v in consts), default=-1) + 1
    lines.append(f"#define NUM_OBJ_EVENT_GFX{' ' * 24}{count}\n")
    lines.append("\n#endif\n")
    return "".join(lines)


def _make_songs_h(se_consts, mus_consts):
    """Build a minimal include/constants/songs.h."""
    lines = ["#ifndef GUARD_SONGS_H\n", "#define GUARD_SONGS_H\n", "\n"]
    for name, val in se_consts:
        lines.append(f"#define {name:<38}{val}\n")
    lines.append(f"\n#define MUS_DUMMY{' ' * 29}0\n")
    for name, val in mus_consts:
        lines.append(f"#define {name:<38}{val}\n")
    lines.append(f"\n#define MUS_NONE{' ' * 30}0xFFFF\n")
    lines.append("\n#endif\n")
    return "".join(lines)


def _make_trainers_data_h(entries):
    """Build a minimal src/data/trainers.h with trainerPic entries.

    entries: list of (trainer_const, pic_const) tuples.
    """
    lines = []
    for trainer, pic in entries:
        lines.append(f"    [DIFFICULTY_NORMAL][{trainer}] =\n")
        lines.append("    {\n")
        lines.append(f"        .trainerPic = {pic},\n")
        lines.append("    },\n")
    return "".join(lines)


def _setup_game_dir(tmp, trainers_h_content="", event_objects_h="",
                    songs_h="", trainers_data_h="", front_pics=None,
                    tilesets=None, songs_dirs=None):
    """Create a minimal game directory structure for testing."""
    game = os.path.join(tmp, "game")

    # include/constants/
    inc_dir = os.path.join(game, "include", "constants")
    os.makedirs(inc_dir)
    if trainers_h_content:
        with open(os.path.join(inc_dir, "trainers.h"), "w") as f:
            f.write(trainers_h_content)
    if event_objects_h:
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write(event_objects_h)
    if songs_h:
        with open(os.path.join(inc_dir, "songs.h"), "w") as f:
            f.write(songs_h)

    # graphics/trainers/front_pics/
    pics_dir = os.path.join(game, "graphics", "trainers", "front_pics")
    os.makedirs(pics_dir)
    if front_pics:
        for stem in front_pics:
            with open(os.path.join(pics_dir, f"{stem}.png"), "w") as f:
                f.write("fake")

    # src/data/trainers.h (data file)
    if trainers_data_h:
        data_dir = os.path.join(game, "src", "data")
        os.makedirs(data_dir)
        with open(os.path.join(data_dir, "trainers.h"), "w") as f:
            f.write(trainers_data_h)

    # data/tilesets/secondary/
    if tilesets:
        ts_dir = os.path.join(game, "data", "tilesets", "secondary")
        os.makedirs(ts_dir)
        for ts in tilesets:
            os.makedirs(os.path.join(ts_dir, ts))

    # sound/songs/
    if songs_dirs:
        songs_dir = os.path.join(game, "sound", "songs")
        os.makedirs(songs_dir)
        for sd in songs_dirs:
            os.makedirs(os.path.join(songs_dir, sd))

    return game


def run_suite():
    _begin_suite("AssetBrowser")

    try:
        from torch.asset_browser import (
            _parse_defines,
            _fmt_name,
            _scan_trainer_sprites,
            _scan_overworld_sprites,
            _scan_music_tracks,
            _scan_sound_effects,
            _scan_tilesets,
            _filter_assets,
            _search_assets,
            _build_sprite_trainer_map,
            VANILLA_TRAINER_PICS,
        )
    except ImportError as e:
        _skip("all asset_browser tests", f"import failed: {e}")
        return

    # ------------------------------------------------------------------
    # T1: _parse_defines — basic header parsing
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        hdr = os.path.join(tmp, "test.h")
        with open(hdr, "w") as f:
            f.write("#define FOO_A 0\n")
            f.write("#define FOO_B 1\n")
            f.write("#define FOO_COUNT 2\n")
            f.write("#define BAR_X 10\n")
        result = _parse_defines(hdr, "FOO_")
        _assert("parse_defines basic",
                len(result) == 2 and result[0] == ("FOO_A", 0) and result[1] == ("FOO_B", 1),
                f"got {result}")
    except Exception as e:
        _fail("parse_defines basic", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T2: _parse_defines — skips COUNT sentinel
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        hdr = os.path.join(tmp, "test.h")
        with open(hdr, "w") as f:
            f.write("#define TRAINER_PIC_HIKER 0\n")
            f.write("#define TRAINER_PIC_COUNT 1\n")
        result = _parse_defines(hdr, "TRAINER_PIC_")
        _assert("parse_defines skips COUNT",
                len(result) == 1 and result[0][0] == "TRAINER_PIC_HIKER",
                f"got {result}")
    except Exception as e:
        _fail("parse_defines skips COUNT", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T3: _parse_defines — nonexistent file returns empty
    # ------------------------------------------------------------------
    result = _parse_defines("/tmp/nonexistent_torch_test_42.h", "FOO_")
    _assert("parse_defines nonexistent", result == [], f"got {result}")

    # ------------------------------------------------------------------
    # T4: _fmt_name — strips prefix and title-cases
    # ------------------------------------------------------------------
    _assert("fmt_name trainer pic",
            _fmt_name("TRAINER_PIC_AQUA_GRUNT_M", "TRAINER_PIC_") == "Aqua Grunt M",
            f"got {_fmt_name('TRAINER_PIC_AQUA_GRUNT_M', 'TRAINER_PIC_')}")
    _assert("fmt_name empty",
            _fmt_name("", "FOO_") == "?",
            "expected '?'")
    _assert("fmt_name no prefix match",
            _fmt_name("BAR_THING", "FOO_") == "Bar Thing",
            f"got {_fmt_name('BAR_THING', 'FOO_')}")

    # ------------------------------------------------------------------
    # T5: Trainer sprite scanner — detects vanilla and custom
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        consts = [
            ("TRAINER_PIC_HIKER", 0),
            ("TRAINER_PIC_COOLTRAINER_M", 1),
            ("TRAINER_PIC_MY_CUSTOM", 2),
        ]
        game = _setup_game_dir(tmp,
            trainers_h_content=_make_trainers_h(consts),
            front_pics=["hiker", "cooltrainer_m", "my_custom"])
        sprites = _scan_trainer_sprites(game)
        _assert("scan trainer sprites count", len(sprites) == 3,
                f"expected 3, got {len(sprites)}")
        customs = [s for s in sprites if s["is_custom"]]
        _assert("scan trainer sprites custom detection",
                len(customs) == 1 and customs[0]["constant"] == "TRAINER_PIC_MY_CUSTOM",
                f"customs: {customs}")
        vanillas = [s for s in sprites if not s["is_custom"]]
        _assert("scan trainer sprites vanilla detection",
                len(vanillas) == 2,
                f"expected 2 vanilla, got {len(vanillas)}")
    except Exception as e:
        _fail("scan trainer sprites", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T6: Trainer sprite scanner — missing file clears file path
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        consts = [("TRAINER_PIC_HIKER", 0)]
        game = _setup_game_dir(tmp,
            trainers_h_content=_make_trainers_h(consts),
            front_pics=[])  # no actual files
        sprites = _scan_trainer_sprites(game)
        _assert("scan trainer sprites missing file",
                len(sprites) == 1 and sprites[0]["file"] == "",
                f"expected empty file, got '{sprites[0]['file'] if sprites else 'none'}'")
    except Exception as e:
        _fail("scan trainer sprites missing file", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T7: Overworld sprite scanner
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        consts = [
            ("OBJ_EVENT_GFX_BRENDAN_NORMAL", 0),
            ("OBJ_EVENT_GFX_NINJA_BOY", 1),
        ]
        game = _setup_game_dir(tmp,
            event_objects_h=_make_event_objects_h(consts))
        sprites = _scan_overworld_sprites(game)
        _assert("scan overworld sprites count", len(sprites) == 2,
                f"expected 2, got {len(sprites)}")
        _assert("scan overworld sprites names",
                sprites[0]["name"] == "Brendan Normal" and sprites[1]["name"] == "Ninja Boy",
                f"got {[s['name'] for s in sprites]}")
    except Exception as e:
        _fail("scan overworld sprites", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T8: Music track scanner
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        mus_consts = [
            ("MUS_LITTLEROOT", 350),
            ("MUS_ROUTE101", 351),
        ]
        game = _setup_game_dir(tmp,
            songs_h=_make_songs_h([], mus_consts),
            songs_dirs=["littleroot"])
        tracks = _scan_music_tracks(game)
        _assert("scan music tracks count", len(tracks) == 2,
                f"expected 2, got {len(tracks)}")
        # First track has a matching directory
        lr = [t for t in tracks if t["constant"] == "MUS_LITTLEROOT"]
        _assert("scan music tracks file path",
                len(lr) == 1 and lr[0]["file"] != "",
                f"got {lr}")
        # Second track has no directory
        rt = [t for t in tracks if t["constant"] == "MUS_ROUTE101"]
        _assert("scan music tracks no file",
                len(rt) == 1 and rt[0]["file"] == "",
                f"got {rt}")
    except Exception as e:
        _fail("scan music tracks", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T9: Sound effects scanner
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        se_consts = [
            ("SE_USE_ITEM", 1),
            ("SE_PC_LOGIN", 2),
            ("SE_DOOR", 3),
        ]
        game = _setup_game_dir(tmp,
            songs_h=_make_songs_h(se_consts, []))
        effects = _scan_sound_effects(game)
        _assert("scan sound effects count", len(effects) == 3,
                f"expected 3, got {len(effects)}")
        _assert("scan sound effects names",
                effects[0]["name"] == "Use Item",
                f"got '{effects[0]['name']}'")
    except Exception as e:
        _fail("scan sound effects", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T10: Tileset scanner
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        game = _setup_game_dir(tmp, tilesets=["cave", "fortree", "my_custom_ts"])
        tilesets = _scan_tilesets(game)
        _assert("scan tilesets count", len(tilesets) == 3,
                f"expected 3, got {len(tilesets)}")
        _assert("scan tilesets names",
                tilesets[0]["name"] == "Cave",
                f"got '{tilesets[0]['name']}'")
    except Exception as e:
        _fail("scan tilesets", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T11: _filter_assets — all mode
    # ------------------------------------------------------------------
    assets = [
        {"is_custom": True, "name": "A", "constant": "A"},
        {"is_custom": False, "name": "B", "constant": "B"},
        {"is_custom": True, "name": "C", "constant": "C"},
    ]
    _assert("filter all", len(_filter_assets(assets, "all")) == 3, "expected 3")

    # ------------------------------------------------------------------
    # T12: _filter_assets — custom mode
    # ------------------------------------------------------------------
    custom = _filter_assets(assets, "custom")
    _assert("filter custom", len(custom) == 2 and all(a["is_custom"] for a in custom),
            f"got {len(custom)}")

    # ------------------------------------------------------------------
    # T13: _filter_assets — vanilla mode
    # ------------------------------------------------------------------
    vanilla = _filter_assets(assets, "vanilla")
    _assert("filter vanilla", len(vanilla) == 1 and not vanilla[0]["is_custom"],
            f"got {len(vanilla)}")

    # ------------------------------------------------------------------
    # T14: _search_assets — matches name and constant
    # ------------------------------------------------------------------
    assets = [
        {"name": "Rival Dawn", "constant": "TRAINER_PIC_RIVAL_DAWN"},
        {"name": "Hiker", "constant": "TRAINER_PIC_HIKER"},
    ]
    _assert("search by name",
            len(_search_assets(assets, "rival")) == 1,
            "expected 1 match for 'rival'")
    _assert("search by constant",
            len(_search_assets(assets, "HIKER")) == 1,
            "expected 1 match for 'HIKER'")
    _assert("search no match",
            len(_search_assets(assets, "zzzzz")) == 0,
            "expected 0 matches")

    # ------------------------------------------------------------------
    # T15: _search_assets — case insensitive
    # ------------------------------------------------------------------
    _assert("search case insensitive",
            len(_search_assets(assets, "RIVAL")) == 1,
            "expected 1 match for 'RIVAL' (case-insensitive)")

    # ------------------------------------------------------------------
    # T16: Vanilla reference set has correct count
    # ------------------------------------------------------------------
    _assert("vanilla trainer pics count",
            len(VANILLA_TRAINER_PICS) == 93,
            f"expected 93, got {len(VANILLA_TRAINER_PICS)}")

    # ------------------------------------------------------------------
    # T17: Vanilla reference set contains known entries
    # ------------------------------------------------------------------
    for name in ("TRAINER_PIC_HIKER", "TRAINER_PIC_STEVEN",
                 "TRAINER_PIC_RS_MAY", "TRAINER_PIC_BRENDAN"):
        _assert(f"vanilla set contains {name}",
                name in VANILLA_TRAINER_PICS,
                f"{name} missing from vanilla set")

    # ------------------------------------------------------------------
    # T18: Sprite trainer map — cross-reference
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        data_h = _make_trainers_data_h([
            ("TRAINER_SAWYER_1", "TRAINER_PIC_HIKER"),
            ("TRAINER_SAWYER_2", "TRAINER_PIC_HIKER"),
            ("TRAINER_RIVAL_1", "TRAINER_PIC_MY_CUSTOM"),
        ])
        game = _setup_game_dir(tmp, trainers_data_h=data_h)
        smap = _build_sprite_trainer_map(game)
        _assert("sprite map hiker trainers",
                "TRAINER_PIC_HIKER" in smap and len(smap["TRAINER_PIC_HIKER"]) == 2,
                f"got {smap.get('TRAINER_PIC_HIKER')}")
        _assert("sprite map custom trainers",
                "TRAINER_PIC_MY_CUSTOM" in smap and len(smap["TRAINER_PIC_MY_CUSTOM"]) == 1,
                f"got {smap.get('TRAINER_PIC_MY_CUSTOM')}")
    except Exception as e:
        _fail("sprite trainer map", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T19: Sprite trainer map — empty/missing file
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        game = _setup_game_dir(tmp)
        smap = _build_sprite_trainer_map(game)
        _assert("sprite map empty", smap == {}, f"expected empty, got {smap}")
    except Exception as e:
        _fail("sprite map empty", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T20: Music scanner — filters MUS_DUMMY and MUS_NONE
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        songs_h = (
            "#define MUS_DUMMY 0\n"
            "#define MUS_ROUTE101 350\n"
            "#define MUS_NONE 0xFFFF\n"
        )
        game = _setup_game_dir(tmp)
        # Write songs.h manually (MUS_NONE uses hex, not handled by _make_songs_h)
        inc_dir = os.path.join(game, "include", "constants")
        os.makedirs(inc_dir, exist_ok=True)
        with open(os.path.join(inc_dir, "songs.h"), "w") as f:
            f.write(songs_h)
        tracks = _scan_music_tracks(game)
        _assert("music scanner filters DUMMY/NONE",
                len(tracks) == 1 and tracks[0]["constant"] == "MUS_ROUTE101",
                f"got {[t['constant'] for t in tracks]}")
    except Exception as e:
        _fail("music scanner filters DUMMY/NONE", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T21: Tileset scanner — empty directory
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        game = _setup_game_dir(tmp)
        tilesets = _scan_tilesets(game)
        _assert("tileset scanner empty", tilesets == [],
                f"expected empty, got {len(tilesets)}")
    except Exception as e:
        _fail("tileset scanner empty", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # T22: Overworld scanner — filters NUM_OBJ_EVENT_GFX sentinel
    # ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="torch_ab_")
    try:
        hdr_content = (
            "#define OBJ_EVENT_GFX_BRENDAN_NORMAL 0\n"
            "#define NUM_OBJ_EVENT_GFX 1\n"
        )
        game = _setup_game_dir(tmp)
        inc_dir = os.path.join(game, "include", "constants")
        os.makedirs(inc_dir, exist_ok=True)
        with open(os.path.join(inc_dir, "event_objects.h"), "w") as f:
            f.write(hdr_content)
        sprites = _scan_overworld_sprites(game)
        _assert("overworld filters sentinel",
                len(sprites) == 1 and sprites[0]["constant"] == "OBJ_EVENT_GFX_BRENDAN_NORMAL",
                f"got {[s['constant'] for s in sprites]}")
    except Exception as e:
        _fail("overworld filters sentinel", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
