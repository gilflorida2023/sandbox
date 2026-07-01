#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Auto-detect and re-execute with venv Python
_venv_python = Path(__file__).parent / "venv" / "bin" / "python"
if sys.executable != str(_venv_python) and _venv_python.exists():
    os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)

import asyncio
import json
import logging
from typing import Optional
import hashlib
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config import config
from mcp_client import MCPClient
from ollama_client import OllamaClient
from tool_wiki import ToolWiki
from context_manager import ContextManager
from session_log import SessionLogger
from router import QueryRouter
from tunnel_manager import TunnelManager
from embedding_service import EmbeddingService
from vector_store import VectorStore
from knowledge_indexer import KnowledgeIndexer

# Dual-mode system constants
PLAN_MODE = "PLAN"
BUILD_MODE = "BUILD"

# Setup logging to workspace/.session-log with relative path from workspace
log_dir = Path(config.workspace.path) / ".session-log"
log_dir.mkdir(parents=True, exist_ok=True)
root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
handler = logging.FileHandler(str(log_dir / "agent.log"))
handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
))
root.addHandler(handler)
root.setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def _parse_text_tool_calls(content: str) -> list[dict]:
    calls = []
    
    # Try direct JSON parse (single object)
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "name" in data:
            args = data.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            calls.append({"name": data["name"], "arguments": args})
            return calls
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Try parsing as JSON array
    try:
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "name" in item:
                    args = item.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    calls.append({"name": item["name"], "arguments": args})
            if calls:
                return calls
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Extract from markdown code blocks using balanced-brace matching (handles multiline JSON)
    for delim in ['```json', '```']:
        start = content.find(delim)
        if start == -1:
            continue
        start = content.find('\n', start) + 1
        end = content.find('```', start)
        if end == -1:
            end = len(content)
        block = content[start:end]
        idx = 0
        while idx < len(block):
            brace = block.find('{', idx)
            if brace == -1:
                break
            depth = 0
            in_str = False
            esc = False
            for end_idx in range(brace, len(block)):
                ch = block[end_idx]
                if esc:
                    esc = False
                    continue
                if ch == '\\' and in_str:
                    esc = True
                    continue
                if ch == '"' and not esc:
                    in_str = not in_str
                    continue
                if not in_str:
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            try:
                                json_str = block[brace:end_idx + 1]
                                # Model often emits raw newlines where \n escape is needed
                                json_str = json_str.replace('\r\n', '\\n').replace('\r', '\\n').replace('\n', '\\n')
                                data = json.loads(json_str)
                                if isinstance(data, dict) and "name" in data:
                                    args = data.get("arguments", {})
                                    if isinstance(args, str):
                                        args = json.loads(args)
                                    calls.append({"name": data["name"], "arguments": args})
                            except (json.JSONDecodeError, TypeError):
                                pass
                            idx = end_idx + 1
                            break
            else:
                idx = brace + 1
        if calls:
            return calls

    # Fallback: search for embedded JSON object in surrounding text
    start_idx = content.find('{"name":')
    if start_idx == -1:
        start_idx = content.find('{"name" :')
    if start_idx >= 0:
        # Try to find matching closing brace
        depth = 0
        in_str = False
        esc = False
        for end_idx in range(start_idx, len(content)):
            ch = content[end_idx]
            if esc:
                esc = False
                continue
            if ch == '\\' and in_str:
                esc = True
                continue
            if ch == '"' and not esc:
                in_str = not in_str
                continue
            if not in_str:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(content[start_idx:end_idx + 1])
                            if isinstance(data, dict) and "name" in data:
                                args = data.get("arguments", {})
                                if isinstance(args, str):
                                    args = json.loads(args)
                                calls.append({"name": data["name"], "arguments": args})
                                return calls
                        except (json.JSONDecodeError, TypeError):
                            pass
                        break

    return calls


class CodingAgent:
    def __init__(self, session_id: str = "", tunnel_manager: Optional[TunnelManager] = None):
        self.mcp = MCPClient()
        self.ollama = OllamaClient(tunnel_manager=tunnel_manager)
        self.wiki = ToolWiki()

        # Phase 2: Semantic search infrastructure
        vs_path = config.vector_store.storage_path or f"{config.workspace.path}/.context/vectors"
        self.embed_service = EmbeddingService(
            host=config.embedding.host,
            port=config.embedding.port,
            model=config.embedding.model,
        )
        self.vector_store = VectorStore(vs_path, embedding_dim=config.vector_store.embedding_dim)
        self.knowledge_indexer = KnowledgeIndexer(self.embed_service, self.vector_store, self.wiki)
        # Index wiki docs on startup (async-safe, uses synchronous httpx)
        try:
            self.knowledge_indexer.index_wiki(self.wiki)
            logger.info("Wiki indexed: %d chunks in Qdrant", self.knowledge_indexer.wiki_count)
        except Exception as e:
            logger.warning("Failed to index wiki: %s", e)

        self.context = ContextManager(
            self.wiki,
            blacklist=set(config.agent.knowledge.blacklist) if config.agent.knowledge.blacklist else None,
            blacklist_regex=config.agent.knowledge.blacklist_regex or None,
            knowledge_indexer=self.knowledge_indexer,
        )
        self.system_prompt = (Path(__file__).parent / "prompts/system_prompt.txt").read_text()
        self.direct_prompt = (Path(__file__).parent / "prompts/direct_prompt.txt").read_text()
        self.plan_prompt = (Path(__file__).parent / "prompts/plan_prompt.txt").read_text()
        self.router = QueryRouter()
        self.learned_tools = set()
        self.session_id = session_id
        self.session_logger = SessionLogger(
            workspace_path=config.workspace.path,
            ollama_host=config.ollama.host,
            ollama_port=config.ollama.port,
            ollama_model=config.ollama.model,
        )

        # Initialize dual-mode system
        self.current_mode = PLAN_MODE
        self.mode_switch_count = 0
        self.protection_cache = {}
        self.pending_changes = {}
        self.change_log = []
        self.current_user = "system"

        # Knowledge ingestion on startup is disabled by default.
        # Past session logs can contain task-specific noise (e.g. prime sieve code)
        # that contaminates future sessions when injected as "Accumulated Knowledge".
        # Enable via config.knowledge.ingest_on_startup if needed.

    def _build_tool_reference(self, tools: list) -> str:
        lines = ["# Tool Reference Guide", ""]
        for tool in tools:
            name = tool.get("name", "?")
            desc = tool.get("description", "")
            schema = tool.get("input_schema", {})
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            
            lines.append(f"## {name}")
            lines.append(f"{desc}")
            lines.append("")
            lines.append("**Parameters:**")
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "any")
                pdesc = pinfo.get("description", "")
                is_req = "required" if pname in required else f"optional (default: {pinfo.get('default', 'N/A')})"
                lines.append(f"- `{pname}` ({ptype}, {is_req}): {pdesc}")
            
            
            lines.append("")
        
        return "\n".join(lines)

    def _is_dangerous_tool_call(self, func_name: str, func_args: dict) -> bool:
        dangerous_tools = {
            "workspace.write",
            "workspace.delete", 
            "workspace.compile"
        }
        return func_name in dangerous_tools

    @staticmethod
    def _strip_plan_json(text: str) -> str:
        """Remove JSON tool-call patterns from plan text using balanced-brace matching."""
        import re

        def matching_brace(s: str, start: int) -> int:
            depth = 1
            i = start + 1
            while i < len(s) and depth > 0:
                if s[i] == '{':
                    depth += 1
                elif s[i] == '}':
                    depth -= 1
                i += 1
            return i if depth == 0 else -1

        def strip_tool_calls(s: str) -> str:
            result = []
            i = 0
            while i < len(s):
                if s[i] == '{':
                    end = matching_brace(s, i)
                    if end != -1:
                        obj = s[i:end]
                        if '"name"' in obj and '"arguments"' in obj:
                            i = end
                            continue
                result.append(s[i])
                i += 1
            return ''.join(result)

        stripped = strip_tool_calls(text)
        stripped = re.sub(r'```(?:json)?\s*```', '', stripped)
        return stripped.strip()

    @staticmethod
    def _fix_file_escaping(filepath: Path) -> bool:
        """Fix JSON-escaping artifacts in written source files.
        Handles the case where `\\n` inside a string literal became a real newline
        after JSON round-trip (model's tool call -> MCP server).
        Returns True if file was modified."""
        import re
        try:
            source = filepath.read_text()
        except Exception:
            return False

        lines = source.split('\n')
        unclosed_fstring = re.compile(r"(f'[^']*\{[^}]*\})$")
        unclosed_fstring2 = re.compile(r'(f"[^"]*\{[^}]*\})$')
        unclosed_string = re.compile(r"('(?:[^'\\]|\\.)*)$")
        unclosed_string2 = re.compile(r'("(?:[^"\\]|\\.)*)$')

        new_lines = []
        i = 0
        fixed = False
        while i < len(lines):
            if i + 1 >= len(lines):
                new_lines.append(lines[i])
                i += 1
                continue

            m1 = unclosed_fstring.search(lines[i])
            m2 = unclosed_fstring2.search(lines[i])
            if (m1 or m2):
                next_line = lines[i+1].strip()
                if next_line.startswith("')") or next_line.startswith('")'):
                    continuation = next_line[1:]  # strip opening quote
                    combined = lines[i] + '\\n' + continuation
                    new_lines.append(combined)
                    i += 2
                    fixed = True
                    continue

            m3 = unclosed_string.search(lines[i])
            m4 = unclosed_string2.search(lines[i])
            if (m3 or m4):
                next_line = lines[i+1].strip()
                # Line ends with unclosed single/double-quoted string
                # Next line starts with a continuation pattern like + '...' or "
                if next_line.startswith("+ '") or next_line.startswith('+ "') or \
                   next_line.startswith("'") or next_line.startswith('"'):
                    # This might be an intended \n — join
                    pass  # too risky to auto-fix without more context

            new_lines.append(lines[i])
            i += 1

        if fixed:
            source = '\n'.join(new_lines)

        # Balanced-brace fix for C files: if more { than }, append missing }
        if filepath.suffix in ('.c', '.h'):
            in_str = False
            esc = False
            brace_depth = 0
            for ch in source:
                if esc:
                    esc = False
                    continue
                if ch == '\\' and in_str:
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if not in_str:
                    if ch == '{':
                        brace_depth += 1
                    elif ch == '}':
                        brace_depth -= 1
            if brace_depth > 0:
                source += '\n' * brace_depth + '}' * brace_depth
                fixed = True
                logger.info("Auto-fixed %d missing closing brace(s) in %s", brace_depth, filepath)

        if fixed:
            filepath.write_text(source)
            logger.info("Written fix for %s", filepath)
        return fixed

    @staticmethod
    def _write_file_directly(path: str, content: str) -> dict:
        """Write a file to the workspace directly, bypassing MCP's sed-based JSON parsing.
        Returns the same result dict format as workspace.write."""
        workspace_root = Path(config.workspace.path).resolve()
        full_path = (workspace_root / path).resolve()
        # Sandbox check
        if not str(full_path).startswith(str(workspace_root)):
            return {"success": False, "error": "Path outside workspace"}
        
        # Check for dual-mode protection if agent instance is available
        # Note: This is a static method, so we can't access instance methods directly
        # Protection should be applied in the chat method before calling _write_file_directly
        
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            bytes_written = len(content.encode("utf-8"))
            logger.info("Direct write: %s (%d bytes)", path, bytes_written)
            return {"success": True, "path": path, "bytes_written": bytes_written}
        except Exception as e:
            logger.error("Direct write failed: %s", e)
            return {"success": False, "error": str(e)}

    async def switch_mode(self, new_mode: str) -> str:
        """Switch between PLAN_MODE and BUILD_MODE with confirmation.
        
        Args:
            new_mode: Either "PLAN" or "BUILD"
            
        Returns:
            Status message of the mode switch
        """
        valid_modes = ["PLAN", "BUILD"]
        if new_mode.upper() not in valid_modes:
            return f"Invalid mode. Must be one of: {', '.join(valid_modes)}"
        
        old_mode = getattr(self, 'current_mode', PLAN_MODE)
        if old_mode == new_mode.upper():
            return f"Already in {new_mode.upper()} mode"
        
        confirmation = input(f"\nSwitch from {old_mode} mode to {new_mode.upper()} mode? This requires explicit confirmation for all subsequent operations. (y/N): ")
        if confirmation.lower() != 'y':
            return "Mode switch cancelled by user"
        
        # Log mode change
        logger.info(f"Mode switch: {old_mode} → {new_mode.upper()}")
        
        # Update mode state
        self.current_mode = new_mode.upper()
        self.mode_switch_count += 1
        
        # Clear sensitive cache on mode change
        self.protection_cache.clear()
        self.pending_changes.clear()
        
        return f"Mode switched to {new_mode.upper()} successfully"

    async def _requires_authorization(self, func_name: str, func_args: dict) -> bool:
        """Check if a tool call requires explicit authorization based on current mode."""
        if self.current_mode == PLAN_MODE:
            if func_name in ['workspace.write', 'workspace.delete', 'workspace.compile', 'workspace.run']:
                return True
        return False

    async def _confirm_change(self, func_name: str, func_args: dict) -> bool:
        """Get explicit user confirmation for a change in BUILD mode."""
        if self.current_mode != BUILD_MODE:
            return True
            
        if self._is_dangerous_tool_call(func_name, func_args):
            path = func_args.get('path', '')
            content_preview = func_args.get('content', '')[:200] if func_args.get('content') else ''
            
            print(f"\n{'='*60}")
            print(f"BUILD MODE CONFIRMATION REQUIRED")
            print(f"{'='*60}")
            print(f"Tool: {func_name}")
            print(f"Path: {path}")
            if content_preview:
                print(f"Content preview:\n{content_preview}")
            print(f"\nCurrent mode: BUILD (read/write/execute permissions)")
            print(f"\nThis will:")
            if func_name == 'workspace.write':
                print(f"  - Create or overwrite file: {path}")
            elif func_name == 'workspace.delete':
                print(f"  - Delete file/directory: {path}")
            elif func_name == 'workspace.compile':
                print(f"  - Compile source: {path}")
            elif func_name == 'workspace.run':
                print(f"  - Execute: {path}")
            print(f"\nEnter 'y' to approve, or any other key to reject:")
            
            try:
                if not sys.stdin.isatty():
                    return False
                confirmation = input("CONFIRM [y/N]: ").strip().lower()
                return confirmation == 'y'
            except:
                return False
        
        return True

    async def execute_tool_with_protection(self, func_name: str, func_args: dict):
        """Execute a tool call with dual-mode protection."""
        # Check mode restrictions
        if await self._requires_authorization(func_name, func_args):
            if self.current_mode == PLAN_MODE:
                return {
                    "success": False,
                    "error": f"Operation '{func_name}' requires BUILD mode (currently in PLAN mode)",
                    "mode_restriction": True,
                    "suggestion": "Press Tab in the REPL to switch to BUILD mode, or perform this analysis in PLAN mode only."
                }
        
        # Get user confirmation for dangerous operations in BUILD mode
        if self.current_mode == BUILD_MODE and await self._confirm_change(func_name, func_args):
            try:
                # Log the attempt
                logger.info(f"Change approved: {func_name}({func_args.get('path', '')})")
                
                # Execute the tool
                if func_name == "workspace.write":
                    result = self._write_file_directly(func_args["path"], func_args["content"])
                    if result.get("success"):
                        filepath = Path(config.workspace.path) / func_args["path"]
                        self._fix_file_escaping(filepath)
                else:
                    result = await self.mcp.call_tool(func_name, func_args)
                
                # Record successful change
                if result.get("success"):
                    self._record_change(func_name, func_args, "approved")
                
                return result
            except Exception as e:
                logger.error(f"Tool {func_name} failed: {e}")
                return {
                    "success": False,
                    "error": str(e)
                }
        
        elif self.current_mode == BUILD_MODE:
            logger.info(f"Change rejected: {func_name}")
            return {
                "success": False,
                "error": f"User rejected change for '{func_name}'",
                "user_rejected": True
            }
        
        else:
            # In PLAN mode but not requiring authorization
            return await self.mcp.call_tool(func_name, func_args)

    def _record_change(self, func_name: str, func_args: dict, status: str):
        """Record a change for audit purposes."""
        if not hasattr(self, 'change_log'):
            self.change_log = []
        
        change_record = {
            "timestamp": time.time(),
            "mode": self.current_mode,
            "func_name": func_name,
            "path": func_args.get('path', ''),
            "status": status,
            "user": "system",
        }
        
        if func_name == 'workspace.write':
            change_record["content_hash"] = hashlib.sha256(
                func_args.get('content', '').encode()
            ).hexdigest()[:16]
        
        self.change_log.append(change_record)
        
        # Persist change log periodically
        if len(self.change_log) % 10 == 0:
            self.persist_change_log()

    def persist_change_log(self):
        """Persist the change log to the workspace for audit purposes."""
        if not hasattr(self, 'change_log') or not self.change_log:
            return
        
        import json
        log_path = Path(config.workspace.path) / "dual-mode-change-log.json"
        
        try:
            existing_data = []
            if log_path.exists():
                existing_data = json.loads(log_path.read_text())
            
            # Append new changes
            existing_data.extend(self.change_log)
            
            # Keep only last 1000 entries to prevent log bloat
            if len(existing_data) > 1000:
                existing_data = existing_data[-1000:]
            
            log_path.write_text(json.dumps(existing_data, indent=2))
            logger.info(f"Change log persisted to {log_path} ({len(self.change_log)} entries)")
        except Exception as e:
            logger.error(f"Failed to persist change log: {e}")

    def _format_output(self, plan: str, tool_log: list, final_content: str) -> str:
        parts = [f"── Phase 1: Plan ──────────────────────────────", plan, ""]
        if tool_log:
            parts.append("── Phase 2: Execution ──────────────────────────")
            parts.extend(tool_log)
            parts.append("")
        if final_content:
            parts.append(final_content)
        return "\n".join(parts)

    async def run(self, task: str) -> str:
        logger.info(f"Starting task: {task}")
        route = self.router.classify(task)

        if route == "direct":
            msgs = [
                {"role": "system", "content": self.direct_prompt},
                {"role": "user", "content": task},
            ]
            response = await self.ollama.chat(msgs, [])
            content = response.get("message", {}).get("content", "") or ""
            return content

        # Tool route — Phase 1: Plan
        plan_msgs = [
            {"role": "system", "content": self.plan_prompt},
            {"role": "user", "content": task},
        ]
        plan_resp = await self.ollama.chat(plan_msgs, [])
        plan = self._strip_plan_json(plan_resp.get("message", {}).get("content", "") or "")

        # Phase 2: Execute
        try:
            tools = await self.mcp.list_tools()
        except Exception as e:
            logger.error("Failed to list MCP tools: %s", e)
            return f"MCP tools server is not running on port 8080.\n\n{plan}"
        tool_schemas = []
        tool_defs = []
        ref_tools = []
        for tool in tools:
            if "input_schema" in tool:
                tool_schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"]
                    }
                })
                if tool["name"].startswith(("workspace.", "wiki.")):
                    params = tool["input_schema"].get("properties", {})
                    param_str = " ".join(f"<{n}>" for n in params.keys())
                    if param_str:
                        param_str = " " + param_str
                    tool_defs.append(f"- **{tool['name']}**: {tool['description']}{param_str}")
                    ref_tools.append(tool)

        tool_ref = self._build_tool_reference(ref_tools)
        system_prompt = self.system_prompt.replace("{TOOL_DEFINITIONS}", "\n".join(tool_defs))

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"## Detailed Tool Reference\n\n{tool_ref}"},
        ]

        if plan:
            messages.append({"role": "system", "content": f"## Plan\n{plan}\n\nExecute this plan using the workspace tools."})

        wiki_context = self.context.get_relevant_context(task, max_tokens=config.agent.max_context_tokens)
        if wiki_context:
            messages.insert(1, {"role": "system", "content": f"## Reference Documentation\n\n{wiki_context}"})

        kb_window = self.context.get_knowledge_window(max_tokens=config.agent.max_context_tokens // 2)
        if kb_window:
            messages.insert(1, {"role": "system", "content": f"## Accumulated Knowledge\n\n{kb_window}"})

        if self.session_id:
            ctx_path = Path(config.context.path) if hasattr(config, 'context') and config.context.path else Path(config.workspace.path) / ".context"
            blob_file = ctx_path / self.session_id / "context-blob.md"
            if blob_file.exists():
                blob = blob_file.read_text()
                messages.insert(1, {"role": "system", "content": f"## Codebase Context\n\n{blob}"})
                logger.info("Injected context blob from %s", blob_file)

        messages.append({"role": "user", "content": task})
        tool_log = []

        for turn in range(config.agent.max_turns):
            logger.info(f"Turn {turn + 1}/{config.agent.max_turns}")

            try:
                response = await self.ollama.chat(messages, tool_schemas)
            except Exception as e:
                logger.error(f"Ollama error: {e}")
                return f"Error communicating with Ollama: {e}"

            done_reason = response.get("done_reason", "")
            if done_reason == "length":
                logger.warning(f"Response truncated due to context limit (turn {turn + 1})")

            message = response.get("message", {})
            content = message.get("content", "") or ""
            thinking = message.get("thinking", "")
            tool_calls = message.get("tool_calls", [])

            if not content and thinking:
                content = thinking

            if not content and not tool_calls:
                logger.warning(f"Empty response: {json.dumps(response)[:500]}")
            elif content:
                logger.debug(f"Model content: {content[:300]}")
            if tool_calls:
                logger.info(f"Tool calls: {[tc['function']['name'] for tc in tool_calls]}")

            parsed_tc = False
            if not tool_calls and content:
                parsed_list = _parse_text_tool_calls(content)
                if parsed_list:
                    parsed_tc = True
                    tool_calls = [{
                        "function": {
                            "name": p["name"],
                            "arguments": json.dumps(p["arguments"]) if isinstance(p.get("arguments"), dict) else "{}"
                        },
                        "id": f"text_tc_{i}"
                    } for i, p in enumerate(parsed_list)]
                else:
                    logger.warning("No text-parsed tool calls in %d chars (run)", len(content))

            if content:
                msg = {"role": "assistant", "content": content}
                if tool_calls and not parsed_tc:
                    msg["tool_calls"] = tool_calls
                messages.append(msg)
                self.context.add_message("assistant", content, tool_calls)

            if not tool_calls:
                if not tool_log and (not content or len(content) < 20) and turn == 0:
                    logger.info("Phase 2 returned empty in run() — retrying with tool prompt")
                    messages.append({"role": "user", "content": "Use the workspace tools to complete your plan step by step. Call one tool at a time."})
                    continue
                logger.info("No tool calls - task complete")
                return self._format_output(plan, tool_log, content)

            for tc in tool_calls:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]

                if isinstance(func_args, str):
                    func_args = json.loads(func_args)

                # Per-tool wiki auto-injection removed: it burned context tokens
                # on docs the model didn't ask for. The model can call wiki.lookup
                # on demand if it needs documentation for a tool.

                logger.info(f"Executing: {func_name}({func_args})")

                try:
                    if func_name == "workspace.write":
                        result = self._write_file_directly(func_args["path"], func_args["content"])
                        if result.get("success"):
                            filepath = Path(config.workspace.path) / func_args["path"]
                            self._fix_file_escaping(filepath)
                    else:
                        result = await self.mcp.call_tool(func_name, func_args)
                    result_str = json.dumps(result)
                    logger.info(f"Result: {result_str[:500]}")
                    messages.append({
                        "role": "user",
                        "content": f"Result of {func_name}: {result_str}\n\nIf the task is not complete, output your next tool call as a JSON code block.",
                    })
                    self.context.add_message("tool", result_str, tool_call_id=tc.get("id", ""))
                    tool_log.append(f"[{func_name}] {result_str[:400]}")
                except Exception as e:
                    error_msg = f"Tool {func_name} failed: {e}"
                    logger.error(error_msg)
                    messages.append({
                        "role": "user",
                        "content": f"Result of {func_name}: " + json.dumps({"success": False, "error": str(e)}) + "\n\nIf the task is not complete, output your next tool call as a JSON code block.",
                    })
                    tool_log.append(f"[{func_name}] FAILED: {e}")

        if tool_calls:
            logger.info("Running final summary turn")
            try:
                response = await self.ollama.chat(messages)
                message = response.get("message", {})
                content = message.get("content", "") or ""
                thinking = message.get("thinking", "")
                if not content and thinking:
                    content = thinking
                if content:
                    return self._format_output(plan, tool_log, content)
            except Exception as e:
                logger.error(f"Final turn error: {e}")

        return "Max turns reached without completion"

    async def build_preamble(self) -> tuple[list, list]:
        """Fetch tools, build system prompt + schemas. Call once per session.
        Returns (messages, tool_schemas)."""
        tools = await self.mcp.list_tools()
        tool_schemas = []
        tool_defs = []
        ref_tools = []
        for tool in tools:
            if "input_schema" in tool:
                tool_schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                })
                if tool["name"].startswith(("workspace.", "wiki.")):
                    params = tool["input_schema"].get("properties", {})
                    param_str = " ".join(f"<{n}>" for n in params.keys())
                    if param_str:
                        param_str = " " + param_str
                    tool_defs.append(
                        f"- **{tool['name']}**: {tool['description']}{param_str}"
                    )
                    ref_tools.append(tool)

        tool_ref = self._build_tool_reference(ref_tools)
        system_prompt = self.system_prompt.replace(
            "{TOOL_DEFINITIONS}", "\n".join(tool_defs)
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"## Detailed Tool Reference\n\n{tool_ref}"},
        ]

        # Inject accumulated knowledge window (token-bounded)
        kb_window = self.context.get_knowledge_window(max_tokens=config.agent.max_context_tokens // 2)
        if kb_window:
            messages.append(
                {"role": "system", "content": f"## Accumulated Knowledge\n\n{kb_window}"}
            )

        if self.session_id:
            ctx_path = (
                Path(config.context.path)
                if hasattr(config, "context") and config.context.path
                else Path(config.workspace.path) / ".context"
            )
            blob_file = ctx_path / self.session_id / "context-blob.md"
            if blob_file.exists():
                blob = blob_file.read_text()
                messages.insert(
                    1, {"role": "system", "content": f"## Codebase Context\n\n{blob}"}
                )
                logger.info("Injected context blob from %s", blob_file)

        return messages, tool_schemas

    async def chat(
        self,
        user_input: str,
        messages: list | None = None,
        tool_schemas: list | None = None,
    ) -> tuple[str, list]:
        """Single user turn. Returns (response_text, updated_messages)."""
        route = self.router.classify(user_input)

        if route == "direct":
            msgs = [
                {"role": "system", "content": self.direct_prompt},
                {"role": "user", "content": user_input},
            ]
            response = await self.ollama.chat(msgs, [])
            content = response.get("message", {}).get("content", "") or ""
            return content, msgs

        # Tool route — Phase 1: Plan
        plan_msgs = [
            {"role": "system", "content": self.plan_prompt},
            {"role": "user", "content": user_input},
        ]
        plan_resp = await self.ollama.chat(plan_msgs, [])
        plan = self._strip_plan_json(plan_resp.get("message", {}).get("content", "") or "")

        # Phase 2: Execute
        if messages is None:
            try:
                messages, tool_schemas = await self.build_preamble()
            except Exception as e:
                logger.error("Failed to build tool preamble: %s", e)
                return f"MCP tools server is not running (port 8080). Workspace tools unavailable.\n\n{plan}", []

        if plan:
            messages.append({"role": "system", "content": f"## Plan\n{plan}\n\nExecute this plan using the workspace tools."})

        wiki_context = self.context.get_relevant_context(user_input, max_tokens=config.agent.max_context_tokens)
        if wiki_context:
            messages.append({"role": "system", "content": f"## Reference Documentation\n\n{wiki_context}"})

        kb_window = self.context.get_knowledge_window(max_tokens=config.agent.max_context_tokens // 2)
        if kb_window:
            messages.append({"role": "system", "content": f"## Accumulated Knowledge\n\n{kb_window}"})

        messages.append({"role": "user", "content": user_input})
        tool_log = []

        for turn in range(config.agent.max_turns):
            logger.info("Turn %d/%d", turn + 1, config.agent.max_turns)

            try:
                response = await self.ollama.chat(messages, tool_schemas)
            except Exception as e:
                logger.error("Ollama error: %s", e)
                return f"Error communicating with Ollama: {e}", messages

            done_reason = response.get("done_reason", "")
            if done_reason == "length":
                logger.warning("Response truncated due to context limit (turn %d)", turn + 1)

            message = response.get("message", {})
            content = message.get("content", "") or ""
            thinking = message.get("thinking", "")
            tool_calls = message.get("tool_calls", [])

            if not content and thinking:
                content = thinking

            if not content and not tool_calls:
                logger.warning("Empty response")
            elif content:
                logger.debug("Model content: %s", content[:300])
            if tool_calls:
                logger.info("Tool calls: %s", [tc["function"]["name"] for tc in tool_calls])

            parsed_tc = False
            if not tool_calls and content:
                parsed_list = _parse_text_tool_calls(content)
                if parsed_list:
                    parsed_tc = True
                    tool_calls = [{
                        "function": {
                            "name": p["name"],
                            "arguments": json.dumps(p["arguments"]) if isinstance(p.get("arguments"), dict) else "{}",
                        },
                        "id": f"text_tc_{i}",
                    } for i, p in enumerate(parsed_list)]
                else:
                    logger.warning("No text-parsed tool calls in %d chars (chat)", len(content))

            if content:
                msg = {"role": "assistant", "content": content}
                if tool_calls and not parsed_tc:
                    msg["tool_calls"] = tool_calls
                messages.append(msg)
                self.context.add_message("assistant", content, tool_calls)

            if not tool_calls:
                if not tool_log and (not content or len(content) < 20) and turn == 0:
                    logger.info("Phase 2 returned empty — retrying with tool prompt")
                    messages.append({"role": "user", "content": "Use the workspace tools to complete your plan step by step. Call one tool at a time."})
                    continue
                logger.info("No tool calls — responding")
                formatted = self._format_output(plan, tool_log, content)
                return formatted, messages

            for tc in tool_calls:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]
                if isinstance(func_args, str):
                    func_args = json.loads(func_args)

                # Per-tool wiki auto-injection removed: the model can call
                # wiki.lookup on demand if it needs documentation.

                logger.info("Executing: %s(%s)", func_name, func_args)
                try:
                    result = await self.execute_tool_with_protection(func_name, func_args)
                    # Auto-switch to BUILD mode if blocked by mode restriction
                    if result.get("mode_restriction"):
                        logger.info("Auto-switching to BUILD mode for tool execution")
                        self.current_mode = BUILD_MODE
                        result = await self.execute_tool_with_protection(func_name, func_args)
                    result_str = json.dumps(result)
                    messages.append({
                        "role": "user",
                        "content": f"Result of {func_name}: {result_str}\n\nIf the task is not complete, output your next tool call as a JSON code block.",
                    })
                    self.context.add_message("tool", result_str, tool_call_id=tc.get("id", ""))
                    tool_log.append(f"[{func_name}] {result_str[:400]}")
                except Exception as e:
                    error_msg = f"Tool {func_name} failed: {e}"
                    logger.error(error_msg)
                    messages.append({
                        "role": "user",
                        "content": f"Result of {func_name}: " + json.dumps({"success": False, "error": str(e)}) + "\n\nIf the task is not complete, output your next tool call as a JSON code block.",
                        "tool_call_id": tc.get("id", ""),
                    })
                    tool_log.append(f"[{func_name}] FAILED: {e}")

        if tool_calls:
            logger.info("Running final summary turn")
            try:
                response = await self.ollama.chat(messages)
                message = response.get("message", {})
                content = message.get("content", "") or ""
                thinking = message.get("thinking", "")
                if not content and thinking:
                    content = thinking
                if content:
                    formatted = self._format_output(plan, tool_log, content)
                    return formatted, messages
            except Exception as e:
                logger.error("Final turn error: %s", e)

        return "Max turns reached without completion", messages

    async def close(self):
        await self.mcp.close()
        await self.ollama.close()
        self.knowledge_indexer.close()


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Coding agent with pipeline integration")
    parser.add_argument("task", nargs="?", help="Task description")
    parser.add_argument("--session-id", help="Session ID from pipeline run")
    parser.add_argument("--workflow", help="Run a pipeline workflow first (e.g. context_load)")
    args = parser.parse_args()

    task = args.task
    if not task and sys.stdin.isatty():
        parser.print_help()
        sys.exit(1)
    if not task:
        task = sys.stdin.read().strip()

    # Optionally run a pipeline workflow first
    if args.workflow:
        sys.path.insert(0, str(Path(__file__).parent))
        from workflows import get_workflow
        pipe = get_workflow(args.workflow)
        try:
            pipe_result = await pipe.run(task, session_id=args.session_id)
            session_id = pipe_result.get("session_id", args.session_id or "")
            logger.info("Pipeline '%s' complete (session %s)", args.workflow, session_id)
            args.session_id = session_id  # pass through to agent
        finally:
            await pipe.close()

    agent = CodingAgent(session_id=args.session_id or "")
    
    try:
        result = await agent.run(task)
        print("\n" + "="*60)
        print("RESULT:")
        print("="*60)
        print(result)
        
        # Log session knowledge
        log_result = agent.session_logger.log_session(
            agent.context.history, task
        )
        if log_result.get("cached"):
            print(f"\nSession already logged (dedup match): {log_result['output_file']}")
        else:
            print(f"\nSession knowledge written to: {log_result['output_file']}")
            extraction = log_result.get("extraction")
            if extraction:
                print(f"  Decisions: {len(extraction.decisions)}")
                print(f"  Roadblocks: {len(extraction.questions)}")
                print(f"  Action Items: {len(extraction.action_items)}")
                print(f"  Ideas: {len(extraction.ideas)}")
            files = log_result.get("files_touched", [])
            if files:
                print(f"  Files touched: {len(files)}")

        # Ingest session log via approval gate
        out_file = log_result.get("output_file")
        if out_file:
            proposed = agent.context.ingest_session_log(out_file)
            pending = agent.context.approval.pending_count()
            approved = len(agent.context.approval.approved)
            print(f"  Knowledge chunks proposed: {proposed} (pending: {pending}, approved: {approved})")
            if config.agent.knowledge.require_user_approval and pending > 0:
                print(f"  Use /pending in the REPL to review, /approve <id> or /reject <id> to decide")
        agent.context.persist_knowledge()
        print(f"  Total knowledge chunks stored: {agent.context.knowledge.count()}")
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())

# Export key symbols for testing
__all__ = [
    'CodingAgent',
    'PLAN_MODE',
    'BUILD_MODE',
    'switch_mode',
    'execute_tool_with_protection',
    '_requires_authorization',
    '_confirm_change',
    '_record_change',
]