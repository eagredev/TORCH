/**
 * TORCH Web GUI — Heal Locations view.
 *
 * List, add, edit, delete heal locations.  Scan for drift and missing entries.
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let allLocations = [];
let styleEl = null;
let _container = null;
let activePanel = "list"; // "list" | "add" | "edit" | "scan"
let editTarget = null;    // heal id being edited
let editField = null;     // field name being inline-edited
let addMode = "pokecenter"; // "pokecenter" | "custom"
let detectResult = null;  // result from /api/heals/detect
let scanResult = null;    // result from /api/heals/scan
let writeLock = false;

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

const STYLES = `
/* Heal locations layout */
.heals-toolbar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem;
  margin-bottom: 1rem;
}
.heals-toolbar-btn {
  padding: 0.4rem 0.8rem; font-size: 0.8rem; font-weight: 500;
  background: var(--surface-2, #1e1e2e); color: var(--text-secondary, #ccc);
  border: 1px solid var(--border-subtle, #313244); border-radius: 4px;
  cursor: pointer; transition: background 0.15s, border-color 0.15s;
}
.heals-toolbar-btn:hover {
  background: rgba(255,255,255,0.05); border-color: var(--accent, #cba6f7);
}
.heals-toolbar-btn.primary {
  background: var(--accent, #cba6f7); color: #111; border-color: var(--accent, #cba6f7);
}
.heals-toolbar-btn.primary:hover { opacity: 0.9; }
.heals-toolbar-btn:disabled {
  opacity: 0.5; cursor: not-allowed;
}
.heals-count {
  font-size: 0.75rem; color: var(--text-dim, #6c7086); margin-left: auto;
}

/* Table */
.heals-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.heals-table th {
  text-align: left; padding: 0.4rem 0.6rem; color: var(--text-dim, #6c7086);
  font-weight: 500; font-size: 0.7rem; text-transform: uppercase;
  letter-spacing: 0.05em; border-bottom: 1px solid var(--border-subtle, #313244);
}
.heals-table td {
  padding: 0.4rem 0.6rem; color: var(--text-secondary, #ccc);
  border-bottom: 1px solid var(--border-subtle, #313244);
}
.heals-table tr:last-child td { border-bottom: none; }
.heals-table tbody tr { cursor: pointer; }
.heals-table tbody tr:hover td { background: rgba(255,255,255,0.02); }
.heals-table tbody tr.active td {
  background: rgba(255,255,255,0.04);
}
.heals-coords {
  font-family: monospace; font-size: 0.8rem; color: var(--text-dim, #6c7086);
}
.heals-status-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
}
.heals-status-ok { background: #4caf50; }
.heals-status-warn { background: #e8a020; }

/* Edit panel */
.heals-edit-panel {
  background: var(--surface-2, #1e1e2e); border: 1px solid var(--border-subtle, #313244);
  border-radius: 8px; padding: 1rem 1.25rem; margin-top: 1rem;
}
.heals-edit-title {
  font-size: 1rem; font-weight: 600; color: var(--text-primary, #cdd6f4);
  margin-bottom: 0.75rem;
}
.heals-field-row {
  display: flex; align-items: center; gap: 0.75rem; padding: 0.4rem 0;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.heals-field-row:last-child { border-bottom: none; }
.heals-field-label {
  min-width: 110px; font-size: 0.75rem; font-weight: 500;
  color: var(--text-dim, #6c7086); text-transform: uppercase;
  letter-spacing: 0.04em;
}
.heals-field-value {
  flex: 1; font-size: 0.85rem; color: var(--text-primary, #cdd6f4);
  cursor: pointer; padding: 0.2rem 0.4rem; border-radius: 3px;
  transition: background 0.15s;
}
.heals-field-value:hover { background: rgba(255,255,255,0.05); }
.heals-field-value.coord { font-family: monospace; }
.heals-field-input {
  flex: 1; padding: 0.3rem 0.5rem; font-size: 0.85rem;
  background: var(--surface-3, #313244); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--accent, #cba6f7); border-radius: 3px; outline: none;
}
.heals-edit-actions {
  display: flex; gap: 0.5rem; margin-top: 1rem; align-items: center;
}
.heals-btn-danger {
  padding: 0.35rem 0.7rem; font-size: 0.8rem;
  background: rgba(220,50,50,0.15); color: #e85050;
  border: 1px solid rgba(220,50,50,0.3); border-radius: 4px;
  cursor: pointer; margin-left: auto;
}
.heals-btn-danger:hover { background: rgba(220,50,50,0.25); }
.heals-btn-sm {
  padding: 0.3rem 0.6rem; font-size: 0.75rem;
  background: var(--surface-2, #1e1e2e); color: var(--text-secondary, #ccc);
  border: 1px solid var(--border-subtle, #313244); border-radius: 3px;
  cursor: pointer;
}
.heals-btn-sm:hover { border-color: var(--accent, #cba6f7); }

/* Add wizard */
.heals-add-panel {
  background: var(--surface-2, #1e1e2e); border: 1px solid var(--border-subtle, #313244);
  border-radius: 8px; padding: 1rem 1.25rem; margin-top: 1rem;
}
.heals-add-title {
  font-size: 1rem; font-weight: 600; color: var(--text-primary, #cdd6f4);
  margin-bottom: 0.75rem;
}
.heals-mode-toggle {
  display: flex; gap: 0; margin-bottom: 1rem;
}
.heals-mode-btn {
  padding: 0.35rem 0.8rem; font-size: 0.8rem;
  background: var(--surface-3, #313244); color: var(--text-dim, #6c7086);
  border: 1px solid var(--border-subtle, #313244); cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.heals-mode-btn:first-child { border-radius: 4px 0 0 4px; }
.heals-mode-btn:last-child { border-radius: 0 4px 4px 0; }
.heals-mode-btn + .heals-mode-btn { border-left: none; }
.heals-mode-btn.active {
  background: var(--accent, #cba6f7); color: #111;
  border-color: var(--accent, #cba6f7);
}
.heals-form-group {
  margin-bottom: 0.75rem;
}
.heals-form-label {
  display: block; font-size: 0.75rem; font-weight: 500;
  color: var(--text-dim, #6c7086); margin-bottom: 0.25rem;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.heals-form-input {
  width: 100%; padding: 0.4rem 0.6rem; font-size: 0.85rem;
  background: var(--surface-3, #313244); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border-subtle, #313244); border-radius: 4px;
  outline: none; box-sizing: border-box;
}
.heals-form-input:focus { border-color: var(--accent, #cba6f7); }
.heals-form-input.short { width: 100px; }
.heals-form-row {
  display: flex; gap: 0.75rem; align-items: flex-end;
}
.heals-detect-result {
  background: rgba(76,175,80,0.08); border: 1px solid rgba(76,175,80,0.2);
  border-radius: 6px; padding: 0.6rem 0.8rem; margin-bottom: 0.75rem;
  font-size: 0.8rem; color: var(--text-secondary, #ccc);
}
.heals-detect-warn {
  color: #e8a020; font-size: 0.75rem; margin-top: 0.25rem;
}

/* Scan results */
.heals-scan-panel {
  background: var(--surface-2, #1e1e2e); border: 1px solid var(--border-subtle, #313244);
  border-radius: 8px; padding: 1rem 1.25rem; margin-top: 1rem;
}
.heals-scan-title {
  font-size: 1rem; font-weight: 600; color: var(--text-primary, #cdd6f4);
  margin-bottom: 0.75rem;
}
.heals-scan-section {
  margin-bottom: 1rem;
}
.heals-scan-subtitle {
  font-size: 0.85rem; font-weight: 600;
  color: var(--text-secondary, #ccc); margin-bottom: 0.5rem;
}
.heals-scan-ok {
  color: #4caf50; font-size: 0.85rem; padding: 0.5rem 0;
}
.heals-drift-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.heals-drift-table th {
  text-align: left; padding: 0.3rem 0.5rem; color: var(--text-dim, #6c7086);
  font-size: 0.7rem; text-transform: uppercase; border-bottom: 1px solid var(--border-subtle, #313244);
}
.heals-drift-table td {
  padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--border-subtle, #313244);
}
.heals-drift-old { color: #e85050; font-family: monospace; text-decoration: line-through; }
.heals-drift-new { color: #4caf50; font-family: monospace; font-weight: 600; }
.heals-missing-row {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.35rem 0; border-bottom: 1px solid rgba(255,255,255,0.04);
  font-size: 0.8rem;
}
.heals-missing-name { flex: 1; color: var(--text-primary, #cdd6f4); }
.heals-missing-type { color: var(--text-dim, #6c7086); font-size: 0.75rem; min-width: 60px; }
.heals-missing-pc { font-size: 0.7rem; }
.heals-missing-pc.yes { color: #4caf50; }
.heals-missing-pc.no { color: var(--text-dim, #6c7086); }

/* Confirmation dialog */
.heals-confirm-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.heals-confirm-box {
  background: var(--surface-2, #1e1e2e); border: 1px solid var(--border-subtle, #313244);
  border-radius: 8px; padding: 1.5rem; max-width: 400px; width: 90%;
}
.heals-confirm-title {
  font-size: 1rem; font-weight: 600; color: #e85050; margin-bottom: 0.75rem;
}
.heals-confirm-text {
  font-size: 0.85rem; color: var(--text-secondary, #ccc); margin-bottom: 1rem;
  line-height: 1.4;
}
.heals-confirm-actions { display: flex; gap: 0.5rem; justify-content: flex-end; }
`;

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function injectCSS() {
  if (styleEl) return;
  styleEl = document.createElement("style");
  styleEl.textContent = STYLES;
  document.head.appendChild(styleEl);
}

function renderToolbar() {
  let html = `<div class="heals-toolbar">`;
  html += `<button class="heals-toolbar-btn primary" data-action="add">+ Add</button>`;
  html += `<button class="heals-toolbar-btn" data-action="scan">Scan</button>`;
  html += `<span class="heals-count">${allLocations.length} location${allLocations.length !== 1 ? "s" : ""}</span>`;
  html += `</div>`;
  return html;
}

function renderTable() {
  if (allLocations.length === 0) {
    return `<div style="color:var(--text-dim);padding:1rem 0;font-size:0.85rem;">No heal locations found. Add one to get started.</div>`;
  }
  let html = `<table class="heals-table"><thead><tr>`;
  html += `<th></th><th>Name</th><th>Map</th><th>Coords</th><th>Respawn</th><th>NPC</th>`;
  html += `</tr></thead><tbody>`;
  for (const loc of allLocations) {
    const isActive = editTarget === loc.id ? " active" : "";
    const hasRespawn = !!loc.respawn_map;
    const dotClass = hasRespawn ? "heals-status-ok" : "heals-status-warn";
    const coordStr = loc.x != null && loc.y != null ? `(${loc.x}, ${loc.y})` : "?";
    const respawnDisplay = loc.respawn_map ? respawnName(loc.respawn_map) : "\u2014";
    const npcStr = loc.respawn_npc || "\u2014";
    html += `<tr class="${isActive}" data-heal-id="${esc(loc.id)}">`;
    html += `<td><span class="heals-status-dot ${dotClass}" title="${hasRespawn ? "Complete" : "Missing respawn"}"></span></td>`;
    html += `<td>${esc(loc.display_name)}</td>`;
    html += `<td style="font-size:0.75rem;color:var(--text-dim)">${esc(mapDisplay(loc.map))}</td>`;
    html += `<td class="heals-coords">${esc(coordStr)}</td>`;
    html += `<td style="font-size:0.75rem">${esc(respawnDisplay)}</td>`;
    html += `<td style="font-size:0.75rem">${esc(npcStr)}</td>`;
    html += `</tr>`;
  }
  html += `</tbody></table>`;
  return html;
}

function mapDisplay(mapConst) {
  if (!mapConst) return "?";
  let name = mapConst;
  if (name.startsWith("MAP_")) name = name.substring(4);
  return name.split("_").map(p => /^[0-9]+[A-Z]+$/.test(p) ? p : p.charAt(0) + p.slice(1).toLowerCase()).join(" ");
}

function respawnName(mapConst) {
  return mapDisplay(mapConst);
}

function renderEditPanel() {
  const loc = allLocations.find(l => l.id === editTarget);
  if (!loc) return "";
  let html = `<div class="heals-edit-panel">`;
  html += `<div class="heals-edit-title">${esc(loc.display_name)}</div>`;

  const fields = [
    { key: "map", label: "Map", value: loc.map || "" },
    { key: "x", label: "X", value: loc.x != null ? String(loc.x) : "", coord: true },
    { key: "y", label: "Y", value: loc.y != null ? String(loc.y) : "", coord: true },
    { key: "respawn_map", label: "Respawn Map", value: loc.respawn_map || "" },
    { key: "respawn_npc", label: "Respawn NPC", value: loc.respawn_npc || "" },
  ];

  for (const f of fields) {
    html += `<div class="heals-field-row">`;
    html += `<span class="heals-field-label">${esc(f.label)}</span>`;
    if (editField === f.key) {
      html += `<input class="heals-field-input" data-edit-field="${esc(f.key)}" value="${esc(f.value)}" autofocus>`;
      html += `<button class="heals-btn-sm" data-save-field="${esc(f.key)}">Save</button>`;
      html += `<button class="heals-btn-sm" data-cancel-edit>Cancel</button>`;
    } else {
      const coordClass = f.coord ? " coord" : "";
      const display = f.value || "\u2014";
      html += `<span class="heals-field-value${coordClass}" data-click-field="${esc(f.key)}">${esc(display)}</span>`;
    }
    html += `</div>`;
  }

  html += `<div class="heals-edit-actions">`;
  html += `<button class="heals-toolbar-btn" data-action="detect-edit">Auto-detect</button>`;
  html += `<button class="heals-btn-danger" data-action="delete">Delete</button>`;
  html += `</div>`;
  html += `</div>`;
  return html;
}

function renderAddPanel() {
  let html = `<div class="heals-add-panel">`;
  html += `<div class="heals-add-title">Add Heal Location</div>`;

  // Mode toggle
  html += `<div class="heals-mode-toggle">`;
  html += `<button class="heals-mode-btn${addMode === "pokecenter" ? " active" : ""}" data-mode="pokecenter">Pokemon Center</button>`;
  html += `<button class="heals-mode-btn${addMode === "custom" ? " active" : ""}" data-mode="custom">Custom Heal Point</button>`;
  html += `</div>`;

  if (addMode === "pokecenter") {
    html += renderAddPokecenter();
  } else {
    html += renderAddCustom();
  }

  html += `<div class="heals-edit-actions">`;
  html += `<button class="heals-toolbar-btn primary" data-action="create"${writeLock ? " disabled" : ""}>Create</button>`;
  html += `<button class="heals-toolbar-btn" data-action="cancel-add">Cancel</button>`;
  html += `</div>`;
  html += `</div>`;
  return html;
}

function renderAddPokecenter() {
  let html = "";
  html += `<div class="heals-form-group">`;
  html += `<label class="heals-form-label">Map Folder Name</label>`;
  html += `<div class="heals-form-row">`;
  html += `<input class="heals-form-input" id="heal-add-map" placeholder="e.g. PetalburgCity" value="${esc(document.getElementById("heal-add-map")?.value || "")}">`;
  html += `<button class="heals-toolbar-btn" data-action="detect"${writeLock ? " disabled" : ""}>Detect</button>`;
  html += `</div>`;
  html += `</div>`;

  if (detectResult) {
    html += `<div class="heals-detect-result">`;
    if (detectResult.coords) {
      html += `<div>Heal tile: <strong>(${detectResult.coords.x}, ${detectResult.coords.y})</strong></div>`;
    }
    if (detectResult.respawn_map) {
      html += `<div>Respawn: <strong>${esc(mapDisplay(detectResult.respawn_map))}</strong></div>`;
    }
    if (detectResult.respawn_npc) {
      html += `<div>Nurse NPC: <strong>${esc(detectResult.respawn_npc)}</strong></div>`;
    }
    if (detectResult.warnings && detectResult.warnings.length) {
      for (const w of detectResult.warnings) {
        html += `<div class="heals-detect-warn">${esc(w)}</div>`;
      }
    }
    html += `</div>`;

    // Override fields
    html += `<div class="heals-form-row">`;
    html += `<div class="heals-form-group"><label class="heals-form-label">X</label>`;
    html += `<input class="heals-form-input short" id="heal-add-x" value="${detectResult.coords ? detectResult.coords.x : ""}"></div>`;
    html += `<div class="heals-form-group"><label class="heals-form-label">Y</label>`;
    html += `<input class="heals-form-input short" id="heal-add-y" value="${detectResult.coords ? detectResult.coords.y : ""}"></div>`;
    html += `</div>`;
    html += `<div class="heals-form-group"><label class="heals-form-label">Respawn Map</label>`;
    html += `<input class="heals-form-input" id="heal-add-respawn" value="${esc(detectResult.respawn_map || "")}"></div>`;
    html += `<div class="heals-form-group"><label class="heals-form-label">Respawn NPC</label>`;
    html += `<input class="heals-form-input short" id="heal-add-npc" value="${esc(detectResult.respawn_npc || "1")}"></div>`;
  }

  return html;
}

function renderAddCustom() {
  let html = "";
  html += `<div class="heals-form-group"><label class="heals-form-label">Heal Location ID</label>`;
  html += `<input class="heals-form-input" id="heal-add-id" placeholder="HEAL_LOCATION_MY_CAMP"></div>`;
  html += `<div class="heals-form-group"><label class="heals-form-label">Map Constant</label>`;
  html += `<input class="heals-form-input" id="heal-add-map-const" placeholder="MAP_MY_CAMP"></div>`;
  html += `<div class="heals-form-row">`;
  html += `<div class="heals-form-group"><label class="heals-form-label">X</label>`;
  html += `<input class="heals-form-input short" id="heal-add-x"></div>`;
  html += `<div class="heals-form-group"><label class="heals-form-label">Y</label>`;
  html += `<input class="heals-form-input short" id="heal-add-y"></div>`;
  html += `</div>`;
  html += `<div class="heals-form-group"><label class="heals-form-label">Respawn Map (optional)</label>`;
  html += `<input class="heals-form-input" id="heal-add-respawn" placeholder="MAP_MY_CAMP_POKEMON_CENTER_1F"></div>`;
  html += `<div class="heals-form-group"><label class="heals-form-label">Respawn NPC (optional)</label>`;
  html += `<input class="heals-form-input short" id="heal-add-npc" placeholder="1"></div>`;
  return html;
}

function renderScanPanel() {
  if (!scanResult) return "";
  let html = `<div class="heals-scan-panel">`;
  html += `<div class="heals-scan-title">Scan Results</div>`;

  if (scanResult.all_ok) {
    html += `<div class="heals-scan-ok">All heal locations are up to date. No drift or missing entries found.</div>`;
  } else {
    // Drift section
    if (scanResult.drift && scanResult.drift.length > 0) {
      html += `<div class="heals-scan-section">`;
      html += `<div class="heals-scan-subtitle">Coordinate Drift (${scanResult.drift.length})</div>`;
      html += `<table class="heals-drift-table"><thead><tr>`;
      html += `<th>Location</th><th>Old</th><th>New</th>`;
      html += `</tr></thead><tbody>`;
      for (const d of scanResult.drift) {
        const name = healIdToDisplay(d.id);
        html += `<tr>`;
        html += `<td>${esc(name)}</td>`;
        html += `<td class="heals-drift-old">(${d.old_x}, ${d.old_y})</td>`;
        html += `<td class="heals-drift-new">(${d.new_x}, ${d.new_y})</td>`;
        html += `</tr>`;
      }
      html += `</tbody></table>`;
      html += `<div style="margin-top:0.5rem"><button class="heals-toolbar-btn primary" data-action="fix-drift"${writeLock ? " disabled" : ""}>Fix All Drift</button></div>`;
      html += `</div>`;
    }

    // Missing section
    if (scanResult.missing && scanResult.missing.length > 0) {
      html += `<div class="heals-scan-section">`;
      html += `<div class="heals-scan-subtitle">Missing Locations (${scanResult.missing.length})</div>`;
      const addable = scanResult.missing.filter(m => m.has_pc);
      for (const m of scanResult.missing) {
        const name = mapDisplay("MAP_" + folderToConst(m.folder));
        const typeShort = m.map_type.replace("MAP_TYPE_", "");
        html += `<div class="heals-missing-row">`;
        html += `<span class="heals-missing-name">${esc(name)}</span>`;
        html += `<span class="heals-missing-type">${esc(typeShort)}</span>`;
        html += `<span class="heals-missing-pc ${m.has_pc ? "yes" : "no"}">${m.has_pc ? "Has PC" : "No PC"}</span>`;
        if (m.has_pc) {
          html += `<button class="heals-btn-sm" data-auto-add="${esc(m.folder)}"${writeLock ? " disabled" : ""}>Add</button>`;
        }
        html += `</div>`;
      }
      if (addable.length > 1) {
        html += `<div style="margin-top:0.5rem"><button class="heals-toolbar-btn" data-action="auto-add-all"${writeLock ? " disabled" : ""}>Add All (${addable.length})</button></div>`;
      }
      html += `</div>`;
    }

    // Nurse issues section
    if (scanResult.nurse_issues && scanResult.nurse_issues.length > 0) {
      html += `<div class="heals-scan-section">`;
      html += `<div class="heals-scan-subtitle">Nurse Script Issues (${scanResult.nurse_issues.length})</div>`;
      const fixable = scanResult.nurse_issues.filter(n => n.fixable);
      for (const n of scanResult.nurse_issues) {
        const name = healIdToDisplay(n.id);
        const scriptLabel = n.script || "(empty)";
        html += `<div class="heals-missing-row">`;
        html += `<span class="heals-missing-name">${esc(name)}</span>`;
        html += `<span style="font-size:0.75rem;color:var(--text-dim)">${esc(n.respawn_folder)}</span>`;
        html += `<span style="font-size:0.7rem;color:#e85050;margin-left:0.5rem">${esc(scriptLabel)}</span>`;
        if (n.fixable) {
          html += `<button class="heals-btn-sm" data-fix-nurse="${esc(n.respawn_folder)}"${writeLock ? " disabled" : ""}>Fix</button>`;
        }
        html += `</div>`;
      }
      if (fixable.length > 1) {
        html += `<div style="margin-top:0.5rem"><button class="heals-toolbar-btn" data-action="fix-nurse-all"${writeLock ? " disabled" : ""}>Fix All (${fixable.length})</button></div>`;
      }
      html += `</div>`;
    }
  }

  html += `<div style="margin-top:0.75rem"><button class="heals-toolbar-btn" data-action="dismiss-scan">Dismiss</button></div>`;
  html += `</div>`;
  return html;
}

function renderConfirmDialog(healId) {
  const loc = allLocations.find(l => l.id === healId);
  const name = loc ? loc.display_name : healId;
  let html = `<div class="heals-confirm-overlay" id="heals-confirm">`;
  html += `<div class="heals-confirm-box">`;
  html += `<div class="heals-confirm-title">Delete Heal Location</div>`;
  html += `<div class="heals-confirm-text">`;
  html += `Are you sure you want to delete <strong>${esc(name)}</strong>?<br><br>`;
  html += `If this is the player's last save location, they will respawn at the default location (Littleroot Town) after blacking out.`;
  html += `</div>`;
  html += `<div class="heals-confirm-actions">`;
  html += `<button class="heals-toolbar-btn" data-action="cancel-delete">Cancel</button>`;
  html += `<button class="heals-btn-danger" data-action="confirm-delete" data-heal-id="${esc(healId)}">Delete</button>`;
  html += `</div>`;
  html += `</div></div>`;
  return html;
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function healIdToDisplay(id) {
  let name = id;
  if (name.startsWith("HEAL_LOCATION_")) name = name.substring(14);
  return name.split("_").map(p => /^[0-9]+[A-Z]+$/.test(p) ? p : p.charAt(0) + p.slice(1).toLowerCase()).join(" ");
}

function folderToConst(folder) {
  // PascalCase -> UPPER_SNAKE (simple heuristic)
  return folder.replace(/([a-z])([A-Z])/g, "$1_$2").toUpperCase();
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadLocations() {
  const res = await api("/heals");
  if (res.ok) {
    allLocations = res.data.locations;
  } else {
    allLocations = [];
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function doDetect() {
  const mapInput = document.getElementById("heal-add-map");
  if (!mapInput || !mapInput.value.trim()) return;
  writeLock = true;
  fullRender();
  try {
    const res = await api(`/heals/detect?map=${encodeURIComponent(mapInput.value.trim())}`);
    if (res.ok) {
      detectResult = res.data;
    } else {
      detectResult = { coords: null, respawn_map: null, respawn_npc: null, warnings: [res.error || "Detection failed"] };
    }
  } catch (e) {
    detectResult = { coords: null, respawn_map: null, respawn_npc: null, warnings: ["Network error"] };
  }
  writeLock = false;
  fullRender();
}

async function doCreate() {
  if (writeLock) return;
  writeLock = true;

  let payload;
  if (addMode === "pokecenter") {
    const mapInput = document.getElementById("heal-add-map");
    const folder = mapInput ? mapInput.value.trim() : "";
    if (!folder) { writeLock = false; return; }
    const mapConst = "MAP_" + folderToConst(folder);
    const healId = "HEAL_LOCATION_" + folderToConst(folder);
    const xEl = document.getElementById("heal-add-x");
    const yEl = document.getElementById("heal-add-y");
    const respawnEl = document.getElementById("heal-add-respawn");
    const npcEl = document.getElementById("heal-add-npc");
    const x = xEl ? parseInt(xEl.value, 10) : NaN;
    const y = yEl ? parseInt(yEl.value, 10) : NaN;
    if (isNaN(x) || isNaN(y)) { writeLock = false; fullRender(); return; }
    payload = { id: healId, map: mapConst, x, y };
    if (respawnEl && respawnEl.value.trim()) payload.respawn_map = respawnEl.value.trim();
    if (npcEl && npcEl.value.trim()) payload.respawn_npc = npcEl.value.trim();
  } else {
    const idEl = document.getElementById("heal-add-id");
    const mapEl = document.getElementById("heal-add-map-const");
    const xEl = document.getElementById("heal-add-x");
    const yEl = document.getElementById("heal-add-y");
    const respawnEl = document.getElementById("heal-add-respawn");
    const npcEl = document.getElementById("heal-add-npc");
    const healId = idEl ? idEl.value.trim() : "";
    const mapConst = mapEl ? mapEl.value.trim() : "";
    const x = xEl ? parseInt(xEl.value, 10) : NaN;
    const y = yEl ? parseInt(yEl.value, 10) : NaN;
    if (!healId || !mapConst || isNaN(x) || isNaN(y)) { writeLock = false; fullRender(); return; }
    payload = { id: healId, map: mapConst, x, y };
    if (respawnEl && respawnEl.value.trim()) payload.respawn_map = respawnEl.value.trim();
    if (npcEl && npcEl.value.trim()) payload.respawn_npc = npcEl.value.trim();
  }

  try {
    const res = await postApi("/heals", payload);
    if (res.ok) {
      activePanel = "list";
      detectResult = null;
      await loadLocations();
      editTarget = res.data.created;
    }
  } catch (e) { /* ignore */ }
  writeLock = false;
  fullRender();
}

async function doSaveField(field) {
  if (writeLock || !editTarget) return;
  const inputEl = _container.querySelector(`[data-edit-field="${field}"]`);
  if (!inputEl) return;
  let value = inputEl.value.trim();
  if (field === "x" || field === "y") {
    value = parseInt(value, 10);
    if (isNaN(value) || value < 0) return;
  }
  writeLock = true;
  try {
    const res = await postApi(`/heals/${encodeURIComponent(editTarget)}`, { field, value });
    if (res.ok) {
      editField = null;
      await loadLocations();
    }
  } catch (e) { /* ignore */ }
  writeLock = false;
  fullRender();
}

async function doDelete(healId) {
  if (writeLock) return;
  writeLock = true;
  try {
    const res = await postApi(`/heals/${encodeURIComponent(healId)}/delete`, {});
    if (res.ok) {
      editTarget = null;
      editField = null;
      await loadLocations();
    }
  } catch (e) { /* ignore */ }
  writeLock = false;
  // Remove confirm dialog
  const overlay = document.getElementById("heals-confirm");
  if (overlay) overlay.remove();
  fullRender();
}

async function doScan() {
  if (writeLock) return;
  writeLock = true;
  fullRender();
  try {
    const res = await postApi("/heals/scan", {});
    if (res.ok) {
      scanResult = res.data;
      activePanel = "scan";
    }
  } catch (e) { /* ignore */ }
  writeLock = false;
  fullRender();
}

async function doFixDrift() {
  if (writeLock) return;
  writeLock = true;
  try {
    const res = await postApi("/heals/fix-drift", {});
    if (res.ok) {
      scanResult = null;
      activePanel = "list";
      await loadLocations();
    }
  } catch (e) { /* ignore */ }
  writeLock = false;
  fullRender();
}

async function doAutoAdd(folders) {
  if (writeLock) return;
  writeLock = true;
  try {
    const res = await postApi("/heals/auto-add", { folders });
    if (res.ok) {
      scanResult = null;
      activePanel = "list";
      await loadLocations();
    }
  } catch (e) { /* ignore */ }
  writeLock = false;
  fullRender();
}

async function doFixNurse(folders) {
  if (writeLock) return;
  writeLock = true;
  try {
    const res = await postApi("/heals/fix-nurse", { folders });
    if (res.ok) {
      // Re-scan to refresh nurse issues
      const scanRes = await postApi("/heals/scan", {});
      if (scanRes.ok) {
        scanResult = scanRes.data;
      }
      await loadLocations();
    }
  } catch (e) { /* ignore */ }
  writeLock = false;
  fullRender();
}

async function doDetectEdit() {
  if (writeLock || !editTarget) return;
  const loc = allLocations.find(l => l.id === editTarget);
  if (!loc || !loc.map) return;
  // Derive folder from map constant
  let folder = loc.map;
  if (folder.startsWith("MAP_")) folder = folder.substring(4);
  // Simple UPPER_SNAKE -> PascalCase
  folder = folder.split("_").map(p => /^[0-9]+[A-Z]+$/.test(p) ? p : p.charAt(0) + p.slice(1).toLowerCase()).join("");

  writeLock = true;
  fullRender();
  try {
    const res = await api(`/heals/detect?map=${encodeURIComponent(folder)}`);
    if (res.ok && res.data.coords) {
      // Auto-save detected values
      await postApi(`/heals/${encodeURIComponent(editTarget)}`, { field: "x", value: res.data.coords.x });
      await postApi(`/heals/${encodeURIComponent(editTarget)}`, { field: "y", value: res.data.coords.y });
      if (res.data.respawn_map) {
        await postApi(`/heals/${encodeURIComponent(editTarget)}`, { field: "respawn_map", value: res.data.respawn_map });
      }
      if (res.data.respawn_npc) {
        await postApi(`/heals/${encodeURIComponent(editTarget)}`, { field: "respawn_npc", value: res.data.respawn_npc });
      }
      await loadLocations();
    }
  } catch (e) { /* ignore */ }
  writeLock = false;
  fullRender();
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function bindEvents() {
  if (!_container) return;

  // Toolbar buttons
  _container.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (btn) {
      const action = btn.dataset.action;
      if (action === "add") {
        activePanel = "add";
        addMode = "pokecenter";
        detectResult = null;
        fullRender();
      } else if (action === "scan") {
        await doScan();
      } else if (action === "cancel-add") {
        activePanel = "list";
        detectResult = null;
        fullRender();
      } else if (action === "detect") {
        await doDetect();
      } else if (action === "create") {
        await doCreate();
      } else if (action === "delete") {
        // Show confirmation dialog
        if (editTarget) {
          _container.insertAdjacentHTML("beforeend", renderConfirmDialog(editTarget));
        }
      } else if (action === "confirm-delete") {
        const healId = btn.dataset.healId;
        if (healId) await doDelete(healId);
      } else if (action === "cancel-delete") {
        const overlay = document.getElementById("heals-confirm");
        if (overlay) overlay.remove();
      } else if (action === "detect-edit") {
        await doDetectEdit();
      } else if (action === "fix-drift") {
        await doFixDrift();
      } else if (action === "dismiss-scan") {
        scanResult = null;
        activePanel = "list";
        fullRender();
      } else if (action === "auto-add-all") {
        if (scanResult && scanResult.missing) {
          const folders = scanResult.missing.filter(m => m.has_pc).map(m => m.folder);
          await doAutoAdd(folders);
        }
      } else if (action === "fix-nurse-all") {
        if (scanResult && scanResult.nurse_issues) {
          const folders = scanResult.nurse_issues.filter(n => n.fixable).map(n => n.respawn_folder);
          await doFixNurse(folders);
        }
      }
      return;
    }

    // Fix single nurse
    const fixNurseBtn = e.target.closest("[data-fix-nurse]");
    if (fixNurseBtn) {
      await doFixNurse([fixNurseBtn.dataset.fixNurse]);
      return;
    }

    // Auto-add single
    const autoAddBtn = e.target.closest("[data-auto-add]");
    if (autoAddBtn) {
      await doAutoAdd([autoAddBtn.dataset.autoAdd]);
      return;
    }

    // Mode toggle
    const modeBtn = e.target.closest("[data-mode]");
    if (modeBtn) {
      addMode = modeBtn.dataset.mode;
      detectResult = null;
      fullRender();
      return;
    }

    // Save field
    const saveBtn = e.target.closest("[data-save-field]");
    if (saveBtn) {
      await doSaveField(saveBtn.dataset.saveField);
      return;
    }

    // Cancel edit
    const cancelBtn = e.target.closest("[data-cancel-edit]");
    if (cancelBtn) {
      editField = null;
      fullRender();
      return;
    }

    // Click field to edit
    const fieldVal = e.target.closest("[data-click-field]");
    if (fieldVal) {
      editField = fieldVal.dataset.clickField;
      fullRender();
      return;
    }

    // Table row click
    const row = e.target.closest("tr[data-heal-id]");
    if (row) {
      const id = row.dataset.healId;
      if (editTarget === id) {
        editTarget = null;
        editField = null;
        activePanel = "list";
      } else {
        editTarget = id;
        editField = null;
        activePanel = "edit";
      }
      fullRender();
      return;
    }

    // Confirm overlay click-outside
    const overlay = document.getElementById("heals-confirm");
    if (overlay && e.target === overlay) {
      overlay.remove();
    }
  });

  // Enter key in edit field
  _container.addEventListener("keydown", async (e) => {
    if (e.key === "Enter") {
      const input = e.target.closest("[data-edit-field]");
      if (input) {
        await doSaveField(input.dataset.editField);
      }
    }
    if (e.key === "Escape") {
      const input = e.target.closest("[data-edit-field]");
      if (input) {
        editField = null;
        fullRender();
      }
    }
  });
}

function fullRender() {
  if (!_container) return;
  let html = renderStudioNavbar("Heals");
  html += renderToolbar();
  html += renderTable();

  if (activePanel === "edit" && editTarget) {
    html += renderEditPanel();
  } else if (activePanel === "add") {
    html += renderAddPanel();
  }

  if (activePanel === "scan" || scanResult) {
    html += renderScanPanel();
  }

  _container.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function render(container) {
  _container = container;
  injectCSS();
  await loadLocations();
  fullRender();
  bindEvents();
}

export function cleanup() {
  _container = null;
  allLocations = [];
  editTarget = null;
  editField = null;
  activePanel = "list";
  addMode = "pokecenter";
  detectResult = null;
  scanResult = null;
  writeLock = false;
  if (styleEl) {
    styleEl.remove();
    styleEl = null;
  }
}
