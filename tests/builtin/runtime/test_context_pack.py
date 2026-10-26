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

"""Interoperate with a receiver that serializes equivalent JSON independently."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from powercontext.builtin.runtime.context_pack import ContextPack, ContextPackError


def _oracle_pack_document() -> dict[str, object]:
    unsigned: dict[str, object] = {
        "schema": "powercontext.context-pack.v1",
        "items": [base64.b64encode(item).decode("ascii") for item in (b"alpha\n", "海洋".encode())],
    }
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    payload = {**unsigned, "digest": "sha256:" + hashlib.sha256(canonical).hexdigest(), "byte_count": 0}
    while True:
        size = len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        if payload["byte_count"] == size:
            return payload
        payload["byte_count"] = size


@pytest.mark.parametrize("indent", [None, 2])
def test_pack_decoder_accepts_equivalent_json_with_canonical_byte_count(indent: int | None) -> None:
    payload = _oracle_pack_document()
    wire = json.dumps(payload, indent=indent).encode()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert wire != canonical

    pack = ContextPack.from_bytes(wire)

    assert pack.items == (b"alpha\n", "海洋".encode())
    assert pack.byte_count == len(canonical)
    assert pack.to_bytes() == canonical


def test_pack_decoder_rejects_size_of_noncanonical_input_instead_of_canonical_document() -> None:
    payload = _oracle_pack_document()
    wire = json.dumps(payload, indent=2).encode()
    payload["byte_count"] = len(wire)

    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(json.dumps(payload, indent=2).encode())


def test_pack_decoder_rejects_duplicate_fields_even_when_their_values_match() -> None:
    payload = _oracle_pack_document()
    wire = json.dumps(payload).encode()
    duplicate = b'{"schema":"powercontext.context-pack.v1",' + wire[1:]

    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(duplicate)
