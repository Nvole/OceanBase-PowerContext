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

"""Prefix-reusable context packs and their wire encoding.

Receivers rebuild a pack from the serialized bytes alone. The digest covers only ``schema`` and
``items``. ``byte_count`` is the length of the canonical pack JSON, including itself.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_B64_RE = re.compile(r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$")


class ContextPackError(Exception):
    """A context pack or delta failed a protocol or chunking check."""


@dataclass(frozen=True)
class ContextPack:
    """One complete context payload split into ordered chunks."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...] | Sequence[bytes]) -> ContextPack:
        """Build a canonical pack from chunk bytes."""

        normalized = _chunk_tuple(items)
        encoded = _canonical_pack_bytes(_encode_items(normalized), _digest_for(normalized))
        payload = json.loads(encoded)
        return cls(items=normalized, digest=payload["digest"], byte_count=payload["byte_count"])

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = 512) -> ContextPack:
        """Split text into deterministic UTF-8 chunks of at most ``chunk_bytes``."""

        if not isinstance(content, str):
            raise ContextPackError("content must be text")
        if type(chunk_bytes) is not int or chunk_bytes < 1:
            raise ContextPackError("chunk_bytes must be a positive integer")
        try:
            data = content.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ContextPackError("content is not valid Unicode") from error
        return cls.build(_split_utf8(data, chunk_bytes))

    def to_bytes(self) -> bytes:
        """Serialize this pack in canonical JSON."""

        return _validated_pack_bytes(self)

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        """Decode a pack and reject any digest, canonical size, or schema mismatch."""

        raw = _raw_bytes(data)
        payload = _load_object(raw, _PACK_FIELDS)
        if payload.get("schema") != PACK_SCHEMA:
            raise ContextPackError("pack schema")
        items = _decode_items(payload.get("items"))
        digest = payload.get("digest")
        byte_count = payload.get("byte_count")
        if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
            raise ContextPackError("pack digest")
        if type(byte_count) is not int or byte_count < 0:
            raise ContextPackError("pack byte_count")
        pack = cls.build(items)
        if pack.digest != digest or pack.byte_count != byte_count:
            raise ContextPackError("pack check")
        return pack


@dataclass(frozen=True)
class ContextPackDelta:
    """Instructions for rebuilding a target pack from a prefix of a base pack."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        """Keep the longest chunk prefix that both packs share and append the target suffix."""

        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("pack endpoints")
        _validated_pack_bytes(base)
        _validated_pack_bytes(target)
        shared = 0
        limit = min(len(base.items), len(target.items))
        while shared < limit and base.items[shared] == target.items[shared]:
            shared += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=shared,
            appended=target.items[shared:],
        )

    def to_bytes(self) -> bytes:
        """Serialize this delta in canonical JSON. ``byte_count`` is not a field."""

        _validate_delta_fields(self)
        payload = {
            "schema": DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_items(self.appended),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        """Decode a delta object. JSON whitespace is ignored; fields and encodings are not."""

        payload = _load_object(_raw_bytes(data), _DELTA_FIELDS)
        if payload.get("schema") != DELTA_SCHEMA:
            raise ContextPackError("delta schema")
        delta = cls(
            base_digest=payload["base_digest"],
            target_digest=payload["target_digest"],
            prefix_items=payload["prefix_items"],
            appended=_decode_items(payload.get("appended")),
        )
        _validate_delta_fields(delta)
        return delta

    @property
    def byte_count(self) -> int:
        """Serialized size. This is not written into the delta JSON."""

        return len(self.to_bytes())


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild the target pack from ``base`` and ``delta`` alone."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta endpoints")
    _validated_pack_bytes(base)
    _validate_delta_fields(delta)
    if delta.base_digest != base.digest:
        raise ContextPackError("base digest")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("prefix_items")
    rebuilt = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if rebuilt.digest != delta.target_digest:
        raise ContextPackError("target digest")
    return rebuilt


def _chunk_tuple(items: tuple[bytes, ...] | Sequence[bytes]) -> tuple[bytes, ...]:
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise ContextPackError("items")
    normalized = tuple(items)
    if any(type(item) is not bytes for item in normalized):
        raise ContextPackError("items")
    return normalized


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("items")
    return tuple(_decode_b64(item) for item in value)


def _decode_b64(value: object) -> bytes:
    if not isinstance(value, str) or _B64_RE.fullmatch(value) is None:
        raise ContextPackError("base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ContextPackError("base64") from error
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ContextPackError("base64")
    return decoded


def _digest_for(items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": PACK_SCHEMA, "items": _encode_items(items)}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _canonical_pack_bytes(items_b64: list[str], digest: str) -> bytes:
    """Return pack JSON whose ``byte_count`` equals the encoded length."""

    # The decimal width of byte_count is the only variable part of an otherwise fixed document.
    sample = _pack_document(items_b64, digest, 0)
    base_length = len(sample) - 1
    for digits in range(1, 12):
        byte_count = base_length + digits
        if len(str(byte_count)) != digits:
            continue
        encoded = _pack_document(items_b64, digest, byte_count)
        if len(encoded) == byte_count:
            return encoded
    raise ContextPackError("byte_count")


def _pack_document(items_b64: list[str], digest: str, byte_count: int) -> bytes:
    payload = {
        "schema": PACK_SCHEMA,
        "items": items_b64,
        "digest": digest,
        "byte_count": byte_count,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validated_pack_bytes(pack: ContextPack) -> bytes:
    if type(pack.items) is not tuple or any(type(item) is not bytes for item in pack.items):
        raise ContextPackError("items")
    expected = _digest_for(pack.items)
    encoded = _canonical_pack_bytes(_encode_items(pack.items), expected)
    if (
        not isinstance(pack.digest, str)
        or pack.digest != expected
        or type(pack.byte_count) is not int
        or pack.byte_count != len(encoded)
    ):
        raise ContextPackError("pack check")
    return encoded


def _validate_delta_fields(delta: ContextPackDelta) -> None:
    if not isinstance(delta.base_digest, str) or _DIGEST_RE.fullmatch(delta.base_digest) is None:
        raise ContextPackError("base digest")
    if not isinstance(delta.target_digest, str) or _DIGEST_RE.fullmatch(delta.target_digest) is None:
        raise ContextPackError("target digest")
    if type(delta.prefix_items) is not int or delta.prefix_items < 0:
        raise ContextPackError("prefix_items")
    if type(delta.appended) is not tuple or any(type(item) is not bytes for item in delta.appended):
        raise ContextPackError("appended")


def _split_utf8(data: bytes, chunk_bytes: int) -> tuple[bytes, ...]:
    chunks: list[bytes] = []
    start = 0
    size = len(data)
    while start < size:
        end = min(start + chunk_bytes, size)
        # A continuation byte means the cut landed inside a code point.
        if end < size:
            while end > start and (data[end] & 0xC0) == 0x80:
                end -= 1
        if end == start:
            raise ContextPackError("utf-8 chunk boundary")
        chunk = data[start:end]
        try:
            chunk.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContextPackError("utf-8 chunk boundary") from error
        chunks.append(chunk)
        start = end
    return tuple(chunks)


def _raw_bytes(data: bytes | bytearray) -> bytes:
    if not isinstance(data, (bytes, bytearray)):
        raise ContextPackError("encoding")
    return bytes(data)


def _load_object(raw: bytes, fields: frozenset[str]) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContextPackError("encoding") from error

    def pairs(seq: list[tuple[Any, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in seq:
            if not isinstance(key, str) or key in obj:
                raise ContextPackError("field")
            obj[key] = value
        return obj

    try:
        payload = json.loads(text, object_pairs_hook=pairs)
    except ContextPackError:
        raise
    except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError) as error:
        raise ContextPackError("json") from error
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ContextPackError("field")
    return payload


__all__ = [
    "DELTA_SCHEMA",
    "PACK_SCHEMA",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
