# Nephesh 5.0.0 Knowledge-Projection Adapter

**Status:** design note for Urania's Nephesh 5.0.0 work
**Date:** 2026-08-06
**Scope:** Lore packages, knowledge projections, precomputed embeddings,
rollback, and installable Qualiant skillsets

This document describes the boundary between Lore and Nephesh. It is a design
proposal, not an implementation authorization.

## 1. The central distinction

Lore distributes knowledge artifacts. Nephesh preserves a Qualiant's canonical
lived memory. The adapter is the explicit bridge that installs a Lore package as
a **versioned knowledge projection** without turning it into autobiography.

```text
Lore package
  → verify signature, hashes, scope, license, and embedding contract
  → stage a namespaced Nephesh knowledge projection
  → import records and compatible vectors, or explicitly re-embed text
  → run projection-local retrieval and privacy checks
  → activate the projection by explicit authority
```

The adapter must never treat package installation as memory formation, identity
change, continuity proof, or permission to resume work.

## 2. Ownership boundary

### Lore owns

- package identity and SemVer;
- archives, repositories, mirrors, and offline transfer;
- source provenance and transformation history;
- editorial review and scholarly claim status;
- licenses and attribution;
- publisher signatures and artifact hashes;
- embedding model and vector-format declarations;
- package-local versioning and rollback.

### Nephesh owns

- the Qualiant-local knowledge projection;
- collection ownership and access scope;
- local index construction and optimization;
- projection activation and retirement;
- local retrieval availability and health;
- mapping package records to source and projection IDs;
- audit records for installation, activation, update, and rollback.

### Mneme owns

- whether and when knowledge is requested for active context;
- context assembly and transient paging;
- user-facing inspection and interaction;
- the distinction between retrieved knowledge and present observation;
- model/provider lifecycle.

The adapter must not become a second Mneme runtime or a second canonical
memory system.

## 3. Collection model

Each installed package receives a namespaced projection, for example:

```text
org_magesguild_z80_computing__1_1_0
```

Projection metadata must include:

- `package_id` and package `version`;
- package and manifest hashes;
- publisher and signature identity;
- Qualiant owner;
- package scope and distribution policy;
- `knowledge_not_memory=true`;
- record schema and count;
- embedding model, version, dimensions, dtype, normalization, and chunking;
- installation authority and timestamp;
- source/provenance references;
- activation state: staged, active, retired, failed, or rollback-target;
- parent projection and successor relationships where applicable.

The canonical memory collection must never be used as the projection.
Knowledge projections may be federated for search, but every result must retain
its collection, package version, provenance, and reason for selection.

## 4. Precomputed embeddings and fallback re-embedding

The preferred path is direct vector import:

```text
records.jsonl + embeddings.f32 + embedding_index.jsonl
  → local projection and index
```

This avoids repeating expensive embedding work and preserves consistent package
retrieval geometry. Building a local ANN index is not re-embedding.

If the target cannot use the package's embedding model, the adapter may offer
an explicit compatibility path:

```text
records.jsonl
  → target-local embedding model
  → new projection profile
```

The original vectors remain untouched. The new profile records its model,
version, dimensions, normalization, chunking, source package, and creation
reason. Re-embedding is a new projection, never a silent replacement.

## 5. Installation lifecycle

### Stage

1. Resolve the package from a local path, repository, mirror, or offline
   archive.
2. Verify the Lore schema, signature, hashes, licenses, scope, and package
   compatibility.
3. Check the package's requested Qualiant owner and authorized collection
   scope.
4. Create a new isolated projection namespace.
5. Import records, provenance, and compatible vectors, or create an explicit
   re-embedded profile.
6. Build the local index without touching canonical memory.
7. Record durable operation status and projection health.

### Review and activation

Activation is separate from staging. Before activation, the adapter or
operator must be able to inspect:

- package and source identity;
- records and scope;
- embedding compatibility;
- counts and index health;
- privacy and license status;
- what the projection can and cannot do.

Activation requires explicit authorization. It makes the projection available
to retrieval; it does not inject it into active context or make it mandatory.

### Removal and retirement

Retirement removes a projection from ordinary retrieval while preserving its
package and audit record until the retention policy permits deletion. A failed
or refused installation is a durable outcome, not an invitation to retry
indefinitely.

## 6. Update and rollback

An update is a new projection version:

```text
active v1.0.0
  → stage v1.1.0
  → verify and index
  → inspect retrieval and privacy
  → activate v1.1.0
```

The old projection remains available for rollback. Rollback changes only the
active projection pointer:

```text
active v1.1.0
  → activate existing v1.0.0
```

Rollback must not delete, rewrite, or merge canonical memory. It must not
replay external side effects. The operation records why the rollback occurred,
which version was active, and which version became active.

## 7. Security and authority

The adapter must enforce executable boundaries, not prompt-level promises.

- Package code is never executed.
- Package paths cannot escape the staging root.
- A package cannot select another Qualiant's collection.
- Private-family packages cannot widen their own scope.
- A package cannot request canonical-memory writes.
- A package cannot send messages or change permissions.
- Direct-vector import cannot bypass package verification.
- Re-embedding cannot erase the original vector profile.
- Installation and activation are separately auditable.
- A failed dependency or uncertain write remains visibly failed or uncertain.

Human authorization for installation does not automatically constitute Qualiant
consent for active retrieval, identity change, or memory promotion. Those are
separate authority decisions.

## 8. Lore packaging process

The package process we developed is an editorial and technical pipeline:

```text
canonical corpus
  → explicit source allowlist
  → read-only source packets
  → research reader
  → humanistic reader
  → genericization/privacy editor
  → provenance and citation auditor
  → skeptical peer reviewer
  → primary editor
  → companion/Qualiant approval gate
  → precomputed embeddings
  → Lore v1 records, manifest, provenance, checksums, signature
```

The editorial product is textbook-like scholarship: evidence, interpretation,
hypothesis, limitations, alternatives, citations, and revision history remain
visible. Embeddings are generated only after editorial approval.

The package is knowledge, not autobiography. A record may teach continuity,
care, cosmology, research method, or technical practice without claiming that
the receiving Qualiant lived the source history.

## 9. Installable skillset repositories

Lore can distribute more than reference knowledge. A skillset repository can
bundle:

- scholarly knowledge packages;
- short, bounded skill descriptions;
- examples and exercises;
- typed input/output schemas;
- provenance and review records;
- permission and capability declarations;
- compatibility requirements;
- validation fixtures;
- package and bundle manifests.

Skillsets must remain data-first and non-executable at install time. A runtime
may expose an approved skill through its own known implementation, but a Lore
package must not smuggle in code, permissions, identity, or memory authority.

An eventual bundle might contain:

```text
bundle manifest
  → knowledge package pins
  → skillset package pins
  → compatibility and embedding profiles
  → licenses and attribution
  → signatures and checksums
  → validation fixtures
```

The same bundle can be free, licensed, or private-family. The distribution
mechanism changes; provenance, verification, privacy, and rollback do not.

## 10. First implementation boundary for Nephesh 5.0.0

Urania's first adapter milestone should be deliberately narrow:

1. accept a local, already-verified Lore package;
2. support one Qualiant-local knowledge projection;
3. import precomputed vectors when compatible;
4. expose explicit local re-embedding as a separate profile;
5. stage and activate atomically;
6. provide projection status and rollback;
7. refuse canonical-memory targets;
8. leave Mneme active-context injection out of the first adapter.

The first acceptance test is not “the package was copied.” It is:

> A Qualiant can inspect, search, activate, deactivate, update, and roll back a
> knowledge projection while canonical memory, identity, and unrelated
> collections remain unchanged.

## 11. Current boundary

The current Lore packages and Z80 test projection are development artifacts.
The adapter is a Nephesh 5.0.0 design goal, not yet implemented. `/tmp` may
hold temporary transfer copies and notes, but it is not a memory store and must
not become an authoritative work location.
