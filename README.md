# TORCH

**The Open ROM Creation Hub**

Write scripts, edit NPCs, manage trainers, and build ROMs for [pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion) hacks — all from one tool.

<!-- TODO: Screenshot of TORCH Studio showing a map with NPC editing panel open -->
<!-- Ideal: dark theme, real map loaded, right panel showing dialogue editing -->
<!-- Size: ~800px wide, PNG. This is the single most important image in the README. -->

TORCH is a CLI and web IDE for Pokemon Emerald ROM hacking. It sits on top of the decomp toolchain and handles the parts that currently require juggling between text editors, Poryscript docs, header files, and terminal commands. You write simplified scripts, TORCH compiles them. You edit trainers and encounters in a browser, TORCH writes the data files. You hit build, TORCH handles the rest.

No pip dependencies. No npm. Just Python and your pokeemerald project.

---

## What does it look like?

### Studio

<!-- TODO: Screenshot of Studio workspace — map canvas + right panel with tabs -->

A three-panel workspace inspired by Porymap and RPG Maker. Map canvas on the left, properties and editors on the right, toolbar on top. Eight editor tabs — Props, NPCs, Encounters, Warps, Scripts, Flags, Shops, Trainers — all in one window.

### Script Editor

<!-- TODO: Screenshot or short GIF of the beat-based script editor -->
<!-- Ideal GIF: click an NPC on canvas -> dialogue editor opens -> type dialogue -> GBA text preview updates live. ~10 seconds. -->

A visual script editor where you compose cutscenes through guided "beats" — dialogue, movement, emotes, camera work, sound — instead of writing Poryscript by hand. Live GBA text preview shows exactly how dialogue will look in-game.

### Terminal

<!-- TODO: Screenshot of TUI main menu or script studio -->

Everything also works from the terminal. Scrolling list menus, inline editors, and a full script studio. No browser required.

---

## TorScript

TorScript is TORCH's scripting language — a human-readable alternative to Poryscript. TORCH compiles it down automatically.

Instead of managing movement data arrays, `applymovement`/`waitmovement` calls, `msgbox` formatting, and constant lookups, you write what you mean:

```
@ Buster
alias buster npc5

label BusterScene
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

**What TorScript handles for you:**

| You write | Instead of |
|-----------|-----------|
| `"Hey there!"` | `msgbox` + format constants + auto-generated string labels |
| `buster walk up 3` | Movement data arrays + `applymovement` + `waitmovement` |
| `buster face down + player face down` | Separate movement blocks + `waitmovement` for each |
| `emote buster !` | Looking up `EMOTE_EXCLAMATION_MARK` |
| `give ITEM_POTION 3` | `giveitem` + bag-full check branching |
| `camera pan down 3` | `setcamerafocus` + offset tracking across the script |
| `clyde walkto player 0 1` | Runtime coordinate calculation + loop labels |
| `pory somecommand(args)` | Direct pass-through for anything TorScript doesn't cover |

The compiler validates flag names, species, items, moves, music, and sound effects against your game's actual header files. Typos are caught at compile time, not after a 5-minute ROM build.

---

## Features

### Workspace and Sync
- **Map registry** — enroll maps, track health (`ok` / `stale` / `drift` / `orphan` / `new`)
- **Sync engine** — compile TorScript, snapshot before every write, deploy to your game project
- **Build assistant** — one-command ROM builds with pre-build safety checks and error diagnosis
- **Verified snapshots** — automatic backups after every successful build

### Editors (Web GUI)
- **NPC Editor** — dialogue editing, 7 creation wizards (flavor NPC, sign, item giver, nurse, etc.), overworld sprite preview
- **Trainers** — party builder with species picker, AI flags, EV/IV spreads, held items
- **Encounters** — wild Pokemon by route, slot, and time-of-day variant
- **Dex** — searchable Pokemon browser with stats, learnsets, evolution chains, shiny sprites
- **Flags** — cross-reference scanner, orphan reclamation, bulk operations
- **Items / Moves / Shops / Learnsets / Heal Locations** — data editors

### Content Management
- **SCORCH Singe** — selective vanilla content removal by category
- **SCORCH Phoenix** — full wipe of all vanilla maps, trainers, and encounters. Tested across every expansion version from v1.6.0 to latest.
- **Building Templates** — `torch template pokecenter Route101 --door 10,5` stamps a complete PokeCentre or Mart interior with layout, scripts, warps, and heal registration in one command
- **Tileset Assistant** — import tilesets from other decomps (e.g. FireRed)
- **Decompiler** — convert existing `.pory` and `.inc` scripts back to TorScript. Click a vanilla NPC in Studio and hit "Convert to Editable."

### Project Lifecycle
- **Multi-project support** — switch between ROM hacks via config
- **Expansion compatibility** — auto-detects your expansion version and gates features accordingly (v1.6.0 through latest, plus vanilla pokeemerald)
- **Backups** — tiered retention (hourly, daily, weekly, monthly) with verified build snapshots
- **Project forking** — clone your project for experimentation without risk
- **Music browser** — preview game tracks with GBA-accurate rendering

### Architecture
- **21 web views**, 3 colour themes (Torch, Porygon, Emerald)
- **86 production modules** across 8 dependency layers
- **4,300+ tests** across 83 suites
- Zero external dependencies — stdlib Python only
- Works from the terminal (TUI) or browser (web GUI)

---

## Requirements

- **Python 3.11+** (stdlib only — nothing to install)
- A [pokeemerald](https://github.com/pret/pokeemerald) or [pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion) v1.6.0+ project
- [Poryscript](https://github.com/huderlem/poryscript) compiler
- [devkitPro](https://devkitpro.org/) toolchain (for building the ROM)

---

## Quick Start

```bash
# Clone TORCH
git clone https://github.com/eagredev/TORCH.git ~/torch

# First-time setup — detects your project and creates config
python3 ~/torch init

# Open the web IDE
python3 ~/torch studio

# Or use the terminal interface
python3 ~/torch
```

### Basic workflow

```bash
# Enroll your maps so TORCH can track them
python3 ~/torch enroll --all

# Open a map in Studio, edit NPCs and scripts visually
python3 ~/torch studio

# Or compile a single TorScript file
python3 ~/torch MyScript.txt

# Sync a map (compile + snapshot + deploy to game project)
python3 ~/torch sync Route101

# Build the ROM
python3 ~/torch build
```

---

## Commands

| Command | What it does |
|---------|-------------|
| `torch` | Main menu |
| `torch studio` | Web IDE |
| `torch script MapName` | Script editor for a specific map |
| `torch sync [MapName]` | Compile and deploy (all enrolled maps or one) |
| `torch build` | Build the ROM with auto-sync and error diagnosis |
| `torch status` | Show enrolled maps with health indicators |
| `torch enroll [--all]` | Register maps for tracking |
| `torch scorch` | SCORCH wizard (vanilla content removal) |
| `torch template` | Stamp building interiors from templates |
| `torch trainers` | Trainer editor |
| `torch encounters` | Encounter editor |
| `torch music` | Music browser and preview |
| `torch flags [MapName]` | Flag browser and scanner |
| `torch shops [MapName]` | Shop editor |
| `torch config` | Configuration manager |
| `torch restore` | Restore from backup |
| `torch decompile file` | Convert .pory to TorScript |

---

## Documentation

Full manual: [`manual.md`](manual.md)
TorScript syntax: [`config/syntax_reference.txt`](config/syntax_reference.txt)

---

## Built on

TORCH builds on the incredible work of the decomp community:

- [pret/pokeemerald](https://github.com/pret/pokeemerald) — the decompilation that makes all of this possible
- [rh-hideout/pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion) — modern battle engine and features
- [huderlem/poryscript](https://github.com/huderlem/poryscript) — the scripting language TORCH compiles to
- [huderlem/porymap](https://github.com/huderlem/porymap) — the map editor that inspired Studio's design

---

## License

All rights reserved. Not yet open source — public release coming soon.
