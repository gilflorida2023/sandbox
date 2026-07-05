"""Tests for the RLM module (SimpleRLM class)."""

import asyncio
import httpx
import sys
import json
sys.path.insert(0, "mcp_poc")

from unittest.mock import AsyncMock, patch, MagicMock

from rlm import SimpleRLM, _chunk_text, SAFE_BUILTINS


def make_mock_ollama():
    """Create a mock OllamaClient for testing."""
    mock = AsyncMock()
    mock.model = "qwen3:0.6b"
    mock.base_url = "http://localhost:11434"
    mock.chat = AsyncMock(return_value={
        "message": {"content": ""}
    })
    return mock


def make_mock_llm_client(responses):
    """Create a mock httpx client that returns given responses.

    responses: list of strings, each becomes the content returned by one
               completion() call to the mock LLM.

    The pre-flight ping is auto-answered (not consumed from responses).
    """
    from unittest.mock import AsyncMock, MagicMock
    client = AsyncMock()
    reply_iter = iter(responses)

    async def success_response(content=""):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={
            "message": {"content": content}
        })
        return resp

    async def mock_post(url, **kwargs):
        body = kwargs.get("json", {})
        msgs = body.get("messages", [])
        # Auto-answer pre-flight ping
        if any(m.get("content") == "ping" for m in msgs):
            return await success_response("pong")
        content = next(reply_iter)
        return await success_response(content)

    client.post = mock_post
    return client


class TestSimpleRLM:
    def test_init(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        assert rlm.model_name == "qwen3:0.6b"
        assert rlm.max_iters == 30
        assert rlm.max_llm_calls == 50
        assert rlm.temperature == 0.3
        assert rlm.llm_call_count == 0
        assert rlm.history == []

    def test_load_system_prompt(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM.__new__(SimpleRLM)
        prompt = rlm._load_system_prompt()
        assert "RLM controller" in prompt
        assert "call_tool" in prompt
        assert "llm_query" in prompt
        assert "FINAL" in prompt
        assert "workspace.git_clone" in prompt
        assert "workspace.run" in prompt

    def test_extract_code_from_markdown(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        code = rlm._extract_code("```python\nprint('hello')\n```")
        assert code == "print('hello')"

    def test_extract_code_from_markdown_py(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        code = rlm._extract_code("```py\nx = 1 + 2\n```")
        assert code == "x = 1 + 2"

    def test_extract_code_plain_python(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        code = rlm._extract_code("for i in range(10):\n    print(i)")
        assert "for i in range(10):" in code

    def test_extract_code_plain_with_final(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        code = rlm._extract_code('FINAL("done")')
        assert code == 'FINAL("done")'

    def test_extract_code_plain_with_llm_query(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        code = rlm._extract_code('result = llm_query("summarize this")')
        assert 'llm_query("summarize this")' in code

    def test_extract_code_empty(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        assert rlm._extract_code("") == ""
        assert rlm._extract_code("Just some text") == ""

    def test_exec_code_stdout(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        env = {"query": "test", "context": "", "history": [], "storage": {}, "sub_results": []}
        result = rlm._exec_code("print('hello world')", env)
        assert result["success"] is True
        assert result["stdout"] == "hello world\n"
        assert result["final_answer"] is None

    def test_exec_code_final_answer_var(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        env = {"query": "test", "context": "", "history": [], "storage": {}, "sub_results": []}
        result = rlm._exec_code('final_answer = "the answer"', env)
        assert result["success"] is True
        assert result["final_answer"] == "the answer"

    def test_exec_code_final_function(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        env = {"query": "test", "context": "", "history": [], "storage": {}, "sub_results": []}
        result = rlm._exec_code('FINAL("done")', env)
        assert result["success"] is True
        assert result["final_answer"] == "done"

    def test_exec_code_error_handling(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        env = {"query": "test", "context": "", "history": [], "storage": {}, "sub_results": []}
        result = rlm._exec_code("x = 1 / 0", env)
        assert result["success"] is False
        assert "ZeroDivisionError" in result["error"]

    def test_exec_code_safe_builtins_blocked(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        env = {"query": "test", "context": "", "history": [], "storage": {}, "sub_results": []}
        result = rlm._exec_code("import os", env)
        assert result["success"] is False
        assert "ImportError" in result["error"] or "NotImplementedError" in result["error"] or "AttributeError" in result["error"]

    def test_exec_code_storage_persistence(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        env = {"query": "test", "context": "", "history": [], "storage": {}, "sub_results": []}
        result = rlm._exec_code("storage['key'] = 'value'", env)
        assert result["env"].get("storage", {}).get("key") == "value"

    def test_exec_code_multi_step(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        env = {"query": "test", "context": "", "history": [], "storage": {}, "sub_results": []}
        result = rlm._exec_code("results = []\nfor i in range(3):\n    results.append(i * 2)", env)
        assert result["success"] is True
        assert "results" in result["env"]
        assert result["env"]["results"] == [0, 2, 4]

    def test_chunk_text(self):
        text = "hello world this is a test of the chunking function"
        chunks = _chunk_text(text, chunk_size=10, overlap=3)
        assert len(chunks) >= 3
        assert chunks[0] == "hello worl"
        assert chunks[0] in text

    def test_chunk_text_empty(self):
        assert _chunk_text("") == []
        assert _chunk_text(None) == []

    def test_chunk_text_no_overlap(self):
        text = "abcdefghijklmnopqrstuvwxyz"
        chunks = _chunk_text(text, chunk_size=10, overlap=0)
        assert len(chunks) == 3
        assert chunks[0] == "abcdefghij"
        assert chunks[1] == "klmnopqrst"
        assert chunks[2] == "uvwxyz"

    def test_safe_builtins_available(self):
        assert "print" in SAFE_BUILTINS
        assert "len" in SAFE_BUILTINS
        assert "range" in SAFE_BUILTINS
        assert "str" in SAFE_BUILTINS
        assert "list" in SAFE_BUILTINS
        assert "dict" in SAFE_BUILTINS
        assert "json" in SAFE_BUILTINS
        assert "Exception" in SAFE_BUILTINS

    def test_safe_builtins_blocked(self):
        assert "exec" not in SAFE_BUILTINS
        assert "eval" not in SAFE_BUILTINS
        assert "open" not in SAFE_BUILTINS

    def test_build_root_messages(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        messages, prompt = rlm._build_root_messages("test query", "var1: val1", "")
        assert isinstance(messages, list)
        assert isinstance(prompt, str)
        assert len(messages) == 2  # system + user
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "test query" in messages[1]["content"]
        assert "var1: val1" in messages[1]["content"]

    def test_build_root_messages_with_history(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        rlm.history.append({
            "iteration": 1,
            "prompt": "user prompt",
            "code": "print('hi')",
            "stdout": "hi\n",
            "error": "",
            "final_answer": None,
            "assistant": "```python\nprint('hi')\n```",
        })
        messages, prompt = rlm._build_root_messages("query", "env state", "prev output")
        assert len(messages) == 4  # system + user/assistant pair + user
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "user prompt"
        assert messages[2]["role"] == "assistant"
        assert "print('hi')" in messages[2]["content"]
        assert "prev output" in messages[3]["content"]

    def test_env_includes_query_and_context(self):
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        env = {"query": "my query", "context": "my context", "history": [], "storage": {}, "sub_results": []}
        result = rlm._exec_code("final_answer = query + ' | ' + context", env)
        assert result["final_answer"] == "my query | my context"

    def test_completion_loop_final_answer(self):
        """Full RLM loop: root LLM generates code that sets final_answer."""
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        rlm._check_tunnel = AsyncMock(return_value=True)
        rlm._llm_client = make_mock_llm_client(['final_answer = "42"'])
        rlm.max_iters = 5
        result = asyncio.run(rlm.completion("what is the answer", ""))
        assert result == "42"

    def test_completion_loop_final_function(self):
        """Full RLM loop: root LLM generates code calling FINAL()."""
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        rlm._check_tunnel = AsyncMock(return_value=True)
        rlm._llm_client = make_mock_llm_client(['FINAL("done")'])
        rlm.max_iters = 5
        result = asyncio.run(rlm.completion("finish", ""))
        assert result == "done"

    def test_completion_loop_max_iters(self):
        """Full RLM loop: reaches max iterations without final_answer."""
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        rlm._check_tunnel = AsyncMock(return_value=True)
        rlm._llm_client = make_mock_llm_client([
            "print('still working')",
            "print('still working')",
            "print('still working')",
        ])
        rlm.max_iters = 3
        result = asyncio.run(rlm.completion("keep going", ""))
        assert "Max iterations" in result

    def test_completion_loop_llm_error(self):
        """Full RLM loop: root LLM fails at iteration (caught by pre-flight ping)."""
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        rlm._check_tunnel = AsyncMock(return_value=True)
        client = AsyncMock()
        client.post = AsyncMock(side_effect=httpx.HTTPError("Ollama error"))
        client.get = AsyncMock(side_effect=httpx.HTTPError("Ollama error"))
        rlm._llm_client = client
        rlm.max_iters = 3
        result = asyncio.run(rlm.completion("test", ""))
        assert "Ollama process is DOWN" in result

    def test_completion_loop_code_extraction(self):
        """Verifies code is extracted from markdown blocks."""
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        rlm._check_tunnel = AsyncMock(return_value=True)
        rlm._llm_client = make_mock_llm_client([
            "```python\nfinal_answer = 'from block'\n```"
        ])
        rlm.max_iters = 5
        result = asyncio.run(rlm.completion("test", ""))
        assert result == "from block"

    def test_completion_loop_storage_persists(self):
        """Verifies storage dict persists across iterations."""
        mock_ollama = make_mock_ollama()
        rlm = SimpleRLM(mock_ollama)
        rlm._check_tunnel = AsyncMock(return_value=True)
        rlm._llm_client = make_mock_llm_client([
            "storage['count'] = 1\nprint('iter 1')",
            "storage['count'] = storage.get('count', 0) + 1\nprint('iter 2')",
            "final_answer = str(storage['count'])",
        ])
        rlm.max_iters = 5
        result = asyncio.run(rlm.completion("count", ""))
        assert result == "2"
