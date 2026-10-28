"""Wishwell HTTP service. It listens only on 127.0.0.1:18604."""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

from poolgod import coin_id_for  # noqa: E402
from wishwell import COLLECTION, SEED_FILE, ensure_ready, hybrid_hits, save_wish, store_name  # noqa: E402

HOST = "127.0.0.1"
PORT = 18604
COIN_ID = re.compile(r"[A-Za-z0-9_]{4,40}")
COLLECTION_HANDLE = None
STORE = None


def ready():
    global COLLECTION_HANDLE, STORE
    STORE = store_name()
    if STORE == "seekdb" and not (SRC.parent / ".env").exists():
        raise SystemExit("missing track .env; refusing to start")
    COLLECTION_HANDLE = ensure_ready()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?", 1)[0]))

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _read(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > 65536:
            raise ValueError("body size is invalid")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            raise ValueError("JSON body required")
        return json.loads(raw.decode("utf-8"))

    def _fail(self, exc):
        detail = str(exc)
        message = type(exc).__name__
        if "password" not in detail.lower() and "SEEKDB_" not in detail:
            message = f"{message}: {detail[:300]}"
        self._send(500, {"error": message})

    def _text(self, payload, key, limit, required=True, default=""):
        value = payload.get(key, default)
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        value = value.strip()
        if required and not value:
            raise ValueError(f"{key} is required")
        if len(value) > limit:
            raise ValueError(f"{key} is too long")
        return value

    def _n_results(self, payload):
        value = payload.get("n_results", 3)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
            raise ValueError("n_results must be an integer from 1 to 8")
        return value

    def _percent(self, payload, key):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 99:
            raise ValueError(f"{key} must be an integer from 1 to 99")
        return value

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/health":
                self._send(200, {
                    "ok": True,
                    "bind": f"{HOST}:{PORT}",
                    "store": STORE,
                    "collection": COLLECTION,
                    "count": COLLECTION_HANDLE.count(),
                })
                return
            if path == "/v1/pond":
                seeds = json.loads(SEED_FILE.read_text(encoding="utf-8"))
                self._send(200, {
                    "store": STORE,
                    "collection": COLLECTION,
                    "count": COLLECTION_HANDLE.count(),
                    "seeds": [{"id": seed["id"], "player": seed["player"], "wish": seed["wish"]} for seed in seeds],
                })
                return
            self._send(404, {"error": "not found"})
        except Exception as exc:
            self._fail(exc)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            payload = self._read()
            if path == "/v1/toss":
                self._send(200, self._toss(payload))
            elif path == "/v1/keep":
                self._send(200, self._keep(payload))
            else:
                self._send(404, {"error": "not found"})
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:
            self._fail(exc)

    def _toss(self, payload):
        player = self._text(payload, "player", 24, required=False, default="无名路人") or "无名路人"
        wish = self._text(payload, "wish", 200)
        result = hybrid_hits(COLLECTION_HANDLE, wish, n_results=self._n_results(payload))
        result.update({
            "player": player,
            "wish": wish,
            "store": STORE,
            "count": COLLECTION_HANDLE.count(),
        })
        return result

    def _keep(self, payload):
        player = self._text(payload, "player", 24, required=False, default="无名路人") or "无名路人"
        wish = self._text(payload, "wish", 200)
        echo = self._text(payload, "echo", 800)
        grant = self._percent(payload, "grant")
        absurdity = self._percent(payload, "absurdity")
        gift = self._text(payload, "gift", 40, required=False, default="")
        cited_ids = payload.get("cited_ids") or []
        if not isinstance(cited_ids, list):
            raise ValueError("cited_ids must be a list")
        cleaned = [str(item) for item in cited_ids[:8]]
        for item in cleaned:
            if len(item) > 40:
                raise ValueError("cited_ids contains an invalid id")
        coin_id = payload.get("coin_id") or coin_id_for(player, wish)
        if not isinstance(coin_id, str) or not COIN_ID.fullmatch(coin_id):
            raise ValueError("coin_id is invalid")
        return save_wish(
            COLLECTION_HANDLE, player, wish, echo, grant, absurdity,
            gift, cleaned, coin_id)


def main():
    ready()
    server = HTTPServer((HOST, PORT), Handler)
    bound_host, bound_port = server.server_address[:2]
    if bound_host != HOST or bound_port != PORT:
        raise RuntimeError("refusing to bind any address other than 127.0.0.1:18604")
    print(f"listening http://{HOST}:{PORT} (store={STORE})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()