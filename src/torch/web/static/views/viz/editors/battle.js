/**
 * battle.js — Battle beat editor.
 *
 * Compact layout: type + trainer on one row, then tabbed text fields
 * (Intro / Defeated / Post-Battle) with GBA preview — one at a time.
 */

import { openToolModal } from "../../../toolbar.js";

const BATTLE_TYPES = [
  "trainerbattle_single",
  "trainerbattle_double",
  "trainerbattle_rematch",
  "trainerbattle_no_intro",
];

const TEXT_TABS = [
  { key: "intro",      label: "Intro",       hint: "before battle" },
  { key: "defeated",   label: "Defeated",    hint: "player wins" },
  { key: "postbattle", label: "Post-Battle", hint: "talk again" },
];

const GBA_LINE_MAX = 18;

function _esc(s) {
  if (!s) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function _toNatural(coded) {
  if (!coded) return "";
  let t = coded.endsWith("$") ? coded.slice(0, -1) : coded;
  t = t.replace(/\\p/g, "\n\n");
  t = t.replace(/\\n/g, "\n");
  return t;
}

function _toCoded(natural) {
  if (!natural) return "";
  let t = natural.replace(/\n\s*\n/g, "\\p");
  t = t.replace(/\n/g, "\\n");
  return t;
}

function _renderGbaPreview(previewEl, naturalText) {
  if (!previewEl) return;
  const coded = _toCoded(naturalText);
  const pages = coded.split("\\p");
  let html = "";
  for (let p = 0; p < pages.length; p++) {
    if (p > 0) html += '<div class="viz-gba-page-break">---</div>';
    const lines = pages[p].split("\\n");
    for (const line of lines) {
      const clean = line.replace(/\$$/g, "");
      const warn = clean.length > GBA_LINE_MAX ? " viz-gba-warn" : "";
      html += `<div class="viz-gba-line${warn}">${_esc(clean) || "&nbsp;"}</div>`;
    }
  }
  previewEl.innerHTML = html;
}

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentType = data.battle_type || "trainerbattle_single";
  const currentArgs = data.args || "";

  const trainerConst = currentArgs.split(",")[0].trim();
  const displayType = currentType.replace("trainerbattle_", "");

  const options = BATTLE_TYPES.map(bt => {
    const label = bt.replace("trainerbattle_", "");
    return `<option value="${bt}" ${bt === currentType ? "selected" : ""}>${label}</option>`;
  }).join("");

  // Extra args beyond trainer const (e.g. rematch callbacks), excluding quoted text
  const extraParts = currentArgs.split(",").slice(1).map(s => s.trim()).filter(s => s && !s.startsWith('"'));
  const extraArgs = extraParts.join(", ");

  // Collect text values
  const texts = {};
  for (const tab of TEXT_TABS) {
    texts[tab.key] = _toNatural(data[tab.key] || "");
  }

  // Build tab buttons
  const tabBtns = TEXT_TABS.map((tab, i) =>
    `<button class="viz-btl-tab${i === 0 ? " viz-btl-tab-active" : ""}" data-tab="${tab.key}">${tab.label}</button>`
  ).join("");

  let html = `
    <div class="viz-btl-row">
      <select id="battle-type" class="viz-btl-select">${options}</select>
      <input type="text" id="battle-trainer" class="viz-btl-trainer" value="${_esc(trainerConst)}" placeholder="TRAINER_CONSTANT" />
      ${trainerConst.startsWith("TRAINER_") ? `<button id="battle-view-trainer" class="viz-btl-card-btn" title="View Trainer Card">\u2197</button>` : ""}
    </div>
    ${extraArgs ? `<input type="text" id="battle-extra" class="viz-btl-extra" value="${_esc(extraArgs)}" placeholder="Extra args" />` : ""}
    <div class="viz-btl-tabs">${tabBtns}</div>
    <div class="viz-btl-text-area">
      <textarea id="battle-text" rows="3" class="viz-btl-textarea" placeholder="${TEXT_TABS[0].hint}">${_esc(texts[TEXT_TABS[0].key])}</textarea>
      <div class="viz-btl-preview"></div>
    </div>
  `;

  bodyEl.innerHTML = html;

  // State
  let activeTab = TEXT_TABS[0].key;
  const savedTexts = { ...texts };
  const textarea = bodyEl.querySelector("#battle-text");
  const preview = bodyEl.querySelector(".viz-btl-preview");
  const tabButtons = bodyEl.querySelectorAll(".viz-btl-tab");

  // Initial preview
  _renderGbaPreview(preview, textarea.value);

  // Tab switching
  for (const btn of tabButtons) {
    btn.addEventListener("click", () => {
      // Save current
      savedTexts[activeTab] = textarea.value;
      // Switch
      activeTab = btn.dataset.tab;
      const tab = TEXT_TABS.find(t => t.key === activeTab);
      textarea.value = savedTexts[activeTab] || "";
      textarea.placeholder = tab ? tab.hint : "";
      _renderGbaPreview(preview, textarea.value);
      // Update active style
      for (const b of tabButtons) b.classList.remove("viz-btl-tab-active");
      btn.classList.add("viz-btl-tab-active");
    });
  }

  // Live preview
  textarea.addEventListener("input", () => {
    _renderGbaPreview(preview, textarea.value);
  });

  // Trainer card button
  const trainerBtn = bodyEl.querySelector("#battle-view-trainer");
  if (trainerBtn) {
    trainerBtn.addEventListener("click", () => {
      const tc = bodyEl.querySelector("#battle-trainer")?.value.trim() || trainerConst;
      openToolModal("Trainer", () => import("../../trainers.js"), { trainerConst: tc });
    });
  }

  return {
    apply() {
      // Save current tab text
      savedTexts[activeTab] = textarea.value;

      const btype = bodyEl.querySelector("#battle-type").value;
      const trainer = bodyEl.querySelector("#battle-trainer")?.value.trim();
      if (!trainer) return null;

      const intro = _toCoded(savedTexts.intro || "");
      const defeated = _toCoded(savedTexts.defeated || "");
      const post = _toCoded(savedTexts.postbattle || "");
      const extra = bodyEl.querySelector("#battle-extra")?.value.trim() || "";

      if (intro || defeated || post) {
        let result = extra ? `${btype} ${trainer}, ${extra}` : `${btype} ${trainer}`;
        if (intro) result += `\n  intro "${intro}$"`;
        if (defeated) result += `\n  defeated "${defeated}$"`;
        if (post) result += `\n  postbattle "${post}$"`;
        return result;
      }

      const args = extra ? `${trainer}, ${extra}` : trainer;
      return `${btype} ${args}`;
    }
  };
}
