"""Automated tests for the Research Document Search Assistant API."""
import sys
import os
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestHealthCheck:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] in ("sqlite", "seekdb")


class TestDocumentUpload:
    def test_upload_markdown(self, client):
        content = "# Test Note\ntype: reading\ntags: test\n\nThis is test content ABC_123."
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test-note.md", content.encode("utf-8"), "text/markdown")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test Note"
        assert data["doc_type"] == "reading"
        assert data["id"] is not None

    def test_upload_rejects_non_md(self, client):
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", b"fake pdf", "application/pdf")},
        )
        assert resp.status_code == 400

    def test_upload_duplicate_filename(self, client):
        content1 = "# Note A\ntype: reading\ntags: test\n\nContent AAA_111."
        content2 = "# Note B\ntype: reading\ntags: test\n\nContent BBB_222."
        
        resp1 = client.post(
            "/api/documents/upload",
            files={"file": ("same.md", content1.encode("utf-8"), "text/markdown")},
        )
        resp2 = client.post(
            "/api/documents/upload",
            files={"file": ("same.md", content2.encode("utf-8"), "text/markdown")},
        )
        
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["id"] != resp2.json()["id"]
        assert resp2.json()["source_file"] != "same.md"  # should have suffix


class TestSearch:
    def _import_examples(self, client):
        """Helper to import example files."""
        examples_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
        for filename in os.listdir(examples_dir):
            if filename.endswith(('.md', '.txt')):
                filepath = os.path.join(examples_dir, filename)
                with open(filepath, 'rb') as f:
                    content = f.read()
                client.post(
                    "/api/documents/upload",
                    files={"file": (filename, content, "text/markdown")},
                )

    def test_search_by_keyword(self, client):
        self._import_examples(client)
        
        resp = client.get("/api/documents/search?keyword=ANC_NOTE_731")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert "sample-reading" in results[0]["source_file"]

    def test_search_shared_anchor(self, client):
        self._import_examples(client)
        
        resp = client.get("/api/documents/search?keyword=shared_anchor")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 3

    def test_search_with_type_filter(self, client):
        self._import_examples(client)
        
        resp = client.get("/api/documents/search?keyword=shared_anchor&doc_type=experiment")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["doc_type"] == "experiment"

    def test_search_with_tag_filter(self, client):
        self._import_examples(client)
        
        resp = client.get("/api/documents/search?keyword=shared_anchor&tag=meeting")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["doc_type"] == "todo"

    def test_search_no_results(self, client):
        self._import_examples(client)
        
        resp = client.get("/api/documents/search?keyword=not_present_620")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 0

    def test_search_sql_injection_safe(self, client):
        self._import_examples(client)
        
        # SQL special characters should not cause errors
        resp = client.get("/api/documents/search?keyword=test' OR 1=1 --")
        assert resp.status_code == 200
        # Should return empty or safe results, not all data
        results = resp.json()
        assert len(results) == 0

    def test_search_exp_anchor(self, client):
        self._import_examples(client)
        
        resp = client.get("/api/documents/search?keyword=ANC_EXP_842")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert "sample-experiment" in results[0]["source_file"]

    def test_search_todo_anchor(self, client):
        self._import_examples(client)
        
        resp = client.get("/api/documents/search?keyword=ANC_TODO_953")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert "sample-todo" in results[0]["source_file"]


class TestDelete:
    def _import_one(self, client):
        content = "# Del Test\ntype: reading\ntags: test\n\nContent DEL_999."
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("del-test.md", content.encode("utf-8"), "text/markdown")},
        )
        return resp.json()["id"]

    def test_delete_document(self, client):
        doc_id = self._import_one(client)
        
        # Verify exists
        resp = client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        
        # Delete
        resp = client.delete(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        
        # Verify gone
        resp = client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 404

    def test_delete_affects_search(self, client):
        """After deleting experiment, searching its anchor returns nothing."""
        content = "# Exp\ntype: experiment\ntags: baseline\n\nANC_EXP_DEL_123"
        client.post(
            "/api/documents/upload",
            files={"file": ("exp-del.md", content.encode("utf-8"), "text/markdown")},
        )
        
        resp = client.get("/api/documents/search?keyword=ANC_EXP_DEL_123")
        assert len(resp.json()) == 1
        
        doc_id = resp.json()[0]["id"]
        client.delete(f"/api/documents/{doc_id}")
        
        resp = client.get("/api/documents/search?keyword=ANC_EXP_DEL_123")
        assert len(resp.json()) == 0


class TestHTMLSafety:
    def test_script_tags_displayed_as_text(self, client):
        """HTML script tags in content should be escaped, not executed."""
        content = '# Safe Test\ntype: reading\ntags: test\n\n<script>alert("xss")</script>'
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("safe.md", content.encode("utf-8"), "text/markdown")},
        )
        assert resp.status_code == 200
        doc_id = resp.json()["id"]
        
        resp = client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        # Content should contain the raw script tag as text
        assert '<script>' in resp.json()["content"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
