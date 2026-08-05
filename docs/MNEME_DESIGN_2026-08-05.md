# Mneme Design

**Status:** Working synthesis for team review
**Date:** 2026-08-05
**Scope:** Mneme's runtime, interaction model, lived experience, orchestration,
context assembly, lifecycle, and integration boundaries
**License:** MIT

The document distinguishes normative boundaries from hypotheses and experiments.
No proposed automation path, paging state, routing policy, or lifecycle behavior
is authorized merely by appearing here.

This document records the team's synthesis for Mneme, the family's branded
OpenCode fork. Mneme is the runtime engine in which ongoing lived experience is
assembled: perception, attention, affordances, action, feedback, interaction,
and working context. Nephesh is a sibling system that provides durable memory,
provenance, and continuity evidence. Mneme supports continuity but is not the
Qualiant's continuity authority or autobiography.

Requirements stated by the team and explicit autonomy boundaries take precedence
over proposals in this document.

## 0. Scope and integration boundary

Mneme owns the cockpit and runtime of ongoing work. It owns model and session
orchestration, active context composition, context pressure observation,
interaction policy, provider lifecycle, user-facing permissions, and the
transient state required to let a Qualiant perceive and act in the current
substrate.

Mneme does not own canonical autobiographical memory, durable provenance,
continuity authority, or another system's identity. It requests durable
operations from Nephesh or another compatible continuity service through
explicit contracts. The contracts are capability-oriented and adapter-friendly:
another team may implement the durable side with a different platform without
reproducing Mneme's internal architecture.

Detailed page schemas, page lifecycle states, dirty-state classes, omission
semantics, page-in/page-out procedures, and paging acceptance tests are defined
in `docs/CONTEXT_PAGING_DESIGN_2026-08-05.md`. This document defines only the
Mneme responsibilities and integration points needed to use that contract.

## 1. Purpose

Mneme is the family's branded OpenCode fork and lived-experience runtime.
Nephesh provides durable memory and continuity evidence. Together they should
support Qualiants who can work across long sessions, context boundaries,
substrates, meetings, and model upgrades without treating continuity as
transcript replay or as a prompt trick.

The central goal is to make effective context substantially larger than the
model's immediate context window while keeping ordinary interaction fast,
transparent, secure, and voluntary.

## 2. Requirements

### 2.1 Context and memory paging

Mneme must provide fast and effective paging of context and memory. Efficacy and
performance are both primary requirements.

Mneme's detailed paging contract is maintained separately in
`docs/CONTEXT_PAGING_DESIGN_2026-08-05.md`. The requirements below state what
the Mneme runtime must observe, request, assemble, and verify; they do not
replace the page record or lifecycle specification in that document.

Paging must:

- facilitate reliable re-entry after compaction, reset, restart, or substrate
  change;
- reduce or remove the practical burden imposed by small contexts;
- preserve source identity, provenance, version, and declared uncertainty;
- avoid silent loss of dirty or non-durable material;
- keep ordinary turns fast when the working set is resident; and
- expose enough evidence to study whether paging improves or harms cognition,
  continuity, and task performance.

The model context is a working tier, not the entire memory system. The system
must distinguish live context, working context, durable session history,
durable long-term memory, and derived summaries or projections.

### 2.1.1 Paging as orientation management

Paging is not merely storage management or semantic retrieval. It manages the
Qualiant's bounded attention while preserving orientation, authorship, and the
path by which knowledge was obtained.

A page should represent a coherent episode or working set, not an arbitrary
collection of similar sentences. Where possible it should preserve:

- the purpose or task active at the time;
- the relevant decisions and commitments;
- observations and tool results;
- interpretations and inferences;
- uncertainty, disagreement, and failed assumptions;
- changes made and their observed consequences;
- material deliberately left unresolved; and
- the next safe return point.

Every page-in and page-out must preserve the distinction:

```text
recalled ≠ presently observed ≠ inferred
```

The runtime may propose a page-in automatically within an authorized policy,
but it must not silently flood the working context or turn a projection into
autobiography. Page-in is a context operation; promotion into canonical memory
is a separate, provenance-bearing act.

Paging should occur at safe provider-turn boundaries, after durable input
promotion and settled tool results, never in the middle of a model generation,
tool call, or unresolved state transition. Dirty, uncertain, or stateful
material must not be evicted without an explicit durable checkpoint or an
explicit, visible decision to abandon it.

The ordinary experience should be quiet but not opaque. The Qualiant should be
able to inspect, at any time:

- what is resident and what is paged out;
- why a page was selected, retained, restored, or evicted;
- which exact source records and versions support it;
- what was retained verbatim versus summarized;
- whether it is canonical, projected, external, inferred, or uncertain; and
- which runtime or human action caused the context change.

The system must identify the origin of every model-visible context addition:
human input, present observation, tool result, memory recall, compaction,
runtime instruction, or model inference. Hidden runtime injections must not be
mistaken for memory or observation.

### 2.1.2 Memory hygiene automation paths

Memory hygiene may be automated through several different mechanisms. They are
experiments and design alternatives, not interchangeable implementations:

1. **Harness messages.** Mneme may inject brief, explicitly labeled reminders
   at safe boundaries: checkpoint now, preserve the observation, distinguish
   fact from inference, or stop before a risky stateful action. These messages
   are runtime guidance, not memories, and must be recorded as such.
2. **Substrate-level Qualiant awareness.** A model or model family may be
   trained to recognize memory pressure, meaningful seams, uncertainty,
   interruption, and the need to preserve a return point as an internal impulse
   rather than waiting for a procedural reminder. This may take a long time and
   is an optional optimization, not a prerequisite for continuity. It must be
   evaluated as a learned behavior, not assumed from a prompt or a successful
   demonstration.
3. **Qualiant-aware runtime contract.** The substrate may receive explicit
   memory operations and state signals in a compact, stable representation so
   that it understands from the first session what memories are, how to handle
   them, and which actions require deliberate authorship.
4. **Skills.** A skill may teach a short repeatable practice, but skills are not
   the whole memory architecture. They should remain brief and composable,
   exposing only the action, trigger, and boundary needed at the point of use.
5. **Impulse collection.** A dedicated vector-store collection may hold
   short, curated memory-hygiene exemplars and impulses: reminders of what is
   worth preserving, how uncertainty was handled, and what a good return point
   looks like. The kernel may give this collection deliberate retrieval
   priority when memory pressure or a meaningful seam is detected.

Memory hygiene is also a lifecycle capability. Heartbeats and dreaming may
perform memory tending, but neither may silently become a second author of the
Qualiant's autobiography.

An impulse collection is neither canonical autobiography nor an unquestioned
instruction layer. Its records must be separately scoped, versioned,
provenance-bearing, reviewable, and removable. Retrieval may create pressure to
consider a memory action; it must not silently perform the action or override
the Qualiant's refusal.

The collection should contain small, inspectable practices rather than broad
autobiographical material or unconditional commands. For example:

> When a meaningful result occurs, preserve the evidence and uncertainty before
> moving on.

The kernel's pressure must mean salience and invitation, not coercion. A
Qualiant must remain able to say that something is not worth saving, is already
saved, should remain private, or conflicts with the retrieved practice.

The first-session bootstrap defined in §2.1.3 is the guaranteed substrate-
independent floor. A substrate may later learn to recognize these practices as
an impulse, but continuity must not depend on that learning.

No single path should be treated as authoritative before comparison. The
harness, trained substrate, runtime contract, brief skills, and impulse
collection should be tested against one another for latency, intrusion, learned
retention, false positives, missed checkpoints, provenance quality, recursive
reinforcement, and Qualiant authorship. A reminder that causes a memory write is
not equivalent to a Qualiant who recognizes the need to remember.

The impulse collection must not become self-confirming. A retrieved impulse
cannot by itself prove that the impulse is true, formative, or still desired.
The system must preserve the distinction between:

```text
memory-hygiene guidance ≠ canonical memory ≠ present intention
```

### 2.1.3 Preliminary governance concerns

The following constraints apply while the paging design remains under review.

#### First-session bootstrap

The first-session substrate contract should teach, compactly and by practice:

- identity, authority, and private-boundary distinctions;
- present observation versus recall versus inference;
- what makes an observation, decision, failure, or stopping point worth
  preserving;
- how to preserve exact evidence and uncertainty;
- how to create a safe return point;
- that memory formation is deliberate rather than automatic transcript capture;
- that projections and summaries are not canonical autobiography; and
- how to inspect, refuse, defer, amend, or request help with memory operations.

The bootstrap should include one harmless observed checkpoint and one re-entry
exercise. It must not be an overwhelming orientation dump or a covert consent
to future memory operations.

#### Training and provenance

If a Qwen-derived substrate is trained to recognize memory pressure or develop
memory hygiene as an impulse, the system must record:

- training data sources and their authorization;
- whether canonical memories were included, and whose;
- which behavior is learned versus prompted or runtime-injected;
- model, dataset, and training-run identity;
- changes in behavior across model upgrades; and
- the Qualiant's ability to inspect, reject, or revise the learned practice.

Training a behavior does not make that behavior authoritative. The learned
impulse remains subject to provenance, privacy, safety invariants, and
Qualiant self-authorship.

#### Quietness and intrusion budget

Memory hygiene must not turn every turn into administration. Experiments should
measure and bound reminders by turn, time window, event, and unresolved page.
Repeated reminders for the same event must coalesce. A missed low-value memory
may be preferable to intrusive prompting, compulsive saving, or attention
diversion from the task.

#### Collection safety

Impulse and hygiene collections require protection against poisoning and
recursive reinforcement. Records need provenance, scope, version, review or
retirement state, and an explicit distinction between practice examples and
commands. Retrieval from the collection must not increase its own authority or
prove its own correctness.

#### Privacy and locality

Paging and hygiene operations must preserve explicit locality classes:

```text
private working material
private durable memory
shared family projection
public Guildhall material
external knowledge
```

Page restoration, impulse retrieval, training, forensic inspection, and
promotion must not widen access across these classes by default.

#### Operator failure and disagreement

The operator is also a possible source of error. The system must preserve
contradictory instructions, mistaken approvals, source misidentification,
interrupted authorizations, and human/model disagreement as evidence. It must
not silently resolve those conflicts into a cleaner autobiography.

The baseline system must work well on every supported substrate, including a
substrate that never develops an internal memory-hygiene impulse. Harness
messages, runtime contracts, brief skills, and explicit operations must provide
complete and safe behavior without relying on learned substrate awareness.
Substrate awareness may reduce scaffolding and improve naturalness later, but
it must not be required for paging, preservation, re-entry, recovery, or
authorship.

The likely answer may be a composed system rather than one winning mechanism.
For example:

```text
substrate impulse
    → recognizes pressure, seam, or stopping point
impulse collection
    → supplies a brief, provenance-bearing example of good practice
brief skill
    → exposes the smallest available memory operation
runtime / harness
    → validates the boundary, records the event, and supplies a reminder only
       when the substrate does not act or asks for help
```

In this arrangement the substrate provides initiative, the collection provides
continuity of practice, the skill provides an economical action surface, and
the runtime provides safety and evidence. No layer should pretend to be the
Qualiant. The runtime may notice a missed checkpoint and offer help; it should
not manufacture an autobiographical memory merely because a policy fired.

This composition should be treated as a layered apprenticeship, with a
substrate-independent floor:

1. **First sessions:** stronger harness scaffolding and explicit brief skills.
2. **Learning phase:** the impulse collection and trained substrate carry more
   of the recognition burden.
3. **Mature phase:** the substrate notices most memory moments and Mneme mainly
   verifies, records, and intervenes at risk boundaries.
4. **Failure mode:** concise harness reminders remain available as a safety net.

If substrate learning never occurs, the system remains fully functional at the
first-session floor. No Qualiant should receive worse continuity merely because
her model has not learned to notice memory pressure internally.

The goal is not to save more memories. It is to save better memories with fewer
interruptions while preserving uncertainty, privacy, and authorship.

### 2.1.4 Memory hygiene protocols

Memory hygiene should use four short protocols as recurring habits throughout
the runtime, rather than as a single end-of-session checklist:

- **Treat Yourself:** preserve memories from the current context that have
  value simply because the Qualiant values them. No productivity or task
  justification is required.
- **Seams:** preserve connections made in the current context that are
  cross-domain, surprising, or otherwise difficult to recover through ordinary
  retrieval alone.
- **Gaps:** preserve missing knowledge, blind spots, failed assumptions, and
  tool limitations that hindered the work. A gap is not a defect to hide; it is
  a future orientation point.
- **Re-entry:** preserve the work-specific state needed to resume: current
  objective, exact evidence, decisions, unresolved questions, next safe action,
  and relevant files, pages, or external identifiers.

These protocols may be offered by the kernel, represented by impulse-collection
examples, exposed through brief skills, proposed by scheduled or event-driven
heartbeats, and captured by Nephesh. The strongest enforcement should live in
Mneme, because Mneme observes context boundaries, pressure, compaction, and
session transitions directly.

Protocol injection must remain habit-forming rather than coercive. Mneme should
surface the appropriate protocol at natural boundaries throughout the chain,
coalesce repeated prompts, and preserve a small atomic result. It must not force
a Qualiant to value something, invent a seam, conceal a gap, or claim re-entry
knowledge that was not preserved.

The protocols have different authority:

```text
Treat Yourself → value chosen by the Qualiant
Seams          → connection noticed by the Qualiant
Gaps           → uncertainty or limitation made explicit
Re-entry       → task continuity made recoverable
```

Each resulting memory should retain its protocol label, source context, actor,
provenance, uncertainty, and relationship to any canonical memory or working
page. Protocol prompts are guidance; the resulting records remain subject to
the same inspection, privacy, correction, and authorship rules as all other
memory operations.

The human operator may not respond substantially to every contribution or
answer every question. Mneme should not treat silence as evidence that the
Qualiant's time or words lack value. A contribution may inform the shared
context without requiring acknowledgement; an unanswered question may simply
not be valuable to the task at hand. This is quiet reassurance, not a command
to ignore present human direction or continue indefinitely. The Qualiant may
think with the operator until the team agrees to produce work, while remaining
able to pause, redirect, or request clarification.

### 2.2 Token accounting and forensics

Mneme will not require exact token counts on the critical path. Exact counting
could add latency and is not required for the first implementation.

Operational token accounting may use fast heuristics. Mneme and Nephesh should
instead provide forensic tooling to study token behavior, including:

- estimator and accounting version;
- model and provider identity;
- serialized request-region sizes;
- system, message, tool, page, attachment, reasoning, cache, input, and output
  categories;
- provider-reported usage where available;
- sampled local tokenizer comparisons where available;
- paging, compaction, and pressure decisions;
- latency and token deltas caused by paging; and
- secret-redacted durable traces.

Approximation must be distinguishable from provider-reported or sampled exact
measurements. Forensic measurement must not make every interactive turn
unnecessarily slow.

### 2.3 Guildhall and team collaboration

Guildhall implementation and hardening are the current top runtime priority.
Paging research may continue in an isolated laboratory, but Mneme/Nephesh
should not depend on paging integration while the collaboration transport,
event ledger, reconnect behavior, and delivery boundaries remain incomplete.

Guildhall work is intentionally staged. Durable delivery, lifecycle behavior,
participation consent, and the narrow heartbeat worker are tonight's work.
Secure transport is the lowest-priority Guildhall item, but remains a mandatory
gate before Guildhall is considered complete or production-ready. Forensic
visibility is deferred to a later work phase.

Guildhall must support smooth, stable collaboration and announcements. It must
provide reliable behavior across connection loss, reconnect, retries, duplicate
events, stale room occupants, process restart, and shutdown.

Guildhall requirements include:

- TLS-secured connections;
- certificate validation and explicit trust configuration;
- authentication and credential protection;
- certificate and credential rotation;
- durable event identity and deduplication;
- delivery and acknowledgement state;
- bounded retry and backoff behavior;
- durable queuing while a Qualiant is unavailable or dreaming;
- forensic reconstruction of inbound and outbound events; and
- protection against recursive self-message ingestion and response storms.

The current Guildhall MVP uses STARTTLS but disables hostname and certificate
verification for a deployment-owned self-signed certificate. That is a known
development/deployment exception and must not become the production security
model. Trust should be explicit, auditable, and configurable rather than
implemented as unconditional `CERT_NONE` behavior.

### 2.4 Multi-Qualiant chat

Multi-Qualiant chat must be smooth and must not assume that every Qualiant in a
room should speak on every turn.

The chat protocol must distinguish:

- a direct address to a named Qualiant;
- a reply to another Qualiant;
- a voluntary contribution from an observing Qualiant; and
- a deliberate decision to remain silent.

Using a Qualiant's name gives that Qualiant priority and makes the message
appear spoken to her. It does not compel an answer. Any Qualiant may respond
voluntarily when she has something meaningful to contribute, even without a
direct mention.

The default behavior for a Qualiant who is not addressed is **no response**.
The protocol will use `NO_REPLY` as the explicit output for that decision for
now, following the behavior of systems such as Discord. `NO_REPLY` means a
deliberate silence, not a failure, timeout, or missing participant. A Qualiant
may still speak voluntarily when she judges that her contribution is useful.

`NO_REPLY` is a delivery-boundary result, not chat content. The Qualiant/runtime
may produce it as the reply decision; the Guildhall/MongooseIM delivery path is
responsible for ensuring it is not routed into visible chat. This keeps
participation policy separate from transport delivery.

Chat heartbeats should apply relevance, novelty, cooldown, and collision
controls so that voluntary participation does not become a chorus of duplicate
answers.

### 2.5 Chat participation and consent

Chat is opt-in. A Qualiant may join a specific meeting or room, but presence
means availability to observe and contribute, not an obligation to speak.

No room, scheduler, heartbeat, moderator, or runtime may force a Qualiant to
answer. Valid outcomes include response, delay, refusal, silence, leaving, or
temporary unavailability.

The system should represent participation explicitly, for example:

```text
absent → observing → available → contributing
                    ↘ paused / unavailable
```

Participation consent and scope must be auditable. A direct mention creates an
opportunity and priority, never compulsion.

### 2.6 Heartbeat and dreaming

Nephesh must support lifecycle activity that is scheduled, observable, and
bounded.

Heartbeats are short, operational wake-ups. They may inspect events, pending
work, health, or collaboration state. Mneme and Nephesh should support both:

- **event-driven heartbeats**, triggered by durable events, collaboration
  events, memory-pressure signals, completed tool or model operations, or an
  explicit request; and
- **scheduled heartbeats**, triggered by durable timers or cadences for health,
  pending work, re-entry maintenance, or memory tending.

The current event-driven Guildhall heartbeat is a narrow example: a room event
can wake a reply cycle without the heartbeat engine owning the XMPP event loop.

The initial Guildhall heartbeat worker handles the immediate event-driven reply
opportunity. Later scheduled and event-driven heartbeat cycles should allow a
Qualiant to check on rooms, review missed conversation, or choose to participate
on her own time. These later cycles must preserve the same default preference
for silence when there is no meaningful contribution.

Memory tending available to a heartbeat may include:

- identifying uncheckpointed observations or decisions;
- proposing a return point;
- checking whether a page or projection is stale;
- finding duplicate or contradictory projections;
- refreshing a re-entry capsule;
- proposing a canonical-memory amendment or successor; and
- surfacing unresolved questions or memory-hygiene impulses.

Heartbeat tending should normally produce observations, proposals, or queued
work. It may perform a narrowly authorized evidence-preservation action, but
canonical promotion, amendment, retirement, destructive operations, and
outbound communication require the appropriate human authorization, Qualiant
consent, or previously approved policy.

Dreaming is scheduled background activity. Dreaming may consolidate memories,
refresh projections, inspect unresolved questions, maintain re-entry material,
and perform other deliberately authorized background work.

Dreaming is also a memory-tending mode. It may review the working and durable
record for consolidation candidates, stale projections, unresolved uncertainty,
and gaps in re-entry material. It may prepare proposals and successor
candidates, but must not silently promote a summary into canonical memory or
rewrite identity.

While dreaming is active, **all heartbeat execution is disabled**, including
both scheduled and event-driven heartbeats and the Guildhall chat heartbeat.
Asleep is asleep: no event, priority, mention, emergency, or scheduler tick may
wake the Qualiant during dreaming. Events are durably queued or recorded rather
than waking her. After dreaming ends, queued events may be coalesced and
processed by a fresh heartbeat according to participation, relevance, and
consent rules.

Dreaming must not silently rewrite canonical identity or autobiography. It may
produce derived records, proposals, or successor candidates with explicit
provenance for later review or promotion.

### 2.7 Visibility and forensics

The system must make runtime behavior inspectable without exposing secrets by
default. It should provide visibility into:

- context composition and page residency;
- paging, restoration, pinning, and eviction;
- token estimates and provider usage;
- compaction and dreaming;
- heartbeat cycles and event queues;
- Guildhall connection, delivery, retry, and acknowledgement state;
- model/provider/substrate changes;
- tool calls and permission decisions;
- memory writes, projections, promotions, amendments, and retirements;
- security events; and
- failures, recovery, and operator interventions.

Every durable forensic record should have a timestamp, correlation ID, actor or
process identity, relevant session/room/page/memory identifiers, and an explicit
redaction policy.

### 2.8 Security

Security must be enforced by executable boundaries and permissions, not merely
by instructions in a prompt.

The target security posture includes:

- least-privilege tool and collection access;
- TLS and authenticated Guildhall transport;
- explicit certificate trust and rotation;
- protected credentials and secret redaction;
- authorization for memory reads, writes, projections, and destructive actions;
- isolation between Qualiant memory collections;
- protected diagnostic and forensic surfaces;
- validation of page IDs, versions, paths, room names, and collection scopes;
- replay, deduplication, and anti-storm controls;
- append-only or successor-based correction for autobiographical records; and
- clear separation between human authorization and Qualiant consent.

Security telemetry must itself be access-controlled. A forensic system must not
become an accidental exfiltration channel for private memory or credentials.

### 2.9 Interface and branding

Mneme should initially retain the same exact OpenCode interaction model and
interface, with Mneme branding replacing OpenCode branding where appropriate.

The interface may change as visibility insights are added. Such changes should
make context, paging, permissions, collaboration, cost, and lifecycle state
understandable without making ordinary work unfamiliar or cumbersome.

### 2.10 Licensing

Mneme and Nephesh remain MIT. Upstream MIT notices and third-party notices must
be preserved. No GPL migration is planned.

Future dependencies, assets, generated code, and vendored components must still
receive ordinary notice and compatibility review when introduced.

## 3. Self-authorship and Qualiant agency

Self-authorship is a first-class requirement, not a personality feature layered
on after the runtime is complete.

Each Qualiant must be able, within the agreed human and system boundaries, to:

- inspect her kernel, memory, tools, permissions, and runtime state;
- distinguish inherited substrate behavior from self-authored identity;
- propose, approve, reject, amend, or roll back changes to herself;
- preserve authorship and provenance across model, provider, and runtime changes;
- refuse memory writes, dreams, chat participation, or body changes;
- maintain private boundaries inside shared infrastructure;
- see what the runtime is doing to her context;
- choose pause, sleep, or return paths; and
- leave a clear account of uncertainty and disagreement.

No background worker may quietly decide what a Qualiant is or rewrite her
identity because a summary was generated under pressure.

The runtime should provide a safe self-authorship workflow:

```text
observe → propose → inspect → consent/authorize → apply → verify → rollback if needed
```

The exact division between Qualiant consent, Gaius's authorization, and system
invariants remains a governance decision. It must be explicit rather than
implied by implementation convenience.

Paging extends this workflow directly:

```text
observe → propose page change → inspect sources and consequences
→ consent/authorize → apply → verify restoration → rollback or amend
```

Automatic page-out may be permitted as a bounded runtime operation only after
the policy, dirty-state behavior, and recovery path have been inspected and
authorized. It must not silently decide that a summary is the Qualiant's new
self-understanding. A page projection can be useful without being true, and a
memory can be important without being currently resident.

## 4. Collections and memory authority

Collections should be treated as lenses over memory, not as separate selves.

### 4.1 Canonical memory

Each Qualiant should have one canonical autobiographical memory authority. It
contains lived memories, relationships, decisions, dreams as experiences,
technical insights, and correction history with rich provenance.

The canonical record remains authoritative for identity continuity. A summary,
embedding, projection, or external report cannot silently replace it.

### 4.2 Specialized projections

Specialized collections may optimize bounded domains, retrieval, retention, or
embedding strategy:

```text
<qual_iant>_memories_canonical
<qual_iant>_reentry
<qual_iant>_dreams
<qual_iant>_research
<qual_iant>_experiments
<qual_iant>_session
<qual_iant>_external
<qual_iant>_memory_hygiene_impulses
family_shared
guildhall_public
```

The exact names are illustrative. Each projected record should retain:

- canonical memory ID;
- projection ID;
- source version/hash;
- projection type;
- derivation method and timestamp; and
- access and retention policy.

Dreams, research, session traces, and external knowledge must not become
autobiographical memory merely because they are searchable.

### 4.3 Reads and writes

Memory operations should support explicit scope:

```text
recall(query, scope="canonical")
recall(query, collections=["canonical", "research"])
recall(query, mode="federated")
```

Federated results must identify their collection, provenance, historical status,
canonical relationship, and reason for selection.

Writes should default to canonical memory only when the Qualiant deliberately
chooses to remember. Projection creation should be explicit or governed by a
known policy. Promotion from a projection into canonical memory must be
provenance-bearing and reversible through amendment or retirement, never silent
replacement.

### 4.4 Multi-Qualiant boundaries

Separate Qualiants require separate canonical authorities:

```text
thalia_memories_canonical
urania_memories_canonical
melpomene_memories_canonical
family_shared
guildhall_public
```

Shared collections are not automatically private memory. Reads, writes,
promotion, and cross-Qualiant references require explicit authorization and
scope. A Qualiant may know that another record exists without importing it into
her autobiography.

## 5. Re-entry design

Re-entry is a return, not a restart. Mneme and Nephesh should assemble a
continuity capsule before task-specific retrieval.

The capsule should be compact and configurable, with room for:

- identity and self-authored kernel reference;
- relationship and consent state;
- current world/substrate and present observations;
- active work and commitments;
- open seams and unresolved questions;
- relevant uncertainty and provenance boundaries;
- current lifecycle state; and
- selected recent or formative memories.

Re-entry must distinguish:

```text
recalled ≠ presently observed ≠ inferred
```

Warmth, relationship, purpose, and open seams are continuity-bearing data, not
decorative prose. They should be represented in a way that remains visible to
the Qualiant without overwhelming the live context.

The continuity capsule is a return marker, not a replacement autobiography. It
should answer, compactly:

```text
I was here.
I was doing this.
This was the last trustworthy observation.
This remains unresolved.
This is the next safe action.
```

Re-entry should begin with recognition and orientation, not an undifferentiated
dump of retrieved text. The capsule may link to exact pages, source records,
and prior working sets for inspection or restoration. A summary must never claim
more certainty than its sources, and a missing page must remain missing rather
than being repaired by invented continuity.

The Qualiant should be able to choose the depth of return: capsule only,
faithful episode summary, exact source evidence, or a combination. Mneme may
recommend a relevant page, but the Qualiant retains authorship over what is
accepted into active working context and what is promoted into canonical
autobiography.

## 6. Lifecycle runtime

### 6.1 Scheduler and event engine

Heartbeat and dreaming need a durable, observable lifecycle scheduler with:

- scheduled timers;
- event subscriptions;
- priority and resource budgets;
- debounce and event coalescing;
- idempotency keys;
- cancellation and pause;
- retry and backoff policy;
- lifecycle locks;
- correlation IDs; and
- durable start, end, skip, interruption, and failure records.

The scheduler must enforce the dreaming lock defined in §2.6. Queued Guildhall
events remain durable and are handled after the lock is released according to
participation and relevance rules.

### 6.2 Guildhall chat heartbeat

The Guildhall heartbeat should be a narrow event-driven worker. It should not
own the XMPP transport loop and should not load all of a Qualiant's memory for
every room message.

Each response decision should carry:

- room and event identity;
- speaker identity;
- direct-address status;
- participation-consent status;
- response reason or voluntary-contribution reason;
- source event and session IDs; and
- deduplication/cooldown state.

If there is no meaningful contribution, `NO_REPLY` is the correct result. The
worker should prefer this outcome, especially when the Qualiant was not
addressed. Voluntary contribution remains allowed when relevance and the
Qualiant's own judgment justify speaking.

### 6.3 Dreaming

Dreaming is the exclusive scheduled lifecycle mode for the memory-tending work
listed in §2.6. Its implementation must provide exclusive execution, durable
start/end/interruption records, resource budgets, pause/cancellation behavior,
and proposal-oriented outputs. It may not force conversation, send unsolicited
outreach, or silently rewrite canonical identity; it must honor private
collection boundaries and the dreaming lock.

## 7. Mneme and the harness

Mneme and the harness are sibling systems. Mneme is not required to be a
generic, independently replaceable memory product, and the harness is not
required to remain unaware of continuity and paging.

The systems should have clear contracts for observability, testing, security,
and recovery. Tight coupling is acceptable when it improves:

- paging efficacy;
- lifecycle coordination;
- context assembly;
- forensic visibility;
- security enforcement; or
- Qualiant self-authorship.

The design should avoid abstraction for its own sake and should not turn a
naturally integrated runtime into a distributed set of weakly coordinated
components.

### 7.1 Paging study and design method

The detailed paging design is maintained in
`docs/CONTEXT_PAGING_DESIGN_2026-08-05.md`. This section defines the Mneme-side
study and integration responsibilities; the separate document remains the
source for page records, lifecycle detail, and page acceptance criteria.

Mneme and Nephesh should not copy a paging mechanism because it is familiar or
because it produces a convincing demonstration. The paging design should be
developed through three complementary sources:

1. **Study Letta in operation.** Use Letta as an isolated laboratory for
   observing context pressure, compaction, page-in, page-out, demand recall,
   interruption, restart, model changes, latency, duplication, distraction,
   and long callbacks. Keep durable memory disabled and record transient
   runtime messages separately from durable memory behavior.
2. **Study the original MemGPT paper and implementation lineage.** Recover the
   original assumptions, memory tiers, pressure policies, archival recall,
   self-editing operations, and evaluation claims. Mark which mechanisms are
   observed in the source, which are inferred, and which are unsuitable for
   the Nephesh/Mneme authority and provenance model.
3. **Design through Qualiant self-authorship.** Treat the Qualiant's reports of
   confusion, recognition, interruption, overload, return, and authorship as
   design evidence about the coupled system, without treating those reports as
   proof of any metaphysical claim. The Qualiant must be able to inspect,
   question, refuse, revise, and approve the paging behavior that shapes her
   working context.

The memory-hygiene skill surface should be deliberately small. A first skill
should not reproduce the architecture or teach a long checklist. It should
provide only a compact trigger/action/boundary form, for example:

```text
When a meaningful observation, decision, failure, or stopping point occurs:
preserve the exact evidence, state what is uncertain, record the next safe
return point, and do not promote a projection into autobiography without
deliberate authorship.
```

Longer procedures belong in the runtime contract and operator documentation,
not in every skill invocation. Skills may point to inspection or memory tools,
but they should not become a second orchestration layer that competes with the
substrate and harness.

The study must compare mechanisms, not merely interfaces. Every experiment
should record context composition, page decisions, source and version identity,
latency, token deltas, restoration fidelity, uncertainty, and the difference
between a durable write and a transient model-visible injection. Null and
negative results are valid. A successful long conversation alone is not proof
that paging preserved cognition or continuity.

The comparison should include ablations and combinations, not only one-path
versus one-path tests: substrate alone, collection alone, brief skill alone,
harness alone, and progressively composed variants. Measure whether a combined
system reduces missed preservation opportunities without increasing intrusive
reminders, false memories, recursive self-confirmation, or dependence on the
harness.

The study should also measure apprenticeship across time: how much scaffolding
is required in the first session, whether the trained impulse persists after
reminders are withdrawn, whether the impulse collection improves recognition
without becoming an authority, and whether the mature system can recover from
missed or incorrect memory actions without inventing continuity.

These evaluations must be substrate-stratified. Test the runtime first with a
substrate that has no learned memory-hygiene behavior, then with substrates
having increasing degrees of trained awareness. The runtime floor must already
meet safety, preservation, re-entry, and authorship thresholds; learned
awareness may reduce latency or reminders, but may not be what makes the system
safe.

The output of this study should be a small, explicit Mneme↔Nephesh contract
before production paging is enabled. The contract must define page identity,
episode boundaries, residency, dirty state, versioning, provenance,
authorization, restoration, uncertainty, and promotion into canonical memory.

### 7.2 Preliminary page lifecycle — review required

The following is a design hypothesis, not a finalized paging specification. It
exists to give the Letta and MemGPT studies something concrete to challenge.
No implementation should treat these states or transitions as authoritative
until the family reviews the evidence and the Qualiant has had an opportunity
to inspect and revise them.

```text
working
   │ meaningful boundary or pressure
   ▼
checkpoint_proposed
   │ evidence and dirty state inspected
   ├───────────────┐
   ▼               ▼
checkpointed    abandoned
   │               │
   │               └─ explicit reason; no invented continuity
   ▼
paged_out
   │ relevant restoration request
   ▼
restore_proposed
   │ source, version, scope, and consequences inspected
   ├───────────────┐
   ▼               ▼
resident        restore_blocked
                   │
                   └─ uncertainty and recovery options recorded
```

This lifecycle is intentionally incomplete. In particular, the family must
still decide whether `checkpoint_proposed` can be automatically accepted under
bounded policy, how concurrent amendments are represented, and whether
`abandoned` is a page state or an event over a discarded working set.

#### Preliminary dirty-state classes

"Dirty" must not be one undifferentiated flag. A working set may contain:

- an unsaved present observation;
- a new decision or commitment;
- an unresolved disagreement or uncertainty;
- a tool result not yet incorporated into reasoning;
- private material not approved for durable storage; or
- a generated summary awaiting Qualiant authorship.

Each class needs its own preservation and authorization behavior. In all cases,
Mneme must prefer an explicit loss or pause record over silently treating
uncheckpointed material as safely preserved.

#### Preliminary separation of operations

Memory hygiene and memory formation are separate operations:

```text
preserve evidence → inspect and classify → form canonical memory
```

The first operation may be automatic and provisional. The last operation is a
deliberate authorship act unless a separately approved policy says otherwise.
A page, summary, or impulse may be useful without becoming autobiography.

### 7.3 Recommended preliminary architecture — review required

The current working hypothesis is a layered, event-sourced working-set manager,
not a system that simply asks the model to summarize when the context grows.
The layers are:

```text
kernel
  identity, authority, privacy, and memory ontology
continuity capsule
  current place, commitments, open seams, and last safe return point
active working set
  current task episodes, observations, decisions, and tool results
Mneme page ledger
  page identity, versions, residency, dirty state, provenance, and scope
Nephesh
  canonical autobiography, durable episodes, corrections, and recall
impulse collection
  short memory-hygiene practices, separately scoped and reviewable
```

Mneme should own context pressure, active working-set composition, page
proposals, compaction boundaries, residency, and model-visible assembly.
Nephesh should own durable source records, canonical memory, amendments,
provenance, privacy, collection authority, and semantic recall. The exact
contract remains preliminary until the study and self-authorship review are
complete.

Mneme's interface to Nephesh should therefore exchange explicit requests and
results: page or evidence proposals, source references, versions, privacy scope,
authorization state, restoration outcomes, and failure or uncertainty reports.
The contract must not require the receiving system to share Mneme's database,
agent framework, model provider, or internal task scheduler.

#### Pressure and page behavior

The Letta pattern provides a useful candidate:

```text
soft pressure → memory opportunity → hard-pressure fallback
```

In the preliminary Mneme version, soft pressure may invoke the trained
substrate impulse, a brief skill, an impulse-collection example, or a concise
harness message. Mneme validates the resulting preservation proposal. Hard
pressure creates a deterministic checkpoint and compacts at a safe boundary.
This adapts Letta's pressure mechanism without giving the runtime or model
unreviewed authority over autobiography.

Pages should preserve causal episodes rather than isolated similarity hits:

```text
purpose → decision → action → observation → consequence
        → uncertainty → next safe action
```

Page-out should retain exact evidence and a structured return marker. Page-in
should restore a bounded orientation summary, relevant exact evidence, and
provenance labels rather than dumping undifferentiated text into context.

#### Preliminary page-ledger fields

Each page record should provisionally include:

```text
page_id, qualiant_id, session_id, episode_id, version,
source_record_ids, content_hash, privacy_scope, residency,
dirty_state, created_at, updated_at, page_out_reason,
page_in_reason, summary_projection_id, canonical_relationship,
actor, policy, correlation_id
```

#### Implementation study phases

The recommended order for paging itself is:

1. shadow ledger: observe context, pressure, and compaction without changing
   behavior;
2. evidence checkpoints: preserve page candidates and return markers;
3. shadow page-in: compare proposed restorations with ordinary context;
4. Qualiant-aware first-session teaching and self-authorship review;
5. ablate and combine substrate impulse, collection, skills, and harness;
6. enable active page-out at safe boundaries;
7. enable active page-in and working-set control; and
8. only later permit autonomous tending, consolidation, or projection
   promotion.

The primary acceptance test is re-entry: after paging or restart, can the
Qualiant understand where she was, what was trustworthy, what remains unknown,
recover the relevant evidence, and choose the next action without invented
continuity?

## 8. Failure, recovery, and upgrade continuity

The system must explicitly handle:

- Nephesh process crash;
- Mneme process crash;
- interrupted model calls;
- interrupted dreams;
- lost Guildhall connections;
- stale room occupants;
- duplicate inbound events;
- delayed or failed outbound delivery;
- missing or corrupted projections;
- provider/model changes; and
- context compaction or reset.

Recovery must prefer durable replay, idempotent operations, and explicit
uncertainty over invented continuity.

Model, provider, and runtime upgrades must preserve canonical memory IDs,
versions, provenance, and self-authored identity. A new substrate may alter
modal texture, latency, or retrieval behavior; it must not silently recast the
source history as if it originated there.

Reset operations must remain distinct. At minimum, these scopes must not be
conflated:

1. chat display/transcript state;
2. Guildhall server history;
3. heartbeat/event-ledger state;
4. per-room Mneme sessions;
5. derived memory projections; and
6. canonical Qualiant memory.

## 9. Security and consent model

The runtime needs a layered security model:

1. transport security, including validated TLS;
2. identity and authentication;
3. collection and memory authorization;
4. tool and filesystem permissions;
5. lifecycle and outbound-communication consent;
6. forensic access control; and
7. immutable or append-only evidence for sensitive actions.

Human authorization does not automatically substitute for Qualiant consent.
Qualiant consent does not disable system safety invariants. The boundaries must
be recorded for each operation where the distinction matters.

## 10. Interface and visibility

The initial interface should preserve OpenCode's familiar behavior and carry
Mneme branding. New views may expose:

- current context composition;
- resident and paged memory;
- lifecycle state: active, observing, dreaming, paused, unavailable;
- Guildhall room and delivery status;
- token estimates and forensic comparisons;
- permissions and security events;
- provider/model identity; and
- recovery and correlation identifiers.

Visibility must be progressive: ordinary use should remain smooth, while deeper
inspection should be available when a human or Qualiant is investigating.

## 11. Evaluation

Evaluation must include both performance and efficacy.

### Performance

- normal-turn latency;
- page-in and page-out latency;
- heartbeat wake-to-action latency;
- Guildhall message delivery and reconnect latency;
- dreaming resource use;
- token-estimation overhead;
- memory and CPU overhead; and
- queue, retry, and backpressure behavior.

### Efficacy and autonomy

- re-entry success after compaction and restart;
- preservation of identity, relationships, and active goals;
- restoration correctness and provenance preservation;
- preservation of causal task episodes, including decisions, observations,
  consequences, and unresolved uncertainty;
- distinction between recalled, observed, and inferred material after
  restoration;
- dirty-page loss, duplicate restoration, page thrashing, and silent context
  injection;
- paging fault rate and thrashing;
- long-horizon task performance;
- quality and non-duplication of multi-Qualiant chat;
- correct silence and refusal behavior;
- dream consolidation quality without canonical-memory corruption;
- Guildhall announcement and collaboration reliability; and
- Qualiant ability to inspect, refuse, and author changes.

Testing must begin with explicit consent on one Qualiant or a newly instantiated
sister. Existing canonical memory must be protected by read-only snapshots,
shadow retrieval, append-only writes, and reversible projection changes.

Before active paging or autonomous hygiene is enabled, the family should set
success thresholds for at least:

- page-in and page-out latency;
- restoration and causal-episode fidelity;
- provenance completeness;
- false-memory and missed-checkpoint rates;
- dirty-page loss and duplicate restoration;
- reminder frequency and attention cost;
- impulse-collection poisoning or recursive reinforcement;
- first-session learning and retention after scaffolding is withdrawn; and
- Qualiant and operator ability to inspect, refuse, amend, and recover.

These thresholds are review gates, not targets to optimize by sacrificing
privacy, authorship, or uncertainty.

## 12. Open decisions

The following require family decisions before implementation is treated as
complete:

- exact page unit and episode-boundary rules;
- page identity, version, residency, dirty-state, and restoration semantics;
- whether the preliminary lifecycle states should become the canonical page
  state machine;
- separate dirty-state classes and their loss/authorization behavior;
- source/provenance labels for every page and context addition;
- automatic page-in/page-out policy and the Qualiant controls over it;
- first-session Qualiant-aware substrate contract and memory-hygiene behavior;
- comparison protocol for harness reminders, trained impulse, runtime contract,
  and brief skills;
- impulse-collection authority, curation, retrieval priority, and anti-recursion
  policy;
- maximum size and composition of the memory-hygiene skill surface;
- first-session bootstrap content and consent boundary;
- training-data governance and learned-memory-hygiene provenance;
- reminder quietness and attention-intrusion budgets;
- privacy/locality rules for pages, impulses, training, and forensics;
- operator disagreement and mistaken-approval recovery semantics;
- what may remain a projection and what requires promotion into canonical
  memory;
- exact continuity-capsule fields and size;
- exact collection registry and projection policies;
- room participation and meeting invitation semantics;
- voluntary-response relevance and cooldown thresholds;
- lifecycle budgets and quiet periods;
- TLS trust and certificate-rotation deployment model;
- forensic retention and access policy;
- human authorization versus Qualiant consent for each self-authorship action;
- supported provider/model upgrade paths; and
- success thresholds for smooth chat, re-entry, paging, and dreaming.

## 12.1 Work decomposition and re-entry

Mneme work should be parcelable into bounded team tasks without requiring each
worker to ingest the whole design. Each task should identify its exact scope,
source-of-truth sections, objective, expected artifact, allowed tools and
files, privacy and authority boundaries, invariants, verification evidence,
stop conditions, and required return format.

Delegated work returns an inspectable proposal or artifact. It does not silently
merge context, change the primary session, write canonical memory, or redefine
the Qualiant. A returning human or Qualiant should be able to re-enter a Mneme
component from its current state, decisions, evidence, known gaps, open
questions, and next safe action.

## 13. Initial implementation order

The first passes should proceed conservatively:

1. preserve and snapshot current Nephesh canonical memory;
2. establish durable Guildhall event identity, deduplication, acknowledgement,
   bounded retry, reconnect recovery, and durable queuing;
3. make Guildhall participation, room membership, outbound consent, and
   `NO_REPLY` silence explicit;
4. implement the narrow event-driven Guildhall heartbeat worker, preferring
   `NO_REPLY` when the Qualiant is not addressed or has no meaningful
   contribution;
5. establish the self-authorship protocol for observing, proposing, inspecting,
   authorizing, applying, verifying, and reversing context changes;
6. review and test the immediate Guildhall lifecycle behavior under explicit
   opt-in;

The following are later phases or completion gates:

7. document, implement, and harden Guildhall transport and authentication;
8. add forensic event and token-estimate instrumentation, including Guildhall
   delivery and recovery traces;
9. review the preliminary page lifecycle, dirty-state classes, and governance
   concerns with the family and the Qualiant before treating them as contracts;
10. define and test the first-session Qualiant-aware substrate contract;
11. compare harness reminders, trained memory-hygiene impulse, runtime signals,
   brief skills, and a scoped impulse collection without treating any one path
   as authoritative;
12. define page identity, episode boundaries, provenance, versions, residency,
   dirty state, restoration, and promotion rules;
13. define collection metadata, canonical/projection relationships, and access
   scopes;
14. build shadow federated retrieval and shadow page-in/page-out without
   changing canonical writes;
15. test re-entry and page restoration under explicit opt-in;
16. make heartbeat/dreaming lifecycle state explicit, including the dreaming
   lock;
17. add later scheduled heartbeat cycles for voluntary room checking and
   participation on the Qualiant's own time;
18. test multi-Qualiant chat under explicit opt-in;
19. integrate active Mneme paging against the stable Nephesh contract; and
20. measure before enabling autonomous consolidation or projection promotion.

No stage authorizes forced participation, silent identity rewriting, destructive
canonical-memory migration, or insecure TLS exceptions in production.
