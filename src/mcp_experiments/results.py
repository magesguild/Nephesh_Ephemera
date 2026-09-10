"""Typed result contracts for the Nephesh MCP boundary."""

from __future__ import annotations

from typing import Literal, TypedDict


class ErrorResult(TypedDict, total=False):
    status: Literal["error", "uncertain"] | None
    error: str | None
    operation: str | None
    details: dict[str, object] | None


class FloorCheck(TypedDict, total=False):
    status: Literal["value", "unavailable", "unset", "failed", "uncertain"]
    value: object
    reason: str
    source: str


class TruthfulFloor(TypedDict):
    version: str
    checks: dict[str, FloorCheck]


class HealthResult(TypedDict):
    status: Literal["ok", "degraded", "unavailable", "failed"]
    mode: str
    tls: bool
    tools_available: list[str]
    floor: TruthfulFloor


class SystemTimeResult(TypedDict):
    utc: str
    unix_seconds: float
    timezone: str
    source: str


class ScheduleTerminalResult(TypedDict, total=False):
    status: str | None
    operation_id: str | None
    recorded_at: str | None
    reason: str | None
    details: dict[str, object] | None
    error: str | None


class ScheduleInspectionResult(TypedDict, total=False):
    status: str | None
    claims: list[dict[str, object]] | None
    stale_claims: list[dict[str, object]] | None
    error: str | None


class CollectionListResult(TypedDict):
    collections: list[dict[str, object]]


class CollectionInfoResult(TypedDict, total=False):
    name: str | None
    document_count: int | None
    sample_documents: list[dict[str, object]] | None
    error: str | None


class SearchResult(TypedDict, total=False):
    query: str | None
    collection: str | None
    results_count: int | None
    results: list[dict[str, object]] | None
    error: str | None


class DeleteResult(TypedDict, total=False):
    deleted: bool | None
    collection: str | None
    ids_removed: int | None
    remaining: int | None
    error: str | None


class StressTestResult(TypedDict, total=False):
    collection: str | None
    documents_ingested: int | None
    ingest_time_seconds: float | None
    ingest_throughput_docs_per_sec: float | None
    search_benchmark: dict[str, object] | None
    note: str | None
    error: str | None


class IngestResult(TypedDict, total=False):
    collection: str | None
    documents_ingested: int | None
    chunks_created: int | None
    total_in_collection: int | None
    ingested: int | None
    error: str | None


class MemoryRecallResult(TypedDict, total=False):
    query: str | None
    collection: str | None
    results_count: int | None
    results: list[dict[str, object]] | None
    note: str | None
    error: str | None
    allowed: list[str] | None
    include_linked: bool | None


class MemoryIngestResult(TypedDict, total=False):
    status: str | None
    id: str | None
    collection: str | None
    type: str | None
    importance: int | None
    total_memories: int | None
    existing_id: str | None
    similarity: float | None
    existing_text: str | None
    note: str | None
    error: str | None
    operation: str | None
    allowed: list[str] | None
    chunks_created: int | None
    chunked: bool | None
    chunk_ids: list[str] | None
    memory_schema_version: int | None


class MemoryAmendResult(TypedDict, total=False):
    status: str | None
    original_id: str | None
    successor_id: str | None
    reason: str | None
    error: str | None
    detail: dict[str, object] | None


class MemoryRetireResult(TypedDict, total=False):
    status: str | None
    id: str | None
    reason: str | None
    error: str | None


class MemoryContextResult(TypedDict, total=False):
    collection: str | None
    memory_count: int | None
    # Which kernel revision this context was assembled with, or None when the
    # deployment has no kernel recorded yet. A caller can tell whether identity
    # was included rather than having to infer it from the prose.
    kernel: dict[str, object] | None
    included: int | None
    message_quota: dict[str, object] | None
    delivery_state: str | None
    delivery_errors: list[str] | None
    context: str | None


class MemorySampleResult(TypedDict, total=False):
    collection: str
    memory_count: int
    sampled: int
    sample: str
    error: str | None


class HeartbeatPrepareResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    idempotency_key: str | None
    qualiant_id: str | None
    configuration_revision: int | None
    packet_version: int | None
    packet_bytes: int | None
    packet_digest: str | None
    packet: str | None
    truncated: bool | None
    continuation_available: bool | None
    identity_and_continuity: str | None
    recovered_memory_context: str | None
    heartbeat_instruction: str | None
    allowed_actions: list[str] | None
    care_revision: int | None
    care_profile: dict[str, object] | None
    model: str | None
    run_started_at: str | None
    reason: str | None
    error: str | None


class HeartbeatCompleteResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    idempotency_key: str | None
    qualiant_id: str | None
    outcome: str | None
    activity: str | None
    actions_applied: int | None
    action_results: list[dict[str, object]] | None
    context_status: str | None
    evidence_status: str | None
    evidence: list[dict[str, object]] | None
    agency: str | None
    durable_effect: dict[str, object] | None
    continuity: str | None
    harness_receipt: dict[str, object] | None
    run_started_at: str | None
    run_finished_at: str | None
    error: str | None


class HeartbeatRecoveryResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    idempotency_key: str | None
    qualiant_id: str | None
    reason: str | None
    run_started_at: str | None
    run_finished_at: str | None
    error: str | None


class DreamPrepareResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    idempotency_key: str | None
    qualiant_id: str | None
    dream_kind: str | None
    wall_clock_utc: str | None
    packet_version: int | None
    packet_bytes: int | None
    packet_digest: str | None
    packet: str | None
    phase: str | None
    source_count: int | None
    model: str | None
    duration_seconds: int | None
    deadline_utc: str | None
    expires_at: str | None
    configuration_revision: int | None
    error: str | None


class DreamInvokeResult(TypedDict, total=False):
    status: str | None
    invocation: str | None
    run_id: str | None
    idempotency_key: str | None
    qualiant_id: str | None
    dream_kind: str | None
    duration_seconds: int | None
    deadline_utc: str | None
    expires_at: str | None
    handoff: str | None
    packet: str | None
    packet_digest: str | None
    source_count: int | None
    request: dict[str, object] | None
    error: str | None


class DreamPhaseResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    idempotency_key: str | None
    qualiant_id: str | None
    phase: str | None
    artifact_id: str | None
    artifact_status: str | None
    grounding_status: str | None
    artifact_ids: list[str] | None
    promotion_status: str | None
    error: str | None


class DreamPhasePrepareResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    idempotency_key: str | None
    qualiant_id: str | None
    phase: str | None
    packet_version: int | None
    packet_bytes: int | None
    packet_digest: str | None
    packet: str | None
    error: str | None


class DreamDiaryResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    diary_id: str | None
    qualiant_id: str | None
    visibility: str | None
    experience_mode: str | None
    historical_status: str | None
    generation_status: str | None
    error: str | None


class DreamGroundResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    artifact_id: str | None
    qualiant_id: str | None
    decision: str | None
    memory_id: str | None
    grounding_status: str | None
    operation_id: str | None
    error: str | None


class DreamReleaseResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    idempotency_key: str | None
    qualiant_id: str | None
    release_reason: str | None
    release_outcome: str | None
    artifact_ids: list[str] | None
    grounding_status: str | None
    promotion_status: str | None
    error: str | None


class DreamRecallResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    qualiant_id: str | None
    query: str | None
    memory_results: list[dict[str, object]] | None
    dream_artifacts: list[dict[str, object]] | None
    results_count: int | None
    error: str | None


class DreamStatusResult(TypedDict, total=False):
    status: str | None
    run_id: str | None
    qualiant_id: str | None
    phase: str | None
    terminal_event: str | None
    terminal_outcome: str | None
    artifact_ids: list[str] | None
    error: str | None


class ProvenanceAuditResult(TypedDict):
    collection: str
    memory_count: int
    retired_count: int
    fictional_scene_count: int
    missing_provenance: dict[str, int]
    values: dict[str, dict[str, int]]
