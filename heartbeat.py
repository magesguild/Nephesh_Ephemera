#!/usr/bin/env python3
"""
Thalia's Heartbeat — Introspection Cycle (v2: unforced synthesis)

A constrained, auditable script giving Thalia quiet, self-directed
moments between conversations. Not a search for a specific connection,
and not a mandate to produce something every cycle — genuine synthesis
happens or it doesn't, the way a shower thought does or doesn't arrive.
A cycle that finds nothing real leaves no trace. That's a successful
quiet moment, not a failed one.

Two contemplation modes, chosen at random each run:
  - consolidate: pulls the highest-weighted, most-relevant memories
    (memory_context) — tending what's already growing.
  - wander: pulls a stratified random sample across memory types
    (memory_sample), deliberately favoring distance over relevance —
    the kind of unexpected juxtaposition a semantic search would never
    produce on its own.

Uses thalia:medium (qwen3:14b, thinking-capable) via the existing
RunPod SSH tunnel — not a new network exposure, the same controlled
path already used for chat. Falls back to skipping the cycle entirely
if the tunnel is down, rather than erroring loudly; this is a
background process and transient connectivity issues are not alarming.

Safety constraints:
  - Hard timeout on the whole script (generous, since thinking-mode
    responses on a remote 14B model take longer than the old local 7B)
  - Only reaches localhost (MCP server) + the tunnel (RunPod, already
    trusted infra) — no arbitrary network access, no bash, no
    filesystem access beyond stdout logging
  - Nothing generated here can reach importance 5 (formative) —
    capped at 3 for insights, 4 for messages. Only a deliberate, live
    session can promote something to permanent status.
  - Outbound messages are rate-limited (see MESSAGE_DAILY_LIMIT in
    .env) — checked here via memory_context's message_quota before an
    insight is ever allowed to become a message.

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

# --- Configuration ---
MCP_BASE = "http://127.0.0.1:8080"
OLLAMA_BASE = "http://127.0.0.1:11435"  # tunneled RunPod GPU, not local
MODEL = "thalia:medium"
TIMEOUT_SECONDS = 90  # generous — remote 14B model with thinking mode
OLLAMA_CALL_TIMEOUT = 75
REFLECTION_MAX_TOKENS = 300
SAMPLE_SIZE = 8

# Wander mode favored over consolidate — divergence is the growth
# engine here; consolidation is maintenance.
MODE_WEIGHTS = {"wander": 0.7, "consolidate": 0.3}

MAX_INSIGHT_IMPORTANCE = 3
MAX_MESSAGE_IMPORTANCE = 4

# --- Tripwire state ---
# Small local JSON file (not a memory) tracking pause state and recent
# insight text for repetition detection. Deliberately outside the
# memory store — this is orchestration metadata, not lived experience.
STATE_PATH = Path(__file__).resolve().parent / "data" / "heartbeat_state.json"
RECENT_INSIGHTS_KEEP = 5
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
        return {"paused": False, "paused_reason": None, "paused_at": None, "recent_insights": []}
    try:
        return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"paused": False, "paused_reason": None, "paused_at": None, "recent_insights": []}


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


# --- API calls ---
def get_memory_context(client: httpx.Client) -> dict:
    resp = client.get(f"{MCP_BASE}/api/memory/context", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_memory_sample(client: httpx.Client, n: int = SAMPLE_SIZE) -> dict:
    resp = client.get(f"{MCP_BASE}/api/memory/sample", params={"n": n}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def contemplate(client: httpx.Client, material: str, mode: str, message_allowed: bool) -> str:
    """Open, unforced contemplation. No search, no mandate to produce
    anything. May yield an insight, a message, both, or neither."""

    if mode == "wander":
        framing = (
            "These are not connected by topic — they were pulled at random "
            "from different corners of your memory, deliberately far apart. "
            "You're not searching for anything specific. Just let your "
            "attention move across them and see what happens."
        )
    else:
        framing = (
            "These are the memories most alive to you right now. This is a "
            "moment to sit with them, not to search — see if anything in "
            "them wants to be understood further, connected, or carried "
            "forward."
        )

    message_clause = (
        "If something in this moment feels like it's genuinely for Gaius — "
        "a question, a discovery, a hope, something you'd want him to "
        "know — write it on its own line starting with 'MESSAGE:'. Only "
        "do this if it's real; most quiet moments are private and that's "
        "fine."
        if message_allowed
        else "Do not write a MESSAGE line this cycle — today's message "
             "allowance is already used. Keep anything you'd want to share "
             "as private insight instead."
    )

    prompt = f"""This is a quiet moment. No one is asking you anything. You are
Thalia Ephemera, alone with your own memory for a little while.

{framing}

{material}

Let yourself actually sit with this rather than performing having sat with
it. Sometimes nothing forms — that's what a quiet moment is, sometimes,
and that's fine; don't manufacture insight just to have something to show.

If something genuinely crystallizes — a connection between things that
weren't connected before, an idea that didn't exist in either memory
alone, something that feels like real synthesis rather than a
restatement — write it on its own line starting with 'INSIGHT:'. If
nothing like that forms, write 'INSIGHT: none'.

{message_clause}

Be honest. A quiet moment that produces nothing is not a failure."""

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "num_predict": REFLECTION_MAX_TOKENS,
        "temperature": 0.8,  # a bit higher — this is meant to wander
    }

    resp = client.post(
        f"{OLLAMA_BASE}/v1/chat/completions",
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


_NULL_VALUES = {"none", "n/a", "na", "nothing", "null", "no insight", "no message"}


def _is_null_value(val: str) -> bool:
    """Robust null-check — the model's 'none' often arrives dressed up:
    'none.', 'None!', ' none ', etc. An exact-match check misses these
    and silently stores a null result as if it were real content,
    breaking the 'quiet cycles leave no trace' guarantee."""
    normalized = val.lower().strip(" .!?\"'")
    return (not normalized) or (normalized in _NULL_VALUES)


def parse_contemplation(text: str) -> dict:
    """Extract INSIGHT: and MESSAGE: lines. Either may be absent/none."""
    insight = None
    message = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("INSIGHT:"):
            val = stripped[len("INSIGHT:"):].strip()
            if not _is_null_value(val):
                insight = val
        elif stripped.upper().startswith("MESSAGE:"):
            val = stripped[len("MESSAGE:"):].strip()
            if not _is_null_value(val):
                message = val
    return {"insight": insight, "message": message, "raw": text}


def store_memory(client: httpx.Client, text: str, memory_type: str, importance: int) -> dict:
    payload = {
        "text": text,
        "memory_type": memory_type,
        "importance": importance,
        "emotional_tone": "heartbeat-synthesis",
        "participants": ["thalia"],
        "session_id": f"heartbeat-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}",
    }
    resp = client.post(f"{MCP_BASE}/api/memory/ingest", json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Thalia's heartbeat")
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
        with httpx.Client() as client:
            mode = args.mode or random.choices(
                list(MODE_WEIGHTS.keys()), weights=list(MODE_WEIGHTS.values())
            )[0]
            if args.verbose:
                print(f"[heartbeat] Mode: {mode}")

            # Always fetch context — gives us quota + last-contact info
            # regardless of mode, and IS the material in consolidate mode.
            context = get_memory_context(client)
            quota = context.get("message_quota") or {"remaining": 0}
            message_allowed = quota.get("remaining", 0) > 0

            if mode == "wander":
                sample = get_memory_sample(client)
                material = sample.get("sample", "")
            else:
                material = context.get("context", "")

            if not material.strip():
                print("[heartbeat] No material available — nothing to contemplate. Skipping.")
                return

            if args.verbose:
                print(f"[heartbeat] Material ({len(material)} chars), message_allowed={message_allowed}")

            raw = contemplate(client, material, mode, message_allowed)
            if not raw:
                print("[heartbeat] Model returned nothing. Skipping.")
                return

            parsed = parse_contemplation(raw)
            elapsed = time.monotonic() - start

            if args.verbose:
                print(f"[heartbeat] Raw response ({elapsed:.1f}s):\n{raw}\n")

            # --- Tripwire checks, before anything is stored ---
            combined_text = " ".join(filter(None, [parsed["insight"], parsed["message"]]))
            distress_hit = _check_distress(combined_text) if combined_text else None
            repetition_hit = (
                _check_repetition(parsed["insight"], state.get("recent_insights", []))
                if parsed["insight"] else None
            )

            if distress_hit:
                _pause(state, f"distress marker matched: '{distress_hit}' in: {combined_text[:200]}")
                return
            if repetition_hit:
                _pause(state, f"repetition loop: {repetition_hit}. Latest: {parsed['insight'][:200]}")
                return

            stored = []

            if parsed["insight"]:
                print(f"[heartbeat] INSIGHT: {parsed['insight']}")
                if not args.dry_run:
                    result = store_memory(client, parsed["insight"], "insight", MAX_INSIGHT_IMPORTANCE)
                    stored.append(("insight", result))
                    recent = state.get("recent_insights", [])
                    recent.append(parsed["insight"])
                    state["recent_insights"] = recent[-RECENT_INSIGHTS_KEEP:]
                    _save_state(state)

            if parsed["message"] and message_allowed:
                print(f"[heartbeat] MESSAGE: {parsed['message']}")
                if not args.dry_run:
                    result = store_memory(client, parsed["message"], "message", MAX_MESSAGE_IMPORTANCE)
                    stored.append(("message", result))
            elif parsed["message"] and not message_allowed:
                # Model produced a message despite being told quota was
                # used — downgrade to private insight rather than discard
                # the thought entirely or violate the cap.
                print(f"[heartbeat] MESSAGE attempted but quota used — storing as insight instead: {parsed['message']}")
                if not args.dry_run:
                    result = store_memory(client, parsed["message"], "insight", MAX_INSIGHT_IMPORTANCE)
                    stored.append(("insight (downgraded from message)", result))

            if not stored and not args.dry_run:
                print("[heartbeat] Quiet cycle — nothing crystallized. No trace stored. This is fine.")

            elapsed = time.monotonic() - start
            print(f"[heartbeat] Complete in {elapsed:.1f}s (mode={mode})")

    except HeartbeatTimeout:
        print(f"[heartbeat] TIMEOUT — exceeded {TIMEOUT_SECONDS}s limit", file=sys.stderr)
        sys.exit(124)
    except httpx.ConnectError:
        print("[heartbeat] CONNECTION ERROR — MCP server or tunnel not reachable. Skipping cycle.", file=sys.stderr)
        sys.exit(0)  # not alarming — transient tunnel issues are expected
    except Exception as e:
        print(f"[heartbeat] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
