# TORCH_MODULE: Camera Engine Patch
# TORCH_GROUP: Core
"""Detect and apply the ScriptResetCameraOffset engine patch.

The GBA camera system silently shifts gSaveBlock1Ptr->pos when the camera
object moves via applymovement.  RemoveCameraObject does NOT undo this, and
battles destroy the camera object while the offset persists.

The patch adds a small C function (ScriptResetCameraOffset) to field_camera.c
that reverses the offset by calling MoveCameraAndRedrawMap with negated values.
It is called from script via callnative and reads the accumulated pan offset
from VAR_0x8004 (X) and VAR_0x8005 (Y).
"""

import os
import re

_SENTINEL = "ScriptResetCameraOffset"

_C_PATCH = '''
// Called from script via callnative to undo camera pan offsets.
// Reads pan tile offset from VAR_0x8004 (X) and VAR_0x8005 (Y),
// reverses the CameraMove() position shift, and redraws the map.
// Injected by TORCH -- do not remove.
void ScriptResetCameraOffset(void)
{
    s16 dx = (s16)gSpecialVar_0x8004;
    s16 dy = (s16)gSpecialVar_0x8005;
    if (dx != 0 || dy != 0)
        MoveCameraAndRedrawMap(-dx, -dy);
}
'''

_H_DECL = "void ScriptResetCameraOffset(void);"


def detect_camera_patch(game_path):
    """Return True if the engine patch is already applied."""
    c_path = os.path.join(game_path, "src", "field_camera.c")
    if not os.path.isfile(c_path):
        return False
    try:
        with open(c_path, "r") as f:
            return _SENTINEL in f.read()
    except OSError:
        return False


def apply_camera_patch(game_path):
    """Inject ScriptResetCameraOffset into field_camera.c and field_camera.h.

    Returns (success: bool, message: str).
    """
    c_path = os.path.join(game_path, "src", "field_camera.c")
    h_path = os.path.join(game_path, "include", "field_camera.h")

    if not os.path.isfile(c_path):
        return False, f"File not found: {c_path}"
    if not os.path.isfile(h_path):
        return False, f"File not found: {h_path}"

    # --- Patch field_camera.c ---
    try:
        with open(c_path, "r") as f:
            c_content = f.read()
    except OSError as e:
        return False, f"Cannot read {c_path}: {e}"

    if _SENTINEL in c_content:
        return True, "Patch already applied."

    # Ensure event_data.h is included (provides gSpecialVar_0x8004/0x8005)
    if '"event_data.h"' not in c_content:
        # Insert after an existing #include line
        include_marker = '#include "global.h"'
        if include_marker in c_content:
            c_content = c_content.replace(
                include_marker,
                include_marker + '\n#include "event_data.h"'
            )

    # Insert after MoveCameraAndRedrawMap function
    marker = "void MoveCameraAndRedrawMap(int deltaX, int deltaY)"
    if marker not in c_content:
        return False, (f"Cannot find '{marker}' in field_camera.c. "
                       "Is this a standard pokeemerald or pokeemerald-expansion project?")

    # Find the closing brace of MoveCameraAndRedrawMap
    marker_pos = c_content.index(marker)
    # Find the next closing brace at column 0 after the marker
    brace_pos = c_content.find("\n}\n", marker_pos)
    if brace_pos == -1:
        return False, "Cannot find end of MoveCameraAndRedrawMap function."

    insert_pos = brace_pos + 3  # after "}\n"
    c_content = c_content[:insert_pos] + _C_PATCH + c_content[insert_pos:]

    try:
        with open(c_path, "w") as f:
            f.write(c_content)
    except OSError as e:
        return False, f"Cannot write {c_path}: {e}"

    # --- Patch field_camera.h ---
    try:
        with open(h_path, "r") as f:
            h_content = f.read()
    except OSError as e:
        return False, f"Cannot read {h_path}: {e}"

    if _SENTINEL not in h_content:
        # Insert after InstallCameraPanAheadCallback declaration
        h_marker = "void InstallCameraPanAheadCallback(void);"
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

    return True, "Camera engine patch applied successfully."
