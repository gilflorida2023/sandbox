import logging
from typing import Dict, List, Optional, Set
from windowed_context_db import (
    KnowledgeChunk, WindowedContextDB, DEFAULT_BLACKLIST,
    _is_contaminated, _compile_regex_blacklist,
)

logger = logging.getLogger(__name__)


class ApprovalManager:
    """Manages user review of proposed knowledge chunks before storage.

    Sits between context extraction and the persistent knowledge DB.
    When require_approval is True, chunks go to a pending queue instead
    of being stored directly. The user approves or rejects via CLI commands.
    """

    def __init__(self, knowledge_db: WindowedContextDB,
                 require_approval: bool = True,
                 blacklist: Optional[Set[str]] = None,
                 blacklist_regex: Optional[List[str]] = None):
        self.knowledge = knowledge_db
        self.require_approval = require_approval
        self.blacklist = blacklist if blacklist is not None else set(DEFAULT_BLACKLIST)
        self.blacklist_regex = _compile_regex_blacklist(blacklist_regex or [])
        self.pending: Dict[str, KnowledgeChunk] = {}
        self.approved: Set[str] = set()
        self.rejected: Set[str] = set()

    def add_blacklist_pattern(self, pattern: str):
        """Add a substring blacklist pattern at runtime."""
        self.blacklist.add(pattern.lower())
        self.knowledge.add_blacklist_pattern(pattern)

    def add_blacklist_regex(self, pattern: str):
        """Add a regex blacklist pattern at runtime."""
        from windowed_context_db import re as _re
        try:
            compiled = _re.compile(pattern, _re.IGNORECASE)
            self.blacklist_regex.append(compiled)
        except _re.error as e:
            logger.warning("Invalid regex pattern %r: %s", pattern, e)
        self.knowledge.add_blacklist_regex(pattern)

    def propose_knowledge(self, content: str, source: str = "manual",
                          tags: Optional[List[str]] = None) -> str:
        """Submit a chunk for storage. Routes through approval if required."""
        if _is_contaminated(content, self.blacklist, self.blacklist_regex):
            logger.debug("ApprovalManager rejected contaminated chunk: %.80s", content)
            return ""

        chunk = KnowledgeChunk.new(content, source=source, tags=tags)

        if self.require_approval:
            self.pending[chunk.chunk_id] = chunk
            logger.info("Chunk %s proposed for approval (source=%s, tags=%s)",
                        chunk.chunk_id, source, tags)
            return chunk.chunk_id
        else:
            return self.knowledge.add(content, source=source, tags=tags)

    def approve(self, chunk_id: str) -> bool:
        """User approved this chunk. Move from pending to knowledge DB."""
        if chunk_id not in self.pending:
            logger.warning("Cannot approve unknown chunk: %s", chunk_id)
            return False
        chunk = self.pending.pop(chunk_id)
        self.approved.add(chunk_id)
        stored_id = self.knowledge.add(
            chunk.content, source=chunk.source, tags=chunk.tags
        )
        if stored_id:
            logger.info("Approved and stored chunk %s", chunk_id)
        else:
            logger.warning("Chunk %s approved but storage returned empty", chunk_id)
        return bool(stored_id)

    def reject(self, chunk_id: str) -> bool:
        """User rejected this chunk. Remove from pending."""
        if chunk_id not in self.pending:
            logger.warning("Cannot reject unknown chunk: %s", chunk_id)
            return False
        chunk = self.pending.pop(chunk_id)
        self.rejected.add(chunk_id)
        logger.info("Rejected chunk %s (source=%s)", chunk_id, chunk.source)
        return True

    def get_pending_summary(self) -> List[Dict]:
        """Return pending chunks for user review display."""
        summaries = []
        for chunk_id, chunk in self.pending.items():
            summaries.append({
                "id": chunk_id,
                "content_preview": chunk.content[:200],
                "source": chunk.source,
                "tags": chunk.tags,
                "created_at": chunk.created_at,
            })
        return summaries

    def pending_count(self) -> int:
        return len(self.pending)

    def ingest_session_log(self, log_path: str) -> int:
        """Read session log and route chunks through approval gate.

        Delegates parsing to WindowedContextDB but uses propose_knowledge
        as the store callback so chunks go to pending instead of directly to DB.
        """
        return self.knowledge.ingest_session_log(
            log_path, store_callback=self.propose_knowledge
        )
