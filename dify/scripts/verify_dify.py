import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from dify_client import PROJECT, RUNTIME, DifyConsole, credentials_from_environment


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_fingerprint():
    paths = [*PROJECT.glob("src/*.py"), *PROJECT.glob("scripts/*.py"), *PROJECT.glob("data/*.json"),
             PROJECT / "docs" / "absurd_debate.dsl.yml", PROJECT / "compose.yaml", PROJECT / "Dockerfile", PROJECT / "requirements.txt"]
    return {path.relative_to(PROJECT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description="Only a real published Dify Workflow can pass this acceptance")
    parser.add_argument("--api-base", default="http://127.0.0.1:15001/v1")
    parser.add_argument("--backend-base", default="http://127.0.0.1:18604")
    parser.add_argument("--seekdb-host")
    parser.add_argument("--restart-backend", action="store_true")
    parser.add_argument("--output", type=Path, default=PROJECT / "evidence")
    arguments = parser.parse_args()
    if arguments.seekdb_host:
        os.environ["SEEKDB_HOST"] = arguments.seekdb_host
    state_file = RUNTIME / "app.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    key = os.environ.get("DIFY_APP_API_KEY") or state.get("api_key")
    if not key:
        raise SystemExit("Import/publish in Dify first and set DIFY_APP_API_KEY, or run scripts/import_dify.py")
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "passed": False,
              "entrypoint": "Dify published Workflow /v1/workflows/run", "checks": {},
              "source_sha256": source_fingerprint(), "workflow_runs": [], "database": {}}
    checks = report["checks"]
    client = httpx.Client(trust_env=False, timeout=180)

    def check(name, condition):
        checks[name] = bool(condition)
        if not condition:
            raise AssertionError(name)

    def run(inputs, name):
        response = client.post(arguments.api_base.rstrip("/") + "/workflows/run",
                               headers={"Authorization": "Bearer " + key},
                               json={"inputs": inputs, "response_mode": "blocking", "user": inputs["player"]})
        response.raise_for_status()
        raw = response.json()
        write_json(arguments.output / (name + ".json"), raw)
        data = raw.get("data", {})
        check(name + "_dify_run_succeeded", bool(raw.get("workflow_run_id")) and data.get("status") == "succeeded")
        check(name + "_seven_nodes_executed", data.get("total_steps", 0) >= 7)
        outputs = data["outputs"]
        saved = json.loads(outputs["saved"])
        check(name + "_seekdb_hybrid", outputs.get("fusion") == "seekdb_hybrid_rrf")
        check(name + "_write_confirmed", saved["refreshed"] is True and saved["ids"] == ["p_" + outputs["round_id"], "h_" + outputs["round_id"]])
        report["workflow_runs"].append({"name": name, "run_id": raw["workflow_run_id"], "status": data["status"], "total_steps": data["total_steps"]})
        return outputs, saved

    try:
        unauthorized = client.post(arguments.api_base.rstrip("/") + "/workflows/run", headers={"Authorization": "Bearer invalid-verification-token"}, json={})
        check("dify_rejects_invalid_app_token", unauthorized.status_code == 401)
        identifier = uuid.uuid4().hex[:10]
        inputs = {"player": "验收_" + identifier, "motion": "猫应该交税_" + identifier, "side": "正方",
                  "argument": '猫霸占窗台阳光却不交税！证人说"喵"。\n我的编号：' + identifier}
        first, first_saved = run(inputs, "01_first_workflow")
        second_inputs = {**inputs, "argument": "我还要为刚才的阳光税申请退款，呼噜也算劳动！编号：" + identifier}
        second, second_saved = run(second_inputs, "02_continuous_workflow")
        check("new_memory_reused_by_next_dify_run", "p_" + first["round_id"] in json.loads(second["retrieved_ids"]))
        repeated, repeated_saved = run(inputs, "03_idempotent_workflow")
        check("retry_does_not_duplicate_cards", repeated_saved["ids"] == first_saved["ids"] and repeated_saved["count"] == second_saved["count"])
        check("quotes_and_newlines_survive_dify", inputs["argument"] in first_saved["player_document"])
        sys.path.insert(0, str(PROJECT / "src"))
        from db import connection_settings
        from debate import open_collection
        import pymysql

        settings = connection_settings()
        with pymysql.connect(**settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT VERSION()")
                version = str(cursor.fetchone()[0])
        collection = open_collection()
        expected_ids = first_saved["ids"] + second_saved["ids"]
        rows = collection.get(ids=expected_ids, include=["documents", "metadatas"])
        check("four_dify_generated_cards_exist_in_real_database", set(expected_ids) == set(rows["ids"]))
        report["database"] = {"version": version, "database": settings["database"], "collection": first_saved["collection"], "verified_ids": expected_ids}
        write_json(arguments.output / "seekdb_saved_cards.json", rows)
        if arguments.restart_backend:
            command = json.loads(os.environ.get("DIFY_DOCKER_COMMAND", '["docker"]'))
            result = subprocess.run(command + ["compose", "restart", "debate"], cwd=PROJECT, capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError("Backend restart command failed; inspect docker compose status")
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    response = client.get(arguments.backend_base.rstrip("/") + "/health", timeout=5)
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(2)
            after, after_saved = run(second_inputs, "04_after_backend_restart")
            check("backend_restart_preserves_seekdb_memory", set(expected_ids).issubset(set(json.loads(after["retrieved_ids"]))) and after_saved["count"] == second_saved["count"])
        else:
            report["backend_restart"] = "not_requested"
        if state.get("app_id"):
            console = DifyConsole(state["console_base"])
            console.login(credentials_from_environment())
            for item in report["workflow_runs"]:
                trace = console.request("GET", f'/apps/{state["app_id"]}/workflow-runs/{item["run_id"]}/node-executions')
                write_json(arguments.output / (item["name"] + "_nodes.json"), trace)
                executions = trace.get("data", [])
                check(item["name"] + "_node_execution_trace", len(executions) >= 7 and all(node.get("status") == "succeeded" for node in executions))
        report["passed"] = all(checks.values())
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)[:500].replace(key, "[REDACTED]")}
    finally:
        write_json(arguments.output / "dify_acceptance.json", report)
        client.close()
    print(json.dumps({"passed": report["passed"], "checks": checks, "error": report.get("error")}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
