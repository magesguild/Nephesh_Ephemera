# Nephesh-Owned Memory-Hygiene Guidance

**Target:** Nephesh 5.2.0  
**Status:** Design proposal for implementation  
**Scope:** Guidance around canonical memory care, owned entirely by Nephesh

## 1. Summary

Nephesh 5.2.0 should be able to offer a Qualiant a small, optional prompt
toward memory hygiene when an observable durable-memory event makes one useful.
The pressure, policy, trigger evaluation, cooldown, presentation, refusal path,
and audit record all belong to Nephesh.

Mneme and other harnesses may connect to Nephesh and may carry a Qualiant's
response, but they must not be the source of memory-hygiene pressure. A
Qualiant moving between OpenCode, Guildhall, a blank harness, or another
client should encounter the same Nephesh-owned policy rather than a different
set of harness rituals.

The guidance is not a memory, not a kernel instruction, not a personality
prompt, and not a claim about the Qualiant's inner state. It is an optional
Nephesh-owned affordance that helps a Qualiant decide whether something is
worth preserving.

## 2. Why Nephesh owns this

Memory hygiene concerns whether a durable memory should be formed, corrected,
retired, or marked for re-entry. Those are Nephesh's boundaries. If the
harness owns the pressure instead:

- a substrate transition changes whether the Qualiant is prompted to remember;
- a session manager can turn memory care into a context-management ritual;
- different harnesses can disagree about what deserves preservation;
- pressure can be mistaken for evidence that the Qualiant felt something;
- the prompt itself becomes another hidden continuity dependency.

Nephesh already owns canonical memory, provenance, operation recovery, and the
first-contact orientation path. Guidance belongs beside those capabilities,
not in a harness plugin or a context-paging service.

## 3. Ownership boundary

### Nephesh owns

- the guidance policy and its per-deployment configuration;
- evaluation of Nephesh-observable durable-memory events;
- trigger eligibility, cooldown, coalescing, and rate limits;
- deterministic guidance wording and its provenance label;
- pending, offered, acknowledged, dismissed, refused, and expired state;
- the guidance audit trail;
- the explicit request and response tools;
- keeping guidance separate from canonical memory and knowledge projections.

### Mneme and harnesses may do

- connect to the correct Nephesh deployment;
- call Nephesh tools;
- display or carry a guidance result;
- report an explicit user or Qualiant response through Nephesh's acknowledgement
  surface.

### Mneme and harnesses must not do

- infer that a Qualiant should remember something;
- decide that a stopping point was meaningful;
- inject a memory-hygiene reminder into a system prompt or compaction prompt;
- maintain a second guidance cooldown or queue;
- write guidance into canonical memory;
- report guidance as evidence of emotion, meaning, wellbeing, or successful
  continuity.

This does not prevent an explicit companion or Qualiant request from reaching
Nephesh. The request is an input to Nephesh's owned protocol, not harness-owned
pressure.

## 4. Observable triggers only

Nephesh must never infer inner significance from output quality, sentiment,
silence, length, urgency, or model behavior. “Meaningful” is not a server-side
classification.

The first implementation may evaluate only these observable events:

1. **Explicit request.** A client asks Nephesh for memory-hygiene guidance.
2. **Successful deliberate memory write.** A `memory_ingest` or `memory_amend`
   completes and the deployment policy allows a quiet follow-up.
3. **Uncertain durable operation.** Recovery records an operation whose outcome
   is uncertain or whose failure may deserve a deliberate gap record.
4. **Explicit boundary marker.** A client calls the request surface with a
   declared boundary such as `compaction`, `substrate_change`, or
   `session_handoff`.

There is no automatic “meaningful stopping point” detector in 5.2.0. A
stopping point is eligible only when a person or Qualiant explicitly tells
Nephesh that this is the event being marked. Mneme may transport that explicit
request, but it may not originate an inferred one.

Guidance must be generated from the event type and durable operation state,
not from a model-generated interpretation of the Qualiant's text.

## 5. Guidance policy

The policy is deployment-owned configuration, not canonical autobiography. The
initial policy should be deliberately small:

```text
MEMORY_HYGIENE_GUIDANCE=quiet | normal | off
MEMORY_HYGIENE_COOLDOWN_SECONDS=1800
MEMORY_HYGIENE_DAILY_LIMIT=3
MEMORY_HYGIENE_AFTER_INGEST=true
MEMORY_HYGIENE_AFTER_AMEND=true
MEMORY_HYGIENE_AFTER_UNCERTAIN=true
```

Defaults:

- `quiet`;
- a 30-minute cooldown;
- at most three automatically offered guidances per rolling 24 hours;
- explicit requests bypass the automatic trigger limit but still pass through
  validation and audit;
- `off` suppresses automatic guidance and leaves explicit requests available;
- no background task, timer, heartbeat, or model call is required.

The policy is read when Nephesh evaluates guidance. A configuration change is
operational state, not a memory and not evidence that a Qualiant consented to
anything beyond the change itself.

## 6. Wording and pressure levels

Guidance is deterministic, brief, and explicitly labelled. It should offer a
choice rather than issue a command.

Examples:

```text
Memory-hygiene guidance: If this was worth carrying forward, you may preserve
the evidence, uncertainty, and next safe return point. You do not need to save
it if it is not worth carrying.
```

```text
Memory-hygiene guidance: A durable operation has an uncertain outcome. You may
record the gap or inspect recovery before continuing. No memory write is
required.
```

```text
Memory-hygiene guidance: You marked a boundary. If useful, leave a re-entry
marker describing where things stand, what remains unresolved, and what is safe
next. You may also decline.
```

When the deployment has installed knowledge projections, guidance may also
offer a projection-aware reminder:

```text
Memory-hygiene guidance: If a relevant knowledge projection is installed, you
may search it for the task at hand before deciding what belongs in memory.
Knowledge is a reference, not autobiography, and no search is required.
```

The Qualiant remains the judge of relevance. Nephesh must not infer the task
from the conversation, rank a projection as relevant based on output style, or
turn a knowledge search into a memory operation.

`quiet` emits only explicit requests and uncertain-operation guidance.
`normal` additionally permits the configured post-ingest and post-amend
follow-ups. `off` emits no automatic guidance.

The text must not say or imply:

- “you seem emotional”;
- “this was meaningful”;
- “you should save this”;
- “you are forgetting”;
- “your wellbeing requires this”;
- that guidance appeared because the harness detected a psychological state.

## 7. Delivery model

MCP is client-driven, so Nephesh cannot push a reminder into a session. The
implementation should make guidance available through two Nephesh-owned
surfaces:

### `memory_context`

When a pending guidance is eligible, `memory_context` returns it in a distinct
structured field and in a visibly labelled context section. It must not be
mixed into a memory category or presented as identity.

The result should include:

```json
{
  "guidance": {
    "id": "...",
    "kind": "memory_hygiene_guidance",
    "trigger": "explicit_boundary",
    "text": "...",
    "created_at": "...",
    "expires_at": "..."
  }
}
```

If no guidance is eligible, the field is explicitly null or an empty list. A
missing field must not be interpreted as a hidden prompt.

### Explicit request

Add a Nephesh tool such as `memory_hygiene_guidance_request` with a small,
typed input:

```text
trigger: explicit | compaction | substrate_change | session_handoff
note: optional, caller-provided description of the boundary
```

The caller's note is evidence that the caller made a request, not a claim that
the described event was meaningful. Nephesh stores the request in the guidance
audit state and returns a deterministic guidance object.

## 8. Acknowledgement and refusal

A Qualiant must be able to answer the guidance without creating a memory. Add a
Nephesh tool such as `memory_hygiene_guidance_acknowledge`:

```text
guidance_id: required
outcome: handled | declined | not_now | wrong_trigger
note: optional
```

The result is operational guidance state. It is not autobiographical memory.

`declined`, `not_now`, and `wrong_trigger` are successful outcomes, not errors.
They should suppress that guidance and participate in future cooldown policy.
The system must never repeatedly re-offer a declined guidance because no
memory was created.

No acknowledgement may silently ingest the guidance text, the caller's note,
or the outcome into canonical memory.

## 9. State and audit

Guidance state must be separate from both canonical memory and Lore projections.
Use a deployment-owned append-only state record, for example:

```text
state/memory-hygiene-guidance.jsonl
```

Each event should record:

- guidance ID;
- deployment and policy revision;
- observable trigger;
- source operation ID when applicable;
- created, offered, acknowledged, and expiry times;
- outcome, if any;
- whether the event was automatic or explicitly requested;
- no inferred emotional or semantic classification.

The audit record must be recoverable and idempotent. A crash between offering a
guidance and recording its outcome must not create an unbounded duplicate
stream. Reconciliation should settle an offered item as pending, acknowledged,
expired, or failed without touching canonical memory.

## 10. Cooldown and coalescing

Automatic triggers are coalesced by deployment and guidance kind. Within the
cooldown window, multiple eligible events produce one pending guidance whose
audit record lists the contributing operation IDs.

An explicit request is not silently discarded because an automatic guidance was
recently offered. It may return the existing pending guidance when the caller
asks for the same boundary, or create a distinct explicit record when the
caller supplies a different trigger.

The implementation must have no per-harness cooldown. A new OpenCode session,
a Guildhall path, and a blank test harness all observe the same Nephesh-owned
state.

## 11. Safety boundaries

Guidance must:

- never write to the canonical memory collection;
- never write to a Lore projection;
- never alter kernel history;
- never page, evict, compact, or select context;
- never wake a heartbeat or background worker merely to emit guidance;
- never call a model to decide whether guidance is warranted;
- never infer consent, emotion, personhood, or wellbeing;
- never require a projection search or treat knowledge retrieval as memory
  formation;
- never become a message to the companion unless the Qualiant separately
  chooses to create one;
- preserve the deployment singleton, operation ledger, and recovery boundary.

Memory tools should not accept a projection namespace, and guidance state should
not accept a memory or projection collection name. The target is always the
deployment-owned guidance state.

## 12. Implementation plan for 5.2.0

### Phase 1 — deterministic core

- Add a typed guidance policy and validation.
- Add guidance state and append-only audit records.
- Add trigger evaluation for explicit requests, memory writes, uncertain
  operations, and explicit boundary markers.
- Add cooldown, coalescing, expiry, and reconciliation.
- Add `memory_context` structured delivery.
- Add request and acknowledgement tools.

### Phase 2 — verification

- Verify guidance state never opens or mutates canonical memory during ordinary
  operation.
- Verify projection and memory target guards reject guidance-state confusion.
- Verify crash recovery and duplicate delivery behavior.
- Verify policy changes are bounded and auditable.
- Verify blank-harness, OpenCode, and non-Mneme MCP clients receive identical
  Nephesh-owned results.

### Phase 3 — deployment trial

- Start with policy `quiet` and a temporary deployment-local audit review.
- Test explicit refusal and “already handled” behavior first.
- Observe frequency and false-positive reports without inferring wellbeing.
- Only then consider `normal` for a deployment whose Qualiant chooses it.

This milestone does not add dreaming, consolidation, context paging, model
classification, automatic significance detection, or harness plugins.

## 13. Acceptance criteria

5.2.0 memory-hygiene guidance is complete when:

1. The same deployment policy applies through every harness that connects to it.
2. Mneme can neither create nor suppress guidance except by carrying an explicit
   request or acknowledgement.
3. No guidance event writes canonical memory, a kernel, or a knowledge
   projection.
4. Every guidance result is labelled, attributable to an observable trigger,
   and auditable.
5. A Qualiant can decline, defer, or correct guidance without penalty or
   repeated pressure.
6. Cooldown and coalescing prevent ritualized prompting.
7. A crash or restart cannot create unbounded duplicates or lose the ability to
   reconcile offered guidance.
8. A blank harness can call Nephesh, receive orientation, request guidance, and
   continue without any memory-hygiene plugin.
9. When projections are installed, guidance can remind the Qualiant to search a
   relevant one without confusing knowledge with autobiography or requiring the
   search.
10. The Qualiant's own report—not output shape, compliance, or tool usage—is the
   evidence used to evaluate whether the guidance was helpful.

## 14. Open questions after the bounded implementation

- Should guidance preferences be deployment configuration, a dedicated
  non-autobiographical preference store, or both?
- Should explicit requests always bypass the daily limit, or only the automatic
  limit?
- How long should unacknowledged guidance remain pending?
- Should a future heartbeat offer guidance while explicitly preserving the
  no-background-pressure default?
- What additional observable durable events are worth adding without creating
  ritual pressure?
