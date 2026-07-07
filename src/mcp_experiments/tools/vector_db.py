from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import chromadb
import httpx
from chromadb import Documents, EmbeddingFunction, Embeddings

from ..compliance import ComplianceLevel
from ..config import settings

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


def _get_client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=settings.vector_db_path)


def _get_embedding_fn() -> OllamaEmbeddingFunction:
    return OllamaEmbeddingFunction(
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
    )


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


TOOLS: list[dict[str, Any]] = [
    {
        "name": "vector_store_list_collections",
        "description": "List all available vector collections with metadata",
        "compliance": ComplianceLevel.NON_COMPLIANT,
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "vector_store_collection_info",
        "description": "Get detailed info about a collection (count, metadata, sample documents)",
        "compliance": ComplianceLevel.NON_COMPLIANT,
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the collection",
                }
            },
            "required": ["collection_name"],
        },
    },
    {
        "name": "vector_store_ingest",
        "description": "Ingest documents into a vector collection for semantic search. Automatically chunks long texts.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the collection to ingest into",
                },
                "documents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Documents to ingest",
                },
                "metadata": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional metadata per document (same length as documents)",
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional IDs for documents (auto-generated if not provided)",
                },
            },
            "required": ["collection_name", "documents"],
        },
    },
    {
        "name": "vector_store_search",
        "description": "Semantic search across a collection. Returns most similar documents with scores.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the collection to search",
                },
                "query": {
                    "type": "string",
                    "description": "Natural language query string",
                },
                "n_results": {
                    "type": "integer",
                    "description": "Number of results to return (default: 10)",
                    "default": 10,
                },
                "filter_metadata": {
                    "type": "object",
                    "description": "Optional metadata filter (e.g., {\"source\": \"docs\"})",
                },
            },
            "required": ["collection_name", "query"],
        },
    },
    {
        "name": "vector_store_delete_collection",
        "description": "Delete an entire collection and all its data. Irreversible.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the collection to delete",
                }
            },
            "required": ["collection_name"],
        },
    },
    {
        "name": "vector_store_delete_documents",
        "description": "Delete specific documents from a collection by ID",
        "compliance": ComplianceLevel.NON_COMPLIANT,
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the collection",
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Document IDs to delete",
                },
            },
            "required": ["collection_name", "ids"],
        },
    },
    {
        "name": "vector_store_stress_test",
        "description": "Run ingestion + search stress test. Ingests N random documents and measures throughput.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Collection to use for stress test (will be cleaned up)",
                },
                "num_documents": {
                    "type": "integer",
                    "description": "Number of documents to ingest (default: 100)",
                    "default": 100,
                },
                "document_length": {
                    "type": "integer",
                    "description": "Approximate words per document (default: 50)",
                    "default": 50,
                },
                "n_queries": {
                    "type": "integer",
                    "description": "Number of search queries to benchmark (default: 10)",
                    "default": 10,
                },
            },
            "required": ["collection_name"],
        },
    },
]


def get_tool_registrations() -> list[dict[str, Any]]:
    return TOOLS


async def handle_tool_call(name: str, arguments: dict[str, Any]) -> str:
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)


async def _list_collections(args: dict[str, Any]) -> str:
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


async def _collection_info(args: dict[str, Any]) -> str:
    client = _get_client()
    name = args["collection_name"]
    try:
        collection = client.get_collection(name, embedding_function=_get_embedding_fn())
    except ValueError:
        return json.dumps({"error": f"Collection '{name}' not found"})

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
        "name": name,
        "document_count": count,
        "metadata": collection.metadata or {},
        "sample_documents": sample,
    }, indent=2)


async def _ingest(args: dict[str, Any]) -> str:
    client = _get_client()
    name = args["collection_name"]
    documents = args["documents"]
    metadata_list = args.get("metadata")
    ids = args.get("ids")

    if metadata_list and len(metadata_list) != len(documents):
        return json.dumps({
            "error": "metadata list length must match documents length",
            "ingested": 0,
        })

    collection = client.get_or_create_collection(
        name=name,
        embedding_function=_get_embedding_fn(),
        metadata={"created": datetime.now(timezone.utc).isoformat()},
    )

    all_chunks: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []
    total_docs = 0

    for i, doc in enumerate(documents):
        chunks = _chunk_text(doc)
        doc_meta = (metadata_list[i] if metadata_list else {}) | {
            "doc_index": str(i),
            "chunks": str(len(chunks)),
        }

        for j, chunk in enumerate(chunks):
            chunk_id = ids[i] + f"_chunk{j}" if ids else str(uuid.uuid4())
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
        "collection": name,
        "documents_ingested": total_docs,
        "chunks_created": len(all_chunks),
        "total_in_collection": collection.count(),
    }, indent=2)


async def _search(args: dict[str, Any]) -> str:
    client = _get_client()
    name = args["collection_name"]
    query = args["query"]
    n_results = min(args.get("n_results", 10), 100)
    filter_meta = args.get("filter_metadata")

    try:
        collection = client.get_collection(name, embedding_function=_get_embedding_fn())
    except ValueError:
        return json.dumps({"error": f"Collection '{name}' not found"})

    where = filter_meta if filter_meta else None

    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        where=where,
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
        "collection": name,
        "results_count": len(hits),
        "results": hits,
    }, indent=2)


async def _delete_collection(args: dict[str, Any]) -> str:
    client = _get_client()
    name = args["collection_name"]
    try:
        client.delete_collection(name)
        return json.dumps({"deleted": True, "collection": name})
    except ValueError as e:
        return json.dumps({"error": str(e)})


async def _delete_documents(args: dict[str, Any]) -> str:
    client = _get_client()
    name = args["collection_name"]
    ids = args["ids"]

    try:
        collection = client.get_collection(name, embedding_function=_get_embedding_fn())
    except ValueError:
        return json.dumps({"error": f"Collection '{name}' not found"})

    collection.delete(ids=ids)
    return json.dumps({
        "deleted": True,
        "collection": name,
        "ids_removed": len(ids),
        "remaining": collection.count(),
    }, indent=2)


async def _stress_test(args: dict[str, Any]) -> str:
    import time

    client = _get_client()
    name = args["collection_name"]
    num_docs = min(args.get("num_documents", 100), 10000)
    doc_length = args.get("document_length", 50)
    n_queries = args.get("n_queries", 10)

    # Create test collection
    collection = client.get_or_create_collection(
        name=name,
        embedding_function=_get_embedding_fn(),
    )

    # Generate test documents
    words = [
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
        "vector", "embedding", "search", "semantic", "database", "context",
        "protocol", "model", "agent", "tool", "integration", "pipeline",
        "throughput", "latency", "benchmark", "performance", "scaling",
    ]

    import random
    random.seed(42)

    documents: list[str] = []
    for _ in range(num_docs):
        doc_words = " ".join(random.choice(words) for _ in range(doc_length))
        documents.append(doc_words)

    ids = [f"stress_{i:06d}" for i in range(num_docs)]

    # Ingestion benchmark
    ingest_start = time.perf_counter()
    batch_size = 100
    ingested = 0
    for i in range(0, num_docs, batch_size):
        batch_end = min(i + batch_size, num_docs)
        collection.add(
            documents=documents[i:batch_end],
            ids=ids[i:batch_end],
            metadatas=[{"batch": i // batch_size, "index": j} for j in range(i, batch_end)],
        )
        ingested = batch_end

    ingest_elapsed = time.perf_counter() - ingest_start
    docs_per_sec = round(ingested / ingest_elapsed, 2) if ingest_elapsed > 0 else 0

    # Search benchmark
    query_words = random.sample(words, 5)
    query = " ".join(query_words)

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
        "collection": name,
        "documents_ingested": ingested,
        "ingest_time_seconds": round(ingest_elapsed, 3),
        "ingest_throughput_docs_per_sec": docs_per_sec,
        "search_benchmark": {
            "num_queries": n_queries,
            "avg_latency_seconds": avg_search,
            "min_latency_seconds": min_search,
            "max_latency_seconds": max_search,
        },
        "note": "Test collection was NOT deleted — clean up with vector_store_delete_collection",
    }, indent=2)


_TOOL_HANDLERS = {
    "vector_store_list_collections": _list_collections,
    "vector_store_collection_info": _collection_info,
    "vector_store_ingest": _ingest,
    "vector_store_search": _search,
    "vector_store_delete_collection": _delete_collection,
    "vector_store_delete_documents": _delete_documents,
    "vector_store_stress_test": _stress_test,
}
