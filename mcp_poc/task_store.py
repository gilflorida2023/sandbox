import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

TASKS_DB = "tasks.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    task_description TEXT NOT NULL,
    session_id TEXT NOT NULL,
    files_involved TEXT NOT NULL DEFAULT '[]',
    decisions TEXT NOT NULL DEFAULT '[]',
    blockers TEXT NOT NULL DEFAULT '[]',
    code_created TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'in_progress',
    created_at REAL NOT NULL,
    last_updated REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(last_updated);
"""


@dataclass
class TaskContext:
    task_id: str
    task_description: str
    session_id: str
    files_involved: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    code_created: List[str] = field(default_factory=list)
    status: str = "in_progress"
    created_at: float = 0.0
    last_updated: float = 0.0

    @classmethod
    def new(cls, task_description: str, session_id: str) -> "TaskContext":
        import hashlib
        now = time.time()
        task_id = hashlib.sha256(
            f"{session_id}:{task_description}:{now}".encode()
        ).hexdigest()[:16]
        return cls(
            task_id=task_id,
            task_description=task_description,
            session_id=session_id,
            created_at=now,
            last_updated=now,
        )


class TaskStore:
    """Persists task context across sessions using SQLite.

    Stores what the system was working on, files involved,
    decisions made, blockers, and code created so the model
    can pick up where it left off.
    """

    def __init__(self, storage_path: str):
        self.storage = Path(storage_path)
        self.storage.mkdir(parents=True, exist_ok=True)
        db_path = self.storage / TASKS_DB
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA_SQL)

    def save_task(self, task: TaskContext):
        self._db.execute(
            """INSERT OR REPLACE INTO tasks
               (task_id, task_description, session_id, files_involved,
                decisions, blockers, code_created, status,
                created_at, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task.task_id, task.task_description, task.session_id,
             json.dumps(task.files_involved), json.dumps(task.decisions),
             json.dumps(task.blockers), json.dumps(task.code_created),
             task.status, task.created_at, task.last_updated),
        )
        self._db.commit()

    def get_task(self, task_id: str) -> Optional[TaskContext]:
        row = self._db.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return self._row_to_task(row) if row else None

    def search_tasks(self, query: str, limit: int = 5) -> List[TaskContext]:
        q = f"%{query}%"
        rows = self._db.execute(
            """SELECT * FROM tasks
               WHERE task_description LIKE ? OR decisions LIKE ? OR blockers LIKE ?
               ORDER BY last_updated DESC
               LIMIT ?""",
            (q, q, q, limit),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_recent_tasks(self, limit: int = 10) -> List[TaskContext]:
        rows = self._db.execute(
            "SELECT * FROM tasks ORDER BY last_updated DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_session_tasks(self, session_id: str) -> List[TaskContext]:
        rows = self._db.execute(
            "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_status(self, task_id: str, status: str):
        self._db.execute(
            "UPDATE tasks SET status = ?, last_updated = ? WHERE task_id = ?",
            (status, time.time(), task_id),
        )
        self._db.commit()

    def add_decision(self, task_id: str, decision: str):
        task = self.get_task(task_id)
        if task:
            task.decisions.append(decision)
            task.last_updated = time.time()
            self.save_task(task)

    def add_blocker(self, task_id: str, blocker: str):
        task = self.get_task(task_id)
        if task:
            task.blockers.append(blocker)
            task.last_updated = time.time()
            self.save_task(task)

    def add_file(self, task_id: str, filepath: str):
        task = self.get_task(task_id)
        if task:
            if filepath not in task.files_involved:
                task.files_involved.append(filepath)
                task.last_updated = time.time()
                self.save_task(task)

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    def format_task_for_context(self, task: TaskContext) -> str:
        lines = [f"=== Previous Task: {task.task_description} ==="]
        lines.append(f"Status: {task.status}")
        if task.files_involved:
            lines.append(f"Files: {', '.join(task.files_involved)}")
        if task.decisions:
            lines.append("Decisions:")
            for d in task.decisions:
                lines.append(f"  - {d}")
        if task.blockers:
            lines.append("Blockers:")
            for b in task.blockers:
                lines.append(f"  - {b}")
        if task.code_created:
            lines.append(f"Code created: {', '.join(task.code_created)}")
        return "\n".join(lines)

    def _row_to_task(self, row: sqlite3.Row) -> TaskContext:
        return TaskContext(
            task_id=row["task_id"],
            task_description=row["task_description"],
            session_id=row["session_id"],
            files_involved=json.loads(row["files_involved"]),
            decisions=json.loads(row["decisions"]),
            blockers=json.loads(row["blockers"]),
            code_created=json.loads(row["code_created"]),
            status=row["status"],
            created_at=row["created_at"],
            last_updated=row["last_updated"],
        )

    def close(self):
        self._db.close()
