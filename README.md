# TORCH

**The Open ROM Creation Hub** — a TorScript compiler, sync engine, data editors, and localhost web IDE for [pokeemerald](https://github.com/pret/pokeemerald) and [pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion) ROM hacks.

TORCH replaces the scattered workflow of manual file editing, terminal commands, and cross-referencing documentation with a single unified tool. Write scripts in simplified TorScript, manage trainers and encounters through guided editors, and build your ROM — all without touching a line of C.

---

## Features

### TorScript

TorScript is TORCH's own scripting language — a simplified, human-readable alternative to writing Poryscript or raw assembly by hand. TORCH compiles it down to Poryscript automatically.

Instead of wrangling `applymovement`, `waitmovement`, `msgbox`, and constant lookups, you write what you mean:

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
- **Dialogue** — just write text in quotes. Line breaks, text boxes, and string labels are managed automatically
- **Movement** — `buster walk up 3` instead of defining movement data arrays and calling `applymovement`/`waitmovement`
- **Parallel movement** — `buster face down + player face down` moves multiple actors simultaneously
- **Walk-to** — `clyde walkto player 0 1` dynamically walks an NPC to a target at runtime
- **Camera** — `camera pan down 3` and `camera reset` with automatic offset tracking
- **Emotes** — `emote buster !` instead of looking up `EMOTE_EXCLAMATION_MARK` constants
- **Give items** — `give ITEM_POTION 3` with automatic bag-full safety check
- **Flags & vars** — `flag set FLAG_NAME`, `gotoif FLAG_NAME Label`
- **Sound** — `sound SE_EXIT`, `music MUS_ROUTE101`, `cry SPECIES_KOFFING`, `fanfare MUS_OBTAIN_ITEM`
- **Screen effects** — `fade black`, `fade in`, `shake 1 8`
- **NPC management** — `hide buster`, `show buster`, `setpos clyde 28 62`
- **Pass-through** — `pory somecommand(args)` for anything TorScript doesn't cover yet

The compiler validates flag names, species, items, moves, music, and sound effects against your game's actual header files before building — so you catch typos at compile time, not after a 5-minute ROM build.

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
