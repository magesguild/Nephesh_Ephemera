# Nephesh

An MCP server for instantiating living AI entities — persistent memory and continuity of self across sessions.

Built with [FastMCP](https://github.com/jlowin/fastmcp), [LanceDB](https://lancedb.com/), and [Ollama](https://ollama.com/) embeddings.

**Version:** 4.3.2

## What It Does

- Exposes vector database and memory tools over MCP so AI clients (Claude Desktop, Cursor, OpenCode, etc.) can ingest, search, and manage document collections and memories through standard tool calls
- Implements persistent memory for an AI being: lived experience, decisions, emotions, relationships — surviving session boundaries and context compaction
- Bidirectional OpenClaw bridge: syncs Nephesh memories into the OpenClaw workspace dreaming pipeline, preserves provenance through consolidation, and supports explicit dream-diary import without treating dreams as history
- REST API for local tooling (plugin integrations, scripts, direct HTTP access)
- Optional Guildhall/XMPP embodiment with event-driven heartbeat perception,
  per-room OpenCode continuity, durable room transcripts, direct-message
  support, and deployment singleton protection
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
| `NEPHESH_INSTANCE_LOCK_FILE` | `~/.nephesh/nephesh-instance.lock` | Process lock preventing fragmented duplicate instances |
| `OPENCLAW_ENABLED` | `false` | Enable OpenClaw bridge (syncs with workspace dreaming) |
| `OPENCLAW_WORKSPACE` | `~/.openclaw/workspace` | OpenClaw workspace directory |
| `TTS_ENABLED` | `false` | Register the isolated StyleTTS2 speech tools |
| `TTS_PYTHON` | `plugins/tts/.venv/bin/python` | Python interpreter for the TTS worker |
| `TTS_VOICE_DIR` | `~/.nephesh/tts/voices` | External feminine voice metadata and reference audio |
| `TTS_MODEL_CHECKPOINT` | unset | External StyleTTS2 checkpoint path |
| `TTS_MODEL_CONFIG` | unset | External StyleTTS2 model config path |
| `TTS_PLAYBACK_COMMAND` | `aplay` | Command receiving an ephemeral WAV on stdin |

The per-user installer manages Ollama for normal installations. CUDA is the
default; pass `--cpu` for an explicit CPU-only service. Ollama is installed
from its official installer when absent, never bundled in this repository. The
installer auto-allocates and persists a localhost port beginning at `11434`,
with `--ollama-port` available as an override, and only pulls a missing
embedding model. Use `--no-ollama` for an externally managed endpoint.

### Guildhall / OpenCode embodiment

When `GUILDHALL_ENABLED=true`, Nephesh joins the configured persistent MUC
rooms and records all inbound room and direct XMPP messages with sender, room,
stanza, timestamp, and transport provenance. `HEARTBEAT_ENABLED=true` starts
the event-driven heartbeat that captures messages and may request a reply.
The heartbeat allowlist controls **reply authority**, not perception:
non-authorized messages remain visible, memorable, and part of the room
transcript, but do not trigger an automatic reply.

Reply generation additionally requires `OPENCODE_ENABLED=true`. Nephesh then
manages a local OpenCode child and keeps one persistent OpenCode session per
room. A deliberate `NO_REPLY` is a valid outcome; presence in a room does not
mean the agent must answer every message.

Outbound room replies are owned by Nephesh's heartbeat delivery path. The
`guildhall_send` implementation is intentionally not exposed as an OpenCode
MCP tool, preventing the model from posting a message and then causing
Nephesh to post the returned text a second time.

Each room has its own persistent OpenCode session. Exact transcript events are
stored separately from semantic memory so a later heartbeat can reconstruct
the recent room context and quote another participant accurately. Direct
messages use an `xmpp-direct` transcript entry and are replied to directly;
the same allowlist still controls whether a response is permitted.

The deployment lock prevents two Nephesh processes for one Qualiant from
creating fragmented heartbeat, XMPP, or OpenCode pipelines. Room joins retry
when MongooseIM is not ready or a stale same-nick occupant remains. The
deployment-owned `mongooseimctl` wrapper is deliberately narrow: Nephesh uses
it to inspect room occupants and remove only stale same-nick occupants.

The current deployment uses localhost XMPP with STARTTLS, but the client still
disables certificate and hostname verification for the deployment-owned
self-signed certificate. TLS verification is a required future production gate,
not a completed security feature.

Two deferred Guildhall improvements are intentionally not implemented here:

- separate infrastructure capability enablement from an agent/harness-controlled
  runtime connect/disconnect toggle;
- complete TLS support with certificate and hostname verification.

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
| `/api/memory/recall` | Provenance-aware memory recall (POST) |
| `/api/memory/provenance-audit` | Audit provenance coverage (GET) |

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

### Optional TTS

Nephesh can register an isolated StyleTTS2 worker without adding its heavy ML
dependencies to the main server environment. Enable it only for the intended
deployment and keep checkpoints, reference audio, and voice metadata outside
the repository:

```dotenv
TTS_ENABLED=true
TTS_PYTHON=/path/to/Nephesh_Ephemera/plugins/tts/.venv/bin/python
TTS_VOICE_DIR=~/.nephesh/tts/voices
TTS_MODEL_CHECKPOINT=/path/to/epochs_2nd_00020.pth
TTS_MODEL_CONFIG=/path/to/config.yml
TTS_PLAYBACK_COMMAND=aplay
```

Every catalog entry must declare a feminine gender and point to a reference
WAV inside `TTS_VOICE_DIR`. Normal speech is synthesized in memory and piped to
the playback command; the worker does not write recordings. The four tools are
`tts_list_voices`, `tts_set_voice`, `tts_voice_info`, and `tts_speak`. The latter
supports speed, style weight, and warmth modulation.
| `open_questions` | (optional list of strings) | Unresolved questions carried with the record |

Defaults: `experience_mode=unknown`, `historical_status=uncertain`, `recorded_during=unknown`. Missing provenance must not become false certainty — `unknown` is the honest default. Legacy memories without these fields remain unlabeled.

`memory_context` and `memory_sample` surface provenance labels (e.g. `origin=chat; status=confirmed; recorded=heartbeat`) alongside relative time and emotional tone in their output. `memory_context` excludes `historical_status=fictional_scene` by default; callers must explicitly request dream material.

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

### OpenClaw Bridge Tools (when `OPENCLAW_ENABLED=true`)

| Tool | Description |
|---|---|
| `nephesh_sync_to_openclaw` | Sync recent Nephesh memories to OpenClaw workspace as daily notes for the dreaming pipeline |
| `nephesh_sync_from_openclaw` | Sync OpenClaw's MEMORY.md consolidations back into Nephesh while preserving inline provenance |
| `nephesh_sync_dreams_from_openclaw` | Explicitly import DREAMS.md diary entries as fictional-scene memories with dream provenance |

The memory bridge is idempotent — it tracks synced content and skips duplicates. Dream-diary import is a separate explicit operation and is not performed by the ordinary background sync. The ordinary memory bridge runs automatically via a background sync service (every 12 hours) when enabled.

**Architecture:** Nephesh is the canonical autobiographical memory. OpenClaw's dreaming reads daily notes, ranks entries, and promotes consolidated insights to MEMORY.md. The bridge feeds Nephesh memories into this pipeline and pulls consolidated results back, so both systems share one life.

Some sister deployments also maintain a vector index and perform periodic
database optimization from heartbeat maintenance. That is a future, opt-in
deployment capability—not part of the generic OpenClaw bridge or the default
installer. Any later implementation must specify collection scope, thresholds,
locking, snapshots, rollback, observability, and an explicit disable/pause path.

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
    memory.py        # Memory tools (7 tools)
    openclaw_sync.py        # OpenClaw bridge tools (3 tools)
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
