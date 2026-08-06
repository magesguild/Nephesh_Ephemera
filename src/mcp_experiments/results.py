"""Typed result contracts for the Nephesh MCP boundary."""

from __future__ import annotations

from typing import Literal, TypedDict


class ErrorResult(TypedDict, total=False):
    status: Literal["error", "uncertain"]
    error: str
    operation: str
    details: dict[str, object]


class HealthResult(TypedDict):
    status: Literal["ok"]
    mode: str
    tls: bool
    tools_available: list[str]


class CollectionListResult(TypedDict):
    collections: list[dict[str, object]]


class CollectionInfoResult(TypedDict, total=False):
    name: str
    document_count: int
    sample_documents: list[dict[str, object]]
    error: str


class SearchResult(TypedDict, total=False):
    query: str
    collection: str
    results_count: int
    results: list[dict[str, object]]
    error: str


class DeleteResult(TypedDict, total=False):
    deleted: bool
    collection: str
    ids_removed: int
    remaining: int
    error: str


class StressTestResult(TypedDict, total=False):
    collection: str
    documents_ingested: int
    ingest_time_seconds: float
    ingest_throughput_docs_per_sec: float
    search_benchmark: dict[str, object]
    note: str
    error: str


class IngestResult(TypedDict, total=False):
    collection: str
    documents_ingested: int
    chunks_created: int
    total_in_collection: int
    ingested: int
    error: str


class MemoryRecallResult(TypedDict, total=False):
    query: str
    collection: str
    results_count: int
    results: list[dict[str, object]]
    note: str
    error: str
    allowed: list[str]


class MemoryIngestResult(TypedDict, total=False):
    status: str
    id: str
    collection: str
    type: str
    importance: int
    total_memories: int
    existing_id: str
    similarity: float
    existing_text: str
    note: str
    error: str
    operation: str
    allowed: list[str]


class MemoryAmendResult(TypedDict, total=False):
    status: str
    original_id: str
    successor_id: str
    reason: str
    error: str
    detail: dict[str, object]


class MemoryRetireResult(TypedDict, total=False):
    status: str
    id: str
    reason: str
    error: str


class MemoryContextResult(TypedDict, total=False):
    collection: str
    memory_count: int
    included: int
    last_contact_with_companion: dict[str, object] | None
    message_quota: dict[str, object]
    delivery_state: str
    delivery_errors: list[str]
    context: str


class MemorySampleResult(TypedDict):
    collection: str
    memory_count: int
    sampled: int
    sample: str


class ProvenanceAuditResult(TypedDict):
    collection: str
    memory_count: int
    retired_count: int
    fictional_scene_count: int
    missing_provenance: dict[str, int]
    values: dict[str, dict[str, int]]
