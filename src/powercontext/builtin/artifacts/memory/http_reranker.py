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

"""HTTP score-service adapter for cross-batch Memory reranking."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

_DEFAULT_POLICY_ID = "http-cross-encoder-v1"


class HTTPMemoryReranker:
    """Select Memory hits with scores from one caller-supplied HTTP client.

    Ranks are the candidate's 1-based index in the full pool. Batches do not
    renumber them, and every batch participates in one global ordering.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = _DEFAULT_POLICY_ID,
    ) -> None:
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("rerank batch_size must be a positive integer")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: Sequence[MemoryHit],
        limit: int,
    ) -> MemoryRerankDecision:
        """Score every candidate and return the top original ranks.

        Higher scores win. Exact score ties keep the lower original rank.
        ``usage.requests`` is the number of HTTP calls made on success.
        """

        pool = tuple(candidates)
        _validate_bounds(len(pool), limit)
        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, len(pool), self._batch_size):
            batch = pool[start : start + self._batch_size]
            ranks = tuple(range(start + 1, start + 1 + len(batch)))
            response = await self._client.post(
                self._endpoint,
                json={
                    "query": query,
                    "candidates": [
                        {"rank": rank, "text": candidate.text} for rank, candidate in zip(ranks, batch, strict=True)
                    ],
                },
            )
            requests += 1
            response.raise_for_status()
            scores.update(_scores_for_batch(response, expected=frozenset(ranks)))
        return MemoryRerankDecision(
            selected_ranks=_select_ranks(scores, limit),
            usage=InferenceUsage(requests=requests),
        )


def _validate_bounds(candidate_count: int, limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003
    if candidate_count < 1:
        raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
    if limit < 1 or limit > candidate_count:
        raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003


def _select_ranks(scores: Mapping[int, float], limit: int) -> tuple[int, ...]:
    ordered = sorted(scores, key=lambda rank: (-scores[rank], rank))
    return tuple(ordered[:limit])


def _scores_for_batch(response: httpx.Response, *, expected: frozenset[int]) -> dict[int, float]:
    payload = _json_object(response)
    if set(payload) != {"scores"}:
        raise ValueError("rerank response schema is invalid")  # noqa: TRY003
    raw_scores = payload["scores"]
    if not isinstance(raw_scores, list):
        raise ValueError("rerank response schema is invalid")  # noqa: TRY003
    parsed: dict[int, float] = {}
    for item in raw_scores:
        rank, score = _score_record(item)
        if rank not in expected or rank in parsed:
            raise ValueError("rerank response ranks do not match the batch")  # noqa: TRY003
        parsed[rank] = score
    if set(parsed) != expected:
        raise ValueError("rerank response ranks do not match the batch")  # noqa: TRY003
    return parsed


def _json_object(response: httpx.Response) -> Mapping[str, object]:
    try:
        payload = response.json()
    except ValueError as error:
        raise ValueError("rerank response is not valid JSON") from error  # noqa: TRY003
    if not isinstance(payload, dict):
        raise ValueError("rerank response schema is invalid")  # noqa: TRY003
    return payload


def _score_record(item: object) -> tuple[int, float]:
    if not isinstance(item, dict) or set(item) != {"rank", "score"}:
        raise ValueError("rerank score record schema is invalid")  # noqa: TRY003
    rank = item["rank"]
    score = item["score"]
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise ValueError("rerank score rank is invalid")  # noqa: TRY003
    return rank, _finite_score(score)


def _finite_score(score: object) -> float:
    if isinstance(score, bool) or not isinstance(score, int | float):
        raise ValueError("rerank score must be finite")  # noqa: TRY003
    try:
        numeric = float(score)
    except OverflowError as error:
        raise ValueError("rerank score must be finite") from error  # noqa: TRY003
    if not math.isfinite(numeric):
        raise ValueError("rerank score must be finite")  # noqa: TRY003
    return numeric


__all__ = ["HTTPMemoryReranker"]
