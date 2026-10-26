"""Loopback-only lab-note service. Bind is fixed at 127.0.0.1:18605."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import labnotes

BIND_HOST = '127.0.0.1'
BIND_PORT = 18605

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>组会材料检索</title>
<style>
body { font-family: sans-serif; margin: 2rem auto; max-width: 52rem; line-height: 1.5; color: #1c1c1c; }
code { background: #f3f3f3; padding: 0 .2rem; }
section { margin: 1.5rem 0; }
label { display: block; margin-top: .6rem; }
input, textarea { width: 100%; box-sizing: border-box; }
button { margin-top: .8rem; }
.banner { background: #fff6d8; border: 1px solid #e0c36a; padding: .8rem 1rem; }
.result { border-top: 1px solid #ddd; padding: .8rem 0; white-space: pre-wrap; }
</style>
</head>
<body>
<h1>组会材料检索</h1>
<p>组会前材料散在笔记和聊天记录里。把中文材料放进 seekdb 集合 <code>track05_labnotes</code>，用全文关键词、向量近邻和 RRF 一起找回来。</p>
<section class="banner">
<strong>Qoder Sites：blocked。</strong>
当前环境没有可用的 Qoder 个人账号，不能发布「任何人都可访问」的站点。本页只监听 127.0.0.1:18605，不是 Qoder Sites，也没有虚构网址或截图。
</section>
<section>
<h2>检索</h2>
<label>关键词（where_document.$contains）<input id="keyword" value="青屿纪要"></label>
<label>语义查询（本地哈希向量的 knn，不下载模型）<textarea id="query" rows="3">组会里怎样把全文和向量结果融合</textarea></label>
<button id="search" type="button">混合检索</button>
</section>
<section>
<h2>导入一条新材料</h2>
<label>标题<input id="title" value="临时核对材料"></label>
<label>主题<input id="topic" value="核对"></label>
<label>场合<input id="meeting" value="2026-10-26 临时核对"></label>
<label>正文<textarea id="body" rows="4">这是新导入的组会材料，用来确认独特代号在刷新索引后能被混合检索找到。</textarea></label>
<button id="import" type="button">导入并检索代号</button>
</section>
<section>
<h2>结果</h2>
<div id="out">还没有检索。</div>
</section>
<script>
function show(data) {
  const out = document.getElementById('out');
  const hits = data.hits || [];
  if (data.code && data.refresh_index) {
    out.textContent = '已导入代号 ' + data.code + '，索引已刷新。正在用该代号检索…';
    return;
  }
  if (!hits.length) {
    out.textContent = '没有含该关键词的材料。\\n' + JSON.stringify({keyword: data.keyword, hybrid_ids: data.hybrid_ids}, null, 2);
    return;
  }
  out.innerHTML = '';
  hits.forEach(function(hit) {
    const block = document.createElement('div');
    block.className = 'result';
    block.textContent = hit.code + '  ' + hit.title + '\\n' + hit.document;
    out.appendChild(block);
  });
}
async function post(path, payload) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'request failed');
  return data;
}
document.getElementById('search').onclick = async function() {
  try { show(await post('/api/search', {keyword: document.getElementById('keyword').value, query: document.getElementById('query').value})); }
  catch (error) { document.getElementById('out').textContent = error.message; }
};
document.getElementById('import').onclick = async function() {
  try {
    const imported = await post('/api/import', {
      title: document.getElementById('title').value,
      topic: document.getElementById('topic').value,
      meeting: document.getElementById('meeting').value,
      body: document.getElementById('body').value
    });
    show(imported);
    show(await post('/api/search', {keyword: imported.code, query: imported.code}));
  } catch (error) {
    document.getElementById('out').textContent = error.message;
  }
};
</script>
</body>
</html>
"""


def assert_loopback(host, port):
    if host != BIND_HOST or port != BIND_PORT:
        raise RuntimeError('refusing bind other than 127.0.0.1:18605')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            body = PAGE.encode('utf-8')
            self.respond(200, 'text/html; charset=utf-8', body)
            return
        if path == '/api/health':
            self.respond_json(health_payload())
            return
        if path == '/favicon.ico':
            self.respond(404, 'text/plain; charset=utf-8', b'not found')
            return
        self.respond_json({'error': 'not found'}, status=404)

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        try:
            payload = self.read_json()
            if path == '/api/search':
                result = labnotes.search_notes(payload.get('keyword', ''), payload.get('query'), payload.get('n_results', 5))
            elif path == '/api/import':
                result = labnotes.import_note(
                    payload.get('title', ''),
                    payload.get('body', ''),
                    payload.get('topic', ''),
                    payload.get('meeting', ''),
                )
            elif path == '/api/seed':
                result = labnotes.seed()
            else:
                self.respond_json({'error': 'not found'}, status=404)
                return
        except ValueError as exc:
            self.respond_json({'error': str(exc)}, status=400)
            return
        except Exception:
            self.respond_json({'error': 'seekdb request failed'}, status=500)
            return
        self.respond_json(result)

    def read_json(self):
        length = int(self.headers.get('Content-Length', '0') or '0')
        if length < 0 or length > 65536:
            raise ValueError('body is too large')
        raw = self.rfile.read(length) if length else b'{}'
        data = json.loads(raw.decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError('json object required')
        return data

    def respond_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.respond(status, 'application/json; charset=utf-8', body)

    def respond(self, status, content_type, body):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def health_payload():
    info = labnotes.stats()
    return {
        'service': 'track05-labnotes',
        'bind': f'{BIND_HOST}:{BIND_PORT}',
        'collection': info['collection'],
        'count': info['count'],
        'qoder_sites': 'blocked',
        'embedding': 'local-char-ngram-64',
    }


class LabnotesServer(ThreadingHTTPServer):
    allow_reuse_address = True


def make_server():
    assert_loopback(BIND_HOST, BIND_PORT)
    return LabnotesServer((BIND_HOST, BIND_PORT), Handler)


def main():
    labnotes.seed()
    server = make_server()
    print(f'listening on http://{BIND_HOST}:{BIND_PORT}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
