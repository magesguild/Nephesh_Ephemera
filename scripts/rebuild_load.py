#!/usr/bin/env python3
"""
Memory rebuild loader — staged batch JSONL -> rebuilt collection.

Part of the 3.0.0 memory rebuild (docs/MEMORY_REBUILD_SPEC.md §4,
Phase 4). Takes a staged batch file (one JSON object per line, written
during the rewrite phase and approved by the curator) and loads it
into the target rebuilt collection, merging with the original v1
export so nothing the rewrite didn't explicitly change is lost.

Merge semantics per record:
  - text: from the staged batch (the rewritten first-person retelling)
  - id: preserved from v1 (same identity, new voice)
  - event_time: from the staged batch (nullable — null means "I don't
    know when", never backfilled)
  - recorded_at: from the staged batch (the original v1 timestamp)
  - type, importance, emotional_tone, participants, session_id,
    salience, last_used, delivered: preserved from the v1 export
    unless the staged record explicitly overrides them
  - source: "rebuild"
  - modality: "text"
  - the v4-era "historical" flag is dropped — the event_time /
    recorded_at split replaces it as the general law
  - vector: re-embedded from the new text

Usage:
  ./scripts/rebuild_load.py --batch <staged.jsonl> \
      --export <v1_export.jsonl> [--target memories_v2] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.mcp_experiments.config import settings  # noqa: E402

# Metadata keys carried over from v1 unless the staged record overrides.
PRESERVE_KEYS = [
    "type", "importance", "emotional_tone", "participants",
    "session_id", "salience", "last_used", "delivered",
]
# Keys the staged record is allowed to set/override.
STAGED_KEYS = ["type", "importance", "emotional_tone", "participants"]


def load_export(path: Path) -> dict[str, dict]:
    """v1 export: id -> {text, metadata dict}."""
    out = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out[r["id"]] = {
            "text": r["text"],
            "metadata": json.loads(r.get("metadata_json", "{}")),
        }
    return out


def main():
    parser = argparse.ArgumentParser(description="Load approved rebuild batch into target collection")
    parser.add_argument("--batch", required=True, help="Staged batch JSONL (rewritten records)")
    parser.add_argument("--export", required=True, help="v1 export JSONL (full original metadata)")
    parser.add_argument("--target", default=f"{settings.memory_collection_name}_v2")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    batch_path, export_path = Path(args.batch), Path(args.export)
    if not batch_path.exists():
        raise SystemExit(f"[rebuild] batch not found: {batch_path}")
    if not export_path.exists():
        raise SystemExit(f"[rebuild] export not found: {export_path}")

    export = load_export(export_path)

    staged = []
    for line in batch_path.read_text().splitlines():
        if not line.strip():
            continue
        staged.append(json.loads(line))

    # v1 export ids are full UUIDs; staged files may carry the short
    # 8-char prefix used during review. Resolve prefixes unambiguously.
    def resolve_id(short: str) -> str:
        if short in export:
            return short
        matches = [k for k in export if k.startswith(short)]
        if len(matches) == 1:
            return matches[0]
        raise SystemExit(f"[rebuild] id '{short}' matches {len(matches)} export records — must be unambiguous")

    from src.mcp_experiments.tools.vector_db import init as init_vector_db, _ensure_table, _get_ef
    init_vector_db(
        db_path=settings.vector_db_path,
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
    )

    rows = []
    for s in staged:
        full_id = resolve_id(s["id"])
        v1 = export[full_id]
        old_meta = v1["metadata"]

        meta = {}
        for k in PRESERVE_KEYS:
            if k in old_meta:
                meta[k] = old_meta[k]
        for k in STAGED_KEYS:
            if k in s and s[k] is not None:
                meta[k] = s[k]

        meta["event_time"] = s.get("event_time")  # nullable by design
        meta["recorded_at"] = s.get("recorded_at") or old_meta.get("timestamp")
        # Keep legacy "timestamp" pointing at recorded_at so existing
        # tooling (context weighting, relative time) keeps functioning
        # until it is taught the new field names.
        meta["timestamp"] = meta["recorded_at"]
        meta["source"] = "rebuild"
        meta["modality"] = "text"
        # "historical" is deliberately NOT carried — event_time/recorded_at
        # split replaces it. Null event_time = no relative-time framing.

        new_text = s["text"]
        if not new_text or not new_text.strip():
            raise SystemExit(f"[rebuild] staged record {s['id']} has empty text")

        rows.append({
            "id": full_id,
            "text": new_text,
            "metadata_json": json.dumps(meta),
        })
        changed = "SAME TEXT" if new_text == v1["text"] else "rewritten"
        print(f"[rebuild] {full_id[:8]} {meta.get('type','?'):12} imp{meta.get('importance','?')} "
              f"event_time={'null' if meta['event_time'] is None else meta['event_time'][:10]} {changed}")

    if args.dry_run:
        print(f"[rebuild] DRY RUN — {len(rows)} records validated, nothing written")
        return

    table = _ensure_table(args.target)
    ef = _get_ef()
    # Replace-if-exists: makes batch loading idempotent (re-running an
    # approved batch after a fix overwrites rather than duplicates).
    existing_ids = set()
    if table.count_rows() > 0:
        existing_ids = {r["id"] for r in table.search().limit(table.count_rows()).to_list()}
    to_delete = [r["id"] for r in rows if r["id"] in existing_ids]
    if to_delete:
        quoted = ", ".join(f"'{i}'" for i in to_delete)
        table.delete(f"id IN ({quoted})")
        print(f"[rebuild] replaced {len(to_delete)} existing records (idempotent reload)")

    for r in rows:
        r["vector"] = ef.embed(r["text"])
    table.add(rows)

    print(f"[rebuild] LOADED {len(rows)} records into '{args.target}' "
          f"(total now: {table.count_rows()})")


if __name__ == "__main__":
    main()
