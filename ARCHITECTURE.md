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

#### Similarity Measure: Cosine Distance

ChromaDB uses cosine distance by default:

```
cosine_distance(A, B) = 1 - cos(θ) = 1 - (A·B) / (|A| × |B|)

When vectors are identical:  distance = 0  (cosine = 1)
When vectors are orthogonal: distance = 1  (cosine = 0)
When vectors are opposite:   distance = 2  (cosine = -1)
```

We convert distance to a score in `search()`:
```python
score = 1.0 - distance  # 1.0 = perfect match, -1.0 = opposite
```

#### How Search Works (ANN)

Exact nearest-neighbor search (comparing a query against every stored vector)
is O(n) — fine for small datasets, impractical at scale. Vector databases use
**Approximate Nearest Neighbor (ANN)** algorithms:

- **HNSW (Hierarchical Navigable Small World)** — ChromaDB's default. Builds a
  multi-layer graph. Search navigates from coarse to fine layers. O(log n).
- **IVF (Inverted File Index)** — Clusters vectors, searches only relevant
  clusters. Faster but less accurate.

You can configure this in ChromaDB via `collection.metadata`:

```python
collection = client.create_collection(
    name="my_collection",
    metadata={
        "hnsw:space": "cosine",       # distance metric
        "hnsw:construction_epochs": 100,  # graph build quality
        "hnsw:M": 16,                 # connections per node
        "hnsw:ef_construction": 200,  # search width during build
        "hnsw:ef_search": 100,        # search width during query
    }
)
```

Tradeoffs:
- Higher `M` and `ef_construction` → better recall, slower build, more memory
- Higher `ef_search` → better recall, slower query

### ChromaDB Under the Hood

ChromaDB uses a **layered architecture**:

```
User Code (our tools)
  │
  ▼
ChromaDB Python Client API
  │
  ▼
ChromaDB Core (Rust via PyO3)
  ├── Metadata store (SQLite - DuckDB)
  ├── Vector index (HNSW - nmslib/hnswlib)
  └── Document store (SQLite)
```

- **Persistent mode**: Stores data to disk in a directory (our `data/chromadb/`)
- **Metadatas**: Stored in SQLite alongside the vector IDs, enables filtering
- **Embeddings**: Generated by our `OllamaEmbeddingFunction` before storage

When you call `collection.add()`:
1. Our embedding function is called for each document → vector
2. Vector + ID + metadata + document are sent to ChromaDB
3. ChromaDB stores them: metadata in SQLite, vector in HNSW index
4. HNSW index is built incrementally as vectors are added

When you call `collection.query()`:
1. Query text is embedded via our embedding function
2. HNSW search finds approximate nearest neighbors
3. Metadata filter is applied (if `where` is specified)
4. Results returned: IDs, distances, metadatas, documents

### Vector DB Implementation Comparison

| Feature | ChromaDB | Qdrant | Weaviate | Pinecone |
|---------|----------|--------|----------|----------|
| **Hosting** | Embedded/Server | Embedded/Server | Server | Cloud only |
| **Index** | HNSW | HNSW | HNSW | Proprietary |
| **Filters** | Metadata where | Payload filter | GraphQL where | Metadata filter |
| **Hybrid search** | No (v1.5) | Yes (BM25 + Dense) | Yes (BM25 + Dense) | No |
| **Multi-tenancy** | Manual namespacing | Built-in collections | Built-in tenants | Built-in namespaces |
| **Deployment** | pip install | Docker | Docker | SaaS |
| **Embedding** | Bring your own | Bring your own | Built-in modules | Built-in or BYO |

**ChromaDB** is ideal for our use case because:
- Zero infrastructure — just `pip install` and a directory path
- Fast iteration for experimentation
- Same API as production ChromaDB (can swap in a remote server later)
- Sufficient for datasets up to ~1M vectors

**Qdrant** would be the next step up if you need:
- Multi-node clustering
- Hybrid search (dense + sparse vectors)
- Higher throughput
- Built-in filtering without scanning

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
│                vector_db.py                           │
│                                                      │
│  init(db_path, model, base_url)                      │
│    └─► Creates OllamaEmbeddingFunction               │
│    └─► Creates ChromaDB PersistentClient             │
│                                                      │
│  ingest(collection_name, documents, ...)             │
│    └─► _chunk_text() → chunks                       │
│    └─► collection.add(documents, ids, metadatas)     │
│                                                      │
│  search(collection_name, query, ...)                 │
│    └─► collection.query(query_texts=[query])         │
│    └─► Converts distances → scores                  │
└──────────────────────────────────────────────────────┘
```
