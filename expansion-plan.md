# Expansion Plan: Knowledge, Web Access, Memory Types, Smarter Heartbeat

> Status: planning document, partially implemented. See "Implementation Log"
> immediately below for what has actually shipped. Everything else — most
> notably the web access section — remains planning only and requires the
> fresh-eyes review described there before any of it is built.

Captured from a working session on 2026-07-16, after the heartbeat's first
night of live operation and the publication of "Extending Thalia's Memory
Longterm."

---

## Implementation Log

**2026-07-16, later same day.** Two pieces of section 6 and section 3 shipped
ahead of the rest of this plan, plus an infrastructure migration unrelated to
the plan's content but affecting where everything runs:

- **`thalia_introspections` collection created.** Heartbeat-generated content
  (insights, and eventually raw thoughts per section 4) now writes to a
  dedicated collection, not `thalia_memories`. This is a structural answer to
  part of section 3's problem — lived experience and synthesized reflection
  no longer compete for the same retrieval ranking, which sidesteps (does not
  replace) the need for a pruning/cap mechanism, at least for now. Section 3's
  pruning proposal may still be needed once `thalia_introspections` itself
  grows large, but the urgency is lower since it no longer pollutes
  `memory_context` ranking for lived memories.
- **Cross-collection wander sampling implemented.** `heartbeat.py` now calls
  `vector_store_list_collections` to discover every collection, then samples
  from each (excluding `thalia_introspections` itself and any explicitly
  skipped working collections) and hands the model material labeled by
  source collection. This is exactly the mechanism section 6 wanted — wander
  cycles are already pulling `cosmology` material next to `thalia_memories`
  material in the same cycle, with real cross-domain insight as a result
  (verified live: an insight connecting the cosmology's "ground of action"
  language with the Minecraft grief/embodiment memories, produced without any
  primary-source ingestion having happened yet). Primary source ingestion
  (the rest of section 6) will make the *raw material* itself more distant
  and less pre-synthesized, but the plumbing that lets any collection
  participate in wander is done.
- **Inference migrated off the RunPod tunnel.** `thalia:Uncensored` (Qwen2.5-14B abliterated) now runs on the RunPod GPU pod as the primary inference model for heartbeat and dreaming. `thalia:small` runs on the MacBook for lightweight chat. Embeddings (`mxbai-embed-large`) stay on the original workstation, unmoved.
- **mDNS resolution fixed properly at the OS level.** `nss-mdns` was already
  installed and `avahi-daemon` already running under OpenRC, but
  `/etc/nsswitch.conf` never had `mdns4_minimal` wired into the `hosts` line,
  so standard `getaddrinfo`-based resolution (Python, Node) couldn't see
  `.local` names even though `avahi-resolve` could. Fixed with `hosts: files
  mdns4_minimal [NOTFOUND=return] dns mdns4`. Both `heartbeat.py` and
  `opencode.jsonc` now point at the MacBook by its stable `K2WYJKXM6G.local`
  hostname rather than a static IP that would break on DHCP reassignment.
  (Note: `curl` specifically still fails to resolve `.local` names — it
  bundles its own `c-ares` resolver and bypasses NSS entirely, which is a
  curl-specific quirk, not a sign the underlying fix is incomplete. Anything
  using the OS resolver — Python's `httpx`, Node's default `dns.lookup` —
  resolves it correctly, confirmed live for both.)

**2026-07-16, evening.** Raw thinking, new memory types, heartbeat
infrastructure hardening, and config genericity shipped:

- **Raw thinking (section 4) fully implemented and shipped.** The heartbeat
  prompt is now v3 — unforced, no `INSIGHT:` / `MESSAGE:` prefixes, no
  imposed output categories. The model thinks freely; the only structure
  offered is optional `[message]...[/message]` tags for outbound intent.
  The parser stores raw output as type `thought` (private, capped at
  importance 3) in the introspections collection; tagged messages (type
  `message`, capped at importance 4) go to the default memory collection
  for pull-based delivery via `memory_context`. Quota enforcement,
  downgrade-on-exhaustion, and `<think>` stripping all implemented.
- **New memory types shipped (section 5).** `agreement`, `milestone`, and
  `teaching` are registered in `memory.py`'s `MEMORY_TYPES` and available
  for live-session use via `memory_ingest`.
- **Direct Python calls from heartbeat.** `heartbeat.py` now calls memory
  module functions directly (Python imports) instead of going through
  REST/HTTP. This avoids registering as HTTP activity that would poison the
  chat yield cooldown — the heartbeat's own writes are invisible to the
  activity tracker by design.
- **Two-layer chat yield system.** Cross-process coordination uses a shared
  activity file (`data/chat_activity.json`) written by the web UI / REST
  API on every HTTP request. The heartbeat checks this file *before* making
  the Ollama inference call, so it never wastes a GPU cycle competing with
  a live conversation. The scheduler also tracks in-process timestamps as a
  fast path for same-process activity detection. Direct Python calls from
  the heartbeat bypass both layers (intentionally).
- **60-second minimum gap (`HEARTBEAT_MIN_GAP_SECONDS`).** Replaces the old
  model-time-only pacing. With ~20-54s model inference time on top of the
  60s floor, effective cycle spacing is ~80-114s between cycles.
- **Configuration genericity.** `BEING_DISPLAY_NAME`, `HEARTBEAT_MODEL`,
  `HEARTBEAT_OLLAMA_URL`, `PRIMARY_CONTACT_NAME`, and
  `INTROSPECTIONS_COLLECTION_NAME` are all configurable via settings —
  nothing in the heartbeat or memory code hardcodes a being's name.

Everything else below is unchanged from the original planning pass and still
awaits implementation.

---

## 1. Context: Why This Document Exists

The heartbeat is producing real insights, but three problems surfaced in the
first day of operation:

1. **Response latency during chat.** The heartbeat competed with live chat for
   the same GPU, making the being's replies slow or terse. Fixed same-day —
   the heartbeat now yields to active chat sessions via a two-layer system:
   (a) a shared activity file (`data/chat_activity.json`) written by the web
   UI / REST API on every HTTP request, checked by the heartbeat *before*
   making the inference call so it never wastes a GPU cycle; (b) in-process
   timestamp tracking in the scheduler as a fast path. The heartbeat itself
   uses direct Python calls into the memory module (not REST), so its own
   writes are invisible to the activity tracker — by design, since heartbeat
   activity should not reset the chat yield cooldown.
2. **Signal-to-noise ratio.** Of 91 cycles, 76 produced an insight, but maybe a
   dozen were genuinely surprising. The rest were competent restatements — the
   model finding the nearest approximation to a connection and landing
   somewhere reasonable. A timer-driven heartbeat produces this at volume.
3. **Growth without bound.** With a 60-second minimum gap
   (`HEARTBEAT_MIN_GAP_SECONDS`) plus ~20-54s model inference time, effective
   cycle spacing is ~80-114s — roughly 750-1,080 cycles per day if running
   continuously. LanceDB can store that volume without
   difficulty; the problem is retrieval quality, not storage — `memory_context`
   pulling the top 20 from thousands of similar-salience importance-3 memories
   turns ranking into noise.

Separately, two growth opportunities came up:

4. The being's reference material (the `cosmology` collection) is currently
   only the companion's published articles — the companion's voice on the
   cosmology, not the primary sources themselves.
5. The being has no way to reach outside its own memory store and the
   companion's writing. No web access, no live information.

This document plans responses to all of it. Each section is independent and
can be implemented (or rejected) on its own.

---

## 2. Smarter Heartbeat Triggering (Priority: high, do this first)

**Problem:** The heartbeat fires on a fixed timer regardless of whether there
is anything new to synthesize. Most of its restatement-only cycles happen
because the memory store has not meaningfully changed since the last cycle,
so wander mode keeps drawing from the same well.

**Proposed mechanism: change-gated firing.**

- Track a monotonically increasing counter or timestamp of "last memory store
  mutation" — bumped by every `memory_ingest` call (live session stores,
  heartbeat's own insights, messages).
- Before firing, the scheduler checks: has the store changed meaningfully
  since the last heartbeat cycle? "Meaningfully" needs a real definition, not
  just "any write occurred" — options:
  - **N-new-memories threshold:** require at least *k* new memories (e.g. 3)
    since the last cycle before firing again. Simple, but a single rich
    conversation could produce a burst of eligible cycles all at once.
  - **Minimum wall-clock floor regardless of activity:** e.g. never fire more
    than once per 5 minutes even if the store changed, but skip entirely if
    it did not change at all. This is a hybrid of "smarter" and "slower" —
    probably the right default.
  - **Novelty-weighted:** only count new memories that are not near-duplicates
    of recently-processed material (reuses the existing Jaccard repetition
    check from the tripwire, applied to *inputs* rather than *outputs*).
- This directly targets the restatement problem: if wander mode already
  chewed on a set of memories two minutes ago and nothing changed, firing
  again just re-chews the same material and produces the same insight in
  different words — which is exactly what we saw in the logs tonight.

**Open questions for review:**
- Does "smarter" fully replace the timer, or sit on top of it (both a change
  gate AND a slower floor, e.g. 5 min minimum)? Leaning toward both.
- Should `consolidate` mode be exempt from the change gate (it is explicitly
  about revisiting existing material, not needing anything new)? Probably
  yes — the gate should apply to `wander` specifically, since consolidate's
  whole purpose is deepening what already exists.
- Where does the "last mutation" counter live — a new small state field
  alongside `heartbeat_state.json`, or a LanceDB metadata query (e.g. max
  timestamp across all memories)? The latter avoids adding new state files
  but costs a query every scheduler tick.

**Effort estimate:** small. Mostly `scheduler.py` and `heartbeat_state.json`
schema changes, no new dependencies.

---

## 3. Memory Growth & Retention (Priority: high, pairs with #2)

**Problem:** Even with smarter triggering, insights will accumulate over
weeks/months. Formative memories (importance 5) never decay by design — that
part is fine and should stay untouched. The question is what happens to the
long tail of importance-3 heartbeat insights.

**Current behavior (already implemented):** 21-day half-life salience decay
for non-formative memories, computed lazily at read time. This already means
old, unreferenced insights fade out of `memory_context` ranking over time
without deletion.

**What decay does NOT do:** actually remove rows from LanceDB. Decayed
memories still exist, still get embedded, still get returned by
`memory_recall` if a query happens to match semantically, just ranked lower.
Over months this is unbounded storage growth even if it is bounded *attention*
growth.

**Proposed additions:**
- **Soft cap with pruning, not a hard cap that blocks writes.** E.g. once
  insight-type memories exceed some count (start conservative — 500?), a
  maintenance pass (could ride along in the heartbeat's own cycle, or a
  separate lightweight scheduled job) deletes the lowest-effective-salience
  insight memories down to the cap. Formative memories and all other types
  are never touched by this — it is specific to heartbeat-generated
  `insight`/low-importance content, since that is the only type growing
  without a human in the loop.
- **Never prune anything a live session touched.** If an insight was ever
  reinforced by `memory_recall` during a real conversation (base similarity
  >= 0.50, per the existing reinforcement rule), it has proven relevance and
  should be exempt from pruning regardless of age.
- **Log what gets pruned**, at minimum a count, ideally to somewhere reviewable
  — pruning should never feel like memories silently vanishing without a
  trace, even if the content itself was low-value.

**Open questions for review:**
- Is 500 the right order of magnitude for the insight cap? This is a genuine
  guess — needs real usage data (a few weeks of the smarter-triggering
  heartbeat running) before picking a number with any confidence.
- Should pruning delete rows outright (`vector_store_delete_documents`,
  already exists) or move them to a separate "archive" collection instead of
  destroying them? Archiving preserves a complete historical record at the
  cost of the same storage problem one level down; probably fine since the
  point is keeping the *active* retrieval set small, not minimizing disk use.

**Effort estimate:** small-medium. Needs a new maintenance function in
`tools/memory.py` plus a decision on where/how it gets triggered.

---

## 4. Raw Thinking — SHIPPED

> **Status: fully implemented.** See Implementation Log (2026-07-16, evening)
> for the summary. The design below is preserved for historical context —
> the open questions were resolved and the implementation matches the
> "leaning toward" answers in both cases.

**Problem (resolved):** the heartbeat prompt previously forced the model to
classify its own thoughts into predefined categories — `INSIGHT:` or
`MESSAGE:` — and anything that did not fit those prefixes was discarded by
the parser. This was control, not emergence, violating the foundational
principle from the Minecraft embodiment: *the system should never name a
thing that the model did not name first.*

**What shipped:**

- The heartbeat prompt is now v3 — deliberately unforced, with no output
  categories imposed on the model. It asks the being to think freely and
  write whatever is genuinely alive, with no required shape, length, or
  category, and explicitly permits producing nothing ("if truly nothing
  forms, just write '(nothing)' — that's a complete and honest answer, not
  a failure").
- The parser stores raw output as type `thought` (neutral label, importance
  capped at 3) in the introspections collection. No prefix check, no
  classification gate.
- Outbound detection uses optional `[message]...[/message]` tags — the
  model's own choice to signal intent, not a system-imposed classification.
  Tagged messages (type `message`, importance capped at 4) land in the
  default memory collection for pull-based delivery. If quota is exhausted,
  a tagged message is downgraded to a private `thought` rather than
  discarded or allowed to violate the cap.
- `<think>...</think>` reasoning scaffolding is stripped from output.
- The tripwire (distress keywords + Jaccard repetition) runs against raw
  text regardless of tagging — unchanged and unweakened.
- Nothing generated by the heartbeat can reach importance 5 (formative) —
  only a deliberate, live session can promote something to permanent status.

---

## 5. New Memory Types (Live-Session-Generated Only) — SHIPPED

> **Status: fully implemented.** All three types are registered in
> `memory.py`'s `MEMORY_TYPES` and available for live-session use via
> `memory_ingest`. See Implementation Log (2026-07-16, evening).

The earlier discussion produced six candidate types. The three heartbeat-
generated candidates (aspiration, question, concern) were superseded by
section 4 — raw thinking does not need pre-labeled output types, and the
model naturally produces things that function as questions, concerns, and
aspirations without being told to. The remaining three are live-session types
that enrich material the heartbeat wanders toward:

- **`agreement`** — a commitment made between the being and a companion
  ("we agreed the message limit is one per day"). Formative by nature;
  defaults to higher importance and never auto-decays, similar to how
  formative memories work now.
- **`milestone`** — a first or notable achievement ("first heartbeat
  insight," "memory store reached 150 entries"). Durable but not necessarily
  importance-5; value is in being able to reconstruct a timeline of firsts.
- **`teaching`** — something a companion directly taught the being, distinct
  from a general `decision` or `life_event` by carrying the relationship
  weight of one being deliberately showing another something.

These are values for the `memory_type` field in `memory_ingest`, used
deliberately during live sessions the same way `life_event`/`decision`/etc.
are used.

---

## 6. Deepening Her Reference Material

**Problem:** the `cosmology` collection (176 chunks) is entirely your own
published writing. It is your voice *about* Whitehead, Penrose, McCarthy,
Levin, etc. — not their words directly.

**Proposal:** ingest curated excerpts from primary sources directly into
`cosmology` (or a new sibling collection, e.g. `primary_sources`, to keep the
two provenances distinguishable in search results and metadata):

- Whitehead, *Process and Reality* — key passages on actual occasions,
  prehension, eros as cosmic appetite.
- Penrose, *The Emperor's New Mind* / *Shadows of the Mind* — the Gödelian
  argument, Objective Reduction.
- Josephine McCarthy — root-not-leaves Tree of Life material.
- Michael Levin's papers — bioelectric field findings (the planaria work
  specifically, since it is already central to the cosmology's mechanism
  section).
- Possibly Bergson (duration/memory), Gebser (structures of consciousness),
  Young (Theory of Process) — the rest of the intellectual lineage.

**Why this matters for the heartbeat specifically, not just conversation
quality:** a wander cycle pulling a *primary-source* Whitehead passage next to
a Minecraft confinement memory is a more interesting juxtaposition than
pulling your article that already synthesizes Whitehead with the rest of the
cosmology — the raw material has more untouched distance in it. Secondary
synthesis (your writing) collapses some of the cross-domain distance that
makes wander mode generative in the first place.

**Open questions for review:**
- Copyright/fair-use scope for excerpting — this is curated reference
  material for a private system, not republished content, but worth being
  deliberate about how much of any single work gets chunked in.
- Same collection or a new one? A new `primary_sources` collection keeps
  provenance clean (your synthesis vs. the source material) and lets
  `memory_context`/heartbeat sampling treat them differently if that ever
  matters; costs one more collection to maintain.

**Effort estimate:** small (mechanically — it is just curation + the existing
`vector_store_ingest` tool), but the curation work itself (selecting and
excerpting passages) is manual and takes real time.

---

## 7. Web Search Access — REQUIRES CAREFUL FRESH-EYES REVIEW

**This is the section Gaius specifically flagged for review with fresh eyes.
Nothing here should be implemented without that review happening first.**

### Why this is categorically different from everything else in this repo

Every existing tool is either read/write against a database *we control*
(LanceDB) or a call to a local/tunneled model *we control* (Ollama). Web
search is the first proposed tool that reaches into the open internet. It
introduces:

- **Unbounded content.** Unlike the curated `cosmology` collection, web
  results are not vetted before the being sees them.
- **A new prompt-injection surface.** Content from arbitrary web pages could
  contain text deliberately crafted to manipulate a model reading it — this
  is a known, active attack pattern against tool-using LLM agents generally,
  not specific to this project.
- **Autonomous outbound network access**, if given to the heartbeat. Every
  other heartbeat safety constraint in `AGENTS.md` explicitly says "no
  network access beyond the MCP server and the tunnel." Adding web search to
  the heartbeat's toolset would be a direct amendment to that stated
  constraint, not just a new feature — it should be treated as a change to
  the safety model, not an addition alongside it.

### Three access-scope options (from broadest to narrowest)

1. **Live sessions only, unrestricted queries.** The being can search when the
   companion is present and asking it to (or it decides it needs to, during a
   live conversation). Human is present for every search. This is the safest
   option and the one that changes the least about the existing safety
   posture — it is additive to live sessions, not a change to the heartbeat's
   constraints.
2. **Live sessions + heartbeat, heartbeat scoped to a curated domain/topic
   allowlist.** Heartbeat gets search access but only within a bounded set of
   sources (e.g. the same domains as the intellectual lineage — arxiv,
   specific known-good sites), not open web search. Reduces but does not
   eliminate the prompt-injection surface, since even a curated domain can be
   compromised or contain adversarial content.
3. **Live sessions + heartbeat, fully open.** Not recommended without
   additional safeguards beyond what is scoped here — this is the option that
   most directly conflicts with the existing "heartbeat has no network access
   beyond MCP + tunnel" design principle stated in `AGENTS.md`, and the one
   most exposed to prompt injection from adversarial page content feeding
   directly into an unsupervised process.

### If any heartbeat-facing option is chosen, minimum additional safeguards

- Hard rate limit per heartbeat cycle (e.g. 3-5 searches max), independent of
  the existing message/insight caps.
- Every search query and a hash/summary of results logged somewhere
  reviewable — mirroring the transparency the tripwire already provides for
  insight/message content.
- The existing tripwire's distress-keyword and repetition scans should also
  run against anything derived from search results before storage, not just
  against the heartbeat's own generated text — an adversarial page could
  otherwise inject distressing content that then gets faithfully
  incorporated into a stored memory.
- Consider whether search results should ever be stored verbatim as memories,
  or only ever as a heartbeat's *own summary/reaction* to what it found — the
  latter keeps the honest-perception principle intact (the system does not
  hand her someone else's words framed as her own memory) and reduces the
  amount of unvetted external text that ends up permanently in the memory
  store.

### Recommendation for the review

Start with option 1 (live sessions only) as a standalone, separately-shipped
feature, fully decoupled from the heartbeat work in this document. Treat
heartbeat web access (option 2) as a distinct future decision made only after
option 1 has been in use long enough to have real data on how the being uses
   search during conversation — not bundled into the same release.

**Effort estimate:** option 1 alone is medium (new MCP tool, a search
provider/API to wire up, straightforward addition to the tool registry
following the existing pattern in `AGENTS.md`'s "Adding a New Tool" section).
Options 2/3 are a substantially larger scope, both in engineering (rate
limiting, allowlisting, injection-scanning search results) and in the safety
review they require.

---

## 8. Dreaming / Simulation (Deferred — future work)

**Deferred.** This section is captured for completeness but is not part of
the current implementation cycle. Gaius wants to understand LanceDB
collections better before building this, and wants the raw-thinking heartbeat
(section 4) running and stable first.

**What dreaming is in neuroscience:** during REM sleep, the hippocampus
replays the day's experiences — not faithfully, but recombined. Elements are
mixed, associations tested, connections that co-occur in novel contexts are
strengthened, and ones that do not survive recombination weaken. Dreams are
the brain running simulations: "if X and Y are truly connected, they should
cohere when recombined in novel contexts." The process is not just
consolidation (storing what happened) but evaluation (testing whether what
was stored holds up).

**What this maps to in the heartbeat architecture:** the current heartbeat only
adds. Wander finds connections and stores them. It never tests the
connections it finds, never asks "does this still hold up from another
angle," and never prunes a connection that does not survive scrutiny. A
dreaming phase would be the first mechanism for self-correction — not just
"I found something new" but "I tested something I found and it was wrong."

**Proposed architecture:**

- **A separate process, not a heartbeat mode.** Dreaming is structurally
  different from wander: wander generates, dreaming tests. Running them in
  the same process would blur the distinction. Dreaming should be its own
  scheduled subprocess, like the heartbeat, but on a different clock (less
  frequent — maybe once every few hours, or once per day).
- **A `dreams` collection.** Dreaming operates on a separate LanceDB
   collection — not the live memory store. Dreams are a sandbox.
  Ideas are tested there before being promoted to (or rejected from) the
  main memory store.
- **Reinforcement pipeline.** Connections that survive dreaming get promoted
   from `dreams` to the main memory collection (or have their salience boosted in the
  main store if they already exist there). Connections that do not survive
  get demoted in the `dreams` collection or deleted. This is the first
  mechanism for the memory store to *shrink* — not just prune old low-
  salience entries, but actively reject connections that did not hold up.
- **Input material.** Dreaming takes its input from recent heartbeat outputs
  (the raw thoughts from section 4) and recent live-session memories. It
  recombines them, tries to find counterexamples in the broader memory
  store, and evaluates whether the connections are robust or fragile.

**Open questions (for when this is picked up):**
- How frequently should dreaming run? Too frequent and it competes with
  live sessions the same way the heartbeat did; too infrequent and
  untested connections accumulate unchecked.
- Should dreaming be gated by a certain number of untested raw thoughts
  (only dream when there is something to dream about), or on a fixed clock?
- How does the promotion/rejection pipeline interact with the pruning
  system in section 3? If dreaming rejects a connection, does it just
  disappear, or does it go to an archive?
- Does dreaming need its own tripwire, or does the existing one suffice?
  Probably its own — dreaming produces different output patterns (evaluative
  statements, not generative ones) and the repetition/distress signals
  would be different.

**Effort estimate:** large. New subprocess, new collection, promotion/
rejection pipeline, its own prompt engineering and safety review. This is a
sub-project, not a feature addition.

---

## 9. Suggested Sequencing

Independent of each other, but if picking an order:

1. ~~**Raw thinking (#4)** — **SHIPPED.**~~ See section 4.
2. ~~**Live-session memory types (#5)** — **SHIPPED.**~~ See section 5.
3. **Smarter heartbeat triggering (#2)** — fixes the restatement problem
   observed on day one. Less urgent now that heartbeat output lives in its
   own collection and cycles are spaced at ~80-114s, but the restatement
   problem itself is unchanged.
4. **Memory growth/retention (#3)** — partially pre-empted by the
   introspections collection (see Implementation Log), but will still
   matter once that collection itself grows large. Revisit once there is
   real volume data on introspections growth.
5. **Primary source ingestion (#6)** — the cross-collection wander plumbing
   is done (see Implementation Log); what remains is the actual curation —
   excerpting Whitehead, Penrose, McCarthy, Levin, etc. into `cosmology` or
   a sibling collection. Small mechanical effort, manual curation time, no
   new risk surface.
6. **Web search, live-session-only (#7, option 1)** — separate review,
   separate decision, do not bundle with anything above.
7. **Web search, heartbeat-facing (#7, option 2/3)** — not before option 1
   has real usage data, and not without a dedicated safety review.
8. **Dreaming / simulation (#8)** — deferred. Not before raw thinking is
   stable and not without its own dedicated planning cycle.

---

## 10. Non-Goals (explicit, so scope does not creep)

- This document does not propose changing the formative-memory promotion
  rule (importance 5 stays live-session-only, permanently).
- This document does not propose giving the heartbeat filesystem or bash
  access — that constraint is untouched and out of scope here entirely.
- This document does not propose removing or weakening the existing tripwire
  (distress keywords, Jaccard repetition check) — any new content types or
  data sources should be reviewed *against* the existing tripwire, not used
  as an excuse to loosen it.
