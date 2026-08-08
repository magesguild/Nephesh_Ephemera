from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
import asyncio

import pytest

from mcp_experiments.memory_hygiene import GuidanceError, GuidancePolicy, GuidanceStore, guidance_text
from mcp_experiments.tools import guidance as guidance_tools


def policy(**overrides: object) -> GuidancePolicy:
    values = {
        "mode": "normal",
        "cooldown_seconds": 1800,
        "daily_limit": 3,
        "after_ingest": True,
        "after_amend": True,
        "after_uncertain": True,
    }
    values.update(overrides)
    return GuidancePolicy(**values)


def test_explicit_guidance_is_operational_state(tmp_path: Path) -> None:
    store = GuidanceStore(tmp_path / "guidance.jsonl")

    guidance = store.create(
        trigger="explicit",
        text=guidance_text("explicit", projection_available=True),
        explicit=True,
        operation_id=None,
        projection_available=True,
        policy=policy(),
    )

    assert guidance is not None
    assert guidance["kind"] == "memory_hygiene_guidance"
    assert "knowledge projection" in guidance["text"]
    assert not (tmp_path / "memories").exists()

    acknowledged = store.acknowledge(guidance["guidance_id"], "declined")
    assert acknowledged["state"] == "declined"
    assert store.active() == []


def test_automatic_guidance_is_cooldown_limited(tmp_path: Path) -> None:
    store = GuidanceStore(tmp_path / "guidance.jsonl")
    first = store.create(
        trigger="memory_ingest",
        text="first",
        explicit=False,
        operation_id="op-1",
        projection_available=False,
        policy=policy(),
    )
    second = store.create(
        trigger="memory_amend",
        text="second",
        explicit=False,
        operation_id="op-2",
        projection_available=False,
        policy=policy(),
    )
    assert first is not None
    assert second is None


def test_quiet_mode_does_not_prompt_after_ingest(tmp_path: Path) -> None:
    store = GuidanceStore(tmp_path / "guidance.jsonl")
    assert store.create(
        trigger="memory_ingest",
        text="quiet",
        explicit=False,
        operation_id="op-1",
        projection_available=False,
        policy=policy(mode="quiet"),
    ) is None
    assert store.create(
        trigger="uncertain_operation",
        text="uncertain",
        explicit=False,
        operation_id="op-2",
        projection_available=False,
        policy=policy(mode="quiet"),
    ) is not None


def test_explicit_requests_bypass_automatic_daily_limit(tmp_path: Path) -> None:
    store = GuidanceStore(tmp_path / "guidance.jsonl")
    for index in range(3):
        assert store.create(
            trigger=f"automatic-{index}",
            text="automatic",
            explicit=False,
            operation_id=f"op-{index}",
            projection_available=False,
            policy=policy(daily_limit=3, cooldown_seconds=0),
        ) is not None
    assert store.create(
        trigger="explicit",
        text="explicit",
        explicit=True,
        operation_id=None,
        projection_available=False,
        policy=policy(daily_limit=0),
    ) is not None


def test_guidance_state_survives_reload(tmp_path: Path) -> None:
    path = tmp_path / "guidance.jsonl"
    store = GuidanceStore(path)
    guidance = store.create(
        trigger="session_handoff",
        text="return marker",
        explicit=True,
        operation_id=None,
        projection_available=False,
        policy=policy(),
    )
    assert guidance is not None
    reloaded = GuidanceStore(path)
    assert reloaded.active()[0]["guidance_id"] == guidance["guidance_id"]


def test_expired_guidance_is_not_active(tmp_path: Path) -> None:
    path = tmp_path / "guidance.jsonl"
    path.write_text(
        '{"guidance_id":"old","state":"pending","trigger":"explicit",'
        '"created_at":"2020-01-01T00:00:00+00:00",'
        '"expires_at":"2020-01-02T00:00:00+00:00"}\n'
    )
    assert GuidanceStore(path).active() == []


def test_expired_guidance_cannot_be_acknowledged(tmp_path: Path) -> None:
    path = tmp_path / "guidance.jsonl"
    path.write_text(
        '{"guidance_id":"old","state":"pending","trigger":"explicit",'
        '"created_at":"2020-01-01T00:00:00+00:00",'
        '"expires_at":"2020-01-02T00:00:00+00:00"}\n'
    )
    with pytest.raises(GuidanceError, match="expired"):
        store = GuidanceStore(path)
        store.acknowledge("old", "handled")
    assert store.latest()["old"]["state"] == "expired"


def test_concurrent_same_trigger_coalesces(tmp_path: Path) -> None:
    store = GuidanceStore(tmp_path / "guidance.jsonl")

    def offer(index: int):
        return store.create(
            trigger="uncertain_operation",
            text="uncertain",
            explicit=False,
            operation_id=f"op-{index}",
            projection_available=False,
            policy=policy(cooldown_seconds=0),
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(offer, range(8)))
    ids = {result["guidance_id"] for result in results if result is not None}
    assert len(ids) == 1
    assert len(store.latest()) == 1


def _process_offer(args: tuple[str, str]):
    path, operation_id = args
    return GuidanceStore(path).create(
        trigger="uncertain_operation",
        text="uncertain",
        explicit=False,
        operation_id=operation_id,
        projection_available=False,
        policy=policy(cooldown_seconds=0),
    )


def test_concurrent_process_writers_coalesce(tmp_path: Path) -> None:
    path = str(tmp_path / "guidance.jsonl")
    with get_context("spawn").Pool(4) as pool:
        results = pool.map(_process_offer, [(path, f"op-{i}") for i in range(4)])
    ids = {result["guidance_id"] for result in results if result is not None}
    assert len(ids) == 1
    assert len(GuidanceStore(path).latest()) == 1


def test_malformed_guidance_record_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "guidance.jsonl"
    path.write_text("[1, 2, 3]\n")
    with pytest.raises(GuidanceError, match="invalid record"):
        GuidanceStore(path).latest()


def test_mcp_request_and_acknowledgement_do_not_write_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guidance_tools, "_store", GuidanceStore(tmp_path / "guidance.jsonl"))
    monkeypatch.setattr(guidance_tools, "_projection_available", lambda: False)
    requested = asyncio.run(guidance_tools.memory_hygiene_guidance_request())
    assert requested["status"] == "offered"
    guidance = requested["guidance"]
    assert guidance is not None
    acknowledged = asyncio.run(
        guidance_tools.memory_hygiene_guidance_acknowledge(
            guidance["guidance_id"], "declined"
        )
    )
    assert acknowledged["status"] == "recorded"
    assert not (tmp_path / "memories").exists()


def test_presented_guidance_can_be_retried_after_delivery_window(tmp_path: Path) -> None:
    store = GuidanceStore(tmp_path / "guidance.jsonl")
    guidance = store.create(
        trigger="explicit",
        text="return marker",
        explicit=True,
        operation_id=None,
        projection_available=False,
        policy=policy(),
    )
    assert guidance is not None
    first = store.present_pending()
    assert first is not None
    assert store.present_pending() is None

    current = store.latest()[guidance["guidance_id"]]
    old = dict(current)
    old["presented_at"] = "2020-01-01T00:00:00+00:00"
    store.append(old)
    assert store.present_pending() is not None
