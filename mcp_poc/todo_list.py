import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from chroma_store import UnifiedChromaStore, TODOS_COLLECTION

logger = logging.getLogger(__name__)


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
        self._store = UnifiedChromaStore(str(self.storage))

    def _todo_to_metadata(self, todo: TodoItem) -> dict:
        meta = {
            "status": todo.status,
            "session_id": todo.session_id,
            "discoveries": json.dumps(todo.discoveries),
            "created_at": todo.created_at,
            "iteration_count": todo.iteration_count,
        }
        if todo.parent_id is not None:
            meta["parent_id"] = todo.parent_id
        if todo.completed_at is not None:
            meta["completed_at"] = todo.completed_at
        return meta

    def _row_to_todo(self, row: dict) -> Optional[TodoItem]:
        if not row:
            return None
        meta = row.get("metadata") or {}
        doc = row.get("document", "")
        discoveries_raw = meta.get("discoveries", "[]")
        if isinstance(discoveries_raw, str):
            discoveries = json.loads(discoveries_raw) if discoveries_raw else []
        else:
            discoveries = discoveries_raw or []
        return TodoItem(
            id=row["id"],
            description=doc,
            status=meta.get("status", "pending"),
            parent_id=meta.get("parent_id"),
            session_id=meta.get("session_id", ""),
            discoveries=discoveries,
            created_at=meta.get("created_at", 0.0),
            completed_at=meta.get("completed_at"),
            iteration_count=meta.get("iteration_count", 0),
        )

    def create_todo(self, description: str, session_id: str, parent_id: Optional[str] = None) -> TodoItem:
        todo = TodoItem.new(description, session_id, parent_id)
        self._store.add_one(
            TODOS_COLLECTION, todo.id,
            metadata=self._todo_to_metadata(todo),
            document=todo.description,
        )
        return todo

    def pick_next(self) -> Optional[TodoItem]:
        results = self._store.get(
            TODOS_COLLECTION,
            limit=100,
        )
        candidates = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                row = {
                    "id": results["ids"][i],
                    "metadata": (results.get("metadatas") or [{}])[i],
                    "document": (results.get("documents") or [""])[i],
                }
                todo = self._row_to_todo(row)
                if todo and todo.status in ("in_progress", "pending"):
                    candidates.append(todo)
        if not candidates:
            return None
        candidates.sort(key=lambda t: (
            0 if t.status == "in_progress" else 1,
            t.created_at,
        ))
        todo = candidates[0]
        if todo.status == "pending":
            self.update_status(todo.id, "in_progress")
            todo.status = "in_progress"
        return todo

    def update_status(self, todo_id: str, status: str):
        now = time.time() if status in ("completed", "blocked") else None
        todo = self.get_todo(todo_id)
        if todo:
            meta = self._todo_to_metadata(todo)
            meta["status"] = status
            if now:
                meta["completed_at"] = now
            self._store.update(
                TODOS_COLLECTION,
                ids=[todo_id],
                metadatas=[meta],
            )

    def increment_iteration(self, todo_id: str):
        todo = self.get_todo(todo_id)
        if todo:
            meta = self._todo_to_metadata(todo)
            meta["iteration_count"] = meta.get("iteration_count", 0) + 1
            self._store.update(
                TODOS_COLLECTION,
                ids=[todo_id],
                metadatas=[meta],
            )

    def add_discovery(self, todo_id: str, doc_id: str):
        todo = self.get_todo(todo_id)
        if todo and doc_id not in todo.discoveries:
            todo.discoveries.append(doc_id)
            self._store.update(
                TODOS_COLLECTION,
                ids=[todo_id],
                metadatas=[self._todo_to_metadata(todo)],
            )

    def get_todo(self, todo_id: str) -> Optional[TodoItem]:
        result = self._store.get_one(TODOS_COLLECTION, todo_id)
        return self._row_to_todo(result) if result else None

    def get_sub_todos(self, parent_id: str) -> List[TodoItem]:
        results = self._store.get(
            TODOS_COLLECTION,
            where={"parent_id": parent_id},
        )
        todos = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                row = {
                    "id": results["ids"][i],
                    "metadata": (results.get("metadatas") or [{}])[i],
                    "document": (results.get("documents") or [""])[i],
                }
                todo = self._row_to_todo(row)
                if todo:
                    todos.append(todo)
        todos.sort(key=lambda t: t.created_at)
        return todos

    def get_session_todos(self, session_id: str) -> List[TodoItem]:
        results = self._store.get(
            TODOS_COLLECTION,
            where={"session_id": session_id},
        )
        todos = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                row = {
                    "id": results["ids"][i],
                    "metadata": (results.get("metadatas") or [{}])[i],
                    "document": (results.get("documents") or [""])[i],
                }
                todo = self._row_to_todo(row)
                if todo:
                    todos.append(todo)
        todos.sort(key=lambda t: t.created_at)
        return todos

    def get_all_todos(self) -> List[TodoItem]:
        results = self._store.get(TODOS_COLLECTION)
        todos = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                row = {
                    "id": results["ids"][i],
                    "metadata": (results.get("metadatas") or [{}])[i],
                    "document": (results.get("documents") or [""])[i],
                }
                todo = self._row_to_todo(row)
                if todo:
                    todos.append(todo)
        todos.sort(key=lambda t: t.created_at)
        return todos

    def completion_rate(self) -> float:
        todos = self.get_all_todos()
        if not todos:
            return 1.0
        done = sum(1 for t in todos if t.status == "completed")
        return done / len(todos)

    def count_by_status(self) -> dict:
        todos = self.get_all_todos()
        counts = {"pending": 0, "in_progress": 0, "completed": 0, "blocked": 0}
        for t in todos:
            if t.status in counts:
                counts[t.status] += 1
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
        results = self._store.get(
            TODOS_COLLECTION,
            where={"session_id": session_id},
        )
        if results and results.get("ids"):
            self._store.delete(TODOS_COLLECTION, ids=results["ids"])

    def close(self):
        pass
