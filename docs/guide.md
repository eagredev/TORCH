# TORCH — User Guide

> v0.1.0-alpha | The Open ROM Creation Hub
> For pokeemerald-expansion ROM hacks | Stdlib Python, no pip required

TORCH is a toolkit for Pokemon ROM hackers using the pokeemerald-expansion decomp project. It replaces the tedious parts — hand-editing C headers, managing file structures, writing Poryscript boilerplate — with guided wizards and automated pipelines.

You write scripts in TorScript. TORCH compiles, syncs, and builds.

---

## Table of Contents

1. [Installation](#1-installation)
2. [First-Time Setup](#2-first-time-setup)
3. [The Big Picture](#3-the-big-picture)
4. [Your First Script](#4-your-first-script)
5. [TorScript Language](#5-torscript-language)
6. [Script Studio](#6-script-studio)
7. [Trainers](#7-trainers)
8. [SCORCH — Removing Vanilla Content](#8-scorch)
9. [Building Your ROM](#9-building-your-rom)
10. [Backups and Restore](#10-backups-and-restore)
11. [Configuration](#11-configuration)
12. [Quick Reference](#12-quick-reference)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Installation

You need two files:
- `install_torch.py` (the installer)
- `torch_v<X.X>_stable.zip` (the release)

Place both in the same folder and run:

```
python3 install_torch.py
```

The installer walks you through everything:
- Where to install (default: `~/torch_stable/`)
- Shell alias setup (so `torch` works from anywhere)
- First-time config (`torch init`)

After installation, open a new terminal and type `torch`. You should see the main menu with the Torchic logo.

### Updating

```
torch update
```

Or run the installer again — it detects existing installs and offers to update.

---

## 2. First-Time Setup

```
torch init
```

This creates your config file at `~/.config/torch/torch.conf`. It asks two things:

1. **Game project path** — where your pokeemerald-expansion folder lives (e.g., `~/Documents/pokeemerald-expansion/`)
2. **Workspace location** — where TORCH stores your script files (default: `~/ROMHacking/TORCH/`)

That's it. TORCH creates the workspace folder structure for you.

### Multiple Projects

TORCH supports multiple projects. Each gets its own section in the config:

```
torch config
```

Choose "Projects" to add, remove, or switch between projects. If you have multiple projects, TORCH asks which one to use on launch (or set a favourite in settings).

You can also force a project from the command line:

```
torch --project "My Other Hack" sync
```

---

## 3. The Big Picture

```
YOUR WORKSPACE                          GAME PROJECT
~/ROMHacking/TORCH/                     ~/Documents/pokeemerald-expansion/
└── YourProject/                        └── data/maps/MyTown/
    └── MyTown/
        ├── setup.pory ────┐
        ├── Greeter.txt ───┤
        ├── Guard.txt ─────┤  torch sync  →  scripts.pory  →  ROM
        └── Cutscene.txt ──┘
```

**The workflow:**
1. You write `.txt` files in your workspace (left side) using TorScript
2. `torch sync MyTown` compiles everything into one `scripts.pory` in the game project
3. `torch build` (or `bb`) builds the ROM
4. If something breaks, `torch restore MyTown` rolls back your workspace

### Two file types

- **`.txt` files** — Written in TorScript. The compiler turns them into Poryscript. One file per NPC or cutscene.
- **`.pory` files** — Raw Poryscript, injected as-is. Used for `setup.pory`, battle text, and anything TorScript can't express.

### Special files

| File | Purpose |
|------|---------|
| `setup.pory` | Always injected first. Put mapscripts, shared text blocks, and movement blocks here. Auto-generated on first sync if missing. |
| `legacy.pory` | Auto-created when migrating an old map. Contains previous assembly wrapped in a Poryscript `raw` block. |
| `battle_TRAINER_*.pory` | Created by the Trainers module. Contains trainer intro/defeat text. |

---

## 4. Your First Script

Let's create a simple NPC that talks to the player.

### Step 1: Create the workspace folder

If your game has a map called `MyTown`, create a folder for it:

```
mkdir -p ~/ROMHacking/TORCH/YourProject/MyTown
```

Or use Script Studio (`torch scene`) to import it — see [Section 6](#6-script-studio).

### Step 2: Create setup.pory

Every map needs a `setup.pory`. The simplest version:

```
// MyTown — mapscripts and shared data
mapscripts MyTown_MapScripts {}
```

Save this as `~/ROMHacking/TORCH/YourProject/MyTown/setup.pory`.

(If you skip this step, TORCH auto-generates one on first sync.)

### Step 3: Write your script

Create `Greeter.txt`:

```
# Friendly NPC in the town square

alias greeter npc1

label MyTown_Greeter
pory lock
faceplayer
msg "Welcome to MyTown!\pWe hope you enjoy your stay.$"
pory release
pory end
```

What each line does:
- `alias greeter npc1` — Names object event #1 "greeter" and auto-generates a `LOCALID_GREETER` constant
- `label MyTown_Greeter` — The script label (this is what you put in Porymap's "Script" field for the NPC)
- `pory lock` / `pory release` / `pory end` — Raw Poryscript commands passed through directly
- `faceplayer` — Makes the NPC turn to face the player
- `msg "..."` — Shows a message box

### Step 4: Sync and build

```
torch sync MyTown
```

TORCH will:
1. Snapshot your workspace (safety backup)
2. Compile `Greeter.txt` into Poryscript
3. Read `setup.pory` as-is
4. Assemble everything into `data/maps/MyTown/scripts.pory`
5. Validate all labels and constants
6. Ask if you want to build

Accept the build. If it succeeds, your NPC is in the game.

### Step 5: Set up in Porymap

Open Porymap, find your NPC on the map, and set its Script field to `MyTown_Greeter`. Save the map and rebuild if needed.

---

## 5. TorScript Language

This is the core of TORCH — a simplified syntax that compiles to Poryscript. You write these commands in `.txt` files.

### Actors

Every movement or emote command needs an actor — who's doing it.

```
player                      The player character
npc5                        Object event by ID number
greeter                     An alias (defined with the alias command)
```

Define aliases at the top of your .txt file:
```
alias buster npc5
alias clyde npc6
```

TORCH auto-generates `const LOCALID_BUSTER = 5` etc. You never need to write const lines manually.

### Messages

```
msg "Simple one-box message.$"
msgnpc "Alternative message style.$"
```

Multi-line (long dialogue):
```
msg "First line of the text box.\nSecond line of the box.\pNew box starts here.$"
```

For readability, you can split across source lines:
```
msg "This is the first part\n"
    "and this continues on.\p"
    "New box here.$"
```

**GBA text limits:** 38 characters per line, 2 lines per text box. Use `\n` for line breaks, `\p` for new boxes, `$` to end.

### Movement

```
buster face down            Face a direction (up/down/left/right)
buster face player          Face toward the player
buster face away            Face away from the player
buster walk up 3            Walk 3 tiles up
buster walkfast left 4      Walk at running speed
buster walkslow down 2      Walk slowly
buster slide right 3        Slide without walking animation
buster jump up              Jump 1 tile
buster jump down 2          Jump 2 tiles
buster do MyMovementLabel   Play a named movement block
```

**Parallel movement** (two actors at once):
```
buster face down + player face down
```

### Emotes

```
buster emote !              Exclamation mark
buster emote ?              Question mark
buster emote !!             Double exclamation
buster emote x              X mark
buster emote heart          Heart
buster emote ...            Thinking dots
```

Custom emotes can be added in `~/ROMHacking/TORCH/config/emotes.conf`.

### Screen Effects

```
fade black                  Fade to black
fade in                     Fade back in (from black)
fade white                  Fade to white
fade from white             Fade back in (from white)
```

### Sound

```
sound SE_EXIT               Play a sound effect
music MUS_ROUTE101          Change background music
fanfare MUS_OBTAIN_ITEM     Play a fanfare (waits for it to finish)
cry SPECIES_KOFFING         Play a Pokemon cry
```

### Timing

```
pause                       Short pause (~0.27 seconds)
pause long                  Longer pause (~0.53 seconds)
pause 60                    Custom pause (60 frames = 1 second)
```

### Flags and Variables

```
flag set FLAG_MY_EVENT      Set a flag (turn it on)
flag clear FLAG_MY_EVENT    Clear a flag (turn it off)
var VAR_MY_STATE 1          Set a variable to a value
gotoif FLAG_MY_EVENT Label  Jump to Label if flag is set
```

### Object Management

```
hide buster                 Despawn an NPC
show buster                 Spawn an NPC
setpos clyde 28 62          Teleport an NPC to coordinates
```

### Script Flow

```
label SceneName             Start a new script block
lock                        Lock all NPCs in place
end                         Release all NPCs and end
release                     Release single NPC and end
goto AnotherLabel           Jump to another script
call SubroutineLabel        Call a subroutine (returns back)
return                      Return from a call
closemessage                Close the dialog box
faceplayer                  NPC faces the player
special FuncName            Call a special engine function
waitstate                   Wait for a special to finish
```

### Pass-Through (Raw Poryscript)

When TorScript can't express what you need:
```
pory applymovement(LOCALID_CLYDE, MyMovement)
pory waitmovement(0)
```

The `pory` prefix passes the line through to the output untouched. `raw` does the same thing.

### Comments

```
# This is stripped from output (not in scripts.pory)
// This becomes a Poryscript comment in the output
```

---

## 6. Script Studio

Script Studio is TORCH's scene editor — a visual way to create and edit cutscene scripts without writing TorScript by hand.

### Opening Script Studio

```
torch scene                 Browse all maps and scenes
torch scene MapName Scene   Open a specific scene directly
```

Or press `[2]` from the main menu.

### The Hub

The hub shows all your maps sorted by status:
- **ACTIVE** — has a workspace folder with scenes
- **CUSTOM** — exists in the game but not imported to your workspace yet
- **ORPHAN** — workspace exists but no game folder
- **VANILLA** — vanilla maps (hidden by default, toggle with `f`)

Navigate with `u`/`j`, open with `v` or the item number, search with `/`.

### Importing Maps

When you see a CUSTOM map, press `v` to import it — TORCH creates the workspace folder and enrolls it.

For bulk import, press `i` (pick specific maps) or `A` (import all custom maps at once).

### Creating a New Scene

Press `n` from the hub or from within a map. The wizard walks you through:

1. **Map name** — which map this scene belongs to
2. **Scene name** — becomes the filename (e.g., `MeetRival.txt`)
3. **Description** — a one-line header comment
4. **Label** — the script label (default: `MapName_SceneName`)
5. **Cast** — add actors with names and NPC object IDs
6. **Trigger type** — how the scene is activated:
   - **NPC interaction** — player talks to an NPC
   - **Walk-on trigger** — player steps on a tile
   - **Map entry** — scene plays when entering the map
   - **Manual** — no scaffolding, you wire it yourself

After the wizard, TORCH creates the file with the right scaffolding and opens the editor.

### The Scene Editor

The editor shows your scene as a numbered list of beats. Each beat is an action: dialogue, movement, emote, fade, etc.

**Key commands:**
| Key | Action |
|-----|--------|
| `a` | Add a beat after current selection |
| `i` | Insert a beat before current selection |
| `e` | Edit the selected beat |
| `d` | Delete the selected beat |
| `:` | Quick-add (type TorScript directly) |
| `s` | Save to file |
| `w` | Save + sync to game + build offer |
| `v` | Toggle storyboard view |
| `m` | Movement block manager |
| `c` | Edit cast |
| `h` | Help (beat type reference) |
| `q` | Quit (prompts if unsaved changes) |

When you quit with unsaved changes, TORCH offers four options:
- Don't quit (go back)
- Save and quit
- Save, sync, and quit
- Quit without saving

### Beat Types

Script Studio supports over 20 beat types: dialogue, move, emote, fade, flag, var, battle, sound, music, fanfare, cry, pause, flow (goto/call/end), gotoif, hide, show, setpos, shake, lock, faceplayer, special, label, comment, and raw pass-through.

When adding a beat, you pick the type from a menu and TORCH prompts you for the details.

---

## 7. Trainers

The Trainers module creates complete trainer battles — no hand-editing C headers.

```
torch battle                Open the Trainers module
torch battle migrate        Migrate legacy .h trainers to .party format
```

Or press `[3]` from the main menu.

**Note:** Requires pokeemerald-expansion. Vanilla pokeemerald is not supported (TORCH will tell you clearly).

### The Trainers Menu

Shows your recent custom trainers, available slots, and the current data format. Options:
- `[l]` List all trainers (scrollable, searchable)
- `[n]` New trainer wizard
- `[f]` Find trainer by ID
- `[r]` Recovery scan (find orphaned trainers)

### Creating a Trainer

Press `n` to start the wizard. It walks you through four steps:

**Step 1: Details**
- Codename (internal constant, e.g., `ROCKET_GRUNT_1`)
- Display name (what the player sees — max 7 characters)
- Trainer class (from a numbered menu)
- Encounter music, sprite, battle type, AI flags

**Step 2: Party**
- Add Pokemon one by one: species, level, held item, moves, ability
- Review each one before confirming
- Add up to 6 Pokemon

**Step 3: Dialogue**
- Which map the trainer appears on
- Intro text (what they say before battle)
- Defeat text (what they say after losing)
- Long text is auto-wrapped to GBA textbox limits

**Step 4: Script Insertion**
- Optionally adds a `trainerbattle` line to one of your .txt scripts

After confirming, TORCH writes to:
- `include/constants/opponents.h` (trainer constant)
- `src/data/trainers.party` (trainer data)
- Your workspace (battle text `.pory` file)

Then sync the map and build to get the trainer in the game.

### Editing and Deleting

Open any trainer from the list or recent panel. Custom trainers can be fully edited — name, party, dialogue, everything. Vanilla trainers are read-only (you can only delete them).

Deletion scans all game files for references, shows what will be cleaned up, and requires typing the trainer name in UPPERCASE to confirm.

### Format Migration

If your project uses the old `.h` trainer format:

```
torch battle migrate
```

This converts all trainers to the newer `.party` format.

---

## 8. SCORCH

SCORCH (**S**elective **C**ontent **O**bliteration and **R**efactoring for **C**lean **H**acks) removes vanilla content you don't need.

Every pokeemerald-expansion project starts with ~500 vanilla maps, ~850 trainers, the entire Battle Frontier, and hundreds of other assets cluttering your workspace. SCORCH scans everything, figures out what's safe to remove, and surgically deletes it.

```
torch scorch                Full-scan wizard
torch scorch maps           Scan and remove vanilla maps only
torch scorch trainers       Scan and remove vanilla trainers only
torch scorch report         Scan-only report (no removal)
torch scorch restore        Restore from a SCORCH snapshot
```

Or press `[5]` from the main menu.

### How It Works

1. **Scan** — SCORCH scans all content categories: maps, trainers, encounters, Battle Frontier, shared scripts, tilesets, graphics, music
2. **Cross-reference** — Every item is checked against your custom content. If anything you made uses it, it's marked BLOCKED
3. **Review** — Results show SAFE/BLOCKED badges. You choose what to remove
4. **Snapshot** — Before deleting anything, SCORCH creates a restorable backup
5. **Remove** — Selected items are surgically removed from game files
6. **Build** — TORCH offers to rebuild so you can verify everything works

### Categories

| Category | What It Removes |
|----------|----------------|
| Maps | Vanilla map directories, JSON entries, layout files |
| Trainers | Trainer constants, party data, battle text |
| Encounters | Wild encounter table entries |
| Frontier | Battle Frontier data and references |
| Scripts | Shared vanilla script files |
| Tilesets | Unused tileset directories and header references |
| Graphics* | (Scan only — removal not yet implemented) |
| Music* | (Scan only — removal not yet implemented) |

### Browsing Without Removing

From the results screen, press `c` to browse categories. You can explore every item, see what references it, and understand the dependency chain — without removing anything. Press `q` to back out.

The Map Groups explorer (`p` from results) shows vanilla maps organized by town cluster with warp and connection info — useful for understanding map relationships.

### Restoring

If a removal causes problems:

```
torch scorch restore
```

Pick the snapshot from before the removal. TORCH restores all files and offers to rebuild.

---

## 9. Building Your ROM

### The Build Command

```
torch build
```

Or press `[b]` from the main menu.

TORCH's build command does more than just `make`:

1. **Auto-syncs stale maps** — If any enrolled maps have been edited since the last sync, TORCH syncs them first
2. **Runs the build** — Executes `make` with parallel jobs
3. **Diagnoses errors** — If the build fails, TORCH reads the error output and prints a human-readable explanation
4. **Creates a verified snapshot** — After every successful build, TORCH saves a restorable backup of all game files it manages

### Error Diagnosis

When a build fails, TORCH identifies common problems:

| Error | TORCH Says |
|-------|-----------|
| `stddef.h: No such file` | GCC header missing — run `fixdev` |
| `region 'rom' overflowed` | ROM too large — remove unused content |
| `No rule to make target` (maps) | Missing map file — was it deleted? |
| `.pory: error` | Poryscript syntax error (file and line shown) |
| `undeclared` | Undeclared constant — check spelling |
| `expected ... before` | C syntax error |

### Auto-Build

After safe operations (sync, restore), TORCH can build automatically without asking. This is controlled by the `auto_build` setting (default: on). Destructive operations always prompt.

### Shell Aliases

For quick builds without TORCH's wrapper:

```
bb                          Fast build (make -j)
bbc                         Clean build (make clean && make -j)
```

---

## 10. Backups and Restore

TORCH has three layers of backup protection.

### Layer 1: Workspace Snapshots

Every time you sync a map, TORCH creates a ZIP of your entire workspace folder for that map. Keeps the last 10 per map (configurable).

Restore with:
```
torch restore MapName
```

This shows a list of snapshots with timestamps. Pick one, and TORCH:
1. Saves your current state to `backups/overwritten/` (safety net)
2. Wipes the workspace and extracts the snapshot
3. Auto-syncs the restored files to the game
4. Offers to build

If the restore fails mid-extraction, TORCH automatically rolls back to your pre-restore state.

### Layer 2: Verified Build Snapshots

After every successful build triggered by TORCH, a snapshot of all managed game files is saved. Keeps the last 3 (configurable).

Nuclear restore:
```
torch restore
```

(No map name = verified restore, not workspace restore.)

This restores `data/maps/`, `data/layouts/`, `src/data/`, `include/constants/`, and `data/event_scripts.s` to the state of a previous working build.

### Layer 3: SCORCH Snapshots

Before any SCORCH removal, a snapshot of all affected files is created. Restorable with:
```
torch scorch restore
```

### TORCH Vault

The Vault (`[4]` from main menu or `torch backup`) manages TORCH's own backups — the tool itself, not your game files. Useful if a TORCH update breaks something.

---

## 11. Configuration

```
torch config
```

Opens the Config Manager for managing projects and settings.

### Settings

| Setting | Default | What It Does |
|---------|---------|-------------|
| `max_snapshots` | 10 | Workspace snapshots kept per map |
| `max_verified_snapshots` | 3 | Verified build snapshots kept |
| `auto_build` | true | Skip "Build now?" prompt after safe operations |
| `level_cap` | 100 | Max Pokemon level in trainer wizard |
| `textbox_warning` | 3 | Warn when dialogue exceeds this many boxes |
| `favourite_project` | (none) | Auto-load this project on launch |
| `nav_up` / `nav_down` | u / j | Navigation keys in scrolling lists |
| `editor_visible_beats` | 20 | Beats visible in scene editor |
| `editor_context` | compact | Context line mode (compact/detail/off) |

Settings are stored in `~/.config/torch/torch.conf` under the `[torch]` section.

---

## 12. Quick Reference

### Commands

| Command | What It Does |
|---------|-------------|
| `torch` | Main menu |
| `torch init` | First-time setup |
| `torch sync MapName` | Sync one map |
| `torch sync` | Sync all enrolled maps |
| `torch build` | Build ROM (auto-syncs stale maps first) |
| `torch restore MapName` | Workspace snapshot restore |
| `torch restore` | Verified build restore (nuclear) |
| `torch scene` | Script Studio hub |
| `torch scene Map Scene` | Open specific scene in editor |
| `torch battle` | Trainers module |
| `torch battle migrate` | Migrate .h trainers to .party |
| `torch scorch` | SCORCH full-scan wizard |
| `torch scorch report` | Scan-only report |
| `torch scorch restore` | Restore from SCORCH snapshot |
| `torch status` | Show enrolled maps with health |
| `torch enroll MapName` | Enroll a map |
| `torch enroll --all` | Enroll all maps |
| `torch unenroll MapName` | Unenroll a map |
| `torch studio` | ROM Studio (title, game code) |
| `torch config` | Config Manager |
| `torch backup` | Back up TORCH itself |
| `torch sandbox` | Dev Sandbox (dev build only) |

### Map Health Indicators

| Badge | Meaning |
|-------|---------|
| `[OK]` | In sync — workspace matches last write |
| `[STALE]` | Workspace edited since last sync |
| `[DRIFT]` | Game file edited outside TORCH |
| `[ORPHAN]` | No game folder found |
| `[MISSING WS]` | No workspace folder |
| `[NEW]` | Enrolled but never synced |

### TorScript Cheat Sheet

```
# Actors
alias buster npc5

# Messages
msg "Hello!$"
msgnpc "NPC-style message.$"

# Movement
buster walk up 3
buster face player
buster jump down 2
buster do MyMovement
player walk left 2 + buster walk right 2

# Emotes
buster emote !
buster emote heart

# Screen
fade black
fade in

# Sound
sound SE_EXIT
music MUS_ROUTE101
fanfare MUS_OBTAIN_ITEM
cry SPECIES_PIKACHU

# Timing
pause
pause long
pause 60

# Flags & Vars
flag set FLAG_MY_EVENT
flag clear FLAG_MY_EVENT
var VAR_MY_STATE 1
gotoif FLAG_MY_EVENT MyLabel

# Objects
hide buster
show buster
setpos buster 10 20

# Flow
label MyLabel
lock
faceplayer
end
release
goto OtherLabel
call Subroutine
return

# Pass-through
pory release
pory end
raw some_poryscript_command()
```

---

## 13. Troubleshooting

### "No config found"
Run `torch init` to create your config file.

### Build fails with "stddef.h: No such file"
Your GCC headers were wiped by a system update. Run `fixdev` to restore them.

### Build fails with "region 'rom' overflowed"
Your ROM is too large. Use SCORCH to remove unused vanilla content.

### "Duplicate label" build error
Two scripts define the same label. Check `setup.pory` and `legacy.pory` — if a legacy map already defines mapscripts, either remove the old block or use the same label name.

### Sync shows label warnings
A `goto`, `call`, or `trainerbattle` target doesn't exist. Check for typos in label names, or make sure the target label is defined somewhere in the same map's workspace.

### Unicode ellipsis crash
Never use the Unicode ellipsis character (`...`) in dialogue. Always use three separate dots (`...`). The GBA assembler can't handle Unicode.

### Trainer name rejected
Trainer display names are limited to 7 characters. This is a GBA hardware limitation.

### Porymap doesn't show my changes
After syncing, you may need to close and reopen the map in Porymap for changes to appear. TORCH writes to `scripts.pory`, but Porymap caches the old version until you reload.

### Can't undo a SCORCH removal
Run `torch scorch restore` and select the snapshot from before the removal. TORCH always creates a snapshot before deleting anything.

### "Already enrolled" or "Not enrolled" errors
Check your registry with `torch status`. Enroll maps with `torch enroll MapName`, unenroll with `torch unenroll MapName`.

---

*TORCH — The Open ROM Creation Hub*
*Making ROM hacking accessible, one wizard at a time.*
