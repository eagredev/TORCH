"""Tests for midi_synth.py — MIDI parser and stdlib synthesizer."""

import io
import math
import os
import struct
import tempfile
import wave

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert

# Path to real MIDI files in the decomp (if available)
_DECOMP_MIDI_DIR = os.path.expanduser(
    "~/Documents/torch-dev/sound/songs/midi"
)
_HAS_DECOMP = os.path.isdir(_DECOMP_MIDI_DIR)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _encode_vlq(value):
    """Encode an integer as a MIDI variable-length quantity."""
    if value < 0:
        value = 0
    result = bytearray()
    result.append(value & 0x7F)
    value >>= 7
    while value:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.reverse()
    return bytes(result)


def _make_minimal_midi(tpq=24, tempo_us=500000, notes=None, loop=False):
    """Build a minimal Type 1 MIDI file in memory.

    notes: list of (channel, note, velocity, start_tick, end_tick)
    Returns bytes.
    """
    if notes is None:
        notes = [(0, 60, 100, 0, 48)]

    num_tracks = 2
    header = b"MThd" + struct.pack(">IHHh", 6, 1, num_tracks, tpq)

    # Tempo track
    tempo_events = bytearray()
    tempo_events += b"\x00\xff\x58\x04\x04\x02\x18\x08"
    t_bytes = tempo_us.to_bytes(3, "big")
    tempo_events += b"\x00\xff\x51\x03" + t_bytes
    if loop:
        tempo_events += b"\x00\xff\x06\x01\x5b"  # "[" at tick 0
    tempo_events += b"\x00\xff\x2f\x00"
    tempo_track = b"MTrk" + struct.pack(">I", len(tempo_events)) + bytes(tempo_events)

    # Note track
    note_events = bytearray()
    sorted_notes = sorted(notes, key=lambda n: n[3])
    all_events = []
    for ch, note, vel, start, end in sorted_notes:
        all_events.append((start, 0x90 | ch, note, vel))
        all_events.append((end, 0x80 | ch, note, 0))
    if loop:
        max_tick = max(n[4] for n in sorted_notes) if sorted_notes else 48
        all_events.append((max_tick, "loop_end", 0, 0))
    all_events.sort(key=lambda e: e[0])

    prev_tick = 0
    for evt in all_events:
        tick = evt[0]
        delta = tick - prev_tick
        prev_tick = tick
        note_events += _encode_vlq(delta)
        if evt[1] == "loop_end":
            note_events += b"\xff\x06\x01\x5d"
        else:
            status, note_num, vel = evt[1], evt[2], evt[3]
            note_events += bytes([status, note_num, vel])
    note_events += b"\x00\xff\x2f\x00"
    note_track = b"MTrk" + struct.pack(">I", len(note_events)) + bytes(note_events)

    return header + tempo_track + note_track


# ── Suite ────────────────────────────────────────────────────────────────────

def run_suite():
    _begin_suite("MIDI Synth  (parser, waveforms, rendering)")

    from torch.midi_synth import (
        MidiEvent, MidiFile, parse_midi, _parse_midi_bytes,
        _read_variable_length, render_midi, render_to_wav,
        render_midi_to_wav_bytes, render_midi_file,
        synth_available, render_quality,
        _midi_note_to_freq, _square_wave, _triangle_wave, _envelope,
        _program_to_waveform, _generate_sample,
        WAVE_SQUARE, WAVE_TRIANGLE, WAVE_NOISE, WAVE_SQUARE25,
    )

    # ── Variable-length parsing ──

    val, pos = _read_variable_length(bytes([0x00]), 0)
    _assert("vlq: zero", val == 0 and pos == 1)

    val, pos = _read_variable_length(bytes([0x7F]), 0)
    _assert("vlq: 127", val == 127 and pos == 1)

    val, pos = _read_variable_length(bytes([0x81, 0x00]), 0)
    _assert("vlq: 128 (two bytes)", val == 128 and pos == 2)

    val, pos = _read_variable_length(bytes([0x83, 0x80, 0x00]), 0)
    _assert("vlq: three bytes", val == 0xC000)

    val, pos = _read_variable_length(bytes([0xFF, 0xFF, 0x40]), 2)
    _assert("vlq: with offset", val == 64 and pos == 3)

    # VLQ roundtrip
    ok = True
    for v in [0, 1, 127, 128, 255, 16383, 16384, 100000]:
        encoded = _encode_vlq(v)
        decoded, _ = _read_variable_length(encoded, 0)
        if decoded != v:
            ok = False
            break
    _assert("vlq: roundtrip encoding", ok)

    # ── MIDI header parsing ──

    data = _make_minimal_midi()
    midi = _parse_midi_bytes(data)
    _assert("parse: minimal midi format", midi.format_type == 1)
    _assert("parse: minimal midi tracks", midi.num_tracks == 2)
    _assert("parse: minimal midi tpq", midi.ticks_per_quarter == 24)
    _assert("parse: minimal midi has events", len(midi.events) > 0)

    data = _make_minimal_midi(tpq=96)
    midi = _parse_midi_bytes(data)
    _assert("parse: custom tpq", midi.ticks_per_quarter == 96)

    try:
        _parse_midi_bytes(b"NOT_MIDI")
        _fail("parse: invalid header raises", "no exception raised")
    except ValueError:
        _ok("parse: invalid header raises")

    # ── Tempo parsing ──

    data = _make_minimal_midi(tempo_us=600000)
    midi = _parse_midi_bytes(data)
    tempos = [e for e in midi.events if e.type == "tempo"]
    _assert("parse: tempo event", len(tempos) == 1 and tempos[0].data["tempo_us"] == 600000)

    # ── Note parsing ──

    data = _make_minimal_midi(notes=[(0, 60, 100, 0, 48)])
    midi = _parse_midi_bytes(data)
    note_ons = [e for e in midi.events if e.type == "note_on"]
    note_offs = [e for e in midi.events if e.type == "note_off"]
    _assert("parse: note_on count", len(note_ons) == 1)
    _assert("parse: note_off count", len(note_offs) == 1)
    _assert("parse: note_on data", note_ons[0].data["note"] == 60 and note_ons[0].data["velocity"] == 100)

    notes = [(0, 60, 100, 0, 24), (0, 64, 80, 24, 48), (1, 48, 120, 0, 48)]
    data = _make_minimal_midi(notes=notes)
    midi = _parse_midi_bytes(data)
    note_ons = [e for e in midi.events if e.type == "note_on"]
    _assert("parse: multiple notes", len(note_ons) == 3)

    # ── Event ordering ──

    notes = [(0, 60, 100, 48, 96), (1, 72, 100, 0, 48)]
    data = _make_minimal_midi(notes=notes)
    midi = _parse_midi_bytes(data)
    ticks = [e.tick for e in midi.events]
    _assert("parse: events sorted by tick", ticks == sorted(ticks))

    # ── Loop markers ──

    data = _make_minimal_midi(loop=True)
    midi = _parse_midi_bytes(data)
    _assert("parse: loop start found", midi.loop_start_tick is not None)
    _assert("parse: loop end found", midi.loop_end_tick is not None)
    _assert("parse: loop start at 0", midi.loop_start_tick == 0)

    data = _make_minimal_midi(loop=False)
    midi = _parse_midi_bytes(data)
    _assert("parse: no loop markers", midi.loop_start_tick is None and midi.loop_end_tick is None)

    # ── MidiEvent repr ──

    ev = MidiEvent(0, "note_on", 0, {"note": 60, "velocity": 100})
    r = repr(ev)
    _assert("MidiEvent repr", "note_on" in r and "60" in r)

    # ── Waveforms ──

    _assert("square: 0.0 → +1", _square_wave(0.0) == 1.0)
    _assert("square: 0.25 → +1", _square_wave(0.25) == 1.0)
    _assert("square: 0.5 → -1", _square_wave(0.5) == -1.0)
    _assert("square: 0.75 → -1", _square_wave(0.75) == -1.0)
    _assert("square25: 0.1 → +1", _square_wave(0.1, 0.25) == 1.0)
    _assert("square25: 0.3 → -1", _square_wave(0.3, 0.25) == -1.0)

    _assert("triangle: 0.0 → 0", abs(_triangle_wave(0.0)) < 0.01)
    _assert("triangle: 0.25 → +1", abs(_triangle_wave(0.25) - 1.0) < 0.01)
    _assert("triangle: 0.5 → 0", abs(_triangle_wave(0.5)) < 0.01)
    _assert("triangle: 0.75 → -1", abs(_triangle_wave(0.75) + 1.0) < 0.01)

    ok = all(-1.0 <= _triangle_wave(i / 100.0) <= 1.0 for i in range(100))
    _assert("triangle: range [-1, +1]", ok)

    for wf in [WAVE_SQUARE, WAVE_TRIANGLE, WAVE_SQUARE25, WAVE_NOISE]:
        s = _generate_sample(wf, 0.25, 440.0, 22050)
        _assert(f"generate_sample: {wf} returns float", isinstance(s, float))

    # ── Frequency conversion ──

    _assert("freq: A4 = 440 Hz", abs(_midi_note_to_freq(69) - 440.0) < 0.1)
    _assert("freq: C4 ≈ 261 Hz", abs(_midi_note_to_freq(60) - 261.63) < 1.0)
    f1 = _midi_note_to_freq(60)
    f2 = _midi_note_to_freq(72)
    _assert("freq: octave doubling", abs(f2 / f1 - 2.0) < 0.001)
    _assert("freq: low A0", 20 < _midi_note_to_freq(21) < 30)

    # ── Program → waveform mapping ──

    _assert("program: percussion → noise", _program_to_waveform(0, 9) == WAVE_NOISE)
    _assert("program: strings → triangle", _program_to_waveform(48, 0) == WAVE_TRIANGLE)
    _assert("program: bass → square25", _program_to_waveform(33, 0) == WAVE_SQUARE25)
    _assert("program: default → square", _program_to_waveform(0, 0) == WAVE_SQUARE)

    # ── Envelope ──

    _assert("envelope: attack start ≈ 0", _envelope(0.0, 1.0, 1.08) < 0.05)
    _assert("envelope: attack peak ≈ 1", abs(_envelope(0.005, 1.0, 1.08) - 1.0) < 0.15)
    _assert("envelope: sustain ≈ 0.7", abs(_envelope(0.5, 1.0, 1.08) - 0.7) < 0.05)
    _assert("envelope: release end ≈ 0", _envelope(1.08, 1.0, 1.08) < 0.05)
    _assert("envelope: after release = 0", _envelope(2.0, 1.0, 1.08) == 0.0)
    _assert("envelope: negative time = 0", _envelope(-1.0, 1.0, 1.08) == 0.0)

    # ── Rendering ──

    data = _make_minimal_midi(notes=[(0, 60, 100, 0, 48)])
    midi = _parse_midi_bytes(data)
    pcm = render_midi(midi, sample_rate=11025, max_duration=5)
    _assert("render: returns bytes", isinstance(pcm, bytes))
    _assert("render: non-empty", len(pcm) > 0)
    _assert("render: even length (16-bit)", len(pcm) % 2 == 0)

    # Empty MIDI produces silence
    midi_empty = MidiFile()
    midi_empty.events = []
    pcm = render_midi(midi_empty, sample_rate=11025, max_duration=1)
    _assert("render: empty midi → silence", len(pcm) > 0)

    # Max duration respected
    data = _make_minimal_midi(notes=[(0, 60, 100, 0, 480)], tpq=24, tempo_us=500000)
    midi = _parse_midi_bytes(data)
    pcm = render_midi(midi, sample_rate=11025, max_duration=2)
    max_bytes = 2 * 2 * 11025 + 6000
    _assert("render: max_duration cap", len(pcm) <= max_bytes)

    # Loop extends duration
    data = _make_minimal_midi(notes=[(0, 60, 100, 0, 48)], tpq=24, tempo_us=500000, loop=True)
    midi = _parse_midi_bytes(data)
    pcm_loop = render_midi(midi, sample_rate=11025, max_duration=30, loop=True)
    pcm_noloop = render_midi(midi, sample_rate=11025, max_duration=30, loop=False)
    _assert("render: loop extends duration", len(pcm_loop) > len(pcm_noloop))

    # Multichannel mixing
    notes = [(0, 60, 100, 0, 48), (1, 64, 80, 0, 48), (2, 67, 90, 0, 48)]
    data = _make_minimal_midi(notes=notes)
    midi = _parse_midi_bytes(data)
    pcm = render_midi(midi, sample_rate=11025, max_duration=5)
    _assert("render: multichannel", len(pcm) > 0)

    # Percussion channel
    data = _make_minimal_midi(notes=[(9, 36, 100, 0, 12)])
    midi = _parse_midi_bytes(data)
    pcm = render_midi(midi, sample_rate=11025, max_duration=2)
    _assert("render: percussion channel", len(pcm) > 0)

    # Non-silent output
    data = _make_minimal_midi(notes=[(0, 60, 127, 0, 96)])
    midi = _parse_midi_bytes(data)
    pcm = render_midi(midi, sample_rate=11025, max_duration=5)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    peak = max(abs(s) for s in samples)
    _assert("render: non-silent output", peak > 100)

    # Velocity affects note amplitude (test via _resolve_notes, not post-normalization)
    # Two notes at different velocities in the same render — louder note should
    # produce higher raw amplitude in the mix buffer before normalization.
    from torch.midi_synth import _resolve_notes
    data_mixed = _make_minimal_midi(notes=[
        (0, 60, 127, 0, 48),   # loud note
        (1, 72, 30, 48, 96),   # quiet note (different pitch to avoid overlap)
    ])
    midi_mixed = _parse_midi_bytes(data_mixed)
    resolved, _, _, _ = _resolve_notes(midi_mixed, 10.0)
    vels = {n.note: n.velocity for n in resolved}
    _assert("render: velocity preserved in notes",
            vels.get(60, 0) > vels.get(72, 0),
            f"vel60={vels.get(60)} vel72={vels.get(72)}")

    # ── WAV output ──

    data = _make_minimal_midi()
    midi = _parse_midi_bytes(data)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        ok = render_to_wav(midi, path, sample_rate=11025, max_duration=2)
        _assert("wav: render_to_wav returns True", ok)
        with wave.open(path, "rb") as wf:
            _assert("wav: 1 channel", wf.getnchannels() == 1)
            _assert("wav: 16-bit", wf.getsampwidth() == 2)
            _assert("wav: correct sample rate", wf.getframerate() == 11025)
            _assert("wav: has frames", wf.getnframes() > 0)
    finally:
        os.unlink(path)

    # Creates parent dirs
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "sub", "dir", "test.wav")
        ok = render_to_wav(midi, path, sample_rate=11025, max_duration=1)
        _assert("wav: creates parent dirs", ok and os.path.exists(path))

    # In-memory wav bytes
    wav_bytes = render_midi_to_wav_bytes(midi, sample_rate=11025, max_duration=1)
    _assert("wav: in-memory bytes not None", wav_bytes is not None)
    _assert("wav: starts with RIFF", wav_bytes[:4] == b"RIFF")
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        _assert("wav: in-memory openable", wf.getnchannels() == 1)

    # Convenience file renderer
    data = _make_minimal_midi()
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
        f.write(data)
        mid_path = f.name
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    try:
        ok = render_midi_file(mid_path, wav_path, sample_rate=11025, max_duration=1)
        _assert("wav: render_midi_file works", ok and os.path.getsize(wav_path) > 0)
    finally:
        os.unlink(mid_path)
        os.unlink(wav_path)

    # Nonexistent file
    ok = render_midi_file("/nonexistent/path.mid", "/tmp/out.wav")
    _assert("wav: nonexistent file → False", not ok)

    # ── Convenience ──

    _assert("synth_available always True", synth_available())
    _assert("render_quality is 'basic'", render_quality() == "basic")

    # ── Real MIDI files (conditional) ──

    if not _HAS_DECOMP:
        _skip("real midi: decomp files", "decomp not available")
    else:
        # Parse birch lab
        path = os.path.join(_DECOMP_MIDI_DIR, "mus_birch_lab.mid")
        midi = parse_midi(path)
        _assert("real: birch lab format", midi.format_type == 1)
        _assert("real: birch lab tracks", midi.num_tracks == 8)
        _assert("real: birch lab tpq", midi.ticks_per_quarter == 24)
        _assert("real: birch lab events", len(midi.events) > 100)
        _assert("real: birch lab loop start", midi.loop_start_tick is not None)
        _assert("real: birch lab loop end", midi.loop_end_tick is not None)

        # Parse petalburg
        path = os.path.join(_DECOMP_MIDI_DIR, "mus_petalburg.mid")
        midi = parse_midi(path)
        _assert("real: petalburg tracks", midi.num_tracks == 9)
        _assert("real: petalburg events", len(midi.events) > 500)

        # Render birch lab
        path = os.path.join(_DECOMP_MIDI_DIR, "mus_birch_lab.mid")
        midi = parse_midi(path)
        pcm = render_midi(midi, sample_rate=11025, max_duration=5)
        _assert("real: birch lab renders", len(pcm) > 0)
        samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
        peak = max(abs(s) for s in samples)
        _assert("real: birch lab non-silent", peak > 100)

        # Smoke test all MIDI files
        failures = []
        count = 0
        for fname in sorted(os.listdir(_DECOMP_MIDI_DIR)):
            if not fname.endswith(".mid"):
                continue
            fpath = os.path.join(_DECOMP_MIDI_DIR, fname)
            try:
                m = parse_midi(fpath)
                pcm = render_midi(m, sample_rate=11025, max_duration=5, loop=False)
                if len(pcm) == 0:
                    failures.append(f"{fname}: empty output")
                count += 1
            except Exception as e:
                failures.append(f"{fname}: {e}")

        _assert("real: smoke test count", count > 50, f"only found {count} files")
        _assert("real: all files parse+render",
                len(failures) == 0,
                f"{len(failures)} failures: " + "; ".join(failures[:5]))

        # All have events
        ok = True
        bad = ""
        for fname in sorted(os.listdir(_DECOMP_MIDI_DIR)):
            if not fname.endswith(".mid"):
                continue
            if fname == "mus_dummy.mid":
                continue  # intentionally empty placeholder
            fpath = os.path.join(_DECOMP_MIDI_DIR, fname)
            m = parse_midi(fpath)
            if len(m.events) == 0:
                ok = False
                bad = fname
                break
        _assert("real: all files have events", ok, f"{bad} has 0 events")
