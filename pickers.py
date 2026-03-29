"""Search-and-pick wizards for game constants (flags, vars, trainers, etc.)."""
# TORCH_MODULE: Constant Pickers
# TORCH_GROUP: Script Studio
import os
import re

from torch.gamedata import (
    load_flags, load_vars, load_trainers, load_songs, load_sound,
    load_species, load_species_unique, load_specials, load_items,
    load_form_tables, parse_defines, parse_specials,
    get_species_summary, clear_gamedata_cache, HEADER_FLAGS,
)
from torch.colours import GOLD, WHITE, CYAN, DIM, RST, GREEN


# ============================================================
# CORE SEARCH-PICK UI
# ============================================================
_MAX_RESULTS = 20


# ── Helper: normalise items ──────────────────────────────────────────────

def _normalise_items(items):
    """Normalise items to (name, comment) tuples."""
    normed = []
    for item in items:
        if isinstance(item, str):
            normed.append((item, ""))
        else:
            normed.append((item[0], item[1] if len(item) > 1 else ""))
    return normed


# ── Helper: filter ────────────────────────────────────────────────────────

def _filter_items(normed, query):
    """Filter (name, comment) tuples by case-insensitive substring match."""
    q = query.lower()
    return [(n, c) for n, c in normed if q in n.lower() or q in c.lower()]


# ── Helper: display matches ──────────────────────────────────────────────

def _display_matches(matches, show_comment, prefix_strip=""):
    """Print up to _MAX_RESULTS matches with numbered indices.

    Returns the truncated 'showing' list.
    """
    showing = matches[:_MAX_RESULTS]
    overflow = len(matches) - len(showing)
    print()
    for i, (name, comment) in enumerate(showing, 1):
        display_name = name
        if prefix_strip and display_name.startswith(prefix_strip):
            display_name = display_name[len(prefix_strip):]
        if show_comment and comment:
            print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{name}{RST}  {DIM}{comment}{RST}")
        else:
            print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{name}{RST}")
    if overflow > 0:
        print(f"    {DIM}... and {overflow} more. Refine your search.{RST}")
    print()
    return showing


# ── Helper: try pick by number ────────────────────────────────────────────

def _try_pick(showing, raw):
    """Try to parse raw input as a 1-based index into showing.

    Returns (selected_name, True) on valid pick, (None, False) if not a number.
    """
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(showing):
            return showing[idx][0], True
        print(f"  {DIM}Pick a number from 1-{len(showing)}.{RST}")
        return None, True  # was a number, but out of range
    except ValueError:
        return None, False


# ── Helper: detail callback dispatch ─────────────────────────────────────

def _handle_detail(pick, detail_callback, showing):
    """Dispatch detail callback for ``d`` or ``d<N>`` input.

    Returns True if a detail view was shown, False otherwise.
    """
    if not detail_callback or not showing:
        return False
    key = pick.lower()
    if key == "d":
        detail_callback(showing[0][0])
        return True
    if key.startswith("d") and len(key) > 1 and key[1:].isdigit():
        idx = int(key[1:]) - 1
        if 0 <= idx < len(showing):
            detail_callback(showing[idx][0])
            return True
    return False


# ── Core search-pick loop ─────────────────────────────────────────────────

def _search_pick(items, prompt_label, show_comment=True, prefix_strip="",
                 detail_callback=None):
    """Interactive search-filter-pick loop.

    *items* is a list of (name, comment) tuples (or plain strings).
    *detail_callback* — if provided, called with the item name when user
    presses ``d`` on a displayed result list.  Shows detail then returns
    to the picker.
    Returns the selected constant string, or None on cancel.
    """
    normed = _normalise_items(items)

    if not normed:
        print(f"  {DIM}(no {prompt_label} constants found — is the game path correct?){RST}")
        print(f"  {DIM}You can type a value manually, or 'q' to cancel.{RST}")
        raw = input(f"  {prompt_label} > ").strip()
        if raw.lower() == "q" or not raw:
            return None
        return raw

    print(f"  {DIM}{len(normed)} {prompt_label} constants available. Search to narrow down.{RST}")

    query = None
    while True:
        # Get search term if we don't already have one from a previous pick
        if query is None:
            print()
            query = input(f"  {GOLD}Search {prompt_label}{RST} (or 'q' to cancel) > ").strip()
        if query.lower() == "q":
            return None
        if not query:
            print(f"  {DIM}Enter a search term to filter results.{RST}")
            query = None
            continue

        matches = _filter_items(normed, query)
        if not matches:
            print(f"  {DIM}No matches for '{query}'. Try a different term.{RST}")
            query = None
            continue

        showing = _display_matches(matches, show_comment, prefix_strip)
        detail_hint = f", {GOLD}d{RST} detail" if detail_callback else ""
        pick = input(f"  {GOLD}#{RST} to select{detail_hint}, or new search > ").strip()
        if pick.lower() == "q":
            return None

        # Detail view: d or d<N>
        if _handle_detail(pick, detail_callback, showing):
            showing = _display_matches(matches, show_comment, prefix_strip)
            continue

        selected, was_number = _try_pick(showing, pick)
        if selected:
            return selected
        # If it was a number (but out of range), re-prompt; otherwise use as new query
        query = None if was_number else pick


# ── Helper: gather labels ─────────────────────────────────────────────────

def _gather_labels(script_data, map_name=None, project_dir=None):
    """Collect labels from script beats and sibling .txt files.

    Returns list[str] of unique label names in discovery order.
    """
    labels = []

    for beat in script_data.get("beats", []):
        if beat["type"] == "label":
            name = beat["data"].get("name", "")
            if name and name not in labels:
                labels.append(name)

    if not (map_name and project_dir):
        return labels
    map_dir = os.path.join(project_dir, map_name)
    if not os.path.isdir(map_dir):
        return labels

    for fname in sorted(os.listdir(map_dir)):
        if not fname.endswith(".txt"):
            continue
        fpath = os.path.join(map_dir, fname)
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("label "):
                        lbl = line[6:].strip()
                        if lbl and lbl not in labels:
                            labels.append(lbl)
        except OSError:
            continue

    return labels


# ── Label picker (interactive) ────────────────────────────────────────────

def _pick_label(script_data, map_name=None, project_dir=None):
    """Pick a label from the current script or sibling scripts.

    Shows a numbered list of known labels. Falls back to free-text input.
    Returns label string or None.
    """
    labels = _gather_labels(script_data, map_name, project_dir)

    if not labels:
        return input("  Target label > ").strip() or None

    print()
    print(f"  {DIM}Known labels:{RST}")
    for i, lbl in enumerate(labels, 1):
        print(f"    {GOLD}[{i}]{RST} {WHITE}{lbl}{RST}")
    print(f"    {GOLD}[t]{RST} {DIM}Type label manually{RST}")
    print()
    pick = input(f"  Label > ").strip()
    if pick.lower() == "q":
        return None
    if pick.lower() == "t":
        return input("  Label name > ").strip() or None
    try:
        idx = int(pick) - 1
        if 0 <= idx < len(labels):
            return labels[idx]
    except ValueError:
        pass
    if pick:
        return pick
    return None


# ============================================================
# FLAG DEFINITION — create new custom flags inline
# ============================================================

def _find_next_unused_flag(lines):
    """Find the next available FLAG_UNUSED_0xXXX in the pool.

    Scans *lines* (list of str) for FLAG_UNUSED_0xXXX definitions and
    checks which ones are already aliased by custom defines.

    Returns the FLAG_UNUSED_* name, or None if pool exhausted.
    """
    # Collect all FLAG_UNUSED_0xXXX defines (the pool)
    # Match lines like: #define FLAG_UNUSED_0x020    0x20 // Unused Flag
    # Exclude DAILY/SPECIAL/TESTING flags that happen to contain UNUSED
    unused_pool = []
    for line in lines:
        m = re.match(r'^#define\s+(FLAG_UNUSED_0x[0-9A-Fa-f]+)\s+', line)
        if m:
            unused_pool.append(m.group(1))

    # Collect all aliases (right-hand side references to FLAG_UNUSED_*)
    # Match lines like: #define FLAG_BEAT_BUSTER_1  FLAG_UNUSED_0x024
    used = set()
    for line in lines:
        m = re.match(r'^#define\s+FLAG_\w+\s+(FLAG_UNUSED_0x[0-9A-Fa-f]+)', line)
        if m:
            used.add(m.group(1))

    for name in unused_pool:
        if name not in used:
            return name
    return None


def _validate_flag_name(name, lines):
    """Validate a proposed flag name.

    Returns (ok, message).
    - Must start with FLAG_
    - Must be UPPER_SNAKE_CASE (A-Z, 0-9, underscore only after FLAG_)
    - Must not already exist in flags.h
    """
    if not name:
        return False, "Flag name cannot be empty."
    if not name.startswith("FLAG_"):
        return False, "Flag name must start with FLAG_."
    if len(name) <= 5:
        return False, "Flag name must have characters after FLAG_."
    suffix = name[5:]
    if not re.match(r'^[A-Z][A-Z0-9_]*$', suffix):
        return False, "Flag name must be UPPER_SNAKE_CASE (A-Z, 0-9, underscores)."
    # Check it doesn't already exist
    define_pat = re.compile(r'^#define\s+' + re.escape(name) + r'\s')
    for line in lines:
        if define_pat.match(line):
            return False, f"{name} already exists in flags.h."
    return True, ""


def _find_insert_point(lines):
    """Find the line index where a new custom flag define should go.

    Looks for a '// Custom' comment section and returns the line after
    the last #define in that section.  Falls back to the line before
    the final #endif.  Returns None if neither is found.
    """
    custom_start = None
    for i, line in enumerate(lines):
        if "custom" in line.lower() and "//" in line:
            custom_start = i
            break

    if custom_start is not None:
        last_define = custom_start
        for i in range(custom_start + 1, len(lines)):
            stripped = lines[i].strip()
            if stripped.startswith("#define FLAG_"):
                last_define = i
            elif stripped and not stripped.startswith("//") and not stripped.startswith("#define"):
                break
        return last_define + 1

    # Fallback: before the final #endif
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("#endif"):
            return i
    return None


def _detect_alignment(lines, insert_idx):
    """Detect the value-column alignment from nearby custom defines.

    Returns the column offset where the FLAG_UNUSED_* value starts.
    """
    align_col = 42  # default
    scan_start = max(0, insert_idx - 5)
    for i in range(scan_start, insert_idx):
        m = re.match(r'^(#define\s+FLAG_\w+\s+)', lines[i])
        if m and 'FLAG_UNUSED_0x' in lines[i][m.end():m.end() + 20]:
            align_col = len(m.group(1))
    return align_col


def _insert_flag_define(flags_h_path, flag_name, unused_flag):
    """Insert '#define FLAG_NAME  FLAG_UNUSED_0xXXX' into flags.h.

    Inserts at the end of the custom flags section (detected by a
    '// Custom' comment), or before #endif if no custom section exists.
    Returns True on success.
    """
    with open(flags_h_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    insert_idx = _find_insert_point(lines)
    if insert_idx is None:
        return False

    align_col = _detect_alignment(lines, insert_idx)
    prefix = f"#define {flag_name}"
    padding = max(1, align_col - len(prefix))
    new_line = f"{prefix}{' ' * padding}{unused_flag}\n"

    lines.insert(insert_idx, new_line)

    with open(flags_h_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return True


def define_new_flag(game_path, flag_name=None):
    """Define a new custom flag in flags.h.

    If *flag_name* is None, prompts the user interactively.
    Returns the flag name on success, or None on failure/cancel.
    Clears the gamedata cache so subsequent picks see the new flag.
    """
    flags_h = os.path.join(game_path, HEADER_FLAGS)
    if not os.path.isfile(flags_h):
        print(f"  {DIM}flags.h not found at {flags_h}{RST}")
        return None

    with open(flags_h, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # Find next available slot
    unused = _find_next_unused_flag(lines)
    if unused is None:
        print(f"  {DIM}No unused flag slots remaining in flags.h.{RST}")
        return None

    # Get flag name
    if flag_name is None:
        print()
        print(f"  {DIM}Next available slot: {unused}{RST}")
        raw = input(f"  {GOLD}Flag name{RST} (e.g. FLAG_BEAT_GYM_1) > ").strip()
        if not raw or raw.lower() == "q":
            return None
        # Auto-prepend FLAG_ if missing
        if not raw.startswith("FLAG_"):
            raw = "FLAG_" + raw
        flag_name = raw.upper()

    # Validate
    ok, msg = _validate_flag_name(flag_name, lines)
    if not ok:
        print(f"  {DIM}{msg}{RST}")
        return None

    # Insert
    if not _insert_flag_define(flags_h, flag_name, unused):
        print(f"  {DIM}Failed to insert flag define.{RST}")
        return None

    # Clear cache so pick_flag sees the new flag
    clear_gamedata_cache()

    print(f"  {GREEN}Created:{RST} {WHITE}{flag_name}{RST} -> {unused}")
    return flag_name


# ============================================================
# CONVENIENCE WRAPPERS — one per data type
# ============================================================

def pick_flag(game_path, flag_log=None):
    """Flag picker — searches include/constants/flags.h.

    If *flag_log* is provided (dict {flag: script_name}), annotates results
    with the script each flag is used in.

    Offers [+] to define a new flag inline before searching.
    """
    if not game_path:
        return input("  Flag constant > ").strip() or None

    # Offer flag creation shortcut
    print()
    print(f"    {GOLD}[+]{RST} Define new flag    {GOLD}[Enter]{RST} Search existing")
    choice = input(f"  > ").strip()
    if choice == "+":
        result = define_new_flag(game_path)
        if result:
            return result
        # If creation failed/cancelled, fall through to search

    items = load_flags(game_path)
    if flag_log:
        annotated = []
        for name, comment in _normalise_items(items):
            scene = flag_log.get(name)
            if scene:
                comment = f"(used by: {scene})" if not comment else f"{comment}  (used by: {scene})"
            annotated.append((name, comment))
        return _search_pick(annotated, "Flag")
    return _search_pick(items, "Flag")


def pick_var(game_path):
    """Var picker — searches include/constants/vars.h."""
    if not game_path:
        return input("  Variable name > ").strip() or None
    return _search_pick(load_vars(game_path), "Var")


def pick_trainer(game_path):
    """Trainer picker — searches include/constants/opponents.h."""
    if not game_path:
        return input("  Trainer constant > ").strip() or None
    return _search_pick(load_trainers(game_path), "Trainer", show_comment=False)


def pick_sound(game_path):
    """Sound effect picker — searches include/constants/songs.h for SE_ constants."""
    if not game_path:
        return input("  Sound constant > ").strip() or None
    return _search_pick(load_songs(game_path, "SE_"), "Sound")


def pick_music(game_path):
    """Music picker — searches include/constants/songs.h for MUS_ constants."""
    if not game_path:
        return input("  Music constant > ").strip() or None
    return _search_pick(load_songs(game_path, "MUS_"), "Music")


def pick_fanfare(game_path):
    """Fanfare picker — searches include/constants/sound.h for FANFARE_ constants."""
    if not game_path:
        return input("  Fanfare constant > ").strip() or None
    return _search_pick(load_sound(game_path, "FANFARE_"), "Fanfare")


def _form_group_prefix(group):
    """Find the common underscore-delimited prefix across a form group.

    Given ['SPECIES_ALCREMIE_STRAWBERRY_VANILLA_CREAM', 'SPECIES_ALCREMIE_BERRY_...']
    returns 'ALCREMIE'.  For ['SPECIES_CHARIZARD', 'SPECIES_CHARIZARD_MEGA_X']
    returns 'CHARIZARD'.
    """
    stems = [c[8:] if c.startswith("SPECIES_") else c for c in group]
    prefix = stems[0]
    for s in stems[1:]:
        while prefix and not s.startswith(prefix):
            idx = prefix.rfind("_")
            prefix = prefix[:idx] if idx >= 0 else ""
    return prefix


def _form_label(const, prefix):
    """Extract a human-readable form suffix from a SPECIES_ constant.

    *prefix* is the common stem (e.g. 'ALCREMIE' or 'CHARIZARD') computed
    by _form_group_prefix().
    Returns "" for the base form (when const stem equals prefix exactly).
    """
    stem = const[8:] if const.startswith("SPECIES_") else const
    if stem == prefix:
        return ""
    if prefix and stem.startswith(prefix + "_"):
        suffix = stem[len(prefix) + 1:]
        return suffix.replace("_", " ").title()
    # Fallback — show full stem
    return stem.replace("_", " ").title()


def _group_search_results(matches, form_tables):
    """Collapse form group members into grouped entries.

    Returns list of tuples:
      (display_name, comment, const_or_None, form_consts_or_None)

    Single species: const is set, form_consts is None.
    Form group:     const is None, form_consts is the list of members.
    """
    seen_groups = set()  # track form group base consts we've already added
    result = []
    for name, comment in matches:
        group = form_tables.get(name)
        if group and len(group) > 1:
            base = group[0]
            if base in seen_groups:
                continue
            seen_groups.add(base)
            # Count how many group members appear in the match list
            match_names = {n for n, _ in matches}
            in_results = sum(1 for g in group if g in match_names)
            result.append((base, comment, None, group, in_results))
        else:
            result.append((name, comment, name, None, 0))
    return result


def _display_species_matches(grouped, show_comment):
    """Display grouped species results. Returns the showing list (truncated)."""
    showing = grouped[:_MAX_RESULTS]
    overflow = len(grouped) - len(showing)
    print()
    for i, entry in enumerate(showing, 1):
        name = entry[0]
        comment = entry[1]
        is_group = entry[3] is not None
        if is_group:
            group = entry[3]
            count = len(group)
            prefix = _form_group_prefix(group)
            display_name = prefix.replace("_", " ").title()
            print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{display_name}{RST}  "
                  f"{CYAN}({count} forms — f{i} to browse){RST}")
            if show_comment and comment:
                print(f"         {DIM}{name}  {comment}{RST}")
            else:
                print(f"         {DIM}{name}{RST}")
        else:
            if show_comment and comment:
                print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{name}{RST}  {DIM}{comment}{RST}")
            else:
                print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{name}{RST}")
    if overflow > 0:
        print(f"    {DIM}... and {overflow} more. Refine your search.{RST}")
    print()
    return showing


def _pick_from_form_group(group, game_path):
    """Two-level drill-down into a form group. Returns selected constant or None."""
    prefix = _form_group_prefix(group)
    display_name = prefix.replace("_", " ").title()

    print()
    print(f"  {WHITE}{display_name}{RST} — {len(group)} forms")
    print(f"  {DIM}Search within forms, # to pick, or q to go back.{RST}")

    form_items = []
    for const in group:
        label = _form_label(const, prefix)
        display_label = label if label else "(Base Form)"
        summary = get_species_summary(game_path, const)
        form_items.append((const, display_label, summary or ""))

    query = None
    while True:
        if query is None:
            print()
            query = input(f"  {GOLD}Search form{RST} (Enter=show all, q=back) > ").strip()
        if query.lower() == "q":
            return None

        if query:
            q = query.lower()
            filtered = [(c, l, s) for c, l, s in form_items
                        if q in c.lower() or q in l.lower()]
        else:
            filtered = form_items

        if not filtered:
            print(f"  {DIM}No forms match '{query}'.{RST}")
            query = None
            continue

        showing = filtered[:_MAX_RESULTS]
        overflow = len(filtered) - len(showing)
        print()
        for i, (const, label, summary) in enumerate(showing, 1):
            if summary:
                print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{label}{RST}  {DIM}{summary}{RST}")
            else:
                print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{label}{RST}")
            print(f"         {DIM}{const}{RST}")
        if overflow > 0:
            print(f"    {DIM}... and {overflow} more. Refine your search.{RST}")
        print()

        pick = input(f"  {GOLD}#{RST} to select, or new search > ").strip()
        if pick.lower() == "q":
            return None
        try:
            idx = int(pick) - 1
            if 0 <= idx < len(showing):
                selected = showing[idx][0]
                label = showing[idx][1]
                print(f"  Selected: {WHITE}{label}{RST} ({selected})")
                return selected
            print(f"  {DIM}Pick a number from 1-{len(showing)}.{RST}")
            continue
        except ValueError:
            query = pick


def pick_species(game_path=None):
    """Species picker with form-group awareness.

    Filters alias defines, collapses multi-form species (Alcremie, Silvally,
    Unown, etc.) into browsable groups. Press f<N> to drill into a form group.
    Press d<N> for a full dex card.
    """
    if not game_path:
        return input("  Species constant > ").strip() or None

    species_list = load_species_unique(game_path)
    form_tables = load_form_tables(game_path)

    # Enrich with stat summaries
    enriched = []
    for name, comment in species_list:
        summary = get_species_summary(game_path, name)
        enriched.append((name, summary or comment))
    has_summaries = any(c for _, c in enriched)

    # Detail callback for dex cards
    def _show_card(item_name):
        try:
            from torch.dex import show_species_card
            show_species_card(item_name, game_path)
        except ImportError:
            pass

    normed = _normalise_items(enriched)
    if not normed:
        print(f"  {DIM}(no Species constants found — is the game path correct?){RST}")
        raw = input(f"  Species > ").strip()
        return raw if raw and raw.lower() != "q" else None

    print(f"  {DIM}{len(normed)} species available (aliases filtered). Search to narrow down.{RST}")

    query = None
    while True:
        if query is None:
            print()
            query = input(f"  {GOLD}Search Species{RST} (or 'q' to cancel) > ").strip()
        if query.lower() == "q":
            return None
        if not query:
            print(f"  {DIM}Enter a search term to filter results.{RST}")
            query = None
            continue

        matches = _filter_items(normed, query)
        if not matches:
            print(f"  {DIM}No matches for '{query}'. Try a different term.{RST}")
            query = None
            continue

        grouped = _group_search_results(matches, form_tables)
        showing = _display_species_matches(grouped, has_summaries)

        detail_hint = f", {GOLD}d{RST}N detail"
        form_hint = f", {GOLD}f{RST}N forms"
        has_groups = any(e[3] is not None for e in showing)
        hints = f"{GOLD}#{RST} to select{detail_hint}"
        if has_groups:
            hints += form_hint
        pick = input(f"  {hints}, or new search > ").strip()

        if pick.lower() == "q":
            return None

        # Form drill-down: f or f<N>
        if pick.lower().startswith("f") and len(pick) > 1 and pick[1:].isdigit():
            idx = int(pick[1:]) - 1
            if 0 <= idx < len(showing) and showing[idx][3] is not None:
                result = _pick_from_form_group(showing[idx][3], game_path)
                if result:
                    return result
                # Returned None = user backed out, re-show results
                showing = _display_species_matches(grouped, has_summaries)
                continue
            elif 0 <= idx < len(showing):
                print(f"  {DIM}That entry has no forms to browse.{RST}")
                continue

        # Detail view: d or d<N>
        if pick.lower().startswith("d"):
            key = pick.lower()
            if key == "d" and showing:
                target = showing[0][0]
                _show_card(target)
                showing = _display_species_matches(grouped, has_summaries)
                continue
            if len(key) > 1 and key[1:].isdigit():
                idx = int(key[1:]) - 1
                if 0 <= idx < len(showing):
                    target = showing[idx][0]
                    _show_card(target)
                    showing = _display_species_matches(grouped, has_summaries)
                    continue

        # Numeric pick
        try:
            idx = int(pick) - 1
            if 0 <= idx < len(showing):
                entry = showing[idx]
                if entry[3] is not None:
                    # It's a form group — drill in automatically
                    result = _pick_from_form_group(entry[3], game_path)
                    if result:
                        return result
                    showing = _display_species_matches(grouped, has_summaries)
                    continue
                else:
                    return entry[2]  # the const
            print(f"  {DIM}Pick a number from 1-{len(showing)}.{RST}")
            continue
        except ValueError:
            pass

        # Not a number — use as new search
        query = pick


def pick_special(game_path):
    """Special function picker — searches data/specials.inc."""
    if not game_path:
        return input("  Special function name > ").strip() or None
    items = [(n, "") for n in load_specials(game_path)]
    return _search_pick(items, "Special", show_comment=False)


# ============================================================
# ITEM PICKER
# ============================================================

def pick_item(game_path):
    """Item picker — searches include/constants/items.h."""
    if not game_path:
        return input("  Item constant > ").strip() or None
    return _search_pick(load_items(game_path), "Item")


def pick_item_list(game_path):
    """Repeated item picker — build a list of items.

    Shows current list, [a] add, [d] remove, [c] confirm.
    Returns list of item constant strings, or empty list on cancel.
    """
    items = []
    while True:
        print()
        if items:
            print(f"  {DIM}Current items:{RST}")
            for i, item in enumerate(items, 1):
                print(f"    {GOLD}[{i}]{RST} {WHITE}{item}{RST}")
        else:
            print(f"  {DIM}(no items yet){RST}")
        print()
        print(f"    {GOLD}[a]{RST} add item    ", end="")
        if items:
            print(f"{GOLD}[d]{RST} remove item    ", end="")
        print(f"{GOLD}[c]{RST} confirm    {GOLD}[q]{RST} cancel")
        print()
        choice = input("  > ").strip().lower()
        if choice == "q":
            return []
        if choice == "c":
            return items
        if choice == "a":
            item = pick_item(game_path)
            if item:
                items.append(item)
        elif choice == "d" and items:
            raw = input(f"  Remove # (1-{len(items)}) > ").strip()
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(items):
                    removed = items.pop(idx)
                    print(f"  Removed: {removed}")
            except ValueError:
                pass


# ============================================================
# NPC PICKER
# ============================================================

def pick_map_npc(game_path, map_name):
    """Pick an NPC from a map's object_events.

    Shows a numbered list of NPCs on the map with coordinates, trainer
    status, and script info.  Returns the selected NPC dict (from
    get_map_objects), or None if cancelled.

    Includes [m] fallback for manual object ID entry.
    """
    from torch.project_files import get_map_objects

    npcs = get_map_objects(game_path, map_name)
    if not npcs:
        print(f"  {DIM}No NPCs found on {map_name}.{RST}")
        return None

    print()
    print(f"  {DIM}NPCs on {map_name}:{RST}")
    print()
    for i, npc in enumerate(npcs, 1):
        parts = [f"at ({npc['x']},{npc['y']})"]
        if npc["trainer_type"] != "TRAINER_TYPE_NONE":
            parts.append("trainer")
        if npc["script"]:
            parts.append(f"script: {npc['script']}")
        else:
            parts.append("no script")
        detail = " \u2014 ".join(parts)
        print(f"    {GOLD}[{i:>2}]{RST} {WHITE}{npc['display_name']}{RST}  {DIM}{detail}{RST}")

    print(f"    {GOLD}[ m]{RST} {DIM}Enter object ID manually{RST}")
    print()
    pick = input(f"  {GOLD}#{RST} to select, or {GOLD}q{RST} to cancel > ").strip()

    if not pick or pick.lower() == "q":
        return None

    if pick.lower() == "m":
        raw = input("  Object ID > ").strip()
        if not raw:
            return None
        try:
            manual_id = int(raw)
        except ValueError:
            print(f"  {DIM}Invalid number.{RST}")
            return None
        # Return a minimal dict for manual entry
        return {
            "object_id": manual_id,
            "graphics_id": "",
            "display_name": f"Object {manual_id}",
            "x": 0, "y": 0,
            "script": "Common_EventScript_NopReturn",
            "trainer_type": "TRAINER_TYPE_NONE",
            "flag": "",
        }

    try:
        idx = int(pick) - 1
        if 0 <= idx < len(npcs):
            selected = npcs[idx]
            print(f"  Selected: {WHITE}{selected['display_name']}{RST} (object {selected['object_id']})")
            return selected
        print(f"  {DIM}Pick a number from 1-{len(npcs)}.{RST}")
    except ValueError:
        print(f"  {DIM}Invalid selection.{RST}")

    return None


# ---------------------------------------------------------------------------
# Backward-compat re-exports (other modules that imported these directly)
# ---------------------------------------------------------------------------
_parse_defines_with_comments = parse_defines
_parse_specials = parse_specials
