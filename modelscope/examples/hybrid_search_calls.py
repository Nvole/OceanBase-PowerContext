"""Assemble the three-record hybrid search call.

This script only prints the call shape. It does not import a database client
or open a connection.
"""

import json
from pathlib import Path

RECORDS_PATH = Path(__file__).resolve().parent / "three_records.json"
REQUIRED_PATHS = (
    "query.where_document.$contains",
    "knn.query_embeddings",
    "rank.rrf",
)


def load_records():
    records = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
    if not isinstance(records, list) or len(records) != 3:
        raise SystemExit("expected exactly 3 records")
    for item in records:
        for key in ("id", "document", "embedding", "metadata"):
            if key not in item:
                raise SystemExit("record missing " + key)
        if len(item["embedding"]) != 3:
            raise SystemExit("embedding must have 3 dimensions")
    return records


def build_calls(records):
    upsert = {
        "method": "upsert",
        "ids": [item["id"] for item in records],
        "documents": [item["document"] for item in records],
        "embeddings": [item["embedding"] for item in records],
        "metadatas": [item["metadata"] for item in records],
    }
    refresh_index = {"method": "refresh_index"}
    hybrid_search = {
        "method": "hybrid_search",
        "query": {"where_document": {"$contains": "工程"}, "n_results": 3},
        "knn": {"query_embeddings": [[0.9, 0.1, 0.0]], "n_results": 3},
        "rank": {"rrf": {}},
        "n_results": 3,
        "include": ["documents", "metadatas"],
    }
    paths = {
        "query.where_document.$contains": hybrid_search["query"]["where_document"]["$contains"],
        "knn.query_embeddings": hybrid_search["knn"]["query_embeddings"],
        "rank.rrf": hybrid_search["rank"]["rrf"],
    }
    return {
        "upsert": upsert,
        "refresh_index": refresh_index,
        "hybrid_search": hybrid_search,
        "paths": paths,
    }


def main():
    payload = build_calls(load_records())
    missing = [name for name in REQUIRED_PATHS if name not in payload["paths"]]
    if missing:
        raise SystemExit("missing " + ",".join(missing))
    if len(payload["upsert"]["ids"]) != 3:
        raise SystemExit("upsert must contain 3 ids")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
