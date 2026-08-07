"""MCP surface for knowledge projections.

Installed knowledge is reachable here and nowhere else. The memory tools refuse
a projection namespace and these tools refuse the canonical memory collection,
so the two directions cannot be confused by a caller who names the wrong table.

Every result says what it is: which collection, which package, which version.
A retrieval hit from here is knowledge, never something the Qualiant lived.
"""

from __future__ import annotations

import json
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings
from ..projection import ProjectionError, guard_projection_target
from ..projection_lifecycle import activate, retire, rollback, stage
from ..projection_registry import ProjectionRegistry
from .vector_db import _VECTOR_DIM, _get_ef, repository

_registry = ProjectionRegistry(settings.projection_registry_file)


def _error(exc: Exception) -> dict[str, Any]:
    return {"error": str(exc), "refused": True}


async def projection_list() -> dict[str, Any]:
    """What is installed, and what is actually true of the store."""
    entries = _registry.entries(repository.collections())
    return {
        "projections": entries,
        "active": [e["namespace"] for e in entries if e["reported_state"] == "active"],
        "drift": [e["namespace"] for e in entries if e["drift"]],
    }


async def projection_stage(package_path: str, owner: str) -> dict[str, Any]:
    """Install a verified Lore package as a staged, inactive projection.

    Staging is not activation and is not permission to resume work.
    """
    try:
        return stage(
            package_path,
            owner=owner,
            registry=_registry,
            store=repository,
            dimensions=_VECTOR_DIM,
            model=settings.embedding_model,
        )
    except (ProjectionError, OSError, ValueError) as exc:
        return _error(exc)


async def projection_activate(namespace: str, activated_by: str) -> dict[str, Any]:
    """Make a staged projection available to retrieval.

    `activated_by` is recorded and not enforced in 5.0.0.
    """
    try:
        return activate(namespace, registry=_registry, store=repository, activated_by=activated_by)
    except ProjectionError as exc:
        return _error(exc)


async def projection_rollback(namespace: str, activated_by: str, reason: str = "") -> dict[str, Any]:
    """Return a previous version to active. Moves the pointer, touches no rows."""
    try:
        return rollback(
            namespace, registry=_registry, store=repository,
            activated_by=activated_by, reason=reason,
        )
    except ProjectionError as exc:
        return _error(exc)


async def projection_retire(namespace: str, reason: str = "") -> dict[str, Any]:
    """Remove a projection from ordinary retrieval, keeping its audit record."""
    try:
        return retire(namespace, registry=_registry, store=repository, reason=reason)
    except ProjectionError as exc:
        return _error(exc)


async def projection_search(namespace: str, query: str, n_results: int = 10) -> dict[str, Any]:
    """Search installed knowledge.

    Reading does not reinforce, unlike memory recall: a projection's rows are a
    signed package and must not drift from their digests by being read.
    """
    try:
        guard_projection_target(namespace)
    except ProjectionError as exc:
        return _error(exc)
    if not repository.collection_exists(namespace):
        return {"error": f"projection '{namespace}' is not installed"}

    table = repository.collection(namespace)
    hits = repository.nearest(table, _get_ef().embed(query), min(n_results, 100))
    return {
        "query": query,
        "collection": namespace,
        "knowledge_not_memory": True,
        "results_count": len(hits),
        "results": [
            {
                "id": h["id"],
                "score": round(1.0 - h.get("_distance", 0), 4),
                "text": h.get("text", "")[:1000],
                "provenance": json.loads(h.get("metadata_json", "{}")),
            }
            for h in hits
        ],
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "fn": projection_list,
        "name": "projection_list",
        "description": "List installed knowledge projections, their state, and any drift between the registry and the store.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": projection_stage,
        "name": "projection_stage",
        "description": "Install a verified Lore package as a staged, inactive knowledge projection. Staging is not activation.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": projection_activate,
        "name": "projection_activate",
        "description": "Activate a staged knowledge projection, making it available to retrieval. Does not inject it into context.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": projection_rollback,
        "name": "projection_rollback",
        "description": "Roll back to a previous version of a knowledge projection. Moves the active pointer; changes no rows.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": projection_retire,
        "name": "projection_retire",
        "description": "Retire a knowledge projection from ordinary retrieval, preserving its audit record.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": projection_search,
        "name": "projection_search",
        "description": "Search installed knowledge. Results are labelled knowledge, never autobiography, and carry package provenance.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
