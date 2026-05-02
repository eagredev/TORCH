# Changelog

## v0.4.0
- TORCH Studio: trigger event editing, standalone app mode
- SCORCH: cancel button during phoenix/singe operations
- Music player widget in Studio status bar
- Dex status bar widget with gen/type filter chips
- Studio UX: Dex widget, collision overlay, NPC detail refinement

## v0.3.9
- Music browser: full GBA-accurate playback via poryaaaa, built-in MIDI synth fallback
- Music browser integrated into Studio and asset browser

## v0.3.8
- Studio UX pass: Dex widget, collision overlay, NPC detail panel refinement

## v0.3.7
- Custom stamp system
- Studio unification: dashboard homepage + unified workspace
- Vanilla NPC auto-decompile (click any vanilla NPC → "Convert to Editable")
- Music plugin foundation

## v0.3.6
- TORCH Studio: 8-tab right panel (Props/NPCs/Enc/Warps/Scripts/Flags/Shops/Trainers)
- Inline event editing (full Porymap parity)
- Scripts Mode with suspend/restore
- Worldstate Simulator (toggle flags → see NPC states update live on canvas)
- NPC Pages (`page N if FLAG_X` — RPG Maker-style multi-state NPCs)
- Web NPC Editor: full CRUD, 7 creation wizards, overworld sprite preview
- Building Templates (`torch template pokecenter/pokemart`)
- Tileset importer (cross-decomp, e.g. FireRed → Emerald)
- Decompiler overhaul: full Poryscript coverage, 86% line reduction on typical vanilla scripts
- `.inc` decompiler: 468/468 vanilla files supported
- Phase 10 web views: Flags, Items, Moves, Shops, Learnsets, Heal Locations, Map Explorer, Asset Browser, SCORCH GUI, Vault snapshots

## v0.3.2 — Initial public commit
- TorScript compiler and sync engine
- TUI with scrolling menus and script studio
- Web GUI foundation (trainers, encounters, dex, flags, shops)
- SCORCH Singe and Phoenix (selective and full vanilla content removal)
- Multi-project config, expansion version detection (v1.6.0 through latest)
- Build assistant with pre-build safety chain
- Tiered backup system with verified build snapshots
