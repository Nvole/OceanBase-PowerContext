"""Context assembly does not keep a fixed answer or fixed material names."""

import sys
import unittest
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK / "src"))

from sdd_context.assemble import assemble, extract_terms


class ContextAssemblyTests(unittest.TestCase):
    def test_terms_keep_full_tokens(self):
        terms = extract_terms("invoice-date-range filter_invoices SPEC_SENTENCE 日期范围")
        self.assertEqual(terms, ["invoice-date-range", "filter_invoices", "SPEC_SENTENCE", "日期范围"])

    def test_sources_come_from_hit_metadata(self):
        hits = [{
            "id": "docs/from-db.md",
            "document": "DB_SENTENCE: from the database",
            "metadata": {"source": "docs/from-db.md", "kind": "spec", "symbol": "规则"},
        }]
        payload = assemble("DB_SENTENCE", ["DB_SENTENCE"], hits, {"status": "empty"}, [])
        self.assertEqual(payload["spec_items"][0]["source"], "docs/from-db.md")
        self.assertEqual(payload["spec_items"][0]["document_id"], "docs/from-db.md")
        self.assertIn("from the database", payload["spec_items"][0]["text"])

    def test_changed_hit_text_replaces_the_sentence(self):
        hit = {
            "id": "docs/from-db.md",
            "document": "DB_SENTENCE: old sentence",
            "metadata": {"source": "docs/from-db.md", "kind": "spec", "symbol": ""},
        }
        first = assemble("DB_SENTENCE", ["DB_SENTENCE"], [hit], {}, [])
        hit["document"] = "DB_SENTENCE: new sentence"
        second = assemble("DB_SENTENCE", ["DB_SENTENCE"], [hit], {}, [])
        self.assertIn("old sentence", first["spec_items"][0]["text"])
        self.assertIn("new sentence", second["spec_items"][0]["text"])
        self.assertNotIn("old sentence", second["spec_items"][0]["text"])

    def test_retrieval_modules_do_not_name_materials(self):
        for relative in ("src/sdd_context/assemble.py", "src/sdd_context/cli.py", "src/sdd_context/store.py"):
            text = (TRACK / relative).read_text(encoding="utf-8")
            for name in ("invoice_filter_spec.md", "invoice_filter.py", "test_invoice_filter.py"):
                self.assertNotIn(name, text, relative)


if __name__ == "__main__":
    unittest.main()
