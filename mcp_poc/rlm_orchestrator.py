import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config import config
from ollama_client import OllamaClient
from todo_list import TodoItem, TodoList
from stats_collector import StatsCollector, TurnStats

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
                 embed_service=None, vector_store=None):
        self.ollama = ollama
        self.todo_list = todo_list
        self.stats = stats_collector
        self.embed_service = embed_service
        self.vector_store = vector_store

    async def run_turn(self, user_input: str, session_id: str,
                       system_prompt: str = "",
                       context_messages: Optional[List[dict]] = None) -> Tuple[str, TurnStats]:
        todo = self.todo_list.pick_next()
        todo_id = todo.id if todo else ""

        messages = self._build_messages(todo, user_input, session_id,
                                        system_prompt, context_messages)

        start = time.monotonic_ns()
        content, raw_stats = await self.ollama.chat_with_stats(messages)
        duration_ns = time.monotonic_ns() - start

        obs = self._parse_observations(content)

        if todo:
            self._apply_observations(obs, todo, session_id)

        budget = self._estimate_context_budget(messages)
        used = sum(len(json.dumps(m)) for m in messages)

        turn_stats = TurnStats(
            turn_number=self.stats.total_turns + 1,
            todo_id=todo_id,
            prompt_tokens=raw_stats.get("prompt_tokens", 0),
            completion_tokens=raw_stats.get("completion_tokens", 0),
            context_budget=budget,
            context_used=used,
            truncated=False,
            self_references=self._count_self_references(content, messages),
            clarification_requests=self._count_clarifications(content),
            duration_ns=duration_ns,
            embedding_calls=self.embed_service.call_count if self.embed_service else 0,
        )
        self.stats.record_turn(turn_stats)

        return content, turn_stats

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
        content, _ = await self.ollama.chat_with_stats(messages)
        todos = self._parse_todo_list(content)
        created = []
        for desc in todos:
            item = self.todo_list.create_todo(desc, session_id)
            created.append(item)
        return created

    def _build_messages(self, todo: Optional[TodoItem], user_input: str,
                        session_id: str, system_prompt: str,
                        context_messages: Optional[List[dict]]) -> List[dict]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        current_todo_desc = todo.description if todo else "(no active todo)"
        todo_text = self.todo_list.todo_text(session_id) if todo else ""

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
