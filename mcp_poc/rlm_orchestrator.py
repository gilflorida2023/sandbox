import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from config import config
from ollama_client import OllamaClient
from todo_list import TodoItem, TodoList
from stats_collector import StatsCollector, TurnStats
from rlm_logger import RlmLogger

logger = logging.getLogger(__name__)


@dataclass
class Observations:
    decisions: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    discoveries: List[str] = field(default_factory=list)
    sub_todos: List[str] = field(default_factory=list)
    files_touched: List[str] = field(default_factory=list)
    is_complete: bool = False


OBSERVATION_SYSTEM_PROMPT = """You are in a Recursive Language Model (RLM) loop. You are working through a todo list.

## Instructions
- Focus on the current active todo.
- After your response, include an ## Observations section with:
  - decision: Any design decisions you made
  - discovery: New information you found
  - blocker: Anything blocking progress
  - subtodo: New sub-tasks you identified
  - complete: "yes" if the current todo is done, "no" otherwise
  - file: Any files you created or modified

## Todo List
{todo_text}

## Current Active Todo
{current_todo}
"""


class RlmOrchestrator:
    def __init__(self, ollama: OllamaClient, todo_list: TodoList,
                 stats_collector: StatsCollector,
                 embed_service=None, vector_store=None,
                 rlm_logger: Optional[RlmLogger] = None,
                 mcp_client=None):
        self.ollama = ollama
        self.todo_list = todo_list
        self.stats = stats_collector
        self.embed_service = embed_service
        self.vector_store = vector_store
        self.rlm_logger = rlm_logger
        self.mcp_client = mcp_client
        self._last_tool_calls: list[str] = []
        self._loop_count = 0

    async def run_turn(self, user_input: str, session_id: str,
                       system_prompt: str = "",
                       context_messages: Optional[List[dict]] = None,
                       use_obs_prompt: bool = True) -> Tuple[str, str, TurnStats, list]:
        todo = self.todo_list.pick_next()
        todo_id = todo.id if todo else ""

        messages = self._build_messages(todo, user_input, session_id,
                                        system_prompt, context_messages, use_obs_prompt)

        start = time.monotonic_ns()
        content, thinking, raw_stats = await self.ollama.chat_with_stats(messages)

        obs = self._parse_observations(content)

        if todo:
            self._apply_observations(obs, todo, session_id)

        # Content-type classification
        content_type = self._classify_content_type(content)
        tool_calls_attempted = self._count_tool_call_blobs(content)
        tool_call_names = self._extract_tool_call_names(content)
        # Extract full tool call objects for execution
        tool_calls = self._extract_tool_calls(content)

        # Tool-spam detection
        if tool_call_names == self._last_tool_calls and tool_call_names:
            self._loop_count += 1
        else:
            self._loop_count = 0
        self._last_tool_calls = tool_call_names

        # Execute tool calls via MCP client if available
        tool_calls_executed = 0
        tool_calls_failed = 0
        if tool_calls and self.mcp_client:
            # Append the assistant content to messages so the LLM sees its own output
            messages.append({"role": "assistant", "content": content})

            for tc in tool_calls:
                func_name = tc["name"]
                func_args = tc.get("arguments", {})
                logger.info("RLM executing: %s(%s)", func_name, func_args)

                try:
                    result = await self.mcp_client.call_tool(func_name, func_args)
                    result_str = json.dumps(result)
                    logger.info("RLM tool result: %s", result_str[:300])
                    messages.append({
                        "role": "tool",
                        "content": f"Result of {func_name}: {result_str}\n\nIf the task is not complete, output your next tool call as a JSON code block.",
                        "tool_call_id": f"rlm_tc_{tool_calls_executed + tool_calls_failed}",
                    })
                    if result.get("success"):
                        tool_calls_executed += 1
                    else:
                        tool_calls_failed += 1
                except Exception as e:
                    logger.error("RLM tool %s failed: %s", func_name, e)
                    messages.append({
                        "role": "tool",
                        "content": f"Result of {func_name}: " + json.dumps({"success": False, "error": str(e)}) + "\n\nIf the task is not complete, output your next tool call as a JSON code block.",
                        "tool_call_id": f"rlm_tc_{tool_calls_executed + tool_calls_failed}",
                    })
                    tool_calls_failed += 1

            # Follow-up LLM call with tool results
            try:
                content, thinking, followup_stats = await self.ollama.chat_with_stats(messages)
                raw_stats["prompt_tokens"] = raw_stats.get("prompt_tokens", 0) + followup_stats.get("prompt_tokens", 0)
                raw_stats["completion_tokens"] = raw_stats.get("completion_tokens", 0) + followup_stats.get("completion_tokens", 0)
                # Re-parse observations from the follow-up response
                obs = self._parse_observations(content)
                if todo:
                    self._apply_observations(obs, todo, session_id)
            except Exception as e:
                logger.error("RLM follow-up LLM call failed: %s", e)

        duration_ns = time.monotonic_ns() - start
        response_preview = content[:120] if content else ""

        # Re-compute context stats after tool execution
        used = sum(len(json.dumps(m)) for m in messages)
        budget = self._estimate_context_budget(messages)

        turn_stats = TurnStats(
            turn_number=self.stats.total_turns + 1,
            todo_id=todo_id,
            prompt_tokens=raw_stats.get("prompt_tokens", 0),
            completion_tokens=raw_stats.get("completion_tokens", 0),
            thinking=thinking,
            context_budget=budget,
            context_used=used,
            truncated=False,
            self_references=self._count_self_references(content, messages),
            clarification_requests=self._count_clarifications(content),
            duration_ns=duration_ns,
            embedding_calls=self.embed_service.call_count if self.embed_service else 0,
            tool_calls_attempted=tool_calls_attempted,
            tool_calls_executed=tool_calls_executed,
            tool_calls_failed=tool_calls_failed,
            content_type=content_type,
            loop_count=self._loop_count,
            response_preview=response_preview,
            context_util_pct=round((used / budget) * 100, 1) if budget > 0 else 0.0,
        )
        self.stats.record_turn(turn_stats)

        # Structured logging
        if self.rlm_logger:
            self.rlm_logger.turn(
                turn_stats=turn_stats,
                content_type=content_type,
                tool_calls_attempted=tool_calls_attempted,
                tool_calls_executed=tool_calls_executed,
                tool_calls_failed=tool_calls_failed,
                loop_count=self._loop_count,
                response_preview=response_preview,
                session_id=session_id,
            )
            if obs.is_complete and todo:
                self.rlm_logger.todo_event(
                    action="completed",
                    todo_id=todo.id,
                    description=todo.description,
                    parent_id=todo.parent_id,
                    turn_number=turn_stats.turn_number,
                    session_id=session_id,
                )

        # Warning for tool-spam (3+ identical consecutive tool calls)
        if self._loop_count >= 3:
            logger.warning(
                "RLM tool-spam detected: %d consecutive identical tool calls [%s] on todo %s",
                self._loop_count, ", ".join(tool_call_names[:3]), todo_id[:8],
            )

        # Warning for empty responses (3+ consecutive empty responses not practical here,
        # but we can warn on individual empty)
        if content_type == "empty":
            logger.warning("RLM turn %d: empty response from model on todo %s",
                           turn_stats.turn_number, todo_id[:8])

        return content, thinking, turn_stats, tool_calls

    async def plan_task(self, task: str, session_id: str,
                        system_prompt: str = "") -> tuple[list[dict], str, str]:
        """Send a task to the LLM and extract steps from its natural response.

        Returns:
            (steps, thinking, raw_content)
            where steps is a list of dicts with keys: step_number, description, has_code, issues
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": task})

        content, thinking, _ = await self.ollama.chat_with_stats(messages)
        steps = self._extract_steps(content)
        return steps, thinking, content

    def _extract_steps(self, content: str) -> list[dict]:
        """Parse natural LLM output into actionable steps.

        Extracts numbered lists, code blocks, and potential issues.
        Returns a list of dicts with: step_number, description, has_code, issues
        """
        if not content:
            return []

        steps = []
        code_blocks = self._extract_code_blocks(content)

        lines = content.split("\n")
        current_step = None
        in_troubleshooting = False
        troubleshooting_blocks: list[str] = []

        for line in lines:
            stripped = line.strip()

            # Detect troubleshooting/Common Issues sections
            lower = stripped.lower()
            if any(w in lower for w in ("troubleshooting", "common issue", "potential issue",
                                         "note:", "if you", "if the", "fix:")):
                in_troubleshooting = True
                troubleshooting_blocks.append(stripped)
                continue
            if in_troubleshooting:
                if stripped and not stripped.startswith(("#", "```")):
                    troubleshooting_blocks.append(stripped)
                    continue
                else:
                    in_troubleshooting = False

            # Match numbered steps: "1. Do something" or "1) Do something"
            numbered = re.match(r"^\s*(\d+)[.)]\s+(.*)", stripped)
            if numbered:
                num = int(numbered.group(1))
                desc = numbered.group(2).strip()

                # Check if this step references a code block
                has_code = False
                for cb in code_blocks:
                    if any(word in cb for word in desc.lower().split()[:5]):
                        has_code = True
                        break

                steps.append({
                    "step_number": num,
                    "description": desc,
                    "has_code": has_code,
                    "issues": list(troubleshooting_blocks),
                })
                troubleshooting_blocks = []
                continue

            # Match markdown checklist items
            checklist = re.match(r"^[-*]\s*\[\s*[ x]?\s*\]\s*(.*)", stripped)
            if checklist:
                desc = checklist.group(1).strip()
                steps.append({
                    "step_number": len(steps) + 1,
                    "description": desc,
                    "has_code": False,
                    "issues": list(troubleshooting_blocks),
                })
                troubleshooting_blocks = []
                continue

            # Lines starting with ## headings — check for Troubleshooting
            if stripped.startswith("##"):
                section_name = stripped.lstrip("#").strip().lower()
                if any(w in section_name for w in ("troubleshoot", "common issue", "potential issue",
                                                     "error", "problem", "faq")):
                    in_troubleshooting = True

        # Attach code blocks to nearest steps
        if code_blocks and steps:
            for cb in code_blocks:
                # Assign to the last step that doesn't already have this code
                for step in reversed(steps):
                    if not any(cb in s.get("code_block", "") for s in steps):
                        step["code_block"] = cb
                        break

        return steps

    def _extract_code_blocks(self, content: str) -> list[str]:
        """Extract fenced code blocks from content."""
        blocks = []
        idx = 0
        while True:
            start = content.find("```", idx)
            if start == -1:
                break
            end = content.find("```", start + 3)
            if end == -1:
                break
            block = content[start + 3:end].strip()
            # Remove optional language tag from first line
            first_newline = block.find("\n")
            if first_newline != -1:
                block = block[first_newline + 1:].strip()
            if block:
                blocks.append(block)
            idx = end + 3
        return blocks

    async def decompose_task(self, task: str, session_id: str) -> List[TodoItem]:
        prompt = (
            f"Break this task into a numbered todo list of concrete, actionable steps. "
            f"Each step should be a single clear goal (e.g., 'Create config.py', not 'Setup').\n\n"
            f"Task: {task}\n\n"
            f"Output each step on its own line starting with '- [ ] '"
        )
        messages = [
            {"role": "system", "content": "You are a task decomposition assistant."},
            {"role": "user", "content": prompt},
        ]
        content, thinking, _ = await self.ollama.chat_with_stats(messages)
        todos = self._parse_todo_list(content)
        created = []
        for desc in todos:
            item = self.todo_list.create_todo(desc, session_id)
            created.append(item)
        return created

    def _build_messages(self, todo: Optional[TodoItem], user_input: str,
                        session_id: str, system_prompt: str,
                        context_messages: Optional[List[dict]],
                        use_obs_prompt: bool = True) -> List[dict]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if use_obs_prompt and todo:
            current_todo_desc = todo.description
            todo_text = self.todo_list.todo_text(session_id) or ""
            obs_prompt = OBSERVATION_SYSTEM_PROMPT.format(
                todo_text=todo_text or "(empty)",
                current_todo=current_todo_desc,
            )
            messages.append({"role": "system", "content": obs_prompt})

        if context_messages:
            messages.extend(context_messages)

        messages.append({"role": "user", "content": user_input})
        return messages

    def _parse_observations(self, content: str) -> Observations:
        obs = Observations()
        block = self._extract_observation_block(content)
        if block:
            for line in block.split("\n"):
                line = line.strip()
                stripped = re.sub(r"^[-*]\s*", "", line)
                if stripped.lower().startswith("decision:"):
                    obs.decisions.append(stripped[len("decision:"):].strip())
                elif stripped.lower().startswith("discovery:"):
                    obs.discoveries.append(stripped[len("discovery:"):].strip())
                elif stripped.lower().startswith("blocker:"):
                    obs.blockers.append(stripped[len("blocker:"):].strip())
                elif stripped.lower().startswith("subtodo:"):
                    obs.sub_todos.append(stripped[len("subtodo:"):].strip())
                elif stripped.lower().startswith("file:"):
                    obs.files_touched.append(stripped[len("file:"):].strip())
                elif stripped.lower().startswith("complete:"):
                    val = stripped[len("complete:"):].strip().lower()
                    obs.is_complete = val in ("yes", "true", "done", "y")
        else:
            for line in content.split("\n"):
                lower = line.lower()
                if any(w in lower for w in ("decided", "chose", "using")):
                    obs.decisions.append(line.strip("- ").strip())
                if any(w in lower for w in ("blocked", "blocker", "needs", "requires")):
                    obs.blockers.append(line.strip("- ").strip())
                if any(w in lower for w in ("found", "discovered", "note:")):
                    obs.discoveries.append(line.strip("- ").strip())
                if any(w in lower for w in ("next", "also need", "todo:", "subtask")):
                    obs.sub_todos.append(line.strip("- ").strip())
                if any(w in lower for w in ("done", "complete", "finished")):
                    obs.is_complete = True
        return obs

    def _extract_observation_block(self, content: str) -> Optional[str]:
        idx = content.find("## Observations")
        if idx == -1:
            idx = content.find("## observations")
        if idx == -1:
            idx = content.find("Observations:")
        if idx == -1:
            return None
        block = content[idx:]
        next_heading = re.search(r"\n##\s", block[15:])
        if next_heading:
            return block[:15 + next_heading.start()]
        return block

    def _apply_observations(self, obs: Observations, todo: TodoItem, session_id: str):
        self.todo_list.increment_iteration(todo.id)

        if obs.is_complete:
            self.todo_list.update_status(todo.id, "completed")
            logger.info("Todo %s marked complete", todo.id[:8])

        for sub in obs.sub_todos:
            self.todo_list.create_todo(sub, session_id, parent_id=todo.id)
            logger.info("Created sub-todo: %s", sub[:60])

        for disc in obs.discoveries:
            if self.vector_store and self.embed_service:
                try:
                    vec = self.embed_service.embed(disc)
                    if vec:
                        doc_id = self.vector_store.store(
                            text=disc,
                            source=f"rlm:{session_id}",
                            vector=vec,
                        )
                        self.todo_list.add_discovery(todo.id, doc_id)
                        logger.info("Stored discovery: %s", disc[:60])
                except Exception as e:
                    logger.warning("Failed to persist discovery: %s", e)

    def _parse_todo_list(self, content: str) -> List[str]:
        todos = []
        for line in content.split("\n"):
            stripped = line.strip()
            match = re.match(r"^[-*]\s*\[\s*[ x]?\s*\]\s*(.*)", stripped)
            if match:
                todo_text = match.group(1).strip()
                if todo_text:
                    todos.append(todo_text)
            elif stripped and not stripped.startswith(("#", "```", "Output", "Task")):
                numbered = re.match(r"^\d+[.)]\s*(.*)", stripped)
                if numbered:
                    todos.append(numbered.group(1).strip())
        return todos

    def _estimate_context_budget(self, messages: List[dict]) -> int:
        total_chars = sum(len(json.dumps(m)) for m in messages)
        return total_chars // 4

    def _count_self_references(self, content: str, messages: List[dict]) -> int:
        prior_terms = set()
        for m in messages[:-1]:
            text = m.get("content", "")
            words = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', text))
            prior_terms.update(words)
        output_terms = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', content))
        overlaps = prior_terms & output_terms
        return len(overlaps)

    def _count_clarifications(self, content: str) -> int:
        patterns = [
            r"I don't have (enough )?context",
            r"I'm not sure",
            r"I don't know",
            r"could you clarify",
            r"what do you mean",
            r"I need more information",
        ]
        count = 0
        for pat in patterns:
            count += len(re.findall(pat, content, re.IGNORECASE))
        return count

    def _classify_content_type(self, content: str) -> str:
        if not content or not content.strip():
            return "empty"

        stripped = content.strip()

        has_json_tool = bool(re.search(r'\{\s*"name"\s*:\s*"[^"]+"', stripped))
        has_observations = bool(re.search(r'##\s*Observations', stripped, re.IGNORECASE))

        if has_json_tool and has_observations:
            return "mixed"
        if has_json_tool:
            return "tool_json"
        if has_observations:
            return "observations"
        return "text"

    def _count_tool_call_blobs(self, content: str) -> int:
        if not content:
            return 0
        return len(re.findall(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"', content))

    def _extract_tool_call_names(self, content: str) -> list[str]:
        if not content:
            return []
        return re.findall(r'\{\s*"name"\s*:\s*"([^"]+)"', content)

    def _extract_tool_calls(self, content: str) -> list[dict]:
        """Extract full tool call objects from JSON code blocks in content.

        Uses balanced-brace matching to handle nested JSON in arguments
        (e.g. {"name": "ws.write", "arguments": {"path": "a.py", "opts": {"force": true}}}).
        """
        if not content:
            return []
        tool_calls = []

        # Find {"name": "...", "arguments": { ... }} patterns via balanced-brace scanning
        search_start = 0
        while True:
            # Locate the start of a potential tool call object
            idx = content.find('{"name"', search_start)
            if idx == -1:
                idx = content.find('{"name" :', search_start)
            if idx == -1:
                break

            # Find the matching closing brace using balanced-brace logic
            depth = 0
            in_str = False
            esc = False
            end_idx = -1
            for i in range(idx, len(content)):
                ch = content[i]
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
                            end_idx = i
                            break

            if end_idx == -1:
                break

            raw_obj = content[idx:end_idx + 1]
            search_start = end_idx + 1

            try:
                obj = json.loads(raw_obj)
            except json.JSONDecodeError:
                continue

            if not isinstance(obj, dict) or "name" not in obj:
                continue

            name = obj["name"]
            arguments = obj.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}

            tool_calls.append({"name": name, "arguments": arguments})

        return tool_calls
