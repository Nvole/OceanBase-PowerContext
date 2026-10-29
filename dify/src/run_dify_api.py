"""Run the imported Dify Workflow app and save a redacted evidence record.

Required environment variables:
  DIFY_API_BASE: Dify server URL, for example http://127.0.0.1
  DIFY_API_KEY: the app API key generated after importing the DSL

The key is never written to the evidence file.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


TRACK = Path(__file__).resolve().parents[1]
SAMPLE = TRACK / "data" / "sample_input.json"
RESULT = TRACK / "results" / "dify_run.json"


def main() -> int:
    base = os.environ.get("DIFY_API_BASE", "http://127.0.0.1").rstrip("/")
    key = os.environ.get("DIFY_API_KEY", "").strip()
    if not key:
        raise SystemExit("DIFY_API_KEY is required after importing the DSL into Dify")

    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    inputs = {key: sample[key] for key in ("player", "motion", "side", "argument")}
    payload = json.dumps({
        "inputs": inputs,
        "response_mode": "blocking",
        "user": "dify-competition-sample",
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/v1/workflows/run",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:1000]
        raise SystemExit(f"Dify workflow request failed with HTTP {error.code}: {detail}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Dify workflow request failed: {type(error).__name__}: {error}") from error

    data = body.get("data") or {}
    outputs = data.get("outputs") or {}
    if status != 200 or data.get("status") != "succeeded":
        raise SystemExit(f"Dify workflow did not succeed: {json.dumps(body, ensure_ascii=False)[:2000]}")
    if not outputs.get("rebuttal"):
        raise SystemExit("Dify workflow succeeded without the rebuttal output")

    evidence = {
        "entrypoint": "dify_workflow_api",
        "dify_api_base": base,
        "api_http_status": status,
        "workflow_status": data.get("status"),
        "workflow_run_id": data.get("id"),
        "task_id": data.get("task_id"),
        "input": sample,
        "outputs": outputs,
        "api_key_recorded": False,
    }
    RESULT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"DIFY_WORKFLOW_OK {data.get('id', '')}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
