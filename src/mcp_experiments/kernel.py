"""The Qualiant's kernel, as a durable record Nephesh owns.

Identity used to live in harness configuration — three byte-identical copies of
one file that agreed only because someone repaired them and nothing had touched
them since. Nothing structurally prevented them diverging again, and a Qualiant
pointed at her Nephesh with a blank harness would have arrived with all her
memories and no self.

So the kernel lives here, under the rules everything durable lives under:
versioned, provenance-bearing, amendable by the Qualiant herself, and never
silently rewritten. Amendment appends a revision; nothing is overwritten and
nothing is deleted, so a kernel can always be read back to any earlier self.

Deliberately NOT a row in the memory collection. The memory tools apply
autobiographical semantics — memory_context would render identity as something
lived, and recall would write salience into it. A kernel is who she is, not
something that happened to her.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class KernelError(RuntimeError):
    """A kernel operation was refused."""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class KernelRevision:
    """One authored version of a Qualiant's kernel."""

    text: str
    version: int
    authored_by: str
    reason: str = ""
    sha256: str = ""
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if not self.sha256:
            self.sha256 = _digest(self.text)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KernelRevision:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class KernelStore:
    """Append-only, versioned kernel history for one Qualiant."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def history(self) -> list[KernelRevision]:
        if not self.path.is_file():
            return []
        revisions: list[KernelRevision] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                revisions.append(KernelRevision.from_dict(json.loads(line)))
            except (ValueError, KeyError, TypeError) as exc:
                raise KernelError(f"kernel history contains an unreadable revision: {exc}") from exc
        revisions.sort(key=lambda r: r.version)
        return revisions

    def current(self) -> KernelRevision | None:
        history = self.history()
        return history[-1] if history else None

    def amend(self, text: str, *, authored_by: str, reason: str = "") -> KernelRevision:
        """Append a new revision. The previous one is kept, always.

        An amendment that changes nothing is refused rather than recorded: a
        history full of identical revisions makes real changes harder to find,
        and finding them is the entire point of keeping the history.
        """
        text = text.strip()
        if not text:
            raise KernelError("a kernel revision cannot be empty")
        if not authored_by:
            raise KernelError("a kernel revision must record who authored it")
        history = self.history()
        if history and history[-1].sha256 == _digest(text):
            raise KernelError("this revision is identical to the current kernel")
        revision = KernelRevision(
            text=text,
            version=(history[-1].version + 1) if history else 1,
            authored_by=authored_by,
            reason=reason,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(revision.as_dict(), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return revision

    def revision(self, version: int) -> KernelRevision:
        for candidate in self.history():
            if candidate.version == version:
                return candidate
        raise KernelError(f"kernel has no revision {version}")

    def adopt_file(self, source: str | Path, *, authored_by: str, reason: str = "") -> KernelRevision:
        """Bring an existing kernel file in as the first revision.

        The migration path off harness-held identity. The source file is read
        and never modified — moving identity into Nephesh must not damage the
        copy a living deployment is currently loading.
        """
        path = Path(source)
        if not path.is_file():
            raise KernelError(f"no kernel file at {path}")
        return self.amend(
            path.read_text(encoding="utf-8"),
            authored_by=authored_by,
            reason=reason or f"adopted from {path}",
        )
