"""Shared game-data parser with session-level caching.

Replaces the per-module header parsers in pickers.py, sync.py, and
battle_wizard.py.  All results are cached for the lifetime of the process.
Call clear_gamedata_cache() if you need to force a re-read (e.g. the user
has just edited a header file mid-session).

NOTE: _CACHE persists for the process lifetime.  If the user edits a game
header between two sync operations in the same session they will see stale
data.  clear_gamedata_cache() is the escape hatch.
"""
# TORCH_MODULE: Game Data
# TORCH_GROUP: Core
import os
import re

GAMEDATA_VERSION = "1.0"

# Cache keyed by (realpath, prefix_or_kind)
_CACHE = {}

# ---------------------------------------------------------------------------
# Relative path constants (relative to game_path root)
# ---------------------------------------------------------------------------

HEADER_FLAGS     = os.path.join("include", "constants", "flags.h")
HEADER_VARS      = os.path.join("include", "constants", "vars.h")
HEADER_TRAINERS  = os.path.join("include", "constants", "opponents.h")
HEADER_SONGS     = os.path.join("include", "constants", "songs.h")
HEADER_SOUND     = os.path.join("include", "constants", "sound.h")
HEADER_SPECIES   = os.path.join("include", "constants", "species.h")
HEADER_SPECIALS  = os.path.join("data", "specials.inc")
# For Phase 3+ data editors
HEADER_MOVES     = os.path.join("include", "constants", "moves.h")
HEADER_ITEMS     = os.path.join("include", "constants", "items.h")
HEADER_ABILITIES = os.path.join("include", "constants", "abilities.h")
HEADER_BATTLE_AI = os.path.join("include", "constants", "battle_ai.h")
HEADER_POKEDEX   = os.path.join("include", "constants", "pokedex.h")


# ---------------------------------------------------------------------------
# Core parsers (with caching)
# ---------------------------------------------------------------------------

def parse_defines(header_path, prefix=None):
    """Parse #define lines from a .h file, capturing inline // comments.

    Returns [(name, comment), ...] sorted by name.  Only includes defines
    whose name starts with *prefix* (if given).  Results are cached.
    """
    if not header_path or not os.path.exists(header_path):
        return []
    try:
        key = (os.path.realpath(header_path), prefix or "")
    except OSError:
        key = (header_path, prefix or "")
    if key in _CACHE:
        return _CACHE[key]

    results = []
    if prefix:
        pattern = re.compile(
            r"^#define\s+(" + re.escape(prefix) + r"\w+)\s+(?:.*?)(?:\s+//\s*(.*))?$"
        )
    else:
        pattern = re.compile(
            r"^#define\s+(\w+)\s+(?:.*?)(?:\s+//\s*(.*))?$"
        )
    try:
        with open(header_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pattern.match(line.rstrip())
                if m:
                    name = m.group(1)
                    comment = (m.group(2) or "").strip()
                    results.append((name, comment))
    except OSError:
        pass
    results.sort(key=lambda x: x[0])
    _CACHE[key] = results
    return results


def parse_defines_full(header_path, prefix=None):
    """Parse #define lines, returning name, value, AND comment.

    Returns [(name, value, comment), ...] sorted by name.
    Value is the raw token(s) between the name and the // comment (stripped).
    For multi-token values like ``(1 << 0)``, the full expression is captured.
    If a define has no value (bare ``#define NAME``), value is empty string.

    Results are cached under a separate key from parse_defines().
    """
    if not header_path or not os.path.exists(header_path):
        return []
    try:
        key = (os.path.realpath(header_path), "_full_" + (prefix or ""))
    except OSError:
        key = (header_path, "_full_" + (prefix or ""))
    if key in _CACHE:
        return _CACHE[key]

    results = []
    _def_re = re.compile(r"^#define\s+(\w+)")
    try:
        with open(header_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.rstrip()
                m = _def_re.match(stripped)
                if not m:
                    continue
                name = m.group(1)
                if prefix and not name.startswith(prefix):
                    continue
                rest = stripped[m.end():]
                comment = ""
                value = ""
                comment_pos = rest.find("//")
                if comment_pos >= 0:
                    comment = rest[comment_pos + 2:].strip()
                    value = rest[:comment_pos].strip()
                else:
                    value = rest.strip()
                results.append((name, value, comment))
    except OSError:
        pass
    results.sort(key=lambda x: x[0])
    _CACHE[key] = results
    return results


def parse_defines_set(header_path, prefix=None):
    """Return a set of constant names — derives from parse_defines (no re-read).

    Replaces battle_wizard._parse_defines().
    """
    return {name for name, _ in parse_defines(header_path, prefix)}


def parse_specials(specials_path):
    """Parse data/specials.inc for def_special FuncName lines.

    Returns sorted list of function name strings.  Results are cached.
    """
    if not specials_path or not os.path.exists(specials_path):
        return []
    try:
        key = (os.path.realpath(specials_path), "specials")
    except OSError:
        key = (specials_path, "specials")
    if key in _CACHE:
        return _CACHE[key]

    results = []
    pattern = re.compile(r"^\s*def_special\s+(\w+)")
    try:
        with open(specials_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pattern.match(line)
                if m:
                    results.append(m.group(1))
    except OSError:
        pass
    results.sort()
    _CACHE[key] = results
    return results


_SPECIES_DATA_CACHE = {}
_LEARNSET_CACHE = {}


def clear_gamedata_cache():
    """Clear all cached header data.  Call if headers were edited mid-session."""
    _CACHE.clear()
    _SPECIES_DATA_CACHE.clear()
    _LEARNSET_CACHE.clear()


# ---------------------------------------------------------------------------
# C struct initializer parsers
# ---------------------------------------------------------------------------

def _extract_brace_block(text, start_pos):
    """From start_pos (pointing at '{'), find the matching '}' respecting nesting.

    Handles nested braces, strings, line comments, and block comments.
    Returns the substring from start_pos through the matching '}' (inclusive),
    or None if braces are unbalanced.
    """
    depth = 0
    i = start_pos
    in_string = False
    in_line_comment = False
    in_block_comment = False
    length = len(text)
    while i < length:
        ch = text[i]
        if in_line_comment:
            if ch == '\n':
                in_line_comment = False
        elif in_block_comment:
            if ch == '*' and i + 1 < length and text[i + 1] == '/':
                in_block_comment = False
                i += 1
        elif in_string:
            if ch == '\\':
                i += 1  # skip escaped char
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == '/' and i + 1 < length:
                if text[i + 1] == '/':
                    in_line_comment = True
                elif text[i + 1] == '*':
                    in_block_comment = True
                    i += 1
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start_pos:i + 1]
        i += 1
    return None  # unbalanced


def _strip_c_comments(text):
    """Remove // and /* */ comments from a string."""
    result = []
    i = 0
    in_string = False
    length = len(text)
    while i < length:
        ch = text[i]
        if in_string:
            result.append(ch)
            if ch == '\\' and i + 1 < length:
                i += 1
                result.append(text[i])
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            result.append(ch)
        elif ch == '/' and i + 1 < length:
            if text[i + 1] == '/':
                # skip to end of line
                while i < length and text[i] != '\n':
                    i += 1
                continue
            elif text[i + 1] == '*':
                i += 2
                while i + 1 < length and not (text[i] == '*' and text[i + 1] == '/'):
                    i += 1
                i += 2  # skip */
                continue
            else:
                result.append(ch)
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


def _strip_line_directives(text):
    """Remove #line and #if/#endif preprocessor directives."""
    return re.sub(r'^#(?:line|if|ifdef|ifndef|endif|else|elif)\b[^\n]*\n?',
                  '', text, flags=re.MULTILINE)


def _parse_fields_from_block(block_inner):
    """Parse .field = value assignments from the inner content of a brace block.

    Returns dict of field_name -> raw_value_string.
    """
    fields = {}
    text = block_inner
    # Find all .field = ... patterns
    field_re = re.compile(r'\.(\w+)\s*=\s*')
    pos = 0
    matches = list(field_re.finditer(text))
    for idx, m in enumerate(matches):
        field_name = m.group(1)
        val_start = m.end()
        value = _extract_field_value(text, val_start, matches, idx)
        fields[field_name] = value.strip()
    return fields


def _extract_field_value(text, val_start, matches, idx):
    """Extract a single field value starting at val_start.

    Scans forward respecting nested braces and parentheses until hitting
    a comma at depth 0, or the start of the next field, or end of text.
    """
    # Determine the boundary: next field start or end of text
    if idx + 1 < len(matches):
        boundary = matches[idx + 1].start()
    else:
        boundary = len(text)
    depth_brace = 0
    depth_paren = 0
    i = val_start
    in_string = False
    value_end = boundary
    while i < boundary:
        ch = text[i]
        if in_string:
            if ch == '\\' and i + 1 < boundary:
                i += 2
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == '{':
                depth_brace += 1
            elif ch == '}':
                if depth_brace > 0:
                    depth_brace -= 1
                else:
                    value_end = i
                    break
            elif ch == '(':
                depth_paren += 1
            elif ch == ')':
                if depth_paren > 0:
                    depth_paren -= 1
            elif ch == ',' and depth_brace == 0 and depth_paren == 0:
                value_end = i
                break
        i += 1
    raw = text[val_start:value_end].strip()
    # Strip trailing comma if present
    if raw.endswith(','):
        raw = raw[:-1].strip()
    return raw


def _read_and_clean(filepath):
    """Read a C source file and strip comments and preprocessor line directives."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    text = _strip_c_comments(text)
    text = _strip_line_directives(text)
    return text


def _cache_key(filepath, kind, extra=None):
    """Build a cache key tuple for struct parsing results."""
    try:
        rp = os.path.realpath(filepath)
    except OSError:
        rp = filepath
    return (rp, kind, extra)


def parse_struct_entries(filepath, index_prefix=None, macros=None):
    """Parse all [INDEX_NAME] = { ... } blocks from a C source file.

    Args:
        filepath: Path to the C source file (.c or .h).
        index_prefix: If provided, only return entries whose index starts
            with this prefix (e.g., "SPECIES_").
        macros: If provided, dict of macro definitions from _collect_file_macros().
            Enables expansion of macro-defined entries (e.g. Alcremie forms).

    Returns:
        dict mapping index name to a dict of field_name -> raw_value_string.
        On error returns {}.
    """
    if not filepath or not os.path.exists(filepath):
        return {}
    # Include macros presence in cache key to avoid stale results
    cache_extra = (index_prefix, "with_macros" if macros else None)
    key = _cache_key(filepath, "struct_entries", cache_extra)
    if key in _CACHE:
        return _CACHE[key]

    text = _read_and_clean(filepath)
    if text is None:
        _CACHE[key] = {}
        return {}

    results = _scan_indexed_entries(text, index_prefix, macros)
    _CACHE[key] = results
    return results


def _scan_indexed_entries(text, index_prefix, macros=None):
    """Scan text for [INDEX] = { ... } blocks and parse their fields.

    When the value after '=' is a macro call instead of '{', expands the
    macro using *macros* dict and parses the resulting struct block.
    """
    results = {}
    entry_re = re.compile(r'\[(\w+)\]\s*=\s*')
    pos = 0
    while pos < len(text):
        m = entry_re.search(text, pos)
        if not m:
            break
        index_name = m.group(1)
        after_eq = m.end()
        # Find the opening brace
        brace_pos = _find_open_brace(text, after_eq)
        if brace_pos is not None:
            block = _extract_brace_block(text, brace_pos)
            if block is None:
                pos = after_eq
                continue
            pos = brace_pos + len(block)
            if index_prefix and not index_name.startswith(index_prefix):
                continue
            inner = block[1:-1]  # strip outer { }
            # Expand any inner macro calls (e.g. ALCREMIE_MISC_INFO inside a block)
            if macros:
                inner = _expand_macro(inner, macros)
            fields = _parse_fields_from_block(inner)
            results[index_name] = fields
        elif macros:
            # No brace found — try to parse a macro call
            expanded, call_end = _try_expand_entry_macro(text, after_eq, macros)
            if expanded is not None:
                pos = call_end
                if index_prefix and not index_name.startswith(index_prefix):
                    continue
                # The expanded text should be a { ... } block
                bp = _find_open_brace(expanded, 0)
                if bp is not None:
                    block = _extract_brace_block(expanded, bp)
                    if block:
                        inner = block[1:-1]
                        # Expand nested macros in the inner block
                        inner = _expand_macro(inner, macros)
                        fields = _parse_fields_from_block(inner)
                        results[index_name] = fields
                        continue
                pos = call_end
            else:
                pos = after_eq
        else:
            pos = after_eq
            continue
    return results


def _try_expand_entry_macro(text, start, macros):
    """Try to parse and expand a macro call at position start in text.

    Handles both function-like macros (NAME(args)) and object-like macros
    (bare NAME that expands to a { ... } block).

    Returns (expanded_text, end_position) or (None, start).
    """
    # Skip whitespace
    i = start
    while i < len(text) and text[i] in " \t\n\r":
        i += 1
    if i >= len(text):
        return None, start

    # Match the macro name
    name_match = re.match(r"(\w+)", text[i:])
    if not name_match:
        return None, start
    macro_name = name_match.group(1)
    if macro_name not in macros:
        return None, start

    macro_def = macros[macro_name]

    if isinstance(macro_def, tuple):
        # Function-like macro: need (args)
        after_name = i + len(macro_name)
        # Skip whitespace to find '('
        j = after_name
        while j < len(text) and text[j] in " \t":
            j += 1
        if j >= len(text) or text[j] != "(":
            return None, start
        paren_text = _extract_paren_args(text, j)
        if paren_text is None:
            return None, start
        call_end = j + len(paren_text)
        # Skip trailing comma/whitespace
        while call_end < len(text) and text[call_end] in " \t\n\r,":
            call_end += 1
        full_call = macro_name + paren_text
        expanded = _expand_macro(full_call, macros)
        return expanded, call_end
    else:
        # Object-like macro: bare name, value is the expansion text
        call_end = i + len(macro_name)
        # Skip trailing comma/whitespace
        while call_end < len(text) and text[call_end] in " \t\n\r,":
            call_end += 1
        expanded = macro_def
        return expanded, call_end


def _find_open_brace(text, start, skip_commas=False):
    """Find the next '{' in text starting at start, skipping whitespace/newlines.

    If skip_commas is True, also skip commas (used between elements in arrays).
    """
    i = start
    length = len(text)
    while i < length:
        ch = text[i]
        if ch == '{':
            return i
        if ch in ' \t\n\r':
            i += 1
            continue
        if skip_commas and ch == ',':
            i += 1
            continue
        # Non-whitespace, non-brace: not a struct entry
        return None
    return None


def parse_struct_entry(filepath, index_name):
    """Parse a single [INDEX_NAME] = { ... } block from a C source file.

    Returns dict of field_name -> raw_value_string, or None if not found.
    Uses parse_struct_entries() internally (benefits from cache).
    """
    entries = parse_struct_entries(filepath)
    return entries.get(index_name)


def parse_unnamed_struct_array(filepath, array_name):
    """Parse an array of unnamed structs (no [INDEX] keys).

    Handles patterns like:
        static const struct T name[] = { { .f = V }, { .f = V } };

    Args:
        array_name: The variable name (e.g., "gTrainerParty_Sawyer1").

    Returns:
        list[dict] of field dicts in order. On error returns [].
    """
    if not filepath or not os.path.exists(filepath):
        return []
    key = _cache_key(filepath, "unnamed_struct_array", array_name)
    if key in _CACHE:
        return _CACHE[key]

    text = _read_and_clean(filepath)
    if text is None:
        _CACHE[key] = []
        return []

    results = _scan_unnamed_array(text, array_name)
    _CACHE[key] = results
    return results


def _scan_unnamed_array(text, array_name):
    """Find array_name[] = { ... } and parse each unnamed struct element."""
    # Match: ... array_name[] = {  (with optional qualifiers before)
    pattern = re.compile(
        re.escape(array_name) + r'\s*\[\s*\]\s*=\s*'
    )
    m = pattern.search(text)
    if not m:
        return []
    brace_pos = _find_open_brace(text, m.end())
    if brace_pos is None:
        return []
    outer_block = _extract_brace_block(text, brace_pos)
    if outer_block is None:
        return []
    # Now find each { ... } element inside the outer block
    inner = outer_block[1:-1]
    results = []
    pos = 0
    while pos < len(inner):
        bp = _find_open_brace(inner, pos, skip_commas=True)
        if bp is None:
            break
        element = _extract_brace_block(inner, bp)
        if element is None:
            break
        pos = bp + len(element)
        element_inner = element[1:-1]
        fields = _parse_fields_from_block(element_inner)
        results.append(fields)
    return results


def extract_field_value(raw_value, unwrap_macro=None):
    """Post-process a raw field value string.

    Args:
        raw_value: The raw string from parse_struct_entries().
        unwrap_macro: If provided, unwrap MACRO(content) -> content.
            E.g., unwrap_macro="_" unwraps _("SAWYER") -> "SAWYER".
            E.g., unwrap_macro="PERCENT_FEMALE" unwraps
            PERCENT_FEMALE(12.5) -> "12.5".

    Returns:
        Processed value string. Brace lists without unwrap_macro are
        returned as-is (stripped). With no special processing, returns
        the value stripped of whitespace.
    """
    val = raw_value.strip()
    if unwrap_macro:
        prefix = unwrap_macro + '('
        if val.startswith(prefix) and val.endswith(')'):
            inner = val[len(prefix):-1].strip()
            # If inner is a quoted string, remove the quotes
            if len(inner) >= 2 and inner[0] == '"' and inner[-1] == '"':
                return inner[1:-1]
            return inner
    return val


# ---------------------------------------------------------------------------
# Convenience loaders — resolve path and delegate through cache
# ---------------------------------------------------------------------------

def load_flags(game_path):
    """Return [(name, comment), ...] for FLAG_ constants."""
    return parse_defines(os.path.join(game_path, HEADER_FLAGS), "FLAG_")


def load_vars(game_path):
    """Return [(name, comment), ...] for VAR_ constants."""
    return parse_defines(os.path.join(game_path, HEADER_VARS), "VAR_")


def load_trainers(game_path):
    """Return [(name, comment), ...] for TRAINER_ constants."""
    return parse_defines(os.path.join(game_path, HEADER_TRAINERS), "TRAINER_")


def load_songs(game_path, prefix):
    """Return [(name, comment), ...] for SE_ or MUS_ constants from songs.h."""
    return parse_defines(os.path.join(game_path, HEADER_SONGS), prefix)


def load_sound(game_path, prefix="FANFARE_"):
    """Return [(name, comment), ...] for FANFARE_ constants from sound.h."""
    return parse_defines(os.path.join(game_path, HEADER_SOUND), prefix)


def load_species(game_path):
    """Return [(name, comment), ...] for SPECIES_ constants."""
    return parse_defines(os.path.join(game_path, HEADER_SPECIES), "SPECIES_")


def load_species_unique(game_path):
    """Return [(name, comment), ...] for real SPECIES_ constants only.

    Filters out alias defines whose value resolves to another SPECIES_*
    constant (e.g. SPECIES_ALCREMIE -> SPECIES_ALCREMIE_STRAWBERRY).
    Only includes defines with numeric values (the real species IDs).
    Also filters meta-constants like SPECIES_NONE, SPECIES_EGG, SPECIES_NUM.
    """
    header = os.path.join(game_path, HEADER_SPECIES)
    try:
        key = (os.path.realpath(header), "species_unique")
    except OSError:
        key = (header, "species_unique")
    if key in _CACHE:
        return _CACHE[key]

    raw = parse_defines_full(header, "SPECIES_")
    skip = {"SPECIES_NONE", "SPECIES_EGG", "SPECIES_NUM", "SPECIES_COUNT"}
    result = []
    for name, value, comment in raw:
        if name in skip:
            continue
        # Skip aliases: value starts with SPECIES_
        if value.startswith("SPECIES_"):
            continue
        # Skip non-numeric meta-defines (GEN*_START, FORMS_START, etc.)
        stripped = value.lstrip("(").rstrip(")")
        if not stripped.isdigit():
            continue
        result.append((name, comment))

    result.sort(key=lambda x: x[0])
    _CACHE[key] = result
    return result


def load_specials(game_path):
    """Return sorted list of special function names from data/specials.inc."""
    return parse_specials(os.path.join(game_path, HEADER_SPECIALS))


def load_items(game_path):
    """Return [(name, comment), ...] for ITEM_ constants.

    Filters out internal constants (ITEM_NONE, ITEM_USE_*, ITEM_FIELD_ARROW,
    ITEMS_COUNT) and alias lines whose value references another ITEM_ constant.
    """
    raw = parse_defines_full(os.path.join(game_path, HEADER_ITEMS), "ITEM_")
    skip_prefixes = ("ITEM_NONE", "ITEM_USE_", "ITEM_FIELD_ARROW")
    filtered = []
    for name, value, comment in raw:
        if name == "ITEMS_COUNT":
            continue
        if any(name.startswith(p) for p in skip_prefixes):
            continue
        # Skip alias lines whose value references another ITEM_ constant
        if "ITEM_" in value:
            continue
        filtered.append((name, comment))
    return filtered


def load_ai_flags(game_path):
    """Load AI flag constants from battle_ai.h.

    Returns [(flag_suffix, description), ...] — e.g., ('CHECK_BAD_MOVE', 'desc')
    Strips the 'AI_FLAG_' prefix from names.
    Filters out system-internal flags (ROAMING, SAFARI, FIRST_BATTLE, DYNAMIC_FUNC).
    Composite presets (e.g., BASIC_TRAINER) are included from a separate parse pass.
    """
    header = os.path.join(game_path, HEADER_BATTLE_AI)
    try:
        key = (os.path.realpath(header), "ai_flags_loaded")
    except OSError:
        key = (header, "ai_flags_loaded")
    if key in _CACHE:
        return _CACHE[key]

    # System flags to exclude (by substring in suffix)
    _SYSTEM_FRAGMENTS = ("ROAMING", "SAFARI", "FIRST_BATTLE", "DYNAMIC_FUNC")

    # Pass 1: individual flags via parse_defines (handles single-token values)
    raw = parse_defines(header, "AI_FLAG_")
    prefix = "AI_FLAG_"
    flags = []
    for name, comment in raw:
        suffix = name[len(prefix):]
        if any(frag in suffix for frag in _SYSTEM_FRAGMENTS):
            continue
        flags.append((suffix, comment))

    # Pass 2: composite presets — parse_defines misses multi-token values
    # like (AI_FLAG_X | AI_FLAG_Y), so scan separately
    _composite_re = re.compile(
        r"^#define\s+(AI_FLAG_\w+)\s+\(AI_FLAG_\w+(?:\s*\|\s*AI_FLAG_\w+)+\)"
        r"(?:\s+//\s*(.*))?$"
    )
    try:
        with open(header, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _composite_re.match(line.rstrip())
                if m:
                    name = m.group(1)
                    suffix = name[len(prefix):]
                    # Skip if already captured or is a system flag
                    if any(s == suffix for s, _ in flags):
                        continue
                    if any(frag in suffix for frag in _SYSTEM_FRAGMENTS):
                        continue
                    comment = (m.group(2) or "").strip()
                    if not comment:
                        comment = "Preset: composite AI combination"
                    flags.append((suffix, comment))
    except OSError:
        pass

    flags.sort(key=lambda x: x[0])
    _CACHE[key] = flags
    return flags


def load_arbitrary_set(header_path, prefix):
    """Return a set of constant names for any header + prefix combo.

    Used by modules that need headers not covered by the named loaders
    (e.g. moves.h, items.h, abilities.h, battle_ai.h).
    """
    return parse_defines_set(header_path, prefix)


# ---------------------------------------------------------------------------
# Trainer ID loaders — unified replacements for per-module parsers
# ---------------------------------------------------------------------------

# Meta-defines to exclude from trainer ID results
_TRAINER_META_DEFINES = frozenset({
    "TRAINERS_COUNT", "MAX_TRAINERS_COUNT", "TRAINER_PARTNER", "TRAINER_NONE",
})

_TRAINER_ID_RE = re.compile(r"^#define\s+(TRAINER_\w+)\s+(\d+)")


def load_trainer_ids(game_path):
    """Parse opponents.h and return a dict mapping trainer constants to IDs.

    Returns dict[str, int] — e.g., {"TRAINER_SAWYER_1": 854, ...}.
    Filters out meta-defines (TRAINERS_COUNT, MAX_TRAINERS_COUNT, etc.)
    and macro-style defines like TRAINER_PARTNER(x).
    On error returns {}.
    """
    header = os.path.join(game_path, HEADER_TRAINERS)
    if not header or not os.path.exists(header):
        return {}
    try:
        key = (os.path.realpath(header), "trainer_ids")
    except OSError:
        key = (header, "trainer_ids")
    if key in _CACHE:
        return _CACHE[key]

    results = {}
    try:
        with open(header, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _TRAINER_ID_RE.match(line)
                if not m:
                    continue
                name = m.group(1)
                if name in _TRAINER_META_DEFINES:
                    continue
                results[name] = int(m.group(2))
    except OSError:
        pass
    _CACHE[key] = results
    return results


def load_trainer_ids_custom(game_path, threshold=854):
    """Return only custom trainers (ID > threshold).

    Returns dict[str, int] — subset of load_trainer_ids() where ID > threshold.
    Default threshold 854 is the last vanilla trainer in unmodified
    pokeemerald-expansion.
    """
    all_ids = load_trainer_ids(game_path)
    return {name: tid for name, tid in all_ids.items() if tid > threshold}


def load_trainer_metadata(game_path):
    """Parse TRAINERS_COUNT and MAX_TRAINERS_COUNT from opponents.h.

    Returns (trainers_count, max_trainers) as ints, or (0, 0) on error.
    """
    header = os.path.join(game_path, HEADER_TRAINERS)
    if not header or not os.path.exists(header):
        return (0, 0)
    try:
        key = (os.path.realpath(header), "trainer_metadata")
    except OSError:
        key = (header, "trainer_metadata")
    if key in _CACHE:
        return _CACHE[key]

    trainers_count = 0
    max_trainers = 0
    count_re = re.compile(r"^#define\s+TRAINERS_COUNT\s+(\d+)")
    max_re = re.compile(r"^#define\s+MAX_TRAINERS_COUNT\s+(\d+)")
    try:
        with open(header, encoding="utf-8", errors="replace") as f:
            for line in f:
                mc = count_re.match(line)
                if mc:
                    trainers_count = int(mc.group(1))
                    continue
                mm = max_re.match(line)
                if mm:
                    max_trainers = int(mm.group(1))
    except OSError:
        pass
    result = (trainers_count, max_trainers)
    _CACHE[key] = result
    return result


def classify_trainers(game_path, threshold=854):
    """Partition all trainers into vanilla and custom sets.

    Returns (vanilla, custom) where each is dict[str, int].

    Uses a comment-marker approach first: if opponents.h contains a line
    matching ``// Custom`` (case-insensitive), everything defined after that
    marker is custom.  Falls back to the numeric threshold (ID <= 854) for
    projects without a marker.
    """
    all_ids = load_trainer_ids(game_path)

    # --- Try comment-marker detection first ---
    opponents_path = os.path.join(game_path, HEADER_TRAINERS)
    try:
        with open(opponents_path, encoding="utf-8", errors="replace") as f:
            text = f.read()

        marker = re.search(r"^//\s*Custom\b", text, re.MULTILINE | re.IGNORECASE)
        if marker:
            after_ids = set(re.findall(
                r"#define\s+(TRAINER_\w+)", text[marker.start():]
            ))
            # Remove meta-defines that might appear after marker
            after_ids -= _TRAINER_META_DEFINES
            vanilla = {}
            custom = {}
            for name, tid in all_ids.items():
                if name in after_ids:
                    custom[name] = tid
                else:
                    vanilla[name] = tid
            return (vanilla, custom)
    except OSError:
        pass

    # --- Fallback: threshold-based (for projects without marker) ---
    vanilla = {name: tid for name, tid in all_ids.items() if tid <= threshold}
    custom = {name: tid for name, tid in all_ids.items() if tid > threshold}
    return (vanilla, custom)


# ---------------------------------------------------------------------------
# Species data loader — base stats + types from gen_N_families.h
# ---------------------------------------------------------------------------

_STAT_FIELDS = ("baseHP", "baseAttack", "baseDefense",
                "baseSpAttack", "baseSpDefense", "baseSpeed")
_STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")

_EV_YIELD_FIELDS = ("evYield_HP", "evYield_Attack", "evYield_Defense",
                     "evYield_SpAttack", "evYield_SpDefense", "evYield_Speed")
_EV_YIELD_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")

_MON_TYPES_RE = re.compile(r"MON_TYPES\(([^)]+)\)")
_MON_EGG_GROUPS_RE = re.compile(r"MON_EGG_GROUPS\(([^)]+)\)")
_EVOLUTION_RE = re.compile(r"EVOLUTION\((.+)\)", re.DOTALL)
_COMPOUND_STRING_RE = re.compile(r"COMPOUND_STRING\((.+)\)", re.DOTALL)
_LEVEL_UP_MOVE_RE = re.compile(r"LEVEL_UP_MOVE\(\s*(\d+)\s*,\s*(\w+)\s*\)")
_DEFINE_RE = re.compile(r"^\s*#define\s+(\w+)\s+(.+)$", re.MULTILINE)

# Match a function-like #define:  #define NAME(params)  body  (with \ continuations)
_FUNC_MACRO_RE = re.compile(
    r"^\s*#define\s+(\w+)\(([^)]*)\)\s*(.*?)(?:\n|$)",
    re.MULTILINE,
)


def _collect_file_macros(filepath):
    """Collect #define macros from a C source file.

    Returns dict mapping macro name -> value string.

    For simple object-like macros: name -> raw value.
    For function-like macros: name -> (params_list, body_string).
    Multi-line macros (backslash continuations) are joined.
    """
    macros = {}
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return macros

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.lstrip()
        if not stripped.startswith("#define"):
            i += 1
            continue

        # Join backslash-continuation lines
        full_line = line
        while full_line.endswith("\\") and i + 1 < len(lines):
            i += 1
            full_line = full_line[:-1] + " " + lines[i].rstrip()
        i += 1

        # Strip inline // comments (outside strings)
        cleaned = _strip_line_comment(full_line)

        # Try function-like macro: #define NAME(params) body
        fm = re.match(r"\s*#define\s+(\w+)\(([^)]*)\)\s*(.*)", cleaned)
        if fm:
            name = fm.group(1)
            params = [p.strip() for p in fm.group(2).split(",") if p.strip()]
            body = fm.group(3).strip()
            macros[name] = (params, body)
            continue

        # Simple object-like macro: #define NAME value
        sm = re.match(r"\s*#define\s+(\w+)\s+(.*)", cleaned)
        if sm:
            name = sm.group(1)
            value = sm.group(2).strip()
            if value:
                macros[name] = value

    return macros


def _strip_line_comment(line):
    """Strip trailing // comments from a line, respecting strings."""
    in_string = False
    for i, ch in enumerate(line):
        if in_string:
            if ch == "\\" and i + 1 < len(line):
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return line[:i].rstrip()
    return line


def _expand_macro(text, macros, depth=0):
    """Expand macro calls in text using collected macro definitions.

    Handles:
    - Function-like macros: NAME(arg1, arg2) with parameter substitution
    - Token pasting: ## operator concatenates adjacent tokens
    - Nested macro calls (up to depth 10)
    - Inner macro calls within expanded text (recursive expansion)

    Returns expanded text string.
    """
    if depth > 10:
        return text

    # Find function-like macro calls: NAME(args)
    # Must match known macro names to avoid false positives
    func_names = [n for n, v in macros.items() if isinstance(v, tuple)]
    if not func_names:
        return text

    # Build a regex that matches any known function-macro call
    # Sort by length descending to prefer longer matches
    func_names.sort(key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(n) for n in func_names) + r")\s*\("
    )

    result = text
    changed = True
    iterations = 0
    while changed and iterations < 20:
        changed = False
        iterations += 1
        m = pattern.search(result)
        if not m:
            break
        macro_name = m.group(1)
        params, body = macros[macro_name]
        # Extract arguments — find matching closing paren
        args_start = m.end()
        args_text = _extract_paren_args(result, args_start - 1)
        if args_text is None:
            break
        call_end = args_start - 1 + len(args_text) + 1  # past the ')'
        # Parse the comma-separated arguments (respecting nesting)
        inner = args_text[1:-1]  # strip outer ( )
        args = _split_macro_args(inner)

        # Substitute parameters in body
        expanded = _substitute_params(body, params, args)

        # Replace the macro call in result
        result = result[:m.start()] + expanded + result[call_end:]
        changed = True

    return result


def _extract_paren_args(text, paren_pos):
    """Extract balanced parenthesized text starting at paren_pos.

    Returns the substring from '(' through matching ')' inclusive,
    or None if unbalanced.
    """
    if paren_pos >= len(text) or text[paren_pos] != "(":
        return None
    depth = 0
    i = paren_pos
    in_string = False
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[paren_pos:i + 1]
        i += 1
    return None


def _split_macro_args(text):
    """Split comma-separated macro arguments, respecting nested parens/braces."""
    args = []
    depth = 0
    current = []
    in_string = False
    for ch in text:
        if in_string:
            current.append(ch)
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            current.append(ch)
        elif ch in "({":
            depth += 1
            current.append(ch)
        elif ch in ")}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        args.append("".join(current).strip())
    return args


def _substitute_params(body, params, args):
    """Substitute macro parameters with arguments, handling ## token pasting."""
    result = body
    # Build substitution map
    subs = {}
    for i, param in enumerate(params):
        subs[param] = args[i] if i < len(args) else ""

    # Handle ## token pasting first: param##param, param##text, text##param
    # Process ## by finding param names adjacent to ## and substituting+joining
    if "##" in result:
        # Replace ## with a unique placeholder, then substitute params, then remove placeholder
        # This handles: foo##param, param##bar, param1##param2
        for param, arg in subs.items():
            # param ## something -> arg + something (no space)
            result = re.sub(
                r"\b" + re.escape(param) + r"\s*##\s*",
                arg, result
            )
            # something ## param -> something + arg (no space)
            result = re.sub(
                r"\s*##\s*" + re.escape(param) + r"\b",
                arg, result
            )

    # Regular parameter substitution (whole-word only)
    for param, arg in subs.items():
        result = re.sub(r"\b" + re.escape(param) + r"\b", arg, result)

    return result


def _resolve_macro(raw, macros):
    """If raw is a bare macro name, resolve it from the macros dict."""
    val = raw.strip()
    if val in macros:
        return macros[val]
    return val


def _parse_mon_types(raw, macros=None):
    """Extract type names from a MON_TYPES(...) macro value.

    Returns list of title-cased type strings with TYPE_ prefix stripped.
    E.g., "MON_TYPES(TYPE_GRASS, TYPE_POISON)" -> ["Grass", "Poison"].
    Resolves macro references (e.g., RALTS_FAMILY_TYPE2) if macros provided.
    """
    m = _MON_TYPES_RE.search(raw)
    if not m:
        # Fallback: bare macro name like CLEFAIRY_FAMILY_TYPES
        stripped = raw.strip().rstrip(",")
        if macros and stripped in macros:
            expanded = macros[stripped]
            # expanded is C array syntax: "{ TYPE_FAIRY, TYPE_FAIRY }"
            # or a ternary/conditional — extract TYPE_ constants
            type_consts = re.findall(r'\bTYPE_(\w+)', expanded)
            if type_consts:
                seen = []
                for tc in type_consts:
                    name = tc.capitalize() if tc == tc.upper() else tc.title()
                    if name not in seen:
                        seen.append(name)
                return seen
        return []
    inner = m.group(1)
    types = []
    for part in inner.split(","):
        t = part.strip()
        # Resolve macro references (e.g., RALTS_FAMILY_TYPE2)
        if macros and not t.startswith("TYPE_"):
            resolved = macros.get(t, t)
            t = _extract_type_from_expr(resolved)
        if t.startswith("TYPE_"):
            t = t[5:]
        types.append(t.capitalize() if t == t.upper() else t.title())
    return types


def _extract_type_from_expr(expr):
    """Extract the first TYPE_ constant from an expression.

    Handles ternary patterns like '(P_UPDATED_TYPES >= GEN_6 ? TYPE_FAIRY : TYPE_PSYCHIC)'
    by taking the first TYPE_ value (modern/latest).
    """
    m = re.search(r'\bTYPE_\w+', expr)
    return m.group(0) if m else expr


def _parse_base_stat(raw, macros=None):
    """Parse a base stat value string to int.

    Handles plain integers, ternary expressions (takes first integer),
    and macro references (resolved via macros dict).
    """
    val = raw.strip()
    # Plain integer
    try:
        return int(val)
    except ValueError:
        pass
    # Try macro resolution
    if macros and val in macros:
        val = macros[val]
    # Ternary or macro expression — grab the first integer
    m = re.search(r'\b(\d+)\b', val)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return 0


def _parse_abilities(raw, macros=None):
    """Extract ability names from a brace-enclosed list or macro.

    E.g., "{ ABILITY_OVERGROW, ABILITY_NONE, ABILITY_CHLOROPHYLL }"
    -> ["Overgrow", None, "Chlorophyll"]
    """
    val = raw.strip()
    # Resolve macro reference (e.g., EEVEE_ABILITIES)
    if macros and not val.startswith("{"):
        val = macros.get(val, val)
    # Strip outer braces
    val = val.strip()
    if val.startswith("{") and val.endswith("}"):
        val = val[1:-1]
    abilities = []
    for part in val.split(","):
        a = part.strip()
        if not a:
            continue
        if a == "ABILITY_NONE":
            abilities.append(None)
        elif a.startswith("ABILITY_"):
            name = a[8:].replace("_", " ").title()
            abilities.append(name)
        else:
            abilities.append(a)
    return abilities


def _parse_egg_groups(raw):
    """Extract egg group names from MON_EGG_GROUPS(...).

    E.g., "MON_EGG_GROUPS(EGG_GROUP_MONSTER, EGG_GROUP_GRASS)"
    -> ["Monster", "Grass"]
    """
    m = _MON_EGG_GROUPS_RE.search(raw)
    if not m:
        return []
    groups = []
    for part in m.group(1).split(","):
        g = part.strip()
        if g.startswith("EGG_GROUP_"):
            g = g[10:].replace("_", " ").title()
        groups.append(g)
    return groups


def _parse_gender_ratio(raw):
    """Parse genderRatio field to a display string.

    Handles PERCENT_FEMALE(N), MON_MALE, MON_FEMALE, MON_GENDERLESS.
    """
    val = raw.strip()
    if val == "MON_MALE":
        return "Male only"
    if val == "MON_FEMALE":
        return "Female only"
    if val == "MON_GENDERLESS":
        return "Genderless"
    inner = extract_field_value(val, unwrap_macro="PERCENT_FEMALE")
    if inner != val:
        return f"{inner}% female"
    return val


def _parse_growth_rate(raw):
    """Parse growthRate field: strip GROWTH_ prefix, title-case.

    E.g., "GROWTH_MEDIUM_SLOW" -> "Medium Slow"
    """
    val = raw.strip()
    if val.startswith("GROWTH_"):
        val = val[7:]
    return val.replace("_", " ").title()


def _parse_ev_yields(fields):
    """Collect non-zero EV yield fields into a dict."""
    evs = {}
    for c_field, key in zip(_EV_YIELD_FIELDS, _EV_YIELD_KEYS):
        raw = fields.get(c_field)
        if raw is not None:
            try:
                v = int(raw.strip())
            except ValueError:
                v = 0
            if v > 0:
                evs[key] = v
    return evs


def _parse_description(raw):
    """Extract text from COMPOUND_STRING(...) or return None.

    Handles multi-line strings concatenated with C string literal syntax.
    Strips \\n newlines.
    """
    m = _COMPOUND_STRING_RE.search(raw)
    if not m:
        return None
    inner = m.group(1).strip()
    # Concatenated C strings: "line1\n" "line2\n" -> join them
    parts = re.findall(r'"([^"]*)"', inner)
    if not parts:
        return None
    text = "".join(parts)
    # Replace literal \n with space
    text = text.replace("\\n", " ")
    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text).strip()
    return text


def _parse_evolutions(raw):
    """Parse EVOLUTION({method, param, target}, ...) into a list of dicts.

    Returns [{"method": "LEVEL", "param": "16", "target": "SPECIES_IVYSAUR"}, ...]
    Handles entries with nested CONDITIONS({...}) by depth-tracking braces.
    """
    m = _EVOLUTION_RE.search(raw)
    if not m:
        return []
    inner = m.group(1)
    evos = []
    for block in _split_evolution_entries(inner):
        parts = _split_top_level_commas(block)
        if len(parts) < 3:
            continue
        method = parts[0].strip()
        if method.startswith("EVO_"):
            method = method[4:]
        param = parts[1].strip()
        target = parts[2].strip()
        evos.append({"method": method, "param": param, "target": target})
    return evos


def _split_evolution_entries(text):
    """Split EVOLUTION() inner text into individual {method, param, target} entries.

    Respects nested braces for entries containing CONDITIONS({...}).
    """
    entries = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == '{' and depth == 0:
            start = i + 1
            depth = 1
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                entries.append(text[start:i])
                start = None
    return entries


def _split_top_level_commas(text):
    """Split text by commas at depth 0 (ignoring commas inside parens/braces)."""
    parts = []
    depth = 0
    current = []
    for ch in text:
        if ch in '({':
            depth += 1
        elif ch in ')}':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(''.join(current))
            current = []
            continue
        current.append(ch)
    parts.append(''.join(current))
    return parts


def _extract_extended_fields(fields, stats, macros=None):
    """Add extended fields (abilities, evs, name, etc.) to a stats dict."""
    # Abilities
    raw_ab = fields.get("abilities")
    stats["abilities"] = _parse_abilities(raw_ab, macros) if raw_ab else []

    # Catch rate
    raw_cr = fields.get("catchRate")
    stats["catch_rate"] = _parse_base_stat(raw_cr, macros) if raw_cr else 0

    # Egg groups
    raw_eg = fields.get("eggGroups")
    stats["egg_groups"] = _parse_egg_groups(raw_eg) if raw_eg else []

    # Gender ratio
    raw_gr = fields.get("genderRatio")
    stats["gender_ratio"] = _parse_gender_ratio(raw_gr) if raw_gr else None

    # Growth rate
    raw_gw = fields.get("growthRate")
    stats["growth_rate"] = _parse_growth_rate(raw_gw) if raw_gw else None

    # EV yields
    stats["evs"] = _parse_ev_yields(fields)

    # Species name and category
    raw_name = fields.get("speciesName")
    stats["name"] = extract_field_value(raw_name, unwrap_macro="_") if raw_name else None

    raw_cat = fields.get("categoryName")
    stats["category"] = extract_field_value(raw_cat, unwrap_macro="_") if raw_cat else None

    # Height and weight
    raw_h = fields.get("height")
    stats["height"] = _parse_base_stat(raw_h, macros) if raw_h else 0

    raw_w = fields.get("weight")
    stats["weight"] = _parse_base_stat(raw_w, macros) if raw_w else 0

    # Description
    raw_desc = fields.get("description", "")
    stats["description"] = _parse_description(raw_desc)

    # Evolutions
    raw_evo = fields.get("evolutions", "")
    stats["evolutions"] = _parse_evolutions(raw_evo)

    # Form flags
    raw_mega = fields.get("isMegaEvolution", "")
    stats["is_mega"] = raw_mega.strip() == "TRUE"

    raw_gmax = fields.get("isGigantamax", fields.get("isGigantamaxForm", ""))
    stats["is_gmax"] = raw_gmax.strip() == "TRUE"

    # National dex number (raw constant, resolved to int in load_species_data)
    raw_ndex = fields.get("natDexNum", "").strip().rstrip(",")
    stats["nat_dex_num_const"] = raw_ndex if raw_ndex else ""


def _extract_species_from_entries(entries, macros=None):
    """Convert parsed struct entries into species data dicts.

    Returns dict mapping SPECIES_CONSTANT -> stat/type dict.
    """
    result = {}
    for species_const, fields in entries.items():
        if not species_const.startswith("SPECIES_"):
            continue
        stats = {}
        valid = True
        for c_field, key in zip(_STAT_FIELDS, _STAT_KEYS):
            raw = fields.get(c_field)
            if raw is None:
                valid = False
                break
            stats[key] = _parse_base_stat(raw, macros)
        if not valid:
            continue
        stats["bst"] = sum(stats[k] for k in _STAT_KEYS)
        raw_types = fields.get("types", "")
        stats["types"] = _parse_mon_types(raw_types, macros)
        _extract_extended_fields(fields, stats, macros)
        result[species_const] = stats
    return result


def load_national_dex(game_path):
    """Load national dex number mapping from pokedex.h.

    Parses the ``enum NationalDexOrder`` block (sequential C enum starting
    at 0).  Preprocessor guards inside the enum are stripped.

    Returns dict mapping constant name to integer value:
        {"NATIONAL_DEX_NONE": 0, "NATIONAL_DEX_BULBASAUR": 1, ...}

    Results are cached.  Returns {} if pokedex.h is missing.
    """
    header = os.path.join(game_path, HEADER_POKEDEX)
    try:
        key = (os.path.realpath(header), "national_dex")
    except OSError:
        key = (header, "national_dex")
    if key in _CACHE:
        return _CACHE[key]

    result = {}
    try:
        with open(header, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        _CACHE[key] = result
        return result

    # Find the enum block
    m = re.search(r"enum\s+NationalDexOrder\s*\{(.*?)\}", text, re.DOTALL)
    if not m:
        _CACHE[key] = result
        return result

    counter = 0
    entry_re = re.compile(r"^\s*(NATIONAL_DEX_\w+)", re.MULTILINE)
    for line in m.group(1).splitlines():
        stripped = line.strip()
        # Skip preprocessor directives and comments
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        em = entry_re.match(line)
        if em:
            result[em.group(1)] = counter
            counter += 1

    _CACHE[key] = result
    return result


def load_species_data(game_path):
    """Load base stats, types, and extended data for all species.

    Reads gen_N_families.h files from the species_info directory.

    Returns dict mapping SPECIES_CONSTANT -> {
        "hp": int, "atk": int, "def": int, "spa": int, "spd": int,
        "spe": int, "bst": int, "types": [str, ...],
        "abilities": [str|None, ...], "catch_rate": int,
        "egg_groups": [str, ...], "gender_ratio": str|None,
        "growth_rate": str|None, "evs": {key: int, ...},
        "name": str|None, "category": str|None,
        "height": int, "weight": int, "description": str|None,
        "evolutions": [{"method": str, "param": str, "target": str}, ...],
        "is_mega": bool, "is_gmax": bool, "nat_dex_num": int,
    }.

    Results are cached by game_path. Returns {} if the species_info
    directory doesn't exist or no files can be parsed.
    """
    try:
        rp = os.path.realpath(game_path)
    except OSError:
        rp = game_path
    if rp in _SPECIES_DATA_CACHE:
        return _SPECIES_DATA_CACHE[rp]

    species_dir = os.path.join(game_path, "src", "data", "pokemon", "species_info")
    if not os.path.isdir(species_dir):
        _SPECIES_DATA_CACHE[rp] = {}
        return {}

    all_data = {}
    try:
        gen_files = sorted(
            f for f in os.listdir(species_dir)
            if f.startswith("gen_") and f.endswith("_families.h")
        )
    except OSError:
        _SPECIES_DATA_CACHE[rp] = {}
        return {}

    for fname in gen_files:
        fpath = os.path.join(species_dir, fname)
        macros = _collect_file_macros(fpath)
        entries = parse_struct_entries(fpath, "SPECIES_", macros)
        species = _extract_species_from_entries(entries, macros)
        all_data.update(species)

    # Resolve natDexNum constants to integers
    dex_map = load_national_dex(game_path)
    for stats in all_data.values():
        const = stats.pop("nat_dex_num_const", "")
        stats["nat_dex_num"] = dex_map.get(const, 0)

    # Resolve alias mismatches: when species.h has
    # SPECIES_A -> numeric and SPECIES_B -> SPECIES_A (alias),
    # but the struct uses [SPECIES_B] as the index, map SPECIES_A
    # to the same data so both keys work.
    alias_map = _build_species_alias_map(game_path)
    extras = {}
    for alias, target in alias_map.items():
        if alias in all_data and target not in all_data:
            extras[target] = all_data[alias]
        elif target in all_data and alias not in all_data:
            extras[alias] = all_data[target]
    all_data.update(extras)

    _SPECIES_DATA_CACHE[rp] = all_data
    return all_data


def _build_species_alias_map(game_path):
    """Build a map of SPECIES_ alias -> target from species.h.

    An alias is a #define whose value references another SPECIES_* constant.
    Returns dict: {alias_name: target_name}.
    """
    header = os.path.join(game_path, HEADER_SPECIES)
    try:
        key = (os.path.realpath(header), "species_alias_map")
    except OSError:
        key = (header, "species_alias_map")
    if key in _CACHE:
        return _CACHE[key]

    raw = parse_defines_full(header, "SPECIES_")
    alias_map = {}
    for name, value, _comment in raw:
        if value.startswith("SPECIES_"):
            alias_map[name] = value

    _CACHE[key] = alias_map
    return alias_map


def load_form_tables(game_path):
    """Load form species tables from form_species_tables.h.

    Parses each ``s<Name>FormSpeciesIdTable[]`` array and collects
    the SPECIES_* constants it contains (stripping preprocessor guards
    and FORM_SPECIES_END).

    Returns dict mapping **every** species constant in any form group to
    the full ordered list of species in that group.  The first entry in
    each list is the base form.  Example::

        {"SPECIES_CHARIZARD": ["SPECIES_CHARIZARD", "SPECIES_CHARIZARD_MEGA_X", ...],
         "SPECIES_CHARIZARD_MEGA_X": ["SPECIES_CHARIZARD", "SPECIES_CHARIZARD_MEGA_X", ...]}

    Results are cached.  Returns {} if the file is missing.
    """
    fpath = os.path.join(game_path, "src", "data", "pokemon",
                         "form_species_tables.h")
    try:
        key = (os.path.realpath(fpath), "form_tables")
    except OSError:
        key = (fpath, "form_tables")
    if key in _CACHE:
        return _CACHE[key]

    result = {}
    try:
        with open(fpath, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        _CACHE[key] = result
        return result

    # Match each table declaration and its body
    table_re = re.compile(
        r"static\s+const\s+u16\s+s\w+FormSpeciesIdTable\s*\[\s*\]\s*=\s*\{"
    )
    species_re = re.compile(r"\b(SPECIES_\w+)\b")

    for m in table_re.finditer(text):
        # Find closing brace for this array
        start = m.end()
        end = text.find("};", start)
        if end < 0:
            continue
        block = text[start:end]
        # Extract SPECIES_* constants, skipping preprocessor lines
        members = []
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "FORM_SPECIES_END" in stripped:
                continue
            sm = species_re.search(line)
            if sm:
                members.append(sm.group(1))
        # Map every member to the same list
        if members:
            for sp in members:
                result[sp] = members

    _CACHE[key] = result
    return result


def get_species_summary(game_path, species_const):
    """Return a one-line stat summary for a species constant.

    Format: "Grass/Poison  HP:45 Atk:49 Def:49 SpA:65 SpD:65 Spe:45 BST:318"
    Returns None if species not found.
    """
    data = load_species_data(game_path)
    info = data.get(species_const)
    if info is None:
        return None
    type_str = "/".join(info["types"]) if info["types"] else "???"
    return (
        f"{type_str}  "
        f"HP:{info['hp']} Atk:{info['atk']} Def:{info['def']} "
        f"SpA:{info['spa']} SpD:{info['spd']} Spe:{info['spe']} "
        f"BST:{info['bst']}"
    )


# ---------------------------------------------------------------------------
# Learnset loaders
# ---------------------------------------------------------------------------


def _species_to_array_name(species_const):
    """Convert SPECIES_BULBASAUR to Bulbasaur for array name lookup.

    SPECIES_MR_MIME -> MrMime, SPECIES_CHARIZARD_MEGA_X -> CharizardMegaX
    """
    if not species_const.startswith("SPECIES_"):
        return species_const
    name = species_const[8:]  # strip SPECIES_
    return "".join(part.capitalize() for part in name.split("_"))


def _build_learnset_index(game_path, kind):
    """Build an index mapping array names to (filepath, line_offset) for a learnset kind.

    kind is one of: "level_up", "teachable", "egg"
    Returns dict mapping array_name -> filepath.
    """
    key = ("_learnset_index", game_path, kind)
    if key in _LEARNSET_CACHE:
        return _LEARNSET_CACHE[key]

    index = {}
    pokemon_dir = os.path.join(game_path, "src", "data", "pokemon")

    if kind == "level_up":
        learnset_dir = os.path.join(pokemon_dir, "level_up_learnsets")
        if os.path.isdir(learnset_dir):
            _index_learnset_dir(learnset_dir, "LevelUpLearnset", index)
    elif kind == "teachable":
        fpath = os.path.join(pokemon_dir, "teachable_learnsets.h")
        if os.path.isfile(fpath):
            _index_learnset_file(fpath, "TeachableLearnset", index)
    elif kind == "egg":
        fpath = os.path.join(pokemon_dir, "egg_moves.h")
        if os.path.isfile(fpath):
            _index_learnset_file(fpath, "EggMoveLearnset", index)

    _LEARNSET_CACHE[key] = index
    return index


def _index_learnset_dir(dirpath, suffix, index):
    """Scan all gen_N.h files in a directory for array declarations."""
    try:
        files = sorted(f for f in os.listdir(dirpath) if f.endswith(".h"))
    except OSError:
        return
    pattern = re.compile(r"\bs(\w+" + re.escape(suffix) + r")\s*\[\s*\]")
    for fname in files:
        fpath = os.path.join(dirpath, fname)
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for m in pattern.finditer(text):
            array_name = m.group(1)
            index[array_name] = fpath


def _index_learnset_file(filepath, suffix, index):
    """Scan a single file for array declarations."""
    pattern = re.compile(r"\bs(\w+" + re.escape(suffix) + r")\s*\[\s*\]")
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return
    for m in pattern.finditer(text):
        index[m.group(1)] = filepath


def load_level_up_learnset(game_path, species_const):
    """Load level-up learnset for a species.

    Returns [(level, "MOVE_NAME"), ...] sorted by level ascending.
    Returns [] if not found.
    """
    cache_key = ("level_up", game_path, species_const)
    if cache_key in _LEARNSET_CACHE:
        return _LEARNSET_CACHE[cache_key]

    base = _species_to_array_name(species_const)
    array_name = base + "LevelUpLearnset"
    index = _build_learnset_index(game_path, "level_up")
    filepath = index.get(array_name)

    result = []
    if filepath:
        result = _parse_level_up_array(filepath, "s" + array_name)
    _LEARNSET_CACHE[cache_key] = result
    return result


def _parse_level_up_array(filepath, array_name):
    """Parse a level-up learnset array from a file."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    # Find the array
    pattern = re.compile(re.escape(array_name) + r"\s*\[\s*\]\s*=\s*\{")
    m = pattern.search(text)
    if not m:
        return []
    # Extract content until closing brace
    start = m.end()
    end = text.find("};", start)
    if end < 0:
        end = len(text)
    block = text[start:end]
    moves = []
    for lm in _LEVEL_UP_MOVE_RE.finditer(block):
        level = int(lm.group(1))
        move = lm.group(2)
        moves.append((level, move))
    moves.sort(key=lambda x: x[0])
    return moves


def load_teachable_learnset(game_path, species_const):
    """Load teachable (TM/HM/tutor) learnset for a species.

    Returns ["MOVE_NAME", ...] sorted alphabetically.
    Returns [] if not found.
    """
    cache_key = ("teachable", game_path, species_const)
    if cache_key in _LEARNSET_CACHE:
        return _LEARNSET_CACHE[cache_key]

    base = _species_to_array_name(species_const)
    array_name = base + "TeachableLearnset"
    index = _build_learnset_index(game_path, "teachable")
    filepath = index.get(array_name)

    result = []
    if filepath:
        result = _parse_move_list_array(filepath, "s" + array_name)
    _LEARNSET_CACHE[cache_key] = result
    return result


def load_egg_moves(game_path, species_const):
    """Load egg moves for a species.

    Returns ["MOVE_NAME", ...] sorted alphabetically.
    Returns [] if not found.
    """
    cache_key = ("egg", game_path, species_const)
    if cache_key in _LEARNSET_CACHE:
        return _LEARNSET_CACHE[cache_key]

    base = _species_to_array_name(species_const)
    array_name = base + "EggMoveLearnset"
    index = _build_learnset_index(game_path, "egg")
    filepath = index.get(array_name)

    result = []
    if filepath:
        result = _parse_move_list_array(filepath, "s" + array_name)
    _LEARNSET_CACHE[cache_key] = result
    return result


def _parse_move_list_array(filepath, array_name):
    """Parse a simple move list array (teachable or egg moves)."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    pattern = re.compile(re.escape(array_name) + r"\s*\[\s*\]\s*=\s*\{")
    m = pattern.search(text)
    if not m:
        return []
    start = m.end()
    end = text.find("};", start)
    if end < 0:
        end = len(text)
    block = text[start:end]
    moves = []
    for line in block.split("\n"):
        stripped = line.strip().rstrip(",").strip()
        if not stripped or stripped.startswith("//"):
            continue
        if stripped == "MOVE_UNAVAILABLE":
            break
        if stripped.startswith("MOVE_"):
            moves.append(stripped)
    moves.sort()
    return moves


# ---------------------------------------------------------------------------
# Name resolvers
# ---------------------------------------------------------------------------

def load_move_names(game_path):
    """Load move constant -> display name mapping.

    Returns {"MOVE_TACKLE": "Tackle", "MOVE_VINE_WHIP": "Vine Whip", ...}.
    Only includes defines with numeric values (skips aliases).
    """
    header = os.path.join(game_path, HEADER_MOVES)
    try:
        key = (os.path.realpath(header), "move_names")
    except OSError:
        key = (header, "move_names")
    if key in _CACHE:
        return _CACHE[key]

    result = {}
    move_re = re.compile(r"^#define\s+(MOVE_\w+)\s+(\d+)")
    try:
        with open(header, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = move_re.match(line)
                if m:
                    name = m.group(1)
                    display = name[5:].replace("_", " ").title()
                    result[name] = display
    except OSError:
        pass
    _CACHE[key] = result
    return result


def load_move_data(game_path):
    """Parse moves_info.h for rich move data.

    Returns dict keyed by move constant::

        {"MOVE_POUND": {"name": "Pound", "type": "Normal",
                        "category": "Physical", "power": 40,
                        "accuracy": 100, "pp": 35,
                        "description": "Pounds the foe with forelegs or tail."},
         ...}

    Moves whose name cannot be parsed are silently skipped.
    Shared description variables (not inline COMPOUND_STRING) yield an
    empty description rather than crashing.
    """
    filepath = os.path.join(game_path, "src", "data", "moves_info.h")
    try:
        key = (os.path.realpath(filepath), "move_data")
    except OSError:
        key = (filepath, "move_data")
    if key in _CACHE:
        return _CACHE[key]

    result = {}
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        _CACHE[key] = result
        return result

    # ---- locate each [MOVE_XXX] = { ... } block via brace-depth scan ----
    # We find the "[MOVE_" marker, then scan forward tracking brace depth
    # to correctly handle nested braces (.contestComboMoves, .argument, etc.)
    move_start_re = re.compile(r'\[(MOVE_\w+)\]\s*=\s*\{')
    _first_int = re.compile(r'\d+')

    pos = 0
    length = len(content)
    while pos < length:
        m = move_start_re.search(content, pos)
        if not m:
            break
        move_const = m.group(1)
        # Scan from the opening brace to find matching close
        brace_start = m.end() - 1  # points at '{'
        depth = 1
        i = brace_start + 1
        while i < length and depth > 0:
            ch = content[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            i += 1
        block = content[brace_start + 1:i - 1]
        pos = i

        entry = {}

        # .name = COMPOUND_STRING("...")
        name_m = re.search(r'\.name\s*=\s*COMPOUND_STRING\("([^"]+)"\)', block)
        if name_m:
            entry["name"] = name_m.group(1)

        # .description -- inline COMPOUND_STRING (may span multiple quoted strings)
        desc_full = re.search(
            r'\.description\s*=\s*COMPOUND_STRING\(((?:\s*"[^"]*")+)\s*\)',
            block,
        )
        if desc_full:
            parts = re.findall(r'"([^"]*)"', desc_full.group(1))
            raw = " ".join(parts).replace("\\n", " ").replace("\\l", " ")
            entry["description"] = re.sub(r' {2,}', ' ', raw).strip()
        # Shared variable references (sMegaDrainDescription etc.) -> skip

        # Helper: extract an int field that may be a plain literal,
        # a ternary (B_... >= GEN_X ? VAL : VAL), or inside a
        # #if / #else preprocessor block.  We grab the first integer
        # that appears after the `=` on the same logical line (for
        # plain / ternary), or the first integer after `#if` (for
        # preprocessor).  In both ternary and #if cases, the first
        # numeric value corresponds to the "newest gen" branch.
        def _extract_int(field, blk):
            # Try plain: .field = 123
            m2 = re.search(r'\.' + field + r'\s*=\s*(\d+)', blk)
            if m2:
                return int(m2.group(1))
            # Try ternary: .field = MACRO ? 123 : 45
            m2 = re.search(
                r'\.' + field + r'\s*=\s*[^,\n]*\?\s*(\d+)',
                blk,
            )
            if m2:
                return int(m2.group(1))
            # Try preprocessor: #if ... \n .field = 123
            m2 = re.search(
                r'#if[^\n]*\n\s*\.' + field + r'\s*=\s*(\d+)',
                blk,
            )
            if m2:
                return int(m2.group(1))
            return None

        # .power
        val = _extract_int("power", block)
        if val is not None:
            entry["power"] = val

        # .type = TYPE_XXX
        type_m = re.search(r'\.type\s*=\s*TYPE_(\w+)', block)
        if type_m:
            entry["type"] = type_m.group(1).replace("_", " ").title()

        # .accuracy
        val = _extract_int("accuracy", block)
        if val is not None:
            entry["accuracy"] = val

        # .pp
        val = _extract_int("pp", block)
        if val is not None:
            entry["pp"] = val

        # .category = DAMAGE_CATEGORY_XXX
        cat_m = re.search(r'\.category\s*=\s*DAMAGE_CATEGORY_(\w+)', block)
        if cat_m:
            entry["category"] = cat_m.group(1).title()

        if entry.get("name"):
            result[move_const] = entry

    _CACHE[key] = result
    return result


def load_ability_names(game_path):
    """Load ability constant -> display name mapping.

    Parses the enum in abilities.h.
    Returns {"ABILITY_OVERGROW": "Overgrow", ...}.
    """
    header = os.path.join(game_path, HEADER_ABILITIES)
    try:
        key = (os.path.realpath(header), "ability_names")
    except OSError:
        key = (header, "ability_names")
    if key in _CACHE:
        return _CACHE[key]

    result = {}
    # Match enum entries like: ABILITY_STENCH = 1,
    ability_re = re.compile(r"^\s*(ABILITY_\w+)\s*=\s*\d+")
    try:
        with open(header, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = ability_re.match(line)
                if m:
                    name = m.group(1)
                    if name == "ABILITY_NONE":
                        continue
                    display = name[8:].replace("_", " ").title()
                    result[name] = display
    except OSError:
        pass
    _CACHE[key] = result
    return result


def load_ability_descriptions(game_path):
    """Load ability constant -> description mapping.

    Parses the gAbilitiesInfo struct in src/data/abilities.h.
    Returns {"ABILITY_OVERGROW": "Powers up Grass-type moves when ...", ...}.
    """
    fpath = os.path.join(game_path, "src", "data", "abilities.h")
    try:
        key = (os.path.realpath(fpath), "ability_descriptions")
    except OSError:
        key = (fpath, "ability_descriptions")
    if key in _CACHE:
        return _CACHE[key]

    result = {}
    try:
        with open(fpath, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        _CACHE[key] = result
        return result

    # Match each [ABILITY_X] = { ... } block and extract .description
    entry_re = re.compile(
        r"\[(ABILITY_\w+)\]\s*=\s*\{(.*?)\}",
        re.DOTALL,
    )
    desc_re = re.compile(
        r'\.description\s*=\s*COMPOUND_STRING\("(.+?)"\)',
    )
    for m in entry_re.finditer(text):
        ability_const = m.group(1)
        block = m.group(2)
        dm = desc_re.search(block)
        if dm:
            result[ability_const] = dm.group(1)

    _CACHE[key] = result
    return result
