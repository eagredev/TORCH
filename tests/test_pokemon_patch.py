"""Pokemon actor engine patch suite -- detect/apply ScriptUnfreezePokemonActor."""
import os
import tempfile

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Pokemon Patch")

    try:
        from torch.pokemon_patch import detect_pokemon_patch, apply_pokemon_patch
    except ImportError as e:
        _skip("all pokemon patch tests", f"import failed: {e}")
        return

    # ---- detect_patch_absent ----
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            inc = os.path.join(tmp, "include")
            os.makedirs(src)
            os.makedirs(inc)
            with open(os.path.join(src, "event_object_movement.c"), "w") as f:
                f.write('#include "global.h"\nvoid UnfreezeObjectEvents(void)\n{\n}\n')
            with open(os.path.join(inc, "event_object_movement.h"), "w") as f:
                f.write('#ifndef GUARD_EVENT_OBJECT_MOVEMENT_H\n'
                        '#define GUARD_EVENT_OBJECT_MOVEMENT_H\n'
                        'void UnfreezeObjectEvents(void);\n'
                        '#endif\n')
            result = detect_pokemon_patch(tmp)
            _assert("detect_patch_absent: returns False", result is False,
                    f"expected False, got {result}")
    except Exception as e:
        _fail("detect_patch_absent", str(e))

    # ---- detect_patch_present ----
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "event_object_movement.c"), "w") as f:
                f.write('void ScriptUnfreezePokemonActor(void) {}\n')
            result = detect_pokemon_patch(tmp)
            _assert("detect_patch_present: returns True", result is True,
                    f"expected True, got {result}")
    except Exception as e:
        _fail("detect_patch_present", str(e))

    # ---- detect_patch_missing_file ----
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = detect_pokemon_patch(tmp)
            _assert("detect_patch_missing_file: returns False", result is False,
                    f"expected False, got {result}")
    except Exception as e:
        _fail("detect_patch_missing_file", str(e))

    # ---- apply_patch_success ----
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            inc = os.path.join(tmp, "include")
            os.makedirs(src)
            os.makedirs(inc)
            with open(os.path.join(src, "event_object_movement.c"), "w") as f:
                f.write('#include "global.h"\n\n'
                        'void UnfreezeObjectEvents(void)\n'
                        '{\n'
                        '    // body\n'
                        '}\n')
            with open(os.path.join(inc, "event_object_movement.h"), "w") as f:
                f.write('#ifndef GUARD_EVENT_OBJECT_MOVEMENT_H\n'
                        '#define GUARD_EVENT_OBJECT_MOVEMENT_H\n'
                        'void UnfreezeObjectEvents(void);\n'
                        '#endif\n')

            ok, msg = apply_pokemon_patch(tmp)
            _assert("apply_patch_success: returns True", ok is True,
                    f"got ({ok}, {msg})")

            # Check .c file contains the sentinel
            with open(os.path.join(src, "event_object_movement.c")) as f:
                c_content = f.read()
            _assert("apply_patch_success: .c has sentinel",
                    "ScriptUnfreezePokemonActor" in c_content,
                    "sentinel not found in .c")
            _assert("apply_patch_success: .c has event_data.h include",
                    '"event_data.h"' in c_content,
                    "event_data.h include not added")

            # Check .h file contains the declaration
            with open(os.path.join(inc, "event_object_movement.h")) as f:
                h_content = f.read()
            _assert("apply_patch_success: .h has declaration",
                    "void ScriptUnfreezePokemonActor(void);" in h_content,
                    "declaration not found in .h")
    except Exception as e:
        _fail("apply_patch_success", str(e))

    # ---- apply_patch_idempotent ----
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            inc = os.path.join(tmp, "include")
            os.makedirs(src)
            os.makedirs(inc)
            with open(os.path.join(src, "event_object_movement.c"), "w") as f:
                f.write('#include "global.h"\n\n'
                        'void UnfreezeObjectEvents(void)\n'
                        '{\n}\n')
            with open(os.path.join(inc, "event_object_movement.h"), "w") as f:
                f.write('#ifndef GUARD_EVENT_OBJECT_MOVEMENT_H\n'
                        '#define GUARD_EVENT_OBJECT_MOVEMENT_H\n'
                        'void UnfreezeObjectEvents(void);\n'
                        '#endif\n')

            # Apply first time
            ok1, msg1 = apply_pokemon_patch(tmp)
            _assert("apply_patch_idempotent: first apply succeeds", ok1 is True,
                    f"first apply: ({ok1}, {msg1})")

            # Read content after first apply
            with open(os.path.join(src, "event_object_movement.c")) as f:
                content_after_first = f.read()

            # Apply second time
            ok2, msg2 = apply_pokemon_patch(tmp)
            _assert("apply_patch_idempotent: second apply succeeds", ok2 is True,
                    f"second apply: ({ok2}, {msg2})")
            _assert("apply_patch_idempotent: second apply says already applied",
                    "already applied" in msg2.lower(),
                    f"expected 'already applied' in msg: {msg2}")

            # Content unchanged
            with open(os.path.join(src, "event_object_movement.c")) as f:
                content_after_second = f.read()
            _assert("apply_patch_idempotent: file unchanged on second apply",
                    content_after_first == content_after_second,
                    "file content changed on second apply")
    except Exception as e:
        _fail("apply_patch_idempotent", str(e))

    # ---- apply_patch_missing_file ----
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg = apply_pokemon_patch(tmp)
            _assert("apply_patch_missing_file: returns False", ok is False,
                    f"expected False, got ({ok}, {msg})")
    except Exception as e:
        _fail("apply_patch_missing_file", str(e))

    # ---- apply_patch_fallback_no_marker ----
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            inc = os.path.join(tmp, "include")
            os.makedirs(src)
            os.makedirs(inc)
            # .c without UnfreezeObjectEvents marker — falls back to append
            with open(os.path.join(src, "event_object_movement.c"), "w") as f:
                f.write('#include "global.h"\n\nvoid SomeOtherFunc(void)\n{\n}\n')
            with open(os.path.join(inc, "event_object_movement.h"), "w") as f:
                f.write('#ifndef GUARD\n#define GUARD\n#endif\n')

            ok, msg = apply_pokemon_patch(tmp)
            _assert("apply_patch_fallback: succeeds", ok is True,
                    f"got ({ok}, {msg})")
            with open(os.path.join(src, "event_object_movement.c")) as f:
                c_content = f.read()
            _assert("apply_patch_fallback: sentinel in .c",
                    "ScriptUnfreezePokemonActor" in c_content,
                    "sentinel not found after fallback append")
    except Exception as e:
        _fail("apply_patch_fallback", str(e))
