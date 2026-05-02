"""TORCH Code Quality Check — cyclomatic complexity gate + guardrails."""
# TORCH_MODULE: Check
# TORCH_GROUP: Dev Tools

import os
import re
import importlib.util

from torch.colours import GOLD, GREEN, WHITE, RED, BOLD_RED, DIM, RST, BAR

# ── Thresholds ────────────────────────────────────────────────────────────────
WARNING_THRESHOLD = 20
ERROR_THRESHOLD = 50

# ── Lizard loader ─────────────────────────────────────────────────────────────
_LIZARD_PATH = os.path.expanduser("~/ROMHacking/TORCH/tools/lizard/lizard.py")


def _load_lizard():
    """Dynamically import lizard from local copy."""
    spec = importlib.util.spec_from_file_location("lizard", _LIZARD_PATH)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scan_file(lizard, filepath):
    """Scan a single file, return list of (func_name, ccn, nloc, start, end)."""
    result = lizard.analyze_file(filepath)
    return [
        (f.name, f.cyclomatic_complexity, f.nloc, f.start_line, f.end_line)
        for f in result.function_list
    ]


# ── Guardrail checks ─────────────────────────────────────────────────────────

# Files known to write Porymap JSON — check for indent=2
_PORYMAP_JSON_WRITERS = {
    "npc_editor.py", "sync.py", "upgrade.py", "scorch_writer.py",
    "scorch_patcher.py", "heal_locations.py", "project_files.py",
}

# Regex patterns
_INDENT_BAD = re.compile(r"json\.dump\s*\(.*indent\s*=\s*(?!2\b)\d+", re.DOTALL)
_INDENT_MULTILINE = re.compile(r"json\.dump\s*\([^)]*indent\s*=\s*(\d+)", re.DOTALL)
_UNICODE_ELLIPSIS = re.compile(r"\u2026")  # literal ...
_STABLE_PKG = "torch" + chr(95) + "stable"  # avoid self-match
_IMPORT_STABLE = re.compile(r"from\s+" + _STABLE_PKG + r"\b|import\s+" + _STABLE_PKG + r"\b")


def _run_guardrails(pkg_dir, web_dir):
    """Run static guardrail checks. Returns list of (file, line, message)."""
    issues = []

    # Collect all .py files to scan
    py_files = []
    for root, dirs, files in os.walk(pkg_dir):
        dirs[:] = [d for d in dirs if d not in {"tests", "__pycache__", ".git"}]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))

    for filepath in py_files:
        basename = os.path.basename(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            continue

        for i, line in enumerate(lines, 1):
            # Check 1: Unicode ellipsis in string literals or comments
            if "\u2026" in line:
                issues.append((filepath, i, "Unicode ellipsis found (use three dots '...' instead)"))

            # Check 2: Import from stable package
            if _IMPORT_STABLE.search(line):
                issues.append((filepath, i, f"Import from {_STABLE_PKG} (should import from torch.*)"))

            # Check 3: json.dump with wrong indent in Porymap JSON writers
            if basename in _PORYMAP_JSON_WRITERS and "json.dump" in line:
                # Check the line and the next few lines for the indent= arg
                chunk = "".join(lines[i-1:i+4])
                m = _INDENT_MULTILINE.search(chunk)
                if m and m.group(1) != "2":
                    issues.append((filepath, i, f"json.dump uses indent={m.group(1)} (must be indent=2 for Porymap JSON)"))

    return issues


# ── Main entry point ──────────────────────────────────────────────────────────

def run_check():
    """Run complexity check + guardrails on all torch_dev modules.

    Returns True if clean (no errors), False if any function exceeds ERROR_THRESHOLD
    or any guardrail check fails.
    """
    lizard = _load_lizard()
    if lizard is None:
        print(f"  {RED}Error: lizard not found at {_LIZARD_PATH}{RST}")
        return False

    # Navigate up from project/ to the torch package root
    pkg_dir = os.path.dirname(os.path.dirname(os.path.realpath(os.path.abspath(__file__))))
    web_dir = os.path.join(pkg_dir, "web")
    # Collect all .py files in the package (including subdirectories)
    _skip_dirs = {"tests", "data_files", "__pycache__"}
    module_paths = []
    for root, dirs, files in os.walk(pkg_dir):
        dirs[:] = [d for d in dirs if d not in _skip_dirs]
        for f in sorted(files):
            if f.endswith(".py") and not f.startswith("__"):
                module_paths.append(os.path.join(root, f))
    module_paths.sort()

    print(BAR)
    print(f"  {WHITE}TORCH Code Quality Check{RST}")
    print(BAR)
    print(f"\n  Scanning {len(module_paths)} modules...\n")

    errors = []
    warnings = []
    total_functions = 0

    for filepath in module_paths:
        mod_file = os.path.relpath(filepath, pkg_dir)
        funcs = _scan_file(lizard, filepath)
        total_functions += len(funcs)

        for name, ccn, nloc, start, end in funcs:
            if ccn > ERROR_THRESHOLD:
                errors.append((mod_file, name, ccn, nloc))
            elif ccn > WARNING_THRESHOLD:
                warnings.append((mod_file, name, ccn, nloc))

    if errors:
        print(f"  {BOLD_RED}ERRORS (CCN > {ERROR_THRESHOLD}):{RST}")
        for mod_file, name, ccn, nloc in errors:
            print(f"    {RED}{mod_file}:{name}{RST}  {DIM}CCN {ccn} ({nloc} lines){RST}")
        print()

    if warnings:
        print(f"  {GOLD}WARNINGS (CCN > {WARNING_THRESHOLD}):{RST}")
        for mod_file, name, ccn, nloc in warnings:
            print(f"    {GOLD}{mod_file}:{name}{RST}  {DIM}CCN {ccn} ({nloc} lines){RST}")
        print()

    if not errors and not warnings:
        print(f"  All functions within thresholds.\n")

    # ── Guardrails ────────────────────────────────────────────────────────────
    guardrail_issues = _run_guardrails(pkg_dir, web_dir)
    guardrail_ok = len(guardrail_issues) == 0

    if guardrail_issues:
        print(f"  {BOLD_RED}GUARDRAIL VIOLATIONS:{RST}")
        for filepath, line, msg in guardrail_issues:
            rel = os.path.relpath(filepath, pkg_dir)
            print(f"    {RED}{rel}:{line}{RST}  {DIM}{msg}{RST}")
        print()
    else:
        print(f"  {GREEN}Guardrails: all clear{RST}\n")

    # Summary
    print(BAR)
    e_str = f"{RED}{len(errors)} errors{RST}" if errors else f"{DIM}0 errors{RST}"
    w_str = f"{GOLD}{len(warnings)} warnings{RST}" if warnings else f"{DIM}0 warnings{RST}"
    g_str = f"{RED}{len(guardrail_issues)} guardrail violations{RST}" if guardrail_issues else f"{DIM}0 guardrail violations{RST}"
    print(f"  {DIM}{len(module_paths)} modules{RST} | {DIM}{total_functions} functions{RST} | {e_str} | {w_str} | {g_str}")
    print(BAR)

    return len(errors) == 0 and guardrail_ok
