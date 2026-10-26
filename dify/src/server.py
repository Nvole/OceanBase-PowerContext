"""Debate HTTP service. It listens only on 127.0.0.1:18604."""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

from debate import COLLECTION, SEED_FILE, ensure_ready, hybrid_hits, save_round
from respond import host_reply, round_id_for

HOST = "127.0.0.1"
PORT = 18604
ROUND_ID = re.compile(r"[A-Za-z0-9_]{4,40}")
COLLECTION_HANDLE = None


def ready():
    global COLLECTION_HANDLE
    if not Path(SEED_FILE).parents[1].joinpath(".env").exists() and not (SRC.parent / ".env").exists():
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

    def _text(self, payload, key, limit, required=True):
        value = payload.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        value = value.strip()
        if required and not value:
            raise ValueError(f"{key} is required")
        if len(value) > limit:
            raise ValueError(f"{key} is too long")
        return value

    def _side(self, payload):
        side = self._text(payload, "side", 8)
        if side not in ("正方", "反方"):
            raise ValueError("side must be 正方 or 反方")
        return side

    def _n_results(self, payload):
        value = payload.get("n_results", 3)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
            raise ValueError("n_results must be an integer from 1 to 8")
        return value

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/health":
                self._send(200, {
                    "ok": True,
                    "bind": f"{HOST}:{PORT}",
                    "collection": COLLECTION,
                    "count": COLLECTION_HANDLE.count(),
                })
                return
            if path == "/v1/motions":
                seeds = json.loads(SEED_FILE.read_text(encoding="utf-8"))
                motions = []
                for seed in seeds:
                    if seed["motion"] not in motions:
                        motions.append(seed["motion"])
                self._send(200, {"motions": motions})
                return
            self._send(404, {"error": "not found"})
        except Exception as exc:
            self._fail(exc)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            payload = self._read()
            if path == "/v1/retrieve":
                self._send(200, self._retrieve(payload))
            elif path == "/v1/respond":
                self._send(200, self._respond(payload))
            elif path == "/v1/save":
                self._send(200, self._save(payload))
            else:
                self._send(404, {"error": "not found"})
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:
            self._fail(exc)

    def _retrieve(self, payload):
        if "text" in payload:
            text = self._text(payload, "text", 800)
        else:
            text = self._text(payload, "argument", 800)
        motion = self._text(payload, "motion", 40, required=False) if "motion" in payload else ""
        return hybrid_hits(COLLECTION_HANDLE, text, motion=motion, n_results=self._n_results(payload))

    def _respond(self, payload):
        player = self._text(payload, "player", 24)
        motion = self._text(payload, "motion", 40)
        side = self._side(payload)
        argument = self._text(payload, "argument", 240)
        hits = payload.get("hits") or []
        if not isinstance(hits, list):
            raise ValueError("hits must be a list")
        reply = host_reply(player, motion, side, argument, hits)
        reply.update({"player": player, "motion": motion, "side": side, "argument": argument})
        return reply

    def _save(self, payload):
        player = self._text(payload, "player", 24)
        motion = self._text(payload, "motion", 40)
        side = self._side(payload)
        argument = self._text(payload, "argument", 240)
        rebuttal = self._text(payload, "rebuttal", 800)
        host_side = self._text(payload, "host_side", 8)
        if host_side not in ("正方", "反方"):
            raise ValueError("host_side must be 正方 or 反方")
        score = payload.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 99:
            raise ValueError("score must be an integer from 1 to 99")
        cited_id = payload.get("cited_id") or ""
        if not isinstance(cited_id, str) or len(cited_id) > 40:
            raise ValueError("cited_id is invalid")
        round_id = payload.get("round_id") or round_id_for(player, motion, argument)
        if not isinstance(round_id, str) or not ROUND_ID.fullmatch(round_id):
            raise ValueError("round_id is invalid")
        return save_round(
            COLLECTION_HANDLE, player, motion, side, argument, rebuttal,
            score, cited_id, round_id, host_side)


def main():
    ready()
    server = HTTPServer((HOST, PORT), Handler)
    bound_host, bound_port = server.server_address[:2]
    if bound_host != HOST or bound_port != PORT:
        raise RuntimeError("refusing to bind any address other than 127.0.0.1:18604")
    print(f"listening http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()