/**
 * structural.js — Info-only editors for structural close beats
 * (endif, endswitch, endchoice).
 */

const STRUCTURAL_INFO = {
  endif: {
    title: "End If",
    desc: "Closes an if/elif/else conditional block.",
    tip: "Every if must have a matching endif.",
  },
  endswitch: {
    title: "End Switch",
    desc: "Closes a switch/case block.",
    tip: "Every switch must have a matching endswitch.",
  },
  endchoice: {
    title: "End Choice",
    desc: "Closes a choice/option block and generates the compiled menu.",
    tip: "The choice block must have at least 2 options.",
  },
};

export function render(bodyEl, beat, helpers) {
  const info = STRUCTURAL_INFO[beat.type] || { title: beat.type, desc: "", tip: "" };

  bodyEl.innerHTML = `
    <div class="viz-simple-info">
      <p class="viz-simple-desc">${helpers.esc(info.desc)}</p>
      ${info.tip ? `<p class="viz-simple-tip"><strong>Tip:</strong> ${helpers.esc(info.tip)}</p>` : ""}
    </div>
  `;

  return {
    apply() {
      return beat.type;
    }
  };
}
