"""Battle format migrator — .h to .party conversion."""
# TORCH_MODULE: Format Migrator
# TORCH_GROUP: Trainers
import os
import re
import zipfile
from datetime import datetime

from torch import BATTLE_VERSION
from torch.names import (
    _detect_trainer_format, _const_to_human_name, _human_name_to_const,
    _ai_flags_to_party_format, _party_ai_to_const,
    _format_stat_spread, _parse_stat_spread,
)
from torch.battle_io import (
    _read_party_file, _parse_party_section, _read_trainer_record,
    _read_trainer_record_party, _serialize_party_trainer,
)
from torch.ui import _offer_build, print_logo, _fmt_class, clear_screen
from torch.colours import GOLD, WHITE, CYAN, DIM, RST, BAR


def _restore_migration_backup(game_path, backup_path):
    """Restore trainer files from a pre-migration backup ZIP.
    Deletes trainers.party if it wasn't in the backup (reverting to legacy format).
    Strips the gTrainers[] array wrapper from trainers.h if present, since
    the expansion's data.c provides its own wrapper for the #include.
    Returns list of restored files, or None on error."""
    party_path = os.path.join(game_path, "src", "data", "trainers.party")
    trainers_h_rel = os.path.join("src", "data", "trainers.h")
    trainers_h_path = os.path.join(game_path, trainers_h_rel)
    try:
        restored = []
        with zipfile.ZipFile(backup_path, "r") as zf:
            archive_members = zf.namelist()
            for member in archive_members:
                target = os.path.join(game_path, member)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                restored.append(member)
        # Strip gTrainers[] wrapper from trainers.h if present.
        # The expansion's data.c declares the array itself and #includes
        # trainers.h for entries only.  Backed-up .h files from legacy
        # format have a standalone wrapper that causes a duplicate
        # declaration error.  Also remove the TRAINER_NONE entry since
        # data.c provides its own.
        if trainers_h_rel in archive_members and os.path.exists(trainers_h_path):
            with open(trainers_h_path) as f:
                content = f.read()
            if content.lstrip().startswith("const struct Trainer gTrainers[]"):
                lines = content.split("\n")
                # Remove first line (array declaration)
                if lines and "gTrainers" in lines[0]:
                    lines = lines[1:]
                # Remove last closing '};'
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i].strip() == "};":
                        lines.pop(i)
                        break
                # Remove TRAINER_NONE block (data.c already has it)
                cleaned = []
                skip = False
                for line in lines:
                    if "[TRAINER_NONE]" in line:
                        skip = True
                        continue
                    if skip:
                        if line.strip() == "},":
                            skip = False
                            continue
                        continue
                    cleaned.append(line)
                # Strip leading blank lines
                while cleaned and not cleaned[0].strip():
                    cleaned.pop(0)
                with open(trainers_h_path, "w") as f:
                    f.write("\n".join(cleaned))
                restored.append(f"{trainers_h_rel} (wrapper stripped)")
        # If trainers.party wasn't in the backup but exists now, delete it
        party_rel = os.path.join("src", "data", "trainers.party")
        if party_rel not in archive_members and os.path.exists(party_path):
            os.remove(party_path)
            restored.append(f"{party_rel} (deleted)")
        return restored
    except Exception as e:
        print(f"  ERROR during migration restore: {e}")
        return None


def _run_battle_format_migrator(game_path, proj_name=None):
    """
    Migrate all trainers from legacy .h files to trainers.party format.
    Dry-run preview first, then writes .party and cleans up .h files.
    """
    clear_screen()
    print_logo(f"Battle Migrator  v{BATTLE_VERSION}", proj_name)
    print(BAR)
    print(f"   {WHITE}LEGACY .h  \u2192  trainers.party FORMAT MIGRATION{RST}")
    print(BAR)
    print()

    opponents_path       = os.path.join(game_path, "include", "constants", "opponents.h")
    trainers_h_path      = os.path.join(game_path, "src", "data", "trainers.h")
    trainer_parties_path = os.path.join(game_path, "src", "data", "trainer_parties.h")
    party_path           = os.path.join(game_path, "src", "data", "trainers.party")

    # ---- Sanity checks ----
    fmt = _detect_trainer_format(game_path)
    if fmt == "party":
        print("  Your project already uses trainers.party format.")
        print("  Nothing to migrate.")
        print()
        input("  Press Enter to go back > ")
        return

    if not os.path.exists(trainers_h_path):
        print(f"  ERROR: trainers.h not found at:")
        print(f"    {trainers_h_path}")
        print()
        input("  Press Enter to go back > ")
        return

    if not os.path.exists(trainer_parties_path):
        print(f"  ERROR: trainer_parties.h not found at:")
        print(f"    {trainer_parties_path}")
        print()
        input("  Press Enter to go back > ")
        return

    # ---- Gather all trainer consts from opponents.h ----
    if not os.path.exists(opponents_path):
        print(f"  ERROR: opponents.h not found at:")
        print(f"    {opponents_path}")
        print()
        input("  Press Enter to go back > ")
        return

    trainer_consts = []
    with open(opponents_path) as f:
        for line in f:
            m = re.match(r"^#define\s+(TRAINER_\w+)\s+(\d+)", line)
            if m:
                const_name = m.group(1)
                const_id = int(m.group(2))
                # Skip meta-defines
                if const_name in ("TRAINERS_COUNT", "MAX_TRAINERS_COUNT", "TRAINER_NONE"):
                    continue
                trainer_consts.append((const_name, const_id))

    if not trainer_consts:
        print("  No trainer defines found in opponents.h (besides TRAINER_NONE).")
        print("  Nothing to migrate.")
        print()
        input("  Press Enter to go back > ")
        return

    # ---- Read all trainer records ----
    records = []
    warnings = []
    for const_name, const_id in trainer_consts:
        rec = _read_trainer_record(const_name, opponents_path, trainers_h_path, trainer_parties_path)
        if rec is None or rec.get("trainer_name") is None:
            warnings.append(f"  {const_name} (ID {const_id}): no data in trainers.h — skipped")
            continue
        if not rec.get("mons"):
            warnings.append(f"  {const_name} (ID {const_id}): no party data — will migrate header only")
        records.append(rec)

    # ---- Dry-run preview ----
    print(f"  Found {len(trainer_consts)} trainer define(s) in opponents.h")
    print(f"  Readable records: {len(records)}")
    if warnings:
        print(f"  Warnings: {len(warnings)}")
    print()

    if records:
        print("  Trainers to migrate:")
        print()
        for rec in records:
            name = rec.get("trainer_name") or "?"
            cls = _fmt_class(rec.get("trainer_class")) if rec.get("trainer_class") else "?"
            n_mons = len(rec.get("mons") or [])
            print(f"    {rec['trainer_const']:<36} {cls:<22} \"{name}\"  ({n_mons} mon{'s' if n_mons != 1 else ''})")
        print()

    if warnings:
        print("  Warnings:")
        for w in warnings:
            print(w)
        print()

    if os.path.exists(party_path):
        print(f"  NOTE: trainers.party already exists — migrated trainers will be appended.")
        print()

    if not records:
        print("  No records to migrate.")
        print()
        input("  Press Enter to go back > ")
        return

    # ---- Confirm ----
    print(f"  This will:")
    print(f"    1. Write {len(records)} trainer(s) to trainers.party")
    print(f"    2. Remove their blocks from trainers.h")
    print(f"    3. Remove their parties from trainer_parties.h")
    print(f"    4. opponents.h stays UNCHANGED (IDs are format-independent)")
    print()
    confirm = input("  Proceed with migration? [y/N] > ").strip().lower()
    if confirm != "y":
        print("  Migration cancelled.")
        print()
        input("  Press Enter to go back > ")
        return

    # ---- Pre-migration snapshot ----
    print()
    print("  Creating pre-migration backup ...")
    migration_backup_dir = os.path.join(game_path, "backups", "migrations")
    os.makedirs(migration_backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_name = f"pre_migration_{timestamp}.zip"
    snapshot_path = os.path.join(migration_backup_dir, snapshot_name)
    files_to_backup = [
        os.path.join("src", "data", "trainers.h"),
        os.path.join("src", "data", "trainer_parties.h"),
        os.path.join("src", "data", "trainers.party"),
    ]
    try:
        with zipfile.ZipFile(snapshot_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path in files_to_backup:
                abs_path = os.path.join(game_path, rel_path)
                if os.path.exists(abs_path):
                    zf.write(abs_path, rel_path)
        print(f"    Snapshot: {snapshot_path}")
        # Auto-prune: keep only the latest migration backup
        existing = sorted([
            f for f in os.listdir(migration_backup_dir)
            if f.startswith("pre_migration_") and f.endswith(".zip")
        ])
        while len(existing) > 1:
            old = existing.pop(0)
            os.remove(os.path.join(migration_backup_dir, old))
            print(f"    Pruned old backup: {old}")
    except Exception as e:
        print(f"  ERROR: Failed to create pre-migration backup: {e}")
        print("  Migration ABORTED — no files were modified.")
        print()
        input("  Press Enter to go back > ")
        return
    print()

    # ---- Phase 1: Write to trainers.party (non-destructive) ----
    print()
    print("  Phase 1: Writing trainers.party ...")
    migrated = 0
    for rec in records:
        block = _serialize_party_trainer(rec)
        with open(party_path, "a") as f:
            f.write("\n" + block + "\n")
        migrated += 1
    print(f"    Wrote {migrated} trainer(s) to trainers.party")

    # ---- Phase 2: Remove from trainers.h ----
    print()
    print("  Phase 2: Cleaning trainers.h ...")
    h_removed = 0
    if os.path.exists(trainers_h_path):
        with open(trainers_h_path) as f:
            content = f.read()
        for rec in records:
            tc = rec["trainer_const"]
            block_pattern = (
                r"\n?\s*\[" + re.escape(tc) + r"\]\s*=\s*\n\s*\{"
                r".*?"
                r"\n\s*\},"
            )
            content, count = re.subn(block_pattern, "", content, flags=re.DOTALL)
            if count > 0:
                h_removed += count
        with open(trainers_h_path, "w") as f:
            f.write(content)
    print(f"    Removed {h_removed} block(s) from trainers.h")

    # ---- Phase 3: Remove from trainer_parties.h ----
    print()
    print("  Phase 3: Cleaning trainer_parties.h ...")
    p_removed = 0
    if os.path.exists(trainer_parties_path):
        with open(trainer_parties_path) as f:
            content = f.read()
        for rec in records:
            party_const = rec.get("party_const")
            if not party_const:
                continue
            pp = (
                r"static\s+const\s+struct\s+TrainerMon\s+" + re.escape(party_const)
                + r"\[\]\s*=\s*\{.*?\};\n?"
            )
            content, count = re.subn(pp, "", content, flags=re.DOTALL)
            if count > 0:
                p_removed += count
        with open(trainer_parties_path, "w") as f:
            f.write(content)
    print(f"    Removed {p_removed} party array(s) from trainer_parties.h")

    # ---- Summary ----
    print()
    print("  " + "━" * 49)
    print(f"   MIGRATION COMPLETE")
    print(f"   {migrated} trainer(s) migrated to trainers.party")
    if warnings:
        print(f"   {len(warnings)} warning(s) — see above")
    print("  " + "━" * 49)
    print()
    print("  Your project now uses trainers.party format.")
    print("  TORCH will auto-detect the format on next launch.")
    print()
    _offer_build(game_path)


def _read_record_dispatch(trainer_const, fmt, opponents_path, trainers_h_path,
                          trainer_parties_path, party_path):
    """Read a trainer record using the correct backend for the format."""
    if fmt == "party":
        return _read_trainer_record_party(trainer_const, party_path, opponents_path)
    else:
        return _read_trainer_record(trainer_const, opponents_path, trainers_h_path, trainer_parties_path)


def _is_orphaned_trainer(record):
    """Return True if a trainer record has no game-file data (workspace-only)."""
    if record is None:
        return True
    return (record.get("trainer_id") is None and
            record.get("trainer_name") is None and
            record.get("trainer_class") is None)


def _handle_orphan_prompt(trainer_const, pory_path):
    """Show orphan message and offer quick-delete. Returns True if deleted."""
    print()
    print(f"  {trainer_const} is orphaned -- workspace file exists but not in game files.")
    print("  This usually means it was only partially created.")
    print()
    choice = input("  [d] Delete workspace file  [Enter] Go back > ").strip().lower()
    if choice == "d":
        if os.path.exists(pory_path):
            os.remove(pory_path)
            print(f"  Deleted: {os.path.basename(pory_path)}")
        else:
            print(f"  File already removed.")
        print()
        input("  Press Enter to continue > ")
        return True
    return False
