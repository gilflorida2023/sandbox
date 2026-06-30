import json
from typing import List, Dict, Any, Optional
from tool_wiki import ToolWiki
from windowed_context_db import WindowedContextDB

class ContextManager:
    """Manages conversation history AND windowed knowledge accumulation.

    Two-layer design:
      Layer 1 — Conversation history (sliding window of raw messages)
      Layer 2 — Windowed knowledge chunks (deduped, weighted, persistent)

    The knowledge layer acts as a "prime sieve": only unique, relevant
    knowledge survives across sessions.
    """

    def __init__(self, wiki: ToolWiki, knowledge_path: str = None,
                 max_kb_window: int = 30, max_kb_total: int = 500):
        self.wiki = wiki
        self.history = []
        self.max_history = 20

        # Knowledge accumulation layer
        from config import config
        kb_path = knowledge_path or f"{config.workspace.path}/.context/knowledge"
        self.knowledge = WindowedContextDB(
            storage_path=kb_path,
            max_window=max_kb_window,
            max_total=max_kb_total,
        )

    def add_message(self, role: str, content: str, tool_calls: List = None,
                    tool_call_id: str = None):
        self.history.append({
            "role": role,
            "content": content,
            "tool_calls": tool_calls,
            "tool_call_id": tool_call_id
        })
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def get_relevant_context(self, query: str) -> Optional[str]:
        """Return relevant context by combining wiki docs + knowledge chunks."""
        query_lower = query.lower()
        parts = []

        # 1 — Wiki tool docs
        for tool_name in self.wiki.get_all_tool_names():
            if tool_name.lower() in query_lower:
                doc = self.wiki.get_tool_doc(tool_name)
                if doc:
                    parts.append(f"=== {tool_name} ===\n{doc[:2000]}")

        # 2 — Wiki guides
        for guide_name in self.wiki.get_all_guide_names():
            if guide_name.lower() in query_lower:
                doc = self.wiki.get_guide(guide_name)
                if doc:
                    parts.append(f"=== Guide: {guide_name} ===\n{doc[:2000]}")

        # 3 — Knowledge chunks (windowed)
        chunks = self.knowledge.query(query, max_results=5)
        if chunks:
            kb_block = []
            for c in chunks:
                kb_block.append(f"- {c.content[:500]}")
            parts.append("=== Prior Knowledge ===\n" + "\n".join(kb_block))

        if not parts:
            getting_started = self.wiki.get_guide("getting_started")
            if getting_started:
                return getting_started[:3000]
            return None

        return "\n\n".join(parts)

    def add_knowledge(self, content: str, source: str = "agent",
                      tags: List[str] = None) -> str:
        """Add a knowledge chunk (deduped by content hash)."""
        return self.knowledge.add(content, source=source, tags=tags)

    def get_knowledge_window(self, max_size: int = None) -> str:
        """Return top-weighted knowledge as a formatted string."""
        chunks = self.knowledge.window(max_size)
        if not chunks:
            return ""
        lines = ["=== Accumulated Knowledge (Window) ==="]
        for c in chunks:
            lines.append(f"- [{c.source}] {c.content[:300]}")
        return "\n".join(lines)

    def ingest_session_log(self, log_path: str) -> int:
        return self.knowledge.ingest_session_log(log_path)

    def ingest_session_logs(self, logs_dir: str, max_logs: int = 20) -> int:
        return self.knowledge.ingest_session_logs(logs_dir, max_logs=max_logs)

    def persist_knowledge(self):
        self.knowledge.save()

    def get_history_summary(self) -> str:
        if not self.history:
            return ""
        recent = self.history[-10:]
        summary = []
        for msg in recent:
            if msg["role"] == "user":
                summary.append(f"User: {msg['content'][:100]}")
            elif msg["role"] == "assistant":
                summary.append(f"Assistant: {msg['content'][:100]}")
            elif msg["role"] == "tool":
                summary.append(f"Tool result: {msg['content'][:100]}")
        return "\n".join(summary)