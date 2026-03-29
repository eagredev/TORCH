/**
 * TORCH Web GUI — Shared Studio navigation bar.
 * Provides consistent "Studio | ToolName | Sub-tabs" navbar for all Studio tools.
 */

import { esc } from "./utils.js";

/**
 * Render a sticky navbar for a Studio tool.
 *
 * @param {string} toolName — Display name of the tool (e.g., "Trainers")
 * @param {Array} [tabs] — Optional sub-tabs: [{id, label}]
 * @param {string|null} [activeTab] — Currently active sub-tab id
 * @returns {string} HTML string for the navbar
 */
export function renderStudioNavbar(toolName, tabs = [], activeTab = null) {
  const studioLink = `<a href="#/studio" class="studio-nav-tab studio-nav-back">Studio</a>`;
  const homeTab = `<span class="studio-nav-tab studio-nav-active">${esc(toolName)}</span>`;
  const subTabs = tabs.map(t =>
    `<button class="studio-nav-tab${t.id === activeTab ? " studio-nav-active" : ""}" data-tab="${esc(t.id)}">${esc(t.label)}</button>`
  ).join("");
  return `<nav class="studio-nav">${studioLink}${homeTab}${subTabs}</nav>`;
}
