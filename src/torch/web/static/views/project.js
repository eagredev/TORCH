/**
 * TORCH Web GUI — Project page.
 *
 * Dedicated view for managing projects: switch, set favourite, view details.
 * Backup Vault and Fork Browser sections.
 * Extracted from settings.js.
 */

import { api, postApi, clearVersionCache } from "../app.js";
import { esc } from "../utils.js";

let projectsData = null;
let backupsData = null;
let forksData = null;
let backupDir = null;
let snapshotsData = null;
let workspaceMapsData = null;
let selectedWorkspaceMap = null;
let workspaceSnapshotsData = null;
let _relockHandler = null;

// ---------------------------------------------------------------------------
// Scoped CSS — injected once
// ---------------------------------------------------------------------------
const STYLE_ID = "project-view-css";

function injectCSS() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    /* Backups & Forks sections */
    .project-section { margin-top: 2rem; }
    .project-section h3 {
      font-size: 1rem;
      color: #eee;
      margin-bottom: 0.75rem;
      font-weight: 600;
    }

    /* Backup table */
    .backup-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
    }
    .backup-table th {
      text-align: left;
      padding: 0.4rem 0.6rem;
      color: var(--text-dim);
      font-weight: 500;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border-subtle);
    }
    .backup-table td {
      padding: 0.4rem 0.6rem;
      color: var(--text-secondary);
      border-bottom: 1px solid var(--border-subtle);
    }
    .backup-table tr:last-child td { border-bottom: none; }
    .backup-table tr:hover td { background: rgba(255,255,255,0.02); }
    .backup-filename {
      font-family: monospace;
      font-size: 0.75rem;
      max-width: 280px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    /* Tier badges */
    .tier-badge {
      display: inline-block;
      font-size: 0.65rem;
      padding: 0.1rem 0.4rem;
      border-radius: 3px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .tier-hot  { background: rgba(232,160,32,0.15); color: #e8a020; border: 1px solid rgba(232,160,32,0.3); }
    .tier-cold { background: rgba(74,158,255,0.15); color: #4a9eff; border: 1px solid rgba(74,158,255,0.3); }
    .tier-old  { background: rgba(102,102,102,0.15); color: #888; border: 1px solid rgba(102,102,102,0.3); }
    .tier-unknown { background: rgba(68,68,68,0.15); color: #555; border: 1px solid rgba(68,68,68,0.3); }

    /* Version badge (backups) */
    .backup-version {
      display: inline-block;
      font-size: 0.65rem;
      padding: 0.1rem 0.35rem;
      border-radius: 3px;
      background: var(--accent-bg-faint);
      color: var(--accent);
      border: 1px solid var(--accent-border-faint);
      font-family: monospace;
    }

    /* Tier legend */
    .tier-legend {
      font-size: 0.7rem;
      color: var(--text-dim);
      margin-bottom: 0.75rem;
      display: flex;
      gap: 1rem;
      flex-wrap: wrap;
    }
    .tier-legend-item { display: flex; align-items: center; gap: 0.3rem; }

    /* Create backup inline form */
    .backup-create-bar {
      display: flex;
      gap: 0.5rem;
      align-items: center;
      margin-bottom: 0.75rem;
    }
    .backup-tag-input {
      padding: 0.25rem 0.5rem;
      font-size: 0.75rem;
      border: 1px solid var(--border-emphasis);
      border-radius: 3px;
      background: var(--surface-1);
      color: var(--text-secondary);
      width: 180px;
    }
    .backup-tag-input:focus {
      outline: none;
      border-color: var(--accent);
    }
    .backup-create-btn {
      padding: 0.25rem 0.6rem;
      font-size: 0.72rem;
      border-radius: 3px;
      border: 1px solid var(--accent);
      background: transparent;
      color: var(--accent);
      cursor: pointer;
    }
    .backup-create-btn:hover:not([disabled]) {
      background: var(--accent);
      color: #111;
    }
    .backup-create-btn[disabled] {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .backup-dir-path {
      font-size: 0.7rem;
      color: var(--text-dim);
      font-family: monospace;
      margin-top: 0.5rem;
    }

    /* Fork cards */
    .fork-card {
      background: var(--surface-2);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 0.75rem 1rem;
      transition: border-color 0.15s;
      margin-bottom: 0.5rem;
    }
    .fork-card:hover { border-color: var(--border-emphasis); }
    .fork-card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
    }
    .fork-card-name {
      font-weight: 600;
      color: #eee;
      font-size: 0.9rem;
    }
    .fork-card-meta {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 0.2rem;
    }
    .fork-card-path {
      font-size: 0.72rem;
      color: #777;
      font-family: monospace;
      margin-top: 0.15rem;
    }
    .fork-exists-dot {
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      margin-right: 0.3rem;
      vertical-align: middle;
    }
    .fork-exists-ok { background: var(--status-ok); }
    .fork-exists-missing { background: var(--status-error); }
    .fork-card-actions {
      display: flex;
      gap: 0.5rem;
      align-items: center;
    }

    /* Tools section */
    .project-tools-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 0.75rem;
    }
    .project-tool-card {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0.75rem 1rem;
      background: var(--surface-2);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      cursor: pointer;
      text-decoration: none;
      transition: border-color 0.15s, background 0.15s;
    }
    .project-tool-card:hover {
      border-color: var(--border-emphasis);
      background: rgba(255,255,255,0.03);
    }
    .project-tool-icon {
      font-size: 1.4rem;
      line-height: 1;
      flex-shrink: 0;
    }
    .project-tool-label {
      font-weight: 600;
      color: #eee;
      font-size: 0.85rem;
    }
    .project-tool-desc {
      font-size: 0.72rem;
      color: var(--text-dim);
      margin-top: 0.1rem;
    }

    /* Empty states */
    .project-empty-state {
      color: var(--text-muted);
      font-size: 0.85rem;
      padding: 1rem;
      text-align: center;
      border: 1px dashed var(--border-subtle);
      border-radius: 6px;
    }
    .project-empty-state code {
      background: var(--surface-2);
      padding: 0.15rem 0.35rem;
      border-radius: 3px;
      font-size: 0.8rem;
    }

    /* Create backup feedback */
    .backup-feedback {
      font-size: 0.75rem;
      margin-left: 0.5rem;
    }
    .backup-feedback-ok { color: var(--status-ok); }
    .backup-feedback-err { color: var(--status-error); }

    /* Snapshot tables (build + workspace) */
    .snapshot-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
    }
    .snapshot-table th {
      text-align: left;
      padding: 0.4rem 0.6rem;
      color: var(--text-dim);
      font-weight: 500;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border-subtle);
    }
    .snapshot-table td {
      padding: 0.4rem 0.6rem;
      color: var(--text-secondary);
      border-bottom: 1px solid var(--border-subtle);
    }
    .snapshot-table tr:last-child td { border-bottom: none; }
    .snapshot-table tr:hover td { background: rgba(255,255,255,0.02); }
    .snapshot-trigger {
      display: inline-block;
      font-size: 0.65rem;
      padding: 0.1rem 0.4rem;
      border-radius: 3px;
      background: rgba(100,100,100,0.15);
      color: #aaa;
      border: 1px solid rgba(100,100,100,0.3);
    }
    .snapshot-pinned {
      display: inline-block;
      font-size: 0.65rem;
      padding: 0.1rem 0.4rem;
      border-radius: 3px;
      background: rgba(232,160,32,0.15);
      color: #e8a020;
      border: 1px solid rgba(232,160,32,0.3);
    }

    /* Restore button (used in both snapshot sections) */
    .snapshot-restore-btn {
      padding: 0.2rem 0.5rem;
      font-size: 0.7rem;
      border-radius: 3px;
      border: 1px solid var(--status-error);
      background: transparent;
      color: var(--status-error);
      cursor: pointer;
      opacity: 0.5;
      pointer-events: none;
      transition: opacity 0.15s;
    }
    .snapshot-restore-btn.unlocked {
      opacity: 1;
      pointer-events: auto;
    }
    .snapshot-restore-btn.unlocked:hover {
      background: var(--status-error);
      color: #111;
    }
    .snapshot-restore-btn[disabled] {
      opacity: 0.3;
      cursor: not-allowed;
      pointer-events: none;
    }
    .snapshot-padlock {
      padding: 0.2rem 0.4rem;
      font-size: 0.7rem;
      border: none;
      background: transparent;
      cursor: pointer;
      opacity: 0.6;
    }
    .snapshot-padlock:hover { opacity: 1; }

    /* Workspace map selector */
    .workspace-map-selector {
      display: flex;
      gap: 0.5rem;
      align-items: center;
      margin-bottom: 0.75rem;
      flex-wrap: wrap;
    }
    .workspace-map-select {
      padding: 0.25rem 0.5rem;
      font-size: 0.75rem;
      border: 1px solid var(--border-emphasis);
      border-radius: 3px;
      background: var(--surface-1);
      color: var(--text-secondary);
      min-width: 200px;
    }
    .workspace-map-select:focus {
      outline: none;
      border-color: var(--accent);
    }
    .workspace-map-count {
      font-size: 0.72rem;
      color: var(--text-dim);
    }

    /* Restore confirmation modal */
    .restore-confirm-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.6);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
    }
    .restore-confirm-modal {
      background: var(--surface-2);
      border: 1px solid var(--border-emphasis);
      border-radius: 8px;
      padding: 1.5rem;
      max-width: 400px;
      width: 90%;
    }
    .restore-confirm-modal h4 {
      color: var(--status-error);
      margin: 0 0 0.75rem 0;
      font-size: 0.95rem;
    }
    .restore-confirm-modal p {
      font-size: 0.8rem;
      color: var(--text-secondary);
      margin: 0 0 1rem 0;
    }
    .restore-confirm-input {
      width: 100%;
      padding: 0.35rem 0.5rem;
      font-size: 0.8rem;
      border: 1px solid var(--border-emphasis);
      border-radius: 3px;
      background: var(--surface-1);
      color: var(--text-secondary);
      margin-bottom: 1rem;
      box-sizing: border-box;
    }
    .restore-confirm-input:focus {
      outline: none;
      border-color: var(--accent);
    }
    .restore-confirm-actions {
      display: flex;
      gap: 0.5rem;
      justify-content: flex-end;
    }
    .restore-confirm-cancel {
      padding: 0.3rem 0.75rem;
      font-size: 0.75rem;
      border-radius: 3px;
      border: 1px solid var(--border-emphasis);
      background: transparent;
      color: var(--text-secondary);
      cursor: pointer;
    }
    .restore-confirm-execute {
      padding: 0.3rem 0.75rem;
      font-size: 0.75rem;
      border-radius: 3px;
      border: 1px solid var(--status-error);
      background: transparent;
      color: var(--status-error);
      cursor: pointer;
    }
    .restore-confirm-execute:hover:not([disabled]) {
      background: var(--status-error);
      color: #111;
    }
    .restore-confirm-execute[disabled] {
      opacity: 0.4;
      cursor: not-allowed;
    }
  `;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadProjects() {
  const resp = await api("/config/projects");
  if (resp.ok) projectsData = resp.data.projects;
}

async function loadBackups() {
  try {
    const resp = await api("/project/backups");
    if (resp.ok) {
      backupsData = resp.data.backups || [];
      backupDir = resp.data.backup_dir || null;
    } else {
      backupsData = [];
      backupDir = null;
    }
  } catch {
    backupsData = [];
    backupDir = null;
  }
}

async function loadForks() {
  try {
    const resp = await api("/project/forks");
    if (resp.ok) {
      forksData = resp.data.forks || [];
    } else {
      forksData = [];
    }
  } catch {
    forksData = [];
  }
}

async function loadSnapshots() {
  try {
    const resp = await api("/vault/snapshots");
    if (resp.ok) {
      snapshotsData = resp.data.snapshots || [];
    } else {
      snapshotsData = [];
    }
  } catch {
    snapshotsData = [];
  }
}

async function loadWorkspaceMaps() {
  try {
    const resp = await api("/vault/workspace");
    if (resp.ok) {
      workspaceMapsData = resp.data.maps || [];
    } else {
      workspaceMapsData = [];
    }
  } catch {
    workspaceMapsData = [];
  }
}

async function loadWorkspaceSnapshots(mapName) {
  if (!mapName) {
    workspaceSnapshotsData = [];
    return;
  }
  try {
    const resp = await api(`/vault/workspace/${encodeURIComponent(mapName)}`);
    if (resp.ok) {
      workspaceSnapshotsData = resp.data.snapshots || [];
    } else {
      workspaceSnapshotsData = [];
    }
  } catch {
    workspaceSnapshotsData = [];
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBackupDate(dateStr) {
  if (!dateStr || dateStr.length !== 8) return dateStr || "?";
  const y = dateStr.slice(0, 4);
  const m = dateStr.slice(4, 6);
  const d = dateStr.slice(6, 8);
  return `${y}-${m}-${d}`;
}

function tierClass(tier) {
  if (tier === "hot") return "tier-hot";
  if (tier === "cold") return "tier-cold";
  if (tier === "old") return "tier-old";
  return "tier-unknown";
}

async function savePref(key, value, feedbackEl) {
  if (feedbackEl) {
    feedbackEl.disabled = true;
    if (feedbackEl.tagName === "BUTTON") feedbackEl.textContent = "Saving...";
  }

  try {
    const res = await fetch("/api/config/preferences", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ changes: [{ key, value }] }),
    });
    const data = await res.json();
    if (!data.ok && feedbackEl && feedbackEl.tagName === "BUTTON") {
      feedbackEl.textContent = data.error || "Error";
      setTimeout(() => { feedbackEl.textContent = "Set as Favourite"; feedbackEl.disabled = false; }, 2000);
    }
  } catch (err) {
    if (feedbackEl && feedbackEl.tagName === "BUTTON") {
      feedbackEl.textContent = "Error";
      setTimeout(() => { feedbackEl.textContent = "Set as Favourite"; feedbackEl.disabled = false; }, 2000);
    }
  }
}

// ---------------------------------------------------------------------------
// Project card (unchanged logic)
// ---------------------------------------------------------------------------

function renderProjectCard(container, proj) {
  const card = document.createElement("div");
  card.className = "project-card" + (proj.active ? " project-active" : "");
  const isActive = proj.active;

  const badges = [];
  if (isActive) badges.push(`<span class="project-badge project-badge-active">Active</span>`);
  if (proj.favourite) badges.push(`<span class="project-badge project-badge-fav">Favourite</span>`);

  const path = proj.game_path.replace(/^\/home\/[^/]+/, "~");

  card.innerHTML = `
    <div class="project-card-header">
      <span class="project-card-name">${esc(proj.name)}</span>
      <span class="project-card-badges">${badges.join(" ")}</span>
    </div>
    <div class="project-card-path">${esc(path)}</div>
    <div class="project-card-actions">
      ${isActive
        ? `<button class="project-switch-btn project-switch-active" disabled>Active</button>`
        : `<button class="project-switch-btn" data-name="${esc(proj.name)}">Switch</button>`
      }
      ${!proj.favourite ? `<button class="project-fav-btn" data-name="${esc(proj.name)}">Set as Favourite</button>` : ""}
    </div>
  `;

  // Wire switch button
  const switchBtn = card.querySelector(".project-switch-btn:not([disabled])");
  if (switchBtn) {
    switchBtn.addEventListener("click", async () => {
      switchBtn.disabled = true;
      switchBtn.textContent = "Switching...";
      try {
        const resp = await postApi("/config/switch-project", { project: switchBtn.dataset.name });
        if (resp.ok) {
          clearVersionCache();
          window.location.reload();
        } else {
          switchBtn.textContent = resp.error || "Error";
          setTimeout(() => { switchBtn.textContent = "Switch"; switchBtn.disabled = false; }, 2000);
        }
      } catch {
        switchBtn.textContent = "Error";
        setTimeout(() => { switchBtn.textContent = "Switch"; switchBtn.disabled = false; }, 2000);
      }
    });
  }

  // Wire favourite button
  const favBtn = card.querySelector(".project-fav-btn");
  if (favBtn) {
    favBtn.addEventListener("click", async () => {
      await savePref("favourite_project", favBtn.dataset.name, favBtn);
      // Refresh data and re-render
      await loadProjects();
      renderContent(container);
    });
  }

  // Padlock + Delete button for non-active projects
  if (!isActive) {
    const actionsDiv = card.querySelector(".project-card-actions");
    const deleteGroup = document.createElement("span");
    deleteGroup.className = "project-delete-group";

    const padlock = document.createElement("button");
    padlock.className = "project-padlock";
    padlock.textContent = "\u{1F512}";
    padlock.title = "Unlock to enable delete";

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "project-delete-btn";
    deleteBtn.textContent = "Delete";
    deleteBtn.disabled = true;
    deleteBtn.title = "Remove project from TORCH (game files are NOT deleted)";

    let unlocked = false;
    padlock.addEventListener("click", (e) => {
      e.stopPropagation();
      unlocked = !unlocked;
      padlock.textContent = unlocked ? "\u{1F513}" : "\u{1F512}";
      deleteBtn.disabled = !unlocked;
      deleteBtn.classList.toggle("project-delete-ready", unlocked);
    });

    const projectName = proj.name;
    deleteBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!unlocked) return;

      const confirmed = confirm(
        `Remove "${projectName}" from TORCH?\n\n` +
        `This will:\n` +
        `  - Remove the project from TORCH's configuration\n` +
        `  - The project will no longer appear in TORCH\n\n` +
        `This will NOT:\n` +
        `  - Delete any game files or project data\n` +
        `  - The project folder remains untouched\n\n` +
        `You can re-add it later with torch config.`
      );
      if (!confirmed) return;

      const doubleConfirm = confirm(
        `Final confirmation: Remove "${projectName}" from TORCH configuration?`
      );
      if (!doubleConfirm) return;

      deleteBtn.disabled = true;
      deleteBtn.textContent = "Deleting...";
      try {
        const res = await fetch("/api/config/delete-project", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_name: projectName }),
        });
        const data = await res.json();
        if (data.ok) {
          await loadProjects();
          renderContent(container);
        } else {
          alert(`Error: ${data.error || "Unknown error"}`);
          deleteBtn.textContent = "Delete";
          deleteBtn.disabled = false;
        }
      } catch (err) {
        alert(`Error: ${err.message}`);
        deleteBtn.textContent = "Delete";
        deleteBtn.disabled = false;
      }
    });

    deleteGroup.appendChild(padlock);
    deleteGroup.appendChild(deleteBtn);
    actionsDiv.appendChild(deleteGroup);
  }

  return card;
}

// ---------------------------------------------------------------------------
// Backups section
// ---------------------------------------------------------------------------

function renderBackupsSection(container) {
  const section = document.createElement("div");
  section.className = "project-section";
  section.innerHTML = `<h3>Backups</h3>`;

  // Create backup bar
  const bar = document.createElement("div");
  bar.className = "backup-create-bar";
  bar.innerHTML = `
    <input type="text" class="backup-tag-input" placeholder="Optional tag (e.g. pre-refactor)" maxlength="60">
    <button class="backup-create-btn">Create Backup</button>
    <span class="backup-feedback"></span>
  `;
  section.appendChild(bar);

  const tagInput = bar.querySelector(".backup-tag-input");
  const createBtn = bar.querySelector(".backup-create-btn");
  const feedback = bar.querySelector(".backup-feedback");

  createBtn.addEventListener("click", async () => {
    createBtn.disabled = true;
    createBtn.textContent = "Creating...";
    tagInput.disabled = true;
    feedback.textContent = "";
    feedback.className = "backup-feedback";
    try {
      const resp = await postApi("/project/backups/create", { tag: tagInput.value || "" });
      if (resp.ok) {
        feedback.textContent = "Backup created";
        feedback.className = "backup-feedback backup-feedback-ok";
        tagInput.value = "";
        // Refresh backup list
        await loadBackups();
        renderBackupTable(section);
      } else {
        feedback.textContent = resp.error || "Failed";
        feedback.className = "backup-feedback backup-feedback-err";
      }
    } catch (err) {
      feedback.textContent = "Error: " + err.message;
      feedback.className = "backup-feedback backup-feedback-err";
    }
    createBtn.disabled = false;
    createBtn.textContent = "Create Backup";
    tagInput.disabled = false;
  });

  // Tier legend
  const legend = document.createElement("div");
  legend.className = "tier-legend";
  legend.innerHTML = `
    <span class="tier-legend-item"><span class="tier-badge tier-hot">hot</span> Recent</span>
    <span class="tier-legend-item"><span class="tier-badge tier-cold">cold</span> Older</span>
    <span class="tier-legend-item"><span class="tier-badge tier-old">old</span> Archive</span>
  `;
  section.appendChild(legend);

  // Table placeholder
  const tableWrap = document.createElement("div");
  tableWrap.className = "backup-table-wrap";
  section.appendChild(tableWrap);

  container.appendChild(section);

  // Render the table
  renderBackupTable(section);
}

function renderBackupTable(section) {
  const wrap = section.querySelector(".backup-table-wrap");
  if (!wrap) return;

  if (!backupsData || backupsData.length === 0) {
    wrap.innerHTML = `<div class="project-empty-state">No backups yet. Create one to protect your work.</div>`;
  } else {
    let rows = "";
    for (const b of backupsData) {
      rows += `<tr>
        <td><span class="backup-filename" title="${esc(b.filename)}">${esc(b.filename)}</span></td>
        <td><span class="backup-version">${esc(b.version || "?")}</span></td>
        <td><span class="tier-badge ${tierClass(b.tier)}">${esc(b.tier || "?")}</span></td>
        <td>${esc(formatBackupDate(b.date))}</td>
        <td>${b.size_mb != null ? esc(b.size_mb.toFixed(1)) + " MB" : "?"}</td>
      </tr>`;
    }
    wrap.innerHTML = `
      <table class="backup-table">
        <thead><tr>
          <th>Filename</th><th>Version</th><th>Tier</th><th>Date</th><th>Size</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  // Backup directory path
  const existingPath = section.querySelector(".backup-dir-path");
  if (existingPath) existingPath.remove();
  if (backupDir) {
    const pathEl = document.createElement("div");
    pathEl.className = "backup-dir-path";
    pathEl.textContent = backupDir.replace(/^\/home\/[^/]+/, "~");
    section.appendChild(pathEl);
  }
}

// ---------------------------------------------------------------------------
// Restore confirmation modal (padlock pattern — type "restore" to confirm)
// ---------------------------------------------------------------------------

function showRestoreConfirmation(title, description, onConfirm) {
  const overlay = document.createElement("div");
  overlay.className = "restore-confirm-overlay";
  overlay.innerHTML = `
    <div class="restore-confirm-modal">
      <h4>${title}</h4>
      <p>${description}</p>
      <input type="text" class="restore-confirm-input" placeholder="Type &quot;restore&quot; to confirm" autocomplete="off">
      <div class="restore-confirm-actions">
        <button class="restore-confirm-cancel">Cancel</button>
        <button class="restore-confirm-execute" disabled>Restore</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const input = overlay.querySelector(".restore-confirm-input");
  const execBtn = overlay.querySelector(".restore-confirm-execute");
  const cancelBtn = overlay.querySelector(".restore-confirm-cancel");

  input.addEventListener("input", () => {
    execBtn.disabled = input.value.trim().toLowerCase() !== "restore";
  });

  cancelBtn.addEventListener("click", () => overlay.remove());
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.remove();
  });

  execBtn.addEventListener("click", async () => {
    if (input.value.trim().toLowerCase() !== "restore") return;
    execBtn.disabled = true;
    execBtn.textContent = "Restoring...";
    input.disabled = true;
    cancelBtn.disabled = true;
    try {
      await onConfirm();
    } finally {
      overlay.remove();
    }
  });

  input.focus();
}

// ---------------------------------------------------------------------------
// Build Snapshots section (verified build snapshots)
// ---------------------------------------------------------------------------

function renderBuildSnapshotsSection(container) {
  const section = document.createElement("div");
  section.className = "project-section";
  const count = snapshotsData ? snapshotsData.length : 0;
  section.innerHTML = `<h3>Build Snapshots (${count})</h3>`;

  const tableWrap = document.createElement("div");
  tableWrap.className = "snapshot-table-wrap";
  section.appendChild(tableWrap);

  container.appendChild(section);
  renderBuildSnapshotTable(section);
}

function renderBuildSnapshotTable(section) {
  const wrap = section.querySelector(".snapshot-table-wrap");
  if (!wrap) return;

  if (!snapshotsData || snapshotsData.length === 0) {
    wrap.innerHTML = `<div class="project-empty-state">No verified build snapshots. Build snapshots are created automatically after successful builds.</div>`;
    return;
  }

  let rows = "";
  for (const s of snapshotsData) {
    rows += `<tr>
      <td>${esc(s.date || "?")}</td>
      <td><span class="snapshot-trigger">${esc(s.trigger || "?")}</span></td>
      <td>${s.file_count != null ? s.file_count : "?"} files</td>
      <td>${s.size_mb != null ? s.size_mb.toFixed(1) + " MB" : "?"}</td>
      <td>
        <button class="snapshot-restore-btn unlocked" data-filename="${esc(s.filename)}">Restore</button>
      </td>
    </tr>`;
  }

  wrap.innerHTML = `
    <table class="snapshot-table">
      <thead><tr>
        <th>Date</th><th>Trigger</th><th>Files</th><th>Size</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  // Wire restore buttons
  wrap.querySelectorAll(".snapshot-restore-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const filename = btn.dataset.filename;
      showRestoreConfirmation(
        "Restore Build Snapshot",
        `This will overwrite game files with the contents of <strong>${esc(filename)}</strong>. This cannot be undone.`,
        async () => {
          try {
            const resp = await postApi("/vault/restore", { filename });
            if (resp.ok) {
              alert(`Restored ${resp.data.file_count} files from ${filename}.`);
            } else {
              alert(`Restore failed: ${resp.error || "Unknown error"}`);
            }
          } catch (err) {
            alert(`Restore failed: ${err.message}`);
          }
        }
      );
    });
  });
}

// ---------------------------------------------------------------------------
// Workspace Snapshots section (per-map)
// ---------------------------------------------------------------------------

function renderWorkspaceSnapshotsSection(outerContainer) {
  const section = document.createElement("div");
  section.className = "project-section";
  section.innerHTML = `<h3>Workspace Snapshots</h3>`;

  // Map selector bar
  const selectorBar = document.createElement("div");
  selectorBar.className = "workspace-map-selector";

  if (!workspaceMapsData || workspaceMapsData.length === 0) {
    section.appendChild(selectorBar);
    const empty = document.createElement("div");
    empty.className = "project-empty-state";
    empty.textContent = "No workspace snapshots found. Snapshots are created during sync operations.";
    section.appendChild(empty);
    outerContainer.appendChild(section);
    return;
  }

  const select = document.createElement("select");
  select.className = "workspace-map-select";
  select.innerHTML = `<option value="">Select a map...</option>` +
    workspaceMapsData.map(m =>
      `<option value="${esc(m.name)}" ${selectedWorkspaceMap === m.name ? "selected" : ""}>${esc(m.name)} (${m.count})</option>`
    ).join("");

  selectorBar.appendChild(select);

  const countLabel = document.createElement("span");
  countLabel.className = "workspace-map-count";
  countLabel.textContent = `${workspaceMapsData.length} map${workspaceMapsData.length !== 1 ? "s" : ""} with snapshots`;
  selectorBar.appendChild(countLabel);

  section.appendChild(selectorBar);

  // Snapshot list container
  const listWrap = document.createElement("div");
  listWrap.className = "workspace-snapshot-list-wrap";
  section.appendChild(listWrap);

  outerContainer.appendChild(section);

  // Wire select change
  select.addEventListener("change", async () => {
    selectedWorkspaceMap = select.value || null;
    if (selectedWorkspaceMap) {
      listWrap.innerHTML = `<p style="color:#888;font-size:0.8rem">Loading snapshots...</p>`;
      await loadWorkspaceSnapshots(selectedWorkspaceMap);
      renderWorkspaceSnapshotList(listWrap, selectedWorkspaceMap);
    } else {
      workspaceSnapshotsData = [];
      listWrap.innerHTML = "";
    }
  });

  // Initial render if map already selected
  if (selectedWorkspaceMap && workspaceSnapshotsData) {
    renderWorkspaceSnapshotList(listWrap, selectedWorkspaceMap);
  }
}

function renderWorkspaceSnapshotList(wrap, mapName) {
  if (!workspaceSnapshotsData || workspaceSnapshotsData.length === 0) {
    wrap.innerHTML = `<div class="project-empty-state">No snapshots for ${esc(mapName)}.</div>`;
    return;
  }

  let rows = "";
  for (const s of workspaceSnapshotsData) {
    const pinnedBadge = s.pinned ? `<span class="snapshot-pinned">pinned</span>` : "";
    rows += `<tr>
      <td>${esc(s.date || "?")}</td>
      <td>${s.file_count != null ? s.file_count : "?"} files</td>
      <td>${s.size_kb != null ? s.size_kb + " KB" : "?"}</td>
      <td>${pinnedBadge}</td>
      <td>
        <button class="snapshot-restore-btn unlocked" data-filename="${esc(s.filename)}">Restore</button>
      </td>
    </tr>`;
  }

  wrap.innerHTML = `
    <table class="snapshot-table">
      <thead><tr>
        <th>Date</th><th>Files</th><th>Size</th><th></th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  // Wire restore buttons
  wrap.querySelectorAll(".snapshot-restore-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const filename = btn.dataset.filename;
      showRestoreConfirmation(
        "Restore Workspace Snapshot",
        `This will restore the workspace for <strong>${esc(mapName)}</strong> from <strong>${esc(filename)}</strong> and re-sync to the game folder.`,
        async () => {
          try {
            const resp = await postApi(`/vault/workspace/${encodeURIComponent(mapName)}/restore`, { filename });
            if (resp.ok) {
              alert(`Restored workspace snapshot for ${mapName}.`);
              // Refresh the snapshot list
              await loadWorkspaceSnapshots(mapName);
              renderWorkspaceSnapshotList(wrap, mapName);
            } else {
              alert(`Restore failed: ${resp.error || "Unknown error"}`);
            }
          } catch (err) {
            alert(`Restore failed: ${err.message}`);
          }
        }
      );
    });
  });
}

// ---------------------------------------------------------------------------
// Forks section
// ---------------------------------------------------------------------------

function renderForksSection(container) {
  const section = document.createElement("div");
  section.className = "project-section";
  section.innerHTML = `<h3>Forks</h3>`;

  const listWrap = document.createElement("div");
  listWrap.className = "fork-list-wrap";
  section.appendChild(listWrap);

  container.appendChild(section);
  renderForkList(section);
}

function renderForkList(section) {
  const wrap = section.querySelector(".fork-list-wrap");
  if (!wrap) return;
  wrap.innerHTML = "";

  if (!forksData || forksData.length === 0) {
    wrap.innerHTML = `<div class="project-empty-state">No forks. Use <code>torch fork</code> in the CLI to create a project fork for safe experimentation.</div>`;
    return;
  }

  for (const fork of forksData) {
    const card = document.createElement("div");
    card.className = "fork-card";

    const path = (fork.game_path || "").replace(/^\/home\/[^/]+/, "~");
    const created = fork.created ? new Date(fork.created).toLocaleDateString() : "?";
    const existsDot = fork.exists
      ? `<span class="fork-exists-dot fork-exists-ok"></span>`
      : `<span class="fork-exists-dot fork-exists-missing"></span><span style="color:var(--status-error);font-size:0.72rem">Missing</span>`;

    card.innerHTML = `
      <div class="fork-card-header">
        <div>
          <span class="fork-card-name">${esc(fork.name)}</span>
          ${existsDot}
        </div>
        <div class="fork-card-actions"></div>
      </div>
      <div class="fork-card-meta">Source: ${esc(fork.source_project || "?")} &middot; Created: ${esc(created)}</div>
      <div class="fork-card-path">${esc(path)}</div>
    `;

    // Delete button with padlock safety
    const actionsDiv = card.querySelector(".fork-card-actions");
    const deleteGroup = document.createElement("span");
    deleteGroup.className = "project-delete-group";

    const padlock = document.createElement("button");
    padlock.className = "project-padlock";
    padlock.textContent = "\u{1F512}";
    padlock.title = "Unlock to enable delete";

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "project-delete-btn";
    deleteBtn.textContent = "Delete";
    deleteBtn.disabled = true;
    deleteBtn.title = "Delete this fork (game files + registry entry)";

    let unlocked = false;
    padlock.addEventListener("click", (e) => {
      e.stopPropagation();
      unlocked = !unlocked;
      padlock.textContent = unlocked ? "\u{1F513}" : "\u{1F512}";
      deleteBtn.disabled = !unlocked;
      deleteBtn.classList.toggle("project-delete-ready", unlocked);
    });

    const forkName = fork.name;
    deleteBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!unlocked) return;

      const confirmed = confirm(
        `Delete fork "${forkName}"?\n\n` +
        `This will:\n` +
        `  - Delete the forked game files on disk\n` +
        `  - Remove the fork from TORCH's registry\n\n` +
        `This cannot be undone.`
      );
      if (!confirmed) return;

      deleteBtn.disabled = true;
      deleteBtn.textContent = "Deleting...";
      padlock.disabled = true;
      try {
        const resp = await postApi("/project/forks/delete", { name: forkName });
        if (resp.ok) {
          await loadForks();
          renderForkList(section);
        } else {
          alert(`Error: ${resp.error || "Unknown error"}`);
          deleteBtn.textContent = "Delete";
          deleteBtn.disabled = false;
          padlock.disabled = false;
        }
      } catch (err) {
        alert(`Error: ${err.message}`);
        deleteBtn.textContent = "Delete";
        deleteBtn.disabled = false;
        padlock.disabled = false;
      }
    });

    deleteGroup.appendChild(padlock);
    deleteGroup.appendChild(deleteBtn);
    actionsDiv.appendChild(deleteGroup);

    wrap.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Tools section
// ---------------------------------------------------------------------------

function renderToolsSection(container) {
  const section = document.createElement("div");
  section.className = "project-section";
  section.innerHTML = `<h3>Tools</h3>`;

  const grid = document.createElement("div");
  grid.className = "project-tools-grid";

  // SCORCH tool card
  const scorchCard = document.createElement("a");
  scorchCard.href = "#/scorch";
  scorchCard.className = "project-tool-card";
  scorchCard.innerHTML = `
    <span class="project-tool-icon">&#x1F525;</span>
    <div>
      <div class="project-tool-label">SCORCH</div>
      <div class="project-tool-desc">Remove vanilla content (selective or total)</div>
    </div>
  `;
  grid.appendChild(scorchCard);

  section.appendChild(grid);
  container.appendChild(section);
}


// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

function renderContent(container) {
  container.innerHTML = "";

  // Header
  const header = document.createElement("div");
  header.className = "project-page-header";
  header.innerHTML = `
    <h2>Projects</h2>
    <p class="project-page-subtitle">Manage your pokeemerald projects</p>
  `;
  container.appendChild(header);

  if (!projectsData || projectsData.length === 0) {
    const empty = document.createElement("div");
    empty.className = "project-page-empty";
    empty.innerHTML = `<p>No projects configured. Run <code>torch init</code> in a pokeemerald directory to set up a project.</p>`;
    container.appendChild(empty);
    // Still render backups and forks even with no projects
  } else {
    // Project cards
    const list = document.createElement("div");
    list.className = "projects-list project-page-list";
    container.appendChild(list);

    for (const proj of projectsData) {
      list.appendChild(renderProjectCard(container, proj));
    }

    // Note
    const note = document.createElement("p");
    note.className = "projects-note";
    note.textContent = "The favourite project auto-loads when the GUI starts.";
    container.appendChild(note);
  }

  // Backups section
  renderBackupsSection(container);

  // Build Snapshots section
  renderBuildSnapshotsSection(container);

  // Workspace Snapshots section
  renderWorkspaceSnapshotsSection(container);

  // Forks section
  renderForksSection(container);

  // Tools section (SCORCH link)
  renderToolsSection(container);

  // Auto-relock padlocks when clicking outside (covers project + fork padlocks)
  if (_relockHandler) document.removeEventListener("click", _relockHandler);
  _relockHandler = () => {
    document.querySelectorAll(".project-padlock").forEach(p => {
      if (p.textContent === "\u{1F513}") {
        p.textContent = "\u{1F512}";
        const btn = p.parentElement.querySelector(".project-delete-btn");
        if (btn) {
          btn.disabled = true;
          btn.classList.remove("project-delete-ready");
        }
      }
    });
  };
  document.addEventListener("click", _relockHandler);
}

export async function render(container) {
  injectCSS();
  container.innerHTML = `<p style="color:#888">Loading projects...</p>`;

  try {
    // Load all data in parallel
    const loads = [loadProjects(), loadBackups(), loadForks(), loadSnapshots(), loadWorkspaceMaps()];
    if (selectedWorkspaceMap) loads.push(loadWorkspaceSnapshots(selectedWorkspaceMap));
    await Promise.all(loads);
    renderContent(container);
  } catch (err) {
    container.innerHTML = `<article><p style="color:#f44">${esc(err.message)}</p></article>`;
  }
}

export function cleanup() {
  projectsData = null;
  backupsData = null;
  forksData = null;
  backupDir = null;
  snapshotsData = null;
  workspaceMapsData = null;
  selectedWorkspaceMap = null;
  workspaceSnapshotsData = null;
  if (_relockHandler) {
    document.removeEventListener("click", _relockHandler);
    _relockHandler = null;
  }
}
