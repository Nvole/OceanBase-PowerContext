"""Loopback UI and seekdb gateway.

Browser code computes embeddings. This process only stores vectors and calls
seekdb hybrid_search. It binds 127.0.0.1:18602 and does not load a model.
"""
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import kb

HOST = '127.0.0.1'
PORT = 18602
STATIC = Path(__file__).resolve().parent / 'static'
CORPUS_PATH = kb.TRACK / 'data' / 'corpus.jsonl'
EVAL_PATH = kb.TRACK / 'data' / 'eval_queries.json'
MAX_BODY = 2_000_000
MAX_ITEMS = 100
MAX_DOCUMENT_CHARS = 8000
METADATA_KEY = re.compile(r'[A-Za-z0-9_]{1,40}')
LOCK = threading.Lock()

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
}


def clean_metadata(metadata):
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError('metadata must be an object')
    clean = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not METADATA_KEY.fullmatch(key):
            raise ValueError('metadata key is invalid')
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError('metadata values must be strings or numbers')
        if isinstance(value, str) and len(value) > 200:
            raise ValueError('metadata value is too long')
        if isinstance(value, float) and (value != value or value in (float('inf'), float('-inf'))):
            raise ValueError('metadata value is non-finite')
        clean[key] = value
    clean.setdefault('source', 'user')
    return clean


def parse_items(payload):
    items = payload.get('items') if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError('items must be a non-empty list')
    if len(items) > MAX_ITEMS:
        raise ValueError('too many items')
    ids, documents, embeddings, metadatas = [], [], [], []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('each item must be an object')
        doc_id = item.get('id')
        document = item.get('document')
        if 'embedding' not in item:
            raise ValueError('embedding is required and is not computed on the server')
        if not isinstance(doc_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', doc_id):
            raise ValueError('document id is invalid')
        if not isinstance(document, str) or not document.strip() or len(document) > MAX_DOCUMENT_CHARS:
            raise ValueError('document text is missing or too long')
        ids.append(doc_id)
        documents.append(document)
        embeddings.append(item.get('embedding'))
        metadatas.append(clean_metadata(item.get('metadata')))
    return ids, documents, embeddings, metadatas


def public_state(collection):
    return {
        'collection': kb.COLLECTION_NAME,
        'database': 'track02_stepfun',
        'count': collection.count(),
        'dimension': kb.DIMENSION,
        'distance': kb.DISTANCE,
        'fulltext_analyzer': 'ik',
        'embedding_function': None,
        'server_computes_embeddings': False,
        'bind': f'{HOST}:{PORT}',
    }


def safe_error(error):
    text = f'{type(error).__name__}: {error}'
    try:
        secret = kb.load_settings()['password']
    except Exception:
        secret = ''
    if secret:
        text = text.replace(secret, '***')
    return text[:800]


def write_items(payload):
    ids, documents, embeddings, metadatas = parse_items(payload)
    with LOCK:
        with kb.connect() as client:
            collection = kb.open_collection(client)
            started = time.perf_counter()
            kb.upsert_documents(collection, ids, documents, embeddings, metadatas)
            upsert_ms = (time.perf_counter() - started) * 1000
            refresh_ms = kb.refresh(collection)
            state = public_state(collection)
    state.update({'upserted': len(ids), 'upsert_ms': upsert_ms, 'refresh_ms': refresh_ms, 'refreshed': True})
    return state


def search_items(payload):
    if not isinstance(payload, dict):
        raise ValueError('search body must be an object')
    if 'embedding' not in payload:
        raise ValueError('embedding is required and is not computed on the server')
    if 'query_texts' in payload:
        raise ValueError('query_texts is rejected so the server cannot embed the query')
    n_results = payload.get('n_results', 5)
    where = None
    session_id = payload.get('session_id')
    if session_id is not None:
        if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', session_id):
            raise ValueError('session_id is invalid')
        where = {'session_id': {'$eq': session_id}}
    with LOCK:
        with kb.connect() as client:
            collection = kb.open_collection(client)
            rows, search_ms = kb.hybrid_search(
                collection, payload.get('query', ''), payload.get('embedding'), n_results=n_results, where=where)
            count = collection.count()
    return {
        'collection': kb.COLLECTION_NAME,
        'count': count,
        'search_ms': search_ms,
        'rank': 'rrf',
        'rows': rows,
        'server_computes_embeddings': False,
    }


def reset_items(payload):
    if not isinstance(payload, dict) or payload.get('confirm') != 'reset-track02':
        raise ValueError('confirm must be reset-track02')
    with LOCK:
        with kb.connect() as client:
            collection = kb.reset_collection(client)
            state = public_state(collection)
    state['reset'] = True
    return state


def read_corpus():
    documents = []
    for line in CORPUS_PATH.read_text(encoding='utf-8').splitlines():
        if line.strip():
            item = json.loads(line)
            documents.append({'id': item['id'], 'title': item['title'], 'document': item['document']})
    return {'documents': documents, 'note': 'Vectors are not included. The browser must embed these texts.'}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print(f'{self.address_string()} {fmt % args}', flush=True)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/state':
            self._json(self._call(self._state))
        elif path == '/api/corpus':
            self._json(read_corpus())
        elif path == '/api/eval-queries':
            self._json(json.loads(EVAL_PATH.read_text(encoding='utf-8')))
        elif path in ('/', '/index.html'):
            self._file(STATIC / 'index.html')
        elif path.startswith('/static/'):
            self._file(STATIC / path[len('/static/'):])
        else:
            self._error(404, 'not found')

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self._body()
        except ValueError as error:
            self._error(400, str(error))
            return
        if path == '/api/upsert':
            self._json(self._call(lambda: write_items(payload)))
        elif path == '/api/search':
            self._json(self._call(lambda: search_items(payload)))
        elif path == '/api/reset':
            self._json(self._call(lambda: reset_items(payload)))
        else:
            self._error(404, 'not found')

    def _state(self):
        with LOCK:
            with kb.connect() as client:
                collection = kb.open_collection(client)
                return public_state(collection)

    def _call(self, func):
        try:
            return 200, func()
        except ValueError as error:
            return 400, {'error': safe_error(error)}
        except Exception as error:
            return 500, {'error': safe_error(error)}

    def _body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length <= 0 or length > MAX_BODY:
            raise ValueError('request body is missing or too large')
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except json.JSONDecodeError as error:
            raise ValueError('request body is not json') from error

    def _json(self, result):
        status, payload = result if isinstance(result, tuple) else (200, result)
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._json((status, {'error': message}))

    def _file(self, path):
        try:
            root = STATIC.resolve()
            target = path.resolve()
        except OSError:
            self._error(404, 'not found')
            return
        if target != root and root not in target.parents:
            self._error(404, 'not found')
            return
        if not target.is_file():
            self._error(404, 'not found')
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', MIME.get(target.suffix, 'application/octet-stream'))
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)


class LoopbackServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    server = LoopbackServer((HOST, PORT), Handler)
    print(f'listening {HOST}:{PORT}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
