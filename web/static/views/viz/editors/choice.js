/**
 * choice.js — Editor for choice, option, and endchoice beats.
 *
 * choice: prompt text with GBA preview
 * option: option text
 * endchoice: info-only
 */

export function render(bodyEl, beat, helpers) {
  const btype = beat.type;
  const data = beat.data || {};

  if (btype === "choice") {
    return _renderChoice(bodyEl, data, helpers);
  } else if (btype === "option") {
    return _renderOption(bodyEl, data, helpers);
  } else if (btype === "endchoice") {
    return _renderEndchoice(bodyEl, helpers);
  }
  return _renderEndchoice(bodyEl, helpers);
}

function _renderChoice(bodyEl, data, helpers) {
  const prompt = data.prompt || "";

  bodyEl.innerHTML = `
    ${helpers.field("Prompt Text", `
      <textarea id="choice-prompt" class="viz-editor-input" rows="2"
                placeholder="What will you do?">${helpers.esc(prompt)}</textarea>
    `)}
    <p class="viz-simple-tip">Follow with option beats (2-6 options). 2 options use Yes/No, 3+ use a multichoice menu.</p>
  `;

  return {
    apply() {
      const text = bodyEl.querySelector("#choice-prompt").value.trim();
      if (!text) return null;
      return `choice "${text}"`;
    }
  };
}

function _renderOption(bodyEl, data, helpers) {
  const text = data.text || "";

  bodyEl.innerHTML = `
    ${helpers.field("Option Text", `
      <input type="text" id="option-text" class="viz-editor-input"
             value="${helpers.esc(text)}" placeholder="Option label">
    `)}
  `;

  return {
    apply() {
      const val = bodyEl.querySelector("#option-text").value.trim();
      if (!val) return null;
      return `option "${val}"`;
    }
  };
}

function _renderEndchoice(bodyEl, helpers) {
  bodyEl.innerHTML = `
    <div class="viz-simple-info">
      <p class="viz-simple-desc">Closes the choice block and generates the compiled options.</p>
    </div>
  `;
  return { apply() { return "endchoice"; } };
}
