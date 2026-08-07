"""Stage, activate, and roll back a knowledge projection.

Three operations over the registry, following section 5 and section 6 of
docs/NEPHESH_DESIGN.md section 6. Staging is separate from
activation because an automatic pull may stage and must never activate.
Rollback moves the active pointer and touches no rows.

Dependencies are passed in rather than imported so the whole module can be
exercised without opening a deployment-owned store.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Protocol

from .projection import (
    EmbeddingContract,
    ProjectionError,
    build_rows,
    guard_projection_target,
    namespace_for,
)
from .projection_registry import ProjectionRecord, ProjectionRegistry, ProjectionState


class Store(Protocol):
    """The slice of PersistenceRepository this module needs."""

    def collections(self) -> list[str]: ...
    def collection_exists(self, name: str) -> bool: ...
    def table(self, name: str) -> Any: ...
    def add(self, table: Any, rows: list[dict[str, Any]]) -> None: ...
    def drop_collection(self, name: str) -> None: ...


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(
    package_dir: str | Path,
    *,
    owner: str,
    registry: ProjectionRegistry,
    store: Store,
    dimensions: int,
    model: str,
    reembed: bool = False,
    embedder: Callable[[str], list[float]] | None = None,
) -> dict[str, Any]:
    """Import a verified package into its own namespace, staged and inactive.

    The package is read and every row built in memory before anything is
    written, so an unreadable package cannot leave a half-filled collection
    behind. If the write itself fails the partial collection is dropped rather
    than left for a later reader to mistake for a real projection.
    """
    package = Path(package_dir)
    manifest_path = package / "manifest.json"
    if not manifest_path.is_file():
        raise ProjectionError(f"no manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    package_id = str(manifest.get("package_id", ""))
    version = str(manifest.get("version", ""))
    contract = EmbeddingContract.from_manifest(manifest)
    try:
        contract.require_compatible(dimensions=dimensions, model=model)
    except ProjectionError:
        if not reembed:
            raise
    if reembed and embedder is None:
        raise ProjectionError("reembedding requires the deployment embedding function")

    namespace = guard_projection_target(namespace_for(package_id, version))
    if store.collection_exists(namespace):
        raise ProjectionError(
            f"{namespace!r} already exists in the store; refusing to stage over it"
        )

    indexed_embedding = {
        "indexed_embedding_model": model,
        "indexed_embedding_dimensions": dimensions,
        "reembedded": reembed,
    }
    rows = build_rows(
        package,
        manifest,
        dimensions,
        embedder=embedder if reembed else None,
        embedding_info=indexed_embedding,
    )
    if not rows:
        raise ProjectionError(f"{package_id} {version} produced no rows to import")

    embedding = manifest.get("embedding") or {}
    publisher = manifest.get("publisher") or {}
    table = store.table(namespace)
    # Registration is inside the cleanup, not after it. registry.record() is
    # where the owner is validated, so a stage() with a bad owner would
    # otherwise import every row, refuse, and leave a populated collection no
    # registry knows about — which then blocks the retry, because staging over
    # an existing collection is refused. Any failure here drops what this call
    # created.
    try:
        store.add(table, rows)
        registry.record(ProjectionRecord(
            package_id=package_id,
            version=version,
            namespace=namespace,
            state=ProjectionState.STAGED,
            owner=owner,
            manifest_sha256=_sha256(manifest_path),
            publisher=str(publisher.get("name", "")),
            records=int(manifest.get("records", 0)),
            chunks=len(rows),
            embedding_model=str(embedding.get("model", "")),
            embedding_dimensions=int(embedding.get("dimensions", 0)),
            embedding_dtype=str(embedding.get("dtype", "")),
            embedding_endianness=str(embedding.get("endianness", "")),
            indexed_embedding_model=model,
            indexed_embedding_dimensions=dimensions,
            reembedded=reembed,
            source_path=str(package),
        ))
    except Exception:
        store.drop_collection(namespace)
        raise
    return {
        "namespace": namespace,
        "package_id": package_id,
        "version": version,
        "rows": len(rows),
        "reembedded": reembed,
        "indexed_embedding_model": model,
        "indexed_embedding_dimensions": dimensions,
    }


def _entry(registry: ProjectionRegistry, store: Store, namespace: str) -> dict[str, Any]:
    entry = registry.resolve(namespace, store.collections())
    if not entry["collection_present"]:
        raise ProjectionError(
            f"{namespace!r} is recorded as {entry['recorded_state']} but its collection is gone; "
            "refusing to make an absent projection active"
        )
    return entry


def _demote_current_active(
    registry: ProjectionRegistry,
    store: Store,
    package_id: str,
    *,
    reason: str,
) -> str | None:
    """Move the package's active version aside so a new one can take the slot."""
    for entry in registry.active(store.collections()):
        if entry.get("package_id") == package_id:
            registry.transition(
                entry["namespace"], ProjectionState.ROLLBACK_TARGET, note=reason
            )
            return entry["namespace"]
    return None


def activate(
    namespace: str,
    *,
    registry: ProjectionRegistry,
    store: Store,
    activated_by: str,
) -> dict[str, Any]:
    """Make a staged projection available to retrieval.

    Activation does not inject anything into context and is not permission to
    resume work. ``activated_by`` is recorded and not enforced — see the
    registry module docstring.
    """
    entry = _entry(registry, store, namespace)
    # Check the target BEFORE demoting anything. Demoting first and discovering
    # afterwards that the target cannot legally become active leaves the
    # package with nothing active at all, while the caller is told the call was
    # refused — a refusal that silently took retrieval down. rollback() already
    # gets this ordering right. ACTIVE stays allowed so re-activating a live
    # projection is a no-op rather than an error; an unregistered but present
    # collection has recorded_state None and is refused here.
    if entry["recorded_state"] not in ("staged", "rollback_target", "active"):
        raise ProjectionError(
            f"{namespace!r} is {entry['recorded_state']}, not activatable"
        )
    superseded = _demote_current_active(
        registry, store, entry["package_id"], reason=f"superseded by {namespace}"
    )
    registry.transition(namespace, ProjectionState.ACTIVE, activated_by=activated_by)
    return {"active": namespace, "superseded": superseded}


def rollback(
    namespace: str,
    *,
    registry: ProjectionRegistry,
    store: Store,
    activated_by: str,
    reason: str = "",
) -> dict[str, Any]:
    """Return a previous version to active. Moves the pointer, touches no rows.

    The target's collection must actually be present. Without that check a
    rollback naming a deleted version would open an empty collection through
    the ordinary create-or-open path and report it as active — the failure this
    whole slice exists to prevent.
    """
    entry = _entry(registry, store, namespace)
    if entry["reported_state"] != ProjectionState.ROLLBACK_TARGET.value:
        raise ProjectionError(
            f"{namespace!r} is {entry['reported_state']}, not a rollback target"
        )
    demoted = _demote_current_active(
        registry, store, entry["package_id"], reason=reason or f"rolled back to {namespace}"
    )
    registry.transition(namespace, ProjectionState.ACTIVE, activated_by=activated_by, note=reason)
    return {"active": namespace, "rolled_back_from": demoted}


def retire(
    namespace: str,
    *,
    registry: ProjectionRegistry,
    store: Store,
    reason: str = "",
) -> dict[str, Any]:
    """Remove a projection from ordinary retrieval, preserving its audit record."""
    registry.resolve(namespace, store.collections())
    registry.transition(namespace, ProjectionState.RETIRED, note=reason)
    return {"retired": namespace}
