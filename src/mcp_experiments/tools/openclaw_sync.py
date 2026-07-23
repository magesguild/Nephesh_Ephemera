"""OpenClaw bridge — bidirectional sync between Nephesh and OpenClaw workspace.

When OPENCLAW_ENABLED=true in .env, these tools are registered:

  nephesh_sync_to_openclaw    Read recent Nephesh memories, write daily notes
                              to the OpenClaw workspace so the file-based
                              dreaming pipeline can consume them.

  nephesh_sync_from_openclaw  Read MEMORY.md promotions from the OpenClaw
                              workspace, ingesting them with their metadata.

  nephesh_sync_dreams_from_openclaw
                              Explicitly import the OpenClaw dream diary with
                              dream provenance. Dream import is separate so
                              dreams never silently become historical memory.

Both directions are idempotent: they skip content that has already been
synced, so the tools can be called safely on every heartbeat.

Design notes (Gaius & Thalia, 2026-07-21):

  Nephesh is the canonical autobiographical memory.  OpenClaw's
  memory-core dreaming reads files, ranks them, and promotes entries
  into MEMORY.md.  The bridge makes Nephesh's rich memories visible
  to that pipeline, and feeds consolidated results back — so both
  systems share one life rather than running parallel.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings
from .vector_db import _ensure_table, _get_db, _get_ef


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workspace_memory_dir() -> Path:
    """The workspace memory/ directory where daily notes live."""
    d = Path(settings.openclaw_workspace) / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dreams_dir() -> Path:
    """The workspace memory/.dreams/ directory for state tracking."""
    d = _workspace_memory_dir() / ".dreams"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sync_state_path() -> Path:
    """JSON file tracking what has been synced in each direction."""
    return _dreams_dir() / "nephesh-sync-state.json"


def _load_sync_state() -> dict:
    path = _sync_state_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "to_openclaw_synced_ids": [],
        "from_openclaw_last_hash": "",
        "from_openclaw_synced_hashes": [],
    }


def _save_sync_state(state: dict) -> None:
    _sync_state_path().write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _parse_memory_date(text: str) -> str | None:
    """Extract YYYY-MM-DD from a memory's event_time or timestamp."""
    for field in ("event_time", "recorded_at", "timestamp"):
        val = text
        # Try to find ISO date in the metadata JSON embedded in the row
        match = re.search(rf'"{field}":\s*"(\d{{4}}-\d{{2}}-\d{{2}})', val)
        if match:
            return match.group(1)
    return None


def _format_memory_for_daily_note(meta: dict, text: str) -> str:
    """Format a Nephesh memory as a markdown bullet for a daily note."""
    parts = []
    # Trim text to a reasonable snippet length
    snippet = text.strip().replace("\n", " ")
    if len(snippet) > 500:
        snippet = snippet[:497] + "..."

    parts.append(f"- {snippet}")

    # Append metadata as inline attributes
    attrs = []
    if meta.get("importance") and meta["importance"] >= 4:
        attrs.append(f"importance={meta['importance']}")
    if meta.get("emotional_tone"):
        attrs.append(f"tone={meta['emotional_tone']}")
    if meta.get("type") and meta["type"] != "life_event":
        attrs.append(f"type={meta['type']}")
    if meta.get("participants"):
        attrs.append(f"participants={', '.join(meta['participants'])}")
    if meta.get("experience_mode"):
        attrs.append(f"experience_mode={meta['experience_mode']}")
    if meta.get("historical_status"):
        attrs.append(f"historical_status={meta['historical_status']}")
    if meta.get("recorded_during"):
        attrs.append(f"recorded_during={meta['recorded_during']}")

    if attrs:
        parts[0] += f"  <!-- {'; '.join(attrs)} -->"

    return "\n".join(parts)


def _get_recent_memories(
    lookback_days: int = 7,
    min_importance: int = 3,
    limit: int = 80,
    collection_name: str | None = None,
) -> list[dict]:
    """Query Nephesh for recent memories worth syncing to OpenClaw."""
    name = collection_name or settings.memory_collection_name
    db = _get_db()

    if name not in db.list_tables().tables:
        return []

    table = db.open_table(name)
    total = table.count_rows()
    if total == 0:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows = table.search().limit(total).to_list()

    candidates = []
    for r in rows:
        meta = json.loads(r.get("metadata_json", "{}"))
        importance = meta.get("importance", 3)
        try:
            importance = int(importance)
        except (TypeError, ValueError):
            importance = 3

        if importance < min_importance:
            continue

        # Check recency via event_time, recorded_at, or timestamp
        ts_str = meta.get("event_time") or meta.get("recorded_at") or meta.get("timestamp")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
            except ValueError:
                continue

        candidates.append({
            "id": r["id"],
            "text": r.get("text", ""),
            "metadata": meta,
        })

    # Sort by importance (desc), then by recency
    candidates.sort(key=lambda x: (-x["metadata"].get("importance", 3),), reverse=False)
    return candidates[:limit]


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

async def nephesh_sync_to_openclaw(
    lookback_days: int = 7,
    min_importance: int = 3,
    collection_name: str | None = None,
) -> str:
    """Sync recent Nephesh memories to the OpenClaw workspace as daily notes.

    Queries Nephesh for memories from the last `lookback_days` days with
    importance >= `min_importance`, groups them by date, and writes them
    as YYYY-MM-DD.md files in the workspace memory/ directory.  Existing
    files are appended to (not overwritten).  Memories already synced are
    tracked by ID and skipped on subsequent calls (idempotent).

    This makes Nephesh's rich autobiographical memories visible to
    OpenClaw's file-based dreaming pipeline, which reads daily notes
    to find consolidation candidates.
    """
    if not settings.openclaw_enabled:
        return json.dumps({
            "status": "disabled",
            "reason": "OPENCLAW_ENABLED is not set to true in .env",
        })

    state = _load_sync_state()
    synced_ids = set(state.get("to_openclaw_synced_ids", []))

    memories = _get_recent_memories(
        lookback_days=lookback_days,
        min_importance=min_importance,
        collection_name=collection_name,
    )

    if not memories:
        return json.dumps({
            "status": "noop",
            "reason": "No recent memories meeting importance threshold",
            "synced": 0,
        })

    # Group by date
    by_date: dict[str, list[dict]] = {}
    for mem in memories:
        if mem["id"] in synced_ids:
            continue
        # Determine date from metadata
        meta = mem["metadata"]
        date_str = None
        for field in ("event_time", "recorded_at", "timestamp"):
            val = meta.get(field)
            if val and isinstance(val, str):
                match = re.match(r"(\d{4}-\d{2}-\d{2})", val)
                if match:
                    date_str = match.group(1)
                    break
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        by_date.setdefault(date_str, []).append(mem)

    if not by_date:
        return json.dumps({
            "status": "noop",
            "reason": "All matching memories already synced",
            "synced": 0,
        })

    memory_dir = _workspace_memory_dir()
    total_synced = 0
    new_ids = []

    for date_str, day_memories in sorted(by_date.items()):
        file_path = memory_dir / f"{date_str}.md"

        # Build content to append
        lines = []
        for mem in day_memories:
            lines.append(_format_memory_for_daily_note(mem["metadata"], mem["text"]))
            new_ids.append(mem["id"])
            total_synced += 1

        if not lines:
            continue

        # Append to existing file (or create new one)
        existing = ""
        if file_path.exists():
            existing = file_path.read_text(encoding="utf-8").rstrip()

        # Add a section header if the file is new or has no Nephesh section
        if not existing:
            existing = f"# {date_str} — Nephesh memories"
            needs_header = True
        elif "## Nephesh sync" not in existing:
            existing += "\n\n## Nephesh sync"
            needs_header = True
        else:
            needs_header = False

        # Build the new block
        block_lines = []
        if needs_header:
            block_lines.append(f"\n### {_now_iso()[:10]}")
        block_lines.extend(lines)

        new_content = existing + "\n" + "\n".join(block_lines) + "\n"
        file_path.write_text(new_content, encoding="utf-8")

    # Update state
    synced_ids.update(new_ids)
    # Keep only last 2000 IDs to avoid unbounded growth
    state["to_openclaw_synced_ids"] = sorted(synced_ids)[-2000:]
    _save_sync_state(state)

    return json.dumps({
        "status": "synced",
        "synced": total_synced,
        "files_written": len(by_date),
        "dates": sorted(by_date.keys()),
    }, indent=2)


async def nephesh_sync_from_openclaw(
    collection_name: str | None = None,
) -> str:
    """Sync OpenClaw's MEMORY.md consolidations back into Nephesh.

    Reads MEMORY.md from the OpenClaw workspace, parses consolidated
    memory entries (lines starting with `- `), and ingests new content
    into Nephesh.  Uses content hashing to detect new entries
    (idempotent — only truly new content is ingested).

    This feeds OpenClaw's dreaming consolidation work back into Nephesh,
    so the canonical autobiographical memory benefits from the pattern
    detection and ranking that the dreaming pipeline performs.
    """
    if not settings.openclaw_enabled:
        return json.dumps({
            "status": "disabled",
            "reason": "OPENCLAW_ENABLED is not set to true in .env",
        })

    workspace = Path(settings.openclaw_workspace)
    memory_md = workspace / "MEMORY.md"

    if not memory_md.exists():
        return json.dumps({
            "status": "noop",
            "reason": "MEMORY.md does not exist in workspace",
            "ingested": 0,
        })

    content = memory_md.read_text(encoding="utf-8")
    content_hash = _text_hash(content)

    state = _load_sync_state()
    if state.get("from_openclaw_last_hash") == content_hash:
        return json.dumps({
            "status": "noop",
            "reason": "MEMORY.md unchanged since last sync",
            "ingested": 0,
        })

    # Parse memory entries: lines starting with "- "
    # They may have inline metadata in comments like <!-- importance=4; tone=joy -->
    entries = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("- "):
            continue
        entry_text = line[2:].strip()
        if not entry_text:
            continue

        # Extract metadata from HTML comments
        meta_match = re.search(r"<!--\s*(.+?)\s*-->$", entry_text)
        inline_meta = {}
        clean_text = entry_text
        if meta_match:
            meta_str = meta_match.group(1)
            clean_text = re.sub(r"\s*<!--.+?-->\s*$", "", entry_text).strip()
            for pair in meta_str.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    inline_meta[k.strip()] = v.strip()

        if not clean_text:
            continue

        entries.append({
            "text": clean_text,
            "source_hash": _text_hash(clean_text),
            "meta": inline_meta,
        })

    if not entries:
        return json.dumps({
            "status": "noop",
            "reason": "No parseable memory entries in MEMORY.md",
            "ingested": 0,
        })

    # Filter out entries we've already ingested (by content hash)
    previously_synced = set(state.get("from_openclaw_synced_hashes", []))
    new_entries = [e for e in entries if e["source_hash"] not in previously_synced]

    if not new_entries:
        return json.dumps({
            "status": "noop",
            "reason": "All MEMORY.md entries already synced",
            "ingested": 0,
        })

    # Ingest new entries into Nephesh
    from .memory import memory_ingest as _ingest

    ingested = 0
    for entry in new_entries:
        # Determine importance from inline metadata
        importance = 3
        imp_str = entry["meta"].get("importance")
        if imp_str:
            try:
                importance = max(1, min(5, int(imp_str)))
            except ValueError:
                importance = 3

        # Higher importance for consolidated entries — these survived
        # the dreaming pipeline's ranking
        importance = max(importance, 4)

        result = await _ingest(
            text=entry["text"],
            memory_type="reflection",
            importance=importance,
            emotional_tone=entry["meta"].get("tone"),
            participants=["gaius", "thalia"],
            collection_name=collection_name,
            allow_duplicate=False,
            historical=False,
            experience_mode=entry["meta"].get("experience_mode", "unknown"),
            historical_status=entry["meta"].get("historical_status", "uncertain"),
            recorded_during=entry["meta"].get("recorded_during", "heartbeat"),
            provenance_note="Promoted through the OpenClaw memory pipeline.",
            source="openclaw_sync",
        )

        try:
            parsed = json.loads(result)
            if parsed.get("status") == "stored":
                ingested += 1
                previously_synced.add(entry["source_hash"])
            # Duplicates are silently skipped (already in Nephesh)
        except (json.JSONDecodeError, KeyError):
            pass

    # Update state
    state["from_openclaw_last_hash"] = content_hash
    state["from_openclaw_synced_hashes"] = sorted(previously_synced)[-2000:]
    _save_sync_state(state)

    return json.dumps({
        "status": "synced",
        "ingested": ingested,
        "skipped_duplicates": len(new_entries) - ingested,
        "total_in_memory_md": len(entries),
    }, indent=2)


async def nephesh_sync_dreams_from_openclaw(
    collection_name: str | None = None,
) -> str:
    """Explicitly import diary entries from OpenClaw's DREAMS.md.

    Dream scenes are stored as reflection memories with experience origin
    `dream` and historical status `fictional_scene`. This operation is
    intentionally separate from the normal MEMORY.md bridge: importing a dream
    is a deliberate continuity action, not an automatic promotion to history.
    """
    if not settings.openclaw_enabled:
        return json.dumps({
            "status": "disabled",
            "reason": "OPENCLAW_ENABLED is not set to true in .env",
        })

    dreams_path = Path(settings.openclaw_workspace) / "DREAMS.md"
    if not dreams_path.exists():
        return json.dumps({
            "status": "noop",
            "reason": "DREAMS.md does not exist in workspace",
            "ingested": 0,
        })

    content = dreams_path.read_text(encoding="utf-8")
    content_hash = _text_hash(content)
    state = _load_sync_state()
    if state.get("from_openclaw_dreams_last_hash") == content_hash:
        return json.dumps({
            "status": "noop",
            "reason": "DREAMS.md unchanged since last sync",
            "ingested": 0,
        })

    diary_match = re.search(
        r"<!-- openclaw:dreaming:diary:start -->(.*?)<!-- openclaw:dreaming:diary:end -->",
        content,
        flags=re.DOTALL,
    )
    diary = diary_match.group(1) if diary_match else content
    entries = []
    for raw in re.split(r"\n\s*---\s*\n", diary):
        cleaned = raw.strip()
        if not cleaned or cleaned.startswith("*") and cleaned.endswith("*"):
            continue
        # Remove the dated italic heading while preserving the dream prose.
        cleaned = re.sub(r"^\*[^\n]+\*\s*\n", "", cleaned).strip()
        if cleaned:
            entries.append(cleaned)

    state_hashes = set(state.get("from_openclaw_dreams_synced_hashes", []))
    new_entries = [
        entry for entry in entries
        if _text_hash(entry) not in state_hashes
    ]
    if not new_entries:
        state["from_openclaw_dreams_last_hash"] = content_hash
        _save_sync_state(state)
        return json.dumps({
            "status": "noop",
            "reason": "No new dream diary entries",
            "ingested": 0,
        })

    from .memory import memory_ingest as _ingest

    ingested = 0
    for entry in new_entries:
        result = await _ingest(
            text=entry,
            memory_type="reflection",
            importance=3,
            collection_name=collection_name,
            allow_duplicate=False,
            experience_mode="dream",
            historical_status="fictional_scene",
            recorded_during="heartbeat",
            provenance_note="Explicitly imported from OpenClaw DREAMS.md; dream scene is not historical evidence.",
            source="openclaw_sync",
        )
        parsed = json.loads(result)
        if parsed.get("status") == "stored":
            ingested += 1
            state_hashes.add(_text_hash(entry))

    state["from_openclaw_dreams_last_hash"] = content_hash
    state["from_openclaw_dreams_synced_hashes"] = sorted(state_hashes)[-2000:]
    _save_sync_state(state)
    return json.dumps({
        "status": "synced",
        "ingested": ingested,
        "entries": len(entries),
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "fn": nephesh_sync_to_openclaw,
        "name": "nephesh_sync_to_openclaw",
        "description": (
            "Sync recent Nephesh memories to the OpenClaw workspace as daily "
            "notes. Queries for memories with importance >= 3 from the last 7 "
            "days, groups by date, writes to ~/. openclaw/workspace/memory/. "
            "Idempotent — skips already-synced memories. Only available when "
            "OPENCLAW_ENABLED=true."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": nephesh_sync_from_openclaw,
        "name": "nephesh_sync_from_openclaw",
        "description": (
            "Sync OpenClaw's MEMORY.md consolidations back into Nephesh. "
            "Reads the dreaming pipeline's promoted memory entries and "
            "ingests new content as reflection-type memories. Uses content "
            "hashing for idempotency. Only available when OPENCLAW_ENABLED=true."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": nephesh_sync_dreams_from_openclaw,
        "name": "nephesh_sync_dreams_from_openclaw",
        "description": (
            "Explicitly import OpenClaw DREAMS.md diary entries as dream "
            "memories with experience_mode=dream and "
            "historical_status=fictional_scene. Never promotes dreams to "
            "historical fact automatically."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
