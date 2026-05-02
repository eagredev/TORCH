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
import { renderDataBeats } from "./views/viz/beatList.js";
import { openToolModal } from "./toolbar.js";

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
let _activeTab = "maps";    // "maps", "beats", "data", or "project"
let _scriptsMode = false;
let _beatTabEl = null;
let _dataTabEl = null;
let _mapsTabEl = null;
let _projectTabEl = null;
let _beatPanelHost = null;  // container for beat panel (sibling of _treeEl)
let _dataHost = null;       // container for data tab content
let _projectHost = null;    // container for project tab content

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initMapTree(container) {
  _container = container;

  // Header with tab bar + search
  const header = document.createElement("div");
  header.className = "ide-left-header";
  header.innerHTML = `
    <div class="ide-left-tabs-row">
      <div class="ide-left-tabs">
        <button class="ide-left-tab active" data-tab="maps">Maps</button>
        <button class="ide-left-tab" data-tab="beats" style="display:none">Beats</button>
        <button class="ide-left-tab" data-tab="data" style="display:none">Data</button>
        <button class="ide-left-tab" data-tab="project">Project</button>
      </div>
      <button class="ide-left-collapse" title="Collapse panel">\u203A</button>
    </div>
    <input type="text" class="ide-map-search" placeholder="Search maps..."
           id="ide-tree-search" autocomplete="off" spellcheck="false" />
  `;
  container.appendChild(header);

  header.querySelector(".ide-left-collapse").addEventListener("click", _toggleLeftCollapse);

  _mapsTabEl = header.querySelector('[data-tab="maps"]');
  _beatTabEl = header.querySelector('[data-tab="beats"]');
  _dataTabEl = header.querySelector('[data-tab="data"]');
  _projectTabEl = header.querySelector('[data-tab="project"]');
  _mapsTabEl.addEventListener("click", () => _switchTab("maps"));
  _beatTabEl.addEventListener("click", () => _switchTab("beats"));
  _dataTabEl.addEventListener("click", () => _switchTab("data"));
  _projectTabEl.addEventListener("click", () => _switchTab("project"));

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

  // Data panel host (hidden by default, shown in scripts mode)
  _dataHost = document.createElement("div");
  _dataHost.className = "ide-data-host";
  _dataHost.style.cssText = "display:none;flex:1;overflow-y:auto;padding:0.3rem;min-height:0;";
  container.appendChild(_dataHost);

  // Project panel host (hidden by default)
  _projectHost = document.createElement("div");
  _projectHost.className = "ide-project-host";
  _projectHost.style.cssText = "display:none;flex:1;overflow-y:auto;padding:0.5rem;";
  container.appendChild(_projectHost);

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
  _dataTabEl = null;
  _mapsTabEl = null;
  _projectTabEl = null;
  _beatPanelHost = null;
  _dataHost = null;
  _projectHost = null;
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
  if (_dataTabEl) _dataTabEl.classList.toggle("active", tab === "data");
  if (_projectTabEl) _projectTabEl.classList.toggle("active", tab === "project");

  // Hide all tab content
  if (_treeEl) _treeEl.style.display = "none";
  if (_searchEl) _searchEl.style.display = "none";
  if (_beatPanelHost) _beatPanelHost.style.display = "none";
  if (_dataHost) _dataHost.style.display = "none";
  if (_projectHost) _projectHost.style.display = "none";
  cleanupBeatPanel();

  if (tab === "maps") {
    if (_treeEl) _treeEl.style.display = "";
    if (_searchEl) _searchEl.style.display = "";
  } else if (tab === "beats") {
    if (_beatPanelHost) {
      _beatPanelHost.style.display = "flex";
      initBeatPanel(_beatPanelHost);
    }
  } else if (tab === "data") {
    if (_dataHost) {
      _dataHost.style.display = "";
      _renderDataTab();
    }
  } else if (tab === "project") {
    if (_projectHost) {
      _projectHost.style.display = "";
      _renderProjectTab();
    }
  }
}

function _onModeChanged(detail) {
  _scriptsMode = detail.mode === "scripts";
  if (_beatTabEl) _beatTabEl.style.display = _scriptsMode ? "" : "none";
  if (_dataTabEl) _dataTabEl.style.display = _scriptsMode ? "" : "none";
  if (!_scriptsMode && (_activeTab === "beats" || _activeTab === "data")) {
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
  if (btn) btn.textContent = collapsed ? "\u2039" : "\u203A";
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

  // Persist selection + track recent maps
  try { localStorage.setItem("torch-ide-last-map", mapName); } catch (_) {}
  _trackRecentMap(mapName);

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

// ---------------------------------------------------------------------------
// Data tab rendering
// ---------------------------------------------------------------------------

function _renderDataTab() {
  if (!_dataHost) return;
  renderDataBeats(_dataHost);
}

// Project tab rendering
// ---------------------------------------------------------------------------

async function _renderProjectTab() {
  if (!_projectHost) return;

  _projectHost.innerHTML = `<div style="color:var(--text-dim);font-size:0.8rem">Loading...</div>`;

  let status = null;
  try {
    const res = await api("/status");
    if (res.ok) status = res.data;
  } catch (_) {}

  // Recent maps from localStorage
  const recentMaps = _getRecentMaps();

  let html = `<div class="ide-project-tab">`;

  // --- Project info ---
  html += `<div class="ide-project-section">`;
  html += `<h4 class="ide-project-heading">Project</h4>`;
  if (status) {
    html += `<div class="ide-project-stat"><span class="ide-project-label">Name</span><span class="ide-project-value">${esc(status.project_name || "—")}</span></div>`;
    html += `<div class="ide-project-stat"><span class="ide-project-label">TORCH</span><span class="ide-project-value">v${esc(status.torch_version || "?")}</span></div>`;
    if (status.expansion_version && status.expansion_version !== "N/A") {
      html += `<div class="ide-project-stat"><span class="ide-project-label">Expansion</span><span class="ide-project-value">v${esc(status.expansion_version)}</span></div>`;
    }
    if (status.enrolled_map_count != null) {
      html += `<div class="ide-project-stat"><span class="ide-project-label">Maps</span><span class="ide-project-value">${status.enrolled_map_count} enrolled</span></div>`;
    }
    if (status.custom_map_count) {
      html += `<div class="ide-project-stat"><span class="ide-project-label">Custom</span><span class="ide-project-value">${status.custom_map_count} maps</span></div>`;
    }
  } else {
    html += `<div class="ide-project-stat" style="color:var(--text-dim)">Could not load project info</div>`;
  }
  html += `</div>`;

  // --- Map health ---
  if (status && status.map_health && Object.keys(status.map_health).length > 0) {
    const h = status.map_health;
    html += `<div class="ide-project-section">`;
    html += `<h4 class="ide-project-heading">Health</h4>`;
    const badges = [];
    if (h.ok) badges.push(`<span class="ide-health-badge ok">${h.ok} ok</span>`);
    if (h.stale) badges.push(`<span class="ide-health-badge stale">${h.stale} stale</span>`);
    if (h.drift) badges.push(`<span class="ide-health-badge drift">${h.drift} drift</span>`);
    if (h.orphan) badges.push(`<span class="ide-health-badge orphan">${h.orphan} orphan</span>`);
    if (h["new"]) badges.push(`<span class="ide-health-badge new">${h["new"]} new</span>`);
    if (h.missing_workspace) badges.push(`<span class="ide-health-badge orphan">${h.missing_workspace} missing</span>`);
    html += `<div class="ide-health-row">${badges.join("")}</div>`;
    html += `</div>`;
  }

  // --- Recent maps ---
  if (recentMaps.length > 0) {
    html += `<div class="ide-project-section">`;
    html += `<h4 class="ide-project-heading">Recent Maps</h4>`;
    for (const m of recentMaps) {
      html += `<div class="ide-project-recent" data-map="${esc(m)}">${esc(_formatMapName(m))}</div>`;
    }
    html += `</div>`;
  }

  // --- Quick links ---
  html += `<div class="ide-project-section">`;
  html += `<h4 class="ide-project-heading">Quick Links</h4>`;
  html += `<div class="ide-project-link" data-tool="settings">Settings</div>`;
  html += `<div class="ide-project-link" data-tool="project">Project Config</div>`;
  html += `<div class="ide-project-link" data-tool="scorch">SCORCH</div>`;
  html += `<div class="ide-project-link" data-tool="assets">Asset Browser</div>`;
  html += `<div class="ide-project-link" data-tool="explorer">Map Graph</div>`;
  html += `</div>`;

  html += `</div>`;
  _projectHost.innerHTML = html;

  // Wire recent map clicks
  _projectHost.querySelectorAll(".ide-project-recent").forEach(el => {
    el.addEventListener("click", () => {
      const mapName = el.dataset.map;
      _selectedMap = mapName;
      _switchTab("maps");
      _renderTree();
      ideEmit(IDE_MAP_SELECTED, { name: mapName, source: "project" });
    });
  });

  // Wire quick links
  const toolMap = {
    settings: ["Settings", () => import("./views/settings.js")],
    project: ["Project", () => import("./views/project.js")],
    scorch: ["SCORCH", () => import("./views/scorch.js")],
    assets: ["Assets", () => import("./views/assets.js")],
    explorer: ["Map Graph", () => import("./views/explorer.js")],
  };
  _projectHost.querySelectorAll(".ide-project-link").forEach(el => {
    el.addEventListener("click", () => {
      const entry = toolMap[el.dataset.tool];
      if (entry) openToolModal(entry[0], entry[1]);
    });
  });
}

function _getRecentMaps() {
  // Track recent maps by storing the last 8 unique selections
  try {
    const raw = localStorage.getItem("torch-ide-recent-maps");
    return raw ? JSON.parse(raw).slice(0, 8) : [];
  } catch (_) { return []; }
}

function _trackRecentMap(mapName) {
  try {
    let recent = _getRecentMaps().filter(m => m !== mapName);
    recent.unshift(mapName);
    if (recent.length > 8) recent = recent.slice(0, 8);
    localStorage.setItem("torch-ide-recent-maps", JSON.stringify(recent));
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

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
