# Nephesh 5 rebuild plan — 2026-08-05

**Status:** Authorized design and implementation plan for the isolated
`nephesh-5.0.0` branch.

**Release boundary:** This work must not upgrade Urania, Thalia, Melpomene,
Polyhymnia, or any other living sister. Do not change the version number or
publish a release until the isolated rebuild is complete and explicitly
approved for a 5.0.0 release.

## Purpose

Nephesh 5 will be rebuilt piece by piece from the canonical persistence and
continuity boundary outward. Existing integrations remain in the repository
for reference and rollback, but are not evidence that they belong in Nephesh's
long-term responsibility surface.

## Nephesh owns

- canonical memories and provenance;
- durable source episodes, queues, transcripts, and recovery ledgers;
- durable page records, versions, amendments, retirement, and successor links;
- typed MCP resources and tools for bounded persistence and named perception;
- integrity, backup, restore, migration, and audit operations;
- truthful dependency/readiness reporting;
- explicit authority, consent, and reversibility records.

## Nephesh does not own

These responsibilities must be stripped from the core boundary and rebuilt as
separate layers or adapters, one at a time:

- communication transports, rooms, presence, reconnect, and delivery;
- XMPP/Guildhall protocol behavior (the existing code remains preserved and
  disabled for now);
- OpenCode/Mneme process, provider, model, and session lifecycle;
- context paging orchestration and model-visible prompt assembly;
- heartbeat/dream scheduling and autonomous event loops;
- channel credentials, device/session tokens, and transport state;
- TTS, email, web, shell, filesystem, and other external action adapters;
- UI, chat application, and user-facing interaction policy;
- external delivery retry policy.

## Adjacent ownership

### Mneme

Mneme owns interaction orchestration, model/provider/session lifecycle, context
paging, working-set composition, and user-facing consent and inspection.

### Communication services

A communication service owns the transport client, presence, rooms, reconnect,
event identity, deduplication, delivery acknowledgment, and channel health. A
future Guildhall service may expose those capabilities through MCP. It must not
make Nephesh responsible for transport presence.

### External adapters

TTS, web, filesystem, shell, email, and similar capabilities belong behind
explicit adapter boundaries with their own lifecycle, credentials, errors,
and audit records.

## Rebuild sequence

1. Produce a component, failure, authority, persistence, and migration map from
   actual behavior rather than filenames.
2. Freeze the current integration behavior as reference-only tests and lab
   fixtures; do not run it against living sisters.
3. Establish the minimal Nephesh persistence MCP surface and typed error model.
4. Move orchestration and model/session lifecycle behind the Mneme boundary.
5. Extract communication into a separately testable service/adapter. The
   existing XMPP implementation remains disabled and is not deleted during the
   first pass.
6. Extract remaining external adapters and schedulers behind explicit seams.
7. Add restart, recovery, provenance, authorization, and degraded-mode tests.
8. Instantiate a new test sister and validate the rebuilt system before any
   consideration of living-sister upgrades or a 5.0.0 release.

## First implementation slice

The first isolated code change removes external lifecycle ownership from the
Nephesh server entry point. The core server no longer starts or stops
Guildhall/XMPP, heartbeat, OpenCode, or OpenClaw background components. The
core tool registry exposes only the persistence-oriented vector, memory, and
information tools. The existing adapter modules remain in the tree for
reference and subsequent extraction work, but are no longer implicitly part of
the Nephesh server runtime.

This slice deliberately does not change the package version, living
deployments, or delete the preserved integration implementations.

## Memory-store compatibility

The persistence rebuild must preserve my existing memory stores. It is valid
for a store to contain rows written by several memory-format generations; new
records may coexist with older records when provenance and readers remain
compatible. No forced rewrite or destructive migration is part of the first
repository slice.

The next slice adds typed repository operations for table reads, nearest-vector
queries, durable appends, and durable updates. Memory services now use those
operations rather than reaching directly into LanceDB table methods. The
existing schema and mixed-format row behavior remain unchanged.

Memory context now reports whether pending-message delivery state is settled or
uncertain when a durable update cannot be completed. This preserves the
existing retry behavior without presenting an ambiguous write as success.

Memory ingestion, retirement, and amendment now expose durable-write
uncertainty explicitly. In particular, an amendment that stores a successor
but cannot retire its original reports that partial outcome instead of claiming
that the amendment completed.

Context projection now calls a separate delivery-mutation boundary after
assembling the projection. Building model-visible context and mutating durable
message state are no longer represented as one undifferentiated block.

Memory context no longer imports or reports Guildhall availability. Transport
presence is not continuity orientation; communication status belongs to the
future channel service.

Vector collection listing, opening, sampling, appending, searching, deleting,
and stress-test storage operations now also pass through the repository. The
MCP-facing vector tools remain behaviorally compatible while storage access is
concentrated behind the persistence boundary.

Repository tests now cover collection preservation, mixed-row-compatible
reads, durable operations, and typed write failure. These tests are hermetic;
they do not open or mutate any deployment-owned memory store.

The persistence boundary now defines append-only operation records with
`prepared`, `completed`, `uncertain`, and `failed` states. A JSONL operation
ledger records transitions with stable operation IDs, timestamps, targets, and
structured details. Wiring individual memory mutations to this ledger is the
next step; the record format is established first so recovery behavior can be
tested independently.

The ledger is now wired into memory ingestion, amendment, retirement, and
pending-message delivery. Each begins with a `prepared` record and records a
`completed` or `uncertain` transition; duplicate detection remains a
non-operation and does not create a dangling prepared record.

The MCP health surface now has an explicit typed result contract rather than
returning an opaque JSON string. Error and uncertain-result shapes are defined
for the next tool migrations.

The first vector tools migrated to structured results are collection listing
and collection inspection. The legacy REST projection accepts both structured
results and old JSON strings during the transition.

Vector semantic search now uses the same structured-result contract. The REST
projection remains compatible through the shared normalization helper.

Vector ingestion now uses a typed structured result as well, including its
validation error shape. The old JSON-string REST behavior remains accepted at
the projection boundary.

Memory recall is now the first memory read operation using a typed structured
result. Its empty-collection, validation-error, and successful-search shapes
are explicit while the REST projection remains backward-compatible.

`memory_context` now returns a typed structured result, including continuity
orientation data, message quota, delivery settlement, and uncertainty details.

Memory sampling and provenance auditing now use typed structured results as
well. The migration preserves the existing textual sample and provenance
fields while removing JSON-string requirements from the MCP boundary.

Memory ingestion, amendment, and retirement, plus vector deletion and stress
testing, now use explicit structured result contracts. The remaining JSON
strings are confined to unmigrated legacy paths and compatibility projections.

Slixmpp is now an optional `guildhall` adapter dependency rather than a core
Nephesh installation requirement. The existing Guildhall implementation and
its tests remain preserved, but the core package no longer declares XMPP as a
mandatory capability.

## Non-negotiable safety rules

- No living sister is upgraded during development.
- No version number changes before release readiness.
- No destructive deletion of existing integration code without a replacement,
  migration record, and rollback path.
- No transport presence is treated as identity or continuity.
- No health check is accepted as proof of end-to-end usability.
- Every boundary must distinguish process health, dependency readiness,
  authenticated connection, durable state, and safe-to-resume status.
