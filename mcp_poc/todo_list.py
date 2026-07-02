import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

TODOS_DB = "todos.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    parent_id TEXT,
    session_id TEXT NOT NULL,
    discoveries TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    completed_at REAL,
    iteration_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_todos_session ON todos(session_id);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
CREATE INDEX IF NOT EXISTS idx_todos_parent ON todos(parent_id);
"""


@dataclass
class TodoItem:
    id: str
    description: str
    status: str = "pending"
    parent_id: Optional[str] = None
    session_id: str = ""
    discoveries: List[str] = field(default_factory=list)
    created_at: float = 0.0
    completed_at: Optional[float] = None
    iteration_count: int = 0

    @classmethod
    def new(cls, description: str, session_id: str, parent_id: Optional[str] = None) -> "TodoItem":
        import hashlib
        now = time.time()
        todo_id = hashlib.sha256(
            f"{session_id}:{description}:{now}".encode()
        ).hexdigest()[:16]
        return cls(
            id=todo_id,
            description=description,
            session_id=session_id,
            parent_id=parent_id,
            created_at=now,
        )


class TodoList:
    def __init__(self, storage_path: str):
        self.storage = Path(storage_path)
        self.storage.mkdir(parents=True, exist_ok=True)
        db_path = self.storage / TODOS_DB
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA_SQL)

    def create_todo(self, description: str, session_id: str, parent_id: Optional[str] = None) -> TodoItem:
        todo = TodoItem.new(description, session_id, parent_id)
        self._db.execute(
            """INSERT INTO todos
               (id, description, status, parent_id, session_id, discoveries,
                created_at, completed_at, iteration_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (todo.id, todo.description, todo.status, todo.parent_id,
             todo.session_id, json.dumps(todo.discoveries),
             todo.created_at, todo.completed_at, todo.iteration_count),
        )
        self._db.commit()
        return todo

    def pick_next(self) -> Optional[TodoItem]:
        row = self._db.execute(
            """SELECT * FROM todos
               WHERE status IN ('in_progress', 'pending')
               ORDER BY
                 CASE status WHEN 'in_progress' THEN 0 WHEN 'pending' THEN 1 END,
                 created_at ASC
               LIMIT 1"""
        ).fetchone()
        if row:
            todo = self._row_to_todo(row)
            if todo.status == "pending":
                self.update_status(todo.id, "in_progress")
                todo.status = "in_progress"
            return todo
        return None

    def update_status(self, todo_id: str, status: str):
        now = time.time() if status in ("completed", "blocked") else None
        self._db.execute(
            "UPDATE todos SET status = ?, completed_at = ? WHERE id = ?",
            (status, now, todo_id),
        )
        self._db.commit()

    def increment_iteration(self, todo_id: str):
        self._db.execute(
            "UPDATE todos SET iteration_count = iteration_count + 1 WHERE id = ?",
            (todo_id,),
        )
        self._db.commit()

    def add_discovery(self, todo_id: str, doc_id: str):
        todo = self.get_todo(todo_id)
        if todo and doc_id not in todo.discoveries:
            todo.discoveries.append(doc_id)
            self._db.execute(
                "UPDATE todos SET discoveries = ? WHERE id = ?",
                (json.dumps(todo.discoveries), todo_id),
            )
            self._db.commit()

    def get_todo(self, todo_id: str) -> Optional[TodoItem]:
        row = self._db.execute(
            "SELECT * FROM todos WHERE id = ?", (todo_id,)
        ).fetchone()
        return self._row_to_todo(row) if row else None

    def get_sub_todos(self, parent_id: str) -> List[TodoItem]:
        rows = self._db.execute(
            "SELECT * FROM todos WHERE parent_id = ? ORDER BY created_at",
            (parent_id,),
        ).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def get_session_todos(self, session_id: str) -> List[TodoItem]:
        rows = self._db.execute(
            "SELECT * FROM todos WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def get_all_todos(self) -> List[TodoItem]:
        rows = self._db.execute(
            "SELECT * FROM todos ORDER BY created_at"
        ).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def completion_rate(self) -> float:
        total = self._db.execute("SELECT COUNT(*) FROM todos").fetchone()[0]
        if total == 0:
            return 1.0
        done = self._db.execute(
            "SELECT COUNT(*) FROM todos WHERE status = 'completed'"
        ).fetchone()[0]
        return done / total

    def count_by_status(self) -> dict:
        rows = self._db.execute(
            "SELECT status, COUNT(*) as cnt FROM todos GROUP BY status"
        ).fetchall()
        counts = {"pending": 0, "in_progress": 0, "completed": 0, "blocked": 0}
        for r in rows:
            counts[r["status"]] = r["cnt"]
        return counts

    def todo_text(self, session_id: str, max_todos: int = 10) -> str:
        todos = self.get_session_todos(session_id)[-max_todos:]
        if not todos:
            return ""
        lines = ["=== Active Todos ==="]
        for t in todos:
            prefix = "[✓]" if t.status == "completed" else \
                     "[▶]" if t.status == "in_progress" else \
                     "[⊘]" if t.status == "blocked" else "[ ]"
            lines.append(f"  {prefix} {t.id[:8]} {t.description}")
            if t.discoveries:
                lines.append(f"       discoveries: {len(t.discoveries)}")
        total = sum(self.count_by_status().values())
        lines.append(f"  --- {self.count_by_status().get('completed', 0)}/{total} completed ---")
        return "\n".join(lines)

    def reset_session(self, session_id: str):
        self._db.execute("DELETE FROM todos WHERE session_id = ?", (session_id,))
        self._db.commit()

    def _row_to_todo(self, row: sqlite3.Row) -> Optional[TodoItem]:
        if not row:
            return None
        return TodoItem(
            id=row["id"],
            description=row["description"],
            status=row["status"],
            parent_id=row["parent_id"],
            session_id=row["session_id"],
            discoveries=json.loads(row["discoveries"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            iteration_count=row["iteration_count"],
        )

    def close(self):
        self._db.close()
