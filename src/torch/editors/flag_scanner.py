"""Flag cross-reference scanner -- find, parse, and manage game flags."""
# TORCH_MODULE: Flag Scanner
# TORCH_GROUP: Shared Infrastructure
import os
import re

from torch.gamedata import HEADER_FLAGS, clear_gamedata_cache

# Directories to skip during os.walk scans
_SKIP_DIRS = {".git", "build", "__pycache__"}

# Binary/non-text extensions to skip (avoid reading images, ROMs, etc.)
_BINARY_EXTS = {
    ".png", ".bmp", ".gif", ".jpg", ".jpeg", ".ico",
    ".gba", ".elf", ".o", ".a", ".so", ".bin", ".pal",
    ".lz", ".rl", ".pcm", ".aif", ".wav", ".mid",
    ".pyc", ".pyo",
}


# ---------------------------------------------------------------------------
# 1. scan_flag_references -- single-flag cross-reference scan
# ---------------------------------------------------------------------------

def scan_flag_references(flag_name, game_path):
    """Find all references to *flag_name* across the game project.

    Returns a list of dicts:
        {"file": relative_path, "line_num": int, "line_text": str, "category": str}

    Categories: header_define, header_alias, script_pory, script_inc,
                map_json, c_source, other.
    """
    if not flag_name or not game_path or not os.path.isdir(game_path):
        return []

    # Word-boundary anchored pattern prevents FLAG_TEMP_1 matching FLAG_TEMP_10
    pattern = re.compile(r"\b" + re.escape(flag_name) + r"\b")
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
                                                   flag_name)
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
# 2. scan_all_flags_bulk -- multi-flag scan in a single os.walk pass
# ---------------------------------------------------------------------------

def scan_all_flags_bulk(game_path, flag_names):
    """Scan for ALL given flag names in a single os.walk pass.

    Returns {flag_name: [ref_dict, ...]} where ref_dict matches the format
    from scan_flag_references.

    Much more efficient than N individual scans -- used by Phoenix and
    other bulk operations.
    """
    if not flag_names or not game_path or not os.path.isdir(game_path):
        return {name: [] for name in (flag_names or [])}

    # Deduplicate while preserving order for deterministic results
    unique_names = list(dict.fromkeys(flag_names))

    # Build a single compiled pattern from all flag names
    # Each name is \b-anchored and re.escaped for safety
    joined = "|".join(r"\b" + re.escape(name) + r"\b" for name in unique_names)
    pattern = re.compile(joined)

    # Build a fast lookup set for individual name extraction
    name_set = set(unique_names)

    # Per-name regex cache (compiled on demand) for extracting which flags
    # matched on a given line
    _name_patterns = {}

    def _get_name_pattern(name):
        if name not in _name_patterns:
            _name_patterns[name] = re.compile(r"\b" + re.escape(name) + r"\b")
        return _name_patterns[name]

    results = {name: [] for name in unique_names}

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
                        if not pattern.search(line_text):
                            continue
                        stripped = line_text.rstrip()
                        # Determine which flag(s) this line references
                        for name in unique_names:
                            if name not in line_text:
                                # Quick substring pre-check before regex
                                continue
                            if _get_name_pattern(name).search(line_text):
                                category = _categorize(rel, fname, ext,
                                                       line_text, name)
                                results[name].append({
                                    "file": rel,
                                    "line_num": line_num,
                                    "line_text": stripped,
                                    "category": category,
                                })
            except (OSError, UnicodeDecodeError):
                continue

    return results


# ---------------------------------------------------------------------------
# 3. parse_flags_h -- structured parsing of flags.h
# ---------------------------------------------------------------------------

_DEFINE_RE = re.compile(
    r"^#define\s+(FLAG_\w+|TEMP_FLAGS_\w+|TRAINER_FLAGS_\w+|"
    r"SYSTEM_FLAGS|DAILY_FLAGS_\w+|SPECIAL_FLAGS_\w+|"
    r"NUM_\w+FLAGS\w*|FLAGS_COUNT)\s+"
    r"(\S+(?:\s*\([^)]*\))?)\s*"
    r"(?://\s*(.*))?$"
)

_DEFINE_RE_BROAD = re.compile(
    r"^#define\s+(\w+)\s+(.+?)(?:\s*//\s*(.*))?$"
)

_ALIAS_RE = re.compile(
    r"^#define\s+(FLAG_\w+)\s+(FLAG_UNUSED_0x[0-9A-Fa-f]+)"
)

# Names that should never be added to section lists
_INFRA_NAMES = {"SYSTEM_FLAGS", "FLAGS_COUNT"}

# Names that mark range boundaries (not section entries)
_RANGE_MARKERS = {
    "TRAINER_FLAGS_START", "TRAINER_FLAGS_END",
    "SPECIAL_FLAGS_START", "SPECIAL_FLAGS_END",
    "DAILY_FLAGS_START", "DAILY_FLAGS_END",
}


def _detect_section(line, section):
    """Detect section transitions based on line content. Returns new section name."""
    if "TEMP_FLAGS_START" in line and "#define" in line and section == "pre":
        return "temp"
    if "TRAINER_FLAGS_START" in line and "#define" in line and section == "event":
        return "trainer"
    if line.strip().startswith("#define") and "SYSTEM_FLAGS" in line and section in ("trainer", "event"):
        return "system"
    if "DAILY_FLAGS_START" in line and "#define" in line and section == "system":
        return "daily"
    if "SPECIAL_FLAGS_START" in line and "#define" in line:
        return "special"
    if section == "temp" and "NUM_TEMP_FLAGS" in line:
        return "event"
    return section


def _classify_define(name, value_str, comment, line, section, result):
    """Classify a parsed #define and add to the appropriate section.

    Returns True if the entry was handled, False to skip.
    """
    if name in _INFRA_NAMES:
        return True
    if name.startswith("NUM_") or name.startswith("TEMP_FLAGS_"):
        return True

    # Range markers (trainer/special/daily start/end)
    if name in _RANGE_MARKERS:
        if name == "TRAINER_FLAGS_START":
            result["trainer_range"]["start"] = value_str
        elif name == "TRAINER_FLAGS_END":
            result["trainer_range"]["end"] = value_str
        return True

    is_unused = name.startswith("FLAG_UNUSED_")
    entry = (name, value_str, comment, is_unused)

    # Add to current section
    if section in result and isinstance(result[section], list):
        result[section].append(entry)

    # Track custom aliases
    alias_m = _ALIAS_RE.match(line)
    if alias_m:
        alias_name, target_name = alias_m.group(1), alias_m.group(2)
        if alias_name != target_name:
            result["custom_aliases"].append((alias_name, target_name))

    return True


def _empty_parse_result():
    """Return an empty parse result structure."""
    return {
        "temp": [],
        "event": [],
        "system": [],
        "daily": [],
        "special": [],
        "trainer_range": {"start": None, "end": None},
        "custom_aliases": [],
    }


def parse_flags_h(game_path):
    """Parse include/constants/flags.h into structured data.

    Returns a dict with keys:
        temp, event, system, daily, special, trainer_range, custom_aliases

    Each value (except trainer_range and custom_aliases) is a list of tuples:
        (name, hex_value_str, comment, is_unused)

    trainer_range is a dict: {"start": str, "end": str} with the raw
    constant names/values.

    custom_aliases is a list of tuples:
        (alias_name, target_unused_name)
    where target_unused_name is the FLAG_UNUSED_0xXXX being aliased.
    """
    flags_h = os.path.join(game_path, HEADER_FLAGS)
    if not os.path.isfile(flags_h):
        return _empty_parse_result()

    try:
        with open(flags_h, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return _empty_parse_result()

    section = "pre"
    result = _empty_parse_result()

    for raw_line in lines:
        line = raw_line.rstrip()
        section = _detect_section(line, section)

        m = _DEFINE_RE.match(line)
        if not m:
            m = _DEFINE_RE_BROAD.match(line)
        if not m:
            continue

        name = m.group(1).strip()
        value_str = m.group(2).strip()
        comment = (m.group(3) or "").strip()

        _classify_define(name, value_str, comment, line, section, result)

    return result


# ---------------------------------------------------------------------------
# 4. count_free_slots -- count unused flag slots in the event range
# ---------------------------------------------------------------------------

def count_free_slots(game_path):
    """Count FLAG_UNUSED_0xXXX in the event range NOT aliased by custom defines.

    Returns (free_count, total_event_slots).

    free_count: number of event-range entries where is_unused=True and the
                flag name is not targeted by any custom alias.
    total_event_slots: total number of entries in the event section.
    """
    parsed = parse_flags_h(game_path)
    event_entries = parsed["event"]
    total_event_slots = len(event_entries)

    # Build set of aliased target names
    aliased = {target for _, target in parsed["custom_aliases"]}

    free_count = 0
    for name, _val, _comment, is_unused in event_entries:
        if is_unused and name not in aliased:
            free_count += 1

    return free_count, total_event_slots


# ---------------------------------------------------------------------------
# 5. delete_flag_from_header -- remove a custom alias from flags.h
# ---------------------------------------------------------------------------

def delete_flag_from_header(game_path, flag_name):
    """Remove a custom alias line from flags.h. Returns True on success.

    Only removes lines of the form:
        #define FLAG_MY_CUSTOM  FLAG_UNUSED_0xXXX

    Never removes FLAG_UNUSED_* defines themselves (those are pool entries).
    After deletion, clears the gamedata cache.
    """
    if not flag_name or not game_path:
        return False

    # Refuse to delete pool entries
    if re.match(r"^FLAG_UNUSED_0x[0-9A-Fa-f]+$", flag_name):
        return False

    flags_h = os.path.join(game_path, HEADER_FLAGS)
    if not os.path.isfile(flags_h):
        return False

    try:
        with open(flags_h, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    # Find the line defining this flag as an alias of FLAG_UNUSED_*
    # Pattern: #define FLAG_NAME   FLAG_UNUSED_0xXXX  (optional comment)
    target_re = re.compile(
        r"^#define\s+" + re.escape(flag_name) + r"\s+FLAG_UNUSED_0x[0-9A-Fa-f]+"
    )

    found_idx = None
    for i, line in enumerate(lines):
        if target_re.match(line):
            found_idx = i
            break

    if found_idx is None:
        return False

    del lines[found_idx]

    try:
        with open(flags_h, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError:
        return False

    clear_gamedata_cache()
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _categorize(rel_path, fname, ext, line_text, flag_name):
    """Determine the reference category for a matched line.

    Categories: header_define, header_alias, script_pory, script_inc,
                map_json, c_source, other.
    """
    if ext == ".h":
        # Distinguish between a pool define and an alias
        if "#define" in line_text:
            # Check if this line defines the flag_name itself
            define_m = re.match(
                r"^#define\s+" + re.escape(flag_name) + r"\s", line_text
            )
            if define_m:
                return "header_define"
            # Check if flag_name appears as the value (i.e. it's aliased)
            alias_m = re.match(
                r"^#define\s+\w+\s+.*" + re.escape(flag_name), line_text
            )
            if alias_m:
                return "header_alias"
        return "header_define"
    elif ext == ".pory":
        return "script_pory"
    elif ext == ".inc":
        return "script_inc"
    elif fname == "map.json":
        return "map_json"
    elif ext == ".c":
        return "c_source"
    else:
        return "other"
