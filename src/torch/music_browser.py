"""TORCH Music Browser — TUI for browsing and playing music."""
# TORCH_MODULE: Music Browser
# TORCH_GROUP: Music

import os

from torch.config import SETTINGS_DEFAULTS, _nav_keys
from torch.colours import GOLD, WHITE, CYAN, GREEN, RED, DIM, RST, DGOLD, BAR
from torch.ui import print_logo, _set_terminal_title, _k, clear_screen


# ── Filter modes ─────────────────────────────────────────────────────────────

_FILTER_MODES = ["all", "music", "sfx", "custom"]
_FILTER_LABELS = {"all": "All", "music": "Music", "sfx": "SFX", "custom": "Custom"}


# ── Rendering ────────────────────────────────────────────────────────────────

def _type_tag(song):
    """Return a coloured tag for the song type."""
    if song.is_custom:
        return f"{GREEN}custom{RST}"
    if song.constant.startswith("SE_"):
        return f"{DIM}sfx{RST}"
    return f"{DIM}mus{RST}"


def _render_list(songs, total, selected, scroll_top, page_size,
                 filter_mode, search_query, status, nav_up, nav_down,
                 now_playing, proj_name):
    """Render the music browser screen."""
    clear_screen()
    print_logo()

    # Header
    label = proj_name or "Music Browser"
    print(f"  {GOLD}+-- {label} -- Music {'─' * max(1, 30 - len(label))}+{RST}")
    print()

    # Status bar
    backend = status.get("backend_label", "none")
    cache_mb = status.get("cache_size_mb", 0)
    mus_count = sum(1 for s in songs if s.constant.startswith("MUS_"))
    se_count = sum(1 for s in songs if s.constant.startswith("SE_"))
    custom_count = sum(1 for s in songs if s.is_custom)

    print(f"  {total} tracks  {DIM}({mus_count} music, {se_count} sfx, "
          f"{custom_count} custom){RST}  "
          f"{DIM}backend: {backend}  cache: {cache_mb} MB{RST}")
    print()

    # Filter bar
    parts = []
    for mode in _FILTER_MODES:
        label = _FILTER_LABELS[mode]
        if mode == filter_mode:
            parts.append(f"[{WHITE}{label}{RST}]")
        else:
            parts.append(f" {DIM}{label}{RST} ")
    filter_str = "  ".join(parts)
    if search_query:
        filter_str += f"  {DIM}search: {search_query}{RST}"
    print(f"  {filter_str}")
    print()

    # Song list
    if total == 0:
        if search_query:
            print(f"  {DIM}No matches for '{search_query}'.{RST}")
        else:
            print(f"  {DIM}No songs found.{RST}")
        print()
    else:
        end = min(scroll_top + page_size, total)
        for i in range(scroll_top, end):
            song = songs[i]
            marker = f"{GOLD}>{RST}" if i == selected else " "
            playing = "♪ " if now_playing and now_playing == song.constant else "  "

            name = song.name[:30].ljust(30)
            vg = song.voicegroup or ""
            if vg:
                vg = f"{DIM}{vg}{RST}"
            vol = f"V:{song.volume}" if song.volume else ""

            tag = _type_tag(song)
            has_midi = "♪" if song.midi_file else " "

            print(f"  {marker} {playing}{has_midi} {name} {tag:>20s}  "
                  f"{vg:>20s}  {DIM}{vol}{RST}")

        if total > page_size:
            print(f"\n  {DIM}{scroll_top + 1}-{end} of {total}{RST}")

    print()

    # Now playing bar
    if now_playing:
        print(f"  {GOLD}♪ Now playing: {WHITE}{now_playing}{RST}")
        print()

    # Controls
    print(f"  {DIM}[Enter] Play/Stop  [{nav_up}/{nav_down}] Navigate  "
          f"[f] Filter  [/] Search  [i] Info  [q] Back{RST}")


def _show_info(song, game_path):
    """Show detailed info for a song."""
    clear_screen()
    print()
    print(f"  {GOLD}+-- Song Info ──────────────────────────────+{RST}")
    print()
    print(f"  {WHITE}Name:{RST}       {song.name}")
    print(f"  {WHITE}Constant:{RST}   {song.constant}")
    print(f"  {WHITE}ID:{RST}         {song.song_id}")
    print(f"  {WHITE}Type:{RST}       {'Custom' if song.is_custom else 'Vanilla'}")
    print()
    print(f"  {WHITE}MIDI file:{RST}  {song.midi_file or 'none'}")
    print(f"  {WHITE}Assembly:{RST}   {'yes' if song.has_assembly else 'no'}")
    print()
    print(f"  {WHITE}Voicegroup:{RST} {song.voicegroup or 'default'}")
    print(f"  {WHITE}Volume:{RST}     {song.volume or 'default'}")
    print(f"  {WHITE}Reverb:{RST}     {song.reverb or 'default'}")
    print(f"  {WHITE}Priority:{RST}   {song.priority or 'default'}")
    print()
    input(f"  {DIM}Press Enter{RST} > ")


# ── Setup wizard ─────────────────────────────────────────────────────────────

def _music_setup(settings):
    """Guide the user through poryaaaa_render setup."""
    from torch.music_player import (
        find_poryaaaa, poryaaaa_available, poryaaaa_version,
        find_audio_player, audio_player_name, preferred_backend,
    )

    clear_screen()
    print()
    print(f"  {GOLD}+-- Music Setup ────────────────────────────+{RST}")
    print()

    backend = preferred_backend(settings)
    if backend == "poryaaaa":
        ver = poryaaaa_version(settings) or "unknown"
        path = find_poryaaaa(settings)
        print(f"  {GREEN}poryaaaa_render installed{RST}")
        print(f"  Version: {ver}")
        print(f"  Path: {path}")
        print()
    else:
        print(f"  Playback backend: {WHITE}built-in MIDI synth{RST} (basic quality)")
        print()
        print(f"  For GBA-accurate playback, install poryaaaa_render:")
        print(f"    1. Download the Linux release from:")
        print(f"       {CYAN}https://github.com/huderlem/poryaaaa/releases{RST}")
        print(f"    2. Extract the zip")
        print(f"    3. Move poryaaaa_render to a directory on your PATH")
        print(f"       (e.g., ~/.local/bin/)")
        print()

        try:
            raw = input(f"  Or enter path to poryaaaa_render (Enter to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if raw and os.path.isfile(raw) and os.access(raw, os.X_OK):
            # Save to config
            settings["poryaaaa_path"] = raw
            from torch.config import load_config, save_config
            config = load_config()
            if config:
                ws, projects, cfg_settings = config
                cfg_settings["poryaaaa_path"] = raw
                save_config(ws, projects, cfg_settings)
            print(f"  {GREEN}Saved.{RST}")
            print()
        elif raw:
            print(f"  {RED}File not found or not executable.{RST}")
            print()

    # Audio player check
    player = audio_player_name(settings)
    if player:
        print(f"  Audio player: {GREEN}{player}{RST}")
    else:
        print(f"  {RED}No audio player found.{RST}")
        print(f"  {DIM}Install pw-play, paplay, or aplay.{RST}")
    print()

    input(f"  {DIM}Press Enter{RST} > ")


# ── Main browser loop ────────────────────────────────────────────────────────

def music_browser(game_path, settings=None, proj_name=None):
    """Music Browser — browse and play music tracks."""
    from torch.music_player import (
        list_songs, play_song, stop_playback, is_playing,
        music_status,
    )

    if settings is None:
        settings = dict(SETTINGS_DEFAULTS)

    _set_terminal_title("TORCH -- Music Browser")
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)
    page_size = settings.get("trainer_list_page_size", 20)

    all_songs = list_songs(game_path)
    filter_mode = "all"
    search_query = ""
    now_playing = None

    st = {"selected_idx": 0, "scroll_top": 0}

    while True:
        # Apply filters
        if filter_mode == "all" and not search_query:
            visible = all_songs
        else:
            visible = list_songs(game_path, filter_type=filter_mode if filter_mode != "all" else None)
            if search_query:
                q = search_query.upper()
                visible = [s for s in visible if q in s.constant.upper() or q in s.name.upper()]

        total = len(visible)

        # Clamp selection
        if total == 0:
            st["selected_idx"] = 0
        else:
            st["selected_idx"] = max(0, min(st["selected_idx"], total - 1))

        # Scroll to keep selected in view
        if total > 0:
            if st["selected_idx"] < st["scroll_top"]:
                st["scroll_top"] = st["selected_idx"]
            if st["selected_idx"] >= st["scroll_top"] + page_size:
                st["scroll_top"] = st["selected_idx"] - page_size + 1

        # Update playing status
        if now_playing and not is_playing():
            now_playing = None

        status = music_status(settings)

        _render_list(visible, total, st["selected_idx"], st["scroll_top"],
                     page_size, filter_mode, search_query, status,
                     NK_UP, NK_DOWN, now_playing, proj_name)

        try:
            raw = input(f"  {GOLD}>{RST} ")
        except (EOFError, KeyboardInterrupt):
            stop_playback()
            return

        raw = raw.rstrip("\n")
        choice = raw.strip()
        cmd = choice.lower()

        # Enter or scroll key: play/stop or scroll
        if raw == "" or raw == " " or cmd == NK_SCROLL:
            if total > 0:
                st["selected_idx"] = (st["selected_idx"] + 1) % total
            continue

        # Navigation
        if cmd == NK_UP:
            if total > 0:
                st["selected_idx"] = (st["selected_idx"] - 1) % total
            continue
        if cmd == NK_DOWN:
            if total > 0:
                st["selected_idx"] = (st["selected_idx"] + 1) % total
            continue

        # Open / play
        if cmd == NK_OPEN or cmd == "p":
            if total == 0:
                continue
            song = visible[st["selected_idx"]]
            if now_playing == song.constant:
                stop_playback()
                now_playing = None
            else:
                if not song.midi_file:
                    # Can't play SE_ or songs without MIDI
                    continue
                stop_playback()
                ok = play_song(game_path, song.constant, settings=settings)
                now_playing = song.constant if ok else None
            continue

        # Filter
        if cmd == "f":
            idx = _FILTER_MODES.index(filter_mode)
            filter_mode = _FILTER_MODES[(idx + 1) % len(_FILTER_MODES)]
            st["selected_idx"] = 0
            st["scroll_top"] = 0
            continue

        # Search
        if cmd == "/":
            try:
                query = input(f"  {GOLD}Search:{RST} ").strip()
                search_query = query
                st["selected_idx"] = 0
                st["scroll_top"] = 0
            except (EOFError, KeyboardInterrupt):
                pass
            continue

        # Clear search
        if cmd == "c" and search_query:
            search_query = ""
            st["selected_idx"] = 0
            st["scroll_top"] = 0
            continue

        # Info
        if cmd == "i":
            if total > 0:
                _show_info(visible[st["selected_idx"]], game_path)
            continue

        # Setup
        if cmd == "s":
            _music_setup(settings)
            continue

        # Quit
        if cmd == "q":
            stop_playback()
            return
