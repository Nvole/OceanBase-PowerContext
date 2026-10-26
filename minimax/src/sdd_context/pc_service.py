"""Start and stop the track-local PowerContext server on 127.0.0.1:18617."""

import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from sdd_context.paths import track_root

HOST = "127.0.0.1"
PORT = 18617
BASE_URL = f"http://{HOST}:{PORT}"


def home_dir() -> Path:
    return track_root() / ".powercontext" / "home"


def env_path() -> Path:
    return track_root() / ".powercontext" / "server.env"


def log_path() -> Path:
    return track_root() / ".powercontext" / "logs" / "server.log"


def pid_path() -> Path:
    return track_root() / ".powercontext" / "server.pid"


def binary() -> Path:
    return track_root() / ".powercontext" / "venv" / "bin" / "powercontext"


def write_env() -> None:
    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    database = home / "powercontext.db"
    content = "\n".join([
        f"POWERCONTEXT_HOME={home.as_posix()}",
        f"POWERCONTEXT_SERVER_HTTP_HOST={HOST}",
        f"POWERCONTEXT_SERVER_HTTP_PORT={PORT}",
        "POWERCONTEXT_SERVER_DATABASE_KIND=sqlite",
        f"POWERCONTEXT_SERVER_DATABASE_URL=sqlite+aiosqlite:///{database.as_posix()}",
        "POWERCONTEXT_SERVER_ACCESS_MODE=disabled",
        "POWERCONTEXT_SERVER_DASHBOARD_ENABLED=false",
        "POWERCONTEXT_SERVER_MCP_ENABLED=false",
        "POWERCONTEXT_SERVER_METRICS_ENABLED=false",
        f"POWERCONTEXT_SERVER_WORKSPACE={track_root().as_posix()}",
        "POWERCONTEXT_SERVER_LOGGING_LEVEL=INFO",
        "",
    ])
    path = env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def live() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "/health/live", timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def ready_body() -> dict:
    import json
    with urllib.request.urlopen(BASE_URL + "/health/ready", timeout=3) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def wipe_home() -> None:
    home = home_dir()
    if not home.exists():
        return
    for path in sorted(home.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            path.rmdir()


def start() -> dict:
    if not binary().is_file():
        return {"started": False, "status": "blocked", "reason": "powercontext binary is not installed in the track venv"}
    write_env()
    if live():
        owner = _port_owner()
        if owner and "powercontext" not in owner.lower():
            return {"started": False, "status": "blocked", "reason": "port 18617 is used by another process"}
        return {"started": True, "status": "already-running", "url": BASE_URL}
    log_path().parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path().open("a", encoding="utf-8")
    process = subprocess.Popen(
        [str(binary()), "server", "run", "--env-file", str(env_path())],
        cwd=str(track_root()),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pid_path().write_text(str(process.pid), encoding="utf-8")
    if not _wait_live(30):
        stop()
        return {
            "started": False,
            "status": "blocked",
            "reason": "PowerContext did not become live on 127.0.0.1:18617",
            "log_tail": _log_tail(),
        }
    ready = {}
    try:
        ready = ready_body()
    except (OSError, urllib.error.URLError, ValueError) as exc:
        ready = {"status": "unreadable", "error": type(exc).__name__}
    return {"started": True, "status": "running", "url": BASE_URL, "pid": process.pid, "ready": ready}


def stop() -> dict:
    pid_text = pid_path().read_text(encoding="utf-8").strip() if pid_path().is_file() else ""
    if not pid_text.isdigit():
        return {"stopped": live() is False}
    pid = int(pid_text)
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid_path().unlink(missing_ok=True)
        return {"stopped": True}
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(30):
        if not _pid_alive(pid):
            break
        time.sleep(0.2)
    if _pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass
    pid_path().unlink(missing_ok=True)
    return {"stopped": True}


def _wait_live(seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if live():
            return True
        time.sleep(0.5)
    return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _port_owner() -> str:
    try:
        completed = subprocess.run(["ss", "-ltnp"], check=False, capture_output=True, text=True)
    except OSError:
        return ""
    for line in completed.stdout.splitlines():
        if f":{PORT}" in line:
            return line
    return ""


def _log_tail() -> str:
    if not log_path().is_file():
        return ""
    lines = log_path().read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
    redacted = []
    for line in lines:
        lower = line.lower()
        if any(word in lower for word in ("password", "token", "secret", "api_key")):
            redacted.append("[redacted]")
        else:
            redacted.append(line)
    return "\n".join(redacted)
