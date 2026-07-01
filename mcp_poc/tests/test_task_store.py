import unittest
import tempfile
import time
from pathlib import Path
from task_store import TaskStore, TaskContext


class TestTaskStore(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.storage_path = Path(self.tempdir)
        self.task_store = TaskStore(str(self.storage_path))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_save_and_retrieve_task(self):
        task = TaskContext.new(
            task_description="Test task",
            session_id="session1"
        )
        task.files_involved = ["file1.py", "file2.py"]
        task.decisions = ["Decision 1", "Decision 2"]
        task.blockers = ["Blocker 1"]
        task.code_created = ["functions/main.py"]
        
        self.task_store.save_task(task)
        
        retrieved_task = self.task_store.get_task(task.task_id)
        self.assertIsNotNone(retrieved_task)
        self.assertEqual(retrieved_task.task_id, task.task_id)
        self.assertEqual(retrieved_task.task_description, "Test task")
        self.assertEqual(retrieved_task.session_id, "session1")
        self.assertEqual(retrieved_task.files_involved, ["file1.py", "file2.py"])
        self.assertEqual(retrieved_task.decisions, ["Decision 1", "Decision 2"])
        self.assertEqual(retrieved_task.blockers, ["Blocker 1"])
        self.assertEqual(retrieved_task.code_created, ["functions/main.py"])
        self.assertEqual(retrieved_task.status, "in_progress")
        self.assertIsNotNone(retrieved_task.created_at)
        self.assertIsNotNone(retrieved_task.last_updated)

    def test_search_tasks(self):
        task1 = TaskContext.new("Database migration", "session1")
        task1.decisions = ["Use Django migrations"]
        self.task_store.save_task(task1)
        
        task2 = TaskContext.new("API refactoring", "session1")
        task2.decisions = ["Use FastAPI"]
        self.task_store.save_task(task2)
        
        results = self.task_store.search_tasks("api", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].task_description, "API refactoring")
        
        results = self.task_store.search_tasks("migration", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].task_description, "Database migration")

    def test_get_recent_tasks(self):
        task1 = TaskContext.new("Task 1", "session1")
        self.task_store.save_task(task1)
        time.sleep(0.01)
        
        task2 = TaskContext.new("Task 2", "session1")
        self.task_store.save_task(task2)
        
        recent = self.task_store.get_recent_tasks(limit=5)
        self.assertEqual(len(recent), 2)
        # Most recent should be first
        self.assertEqual(recent[0].task_description, "Task 2")
        self.assertEqual(recent[1].task_description, "Task 1")

    def test_get_session_tasks(self):
        task1 = TaskContext.new("Task 1", "session1")
        self.task_store.save_task(task1)
        
        task2 = TaskContext.new("Task 2", "session1")
        self.task_store.save_task(task2)
        
        task3 = TaskContext.new("Task 3", "session2")
        self.task_store.save_task(task3)
        
        session_tasks = self.task_store.get_session_tasks("session1")
        self.assertEqual(len(session_tasks), 2)
        for task in session_tasks:
            self.assertEqual(task.session_id, "session1")

    def test_update_status(self):
        task = TaskContext.new("Test task", "session1")
        self.task_store.save_task(task)
        
        self.task_store.update_status(task.task_id, "completed")
        
        updated_task = self.task_store.get_task(task.task_id)
        self.assertEqual(updated_task.status, "completed")
        self.assertNotEqual(updated_task.last_updated, updated_task.created_at)

    def test_add_decision(self):
        task = TaskContext.new("Test task", "session1")
        self.task_store.save_task(task)
        
        self.task_store.add_decision(task.task_id, "Decision 1")
        self.task_store.add_decision(task.task_id, "Decision 2")
        
        updated_task = self.task_store.get_task(task.task_id)
        self.assertEqual(updated_task.decisions, ["Decision 1", "Decision 2"])

    def test_add_blocker(self):
        task = TaskContext.new("Test task", "session1")
        self.task_store.save_task(task)
        
        self.task_store.add_blocker(task.task_id, "Blocker 1")
        self.task_store.add_blocker(task.task_id, "Blocker 2")
        
        updated_task = self.task_store.get_task(task.task_id)
        self.assertEqual(updated_task.blockers, ["Blocker 1", "Blocker 2"])

    def test_add_file(self):
        task = TaskContext.new("Test task", "session1")
        self.task_store.save_task(task)
        
        self.task_store.add_file(task.task_id, "file1.py")
        self.task_store.add_file(task.task_id, "file2.py")
        self.task_store.add_file(task.task_id, "file1.py")  # Duplicate
        
        updated_task = self.task_store.get_task(task.task_id)
        self.assertEqual(updated_task.files_involved, ["file1.py", "file2.py"])

    def test_task_format_for_context(self):
        task = TaskContext.new("Database migration", "session1")
        task.decisions = ["Use Django migrations"]
        task.blockers = ["Need to clean up old code"]
        task.code_created = ["migrations/0001_initial.py"]
        
        formatted = self.task_store.format_task_for_context(task)
        
        self.assertIn("=== Previous Task: Database migration ===", formatted)
        self.assertIn("Status: in_progress", formatted)
        self.assertIn("Decisions:", formatted)
        self.assertIn("- Use Django migrations", formatted)
        self.assertIn("Blockers:", formatted)
        self.assertIn("- Need to clean up old code", formatted)
        self.assertIn("Code created: migrations/0001_initial.py", formatted)

    def test_task_count(self):
        self.assertEqual(self.task_store.count(), 0)
        
        task1 = TaskContext.new("Task 1", "session1")
        self.task_store.save_task(task1)
        
        self.assertEqual(self.task_store.count(), 1)
        
        task2 = TaskContext.new("Task 2", "session1")
        self.task_store.save_task(task2)
        
        self.assertEqual(self.task_store.count(), 2)

    def test_duplicate_task_save(self):
        task1 = TaskContext.new("Same task", "session1")
        task1.task_id = "custom_id_123"
        self.task_store.save_task(task1)
        
        task2 = TaskContext.new("Same task", "session1")
        task2.task_id = "custom_id_123"
        task2.decisions = ["New decision"]
        self.task_store.save_task(task2)
        
        retrieved_task = self.task_store.get_task("custom_id_123")
        self.assertEqual(retrieved_task.task_description, "Same task")
        self.assertEqual(retrieved_task.decisions, ["New decision"])

    def test_task_new_id_generation(self):
        task1 = TaskContext.new("Task description", "session1")
        self.assertEqual(len(task1.task_id), 16)  # First 16 chars of hash
        
        task2 = TaskContext.new("Task description", "session1")
        self.assertNotEqual(task1.task_id, task2.task_id)


if __name__ == "__main__":
    unittest.main()