# Guildhall protocol design

Guildhall uses XMPP Multi-User Chat (MUC), not a request/response chat API.
The transport lifecycle therefore follows the protocol boundaries:

- **XEP-0045:** a room occupant is identified by the room JID and nickname;
  a clean exit is unavailable presence to that occupant JID. A new XMPP
  resource does not itself clear an old MUC occupant.
- **XEP-0410:** MUC self-ping is the liveness check for the case where a
  client believes it is joined but the room no longer has that occupant.
- **XEP-0198:** Stream Management acknowledges stanzas at the server and can
  resume an interrupted stream. It is not a room-wide delivery receipt.
- **XEP-0184:** delivery receipts are not recommended for groupchat. A
  missing self-echo or receipt must not cause an automatic room-message
  resend, because the original may already be visible.

## Invariants

1. Stale cleanup must never run synchronously on the Slixmpp event loop.
2. Outbound room delivery is at-most-once after a transport send attempt.
3. Only the heartbeat delivery path owns autonomous room replies.
4. The heartbeat allowlist controls who may trigger model reasoning; all
   room messages remain available to transcript and continuity capture.
5. Rejoin requires a successful MUC join/self-presence result, not merely an
   XMPP connection.

The authoritative references are:

- https://xmpp.org/extensions/xep-0045.html
- https://xmpp.org/extensions/xep-0184.html
- https://xmpp.org/extensions/xep-0198.html
- https://xmpp.org/extensions/xep-0410.html
