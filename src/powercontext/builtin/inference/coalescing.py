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

"""Coalesce concurrent embedding requests and cache successful vectors."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel

_Vector = tuple[float, ...]


@dataclass(frozen=True, slots=True)
class _BatchCharge:
    """Usage of one underlying batch, shared by every caller that waited for it."""

    usage: InferenceUsage


_Outcome = tuple[_Vector, _BatchCharge | None]


class _Shared:
    """One text claimed for an underlying batch, with each caller's private waiter."""

    __slots__ = ("future", "waiters")

    def __init__(self, future: asyncio.Future[_Outcome]) -> None:
        self.future = future
        self.waiters: list[asyncio.Future[_Outcome]] = []


def _retrieve_exception(future: asyncio.Future[object]) -> None:
    if not future.cancelled():
        future.exception()


def _deliver(source: asyncio.Future[_Outcome], waiter: asyncio.Future[_Outcome]) -> None:
    if waiter.done():
        if not source.cancelled():
            source.exception()
        return
    if source.cancelled():
        waiter.cancel()
        return
    error = source.exception()
    if error is not None:
        waiter.set_exception(error)
        return
    waiter.set_result(source.result())


def _fan_out(source: asyncio.Future[_Outcome], waiter: asyncio.Future[_Outcome]) -> None:
    if source.done():
        _deliver(source, waiter)
        return

    def _done(done: asyncio.Future[_Outcome]) -> None:
        _deliver(done, waiter)

    source.add_done_callback(_done)


def _freeze_vector(vector: Sequence[float]) -> _Vector:
    return tuple(float(item) for item in vector)


def _merge_usage(usages: tuple[InferenceUsage, ...]) -> InferenceUsage:
    if not usages:
        return InferenceUsage(requests=0)
    requests = 0
    input_tokens = 0
    output_tokens = 0
    saw_input = False
    saw_output = False
    for usage in usages:
        requests += usage.requests
        if usage.input_tokens is not None:
            saw_input = True
            input_tokens += usage.input_tokens
        if usage.output_tokens is not None:
            saw_output = True
            output_tokens += usage.output_tokens
    return InferenceUsage(
        requests=requests,
        input_tokens=input_tokens if saw_input else None,
        output_tokens=output_tokens if saw_output else None,
    )


class CoalescingEmbeddingModel:
    """Share in-flight embedding work and reuse a bounded LRU of successful vectors.

    Callers wait on private futures, so cancelling one call does not cancel the
    underlying batch or drop another caller's result. Usage counts each distinct
    underlying batch a caller waited for once; cache hits add no requests.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if max_batch_size < 1:
            raise ValueError("max_batch_size must be positive")  # noqa: TRY003
        if cache_size < 0:
            raise ValueError("cache_size must be non-negative")  # noqa: TRY003
        if coalesce_ms < 0:
            raise ValueError("coalesce_ms must be non-negative")  # noqa: TRY003
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = coalesce_ms / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, _Vector] = OrderedDict()
        self._inflight: dict[str, _Shared] = {}
        self._pending: list[str] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()

    @property
    def profile(self):
        return self._model.profile

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Return one vector per input text, including duplicates, in input order."""

        if not texts:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        loop = asyncio.get_running_loop()
        async with self._lock:
            waiters = [self._claim(text, loop) for text in texts]
            self._ensure_flush()

        vectors: list[_Vector] = []
        charges: list[_BatchCharge] = []
        seen: set[int] = set()
        failure: Exception | None = None
        try:
            for waiter in waiters:
                try:
                    vector, charge = await waiter
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if failure is None:
                        failure = exc
                    continue
                if failure is not None:
                    continue
                vectors.append(vector)
                if charge is not None and id(charge) not in seen:
                    seen.add(id(charge))
                    charges.append(charge)
        except asyncio.CancelledError:
            for waiter in waiters:
                if not waiter.done():
                    waiter.cancel()
            raise
        if failure is not None:
            raise failure
        return EmbeddingResult(vectors=tuple(vectors), usage=_merge_usage(tuple(charge.usage for charge in charges)))

    def _claim(self, text: str, loop: asyncio.AbstractEventLoop) -> asyncio.Future[_Outcome]:
        cached = self._cache.get(text)
        if cached is not None:
            self._cache.move_to_end(text)
            waiter: asyncio.Future[_Outcome] = loop.create_future()
            waiter.add_done_callback(_retrieve_exception)
            waiter.set_result((cached, None))
            return waiter

        shared = self._inflight.get(text)
        if shared is None:
            future: asyncio.Future[_Outcome] = loop.create_future()
            future.add_done_callback(_retrieve_exception)
            shared = _Shared(future)
            self._inflight[text] = shared
            self._pending.append(text)
        waiter = loop.create_future()
        waiter.add_done_callback(_retrieve_exception)
        shared.waiters.append(waiter)
        _fan_out(shared.future, waiter)
        return waiter

    def _ensure_flush(self) -> None:
        if not self._pending:
            return
        task = self._flush_task
        if task is not None and not task.done():
            return
        self._flush_task = self._spawn(self._flush())

    def _spawn(self, coro: Coroutine[object, object, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _flush(self) -> None:
        try:
            delay = self._coalesce_seconds if self._coalesce_seconds > 0 else 0
            await asyncio.sleep(delay)
            async with self._lock:
                pending = tuple(self._pending)
                self._pending.clear()
                if self._flush_task is asyncio.current_task():
                    self._flush_task = None
                kept: list[str] = []
                for text in pending:
                    shared = self._inflight.get(text)
                    if shared is None:
                        continue
                    if any(not waiter.done() for waiter in shared.waiters):
                        kept.append(text)
                        continue
                    self._inflight.pop(text, None)
                    if not shared.future.done():
                        shared.future.cancel()
                batches = tuple(
                    tuple(kept[index : index + self._max_batch_size])
                    for index in range(0, len(kept), self._max_batch_size)
                )
            for batch in batches:
                self._spawn(self._run_batch(batch))
        except asyncio.CancelledError:
            await self._abandon_pending()
            raise

    async def _abandon_pending(self) -> None:
        async with self._lock:
            pending = tuple(self._pending)
            self._pending.clear()
            if self._flush_task is asyncio.current_task():
                self._flush_task = None
            shareds = []
            for text in pending:
                shared = self._inflight.pop(text, None)
                if shared is not None:
                    shareds.append(shared)
        for shared in shareds:
            if not shared.future.done():
                shared.future.cancel()

    async def _run_batch(self, texts: tuple[str, ...]) -> None:
        try:
            result = await self._model.embed(texts)
        except asyncio.CancelledError:
            await self._reject(texts, RuntimeError("embedding batch cancelled"))  # noqa: TRY003
            raise
        except Exception as exc:
            await self._reject(texts, exc)
            return
        if len(result.vectors) != len(texts):
            await self._reject(texts, ValueError("embedding-count"))  # noqa: TRY003
            return
        try:
            vectors = tuple(_freeze_vector(vector) for vector in result.vectors)
        except Exception as exc:
            await self._reject(texts, exc)
            return
        await self._resolve(texts, vectors, result.usage)

    async def _resolve(self, texts: tuple[str, ...], vectors: tuple[_Vector, ...], usage: InferenceUsage) -> None:
        charge = _BatchCharge(usage)
        async with self._lock:
            deliveries: list[tuple[asyncio.Future[_Outcome], _Outcome]] = []
            for text, vector in zip(texts, vectors, strict=True):
                self._remember(text, vector)
                shared = self._inflight.pop(text, None)
                if shared is not None and not shared.future.done():
                    deliveries.append((shared.future, (vector, charge)))
        for future, outcome in deliveries:
            future.set_result(outcome)

    async def _reject(self, texts: tuple[str, ...], exc: Exception) -> None:
        async with self._lock:
            failed: list[asyncio.Future[_Outcome]] = []
            for text in texts:
                shared = self._inflight.pop(text, None)
                if shared is not None and not shared.future.done():
                    failed.append(shared.future)
        for future in failed:
            future.set_exception(exc)

    def _remember(self, text: str, vector: _Vector) -> None:
        if self._cache_size <= 0:
            return
        self._cache[text] = vector
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


__all__ = ["CoalescingEmbeddingModel"]
