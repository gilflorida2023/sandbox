import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TurnStats:
    turn_number: int = 0
    todo_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    context_budget: int = 0
    context_used: int = 0
    truncated: bool = False
    sem_search_scores: List[float] = field(default_factory=list)
    self_references: int = 0
    clarification_requests: int = 0
    duration_ns: int = 0
    embedding_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def context_utilization(self) -> float:
        if self.context_budget > 0:
            return self.context_used / self.context_budget
        return 0.0


@dataclass
class StatsSummary:
    total_turns: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    avg_prompt_per_turn: float = 0.0
    avg_completion_per_turn: float = 0.0
    avg_sem_score: float = 0.0
    truncation_rate: float = 0.0
    self_ref_rate: float = 0.0
    clarification_rate: float = 0.0
    todo_completion_rate: float = 0.0
    avg_duration_ms: float = 0.0
    total_embedding_calls: int = 0

    def dashboard(self, todo_completion_rate: float = 0.0) -> str:
        lines = []
        lines.append("╔══════════════════════════════════════════════╗")
        lines.append("║            RLM TELEMETRY DASHBOARD           ║")
        lines.append("╠══════════════════════════════════════════════╣")
        lines.append(f"║ TURNS         Total: {self.total_turns:<4d}  "
                      f"Avg/turn: {int(self.avg_prompt_per_turn + self.avg_completion_per_turn):>5d}t  ║")
        lines.append(f"║ PROMPT        Total: {self.total_prompt_tokens:<6d}t  "
                      f"Avg: {int(self.avg_prompt_per_turn):>5d}t    ║")
        lines.append(f"║ COMPLETION    Total: {self.total_completion_tokens:<6d}t  "
                      f"Avg: {int(self.avg_completion_per_turn):>4d}t    ║")
        lines.append(f"║ EMBEDDING     Calls: {self.total_embedding_calls:<4d}                    ║")
        lines.append("╟──────────────────────────────────────────────╢")
        tr = f"{self.truncation_rate * 100:.0f}%" if self.total_turns > 0 else "0%"
        sr = f"{self.self_ref_rate * 100:.0f}%" if self.total_turns > 0 else "0%"
        cr = f"{self.clarification_rate * 100:.0f}%" if self.total_turns > 0 else "0%"
        sc = f"{self.avg_sem_score:.2f}" if self.total_turns > 0 else "N/A"
        lines.append(f"║ TRUNCATION RATE   {tr:<6s}                        ║")
        lines.append(f"║ SELF-REFERENCE    {sr:<6s}                        ║")
        lines.append(f"║ CLARIFICATIONS    {cr:<6s}                        ║")
        lines.append(f"║ AVG SEM SCORE     {sc:<6s}                        ║")
        lines.append("╟──────────────────────────────────────────────╢")
        lines.append(f"║ TODO COMPLETION   {todo_completion_rate * 100:.0f}%                              ║")
        lines.append(f"║ AVG DURATION      {self.avg_duration_ms:.0f}ms                          ║")
        lines.append("╚══════════════════════════════════════════════╝")
        return "\n".join(lines)


class StatsCollector:
    def __init__(self, max_window: int = 100):
        self._turns: List[TurnStats] = []
        self._max_window = max_window

    def record_turn(self, stats: TurnStats):
        self._turns.append(stats)
        if len(self._turns) > self._max_window:
            self._turns.pop(0)

    def get_rolling_average(self, window: int = 10) -> Optional[TurnStats]:
        if not self._turns:
            return None
        recent = self._turns[-window:]
        if not recent:
            return None
        n = len(recent)
        avg = TurnStats(turn_number=recent[-1].turn_number)
        avg.prompt_tokens = sum(t.prompt_tokens for t in recent) // n
        avg.completion_tokens = sum(t.completion_tokens for t in recent) // n
        avg.context_budget = sum(t.context_budget for t in recent) // n
        avg.context_used = sum(t.context_used for t in recent) // n
        avg.truncated = any(t.truncated for t in recent)
        avg.self_references = sum(t.self_references for t in recent) // n
        avg.clarification_requests = sum(t.clarification_requests for t in recent) // n
        avg.duration_ns = sum(t.duration_ns for t in recent) // n
        avg.embedding_calls = sum(t.embedding_calls for t in recent) // n
        scores = [s for t in recent for s in t.sem_search_scores]
        if scores:
            avg.sem_search_scores = [sum(scores) / len(scores)]
        return avg

    def get_summary(self) -> StatsSummary:
        n = len(self._turns)
        if n == 0:
            return StatsSummary()

        summary = StatsSummary(total_turns=n)
        scores = []
        for t in self._turns:
            summary.total_prompt_tokens += t.prompt_tokens
            summary.total_completion_tokens += t.completion_tokens
            summary.total_embedding_calls += t.embedding_calls
            scores.extend(t.sem_search_scores)

        summary.avg_prompt_per_turn = summary.total_prompt_tokens / n
        summary.avg_completion_per_turn = summary.total_completion_tokens / n
        summary.avg_sem_score = sum(scores) / len(scores) if scores else 0.0

        truncated_count = sum(1 for t in self._turns if t.truncated)
        summary.truncation_rate = truncated_count / n

        ref_count = sum(1 for t in self._turns if t.self_references > 0)
        summary.self_ref_rate = ref_count / n

        clar_count = sum(1 for t in self._turns if t.clarification_requests > 0)
        summary.clarification_rate = clar_count / n

        total_duration = sum(t.duration_ns for t in self._turns)
        summary.avg_duration_ms = (total_duration / n) / 1_000_000 if n > 0 else 0.0

        return summary

    @property
    def turns(self) -> List[TurnStats]:
        return list(self._turns)

    @property
    def total_turns(self) -> int:
        return len(self._turns)

    def clear(self):
        self._turns.clear()
