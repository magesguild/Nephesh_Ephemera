#!/usr/bin/env python3
"""
Snapshot — memory backup and restore verification.

Part of the 3.0.0 memory rebuild (docs/MEMORY_REBUILD_SPEC.md §6).
Two artifacts per snapshot:
  1. Full tar.gz of the LanceDB directory (everything: memories,
     introspections, study, foundation, cosmology).
  2. JSONL export of the configured memory collection (id, text,
     metadata_json) — human-readable, greppable, and the working
     input format for the rebuild's rewrite phases.

Retention: keeps the newest N daily snapshots and one snapshot per
ISO week for the last M weeks (defaults 7 and 8, per spec). Pruning
only ever touches files matching this script's own naming pattern.

A backup that has never been restored is a hope, not a backup:
`--verify` extracts the newest tar to a temp dir, opens it with
LanceDB, and compares row counts against the live database.

Usage:
  ./scripts/snapshot.py                 # take a snapshot, prune old ones
  ./scripts/snapshot.py --verify        # snapshot + restore test
  ./scripts/snapshot.py --verify-only   # restore-test newest existing snapshot
  ./scripts/snapshot.py --keep-daily 7 --keep-weekly 8
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.mcp_experiments.config import settings  # noqa: E402

SNAP_PATTERN = re.compile(r"^lancedb_(\d{8})T(\d{6})Z\.tar\.gz$")
EXPORT_PATTERN = re.compile(r"^memory_export_(\d{8})T(\d{6})Z\.jsonl$")


def _backups_dir() -> Path:
    d = Path(settings.snapshot_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def take_snapshot() -> tuple[Path, Path, int]:
    """Create tar of the LanceDB dir + JSONL export of the memory
    collection. Returns (tar_path, export_path, memory_row_count)."""
    db_path = Path(settings.vector_db_path)
    if not db_path.exists():
        raise SystemExit(f"[snapshot] Vector DB path does not exist: {db_path}")

    ts = _timestamp()
    backups = _backups_dir()

    # 1. Full tar of the LanceDB directory
    tar_path = backups / f"lancedb_{ts}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(db_path, arcname=db_path.name)
    print(f"[snapshot] LanceDB tar: {tar_path} "
          f"({tar_path.stat().st_size / 1024 / 1024:.1f} MiB)")

    # 2. JSONL export of the memory collection
    import lancedb
    db = lancedb.connect(str(db_path))
    tables = db.list_tables().tables if hasattr(db.list_tables(), "tables") else db.table_names()
    export_path = backups / f"memory_export_{ts}.jsonl"
    count = 0
    coll = settings.memory_collection_name
    if coll in tables:
        table = db.open_table(coll)
        rows = table.to_arrow().to_pylist()
        with export_path.open("w") as f:
            for row in rows:
                record = {
                    "id": row.get("id"),
                    "text": row.get("text"),
                    "metadata_json": row.get("metadata_json"),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
        print(f"[snapshot] Memory export: {export_path} ({count} rows from '{coll}')")
    else:
        print(f"[snapshot] WARNING: memory collection '{coll}' not found; no export written")

    return tar_path, export_path, count


def verify_restore(tar_path: Path | None = None) -> bool:
    """Extract the newest (or given) tar into a temp dir, open with
    LanceDB, compare per-table row counts against the live DB."""
    backups = _backups_dir()
    if tar_path is None:
        candidates = sorted(p for p in backups.iterdir() if SNAP_PATTERN.match(p.name))
        if not candidates:
            print("[snapshot] VERIFY FAILED: no snapshots found")
            return False
        tar_path = candidates[-1]

    import lancedb
    live_db = lancedb.connect(str(settings.vector_db_path))
    live_tables = live_db.list_tables().tables if hasattr(live_db.list_tables(), "tables") else live_db.table_names()
    live_counts = {t: live_db.open_table(t).count_rows() for t in live_tables}

    with tempfile.TemporaryDirectory(prefix="snapshot_verify_") as tmp:
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(tmp, filter="data")
        restored_path = Path(tmp) / Path(settings.vector_db_path).name
        rest_db = lancedb.connect(str(restored_path))
        rest_tables = rest_db.list_tables().tables if hasattr(rest_db.list_tables(), "tables") else rest_db.table_names()
        rest_counts = {t: rest_db.open_table(t).count_rows() for t in rest_tables}

    ok = True
    for t, n in rest_counts.items():
        live_n = live_counts.get(t)
        status = "OK" if live_n == n else f"MISMATCH (live={live_n})"
        if live_n != n:
            # Live may legitimately have grown since the snapshot;
            # only a restored count EXCEEDING live is a hard failure.
            if live_n is None or n > live_n:
                ok = False
            else:
                status += " [live grew since snapshot — acceptable]"
        print(f"[verify] {t}: restored={n} {status}")

    print(f"[verify] {'PASSED' if ok else 'FAILED'} for {tar_path.name}")
    return ok


def prune(keep_daily: int, keep_weekly: int) -> None:
    """Keep the newest `keep_daily` snapshots plus one per ISO week for
    the last `keep_weekly` weeks. Exports are pruned alongside their
    tars. Never touches files not matching our naming pattern."""
    backups = _backups_dir()
    snaps = sorted(
        (p for p in backups.iterdir() if SNAP_PATTERN.match(p.name)),
        reverse=True,  # newest first
    )
    keep: set[Path] = set(snaps[:keep_daily])

    weekly_seen: set[str] = set()
    for p in snaps:
        m = SNAP_PATTERN.match(p.name)
        dt = datetime.strptime(m.group(1), "%Y%m%d")
        week = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        if week not in weekly_seen and len(weekly_seen) < keep_weekly:
            weekly_seen.add(week)
            keep.add(p)

    for p in snaps:
        if p not in keep:
            ts_part = SNAP_PATTERN.match(p.name).group(0).replace("lancedb_", "").replace(".tar.gz", "")
            export = backups / f"memory_export_{ts_part}.jsonl"
            p.unlink()
            if export.exists():
                export.unlink()
            print(f"[prune] removed {p.name}")


def main():
    parser = argparse.ArgumentParser(description="Memory snapshot / restore verification")
    parser.add_argument("--verify", action="store_true", help="Snapshot, then restore-test it")
    parser.add_argument("--verify-only", action="store_true", help="Restore-test newest existing snapshot")
    parser.add_argument("--keep-daily", type=int, default=7)
    parser.add_argument("--keep-weekly", type=int, default=8)
    args = parser.parse_args()

    if args.verify_only:
        sys.exit(0 if verify_restore() else 1)

    take_snapshot()
    prune(args.keep_daily, args.keep_weekly)

    if args.verify:
        sys.exit(0 if verify_restore() else 1)


if __name__ == "__main__":
    main()
