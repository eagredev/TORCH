# TORCH_MODULE: Pokemon Actor Engine Patch
# TORCH_GROUP: Core
"""Detect and apply the ScriptUnfreezePokemonActor engine patch.

When lockall freezes all NPCs during scripts, Pokemon actors lose their
autonomous walk-in-place animation (bobbing). This patch adds a small C
function that unfreezes a specific object event by local ID, allowing
its movement type to resume. Called from compiled TorScript via callnative.
"""

import os
import re

_SENTINEL = "ScriptUnfreezePokemonActor"

_C_PATCH = '''
// Called from script via callnative to unfreeze a Pokemon actor.
// Reads local ID from VAR_0x8004.
// Unfreezes the object event so its autonomous movement type resumes.
// Used by TORCH to keep Pokemon actors animated during cutscenes.
// Injected by TORCH -- do not remove.
void ScriptUnfreezePokemonActor(void)
{
    u8 localId = (u8)gSpecialVar_0x8004;
    u8 objEventId;
    if (!TryGetObjectEventIdByLocalIdAndMap(localId, 0, 0, &objEventId))
        UnfreezeObjectEvent(&gObjectEvents[objEventId]);
}
'''

_H_DECL = "void ScriptUnfreezePokemonActor(void);"


def detect_pokemon_patch(game_path):
    """Return True if the engine patch is already applied."""
    c_path = os.path.join(game_path, "src", "event_object_movement.c")
    if not os.path.isfile(c_path):
        return False
    try:
        with open(c_path, "r") as f:
            return _SENTINEL in f.read()
    except OSError:
        return False


def apply_pokemon_patch(game_path):
    """Inject ScriptUnfreezePokemonActor into event_object_movement.c/.h.

    Returns (success: bool, message: str).
    """
    c_path = os.path.join(game_path, "src", "event_object_movement.c")
    h_path = os.path.join(game_path, "include", "event_object_movement.h")

    if not os.path.isfile(c_path):
        return False, f"File not found: {c_path}"
    if not os.path.isfile(h_path):
        return False, f"File not found: {h_path}"

    # --- Patch event_object_movement.c ---
    try:
        with open(c_path, "r") as f:
            c_content = f.read()
    except OSError as e:
        return False, f"Cannot read {c_path}: {e}"

    if _SENTINEL in c_content:
        return True, "Patch already applied."

    # Ensure event_data.h is included (provides gSpecialVar_0x8004)
    if '"event_data.h"' not in c_content:
        include_marker = '#include "global.h"'
        if include_marker in c_content:
            c_content = c_content.replace(
                include_marker,
                include_marker + '\n#include "event_data.h"'
            )

    # Find UnfreezeObjectEvents (plural) function and insert after it
    # This is the natural home for a single-object unfreeze helper
    marker = "void UnfreezeObjectEvents(void)"
    if marker in c_content:
        # Find the closing brace of UnfreezeObjectEvents
        marker_pos = c_content.index(marker)
        brace_pos = c_content.find("\n}\n", marker_pos)
        if brace_pos == -1:
            # Try end-of-file variant (no trailing newline after })
            brace_pos = c_content.find("\n}", marker_pos)
            if brace_pos == -1:
                return False, "Cannot find end of UnfreezeObjectEvents function."
            insert_pos = brace_pos + 2
        else:
            insert_pos = brace_pos + 3  # after "}\n"
    else:
        # Fallback: append at end of file
        insert_pos = len(c_content)

    c_content = c_content[:insert_pos] + _C_PATCH + c_content[insert_pos:]

    try:
        with open(c_path, "w") as f:
            f.write(c_content)
    except OSError as e:
        return False, f"Cannot write {c_path}: {e}"

    # --- Patch event_object_movement.h ---
    try:
        with open(h_path, "r") as f:
            h_content = f.read()
    except OSError as e:
        return False, f"Cannot read {h_path}: {e}"

    if _SENTINEL not in h_content:
        # Insert near related declarations
        h_marker = "void UnfreezeObjectEvents(void);"
        if h_marker in h_content:
            h_content = h_content.replace(
                h_marker,
                f"{h_marker}\n{_H_DECL}"
            )
        else:
            # Fallback: insert before the #endif guard
            h_content = h_content.replace(
                "#endif",
                f"{_H_DECL}\n\n#endif",
                1
            )

        try:
            with open(h_path, "w") as f:
                f.write(h_content)
        except OSError as e:
            return False, f"Cannot write {h_path}: {e}"

    return True, "Pokemon actor engine patch applied successfully."
