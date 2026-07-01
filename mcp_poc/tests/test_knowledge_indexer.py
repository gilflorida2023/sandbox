import unittest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestChunkMarkdown(unittest.TestCase):
    def test_chunk_by_headings(self):
        from knowledge_indexer import chunk_markdown
        text = (
            "# Heading 1\n\n"
            "Some content here with enough text to exceed the minimum length threshold easily.\n\n"
            "## Subheading\n\n"
            "More content under the subheading that also exceeds the minimum length easily."
        )
        chunks = chunk_markdown(text, "test.md")
        self.assertGreaterEqual(len(chunks), 2)

    def test_single_chunk_no_headings(self):
        from knowledge_indexer import chunk_markdown
        text = "Just a single paragraph of text without any markdown headings."
        chunks = chunk_markdown(text, "test.md")
        self.assertEqual(len(chunks), 1)

    def test_min_length_filter(self):
        from knowledge_indexer import chunk_markdown
        text = "short"
        chunks = chunk_markdown(text, "test.md", min_len=10)
        self.assertEqual(len(chunks), 0)


class TestKnowledgeIndexer(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from vector_store import VectorStore
        from embedding_service import EmbeddingService
        from knowledge_indexer import KnowledgeIndexer
        from tool_wiki import ToolWiki

        self.vs = VectorStore(self.tmpdir, embedding_dim=8)
        self.es = MagicMock()
        self.es.dimension = 8
        self.es.embed.return_value = [0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.es.embed_query.return_value = [0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.wiki = MagicMock()
        self.wiki.wiki_path = Path("/nonexistent")

        self.ki = KnowledgeIndexer(self.es, self.vs, self.wiki)

    def tearDown(self):
        self.vs.close()

    def test_index_wiki_handles_missing_dirs(self):
        self.ki.index_wiki(self.wiki)
        self.assertEqual(self.ki.wiki_count, 0)

    def test_add_knowledge_chunk(self):
        doc_id = self.ki.add_knowledge_chunk("test knowledge", "test", ["tag1"])
        self.assertTrue(doc_id)
        self.assertEqual(self.ki.knowledge_count, 1)

    def test_search_returns_results(self):
        self.ki.add_knowledge_chunk("test knowledge content", "test")
        self.es.embed_query.return_value = [0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        from vector_store import SearchResult
        self.vs.search_all = MagicMock(return_value=[
            SearchResult(content="test knowledge content", source="test", score=0.9)
        ])
        results = self.ki.search("test query")
        self.assertEqual(len(results), 1)

    def test_format_results(self):
        from vector_store import SearchResult
        results = [
            SearchResult(content="doc one content", source="src1", score=0.95),
            SearchResult(content="doc two content", source="src2", score=0.85),
        ]
        formatted = self.ki.format_results(results, max_chars=500)
        self.assertIn("Relevant Knowledge", formatted)
        self.assertIn("doc one content", formatted)
        self.assertIn("doc two content", formatted)

    def test_format_results_empty(self):
        self.assertEqual(self.ki.format_results([]), "")

    def test_search_wiki_delegates(self):
        from vector_store import SearchResult
        self.vs.search = MagicMock(return_value=[
            SearchResult(content="wiki doc", source="wiki/tools/test.md", score=0.9)
        ])
        self.es.embed_query.return_value = [0.5] * 8
        results = self.ki.search_wiki("test query")
        self.assertEqual(len(results), 1)
