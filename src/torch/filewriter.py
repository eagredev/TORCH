"""Atomic C header file writer utilities.

All functions use tempfile.mkstemp + os.replace for POSIX-atomic writes.
A partial write will never corrupt the target file.  All public functions
return bool (True = success, False = failure) and never raise.
"""
# TORCH_MODULE: File Writer
# TORCH_GROUP: Core
import os
import re
import tempfile

FILEWRITER_VERSION = "1.0"


def _write_atomic(filepath, lines):
    """Write *lines* (list of str) to *filepath* atomically.

    Creates a temp file in the same directory, writes all lines, then
    calls os.replace() to do an atomic rename.  Returns True on success.
    """
    dirpath = os.path.dirname(os.path.abspath(filepath))
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dirpath)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(tmp_path, filepath)
            return True
        except Exception:
            # Clean up the temp file if something went wrong
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False
    except Exception:
        return False


def replace_block(filepath, start_pattern, end_pattern, new_content,
                  create_if_missing=False):
    """Replace a region between two regex-matched lines (inclusive) with new_content.

    *start_pattern* and *end_pattern* are compiled or string regexes matched
    against each line.  The replacement includes the start and end lines
    themselves (they are replaced with new_content).

    If the region is not found and create_if_missing is True, new_content is
    appended to the file.

    Returns True on success, False on failure.
    """
    if not os.path.exists(filepath):
        if create_if_missing:
            return _write_atomic(filepath, [new_content])
        return False

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    start_re = re.compile(start_pattern) if isinstance(start_pattern, str) else start_pattern
    end_re   = re.compile(end_pattern)   if isinstance(end_pattern, str)   else end_pattern

    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if start_idx is None and start_re.search(line):
            start_idx = i
        elif start_idx is not None and end_re.search(line):
            end_idx = i
            break

    if start_idx is None or end_idx is None:
        if create_if_missing:
            new_lines = lines + [new_content]
            return _write_atomic(filepath, new_lines)
        return False

    new_lines = lines[:start_idx] + [new_content] + lines[end_idx + 1:]
    return _write_atomic(filepath, new_lines)


def patch_define(filepath, const_name, new_value):
    """Find '#define CONST_NAME <value>' and replace the value only.

    Preserves any trailing // comment.  Returns True on success.
    """
    if not os.path.exists(filepath):
        return False
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    pattern = re.compile(
        r"^(#define\s+" + re.escape(const_name) + r"\s+)(\S+)(.*)"
    )
    new_lines = []
    patched = False
    for line in lines:
        m = pattern.match(line.rstrip("\n"))
        if m and not patched:
            new_line = m.group(1) + str(new_value) + m.group(3) + "\n"
            new_lines.append(new_line)
            patched = True
        else:
            new_lines.append(line)

    if not patched:
        return False
    return _write_atomic(filepath, new_lines)


def append_define(filepath, const_name, value, comment=None):
    """Append a '#define CONST_NAME value' line to *filepath*.

    If *comment* is provided, appends '  // comment' after the value.
    Returns True on success.
    """
    if comment:
        line = f"#define {const_name} {value}  // {comment}\n"
    else:
        line = f"#define {const_name} {value}\n"

    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line)
        return True
    except OSError:
        return False


def insert_after_marker(filepath, marker_pattern, new_lines):
    """Insert *new_lines* (list of str) after the first line matching *marker_pattern*.

    Returns True on success.
    """
    if not os.path.exists(filepath):
        return False
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return False

    marker_re = re.compile(marker_pattern) if isinstance(marker_pattern, str) else marker_pattern
    insert_at = None
    for i, line in enumerate(lines):
        if marker_re.search(line):
            insert_at = i + 1
            break

    if insert_at is None:
        return False

    result = lines[:insert_at] + new_lines + lines[insert_at:]
    return _write_atomic(filepath, result)


def _skip_string(text, i, length):
    """Skip past a string literal starting at the opening quote. Returns index after closing quote."""
    i += 1  # skip opening quote
    while i < length and text[i] != '"':
        if text[i] == '\\':
            i += 1  # skip escaped char
        i += 1
    return i + 1  # skip closing quote


def _skip_line_comment(text, i, length):
    """Skip a // comment to end of line. Returns index at the newline (or end)."""
    while i < length and text[i] != '\n':
        i += 1
    return i


def _skip_block_comment(text, i, length):
    """Skip a /* ... */ comment. i should point at '/'. Returns index after closing '/'."""
    i += 2  # skip /*
    while i + 1 < length and not (text[i] == '*' and text[i + 1] == '/'):
        i += 1
    return i + 2  # skip past */


def _extract_struct_block(text, start_pos):
    """Find the { ... } block starting at or after start_pos.

    Scans forward from start_pos to find the opening '{', then tracks
    brace depth while skipping string literals and comments.

    Returns (block_start, block_end) — character positions of '{' and '}'
    inclusive, or (None, None) if not found.
    """
    i = start_pos
    length = len(text)
    # Find opening brace
    while i < length and text[i] != '{':
        i += 1
    if i >= length:
        return None, None
    block_start = i
    depth = 1
    i += 1
    while i < length and depth > 0:
        ch = text[i]
        if ch == '"':
            i = _skip_string(text, i, length)
            continue
        elif ch == '/' and i + 1 < length and text[i + 1] == '/':
            i = _skip_line_comment(text, i, length)
            continue
        elif ch == '/' and i + 1 < length and text[i + 1] == '*':
            i = _skip_block_comment(text, i, length)
            continue
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return block_start, i
        i += 1
    return None, None


def _find_field_value_span(block_text, field_name):
    """Find the start and end positions of a field's value within a struct block.

    Returns (val_start, val_end) character positions within block_text,
    or (None, None) if the field is not found.

    val_start: first character of the value (after '= ')
    val_end: one past the last character of the value (before trailing comma/comment/whitespace)
    """
    pattern = re.compile(r"\." + re.escape(field_name) + r"\s*=\s*")
    m = pattern.search(block_text)
    if not m:
        return None, None
    val_start = m.end()
    return _scan_value_end(block_text, val_start)


def _is_value_terminator(ch, text, i, val_start, length):
    """Check if character at position i terminates a field value at depth 0."""
    if ch == ',' or ch == '\n':
        return True
    if ch == '/' and i + 1 < length and text[i + 1] == '/':
        return True
    if ch == '}' and i > val_start:
        return True
    return False


def _scan_value_end(block_text, val_start):
    """Scan from val_start to find where the value ends.

    Tracks brace {} and paren () depth. Stops at ',' or '//' or newline
    or '}' at depth 0. Skips string literals. Returns (val_start, val_end)
    where val_end points to one past the last non-whitespace character of
    the value.
    """
    i = val_start
    length = len(block_text)
    depth = 0
    while i < length:
        ch = block_text[i]
        if ch == '"':
            i = _skip_string(block_text, i, length)
            continue
        if depth == 0 and _is_value_terminator(ch, block_text, i, val_start, length):
            break
        if ch in ('{', '('):
            depth += 1
        elif ch in ('}', ')'):
            depth -= 1
        i += 1
    # Trim trailing whitespace from value
    val_end = i
    while val_end > val_start and block_text[val_end - 1] in (' ', '\t', '\n', '\r'):
        val_end -= 1
    return val_start, val_end


def patch_struct_field(filepath, struct_name, field_name, new_value):
    """Patch a single field inside a named struct entry.

    Finds the [struct_name] = { ... } block in the file, locates
    .field_name = <value>, and replaces just the value portion with
    new_value.  Preserves all comments, formatting, and trailing commas.

    Returns True on success, False on failure.  Never raises.
    """
    if not os.path.exists(filepath):
        return False
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return False

    # Find the struct entry: [STRUCT_NAME] = ...
    entry_pat = re.compile(r"\[" + re.escape(struct_name) + r"\]\s*=\s*")
    entry_m = entry_pat.search(text)
    if not entry_m:
        return False

    # Extract the { ... } block
    block_start, block_end = _extract_struct_block(text, entry_m.end())
    if block_start is None:
        return False

    block_text = text[block_start:block_end + 1]

    # Find the field value within the block
    val_start, val_end = _find_field_value_span(block_text, field_name)
    if val_start is None:
        return False

    # Convert block-relative positions to file-absolute positions
    abs_val_start = block_start + val_start
    abs_val_end = block_start + val_end

    # Splice the new value into the original text
    new_text = text[:abs_val_start] + new_value + text[abs_val_end:]

    return _write_atomic(filepath, [new_text])
