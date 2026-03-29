/**
 * TORCH IDE — Map Tree (left panel).
 *
 * Hierarchical tree of all maps organized by map group.
 * Search filter, health badges, NPC counts.
 * Dispatches IDE_MAP_SELECTED when a map is clicked.
 */

import { api } from "./app.js";
import { esc } from "./utils.js";
import {
  ideEmit, ideOn, IDE_MAP_SELECTED, IDE_MODE_CHANGED,
  IDE_SCRIPT_LOADED, IDE_SCRIPT_UNLOADED,
} from "./ide.js";
import { initBeatPanel, cleanupBeatPanel } from "./scriptBeatPanel.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _treeEl = null;
let _searchEl = null;
let _groups = null;       // { group_order: [...], groupName: [mapName, ...] }
let _selectedMap = null;
let _searchQuery = "";
let _collapsed = {};      // groupName -> bool
let _mapUnsub = null;
let _modeUnsub = null;
let _scriptLoadUnsub = null;
let _scriptUnloadUnsub = null;
let _activeTab = "maps";    // "maps" or "beats"
let _scriptsMode = false;
let _beatTabEl = null;
let _mapsTabEl = null;
let _beatPanelHost = null;  // container for beat panel (sibling of _treeEl)

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initMapTree(container) {
  _container = container;

  // Header with tab bar + search
  const header = document.createElement("div");
  header.className = "ide-left-header";
  header.innerHTML = `
    <div style="display:flex;align-items:center;gap:0.3rem">
      <div class="ide-left-tabs">
        <button class="ide-left-tab active" data-tab="maps">Maps</button>
        <button class="ide-left-tab" data-tab="beats" style="display:none">Beats</button>
      </div>
      <button class="ide-left-collapse" title="Collapse panel">\u25C0</button>
    </div>
    <input type="text" class="ide-map-search" placeholder="Search maps..."
           id="ide-tree-search" autocomplete="off" spellcheck="false" />
  `;
  container.appendChild(header);

  header.querySelector(".ide-left-collapse").addEventListener("click", _toggleLeftCollapse);

  _mapsTabEl = header.querySelector('[data-tab="maps"]');
  _beatTabEl = header.querySelector('[data-tab="beats"]');
  _mapsTabEl.addEventListener("click", () => _switchTab("maps"));
  _beatTabEl.addEventListener("click", () => _switchTab("beats"));

  _searchEl = document.getElementById("ide-tree-search");
  _searchEl.addEventListener("input", _onSearch);

  // Tree container (Maps tab content)
  _treeEl = document.createElement("div");
  _treeEl.className = "ide-map-tree";
  container.appendChild(_treeEl);

  // Beat panel host (Beats tab content — hidden by default)
  _beatPanelHost = document.createElement("div");
  _beatPanelHost.className = "ide-beat-panel-host";
  _beatPanelHost.style.cssText = "display:none;flex:1;overflow:hidden;";
  container.appendChild(_beatPanelHost);

  // Listen for external map selection (e.g. warp navigation)
  _mapUnsub = ideOn(IDE_MAP_SELECTED, (d) => {
    if (d.source !== "tree") {
      _selectedMap = d.name;
      _renderTree();
      // Persist selection
      try { localStorage.setItem("torch-ide-last-map", d.name); } catch (_) {}
    }
  });

  // Scripts mode events
  _modeUnsub = ideOn(IDE_MODE_CHANGED, _onModeChanged);
  _scriptLoadUnsub = ideOn(IDE_SCRIPT_LOADED, _onScriptLoaded);
  _scriptUnloadUnsub = ideOn(IDE_SCRIPT_UNLOADED, _onScriptUnloaded);

  // Load data
  _loadTree();
}

export function cleanupMapTree() {
  if (_mapUnsub) _mapUnsub();
  if (_modeUnsub) _modeUnsub();
  if (_scriptLoadUnsub) _scriptLoadUnsub();
  if (_scriptUnloadUnsub) _scriptUnloadUnsub();
  _mapUnsub = null;
  _modeUnsub = null;
  _scriptLoadUnsub = null;
  _scriptUnloadUnsub = null;
  cleanupBeatPanel();
  _container = null;
  _treeEl = null;
  _searchEl = null;
  _groups = null;
  _selectedMap = null;
  _searchQuery = "";
  _collapsed = {};
  _activeTab = "maps";
  _scriptsMode = false;
  _beatTabEl = null;
  _mapsTabEl = null;
  _beatPanelHost = null;
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function _loadTree() {
  try {
    const res = await api("/explorer/regions");
    if (res.ok && res.data && res.data.regions) {
      // Convert from [{name, maps, count}] to our internal format
      const regions = res.data.regions;
      _groups = {
        group_order: regions.map(r => r.name),
      };
      for (const r of regions) {
        _groups[r.name] = r.maps || [];
      }
      _renderTree();

      // Auto-restore last selected map
      _autoRestoreLastMap();
      return;
    }
  } catch (_) {}

  // Fallback: try /api/maps for a flat list
  try {
    const res2 = await api("/maps");
    if (res2.ok && Array.isArray(res2.data)) {
      _groups = { group_order: ["All Maps"], "All Maps": res2.data };
      _renderTree();
      return;
    }
  } catch (__) {}

  if (_treeEl) {
    _treeEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim)">Failed to load maps</div>';
  }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _renderTree() {
  if (!_treeEl || !_groups) return;

  const q = _searchQuery.toLowerCase();
  const order = _groups.group_order || [];
  let html = "";

  for (const group of order) {
    const maps = _groups[group] || [];
    // Filter maps by search
    const filtered = q
      ? maps.filter(m => m.toLowerCase().includes(q))
      : maps;

    if (filtered.length === 0 && q) continue;

    const isCollapsed = _collapsed[group] && !q;
    const colClass = isCollapsed ? " collapsed" : "";

    html += `<div class="ide-tree-group">`;
    html += `<div class="ide-tree-group-header${colClass}" data-group="${esc(group)}">`;
    html += `<span class="arrow">\u25BC</span>`;
    html += `<span>${esc(_formatGroupName(group))}</span>`;
    html += `<span class="count">${filtered.length}</span>`;
    html += `</div>`;
    html += `<div class="ide-tree-group-items">`;

    for (const mapName of filtered) {
      const sel = mapName === _selectedMap ? " selected" : "";
      html += `<div class="ide-tree-map${sel}" data-map="${esc(mapName)}">`;
      html += `<span>${esc(_formatMapName(mapName))}</span>`;
      html += `</div>`;
    }

    html += `</div></div>`;
  }

  if (!html) {
    html = '<div style="padding:0.5rem 1rem;color:var(--text-dim);font-size:0.8rem">No maps found</div>';
  }

  _treeEl.innerHTML = html;

  // Attach click handlers
  _treeEl.querySelectorAll(".ide-tree-group-header").forEach(el => {
    el.addEventListener("click", _onGroupToggle);
  });
  _treeEl.querySelectorAll(".ide-tree-map").forEach(el => {
    el.addEventListener("click", _onMapClick);
  });
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Tab switching + Scripts Mode
// ---------------------------------------------------------------------------

function _switchTab(tab) {
  if (tab === _activeTab) return;
  _activeTab = tab;

  if (_mapsTabEl) _mapsTabEl.classList.toggle("active", tab === "maps");
  if (_beatTabEl) _beatTabEl.classList.toggle("active", tab === "beats");

  if (tab === "maps") {
    if (_treeEl) _treeEl.style.display = "";
    if (_searchEl) _searchEl.parentElement.querySelector(".ide-map-search").style.display = "";
    if (_beatPanelHost) _beatPanelHost.style.display = "none";
    cleanupBeatPanel();
  } else {
    if (_treeEl) _treeEl.style.display = "none";
    // Hide search bar in beats mode
    if (_searchEl) _searchEl.style.display = "none";
    if (_beatPanelHost) {
      _beatPanelHost.style.display = "flex";
      initBeatPanel(_beatPanelHost);
    }
  }
}

function _onModeChanged(detail) {
  _scriptsMode = detail.mode === "scripts";
  if (_beatTabEl) _beatTabEl.style.display = _scriptsMode ? "" : "none";
  if (!_scriptsMode && _activeTab === "beats") {
    _switchTab("maps");
  }
}

function _onScriptLoaded() {
  if (!_scriptsMode) return;
  // Auto-switch to Beats tab when a script loads
  _switchTab("beats");
}

function _onScriptUnloaded() {
  if (_activeTab === "beats") {
    _switchTab("maps");
  }
}

// ---------------------------------------------------------------------------

function _toggleLeftCollapse() {
  const left = document.getElementById("ide-left");
  const handle = document.getElementById("ide-resize-left");
  if (!left) return;

  const collapsed = left.classList.toggle("collapsed");
  if (handle) handle.style.display = collapsed ? "none" : "";

  const btn = left.querySelector(".ide-left-collapse");
  if (btn) btn.textContent = collapsed ? "\u25B6" : "\u25C0";
}

function _onSearch() {
  _searchQuery = _searchEl ? _searchEl.value : "";
  _renderTree();
}

function _onGroupToggle(e) {
  const header = e.currentTarget;
  const group = header.dataset.group;
  _collapsed[group] = !_collapsed[group];
  header.classList.toggle("collapsed");
  const items = header.nextElementSibling;
  if (items) {
    items.style.display = _collapsed[group] ? "none" : "";
  }
}

function _onMapClick(e) {
  const el = e.currentTarget;
  const mapName = el.dataset.map;
  if (!mapName || mapName === _selectedMap) return;

  _selectedMap = mapName;
  _renderTree();

  // Persist selection
  try { localStorage.setItem("torch-ide-last-map", mapName); } catch (_) {}

  // Dispatch to other panels
  ideEmit(IDE_MAP_SELECTED, { name: mapName, source: "tree" });

  // Scroll selected item into view
  const selected = _treeEl?.querySelector(".ide-tree-map.selected");
  if (selected) selected.scrollIntoView({ block: "nearest" });
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function _autoRestoreLastMap() {
  try {
    const lastMap = localStorage.getItem("torch-ide-last-map");
    if (!lastMap || !_groups) return;
    // Verify the map exists in our tree
    const allMaps = Object.values(_groups).flat().filter(m => typeof m === "string");
    if (allMaps.includes(lastMap)) {
      _selectedMap = lastMap;
      _renderTree();
      ideEmit(IDE_MAP_SELECTED, { name: lastMap, source: "restore" });
      // Scroll into view after render
      requestAnimationFrame(() => {
        const sel = _treeEl?.querySelector(".ide-tree-map.selected");
        if (sel) sel.scrollIntoView({ block: "nearest" });
      });
    }
  } catch (_) {}
}

function _formatGroupName(name) {
  // gMapGroup_Foo -> Foo
  if (name.startsWith("gMapGroup_")) {
    return name.slice(10).replace(/_/g, " ");
  }
  return name.replace(/_/g, " ");
}

function _formatMapName(name) {
  // CamelCase with numbers -> spaced: Route101 -> Route 101
  return name
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replace(/(\D)(\d)/g, "$1 $2");
}
