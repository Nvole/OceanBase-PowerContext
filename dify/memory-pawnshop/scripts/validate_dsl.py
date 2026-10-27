#!/usr/bin/env python3
"""Structural and code-level checks for the generated Dify Chatflow DSL."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DSL_PATH = ROOT / "dify" / "Memory_Pawnshop_Chatflow.yml"
OUT_PATH = ROOT / "evidence" / "dsl-validation.json"

REQUIRED_NODES = {
    "start",
    "identify_ticket",
    "http_context",
    "parse_context",
    "llm",
    "http_save",
    "parse_save",
    "answer",
}
SYS_FIELDS = {"query", "user_id", "conversation_id", "workflow_run_id", "files"}
checks: list[dict] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    checks.append({"name": name, "passed": bool(condition), "detail": detail})
    if not condition:
        raise SystemExit(f"DSL validation failed: {name} {detail}")


def validate_graph(dsl: dict) -> dict[str, dict]:
    graph = dsl["workflow"]["graph"]
    nodes = {item["id"]: item for item in graph["nodes"]}
    check("DSL 版本为 0.3.1", dsl.get("version") == "0.3.1", str(dsl.get("version")))
    check("应用类型为 advanced-chat", dsl["app"].get("mode") == "advanced-chat")
    check("节点集合完整", set(nodes) == REQUIRED_NODES, str(sorted(nodes)))
    check("Chatflow Start 不依赖自定义变量", nodes["start"]["data"].get("variables") == [])

    incoming = {node_id: 0 for node_id in nodes}
    outgoing = {node_id: 0 for node_id in nodes}
    for edge in graph["edges"]:
        check("边引用有效节点", edge["source"] in nodes and edge["target"] in nodes)
        incoming[edge["target"]] += 1
        outgoing[edge["source"]] += 1
    for node_id in nodes:
        if node_id != "start":
            check(f"{node_id} 只有一个入口", incoming[node_id] == 1)
        if node_id != "answer":
            check(f"{node_id} 只有一个出口", outgoing[node_id] == 1)

    for node in nodes.values():
        node_id = node["id"]
        data = node["data"]
        for variable in data.get("variables") or []:
            selector = variable.get("value_selector") or []
            if not selector:
                continue
            root, field = selector[0], selector[1] if len(selector) > 1 else ""
            if root == "sys":
                check(f"{node_id} 使用合法系统变量", field in SYS_FIELDS, field)
            else:
                check(f"{node_id} 引用已有节点", root in nodes, root)
        if data.get("type") == "code":
            compile(data["code"], f"{node_id}.py", "exec")

    templates = [nodes["answer"]["data"]["answer"]]
    templates.extend(item["text"] for item in nodes["llm"]["data"]["prompt_template"])
    for template in templates:
        for selector in re.findall(r"\{\{#([^#]+)#\}\}", template):
            root = selector.split(".", 1)[0]
            check("模板变量引用已有节点或 sys", root == "sys" or root in nodes, selector)

    for node_id in ("http_context", "http_save"):
        check(f"{node_id} 使用 POST", nodes[node_id]["data"]["method"] == "post")
        body = nodes[node_id]["data"]["body"]
        check(f"{node_id} 请求 JSON", body["type"] == "json")
        check(f"{node_id} JSON body 为 Dify 1.9 单条目", len(body["data"]) == 1)
        if len(body["data"]) == 1:
            value = body["data"][0]["value"]
            check(f"{node_id} JSON body 可解析", isinstance(json.loads(value), dict))
        check(f"{node_id} timeout 使用 1.9 字段", set(nodes[node_id]["data"]["timeout"]) == {"connect", "read", "write"})
    check(
        "HTTP 节点使用可替换的服务地址",
        nodes["http_context"]["data"]["url"].endswith("/api/pawn/context")
        and nodes["http_save"]["data"]["url"].endswith("/api/pawn/remember"),
    )
    check("LLM 模型可导入后重新绑定", bool(nodes["llm"]["data"]["model"]["provider"]))
    return nodes


def validate_ticket_parser(nodes: dict[str, dict]) -> None:
    namespace: dict = {}
    exec(nodes["identify_ticket"]["data"]["code"], namespace)
    parser = namespace["main"]
    cases = [
        ("当票号：小满。我想当掉一段记忆。", "小满"),
        ("取一个当票号叫「阿蛮」。我想典当。", "阿蛮"),
        ("我的当票号是阿满，我想赎回。", "阿满"),
    ]
    for text, expected in cases:
        result = parser(text, "user-1", "conv-1")
        check("解析显式当票号", result["ticket_id"] == expected, text)
        check("标记显式当票来源", result["ticket_origin"] == "explicit")

    first = parser("我想当掉一段雨声。", "stable-user", "conv-a")
    second = parser("我想当掉一段铃声。", "stable-user", "conv-b")
    check("相同 Dify 用户生成稳定当票号", first["ticket_id"] == second["ticket_id"])
    check("自动当票号带可读前缀", first["ticket_id"].startswith("客-"))
    url_case = parser("当票号：https://example.com", "user-1", "conv-1")
    check("拒绝把网址当作当票号", url_case["ticket_origin"] != "explicit")
    long_case = parser("当票号：" + "字" * 60, "user-1", "conv-1")
    check("当票号长度限制为 24", len(long_case["ticket_id"]) == 24)


def main() -> None:
    raw = DSL_PATH.read_bytes()
    dsl = yaml.safe_load(raw.decode("utf-8"))
    nodes = validate_graph(dsl)
    validate_ticket_parser(nodes)
    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dsl_path": str(DSL_PATH),
        "dsl_sha256": hashlib.sha256(raw).hexdigest(),
        "dify_target": "Dify 1.9.x / DSL 0.3.1",
        "checks": checks,
        "result": "passed",
        "note": "本脚本验证 DSL 结构与内嵌 Python 代码；Dify UI 实机导入需在 Dify 环境中完成。",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "passed", "checks": len(checks), "output": str(OUT_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
