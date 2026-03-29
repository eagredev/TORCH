/**
 * comment.js — Editor for comment beats (# lines).
 */

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentText = data.text || "";

  bodyEl.innerHTML = `
    ${helpers.field("Comment", `<textarea id="viz-comment-text" rows="3" class="viz-raw-textarea">${helpers.esc(currentText)}</textarea>`)}
    <p class="viz-editor-info">Comments are ignored by the compiler. Use them to annotate your script.</p>
  `;

  return {
    apply() {
      const text = bodyEl.querySelector("#viz-comment-text").value.trim();
      return `# ${text}`;
    },
  };
}
