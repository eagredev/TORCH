"""TORCH Built-in MIDI Synthesizer — stdlib-only fallback for music playback.

Pure Python MIDI parser and waveform synthesizer.  Reads Standard MIDI Files
(.mid) and renders to .wav using basic waveforms (square, triangle, noise).
Not GBA-accurate — that's poryaaaa's job — but functional enough to identify
songs, check loop points, and verify custom MIDI structure.

No external dependencies.  Uses only struct, math, wave from the stdlib.
"""
# TORCH_MODULE: MIDI Synth
# TORCH_GROUP: Music

import math
import os
import struct
import wave

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_SAMPLE_RATE = 22050
DEFAULT_MAX_DURATION = 180  # seconds
DEFAULT_LOOP_COUNT = 2      # play loop body this many times, then fade

# MIDI status bytes
_NOTE_OFF        = 0x80
_NOTE_ON         = 0x90
_POLY_AFTERTOUCH = 0xA0
_CONTROL_CHANGE  = 0xB0
_PROGRAM_CHANGE  = 0xC0
_CHAN_AFTERTOUCH  = 0xD0
_PITCH_BEND      = 0xE0
_SYSEX           = 0xF0
_META            = 0xFF

# Meta event types
_META_TEXT        = 0x01
_META_MARKER      = 0x06
_META_TEMPO       = 0x51
_META_TIME_SIG    = 0x58
_META_END_OF_TRACK = 0x2F

# Waveform types
WAVE_SQUARE   = "square"
WAVE_TRIANGLE = "triangle"
WAVE_NOISE    = "noise"
WAVE_SQUARE25 = "square25"   # 25% duty cycle

# MIDI percussion channel (0-indexed)
_PERCUSSION_CHANNEL = 9

# Simple ADSR envelope (in seconds)
_ATTACK  = 0.005
_DECAY   = 0.05
_SUSTAIN = 0.7   # sustain level (0-1)
_RELEASE = 0.08


# ── Data Structures ──────────────────────────────────────────────────────────

class MidiEvent:
    """A single MIDI event with absolute tick timing."""
    __slots__ = ("tick", "type", "channel", "data")

    def __init__(self, tick, etype, channel, data):
        self.tick = tick
        self.type = etype
        self.channel = channel
        self.data = data  # dict with event-specific fields

    def __repr__(self):
        return f"MidiEvent(t={self.tick}, {self.type}, ch={self.channel}, {self.data})"


class MidiFile:
    """Parsed MIDI file."""
    __slots__ = ("format_type", "num_tracks", "ticks_per_quarter",
                 "events", "loop_start_tick", "loop_end_tick", "duration_ticks")

    def __init__(self):
        self.format_type = 1
        self.num_tracks = 0
        self.ticks_per_quarter = 24
        self.events = []           # sorted by tick
        self.loop_start_tick = None
        self.loop_end_tick = None
        self.duration_ticks = 0


# ── MIDI Parsing ─────────────────────────────────────────────────────────────

def parse_midi(path):
    """Parse a Standard MIDI File (.mid) and return a MidiFile object.

    Supports Type 0 (single track) and Type 1 (multi-track).
    """
    with open(path, "rb") as f:
        data = f.read()
    return _parse_midi_bytes(data)


def _parse_midi_bytes(data):
    """Parse MIDI from raw bytes."""
    midi = MidiFile()
    pos = 0

    # ── Header chunk ──
    if data[pos:pos + 4] != b"MThd":
        raise ValueError("Not a MIDI file: missing MThd header")
    pos += 4

    header_len = struct.unpack(">I", data[pos:pos + 4])[0]
    pos += 4

    fmt, num_tracks, division = struct.unpack(">HHH", data[pos:pos + 6])
    pos += header_len  # usually 6, but spec allows more

    midi.format_type = fmt
    midi.num_tracks = num_tracks

    if division & 0x8000:
        # SMPTE time — rare, just use a sensible default
        midi.ticks_per_quarter = 24
    else:
        midi.ticks_per_quarter = division

    # ── Track chunks ──
    all_events = []
    for _ in range(num_tracks):
        if pos >= len(data):
            break
        if data[pos:pos + 4] != b"MTrk":
            # Skip unknown chunks
            pos += 4
            chunk_len = struct.unpack(">I", data[pos:pos + 4])[0]
            pos += 4 + chunk_len
            continue

        pos += 4
        track_len = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4

        track_end = pos + track_len
        track_events, _ = _parse_track(data, pos, track_end)
        all_events.extend(track_events)
        pos = track_end

    # Sort all events by tick (stable sort preserves intra-track order)
    all_events.sort(key=lambda e: e.tick)
    midi.events = all_events

    # Find loop markers and duration
    for ev in all_events:
        if ev.type == "marker":
            text = ev.data.get("text", "")
            if text == "[":
                midi.loop_start_tick = ev.tick
            elif text == "]":
                midi.loop_end_tick = ev.tick

    if all_events:
        midi.duration_ticks = all_events[-1].tick
    return midi


def _read_variable_length(data, pos):
    """Read a MIDI variable-length quantity. Returns (value, new_pos)."""
    value = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not (byte & 0x80):
            break
    return value, pos


def _parse_track(data, pos, end):
    """Parse a single MIDI track. Returns (events, final_pos)."""
    events = []
    abs_tick = 0
    running_status = 0

    while pos < end:
        # Delta time
        delta, pos = _read_variable_length(data, pos)
        abs_tick += delta

        if pos >= end:
            break

        byte = data[pos]

        # Meta event
        if byte == _META:
            pos += 1
            if pos >= end:
                break
            meta_type = data[pos]
            pos += 1
            length, pos = _read_variable_length(data, pos)
            meta_data = data[pos:pos + length]
            pos += length

            if meta_type == _META_TEMPO:
                if len(meta_data) >= 3:
                    tempo = (meta_data[0] << 16) | (meta_data[1] << 8) | meta_data[2]
                    events.append(MidiEvent(abs_tick, "tempo", None,
                                            {"tempo_us": tempo}))
            elif meta_type in (_META_TEXT, _META_MARKER):
                try:
                    text = meta_data.decode("ascii", errors="replace").strip()
                except Exception:
                    text = ""
                if text:
                    events.append(MidiEvent(abs_tick, "marker", None,
                                            {"text": text}))
            # Other meta events silently skipped
            continue

        # SysEx
        if byte == _SYSEX or byte == 0xF7:
            pos += 1
            length, pos = _read_variable_length(data, pos)
            pos += length
            continue

        # Channel events
        if byte & 0x80:
            status = byte
            pos += 1
            running_status = status
        else:
            # Running status
            status = running_status

        msg_type = status & 0xF0
        channel = status & 0x0F

        if msg_type == _NOTE_ON:
            if pos + 1 >= end:
                break
            note = data[pos]
            velocity = data[pos + 1]
            pos += 2
            if velocity == 0:
                events.append(MidiEvent(abs_tick, "note_off", channel,
                                        {"note": note, "velocity": 0}))
            else:
                events.append(MidiEvent(abs_tick, "note_on", channel,
                                        {"note": note, "velocity": velocity}))

        elif msg_type == _NOTE_OFF:
            if pos + 1 >= end:
                break
            note = data[pos]
            velocity = data[pos + 1]
            pos += 2
            events.append(MidiEvent(abs_tick, "note_off", channel,
                                    {"note": note, "velocity": velocity}))

        elif msg_type == _CONTROL_CHANGE:
            if pos + 1 >= end:
                break
            cc = data[pos]
            val = data[pos + 1]
            pos += 2
            events.append(MidiEvent(abs_tick, "cc", channel,
                                    {"controller": cc, "value": val}))

        elif msg_type == _PROGRAM_CHANGE:
            if pos >= end:
                break
            program = data[pos]
            pos += 1
            events.append(MidiEvent(abs_tick, "program_change", channel,
                                    {"program": program}))

        elif msg_type == _PITCH_BEND:
            if pos + 1 >= end:
                break
            lsb = data[pos]
            msb = data[pos + 1]
            pos += 2
            bend = ((msb << 7) | lsb) - 8192  # -8192 to +8191
            events.append(MidiEvent(abs_tick, "pitch_bend", channel,
                                    {"bend": bend}))

        elif msg_type == _POLY_AFTERTOUCH:
            pos += 2  # skip
        elif msg_type == _CHAN_AFTERTOUCH:
            pos += 1  # skip
        else:
            # Unknown — skip one byte and hope
            pos += 1

    return events, pos


# ── Waveform Generators ─────────────────────────────────────────────────────

def _midi_note_to_freq(note):
    """Convert MIDI note number to frequency in Hz.  A4 (note 69) = 440 Hz."""
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def _square_wave(phase, duty=0.5):
    """Square wave: +1 if phase < duty, else -1."""
    return 1.0 if (phase % 1.0) < duty else -1.0


def _triangle_wave(phase):
    """Triangle wave: ramps linearly between -1 and +1."""
    p = phase % 1.0
    if p < 0.25:
        return p * 4.0
    elif p < 0.75:
        return 2.0 - p * 4.0
    else:
        return p * 4.0 - 4.0


_noise_state = 0x7FFF  # 15-bit LFSR


def _noise_sample(freq, sample_rate):
    """Simple noise generator using a 15-bit LFSR, stepped at freq rate."""
    global _noise_state
    # Step the LFSR at the note frequency
    _noise_state = ((_noise_state >> 1) |
                    (((_noise_state ^ (_noise_state >> 1)) & 1) << 14))
    return 1.0 if (_noise_state & 1) else -1.0


def _generate_sample(waveform, phase, freq, sample_rate):
    """Generate a single sample for the given waveform type."""
    if waveform == WAVE_SQUARE:
        return _square_wave(phase, 0.5)
    elif waveform == WAVE_SQUARE25:
        return _square_wave(phase, 0.25)
    elif waveform == WAVE_TRIANGLE:
        return _triangle_wave(phase)
    elif waveform == WAVE_NOISE:
        return _noise_sample(freq, sample_rate)
    return _square_wave(phase, 0.5)


# ── Channel → Waveform Mapping ──────────────────────────────────────────────

# Simple program-to-waveform mapping (approximates GBA sound character)
# Programs 0-127 mapped to waveforms.  This is intentionally simple.
def _program_to_waveform(program, channel):
    """Map MIDI program number to a waveform type."""
    if channel == _PERCUSSION_CHANNEL:
        return WAVE_NOISE
    # Strings, pads, brass → triangle (smoother)
    if 40 <= program <= 79:
        return WAVE_TRIANGLE
    # Bass → square 25% duty (thinner, punchier)
    if 32 <= program <= 39:
        return WAVE_SQUARE25
    # Default → square 50%
    return WAVE_SQUARE


# ── ADSR Envelope ────────────────────────────────────────────────────────────

def _envelope(t, note_duration, release_end):
    """Calculate ADSR envelope amplitude at time t (seconds from note start).

    note_duration: time from note_on to note_off (seconds)
    release_end:   note_duration + _RELEASE
    """
    if t < 0:
        return 0.0
    if t < _ATTACK:
        # Attack: ramp up
        return t / _ATTACK
    if t < _ATTACK + _DECAY:
        # Decay: ramp down to sustain
        decay_progress = (t - _ATTACK) / _DECAY
        return 1.0 - decay_progress * (1.0 - _SUSTAIN)
    if t < note_duration:
        # Sustain
        return _SUSTAIN
    if t < release_end:
        # Release: ramp down from sustain
        release_progress = (t - note_duration) / _RELEASE
        return _SUSTAIN * (1.0 - release_progress)
    return 0.0


# ── Synthesis Engine ─────────────────────────────────────────────────────────

class _NoteEvent:
    """A resolved note with timing in seconds."""
    __slots__ = ("start", "end", "note", "velocity", "channel", "waveform",
                 "freq", "bend_semitones")

    def __init__(self, start, end, note, velocity, channel, waveform):
        self.start = start
        self.end = end
        self.note = note
        self.velocity = velocity
        self.channel = channel
        self.waveform = waveform
        self.freq = _midi_note_to_freq(note)
        self.bend_semitones = 0.0


def _resolve_notes(midi, max_duration):
    """Convert MIDI events to timed note events in seconds."""
    # Build tempo map (tick → microseconds per quarter note)
    tempo_map = [(0, 500000)]  # default: 120 BPM
    for ev in midi.events:
        if ev.type == "tempo":
            tempo_map.append((ev.tick, ev.data["tempo_us"]))
    tempo_map.sort(key=lambda t: t[0])

    tpq = midi.ticks_per_quarter

    def tick_to_seconds(target_tick):
        """Convert absolute tick to seconds using the tempo map."""
        seconds = 0.0
        prev_tick = 0
        current_tempo = 500000  # default 120 BPM
        for i, (map_tick, tempo_us) in enumerate(tempo_map):
            if map_tick >= target_tick:
                break
            if map_tick > prev_tick:
                delta_ticks = map_tick - prev_tick
                seconds += delta_ticks * current_tempo / (tpq * 1_000_000)
                prev_tick = map_tick
            current_tempo = tempo_us
        # Remaining ticks at current tempo
        if target_tick > prev_tick:
            delta_ticks = target_tick - prev_tick
            seconds += delta_ticks * current_tempo / (tpq * 1_000_000)
        return seconds

    # Track active notes and program per channel
    programs = {}       # channel → program
    active = {}         # (channel, note) → (start_time, velocity)
    notes = []
    channel_volumes = {}  # channel → volume (CC 7)

    # Handle looping
    loop_start_sec = None
    loop_end_sec = None
    if midi.loop_start_tick is not None:
        loop_start_sec = tick_to_seconds(midi.loop_start_tick)
    if midi.loop_end_tick is not None:
        loop_end_sec = tick_to_seconds(midi.loop_end_tick)

    for ev in midi.events:
        t = tick_to_seconds(ev.tick)
        if t > max_duration:
            break

        if ev.type == "program_change" and ev.channel is not None:
            programs[ev.channel] = ev.data["program"]

        elif ev.type == "cc" and ev.channel is not None:
            if ev.data["controller"] == 7:
                channel_volumes[ev.channel] = ev.data["value"]

        elif ev.type == "note_on" and ev.channel is not None:
            key = (ev.channel, ev.data["note"])
            # Close any existing note on this key
            if key in active:
                start, vel = active.pop(key)
                prog = programs.get(ev.channel, 0)
                wf = _program_to_waveform(prog, ev.channel)
                notes.append(_NoteEvent(start, t, key[1], vel, ev.channel, wf))
            active[key] = (t, ev.data["velocity"])

        elif ev.type == "note_off" and ev.channel is not None:
            key = (ev.channel, ev.data["note"])
            if key in active:
                start, vel = active.pop(key)
                prog = programs.get(ev.channel, 0)
                wf = _program_to_waveform(prog, ev.channel)
                notes.append(_NoteEvent(start, t, key[1], vel, ev.channel, wf))

    # Close any still-active notes
    end_time = min(tick_to_seconds(midi.duration_ticks), max_duration)
    for key, (start, vel) in active.items():
        ch, note_num = key
        prog = programs.get(ch, 0)
        wf = _program_to_waveform(prog, ch)
        notes.append(_NoteEvent(start, end_time, note_num, vel, ch, wf))

    return notes, loop_start_sec, loop_end_sec, channel_volumes


def render_midi(midi, *, sample_rate=DEFAULT_SAMPLE_RATE,
                max_duration=DEFAULT_MAX_DURATION, loop=True,
                loop_count=DEFAULT_LOOP_COUNT):
    """Render a MidiFile to raw PCM bytes (signed 16-bit LE, mono).

    Returns bytes.
    """
    notes, loop_start, loop_end, ch_volumes = _resolve_notes(midi, max_duration)

    if not notes:
        # Silent — return 1 second of silence
        return b"\x00\x00" * sample_rate

    # Calculate total duration
    if loop and loop_start is not None and loop_end is not None and loop_end > loop_start:
        # Play: intro → loop body × loop_count → fadeout
        intro_dur = loop_start
        loop_dur = loop_end - loop_start
        total_dur = intro_dur + loop_dur * loop_count
    else:
        # No loop — just play to the end of the last note + release
        total_dur = max(n.end for n in notes) + _RELEASE

    total_dur = min(total_dur, max_duration)
    total_samples = int(total_dur * sample_rate)
    if total_samples <= 0:
        return b"\x00\x00" * sample_rate

    # Pre-allocate output buffer
    buf = [0.0] * total_samples

    # Render each note
    for note in notes:
        _render_note(note, buf, sample_rate, total_samples, ch_volumes,
                     loop_start, loop_end, loop_count if loop else 0)

    # Normalize and convert to 16-bit PCM
    peak = max(abs(s) for s in buf) if buf else 1.0
    if peak < 0.001:
        peak = 1.0

    # Leave some headroom
    scale = 28000.0 / peak

    # Fade out the last 2 seconds
    fade_samples = min(int(2.0 * sample_rate), total_samples // 4)
    if fade_samples > 0:
        fade_start = total_samples - fade_samples
        for i in range(fade_samples):
            buf[fade_start + i] *= 1.0 - (i / fade_samples)

    pcm = bytearray(total_samples * 2)
    for i in range(total_samples):
        sample = int(buf[i] * scale)
        sample = max(-32768, min(32767, sample))
        struct.pack_into("<h", pcm, i * 2, sample)

    return bytes(pcm)


def _render_note(note, buf, sample_rate, total_samples, ch_volumes,
                 loop_start, loop_end, loop_count):
    """Render a single note into the mix buffer, handling loop expansion."""
    # Volume scaling from velocity and channel volume
    vel_scale = note.velocity / 127.0
    ch_vol = ch_volumes.get(note.channel, 100) / 127.0
    amplitude = vel_scale * ch_vol * 0.3  # 0.3 base to avoid clipping with polyphony

    note_dur = note.end - note.start
    release_dur = _RELEASE

    has_loop = (loop_count > 0 and loop_start is not None and
                loop_end is not None and loop_end > loop_start)
    loop_dur = (loop_end - loop_start) if has_loop else 0.0

    # Determine which loop iterations this note appears in
    if has_loop:
        _render_note_looped(note, buf, sample_rate, total_samples, amplitude,
                            note_dur, release_dur, loop_start, loop_end,
                            loop_dur, loop_count)
    else:
        _render_note_simple(note, buf, sample_rate, total_samples, amplitude,
                            note_dur, release_dur)


def _render_note_simple(note, buf, sample_rate, total_samples, amplitude,
                        note_dur, release_dur):
    """Render a note without loop expansion."""
    freq = note.freq
    wf = note.waveform
    start_sample = int(note.start * sample_rate)
    end_sample = min(int((note.end + release_dur) * sample_rate), total_samples)

    phase = 0.0
    phase_inc = freq / sample_rate

    for i in range(start_sample, end_sample):
        if i < 0:
            continue
        t = (i - start_sample) / sample_rate
        env = _envelope(t, note_dur, note_dur + release_dur)
        sample = _generate_sample(wf, phase, freq, sample_rate)
        buf[i] += sample * env * amplitude
        phase += phase_inc


def _render_note_looped(note, buf, sample_rate, total_samples, amplitude,
                        note_dur, release_dur, loop_start, loop_end,
                        loop_dur, loop_count):
    """Render a note with loop expansion."""
    freq = note.freq
    wf = note.waveform

    # A note can appear in:
    #   - The intro (before loop_start): plays once
    #   - The loop body (loop_start..loop_end): plays loop_count times
    # Notes that span the boundary get clipped at the boundary.

    if note.end <= loop_start:
        # Entirely in intro — play once
        _render_note_simple(note, buf, sample_rate, total_samples, amplitude,
                            note_dur, release_dur)
        return

    if note.start >= loop_end:
        # After loop — shouldn't happen, but handle gracefully
        return

    # Note is in the loop body (possibly partially)
    body_start = max(note.start, loop_start)
    body_end = min(note.end, loop_end)
    body_note_dur = body_end - body_start

    for iteration in range(loop_count):
        offset = loop_start + iteration * loop_dur
        render_start = offset + (body_start - loop_start)

        start_sample = int(render_start * sample_rate)
        end_sample = min(int((render_start + body_note_dur + release_dur) * sample_rate),
                         total_samples)

        phase = 0.0
        phase_inc = freq / sample_rate

        for i in range(start_sample, end_sample):
            if i < 0 or i >= total_samples:
                continue
            t = (i - start_sample) / sample_rate
            env = _envelope(t, body_note_dur, body_note_dur + release_dur)
            sample = _generate_sample(wf, phase, freq, sample_rate)
            buf[i] += sample * env * amplitude
            phase += phase_inc

    # Also render intro portion if note starts before loop
    if note.start < loop_start:
        intro_dur = loop_start - note.start
        start_sample = int(note.start * sample_rate)
        end_sample = min(int((loop_start + release_dur) * sample_rate), total_samples)
        phase = 0.0
        phase_inc = freq / sample_rate
        for i in range(start_sample, end_sample):
            if i < 0:
                continue
            t = (i - start_sample) / sample_rate
            env = _envelope(t, intro_dur, intro_dur + release_dur)
            sample = _generate_sample(wf, phase, freq, sample_rate)
            buf[i] += sample * env * amplitude
            phase += phase_inc


# ── Output ───────────────────────────────────────────────────────────────────

def render_to_wav(midi, output_path, **kwargs):
    """Render a MidiFile to a .wav file.

    Returns True on success, False on error.
    """
    try:
        pcm = render_midi(midi, **kwargs)
        sr = kwargs.get("sample_rate", DEFAULT_SAMPLE_RATE)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sr)
            wf.writeframes(pcm)
        return True
    except Exception:
        return False


def render_midi_to_wav_bytes(midi, **kwargs):
    """Render a MidiFile to in-memory .wav bytes (for streaming).

    Returns bytes containing a complete .wav file, or None on error.
    """
    try:
        import io
        pcm = render_midi(midi, **kwargs)
        sr = kwargs.get("sample_rate", DEFAULT_SAMPLE_RATE)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm)
        return buf.getvalue()
    except Exception:
        return None


# ── Convenience ──────────────────────────────────────────────────────────────

def synth_available():
    """Always True — stdlib-only, no external dependencies."""
    return True


def render_quality():
    """Return quality descriptor for UI display."""
    return "basic"


def render_midi_file(midi_path, output_path, **kwargs):
    """Parse a .mid file and render it to .wav.  Convenience wrapper.

    Returns True on success, False on error.
    """
    try:
        midi = parse_midi(midi_path)
        return render_to_wav(midi, output_path, **kwargs)
    except Exception:
        return False
