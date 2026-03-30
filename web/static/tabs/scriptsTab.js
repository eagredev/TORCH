/**
 * TORCH IDE — Scripts Tab.
 * TORCH_MODULE
 *
 * Enhanced script list for the current map with beat counts.
 * Click to load in Scripts Mode or open in drawer.
 *
 * Tab API: init(container, mapName), update(mapName), onSelect(), onDeselect(), cleanup()
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import { ideEmit, IDE_OPEN_SCRIPT } from "../ide.js";

let _container = null;
let _currentMap = null;

export function init(container, mapName) {
  _container = container;
  _currentMap = mapName;
  if (mapName) _load(mapName);
  else _showEmpty();
}

export function update(mapName) {
  _currentMap = mapName;
  if (mapName) _load(mapName);
  else _showEmpty();
}

export function onSelect() {}
export function onDeselect() {}
export function cleanup() { _container = null; _currentMap = null; }

async function _load(mapName) {
  if (!_container) return;
  _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim);font-size:0.78rem">Loading scripts...</div>';

  try {
    const res = await api(`/scenes/${encodeURIComponent(mapName)}`);
    const scripts = res.ok ? (res.data?.scripts || []) : [];

    if (scripts.length === 0) {
      _container.innerHTML = `<div style="padding:0.8rem;color:var(--text-dim);text-align:center;font-size:0.78rem">
        No workspace scripts<br>
        <button class="ide-scripts-decompile-all" style="margin-top:0.5rem;padding:0.3rem 0.8rem;border:none;border-radius:4px;background:var(--accent);color:var(--bg-primary);cursor:pointer;font-size:0.72rem;font-weight:600">Decompile All Scripts</button>
        <span class="ide-scripts-decompile-status" style="display:block;margin-top:0.3rem;font-size:0.68rem"></span>
      </div>`;
      const btn = _container.querySelector(".ide-scripts-decompile-all");
      if (btn) {
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          btn.textContent = "Decompiling\u2026";
          const statusEl = _container.querySelector(".ide-scripts-decompile-status");
          const r = await postApi(`/npcs/${encodeURIComponent(mapName)}/decompile-all`, {});
          if (r && r.ok) {
            const d = r.data || {};
            const count = (d.imported || []).length;
            if (statusEl) { statusEl.textContent = `Imported ${count} script(s)`; statusEl.style.color = "var(--status-ok)"; }
            // Reload the list
            setTimeout(() => _load(mapName), 500);
          } else {
            btn.disabled = false;
            btn.textContent = "Decompile All Scripts";
            if (statusEl) { statusEl.textContent = r?.error || "Failed"; statusEl.style.color = "var(--status-error)"; }
          }
        });
      }
      return;
    }

    let html = `<div class="ide-scripts-tab-list">`;
    for (const s of scripts) {
      const name = s.name || s;
      const beats = s.beat_count ? `${s.beat_count} beats` : "";
      const icon = _typeIcon(s.type || "");
      html += `<div class="ide-script-row" data-map="${esc(mapName)}" data-script="${esc(name)}">`;
      html += `<span class="ide-script-icon">${icon}</span>`;
      html += `<span class="ide-script-name">${esc(name)}</span>`;
      if (beats) html += `<span class="ide-script-beats">${esc(beats)}</span>`;
      html += `</div>`;
    }
    html += `</div>`;

    // Footer
    html += `<div class="ide-scripts-tab-footer">`;
    html += `<button class="ide-scripts-tab-open">Open Script Browser</button>`;
    html += `</div>`;

    _container.innerHTML = html;

    // Wire clicks
    _container.querySelectorAll(".ide-script-row").forEach(row => {
      row.addEventListener("click", () => {
        ideEmit(IDE_OPEN_SCRIPT, {
          mapName: row.dataset.map,
          scriptName: row.dataset.script,
        });
      });
    });

    const openBtn = _container.querySelector(".ide-scripts-tab-open");
    if (openBtn) {
      openBtn.addEventListener("click", async () => {
        const { openToolModal } = await import("../toolbar.js");
        openToolModal("Scripts", () => import("../views/scripts.js"));
      });
    }
  } catch (_) {
    _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim)">Failed to load</div>';
  }
}

function _showEmpty() {
  if (_container) _container.innerHTML = '<div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.78rem">Select a map</div>';
}

function _typeIcon(type) {
  if (type === "cutscene" || type === "scene") return "\u{1F3AC}";
  if (type === "dialogue" || type === "flavor") return "\u{1F4AC}";
  if (type === "setup" || type === "mapscript") return "\u2699";
  return "\u{1F4C4}";
}
