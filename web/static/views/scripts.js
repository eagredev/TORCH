/**
 * TORCH Web GUI — Script Browser.
 *
 * Navigates maps and their TorScript files. Supports creating, deleting
 * (with full safety chain), and importing game scripts. Entry point to the
 * Script Editor (visualizer).
 *
 * Route: #/scripts  or  #/scripts/{MapName}
 */

import { api, postApi } from "../app.js";
import { esc, createModal } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";
import { getMapFromHashOrContext } from "../viewContext.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _maps = null;          // cached map list from /api/studio/maps
let _scripts = null;       // current map's script list
let _selectedMap = "";     // currently selected map name
let _scrollPos = 0;        // scroll restoration
let _statusTimer = null;   // auto-fade timer for status messages
let _viewMode = "scripts"; // "scripts" or "chains"
let _mapChains = [];       // chains relevant to the current map

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// esc() removed — now imported from utils.js

function showStatus(msg, isError) {
  const el = document.getElementById("scripts-status");
  if (!el) return;
  el.textContent = msg;
  el.style.display = "block";
  el.style.color = isError ? "var(--del-color, #f44)" : "var(--ins-color, #4ade80)";
  if (_statusTimer) clearTimeout(_statusTimer);
  _statusTimer = setTimeout(() => { el.style.display = "none"; }, 2500);
}

function closeModal() {
  document.querySelectorAll(".scripts-modal-backdrop").forEach(b => b.remove());
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadMaps() {
  const resp = await api("/studio/maps");
  if (resp.ok) {
    _maps = resp.maps || resp.data?.maps || resp.data || [];
    // Normalize — API may return different shapes
    if (!Array.isArray(_maps)) _maps = [];
  } else {
    _maps = [];
  }
}

async function loadScripts(mapName) {
  const resp = await api(`/scenes/${mapName}`);
  const scripts = resp.data?.scripts || resp.scripts;
  if (resp.ok !== false && scripts) {
    _scripts = scripts;
  } else {
    _scripts = [];
  }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderMapSelect() {
  const sel = document.getElementById("scripts-map-select");
  if (!sel || !_maps) return;

  // Filter to enrolled or custom maps, then sort alphabetically
  const relevant = _maps
    .filter(m => m.enrolled || m.is_custom || m.status !== "VANILLA")
    .sort((a, b) => a.name.localeCompare(b.name));

  sel.innerHTML = `<option value="">Select map...</option>`;
  for (const m of relevant) {
    const opt = document.createElement("option");
    opt.value = m.name;
    opt.textContent = m.name;
    if (m.name === _selectedMap) opt.selected = true;
    sel.appendChild(opt);
  }

  sel.addEventListener("change", () => {
    _selectedMap = sel.value;
    if (_selectedMap) {
      history.replaceState(null, "", `#/scripts/${_selectedMap}`);
      onMapSelected();
    } else {
      history.replaceState(null, "", "#/scripts");
      document.getElementById("scripts-content").style.display = "none";
      document.getElementById("scripts-empty").style.display = "block";
    }
  });
}

async function onMapSelected() {
  const content = document.getElementById("scripts-content");
  const empty = document.getElementById("scripts-empty");
  if (!_selectedMap) {
    content.style.display = "none";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";
  content.style.display = "block";

  // Reset to scripts view when changing maps
  _viewMode = "scripts";
  _updateViewToggle();

  const grid = document.getElementById("scripts-grid");
  grid.innerHTML = `<p style="color:#888">Loading scripts...</p>`;

  await loadScripts(_selectedMap);
  renderScriptCards();

  // Load chains for this map in the background
  _loadMapChains(_selectedMap);
}

async function _loadMapChains(mapName) {
  try {
    const resp = await api(`/chains/by-script/${mapName}/_all`);
    if (resp.ok !== false && resp.data) {
      _mapChains = resp.data.chains || [];
    } else {
      // Fallback: load all chains and filter
      const allResp = await api("/chains");
      const all = (allResp.ok !== false && allResp.data) ? (allResp.data.chains || []) : [];
      _mapChains = all.filter(c => (c.maps || []).includes(mapName));
    }
  } catch {
    _mapChains = [];
  }
}

function _updateViewToggle() {
  const chainsBtn = document.getElementById("scripts-chains-btn");
  const grid = document.getElementById("scripts-grid");
  const chainsView = document.getElementById("scripts-chains-view");
  const toolbar = document.querySelector(".scripts-toolbar");
  const newBtn = document.getElementById("scripts-new-btn");
  const importBtn = document.getElementById("scripts-import-btn");

  if (!chainsBtn) return;

  if (_viewMode === "chains") {
    chainsBtn.textContent = "Scripts";
    chainsBtn.title = "Switch back to scripts view";
    if (grid) grid.style.display = "none";
    if (chainsView) chainsView.style.display = "block";
    if (newBtn) newBtn.style.display = "none";
    if (importBtn) importBtn.style.display = "none";
  } else {
    chainsBtn.textContent = "Chains";
    chainsBtn.title = "View script chains for this map";
    if (grid) grid.style.display = "";
    if (chainsView) chainsView.style.display = "none";
    if (newBtn) newBtn.style.display = "";
    if (importBtn) importBtn.style.display = "";
  }
}

function _renderChainsView() {
  let view = document.getElementById("scripts-chains-view");
  if (!view) {
    view = document.createElement("div");
    view.id = "scripts-chains-view";
    view.className = "scripts-chains-view";
    const grid = document.getElementById("scripts-grid");
    if (grid) grid.parentNode.insertBefore(view, grid.nextSibling);
  }
  view.innerHTML = "";

  if (_mapChains.length === 0) {
    view.innerHTML = `
      <p style="color:#888">No chains involve scripts on this map.</p>
      <p style="color:#888;font-size:0.85em">
        <a href="#/chains" style="color:var(--link-color,#58a6ff)">Open Chain Builder</a> to create chains linking scripts across maps.
      </p>
    `;
    return;
  }

  for (const c of _mapChains) {
    const card = document.createElement("div");
    card.className = "chain-card";

    const maps = (c.maps || []).join(", ");
    const syncDot = c.synced_at
      ? `<span class="chain-sync-dot chain-sync-ok" title="Synced"></span>`
      : `<span class="chain-sync-dot chain-sync-stale" title="Not synced"></span>`;

    card.innerHTML = `
      <div class="chain-card-header">
        <h3 class="chain-card-name">${esc(c.name)}</h3>
        ${syncDot}
      </div>
      <div class="chain-card-meta">
        <span>${c.script_count} script${c.script_count !== 1 ? "s" : ""}</span>
        <span>${maps || "no maps"}</span>
      </div>
      <div class="chain-card-actions">
        <a href="#/chains/${esc(c.name)}" class="chain-card-open">Open in Builder</a>
      </div>
    `;

    view.appendChild(card);
  }
}

function renderScriptCards() {
  const grid = document.getElementById("scripts-grid");
  if (!grid) return;
  grid.innerHTML = "";

  if (!_scripts || _scripts.length === 0) {
    grid.innerHTML = `<p style="color:#888">No scripts found for this map. Create one or import from the game.</p>`;
    return;
  }

  for (const s of _scripts) {
    const card = document.createElement("div");
    card.className = "script-card";
    card.dataset.script = s.name;
    card.innerHTML = `
      <div class="script-card-header">
        <h3 class="script-card-name">${esc(s.name)}</h3>
        <div class="script-card-header-actions">
          <button class="script-card-rename" title="Rename script">\u270E</button>
          <button class="script-card-delete" title="Delete script">\u{1F5D1}</button>
        </div>
      </div>
      <div class="script-card-meta">
        <span>${s.beat_count ?? 0} beats</span>
        <span>${s.cast_count ?? 0} cast</span>
      </div>
      <div class="script-card-actions">
        <a href="#/visualizer/${esc(_selectedMap)}/${esc(s.name)}" class="script-card-edit">Edit \u2192</a>
      </div>
    `;

    // Card click → navigate to editor (unless action btn or link)
    card.addEventListener("click", (e) => {
      if (e.target.closest(".script-card-delete") || e.target.closest(".script-card-rename") || e.target.closest("a")) return;
      _saveScroll();
      window.location.hash = `#/visualizer/${_selectedMap}/${s.name}`;
    });

    // Rename button → rename modal
    card.querySelector(".script-card-rename").addEventListener("click", (e) => {
      e.stopPropagation();
      showRenameModal(s.name);
    });

    // Delete button → padlock modal
    card.querySelector(".script-card-delete").addEventListener("click", (e) => {
      e.stopPropagation();
      showDeletePadlock(s.name);
    });

    // Save scroll before link click
    const editLink = card.querySelector(".script-card-edit");
    if (editLink) editLink.addEventListener("click", () => _saveScroll());

    grid.appendChild(card);
  }

  _restoreScroll();
}

// ---------------------------------------------------------------------------
// New Script Modal
// ---------------------------------------------------------------------------

function showNewScriptModal() {
  const { el, close } = createModal("scripts-modal", `
      <h3>New Script</h3>
      <div class="viz-editor-field">
        <label for="scripts-new-name">Script Name</label>
        <input type="text" id="scripts-new-name" placeholder="e.g., BusterEncounter" autocomplete="off" />
      </div>
      <p class="scripts-modal-info">
        Creates a new TorScript file in the workspace. The script will start with a basic template.
      </p>
      <p id="scripts-new-error" style="color:var(--del-color,#f44);display:none;"></p>
      <div class="scripts-modal-actions">
        <button class="btn-apply" id="scripts-new-confirm">Create</button>
        <button class="btn-cancel" id="scripts-new-cancel">Cancel</button>
      </div>
  `);

  const nameInput = el.querySelector("#scripts-new-name");
  const errorEl = el.querySelector("#scripts-new-error");
  const confirmBtn = el.querySelector("#scripts-new-confirm");

  // Close on cancel
  el.querySelector("#scripts-new-cancel").addEventListener("click", close);

  // Validate on input
  nameInput.addEventListener("input", () => {
    const val = nameInput.value.trim();
    const valid = /^[A-Za-z][A-Za-z0-9_]*$/.test(val);
    const duplicate = _scripts && _scripts.some(s => s.name === val);

    if (!val) {
      errorEl.style.display = "none";
      confirmBtn.disabled = true;
    } else if (!valid) {
      errorEl.textContent = "Name must start with a letter and contain only letters, numbers, and underscores.";
      errorEl.style.display = "block";
      confirmBtn.disabled = true;
    } else if (duplicate) {
      errorEl.textContent = `Script "${val}" already exists.`;
      errorEl.style.display = "block";
      confirmBtn.disabled = true;
    } else {
      errorEl.style.display = "none";
      confirmBtn.disabled = false;
    }
  });

  confirmBtn.disabled = true;

  // Create
  confirmBtn.addEventListener("click", async () => {
    const name = nameInput.value.trim();
    if (!name) return;

    confirmBtn.disabled = true;
    confirmBtn.textContent = "Creating...";

    try {
      const resp = await postApi(`/scenes/${_selectedMap}/create`, { name });
      if (resp.ok) {
        close();
        showStatus(`Script "${name}" created.`);
        await loadScripts(_selectedMap);
        renderScriptCards();
      } else {
        errorEl.textContent = resp.error || "Failed to create script.";
        errorEl.style.display = "block";
        confirmBtn.textContent = "Create";
        confirmBtn.disabled = false;
      }
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.style.display = "block";
      confirmBtn.textContent = "Create";
      confirmBtn.disabled = false;
    }
  });

  nameInput.focus();
}

// ---------------------------------------------------------------------------
// Rename Script Modal
// ---------------------------------------------------------------------------

function showRenameModal(scriptName) {
  const { el, close } = createModal("scripts-modal", `
      <h3>Rename Script</h3>
      <div class="viz-editor-field">
        <label for="scripts-rename-name">New Name</label>
        <input type="text" id="scripts-rename-name" value="${esc(scriptName)}" autocomplete="off" />
      </div>
      <p id="scripts-rename-error" style="color:var(--del-color,#f44);display:none;"></p>
      <div id="scripts-rename-warnings" style="color:var(--warn-color,#f0ad4e);display:none;font-size:0.85em;margin-bottom:8px;"></div>
      <div class="scripts-modal-actions">
        <button class="btn-apply" id="scripts-rename-confirm">Rename</button>
        <button class="btn-cancel" id="scripts-rename-cancel">Cancel</button>
      </div>
  `);

  const nameInput = el.querySelector("#scripts-rename-name");
  const errorEl = el.querySelector("#scripts-rename-error");
  const confirmBtn = el.querySelector("#scripts-rename-confirm");

  // Close on cancel
  el.querySelector("#scripts-rename-cancel").addEventListener("click", close);

  // Select all text for easy replacement
  nameInput.select();

  // Validate on input
  nameInput.addEventListener("input", () => {
    const val = nameInput.value.trim();
    const valid = /^[A-Za-z][A-Za-z0-9_]*$/.test(val);
    const duplicate = _scripts && _scripts.some(s => s.name === val);
    const same = val === scriptName;

    if (!val) {
      errorEl.style.display = "none";
      confirmBtn.disabled = true;
    } else if (!valid) {
      errorEl.textContent = "Name must start with a letter and contain only letters, numbers, and underscores.";
      errorEl.style.display = "block";
      confirmBtn.disabled = true;
    } else if (same) {
      errorEl.textContent = "Name is the same as the current name.";
      errorEl.style.display = "block";
      confirmBtn.disabled = true;
    } else if (duplicate) {
      errorEl.textContent = `Script "${val}" already exists.`;
      errorEl.style.display = "block";
      confirmBtn.disabled = true;
    } else {
      errorEl.style.display = "none";
      confirmBtn.disabled = false;
    }
  });

  // Initial state: disabled (same name)
  confirmBtn.disabled = true;

  // Rename
  confirmBtn.addEventListener("click", async () => {
    const newName = nameInput.value.trim();
    if (!newName || newName === scriptName) return;

    confirmBtn.disabled = true;
    confirmBtn.textContent = "Renaming...";

    try {
      const resp = await postApi(`/scenes/${_selectedMap}/${scriptName}/rename`, { new_name: newName });
      if (resp.ok) {
        // Show chain warnings if any
        const warnings = resp.data?.warnings;
        if (warnings && warnings.length > 0) {
          const warningsEl = el.querySelector("#scripts-rename-warnings");
          warningsEl.innerHTML = warnings.map(w => `<p>${esc(w)}</p>`).join("");
          warningsEl.style.display = "block";
          // Let the user see the warning, then close after a short delay
          showStatus(`Script renamed to "${newName}".`);
          await loadScripts(_selectedMap);
          renderScriptCards();
          setTimeout(close, 2500);
        } else {
          close();
          showStatus(`Script renamed to "${newName}".`);
          await loadScripts(_selectedMap);
          renderScriptCards();
        }
      } else {
        errorEl.textContent = resp.error || "Failed to rename script.";
        errorEl.style.display = "block";
        confirmBtn.textContent = "Rename";
        confirmBtn.disabled = false;
      }
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.style.display = "block";
      confirmBtn.textContent = "Rename";
      confirmBtn.disabled = false;
    }
  });

  nameInput.focus();
}

// ---------------------------------------------------------------------------
// Delete Safety Chain — Step 1: Padlock confirmation
// ---------------------------------------------------------------------------

function showDeletePadlock(scriptName) {
  const { el, close } = createModal("scripts-modal", `
      <h3>Delete Script: ${esc(scriptName)}</h3>
      <p>This action cannot be undone. Type the script name to confirm.</p>
      <div class="viz-editor-field">
        <label>Type "${esc(scriptName)}" to confirm</label>
        <input type="text" id="scripts-delete-confirm-input" autocomplete="off" />
      </div>
      <div class="scripts-modal-actions">
        <button class="btn-apply scripts-delete-execute" id="scripts-delete-analyze" disabled>Analyze &amp; Delete</button>
        <button class="btn-cancel" id="scripts-delete-cancel">Cancel</button>
      </div>
  `);
  el.classList.add("scripts-delete-modal");

  const input = el.querySelector("#scripts-delete-confirm-input");
  const analyzeBtn = el.querySelector("#scripts-delete-analyze");

  el.querySelector("#scripts-delete-cancel").addEventListener("click", close);

  // Enable button only when name matches exactly
  input.addEventListener("input", () => {
    analyzeBtn.disabled = input.value !== scriptName;
  });

  analyzeBtn.addEventListener("click", async () => {
    if (input.value !== scriptName) return;
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = "Analyzing...";

    try {
      const resp = await postApi(`/scenes/${_selectedMap}/${scriptName}/analyze-delete`);
      close();
      if (resp.ok) {
        showImpactReport(scriptName, resp.data);
      } else {
        showStatus(resp.error || "Analysis failed.", true);
      }
    } catch (err) {
      close();
      showStatus(`Analysis error: ${err.message}`, true);
    }
  });

  input.focus();
}

// ---------------------------------------------------------------------------
// Delete Safety Chain — Step 2: Impact Report
// ---------------------------------------------------------------------------

function showImpactReport(scriptName, data) {
  const flagCount = data.flags_used ? data.flags_used.length : 0;
  const moveCount = data.movements ? data.movements.length : 0;
  const crossRefCount = data.cross_refs ? data.cross_refs.length : 0;

  let crossRefHtml = "";
  if (crossRefCount > 0) {
    crossRefHtml = `<p style="color:var(--del-color,#f44)"><strong>${crossRefCount}</strong> cross-reference${crossRefCount !== 1 ? "s" : ""} found — other scripts reference this one</p>`;
  }

  // TODO: Add reclaim_flags / reclaim_movements checkboxes once the backend
  // supports actual flag and movement reclamation (game-file modification).
  // For now we only show the impact summary — no reclaim options.

  const { el, close } = createModal("scripts-modal", `
      <h3>Impact Analysis: ${esc(scriptName)}</h3>
      <div class="scripts-impact-report">
        <p><strong>${data.beat_count ?? 0}</strong> beat${(data.beat_count ?? 0) !== 1 ? "s" : ""} will be removed</p>
        <p><strong>${flagCount}</strong> flag${flagCount !== 1 ? "s" : ""} may become orphaned</p>
        <p><strong>${moveCount}</strong> movement block${moveCount !== 1 ? "s" : ""} will be removed</p>
        ${crossRefHtml}
      </div>
      <div class="scripts-modal-actions">
        <button class="btn-apply scripts-delete-execute" id="scripts-delete-execute">Delete</button>
        <button class="btn-cancel" id="scripts-impact-cancel">Cancel</button>
      </div>
  `);
  el.classList.add("scripts-impact-modal");

  el.querySelector("#scripts-impact-cancel").addEventListener("click", close);

  el.querySelector("#scripts-delete-execute").addEventListener("click", async () => {
    const btn = el.querySelector("#scripts-delete-execute");
    btn.disabled = true;
    btn.textContent = "Deleting...";

    try {
      const resp = await postApi(`/scenes/${_selectedMap}/${scriptName}/delete`, {});
      close();
      if (resp.ok) {
        showStatus(`Script "${scriptName}" deleted.`);
        await loadScripts(_selectedMap);
        renderScriptCards();
      } else {
        showStatus(resp.error || "Delete failed.", true);
      }
    } catch (err) {
      close();
      showStatus(`Delete error: ${err.message}`, true);
    }
  });
}

// ---------------------------------------------------------------------------
// Import from Game
// ---------------------------------------------------------------------------

function showImportModal() {
  const { el, close } = createModal("scripts-modal", `
      <h3>Import Game Scripts</h3>
      <p class="scripts-modal-info">Import scripts from the game source into your workspace. They will be decompiled from Poryscript to TorScript.</p>
      <div id="scripts-import-list" class="scripts-import-list">
        <p style="color:#888">Loading...</p>
      </div>
      <div class="scripts-modal-actions">
        <button class="btn-cancel" id="scripts-import-cancel">Close</button>
      </div>
  `);
  el.classList.add("scripts-import-modal");

  el.querySelector("#scripts-import-cancel").addEventListener("click", close);

  // Fetch available game scripts
  api(`/scenes/${_selectedMap}/game-scripts`).then(resp => {
    const list = el.querySelector("#scripts-import-list");
    if (!list) return;

    const scripts = resp.scripts || [];
    if (scripts.length === 0) {
      list.innerHTML = `<p style="color:#888">No importable scripts found for this map.</p>`;
      return;
    }

    list.innerHTML = "";
    for (const s of scripts) {
      const item = document.createElement("div");
      item.className = "scripts-import-item";
      item.innerHTML = `
        <span>${esc(s.name)}</span>
        <button class="scripts-import-item-btn" data-path="${esc(s.path)}" data-name="${esc(s.name)}">Import</button>
      `;

      item.querySelector(".scripts-import-item-btn").addEventListener("click", async (e) => {
        const btn = e.target;
        const scriptPath = btn.dataset.path;
        const scriptName = btn.dataset.name;

        btn.disabled = true;
        btn.textContent = "Importing...";

        try {
          const importResp = await postApi(`/scenes/${_selectedMap}/import`, {
            script_path: scriptPath,
            script_name: scriptName,
          });
          if (importResp.ok) {
            btn.textContent = "Imported";
            showStatus(`Imported "${scriptName}".`);
            // Reload script list in the background
            await loadScripts(_selectedMap);
            renderScriptCards();
          } else {
            btn.textContent = importResp.error || "Error";
            setTimeout(() => { btn.textContent = "Import"; btn.disabled = false; }, 2000);
          }
        } catch (err) {
          btn.textContent = "Error";
          setTimeout(() => { btn.textContent = "Import"; btn.disabled = false; }, 2000);
        }
      });

      list.appendChild(item);
    }
  }).catch(() => {
    const list = el.querySelector("#scripts-import-list");
    if (list) list.innerHTML = `<p style="color:var(--del-color,#f44)">Failed to load game scripts.</p>`;
  });
}

// ---------------------------------------------------------------------------
// Scroll restoration
// ---------------------------------------------------------------------------

function _saveScroll() {
  _scrollPos = document.getElementById("scripts-content")?.scrollTop || window.scrollY || 0;
}

function _restoreScroll() {
  if (_scrollPos > 0) {
    const el = document.getElementById("scripts-content");
    if (el) {
      el.scrollTop = _scrollPos;
    } else {
      window.scrollTo(0, _scrollPos);
    }
  }
}

// ---------------------------------------------------------------------------
// Main render / cleanup
// ---------------------------------------------------------------------------

export async function render(container) {
  // Parse map name from URL hash or IDE view context
  _selectedMap = getMapFromHashOrContext() || "";

  container.innerHTML = `
    <article class="scripts-root">
      ${renderStudioNavbar("Scripts")}
      <header class="scripts-header">
        <div class="scripts-map-select-wrap">
          <select id="scripts-map-select" class="scripts-map-select">
            <option value="">Select map...</option>
          </select>
        </div>
      </header>

      <div id="scripts-content" class="scripts-content" style="display:none;">
        <div class="scripts-toolbar">
          <button id="scripts-new-btn" class="scripts-new-btn">+ New Script</button>
          <button id="scripts-import-btn" class="scripts-import-btn">Import from Game</button>
          <button id="scripts-chains-btn" class="scripts-chains-link" title="View script chains for this map">Chains</button>
        </div>
        <div id="scripts-status" class="scripts-status" style="display:none;"></div>
        <div id="scripts-grid" class="scripts-grid"></div>
      </div>

      <div id="scripts-empty" class="scripts-empty">
        <p>Select a map to browse its scripts.</p>
      </div>
    </article>
  `;

  // Wire toolbar buttons
  document.getElementById("scripts-new-btn").addEventListener("click", showNewScriptModal);
  document.getElementById("scripts-import-btn").addEventListener("click", showImportModal);
  document.getElementById("scripts-chains-btn").addEventListener("click", () => {
    if (_viewMode === "scripts") {
      _viewMode = "chains";
      _renderChainsView();
    } else {
      _viewMode = "scripts";
    }
    _updateViewToggle();
  });

  // Load maps and populate selector
  try {
    await loadMaps();
    renderMapSelect();
    if (_selectedMap) {
      await onMapSelected();
    }
  } catch (err) {
    container.innerHTML = `<article><p style="color:#f44">${esc(err.message)}</p></article>`;
  }
}

export function cleanup() {
  _maps = null;
  _scripts = null;
  _selectedMap = "";
  _scrollPos = 0;
  _viewMode = "scripts";
  _mapChains = [];
  if (_statusTimer) {
    clearTimeout(_statusTimer);
    _statusTimer = null;
  }
  // Remove any lingering modals
  closeModal();
}
