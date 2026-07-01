import unittest
import tempfile
import logging
from unittest.mock import Mock, MagicMock, patch

logging.disable(logging.CRITICAL)


class MockWiki:
    def get_all_tool_names(self):
        return ["workspace.read", "workspace.write"]

    def get_tool_doc(self, name):
        return f"Documentation for {name}"

    def get_all_guide_names(self):
        return ["getting_started"]

    def get_guide(self, name):
        return "Welcome to the workspace."


class TestContextManager(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.wiki = MockWiki()

    @patch("config.config")
    def test_init_creates_knowledge_and_approval(self, mock_config):
        mock_config.workspace.path = self.tmpdir
        mock_config.agent.knowledge.require_user_approval = True
        mock_config.agent.knowledge.blacklist = ["biscuit"]
        mock_config.agent.knowledge.blacklist_regex = []
        from context_manager import ContextManager
        cm = ContextManager(self.wiki, knowledge_path=self.tmpdir)
        self.assertIsNotNone(cm.knowledge)
        self.assertIsNotNone(cm.approval)
        self.assertEqual(cm.knowledge.count(), 0)

    @patch("config.config")
    def test_add_knowledge_routes_through_approval(self, mock_config):
        mock_config.workspace.path = self.tmpdir
        mock_config.agent.knowledge.require_user_approval = True
        mock_config.agent.knowledge.blacklist = ["biscuit"]
        mock_config.agent.knowledge.blacklist_regex = []
        from context_manager import ContextManager
        cm = ContextManager(self.wiki, knowledge_path=self.tmpdir)
        cid = cm.add_knowledge("useful tip", source="test")
        self.assertNotEqual(cid, "")
        self.assertEqual(cm.approval.pending_count(), 1)
        self.assertEqual(cm.knowledge.count(), 0)
        cm.approval.approve(cid)
        self.assertEqual(cm.knowledge.count(), 1)

    @patch("config.config")
    def test_ingest_session_log_routes_through_approval(self, mock_config):
        mock_config.workspace.path = self.tmpdir
        mock_config.agent.knowledge.require_user_approval = True
        mock_config.agent.knowledge.blacklist = []
        mock_config.agent.knowledge.blacklist_regex = []
        from context_manager import ContextManager
        import tempfile as tf
        log = tf.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        log.write("## Decisions\n1. Use Python\n")
        log.close()
        cm = ContextManager(self.wiki, knowledge_path=self.tmpdir)
        count = cm.ingest_session_log(log.name)
        self.assertGreater(count, 0)
        self.assertEqual(cm.approval.pending_count(), count)

    @patch("config.config")
    def test_get_relevant_context_respects_budget(self, mock_config):
        mock_config.workspace.path = self.tmpdir
        mock_config.agent.knowledge.require_user_approval = False
        mock_config.agent.knowledge.blacklist = []
        mock_config.agent.knowledge.blacklist_regex = []
        from context_manager import ContextManager
        cm = ContextManager(self.wiki, knowledge_path=self.tmpdir)
        ctx = cm.get_relevant_context("workspace.read", max_tokens=10)
        self.assertIsNotNone(ctx)
        estimated = len(ctx) // 4
        self.assertLessEqual(estimated, 10)

    @patch("config.config")
    def test_get_relevant_context_returns_none_for_unmatched(self, mock_config):
        mock_config.workspace.path = self.tmpdir
        mock_config.agent.knowledge.require_user_approval = False
        mock_config.agent.knowledge.blacklist = []
        mock_config.agent.knowledge.blacklist_regex = []
        from context_manager import ContextManager
        cm = ContextManager(self.wiki, knowledge_path=self.tmpdir)
        ctx = cm.get_relevant_context("xyznonexistent12345", max_tokens=100)
        self.assertIsNotNone(ctx)
        self.assertIn("welcome", ctx.lower())

    @patch("config.config")
    def test_get_knowledge_window_empty(self, mock_config):
        mock_config.workspace.path = self.tmpdir
        mock_config.agent.knowledge.require_user_approval = False
        mock_config.agent.knowledge.blacklist = []
        mock_config.agent.knowledge.blacklist_regex = []
        from context_manager import ContextManager
        cm = ContextManager(self.wiki, knowledge_path=self.tmpdir)
        result = cm.get_knowledge_window()
        self.assertEqual(result, "")

    @patch("config.config")
    def test_get_knowledge_window_with_chunks(self, mock_config):
        mock_config.workspace.path = self.tmpdir
        mock_config.agent.knowledge.require_user_approval = False
        mock_config.agent.knowledge.blacklist = []
        mock_config.agent.knowledge.blacklist_regex = []
        from context_manager import ContextManager
        cm = ContextManager(self.wiki, knowledge_path=self.tmpdir)
        cm.add_knowledge("important fact about coding", source="test")
        result = cm.get_knowledge_window(max_tokens=500)
        self.assertIn("important fact", result)

    @patch("config.config")
    def test_history_tracking(self, mock_config):
        mock_config.workspace.path = self.tmpdir
        mock_config.agent.knowledge.require_user_approval = False
        mock_config.agent.knowledge.blacklist = []
        mock_config.agent.knowledge.blacklist_regex = []
        from context_manager import ContextManager
        cm = ContextManager(self.wiki, knowledge_path=self.tmpdir)
        cm.add_message("user", "hello")
        cm.add_message("assistant", "hi there")
        self.assertEqual(len(cm.history), 2)
        summary = cm.get_history_summary()
        self.assertIn("hello", summary)
        self.assertIn("hi there", summary)


if __name__ == "__main__":
    unittest.main()
