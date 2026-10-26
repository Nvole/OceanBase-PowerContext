"""Import engineering files and search collection track07_sdd_docs."""

import re
import sys

from pyseekdb import HNSWConfiguration

from sdd_context.embed import DIMENSION, embed_documents, embed_text
from sdd_context.paths import env_file, project_root, track_root

COLLECTION = "track07_sdd_docs"
_DEF = re.compile(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)
_HEADING = re.compile(r"^##\s+(.+)$", re.M)


def connect():
    scripts = project_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from db import connect_collection_api
    return connect_collection_api(env_file())


def open_collection(client):
    if client.has_collection(COLLECTION):
        current = client.get_collection(COLLECTION, embedding_function=None)
        if getattr(current, "_dimension", None) not in (None, DIMENSION):
            client.delete_collection(COLLECTION)
        else:
            return current
    return client.get_or_create_collection(
        name=COLLECTION,
        configuration=HNSWConfiguration(dimension=DIMENSION, distance="l2"),
        embedding_function=None,
    )


def import_materials(client=None) -> dict:
    client = client or connect()
    collection = open_collection(client)
    rows = list(_materials())
    if not rows:
        raise RuntimeError("no engineering materials found to import")
    ids = [row["id"] for row in rows]
    documents = [row["document"] for row in rows]
    metadatas = [row["metadata"] for row in rows]
    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embed_documents(documents),
        metadatas=metadatas,
    )
    collection.refresh_index()
    return {"collection": COLLECTION, "count": collection.count(), "ids": ids}


def search(task_terms: list[str], client=None) -> tuple[list[dict], list[dict]]:
    client = client or connect()
    collection = open_collection(client)
    found = {}
    queries = []
    for term in task_terms:
        try:
            result = collection.get(
                where_document={"$contains": term},
                include=["documents", "metadatas"],
            )
            rows = _rows_from_get(result)
            queries.append({"term": term, "mode": "fulltext", "ids": [row["id"] for row in rows]})
        except Exception as exc:
            queries.append({"term": term, "mode": "fulltext", "error": type(exc).__name__})
            continue
        for row in rows:
            found[row["id"]] = row
    if not found and task_terms:
        vector = embed_text(" ".join(task_terms))
        try:
            result = collection.query(
                query_embeddings=[vector],
                n_results=10,
                include=["documents", "metadatas"],
            )
            rows = _rows_from_query(result)
            queries.append({"term": " ".join(task_terms), "mode": "vector", "ids": [row["id"] for row in rows]})
            for row in rows:
                found[row["id"]] = row
        except Exception as exc:
            queries.append({"term": " ".join(task_terms), "mode": "vector", "error": type(exc).__name__})
    return list(found.values()), queries


def _materials():
    root = track_root()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".powercontext" in path.parts or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        kind = _kind(relative, path.name)
        if kind is None or path.suffix.lower() not in {".md", ".py"}:
            continue
        if path.stat().st_size > 200_000:
            continue
        text = path.read_text(encoding="utf-8")
        yield {
            "id": relative,
            "document": text,
            "metadata": {
                "source": relative,
                "kind": kind,
                "symbol": _symbols(text, kind),
            },
        }


def _kind(relative: str, name: str) -> str | None:
    if relative.startswith("src/lab/") and name.endswith(".py"):
        return "code"
    if relative.startswith("tests/") and name.startswith("test_") and name.endswith(".py"):
        return "test"
    if relative.startswith("docs/") and name.endswith("_spec.md"):
        return "spec"
    if relative.startswith("docs/") and name.endswith(".md"):
        return "document"
    return None


def _symbols(text: str, kind: str) -> str:
    if kind == "code":
        names = _DEF.findall(text)
    elif kind == "test":
        names = [name for name in _DEF.findall(text) if name.startswith("test_")]
    else:
        names = _HEADING.findall(text)
    return ",".join(names)[:500]


def _rows_from_get(result: dict) -> list[dict]:
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    if ids and isinstance(ids[0], list):
        ids = ids[0]
        documents = documents[0] if documents else []
        metadatas = metadatas[0] if metadatas else []
    return _zip_rows(ids, documents, metadatas)


def _rows_from_query(result: dict) -> list[dict]:
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    if ids and isinstance(ids[0], list):
        ids = ids[0]
        documents = documents[0] if documents else []
        metadatas = metadatas[0] if metadatas else []
    return _zip_rows(ids, documents, metadatas)


def _zip_rows(ids, documents, metadatas) -> list[dict]:
    rows = []
    for index, doc_id in enumerate(ids):
        rows.append({
            "id": doc_id,
            "document": documents[index] if index < len(documents) else "",
            "metadata": metadatas[index] if index < len(metadatas) else {},
        })
    return rows
