import argparse
import datetime
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import httpx
from playwright.sync_api import expect, sync_playwright
from scripts.run import configure_database


def main():
    parser = argparse.ArgumentParser(description='Browser acceptance on isolated SQLite or dedicated qoder_research.')
    parser.add_argument('--connection-file', type=Path)
    parser.add_argument('--restart-wsl-seekdb', action='store_true')
    parser.add_argument('--output', type=Path, default=project_root / 'submission' / 'release_20261028')
    arguments = parser.parse_args()
    if arguments.restart_wsl_seekdb and not arguments.connection_file:
        parser.error('A local seekdb connection file is required for the explicit WSL restart test.')
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    marker = 'QODERRELEASE' + uuid.uuid4().hex
    owned_ids = set()
    temporary = tempfile.TemporaryDirectory(prefix='qoder_browser_')
    configure_database(arguments.connection_file, sqlite=not arguments.connection_file)
    if not arguments.connection_file:
        os.environ['QODER_SQLITE_PATH'] = str(Path(temporary.name) / 'browser.db')
    from app.main import app
    from app.database import engine
    from sqlalchemy import text

    def check(name, passed):
        checks.append({'name': name, 'passed': bool(passed)})
        if not passed:
            raise AssertionError(name)

    with engine.connect() as connection:
        original_ids = set(connection.execute(text('SELECT id FROM documents')).scalars())
        version = connection.execute(text('SELECT VERSION()')).scalar() if arguments.connection_file else 'SQLite temporary database'
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    server_log = (output / 'browser_server.log').open('w', encoding='utf-8')
    server = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
        cwd=project_root, env=os.environ.copy(), stdout=server_log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    report = {'checked_at': datetime.datetime.now().astimezone().isoformat(), 'database': 'qoder_research' if arguments.connection_file else 'temporary SQLite', 'version': version, 'checks': checks, 'source': 'Codex actual Chromium browser and SQL verification'}
    client = httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=15)
    try:
        for attempt in range(60):
            if server.poll() is not None:
                raise RuntimeError('Local verification server stopped; see browser_server.log.')
            try:
                if client.get('/api/health').status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        check('server_ready', client.get('/api/health').status_code == 200)
        check('expected_database_backend', client.get('/api/health').json()['database'] == ('seekdb' if arguments.connection_file else 'sqlite'))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1080}, device_scale_factor=1)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(str(client.base_url), wait_until='networkidle')
            expect(page.locator('h1')).to_contain_text('科研资料检索助手')
            page.screenshot(path=str(output / '01_homepage.png'), full_page=True)
            uploads = []
            for sample in sorted((project_root / 'examples').glob('*.md')):
                content = sample.read_text(encoding='utf-8') + '\n\n' + marker + ' 中文验收\n'
                uploads.append({'name': sample.name, 'mimeType': 'text/markdown', 'buffer': content.encode('utf-8')})
            page.locator('#fileInput').set_input_files(uploads)
            expect(page.locator('#uploadStatus p')).to_have_count(len(uploads))
            expect(page.locator('#uploadStatus')).not_to_contain_text('上传失败')
            response = client.get('/api/documents/search', params={'keyword': marker})
            response.raise_for_status()
            uploaded = response.json()
            owned_ids.update(document['id'] for document in uploaded)
            check('browser_upload_three_types', len(uploaded) == 3 and {document['doc_type'] for document in uploaded} == {'reading', 'experiment', 'todo'})
            page.locator('#searchInput').fill(marker)
            page.locator('#searchInput').press('Enter')
            expect(page.locator('.result-item')).to_have_count(3)
            page.screenshot(path=str(output / '02_search_seekdb.png'), full_page=True)
            check('browser_search_three_results', True)
            page.locator('#typeFilter').select_option('experiment')
            page.locator('#searchInput').press('Enter')
            expect(page.locator('.result-item')).to_have_count(1)
            page.screenshot(path=str(output / '03_type_filter.png'), full_page=True)
            check('browser_type_filter', True)
            page.locator('.result-title').click()
            expect(page.locator('#detailModal')).to_be_visible()
            expect(page.locator('#detailContent')).to_contain_text(marker)
            page.screenshot(path=str(output / '04_document_detail.png'), full_page=True)
            page.evaluate('closeModal()')
            check('browser_document_detail', True)
            page.locator('#typeFilter').select_option('')
            page.locator('#tagFilter').fill('baseline')
            page.locator('#searchInput').press('Enter')
            expect(page.locator('.result-item')).to_have_count(1)
            check('browser_tag_filter', True)
            page.locator('#tagFilter').fill('')
            page.locator('#searchInput').fill('中文验收')
            page.locator('#searchInput').press('Enter')
            expect(page.locator('.result-item')).to_have_count(3)
            check('browser_chinese_search', True)
            for sequence in range(2):
                duplicate = client.post('/api/documents/upload', files={'file': ('same-release.md', f'# Duplicate\ntype: reading\n\n{marker}'.encode())})
                duplicate.raise_for_status()
                owned_ids.add(duplicate.json()['id'])
            documents = client.get('/api/documents/search', params={'keyword': marker}).json()
            check('duplicate_names_are_preserved', len({document['source_file'] for document in documents}) == 5)
            xss_payload = f'# <img src=x onerror=window.__qoder_xss=1>\ntype: reading\ntags: {marker}\n\n{marker} <script>window.__qoder_xss=1</script> <img src=x onerror=window.__qoder_xss=1> <a href=javascript:alert(1)>unsafe</a>'
            response = client.post('/api/documents/upload', files={'file': ('xss-release.md', xss_payload.encode())})
            response.raise_for_status()
            xss_document = response.json()
            owned_ids.add(xss_document['id'])
            page.locator('#searchInput').fill(marker)
            page.locator('#searchInput').press('Enter')
            expect(page.locator('.result-item')).to_have_count(6)
            check('browser_xss_search_not_executed', page.evaluate('window.__qoder_xss !== 1') and page.locator('#resultsList img, #resultsList script, #resultsList a').count() == 0)
            page.evaluate('showDetail(' + str(xss_document['id']) + ')')
            expect(page.locator('#detailModal')).to_be_visible()
            check('browser_xss_detail_not_executed', page.evaluate('window.__qoder_xss !== 1') and page.locator('#detailContent img, #detailContent script, #detailContent a').count() == 0)
            page.screenshot(path=str(output / '05_xss_rendered_as_text.png'), full_page=True)
            page.evaluate('closeModal()')
            invalid_type = f'# Bad type\ntype: <img src=x onerror=window.__qoder_xss=1>\n\n{marker}'
            response = client.post('/api/documents/upload', files={'file': ('bad-type.md', invalid_type.encode())})
            check('metadata_xss_rejected', response.status_code == 400)
            injection = client.get('/api/documents/search', params={'keyword': marker + "' OR '1'='1"})
            check('sql_injection_returns_no_unrelated_rows', injection.status_code == 200 and injection.json() == [])
            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('.result-item').filter(has_text=xss_document['title']).locator('.btn-delete').click()
            expect(page.locator('.result-item')).to_have_count(5)
            check('browser_delete_changes_search', client.get('/api/documents/' + str(xss_document['id'])).status_code == 404)
            check('browser_no_javascript_errors', not errors)
            if arguments.restart_wsl_seekdb:
                check('before_restart_rows_exist', len(client.get('/api/documents/search', params={'keyword': marker}).json()) == 5)
                engine.dispose()
                restarted = subprocess.run(['wsl.exe', '-d', 'seekdb-ubuntu', '-u', 'root', '--', 'systemctl', 'restart', 'seekdb'], capture_output=True, timeout=90)
                check('seekdb_service_restart', restarted.returncode == 0)
                for attempt in range(60):
                    try:
                        result = client.get('/api/documents/search', params={'keyword': marker})
                        if result.status_code == 200 and len(result.json()) == 5:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(1)
                check('seekdb_restart_preserves_all_test_rows', result.status_code == 200 and len(result.json()) == 5)
            page.goto((project_root / 'site' / 'index.html').as_uri(), wait_until='load')
            page.screenshot(path=str(output / '06_showcase_preview.png'), full_page=True)
            check('showcase_local_preview', True)
            browser.close()
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error_type'] = type(error).__name__
        raise
    finally:
        try:
            remaining = client.get('/api/documents/search', params={'keyword': marker}).json()
            owned_ids.update(document['id'] for document in remaining)
            for document_id in owned_ids:
                if document_id not in original_ids:
                    response = client.delete('/api/documents/' + str(document_id))
                    if response.status_code not in (200, 404):
                        raise RuntimeError('Could not remove a verification-owned document.')
            with engine.connect() as connection:
                final_ids = set(connection.execute(text('SELECT id FROM documents')).scalars())
            report['verification_rows_removed'] = not (owned_ids & final_ids)
            report['preexisting_documents_preserved'] = original_ids.issubset(final_ids)
        finally:
            client.close()
            server.terminate()
            server.wait(timeout=20)
            server_log.close()
            engine.dispose()
            temporary.cleanup()
            (output / 'browser_acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'passed_checks': len(checks), 'cleanup': report['verification_rows_removed'], 'existing_data_preserved': report['preexisting_documents_preserved']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
