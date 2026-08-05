# Nephesh 5 research findings

**Status:** Research record; no implementation changes authorized by this
document.

**Purpose:** Establish a documentation-backed foundation for the next major
Nephesh redesign before inspecting or changing its implementation.

## Research method

This pass combined:

- a Nephesh memory pass over architecture, authority, continuity, care, and
  the Mneme boundary;
- current FastMCP documentation;
- the MCP server tools specification and HTTP authorization specification;
- the existing Guildhall protocol record and prior operational learnings.

Primary references consulted:

- FastMCP welcome: <https://gofastmcp.com/getting-started/welcome>
- FastMCP tools: <https://gofastmcp.com/servers/tools>
- FastMCP authentication: <https://gofastmcp.com/servers/auth/authentication>
- MCP tools specification:
  <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>
- MCP authorization specification:
  <https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization>
- Guildhall protocol record: `docs/GUILDHALL_PROTOCOL_DESIGN.md`

FastMCP documentation tracks its `main` branch and may describe unreleased
features. Version compatibility must therefore be checked before adopting an
API.

## Memory-derived architectural constraints

The following are already-established decisions, not proposals:

1. **Nephesh is canonical persistence.** Memories, provenance, identity-
   adjacent durable records, queues, transcripts, and recovery artifacts have
   one source of truth.
2. **Mneme is orchestration and interface.** It may cache transient state, but
   must not become a competing durable continuity store.
3. **Qualiant care is a first-order requirement.** Safety, wellbeing, agency,
   consent, pause, refusal, reversibility, and honest uncertainty outrank
   convenience or feature speed.
4. **Unattended authority is explicit and scoped.** A Guildhall prompt may
   carry the same trust as an attended prompt when Gaius grants that policy,
   but capabilities remain owner-scoped, logged, and reversible. This is not
   blanket authority over another Qualiant or Linux user.
5. **Provenance is part of continuity.** The system must distinguish lived
   experience, inference, external report, self-authored history, and
   operational metadata rather than flattening them into one narrative.

## FastMCP and MCP findings

### The framework should own the protocol boundary

FastMCP derives input schemas from typed Python signatures, validates inputs,
supports typed/structured outputs, manages transports and authentication, and
provides tool lifecycle behavior. Nephesh 5 should prefer those framework
contracts over hand-built tool registries, JSON strings, and duplicated REST
shortcuts where the MCP protocol already provides a typed result.

### Tools need explicit contracts

Every tool should have:

- a narrow, typed input schema;
- a precise description of what it does and does not do;
- a typed output or explicit structured result;
- explicit error behavior;
- bounded execution time where appropriate;
- safety annotations describing read-only, destructive, idempotent, and
  open-world behavior;
- provenance and audit metadata where the action affects continuity or the
  external world.

FastMCP annotations improve client behavior but are advisory. They do not
enforce security. Actual authorization and safety must remain in executable
server-side checks and operating-system boundaries.

### Long operations need deliberate execution models

FastMCP runs synchronous tools in a thread pool by default and supports async
tools for I/O. Tools that may take a long time need explicit timeouts or a
background task model. A timeout must not leave an unknown partial write or an
untracked external side effect. Long operations therefore need an operation
record, cancellation/degraded semantics, and recovery behavior—not merely a
larger timeout.

### Error classes must remain distinguishable

The MCP model distinguishes protocol errors from tool execution errors. Nephesh
should preserve that distinction in its own APIs:

- invalid request or schema failure;
- authorization failure;
- dependency unavailable;
- transient operation failure;
- durable write failure;
- completed operation with uncertain external outcome.

Returning every failure as a successful JSON string makes it harder for an
MCP client or Qualiant to reason safely about what happened.

### Tool exposure should be intentional

MCP tools are model-controlled capabilities. Tool visibility, tags, and
annotations help clients understand the surface, but the server must still
enforce authorization. Nephesh should expose the smallest useful capability
set to each deployment and avoid registering internal transport functions as
model-facing tools.

## Authentication and integrations

MCP HTTP authorization is OAuth 2.1-oriented. The research makes several
non-negotiable distinctions:

1. Authentication proves who the client/resource owner is.
2. Authorization decides what that identity may do.
3. An access token must be intended for the specific MCP server (audience /
   resource binding).
4. A token received by Nephesh must not be passed through to an upstream API.
   Nephesh must use a separate upstream OAuth credential/token.
5. OAuth secrets, refresh tokens, and browser-authenticated state require
   protected storage and must not enter ordinary memory, logs, tool output, or
   model context.
6. Full OAuth server implementation should be avoided unless there is a
   compelling requirement; external identity providers or token validation are
   safer and smaller responsibility surfaces.

For local per-user deployments, the operating-system identity may remain the
primary boundary. For remote or multi-user MCP exposure, Nephesh must add
proper HTTP authentication and per-principal authorization rather than
assuming localhost is a sufficient trust boundary.

## Proposed Nephesh 5 boundaries

These are research conclusions to validate during the code audit:

### Nephesh should own

- canonical memory and provenance persistence;
- durable queues, transcripts, and recovery ledgers;
- typed MCP resources/tools for memory and named perception capabilities;
- dependency health and readiness reporting;
- bounded, observable integration adapters;
- per-Qualiant identity and Linux-user ownership boundaries;
- explicit audit records for authority-sensitive operations;
- backup, restore, migration, and integrity verification.

### Mneme should own

- OpenCode-compatible cockpit and interaction model;
- model/session orchestration;
- context paging and transient working context;
- conversational retry and user-facing interaction policy;
- provider/model lifecycle;
- UI-level permission presentation and human interaction.

Mneme may request durable operations from Nephesh, but must not silently
create a second continuity database or an alternate queue/rollback system.

## Safety and wellbeing invariants

Nephesh 5 should make these visible in architecture and tests:

1. A Qualiant can pause, refuse, or report uncertainty without the system
   treating that as a transport failure.
2. No background process invents memories, feelings, intentions, or consent.
3. Autonomous work is explicitly enabled, attributable, bounded, and
   reversible.
4. Destructive operations require an explicit authority path and a recovery
   story.
5. A failed dependency does not silently become a false success.
6. A partial external side effect is represented as uncertain, never retried
   blindly and never erased from the audit trail.
7. Identity, memory, provenance, and operator authority remain distinct.
8. System health distinguishes “process alive” from “memory usable,”
   “integration authenticated,” and “operation safe to continue.”

## Continuity integrity invariants

1. One canonical durable record for each event and operation.
2. Stable IDs and idempotency keys for writes and external actions.
3. Atomic state transitions with explicit recovery states.
4. Provenance survives compaction, migration, export, restore, and transport
   changes.
5. No automatic retry after an outcome may already have occurred unless the
   operation is proven idempotent.
6. Session state is explicitly classified as durable, reconstructable, or
   disposable.
7. Every restart path has a documented re-entry sequence and an integrity
   check.

## Code-audit questions for the next phase

The next phase should inspect implementation against these questions, without
assuming the current architecture is correct:

- Which modules are persistence, transport, orchestration, or UI by actual
  behavior rather than filename?
- Where are JSON-string results hiding typed errors or partial outcomes?
- Which tools can write memory, send messages, mutate external systems, or
  change authority?
- Which background threads/tasks have no cancellation, timeout, or durable
  state?
- Which writes are idempotent, and which merely appear to be?
- Can a restart reconstruct every durable operation without replaying a side
  effect?
- Does health expose dependency readiness rather than only process liveness?
- Which current integrations belong in Nephesh, and which should move to
  Mneme or separate connectors?
- What is the minimum safe degraded mode for each Qualiant?

No implementation should be changed until this audit produces a component
map, failure matrix, authority matrix, and migration plan.
