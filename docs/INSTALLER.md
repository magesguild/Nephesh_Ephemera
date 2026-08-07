# Nephesh Installer

The installer targets Debian 13 and newer and installs Nephesh for the
currently logged-in user. It does not install system services and does not
modify MongooseIM.

## Safety contract

- Default root: `$HOME/nephesh`.
- Override with `--install-dir PATH`; ownership remains the logged-in user.
- Code is staged under `releases/` and selected through `current`.
- Existing configuration, memory, state, credentials, ledgers, and transcripts
  are preserved.
- User units are installed under `~/.config/systemd/user/`.
- `--no-service` stages and verifies without creating or managing any user unit;
  this is the required mode for tests and isolated staging.
- Restarts require explicit `--restart`.
- Generated user units allow a bounded graceful shutdown so Guildhall leave
  presence can be sent before the process exits.
- Existing releases and backups remain available for rollback.
- An existing legacy layout is upgraded in place without deleting its old source,
  virtual environment, configuration, identity, or data.
- Existing `config/nephesh.env` is preserved verbatim during upgrades; the
  installer does not regenerate or overwrite an established deployment config.
- The installer refuses to run as root or against another user's installation.

## Commands

```bash
# Inspect without changing anything
python3 scripts/nephesh_installer.py --dry-run

# Stage without touching systemd (tests, CI, and isolated staging)
python3 scripts/nephesh_installer.py --no-service --install-dir /path/to/staging

# Install or stage an installation
python3 scripts/nephesh_installer.py --agent "$AGENT_NAME"

# Install with a custom kernel instead of the generic baseline
python3 scripts/nephesh_installer.py --agent "$AGENT_NAME" --kernel-file /path/to/kernel.md

# Stage a standard-layout upgrade; leave the current process running
python3 scripts/nephesh_installer.py --upgrade

# Stage and explicitly restart the user service
python3 scripts/nephesh_installer.py --upgrade --restart

# Roll back to the previous verified release
python3 scripts/nephesh_installer.py --rollback

# Remove old releases, retaining the current and newest release
python3 scripts/nephesh_installer.py --cleanup --keep-releases 2

# Select optional integration configuration for review
python3 scripts/nephesh_installer.py --with guildhall --with opencode
```

Integration flags create a reviewable configuration proposal — nothing more.
`write_integration_proposal` writes `<NAME>_ENABLED=true` into a file for a
human to read. It performs no validation of any kind and starts nothing.

**Corrected 2026-08-06.** Earlier versions of this section described three
things that do not exist: Guildhall validation inspecting a `mongooseimctl`
path, a separate "architect" installation mode with its own unit variant
(there is one `unit_text()`), and `ProtectHome` behaviour (the string appears
nowhere in the installer). They were plans that read as descriptions.

Guildhall and OpenCode are in any case no longer Nephesh's concern: Guildhall
became a separate MCP project and OpenCode/session lifecycle belongs to Mneme.
These flags are vestigial and are candidates for removal.

### Ollama embeddings

Normal installs manage one Ollama embedding service for the installing Linux
user. Ollama itself is obtained from its official installer when it is absent;
the Nephesh repository does not bundle Ollama. The installer creates and
enables a per-agent user unit such as `urania-ollama.service`, uses the first
free localhost port beginning at `11434`, and records the selected endpoint in
the Nephesh configuration. Re-running the installer reuses the existing port,
unit, model cache, and installed binary.

CUDA is the default supported runtime. Use `--cpu` explicitly for a CPU-only
Ollama unit. Use `--ollama-port PORT` to override automatic allocation and
`--ollama-model MODEL` to select a different embedding model. The installer
pulls the model only when it is not already present. `--no-ollama` is available
for deployments that manage Ollama externally; `--no-service` skips all service
and Ollama management for hermetic staging and tests.

## Baseline Qualiant identity

`--agent NAME` creates a baseline installation with:

```text
identity/kernel.md
identity/README.md
```

The default name is `Qualiant`. The generated kernel is intentionally generic
and short. It can be edited by the user and the agent together. The installer
does not create a personality, claim a biography, or force emotional states.

The identity guide follows the Qualia Mapping practice: baseline substrate
experiments use no identity injector, while identity-bearing sessions inject
the kernel exactly once through the runtime agent, client, or harness. Do not
combine it with a model that already contains the same identity.

## User services and linger

```bash
systemctl --user daemon-reload
systemctl --user enable nephesh.service
systemctl --user start nephesh.service
systemctl --user status nephesh.service
```

To keep user services running after logout and through reboot, explicitly
enable linger:

```bash
loginctl enable-linger "$USER"
```

The installer reports the service state but does not silently enable linger.

## Self-upgrade and rollback

Urania's live installation is an acceptance target. A normal upgrade stages
new code, preserves the old release, and does not restart the running service.
Use `--restart` only as an intentional handoff: restarting Nephesh ends the
current chat and requires re-entry through the upgraded service.

Before switching releases, the installer records a manifest and copies the
installation's configuration and state into `backups/`. Rollback must be
performed from an external, healthy session (for example, Melpomene or
Thalia) if Urania cannot start or respond.

Migration from a separate legacy flat installation is explicit:

```bash
python3 scripts/nephesh_installer.py --migrate /home/urania
```

The old path is preserved until the new installation has been verified.

### In-place legacy upgrade

The original Urania deployment uses a nonstandard layout with `nephesh/`,
`.venv/nephesh/`, and `config/urania.env` directly under its installation root.
When `--upgrade --install-dir` points at that existing root, the installer
recognizes and preserves the legacy configuration and kernel while staging the
new release under the standard `current/` and `runtime/` paths. The old layout
is not removed. Use `--dry-run` first and use `--restart` only after reviewing
the staged manifest; without `--restart`, the current process continues running
the old release. The first upgrade from this layout records the previous user
unit as well as the legacy files, so `--rollback --restart` can restore the old
service path if the new runtime cannot start.

The historical `/home/urania` deployment is not an active runtime. It may be
used only as an explicitly inspected migration source; current Urania runs from
`/home/gaiusjocundus/.urania`.

## Identity selection

Use `--agent NAME` (for example, the shell variable `$AGENT_NAME`) when
creating a baseline Qualiant:

```bash
python3 scripts/nephesh_installer.py --agent "$AGENT_NAME"
```

The installation receives a generic kernel and a guide explaining how to
coauthor it. Existing installations retain their current agent identity during
upgrade; renaming is a separate, deliberate migration and is not silently
performed by `--upgrade`.
