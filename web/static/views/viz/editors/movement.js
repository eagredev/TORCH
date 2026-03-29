// movement.js — Movement beat editor (walk/run/slide/jump/face with parallel actions)
// S233 — Phase 2 (Editors)
// Handles beat types: move, movement

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DIR_VERBS = ["walk", "walkfast", "walkslow", "run", "slide", "face"];
const COUNT_VERBS = ["walk", "walkfast", "walkslow", "run", "slide", "jump"];
const LABEL_VERBS = ["do"];
const EMOTE_VERBS = ["emote"];
const ALL_VERBS = ["walk", "walkfast", "walkslow", "run", "slide", "jump", "face", "do", "emote"];
const VERB_LABELS = {
  walk: "Walk", walkfast: "Walk (fast)", walkslow: "Walk (slow)",
  run: "Run", slide: "Slide", jump: "Jump", face: "Face",
  do: "Run movement block", emote: "Emote",
};
const DIRECTIONS = ["up", "down", "left", "right"];

// ---------------------------------------------------------------------------
// render()
// ---------------------------------------------------------------------------

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};

  // Normalize actions to array
  let actions;
  if (Array.isArray(data.actions)) {
    actions = data.actions.map(a => ({ ...a }));
  } else {
    actions = [{ actor: data.actor || "player", verb: data.verb || "walk", direction: data.direction || "down", count: data.count || "1", label: data.label || "", emote_name: data.emote_name || "" }];
  }

  // Render all rows
  _renderRows(bodyEl, actions, helpers);

  return {
    apply() {
      const rows = bodyEl.querySelectorAll(".viz-move-row");
      const parts = [];
      for (const row of rows) {
        const actor = row.querySelector(".viz-move-actor").value;
        const verb = row.querySelector(".viz-move-verb").value;
        if (LABEL_VERBS.includes(verb)) {
          const labelInput = row.querySelector(".viz-move-label-input");
          const label = labelInput ? labelInput.value.trim() : "";
          if (!label) return null;
          parts.push(`${actor} do ${label}`);
        } else if (EMOTE_VERBS.includes(verb)) {
          const emoteInput = row.querySelector(".viz-move-emote-input");
          const emote = emoteInput ? emoteInput.value.trim() : "!";
          parts.push(`${actor} emote ${emote}`);
        } else {
          const tokens = [actor, verb];
          if (DIR_VERBS.includes(verb)) {
            const activeDir = row.querySelector(".viz-dir-btn.active");
            tokens.push(activeDir ? activeDir.dataset.dir : "down");
          }
          if (COUNT_VERBS.includes(verb)) {
            const countInput = row.querySelector(".viz-move-count-input");
            tokens.push(countInput ? countInput.value : "1");
          }
          parts.push(tokens.join(" "));
        }
      }
      return parts.join(" + ");
    },
  };
}

// ---------------------------------------------------------------------------
// Row rendering
// ---------------------------------------------------------------------------

function _renderRows(bodyEl, actions, helpers) {
  bodyEl.innerHTML = "";

  for (let i = 0; i < actions.length; i++) {
    _addRow(bodyEl, actions[i], i, actions.length, helpers);
  }

  // Parallel action explanation + add button
  const footer = document.createElement("div");
  footer.className = "viz-move-footer";
  footer.innerHTML = `<p class="viz-editor-info">Actions joined with + run simultaneously (parallel).</p>`;
  const addBtn = document.createElement("button");
  addBtn.className = "btn-cancel viz-move-add";
  addBtn.textContent = "+ Add parallel action";
  addBtn.addEventListener("click", () => {
    const idx = bodyEl.querySelectorAll(".viz-move-row").length;
    const newAction = { actor: "player", verb: "walk", direction: "down", count: "1" };
    const row = _buildRowEl(newAction, idx, helpers);
    bodyEl.insertBefore(row, footer);
    _updateRemoveButtons(bodyEl);
  });
  footer.appendChild(addBtn);
  bodyEl.appendChild(footer);
}

function _addRow(bodyEl, action, index, total, helpers) {
  const row = _buildRowEl(action, index, helpers);
  bodyEl.appendChild(row);
}

function _buildRowEl(action, index, helpers) {
  const row = document.createElement("div");
  row.className = "viz-move-row";
  row.dataset.row = index;

  const verb = action.verb || "walk";
  const showDir = DIR_VERBS.includes(verb);
  const showCount = COUNT_VERBS.includes(verb);
  const showLabel = LABEL_VERBS.includes(verb);
  const showEmote = EMOTE_VERBS.includes(verb);
  const dir = action.direction || "down";
  const count = action.count || "1";
  const label = action.label || "";
  const emoteName = action.emote_name || action.emote || "!";

  // Actor select
  const actorHTML = helpers.field("Actor",
    helpers.buildActorSelect(`viz-move-actor-${index}`, action.actor || "player")
      .replace("viz-ed-select", "viz-ed-select viz-move-actor")
  );

  // Verb select with descriptive labels
  const verbOptions = ALL_VERBS.map(v =>
    `<option value="${v}" ${v === verb ? "selected" : ""}>${VERB_LABELS[v] || v}</option>`
  ).join("");
  const verbHTML = helpers.field("Action",
    `<select class="viz-ed-select viz-move-verb">${verbOptions}</select>`
  );

  // Direction buttons
  const dirBtns = DIRECTIONS.map(d =>
    `<button type="button" class="viz-dir-btn${d === dir ? " active" : ""}" data-dir="${d}">${_dirArrow(d)}</button>`
  ).join("");
  const dirHTML = `<div class="viz-editor-field viz-move-dir" style="display:${showDir ? "block" : "none"}">
    <label>Direction</label>
    <div class="viz-dir-btns">${dirBtns}</div>
  </div>`;

  // Count input
  const countHTML = `<div class="viz-editor-field viz-move-count" style="display:${showCount ? "block" : "none"}">
    <label>Steps</label>
    <input type="number" class="viz-move-count-input" min="1" max="99" value="${helpers.esc(String(count))}" />
  </div>`;

  // Label input (for "do" verb — references a named movement block)
  const labelHTML = `<div class="viz-editor-field viz-move-label" style="display:${showLabel ? "block" : "none"}">
    <label>Movement Block</label>
    <input type="text" class="viz-move-label-input viz-ed-input" value="${helpers.esc(label)}" placeholder="MapName_BlockName" />
  </div>`;

  // Emote input (for "emote" verb)
  const emoteHTML = `<div class="viz-editor-field viz-move-emote" style="display:${showEmote ? "block" : "none"}">
    <label>Emote</label>
    <input type="text" class="viz-move-emote-input viz-ed-input" value="${helpers.esc(emoteName)}" placeholder="! or ? or heart" />
  </div>`;

  // Remove button
  const removeHTML = `<button type="button" class="viz-move-remove" title="Remove">\u00d7</button>`;

  row.innerHTML = actorHTML + verbHTML + dirHTML + countHTML + labelHTML + emoteHTML + removeHTML;

  // Wire up verb change → toggle relevant fields
  const verbSelect = row.querySelector(".viz-move-verb");
  const dirField = row.querySelector(".viz-move-dir");
  const countField = row.querySelector(".viz-move-count");
  const labelField = row.querySelector(".viz-move-label");
  const emoteField = row.querySelector(".viz-move-emote");
  verbSelect.addEventListener("change", () => {
    const v = verbSelect.value;
    dirField.style.display = DIR_VERBS.includes(v) ? "block" : "none";
    countField.style.display = COUNT_VERBS.includes(v) ? "block" : "none";
    labelField.style.display = LABEL_VERBS.includes(v) ? "block" : "none";
    emoteField.style.display = EMOTE_VERBS.includes(v) ? "block" : "none";
  });

  // Wire up direction buttons
  const dirBtnEls = row.querySelectorAll(".viz-dir-btn");
  for (const btn of dirBtnEls) {
    btn.addEventListener("click", () => {
      for (const b of dirBtnEls) b.classList.remove("active");
      btn.classList.add("active");
    });
  }

  // Wire up remove button
  row.querySelector(".viz-move-remove").addEventListener("click", () => {
    const parent = row.parentNode;
    row.remove();
    _updateRemoveButtons(parent);
  });

  return row;
}

function _updateRemoveButtons(container) {
  const rows = container.querySelectorAll(".viz-move-row");
  rows.forEach((row, i) => {
    row.dataset.row = i;
    const rmBtn = row.querySelector(".viz-move-remove");
    if (rmBtn) rmBtn.style.display = rows.length <= 1 ? "none" : "";
  });
}

function _dirArrow(dir) {
  switch (dir) {
    case "up": return "\u2191";
    case "down": return "\u2193";
    case "left": return "\u2190";
    case "right": return "\u2192";
    default: return dir;
  }
}
