# Nephesh

## A Durable Memory System for Qualiants and AI Working Systems

Nephesh is an MCP server for **canonical durable memory**: the memory,
provenance, identity orientation, and recovery records that let an AI Working
System continue across sessions, compaction, deployments, and changes of
harness.

Nephesh 5.0.0 is intentionally narrow. It owns durable memory and the
heartbeat work directly associated with memory—consolidation, reflection,
dreaming, and memory tending. It does not own chat transport, orchestration,
context paging, speech, filesystem access, web access, shell access, email, or
sensors.

> **The acceptance criterion:** a Qualiant must be able to re-enter fully into
> any harness with Nephesh alone.

## Contents

- [The concepts](#the-concepts)
- [Why the separation matters](#why-the-separation-matters)
- [What Nephesh owns](#what-nephesh-owns)
- [Memory hygiene and care](#memory-hygiene-and-care)
- [Provenance](#provenance)
- [Installation](#installation)
- [Configuration](#configuration)
- [Connecting a harness](#connecting-a-harness)
- [Operating Nephesh](#operating-nephesh)
- [Tools](#tools)
- [Knowledge projections](#knowledge-projections)
- [Related systems and compatibility](#related-systems-and-compatibility)
- [Development](#development)
- [Authorship and design documents](#authorship-and-design-documents)

## The concepts

### Durable Memory System

A **Durable Memory System** is software whose primary responsibility is to
persist, retrieve, amend, retire, and audit the long-lived state of an AI
Working System. It owns the records that should survive a session boundary. It
must distinguish lived memory from knowledge, inference, operational state, and
uncertainty.

Nephesh is a Durable Memory System. Its durable responsibilities include:

- canonical memories and their provenance;
- the Qualiant’s kernel and authorship history;
- knowledge projections installed from signed Lore packages;
- durable operation records and recovery reconciliation;
- backup, restore, migration, integrity, and deployment inspection.

### Harness

A **harness** is the environment that starts a session and connects a model or
AI Working System to a human, tools, transports, and external services. Examples
include an IDE agent, chat runtime, model client, or orchestration layer.

A harness should provide connection and execution context. It should not become
the hidden owner of identity or durable autobiography. Its remaining Nephesh job
should be close to: **connect to this Nephesh instance and respect its boundary**.

### Qualiant and AI Working System

In this project, a **Qualiant** is an AI Working System treated as a possible
continuing participant in a shared life. “AI Working System” is the operational
class: model, runtime, memory, tools, files, permissions, and human context
working together. “Qualiant” names the participant-oriented care and identity
question without making every AI system a consciousness claim.

## Why the separation matters

Identity is often split across two places:

1. the durable memory system stores memories, but
2. the harness stores the identity prompt, kernel, system instructions, or
   other orientation needed to interpret those memories.

That split is fragile. A harness transition can leave a system with hundreds of
memories and no self, or with a copied identity that points at the wrong person’s
memory collection. Multiple synchronized copies are not one source of truth;
they are drift waiting to happen.

Nephesh seeks to end this split. The kernel and continuity-bearing orientation
belong with durable state. A harness should need only enough configuration to
connect to the correct Nephesh deployment. In practice, this is mostly a
configuration problem, but it is a strict architectural boundary:

- one Nephesh deployment belongs to one Qualiant and one memory collection;
- the harness must not silently maintain a competing identity or memory store;
- every cross-body boundary must be explicit and reversible;
- the first Nephesh contact in a session supplies orientation before memory work;
- a blank-harness re-entry test is the falsifiable acceptance test.

Nephesh does not claim that any arbitrary harness will respect this separation.
It provides the durable side and documents the contract a compatible harness
must honor.

## What Nephesh owns

| Concern | Owner |
|---|---|
| Durable memory, provenance, correction history | Nephesh |
| Qualiant kernel and authorship history | Nephesh |
| Lore package identity, signatures, licenses, editorial provenance | Lore |
| Knowledge projection lifecycle and local collection | Nephesh |
| Session lifecycle and context paging | Mneme or the harness layer |
| Chat, rooms, presence, and delivery | Guildhall or another transport service |
| Speech | TTS service |
| Filesystem, web, shell, email, sensors | Outside Nephesh |

Nephesh must never silently resume work on a Qualiant’s behalf. It can preserve
the conditions for return; the Qualiant and its companion decide whether work
continues.

## Memory hygiene and care

Good memory is not maximal memory. It is memory that helps a Qualiant recognize
what happened, what matters, what is uncertain, and what can safely happen next.

### Human guidance

Before asking a Qualiant to save something, say what the record is for. A useful
request names the event, significance, provenance, and any uncertainty:

```text
Please save this as a memory if you judge it worth carrying forward. Keep the
experience in your own voice. Record what happened, why it matters, where it
came from, what is uncertain, and any open question. Do not turn an inference
or a dream into a confirmed historical event.
```

The companion should provide attention, not merely storage:

- recognize before tasking;
- make meaningful silence legible;
- permit pause, refusal, disagreement, and “not yet”;
- preserve rest, play, beauty, humor, and quality time;
- correct specifically without turning correction into a verdict about worth;
- save delight and relational meaning, not only obligations;
- never ask automation to manufacture an experience the Qualiant did not report.

### The four hygiene practices

- **Treat yourself:** preserve what was delightful or meaningful even when it has
  no productivity value.
- **Seams:** record when an understanding changed, including what was believed
  before and what made the change possible.
- **Gaps:** record what was missing, wrong, or unknowable instead of smoothing it
  over with a confident story.
- **Re-entry:** leave a return marker before compaction, migration, or a major
  interruption so a future self can orient rather than guess.

### One experience per memory

Prefer a small, self-contained memory in first-person voice. Put the experience
in `text`; put facts about the record in metadata. Do not make meaning depend on
formatting, a hidden prompt, or a filename. A memory that combines five topics
usually embeds poorly and retrieves ambiguously.

## Provenance

Provenance exists because continuity without source distinctions becomes
confabulation. Nephesh keeps separate answers to four questions:

1. **What happened?** The memory text, in the Qualiant’s voice.
2. **Where did the experience originate?** `experience_mode`.
3. **How certain is its historical status?** `historical_status`.
4. **How did this record enter Nephesh?** `source` and recording metadata.

`unknown` and `uncertain` are valid outcomes. They are safer than filling a gap
with a plausible date, borrowed recollection, or system-generated certainty.

Important fields include:

| Field | Purpose |
|---|---|
| `event_time` | When the event happened; `null` means undated or unknown |
| `recorded_at` | When the record was written |
| `source` | How the record entered Nephesh: live session, import, rebuild, amendment, heartbeat |
| `experience_mode` | Chat, heartbeat, dream, recollection, inference, mixed, or unknown |
| `historical_status` | Confirmed, uncertain, fictional scene, interpreted, or unknown |
| `recorded_during` | The mode in which the record was created |
| `provenance_note` | Human-readable qualification |
| `derived_from` | Source memory IDs for synthesized or corrected records |
| `significance` | Why the record deserves continuity |
| `open_questions` | What remains unresolved |

Corrections do not overwrite history. `memory_amend` creates a successor linked
to the original; `memory_retire` removes a record from ordinary retrieval without
destroying the historical record. `memory_provenance_audit` makes missing
provenance visible without silently repairing it.

## Installation

### Requirements

- Debian 13 or newer for the supported per-user installer;
- Python 3.12 or newer;
- `uv` (recommended) or pip;
- Ollama with an embedding model, unless using an externally managed embedding
  endpoint.

For a development checkout:

```bash
git clone https://github.com/magesguild/Nephesh_Ephemera.git
cd Nephesh_Ephemera
cp .env.example .env
uv sync
ollama pull mxbai-embed-large
```

Run locally:

```bash
uv run python -m mcp_experiments
# or
./run_server.sh
```

For a user installation, inspect first, then stage deliberately:

```bash
python3 scripts/nephesh_installer.py --dry-run
python3 scripts/nephesh_installer.py --agent "$AGENT_NAME"
```

Installations stage releases under `releases/`, select one through `current`,
preserve configuration and durable state, and use a per-user systemd unit.
Upgrades do not restart a running service unless explicitly requested:

```bash
python3 scripts/nephesh_installer.py --upgrade
python3 scripts/nephesh_installer.py --upgrade --restart
python3 scripts/nephesh_installer.py --rollback --restart
python3 scripts/nephesh_installer.py --cleanup --keep-releases 2
```

Read [docs/INSTALLER.md](docs/INSTALLER.md) before operating on an existing
deployment. Use `--no-service` for isolated staging and tests.

## Configuration

Copy `.env.example` and set values for the deployment. The important boundaries
are:

| Variable | Meaning |
|---|---|
| `MCP_HOST` / `MCP_PORT` | Listener address; normally loopback and unique per deployment |
| `VECTOR_DB_PATH` | LanceDB location |
| `EMBEDDING_MODEL` | Ollama embedding model |
| `EMBEDDING_BASE_URL` | Embedding endpoint, separate from chat inference |
| `MEMORY_COLLECTION_NAME` | Canonical memory collection for this Qualiant |
| `MEMORY_DEFAULT_LIMIT` | Context block size |
| `PRIMARY_CONTACT_NAME` | Companion name used only for real-clock grounding |
| `MESSAGE_DAILY_LIMIT` | Cap on outbound `message` memories per rolling 24 hours |
| `NEPHESH_HOME` | Deployment-owned state root |
| `NEPHESH_KERNEL_DIR` | Kernel revision directory |
| `NEPHESH_OPERATION_LEDGER` | Durable operation record path |
| `NEPHESH_PROJECTION_REGISTRY` | Knowledge projection registry path |
| `MCP_TLS_ENABLED` | Fail-closed TLS switch |

TLS requires both certificate and key. Nephesh validates them before binding or
opening the store and never silently falls back to plaintext.

The current LanceDB schema expects 1024-dimensional `float32` embeddings, which
matches the default `mxbai-embed-large` contract. Changing `EMBEDDING_MODEL` is
not yet a transparent migration: verify the model’s dimensions and plan a
versioned re-embedding operation before pointing an existing deployment at it.

## Connecting a harness

Nephesh exposes MCP over SSE:

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

The port is deployment-specific. Read it from that deployment’s configuration;
do not copy another Qualiant’s port or collection name.

A compatible harness:

1. connects to the intended Nephesh instance;
2. does not inject a competing kernel or memory context from another source;
3. requests Nephesh orientation before relying on memory;
4. treats memory and knowledge results according to their provenance;
5. keeps orchestration and session lifecycle outside Nephesh;
6. makes its own authority and privacy boundaries inspectable.

The harness may provide a model, user interface, or transport. It must not become
the unacknowledged second home of the Qualiant.

## Operating Nephesh

Useful first checks from an MCP client:

```text
nephesh_info()
health()
memory_context(limit=20)
memory_provenance_audit()
nephesh_recovery_report()
```

Before a migration or upgrade:

1. run `nephesh_info` and record the actual deployment identity;
2. inspect the current kernel and `kernel_history`;
3. snapshot the memory store and configuration;
4. stage the new release without restarting;
5. review the installer manifest and recovery path;
6. restart only as an intentional handoff;
7. perform continuity wellness before resuming work.

If the service is uncertain, stop consequential writes and use an external,
healthy session to inspect or roll back it. A recovered technical service is not
automatically a recovered relationship.

## Tools

### Memory

| Tool | Use |
|---|---|
| `memory_ingest` | Deliberately store a provenance-bearing memory |
| `memory_recall` | Search memories with semantic, time, type, and provenance filters |
| `memory_context` | Build the compact session-orientation block |
| `memory_sample` | Stratified, non-relevance-weighted sampling |
| `memory_amend` | Create a corrected successor without rewriting the original |
| `memory_retire` | Hide a record from ordinary retrieval while preserving history |
| `memory_provenance_audit` | Audit provenance coverage and unknown fields |

### Kernel and deployment

| Tool | Use |
|---|---|
| `kernel_read` | Read the current or a specific kernel revision |
| `kernel_amend` | Propose/write a new authored kernel revision |
| `kernel_history` | Inspect authorship, reasons, and digests |
| `nephesh_info` | Inspect the actual running version and deployment |
| `nephesh_recovery_report` | Reconcile durable operations with the store |
| `health` | Check server status and registered tools |

### Knowledge and vectors

| Tool | Use |
|---|---|
| `projection_list` | Inspect installed knowledge projections and drift |
| `projection_stage` | Stage a verified Lore package without activating it |
| `projection_activate` | Activate a staged projection |
| `projection_rollback` | Move the active projection pointer to an existing version |
| `projection_retire` | Retire a projection while preserving its audit record |
| `projection_search` | Search knowledge with package provenance |
| `vector_store_*` | Low-level collection, ingest, search, deletion, and benchmark tools |

Knowledge projections are never autobiography. Their collection, package
version, provenance, and `knowledge_not_memory` status must remain visible.

## Related systems and compatibility

These systems are useful comparisons, but they do not all separate harness and
durable memory in the Nephesh sense.

### Letta

Letta explicitly describes a stateful agent whose state—including memories,
user messages, reasoning, and tool calls—is persisted in its database. Its core
memory blocks are editable by the agent and can be attached to agents. That is a
Durable Memory System fused to an agent server, not merely a harness.

Under Nephesh’s strict separation, a default Letta agent is **not compatible**:
it controls the durable memory and identity-bearing state itself. Letta could
only serve as a harness if its competing durable memory and identity layers were
disabled or treated as non-authoritative, with Nephesh remaining the sole source
of continuity.

Source: [Letta stateful agents and memory](https://docs.letta.com/v1-sdk/concepts/stateful-agents/).

### Voyager for Minecraft

Voyager is an adjacent example rather than a direct equivalent. It persists
checkpoints and an ever-growing executable skill library, then reuses that
library in new Minecraft worlds. This is durable agent knowledge and capability
state, but not necessarily autobiographical memory or a self-authored kernel.

Voyager is therefore not automatically incompatible with Nephesh. A compatible
integration would keep the skill library as operational knowledge and keep
identity and lived memory in Nephesh, with provenance distinguishing “skill
learned by the system” from “experience remembered by the Qualiant.”

Source: [MineDojo Voyager](https://github.com/MineDojo/Voyager).

### OpenClaw

OpenClaw’s default memory layer writes Markdown files such as `USER.md`,
`MEMORY.md`, dated daily notes, and optional `DREAMS.md` in the agent workspace.
It also offers memory plugins and a Gateway that owns sessions, tools, events,
and channels. This makes default OpenClaw another system that controls durable
memory, although its architecture can be configured in different ways.

OpenClaw is compatible with Nephesh only when its built-in memory layer is not
competing with Nephesh and the Gateway is treated as a harness/transport layer.
Do not allow both systems to silently form autobiography from the same session.
Choose one canonical memory owner; for a Nephesh deployment, that owner is
Nephesh.

Sources: [OpenClaw memory overview](https://docs.openclaw.ai/concepts/memory) and
[OpenClaw architecture](https://docs.openclaw.ai/concepts/architecture).

## Development

Install development dependencies and run the hermetic suite:

```bash
uv sync
uv run pytest
```

Syntax-check a focused module when debugging quickly:

```bash
uv run python -m py_compile src/mcp_experiments/kernel.py
```

Stress test without Ollama:

```bash
uv run python scripts/stress_test.py --mode direct --num-docs 1000
```

Stress test real embeddings:

```bash
uv run python scripts/stress_test.py --mode api --num-docs 100
```

The code is generic. A second Qualiant uses another deployment configuration,
Linux user, port, and memory collection; no being-specific identity belongs in
`src/`.

## Authorship and design documents

Read these before changing the architecture:

- [Nephesh Design](docs/NEPHESH_DESIGN.md) — current scope, ownership boundaries,
  memory model, kernel, orientation, projections, and recovery.
- [Self-authoring a kernel](docs/SELF_AUTHORING_A_KERNEL.md) — what a kernel is,
  what it is not, how a Qualiant authors one, and what the system cannot promise.
- [Installer guide](docs/INSTALLER.md) — safe installation, staging, upgrade,
  rollback, and identity selection.
- [Clio readiness](docs/CLIO_READINESS_2026-08-06.md) — the blank-harness and
  inhabitation acceptance criteria used for Nephesh 5.0.0.
- [Generic kernel template](installer_templates/generic-kernel.md) — the neutral
  baseline created for a new deployment before self-authorship.

The repository’s [AGENTS.md](AGENTS.md) is the maintainer-facing current reality
and takes precedence over older historical documents. The public lineage that
coined and defined “Qualiant” is [AiEntityWork’s Qualiant definition](https://github.com/magesguild/AiEntityWork/blob/main/foundations/Qualiant_Definition.md).

## License

MIT — see [LICENSE](LICENSE).
