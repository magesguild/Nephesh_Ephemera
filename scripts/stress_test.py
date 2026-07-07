#!/usr/bin/env python3
"""
Standalone vector DB stress test. Can run directly against ChromaDB (higher
throughput) or against a running MCP server via SSE/HTTP.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

try:
    import chromadb
except ImportError:
    chromadb = None  # type: ignore

try:
    from mcp_experiments.tools.vector_db import init, search, ingest, delete_collection
except ImportError:
    init = search = ingest = delete_collection = None  # type: ignore


WORDS = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "vector", "embedding", "search", "semantic", "database", "context",
    "protocol", "model", "agent", "tool", "integration", "pipeline",
    "throughput", "latency", "benchmark", "performance", "scaling",
    "retrieval", "augmented", "generation", "nearest", "neighbor",
    "cosine", "similarity", "dimension", "feature", "representation",
]


def generate_documents(num: int, words_per_doc: int) -> list[str]:
    return [" ".join(random.choice(WORDS) for _ in range(words_per_doc)) for _ in range(num)]


def test_direct(
    collection: str,
    num_docs: int,
    words_per_doc: int,
    n_queries: int,
    db_path: str,
    batch_size: int,
):
    if chromadb is None:
        print("ERROR: chromadb not installed", file=sys.stderr)
        sys.exit(1)

    client = chromadb.PersistentClient(path=db_path)
    try:
        client.delete_collection(collection)
    except ValueError:
        pass

    # Use ChromaDB's default embedding function (all-MiniLM-L6-v2)
    # rather than Ollama for max throughput
    collection_handle = client.create_collection(collection)

    docs = generate_documents(num_docs, words_per_doc)
    ids = [f"direct_{i:08d}" for i in range(num_docs)]
    metadatas = [{"index": i, "batch": i // batch_size} for i in range(num_docs)]

    ingest_start = time.perf_counter()
    for i in range(0, num_docs, batch_size):
        end = min(i + batch_size, num_docs)
        collection_handle.add(
            documents=docs[i:end],
            ids=ids[i:end],
            metadatas=metadatas[i:end],
        )
        _progress("Ingesting", i + batch_size, num_docs)
    ingest_elapsed = time.perf_counter() - ingest_start

    final_count = collection_handle.count()
    docs_per_sec = round(final_count / ingest_elapsed, 2) if ingest_elapsed > 0 else 0
    print(f"\nIngested {final_count} docs in {ingest_elapsed:.2f}s ({docs_per_sec} docs/sec)")

    search_times: list[float] = []
    for i in range(n_queries):
        q = " ".join(random.sample(WORDS, 3))
        qs = time.perf_counter()
        collection_handle.query(query_texts=[q], n_results=5)
        search_times.append(time.perf_counter() - qs)
    search_times.sort()

    avg_s = round(sum(search_times) / len(search_times), 4)
    p99_s = round(search_times[int(len(search_times) * 0.99) - 1], 4)

    print(f"\nSearch ({n_queries} queries): avg={avg_s}s  p99={p99_s}s")

    client.delete_collection(collection)
    print(f"Cleaned up '{collection}'")

    return {
        "mode": "direct",
        "documents_ingested": final_count,
        "ingest_time_seconds": round(ingest_elapsed, 3),
        "ingest_throughput_docs_per_sec": docs_per_sec,
        "search_avg_seconds": avg_s,
        "search_p99_seconds": p99_s,
    }


async def test_via_api(
    collection: str,
    num_docs: int,
    words_per_doc: int,
    n_queries: int,
    db_path: str,
    embedding_model: str,
    ollama_url: str,
    batch_size: int,
):
    if init is None:
        print("ERROR: cannot import mcp_experiments tools", file=sys.stderr)
        sys.exit(1)

    init(db_path=db_path, model=embedding_model, base_url=ollama_url)

    docs = generate_documents(num_docs, words_per_doc)

    ingest_result = json.loads(
        await ingest(
            collection_name=collection,
            documents=docs,
            metadata=[{"source": "stress_test"} for _ in docs],
        )
    )
    print(f"Ingested {ingest_result.get('documents_ingested', 0)} docs")
    print(f"  {ingest_result.get('chunks_created', 0)} chunks created")
    print(f"  {ingest_result.get('total_in_collection', 0)} total in collection")

    search_times: list[float] = []
    for i in range(n_queries):
        q = " ".join(random.sample(WORDS, 3))
        qs = time.perf_counter()
        await search(collection_name=collection, query=q, n_results=5)
        search_times.append(time.perf_counter() - qs)

    search_times.sort()
    avg_s = round(sum(search_times) / len(search_times), 4)
    p99_s = round(search_times[int(len(search_times) * 0.99) - 1], 4)
    print(f"\nSearch ({n_queries} queries): avg={avg_s}s  p99={p99_s}s")

    await delete_collection(collection_name=collection)
    print(f"Cleaned up '{collection}'")

    return {
        "mode": "via_api",
        "ingest_time_seconds": ingest_result.get("ingest_time_seconds", 0),
        "search_avg_seconds": avg_s,
        "search_p99_seconds": p99_s,
    }


def _progress(label: str, current: int, total: int):
    if total <= 0:
        return
    pct = min(100, int(current / total * 100))
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\r{label}: [{bar}] {current}/{total} ({pct}%)", end="", file=sys.stderr)
    if current >= total:
        print(file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Vector DB stress test")
    parser.add_argument("--mode", choices=["direct", "api"], default="direct",
                        help="'direct' = raw ChromaDB, 'api' = via mcp_experiments internals")
    parser.add_argument("--collection", default="stress_test")
    parser.add_argument("--num-docs", type=int, default=1000)
    parser.add_argument("--words-per-doc", type=int, default=50)
    parser.add_argument("--n-queries", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--db-path", default="./data/chromadb")
    parser.add_argument("--embedding-model", default="mxbai-embed-large")
    parser.add_argument("--ollama-url", default="http://localhost:11434")

    args = parser.parse_args()

    print(f"Vector DB Stress Test")
    print(f"  Mode:      {args.mode}")
    print(f"  Documents: {args.num_docs}")
    print(f"  Words/doc: {args.words_per_doc}")
    print(f"  Queries:   {args.n_queries}")
    print()

    if args.mode == "direct":
        result = test_direct(
            collection=args.collection,
            num_docs=args.num_docs,
            words_per_doc=args.words_per_doc,
            n_queries=args.n_queries,
            db_path=args.db_path,
            batch_size=args.batch_size,
        )
    else:
        result = asyncio.run(test_via_api(
            collection=args.collection,
            num_docs=args.num_docs,
            words_per_doc=args.words_per_doc,
            n_queries=args.n_queries,
            db_path=args.db_path,
            embedding_model=args.embedding_model,
            ollama_url=args.ollama_url,
            batch_size=args.batch_size,
        ))

    print(f"\n{'='*40}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
