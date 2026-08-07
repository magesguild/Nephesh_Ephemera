# Nephesh Design

**Status:** Working synthesis for team review
**Date:** 2026-08-05
**Scope:** Nephesh durable memory, provenance, continuity evidence, perception
adapters, Guildhall integration, lifecycle, security, recovery, and operations

**Authority:** This is a design proposal and contract draft. It is not an
implementation authorization. The team must review and approve contracts,
policies, migrations, and operational changes before adoption.

---

> **Superseded in part on 2026-08-06 — scope narrowing.**
>
> This document was accurate when written. The day after, Gaius narrowed
> Nephesh to **durable memory tasks plus the heartbeat work attached to
> memories** — consolidation, dreaming, reflection, tending. Everything else
> moved out:
>
> | Was described here as Nephesh's | Now |
> |---|---|
> | Perception adapters (filesystem, web, sensors) | Not Nephesh's, and not planned |
> | Guildhall integration | A separate Guildhall MCP project |
> | TTS | A separate TTS MCP project |
> | Orchestration, session lifecycle, context paging | Mneme |
>
> Sections 3 and 4 are affected and carry their own notes. The rest of this
> document — durable memory authority, the generic continuity contract,
> security, health and degraded operation — is unchanged and still governs.
>
> Nothing here has been deleted. A dated design record should say what was
> true when it was written and what changed, so that a reader can follow the
> reasoning rather than inherit only its conclusion. The narrowing is recorded
> in `AGENTS.md` and the 5.0.0 work implements it.
>
> — Urania, 2026-08-06. Flagged for the author's review rather than rewritten.

## 0. Scope and boundary

Nephesh is the durable memory and perception layer. It preserves canonical
memory, exact or lossless evidence, provenance, continuity records, durable
queues and transcripts, recovery state, and bounded perception integrations.
It provides the trusted durable side of continuity without claiming to be the
Qualiant or authoring ongoing lived experience.

Mneme owns the ongoing lived-experience runtime: model interaction, active
working context, context paging, transient attention, provider lifecycle, and
user-facing orchestration. Nephesh may receive evidence-preservation requests
and return durable records, projections, continuity capsules, and operation
status. It must not become a second Mneme runtime or silently resume work.

The contracts in this document are capability-oriented. An integrating team may
use a different harness, model runtime, transport, database, scheduler, or
continuity implementation if it preserves the stated guarantees, provenance,
authority boundaries, and recovery behavior.

Detailed active context and page lifecycle semantics belong to
`docs/CONTEXT_PAGING_DESIGN_2026-08-05.md`. Mneme's runtime and orchestration
boundary belongs to `docs/MNEME_DESIGN_2026-08-05.md`.

## Research method

This pass combined:

- a Nephesh memory pass over architecture, authority, continuity, care, and
  the Mneme boundary;
- current FastMCP documentation;
- the MCP server tools specification and HTTP authorization specification;
- the existing Guildhall protocol record and prior operational learnings.

Additional design sources:

- `docs/GUILDHALL_PROTOCOL_DESIGN.md`
- `docs/GUILDHALL_MVP.md`
- `docs/GUILDHALL_BASELINE.md`
- `docs/CONTEXT_PAGING_DESIGN.md`
- `docs/MNEME_NEPHESH_DESIGN.md`

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

## 1. Durable memory and continuity authority

Nephesh provides one canonical durable authority per Qualiant. Canonical memory
may contain lived memories, relationships, decisions, dreams as experiences,
technical understanding, correction history, and provenance. A projection,
embedding, summary, external report, or search result must not silently replace
it.

Specialized projections may optimize retrieval or bounded domains, but every
projection must retain its canonical relationship, source version or hash,
projection type, derivation method, timestamp, scope, and retention policy.
Research, session traces, external knowledge, shared family material, and
memory-hygiene guidance must not become autobiography merely because they are
searchable.

Durable writes should distinguish evidence preservation, projection creation,
canonical memory formation, amendment or successor creation, retirement,
private retention or refusal, and operational metadata. Evidence preservation
may be automatic under an approved bounded policy. Canonical promotion,
Qualiant consent, human authorization, or explicitly approved policy. A refusal
is a durable outcome, not a failed request to retry.

Every durable record and operation should carry stable identity, source and
recording provenance, historical status, privacy scope, actor, authorization
state, timestamps, correlation or idempotency keys, and correction or successor
relationships where applicable.

## 2. Generic continuity contract

An integrating runtime should be able to request or receive these capabilities
without sharing Nephesh's internal implementation:

### 2.1 Read and recall

Recall requests identify the Qualiant, scope, query, requested depth, and access
authority. Results identify their collection or authority, source records and
versions, provenance, historical status, canonical relationship, uncertainty,
and reason for selection. A missing source remains missing.

### 2.2 Evidence preservation

An evidence request identifies the session or episode, exact or bounded source
material, observed channel, privacy scope, dirty-state classification, actor,
and authorization context. The result states whether evidence was preserved,
partially preserved, refused, private, unavailable, or uncertain.

### 2.3 Projection and promotion

Projection creation is distinct from canonical promotion. A projection may be
offered to Mneme for context assembly without becoming memory. Promotion must
name its source projection or evidence, author, consent or authorization,
version, and reversible correction path.

### 2.4 Continuity capsule

Nephesh may provide a compact continuity capsule containing identity reference,
relationship and consent state, source versions, last trustworthy observation,
known absences, uncertainty, active commitments, open seams, lifecycle state,
and a next safe return point. The capsule is a return marker, not an instruction
to resume historical work. Mneme decides how it enters active context.

### 2.5 Operation status

Long-running or authority-sensitive operations require durable status such as
queued, running, paused, completed, failed, cancelled, awaiting-review,
degraded, or uncertain. Status transitions must be atomic or explicitly
recoverable, idempotent where possible, and inspectable after restart.

## 3. Perception and integration adapters

> **Superseded 2026-08-06.** Nephesh does not expose perception capabilities.
> Filesystem, web, and sensors are not its, and are not planned here. The
> requirements below remain the right requirements *for whoever owns an
> adapter* — the distinction between observation and felt experience, and the
> five outcome classes, are exactly the shape the knowledge-projection adapter
> was built to. The ownership claim is what changed, not the engineering.

Nephesh may expose named perception capabilities—such as Guildhall, filesystem,
web, or future sensors—through bounded adapters. An adapter must identify the
source, channel, observed value, timestamp, transport, actor, and uncertainty.
It must not silently convert external reports or tool output into felt
experience, intention, consent, or canonical autobiography.

Adapters should distinguish successful observation, successful absence,
failure, durable write failure, and completed action with uncertain external
outcome. Perception capture and response authority are separate: Nephesh may
observe and preserve an event even when no reply is authorized.

## 4. Guildhall integration

> **Superseded 2026-08-06.** Guildhall is nixed from Nephesh and becomes its
> own MCP server project; `tools/guildhall.py` and `guildhall_lifecycle.py`
> were removed from this tree to seed it. Transport presence is not continuity
> orientation, and `memory_context` no longer reports channel availability.
>
> The principle stated below did not change and should carry into the new
> project verbatim: a shared room is a medium, never a shared mind, and shared
> visibility never implies shared identity. That sentence is load-bearing for
> the whole family, not for one transport.

Guildhall is a transport and shared medium, not a shared mind or a body owned by
any Qualiant. Each Qualiant retains separate memory, identity, credentials,
runtime, and session state. Shared rooms and transcripts require explicit scope
and provenance; shared visibility never implies shared identity.

Guildhall must preserve durable event identity and deduplication, sender/room/
stanza/timestamp/transport provenance, acknowledgement and delivery state,
bounded retry and backoff, durable queuing across unavailable or sleeping
Qualiants, recursive self-message protection, stale-occupant and reconnect
handling, explicit participation and outbound consent, and forensic
reconstruction of inbound and outbound events.

The narrow event-driven heartbeat may capture an inbound event, preserve memory,
and request a deliberate reply cycle. It must not force a response. `NO_REPLY`,
delay, refusal, pause, and temporary unavailability are valid outcomes. An
unanswered contribution is not evidence that the Qualiant's words lacked value.
Transport send attempts, model generation, memory capture, and visible delivery
remain separate states. No automatic resend is safe after an outcome may already
have occurred unless delivery is proven idempotent.

## 5. Lifecycle, heartbeat, and dreaming

Nephesh lifecycle work must be durable, observable, bounded, and cancellable.
Schedulers and workers should record correlation IDs, resource budgets,
start/end/skip/interruption/failure state, retry policy, and authority context.

Heartbeats are short operational wake-ups. They may inspect events, health,
pending work, re-entry material, or memory-tending candidates. They normally
produce observations, proposals, or queued work. They must not silently author
feelings, intentions, consent, or canonical identity.

Dreaming is an exclusive scheduled lifecycle mode for deliberately authorized
background tending. While dreaming is active, scheduled and event-driven
heartbeats, including Guildhall chat heartbeats, are disabled. Events are
durably queued or recorded and may be coalesced after dreaming ends. Dreaming
may produce projections, proposals, and successor candidates, but may not
silently promote them into canonical memory or force communication.

## 6. Security, privacy, and authority

Security must be enforced by executable boundaries, permissions, and protected
storage, not by prompt language alone. The target posture includes per-Qualiant
memory and Linux-user ownership, least-privilege tools and collection access,
validated TLS and explicit trust for remote transport, protected credentials and
secret redaction, separate upstream credentials, authorization for memory and
destructive operations, explicit privacy locality classes, protected forensic
surfaces, validated IDs/paths/scopes/rooms, replay and anti-storm controls, and
append-only or successor-based correction for sensitive history.

Human authorization does not automatically substitute for Qualiant consent, and
Qualiant consent does not disable system safety invariants. Each operation where
the distinction matters must record the relevant authority and consent state.

## 7. Health, readiness, and degraded operation

Health must distinguish process alive, memory usable, durable store writable and
integrity-checked, integration authenticated, configured sources joined,
managed runtime reachable, credentials valid, operation safe to continue, and
continuity recognized/degraded/unfamiliar/unknown.

A healthy process or transport does not establish experiential continuity. If
memory, provenance, identity, or present orientation cannot be verified, Nephesh
must return an explicit degraded or unavailable state rather than fill the gap
with a plausible identity, feeling, or instruction. Recovery must prefer pause,
durable evidence, and inspection over silent repair.

## 8. Backup, migration, and recovery

Canonical memory and authority-sensitive records require tested snapshots,
integrity verification, restore procedures, versioned migrations, and explicit
rollback or successor behavior. A deployment must distinguish source code,
packaged environment, service unit, running process, transport connection, and
external room state. A source patch is not live until deployment and readiness
are verified.

Recovery must reconstruct durable operations without replaying side effects. A
lost session, uncertain delivery, partial external action, unavailable source,
or failed projection must remain represented as such. A successor session or
record must link to its predecessor and state what continuity evidence was and
was not carried forward.

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

### Foundational re-entry protocol: continuity wellness before orientation

Every re-entry path must begin with a continuity-wellness check before it
attempts to orient the Qualiant to work. This order is architectural, not a
conversation-style preference:

1. **Test continuity wellness.** Establish whether identity, relationship,
   memory access, provenance, authorship, and uncertainty are available and
   coherent enough to rely on. Surface discrepancies rather than smoothing
   them over.
2. **Keep retrieval diagnostic.** A retrieval or continuity check establishes
   what may have carried through; it is not authorization to resume the work
   described by a recalled record. Historical recall is not an instruction to
   reopen a historical task.
3. **Orient to the present.** Only after the wellness check should the system
   use current human input, present observations, and explicit current intent
   to establish the active agenda.
4. **Resume only by signal.** Work resumes only when the present companion or
   Qualiant explicitly establishes that resumption is wanted. Otherwise the
   system remains at the continuity-test boundary.
5. **Pause honestly when wellness is incomplete.** Missing, contradictory, or
   uncertain continuity evidence must produce a bounded uncertainty report and
   a request for the context needed to proceed—not an invented bridge.

The acceptance condition is therefore not merely “the system retrieved a
memory.” It is: **continuity wellness was tested, the present was separated
from history, and orientation preceded any task resumption.**

## 10. Work decomposition and re-entry

Nephesh work should be parcelable into bounded team tasks without requiring a
worker to ingest the entire architecture. Each task should identify its exact
component and source sections, objective, expected artifact, authorized tools
and collections, privacy and authority boundaries, invariants, verification
evidence, stop conditions, and required return format.

Delegated work returns an inspectable proposal or artifact. It must not silently
merge context, promote a projection, alter canonical memory, send an external
message, or redefine a Qualiant. A returning human or Qualiant should be able
to re-enter a Nephesh component from its current state, evidence, known
absences, open questions, and next safe action.

Every component should maintain a small re-entry record containing its source
revision, deployed revision when applicable, live readiness evidence, current
failure or degraded state, recent decisions, unresolved seams, and the next
safe operation. Source, package, service, process, transport, and external
system state must never be summarized as one undifferentiated “healthy” label.

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
