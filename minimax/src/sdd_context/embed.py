"""Stable bag-of-tokens vectors. Not a semantic model and not downloaded."""

import hashlib
import re

DIMENSION = 8
_TOKEN = re.compile(r"[A-Za-z0-9_\-]{2,}")
_CJK = re.compile(r"[\u4e00-\u9fff]{2,}")


def embed_text(text: str) -> list[float]:
    vector = [0.0] * DIMENSION
    for token in _TOKEN.findall(text.lower()):
        vector[_bucket(token)] += 1.0
    for chunk in _CJK.findall(text):
        for index in range(len(chunk) - 1):
            vector[_bucket(chunk[index:index + 2])] += 1.0
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [value / norm for value in vector]


def embed_documents(texts: list[str]) -> list[list[float]]:
    return [embed_text(text) for text in texts]


def _bucket(token: str) -> int:
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % DIMENSION
