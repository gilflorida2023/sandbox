import unittest
import tempfile
import time
from pathlib import Path
from correction_store import CorrectionStore


class TestCorrectionStore(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.storage_path = Path(self.tempdir)
        self.correction_store = CorrectionStore(str(self.storage_path))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_add_and_retrieve_corrections(self):
        self.correction_store.add_correction(
            topic="api_response",
            incorrect="The API returned null",
            correct="The API returned {expected_value}",
            context="API endpoint was not handling error cases"
        )
        
        corrections = self.correction_store.get_corrections("api_response")
        self.assertEqual(len(corrections), 1)
        
        correction = corrections[0]
        self.assertEqual(correction["topic"], "api_response")
        self.assertIn("API returned null", correction["incorrect_output"])
        self.assertIn("API returned {expected_value}", correction["correct_output"])
        self.assertIn("API endpoint was not handling error cases", correction["context"])
        self.assertEqual(correction["applied_count"], 0)

    def test_add_multiple_corrections(self):
        self.correction_store.add_correction(
            topic="database_query",
            incorrect="SELECT * FROM table",
            correct="SELECT specific_columns FROM table WHERE condition"
        )
        
        self.correction_store.add_correction(
            topic="database_query",
            incorrect="UPDATE table SET column = value",
            correct="UPDATE table SET column = value WHERE condition"
        )
        
        corrections = self.correction_store.get_corrections("database_query")
        self.assertEqual(len(corrections), 2)
        
        topics = [c["topic"] for c in corrections]
        self.assertIn("database_query", topics)
        self.assertEqual(len([c for c in corrections if "api" in c.get("topic", "")]), 0)

    def test_get_all_corrections(self):
        self.correction_store.add_correction("topic1", "incorrect1", "correct1")
        self.correction_store.add_correction("topic2", "incorrect2", "correct2")
        
        all_corrections = self.correction_store.get_all_corrections(limit=5)
        self.assertEqual(len(all_corrections), 2)
        
        recent = self.correction_store.get_all_corrections(limit=1)
        self.assertEqual(len(recent), 1)

    def test_increment_applied(self):
        self.correction_store.add_correction("test_topic", "incorrect", "correct")
        
        corrections = self.correction_store.get_corrections("test_topic")
        correction_id = corrections[0]["id"]
        
        self.assertEqual(corrections[0]["applied_count"], 0)
        
        self.correction_store.increment_applied(correction_id)
        
        updated_corrections = self.correction_store.get_corrections("test_topic")
        self.assertEqual(updated_corrections[0]["applied_count"], 1)

    def test_format_corrections_for_context(self):
        self.correction_store.add_correction(
            topic="error_handling",
            incorrect="Silent failure",
            correct="Throw meaningful exception",
            context="Need user-visible errors"
        )
        
        formatted = self.correction_store.format_corrections_for_context("error_handling")
        
        self.assertIn("=== User Corrections ===", formatted)
        self.assertIn("- Topic: error_handling", formatted)
        self.assertIn("Incorrect: Silent failure", formatted)
        self.assertIn("Correct: Throw meaningful exception", formatted)
        # Note: context is NOT included in formatted output (only topic, incorrect, correct)
        self.assertNotIn("Need user-visible errors", formatted)
        
        # After formatting, applied count should be incremented
        corrections = self.correction_store.get_corrections("error_handling")
        self.assertEqual(corrections[0]["applied_count"], 1)

    def test_format_corrections_for_context_empty(self):
        formatted = self.correction_store.format_corrections_for_context("nonexistent_topic")
        self.assertEqual(formatted, "")

    def test_correction_count(self):
        self.assertEqual(self.correction_store.count(), 0)
        
        self.correction_store.add_correction("topic1", "incorrect1", "correct1")
        self.assertEqual(self.correction_store.count(), 1)
        
        self.correction_store.add_correction("topic2", "incorrect2", "correct2")
        self.assertEqual(self.correction_store.count(), 2)

    def test_correction_topic_search_partial(self):
        self.correction_store.add_correction(
            topic="database_migration",
            incorrect="Full table replacement",
            correct="Incremental migrations",
            context="Migration from SQLite to PostgreSQL"
        )
        
        self.correction_store.add_correction(
            topic="api_migration",
            incorrect="Complete rewrite",
            correct="Gradual API updates",
            context="API deprecation strategy"
        )
        
        # Search for "migration" should match database_migration (both have migration in topic)
        # Note: LIKE "migration" will match both "database_migration" and "api_migration"
        corrections = self.correction_store.get_corrections("migration")
        self.assertEqual(len(corrections), 2)
        
        # Search for "api" should match api_migration
        corrections = self.correction_store.get_corrections("api")
        self.assertEqual(len(corrections), 1)
        self.assertIn("api_migration", corrections[0]["topic"])

    def test_correction_data_preservation(self):
        long_incorrect = "This is a very long incorrect response " * 10
        long_correct = "This is the correct response with proper formatting and details " * 10
        long_context = "Detailed context about what went wrong and how to fix it " * 5
        
        self.correction_store.add_correction(
            topic="complex_function",
            incorrect=long_incorrect,
            correct=long_correct,
            context=long_context
        )
        
        corrections = self.correction_store.get_corrections("complex_function")
        self.assertEqual(len(corrections), 1)
        
        correction = corrections[0]
        self.assertIn("very long incorrect", correction["incorrect_output"])
        self.assertIn("correct response with proper", correction["correct_output"])
        self.assertIn("Detailed context about what went wrong", correction["context"])

    def test_correction_timestamp(self):
        before_time = time.time()
        self.correction_store.add_correction("timestamp_test", "old", "new")
        
        after_time = time.time()
        corrections = self.correction_store.get_corrections("timestamp_test")
        
        correction_time = corrections[0]["created_at"]
        self.assertGreaterEqual(correction_time, before_time)
        self.assertLessEqual(correction_time, after_time)


if __name__ == "__main__":
    unittest.main()