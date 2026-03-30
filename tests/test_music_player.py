"""Tests for music_player.py — playback engine, metadata, cache."""

import os
import shutil
import struct
import tempfile
import time

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert

# Path to real decomp (if available)
_DECOMP = os.path.expanduser("~/Documents/torch-dev")
_HAS_DECOMP = os.path.isfile(os.path.join(_DECOMP, "include", "constants", "songs.h"))


def run_suite():
    _begin_suite("Music Player  (metadata, cache, backends)")

    from torch.music_player import (
        SongInfo, MidiCfgEntry,
        find_poryaaaa, poryaaaa_available, poryaaaa_version,
        preferred_backend, find_audio_player, audio_player_name,
        parse_midi_cfg, list_songs, song_info, _format_song_name,
        _parse_songs_header,
        render_song, render_song_cached,
        cache_path, cache_clear, cache_size, cache_evict,
        play_song, stop_playback, is_playing,
        music_status,
        _render_builtin,
        _CACHE_DIR,
    )

    # ── SongInfo ──

    info = SongInfo("MUS_TEST", "Test Song", volume=80, reverb=50)
    _assert("SongInfo: constant", info.constant == "MUS_TEST")
    _assert("SongInfo: name", info.name == "Test Song")
    _assert("SongInfo: volume", info.volume == 80)
    d = info.to_dict()
    _assert("SongInfo: to_dict keys",
            "constant" in d and "name" in d and "volume" in d)
    _assert("SongInfo: to_dict values",
            d["constant"] == "MUS_TEST" and d["volume"] == 80)

    # ── MidiCfgEntry ──

    entry = MidiCfgEntry("test.mid", voicegroup="_test", volume=80)
    _assert("MidiCfgEntry: filename", entry.filename == "test.mid")
    _assert("MidiCfgEntry: voicegroup", entry.voicegroup == "_test")

    # ── Name formatting ──

    _assert("format: MUS_PETALBURG", _format_song_name("MUS_PETALBURG") == "Petalburg")
    _assert("format: SE_BALL_OPEN", _format_song_name("SE_BALL_OPEN") == "Ball Open")
    _assert("format: MUS_VS_GYM_LEADER",
            _format_song_name("MUS_VS_GYM_LEADER") == "Vs Gym Leader")

    # ── Backend detection ──

    backend = preferred_backend()
    _assert("backend: returns string", backend in ("poryaaaa", "builtin"))

    # Audio player detection (SteamOS has pw-play)
    player = find_audio_player()
    if player:
        _ok("audio_player: found")
    else:
        _skip("audio_player: found", "no audio player available")

    player_name = audio_player_name()
    if player_name:
        _assert("audio_player: name is string", isinstance(player_name, str))
    else:
        _skip("audio_player: name is string", "no audio player")

    # ── poryaaaa detection ──

    # We can't guarantee poryaaaa is installed, so just test the API
    pory = find_poryaaaa()
    if pory:
        _assert("poryaaaa: path is file", os.path.isfile(pory))
        ver = poryaaaa_version()
        _assert("poryaaaa: version not None", ver is not None,
                "poryaaaa found but version returned None")
    else:
        _ok("poryaaaa: not installed (expected)")

    _assert("poryaaaa_available: returns bool",
            isinstance(poryaaaa_available(), bool))

    # ── Cache paths ──

    p = cache_path("petalburg", "builtin")
    _assert("cache_path: contains builtin", "/builtin/" in p)
    _assert("cache_path: ends with .wav", p.endswith(".wav"))

    p2 = cache_path("MUS_PETALBURG", "poryaaaa")
    _assert("cache_path: strips prefix", "mus_" not in os.path.basename(p2))
    _assert("cache_path: poryaaaa backend", "/poryaaaa/" in p2)

    # ── Cache management ──

    # Use a temporary cache dir to avoid polluting real cache
    import torch.music_player as mp
    original_cache = mp._CACHE_DIR
    tmp_cache = tempfile.mkdtemp(prefix="torch_music_cache_")
    mp._CACHE_DIR = tmp_cache

    try:
        _assert("cache_size: empty = 0", cache_size() == 0)

        # Create a fake cached file
        backend_dir = os.path.join(tmp_cache, "builtin")
        os.makedirs(backend_dir, exist_ok=True)
        fake_wav = os.path.join(backend_dir, "test.wav")
        with open(fake_wav, "wb") as f:
            f.write(b"\x00" * 1000)

        _assert("cache_size: after add", cache_size() == 1000)

        # Clear specific song
        cache_clear("test")
        _assert("cache_clear: specific song", not os.path.exists(fake_wav))

        # Recreate for eviction test
        os.makedirs(backend_dir, exist_ok=True)
        for i in range(5):
            p = os.path.join(backend_dir, f"song{i}.wav")
            with open(p, "wb") as f:
                f.write(b"\x00" * 1000)
            time.sleep(0.01)  # ensure different mtime

        _assert("cache_size: 5 files", cache_size() == 5000)

        # Evict to keep only 3000 bytes
        cache_evict(3000)
        _assert("cache_evict: reduced", cache_size() <= 3000)

        # Clear all
        cache_clear()
        _assert("cache_clear: all gone", cache_size() == 0)

    finally:
        mp._CACHE_DIR = original_cache
        shutil.rmtree(tmp_cache, ignore_errors=True)

    # ── Music status ──

    status = music_status()
    _assert("status: has backend", "backend" in status)
    _assert("status: has backend_label", "backend_label" in status)
    _assert("status: has audio_player", "audio_player" in status)
    _assert("status: has cache_size_mb", "cache_size_mb" in status)

    # ── Playback state ──

    _assert("is_playing: initially False", not is_playing())
    stop_playback()  # should not error
    _ok("stop_playback: no-op when nothing playing")

    # ── Real decomp tests ──

    if not _HAS_DECOMP:
        _skip("real: decomp tests", "torch-dev decomp not available")
        return

    # midi.cfg parsing
    cfg = parse_midi_cfg(_DECOMP)
    _assert("real: midi.cfg count", len(cfg) > 100,
            f"only {len(cfg)} entries")

    entry = cfg.get("mus_petalburg.mid")
    _assert("real: petalburg in cfg", entry is not None)
    if entry:
        _assert("real: petalburg voicegroup", entry.voicegroup == "_petalburg")
        _assert("real: petalburg volume", entry.volume == 80)
        _assert("real: petalburg reverb", entry.reverb == 50)

    # songs.h parsing
    header = _parse_songs_header(_DECOMP)
    _assert("real: songs.h entries", len(header) > 200,
            f"only {len(header)} entries")

    # Song listing
    songs = list_songs(_DECOMP)
    _assert("real: total songs", len(songs) > 300, f"only {len(songs)}")

    mus = [s for s in songs if s.constant.startswith("MUS_")]
    se = [s for s in songs if s.constant.startswith("SE_")]
    _assert("real: has MUS_ songs", len(mus) > 100)
    _assert("real: has SE_ songs", len(se) > 100)

    # Filter types
    music_only = list_songs(_DECOMP, filter_type="music")
    sfx_only = list_songs(_DECOMP, filter_type="sfx")
    _assert("real: music filter", all(s.constant.startswith("MUS_") for s in music_only))
    _assert("real: sfx filter", all(s.constant.startswith("SE_") for s in sfx_only))

    # Single song info
    info = song_info(_DECOMP, "petalburg")
    _assert("real: song_info by stem", info is not None)
    if info:
        _assert("real: info name", info.name == "Petalburg")
        _assert("real: info midi_file", info.midi_file is not None)
        _assert("real: info voicegroup", info.voicegroup == "_petalburg")

    info2 = song_info(_DECOMP, "MUS_PETALBURG")
    _assert("real: song_info by constant", info2 is not None)

    info3 = song_info(_DECOMP, "nonexistent_song_xyz")
    _assert("real: song_info miss", info3 is None)

    # MUS songs with MIDI files
    with_midi = [s for s in mus if s.midi_file]
    _assert("real: MUS with MIDI files", len(with_midi) > 100,
            f"only {len(with_midi)}")

    # Vanilla detection
    vanilla_mus = [s for s in mus if not s.is_custom]
    _assert("real: vanilla detection works", len(vanilla_mus) > 50,
            f"only {len(vanilla_mus)} vanilla (expected most of {len(mus)})")

    # ── Built-in render test ──

    tmp_dir = tempfile.mkdtemp(prefix="torch_music_render_")
    try:
        out = os.path.join(tmp_dir, "test.wav")
        ok = _render_builtin(_DECOMP, "petalburg", out, sample_rate=11025,
                             duration=5)
        _assert("real: builtin render petalburg", ok)
        if ok:
            _assert("real: output file exists", os.path.isfile(out))
            _assert("real: output file > 0", os.path.getsize(out) > 0)

        # Nonexistent song
        ok2 = _render_builtin(_DECOMP, "nonexistent_xyz", out)
        _assert("real: builtin render miss → False", not ok2)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Cached render test ──

    original_cache = mp._CACHE_DIR
    tmp_cache = tempfile.mkdtemp(prefix="torch_music_cache_")
    mp._CACHE_DIR = tmp_cache

    try:
        wav = render_song_cached(_DECOMP, "birch_lab")
        _assert("real: cached render returns path", wav is not None)
        if wav:
            _assert("real: cached file exists", os.path.isfile(wav))
            _assert("real: cached file > 0", os.path.getsize(wav) > 0)

        # Second call should use cache (much faster)
        t0 = time.monotonic()
        wav2 = render_song_cached(_DECOMP, "birch_lab")
        t1 = time.monotonic()
        _assert("real: cache hit returns same path", wav2 == wav)
        _assert("real: cache hit is fast", t1 - t0 < 0.5,
                f"took {t1 - t0:.2f}s")
    finally:
        mp._CACHE_DIR = original_cache
        shutil.rmtree(tmp_cache, ignore_errors=True)
