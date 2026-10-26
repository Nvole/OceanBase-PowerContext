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

"""Capture one Pi v3 branch as immutable event evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import quote

from pydantic import BaseModel, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    Source,
    SourceMaterialization,
    TextEvidence,
)

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
_CHECKPOINT_VERSION = 1
_CONTROL_CONTENT = frozenset({"thinking", "image", "redacted_thinking"})


class PiSessionInput(BaseModel):
    """UTF-8 JSONL bytes for one Pi session and the branch leaf to read."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected branch, including its original record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """Captured Pi event. Identity is the session id plus the event id."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class _ParsedSession:
    def __init__(
        self,
        session_id: str,
        entries: tuple[dict[str, Any], ...],
        events: tuple[PiEventInput, ...],
    ) -> None:
        self.session_id = session_id
        self.entries = entries
        self.events = events


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Return visible events from the leaf to the root, root first.

    Invalid encoding, JSON, or tree structure raises ``ValueError`` and yields
    no partial chain. Control nodes stay in the tree but do not become events.
    """

    return _parse_session(value.content, value.leaf_id).events


class PiEventTextEvidenceProjection:
    """Project one captured Pi event through the standard text-evidence shape."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


class PiEventSourceDefinition:
    """Resolve a visible Pi event into a captured Source and read it back."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    version = "1"
    source_class = PiEventSource
    projections = (PiEventTextEvidenceProjection(),)

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(
            name=_source_id(value.session_id, value.event_id),
            definition_version=self.version,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


PI_EVENT_SOURCE_DEFINITION = PiEventSourceDefinition()


class PiSessionConnector:
    """Import new visible events on one selected branch and resume after restart."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        parsed = _parse_session(self._path.read_bytes(), self._leaf_id)
        known_session, imported = _load_checkpoint(session.checkpoint)
        if known_session not in (None, parsed.session_id):
            _invalid("Pi session id changed after events were imported")
        digests = {str(record["id"]): _record_digest(record) for record in parsed.entries}
        for event_id, digest in imported.items():
            if digests.get(event_id) != digest:
                _invalid("imported Pi event was rewritten")
        updated = dict(imported)
        for event in parsed.events:
            if event.event_id in updated:
                continue
            await session.submit(_source_id(event.session_id, event.event_id), PI_EVENT_SOURCE_NAME, event)
            updated[event.event_id] = digests[event.event_id]
        checkpoint = {"version": _CHECKPOINT_VERSION, "session_id": parsed.session_id, "records": updated}
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint)


def _parse_session(content: bytes, leaf_id: str | None) -> _ParsedSession:
    records = _load_records(content)
    if not records:
        _invalid("Pi session is empty")
    header, *entries = records
    session_id = _session_id(header)
    by_id = _index_entries(entries)
    if leaf_id is None:
        if not entries:
            _invalid("Pi session leaf was not found")
        selected = str(entries[-1]["id"])
    else:
        selected = leaf_id
    events: list[PiEventInput] = []
    for event_id in _ancestor_ids(by_id, selected):
        event = _visible_event(session_id, by_id[event_id])
        if event is not None:
            events.append(event)
    return _ParsedSession(session_id, tuple(entries), tuple(events))


def _load_records(content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        detail = "Pi session is not valid UTF-8"
        raise ValueError(detail) from error
    records: list[dict[str, Any]] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            detail = "Pi session line is not valid JSON"
            raise ValueError(detail) from error
        if not isinstance(value, dict):
            _invalid("Pi session line must be a JSON object")
        records.append(value)
    return records


def _session_id(header: dict[str, Any]) -> str:
    version = header.get("version")
    session_id = header.get("id")
    if header.get("type") != "session" or type(version) is not int or version != 3:
        _invalid("Pi session header must be version 3")
    if not isinstance(session_id, str) or session_id == "":
        _invalid("Pi session id must be a non-empty string")
    return session_id


def _index_entries(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for record in entries:
        event_id = record.get("id")
        if not isinstance(event_id, str) or event_id == "" or event_id in by_id:
            _invalid("Pi session event id must be unique")
        if "parentId" not in record:
            _invalid("Pi session event is missing parentId")
        parent_id = record["parentId"]
        if parent_id is not None and (not isinstance(parent_id, str) or parent_id not in by_id):
            _invalid("Pi session parent is missing or cyclic")
        by_id[event_id] = record
    return by_id


def _ancestor_ids(by_id: dict[str, dict[str, Any]], leaf_id: str) -> tuple[str, ...]:
    if leaf_id not in by_id:
        _invalid("Pi session leaf was not found")
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = leaf_id
    while current is not None:
        if current in seen:
            _invalid("Pi session contains a cycle")
        seen.add(current)
        chain.append(current)
        parent_id = by_id[current].get("parentId")
        current = parent_id if isinstance(parent_id, str) else None
    chain.reverse()
    return tuple(chain)


def _visible_event(session_id: str, record: dict[str, Any]) -> PiEventInput | None:
    event_type = record.get("type")
    event_id = record.get("id")
    if not isinstance(event_type, str) or not isinstance(event_id, str):
        return None
    rendered = _render_event(event_type, record)
    if rendered is None:
        return None
    role, body = rendered
    parent_id = record.get("parentId")
    return PiEventInput(
        session_id=session_id,
        event_id=event_id,
        parent_id=parent_id if isinstance(parent_id, str) else None,
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _render_event(event_type: str, record: dict[str, Any]) -> tuple[str, str] | None:
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if not isinstance(role, str) or role == "":
            return None
        if role == "toolResult":
            return role, _tool_result_body(message)
        if role == "bashExecution":
            return role, _bash_body(message)
        body = _message_body(message.get("content"))
        if body is None:
            return None
        return role, body
    if event_type in {"compaction", "branch_summary"}:
        summary = record.get("summary")
        if not isinstance(summary, str) or summary == "":
            return None
        return event_type, summary
    if event_type == "custom_message":
        body = _message_body(record.get("content"))
        if body is None:
            return None
        return "custom", body
    return None


def _message_body(content: object) -> str | None:
    if isinstance(content, str):
        return content if content != "" else None
    if not isinstance(content, list):
        return None
    parts = [part for block in content if (part := _block_text(block)) is not None]
    if not parts:
        return None
    body = "\n".join(parts)
    return body if body != "" else None


def _block_text(block: object) -> str | None:
    if isinstance(block, str):
        return block if block != "" else None
    if not isinstance(block, dict):
        return None
    block_type = block.get("type")
    if block_type in _CONTROL_CONTENT:
        return None
    if block_type == "text":
        text = block.get("text")
        if not isinstance(text, str) or text == "":
            return None
        return text
    if block_type == "toolCall":
        return _tool_call_body(block)
    return None


def _tool_call_body(block: dict[str, Any]) -> str:
    name = _text_field(block, "name")
    call_id = _text_field(block, "id")
    if call_id == "":
        call_id = _text_field(block, "toolCallId")
    arguments = block.get("arguments", {})
    return f"[tool_call {name} {call_id}] {_compact_json(arguments)}"


def _tool_result_body(message: dict[str, Any]) -> str:
    name = _text_field(message, "toolName")
    call_id = _text_field(message, "toolCallId")
    text = _plain_text(message.get("content"))
    prefix = f"[tool_result {name} {call_id}]"
    if text == "":
        return prefix
    return f"{prefix} {text}"


def _bash_body(message: dict[str, Any]) -> str:
    command = _text_field(message, "command")
    output = _text_field(message, "output")
    return f"$ {command}\n{output}"


def _plain_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            if block != "":
                parts.append(block)
            continue
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text != "":
            parts.append(text)
    return "\n".join(parts)


def _text_field(value: dict[str, Any], key: str) -> str:
    field = value.get(key)
    return field if isinstance(field, str) else ""


def _compact_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        detail = "Pi tool arguments are not JSON"
        raise ValueError(detail) from error


def _source_id(session_id: str, event_id: str) -> str:
    encoded = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(encoded) <= MAX_SOURCE_ID_LENGTH:
        return encoded
    payload = _framed(session_id) + _framed(event_id)
    return f"pi:{hashlib.sha256(payload).hexdigest()}"


def _framed(value: str) -> bytes:
    encoded = value.encode()
    return len(encoded).to_bytes(8, "big") + encoded


def _record_digest(record: dict[str, Any]) -> str:
    try:
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        detail = "Pi session record is not JSON"
        raise ValueError(detail) from error
    return hashlib.sha256(encoded.encode()).hexdigest()


def _load_checkpoint(value: JsonValue | None) -> tuple[str | None, dict[str, str]]:
    if value is None:
        return None, {}
    if not isinstance(value, dict) or value.get("version") != _CHECKPOINT_VERSION:
        _invalid("Pi session checkpoint is invalid")
    session_id = value.get("session_id")
    records = value.get("records")
    if session_id is not None and not isinstance(session_id, str):
        _invalid("Pi session checkpoint is invalid")
    if not isinstance(records, dict):
        _invalid("Pi session checkpoint is invalid")
    imported: dict[str, str] = {}
    for event_id, digest in records.items():
        if not isinstance(event_id, str) or not isinstance(digest, str):
            _invalid("Pi session checkpoint is invalid")
        imported[event_id] = digest
    return session_id, imported


def _invalid(detail: str) -> NoReturn:
    raise ValueError(detail)


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
]
