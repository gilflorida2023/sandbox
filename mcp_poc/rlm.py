"""Simple Recursive Language Model (RLM) implementation.

The Root LLM generates Python code executed in a persistent sandboxed REPL.
Code can inspect context, call sub-LLM queries, execute MCP tools, etc.
Loop continues until the model sets final_answer or calls FINAL().
"""

import asyncio
import ast
import datetime
import difflib
import io
import json
import logging
import os
import re
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import config

logger = logging.getLogger(__name__)

CGI_BASE = Path("/home/scout/projects/sandbox/scout/cgi-bin/mcp/tools")
TOOL_LOG_PATH = Path(config.workspace.path) / ".session-log" / "rlm_tool_calls.jsonl"


def _safe_import(name, *args, **kwargs):
    """Restricted __import__: only allow modules that are safe."""
    ALLOWED = {"json", "math", "re", "textwrap", "collections", "itertools",
               "functools", "pathlib", "datetime", "typing", "copy", "random"}
    top = name.split(".")[0]
    if top in ALLOWED or not args:
        return __import__(name, *args, **kwargs)
    raise ImportError(f"Import of '{name}' is not allowed in RLM sandbox")


SAFE_BUILTINS = {
    "__import__": _safe_import,
    "abs": abs, "all": all, "any": any, "ascii": ascii, "bin": bin,
    "bool": bool, "bytearray": bytearray, "bytes": bytes, "chr": chr,
    "complex": complex, "dict": dict, "dir": dir, "divmod": divmod,
    "enumerate": enumerate, "filter": filter, "float": float, "format": format,
    "frozenset": frozenset, "getattr": getattr, "hasattr": hasattr,
    "hash": hash, "hex": hex, "id": id, "int": int, "isinstance": isinstance,
    "issubclass": issubclass, "iter": iter, "len": len, "list": list,
    "map": map, "max": max, "min": min, "next": next, "object": object,
    "oct": oct, "ord": ord, "pow": pow, "print": print, "range": range,
    "repr": repr, "reversed": reversed, "round": round, "set": set,
    "slice": slice, "sorted": sorted, "str": str, "sum": sum,
    "tuple": tuple, "type": type, "zip": zip, "True": True, "False": False,
    "None": None, "Exception": Exception, "ValueError": ValueError,
    "TypeError": TypeError, "KeyError": KeyError, "IndexError": IndexError,
    "RuntimeError": RuntimeError, "StopIteration": StopIteration,
    "json": json,
}

# Known tool name shortcuts the model might guess
TOOL_ALIASES = {
    "clone": "workspace.git_clone",
    "git_clone": "workspace.git_clone",
    "build": "workspace.build",
    "run": "workspace.run",
    "list": "workspace.list",
    "read": "workspace.read",
    "write": "workspace.write",
    "search": "workspace.search",
    "compile": "workspace.compile",
    "delete": "workspace.delete",
    "lookup": "wiki.lookup",
    "wiki": "wiki.lookup",
    "webfetch": "workspace.webfetch",
    "websearch": "workspace.websearch",
    "list_tools": "workspace.list_tools",
}

KNOWN_TOOL_NAMES = sorted(TOOL_ALIASES.values())


def _fix_call_tool_dicts(code: str) -> str:
    """Fix missing commas in multi-line call_tool() dict arguments.

    Small models often wrap long dict entries across lines and drop the
    trailing comma on the first line. This inserts them before exec().
    """
    if "call_tool" not in code:
        return code

    fixed = []
    for line in code.splitlines():
        stripped = line.rstrip()
        if not stripped:
            fixed.append(stripped)
            continue

        peek_next = False
        if fixed:
            prev = fixed[-1].rstrip()
            if (prev.endswith('"') or prev.endswith("'") or prev[-1].isdigit()):
                peek_next = True

        if peek_next and (stripped.startswith('"') or stripped.startswith("'")):
            fixed[-1] += ","

        fixed.append(stripped)

    return "\n".join(fixed)


class _MaxLLMCallsError(RuntimeError):
    """Raised when the RLM exceeds the maximum number of LLM sub-calls."""


def _sync_call_mcp(name: str, arguments: dict) -> dict:
    """Synchronous MCP tool call using subprocess."""
    try:
        proc = subprocess.run(
            ["bash", str(CGI_BASE / "call.sh")],
            input=json.dumps({"name": name, "arguments": arguments}).encode(),
            capture_output=True,
            timeout=60,
        )
        stderr_text = proc.stderr.decode().strip()
        if proc.returncode != 0:
            msg = stderr_text or f"CGI script failed (exit {proc.returncode})"
            return {"success": False, "error": msg, "stderr": stderr_text}
        try:
            result = json.loads(proc.stdout.decode())
            result["stderr"] = stderr_text
            return result
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid JSON from tool: {e}",
                "raw_stdout": proc.stdout.decode()[:2000],
                "stderr": stderr_text,
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "MCP tool call timed out after 60s"}
    except FileNotFoundError:
        return {"success": False, "error": f"MCP CGI script not found: {CGI_BASE / 'call.sh'}"}


def _sync_llm_request(base_url: str, model: str, messages: list, temperature: float = 0.3) -> str:
    """Synchronous Ollama API call for sub-queries inside exec()."""
    try:
        response = httpx.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_ctx": 32768,
                },
            },
            timeout=300,
        )
        response.raise_for_status()
        data = response.json()
        msg = data.get("message", {})
        return msg.get("content", "")
    except Exception as e:
        return f"[LLM call failed: {e}]"


def _append_tool_log(entry: dict):
    """Append one tool call record to the JSONL log file."""
    try:
        TOOL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TOOL_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning("Failed to write tool log: %s", e)


def _shorten_code(code: str, max_len: int = 80) -> str:
    """Truncate code for display, showing first call_tool or key line."""
    for line in code.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("print("):
            return stripped[:max_len]
    return code[:max_len]


def _suggest_tool(wrong_name: str) -> Optional[str]:
    """Suggest the correct tool name for a likely wrong guess."""
    exact = TOOL_ALIASES.get(wrong_name)
    if exact:
        return exact
    matches = difflib.get_close_matches(wrong_name, KNOWN_TOOL_NAMES, n=1, cutoff=0.4)
    if matches:
        return matches[0]
    return None


def _fetch_available_tools() -> list:
    """Fetch available MCP tools by calling list.sh."""
    try:
        proc = subprocess.run(
            ["bash", str(CGI_BASE / "list.sh")],
            input=b"{}",
            capture_output=True,
            timeout=10,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout.decode())
            tools = data.get("tools", [])
            return sorted(t["name"] for t in tools)
    except Exception as e:
        logger.warning("Failed to fetch tool list: %s", e)
    return KNOWN_TOOL_NAMES


class SimpleRLM:
    """Recursive Language Model controller.

    The root LLM generates Python code executed in a persistent sandbox.
    Sub-tasks are handled by llm_query() (sync wrapper around Ollama API).
    Loop continues until FINAL() or max iterations reached.
    """

    def __init__(
        self,
        ollama_client,
        vector_store=None,
        mcp_client=None,
    ):
        self.ollama = ollama_client
        self.model_name = ollama_client.model
        self.base_url = ollama_client.base_url
        self.vector_store = vector_store
        self.mcp = mcp_client

        self.max_iters = config.rlm.max_iterations
        self.max_llm_calls = config.rlm.max_llm_calls
        self.temperature = config.rlm.temperature
        self.num_ctx = config.rlm.num_ctx

        self.llm_call_count = 0
        self.history: List[Dict] = []
        self._root_system_prompt = self._load_system_prompt()
        self._session_id = str(uuid.uuid4())[:8]

        self._safe_builtins = dict(SAFE_BUILTINS)

        # Dedup tracking
        self._prev_codes: List[str] = []
        self._tool_call_log: List[Dict] = []

        # Available tools (fetched at startup)
        self._available_tools: List[str] = _fetch_available_tools()

        # Persistent HTTP client for Root LLM calls (lazy init)
        self._llm_client = None

        print(f"  RLM session: {self._session_id}")
        print(f"  Tool log: {TOOL_LOG_PATH}")
        print(f"  Available tools: {', '.join(self._available_tools)}")

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / "rlm_system_prompt.txt"
        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            return "You are an RLM controller. Write Python code. Set final_answer or call FINAL() when done."

    def _build_prompt(self, query: str, env_summary: str, last_output: str) -> str:
        parts = [f"## Query\n{query}\n\n## Environment State\n{env_summary}"]
        if last_output:
            parts.append(f"\n## Previous Output\n{last_output}")
        return "\n".join(parts)

    def _build_root_messages(self, query: str, env_summary: str, last_output: str = "") -> Tuple[list, str]:
        messages = [{"role": "system", "content": self._root_system_prompt}]

        for turn in self.history[-4:]:
            if turn.get("prompt"):
                messages.append({"role": "user", "content": turn["prompt"]})
            if turn.get("assistant"):
                messages.append({"role": "assistant", "content": turn["assistant"]})

        prompt_text = self._build_prompt(query, env_summary, last_output)
        messages.append({"role": "user", "content": prompt_text})
        return messages, prompt_text

    def _make_llm_query(self, env: dict) -> callable:
        def llm_query(prompt: str, system: str = None) -> str:
            if self.llm_call_count >= self.max_llm_calls:
                raise _MaxLLMCallsError(
                    f"Max LLM sub-calls ({self.max_llm_calls}) reached"
                )
            self.llm_call_count += 1

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            result = _sync_llm_request(
                self.base_url, self.model_name, messages, self.temperature
            )

            if "sub_results" not in env:
                env["sub_results"] = []
            env["sub_results"].append(result)
            return result

        return llm_query

    def _make_call_tool(self) -> callable:
        """Create call_tool() with automatic name correction and logging."""

        def call_tool(name: str, arguments: dict) -> dict:
            # Auto-correct common tool name mistakes
            corrected = _suggest_tool(name)
            if corrected:
                actual_name = corrected
                if corrected != name:
                    print(f"  (corrected tool name: '{name}' → '{corrected}')")
            else:
                actual_name = name

            result = _sync_call_mcp(actual_name, arguments)

            entry = {
                "ts": datetime.datetime.now().isoformat(),
                "session": self._session_id,
                "tool": actual_name,
                "requested_tool": name if name != actual_name else None,
                "args": arguments,
                "result_success": result.get("success"),
                "result_preview": json.dumps(result)[:500],
            }
            _append_tool_log(entry)
            self._tool_call_log.append(entry)

            print(f"[{actual_name}] success={result.get('success')}")
            content = result.get("content") or result.get("stdout") or result.get("error") or ""
            if content:
                for line in content.strip().splitlines()[:20]:
                    print(f"  {line}")
                if len(content.strip().splitlines()) > 20:
                    print(f"  ... ({len(content.strip().splitlines())} lines total)")

            # If the tool failed with "Unknown tool" and we didn't auto-correct,
            # print a helpful suggestion
            if not result.get("success") and "Unknown tool" in result.get("error", ""):
                suggestion = _suggest_tool(name)
                if suggestion:
                    print(f"  💡 Did you mean '{suggestion}'?")
                else:
                    print(f"  💡 Available tools: {', '.join(self._available_tools[:10])}...")

            return result

        return call_tool

    def _make_search_context(self) -> callable:
        if not self.vector_store:
            def _noop(query: str, top_k: int = 5) -> list:
                return []
            return _noop

        def search_context(query: str, top_k: int = 5) -> list:
            try:
                from embedding_service import EmbeddingService
                embed = EmbeddingService(
                    host=config.embedding.host,
                    port=config.embedding.port,
                    model=config.embedding.model,
                )
                vec = embed.embed_query(query)
                if not vec:
                    return []
                results = self.vector_store.search_all(vec, top_k=top_k)
                return [
                    {"content": r.content, "source": r.source, "score": r.score}
                    for r in results
                ]
            except Exception as e:
                logger.warning("search_context failed: %s", e)
                return []

        return search_context

    def _detect_loop(self, code: str) -> Optional[str]:
        normalized = " ".join(
            line.strip() for line in code.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        if not normalized:
            return None

        match_count = sum(1 for c in self._prev_codes if c == normalized)
        self._prev_codes.append(normalized)

        if match_count >= 3:
            called_tools = {e["tool"] for e in self._tool_call_log}
            steps = []
            if "workspace.git_clone" not in called_tools:
                steps.append("1. call_tool('workspace.git_clone', {'url': '<repo_url>', 'path': 'repos/simplesieve'})")
            if "workspace.git_clone" in called_tools and "workspace.build" not in called_tools:
                steps.append("2. call_tool('workspace.build', {'path': 'repos/simplesieve'})")
            if "workspace.build" in called_tools and "workspace.run" not in called_tools:
                steps.append("3. call_tool('workspace.run', {'path': 'repos/simplesieve/simplesieve', 'args': ['-c', '-limit', '1e6']})")

            guide = "You are repeating the same code. Follow these exact steps ONE AT A TIME:\n"
            if steps:
                guide += "\n".join(steps)
            else:
                guide += "All steps appear done. Call FINAL('summary of what was done')"
            return guide

        return None

    def _exec_code(self, code: str, env: dict) -> dict:
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture

        globals_dict = {
            "__builtins__": self._safe_builtins,
            **env,
        }

        globals_dict["llm_query"] = self._make_llm_query(env)
        globals_dict["call_tool"] = self._make_call_tool()
        globals_dict["search_context"] = self._make_search_context()
        globals_dict["chunk_text"] = _chunk_text

        final_answer_container = {"value": None}

        def FINAL(answer: str):
            final_answer_container["value"] = answer
            raise StopIteration(answer)

        globals_dict["FINAL"] = FINAL

        try:
            exec(textwrap.dedent(code), globals_dict)
            captured = stdout_capture.getvalue()
            final_val = globals_dict.get("final_answer", final_answer_container["value"])
            return {
                "success": True,
                "stdout": captured,
                "final_answer": final_val,
                "env": globals_dict,
            }
        except StopIteration as e:
            captured = stdout_capture.getvalue()
            return {
                "success": True,
                "stdout": captured,
                "final_answer": e.args[0] if e.args else final_answer_container["value"],
                "env": globals_dict,
            }
        except _MaxLLMCallsError as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": stdout_capture.getvalue(),
                "final_answer": None,
            }
        except Exception as e:
            error_text = f"{type(e).__name__}: {e}"
            import traceback
            error_text += "\n" + traceback.format_exc()
            return {
                "success": False,
                "error": error_text,
                "stdout": stdout_capture.getvalue(),
                "final_answer": None,
            }
        finally:
            sys.stdout = old_stdout

    async def completion(self, query: str, context: Any = None) -> str:
        """Main RLM entry point."""
        self.llm_call_count = 0
        self.history = []
        self._prev_codes = []
        self._tool_call_log = []

        env = {
            "query": query,
            "context": context or "",
            "history": [],
            "storage": {},
            "sub_results": [],
            "uuid": str(uuid.uuid4()),
            "available_tools": self._available_tools,
        }

        iteration = 0
        print()

        # Pre-flight ping: verify Ollama is responsive before entering the loop
        if self._llm_client is None:
            self._llm_client = httpx.AsyncClient(timeout=config.ollama.timeout)
        print("  (pinging Ollama — waiting for model to load...)")
        try:
            ping_resp = await self._llm_client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model_name,
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": False,
                    "options": {"num_ctx": 4096, "temperature": 0},
                },
                timeout=httpx.Timeout(120.0),
            )
            ping_resp.raise_for_status()
        except Exception as e:
            return (
                f"\n[RLM] Ollama unreachable at {self.base_url} with model '{self.model_name}': {repr(e)}\n"
                f"  Check: ollama is running, model is pulled, SSH tunnel is active."
            )

        while iteration < self.max_iters:
            iteration += 1

            # Check if the LAST tool call failed — inject guidance if so
            last_tool_failed = False
            last_failed_tool = None
            if self._tool_call_log:
                last_entry = self._tool_call_log[-1]
                if not last_entry.get("result_success"):
                    last_tool_failed = True
                    last_failed_tool = last_entry.get("tool")

            # Build environment summary
            tool_count = len(self._tool_call_log)
            env_summary_lines = [
                f"Iteration: {iteration}/{self.max_iters}",
                f"Tool calls made: {tool_count}",
                f"LLM calls used: {self.llm_call_count}/{self.max_llm_calls}",
                f"Available tools: {', '.join(self._available_tools)}",
            ]
            if self._tool_call_log:
                env_summary_lines.append("Completed steps:")
                for e in self._tool_call_log[-5:]:
                    status = "OK" if e.get("result_success") else "FAIL"
                    env_summary_lines.append(f"  [{status}] {e['tool']}")
            env_summary = "\n".join(env_summary_lines)

            # Build feedback from last iteration
            last_output = ""
            if self.history:
                last_turn = self.history[-1]
                stdout = last_turn.get("stdout", "")
                error = last_turn.get("error", "")
                code = last_turn.get("code", "")
                if stdout or error:
                    stdout_lines = stdout.rstrip().splitlines()
                    if len(stdout_lines) > 15:
                        stdout = "\n".join(stdout_lines[:15]) + f"\n... ({len(stdout_lines)} lines total)"
                    last_output += f"# Previous Code\n```python\n{code}\n```\n"
                if stdout:
                    last_output += f"\n## STDOUT\n{stdout[:3000]}"
                if error:
                    last_output += f"\n## ERROR\n{error[:1500]}"

            # If the last tool failed, append correction guidance
            if last_tool_failed:
                last_output += (
                    "\n\n## TOOL ERROR — DO NOT CALL FINAL\n"
                    f"The tool '{last_failed_tool}' failed. Do NOT call FINAL. "
                    "Retry with a valid tool name from Available tools above."
                )

            loop_guide = None
            if self.history:
                loop_guide = self._detect_loop(self.history[-1].get("code", ""))

            messages, prompt_text = self._build_root_messages(query, env_summary, last_output)

            if loop_guide:
                print(f"  ── Iteration {iteration} ── (loop detected, injecting guidance)")
                last_output += (
                    f"\n## GUIDANCE\n{loop_guide}\n\n"
                    "Do NOT output explanations. Output ONLY raw Python code."
                )
                continue

            print(f"  ── Iteration {iteration} ──")
            raw_response = ""
            try:
                if self._llm_client is None:
                    self._llm_client = httpx.AsyncClient(timeout=300)
                resp = await self._llm_client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model_name,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": config.rlm.temperature,
                            "num_ctx": config.rlm.num_ctx,
                        },
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                msg = data.get("message", {})
                raw_response = msg.get("content", "").strip()
            except Exception as e:
                logger.exception("Root LLM call failed at iteration %d", iteration)
                return f"\n[RLM Error] Root LLM call failed at iteration {iteration}: {repr(e)}"

            code = self._extract_code(raw_response)

            if not code:
                print("    (empty response, retrying)")
                continue

            # Fix missing commas in multi-line call_tool dicts
            fix_applied = _fix_call_tool_dicts(code)
            if fix_applied != code:
                print("    (fixed missing commas)")
                code = fix_applied

            # Pre-validate syntax before exec
            try:
                ast.parse(code)
            except SyntaxError as e:
                print(f"    ✗ Syntax error: {e.msg} (line {e.lineno})")
                last_output += (
                    f"\n## YOUR RAW OUTPUT (last attempt)\n```\n{raw_response}\n```\n"
                    f"\n## SYNTAX ERROR\n{e.msg} (line {e.lineno})\n\n"
                    "Fix the syntax. Each call_tool() on ONE line — do NOT split dicts across lines."
                )
                continue

            print(f"    {_shorten_code(code)}")
            logger.info("RLM iteration %d/%d: %d chars, %d tool calls, %d LLM calls",
                        iteration, self.max_iters, len(code), tool_count, self.llm_call_count)

            env["history"] = [h.get("stdout", "") for h in self.history]
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._exec_code, code, env
            )

            success = result.get("success", False)
            stdout = result.get("stdout", "")
            error = result.get("error", "")
            final_answer = result.get("final_answer")

            self.history.append({
                "iteration": iteration,
                "prompt": prompt_text,
                "code": code,
                "stdout": stdout,
                "error": error,
                "final_answer": final_answer,
                "assistant": f"```python\n{code}\n```",
            })

            if result.get("env"):
                env = result["env"]

            stdout_summary = stdout.rstrip()
            if stdout_summary:
                last_line = stdout_summary.splitlines()[-1][:80]
                print(f"    → {last_line}")
            elif error:
                print(f"    → ERROR: {error.split(chr(10))[0][:100]}")
            else:
                print(f"    → (no output)")

            if final_answer is not None:
                print(f"\n  ✅ RLM finished at iteration {iteration}")
                print(f"  Tool calls: {tool_count}")
                print(f"  Sub-LLM calls: {self.llm_call_count}")
                return str(final_answer)

            if not success:
                print(f"    ⚠ Execution error: {error.split(chr(10))[0][:100]}")

        fallback = env.get("final_answer") or env.get("storage", {}).get("final_answer") or ""
        if fallback:
            return str(fallback)

        return f"\n[RLM] Max iterations ({self.max_iters}) reached. Made {len(self._tool_call_log)} tool calls. See {TOOL_LOG_PATH} for full log."

    def _extract_code(self, content: str) -> str:
        for marker in ["```python", "```py", "```"]:
            start = content.find(marker)
            if start == -1:
                continue
            start = content.find("\n", start) + 1
            end = content.find("```", start)
            if end == -1:
                end = len(content)
            code = content[start:end].strip()
            if code:
                return code

        stripped = content.strip()
        if stripped and ("=" in stripped or "def " in stripped or "import " in stripped
                         or "for " in stripped or "if " in stripped or "FINAL(" in stripped
                         or "llm_query(" in stripped or "call_tool(" in stripped):
            return stripped

        return ""


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list:
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks
