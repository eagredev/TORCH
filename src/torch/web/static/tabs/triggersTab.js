/**
 * TORCH IDE -- Triggers Tab.
 * TORCH_MODULE
 *
 * Lists all coord_events (triggers) on the current map.
 * Click trigger -> highlights on canvas. "Add Trigger" button opens wizard.
 * Edit/delete controls per trigger.
 *
 * Tab API: init(container, mapName), update(mapName), onSelect(), onDeselect(), cleanup()
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import {
  ideOn, ideEmit,
  IDE_EVENT_SELECTED,
} from "../ide.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _currentMap = null;
let _active = false;
let _unsubs = [];
let _triggers = null;

// ---------------------------------------------------------------------------
// Tab API
// ---------------------------------------------------------------------------

export function init(container, mapName) {
  _container = container;
  _currentMap = mapName;
  _active = true;

  _unsubs.push(ideOn(IDE_EVENT_SELECTED, _onCanvasSelect));
  _unsubs.push(ideOn("ide:event-updated", _onEventUpdated));

  if (mapName) _load(mapName);
  else _showEmpty();
}

export function update(mapName) {
  _currentMap = mapName;
  _triggers = null;
  if (mapName) _load(mapName);
  else _showEmpty();
}

export function onSelect() { _active = true; }
export function onDeselect() { _active = false; }

export function cleanup() {
  for (const unsub of _unsubs) unsub();
  _unsubs = [];
  _container = null;
  _currentMap = null;
  _triggers = null;
  _active = false;
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function _load(mapName) {
  if (!_container) return;
  _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim);font-size:0.78rem">Loading triggers...</div>';

  try {
    const res = await api(`/map/${encodeURIComponent(mapName)}/triggers`);
    if (res?.ok) {
      _triggers = res.data.triggers || [];
      _render();
    } else {
      _showEmpty();
    }
  } catch (_) {
    _showEmpty();
  }
}

// ---------------------------------------------------------------------------
// Canvas sync
// ---------------------------------------------------------------------------

function _onCanvasSelect(detail) {
  if (!_active || !_container || !detail || detail.type !== "trigger") return;
  const idx = detail.data?.id ?? detail.data?._index;
  if (idx == null) return;

  _container.querySelectorAll(".ide-trig-row").forEach(row => {
    row.classList.toggle("highlighted", row.dataset.trigIdx === String(idx));
  });

  const target = _container.querySelector(`.ide-trig-row[data-trig-idx="${idx}"]`);
  if (target) target.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function _onEventUpdated() {
  // Refresh after inline edits
  if (_active && _currentMap) _load(_currentMap);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_container) return;

  const triggers = _triggers || [];

  let html = "";

  // Add Trigger button
  html += `<div class="ide-trig-toolbar">
    <button class="ide-trig-add-btn" title="Create a new trigger">+ Add Trigger</button>
  </div>`;

  if (triggers.length === 0) {
    html += '<div style="padding:0.8rem;color:var(--text-dim);text-align:center;font-size:0.78rem">No triggers on this map</div>';
    _container.innerHTML = html;
    _wireAddButton();
    return;
  }

  html += '<div class="ide-trig-list">';
  for (const t of triggers) {
    const gateText = (t.var === "0" && t.var_value === "0")
      ? "always"
      : `${t.var}=${t.var_value}`;
    const script = t.script || "(none)";

    html += `<div class="ide-trig-row" data-trig-idx="${t.index}">`;
    html += `<div class="ide-trig-icon">T</div>`;
    html += `<div class="ide-trig-info">`;
    html += `<div class="ide-trig-label">${esc(script)}</div>`;
    html += `<div class="ide-trig-meta">(${t.x}, ${t.y}) gate: ${esc(gateText)}</div>`;
    html += `</div>`;
    html += `<button class="ide-trig-del" data-idx="${t.index}" title="Delete trigger">&times;</button>`;
    html += `</div>`;
  }
  html += '</div>';

  html += `<div class="ide-trig-footer">
    <span class="ide-trig-count">${triggers.length} trigger${triggers.length !== 1 ? "s" : ""}</span>
  </div>`;

  _container.innerHTML = html;

  _wireAddButton();

  // Wire row clicks -> select on canvas
  _container.querySelectorAll(".ide-trig-row").forEach(row => {
    row.addEventListener("click", (e) => {
      if (e.target.classList.contains("ide-trig-del")) return;
      const idx = parseInt(row.dataset.trigIdx, 10);
      const trig = triggers.find(t => t.index === idx);
      if (trig) {
        ideEmit(IDE_EVENT_SELECTED, { type: "trigger", data: { ...trig, id: idx } });
        _container.querySelectorAll(".ide-trig-row").forEach(r => r.classList.remove("highlighted"));
        row.classList.add("highlighted");
      }
    });
  });

  // Wire delete buttons
  _container.querySelectorAll(".ide-trig-del").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const idx = btn.dataset.idx;
      const trig = triggers.find(t => t.index === parseInt(idx, 10));
      const label = trig ? trig.script || `Trigger #${idx}` : `Trigger #${idx}`;

      if (!confirm(`Delete ${label}?`)) return;

      btn.textContent = "...";
      btn.disabled = true;

      try {
        const res = await fetch(`/api/map/${encodeURIComponent(_currentMap)}/triggers/${idx}`, {
          method: "DELETE",
        });
        const data = await res.json();
        if (data.ok) {
          _load(_currentMap);
          ideEmit("ide:event-updated", { mapName: _currentMap });
        } else {
          btn.textContent = "!";
          btn.disabled = false;
        }
      } catch (_) {
        btn.textContent = "!";
        btn.disabled = false;
      }
    });
  });
}

function _wireAddButton() {
  const addBtn = _container?.querySelector(".ide-trig-add-btn");
  if (!addBtn || !_currentMap) return;

  addBtn.addEventListener("click", async () => {
    const { openTriggerWizard } = await import("../views/triggerWizard.js");
    openTriggerWizard(_currentMap, () => {
      _load(_currentMap);
      ideEmit("ide:event-updated", { mapName: _currentMap });
    });
  });
}

function _showEmpty() {
  if (!_container) return;
  _container.innerHTML = '<div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.78rem">Select a map to see triggers</div>';
}
