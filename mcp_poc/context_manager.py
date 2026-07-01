import json
import logging
from typing import List, Dict, Any, Optional, Set
from tool_wiki import ToolWiki
from windowed_context_db import WindowedContextDB
from user_approval import ApprovalManager

logger = logging.getLogger(__name__)

def _estimate_tokens(text: str) -> int:
    return len(text) // 4


class ContextManager:
    """Manages conversation history, windowed knowledge, and semantic search.

    Two-layer design:
      Layer 1 — Conversation history (sliding window of raw messages)
      Layer 2 — Windowed knowledge chunks (deduped, weighted, persistent)
      Layer 3 — Semantic search (embedding + vector store for fuzzy matching)

    The knowledge layer acts as a "prime sieve": only unique, relevant
    knowledge survives across sessions.
    """

    def __init__(self, wiki: ToolWiki, knowledge_path: str = None,
                 max_kb_window: int = 30, max_kb_total: int = 500,
                 blacklist: Set[str] = None,
                 blacklist_regex: List[str] = None,
                 knowledge_indexer: Any = None):
        self.wiki = wiki
        self.history = []
        self.max_history = 20
        self.knowledge_indexer = knowledge_indexer

        # Knowledge accumulation layer
        from config import config
        kb_path = knowledge_path or f"{config.workspace.path}/.context/knowledge"
        self.knowledge = WindowedContextDB(
            storage_path=kb_path,
            max_window=max_kb_window,
            max_total=max_kb_total,
            blacklist=blacklist,
            blacklist_regex=blacklist_regex,
        )
        self.approval = ApprovalManager(
            knowledge_db=self.knowledge,
            require_approval=config.agent.knowledge.require_user_approval,
            blacklist=blacklist,
            blacklist_regex=blacklist_regex,
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

    def get_relevant_context(self, query: str, max_tokens: int = 2000) -> Optional[str]:
        """Return relevant context by combining wiki docs + knowledge chunks."""
        query_lower = query.lower()
        parts = []

        budget = max_tokens

        # 1 — Wiki tool docs
        for tool_name in self.wiki.get_all_tool_names():
            if tool_name.lower() in query_lower:
                doc = self.wiki.get_tool_doc(tool_name)
                if doc:
                    d = f"=== {tool_name} ===\n{doc}"
                    if _estimate_tokens(d) > budget:
                        logger.warning("Truncated wiki doc '%s' from %d to %d tokens",
                                       tool_name, _estimate_tokens(d), budget)
                        d = d[:budget * 4]
                    parts.append(d)
                    budget -= _estimate_tokens(d)
                    if budget <= 0:
                        logger.warning("Token budget exhausted after wiki docs")
                        break

        # 2 — Wiki guides
        if budget > 0:
            for guide_name in self.wiki.get_all_guide_names():
                if guide_name.lower() in query_lower:
                    doc = self.wiki.get_guide(guide_name)
                    if doc:
                        d = f"=== Guide: {guide_name} ===\n{doc}"
                        if _estimate_tokens(d) > budget:
                            logger.warning("Truncated wiki guide '%s' from %d to %d tokens",
                                           guide_name, _estimate_tokens(d), budget)
                            d = d[:max(budget * 4, 0)]
                        parts.append(d)
                        budget -= _estimate_tokens(d)
                        if budget <= 0:
                            logger.warning("Token budget exhausted after wiki guides")
                            break

        # 3 — Knowledge chunks (windowed, keyword match)
        if budget > 0:
            chunks = self.knowledge.query(query, max_results=5)
            if chunks:
                kb_block = []
                for c in chunks:
                    clipped = c.content
                    if _estimate_tokens(clipped) > 100:
                        clipped = clipped[:400]
                    kb_block.append(f"- {clipped}")
                combined = "=== Prior Knowledge ===\n" + "\n".join(kb_block)
                if _estimate_tokens(combined) > budget:
                    logger.warning("Truncated knowledge window from %d to %d tokens",
                                   _estimate_tokens(combined), budget)
                    combined = combined[:max(budget * 4, 0)]
                parts.append(combined)

        # 4 — Semantic search results (embedding-based)
        if budget > 0 and self.knowledge_indexer is not None and self.knowledge_indexer._indexed:
            semantic_results = self.knowledge_indexer.search(query, top_k=3, score_threshold=0.4)
            if semantic_results:
                semantic_block = self.knowledge_indexer.format_results(
                    semantic_results, max_chars=budget * 4
                )
                if _estimate_tokens(semantic_block) > budget:
                    logger.warning("Truncated semantic search from %d to %d tokens",
                                   _estimate_tokens(semantic_block), budget)
                    semantic_block = semantic_block[:max(budget * 4, 0)]
                parts.append(semantic_block)

        if not parts:
            getting_started = self.wiki.get_guide("getting_started")
            if getting_started:
                gs = getting_started[:max(max_tokens * 4, 0)]
                return gs
            return None

        result = "\n\n".join(parts)
        if _estimate_tokens(result) > max_tokens:
            logger.warning("Final context truncated from %d to %d tokens",
                           _estimate_tokens(result), max_tokens)
            result = result[:max_tokens * 4]
        return result

    def add_knowledge(self, content: str, source: str = "agent",
                      tags: List[str] = None) -> str:
        """Add a knowledge chunk via the approval gate.

        Also indexes approved chunks in the vector store for semantic search.
        """
        chunk_id = self.approval.propose_knowledge(content, source=source, tags=tags)
        if chunk_id and self.knowledge_indexer:
            self.knowledge_indexer.add_knowledge_chunk(content, source=source, tags=tags)
        return chunk_id

    def get_knowledge_window(self, max_size: int = None, max_tokens: int = 1000) -> str:
        """Return top-weighted knowledge as a formatted string."""
        chunks = self.knowledge.window(max_size)
        if not chunks:
            return ""
        lines = ["=== Accumulated Knowledge (Window) ==="]
        budget = max_tokens
        for c in chunks:
            clipped = c.content
            if _estimate_tokens(clipped) > 200:
                clipped = clipped[:800]
            entry = f"- [{c.source}] {clipped}"
            if _estimate_tokens(entry) > budget:
                logger.warning("Knowledge window exhausted budget after %d/%d chunks",
                               len(lines) - 1, len(chunks))
                break
            lines.append(entry)
            budget -= _estimate_tokens(entry)
        return "\n".join(lines)

    def ingest_session_log(self, log_path: str) -> int:
        return self.approval.ingest_session_log(log_path)

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