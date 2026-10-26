# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Propagate source availability across an explicit evidence DAG.

Native Memory eligibility is the Memory entry state written by
``MemoryService.forget`` / ``reactivate``. Those calls keep the entry body
version and drop or restore search projections. The graph document is saved
only after those writes succeed, so a failed native write stays retryable
instead of looking like a committed event replay.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import insert, select, update

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory.errors import InvalidMemoryCitationError
from powercontext.builtin.artifacts.topic_memory.errors import TopicMemoryError
from powercontext.builtin.persistence.errors import RepositoryError
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_TABLE
from powercontext.builtin.records import BaseAccessError
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.errors import RevisionConflictError
from powercontext.sources import SourceRef

_MEMORY_FAMILY = "memory"
_TOPIC_FAMILY = "topic-memory"
_POLICIES = frozenset({"all", "any"})
_PURPOSES = frozenset({"generation", "audit"})
_UNREADABLE = (
    LookupError,
    InvalidMemoryCitationError,
    RevisionConflictError,
    BaseAccessError,
    TopicMemoryError,
    RepositoryError,
)


class SourceLifecycleError(ValueError):
    """A rejected source-lifecycle registration or event."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SourceLifecycleEvent(BaseModel):
    """One availability change for an already registered source."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    node_id: str
    reason: str
    revision: int
    sequence: int
    available: bool

    @field_validator("node_id", "reason")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not isinstance(value, str) or value.strip() == "":
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("revision", "sequence")
    @classmethod
    def reject_non_positive(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("must be a positive integer")
        return value


@dataclass
class _Node:
    kind: str
    available: bool
    parents: tuple[str, ...]
    policy: str | None
    revision: int | None
    reference: dict[str, Any]
    last_event: dict[str, Any] | None

    def binding(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "revision": self.revision,
            "reference": self.reference,
            "parents": list(self.parents),
            "policy": self.policy,
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "available": self.available,
            "parents": list(self.parents),
            "policy": self.policy,
            "revision": self.revision,
            "reference": self.reference,
            "last_event": self.last_event,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> _Node:
        last_event = payload["last_event"]
        return cls(
            kind=str(payload["kind"]),
            available=bool(payload["available"]),
            parents=tuple(payload["parents"]),
            policy=None if payload["policy"] is None else str(payload["policy"]),
            revision=None if payload["revision"] is None else int(payload["revision"]),
            reference=dict(payload["reference"]),
            last_event=None if last_event is None else dict(last_event),
        )


def _positive_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SourceLifecycleError("revision")
    return value


def _node_id(value: object) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise SourceLifecycleError("node-id")
    return value


def _parents(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise SourceLifecycleError("parents")
    parents: list[str] = []
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            raise SourceLifecycleError("parents")
        parents.append(item)
    if len(parents) != len(set(parents)):
        raise SourceLifecycleError("duplicate-parent")
    return tuple(parents)


def _policy(value: object) -> str:
    if not isinstance(value, str) or value not in _POLICIES:
        raise SourceLifecycleError("policy")
    return value


def _event(value: object) -> SourceLifecycleEvent:
    if isinstance(value, SourceLifecycleEvent):
        return value
    if isinstance(value, Mapping):
        return SourceLifecycleEvent.model_validate(dict(value))
    raise SourceLifecycleError("event")


def _database(runtime: object):
    provider = getattr(runtime, "_provider", None)
    database = getattr(provider, "database", None)
    if database is None:
        raise SourceLifecycleError("database")
    return database


def _encode(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode(blob: object) -> dict[str, Any]:
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    if isinstance(blob, str):
        payload = json.loads(blob)
    else:
        payload = json.loads(bytes(blob).decode("utf-8"))
    if not isinstance(payload, dict):
        raise SourceLifecycleError("document")
    return payload


async def _load(runtime: object, scope_id: str) -> dict[str, _Node]:
    async with _database(runtime).transaction() as connection:
        result = await connection.execute(
            select(SOURCE_LIFECYCLE_TABLE.c.document).where(SOURCE_LIFECYCLE_TABLE.c.scope_id == scope_id)
        )
        row = result.first()
    if row is None or row[0] is None:
        return {}
    nodes: dict[str, _Node] = {}
    for node_id, raw in _decode(row[0]).get("nodes", {}).items():
        nodes[str(node_id)] = _Node.from_json(raw)
    return nodes


async def _save(runtime: object, scope_id: str, nodes: Mapping[str, _Node]) -> None:
    document = _encode({"version": 1, "nodes": {node_id: node.to_json() for node_id, node in nodes.items()}})
    async with _database(runtime).transaction() as connection:
        existing = await connection.execute(
            select(SOURCE_LIFECYCLE_TABLE.c.scope_id).where(SOURCE_LIFECYCLE_TABLE.c.scope_id == scope_id)
        )
        if existing.first() is None:
            await connection.execute(insert(SOURCE_LIFECYCLE_TABLE).values(scope_id=scope_id, document=document))
            return
        await connection.execute(
            update(SOURCE_LIFECYCLE_TABLE)
            .where(SOURCE_LIFECYCLE_TABLE.c.scope_id == scope_id)
            .values(document=document)
        )


def _active_ids(nodes: Mapping[str, _Node]) -> list[str]:
    return sorted(node_id for node_id, node in nodes.items() if node.available)


def _require_dag(nodes: Mapping[str, _Node], node_id: str, parents: Sequence[str]) -> None:
    if node_id in parents:
        raise SourceLifecycleError("cycle")
    missing = [parent for parent in parents if parent not in nodes]
    if missing:
        raise SourceLifecycleError("missing-parent")
    seen: set[str] = set()
    stack = list(parents)
    while stack:
        current = stack.pop()
        if current == node_id:
            raise SourceLifecycleError("cycle")
        if current in seen:
            continue
        seen.add(current)
        parent = nodes.get(current)
        if parent is not None:
            stack.extend(parent.parents)


def _supported(node: _Node, nodes: Mapping[str, _Node]) -> bool:
    flags = tuple(nodes[parent].available for parent in node.parents)
    if node.policy == "all":
        return all(flags)
    return any(flags)


def _recompute(nodes: dict[str, _Node]) -> None:
    pending = set(nodes)
    indegree = {node_id: len(node.parents) for node_id, node in nodes.items()}
    children: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for node_id, node in nodes.items():
        for parent in node.parents:
            children[parent].append(node_id)
    while pending:
        ready = sorted(node_id for node_id in pending if indegree[node_id] == 0)
        if not ready:
            raise SourceLifecycleError("cycle")
        current = ready[0]
        pending.remove(current)
        node = nodes[current]
        if node.kind != "source":
            node.available = _supported(node, nodes)
        for child in children[current]:
            indegree[child] -= 1


def _materialize(node: _Node) -> SourceRef | MemoryCitation | ArtifactRef:
    ref = node.reference
    if node.kind == "source":
        return SourceRef(source_type=ref["source_type"], source_id=ref["source_id"])
    if node.kind == "memory":
        return MemoryCitation(
            memory_ref=ArtifactRef(
                family=ref["family"],
                artifact_id=ref["artifact_id"],
                revision=int(ref["revision"]),
            ),
            entry_id=ref["entry_id"],
            entry_version_id=ref["entry_version_id"],
        )
    return ArtifactRef(family=ref["family"], artifact_id=ref["artifact_id"], revision=int(ref["revision"]))


def _audit_reason(reason: str | None) -> str:
    text = "source-lifecycle" if reason is None else reason.strip()
    if not text:
        text = "source-lifecycle"
    return text[:512]


def _same_event(stored: Mapping[str, Any], event: SourceLifecycleEvent) -> bool:
    return (
        int(stored["sequence"]) == event.sequence
        and int(stored["revision"]) == event.revision
        and bool(stored["available"]) is event.available
        and stored["reason"] == event.reason
    )


async def _sync_memory(service: object, node: _Node, reason: str) -> None:
    ref = node.reference
    try:
        head = await service.head(ref["artifact_id"])  # type: ignore[attr-defined]
        versions = await service.entries(head)  # type: ignore[attr-defined]
    except LookupError as error:
        raise SourceLifecycleError("memory-entry") from error
    version = next(
        (
            item
            for item in versions
            if item.entry_id == ref["entry_id"] and item.entry_version_id == ref["entry_version_id"]
        ),
        None,
    )
    manifest = next((item for item in head.content.manifest.entries if item.entry_id == ref["entry_id"]), None)
    if version is None or manifest is None or manifest.entry_version_id != ref["entry_version_id"]:
        raise SourceLifecycleError("memory-entry")
    target = "active" if node.available else "inactive"
    if manifest.state == target:
        return
    if node.available:
        await service.reactivate(head, entries=(version,), reason=reason)  # type: ignore[attr-defined]
        return
    await service.forget(head, entries=(version,), reason=reason)  # type: ignore[attr-defined]


async def _sync_memories(service: object, nodes: Mapping[str, _Node], reason: str | None) -> None:
    audit_reason = _audit_reason(reason)
    for node_id in sorted(nodes):
        node = nodes[node_id]
        if node.kind == "memory":
            await _sync_memory(service, node, audit_reason)


async def hidden_topic_artifact_ids(runtime: object, scope_id: str) -> set[str]:
    """Return topic artifact ids with no eligible lifecycle binding."""

    try:
        scope = validate_scope_id(scope_id)
    except ValueError:
        return set()
    nodes = await _load(runtime, scope)
    grouped: dict[str, list[bool]] = {}
    for node in nodes.values():
        if node.kind != "topic":
            continue
        grouped.setdefault(str(node.reference["artifact_id"]), []).append(node.available)
    return {artifact_id for artifact_id, flags in grouped.items() if not any(flags)}


class LifecycleTopicSearch:
    """Drop topic hits whose registered evidence no longer supports them."""

    def __init__(self, runtime: object, inner: object) -> None:
        self._runtime = runtime
        self._inner = inner

    async def __call__(
        self,
        scope_id: str,
        query: str,
        /,
        *,
        limit: int,
        mode: str = "auto",
        query_vector: tuple[float, ...] | None = None,
        embedding_profile: object = None,
        admission: object = None,
        query_embedding: object = None,
    ) -> object:
        result = await self._inner(  # type: ignore[operator]
            scope_id,
            query,
            limit=limit,
            mode=mode,
            query_vector=query_vector,
            embedding_profile=embedding_profile,
            admission=admission,
            query_embedding=query_embedding,
        )
        hidden = await hidden_topic_artifact_ids(self._runtime, scope_id)
        if not hidden:
            return result
        hits = tuple(hit for hit in result.hits if hit.artifact_ref.artifact_id not in hidden)
        if len(hits) == len(result.hits):
            return result
        return result.model_copy(update={"hits": hits})


class ScopedSourceLifecycle:
    """Register and propagate one scope's explicit evidence DAG."""

    def __init__(self, runtime: object, scope_id: str) -> None:
        self._runtime = runtime
        self.scope_id = validate_scope_id(scope_id)

    async def register_source(self, node_id: str, source_ref: SourceRef, revision: int) -> None:
        identity = _node_id(node_id)
        selected_revision = _positive_revision(revision)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source-ref")
        reference = {"source_type": source_ref.source_type, "source_id": source_ref.source_id}
        binding = {
            "kind": "source",
            "revision": selected_revision,
            "reference": reference,
            "parents": [],
            "policy": None,
        }
        async with self._runtime._context(self.scope_id):  # type: ignore[attr-defined]
            async with self._runtime._locked(self.scope_id):  # type: ignore[attr-defined]
                nodes = await _load(self._runtime, self.scope_id)
                existing = nodes.get(identity)
                if existing is not None:
                    if existing.binding() == binding:
                        return
                    raise SourceLifecycleError("conflict")
                await self._require_source(source_ref)
                nodes[identity] = _Node(
                    kind="source",
                    available=True,
                    parents=(),
                    policy=None,
                    revision=selected_revision,
                    reference=reference,
                    last_event=None,
                )
                await _save(self._runtime, self.scope_id, nodes)

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        parents: Sequence[str],
        policy: str,
    ) -> None:
        if not isinstance(citation, MemoryCitation) or citation.memory_ref.family != _MEMORY_FAMILY:
            raise SourceLifecycleError("memory-citation")
        reference = {
            "family": citation.memory_ref.family,
            "artifact_id": citation.memory_ref.artifact_id,
            "revision": citation.memory_ref.revision,
            "entry_id": citation.entry_id,
            "entry_version_id": citation.entry_version_id,
        }
        await self._register_derived(node_id, "memory", reference, parents, policy, citation=citation)

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        parents: Sequence[str],
        policy: str,
    ) -> None:
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != _TOPIC_FAMILY:
            raise SourceLifecycleError("topic-ref")
        reference = {
            "family": artifact_ref.family,
            "artifact_id": artifact_ref.artifact_id,
            "revision": artifact_ref.revision,
        }
        await self._register_derived(node_id, "topic", reference, parents, policy, artifact_ref=artifact_ref)

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        selected = _event(event)
        async with self._runtime._context(self.scope_id) as context:  # type: ignore[attr-defined]
            async with self._runtime._locked(self.scope_id):  # type: ignore[attr-defined]
                nodes = await _load(self._runtime, self.scope_id)
                node = nodes.get(selected.node_id)
                if node is None or node.kind != "source":
                    raise SourceLifecycleError("unknown-source")
                if node.revision != selected.revision:
                    raise SourceLifecycleError("revision")
                if node.last_event is not None:
                    if selected.sequence < int(node.last_event["sequence"]):
                        raise SourceLifecycleError("sequence")
                    if selected.sequence == int(node.last_event["sequence"]):
                        if _same_event(node.last_event, selected):
                            return _active_ids(nodes)
                        raise SourceLifecycleError("sequence")
                node.available = selected.available
                node.last_event = {
                    "sequence": selected.sequence,
                    "revision": selected.revision,
                    "available": selected.available,
                    "reason": selected.reason,
                }
                _recompute(nodes)
                await _sync_memories(context.artifacts.memory, nodes, selected.reason)
                await _save(self._runtime, self.scope_id, nodes)
                return _active_ids(nodes)

    async def resolve(self, node_id: str, purpose: str) -> SourceRef | MemoryCitation | ArtifactRef:
        if purpose not in _PURPOSES:
            raise SourceLifecycleError("purpose")
        identity = _node_id(node_id)
        async with self._runtime._scoped_operation(self.scope_id):  # type: ignore[attr-defined]
            nodes = await _load(self._runtime, self.scope_id)
        node = nodes.get(identity)
        if node is None:
            raise SourceLifecycleError("unknown-node")
        if purpose == "generation" and not node.available:
            raise SourceLifecycleError("unavailable")
        return _materialize(node)

    async def _register_derived(
        self,
        node_id: str,
        kind: str,
        reference: dict[str, Any],
        parents: Sequence[str],
        policy: str,
        *,
        citation: MemoryCitation | None = None,
        artifact_ref: ArtifactRef | None = None,
    ) -> None:
        identity = _node_id(node_id)
        selected_parents = _parents(parents)
        selected_policy = _policy(policy)
        binding = {
            "kind": kind,
            "revision": None,
            "reference": reference,
            "parents": list(selected_parents),
            "policy": selected_policy,
        }
        async with self._runtime._context(self.scope_id) as context:  # type: ignore[attr-defined]
            async with self._runtime._locked(self.scope_id):  # type: ignore[attr-defined]
                nodes = await _load(self._runtime, self.scope_id)
                existing = nodes.get(identity)
                if existing is not None:
                    if existing.binding() == binding:
                        return
                    raise SourceLifecycleError("conflict")
                _require_dag(nodes, identity, selected_parents)
                if citation is not None:
                    await self._require_memory(context.artifacts.memory, citation)
                if artifact_ref is not None:
                    await self._require_topic(artifact_ref)
                available = _supported(
                    _Node(kind, True, selected_parents, selected_policy, None, reference, None),
                    nodes,
                )
                nodes[identity] = _Node(
                    kind=kind,
                    available=available,
                    parents=selected_parents,
                    policy=selected_policy,
                    revision=None,
                    reference=reference,
                    last_event=None,
                )
                if kind == "memory":
                    await _sync_memory(context.artifacts.memory, nodes[identity], "source-lifecycle")
                await _save(self._runtime, self.scope_id, nodes)

    async def _require_source(self, source_ref: SourceRef) -> None:
        try:
            await self._runtime._records().get_source(  # type: ignore[attr-defined]
                self.scope_id,
                source_ref.source_type,
                source_ref.source_id,
            )
        except _UNREADABLE as error:
            raise SourceLifecycleError("unreadable") from error

    async def _require_memory(self, service: object, citation: MemoryCitation) -> None:
        try:
            await service.validate_citation(citation)  # type: ignore[attr-defined]
            head = await service.head(citation.memory_ref.artifact_id)  # type: ignore[attr-defined]
        except _UNREADABLE as error:
            raise SourceLifecycleError("unreadable") from error
        if not any(
            item.entry_id == citation.entry_id and item.entry_version_id == citation.entry_version_id
            for item in head.content.manifest.entries
        ):
            raise SourceLifecycleError("unreadable")

    async def _require_topic(self, artifact_ref: ArtifactRef) -> None:
        getter = self._runtime._topic_memory_get  # type: ignore[attr-defined]
        if getter is None:
            raise SourceLifecycleError("topic-memory")
        try:
            await getter(self.scope_id, artifact_ref)
        except _UNREADABLE as error:
            raise SourceLifecycleError("unreadable") from error


class SourceLifecycleApplication:
    """Select the source-lifecycle service for one scope."""

    def __init__(self, runtime: object) -> None:
        self._runtime = runtime

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self._runtime, scope_id)


__all__ = [
    "LifecycleTopicSearch",
    "SourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
]
