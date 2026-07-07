#!/usr/bin/env python3
"""
Standalone vector DB stress test. Can run against a running MCP server
(via HTTP) or directly against ChromaDB for higher throughput testing.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

try:
    import chromadb
except ImportError:
    chromadb = None  # type: ignore

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
    collection_name: str,
    num_docs: int,
    words_per_doc: int,
    n_queries: int,
    db_path: str,
    batch_size: int,
):
    if chromadb is None:
        print("ERROR: chromadb not installed. Run: pip install chromadb", file=sys.stderr)
        sys.exit(1)

    client = chromadb.PersistentClient(path=db_path)

    # Clean up from previous runs
    try:
        client.delete_collection(collection_name)
    except ValueError:
        pass

    collection = client.create_collection(collection_name)

    docs = generate_documents(num_docs, words_per_doc)
    ids = [f"direct_{i:08d}" for i in range(num_docs)]
    metadatas = [{"index": i, "batch": i // batch_size} for i in range(num_docs)]

    # Ingestion
    ingest_start = time.perf_counter()
    for i in range(0, num_docs, batch_size):
        end = min(i + batch_size, num_docs)
        collection.add(
            documents=docs[i:end],
            ids=ids[i:end],
            metadatas=metadatas[i:end],
        )
        _progress("Ingesting", i + batch_size, num_docs)
    ingest_elapsed = time.perf_counter() - ingest_start

    final_count = collection.count()
    docs_per_sec = round(final_count / ingest_elapsed, 2) if ingest_elapsed > 0 else 0

    print(f"\nIngested {final_count} documents in {ingest_elapsed:.2f}s ({docs_per_sec} docs/sec)")

    # Search
    query_words = random.sample(WORDS, 3)
    query = " ".join(query_words)

    search_times: list[float] = []
    print(f"Running {n_queries} search queries...")
    for i in range(n_queries):
        q = " ".join(random.sample(WORDS, 3))
        q_start = time.perf_counter()
        collection.query(query_texts=[q], n_results=5)
        search_times.append(time.perf_counter() - q_start)

    avg_search = round(sum(search_times) / len(search_times), 4)
    min_search = round(min(search_times), 4)
    max_search = round(max(search_times), 4)
    p99_search = round(sorted(search_times)[int(len(search_times) * 0.99) - 1], 4)

    print(f"\nSearch benchmark ({n_queries} queries):")
    print(f"  Avg:  {avg_search}s")
    print(f"  Min:  {min_search}s")
    print(f"  Max:  {max_search}s")
    print(f"  P99:  {p99_search}s")

    # Cleanup
    client.delete_collection(collection_name)
    print(f"\nCleaned up collection '{collection_name}'")

    return {
        "mode": "direct",
        "documents_ingested": final_count,
        "ingest_time_seconds": round(ingest_elapsed, 3),
        "ingest_throughput_docs_per_sec": docs_per_sec,
        "search_avg_seconds": avg_search,
        "search_p99_seconds": p99_search,
    }


def test_via_mcp_server(
    base_url: str,
    collection_name: str,
    num_docs: int,
    words_per_doc: int,
    n_queries: int,
):
    if httpx is None:
        print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
        sys.exit(1)

    server_url = base_url.rstrip("/")

    docs = generate_documents(num_docs, words_per_doc)
    result_text = json.dumps(docs)

    payload = {
        "name": "vector_store_stress_test",
        "arguments": {
            "collection_name": collection_name,
            "num_documents": num_docs,
            "document_length": words_per_doc,
            "n_queries": n_queries,
        },
    }

    print(f"Calling vector_store_stress_test on MCP server at {server_url}...")
    with httpx.Client(timeout=300.0) as client:
        resp = client.post(f"{server_url}/call_tool", json=payload)
        resp.raise_for_status()
        result = resp.json()
        print(json.dumps(result, indent=2))
        return result


def _progress(label: str, current: int, total: int):
    if total > 0:
        pct = min(100, int(current / total * 100))
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"\r{label}: [{bar}] {current}/{total} ({pct}%)", end="", file=sys.stderr)
        if current >= total:
            print(file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Vector DB stress test")
    parser.add_argument("--mode", choices=["direct", "server"], default="direct",
                        help="Run directly against ChromaDB or via MCP server")
    parser.add_argument("--server-url", default="http://127.0.0.1:8080",
                        help="MCP server URL (for server mode)")
    parser.add_argument("--collection", default="stress_test",
                        help="Collection name for the test")
    parser.add_argument("--num-docs", type=int, default=1000,
                        help="Number of documents to ingest")
    parser.add_argument("--words-per-doc", type=int, default=50,
                        help="Words per generated document")
    parser.add_argument("--n-queries", type=int, default=20,
                        help="Number of search queries to benchmark")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Batch size for ingestion")
    parser.add_argument("--db-path", default="./data/chromadb",
                        help="ChromaDB path (for direct mode)")

    args = parser.parse_args()

    print(f"Vector DB Stress Test")
    print(f"  Mode:      {args.mode}")
    print(f"  Documents: {args.num_docs}")
    print(f"  Words/doc: {args.words_per_doc}")
    print(f"  Queries:   {args.n_queries}")
    print(f"  Batch:     {args.batch_size}")
    print()

    if args.mode == "direct":
        result = test_direct(
            collection_name=args.collection,
            num_docs=args.num_docs,
            words_per_doc=args.words_per_doc,
            n_queries=args.n_queries,
            db_path=args.db_path,
            batch_size=args.batch_size,
        )
    else:
        result = test_via_mcp_server(
            base_url=args.server_url,
            collection_name=args.collection,
            num_docs=args.num_docs,
            words_per_doc=args.words_per_doc,
            n_queries=args.n_queries,
        )

    print(f"\n{'='*50}")
    print("RESULT:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
