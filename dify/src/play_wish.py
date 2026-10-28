"""Play one full game through the exact steps the Dify DSL performs.

Start the HTTP service in the current store mode, toss a wish, let the pool
god write the echo, keep the round, then toss a related phrase to prove the
new round recalls the old wish. Writes results/sample_run.json.

Usage:
  python src/play_wish.py ["你的愿望"] [--no-server]
"""
import json
import sys
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

SRC = Path(__file__).resolve().parent
TRACK = SRC.parent
sys.path.insert(0, str(SRC))

from poolgod import god_payload  # noqa: E402
from wishwell import store_name  # noqa: E402

HOST = "127.0.0.1"
PORT = 18604


def http_json(method, path, payload=None):
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"http://{HOST}:{PORT}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    argv = [arg for arg in sys.argv[1:] if arg != "--no-server"]
    no_server = "--no-server" in sys.argv[1:]
    wish = argv[0] if argv else "我想许愿周五永远不结束，并且食堂的鸡腿每天多一根。"
    player = "试池的人"

    server = None
    if not no_server:
        from server import Handler, ready
        ready()
        server = HTTPServer((HOST, PORT), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"service up at http://{HOST}:{PORT} (store={store_name()})", flush=True)

    try:
        toss = http_json("POST", "/v1/toss", {"player": player, "wish": wish, "n_results": 3})
        letter = god_payload(player, wish, toss.get("hits") or [])
        kept = http_json("POST", "/v1/keep", {
            "player": player, "wish": wish, "echo": letter["echo"],
            "grant": letter["grant"], "absurdity": letter["absurdity"],
            "gift": letter["gift"], "cited_ids": letter["cited_ids"],
            "coin_id": letter["coin_id"],
        })
        recalled = http_json("POST", "/v1/toss", {
            "player": "另一位客人", "wish": wish[:12], "n_results": 3})
        hit_ids = [hit.get("id") for hit in recalled.get("hits") or []]
        found = f"w_{letter['coin_id']}" in hit_ids or f"e_{letter['coin_id']}" in hit_ids
        report = {
            "store": store_name(),
            "toss": toss,
            "echo": letter,
            "kept": kept,
            "recall_toss": recalled,
            "recalled_own_coin": found,
        }
        results = TRACK / "results"
        results.mkdir(parents=True, exist_ok=True)
        (results / "sample_run.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print()
        print(letter["echo"])
        print()
        print(f"许愿币 W-{letter['coin_id']} 已入池；再次投币能找回自己：{found}")
        print("证据已写入 results/sample_run.json")
    finally:
        if server is not None:
            server.shutdown()


if __name__ == "__main__":
    main()