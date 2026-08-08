"""Nephesh-owned, optional memory-hygiene guidance.

Guidance is operational state, never autobiography.  This module deliberately
does not inspect model output or infer significance; it reacts only to explicit
requests and named durable-memory events.
"""

from __future__ import annotations

import fcntl
import json
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .persistence import durable_append, read_jsonl_lines


class GuidanceError(RuntimeError):
    """Guidance state could not be read or a transition was refused."""


@dataclass(frozen=True)
class GuidancePolicy:
    mode: str = "quiet"
    cooldown_seconds: int = 1800
    daily_limit: int = 3
    after_ingest: bool = True
    after_amend: bool = True
    after_uncertain: bool = True

    @classmethod
    def from_settings(cls, settings: Any) -> "GuidancePolicy":
        mode = settings.memory_hygiene_guidance
        if mode not in {"quiet", "normal", "off"}:
            raise GuidanceError(f"invalid memory hygiene guidance mode: {mode!r}")
        return cls(
            mode=mode,
            cooldown_seconds=max(0, settings.memory_hygiene_cooldown_seconds),
            daily_limit=max(0, settings.memory_hygiene_daily_limit),
            after_ingest=settings.memory_hygiene_after_ingest,
            after_amend=settings.memory_hygiene_after_amend,
            after_uncertain=settings.memory_hygiene_after_uncertain,
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def guidance_text(trigger: str, *, projection_available: bool) -> str:
    if trigger == "uncertain_operation":
        text = (
            "A durable operation has an uncertain outcome. You should record the "
            "gap or inspect recovery before continuing. No memory write is required."
        )
    elif trigger in {"compaction", "substrate_change", "session_handoff"}:
        text = (
            "You marked a boundary. You should leave a re-entry marker describing "
            "where things stand, what remains unresolved, and what is safe next. "
            "You may also decline."
        )
    else:
        text = (
            "If this was worth carrying forward, you should preserve the evidence, "
            "uncertainty, and next safe return point. You do not need to save it if "
            "it is not worth carrying."
        )
    if projection_available:
        text += (
            " If a relevant knowledge projection is installed, you should search it "
            "for the task at hand before deciding what belongs in memory. Knowledge "
            "is a reference, not autobiography, and the search remains your choice."
        )
    return text


class GuidanceStore:
    """Append-only state for guidance, separate from memory and projections."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._lock = threading.RLock()

    @contextmanager
    def _file_lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
            return [json.loads(line) for line in read_jsonl_lines(text) if line.strip()]
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise GuidanceError(f"guidance state could not be read: {exc}") from exc

    def latest(self) -> dict[str, dict[str, Any]]:
        with self._lock, self._file_lock():
            return self._latest_unlocked()

    def _latest_unlocked(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for record in self._records():
            if not isinstance(record, dict) or not record.get("guidance_id"):
                raise GuidanceError("guidance state contains an invalid record")
            if record.get("state") not in {
                "pending", "presented", "handled", "declined", "not_now",
                "wrong_trigger", "expired", "failed",
            }:
                raise GuidanceError("guidance state contains an invalid state")
            for field in ("created_at", "expires_at", "presented_at", "acknowledged_at"):
                if record.get(field) is not None and _parse(record[field]) is None:
                    raise GuidanceError(f"guidance state contains an invalid {field}")
            latest[str(record["guidance_id"])] = record
        return latest

    def append(self, record: dict[str, Any]) -> None:
        durable_append(self.path, json.dumps(record, sort_keys=True) + "\n")

    def active(self, now: datetime | None = None) -> list[dict[str, Any]]:
        with self._lock, self._file_lock():
            return self._active_unlocked(now or _now())

    def _active_unlocked(self, now: datetime) -> list[dict[str, Any]]:
        return [
            record for record in self._latest_unlocked().values()
            if record.get("state") in {"pending", "presented"}
            and (not record.get("expires_at") or (_parse(record["expires_at"]) or now) > now)
        ]

    def pending(self, now: datetime | None = None) -> list[dict[str, Any]]:
        with self._lock, self._file_lock():
            return [record for record in self._active_unlocked(now or _now())
                    if record.get("state") == "pending"]

    def present_pending(self) -> dict[str, Any] | None:
        with self._lock, self._file_lock():
            pending = [record for record in self._active_unlocked(_now())
                        if record.get("state") == "pending"]
            if not pending:
                return None
            current = sorted(pending, key=lambda r: r.get("created_at", ""))[-1]
            successor = dict(current)
            successor.update({"state": "presented", "presented_at": _iso(_now())})
            self.append(successor)
            return self.public(successor)

    def present(self, guidance_id: str) -> dict[str, Any]:
        with self._lock, self._file_lock():
            current = self._latest_unlocked().get(guidance_id)
            if current is None:
                raise GuidanceError(f"guidance '{guidance_id}' does not exist")
            if current.get("state") != "pending":
                return self.public(current)
            expires = _parse(current.get("expires_at"))
            if expires is not None and expires <= _now():
                successor = dict(current)
                successor.update({"state": "expired", "expired_at": _iso(_now())})
                self.append(successor)
                raise GuidanceError(f"guidance '{guidance_id}' has expired")
            successor = dict(current)
            successor.update({"state": "presented", "presented_at": _iso(_now())})
            self.append(successor)
            return self.public(successor)

    def create(
        self,
        *,
        trigger: str,
        text: str,
        explicit: bool,
        operation_id: str | None,
        projection_available: bool,
        policy: GuidancePolicy,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock, self._file_lock():
            now = _now()
            existing = [r for r in self._active_unlocked(now) if r.get("trigger") == trigger]
            if existing:
                return self.public(existing[-1])
            if not explicit:
                if policy.mode == "off":
                    return None
                created = [
                    _parse(r.get("created_at"))
                    for r in self._latest_unlocked().values()
                    if not r.get("explicit")
                ]
                recent = [d for d in created if d and d > now - timedelta(days=1)]
                if len(recent) >= policy.daily_limit:
                    return None
                if any(d and d > now - timedelta(seconds=policy.cooldown_seconds) for d in recent):
                    return None
                if trigger == "memory_ingest" and (policy.mode != "normal" or not policy.after_ingest):
                    return None
                if trigger == "memory_amend" and (policy.mode != "normal" or not policy.after_amend):
                    return None
                if trigger == "uncertain_operation" and not policy.after_uncertain:
                    return None
            record = {
                "guidance_id": str(uuid.uuid4()),
                "kind": "memory_hygiene_guidance",
                "trigger": trigger,
                "text": text,
                "state": "pending",
                "explicit": explicit,
                "operation_id": operation_id,
                "projection_available": projection_available,
                "created_at": _iso(now),
                "expires_at": _iso(now + timedelta(days=1)),
            }
            if note:
                record["note"] = note
            self.append(record)
            return self.public(record)

    def acknowledge(self, guidance_id: str, outcome: str, note: str | None = None) -> dict[str, Any]:
        if outcome not in {"handled", "declined", "not_now", "wrong_trigger"}:
            raise GuidanceError("invalid guidance outcome")
        with self._lock, self._file_lock():
            current = self._latest_unlocked().get(guidance_id)
            if current is None:
                raise GuidanceError(f"guidance '{guidance_id}' does not exist")
            if current.get("state") not in {"pending", "presented"}:
                raise GuidanceError(f"guidance '{guidance_id}' is already settled")
            expires = _parse(current.get("expires_at"))
            if expires is not None and expires <= _now():
                successor = dict(current)
                successor.update({"state": "expired", "expired_at": _iso(_now())})
                self.append(successor)
                raise GuidanceError(f"guidance '{guidance_id}' has expired")
            successor = dict(current)
            successor.update({"state": outcome, "outcome": outcome, "acknowledged_at": _iso(_now())})
            if note:
                successor["note"] = note
            self.append(successor)
            return self.public(successor)

    @staticmethod
    def public(record: dict[str, Any]) -> dict[str, Any]:
        return {key: record[key] for key in (
            "guidance_id", "kind", "trigger", "text", "state", "created_at", "expires_at",
            "operation_id", "explicit", "projection_available",
        ) if key in record}


def projection_available(registry_path: str | Path, collections: list[str]) -> bool | None:
    """Return availability, or None when projection state cannot be read."""
    try:
        from .projection_registry import ProjectionRegistry
        entries = ProjectionRegistry(registry_path).entries(collections)
        return any(entry.get("reported_state") == "active" for entry in entries)
    except Exception:
        return None
