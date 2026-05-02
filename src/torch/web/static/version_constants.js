/**
 * Expansion version thresholds -- mirrors expansion_compat.py feature registry.
 *
 * Usage:
 *   import { versionGate } from "./app.js";
 *   import { MOVESET_REFACTOR } from "./version_constants.js";
 *   if (await versionGate(...MOVESET_REFACTOR)) { // show tab }
 */

// Trainer system
export const PARTY_FORMAT = [1, 9, 0];
export const TRAINER_BATTLE_CONSOLIDATED = [1, 11, 0];
export const AI_FLAGS_U64 = [1, 12, 0];

// Encounter system
export const TIME_BASED_ENCOUNTERS = [1, 12, 0];

// Build system
export const MAKE_RELEASE = [1, 14, 0];

// Data refactors
export const MOVESET_REFACTOR = [1, 14, 0];
