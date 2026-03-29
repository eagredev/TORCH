/**
 * TORCH IDE — Toolbar (top bar).
 *
 * Dropdown menus: File, Edit, View, Tools.
 * Mode toggle (View / Events), Build button.
 * openToolModal() wraps existing views as floating modal dialogs.
 */

import { api, postApi } from "./app.js";
import { esc } from "./utils.js";
import { ideEmit, IDE_MODE_CHANGED, getSelectedMap } from "./ide.js";
import { toggleGrid, toggleNpcs, toggleWarps, toggleTriggers, toggleSigns, toggleBorders } from "./mapCanvas.js";

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
 * The modal overlays the IDE panels — clicking the backdrop or pressing
 * Escape closes it.
 *
 * @param {string} title — Modal title bar text
 * @param {() => Promise<{render, cleanup}>} loader — dynamic import fn
 * @param {string} [hashContext] — optional hash to set temporarily so the
 *   view picks up map context (e.g. "#/encounters/ShirubeTown")
 */
export async function openToolModal(title, loader, hashContext) {
  // Close any existing modal first
  closeToolModal();

  // Create backdrop
  const backdrop = document.createElement("div");
  backdrop.className = "ide-modal-backdrop";

  // Create modal window
  const modal = document.createElement("div");
  modal.className = "ide-modal";

  // Title bar
  const titleBar = document.createElement("div");
  titleBar.className = "ide-modal-titlebar";
  titleBar.innerHTML = `
    <span class="ide-modal-title">${esc(title)}</span>
    <button class="ide-modal-close">&times;</button>
  `;

  // Content area — this is where the view renders
  const content = document.createElement("div");
  content.className = "ide-modal-content";

  modal.appendChild(titleBar);
  modal.appendChild(content);
  backdrop.appendChild(modal);
  document.body.appendChild(backdrop);

  // Make title bar draggable
  _makeDraggable(modal, titleBar);

  // Load and render the view
  // Temporarily set hash so map-aware views pick up context
  const prevHash = window.location.hash;
  if (hashContext) {
    history.replaceState(null, "", hashContext);
  }

  let viewCleanup = null;
  try {
    const view = await loader();
    await view.render(content);
    viewCleanup = view.cleanup || null;
  } catch (err) {
    content.innerHTML = `<div style="padding:1rem;color:var(--status-error)">${esc(err.message)}</div>`;
  }

  // Restore hash to IDE route
  if (hashContext) {
    history.replaceState(null, "", prevHash || "#/ide");
  }

  // Close handlers
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

/** Close the currently open tool modal (if any). */
function closeToolModal() {
  if (_activeModal) {
    _activeModal();
    _activeModal = null;
  }
}

/** Make an element draggable by its handle. */
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
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      el.style.left = (startLeft + dx) + "px";
      el.style.top = (startTop + dy) + "px";
      el.style.transform = "none";   // override centered transform
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
// Menu definitions
// ---------------------------------------------------------------------------

/** Build a hash context for map-aware views, pointing at the selected map. */
function _mapHash(viewName) {
  const map = getSelectedMap();
  return map ? `#/${viewName}/${map}` : `#/${viewName}`;
}

const MENUS = [
  {
    name: "File",
    items: [
      { label: "Build ROM", shortcut: "Ctrl+B", action: _doBuild },
      { sep: true },
      { label: "Settings", action: () => openToolModal("Settings", () => import("./views/settings.js")) },
      { label: "Project", action: () => openToolModal("Project", () => import("./views/project.js")) },
      { label: "Version History", action: () => openToolModal("Versions", () => import("./views/versions.js")) },
    ],
  },
  {
    name: "Edit",
    items: [
      { label: "Find Map...", shortcut: "Ctrl+F", action: _doFocusSearch },
      { sep: true },
      { label: "Trainers", action: () => openToolModal("Trainers", () => import("./views/trainers.js")) },
      { label: "Encounters", action: () => openToolModal("Encounters", () => import("./views/encounters.js"), _mapHash("encounters")) },
      { label: "Shops", action: () => openToolModal("Shops", () => import("./views/shops.js"), _mapHash("shops")) },
      { label: "Heal Locations", action: () => openToolModal("Heals", () => import("./views/heals.js")) },
      { sep: true },
      { label: "Flags", action: () => openToolModal("Flags", () => import("./views/flags.js"), _mapHash("flags")) },
    ],
  },
  {
    name: "View",
    items: [
      { label: "Toggle Grid", shortcut: "G", action: _doToggleGrid },
      { label: "Toggle NPCs", action: () => toggleNpcs() },
      { label: "Toggle Warps", action: () => toggleWarps() },
      { label: "Toggle Triggers", action: () => toggleTriggers() },
      { label: "Toggle Signs", action: () => toggleSigns() },
      { label: "Toggle Border Tiles", shortcut: "B", action: () => toggleBorders() },
      { sep: true },
      { label: "Dex", action: () => openToolModal("Dex", () => import("./views/dex.js")) },
      { label: "Moves", action: () => openToolModal("Moves", () => import("./views/moves.js")) },
      { label: "Learnsets", action: () => openToolModal("Learnsets", () => import("./views/learnsets.js")) },
      { sep: true },
      { label: "Items", action: () => openToolModal("Items", () => import("./views/items.js")) },
      { label: "Asset Browser", action: () => openToolModal("Assets", () => import("./views/assets.js")) },
      { sep: true },
      { label: "Map Graph", action: () => openToolModal("Map Graph", () => import("./views/explorer.js")) },
      { label: "Dashboard", action: () => openToolModal("Dashboard", () => import("./views/dashboard.js")) },
    ],
  },
  {
    name: "Tools",
    items: [
      { label: "Tileset Editor", action: () => openToolModal("Tileset Editor", () => import("./views/tilesets.js")) },
      { label: "Templates", action: () => openToolModal("Templates", () => import("./views/templates.js")) },
      { sep: true },
      { label: "Scripts", action: () => openToolModal("Scripts", () => import("./views/scripts.js"), _mapHash("scripts")) },
      { label: "NPCs", action: () => openToolModal("NPCs", () => import("./views/npcs.js")) },
    ],
  },
];

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initToolbar(container) {
  _container = container;

  // Menu triggers (left section)
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
      itemBtn.innerHTML = `
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

  // Right section: mode toggle + build
  const rightDiv = document.createElement("div");
  rightDiv.className = "ide-toolbar-right";

  // Mode toggle
  const modeDiv = document.createElement("div");
  modeDiv.className = "ide-mode-toggle";
  modeDiv.id = "ide-mode-toggle";
  modeDiv.innerHTML = `
    <button class="ide-mode-btn active" data-mode="view" title="View Mode (F5)">View</button>
    <button class="ide-mode-btn" data-mode="events" title="Event Mode (F6)">Events</button>
    <button class="ide-mode-btn" data-mode="scripts" title="Scripts Mode (F7)">Scripts</button>
  `;
  modeDiv.querySelectorAll(".ide-mode-btn").forEach(btn => {
    btn.addEventListener("click", () => _setMode(btn.dataset.mode));
  });
  rightDiv.appendChild(modeDiv);

  // Build button
  const buildBtn = document.createElement("button");
  buildBtn.className = "ide-build-btn";
  buildBtn.textContent = "Build";
  buildBtn.title = "Build ROM (Ctrl+B)";
  buildBtn.addEventListener("click", _doBuild);
  rightDiv.appendChild(buildBtn);

  container.appendChild(rightDiv);

  // Close menus on outside click
  _docClickHandler = (e) => {
    if (!e.target.closest(".ide-toolbar-menus")) {
      _closeMenus();
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
  const toggle = document.getElementById("ide-mode-toggle");
  if (toggle) {
    toggle.querySelectorAll(".ide-mode-btn").forEach(b =>
      b.classList.toggle("active", b.dataset.mode === _mode));
  }
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

    // Scripts mode cascade: close editor → unload script → exit mode
    if (_mode === "scripts") {
      import("./scriptsMode.js").then(m => m.handleEscape(_setMode));
      e.preventDefault();
      return;
    }
  }

  // Ctrl+B — Build
  if (e.ctrlKey && e.key === "b") {
    e.preventDefault();
    _doBuild();
    return;
  }

  // Ctrl+F — Focus map search
  if (e.ctrlKey && e.key === "f") {
    e.preventDefault();
    _doFocusSearch();
    return;
  }

  // G — Toggle grid (when no modal open)
  if (!_activeModal && e.key === "g" && !e.ctrlKey && !e.altKey) {
    _doToggleGrid();
    return;
  }

  // B — Toggle border tiles
  if (!_activeModal && e.key === "b" && !e.ctrlKey && !e.altKey) {
    toggleBorders();
    return;
  }

  // F5 — View mode
  if (e.key === "F5") {
    e.preventDefault();
    _setMode("view");
    return;
  }

  // F6 — Event mode
  if (e.key === "F6") {
    e.preventDefault();
    _setMode("events");
    return;
  }

  // F7 — Scripts mode
  if (e.key === "F7") {
    e.preventDefault();
    _setMode("scripts");
    return;
  }
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

function _doToggleGrid() {
  toggleGrid();
}

function _doFocusSearch() {
  const search = document.getElementById("ide-tree-search");
  if (search) search.focus();
}
