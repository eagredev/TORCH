// dialogue.js — Dialogue / Text beat editor
// S233 — Phase 2 (Editors), redesigned 2026-03-30
// Handles beat types: dialogue, text

import { state } from "../state.js";

// ---------------------------------------------------------------------------
// GBA text constants
// ---------------------------------------------------------------------------

const GBA_LINE_MAX = 18;
const GBA_LINES_PER_BOX = 2;

// ---------------------------------------------------------------------------
// Conversion: natural text <-> escape-coded text
// ---------------------------------------------------------------------------

/**
 * Convert escape-coded text (with literal \n and \p) to natural text
 * for display in the textarea. \p → double newline, \n → single newline.
 */
function _toNatural(coded) {
  if (!coded) return "";
  // Strip trailing $
  let t = coded.endsWith("$") ? coded.slice(0, -1) : coded;
  // \p (page break) → double newline
  t = t.replace(/\\p/g, "\n\n");
  // \n (line break) → single newline
  t = t.replace(/\\n/g, "\n");
  return t;
}

/**
 * Convert natural text back to escape-coded text.
 * Double newline → \p, single newline → \n.
 */
function _toCoded(natural) {
  if (!natural) return "";
  // Double newline (with optional whitespace between) → \p
  let t = natural.replace(/\n\s*\n/g, "\\p");
  // Remaining single newlines → \n
  t = t.replace(/\n/g, "\\n");
  return t;
}

// ---------------------------------------------------------------------------
// GBA Preview renderer
// ---------------------------------------------------------------------------

function _renderPreview(previewEl, naturalText) {
  if (!previewEl) return;
  const box = previewEl.querySelector(".viz-gba-preview-box");
  const counter = previewEl.querySelector(".viz-gba-char-count");
  if (!box || !counter) return;

  // Convert natural text to coded for analysis
  const coded = _toCoded(naturalText);
  const pages = coded.split("\\p");
  let boxHTML = "";
  let counterHTML = "";
  let lineNum = 1;

  for (let p = 0; p < pages.length; p++) {
    if (p > 0) boxHTML += '<div class="viz-gba-page-break">---</div>';
    const lines = pages[p].split("\\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].replace(/\$$/g, "");
      const len = line.length;
      const warn = len > GBA_LINE_MAX ? " viz-gba-warn" : "";
      boxHTML += `<div class="viz-gba-line${warn}">${_esc(line) || "&nbsp;"}</div>`;
      counterHTML += `<div${warn ? ' class="viz-gba-warn"' : ""}>L${lineNum}: ${len}/${GBA_LINE_MAX}</div>`;
      lineNum++;
    }
  }

  box.innerHTML = boxHTML;
  counter.innerHTML = counterHTML;
}

function _esc(s) {
  if (!s) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Speaker auto-detection
// ---------------------------------------------------------------------------

/** Try to get the NPC speaker name from the script's cast (alias directives). */
function _detectSpeaker() {
  if (!state.source) return "";
  // Look for 'alias NAME npcN' — the first alias is typically the speaker
  const m = state.source.match(/^alias\s+(\w+)\s+npc/m);
  if (m) {
    // Capitalize first letter
    const name = m[1];
    return name.charAt(0).toUpperCase() + name.slice(1);
  }
  return "";
}

// ---------------------------------------------------------------------------
// render()
// ---------------------------------------------------------------------------

export function render(bodyEl, beat, helpers) {
  const isText = beat.type === "text";
  const data = beat.data || {};

  if (isText) {
    return _renderText(bodyEl, beat, data, helpers);
  }
  return _renderDialogue(bodyEl, beat, data, helpers);
}

// ---------------------------------------------------------------------------
// Dialogue editor (msg / msgnpc) — redesigned
// ---------------------------------------------------------------------------

function _renderDialogue(bodyEl, beat, data, helpers) {
  const srcLine = _getSourceLine(beat);
  const isMsgNpc = srcLine ? srcLine.trimStart().startsWith("msgnpc") : !data.label;
  const speaker = data.label || "";
  const rawText = _extractText(data);
  const naturalText = _toNatural(rawText);

  // Detect if this NPC has a speaker from the script's cast
  const autoSpeaker = _detectSpeaker();
  const hasSpeaker = !isMsgNpc && (speaker || autoSpeaker);

  let html = "";

  // Speaker toggle — simple checkbox + name field
  html += `<div class="viz-editor-field">
    <label class="viz-ed-speaker-toggle">
      <input type="checkbox" id="viz-dlg-has-speaker" ${hasSpeaker ? "checked" : ""} />
      Show speaker name
    </label>
  </div>`;

  html += `<div class="viz-editor-field viz-dlg-speaker" style="display:${hasSpeaker ? "flex" : "none"}">
    <label>Speaker</label>
    <input type="text" id="viz-dlg-speaker" value="${helpers.esc(speaker || autoSpeaker)}" placeholder="NPC name" />
  </div>`;

  // Natural text editing area
  html += `<div class="viz-editor-field">
    <label>Dialogue</label>
    <textarea id="viz-dlg-text" rows="5" class="viz-ed-textarea" placeholder="Type dialogue naturally.\nNew line = line break\nBlank line = new text box">${helpers.esc(naturalText)}</textarea>
    <div class="viz-ed-hint">Line break = new line in text box. Blank line = new text box (page).</div>
  </div>`;

  // GBA Preview
  html += `<div class="viz-gba-preview">
    <div class="viz-gba-preview-box"></div>
    <div class="viz-gba-char-count"></div>
  </div>`;

  bodyEl.innerHTML = html;

  // Wire up speaker toggle
  const speakerCheck = bodyEl.querySelector("#viz-dlg-has-speaker");
  const speakerField = bodyEl.querySelector(".viz-dlg-speaker");
  speakerCheck.addEventListener("change", () => {
    speakerField.style.display = speakerCheck.checked ? "flex" : "none";
  });

  // Wire up GBA preview with live update
  const textarea = bodyEl.querySelector("#viz-dlg-text");
  const preview = bodyEl.querySelector(".viz-gba-preview");
  _renderPreview(preview, textarea.value);
  textarea.addEventListener("input", () => _renderPreview(preview, textarea.value));

  return {
    apply() {
      const showSpeaker = speakerCheck.checked;
      let text = _toCoded(textarea.value);
      if (!text.endsWith("$")) text += "$";
      if (showSpeaker) {
        const sp = bodyEl.querySelector("#viz-dlg-speaker").value.trim();
        return sp ? `msg "${sp}: ${text}"` : `msg "${text}"`;
      }
      return `msgnpc "${text}"`;
    },
  };
}

// ---------------------------------------------------------------------------
// Text editor (text LABEL "content$")
// ---------------------------------------------------------------------------

function _renderText(bodyEl, beat, data, helpers) {
  const label = data.name || data.label || "";
  const rawText = _extractText(data);
  const naturalText = _toNatural(rawText);

  let html = "";
  html += helpers.field("Label",
    `<input type="text" id="viz-txt-label" value="${helpers.esc(label)}" placeholder="TextLabel" />`
  );
  html += `<div class="viz-editor-field">
    <label>Text</label>
    <textarea id="viz-txt-text" rows="5" class="viz-ed-textarea" placeholder="Type text naturally">${helpers.esc(naturalText)}</textarea>
    <div class="viz-ed-hint">Line break = \\n. Blank line = \\p (new text box).</div>
  </div>`;
  html += `<div class="viz-gba-preview">
    <div class="viz-gba-preview-box"></div>
    <div class="viz-gba-char-count"></div>
  </div>`;

  bodyEl.innerHTML = html;

  const textarea = bodyEl.querySelector("#viz-txt-text");
  const preview = bodyEl.querySelector(".viz-gba-preview");
  _renderPreview(preview, textarea.value);
  textarea.addEventListener("input", () => _renderPreview(preview, textarea.value));

  return {
    apply() {
      const lbl = bodyEl.querySelector("#viz-txt-label").value.trim() || "NewText";
      let text = _toCoded(textarea.value);
      if (!text.endsWith("$")) text += "$";
      return `text ${lbl} "${text}"`;
    },
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _extractText(data) {
  let t = data.text || data.content || "";
  if (t.endsWith("$")) t = t.slice(0, -1);
  return t;
}

function _getSourceLine(beat) {
  if (beat.source_line == null) return null;
  const lines = state.source.split("\n");
  return lines[beat.source_line] || null;
}
