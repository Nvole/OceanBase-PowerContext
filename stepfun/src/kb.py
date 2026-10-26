"""seekdb access for the browser knowledge base.

Embeddings are always supplied by the caller. This module does not load a model.
"""
import re
import time
from pathlib import Path

import pyseekdb
from pyseekdb import Configuration, FulltextIndexConfig, HNSWConfiguration

TRACK = Path(__file__).resolve().parents[1]
ENV_PATH = TRACK / '.env'
COLLECTION_NAME = 'track02_stepfun_kb'
DIMENSION = 384
DISTANCE = 'cosine'

_WORD = re.compile(r'[^\w\u4e00-\u9fff]+', re.UNICODE)


def load_settings(path=None):
    """Read the track connection file. Callers must not print the result."""
    env_path = Path(path) if path else ENV_PATH
    values = {}
    for raw in env_path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key] = value
    missing = [key for key in ('SEEKDB_HOST', 'SEEKDB_PORT', 'SEEKDB_USER', 'SEEKDB_PASSWORD', 'SEEKDB_DATABASE')
               if not values.get(key)]
    if missing:
        raise RuntimeError('track .env is missing required connection keys')
    return {
        'host': values['SEEKDB_HOST'],
        'port': int(values['SEEKDB_PORT']),
        'user': values['SEEKDB_USER'],
        'password': values['SEEKDB_PASSWORD'],
        'database': values['SEEKDB_DATABASE'],
    }


def connect(path=None):
    return pyseekdb.Client(**load_settings(path))


def index_configuration():
    return Configuration(
        hnsw=HNSWConfiguration(dimension=DIMENSION, distance=DISTANCE),
        fulltext_config=FulltextIndexConfig(analyzer='ik'),
    )


def open_collection(client, create=True):
    """Return track02_stepfun_kb with embedding generation disabled."""
    if client.has_collection(COLLECTION_NAME):
        collection = client.get_collection(COLLECTION_NAME, embedding_function=None)
    elif create:
        collection = client.create_collection(
            name=COLLECTION_NAME,
            configuration=index_configuration(),
            embedding_function=None,
        )
    else:
        raise ValueError(f'collection {COLLECTION_NAME} does not exist')
    if getattr(collection, '_embedding_function', None) is not None:
        raise RuntimeError('refusing to use a collection that still has an embedding function')
    return collection


def reset_collection(client):
    if client.has_collection(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
    return open_collection(client, create=True)


def check_embedding(embedding):
    if not isinstance(embedding, list) or len(embedding) != DIMENSION or (embedding and isinstance(embedding[0], list)):
        raise ValueError(f'embedding must be one {DIMENSION}-dimensional vector')
    values = []
    for item in embedding:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError('embedding values must be numbers')
        number = float(item)
        if number != number or number in (float('inf'), float('-inf')):
            raise ValueError('embedding has a non-finite value')
        values.append(number)
    return values


def contains_text(text):
    if not isinstance(text, str):
        raise ValueError('query text must be a string')
    cleaned = _WORD.sub(' ', text).strip()
    if not cleaned:
        raise ValueError('query text has no searchable tokens')
    if len(cleaned) > 200:
        raise ValueError('query text is too long')
    return cleaned


def upsert_documents(collection, ids, documents, embeddings, metadatas):
    if not ids:
        raise ValueError('at least one document is required')
    if not (len(ids) == len(documents) == len(embeddings) == len(metadatas)):
        raise ValueError('ids, documents, embeddings, and metadatas must have the same length')
    vectors = [check_embedding(embedding) for embedding in embeddings]
    collection.upsert(ids=list(ids), documents=list(documents), embeddings=vectors, metadatas=list(metadatas))


def refresh(collection):
    started = time.perf_counter()
    collection.refresh_index()
    return (time.perf_counter() - started) * 1000


def hybrid_search(collection, query_text, embedding, n_results=5, where=None):
    """Run seekdb hybrid search from a caller-supplied vector and full-text string."""
    if not isinstance(n_results, int) or not 1 <= n_results <= 20:
        raise ValueError('n_results must be an integer from 1 to 20')
    text = contains_text(query_text)
    vector = check_embedding(embedding)
    query = {'where_document': {'$contains': text}, 'n_results': n_results}
    knn = {'query_embeddings': [vector], 'n_results': n_results}
    if where:
        query['where'] = where
        knn['where'] = where
    started = time.perf_counter()
    result = collection.hybrid_search(
        query=query,
        knn=knn,
        rank={'rrf': {}},
        n_results=n_results,
        include=['documents', 'metadatas', 'distances'],
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    return rows_from_hybrid(result), elapsed_ms


def rows_from_hybrid(result):
    ids = _flat(result.get('ids'))
    documents = _flat(result.get('documents'))
    metadatas = _flat(result.get('metadatas'))
    distances = _flat(result.get('distances'))
    rows = []
    for index, doc_id in enumerate(ids):
        distance = distances[index] if index < len(distances) else None
        if distance is not None:
            distance = float(distance)
        metadata = metadatas[index] if index < len(metadatas) else None
        rows.append({
            'id': doc_id,
            'document': documents[index] if index < len(documents) else None,
            'metadata': metadata,
            'distance': distance,
        })
    return rows


def _flat(value):
    if not value:
        return []
    if isinstance(value[0], list):
        return value[0]
    return value
