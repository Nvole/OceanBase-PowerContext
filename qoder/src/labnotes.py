"""Lab-meeting note retrieval on seekdb collection track05_labnotes.

Hybrid search is where_document.$contains plus knn plus RRF.
Writes call refresh_index before a new code is expected to be searchable.
Embeddings are hashed locally so no model is downloaded.
"""
import argparse
import json
import re
import secrets
import threading
from pathlib import Path

import pyseekdb
from pyseekdb import HNSWConfiguration

from embeddings import DIMENSION, embed_text

COLLECTION = 'track05_labnotes'
CODE_RE = re.compile(r'^LN[0-9A-F]{10}$')
_LOCK = threading.RLock()
_CLIENT = None
_COLLECTION = None


def track_root():
    return Path(__file__).resolve().parents[1]


def seed_file():
    return Path(__file__).resolve().parent / 'seed_labnotes.json'


def load_settings():
    path = track_root() / '.env'
    if not path.is_file():
        raise RuntimeError('track .env is missing')
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
    required = ('SEEKDB_HOST', 'SEEKDB_PORT', 'SEEKDB_USER', 'SEEKDB_PASSWORD', 'SEEKDB_DATABASE')
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise RuntimeError('track .env is incomplete')
    return {
        'host': values['SEEKDB_HOST'],
        'port': int(values['SEEKDB_PORT']),
        'user': values['SEEKDB_USER'],
        'password': values['SEEKDB_PASSWORD'],
        'database': values['SEEKDB_DATABASE'],
    }


def has_cjk(text):
    return any('\u4e00' <= char <= '\u9fff' for char in text)


def load_seed_notes():
    notes = json.loads(seed_file().read_text(encoding='utf-8'))
    if not isinstance(notes, list) or len(notes) < 10:
        raise ValueError('seed file must contain at least 10 notes')
    seen_ids = set()
    seen_codes = set()
    normalized = []
    for note in notes:
        item = normalize_note(note, origin='seed', assign_code=False)
        if item['id'] in seen_ids or item['code'] in seen_codes:
            raise ValueError('seed ids and codes must be unique')
        seen_ids.add(item['id'])
        seen_codes.add(item['code'])
        normalized.append(item)
    return normalized


def normalize_note(note, origin, assign_code):
    if not isinstance(note, dict):
        raise ValueError('note must be an object')
    title = clean_text(note.get('title', ''), 'title', 80)
    body = clean_text(note.get('body', ''), 'body', 4000)
    topic = clean_text(note.get('topic', ''), 'topic', 40)
    meeting = clean_text(note.get('meeting') or '未标注场次', 'meeting', 40)
    if not has_cjk(title + body):
        raise ValueError('note must contain Chinese text')
    if assign_code:
        code = note.get('code') or new_code()
    else:
        code = str(note.get('code') or '').strip()
    if origin == 'import' and not CODE_RE.fullmatch(code):
        raise ValueError('import code is invalid')
    if origin == 'seed' and not re.fullmatch(r'LN[A-Z0-9]+', code):
        raise ValueError('seed code is invalid')
    note_id = str(note.get('id') or '').strip()
    if origin == 'import':
        note_id = 'ln-import-' + code.lower()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', note_id):
        raise ValueError('note id is invalid')
    return {
        'id': note_id,
        'code': code,
        'title': title,
        'topic': topic,
        'meeting': meeting,
        'body': body,
        'origin': origin,
    }


def clean_text(value, label, limit):
    text = str(value).replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text or len(text) > limit or '\x00' in text:
        raise ValueError(f'{label} length is invalid')
    return text


def new_code():
    return 'LN' + secrets.token_hex(5).upper()


def render_document(note):
    return (
        f"代号：{note['code']}\n"
        f"标题：{note['title']}\n"
        f"主题：{note['topic']}\n"
        f"场合：{note['meeting']}\n"
        f"正文：{note['body']}\n"
    )


def connect():
    global _CLIENT, _COLLECTION
    with _LOCK:
        if _COLLECTION is not None:
            return _COLLECTION
        settings = load_settings()
        client = pyseekdb.Client(
            host=settings['host'],
            port=settings['port'],
            user=settings['user'],
            password=settings['password'],
            database=settings['database'],
        )
        _CLIENT = client
        _COLLECTION = ensure_collection(client)
        return _COLLECTION


def ensure_collection(client):
    if client.has_collection(COLLECTION):
        current = client.get_collection(COLLECTION, embedding_function=None)
        if current.dimension == DIMENSION:
            return current
        client.delete_collection(COLLECTION)
    return client.create_collection(
        name=COLLECTION,
        configuration=HNSWConfiguration(dimension=DIMENSION, distance='cosine'),
        embedding_function=None,
    )


def upsert_notes(notes):
    collection = connect()
    documents = [render_document(note) for note in notes]
    payload = {
        'ids': [note['id'] for note in notes],
        'documents': documents,
        'embeddings': [embed_text(document) for document in documents],
        'metadatas': [
            {
                'code': note['code'],
                'title': note['title'],
                'topic': note['topic'],
                'meeting': note['meeting'],
                'origin': note['origin'],
            }
            for note in notes
        ],
    }
    with _LOCK:
        collection.upsert(**payload)
        collection.refresh_index()


def seed():
    notes = load_seed_notes()
    data_path = track_root() / 'data' / 'labnotes.json'
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(seed_file().read_text(encoding='utf-8'), encoding='utf-8')
    upsert_notes(notes)
    return {'seeded': len(notes), 'collection': COLLECTION, 'refresh_index': True}


def import_note(title, body, topic, meeting='', code=None):
    note = normalize_note(
        {'title': title, 'body': body, 'topic': topic, 'meeting': meeting, 'code': code},
        origin='import',
        assign_code=True,
    )
    upsert_notes([note])
    return {
        'id': note['id'],
        'code': note['code'],
        'title': note['title'],
        'topic': note['topic'],
        'meeting': note['meeting'],
        'origin': note['origin'],
        'refresh_index': True,
    }


def stats():
    collection = connect()
    with _LOCK:
        count = int(collection.count())
    return {'collection': COLLECTION, 'count': count}


def hybrid_search_raw(keyword, query_text, n_results):
    """Full-text $contains, explicit knn embeddings, then RRF."""
    collection = connect()
    vector = embed_text(query_text)
    with _LOCK:
        return collection.hybrid_search(
            query={'where_document': {'$contains': keyword}, 'n_results': n_results},
            knn={'query_embeddings': [vector], 'n_results': n_results},
            rank={'rrf': {}},
            n_results=n_results,
            include=['documents', 'metadatas', 'distances'],
        )


def search_notes(keyword, query_text=None, n_results=5):
    keyword = str(keyword).strip()
    if not keyword or len(keyword) > 64 or '\x00' in keyword:
        raise ValueError('keyword must be 1 to 64 characters')
    query_text = str(query_text if query_text is not None else keyword).strip()
    if not query_text or len(query_text) > 500 or '\x00' in query_text:
        raise ValueError('query must be 1 to 500 characters')
    try:
        n_results = int(n_results)
    except (TypeError, ValueError) as exc:
        raise ValueError('n_results must be between 1 and 10') from exc
    if n_results < 1 or n_results > 10:
        raise ValueError('n_results must be between 1 and 10')
    window = max(n_results, 10)
    raw = hybrid_search_raw(keyword, query_text, window)
    ids = first_group(raw.get('ids'))
    documents = first_group(raw.get('documents'))
    metadatas = first_group(raw.get('metadatas'))
    distances = first_group(raw.get('distances'))
    needle = keyword.lower()
    hits = []
    for index, note_id in enumerate(ids):
        document = documents[index] if index < len(documents) and documents[index] is not None else ''
        if needle not in str(document).lower():
            continue
        metadata = metadata_dict(metadatas[index] if index < len(metadatas) else None)
        distance = distances[index] if index < len(distances) else None
        hits.append({
            'id': note_id,
            'code': metadata.get('code') or line_value(document, '代号'),
            'title': metadata.get('title') or line_value(document, '标题'),
            'topic': metadata.get('topic') or line_value(document, '主题'),
            'meeting': metadata.get('meeting') or line_value(document, '场合'),
            'origin': metadata.get('origin') or '',
            'document': document,
            'distance': float(distance) if isinstance(distance, (int, float)) else None,
        })
        if len(hits) >= n_results:
            break
    return {
        'collection': COLLECTION,
        'keyword': keyword,
        'query': query_text,
        'mode': 'hybrid',
        'rank': 'rrf',
        'where_document': {'$contains': keyword},
        'hybrid_ids': list(ids),
        'hits': hits,
    }


def first_group(value):
    if not value:
        return []
    if isinstance(value, list) and value and isinstance(value[0], list):
        return value[0]
    return list(value)


def metadata_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def line_value(document, label):
    prefix = label + '：'
    for line in str(document).splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ''


def main():
    parser = argparse.ArgumentParser(description='Search or import lab-meeting notes.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('seed')
    search = sub.add_parser('search')
    search.add_argument('--keyword', required=True)
    search.add_argument('--query', default=None)
    search.add_argument('--n-results', type=int, default=5)
    imported = sub.add_parser('import')
    imported.add_argument('--title', required=True)
    imported.add_argument('--body', required=True)
    imported.add_argument('--topic', required=True)
    imported.add_argument('--meeting', default='')
    args = parser.parse_args()
    if args.command == 'seed':
        result = seed()
    elif args.command == 'search':
        result = search_notes(args.keyword, args.query, args.n_results)
    else:
        result = import_note(args.title, args.body, args.topic, args.meeting)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
