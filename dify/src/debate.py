"""seekdb collection track04_debate: save cards and hybrid_search them.

Vector and full-text hits are fused by seekdb RRF inside hybrid_search.
This module does not merge the two result lists itself.
"""
import json
import re
import sys
from pathlib import Path

from hashvec import DIM, hash_embed
from pyseekdb import FulltextIndexConfig, HNSWConfiguration, Schema, VectorIndexConfig

TRACK = Path(__file__).resolve().parents[1]
ROOT = TRACK.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect_collection_api  # noqa: E402

COLLECTION = "track04_debate"
ENV_FILE = TRACK / ".env"
SEED_FILE = TRACK / "data" / "seed_arguments.json"
CONTENT_WORDS = (
    "石榴干", "西瓜税", "交税", "阳光", "呼噜", "窗台", "沙发", "冰箱",
    "投票", "周一", "周二", "周日", "梦想", "热汤", "雨天", "勺子",
    "税务", "口粮", "睡眠", "灵感", "猫", "税", "雨", "汤",
)


def card_document(motion, side, speech):
    return f"【辩题】{motion}\n【立场】{side}\n【发言】{speech}"


def embed_source(motion, text):
    motion = (motion or "").strip()
    text = (text or "").strip()
    if not text:
        raise ValueError("text is empty")
    if motion and motion not in text:
        return motion + "\n" + text
    return text


def keywords_for(text, limit=3):
    found = [word for word in CONTENT_WORDS if word in text]
    found.sort(key=len, reverse=True)
    chosen = []
    for word in found:
        if any(word in kept and word != kept for kept in chosen):
            continue
        chosen.append(word)
        if len(chosen) >= limit:
            return chosen
    if chosen:
        return chosen
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    if len(chars) >= 2:
        return ["".join(chars[:2])]
    words = re.findall(r"[A-Za-z0-9_]{2,}", text.lower())
    return chars[:1] or words[:1] or ["辩题"]


def where_document(keywords):
    if len(keywords) == 1:
        return {"$contains": keywords[0]}
    return {"$or": [{"$contains": word} for word in keywords]}


def _group(value):
    if not value:
        return []
    if isinstance(value[0], list):
        return value[0]
    return value


def unpack_hits(result):
    ids = _group(result.get("ids"))
    documents = _group(result.get("documents"))
    metadatas = _group(result.get("metadatas"))
    distances = _group(result.get("distances"))
    hits = []
    for index, doc_id in enumerate(ids):
        score = distances[index] if index < len(distances) else None
        if score is not None:
            score = float(score)
        metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
        hits.append({
            "id": doc_id,
            "document": documents[index] if index < len(documents) else "",
            "metadata": metadata,
            "score": score,
        })
    return hits


def hybrid_search_parts(collection, vector, keywords, n_results=3):
    """One seekdb hybrid_search call. Do not rank the two legs in Python."""
    if len(vector) != DIM:
        raise ValueError(f"expected {DIM} dimensions")
    if not keywords:
        raise ValueError("keywords required")
    window = max(int(n_results), 8)
    result = collection.hybrid_search(
        query={"where_document": where_document(keywords), "n_results": window},
        knn={"query_embeddings": [vector], "n_results": window},
        rank={"rrf": {}},
        n_results=int(n_results),
        include=["documents", "metadatas"],
    )
    return unpack_hits(result)


def hybrid_hits(collection, text, motion="", n_results=3):
    query_text = embed_source(motion, text)
    keywords = keywords_for(query_text)
    hits = hybrid_search_parts(collection, hash_embed(query_text), keywords, n_results=n_results)
    return {
        "collection": COLLECTION,
        "fusion": "seekdb_hybrid_rrf",
        "keywords": keywords,
        "query_text": query_text,
        "hits": hits,
    }


def open_collection(env_file=None):
    client = connect_collection_api(str(env_file or ENV_FILE))
    schema = Schema(
        vector_index=VectorIndexConfig(
            hnsw=HNSWConfiguration(dimension=DIM, distance="cosine"),
            embedding_function=None,
        ),
        fulltext_index=FulltextIndexConfig(analyzer="ik"),
    )
    return client.get_or_create_collection(
        name=COLLECTION, schema=schema, embedding_function=None)


def upsert_cards(collection, items):
    ids = [item["id"] for item in items]
    documents = [item["document"] for item in items]
    embeddings = [hash_embed(document) for document in documents]
    metadatas = [item["metadata"] for item in items]
    collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
    collection.refresh_index()
    return ids


def load_seeds(collection, seed_file=None):
    payload = json.loads(Path(seed_file or SEED_FILE).read_text(encoding="utf-8"))
    items = []
    for seed in payload:
        document = card_document(seed["motion"], seed["side"], seed["speech"])
        items.append({
            "id": seed["id"],
            "document": document,
            "metadata": {
                "role": "seed",
                "player": seed["player"],
                "motion": seed["motion"],
                "side": seed["side"],
                "round_id": seed["id"],
                "score": 0,
                "cited_id": "",
            },
        })
    return upsert_cards(collection, items)


def ensure_ready(env_file=None, seed_file=None):
    collection = open_collection(env_file)
    load_seeds(collection, seed_file)
    return collection


def save_round(collection, player, motion, side, argument, rebuttal, score, cited_id, round_id, host_side):
    player_document = card_document(motion, side, argument)
    host_document = card_document(motion, host_side, rebuttal)
    ids = upsert_cards(collection, [
        {
            "id": f"p_{round_id}",
            "document": player_document,
            "metadata": {
                "role": "player",
                "player": player,
                "motion": motion,
                "side": side,
                "round_id": round_id,
                "score": int(score),
                "cited_id": cited_id or "",
            },
        },
        {
            "id": f"h_{round_id}",
            "document": host_document,
            "metadata": {
                "role": "host",
                "player": "主持人杠精",
                "motion": motion,
                "side": host_side,
                "round_id": round_id,
                "score": int(score),
                "cited_id": cited_id or "",
            },
        },
    ])
    return {
        "ids": ids,
        "refreshed": True,
        "count": collection.count(),
        "collection": COLLECTION,
        "round_id": round_id,
        "player_document": player_document,
        "host_document": host_document,
    }