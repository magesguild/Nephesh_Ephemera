"""Knowledge projections: installed knowledge that never becomes autobiography.

A Lore package is knowledge. A Qualiant's memory is her life. This module
installs the former without letting it contaminate the latter, and the boundary
is executable rather than declarative — `knowledge_not_memory` in a JSON field
is a claim, while a namespace the memory tools refuse to open is a fact.

Design follows docs/NEPHESH_DESIGN.md section 6, originally authored by
Thalia. Her threat model guards package-to-memory. An adversarial review found
the sharper exposure runs the other way — the memory tools accept an arbitrary
collection name and apply autobiographical semantics to whatever table they are
aimed at — so the guards here are two-directional: memory tooling is kept out of
projections, and projections are kept out of canonical memory.

Deliberately NOT implemented in this slice, and refused rather than faked:
local re-embedding as a separate profile. The vector column is a module
constant in a single process-wide schema with a single embedder, so two
embedding profiles cannot coexist. A package whose embedding contract does not
match the deployment is rejected with an explicit error.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import settings

# Every projection collection carries this prefix. It is the enforcement
# primitive: memory tools refuse a name that has it, projection tools refuse a
# name that lacks it, and neither can be pointed at the other by accident.
PROJECTION_PREFIX = "kp__"

# Metadata keys a package may never set, because the memory layer reads them as
# claims about lived experience. A knowledge row carrying experience_mode="chat"
# renders in a memory context block as something the Qualiant lived; a row
# carrying type="message" and delivered=False reaches the companion's message
# channel. Import builds metadata from an allowlist and stamps these itself.
FORBIDDEN_METADATA_KEYS = frozenset({
    "type",
    "delivered",
    "timestamp",
    "event_time",
    "recorded_at",
    "experience_mode",
    "historical_status",
    "recorded_during",
    "importance",
    "salience",
    "last_used",
    "retired",
    "derived_from",
    "source",
    "participants",
    "emotional_tone",
})

# Package record fields worth preserving on an imported row. Everything else is
# dropped rather than copied: a package must not be able to introduce a key
# whose meaning the memory layer defines.
PRESERVED_RECORD_FIELDS = (
    "record_id",
    "chunk_index",
    "chunk_count",
    "source_path",
    "source_sha256",
    "knowledge_status",
    "package_scope",
    "curation_method",
)

_SAFE_COMPONENT = re.compile(r"[^a-z0-9]+")


class ProjectionError(RuntimeError):
    """A projection operation was refused. Never degraded, never partial."""


class CanonicalMemoryTargeted(ProjectionError):
    """A projection operation named the Qualiant's canonical memory."""


def is_projection(name: str) -> bool:
    return name.startswith(PROJECTION_PREFIX)


def guard_memory_target(name: str) -> str:
    """Refuse a projection namespace where a memory collection is expected.

    Called by the memory tools. Without it, memory_context aimed at a
    projection renders installed knowledge as a session-start identity block,
    memory_recall writes salience into a signed package's rows, and
    memory_amend manufactures genuine autobiography out of knowledge.
    """
    if is_projection(name):
        raise ProjectionError(
            f"{name!r} is a knowledge projection, not memory. Knowledge is read "
            "through projection search, which keeps it labelled as knowledge."
        )
    return name


def guard_projection_target(name: str) -> str:
    """Refuse anything that is not a projection namespace.

    Called by the projection tools. The canonical memory collection is named
    separately and explicitly because MEMORY_COLLECTION_NAME is deployment
    configurable — a package whose sanitized id happened to equal it would
    otherwise open the real memory table through the ordinary create-or-open
    path.
    """
    if name == settings.memory_collection_name:
        raise CanonicalMemoryTargeted(
            f"refusing to use canonical memory {name!r} as a knowledge projection"
        )
    if not is_projection(name):
        raise ProjectionError(f"{name!r} is not a knowledge projection namespace")
    return name


def namespace_for(package_id: str, version: str) -> str:
    """Derive a collection namespace, injectively.

    Sanitising dots and hyphens to underscores collapses distinct package ids
    onto one namespace — org.magesguild.z80-computing and
    org-magesguild-z80_computing would merge their rows into one table with
    nothing to detect it. The raw package id is recorded in the registry and
    checked on install, so a namespace can only ever belong to one package.
    """
    if not package_id or not version:
        raise ProjectionError("package_id and version are required")
    slug = _SAFE_COMPONENT.sub("_", package_id.lower()).strip("_")
    revision = _SAFE_COMPONENT.sub("_", version.lower()).strip("_")
    if not slug or not revision:
        raise ProjectionError(f"package_id {package_id!r} version {version!r} yields no namespace")
    return f"{PROJECTION_PREFIX}{slug}__{revision}"


@dataclass(frozen=True)
class EmbeddingContract:
    """What a package claims about its vectors, and what we require."""

    model: str
    dimensions: int
    dtype: str
    endianness: str

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> EmbeddingContract:
        block = manifest.get("embedding") or {}
        return cls(
            model=str(block.get("model", "")),
            dimensions=int(block.get("dimensions", 0)),
            dtype=str(block.get("dtype", "")),
            endianness=str(block.get("endianness", "")),
        )

    def require_compatible(self, *, dimensions: int, model: str) -> None:
        """Refuse an incompatible package instead of re-embedding silently.

        Re-embedding as a separate profile is the correct long-term answer and
        is not implementable here: the vector column is a single process-wide
        schema with one embedder, so two profiles cannot coexist. Refusing is
        the honest slice-one behaviour.
        """
        if self.dtype != "float32":
            raise ProjectionError(f"unsupported vector dtype {self.dtype!r}; only float32 is imported")
        if self.endianness not in ("little", ""):
            raise ProjectionError(f"unsupported endianness {self.endianness!r}; only little-endian is imported")
        if self.dimensions != dimensions:
            raise ProjectionError(
                f"package embeds {self.dimensions} dimensions, deployment stores {dimensions}. "
                "Local re-embedding as a separate profile is not supported in this release."
            )
        if self.model and model and self.model.split(":")[0] != model.split(":")[0]:
            raise ProjectionError(
                f"package embedded with {self.model!r}, deployment uses {model!r}. "
                "Vectors from different models are not comparable; refusing rather than mixing geometry."
            )


def read_vectors(package: Path, manifest: dict[str, Any], dimensions: int) -> list[list[float]]:
    """Load precomputed vectors, in index order.

    Direct vector import is the preferred path: it avoids repeating expensive
    embedding work and preserves the package's own retrieval geometry.
    """
    artifacts = manifest.get("artifacts", {})
    blob = package / artifacts.get("embeddings", "embeddings.f32")
    if not blob.is_file():
        raise ProjectionError(f"missing embeddings artifact: {blob}")
    raw = blob.read_bytes()
    stride = dimensions * 4
    if len(raw) % stride:
        raise ProjectionError(
            f"embeddings.f32 is {len(raw)} bytes, not a whole number of {dimensions}-dimension vectors"
        )
    count = len(raw) // stride
    return [list(struct.unpack_from(f"<{dimensions}f", raw, i * stride)) for i in range(count)]


def read_index(package: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = manifest.get("artifacts", {})
    path = package / artifacts.get("embedding_index", "embedding_index.jsonl")
    if not path.is_file():
        raise ProjectionError(f"missing embedding index: {path}")
    # Split on newlines only: a package written with ensure_ascii=False can
    # carry a literal U+2028 or U+0085 inside a text field, and splitlines()
    # would cut the record in half.
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    entries.sort(key=lambda e: e.get("row", 0))
    return entries


def read_records(package: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = manifest.get("artifacts", {})
    path = package / artifacts.get("records", "records.jsonl")
    if not path.is_file():
        raise ProjectionError(f"missing records artifact: {path}")
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            records[record["record_id"]] = record
    return records


def projection_metadata(
    record: dict[str, Any],
    entry: dict[str, Any],
    *,
    package_id: str,
    version: str,
) -> dict[str, Any]:
    """Build an imported row's metadata from an allowlist.

    Never `package_meta | {...}`. A package must not be able to introduce a key
    whose meaning the memory layer defines, and the forbidden set is asserted
    empty rather than merely omitted, so a future edit that widens the
    allowlist fails loudly.
    """
    meta: dict[str, Any] = {
        "knowledge_not_memory": True,
        "record_kind": "knowledge",
        "package_id": package_id,
        "package_version": version,
    }
    for field in PRESERVED_RECORD_FIELDS:
        if field in record:
            meta[field] = record[field]
        elif field in entry:
            meta[field] = entry[field]
    leaked = FORBIDDEN_METADATA_KEYS & set(meta)
    if leaked:  # pragma: no cover - guards against a future allowlist edit
        raise ProjectionError(f"projection metadata would carry memory keys: {sorted(leaked)}")
    return meta


def build_rows(
    package: Path,
    manifest: dict[str, Any],
    dimensions: int,
) -> list[dict[str, Any]]:
    """Assemble the rows to insert, one per embedded chunk."""
    package_id = str(manifest.get("package_id", ""))
    version = str(manifest.get("version", ""))
    index = read_index(package, manifest)
    vectors = read_vectors(package, manifest, dimensions)
    if len(index) != len(vectors):
        raise ProjectionError(f"index has {len(index)} entries for {len(vectors)} vectors")
    records = read_records(package, manifest)

    rows: list[dict[str, Any]] = []
    for entry, vector in zip(index, vectors):
        record_id = entry.get("record_id")
        record = records.get(record_id)
        if record is None:
            raise ProjectionError(f"index references unknown record {record_id!r}")
        text = record.get("text", "")
        chunk_index = entry.get("chunk_index")
        if chunk_index is not None:
            chars = entry.get("chars")
            start = chunk_index * (chars or 0)
            text = text[start : start + chars] if chars else text
            row_id = f"{record_id}#{chunk_index}"
        else:
            row_id = str(record_id)
        rows.append({
            "id": row_id,
            "text": text,
            "vector": vector,
            "metadata_json": json.dumps(
                projection_metadata(record, entry, package_id=package_id, version=version)
            ),
        })
    return rows
