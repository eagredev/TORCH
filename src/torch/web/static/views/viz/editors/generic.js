/**
 * generic.js — Fallback raw source editor for unhandled beat types.
 */

import { state } from "../state.js";

export function render(bodyEl, beat, helpers) {
  // Extract original source lines for this beat
  const lines = state.source.split("\n");
  const sl = beat.source_line;
  const el = beat.source_end_line != null ? beat.source_end_line : sl + 1;
  const original = lines.slice(sl, el).join("\n");

  const isMultiline = el - sl > 1;
  const rows = isMultiline ? Math.min(el - sl + 1, 10) : 2;

  bodyEl.innerHTML = `
    <div class="viz-editor-field">
      <label>Source (TorScript)</label>
      <textarea id="viz-raw-src" rows="${rows}" class="viz-raw-textarea">${helpers.esc(original)}</textarea>
    </div>
    <p class="viz-editor-info">Edit the raw TorScript source directly. One line per simple beat, multiple lines for blocks.</p>
  `;

  return {
    apply() {
      const text = bodyEl.querySelector("#viz-raw-src").value.trim();
      if (!text) return null;
      return text;
    }
  };
}
