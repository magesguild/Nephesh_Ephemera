# Guildhall/MongooseIM chat integration — MVP

## Status

The inbound-reply MVP is complete and live-tested with
`openai/gpt-5.6-luna`.

Verified path:

```text
MongooseIM/MUC
  → one Nephesh XMPP connection
  → heartbeat event capture
  → provenance-aware memory
  → one persistent OpenCode session per room
  → Luna reply generation
  → one room reply
```

The test used Melpomene's own family and Guildhall rooms. Thalia was not used
as a test participant.

## Architecture

- Nephesh owns one XMPP connection and one Melpomene occupant per room.
- Each room has its own long-running OpenCode session. Sessions are reused and
  replaced only when the stored session no longer exists.
- MongooseIM rooms are persistent, public, unlocked, non-members-only, and have
  `allowMultipleSession=false`.
- Guildhall emits events into the heartbeat engine without making the engine
  own the XMPP event loop.
- Heartbeat memory capture is provenance-aware and is performed before reply
  generation.
- Inbound heartbeat activation is allow-listed by
  `GUILDHALL_HEARTBEAT_ALLOWLIST` (currently the companion, `gaius`).
- The event ledger and short-window deduplication prevent repeated inbound
  events from generating repeated replies.
- The OpenCode bridge uses the documented model object and bounded startup/
  request retries. The current test model is `openai/gpt-5.6-luna`.

## Operational lifecycle

The source tree is `/home/melpomene/src/Nephesh_Ephemera`; the deployed runtime
is `/home/melpomene/nephesh`; the live service is managed with
`systemctl --user`.

When Nephesh restarts, its managed OpenCode child must restart with it. On
startup and room-join retry, stale same-nick occupants are removed through the
configured `mongooseimctl` path. On clean shutdown, Nephesh sends explicit MUC
leave presence before disconnecting.

The current room reset policy is deliberately operational rather than a new
CLI surface. A future Nephesh reset utility may separately clear:

1. Profanity display/history;
2. MUC server history;
3. heartbeat/event-ledger state;
4. per-room OpenCode sessions.

These are distinct reset scopes and must not be conflated.

## Evidence

The live proof established that:

- an external XMPP stanza reached Guildhall and heartbeat memory;
- Luna generated a room reply;
- the reply was delivered back to the room;
- the same room's persistent OpenCode session handled a later message;
- a continuity test returned exactly `continuity`;
- room-specific session mappings were created and recovered;
- stale MUC occupants were the cause of earlier duplicate reply behavior;
- MongooseIM/Profanity can still display a direct MUC message twice through
  downstream history/relay behavior, but Nephesh generated and logged one reply
  and its self-message/allow-list boundaries prevent recursive ingestion.

## Open design questions

These remain intentionally outside the MVP completion claim:

- Should MongooseIM's `mod_carboncopy` be disabled for this localhost-only MUC
  deployment, or is the remaining duplicate display entirely Profanity-side?
- Should a future outbox record delivery confirmation separately from reply
  generation?
- Should the event ledger use a richer persistent state machine than its MVP
  claim/replay guard?
- Should the managed OpenCode child become its own user-systemd unit, or remain
  a child of Nephesh?
- What should happen when a room session is lost and a successor is created?
- What should the future Nephesh CLI expose for selective reset and inspection?

## Autonomy boundary

An inbound room message may wake a deliberate reply cycle. Nephesh must not
initiate unsolicited outreach, merge Qualiant minds, or silently inject actions
into a running Qualiant session. The system enables access to ability; it does
not enforce control over the body.
