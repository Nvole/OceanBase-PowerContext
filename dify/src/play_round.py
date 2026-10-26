"""Play one round with curl, in the same order as the Dify DSL.

This does not import the DSL into Dify. There is no Dify UI on this machine.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
TRACK = SRC.parent
RESULT = TRACK / "results"
CURL_DIR = RESULT / "curl"
SAMPLE_PATH = TRACK / "data" / "sample_input.json"
BASE = "http://127.0.0.1:18604"


def curl(url, out_path, body_path=None):
    command = [
        "curl", "-sS", "-m", "30", "-o", str(out_path), "-w", "%{http_code}",
        "-H", "Content-Type: application/json; charset=utf-8",
    ]
    if body_path is not None:
        command.extend(["--data-binary", f"@{body_path}"])
    command.append(url)
    proc = subprocess.run(command, check=False, capture_output=True)
    text = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
    try:
        body = json.loads(text) if text else None
    except json.JSONDecodeError:
        body = {"raw": text}
    return {
        "http_code": proc.stdout.decode("ascii", "replace").strip(),
        "stderr": proc.stderr.decode("utf-8", "replace")[-500:],
        "body": body,
        "curl": command,
    }


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def wait_health(out_path):
    last = None
    for _ in range(60):
        last = curl(f"{BASE}/health", out_path)
        if last["http_code"] == "200" and (last["body"] or {}).get("ok"):
            return last
        time.sleep(0.5)
    raise RuntimeError(f"health check failed: {last}")


def listen_lines():
    proc = subprocess.run(["ss", "-ltn"], check=False, capture_output=True, text=True)
    return [line.strip() for line in proc.stdout.splitlines() if ":18604" in line]


def main():
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    CURL_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RESULT / "server.log"
    log_file = log_path.open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, str(SRC / "server.py")],
        cwd=str(TRACK.parents[1]),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_file.close()
    report = {
        "application": "离谱辩题",
        "dify_imported": False,
        "dify_ui_available": False,
        "note": "本机没有 Dify 界面，DSL 未导入。下面按 DSL 的顺序用 curl 打完一局：输入、HTTP 检索、回应、HTTP 保存、输出。",
        "dsl": "docs/absurd_debate.dsl.yml",
        "orchestration": ["输入", "HTTP 检索", "回应", "HTTP 保存", "输出"],
        "bind": "127.0.0.1:18604",
        "collection": "track04_debate",
        "input": sample,
        "server_pid": server.pid,
    }
    try:
        health = wait_health(CURL_DIR / "health.json")
        lines = listen_lines()
        if not any("127.0.0.1:18604" in line for line in lines):
            raise RuntimeError(f"service is not bound to 127.0.0.1:18604: {lines}")
        if any(line.startswith("0.0.0.0:18604") or " 0.0.0.0:18604" in line for line in lines):
            raise RuntimeError(f"service is exposed beyond loopback: {lines}")
        retrieve_body = {
            "text": sample["argument"],
            "motion": sample["motion"],
            "n_results": sample["n_results"],
        }
        write_json(CURL_DIR / "retrieve_body.json", retrieve_body)
        retrieve = curl(f"{BASE}/v1/retrieve", CURL_DIR / "retrieve.json", CURL_DIR / "retrieve_body.json")
        hits = (retrieve["body"] or {}).get("hits") or []
        if retrieve["http_code"] != "200" or not hits:
            raise RuntimeError(f"retrieve failed: {retrieve}")
        if (hits[0].get("metadata") or {}).get("motion") != sample["motion"]:
            raise RuntimeError(f"hybrid search did not surface the motion: {hits}")
        respond_body = {
            "player": sample["player"],
            "motion": sample["motion"],
            "side": sample["side"],
            "argument": sample["argument"],
            "hits": hits,
        }
        write_json(CURL_DIR / "respond_body.json", respond_body)
        respond = curl(f"{BASE}/v1/respond", CURL_DIR / "respond.json", CURL_DIR / "respond_body.json")
        reply = respond["body"] or {}
        if respond["http_code"] != "200" or "主持人杠精" not in reply.get("rebuttal", ""):
            raise RuntimeError(f"respond failed: {respond}")
        if reply.get("host_side") != "反方" or reply.get("cited_id") != hits[0]["id"]:
            raise RuntimeError(f"respond did not cite the retrieved card: {reply}")
        save_body = {
            "player": sample["player"],
            "motion": sample["motion"],
            "side": sample["side"],
            "argument": sample["argument"],
            "rebuttal": reply["rebuttal"],
            "score": reply["score"],
            "cited_id": reply["cited_id"],
            "round_id": reply["round_id"],
            "host_side": reply["host_side"],
        }
        write_json(CURL_DIR / "save_body.json", save_body)
        saved = curl(f"{BASE}/v1/save", CURL_DIR / "save.json", CURL_DIR / "save_body.json")
        saved_body = saved["body"] or {}
        player_id = f"p_{reply['round_id']}"
        if saved["http_code"] != "200" or not saved_body.get("refreshed") or player_id not in saved_body.get("ids", []):
            raise RuntimeError(f"save failed: {saved}")
        again_body = {"text": saved_body["player_document"], "n_results": 3}
        write_json(CURL_DIR / "retrieve_after_body.json", again_body)
        again = curl(f"{BASE}/v1/retrieve", CURL_DIR / "retrieve_after.json", CURL_DIR / "retrieve_after_body.json")
        again_ids = [hit["id"] for hit in (again["body"] or {}).get("hits") or []]
        if again["http_code"] != "200" or player_id not in again_ids:
            raise RuntimeError(f"saved card is not hybrid-searchable after refresh_index: {again}")
        report.update({
            "listen": lines,
            "server_left_running": True,
            "steps": {
                "health": health,
                "retrieve": retrieve,
                "respond": respond,
                "save": saved,
                "retrieve_after_save": again,
            },
            "output": {
                "rebuttal": reply["rebuttal"],
                "score": reply["score"],
                "cited_id": reply["cited_id"],
                "round_id": reply["round_id"],
                "saved_ids": saved_body["ids"],
                "found_after_refresh": True,
                "fusion": retrieve["body"].get("fusion"),
                "keywords": retrieve["body"].get("keywords"),
            },
        })
        (RESULT / "sample_run.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("PLAY_OK", reply["round_id"])
    except Exception as exc:
        report["server_left_running"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            tail = ""
        if "password" in tail.lower() or "SEEKDB_" in tail:
            tail = "redacted"
        report["server_log_tail"] = tail
        (RESULT / "sample_run.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.killpg(server.pid, signal.SIGTERM)
        print("PLAY_FAIL", type(exc).__name__, exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()