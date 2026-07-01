import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = (
    "Summarize the following conversation turns, preserving:\n"
    "- The user's goal/task\n"
    "- Key decisions made\n"
    "- Files created or modified\n"
    "- Any issues or blockers encountered\n"
    "- Important findings or insights\n\n"
    "{turns}\n\nSummary:"
)


class ConversationSummarizer:
    """Summarizes conversation history for context window management.

    When the conversation exceeds the context window, earlier turns
    are summarized to preserve key information without consuming
    excessive tokens. The last N turns are always kept intact.
    """

    def __init__(self, ollama_client, max_summary_tokens: int = 300,
                 keep_recent_turns: int = 4):
        self.ollama = ollama_client
        self.max_summary_tokens = max_summary_tokens
        self.keep_recent_turns = keep_recent_turns

    async def summarize_turns(self, messages: List[Dict]) -> str:
        if len(messages) < self.keep_recent_turns + 2:
            return ""

        turns_to_summarize = messages[:-self.keep_recent_turns]
        turn_text = self._messages_to_text(turns_to_summarize)

        prompt = SUMMARY_PROMPT.format(turns=turn_text)

        try:
            response = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            summary = response.get("message", {}).get("content", "")
            summary = self._truncate_to_budget(summary)
            logger.info("Conversation summarized (%d chars -> %d chars)",
                        len(turn_text), len(summary))
            return summary
        except Exception as e:
            logger.warning("Summarization failed: %s", e)
            return ""

    def _messages_to_text(self, messages: List[Dict]) -> str:
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                tc_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                content += f" [tools: {', '.join(tc_names)}]"
            clipped = content[:800]
            lines.append(f"[{role.upper()}]: {clipped}")
        return "\n".join(lines)

    def _truncate_to_budget(self, summary: str) -> str:
        max_chars = self.max_summary_tokens * 4
        if len(summary) > max_chars:
            logger.warning("Summary truncated from %d to %d chars",
                           len(summary), max_chars)
            return summary[:max_chars]
        return summary

    def format_summary_for_context(self, summary: str) -> str:
        if not summary:
            return ""
        return f"=== Previous Conversation Summary ===\n{summary}"
