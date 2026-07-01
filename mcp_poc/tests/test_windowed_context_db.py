import unittest
import tempfile
import logging

logging.disable(logging.CRITICAL)


class TestContaminationHelpers(unittest.TestCase):

    def test_default_blacklist_rejects_contaminated(self):
        from windowed_context_db import _is_contaminated
        self.assertTrue(_is_contaminated("implement a prime sieve"))
        self.assertTrue(_is_contaminated("simplesieve is fast"))
        self.assertTrue(_is_contaminated("the sieve of eratosthenes algorithm"))
        self.assertTrue(_is_contaminated("primesieve in C"))

    def test_default_blacklist_accepts_clean(self):
        from windowed_context_db import _is_contaminated
        self.assertFalse(_is_contaminated("biscuit recipe with flour"))
        self.assertFalse(_is_contaminated("car maintenance tips"))
        self.assertFalse(_is_contaminated(""))

    def test_custom_blacklist(self):
        from windowed_context_db import _is_contaminated
        bl = {"biscuit", "recipe"}
        self.assertTrue(_is_contaminated("biscuit recipe", blacklist=bl))
        self.assertTrue(_is_contaminated("make a cake recipe", blacklist=bl))
        self.assertFalse(_is_contaminated("car repair", blacklist=bl))

    def test_regex_blacklist(self):
        from windowed_context_db import _is_contaminated, _compile_regex_blacklist
        rbl = _compile_regex_blacklist([r"sieve\s+of"])
        self.assertTrue(_is_contaminated("sieve of eratosthenes", blacklist_regex=rbl))
        self.assertTrue(_is_contaminated("the sieve of eratosthenes", blacklist_regex=rbl))
        self.assertFalse(_is_contaminated("sieve and eratosthenes", blacklist_regex=rbl))

    def test_regex_and_substring_combined(self):
        from windowed_context_db import _is_contaminated, _compile_regex_blacklist
        rbl = _compile_regex_blacklist([r"evil\s+code"])
        bl = {"biscuit"}
        self.assertTrue(_is_contaminated("biscuit recipe", blacklist=bl))
        self.assertTrue(_is_contaminated("evil code here", blacklist_regex=rbl))
        self.assertFalse(_is_contaminated("clean content", blacklist=bl, blacklist_regex=rbl))

    def test_invalid_regex_logs_warning(self):
        from windowed_context_db import _compile_regex_blacklist
        result = _compile_regex_blacklist([r"[invalid"])
        self.assertEqual(len(result), 0)

    def test_estimate_tokens(self):
        from windowed_context_db import _estimate_tokens
        self.assertEqual(_estimate_tokens("hello world"), 2)
        self.assertEqual(_estimate_tokens(""), 0)
        self.assertEqual(_estimate_tokens("a" * 100), 25)

    def test_truncate_at_tokens(self):
        from windowed_context_db import _truncate_at_tokens
        text = "hello world this is a test"
        self.assertEqual(_truncate_at_tokens(text, 100), text)
        short = _truncate_at_tokens(text, 2)
        self.assertLessEqual(len(short), 8)


class TestWindowedContextDB(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_accepts_blacklist_param(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir, blacklist={"biscuit"})
        self.assertEqual(db.blacklist, {"biscuit"})

    def test_accepts_blacklist_regex_param(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir, blacklist_regex=[r"sieve\s+of"])
        self.assertEqual(len(db.blacklist_regex), 1)

    def test_add_rejects_contaminated(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir, blacklist={"biscuit"})
        result = db.add("biscuit recipe", source="test")
        self.assertEqual(result, "")
        self.assertEqual(db.count(), 0)

    def test_add_accepts_clean(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir, blacklist={"biscuit"})
        result = db.add("car repair tips", source="test", tags=["car"])
        self.assertNotEqual(result, "")
        self.assertEqual(db.count(), 1)

    def test_runtime_blacklist_extension(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir, blacklist={"biscuit"})
        db.add_blacklist_pattern("cake")
        self.assertIn("cake", db.blacklist)
        self.assertTrue(db.blacklist.issuperset({"biscuit", "cake"}))

    def test_runtime_regex_extension(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir)
        db.add_blacklist_regex(r"evil\s+code")
        self.assertEqual(len(db.blacklist_regex), 1)
        # Verify it actually blocks
        from windowed_context_db import _is_contaminated
        self.assertTrue(_is_contaminated("evil code", blacklist_regex=db.blacklist_regex))

    def test_add_rejects_regex_contaminated(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir, blacklist_regex=[r"evil\s+code"])
        result = db.add("this has evil code in it", source="test")
        self.assertEqual(result, "")
        self.assertEqual(db.count(), 0)

    def test_add_accepts_when_regex_doesnt_match(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir, blacklist_regex=[r"evil\s+code"])
        result = db.add("this has evilcode in it", source="test")
        self.assertNotEqual(result, "")
        self.assertEqual(db.count(), 1)

    def test_query_returns_results(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir)
        db.add("biscuit recipe: flour and butter", source="test", tags=["recipe"])
        results = db.query("biscuit")
        self.assertEqual(len(results), 1)
        self.assertIn("biscuit", results[0].content.lower())

    def test_window_returns_weighted(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir)
        db.add("first entry", source="test")
        db.add("second entry", source="test")
        win = db.window(max_size=10)
        self.assertEqual(len(win), 2)

    def test_prune_removes_excess(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir, max_total=2)
        db.add("entry one", source="test")
        db.add("entry two", source="test")
        db.add("entry three", source="test")
        removed = db.prune()
        self.assertGreaterEqual(removed, 0)
        self.assertLessEqual(db.count(), 2)

    def test_clear_removes_all(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir)
        db.add("something", source="test")
        self.assertEqual(db.count(), 1)
        db.clear()
        self.assertEqual(db.count(), 0)

    def test_dedup_on_duplicate_add(self):
        from windowed_context_db import WindowedContextDB
        db = WindowedContextDB(self.tmpdir)
        cid1 = db.add("exact same content", source="test")
        cid2 = db.add("exact same content", source="test")
        self.assertEqual(cid1, cid2)
        self.assertEqual(db.count(), 1)

    def test_ingest_session_log_with_callback(self):
        from windowed_context_db import WindowedContextDB
        import tempfile
        log = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        log.write("## Decisions\n1. Use Python\n## Roadblocks\n- None\n")
        log.close()
        db = WindowedContextDB(self.tmpdir)
        captured = []
        def store_cb(content, source, tags):
            captured.append((content, source, tags))
            return "ok"
        count = db.ingest_session_log(log.name, store_callback=store_cb)
        self.assertGreater(count, 0)
        self.assertEqual(len(captured), count)


if __name__ == "__main__":
    unittest.main()
