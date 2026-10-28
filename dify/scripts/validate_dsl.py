"""Structural checks for the wishwell Dify DSL (0.5.0) and its local variant.

Usage: python scripts/validate_dsl.py [path-to-dsl]
"""
import json
import re
import sys
import textwrap
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc

TRACK = Path(__file__).resolve().parents[1]
DEFAULT = TRACK / "docs" / "wishwell.dsl.yml"
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"name": name, "passed": bool(ok), "detail": detail})
    print(("PASS" if ok else "FAIL"), name, detail)


def validate(path):
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    check("yaml_parses", data is not None)
    if not data:
        return
    check("kind", data.get("kind") == "app")
    check("app_mode", data.get("app", {}).get("mode") == "workflow")
    graph = data.get("workflow", {}).get("graph", {})
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    by_id = {node.get("id"): node for node in nodes}
    types = [node.get("data", {}).get("type") for node in nodes]
    check("node_chain", types == ["start", "http-request", "llm", "code", "http-request", "end"], str(types))
    check("six_nodes", len(nodes) == 6 and len(edges) == 5)
    for edge in edges:
        check(f"edge_ok_{edge.get('source')}_{edge.get('target')}",
              edge.get("source") in by_id and edge.get("target") in by_id)
    env = data.get("workflow", {}).get("environment_variables") or []
    check("env_api_base", any(item.get("name") == "WISH_API_BASE" for item in env))
    start = by_id.get("1733000101", {}).get("data", {})
    vars_ = start.get("variables") or []
    check("start_vars", [item.get("variable") for item in vars_] == ["player", "wish"],
          str([item.get("variable") for item in vars_]))
    check("wish_required", any(item.get("variable") == "wish" and item.get("required") for item in vars_))
    toss = by_id.get("1733000102", {}).get("data", {})
    check("toss_url", toss.get("url") == "{{#env.WISH_API_BASE#}}/v1/toss")
    body = toss.get("body", {})
    items = body.get("data") or []
    check("toss_json_single_item", body.get("type") == "json" and len(items) == 1 and items[0].get("type") == "text")
    check("toss_body_fields", "wish" in items[0].get("value", "") and "player" in items[0].get("value", ""))
    llm = by_id.get("1733000103", {}).get("data", {})
    check("llm_model", llm.get("model", {}).get("mode") == "chat" and llm.get("model", {}).get("provider"))
    prompts = llm.get("prompt_template") or []
    check("llm_prompt_roles", [item.get("role") for item in prompts] == ["system", "user"])
    check("llm_prompt_json_contract", "JSON" in "\n".join(item.get("text", "") for item in prompts))
    check("llm_context_off", llm.get("context", {}).get("enabled") is False)
    code_node = by_id.get("1733000104", {}).get("data", {})
    code = code_node.get("code") or ""
    check("code_compiles", True if compile(code, "dsl-code", "exec") is not None else False)
    outputs = code_node.get("outputs") or {}
    for key, typ in (("echo", "string"), ("grant", "number"), ("absurdity", "number"),
                     ("gift", "string"), ("coin_id", "string"), ("save_body", "string")):
        check(f"code_output_{key}", outputs.get(key, {}).get("type") == typ)
    keep = by_id.get("1733000105", {}).get("data", {})
    check("keep_url", keep.get("url") == "{{#env.WISH_API_BASE#}}/v1/keep")
    keep_items = (keep.get("body", {}).get("data")) or []
    check("keep_raw_text", keep.get("body", {}).get("type") == "raw-text" and len(keep_items) == 1)
    end = by_id.get("1733000106", {}).get("data", {})
    end_out = end.get("outputs") or []
    check("end_outputs", len(end_out) == 6, str(len(end_out)))
    secrets = re.findall(r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|password\s*[:=]\s*[^\s\"']+)", raw)
    check("no_secrets", not secrets, str(secrets[:1]))
    return data


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    validate(path)
    report = TRACK / "results" / "dsl-validation.json"
    report.write_text(json.dumps({
        "path": str(path),
        "checks": CHECKS,
        "passed": sum(1 for item in CHECKS if item["passed"]),
        "total": len(CHECKS),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = len(CHECKS)
    passed = sum(1 for item in CHECKS if item["passed"])
    print(f"DSL_OK {passed}/{total}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()