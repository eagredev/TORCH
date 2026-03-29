// dialogue.js — Dialogue / Text beat editor
// S233 — Phase 2 (Editors)
// Handles beat types: dialogue, text

import { state } from "../state.js";

// ---------------------------------------------------------------------------
// GBA Preview renderer
// ---------------------------------------------------------------------------

const GBA_LINE_MAX = 18;

function _renderPreview(previewEl, text) {
  if (!previewEl) return;
  const box = previewEl.querySelector(".viz-gba-preview-box");
  const counter = previewEl.querySelector(".viz-gba-char-count");
  if (!box || !counter) return;

  // Split on literal \p (page) and \n (newline) as typed in the textarea
  const pages = text.split("\\p");
  let boxHTML = "";
  let counterHTML = "";
  let lineNum = 1;

  for (let p = 0; p < pages.length; p++) {
    if (p > 0) boxHTML += '<div class="viz-gba-page-break">--- page ---</div>';
    const lines = pages[p].split("\\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].replace(/\$$/g, ""); // strip trailing $
      const len = line.length;
      const warn = len > GBA_LINE_MAX ? " viz-gba-warn" : "";
      boxHTML += `<div class="viz-gba-line${warn}">${_esc(line) || "&nbsp;"}</div>`;
      counterHTML += `<div${warn ? ' class="viz-gba-warn"' : ""}>Line ${lineNum}: ${len}/${GBA_LINE_MAX} chars</div>`;
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
// Dialogue editor (msg / msgnpc)
// ---------------------------------------------------------------------------

function _renderDialogue(bodyEl, beat, data, helpers) {
  // Determine style from source line or data
  const srcLine = _getSourceLine(beat);
  const isMsgNpc = srcLine ? srcLine.trimStart().startsWith("msgnpc") : !data.label;
  const currentStyle = isMsgNpc ? "msgnpc" : "msg";
  const speaker = data.label || "";
  const text = _extractText(data);

  let html = "";

  // Style radio buttons
  html += `<div class="viz-editor-field"><label>Style</label>
    <div class="viz-ed-radios">
      <label><input type="radio" name="viz-dlg-style" value="msg" ${currentStyle === "msg" ? "checked" : ""} /> msg (speaker)</label>
      <label><input type="radio" name="viz-dlg-style" value="msgnpc" ${currentStyle === "msgnpc" ? "checked" : ""} /> msgnpc (no speaker)</label>
    </div>
  </div>`;

  // Speaker field (shown only for msg)
  html += `<div class="viz-editor-field viz-dlg-speaker" style="display:${currentStyle === "msg" ? "block" : "none"}">
    <label>Speaker</label>
    <input type="text" id="viz-dlg-speaker" value="${helpers.esc(speaker)}" placeholder="NPC name" />
  </div>`;

  // Text
  html += helpers.field("Text",
    `<textarea id="viz-dlg-text" rows="4" class="viz-ed-textarea">${helpers.esc(text)}</textarea>`
  );

  // GBA Preview
  html += `<div class="viz-gba-preview">
    <div class="viz-gba-preview-box"></div>
    <div class="viz-gba-char-count"></div>
  </div>`;

  bodyEl.innerHTML = html;

  // Wire up style toggle
  const speakerField = bodyEl.querySelector(".viz-dlg-speaker");
  const radios = bodyEl.querySelectorAll('input[name="viz-dlg-style"]');
  for (const r of radios) {
    r.addEventListener("change", () => {
      speakerField.style.display = r.value === "msg" ? "block" : "none";
    });
  }

  // Wire up GBA preview
  const textarea = bodyEl.querySelector("#viz-dlg-text");
  const preview = bodyEl.querySelector(".viz-gba-preview");
  _renderPreview(preview, textarea.value);
  textarea.addEventListener("input", () => _renderPreview(preview, textarea.value));

  return {
    apply() {
      const style = bodyEl.querySelector('input[name="viz-dlg-style"]:checked').value;
      let text = textarea.value;
      if (!text.endsWith("$")) text += "$";
      if (style === "msg") {
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
  const text = _extractText(data);

  let html = "";
  html += helpers.field("Label",
    `<input type="text" id="viz-txt-label" value="${helpers.esc(label)}" placeholder="TextLabel" />`
  );
  html += helpers.field("Text",
    `<textarea id="viz-txt-text" rows="4" class="viz-ed-textarea">${helpers.esc(text)}</textarea>`
  );
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
      let text = textarea.value;
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
  // Strip trailing $ for display
  if (t.endsWith("$")) t = t.slice(0, -1);
  return t;
}

function _getSourceLine(beat) {
  if (beat.source_line == null) return null;
  const lines = state.source.split("\n");
  return lines[beat.source_line] || null;
}
