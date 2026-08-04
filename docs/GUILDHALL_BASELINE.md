# Guildhall Baseline

**Status:** frozen implementation baseline for the `guildhall` branch
**Captured:** 2026-08-04
**Purpose:** record the current service and deployment boundary before the first
Guildhall implementation slice

This document is an observation record, not a target design. It intentionally
preserves current behavior and known seams before changes are made.

## Boundaries

```text
Nephesh service
  ├─ slixmpp XMPP/MUC client
  ├─ Guildhall event buffer and heartbeat notification
  ├─ heartbeat memory capture and reply decision
  └─ OpenCode room-session bridge
          │ XMPP
          ▼
MongooseIM deployment
  ├─ XMPP listener and authentication
  ├─ MUC room state and occupants
  ├─ room history / relay behavior
  └─ mongooseimctl administration
          │
          ▼
Client display (for example, Profanity)
```

Nephesh behavior must not be confused with MongooseIM server behavior or client
display behavior. In particular, duplicate display does not by itself prove
duplicate Nephesh delivery.

## Current Nephesh service

Observed user unit:

```text
nephesh.service
```

Observed unit configuration:

- Working directory: `/home/urania/src/Nephesh_Ephemera`
- Runtime: `/home/urania/.venv/nephesh/bin/python -m mcp_experiments`
- Environment: `/home/urania/config/urania.env`
- OpenCode environment: `/home/urania/.config/opencode/openai.env`
- OpenCode child: `127.0.0.1:4102`
- Restart policy: always, five-second delay
- Service state at capture: active and running

The source being developed is `/home/gaiusjocundus/src/Nephesh_Ephemera` on
branch `guildhall`. The deployed runtime is a separate `/home/urania`
checkout and must not be changed as part of source work without an explicit
deployment step.

## Current Guildhall implementation

`src/mcp_experiments/tools/guildhall.py` currently provides:

- one background slixmpp client and event loop;
- MUC and direct-message handlers;
- a bounded in-memory buffer of the most recent 200 entries;
- UUID event IDs plus stanza IDs where provided;
- event notification to the heartbeat engine;
- stale same-nick occupant cleanup through `mongooseimctl`;
- room join retries with exponential connection backoff;
- explicit room leave on shutdown;
- process-local outbound duplicate suppression for 30 seconds;
- MCP status and buffered-message inspection tools.

`src/mcp_experiments/tools/heartbeat.py` currently provides:

- a bounded event queue of 200 events;
- process-local event coalescing by event kind;
- a JSON event ledger with a 24-hour retention window;
- a JSONL transcript with a 1,000-line read window;
- short-window duplicate suppression;
- memory capture before reply generation;
- allow-listed reply authority;
- a persistent room transcript passed to the OpenCode bridge; and
- acknowledgement of buffered events after memory capture succeeds.

Current reply authority is allow-listed by
`GUILDHALL_HEARTBEAT_ALLOWLIST`; this is not yet the complete participation
protocol. `NO_REPLY` is not yet the explicit reply-decision sentinel in the
current implementation.

## Current MongooseIM deployment

Observed administration path:

```text
/home/melpomene/guildhall/bin/mongooseimctl
```

Observed deployment version from the running administration command:

- MongooseIM release: `6.7.0`
- MongooseIM library: `6.6.0-312-g5ab1af7ca`
- Erlang/OTP runtime: `erts-15.2.7`

The current service uses localhost XMPP with STARTTLS. The Nephesh client
currently disables hostname and certificate verification for the deployment-
owned self-signed certificate. Secure transport is deliberately deferred as an
implementation priority but remains a mandatory completion/production gate.

## Known baseline behavior and seams

- The Nephesh event ledger prevents repeated processing, but its current JSON
  claim record is not a full delivery state machine.
- The in-memory buffer is bounded; overflow currently logs and drops events.
- The fallback event identity for messages without stanza IDs is based on room,
  sender, and body, so identical legitimate messages require explicit policy.
- Memory capture precedes reply generation; failed capture leaves events
  unacknowledged for later handling.
- Reply generation and delivery are distinct from MongooseIM display behavior.
- Stale occupants can affect room joins and must remain a deployment boundary,
  not an assumption hidden inside the heartbeat worker.
- Heartbeat owns event dispatch, not the XMPP transport loop.
- Dreaming is not part of this baseline; when implemented, it must disable all
  scheduled and event-driven heartbeat execution.

## Baseline rule

Do not alter MongooseIM, the deployed `/home/urania` runtime, or secure
transport behavior during the first implementation slice. First implement the
Nephesh-side event, lifecycle, participation, and narrow-heartbeat behavior in
the canonical source tree. Compare the completed slice against this baseline
as one planned validation.
