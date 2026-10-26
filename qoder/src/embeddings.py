"""Local character n-gram vectors for knn. No embedding model is downloaded."""
import math

DIMENSION = 64


def embed_text(text):
    values = [0.0] * DIMENSION
    compact = ''.join(str(text).lower().split())
    if not compact:
        compact = 'empty'
    grams = list(compact)
    grams.extend(compact[index:index + 2] for index in range(len(compact) - 1))
    for gram in grams:
        digest = 2166136261
        for char in gram:
            digest ^= ord(char)
            digest = (digest * 16777619) & 0xFFFFFFFF
        values[digest % DIMENSION] += 1.0 if digest & 0x100 else -1.0
    norm = math.sqrt(sum(item * item for item in values)) or 1.0
    return [item / norm for item in values]
