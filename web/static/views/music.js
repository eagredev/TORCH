/**
 * TORCH Web GUI — Music Browser view.
 *
 * Browse all music tracks and sound effects with metadata.
 * Two playback modes:
 *   1. Server-rendered .wav via /api/music/play/<name> (higher quality, uses
 *      poryaaaa or built-in synth on the server)
 *   2. Client-side Web Audio MIDI playback via midiPlayer.js (instant, no
 *      server render needed)
 *
 * HTML5 <audio> element for .wav playback, midiPlayer for instant preview.
 */

import { api } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";
import { midiPlayer } from "../midiPlayer.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let allSongs = [];
let filteredSongs = [];
let status = {};
let activeFilter = "all";  // "all" | "music" | "sfx" | "custom"
let searchQuery = "";
let debounceTimer = null;
let nowPlaying = null;     // song constant currently playing
let playMode = "midi";     // "midi" (instant) or "wav" (server-rendered)
let audioEl = null;        // <audio> element for wav playback
let _container = null;

// ---------------------------------------------------------------------------
// Scoped CSS
// ---------------------------------------------------------------------------

const STYLE_ID = "music-view-css";

function injectCSS() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    .music-toolbar {
      display: flex; flex-wrap: wrap; align-items: center;
      gap: 0.75rem; margin-bottom: 1rem;
    }
    .music-search {
      flex: 1; min-width: 180px; padding: 0.4rem 0.6rem;
      font-size: 0.85rem; background: var(--surface-2);
      border: 1px solid var(--border-subtle); border-radius: 4px;
      color: #eee; outline: none;
    }
    .music-search:focus { border-color: var(--accent); }
    .music-search::placeholder { color: var(--text-muted); }

    .music-filters {
      display: flex; gap: 0.25rem;
    }
    .music-filter-btn {
      padding: 0.3rem 0.7rem; font-size: 0.8rem;
      background: var(--surface-2); border: 1px solid var(--border-subtle);
      border-radius: 4px; color: var(--text-muted); cursor: pointer;
    }
    .music-filter-btn:hover { border-color: var(--accent); color: #eee; }
    .music-filter-btn.active {
      background: var(--accent); border-color: var(--accent);
      color: #000; font-weight: bold;
    }

    .music-status-bar {
      display: flex; justify-content: space-between; align-items: center;
      padding: 0.5rem 0; font-size: 0.8rem; color: var(--text-muted);
      border-bottom: 1px solid var(--border-subtle); margin-bottom: 0.75rem;
    }

    .music-list { list-style: none; padding: 0; margin: 0; }
    .music-item {
      display: flex; align-items: center; gap: 0.75rem;
      padding: 0.5rem 0.75rem; border-radius: 4px; cursor: pointer;
      transition: background 0.1s;
    }
    .music-item:hover { background: var(--surface-2); }
    .music-item.playing { background: var(--surface-2); }
    .music-item.playing .music-name { color: var(--accent); font-weight: bold; }

    .music-play-btn {
      width: 28px; height: 28px; flex-shrink: 0;
      display: flex; align-items: center; justify-content: center;
      font-size: 0.9rem; background: var(--surface-2);
      border: 1px solid var(--border-subtle); border-radius: 50%;
      color: var(--text-muted); cursor: pointer;
    }
    .music-play-btn:hover { border-color: var(--accent); color: var(--accent); }
    .music-item.playing .music-play-btn {
      background: var(--accent); border-color: var(--accent); color: #000;
    }
    .music-play-btn.no-midi {
      opacity: 0.3; cursor: default;
    }

    .music-name { flex: 1; min-width: 0; font-size: 0.85rem; color: #ddd; }
    .music-meta {
      font-size: 0.75rem; color: var(--text-muted);
      display: flex; gap: 0.75rem; flex-shrink: 0;
    }
    .music-tag {
      font-size: 0.7rem; padding: 0.15rem 0.4rem;
      border-radius: 3px; font-weight: bold;
    }
    .music-tag.custom { background: #1b4332; color: #95d5b2; }
    .music-tag.vanilla { background: var(--surface-2); color: var(--text-muted); }

    .music-player-bar {
      position: sticky; bottom: 0; padding: 0.75rem 1rem;
      background: var(--surface-1); border-top: 1px solid var(--border-subtle);
      display: flex; align-items: center; gap: 1rem;
    }
    .music-player-bar .now-playing { flex: 1; font-size: 0.85rem; color: var(--accent); }
    .music-player-bar audio { flex: 2; max-width: 400px; height: 32px; }
    .music-player-bar .stop-btn {
      padding: 0.3rem 0.8rem; font-size: 0.8rem;
      background: var(--surface-2); border: 1px solid var(--border-subtle);
      border-radius: 4px; color: #eee; cursor: pointer;
    }

    .music-mode-toggle {
      font-size: 0.75rem; color: var(--text-muted); cursor: pointer;
      text-decoration: underline;
    }
    .music-mode-toggle:hover { color: var(--accent); }

    .music-empty {
      text-align: center; padding: 3rem; color: var(--text-muted);
    }
  `;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadSongs() {
  const res = await api("/music/songs");
  if (res.ok) allSongs = res.data;
}

async function loadStatus() {
  const res = await api("/music/status");
  if (res.ok) status = res.data;
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

function applyFilters() {
  let songs = allSongs;
  if (activeFilter === "music") songs = songs.filter(s => s.constant.startsWith("MUS_"));
  else if (activeFilter === "sfx") songs = songs.filter(s => s.constant.startsWith("SE_"));
  else if (activeFilter === "custom") songs = songs.filter(s => s.is_custom);

  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    songs = songs.filter(s =>
      s.name.toLowerCase().includes(q) ||
      s.constant.toLowerCase().includes(q) ||
      (s.voicegroup || "").toLowerCase().includes(q)
    );
  }
  filteredSongs = songs;
}

// ---------------------------------------------------------------------------
// Playback
// ---------------------------------------------------------------------------

function playSong(song) {
  stopPlayback();

  if (!song.midi_file) return;

  nowPlaying = song.constant;
  const constant = song.constant;

  if (playMode === "midi" && midiPlayer && midiPlayer.canPlay()) {
    // Client-side MIDI playback (instant)
    const stem = constant.toLowerCase();
    midiPlayer.play(`/api/music/midi/${stem}`);
    midiPlayer.onStop = () => {
      if (nowPlaying === constant) {
        nowPlaying = null;
        renderView();
      }
    };
  } else {
    // Server-side wav render via fetch-then-play (avoids <audio> event races)
    const stem = constant.toLowerCase();
    fetch(`/api/music/play/${stem}`)
      .then(resp => {
        if (nowPlaying !== constant) return;
        if (!resp.ok) throw new Error(resp.status);
        return resp.blob();
      })
      .then(blob => {
        if (!blob || nowPlaying !== constant) return;
        if (!audioEl) {
          audioEl = new Audio();
          audioEl.addEventListener("ended", () => {
            nowPlaying = null;
            renderView();
          });
        }
        audioEl.src = URL.createObjectURL(blob);
        return audioEl.play();
      })
      .catch(() => {
        // WAV failed — fall back to MIDI if available
        if (nowPlaying !== constant) return;
        if (midiPlayer && midiPlayer.canPlay()) {
          midiPlayer.play(`/api/music/midi/${constant.toLowerCase()}`);
          midiPlayer.onStop = () => {
            if (nowPlaying === constant) {
              nowPlaying = null;
              renderView();
            }
          };
        } else {
          nowPlaying = null;
          renderView();
        }
      });
  }
  renderView();
}

function stopPlayback() {
  nowPlaying = null;
  if (audioEl) { audioEl.pause(); }
  if (midiPlayer) midiPlayer.stop();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderView() {
  if (!_container) return;

  const hasMidiPlayer = midiPlayer && midiPlayer.canPlay();
  applyFilters();

  const musCount = allSongs.filter(s => s.constant.startsWith("MUS_")).length;
  const seCount = allSongs.filter(s => s.constant.startsWith("SE_")).length;
  const customCount = allSongs.filter(s => s.is_custom).length;
  const backend = status.backend_label || "unknown";
  const cacheMB = status.cache_size_mb || 0;

  const filters = ["all", "music", "sfx", "custom"].map(f => {
    const label = f === "all" ? "All" : f === "music" ? "Music" : f === "sfx" ? "SFX" : "Custom";
    const cls = f === activeFilter ? "active" : "";
    return `<button class="music-filter-btn ${cls}" data-filter="${f}">${label}</button>`;
  }).join("");

  let modeToggle = "";
  if (hasMidiPlayer) {
    const label = playMode === "midi" ? "MIDI (instant)" : "WAV (rendered)";
    modeToggle = `<span class="music-mode-toggle" id="mode-toggle">Playback: ${label}</span>`;
  }

  let listHTML = "";
  if (filteredSongs.length === 0) {
    listHTML = `<div class="music-empty">${searchQuery ? "No matches" : "No songs found"}</div>`;
  } else {
    const items = filteredSongs.map(s => {
      const isPlaying = nowPlaying === s.constant;
      const cls = isPlaying ? "music-item playing" : "music-item";
      const icon = isPlaying ? "\u25A0" : "\u25B6";
      const hasMidi = s.midi_file;
      const btnCls = hasMidi ? "music-play-btn" : "music-play-btn no-midi";
      const tag = s.is_custom
        ? `<span class="music-tag custom">custom</span>`
        : `<span class="music-tag vanilla">${s.constant.startsWith("SE_") ? "sfx" : "mus"}</span>`;
      const vg = s.voicegroup ? `<span>${esc(s.voicegroup)}</span>` : "";
      const vol = s.volume ? `<span>V:${s.volume}</span>` : "";

      return `<li class="${cls}" data-song="${esc(s.constant)}">
        <button class="${btnCls}" title="${hasMidi ? 'Play' : 'No MIDI file'}">${icon}</button>
        <span class="music-name">${esc(s.name)}</span>
        <span class="music-meta">${tag}${vg}${vol}</span>
      </li>`;
    }).join("");
    listHTML = `<ul class="music-list">${items}</ul>`;
  }

  let playerBar = "";
  if (nowPlaying) {
    const song = allSongs.find(s => s.constant === nowPlaying);
    const name = song ? song.name : nowPlaying;
    if (playMode === "wav" || !hasMidiPlayer) {
      playerBar = `<div class="music-player-bar">
        <span class="now-playing">\u266A ${esc(name)}</span>
        <button class="stop-btn" id="stop-btn">Stop</button>
      </div>`;
    } else {
      playerBar = `<div class="music-player-bar">
        <span class="now-playing">\u266A ${esc(name)}</span>
        <button class="stop-btn" id="stop-btn">Stop</button>
      </div>`;
    }
  }

  _container.innerHTML = `
    ${renderStudioNavbar("music")}
    <article>
      <header><h2>Music</h2></header>

      <div class="music-status-bar">
        <span>${filteredSongs.length} tracks (${musCount} music, ${seCount} sfx, ${customCount} custom)</span>
        <span>Backend: ${esc(backend)} \u2022 Cache: ${cacheMB} MB ${modeToggle}</span>
      </div>

      <div class="music-toolbar">
        <div class="music-filters">${filters}</div>
        <input class="music-search" type="text" placeholder="Search songs..."
               value="${esc(searchQuery)}" id="music-search">
      </div>

      ${listHTML}
    </article>
    ${playerBar}
  `;

  // Bind events
  _container.querySelectorAll(".music-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      activeFilter = btn.dataset.filter;
      renderView();
    });
  });

  const searchInput = _container.querySelector("#music-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        searchQuery = searchInput.value;
        renderView();
      }, 200);
    });
    // Restore cursor position
    searchInput.focus();
    searchInput.setSelectionRange(searchQuery.length, searchQuery.length);
  }

  _container.querySelectorAll(".music-item").forEach(item => {
    item.addEventListener("click", () => {
      const constant = item.dataset.song;
      const song = allSongs.find(s => s.constant === constant);
      if (!song || !song.midi_file) return;
      if (nowPlaying === constant) {
        stopPlayback();
        renderView();
      } else {
        playSong(song);
      }
    });
  });

  const stopBtn = _container.querySelector("#stop-btn");
  if (stopBtn) {
    stopBtn.addEventListener("click", () => {
      stopPlayback();
      renderView();
    });
  }

  const toggle = _container.querySelector("#mode-toggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      stopPlayback();
      playMode = playMode === "midi" ? "wav" : "midi";
      renderView();
    });
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export async function render(container) {
  _container = container;
  injectCSS();

  container.innerHTML = `
    ${renderStudioNavbar("music")}
    <article><header><h2>Music</h2></header>
    <p style="color:var(--text-muted)">Loading songs...</p></article>
  `;

  await Promise.all([loadSongs(), loadStatus()]);
  renderView();
}

export function cleanup() {
  stopPlayback();
  _container = null;
  clearTimeout(debounceTimer);
  allSongs = [];
  filteredSongs = [];
  searchQuery = "";
  activeFilter = "all";
  nowPlaying = null;
}
