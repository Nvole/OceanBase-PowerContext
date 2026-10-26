"""Upload seekdb-hybrid-lab only when MODELSCOPE_API_TOKEN is set.

The token is read from the environment and is never printed, logged, or written.
This script does not read or modify .env and does not connect to seekdb.
Without the token it records uploaded=false and makes no network call.
"""

import json
import os
import sys
import uuid
import urllib.error
import urllib.request
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
ZIP_PATH = TRACK / "dist" / "seekdb-hybrid-lab.zip"
RESULT = TRACK / "results" / "upload_result.json"
API = "https://modelscope.cn/openapi/v1"
TOKEN_NAME = "MODELSCOPE_API_TOKEN"
SKILL_NAME = "seekdb-hybrid-lab"


def write_result(payload):
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def redact(text, token):
    if token:
        return text.replace(token, "[redacted]")
    return text


def request_json(method, url, token, payload=None, body=None, content_type=None):
    data = body
    headers = {"Authorization": "Bearer " + token}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    elif content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        status = error.code
    if not raw:
        return status, {}
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit("ModelScope returned non-JSON: " + redact(raw[:300], token)) from error


def data_of(payload):
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def upload_file(token):
    boundary = "----seekdbhybridlab" + uuid.uuid4().hex
    content = ZIP_PATH.read_bytes()
    filename = ZIP_PATH.name
    body = b"".join(
        [
            ("--" + boundary + "\r\n").encode("utf-8"),
            (
                'Content-Disposition: form-data; name="file"; filename="' + filename + '"\r\n'
            ).encode("utf-8"),
            b"Content-Type: application/zip\r\n\r\n",
            content,
            ("\r\n--" + boundary + "--\r\n").encode("utf-8"),
        ]
    )
    status, payload = request_json(
        "POST",
        API + "/files/upload",
        token,
        body=body,
        content_type="multipart/form-data; boundary=" + boundary,
    )
    file_id = data_of(payload).get("id")
    if status >= 400 or not file_id:
        raise SystemExit("file upload failed with status " + str(status))
    return file_id


def main():
    token = os.environ.get(TOKEN_NAME, "").strip()
    base = {
        "skill_name": SKILL_NAME,
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size if ZIP_PATH.is_file() else None,
        "token_printed": False,
        "seekdb_contacted": False,
        "env_file_modified": False,
    }
    if not token:
        base.update(
            {
                "uploaded": False,
                "reason": "MODELSCOPE_API_TOKEN is not set",
                "network_called": False,
            }
        )
        write_result(base)
        print("uploaded=false")
        return 0
    if not ZIP_PATH.is_file():
        raise SystemExit("zip is missing; run scripts/package_skill.py first")
    if ZIP_PATH.stat().st_size >= 5 * 1024 * 1024:
        raise SystemExit("zip must be smaller than 5MB")
    try:
        status, me = request_json("GET", API + "/users/me", token)
        if status >= 400:
            raise SystemExit("users/me failed with status " + str(status))
        owner = data_of(me).get("username") or data_of(me).get("name")
        if not owner:
            raise SystemExit("users/me did not return an owner")
        file_id = upload_file(token)
        create_body = {
            "skill_name": SKILL_NAME,
            "owner": owner,
            "display_name": "seekdb 混合检索实验",
            "description": "用三条示例演示 seekdb 的 upsert、refresh_index 和 hybrid_search。",
            "license": "Apache-2.0",
            "category": "developer-tools",
            "private": True,
            "skill_file": file_id,
        }
        status, created = request_json("POST", API + "/skills", token, payload=create_body)
        if status == 409:
            status, created = request_json(
                "PATCH",
                API + "/skills/" + owner + "/" + SKILL_NAME + "/settings",
                token,
                payload={"skill_file": file_id, "private": True},
            )
        if status >= 400:
            raise SystemExit("skill create or update failed with status " + str(status))
        page = data_of(created).get("url") or (
            "https://modelscope.cn/skills/" + owner + "/" + SKILL_NAME
        )
        base.update(
            {
                "uploaded": True,
                "network_called": True,
                "owner": owner,
                "private": True,
                "url": page,
                "file_id": file_id,
            }
        )
        write_result(base)
        print("uploaded=true")
        return 0
    except Exception as error:
        message = redact(str(error), token)
        base.update({"uploaded": False, "reason": message, "network_called": True})
        write_result(base)
        print("uploaded=false")
        return 1


if __name__ == "__main__":
    sys.exit(main())
