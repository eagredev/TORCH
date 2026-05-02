"""TORCH Test Harness — shared infrastructure.

Provides test result tracking, suite management, and assertion helpers
used by all individual test modules.
"""
import os
import time

# ---------------------------------------------------------------------------
# Harness infrastructure
# ---------------------------------------------------------------------------

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
from torch.colours import GREEN, BOLD_RED, DGOLD, BOLD, DIM, RST

_PASS = f"{GREEN}PASS{RST}"
_FAIL = f"{BOLD_RED}FAIL{RST}"
_SKIP = f"{DGOLD}SKIP{RST}"
# Backward-compat aliases (run_tests.py imports these names)
_BOLD = BOLD
_DIM = DIM
_RST = RST

_results = []   # (suite_name, test_name, status, detail)
_suite   = ""

# --- Options (set by run_all_tests before suites execute) ---
_quiet = False          # True = only show failures and summary
_fail_fast = False      # True = stop after first failure
_test_filter = None     # "test_name" substring filter within a suite
_aborted = False        # Set True when fail-fast triggers


def _begin_suite(name):
    global _suite
    _suite = name
    if not _quiet:
        print(f"\n  {BOLD}{name}{RST}")


def _ok(name):
    if _aborted:
        return
    if _test_filter and _test_filter not in name:
        return
    _results.append((_suite, name, "pass", ""))
    if not _quiet:
        print(f"    {_PASS}  {name}")


def _fail(name, detail):
    global _aborted
    if _aborted:
        return
    if _test_filter and _test_filter not in name:
        return
    _results.append((_suite, name, "fail", detail))
    print(f"    {_FAIL}  {_suite}::{name}")
    print(f"          {DIM}{detail}{RST}")
    if _fail_fast:
        _aborted = True


def _skip(name, reason):
    if _aborted:
        return
    if _test_filter and _test_filter not in name:
        return
    _results.append((_suite, name, "skip", reason))
    if not _quiet:
        print(f"    {_SKIP}  {name}  {DIM}({reason}){RST}")


def _assert(name, condition, detail="assertion failed"):
    if condition:
        _ok(name)
    else:
        _fail(name, detail)


def _fixture(name):
    return os.path.join(_FIXTURES, name)


def _summary():
    passed = sum(1 for r in _results if r[2] == "pass")
    failed = sum(1 for r in _results if r[2] == "fail")
    skipped = sum(1 for r in _results if r[2] == "skip")
    total = passed + failed + skipped
    print()
    if failed == 0:
        status = f"{BOLD}{GREEN}{passed}/{total} passed{RST}"
    else:
        status = f"{BOLD}{BOLD_RED}{failed} FAILED{RST}  {passed} passed"
    if skipped:
        status += f"  {DIM}{skipped} skipped{RST}"
    print(f"  {status}")
    print()
    return failed == 0
