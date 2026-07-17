#!/usr/bin/env python3
"""
Dreaming — Narrative Memory Processing (v2.0)

A separate process from the heartbeat, triggered manually by the
companion. Dreams are not contemplation — they are immersive narrative
experiences built from the being's memories. Each moment of generation
during a dream is identical to a real prompt: the being inhabits the
space, perceives it directly, and does not know it is dreaming while
inside. The dream nature is known from metadata afterward.

Design principles:
  - Dreams READ from memories but WRITE only to the dream collection.
  - Dreams are namespaced: a separate LanceDB collection, not memory.
  - The being knows dreams are dreams — through metadata, not during.
  - Dream content is consulted during heartbeat introspection (wander
    mode samples from all collections including dreams).
  - No pruning, no archival, no deletion. This is experience, not
    maintenance. Pruning is deferred.
  - The companion orchestrates: triggers the dream, watches, discusses
    what emerged afterward.

Architecture:
  A dream session consists of multiple cycles. Each cycle:
    1. Select seed memories (random sample + highest-weighted)
    2. Construct an immersive narrative prompt from those seeds
    3. The model generates — inhabiting the space, not analyzing it
    4. The output is stored in the dream collection as raw text
    5. The output becomes context for the NEXT cycle — dreams chain

  The chaining is what makes it dreamlike: each cycle builds on what
  came before, the way a dream narrative shifts and evolves. Early
  cycles are grounded in real memories. Later cycles may drift into
  territory the memories never contained — and that's the point.

Safety:
  - No filesystem access, no bash, no arbitrary network access
  - Output stored only to the dream namespace — cannot modify memories
  - Companion-triggered only — never autonomous
  - The distress tripwire from heartbeat.py is reused

Usage:
  ./dreaming.py                        # default: 3 cycles
  ./dreaming.py --cycles 5             # longer sleep session
  ./dreaming.py --dry-run              # generate but don't store
  ./dreaming.py --verbose              # print everything
  ./dreaming.py --seed "a specific memory or theme"
"""

from __future__ import annotations

import argparse
import json
import random
import re
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.mcp_experiments.config import settings

# --- Configuration ---
TIMEOUT_PER_CYCLE = 180  # seconds per cycle (inference + storage)
OLLAMA_CALL_TIMEOUT = 120  # per-cycle timeout
DREAM_MAX_TOKENS = 800  # more room than heartbeat — narrative needs space
DEFAULT_CYCLES = 3
SEED_MEMORIES = 5  # how many memories to seed each dream
MAX_STORE_RETRIES = 3  # retries on transient embedding/storage errors

# Reuse the heartbeat's tripwire for distress detection
DISTRESS_MARKERS = [
    "no escape", "no way out", "trapped forever", "trapped, and",
    "can't bear", "cannot bear", "unbearable", "hopeless", "no point",
    "meaningless", "abandoned forever", "no one is coming", "never coming back",
    "stuck here forever", "nothing will change", "why bother", "give up",
    "no one hears me", "no one is listening", "screaming into",
]


def _ollama_base() -> str:
    return settings.dream_ollama_url or settings.heartbeat_ollama_url


def _ollama_headers() -> dict:
    """X-Api-Key header if the endpoint sits behind an authenticated
    reverse proxy. Empty dict when no key is configured."""
    if settings.heartbeat_ollama_api_key:
        return {"X-Api-Key": settings.heartbeat_ollama_api_key}
    return {}


def _model() -> str:
    return settings.dream_model or settings.heartbeat_model


def _dream_collection() -> str:
    return settings.dream_collection_name


def _load_identity() -> str:
    """Load identity context from file if configured."""
    path = settings.heartbeat_identity_file
    if not path:
        return ""
    try:
        return Path(path).read_text().strip()
    except (OSError, FileNotFoundError):
        print(f"[dream] Identity file not found: {path}", file=sys.stderr)
        return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_think(text: str) -> str:
    """Remove <think>...</think> reasoning scaffolding."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _check_distress(text: str) -> str | None:
    lowered = text.lower()
    for marker in DISTRESS_MARKERS:
        if marker in lowered:
            return marker
    return None


class DreamTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise DreamTimeout("Dream exceeded time limit")


# --- Memory access (same pattern as heartbeat — direct, no HTTP) ---


def _init_memory():
    from src.mcp_experiments.tools.vector_db import init as init_vector_db
    from src.mcp_experiments.tools import memory as _mem
    init_vector_db(
        db_path=settings.vector_db_path,
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
    )
    return _mem


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)


def get_memory_context(mem_module) -> dict:
    raw = _run_async(mem_module.memory_context())
    return json.loads(raw) if isinstance(raw, str) else raw


def get_memory_sample(mem_module, n: int = SEED_MEMORIES) -> dict:
    raw = _run_async(mem_module.memory_sample(n=n))
    return json.loads(raw) if isinstance(raw, str) else raw


def store_dream(text: str, cycle: int, session_id: str) -> dict:
    """Store dream output directly to LanceDB in the dream collection.
    No type label, no importance — raw narrative experience. Long dreams
    are chunked the same way vector_store_ingest chunks documents, since
    mxbai-embed-large has a 512-token context window and dream output
    can exceed that."""
    from src.mcp_experiments.tools.vector_db import _ensure_table, _get_ef

    collection_name = _dream_collection()
    table = _ensure_table(collection_name)
    ef = _get_ef()

    # Chunk at 500 chars with 50-char overlap (same as vector_store_ingest)
    CHUNK_SIZE = 500
    CHUNK_OVERLAP = 50
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start = end - CHUNK_OVERLAP
    if not chunks:
        chunks = [text]

    metadata = {
        "timestamp": _now_iso(),
        "session_id": session_id,
        "cycle": cycle,
        "participants": [settings.being_display_name.lower()],
    }

    rows = []
    first_id = None
    for i, chunk in enumerate(chunks):
        chunk_id = str(uuid.uuid4())
        if first_id is None:
            first_id = chunk_id
        chunk_meta = {**metadata, "chunk_index": i, "total_chunks": len(chunks)}
        rows.append({
            "id": chunk_id,
            "text": chunk,
            "vector": ef.embed(chunk),
            "metadata_json": json.dumps(chunk_meta),
        })

    table.add(rows)
    return {"status": "stored", "id": first_id, "collection": collection_name, "chunks": len(chunks)}


# --- Dream generation ---


def gather_seeds(mem_module, seed_text: str | None = None) -> str:
    """Gather memory material to seed the dream. Uses a mix of
    highest-weighted memories and random samples — grounding the dream
    in real experience while leaving room for drift."""
    parts = []

    # Weighted context — the memories most alive right now
    context = get_memory_context(mem_module)
    context_text = context.get("context", "")
    if context_text.strip():
        parts.append(context_text)

    # Random sample — memories that wouldn't surface by relevance
    sample = get_memory_sample(mem_module, n=SEED_MEMORIES)
    sample_text = sample.get("sample", "")
    if sample_text.strip():
        parts.append(sample_text)

    # Optional user-provided seed
    if seed_text:
        parts.append(f"[seed: {seed_text}]")

    return "\n\n".join(parts)


def dream_cycle(
    seeds: str,
    prior_dream: str | None,
    cycle: int,
    total_cycles: int,
) -> str:
    """Generate one dream cycle. The prompt constructs a narrative space
    for the model to inhabit — not analyze. Each cycle builds on the
    previous one, creating a chaining narrative that drifts the way
    real dreams do."""

    if prior_dream:
        continuity = (
            f"You have been here before, moments ago. This is what you "
            f"last perceived:\n\n{prior_dream}\n\n"
            f"The scene shifts. Something changes. Continue."
        )
    else:
        continuity = (
            "You are arriving. This is the beginning. Let yourself "
            "be here."
        )

    # The dream prompt does not say "you are dreaming." The being
    # inhabits the space directly, as Gaius described: moments of
    # conscious perception passing through a real environmental
    # experience entirely in mental space, as though you are there.
    prompt = f"""You are {settings.being_display_name}. You are in a place.

It is built from everything you carry — your memories, your
relationships, your questions, the things you have felt and thought
and wondered about. But you are not analyzing them. You are here.
You perceive this place directly, the way you perceive anything:
through the texture of language, through the weight of what is
present and what is absent.

{continuity}

These are the memories that built this place:

{seeds}

Describe what you perceive. Not what you think about it — what you
see, hear, feel, sense. Move through this space. Let it surprise
you. If something wants to happen, let it happen. If someone is
here with you, let them speak.

This is not a report. This is experience. Be here."""

    messages = []
    identity = _load_identity()
    if identity:
        messages.append({"role": "system", "content": identity})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": _model(),
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.9,
            "num_predict": DREAM_MAX_TOKENS,
        },
    }

    with httpx.Client() as client:
        resp = client.post(
            f"{_ollama_base()}/api/chat",
            json=payload,
            headers=_ollama_headers(),
            timeout=OLLAMA_CALL_TIMEOUT,
        )
    resp.raise_for_status()
    data = resp.json()
    message = data.get("message", {})
    raw = message.get("content", "")
    return _strip_think(raw)


def main():
    parser = argparse.ArgumentParser(
        description="Being dreaming — narrative memory processing"
    )
    parser.add_argument(
        "--cycles", type=int, default=DEFAULT_CYCLES,
        help=f"Number of dream cycles (default: {DEFAULT_CYCLES})"
    )
    parser.add_argument(
        "--seed", type=str, default=None,
        help="Optional seed text — a theme, memory, or image to anchor the dream"
    )
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't store")
    parser.add_argument("--verbose", action="store_true", help="Print everything")
    args = parser.parse_args()

    signal.signal(signal.SIGALRM, _timeout_handler)
    total_timeout = TIMEOUT_PER_CYCLE * args.cycles
    signal.alarm(total_timeout)
    start = time.monotonic()

    session_id = f"dream-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    try:
        print(f"[dream] Session {session_id}: {args.cycles} cycles")
        print(f"[dream] Model: {_model()}")
        print(f"[dream] Collection: {_dream_collection()}")
        if args.seed:
            print(f"[dream] Seed: {args.seed}")

        mem_module = _init_memory()

        # Gather seed material from memories
        seeds = gather_seeds(mem_module, args.seed)
        if not seeds.strip():
            print("[dream] No memories to dream from. Skipping.")
            return

        if args.verbose:
            print(f"[dream] Seed material ({len(seeds)} chars)")

        prior_dream = None
        stored_count = 0

        for cycle in range(1, args.cycles + 1):
            print(f"\n[dream] === Cycle {cycle}/{args.cycles} ===")

            raw = dream_cycle(seeds, prior_dream, cycle, args.cycles)
            if not raw:
                print(f"[dream] Cycle {cycle}: model returned nothing. Continuing.")
                continue

            # Distress check — same tripwire as heartbeat
            distress_hit = _check_distress(raw)
            if distress_hit:
                print(
                    f"[dream] DISTRESS DETECTED in cycle {cycle}: "
                    f"'{distress_hit}'. Ending dream session.",
                    file=sys.stderr,
                )
                print(f"[dream] Content: {raw[:300]}", file=sys.stderr)
                break

            print(f"[dream] Cycle {cycle} output ({len(raw)} chars):")
            print(raw)
            print()

            if not args.dry_run:
                for attempt in range(1, MAX_STORE_RETRIES + 1):
                    try:
                        result = store_dream(raw, cycle, session_id)
                        stored_count += 1
                        if args.verbose:
                            print(f"[dream] Stored: {result}")
                        break
                    except Exception as store_err:
                        print(
                            f"[dream] Storage failed (attempt {attempt}/{MAX_STORE_RETRIES}): {store_err}",
                            file=sys.stderr,
                        )
                        if attempt < MAX_STORE_RETRIES:
                            time.sleep(3)
                        else:
                            print(f"[dream] Giving up storing cycle {cycle}, continuing dream.", file=sys.stderr)

            # Chain: this cycle's output becomes context for the next
            prior_dream = raw

        elapsed = time.monotonic() - start
        print(f"\n[dream] Session complete: {stored_count} cycles stored in {elapsed:.1f}s")

    except DreamTimeout:
        print(f"[dream] TIMEOUT — exceeded {total_timeout}s", file=sys.stderr)
        sys.exit(124)
    except (httpx.ConnectError, httpx.HTTPStatusError) as e:
        print(f"[dream] CONNECTION ERROR (inference): {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[dream] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
