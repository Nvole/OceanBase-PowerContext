"""Security and homepage tests using the shared temporary database fixtures."""

# =============================================================================
# Homepage Regression Tests
# =============================================================================

class TestHomepage:
    """Verify the homepage renders correctly after Codex TemplateResponse fix."""

    def test_homepage_returns_200(self, client):
        """GET / must return 200 with HTML content."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_homepage_contains_title(self, client):
        """Homepage must contain the application title."""
        resp = client.get("/")
        assert "科研资料检索助手" in resp.text

    def test_homepage_contains_search_ui(self, client):
        """Homepage must contain the search input element."""
        resp = client.get("/")
        assert 'id="searchInput"' in resp.text

    def test_homepage_contains_upload_ui(self, client):
        """Homepage must contain the upload area."""
        resp = client.get("/")
        assert 'id="dropZone"' in resp.text

    def test_homepage_shows_sqlite_mode(self, client):
        """Since SEEKDB_HOST is empty, homepage should show SQLite mode."""
        resp = client.get("/")
        assert "SQLite" in resp.text

    def test_homepage_loads_static_files(self, client):
        """Homepage references CSS and JS files that should be accessible."""
        resp_css = client.get("/static/style.css")
        assert resp_css.status_code == 200
        
        resp_js = client.get("/static/app.js")
        assert resp_js.status_code == 200


# =============================================================================
# Security Tests
# =============================================================================

class TestSecurityXSS:
    """Test that HTML/script content is safely handled and never executed."""

    def _upload_content(self, client, filename, content):
        return client.post(
            "/api/documents/upload",
            files={"file": (filename, content.encode("utf-8"), "text/markdown")},
        )

    def test_script_tag_in_content_stored_as_text(self, client):
        """Script tags in uploaded content are stored but must be escaped in display."""
        content = '# XSS Test\ntype: reading\ntags: test\n\n<script>alert("xss")</script>'
        resp = self._upload_content(client, "xss-test.md", content)
        assert resp.status_code == 200
        doc_id = resp.json()["id"]
        
        # API returns raw content (correct - it's data)
        resp2 = client.get(f"/api/documents/{doc_id}")
        assert "<script>" in resp2.json()["content"]

    def test_script_tag_in_search_results_escaped_by_frontend(self, client):
        """Search results containing script tags - frontend JS uses escapeHtml()."""
        content = '# Script Search\ntype: reading\ntags: test\n\n<script>document.cookie</script> ANCHOR_XSS_001'
        self._upload_content(client, "xss-search.md", content)
        
        resp = client.get("/api/documents/search?keyword=ANCHOR_XSS_001")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        # The matched_paragraph contains the raw text; frontend escapeHtml() handles display
        assert "<script>" in results[0]["matched_paragraph"]

    def test_img_onerror_injection(self, client):
        """Image onerror injection attempt in content."""
        content = '# Img Test\ntype: reading\ntags: test\n\n<img src=x onerror=alert(1)> INJECT_001'
        self._upload_content(client, "inject-img.md", content)
        
        resp = client.get("/api/documents/search?keyword=INJECT_001")
        assert resp.status_code == 200
        # Content stored as-is; frontend escapeHtml prevents execution
        assert '<img' in resp.json()[0]["matched_paragraph"]

    def test_event_handler_in_title(self, client):
        """Event handler injection in title field."""
        content = '# " onclick="alert(1)\ntype: reading\ntags: test\n\nBody content TITLE_INJECT_01'
        self._upload_content(client, "inject-title.md", content)
        
        resp = client.get("/api/documents/search?keyword=TITLE_INJECT_01")
        assert resp.status_code == 200

    def test_javascript_url_in_content(self, client):
        """javascript: URL in content should be stored as text, not navigable."""
        content = '# JS URL\ntype: reading\ntags: test\n\n<a href="javascript:alert(1)">click</a> JSURL_001'
        self._upload_content(client, "inject-jsurl.md", content)
        
        resp = client.get("/api/documents/search?keyword=JSURL_001")
        assert resp.status_code == 200
        assert "javascript:" in resp.json()[0]["matched_paragraph"]


class TestSecuritySQL:
    """Test SQL injection prevention."""

    def test_sql_injection_in_keyword(self, client):
        """SQL injection attempt in search keyword must return safely."""
        # Upload some data first
        content = '# SQL Safe\ntype: reading\ntags: test\n\nNormal content SQLSAFE_001'
        client.post(
            "/api/documents/upload",
            files={"file": ("sql-safe.md", content.encode("utf-8"), "text/markdown")},
        )
        
        # Attempt SQL injection
        injection = "SQLSAFE_001' OR '1'='1"
        resp = client.get(f"/api/documents/search?keyword={injection}")
        assert resp.status_code == 200
        # Should NOT return all documents - should return 0 (no literal match)
        results = resp.json()
        assert len(results) == 0

    def test_sql_drop_table_attempt(self, client):
        """DROP TABLE attempt in keyword must be safely handled."""
        resp = client.get("/api/documents/search?keyword=DROP TABLE documents")
        assert resp.status_code == 200
        # Verify table still exists by doing a normal operation
        content = '# After Drop\ntype: reading\ntags: test\n\nStill working DROPTBL_001'
        resp2 = client.post(
            "/api/documents/upload",
            files={"file": ("after-drop.md", content.encode("utf-8"), "text/markdown")},
        )
        assert resp2.status_code == 200

    def test_semicolon_injection(self, client):
        """Semicolon-based injection in keyword."""
        resp = client.get("/api/documents/search?keyword=test'; DELETE FROM documents; --")
        assert resp.status_code == 200

    def test_union_injection(self, client):
        """UNION-based injection attempt."""
        resp = client.get("/api/documents/search?keyword=' UNION SELECT * FROM documents --")
        assert resp.status_code == 200

    def test_type_filter_injection(self, client):
        """SQL injection via doc_type parameter."""
        resp = client.get("/api/documents/search?keyword=test&doc_type=reading' OR '1'='1")
        # Should return 422 (validation) or 200 with empty results
        assert resp.status_code in (200, 422)

    def test_tag_filter_injection(self, client):
        """SQL injection via tag parameter."""
        resp = client.get("/api/documents/search?keyword=test&tag='; DROP TABLE documents;--")
        assert resp.status_code == 200


class TestSecurityUpload:
    """Test upload security."""

    def test_reject_executable_extension(self, client):
        """Reject .exe, .py, .js files."""
        for name in ["hack.exe", "hack.py", "hack.js"]:
            resp = client.post(
                "/api/documents/upload",
                files={"file": (name, b"content", "application/octet-stream")},
            )
            assert resp.status_code == 400, f"Should reject {name}"

    def test_reject_html_extension(self, client):
        """Reject .html files."""
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("page.html", b"<html></html>", "text/html")},
        )
        assert resp.status_code == 400

    def test_accept_txt_extension(self, client):
        """Accept .txt files."""
        content = "# TXT Test\ntype: reading\ntags: test\n\nTXT content ACCEPT_TXT_01"
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("valid.txt", content.encode("utf-8"), "text/plain")},
        )
        assert resp.status_code == 200

    def test_reject_non_utf8(self, client):
        """Reject non-UTF-8 encoded files."""
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("binary.md", b"\xff\xfe\x00\x01\x80\x81", "text/markdown")},
        )
        assert resp.status_code == 400


# =============================================================================
# Core Functionality Tests (in isolated DB)
# =============================================================================

class TestCoreFunctionality:
    """Verify core features work in isolated environment."""

    def test_upload_and_retrieve(self, client):
        content = "# Core Test\ntype: experiment\ntags: core\n\nCORE_ANCHOR_001"
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("core.md", content.encode("utf-8"), "text/markdown")},
        )
        assert resp.status_code == 200
        doc_id = resp.json()["id"]
        
        resp2 = client.get(f"/api/documents/{doc_id}")
        assert resp2.status_code == 200
        assert resp2.json()["title"] == "Core Test"

    def test_search_returns_correct_type(self, client):
        content = "# Type Test\ntype: todo\ntags: typetest\n\nTYPE_ANCHOR_002"
        client.post(
            "/api/documents/upload",
            files={"file": ("type.md", content.encode("utf-8"), "text/markdown")},
        )
        
        resp = client.get("/api/documents/search?keyword=TYPE_ANCHOR_002")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["doc_type"] == "todo"

    def test_delete_removes_from_search(self, client):
        content = "# Delete Test\ntype: reading\ntags: del\n\nDEL_ANCHOR_003"
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("del.md", content.encode("utf-8"), "text/markdown")},
        )
        doc_id = resp.json()["id"]
        
        # Verify searchable
        resp2 = client.get("/api/documents/search?keyword=DEL_ANCHOR_003")
        assert len(resp2.json()) == 1
        
        # Delete
        resp3 = client.delete(f"/api/documents/{doc_id}")
        assert resp3.status_code == 200
        
        # Verify gone
        resp4 = client.get("/api/documents/search?keyword=DEL_ANCHOR_003")
        assert len(resp4.json()) == 0

    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
