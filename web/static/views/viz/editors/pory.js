/**
 * pory.js — Poryscript passthrough beat editor.
 *
 * Shows the raw Poryscript command in an editable textarea,
 * allowing direct read/edit of engine commands that don't have
 * dedicated TorScript syntax.
 */

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const rawLine = data.raw_line || data.content || "";

  bodyEl.innerHTML = `
    <div class="viz-editor-field">
      <label>Poryscript</label>
      <textarea id="pory-src" rows="3" class="viz-raw-textarea"
        spellcheck="false" autocomplete="off"
        style="font-family:monospace;font-size:13px;resize:vertical;"
      >${helpers.esc(rawLine)}</textarea>
    </div>
    <p class="viz-editor-info" style="margin-top:8px;font-size:0.72rem;color:var(--text-dim);">
      Raw Poryscript command. This is passed directly to the compiler
      without translation. Use this for engine commands that don't have
      TorScript equivalents.
    </p>
  `;

  // Auto-focus the textarea
  setTimeout(() => {
    const ta = bodyEl.querySelector("#pory-src");
    if (ta) { ta.focus(); ta.selectionStart = ta.selectionEnd = ta.value.length; }
  }, 50);

  return {
    apply() {
      const text = bodyEl.querySelector("#pory-src").value.trim();
      if (!text) return null;
      return `pory ${text}`;
    }
  };
}
