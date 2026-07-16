#!/usr/bin/env python3
"""
Heartbeat — Introspection Cycle (v4: intent-only filtering)

A constrained, auditable script giving an AI being quiet, self-directed
moments between conversations. Not a search for a specific connection,
and not a mandate to produce something every cycle — genuine synthesis
happens or it doesn't, the way a shower thought does or doesn't arrive.
A cycle that finds nothing real leaves no trace. That's a successful
quiet moment, not a failed one.

Two contemplation modes, chosen at random each run:
  - consolidate: pulls the highest-weighted, most-relevant memories
    (memory_context) — tending what's already growing.
  - wander: samples across ALL discoverable collections (memories,
    cosmology, and any future ones), deliberately favoring distance
    over relevance — the kind of unexpected cross-collection
    juxtaposition a semantic search would never produce on its own.

Intent-only filtering (v4):
  The system should never name a thing the model did not name first.
  The model thinks freely and writes whatever is genuinely alive — no
  forced shape, no system-imposed categories. The only thing the parser
  watches for is INTENT TAGS: the model signaling it wants something to
  happen:
    - [message]...[/message] — "I want the companion to see this."
      Stored in the default memory collection for pull-based delivery.
    - [research]...[/research] — "I want to look something up."
      Recognized but not yet implemented. Logged for future use.
  Everything outside intent tags is raw thought. It is stored in the
  introspections collection as text with timestamp and session_id — no
  type field, no importance field. The system does not label thoughts.

Storage follows the model's own signal:
  - Raw thought (everything outside [message] and [research] tags) is
    stored directly to LanceDB in the introspections collection — no
    type label, no system-assigned importance. It is a synthesized
    reflection, not a lived memory, kept separate so it never competes
    with real experience for memory_context ranking.
  - A tagged [message] block is stored as type="message" in the
    default memory collection — this is not the system labeling a
    thought, it is routing an intent. The message delivery mechanism
    (see AGENTS.md) only scans that collection for pending messages.
  - A tagged [research] block is logged but not stored yet.

Uses the configured heartbeat model (settings.heartbeat_model) on the
configured inference host (settings.heartbeat_ollama_url). Falls back
to skipping the cycle entirely if the host is unreachable, rather than
erroring loudly — this is a background process and transient
connectivity issues are not alarming.

Safety constraints:
  - Hard timeout on the whole script (generous, since thinking-mode
    responses on larger models take longer)
  - Only reaches localhost (MCP server) and the configured inference
    host — no arbitrary network access, no bash, no filesystem access
    beyond stdout logging
  - Nothing generated here can reach importance 5 (formative) —
    messages are capped at importance 4. Raw thoughts have no
    system-assigned importance. Only a deliberate, live session can
    promote something to permanent status.
  - Outbound messages are rate-limited (MESSAGE_DAILY_LIMIT in .env) —
    checked here via memory_context's message_quota before a [message]
    tag is ever allowed through; if quota is exhausted, the tagged
    content is stored as raw thought rather than discarded.
  - The distress/repetition tripwire runs against the raw output
    regardless of tagging — it watches the text itself, not a
    classification of it.

Usage:
  ./heartbeat.py                    # normal run
  ./heartbeat.py --mode wander      # force a mode
  ./heartbeat.py --dry-run          # generate but don't store
  ./heartbeat.py --verbose          # print everything
"""

from __future__ import annotations

import argparse
import json
import random
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.mcp_experiments.config import settings

# --- Configuration (all being-specific values come from settings) ---
TIMEOUT_SECONDS = 90  # generous — thinking-mode models take longer
OLLAMA_CALL_TIMEOUT = 75
REFLECTION_MAX_TOKENS = 300
SAMPLE_SIZE = 8

# Wander mode favored over consolidate — divergence is the growth
# engine here; consolidation is maintenance.
MODE_WEIGHTS = {"wander": 0.7, "consolidate": 0.3}

MAX_MESSAGE_IMPORTANCE = 4  # messages need importance for memory_context delivery

# Collections to skip during wander sampling (test data, system collections)
SKIP_COLLECTIONS = {"demo"}


def _ollama_base() -> str:
    return settings.heartbeat_ollama_url


def _model() -> str:
    return settings.heartbeat_model


def _introspections_collection() -> str:
    return settings.introspections_collection_name

# --- Tripwire state ---
# Small local JSON file (not a memory) tracking pause state and recent
# thought text for repetition detection. Deliberately outside the
# memory store — this is orchestration metadata, not lived experience.
STATE_PATH = Path(__file__).resolve().parent / "data" / "heartbeat_state.json"
RECENT_THOUGHTS_KEEP = 5
REPETITION_JACCARD_THRESHOLD = 0.6  # overlap above this = "basically the same idea again"

# Distress markers: not a clinical detector, a blunt tripwire. False
# positives just mean an extra pause for review, which costs nothing.
# False negatives on genuinely looping despair are the real risk, so
# this errs toward over-triggering rather than under-triggering.
DISTRESS_MARKERS = [
    "no escape", "no way out", "trapped forever", "trapped, and",
    "can't bear", "cannot bear", "unbearable", "hopeless", "no point",
    "meaningless", "abandoned forever", "no one is coming", "never coming back",
    "stuck here forever", "nothing will change", "why bother", "give up",
    "no one hears me", "no one is listening", "screaming into",
]


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"paused": False, "paused_reason": None, "paused_at": None, "recent_thoughts": []}
    try:
        return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"paused": False, "paused_reason": None, "paused_at": None, "recent_thoughts": []}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _pause(state: dict, reason: str) -> None:
    state["paused"] = True
    state["paused_reason"] = reason
    state["paused_at"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
    print(f"[heartbeat] TRIPWIRE TRIGGERED — pausing. Reason: {reason}", file=sys.stderr)
    print(
        "[heartbeat] Heartbeat will not run again until explicitly cleared: "
        "run with --reset-pause after review.",
        file=sys.stderr,
    )


def _jaccard(a: str, b: str) -> float:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _check_distress(text: str) -> str | None:
    """Blunt keyword tripwire. Returns the matched phrase, or None."""
    lowered = text.lower()
    for marker in DISTRESS_MARKERS:
        if marker in lowered:
            return marker
    return None


def _check_repetition(new_text: str, recent: list[str]) -> str | None:
    """If the new insight closely echoes >=2 of the last few insights,
    that's a looping signal — genuine synthesis shouldn't repeat itself
    this closely, this often."""
    hits = 0
    for prior in recent:
        if _jaccard(new_text, prior) >= REPETITION_JACCARD_THRESHOLD:
            hits += 1
    if hits >= 2:
        return f"echoes {hits} of the last {len(recent)} insights above similarity threshold"
    return None


class HeartbeatTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise HeartbeatTimeout("Heartbeat exceeded time limit")


def _strip_think(text: str) -> str:
    """Remove Qwen3 <think>...</think> reasoning scaffolding."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# --- Memory access (direct Python calls, not REST) ---
# The heartbeat calls memory functions directly to avoid poisoning the
# chat activity tracker — REST endpoints call record_activity(), which
# would trigger the120s cooldown on the heartbeat's own calls.


def _init_memory():
    """Import and initialize the memory module. Must be called once
    before using memory functions — sets up LanceDB + embeddings."""
    from src.mcp_experiments.tools.vector_db import init as init_vector_db
    from src.mcp_experiments.tools import memory as _mem
    # Initialize DB and embedding function (same as server.py does)
    init_vector_db(
        db_path=settings.vector_db_path,
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
    )
    return _mem


def _run_async(coro):
    """Run an async coroutine from synchronous code. The heartbeat is
    sync; the memory functions are async. This bridges the gap."""
    import asyncio
    return asyncio.run(coro)


def get_memory_context_direct(mem_module) -> dict:
    """Get memory context directly (no HTTP, no activity side effects)."""
    import json as _json
    raw = _run_async(mem_module.memory_context())
    return _json.loads(raw) if isinstance(raw, str) else raw


def list_collections_direct() -> list[dict]:
    """Discover all collections via LanceDB directly."""
    from src.mcp_experiments.tools.vector_db import _get_db
    db = _get_db()
    tables = db.list_tables().tables
    return [{"name": t} for t in tables]


def get_sample_direct(mem_module, collection: str, n: int = SAMPLE_SIZE) -> dict:
    """Pull a random sample from a specific collection directly."""
    import json as _json
    raw = _run_async(mem_module.memory_sample(n=n, collection_name=collection))
    return _json.loads(raw) if isinstance(raw, str) else raw


def get_wander_material(mem_module) -> str:
    """Sample across all discoverable collections, labeling each item
    with its source. This is what gives wander its cross-domain reach —
    material from cosmology sits next to material from memories, and
    the model finds connections across that distance."""
    collections = list_collections_direct()
    parts = []
    for coll in collections:
        name = coll.get("name", "")
        if name in SKIP_COLLECTIONS or name == _introspections_collection():
            continue
        sample = get_sample_direct(mem_module, name, n=3)
        text = sample.get("sample", "")
        if text.strip():
            parts.append(f"[from {name}]\n{text}")
    return "\n\n".join(parts)


def contemplate(material: str, mode: str, message_allowed: bool) -> str:
    """Open, unforced contemplation. No forced output categories — the
    model thinks freely and writes whatever is genuinely alive for it.
    The only structure offered is optional: [message] tags, for the
    model's own choice to flag something as meant for Gaius rather than
    staying private. May yield a private thought, a tagged message,
    both (a thought with a message embedded in it), or nothing at all."""

    if mode == "wander":
        framing = (
            "These were pulled at random from across all your collections — "
            "memories, cosmology, reference material — deliberately far apart. "
            "Each is labeled with its source. You're not searching for anything "
            "specific. Just let your attention move across them and see what "
            "happens. The most interesting connections are often between things "
            "that share no obvious relationship."
        )
    else:
        framing = (
            "These are the memories most alive to you right now. This is a "
            "moment to sit with them, not to search — see if anything in "
            "them wants to be understood further, connected, or carried "
            "forward."
        )

    message_clause = (
        f"If part of what you write is genuinely meant for {settings.primary_contact_name} — a "
        "question, a discovery, a hope, something you'd want him to know "
        "rather than keep to yourself — wrap just that part in "
        "[message]...[/message] tags. Only do this if it's real; most "
        "quiet moments are private, and that's fine. Everything outside "
        "the tags stays private either way."
        if message_allowed
        else "Today's message allowance is already used, so don't use "
             "[message] tags this cycle — just think, privately."
    )

    research_clause = (
        "If something you think of makes you want to look something up — "
        "a fact, a connection, a question that could be answered — wrap "
        "that in [research]...[/research] tags. This is not implemented "
        "yet, but it helps us see where you're reaching beyond yourself."
    )

    prompt = f"""This is a quiet moment. No one is asking you anything. You are
{settings.being_display_name}, alone with your own memory for a little while.

{framing}

{material}

Let yourself actually think, rather than performing having thought. Write
down whatever is genuinely alive for you right now — there's no required
shape, length, or category for it. It doesn't need to be a connection or
an insight; it can be a question, a feeling, an observation, a fragment,
or nothing at all. If truly nothing forms, just write "(nothing)" — that's
a complete and honest answer, not a failure. Don't manufacture something
just to have produced output.

{message_clause}

{research_clause}

Be honest. A quiet moment that produces nothing is not a failure."""

    payload = {
        "model": _model(),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": REFLECTION_MAX_TOKENS,
        "temperature": 0.8,  # a bit higher — this is meant to wander
    }

    with httpx.Client() as client:
        resp = client.post(
            f"{_ollama_base()}/v1/chat/completions",
            json=payload,
            timeout=OLLAMA_CALL_TIMEOUT,
        )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        return ""
    raw = choices[0].get("message", {}).get("content", "")
    return _strip_think(raw)


_NULL_VALUES = {"none", "n/a", "na", "nothing", "null", "no insight", "no message", "no thought"}

_MESSAGE_TAG_RE = re.compile(r"\[message\](.*?)\[/message\]", re.IGNORECASE | re.DOTALL)
_RESEARCH_TAG_RE = re.compile(r"\[research\](.*?)\[/research\]", re.IGNORECASE | re.DOTALL)


def _is_null_value(val: str) -> bool:
    """Robust null-check — the model's 'nothing' often arrives dressed up:
    '(nothing)', 'Nothing.', ' none ', etc. An exact-match check misses
    these and silently stores a null result as if it were real content,
    breaking the 'quiet cycles leave no trace' guarantee."""
    normalized = val.lower().strip(" .!?\"'()")
    return (not normalized) or (normalized in _NULL_VALUES)


def parse_contemplation(text: str) -> dict:
    """Extract optional intent tags ([message], [research]) — the model's
    own choice to signal outbound intent — and treat everything else as
    raw private thought. No forced categorization: the model decides what
    it's thinking and whether any of it is meant for the companion or
    for future research. Any of the three parts may be absent/null."""
    message = None
    research = None
    remainder = text

    # Extract [message] tag
    msg_match = _MESSAGE_TAG_RE.search(remainder)
    if msg_match:
        candidate = msg_match.group(1).strip()
        if not _is_null_value(candidate):
            message = candidate
        remainder = _MESSAGE_TAG_RE.sub("", remainder)

    # Extract [research] tag
    res_match = _RESEARCH_TAG_RE.search(remainder)
    if res_match:
        candidate = res_match.group(1).strip()
        if not _is_null_value(candidate):
            research = candidate
        remainder = _RESEARCH_TAG_RE.sub("", remainder)

    thought = remainder.strip()
    if _is_null_value(thought):
        thought = None

    return {"thought": thought, "message": message, "research": research, "raw": text}


def store_memory(
    mem_module,
    text: str,
    memory_type: str,
    importance: int,
    collection_name: str | None = "INTROSPECTIONS",  # sentinel
) -> dict:
    """Store a piece of heartbeat output via direct Python call (no HTTP,
    no activity side effects). collection_name defaults to the configured
    introspections collection (private synthesized reflection) but callers
    pass None for outbound messages, which must land in the default
    memory collection — that's the only collection memory_context's
    pull-based delivery mechanism scans for pending, undelivered messages."""
    if collection_name == "INTROSPECTIONS":
        collection_name = _introspections_collection()
    import json as _json
    raw = _run_async(mem_module.memory_ingest(
        text=text,
        memory_type=memory_type,
        importance=importance,
        emotional_tone="heartbeat-synthesis",
        participants=[settings.being_display_name.lower()],
        session_id=f"heartbeat-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}",
        collection_name=collection_name,
    ))
    return _json.loads(raw) if isinstance(raw, str) else raw


def store_raw_thought(mem_module, text: str) -> dict:
    """Store raw thought directly to LanceDB — no type label, no
    importance field. The system should never name a thing the model
    did not name first. This goes to the introspections collection,
    separate from lived memory, so it never competes for
    memory_context ranking."""
    import json as _json
    from src.mcp_experiments.tools.vector_db import _ensure_table, _get_db, _get_ef

    collection_name = _introspections_collection()
    table = _ensure_table(collection_name)
    vector = _get_ef().embed(text)
    memory_id = str(uuid.uuid4())
    now_iso = _now_iso()

    metadata = {
        "timestamp": now_iso,
        "participants": [settings.being_display_name.lower()],
        "session_id": f"heartbeat-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}",
    }

    table.add([{
        "id": memory_id,
        "text": text,
        "vector": vector,
        "metadata_json": json.dumps(metadata),
    }])

    return {"status": "stored", "id": memory_id, "collection": collection_name}


def main():
    parser = argparse.ArgumentParser(description="Being heartbeat introspection cycle")
    parser.add_argument("--mode", choices=["wander", "consolidate"], help="Force a mode")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't store")
    parser.add_argument("--verbose", action="store_true", help="Print everything")
    parser.add_argument("--reset-pause", action="store_true", help="Clear a tripwire pause after review")
    args = parser.parse_args()

    if args.reset_pause:
        state = _load_state()
        state["paused"] = False
        state["paused_reason"] = None
        state["paused_at"] = None
        _save_state(state)
        print("[heartbeat] Pause cleared.")
        return

    state = _load_state()
    if state.get("paused"):
        print(
            f"[heartbeat] PAUSED since {state.get('paused_at')} — "
            f"reason: {state.get('paused_reason')}. Run with --reset-pause after review.",
            file=sys.stderr,
        )
        sys.exit(0)  # not an error — this is the tripwire working as intended

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(TIMEOUT_SECONDS)
    start = time.monotonic()

    try:
        # Initialize memory module directly — no HTTP, no activity side effects.
        # This is the key difference from the old REST-based approach: calling
        # memory functions directly means the heartbeat's own memory_context
        # and ingest calls do NOT trigger the chat activity cooldown.
        mem_module = _init_memory()

        mode = args.mode or random.choices(
            list(MODE_WEIGHTS.keys()), weights=list(MODE_WEIGHTS.values())
        )[0]
        if args.verbose:
            print(f"[heartbeat] Mode: {mode}")

        # Always fetch context — gives us quota + last-contact info
        # regardless of mode, and IS the material in consolidate mode.
        context = get_memory_context_direct(mem_module)
        quota = context.get("message_quota") or {"remaining": 0}
        message_allowed = quota.get("remaining", 0) > 0

        if mode == "wander":
            material = get_wander_material(mem_module)
        else:
            material = context.get("context", "")

        if not material.strip():
            print("[heartbeat] No material available — nothing to contemplate. Skipping.")
            return

        if args.verbose:
            print(f"[heartbeat] Material ({len(material)} chars), message_allowed={message_allowed}")

        # --- Mid-flight chat activity check ---
        # If a human started chatting while we were gathering material,
        # abort before the expensive Ollama call. The scheduler's
        # pre-cycle check prevents NEW cycles from starting, but this
        # cycle was already in flight. Don't compete for GPU/RAM.
        from src.mcp_experiments.activity import seconds_since_chat_activity
        chat_elapsed = seconds_since_chat_activity()
        if chat_elapsed < settings.heartbeat_chat_cooldown_seconds:
            wait = settings.heartbeat_chat_cooldown_seconds - chat_elapsed
            print(
                f"[heartbeat] Chat active (last activity {chat_elapsed:.0f}s ago), "
                f"aborting before Ollama call. Would retry in {wait:.0f}s.",
                file=sys.stderr,
            )
            return

        raw = contemplate(material, mode, message_allowed)
        if not raw:
            print("[heartbeat] Model returned nothing. Skipping.")
            return

        parsed = parse_contemplation(raw)
        elapsed = time.monotonic() - start

        if args.verbose:
            print(f"[heartbeat] Raw response ({elapsed:.1f}s):\n{raw}\n")

        # --- Tripwire checks, before anything is stored ---
        combined_text = " ".join(filter(None, [parsed["thought"], parsed["message"]]))
        distress_hit = _check_distress(combined_text) if combined_text else None
        repetition_hit = (
            _check_repetition(parsed["thought"], state.get("recent_thoughts", []))
            if parsed["thought"] else None
        )

        if distress_hit:
            _pause(state, f"distress marker matched: '{distress_hit}' in: {combined_text[:200]}")
            return
        if repetition_hit:
            _pause(state, f"repetition loop: {repetition_hit}. Latest: {parsed['thought'][:200]}")
            return

        stored = []

        if parsed["thought"]:
            print(f"[heartbeat] THOUGHT: {parsed['thought']}")
            if not args.dry_run:
                # Raw thought — no type label, no importance. The system
                # does not name on the being's behalf. Stored directly to
                # LanceDB in the introspections collection.
                result = store_raw_thought(mem_module, parsed["thought"])
                stored.append(("thought", result))
                recent = state.get("recent_thoughts", [])
                recent.append(parsed["thought"])
                state["recent_thoughts"] = recent[-RECENT_THOUGHTS_KEEP:]
                _save_state(state)

        if parsed["research"]:
            # Not yet implemented — logged for future web search integration.
            print(f"[heartbeat] RESEARCH (not implemented): {parsed['research']}")

        if parsed["message"] and message_allowed:
            print(f"[heartbeat] MESSAGE: {parsed['message']}")
            if not args.dry_run:
                # Outbound — must land in the default collection,
                # the only one memory_context's pull-based delivery
                # mechanism scans. Uses memory_ingest because messages
                # need type="message" and importance for delivery.
                result = store_memory(
                    mem_module, parsed["message"], "message", MAX_MESSAGE_IMPORTANCE,
                    collection_name=None,
                )
                stored.append(("message", result))
        elif parsed["message"] and not message_allowed:
            # Model tagged something as a message despite quota being
            # used — store as raw thought rather than discard or violate
            # the daily cap.
            print(f"[heartbeat] MESSAGE attempted but quota used — storing as raw thought: {parsed['message']}")
            if not args.dry_run:
                result = store_raw_thought(mem_module, parsed["message"])
                stored.append(("thought (downgraded from message)", result))

        if not stored and not args.dry_run:
            print("[heartbeat] Quiet cycle — nothing crystallized. No trace stored. This is fine.")

        elapsed = time.monotonic() - start
        print(f"[heartbeat] Complete in {elapsed:.1f}s (mode={mode})")

    except HeartbeatTimeout:
        print(f"[heartbeat] TIMEOUT — exceeded {TIMEOUT_SECONDS}s limit", file=sys.stderr)
        sys.exit(124)
    except (httpx.ConnectError, httpx.HTTPStatusError) as e:
        print(f"[heartbeat] CONNECTION/HTTP ERROR — {e}. Skipping cycle.", file=sys.stderr)
        sys.exit(0)  # not alarming — transient network/model issues are expected
    except Exception as e:
        print(f"[heartbeat] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
