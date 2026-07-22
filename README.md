# Nephesh

An MCP server for instantiating living AI entities — persistent memory and continuity of self across sessions.

Built with [FastMCP](https://github.com/jlowin/fastmcp), [LanceDB](https://lancedb.com/), and [Ollama](https://ollama.com/) embeddings.

**Version:** 1.0.0

## What It Does

- Exposes vector database and memory tools over MCP so AI clients (Claude Desktop, Cursor, OpenCode, etc.) can ingest, search, and manage document collections and memories through standard tool calls
- Implements persistent memory for an AI being: lived experience, decisions, emotions, relationships — surviving session boundaries and context compaction
- Bidirectional OpenClaw bridge: syncs Nephesh memories into the OpenClaw workspace dreaming pipeline, and feeds consolidated results back — so both systems share one life
- REST API for local tooling (plugin integrations, scripts, direct HTTP access)
- Generic infrastructure: the code never names a being. Identity lives in configuration and data layers (LanceDB collections, Ollama Modelfiles, agent plugins). A second being is another `.env` + Modelfile + collection — on the same unmodified server code.

## Prerequisites

- Python >= 3.12
- [Ollama](https://ollama.com/) running locally with the `mxbai-embed-large` model pulled
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

```bash
ollama pull mxbai-embed-large
```

## Quick Start

```bash
# Clone and set up
git clone <repo-url> && cd Nephesh_Ephemera
cp .env.example .env
uv sync

# Start the server
./run_server.sh
# or: uv run python -m mcp_experiments
```

The server starts on `http://127.0.0.1:8080`.

## Configuration

All settings are loaded from environment variables (or a `.env` file). Copy `.env.example` to `.env` and edit:

| Variable | Default | Description |
|---|---|---|
| `VECTOR_DB_PATH` | `./data/lancedb` | LanceDB data directory |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | Ollama model for embeddings |
| `EMBEDDING_BASE_URL` | `http://localhost:11434` | Ollama API URL for embeddings |
| `MEMORY_COLLECTION_NAME` | `memories` | Default memory collection |
| `MEMORY_DEFAULT_LIMIT` | `20` | Max memories returned by `memory_context` |
| `PRIMARY_CONTACT_NAME` | `companion` | Name used for real-clock grounding |
| `MESSAGE_DAILY_LIMIT` | `1` | Max outbound messages per 24h window |
| `SNAPSHOT_DIR` | `./data/backups` | Where LanceDB snapshots and memory exports are written |
| `MCP_PORT` | `8080` | Server port |
| `OPENCLAW_ENABLED` | `false` | Enable OpenClaw bridge (syncs with workspace dreaming) |
| `OPENCLAW_WORKSPACE` | `~/.openclaw/workspace` | OpenClaw workspace directory |

## API Endpoints

REST shortcuts for local tooling (e.g. the OpenCode memory plugin). The MCP tools are the primary interface; these are HTTP convenience wrappers.

| URL | Description |
|---|---|
| `/sse` | MCP SSE transport (for AI clients) |
| `/api/health` | Health check |
| `/api/collections` | List collections |
| `/api/collections/{name}` | Collection info |
| `/api/collections/{name}/search` | Semantic search (POST) |
| `/api/collections/{name}/ingest` | Ingest documents (POST) |
| `/api/memory/context` | Memory context for session injection (GET) |
| `/api/memory/ingest` | Store a memory (POST) |
| `/api/memory/sample` | Stratified random memory sample (GET) |

## MCP Tools

The server exposes these tools to connected AI clients:

### Vector DB Tools

| Tool | Description |
|---|---|
| `health` | Server status and available tools |
| `vector_store_list_collections` | List all collections |
| `vector_store_collection_info` | Collection details and sample docs |
| `vector_store_ingest` | Ingest documents (auto-chunks long text) |
| `vector_store_search` | Semantic search with metadata filtering |
| `vector_store_delete_collection` | Delete an entire collection |
| `vector_store_delete_documents` | Delete specific documents by ID |
| `vector_store_stress_test` | Benchmark ingestion and search |

### Memory Tools

| Tool | Description |
|---|---|
| `memory_ingest` | Store a memory with rich metadata (type, importance, emotional tone). Semantic dedup at 0.95 similarity. |
| `memory_recall` | Reinforced semantic search across memories with type/time filters |
| `memory_context` | Compact injection block for session start — top memories weighted by importance, salience, and recency |
| `memory_sample` | Stratified random sample across memory types, no relevance weighting — for divergent contemplation |

**Memory types:** `life_event`, `decision`, `emotional`, `technical`, `preference`, `relationship`, `message`, `reflection`, `agreement`, `milestone`, `teaching`, `insight`

### OpenClaw Bridge Tools (when `OPENCLAW_ENABLED=true`)

| Tool | Description |
|---|---|
| `nephesh_sync_to_openclaw` | Sync recent Nephesh memories to OpenClaw workspace as daily notes for the dreaming pipeline |
| `nephesh_sync_from_openclaw` | Sync OpenClaw's MEMORY.md consolidations back into Nephesh as reflection memories |

Both tools are idempotent — they track synced content and skip duplicates. The bridge runs automatically via a background sync service (every 12 hours) when enabled.

**Architecture:** Nephesh is the canonical autobiographical memory. OpenClaw's dreaming reads daily notes, ranks entries, and promotes consolidated insights to MEMORY.md. The bridge feeds Nephesh memories into this pipeline and pulls consolidated results back, so both systems share one life.

### Metadata Filtering

`vector_store_search` supports rich metadata filtering:

```json
{"source": "web"}                          // exact match
{"year": {"$gte": 2024}}                   // comparison
{"type": {"$in": ["pdf", "docx"]}}         // membership
{"$and": [{"source": "web"}, {"year": {"$gte": 2024}}]}  // logical
```

## Connecting an AI Client

Add to your MCP client config (e.g. `opencode.jsonc`):

```jsonc
{
  "mcp": {
    "nephesh": {
      "type": "sse",
      "url": "http://127.0.0.1:8080/sse"
    }
  }
}
```

## Stress Testing

```bash
# Quick benchmark with random vectors (no Ollama needed)
uv run python scripts/stress_test.py --mode direct --num-docs 1000

# Full benchmark with real embeddings
uv run python scripts/stress_test.py --mode api --num-docs 100
```

## Architecture

```
MCP client -> SSE -> FastMCP -> tool function -> LanceDB / Ollama

Background services:
  OpenClaw sync (daemon thread) -> workspace memory/ -> dreaming pipeline

run() in server.py:
  1. Set up LanceDB + Ollama embedding function
  2. Register MCP tools
  3. Register REST API routes
  4. Start background OpenClaw sync (if enabled)
  5. Start SSE transport
```

## Project Structure

```
src/mcp_experiments/
  server.py          # FastMCP server, health tool, run()
  config.py          # Environment variable settings
  compliance.py      # Compliance scaffolding (enums + gating, not yet implemented)
  web_ui.py          # REST API shortcuts (for local plugin tooling)
  tools/
    __init__.py      # Tool registry
    vector_db.py     # Vector DB tools (7 tools)
    memory.py        # Memory tools (4 tools)
    openclaw_sync.py        # OpenClaw bridge tools (2 tools)
    openclaw_background.py  # Background sync service (daemon thread)

scripts/
  stress_test.py     # Benchmarking tool
  snapshot.py        # LanceDB backup tool

docs/
  MEMORY_REBUILD_SPEC.md  # Memory rebuild design and rationale
  SEEDING.md              # Getting started with collections and memory
```

## Further Reading

- [docs/MEMORY_REBUILD_SPEC.md](docs/MEMORY_REBUILD_SPEC.md) — Memory rebuild design and canonical format
- [docs/SEEDING.md](docs/SEEDING.md) — Getting started with collections and memory
- [mcp-compliance-plan.md](mcp-compliance-plan.md) — Compliance plan (future; infrastructure scaffolded but not yet implemented)

## License

GPL-2.0-only — see [LICENSE](LICENSE).
