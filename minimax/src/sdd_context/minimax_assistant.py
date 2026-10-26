"""Call MiniMax only when MINIMAX_API_KEY is present. Never invent a reply."""

import json
import os
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io").rstrip("/") + "/v1/text/chatcompletion_v2"
MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.5")


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
    message = (((body.get("choices") or [{}])[0].get("message")) or {})
    return {
        "participated": True,
        "status": "completed",
        "http_status": http_status,
        "model": body.get("model") or MODEL,
        "usage": body.get("usage") or {},
        "assistant_content": message.get("content") or "",
        "finish_reason": ((body.get("choices") or [{}])[0].get("finish_reason")),
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
