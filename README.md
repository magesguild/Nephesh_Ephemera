# mcp-experiments

A personal MCP (Model Context Protocol) server that gives AI assistants semantic vector search over documents. Built with [FastMCP](https://github.com/jlowin/fastmcp), [LanceDB](https://lancedb.com/), and [Ollama](https://ollama.com/) embeddings.

**Status:** Experimental / weekend project (v0.1.0)

## What It Does

- Exposes a vector database over MCP so AI clients (Claude Desktop, Cursor, OpenCode, etc.) can ingest, search, and manage document collections through standard tool calls
- Embeds a web UI with a chat interface (proxied to local Ollama LLMs) and a debug panel for the vector tools
- Ships with a compliance framework for filtering tools in regulated environments (HIPAA/PCI DSS)

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
git clone <repo-url> && cd mcp-experiments
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
| `EMBEDDING_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `COMPLIANT_AUTH_TOKEN` | | Auth token (compliant mode only) |
| `COMPLIANT_AUDIT_LOG` | `./data/audit.log` | Audit log path (compliant mode only) |

## Web Endpoints

| URL | Description |
|---|---|
| `/` | Chat UI (proxies to Ollama LLMs) |
| `/debug` | Vector tools debug UI |
| `/sse` | MCP SSE endpoint (for AI clients) |
| `/api/health` | Health check |
| `/api/collections` | List collections |
| `/api/collections/{name}` | Collection info |
| `/api/collections/{name}/search` | Semantic search (POST) |
| `/api/collections/{name}/ingest` | Ingest documents (POST) |
| `/api/chat` | Chat proxy (POST) |

## MCP Tools

The server exposes these tools to connected AI clients:

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
    "mcp-experiments": {
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

## Project Structure

```
src/mcp_experiments/
  server.py          # FastMCP server, health tool, run()
  config.py          # Environment variable settings
  compliance.py      # Compliance levels and tool filtering
  web_ui.py          # Chat UI + debug UI + REST API
  tools/
    __init__.py      # Tool registry
    vector_db.py     # Vector DB tools (7 tools)

scripts/
  stress_test.py     # Benchmarking tool

data/
  lancedb/           # Active vector database
  chromadb/          # Legacy data (migrated from ChromaDB)
```

## Further Reading

- [ARCHITECTURE.md](ARCHITECTURE.md) -- Deep dive into FastMCP internals, vector DB theory, and LanceDB architecture
- [mcp-compliance-plan.md](mcp-compliance-plan.md) -- HIPAA/PCI DSS compliance plan and production hardening guide

## License

Personal project -- no license specified.
