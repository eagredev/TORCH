"""UI helpers, logo display, and formatting for TORCH."""
# TORCH_MODULE: UI Helpers
# TORCH_GROUP: Core
import json
import os
import sys
import re
import subprocess

from torch import VERSION, BUILD_TRACK
from torch.config import load_config
from torch.expansion_compat import MAKE_RELEASE, detect_expansion_version
from torch.textutils import count_text_boxes, dialogue_prompt as _dialogue_prompt_impl
from torch.colours import GOLD, WHITE, GREEN, DIM, RST


def clear_screen():
    """Clear the terminal and scrollback for a clean redraw.

    Uses ANSI escapes instead of os.system("clear") to avoid the visible
    blank frame caused by subprocess overhead.  Sequence:
      \\033[H    — cursor to top-left
      \\033[2J   — erase entire visible screen
      \\033[3J   — erase scrollback buffer
    """
    sys.stdout.write("\033[H\033[2J\033[3J")
    sys.stdout.flush()


TORCHIC_ART = """\
**+
 -****:     -*
   ******  -***
    ****+*****=
      ***+++*---+
  -****+=++++++++++=
 -****+=++++++++++#.+
      +++++++++++++.++
      +++.#:++=***+++=
      +++...++*---+++
       ++++++++=-++-**=
         ++++++++*****:++
           *-++:*****+=+
          *=+=++*==--++
             =+-=+=--=
                  + +*+
               *:* =***
             +*+ +**"""

# -- ANSI colour codes for Torchic logo --
# Each art character maps to a fixed colour (per-glyph colouring).
_C_YELLOW   = "\033[38;2;248;208;48m"   # * — yellow (crest, neck feathers, legs)
_C_ORANGE   = "\033[38;2;240;128;48m"   # + — orange (main head & body)
_C_LTYELLOW = "\033[38;2;255;224;130m"  # - — light yellow (beak, feet highlights)
_C_DKORANGE = "\033[38;2;220;100;50m"   # = — dark orange/red (shadows, mouth)
_C_WHITE    = "\033[38;2;255;255;255m"  # : — white (eye reflection)
_C_BLACK    = "\033[38;2;30;30;30m"     # . — near-black (eye pupil)
_C_EYEWHT   = "\033[38;2;255;255;255m"  # # (interior) — eye whites
_C_RDPINK   = "\033[38;2;220;60;80m"   # inner mouth
_C_RESET    = "\033[0m"


def _k(s):
    """Format a key hint: _k('q') -> '[q]' in gold."""
    return f"{_C_YELLOW}[{s}]{_C_RESET}"


# Each art line encoded as list of (text, colour) segments.
# Per-glyph colouring: * = yellow, + = orange, - = light yellow,
# = = dark orange, . = black, : = white, # (interior) = eye white.
_TORCHIC_COLOUR = [
    # Line 1: top of crest (padded to match line 2 width for alignment)
    [(" ", ""), ("**", _C_YELLOW), ("+", _C_YELLOW), ("          ", "")],
    # Line 2: crest feathers
    [(" ", ""), ("-", _C_LTYELLOW), ("****", _C_YELLOW), (":", _C_YELLOW),
     ("     ", ""), ("-", _C_LTYELLOW), ("*", _C_YELLOW)],
    # Line 3: crest split
    [("   ", ""), ("******", _C_YELLOW), ("  ", ""), ("-", _C_LTYELLOW), ("***", _C_YELLOW)],
    # Line 4: crest meets head
    [("    ", ""), ("****", _C_YELLOW), ("+", _C_ORANGE), ("*****", _C_YELLOW),
     ("=", _C_YELLOW)],
    # Line 5: crest tip, body starts
    [("      ", ""), ("***", _C_YELLOW), ("+++", _C_ORANGE), ("*", _C_YELLOW),
     ("---", _C_ORANGE), ("+", _C_ORANGE)],
    # Line 6: body
    [("  ", ""), ("-", _C_LTYELLOW), ("****", _C_YELLOW), ("+", _C_ORANGE),
     ("=", _C_DKORANGE), ("+++++++++", _C_ORANGE), ("+", _C_ORANGE),
     ("=", _C_DKORANGE)],
    # Line 7: body, right eye
    [(" ", ""), ("-", _C_LTYELLOW), ("****", _C_YELLOW), ("+", _C_ORANGE),
     ("=", _C_DKORANGE), ("++++++++++", _C_ORANGE), ("#", _C_EYEWHT),
     (".", _C_BLACK), ("+", _C_ORANGE)],
    # Line 8: body, beak
    [("      ", ""), ("+++++++++++++", _C_ORANGE), (".", _C_BLACK), ("++", _C_ORANGE)],
    # Line 9: body, left eye, beak
    [("      ", ""), ("+++", _C_ORANGE), (".", _C_BLACK), ("#", _C_EYEWHT),
     (":", _C_WHITE), ("++", _C_ORANGE), ("=", _C_DKORANGE), ("***", _C_YELLOW),
     ("+++", _C_ORANGE), ("=", _C_DKORANGE)],
    # Line 10: face detail, inner mouth
    [("      ", ""), ("+++", _C_ORANGE), ("...", _C_BLACK), ("++", _C_ORANGE),
     ("*", _C_YELLOW), ("---", _C_RDPINK), ("+++", _C_ORANGE)],
    # Line 11: body
    [("       ", ""), ("++++++++", _C_ORANGE), ("=", _C_DKORANGE),
     ("-", _C_ORANGE), ("++", _C_ORANGE), ("-", _C_LTYELLOW), ("**", _C_YELLOW),
     ("=", _C_DKORANGE)],
    # Line 12: chest, feet start
    [("         ", ""), ("++++++++", _C_ORANGE),
     ("*****", _C_YELLOW), (":", _C_WHITE), ("++", _C_ORANGE)],
    # Line 13: lower body
    [("           ", ""), ("*", _C_YELLOW), ("-", _C_LTYELLOW), ("++", _C_ORANGE),
     (":", _C_WHITE), ("*****", _C_YELLOW), ("+", _C_ORANGE), ("=", _C_DKORANGE),
     ("+", _C_ORANGE)],
    # Line 14: legs
    [("          ", ""), ("*", _C_YELLOW), ("=", _C_DKORANGE), ("+", _C_ORANGE),
     ("=", _C_DKORANGE), ("++", _C_ORANGE), ("*", _C_YELLOW), ("==", _C_DKORANGE),
     ("--", _C_LTYELLOW), ("++", _C_ORANGE)],
    # Line 15: ankles
    [("             ", ""), ("=", _C_DKORANGE), ("+", _C_ORANGE), ("-", _C_LTYELLOW),
     ("=", _C_DKORANGE), ("+", _C_ORANGE), ("=", _C_DKORANGE), ("--", _C_LTYELLOW),
     ("=", _C_DKORANGE)],
    # Line 16: toes
    [("                  ", ""), ("+", _C_ORANGE), (" ", ""), ("+", _C_ORANGE),
     ("*", _C_YELLOW), ("+", _C_ORANGE)],
    # Line 17: feet
    [("               ", ""), ("*", _C_YELLOW),
     (":", _C_WHITE), ("*", _C_YELLOW), (" ", ""), ("=", _C_DKORANGE),
     ("***", _C_YELLOW)],
    # Line 18: feet
    [("             ", ""), ("+", _C_ORANGE), ("*", _C_YELLOW), ("+", _C_ORANGE),
     (" ", ""), ("+", _C_ORANGE), ("**", _C_YELLOW)],
]


def _render_colour_line(segments):
    """Render a list of (text, colour) segments into a single coloured string."""
    parts = []
    for text, colour in segments:
        if colour:
            parts.append(f"{colour}{text}{_C_RESET}")
        else:
            parts.append(text)
    return "".join(parts)


def _plain_len(segments):
    """Return the visible (uncoloured) character count of a segment list."""
    return sum(len(text) for text, _ in segments)


def print_logo(subtitle, proj_name=None):
    """Print the TORCH logo with Torchic art and a subtitle, centred over the panel.

    If proj_name is given it is shown in the 'Project' field; subtitle is shown
    as a dim module tag after it.  If only subtitle is given it fills the
    Project field directly (legacy / no-project contexts such as init/update).
    """
    panel_width = 51  # 2-space indent + 49 box-drawing chars
    for segments in _TORCHIC_COLOUR:
        rendered = _render_colour_line(segments)
        visible = _plain_len(segments)
        pad = max(0, (panel_width - visible) // 2)
        print(" " * pad + rendered)
    track_label = {"dev": "  [dev]", "experimental": "  [experimental]", "unknown": "  [?]"}.get(BUILD_TRACK, "")
    ver_text = f"TORCH  v{VERSION}{track_label}"
    print(f"{GOLD}{ver_text.center(panel_width)}{RST}")
    tagline = f"{DIM}The Open ROM Creation Hub{RST}"
    tagline_plain = "The Open ROM Creation Hub"
    print(tagline.center(panel_width + (len(tagline) - len(tagline_plain))))
    if proj_name and subtitle:
        print()
        combined = (f"{DIM}Project{RST}  {WHITE}{proj_name}{RST}"
                    f"  {DIM}\u2014  {subtitle}{RST}")
        combined_plain = f"Project  {proj_name}  \u2014  {subtitle}"
        print(combined.center(panel_width + (len(combined) - len(combined_plain))))
    elif subtitle or proj_name:
        text = proj_name or subtitle
        print()
        combined = f"{DIM}Project{RST}  {WHITE}{text}{RST}"
        combined_plain = f"Project  {text}"
        print(combined.center(panel_width + (len(combined) - len(combined_plain))))
    print()


def _set_terminal_title(title):
    """Set the Konsole (or any VTE) window title via ANSI escape."""
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def _fmt_class(raw):
    """Strip TRAINER_CLASS_ prefix and title-case. E.g. TRAINER_CLASS_TEAM_ROCKET -> Team Rocket."""
    if not raw:
        return "?"
    return raw.replace("TRAINER_CLASS_", "").replace("_", " ").title()


def _fmt_music(raw):
    """Strip TRAINER_ENCOUNTER_MUSIC_ prefix and title-case."""
    if not raw:
        return "?"
    return raw.replace("TRAINER_ENCOUNTER_MUSIC_", "").replace("_", " ").title()


def _fmt_sprite(raw):
    """Strip TRAINER_PIC_ prefix and title-case."""
    if not raw:
        return "?"
    return raw.replace("TRAINER_PIC_", "").replace("_", " ").title()


def _fmt_ai_flags(raw):
    """Split | separated AI flags, strip AI_FLAG_ prefix, title-case, join with commas."""
    if not raw:
        return "?"
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    return ", ".join(p.replace("AI_FLAG_", "").replace("_", " ").title() for p in parts)


def _truncate_dialogue(text, max_len=45):
    """Strip control chars and truncate dialogue for preview."""
    if not text:
        return "(none)"
    clean = text.replace("\\n", " ").replace("\\p", " ").replace("$", "").strip()
    clean = re.sub(r'\s+', ' ', clean)
    if len(clean) > max_len:
        return clean[:max_len - 3] + "..."
    return clean


def _fmt_const_name(const, lookup):
    """Return human-readable name from lookup dict, or fall back to title-cased suffix."""
    if not const:
        return "?"
    if const in lookup:
        return lookup[const]
    for prefix in ("ABILITY_", "MOVE_", "SPECIES_", "ITEM_",
                    "TRAINER_ENCOUNTER_MUSIC_", "TRAINER_PIC_"):
        if const.startswith(prefix):
            return const[len(prefix):].replace("_", " ").title()
    return const


def _parse_ability_names(game_path):
    """Returns {ABILITY_CONST: 'Display Name'} from src/data/text/abilities.h."""
    path = os.path.join(game_path, "src", "data", "text", "abilities.h")
    result = {}
    if not os.path.exists(path):
        return result
    with open(path) as f:
        for line in f:
            m = re.match(r'\s*\[(\w+)\]\s*=\s*_\("([^"]+)"\)', line)
            if m:
                result[m.group(1)] = m.group(2)
    return result


def _parse_ability_descriptions(game_path):
    """Returns {ABILITY_CONST: 'Description'} from src/data/text/abilities.h."""
    path = os.path.join(game_path, "src", "data", "text", "abilities.h")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        content = f.read()
    desc_var_to_text = {}
    for m in re.finditer(r'static\s+const\s+u8\s+(s\w+Description)\[\]\s*=\s*_\("([^"]+)"\)', content):
        desc_var_to_text[m.group(1)] = m.group(2)
    result = {}
    for m in re.finditer(r'\[(\w+)\]\s*=\s*(s\w+Description)', content):
        var = m.group(2)
        if var in desc_var_to_text:
            result[m.group(1)] = desc_var_to_text[var]
    return result


def _parse_move_names(game_path):
    """Returns {MOVE_CONST: 'Display Name'} from src/data/text/move_names.h."""
    path = os.path.join(game_path, "src", "data", "text", "move_names.h")
    result = {}
    if not os.path.exists(path):
        return result
    with open(path) as f:
        for line in f:
            m = re.match(r'\s*\[(\w+)\]\s*=\s*_\("([^"]+)"\)', line)
            if m:
                result[m.group(1)] = m.group(2)
    return result


def _diagnose_build_error(stderr_text):
    """Parse build stderr and print human-readable diagnosis."""
    patterns = [
        (r'stddef\.h.*No such file',
         "GCC header missing -- this happens after SteamOS updates. Run: fixdev"),
        (r"region 'rom' overflowed",
         "ROM too large -- the game exceeds the GBA ROM size limit. Remove unused content with torch scorch or reduce assets."),
        (r"No rule to make target '([^']*data/maps/\w+[^']*)'",
         None),  # special: uses match group
        (r"No rule to make target",
         "Missing file referenced by the build system. Check if a file was deleted without updating its references."),
        (r"([\w/]+\.pory):\s*\d+.*error",
         None),  # special: uses match group
        (r"'(\w+)' undeclared",
         None),  # special: uses match group
        (r"expected '.*' before",
         "Syntax error in C source -- likely an unmatched brace or missing semicolon. Check the file and line listed above."),
        (r"symbol `(\w+)' is already defined",
         None),  # special: uses match group
    ]
    # Check for undefined references to map scripts first (can have many)
    undef_refs = re.findall(
        r"undefined reference to `([^'`]+)'", stderr_text
    )
    if undef_refs:
        # Extract map names from linker context lines like:
        #   in function `PlayerHome_MapBGEvents':
        #   in function `LakeElixSouth_ObjectEvents':
        # Build a map of "current map context" per line position
        context_maps = []
        for m_ctx in re.finditer(
            r"in function `(\w+?)_(MapBGEvents|ObjectEvents|MapWarps|"
            r"MapCoordEvents|MapEvents)'", stderr_text
        ):
            context_maps.append((m_ctx.start(), m_ctx.group(1)))
        # Group each undefined ref under its nearest preceding context map
        by_map = {}
        for m_ref in re.finditer(
            r"undefined reference to `([^'`]+)'", stderr_text
        ):
            label = m_ref.group(1)
            map_name = "Unknown"
            for pos, name in reversed(context_maps):
                if pos < m_ref.start():
                    map_name = name
                    break
            by_map.setdefault(map_name, []).append(label)
        print(f"  {GOLD}{'─' * 50}{RST}")
        print(f"  {GOLD}TORCH diagnosis:{RST}")
        print(f"    {len(undef_refs)} missing script(s) -- events on your map")
        print(f"    are pointing at scripts that don't exist yet.")
        print()
        print(f"    For each label below, either:")
        print(f"    - Write the script and run torch sync, or")
        print(f"    - Open the map in Porymap and remove/reassign the event")
        print()
        for map_name, labels in sorted(by_map.items()):
            print(f"    {GOLD}{map_name}:{RST}")
            for label in labels:
                print(f"      - {label}")
        print(f"  {GOLD}{'─' * 50}{RST}")
        return "undefined_script_references"
    # Check for duplicate symbol definitions (can have many)
    dup_symbols = re.findall(
        r"symbol `(\w+)' is already defined", stderr_text
    )
    if dup_symbols:
        # Extract file context from lines like:
        #   data/maps/PlayerHome/scripts.inc:5: Error: symbol `...' is already defined
        by_file = {}
        for m_dup in re.finditer(
            r"([\w/]+\.(?:inc|pory|s)):\d+:.*symbol `(\w+)' is already defined",
            stderr_text,
        ):
            by_file.setdefault(m_dup.group(1), []).append(m_dup.group(2))
        print(f"  {GOLD}{'─' * 50}{RST}")
        print(f"  {GOLD}TORCH diagnosis:{RST}")
        print(f"    {len(dup_symbols)} duplicate label(s) -- the same script")
        print(f"    label is defined in two places.")
        print()
        print(f"    This usually means a label in legacy.pory is also")
        print(f"    in setup.pory. Check each map's workspace folder")
        print(f"    and remove the duplicate from one of the files.")
        print()
        for fpath, labels in sorted(by_file.items()):
            print(f"    {GOLD}{fpath}:{RST}")
            for label in labels:
                print(f"      - {label}")
        print(f"  {GOLD}{'─' * 50}{RST}")
        return "duplicate_symbols"
    for pattern, static_msg in patterns:
        m = re.search(pattern, stderr_text)
        if m:
            if pattern.startswith(r"No rule to make target '([^']*data/maps"):
                diagnosis = (f"Missing map file: {m.group(1)}. Was it removed by SCORCH "
                             "or manually deleted? Check data/maps/ and map_groups.json.")
            elif pattern.startswith(r"([\w/]+\.pory)"):
                diagnosis = (f"Poryscript error in {m.group(1)}. Check the script for "
                             "syntax issues -- unmatched braces, missing semicolons, "
                             "or undefined labels.")
            elif pattern.startswith(r"'(\w+)' undeclared"):
                diagnosis = (f"Undeclared constant: {m.group(1)}. Make sure it's defined "
                             "in the correct header (flags.h, vars.h, opponents.h, etc.).")
            else:
                diagnosis = static_msg
            print(f"  {GOLD}{'─' * 50}{RST}")
            print(f"  {GOLD}TORCH diagnosis:{RST}")
            print(f"    {diagnosis}")
            print(f"  {GOLD}{'─' * 50}{RST}")
            return diagnosis
    return None


def _get_auto_build_setting():
    """Read auto_build setting from config. Returns True if enabled (default)."""
    try:
        cfg = load_config()
        if cfg:
            _, _, settings = cfg
            val = settings.get("auto_build", True)
            if isinstance(val, str):
                return val.lower() in ("true", "1", "yes")
            return bool(val)
    except Exception:
        pass
    return True


def _sync_stale_before_build(project_dir, game_path, emotes_conf, source_display, max_snapshots):
    """Check enrolled maps for staleness and auto-sync before build.

    Only syncs claimed maps. Re-decompiles pristine_stale maps.
    Returns the number of maps synced, or 0 if none needed.
    Silently returns 0 if registry module is unavailable.
    """
    try:
        from torch.registry import (
            get_enrolled_maps, get_map_health,
            get_map_state, STATE_PRISTINE, STATE_LOCKED,
        )
        from torch.sync import sync_map
    except ImportError:
        return 0
    try:
        enrolled = get_enrolled_maps(project_dir)
    except Exception:
        return 0

    stale = []
    pristine_stale = []
    for name in enrolled:
        try:
            state = get_map_state(project_dir, name)
            if state in (STATE_PRISTINE, STATE_LOCKED):
                # Check pristine maps for staleness
                if state == STATE_PRISTINE:
                    health = get_map_health(project_dir, name, game_path)
                    if health == "pristine_stale":
                        pristine_stale.append(name)
                continue
            health = get_map_health(project_dir, name, game_path)
            if health in ("stale", "never_written"):
                stale.append(name)
        except Exception:
            pass

    # Re-decompile pristine_stale maps
    if pristine_stale:
        try:
            from torch.bulk_decompile import re_decompile_pristine
            for name in pristine_stale:
                try:
                    re_decompile_pristine(game_path, name, project_dir)
                except Exception:
                    pass
        except ImportError:
            pass

    if not stale:
        return 0
    print(f"  {DIM}Syncing {len(stale)} stale map(s) before build...{RST}")
    synced = 0
    for name in stale:
        print(f"  {DIM}  {name}{RST}")
        try:
            sync_map(name, project_dir, game_path, emotes_conf, source_display, max_snapshots)
            synced += 1
        except Exception:
            pass
    return synced


def _find_built_rom(game_path):
    """Find the most recently modified .gba file in the game directory."""
    best_path = None
    best_mtime = 0
    for entry in os.listdir(game_path):
        if entry.endswith(".gba"):
            fpath = os.path.join(game_path, entry)
            try:
                mt = os.path.getmtime(fpath)
                if mt > best_mtime:
                    best_mtime = mt
                    best_path = fpath
            except OSError:
                pass
    return best_path


def _build_command(expansion_version):
    """Return the make command list for the given expansion version.

    v1.14.0+: ['make', 'release', '-j{nproc}']
    Earlier / unknown: ['make', '-j{nproc}']
    """
    nproc = os.cpu_count() or 4
    if expansion_version is not None and expansion_version >= MAKE_RELEASE:
        return ["make", "release", f"-j{nproc}"]
    return ["make", f"-j{nproc}"]


_SNAPSHOT_STALE_DAYS = 3


def _warn_stale_snapshot(game_path):
    """Warn if the most recent verified snapshot is older than N days."""
    try:
        from torch.verified_snapshots import list_verified_snapshots
        from datetime import datetime, timezone
        snapshots = list_verified_snapshots(game_path)
        if not snapshots:
            print(f"  {GOLD}Warning:{RST} No verified build snapshots exist.")
            print(f"  {DIM}This build will create one. Use 'torch restore' to roll back.{RST}")
            return
        latest = snapshots[0]  # newest first
        ts_str = latest.get("timestamp", "")
        if not ts_str:
            return
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_days = (now - ts).days
        if age_days >= _SNAPSHOT_STALE_DAYS:
            print(f"  {GOLD}Warning:{RST} Last verified snapshot is {age_days} day(s) old.")
            print(f"  {DIM}If you've been using 'bb' to build, snapshots aren't created.{RST}")
            print(f"  {DIM}Use 'torch build' regularly to maintain safety snapshots.{RST}")
    except Exception:
        pass  # Never block a build for snapshot warnings


def _sanitize_map_scripts(game_path):
    """Fix empty script fields in map.json files before building.

    mapjson crashes with "Value for 'script' cannot be empty" when an NPC
    has an empty string as its script value. This can happen after SCORCH
    removes vanilla script references or when NPCs are created without scripts.
    """
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return
    for entry in os.listdir(maps_dir):
        map_dir = os.path.join(maps_dir, entry)
        map_json = os.path.join(map_dir, "map.json")
        if not os.path.isfile(map_json):
            continue
        try:
            with open(map_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        fixed = False
        for obj in data.get("object_events", []):
            if not obj.get("script"):
                obj["script"] = "Common_EventScript_NopReturn"
                fixed = True
        if fixed:
            try:
                with open(map_json, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
            except OSError:
                pass


def _regenerate_map_incs(game_path):
    """Regenerate missing map .inc files (events, header, connections).

    These files are auto-generated from map.json by the mapjson tool.
    ``make clean`` deletes them, and stale build caches can cause
    "No rule to make target" errors when they go missing.
    Runs ``make generated`` if any are absent.
    """
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return
    needed = ("events.inc", "header.inc", "connections.inc")
    missing = False
    for entry in os.listdir(maps_dir):
        map_dir = os.path.join(maps_dir, entry)
        if not os.path.isdir(map_dir):
            continue
        map_json = os.path.join(map_dir, "map.json")
        if not os.path.isfile(map_json):
            continue
        for inc_name in needed:
            if not os.path.isfile(os.path.join(map_dir, inc_name)):
                missing = True
                break
        if missing:
            break
    if missing:
        try:
            subprocess.run(
                ["make", "generated"],
                cwd=game_path, capture_output=True,
                text=True, timeout=120,
            )
        except Exception:
            pass


def _precompile_poryscript(game_path):
    """Compile any .pory files missing their .inc counterpart.

    ``make clean`` deletes .inc files generated from .pory scripts.
    The Makefile has no rule to regenerate them, so we compile them
    here before invoking make.
    """
    compiler = os.path.join(game_path, "tools", "poryscript", "poryscript")
    if not os.path.isfile(compiler):
        return
    font_cfg = os.path.join(game_path, "font_config.json")
    maps_dir = os.path.join(game_path, "data", "maps")
    if not os.path.isdir(maps_dir):
        return
    for root, _dirs, files in os.walk(maps_dir):
        for fname in files:
            if not fname.endswith(".pory"):
                continue
            pory_path = os.path.join(root, fname)
            inc_path = pory_path[:-5] + ".inc"
            if os.path.isfile(inc_path):
                try:
                    if os.path.getmtime(inc_path) >= os.path.getmtime(pory_path):
                        continue
                except OSError:
                    pass
            cmd = [compiler, "-i", pory_path, "-o", inc_path]
            if os.path.isfile(font_cfg):
                cmd.extend(["-fc", font_cfg])
            try:
                subprocess.run(
                    cmd, cwd=game_path, capture_output=True,
                    text=True, timeout=30,
                )
            except Exception:
                pass


def _execute_build(game_path, expansion_version, trigger, diagnose):
    """Run make, report results, and create a verified snapshot on success.

    Returns True on success, False on failure/error.
    """
    # Auto-detect expansion version if not provided
    if expansion_version is None:
        expansion_version = detect_expansion_version(game_path)

    # Warn if last verified snapshot is stale
    _warn_stale_snapshot(game_path)

    # Run Map Guard to fix any Porymap save bugs before building
    try:
        from torch.sync import _run_map_guard
        guard_fixes = _run_map_guard(game_path)
        if guard_fixes:
            print(f"  Map Guard: fixed {guard_fixes} Porymap issue(s)")
    except Exception:
        pass  # Never let Map Guard failure block a build

    # Fix empty script fields in map.json (mapjson crashes on them)
    _sanitize_map_scripts(game_path)

    # Regenerate missing map .inc files (events, header, connections)
    _regenerate_map_incs(game_path)

    # Pre-compile any .pory files missing their .inc (make clean deletes them)
    _precompile_poryscript(game_path)

    cmd = _build_command(expansion_version)
    success = False
    try:
        result = subprocess.run(
            cmd,
            cwd=game_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode == 0:
            print(f"  {GREEN}Build successful.{RST}")
            success = True
            # Show ROM location
            rom_path = _find_built_rom(game_path)
            if rom_path:
                rom_display = rom_path.replace(os.path.expanduser("~"), "~")
                print(f"  ROM: {rom_display}")
            # Auto-snapshot on successful build
            try:
                from torch.verified_snapshots import create_verified_snapshot
                from torch.config import load_config as _vs_load_config
                _vs_cfg = _vs_load_config()
                _vs_max = 3
                if _vs_cfg:
                    _, _, _vs_settings = _vs_cfg
                    _vs_max = int(_vs_settings.get("max_verified_snapshots", 3))
                create_verified_snapshot(game_path, trigger=trigger, max_count=_vs_max)
            except Exception:
                pass  # Never let snapshot failure block the user
        else:
            print(result.stdout)
            print(f"  Build failed (exit code {result.returncode}).")
            if diagnose:
                _diagnose_build_error(result.stdout)
    except FileNotFoundError:
        print("  ERROR: 'make' not found. Is devkitARM in PATH?")
        print("  Run bb manually to build.")
    return success


def _offer_build(game_path=None, trigger="manual", safe=False, auto_build=False,
                 project_dir=None, emotes_conf=None, source_display=None, max_snapshots=10,
                 diagnose=True, expansion_version=None):
    """Prompt user to build, or auto-build after safe operations.

    When safe=True and auto_build=True, skips the Y/n prompt.
    If project_dir is provided, checks for stale maps and auto-syncs before building.
    On failure, diagnoses common errors from stderr.
    expansion_version: tuple (major, minor, patch) or None. When >= (1,14,0),
    uses 'make release' instead of plain 'make'.

    Returns True on success, False on failure/error, None if the user declined.
    """
    # Auto-sync stale maps if we have project context
    if project_dir and emotes_conf and source_display:
        _sync_stale_before_build(project_dir, game_path, emotes_conf, source_display, max_snapshots)

    # Build mode label
    release_mode = (expansion_version is not None and expansion_version >= MAKE_RELEASE)

    # Decide whether to prompt
    if safe and auto_build:
        do_build = True
        if release_mode:
            print("  Building (release mode)...")
        else:
            print("  Building...")
    else:
        yn = input("  Build now? [Y/n] > ").strip().lower()
        do_build = yn in ("", "y", "yes")

    if do_build:
        print()
        if release_mode:
            print("  Building ROM (release mode) — this may take a few minutes...")
        else:
            print("  Building ROM — this may take a few minutes...")
        print()
        if not game_path:
            cfg = load_config()
            if cfg:
                _, projects, _ = cfg
                if projects:
                    first_proj = list(projects.values())[0]
                    game_path = os.path.expanduser(first_proj["game_path"])
        if not game_path:
            print("  Error: Could not determine game path. Run bb manually.")
            return False
        game_path = os.path.expanduser(game_path)
        success = _execute_build(game_path, expansion_version, trigger, diagnose)
        # Auto-enroll custom maps after a successful build
        if success and project_dir:
            try:
                from torch.registry import bulk_enroll
                count, _ = bulk_enroll(project_dir, game_path)
                if count:
                    print(f"  {DIM}Auto-enrolled {count} map(s).{RST}")
            except Exception:
                pass
        input("  Press Enter to continue > ")
        return success
    else:
        print("  Remember to run bb before testing.")
        return None


# Module-level alias so other modules that import _count_dialogue_boxes from
# torch.ui continue to work unchanged.
_count_dialogue_boxes = count_text_boxes


def _dialogue_prompt(label, is_double=False, textbox_warning=3):
    """Prompt for dialogue text with auto-wrap preview and length check.

    Thin wrapper around textutils.dialogue_prompt — eliminates the old
    circular lazy-import of torch.battle_wizard._wrap_dialogue.
    """
    return _dialogue_prompt_impl(label, is_double=is_double, textbox_warning=textbox_warning)
