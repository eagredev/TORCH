"""Script round-trip suite -- parse then serialize then compare."""
from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert, _fixture


def run_suite():
    _begin_suite("Script round-trip  (parse → serialize → compare)")

    try:
        from torch.script_model import _parse_script, _serialize_script
    except ImportError as e:
        _skip("all script round-trip tests", f"import failed: {e}")
        return

    fixtures = ["Officer.txt", "Buster.txt", "Clyde.txt", "ClydeArrives.txt"]

    for fname in fixtures:
        path = _fixture(fname)
        try:
            # Read original text
            with open(path, "r") as f:
                original = f.read()

            # Parse then serialize
            script_data = _parse_script(path)
            serialized = _serialize_script(script_data)

            # Compare line by line (ignoring trailing whitespace on each line
            # and trailing newlines at end of file — cosmetic differences only)
            orig_lines = [l.rstrip() for l in original.rstrip().splitlines()]
            new_lines  = [l.rstrip() for l in serialized.rstrip().splitlines()]

            if orig_lines == new_lines:
                _ok(f"{fname}: round-trip matches original")
            else:
                # Find first difference for a useful error message
                for i, (a, b) in enumerate(zip(orig_lines, new_lines)):
                    if a != b:
                        _fail(
                            f"{fname}: round-trip mismatch",
                            f"line {i+1}: original={repr(a)}  got={repr(b)}"
                        )
                        break
                else:
                    _fail(
                        f"{fname}: round-trip length mismatch",
                        f"original={len(orig_lines)} lines  got={len(new_lines)} lines"
                    )

        except Exception as e:
            _fail(f"{fname}: round-trip raised", str(e))

    # Structural check: parsed beat list is non-empty for a known script
    try:
        script_data = _parse_script(_fixture("ClydeArrives.txt"))
        _assert(
            "ClydeArrives.txt: parsed beat list is non-empty",
            len(script_data.get("beats", [])) > 0,
            "beat list was empty after parse"
        )
        _assert(
            "ClydeArrives.txt: cast contains 'buster' and 'clyde'",
            "buster" in script_data.get("cast", {}) and "clyde" in script_data.get("cast", {}),
            f"cast was: {script_data.get('cast')}"
        )
    except Exception as e:
        _fail("ClydeArrives.txt: structural check raised", str(e))
