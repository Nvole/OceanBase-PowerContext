"""Import materials, prove spec refresh, and reuse PowerContext state."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from sdd_context.minimax_assistant import apply_assistant_module, request_change
from sdd_context.paths import project_root, track_root
from sdd_context.pc_service import binary, start, stop, wipe_home
from sdd_context.store import import_materials
from sdd_context.task_state import save_marker, scope_path

TASK = "invoice-date-range filter_invoices test_filter_by_date_range SPEC_SENTENCE 日期范围 金额 状态"
OLD = "SPEC_SENTENCE: 日期筛选使用闭区间，边界当天的发票必须保留。"
NEW = "SPEC_SENTENCE: 日期筛选使用闭区间，边界当天的发票必须保留，并且只比较日历日。"
MARKER = "TRACK07_STATE_MARKER"


def main() -> int:
    root = track_root()
    results = root / "results"
    results.mkdir(parents=True, exist_ok=True)
    probe = results / "probe_ft.py"
    if probe.exists():
        probe.unlink()
    summary = {
        "seekdb": "pending",
        "spec_refresh": "pending",
        "powercontext": "pending",
        "minimax": "pending",
    }
    spec_path = None
    original = None
    try:
        imported = import_materials()
        first = _build(results / "context.json")
        _require_materials(first)
        summary["seekdb"] = {
            "collection": imported["collection"],
            "count": imported["count"],
            "query_ids": [item["document_id"] for item in first["spec_items"] + first["code"] + first["tests"]],
        }
        (results / "db_query_record.json").write_text(
            json.dumps({"task": TASK, "queries": first["queries"], "sources": _sources(first)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if OLD not in _spec_lines(first):
            raise AssertionError("initial query did not return the current spec sentence")
        spec_source = _source_for_line(first, OLD)
        spec_path = root / spec_source
        original = spec_path.read_text(encoding="utf-8")
        spec_path.write_text(original.replace(OLD, NEW, 1), encoding="utf-8")
        stale = _build(results / "context_stale_file.json")
        if OLD not in _spec_lines(stale) or NEW in _spec_lines(stale):
            raise AssertionError("context changed before re-import, so it is not reading the collection")
        import_materials()
        refreshed = _build_until(
            results / "context_refreshed.json",
            lambda payload: NEW in _spec_lines(payload) and OLD not in _spec_lines(payload),
        )
        if NEW not in _spec_lines(refreshed) or OLD in _spec_lines(refreshed):
            raise AssertionError("re-import did not surface the updated spec sentence")
        summary["spec_refresh"] = {
            "source": spec_source,
            "before_reimport": _spec_lines(stale),
            "after_reimport": _spec_lines(refreshed),
        }
        (results / "spec_refresh.json").write_text(
            json.dumps(summary["spec_refresh"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary["powercontext"] = _powercontext(results)
        context_for_model = json.loads((results / "context.json").read_text(encoding="utf-8"))
        mini = request_change(TASK, context_for_model)
        if "prompt_preview_not_sent" in mini:
            (results / "minimax_prompt_preview.json").write_text(
                json.dumps({"sent": False, "prompt": mini.pop("prompt_preview_not_sent")}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if mini.get("participated"):
            applied = apply_assistant_module(mini.get("assistant_content", ""), root / "src" / "lab" / "invoice_filter.py")
            mini.update(applied)
            test = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", str(root / "tests"), "-v"],
                cwd=str(project_root()),
                env={**os.environ, "PYTHONPATH": str(root / "src")},
                text=True,
                capture_output=True,
            )
            (results / "tests_after_minimax.txt").write_text(test.stdout + test.stderr + f"\nexit_code={test.returncode}\n", encoding="utf-8")
            mini["applied_tests_exit_code"] = test.returncode
            if test.returncode != 0:
                raise AssertionError("tests failed after applying MiniMax response")
        (results / "minimax_status.json").write_text(json.dumps({key: value for key, value in mini.items() if key != "assistant_content"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["minimax"] = {"participated": mini.get("participated"), "status": mini.get("status"), "applied_to": mini.get("applied_to")}
        _write_usage(root / "minimax" / "usage_record.md", mini, summary)
    except Exception as exc:
        summary["error"] = _public_error(exc)
        _write_summary(results, summary)
        return 1
    finally:
        if spec_path is not None and original is not None:
            spec_path.write_text(original, encoding="utf-8")
            try:
                import_materials()
            except Exception as exc:
                summary["restore_error"] = _public_error(exc)
        _write_summary(results, summary)
    try:
        restored = _build(results / "context_restored.json")
        if OLD not in _spec_lines(restored) or NEW in _spec_lines(restored):
            raise AssertionError("restored spec sentence was not imported back into the collection")
    except Exception as exc:
        summary["error"] = _public_error(exc)
        _write_summary(results, summary)
        return 1
    _write_summary(results, summary)
    return 0 if "error" not in summary else 1


def _powercontext(results: Path) -> dict:
    stop()
    wipe_home()
    if scope_path().exists():
        scope_path().unlink()
    started = start()
    if not started.get("started"):
        record = {"status": "blocked", "start": started}
        (results / "powercontext_reuse.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return record
    text = (
        f"{MARKER}\n"
        "已完成：金额筛选与状态筛选已实现，回归测试通过。\n"
        "待办：日期范围筛选已实现，后续任务直接复用该结论。\n"
        "验证：修改前日期范围测试失败，修改后同一组测试通过。\n"
        "决定：invoice_date 使用闭区间，只比较日历日；起止颠倒时返回空列表。\n"
    )
    saved = save_marker(text)
    stop()
    restarted = start()
    shown = _cli(["show-state"])
    built = _build(results / "context_with_state.json")
    version = ""
    if binary().is_file():
        completed = subprocess.run([str(binary()), "--version"], check=False, capture_output=True, text=True)
        version = (completed.stdout or completed.stderr).strip()
    state_text = (built.get("task_state") or {}).get("text") or ""
    record = {
        "status": "reused" if MARKER in state_text and MARKER in (shown.stdout or "") else "write_failed",
        "version": version,
        "url": "http://127.0.0.1:18617",
        "saved": _brief(saved),
        "restart": {"started": restarted.get("started"), "status": restarted.get("status"), "ready": restarted.get("ready")},
        "show_state_status": _json_status(shown.stdout),
        "used_in_context": MARKER in state_text,
    }
    if record["status"] != "reused":
        record["show_state_stdout"] = (shown.stdout or "")[-1500:]
        record["show_state_stderr"] = (shown.stderr or "")[-1500:]
        record["saved_body"] = saved.get("body")
    (results / "powercontext_reuse.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def _require_materials(payload: dict) -> None:
    if not any("def filter_invoices" in item["text"] for item in payload["code"]):
        raise AssertionError("query results did not include the filter implementation")
    if not any("def test_filter_by_date_range" in item["text"] for item in payload["tests"]):
        raise AssertionError("query results did not include the date-range test")
    if not payload["spec_items"]:
        raise AssertionError("query results did not include a spec")
    for key in ("spec_items", "code", "tests"):
        for item in payload[key]:
            if not item["source"] or item["source"] != item["document_id"]:
                raise AssertionError("context source was not taken from the query hit")
    if not any(query.get("ids") for query in payload["queries"]):
        raise AssertionError("full-text query returned no rows")


def _build(path: Path) -> dict:
    completed = _cli(["build", "--task", TASK, "--out", str(path)])
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return json.loads(path.read_text(encoding="utf-8"))


def _build_until(path: Path, predicate) -> dict:
    last = None
    for _ in range(5):
        last = _build(path)
        if predicate(last):
            return last
        time.sleep(0.4)
    return last


def _cli(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(track_root() / "src")
    return subprocess.run(
        [sys.executable, "-m", "sdd_context", *args],
        cwd=str(project_root()),
        env=env,
        text=True,
        capture_output=True,
    )


def _spec_lines(payload: dict) -> list[str]:
    lines = []
    for item in payload.get("spec_items") or []:
        for line in (item.get("text") or "").splitlines():
            if line.startswith("SPEC_SENTENCE:"):
                lines.append(line.strip())
    return lines


def _source_for_line(payload: dict, line: str) -> str:
    for item in payload.get("spec_items") or []:
        if line in (item.get("text") or ""):
            return item["source"]
    raise AssertionError("query results did not identify the spec source")


def _sources(payload: dict) -> dict:
    return {
        key: [item["source"] for item in payload.get(key) or []]
        for key in ("spec_items", "code", "tests", "other")
    }


def _json_status(stdout: str) -> str:
    try:
        return json.loads(stdout).get("status", "")
    except json.JSONDecodeError:
        return "unparsed"


def _brief(payload: dict) -> dict:
    body = payload.get("body")
    return {
        "status": payload.get("status"),
        "http_status": payload.get("http_status"),
        "body_keys": sorted(body) if isinstance(body, dict) else [],
    }


def _write_usage(path: Path, mini: dict, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MiniMax ????",
        "",
        f"- ???{mini.get('status')}",
        f"- ???????{mini.get('participated')}",
        f"- ???{mini.get('model', '')}",
        f"- ???{mini.get('endpoint', '')}",
        f"- HTTP ???{mini.get('http_status', '')}",
        f"- ?????{mini.get('applied_to', '???')}",
        f"- ?????????{mini.get('applied_tests_exit_code', '???')}",
        f"- ???{mini.get('reason', '')}",
        "",
        "?????? seekdb ???????????????????????MiniMax ?????????????????????????????????",
        "??? API Key ?????????",
        "",
        "## ?????",
        "",
        "??????????? `results/context.json` ? `results/db_query_record.json`?",
        "????????? `results/spec_refresh.json`?",
        f"PowerContext?{json.dumps(summary.get('powercontext'), ensure_ascii=False)}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_summary(results: Path, summary: dict) -> None:
    (results / "acceptance_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _public_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if any(word in text.lower() for word in ("password", "token", "secret", "api_key")):
        return type(exc).__name__
    return text[:1500]


if __name__ == "__main__":
    raise SystemExit(main())
