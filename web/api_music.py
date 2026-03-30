# TORCH_MODULE: Web API — Music
# TORCH_GROUP: Web
"""Music Browser API endpoints for the TORCH web GUI.

Provides song listing with metadata, render-on-demand .wav streaming
for browser playback, backend status, and cache management.
"""

import os
import time

from torch.web.api import (
    api_route, ok_response, error_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_game_path(handler):
    """Return game_path from server, or None."""
    return getattr(handler.server, "game_path", "") or None


def _get_settings(handler):
    """Return settings dict from server, or empty dict."""
    return getattr(handler.server, "settings", {}) or {}


# Song list cache (avoid re-parsing on every request)
_song_cache = {"data": None, "ts": 0}
_CACHE_TTL = 30  # seconds


def _cached_songs(game_path):
    """Return cached song list."""
    from torch.music_player import list_songs
    now = time.time()
    if _song_cache["data"] and now - _song_cache["ts"] < _CACHE_TTL:
        return _song_cache["data"]
    songs = list_songs(game_path)
    _song_cache["data"] = songs
    _song_cache["ts"] = now
    return songs


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_route("GET", "/api/music/songs")
def handle_music_songs(handler, match, query_params):
    """List all songs with metadata.  Optional filter param."""
    game_path = _get_game_path(handler)
    if not game_path:
        return error_response("No project loaded", 400)

    filter_type = query_params.get("filter", [None])[0]
    if filter_type and filter_type not in ("music", "sfx", "custom"):
        filter_type = None

    from torch.music_player import list_songs
    songs = list_songs(game_path, filter_type=filter_type)
    return ok_response([s.to_dict() for s in songs])


@api_route("GET", r"/api/music/songs/([A-Za-z0-9_]+)")
def handle_music_song_detail(handler, match, query_params):
    """Get details for a single song."""
    game_path = _get_game_path(handler)
    if not game_path:
        return error_response("No project loaded", 400)

    name = match.group(1)
    from torch.music_player import song_info
    info = song_info(game_path, name)
    if not info:
        return error_response(f"Song not found: {name}", 404)
    return ok_response(info.to_dict())


@api_route("GET", r"/api/music/play/([A-Za-z0-9_]+)")
def handle_music_play(handler, match, query_params):
    """Stream a rendered .wav file for browser <audio> playback.

    Renders on first request, serves from cache on subsequent requests.
    Returns raw audio/wav bytes (not JSON).
    """
    game_path = _get_game_path(handler)
    if not game_path:
        return error_response("No project loaded", 400)

    name = match.group(1)
    settings = _get_settings(handler)

    from torch.music_player import render_song_cached
    wav_path = render_song_cached(game_path, name, settings=settings)

    if not wav_path or not os.path.isfile(wav_path):
        return error_response(f"Could not render: {name}", 500)

    # Serve the wav file
    try:
        with open(wav_path, "rb") as f:
            data = f.read()
        handler.send_response(200)
        handler.send_header("Content-Type", "audio/wav")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "max-age=300")
        handler.end_headers()
        handler.wfile.write(data)
        return None  # Signal: response already sent
    except Exception as e:
        return error_response(f"Error serving audio: {e}", 500)


@api_route("GET", r"/api/music/midi/([A-Za-z0-9_]+)")
def handle_music_midi(handler, match, query_params):
    """Serve a raw .mid file for browser-side MIDI playback.

    Returns raw audio/midi bytes (not JSON).
    """
    game_path = _get_game_path(handler)
    if not game_path:
        return error_response("No project loaded", 400)

    name = match.group(1).lower()
    if not name.startswith("mus_"):
        name = f"mus_{name}"

    midi_path = os.path.join(game_path, "sound", "songs", "midi", f"{name}.mid")
    if not os.path.isfile(midi_path):
        return error_response(f"MIDI file not found: {name}", 404)

    try:
        with open(midi_path, "rb") as f:
            data = f.read()
        handler.send_response(200)
        handler.send_header("Content-Type", "audio/midi")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "max-age=3600")
        handler.end_headers()
        handler.wfile.write(data)
        return None
    except Exception as e:
        return error_response(f"Error serving MIDI: {e}", 500)


@api_route("GET", "/api/music/status")
def handle_music_status(handler, match, query_params):
    """Return backend status, cache size, etc."""
    settings = _get_settings(handler)
    from torch.music_player import music_status
    return ok_response(music_status(settings))


@api_route("POST", "/api/music/cache/clear")
def handle_music_cache_clear(handler, match, query_params):
    """Clear the render cache."""
    from torch.music_player import cache_clear
    cache_clear()
    _song_cache["data"] = None
    return ok_response({"cleared": True})


@api_route("GET", "/api/music/voicegroups")
def handle_music_voicegroups(handler, match, query_params):
    """List available voicegroups from midi.cfg."""
    game_path = _get_game_path(handler)
    if not game_path:
        return error_response("No project loaded", 400)

    from torch.music_player import parse_midi_cfg
    cfg = parse_midi_cfg(game_path)

    # Collect unique voicegroups
    vgs = {}
    for filename, entry in cfg.items():
        if entry.voicegroup:
            vg = entry.voicegroup
            if vg not in vgs:
                vgs[vg] = {"name": vg, "songs": []}
            vgs[vg]["songs"].append(filename.replace(".mid", "").upper())

    result = sorted(vgs.values(), key=lambda v: v["name"])
    return ok_response(result)
