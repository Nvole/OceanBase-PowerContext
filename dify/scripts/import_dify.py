import argparse
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dify_client import PROJECT, RUNTIME, DifyConsole, credentials_from_environment, write_private


def main():
    parser = argparse.ArgumentParser(description="Import and publish the actual Dify Workflow")
    parser.add_argument("--console-base", default="http://127.0.0.1:15001")
    parser.add_argument("--initialize-local", action="store_true")
    parser.add_argument("--output", type=Path, default=PROJECT / "evidence")
    arguments = parser.parse_args()
    console = DifyConsole(arguments.console_base)
    setup = console.wait_ready()
    if setup["step"] == "not_started":
        if not arguments.initialize_local or urlsplit(arguments.console_base).hostname not in {"127.0.0.1", "localhost"}:
            raise SystemExit("Initialize your own Dify in its UI, or explicitly use --initialize-local on your new loopback stack")
        credentials = {"email": "reviewer@example.com", "password": "DifyV2-" + secrets.token_hex(16)}
        write_private(RUNTIME / "admin.json", credentials)
        console.request("POST", "/setup", {**credentials, "name": "DifyV2Reviewer", "language": "zh-Hans"})
    credentials = credentials_from_environment()
    console.login(credentials)
    dsl_path = PROJECT / "docs" / "absurd_debate.dsl.yml"
    dsl = dsl_path.read_text(encoding="utf-8")
    private_app = RUNTIME / "app.json"
    previous = json.loads(private_app.read_text(encoding="utf-8")) if private_app.exists() else {}
    payload = {"mode": "yaml-content", "yaml_content": dsl}
    if previous.get("console_base") == console.base and previous.get("app_id"):
        payload["app_id"] = previous["app_id"]
    imported = console.request("POST", "/apps/imports", payload)
    if imported.get("status") == "pending":
        imported = console.request("POST", "/apps/imports/" + imported["id"] + "/confirm")
    if imported.get("status") not in {"completed", "completed-with-warnings"} or not imported.get("app_id"):
        raise RuntimeError("Dify import did not complete")
    app_id = imported["app_id"]
    published = console.request("POST", f"/apps/{app_id}/workflows/publish", {})
    if published.get("result") != "success":
        raise RuntimeError("Dify Workflow publication did not succeed")
    api_key = previous.get("api_key") if previous.get("app_id") == app_id else None
    if not api_key:
        api_key = console.request("POST", f"/apps/{app_id}/api-keys", {})["token"]
    write_private(private_app, {"app_id": app_id, "api_key": api_key, "console_base": console.base})
    exported = console.request("GET", f"/apps/{app_id}/export?include_secret=false")
    arguments.output.mkdir(parents=True, exist_ok=True)
    (arguments.output / "dify_exported.yml").write_text(exported["data"], encoding="utf-8")
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(), "dify_version": "1.12.0",
        "app_id": app_id, "import_status": imported["status"], "published": True,
        "dsl_sha256": hashlib.sha256(dsl_path.read_bytes()).hexdigest(),
        "exported_from_real_dify": True, "runtime_secrets_included": False,
    }
    (arguments.output / "dify_import.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    print("API key and local account are private in .runtime/; never submit that directory")


if __name__ == "__main__":
    main()
