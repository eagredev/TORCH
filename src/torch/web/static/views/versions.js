/**
 * TORCH Web GUI — Game Versions view.
 *
 * Manual version control for ROM hack projects. Save, restore, bump, delete.
 * Cards showing version label, date, ROM tag, size. Permanent snapshots
 * that are never auto-deleted.
 */

import { api, postApi, deleteApi } from "../app.js";
import { esc, createModal } from "../utils.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _container = null;
let versionsData = null;     // {versions, next_version, disk_usage_mb, version_count}
let saving = false;
let restoring = false;

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

const STYLE_ID = "versions-view-css";

function injectCSS() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    /* Header bar */
    .ver-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1.25rem;
    }
    .ver-header h2 {
      margin: 0;
      font-size: 1.15rem;
      color: #eee;
    }
    .ver-stats {
      display: flex;
      gap: 1rem;
      font-size: 0.75rem;
      color: var(--text-dim);
    }
    .ver-stat-value {
      color: var(--accent);
      font-weight: 600;
      font-family: monospace;
    }

    /* Action bar */
    .ver-actions {
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
      margin-bottom: 1.25rem;
    }
    .ver-btn {
      padding: 0.35rem 0.75rem;
      font-size: 0.78rem;
      border-radius: 4px;
      border: 1px solid var(--accent);
      background: transparent;
      color: var(--accent);
      cursor: pointer;
      transition: background 0.15s, color 0.15s;
      font-weight: 500;
    }
    .ver-btn:hover:not([disabled]) {
      background: var(--accent);
      color: #111;
    }
    .ver-btn[disabled] {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .ver-btn--danger {
      border-color: var(--status-error);
      color: var(--status-error);
    }
    .ver-btn--danger:hover:not([disabled]) {
      background: var(--status-error);
      color: #111;
    }
    .ver-btn--secondary {
      border-color: var(--border-emphasis);
      color: var(--text-secondary);
    }
    .ver-btn--secondary:hover:not([disabled]) {
      background: var(--border-emphasis);
      color: #eee;
    }

    /* Empty state */
    .ver-empty {
      text-align: center;
      padding: 3rem 1rem;
      color: var(--text-dim);
    }
    .ver-empty p { margin: 0.5rem 0; }
    .ver-empty .ver-empty-cta {
      margin-top: 1rem;
    }

    /* Version cards */
    .ver-list {
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }
    .ver-card {
      background: var(--surface-2);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 0.75rem 1rem;
      transition: border-color 0.15s;
    }
    .ver-card:hover {
      border-color: var(--border-emphasis);
    }
    .ver-card-top {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      flex-wrap: wrap;
    }
    .ver-card-version {
      font-family: monospace;
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--accent);
      min-width: 3.5rem;
    }
    .ver-card-label {
      font-weight: 600;
      color: #eee;
      font-size: 0.88rem;
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .ver-card-badges {
      display: flex;
      gap: 0.4rem;
      align-items: center;
    }
    .ver-badge {
      display: inline-block;
      font-size: 0.62rem;
      padding: 0.1rem 0.4rem;
      border-radius: 3px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .ver-badge-rom {
      background: rgba(76,175,80,0.15);
      color: #4caf50;
      border: 1px solid rgba(76,175,80,0.3);
    }
    .ver-badge-no-rom {
      background: rgba(102,102,102,0.15);
      color: #888;
      border: 1px solid rgba(102,102,102,0.3);
    }
    .ver-card-meta {
      display: flex;
      gap: 1rem;
      font-size: 0.72rem;
      color: var(--text-dim);
      margin-top: 0.35rem;
      flex-wrap: wrap;
    }
    .ver-card-notes {
      font-size: 0.72rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
      font-style: italic;
    }
    .ver-card-actions {
      display: flex;
      gap: 0.4rem;
      margin-top: 0.5rem;
    }
    .ver-card-btn {
      padding: 0.2rem 0.5rem;
      font-size: 0.68rem;
      border-radius: 3px;
      border: 1px solid var(--border-emphasis);
      background: transparent;
      color: var(--text-secondary);
      cursor: pointer;
      transition: background 0.15s, color 0.15s;
    }
    .ver-card-btn:hover:not([disabled]) {
      background: var(--surface-3, rgba(255,255,255,0.06));
      color: #eee;
    }
    .ver-card-btn--restore {
      border-color: var(--accent);
      color: var(--accent);
    }
    .ver-card-btn--restore:hover:not([disabled]) {
      background: var(--accent);
      color: #111;
    }
    .ver-card-btn--delete {
      border-color: transparent;
      color: var(--text-dim);
    }
    .ver-card-btn--delete:hover:not([disabled]) {
      border-color: var(--status-error);
      color: var(--status-error);
    }

    /* Save modal */
    .ver-save-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.6);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
    }
    .ver-save-modal {
      background: var(--surface-1);
      border: 1px solid var(--border-emphasis);
      border-radius: 8px;
      padding: 1.5rem;
      width: 380px;
      max-width: 90vw;
    }
    .ver-save-modal h3 {
      margin: 0 0 1rem;
      font-size: 1rem;
      color: #eee;
    }
    .ver-save-modal label {
      display: block;
      font-size: 0.78rem;
      color: var(--text-secondary);
      margin-bottom: 0.25rem;
    }
    .ver-save-modal input,
    .ver-save-modal textarea {
      width: 100%;
      padding: 0.4rem 0.6rem;
      font-size: 0.82rem;
      background: var(--surface-2);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      color: #eee;
      outline: none;
      margin-bottom: 0.75rem;
      box-sizing: border-box;
    }
    .ver-save-modal input:focus,
    .ver-save-modal textarea:focus {
      border-color: var(--accent);
    }
    .ver-save-modal textarea {
      resize: vertical;
      min-height: 3rem;
      font-family: inherit;
    }
    .ver-save-modal .ver-modal-actions {
      display: flex;
      gap: 0.5rem;
      justify-content: flex-end;
      margin-top: 0.5rem;
    }

    /* Restore modal */
    .ver-restore-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.6);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
    }
    .ver-restore-modal {
      background: var(--surface-1);
      border: 1px solid var(--border-emphasis);
      border-radius: 8px;
      padding: 1.5rem;
      width: 340px;
      max-width: 90vw;
    }
    .ver-restore-modal h3 {
      margin: 0 0 0.75rem;
      font-size: 1rem;
      color: #eee;
    }
    .ver-restore-option {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.5rem 0;
      font-size: 0.82rem;
      color: var(--text-secondary);
      cursor: pointer;
    }
    .ver-restore-option input[type="checkbox"] {
      margin: 0;
      accent-color: var(--accent);
    }
    .ver-restore-modal .ver-modal-actions {
      display: flex;
      gap: 0.5rem;
      justify-content: flex-end;
      margin-top: 1rem;
    }

    /* Delete confirmation */
    .ver-delete-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.6);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
    }
    .ver-delete-modal {
      background: var(--surface-1);
      border: 1px solid var(--status-error);
      border-radius: 8px;
      padding: 1.5rem;
      width: 340px;
      max-width: 90vw;
    }
    .ver-delete-modal h3 {
      margin: 0 0 0.5rem;
      font-size: 1rem;
      color: var(--status-error);
    }
    .ver-delete-modal p {
      font-size: 0.82rem;
      color: var(--text-secondary);
      margin: 0 0 1rem;
    }
    .ver-delete-modal .ver-modal-actions {
      display: flex;
      gap: 0.5rem;
      justify-content: flex-end;
    }

    /* Bump confirmation */
    .ver-bump-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.6);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
    }
    .ver-bump-modal {
      background: var(--surface-1);
      border: 1px solid var(--border-emphasis);
      border-radius: 8px;
      padding: 1.5rem;
      width: 340px;
      max-width: 90vw;
    }
    .ver-bump-modal h3 {
      margin: 0 0 0.5rem;
      font-size: 1rem;
      color: #eee;
    }
    .ver-bump-modal p {
      font-size: 0.82rem;
      color: var(--text-secondary);
      margin: 0 0 1rem;
    }
    .ver-bump-modal .ver-modal-actions {
      display: flex;
      gap: 0.5rem;
      justify-content: flex-end;
    }

    /* Toast notification */
    .ver-toast {
      position: fixed;
      bottom: 3.5rem;
      right: 1rem;
      background: var(--surface-1);
      border: 1px solid var(--accent);
      border-radius: 6px;
      padding: 0.6rem 1rem;
      font-size: 0.8rem;
      color: #eee;
      z-index: 2000;
      animation: ver-toast-in 0.2s ease-out;
    }
    .ver-toast--error {
      border-color: var(--status-error);
    }
    @keyframes ver-toast-in {
      from { opacity: 0; transform: translateY(0.5rem); }
      to { opacity: 1; transform: translateY(0); }
    }
  `;
  document.body.appendChild(style);
}


// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadVersions() {
  try {
    const resp = await api("/versions");
    if (resp.ok) {
      versionsData = resp.data;
    }
  } catch (err) {
    console.error("Failed to load versions:", err);
  }
}


// ---------------------------------------------------------------------------
// Toast helper
// ---------------------------------------------------------------------------

function showToast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "ver-toast" + (isError ? " ver-toast--error" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}


// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderAll() {
  if (!_container || !versionsData) return;

  const versions = versionsData.versions || [];
  const nextVer = versionsData.next_version || "0.1";
  const diskMb = versionsData.disk_usage_mb || 0;
  const count = versionsData.version_count || 0;

  let html = `
    <div class="ver-header">
      <h2>Game Versions</h2>
      <div class="ver-stats">
        <span>Next: <span class="ver-stat-value">${esc(nextVer)}</span></span>
        <span>Saved: <span class="ver-stat-value">${count}</span></span>
        <span>Disk: <span class="ver-stat-value">${diskMb.toFixed(1)} MB</span></span>
      </div>
    </div>
    <div class="ver-actions">
      <button class="ver-btn" id="ver-save-btn" ${saving ? "disabled" : ""}>
        ${saving ? "Saving..." : "Save Version"}
      </button>
      <button class="ver-btn ver-btn--secondary" id="ver-bump-btn">Bump Major</button>
    </div>
  `;

  if (versions.length === 0) {
    html += `
      <div class="ver-empty">
        <p>No versions saved yet.</p>
        <p>Save your first version to create a permanent checkpoint<br>
           of your game, ROM, and workspace.</p>
      </div>
    `;
  } else {
    html += `<div class="ver-list">`;
    for (const v of versions) {
      const label = v.label || "(unnamed)";
      const romBadge = v.rom_filename
        ? `<span class="ver-badge ver-badge-rom">ROM</span>`
        : `<span class="ver-badge ver-badge-no-rom">No ROM</span>`;
      const sizeMb = (v.size_bytes || 0) / (1024 * 1024);
      const notes = v.notes ? `<div class="ver-card-notes">${esc(v.notes)}</div>` : "";

      html += `
        <div class="ver-card" data-version="${esc(v.version)}">
          <div class="ver-card-top">
            <span class="ver-card-version">v${esc(v.version)}</span>
            <span class="ver-card-label">${esc(label)}</span>
            <div class="ver-card-badges">${romBadge}</div>
          </div>
          <div class="ver-card-meta">
            <span>${esc(v.display_time || v.timestamp || "")}</span>
            <span>${v.file_count || 0} files</span>
            <span>${sizeMb.toFixed(1)} MB</span>
            ${v.torch_version ? `<span>TORCH v${esc(v.torch_version)}</span>` : ""}
            ${v.expansion_version ? `<span>Exp v${esc(v.expansion_version)}</span>` : ""}
          </div>
          ${notes}
          <div class="ver-card-actions">
            <button class="ver-card-btn ver-card-btn--restore" data-action="restore" data-version="${esc(v.version)}">
              Restore
            </button>
            <button class="ver-card-btn" data-action="info" data-version="${esc(v.version)}">
              Info
            </button>
            <button class="ver-card-btn ver-card-btn--delete" data-action="delete" data-version="${esc(v.version)}">
              Delete
            </button>
          </div>
        </div>
      `;
    }
    html += `</div>`;
  }

  _container.innerHTML = html;
  bindEvents();
}


// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function bindEvents() {
  // Save button
  const saveBtn = document.getElementById("ver-save-btn");
  if (saveBtn) {
    saveBtn.addEventListener("click", openSaveModal);
  }

  // Bump button
  const bumpBtn = document.getElementById("ver-bump-btn");
  if (bumpBtn) {
    bumpBtn.addEventListener("click", openBumpModal);
  }

  // Card action buttons
  _container.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", (e) => {
      const action = btn.dataset.action;
      const version = btn.dataset.version;
      if (action === "restore") openRestoreModal(version);
      else if (action === "info") openInfoModal(version);
      else if (action === "delete") openDeleteModal(version);
    });
  });
}


// ---------------------------------------------------------------------------
// Save modal
// ---------------------------------------------------------------------------

function openSaveModal() {
  const nextVer = versionsData?.next_version || "?";
  const { el, close } = createModal("ver-save-modal", `
    <h3>Save Version v${esc(nextVer)}</h3>
    <label for="ver-label">Label</label>
    <input type="text" id="ver-label-input" placeholder="e.g. First gym complete" autofocus>
    <label for="ver-notes">Notes (optional)</label>
    <textarea id="ver-notes-input" rows="2" placeholder="What changed in this version?"></textarea>
    <div class="ver-modal-actions">
      <button class="ver-btn ver-btn--secondary ver-cancel-btn">Cancel</button>
      <button class="ver-btn ver-confirm-save-btn">Save</button>
    </div>
  `);

  el.querySelector(".ver-cancel-btn").addEventListener("click", close);
  el.querySelector(".ver-confirm-save-btn").addEventListener("click", async () => {
    const label = el.querySelector("#ver-label-input").value.trim();
    const notes = el.querySelector("#ver-notes-input").value.trim();
    const btn = el.querySelector(".ver-confirm-save-btn");
    btn.disabled = true;
    btn.textContent = "Saving...";
    saving = true;

    try {
      const resp = await postApi("/versions", { label, notes });
      if (resp.ok) {
        close();
        showToast(`Saved v${resp.data.version} (${resp.data.size_mb} MB)`);
        await loadVersions();
        renderAll();
      } else {
        showToast(resp.error || "Failed to save version", true);
        btn.disabled = false;
        btn.textContent = "Save";
      }
    } catch (err) {
      showToast("Error: " + err.message, true);
      btn.disabled = false;
      btn.textContent = "Save";
    } finally {
      saving = false;
    }
  });

  // Focus label input
  setTimeout(() => el.querySelector("#ver-label-input")?.focus(), 50);
}


// ---------------------------------------------------------------------------
// Restore modal
// ---------------------------------------------------------------------------

function openRestoreModal(versionStr) {
  const v = (versionsData?.versions || []).find(x => x.version === versionStr);
  if (!v) return;

  const label = v.label || "(unnamed)";
  const { el, close } = createModal("ver-restore-modal", `
    <h3>Restore v${esc(versionStr)}</h3>
    <p style="font-size:0.8rem;color:var(--text-dim);margin:0 0 0.75rem">${esc(label)}</p>
    <label class="ver-restore-option">
      <input type="checkbox" id="ver-r-game" checked> Game source files
    </label>
    <label class="ver-restore-option">
      <input type="checkbox" id="ver-r-rom" checked ${v.rom_filename ? "" : "disabled"}>
      ROM binary ${v.rom_filename ? "" : "(not included)"}
    </label>
    <label class="ver-restore-option">
      <input type="checkbox" id="ver-r-workspace" checked> TORCH workspace
    </label>
    <div class="ver-modal-actions">
      <button class="ver-btn ver-btn--secondary ver-cancel-btn">Cancel</button>
      <button class="ver-btn ver-card-btn--restore ver-confirm-restore-btn">Restore</button>
    </div>
  `);

  el.querySelector(".ver-cancel-btn").addEventListener("click", close);
  el.querySelector(".ver-confirm-restore-btn").addEventListener("click", async () => {
    const game = el.querySelector("#ver-r-game").checked;
    const rom = el.querySelector("#ver-r-rom").checked;
    const workspace = el.querySelector("#ver-r-workspace").checked;

    if (!game && !rom && !workspace) {
      showToast("Select at least one category to restore", true);
      return;
    }

    const btn = el.querySelector(".ver-confirm-restore-btn");
    btn.disabled = true;
    btn.textContent = "Restoring...";
    restoring = true;

    try {
      const resp = await postApi(`/versions/${versionStr}/restore`, { game, rom, workspace });
      if (resp.ok) {
        close();
        showToast(`Restored v${versionStr} (${resp.data.file_count} files)`);
      } else {
        showToast(resp.error || "Restore failed", true);
        btn.disabled = false;
        btn.textContent = "Restore";
      }
    } catch (err) {
      showToast("Error: " + err.message, true);
      btn.disabled = false;
      btn.textContent = "Restore";
    } finally {
      restoring = false;
    }
  });
}


// ---------------------------------------------------------------------------
// Info modal
// ---------------------------------------------------------------------------

function openInfoModal(versionStr) {
  const v = (versionsData?.versions || []).find(x => x.version === versionStr);
  if (!v) return;

  const sizeMb = (v.size_bytes || 0) / (1024 * 1024);
  const romMb = (v.rom_size_bytes || 0) / (1024 * 1024);
  const label = v.label || "(unnamed)";

  const { el, close } = createModal("ver-save-modal", `
    <h3>Version v${esc(versionStr)}</h3>
    <table style="width:100%;font-size:0.82rem;border-collapse:collapse">
      <tr><td style="color:var(--text-dim);padding:0.25rem 0.5rem 0.25rem 0">Label</td>
          <td style="color:#eee;padding:0.25rem 0">${esc(label)}</td></tr>
      <tr><td style="color:var(--text-dim);padding:0.25rem 0.5rem 0.25rem 0">Saved</td>
          <td style="padding:0.25rem 0">${esc(v.display_time || v.timestamp || "")}</td></tr>
      <tr><td style="color:var(--text-dim);padding:0.25rem 0.5rem 0.25rem 0">Files</td>
          <td style="padding:0.25rem 0">${v.file_count || 0}</td></tr>
      <tr><td style="color:var(--text-dim);padding:0.25rem 0.5rem 0.25rem 0">Size</td>
          <td style="padding:0.25rem 0">${sizeMb.toFixed(1)} MB</td></tr>
      <tr><td style="color:var(--text-dim);padding:0.25rem 0.5rem 0.25rem 0">ROM</td>
          <td style="padding:0.25rem 0">${v.rom_filename
            ? `${esc(v.rom_filename)} (${romMb.toFixed(1)} MB)`
            : '<span style="color:var(--text-dim)">not included</span>'}</td></tr>
      <tr><td style="color:var(--text-dim);padding:0.25rem 0.5rem 0.25rem 0">TORCH</td>
          <td style="padding:0.25rem 0">v${esc(v.torch_version || "?")}</td></tr>
      ${v.expansion_version ? `
      <tr><td style="color:var(--text-dim);padding:0.25rem 0.5rem 0.25rem 0">Expansion</td>
          <td style="padding:0.25rem 0">v${esc(v.expansion_version)}</td></tr>` : ""}
      ${v.notes ? `
      <tr><td style="color:var(--text-dim);padding:0.25rem 0.5rem 0.25rem 0">Notes</td>
          <td style="padding:0.25rem 0;font-style:italic">${esc(v.notes)}</td></tr>` : ""}
    </table>
    <div class="ver-modal-actions" style="margin-top:1rem">
      <button class="ver-btn ver-btn--secondary ver-cancel-btn">Close</button>
    </div>
  `);

  el.querySelector(".ver-cancel-btn").addEventListener("click", close);
}


// ---------------------------------------------------------------------------
// Delete modal
// ---------------------------------------------------------------------------

function openDeleteModal(versionStr) {
  const v = (versionsData?.versions || []).find(x => x.version === versionStr);
  if (!v) return;

  const label = v.label || "(unnamed)";
  const { el, close } = createModal("ver-delete-modal", `
    <h3>Delete Version</h3>
    <p>Permanently delete <strong>v${esc(versionStr)}</strong> &mdash; ${esc(label)}?</p>
    <p style="font-size:0.75rem;color:var(--text-dim)">This cannot be undone.</p>
    <div class="ver-modal-actions">
      <button class="ver-btn ver-btn--secondary ver-cancel-btn">Cancel</button>
      <button class="ver-btn ver-btn--danger ver-confirm-delete-btn">Delete</button>
    </div>
  `);

  el.querySelector(".ver-cancel-btn").addEventListener("click", close);
  el.querySelector(".ver-confirm-delete-btn").addEventListener("click", async () => {
    const btn = el.querySelector(".ver-confirm-delete-btn");
    btn.disabled = true;
    btn.textContent = "Deleting...";

    try {
      const resp = await deleteApi(`/versions/${versionStr}`);
      if (resp.ok) {
        close();
        showToast(`Deleted v${versionStr}`);
        await loadVersions();
        renderAll();
      } else {
        showToast(resp.error || "Delete failed", true);
        btn.disabled = false;
        btn.textContent = "Delete";
      }
    } catch (err) {
      showToast("Error: " + err.message, true);
      btn.disabled = false;
      btn.textContent = "Delete";
    }
  });
}


// ---------------------------------------------------------------------------
// Bump major modal
// ---------------------------------------------------------------------------

function openBumpModal() {
  const nextVer = versionsData?.next_version || "?";
  // Parse current major from next_version
  const parts = nextVer.split(".");
  const currentMajor = parseInt(parts[0] || "0", 10);
  const newMajor = currentMajor + 1;

  const { el, close } = createModal("ver-bump-modal", `
    <h3>Bump Major Version</h3>
    <p>Current next version: <strong>v${esc(nextVer)}</strong></p>
    <p>After bump, next save will be: <strong>v${newMajor}.0</strong></p>
    <div class="ver-modal-actions">
      <button class="ver-btn ver-btn--secondary ver-cancel-btn">Cancel</button>
      <button class="ver-btn ver-confirm-bump-btn">Bump</button>
    </div>
  `);

  el.querySelector(".ver-cancel-btn").addEventListener("click", close);
  el.querySelector(".ver-confirm-bump-btn").addEventListener("click", async () => {
    const btn = el.querySelector(".ver-confirm-bump-btn");
    btn.disabled = true;
    btn.textContent = "Bumping...";

    try {
      const resp = await postApi("/versions/bump");
      if (resp.ok) {
        close();
        showToast(`Major version bumped to v${resp.data.new_version}`);
        await loadVersions();
        renderAll();
      } else {
        showToast(resp.error || "Bump failed", true);
        btn.disabled = false;
        btn.textContent = "Bump";
      }
    } catch (err) {
      showToast("Error: " + err.message, true);
      btn.disabled = false;
      btn.textContent = "Bump";
    }
  });
}


// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export async function render(container) {
  injectCSS();
  _container = container;
  container.innerHTML = `<div style="color:var(--text-dim);padding:2rem">Loading versions...</div>`;

  await loadVersions();
  renderAll();
}

export function cleanup() {
  _container = null;
  versionsData = null;
  saving = false;
  restoring = false;
}
