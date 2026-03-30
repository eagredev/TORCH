/**
 * TORCH Web GUI — Stamp Library view.
 * TORCH_MODULE
 *
 * Browse, create, place, and delete custom stamps. Also shows built-in
 * templates. Works as a standalone route (/stamp-library) and as a
 * Studio modal via openToolModal().
 */

import { api, postApi, deleteApi } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let styleEl = null;
let _container = null;
let _state = "grid";          // "grid" | "create" | "place"
let _stamps = [];             // combined list (built-in + custom)
let _builtinTemplates = [];   // from /api/templates
let _customStamps = [];       // from /api/stamps
let _sourceMaps = [];
let _sourceWarps = [];
let _selectedStamp = null;    // stamp object for place flow
let _searchQuery = "";
let _writeLock = false;
let _previewResult = null;
let _previewLoading = false;
let _previewTimer = null;
let _stampResult = null;
let _createResult = null;

// Create wizard state
let _createStep = 0;          // 0-3
let _createSourceMap = "";
let _createWarps = [];        // warp objects for selected source
let _createExitIndices = [];  // checked exit warp indices
let _createName = "";
let _createDesc = "";
let _createTags = "";
let _createIncludeScripts = false;

// Place form state
let _placeParentMap = "";
let _placeDoorX = 0;
let _placeDoorY = 0;
let _placeMapName = "";
let _placeMapGroup = "";
let _parentMaps = [];
let _mapGroups = [];

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

const STYLES = `
/* Stamp Library layout */
.sl-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 1rem; flex-wrap: wrap; gap: 0.75rem;
}
.sl-header h2 {
  margin: 0; color: var(--text-primary, #cdd6f4); font-size: 1.2rem;
}
.sl-header-actions {
  display: flex; gap: 0.5rem; align-items: center;
}
.sl-search {
  padding: 0.45rem 0.7rem; min-width: 200px;
  background: var(--surface-1, #181825);
  color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border-subtle, #313244);
  border-radius: 6px; font-size: 0.85rem;
}
.sl-search:focus {
  outline: none; border-color: var(--accent, #cba6f7);
}

/* Card grid */
.sl-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem; padding: 0.5rem 0;
}
.sl-card {
  background: var(--surface-2, #1e1e2e);
  border: 1px solid var(--border-subtle, #313244);
  border-radius: 10px; padding: 1.25rem;
  display: flex; flex-direction: column; gap: 0.6rem;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.sl-card:hover {
  border-color: var(--accent, #cba6f7);
  box-shadow: 0 0 0 1px var(--accent, #cba6f7);
}
.sl-card-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 0.5rem;
}
.sl-card-name {
  font-size: 1rem; font-weight: 600;
  color: var(--text-primary, #cdd6f4);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sl-badge {
  display: inline-block; padding: 0.1rem 0.45rem;
  border-radius: 4px; font-size: 0.7rem; font-weight: 600;
  white-space: nowrap;
}
.sl-badge-builtin {
  background: rgba(137,180,250,0.15); color: #89b4fa;
}
.sl-badge-custom {
  background: rgba(166,227,161,0.15); color: #a6e3a1;
}
.sl-card-meta {
  font-size: 0.8rem; color: var(--text-dim, #6c7086);
  line-height: 1.4;
}
.sl-card-tags {
  display: flex; flex-wrap: wrap; gap: 0.3rem;
}
.sl-tag {
  display: inline-block; padding: 0.1rem 0.4rem;
  background: rgba(255,255,255,0.05);
  border-radius: 4px; font-size: 0.72rem;
  color: var(--text-dim, #6c7086);
}
.sl-card-actions {
  margin-top: auto; display: flex; gap: 0.5rem; padding-top: 0.4rem;
}
.sl-card-desc {
  font-size: 0.8rem; color: var(--text-dim, #6c7086);
  line-height: 1.4;
}
.sl-empty {
  color: var(--text-dim, #6c7086); font-size: 0.9rem;
  padding: 2rem 0; text-align: center;
}

/* Buttons */
.sl-btn {
  padding: 0.45rem 0.9rem; border-radius: 6px; font-size: 0.82rem;
  font-weight: 500; cursor: pointer; border: none;
  transition: opacity 0.15s;
}
.sl-btn:hover { opacity: 0.9; }
.sl-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.sl-btn-primary {
  background: var(--accent, #cba6f7); color: #111;
}
.sl-btn-secondary {
  background: var(--surface-2, #1e1e2e);
  color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border-subtle, #313244);
}
.sl-btn-danger {
  background: rgba(243,139,168,0.15); color: #f38ba8;
  border: 1px solid rgba(243,139,168,0.3);
}
.sl-btn-sm {
  padding: 0.3rem 0.6rem; font-size: 0.78rem;
}

/* Wizard / form layout */
.sl-wizard {
  max-width: 680px;
}
.sl-wizard-title {
  font-size: 1.1rem; font-weight: 600;
  color: var(--text-primary, #cdd6f4);
  margin-bottom: 0.75rem;
}
.sl-wizard-step {
  font-size: 0.78rem; color: var(--text-dim, #6c7086);
  margin-bottom: 1rem;
}
.sl-field {
  margin-bottom: 1rem;
}
.sl-field label {
  display: block; font-size: 0.8rem; font-weight: 500;
  color: var(--text-dim, #6c7086);
  margin-bottom: 0.3rem;
}
.sl-field select,
.sl-field input[type="number"],
.sl-field input[type="text"],
.sl-field textarea {
  width: 100%; padding: 0.5rem 0.6rem;
  background: var(--surface-1, #181825);
  color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border-subtle, #313244);
  border-radius: 6px; font-size: 0.85rem;
  font-family: inherit;
}
.sl-field select:focus,
.sl-field input:focus,
.sl-field textarea:focus {
  outline: none; border-color: var(--accent, #cba6f7);
}
.sl-field-hint {
  font-size: 0.73rem; color: var(--text-dim, #6c7086);
  margin-top: 0.2rem;
}
.sl-coords {
  display: flex; gap: 1rem;
}
.sl-coords .sl-field { flex: 1; }
.sl-checkbox {
  display: flex; align-items: center; gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.sl-checkbox input { width: auto; }
.sl-checkbox label { margin-bottom: 0; font-size: 0.82rem; }

/* Warp list */
.sl-warp-list {
  list-style: none; padding: 0; margin: 0;
  max-height: 240px; overflow-y: auto;
  border: 1px solid var(--border-subtle, #313244);
  border-radius: 6px; background: var(--surface-1, #181825);
}
.sl-warp-item {
  padding: 0.4rem 0.6rem; display: flex; align-items: center; gap: 0.5rem;
  font-size: 0.82rem; color: var(--text-primary, #cdd6f4);
  border-bottom: 1px solid var(--border-subtle, #313244);
}
.sl-warp-item:last-child { border-bottom: none; }
.sl-warp-item input { width: auto; }
.sl-warp-dest {
  color: var(--text-dim, #6c7086); font-size: 0.75rem;
}

/* Preview panel */
.sl-preview {
  background: var(--surface-1, #181825);
  border: 1px solid var(--border-subtle, #313244);
  border-radius: 8px; padding: 1rem;
  margin-bottom: 1rem; font-size: 0.8rem;
}
.sl-preview-title {
  font-weight: 600; color: var(--text-primary, #cdd6f4);
  margin-bottom: 0.5rem;
}
.sl-preview-item {
  padding: 0.2rem 0; display: flex; align-items: center; gap: 0.4rem;
}
.sl-preview-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
}
.sl-dot-green { background: #a6e3a1; }
.sl-dot-yellow { background: #f9e2af; }
.sl-dot-blue { background: #89b4fa; }
.sl-preview-error { color: #f38ba8; }
.sl-preview-warning { color: #fab387; }
.sl-preview-loading { color: var(--text-dim, #6c7086); font-style: italic; }

/* Result panel */
.sl-result {
  border-radius: 8px; padding: 1rem; margin-bottom: 1rem;
  font-size: 0.85rem;
}
.sl-result.success {
  background: rgba(166,227,161,0.1);
  border: 1px solid rgba(166,227,161,0.3);
  color: #a6e3a1;
}
.sl-result.failure {
  background: rgba(243,139,168,0.1);
  border: 1px solid rgba(243,139,168,0.3);
  color: #f38ba8;
}

/* Actions row */
.sl-actions {
  display: flex; gap: 0.75rem; margin-top: 1rem;
}

/* Loading spinner */
.sl-spinner {
  color: var(--text-dim, #6c7086); font-style: italic;
  padding: 2rem; text-align: center;
}

/* Info expand */
.sl-info-panel {
  margin-top: 0.5rem; padding: 0.6rem;
  background: var(--surface-1, #181825);
  border-radius: 6px; font-size: 0.78rem;
  color: var(--text-dim, #6c7086); line-height: 1.5;
  display: none;
}
.sl-info-panel.open { display: block; }
`;

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadStamps() {
  _customStamps = [];
  _builtinTemplates = [];

  const [customRes, builtinRes] = await Promise.all([
    api("/stamps"),
    api("/templates"),
  ]);

  if (customRes.ok) {
    _customStamps = (customRes.data.stamps || []).map(s => ({
      ...s,
      _type: "custom",
    }));
  }
  if (builtinRes.ok) {
    _builtinTemplates = (builtinRes.data.templates || []).map(t => ({
      id: t.id,
      name: t.name,
      description: t.description || "",
      width: null,
      height: null,
      tags: t.includes || [],
      created_from: "",
      _type: "builtin",
      _templateData: t,
    }));
  }

  _stamps = [..._builtinTemplates, ..._customStamps];
}

async function loadSourceMaps() {
  const res = await api("/stamps/source-maps");
  if (res.ok) _sourceMaps = res.data.maps || [];
}

async function loadSourceWarps(mapName) {
  _sourceWarps = [];
  if (!mapName) return;
  const res = await api(`/stamps/source-map/${encodeURIComponent(mapName)}/warps`);
  if (res.ok) _sourceWarps = res.data.warps || [];
}

async function loadParentMaps() {
  const res = await api("/templates/maps");
  if (res.ok) _parentMaps = res.data.maps || [];
}

async function loadMapGroups() {
  const res = await api("/templates/groups");
  if (res.ok) _mapGroups = res.data.groups || [];
}

// ---------------------------------------------------------------------------
// Filtered stamps
// ---------------------------------------------------------------------------

function filteredStamps() {
  if (!_searchQuery) return _stamps;
  const q = _searchQuery.toLowerCase();
  return _stamps.filter(s => {
    if (s.name.toLowerCase().includes(q)) return true;
    if ((s.description || "").toLowerCase().includes(q)) return true;
    if ((s.tags || []).some(t => t.toLowerCase().includes(q))) return true;
    if ((s.created_from || "").toLowerCase().includes(q)) return true;
    return false;
  });
}

// ---------------------------------------------------------------------------
// Render: Library Grid
// ---------------------------------------------------------------------------

function renderGrid() {
  let html = renderStudioNavbar("Stamp Library");
  html += `<div class="sl-header">`;
  html += `<h2>Stamp Library</h2>`;
  html += `<div class="sl-header-actions">`;
  html += `<input type="text" class="sl-search" id="sl-search" placeholder="Search stamps..." value="${esc(_searchQuery)}">`;
  html += `<button class="sl-btn sl-btn-primary" id="sl-create-btn">+ Create Stamp</button>`;
  html += `</div></div>`;

  const visible = filteredStamps();
  if (visible.length === 0) {
    if (_stamps.length === 0) {
      html += `<div class="sl-empty">No stamps yet. Create one from an existing map, or use a built-in template from the Templates view.</div>`;
    } else {
      html += `<div class="sl-empty">No stamps match your search.</div>`;
    }
    return html;
  }

  html += `<div class="sl-grid">`;
  for (const stamp of visible) {
    const isBuiltin = stamp._type === "builtin";
    const badgeClass = isBuiltin ? "sl-badge-builtin" : "sl-badge-custom";
    const badgeLabel = isBuiltin ? "Built-in" : "Custom";

    const dims = (stamp.width && stamp.height)
      ? `${stamp.width}\u00d7${stamp.height}`
      : "";
    const source = stamp.created_from ? `From: ${esc(stamp.created_from)}` : "";
    const metaParts = [dims, source].filter(Boolean);

    html += `<div class="sl-card" data-stamp-id="${esc(stamp.id)}" data-stamp-type="${esc(stamp._type)}">`;
    html += `<div class="sl-card-header">`;
    html += `<span class="sl-card-name">${esc(stamp.name)}</span>`;
    html += `<span class="sl-badge ${badgeClass}">${badgeLabel}</span>`;
    html += `</div>`;

    if (stamp.description) {
      html += `<div class="sl-card-desc">${esc(stamp.description)}</div>`;
    }

    if (metaParts.length > 0) {
      html += `<div class="sl-card-meta">${metaParts.map(p => esc(p)).join(" &middot; ")}</div>`;
    }

    if (stamp.tags && stamp.tags.length > 0) {
      html += `<div class="sl-card-tags">`;
      for (const tag of stamp.tags) {
        html += `<span class="sl-tag">${esc(tag)}</span>`;
      }
      html += `</div>`;
    }

    html += `<div class="sl-card-actions">`;
    if (isBuiltin) {
      html += `<button class="sl-btn sl-btn-primary sl-btn-sm sl-action-place-builtin" data-template="${esc(stamp.id)}">Stamp</button>`;
      html += `<button class="sl-btn sl-btn-secondary sl-btn-sm sl-action-info" data-stamp-id="${esc(stamp.id)}">Info</button>`;
    } else {
      html += `<button class="sl-btn sl-btn-primary sl-btn-sm sl-action-place" data-stamp-id="${esc(stamp.id)}">Place</button>`;
      html += `<button class="sl-btn sl-btn-secondary sl-btn-sm sl-action-info" data-stamp-id="${esc(stamp.id)}">Info</button>`;
      html += `<button class="sl-btn sl-btn-danger sl-btn-sm sl-action-delete" data-stamp-id="${esc(stamp.id)}">Delete</button>`;
    }
    html += `</div>`;

    // Info panel (hidden until toggled)
    html += `<div class="sl-info-panel" id="sl-info-${esc(stamp.id)}"></div>`;

    html += `</div>`;
  }
  html += `</div>`;
  return html;
}

// ---------------------------------------------------------------------------
// Render: Create Wizard
// ---------------------------------------------------------------------------

function renderCreateWizard() {
  let html = renderStudioNavbar("Stamp Library");
  html += `<div class="sl-wizard">`;
  html += `<div class="sl-wizard-title">Create Custom Stamp</div>`;
  html += `<div class="sl-wizard-step">Step ${_createStep + 1} of 4</div>`;

  if (_createStep === 0) {
    html += renderCreateStep0();
  } else if (_createStep === 1) {
    html += renderCreateStep1();
  } else if (_createStep === 2) {
    html += renderCreateStep2();
  } else if (_createStep === 3) {
    html += renderCreateStep3();
  }

  html += `</div>`;
  return html;
}

function renderCreateStep0() {
  // Step 1: Select source map
  let html = `<div class="sl-field">`;
  html += `<label>Source Map</label>`;
  html += `<select id="sl-create-source">`;
  html += `<option value="">-- Select a map --</option>`;
  for (const m of _sourceMaps) {
    const dims = (m.width && m.height) ? ` (${m.width}\u00d7${m.height})` : "";
    const sel = m.name === _createSourceMap ? " selected" : "";
    html += `<option value="${esc(m.name)}"${sel}>${esc(m.name)}${dims} - ${m.warp_count} warp${m.warp_count !== 1 ? "s" : ""}, ${m.object_count} obj</option>`;
  }
  html += `</select>`;
  html += `<div class="sl-field-hint">Choose an existing interior map to capture as a reusable stamp.</div>`;
  html += `</div>`;

  html += `<div class="sl-actions">`;
  html += `<button class="sl-btn sl-btn-secondary" id="sl-create-cancel">Cancel</button>`;
  html += `<button class="sl-btn sl-btn-primary" id="sl-create-next" ${_createSourceMap ? "" : "disabled"}>Next</button>`;
  html += `</div>`;
  return html;
}

function renderCreateStep1() {
  // Step 2: Mark exit warps
  let html = `<div class="sl-field">`;
  html += `<label>Exit Warps</label>`;
  html += `<div class="sl-field-hint" style="margin-bottom:0.5rem">Check the warps that lead outside (exit doors). These will be linked to the parent map when the stamp is placed.</div>`;

  if (_createWarps.length === 0) {
    html += `<div class="sl-empty" style="padding:1rem">No warps found on this map.</div>`;
  } else {
    html += `<ul class="sl-warp-list">`;
    for (const w of _createWarps) {
      const checked = _createExitIndices.includes(w.index) ? " checked" : "";
      const dest = w.dest_map ? `\u2192 ${w.dest_map}` : "";
      html += `<li class="sl-warp-item">`;
      html += `<input type="checkbox" class="sl-warp-check" data-index="${w.index}"${checked}>`;
      html += `<span>Warp ${w.index} (${w.x}, ${w.y})</span>`;
      if (dest) html += `<span class="sl-warp-dest">${esc(dest)}</span>`;
      html += `</li>`;
    }
    html += `</ul>`;
  }
  html += `</div>`;

  html += `<div class="sl-actions">`;
  html += `<button class="sl-btn sl-btn-secondary" id="sl-create-back">Back</button>`;
  html += `<button class="sl-btn sl-btn-primary" id="sl-create-next" ${_createExitIndices.length > 0 ? "" : "disabled"}>Next</button>`;
  html += `</div>`;
  return html;
}

function renderCreateStep2() {
  // Step 3: Name and configure
  let html = `<div class="sl-field">`;
  html += `<label>Stamp Name</label>`;
  html += `<input type="text" id="sl-create-name" value="${esc(_createName)}" placeholder="e.g. Generic House (Small)">`;
  html += `</div>`;

  html += `<div class="sl-field">`;
  html += `<label>Description (optional)</label>`;
  html += `<textarea id="sl-create-desc" rows="2" placeholder="Brief description of this stamp...">${esc(_createDesc)}</textarea>`;
  html += `</div>`;

  html += `<div class="sl-field">`;
  html += `<label>Tags (comma-separated)</label>`;
  html += `<input type="text" id="sl-create-tags" value="${esc(_createTags)}" placeholder="e.g. house, residential, small">`;
  html += `<div class="sl-field-hint">Tags help filter stamps in the library.</div>`;
  html += `</div>`;

  html += `<div class="sl-checkbox">`;
  html += `<input type="checkbox" id="sl-create-scripts" ${_createIncludeScripts ? "checked" : ""}>`;
  html += `<label for="sl-create-scripts">Include scripts from source map</label>`;
  html += `</div>`;

  html += `<div class="sl-actions">`;
  html += `<button class="sl-btn sl-btn-secondary" id="sl-create-back">Back</button>`;
  html += `<button class="sl-btn sl-btn-primary" id="sl-create-next" ${_createName.trim() ? "" : "disabled"}>Next</button>`;
  html += `</div>`;
  return html;
}

function renderCreateStep3() {
  // Step 4: Confirm and create
  const tagList = _createTags ? _createTags.split(",").map(t => t.trim()).filter(Boolean) : [];

  let html = `<div class="sl-preview">`;
  html += `<div class="sl-preview-title">Summary</div>`;
  html += `<div class="sl-preview-item"><strong>Source:</strong>&nbsp;${esc(_createSourceMap)}</div>`;
  html += `<div class="sl-preview-item"><strong>Name:</strong>&nbsp;${esc(_createName)}</div>`;
  if (_createDesc) {
    html += `<div class="sl-preview-item"><strong>Description:</strong>&nbsp;${esc(_createDesc)}</div>`;
  }
  html += `<div class="sl-preview-item"><strong>Exit warps:</strong>&nbsp;${_createExitIndices.join(", ")}</div>`;
  if (tagList.length > 0) {
    html += `<div class="sl-preview-item"><strong>Tags:</strong>&nbsp;${tagList.map(t => esc(t)).join(", ")}</div>`;
  }
  html += `<div class="sl-preview-item"><strong>Include scripts:</strong>&nbsp;${_createIncludeScripts ? "Yes" : "No"}</div>`;
  html += `</div>`;

  // Result
  if (_createResult) {
    if (_createResult.success) {
      html += `<div class="sl-result success"><strong>Stamp created!</strong> ${esc(_createResult.stamp ? _createResult.stamp.name : _createName)}</div>`;
    } else {
      html += `<div class="sl-result failure"><strong>Failed:</strong> ${esc(_createResult.error || "Unknown error")}</div>`;
    }
  }

  html += `<div class="sl-actions">`;
  html += `<button class="sl-btn sl-btn-secondary" id="sl-create-back" ${_createResult ? "style=\"display:none\"" : ""}>Back</button>`;
  if (_createResult && _createResult.success) {
    html += `<button class="sl-btn sl-btn-primary" id="sl-create-done">Back to Library</button>`;
  } else {
    html += `<button class="sl-btn sl-btn-primary" id="sl-create-submit" ${_writeLock ? "disabled" : ""}>${_writeLock ? "Creating..." : "Create Stamp"}</button>`;
  }
  html += `</div>`;
  return html;
}

// ---------------------------------------------------------------------------
// Render: Place Form (inline, for standalone route)
// ---------------------------------------------------------------------------

function renderPlaceForm() {
  if (!_selectedStamp) return "";

  const isBuiltin = _selectedStamp._type === "builtin";
  let html = renderStudioNavbar("Stamp Library");
  html += `<div class="sl-wizard">`;
  html += `<div class="sl-wizard-title">Place: ${esc(_selectedStamp.name)}</div>`;

  if (isBuiltin) {
    // For built-in templates, redirect to the templates view
    html += `<p style="color:var(--text-dim,#6c7086);font-size:0.85rem;margin-bottom:1rem">`;
    html += `Built-in templates use the Templates wizard for placement.</p>`;
    html += `<div class="sl-actions">`;
    html += `<button class="sl-btn sl-btn-secondary" id="sl-place-back">Back</button>`;
    html += `<a href="#/templates" class="sl-btn sl-btn-primary" style="text-decoration:none;display:inline-block">Open Templates</a>`;
    html += `</div></div>`;
    return html;
  }

  // Parent map
  html += `<div class="sl-field">`;
  html += `<label>Parent Map (door location)</label>`;
  html += `<select id="sl-place-parent">`;
  html += `<option value="">-- Select a map --</option>`;
  for (const m of _parentMaps) {
    const dims = (m.width && m.height) ? ` ${m.width}\u00d7${m.height}` : "";
    const typeStr = (m.map_type || "").replace("MAP_TYPE_", "");
    const sel = m.name === _placeParentMap ? " selected" : "";
    html += `<option value="${esc(m.name)}"${sel}>${esc(m.name)} (${esc(typeStr)}${dims})</option>`;
  }
  html += `</select></div>`;

  // Door coordinates
  html += `<div class="sl-coords">`;
  html += `<div class="sl-field">`;
  html += `<label>Door X</label>`;
  html += `<input type="number" id="sl-place-dx" min="0" value="${_placeDoorX}">`;
  html += `</div>`;
  html += `<div class="sl-field">`;
  html += `<label>Door Y</label>`;
  html += `<input type="number" id="sl-place-dy" min="0" value="${_placeDoorY}">`;
  html += `</div></div>`;

  // Optional map name
  html += `<div class="sl-field">`;
  html += `<label>Map Name (optional override)</label>`;
  html += `<input type="text" id="sl-place-name" value="${esc(_placeMapName)}" placeholder="Auto-generated if empty">`;
  html += `</div>`;

  // Map group
  html += `<div class="sl-field">`;
  html += `<label>Map Group</label>`;
  html += `<select id="sl-place-group">`;
  html += `<option value="">-- Auto (same as parent) --</option>`;
  for (const g of _mapGroups) {
    const sel = g === _placeMapGroup ? " selected" : "";
    html += `<option value="${esc(g)}"${sel}>${esc(g)}</option>`;
  }
  html += `</select></div>`;

  // Preview
  html += `<div class="sl-preview" id="sl-preview">`;
  html += `<div class="sl-preview-title">Preview</div>`;
  html += `<div class="sl-preview-loading">Fill in parent map and door coordinates to see preview...</div>`;
  html += `</div>`;

  // Stamp result
  if (_stampResult) {
    if (_stampResult.success) {
      const mapsCreated = (_stampResult.maps_created || []).map(m => esc(m)).join(", ");
      html += `<div class="sl-result success">`;
      html += `<strong>Placement complete!</strong><br>`;
      if (mapsCreated) html += `Created: ${mapsCreated}<br>`;
      html += `Files created: ${(_stampResult.created_files || []).length}<br>`;
      html += `Files modified: ${(_stampResult.modified_files || []).length}`;
      if ((_stampResult.warnings || []).length > 0) {
        html += `<div style="color:#fab387;margin-top:0.4rem">Warnings: ${_stampResult.warnings.map(w => esc(w)).join("; ")}</div>`;
      }
      html += `</div>`;
    } else {
      html += `<div class="sl-result failure"><strong>Placement failed:</strong> ${esc(_stampResult.error || "Unknown error")}</div>`;
    }
  }

  // Buttons
  const canPlace = _previewResult && _previewResult.valid && !_writeLock && !_stampResult;
  html += `<div class="sl-actions">`;
  html += `<button class="sl-btn sl-btn-secondary" id="sl-place-back">Back</button>`;
  html += `<button class="sl-btn sl-btn-primary" id="sl-place-submit" ${canPlace ? "" : "disabled"}>${_writeLock ? "Placing..." : "Place Stamp"}</button>`;
  html += `</div>`;

  html += `</div>`;
  return html;
}

// ---------------------------------------------------------------------------
// Preview (placement)
// ---------------------------------------------------------------------------

function schedulePreview() {
  if (_previewTimer) clearTimeout(_previewTimer);
  _previewTimer = setTimeout(doPreview, 400);
}

async function doPreview() {
  if (!_container || !_selectedStamp) return;
  const parent = (_container.querySelector("#sl-place-parent") || {}).value || "";
  const doorX = (_container.querySelector("#sl-place-dx") || {}).value || "";
  const doorY = (_container.querySelector("#sl-place-dy") || {}).value || "";

  if (!parent || doorX === "" || doorY === "") {
    _previewResult = null;
    renderPreviewPanel();
    return;
  }

  _previewLoading = true;
  renderPreviewPanel();

  const mapName = (_container.querySelector("#sl-place-name") || {}).value || "";
  let qs = `?stamp_id=${encodeURIComponent(_selectedStamp.id)}`;
  qs += `&parent_map=${encodeURIComponent(parent)}`;
  qs += `&door_x=${encodeURIComponent(doorX)}`;
  qs += `&door_y=${encodeURIComponent(doorY)}`;
  if (mapName) qs += `&map_name=${encodeURIComponent(mapName)}`;

  const res = await api(`/stamps/preview${qs}`);
  _previewLoading = false;
  if (res.ok) {
    _previewResult = res.data;
  } else {
    _previewResult = { valid: false, errors: [res.error || "Preview failed"], warnings: [], preview: {} };
  }
  renderPreviewPanel();
}

function renderPreviewPanel() {
  const el = _container && _container.querySelector("#sl-preview");
  if (!el) return;

  let html = `<div class="sl-preview-title">Preview</div>`;
  if (_previewLoading) {
    html += `<div class="sl-preview-loading">Validating...</div>`;
  } else if (!_previewResult) {
    html += `<div class="sl-preview-loading">Fill in parent map and door coordinates to see preview...</div>`;
  } else {
    for (const err of (_previewResult.errors || [])) {
      html += `<div class="sl-preview-item sl-preview-error">\u2716 ${esc(err)}</div>`;
    }
    for (const warn of (_previewResult.warnings || [])) {
      html += `<div class="sl-preview-item sl-preview-warning">\u26A0 ${esc(warn)}</div>`;
    }
    const p = _previewResult.preview || {};
    for (const m of (p.maps_to_create || [])) {
      html += `<div class="sl-preview-item"><span class="sl-preview-dot sl-dot-green"></span> Create: ${esc(m)}</div>`;
    }
    for (const f of (p.files_to_create || [])) {
      html += `<div class="sl-preview-item"><span class="sl-preview-dot sl-dot-green"></span> ${esc(f)}</div>`;
    }
    for (const f of (p.files_to_modify || [])) {
      html += `<div class="sl-preview-item"><span class="sl-preview-dot sl-dot-yellow"></span> ${esc(f)}</div>`;
    }
  }
  el.innerHTML = html;

  // Update place button state
  const btn = _container && _container.querySelector("#sl-place-submit");
  if (btn) {
    btn.disabled = !(_previewResult && _previewResult.valid && !_writeLock && !_stampResult);
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function doPlace() {
  if (_writeLock || !_container || !_selectedStamp) return;
  _writeLock = true;
  renderPreviewPanel();

  const parent = (_container.querySelector("#sl-place-parent") || {}).value || "";
  const doorX = parseInt((_container.querySelector("#sl-place-dx") || {}).value, 10);
  const doorY = parseInt((_container.querySelector("#sl-place-dy") || {}).value, 10);
  const mapName = (_container.querySelector("#sl-place-name") || {}).value || "";
  const mapGroup = (_container.querySelector("#sl-place-group") || {}).value || "";

  const body = {
    stamp_id: _selectedStamp.id,
    parent_map: parent,
    door_x: doorX,
    door_y: doorY,
  };
  if (mapName) body.map_name = mapName;
  if (mapGroup) body.map_group = mapGroup;

  const res = await postApi("/stamps/place", body);
  _writeLock = false;

  if (res.ok) {
    _stampResult = res.data;
  } else {
    _stampResult = { success: false, error: res.error || "Placement failed" };
  }
  _container.innerHTML = renderPlaceForm();
  bindPlaceEvents();
  renderPreviewPanel();
}

async function doCreateStamp() {
  if (_writeLock) return;
  _writeLock = true;
  rerenderState();

  const tagList = _createTags ? _createTags.split(",").map(t => t.trim()).filter(Boolean) : [];

  const body = {
    source_map: _createSourceMap,
    name: _createName,
    exit_warp_indices: _createExitIndices,
    include_scripts: _createIncludeScripts,
    description: _createDesc,
    tags: tagList.length > 0 ? tagList : undefined,
  };

  const res = await postApi("/stamps/create", body);
  _writeLock = false;

  if (res.ok) {
    _createResult = res.data;
  } else {
    _createResult = { success: false, error: res.error || "Creation failed" };
  }
  rerenderState();
}

async function doDelete(stampId) {
  if (!confirm("Delete this custom stamp? This cannot be undone.")) return;
  const res = await deleteApi(`/stamps/${encodeURIComponent(stampId)}`);
  if (res.ok) {
    // Refresh list
    await loadStamps();
    rerenderState();
  } else {
    alert("Delete failed: " + (res.error || "Unknown error"));
  }
}

async function doShowInfo(stampId) {
  const panel = _container && _container.querySelector(`#sl-info-${CSS.escape(stampId)}`);
  if (!panel) return;

  if (panel.classList.contains("open")) {
    panel.classList.remove("open");
    return;
  }

  // Fetch full manifest for custom stamps
  const stamp = _stamps.find(s => s.id === stampId);
  if (!stamp) return;

  if (stamp._type === "builtin") {
    const t = stamp._templateData;
    panel.innerHTML = `
      <div><strong>Type:</strong> Built-in Template</div>
      <div><strong>Includes:</strong> ${(t.includes || []).map(s => esc(s)).join(", ") || "N/A"}</div>
      ${t.creates_heal_location ? "<div><strong>Creates heal location</strong></div>" : ""}
    `;
  } else {
    panel.textContent = "Loading...";
    const res = await api(`/stamps/${encodeURIComponent(stampId)}`);
    if (res.ok) {
      const data = res.data;
      const exitWarps = (data.exit_warps || []).map(w => `warp ${w.index} (${w.x},${w.y})`).join(", ");
      panel.innerHTML = `
        <div><strong>Source map:</strong> ${esc(data.created_from || "")}</div>
        <div><strong>Size:</strong> ${data.width || "?"}\u00d7${data.height || "?"}</div>
        <div><strong>Tileset:</strong> ${esc(data.primary_tileset || "")} / ${esc(data.secondary_tileset || "")}</div>
        <div><strong>Exit warps:</strong> ${esc(exitWarps) || "none"}</div>
        <div><strong>Objects:</strong> ${(data.object_events || []).length}</div>
        <div><strong>Scripts included:</strong> ${data.scripts_pory ? "Yes" : "No"}</div>
        <div><strong>Stamp version:</strong> ${esc(data.stamp_version || "?")}</div>
      `;
    } else {
      panel.textContent = "Failed to load details.";
    }
  }
  panel.classList.add("open");
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function bindGridEvents() {
  if (!_container) return;

  // Search
  const searchInput = _container.querySelector("#sl-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      _searchQuery = searchInput.value;
      // Re-render grid only (keep header)
      const gridEl = _container.querySelector(".sl-grid");
      const emptyEl = _container.querySelector(".sl-empty");
      // Full re-render to update grid
      _container.innerHTML = renderGrid();
      bindGridEvents();
      // Restore focus
      const newSearch = _container.querySelector("#sl-search");
      if (newSearch) {
        newSearch.focus();
        newSearch.setSelectionRange(newSearch.value.length, newSearch.value.length);
      }
    });
  }

  // Create button
  const createBtn = _container.querySelector("#sl-create-btn");
  if (createBtn) {
    createBtn.addEventListener("click", async () => {
      _state = "create";
      _createStep = 0;
      _createSourceMap = "";
      _createWarps = [];
      _createExitIndices = [];
      _createName = "";
      _createDesc = "";
      _createTags = "";
      _createIncludeScripts = false;
      _createResult = null;
      await loadSourceMaps();
      rerenderState();
    });
  }

  // Place buttons (custom stamps)
  _container.querySelectorAll(".sl-action-place").forEach(btn => {
    btn.addEventListener("click", async () => {
      const stampId = btn.dataset.stampId;
      const stamp = _stamps.find(s => s.id === stampId);
      if (!stamp) return;

      _selectedStamp = stamp;
      _stampResult = null;
      _previewResult = null;
      _placeParentMap = "";
      _placeDoorX = 0;
      _placeDoorY = 0;
      _placeMapName = "";
      _placeMapGroup = "";

      // Check if in Studio — dispatch event and show fallback form
      if (_isInStudio()) {
        try {
          const { ideEmit } = await import("../ide.js");
          ideEmit("ide:stamp-pending", { stamp_id: stampId, stamp: stamp });
        } catch (_) {}
      }

      // Always show inline placement form as fallback
      _state = "place";
      await Promise.all([loadParentMaps(), loadMapGroups()]);
      rerenderState();
    });
  });

  // Place buttons (built-in templates — redirect to templates view)
  _container.querySelectorAll(".sl-action-place-builtin").forEach(btn => {
    btn.addEventListener("click", () => {
      window.location.hash = "#/templates";
    });
  });

  // Info buttons
  _container.querySelectorAll(".sl-action-info").forEach(btn => {
    btn.addEventListener("click", () => {
      doShowInfo(btn.dataset.stampId);
    });
  });

  // Delete buttons
  _container.querySelectorAll(".sl-action-delete").forEach(btn => {
    btn.addEventListener("click", () => {
      doDelete(btn.dataset.stampId);
    });
  });
}

function bindCreateEvents() {
  if (!_container) return;

  const cancelBtn = _container.querySelector("#sl-create-cancel");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      _state = "grid";
      rerenderState();
    });
  }

  const backBtn = _container.querySelector("#sl-create-back");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      if (_createStep > 0) {
        _createStep--;
        rerenderState();
      } else {
        _state = "grid";
        rerenderState();
      }
    });
  }

  const nextBtn = _container.querySelector("#sl-create-next");
  if (nextBtn) {
    nextBtn.addEventListener("click", async () => {
      if (_createStep === 0) {
        // Save source map, load warps
        const sel = _container.querySelector("#sl-create-source");
        if (sel) _createSourceMap = sel.value;
        if (!_createSourceMap) return;
        await loadSourceWarps(_createSourceMap);
        _createExitIndices = [];
        _createStep = 1;
        rerenderState();
      } else if (_createStep === 1) {
        _createStep = 2;
        if (!_createName) _createName = _createSourceMap;
        rerenderState();
      } else if (_createStep === 2) {
        // Save fields
        const nameInput = _container.querySelector("#sl-create-name");
        const descInput = _container.querySelector("#sl-create-desc");
        const tagsInput = _container.querySelector("#sl-create-tags");
        const scriptsCheck = _container.querySelector("#sl-create-scripts");
        if (nameInput) _createName = nameInput.value;
        if (descInput) _createDesc = descInput.value;
        if (tagsInput) _createTags = tagsInput.value;
        if (scriptsCheck) _createIncludeScripts = scriptsCheck.checked;
        if (!_createName.trim()) return;
        _createStep = 3;
        _createResult = null;
        rerenderState();
      }
    });
  }

  const submitBtn = _container.querySelector("#sl-create-submit");
  if (submitBtn) {
    submitBtn.addEventListener("click", doCreateStamp);
  }

  const doneBtn = _container.querySelector("#sl-create-done");
  if (doneBtn) {
    doneBtn.addEventListener("click", async () => {
      _state = "grid";
      await loadStamps();
      rerenderState();
    });
  }

  // Source map select (step 0)
  const sourceSel = _container.querySelector("#sl-create-source");
  if (sourceSel) {
    sourceSel.addEventListener("change", () => {
      _createSourceMap = sourceSel.value;
      const next = _container.querySelector("#sl-create-next");
      if (next) next.disabled = !_createSourceMap;
    });
  }

  // Warp checkboxes (step 1)
  _container.querySelectorAll(".sl-warp-check").forEach(cb => {
    cb.addEventListener("change", () => {
      const idx = parseInt(cb.dataset.index, 10);
      if (cb.checked) {
        if (!_createExitIndices.includes(idx)) _createExitIndices.push(idx);
      } else {
        _createExitIndices = _createExitIndices.filter(i => i !== idx);
      }
      const next = _container.querySelector("#sl-create-next");
      if (next) next.disabled = _createExitIndices.length === 0;
    });
  });

  // Name input live validation (step 2)
  const nameInput = _container.querySelector("#sl-create-name");
  if (nameInput) {
    nameInput.addEventListener("input", () => {
      _createName = nameInput.value;
      const next = _container.querySelector("#sl-create-next");
      if (next) next.disabled = !_createName.trim();
    });
  }
}

function bindPlaceEvents() {
  if (!_container) return;

  const backBtn = _container.querySelector("#sl-place-back");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      _state = "grid";
      _selectedStamp = null;
      _stampResult = null;
      _previewResult = null;
      rerenderState();
    });
  }

  const submitBtn = _container.querySelector("#sl-place-submit");
  if (submitBtn) {
    submitBtn.addEventListener("click", doPlace);
  }

  // Preview triggers
  const inputs = _container.querySelectorAll("#sl-place-parent, #sl-place-dx, #sl-place-dy, #sl-place-name, #sl-place-group");
  inputs.forEach(el => {
    el.addEventListener("input", schedulePreview);
    el.addEventListener("change", schedulePreview);
  });
}

// ---------------------------------------------------------------------------
// State machine re-render
// ---------------------------------------------------------------------------

function rerenderState() {
  if (!_container) return;
  if (_state === "grid") {
    _container.innerHTML = renderGrid();
    bindGridEvents();
  } else if (_state === "create") {
    _container.innerHTML = renderCreateWizard();
    bindCreateEvents();
  } else if (_state === "place") {
    _container.innerHTML = renderPlaceForm();
    bindPlaceEvents();
  }
}

// ---------------------------------------------------------------------------
// Studio detection
// ---------------------------------------------------------------------------

function _isInStudio() {
  // Check if we're inside the IDE (toolbar present, or hash is /studio or /ide)
  const hash = window.location.hash || "";
  if (hash.startsWith("#/studio") || hash.startsWith("#/ide")) return true;
  // Also check for IDE modal context (opened via openToolModal)
  if (document.querySelector(".ide-modal-backdrop")) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export async function render(container) {
  _container = container;

  // Inject scoped styles
  styleEl = document.createElement("style");
  styleEl.textContent = STYLES;
  document.head.appendChild(styleEl);

  // Show loading
  container.innerHTML = `<div class="sl-spinner">Loading stamp library...</div>`;

  // Load data
  await loadStamps();

  _state = "grid";
  _searchQuery = "";
  _selectedStamp = null;
  _stampResult = null;
  _previewResult = null;
  _createResult = null;

  container.innerHTML = renderGrid();
  bindGridEvents();
}

export function cleanup() {
  if (styleEl) { styleEl.remove(); styleEl = null; }
  if (_previewTimer) { clearTimeout(_previewTimer); _previewTimer = null; }
  _container = null;
  _state = "grid";
  _stamps = [];
  _builtinTemplates = [];
  _customStamps = [];
  _sourceMaps = [];
  _sourceWarps = [];
  _selectedStamp = null;
  _searchQuery = "";
  _writeLock = false;
  _previewResult = null;
  _previewLoading = false;
  _stampResult = null;
  _createResult = null;
  _createStep = 0;
  _parentMaps = [];
  _mapGroups = [];
}
