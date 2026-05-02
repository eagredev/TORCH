/**
 * TORCH Web GUI — Chain Builder.
 *
 * Create, edit, and manage script chains. Chains are ordered sequences of
 * scripts forming continuous narrative flows, enabling cross-script position
 * tracking with auto-calculated ranges and manual overrides.
 *
 * Route: #/chains  or  #/chains/{ChainName}
 */

import { api, postApi } from "../app.js";
import { renderSegment, getCardinalRegions, getSightRegions, getApproachRegions, wasDrag, initInteraction, cssToTile } from "./chainCanvas.js";
import { esc, createModal } from "../utils.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _chains = null;           // cached chain list
let _selectedChain = "";      // currently selected chain name
let _chainData = null;        // full chain data for detail view
let _maps = null;             // map list for script picker
let _dragSrc = null;          // drag-and-drop source index
let _statusTimer = null;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// esc() removed — now imported from utils.js

function showStatus(msg, isError) {
  const el = document.getElementById("chains-status");
  if (!el) return;
  el.textContent = msg;
  el.style.display = "block";
  el.style.color = isError ? "var(--del-color, #f44)" : "var(--ins-color, #4ade80)";
  if (_statusTimer) clearTimeout(_statusTimer);
  _statusTimer = setTimeout(() => { el.style.display = "none"; }, 2500);
}

function closeModal() {
  document.querySelectorAll(".chains-modal-backdrop").forEach(b => b.remove());
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadChains() {
  const resp = await api("/chains");
  _chains = (resp.ok !== false && resp.data) ? (resp.data.chains || []) : [];
}

async function loadChainDetail(name) {
  const resp = await api(`/chains/${encodeURIComponent(name)}`);
  if (resp.ok !== false && resp.data) {
    _chainData = resp.data;
    return true;
  }
  _chainData = null;
  return false;
}

async function loadMaps() {
  if (_maps) return;
  const resp = await api("/studio/maps");
  if (resp.ok !== false) {
    const raw = resp.maps || resp.data?.maps || resp.data || [];
    _maps = Array.isArray(raw)
      ? raw.filter(m => m.enrolled || m.is_custom || m.status !== "VANILLA")
           .sort((a, b) => a.name.localeCompare(b.name))
      : [];
  } else {
    _maps = [];
  }
}

// ---------------------------------------------------------------------------
// Chain list rendering
// ---------------------------------------------------------------------------

function renderChainList() {
  const grid = document.getElementById("chains-grid");
  if (!grid) return;
  grid.innerHTML = "";

  if (!_chains || _chains.length === 0) {
    grid.innerHTML = `
      <div class="chain-onboarding">
        <h3>What are Script Chains?</h3>
        <p>Chains link multiple scripts into an ordered sequence &mdash; a multi-part cutscene,
        a cross-map journey, or any series of scripts that should flow together.</p>
        <p>Chains track <strong>actor positions</strong> across scripts automatically.
        When an NPC walks to position (5,10) in script A, script B starts knowing
        they're already there.</p>
        <h4>Getting Started</h4>
        <ol>
          <li>Click <strong>+ New Chain</strong> to create a chain with a head script</li>
          <li>Add more scripts to the chain in sequence order</li>
          <li>Assign cast members (NPCs that appear across scripts)</li>
          <li>Hit <strong>Sync</strong> to auto-calculate position ranges</li>
        </ol>
        <p>Or try <strong>Discover</strong> to scan for scripts that already call each other via goto/call.</p>
      </div>
    `;
    return;
  }

  for (const c of _chains) {
    const card = document.createElement("div");
    card.className = "chain-card";
    card.dataset.chain = c.name;

    const maps = (c.maps || []).join(", ");
    const syncStatus = c.synced_at ? "synced" : "unsynced";
    const syncDot = c.synced_at
      ? `<span class="chain-sync-dot chain-sync-ok" title="Last sync: ${c.synced_at}"></span>`
      : `<span class="chain-sync-dot chain-sync-stale" title="Not yet synced"></span>`;

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
        <button class="chain-card-open" data-chain="${esc(c.name)}">Open</button>
        <button class="chain-card-delete" data-chain="${esc(c.name)}">Delete</button>
      </div>
    `;

    card.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      _openChainDetail(c.name);
    });

    card.querySelector(".chain-card-open").addEventListener("click", () => {
      _openChainDetail(c.name);
    });

    card.querySelector(".chain-card-delete").addEventListener("click", (e) => {
      e.stopPropagation();
      _confirmDelete(c.name);
    });

    grid.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Chain detail rendering
// ---------------------------------------------------------------------------

async function _openChainDetail(name) {
  _selectedChain = name;
  history.replaceState(null, "", `#/chains/${name}`);

  const ok = await loadChainDetail(name);
  if (!ok) {
    showStatus(`Failed to load chain: ${name}`, true);
    return;
  }
  renderChainDetail();
}

function renderChainDetail() {
  const content = document.getElementById("chains-content");
  if (!content || !_chainData) return;

  const seq = _chainData.sequence || [];
  const segments = _chainData.segments || {};
  const overrides = _chainData.manual_overrides || {};
  const sync = _chainData.sync || {};
  const cast = _chainData.cast || {};

  content.innerHTML = `
    <div class="chain-detail">
      <div class="chain-detail-header">
        <button class="chain-back-btn">\u2190 All Chains</button>
        <h3>${esc(_chainData.chain)}</h3>
        <div class="chain-detail-actions">
          <button class="chain-sync-btn" title="Sync chain positions">Sync</button>
          <button class="chain-add-btn">+ Add Script</button>
        </div>
      </div>

      <div class="chain-flow" id="chain-flow"></div>

      <div class="chain-preview-section">
        <h4>Segment Preview</h4>
        <div class="chain-preview-info" id="chain-preview-info">
          <span style="color:#888">Click a segment above to preview</span>
        </div>
        <canvas id="chain-preview-canvas" width="560" height="350" class="chain-preview-canvas"></canvas>
        <div class="chain-preview-actions" id="chain-preview-actions" style="display:none">
          <button class="btn-apply chain-open-editor-btn" id="chain-open-editor-btn">Open in Script Editor</button>
        </div>
      </div>

      <div class="chain-cast-section">
        <h4>Cast</h4>
        <div id="chain-cast-list" class="chain-cast-list"></div>
        <button class="chain-add-cast-btn">+ Add Cast Member</button>
      </div>

      <div class="chain-overrides-section">
        <h4>Manual Overrides</h4>
        <div id="chain-overrides-list" class="chain-overrides-list"></div>
      </div>
    </div>
  `;

  // Render flow diagram
  _renderFlowDiagram(seq, segments, sync);

  // Render cast list
  _renderCastList(cast);

  // Render overrides
  _renderOverrides(overrides);

  // Wire up buttons
  content.querySelector(".chain-back-btn").addEventListener("click", () => {
    _selectedChain = "";
    _chainData = null;
    history.replaceState(null, "", "#/chains");
    renderChainList();
    document.getElementById("chains-detail-wrap").style.display = "none";
    document.getElementById("chains-list-wrap").style.display = "block";
  });

  content.querySelector(".chain-sync-btn").addEventListener("click", _syncChain);
  content.querySelector(".chain-add-btn").addEventListener("click", _showAddScriptModal);
  content.querySelector(".chain-add-cast-btn")?.addEventListener("click", _showAddCastModal);

  // Wire up segment preview canvas
  _wirePreviewCanvas(seq, segments);

  // Show detail, hide list
  document.getElementById("chains-detail-wrap").style.display = "block";
  document.getElementById("chains-list-wrap").style.display = "none";
}

// ---------------------------------------------------------------------------
// Flow diagram — horizontal boxes with arrows
// ---------------------------------------------------------------------------

function _renderFlowDiagram(sequence, segments, sync) {
  const flow = document.getElementById("chain-flow");
  if (!flow) return;
  flow.innerHTML = "";

  let prevMap = "";
  for (let i = 0; i < sequence.length; i++) {
    const entry = sequence[i];
    const seg = segments[entry.script] || {};
    const hash = (sync.input_hashes || {})[entry.script];

    // Map boundary marker
    if (entry.map !== prevMap && prevMap !== "") {
      const boundary = document.createElement("div");
      boundary.className = "chain-flow-boundary";
      boundary.textContent = entry.map;
      flow.appendChild(boundary);
    }

    // Arrow between boxes (except before first)
    if (i > 0 && entry.map === prevMap) {
      const arrow = document.createElement("div");
      arrow.className = "chain-flow-arrow";
      arrow.textContent = "\u2192";
      flow.appendChild(arrow);
    }

    // Script box
    const box = document.createElement("div");
    box.className = "chain-flow-box";
    box.draggable = true;
    box.dataset.index = i;
    box.dataset.script = entry.script;

    // Status color
    const statusClass = hash ? "chain-flow-synced" : "chain-flow-stale";
    box.classList.add(statusClass);

    const actorCount = Object.keys(seg.output?.actors || {}).length;
    const trigger = seg.trigger;
    const triggerLabel = trigger ? `(${trigger.type})` : "";

    box.innerHTML = `
      <div class="chain-flow-box-name">${esc(entry.script)}</div>
      <div class="chain-flow-box-meta">
        ${entry.map !== prevMap || i === 0 ? `<span class="chain-flow-box-map">${esc(entry.map)}</span>` : ""}
        <span>${actorCount} actors ${triggerLabel}</span>
      </div>
      <button class="chain-flow-remove" data-script="${esc(entry.script)}" title="Remove from chain">\u00D7</button>
    `;

    // Click box → select segment for preview
    box.addEventListener("click", (e) => {
      if (e.target.closest(".chain-flow-remove")) return;
      _selectSegmentPreview(entry.script, entry.map, segments);
      // Highlight selected box
      flow.querySelectorAll(".chain-flow-box").forEach(b => b.classList.remove("chain-flow-selected"));
      box.classList.add("chain-flow-selected");
    });

    // Remove button
    box.querySelector(".chain-flow-remove").addEventListener("click", (e) => {
      e.stopPropagation();
      _removeSegment(entry.script);
    });

    // Drag-and-drop reordering
    box.addEventListener("dragstart", (e) => {
      _dragSrc = i;
      box.classList.add("chain-flow-dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    box.addEventListener("dragend", () => {
      box.classList.remove("chain-flow-dragging");
      _dragSrc = null;
    });
    box.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      box.classList.add("chain-flow-dragover");
    });
    box.addEventListener("dragleave", () => {
      box.classList.remove("chain-flow-dragover");
    });
    box.addEventListener("drop", (e) => {
      e.preventDefault();
      box.classList.remove("chain-flow-dragover");
      if (_dragSrc !== null && _dragSrc !== i) {
        _reorderSegments(_dragSrc, i);
      }
    });

    flow.appendChild(box);
    prevMap = entry.map;
  }
}

// ---------------------------------------------------------------------------
// Cast list
// ---------------------------------------------------------------------------

function _renderCastList(cast) {
  const list = document.getElementById("chain-cast-list");
  if (!list) return;
  list.innerHTML = "";

  const entries = Object.entries(cast);
  if (entries.length === 0) {
    list.innerHTML = `<p style="color:#888">No cast members defined. Add a cast member to link NPCs across maps.</p>`;
    return;
  }

  for (const [id, data] of entries) {
    const events = data.events || {};
    const mapEntries = Object.entries(events);
    let assignmentHtml = "";
    if (mapEntries.length === 0) {
      assignmentHtml = `<span style="color:#888">no NPC assignments</span>`;
    } else {
      assignmentHtml = mapEntries.map(([mapName, info]) => {
        if (typeof info === "object" && info.object_event_index) {
          return `<span class="chain-cast-assignment">${esc(mapName)}: NPC #${info.object_event_index}</span>`;
        }
        return `<span class="chain-cast-assignment">${esc(mapName)}</span>`;
      }).join("");
    }

    const div = document.createElement("div");
    div.className = "chain-cast-item";
    div.innerHTML = `
      <div class="chain-cast-item-header">
        <span class="chain-cast-name">${esc(data.display_name || id)}</span>
        <button class="chain-cast-edit-btn" data-cast="${esc(id)}" title="Edit assignments">Edit</button>
        <button class="chain-cast-remove-btn" data-cast="${esc(id)}" title="Remove cast member">Remove</button>
      </div>
      <div class="chain-cast-assignments">${assignmentHtml}</div>
    `;

    div.querySelector(".chain-cast-edit-btn").addEventListener("click", () => {
      _showEditCastModal(id, data);
    });

    div.querySelector(".chain-cast-remove-btn").addEventListener("click", async () => {
      const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
        action: "update_cast",
        cast_id: id,
        events: { _remove: true },
      });
      if (resp.ok !== false && resp.data) {
        _chainData = resp.data;
        renderChainDetail();
        showStatus(`Removed cast: ${data.display_name || id}`);
      }
    });

    list.appendChild(div);
  }
}

// ---------------------------------------------------------------------------
// Overrides display
// ---------------------------------------------------------------------------

function _renderOverrides(overrides) {
  const list = document.getElementById("chain-overrides-list");
  if (!list) return;
  list.innerHTML = "";

  const entries = Object.entries(overrides);
  if (entries.length === 0) {
    list.innerHTML = `<p style="color:#888">No manual overrides. Override chain-calculated positions when needed.</p>`;
    return;
  }

  for (const [segment, segData] of entries) {
    const actors = segData.actors || {};
    for (const [actor, fields] of Object.entries(actors)) {
      const div = document.createElement("div");
      div.className = "chain-override-item";
      const note = fields.note || "";
      const stale = fields.stale_warning || "";
      const fieldStr = Object.entries(fields)
        .filter(([k]) => k !== "note" && k !== "stale_warning")
        .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
        .join(", ");

      div.innerHTML = `
        <span class="chain-override-seg">${esc(segment)}</span>
        <span class="chain-override-actor">${esc(actor)}</span>
        <span class="chain-override-fields">${esc(fieldStr)}</span>
        ${note ? `<span class="chain-override-note">${esc(note)}</span>` : ""}
        ${stale ? `<span class="chain-override-stale">${esc(stale)}</span>` : ""}
        <button class="chain-override-clear" data-segment="${esc(segment)}" data-actor="${esc(actor)}"
                title="Clear override">Clear</button>
      `;

      div.querySelector(".chain-override-clear").addEventListener("click", () => {
        _clearOverride(segment, actor);
      });

      list.appendChild(div);
    }
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

let _previewScript = "";
let _previewMap = "";

function _selectSegmentPreview(scriptName, mapName, segments) {
  _previewScript = scriptName;
  _previewMap = mapName;

  let canvas = document.getElementById("chain-preview-canvas");
  const info = document.getElementById("chain-preview-info");
  const actions = document.getElementById("chain-preview-actions");
  if (!canvas) return;

  // Replace canvas to clear old event listeners (pan/zoom/click)
  const newCanvas = canvas.cloneNode(true);
  canvas.parentNode.replaceChild(newCanvas, canvas);
  canvas = newCanvas;

  // Wire pan/zoom interaction
  initInteraction(canvas);

  const seg = segments[scriptName];
  if (seg) {
    renderSegment(canvas, seg, _chainData, scriptName, null);
  }

  // Wire trigger tile click handler for segments with sight triggers
  _wireTriggerClickHandler(canvas, scriptName, seg);

  if (info) info.innerHTML = `<strong>${esc(scriptName)}</strong> <span style="color:#888">(${esc(mapName)})</span>`;
  if (actions) actions.style.display = "flex";

  // Wire the "Open in Script Editor" button
  const btn = document.getElementById("chain-open-editor-btn");
  if (btn) {
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.addEventListener("click", () => {
      window.location.hash = `#/visualizer/${mapName}/${scriptName}`;
    });
  }

  // Render trigger configuration for this segment
  _renderTriggerConfig(scriptName, seg);
}

function _renderTriggerConfig(scriptName, seg) {
  const actions = document.getElementById("chain-preview-actions");
  if (!actions) return;

  // Remove any existing trigger config
  const existing = document.getElementById("chain-trigger-config");
  if (existing) existing.remove();

  // Only show trigger config for the head (first) segment —
  // subsequent segments are triggered by the previous script ending
  const sequence = _chainData?.sequence || [];
  const isHead = sequence.length > 0 && sequence[0].script === scriptName;
  if (!isHead) return;

  const trigger = seg?.trigger || {};
  const currentType = trigger.type || "";
  const currentRadius = trigger.radius || 3;

  const div = document.createElement("div");
  div.id = "chain-trigger-config";
  div.className = "chain-trigger-config";
  div.innerHTML = `
    <label>How does this chain start?</label>
    <div class="chain-trigger-row">
      <select id="chain-trigger-type" class="chains-select">
        <option value="" ${!currentType ? "selected" : ""}>(none)</option>
        <option value="sight" ${currentType === "sight" ? "selected" : ""}>Player enters NPC sight range</option>
        <option value="talk" ${currentType === "talk" ? "selected" : ""}>Player talks to NPC</option>
        <option value="walk_over" ${currentType === "walk_over" ? "selected" : ""}>Player steps on tile</option>
      </select>
      <input type="number" id="chain-trigger-radius" class="chain-trigger-radius-input"
             min="1" max="10" value="${currentRadius}"
             style="${currentType === "sight" ? "" : "display:none"}" />
    </div>
  `;

  actions.parentNode.insertBefore(div, actions);

  const typeSel = div.querySelector("#chain-trigger-type");
  const radiusInput = div.querySelector("#chain-trigger-radius");

  typeSel.addEventListener("change", async () => {
    const newType = typeSel.value;
    radiusInput.style.display = newType === "sight" ? "" : "none";

    if (!newType) {
      // Clear trigger
      await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
        action: "set_trigger",
        script: scriptName,
        trigger: null,
      });
    } else {
      const newTrigger = { type: newType };
      if (newType === "sight") {
        newTrigger.radius = parseInt(radiusInput.value, 10) || 3;
        newTrigger.excluded_cardinals = trigger.excluded_cardinals || [];
        newTrigger.excluded_distances = trigger.excluded_distances || [];
      }
      await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
        action: "set_trigger",
        script: scriptName,
        trigger: newTrigger,
      });
    }
    showStatus("Trigger updated");
  });

  radiusInput.addEventListener("change", async () => {
    if (typeSel.value !== "sight") return;
    const newTrigger = {
      type: "sight",
      radius: parseInt(radiusInput.value, 10) || 3,
      excluded_cardinals: trigger.excluded_cardinals || [],
      excluded_distances: trigger.excluded_distances || [],
    };
    await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
      action: "set_trigger",
      script: scriptName,
      trigger: newTrigger,
    });
    showStatus("Trigger radius updated");
  });
}

function _wireTriggerClickHandler(canvas, scriptName, seg) {
  if (!seg?.trigger) return;
  const triggerType = seg.trigger.type;
  if (triggerType !== "sight" && triggerType !== "talk") return;

  canvas.addEventListener("click", async (e) => {
    if (wasDrag()) return;

    const rect = canvas.getBoundingClientRect();
    const tile = cssToTile(canvas, e.clientX - rect.left, e.clientY - rect.top);
    const trigger = seg.trigger;

    // --- Sight trigger: corridor tiles + cardinal tiles ---
    if (triggerType === "sight") {
      const sightRegions = getSightRegions();
      const sr = sightRegions.find(r => r.x === tile.tx && r.y === tile.ty);
      if (sr) {
        const excluded = trigger.excluded_distances || [];
        const idx = excluded.indexOf(sr.distance);
        if (idx >= 0) {
          excluded.splice(idx, 1);
        } else {
          excluded.push(sr.distance);
          excluded.sort((a, b) => a - b);
        }
        trigger.excluded_distances = excluded;

        const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
          action: "set_trigger",
          script: scriptName,
          trigger: trigger,
        });
        if (resp.ok !== false && resp.data) {
          _chainData = resp.data;
          seg = (_chainData.segments || {})[scriptName] || seg;
        }
        renderSegment(canvas, seg, _chainData, scriptName, null);
        showStatus(`Distance ${sr.distance} ${idx >= 0 ? "enabled" : "blocked"}`);
        return;
      }

      const cardinalRegions = getCardinalRegions();
      const cr = cardinalRegions.find(r => r.x === tile.tx && r.y === tile.ty);
      if (cr) {
        const excluded = trigger.excluded_cardinals || [];
        const idx = excluded.indexOf(cr.label);
        if (idx >= 0) {
          excluded.splice(idx, 1);
        } else {
          excluded.push(cr.label);
        }
        trigger.excluded_cardinals = excluded;

        const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
          action: "set_trigger",
          script: scriptName,
          trigger: trigger,
        });
        if (resp.ok !== false && resp.data) {
          _chainData = resp.data;
          seg = (_chainData.segments || {})[scriptName] || seg;
        }
        renderSegment(canvas, seg, _chainData, scriptName, null);
        showStatus(`${cr.label} tile ${idx >= 0 ? "enabled" : "disabled"}`);
        return;
      }
    }

    // --- Talk trigger: approach tiles ---
    if (triggerType === "talk") {
      const approachRegions = getApproachRegions();
      const ar = approachRegions.find(r => r.x === tile.tx && r.y === tile.ty);
      if (ar) {
        const tiles = trigger.approach_tiles || [];
        if (tiles[ar.index]) {
          tiles[ar.index].enabled = !tiles[ar.index].enabled;
        }

        const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
          action: "set_trigger",
          script: scriptName,
          trigger: trigger,
        });
        if (resp.ok !== false && resp.data) {
          _chainData = resp.data;
          seg = (_chainData.segments || {})[scriptName] || seg;
        }
        renderSegment(canvas, seg, _chainData, scriptName, null);
        const label = ar.facing;
        const nowEnabled = tiles[ar.index]?.enabled !== false;
        showStatus(`${label} approach ${nowEnabled ? "enabled" : "disabled"}`);
      }
    }
  });
}

function _wirePreviewCanvas(sequence, segments) {
  // Auto-select first segment if present
  if (sequence.length > 0) {
    _selectSegmentPreview(sequence[0].script, sequence[0].map, segments);
    // Highlight first flow box
    const firstBox = document.querySelector(`.chain-flow-box[data-script="${sequence[0].script}"]`);
    if (firstBox) firstBox.classList.add("chain-flow-selected");
  }
}

async function _removeSegment(scriptName) {
  if (!_chainData) return;
  const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
    action: "remove_segment",
    script: scriptName,
  });
  if (resp.ok !== false && resp.data) {
    _chainData = resp.data;
    renderChainDetail();
    showStatus(`Removed ${scriptName}`);
  } else {
    showStatus(`Failed to remove: ${resp.error || "unknown error"}`, true);
  }
}

async function _reorderSegments(fromIdx, toIdx) {
  if (!_chainData) return;
  const seq = [...(_chainData.sequence || [])];
  const [moved] = seq.splice(fromIdx, 1);
  seq.splice(toIdx, 0, moved);
  const newOrder = seq.map(e => e.script);

  const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
    action: "reorder",
    order: newOrder,
  });
  if (resp.ok !== false && resp.data) {
    _chainData = resp.data;
    renderChainDetail();
  }
}

async function _clearOverride(segment, actor) {
  if (!_chainData) return;
  const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
    action: "clear_override",
    segment,
    actor,
  });
  if (resp.ok !== false && resp.data) {
    _chainData = resp.data;
    renderChainDetail();
    showStatus("Override cleared");
  }
}

async function _syncChain() {
  if (!_chainData) return;
  showStatus("Syncing...");
  try {
    const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}/sync`, {});
    if (resp.ok !== false) {
      const data = resp.data || resp;
      const synced = data.segments_synced || 0;
      const skipped = data.segments_skipped || 0;
      showStatus(`Synced: ${synced} updated, ${skipped} unchanged`);

      // Show warnings if any
      const warnings = data.warnings || [];
      _showSyncWarnings(warnings);

      // Reload detail to show updated state, preserving selected segment
      const prevScript = _previewScript;
      const prevMap = _previewMap;
      await loadChainDetail(_chainData.chain);
      renderChainDetail();
      // Re-select the previously selected segment
      if (prevScript && _chainData) {
        const segments = _chainData.segments || {};
        if (segments[prevScript]) {
          _selectSegmentPreview(prevScript, prevMap || segments[prevScript].map, segments);
          // Re-highlight the flow box
          document.querySelectorAll(".chain-flow-box").forEach(b => b.classList.remove("chain-flow-selected"));
          const box = document.querySelector(`.chain-flow-box[data-script="${prevScript}"]`);
          if (box) box.classList.add("chain-flow-selected");
        }
      }
    } else {
      showStatus(`Sync failed: ${resp.error || "unknown"}`, true);
    }
  } catch (err) {
    showStatus(`Sync error: ${err.message}`, true);
  }
}

function _showSyncWarnings(warnings) {
  // Remove any existing warnings
  const existing = document.querySelector(".chain-sync-warnings");
  if (existing) existing.remove();

  if (!warnings.length) return;

  const container = document.getElementById("chains-status");
  if (!container) return;

  const div = document.createElement("div");
  div.className = "chain-sync-warnings";
  div.innerHTML = `
    <div class="chain-sync-warnings-header">
      <span>${warnings.length} warning${warnings.length !== 1 ? "s" : ""}</span>
      <button class="chain-sync-warnings-close" title="Dismiss">\u00D7</button>
    </div>
    <ul class="chain-sync-warnings-list">
      ${warnings.map(w => `<li>${esc(w)}</li>`).join("")}
    </ul>
  `;

  container.parentNode.insertBefore(div, container.nextSibling);

  div.querySelector(".chain-sync-warnings-close").addEventListener("click", () => div.remove());

  // Auto-dismiss after 10 seconds
  setTimeout(() => { if (div.parentNode) div.remove(); }, 10000);
}

// ---------------------------------------------------------------------------
// Create chain modal
// ---------------------------------------------------------------------------

function showCreateModal() {
  closeModal();
  const { el, close } = createModal("chains-modal", `
      <h3>New Chain</h3>
      <div class="viz-editor-field">
        <label for="chains-new-name">Chain Name</label>
        <input type="text" id="chains-new-name" placeholder="e.g., BusterSequence" autocomplete="off" />
      </div>
      <div class="viz-editor-field">
        <label for="chains-head-map">Head Script Map</label>
        <select id="chains-head-map" class="chains-select">
          <option value="">Select map...</option>
        </select>
      </div>
      <div class="viz-editor-field">
        <label for="chains-head-script">Head Script</label>
        <select id="chains-head-script" class="chains-select">
          <option value="">Select map first...</option>
        </select>
      </div>
      <p id="chains-new-error" style="color:var(--del-color,#f44);display:none;"></p>
      <div class="chains-modal-btns">
        <button class="btn-apply" id="chains-create-btn">Create</button>
        <button class="btn-cancel" id="chains-cancel-btn">Cancel</button>
      </div>
  `);

  el.querySelector("#chains-cancel-btn").addEventListener("click", close);

  // Populate map select
  const mapSel = el.querySelector("#chains-head-map");
  for (const m of (_maps || [])) {
    const opt = document.createElement("option");
    opt.value = m.name;
    opt.textContent = m.name;
    mapSel.appendChild(opt);
  }

  // When map selected, load scripts
  const scriptSel = el.querySelector("#chains-head-script");
  mapSel.addEventListener("change", async () => {
    scriptSel.innerHTML = `<option value="">Loading...</option>`;
    if (!mapSel.value) {
      scriptSel.innerHTML = `<option value="">Select map first...</option>`;
      return;
    }
    const resp = await api(`/scenes/${mapSel.value}`);
    const scripts = (resp.data?.scripts || resp.scripts || []);
    scriptSel.innerHTML = `<option value="">Select script...</option>`;
    for (const s of scripts) {
      const opt = document.createElement("option");
      opt.value = s.name;
      opt.textContent = s.name;
      scriptSel.appendChild(opt);
    }
    // Auto-fill chain name from head script
    const nameInput = el.querySelector("#chains-new-name");
    if (!nameInput.value && scripts.length > 0) {
      // Wait for user to pick
    }
  });

  scriptSel.addEventListener("change", () => {
    const nameInput = el.querySelector("#chains-new-name");
    if (!nameInput.value && scriptSel.value) {
      nameInput.value = scriptSel.value;
    }
  });

  // Create button
  el.querySelector("#chains-create-btn").addEventListener("click", async () => {
    const name = el.querySelector("#chains-new-name").value.trim();
    const headMap = mapSel.value;
    const headScript = scriptSel.value;
    const errEl = el.querySelector("#chains-new-error");

    if (!name) { errEl.textContent = "Name required"; errEl.style.display = "block"; return; }
    if (!headMap || !headScript) { errEl.textContent = "Select a head script"; errEl.style.display = "block"; return; }
    if (!/^[A-Za-z0-9_]+$/.test(name)) { errEl.textContent = "Name: letters, numbers, underscores only"; errEl.style.display = "block"; return; }

    const resp = await postApi("/chains", { name, head_script: headScript, head_map: headMap });
    if (resp.ok !== false) {
      close();
      await loadChains();
      renderChainList();
      showStatus(`Chain '${name}' created`);
      _openChainDetail(name);
    } else {
      errEl.textContent = resp.error || "Failed to create chain";
      errEl.style.display = "block";
    }
  });

  el.querySelector("#chains-new-name").focus();
}

// ---------------------------------------------------------------------------
// Add script to chain modal
// ---------------------------------------------------------------------------

async function _showAddScriptModal() {
  await loadMaps();
  closeModal();
  const { el, close } = createModal("chains-modal", `
      <h3>Add Script to Chain</h3>
      <div class="viz-editor-field">
        <label for="chains-add-map">Map</label>
        <select id="chains-add-map" class="chains-select">
          <option value="">Select map...</option>
        </select>
      </div>
      <div class="viz-editor-field">
        <label for="chains-add-script">Script</label>
        <select id="chains-add-script" class="chains-select">
          <option value="">Select map first...</option>
        </select>
      </div>
      <div class="chains-modal-btns">
        <button class="btn-apply" id="chains-add-confirm">Add</button>
        <button class="btn-cancel" id="chains-add-cancel">Cancel</button>
      </div>
  `);

  el.querySelector("#chains-add-cancel").addEventListener("click", close);

  const mapSel = el.querySelector("#chains-add-map");
  for (const m of (_maps || [])) {
    const opt = document.createElement("option");
    opt.value = m.name;
    opt.textContent = m.name;
    mapSel.appendChild(opt);
  }

  const scriptSel = el.querySelector("#chains-add-script");
  mapSel.addEventListener("change", async () => {
    scriptSel.innerHTML = `<option value="">Loading...</option>`;
    if (!mapSel.value) {
      scriptSel.innerHTML = `<option value="">Select map first...</option>`;
      return;
    }
    const resp = await api(`/scenes/${mapSel.value}`);
    const scripts = (resp.data?.scripts || resp.scripts || []);
    scriptSel.innerHTML = `<option value="">Select script...</option>`;
    for (const s of scripts) {
      const opt = document.createElement("option");
      opt.value = s.name;
      opt.textContent = s.name;
      scriptSel.appendChild(opt);
    }
  });

  el.querySelector("#chains-add-confirm").addEventListener("click", async () => {
    const mapName = mapSel.value;
    const scriptName = scriptSel.value;
    if (!mapName || !scriptName) return;

    const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
      action: "add_segment",
      script: scriptName,
      map: mapName,
    });
    if (resp.ok !== false && resp.data) {
      _chainData = resp.data;
      close();
      renderChainDetail();
      showStatus(`Added ${scriptName}`);
    } else {
      showStatus(`Failed: ${resp.error || "unknown"}`, true);
    }
  });
}

// ---------------------------------------------------------------------------
// Add cast member modal
// ---------------------------------------------------------------------------

function _showAddCastModal() {
  closeModal();

  // Build NPC picker options from chain's maps
  const maps = [];
  const seen = new Set();
  for (const entry of (_chainData?.sequence || [])) {
    if (!seen.has(entry.map)) {
      seen.add(entry.map);
      maps.push(entry.map);
    }
  }

  const { el, close } = createModal("chains-modal", `
      <h3>Add Cast Member</h3>
      <div class="viz-editor-field">
        <label for="chains-cast-name">Character Name</label>
        <input type="text" id="chains-cast-name" placeholder="e.g., Buster" autocomplete="off" />
        <small style="color:#888">Used as display name. ID is auto-derived (lowercase).</small>
      </div>
      <div class="chain-cast-npc-assignments" id="chain-cast-npc-assignments">
        <label>NPC Assignments</label>
        <p style="color:#888;font-size:0.85em">Assign which object_event on each map corresponds to this character.</p>
        ${maps.map(m => `
          <div class="chain-cast-map-row" data-map="${esc(m)}">
            <span class="chain-cast-map-label">${esc(m)}</span>
            <select class="chain-cast-npc-select chains-select" data-map="${esc(m)}">
              <option value="">Loading NPCs...</option>
            </select>
          </div>
        `).join("")}
      </div>
      <div class="chains-modal-btns">
        <button class="btn-apply" id="chains-cast-confirm">Add</button>
        <button class="btn-cancel" id="chains-cast-cancel">Cancel</button>
      </div>
  `);

  el.querySelector("#chains-cast-cancel").addEventListener("click", close);

  // Load NPCs for each map
  for (const mapName of maps) {
    api(`/scenes/${mapName}/npcs`).then(resp => {
      const sel = el.querySelector(`.chain-cast-npc-select[data-map="${mapName}"]`);
      if (!sel) return;
      const npcs = resp.data?.npcs || resp.npcs || [];
      sel.innerHTML = `<option value="">(none)</option>`;
      for (const npc of npcs) {
        const label = npc.script
          ? `#${npc.id} - ${npc.graphics_id} (${npc.script})`
          : `#${npc.id} - ${npc.graphics_id} @ ${npc.x},${npc.y}`;
        const opt = document.createElement("option");
        opt.value = npc.id;
        opt.textContent = label;
        sel.appendChild(opt);
      }
    }).catch(() => {
      const sel = el.querySelector(`.chain-cast-npc-select[data-map="${mapName}"]`);
      if (sel) sel.innerHTML = `<option value="">(failed to load)</option>`;
    });
  }

  el.querySelector("#chains-cast-confirm").addEventListener("click", async () => {
    const name = el.querySelector("#chains-cast-name").value.trim();
    if (!name) return;

    const castId = name.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");
    if (!castId) return;

    // Build events map: { mapName: { object_event_index: N, graphics_id: "" } }
    const events = { display_name: name };
    const selects = el.querySelectorAll(".chain-cast-npc-select");
    for (const sel of selects) {
      const mapName = sel.dataset.map;
      const npcId = parseInt(sel.value, 10);
      if (!isNaN(npcId) && npcId > 0) {
        events[mapName] = { object_event_index: npcId };
      }
    }

    const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
      action: "update_cast",
      cast_id: castId,
      events,
    });
    if (resp.ok !== false && resp.data) {
      _chainData = resp.data;
      close();
      renderChainDetail();
      showStatus(`Added cast: ${name}`);
    }
  });

  el.querySelector("#chains-cast-name").focus();
}

// ---------------------------------------------------------------------------
// Edit cast member modal (NPC reassignment)
// ---------------------------------------------------------------------------

function _showEditCastModal(castId, castData) {
  closeModal();

  const maps = [];
  const seen = new Set();
  for (const entry of (_chainData?.sequence || [])) {
    if (!seen.has(entry.map)) {
      seen.add(entry.map);
      maps.push(entry.map);
    }
  }

  const existingEvents = castData.events || {};

  const { el, close } = createModal("chains-modal", `
      <h3>Edit Cast: ${esc(castData.display_name || castId)}</h3>
      <div class="chain-cast-npc-assignments" id="chain-cast-edit-assignments">
        ${maps.map(m => `
          <div class="chain-cast-map-row" data-map="${esc(m)}">
            <span class="chain-cast-map-label">${esc(m)}</span>
            <select class="chain-cast-npc-select chains-select" data-map="${esc(m)}">
              <option value="">Loading NPCs...</option>
            </select>
          </div>
        `).join("")}
      </div>
      <div class="chains-modal-btns">
        <button class="btn-apply" id="chains-cast-edit-save">Save</button>
        <button class="btn-cancel" id="chains-cast-edit-cancel">Cancel</button>
      </div>
  `);

  el.querySelector("#chains-cast-edit-cancel").addEventListener("click", close);

  // Load NPCs and pre-select current assignments
  for (const mapName of maps) {
    api(`/scenes/${mapName}/npcs`).then(resp => {
      const sel = el.querySelector(`.chain-cast-npc-select[data-map="${mapName}"]`);
      if (!sel) return;
      const npcs = resp.data?.npcs || resp.npcs || [];
      sel.innerHTML = `<option value="">(none)</option>`;
      for (const npc of npcs) {
        const label = npc.script
          ? `#${npc.id} - ${npc.graphics_id} (${npc.script})`
          : `#${npc.id} - ${npc.graphics_id} @ ${npc.x},${npc.y}`;
        const opt = document.createElement("option");
        opt.value = npc.id;
        opt.textContent = label;
        // Pre-select if matches existing assignment
        const existing = existingEvents[mapName];
        if (existing && existing.object_event_index === npc.id) {
          opt.selected = true;
        }
        sel.appendChild(opt);
      }
    }).catch(() => {
      const sel = el.querySelector(`.chain-cast-npc-select[data-map="${mapName}"]`);
      if (sel) sel.innerHTML = `<option value="">(failed to load)</option>`;
    });
  }

  el.querySelector("#chains-cast-edit-save").addEventListener("click", async () => {
    const events = { display_name: castData.display_name || castId };
    const selects = el.querySelectorAll(".chain-cast-npc-select");
    for (const sel of selects) {
      const mapName = sel.dataset.map;
      const npcId = parseInt(sel.value, 10);
      if (!isNaN(npcId) && npcId > 0) {
        events[mapName] = { object_event_index: npcId };
      }
    }

    const resp = await postApi(`/chains/${encodeURIComponent(_chainData.chain)}`, {
      action: "update_cast",
      cast_id: castId,
      events,
    });
    if (resp.ok !== false && resp.data) {
      _chainData = resp.data;
      close();
      renderChainDetail();
      showStatus(`Updated cast: ${castData.display_name || castId}`);
    }
  });
}

// ---------------------------------------------------------------------------
// Delete confirmation
// ---------------------------------------------------------------------------

function _confirmDelete(name) {
  closeModal();
  const { el, close } = createModal("chains-modal", `
      <h3>Delete Chain</h3>
      <p>Delete chain <strong>${esc(name)}</strong>? This removes the .chain.json file. Scripts are not affected.</p>
      <div class="chains-modal-btns">
        <button class="btn-apply chain-delete-confirm" style="background:var(--del-color,#f44)">Delete</button>
        <button class="btn-cancel chain-delete-cancel">Cancel</button>
      </div>
  `);

  el.querySelector(".chain-delete-cancel").addEventListener("click", close);
  el.querySelector(".chain-delete-confirm").addEventListener("click", async () => {
    // Use fetch directly for DELETE method
    try {
      const resp = await fetch(`/api/chains/${encodeURIComponent(name)}`, { method: "DELETE" });
      const data = await resp.json();
      if (data.ok !== false) {
        close();
        await loadChains();
        renderChainList();
        showStatus(`Chain '${name}' deleted`);
      } else {
        showStatus(`Delete failed: ${data.error || "unknown"}`, true);
      }
    } catch (err) {
      showStatus(`Delete error: ${err.message}`, true);
    }
  });
}

// ---------------------------------------------------------------------------
// Discover chains
// ---------------------------------------------------------------------------

async function _discoverChains() {
  showStatus("Scanning for chain candidates...");
  try {
    const resp = await api("/chains/discover");
    if (resp.ok !== false && resp.data) {
      const suggestions = resp.data.suggestions || [];
      if (suggestions.length === 0) {
        showStatus("No chain candidates found (no goto/call references between scripts)");
        return;
      }
      _showDiscoverResults(suggestions);
    } else {
      showStatus("Discovery failed", true);
    }
  } catch (err) {
    showStatus(`Discovery error: ${err.message}`, true);
  }
}

function _showDiscoverResults(suggestions) {
  closeModal();

  let listHTML = "";
  for (const s of suggestions) {
    const scripts = s.sequence.map(e => `${e.script} (${e.map})`).join(" \u2192 ");
    listHTML += `
      <div class="chains-discover-item">
        <div><strong>${esc(s.head)}</strong> &mdash; ${s.sequence.length} scripts</div>
        <div style="color:#888;font-size:0.85em">${esc(scripts)}</div>
        <button class="btn-apply chains-discover-create" data-head="${esc(s.head)}"
                data-map="${esc(s.map)}" data-seq='${JSON.stringify(s.sequence)}'>
          Create Chain
        </button>
      </div>
    `;
  }

  const { el, close } = createModal("chains-modal", `
      <h3>Discovered Chain Candidates</h3>
      <div class="chains-discover-list">${listHTML}</div>
      <div class="chains-modal-btns">
        <button class="btn-cancel chains-discover-close">Close</button>
      </div>
  `);
  el.style.maxWidth = "600px";

  el.querySelector(".chains-discover-close").addEventListener("click", close);

  // Create buttons
  el.querySelectorAll(".chains-discover-create").forEach(btn => {
    btn.addEventListener("click", async () => {
      const head = btn.dataset.head;
      const map = btn.dataset.map;
      const seq = JSON.parse(btn.dataset.seq);

      // Create chain with head
      const resp = await postApi("/chains", { name: head, head_script: head, head_map: map });
      if (resp.ok === false) {
        showStatus(`Failed: ${resp.error}`, true);
        return;
      }

      // Add remaining segments
      for (let i = 1; i < seq.length; i++) {
        await postApi(`/chains/${encodeURIComponent(head)}`, {
          action: "add_segment",
          script: seq[i].script,
          map: seq[i].map,
        });
      }

      close();
      await loadChains();
      renderChainList();
      showStatus(`Created chain: ${head}`);
    });
  });
}

// ---------------------------------------------------------------------------
// Main render / cleanup
// ---------------------------------------------------------------------------

export async function render(container) {
  const hash = window.location.hash.slice(1) || "/chains";
  const parts = hash.split("/").filter(Boolean);
  _selectedChain = parts[1] || "";

  container.innerHTML = `
    <article class="chains-root">
      <header class="chains-header">
        <a href="#/scripts" class="chains-back-link">\u2190 Scripts</a>
        <h2>Chain Builder</h2>
        <div class="chains-header-actions">
          <button id="chains-discover-btn" class="chains-discover-btn" title="Scan scripts for goto/call references">Discover</button>
          <button id="chains-new-btn" class="chains-new-btn">+ New Chain</button>
        </div>
      </header>

      <div id="chains-status" class="chains-status" style="display:none;"></div>

      <div id="chains-list-wrap" style="display:block;">
        <div id="chains-grid" class="chains-grid"></div>
      </div>

      <div id="chains-detail-wrap" style="display:none;">
        <div id="chains-content"></div>
      </div>
    </article>
  `;

  document.getElementById("chains-new-btn").addEventListener("click", async () => {
    await loadMaps();
    showCreateModal();
  });
  document.getElementById("chains-discover-btn").addEventListener("click", _discoverChains);

  try {
    await loadChains();
    if (_selectedChain && _chains && _chains.some(c => c.name === _selectedChain || c === _selectedChain)) {
      await _openChainDetail(_selectedChain);
    } else {
      _selectedChain = "";
      renderChainList();
    }
  } catch (err) {
    container.innerHTML = `<article><p style="color:#f44">${esc(err.message)}</p></article>`;
  }
}

export function cleanup() {
  _chains = null;
  _selectedChain = "";
  _chainData = null;
  _maps = null;
  _dragSrc = null;
  _previewScript = "";
  _previewMap = "";
  if (_statusTimer) {
    clearTimeout(_statusTimer);
    _statusTimer = null;
  }
  closeModal();
}
