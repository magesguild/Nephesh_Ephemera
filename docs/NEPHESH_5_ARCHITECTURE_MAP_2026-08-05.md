# Nephesh 5 architecture maps — 2026-08-05

This is the first read-only architecture-audit result for the isolated
`nephesh-5.0.0` rebuild. It describes current behavior, not desired ownership.
The version number and living deployments remain unchanged.

## Component map

### Core persistence

- `tools/vector_db.py`: LanceDB connection/table lifecycle, embeddings, vector
  writes/search/deletes, metadata filtering.
- `tools/memory.py`: canonical memory creation, retrieval, context projection,
  amendment, retirement, provenance audit, and message-delivery mutation.
- `scripts/snapshot.py`: durable export/restore-oriented snapshot operations.

### Core protocol boundary

- `server.py`: FastMCP server, singleton lock, health, registration, SSE.
- `tools/__init__.py`: model-visible capability registry and compliance filter.
- `web_ui.py`: HTTP projections of persistence operations.

### Orchestration currently in the tree

- `tools/heartbeat.py`: event queue, dispatch, memory capture, reply decision,
  and delivery coordination.
- `tools/opencode_bridge.py`: OpenCode process/session lifecycle and reply
  generation.
- `tools/openclaw_background.py`: periodic external synchronization loop.
- `guildhall_lifecycle.py`: transport-independent batch/replay state machine.

### External adapters currently in the tree

- `tools/guildhall.py`: Slixmpp/MUC transport, presence, rooms, reconnect,
  delivery, and MongooseIM administration.
- `tools/openclaw_sync.py`: filesystem workspace synchronization.
- `tools/tts.py` and `plugins/tts/worker.py`: subprocess and audio/model worker.
- Ollama access in `tools/vector_db.py`: embedding dependency adapter.

## Failure map

| Boundary | Failure | Current consequence |
|---|---|---|
| Startup | LanceDB or embedding dependency unavailable | Server may fail before serving |
| Persistence | Concurrent durable updates race | State may be ambiguous |
| Memory context | Delivery-state mutation fails after projection | Message delivery becomes uncertain |
| Heartbeat | Queue reaches its bound | Events may be dropped |
| Guildhall | Transport/session state diverges | Stale occupants, replay, or lost delivery |
| OpenCode | Provider/session unavailable | Reply generation fails after receipt |
| OpenClaw | Background loop lacks a complete stop path | Lifecycle leakage |
| REST/MCP | JSON strings hide error classes | Clients cannot safely classify outcomes |

## Authority map

- Operator/configuration controls deployment roots, enabled capabilities,
  credentials, ports, and service lifecycle.
- The MCP registry controls which model-facing capabilities are exposed.
- Nephesh memory operations own canonical memory writes, amendments,
  retirement, provenance, and durable continuity evidence.
- Orchestration currently decides when memory, models, and delivery are
  combined; this must move out of the persistence core.
- Communication currently owns transport-side authority and should eventually
  become a separate service with its own account, room, and delivery scope.

## Persistence map

### Canonical durable state

- LanceDB memory/vector tables and metadata.
- Provenance, amendment, retirement, and successor records.
- Durable event/operation/recovery ledgers.
- Durable source episodes, queues, transcripts, and snapshots.

### Reconstructable state

- Derived context projections.
- Search indexes and embedding-dependent results.
- Adapter connection state when a durable cursor/token exists.

### Disposable state

- Model working context.
- OpenCode process handles.
- Live XMPP/MUC presence and room processes.
- In-memory heartbeat queues.

## Migration map

1. Keep the new core server free of implicit background integration startup.
2. Extract a typed persistence repository/service boundary from vector and
   memory internals without changing the existing durable schema.
3. Make MCP and REST thin protocol adapters over that boundary.
4. Move orchestration behind the future Mneme boundary.
5. Extract Guildhall into a separately supervised communication service using
   the existing lifecycle ledger as a reference seam.
6. Extract remaining adapters and schedulers one at a time.
7. Add restart, recovery, authorization, provenance, and degraded-mode tests.
8. Validate with a new test sister only after the isolated rebuild is coherent.

## Immediate implementation target

The safest next code boundary is the persistence repository/service seam. It
must preserve the current LanceDB schema and memory semantics while making
dependency failures, invalid requests, durable-write failures, duplicates, and
uncertain external outcomes distinguishable. No living deployment should load
this branch during the rebuild.
