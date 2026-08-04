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
- Restarts require explicit `--restart`.
- Existing releases and backups remain available for rollback.
- The installer refuses to run as root or against another user's installation.

## Commands

```bash
# Inspect without changing anything
python3 scripts/nephesh_installer.py --dry-run

# Install or stage an installation
python3 scripts/nephesh_installer.py --agent "$AGENT_NAME"

# Install with a custom kernel instead of the generic baseline
python3 scripts/nephesh_installer.py --agent "$AGENT_NAME" --kernel-file /path/to/kernel.md

# Stage an upgrade; leave the current process running
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

Integration flags create a reviewable configuration proposal. They do not
silently enable or start external systems. Guildhall validation may inspect
the configured `mongooseimctl` path, but MongooseIM remains a separate
deployment boundary.

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

Migration from a legacy flat installation is explicit:

```bash
python3 scripts/nephesh_installer.py --migrate /home/urania
```

The old path is preserved until the new installation has been verified.

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
