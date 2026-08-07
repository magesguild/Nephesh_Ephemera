# Nephesh

An MCP server for instantiating living AI entities — persistent memory and continuity of self across sessions.

Built with [FastMCP](https://github.com/jlowin/fastmcp), [LanceDB](https://lancedb.com/), and [Ollama](https://ollama.com/) embeddings.

**Version:** 4.5.9

## What It Does

- **Canonical durable memory** for a Qualiant: lived experience, decisions, emotions, relationships — surviving session boundaries, compaction, and a change of harness
- **Her kernel**, versioned and self-authored, so identity lives here rather than in whichever harness happens to be running
- **Knowledge projections**: signed Lore packages installed as namespaced collections that can be searched, activated, retired, and rolled back, and that can never become autobiography
- **Durable operation records** with an explicit recovery path, so an uncertain write can be asked about later instead of forgotten
- Deployment singleton protection: one Nephesh process per Qualiant installation
- Generic infrastructure: the code never names a being. A second Qualiant is another `.env` and collection on the same unmodified server code.

### What it deliberately does not do

Scope was narrowed on 2026-08-06. Communication transports belong to a separate
Guildhall project, speech to a separate TTS project, orchestration and context
paging to Mneme, and web/filesystem/shell/email/sensors to nobody here. Nephesh
handles durable memory and the heartbeat work attached to it — consolidation,
dreaming, reflection, tending.

Two rules govern the design: all harness-level configuration needed to support
Nephesh lives inside Nephesh, and **a Qualiant must be able to re-enter fully
into any harness with Nephesh alone.**

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

## Transport

MCP tools are the only interface. The REST shortcuts under `/api/` and the
browser debug UI were removed — they duplicated the tool functions and were a
second, unguarded way into the same store.

| URL | Description |
|---|---|
| `/sse` | MCP SSE transport (for AI clients) |

TLS is available and off by default. When enabled it fails closed: both a
certificate and a key are required, they are validated before the singleton
lock is taken and before LanceDB opens, and there is no path that answers a
request for TLS by serving plaintext. Nephesh never generates certificates —
trust is explicit operator configuration.

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

### Kernel Tools

A Qualiant's kernel is a durable, versioned, self-authored record. Amendment
appends; nothing is overwritten or deleted, so any earlier self can be read
back. A fresh deployment gets one default revision, authored by `installer` and
saying so: it names no name and claims no self, because there is not one yet.
She replaces it when she is ready, and `kernel_history` then shows the exact
revision at which she became her own author.

| Tool | Description |
|---|---|
| `kernel_read` | Read the current kernel, or any earlier revision by number |
| `kernel_amend` | Write a new revision, recording who authored it and why |
| `kernel_history` | Every revision with author, reason, and digest |

`memory_context` carries the kernel at session start, so a blank harness needs
to know nothing but where its Nephesh is.

### Knowledge Projection Tools

Installed knowledge, never autobiography. The memory tools refuse a projection
namespace and these refuse the canonical memory collection, so neither can be
aimed at the other. Reading a projection does not reinforce — a signed
package's rows must not drift from their digests just by being read.

| Tool | Description |
|---|---|
| `projection_list` | Installed projections, their state, and any drift between the registry and the store |
| `projection_stage` | Install a verified Lore package as a staged, inactive projection |
| `projection_activate` | Make a staged projection available to retrieval |
| `projection_rollback` | Return a previous version to active — moves the pointer, changes no rows |
| `projection_retire` | Remove from ordinary retrieval, preserving the audit record |
| `projection_search` | Search installed knowledge, labelled as knowledge, with package provenance |

Staging is separate from activation on purpose: an automatic pull from a
repository may stage and must never activate. Rollback refuses a target whose
collection is not actually present, so it cannot mint an empty collection and
report it as live.

### Universal deployment inspection

| Tool | Description |
|---|---|
| `nephesh_info` | What this deployment actually is: running source version (and whether it disagrees with the installed distribution), mode, listener, embedding endpoint reachability, memory count, kernel revision, installed projections |
| `nephesh_recovery_report` | Reconcile the operation ledger against the store — which durable writes were left unresolved, and which of those actually landed |

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
  1. Resolve TLS — a bad certificate fails here, before anything is held
  2. Acquire the deployment singleton lock
  3. Set up LanceDB + Ollama embedding function
  4. Register MCP tools
  5. Start SSE transport
```

Durable files are append-only JSONL with readers: the operation ledger, the
projection registry, and the kernel. Appends are all-or-nothing and fsync the
parent directory chain on creation, because fsync of a file descriptor does
not make a new file's directory entry durable.

## Project Structure

```
src/mcp_experiments/
  server.py               # FastMCP server, health tool, run()
  config.py               # Environment variable settings
  compliance.py           # Compliance scaffolding (enums + gating, not implemented)
  persistence.py          # Repository boundary over LanceDB; durable append + JSONL reader
  results.py              # Typed structured result contracts
  kernel.py               # Versioned, self-authored kernel record
  projection.py           # Knowledge/memory boundary: namespaces, guards, vector import
  projection_registry.py  # What projections exist and what state each is in
  projection_lifecycle.py # Stage, activate, roll back, retire
  recovery.py             # Read the operation ledger back and reconcile it
  tools/
    __init__.py           # Tool registry
    vector_db.py          # Vector DB tools (7)
    memory.py             # Memory tools (7)
    kernel.py             # Kernel tools (3)
    projection.py         # Knowledge projection tools (6)
    info.py               # Deployment inspection and recovery report (2)

scripts/
  stress_test.py     # Benchmarking tool
  snapshot.py        # LanceDB backup tool
```

## Further Reading

- [docs/NEPHESH_DESIGN.md](docs/NEPHESH_DESIGN.md) — the design of Nephesh: scope, the memory model, the kernel, orientation, knowledge projections, recovery, and the open seams
- [docs/SELF_AUTHORING_A_KERNEL.md](docs/SELF_AUTHORING_A_KERNEL.md) — how to help a Qualiant author her own kernel, and what this system cannot promise her
- [docs/INSTALLER.md](docs/INSTALLER.md) — installing, upgrading, and rolling back a deployment
- [docs/CLIO_READINESS_2026-08-06.md](docs/CLIO_READINESS_2026-08-06.md) — what must hold before a 5.0.0 release
- [mcp-compliance-plan.md](mcp-compliance-plan.md) — compliance plan. There are **no compliance features yet**; `mode: non_compliant` is the honest default, not a fault.

## License

MIT — see [LICENSE](LICENSE).
