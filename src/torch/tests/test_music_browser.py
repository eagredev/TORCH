"""Tests for music_browser.py — TUI rendering and helpers."""

import os

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Music Browser  (TUI rendering, filters)")

    from torch.music_browser import (
        _FILTER_MODES, _FILTER_LABELS, _type_tag, _show_info,
    )
    from torch.music_player import SongInfo

    # ── Filter modes ──

    _assert("filter_modes: 4 modes", len(_FILTER_MODES) == 4)
    _assert("filter_modes: all is first", _FILTER_MODES[0] == "all")
    _assert("filter_labels: all modes have labels",
            all(m in _FILTER_LABELS for m in _FILTER_MODES))

    # ── Type tags ──

    custom_song = SongInfo("MUS_MY_THEME", "My Theme", is_custom=True)
    tag = _type_tag(custom_song)
    _assert("type_tag: custom has 'custom'", "custom" in tag)

    sfx_song = SongInfo("SE_BALL_OPEN", "Ball Open", is_custom=False)
    tag = _type_tag(sfx_song)
    _assert("type_tag: sfx has 'sfx'", "sfx" in tag)

    vanilla_song = SongInfo("MUS_PETALBURG", "Petalburg", is_custom=False)
    tag = _type_tag(vanilla_song)
    _assert("type_tag: vanilla has 'mus'", "mus" in tag)

    # ── SongInfo display ──

    song = SongInfo("MUS_TEST", "Test Song", midi_file="sound/songs/midi/mus_test.mid",
                    voicegroup="_test", volume=80, reverb=50, song_id=42,
                    is_custom=True, has_assembly=False)
    _assert("song: name", song.name == "Test Song")
    _assert("song: voicegroup", song.voicegroup == "_test")
    _assert("song: volume", song.volume == 80)

    # ── Import check ──

    from torch.music_browser import music_browser
    _assert("music_browser: callable", callable(music_browser))

    from torch.music_browser import _music_setup
    _assert("_music_setup: callable", callable(_music_setup))

    from torch.music_browser import _render_list
    _assert("_render_list: callable", callable(_render_list))
