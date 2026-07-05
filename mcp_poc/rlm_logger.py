import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from stats_collector import TurnStats

logger = logging.getLogger(__name__)


class RlmLogger:
    """Structured JSON-lines event logger for RLM orchestration.

    Writes one JSON object per line to `.session-log/rlm.jsonl`.
    Each line is a parseable event: rlmturn, todoevent, decompose, rlmsummary.
    """

    def __init__(self, workspace_path: str):
        self.log_dir = Path(workspace_path) / ".session-log"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.log_dir / "rlm.jsonl"
        self._file: Optional[Path] = None

    def _write(self, event: dict):
        line = json.dumps(event, default=str)
        with open(self._path, "a") as f:
            f.write(line + "\n")

    def decompose(self, task: str, num_todos: int, todo_descriptions: list[str], session_id: str = ""):
        self._write({
            "event": "decompose",
            "ts": datetime.now().isoformat(),
            "session_id": session_id,
            "task": task[:200],
            "num_todos": num_todos,
            "todos": todo_descriptions,
        })

    def todo_event(self, action: str, todo_id: str, description: str,
                   parent_id: Optional[str] = None, turn_number: int = 0, session_id: str = ""):
        self._write({
            "event": "todoevent",
            "ts": datetime.now().isoformat(),
            "session_id": session_id,
            "todo_id": todo_id,
            "action": action,
            "description": description[:120],
            "parent_id": parent_id or "",
            "turn_number": turn_number,
        })

    def turn(self, turn_stats: TurnStats, content_type: str, tool_calls_attempted: int,
             tool_calls_executed: int, tool_calls_failed: int, loop_count: int,
             response_preview: str, session_id: str = ""):
        self._write({
            "event": "rlmturn",
            "ts": datetime.now().isoformat(),
            "session_id": session_id,
            "turn_number": turn_stats.turn_number,
            "todo_id": turn_stats.todo_id,
            "tokens": {
                "prompt": turn_stats.prompt_tokens,
                "completion": turn_stats.completion_tokens,
            },
            "context": {
                "budget": turn_stats.context_budget,
                "used": turn_stats.context_used,
                "util_pct": round(turn_stats.context_utilization * 100, 1),
            },
            "duration_ms": round(turn_stats.duration_ns / 1_000_000, 1),
            "content_type": content_type,
            "tool_calls_attempted": tool_calls_attempted,
            "tool_calls_executed": tool_calls_executed,
            "tool_calls_failed": tool_calls_failed,
            "loop_count": loop_count,
            "self_references": turn_stats.self_references,
            "clarifications": turn_stats.clarification_requests,
            "truncated": turn_stats.truncated,
            "response_preview": response_preview[:200],
        })

    def summary(self, total_turns: int, total_prompt: int, total_completion: int,
                avg_duration_ms: float, todo_completion_rate: float,
                content_type_breakdown: dict[str, int],
                loop_detections: int, session_id: str = ""):
        self._write({
            "event": "rlmsummary",
            "ts": datetime.now().isoformat(),
            "session_id": session_id,
            "total_turns": total_turns,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "avg_duration_ms": round(avg_duration_ms, 1),
            "todo_completion_rate": round(todo_completion_rate, 3),
            "content_type_breakdown": content_type_breakdown,
            "loop_detections": loop_detections,
        })
