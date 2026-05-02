// emote.js — Emote beat editor with visual emote grid
// S233 — Phase 2 (Editors)

import { api } from "../../../app.js";

// ---------------------------------------------------------------------------
// Builtin emote visuals
// ---------------------------------------------------------------------------

const EMOTE_SYMBOLS = {
  "!":     { symbol: "!",  color: "#e53935", bold: true },
  "?":     { symbol: "?",  color: "#1e88e5", bold: true },
  "!!":    { symbol: "!!", color: "#e53935", bold: true },
  "x":     { symbol: "\u2716", color: "#e53935", bold: true },
  "heart": { symbol: "\u2665", color: "#e53935", bold: false },
  "love":  { symbol: "\u2665", color: "#e53935", bold: false },
  "...":   { symbol: "\u2026", color: "#666",    bold: false },
  "happy": { symbol: "\u266a", color: "#43a047", bold: false },
};

// ---------------------------------------------------------------------------
// render()
// ---------------------------------------------------------------------------

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentActor = data.actor || "player";
  const currentEmote = data.emote_name || data.emote || "!";

  let selectedEmote = currentEmote;

  // Actor select
  let html = helpers.field("Actor", helpers.buildActorSelect("viz-emote-actor", currentActor));

  // Placeholder for grid (filled after async fetch)
  html += `<div class="viz-editor-field"><label>Emote</label><div id="viz-emote-grid-wrap" class="viz-emote-grid">Loading...</div></div>`;

  bodyEl.innerHTML = html;

  // Fetch emotes and build grid
  const gridWrap = bodyEl.querySelector("#viz-emote-grid-wrap");
  _loadEmoteGrid(gridWrap, currentEmote).then(sel => {
    selectedEmote = sel || currentEmote;
  });

  // Track selection changes via delegation
  bodyEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".viz-emote-btn");
    if (!btn) return;
    const allBtns = bodyEl.querySelectorAll(".viz-emote-btn");
    for (const b of allBtns) b.classList.remove("active");
    btn.classList.add("active");
    selectedEmote = btn.dataset.emote;
  });

  return {
    apply() {
      const actor = bodyEl.querySelector("#viz-emote-actor").value;
      return `${actor} emote ${selectedEmote}`;
    },
  };
}

// ---------------------------------------------------------------------------
// Grid builder
// ---------------------------------------------------------------------------

async function _loadEmoteGrid(container, currentEmote) {
  // Start with builtins
  let emotes = Object.keys(EMOTE_SYMBOLS).map(name => ({
    name, builtin: true,
  }));

  // Fetch custom emotes from API
  try {
    const resp = await api("/data/emotes");
    if (resp && Array.isArray(resp.emotes)) {
      // Merge: API may include builtins and customs
      const builtinNames = new Set(Object.keys(EMOTE_SYMBOLS));
      for (const e of resp.emotes) {
        if (!builtinNames.has(e.name)) {
          emotes.push({ name: e.name, builtin: false });
        }
      }
    }
  } catch {
    // API unavailable — use builtins only
  }

  let html = "";
  for (const em of emotes) {
    const isActive = em.name === currentEmote ? " active" : "";
    const vis = EMOTE_SYMBOLS[em.name];
    let inner;
    if (vis) {
      const style = `color:${vis.color};${vis.bold ? "font-weight:bold" : ""}`;
      inner = `<span class="viz-emote-symbol" style="${style}">${_esc(vis.symbol)}</span>`;
    } else {
      inner = `<span class="viz-emote-symbol">${_esc(em.name)}</span><span class="viz-emote-badge">(c)</span>`;
    }
    html += `<button type="button" class="viz-emote-btn${isActive}" data-emote="${_esc(em.name)}" title="${_esc(em.name)}">${inner}</button>`;
  }
  container.innerHTML = html;
  return currentEmote;
}

function _esc(s) {
  if (!s) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
