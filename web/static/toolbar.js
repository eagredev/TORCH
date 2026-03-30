/**
 * TORCH IDE — Toolbar (top bar).
 * TORCH_MODULE
 *
 * 6-menu layout: File | Edit | View | Data | Window | Help
 * Inline mode toggle (View · Events · Scripts) with underline accent.
 * Build button + Close/Exit button.
 * openToolModal() wraps existing views as floating modal dialogs.
 */

import { api, postApi } from "./app.js";
import { esc } from "./utils.js";
import { ideEmit, IDE_MODE_CHANGED } from "./ide.js";
import { toggleGrid, toggleNpcs, toggleWarps, toggleTriggers, toggleSigns, toggleBorders } from "./mapCanvas.js";
import { setCollisionVisible, isCollisionVisible } from "./collisionOverlay.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _openMenu = null;       // name of currently open menu
let _docClickHandler = null;
let _keyHandler = null;
let _mode = "view";         // "view", "events", or "scripts"
let _activeModal = null;    // current open modal cleanup fn

// ---------------------------------------------------------------------------
// Tool modal system
// ---------------------------------------------------------------------------

/**
 * Open an existing view module as a floating modal dialog inside the IDE.
 * @param {string} title — Modal title bar text
 * @param {() => Promise<{render, cleanup}>} loader — dynamic import fn
 * @param {string} [hashContext] — optional hash for map context
 */
export async function openToolModal(title, loader, context) {
  closeToolModal();

  const backdrop = document.createElement("div");
  backdrop.className = "ide-modal-backdrop";

  const modal = document.createElement("div");
  modal.className = "ide-modal";

  const titleBar = document.createElement("div");
  titleBar.className = "ide-modal-titlebar";
  titleBar.innerHTML = `
    <span class="ide-modal-title">${esc(title)}</span>
    <button class="ide-modal-close">&times;</button>
  `;

  const content = document.createElement("div");
  content.className = "ide-modal-content";

  modal.appendChild(titleBar);
  modal.appendChild(content);
  backdrop.appendChild(modal);
  document.body.appendChild(backdrop);

  _makeDraggable(modal, titleBar);

  // Views read the selected map via getMapFromHashOrContext() from viewContext.js.
  // No hash manipulation needed — IDE_MAP_SELECTED already calls setViewContext().

  let viewCleanup = null;
  try {
    const view = await loader();
    await view.render(content, context);
    viewCleanup = view.cleanup || null;
  } catch (err) {
    content.innerHTML = `<div style="padding:1rem;color:var(--status-error)">${esc(err.message)}</div>`;
  }

  const close = () => {
    if (viewCleanup) viewCleanup();
    backdrop.remove();
    _activeModal = null;
  };

  titleBar.querySelector(".ide-modal-close").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) close();
  });

  _activeModal = close;
}

function closeToolModal() {
  if (_activeModal) {
    _activeModal();
    _activeModal = null;
  }
}

function _makeDraggable(el, handle) {
  let startX, startY, startLeft, startTop;
  handle.style.cursor = "grab";

  handle.addEventListener("mousedown", (e) => {
    if (e.target.closest(".ide-modal-close")) return;
    e.preventDefault();
    handle.style.cursor = "grabbing";

    const rect = el.getBoundingClientRect();
    startX = e.clientX;
    startY = e.clientY;
    startLeft = rect.left;
    startTop = rect.top;

    const onMove = (ev) => {
      el.style.left = (startLeft + ev.clientX - startX) + "px";
      el.style.top = (startTop + ev.clientY - startY) + "px";
      el.style.transform = "none";
      el.style.margin = "0";
    };

    const onUp = () => {
      handle.style.cursor = "grab";
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}

// ---------------------------------------------------------------------------
// Menu definitions — 8 industry-standard menus
// ---------------------------------------------------------------------------

const MENUS = [
  {
    name: "File",
    items: [
      { label: "Build ROM", shortcut: "Ctrl+B", action: _doBuild },
      { label: "Build Output", shortcut: "Ctrl+Shift+B", action: _toggleBuildOutput },
      { sep: true },
      { label: "Settings", shortcut: "Ctrl+,", action: () => openToolModal("Settings", () => import("./views/settings.js")) },
      { label: "Project", shortcut: "Ctrl+Shift+P", action: () => openToolModal("Project", () => import("./views/project.js")) },
      { sep: true },
      { label: "Version History", action: () => openToolModal("Versions", () => import("./views/versions.js")) },
      { sep: true },
      { label: "Close Studio", action: _closeStudio },
      { label: "Quit TORCH", shortcut: "Ctrl+Q", action: _quitTorch },
    ],
  },
  {
    name: "Edit",
    items: [
      { label: "Undo", shortcut: "Ctrl+Z", action: _doUndo },
      { label: "Redo", shortcut: "Ctrl+Y", action: _doRedo },
    ],
  },
  {
    name: "View",
    items: [
      { label: "Toggle Grid", shortcut: "G", action: () => toggleGrid() },
      { label: "Toggle NPCs", shortcut: "Shift+N", action: () => toggleNpcs() },
      { label: "Toggle Warps", shortcut: "Shift+W", action: () => toggleWarps() },
      { label: "Toggle Triggers", shortcut: "Shift+T", action: () => toggleTriggers() },
      { label: "Toggle Signs", shortcut: "Shift+S", action: () => toggleSigns() },
      { label: "Toggle Border Tiles", shortcut: "B", action: () => toggleBorders() },
      { sep: true },
      { label: "Toggle Collision", shortcut: "Shift+C", action: () => setCollisionVisible(!isCollisionVisible()) },
    ],
  },
  {
    name: "Data",
    items: [
      { label: "Trainers", action: () => openToolModal("Trainers", () => import("./views/trainers.js")) },
      { label: "Encounters", action: () => openToolModal("Encounters", () => import("./views/encounters.js")) },
      { label: "Shops", action: () => openToolModal("Shops", () => import("./views/shops.js")) },
      { label: "Heal Locations", action: () => openToolModal("Heals", () => import("./views/heals.js")) },
      { label: "Flags", action: () => openToolModal("Flags", () => import("./views/flags.js")) },
      { sep: true },
      { label: "Dex", action: () => openToolModal("Dex", () => import("./views/dex.js")) },
      { label: "Moves", action: () => openToolModal("Moves", () => import("./views/moves.js")) },
      { label: "Learnsets", action: () => openToolModal("Learnsets", () => import("./views/learnsets.js")) },
      { label: "Items", action: () => openToolModal("Items", () => import("./views/items.js")) },
    ],
  },
  {
    name: "Window",
    items: [
      { label: "Asset Browser", action: () => openToolModal("Assets", () => import("./views/assets.js")) },
      { label: "Tileset Editor", action: () => openToolModal("Tileset Editor", () => import("./views/tilesets.js")) },
      { label: "Templates", action: () => openToolModal("Templates", () => import("./views/templates.js")) },
      { label: "Stamp Library", action: () => openToolModal("Stamp Library", () => import("./views/stampLibrary.js")) },
      { label: "Scripts", action: () => openToolModal("Scripts", () => import("./views/scripts.js")) },
      { label: "NPCs", action: () => openToolModal("NPCs", () => import("./views/npcs.js")) },
      { sep: true },
      { label: "Map Graph", action: () => openToolModal("Map Graph", () => import("./views/explorer.js")) },
      { label: "Dashboard", action: () => openToolModal("Dashboard", () => import("./views/dashboard.js")) },
      { sep: true },
      { label: "SCORCH", action: () => openToolModal("SCORCH", () => import("./views/scorch.js")) },
    ],
  },
  {
    name: "Help",
    items: [
      { label: "Keyboard Shortcuts", shortcut: "Ctrl+/", action: _showShortcuts },
      { label: "About TORCH", action: _showAbout },
    ],
  },
];

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initToolbar(container) {
  _container = container;

  // Left section: menus
  const menusDiv = document.createElement("div");
  menusDiv.className = "ide-toolbar-menus";

  for (const menu of MENUS) {
    const wrapper = document.createElement("div");
    wrapper.style.position = "relative";
    wrapper.style.display = "inline-block";

    const btn = document.createElement("button");
    btn.className = "ide-menu-trigger";
    btn.textContent = menu.name;
    btn.dataset.menu = menu.name;
    btn.addEventListener("click", _onMenuClick);
    btn.addEventListener("mouseenter", _onMenuHover);
    wrapper.appendChild(btn);

    const dropdown = document.createElement("div");
    dropdown.className = "ide-dropdown";
    dropdown.dataset.menu = menu.name;
    dropdown.style.display = "none";

    for (const item of menu.items) {
      if (item.sep) {
        const sep = document.createElement("div");
        sep.className = "ide-dropdown-sep";
        dropdown.appendChild(sep);
        continue;
      }

      const itemBtn = document.createElement("button");
      itemBtn.className = "ide-dropdown-item";
      if (item.modeCheck) itemBtn.dataset.modeCheck = item.modeCheck;
      itemBtn.innerHTML = `
        <span class="ide-dropdown-check">${item.modeCheck ? "\u25CF" : ""}</span>
        <span>${esc(item.label)}</span>
        ${item.shortcut ? `<span class="shortcut">${esc(item.shortcut)}</span>` : ""}
      `;
      if (item.action) {
        itemBtn.addEventListener("click", () => {
          _closeMenus();
          item.action();
        });
      }
      dropdown.appendChild(itemBtn);
    }

    wrapper.appendChild(dropdown);
    menusDiv.appendChild(wrapper);
  }

  container.appendChild(menusDiv);

  // Right section: mode dropdown + close
  const rightDiv = document.createElement("div");
  rightDiv.className = "ide-toolbar-right";

  // Mode dropdown — styled like menu triggers but on the right side
  const modeWrapper = document.createElement("div");
  modeWrapper.style.position = "relative";
  modeWrapper.style.display = "inline-block";

  const modeBtn = document.createElement("button");
  modeBtn.className = "ide-menu-trigger ide-mode-trigger";
  modeBtn.id = "ide-mode-trigger";
  modeBtn.textContent = "View";
  modeBtn.title = "Switch mode (F5/F6/F7)";
  modeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const dd = modeWrapper.querySelector(".ide-dropdown");
    const isOpen = dd.style.display !== "none";
    _closeMenus(); // close left-side menus
    dd.style.display = isOpen ? "none" : "";
    modeBtn.classList.toggle("open", !isOpen);
  });
  modeWrapper.appendChild(modeBtn);

  const modeDropdown = document.createElement("div");
  modeDropdown.className = "ide-dropdown ide-mode-dropdown";
  modeDropdown.style.display = "none";

  const modes = [
    { id: "view", label: "View Mode", key: "F5" },
    { id: "events", label: "Event Mode", key: "F6" },
    { id: "scripts", label: "Scripts Mode", key: "F7" },
  ];
  for (const m of modes) {
    const itemBtn = document.createElement("button");
    itemBtn.className = "ide-dropdown-item";
    itemBtn.dataset.modeCheck = m.id;
    itemBtn.innerHTML = `
      <span class="ide-dropdown-check">${m.id === _mode ? "\u25CF" : ""}</span>
      <span>${esc(m.label)}</span>
      <span class="shortcut">${esc(m.key)}</span>
    `;
    itemBtn.addEventListener("click", () => {
      modeDropdown.style.display = "none";
      modeBtn.classList.remove("open");
      _setMode(m.id);
    });
    modeDropdown.appendChild(itemBtn);
  }

  modeWrapper.appendChild(modeDropdown);
  rightDiv.appendChild(modeWrapper);

  // Close/Exit button
  const closeBtn = document.createElement("button");
  closeBtn.className = "ide-close-btn";
  closeBtn.innerHTML = "&times;";
  closeBtn.title = "Close Studio";
  closeBtn.addEventListener("click", _closeStudio);
  rightDiv.appendChild(closeBtn);

  container.appendChild(rightDiv);

  // Close menus on outside click
  _docClickHandler = (e) => {
    if (!e.target.closest(".ide-toolbar-menus")) {
      _closeMenus();
    }
    // Also close mode dropdown if clicking outside it
    if (!e.target.closest(".ide-toolbar-right")) {
      const dd = document.querySelector(".ide-mode-dropdown");
      if (dd) dd.style.display = "none";
      const trigger = document.getElementById("ide-mode-trigger");
      if (trigger) trigger.classList.remove("open");
    }
  };
  document.addEventListener("click", _docClickHandler);

  // Keyboard shortcuts
  _keyHandler = _onKeyDown.bind(null);
  document.addEventListener("keydown", _keyHandler);
}

export function cleanupToolbar() {
  if (_docClickHandler) {
    document.removeEventListener("click", _docClickHandler);
    _docClickHandler = null;
  }
  if (_keyHandler) {
    document.removeEventListener("keydown", _keyHandler);
    _keyHandler = null;
  }
  closeToolModal();
  _container = null;
  _openMenu = null;
}

// ---------------------------------------------------------------------------
// Mode switching
// ---------------------------------------------------------------------------

function _setMode(mode) {
  _mode = mode;
  const LABELS = { view: "View", events: "Events", scripts: "Scripts" };

  // Update the right-side mode trigger button text
  const trigger = document.getElementById("ide-mode-trigger");
  if (trigger) trigger.textContent = LABELS[_mode] || _mode;

  // Update all Mode checkmarks (both Mode menu and mode dropdown)
  document.querySelectorAll("[data-mode-check]").forEach(el => {
    const check = el.querySelector(".ide-dropdown-check");
    if (check) check.textContent = el.dataset.modeCheck === _mode ? "\u25CF" : "";
  });

  ideEmit(IDE_MODE_CHANGED, { mode: _mode });
}

export function getMode() { return _mode; }

// ---------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------

function _onKeyDown(e) {
  // Don't intercept when typing in inputs
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" ||
      e.target.isContentEditable) return;

  // Escape closes modal or menu, or cascades in scripts mode
  if (e.key === "Escape") {
    if (_activeModal) { closeToolModal(); e.preventDefault(); return; }
    if (_openMenu) { _closeMenus(); e.preventDefault(); return; }
    if (_mode === "scripts") {
      import("./scriptsMode.js").then(m => m.handleEscape(_setMode));
      e.preventDefault();
      return;
    }
  }

  // Ctrl+B — Build
  if (e.ctrlKey && !e.shiftKey && e.key === "b") {
    e.preventDefault();
    _doBuild();
    return;
  }

  // Ctrl+Shift+B — Build Output
  if (e.ctrlKey && e.shiftKey && e.key === "B") {
    e.preventDefault();
    _toggleBuildOutput();
    return;
  }

  // Ctrl+F — Focus map search
  if (e.ctrlKey && e.key === "f") {
    e.preventDefault();
    _doFocusSearch();
    return;
  }

  // Ctrl+, — Settings
  if (e.ctrlKey && e.key === ",") {
    e.preventDefault();
    openToolModal("Settings", () => import("./views/settings.js"));
    return;
  }

  // Ctrl+Q — Quit
  if (e.ctrlKey && e.key === "q") {
    e.preventDefault();
    _quitTorch();
    return;
  }

  // Ctrl+/ — Keyboard shortcuts
  if (e.ctrlKey && e.key === "/") {
    e.preventDefault();
    _showShortcuts();
    return;
  }

  // Single-key shortcuts (only when no modal open and not in input)
  if (!_activeModal) {
    // G — Toggle grid
    if (e.key === "g" && !e.ctrlKey && !e.altKey && !e.shiftKey) {
      toggleGrid();
      return;
    }

    // B — Toggle border tiles
    if (e.key === "b" && !e.ctrlKey && !e.altKey && !e.shiftKey) {
      toggleBorders();
      return;
    }

    // Shift+N/W/T/S — Toggle visibility
    if (e.shiftKey && !e.ctrlKey && !e.altKey) {
      if (e.key === "N") { toggleNpcs(); return; }
      if (e.key === "W") { toggleWarps(); return; }
      if (e.key === "T") { toggleTriggers(); return; }
      if (e.key === "S") { toggleSigns(); return; }
      if (e.key === "C") { setCollisionVisible(!isCollisionVisible()); return; }
    }
  }

  // F5 — View mode
  if (e.key === "F5") { e.preventDefault(); _setMode("view"); return; }
  // F6 — Event mode
  if (e.key === "F6") { e.preventDefault(); _setMode("events"); return; }
  // F7 — Scripts mode
  if (e.key === "F7") { e.preventDefault(); _setMode("scripts"); return; }
}

// ---------------------------------------------------------------------------
// Menu interaction
// ---------------------------------------------------------------------------

function _onMenuClick(e) {
  const name = e.currentTarget.dataset.menu;
  if (_openMenu === name) {
    _closeMenus();
  } else {
    _openMenu = name;
    _updateMenuVisibility();
  }
}

function _onMenuHover(e) {
  if (_openMenu) {
    _openMenu = e.currentTarget.dataset.menu;
    _updateMenuVisibility();
  }
}

function _updateMenuVisibility() {
  if (!_container) return;
  _container.querySelectorAll(".ide-dropdown").forEach(dd => {
    dd.style.display = dd.dataset.menu === _openMenu ? "" : "none";
  });
  _container.querySelectorAll(".ide-menu-trigger").forEach(btn => {
    btn.classList.toggle("open", btn.dataset.menu === _openMenu);
  });
  // Refresh Mode checkmarks when opening Mode menu
  if (_openMenu === "Mode") {
    _container.querySelectorAll("[data-mode-check]").forEach(el => {
      const check = el.querySelector(".ide-dropdown-check");
      if (check) check.textContent = el.dataset.modeCheck === _mode ? "\u25CF" : "";
    });
  }
}

function _closeMenus() {
  _openMenu = null;
  if (_container) {
    _container.querySelectorAll(".ide-dropdown").forEach(dd => {
      dd.style.display = "none";
    });
    _container.querySelectorAll(".ide-menu-trigger").forEach(btn => {
      btn.classList.remove("open");
    });
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function _doBuild() {
  try {
    await postApi("/build", {});
  } catch (_) {}
}

function _doFocusSearch() {
  const search = document.getElementById("ide-tree-search");
  if (search) search.focus();
}

function _closeStudio() {
  window.location.hash = "#/";
}

function _quitTorch() {
  fetch("/api/shutdown", { method: "POST" }).then(() => window.close()).catch(() => {});
}

function _toggleBuildOutput() {
  const drawer = document.getElementById("build-drawer");
  if (drawer) drawer.classList.toggle("open");
}

function _doUndo() {
  // Context-dependent: script editor undo if available
  import("./views/viz/state.js").then(mod => {
    if (mod.state && mod.state.frames && mod.state.frames.length > 0) {
      import("./views/viz/history.js").then(h => h.undo());
    }
  }).catch(() => {});
}

function _doRedo() {
  import("./views/viz/state.js").then(mod => {
    if (mod.state && mod.state.frames && mod.state.frames.length > 0) {
      import("./views/viz/history.js").then(h => h.redo());
    }
  }).catch(() => {});
}

function _showShortcuts() {
  closeToolModal();

  const backdrop = document.createElement("div");
  backdrop.className = "ide-modal-backdrop";

  const modal = document.createElement("div");
  modal.className = "ide-modal ide-shortcuts-modal";
  modal.innerHTML = `
    <div class="ide-modal-titlebar">
      <span class="ide-modal-title">Keyboard Shortcuts</span>
      <button class="ide-modal-close">&times;</button>
    </div>
    <div class="ide-modal-content" style="padding:1rem;overflow:auto">
      <table class="ide-shortcut-table">
        <tr><th colspan="2">General</th></tr>
        <tr><td>Ctrl+B</td><td>Build ROM</td></tr>
        <tr><td>Ctrl+Shift+B</td><td>Build Output</td></tr>
        <tr><td>Ctrl+F</td><td>Focus Map Search</td></tr>
        <tr><td>Ctrl+,</td><td>Settings</td></tr>
        <tr><td>Ctrl+Q</td><td>Quit TORCH</td></tr>
        <tr><td>Escape</td><td>Close / Back</td></tr>
        <tr><th colspan="2">Modes</th></tr>
        <tr><td>F5</td><td>View Mode</td></tr>
        <tr><td>F6</td><td>Event Mode</td></tr>
        <tr><td>F7</td><td>Scripts Mode</td></tr>
        <tr><th colspan="2">Canvas Display</th></tr>
        <tr><td>G</td><td>Toggle Grid</td></tr>
        <tr><td>B</td><td>Toggle Border Tiles</td></tr>
        <tr><td>Shift+N</td><td>Toggle NPCs</td></tr>
        <tr><td>Shift+W</td><td>Toggle Warps</td></tr>
        <tr><td>Shift+T</td><td>Toggle Triggers</td></tr>
        <tr><td>Shift+S</td><td>Toggle Signs</td></tr>
        <tr><td>Shift+C</td><td>Toggle Collision</td></tr>
        <tr><th colspan="2">Scripts Mode</th></tr>
        <tr><td>J / K</td><td>Navigate beats</td></tr>
        <tr><td>Enter</td><td>Edit beat</td></tr>
        <tr><td>Space</td><td>Play / Pause</td></tr>
        <tr><td>Escape</td><td>Close editor / Unload / Exit mode</td></tr>
      </table>
    </div>
  `;

  backdrop.appendChild(modal);
  document.body.appendChild(backdrop);

  const close = () => {
    backdrop.remove();
    _activeModal = null;
  };

  modal.querySelector(".ide-modal-close").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) close();
  });

  _activeModal = close;
}

async function _showAbout() {
  let version = "?";
  let project = "?";
  let expansion = "?";
  try {
    const res = await api("/status");
    if (res.ok) {
      version = res.data.torch_version || "?";
      project = res.data.project_name || "?";
      expansion = res.data.expansion_version || "N/A";
    }
  } catch (_) {}

  closeToolModal();

  const backdrop = document.createElement("div");
  backdrop.className = "ide-modal-backdrop";

  const modal = document.createElement("div");
  modal.className = "ide-modal";
  modal.style.maxWidth = "380px";
  modal.innerHTML = `
    <div class="ide-modal-titlebar">
      <span class="ide-modal-title">About TORCH</span>
      <button class="ide-modal-close">&times;</button>
    </div>
    <div class="ide-modal-content" style="padding:1.5rem;text-align:center">
      <div style="font-size:2rem;margin-bottom:0.5rem">\u{1F525}</div>
      <h2 style="margin:0 0 0.25rem 0;color:var(--accent)">TORCH Studio</h2>
      <p style="margin:0 0 1rem 0;color:var(--text-muted);font-size:0.8rem">The Open ROM Creation Hub</p>
      <div style="font-size:0.78rem;color:var(--text-secondary);line-height:1.6">
        <div>Version: <strong>${esc(version)}</strong></div>
        <div>Project: <strong>${esc(project)}</strong></div>
        <div>Expansion: <strong>${esc(expansion)}</strong></div>
      </div>
    </div>
  `;

  backdrop.appendChild(modal);
  document.body.appendChild(backdrop);

  const close = () => {
    backdrop.remove();
    _activeModal = null;
  };

  modal.querySelector(".ide-modal-close").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) close();
  });

  _activeModal = close;
}
