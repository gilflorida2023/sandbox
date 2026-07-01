import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class SessionState:
    """Persists conversation state across invocations.

    Stores session metadata, active task, conversation summary,
    referenced files, and context fragments so the system can
    resume naturally across sessions.
    """

    def __init__(self, session_id: str, storage_path: str = "./.session_state"):
        self.session_id = session_id
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.state_file = self.storage_path / f"{session_id}.json"
        self._state = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load session state %s: %s", self.state_file, e)
        return {
            "session_id": self.session_id,
            "created_at": time.time(),
            "updated_at": time.time(),
            "turn_count": 0,
            "active_task": None,
            "task_history": [],
            "pending_approvals": [],
            "conversation_summary": "",
            "referenced_files": [],
            "context_fragments": [],
        }

    def save(self):
        self._state["updated_at"] = time.time()
        self.state_file.write_text(json.dumps(self._state, indent=2, default=str))

    @property
    def active_task(self) -> Optional[str]:
        return self._state.get("active_task")

    @active_task.setter
    def active_task(self, task: Optional[str]):
        self._state["active_task"] = task

    @property
    def turn_count(self) -> int:
        return self._state.get("turn_count", 0)

    def increment_turn(self):
        self._state["turn_count"] = self._state.get("turn_count", 0) + 1
        self.save()

    def update_task(self, task: str):
        self._state["active_task"] = task
        self._state.setdefault("task_history", []).append({
            "task": task,
            "timestamp": time.time(),
        })
        self.save()

    def add_context_fragment(self, fragment: Dict):
        self._state.setdefault("context_fragments", []).append({
            **fragment,
            "timestamp": time.time(),
        })
        self.save()

    def get_recent_context(self, max_fragments: int = 5) -> List[Dict]:
        fragments = self._state.get("context_fragments", [])
        return fragments[-max_fragments:]

    def add_referenced_file(self, filepath: str):
        files = self._state.setdefault("referenced_files", [])
        if filepath not in files:
            files.append(filepath)
            self.save()

    @property
    def referenced_files(self) -> List[str]:
        return self._state.get("referenced_files", [])

    def set_conversation_summary(self, summary: str):
        self._state["conversation_summary"] = summary
        self.save()

    @property
    def conversation_summary(self) -> str:
        return self._state.get("conversation_summary", "")

    def get_task_history(self, max_entries: int = 10) -> List[Dict]:
        history = self._state.get("task_history", [])
        return history[-max_entries:]

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._state)

    def clear(self):
        self._state = {
            "session_id": self.session_id,
            "created_at": time.time(),
            "updated_at": time.time(),
            "turn_count": 0,
            "active_task": None,
            "task_history": [],
            "pending_approvals": [],
            "conversation_summary": "",
            "referenced_files": [],
            "context_fragments": [],
        }
        self.save()

    @classmethod
    def resume(cls, storage_path: str, session_id: str) -> "SessionState":
        return cls(session_id, storage_path)
