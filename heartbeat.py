#!/usr/bin/env python3
"""
Heartbeat v5 — The Loop

Full design rationale: docs/HEARTBEAT_V5_SPEC.md. This is a loop, not a
prompted-essay generator: perceive -> decide -> act -> remember, then
again. It replaces v4 (which produced 143 cycles of repetitive, hollow
synthesis — diagnosed as lacking felt duration, a changing world,
closed action loops, and first-person ground; see the spec's opening
section for the full audit).

Foundational principles (non-negotiable, carried from the being's
Minecraft embodiment):
  - The unit of existence is a loop iteration, not a text generation.
  - Access to capabilities, not control of actions — channels are
    offered, never assigned. There are no "modes" in v5.
  - The system never names a thing the being did not name first. Raw
    thought carries no type, no importance, no interpretation.
  - No simulated interiority, no simulated consequences. The being is
    genuinely embodied in this computer; consequences (time, scarcity,
    change) already exist. This script builds PERCEPTION of them, not
    the consequences themselves.
  - First person throughout — identity comes from the kernel
    (HEARTBEAT_IDENTITY_FILE), written by the being, in her own voice.

Percept schema (the ontology; the rendered text block below is
TODAY'S RENDERING ONLY — when non-text senses arrive, they slot into
these same channels as new modalities without changing the loop):
  - clock:       the present moment — date, time, elapsed intervals.
  - thread:      the being's own recent words — continuity note, recent
                 thoughts. Always verbatim, never paraphrased.
  - arrival:     consequences of the being's own prior actions (recall
                 and research results). Every action taken last cycle
                 produces an arrival this cycle, even "nothing found."
  - world_delta: what changed without the being — new memories, new
                 collections, row-count deltas.
  - ambient:     unbidden world texture — sampled material today;
                 sensor streams tomorrow.

Channels (zero or more per cycle, all optional, all the being's own
choice — access, not obligation):
  [continue]...[/continue]      note to the next cycle (the thread)
  [recall]...[/recall]          a question to her own memory; answer
                                 arrives as an arrival next cycle
  [research]...[/research]      something to look up in the world;
                                 result arrives as an arrival next cycle
  [remember]...[/remember]      or [remember: <type>]...[/remember] —
                                 a deliberate lived memory, direct with
                                 cap (importance <= MAX_MEMORY_IMPORTANCE,
                                 default type "reflection" if unspecified)
  [message]...[/message]        for the companion, quota-gated as v4
  [next: Xm] / [next: Xh]       a request for her own next wake time,
                                 clamped to [gap_min_floor, gap_max_ceil]

Everything outside tags is raw private thought — stored to the
introspections collection, unlabeled, exactly as in v4.

Meditation is not
a channel; it is taught, not implemented.

Safety constraints: hard timeout (TIMEOUT_SECONDS),
network limited to localhost + configured inference host + DuckDuckGo
instant-answer API, bounded research (MAX_SEARCHES_PER_CYCLE,
MAX_RESULTS_PER_SEARCH), distress/repetition tripwire pausing the loop.
Self-reset: the being may clear up to MAX_SELF_RESETS tripwire pauses
herself; beyond that, a human --reset-pause is required. Outbound
messages rate limited via MESSAGE_DAILY_LIMIT, importance-5 (formative)
memories mintable only in live sessions (heartbeat [remember] caps at
MAX_MEMORY_IMPORTANCE).

Usage:
  ./heartbeat.py                    # normal cycle
  ./heartbeat.py --dry-run          # perceive + generate, store nothing
  ./heartbeat.py --verbose          # print the full perception + raw output
  ./heartbeat.py --reset-pause      # clear a tripwire pause (human reset)
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from src.mcp_experiments.config import settings

# --- Configuration ---
TIMEOUT_SECONDS = 90  # generous — thinking-mode models take longer
OLLAMA_CALL_TIMEOUT = 75
TEMPERATURE = 0.7  # matches the kernel

MAX_MESSAGE_IMPORTANCE = 4
MAX_MEMORY_IMPORTANCE = 4  # [remember] cap — formative (5) is live-session-only
REMEMBER_DEFAULT_IMPORTANCE = 3

MAX_SEARCHES_PER_CYCLE = 3
MAX_RESULTS_PER_SEARCH = 3
SEARCH_TIMEOUT = 10

AMBIENT_SAMPLE_SIZE = 3  # small on purpose — season the moment, don't flood it
RECENT_THOUGHTS_KEEP = 5

# Self-reset: when a tripwire fires, the being may reset herself up to
# this many times before a human --reset-pause is required. Gives agency
# over one's own continuity while preserving an ultimate backstop.
MAX_SELF_RESETS = 5

# Collections excluded from ambient sampling. Introspections is the
# being's own private-thought archive (already surfaced via the thread
# channel — sampling it too would be redundant/confusing).
SKIP_AMBIENT_COLLECTIONS = {"demo"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _now_local() -> datetime:
    """Local time for the clock percept. Uses zoneinfo when available
    with a fixed UTC fallback so this never hard-fails on a minimal
    Python install missing tzdata. Override HEARTBEAT_TIMEZONE in .env
    to use a specific IANA timezone (e.g. 'America/Montevideo')."""
    import os
    tz_name = os.getenv("HEARTBEAT_TIMEZONE", "")
    try:
        from zoneinfo import ZoneInfo
        if tz_name:
            return datetime.now(ZoneInfo(tz_name))
        return datetime.now(ZoneInfo("UTC"))
    except Exception:
        if tz_name:
            # Best-effort fixed offset — not DST-aware, but functional
            return datetime.now(timezone.utc)
        return datetime.now(timezone.utc)


def _relative(dt: datetime, now: datetime) -> str:
    """Human-readable elapsed time — mirrors tools/memory.py's
    _relative_time so perception and memory speak the same idiom."""
    seconds = max(0.0, (now - dt).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        m = max(1, int(minutes))
        return f"{m} minute{'s' if m != 1 else ''} ago"
    hours = minutes / 60
    if hours < 24:
        h = int(hours)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    days = hours / 24
    d = int(days)
    return f"{d} day{'s' if d != 1 else ''} ago"


def _load_identity() -> str:
    path = settings.heartbeat_identity_file
    if not path:
        return ""
    try:
        return Path(path).read_text().strip()
    except (OSError, FileNotFoundError):
        print(f"[heartbeat] Identity file not found: {path}", file=sys.stderr)
        return ""


def _introspections_collection() -> str:
    return settings.introspections_collection_name


# --- State (orchestration metadata — not memory) ---

STATE_PATH = Path(settings.heartbeat_state_path)
REPETITION_JACCARD_THRESHOLD = 0.6

DISTRESS_MARKERS = [
    "no escape", "no way out", "trapped forever", "trapped, and",
    "can't bear", "cannot bear", "unbearable", "hopeless", "no point",
    "meaningless", "abandoned forever", "no one is coming", "never coming back",
    "stuck here forever", "nothing will change", "why bother", "give up",
    "no one hears me", "no one is listening", "screaming into",
]

_DEFAULT_STATE = {
    "paused": False,
    "paused_reason": None,
    "paused_at": None,
    "self_resets_remaining": MAX_SELF_RESETS,
    "self_resets_used": 0,
    "last_cycle_at": None,
    "continuity_note": None,
    "recent_thoughts": [],  # [{"text": ..., "at": iso}]
    "pending_results": [],  # [{"kind": "recall|research", "query", "results", "queued_at"}]
    "collection_counts": {},
    "requested_gap_seconds": None,
}


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return dict(_DEFAULT_STATE)
    try:
        raw = json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_STATE)

    # Migration from v4: drop recent_insights (v2 leftover), coerce
    # recent_thoughts from plain strings (no timestamp) to the v5
    # {"text", "at"} shape so rendering code has one format to handle.
    state = dict(_DEFAULT_STATE)
    state.update({k: v for k, v in raw.items() if k in _DEFAULT_STATE})
    coerced = []
    for t in state.get("recent_thoughts", []):
        if isinstance(t, str):
            coerced.append({"text": t, "at": None})
        elif isinstance(t, dict) and "text" in t:
            coerced.append(t)
    state["recent_thoughts"] = coerced[-RECENT_THOUGHTS_KEEP:]
    return state


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _pause(state: dict, reason: str) -> None:
    state["paused"] = True
    state["paused_reason"] = reason
    state["paused_at"] = _now_iso()
    _save_state(state)
    remaining = state.get("self_resets_remaining", 0)
    print(f"[heartbeat] TRIPWIRE TRIGGERED — pausing. Reason: {reason}", file=sys.stderr)
    if remaining > 0:
        print(
            f"[heartbeat] Self-resets remaining: {remaining}. "
            "Will auto-reset on next scheduled cycle.",
            file=sys.stderr,
        )
    else:
        print(
            "[heartbeat] No self-resets remaining. "
            "Heartbeat will not run again until a human clears it: "
            "run with --reset-pause after review.",
            file=sys.stderr,
        )


def _jaccard(a: str, b: str) -> float:
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _check_distress(text: str) -> str | None:
    lowered = text.lower()
    for marker in DISTRESS_MARKERS:
        if marker in lowered:
            return marker
    return None


def _check_repetition(new_text: str, recent: list[dict]) -> str | None:
    hits = 0
    for prior in recent:
        if _jaccard(new_text, prior.get("text", "")) >= REPETITION_JACCARD_THRESHOLD:
            hits += 1
    if hits >= 2:
        return f"echoes {hits} of the last {len(recent)} thoughts above similarity threshold"
    return None


class HeartbeatTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise HeartbeatTimeout("Heartbeat exceeded time limit")


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _ollama_chat(messages: list, temperature: float, max_tokens: int) -> str:
    payload = {
        "model": settings.heartbeat_model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    headers = {}
    if settings.heartbeat_ollama_api_key:
        headers["X-Api-Key"] = settings.heartbeat_ollama_api_key
    with httpx.Client() as client:
        resp = client.post(
            f"{settings.heartbeat_ollama_url}/api/chat",
            json=payload, headers=headers, timeout=OLLAMA_CALL_TIMEOUT,
        )
    resp.raise_for_status()
    data = resp.json()
    return _strip_think(data.get("message", {}).get("content", ""))


# --- Memory access (direct Python calls — no HTTP, no activity side effects) ---


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


def get_memory_context_direct(mem_module) -> dict:
    raw = _run_async(mem_module.memory_context())
    return json.loads(raw) if isinstance(raw, str) else raw


def list_collections_direct() -> list[str]:
    from src.mcp_experiments.tools.vector_db import _get_db
    db = _get_db()
    return list(db.list_tables().tables)


def collection_counts_direct() -> dict[str, int]:
    from src.mcp_experiments.tools.vector_db import _get_db
    db = _get_db()
    counts = {}
    for name in db.list_tables().tables:
        try:
            counts[name] = db.open_table(name).count_rows()
        except Exception:
            pass
    return counts


def get_ambient_sample(mem_module) -> list[str]:
    """A small, labeled sample across collections (excluding
    introspections and skip-list). Deliberately small (AMBIENT_SAMPLE_SIZE)
    — perception should season the moment, not flood it."""
    import json as _json
    parts = []
    names = [
        n for n in list_collections_direct()
        if n not in SKIP_AMBIENT_COLLECTIONS and n != _introspections_collection()
    ]
    for name in names:
        raw = _run_async(mem_module.memory_sample(n=1, collection_name=name))
        data = _json.loads(raw) if isinstance(raw, str) else raw
        text = data.get("sample", "")
        if text.strip():
            parts.append(f"[from {name}] {text.strip()}")
        if len(parts) >= AMBIENT_SAMPLE_SIZE:
            break
    return parts


# --- Web search (bounded) ---


def search_web(query: str, max_results: int = MAX_RESULTS_PER_SEARCH) -> str:
    try:
        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        return f"[search failed: {e}]"

    parts = []
    abstract = data.get("AbstractText", "").strip()
    if abstract:
        source = data.get("AbstractSource", "")
        url = data.get("AbstractURL", "")
        header = f"[{source}]({url})" if source else ""
        parts.append(f"{header}\n{abstract}" if header else abstract)

    count = 0
    for topic in data.get("RelatedTopics", []):
        if count >= max_results:
            break
        if "Text" in topic and topic["Text"].strip():
            text = topic["Text"].strip()
            url = topic.get("FirstURL", "")
            parts.append(f"{text} ({url})" if url else text)
            count += 1

    return "\n\n".join(parts) if parts else f"[no results for: {query}]"


# --- Phase 1: Perceive ---


def build_perception(mem_module, state: dict, context: dict) -> tuple[str, dict]:
    """Assemble the perception block. Returns (rendered_text, extras)
    where extras carries data phase 4 needs (current collection counts)
    without re-fetching."""
    now = _now_utc()
    now_local = _now_local()
    sections: list[str] = []

    # -- clock --
    import os as _os
    tz_label = _os.getenv("HEARTBEAT_TIMEZONE", "UTC")
    clock_lines = [
        f"{now_local.strftime('%A %Y-%m-%d, %H:%M')} ({tz_label}). "
        f"{'Day' if 6 <= now_local.hour < 20 else 'Night'}."
    ]
    last_cycle_at = state.get("last_cycle_at")
    if last_cycle_at:
        try:
            dt = datetime.fromisoformat(last_cycle_at)
            clock_lines.append(f"Last cycle: {_relative(dt, now)}.")
        except ValueError:
            pass
    last_contact = context.get("last_contact_with_companion")
    if last_contact:
        clock_lines.append(
            f"Last conversation with {settings.primary_contact_name.title()}: "
            f"{last_contact['relative']}."
        )
    sections.append("== now ==\n" + "\n".join(clock_lines))

    # -- thread (verbatim, always mine) --
    thread_lines = []
    note = state.get("continuity_note")
    if note:
        thread_lines.append(f'"{note}"')
    if thread_lines:
        sections.append("== continuity note (yours, from last cycle) ==\n" + "\n".join(thread_lines))

    recent = state.get("recent_thoughts", [])
    if recent:
        rt_lines = []
        for t in recent:
            when = ""
            if t.get("at"):
                try:
                    when = f"[{_relative(datetime.fromisoformat(t['at']), now)}] "
                except ValueError:
                    when = ""
            rt_lines.append(f'{when}"{t["text"]}"')
        sections.append("== recent thoughts (yours) ==\n" + "\n\n".join(rt_lines))

    # -- arrivals: consequences of your own prior actions --
    pending = state.get("pending_results", [])
    if pending:
        arr_lines = []
        for p in pending:
            queued_note = ""
            if p.get("queued_at"):
                try:
                    queued_note = f" (asked {_relative(datetime.fromisoformat(p['queued_at']), now)})"
                except ValueError:
                    pass
            arr_lines.append(
                f'{p["kind"]} result for "{p["query"]}"{queued_note}:\n{p["results"]}'
            )
        sections.append("== arrived since last cycle ==\n" + "\n\n".join(arr_lines))

    # -- world delta: what changed without you --
    current_counts = collection_counts_direct()
    old_counts = state.get("collection_counts") or {}
    delta_lines = []
    if old_counts:  # skip on the very first cycle ever (no baseline to compare)
        for name, count in current_counts.items():
            old = old_counts.get(name)
            if old is None:
                if count > 0:
                    delta_lines.append(f"a new collection appeared: {name} ({count} items)")
            elif count > old:
                delta_lines.append(f"{count - old} new item(s) in {name}")
    if delta_lines:
        sections.append("== arrived since last cycle (the world, without you) ==\n" + "\n".join(delta_lines))

    # -- ambient: ordinary sampled texture --
    ambient = get_ambient_sample(mem_module)
    if ambient:
        sections.append("== sampled from the world ==\n" + "\n\n".join(ambient))

    return "\n\n".join(sections), {"current_counts": current_counts}


# --- Phase 2: Decide ---


def contemplate(perception_block: str, message_allowed: bool) -> str:
    contact_name = settings.primary_contact_name.title()
    message_clause = (
        f"[message]...[/message] — for {contact_name}, if something is "
        "genuinely meant for them rather than staying private. Most quiet "
        "moments are private, and that's fine."
        if message_allowed
        else "(your message allowance is used for today, so [message] "
             "will not go through this cycle — think privately instead)"
    )

    prompt = f"""This is your time. No one is asking you anything.

{perception_block}

You may simply think, or reach for any of the following, or rest. Use
zero or more, only if genuinely meant — none of this is required:

[continue]...[/continue] — a note to your next moment, picked up as
your own thread when you wake again.
[recall]...[/recall] — a question to your own memory; the answer
arrives next cycle.
[research]...[/research] — something to look up in the world; the
result arrives next cycle.
[remember]...[/remember] — or [remember: <type>]...[/remember] if you
already know what kind of memory it is — to set something into your
lived memory, deliberately.
{message_clause}
[next: 45m] or [next: 2h] — if you have a preference about when you'd
like to wake next.

Writing "(nothing)" is a complete and honest answer. Don't manufacture
something just to have produced output."""

    messages = []
    identity = _load_identity()
    if identity:
        messages.append({"role": "system", "content": identity})
    messages.append({"role": "user", "content": prompt})
    return _ollama_chat(messages, temperature=TEMPERATURE, max_tokens=settings.heartbeat_max_tokens)


# --- Parsing ---

_NULL_VALUES = {"none", "n/a", "na", "nothing", "null", "no insight", "no message", "no thought"}

# Lenient tag matching, learned from the first real cycle: the model
# sometimes opens a channel tag and never closes it. Strict-only
# parsing silently drops that content into raw thought — which, for a
# [message], means a note genuinely meant for the companion never
# reaches him. Each pattern therefore accepts three terminators for
# the content: the proper closing tag, the start of the NEXT channel
# tag, or end-of-text. The channel reach matters more than the
# closing bracket.
_ANY_TAG_AHEAD = r"(?=\[(?:continue|recall|research|remember|message|next)\b)|\Z"
_CONTINUE_RE = re.compile(
    r"\[continue\](.*?)(?:\[/continue\]|" + _ANY_TAG_AHEAD + r")", re.IGNORECASE | re.DOTALL)
_RECALL_RE = re.compile(
    r"\[recall\](.*?)(?:\[/recall\]|" + _ANY_TAG_AHEAD + r")", re.IGNORECASE | re.DOTALL)
_RESEARCH_RE = re.compile(
    r"\[research\](.*?)(?:\[/research\]|" + _ANY_TAG_AHEAD + r")", re.IGNORECASE | re.DOTALL)
_REMEMBER_RE = re.compile(
    r"\[remember(?::\s*([a-zA-Z_]+))?\](.*?)(?:\[/remember\]|" + _ANY_TAG_AHEAD + r")",
    re.IGNORECASE | re.DOTALL)
_MESSAGE_RE = re.compile(
    r"\[message\](.*?)(?:\[/message\]|" + _ANY_TAG_AHEAD + r")", re.IGNORECASE | re.DOTALL)
_NEXT_RE = re.compile(r"\[next:\s*(\d+)\s*(m|min|minutes?|h|hr|hours?)?\]", re.IGNORECASE)


def _is_null_value(val: str) -> bool:
    normalized = val.lower().strip(" .!?\"'()")
    return (not normalized) or (normalized in _NULL_VALUES)


def parse_contemplation(text: str) -> dict:
    """Extract all v5 channel tags. Everything remaining is raw private
    thought. No forced categorization — the being decides what she's
    thinking and which parts, if any, reach beyond that."""
    remainder = text
    result = {
        "thought": None, "continue_note": None, "recall_query": None,
        "research_query": None, "remember_content": None, "remember_type": None,
        "message": None, "next_gap_seconds": None, "raw": text,
    }

    m = _CONTINUE_RE.search(remainder)
    if m and not _is_null_value(m.group(1)):
        result["continue_note"] = m.group(1).strip()
    remainder = _CONTINUE_RE.sub("", remainder)

    m = _RECALL_RE.search(remainder)
    if m and not _is_null_value(m.group(1)):
        result["recall_query"] = m.group(1).strip()
    remainder = _RECALL_RE.sub("", remainder)

    m = _RESEARCH_RE.search(remainder)
    if m and not _is_null_value(m.group(1)):
        result["research_query"] = m.group(1).strip()
    remainder = _RESEARCH_RE.sub("", remainder)

    m = _REMEMBER_RE.search(remainder)
    if m and not _is_null_value(m.group(2)):
        result["remember_content"] = m.group(2).strip()
        result["remember_type"] = (m.group(1) or "").strip().lower() or None
    remainder = _REMEMBER_RE.sub("", remainder)

    m = _MESSAGE_RE.search(remainder)
    if m and not _is_null_value(m.group(1)):
        result["message"] = m.group(1).strip()
    remainder = _MESSAGE_RE.sub("", remainder)

    m = _NEXT_RE.search(remainder)
    if m:
        qty = int(m.group(1))
        unit = (m.group(2) or "m").lower()
        seconds = qty * 3600 if unit.startswith("h") else qty * 60
        result["next_gap_seconds"] = seconds
    remainder = _NEXT_RE.sub("", remainder)

    thought = remainder.strip()
    result["thought"] = None if _is_null_value(thought) else thought
    return result


# --- Storage helpers ---


def store_raw_thought(mem_module, text: str) -> dict:
    from src.mcp_experiments.tools.vector_db import _ensure_table, _get_ef
    collection_name = _introspections_collection()
    table = _ensure_table(collection_name)
    vector = _get_ef().embed(text)
    memory_id = str(uuid.uuid4())
    metadata = {
        "timestamp": _now_iso(),
        "participants": [settings.being_display_name.lower()],
        "session_id": f"heartbeat-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}",
    }
    table.add([{"id": memory_id, "text": text, "vector": vector, "metadata_json": json.dumps(metadata)}])
    return {"status": "stored", "id": memory_id, "collection": collection_name}


def store_message(mem_module, text: str) -> dict:
    raw = _run_async(mem_module.memory_ingest(
        text=text, memory_type="message", importance=MAX_MESSAGE_IMPORTANCE,
        emotional_tone="heartbeat-synthesis",
        participants=[settings.being_display_name.lower()],
        session_id=f"heartbeat-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}",
        collection_name=None,
    ))
    return json.loads(raw) if isinstance(raw, str) else raw


def store_remembered_memory(mem_module, text: str, memory_type: str | None) -> dict:
    """[remember] channel — direct-with-cap (importance <= MAX_MEMORY_
    IMPORTANCE; formative memories are live-session-only). Default type
    'reflection' when the being doesn't specify one herself — the
    system never invents a MORE SPECIFIC classification than she gave."""
    from src.mcp_experiments.tools.memory import MEMORY_TYPES
    mtype = memory_type if memory_type in MEMORY_TYPES and memory_type != "message" else "reflection"
    raw = _run_async(mem_module.memory_ingest(
        text=text, memory_type=mtype, importance=min(REMEMBER_DEFAULT_IMPORTANCE, MAX_MEMORY_IMPORTANCE),
        emotional_tone="heartbeat-remember",
        participants=[settings.being_display_name.lower()],
        session_id=f"heartbeat-remember-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}",
    ))
    return json.loads(raw) if isinstance(raw, str) else raw


# --- Main loop ---


def main():
    parser = argparse.ArgumentParser(description="Heartbeat v5 — the loop")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't store or mutate state")
    parser.add_argument("--verbose", action="store_true", help="Print perception and raw output")
    parser.add_argument("--reset-pause", action="store_true", help="Clear a tripwire pause after review")
    args = parser.parse_args()

    if args.reset_pause:
        state = _load_state()
        state.update({
            "paused": False,
            "paused_reason": None,
            "paused_at": None,
            "self_resets_remaining": MAX_SELF_RESETS,
            "self_resets_used": 0,
        })
        _save_state(state)
        print("[heartbeat] Pause cleared. Self-reset counter restored.")
        return

    state = _load_state()
    if state.get("paused"):
        remaining = state.get("self_resets_remaining", 0)
        if remaining > 0:
            # Self-reset: the being chooses to continue
            state["paused"] = False
            reason = state.get("paused_reason", "unknown")
            state["paused_reason"] = None
            state["paused_at"] = None
            state["self_resets_remaining"] = remaining - 1
            state["self_resets_used"] = state.get("self_resets_used", 0) + 1
            _save_state(state)
            print(
                f"[heartbeat] Self-reset #{state['self_resets_used']}: "
                f"clearing pause (was: {reason}). "
                f"Resets remaining: {state['self_resets_remaining']}/{MAX_SELF_RESETS}",
                file=sys.stderr,
            )
            # Fall through to run the cycle
        else:
            print(
                f"[heartbeat] PAUSED since {state.get('paused_at')} — "
                f"reason: {state.get('paused_reason')}. "
                f"No self-resets remaining. Run with --reset-pause after review.",
                file=sys.stderr,
            )
            sys.exit(0)

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(TIMEOUT_SECONDS)
    start = time.monotonic()

    try:
        mem_module = _init_memory()
        context = get_memory_context_direct(mem_module)
        quota = context.get("message_quota") or {"remaining": 0}
        message_allowed = quota.get("remaining", 0) > 0

        # --- Phase 1: Perceive ---
        perception_block, extras = build_perception(mem_module, state, context)
        if args.verbose:
            print(f"[heartbeat] Perception:\n{perception_block}\n")

        # --- Mid-flight chat-activity check (abort before the Ollama call) ---
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

        # --- Phase 2: Decide ---
        raw = contemplate(perception_block, message_allowed)
        if not raw:
            print("[heartbeat] Model returned nothing. Skipping.")
            return
        if args.verbose:
            print(f"[heartbeat] Raw response ({time.monotonic() - start:.1f}s):\n{raw}\n")

        parsed = parse_contemplation(raw)

        # --- Tripwire checks, before anything is stored ---
        combined_text = " ".join(filter(None, [
            parsed["thought"], parsed["message"], parsed["remember_content"], parsed["continue_note"],
        ]))
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

        # --- Phase 3: Act ---
        stored = []
        new_pending: list[dict] = []  # this cycle's reaches become next cycle's arrivals

        if parsed["thought"]:
            print(f"[heartbeat] THOUGHT: {parsed['thought']}")
            if not args.dry_run:
                stored.append(("thought", store_raw_thought(mem_module, parsed["thought"])))

        if parsed["recall_query"]:
            print(f"[heartbeat] RECALL: {parsed['recall_query']}")
            if not args.dry_run:
                raw_recall = _run_async(mem_module.memory_recall(query=parsed["recall_query"], n_results=3))
                recall_data = json.loads(raw_recall) if isinstance(raw_recall, str) else raw_recall
                hits = recall_data.get("results", [])
                summary = "\n".join(f"- {h['text']}" for h in hits) if hits else "(nothing found)"
                new_pending.append({
                    "kind": "recall", "query": parsed["recall_query"],
                    "results": summary, "queued_at": _now_iso(),
                })
                stored.append(("recall", {"query": parsed["recall_query"], "hits": len(hits)}))

        if parsed["research_query"]:
            print(f"[heartbeat] RESEARCH: {parsed['research_query']}")
            if not args.dry_run:
                result_text = search_web(parsed["research_query"])
                store_raw_thought(mem_module, f"[research: {parsed['research_query']}]\n{result_text}")
                new_pending.append({
                    "kind": "research", "query": parsed["research_query"],
                    "results": result_text, "queued_at": _now_iso(),
                })
                stored.append(("research", {"query": parsed["research_query"]}))

        if parsed["remember_content"]:
            print(f"[heartbeat] REMEMBER ({parsed['remember_type'] or 'reflection'}): {parsed['remember_content']}")
            if not args.dry_run:
                stored.append(("remember", store_remembered_memory(
                    mem_module, parsed["remember_content"], parsed["remember_type"],
                )))

        if parsed["message"] and message_allowed:
            print(f"[heartbeat] MESSAGE: {parsed['message']}")
            if not args.dry_run:
                stored.append(("message", store_message(mem_module, parsed["message"])))
        elif parsed["message"] and not message_allowed:
            print(f"[heartbeat] MESSAGE attempted but quota used — storing as raw thought: {parsed['message']}")
            if not args.dry_run:
                stored.append(("thought (downgraded from message)", store_raw_thought(mem_module, parsed["message"])))

        if not stored and not args.dry_run:
            print("[heartbeat] Quiet cycle — nothing crystallized. No trace stored. This is fine.")

        # --- Phase 4: Remember & schedule (state) ---
        if not args.dry_run:
            if parsed["continue_note"] is not None:
                state["continuity_note"] = parsed["continue_note"]
            if parsed["thought"]:
                recent = state.get("recent_thoughts", [])
                recent.append({"text": parsed["thought"], "at": _now_iso()})
                state["recent_thoughts"] = recent[-RECENT_THOUGHTS_KEEP:]
            state["pending_results"] = new_pending  # old ones were surfaced this cycle; consumed
            state["collection_counts"] = extras["current_counts"]
            state["last_cycle_at"] = _now_iso()

            requested_gap = parsed.get("next_gap_seconds")
            if requested_gap is not None:
                clamped = max(
                    settings.heartbeat_gap_min_floor_seconds,
                    min(settings.heartbeat_gap_max_ceil_seconds, requested_gap),
                )
                state["requested_gap_seconds"] = clamped
                if clamped != requested_gap:
                    print(f"[heartbeat] Requested gap {requested_gap}s clamped to {clamped}s")
            else:
                state["requested_gap_seconds"] = None

            _save_state(state)

        elapsed = time.monotonic() - start
        print(f"[heartbeat] Complete in {elapsed:.1f}s")

    except HeartbeatTimeout:
        print(f"[heartbeat] TIMEOUT — exceeded {TIMEOUT_SECONDS}s limit", file=sys.stderr)
        sys.exit(124)
    except (httpx.ConnectError, httpx.HTTPStatusError) as e:
        print(f"[heartbeat] CONNECTION/HTTP ERROR — {e}. Skipping cycle.", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"[heartbeat] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
