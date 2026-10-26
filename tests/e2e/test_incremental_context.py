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

from __future__ import annotations

import asyncio

from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    PrepareContextRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.context_pack import ContextPack, ContextPackDelta, apply_context_pack_delta
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource


class _Pipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(kind="conversation-turn", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


def test_incremental_prepare_preserves_query_selection_and_empty_results() -> None:
    async def scenario() -> None:
        async with open_builtin_runtime(BuiltinConfig(), candidate_pipeline=_Pipeline()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="Query selection", summary="Incremental compatibility", idempotency_key="incremental")
            )
            sources = runtime.sources.for_scope(scope.scope_id)
            memory = runtime.memory.for_scope(scope.scope_id)
            context = runtime.context.for_scope(scope.scope_id)
            texts = [f"Agenda {index}: discuss garden maintenance and office equipment." for index in range(10)]
            texts[7] = "Quartz calibration requires the laboratory reference frequency of 32768 Hz."
            for index, text in enumerate(texts):
                await sources.capture(CaptureSource(source_id=f"turn-{index}", content=text, metadata={}))
                while (await memory.flush()).processed:
                    pass

            hits = await memory.search(SearchMemoryRequest(query="quartz", mode="fts", limit=10))
            assert len(hits.hits) == 1
            request = PrepareContextRequest(query="quartz", max_bytes=16000)
            ordinary = await context.prepare(request)
            assert ordinary.content is not None and texts[7] in ordinary.content
            assert all(text not in ordinary.content for index, text in enumerate(texts) if index != 7)
            assert not ordinary.content.endswith("\nquartz")

            first = await context.prepare_incremental(request)
            assert isinstance(first, ContextPack)
            base = ContextPack.from_bytes(first.to_bytes())
            assert b"".join(base.items) == ordinary.content.encode()
            empty_request = PrepareContextRequest(query="zzzxynonexistent", max_bytes=16000)
            empty = await context.prepare(empty_request)
            assert empty.status == "empty" and empty.content is None
            delta = await context.prepare_incremental(empty_request, base_pack=base)
            assert isinstance(delta, ContextPackDelta)
            restored = apply_context_pack_delta(base, ContextPackDelta.from_bytes(delta.to_bytes()))
            assert restored.items == ()

            next_delta = await context.prepare_incremental(request, base_pack=restored)
            assert isinstance(next_delta, ContextPackDelta)
            replay = apply_context_pack_delta(restored, ContextPackDelta.from_bytes(next_delta.to_bytes()))
            assert b"".join(replay.items) == ordinary.content.encode()

    asyncio.run(scenario())
