"""Script compiler — converts .txt TorScript to Poryscript .pory."""
# TORCH_MODULE: Script Compiler
# TORCH_GROUP: Script Studio
import os
import re

from torch.data import (
    BUILTIN_EMOTES, COMMON_EMOTES, COMMON_FACE,
    WALK_COMMANDS, WALKTO_COMMANDS, DIRECTIONS,
    JUMP_COMMANDS, JUMP2_COMMANDS,
)


class CompilerState:
    def __init__(self, label_prefix, map_id=None, game_path=None,
                 map_name=None):
        self.label_prefix = label_prefix
        self.map_id = map_id        # MAP_* constant from map.json "id" (for camera reset warp fallback)
        self.game_path = game_path  # game project root (for self-flag allocation)
        self.map_name = map_name    # map folder name (for self-flag naming)
        self.aliases = {}           # alias_name -> npc_number (int)
        self.pokemon_actors = {}    # name -> {"npc_id": int, "species": str}
        self.pokemon_hidden = set()        # Pokemon actors that have been hidden
        self.needs_pokemon_patch = False   # whether compiled output uses ScriptUnfreezePokemonActor
        self.const_lines = []       # const declarations (from aliases)
        self.output_blocks = []     # list of top-level blocks (strings)
        self.current_script = None  # name of current script block
        self.script_lines = []      # lines inside current script { }
        self.movement_blocks = []   # (label, list_of_movement_commands)
        self.text_blocks = []       # (label, text_string) for named text blocks
        self.move_counter = 0
        self.walkto_counter = 0  # Unique counter for walkto loop labels
        self.walkto_steps_emitted = False  # Shared single-step movement blocks
        self.emotes = {}
        self.errors = []
        self.current_line_num = 0
        self.has_mapscripts = False
        self.auto_labels = {}  # label_name -> [lines] for auto-generated labels
        self.camera_spawned = False   # whether SpawnCameraObject has been emitted
        self.camera_offset_x = 0     # accumulated camera pan X tiles (+ = east)
        self.camera_offset_y = 0     # accumulated camera pan Y tiles (+ = south)
        self.needs_camera_patch = False  # whether compiled output uses ScriptResetCameraOffset
        self.if_depth = 0            # nesting level for if/elif/else/endif blocks
        self.switch_depth = 0        # nesting level for switch/case/endswitch blocks
        self.choice_options = []     # option texts for current choice block
        self.choice_prompt = ""      # prompt text for current choice block
        # NPC Pages
        self.current_page = None     # {"page_num": int, "label": str|None, "condition": str|None, "hide_targets": []}
        self.page_groups = {}        # label_name -> [page_info_dict, ...]
        self.page_lines = {}         # label_name -> {page_num: [emitted_lines]}
        self.self_flag_names = {}    # cache: "suffix_key" -> "FLAG_SELF_..." name

    def error(self, msg):
        self.errors.append(f"Line {self.current_line_num}: {msg}")

    def next_move_label(self):
        self.move_counter += 1
        return f"{self.label_prefix}_Move_{self.move_counter}"

    def emit(self, line):
        """Add a line inside the current script block."""
        if self.current_page and self.current_page.get("label"):
            label = self.current_page["label"]
            pnum = self.current_page["page_num"]
            self.page_lines.setdefault(label, {}).setdefault(pnum, []).append(line)
        else:
            self.script_lines.append(line)

    def emit_blank(self):
        self.script_lines.append("")

    def resolve_self_flag(self, suffix):
        """Resolve self.SUFFIX to a deterministic FLAG_SELF_... name."""
        from torch.self_flags import make_self_flag_name
        # Determine NPC context from current page label or current script
        npc_label = ""
        if self.current_page and self.current_page.get("label"):
            npc_label = self.current_page["label"]
        elif self.current_script:
            npc_label = self.current_script
        map_ref = self.map_name or self.label_prefix
        key = f"{map_ref}_{npc_label}_{suffix}"
        if key in self.self_flag_names:
            return self.self_flag_names[key]
        flag_name = make_self_flag_name(map_ref, npc_label, suffix)
        self.self_flag_names[key] = flag_name
        return flag_name

    def open_script(self, name):
        """Start a new script block."""
        if self.current_script:
            self.close_script()
        self.current_script = name
        self.script_lines = []
        self.camera_spawned = False
        self.camera_offset_x = 0
        self.camera_offset_y = 0

    def register_auto_label(self, label, lines_list):
        """Register a label to be auto-appended at end if not already defined."""
        if label not in self.auto_labels:
            self.auto_labels[label] = lines_list

    def close_script(self):
        """Close the current script block and add it to output."""
        if self.current_script:
            # Check for unclosed blocks and auto-close with error
            target = self.script_lines
            if self.current_page and self.current_page.get("label"):
                label = self.current_page["label"]
                pnum = self.current_page["page_num"]
                target = self.page_lines.get(label, {}).get(pnum, self.script_lines)
            if self.if_depth > 0:
                self.error(f"Unclosed 'if' block ({self.if_depth} level(s) deep) at end of script '{self.current_script}'")
                for _ in range(self.if_depth):
                    target.append("}")
                self.if_depth = 0
            if self.switch_depth > 0:
                self.error(f"Unclosed 'switch' block at end of script '{self.current_script}'")
                for _ in range(self.switch_depth):
                    target.append("}")
                self.switch_depth = 0
            # Pages: lines went to page_lines via emit redirect, skip output_blocks
            if self.current_page:
                self.current_script = None
                self.script_lines = []
                return
            lines = "\n".join(f"    {l}" if l else "" for l in self.script_lines)
            block = f"script {self.current_script} {{\n{lines}\n}}"
            self.output_blocks.append(block)
            self.current_script = None
            self.script_lines = []


def load_emotes(emotes_conf):
    """Load built-in emotes and merge with custom ones from emotes.conf."""
    emotes = dict(BUILTIN_EMOTES)
    if emotes_conf and os.path.exists(emotes_conf):
        with open(emotes_conf, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    emotes[key.strip()] = val.strip()
    return emotes


def resolve_actor(name, state):
    """Resolve an actor name to its Poryscript reference."""
    if name == "player":
        return "OBJ_EVENT_ID_PLAYER"
    if name in state.aliases:
        # Return the LOCALID constant name
        const_name = f"LOCALID_{name.upper()}"
        return const_name
    # Check if it's npcN format
    m = re.match(r"^npc(\\d+)$", name)
    if m:
        return m.group(1)
    state.error(f"Unknown actor '{name}'. Use 'player', 'npcN', or define an alias.")
    return name


def parse_movement_action(actor, parts, state):
    """
    Parse a movement action for a single actor.
    Returns (actor_ref, movement_label, custom_block_or_None).
    """
    actor_ref = resolve_actor(actor, state)
    cmd = parts[0] if parts else ""

    # --- do (play a named movement block) ---
    if cmd == "do":
        if len(parts) < 2:
            state.error("'do' needs a movement label name, e.g. 'actorname do MapName_MovementBlockName'")
            return None
        move_label = parts[1]
        return (actor_ref, move_label, None)

    # --- face ---
    if cmd == "face":
        if len(parts) < 2:
            state.error("'face' needs a direction (up/down/left/right/player/away)")
            return None
        direction = parts[1]
        if direction in COMMON_FACE:
            return (actor_ref, COMMON_FACE[direction], None)
        else:
            state.error(f"Unknown face direction '{direction}'")
            return None

    # --- emote ---
    if cmd == "emote":
        if len(parts) < 2:
            state.error("'emote' needs an emote name (!, ?, !!, x, heart, ...)")
            return None
        emote_name = parts[1]
        if emote_name in COMMON_EMOTES:
            return (actor_ref, COMMON_EMOTES[emote_name], None)
        if emote_name in state.emotes:
            label = state.next_move_label()
            block = [state.emotes[emote_name]]
            return (actor_ref, label, block)
        else:
            state.error(f"Unknown emote '{emote_name}'. Add it to config/emotes.conf.")
            return None

    # --- walk / walkfast / walkslow / run / slide ---
    if cmd in WALK_COMMANDS:
        if len(parts) < 3:
            state.error(f"'{cmd}' needs direction and count, e.g. '{cmd} up 3'")
            return None
        direction = parts[1]
        if direction not in DIRECTIONS:
            state.error(f"Unknown direction '{direction}' for '{cmd}'")
            return None
        try:
            count = int(parts[2])
        except ValueError:
            state.error(f"'{cmd}' count must be a number, got '{parts[2]}'")
            return None
        prefix = WALK_COMMANDS[cmd]
        move_cmd = f"{prefix}_{direction}"
        label = state.next_move_label()
        block = [f"{move_cmd} * {count}" if count > 1 else move_cmd]
        return (actor_ref, label, block)

    # --- jump ---
    if cmd == "jump":
        if len(parts) < 2:
            state.error("'jump' needs a direction (up/down/left/right)")
            return None
        direction = parts[1]
        if direction not in DIRECTIONS:
            state.error(f"Unknown jump direction '{direction}'")
            return None
        tile_count = 1
        if len(parts) >= 3:
            try:
                tile_count = int(parts[2])
            except ValueError:
                state.error(f"Jump tile count must be a number, got '{parts[2]}'")
                return None
        if tile_count == 1:
            label = state.next_move_label()
            block = [JUMP_COMMANDS[direction]]
            return (actor_ref, label, block)
        elif tile_count == 2:
            label = state.next_move_label()
            block = [JUMP2_COMMANDS[direction]]
            return (actor_ref, label, block)
        else:
            state.error(f"Jump supports 1 or 2 tiles, not {tile_count}")
            return None

    state.error(f"Unknown movement command '{cmd}'")
    return None


# ---------------------------------------------------------------------------
# walkto — dynamic walk-to-coordinate compilation
# ---------------------------------------------------------------------------
# Uses VAR_0x8004 (target X), VAR_0x8005 (target Y),
#      VAR_0x8006 (current X), VAR_0x8007 (current Y) as scratch.
#
# Syntax:
#   actor walkto X Y              — walk to absolute tile (X, Y)
#   actor walkto player OX OY     — walk to (player_x + OX, player_y + OY)
#   actor walkto otheractor OX OY — walk to (actor_x + OX, actor_y + OY)
#   actor walkfastto ...           — same, run speed
#   actor walkslowto ...           — same, slow speed
#
# Compiles to: inline setup + call(loop) + loop auto-labels
# The loop walks one tile at a time on X axis, then Y axis (L-shaped path).

_WALKTO_VAR_TARGET_X = "VAR_0x8004"
_WALKTO_VAR_TARGET_Y = "VAR_0x8005"
_WALKTO_VAR_CUR_X = "VAR_0x8006"
_WALKTO_VAR_CUR_Y = "VAR_0x8007"


def _compile_walkto(actor_name, parts, state):
    """Compile a walkto command into inline setup + call to loop subroutine."""
    cmd = parts[0]
    speed_prefix = WALKTO_COMMANDS.get(cmd, "walk")
    actor_ref = resolve_actor(actor_name, state)

    # Parse target: walkto X Y  OR  walkto <ref_actor> OX OY
    if len(parts) < 3:
        state.error(f"'{cmd}' needs target coords: '{cmd} X Y' or "
                    f"'{cmd} player OX OY'")
        return
    target_arg = parts[1]

    # Check if target is a number (absolute) or an actor reference (relative)
    try:
        abs_x = int(target_arg)
        # Absolute mode: walkto X Y
        if len(parts) < 3:
            state.error(f"'{cmd}' absolute mode needs X and Y: '{cmd} 25 61'")
            return
        try:
            abs_y = int(parts[2])
        except ValueError:
            state.error(f"'{cmd}' Y coordinate must be a number, got '{parts[2]}'")
            return
        # Emit: setvar target_x, abs_x; setvar target_y, abs_y
        state.emit(f"setvar({_WALKTO_VAR_TARGET_X}, {abs_x})")
        state.emit(f"setvar({_WALKTO_VAR_TARGET_Y}, {abs_y})")

    except ValueError:
        # Relative mode: walkto <actor> OX OY
        ref_actor = target_arg
        if len(parts) < 4:
            state.error(f"'{cmd}' relative mode needs offsets: "
                        f"'{cmd} {ref_actor} OX OY'")
            return
        try:
            off_x = int(parts[2])
            off_y = int(parts[3])
        except ValueError:
            state.error(f"'{cmd}' offsets must be numbers, got "
                        f"'{parts[2]}' '{parts[3]}'")
            return

        if ref_actor == "player":
            state.emit(f"getplayerxy({_WALKTO_VAR_TARGET_X}, "
                        f"{_WALKTO_VAR_TARGET_Y})")
        else:
            ref_ref = resolve_actor(ref_actor, state)
            state.emit(f"getobjectxy({ref_ref}, CURRENT_POSITION, "
                        f"{_WALKTO_VAR_TARGET_X}, {_WALKTO_VAR_TARGET_Y})")

        if off_x > 0:
            state.emit(f"addvar({_WALKTO_VAR_TARGET_X}, {off_x})")
        elif off_x < 0:
            state.emit(f"subvar({_WALKTO_VAR_TARGET_X}, {-off_x})")
        if off_y > 0:
            state.emit(f"addvar({_WALKTO_VAR_TARGET_Y}, {off_y})")
        elif off_y < 0:
            state.emit(f"subvar({_WALKTO_VAR_TARGET_Y}, {-off_y})")

    # Generate unique loop labels
    state.walkto_counter += 1
    n = state.walkto_counter
    prefix = state.label_prefix
    loop_x = f"{prefix}_WalkTo{n}_X"
    step_left = f"{prefix}_WalkTo{n}_StepLeft"
    wait_x = f"{prefix}_WalkTo{n}_WaitX"
    loop_y = f"{prefix}_WalkTo{n}_Y"
    step_up = f"{prefix}_WalkTo{n}_StepUp"
    wait_y = f"{prefix}_WalkTo{n}_WaitY"
    done = f"{prefix}_WalkTo{n}_Done"

    # Emit shared single-step movement blocks (once per file)
    _emit_walkto_step_movements(state, speed_prefix)

    # Step label names depend on speed
    step_r = f"{prefix}_WalkToStep_{speed_prefix}_right"
    step_l = f"{prefix}_WalkToStep_{speed_prefix}_left"
    step_d = f"{prefix}_WalkToStep_{speed_prefix}_down"
    step_u = f"{prefix}_WalkToStep_{speed_prefix}_up"

    # Emit call to loop subroutine
    state.emit(f"call({loop_x})")

    # Register X-axis loop
    state.register_auto_label(loop_x, [
        f"getobjectxy({actor_ref}, CURRENT_POSITION, "
        f"{_WALKTO_VAR_CUR_X}, {_WALKTO_VAR_CUR_Y})",
        f"compare_var_to_var({_WALKTO_VAR_CUR_X}, {_WALKTO_VAR_TARGET_X})",
        f"goto_if_eq({loop_y})",
        f"goto_if_gt({step_left})",
        f"applymovement({actor_ref}, {step_r})",
        f"goto({wait_x})",
    ])

    state.register_auto_label(step_left, [
        f"applymovement({actor_ref}, {step_l})",
        f"goto({wait_x})",
    ])

    state.register_auto_label(wait_x, [
        f"waitmovement({actor_ref})",
        f"goto({loop_x})",
    ])

    # Register Y-axis loop
    state.register_auto_label(loop_y, [
        f"getobjectxy({actor_ref}, CURRENT_POSITION, "
        f"{_WALKTO_VAR_CUR_X}, {_WALKTO_VAR_CUR_Y})",
        f"compare_var_to_var({_WALKTO_VAR_CUR_Y}, {_WALKTO_VAR_TARGET_Y})",
        f"goto_if_eq({done})",
        f"goto_if_gt({step_up})",
        f"applymovement({actor_ref}, {step_d})",
        f"goto({wait_y})",
    ])

    state.register_auto_label(step_up, [
        f"applymovement({actor_ref}, {step_u})",
        f"goto({wait_y})",
    ])

    state.register_auto_label(wait_y, [
        f"waitmovement({actor_ref})",
        f"goto({loop_y})",
    ])

    state.register_auto_label(done, [
        "return",
    ])


def _emit_walkto_step_movements(state, speed_prefix):
    """Emit single-step movement blocks for walkto (shared across calls)."""
    prefix = state.label_prefix
    for direction in ("left", "right", "up", "down"):
        label = f"{prefix}_WalkToStep_{speed_prefix}_{direction}"
        # Check if already emitted (multiple walkto calls share these)
        for existing_label, _ in state.movement_blocks:
            if existing_label == label:
                return  # Already emitted for this speed
    # Emit all four directions for this speed
    for direction in ("left", "right", "up", "down"):
        label = f"{prefix}_WalkToStep_{speed_prefix}_{direction}"
        move_cmd = f"{speed_prefix}_{direction}"
        state.movement_blocks.append((label, [move_cmd]))


def handle_movement_line(line, state):
    """Handle a movement line, possibly with parallel actions (+ separator)."""
    segments = [s.strip() for s in line.split("+")]

    # Reject camera commands in movement lines — camera is its own beat
    for seg in segments:
        seg_tokens = seg.split()
        if seg_tokens and seg_tokens[0] == "camera":
            if len(segments) > 1:
                state.error("camera cannot be combined with '+' parallel movement")
            else:
                state.error("Use 'camera pan/reset' as a standalone command, not as a movement actor")
            return

    # Check for walkto — must be the only segment (can't parallelize)
    for seg in segments:
        tokens = seg.split()
        if len(tokens) >= 2 and tokens[1] in WALKTO_COMMANDS:
            if len(segments) > 1:
                state.error("walkto cannot be combined with '+' parallel movement")
                return
            _compile_walkto(tokens[0], tokens[1:], state)
            return

    results = []

    for seg in segments:
        tokens = seg.split()
        if len(tokens) < 2:
            state.error(f"Movement command too short: '{seg}'")
            continue
        actor = tokens[0]
        action_parts = tokens[1:]
        result = parse_movement_action(actor, action_parts, state)
        if result:
            results.append(result)

    if not results:
        return

    for actor_ref, label, block in results:
        if block:
            state.movement_blocks.append((label, block))
        state.emit(f"applymovement({actor_ref}, {label})")

    if len(results) == 1:
        actor_ref = results[0][0]
        state.emit(f"waitmovement({actor_ref})")
    else:
        # Wait for each actor individually — waitmovement(0) only waits for
        # the most recent applymovement, so parallel movements need per-actor waits
        for actor_ref, label, block in results:
            state.emit(f"waitmovement({actor_ref})")

    # Re-unfreeze Pokemon actors after waitmovement so their autonomous
    # movement type resumes (face/walk commands re-freeze them)
    for actor_ref, label, block in results:
        for pname in state.pokemon_actors:
            if actor_ref == f"LOCALID_{pname.upper()}" and pname not in state.pokemon_hidden:
                _emit_pokemon_unfreeze(state, pname)
                break


def handle_msg(first_line, lines, line_idx, state, msg_type="MSGBOX_DEFAULT"):
    """
    Handle a msg/msgnpc command, including multi-line continuations.
    Returns how many extra lines were consumed.
    """
    # Determine command prefix
    if first_line.startswith("msgnpc"):
        prefix = "msgnpc"
        msg_type = "MSGBOX_NPC"
    else:
        prefix = "msg"

    m = re.match(rf'^{prefix}\s+"(.*)"$', first_line)
    if not m:
        state.error(f"{prefix} must be followed by a quoted string: {prefix} \"text here\"")
        return 0

    text_parts = [m.group(1)]
    consumed = 0

    # Check for continuation lines
    idx = line_idx + 1
    while idx < len(lines):
        next_line = lines[idx].strip()
        if next_line.startswith('"') and next_line.endswith('"'):
            text_parts.append(next_line[1:-1])
            consumed += 1
            idx += 1
        else:
            break

    full_text = "".join(text_parts)

    # Auto-add $ at end if missing
    if not full_text.endswith("$"):
        full_text += "$"

    # In Poryscript, msgbox takes inline string with type
    # Split long text at \p for readability in the .pory source
    # But Poryscript handles it as one string, so we join with line continuation
    pory_strings = []
    segments = re.split(r'(\\\\p)', full_text)
    current = ""
    for seg in segments:
        current += seg
        if seg == "\\\\p":
            pory_strings.append(current)
            current = ""
    if current:
        pory_strings.append(current)

    if len(pory_strings) == 1:
        state.emit(f'msgbox("{full_text}", {msg_type})')
    else:
        # Multi-line for readability
        joined = '"\n           "'.join(pory_strings)
        state.emit(f'msgbox("{joined}", {msg_type})')

    return consumed


# ============================================================
# DIRECTIVE HANDLERS — Top-level (can execute outside a script block)
# ============================================================

def _compile_alias(tokens, stripped, state, lines, i):
    """Handle 'alias name npcN' directive."""
    if len(tokens) < 3:
        state.error("'alias' needs a name and target: alias name npcN")
        return 0
    alias_name = tokens[1]
    target = tokens[2]
    m = re.match(r"^npc(\d+)$", target)
    if m:
        npc_id = int(m.group(1))
        state.aliases[alias_name] = npc_id
        const_name = f"LOCALID_{alias_name.upper()}"
        state.const_lines.append(f"const {const_name} = {npc_id}")
    else:
        state.error(f"Alias target must be npcN format, got '{target}'")
    return 0


def _compile_pokemon(tokens, stripped, state, lines, i):
    """Handle 'pokemon species npcN' — declare a Pokemon actor."""
    if len(tokens) < 3:
        state.error("Usage: pokemon <species> npc<N>")
        return 0
    species_name = tokens[1].lower()
    target = tokens[2]
    m = re.match(r"^npc(\d+)$", target)
    if not m:
        state.error(f"Pokemon target must be npcN format, got '{target}'")
        return 0
    npc_id = int(m.group(1))
    if species_name in state.aliases:
        state.error(f"'{species_name}' is already declared as an alias")
        return 0
    state.aliases[species_name] = npc_id
    state.pokemon_actors[species_name] = {"npc_id": npc_id, "species": species_name}
    const_name = f"LOCALID_{species_name.upper()}"
    state.const_lines.append(f"const {const_name} = {npc_id}")
    return 0


def _compile_mapscripts(tokens, stripped, state, lines, i):
    """Handle 'mapscripts LabelName' directive."""
    if len(tokens) < 2:
        state.error("'mapscripts' needs a label name")
        return 0
    name = tokens[1]
    state.has_mapscripts = True
    state.output_blocks.insert(0, f"mapscripts {name} {{}}")
    return 0


def _compile_page(tokens, stripped, state, lines, i):
    """Handle 'page N [if CONDITION]' — start an NPC page block."""
    if len(tokens) < 2:
        state.error("'page' requires a page number: page N [if CONDITION]")
        return 0

    try:
        page_num = int(tokens[1])
    except ValueError:
        state.error(f"Page number must be an integer, got '{tokens[1]}'")
        return 0

    if page_num < 1:
        state.error(f"Page number must be >= 1, got {page_num}")
        return 0

    # Parse optional condition: page N if CONDITION
    condition = None
    if len(tokens) >= 3 and tokens[2] == "if":
        cond_expr, err = _parse_condition(tokens, start=3, state=state)
        if err:
            state.error(f"page {page_num}: {err}")
            return 0
        condition = cond_expr

    # Validate: page 1 must not have a condition
    if page_num == 1 and condition:
        state.error("Page 1 must be the unconditional default (no 'if' clause)")
        return 0

    # Validate: page 2+ must have a condition
    if page_num > 1 and not condition:
        state.error(f"Page {page_num} requires a condition: page {page_num} if CONDITION")
        return 0

    # Close any open script from a previous page
    if state.current_script:
        state.close_script()

    # Set up the new page
    state.current_page = {
        "page_num": page_num,
        "label": None,       # filled in by label directive
        "condition": condition,
        "hide_targets": [],
    }
    return 0


def _finalize_pages(state):
    """Merge page blocks into single scripts with descending-priority conditionals."""
    for label, pages in state.page_groups.items():
        # Check for duplicate page numbers
        seen_nums = set()
        for pg in pages:
            if pg["page_num"] in seen_nums:
                state.error(f"Duplicate page {pg['page_num']} for script '{label}'")
            seen_nums.add(pg["page_num"])

        # Sort pages by page_num descending (highest priority first)
        sorted_pages = sorted(pages, key=lambda p: p["page_num"], reverse=True)

        body_lines = []
        page_line_data = state.page_lines.get(label, {})

        for pg in sorted_pages:
            pnum = pg["page_num"]
            condition = pg.get("condition")
            hide_targets = pg.get("hide_targets", [])
            page_body = page_line_data.get(pnum, [])

            # Build page content
            content = []
            if hide_targets:
                for target in hide_targets:
                    # Resolve alias to LOCALID_
                    if target in state.aliases:
                        const_name = f"LOCALID_{target.upper()}"
                    elif re.match(r"^npc\d+$", target):
                        const_name = target.replace("npc", "")
                    else:
                        const_name = target
                    content.append(f"removeobject({const_name})")
                if not page_body:
                    # Pure hide page — add releaseall + end
                    content.append("releaseall")
                    content.append("end")
            content.extend(page_body)

            if condition:
                body_lines.append(f"// Page {pnum}")
                body_lines.append(f"if ({condition}) {{")
                for cl in content:
                    body_lines.append(f"    {cl}")
                body_lines.append("}")
            else:
                # Default page (page 1) — no wrapping if
                body_lines.append(f"// Page {pnum} (default)")
                body_lines.extend(content)

        # Assemble the script block
        inner = "\n".join(f"    {l}" if l else "" for l in body_lines)
        block = f"script {label} {{\n{inner}\n}}"
        state.output_blocks.append(block)


def _compile_script_directive(tokens, stripped, state, lines, i):
    """Handle 'script Name' — start a new script block."""
    if len(tokens) < 2:
        state.error("'script' needs a name")
        return 0
    state.open_script(tokens[1])
    return 0


def _compile_label_directive(tokens, stripped, state, lines, i):
    """Handle 'label Name' — start a new script block."""
    if len(tokens) < 2:
        state.error("'label' needs a name")
        return 0
    label_name = tokens[1].rstrip(":")
    # Inside a page block: record the label on the page and set up line collection
    if state.current_page:
        state.current_page["label"] = label_name
        state.page_lines.setdefault(label_name, {}).setdefault(
            state.current_page["page_num"], [])
        # Register page in page_groups
        state.page_groups.setdefault(label_name, []).append(state.current_page)
    state.open_script(label_name)
    return 0


def _compile_text(tokens, stripped, state, lines, i):
    """Handle 'text LabelName "content"' — named text block."""
    m2 = re.match(r'^text\s+(\S+)\s+"(.*)"$', stripped)
    if not m2:
        state.error('Usage: text LabelName "Text content here$"')
        return 0
    text_label = m2.group(1)
    text_content = m2.group(2)
    consumed = 0
    idx = i + 1
    while idx < len(lines):
        next_line = lines[idx].strip()
        if next_line.startswith('"') and next_line.endswith('"'):
            text_content += next_line[1:-1]
            consumed += 1
            idx += 1
        else:
            break
    if not text_content.endswith("$"):
        text_content += "$"
    state.text_blocks.append((text_label, text_content))
    return consumed


def _compile_movement(tokens, stripped, state, lines, i):
    """Handle 'movement LabelName' — named movement block."""
    if len(tokens) < 2:
        state.error("'movement' needs a label name")
        return 0
    move_label = tokens[1]
    move_cmds = []
    brace_match = re.match(r'^movement\s+\S+\s*\{(.+)\}$', stripped)
    if brace_match:
        inner = brace_match.group(1).strip()
        move_cmds = [c.strip() for c in inner.split(",")]
        state.movement_blocks.append((move_label, move_cmds))
        return 0
    idx = i + 1
    consumed = 0
    while idx < len(lines):
        mline = lines[idx].strip()
        if mline == "endmovement":
            consumed += 1
            break
        if mline and not mline.startswith("#"):
            move_cmds.append(mline)
        consumed += 1
        idx += 1
    state.movement_blocks.append((move_label, move_cmds))
    return consumed


# ============================================================
# DIRECTIVE HANDLERS — In-script (require an open script block)
# ============================================================

def _compile_lock(tokens, stripped, state, lines, i):
    state.emit("lockall")
    # Unfreeze Pokemon actors so their autonomous movement resumes
    for name, info in state.pokemon_actors.items():
        if name not in state.pokemon_hidden:
            _emit_pokemon_unfreeze(state, name)
    return 0


def _emit_pokemon_unfreeze(state, actor_name):
    """Emit callnative to unfreeze a Pokemon actor after lock/waitmovement.

    Pokemon actors use MOVEMENT_TYPE_WALK_IN_PLACE_DOWN in map.json for
    autonomous bobbing. lockall freezes them. This emits a callnative to
    ScriptUnfreezePokemonActor which unfreezes a single object event by
    local ID so its movement type resumes.
    """
    const_name = f"LOCALID_{actor_name.upper()}"
    state.emit(f"setvar(VAR_0x8004, {const_name})")
    state.emit("callnative(ScriptUnfreezePokemonActor)")
    state.needs_pokemon_patch = True


def _compile_end(tokens, stripped, state, lines, i):
    state.emit("releaseall")
    state.emit("end")
    return 0


def _compile_release(tokens, stripped, state, lines, i):
    state.emit("release")
    state.emit("end")
    return 0


def _compile_closemessage(tokens, stripped, state, lines, i):
    state.emit("closemessage")
    return 0


def _compile_goto(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'goto' needs a label name")
        return 0
    state.emit(f"goto({tokens[1]})")
    return 0


def _compile_call(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'call' needs a label name")
        return 0
    state.emit(f"call({tokens[1]})")
    return 0


def _compile_return(tokens, stripped, state, lines, i):
    state.emit("return")
    return 0


def _compile_msg(tokens, stripped, state, lines, i):
    return handle_msg(stripped, lines, i, state, "MSGBOX_DEFAULT")


def _compile_msgnpc(tokens, stripped, state, lines, i):
    return handle_msg(stripped, lines, i, state, "MSGBOX_NPC")


_FADE_MAP = {
    "black": "FADE_TO_BLACK",
    "in": "FADE_FROM_BLACK",
    "from black": "FADE_FROM_BLACK",
    "white": "FADE_TO_WHITE",
    "from white": "FADE_FROM_WHITE",
    "in white": "FADE_FROM_WHITE",
}


def _compile_fade(tokens, stripped, state, lines, i):
    rest = " ".join(tokens[1:])
    if rest in _FADE_MAP:
        state.emit(f"fadescreen({_FADE_MAP[rest]})")
    else:
        state.error(f"Unknown fade type '{rest}'")
    return 0


def _compile_sound(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'sound' needs a sound effect name")
        return 0
    state.emit(f"playse({tokens[1]})")
    return 0


def _compile_music(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'music' needs a BGM name")
        return 0
    state.emit(f"playbgm({tokens[1]}, FALSE)")
    return 0


def _compile_fanfare(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'fanfare' needs a fanfare name")
        return 0
    state.emit(f"playfanfare({tokens[1]})")
    state.emit("waitfanfare")
    return 0


_CRY_MODES = {
    "encounter": "CRY_MODE_ENCOUNTER",
    "faint": "CRY_MODE_FAINT",
}

def _compile_cry(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'cry' needs a species constant")
        return 0
    species = tokens[1]
    if len(tokens) >= 3 and tokens[2] in _CRY_MODES:
        state.emit(f"playmoncry({species}, {_CRY_MODES[tokens[2]]})")
    else:
        state.emit(f"playmoncry({species}, CRY_MODE_NORMAL)")
    return 0


def _compile_pause(tokens, stripped, state, lines, i):
    if len(tokens) >= 2 and tokens[1] == "long":
        state.emit("delay(32)")
    elif len(tokens) >= 2:
        try:
            frames = int(tokens[1])
            state.emit(f"delay({frames})")
        except ValueError:
            state.error(f"Unknown pause type '{tokens[1]}'")
    else:
        state.emit("delay(16)")
    return 0


def _compile_flag(tokens, stripped, state, lines, i):
    if len(tokens) < 3:
        state.error("Usage: flag set FLAG_NAME or flag clear FLAG_NAME")
        return 0
    action = tokens[1]
    flag_name = tokens[2]
    # Resolve self-flags: flag set self.talked → setflag(FLAG_SELF_...)
    if flag_name.startswith("self."):
        suffix = flag_name[5:]
        if not suffix:
            state.error("'self.' requires a flag name (e.g. self.talked)")
            return 0
        flag_name = state.resolve_self_flag(suffix)
    if action == "set":
        state.emit(f"setflag({flag_name})")
    elif action == "clear":
        state.emit(f"clearflag({flag_name})")
    else:
        state.error(f"Unknown flag action '{action}'")
    return 0


def _compile_var(tokens, stripped, state, lines, i):
    if len(tokens) < 3:
        state.error("Usage: var VAR_NAME value")
        return 0
    var_name = tokens[1]
    op = tokens[2]
    if op == '=' and len(tokens) >= 4:
        state.emit(f"copyvar({var_name}, {tokens[3]})")
    elif op == '+' and len(tokens) >= 4:
        state.emit(f"addvar({var_name}, {tokens[3]})")
    elif op == '-' and len(tokens) >= 4:
        state.emit(f"subvar({var_name}, {tokens[3]})")
    else:
        state.emit(f"setvar({var_name}, {op})")
    return 0


def _compile_hide(tokens, stripped, state, lines, i):
    cmd = tokens[0]
    if len(tokens) < 2:
        state.error(f"'{cmd}' needs an actor name")
        return 0
    actor_name = tokens[1]
    actor_ref = resolve_actor(actor_name, state)
    # hide actor MAP_NAME → hideobjectat(actor, MAP)
    if len(tokens) >= 3 and tokens[2].startswith("MAP_"):
        state.emit(f"hideobjectat({actor_ref}, {tokens[2]})")
        return 0
    # Clear held movement before hiding Pokemon actors
    if actor_name in state.pokemon_actors:
        state.emit(f"waitmovement({actor_ref})")
        state.pokemon_hidden.add(actor_name)
    state.emit(f"removeobject({actor_ref})")
    return 0


def _compile_show(tokens, stripped, state, lines, i):
    cmd = tokens[0]
    if len(tokens) < 2:
        state.error(f"'{cmd}' needs an actor name")
        return 0
    actor_name = tokens[1]
    actor_ref = resolve_actor(actor_name, state)
    # show actor MAP_NAME → showobjectat(actor, MAP)
    if len(tokens) >= 3 and tokens[2].startswith("MAP_"):
        state.emit(f"showobjectat({actor_ref}, {tokens[2]})")
        return 0
    state.emit(f"addobject({actor_ref})")
    # Unfreeze shown Pokemon actors so their autonomous movement resumes
    if actor_name in state.pokemon_actors:
        state.pokemon_hidden.discard(actor_name)
        _emit_pokemon_unfreeze(state, actor_name)
    return 0


def _compile_faint(tokens, stripped, state, lines, i):
    """Handle 'faint actor' — stop Pokemon idle animation (fainted state)."""
    if len(tokens) < 2:
        state.error("'faint' needs a Pokemon actor name")
        return 0
    actor_name = tokens[1]
    if actor_name not in state.pokemon_actors:
        state.error(f"'{actor_name}' is not a Pokemon actor (use 'pokemon {actor_name} npcN')")
        return 0
    actor_ref = resolve_actor(actor_name, state)
    # Face down and mark hidden (no unfreeze — stay frozen)
    state.emit(f"applymovement({actor_ref}, Common_Movement_FaceDown)")
    state.emit(f"waitmovement({actor_ref})")
    state.pokemon_hidden.add(actor_name)
    return 0


def _compile_revive(tokens, stripped, state, lines, i):
    """Handle 'revive actor' — restart Pokemon idle animation."""
    if len(tokens) < 2:
        state.error("'revive' needs a Pokemon actor name")
        return 0
    actor_name = tokens[1]
    if actor_name not in state.pokemon_actors:
        state.error(f"'{actor_name}' is not a Pokemon actor (use 'pokemon {actor_name} npcN')")
        return 0
    state.pokemon_hidden.discard(actor_name)
    _emit_pokemon_unfreeze(state, actor_name)
    return 0


def _compile_setpos(tokens, stripped, state, lines, i):
    if len(tokens) < 3:
        state.error("Usage: setpos actor x y | setpos actor perm")
        return 0
    actor_ref = resolve_actor(tokens[1], state)
    if tokens[2] == "perm":
        state.emit(f"copyobjectxytoperm({actor_ref})")
        return 0
    if len(tokens) < 4:
        state.error("Usage: setpos actor x y | setpos actor perm")
        return 0
    state.emit(f"setobjectxy({actor_ref}, {tokens[2]}, {tokens[3]})")
    return 0


def _compile_shake(tokens, stripped, state, lines, i):
    if len(tokens) < 3:
        state.error("Usage: shake intensity count")
        return 0
    state.emit(f"setvar(VAR_0x8004, {tokens[1]})")
    state.emit(f"setvar(VAR_0x8005, {tokens[2]})")
    state.emit("special(ShakeCamera)")
    return 0


_CAMERA_DIR_OFFSET = {
    "down": (0, 1), "up": (0, -1),
    "right": (1, 0), "left": (-1, 0),
}


def _camera_emit_reset(state, offset_x, offset_y):
    """Emit the callnative sequence to undo a camera pan offset."""
    if offset_x == 0 and offset_y == 0:
        return
    # Convert signed offset to u16 for setvar (C casts back to s16)
    def _u16(val):
        if val < 0:
            return f"0x{val & 0xFFFF:04X}"
        return str(val)
    state.emit(f"setvar(VAR_0x8004, {_u16(offset_x)})")
    state.emit(f"setvar(VAR_0x8005, {_u16(offset_y)})")
    state.emit("callnative(ScriptResetCameraOffset)")
    state.needs_camera_patch = True


def _compile_camera(tokens, stripped, state, lines, i):
    """Compile camera pan/reset/follow commands."""
    if len(tokens) < 2:
        state.error("Usage: camera pan <direction> <tiles> | camera reset | camera follow <target>")
        return 0
    action = tokens[1]

    if action == "pan":
        if len(tokens) < 4:
            state.error("Usage: camera pan <direction> <tiles>")
            return 0
        direction = tokens[2]
        if direction not in DIRECTIONS:
            state.error(f"Unknown camera pan direction '{direction}'")
            return 0
        try:
            count = int(tokens[3])
        except ValueError:
            state.error(f"Camera pan tile count must be a number, got '{tokens[3]}'")
            return 0
        # Accumulate offset for reset correction
        dx, dy = _CAMERA_DIR_OFFSET[direction]
        state.camera_offset_x += dx * count
        state.camera_offset_y += dy * count
        # Auto-spawn camera object if not yet spawned in this script
        if not state.camera_spawned:
            state.emit("special(SpawnCameraObject)")
            state.camera_spawned = True
        # Generate movement block for the camera pan
        move_cmd = f"walk_{direction}"
        label = state.next_move_label()
        block = [f"{move_cmd} * {count}" if count > 1 else move_cmd]
        state.movement_blocks.append((label, block))
        state.emit(f"applymovement(OBJ_EVENT_ID_CAMERA, {label})")
        state.emit("waitmovement(OBJ_EVENT_ID_CAMERA)")
        return 0

    if action == "reset":
        # Always emit RemoveCameraObject — camera state can carry across
        # goto boundaries, so the compiler can't know if one is active.
        # RemoveCameraObject is a no-op at the engine level when no camera exists.
        state.emit("special(RemoveCameraObject)")
        state.camera_spawned = False

        if len(tokens) == 2:
            # Bare "camera reset" — use accumulated offsets
            _camera_emit_reset(state, state.camera_offset_x, state.camera_offset_y)
            state.camera_offset_x = 0
            state.camera_offset_y = 0
        elif len(tokens) >= 5 and tokens[2] == "warp":
            # "camera reset warp MAP X Y" — explicit warp to coordinates
            map_const = tokens[2 + 1]  # MAP_*
            warp_x = tokens[2 + 2]
            warp_y = tokens[2 + 3]
            state.emit(f"warpsilent({map_const}, WARP_ID_NONE, {warp_x}, {warp_y})")
            state.emit("waitstate")
            state.camera_offset_x = 0
            state.camera_offset_y = 0
        elif len(tokens) == 4:
            # "camera reset <offset_x> <offset_y>" — manual offset for cross-label
            try:
                manual_x = int(tokens[2])
                manual_y = int(tokens[3])
            except ValueError:
                state.error("Usage: camera reset <offset_x> <offset_y> (integers)")
                return 0
            _camera_emit_reset(state, manual_x, manual_y)
            state.camera_offset_x = 0
            state.camera_offset_y = 0
        else:
            state.error("Usage: camera reset | camera reset warp MAP X Y | camera reset <offset_x> <offset_y>")
        return 0

    if action == "follow":
        state.error("'camera follow' is not yet supported — use 'camera pan' to move the camera manually")
        return 0

    state.error(f"Unknown camera action '{action}'. Use: pan, reset")
    return 0


def _compile_faceplayer(tokens, stripped, state, lines, i):
    state.emit("faceplayer")
    return 0


def _compile_special(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'special' needs a function name")
        return 0
    if len(tokens) >= 3:
        # special Func VAR → specialvar(VAR, Func)
        state.emit(f"specialvar({tokens[2]}, {tokens[1]})")
    else:
        state.emit(f"special({tokens[1]})")
    return 0


def _compile_waitstate(tokens, stripped, state, lines, i):
    state.emit("waitstate")
    return 0


def _compile_gotoif(tokens, stripped, state, lines, i):
    if len(tokens) < 3:
        state.error("Usage: gotoif FLAG_NAME LabelName")
        return 0
    state.emit(f"if (flag({tokens[1]})) {{")
    state.emit(f"    goto({tokens[2]})")
    state.emit("}")
    return 0


# ============================================================
# CONDITION PARSER — shared by if/elif/gotoif
# ============================================================

_COMPARISON_OPS = {"==", "!=", ">", "<", ">=", "<="}


def _parse_condition(tokens, start=0, state=None):
    """Parse a TorScript condition into a Poryscript expression.

    Supported forms:
      FLAG_X               -> flag(FLAG_X)
      not FLAG_X           -> !flag(FLAG_X)
      VAR_X op value       -> var(VAR_X) op value
      not VAR_X op value   -> !(var(VAR_X) op value)
      defeated TRAINER_X   -> defeated(TRAINER_X)
      self.NAME            -> flag(FLAG_SELF_...)
      A and B              -> A && B
      A or B               -> A || B

    Returns (pory_condition_string, error_or_None).
    """
    parts = list(tokens[start:])
    if not parts:
        return None, "Empty condition"

    # Split on 'and' / 'or' for compound conditions
    # Find the top-level logic operator (not inside sub-conditions)
    logic_op = None
    split_idx = None
    for idx, tok in enumerate(parts):
        if tok in ("and", "or") and idx > 0:
            logic_op = tok
            split_idx = idx
            break

    if logic_op:
        left_tokens = parts[:split_idx]
        right_tokens = parts[split_idx + 1:]
        left_expr, left_err = _parse_single_condition(left_tokens, state=state)
        if left_err:
            return None, left_err
        right_expr, right_err = _parse_condition(right_tokens, state=state)
        if right_err:
            return None, right_err
        joiner = "&&" if logic_op == "and" else "||"
        return f"{left_expr} {joiner} {right_expr}", None

    return _parse_single_condition(parts, state=state)


def _parse_single_condition(parts, state=None):
    """Parse a single (non-compound) condition.

    Returns (pory_expr, error_or_None).
    """
    if not parts:
        return None, "Empty condition"

    negated = False
    if parts[0] == "not":
        negated = True
        parts = parts[1:]
        if not parts:
            return None, "'not' requires a flag or variable"

    # self.NAME — per-NPC self-flag
    if parts[0].startswith("self."):
        suffix = parts[0][5:]
        if not suffix:
            return None, "'self.' requires a flag name (e.g. self.talked)"
        if not state:
            return None, "self-flags require a compiler context"
        flag_name = state.resolve_self_flag(suffix)
        expr = f"flag({flag_name})"
        if negated:
            expr = f"!{expr}"
        return expr, None

    # defeated TRAINER_X
    if parts[0] == "defeated":
        if len(parts) < 2:
            return None, "'defeated' requires a trainer ID"
        expr = f"defeated({parts[1]})"
        if negated:
            expr = f"!{expr}"
        return expr, None

    name = parts[0]

    # VAR_X op value
    if name.startswith("VAR_") and len(parts) >= 3 and parts[1] in _COMPARISON_OPS:
        op = parts[1]
        value = parts[2]
        expr = f"var({name}) {op} {value}"
        if negated:
            expr = f"!({expr})"
        return expr, None

    # FLAG_X (boolean)
    if name.startswith("FLAG_"):
        expr = f"flag({name})"
        if negated:
            expr = f"!{expr}"
        return expr, None

    # Bare VAR_X without operator — treat as != 0 (truthiness)
    if name.startswith("VAR_"):
        expr = f"var({name})"
        if negated:
            expr = f"!{expr}"
        return expr, None

    return None, f"Cannot parse condition: '{' '.join(parts)}'"


# ============================================================
# IF / ELIF / ELSE / ENDIF
# ============================================================

def _compile_if(tokens, stripped, state, lines, i):
    cond_expr, err = _parse_condition(tokens, start=1, state=state)
    if err:
        state.error(f"if: {err}")
        return 0
    state.emit(f"if ({cond_expr}) {{")
    state.if_depth += 1
    return 0


def _compile_elif(tokens, stripped, state, lines, i):
    if state.if_depth <= 0:
        state.error("'elif' without matching 'if'")
        return 0
    cond_expr, err = _parse_condition(tokens, start=1, state=state)
    if err:
        state.error(f"elif: {err}")
        return 0
    state.emit(f"}} elif ({cond_expr}) {{")
    return 0


def _compile_else(tokens, stripped, state, lines, i):
    if state.if_depth <= 0:
        state.error("'else' without matching 'if'")
        return 0
    state.emit("} else {")
    return 0


def _compile_endif(tokens, stripped, state, lines, i):
    if state.if_depth <= 0:
        state.error("'endif' without matching 'if'")
        return 0
    state.emit("}")
    state.if_depth -= 1
    return 0


# ============================================================
# SWITCH / CASE / ENDSWITCH
# ============================================================

def _compile_switch(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("Usage: switch VAR_NAME")
        return 0
    var_name = tokens[1]
    if not var_name.startswith("VAR_"):
        state.error(f"switch requires a VAR_* name, got '{var_name}'")
        return 0
    state.emit(f"switch (var({var_name})) {{")
    state.switch_depth += 1
    return 0


def _compile_case(tokens, stripped, state, lines, i):
    if state.switch_depth <= 0:
        state.error("'case' without matching 'switch'")
        return 0
    if len(tokens) < 2:
        state.error("Usage: case value")
        return 0
    state.emit(f"    case {tokens[1]}:")
    return 0


def _compile_default(tokens, stripped, state, lines, i):
    if state.switch_depth <= 0:
        state.error("'default' without matching 'switch'")
        return 0
    state.emit("    default:")
    return 0


def _compile_endswitch(tokens, stripped, state, lines, i):
    if state.switch_depth <= 0:
        state.error("'endswitch' without matching 'switch'")
        return 0
    state.emit("}")
    state.switch_depth -= 1
    return 0


# ============================================================
# CHOICE / OPTION / ENDCHOICE
# ============================================================

def _compile_choice(tokens, stripped, state, lines, i):
    # Extract prompt text (everything after "choice")
    prompt = stripped[7:].strip().strip('"').rstrip('"')
    if not prompt:
        state.error("Usage: choice \"prompt text\"")
        return 0
    # Ensure $ terminator
    if not prompt.endswith("$"):
        prompt += "$"
    state.choice_prompt = prompt
    state.choice_options = []
    return 0


def _compile_option(tokens, stripped, state, lines, i):
    if not state.choice_prompt:
        state.error("'option' without matching 'choice'")
        return 0
    # Extract option text
    opt_text = stripped[7:].strip().strip('"').rstrip('"')
    if not opt_text:
        state.error("Usage: option \"option text\"")
        return 0
    state.choice_options.append(opt_text)
    return 0


def _compile_endchoice(tokens, stripped, state, lines, i):
    if not state.choice_prompt:
        state.error("'endchoice' without matching 'choice'")
        return 0

    opts = state.choice_options
    prompt = state.choice_prompt

    if len(opts) < 2:
        state.error("choice requires at least 2 options")
        state.choice_prompt = ""
        state.choice_options = []
        return 0

    if len(opts) == 2:
        # Use MSGBOX_YESNO — works on all versions
        state.emit(f'msgbox("{prompt}", MSGBOX_YESNO)')
        state.emit("if (var(VAR_RESULT) == YES) {")
        # First option = YES branch, will be filled by content between
        # For now, emit a comment showing which option this is
        state.emit(f'    // Option: {opts[0]}')
        state.emit("} else {")
        state.emit(f'    // Option: {opts[1]}')
        state.emit("}")
    else:
        # Use dynmultichoice (expansion v1.9.0+)
        # Build the option string: dynmultichoice(x, y, ignoreBPress, maxPerRow, "opt1", "opt2", ...)
        opt_args = ", ".join(f'"{o}"' for o in opts)
        state.emit(f'msgbox("{prompt}", MSGBOX_DEFAULT)')
        state.emit(f"dynmultichoice(0, 0, TRUE, 2, {opt_args})")
        state.emit("switch (var(VAR_RESULT)) {")
        for idx, opt in enumerate(opts):
            state.emit(f"    case {idx}:")
            state.emit(f"        // Option: {opt}")
        state.emit("}")

    state.choice_prompt = ""
    state.choice_options = []
    return 0


# ============================================================
# CHECK (item, partysize, money, badge)
# ============================================================

_CHECK_COMMANDS = {
    "item": lambda arg: f"checkitem({arg})",
    "itemspace": lambda arg: f"checkitemspace({arg})",
    "partysize": lambda arg: "getpartysize",
    "money": lambda arg: f"checkmoney({arg})",
    "badge": lambda arg: f"checkbadge({arg})",
    "gender": lambda arg: "checkplayergender",
}


def _compile_check(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("Usage: check item|itemspace|partysize|money|badge|gender [argument]")
        return 0
    check_type = tokens[1]
    if check_type not in _CHECK_COMMANDS:
        state.error(f"Unknown check type '{check_type}'. Use: item, itemspace, partysize, money, badge, gender")
        return 0
    arg = tokens[2] if len(tokens) >= 3 else ""
    if check_type not in ("partysize", "gender") and not arg:
        state.error(f"'check {check_type}' requires an argument")
        return 0
    state.emit(_CHECK_COMMANDS[check_type](arg))
    return 0


_TRAINERBATTLE_MACROS = {
    "trainerbattle_single",
    "trainerbattle_double",
    "trainerbattle_rematch",
    "trainerbattle_rematch_double",
    "trainerbattle_no_intro",
    "trainerbattle_two_trainers",
}


def _compile_trainerbattle(tokens, stripped, state, lines, i):
    """Compile any trainerbattle_* macro.

    Supports two forms:
    1. Legacy single-line: trainerbattle_single TRAINER_X, IntroLabel, DefeatedLabel
       → pass through to Poryscript as-is
    2. Expanded multi-line with inline text:
       trainerbattle_single TRAINER_X
         intro "text$"
         defeated "text$"
         postbattle "text$"
       → generate text labels, emit trainerbattle + msgbox
    """
    macro = tokens[0]
    args = stripped[len(macro):].strip()

    # Check for expanded form: look ahead for indented intro/defeated/postbattle
    texts = {}
    extra = 0
    j = i + 1
    while j < len(lines):
        sub = lines[j].strip()
        if not sub:
            j += 1
            extra += 1
            continue
        m = re.match(r'^(intro|defeated|postbattle)\s+"(.*)"$', sub)
        if m:
            field, text = m.group(1), m.group(2)
            texts[field] = text
            j += 1
            extra += 1
        else:
            break

    if texts:
        # Expanded form — generate text labels and battle command
        trainer_const = args.split(",")[0].strip() if args else macro
        # Derive label base from trainer const (TRAINER_PETE → Pete)
        label_base = trainer_const.replace("TRAINER_", "").title().replace("_", "")
        prefix = state.label_prefix  # e.g. "Route103"

        text_labels = []
        for field in ("intro", "defeated"):
            if field in texts:
                lbl = f"{prefix}_Text_{label_base}{field.title()}"
                t = texts[field]
                if not t.endswith("$"):
                    t += "$"
                state.text_blocks.append((lbl, t))
                text_labels.append(lbl)
            else:
                text_labels.append(f"{prefix}_Text_{label_base}{field.title()}")

        # Emit trainerbattle with generated text labels
        tb_args = f"{trainer_const}, {', '.join(text_labels)}"
        state.emit(f"{macro}({tb_args})")

        # Emit post-battle msgbox if provided
        if "postbattle" in texts:
            t = texts["postbattle"]
            if not t.endswith("$"):
                t += "$"
            state.emit(f'msgbox("{t}", MSGBOX_AUTOCLOSE)')
    else:
        # Legacy single-line form — pass through
        state.emit(f"{macro}({args})")

    # Battles destroy dynamically-spawned objects (including the camera object).
    # Clear the flag so a subsequent camera pan will re-spawn it.
    # Do NOT reset camera offsets — the position shift persists through battles.
    state.camera_spawned = False
    return extra


def _compile_follower(tokens, stripped, state, lines, i):
    """Compile follower beat to expansion macros."""
    action = tokens[1] if len(tokens) >= 2 else "add"

    if action == "add" and len(tokens) >= 5:
        source = tokens[2]  # "local" or "dynamic"
        if source == "local":
            # follower add local LOCALID_X PARTNER_Y [FLAGS]
            local_id = tokens[3]
            partner = tokens[4]
            flags = tokens[5] if len(tokens) >= 6 else "FNPC_ALL"
            state.emit(f"setfollowernpc({local_id}, {flags}, 0, {partner})")
        elif source == "dynamic":
            # follower add dynamic OBJ_EVENT_GFX_X PARTNER_Y [FLAGS]
            gfx = tokens[3]
            partner = tokens[4]
            flags = tokens[5] if len(tokens) >= 6 else "FNPC_ALL"
            state.emit(f"createfollowernpc({gfx}, {flags}, 0, {partner})")
        else:
            state.error(f"follower add: unknown source '{source}' (expected 'local' or 'dynamic')")
    elif action == "remove":
        state.emit("destroyfollowernpc")
    elif action == "face":
        state.emit("facefollowernpc")
    elif action == "hide":
        if len(tokens) >= 3:
            speed = tokens[2]
            state.emit(f"hidefollowernpc({speed})")
        else:
            state.emit("hidefollowernpc")
    elif action == "check":
        state.emit("checkfollowernpc")
    elif action == "change" and len(tokens) >= 3:
        partner = tokens[2]
        state.emit(f"changefollowerbattler({partner})")
    else:
        state.error(f"follower: unknown action '{action}'")
    return 0


def _compile_multi(tokens, stripped, state, lines, i):
    """Compile multi beat to expansion macros."""
    variant = tokens[1] if len(tokens) >= 2 else "2v2"

    if variant == "2v2" and len(tokens) >= 7:
        # multi 2v2 TRAINER_A TextA TRAINER_B TextB PARTNER_X
        state.emit(f"multi_2_vs_2({tokens[2]}, {tokens[3]}, {tokens[4]}, {tokens[5]}, {tokens[6]})")
    elif variant == "2v1" and len(tokens) >= 5:
        # multi 2v1 TRAINER_A TextA PARTNER_X
        state.emit(f"multi_2_vs_1({tokens[2]}, {tokens[3]}, {tokens[4]})")
    elif variant == "2v2_fixed" and len(tokens) >= 7:
        state.emit(f"multi_fixed_2_vs_2({tokens[2]}, {tokens[3]}, {tokens[4]}, {tokens[5]}, {tokens[6]})")
    elif variant == "2v1_fixed" and len(tokens) >= 5:
        state.emit(f"multi_fixed_2_vs_1({tokens[2]}, {tokens[3]}, {tokens[4]})")
    else:
        state.error(f"multi: insufficient arguments for variant '{variant}'")
    return 0


def _compile_give(tokens, stripped, state, lines, i):
    """Compile give beat -- giveitem with bag-full safety check."""
    if len(tokens) < 2 or not tokens[1]:
        state.error("give requires an item name (e.g. give ITEM_POTION)")
        return 0
    item = tokens[1]
    qty = tokens[2] if len(tokens) >= 3 else "1"
    if qty != "1":
        state.emit(f"giveitem({item}, {qty})")
    else:
        state.emit(f"giveitem({item})")
    # Bag-full check
    bag_label = f"{state.label_prefix}_BagFull"
    state.emit("compare(VAR_RESULT, FALSE)")
    state.emit(f"goto_if_eq({bag_label})")
    state.register_auto_label(bag_label, [
        'msgbox(format("Your bag is too full!"), MSGBOX_DEFAULT)',
        "release",
        "end",
    ])
    return 0


def _compile_raw(tokens, stripped, state, lines, i):
    raw_content = stripped[4:].strip()
    state.emit(raw_content)
    return 0


def _compile_pory(tokens, stripped, state, lines, i):
    pory_content = stripped[5:].strip()
    state.emit(pory_content)
    return 0


# ============================================================
# WAIT / SYNC COMMANDS
# ============================================================

def _compile_waitmessage(tokens, stripped, state, lines, i):
    state.emit("waitmessage")
    return 0

def _compile_waitbutton(tokens, stripped, state, lines, i):
    state.emit("waitbuttonpress")
    return 0

def _compile_waitse(tokens, stripped, state, lines, i):
    state.emit("waitse")
    return 0

def _compile_waitmoncry(tokens, stripped, state, lines, i):
    state.emit("waitmoncry")
    return 0

def _compile_waitfanfare(tokens, stripped, state, lines, i):
    state.emit("waitfanfare")
    return 0

def _compile_getpos(tokens, stripped, state, lines, i):
    if len(tokens) < 4:
        state.error("Usage: getpos player|actor VAR_X VAR_Y")
        return 0
    target = tokens[1]
    var_x = tokens[2]
    var_y = tokens[3]
    if target == "player":
        state.emit(f"getplayerxy({var_x}, {var_y})")
    else:
        actor_ref = resolve_actor(target, state)
        state.emit(f"getobjectxy({actor_ref}, {var_x}, {var_y})")
    return 0


# ============================================================
# MESSAGE (raw, no box type)
# ============================================================

def _compile_message(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'message' needs a text label")
        return 0
    state.emit(f"message({tokens[1]})")
    return 0


# ============================================================
# WILDBATTLE
# ============================================================

def _compile_wildbattle(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("Usage: wildbattle SPECIES LEVEL or wildbattle start")
        return 0
    if tokens[1] == "start":
        state.emit("dowildbattle")
    elif len(tokens) >= 3:
        species = tokens[1]
        level = tokens[2]
        if len(tokens) >= 4:
            item = tokens[3]
            state.emit(f"setwildbattle({species}, {level}, {item})")
        else:
            state.emit(f"setwildbattle({species}, {level})")
    else:
        state.error("Usage: wildbattle SPECIES LEVEL [ITEM] or wildbattle start")
    return 0


# ============================================================
# TAKE (removeitem)
# ============================================================

def _compile_take(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'take' requires an item name (e.g. take ITEM_POTION)")
        return 0
    item = tokens[1]
    qty = tokens[2] if len(tokens) >= 3 else "1"
    if qty != "1":
        state.emit(f"removeitem({item}, {qty})")
    else:
        state.emit(f"removeitem({item})")
    return 0


# ============================================================
# RANDOM
# ============================================================

def _compile_random(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'random' needs a max value (e.g. random 5)")
        return 0
    state.emit(f"random({tokens[1]})")
    return 0


# ============================================================
# SHOP (pokemart)
# ============================================================

def _compile_shop(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'shop' needs a mart list label")
        return 0
    label = tokens[1]
    if len(tokens) >= 3 and tokens[2] == "decoration":
        state.emit(f"pokemartdecoration({label})")
    else:
        state.emit(f"pokemart({label})")
    return 0


# ============================================================
# BRAILLE
# ============================================================

def _compile_braille(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'braille' needs a text label")
        return 0
    state.emit(f"braillemsgbox({tokens[1]})")
    return 0


# ============================================================
# SHOWMON / HIDEMON
# ============================================================

def _compile_showmon(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'showmon' needs a species constant")
        return 0
    species = tokens[1]
    x = tokens[2] if len(tokens) >= 3 else "10"
    y = tokens[3] if len(tokens) >= 4 else "3"
    state.emit(f"showmonpic({species}, {x}, {y})")
    return 0

def _compile_hidemon(tokens, stripped, state, lines, i):
    state.emit("hidemonpic")
    return 0


# ============================================================
# SHOWMONEY / SHOWCOINS
# ============================================================

def _compile_showmoney(tokens, stripped, state, lines, i):
    x = tokens[1] if len(tokens) >= 2 else "0"
    y = tokens[2] if len(tokens) >= 3 else "0"
    state.emit(f"showmoneybox({x}, {y})")
    return 0

def _compile_showcoins(tokens, stripped, state, lines, i):
    x = tokens[1] if len(tokens) >= 2 else "0"
    y = tokens[2] if len(tokens) >= 3 else "0"
    state.emit(f"showcoinsbox({x}, {y})")
    return 0


# ============================================================
# BUFFER
# ============================================================

_BUFFER_COMMANDS = {
    "species": lambda slot, arg: f"bufferspeciesname({slot}, {arg})",
    "item": lambda slot, arg: f"bufferitemname({slot}, {arg})",
    "move": lambda slot, arg: f"buffermovename({slot}, {arg})",
    "number": lambda slot, arg: f"buffernumberstring({slot}, {arg})",
    "leadmon": lambda slot, arg: f"bufferleadmonspeciesname({slot})",
    "string": lambda slot, arg: f"bufferstring({slot}, {arg})",
}

def _compile_buffer(tokens, stripped, state, lines, i):
    if len(tokens) < 3:
        state.error("Usage: buffer N species|item|move|number|leadmon|string ARG")
        return 0
    slot_num = tokens[1]
    slot = f"STR_VAR_{slot_num}" if slot_num.isdigit() else slot_num
    buf_type = tokens[2]
    if buf_type not in _BUFFER_COMMANDS:
        state.error(f"Unknown buffer type '{buf_type}'. Use: species, item, move, number, leadmon, string")
        return 0
    arg = tokens[3] if len(tokens) >= 4 else ""
    if buf_type != "leadmon" and not arg:
        state.error(f"'buffer {slot_num} {buf_type}' requires an argument")
        return 0
    state.emit(_BUFFER_COMMANDS[buf_type](slot, arg))
    return 0


# ============================================================
# TILE (setmetatile)
# ============================================================

def _compile_tile(tokens, stripped, state, lines, i):
    if len(tokens) < 5:
        state.error("Usage: tile X Y METATILE_ID COLLISION")
        return 0
    state.emit(f"setmetatile({tokens[1]}, {tokens[2]}, {tokens[3]}, {tokens[4]})")
    return 0


# ============================================================
# DOOR (opendoor/closedoor/waitdooranim)
# ============================================================

def _compile_door(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("Usage: door open|close|wait [X Y]")
        return 0
    action = tokens[1]
    if action == "wait":
        state.emit("waitdooranim")
    elif action in ("open", "close"):
        if len(tokens) < 4:
            state.error(f"'door {action}' needs X Y coordinates")
            return 0
        cmd = "opendoor" if action == "open" else "closedoor"
        state.emit(f"{cmd}({tokens[2]}, {tokens[3]})")
    else:
        state.error(f"Unknown door action '{action}'. Use: open, close, wait")
    return 0


# ============================================================
# STAT (incrementgamestat)
# ============================================================

def _compile_stat(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'stat' needs a stat name")
        return 0
    state.emit(f"incrementgamestat({tokens[1]})")
    return 0


# ============================================================
# SLOTS (playslotmachine)
# ============================================================

def _compile_slots(tokens, stripped, state, lines, i):
    if len(tokens) < 2:
        state.error("'slots' needs a machine ID variable")
        return 0
    state.emit(f"playslotmachine({tokens[1]})")
    return 0


# ============================================================
# DISPATCH TABLES
# ============================================================

# Top-level directive table (can execute outside a script block)
_TOPLEVEL_HANDLERS = {
    "alias": _compile_alias,
    "pokemon": _compile_pokemon,
    "mapscripts": _compile_mapscripts,
    "page": _compile_page,
    "script": _compile_script_directive,
    "label": _compile_label_directive,
    "text": _compile_text,
    "movement": _compile_movement,
}

# In-script directive table (requires an open script block)
_INSCRIPT_HANDLERS = {
    "lock": _compile_lock,
    "end": _compile_end,
    "release": _compile_release,
    "closemessage": _compile_closemessage,
    "goto": _compile_goto,
    "call": _compile_call,
    "return": _compile_return,
    "msg": _compile_msg,
    "msgnpc": _compile_msgnpc,
    "fade": _compile_fade,
    "sound": _compile_sound,
    "music": _compile_music,
    "fanfare": _compile_fanfare,
    "cry": _compile_cry,
    "pause": _compile_pause,
    "flag": _compile_flag,
    "var": _compile_var,
    "hide": _compile_hide,
    "remove": _compile_hide,
    "show": _compile_show,
    "add": _compile_show,
    "faint": _compile_faint,
    "revive": _compile_revive,
    "setpos": _compile_setpos,
    "shake": _compile_shake,
    "camera": _compile_camera,
    "faceplayer": _compile_faceplayer,
    "special": _compile_special,
    "waitstate": _compile_waitstate,
    "gotoif": _compile_gotoif,
    "if": _compile_if,
    "elif": _compile_elif,
    "else": _compile_else,
    "endif": _compile_endif,
    "switch": _compile_switch,
    "case": _compile_case,
    "default": _compile_default,
    "endswitch": _compile_endswitch,
    "choice": _compile_choice,
    "option": _compile_option,
    "endchoice": _compile_endchoice,
    "check": _compile_check,
    "trainerbattle_single": _compile_trainerbattle,
    "trainerbattle_double": _compile_trainerbattle,
    "trainerbattle_rematch": _compile_trainerbattle,
    "trainerbattle_rematch_double": _compile_trainerbattle,
    "trainerbattle_no_intro": _compile_trainerbattle,
    "trainerbattle_two_trainers": _compile_trainerbattle,
    "raw": _compile_raw,
    "pory": _compile_pory,
    "follower": _compile_follower,
    "multi": _compile_multi,
    "give": _compile_give,
    "waitmessage": _compile_waitmessage,
    "waitbutton": _compile_waitbutton,
    "waitse": _compile_waitse,
    "waitmoncry": _compile_waitmoncry,
    "waitfanfare": _compile_waitfanfare,
    "getpos": _compile_getpos,
    "message": _compile_message,
    "wildbattle": _compile_wildbattle,
    "take": _compile_take,
    "random": _compile_random,
    "shop": _compile_shop,
    "braille": _compile_braille,
    "showmon": _compile_showmon,
    "hidemon": _compile_hidemon,
    "showmoney": _compile_showmoney,
    "showcoins": _compile_showcoins,
    "buffer": _compile_buffer,
    "tile": _compile_tile,
    "door": _compile_door,
    "stat": _compile_stat,
    "slots": _compile_slots,
}


# ============================================================
# MAIN COMPILER
# ============================================================

def _dispatch_inscript(cmd, tokens, stripped, state, lines, i):
    """Dispatch an in-script directive. Returns extra lines consumed."""
    # Comment pass-through
    if cmd.startswith("//") or cmd.startswith("@"):
        state.emit(f"// {stripped.lstrip('/@').strip()}")
        return 0

    # In-script directives
    if cmd in _INSCRIPT_HANDLERS:
        return _INSCRIPT_HANDLERS[cmd](tokens, stripped, state, lines, i)

    # Actor-first movement
    if cmd == "player" or cmd in state.aliases or re.match(r"^npc\d+$", cmd):
        handle_movement_line(stripped, state)
        return 0

    state.error(f"Unknown command '{cmd}'")
    return 0


def compile_script(input_path, label_prefix, emotes_conf, map_id=None,
                    game_path=None, map_name=None):
    """Main compilation function. Returns the generated .pory content."""
    state = CompilerState(label_prefix, map_id=map_id, game_path=game_path,
                          map_name=map_name)
    state.emotes = load_emotes(emotes_conf)

    with open(input_path, "r") as f:
        raw_lines = f.readlines()

    lines = [l.rstrip("\n") for l in raw_lines]

    i = 0
    while i < len(lines):
        state.current_line_num = i + 1
        line = lines[i]
        stripped = line.strip()

        # Skip blank lines and comments
        if not stripped or stripped.startswith("#"):
            if not stripped and state.current_script:
                state.emit_blank()
            i += 1
            continue

        tokens = stripped.split()
        cmd = tokens[0]

        # Page-level hide: between 'page N' and 'label', captures hide targets
        if state.current_page and not state.current_page.get("label") and cmd in ("hide", "remove"):
            if len(tokens) >= 2:
                state.current_page["hide_targets"].append(tokens[1])
            else:
                state.error(f"'{cmd}' needs an actor name")
            i += 1
            continue

        # Top-level directives
        if cmd in _TOPLEVEL_HANDLERS:
            consumed = _TOPLEVEL_HANDLERS[cmd](tokens, stripped, state, lines, i)
            i += 1 + consumed
            continue

        # Must be in a script block for remaining directives
        if not state.current_script:
            state.error(f"Command '{cmd}' found outside of a script/label block")
            i += 1
            continue

        # In-script dispatch (commands, comments, movement)
        consumed = _dispatch_inscript(cmd, tokens, stripped, state, lines, i)
        i += 1 + consumed

    # Close any open script block
    if state.current_script:
        state.close_script()

    # Finalize NPC pages into merged script blocks
    if state.page_groups:
        _finalize_pages(state)

    # Allocate self-flags in flags.h (only when game_path is available)
    if state.self_flag_names and state.game_path:
        from torch.self_flags import ensure_self_flag
        for _key, flag_name in state.self_flag_names.items():
            npc_label = ""
            suffix = ""
            # Extract NPC and suffix from the key: "map_label_suffix"
            parts = _key.rsplit("_", 1)
            if len(parts) == 2:
                suffix = parts[1]
                npc_label = parts[0]
            ensure_self_flag(state.game_path, flag_name,
                           map_name=state.map_name or "",
                           npc_label=npc_label, suffix=suffix)

    return _assemble_output(state), state.errors


def _assemble_output(state):
    """Assemble final .pory output from compiled state."""
    output_parts = []

    # Constants (from aliases)
    if state.const_lines:
        for cl in state.const_lines:
            output_parts.append(cl)
        output_parts.append("")

    # All output blocks (mapscripts, scripts)
    for block in state.output_blocks:
        output_parts.append(block)
        output_parts.append("")

    # Auto-generated labels (from give beat bag-full checks, etc.)
    for label, label_lines in state.auto_labels.items():
        # Skip if the user already defined this label
        existing_labels = set()
        for block in state.output_blocks:
            if block.startswith(f"script {label} "):
                existing_labels.add(label)
        if label not in existing_labels:
            inner = "\n".join(f"    {l}" for l in label_lines)
            output_parts.append(f"script {label} {{")
            output_parts.append(inner)
            output_parts.append("}")
            output_parts.append("")

    # Named text blocks
    if state.text_blocks:
        for label, text_content in state.text_blocks:
            output_parts.append(f"text {label} {{")
            output_parts.append(f'    "{text_content}"')
            output_parts.append("}")
            output_parts.append("")

    # Movement blocks
    if state.movement_blocks:
        for label, commands in state.movement_blocks:
            move_lines = "\n".join(f"    {c}" for c in commands)
            output_parts.append(f"movement {label} {{")
            output_parts.append(move_lines)
            output_parts.append("}")
            output_parts.append("")

    return "\n".join(output_parts)
