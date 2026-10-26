"""Read and write task state through the local PowerContext HTTP API."""

import json
import urllib.error
import urllib.request
from pathlib import Path

from sdd_context.pc_service import BASE_URL
from sdd_context.paths import track_root

SCOPE_FILE = "scope_id"


def scope_path() -> Path:
    return track_root() / ".powercontext" / SCOPE_FILE


def save_marker(text: str) -> dict:
    scope = _ensure_scope()
    if scope.get("status") == "blocked":
        return scope
    scope_id = scope["scope_id"]
    status, body = _post("/v1/memory/remember", {
        "scope_id": scope_id,
        "kind": "decision",
        "text": text,
        "reason": "recorded task progress and verification",
    })
    if status >= 400:
        status, body = _post("/v1/memory/remember", {
            "scope_id": scope_id,
            "kind": "fact",
            "text": text,
        })
    return {"status": "saved" if status < 400 else "write_failed", "http_status": status, "body": body, "scope_id": scope_id}


def read_state() -> dict:
    if not scope_path().is_file():
        return {"status": "blocked", "reason": "no PowerContext scope has been saved"}
    scope_id = scope_path().read_text(encoding="utf-8").strip()
    prepared_status, prepared = _post("/v1/context/prepare", {
        "scope_id": scope_id,
        "query": "TRACK07_STATE_MARKER",
        "max_bytes": 4000,
    })
    listed_status, listed = _post("/v1/atomic-memory/list", {"scope_id": scope_id, "limit": 20})
    text = ""
    if isinstance(prepared, dict):
        text = prepared.get("content") or ""
    if "TRACK07_STATE_MARKER" not in text:
        dumped = json.dumps(listed, ensure_ascii=False)
        if "TRACK07_STATE_MARKER" in dumped:
            text = dumped
    if not text and prepared_status >= 400 and listed_status >= 400:
        return {
            "status": "blocked",
            "reason": "PowerContext did not answer on 127.0.0.1:18617",
            "prepare_http_status": prepared_status,
            "list_http_status": listed_status,
        }
    return {
        "status": "ready" if "TRACK07_STATE_MARKER" in text else "empty",
        "scope_id": scope_id,
        "prepare_http_status": prepared_status,
        "list_http_status": listed_status,
        "prepare_status": prepared.get("status") if isinstance(prepared, dict) else "",
        "text": text,
        "used_in_context": "TRACK07_STATE_MARKER" in text,
    }


def _ensure_scope() -> dict:
    if scope_path().is_file():
        return {"status": "existing", "scope_id": scope_path().read_text(encoding="utf-8").strip()}
    status, body = _post("/v1/scopes", {
        "title": "track07 invoice date range",
        "summary": "Task state for the invoice filter change",
        "idempotency_key": "track07-invoice-date-range",
    })
    if status >= 400 or "scope_id" not in body:
        return {"status": "blocked", "reason": "PowerContext scope was not created", "http_status": status, "body": body}
    scope_path().parent.mkdir(parents=True, exist_ok=True)
    scope_path().write_text(body["scope_id"], encoding="utf-8")
    return {"status": "created", "scope_id": body["scope_id"]}


def _post(path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": raw[:1500]}
        return error.code, body
    except (OSError, urllib.error.URLError) as exc:
        return 599, {"error": type(exc).__name__}
