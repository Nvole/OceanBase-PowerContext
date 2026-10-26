"""Turn collection hits into task context. Sources come only from those hits."""

import re

_SPLIT = re.compile(r"[\s,，。；;：:、（）()\[\]{}\"'`]+")


def extract_terms(task: str) -> list[str]:
    terms = []
    seen = set()
    for chunk in _SPLIT.split(task.strip()):
        if len(chunk) < 2 or len(chunk) > 64 or chunk in seen:
            continue
        seen.add(chunk)
        terms.append(chunk)
        if len(terms) >= 16:
            break
    return terms


def assemble(task: str, terms: list[str], hits: list[dict], task_state: dict, queries: list[dict]) -> dict:
    grouped = {"spec": [], "code": [], "test": [], "document": []}
    for hit in hits:
        metadata = hit.get("metadata") or {}
        kind = metadata.get("kind") or "document"
        if kind not in grouped:
            kind = "document"
        grouped[kind].append({
            "source": metadata.get("source") or "",
            "kind": kind,
            "symbol": metadata.get("symbol") or "",
            "document_id": hit.get("id") or "",
            "text": hit.get("document") or "",
        })
    for items in grouped.values():
        items.sort(key=lambda item: item["source"])
    return {
        "task": task,
        "collection": "track07_sdd_docs",
        "query_terms": terms,
        "queries": queries,
        "spec_items": grouped["spec"],
        "code": grouped["code"],
        "tests": grouped["test"],
        "other": grouped["document"],
        "task_state": task_state,
        "sources_come_from_query_results": True,
    }
