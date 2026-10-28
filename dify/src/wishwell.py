"""seekdb collection track04_wishwell: store wishes and pool-god echoes.

Retrieval is one seekdb hybrid_search call per toss; the vector and full-text
legs are fused inside seekdb with RRF. This module never ranks the two legs
in Python.

Default store is seekdb server mode opened through the box helper
`connect_collection_api` (provided as ~/oceanbase/scripts/db.py on the eval
box), the same convention the other tracks in this repository use. On
machines without that helper, WISHWELL_STORE=file switches to a JSON-file
stand-in with identical call shapes so local demos and unit tests can run
anywhere. Competition evidence always uses the default seekdb store.
"""
import json
import os
import re
import sys
from pathlib import Path

from hashvec import DIM, cosine, hash_embed

TRACK = Path(__file__).resolve().parents[1]
ROOT = TRACK.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))  # box helper: connect_collection_api

COLLECTION = "track04_wishwell"
ENV_FILE = TRACK / ".env"
SEED_FILE = TRACK / "data" / "seed_wishes.json"
STORE_FILE = TRACK / "data" / "wishwell-store.json"


def wish_document(player, wish):
    return f"【愿望】{wish}\n【许愿人】{player}"


def echo_document(echo):
    return f"【回声】{echo}"


def embed_source(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("text is empty")
    return text


def keywords_for(text, limit=3):
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = []
    for left, right in zip(chars, chars[1:]):
        pair = left + right
        if pair not in bigrams:
            bigrams.append(pair)
        if len(bigrams) >= limit:
            return bigrams
    if bigrams:
        return bigrams
    words = re.findall(r"[A-Za-z0-9_]{2,}", text.lower())
    return words[:limit] or chars[:1] or ["愿望"]


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


def hybrid_hits(collection, text, n_results=3):
    query_text = embed_source(text)
    keywords = keywords_for(query_text)
    hits = hybrid_search_parts(collection, hash_embed(query_text), keywords, n_results=n_results)
    return {
        "collection": COLLECTION,
        "fusion": "seekdb_hybrid_rrf",
        "keywords": keywords,
        "query_text": query_text,
        "hits": hits,
    }


def store_name():
    return os.environ.get("WISHWELL_STORE", "seekdb").strip().lower() or "seekdb"


def open_seekdb_collection(env_file=None):
    from db import connect_collection_api  # noqa: PLC0415 (box helper)
    from pyseekdb import FulltextIndexConfig, HNSWConfiguration, Schema, VectorIndexConfig

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


class FileCollection:
    """JSON-file stand-in with the same call shapes as a seekdb collection."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def _flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, ids, documents, embeddings, metadatas):
        for index, doc_id in enumerate(ids):
            self.data[str(doc_id)] = {
                "document": documents[index],
                "embedding": embeddings[index],
                "metadata": metadatas[index] if index < len(metadatas) else {},
            }
        self.refresh_index()

    def refresh_index(self):
        self._flush()

    def count(self):
        return len(self.data)

    def delete(self, ids):
        for doc_id in ids:
            self.data.pop(str(doc_id), None)
        self.refresh_index()

    def _matches(self, where, document):
        if not where:
            return True
        if "$contains" in where:
            words = [where["$contains"]]
        else:
            words = [item.get("$contains", "") for item in (where.get("$or") or [])]
        return any(word and word in document for word in words)

    def hybrid_search(self, query, knn, rank, n_results, include):
        del rank, include  # file stand-in keeps the same signature
        window = int(query.get("n_results") or int(n_results))
        vector = knn["query_embeddings"][0]
        rows = list(self.data.items())
        scored = []
        for doc_id, row in rows:
            similarity = cosine(vector, row["embedding"])
            if similarity >= 0.0:
                scored.append((doc_id, row, similarity))
        scored.sort(key=lambda item: item[2], reverse=True)
        vector_rank = {}
        for index, (doc_id, _row, _sim) in enumerate(scored[:window]):
            vector_rank[doc_id] = index
        fulltext_rank = {}
        for doc_id, row in rows:
            if self._matches(query.get("where_document") or {}, row["document"]):
                fulltext_rank[doc_id] = len(fulltext_rank)
        rrf = {}
        for doc_id in set(vector_rank) | set(fulltext_rank):
            score = 0.0
            if doc_id in vector_rank:
                score += 1.0 / (60 + vector_rank[doc_id])
            if doc_id in fulltext_rank:
                score += 1.0 / (60 + fulltext_rank[doc_id])
            rrf[doc_id] = score
        ranked = sorted(rrf.items(), key=lambda item: item[1], reverse=True)[:int(n_results)]
        ids, documents, metadatas, distances = [], [], [], []
        for doc_id, score in ranked:
            row = self.data[doc_id]
            ids.append(doc_id)
            documents.append(row["document"])
            metadatas.append(row["metadata"])
            distances.append(score)
        return {
            "ids": [ids],
            "documents": [documents],
            "metadatas": [metadatas],
            "distances": [distances],
        }


def open_file_collection():
    return FileCollection(STORE_FILE)


def open_collection(env_file=None):
    store = store_name()
    if store == "file":
        return open_file_collection()
    if store != "seekdb":
        raise ValueError(f"unknown WISHWELL_STORE: {store}")
    return open_seekdb_collection(env_file)


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
        items.append({
            "id": seed["id"],
            "document": wish_document(seed["player"], seed["wish"]),
            "metadata": {
                "role": "seed",
                "player": seed["player"],
                "wish": seed["wish"],
                "coin_id": seed["id"],
                "grant": 0,
                "absurdity": 0,
                "gift": "",
                "cited_ids": [],
            },
        })
    return upsert_cards(collection, items)


def save_wish(collection, player, wish, echo, grant, absurdity, gift, cited_ids, coin_id):
    wish_doc = wish_document(player, wish)
    echo_doc = echo_document(echo)
    ids = upsert_cards(collection, [
        {
            "id": f"w_{coin_id}",
            "document": wish_doc,
            "metadata": {
                "role": "wish",
                "player": player,
                "wish": wish,
                "coin_id": coin_id,
                "grant": int(grant),
                "absurdity": int(absurdity),
                "gift": gift,
                "cited_ids": list(cited_ids or []),
            },
        },
        {
            "id": f"e_{coin_id}",
            "document": echo_doc,
            "metadata": {
                "role": "echo",
                "player": "池神",
                "wish": wish,
                "coin_id": coin_id,
                "grant": int(grant),
                "absurdity": int(absurdity),
                "gift": gift,
                "cited_ids": list(cited_ids or []),
            },
        },
    ])
    return {
        "ids": ids,
        "refreshed": True,
        "count": collection.count(),
        "collection": COLLECTION,
        "coin_id": coin_id,
        "wish_document": wish_doc,
        "echo_document": echo_doc,
    }


def ensure_ready(env_file=None, seed_file=None):
    collection = open_collection(env_file)
    load_seeds(collection, seed_file)
    return collection