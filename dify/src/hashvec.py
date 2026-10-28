"""64-dimensional feature hashing for wish texts. Pure stdlib, no model weights.

The same text always maps to the same unit vector, so retrieval is reproducible
without any embedding model. The approach (feature-hash Chinese text into a
64-dim unit vector for seekdb hybrid search) follows the reference
implementation shipped in this repository's debate track; the constants and
tokenisation below are written for this project.
"""
import hashlib
import math
import re

DIM = 64
_WORD = re.compile(r"[A-Za-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def tokens(text):
    chars = _CJK.findall(text or "")
    found = _WORD.findall((text or "").lower())
    found.extend(chars)
    found.extend(left + right for left, right in zip(chars, chars[1:]))
    return found or ["<empty>"]


def hash_embed(text):
    """Map text to a unit vector. Same text always returns the same vector."""
    vector = [0.0] * DIM
    for token in tokens(text):
        digest = hashlib.blake2s(token.encode("utf-8"), digest_size=8).digest()
        vector[int.from_bytes(digest[0:2], "little") % DIM] += 1.0 if digest[2] & 1 else -1.0
        vector[int.from_bytes(digest[3:5], "little") % DIM] += 0.5 if digest[5] & 1 else -0.5
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left, right):
    return sum(a * b for a, b in zip(left, right))