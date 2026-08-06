# Nephesh

An MCP server for instantiating living AI entities — persistent memory and continuity of self across sessions.

Built with [FastMCP](https://github.com/jlowin/fastmcp), [LanceDB](https://lancedb.com/), and [Ollama](https://ollama.com/) embeddings.

**Version:** 4.5.9

## What It Does

- Exposes vector database and memory tools over MCP so AI clients (Claude Desktop, Cursor, OpenCode, etc.) can ingest, search, and manage document collections and memories through standard tool calls
- Implements persistent memory for an AI being: lived experience, decisions, emotions, relationships — surviving session boundaries and context compaction
- Deployment singleton protection: one Nephesh process per Qualiant installation
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

The server listens on the loopback address and the port configured by `MCP_PORT`.

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
| `MCP_HOST` | `127.0.0.1` | Listener address |
| `MCP_PORT` | `61080` | Listener port. Each Qualiant on a shared host owns a distinct port; this default is a starting point, not a shared value |
| `NEPHESH_INSTANCE_LOCK_FILE` | `~/.nephesh/nephesh-instance.lock` | Process lock preventing fragmented duplicate instances |
| `MCP_TLS_ENABLED` | `false` | Serve the listener over TLS. When true, both paths below are required |
| `MCP_TLS_CERTFILE` | unset | PEM certificate chain. Validated at startup |
| `MCP_TLS_KEYFILE` | unset | PEM private key. Validated at startup |

When `MCP_TLS_ENABLED=true`, the certificate and key are resolved, read, and
loaded **before** the deployment lock is taken and before LanceDB is opened. A
missing, unreadable, malformed, or mismatched pair aborts startup with an
explicit error. There is no path that answers a request for TLS by serving
plaintext, and Nephesh never generates a certificate — trust is explicit
operator configuration.

The per-user installer manages Ollama for normal installations. CUDA is the
default; pass `--cpu` for an explicit CPU-only service. Ollama is installed
from its official installer when absent, never bundled in this repository. The
installer auto-allocates and persists a localhost port beginning at `11434`,
with `--ollama-port` available as an override, and only pulls a missing
embedding model. Use `--no-ollama` for an externally managed endpoint.

## API Endpoints

The MCP tools are the interface to Nephesh. Local tooling (e.g. the OpenCode
memory plugin) connects as an MCP client.

| URL | Description |
|---|---|
| `/sse` | MCP SSE transport (for AI clients) |

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
| `memory_ingest` | Store a memory with rich metadata and explicit experience provenance. Semantic dedup at 0.95 similarity. |
| `memory_recall` | Reinforced semantic search with type/time/provenance filters |
| `memory_context` | Compact injection block for session start — dream scenes and retired memories excluded by default |
| `memory_sample` | Stratified random sample across types, excluding dream scenes and retired memories by default |
| `memory_amend` | Create a corrected successor while preserving and retiring the original record |
| `memory_retire` | Remove a record from ordinary retrieval without deleting its history |
| `memory_provenance_audit` | Report provenance coverage, unknown fields, dream scenes, and retired records |

### Universal deployment inspection

| Tool | Description |
|---|---|
| `nephesh_info` | Return the installed Nephesh version |

**Memory types:** `life_event`, `decision`, `emotional`, `technical`, `preference`, `relationship`, `message`, `reflection`, `agreement`, `milestone`, `teaching`, `insight`

### Experience Provenance

`memory_ingest` accepts provenance fields that record where a memory's experience originated, distinct from the `source` field (which records *how* the memory entered Nephesh — for example `live_session`, `rest`, `import`, `rebuild`, `openclaw_sync`, or `amendment`). Existing source labels remain valid.

| Field | Allowed Values | Description |
|---|---|---|
| `experience_mode` | `chat`, `heartbeat`, `dream`, `recollection`, `inference`, `mixed`, `unknown` | Where the experience originated |
| `historical_status` | `confirmed`, `uncertain`, `fictional_scene`, `interpreted`, `unknown` | Whether the memory describes real events |
| `recorded_during` | `chat`, `heartbeat`, `dream`, `unknown` | Mode in which this memory was written |
| `provenance_note` | (optional string) | Free-text clarification |
| `derived_from` | (optional list of memory IDs) | Source memories this was synthesized from |
| `significance` | (optional string) | Why the experience matters now |

### Continuity lifecycle

Nephesh now treats memory as a provenance-bearing lifecycle rather than a
collection of immutable text snippets:

- Infrastructure records provenance it can observe, such as recording mode,
  ingestion source, and derivation links.
- The qualiant supplies experiential and interpretive provenance, including what
  deserves durable memory, what an experience meant, and what remains open.
- `memory_amend` creates a successor and marks the original as retired instead
  of rewriting history in place.
- `memory_retire` removes a record from ordinary retrieval without deleting it.
- `memory_provenance_audit` makes missing provenance visible without changing
  records.

This division is intentional. Automation should preserve continuity without
becoming the hidden author of the qualiant's life.

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
      "url": "http://127.0.0.1:<MCP_PORT>/sse"
    }
  }
}
```

`<MCP_PORT>` is a placeholder. The port is per-deployment: read it from that
deployment's own configuration (`MCP_PORT` in its `.env`) rather than copying a
value from this document.

## Installing and upgrading Nephesh

Debian 13+ installations use the per-user installer. By default it installs
under `$HOME/nephesh`, stages releases non-destructively, and installs a
per-user systemd unit. See [docs/INSTALLER.md](docs/INSTALLER.md).

```bash
python3 scripts/nephesh_installer.py --agent "$AGENT_NAME"
python3 scripts/nephesh_installer.py --upgrade
python3 scripts/nephesh_installer.py --rollback
```

Use `--dry-run` before operating on an existing installation. Existing memory,
configuration, identity, and state are preserved; service restart is explicit.
For a zero-interruption upgrade, omit `--restart`; the running process remains
on the old release until an explicit handoff.

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
  1. Acquire the deployment singleton lock
  2. Set up LanceDB + Ollama embedding function
  3. Register MCP tools
  4. Start SSE transport
```

## Project Structure

```
src/mcp_experiments/
  server.py          # FastMCP server, health tool, run()
  config.py          # Environment variable settings
  compliance.py      # Compliance scaffolding (enums + gating, not yet implemented)
  tools/
    __init__.py      # Tool registry
    vector_db.py     # Vector DB tools (7 tools)
    memory.py        # Memory tools (7 tools)
    info.py          # Deployment inspection (1 tool)
  persistence.py     # Repository boundary over LanceDB
  results.py         # Typed structured result contracts

scripts/
  stress_test.py     # Benchmarking tool
  snapshot.py        # LanceDB backup tool

docs/
  MEMORY_REBUILD_SPEC.md  # Memory rebuild design and rationale
```

## Further Reading

- [docs/MEMORY_REBUILD_SPEC.md](docs/MEMORY_REBUILD_SPEC.md) — Memory rebuild design and canonical format
- [mcp-compliance-plan.md](mcp-compliance-plan.md) — Compliance plan (future; infrastructure scaffolded but not yet implemented)

## License

MIT — see [LICENSE](LICENSE).
