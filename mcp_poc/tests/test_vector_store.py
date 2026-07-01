import unittest
import tempfile
import uuid
from pathlib import Path


class TestVectorStore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from vector_store import VectorStore, WIKI_COLLECTION, KNOWLEDGE_COLLECTION, SearchResult
        self.vs = VectorStore(self.tmpdir, embedding_dim=8)
        self.WIKI = WIKI_COLLECTION
        self.KNOWLEDGE = KNOWLEDGE_COLLECTION
        self.SearchResult = SearchResult

    def tearDown(self):
        self.vs.close()

    def _uid(self):
        return str(uuid.uuid4())

    def test_initial_counts_zero(self):
        self.assertEqual(self.vs.count(self.WIKI), 0)
        self.assertEqual(self.vs.count(self.KNOWLEDGE), 0)

    def test_insert_and_search(self):
        vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.vs.insert(self.WIKI, self._uid(), vec, {
            "content": "test document one",
            "source": "test",
        })
        self.assertEqual(self.vs.count(self.WIKI), 1)

        query_vec = [0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        results = self.vs.search(self.WIKI, query_vec, top_k=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "test document one")

    def test_search_all_combines_collections(self):
        v1 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        v2 = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.vs.insert(self.WIKI, self._uid(), v1, {"content": "wiki doc", "source": "wiki"})
        self.vs.insert(self.KNOWLEDGE, self._uid(), v2, {"content": "knowledge doc", "source": "kb"})

        query = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        results = self.vs.search_all(query, top_k=5)
        self.assertEqual(len(results), 2)

    def test_score_threshold(self):
        vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.vs.insert(self.WIKI, self._uid(), vec, {"content": "match", "source": "test"})
        results = self.vs.search(self.WIKI, [1.0] + [0.0] * 7, top_k=5, score_threshold=0.99)
        self.assertEqual(len(results), 1)

    def test_insert_batch(self):
        from qdrant_client.http import models as qmodels
        points = [
            qmodels.PointStruct(
                id=self._uid(), vector=[float(i)] + [0.0] * 7,
                payload={"content": f"batch {i}", "source": "test"}
            )
            for i in range(3)
        ]
        self.vs.insert_batch(self.WIKI, points)
        self.assertEqual(self.vs.count(self.WIKI), 3)

    def test_delete_collection(self):
        uid = self._uid()
        self.vs.insert(self.WIKI, uid, [1.0] + [0.0] * 7, {"content": "x", "source": "t"})
        self.vs.delete_collection(self.WIKI)
        self.assertEqual(self.vs.count(self.WIKI), 0)
