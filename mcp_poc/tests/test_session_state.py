import unittest
import json
import tempfile
import time
from pathlib import Path
from session_state import SessionState


class TestSessionState(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.storage_path = Path(self.tempdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_initialization(self):
        state = SessionState("test_session", str(self.storage_path))
        self.assertEqual(state.session_id, "test_session")
        self.assertEqual(state.turn_count, 0)
        self.assertIsNone(state.active_task)
        self.assertEqual(state.conversation_summary, "")
        self.assertEqual(len(state.referenced_files), 0)
        self.assertEqual(len(state.get_recent_context()), 0)

    def test_save_and_load(self):
        state = SessionState("test_session", str(self.storage_path))
        state.active_task = "Implement feature"
        state.increment_turn()
        state.add_referenced_file("file1.py")
        state.add_context_fragment({"role": "user", "content": "Hello"})
        
        state.save()
        
        new_state = SessionState("test_session", str(self.storage_path))
        self.assertEqual(new_state.session_id, "test_session")
        self.assertEqual(new_state.active_task, "Implement feature")
        self.assertEqual(new_state.turn_count, 1)
        self.assertEqual(new_state.referenced_files, ["file1.py"])
        self.assertEqual(len(new_state.get_recent_context()), 1)

    def test_increment_turn(self):
        state = SessionState("test_session", str(self.storage_path))
        self.assertEqual(state.turn_count, 0)
        state.increment_turn()
        self.assertEqual(state.turn_count, 1)
        state.increment_turn()
        self.assertEqual(state.turn_count, 2)

    def test_update_task(self):
        state = SessionState("test_session", str(self.storage_path))
        state.update_task("Task 1")
        self.assertEqual(state.active_task, "Task 1")
        self.assertEqual(len(state.get_task_history()), 1)
        self.assertEqual(state.get_task_history()[0]["task"], "Task 1")
        
        state.update_task("Task 2")
        self.assertEqual(state.active_task, "Task 2")
        self.assertEqual(len(state.get_task_history()), 2)
        self.assertEqual(state.get_task_history()[1]["task"], "Task 2")

    def test_add_context_fragment(self):
        state = SessionState("test_session", str(self.storage_path))
        fragment = {"role": "user", "content": "Test content"}
        state.add_context_fragment(fragment)
        
        fragments = state.get_recent_context()
        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0]["role"], "user")
        self.assertEqual(fragments[0]["content"], "Test content")
        self.assertIn("timestamp", fragments[0])
        self.assertTrue(isinstance(fragments[0]["timestamp"], float))

    def test_get_recent_context_limiting(self):
        state = SessionState("test_session", str(self.storage_path))
        
        for i in range(10):
            state.add_context_fragment({"id": i})
        
        recent = state.get_recent_context(max_fragments=3)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[0]["id"], 7)  # Most recent
        self.assertEqual(recent[1]["id"], 8)
        self.assertEqual(recent[2]["id"], 9)

    def test_add_referenced_file(self):
        state = SessionState("test_session", str(self.storage_path))
        
        state.add_referenced_file("file1.py")
        self.assertEqual(state.referenced_files, ["file1.py"])
        
        state.add_referenced_file("file2.py")
        self.assertEqual(set(state.referenced_files), {"file1.py", "file2.py"})
        
        state.add_referenced_file("file1.py")  # Duplicate
        self.assertEqual(set(state.referenced_files), {"file1.py", "file2.py"})

    def test_set_conversation_summary(self):
        state = SessionState("test_session", str(self.storage_path))
        summary = "This is a test summary"
        state.set_conversation_summary(summary)
        
        self.assertEqual(state.conversation_summary, summary)

    def test_as_dict(self):
        state = SessionState("test_session", str(self.storage_path))
        state.add_referenced_file("file1.py")
        state.set_conversation_summary("Test summary")
        
        state_dict = state.as_dict()
        self.assertIsInstance(state_dict, dict)
        self.assertEqual(state_dict["session_id"], "test_session")
        self.assertEqual(state_dict["referenced_files"], ["file1.py"])
        self.assertEqual(state_dict["conversation_summary"], "Test summary")

    def test_clear(self):
        state = SessionState("test_session", str(self.storage_path))
        state.add_referenced_file("file1.py")
        state.set_conversation_summary("Test summary")
        state.increment_turn()
        
        state.clear()
        
        self.assertEqual(state.session_id, "test_session")
        self.assertEqual(state.turn_count, 0)
        self.assertIsNone(state.active_task)
        self.assertEqual(state.conversation_summary, "")
        self.assertEqual(state.referenced_files, [])
        self.assertEqual(len(state.get_recent_context()), 0)


if __name__ == "__main__":
    unittest.main()