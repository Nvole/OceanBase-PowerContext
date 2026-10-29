import base64
import json
import os
import time
from pathlib import Path

import httpx


PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = PROJECT / ".runtime"


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


class DifyConsole:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.client = httpx.Client(base_url=self.base, trust_env=False, timeout=180)

    def request(self, method, path, payload=None):
        csrf = next((cookie.value for cookie in self.client.cookies.jar if cookie.name.endswith("csrf_token")), None)
        headers = {"X-CSRF-Token": csrf} if csrf else {}
        response = self.client.request(method, "/console/api" + path, json=payload, headers=headers)
        if response.is_error:
            raise RuntimeError(f"Dify console {method} {path} returned HTTP {response.status_code}: {response.text[:500]}")
        return response.json()

    def wait_ready(self, timeout=300):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                return self.request("GET", "/setup")
            except (httpx.HTTPError, RuntimeError):
                time.sleep(3)
        raise RuntimeError("Dify API did not become ready; inspect docker compose logs api")

    def login(self, credentials):
        result = self.request("POST", "/login", {
            "email": credentials["email"], "password": base64.b64encode(credentials["password"].encode("utf-8")).decode("ascii"), "remember_me": True,
        })
        if result.get("result") != "success":
            raise RuntimeError("Dify login did not succeed")


def credentials_from_environment():
    email = os.environ.get("DIFY_CONSOLE_EMAIL")
    password = os.environ.get("DIFY_CONSOLE_PASSWORD")
    if email and password:
        return {"email": email, "password": password}
    destination = RUNTIME / "admin.json"
    if destination.exists():
        return json.loads(destination.read_text(encoding="utf-8"))
    raise RuntimeError("Set DIFY_CONSOLE_EMAIL/PASSWORD, or initialize your new local Dify stack first")
