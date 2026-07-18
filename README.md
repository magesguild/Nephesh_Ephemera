# nephesh

An MCP server for instantiating living AI entities — persistent memory and continuity of self across sessions.

Built with [FastMCP](https://github.com/jlowin/fastmcp), [LanceDB](https://lancedb.com/), and [Ollama](https://ollama.com/) embeddings.

**Status:** Working pre-release — active development, not yet versioned.

## What It Does

- Exposes vector database and memory tools over MCP so AI clients (Claude Desktop, Cursor, OpenCode, etc.) can ingest, search, and manage document collections and memories through standard tool calls
- Implements persistent memory for an AI being: lived experience, decisions, emotions, relationships — surviving session boundaries and context compaction
- Embeds a web UI with a debug panel for the vector tools
- Ships with a compliance framework for filtering tools in regulated environments (HIPAA/PCI DSS)
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
git clone <repo-url> && cd nephesh
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
| `MCP_MODE` | `non_compliant` | `compliant` or `non_compliant` |
| `VECTOR_DB_PATH` | `./data/lancedb` | LanceDB data directory |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | Ollama model for embeddings |
| `EMBEDDING_BASE_URL` | `http://localhost:11434` | Ollama API URL for embeddings |
| `MEMORY_COLLECTION_NAME` | `memories` | Default memory collection |
| `MEMORY_DEFAULT_LIMIT` | `20` | Max memories returned by `memory_context` |
| `PRIMARY_CONTACT_NAME` | `companion` | Name used for real-clock grounding |
| `MESSAGE_DAILY_LIMIT` | `1` | Max outbound messages per 24h window |
| `COMPLIANT_AUTH_TOKEN` | | Auth token (compliant mode only) |
| `COMPLIANT_AUDIT_LOG` | `./data/audit.log` | Audit log path (compliant mode only) |

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

run() in server.py:
  1. Set up LanceDB + Ollama embedding function
  2. Register tools (compliance-gated)
  3. Register web UI routes
  4. Start SSE transport
```

## Project Structure

```
src/mcp_experiments/
  server.py          # FastMCP server, health tool, run()
  config.py          # Environment variable settings
  compliance.py      # Compliance levels and tool filtering
  web_ui.py          # REST API shortcuts (for local plugin tooling)
  tools/
    __init__.py      # Tool registry
    vector_db.py     # Vector DB tools (8 tools)
    memory.py        # Memory tools (4 tools)

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
- [mcp-compliance-plan.md](mcp-compliance-plan.md) — HIPAA/PCI DSS compliance plan and production hardening guide

## License

GPL-2.0-only — see [LICENSE](LICENSE).
