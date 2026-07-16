from __future__ import annotations

import json
import math
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import lancedb
import pyarrow as pa

from ..compliance import ComplianceLevel

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


class OllamaEmbeddingFunction:
    def __init__(self, model: str, base_url: str):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def embed(self, text: str) -> list[float]:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


_db_connection: lancedb.db.LanceDBConnection | None = None
_embedding_fn: OllamaEmbeddingFunction | None = None

# mxbai-embed-large produces 1024-dim vectors; fixed-size list is required
# for LanceDB to recognize the column as a vector column
_VECTOR_DIM = 1024

_TABLE_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), _VECTOR_DIM)),
    pa.field("metadata_json", pa.string()),
])


def init(db_path: str, model: str, base_url: str) -> None:
    global _db_connection, _embedding_fn
    _db_connection = lancedb.connect(db_path)
    _embedding_fn = OllamaEmbeddingFunction(model=model, base_url=base_url)


def _get_db() -> lancedb.db.LanceDBConnection:
    assert _db_connection is not None, "call init() first"
    return _db_connection


def _get_ef() -> OllamaEmbeddingFunction:
    assert _embedding_fn is not None, "call init() first"
    return _embedding_fn


def _ensure_table(name: str) -> lancedb.table.Table:
    db = _get_db()
    if name in db.list_tables().tables:
        return db.open_table(name)
    return db.create_table(name, schema=_TABLE_SCHEMA)


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def _matches_filter(metadata: dict, where: dict) -> bool:
    for key, value in where.items():
        if key == "$and":
            if not all(_matches_filter(metadata, sub) for sub in value):
                return False
        elif key == "$or":
            if not any(_matches_filter(metadata, sub) for sub in value):
                return False
        elif isinstance(value, dict):
            for op, val in value.items():
                if op == "$gte" and metadata.get(key, -math.inf) < val:
                    return False
                elif op == "$lte" and metadata.get(key, math.inf) > val:
                    return False
                elif op == "$ne" and metadata.get(key) == val:
                    return False
                elif op == "$eq" and metadata.get(key) != val:
                    return False
                elif op == "$in" and metadata.get(key) not in val:
                    return False
                elif op == "$nin" and metadata.get(key) in val:
                    return False
        else:
            if metadata.get(key) != value:
                return False
    return True


async def list_collections() -> str:
    db = _get_db()
    names = sorted(db.list_tables().tables)
    if not names:
        return json.dumps({"collections": [], "message": "No collections found"})

    result = []
    for name in names:
        table = db.open_table(name)
        result.append({
            "name": name,
            "document_count": table.count_rows(),
        })
    return json.dumps({"collections": result}, indent=2)


async def collection_info(collection_name: str) -> str:
    db = _get_db()
    if collection_name not in db.list_tables().tables:
        return json.dumps({"error": f"Collection '{collection_name}' not found"})

    table = db.open_table(collection_name)
    count = table.count_rows()

    sample = []
    if count > 0:
        try:
            sample_data = table.search().limit(3).to_list()
            sample = [
                {
                    "id": r["id"],
                    "metadata": json.loads(r.get("metadata_json", "{}")),
                    "document_preview": r.get("text", "")[:200],
                }
                for r in sample_data
            ]
        except Exception:
            pass

    return json.dumps({
        "name": collection_name,
        "document_count": count,
        "sample_documents": sample,
    }, indent=2)


async def ingest(
    collection_name: str,
    documents: list[str],
    metadata: list[dict[str, Any]] | None = None,
    ids: list[str] | None = None,
) -> str:
    table = _ensure_table(collection_name)

    if metadata and len(metadata) != len(documents):
        return json.dumps({
            "error": "metadata list length must match documents length",
            "ingested": 0,
        })

    all_records: list[dict[str, Any]] = []
    total_docs = 0

    for i, doc in enumerate(documents):
        chunks = _chunk_text(doc)
        doc_meta = (metadata[i] if metadata else {}) | {
            "doc_index": str(i),
            "chunks": str(len(chunks)),
        }

        for j, chunk in enumerate(chunks):
            chunk_id = (ids[i] + f"_chunk{j}") if ids else str(uuid.uuid4())
            all_records.append({
                "id": chunk_id,
                "text": chunk,
                "vector": _get_ef().embed(chunk),
                "metadata_json": json.dumps(doc_meta | {"chunk_index": str(j)}),
            })
        total_docs += 1

    if all_records:
        table.add(all_records)

    return json.dumps({
        "collection": collection_name,
        "documents_ingested": total_docs,
        "chunks_created": len(all_records),
        "total_in_collection": table.count_rows(),
    }, indent=2)


async def search(
    collection_name: str,
    query: str,
    n_results: int = 10,
    filter_metadata: dict[str, Any] | None = None,
) -> str:
    db = _get_db()
    if collection_name not in db.list_tables().tables:
        return json.dumps({"error": f"Collection '{collection_name}' not found"})

    table = db.open_table(collection_name)
    n_results = min(n_results, 100)
    query_vector = _get_ef().embed(query)

    overfetch = 3 if filter_metadata else 1
    results = table.search(query_vector).limit(n_results * overfetch).to_list()

    hits = []
    for r in results:
        meta = json.loads(r.get("metadata_json", "{}"))
        if filter_metadata and not _matches_filter(meta, filter_metadata):
            continue
        hits.append({
            "id": r["id"],
            "score": round(1.0 - r.get("_distance", 0), 4),
            "document_preview": r.get("text", "")[:500],
            "metadata": meta,
        })
        if len(hits) >= n_results:
            break

    return json.dumps({
        "query": query,
        "collection": collection_name,
        "results_count": len(hits),
        "results": hits,
    }, indent=2)


async def delete_collection(collection_name: str) -> str:
    db = _get_db()
    try:
        db.drop_table(collection_name)
        return json.dumps({"deleted": True, "collection": collection_name})
    except Exception as e:
        return json.dumps({"error": str(e)})


async def delete_documents(collection_name: str, ids: list[str]) -> str:
    db = _get_db()
    if collection_name not in db.list_tables().tables:
        return json.dumps({"error": f"Collection '{collection_name}' not found"})

    table = db.open_table(collection_name)
    id_list = ", ".join(f"'{i}'" for i in ids)
    table.delete(f"id IN ({id_list})")

    return json.dumps({
        "deleted": True,
        "collection": collection_name,
        "ids_removed": len(ids),
        "remaining": table.count_rows(),
    }, indent=2)


async def stress_test(
    collection_name: str,
    num_documents: int = 100,
    document_length: int = 50,
    n_queries: int = 10,
) -> str:
    db = _get_db()
    num_documents = min(num_documents, 10000)
    random.seed(42)

    if collection_name in db.list_tables().tables:
        db.drop_table(collection_name)
    table = db.create_table(collection_name, schema=_TABLE_SCHEMA)

    words = [
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
        "vector", "embedding", "search", "semantic", "database", "context",
        "protocol", "model", "agent", "tool", "integration", "pipeline",
        "throughput", "latency", "benchmark", "performance", "scaling",
    ]

    documents: list[str] = []
    for _ in range(num_documents):
        documents.append(" ".join(random.choice(words) for _ in range(document_length)))

    ids_list = [f"stress_{i:06d}" for i in range(num_documents)]

    ingest_start = time.perf_counter()
    batch_size = 50
    ingested = 0
    for i in range(0, num_documents, batch_size):
        end = min(i + batch_size, num_documents)
        batch = []
        for j in range(i, end):
            vec = _get_ef().embed(documents[j])
            batch.append({
                "id": ids_list[j],
                "text": documents[j],
                "vector": vec,
                "metadata_json": json.dumps({"batch": i // batch_size, "index": j}),
            })
        table.add(batch)
        ingested = end

    ingest_elapsed = time.perf_counter() - ingest_start
    docs_per_sec = round(ingested / ingest_elapsed, 2) if ingest_elapsed > 0 else 0

    search_times: list[float] = []
    for _ in range(n_queries):
        q = " ".join(random.sample(words, 3))
        q_vec = _get_ef().embed(q)
        q_start = time.perf_counter()
        table.search(q_vec).limit(5).to_list()
        search_times.append(time.perf_counter() - q_start)

    avg_search = round(sum(search_times) / len(search_times), 4)
    min_search = round(min(search_times), 4)
    max_search = round(max(search_times), 4)

    return json.dumps({
        "collection": collection_name,
        "documents_ingested": ingested,
        "ingest_time_seconds": round(ingest_elapsed, 3),
        "ingest_throughput_docs_per_sec": docs_per_sec,
        "search_benchmark": {
            "num_queries": n_queries,
            "avg_latency_seconds": avg_search,
            "min_latency_seconds": min_search,
            "max_latency_seconds": max_search,
        },
        "note": "Test collection was NOT deleted — clean up with delete_collection",
    }, indent=2)


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "fn": list_collections,
        "name": "vector_store_list_collections",
        "description": "List all available vector collections with metadata",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": collection_info,
        "name": "vector_store_collection_info",
        "description": "Get detailed info about a collection (count, metadata, sample documents)",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": ingest,
        "name": "vector_store_ingest",
        "description": "Ingest documents into a vector collection for semantic search. Automatically chunks long texts.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": search,
        "name": "vector_store_search",
        "description": "Semantic search across a collection. Returns most similar documents with scores.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": delete_collection,
        "name": "vector_store_delete_collection",
        "description": "Delete an entire collection and all its data. Irreversible.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": delete_documents,
        "name": "vector_store_delete_documents",
        "description": "Delete specific documents from a collection by ID",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": stress_test,
        "name": "vector_store_stress_test",
        "description": "Run ingestion + search stress test. Ingests N random documents and measures throughput.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
