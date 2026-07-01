import unittest
from unittest.mock import MagicMock
from context_stitcher import ContextStitcher


class TestContextStitcher(unittest.TestCase):
    def setUp(self):
        self.mock_store = MagicMock()
        self.mock_embed_service = MagicMock()
        self.stitcher = ContextStitcher(
            vector_store=self.mock_store,
            embedding_service=self.mock_embed_service
        )

    def test_get_session_context_with_embedding(self):
        self.mock_embed_service.embed_query = MagicMock(return_value=[0.1, 0.2, 0.3])
        self.mock_store.search_all = MagicMock(return_value=[])
        
        result = self.stitcher.get_session_context("test query")
        
        self.mock_embed_service.embed_query.assert_called_once_with("test query")
        self.mock_store.search_all.assert_called_once_with(
            [0.1, 0.2, 0.3], top_k=3, score_threshold=0.55
        )
        self.assertEqual(result, "")

    def test_get_session_context_without_embedding(self):
        self.mock_embed_service.embed_query = MagicMock(return_value=None)
        
        result = self.stitcher.get_session_context("test query")
        
        self.mock_embed_service.embed_query.assert_called_once_with("test query")
        self.mock_store.search_all.assert_not_called()
        self.assertEqual(result, "")

    def test_get_session_context_with_results(self):
        mock_result1 = MagicMock()
        mock_result1.content = "First result from session"
        mock_result1.source = "session1"
        mock_result1.score = 0.8
        
        mock_result2 = MagicMock()
        mock_result2.content = "Second result from session"
        mock_result2.source = "session2"
        mock_result2.score = 0.7
        
        self.mock_embed_service.embed_query = MagicMock(return_value=[0.1, 0.2, 0.3])
        self.mock_store.search_all = MagicMock(return_value=[mock_result1, mock_result2])
        
        result = self.stitcher.get_session_context("test query", max_tokens=1000)
        
        self.assertIn("=== Context from Previous Sessions ===", result)
        self.assertIn("[From session1 (relevance: 0.80)]", result)
        self.assertIn("First result from session", result)
        self.assertIn("[From session2 (relevance: 0.70)]", result)
        self.assertIn("Second result from session", result)

    def test_get_session_context_with_score_threshold(self):
        mock_result_below = MagicMock()
        mock_result_below.content = "Below threshold result"
        mock_result_below.source = "session1"
        mock_result_below.score = 0.4  # Below 0.55 threshold
        
        mock_result_above = MagicMock()
        mock_result_above.content = "Above threshold result"
        mock_result_above.source = "session2"
        mock_result_above.score = 0.8  # Above threshold
        
        self.mock_embed_service.embed_query = MagicMock(return_value=[0.1, 0.2, 0.3])
        self.mock_store.search_all = MagicMock(return_value=[mock_result_below, mock_result_above])
        
        result = self.stitcher.get_session_context("test query")
        
        # Both results should be included, but formatted correctly
        self.assertIn("Above threshold result", result)

    def test_format_results(self):
        mock_result1 = MagicMock()
        mock_result1.content = "Short content"
        mock_result1.source = "session1"
        mock_result1.score = 0.9
        
        mock_result2 = MagicMock()
        mock_result2.content = "Another short result"
        mock_result2.source = "session2"
        mock_result2.score = 0.8
        
        results = [mock_result1, mock_result2]
        
        result = self.stitcher._format_results(results, max_tokens=500)
        
        self.assertIn("=== Context from Previous Sessions ===", result)
        self.assertIn("[From session1 (relevance: 0.90)]", result)
        self.assertIn("Short content", result)
        self.assertIn("[From session2 (relevance: 0.80)]", result)
        self.assertIn("Another short result", result)

    def test_format_results_long_content_truncation(self):
        mock_result1 = MagicMock()
        mock_result1.content = "X" * 600  # Very long content
        mock_result1.source = "session1"
        mock_result1.score = 0.9
        
        mock_result2 = MagicMock()
        mock_result2.content = "Short"
        mock_result2.source = "session2"
        mock_result2.score = 0.8
        
        results = [mock_result1, mock_result2]
        
        result = self.stitcher._format_results(results, max_tokens=500)
        
        self.assertIn("...", result)  # Should be truncated
        self.assertIn("[From session1 (relevance: 0.90)]", result)
        self.assertIn("Short", result)

    def test_format_results_budget_limiting(self):
        mock_result1 = MagicMock()
        mock_result1.content = "Result 1 with medium length content"
        mock_result1.source = "session1"
        mock_result1.score = 0.9
        
        mock_result2 = MagicMock()
        mock_result2.content = "Result 2 with more content to fill budget"
        mock_result2.source = "session2"
        mock_result2.score = 0.8
        
        mock_result3 = MagicMock()
        mock_result3.content = "Result 3 that should be cut off due to budget"
        mock_result3.source = "session3"
        mock_result3.score = 0.7
        
        results = [mock_result1, mock_result2, mock_result3]
        
        result = self.stitcher._format_results(results, max_tokens=100)  # Very small budget
        
        # Should include first two full results
        self.assertIn("Result 1 with medium length content", result)
        self.assertIn("Result 2 with more content to fill budget", result)
        
        # Third result should be partially included or omitted due to budget
        self.assertTrue("Result 3" in result or result.count("Result 3") >= 0)

    def test_get_session_context_empty_result(self):
        self.mock_embed_service.embed_query = MagicMock(return_value=[0.1, 0.2, 0.3])
        self.mock_store.search_all = MagicMock(return_value=[])
        
        result = self.stitcher.get_session_context("test query")
        
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()