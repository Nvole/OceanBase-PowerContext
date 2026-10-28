"""Call MiniMax only when MINIMAX_API_KEY is present. Never invent a reply."""

import ast
import json
import re
import os
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com").rstrip("/") + "/v1/text/chatcompletion_v2"
MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M3.1-Flash")


def status() -> dict:
    if not os.environ.get("MINIMAX_API_KEY", "").strip():
        return {
            "participated": False,
            "status": "blocked",
            "reason": "MINIMAX_API_KEY is unset. No dialogue was fabricated.",
            "endpoint": ENDPOINT,
            "model": MODEL,
        }
    return {"participated": False, "status": "key_present", "endpoint": ENDPOINT, "model": MODEL}


def request_change(task: str, context_payload: dict) -> dict:
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    prompt = _prompt(task, context_payload)
    if not key:
        return {
            "participated": False,
            "status": "blocked",
            "reason": "MINIMAX_API_KEY is unset. No dialogue was fabricated.",
            "endpoint": ENDPOINT,
            "model": MODEL,
            "prompt_preview_not_sent": prompt,
        }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({
            "model": MODEL,
            "temperature": 0.2,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "name": "MiniMax AI", "content": "Modify the invoice filter using only the supplied context. Return the full Python module."},
                {"role": "user", "name": "user", "content": prompt},
            ],
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
            http_status = response.status
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        return {"participated": False, "status": "http_error", "http_status": error.code, "detail": detail[:2000], "model": MODEL}
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"participated": False, "status": "request_failed", "error": type(exc).__name__, "model": MODEL}
    base_resp = body.get("base_resp") or {}
    provider_status = base_resp.get("status_code", 0)
    if provider_status not in (0, None):
        return {
            "participated": False,
            "status": "provider_error",
            "http_status": http_status,
            "provider_status": provider_status,
            "reason": base_resp.get("status_msg", "MiniMax provider error"),
            "model": MODEL,
        }
    choices = body.get("choices") or []
    message = ((choices[0].get("message") if choices else None) or {})
    content = message.get("content") or message.get("reasoning_content") or ""
    if not content:
        return {
            "participated": False,
            "status": "empty_response",
            "http_status": http_status,
            "reason": "MiniMax returned no assistant content",
            "model": body.get("model") or MODEL,
        }
    return {
        "participated": True,
        "status": "completed",
        "http_status": http_status,
        "model": body.get("model") or MODEL,
        "usage": body.get("usage") or {},
        "assistant_content": content,
        "finish_reason": ((choices[0] if choices else {}).get("finish_reason")),
    }


def _prompt(task: str, context_payload: dict) -> str:
    parts = [f"任务：{task}", "下面的规格、代码和测试来自资料库查询结果。"]
    for label, key in (("规格", "spec_items"), ("代码", "code"), ("测试", "tests")):
        for item in context_payload.get(key) or []:
            parts.append(f"\n[{label}] source={item.get('source')}\n{item.get('text')}")
    state = (context_payload.get("task_state") or {}).get("text") or ""
    if state:
        parts.append("\n[任务状态]\n" + state)
    parts.append("\n请只实现规格里尚未落地的日期范围行为，并保持金额与状态行为不变。")
    return "\n".join(parts)


def apply_assistant_module(content: str, destination: str | os.PathLike[str]) -> dict:
    match = re.search(r"```(?:python)?\s*(.*?)```", content, flags=re.IGNORECASE | re.DOTALL)
    module = (match.group(1) if match else content).strip() + "\n"
    ast.parse(module)
    if "def filter_invoices" not in module or 'REVISION = "date-range-applied"' not in module:
        raise ValueError("MiniMax response did not contain the required invoice filter revision")
    target = os.fspath(destination)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(module)
    return {"applied_to": target, "code_sha256": __import__("hashlib").sha256(module.encode()).hexdigest(), "code_length": len(module)}
