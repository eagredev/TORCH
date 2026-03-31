/**
 * TORCH Studio — Music Status Bar Widget.
 * Spotify-style floating music player anchored to the IDE status bar.
 * Compact playback controls, playlist browsing, and transport — always
 * available while editing maps without leaving the workspace.
 *
 * TORCH_MODULE
 */

import { api } from "./app.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 40;
const LS_VOLUME = "torch-music-volume";
const LS_SHUFFLE = "torch-music-shuffle";
const LS_LOOP = "torch-music-loop";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _panelEl = null;
let _toggleBtn = null;
let _isOpen = false;
let _audioEl = null;
let _allSongs = null;
let _filteredSongs = [];
let _queue = [];
let _queueIndex = -1;
let _nowPlaying = null;
let _isPlaying = false;
let _shuffle = false;
let _loop = false;
let _volume = 0.7;
let _progressRAF = null;
let _searchQuery = "";
let _activeCategory = "music";
let _escHandler = null;
let _rendered = 0;
let _scrollFn = null;
let _debounceTimer = null;
let _loadingPlayback = false;

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

function _loadPrefs() {
  try {
    const v = localStorage.getItem(LS_VOLUME);
    if (v !== null) _volume = parseFloat(v);
    _shuffle = localStorage.getItem(LS_SHUFFLE) === "true";
    _loop = localStorage.getItem(LS_LOOP) === "true";
  } catch (_) {}
}

function _saveVolume() {
  try { localStorage.setItem(LS_VOLUME, String(_volume)); } catch (_) {}
}
function _saveShuffle() {
  try { localStorage.setItem(LS_SHUFFLE, String(_shuffle)); } catch (_) {}
}
function _saveLoop() {
  try { localStorage.setItem(LS_LOOP, String(_loop)); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

/**
 * Initialize the Music widget. Call during IDE render().
 * @param {HTMLElement} containerEl - the ide-root or document.body
 */
export function initMusicWidget(containerEl) {
  if (_panelEl) return;

  _loadPrefs();

  // 1. Create toggle button in the status bar
  const statusBar = document.getElementById("ide-status");
  if (!statusBar) return;

  _toggleBtn = document.createElement("button");
  _toggleBtn.className = "music-widget-toggle";
  _toggleBtn.textContent = "\u266B Music";
  _toggleBtn.title = "Toggle music player";
  _toggleBtn.addEventListener("click", _toggle);

  const versionEl = document.getElementById("ide-status-version");
  if (versionEl) statusBar.insertBefore(_toggleBtn, versionEl);
  else statusBar.appendChild(_toggleBtn);

  // 2. Create dedicated audio element
  _audioEl = new Audio();
  _audioEl.volume = _volume;
  _audioEl.addEventListener("ended", _onTrackEnded);

  // 3. Create the floating panel
  _panelEl = document.createElement("div");
  _panelEl.className = "music-widget-panel";
  _buildPanelDOM();

  const root = containerEl.querySelector(".ide-root") || containerEl;
  root.appendChild(_panelEl);

  // 4. Escape key closes panel
  _escHandler = (e) => {
    if (e.key === "Escape" && _isOpen) {
      e.stopPropagation();
      _close();
    }
  };
  document.addEventListener("keydown", _escHandler);
}

/** Tear down the widget. Call during IDE cleanup(). */
export function cleanupMusicWidget() {
  if (_escHandler) {
    document.removeEventListener("keydown", _escHandler);
    _escHandler = null;
  }
  _stopProgressLoop();
  if (_audioEl) {
    _audioEl.pause();
    _audioEl.removeEventListener("ended", _onTrackEnded);
    if (_audioEl.src && _audioEl.src.startsWith("blob:")) {
      URL.revokeObjectURL(_audioEl.src);
    }
    _audioEl = null;
  }
  if (_debounceTimer) clearTimeout(_debounceTimer);
  if (_scrollFn && _panelEl) {
    const playlist = _panelEl.querySelector(".music-widget-playlist");
    if (playlist) playlist.removeEventListener("scroll", _scrollFn);
  }
  if (_panelEl) { _panelEl.remove(); _panelEl = null; }
  if (_toggleBtn) { _toggleBtn.remove(); _toggleBtn = null; }
  _isOpen = false;
  _allSongs = null;
  _filteredSongs = [];
  _queue = [];
  _queueIndex = -1;
  _nowPlaying = null;
  _isPlaying = false;
  _rendered = 0;
  _scrollFn = null;
  _searchQuery = "";
  _loadingPlayback = false;
}

// ---------------------------------------------------------------------------
// Open / Close / Toggle
// ---------------------------------------------------------------------------

function _toggle() {
  if (_isOpen) _close();
  else _open();
}

function _open() {
  if (!_panelEl) return;
  _panelEl.classList.add("open");
  if (_toggleBtn) _toggleBtn.classList.add("active");
  _isOpen = true;

  // Lazy-load songs on first open
  if (!_allSongs) _loadSongs();
}

function _close() {
  if (!_panelEl) return;
  _panelEl.classList.remove("open");
  if (_toggleBtn) _toggleBtn.classList.remove("active");
  _isOpen = false;
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function _loadSongs() {
  const body = _panelEl.querySelector(".music-widget-playlist");
  if (body) body.innerHTML = `<div class="music-widget-loading">Loading songs...</div>`;

  const res = await api("/api/music/songs");
  if (!res.ok) {
    if (body) body.innerHTML = `<div class="music-widget-loading">Error loading songs</div>`;
    return;
  }
  _allSongs = res.data || [];
  _applyFilters();
  _renderPlaylist();
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

function _applyFilters() {
  if (!_allSongs) return;
  let songs = _allSongs;

  if (_activeCategory === "music") {
    songs = songs.filter(s => s.constant.startsWith("MUS_"));
  } else if (_activeCategory === "sfx") {
    songs = songs.filter(s => s.constant.startsWith("SE_"));
  } else if (_activeCategory === "custom") {
    songs = songs.filter(s => s.is_custom);
  }
  // "all" = no filter

  if (_searchQuery) {
    const q = _searchQuery.toLowerCase();
    songs = songs.filter(s =>
      s.name.toLowerCase().includes(q) ||
      s.constant.toLowerCase().includes(q)
    );
  }

  _filteredSongs = songs;
  _rebuildQueue();
}

function _rebuildQueue() {
  _queue = _filteredSongs.slice();
  // If currently playing, try to find it in the new queue
  if (_nowPlaying) {
    const idx = _queue.findIndex(s => s.constant === _nowPlaying.constant);
    _queueIndex = idx >= 0 ? idx : -1;
  } else {
    _queueIndex = -1;
  }
}

// ---------------------------------------------------------------------------
// Panel DOM
// ---------------------------------------------------------------------------

function _buildPanelDOM() {
  _panelEl.innerHTML = "";

  // Header
  const header = document.createElement("div");
  header.className = "music-widget-header";
  const titleSpan = document.createElement("span");
  titleSpan.className = "music-widget-title";
  titleSpan.textContent = "\u266B Music";
  header.appendChild(titleSpan);
  const closeBtn = document.createElement("button");
  closeBtn.className = "music-widget-close";
  closeBtn.textContent = "\u00d7";
  closeBtn.addEventListener("click", _close);
  header.appendChild(closeBtn);
  _panelEl.appendChild(header);

  // Now-playing track info
  const track = document.createElement("div");
  track.className = "music-widget-track";
  track.id = "mw-track";
  const trackName = document.createElement("span");
  trackName.className = "music-widget-track-name";
  trackName.id = "mw-track-name";
  trackName.textContent = "No track selected";
  track.appendChild(trackName);
  _panelEl.appendChild(track);

  // Progress bar
  const progressWrap = document.createElement("div");
  progressWrap.className = "music-widget-progress-wrap";

  const progressBar = document.createElement("div");
  progressBar.className = "music-widget-progress";
  progressBar.id = "mw-progress";
  const progressFill = document.createElement("div");
  progressFill.className = "music-widget-progress-fill";
  progressFill.id = "mw-progress-fill";
  progressBar.appendChild(progressFill);
  progressBar.addEventListener("click", _onProgressClick);
  progressWrap.appendChild(progressBar);

  const timeRow = document.createElement("div");
  timeRow.className = "music-widget-progress-time";
  const timeCur = document.createElement("span");
  timeCur.id = "mw-time-cur";
  timeCur.textContent = "0:00";
  const timeDur = document.createElement("span");
  timeDur.id = "mw-time-dur";
  timeDur.textContent = "0:00";
  timeRow.appendChild(timeCur);
  timeRow.appendChild(timeDur);
  progressWrap.appendChild(timeRow);

  _panelEl.appendChild(progressWrap);

  // Transport controls
  const transport = document.createElement("div");
  transport.className = "music-widget-transport";

  const btnPrev = _makeTransportBtn("mw-prev", "\u23EE", "Previous", _prev);
  const btnPlay = _makeTransportBtn("mw-play", "\u25B6", "Play/Pause", _togglePlay);
  const btnNext = _makeTransportBtn("mw-next", "\u23ED", "Next", _next);
  const btnShuffle = _makeTransportBtn("mw-shuffle", "\uD83D\uDD00", "Shuffle", _toggleShuffle);
  const btnLoop = _makeTransportBtn("mw-loop", "\uD83D\uDD01", "Loop", _toggleLoop);

  if (_shuffle) btnShuffle.classList.add("active");
  if (_loop) btnLoop.classList.add("active");

  transport.appendChild(btnShuffle);
  transport.appendChild(btnPrev);
  transport.appendChild(btnPlay);
  transport.appendChild(btnNext);
  transport.appendChild(btnLoop);

  // Volume slider
  const volWrap = document.createElement("div");
  volWrap.className = "music-widget-volume";
  const volIcon = document.createElement("span");
  volIcon.className = "music-widget-vol-icon";
  volIcon.textContent = "\uD83D\uDD0A";
  volWrap.appendChild(volIcon);
  const volSlider = document.createElement("input");
  volSlider.type = "range";
  volSlider.min = "0";
  volSlider.max = "1";
  volSlider.step = "0.01";
  volSlider.value = String(_volume);
  volSlider.className = "music-widget-vol-slider";
  volSlider.id = "mw-vol";
  volSlider.addEventListener("input", _onVolumeChange);
  volWrap.appendChild(volSlider);
  transport.appendChild(volWrap);

  _panelEl.appendChild(transport);

  // Filter row
  const filterRow = document.createElement("div");
  filterRow.className = "music-widget-filter-row";

  const searchInput = document.createElement("input");
  searchInput.type = "text";
  searchInput.className = "music-widget-search";
  searchInput.placeholder = "Search...";
  searchInput.autocomplete = "off";
  searchInput.addEventListener("input", () => {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(() => {
      _searchQuery = searchInput.value.trim();
      _applyFilters();
      _renderPlaylist();
    }, 200);
  });
  filterRow.appendChild(searchInput);

  const chips = document.createElement("div");
  chips.className = "music-widget-chips";
  for (const cat of ["music", "sfx", "custom", "all"]) {
    const chip = document.createElement("button");
    chip.className = "music-widget-chip" + (cat === _activeCategory ? " active" : "");
    chip.dataset.cat = cat;
    chip.textContent = cat === "music" ? "Music" : cat === "sfx" ? "SFX" : cat === "custom" ? "Custom" : "All";
    chip.addEventListener("click", () => {
      _activeCategory = cat;
      _syncChips();
      _applyFilters();
      _renderPlaylist();
    });
    chips.appendChild(chip);
  }
  filterRow.appendChild(chips);
  _panelEl.appendChild(filterRow);

  // Playlist
  const playlist = document.createElement("div");
  playlist.className = "music-widget-playlist";
  playlist.id = "mw-playlist";
  _panelEl.appendChild(playlist);
}

function _makeTransportBtn(id, label, title, handler) {
  const btn = document.createElement("button");
  btn.className = "music-widget-tbtn";
  btn.id = id;
  btn.textContent = label;
  btn.title = title;
  btn.addEventListener("click", handler);
  return btn;
}

// ---------------------------------------------------------------------------
// Playlist rendering
// ---------------------------------------------------------------------------

function _renderPlaylist() {
  const container = _panelEl ? _panelEl.querySelector(".music-widget-playlist") : null;
  if (!container) return;

  if (_scrollFn) {
    container.removeEventListener("scroll", _scrollFn);
    _scrollFn = null;
  }
  _rendered = 0;
  container.innerHTML = "";

  if (!_filteredSongs.length) {
    const empty = document.createElement("div");
    empty.className = "music-widget-loading";
    empty.textContent = _searchQuery ? "No matches" : "No songs found";
    container.appendChild(empty);
    return;
  }

  _rendered = _appendPlaylistRows(container, 0, PAGE_SIZE);
  _setupPlaylistScroll(container);
}

function _appendPlaylistRows(container, start, count) {
  const end = Math.min(start + count, _filteredSongs.length);
  const frag = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const song = _filteredSongs[i];
    const row = document.createElement("div");
    row.className = "music-widget-playlist-item";
    if (_nowPlaying && _nowPlaying.constant === song.constant) {
      row.classList.add("active");
    }
    row.dataset.constant = song.constant;

    const indicator = document.createElement("span");
    indicator.className = "music-widget-pl-indicator";
    indicator.textContent = (_nowPlaying && _nowPlaying.constant === song.constant && _isPlaying) ? "\u25B6" : "";
    row.appendChild(indicator);

    const name = document.createElement("span");
    name.className = "music-widget-pl-name";
    name.textContent = song.name;
    row.appendChild(name);

    row.addEventListener("click", () => {
      const idx = _queue.findIndex(s => s.constant === song.constant);
      if (idx >= 0) {
        _queueIndex = idx;
        _playSong(_queue[_queueIndex]);
      }
    });
    frag.appendChild(row);
  }
  container.appendChild(frag);
  return end;
}

function _setupPlaylistScroll(container) {
  _scrollFn = () => {
    if (_rendered >= _filteredSongs.length) return;
    const threshold = container.scrollHeight - container.clientHeight - 100;
    if (container.scrollTop >= threshold) {
      _rendered = _appendPlaylistRows(container, _rendered, PAGE_SIZE);
    }
  };
  container.addEventListener("scroll", _scrollFn);
}

function _highlightActive() {
  if (!_panelEl) return;
  const items = _panelEl.querySelectorAll(".music-widget-playlist-item");
  items.forEach(item => {
    const isActive = _nowPlaying && item.dataset.constant === _nowPlaying.constant;
    item.classList.toggle("active", isActive);
    const indicator = item.querySelector(".music-widget-pl-indicator");
    if (indicator) {
      indicator.textContent = (isActive && _isPlaying) ? "\u25B6" : "";
    }
  });
}

function _syncChips() {
  if (!_panelEl) return;
  _panelEl.querySelectorAll(".music-widget-chip").forEach(c => {
    c.classList.toggle("active", c.dataset.cat === _activeCategory);
  });
}

// ---------------------------------------------------------------------------
// Playback
// ---------------------------------------------------------------------------

function _playSong(song) {
  if (!song || !_audioEl) return;

  // Stop current
  _audioEl.pause();
  if (_audioEl.src && _audioEl.src.startsWith("blob:")) {
    URL.revokeObjectURL(_audioEl.src);
  }
  _stopProgressLoop();

  _nowPlaying = song;
  _isPlaying = false;
  _loadingPlayback = true;
  _updateTrackDisplay();
  _updateToggleBtn();
  _highlightActive();
  _updatePlayBtn();

  const stem = song.constant.toLowerCase();

  fetch(`/api/music/play/${stem}`)
    .then(resp => {
      if (!_nowPlaying || _nowPlaying.constant !== song.constant) return null;
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return resp.blob();
    })
    .then(blob => {
      if (!blob || !_nowPlaying || _nowPlaying.constant !== song.constant) return;
      _audioEl.src = URL.createObjectURL(blob);
      _audioEl.volume = _volume;
      _loadingPlayback = false;
      return _audioEl.play();
    })
    .then(() => {
      if (_nowPlaying && _nowPlaying.constant === song.constant) {
        _isPlaying = true;
        _updatePlayBtn();
        _updateToggleBtn();
        _highlightActive();
        _startProgressLoop();
      }
    })
    .catch(() => {
      if (_nowPlaying && _nowPlaying.constant === song.constant) {
        _loadingPlayback = false;
        _nowPlaying = null;
        _isPlaying = false;
        _updateTrackDisplay();
        _updatePlayBtn();
        _updateToggleBtn();
        _highlightActive();
        // Show error briefly in track name
        const nameEl = _panelEl ? _panelEl.querySelector("#mw-track-name") : null;
        if (nameEl) nameEl.textContent = "Playback failed";
      }
    });
}

function _onTrackEnded() {
  _isPlaying = false;
  _stopProgressLoop();
  _next();
}

function _togglePlay() {
  if (!_audioEl) return;
  if (!_nowPlaying) {
    // Nothing playing — start first song in queue
    if (_queue.length) {
      _queueIndex = 0;
      _playSong(_queue[0]);
    }
    return;
  }

  if (_isPlaying) {
    _audioEl.pause();
    _isPlaying = false;
    _stopProgressLoop();
  } else {
    _audioEl.play().then(() => {
      _isPlaying = true;
      _startProgressLoop();
    }).catch(() => {});
  }
  _updatePlayBtn();
  _updateToggleBtn();
  _highlightActive();
}

function _next() {
  if (!_queue.length) return;

  if (_shuffle) {
    // Random index different from current if possible
    if (_queue.length > 1) {
      let next;
      do { next = Math.floor(Math.random() * _queue.length); } while (next === _queueIndex);
      _queueIndex = next;
    } else {
      _queueIndex = 0;
    }
  } else {
    _queueIndex++;
    if (_queueIndex >= _queue.length) {
      if (_loop) {
        _queueIndex = 0;
      } else {
        // End of queue, stop
        _queueIndex = _queue.length - 1;
        _isPlaying = false;
        _stopProgressLoop();
        _updatePlayBtn();
        _updateToggleBtn();
        _highlightActive();
        return;
      }
    }
  }
  _playSong(_queue[_queueIndex]);
}

function _prev() {
  if (!_audioEl || !_nowPlaying) return;

  // If more than 3 seconds in, restart current track
  if (_audioEl.currentTime > 3) {
    _audioEl.currentTime = 0;
    return;
  }

  if (!_queue.length) return;
  _queueIndex--;
  if (_queueIndex < 0) {
    _queueIndex = _loop ? _queue.length - 1 : 0;
  }
  _playSong(_queue[_queueIndex]);
}

function _toggleShuffle() {
  _shuffle = !_shuffle;
  _saveShuffle();
  const btn = _panelEl ? _panelEl.querySelector("#mw-shuffle") : null;
  if (btn) btn.classList.toggle("active", _shuffle);
}

function _toggleLoop() {
  _loop = !_loop;
  _saveLoop();
  const btn = _panelEl ? _panelEl.querySelector("#mw-loop") : null;
  if (btn) btn.classList.toggle("active", _loop);
}

function _onVolumeChange(e) {
  _volume = parseFloat(e.target.value);
  if (_audioEl) _audioEl.volume = _volume;
  _saveVolume();
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

function _startProgressLoop() {
  _stopProgressLoop();
  const tick = () => {
    _updateProgress();
    _progressRAF = requestAnimationFrame(tick);
  };
  _progressRAF = requestAnimationFrame(tick);
}

function _stopProgressLoop() {
  if (_progressRAF) {
    cancelAnimationFrame(_progressRAF);
    _progressRAF = null;
  }
}

function _updateProgress() {
  if (!_audioEl || !_panelEl) return;
  const fill = _panelEl.querySelector("#mw-progress-fill");
  const curEl = _panelEl.querySelector("#mw-time-cur");
  const durEl = _panelEl.querySelector("#mw-time-dur");
  if (!fill) return;

  const cur = _audioEl.currentTime || 0;
  const dur = _audioEl.duration || 0;
  const pct = dur > 0 ? (cur / dur) * 100 : 0;

  fill.style.width = pct + "%";
  if (curEl) curEl.textContent = _fmtTime(cur);
  if (durEl) durEl.textContent = dur > 0 ? _fmtTime(dur) : "--:--";
}

function _onProgressClick(e) {
  if (!_audioEl || !_audioEl.duration) return;
  const rect = e.currentTarget.getBoundingClientRect();
  const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  _audioEl.currentTime = pct * _audioEl.duration;
  _updateProgress();
}

function _fmtTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m + ":" + String(s).padStart(2, "0");
}

// ---------------------------------------------------------------------------
// UI updates
// ---------------------------------------------------------------------------

function _updateTrackDisplay() {
  if (!_panelEl) return;
  const nameEl = _panelEl.querySelector("#mw-track-name");
  if (!nameEl) return;
  if (_nowPlaying) {
    nameEl.textContent = _nowPlaying.name;
    nameEl.classList.add("playing");
  } else {
    nameEl.textContent = "No track selected";
    nameEl.classList.remove("playing");
  }
}

function _updatePlayBtn() {
  if (!_panelEl) return;
  const btn = _panelEl.querySelector("#mw-play");
  if (!btn) return;
  btn.textContent = _isPlaying ? "\u23F8" : "\u25B6";
}

function _updateToggleBtn() {
  if (!_toggleBtn) return;
  if (_nowPlaying && _isPlaying) {
    // Abbreviate long names
    let name = _nowPlaying.name;
    if (name.length > 14) name = name.slice(0, 13) + "\u2026";
    _toggleBtn.textContent = "\u266B " + name;
    _toggleBtn.classList.add("playing");
  } else {
    _toggleBtn.textContent = "\u266B Music";
    _toggleBtn.classList.remove("playing");
  }
}
