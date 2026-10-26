"""Fixed-vector checks for seekdb hybrid_search.

Vectors are hand-built fixtures. This file does not load an embedding model
and does not invent WebGPU or WASM timings.
"""
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pymysql

TRACK = Path(__file__).resolve().parents[1]
SRC = TRACK / 'src'
sys.path.insert(0, str(SRC))
import kb  # noqa: E402

RESULTS = TRACK / 'results'
DATA = TRACK / 'data'
FIXTURES = [
    ('fixture-seekdb', 'seekdbhybrid', 0, 'alpha', 'seekdb 在库内完成混合检索。标记 seekdbhybrid。'),
    ('fixture-minilm', 'minilm384', 16, 'alpha', '公开模型输出 384 维向量。标记 minilm384。'),
    ('fixture-webgpu', 'webgpufirst', 32, 'beta', '优先使用 WebGPU，并在页面显示后端。标记 webgpufirst。'),
    ('fixture-int8', 'int8quant', 48, 'beta', 'INT8 量化对应 q8 模型文件。标记 int8quant。'),
    ('fixture-wasm', 'wasmfallback', 64, 'beta', '没有 WebGPU 时降级到 WASM。标记 wasmfallback。'),
    ('fixture-refresh', 'refreshindex', 80, 'alpha', '写入后要做索引刷新。标记 refreshindex。也包含词 刷新索引。'),
]


def basis(index):
    vector = [0.0] * kb.DIMENSION
    vector[index] = 1.0
    return vector


def blend(left_index, right_index, left_weight=0.85):
    mixed = [left_weight if position == left_index else (1 - left_weight if position == right_index else 0.0)
             for position in range(kb.DIMENSION)]
    norm = sum(value * value for value in mixed) ** 0.5
    return [value / norm for value in mixed]


def median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def ids_of(rows):
    return [row['id'] for row in rows]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def source_audit():
    kb_source = (SRC / 'kb.py').read_text(encoding='utf-8')
    server_source = (SRC / 'server.py').read_text(encoding='utf-8')
    worker = (SRC / 'static' / 'embed_worker.js').read_text(encoding='utf-8')
    page = (SRC / 'static' / 'index.html').read_text(encoding='utf-8')
    app = (SRC / 'static' / 'app.js').read_text(encoding='utf-8')
    for forbidden in ('DefaultEmbeddingFunction', 'sentence_transformers', 'openai', 'onnxruntime', 'query_texts'):
        require(forbidden not in kb_source, f'kb.py contains {forbidden}')
    for forbidden in ('DefaultEmbeddingFunction', 'sentence_transformers', 'openai', 'onnxruntime'):
        require(forbidden not in server_source, f'server.py contains {forbidden}')
    require(server_source.count('query_texts') == 2, 'server.py should only mention query_texts when rejecting it')
    require('embedding_function=None' in kb_source, 'collection embedding function is not explicitly disabled')
    require("rank={'rrf': {}}" in kb_source, 'hybrid search does not use rank.rrf')
    require("'$contains'" in kb_source and 'query_embeddings' in kb_source, 'hybrid search arguments are incomplete')
    require('refresh_index' in kb_source, 'refresh_index is missing')
    for needle in ('Xenova/all-MiniLM-L6-v2', "dtype: DTYPE", "const DTYPE = 'q8'", 'webgpu', 'wasm'):
        require(needle in worker, f'worker is missing {needle}')
    require('当前推理后端' in page and 'WebGPU' in page and 'WASM' in page, 'page does not name the backend')
    require('server_computes_embeddings' in app or '服务端未重新计算向量' in app, 'page does not state where embedding happens')
    joined = kb_source + server_source + worker + app
    for remote_api in ('api.openai.com', 'dashscope', 'generativelanguage.googleapis.com'):
        require(remote_api not in joined, f'found remote inference host {remote_api}')


def model_sizes():
    url = 'https://huggingface.co/api/models/Xenova/all-MiniLM-L6-v2/tree/main/onnx'
    recorded = json.loads((DATA / 'published_onnx_sizes.json').read_text(encoding='utf-8'))
    fetched = False
    error = None
    files = {name: item['bytes'] for name, item in recorded['files'].items()}
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode('utf-8'))
        files = {item['path']: (item.get('lfs') or {}).get('size') or item.get('size') for item in payload}
        fetched = True
    except Exception as exc:
        error = type(exc).__name__
    fp32 = files['onnx/model.onnx']
    int8 = files['onnx/model_quantized.onnx']
    report = {
        'source_url': url,
        'fetched_during_test': fetched,
        'fetch_error': error,
        'weights_downloaded': False,
        'onnx_bytes': files,
        'fp32_bytes': fp32,
        'int8_q8_bytes': int8,
        'compression_ratio_fp32_over_int8': fp32 / int8,
        'same_bytes_as_model_int8': files.get('onnx/model_int8.onnx') == int8,
        'scope': 'ONNX weight files only. Tokenizer and config are shared and are not quantized.',
        'quality_change': 'Not measured. The headless host did not run FP32 or INT8 browser inference.',
    }
    (RESULTS / 'model_artifact_sizes.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return report


def database_version():
    settings = kb.load_settings()
    require(settings['host'] == '127.0.0.1', 'seekdb host is not loopback')
    require(settings['database'] == 'track02_stepfun', 'unexpected seekdb database')
    with pymysql.connect(host=settings['host'], port=settings['port'], user=settings['user'], password=settings['password'],
                         database=settings['database'], charset='utf8mb4', autocommit=True, connect_timeout=5,
                         read_timeout=30, write_timeout=30) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT VERSION(), DATABASE()')
            version, database = cursor.fetchone()
    return {'version': version, 'database': database}


def write_fixture_file():
    payload = {
        'note': 'Deterministic 384-d unit vectors for tests and the page probe. They are not MiniLM embeddings.',
        'dimension': kb.DIMENSION,
        'documents': [{
            'id': doc_id,
            'keyword': keyword,
            'basis_index': index,
            'role': role,
            'document': text,
            'embedding': basis(index),
        } for doc_id, keyword, index, role, text in FIXTURES],
    }
    (DATA / 'fixed_vectors.json').write_text(json.dumps(payload, ensure_ascii=False) + '\n', encoding='utf-8')


def search(collection, keyword, embedding, n_results=5, where=None):
    rows, elapsed = kb.hybrid_search(collection, keyword, embedding, n_results=n_results, where=where)
    return rows, elapsed


def run_database_cases():
    started = time.perf_counter()
    with kb.connect() as client:
        collection = kb.reset_collection(client)
        require(getattr(collection, '_embedding_function', None) is None, 'embedding function was installed')
        ids, documents, embeddings, metadatas = [], [], [], []
        for doc_id, keyword, index, role, text in FIXTURES:
            ids.append(doc_id)
            documents.append(text)
            embeddings.append(basis(index))
            metadatas.append({'source': 'fixed-vector', 'keyword': keyword, 'role': role})
        write_started = time.perf_counter()
        kb.upsert_documents(collection, ids, documents, embeddings, metadatas)
        upsert_ms = (time.perf_counter() - write_started) * 1000
        refresh_ms = kb.refresh(collection)
        warm_refresh_ms = kb.refresh(collection)
        require(collection.count() == len(FIXTURES), 'fixture count mismatch')

        both, both_ms = search(collection, 'webgpufirst', basis(32))
        require(ids_of(both)[0] == 'fixture-webgpu', f'aligned hybrid top id was {ids_of(both)}')

        fused, _fused_ms = search(collection, 'wasmfallback', blend(64, 48))
        require(ids_of(fused)[0] == 'fixture-wasm', f'fused hybrid top id was {ids_of(fused)}')

        split, _split_ms = search(collection, 'wasmfallback', basis(48), n_results=5)
        split_ids = ids_of(split)
        require('fixture-wasm' in split_ids and 'fixture-int8' in split_ids, f'split hybrid ids were {split_ids}')

        filtered, _filtered_ms = search(collection, 'webgpufirst', basis(32), where={'role': {'$eq': 'beta'}})
        require(ids_of(filtered)[0] == 'fixture-webgpu', f'filtered top id was {ids_of(filtered)}')
        require(all(row['metadata'].get('role') == 'beta' for row in filtered), 'metadata filter leaked another role')

        new_id = 'fixture-new'
        before_rows, _before_ms = search(collection, 'newdocmarker', basis(96))
        visible_before_write = new_id in ids_of(before_rows)
        kb.upsert_documents(
            collection, [new_id], ['增量文档在刷新后才应稳定可检。标记 newdocmarker。'], [basis(96)],
            [{'source': 'fixed-vector', 'keyword': 'newdocmarker', 'role': 'gamma'}])
        before_refresh_rows, _ = search(collection, 'newdocmarker', basis(96))
        visible_before_refresh = new_id in ids_of(before_refresh_rows)
        incremental_refresh_ms = kb.refresh(collection)
        after_rows, after_ms = search(collection, 'newdocmarker', basis(96))
        require(ids_of(after_rows)[0] == new_id, f'new document was not first after refresh: {ids_of(after_rows)}')

        count_before = collection.count()
        kb.upsert_documents(collection, ['fixture-webgpu'], [FIXTURES[2][4]], [basis(32)],
                            [{'source': 'fixed-vector', 'keyword': 'webgpufirst', 'role': 'beta'}])
        kb.refresh(collection)
        require(collection.count() == count_before, 'upsert duplicated an existing id')

        samples = []
        for _ in range(7):
            _rows, elapsed = search(collection, 'webgpufirst', basis(32))
            samples.append(elapsed)
        chinese_rows, chinese_ms = search(collection, '刷新索引', basis(80))
        final_count = collection.count()
    return {
        'upsert_ms': upsert_ms,
        'refresh_index_ms': refresh_ms,
        'refresh_index_warm_ms': warm_refresh_ms,
        'incremental_refresh_ms': incremental_refresh_ms,
        'hybrid_search_ms_raw': samples,
        'hybrid_search_ms_median': median(samples),
        'cases': {
            'aligned_keyword_and_vector': {'top': ids_of(both)[0], 'ids': ids_of(both), 'ms': both_ms, 'passed': True},
            'fused_keyword_and_nearby_vector': {'top': ids_of(fused)[0], 'ids': ids_of(fused), 'passed': True},
            'keyword_and_vector_disagree': {'ids': split_ids, 'passed': True},
            'metadata_filter': {'ids': ids_of(filtered), 'passed': True},
            'incremental_refresh': {
                'visible_before_write': visible_before_write,
                'visible_before_refresh': visible_before_refresh,
                'top_after_refresh': ids_of(after_rows)[0],
                'ms': after_ms,
                'passed': True,
            },
            'chinese_contains_recorded_not_required': {
                'query': '刷新索引',
                'ids': ids_of(chinese_rows),
                'top_is_refresh_doc': ids_of(chinese_rows)[:1] == ['fixture-refresh'],
                'ms': chinese_ms,
            },
        },
        'count': final_count,
        'database_case_ms': (time.perf_counter() - started) * 1000,
    }


def port_is_open(port):
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(('127.0.0.1', port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def http_json(method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        f'http://127.0.0.1:18602{path}', data=data, method=method,
        headers={'Content-Type': 'application/json'} if data is not None else {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode('utf-8'))


def start_server():
    if port_is_open(18602):
        raise RuntimeError('127.0.0.1:18602 is already in use')
    command = ('cd /data/zouyuanwei/oceanbase && . ./env.sh && '
               'uv run --locked python tracks/02_stepfun_browser_kb/src/server.py')
    process = subprocess.Popen(['bash', '-lc', command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    logs = []

    def drain():
        for line in process.stdout:
            logs.append(line.rstrip())

    threading.Thread(target=drain, daemon=True).start()
    deadline = time.time() + 40
    while time.time() < deadline:
        if any('listening 127.0.0.1:18602' in line for line in logs):
            return process, logs
        if process.poll() is not None:
            break
        time.sleep(0.1)
    process.kill()
    raise RuntimeError('server did not listen: ' + '\n'.join(logs[-40:]))


def stop_server(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run_http_cases():
    process, logs = start_server()
    try:
        status, state = http_json('GET', '/api/state')
        require(status == 200, f'state failed: {state}')
        require(state['collection'] == kb.COLLECTION_NAME, 'wrong collection name')
        require(state['embedding_function'] is None, 'state exposes an embedding function')
        require(state['server_computes_embeddings'] is False, 'server claims to compute embeddings')
        require(state['bind'] == '127.0.0.1:18602', 'server bind is not loopback 18602')
        with urllib.request.urlopen('http://127.0.0.1:18602/', timeout=10) as response:
            html = response.read().decode('utf-8')
        require('当前推理后端' in html and 'WebGPU' in html and 'WASM' in html, 'homepage does not show backends')
        status, missing = http_json('POST', '/api/search', {'query': 'webgpufirst'})
        require(status == 400, 'search without embedding was accepted')
        status, rejected = http_json('POST', '/api/search', {'query': 'webgpufirst', 'embedding': basis(32), 'query_texts': ['webgpufirst']})
        require(status == 400, 'query_texts was accepted')
        status, bad_item = http_json('POST', '/api/upsert', {'items': [{'id': 'x', 'document': 'x'}]})
        require(status == 400, 'upsert without embedding was accepted')
        status, found = http_json('POST', '/api/search', {'query': 'webgpufirst', 'embedding': basis(32), 'n_results': 3})
        require(status == 200 and found['rows'][0]['id'] == 'fixture-webgpu', f'http hybrid failed: {found}')
        require(found['server_computes_embeddings'] is False, 'search response claims server embeddings')
        status, corpus = http_json('GET', '/api/corpus')
        require(status == 200 and corpus['documents'] and 'embedding' not in corpus['documents'][0], 'corpus leaked vectors')
        listeners = subprocess.check_output(['ss', '-ltn'], text=True)
        require('127.0.0.1:18602' in listeners, 'ss did not show the loopback listener')
        require('0.0.0.0:18602' not in listeners and '[::]:18602' not in listeners, 'service is not loopback-only')
        return {
            'passed': True,
            'http_top_id': found['rows'][0]['id'],
            'http_search_ms': found['search_ms'],
            'listener': '127.0.0.1:18602',
            'startup_log_tail': logs[-8:],
        }
    finally:
        stop_server(process)


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    source_audit()
    sizes = model_sizes()
    version = database_version()
    write_fixture_file()
    database_cases = run_database_cases()
    http_cases = run_http_cases()
    report = {
        'collection': kb.COLLECTION_NAME,
        'dimension': kb.DIMENSION,
        'distance': kb.DISTANCE,
        'embedding_function': None,
        'server_computes_embeddings': False,
        'hybrid_search': {
            'query': 'where_document.$contains',
            'knn': 'query_embeddings',
            'rank': 'rrf',
            'refresh_after_write': True,
        },
        'seekdb': version,
        'latency_ms': {
            'upsert_batch': database_cases['upsert_ms'],
            'refresh_index': database_cases['refresh_index_ms'],
            'refresh_index_warm': database_cases['refresh_index_warm_ms'],
            'incremental_refresh': database_cases['incremental_refresh_ms'],
            'hybrid_search_raw': database_cases['hybrid_search_ms_raw'],
            'hybrid_search_median': database_cases['hybrid_search_ms_median'],
        },
        'cases': database_cases['cases'],
        'record_count': database_cases['count'],
        'http': http_cases,
        'model_compression_ratio_fp32_over_int8': sizes['compression_ratio_fp32_over_int8'],
        'webgpu_ms': None,
        'wasm_ms': None,
        'browser_timing_note': 'This host is headless. WebGPU and WASM milliseconds were not measured and are not fabricated.',
        'retrieval_quality_note': 'Fixed vectors verify database ranking only. INT8 versus FP32 semantic quality was not run here.',
    }
    (RESULTS / 'fixed_vector_test.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({
        'passed': True,
        'hybrid_search_ms_median': report['latency_ms']['hybrid_search_median'],
        'compression_ratio': report['model_compression_ratio_fp32_over_int8'],
        'top_after_refresh': report['cases']['incremental_refresh']['top_after_refresh'],
        'visible_before_refresh': report['cases']['incremental_refresh']['visible_before_refresh'],
        'chinese_top_matches': report['cases']['chinese_contains_recorded_not_required']['top_is_refresh_doc'],
        'webgpu_ms': None,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
