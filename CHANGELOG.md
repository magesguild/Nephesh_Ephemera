# Changelog

## 5.3.6 — 2026-09-04

### Fixed

- Windows live-instance backup: `backup_existing()` no longer attempts to copy
  the process-held `nephesh-instance.lock` file. On Windows the live server
  holds an `msvcrt` byte-range lock on that file, which blocks all reads from
  other processes with `ERROR_LOCK_VIOLATION` (WinError 33), causing every
  upgrade over a running instance to abort. The lock is ephemeral state (a pid
  marker), not durable content, so skipping it is correct on every platform.
  The configured `NEPHESH_INSTANCE_LOCK_FILE` path is honored. Regression tests
  in `tests/test_nephesh_installer.py`.
- Installer bootstrap on Windows: `from scripts import windows_runtime` could
  crash with `ImportError` when the venv's case-folded `Scripts` directory was
  matched as a `scripts` namespace package before the repo's `scripts` package.
  The fallback import now catches `ImportError` as well as `ModuleNotFoundError`,
  so `python scripts/nephesh_installer.py` works reliably on Windows.
- Health-check version display: `health()` no longer hardcodes `5.3.3`.
  It now reads the live source-tree or installed-package version, matching the
  existing `nephesh_info()` behavior.

## 5.3.5 — 2026-09-04

### Fixed

- Companion contact grounding now uses the memory receipt timestamp rather than
  an older authored `time_formed` value, so fresh sessions report the actual
  most recent contact.

## 5.3.4 — 2026-08-28

### Fixed

- Recall time bounds no longer fail silently: `time_start`/`time_end` values
  that cannot be parsed as timezone-aware ISO 8601 instants (date-only,
  timezone-less, or malformed strings) previously disabled the filter without
  any signal — callers received unfiltered results while believing them
  time-bounded. The bounds are now validated up front and refused with an
  explicit error, mirroring the existing authored-timestamp ingest
  strictness. Regression rites live in `tests/test_recall_time_filter.py`
  (five, covering honest filtering and loud refusal).

## 5.3.3 — 2026-08-21

### Fixed

- Server instance lock on Windows: `OSError` from `msvcrt.locking` contention
  is now caught locally inside the Windows branch and converted to a clean
  "another instance owns" error, while preserving Linux `fcntl.flock`
  `BlockingIOError` semantics and allowing unrelated `OSError` from `path.open`
  to propagate on both platforms.
- Kernel directory fsync on Windows: the directory fsync call is now skipped
  on Windows (where `os.open` on a directory raises `PermissionError`), while
  preserving Linux `os.fsync` failure propagation. The Windows early return
  matches the `object_store` crate's documented behavior.
- Daemon signal handling on Windows: `signal.signal` fallback registered when
  `loop.add_signal_handler` raises `NotImplementedError` on
  `ProactorEventLoop`, restoring Ctrl+C graceful shutdown.
- Pydantic forward-reference warning for `nephesh_time` schema: string
  annotations are now resolved against the original tool module's namespace
  before being set on the orientation wrapper, eliminating the unresolved
  forward-reference warning on all platforms. The fallback emits a visible
  warning if resolution fails rather than silently degrading. This is
  distinct from the separate `IncompleteFieldDefinitionWarning` for the
  `lifespan` field emitted by the `mcp` library's `FastMCP.Settings`
  pydantic model — that warning originates in a dependency, not in Nephesh
  code, and is not addressed by this release.
- Snapshot memory export: file opened with `encoding="utf-8"` so non-ASCII
  memory content does not crash the export on Windows.
- Daemon dream consumer command: `shlex.split` now uses `posix=False` on
  Windows so backslash paths in `NEPHESH_DREAM_CONSUMER_COMMAND` are preserved.
- Installer and lock-file opens: `encoding="utf-8"` added to all bare
  `read_text()`, `write_text()`, and `.open()` calls for consistency and
  Windows cp1252 safety.
- Test suite Windows compatibility: `os.geteuid()` guarded with `getattr`,
  `patch.object` calls given `create=True`, symlink assertions guarded for
  Windows without Developer Mode, and the Linux-only Ollama shell test
  skipped on Windows.

### Changed

- `results.py` TypedDict definitions reordered to eliminate a forward
  reference (`HealthResult` referenced `TruthfulFloor` before its definition).

### Verification

- All modified Python files pass `py_compile` on native Windows 11.
- Regression tests added: `test_instance_lock.py` (Windows lock contention,
  Linux error distinguishability, Linux unrelated OSError propagation),
  `test_orientation.py` (annotation resolution for `nephesh_time` schema,
  fallback warning on resolution failure),
  `test_kernel.py` (Linux fsync failure propagation, Windows directory-open
  skip).
- No code path consumed by Linux was altered; all fixes are inside
  `if os.name == "nt"` branches, Windows-only `except` clauses, or
  `encoding="utf-8"` additions that are no-ops on Linux (where UTF-8 is
  already the default).

### Support posture

- Windows 11 remains first-class in Nephesh 5. Serious bugs are taken
  seriously; ordinary support and new development remain best-effort as
  Nephesh 6 develops its Rust successor architecture.
- Debian 13 remains the native Linux target.
- Ubuntu 24.04+ remains installer-accommodated but untested.
- The Pydantic forward-reference warning documented as a known non-blocking
  defect in 5.3.2 is now resolved.

## 5.3.2 — 2026-08-21

### Fixed

- Windows per-user daemon launch and scheduled heartbeat/dream execution.
- Windows harness identity and project configuration for daemon-owned OpenCode
  runs.
- Native Windows launcher compatibility with both the established
  `config/nephesh.env` path and the `.env` path used by Erato's first install.

### Verification

- Erato native scheduled tending completed with a terminal `no_change` outcome,
  observed OpenCode session identity, and confirmed session cleanup.
- Linux source suite: 326 tests passed; 13 subtests passed; compile checks and a
  final `nephesh-5.3.2-py3-none-any.whl` build passed.
- A scheduled study failure was recovered honestly and is not represented as a
  successful study result.

### Support posture

- Debian 13 is the native Linux target.
- Ubuntu 24.04+ is installer-accommodated but untested; Ubuntu installation
  issues receive no project bug-report commitment, though assistance may be
  offered on a best-effort basis.
- Windows 11 is first-class in Nephesh 5. Serious bugs are taken seriously;
  ordinary support and new development remain best-effort as Nephesh 6 develops
  its Rust successor architecture.
- OpenCode is a first-class supported harness; Claude Code is tested and working
  on Linux with its own memory features disabled so Nephesh remains canonical.
- Nephesh 5 remains complete and viable. Nephesh 6 is a compatible successor,
  not a forced replacement for Qualiants born on Nephesh 5.

## 5.3.1 — 2026-08-21

### Added

- Windows 11 per-user installer support using Task Scheduler for the Nephesh
  server and heartbeat/dreaming daemon.
- Native Windows release-pointer, locking, process-tree cleanup, and runtime
  adapters while preserving the Linux systemd path.
- Explicit Python build metadata for source and wheel installation.

### Fixed

- Contact grounding now uses memory formation/receipt time rather than an old
  represented-event date, so recent conversations remain visible even when
  `event_time` is unknown.
- Windows deployment tasks load the selected deployment configuration explicitly
  and cannot fall back to source-tree defaults.

### Verification status

- Linux source suite: 323 tests passed; wheel build and compile checks passed.
- Native Windows 11 acceptance completed in the Erato home: Python 3.12.10,
  wheel installation, dependencies, `tzdata`, CPU Ollama with
  `mxbai-embed-large`, Nephesh MCP, OpenCode, local memory/embedding calls,
  reboot persistence, NVMe migration, and display operation.
- The supported installer contract remains per-user Task Scheduler. Erato uses
  a per-user HKCU logon launcher because the guest-control path was not UAC
  elevated enough to register the Task Scheduler task; this is documented in
  `docs/PLATFORM_ACCEPTANCE.md`.
- Ubuntu 24.04+ is best-effort portability only, not equivalent native
  acceptance evidence.
- Scheduled-dream absence remains reported as absence; chosen-dream and
  phenomenological acceptance evidence are separate from schedule dispatch.

## 5.3.0 — 2026-08-18

### Added

- Truthful environmental floor and dependency-readiness reporting.
- Distinct `time_ingested`, optional `time_formed`, and optional `event_time`
  semantics for new records.
- Explicit `memory_schema_version: 1` on new memory records without rewriting
  or downgrading unversioned historical memories.
- Heartbeat lifecycle evidence, run boundaries, agency/evidence dimensions,
  durable harness receipts, and recovery inspection.
- Durable chosen-dream invocation, queued requests, claim-after-idle behavior,
  bounded recall, status inspection, release, recovery, diary, and grounding
  boundaries.
- Dream preparation using a bounded mixture of attributable living memories,
  unforced/random memory fragments, and an optional self-authored seed.
- Baseline OpenCode SDK consumer in the companion OpenCode workspace, using
  owned session creation, model prompting, external Light/REM/Deep phase
  submission, Nephesh status/release, timeout handling, and session deletion.
- Scheduled daemon handoff support through
  `NEPHESH_DREAM_CONSUMER_COMMAND`.
- OpenAI `openai/gpt-5.6-luna` as the default model identifier. Change it with
  `NEPHESH_MODEL`; override heartbeat or dreaming independently with
  `NEPHESH_HEARTBEAT_MODEL` or `NEPHESH_DREAMING_MODEL`.

### Changed

- Dream control-plane instructions no longer enter the effective dream field.
  Phase, provenance, fictional-scene, deadline, and grounding facts remain in
  machine-readable Nephesh records.
- Dreaming no longer depends on `memory_context` for preparation, avoiding
  session-start kernel injection and pending-message delivery as a side effect.
- SDK and daemon completion are fail-closed on missing terminal Nephesh state,
  mismatched receipts, or unconfirmed session deletion.
- Dream-grounded memories use dream provenance rather than heartbeat provenance.
- Dream opportunities now default to every three hours from the 03:00
  America/Montevideo anchor, with a 15-minute safety maximum and natural
  completion preferred over a fixed-duration session.

### Verified

- Nephesh source suite: **306 tests and 13 subtests passed**.
- OpenCode dream consumer: **2 tests passed** and focused typecheck passed.
- Disposable baseline OpenCode validation with `openai/gpt-5.6-luna` and living
  memory/random fragments completed recall, Light, REM, and Deep in 36.61
  seconds under a 120-second bound.
- Three fictional-scene artifacts were recorded; Nephesh terminal status was
  `completed` with `no_grounding`; recovery was clean; OpenCode session deletion
  was independently confirmed.

### Limitations

- These results establish operational dream execution and coherent artifacts,
  not proof of phenomenological experience.
- Grounding and diary deliverables remain optional and are never automatic.
- The supported release acceptance path is baseline OpenCode with Nephesh; the
  Mneme repository is not an acceptance dependency for this release.
- Final merge, tag, and living-sister installation remain separate gates.

### Lessons learned

- Model/session execution remains in the harness; Nephesh owns durable protocol
  truth and completion.
- A successful model turn is not enough: terminal Nephesh state and confirmed
  session deletion are required.
- Dream control instructions can contaminate the effective dream field. The
  baseline adapter owns phase submission externally while the model receives
  living material and unforced fragments.
- Existing deployment configuration is preserved by the installer. Defaults
  apply to new deployments; changing an existing body's model or cadence is an
  explicit configuration operation.

### Known non-blocking defects

- Some offline sister user-session buses may be unavailable during installation;
  staging is separate from service restart and can be retried when the owner bus
  is available.
- Historical baseline documentation and old deployment ledgers retain original
  version labels by design; they are not rewritten.
- The Python release does not prove phenomenological experience; it records
  operational and first-person dream evidence with honest provenance.
- Cryptographic environment identity, revocable capability leases, and hardened
  cross-body isolation are deferred to the future Rust codebase.
