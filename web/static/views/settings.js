/**
 * TORCH Web GUI — Settings (Config Tuner) view.
 *
 * Two-panel layout: category sidebar + settings list with inline editing.
 * Supports bool toggles, gen pickers, int inputs, flag/var inputs, and
 * ROM metadata fields. Pending changes are batched and saved together.
 * Also includes TORCH Preferences (gui settings, LAN mode, etc.).
 */

import { api } from "../app.js";
import { esc } from "../utils.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let categories = null;       // cached category list from API
let activeCategory = null;   // index into categories array
let searchQuery = "";
let searchResults = null;    // flat search results (or null when not searching)
let pendingChanges = {};     // key: "file::name" -> {file, name, value, type}
let expandedSetting = null;  // "name" of currently expanded inline editor
let debounceTimer = null;

// TORCH preferences state
let torchPrefs = null;       // cached from /api/config/preferences
let torchProjects = null;    // cached from /api/config/projects (used by favourite_project picker)
let activeView = "config";   // "config" = expansion settings, "prefs" = TORCH prefs
let _restartRequired = false; // set when LAN/port/auth changed

const GEN_VALUES = [
  "GEN_3", "GEN_4", "GEN_5", "GEN_6", "GEN_7", "GEN_8", "GEN_9", "GEN_LATEST",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pendingKey(file, name) {
  return `${file}::${name}`;
}

function pendingCount() {
  return Object.keys(pendingChanges).length;
}

// esc() removed — now imported as esc from utils.js

/**
 * Convert a raw #define name to a human-readable display name.
 * Strips the category prefix (B_, P_, OW_, I_, etc.) and title-cases the rest.
 * e.g. "B_CRIT_CHANCE" -> "Crit Chance", "OW_RUNNING_INDOORS" -> "Running Indoors"
 */
function humanName(raw) {
  // Strip prefix: first uppercase segment followed by _
  const stripped = raw.replace(/^[A-Z]+_/, "");
  // Title case: split on _, capitalize first letter of each word, lowercase the rest
  return stripped
    .split("_")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

function valueClass(type) {
  switch (type) {
    case "bool":     return "settings-val-bool";
    case "gen":      return "settings-val-gen";
    case "int":      return "settings-val-int";
    case "flag_var": return "settings-val-flagvar";
    case "const":    return "settings-val-const";
    default:         return "";
  }
}

function displayValue(item) {
  const pk = pendingKey(item._file || "", item.name);
  if (pendingChanges[pk]) return pendingChanges[pk].value;
  if (item.type === "bool") return item.parsed ? "TRUE" : "FALSE";
  if (item.type === "rom_field") return item.parsed?.value ?? item.value;
  return item.value;
}

function boolClass(item) {
  const pk = pendingKey(item._file || "", item.name);
  const val = pendingChanges[pk] ? pendingChanges[pk].value : (item.parsed ? "TRUE" : "FALSE");
  return val === "TRUE" ? "settings-val-bool-true" : "settings-val-bool-false";
}

function flagVarClass(item) {
  const pk = pendingKey(item._file || "", item.name);
  const val = pendingChanges[pk] ? pendingChanges[pk].value : item.value;
  return val === "0" ? "settings-val-const" : "settings-val-flagvar";
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

export async function render(container) {
  container.innerHTML = `<p style="color:#888">Loading settings...</p>`;

  try {
    const loads = [];
    if (!categories) {
      loads.push(api("/settings/categories").then(resp => {
        if (resp.ok) categories = resp.data.categories;
      }));
    }
    if (!torchPrefs) {
      loads.push(api("/config/preferences").then(resp => {
        if (resp.ok) torchPrefs = resp.data.preferences;
      }));
    }
    if (!torchProjects) {
      loads.push(api("/config/projects").then(resp => {
        if (resp.ok) torchProjects = resp.data.projects;
      }));
    }
    await Promise.all(loads);

    if (categories && categories.length > 0 && activeCategory === null && activeView === "config") {
      activeCategory = 0;
    }

    renderLayout(container);
  } catch (err) {
    container.innerHTML = `<article><p style="color:#f44">${esc(err.message)}</p></article>`;
  }
}

function renderLayout(container) {
  container.innerHTML = "";

  // Search bar
  const searchBar = document.createElement("div");
  searchBar.className = "settings-search-bar";
  searchBar.innerHTML = `
    <input type="text" class="settings-search" placeholder="Search all settings..."
           value="${esc(searchQuery)}">
  `;
  container.appendChild(searchBar);

  const searchInput = searchBar.querySelector(".settings-search");
  searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      searchQuery = searchInput.value.trim();
      if (searchQuery.length >= 2) {
        await doSearch(searchQuery, container);
      } else {
        searchResults = null;
        renderLayout(container);
      }
    }, 250);
  });

  // Main two-panel layout
  const wrap = document.createElement("div");
  wrap.className = "settings-container";
  container.appendChild(wrap);

  // Sidebar
  const sidebar = document.createElement("div");
  sidebar.className = "settings-sidebar";
  wrap.appendChild(sidebar);
  renderSidebar(sidebar);

  // Main panel
  const main = document.createElement("div");
  main.className = "settings-main";
  wrap.appendChild(main);

  if (searchResults) {
    renderSearchResults(main);
  } else if (activeView === "prefs") {
    renderPrefsPanel(main);
  } else if (categories && activeCategory !== null && categories[activeCategory]) {
    renderSettingsPanel(main, categories[activeCategory]);
  } else {
    main.innerHTML = `<p style="color:#888">No categories found.</p>`;
  }

  // Save bar (expansion config changes)
  renderSaveBar(container);
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

function renderSidebar(sidebar) {
  sidebar.innerHTML = "";

  // --- TORCH section ---
  if (torchPrefs) {
    const torchHeader = document.createElement("div");
    torchHeader.className = "settings-section-header";
    torchHeader.textContent = "TORCH";
    sidebar.appendChild(torchHeader);

    const prefsEl = document.createElement("div");
    prefsEl.className = "settings-cat-item" + (activeView === "prefs" && !searchResults ? " active" : "");
    prefsEl.innerHTML = `
      <span class="settings-cat-name">Preferences</span>
      <span class="settings-count">${torchPrefs.length}</span>
    `;
    prefsEl.addEventListener("click", () => {
      activeView = "prefs";
      activeCategory = null;
      searchQuery = "";
      searchResults = null;
      expandedSetting = null;
      const searchInput = document.querySelector(".settings-search");
      if (searchInput) searchInput.value = "";
      renderLayout(sidebar.closest("#app") || sidebar.parentElement.parentElement);
    });
    sidebar.appendChild(prefsEl);

    const divider = document.createElement("hr");
    divider.className = "settings-section-divider";
    sidebar.appendChild(divider);
  }

  // --- Expansion config categories ---
  if (!categories) return;

  let addedRomHeader = false;
  let addedConfigHeader = false;

  for (let i = 0; i < categories.length; i++) {
    const cat = categories[i];
    const isRom = cat.name === "ROM Metadata";

    // Add section headers
    if (isRom && !addedRomHeader) {
      const header = document.createElement("div");
      header.className = "settings-section-header";
      header.textContent = "PROJECT";
      sidebar.appendChild(header);
      addedRomHeader = true;
    } else if (!isRom && !addedConfigHeader) {
      if (addedRomHeader) {
        const divider = document.createElement("hr");
        divider.className = "settings-section-divider";
        sidebar.appendChild(divider);
      }
      const header = document.createElement("div");
      header.className = "settings-section-header";
      header.textContent = "CONFIG";
      sidebar.appendChild(header);
      addedConfigHeader = true;
    }

    const el = document.createElement("div");
    el.className = "settings-cat-item" + (activeView === "config" && i === activeCategory && !searchResults ? " active" : "");
    el.innerHTML = `
      <span class="settings-cat-name">${esc(cat.name)}</span>
      <span class="settings-count">${cat.count}</span>
    `;
    el.addEventListener("click", () => {
      activeView = "config";
      activeCategory = i;
      searchQuery = "";
      searchResults = null;
      expandedSetting = null;
      const searchInput = document.querySelector(".settings-search");
      if (searchInput) searchInput.value = "";
      renderLayout(sidebar.closest("#app") || sidebar.parentElement.parentElement);
    });
    sidebar.appendChild(el);
  }
}

// ---------------------------------------------------------------------------
// Settings panel (category view)
// ---------------------------------------------------------------------------

function renderSettingsPanel(main, cat) {
  main.innerHTML = "";

  const header = document.createElement("div");
  header.className = "settings-panel-header";
  header.innerHTML = `<h3>${esc(cat.name)} <span class="settings-count-inline">(${cat.count})</span></h3>`;
  main.appendChild(header);

  const list = document.createElement("div");
  list.className = "settings-list";
  main.appendChild(list);

  for (const item of cat.settings) {
    item._file = cat.file;  // attach file path for save
    renderSettingRow(list, item);
  }
}

function renderSettingRow(parent, item) {
  const pk = pendingKey(item._file || "", item.name);
  const hasPending = pk in pendingChanges;
  const isExpanded = expandedSetting === item.name;
  const isConst = item.type === "const";

  const row = document.createElement("div");
  row.className = "settings-row" + (hasPending ? " modified" : "") + (isExpanded ? " expanded" : "");

  const valDisplay = displayValue(item);
  let valCls = valueClass(item.type);
  if (item.type === "bool") valCls = boolClass(item);
  else if (item.type === "flag_var") valCls = flagVarClass(item);

  row.innerHTML = `
    <div class="settings-row-header">
      <span class="settings-row-name" title="${esc(item.name)}">${esc(humanName(item.name))}${hasPending ? ' <span class="settings-pending-badge">*</span>' : ""}</span>
      <span class="settings-row-value ${valCls}">${esc(String(valDisplay))}</span>
    </div>
    ${item.comment ? `<div class="settings-row-comment">${esc(item.comment)}</div>` : ""}
  `;

  if (!isConst) {
    row.style.cursor = "pointer";
    row.addEventListener("click", (e) => {
      if (e.target.closest(".settings-edit-panel")) return;
      // Don't expand when the bool toggle value was clicked
      if (e.target.closest(".settings-bool-toggle")) return;
      expandedSetting = isExpanded ? null : item.name;
      // Re-render the main panel
      const mainEl = row.closest(".settings-main");
      if (mainEl) {
        if (searchResults) {
          renderSearchResults(mainEl);
        } else if (categories && activeCategory !== null) {
          renderSettingsPanel(mainEl, categories[activeCategory]);
        }
      }
    });
  }

  // Inline bool toggle: clicking the value span toggles without expanding
  if (item.type === "bool" && !isConst) {
    const valSpan = row.querySelector(".settings-row-value");
    valSpan.classList.add("settings-bool-toggle");
    valSpan.addEventListener("click", (e) => {
      e.stopPropagation();
      const currentVal = pk in pendingChanges
        ? pendingChanges[pk].value
        : (item.parsed ? "TRUE" : "FALSE");
      const newVal = currentVal === "TRUE" ? "FALSE" : "TRUE";
      const origVal = item.parsed ? "TRUE" : "FALSE";
      if (newVal === origVal) {
        delete pendingChanges[pk];
      } else {
        pendingChanges[pk] = {
          file: item._file || "",
          name: item.name,
          value: newVal,
          type: "bool",
        };
      }
      refreshAll(row);
    });
  }

  parent.appendChild(row);

  if (isExpanded && !isConst) {
    const panel = document.createElement("div");
    panel.className = "settings-edit-panel";
    renderEditPanel(panel, item);
    parent.appendChild(panel);
  }
}

// ---------------------------------------------------------------------------
// Inline edit panels
// ---------------------------------------------------------------------------

function renderEditPanel(panel, item) {
  const pk = pendingKey(item._file || "", item.name);
  const currentVal = pendingChanges[pk]?.value ?? displayValue(item);

  switch (item.type) {
    case "bool":
      renderBoolEditor(panel, item, pk, currentVal);
      break;
    case "gen":
      renderGenEditor(panel, item, pk, currentVal);
      break;
    case "int":
      renderIntEditor(panel, item, pk, currentVal);
      break;
    case "flag_var":
      renderFlagVarEditor(panel, item, pk, currentVal);
      break;
    case "rom_field":
      renderRomFieldEditor(panel, item, pk);
      break;
    default:
      panel.innerHTML = `<span class="settings-val-const">Edit manually in header file</span>`;
  }
}

function renderBoolEditor(panel, item, pk, currentVal) {
  panel.innerHTML = `
    <div class="settings-edit-bool">
      <button class="settings-bool-btn${currentVal === "TRUE" ? " active-true" : ""}" data-val="TRUE">TRUE</button>
      <button class="settings-bool-btn${currentVal === "FALSE" ? " active-false" : ""}" data-val="FALSE">FALSE</button>
    </div>
  `;
  panel.querySelectorAll(".settings-bool-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const newVal = btn.dataset.val;
      const origVal = item.parsed ? "TRUE" : "FALSE";
      if (newVal === origVal) {
        delete pendingChanges[pk];
      } else {
        pendingChanges[pk] = { file: item._file, name: item.name, value: newVal, type: item.type };
      }
      refreshAll(panel);
    });
  });
}

function renderGenEditor(panel, item, pk, currentVal) {
  const btns = GEN_VALUES.map(g =>
    `<button class="settings-gen-btn${currentVal === g ? " active-gen" : ""}" data-val="${g}">${g.replace("GEN_", "")}</button>`
  ).join("");
  panel.innerHTML = `<div class="settings-edit-gen">${btns}</div>`;
  panel.querySelectorAll(".settings-gen-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const newVal = btn.dataset.val;
      if (newVal === item.value) {
        delete pendingChanges[pk];
      } else {
        pendingChanges[pk] = { file: item._file, name: item.name, value: newVal, type: item.type };
      }
      refreshAll(panel);
    });
  });
}

function renderIntEditor(panel, item, pk, currentVal) {
  panel.innerHTML = `
    <div class="settings-edit-int">
      <input type="number" class="settings-edit-input" value="${esc(String(currentVal))}">
      <button class="settings-apply-btn">Apply</button>
    </div>
  `;
  const input = panel.querySelector("input");
  const applyBtn = panel.querySelector(".settings-apply-btn");
  function applyValue() {
    const newVal = input.value.trim();
    if (newVal === item.value) {
      delete pendingChanges[pk];
    } else {
      pendingChanges[pk] = { file: item._file, name: item.name, value: newVal, type: item.type };
    }
    refreshAll(panel);
  }
  applyBtn.addEventListener("click", (e) => { e.stopPropagation(); applyValue(); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.stopPropagation(); applyValue(); } });
  input.addEventListener("click", (e) => e.stopPropagation());
}

function renderFlagVarEditor(panel, item, pk, currentVal) {
  panel.innerHTML = `
    <div class="settings-edit-flagvar">
      <button class="settings-flagvar-btn${currentVal === "0" ? " active-disabled" : ""}" data-val="0">Disabled (0)</button>
      <input type="text" class="settings-edit-input" placeholder="FLAG_... or VAR_..."
             value="${esc(currentVal === "0" ? "" : currentVal)}">
      <button class="settings-apply-btn">Apply</button>
    </div>
  `;
  const disableBtn = panel.querySelector(".settings-flagvar-btn");
  const input = panel.querySelector("input");
  const applyBtn = panel.querySelector(".settings-apply-btn");

  disableBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (item.value === "0") {
      delete pendingChanges[pk];
    } else {
      pendingChanges[pk] = { file: item._file, name: item.name, value: "0", type: item.type };
    }
    refreshAll(panel);
  });

  function applyCustom() {
    const newVal = input.value.trim();
    if (!newVal || newVal === item.value) {
      delete pendingChanges[pk];
    } else {
      pendingChanges[pk] = { file: item._file, name: item.name, value: newVal, type: item.type };
    }
    refreshAll(panel);
  }
  applyBtn.addEventListener("click", (e) => { e.stopPropagation(); applyCustom(); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.stopPropagation(); applyCustom(); } });
  input.addEventListener("click", (e) => e.stopPropagation());
}

function renderRomFieldEditor(panel, item, pk) {
  const field = item.parsed || {};
  const maxLen = field.max_len || 0;
  panel.innerHTML = `
    <div class="settings-edit-rom">
      <input type="text" class="settings-edit-input" value="${esc(field.value || "")}"
             ${maxLen ? `maxlength="${maxLen}"` : ""}>
      ${maxLen ? `<span class="settings-rom-hint">max ${maxLen} chars</span>` : ""}
      <button class="settings-rom-save-btn">Save</button>
    </div>
  `;
  const input = panel.querySelector("input");
  const saveBtn = panel.querySelector(".settings-rom-save-btn");

  async function saveRomField() {
    const newVal = input.value.trim();
    saveBtn.textContent = "Saving...";
    saveBtn.disabled = true;
    try {
      const res = await fetch("/api/settings/rom", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: field.key || item.name, value: newVal }),
      });
      const data = await res.json();
      if (data.ok) {
        saveBtn.textContent = "Saved";
        // Invalidate cache so next render picks up new value
        categories = null;
        setTimeout(() => {
          const app = document.getElementById("app");
          if (app) render(app);
        }, 600);
      } else {
        saveBtn.textContent = data.error || "Error";
        setTimeout(() => { saveBtn.textContent = "Save"; saveBtn.disabled = false; }, 2000);
      }
    } catch (err) {
      saveBtn.textContent = "Error";
      setTimeout(() => { saveBtn.textContent = "Save"; saveBtn.disabled = false; }, 2000);
    }
  }
  saveBtn.addEventListener("click", (e) => { e.stopPropagation(); saveRomField(); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.stopPropagation(); saveRomField(); } });
  input.addEventListener("click", (e) => e.stopPropagation());
}

// ---------------------------------------------------------------------------
// TORCH Preferences panel
// ---------------------------------------------------------------------------

const PREF_GROUPS = [
  { label: "Web GUI / LAN", keys: ["gui_lan_enabled", "gui_port", "gui_host", "gui_username", "gui_password"] },
  { label: "Build & Sync", keys: ["auto_build", "max_snapshots", "max_verified_snapshots"] },
  { label: "Editor", keys: ["editor_visible_beats", "editor_context", "storyboard_page_size", "vim_help_dismissed"] },
  { label: "Lists", keys: ["map_list_page_size", "trainer_list_page_size", "show_all_trainers", "maps_view", "textbox_warning", "level_cap"] },
  { label: "Navigation Keys", keys: ["nav_scroll", "nav_up", "nav_down", "nav_open"] },
  { label: "Projects", keys: ["projects_directory", "favourite_project"] },
];

function prefDisplayName(key) {
  return key.replace(/_/g, " ").replace(/\bgui\b/gi, "GUI")
    .replace(/\blan\b/gi, "LAN").replace(/\brom\b/gi, "ROM")
    .replace(/\bnav\b/gi, "Nav").replace(/\bvim\b/gi, "Vim")
    .split(" ").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function renderPrefsPanel(main) {
  main.innerHTML = "";

  if (!torchPrefs || torchPrefs.length === 0) {
    main.innerHTML = `<p style="color:#888">No preferences loaded.</p>`;
    return;
  }

  // Restart banner (inside main panel, not as layout sibling)
  if (_restartRequired) {
    const banner = document.createElement("div");
    banner.className = "pref-restart-banner";
    banner.textContent = "Restart required for network changes. Re-run torch gui to apply.";
    main.appendChild(banner);
  }

  const header = document.createElement("div");
  header.className = "settings-panel-header";
  header.innerHTML = `<h3>TORCH Preferences</h3>`;
  main.appendChild(header);

  // Index prefs by key
  const byKey = {};
  for (const p of torchPrefs) byKey[p.key] = p;

  for (const group of PREF_GROUPS) {
    const items = group.keys.filter(k => byKey[k]).map(k => byKey[k]);
    if (items.length === 0) continue;

    const groupEl = document.createElement("div");
    groupEl.className = "prefs-group";
    groupEl.innerHTML = `<div class="prefs-group-label">${esc(group.label)}</div>`;
    main.appendChild(groupEl);

    const list = document.createElement("div");
    list.className = "settings-list";
    groupEl.appendChild(list);

    for (const pref of items) {
      renderPrefRow(list, pref);
    }
  }

  // Any ungrouped prefs
  const grouped = new Set(PREF_GROUPS.flatMap(g => g.keys));
  const ungrouped = torchPrefs.filter(p => !grouped.has(p.key));
  if (ungrouped.length > 0) {
    const groupEl = document.createElement("div");
    groupEl.className = "prefs-group";
    groupEl.innerHTML = `<div class="prefs-group-label">Other</div>`;
    main.appendChild(groupEl);
    const list = document.createElement("div");
    list.className = "settings-list";
    groupEl.appendChild(list);
    for (const pref of ungrouped) {
      renderPrefRow(list, pref);
    }
  }
}

function renderPrefRow(parent, pref) {
  const isExpanded = expandedSetting === `pref::${pref.key}`;
  const isModified = pref.value !== pref.default;

  const row = document.createElement("div");
  row.className = "settings-row" + (isExpanded ? " expanded" : "");
  row.style.cursor = "pointer";

  let valDisplay = String(pref.value);
  let valCls = "";

  if (pref.type === "bool") {
    valDisplay = pref.value ? "ON" : "OFF";
    valCls = pref.value ? "settings-val-bool-true" : "settings-val-bool-false";
  } else if (pref.type === "int") {
    valCls = "settings-val-int";
  } else {
    valCls = pref.value ? "" : "settings-val-const";
    if (pref.key === "gui_password" && pref.value) {
      valDisplay = pref.value.charAt(0) + "*".repeat(Math.max(0, pref.value.length - 1));
    }
  }

  row.innerHTML = `
    <div class="settings-row-header">
      <span class="settings-row-name" title="${esc(pref.key)}">${esc(prefDisplayName(pref.key))}${isModified ? ' <span class="settings-pending-badge">*</span>' : ""}</span>
      <span class="settings-row-value ${valCls}">${esc(valDisplay)}</span>
    </div>
    ${pref.description ? `<div class="settings-row-comment">${esc(pref.description)}</div>` : ""}
  `;

  row.addEventListener("click", (e) => {
    if (e.target.closest(".pref-edit-panel")) return;
    expandedSetting = isExpanded ? null : `pref::${pref.key}`;
    const mainEl = row.closest(".settings-main");
    if (mainEl) renderPrefsPanel(mainEl);
  });

  parent.appendChild(row);

  if (isExpanded) {
    const panel = document.createElement("div");
    panel.className = "settings-edit-panel pref-edit-panel";
    renderPrefEditor(panel, pref);
    parent.appendChild(panel);
  }
}

function renderPrefEditor(panel, pref) {
  if (pref.type === "bool") {
    panel.innerHTML = `
      <div class="settings-edit-bool">
        <button class="settings-bool-btn${pref.value ? " active-true" : ""}" data-val="true">ON</button>
        <button class="settings-bool-btn${!pref.value ? " active-false" : ""}" data-val="false">OFF</button>
      </div>
    `;
    panel.querySelectorAll(".settings-bool-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const newVal = btn.dataset.val === "true";
        savePref(pref.key, newVal, btn);
      });
    });
  } else if (pref.type === "int") {
    panel.innerHTML = `
      <div class="settings-edit-int">
        <input type="number" class="settings-edit-input" value="${pref.value}">
        <button class="settings-apply-btn">Apply</button>
      </div>
    `;
    const input = panel.querySelector("input");
    const applyBtn = panel.querySelector(".settings-apply-btn");
    function applyValue() {
      const val = parseInt(input.value, 10);
      if (isNaN(val)) return;
      savePref(pref.key, val, applyBtn);
    }
    applyBtn.addEventListener("click", (e) => { e.stopPropagation(); applyValue(); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.stopPropagation(); applyValue(); } });
    input.addEventListener("click", (e) => e.stopPropagation());
  } else if (pref.key === "favourite_project" && torchProjects && torchProjects.length > 0) {
    // Project picker dropdown
    const options = [`<option value="">(none)</option>`]
      .concat(torchProjects.map(p =>
        `<option value="${esc(p.name)}"${p.name === pref.value ? " selected" : ""}>${esc(p.name)}</option>`
      ));
    panel.innerHTML = `
      <div class="settings-edit-int">
        <select class="settings-edit-input pref-project-select">${options.join("")}</select>
      </div>
    `;
    const sel = panel.querySelector("select");
    sel.addEventListener("change", (e) => {
      e.stopPropagation();
      savePref(pref.key, sel.value, sel);
    });
    sel.addEventListener("click", (e) => e.stopPropagation());
  } else if (pref.key === "editor_context") {
    // Choice editor: compact / detail / off
    const choices = ["compact", "detail", "off"];
    const btns = choices.map(c =>
      `<button class="settings-gen-btn${pref.value === c ? " active-gen" : ""}" data-val="${c}">${c}</button>`
    ).join("");
    panel.innerHTML = `<div class="settings-edit-gen">${btns}</div>`;
    panel.querySelectorAll(".settings-gen-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        savePref(pref.key, btn.dataset.val, btn);
      });
    });
  } else if (pref.key === "maps_view") {
    // Choice editor: recent / all
    const choices = ["recent", "all"];
    const btns = choices.map(c =>
      `<button class="settings-gen-btn${pref.value === c ? " active-gen" : ""}" data-val="${c}">${c}</button>`
    ).join("");
    panel.innerHTML = `<div class="settings-edit-gen">${btns}</div>`;
    panel.querySelectorAll(".settings-gen-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        savePref(pref.key, btn.dataset.val, btn);
      });
    });
  } else {
    // String editor
    const isPassword = pref.key === "gui_password";
    panel.innerHTML = `
      <div class="settings-edit-int">
        <input type="${isPassword ? "password" : "text"}" class="settings-edit-input"
               value="${esc(String(pref.value))}" placeholder="${esc(String(pref.default) || "(empty)")}">
        <button class="settings-apply-btn">Apply</button>
      </div>
    `;
    const input = panel.querySelector("input");
    const applyBtn = panel.querySelector(".settings-apply-btn");
    function applyValue() {
      savePref(pref.key, input.value, applyBtn);
    }
    applyBtn.addEventListener("click", (e) => { e.stopPropagation(); applyValue(); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.stopPropagation(); applyValue(); } });
    input.addEventListener("click", (e) => e.stopPropagation());
  }

  // Default reset button
  const resetWrap = document.createElement("div");
  resetWrap.className = "pref-reset-wrap";
  resetWrap.innerHTML = `<button class="pref-reset-btn">Reset to default (${esc(String(pref.default) || "empty")})</button>`;
  resetWrap.querySelector("button").addEventListener("click", (e) => {
    e.stopPropagation();
    savePref(pref.key, pref.default, e.target);
  });
  panel.appendChild(resetWrap);
}

async function savePref(key, value, feedbackEl) {
  if (feedbackEl) {
    feedbackEl.disabled = true;
    if (feedbackEl.tagName === "BUTTON") feedbackEl.textContent = "Saving...";
  }

  try {
    const res = await fetch("/api/config/preferences", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ changes: [{ key, value }] }),
    });
    const data = await res.json();
    if (data.ok) {
      // Update local cache
      if (torchPrefs) {
        const p = torchPrefs.find(p => p.key === key);
        if (p) p.value = value;
      }
      // Track restart requirement
      if (data.data.restart_required) {
        _restartRequired = true;
      }
      // Re-render
      const mainEl = document.querySelector(".settings-main");
      if (mainEl) renderPrefsPanel(mainEl);
    } else {
      if (feedbackEl && feedbackEl.tagName === "BUTTON") {
        feedbackEl.textContent = data.error || "Error";
        setTimeout(() => { feedbackEl.textContent = "Apply"; feedbackEl.disabled = false; }, 2000);
      }
    }
  } catch (err) {
    if (feedbackEl && feedbackEl.tagName === "BUTTON") {
      feedbackEl.textContent = "Error";
      setTimeout(() => { feedbackEl.textContent = "Apply"; feedbackEl.disabled = false; }, 2000);
    }
  }
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

async function doSearch(query, container) {
  try {
    const resp = await api(`/settings/search?q=${encodeURIComponent(query)}`);
    if (!resp.ok) {
      searchResults = [];
      return;
    }
    searchResults = resp.data.results;
    renderLayout(container);
  } catch {
    searchResults = [];
  }
}

function renderSearchResults(main) {
  main.innerHTML = "";
  if (!searchResults || searchResults.length === 0) {
    main.innerHTML = `<p style="color:#888">No results for "${esc(searchQuery)}"</p>`;
    return;
  }

  const header = document.createElement("div");
  header.className = "settings-panel-header";
  header.innerHTML = `<h3>Search results <span class="settings-count-inline">(${searchResults.length})</span></h3>`;
  main.appendChild(header);

  const list = document.createElement("div");
  list.className = "settings-list";
  main.appendChild(list);

  for (const item of searchResults) {
    // Attach file path from search result
    item._file = item.file;
    const catTag = document.createElement("div");
    catTag.className = "settings-search-cat-tag";
    catTag.textContent = item.category;
    list.appendChild(catTag);
    renderSettingRow(list, item);
  }
}

// ---------------------------------------------------------------------------
// Save bar
// ---------------------------------------------------------------------------

function renderSaveBar(container) {
  // Remove existing
  const old = container.querySelector(".settings-save-bar");
  if (old) old.remove();

  const count = pendingCount();
  if (count === 0) return;

  const bar = document.createElement("div");
  bar.className = "settings-save-bar";
  bar.innerHTML = `
    <button class="settings-discard-btn">Discard</button>
    <button class="settings-save-btn">Save Changes (${count})</button>
  `;
  container.appendChild(bar);

  bar.querySelector(".settings-discard-btn").addEventListener("click", () => {
    pendingChanges = {};
    expandedSetting = null;
    renderLayout(container);
  });

  bar.querySelector(".settings-save-btn").addEventListener("click", async () => {
    const saveBtn = bar.querySelector(".settings-save-btn");
    saveBtn.textContent = "Saving...";
    saveBtn.disabled = true;

    const changes = Object.values(pendingChanges).map(c => ({
      file: c.file,
      name: c.name,
      value: c.value,
    }));

    try {
      const res = await fetch("/api/settings/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ changes }),
      });
      const data = await res.json();
      if (data.ok) {
        const d = data.data;
        pendingChanges = {};
        expandedSetting = null;
        categories = null;  // invalidate cache
        saveBtn.textContent = `Saved ${d.saved}${d.failed ? `, ${d.failed} failed` : ""}`;
        setTimeout(() => render(container), 800);
      } else {
        saveBtn.textContent = data.error || "Save failed";
        setTimeout(() => { saveBtn.textContent = `Save Changes (${count})`; saveBtn.disabled = false; }, 2000);
      }
    } catch (err) {
      saveBtn.textContent = "Save error";
      setTimeout(() => { saveBtn.textContent = `Save Changes (${count})`; saveBtn.disabled = false; }, 2000);
    }
  });
}

// ---------------------------------------------------------------------------
// Refresh helper (re-render current panel without losing scroll)
// ---------------------------------------------------------------------------

function refreshAll(fromEl) {
  const container = document.getElementById("app");
  if (!container) return;
  const scrollY = window.scrollY;
  renderLayout(container);
  window.scrollTo(0, scrollY);
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

export function cleanup() {
  clearTimeout(debounceTimer);
  debounceTimer = null;
  categories = null;
  activeCategory = null;
  searchQuery = "";
  searchResults = null;
  pendingChanges = {};
  expandedSetting = null;
  torchPrefs = null;
  torchProjects = null;
  activeView = "config";
  _restartRequired = false;
}
