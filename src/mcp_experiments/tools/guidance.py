"""MCP tools for Nephesh-owned memory-hygiene guidance."""

from __future__ import annotations

from typing import Literal

from ..compliance import ComplianceLevel
from ..config import settings
from ..memory_hygiene import GuidanceError, GuidancePolicy, GuidanceStore, guidance_text, projection_available
from ..results import GuidanceAcknowledgeResult, GuidanceRequestResult
from .vector_db import repository


_store = GuidanceStore(settings.memory_hygiene_state_file)


def _projection_available() -> bool:
    return projection_available(settings.projection_registry_file, repository.collections())


async def memory_hygiene_guidance_request(
    trigger: Literal["explicit", "compaction", "substrate_change", "session_handoff"] = "explicit",
    note: str | None = None,
) -> GuidanceRequestResult:
    """Request optional memory-hygiene guidance from Nephesh.

    This does not create a memory. The caller's declared trigger is recorded as
    an explicit request; Nephesh does not infer significance from it.
    """
    try:
        policy = GuidancePolicy.from_settings(settings)
        available = _projection_available()
        guidance = _store.create(
            trigger=trigger,
            text=guidance_text(trigger, projection_available=available),
            explicit=True,
            operation_id=None,
            projection_available=available,
            policy=policy,
            note=note,
        )
        if guidance:
            guidance = _store.present(guidance["guidance_id"])
        return {"status": "offered", "guidance": guidance}
    except (GuidanceError, OSError) as exc:
        return {"error": str(exc)}


async def memory_hygiene_guidance_acknowledge(
    guidance_id: str,
    outcome: Literal["handled", "declined", "not_now", "wrong_trigger"],
    note: str | None = None,
) -> GuidanceAcknowledgeResult:
    """Acknowledge, defer, decline, or correct a guidance offer.

    Outcomes are operational state and never become autobiographical memory.
    """
    try:
        return {
            "status": "recorded",
            "guidance": _store.acknowledge(guidance_id, outcome, note),
        }
    except (GuidanceError, OSError) as exc:
        return {"error": str(exc)}


TOOL_DEFINITIONS = [
    {
        "fn": memory_hygiene_guidance_request,
        "name": "memory_hygiene_guidance_request",
        "description": "Request optional Nephesh-owned memory-hygiene guidance without creating a memory.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_hygiene_guidance_acknowledge,
        "name": "memory_hygiene_guidance_acknowledge",
        "description": "Acknowledge, defer, decline, or correct a memory-hygiene guidance offer without creating a memory.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
