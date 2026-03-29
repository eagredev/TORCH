# TORCH

**The Open ROM Creation Hub** — a TorScript compiler, sync engine, data editors, and localhost web IDE for [pokeemerald](https://github.com/pret/pokeemerald) and [pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion) ROM hacks.

TORCH replaces the scattered workflow of manual file editing, terminal commands, and cross-referencing documentation with a single unified tool. Write scripts in simplified TorScript, manage trainers and encounters through guided editors, and build your ROM — all without touching a line of C.

---

## Features

### TorScript Compiler
Write game scripts in a simplified, human-readable format — TORCH compiles them to Poryscript automatically.

```
@ Buster
    "Hey, have you seen my Poochyena?"
    "I lost him near the lake..."
    emote buster !
    pause 30
    "Oh wait, there he is!"
```

### Sync Engine
Manages the pipeline from your workspace to the game project. Tracks map health (`ok`, `stale`, `drift`, `orphan`, `new`), snapshots before every sync, and auto-detects when files change outside TORCH.

### Web IDE (`torch studio --web`)
A full localhost web interface with 19 views:

- **Dashboard** — project overview and quick actions
- **Studio** — map workspace with script editing
- **Script Editor** — beat-based visual script editor with GBA dialogue preview
- **Dex** — searchable Pokemon browser with stats, learnsets, and evolution chains
- **Trainers** — party editor with species picker and AI flag configuration
- **Encounters** — wild Pokemon editor with route/slot management
- **Map Explorer** — SVG connectivity graph of your game world
- **NPC Editor** — dialogue editing with wizard-guided NPC creation
- **Flags / Items / Moves / Shops / Learnsets** — data editors
- **SCORCH** — vanilla content removal (selective or full phoenix)
- **Templates** — stamp complete building interiors from a single command
- **Project Management** — backups, forks, version info

Three colour themes: Torch (orange), Porygon (pink), and Emerald (green).

### TUI (Terminal Interface)
Everything also works from the terminal. Scrolling list menus, inline editors, and a full script studio — no browser required.

### SCORCH
Remove vanilla content you don't need. Two modes:
- **Singe** — selective removal by category (maps, trainers, encounters, etc.)
- **Phoenix** — full wipe of all vanilla maps, trainers, and encounters. Tested across every expansion version from v1.6.0 to latest.

### Building Templates
`torch template pokecenter ParentMap --door X,Y` stamps a complete PokeCentre or PokeMart interior — layout, scripts, warp connections, heal location registration — from a single command.

### And More
- **Decompiler** — convert existing `.pory` scripts back to TorScript
- **Map Registry** — enroll maps, track sync status, detect drift
- **Flag Scanner** — cross-reference flags across scripts, reclaim orphans
- **Tileset Assistant** — import tilesets from other decomps (e.g. FireRed)
- **Expansion Compatibility** — supports pokeemerald-expansion v1.6.0 through latest, plus vanilla pokeemerald
- **Build Assistant** — one-command ROM builds with pre-build safety checks and error diagnosis
- **Verified Snapshots** — automatic backups after every successful build

---

## Requirements

- Python 3.11+ (stdlib only — no pip dependencies)
- A [pokeemerald](https://github.com/pret/pokeemerald) or [pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion) (v1.6.0+) project
- [Poryscript](https://github.com/huderlem/poryscript) compiler
- devkitPro toolchain (for building the ROM)

---

## Quick Start

```bash
# Clone the repo
git clone git@github.com:eagredev/TORCH.git ~/torch_dev

# Run first-time setup
python3 ~/torch_dev/ init

# Launch the web IDE
python3 ~/torch_dev/ studio --web

# Or use the terminal interface
python3 ~/torch_dev/
```

---

## Testing

4055 tests across 79 suites. Stdlib `unittest` only — no test framework dependencies.

```bash
# Run all tests
python3 ~/torch_dev/tests/run_tests.py

# Run a specific suite
python3 ~/torch_dev/tests/run_tests.py compiler

# Run a specific test
python3 ~/torch_dev/tests/run_tests.py compiler::test_basic_dialogue
```

---

## Architecture

- **77 production modules** organised across 8 dependency layers
- **16 web backend modules** (stdlib `http.server`, vanilla JS frontend)
- **52 JavaScript frontend files** (19 views, 28 beat editors, 5 utilities)
- Zero external dependencies — runs anywhere Python 3.11+ is available

---

## License

All rights reserved. This project is not yet open source.
