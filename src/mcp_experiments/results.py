"""Typed result contracts for the Nephesh MCP boundary."""

from __future__ import annotations

from typing import Literal, TypedDict


class ErrorResult(TypedDict, total=False):
    status: Literal["error", "uncertain"] | None
    error: str | None
    operation: str | None
    details: dict[str, object] | None


class HealthResult(TypedDict):
    status: Literal["ok"]
    mode: str
    tls: bool
    tools_available: list[str]


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
    guidance: dict[str, object] | None
    guidance_error: str | None


class MemoryAmendResult(TypedDict, total=False):
    status: str | None
    original_id: str | None
    successor_id: str | None
    reason: str | None
    error: str | None
    detail: dict[str, object] | None
    guidance: dict[str, object] | None
    guidance_error: str | None


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
    last_contact_with_companion: dict[str, object] | None
    message_quota: dict[str, object] | None
    delivery_state: str | None
    delivery_errors: list[str] | None
    guidance: dict[str, object] | None
    guidance_error: str | None
    context: str | None


class GuidancePublic(TypedDict, total=False):
    guidance_id: str
    kind: str
    trigger: str
    text: str
    state: str
    created_at: str
    expires_at: str
    operation_id: str | None
    explicit: bool
    projection_available: bool | None


class GuidanceRequestResult(TypedDict, total=False):
    status: str | None
    guidance: GuidancePublic | None
    error: str | None
    allowed: list[str] | None


class GuidanceAcknowledgeResult(TypedDict, total=False):
    status: str | None
    guidance: GuidancePublic | None
    error: str | None


class MemorySampleResult(TypedDict, total=False):
    collection: str
    memory_count: int
    sampled: int
    sample: str
    error: str | None


class ProvenanceAuditResult(TypedDict):
    collection: str
    memory_count: int
    retired_count: int
    fictional_scene_count: int
    missing_provenance: dict[str, int]
    values: dict[str, dict[str, int]]
