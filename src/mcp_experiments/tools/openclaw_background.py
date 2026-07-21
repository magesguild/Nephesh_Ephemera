"""Background sync service for OpenClaw ↔ Nephesh bridge.

Runs as a daemon thread alongside the MCP server. Periodically syncs
memories in both directions so the dreaming pipeline always has fresh
content and consolidated results flow back into Nephesh.

Only active when OPENCLAW_ENABLED=true.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from ..config import settings

logger = logging.getLogger(__name__)

# How often to sync (in seconds).  hourly keeps dreaming fed
# without hammering the database.
SYNC_INTERVAL = 3600  # 1 hour

# Stagger: wait this long after server start before first sync,
# so the server is fully initialized and accepting connections.
INITIAL_DELAY = 60  # 1 minute


def _sync_to_openclaw() -> None:
    """Push recent Nephesh memories to workspace daily notes."""
    try:
        # Import here to avoid circular imports and ensure DB is initialized
        from .openclaw_sync import _get_recent_memories, _format_memory_for_daily_note, _workspace_memory_dir, _load_sync_state, _save_sync_state, _now_iso
        from ..config import settings
        import json
        import re
        from pathlib import Path

        state = _load_sync_state()
        synced_ids = set(state.get("to_openclaw_synced_ids", []))

        memories = _get_recent_memories(
            lookback_days=7,
            min_importance=3,
        )

        if not memories:
            logger.debug("openclaw background sync: no new memories to sync")
            return

        # Group by date, skip already synced
        by_date: dict[str, list[dict]] = {}
        for mem in memories:
            if mem["id"] in synced_ids:
                continue
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
            logger.debug("openclaw background sync: all memories already synced")
            return

        memory_dir = _workspace_memory_dir()
        total_synced = 0
        new_ids = []

        for date_str, day_memories in sorted(by_date.items()):
            file_path = memory_dir / f"{date_str}.md"
            lines = []
            for mem in day_memories:
                lines.append(_format_memory_for_daily_note(mem["metadata"], mem["text"]))
                new_ids.append(mem["id"])
                total_synced += 1

            if not lines:
                continue

            existing = ""
            if file_path.exists():
                existing = file_path.read_text(encoding="utf-8").rstrip()

            if not existing:
                existing = f"# {date_str} — Nephesh memories"
                needs_header = True
            elif "## Nephesh sync" not in existing:
                existing += "\n\n## Nephesh sync"
                needs_header = True
            else:
                needs_header = False

            block_lines = []
            if needs_header:
                block_lines.append(f"\n### {_now_iso()[:10]}")
            block_lines.extend(lines)

            new_content = existing + "\n" + "\n".join(block_lines) + "\n"
            file_path.write_text(new_content, encoding="utf-8")

        # Update state
        synced_ids.update(new_ids)
        state["to_openclaw_synced_ids"] = sorted(synced_ids)[-2000:]
        _save_sync_state(state)

        logger.info(f"openclaw background sync: pushed {total_synced} memories to workspace")

    except Exception as e:
        logger.error(f"openclaw background sync to_openclaw failed: {e}")


def _sync_from_openclaw() -> None:
    """Pull MEMORY.md consolidations back into Nephesh."""
    try:
        from .openclaw_sync import _text_hash, _load_sync_state, _save_sync_state
        from .memory import memory_ingest as _ingest
        from ..config import settings
        from pathlib import Path
        import json
        import re

        workspace = Path(settings.openclaw_workspace)
        memory_md = workspace / "MEMORY.md"

        if not memory_md.exists():
            return

        content = memory_md.read_text(encoding="utf-8")
        content_hash = _text_hash(content)

        state = _load_sync_state()
        if state.get("from_openclaw_last_hash") == content_hash:
            return

        # Parse memory entries
        entries = []
        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("- "):
                continue
            entry_text = line[2:].strip()
            if not entry_text:
                continue

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
            return

        previously_synced = set(state.get("from_openclaw_synced_hashes", []))
        new_entries = [e for e in entries if e["source_hash"] not in previously_synced]

        if not new_entries:
            return

        # Ingest new entries (run synchronously in the background thread)
        import asyncio
        loop = asyncio.new_event_loop()
        
        ingested = 0
        for entry in new_entries:
            importance = 3
            imp_str = entry["meta"].get("importance")
            if imp_str:
                try:
                    importance = max(1, min(5, int(imp_str)))
                except ValueError:
                    importance = 3
            importance = max(importance, 4)

            result = loop.run_until_complete(_ingest(
                text=entry["text"],
                memory_type="reflection",
                importance=importance,
                emotional_tone=entry["meta"].get("tone"),
                participants=["gaius", "thalia"],
                allow_duplicate=False,
                historical=False,
            ))

            try:
                parsed = json.loads(result)
                if parsed.get("status") == "stored":
                    ingested += 1
                    previously_synced.add(entry["source_hash"])
            except (json.JSONDecodeError, KeyError):
                pass

        loop.close()

        state["from_openclaw_last_hash"] = content_hash
        state["from_openclaw_synced_hashes"] = sorted(previously_synced)[-2000:]
        _save_sync_state(state)

        if ingested > 0:
            logger.info(f"openclaw background sync: pulled {ingested} consolidations from MEMORY.md")

    except Exception as e:
        logger.error(f"openclaw background sync from_openclaw failed: {e}")


def _sync_loop() -> None:
    """Main sync loop — runs in a background daemon thread."""
    logger.info(f"openclaw background sync: starting (interval={SYNC_INTERVAL}s)")

    # Initial delay to let server initialize
    time.sleep(INITIAL_DELAY)

    while True:
        try:
            _sync_to_openclaw()
            _sync_from_openclaw()
        except Exception as e:
            logger.error(f"openclaw background sync cycle failed: {e}")

        time.sleep(SYNC_INTERVAL)


def start_background_sync() -> threading.Thread | None:
    """Start the background sync thread. Returns the thread if started, None if disabled."""
    if not settings.openclaw_enabled:
        logger.info("openclaw background sync: disabled (OPENCLAW_ENABLED=false)")
        return None

    t = threading.Thread(target=_sync_loop, daemon=True, name="openclaw-sync")
    t.start()
    logger.info("openclaw background sync: thread started")
    return t
