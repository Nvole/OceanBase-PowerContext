"""Verify Chinese seed notes, hybrid search, and the loopback service."""
import json
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import labnotes  # noqa: E402
import server  # noqa: E402


def fail(message):
    raise AssertionError(message)


def check_seed():
    notes = labnotes.load_seed_notes()
    if len(notes) < 10:
        fail('expected at least 10 seed notes')
    if sum('青屿纪要' in note['title'] + note['body'] for note in notes) != 1:
        fail('青屿纪要 must appear in exactly one seed note')
    for note in notes:
        if not labnotes.has_cjk(note['body']):
            fail('seed note is not Chinese')
    seeded = labnotes.seed()
    info = labnotes.stats()
    if info['count'] < len(notes):
        fail('collection does not contain the seed notes')
    found = labnotes.search_notes('青屿纪要', '组会里怎样把全文和向量结果融合', 5)
    codes = [hit['code'] for hit in found['hits']]
    if 'LNSEED02' not in codes:
        fail('Chinese keyword was not retrieved by hybrid search')
    if 'ln-seed-02' not in found['hybrid_ids']:
        fail('Chinese note missing from hybrid ids')
    try:
        labnotes.search_notes('   ', '组会')
    except ValueError:
        pass
    else:
        fail('blank keyword was accepted')
    return {
        'seeded': seeded['seeded'],
        'count': info['count'],
        'refresh_index': seeded['refresh_index'],
        'chinese_keyword': '青屿纪要',
        'chinese_hybrid_ids': found['hybrid_ids'],
        'chinese_codes': codes,
    }


def check_import():
    try:
        labnotes.import_note('Only English', 'This note has no Chinese characters.', 'test')
    except ValueError:
        pass
    else:
        fail('non-Chinese import was accepted')
    imported = labnotes.import_note(
        '临时核对材料',
        '这是新导入的组会材料，用来确认独特代号在刷新索引后能被混合检索找到。',
        '核对',
        '2026-10-26 临时核对',
    )
    if not imported['refresh_index']:
        fail('import did not refresh the index')
    if imported['code'] in {note['code'] for note in labnotes.load_seed_notes()}:
        fail('imported code collided with a seed code')
    found = labnotes.search_notes(imported['code'], imported['code'], 5)
    hit_ids = [hit['id'] for hit in found['hits']]
    if imported['id'] not in found['hybrid_ids'] or imported['id'] not in hit_ids:
        fail('imported unique code was not retrieved')
    if not any(imported['code'] in hit['document'] for hit in found['hits']):
        fail('retrieved document does not contain the unique code')
    return {
        'id': imported['id'],
        'code': imported['code'],
        'refresh_index': True,
        'hybrid_ids': found['hybrid_ids'],
        'found': True,
    }


def request_json(method, path, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        f'http://{server.BIND_HOST}:{server.BIND_PORT}{path}',
        data=data,
        headers={} if data is None else {'Content-Type': 'application/json; charset=utf-8'},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        body = response.read().decode('utf-8')
        return response.status, json.loads(body), body


def check_server():
    try:
        server.assert_loopback('0.0.0.0', 18605)
    except RuntimeError:
        pass
    else:
        fail('non-loopback bind was accepted')
    if server.BIND_HOST != '127.0.0.1' or server.BIND_PORT != 18605:
        fail('service bind changed')
    httpd = server.make_server()
    actual_host, actual_port = httpd.server_address[:2]
    if actual_host != '127.0.0.1' or actual_port != 18605:
        httpd.server_close()
        fail('server socket is not 127.0.0.1:18605')
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, health, raw_health = request_json('GET', '/api/health')
        if status != 200 or health.get('bind') != '127.0.0.1:18605' or health.get('qoder_sites') != 'blocked':
            fail('health check did not report the loopback bind and blocked sites')
        if health.get('count', 0) < 10:
            fail('service does not see the seeded notes')
        _, found, raw_search = request_json('POST', '/api/search', {'keyword': '青屿纪要', 'query': '混合检索'})
        if 'LNSEED02' not in [hit['code'] for hit in found.get('hits', [])]:
            fail('HTTP search missed the Chinese note')
        _, imported, raw_import = request_json('POST', '/api/import', {
            'title': '接口导入核对',
            'topic': '核对',
            'meeting': '2026-10-26 接口核对',
            'body': '通过本机接口导入的组会材料，应能按新代号检索到。',
        })
        _, located, raw_located = request_json('POST', '/api/search', {
            'keyword': imported['code'],
            'query': imported['code'],
        })
        if imported['id'] not in [hit['id'] for hit in located.get('hits', [])]:
            fail('HTTP import code was not searchable')
        secret = labnotes.load_settings()['password']
        combined = '\n'.join([raw_health, raw_search, raw_import, raw_located])
        if secret and secret in combined:
            fail('HTTP response contains the database password')
        return {
            'bind': health['bind'],
            'qoder_sites': health['qoder_sites'],
            'count': health['count'],
            'http_import_code': imported['code'],
            'http_import_found': True,
        }
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def main():
    report = {
        'collection': labnotes.COLLECTION,
        'mode': 'where_document.$contains + knn + rrf',
        'embedding': 'local-char-ngram-64',
        'model_download': False,
        'qoder_sites': 'blocked',
        'seed': check_seed(),
        'import': check_import(),
        'server': check_server(),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    secret = labnotes.load_settings()['password']
    if secret and secret in text:
        fail('report contains the database password')
    for folder in (ROOT / 'results', ROOT / 'docs'):
        folder.mkdir(parents=True, exist_ok=True)
    (ROOT / 'results' / 'hybrid_search.json').write_text(text + '\n', encoding='utf-8')
    (ROOT / 'docs' / 'last_run.json').write_text(text + '\n', encoding='utf-8')
    print(json.dumps({
        'status': 'PASS',
        'seeded': report['seed']['seeded'],
        'import_code': report['import']['code'],
        'import_found': report['import']['found'],
        'bind': report['server']['bind'],
        'qoder_sites': report['qoder_sites'],
    }, ensure_ascii=True))


if __name__ == '__main__':
    main()
