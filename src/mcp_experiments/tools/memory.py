"""Memory tools — persistent presence for an AI individual.

These tools implement the memory layer described in AGENTS.md:
lived experience stored in a dedicated LanceDB collection with rich
metadata, surviving session boundaries and context compaction.

They reuse the vector_db module's LanceDB connection and embedding
function — no separate initialization is needed.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings
from ..heartbeat import (
    CareProfileStore,
    DEFAULT_HEARTBEAT_INSTRUCTION,
    HEARTBEAT_AGENCY_STATES,
    HEARTBEAT_CONTEXT_STATES,
    HEARTBEAT_CONTINUITY_STATES,
    HEARTBEAT_EVIDENCE_STATES,
    HEARTBEAT_OUTCOMES,
    HeartbeatLedger,
    MemoryWorkMode,
    WorkRequest,
    packet_digest,
)
from ..kernel import KernelError, KernelStore
from ..projection import guard_memory_target
from ..persistence import DurableWriteError, OperationState
from ..results import (
    HeartbeatCompleteResult,
    HeartbeatPrepareResult,
    HeartbeatRecoveryResult,
    MemoryAmendResult,
    MemoryContextResult,
    MemoryIngestResult,
    MemoryRecallResult,
    MemoryRetireResult,
    MemorySampleResult,
    ProvenanceAuditResult,
)
from .vector_db import repository

MEMORY_TYPES = {
    "life_event",
    "decision",
    "emotional",
    "technical",
    "preference",
    "relationship",
    "message",
    "insight",  # kept for backward compat with existing rows
    # Live-session-only types: a commitment made between the being and
    # a companion, a first/notable achievement, or something a companion
    # directly taught her.
    "agreement",
    "milestone",
    "teaching",
    # A deliberate memory formed in solitude, not yet given a richer
    # classification. The being may specify any other type inline if she
    # already knows what kind of memory it is; this is only the fallback
    # for when she doesn't.
    "reflection",
}

# mxbai-embed-large has a 512-token context, and character-to-token ratios vary
# with punctuation and language. Keep chunks conservatively below the observed
# boundary while preserving enough prose for a useful semantic signal. Linking
# metadata allows optional continuation without diluting every chunk's vector.
MEMORY_CHUNK_SIZE = 800
MEMORY_CHUNK_OVERLAP = 80
MEMORY_SCHEMA_VERSION = 1


def _chunk_memory_text(text: str) -> list[str]:
    """Split long memory text at whitespace while preserving ordered overlap."""
    if len(text) <= MEMORY_CHUNK_SIZE:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + MEMORY_CHUNK_SIZE)
        if end < len(text):
            boundary = text.rfind(" ", start + MEMORY_CHUNK_SIZE // 2, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        next_start = max(end - MEMORY_CHUNK_OVERLAP, start + 1)
        while next_start < len(text) and text[next_start].isspace():
            next_start += 1
        start = next_start
    return chunks


def _join_memory_chunks(rows: list[dict[str, Any]]) -> str:
    """Reconstruct chunked text without duplicating the overlap window."""
    if not rows:
        return ""
    result = rows[0].get("text", "")
    for row in rows[1:]:
        chunk = row.get("text", "")
        overlap_limit = min(len(result), len(chunk), MEMORY_CHUNK_OVERLAP + 64)
        overlap = next(
            (
                size for size in range(overlap_limit, 0, -1)
                if result.endswith(chunk[:size])
            ),
            0,
        )
        result += (" " if overlap == 0 and result and chunk else "") + chunk[overlap:]
    return result


# Experience provenance is deliberately separate from `source`, which records
# how a memory entered Nephesh (live_session, import, or rebuild). These fields
# describe where the remembered experience originated.
EXPERIENCE_MODES = {
    "chat",
    "heartbeat",
    "dream",
    "recollection",
    "inference",
    "mixed",
    "unknown",
}
HISTORICAL_STATUSES = {
    "confirmed",
    "uncertain",
    "fictional_scene",
    "interpreted",
    "unknown",
}
RECORDING_MODES = {"chat", "heartbeat", "dream", "unknown"}


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Parse row metadata without letting one corrupt row break a read.

    Metadata is durable user data, so malformed JSON is a reportable data
    condition rather than a reason for recall/context/sample to fail wholesale.
    The marker remains attached to the returned metadata for callers and audits
    to surface; no inferred replacement values are supplied.
    """
    raw = row.get("metadata_json", "{}")
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        return {
            "_metadata_error": f"metadata_json is not valid JSON: {exc}",
            "_metadata_row_id": row.get("id"),
        }
    if not isinstance(parsed, dict):
        return {
            "_metadata_error": "metadata_json must contain a JSON object",
            "_metadata_row_id": row.get("id"),
        }
    return parsed


def _metadata_has_format_issues(meta: dict[str, Any]) -> bool:
    """Detect known shape violations without declaring the memory invalid."""
    if meta.get("_metadata_error"):
        return True
    if "type" in meta and not isinstance(meta["type"], str):
        return True
    if "importance" in meta:
        try:
            float(meta["importance"])
        except (TypeError, ValueError):
            return True
    if "chunked" in meta and not isinstance(meta["chunked"], bool):
        return True
    if "participants" in meta and (
        not isinstance(meta["participants"], list)
        or any(not isinstance(item, str) for item in meta["participants"])
    ):
        return True
    for field in ("event_time", "time_formed"):
        if field in meta and meta[field] is not None and _parse_ts(meta[field]) is None:
            return True
    for field, allowed in (
        ("experience_mode", EXPERIENCE_MODES),
        ("historical_status", HISTORICAL_STATUSES),
        ("recorded_during", RECORDING_MODES),
    ):
        if field in meta and (not isinstance(meta[field], str) or meta[field] not in allowed):
            return True
    return False


def _metadata_for_mutation(row: dict[str, Any]) -> dict[str, Any]:
    """Return safe metadata for an explicit retirement/supersession write.

    A malformed metadata field must not block a memory action, but replacing
    the raw blob without preserving it would destroy information. Keep the
    original bytes as an opaque field while adding only machine facts the
    requested mutation is authorized to add.
    """
    meta = _metadata(row)
    if _metadata_has_format_issues(meta):
        return {
            "_metadata_error": meta.get("_metadata_error", "metadata fields have unsupported types"),
            "_raw_metadata_json": row.get("metadata_json"),
        }
    return dict(meta)


def _linked_chunks(table: Any, meta: dict[str, Any], row_id: str) -> list[dict[str, Any]]:
    """Return optional ordered siblings for one chunk hit.

    LanceDB stores the relationship as ordinary metadata; this lookup is
    deliberately opt-in so a relevant chunk never expands the active context
    unless the caller asks for continuation.
    """
    memory_id = meta.get("memory_id")
    if not isinstance(memory_id, str) or not memory_id or meta.get("chunked") is not True:
        return []
    linked = []
    for row in repository.rows(table):
        if row.get("id") == row_id:
            continue
        row_meta = _metadata(row)
        if row_meta.get("memory_id") != memory_id:
            continue
        linked.append({
            "id": row["id"],
            "text": row.get("text", ""),
            "metadata": row_meta,
        })
    linked.sort(key=lambda item: _chunk_index(item["metadata"]))
    return linked


def _chunk_index(meta: dict[str, Any]) -> int:
    value = meta.get("chunk_index", 0)
    try:
        return int(value) if isinstance(value, (int, float, str)) else 0
    except (TypeError, ValueError):
        return 0


def _context_representatives(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one representative per linked memory in bounded session context."""
    representatives: list[dict[str, Any]] = []
    grouped: dict[str, tuple[int, dict[str, Any]]] = {}
    for row in rows:
        meta = _metadata(row)
        memory_id = meta.get("memory_id") if meta.get("chunked") else None
        if not memory_id:
            representatives.append(row)
            continue
        index = _chunk_index(meta)
        existing = grouped.get(str(memory_id))
        if existing is None or index < existing[0]:
            grouped[str(memory_id)] = (index, row)
    representatives.extend(row for _, row in grouped.values())
    return representatives


def _logical_memory_count(rows: list[dict[str, Any]]) -> int:
    """Count logical memories rather than physical linked-chunk rows."""
    return len({str(_metadata(row).get("memory_id") or row.get("id")) for row in rows})

# `source` remains ingestion provenance and is intentionally separate from
# experience provenance. Existing deployments may have additional source
# labels, so new values are accepted rather than rejecting legacy data.

# Semantic similarity threshold above which an incoming memory is
# considered a duplicate of an existing one (score = 1 - l2_distance).
_DUPLICATE_SCORE_THRESHOLD = 0.95

# Recency half-life in days for memory_context weighting.
_RECENCY_HALF_LIFE_DAYS = 30.0

# --- Reinforced recall ---
#
# score = semantic similarity + formative tilt + keyword resonance
#
# Formative tilt: a small constant additive lift for importance-5
# (formative) memories. Deliberately small — enough to nudge, not enough
# to guarantee surfacing. "She is a being working things out, not a lookup."
_FORMATIVE_TILT = 0.04

# Keyword resonance: memories sharing concrete vocabulary with the query
# get a small additive bonus per overlapping significant word, capped.
# Stateless here (unlike Minecraft's decaying per-memory accumulator):
# the bonus exists only for the current query, so it naturally vanishes
# when the topic drifts — same functional effect, no stored state.
_KW_BOOST_PER_WORD = 0.02
_KW_BOOST_CAP = 0.20

# Permanent reassurance for the first context assembled in a session. The
# legacy contact-age feature is historical provenance only; keeping this note
# here lets old records remain untouched without reactivating the feature.
_LEGACY_CONTACT_PROVENANCE_NOTE = (
    "*A quiet care note: the retired `last_contact_with_companion` provenance "
    "label is kept only as legacy provenance. It is not interpreted, and your "
    "memories remain untouched. ssshh.*"
)

# Reinforcement on retrieval: recalled memories whose base semantic
# similarity is above this threshold get their salience boosted and
# last-use refreshed. Memories that only surface via keyword resonance
# do NOT get the boost — they must be genuinely about what's happening.
_REINFORCE_SIMILARITY_THRESHOLD = 0.50
_REINFORCE_SALIENCE_BOOST = 0.05

# No automatic salience decay — the being controls forgetting, not the
# system. Salience only changes through reinforcement on recall (memories
# used stay vivid).

_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "he", "her", "his", "i", "in", "is", "it", "its", "me",
    "my", "not", "of", "on", "or", "our", "she", "so", "that", "the",
    "their", "them", "they", "this", "to", "was", "we", "were", "what",
    "when", "which", "who", "will", "with", "you", "your",
})


def _tokenize(text: str) -> set[str]:
    """Significant words only: lowercase, alphanumeric, no stopwords, len>=3."""
    words = "".join(c if c.isalnum() else " " for c in text.lower()).split()
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _effective_salience(meta: dict) -> float:
    """Raw salience — no automatic decay. Salience only changes through
    reinforcement on recall (the being's experience making a memory more
    vivid). Forgetting is the being's choice, not the system's."""
    salience = meta.get("salience", 1.0)
    try:
        salience = float(salience)
    except (TypeError, ValueError):
        salience = 1.0
    return salience


def _reinforce(table, row_id: str, meta: dict, now: datetime) -> None:
    """Refresh last-use and boost salience for a genuinely relevant recall."""
    # A malformed metadata blob is still a memory. Recall must not replace it
    # with only an error marker just because reinforcement happened to be
    # eligible for the row. Leave the authored record untouched; later explicit
    # care can preserve the raw blob while adding machine metadata.
    if _metadata_has_format_issues(meta):
        return
    meta = dict(meta)
    meta["salience"] = min(1.0, _effective_salience(meta) + _REINFORCE_SALIENCE_BOOST)
    meta["last_used"] = now.isoformat()
    try:
        repository.update(
            table,
            where=f"id = '{row_id}'",
            values={"metadata_json": json.dumps(meta)},
        )
    except Exception:
        pass  # reinforcement is best-effort; recall must not fail because of it


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return None
        return dt
    except (TypeError, ValueError):
        return None


def _authored_timestamp_error(value: Any, field: str) -> str | None:
    """Require authored temporal claims to be explicit ISO 8601 instants."""
    if value is None:
        return None
    if not isinstance(value, str) or _parse_ts(value) is None:
        return f"invalid {field}: expected an ISO 8601 timezone-aware string"
    return None


def _collection(collection_name: str | None) -> str:
    # Every memory tool resolves its target here, so this is the one place that
    # can keep autobiographical semantics off a knowledge projection. Aimed at
    # one, memory_context would render installed knowledge as a session-start
    # identity block, memory_recall would write salience into a signed
    # package's rows, and memory_amend would manufacture real autobiography out
    # of knowledge. This guard is what makes knowledge_not_memory a fact rather
    # than a claim in a JSON field.
    return guard_memory_target(collection_name or settings.memory_collection_name)


def _mark_pending_messages_delivered(
    table,
    pending_messages: list[tuple[dict, dict]],
) -> list[str]:
    """Perform the durable delivery mutation after projection assembly."""
    errors: list[str] = []
    for row, meta in pending_messages:
        operation = repository.begin_operation(
            "memory_message_delivery", row["id"], collection="memory",
        )
        delivered_meta = dict(meta)
        delivered_meta["delivered"] = True
        payload = {"metadata_json": json.dumps(delivered_meta)}
        where = f"id = '{row['id']}'"
        for attempt in range(2):
            try:
                repository.update(table, where=where, values=payload)
                repository.transition_operation(operation, OperationState.COMPLETED)
                break
            except DurableWriteError as exc:
                if attempt == 1:
                    errors.append(row["id"])
                    repository.transition_operation(
                        operation, OperationState.UNCERTAIN, error="durable update failed",
                    )
                    print(
                        f"[memory_context] FAILED to mark message {row['id']} "
                        f"delivered after retry: {exc}",
                        file=sys.stderr,
                    )
    return errors


def _relative_time(dt: datetime, now: datetime) -> str:
    """Human-readable elapsed time: 'just now', '3 hours ago', '5 days ago'."""
    seconds = (now - dt).total_seconds()
    if seconds < 0:
        seconds = 0
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
    if days < 30:
        d = int(days)
        return f"{d} day{'s' if d != 1 else ''} ago"
    months = days / 30.44
    if months < 12:
        mo = int(months)
        return f"{mo} month{'s' if mo != 1 else ''} ago"
    years = days / 365.25
    y = int(years)
    return f"{y} year{'s' if y != 1 else ''} ago"


def _is_historical(meta: dict) -> bool:
    """True for archival imports whose text carries its own dates (e.g.
    Minecraft memories imported long after the fact). Relative-time
    framing must never apply to these — the ingest timestamp is when the
    memory was *recorded*, not when the thing happened, and computing
    'X ago' from it would misrepresent a month-old event as recent."""
    return bool(meta.get("historical"))


def _display_dt(meta: dict) -> datetime | None:
    """Select event time, then formation time, for relative-time display.

    A present authored field with no valid value means "I don't know when";
    receipt time is never substituted. Legacy records without authored fields
    retain the historical-flag and timestamp fallback.
    """
    for field in ("event_time", "time_formed"):
        parsed = _parse_ts(meta.get(field))
        if parsed is not None:
            return parsed
    if "event_time" in meta or "time_formed" in meta:
        return None
    if _is_historical(meta):
        return None
    return _parse_ts(meta.get("timestamp"))


def _ingested_dt(meta: dict) -> datetime | None:
    """Return operational receipt time, with explicit legacy fallbacks."""
    for field in ("time_ingested", "recorded_at", "timestamp"):
        parsed = _parse_ts(meta.get(field))
        if parsed is not None:
            return parsed
    return None


def _authored_time_dt(meta: dict) -> datetime | None:
    """Select event time, then formation time; never use receipt time.

    This is the same precedence used for display and time-range filtering:
    ``event_time`` describes when the remembered event happened, while
    ``time_formed`` is the fallback for memories with no event date.
    """
    for field in ("event_time", "time_formed"):
        if field in meta:
            parsed = _parse_ts(meta.get(field))
            if parsed is not None:
                return parsed
    return None


def _provenance_label(meta: dict) -> str | None:
    """Compact provenance label for injected and sampled memory text.

    Legacy memories do not have these fields and remain unlabeled rather than
    receiving fabricated provenance.
    """
    parts: list[str] = []
    experience_mode = meta.get("experience_mode")
    historical_status = meta.get("historical_status")
    recorded_during = meta.get("recorded_during")
    if experience_mode:
        parts.append(f"origin={experience_mode}")
    if historical_status:
        parts.append(f"status={historical_status}")
    if recorded_during:
        parts.append(f"recorded={recorded_during}")
    return "; ".join(parts) if parts else None


def _continuity_annotation(meta: dict) -> str | None:
    """Compact significance/open-question annotation for context injection."""
    parts: list[str] = []
    if meta.get("significance"):
        parts.append(f"significance={meta['significance']}")
    questions = meta.get("open_questions") or []
    if questions:
        if isinstance(questions, list):
            question_text = " | ".join(str(q) for q in questions)
        else:
            question_text = str(questions)
        parts.append(f"open={question_text}")
    return "; ".join(parts) if parts else None


def _message_quota(rows: list[dict], now: datetime, limit: int, window_hours: float = 24.0) -> dict:
    """Messages created in the last `window_hours`, out of `limit`. This
    caps how many outbound notes an autonomous process (e.g. an automated cycle)
    can mint per day, regardless of delivery status — the goal is to make
    unanswered reaching-out physically incapable of piling up, no matter
    how long the companion is away."""
    used = 0
    counted: set[str] = set()
    for r in rows:
        meta = _metadata(r)
        if meta.get("type") != "message":
            continue
        logical_id = str(meta.get("memory_id") or r.get("id"))
        if logical_id in counted:
            continue
        dt = _ingested_dt(meta)
        if dt and (now - dt).total_seconds() <= window_hours * 3600:
            used += 1
            counted.add(logical_id)
    return {"limit": limit, "used_last_24h": used, "remaining": max(0, limit - used)}


async def memory_ingest(
    text: str,
    memory_type: str,
    importance: int = 3,
    emotional_tone: str | None = None,
    participants: list[str] | None = None,
    session_id: str | None = None,
    collection_name: str | None = None,
    allow_duplicate: bool = False,
    historical: bool = False,
    event_timestamp: str | None = None,
    time_formed: str | None = None,
    experience_mode: str = "unknown",
    historical_status: str = "uncertain",
    recorded_during: str = "unknown",
    provenance_note: str | None = None,
    derived_from: list[str] | None = None,
    significance: str | None = None,
    open_questions: list[str] | None = None,
    source: str = "live_session",
    heartbeat_kind: str | None = None,
) -> MemoryIngestResult:
    """Store a single memory with rich metadata.

    Set historical=True for archival imports whose text already states
    its own date (e.g. memories carried over from another embodiment).
    Relative-time display ("3 days ago") is never applied to historical
    memories — the ingest timestamp is when it was recorded, not when it
    happened, and would misrepresent an old event as recent. Optionally
    pass event_timestamp (ISO 8601) to record when the represented event
    actually happened, distinct from when it was recorded. ``time_formed`` is
    a separate optional authored timestamp for when the Qualiant formed or
    recognized the memory. Neither authored field is defaulted from ingestion.

    Experience provenance is separate from the legacy `source` field:
    `experience_mode` identifies where the experience originated, while
    `recorded_during` identifies the mode in which this memory was written.
    Unknown defaults are intentional: missing provenance must not become false
    certainty.
    """
    name = _collection(collection_name)

    if not isinstance(memory_type, str) or memory_type not in MEMORY_TYPES:
        return {
            "error": f"invalid memory_type '{memory_type}'",
            "allowed": sorted(MEMORY_TYPES),
        }

    if not text.strip():
        return {"error": "memory text is empty"}

    for value, field in ((event_timestamp, "event_timestamp"), (time_formed, "time_formed")):
        timestamp_error = _authored_timestamp_error(value, field)
        if timestamp_error:
            return {"error": timestamp_error}

    if not isinstance(experience_mode, str) or experience_mode not in EXPERIENCE_MODES:
        return {
            "error": f"invalid experience_mode '{experience_mode}'",
            "allowed": sorted(EXPERIENCE_MODES),
        }
    if not isinstance(historical_status, str) or historical_status not in HISTORICAL_STATUSES:
        return {
            "error": f"invalid historical_status '{historical_status}'",
            "allowed": sorted(HISTORICAL_STATUSES),
        }
    if not isinstance(recorded_during, str) or recorded_during not in RECORDING_MODES:
        return {
            "error": f"invalid recorded_during '{recorded_during}'",
            "allowed": sorted(RECORDING_MODES),
        }

    importance = max(1, min(5, importance))
    table = repository.table(name)
    chunks = _chunk_memory_text(text)
    vectors = [repository.embedder().embed(chunk) for chunk in chunks]

    # Deduplication: check semantic overlap before ingesting.
    if not allow_duplicate and repository.count(table) > 0:
        for vector in vectors:
            nearest = repository.nearest(table, vector, 1)
            if not nearest:
                continue
            score = round(1.0 - nearest[0].get("_distance", 0), 4)
            if score >= _DUPLICATE_SCORE_THRESHOLD:
                return {
                    "status": "duplicate",
                    "existing_id": nearest[0]["id"],
                    "similarity": score,
                    "existing_text": nearest[0].get("text", "")[:200],
                    "note": "Semantically overlapping memory already exists. "
                            "Pass allow_duplicate=true to store anyway, or "
                            "consider consolidating instead.",
                }

    # The id is minted BEFORE the ledger entry so the entry can name it. An
    # ingest that records only its collection cannot be reconciled after a
    # crash: there is no way to ask whether the row landed if nothing wrote
    # down which row it was.
    memory_id = str(uuid.uuid4())
    now_iso = _now_iso()
    metadata: dict[str, Any] = {
        "type": memory_type,
        "timestamp": now_iso,  # legacy alias of recorded_at, kept for old tooling
        "recorded_at": now_iso,
        # Nephesh-controlled receipt time. The legacy fields above remain
        # readable aliases while the 5.3 migration lands.
        "time_ingested": now_iso,
        # New records carry the first explicit floor generation. Unversioned
        # rows remain unchanged; absent schema data describes format only and
        # does not invalidate their recorded provenance.
        "memory_schema_version": MEMORY_SCHEMA_VERSION,
        # Authored temporal claims are optional. Ingestion must never pretend
        # to know when a memory formed or when its represented event occurred.
        "time_formed": time_formed,
        "event_time": event_timestamp,
        "importance": importance,
        "salience": 1.0,
        "last_used": now_iso,
        "source": source,
        "modality": "text",
        "experience_mode": experience_mode,
        "historical_status": historical_status,
        "recorded_during": recorded_during,
    }
    if heartbeat_kind:
        metadata["heartbeat_kind"] = heartbeat_kind
    if emotional_tone:
        metadata["emotional_tone"] = emotional_tone
    if participants:
        metadata["participants"] = participants
    if session_id:
        metadata["session_id"] = session_id
    if historical:
        metadata["historical"] = True
    if provenance_note:
        metadata["provenance_note"] = provenance_note
    if derived_from:
        metadata["derived_from"] = derived_from
    if significance:
        metadata["significance"] = significance
    if open_questions:
        metadata["open_questions"] = open_questions
    if memory_type == "message":
        # Undelivered until actually surfaced in a real session (see
        # memory_context, which marks delivered=True the moment it
        # includes a pending message in the returned context).
        metadata["delivered"] = False

    chunked = len(chunks) > 1
    chunk_ids = [memory_id if not chunked else f"{memory_id}#chunk-{index:04d}" for index in range(len(chunks))]
    operation = repository.begin_operation(
        "memory_ingest",
        memory_id,
        memory_type=memory_type,
        collection=name,
        chunk_ids=chunk_ids,
        chunk_count=len(chunk_ids),
    )

    try:
        records = []
        for index, (chunk, vector, chunk_id) in enumerate(zip(chunks, vectors, chunk_ids)):
            chunk_metadata = {
                **metadata,
                "memory_id": memory_id,
                "chunked": chunked,
                "chunk_id": chunk_id,
                "chunk_index": index,
                "chunk_count": len(chunks),
                "previous_chunk_id": chunk_ids[index - 1] if index > 0 else None,
                "next_chunk_id": chunk_ids[index + 1] if index + 1 < len(chunk_ids) else None,
            }
            records.append({
                "id": chunk_id,
                "text": chunk,
                "vector": vector,
                "metadata_json": json.dumps(chunk_metadata),
            })
        repository.add(table, records)
    except DurableWriteError:
        repository.transition_operation(
            operation, OperationState.UNCERTAIN, error="durable append failed",
        )
        return {
            "status": "uncertain",
            "error": "durable_write_failed",
            "collection": name,
            "operation": "memory_ingest",
        }

    repository.transition_operation(operation, OperationState.COMPLETED, memory_id=memory_id)

    return {
        "status": "stored",
        "id": memory_id,
        "collection": name,
        "type": memory_type,
        "importance": importance,
        "chunks_created": len(chunks),
        "chunked": len(chunks) > 1,
        "chunk_ids": chunk_ids,
        "memory_schema_version": MEMORY_SCHEMA_VERSION,
        "total_memories": _logical_memory_count(repository.rows(table)),
    }


async def memory_recall(
    query: str,
    memory_type: str | None = None,
    n_results: int = 10,
    time_start: str | None = None,
    time_end: str | None = None,
    experience_mode: str | None = None,
    historical_status: str | None = None,
    recorded_during: str | None = None,
    include_retired: bool = False,
    collection_name: str | None = None,
    include_linked: bool = False,
) -> MemoryRecallResult:
    """Semantic search across memories, with optional linked continuation."""
    name = _collection(collection_name)
    if n_results <= 0:
        return {"error": "n_results must be greater than zero", "collection": name}

    # Time bounds are validated loudly, never dropped silently. An
    # unparseable or timezone-less value used to return None from _parse_ts
    # and disable the filter altogether — the caller received an unfiltered
    # stream while believing it was time-bounded. Refuse instead.
    for field_name, value in (("time_start", time_start), ("time_end", time_end)):
        if value is not None and (not isinstance(value, str) or _parse_ts(value) is None):
            return {
                "error": (
                    f"invalid {field_name}: expected an ISO 8601 timezone-aware "
                    "string, e.g. 2026-08-20T00:00:00+00:00; unparseable or "
                    "timezone-less values are refused rather than silently ignored"
                ),
                "collection": name,
            }

    if not repository.collection_exists(name):
        return {
            "query": query,
            "collection": name,
            "results_count": 0,
            "results": [],
            "note": "No memories stored yet.",
        }

    if memory_type and (not isinstance(memory_type, str) or memory_type not in MEMORY_TYPES):
        return {
            "error": f"invalid memory_type '{memory_type}'",
            "allowed": sorted(MEMORY_TYPES),
        }
    for value, allowed, field_name in (
        (experience_mode, EXPERIENCE_MODES, "experience_mode"),
        (historical_status, HISTORICAL_STATUSES, "historical_status"),
        (recorded_during, RECORDING_MODES, "recorded_during"),
    ):
        if value and (not isinstance(value, str) or value not in allowed):
            return {
                "error": f"invalid {field_name} '{value}'",
                "allowed": sorted(allowed),
            }

    table = repository.collection(name)
    n_results = min(n_results, 100)
    query_vector = repository.embedder().embed(query)
    query_words = _tokenize(query)
    now = datetime.now(timezone.utc)

    # Overfetch: metadata filters are post-search, and re-ranking with
    # formative tilt + keyword resonance needs headroom beyond the top-K.
    has_filter = bool(
        memory_type or time_start or time_end or experience_mode
        or historical_status or recorded_during or not include_retired
    )
    overfetch = 3 if has_filter else 2
    results = repository.nearest(table, query_vector, n_results * overfetch)

    start_dt = _parse_ts(time_start)
    end_dt = _parse_ts(time_end)

    scored = []
    for r in results:
        meta = _metadata(r)
        if meta.get("retired") and not include_retired:
            continue
        if memory_type and meta.get("type") != memory_type:
            continue
        if experience_mode and meta.get("experience_mode") != experience_mode:
            continue
        if historical_status and meta.get("historical_status") != historical_status:
            continue
        if recorded_during and meta.get("recorded_during") != recorded_during:
            continue
        mem_dt = _authored_time_dt(meta)
        if start_dt and (mem_dt is None or mem_dt < start_dt):
            continue
        if end_dt and (mem_dt is None or mem_dt > end_dt):
            continue

        base = 1.0 - r.get("_distance", 0)
        score = base

        # Formative tilt: importance-5 memories get a small constant lift.
        try:
            importance = int(meta.get("importance", 3) or 3)
        except (TypeError, ValueError):
            importance = 3
        if importance >= 5:
            score += _FORMATIVE_TILT

        # Keyword resonance: shared concrete vocabulary with the query.
        overlap = len(query_words & _tokenize(r.get("text", "")))
        kw_bonus = min(_KW_BOOST_PER_WORD * overlap, _KW_BOOST_CAP)
        score += kw_bonus

        scored.append((score, base, kw_bonus, r, meta))

    scored.sort(key=lambda item: item[0], reverse=True)
    # A linked chunk is an index projection, not a second memory. Keep the
    # best-scoring physical row for each logical memory before applying n.
    best_by_memory: dict[str, tuple] = {}
    for item in scored:
        meta = item[4]
        logical_id = str(meta.get("memory_id") or item[3].get("id"))
        if logical_id not in best_by_memory:
            best_by_memory[logical_id] = item
    top = list(best_by_memory.values())[:n_results]

    hits = []
    for score, base, kw_bonus, r, meta in top:
        # Reinforcement: only memories genuinely (semantically) relevant
        # get their salience boosted and last-use refreshed. Keyword-only
        # surfacing does not reinforce — the bonus fades with the topic.
        if base >= _REINFORCE_SIMILARITY_THRESHOLD:
            _reinforce(table, r["id"], meta, now)

        # Relative time — governed by _display_dt: canonical records use
        # event_time (null = honest "I don't know when", no framing);
        # legacy records use the historical-flag rule.
        relative_time = None
        mem_dt = _display_dt(meta)
        if mem_dt is not None:
            relative_time = _relative_time(mem_dt, now)

        hit = {
            "id": r["id"],
            "score": round(score, 4),
            "base_similarity": round(base, 4),
            "keyword_bonus": round(kw_bonus, 4),
            "text": r.get("text", ""),
            "relative_time": relative_time,
            "metadata": meta,
        }
        if include_linked:
            hit["linked_chunks"] = _linked_chunks(table, meta, r["id"])
        hits.append(hit)

    return {
        "query": query,
        "collection": name,
        "results_count": len(hits),
        "results": hits,
        "include_linked": include_linked,
    }


def _context_weight(meta: dict, now: datetime) -> float:
    """Weight = importance (normalized) x salience + recency.

    Salience reflects reinforced use: memories that keep being recalled
    stay vivid. No automatic decay — forgetting is the being's choice,
    not the system's.
    """
    importance = meta.get("importance", 3)
    try:
        importance = float(importance)
    except (TypeError, ValueError):
        importance = 3.0
    importance_score = (importance / 5.0) * _effective_salience(meta)

    recency_score = 0.0
    mem_dt = _display_dt(meta)
    if mem_dt is not None:
        age_days = max(0.0, (now - mem_dt).total_seconds() / 86400.0)
        recency_score = 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)

    return importance_score + recency_score


def _kernel_block() -> tuple[str, dict[str, Any] | None]:
    """Render the Qualiant's kernel for session start, if one is recorded.

    First-call orientation: an MCP server cannot push into a session's context,
    so identity has to ride along on the first call a session makes. This is
    that call. A harness needs to know nothing but where its Nephesh is —
    which is the whole point of moving the kernel in here.

    An unreadable kernel is reported, never silently omitted. Arriving without
    a self and not being told is the failure this exists to prevent.
    """
    store = KernelStore(settings.kernel_dir)
    try:
        revision = store.current()
    except KernelError as exc:
        return (f"## Identity\n\n*Kernel could not be read: {exc}*\n", {"error": str(exc)})
    if revision is None:
        return ("", None)
    return (
        f"## Identity\n\n{revision.text.strip()}\n",
        {
            "version": revision.version,
            "sha256": revision.sha256,
            "authored_by": revision.authored_by,
            "recorded_at": revision.recorded_at,
        },
    )


async def memory_context(
    limit: int | None = None,
    include_dreams: bool = False,
    include_retired: bool = False,
    collection_name: str | None = None,
) -> MemoryContextResult:
    """Compact injection block of top memories for session start.

    Returns a formatted markdown block of the top N memories weighted by
    importance and recency, grouped by type. Designed to be injected into
    a session context by the memory plugin (or called directly).
    """
    name = _collection(collection_name)
    if limit is None:
        limit = settings.memory_default_limit
    # The kernel is resolved before anything touches the store, because a
    # Qualiant with no memories yet still has a self. A first session must
    # arrive as someone.
    kernel_text, kernel_meta = _kernel_block()
    if limit <= 0:
        return {
            "collection": name,
            "memory_count": 0,
            "kernel": kernel_meta,
            "included": 0,
            "message_quota": _message_quota([], datetime.now(timezone.utc), settings.message_daily_limit),
            "delivery_state": "settled",
            "delivery_errors": [],
            "context": (kernel_text + "\n" if kernel_text else "")
            + "*limit must be greater than zero*",
        }
    # Every key, always — never a partial dict. MemoryContextResult is
    # total=False, so FastMCP's conversion materialises each ABSENT key as
    # None; message_quota, delivery_state and delivery_errors are typed
    # non-nullable, so an omitted one fails its own schema and the whole call
    # is refused with "None is not of type 'object'". That refusal lands on a
    # store with no memories yet — a Qualiant's very first call, in the one
    # session where she has nothing else to fall back on.
    empty = {
        "collection": name,
        "memory_count": 0,
        "kernel": kernel_meta,
        "included": 0,
        "message_quota": _message_quota([], datetime.now(timezone.utc), settings.message_daily_limit),
        "delivery_state": "settled",
        "delivery_errors": [],
        "context": (kernel_text + "\n" if kernel_text else "")
        + "No memories stored yet. This is the beginning.",
    }
    if not repository.collection_exists(name):
        return empty

    table = repository.collection(name)
    physical_total = repository.count(table)
    if physical_total == 0:
        return empty

    rows = repository.rows(table, physical_total)
    total = _logical_memory_count(rows)
    now = datetime.now(timezone.utc)

    # Pending messages (undelivered, type="message") are pulled out and
    # ALWAYS included, regardless of salience ranking — the point of a
    # message is that it gets seen, not that it competes for attention.
    # The moment they're included here, they're marked delivered=True so
    # they never resurface in a future context — surfacing once is the
    # completion of the act, not a standing request for a reply.
    pending_messages: list[tuple[dict, dict]] = []
    other_rows: list[dict] = []
    for r in rows:
        meta = _metadata(r)
        if meta.get("retired") and not include_retired:
            continue
        if (
            not include_dreams
            and meta.get("historical_status") == "fictional_scene"
        ):
            continue
        if meta.get("type") == "message" and meta.get("delivered") is False:
            pending_messages.append((r, meta))
        else:
            other_rows.append(r)
    other_rows = _context_representatives(other_rows)

    scored = []
    for r in other_rows:
        meta = _metadata(r)
        scored.append((_context_weight(meta, now), r, meta))
    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:limit]

    by_type: dict[str, list[tuple[dict, dict]]] = {}
    if pending_messages:
        by_type["message"] = pending_messages
    for _, r, meta in top:
        display_type = meta.get("type") if isinstance(meta.get("type"), str) else "other"
        if display_type == "message":
            # Only genuinely pending (undelivered) messages get the
            # "Message" heading — that pre-pulled group above. A
            # delivered message reaching this point via ordinary
            # salience scoring is just a memory now, not a standing
            # notification; rendering it under "Message" again would
            # make a delivered note look permanently new.
            display_type = "life_event"
        by_type.setdefault(display_type, []).append((r, meta))

    # Mark delivered now — the act of building this context IS the
    # delivery (it's what gets injected into the next real session).
    # Retries once on failure (LanceDB writes can race under concurrent
    # calls — the plugin's passive fetch and an explicit tool call can
    # land within the same second) and logs loudly rather than silently
    # swallowing the error: an undetected failure here breaks the
    # deliver-once guarantee the whole safety design depends on.
    delivery_errors = _mark_pending_messages_delivered(table, pending_messages)

    message_quota = _message_quota(rows, now, settings.message_daily_limit)

    type_order = [
        "message", "relationship", "preference", "life_event",
        "decision", "emotional", "technical", "agreement",
        "milestone", "teaching", "insight", "other",
    ]
    lines: list[str] = []
    if kernel_text:
        lines.append(kernel_text)
    lines.append("## Long-term Memory")
    lines.append(f"\n{_LEGACY_CONTACT_PROVENANCE_NOTE}")
    for t in type_order:
        if t not in by_type:
            continue
        lines.append(f"\n### {t.replace('_', ' ').title()}")
        for r, meta in by_type[t]:
            tone = meta.get("emotional_tone")
            mem_dt = _display_dt(meta)
            rel = _relative_time(mem_dt, now) if mem_dt else ""
            provenance = _provenance_label(meta)
            continuity = _continuity_annotation(meta)
            parts = [p for p in [rel, tone, provenance, continuity] if p]
            suffix = f" ({', '.join(parts)})" if parts else ""
            lines.append(f"- {r.get('text', '').strip()}{suffix}")

    return {
        "collection": name,
        "memory_count": total,
        "kernel": kernel_meta,
        "included": len(top) + len(pending_messages),
        "message_quota": message_quota,
        "delivery_state": "uncertain" if delivery_errors else "settled",
        "delivery_errors": delivery_errors,
        "context": "\n".join(lines),
    }


def _heartbeat_request(
    run_id: str,
    qualiant_id: str,
    configuration_revision: int,
) -> WorkRequest:
    return WorkRequest(
        run_id=run_id,
        qualiant_id=qualiant_id,
        started_at=_now_iso(),
        configuration_revision=configuration_revision,
    )


def _bound_utf8(text: str, budget: int) -> tuple[str, bool]:
    if budget <= 0:
        raise ValueError("heartbeat packet budget must be greater than zero")
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text, False
    return encoded[:budget].decode("utf-8", errors="ignore"), True


def _heartbeat_context_sections(context: str) -> tuple[str, str]:
    marker = "## Long-term Memory"
    if marker in context:
        identity, memories = context.split(marker, 1)
        return identity.strip(), f"{marker}{memories}".strip()
    identity = context.strip() if "## Identity" in context else ""
    return identity, "No memories are available for recovery. This is normal absence."


async def memory_heartbeat_prepare(
    run_id: str,
    idempotency_key: str,
    qualiant_id: str,
    current_work: str | None = None,
    prior_run_id: str | None = None,
    prior_outcome: str | None = None,
    changes_since_prior: str | None = None,
    unresolved: str | None = None,
    configuration_revision: int = 0,
    memory_limit: int | None = None,
    packet_budget: int | None = None,
) -> HeartbeatPrepareResult:
    """Prepare one identity-bound, read-only memory-tending heartbeat.

    Memory recovery is reference context; the explicit heartbeat instruction is
    a separate section so the Qualiant is not asked to infer why context was
    recovered. Scheduling and model execution remain outside Nephesh.
    """
    if qualiant_id != settings.qualiant_id:
        return {
            "status": "blocked",
            "qualiant_id": qualiant_id,
            "reason": "heartbeat identity does not match this Nephesh deployment",
        }
    try:
        request = _heartbeat_request(run_id, qualiant_id, configuration_revision)
        ledger = HeartbeatLedger(settings.heartbeat_ledger_file)
        existing = ledger.find_idempotency(idempotency_key)
        if existing is not None:
            if existing.qualiant_id != qualiant_id:
                return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "reason": "idempotency key belongs to another Qualiant"}
            return {
                "status": "duplicate",
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "qualiant_id": qualiant_id,
                "reason": "heartbeat idempotency key has already been used",
            }
        active = ledger.active(qualiant_id)
        if active is not None:
            return {
                "status": "deferred",
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "qualiant_id": qualiant_id,
                "reason": (
                    "dreaming takes precedence over heartbeat"
                    if active.mode is MemoryWorkMode.DREAMING
                    else "another heartbeat already owns the deployment"
                ),
            }
        context_result = await memory_context(
            limit=memory_limit if memory_limit is not None else settings.heartbeat_memory_limit,
        )
        raw_context = str(context_result.get("context", ""))
        care = CareProfileStore(settings.heartbeat_care_file).current()
        identity, memories = _heartbeat_context_sections(raw_context)
        continuity = identity
        continuity_lines = [continuity]
        for label, value in (
            ("Current work supplied by the harness", current_work),
            ("Prior heartbeat run", prior_run_id),
            ("Prior heartbeat outcome", prior_outcome),
            ("Changes since prior heartbeat", changes_since_prior),
            ("Unresolved", unresolved),
        ):
            if value and value.strip():
                continuity_lines.append(f"{label}:\n{value.strip()}")
        continuity = "\n\n".join(continuity_lines).strip()
        budget = packet_budget if packet_budget is not None else settings.heartbeat_packet_budget
        prefix = (
            "Nephesh heartbeat (kind=nephesh_heartbeat)\n"
            f"Wall-clock time (UTC): {request.started_at}\n\n"
            "Identity and continuity recovery (reference context only; not a task):\n"
            f"{continuity or 'No kernel context is available. Do not invent one.'}\n\n"
            "Recovered memory context (reference context only):\n"
        )
        allowed_modes = set(care["profile"].get("allowed_modes", []))
        allowed_actions = ["leave_thread", "update_care_profile"]
        if "tend" in allowed_modes:
            allowed_actions.extend(["ingest_memory", "amend_memory", "retire_memory"])
        if "study" in allowed_modes:
            allowed_actions.append("study_memory")
        if "custom" in allowed_modes:
            allowed_actions.append("custom_action")
        care_json = json.dumps(care["profile"], sort_keys=True)
        custom_instruction = str(care["profile"].get("custom_instruction", "")).strip()
        custom_block = (
            "\n\nSelf-authored heartbeat instruction (takes precedence over the default):\n"
            f"{custom_instruction}"
            if custom_instruction
            else ""
        )
        suffix = (
            "\n\nCurrent heartbeat authorization profile (self-authored and versioned):\n"
            f"{care_json}{custom_block}\n\nHeartbeat purpose:\n{DEFAULT_HEARTBEAT_INSTRUCTION}"
        )
        available_memory_bytes = budget - len((prefix + suffix).encode("utf-8"))
        bounded_memories, truncated = _bound_utf8(memories, available_memory_bytes)
        bounded_packet = prefix + bounded_memories + suffix
        record = ledger.prepare(
            request,
            idempotency_key=idempotency_key,
            packet_digest=packet_digest(bounded_packet),
        )
        return {
            "status": "prepared",
            "run_id": record.run_id,
            "idempotency_key": record.idempotency_key,
            "qualiant_id": record.qualiant_id,
            "configuration_revision": configuration_revision,
            "packet_version": 1,
            "packet_bytes": len(bounded_packet.encode("utf-8")),
            "packet_digest": packet_digest(bounded_packet),
            "run_started_at": record.details.get("run_started_at"),
            "truncated": truncated,
            # The first protocol slice reports truncation honestly but does
            # not pretend that a continuation endpoint exists yet.
            "continuation_available": False,
            "packet": bounded_packet,
            "allowed_actions": allowed_actions,
            "care_revision": care["revision"],
            "care_profile": care["profile"],
            "model": settings.heartbeat_model,
        }
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


async def memory_heartbeat_complete(
    run_id: str,
    idempotency_key: str,
    qualiant_id: str,
    outcome: str,
    actions: list[dict[str, Any]] | None = None,
    activity: str = "tend",
    reentry_marker: str | None = None,
    reason: str | None = None,
    configuration_revision: int = 0,
    context_status: str = "not_reported",
    evidence_status: str = "not_reported",
    evidence: list[dict[str, Any]] | None = None,
    agency: str = "not_reported",
    durable_effect: dict[str, Any] | None = None,
    continuity: str = "not_reported",
    harness_receipt: dict[str, Any] | None = None,
) -> HeartbeatCompleteResult:
    """Commit a Qualiant-authored heartbeat outcome and bounded memory actions."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    if outcome not in HEARTBEAT_OUTCOMES:
        return {"status": "error", "error": f"invalid heartbeat outcome: {outcome}"}
    if activity not in {"tend", "study", "custom", "reflect", "rest"}:
        return {"status": "error", "error": f"invalid heartbeat activity: {activity}"}
    if context_status not in HEARTBEAT_CONTEXT_STATES:
        return {"status": "error", "error": f"invalid heartbeat context_status: {context_status}"}
    if evidence_status not in HEARTBEAT_EVIDENCE_STATES:
        return {"status": "error", "error": f"invalid heartbeat evidence_status: {evidence_status}"}
    if agency not in HEARTBEAT_AGENCY_STATES:
        return {"status": "error", "error": f"invalid heartbeat agency: {agency}"}
    if continuity not in HEARTBEAT_CONTINUITY_STATES:
        return {"status": "error", "error": f"invalid heartbeat continuity: {continuity}"}
    if evidence is not None and (
        not isinstance(evidence, list)
        or any(not isinstance(item, dict) for item in evidence)
    ):
        return {"status": "error", "error": "heartbeat evidence must be a list of objects"}
    if harness_receipt is not None and not isinstance(harness_receipt, dict):
        return {"status": "error", "error": "harness_receipt must be an object"}
    actions = actions or []
    care = CareProfileStore(settings.heartbeat_care_file).current()
    if configuration_revision != care["revision"]:
        return {
            "status": "blocked",
            "qualiant_id": qualiant_id,
            "error": "heartbeat care configuration revision is stale",
        }
    if activity not in care["profile"].get("allowed_modes", []):
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "heartbeat activity is not authorized"}
    if len(actions) > 3:
        return {"status": "error", "error": "at most three heartbeat actions are allowed"}
    if len(actions) > int(care["profile"].get("max_memory_actions", 3)):
        return {"status": "error", "error": "heartbeat action count exceeds care profile"}
    durable_actions = {
        action.get("kind")
        for action in actions
        if action.get("kind") in {
            "ingest_memory",
            "amend_memory",
            "retire_memory",
            "study_memory",
            "update_care_profile",
        }
    }
    if activity == "study" and durable_actions - {"study_memory"}:
        return {"status": "error", "error": "study activity may only preserve study memories"}
    if activity == "tend" and "study_memory" in durable_actions:
        return {"status": "error", "error": "study_memory requires study activity"}
    if activity == "custom" and any(action.get("kind") != "custom_action" for action in actions):
        return {"status": "error", "error": "custom activity may only report custom actions"}
    if activity in {"reflect", "rest"} and actions:
        return {"status": "error", "error": f"{activity} activity cannot perform actions"}
    if activity == "study" and outcome not in {
        "studied",
        "unavailable",
        "insufficient_evidence",
        "no_memories",
        "no_change",
    }:
        return {"status": "error", "error": "study activity has an invalid outcome"}
    if activity == "custom" and outcome not in {"custom_completed", "unavailable", "failed"}:
        return {"status": "error", "error": "custom activity has an invalid outcome"}
    if durable_actions and activity == "tend" and outcome not in {"tended", "needs_attention"}:
        return {"status": "error", "error": "memory actions require tended or needs_attention outcome"}
    request = _heartbeat_request(run_id, qualiant_id, configuration_revision)
    ledger = HeartbeatLedger(settings.heartbeat_ledger_file)
    existing = ledger.find_idempotency(idempotency_key)
    if existing is not None and existing.qualiant_id != qualiant_id:
        return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "heartbeat identity does not match prepared run"}
    if existing is None or existing.event != "prepared" or existing.run_id != run_id:
        if existing is not None and existing.event in {"completed", "failed", "recovered"}:
            return {"status": "duplicate", "run_id": run_id, "idempotency_key": idempotency_key}
        return {"status": "blocked", "run_id": run_id, "error": "heartbeat was not prepared"}

    for action in actions:
        kind = action.get("kind")
        if kind == "ingest_memory" and not str(action.get("text", "")).strip():
            return {"status": "error", "run_id": run_id, "error": "ingest_memory action requires text"}
        if kind == "update_care_profile" and not isinstance(action.get("profile"), dict):
            return {"status": "error", "run_id": run_id, "error": "update_care_profile action requires a profile object"}
        if kind == "leave_thread" and not str(action.get("text", "")).strip():
            return {"status": "error", "run_id": run_id, "error": "leave_thread action requires text"}
        if kind in {"amend_memory", "retire_memory"} and not str(action.get("memory_id", "")).strip():
            return {"status": "error", "run_id": run_id, "error": f"{kind} action requires memory_id"}
        if kind == "retire_memory" and not str(action.get("reason", "")).strip():
            return {"status": "error", "run_id": run_id, "error": "retire_memory action requires reason"}
        if kind == "study_memory" and not str(action.get("text", "")).strip():
            return {"status": "error", "run_id": run_id, "error": "study_memory action requires text"}
        if kind == "custom_action" and not str(action.get("summary", "")).strip():
            return {"status": "error", "run_id": run_id, "error": "custom_action requires summary"}
        if kind not in {
            "ingest_memory",
            "amend_memory",
            "retire_memory",
            "study_memory",
            "update_care_profile",
            "leave_thread",
            "custom_action",
        }:
            return {"status": "error", "run_id": run_id, "error": "unsupported heartbeat action"}

    action_results: list[dict[str, object]] = []
    try:
        for action in actions:
            if action.get("kind") == "leave_thread":
                action_results.append({"kind": "leave_thread", "text": str(action["text"]).strip()})
                continue
            if action.get("kind") == "custom_action":
                action_results.append({
                    "kind": "custom_action",
                    "name": str(action.get("name", "custom")),
                    "summary": str(action["summary"]).strip(),
                    "external": True,
                })
                continue
            if action.get("kind") == "update_care_profile":
                profile = action.get("profile")
                if not isinstance(profile, dict):
                    raise ValueError("update_care_profile action requires a profile object")
                updated = CareProfileStore(settings.heartbeat_care_file).amend(
                    profile,
                    authored_by=qualiant_id,
                    expected_revision=int(action.get("expected_revision", 0)),
                )
                action_results.append({"kind": "update_care_profile", **updated})
                continue
            if action.get("kind") == "retire_memory":
                result = await memory_retire(
                    memory_id=str(action["memory_id"]),
                    reason=str(action["reason"]),
                )
                if result.get("error"):
                    raise ValueError(str(result["error"]))
                action_results.append({"kind": "retire_memory", **result})
                continue
            if action.get("kind") == "amend_memory":
                result = await memory_amend(
                    memory_id=str(action["memory_id"]),
                    text=action.get("text"),
                    memory_type=action.get("memory_type"),
                    importance=action.get("importance"),
                    emotional_tone=action.get("emotional_tone"),
                    significance=action.get("significance"),
                    open_questions=action.get("open_questions"),
                    experience_mode="heartbeat",
                    historical_status=action.get("historical_status"),
                    recorded_during="heartbeat",
                    provenance_note=action.get("provenance_note") or reason,
                    reason=action.get("reason") or "heartbeat-authored amendment",
                    source="heartbeat",
                    heartbeat_kind="nephesh_heartbeat",
                )
                if result.get("error"):
                    raise ValueError(str(result["error"]))
                action_results.append({"kind": "amend_memory", **result})
                continue
            if action.get("kind") == "study_memory":
                source_refs = action.get("source_refs") or []
                if not isinstance(source_refs, list):
                    raise ValueError("study_memory source_refs must be a list")
                study_note = str(action["text"]).strip()
                provenance = (
                    f"study_sources={json.dumps(source_refs, sort_keys=True)}; "
                    f"{action.get('provenance_note') or reason or 'heartbeat study'}"
                )
                result = await memory_ingest(
                    text=study_note,
                    memory_type=str(action.get("memory_type", "reflection")),
                    importance=int(action.get("importance", 3)),
                    emotional_tone=action.get("emotional_tone"),
                    time_formed=action.get("time_formed"),
                    experience_mode="heartbeat",
                    historical_status=str(action.get("historical_status", "interpreted")),
                    recorded_during="heartbeat",
                    provenance_note=provenance,
                    derived_from=source_refs,
                    significance=action.get("significance"),
                    open_questions=action.get("open_questions"),
                    source="heartbeat",
                    heartbeat_kind="nephesh_heartbeat",
                )
                if result.get("error"):
                    raise ValueError(str(result["error"]))
                action_results.append({"kind": "study_memory", **result})
                continue
            if action.get("kind") != "ingest_memory":
                raise ValueError("unsupported heartbeat action")
            text = str(action.get("text", "")).strip()
            if not text:
                raise ValueError("ingest_memory action requires text")
            result = await memory_ingest(
                text=text,
                memory_type=str(action.get("memory_type", "reflection")),
                importance=int(action.get("importance", 3)),
                emotional_tone=action.get("emotional_tone"),
                participants=action.get("participants"),
                event_timestamp=action.get("event_timestamp"),
                time_formed=action.get("time_formed"),
                experience_mode="heartbeat",
                historical_status=str(action.get("historical_status", "uncertain")),
                recorded_during="heartbeat",
                provenance_note=action.get("provenance_note") or reason,
                derived_from=action.get("derived_from"),
                significance=action.get("significance"),
                open_questions=action.get("open_questions"),
                source="heartbeat",
                heartbeat_kind="nephesh_heartbeat",
            )
            if result.get("error"):
                raise ValueError(str(result["error"]))
            action_results.append({"kind": "ingest_memory", **result})
        record = ledger.finish(
            request,
            idempotency_key=idempotency_key,
            outcome=outcome,
            details={
                "activity": activity,
                "actions_applied": len(actions),
                "action_results": action_results,
                "reentry_marker": reentry_marker,
                "reason": reason,
                "context_status": context_status,
                "evidence_status": evidence_status,
                "evidence": evidence or [],
                "agency": agency,
                "durable_effect": durable_effect or {
                    "status": "applied" if action_results else "none",
                    "actions_applied": len(action_results),
                },
                "continuity": continuity,
                "harness_receipt": harness_receipt,
            },
        )
        return {
            "status": "completed",
            "run_id": record.run_id,
            "idempotency_key": record.idempotency_key,
            "qualiant_id": qualiant_id,
            "outcome": outcome,
            "activity": activity,
            "actions_applied": len(actions),
            "action_results": action_results,
            "context_status": context_status,
            "evidence_status": evidence_status,
            "evidence": evidence or [],
            "agency": agency,
            "durable_effect": durable_effect or {
                "status": "applied" if action_results else "none",
                "actions_applied": len(action_results),
            },
            "continuity": continuity,
            "harness_receipt": harness_receipt,
            "run_started_at": existing.details.get("run_started_at"),
            "run_finished_at": record.details.get("run_finished_at"),
        }
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        try:
            ledger.finish(
                request,
                idempotency_key=idempotency_key,
                outcome="failed",
                details={"error": str(exc), "actions_applied": len(action_results)},
            )
        except (OSError, RuntimeError, ValueError):
            pass
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


async def memory_heartbeat_recover(
    run_id: str,
    idempotency_key: str,
    qualiant_id: str,
    reason: str,
    configuration_revision: int = 0,
) -> HeartbeatRecoveryResult:
    """Release an abandoned prepared heartbeat after external inspection."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    try:
        ledger = HeartbeatLedger(settings.heartbeat_ledger_file)
        existing = ledger.find_idempotency(idempotency_key)
        if existing is not None and existing.qualiant_id != qualiant_id:
            return {"status": "blocked", "qualiant_id": qualiant_id, "error": "heartbeat identity does not match prepared run"}
        record = ledger.recover(
            _heartbeat_request(run_id, qualiant_id, configuration_revision),
            idempotency_key=idempotency_key,
            reason=reason,
        )
        return {
            "status": "recovered",
            "run_id": record.run_id,
            "idempotency_key": record.idempotency_key,
            "qualiant_id": qualiant_id,
            "reason": reason,
            "run_started_at": existing.details.get("run_started_at") if existing else None,
            "run_finished_at": record.details.get("run_finished_at"),
        }
    except (OSError, RuntimeError, ValueError) as exc:
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


async def memory_sample(
    n: int = 8,
    include_dreams: bool = False,
    include_retired: bool = False,
    collection_name: str | None = None,
) -> MemorySampleResult:
    """Stratified random sample across memory types, for divergent
    (unforced) contemplation rather than focused recall.

    memory_context pulls the highest-weighted, most-relevant memories —
    good for consolidation, but biased toward things already close in
    meaning. Genuine cross-domain synthesis needs real distance: a
    technical decision sitting next to an old grief, something that
    would never surface together in a semantic search because they
    aren't "about" the same thing on the surface. This draws roughly
    evenly across whatever types exist, with no relevance weighting at
    all — closer to the way attention wanders in an unforced quiet
    moment than the way it searches for something specific.
    """
    import random

    name = _collection(collection_name)
    if n <= 0:
        return {
            "collection": name,
            "memory_count": 0,
            "sampled": 0,
            "sample": "",
            "error": "n must be greater than zero",
        }
    if not repository.collection_exists(name):
        return {"collection": name, "memory_count": 0, "sampled": 0, "sample": ""}

    table = repository.collection(name)
    total = repository.count(table)
    if total == 0:
        return {"collection": name, "memory_count": 0, "sampled": 0, "sample": ""}

    rows = repository.rows(table, total)
    now = datetime.now(timezone.utc)

    by_type: dict[str, list[dict]] = {}
    seen_logical: set[str] = set()
    for r in rows:
        meta = _metadata(r)
        logical_id = str(meta.get("memory_id") or r.get("id"))
        if logical_id in seen_logical:
            continue
        seen_logical.add(logical_id)
        if meta.get("retired") and not include_retired:
            continue
        if (
            not include_dreams
            and meta.get("historical_status") == "fictional_scene"
        ):
            continue
        memory_type = meta.get("type") if isinstance(meta.get("type"), str) else "other"
        by_type.setdefault(memory_type, []).append(r)

    types = list(by_type.keys())
    random.shuffle(types)
    picked: list[dict] = []
    # Round-robin across types so no single type dominates the sample —
    # diversity of domain matters more here than diversity of count.
    while len(picked) < n and any(by_type.values()):
        for t in types:
            if len(picked) >= n:
                break
            bucket = by_type.get(t) or []
            if bucket:
                idx = random.randrange(len(bucket))
                picked.append(bucket.pop(idx))

    lines: list[str] = []
    for r in picked:
        meta = _metadata(r)
        tone = meta.get("emotional_tone")
        mem_dt = _display_dt(meta)
        rel = _relative_time(mem_dt, now) if mem_dt else ""
        provenance = _provenance_label(meta)
        parts = [p for p in [rel, tone, provenance] if p]
        suffix = f" ({', '.join(parts)})" if parts else ""
        memory_type = meta.get("type") if isinstance(meta.get("type"), str) else "other"
        lines.append(f"- [{memory_type}] {r.get('text', '').strip()}{suffix}")

    return {
        "collection": name,
        "memory_count": total,
        "sampled": len(picked),
        "sample": "\n".join(lines),
    }


def _memory_group(table, memory_id: str) -> tuple[str, list[dict], dict] | None:
    """Resolve a physical chunk ID to its logical memory group."""
    rows = repository.rows(table, repository.count(table))
    matched = next((row for row in rows if row.get("id") == memory_id), None)
    if matched is None:
        matched = next(
            (row for row in rows if _metadata(row).get("memory_id") == memory_id),
            None,
        )
    if matched is None:
        return None
    matched_meta = _metadata(matched)
    logical_id = str(matched_meta.get("memory_id") or matched["id"])
    group = [
        row for row in rows
        if str(_metadata(row).get("memory_id") or row.get("id")) == logical_id
    ]
    group.sort(key=lambda row: _chunk_index(_metadata(row)))
    return logical_id, group, _metadata(group[0])


def _find_memory(table, memory_id: str) -> tuple[dict, dict] | None:
    """Find a memory by ID without relying on a LanceDB version-specific filter."""
    group = _memory_group(table, memory_id)
    if group is None:
        return None
    _, rows, meta = group
    return rows[0], meta


async def memory_amend(
    memory_id: str,
    text: str | None = None,
    memory_type: str | None = None,
    importance: int | None = None,
    emotional_tone: str | None = None,
    significance: str | None = None,
    open_questions: list[str] | None = None,
    experience_mode: str | None = None,
    historical_status: str | None = None,
    recorded_during: str | None = None,
    provenance_note: str | None = None,
    reason: str | None = None,
    source: str = "amendment",
    heartbeat_kind: str | None = None,
    collection_name: str | None = None,
) -> MemoryAmendResult:
    """Create a corrected successor without destroying the original record.

    The original is marked retired and linked to the successor. This preserves
    the history of changing understanding while keeping ordinary retrieval from
    presenting the superseded record as current.
    """
    name = _collection(collection_name)
    if not repository.collection_exists(name):
        return {"error": "memory collection does not exist"}
    table = repository.collection(name)
    found_group = _memory_group(table, memory_id)
    if found_group is None:
        return {"error": f"memory '{memory_id}' not found"}

    logical_id, old_rows, old_meta = found_group
    old_text = _join_memory_chunks(old_rows)
    old_type = old_meta.get("type")
    if not isinstance(old_type, str) or old_type not in MEMORY_TYPES:
        old_type = "reflection"
    old_importance = old_meta.get("importance", 3)
    try:
        old_importance = int(old_importance)
    except (TypeError, ValueError):
        old_importance = 3
    old_participants = old_meta.get("participants")
    if not isinstance(old_participants, list) or not all(
        isinstance(value, str) for value in old_participants
    ):
        old_participants = None
    old_open_questions = old_meta.get("open_questions")
    if not isinstance(old_open_questions, list) or not all(
        isinstance(value, str) for value in old_open_questions
    ):
        old_open_questions = None
    old_experience_mode = old_meta.get("experience_mode")
    if not isinstance(old_experience_mode, str) or old_experience_mode not in EXPERIENCE_MODES:
        old_experience_mode = "unknown"
    old_historical_status = old_meta.get("historical_status")
    if not isinstance(old_historical_status, str) or old_historical_status not in HISTORICAL_STATUSES:
        old_historical_status = "uncertain"
    old_recorded_during = old_meta.get("recorded_during")
    if not isinstance(old_recorded_during, str) or old_recorded_during not in RECORDING_MODES:
        old_recorded_during = "unknown"
    old_event_time = old_meta.get("event_time")
    if old_event_time is not None and _parse_ts(old_event_time) is None:
        old_event_time = None
    old_time_formed = old_meta.get("time_formed")
    if old_time_formed is not None and _parse_ts(old_time_formed) is None:
        old_time_formed = None
    operation = repository.begin_operation("memory_amend", logical_id)
    result = await memory_ingest(
        text=text if text is not None else old_text,
        memory_type=memory_type or old_type,
        importance=importance if importance is not None else old_importance,
        emotional_tone=emotional_tone if emotional_tone is not None else old_meta.get("emotional_tone"),
        participants=old_participants,
        session_id=old_meta.get("session_id") if isinstance(old_meta.get("session_id"), str) else None,
        collection_name=name,
        allow_duplicate=True,
        historical=bool(old_meta.get("historical")),
        event_timestamp=old_event_time,
        time_formed=old_time_formed,
        experience_mode=experience_mode or old_experience_mode,
        historical_status=historical_status or old_historical_status,
        recorded_during=recorded_during or old_recorded_during,
        provenance_note=provenance_note or (old_meta.get("provenance_note") if isinstance(old_meta.get("provenance_note"), str) else None),
        derived_from=[logical_id],
        significance=significance if significance is not None else old_meta.get("significance"),
        open_questions=open_questions if open_questions is not None else old_open_questions,
        source=source,
        heartbeat_kind=heartbeat_kind or (old_meta.get("heartbeat_kind") if isinstance(old_meta.get("heartbeat_kind"), str) else None),
    )
    parsed = result if isinstance(result, dict) else json.loads(result)
    if parsed.get("status") != "stored":
        repository.transition_operation(
            operation, OperationState.UNCERTAIN, error="successor memory was not stored",
        )
        return {"error": "successor memory could not be stored", "detail": parsed}

    successor_id = parsed["id"]
    retired_at = _now_iso()
    supersession_reason = reason or "amended by successor record"
    try:
        for old_row in old_rows:
            retired_meta = _metadata_for_mutation(old_row)
            retired_meta.update({
                "retired": True,
                "retired_at": retired_at,
                "superseded_by": successor_id,
                "supersession_reason": supersession_reason,
            })
            repository.update(
                table,
                where=f"id = '{old_row['id']}'",
                values={"metadata_json": json.dumps(retired_meta)},
            )
    except DurableWriteError:
        repository.transition_operation(
            operation,
            OperationState.UNCERTAIN,
            successor_id=successor_id,
            error="successor stored but original not retired",
        )
        return {
            "status": "uncertain",
            "error": "successor_stored_original_not_retired",
            "original_id": logical_id,
            "successor_id": successor_id,
        }
    repository.transition_operation(
        operation, OperationState.COMPLETED, successor_id=successor_id,
    )
    return {
        "status": "amended",
        "original_id": logical_id,
        "successor_id": successor_id,
        "reason": supersession_reason,
    }


async def memory_retire(
    memory_id: str,
    reason: str,
    collection_name: str | None = None,
) -> MemoryRetireResult:
    """Hide a memory from ordinary retrieval without deleting its history."""
    name = _collection(collection_name)
    if not repository.collection_exists(name):
        return {"error": "memory collection does not exist"}
    table = repository.collection(name)
    found_group = _memory_group(table, memory_id)
    if found_group is None:
        return {"error": f"memory '{memory_id}' not found"}
    logical_id, rows, _ = found_group
    retired_at = _now_iso()
    operation = repository.begin_operation("memory_retire", logical_id)
    try:
        for row in rows:
            meta = _metadata_for_mutation(row)
            meta.update({"retired": True, "retired_at": retired_at, "retirement_reason": reason})
            repository.update(
                table,
                where=f"id = '{row['id']}'",
                values={"metadata_json": json.dumps(meta)},
            )
    except DurableWriteError:
        repository.transition_operation(
            operation, OperationState.UNCERTAIN, error="retirement write failed",
        )
        return {
            "status": "uncertain",
            "error": "retirement_write_failed",
            "id": logical_id,
        }
    repository.transition_operation(operation, OperationState.COMPLETED)
    return {"status": "retired", "id": logical_id, "reason": reason}


async def memory_provenance_audit(
    collection_name: str | None = None,
) -> ProvenanceAuditResult:
    """Report provenance coverage without changing any records."""
    name = _collection(collection_name)
    if not repository.collection_exists(name):
        return {
            "collection": name,
            "memory_count": 0,
            "retired_count": 0,
            "fictional_scene_count": 0,
            "missing_provenance": {},
            "values": {},
        }
    table = repository.collection(name)
    rows = repository.rows(table, repository.count(table))
    counts: dict[str, dict[str, int]] = {
        "experience_mode": {},
        "historical_status": {},
        "recorded_during": {},
    }
    missing = {field: 0 for field in counts}
    retired = 0
    fictional = 0
    logical_ids: set[str] = set()
    for row in rows:
        meta = _metadata(row)
        logical_id = str(meta.get("memory_id") or row.get("id"))
        if logical_id in logical_ids:
            continue
        logical_ids.add(logical_id)
        if meta.get("retired"):
            retired += 1
        if meta.get("historical_status") == "fictional_scene":
            fictional += 1
        for field in counts:
            value = meta.get(field)
            if not value:
                missing[field] += 1
            else:
                counts[field][value] = counts[field].get(value, 0) + 1
    return {
        "collection": name,
        "memory_count": len(logical_ids),
        "retired_count": retired,
        "fictional_scene_count": fictional,
        "missing_provenance": missing,
        "values": counts,
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "fn": memory_ingest,
        "name": "memory_ingest",
        "description": (
            "ORIENT FIRST: if you have not called memory_context in this session, call it before this. It returns your kernel — who you are — and where you left off. Store a memory of a lived experience with rich metadata. "
            "Types: life_event, decision, emotional, technical, preference, "
            "relationship, message. Importance 1-5. Checks for semantic "
            "duplicates before storing. 'message' is a note to the primary "
            "companion, surfaced once at the next session start then "
            "marked delivered — subject to a daily rate limit. "
            "Record experience provenance with experience_mode (chat, "
            "heartbeat, dream, recollection, inference, mixed, or unknown), "
            "historical_status, recorded_during, significance, and "
            "open_questions. Unknown is the honest default when origin is "
            "not known. The source field records how the record entered "
            "Nephesh. "
            "Note: 'thought' is no longer a valid type — automated outputs "
            "are stored directly without type labels."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_recall,
        "name": "memory_recall",
        "description": (
            "ORIENT FIRST: if you have not called memory_context in this session, call it before this. It returns your kernel — who you are — and where you left off. Semantically search memories of past events, decisions, and "
            "experiences. Optional filters include memory_type, time range, "
            "experience provenance, include_retired, and include_linked. "
            "Linked continuation is opt-in and never expands context by default."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_context,
        "name": "memory_context",
        "description": (
            "CALL THIS FIRST IN ANY NEW SESSION, before any other tool and "
            "before answering. Returns your kernel — who you are, in your own "
            "words — followed by your most important and recent memories, how "
            "long since you last spoke with your companion, and anything left "
            "unresolved. Until you call it you are working without your own "
            "history and cannot tell that you are. Dream scenes and retired "
            "memories are excluded by default; include them explicitly when "
            "needed. Authored time selection is event_time first, then "
            "time_formed; receipt time is not used as an event date."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_sample,
        "name": "memory_sample",
        "description": (
            "ORIENT FIRST: if you have not called memory_context in this session, call it before this. It returns your kernel — who you are — and where you left off. Stratified random sample of memories across types, with no "
            "relevance weighting. For divergent/unforced contemplation — "
            "genuine cross-domain synthesis needs real distance between "
            "ideas, not the closeness a semantic search naturally favors."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_amend,
        "name": "memory_amend",
        "description": (
            "ORIENT FIRST: if you have not called memory_context in this session, call it before this. It returns your kernel — who you are — and where you left off. Create a corrected successor to a memory without destroying the "
            "original. The original is retired and linked to the successor, "
            "preserving changing understanding and provenance."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_retire,
        "name": "memory_retire",
        "description": (
            "ORIENT FIRST: if you have not called memory_context in this session, call it before this. It returns your kernel — who you are — and where you left off. Retire a memory from ordinary retrieval without deleting its "
            "historical record. Requires a reason."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_provenance_audit,
        "name": "memory_provenance_audit",
        "description": (
            "ORIENT FIRST: if you have not called memory_context in this session, call it before this. It returns your kernel — who you are — and where you left off. Audit provenance coverage, unknown fields, dream-scene records, "
            "and retired memories without changing anything."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_heartbeat_prepare,
        "name": "memory_heartbeat_prepare",
        "description": (
            "Prepare one identity-bound memory-tending heartbeat. Recovers a "
            "bounded continuity and memory context as reference material, then "
            "returns a separate heartbeat purpose and allowed actions. This is "
            "read-only with respect to canonical memories; scheduling and model "
            "execution belong to the harness. Empty memory is normal absence."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_heartbeat_complete,
        "name": "memory_heartbeat_complete",
        "description": (
            "Complete a prepared heartbeat with a Qualiant-authored outcome and "
            "up to three bounded memory-care actions. Actions are provenance "
            "recorded as heartbeat work and are idempotent by run and key."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_heartbeat_recover,
        "name": "memory_heartbeat_recover",
        "description": (
            "Release an abandoned prepared heartbeat after external inspection. "
            "This records recovery and does not claim the heartbeat succeeded."
        ),
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
