"""ROM metadata - Makefile field parsing and editing.

Reads and writes ROM header fields (game title, game code, maker code)
from the project Makefile. Provides ``read_rom_fields()`` and
``write_rom_field()`` consumed by the Settings module, web API, and
upgrade system.
"""
# TORCH_MODULE: ROM Studio
# TORCH_GROUP: Tools
import os
import re
import shutil

from torch.ui import print_logo, _set_terminal_title, _offer_build, _k, clear_screen
from torch.config import DIVIDER, _nav_keys
from torch.colours import GOLD, WHITE, CYAN, DIM, RST, BAR

# Try to import config_tuner for redirect
try:
    from torch.config_tuner import config_command as _config_command
    _HAS_TUNER = True
except ImportError:
    _HAS_TUNER = False


def _read_makefile_var(makefile_path, name):
    """Read a variable assignment from the Makefile: NAME        := VALUE"""
    if not os.path.exists(makefile_path):
        return None
    with open(makefile_path) as f:
        for line in f:
            m = re.match(r"^" + re.escape(name) + r"\s*[:?]?=\s*(.+)", line)
            if m:
                return m.group(1).strip()
    return None


def _read_rom_filename(makefile_path):
    """Read the ROM output filename from the Makefile.

    Tries ROM_NAME first; if it contains unresolvable Make variable
    references (e.g. ``$(FILE_NAME).gba``), resolves them by reading
    BUILD_NAME and FILE_NAME from the same Makefile.
    Returns '?' if resolution fails.
    """
    rom_name = _read_makefile_var(makefile_path, "ROM_NAME")
    if rom_name and "$(" not in rom_name:
        return rom_name
    file_name = _read_makefile_var(makefile_path, "FILE_NAME")
    if file_name and "$(" not in file_name:
        return file_name + ".gba"
    # Both ROM_NAME and FILE_NAME contain variable refs — resolve the chain
    build_name = _read_makefile_var(makefile_path, "BUILD_NAME")
    if build_name and "$(" not in build_name:
        # Resolve FILE_NAME first (e.g. "poke$(BUILD_NAME)" -> "pokeemerald")
        if file_name:
            file_name = file_name.replace("$(BUILD_NAME)", build_name)
        # Resolve ROM_NAME using the resolved FILE_NAME
        if rom_name and file_name and "$(" not in file_name:
            resolved = rom_name.replace("$(FILE_NAME)", file_name)
            resolved = resolved.replace("$(BUILD_NAME)", build_name)
            if "$(" not in resolved:
                return resolved
        # FILE_NAME resolved but ROM_NAME missing or still unresolvable
        if file_name and "$(" not in file_name:
            return file_name + ".gba"
    return "?"


def _write_makefile_var(makefile_path, name, new_value):
    """Replace a variable assignment line in the Makefile."""
    if not os.path.exists(makefile_path):
        return False
    with open(makefile_path) as f:
        content = f.read()
    new_content = re.sub(
        r"^(" + re.escape(name) + r"\s*[:?]?=\s*).*",
        lambda m: m.group(1) + new_value,
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if new_content == content:
        return False
    shutil.copy2(makefile_path, makefile_path + ".bak")
    with open(makefile_path, "w") as f:
        f.write(new_content)
    return True


def _set_rom_filename(makefile_path, gba_name):
    """Set the ROM output filename while preserving the release-suffix chain.

    Instead of hardcoding ROM_NAME (which breaks ``make release`` producing
    a separate ``-release.gba``), this writes FILE_NAME and ensures ROM_NAME
    uses the ``$(FILE_NAME).gba`` variable reference.

    Args:
        makefile_path: Path to the project Makefile.
        gba_name: Desired filename, e.g. ``pokeseihoku.gba``.

    Returns True on success.
    """
    base = gba_name.removesuffix(".gba") if gba_name.endswith(".gba") else gba_name
    ok = _write_makefile_var(makefile_path, "FILE_NAME", base)
    if not ok:
        return False
    # Ensure ROM_NAME uses the variable chain, not a hardcoded literal
    rom_name = _read_makefile_var(makefile_path, "ROM_NAME")
    if rom_name and "$(" not in rom_name:
        # Currently hardcoded — restore the chain
        _write_makefile_var(makefile_path, "ROM_NAME", "$(FILE_NAME).gba")
    return True


def _retire_old_rom(game_path, old_name, new_name):
    """Move the old ROM file to a legacy_roms folder after a rename + build.

    Only called after a successful build, so the new ROM is guaranteed to exist.
    """
    if old_name == new_name:
        return
    old_path = os.path.join(game_path, old_name)
    if not os.path.isfile(old_path):
        return
    legacy_dir = os.path.join(game_path, "legacy_roms")
    os.makedirs(legacy_dir, exist_ok=True)
    dest = os.path.join(legacy_dir, old_name)
    # Avoid overwriting a previous legacy ROM with the same name
    if os.path.exists(dest):
        base, ext = os.path.splitext(old_name)
        n = 1
        while os.path.exists(dest):
            dest = os.path.join(legacy_dir, f"{base}_{n}{ext}")
            n += 1
    try:
        shutil.move(old_path, dest)
        dest_display = dest.replace(os.path.expanduser("~"), "~")
        print(f"  Old ROM moved to: {dest_display}")
    except OSError as e:
        print(f"  WARNING: Could not move old ROM: {e}")


def _read_game_name(rom_header_path):
    """Read .gameName = "..." from rom_header_gf.c"""
    if not os.path.exists(rom_header_path):
        return None
    with open(rom_header_path) as f:
        for line in f:
            m = re.search(r'\.gameName\s*=\s*"([^"]*)"', line)
            if m:
                return m.group(1)
    return None


def _write_game_name(rom_header_path, new_name):
    """Update .gameName = "..." in rom_header_gf.c"""
    if not os.path.exists(rom_header_path):
        return False
    with open(rom_header_path) as f:
        content = f.read()
    new_content = re.sub(
        r'(\.gameName\s*=\s*")[^"]*(")',
        lambda m: m.group(1) + new_name + m.group(2),
        content,
        count=1,
    )
    if new_content == content:
        return False
    shutil.copy2(rom_header_path, rom_header_path + ".bak")
    with open(rom_header_path, "w") as f:
        f.write(new_content)
    return True


def _read_project_info(game_path, project_dir):
    """Gather ROM metadata + workspace stats for the main menu display."""
    makefile_path = os.path.join(game_path, "Makefile")
    rom_header_path = os.path.join(game_path, "src", "rom_header_gf.c")
    info = {
        "title": _read_makefile_var(makefile_path, "TITLE") or "?",
        "game_code": _read_makefile_var(makefile_path, "GAME_CODE") or "?",
        "revision": _read_makefile_var(makefile_path, "REVISION") or "?",
        "rom_name": _read_rom_filename(makefile_path),
        "game_path_display": game_path.replace(os.path.expanduser("~"), "~"),
    }
    # Count maps and scripts in workspace
    map_count = 0
    script_count = 0
    skip_dirs = {"backups", "config", "output", "_unassigned"}
    if os.path.isdir(project_dir):
        for entry in os.listdir(project_dir):
            entry_path = os.path.join(project_dir, entry)
            if not os.path.isdir(entry_path) or entry in skip_dirs:
                continue
            map_count += 1
            for fname in os.listdir(entry_path):
                if fname.endswith(".txt") or fname.endswith(".pory"):
                    script_count += 1
    info["map_count"] = map_count
    info["script_count"] = script_count
    # Registry enrolled count
    try:
        from torch.registry import get_enrolled_maps
        info["enrolled_count"] = len(get_enrolled_maps(project_dir))
    except Exception:
        info["enrolled_count"] = 0
    return info


# ---------------------------------------------------------------------------
# Public API — consumed by config_tuner (Settings module)
# ---------------------------------------------------------------------------

# Field definitions: (key, label, max_len, validator_type, source)
# source: "makefile" or "header"
_ROM_FIELDS = [
    ("TITLE",         "ROM Title",     12,   "title",     "makefile"),
    ("GAME_CODE",     "Game Code",      4,   "game_code", "makefile"),
    ("MAKER_CODE",    "Maker Code",     2,   "maker_code","makefile"),
    ("REVISION",      "Revision",     None,  "revision",  "makefile"),
    ("ROM_FILENAME",  "ROM Filename", None,  "filename",  "makefile"),
    ("INTERNAL_NAME", "Internal Name",  31,  "internal",  "header"),
]


def read_rom_fields(game_path, project_dir=None):
    """Read all ROM metadata fields and return a list of dicts.

    Each dict has: key, label, value, max_len, validator.
    """
    makefile_path = os.path.join(game_path, "Makefile")
    rom_header_path = os.path.join(game_path, "src", "rom_header_gf.c")

    fields = []
    for key, label, max_len, validator, source in _ROM_FIELDS:
        if source == "header":
            value = _read_game_name(rom_header_path) or "?"
        elif key == "ROM_FILENAME":
            value = _read_rom_filename(makefile_path)
        else:
            value = _read_makefile_var(makefile_path, key) or "?"
        fields.append({
            "key": key,
            "label": label,
            "value": value,
            "max_len": max_len,
            "validator": validator,
        })
    return fields


def _validate_title(value, max_len):
    if len(value) > max_len:
        return False, f"Max {max_len} chars (got {len(value)})."
    if not re.match(r'^[A-Za-z0-9 ]+$', value):
        return False, "Only letters, numbers, and spaces allowed."
    return True, ""


def _validate_game_code(value, max_len):
    v = value.upper()
    if len(v) != max_len:
        return False, f"Must be exactly {max_len} characters (got {len(v)})."
    if not v.isascii() or not v.isalnum():
        return False, "Must be ASCII alphanumeric only."
    return True, ""


def _validate_maker_code(value, max_len):
    if len(value) != max_len:
        return False, f"Must be exactly {max_len} characters (got {len(value)})."
    return True, ""


def _validate_revision(value, _max_len):
    try:
        n = int(value)
    except ValueError:
        return False, "Must be an integer."
    if n < 0 or n > 255:
        return False, "Must be 0-255."
    return True, ""


def _validate_filename(value, _max_len):
    if not value.endswith(".gba"):
        value += ".gba"
    value = os.path.basename(value)
    if not value:
        return False, "Invalid filename."
    return True, ""


def _validate_internal(value, max_len):
    if max_len and len(value) > max_len:
        return False, f"Max {max_len} chars (got {len(value)})."
    if '"' in value or '\\' in value:
        return False, "Cannot contain quote or backslash characters."
    return True, ""


_VALIDATORS = {
    "title": _validate_title,
    "game_code": _validate_game_code,
    "maker_code": _validate_maker_code,
    "revision": _validate_revision,
    "filename": _validate_filename,
    "internal": _validate_internal,
}


def _validate_rom_field(validator, value, max_len):
    """Validate a ROM field value. Returns (ok, message)."""
    if not value:
        return False, "Value cannot be empty."
    fn = _VALIDATORS.get(validator)
    if fn:
        return fn(value, max_len)
    return True, ""


def write_rom_field(game_path, project_dir, field_key, new_value):
    """Validate and write a single ROM field. Returns (success, message)."""
    makefile_path = os.path.join(game_path, "Makefile")
    rom_header_path = os.path.join(game_path, "src", "rom_header_gf.c")

    # Find field definition
    field_def = None
    for key, label, max_len, validator, source in _ROM_FIELDS:
        if key == field_key:
            field_def = (key, label, max_len, validator, source)
            break
    if not field_def:
        return False, f"Unknown field: {field_key}"

    key, label, max_len, validator, source = field_def

    # Special handling: game_code is uppercased
    if validator == "game_code":
        new_value = new_value.upper()

    # Special handling: filename must end in .gba
    if validator == "filename":
        if not new_value.endswith(".gba"):
            new_value += ".gba"
        new_value = os.path.basename(new_value)

    # Validate
    ok, msg = _validate_rom_field(validator, new_value, max_len)
    if not ok:
        return False, msg

    # Write
    if source == "header":
        if _write_game_name(rom_header_path, new_value):
            return True, f"{label} set to '{new_value}'."
        return False, f"Could not update rom_header_gf.c."

    # Makefile fields
    if key == "ROM_FILENAME":
        if _set_rom_filename(makefile_path, new_value):
            return True, f"{label} set to '{new_value}'."
        return False, "Could not update Makefile."

    if _write_makefile_var(makefile_path, key, new_value):
        return True, f"{label} set to '{new_value}'."
    return False, "Could not update Makefile."


def studio_command(game_path, settings=None, proj_name=None):
    """ROM Studio CLI entry — redirects to Settings when available."""
    if settings is None:
        settings = {}
    if _HAS_TUNER:
        # Redirect to the unified Settings module
        _config_command([], None, game_path, None, settings,
                        proj_name=proj_name)
        return
    # Fallback: show old ROM Studio UI if tuner unavailable
    _studio_menu(game_path, settings, proj_name)


def _studio_menu(game_path, settings, proj_name=None):
    """Legacy ROM Studio interactive UI (fallback when tuner unavailable)."""
    NK_SCROLL, NK_UP, NK_DOWN, NK_OPEN = _nav_keys(settings)

    makefile_path = os.path.join(game_path, "Makefile")
    rom_header_path = os.path.join(game_path, "src", "rom_header_gf.c")

    def _field_row(key, label, value, desc):
        return (f"  {_k(key)} {WHITE}{label:<14}{RST} {CYAN}{value}{RST}\n"
                f"      {DIM}{desc}{RST}")

    _set_terminal_title("TORCH \u2014 ROM Studio")
    selected = 0
    FIELD_COUNT = 6

    while True:
        clear_screen()
        title       = _read_makefile_var(makefile_path, "TITLE")        or "?"
        game_code   = _read_makefile_var(makefile_path, "GAME_CODE")    or "?"
        maker_code  = _read_makefile_var(makefile_path, "MAKER_CODE")   or "?"
        revision    = _read_makefile_var(makefile_path, "REVISION")     or "?"
        rom_name    = _read_rom_filename(makefile_path)
        game_name   = _read_game_name(rom_header_path)                  or "?"

        fields = [
            ("ROM Title",     title,     "GBA header, max 12 chars \u2014 shown in emulator title bar"),
            ("Game Code",     game_code, "4-char ROM ID used by save managers, e.g. BPEE"),
            ("Maker Code",    maker_code,"2-char publisher code, usually 01 for Nintendo"),
            ("Revision",      revision,  "ROM version number, usually 0"),
            ("ROM Filename",  rom_name,  "Output .gba filename when you run bb"),
            ("Internal Name", game_name, "Stored in ROM data \u2014 seen by some tools"),
        ]

        print_logo("ROM Studio", proj_name)
        print(BAR)
        print(f"   {WHITE}ROM STUDIO{RST}")
        print(BAR)
        print()
        for i, (label, value, desc) in enumerate(fields):
            cursor = f"{GOLD}>>{RST}" if i == selected else "  "
            label_col = WHITE if i == selected else f"{WHITE}"
            print(f"  {cursor} {_k(i + 1)} {label_col}{label:<14}{RST} {CYAN}{value}{RST}")
            print(f"       {DIM}{desc}{RST}")
            print()
        print(BAR)
        print()
        print(f"  {_k(NK_OPEN)}/{_k('Enter')} {DIM}edit{RST}  "
              f"{_k(NK_UP)} {DIM}up{RST}  {_k(NK_DOWN)} {DIM}down{RST}  "
              f"{_k('#')} {DIM}jump{RST}  {_k('q')} {DIM}back{RST}")
        print()
        choice = input(f"  {GOLD}>{RST} ").strip()

        if not choice:
            # Enter with no input = edit selected field
            choice = str(selected + 1)

        cmd = choice.lower()

        if cmd == "q":
            return

        if cmd in (NK_UP, "k"):
            selected = max(0, selected - 1)
            continue

        if cmd == NK_DOWN:
            selected = min(FIELD_COUNT - 1, selected + 1)
            continue

        if cmd == NK_OPEN:
            choice = str(selected + 1)

        if choice.isdigit() and 1 <= int(choice) <= FIELD_COUNT:
            selected = int(choice) - 1

        if choice == "1":
            print()
            new_val = input(f"  ROM Title (max 12 chars, current: {title!r}) > ").strip()
            if not new_val:
                print("  Cancelled.")
                continue
            if len(new_val) > 12:
                print(f"  '{new_val}' is {len(new_val)} chars — max 12. Try again.")
                continue
            if not re.match(r'^[A-Za-z0-9 ]+$', new_val):
                print("  Title can only contain letters, numbers, and spaces.")
                continue
            if _write_makefile_var(makefile_path, "TITLE", new_val):
                print(f"  ROM Title set to '{new_val}'.")
                _offer_build(game_path)
            else:
                print("  ERROR: Could not update Makefile.")

        elif choice == "2":
            print()
            new_val = input(f"  Game Code (4 chars, current: {game_code!r}) > ").strip().upper()
            if not new_val:
                print("  Cancelled.")
                continue
            if len(new_val) != 4:
                print(f"  Game Code must be exactly 4 characters. Got {len(new_val)}.")
                continue
            if not new_val.isascii() or not new_val.isalnum():
                print("  Game Code must be ASCII alphanumeric only.")
                continue
            if _write_makefile_var(makefile_path, "GAME_CODE", new_val):
                print(f"  Game Code set to '{new_val}'.")
                _offer_build(game_path)
            else:
                print("  ERROR: Could not update Makefile.")

        elif choice == "3":
            print()
            new_val = input(f"  Maker Code (2 chars, current: {maker_code!r}) > ").strip()
            if not new_val:
                print("  Cancelled.")
                continue
            if len(new_val) != 2:
                print(f"  Maker Code must be exactly 2 characters. Got {len(new_val)}.")
                continue
            if _write_makefile_var(makefile_path, "MAKER_CODE", new_val):
                print(f"  Maker Code set to '{new_val}'.")
                _offer_build(game_path)
            else:
                print("  ERROR: Could not update Makefile.")

        elif choice == "4":
            print()
            new_val = input(f"  Revision (current: {revision!r}) > ").strip()
            if not new_val:
                print("  Cancelled.")
                continue
            if _write_makefile_var(makefile_path, "REVISION", new_val):
                print(f"  Revision set to '{new_val}'.")
                _offer_build(game_path)
            else:
                print("  ERROR: Could not update Makefile.")

        elif choice == "5":
            print()
            new_val = input(f"  ROM Filename (current: {rom_name!r}, must end in .gba) > ").strip()
            if not new_val:
                print("  Cancelled.")
                continue
            if not new_val.endswith(".gba"):
                new_val += ".gba"
            new_val = os.path.basename(new_val)
            if _set_rom_filename(makefile_path, new_val):
                old_rom_name = rom_name
                print(f"  ROM Filename set to '{new_val}'.")
                print()
                print(f"  {GOLD}Note:{RST} Building with the new name will create"
                      f" a new ROM file.")
                print(f"  Your existing ROM ({old_rom_name}) will be moved to"
                      f" a 'legacy_roms' folder.")
                print()
                built = _offer_build(game_path)
                if built:
                    _retire_old_rom(game_path, old_rom_name, new_val)
                rom_name = new_val
            else:
                print("  ERROR: Could not update Makefile.")

        elif choice == "6":
            print()
            new_val = input(f"  Internal Name (current: {game_name!r}) > ").strip()
            if not new_val:
                print("  Cancelled.")
                continue
            if len(new_val) > 31:
                print(f"  Internal Name must be 31 characters or fewer. Got {len(new_val)}.")
                continue
            if '"' in new_val or '\\' in new_val:
                print("  Internal Name cannot contain quote or backslash characters.")
                continue
            if _write_game_name(rom_header_path, new_val):
                print(f"  Internal Name set to '{new_val}'.")
                _offer_build(game_path)
            else:
                print("  ERROR: Could not update rom_header_gf.c.")

        else:
            print("  Invalid choice.")
