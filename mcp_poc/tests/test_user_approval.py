import unittest
import tempfile
import logging

logging.disable(logging.CRITICAL)


class TestApprovalManager(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_approval(self, require_approval=True, blacklist=None, blacklist_regex=None):
        from windowed_context_db import WindowedContextDB
        from user_approval import ApprovalManager
        kb = WindowedContextDB(self.tmpdir, blacklist=blacklist or set())
        am = ApprovalManager(kb, require_approval=require_approval,
                             blacklist=blacklist, blacklist_regex=blacklist_regex)
        return kb, am

    def test_propose_adds_to_pending(self):
        kb, am = self._make_approval()
        cid = am.propose_knowledge("biscuit recipe", source="test", tags=["recipe"])
        self.assertNotEqual(cid, "")
        self.assertEqual(am.pending_count(), 1)
        self.assertEqual(kb.count(), 0)

    def test_propose_rejects_contaminated(self):
        kb, am = self._make_approval(blacklist={"biscuit"})
        cid = am.propose_knowledge("biscuit recipe", source="test")
        self.assertEqual(cid, "")
        self.assertEqual(am.pending_count(), 0)
        self.assertEqual(kb.count(), 0)

    def test_propose_rejects_regex_contaminated(self):
        kb, am = self._make_approval(blacklist_regex=[r"evil\s+code"])
        cid = am.propose_knowledge("evil code here", source="test")
        self.assertEqual(cid, "")
        self.assertEqual(am.pending_count(), 0)

    def test_approve_moves_to_knowledge(self):
        kb, am = self._make_approval()
        cid = am.propose_knowledge("biscuit recipe", source="test")
        self.assertEqual(kb.count(), 0)
        result = am.approve(cid)
        self.assertTrue(result)
        self.assertEqual(am.pending_count(), 0)
        self.assertEqual(kb.count(), 1)
        self.assertIn(cid, am.approved)

    def test_approve_unknown_returns_false(self):
        kb, am = self._make_approval()
        result = am.approve("nonexistent")
        self.assertFalse(result)

    def test_reject_removes_from_pending(self):
        kb, am = self._make_approval()
        cid = am.propose_knowledge("biscuit recipe", source="test")
        self.assertEqual(am.pending_count(), 1)
        result = am.reject(cid)
        self.assertTrue(result)
        self.assertEqual(am.pending_count(), 0)
        self.assertEqual(kb.count(), 0)
        self.assertIn(cid, am.rejected)

    def test_reject_unknown_returns_false(self):
        kb, am = self._make_approval()
        result = am.reject("nonexistent")
        self.assertFalse(result)

    def test_get_pending_summary(self):
        kb, am = self._make_approval()
        cid = am.propose_knowledge("biscuit recipe with flour and butter",
                                   source="test", tags=["recipe"])
        summary = am.get_pending_summary()
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["id"], cid)
        self.assertEqual(summary[0]["source"], "test")
        self.assertEqual(summary[0]["tags"], ["recipe"])
        self.assertIn("biscuit", summary[0]["content_preview"])

    def test_empty_pending_summary(self):
        kb, am = self._make_approval()
        self.assertEqual(am.get_pending_summary(), [])

    def test_no_approval_mode_stores_directly(self):
        kb, am = self._make_approval(require_approval=False)
        cid = am.propose_knowledge("biscuit recipe", source="test")
        self.assertEqual(am.pending_count(), 0)
        self.assertEqual(kb.count(), 1)

    def test_multiple_pending_chunks(self):
        kb, am = self._make_approval()
        cid1 = am.propose_knowledge("first", source="test")
        cid2 = am.propose_knowledge("second", source="test")
        cid3 = am.propose_knowledge("third", source="test")
        self.assertEqual(am.pending_count(), 3)
        am.approve(cid1)
        am.reject(cid3)
        self.assertEqual(am.pending_count(), 1)
        self.assertEqual(kb.count(), 1)
        self.assertIn(cid2, am.pending)

    def test_runtime_blacklist_extension(self):
        kb, am = self._make_approval()
        am.add_blacklist_pattern("biscuit")
        cid = am.propose_knowledge("biscuit recipe", source="test")
        self.assertEqual(cid, "")
        self.assertIn("biscuit", kb.blacklist)

    def test_runtime_regex_extension(self):
        kb, am = self._make_approval()
        am.add_blacklist_regex(r"evil\s+code")
        cid = am.propose_knowledge("evil code here", source="test")
        self.assertEqual(cid, "")
        self.assertEqual(len(kb.blacklist_regex), 1)

    def test_ingest_session_log_through_approval(self):
        from windowed_context_db import WindowedContextDB
        from user_approval import ApprovalManager
        import tempfile as tf
        log = tf.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        log.write("## Decisions\n1. Use Python\n## Ideas\n- New approach\n")
        log.close()
        kb = WindowedContextDB(self.tmpdir)
        am = ApprovalManager(kb, require_approval=True)
        count = am.ingest_session_log(log.name)
        self.assertGreater(count, 0)
        self.assertEqual(am.pending_count(), count)
        self.assertEqual(kb.count(), 0)


if __name__ == "__main__":
    unittest.main()
