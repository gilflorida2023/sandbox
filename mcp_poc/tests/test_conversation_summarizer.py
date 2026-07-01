import asyncio
import unittest
import json
from unittest.mock import AsyncMock, MagicMock
from conversation_summarizer import ConversationSummarizer


class TestConversationSummarizer(unittest.TestCase):
    def setUp(self):
        self.mock_ollama = AsyncMock()
        self.summarizer = ConversationSummarizer(
            ollama_client=self.mock_ollama,
            max_summary_tokens=300,
            keep_recent_turns=4
        )

    async def test_should_summarize_when_enough_turns(self):
        messages = []
        for i in range(10):
            messages.append({"role": "user", "content": f"Message {i}"})
        
        self.mock_ollama.chat = AsyncMock(return_value={
            "message": {"content": "Summary of message 0-5"}
        })
        
        result = await self.summarizer.summarize_turns(messages)
        
        self.assertEqual(result, "Summary of message 0-5")

    async def test_should_not_summarize_when_too_few_turns(self):
        messages = []
        for i in range(5):
            messages.append({"role": "user", "content": f"Message {i}"})
        
        result = await self.summarizer.summarize_turns(messages)
        
        self.assertEqual(result, "")

    async def test_should_summarize_only_older_turns(self):
        messages = []
        for i in range(10):
            messages.append({"role": "user", "content": f"Message {i}"})
        
        self.mock_ollama.chat = AsyncMock(return_value={
            "message": {"content": "Summary"}
        })
        
        result = await self.summarizer.summarize_turns(messages)
        
        self.assertEqual(result, "Summary")

    def test_messages_to_text_conversion(self):
        messages = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Response", "tool_calls": [
                {"function": {"name": "tool1", "arguments": "{}"}}
            ]}
        ]
        
        text = self.summarizer._messages_to_text(messages)
        
        self.assertIn("[USER]: Hello world", text)
        self.assertIn("[ASSISTANT]: Response", text)
        self.assertIn("[tools: tool1]", text)

    def test_truncate_to_budget(self):
        long_text = "A" * 2000
        
        result = self.summarizer._truncate_to_budget(long_text)
        
        self.assertEqual(len(result), 300 * 4)  # 300 tokens * 4 chars per token
        
        short_text = "Short"
        self.assertEqual(self.summarizer._truncate_to_budget(short_text), "Short")

    def test_format_summary_for_context_with_summary(self):
        summary = "Test summary content"
        
        result = self.summarizer.format_summary_for_context(summary)
        
        self.assertIn("=== Previous Conversation Summary ===", result)
        self.assertIn("Test summary content", result)

    def test_format_summary_for_context_empty(self):
        result = self.summarizer.format_summary_for_context("")
        
        self.assertEqual(result, "")
        
        result = self.summarizer.format_summary_for_context(None)
        self.assertEqual(result, "")

    async def test_ollama_chat_integration(self):
        messages = []
        for i in range(10):
            messages.append({"role": "user", "content": f"Message {i}"})
        
        self.mock_ollama.chat = AsyncMock(return_value={
            "message": {"content": "Generated summary"}
        })
        
        result = await self.summarizer.summarize_turns(messages)
        
        self.mock_ollama.chat.assert_called_once()
        call_args = self.mock_ollama.chat.call_args
        
        self.assertIn("model", call_args.kwargs)
        self.assertIn("messages", call_args.kwargs)
        self.assertEqual(len(call_args.kwargs["messages"]), 1)
        self.assertEqual(call_args.kwargs["messages"][0]["role"], "user")

    async def test_token_budget_exceeded(self):
        messages = []
        for i in range(20):  # Large number of messages
            messages.append({"role": "user", "content": "A very long message that should trigger truncation"})
        
        self.mock_ollama.chat = AsyncMock(return_value={
            "message": {"content": "X" * 2000}  # Long text
        })
        
        result = await self.summarizer.summarize_turns(messages)
        
        self.assertEqual(len(result), 300 * 4)  # Truncated to budget

    async def test_summarization_failure(self):
        messages = []
        for i in range(10):
            messages.append({"role": "user", "content": f"Message {i}"})
        
        self.mock_ollama.chat = AsyncMock(side_effect=Exception("Ollama error"))
        
        result = await self.summarizer.summarize_turns(messages)
        
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()