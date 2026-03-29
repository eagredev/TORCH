// source.js — Collapsible source view with syntax highlighting
// S235 — Phase 2 (Editors)

import { state, on, off, SOURCE_CHANGED, BEAT_CHANGED, FRAMES_UPDATED } from "./state.js";

// ---------------------------------------------------------------------------
// Syntax highlighting rules (ordered by priority)
// ---------------------------------------------------------------------------

const HIGHLIGHT_RULES = [
  { cls: "src-comment",  rx: /#.*$/m },
  { cls: "src-string",   rx: /"[^"]*"/g },
  { cls: "src-dialogue", rx: /\b(msg|msgnpc|text)\b/g },
  { cls: "src-move",     rx: /\b(walk|walkfast|walkslow|run|slide|jump|face|setpos|hide|show)\b/g },
  { cls: "src-effect",   rx: /\b(emote|shake|cry|fanfare)\b/g },
  { cls: "src-screen",   rx: /\b(fade|sound|music|pause)\b/g },
  { cls: "src-flow",     rx: /\b(flag|var|gotoif|goto|call|end|release|return)\b/g },
  { cls: "src-battle",   rx: /\b(battle)\b/g },
  { cls: "src-label",    rx: /^\s*(label\s+\S+)/m },
  { cls: "src-alias",    rx: /^\s*(alias\s+\S+\s+\S+)/m },
  { cls: "src-struct",   rx: /\b(lock|faceplayer|closemessage|waitstate|special)\b/g },
  { cls: "src-raw",      rx: /\b(pory|raw)\b/g },
];

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _container = null;
let _pre = null;
let _toggleBtn = null;
let _body = null;
let _expanded = false;
let _handlers = [];
let _debounceTimer = null;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function init(containerEl) {
  _container = containerEl;

  // Restore persisted state
  _expanded = localStorage.getItem("torch-viz-source") === "1";

  // Build panel HTML
  const panel = document.createElement("div");
  panel.className = "viz-source-panel";

  const header = document.createElement("div");
  header.className = "viz-source-header";

  _toggleBtn = document.createElement("button");
  _toggleBtn.className = "viz-source-toggle";
  _toggleBtn.title = "Toggle source view";
  _toggleBtn.textContent = _expanded ? "Source \u25be" : "Source \u25b8";
  header.appendChild(_toggleBtn);

  _body = document.createElement("div");
  _body.className = "viz-source-body";
  _body.style.display = _expanded ? "" : "none";

  _pre = document.createElement("pre");
  _pre.className = "viz-source-pre";
  _body.appendChild(_pre);

  panel.appendChild(header);
  panel.appendChild(_body);
  _container.appendChild(panel);

  // Toggle handler
  _toggleBtn.addEventListener("click", _toggle);

  // Event bus subscriptions
  _handlers = [
    { name: SOURCE_CHANGED, handler: on(SOURCE_CHANGED, _scheduleRender) },
    { name: BEAT_CHANGED,   handler: on(BEAT_CHANGED, _scheduleRender) },
    { name: FRAMES_UPDATED, handler: on(FRAMES_UPDATED, _scheduleRender) },
  ];

  // Initial render
  if (_expanded) _renderSource();
}

export function cleanup() {
  for (const { name, handler } of _handlers) {
    off(name, handler);
  }
  _handlers = [];

  if (_toggleBtn) {
    _toggleBtn.removeEventListener("click", _toggle);
  }

  if (_debounceTimer) {
    clearTimeout(_debounceTimer);
    _debounceTimer = null;
  }

  _container = null;
  _pre = null;
  _toggleBtn = null;
  _body = null;
}

// ---------------------------------------------------------------------------
// Expand / collapse
// ---------------------------------------------------------------------------

function _toggle() {
  _expanded = !_expanded;
  localStorage.setItem("torch-viz-source", _expanded ? "1" : "0");
  _toggleBtn.textContent = _expanded ? "Source \u25be" : "Source \u25b8";
  _body.style.display = _expanded ? "" : "none";

  if (_expanded) {
    _renderSource();
  } else {
    _pre.innerHTML = "";
  }

  // Notify shell for mutual exclusivity
  _container.dispatchEvent(new CustomEvent("source-panel-toggled", {
    bubbles: true,
    detail: { expanded: _expanded },
  }));
}

// ---------------------------------------------------------------------------
// Debounced rendering
// ---------------------------------------------------------------------------

function _scheduleRender() {
  if (_debounceTimer) clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(_renderSource, 100);
}

function _renderSource() {
  if (!_expanded || !_pre) return;
  const source = state.source;
  if (!source) {
    _pre.innerHTML = '<span class="src-empty">No source loaded</span>';
    return;
  }

  const lines = source.split("\n");
  const frame = state.frames[state.currentBeat];
  const sl = frame?.beat?.source_line ?? -1;
  const el = frame?.beat?.source_end_line ?? sl;

  let html = "";
  for (let i = 0; i < lines.length; i++) {
    const isCurrent = sl >= 0 && i >= sl && i < el;
    const cls = isCurrent ? "src-line src-current-line" : "src-line";
    const highlighted = _highlight(lines[i]);
    html += `<div class="${cls}"><span class="src-line-num">${i + 1}</span>${highlighted}</div>`;
  }
  _pre.innerHTML = html;

  // Auto-scroll to current line
  if (sl >= 0) {
    const currentEl = _pre.querySelector(".src-current-line");
    if (currentEl) {
      currentEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }
}

// ---------------------------------------------------------------------------
// Syntax highlighting (marker technique to prevent double-wrapping)
// ---------------------------------------------------------------------------

function _highlight(line) {
  let escaped = _esc(line);
  const markers = [];

  for (const rule of HIGHLIGHT_RULES) {
    // Clone regex to reset lastIndex for /g patterns
    const rx = new RegExp(rule.rx.source, rule.rx.flags);
    escaped = escaped.replace(rx, (match) => {
      const id = markers.length;
      markers.push({ cls: rule.cls, text: match });
      return `\x00${id}\x01`;
    });
  }

  // Replace markers with spans
  for (let i = 0; i < markers.length; i++) {
    escaped = escaped.replace(`\x00${i}\x01`, `<span class="${markers[i].cls}">${markers[i].text}</span>`);
  }
  return escaped;
}

function _esc(s) {
  if (!s) return "";
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
