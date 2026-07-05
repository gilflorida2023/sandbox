import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from chroma_store import UnifiedChromaStore, TASKS_COLLECTION

logger = logging.getLogger(__name__)


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
    def __init__(self, storage_path: str):
        self.storage = Path(storage_path)
        self.storage.mkdir(parents=True, exist_ok=True)
        self._store = UnifiedChromaStore(str(self.storage))

    def _task_to_metadata(self, task: TaskContext) -> dict:
        return {
            "task_id": task.task_id,
            "session_id": task.session_id,
            "files_involved": json.dumps(task.files_involved),
            "decisions": json.dumps(task.decisions),
            "blockers": json.dumps(task.blockers),
            "code_created": json.dumps(task.code_created),
            "status": task.status,
            "created_at": task.created_at,
            "last_updated": task.last_updated,
        }

    def _row_to_task(self, row: dict) -> Optional[TaskContext]:
        if not row:
            return None
        meta = row.get("metadata") or {}
        doc = row.get("document", meta.get("task_description", ""))
        files_raw = meta.get("files_involved", "[]")
        if isinstance(files_raw, str):
            files_raw = json.loads(files_raw) if files_raw else []
        decisions_raw = meta.get("decisions", "[]")
        if isinstance(decisions_raw, str):
            decisions_raw = json.loads(decisions_raw) if decisions_raw else []
        blockers_raw = meta.get("blockers", "[]")
        if isinstance(blockers_raw, str):
            blockers_raw = json.loads(blockers_raw) if blockers_raw else []
        code_raw = meta.get("code_created", "[]")
        if isinstance(code_raw, str):
            code_raw = json.loads(code_raw) if code_raw else []
        return TaskContext(
            task_id=row["id"],
            task_description=doc,
            session_id=meta.get("session_id", ""),
            files_involved=files_raw,
            decisions=decisions_raw,
            blockers=blockers_raw,
            code_created=code_raw,
            status=meta.get("status", "in_progress"),
            created_at=meta.get("created_at", 0.0),
            last_updated=meta.get("last_updated", 0.0),
        )

    def save_task(self, task: TaskContext):
        if self.get_task(task.task_id):
            self._store.update(
                TASKS_COLLECTION,
                ids=[task.task_id],
                metadatas=[self._task_to_metadata(task)],
                documents=[task.task_description],
            )
        else:
            self._store.add_one(
                TASKS_COLLECTION, task.task_id,
                metadata=self._task_to_metadata(task),
                document=task.task_description,
            )

    def get_task(self, task_id: str) -> Optional[TaskContext]:
        result = self._store.get_one(TASKS_COLLECTION, task_id)
        return self._row_to_task(result) if result else None

    def search_tasks(self, query: str, limit: int = 5) -> List[TaskContext]:
        q = query.lower()
        results = self._store.get(TASKS_COLLECTION)
        tasks = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                doc = (results.get("documents") or [""])[i]
                if q in doc.lower():
                    row = {
                        "id": results["ids"][i],
                        "metadata": (results.get("metadatas") or [{}])[i],
                        "document": doc,
                    }
                    task = self._row_to_task(row)
                    if task:
                        tasks.append(task)
        tasks.sort(key=lambda t: t.last_updated, reverse=True)
        return tasks[:limit]

    def get_recent_tasks(self, limit: int = 10) -> List[TaskContext]:
        results = self._store.get(TASKS_COLLECTION)
        tasks = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                row = {
                    "id": results["ids"][i],
                    "metadata": (results.get("metadatas") or [{}])[i],
                    "document": (results.get("documents") or [""])[i],
                }
                task = self._row_to_task(row)
                if task:
                    tasks.append(task)
        tasks.sort(key=lambda t: t.last_updated, reverse=True)
        return tasks[:limit]

    def get_session_tasks(self, session_id: str) -> List[TaskContext]:
        results = self._store.get(
            TASKS_COLLECTION,
            where={"session_id": session_id},
        )
        tasks = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                row = {
                    "id": results["ids"][i],
                    "metadata": (results.get("metadatas") or [{}])[i],
                    "document": (results.get("documents") or [""])[i],
                }
                task = self._row_to_task(row)
                if task:
                    tasks.append(task)
        tasks.sort(key=lambda t: t.created_at)
        return tasks

    def update_status(self, task_id: str, status: str):
        task = self.get_task(task_id)
        if task:
            task.status = status
            task.last_updated = time.time()
            self.save_task(task)

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
        return self._store.count(TASKS_COLLECTION)

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

    def close(self):
        pass
