/**
 * sound.js — Handles sound, music, fanfare, and cry beat types.
 */

import { api } from "../../../app.js";

const AUDIO_CONFIG = {
  sound:   { endpoint: "/data/sounds", key: "sounds",  label: "Sound Effect", prefix: "SE_" },
  cry:     { endpoint: "/data/sounds", key: "sounds",  label: "Pokemon Cry",  prefix: "SE_" },
  music:   { endpoint: "/data/music",  key: "music",   label: "Music",        prefix: "MUS_" },
  fanfare: { endpoint: "/data/music",  key: "music",   label: "Fanfare",      prefix: "MUS_" },
};

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const config = AUDIO_CONFIG[beat.type] || AUDIO_CONFIG.sound;
  const currentConstant = data.constant || data.name || data.sound || "";

  bodyEl.innerHTML = `
    ${helpers.field(config.label, helpers.buildSearchPicker("audio-picker", [], currentConstant))}
  `;

  // Load audio constants asynchronously
  api(config.endpoint).then(res => {
    if (res.ok && res.data[config.key]) {
      const items = res.data[config.key].map(s => s.const || s.name || s.display);
      helpers.attachSearchPicker(bodyEl, "audio-picker", items);
    }
  });

  return {
    apply() {
      const input = bodyEl.querySelector("#audio-picker");
      const constant = input ? input.value.trim() : "";
      if (!constant) return null;
      return `${beat.type} ${constant}`;
    }
  };
}
