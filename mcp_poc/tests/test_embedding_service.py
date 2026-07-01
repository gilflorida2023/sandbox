import unittest
from unittest.mock import patch, MagicMock
import json


class TestEmbeddingService(unittest.TestCase):
    def setUp(self):
        self.mock_get_patcher = patch("httpx.Client.post")
        self.mock_post = self.mock_get_patcher.start()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "model": "nomic-embed-text",
            "embeddings": [[0.1, 0.2, 0.3]],
        }
        mock_response.raise_for_status.return_value = None
        self.mock_post.return_value = mock_response

        from embedding_service import EmbeddingService
        self.svc = EmbeddingService(host="localhost", port=11434)

    def tearDown(self):
        self.svc.close()
        self.mock_get_patcher.stop()

    def test_embed_returns_vector(self):
        vec = self.svc.embed("hello")
        self.assertEqual(len(vec), 3)
        self.assertAlmostEqual(vec[0], 0.1)

    def test_embed_batch(self):
        vecs = self.svc.embed_batch(["hello", "world"])
        self.assertEqual(len(vecs), 2)

    def test_embed_caches_duplicates(self):
        v1 = self.svc.embed("test string")
        v2 = self.svc.embed("test string")
        self.assertEqual(v1, v2)
        self.assertEqual(self.mock_post.call_count, 1)

    def test_embed_query(self):
        vec = self.svc.embed_query("test query")
        self.assertEqual(len(vec), 3)

    def test_dimension_detected(self):
        self.svc.embed("probe")
        self.assertEqual(self.svc.dimension, 3)

    def test_empty_batch(self):
        self.assertEqual(self.svc.embed_batch([]), [])

    def test_api_failure(self):
        self.mock_post.side_effect = Exception("API error")
        vec = self.svc.embed("fail")
        self.assertEqual(vec, [])
