"""TORCH Music Player — playback engine with backend selection.

Orchestrates music playback via two backends:
  1. poryaaaa_render (external binary) — GBA-accurate m4a engine emulation
  2. Built-in MIDI synth (midi_synth.py) — stdlib-only fallback

Also provides song metadata (parsed from songs.h + midi.cfg + filesystem)
and a render cache to avoid re-rendering on repeat plays.
"""
# TORCH_MODULE: Music Player
# TORCH_GROUP: Music

import os
import re
import shutil
import subprocess
import time

# ── Constants ────────────────────────────────────────────────────────────────

_MIDI_DIR = os.path.join("sound", "songs", "midi")
_MIDI_CFG = os.path.join("sound", "songs", "midi", "midi.cfg")
_SONGS_HEADER = os.path.join("include", "constants", "songs.h")

_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "torch", "music")

_DEFAULT_SAMPLE_RATE = 22050
_DEFAULT_DURATION = 180
_DEFAULT_CACHE_MAX_MB = 200

# Audio player detection order (for TUI playback)
_AUDIO_PLAYERS = ["pw-play", "paplay", "aplay"]

# poryaaaa search paths (beyond PATH)
_PORYAAAA_EXTRA_PATHS = [
    os.path.expanduser("~/.local/bin/poryaaaa_render"),
    os.path.expanduser("~/bin/poryaaaa_render"),
    "/usr/local/bin/poryaaaa_render",
]

# Regex for parsing midi.cfg lines
_MIDI_CFG_RE = re.compile(
    r"^(\S+\.mid):\s*(.*)"
)

# Playback subprocess handle (for stop_playback)
_playback_proc = None


# ── Data Structures ──────────────────────────────────────────────────────────

class SongInfo:
    """Metadata for a single song."""
    __slots__ = ("constant", "name", "midi_file", "voicegroup", "volume",
                 "reverb", "priority", "is_custom", "has_assembly", "song_id")

    def __init__(self, constant, name, midi_file=None, voicegroup=None,
                 volume=None, reverb=None, priority=None, is_custom=False,
                 has_assembly=False, song_id=None):
        self.constant = constant
        self.name = name
        self.midi_file = midi_file
        self.voicegroup = voicegroup
        self.volume = volume
        self.reverb = reverb
        self.priority = priority
        self.is_custom = is_custom
        self.has_assembly = has_assembly
        self.song_id = song_id

    def to_dict(self):
        return {
            "constant": self.constant,
            "name": self.name,
            "midi_file": self.midi_file,
            "voicegroup": self.voicegroup,
            "volume": self.volume,
            "reverb": self.reverb,
            "priority": self.priority,
            "is_custom": self.is_custom,
            "has_assembly": self.has_assembly,
            "song_id": self.song_id,
        }


class MidiCfgEntry:
    """Parsed entry from midi.cfg."""
    __slots__ = ("filename", "voicegroup", "volume", "reverb", "priority",
                 "extended")

    def __init__(self, filename, voicegroup=None, volume=None, reverb=None,
                 priority=None, extended=False):
        self.filename = filename
        self.voicegroup = voicegroup
        self.volume = volume
        self.reverb = reverb
        self.priority = priority
        self.extended = extended


# ── Backend Detection ────────────────────────────────────────────────────────

def find_poryaaaa(settings=None):
    """Find poryaaaa_render binary.  Returns full path or None.

    Search order:
    1. poryaaaa_path from settings/config
    2. shutil.which("poryaaaa_render") (on PATH)
    3. Common install locations
    """
    # Check config
    if settings:
        cfg_path = settings.get("poryaaaa_path", "")
        if cfg_path and os.path.isfile(cfg_path) and os.access(cfg_path, os.X_OK):
            return cfg_path

    # Check PATH
    on_path = shutil.which("poryaaaa_render")
    if on_path:
        return on_path

    # Check common locations
    for p in _PORYAAAA_EXTRA_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    return None


def poryaaaa_available(settings=None):
    """Return True if poryaaaa_render is installed and findable."""
    return find_poryaaaa(settings) is not None


def poryaaaa_version(settings=None):
    """Return poryaaaa version string, or None if not available."""
    binary = find_poryaaaa(settings)
    if not binary:
        return None
    try:
        # poryaaaa_render has no --version flag; running with no args prints usage
        result = subprocess.run(
            [binary], capture_output=True, text=True, timeout=5
        )
        output = (result.stdout + result.stderr).strip()
        # Look for version pattern like "1.2.0" or "v1.2.0" in output
        match = re.search(r"v?(\d+\.\d+\.\d+)", output)
        if match:
            return match.group(1)
        # No version string in output — just confirm it exists
        return "installed"
    except Exception:
        return None


def preferred_backend(settings=None):
    """Return the best available playback backend.

    Returns: "poryaaaa", "builtin", or "none"
    """
    if poryaaaa_available(settings):
        return "poryaaaa"
    return "builtin"  # midi_synth is always available (stdlib-only)


def find_audio_player(settings=None):
    """Find a system audio player for TUI playback.  Returns path or None."""
    # Check config override
    if settings:
        override = settings.get("audio_player", "")
        if override:
            path = shutil.which(override)
            if path:
                return path

    for name in _AUDIO_PLAYERS:
        path = shutil.which(name)
        if path:
            return path
    return None


def audio_player_name(settings=None):
    """Return human-readable name of the audio player, or None."""
    player = find_audio_player(settings)
    if not player:
        return None
    base = os.path.basename(player)
    labels = {"pw-play": "PipeWire", "paplay": "PulseAudio", "aplay": "ALSA"}
    return labels.get(base, base)


# ── Song Metadata ────────────────────────────────────────────────────────────

def parse_midi_cfg(game_path):
    """Parse midi.cfg and return {midi_filename: MidiCfgEntry}.

    midi.cfg format:
        mus_petalburg.mid:  -E -R50 -G_petalburg -V080
    """
    cfg_path = os.path.join(game_path, _MIDI_CFG)
    entries = {}

    if not os.path.isfile(cfg_path):
        return entries

    try:
        with open(cfg_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = _MIDI_CFG_RE.match(line)
                if not m:
                    continue

                filename = m.group(1)
                flags_str = m.group(2)

                voicegroup = None
                volume = None
                reverb = None
                priority = None
                extended = False

                for token in flags_str.split():
                    if token.startswith("-G"):
                        voicegroup = token[2:]
                    elif token.startswith("-V"):
                        try:
                            volume = int(token[2:])
                        except ValueError:
                            pass
                    elif token.startswith("-R"):
                        try:
                            reverb = int(token[2:])
                        except ValueError:
                            pass
                    elif token.startswith("-P"):
                        try:
                            priority = int(token[2:])
                        except ValueError:
                            pass
                    elif token == "-E":
                        extended = True

                entries[filename] = MidiCfgEntry(
                    filename=filename,
                    voicegroup=voicegroup,
                    volume=volume,
                    reverb=reverb,
                    priority=priority,
                    extended=extended,
                )
    except OSError:
        pass

    return entries


def _parse_songs_header(game_path):
    """Parse songs.h for MUS_ and SE_ constants.

    Returns [(constant, song_id), ...]
    """
    header_path = os.path.join(game_path, _SONGS_HEADER)
    results = []

    if not os.path.isfile(header_path):
        return results

    try:
        with open(header_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("#define "):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                name = parts[1]
                if not (name.startswith("MUS_") or name.startswith("SE_")):
                    continue
                try:
                    val = int(parts[2], 0)
                except ValueError:
                    continue
                results.append((name, val))
    except OSError:
        pass

    return results


def _format_song_name(constant):
    """Convert MUS_PETALBURG → Petalburg, SE_BALL_OPEN → Ball Open."""
    prefix = "MUS_" if constant.startswith("MUS_") else "SE_"
    name = constant[len(prefix):]
    return name.replace("_", " ").title()


def list_songs(game_path, filter_type=None):
    """List all songs with metadata.

    filter_type: None (all), "music" (MUS_ only), "sfx" (SE_ only), "custom"
    Returns [SongInfo, ...]
    """
    # Load vanilla set for custom detection
    try:
        from torch.data_files.vanilla_asset_sets import VANILLA_MUSIC, VANILLA_SOUND_EFFECTS
    except ImportError:
        VANILLA_MUSIC = set()
        VANILLA_SOUND_EFFECTS = set()

    header_entries = _parse_songs_header(game_path)
    cfg_entries = parse_midi_cfg(game_path)
    midi_dir = os.path.join(game_path, _MIDI_DIR)

    songs = []
    for constant, song_id in header_entries:
        # Skip special constants
        if constant in ("MUS_NONE", "MUS_DUMMY") or song_id >= 0x7FFF:
            continue

        is_mus = constant.startswith("MUS_")
        is_se = constant.startswith("SE_")

        # Filter
        if filter_type == "music" and not is_mus:
            continue
        if filter_type == "sfx" and not is_se:
            continue

        # Determine custom status
        vanilla_set = VANILLA_MUSIC if is_mus else VANILLA_SOUND_EFFECTS
        is_custom = constant not in vanilla_set

        if filter_type == "custom" and not is_custom:
            continue

        # Find midi file
        stem = constant.lower()
        midi_file = None
        midi_path = os.path.join(midi_dir, f"{stem}.mid")
        if os.path.isfile(midi_path):
            midi_file = f"{_MIDI_DIR}/{stem}.mid"

        # Get midi.cfg data
        cfg = cfg_entries.get(f"{stem}.mid")
        voicegroup = cfg.voicegroup if cfg else None
        volume = cfg.volume if cfg else None
        reverb = cfg.reverb if cfg else None
        priority = cfg.priority if cfg else None

        # Check for compiled assembly
        has_assembly = False
        asm_path = os.path.join(game_path, "sound", "songs", f"{stem}.s")
        if os.path.isfile(asm_path):
            has_assembly = True

        songs.append(SongInfo(
            constant=constant,
            name=_format_song_name(constant),
            midi_file=midi_file,
            voicegroup=voicegroup,
            volume=volume,
            reverb=reverb,
            priority=priority,
            is_custom=is_custom,
            has_assembly=has_assembly,
            song_id=song_id,
        ))

    return songs


def song_info(game_path, song_name):
    """Get info for a specific song by constant name (e.g. 'MUS_PETALBURG')
    or stem name (e.g. 'petalburg').

    Returns SongInfo or None.
    """
    target = song_name.upper()
    if not target.startswith("MUS_") and not target.startswith("SE_"):
        target = f"MUS_{target}"

    for s in list_songs(game_path):
        if s.constant == target:
            return s
    return None


# ── Rendering ────────────────────────────────────────────────────────────────

def _render_poryaaaa(game_path, song_name, output_path, settings=None,
                     sample_rate=None, duration=None, reverb=None):
    """Render a song using poryaaaa_render.  Returns True on success."""
    binary = find_poryaaaa(settings)
    if not binary:
        return False

    # Determine the song stem (lowercase, no prefix)
    stem = song_name.lower()
    if stem.startswith("mus_"):
        stem = stem[4:]

    # Find the MIDI file
    midi_path = os.path.join(game_path, _MIDI_DIR, f"mus_{stem}.mid")
    if not os.path.isfile(midi_path):
        return False

    # Look up voicegroup from midi.cfg (falls back to stem name)
    cfg = parse_midi_cfg(game_path)
    cfg_entry = cfg.get(f"mus_{stem}.mid")
    voicegroup = stem
    if cfg_entry and cfg_entry.voicegroup:
        # midi.cfg voicegroup is like "_petalburg" — strip leading underscore
        vg = cfg_entry.voicegroup
        if vg.startswith("_"):
            vg = vg[1:]
        voicegroup = vg

    sr = sample_rate or _DEFAULT_SAMPLE_RATE
    dur = duration or _DEFAULT_DURATION
    rev = reverb if reverb is not None else 0

    cmd = [
        binary, game_path, voicegroup,
        "--midi", midi_path,
        "--output", output_path,
        "--sample-rate", str(sr),
        "--total-duration-seconds", str(dur),
        "--reverb", str(rev),
    ]

    # Pass volume from midi.cfg if available
    if cfg_entry and cfg_entry.volume is not None:
        cmd.extend(["--song-volume", str(cfg_entry.volume)])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=dur + 30
        )
        return result.returncode == 0 and os.path.isfile(output_path)
    except Exception:
        return False


def _render_builtin(game_path, song_name, output_path, sample_rate=None,
                    duration=None):
    """Render a song using the built-in MIDI synth.  Returns True on success."""
    from torch.midi_synth import parse_midi, render_to_wav

    stem = song_name.lower()
    if stem.startswith("mus_"):
        stem = stem[4:]

    midi_path = os.path.join(game_path, _MIDI_DIR, f"mus_{stem}.mid")
    if not os.path.isfile(midi_path):
        # Try exact name
        midi_path = os.path.join(game_path, _MIDI_DIR, f"{stem}.mid")
    if not os.path.isfile(midi_path):
        return False

    sr = sample_rate or _DEFAULT_SAMPLE_RATE
    dur = duration or _DEFAULT_DURATION

    try:
        midi = parse_midi(midi_path)
        return render_to_wav(midi, output_path, sample_rate=sr, max_duration=dur)
    except Exception:
        return False


def render_song(game_path, song_name, output_path, *,
                sample_rate=None, duration=None, reverb=None,
                backend=None, settings=None):
    """Render a song to .wav.

    backend: "poryaaaa", "builtin", or None (auto-select).
    Returns True on success.
    """
    if backend is None:
        backend = preferred_backend(settings)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if backend == "poryaaaa":
        return _render_poryaaaa(game_path, song_name, output_path,
                                settings=settings, sample_rate=sample_rate,
                                duration=duration, reverb=reverb)
    else:
        return _render_builtin(game_path, song_name, output_path,
                               sample_rate=sample_rate, duration=duration)


# ── Cache ────────────────────────────────────────────────────────────────────

def cache_path(song_name, backend="builtin"):
    """Return the cache file path for a rendered song."""
    stem = song_name.lower()
    if stem.startswith("mus_"):
        stem = stem[4:]
    return os.path.join(_CACHE_DIR, backend, f"{stem}.wav")


def render_song_cached(game_path, song_name, *, settings=None):
    """Render a song to cache if not already cached.  Returns path or None."""
    backend = preferred_backend(settings)
    path = cache_path(song_name, backend)

    if os.path.isfile(path):
        return path

    sr = _DEFAULT_SAMPLE_RATE
    dur = _DEFAULT_DURATION
    if settings:
        sr = settings.get("music_sample_rate", sr)
        dur = settings.get("music_default_duration", dur)

    ok = render_song(game_path, song_name, path,
                     sample_rate=sr, duration=dur,
                     backend=backend, settings=settings)

    if ok and os.path.isfile(path):
        # Enforce cache size limit
        max_mb = _DEFAULT_CACHE_MAX_MB
        if settings:
            max_mb = settings.get("music_cache_max_mb", max_mb)
        cache_evict(max_mb * 1024 * 1024)
        return path
    return None


def cache_clear(song_name=None):
    """Clear cached renders.  If song_name is None, clears all."""
    if song_name is None:
        if os.path.isdir(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR, ignore_errors=True)
        return

    for backend in ("poryaaaa", "builtin"):
        path = cache_path(song_name, backend)
        if os.path.isfile(path):
            try:
                os.unlink(path)
            except OSError:
                pass


def cache_size():
    """Return total cache size in bytes."""
    total = 0
    if not os.path.isdir(_CACHE_DIR):
        return 0
    for root, dirs, files in os.walk(_CACHE_DIR):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def cache_evict(max_bytes):
    """Remove oldest cached files until total size is under max_bytes."""
    if not os.path.isdir(_CACHE_DIR):
        return

    # Collect all cached files with mtime
    files = []
    for root, dirs, fnames in os.walk(_CACHE_DIR):
        for f in fnames:
            path = os.path.join(root, f)
            try:
                stat = os.stat(path)
                files.append((path, stat.st_mtime, stat.st_size))
            except OSError:
                pass

    total = sum(s for _, _, s in files)
    if total <= max_bytes:
        return

    # Sort oldest first
    files.sort(key=lambda x: x[1])
    for path, _, size in files:
        if total <= max_bytes:
            break
        try:
            os.unlink(path)
            total -= size
        except OSError:
            pass


# ── Playback (TUI) ──────────────────────────────────────────────────────────

def play_song(game_path, song_name, *, settings=None):
    """Play a song in the background (TUI mode).

    Renders to cache, then plays via system audio player.
    Returns True if playback started successfully.
    """
    global _playback_proc

    # Stop any current playback
    stop_playback()

    # Render to cache
    wav_path = render_song_cached(game_path, song_name, settings=settings)
    if not wav_path:
        return False

    # Find audio player
    player = find_audio_player(settings)
    if not player:
        return False

    try:
        _playback_proc = subprocess.Popen(
            [player, wav_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def stop_playback():
    """Stop any currently playing audio."""
    global _playback_proc
    if _playback_proc is not None:
        try:
            _playback_proc.terminate()
            _playback_proc.wait(timeout=2)
        except Exception:
            try:
                _playback_proc.kill()
            except Exception:
                pass
        _playback_proc = None


def is_playing():
    """Return True if audio is currently playing."""
    global _playback_proc
    if _playback_proc is None:
        return False
    if _playback_proc.poll() is not None:
        _playback_proc = None
        return False
    return True


# ── Status ───────────────────────────────────────────────────────────────────

def music_status(settings=None):
    """Return a status dict for display in UI/API."""
    backend = preferred_backend(settings)
    poryaaaa_ver = poryaaaa_version(settings) if backend == "poryaaaa" else None
    player = audio_player_name(settings)
    c_size = cache_size()

    return {
        "backend": backend,
        "backend_label": "poryaaaa" if backend == "poryaaaa" else "Built-in MIDI",
        "poryaaaa_version": poryaaaa_ver,
        "poryaaaa_path": find_poryaaaa(settings),
        "audio_player": player,
        "cache_size_bytes": c_size,
        "cache_size_mb": round(c_size / (1024 * 1024), 1),
    }
