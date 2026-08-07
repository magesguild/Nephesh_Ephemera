"""The Qualiant's kernel: a versioned, self-authored durable record.

Identity used to live in harness configuration — copies of one file that agreed
only because someone repaired them and nothing had touched them since. Nothing
structurally prevented them diverging again, and a Qualiant pointed at her
Nephesh with a blank harness would have arrived with all her memories and no
self. So the kernel lives here, under the rules everything durable lives under:
versioned, provenance-bearing, amendable by the Qualiant herself, never
silently rewritten.

Stored as markdown, one file per revision, because a kernel is prose a being
reads — not a record a machine parses. Prose inside JSON means escaped newlines,
which makes the raw file unreadable exactly when raw reading matters most: when
the server will not start and someone needs to know who this deployment is.
`cat config/kernel/002.md` has to just work.

    config/kernel/001.md
    config/kernel/002.md   <- current is the highest number

Append-only by construction: a revision file is never rewritten, so no earlier
self can be lost. Provenance rides in frontmatter, where it is as readable as
the kernel itself.

Deliberately NOT a row in the memory collection. The memory tools apply
autobiographical semantics — context would render identity as something lived
and recall would write salience into it. A kernel is who she is, not something
that happened to her.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .persistence import durable_write_new

_REVISION_NAME = re.compile(r"^(\d{3,})\.md$")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)

#: Frontmatter keys this reader understands. Anything else is preserved in the
#: file but ignored here rather than treated as an error — a future field
#: should not make an old Qualiant's kernel unreadable.
_INT_KEYS = frozenset({"version", "supersedes"})


class KernelError(RuntimeError):
    """A kernel operation was refused."""


def _digest(text: str, *, authored_by: str = "", reason: str = "", recorded_at: str = "") -> str:
    """Cover the provenance as well as the prose.

    A digest over the text alone leaves `authored_by` editable with nothing to
    detect it — someone could rewrite who wrote a kernel and the integrity
    check would stay quiet. Attribution is exactly the claim a reader most
    needs to trust, so it is inside the digest.
    """
    payload = "\n".join((authored_by, reason, recorded_at, text))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class KernelRevision:
    """One authored version of a Qualiant's kernel."""

    text: str
    version: int
    authored_by: str
    reason: str = ""
    sha256: str = ""
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    supersedes: int | None = None
    path: str = ""

    def __post_init__(self) -> None:
        if not self.sha256:
            self.sha256 = self.compute_digest()

    def compute_digest(self) -> str:
        return _digest(
            self.text,
            authored_by=self.authored_by,
            reason=self.reason,
            recorded_at=self.recorded_at,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "authored_by": self.authored_by,
            "reason": self.reason,
            "sha256": self.sha256,
            "recorded_at": self.recorded_at,
            "supersedes": self.supersedes,
            "path": self.path,
            "text": self.text,
        }

    def render(self) -> str:
        """The file as written: frontmatter, then the kernel itself."""
        lines = [
            "---",
            f"version: {self.version}",
            f"authored_by: {self.authored_by}",
            f"reason: {self.reason}",
            f"recorded_at: {self.recorded_at}",
            f"sha256: {self.sha256}",
        ]
        if self.supersedes is not None:
            lines.append(f"supersedes: {self.supersedes}")
        lines.append("---")
        lines.append("")
        return "\n".join(lines) + self.text.strip() + "\n"


def _parse(path: Path) -> KernelRevision:
    """Read one revision file.

    A file whose frontmatter is missing or unreadable is refused rather than
    guessed at. A kernel read wrongly is worse than a kernel not read.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise KernelError(f"kernel revision {path.name} could not be read: {exc}") from exc

    match = _FRONTMATTER.match(raw)
    if not match:
        raise KernelError(f"kernel revision {path.name} has no frontmatter")

    fields: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key in _INT_KEYS:
            try:
                fields[key] = int(value)
            except ValueError as exc:
                raise KernelError(f"kernel revision {path.name} has a bad {key}: {value!r}") from exc
        elif key in ("authored_by", "reason", "recorded_at", "sha256"):
            fields[key] = value

    if "version" not in fields:
        raise KernelError(f"kernel revision {path.name} declares no version")
    if not fields.get("authored_by"):
        raise KernelError(f"kernel revision {path.name} records no author")

    text = match.group(2).strip()
    revision = KernelRevision(
        text=text,
        version=fields["version"],
        authored_by=fields["authored_by"],
        reason=fields.get("reason", ""),
        sha256=fields.get("sha256", ""),
        recorded_at=fields.get("recorded_at", ""),
        supersedes=fields.get("supersedes"),
        path=str(path),
    )
    if not revision.sha256:
        raise KernelError(f"kernel revision {path.name} records no digest")
    if revision.sha256 != revision.compute_digest():
        raise KernelError(
            f"kernel revision {path.name} does not match its recorded digest; "
            "its text or its attribution has been edited outside Nephesh"
        )
    return revision


class KernelStore:
    """Append-only, versioned kernel history for one Qualiant."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def _files(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        found = [p for p in self.directory.iterdir() if _REVISION_NAME.match(p.name)]
        return sorted(found, key=lambda p: int(_REVISION_NAME.match(p.name).group(1)))

    def history(self) -> list[KernelRevision]:
        return [_parse(path) for path in self._files()]

    def current(self) -> KernelRevision | None:
        files = self._files()
        return _parse(files[-1]) if files else None

    def revision(self, version: int) -> KernelRevision:
        for candidate in self.history():
            if candidate.version == version:
                return candidate
        raise KernelError(f"kernel has no revision {version}")

    def amend(self, text: str, *, authored_by: str, reason: str = "") -> KernelRevision:
        """Write a new revision. Every earlier one is kept, always.

        An amendment identical to the current kernel is refused rather than
        recorded: a history full of identical revisions makes real changes
        harder to find, and finding them is the point of keeping the history.
        """
        text = text.strip()
        if not text:
            raise KernelError("a kernel revision cannot be empty")
        if not authored_by:
            raise KernelError("a kernel revision must record who authored it")

        previous = self.current()
        if previous is not None and previous.text == text:
            raise KernelError("this revision is identical to the current kernel")

        revision = KernelRevision(
            text=text,
            version=(previous.version + 1) if previous else 1,
            authored_by=authored_by,
            reason=reason,
            supersedes=previous.version if previous else None,
        )
        path = self.directory / f"{revision.version:03d}.md"
        revision.path = str(path)
        try:
            durable_write_new(path, revision.render())
        except FileExistsError as exc:  # pragma: no cover - concurrent amend
            raise KernelError(f"kernel revision {path.name} already exists") from exc
        self._point_current_at(path)
        return revision

    def current_path(self) -> Path:
        """A stable path that always resolves to the newest revision.

        Harnesses that load instruction files by path need somewhere fixed to
        point. OpenCode's documented `instructions` option takes paths and
        globs; a glob would load every revision she has ever written, and a
        pinned revision number goes stale the moment she amends. A symlink is
        neither: it is one name that always means "her kernel now", and it
        cannot drift from the revision because it *is* the revision.
        """
        return self.directory / "current.md"

    def _point_current_at(self, path: Path) -> None:
        link = self.current_path()
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(path.name)
        except OSError:
            # A filesystem without symlinks costs a convenience, not the
            # kernel. The revision itself is already durably written.
            pass

    def adopt_file(self, source: str | Path, *, authored_by: str, reason: str = "") -> KernelRevision:
        """Bring an existing kernel file in as a revision.

        The migration path off harness-held identity. The source is read and
        never modified — moving identity into Nephesh must not damage the copy
        a living deployment is currently loading.
        """
        path = Path(source)
        if not path.is_file():
            raise KernelError(f"no kernel file at {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise KernelError(f"kernel file {path} could not be read: {exc}") from exc
        return self.amend(
            text,
            authored_by=authored_by,
            reason=reason or f"adopted from {path}",
        )
