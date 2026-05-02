/**
 * simple.js — Contextual info editor for parameterless beats
 * (lock, faceplayer, closemessage, waitstate).
 */

const SIMPLE_INFO = {
  lock: {
    title: "Lock",
    desc: "Freezes the player and all NPCs in place. Movement inputs are ignored until the script calls release or ends.",
    tip: "Usually placed at the start of a cutscene, paired with release at the end.",
  },
  faceplayer: {
    title: "Face Player",
    desc: "The speaking NPC turns to face the player character. The direction is calculated automatically based on relative positions.",
    tip: "Place this at the start of a conversation, after lock.",
  },
  closemessage: {
    title: "Close Message",
    desc: "Closes the current dialogue textbox. The textbox stays open after the last msg/msgnpc until explicitly closed.",
    tip: "Always close the message before movement beats or fades.",
  },
  waitstate: {
    title: "Wait State",
    desc: "Pauses script execution until the current special function finishes its animation or task.",
    tip: "Required after most special calls that have visible effects (e.g., healing, item fanfares).",
  },
};

export function render(bodyEl, beat, helpers) {
  const info = SIMPLE_INFO[beat.type] || { title: beat.type, desc: "", tip: "" };

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
