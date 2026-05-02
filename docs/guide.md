# TORCH — User Guide

> v0.4.0 | The Open ROM Creation Hub
> For pokeemerald-expansion ROM hacks | Stdlib Python, no pip required

TORCH is a toolkit for Pokemon ROM hackers using the pokeemerald decomp projects. It replaces the tedious parts — hand-editing scripts, managing file structures, cross-referencing documentation — with visual editors and automated pipelines.

You write scripts in TorScript. You edit trainers, encounters, and NPCs in a browser. TORCH compiles, syncs, and builds.

---

## Table of Contents

1. [Installation](#1-installation)
2. [First-Time Setup](#2-first-time-setup)
3. [The Big Picture](#3-the-big-picture)
4. [Web GUI (TORCH Studio)](#4-web-gui)
5. [Your First Script](#5-your-first-script)
6. [TorScript Language](#6-torscript-language)
7. [Script Studio](#7-script-studio)
8. [Trainers](#8-trainers)
9. [Encounters](#9-encounters)
10. [NPCs](#10-npcs)
11. [Building Templates](#11-building-templates)
12. [SCORCH — Removing Vanilla Content](#12-scorch)
13. [Data Editors](#13-data-editors)
14. [Music Browser](#14-music-browser)
15. [Tileset Assistant](#15-tileset-assistant)
16. [Map Explorer](#16-map-explorer)
17. [Decompiler](#17-decompiler)
18. [Building Your ROM](#18-building-your-rom)
19. [Backups and Restore](#19-backups-and-restore)
20. [Project Management](#20-project-management)
21. [Configuration](#21-configuration)
22. [Quick Reference](#22-quick-reference)
23. [Troubleshooting](#23-troubleshooting)

---

## 1. Installation

### Requirements

- **Python 3.11+** (stdlib only — nothing to pip install)
- A [pokeemerald](https://github.com/pret/pokeemerald) or [pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion) v1.6.0+ project
- [Poryscript](https://github.com/huderlem/poryscript) compiler
- [devkitPro](https://devkitpro.org/) toolchain (for building the ROM)

### Install

```bash
git clone https://github.com/eagredev/TORCH.git ~/torch
```

That's it. No build step, no dependencies.

---

## 2. First-Time Setup

```bash
python3 ~/torch init
```

This walks you through:
- Locating your pokeemerald-expansion project
- Detecting your expansion version (v1.6.0 through latest, or vanilla pokeemerald)
- Creating `~/.config/torch/torch.conf`

Once setup is complete, launch TORCH:

```bash
# Web GUI (recommended for most work)
python3 ~/torch gui

# Terminal interface
python3 ~/torch
```

---

## 3. The Big Picture

TORCH sits between you and the decomp toolchain. The workflow looks like this:

```
You (TorScript, visual editors)
  |
TORCH (compiles, validates, manages files)
  |
pokeemerald-expansion (C code, makefiles, ROM output)
```

### Core concepts

**Workspace** — TORCH keeps your work in a separate workspace directory, organised by map. Your TorScript files, snapshots, and backups live here, not in the game project folder.

**Enrollment** — Before TORCH can track a map, you enroll it. This registers the map in TORCH's registry so it can monitor health, sync changes, and create snapshots.

**Sync** — When you're ready to deploy changes, TORCH compiles your TorScript, validates constants against game headers, snapshots the current state, and writes the output to your game project.

**Build** — TORCH auto-syncs any stale maps, runs pre-build safety checks, then calls `make` to build the ROM.

### Two interfaces, one workflow

**Web GUI** — A browser-based IDE for visual editing. Maps, NPCs, trainers, encounters, scripts, flags, shops — all editable in a single window. This is the recommended way to use TORCH for day-to-day work.

**Terminal (TUI)** — Everything also works from the command line. Scrolling list menus, inline editors, keyboard-driven navigation. Useful for quick operations, scripting, and when you don't need the full IDE.

Both interfaces read and write the same project files. You can switch between them freely.

---

## 4. Web GUI

The web GUI is TORCH's primary interface. Launch it with:

```bash
python3 ~/torch gui
```

This starts a local web server (default: `http://localhost:8642`) and opens your browser.

### Dashboard

The landing page shows your project overview with quick actions — build, open Studio, recent maps.

### TORCH Studio

The main workspace. A three-panel layout inspired by Porymap and RPG Maker:

- **Left panel** — Map tree, project health, recent maps
- **Centre** — Map canvas with rendered tiles, NPC sprites, warps, and connection strips
- **Right panel** — Eight editor tabs:
  - **Props** — Map object properties with inline editing
  - **NPCs** — NPC list with dialogue editing and sprite preview
  - **Encounters** — Wild Pokemon encounters for this map
  - **Warps** — Warp connections
  - **Scripts** — TorScript files with beat-based visual editor
  - **Flags** — Flags used in this map's scripts
  - **Shops** — Shop inventories
  - **Trainers** — Trainer parties on this map

The toolbar provides File, Edit, View, Data, Window, and Help menus.

### Other views

The sidebar provides access to standalone editors:

| View | What it does |
|------|-------------|
| Dex | Searchable Pokemon browser — stats, types, abilities, evolution chains, learnsets, shiny sprites |
| Trainers | Party builder with species picker, AI flags, EV/IV spreads, held items |
| Encounters | Wild Pokemon editor by route, slot, and time-of-day |
| NPCs | Map-first NPC browser with dialogue editing and 7 creation wizards |
| Flags | Cross-reference scanner with orphan detection |
| Items | Item data editor |
| Moves | Move data editor |
| Shops | Shop inventory editor |
| Learnsets | Level-up, TM, egg move editor |
| Heals | Heal location manager |
| Music | Track browser with GBA-accurate playback |
| Map Explorer | SVG connectivity graph of your game world |
| Assets | 7-category asset browser (sprites, tilesets, music, etc.) |
| Tilesets | Tileset viewer and editor |
| Templates | Building template wizard |
| SCORCH | Vanilla content removal (Singe + Phoenix) |
| Scripts | Script browser with search and CRUD |
| Project | Backups, forks, version info |
| Settings | Game settings and expansion options |

Three colour themes: **Torch** (orange), **Porygon** (pink), **Emerald** (green).

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| gui_port | 8642 | Server port |
| gui_host | 127.0.0.1 | Bind address (local only) |
| gui_lan_enabled | false | Allow LAN access (binds to 0.0.0.0) |
| gui_username | (empty) | HTTP Basic Auth username |
| gui_password | (empty) | HTTP Basic Auth password |

LAN mode lets you access the GUI from another device on your network — useful for working on a Steam Deck while viewing the GUI on a phone or tablet.

---

## 5. Your First Script

### 1. Enroll your maps

```bash
python3 ~/torch enroll --all
```

This registers all maps in your project. You can also enroll individually:

```bash
python3 ~/torch enroll Route101
```

### 2. Write a TorScript file

Create a file in your workspace (TORCH creates the workspace directory for you):

```
~/ROMHacking/TORCH/<ProjectName>/Route101/Buster.txt
```

Write some TorScript:

```
@ Buster
alias buster npc5

label Route101_Buster
    lock
    buster face player
    "Hey, have you seen my Poochyena?"
    "I lost him near the lake..."
    emote buster !
    pause 30
    buster walk down 3
    "Oh wait, there he is!"
    flag set FLAG_MET_BUSTER
    end
```

### 3. Sync

```bash
python3 ~/torch sync Route101
```

TORCH compiles the TorScript to Poryscript, validates all constants (flag names, species, items) against your game headers, snapshots the current state, and writes the output to your game project.

### 4. Set the script in your map

In Porymap (or TORCH Studio's Props tab), set the NPC's script field to `Route101_Buster`.

### 5. Build

```bash
python3 ~/torch build
```

TORCH auto-syncs any stale maps, runs pre-build safety checks, and builds the ROM.

### Or do it all in the GUI

Open TORCH Studio, navigate to your map, click an NPC, edit the dialogue right in the browser, and hit Build from the toolbar. No terminal required.

---

## 6. TorScript Language

TorScript is TORCH's scripting language — a human-readable alternative to Poryscript. TORCH compiles it down automatically.

For the complete syntax reference, see [syntax_reference.txt](syntax_reference.txt).

### Script structure

Every TorScript file follows this pattern:

```
@ Description comment
alias actorname npc5

label ScriptName
    lock
    ... commands ...
    end
```

**Aliases** map friendly names to NPC local IDs. The compiler generates `const LOCALID_ACTORNAME = 5` automatically.

### Dialogue

Just write text in quotes:

```
"Hello there!"
"This is a second text box."
```

TORCH handles text labels, line breaks, and box formatting. Multi-line dialogue:

```
"This is a longer message that\n"
"spans two lines in one box.\p"
"And continues in a new box."
```

The `$` end marker is added automatically if you forget it.

### Movement

```
buster walk up 3         # Walk 3 tiles north
buster walkfast left 2   # Fast walk (run speed)
buster walkslow down 1   # Slow walk
buster face player       # Turn to face the player
buster face away         # Turn away from the player
buster jump right        # 1-tile jump
buster jump up 2         # 2-tile jump
buster slide left 3      # Slide without walk animation
```

**Parallel movement** — move multiple actors at once:

```
buster walk down 2 + player walk up 2
```

**Walk-to** — dynamic pathfinding to a target:

```
clyde walkto 25 61            # Walk to absolute tile
clyde walkto player 0 1       # Walk to 1 tile below the player
clyde walkfastto buster -1 0  # Fast walk to 1 tile left of buster
```

Walk-to moves L-shaped (X axis first, then Y axis). Speed variants: `walkto`, `walkfastto`, `walkslowto`, `runto`.

### Named movement blocks

Define reusable movement sequences:

```
movement MyDance
    walk_in_place_down
    delay_16
    walk_in_place_up
    delay_16
endmovement
```

Or inline: `movement MyDance { walk_in_place_down, delay_16, walk_in_place_up }`

Reference with: `buster do MyDance`

### Emotes

```
emote buster !       # Exclamation mark
emote buster ?       # Question mark
emote buster !!      # Double exclamation
emote buster x       # X mark
emote buster heart   # Heart
emote buster ...     # Ellipsis
```

Custom emotes can be defined in `config/emotes.conf`.

### Camera

```
camera pan down 3        # Pan camera 3 tiles south
camera pan right 2       # Pan camera 2 tiles east
camera reset             # Return camera to player
camera reset warp MAP X Y  # Warp to location (ends script)
```

Camera pans accumulate — if you pan down 3 then right 2, `camera reset` corrects the full offset. The reset uses a small engine patch that TORCH auto-applies on first use.

Camera commands cannot use the `+` parallel syntax.

### Sound

```
sound SE_EXIT              # Sound effect
music MUS_ROUTE101         # Background music
fanfare MUS_OBTAIN_ITEM    # Fanfare (waits for completion)
cry SPECIES_KOFFING        # Pokemon cry
```

### Screen effects

```
fade black           # Fade to black
fade in              # Fade from black
fade white           # Fade to white
fade from white      # Fade from white
shake 2 4            # Shake camera (intensity, count)
```

### Timing

```
pause              # Short pause (~16 frames)
pause long         # Longer pause (~32 frames)
pause 60           # Custom frame count
```

### Flags and variables

```
flag set FLAG_MET_BUSTER      # Set a flag
flag clear FLAG_MET_BUSTER    # Clear a flag
var VAR_0x8004 42             # Set a variable
gotoif FLAG_MET_BUSTER Label  # Jump if flag is set
```

### Object management

```
hide buster          # Remove NPC from map
show buster          # Add NPC back to map
setpos clyde 28 62   # Move NPC to position
```

### Give items

```
give ITEM_POTION           # Give 1 potion
give ITEM_RARE_CANDY 3     # Give 3 rare candies
```

Automatically generates a bag-full safety check.

### Pokemon actors

Declare a Pokemon as a map NPC:

```
pokemon pikachu npc2
```

This enables special freeze/unfreeze logic for idle animation:

```
faint pikachu     # Stop idle animation (fainted state)
revive pikachu    # Resume idle animation
```

### Follower NPCs

Control follower NPCs (requires pokeemerald-expansion):

```
follower add local LOCALID_RIVAL PARTNER_CYNTHIA
follower add dynamic OBJ_EVENT_GFX_GIRL PARTNER_CYNTHIA FNPC_ALL
follower remove
follower face
follower hide FOLLOWER_MOVE_SLOW
follower check
follower change PARTNER_ID
```

### Multi battles

```
multi 2v2 TRAINER_A IntroTextA TRAINER_B IntroTextB PARTNER_X
multi 2v1 TRAINER_A IntroTextA PARTNER_X
```

Fixed variants: `multi 2v2_fixed`, `multi 2v1_fixed`.

### Trainer battles

Legacy single-line:

```
trainerbattle_single TRAINER_RIVAL, IntroLabel, DefeatLabel
```

Expanded form with auto-generated text labels:

```
trainerbattle_single TRAINER_RIVAL
    intro "Let's battle!"
    defeated "You're tough..."
    postbattle "I'll train harder next time."
```

Variants: `trainerbattle_single`, `trainerbattle_double`, `trainerbattle_rematch`, `trainerbattle_rematch_double`, `trainerbattle_no_intro`, `trainerbattle_two_trainers`.

### Pass-through

For anything TorScript doesn't cover:

```
pory applymovement(LOCALID_CLYDE, MyMovement)
raw waitmovement(0)
```

Both `pory` and `raw` emit the line as-is into the Poryscript output.

### Script flow

```
label ScriptName        # Start a script block
lock                    # Lock all movement
end                     # Release all + end script
release                 # Release single NPC + end
goto Label              # Jump to label
call Label              # Call subroutine
return                  # Return from subroutine
closemessage            # Close dialogue box
faceplayer              # NPC faces player
special FunctionName    # Call a special C function
waitstate               # Wait for special to complete
```

### Comments

```
# This is ignored by the compiler
// This appears in the Poryscript output
@ This also appears in the output
```

### Compile-time validation

The compiler validates these against your game's actual header files:
- Flag names (`FLAG_*`)
- Variable names (`VAR_*`)
- Trainer IDs (`TRAINER_*`)
- Sound effects (`SE_*`)
- Music tracks (`MUS_*`)
- Species constants (`SPECIES_*`)
- Item constants (`ITEM_*`)
- Special function names

Typos are caught at compile time, not after a 5-minute ROM build.

---

## 7. Script Studio

The Script Studio is TORCH's visual script editor — available in both the web GUI and the TUI.

### Web GUI (Scripts tab in Studio)

In TORCH Studio, the Scripts tab shows all TorScript files for the current map. Click a script to open the beat-based editor:

- **Beat list** — Your script as a list of actions (dialogue, movement, emote, camera, etc.)
- **Canvas** — Live preview of actor positions with GBA-style dialogue rendering
- **Beat editors** — Specialised editors for each action type (21 editor types)
- **Cast panel** — View and manage NPC aliases
- **Source view** — See the raw TorScript

The Script Browser (`/scripts` in the sidebar) provides project-wide script search and CRUD operations.

### TUI

```bash
python3 ~/torch script MapName
python3 ~/torch script MapName ScriptName   # Open specific script
```

The TUI Script Studio provides:
- Map browser with search
- Script list with health indicators
- Beat-based editor with inline preview
- Movement block manager (press `m`)
- Storyboard view (paginated beat overview)
- Snapshot/restore per map

---

## 8. Trainers

### Web GUI

The Trainers view provides a party builder for each trainer:
- Species picker with search
- Move selection
- Held items, abilities, nature
- AI flags with descriptions
- EV/IV spreads
- Level and friendship

### TUI

```bash
python3 ~/torch trainers
python3 ~/torch battle
```

### Trainer format

TORCH supports both legacy `.h` format and modern `.party` format. The `.party` format (available in expansion v1.9.0+) supports longer names, custom movesets, and held items.

To migrate legacy trainers:

```bash
python3 ~/torch battle migrate
```

---

## 9. Encounters

### Web GUI

The Encounters view (and the Encounters tab in Studio) lets you edit wild Pokemon by route and slot. Time-of-day variants are supported on expansion v1.12.0+.

### TUI

```bash
python3 ~/torch wild
python3 ~/torch encounters
```

---

## 10. NPCs

### Web GUI

The NPC Editor provides:
- Map-first browser with NPC counts and overworld sprite preview
- Card grid showing all NPCs on a map
- Detail panel with dialogue editing and GBA text preview
- 7 creation wizards: **Flavor NPC**, **Sign**, **Item Giver**, **Multi-State**, **Nurse**, **PC**, **Infrastructure Sign**
- Health scan for missing or stub scripts
- "Convert to Editable" button for vanilla NPCs — auto-decompiles to TorScript

### TUI

```bash
python3 ~/torch npc MapName
```

---

## 11. Building Templates

Stamp complete building interiors from a single command:

```bash
python3 ~/torch template pokecenter Route101 --door 10,5
python3 ~/torch template pokemart Route101 --door 14,5
```

This creates:
- A new interior map with the correct layout
- NPC scripts (Nurse Joy, PC, Mart clerk)
- Warp connections between the parent map and the interior
- Heal location registration (for PokeCentres)
- Map group enrollment

Also available in the web GUI via the Templates view.

---

## 12. SCORCH — Removing Vanilla Content

SCORCH removes stock Pokemon Emerald content you don't need in your ROM hack. Two modes:

### Singe (selective removal)

```bash
python3 ~/torch scorch              # Full-scan wizard
python3 ~/torch scorch maps         # Remove vanilla maps only
python3 ~/torch scorch trainers     # Remove vanilla trainers only
python3 ~/torch scorch encounters   # Remove vanilla encounters only
python3 ~/torch scorch report       # Scan without removing
```

Categories: `maps`, `trainers`, `encounters`, `frontier`, `scripts`, `tilesets`, `graphics`, `music`.

Items are tagged **SAFE**, **BLOCKED**, or **CAUTION** based on cross-reference analysis.

### Phoenix (full wipe)

```bash
python3 ~/torch scorch phoenix       # Remove ALL vanilla maps, trainers, encounters
python3 ~/torch scorch phoenix plan  # Dry-run report
```

Phoenix has been tested across every expansion version from v1.6.0 to latest. Works on fresh clones — no prior build required.

### Safety

SCORCH takes a full snapshot before any removal:

```bash
python3 ~/torch scorch restore     # Restore from SCORCH snapshot
```

Also available in the web GUI via the SCORCH view.

---

## 13. Data Editors

TORCH provides editors for all major game data. Each is available in both the web GUI sidebar and as a CLI command.

| Editor | CLI Command | What it edits |
|--------|-------------|---------------|
| Dex | `torch dex` | Pokemon species, stats, types, abilities, evolution chains, learnsets |
| Items | `torch items` | Item names, descriptions, effects, held attributes |
| Moves | `torch moves` | Move power, accuracy, type, category, effect |
| Learnsets | `torch learnsets` | Level-up moves, TM/HM compatibility, egg moves |
| Flags | `torch flags [MapName]` | Flag cross-references, orphan detection, bulk rename |
| Shops | `torch shops [MapName]` | Shop inventories and pricing |
| Heals | `torch heal` | Heal location registry (PokeCentre healing tiles) |

---

## 14. Music Browser

Browse and preview your game's music tracks:

```bash
python3 ~/torch music
```

Playback uses [poryaaaa_render](https://github.com/pret/poryaaaa) for GBA-accurate audio, with a built-in MIDI synth as fallback. Rendered audio is cached to disk.

Also available in the web GUI sidebar and the Asset Browser.

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| poryaaaa_path | (auto-detect) | Path to poryaaaa_render binary |
| audio_player | (auto-detect) | Audio player for TUI (pw-play, paplay, aplay) |
| music_cache_max_mb | 200 | Max cache size in MB |
| music_sample_rate | 22050 | Render sample rate (22050 or 44100) |
| music_default_duration | 180 | Default render length in seconds |

---

## 15. Tileset Assistant

Import and manage tilesets:

```bash
python3 ~/torch tileset import /path/to/source/tileset NewTilesetName
```

The tileset importer:
- Auto-detects metatile formats (8/12 tiles, 2/4 byte attributes)
- Converts metatile data between formats
- Remaps tile indices across primary/secondary boundaries
- Resolves shared tile graphics

The web GUI provides a visual tileset editor with metatile composition, layer management, and a pixel editor.

---

## 16. Map Explorer

Browse your game world's map connectivity:

```bash
python3 ~/torch explore
python3 ~/torch explore Route101
```

The web GUI provides an interactive SVG graph showing map connections, warps, and navigation paths.

---

## 17. Decompiler

Convert existing scripts back to TorScript:

```bash
# Poryscript (.pory) to TorScript
python3 ~/torch decompile path/to/file.pory

# Assembly (.inc) to Poryscript
python3 ~/torch decompile-inc path/to/file.inc MapName
```

In the web GUI, click any vanilla NPC in Studio and hit "Convert to Editable" — TORCH auto-decompiles the script to a TorScript workspace file.

The decompiler handles:
- Standard dialogue scripts
- Trainer battles (all variants)
- Flag checks and branching
- Movement sequences
- Signs and item givers

---

## 18. Building Your ROM

```bash
python3 ~/torch build
```

The build command does three things:

1. **Auto-sync** — syncs all stale enrolled maps
2. **Pre-build safety checks:**
   - Sanitises empty script fields in map.json
   - Regenerates missing .inc files
   - Precompiles all .pory files
3. **Build** — runs `make` with all CPU cores
4. **Error diagnosis** — if the build fails, pattern-matches the error output and suggests a fix

### Recognised error patterns

| Error | Suggested fix |
|-------|--------------|
| stddef.h missing | Run `fixdev` (SteamOS header restore) |
| ROM region overflowed | Use SCORCH to remove vanilla content |
| Missing map data file | Check map folder structure |
| Poryscript .pory error | Check script syntax |
| Undeclared constant | Check header files / flag names |
| C syntax error | Check source file |

### Build in the GUI

The toolbar Build button (or keyboard shortcut) triggers the same pipeline.

---

## 19. Backups and Restore

### Workspace snapshots

TORCH automatically snapshots your workspace files before every sync. Snapshots are stored per-map and pruned to `max_snapshots` (default: 10).

```bash
python3 ~/torch restore Route101    # Interactive workspace restore for one map
```

### Verified build snapshots

After every successful build via `torch build`, TORCH saves a verified snapshot of all enrolled map workspaces. This is your safety net.

```bash
python3 ~/torch restore             # Restore from last verified build snapshot
```

Retention controlled by `max_verified_snapshots` (default: 3).

### Manual backups

```bash
python3 ~/torch backup              # Create a backup
python3 ~/torch backup "pre-merge"  # Create a tagged backup
python3 ~/torch backup list         # Show all backups with tier labels
python3 ~/torch backup prune        # Enforce retention policy
```

Backup retention is tiered: hourly, daily, weekly, monthly.

---

## 20. Project Management

### Multiple projects

TORCH supports multiple pokeemerald projects. Configure them in `torch config`:

```bash
python3 ~/torch config
```

Switch projects:

```bash
python3 ~/torch --project "My Other Hack" build
```

Set a favourite project to auto-load:

```ini
# In ~/.config/torch/torch.conf
favourite_project = My Project Name
```

### Fork a project

Create an independent copy of your project for experimentation:

```bash
python3 ~/torch fork
```

### Create a new project

Clone pokeemerald-expansion from GitHub:

```bash
python3 ~/torch new
```

### Upgrade expansion version

```bash
python3 ~/torch upgrade --check      # Check available versions
python3 ~/torch upgrade --to 1.14.4  # Upgrade to specific version
```

### Game version control

```bash
python3 ~/torch versions save "v1.0 release candidate"
python3 ~/torch versions list
python3 ~/torch versions restore
```

---

## 21. Configuration

TORCH stores its configuration in `~/.config/torch/torch.conf` (INI format).

### All settings

#### Project

| Setting | Default | Description |
|---------|---------|-------------|
| favourite_project | (empty) | Auto-load this project on launch |
| projects_directory | ~/Documents | Default directory for new projects |

#### Editor

| Setting | Default | Description |
|---------|---------|-------------|
| editor_visible_beats | 20 | Beats visible in Script Editor scroll |
| storyboard_page_size | 30 | Lines per page in storyboard view |
| editor_context | compact | Context line mode (compact / detail / off) |
| vim_help_dismissed | false | Skip vim navigation guide |

#### Lists

| Setting | Default | Description |
|---------|---------|-------------|
| trainer_list_page_size | 20 | Trainers per page |
| map_list_page_size | 20 | Maps per page |
| show_all_trainers | false | Show all trainers including vanilla |
| maps_view | recent | Default view in Studio (recent / all) |

#### Gameplay

| Setting | Default | Description |
|---------|---------|-------------|
| textbox_warning | 3 | Warn when dialogue exceeds this many boxes |
| level_cap | 100 | Max Pokemon level in trainer parties |

#### Snapshots

| Setting | Default | Description |
|---------|---------|-------------|
| max_snapshots | 10 | Workspace snapshots kept per map |
| max_verified_snapshots | 3 | Verified build snapshots retained |

#### Build

| Setting | Default | Description |
|---------|---------|-------------|
| auto_build | true | Auto-build after safe operations without prompting |

#### Navigation keys

| Setting | Default | Description |
|---------|---------|-------------|
| nav_up | u | Move highlight up in list menus |
| nav_down | j | Move highlight down in list menus |
| nav_open | v | Open / act on highlighted item |
| nav_scroll | (empty) | Secondary scroll-down key (Enter always scrolls) |

#### Templates

| Setting | Default | Description |
|---------|---------|-------------|
| template_include_2f | true | Include 2F when stamping PokeCentre templates |

#### Web GUI

| Setting | Default | Description |
|---------|---------|-------------|
| gui_port | 8642 | Server port |
| gui_host | 127.0.0.1 | Bind address |
| gui_lan_enabled | false | Allow LAN access |
| gui_username | (empty) | HTTP Basic Auth username |
| gui_password | (empty) | HTTP Basic Auth password |

#### Audio

| Setting | Default | Description |
|---------|---------|-------------|
| poryaaaa_path | (auto-detect) | Path to poryaaaa_render binary |
| audio_player | (auto-detect) | Audio player for TUI playback |
| music_cache_max_mb | 200 | Max cache size in MB |
| music_sample_rate | 22050 | Render sample rate |
| music_default_duration | 180 | Default render duration in seconds |

---

## 22. Quick Reference

### CLI Commands

#### Core workflow
```
torch                           Main menu (TUI)
torch gui                       Launch web GUI
torch init                      First-time setup
torch sync [MapName]            Compile + deploy (one map or all enrolled)
torch build                     Build ROM with auto-sync + error diagnosis
torch restore                   Restore from verified build snapshot
torch restore MapName           Interactive workspace restore
torch status                    Map health indicators
torch enroll [MapName|--all]    Register maps for tracking
torch unenroll MapName          Remove map from registry
```

#### Editors
```
torch script MapName [Script]   Script Studio (TUI)
torch trainers                  Trainer editor
torch wild / torch encounters   Encounter editor
torch npc MapName               NPC editor
torch dex                       Pokemon browser
torch items                     Item editor
torch moves                     Move editor
torch learnsets                 Learnset editor
torch flags [MapName]           Flag browser
torch shops [MapName]           Shop editor
torch heal                      Heal location manager
torch music                     Music browser
torch explore [MapName]         Map Explorer
torch tileset                   Tileset assistant
torch template [type] [args]    Building templates
torch rom                       ROM metadata editor
torch settings                  Game settings menu
```

#### Content management
```
torch scorch                    SCORCH wizard (selective removal)
torch scorch phoenix            Full vanilla wipe
torch scorch report             Scan-only report
torch scorch restore            Restore from SCORCH snapshot
```

#### Project management
```
torch config                    Configuration manager
torch backup [tag]              Create backup
torch backup list               List backups
torch backup prune              Enforce retention policy
torch fork                      Clone project for experimentation
torch new                       Create new project from GitHub
torch upgrade [--check|--to X]  Upgrade expansion version
torch versions [subcommand]     Game version control
torch decompile file [MapName]  Decompile .pory to TorScript
torch decompile-inc file [Map]  Decompile .inc to Poryscript
torch --project "Name" cmd      Select project for this command
```

### Map health states

| State | Meaning | Action |
|-------|---------|--------|
| OK | Workspace and game files in sync | Nothing needed |
| STALE | Workspace changed since last sync | `torch sync MapName` |
| DRIFT | Game files changed outside TORCH | Re-sync or restore |
| ORPHAN | Game files exist but no workspace | Restore or re-import |
| NEW | Workspace exists but never synced | `torch sync MapName` |
| MISSING WS | Enrolled but workspace deleted | `torch restore MapName` |

### Main menu (TUI)

```
[1] Studio        Your maps, trainers, items & scripts
[2] Dex           Pokemon species, moves & learnsets
[3] Game Settings Expansion options, ROM, tilesets & assets
[4] Project       Backups, SCORCH, fork & upgrade
[b] Build         Build ROM
[r] Restore       Restore from verified snapshot
[c] Config        Projects & preferences
[?] Help
[q] Quit
```

---

## 23. Troubleshooting

### Build fails with "stddef.h not found"

SteamOS updates can overwrite patched GCC headers. Run:

```bash
fixdev
```

### Build fails with "ROM region overflowed"

Your ROM is too large. Use SCORCH to remove vanilla content you don't need:

```bash
python3 ~/torch scorch
```

### Web GUI won't open in browser

Check that no other process is using port 8642:

```bash
python3 ~/torch gui --port 9000
```

### Music playback doesn't work

Install poryaaaa_render for GBA-accurate playback, or TORCH falls back to a built-in MIDI synth. Check your `audio_player` config if TUI playback is silent.

### "Constant not found" warnings during sync

The compiler validates constants against your game headers. If you see warnings:
- Check spelling of FLAG_, ITEM_, SPECIES_ etc. constants
- Make sure you're using constants that exist in your expansion version
- Use `pory` pass-through for non-standard constants

### Sync shows DRIFT state

Something changed the game files outside TORCH (e.g. manual Porymap edits). If intentional, re-sync to update TORCH's tracking. If accidental, restore:

```bash
python3 ~/torch restore MapName
```

### Unicode ellipsis crashes the build

Never use the Unicode ellipsis character. Always use three ASCII dots `...`. The GBA assembler cannot handle Unicode characters.

### Escape sequences in TorScript

`\n` and `\p` are Poryscript text commands (new line / new paragraph). If you're writing TorScript in a context where Python interprets backslashes, escape them as `\\n` and `\\p`.

---

## Built on

TORCH builds on the work of the decomp community:

- [pret/pokeemerald](https://github.com/pret/pokeemerald) — the decompilation
- [rh-hideout/pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion) — modern battle engine and features
- [huderlem/poryscript](https://github.com/huderlem/poryscript) — the scripting language TORCH compiles to
- [huderlem/porymap](https://github.com/huderlem/porymap) — the map editor that inspired Studio
