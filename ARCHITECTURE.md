# Deep Dive: FastMCP & Vector Database Internals

## 1. What FastMCP Is

FastMCP is Anthropic's high-level Python SDK for building MCP servers. It's a
wrapper around the lower-level `mcp.server.lowlevel.Server` class that provides:

- **Automatic JSON Schema generation** — Python function type annotations → MCP
  input schemas, no manual dicts
- **Pydantic validation** — arguments are validated and coerced automatically
- **Transport handling** — stdio, SSE, and Streamable HTTP are all supported
- **Auth integration** — OAuth 2.1 + PKCE built in
- **Starlette under the hood** — SSE and Streamable HTTP run via Uvicorn

### Without FastMCP (low-level API):

```python
from mcp.server.lowlevel import Server

server = Server("my-server")

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [types.Tool(
        name="my_tool",
        description="Does something",
        inputSchema={"type": "object", "properties": {...}},
    )]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    ...
```

### With FastMCP:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
async def my_tool(x: int, label: str = "default") -> str:
    """Does something — this docstring becomes the tool description."""
    return f"{label}: {x}"
```

FastMCP introspects the function signature and generates the full JSON Schema
for you. The `@mcp.tool()` decorator calls `mcp.add_tool()` internally, which
creates a `Tool` object via `Tool.from_function()`.

### How Tool Registration Works

```
mcp.add_tool(fn, name, description)
  └─► Tool.from_function(fn, name, description)
        ├─► Inspects fn.__name__, docstring
        ├─► Builds FuncMetadata from fn signature
        │     ├─► Extracts parameter names, types, defaults
        │     └─► Creates a Pydantic model (arg_model)
        └─► Stores in ToolManager._tools dict
```

When a client calls `tools/call`:
```
MCP client → FastMCP.call_tool(name, args)
  └─► ToolManager.call_tool(name, arguments)
        └─► Tool.run(arguments)
              └─► fn_metadata.call_fn_with_arg_validation(fn, arguments)
                    ├─► Validates via Pydantic (coercion/type errors)
                    └─► Calls the actual Python function
```

### What Happens at `mcp.run()`

Calling `mcp.run(transport="sse", host="127.0.0.1", port=8080)` does:

1. Creates a Starlette ASGI app
2. Mounts SSE transport at `/sse` and message handler at `/messages/`
3. Starts Uvicorn server on the given host:port
4. Client connects to `/sse`, gets a stream of events
5. Client POSTs tool calls to `/messages/`

The SSE transport flow:
```
Client → GET /sse
  Server → SSE event: "Connected"
  Server → SSE event: "Endpoint: /messages/?session_id=..."
Client → POST /messages/?session_id=...  {jsonrpc, method: "tools/call", ...}
  Server → HTTP 202 Accepted
  Server → SSE event: {jsonrpc, result: ...}
```

### What Our `server.py` Looks Like Now

```python
mcp = FastMCP("mcp-experiments", instructions="...")

@mcp.tool()
async def health() -> str:
    """Check if the server is running."""
    return json.dumps({"status": "ok"})

# In run():
init_vector_db(...)        # Set up ChromaDB + Ollama
register_all(mcp)           # Register all tool modules
mcp.run(transport="sse")    # Start the server
```

`register_all()` iterates each tool module's `TOOL_DEFINITIONS` list and calls
`mcp.add_tool(fn, name=..., description=...)`. The compliance system filters
out tools that don't match the current server mode.

---

## 2. Vector Database Internals

### What a Vector Database Does

At its core, a vector database stores arrays of floats (embeddings) and answers
the question: *"which stored vectors are most similar to this query vector?"*

### Key Concepts

#### Embedding

An embedding is a dense vector representation of data (text, image, etc.)
produced by a neural network. Our server uses `mxbai-embed-large` via Ollama:

```
Input: "Vector databases store embeddings"
  │
  ▼
Ollama API: POST /api/embeddings
  {
    "model": "mxbai-embed-large",
    "prompt": "Vector databases store embeddings"
  }
  │
  ▼
Output: [0.023, -0.456, 0.789, ..., 0.123]  (1024 floats)
```

Each dimension captures some semantic feature of the input. Two similar texts
produce vectors that are "close" in this high-dimensional space.

#### Similarity Measure: Distance

LanceDB uses L2 (Euclidean) distance by default. We convert it to a similarity
score in `search()`:

```
l2_distance(A, B) = sqrt(sum((Aᵢ - Bᵢ)²))

When vectors are identical:  distance = 0  (score = 1)
When vectors are opposite:   distance = √2 ≈ 1.414  (score ≈ -0.414)
```

Our score conversion:
```python
score = 1.0 - distance  # 1.0 = perfect match
```

This normalization keeps the output consistent with the ChromaDB-era API.

#### How Search Works (ANN)

Exact nearest-neighbor search (comparing a query against every stored vector)
is O(n) — fine for small datasets, impractical at scale. Vector databases use
**Approximate Nearest Neighbor (ANN)** algorithms:

- **IVF (Inverted File Index)** — LanceDB's default. Clusters vectors with k-means,
  searches only the nearest clusters. O(log n) with reasonable accuracy.
- **HNSW (Hierarchical Navigable Small World)** — Builds a multi-layer graph.
  Available in LanceDB but not the default. Better recall at higher memory cost.

LanceDB's IVF is partitioned and append-only — new vectors route to the
appropriate partition without rebuilding the full index. This is the key
architectural difference from HNSW-based stores (ChromaDB, Qdrant) which need
periodic index rebuilds under continuous ingestion.

You can configure the index at table creation:

```python
import pyarrow as pa

table = db.create_table("my_table", schema=pa.schema([
    pa.field("id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32())),
    pa.field("metadata_json", pa.string()),
]))
```

Index tuning in LanceDB is done after creation:

```python
table.create_index(metric="L2", num_partitions=256, num_sub_vectors=16)
```

Tradeoffs:
- More partitions → faster search, potentially lower recall
- IVF + product quantization → smaller index, slight accuracy loss
- Append-only design → no rebuild pauses during ingestion

### LanceDB Under the Hood

LanceDB has a **columnar + embedded** architecture:

```
User Code (our tools)
  │
  ▼
LanceDB Python SDK (PyO3)
  │
  ▼
Lance Columnar Format (Rust)
  ├── Columnar storage (append-only fragments)
  ├── Vector index (IVF-PQ)
  └── Metadata (stored as columns in the Lance file)
```

- **Columnar**: Data is stored column-wise (like Parquet) — adding a column
  doesn't rewrite existing data
- **Append-only**: New writes create new file fragments; no in-place mutation
- **Versioned**: Each write produces a new version; you can time-travel
- **Embedded**: Runs in-process, no server to stand up — just `lancedb.connect()`
- **Object storage native**: Data URI can point to S3/GCS — works locally and
  on cloud with the same API

When you call `table.add(records)`:
1. Ollama embedding function is called for each document → vector
2. Record (id + text + vector + metadata_json) is serialized to Lance format
3. New fragment is appended — no index rebuild needed
4. IVF index is updated incrementally

When you call `table.search(query_vector)`:
1. IVF index routes the query to the nearest partitions
2. Distances computed within those partitions
3. Metadata filtering is applied post-search (in our implementation)
4. Results returned: dicts with id, text, metadata_json, _distance

### Vector DB Implementation Comparison

| Feature | LanceDB | Qdrant | Weaviate | Pinecone |
|---------|---------|--------|----------|----------|
| **Hosting** | Embedded / object-store | Embedded / Server | Server | Cloud only |
| **Index** | IVF-PQ | HNSW | HNSW | Proprietary |
| **Stores raw data** | Yes (columnar) | Metadata only | Metadata only | Metadata only |
| **Append-only** | Yes (no rebuilds) | No (HNSW rebuilds) | No | No |
| **Versioning** | Native (every write) | None | None | None |
| **Hybrid search** | Full-text + vector | BM25 + vector | BM25 + vector | No |
| **Multi-tenancy** | Table namespacing | Built-in collections | Built-in tenants | Built-in namespaces |
| **Deployment** | `pip install` | Docker | Docker | SaaS |

**LanceDB** is the right choice here because:
- Zero infrastructure — `pip install` and a local path (or S3 URI)
- Append-only design fits continuous ingestion from Slack/ClickUp/email
- Columnar storage means zero-copy schema evolution (new embedding model? add a column)
- Native versioning enables rollback of data pipeline errors
- Same API whether data sits on local disk or S3 — direct cloud migration path

**Qdrant** would be the next step up if you need:
- Multi-node clustering with raft consensus
- Built-in indexed filtering (LanceDB post-filters metadata)
- Higher recall requirements (HNSW typically beats IVF on recall)

### What Our Chunking Strategy Does

```
Document: "MCP is a protocol for connecting AI models to tools and data. It defines..."
                     ▼
Chunk at 500 chars with 50-char overlap:
  [0:500]   "MCP is a protocol for connecting AI models to tools and data. It defines..."
  [450:950] "...It defines how clients discover and invoke tool capabilities..."
  [900:1400] "...tool capabilities through a standard JSON-RPC interface..."
```

The overlap prevents cutting a semantic unit in half — the context straddles
chunks. Each chunk is independently embedded and searched. At query time, the
score reflects the best-matching chunk, not the full document.

### Compliance Integration

Each tool carries a `ComplianceLevel`:

```python
TOOL_DEFINITIONS = [
    {
        "fn": ingest,
        "name": "vector_store_ingest",
        "compliance": ComplianceLevel.NON_COMPLIANT,
        # ...
    },
]
```

When the server runs in `compliant` mode, tools classified as `NON_COMPLIANT`
are filtered out by `register_all()` before they reach FastMCP. In compliant
mode, the `COMPLIANT` flag could also trigger:
- Redaction of tool arguments in audit logs
- Blocking output containing PHI patterns
- Requiring OAuth tokens with specific scopes

This is where the "safeguards to prevent accidental login to non-compliant
systems" would be enforced — the server simply doesn't register those tools,
so the AI agent can't call them.

---

## 3. Architecture Summary

```
┌──────────────────────────────────────────────────────┐
│                   MCP Client                         │
│  (Claude Desktop, Cursor, custom agent, etc.)        │
└────────────────────────┬─────────────────────────────┘
                         │ SSE / Streamable HTTP
                         ▼
┌──────────────────────────────────────────────────────┐
│              FastMCP (Starlette + Uvicorn)            │
│                                                      │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ ToolManager│  │ AuthManager  │  │ SSE Transport│ │
│  └─────┬──────┘  └──────────────┘  └──────────────┘ │
└────────┼─────────────────────────────────────────────┘
         │ mcp.add_tool()
         ▼
┌──────────────────────────────────────────────────────┐
│                register_all(mcp)                      │
│                                                      │
│  For each tool module:                               │
│    For each TOOL_DEFINITION:                         │
│      if compliance check passes → mcp.add_tool(fn)   │
│                                                      │
│  Modules: vector_db  (future: slack, clickup, email) │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                vector_db.py  (LanceDB)                │
│                                                      │
│  init(db_path, model, base_url)                      │
│    └─► Creates OllamaEmbeddingFunction               │
│    └─► Creates LanceDB connection                    │
│                                                      │
│  ingest(collection_name, documents, ...)             │
│    └─► _chunk_text() → chunks                       │
│    └─► embed each chunk via Ollama                   │
│    └─► table.add(records)  (append-only)             │
│                                                      │
│  search(collection_name, query, ...)                 │
│    └─► embed query via Ollama                        │
│    └─► table.search(query_vector).limit(n)           │
│    └─► Post-filter metadata in Python                │
│    └─► Converts _distance → scores                   │
└──────────────────────────────────────────────────────┘
```
