"""Checks for the absurd-debate service. Run with the project uv environment."""
import json
import math
import os
import re
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

TRACK = Path(__file__).resolve().parents[1]
SRC = TRACK / "src"
sys.path.insert(0, str(SRC))

from debate import hybrid_hits, hybrid_search_parts, save_round, ensure_ready
from hashvec import DIM, cosine, hash_embed
from respond import host_reply

REPORT = {}


def check(name, fn):
    fn()
    REPORT[name] = {"passed": True}
    print("PASS", name)


def test_hash_vector():
    left = hash_embed("猫应该交税，窗台阳光")
    right = hash_embed("猫应该交税，窗台阳光和呼噜")
    other = hash_embed("冰箱保管口粮并行使投票权")
    assert len(left) == DIM == 64
    assert abs(math.sqrt(sum(value * value for value in left)) - 1) < 1e-9
    assert left == hash_embed("猫应该交税，窗台阳光")
    assert left != other
    assert cosine(left, right) > cosine(left, other)


def test_host_cites_and_switches_side():
    reply = host_reply("夜班辩手", "猫应该交税", "正方", "猫霸占阳光。", [
        {"id": "seed_cat_pro", "document": "旧档案发言", "metadata": {"player": "阳光审计员"}},
    ])
    assert reply["host_side"] == "反方"
    assert reply["cited_id"] == "seed_cat_pro"
    assert "阳光审计员" in reply["rebuttal"]
    assert "主持人杠精" in reply["rebuttal"]
    assert 1 <= reply["score"] <= 99
    again = host_reply("夜班辩手", "猫应该交税", "正方", "猫霸占阳光。", [
        {"id": "seed_cat_pro", "document": "旧档案发言", "metadata": {"player": "阳光审计员"}},
    ])
    assert again == reply


def test_source_does_not_merge_legs():
    source = (SRC / "debate.py").read_text(encoding="utf-8")
    server = (SRC / "server.py").read_text(encoding="utf-8")
    assert "def hybrid_search_parts" in source
    assert "hybrid_search(" in source
    assert "refresh_index(" in source
    assert "collection.query(" not in source
    assert "rrf_score" not in source
    assert "def merge" not in source
    assert 'HOST = "127.0.0.1"' in server
    assert "PORT = 18604" in server
    assert 'os.environ.get("DEBATE_BIND", HOST)' in server
    assert "ROOT /" not in source


def test_retrieve_calls_hybrid_once():
    class Fake:
        def __init__(self):
            self.calls = []

        def hybrid_search(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "ids": [["seed_cat_pro"]],
                "documents": [["【辩题】猫应该交税\n【发言】旧"]],
                "metadatas": [[{"player": "阳光审计员"}]],
                "distances": [[0.0328]],
            }

        def query(self, **kwargs):
            raise AssertionError("plain vector query must not replace hybrid_search")

    fake = Fake()
    found = hybrid_hits(fake, "猫霸占窗台阳光却不交税", motion="猫应该交税", n_results=3)
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["rank"] == {"rrf": {}}
    assert "where_document" in call["query"]
    assert len(call["knn"]["query_embeddings"][0]) == 64
    assert found["fusion"] == "seekdb_hybrid_rrf"
    assert found["hits"][0]["id"] == "seed_cat_pro"


def test_save_refreshes_before_return():
    class Fake:
        def __init__(self):
            self.order = []

        def upsert(self, **kwargs):
            self.order.append("upsert")
            assert len(kwargs["embeddings"]) == 2
            assert all(len(vector) == 64 for vector in kwargs["embeddings"])

        def refresh_index(self):
            self.order.append("refresh")

        def count(self):
            return 8

    fake = Fake()
    saved = save_round(
        fake, "夜班辩手", "猫应该交税", "正方", "猫霸占阳光。", "本席反对。",
        40, "seed_cat_pro", "abcd1234", "反方")
    assert fake.order == ["upsert", "refresh"]
    assert saved["refreshed"] is True
    assert saved["ids"] == ["p_abcd1234", "h_abcd1234"]


@pytest.mark.skipif(os.environ.get("RUN_SEEKDB_TESTS") != "1", reason="Requires the dedicated real seekdb database")
def test_real_hybrid_prefers_overlap():
    collection = ensure_ready()
    vector = [0.0] * 64
    vector[0] = 1.0
    near = [0.0] * 64
    near[0] = 1.0
    near[1] = 0.25
    scale = math.sqrt(sum(value * value for value in near))
    near = [value / scale for value in near]
    far = [0.0] * 64
    far[1] = 1.0
    meta = {"role": "test", "player": "测试员", "motion": "西瓜税", "side": "正方", "round_id": "t", "score": 1, "cited_id": ""}
    ids = ["t_both", "t_vec", "t_ft"]
    try:
        collection.upsert(
            ids=ids,
            documents=["暗号西瓜税只此一份", "冰箱只负责制冷", "另一处暗号西瓜税"],
            embeddings=[vector, near, far],
            metadatas=[dict(meta), dict(meta), dict(meta)],
        )
        collection.refresh_index()
        hits = hybrid_search_parts(collection, vector, ["西瓜税"], n_results=3)
        assert hits, "hybrid_search returned nothing"
        assert hits[0]["id"] == "t_both", hits
        assert hits[0]["score"] > hits[1]["score"]
    finally:
        collection.delete(ids=ids)


@pytest.mark.skipif(os.environ.get("RUN_SEEKDB_TESTS") != "1", reason="Requires the dedicated real seekdb database")
def test_real_save_is_searchable():
    collection = ensure_ready()
    argument = "石榴干这个暗号只在测试回合出现一次。"
    reply = host_reply("测试员", "石榴干应该单独建档", "反方", argument, [])
    saved = None
    try:
        saved = save_round(
            collection, "测试员", "石榴干应该单独建档", "反方", argument,
            reply["rebuttal"], reply["score"], "", reply["round_id"], reply["host_side"])
        found = hybrid_hits(collection, saved["player_document"], n_results=3)
        assert f"p_{reply['round_id']}" in [hit["id"] for hit in found["hits"]], found
    finally:
        if saved:
            collection.delete(ids=saved["ids"])


def test_dsl_code_matches_runtime():
    dsl = (TRACK / "docs" / "absurd_debate.dsl.yml").read_text(encoding="utf-8")
    document = yaml.safe_load(dsl)
    assert document["version"] == "0.5.0"
    for title in ("输入", "HTTP 检索", "回应", "HTTP 保存", "输出"):
        assert f"title: {title}" in dsl
    assert "http://debate:18604" in dsl
    nodes = {node["id"]: node for node in document["workflow"]["graph"]["nodes"]}
    assert len(nodes) == 7
    assert len(document["workflow"]["graph"]["edges"]) == 6
    code = nodes["1733000103"]["data"]["code"]
    namespace = {}
    exec(code, namespace)
    hits = [{"id": "seed_cat_pro", "document": "旧档案发言", "metadata": {"player": "阳光审计员"}}]
    body = json.dumps({"hits": hits}, ensure_ascii=False)
    produced = namespace["main"]("夜班辩手", "猫应该交税", "正方", "猫霸占阳光。", body, 200)
    expected = host_reply("夜班辩手", "猫应该交税", "正方", "猫霸占阳光。", hits)
    for key in ("rebuttal", "score", "cited_id", "host_side", "round_id"):
        assert produced[key] == expected[key]
    saved = json.loads(produced["save_body"])
    assert saved["rebuttal"] == expected["rebuttal"]
    assert saved["round_id"] == expected["round_id"]
    with pytest.raises(ValueError):
        namespace["main"]("夜班辩手", "猫应该交税", "正方", "猫霸占阳光。", body, 500)


def test_dsl_serializes_quotes_and_newlines():
    document = yaml.safe_load((TRACK / "docs" / "absurd_debate.dsl.yml").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in document["workflow"]["graph"]["nodes"]}
    namespace = {}
    exec(nodes["1733000106"]["data"]["code"], namespace)
    argument = '证人说"喵"\n又说：反对！\\'
    actual = json.loads(namespace["main"](argument, "猫应该交税")["request_body"])
    assert actual["text"] == argument
    assert nodes["1733000102"]["data"]["body"]["type"] == "raw-text"


def test_dsl_rejects_unsaved_results():
    document = yaml.safe_load((TRACK / "docs" / "absurd_debate.dsl.yml").read_text(encoding="utf-8"))
    node = next(node for node in document["workflow"]["graph"]["nodes"] if node["id"] == "1733000107")
    namespace = {}
    exec(node["data"]["code"], namespace)
    with pytest.raises(ValueError):
        namespace["main"]('{}', 500, '{}', 'abc123', '拒绝', 50, '')
    with pytest.raises(ValueError):
        namespace["main"]('{"refreshed": false, "ids": []}', 200, '{}', 'abc123', '拒绝', 50, '')


def main():
    check("hash_vector", test_hash_vector)
    check("host", test_host_cites_and_switches_side)
    check("source", test_source_does_not_merge_legs)
    check("single_hybrid_call", test_retrieve_calls_hybrid_once)
    check("refresh_after_write", test_save_refreshes_before_return)
    check("dsl", test_dsl_code_matches_runtime)
    check("real_hybrid", test_real_hybrid_prefers_overlap)
    check("real_save", test_real_save_is_searchable)
    destination = TRACK / "results" / "test_report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("TEST_OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("TEST_FAIL", type(exc).__name__, exc)
        raise
