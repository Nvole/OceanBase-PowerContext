"""Checks for the wishwell service. Run inside the project uv environment.

On the eval box (default seekdb store) the real-seekdb checks run as well;
locally WISHWELL_STORE=file exercises the same flow through the JSON stand-in.
"""
import json
import math
import re
import sys
import textwrap
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
SRC = TRACK / "src"
sys.path.insert(0, str(SRC))

from hashvec import DIM, cosine, hash_embed
from poolgod import echo_letter, god_payload
from wishwell import ensure_ready, hybrid_hits, hybrid_search_parts, save_wish, store_name, wish_document

REPORT = {}


def check(name, fn):
    skipped = fn()
    if skipped:
        REPORT[name] = {"skipped": skipped}
        print("SKIP", name, skipped)
        return
    REPORT[name] = {"passed": True}
    print("PASS", name)


def test_hash_vector():
    left = hash_embed("希望周一自动放假")
    right = hash_embed("希望周一自动放假并且周报自己写")
    other = hash_embed("冰箱只负责制冷")
    assert len(left) == DIM == 64
    assert abs(math.sqrt(sum(value * value for value in left)) - 1) < 1e-9
    assert left == hash_embed("希望周一自动放假")
    assert left != other
    assert cosine(left, right) > cosine(left, other)


def test_poolgod_cites_old_wishes():
    hits = [{
        "id": "seed_w01",
        "document": wish_document("不想写周报的人", "希望每周一自动放假。"),
        "metadata": {"player": "不想写周报的人", "wish": "希望每周一自动放假。"},
    }]
    letter = echo_letter("新来的", "希望周报自己会写自己。", hits)
    assert letter["cited_ids"] == ["seed_w01"]
    assert "不想写周报的人" in letter["echo"]
    assert "每周一自动放假" in letter["echo"]
    assert 1 <= letter["grant"] <= 99
    assert 1 <= letter["absurdity"] <= 99
    assert re.fullmatch(r"[0-9a-f]{8}", letter["coin_id"])
    assert letter == echo_letter("新来的", "希望周报自己会写自己。", hits)
    assert god_payload("新来的", "希望周报自己会写自己。", hits)["echo"] == letter["echo"]


def test_source_does_not_merge_legs():
    source = (SRC / "wishwell.py").read_text(encoding="utf-8")
    server = (SRC / "server.py").read_text(encoding="utf-8")
    assert "def hybrid_search_parts" in source
    assert "hybrid_search(" in source
    assert "refresh_index(" in source
    assert "collection.query(" not in source
    assert "def merge" not in source
    assert 'HOST = "127.0.0.1"' in server
    assert "PORT = 18604" in server
    assert "0.0.0.0" not in server


def test_toss_calls_hybrid_once():
    class Fake:
        def __init__(self):
            self.calls = []

        def hybrid_search(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "ids": [["seed_w01"]],
                "documents": [[wish_document("不想写周报的人", "希望每周一自动放假。")]],
                "metadatas": [[{"player": "不想写周报的人", "wish": "希望每周一自动放假。"}]],
                "distances": [[0.0328]],
            }

        def query(self, **kwargs):
            raise AssertionError("plain vector query must not replace hybrid_search")

    fake = Fake()
    found = hybrid_hits(fake, "希望周报自己会写自己。", n_results=3)
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["rank"] == {"rrf": {}}
    assert "where_document" in call["query"]
    assert len(call["knn"]["query_embeddings"][0]) == 64
    assert found["fusion"] == "seekdb_hybrid_rrf"
    assert found["hits"][0]["id"] == "seed_w01"


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
            return 9

    fake = Fake()
    saved = save_wish(fake, "新来的", "希望周报自己会写自己。", "回声", 50, 50, "赠品", ["seed_w01"], "a1b2c3d4")
    assert fake.order == ["upsert", "refresh"]
    assert saved["refreshed"] is True
    assert saved["ids"] == ["w_a1b2c3d4", "e_a1b2c3d4"]


def test_real_hybrid_prefers_overlap():
    if store_name() != "seekdb":
        return "no seekdb server here"
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
    meta = {"role": "test", "player": "测试员", "wish": "暗号石榴干只此一份", "coin_id": "t",
            "grant": 1, "absurdity": 1, "gift": "", "cited_ids": []}
    ids = ["t_both", "t_vec", "t_ft"]
    try:
        collection.upsert(
            ids=ids,
            documents=["暗号石榴干只此一份", "冰箱只负责制冷", "另一处暗号石榴干"],
            embeddings=[vector, near, far],
            metadatas=[dict(meta), dict(meta), dict(meta)],
        )
        collection.refresh_index()
        hits = hybrid_search_parts(collection, vector, ["石榴干"], n_results=3)
        assert hits, "hybrid_search returned nothing"
        assert hits[0]["id"] == "t_both", hits
    finally:
        collection.delete(ids=ids)


def test_real_save_is_searchable():
    if store_name() != "seekdb":
        return "no seekdb server here"
    collection = ensure_ready()
    wish = "石榴干这个暗号只在测试回合出现一次。"
    saved = None
    try:
        saved = save_wish(collection, "测试员", wish, "回声", 40, 40, "赠品", [], "feedc0de")
        found = hybrid_hits(collection, saved["wish_document"], n_results=3)
        assert "w_feedc0de" in [hit["id"] for hit in found["hits"]], found
    finally:
        if saved:
            collection.delete(ids=saved["ids"])


def test_file_store_roundtrip():
    if store_name() != "file":
        return "not file store"
    collection = ensure_ready()
    wish = "本地文件店里的暗号：周四下午三点半。"
    letter = echo_letter("本地测试员", wish, [])
    saved = save_wish(collection, "本地测试员", wish, letter["echo"], letter["grant"],
                      letter["absurdity"], letter["gift"], [], letter["coin_id"])
    try:
        found = hybrid_hits(collection, "周四下午三点半的暗号", n_results=3)
        assert f"w_{letter['coin_id']}" in [hit["id"] for hit in found["hits"]], found
    finally:
        if saved:
            collection.delete(ids=saved["ids"])


def test_dsl_code_matches_runtime():
    dsl = (TRACK / "docs" / "wishwell.dsl.yml").read_text(encoding="utf-8")
    assert 'version: "0.5.0"' in dsl
    for title in ("输入", "HTTP 投币", "池神", "制币", "HTTP 入池", "输出"):
        assert f"title: {title}" in dsl
    assert "dify_imported: true" not in dsl.lower()
    assert "WISH_API_BASE" in dsl
    marker = "def main(player: str, wish: str, toss_body: str, god_text: str) -> dict:"
    start = dsl.rfind("\n", 0, dsl.index(marker)) + 1
    lines = []
    base = None
    for line in dsl[start:].splitlines():
        indent = len(line) - len(line.lstrip(" "))
        if base is None:
            base = indent
            lines.append(line)
            continue
        if line.strip() and indent < base:
            break
        lines.append(line)
    code = textwrap.dedent("\n".join(lines) + "\n")
    namespace = {}
    exec(code, namespace)
    wish = "希望食堂鸡腿每天多一根。"
    player = "测试员"
    hits = [{
        "id": "seed_w01",
        "document": wish_document("不想写周报的人", "希望每周一自动放假。"),
        "metadata": {"player": "不想写周报的人", "wish": "希望每周一自动放假。"},
    }]
    toss_body = json.dumps({"hits": hits}, ensure_ascii=False)
    letter = god_payload(player, wish, hits)
    god_text = json.dumps(letter, ensure_ascii=False)
    produced = namespace["main"](player, wish, toss_body, god_text)
    for key in ("echo", "grant", "absurdity", "gift", "coin_id"):
        assert produced[key] == letter[key], key
    saved = json.loads(produced["save_body"])
    assert saved["echo"] == letter["echo"]
    assert saved["coin_id"] == letter["coin_id"]
    assert saved["cited_ids"] == letter["cited_ids"]
    guide = (TRACK / "docs" / "运行说明.md").read_text(encoding="utf-8")
    assert "127.0.0.1:18604" in guide
    assert "seekdb" in guide


def main():
    check("hash_vector", test_hash_vector)
    check("poolgod", test_poolgod_cites_old_wishes)
    check("source", test_source_does_not_merge_legs)
    check("single_hybrid_call", test_toss_calls_hybrid_once)
    check("refresh_after_write", test_save_refreshes_before_return)
    check("dsl", test_dsl_code_matches_runtime)
    check("real_hybrid", test_real_hybrid_prefers_overlap)
    check("real_save", test_real_save_is_searchable)
    check("file_roundtrip", test_file_store_roundtrip)
    destination = TRACK / "results" / "test_report.json"
    destination.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("TEST_OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("TEST_FAIL", type(exc).__name__, exc)
        raise