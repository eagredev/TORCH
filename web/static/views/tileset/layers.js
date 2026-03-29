/**
 * layers.js — Layer Setup Wizard for the Tileset Editor.
 * Extracted from metatiles.js. Guides the user through configuring
 * which metatiles have content that should render in front of the player.
 */

import { esc } from "../../utils.js";
import { renderStudioNavbar } from "../../studioNav.js";
import {
  state, emit,
  WIZARD_STARTED, WIZARD_EXITED, DIRTY_CHANGED,
  TILE_POSITIONS,
} from "./state.js";
import { renderMetatileTile, drawPlayerSilhouette } from "./renderer.js";

// ---------------------------------------------------------------------------
// Wizard helpers
// ---------------------------------------------------------------------------

export function isEmptyMetatile(mt) {
  if (!mt || !mt.tiles) return true;
  return mt.tiles.every(t => t.tile === 0 && t.palette === 0);
}

function isEmptyLayer(tiles, start, count) {
  for (let i = start; i < start + count; i++) {
    if (tiles[i] && (tiles[i].tile !== 0 || tiles[i].palette !== 0)) return false;
  }
  return true;
}

export function hasLayerChoice(mt) {
  if (!mt || !mt.tiles || mt.tiles.length < 12) return false;
  const hasBottom = !isEmptyLayer(mt.tiles, 0, 4);
  const hasMiddle = !isEmptyLayer(mt.tiles, 4, 4);
  const hasTop = !isEmptyLayer(mt.tiles, 8, 4);
  return (hasBottom ? 1 : 0) + (hasMiddle ? 1 : 0) + (hasTop ? 1 : 0) >= 2;
}

function _hasTopLayerContent(mt) {
  if (!mt || !mt.tiles || mt.tiles.length < 12) return false;
  return mt.tiles.slice(8, 12).some(t => t.tile !== 0 || t.palette !== 0);
}

export function wizardEligible() {
  return state.metatiles
    .filter(mt => !isEmptyMetatile(mt) && _hasTopLayerContent(mt))
    .map(mt => mt.id);
}

export function wizardUnconfigured() {
  return state.metatiles
    .filter(mt => !isEmptyMetatile(mt) && _hasTopLayerContent(mt)
                  && !state.pendingChanges.has(mt.id))
    .map(mt => mt.id);
}

// ---------------------------------------------------------------------------
// Wizard flow
// ---------------------------------------------------------------------------

export function startWizard(mode) {
  state.wizardMode = true;
  state.wizardIndex = 0;

  if (mode === "all") {
    state.wizardQueue = wizardEligible();
  } else if (mode === "from-selected" && state.selectedId != null) {
    const all = wizardEligible();
    const idx = all.indexOf(state.selectedId);
    state.wizardQueue = idx >= 0 ? all.slice(idx) : all;
  } else {
    state.wizardQueue = wizardUnconfigured();
    if (state.wizardQueue.length === 0) {
      _showWizardMenu("all_done");
      return;
    }
  }

  if (state.wizardQueue.length === 0) {
    _showWizardMenu("none_eligible");
    return;
  }

  emit(WIZARD_STARTED);
  renderWizard();
}

export function exitWizard() {
  state.wizardMode = false;
  state.wizardQueue = [];
  state.wizardIndex = 0;
  emit(WIZARD_EXITED);
}

function wizardSetAndNext(action, behavior) {
  const mtId = state.wizardQueue[state.wizardIndex];
  const mt = state.metatiles.find(m => m.id === mtId);
  if (mt) {
    const existing = state.pendingChanges.get(mtId) || {};
    if (action === "move") {
      existing.layer_action = "top_to_middle";
    } else if (action === "keep") {
      existing._reviewed = true;
    }
    if (behavior != null) existing.behavior = behavior;
    state.pendingChanges.set(mtId, existing);
  }
  state.wizardIndex++;
  if (state.wizardIndex >= state.wizardQueue.length) {
    renderWizardComplete();
  } else {
    renderWizard();
  }
}

function wizardSkip() {
  state.wizardIndex++;
  if (state.wizardIndex >= state.wizardQueue.length) {
    renderWizardComplete();
  } else {
    renderWizard();
  }
}

function wizardBack() {
  if (state.wizardIndex > 0) {
    state.wizardIndex--;
    renderWizard();
  }
}

// ---------------------------------------------------------------------------
// Wizard menu (shown when no tiles need configuration)
// ---------------------------------------------------------------------------

function _showWizardMenu(reason) {
  if (!state.container) return;
  const displayName = (state.secondaryName || state.primaryName)
    .replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  const allCount = wizardEligible().length;

  let html = renderStudioNavbar("Assets");
  html += `<div class="wiz-container"><div class="wiz-body" style="text-align:center;padding:2rem;">`;

  if (reason === "all_done") {
    html += `<p style="color:var(--text-primary);font-size:1.1rem;margin-bottom:0.5rem;">All multi-layer tiles in ${esc(displayName)} have been configured.</p>`;
    html += `<p style="color:var(--text-secondary);font-size:0.85rem;margin-bottom:1.5rem;">You can restart the wizard to review your choices.</p>`;
  } else {
    html += `<p style="color:var(--text-primary);font-size:1.1rem;margin-bottom:0.5rem;">No tiles need layer configuration.</p>`;
    html += `<p style="color:var(--text-secondary);font-size:0.85rem;margin-bottom:1.5rem;">All tiles have content on only one layer.</p>`;
  }

  if (allCount > 0) {
    html += `<button class="wiz-nav-btn" data-action="restart" style="margin:0.3rem;padding:0.5rem 1.2rem;">Start from beginning (${allCount} tiles)</button><br>`;
  }
  html += `<button class="wiz-nav-btn wiz-exit-btn" data-action="exit" style="margin:0.3rem;padding:0.5rem 1.2rem;">Back to Editor</button>`;
  html += `</div></div>`;

  state.container.innerHTML = html;

  state.container.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", () => {
      if (btn.dataset.action === "restart") startWizard("all");
      else exitWizard();
    });
  });
}

// ---------------------------------------------------------------------------
// Wizard step rendering
// ---------------------------------------------------------------------------

export function renderWizard() {
  if (!state.container) return;
  const mtId = state.wizardQueue[state.wizardIndex];
  const mt = state.metatiles.find(m => m.id === mtId);
  if (!mt) return;

  const displayName = (state.secondaryName || state.primaryName)
    .replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  const progress = state.wizardIndex + 1;
  const total = state.wizardQueue.length;
  const pct = Math.round((progress / total) * 100);

  let html = renderStudioNavbar("Assets");

  html += `<div class="wiz-container">`;
  html += `<div class="wiz-header">`;
  html += `<h2>Layer Setup Wizard</h2>`;
  const skipped = state.metatiles.filter(mt => !isEmptyMetatile(mt)).length - total;
  const skippedNote = skipped > 0 ? ` (${skipped} single-layer tiles auto-skipped)` : "";
  html += `<span class="wiz-subtitle">${esc(displayName)} &mdash; ${progress} of ${total} tiles${skippedNote}</span>`;
  html += `<div class="wiz-progress"><div class="wiz-progress-bar" style="width:${pct}%"></div></div>`;
  html += `</div>`;

  html += `<div class="wiz-body">`;
  html += `<p class="wiz-prompt">Which looks correct?</p>`;
  html += `<p style="font-size:0.8rem; color:var(--text-secondary); margin: -0.5rem 0 1rem; text-align:center;">`;
  html += `The <span style="color:rgba(60,180,255,0.9);">blue figure</span> is the player. Pick the version where the player is at the right depth.</p>`;

  html += `<div class="wiz-compare-row">`;

  html += `<button class="wiz-compare-btn" data-action="keep">`;
  html += `<canvas class="wiz-compare-canvas" id="wiz-cmp-overlap" width="16" height="16"></canvas>`;
  html += `<strong>Tile overlaps player</strong>`;
  html += `<span>Wall edge, counter top, railing, stair banister</span>`;
  html += `</button>`;

  html += `<button class="wiz-compare-btn" data-action="move">`;
  html += `<canvas class="wiz-compare-canvas" id="wiz-cmp-behind" width="16" height="16"></canvas>`;
  html += `<strong>Player on top</strong>`;
  html += `<span>Floor, carpet, stool, low table, solid wall</span>`;
  html += `</button>`;

  html += `</div>`;

  html += `<div class="wiz-extra-row">`;
  html += `<button class="wiz-extra-btn" data-action="move">Player can't reach this</button>`;
  html += `<button class="wiz-skip-btn" data-action="skip">Skip</button>`;
  html += `</div>`;

  html += `<div class="wiz-meta">Metatile #${mt.id} (0x${mt.id.toString(16).toUpperCase().padStart(3, "0")})</div>`;
  html += `</div>`;

  // Footer
  html += `<div class="wiz-footer">`;
  html += `<button class="wiz-nav-btn" data-action="back"${state.wizardIndex === 0 ? " disabled" : ""}>&larr; Back</button>`;
  html += `<button class="wiz-nav-btn wiz-exit-btn" data-action="exit">Exit Wizard</button>`;
  html += `<span class="wiz-changes">${state.pendingChanges.size} change${state.pendingChanges.size === 1 ? "" : "s"}</span>`;
  html += `</div>`;

  html += `</div>`;

  state.container.innerHTML = html;

  // Render comparison canvases
  const tiles = mt.tiles || [];

  const overlapCanvas = document.getElementById("wiz-cmp-overlap");
  if (overlapCanvas) {
    const ctx = overlapCanvas.getContext("2d");
    ctx.clearRect(0, 0, 16, 16);
    for (let i = 0; i < 4; i++)
      renderMetatileTile(ctx, tiles[i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
    for (let i = 0; i < 4; i++)
      renderMetatileTile(ctx, tiles[4 + i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
    drawPlayerSilhouette(ctx);
    for (let i = 0; i < 4; i++)
      renderMetatileTile(ctx, tiles[8 + i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
  }

  const behindCanvas = document.getElementById("wiz-cmp-behind");
  if (behindCanvas) {
    const ctx = behindCanvas.getContext("2d");
    ctx.clearRect(0, 0, 16, 16);
    for (let i = 0; i < 4; i++)
      renderMetatileTile(ctx, tiles[i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
    for (let i = 0; i < 4; i++)
      renderMetatileTile(ctx, tiles[4 + i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
    for (let i = 0; i < 4; i++)
      renderMetatileTile(ctx, tiles[8 + i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
    drawPlayerSilhouette(ctx);
  }

  // Bind events
  state.container.querySelectorAll(".wiz-compare-btn, .wiz-extra-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.action;
      const beh = btn.dataset.behavior ? parseInt(btn.dataset.behavior, 10) : undefined;
      wizardSetAndNext(action, beh);
    });
  });

  const skipBtn = state.container.querySelector(".wiz-skip-btn");
  if (skipBtn) skipBtn.addEventListener("click", wizardSkip);

  state.container.querySelectorAll(".wiz-nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.action;
      if (action === "back") wizardBack();
      else if (action === "exit") exitWizard();
    });
  });
}

// ---------------------------------------------------------------------------
// Wizard complete
// ---------------------------------------------------------------------------

function renderWizardComplete() {
  if (!state.container) return;

  const displayName = (state.secondaryName || state.primaryName)
    .replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  const changeCount = state.pendingChanges.size;

  let html = renderStudioNavbar("Assets");
  html += `<div class="wiz-container">`;
  html += `<div class="wiz-header"><h2>Wizard Complete</h2></div>`;
  html += `<div class="wiz-body" style="text-align:center; padding: 2rem;">`;
  html += `<p style="font-size: 1.2rem; color: var(--text-primary);">`;
  html += `You categorized <strong>${changeCount}</strong> metatile${changeCount === 1 ? "" : "s"} in ${esc(displayName)}.`;
  html += `</p>`;
  if (changeCount > 0) {
    html += `<p style="color: var(--text-secondary); margin-top: 0.5rem;">Changes are pending. Save them from the editor to apply.</p>`;
  }
  html += `<button class="wiz-nav-btn" data-action="done" style="margin-top: 1.5rem; font-size: 1rem; padding: 0.5rem 1.5rem;">Go to Editor</button>`;
  html += `</div></div>`;

  state.container.innerHTML = html;

  state.container.querySelector('[data-action="done"]').addEventListener("click", () => {
    exitWizard();
  });
}
