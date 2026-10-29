import copy
import json
from pathlib import Path

import yaml


PROJECT = Path(__file__).resolve().parents[1]
DSL = PROJECT / "docs" / "absurd_debate.dsl.yml"


def code_node(node_id, title, code, variables, outputs, position):
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": position, "y": 220},
        "positionAbsolute": {"x": position, "y": 220},
        "height": 140,
        "width": 244,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {
            "type": "code", "title": title, "desc": title,
            "code_language": "python3", "code": code,
            "variables": [{"variable": name, "value_selector": selector} for name, selector in variables.items()],
            "outputs": {name: {"type": value} for name, value in outputs.items()},
        },
    }


def build():
    document = yaml.safe_load(DSL.read_text(encoding="utf-8"))
    nodes = {node["id"]: copy.deepcopy(node) for node in document["workflow"]["graph"]["nodes"]}
    start, retrieve, respond, save, end = [nodes[f"173300010{number}"] for number in range(1, 6)]
    prepare_id = "1733000106"
    confirm_id = "1733000107"
    prepare = code_node(
        prepare_id, "安全序列化输入",
        'def main(argument: str, motion: str) -> dict:\n'
        '    import json\n'
        '    return {"request_body": json.dumps({"text": argument, "motion": motion, "n_results": 8}, ensure_ascii=False)}\n',
        {"argument": [start["id"], "argument"], "motion": [start["id"], "motion"]},
        {"request_body": "string"}, 380,
    )
    retrieve["data"]["body"] = {"type": "raw-text", "data": [{"key": "", "type": "text", "value": "{{#" + prepare_id + ".request_body#}}"}]}
    retrieve["data"]["url"] = "{{#env.DEBATE_API_BASE#}}/v1/retrieve"
    respond["data"]["code"] = respond["data"]["code"].replace(
        'retrieve_body: str)', 'retrieve_body: str, retrieve_status: float)'
    ).replace('    import json\n', '    import json\n    if int(retrieve_status) != 200:\n        raise ValueError("seekdb retrieval HTTP request failed")\n', 1)
    if not any(variable["variable"] == "retrieve_status" for variable in respond["data"]["variables"]):
        respond["data"]["variables"].append({"variable": "retrieve_status", "value_selector": [retrieve["id"], "status_code"]})
    confirm_code = '''def main(saved_body: str, saved_status: float, retrieve_body: str, round_id: str, rebuttal: str, score: float, cited_id: str) -> dict:
    import json
    if int(saved_status) != 200:
        raise ValueError("seekdb save HTTP request failed")
    saved = json.loads(saved_body)
    expected = ["p_" + round_id, "h_" + round_id]
    if saved.get("refreshed") is not True or saved.get("ids") != expected:
        raise ValueError("seekdb write/refresh was not confirmed")
    retrieved = json.loads(retrieve_body)
    if retrieved.get("fusion") != "seekdb_hybrid_rrf":
        raise ValueError("seekdb hybrid retrieval was not used")
    return {
        "rebuttal": rebuttal, "score": score, "cited_id": cited_id,
        "round_id": round_id, "saved": json.dumps(saved, ensure_ascii=False),
        "retrieved_ids": json.dumps([hit["id"] for hit in retrieved["hits"]]),
        "fusion": retrieved["fusion"],
    }
'''
    confirm = code_node(confirm_id, "确认 seekdb 写入成功", confirm_code, {
        "saved_body": [save["id"], "body"], "saved_status": [save["id"], "status_code"],
        "retrieve_body": [retrieve["id"], "body"], "round_id": [respond["id"], "round_id"],
        "rebuttal": [respond["id"], "rebuttal"], "score": [respond["id"], "score"],
        "cited_id": [respond["id"], "cited_id"],
    }, {"rebuttal": "string", "score": "number", "cited_id": "string", "round_id": "string", "saved": "string", "retrieved_ids": "string", "fusion": "string"}, 1580)
    end["data"]["outputs"] = [
        {"variable": name, "value_selector": [confirm_id, name], "value_type": value["type"]}
        for name, value in confirm["data"]["outputs"].items()
    ]
    ordered = [start, prepare, retrieve, respond, save, confirm, end]
    for index, node in enumerate(ordered):
        node["position"] = {"x": 80 + index * 300, "y": 220}
        node["positionAbsolute"] = node["position"].copy()
    edges = []
    for source, target in zip(ordered, ordered[1:]):
        edges.append({
            "id": source["id"] + "-source-" + target["id"] + "-target",
            "source": source["id"], "target": target["id"], "sourceHandle": "source", "targetHandle": "target",
            "type": "custom", "zIndex": 0,
            "data": {"isInIteration": False, "isInLoop": False, "sourceType": source["data"]["type"], "targetType": target["data"]["type"]},
        })
    document["app"]["name"] = "离谱辩题 · Dify seekdb 实跑版"
    document["app"]["description"] = "Dify 编排检索、规则主持、保存确认；seekdb 保存历史辩词。规则主持，不冒充大模型。"
    document["workflow"]["environment_variables"][0]["value"] = "http://debate:18604"
    document["workflow"]["environment_variables"][0]["description"] = "Compose 内部后端地址；自有 Dify 部署需填写该容器实际可访问的地址。"
    document["workflow"]["graph"]["nodes"] = ordered
    document["workflow"]["graph"]["edges"] = edges
    document["workflow"]["rag_pipeline_variables"] = []
    DSL.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(json.dumps({"nodes": len(ordered), "edges": len(edges), "model_required": False}))


if __name__ == "__main__":
    build()
