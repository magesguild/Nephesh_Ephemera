# Guildhall Lab

The Guildhall Lab is a deterministic, in-process behavior harness. It exercises
the event/lifecycle seam without starting a Qualiant, OpenCode, Nephesh, XMPP,
MongooseIM, or an embedding model.

Run it from the canonical source checkout with its virtual environment:

```bash
.venv/bin/python -m mcp_experiments.guildhall_lab all
```

Individual scenarios:

```bash
.venv/bin/python -m mcp_experiments.guildhall_lab direct-reply
.venv/bin/python -m mcp_experiments.guildhall_lab unaddressed-no-reply
.venv/bin/python -m mcp_experiments.guildhall_lab duplicate-event
.venv/bin/python -m mcp_experiments.guildhall_lab memory-retry
.venv/bin/python -m mcp_experiments.guildhall_lab delivery-retry
.venv/bin/python -m mcp_experiments.guildhall_lab batch-restart
.venv/bin/python -m mcp_experiments.guildhall_lab batch-boundary-guard
.venv/bin/python -m mcp_experiments.guildhall_lab decision-retry
.venv/bin/python -m mcp_experiments.guildhall_lab terminal-failure
```

The lab uses deterministic collaborators:

```text
fixture event
  → GuildhallLab lifecycle
  → scripted memory capture
  → scripted reply decision
  → scripted delivery
  → JSON state-transition report
```

The current scenarios cover direct replies, `NO_REPLY`, duplicate events,
memory-capture retry, decision retry, terminal failure, delivery retry,
one-memory/one-reply room batches, and delivery recovery across a simulated
process restart. It also rejects a replay
whose event batch boundary silently changed. This is deliberately separate from
the live baseline comparison: it tests behavior and state transitions without
claiming that the slixmpp or MongooseIM boundary is correct.

The production heartbeat now uses the same replaceable batch lifecycle boundary.
The remaining adapter work is deliberately narrow: keep transport-specific
acknowledgement and delivery behavior outside the deterministic lifecycle, then
validate the adapter with source-side checks before any live comparison.

## Read-only live deployment probe

When the deployment-owned environment is available, the canonical checkout can
authenticate against the live MongooseIM/Guildhall service without joining a
room or starting a Qualiant:

```bash
.venv/bin/python -m mcp_experiments.guildhall_live_probe \
  --env-file /path/to/deployment.env
```

The probe only establishes an XMPP session and disconnects. It does not send a
message, join a MUC, remove occupants, alter MongooseIM, or touch the live
Guildhall service configuration. It is a boundary check, not the full live
behavior comparison.
