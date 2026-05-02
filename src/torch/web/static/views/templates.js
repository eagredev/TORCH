/**
 * TORCH Web GUI — Building Templates view.
 * Gallery of template cards + stamp wizard with preview.
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

let styleEl = null;
let _container = null;
let state = "gallery";  // "gallery" | "wizard"
let selectedTemplate = null;
let parentMaps = [];
let mapGroups = [];
let templates = [];
let previewResult = null;
let previewLoading = false;
let stampResult = null;
let writeLock = false;
let previewTimer = null;

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

const STYLES = `
/* Gallery layout */
.tmpl-gallery {
  display: flex; flex-wrap: wrap; gap: 1.5rem;
  padding: 1rem 0;
}
.tmpl-card {
  background: var(--surface-2, #1e1e2e);
  border: 1px solid var(--border-subtle, #313244);
  border-radius: 10px; padding: 1.5rem;
  min-width: 260px; max-width: 340px; flex: 1;
  display: flex; flex-direction: column; gap: 0.75rem;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.tmpl-card:hover {
  border-color: var(--accent, #cba6f7);
  box-shadow: 0 0 0 1px var(--accent, #cba6f7);
}
.tmpl-card-name {
  font-size: 1.1rem; font-weight: 600;
  color: var(--text-primary, #cdd6f4);
}
.tmpl-card-desc {
  font-size: 0.85rem; color: var(--text-dim, #6c7086);
  line-height: 1.4;
}
.tmpl-card-details {
  display: flex; flex-direction: column; gap: 0.3rem;
  font-size: 0.8rem; color: var(--text-dim, #6c7086);
}
.tmpl-card-tag {
  display: inline-block; padding: 0.15rem 0.5rem;
  background: rgba(255,255,255,0.05);
  border-radius: 4px; font-size: 0.75rem;
  color: var(--text-dim, #6c7086);
}
.tmpl-card-tag.heal {
  color: #f38ba8; background: rgba(243,139,168,0.1);
}
.tmpl-card-btn {
  margin-top: auto; padding: 0.6rem 1.2rem;
  background: var(--accent, #cba6f7); color: #111;
  border: none; border-radius: 6px; cursor: pointer;
  font-weight: 600; font-size: 0.85rem;
  transition: opacity 0.15s;
}
.tmpl-card-btn:hover { opacity: 0.9; }

/* Wizard layout */
.tmpl-wizard {
  max-width: 720px;
}
.tmpl-wizard-title {
  font-size: 1.1rem; font-weight: 600;
  color: var(--text-primary, #cdd6f4);
  margin-bottom: 1rem;
}
.tmpl-field {
  margin-bottom: 1rem;
}
.tmpl-field label {
  display: block; font-size: 0.8rem; font-weight: 500;
  color: var(--text-dim, #6c7086);
  margin-bottom: 0.3rem;
}
.tmpl-field select,
.tmpl-field input[type="number"],
.tmpl-field input[type="text"] {
  width: 100%; padding: 0.5rem 0.6rem;
  background: var(--surface-1, #181825);
  color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border-subtle, #313244);
  border-radius: 6px; font-size: 0.85rem;
}
.tmpl-field select:focus,
.tmpl-field input:focus {
  outline: none;
  border-color: var(--accent, #cba6f7);
}
.tmpl-field-hint {
  font-size: 0.75rem; color: var(--text-dim, #6c7086);
  margin-top: 0.2rem;
}
.tmpl-coords {
  display: flex; gap: 1rem;
}
.tmpl-coords .tmpl-field { flex: 1; }
.tmpl-checkbox {
  display: flex; align-items: center; gap: 0.5rem;
  margin-bottom: 1rem;
}
.tmpl-checkbox input { width: auto; }
.tmpl-checkbox label { margin-bottom: 0; }

/* Preview panel */
.tmpl-preview {
  background: var(--surface-1, #181825);
  border: 1px solid var(--border-subtle, #313244);
  border-radius: 8px; padding: 1rem;
  margin-bottom: 1rem; font-size: 0.8rem;
}
.tmpl-preview-title {
  font-weight: 600; color: var(--text-primary, #cdd6f4);
  margin-bottom: 0.5rem;
}
.tmpl-preview-item {
  padding: 0.2rem 0; display: flex; align-items: center; gap: 0.4rem;
}
.tmpl-preview-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
}
.tmpl-dot-green { background: #a6e3a1; }
.tmpl-dot-yellow { background: #f9e2af; }
.tmpl-dot-blue { background: #89b4fa; }
.tmpl-preview-error { color: #f38ba8; }
.tmpl-preview-warning { color: #fab387; }
.tmpl-preview-loading { color: var(--text-dim, #6c7086); font-style: italic; }

/* Result panel */
.tmpl-result {
  border-radius: 8px; padding: 1rem; margin-bottom: 1rem;
  font-size: 0.85rem;
}
.tmpl-result.success {
  background: rgba(166,227,161,0.1);
  border: 1px solid rgba(166,227,161,0.3);
  color: #a6e3a1;
}
.tmpl-result.failure {
  background: rgba(243,139,168,0.1);
  border: 1px solid rgba(243,139,168,0.3);
  color: #f38ba8;
}
.tmpl-result a {
  color: var(--accent, #cba6f7); text-decoration: underline;
  cursor: pointer;
}

/* Button row */
.tmpl-actions {
  display: flex; gap: 0.75rem; margin-top: 1rem;
}
.tmpl-btn {
  padding: 0.5rem 1rem; border-radius: 6px; font-size: 0.85rem;
  font-weight: 500; cursor: pointer; border: none;
  transition: opacity 0.15s;
}
.tmpl-btn:hover { opacity: 0.9; }
.tmpl-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.tmpl-btn-primary {
  background: var(--accent, #cba6f7); color: #111;
}
.tmpl-btn-secondary {
  background: var(--surface-2, #1e1e2e);
  color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border-subtle, #313244);
}
`;

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------

function renderGallery() {
  let html = renderStudioNavbar("Templates");
  html += `<h2 style="margin-bottom:0.5rem;color:var(--text-primary,#cdd6f4)">Building Templates</h2>`;
  html += `<p style="font-size:0.85rem;color:var(--text-dim,#6c7086);margin-bottom:1rem">Stamp complete building interiors with one click.</p>`;
  html += `<div class="tmpl-gallery">`;

  for (const t of templates) {
    const tags = t.includes.map(s => `<span class="tmpl-card-tag">${esc(s)}</span>`).join(" ");
    const healTag = t.creates_heal_location
      ? `<span class="tmpl-card-tag heal">+ Heal Location</span>`
      : "";
    html += `
      <div class="tmpl-card">
        <div class="tmpl-card-name">${esc(t.name)}</div>
        <div class="tmpl-card-desc">${esc(t.description)}</div>
        <div class="tmpl-card-details">${tags} ${healTag}</div>
        <button class="tmpl-card-btn" data-template="${esc(t.id)}">Stamp</button>
      </div>`;
  }
  html += `</div>`;
  return html;
}

function renderWizard() {
  const t = templates.find(x => x.id === selectedTemplate);
  if (!t) return `<p>Unknown template.</p>`;

  let html = renderStudioNavbar("Templates");
  html += `<div class="tmpl-wizard">`;
  html += `<div class="tmpl-wizard-title">Stamp ${esc(t.name)}</div>`;

  // Parent map dropdown
  html += `<div class="tmpl-field">
    <label>Parent Map (door location)</label>
    <select id="tmpl-parent">
      <option value="">-- Select a map --</option>
      ${parentMaps.map(m => `<option value="${esc(m.name)}">${esc(m.name)} (${esc(m.map_type.replace("MAP_TYPE_",""))} ${m.width || "?"}x${m.height || "?"})</option>`).join("")}
    </select>
  </div>`;

  // Town name
  html += `<div class="tmpl-field">
    <label>Town Name (used for map folder naming)</label>
    <input type="text" id="tmpl-town" placeholder="e.g. ShirubeTown">
    <div class="tmpl-field-hint">Auto-filled from parent map. Edit to customise.</div>
  </div>`;

  // Door coordinates
  html += `<div class="tmpl-coords">
    <div class="tmpl-field">
      <label>Door X</label>
      <input type="number" id="tmpl-door-x" min="0" value="0">
    </div>
    <div class="tmpl-field">
      <label>Door Y</label>
      <input type="number" id="tmpl-door-y" min="0" value="0">
    </div>
  </div>`;
  html += `<div class="tmpl-field-hint" id="tmpl-bounds-hint"></div>`;

  // Include 2F (PokéCenter only)
  if (selectedTemplate === "pokecenter") {
    const checked = localStorage.getItem("torch_tmpl_include_2f") !== "false";
    html += `<div class="tmpl-checkbox">
      <input type="checkbox" id="tmpl-2f" ${checked ? "checked" : ""}>
      <label for="tmpl-2f">Include 2F (Cable Club)</label>
    </div>`;
  }

  // Map group dropdown
  html += `<div class="tmpl-field">
    <label>Map Group</label>
    <select id="tmpl-group">
      <option value="">-- Auto (same group as parent) --</option>
      ${mapGroups.map(g => `<option value="${esc(g)}">${esc(g)}</option>`).join("")}
    </select>
  </div>`;

  // Preview panel
  html += `<div class="tmpl-preview" id="tmpl-preview">
    <div class="tmpl-preview-title">Preview</div>
    <div class="tmpl-preview-loading">Fill in all fields to see preview...</div>
  </div>`;

  // Stamp result
  if (stampResult) {
    if (stampResult.success) {
      let links = `<a href="#/explorer">Open Map Explorer</a>`;
      if (selectedTemplate === "pokemart") {
        links += ` &middot; <a href="#/shops">Edit Shop Items</a>`;
      }
      html += `<div class="tmpl-result success">
        <strong>Stamp complete!</strong><br>
        Created: ${(stampResult.maps_created || []).map(m => esc(m)).join(", ")}<br>
        Files created: ${(stampResult.created_files || []).length}<br>
        Files modified: ${(stampResult.modified_files || []).length}<br>
        ${stampResult.heal_location_id ? `Heal location: ${esc(stampResult.heal_location_id)}<br>` : ""}
        ${(stampResult.warnings || []).length ? `<div style="color:#fab387;margin-top:0.4rem">Warnings: ${stampResult.warnings.map(w => esc(w)).join("; ")}</div>` : ""}
        <div style="margin-top:0.5rem">${links}</div>
      </div>`;
    } else {
      html += `<div class="tmpl-result failure">
        <strong>Stamp failed:</strong> ${esc(stampResult.error || "Unknown error")}
      </div>`;
    }
  }

  // Buttons
  const canStamp = previewResult && previewResult.valid && !writeLock && !stampResult;
  html += `<div class="tmpl-actions">
    <button class="tmpl-btn tmpl-btn-secondary" id="tmpl-back">Back</button>
    <button class="tmpl-btn tmpl-btn-primary" id="tmpl-stamp" ${canStamp ? "" : "disabled"}>
      ${writeLock ? "Stamping..." : "Stamp"}
    </button>
  </div>`;

  html += `</div>`;
  return html;
}

function renderPreview() {
  const el = _container && _container.querySelector("#tmpl-preview");
  if (!el) return;

  let html = `<div class="tmpl-preview-title">Preview</div>`;
  if (previewLoading) {
    html += `<div class="tmpl-preview-loading">Validating...</div>`;
  } else if (!previewResult) {
    html += `<div class="tmpl-preview-loading">Fill in all fields to see preview...</div>`;
  } else {
    // Errors
    for (const err of (previewResult.errors || [])) {
      html += `<div class="tmpl-preview-item tmpl-preview-error">\u2716 ${esc(err)}</div>`;
    }
    // Warnings
    for (const warn of (previewResult.warnings || [])) {
      html += `<div class="tmpl-preview-item tmpl-preview-warning">\u26A0 ${esc(warn)}</div>`;
    }
    const p = previewResult.preview || {};
    // Maps to create
    for (const m of (p.maps_to_create || [])) {
      html += `<div class="tmpl-preview-item"><span class="tmpl-preview-dot tmpl-dot-green"></span> Create: ${esc(m)}</div>`;
    }
    // Files to create
    for (const f of (p.files_to_create || [])) {
      html += `<div class="tmpl-preview-item"><span class="tmpl-preview-dot tmpl-dot-green"></span> ${esc(f)}</div>`;
    }
    // Files to modify
    for (const f of (p.files_to_modify || [])) {
      html += `<div class="tmpl-preview-item"><span class="tmpl-preview-dot tmpl-dot-yellow"></span> ${esc(f)}</div>`;
    }
    // Heal location
    if (p.heal_location_id) {
      html += `<div class="tmpl-preview-item"><span class="tmpl-preview-dot tmpl-dot-blue"></span> Heal: ${esc(p.heal_location_id)}</div>`;
    }
  }
  el.innerHTML = html;

  // Update stamp button state
  const btn = _container && _container.querySelector("#tmpl-stamp");
  if (btn) {
    btn.disabled = !(previewResult && previewResult.valid && !writeLock && !stampResult);
  }
}

// ---------------------------------------------------------------------------
// Data loading and preview
// ---------------------------------------------------------------------------

async function loadTemplates() {
  const res = await api("/templates");
  if (res.ok) templates = res.data.templates || [];
}

async function loadParentMaps() {
  const res = await api("/templates/maps");
  if (res.ok) parentMaps = res.data.maps || [];
}

async function loadMapGroups() {
  const res = await api("/templates/groups");
  if (res.ok) mapGroups = res.data.groups || [];
}

function schedulePreview() {
  if (previewTimer) clearTimeout(previewTimer);
  previewTimer = setTimeout(doPreview, 400);
}

async function doPreview() {
  if (!_container) return;
  const parent = (_container.querySelector("#tmpl-parent") || {}).value || "";
  const doorX = (_container.querySelector("#tmpl-door-x") || {}).value || "";
  const doorY = (_container.querySelector("#tmpl-door-y") || {}).value || "";

  if (!parent || doorX === "" || doorY === "") {
    previewResult = null;
    renderPreview();
    return;
  }

  const include2f = selectedTemplate === "pokecenter"
    ? ((_container.querySelector("#tmpl-2f") || {}).checked !== false)
    : true;
  const townName = (_container.querySelector("#tmpl-town") || {}).value || "";

  previewLoading = true;
  renderPreview();

  let qs = `?template=${encodeURIComponent(selectedTemplate)}`;
  qs += `&parent=${encodeURIComponent(parent)}`;
  qs += `&door_x=${encodeURIComponent(doorX)}`;
  qs += `&door_y=${encodeURIComponent(doorY)}`;
  qs += `&include_2f=${include2f}`;
  if (townName) qs += `&town_name=${encodeURIComponent(townName)}`;

  const res = await api(`/templates/preview${qs}`);
  previewLoading = false;
  if (res.ok) {
    previewResult = res.data;
  } else {
    previewResult = { valid: false, errors: [res.error || "Preview failed"], warnings: [], preview: {} };
  }
  renderPreview();
}

async function doStamp() {
  if (writeLock || !_container) return;
  writeLock = true;
  renderPreview();

  const parent = (_container.querySelector("#tmpl-parent") || {}).value || "";
  const doorX = parseInt((_container.querySelector("#tmpl-door-x") || {}).value, 10);
  const doorY = parseInt((_container.querySelector("#tmpl-door-y") || {}).value, 10);
  const include2f = selectedTemplate === "pokecenter"
    ? ((_container.querySelector("#tmpl-2f") || {}).checked !== false)
    : true;
  const townName = (_container.querySelector("#tmpl-town") || {}).value || "";
  const mapGroup = (_container.querySelector("#tmpl-group") || {}).value || "";

  const body = {
    template: selectedTemplate,
    parent_map: parent,
    door_x: doorX,
    door_y: doorY,
    include_2f: include2f,
  };
  if (townName) body.town_name = townName;
  if (mapGroup) body.map_group = mapGroup;

  const res = await postApi("/templates/stamp", body);
  writeLock = false;

  if (res.ok) {
    stampResult = res.data;
  } else {
    stampResult = { success: false, error: res.error || "Stamp request failed" };
  }
  // Re-render entire wizard to show result
  _container.innerHTML = renderWizard();
  bindWizardEvents();
  renderPreview();
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function bindGalleryEvents() {
  if (!_container) return;
  _container.querySelectorAll(".tmpl-card-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      selectedTemplate = btn.dataset.template;
      stampResult = null;
      previewResult = null;

      // Load data for wizard
      await Promise.all([loadParentMaps(), loadMapGroups()]);
      state = "wizard";
      _container.innerHTML = renderWizard();
      bindWizardEvents();
    });
  });
}

function bindWizardEvents() {
  if (!_container) return;

  const backBtn = _container.querySelector("#tmpl-back");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      state = "gallery";
      stampResult = null;
      previewResult = null;
      _container.innerHTML = renderGallery();
      bindGalleryEvents();
    });
  }

  const stampBtn = _container.querySelector("#tmpl-stamp");
  if (stampBtn) {
    stampBtn.addEventListener("click", doStamp);
  }

  // Auto-fill town name from parent map selection
  const parentSel = _container.querySelector("#tmpl-parent");
  const townInput = _container.querySelector("#tmpl-town");
  if (parentSel) {
    parentSel.addEventListener("change", () => {
      if (townInput) townInput.value = parentSel.value;
      // Update bounds hint
      const m = parentMaps.find(x => x.name === parentSel.value);
      const hint = _container.querySelector("#tmpl-bounds-hint");
      if (hint && m && m.width && m.height) {
        hint.textContent = `Map bounds: ${m.width}\u00d7${m.height}`;
      } else if (hint) {
        hint.textContent = "";
      }
      schedulePreview();
    });
  }

  // Save 2F preference
  const cb2f = _container.querySelector("#tmpl-2f");
  if (cb2f) {
    cb2f.addEventListener("change", () => {
      localStorage.setItem("torch_tmpl_include_2f", cb2f.checked);
      schedulePreview();
    });
  }

  // Preview on coordinate or group changes
  const inputs = _container.querySelectorAll("#tmpl-door-x, #tmpl-door-y, #tmpl-town, #tmpl-group");
  inputs.forEach(el => {
    el.addEventListener("input", schedulePreview);
    el.addEventListener("change", schedulePreview);
  });
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export async function render(container) {
  _container = container;

  // Inject styles
  styleEl = document.createElement("style");
  styleEl.textContent = STYLES;
  document.head.appendChild(styleEl);

  // Load templates
  await loadTemplates();

  state = "gallery";
  container.innerHTML = renderGallery();
  bindGalleryEvents();
}

export function cleanup() {
  if (styleEl) { styleEl.remove(); styleEl = null; }
  if (previewTimer) { clearTimeout(previewTimer); previewTimer = null; }
  _container = null;
  state = "gallery";
  selectedTemplate = null;
  parentMaps = [];
  mapGroups = [];
  previewResult = null;
  stampResult = null;
  writeLock = false;
}
