"""Variable cross-reference scanner -- find, parse, and manage game variables."""
# TORCH_MODULE: Variable Scanner
# TORCH_GROUP: Shared Infrastructure
import os
import re

from torch.gamedata import HEADER_VARS, clear_gamedata_cache

# Directories to skip during os.walk scans
_SKIP_DIRS = {".git", "build", "__pycache__"}

# Binary/non-text extensions to skip
_BINARY_EXTS = {
    ".png", ".bmp", ".gif", ".jpg", ".jpeg", ".ico",
    ".gba", ".elf", ".o", ".a", ".so", ".bin", ".pal",
    ".lz", ".rl", ".pcm", ".aif", ".wav", ".mid",
    ".pyc", ".pyo",
}


# ---------------------------------------------------------------------------
# 1. scan_var_references -- single-variable cross-reference scan
# ---------------------------------------------------------------------------

def scan_var_references(var_name, game_path):
    """Find all references to *var_name* across the game project.

    Returns a list of dicts:
        {"file": relative_path, "line_num": int, "line_text": str, "category": str}

    Categories: header_define, script_pory, script_inc, c_source, other.
    """
    if not var_name or not game_path or not os.path.isdir(game_path):
        return []

    pattern = re.compile(r"\b" + re.escape(var_name) + r"\b")
    refs = []

    for dirpath, dirnames, filenames in os.walk(game_path):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in _BINARY_EXTS:
                continue
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, game_path)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line_num, line_text in enumerate(f, 1):
                        if pattern.search(line_text):
                            category = _categorize(rel, fname, ext, line_text,
                                                   var_name)
                            refs.append({
                                "file": rel,
                                "line_num": line_num,
                                "line_text": line_text.rstrip(),
                                "category": category,
                            })
            except (OSError, UnicodeDecodeError):
                continue

    return refs


# ---------------------------------------------------------------------------
# 2. parse_vars_h -- structured parsing of vars.h
# ---------------------------------------------------------------------------

_DEFINE_RE = re.compile(
    r"^#define\s+(VAR_\w+|TEMP_VARS_\w+|VARS_\w+|NUM_\w+VARS\w*)\s+"
    r"(\S+(?:\s*\([^)]*\))?)\s*"
    r"(?://\s*(.*))?$"
)

_DEFINE_RE_BROAD = re.compile(
    r"^#define\s+(\w+)\s+(.+?)(?:\s*//\s*(.*))?$"
)

# Names that are infrastructure, not actual variables
_INFRA_NAMES = {
    "VARS_START", "VARS_COUNT", "VARS_END",
    "TEMP_VARS_START", "TEMP_VARS_END", "NUM_TEMP_VARS",
    "SPECIAL_VARS_START", "SPECIAL_VARS_END",
}

# Range boundary markers
_RANGE_MARKERS = {
    "TEMP_VARS_START", "TEMP_VARS_END", "NUM_TEMP_VARS",
    "SPECIAL_VARS_START", "SPECIAL_VARS_END",
}


def _detect_var_section(line, section):
    """Detect section transitions based on line content."""
    stripped = line.strip()
    if "TEMP_VARS_START" in stripped and "#define" in stripped and section == "pre":
        return "temp"
    if "VAR_OBJ_GFX_ID_0" in stripped and section == "temp":
        return "graphics"
    if section == "temp" and "NUM_TEMP_VARS" in stripped:
        return "graphics"
    # After graphics IDs (0x401F), general purpose starts at 0x4020
    if section == "graphics" and not stripped.startswith("#define VAR_OBJ_GFX_ID_"):
        if stripped.startswith("#define VAR_"):
            return "persistent"
    if "SPECIAL_VARS_START" in stripped or "0x8000" in stripped:
        if section in ("persistent", "graphics"):
            return "special"
    return section


def _empty_parse_result():
    """Return an empty parse result structure."""
    return {
        "temp": [],
        "graphics": [],
        "persistent": [],
        "special": [],
    }


def parse_vars_h(game_path):
    """Parse include/constants/vars.h into structured data.

    Returns a dict with keys:
        temp, graphics, persistent, special

    Each value is a list of tuples:
        (name, value_str, comment, is_unused)
    """
    vars_h = os.path.join(game_path, HEADER_VARS)
    if not os.path.isfile(vars_h):
        return _empty_parse_result()

    try:
        with open(vars_h, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return _empty_parse_result()

    section = "pre"
    result = _empty_parse_result()

    for raw_line in lines:
        line = raw_line.rstrip()
        section = _detect_var_section(line, section)

        m = _DEFINE_RE.match(line)
        if not m:
            m = _DEFINE_RE_BROAD.match(line)
        if not m:
            continue

        name = m.group(1).strip()
        value_str = m.group(2).strip()
        comment = (m.group(3) or "").strip()

        # Skip infrastructure defines
        if name in _INFRA_NAMES:
            continue
        if name.startswith("NUM_") or name.startswith("TEMP_VARS_"):
            continue
        if name == "VARS_START":
            continue

        # Skip guard macros
        if name.startswith("GUARD_"):
            continue

        # Only include VAR_* names
        if not name.startswith("VAR_"):
            continue

        is_unused = "Unused" in comment or name.startswith("VAR_UNUSED_")
        entry = (name, value_str, comment, is_unused)

        if section in result:
            result[section].append(entry)

    return result


# ---------------------------------------------------------------------------
# 3. count_free_var_slots -- count unused variable slots
# ---------------------------------------------------------------------------

def count_free_var_slots(game_path):
    """Count VAR_UNUSED_* entries in the persistent range.

    Returns (free_count, total_persistent_slots).
    """
    parsed = parse_vars_h(game_path)
    persistent = parsed["persistent"]
    total = len(persistent)
    free = sum(1 for name, _, _, is_unused in persistent if is_unused)
    return free, total


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _categorize(rel_path, fname, ext, line_text, var_name):
    """Determine the reference category for a matched line."""
    if ext == ".h":
        if "#define" in line_text:
            return "header_define"
        return "header_define"
    elif ext == ".pory":
        return "script_pory"
    elif ext == ".inc":
        return "script_inc"
    elif ext == ".c":
        return "c_source"
    else:
        return "other"
