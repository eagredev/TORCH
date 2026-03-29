"""Tests for check.py — code quality gate."""
import os
import importlib.util

from torch.tests.harness import _begin_suite, _assert
from torch.check import run_check, _load_lizard, _scan_file, WARNING_THRESHOLD, ERROR_THRESHOLD


def run_suite():
    _begin_suite("Check (code quality gate)")

    # 1. run_check is importable
    _assert("run_check is callable", callable(run_check))

    # 2. run_check returns a boolean
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = run_check()
    _assert("run_check returns a boolean", isinstance(result, bool), f"got {type(result)}")

    # 3. Lizard import mechanism works
    lizard = _load_lizard()
    _assert("lizard loads successfully",
            lizard is not None and hasattr(lizard, "analyze_file"),
            "lizard module missing or no analyze_file")

    # 4. Scanning a single file works (use check.py itself)
    check_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "check.py"
    )
    funcs = _scan_file(lizard, check_path)
    func_names = [f[0] for f in funcs]
    _assert("scan finds functions in check.py",
            "run_check" in func_names and len(funcs) >= 3,
            f"found: {func_names}")

    # 5. A trivial function is not flagged
    trivial = [f for f in funcs if f[0] == "_load_lizard"]
    _assert("trivial function CCN <= WARNING_THRESHOLD",
            len(trivial) == 1 and trivial[0][1] <= WARNING_THRESHOLD,
            f"CCN={trivial[0][1] if trivial else '?'}")

    # 6. Warning threshold is 20
    _assert("WARNING_THRESHOLD is 20", WARNING_THRESHOLD == 20,
            f"got {WARNING_THRESHOLD}")

    # 7. Error threshold is 50
    _assert("ERROR_THRESHOLD is 50", ERROR_THRESHOLD == 50,
            f"got {ERROR_THRESHOLD}")
