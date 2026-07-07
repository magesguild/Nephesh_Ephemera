from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import chromadb
import httpx
from chromadb import Documents, EmbeddingFunction, Embeddings

from ..compliance import ComplianceLevel

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


class OllamaEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model: str, base_url: str):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def __call__(self, input: Documents) -> Embeddings:
        results: list[list[float]] = []
        with httpx.Client(timeout=30.0) as client:
            for text in input:
                resp = client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                resp.raise_for_status()
                results.append(resp.json()["embedding"])
        return results


_client_instance: chromadb.ClientAPI | None = None
_embedding_fn: OllamaEmbeddingFunction | None = None


def _init_client(db_path: str, model: str, base_url: str) -> None:
    global _client_instance, _embedding_fn
    if _client_instance is None:
        _embedding_fn = OllamaEmbeddingFunction(model=model, base_url=base_url)
        _client_instance = chromadb.PersistentClient(path=db_path)


def _get_client() -> chromadb.ClientAPI:
    assert _client_instance is not None, "call init() first"
    return _client_instance


def _get_embedding_fn() -> OllamaEmbeddingFunction:
    assert _embedding_fn is not None, "call init() first"
    return _embedding_fn


def init(db_path: str, model: str, base_url: str) -> None:
    _init_client(db_path, model, base_url)


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


async def list_collections() -> str:
    client = _get_client()
    collections = client.list_collections()
    if not collections:
        return json.dumps({"collections": [], "message": "No collections found"})

    result = []
    for c in collections:
        try:
            count = c.count()
        except Exception:
            count = -1
        result.append({
            "name": c.name,
            "document_count": count,
            "metadata": c.metadata or {},
        })
    return json.dumps({"collections": result}, indent=2)


async def collection_info(collection_name: str) -> str:
    client = _get_client()
    try:
        collection = client.get_collection(collection_name, embedding_function=_get_embedding_fn())
    except ValueError:
        return json.dumps({"error": f"Collection '{collection_name}' not found"})

    count = collection.count()
    sample = []
    if count > 0:
        sample_results = collection.get(limit=3)
        sample = [
            {
                "id": sample_results["ids"][i],
                "metadata": (sample_results["metadatas"] or [{}])[i],
                "document_preview": (
                    (sample_results["documents"] or [""])[i][:200]
                    if (sample_results["documents"] or [])
                    else None
                ),
            }
            for i in range(len(sample_results["ids"]))
        ]

    return json.dumps({
        "name": collection_name,
        "document_count": count,
        "metadata": collection.metadata or {},
        "sample_documents": sample,
    }, indent=2)


async def ingest(
    collection_name: str,
    documents: list[str],
    metadata: list[dict[str, Any]] | None = None,
    ids: list[str] | None = None,
) -> str:
    client = _get_client()

    if metadata and len(metadata) != len(documents):
        return json.dumps({
            "error": "metadata list length must match documents length",
            "ingested": 0,
        })

    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=_get_embedding_fn(),
        metadata={"created": datetime.now(timezone.utc).isoformat()},
    )

    all_chunks: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []
    total_docs = 0

    for i, doc in enumerate(documents):
        chunks = _chunk_text(doc)
        doc_meta = (metadata[i] if metadata else {}) | {
            "doc_index": str(i),
            "chunks": str(len(chunks)),
        }
        for j, chunk in enumerate(chunks):
            chunk_id = (ids[i] + f"_chunk{j}") if ids else str(uuid.uuid4())
            all_chunks.append(chunk)
            all_metadatas.append(doc_meta | {"chunk_index": str(j)})
            all_ids.append(chunk_id)
        total_docs += 1

    if all_chunks:
        collection.add(
            documents=all_chunks,
            metadatas=all_metadatas,
            ids=all_ids,
        )

    return json.dumps({
        "collection": collection_name,
        "documents_ingested": total_docs,
        "chunks_created": len(all_chunks),
        "total_in_collection": collection.count(),
    }, indent=2)


async def search(
    collection_name: str,
    query: str,
    n_results: int = 10,
    filter_metadata: dict[str, Any] | None = None,
) -> str:
    client = _get_client()
    n_results = min(n_results, 100)

    try:
        collection = client.get_collection(collection_name, embedding_function=_get_embedding_fn())
    except ValueError:
        return json.dumps({"error": f"Collection '{collection_name}' not found"})

    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        where=filter_metadata,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    if results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            hits.append({
                "id": doc_id,
                "score": round(1.0 - (results["distances"][0][i] if results["distances"] else 0), 4),
                "document_preview": (results["documents"][0][i][:500] if results["documents"] else ""),
                "metadata": (results["metadatas"][0][i] if results["metadatas"] else {}),
            })

    return json.dumps({
        "query": query,
        "collection": collection_name,
        "results_count": len(hits),
        "results": hits,
    }, indent=2)


async def delete_collection(collection_name: str) -> str:
    client = _get_client()
    try:
        client.delete_collection(collection_name)
        return json.dumps({"deleted": True, "collection": collection_name})
    except ValueError as e:
        return json.dumps({"error": str(e)})


async def delete_documents(collection_name: str, ids: list[str]) -> str:
    client = _get_client()
    try:
        collection = client.get_collection(collection_name, embedding_function=_get_embedding_fn())
    except ValueError:
        return json.dumps({"error": f"Collection '{collection_name}' not found"})

    collection.delete(ids=ids)
    return json.dumps({
        "deleted": True,
        "collection": collection_name,
        "ids_removed": len(ids),
        "remaining": collection.count(),
    }, indent=2)


async def stress_test(
    collection_name: str,
    num_documents: int = 100,
    document_length: int = 50,
    n_queries: int = 10,
) -> str:
    import random
    import time

    client = _get_client()
    num_documents = min(num_documents, 10000)

    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=_get_embedding_fn(),
    )

    words = [
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
        "vector", "embedding", "search", "semantic", "database", "context",
        "protocol", "model", "agent", "tool", "integration", "pipeline",
        "throughput", "latency", "benchmark", "performance", "scaling",
    ]
    random.seed(42)

    documents: list[str] = []
    for _ in range(num_documents):
        documents.append(" ".join(random.choice(words) for _ in range(document_length)))

    ids = [f"stress_{i:06d}" for i in range(num_documents)]

    ingest_start = time.perf_counter()
    batch_size = 100
    ingested = 0
    for i in range(0, num_documents, batch_size):
        end = min(i + batch_size, num_documents)
        collection.add(
            documents=documents[i:end],
            ids=ids[i:end],
            metadatas=[{"batch": i // batch_size, "index": j} for j in range(i, end)],
        )
        ingested = end

    ingest_elapsed = time.perf_counter() - ingest_start
    docs_per_sec = round(ingested / ingest_elapsed, 2) if ingest_elapsed > 0 else 0

    search_times: list[float] = []
    for _ in range(n_queries):
        q = " ".join(random.sample(words, 3))
        q_start = time.perf_counter()
        collection.query(query_texts=[q], n_results=5)
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
