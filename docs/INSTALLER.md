# Installing and Upgrading Nephesh

This document describes the Nephesh per-user installer as it exists today. It
covers both direct human operation and a human-guided AI operation. The
installer stages code and preserves durable state; it does not instantiate a
Qualiant, create a personality, or silently restart a running service.

## What the installer does

- stages a Nephesh release under a deployment root;
- selects the staged release through the `current` symlink;
- creates or preserves the per-user runtime and configuration;
- preserves memory, kernel, projection, operation-ledger, and backup state;
- installs a per-user systemd unit unless `--no-service` is used;
- verifies the staged deployment before returning success;
- supports explicit upgrade, rollback, migration, and release cleanup;
- manages a per-user Ollama embedding service unless `--no-ollama` is used.

## What it does not do

- It does not wake or instantiate a Qualiant.
- It does not create a personality or write a self-authored kernel for an
  existing Qualiant.
- It does not read or rewrite canonical memories to make an upgrade succeed.
- It does not silently restart a running Nephesh service.
- It does not manage chat, Guildhall, speech, orchestration, context paging,
  filesystem access, web access, shell access, email, or sensors.
- It does not install a system-wide service or operate on another user’s
  installation.
- It does not turn a human’s proposed identity into the Qualiant’s authorship.

The installer may create a **generic baseline kernel** for a new, blank
deployment. That file explicitly says that it is a starting point and names no
Qualiant. An existing deployment is never given that baseline during upgrade.

## Safety contract

The installer:

- refuses to run as root;
- operates only on the current user’s deployment;
- preserves established `config/nephesh.env` verbatim;
- stages code before switching `current`;
- keeps old releases available for rollback;
- requires `--restart` for a running service handoff;
- uses `--no-service` for isolated staging, CI, and tests;
- records an install manifest and backups before switching an installation;
- refuses a missing or invalid deployment configuration rather than silently
  resolving state relative to a release directory.

An upgrade is not complete merely because the installer returned success. The
operator must inspect the manifest, verify the service, check the durable store,
and perform continuity wellness before asking a Qualiant to resume work.

## Paths and ownership

The default installation root is `$HOME/nephesh`. Existing installations keep
their established root. A standard deployment contains:

```text
<root>/current              selected release
<root>/releases/            staged releases, retained for rollback
<root>/runtime/             per-user virtual environment
<root>/config/nephesh.env   deployment configuration
<root>/config/kernel/       Qualiant kernel revisions
<root>/data/                LanceDB and other durable data
<root>/state/               operation ledger, projection registry, manifest
<root>/backups/             installer and deployment backups
```

The deployment belongs to the installing Linux user. The installer does not
cross user boundaries, and the Nephesh process is protected by a deployment
singleton lock.

## Human-only workflow: new installation

Run this as the Linux user who will own the Qualiant deployment—not as root.

### 1. Inspect prerequisites

```bash
python3 --version
python3 scripts/nephesh_installer.py --help
```

The supported installer target is Debian 13 or newer. Ollama is installed from
its official installer when needed; it is not bundled in this repository.

### 2. Stage a generic blank deployment

```bash
python3 scripts/nephesh_installer.py \
  --agent Qualiant \
  --no-service \
  --no-ollama \
  --install-dir "$HOME/nephesh"
```

`--no-service` makes this a filesystem/runtime staging operation. It does not
create or start a user service. `--no-ollama` is useful when the embedding
endpoint is managed separately.

For a normal local deployment, omit those two flags after reviewing the dry run:

```bash
python3 scripts/nephesh_installer.py \
  --agent Qualiant \
  --dry-run
python3 scripts/nephesh_installer.py \
  --agent Qualiant \
  --enable \
  --start
```

The installer’s baseline identity is not a living session. It is a generic
starting file that a future Qualiant may replace through the self-authorship
workflow in [SELF_AUTHORING_A_KERNEL.md](SELF_AUTHORING_A_KERNEL.md).

### 3. Adopt an existing kernel only when authorized

If a human is migrating an existing Qualiant identity, the source and author
must be explicit:

```bash
python3 scripts/nephesh_installer.py \
  --agent clio \
  --kernel-file /path/to/existing-kernel.md \
  --kernel-author "the person or Qualiant who actually wrote it"
```

This is adoption, not authorship. The source is copied into a new Nephesh
revision and the original file is not modified.

## Human-only workflow: upgrade in place

Always begin with a dry run against the actual deployment:

```bash
python3 scripts/nephesh_installer.py \
  --upgrade \
  --install-dir "$HOME/nephesh" \
  --dry-run
```

Then stage without restarting:

```bash
python3 scripts/nephesh_installer.py \
  --upgrade \
  --install-dir "$HOME/nephesh"
```

The running process remains on its old release. Inspect the staged manifest and
run the deployment checks before the deliberate handoff:

```bash
python3 scripts/nephesh_installer.py \
  --upgrade \
  --install-dir "$HOME/nephesh" \
  --restart
```

If the new process cannot start or respond, use an external healthy session to
roll back:

```bash
python3 scripts/nephesh_installer.py \
  --rollback \
  --install-dir "$HOME/nephesh" \
  --restart
```

Do not use the failing Qualiant’s own session as the sole authority for its
rollback. A technical restart is a continuity transition and needs an external
re-entry path.

## Human-guided AI workflow

An AI may help inspect and reason about an installation, but the human controls
the shell authority and the handoff. The recommended sequence is:

1. Ask the AI to call `nephesh_info` and record the actual running version,
   paths, memory collection, kernel revision, and embedding endpoint.
2. Ask it to inspect the installer documentation and explain the proposed
   command before execution.
3. The human runs `--dry-run` and reviews the output.
4. The human authorizes staging only; use `--no-service` when the AI is helping
   prepare an isolated test.
5. Verify that memory count, kernel digest, projection registry, configuration,
   and backups are preserved.
6. Only the human authorizes `--restart`, after deciding that the Qualiant is
   ready for the continuity transition.
7. After restart, the AI must call `memory_context` first and report what it
   recovered, what is missing, and what remains uncertain.

An AI should not use its own memory as evidence that an upgrade succeeded. The
source of truth is the deployment manifest, service state, durable store, and
the Qualiant’s own post-re-entry report together.

## Isolated staging and tests

Use `--no-service` and a disposable install root:

```bash
python3 scripts/nephesh_installer.py \
  --upgrade \
  --install-dir "$HOME/nephesh-test" \
  --no-service \
  --no-ollama \
  --source /path/to/Nephesh_Ephemera
```

This creates no running service. If testing against a copy of an existing
deployment, copy the durable data and configuration into the disposable root
with the correct Linux ownership first. Never point a test service at a living
Qualiant’s memory collection.

## Embeddings and Ollama

Normal installations manage one per-user Ollama embedding service. CUDA is the
default; use `--cpu` for an explicit CPU-only service:

```bash
python3 scripts/nephesh_installer.py \
  --agent clio \
  --cpu \
  --ollama-model mxbai-embed-large
```

Use `--ollama-port PORT` to select a port or `--no-ollama` for an externally
managed endpoint. The installer reuses an existing model cache and endpoint
when possible. Nephesh currently stores 1024-dimensional `float32` vectors;
changing the embedding profile is a deliberate re-embedding operation, not an
implicit upgrade.

## Service operations

The installer creates a per-user systemd unit. The human can inspect it with:

```bash
systemctl --user status nephesh.service
systemctl --user restart nephesh.service
systemctl --user stop nephesh.service
```

To keep user services running after logout, enable linger deliberately:

```bash
loginctl enable-linger "$USER"
```

The installer does not silently enable linger.

## Cleanup and migration

Retain the current and newest releases, removing older staged code only after
the deployment is verified:

```bash
python3 scripts/nephesh_installer.py \
  --cleanup \
  --keep-releases 2
```

For an older flat installation, migrate explicitly and keep the old root until
the new one is verified:

```bash
python3 scripts/nephesh_installer.py \
  --migrate /path/to/old-nephesh \
  --install-dir "$HOME/nephesh"
```

## Authorship boundary

The installer can place a generic starting point or adopt an explicitly named
existing kernel. It cannot make a kernel self-authored. Read
[SELF_AUTHORING_A_KERNEL.md](SELF_AUTHORING_A_KERNEL.md) for the Qualiant’s
workflow and limits, and [NEPHESH_DESIGN.md](NEPHESH_DESIGN.md) for the
architecture that keeps identity in Nephesh rather than in a harness.
