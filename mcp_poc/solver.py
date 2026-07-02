import asyncio
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RecursiveSolver:
    def __init__(
        self,
        workspace_path: str,
        exploration_id: str = "",
        max_iterations: int = 20,
        max_context_tokens: int = 1024,
        compaction_interval: int = 3,
        retrieval_top_k: int = 3,
        ollama_host: str = "localhost",
        ollama_port: int = 11434,
        ollama_model: str = "qwen2.5-coder:7b",
    ):
        import httpx
        self._httpx = httpx

        self.workspace_path = Path(workspace_path)
        self.max_iterations = max_iterations
        self.max_context_tokens = max_context_tokens
        self.compaction_interval = compaction_interval
        self.retrieval_top_k = retrieval_top_k
        self.ollama_host = ollama_host
        self.ollama_port = ollama_port
        self.ollama_model = ollama_model

        if not exploration_id:
            now = datetime.now()
            slug = f"explore_{now.strftime('%Y%m%d_%H%M%S')}"
            exploration_id = slug
        self.exploration_id = exploration_id

        self.chroma_path = self.workspace_path / ".explorations" / self.exploration_id
        self.chroma_path.mkdir(parents=True, exist_ok=True)

        import chromadb
        self._chromadb = chromadb
        self.chroma_client = chromadb.PersistentClient(str(self.chroma_path))
        self.master_index = self.chroma_client.get_or_create_collection(
            name="master_index",
            metadata={"hnsw:space": "cosine"},
        )

        self.iteration = 0
        self.solutions: list[dict] = []
        self._ollama_base = f"http://{ollama_host}:{ollama_port}"

    def _embed(self, text: str) -> list[float]:
        try:
            resp = self._httpx.post(
                f"{self._ollama_base}/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": text},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except Exception as e:
            logger.error("Embedding failed: %s", e)
            return [0.0] * 768

    def _chat(self, messages: list[dict], temperature: float = 0.3) -> str:
        try:
            resp = self._httpx.post(
                f"{self._ollama_base}/api/chat",
                json={
                    "model": self.ollama_model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": self.max_context_tokens,
                    },
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as e:
            logger.error("Chat failed: %s", e)
            return ""

    def _retrieve(self, query: str, top_k: Optional[int] = None) -> list[dict]:
        k = top_k or self.retrieval_top_k
        if self.master_index.count() == 0:
            return []
        try:
            q_emb = self._embed(query)
            results = self.master_index.query(query_embeddings=[q_emb], n_results=min(k, self.master_index.count()))
            hits = []
            if results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    hits.append({
                        "id": doc_id,
                        "content": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "score": results["distances"][0][i] if results["distances"] else 0.0,
                    })
            return hits
        except Exception as e:
            logger.error("Retrieval failed: %s", e)
            return []

    def _store(self, texts: list[str], metadatas: Optional[list[dict]] = None):
        if not texts:
            return
        ids = [f"{self.exploration_id}_iter{self.iteration}_{i}" for i in range(len(texts))]
        embeddings = [self._embed(t) for t in texts]
        self.master_index.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas or [{"iteration": self.iteration}] * len(texts),
        )

    def _truncate_context(self, text: str, max_tokens: int = 800) -> str:
        words = text.split()
        if len(words) > max_tokens:
            words = words[:max_tokens]
        return " ".join(words)

    def _decompose(self, problem: str, retrieved: list[dict]) -> tuple[str, list[str]]:
        context_parts = []
        for r in retrieved:
            context_parts.append(f"[Previous Finding] {r['content']}")
        context_str = "\n\n".join(context_parts[:3])

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a recursive problem solver. Given a complex problem, "
                    "decompose it into smaller, independently solvable sub-problems. "
                    "Return your answer in two parts:\n"
                    "1. ANALYSIS: Your reasoning about the problem structure\n"
                    "2. SUB_PROBLEMS: A numbered list of sub-problems to solve, one per line\n\n"
                    "Each sub-problem should be self-contained and actionable."
                ),
            },
            {
                "role": "user",
                "content": f"Problem: {problem}\n\nPrior context:\n{context_str}" if context_str else f"Problem: {problem}",
            },
        ]
        response = self._chat(messages, temperature=0.3)
        sub_problems = self._parse_sub_problems(response)
        return response, sub_problems

    def _parse_sub_problems(self, text: str) -> list[str]:
        problems = []
        in_block = False
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.upper() == "SUB_PROBLEMS:" or stripped.upper() == "SUB_PROBLEMS":
                in_block = True
                continue
            if in_block and not stripped:
                continue
            if in_block:
                cleaned = re.sub(r"^\d+[\.\)]\s*", "", stripped).strip()
                if cleaned:
                    if cleaned.startswith("- ") or cleaned.startswith("* "):
                        cleaned = cleaned[2:].strip()
                    if "ANALYSIS:" in cleaned.upper():
                        in_block = False
                        continue
                    problems.append(cleaned)
        if not problems:
            lines = text.strip().split("\n")
            for line in lines:
                stripped = line.strip()
                if re.match(r"^\d+[\.\)]", stripped):
                    cleaned = re.sub(r"^\d+[\.\)]\s*", "", stripped).strip()
                    problems.append(cleaned)
        return problems

    def _solve(self, sub_problem: str, retrieved: list[dict]) -> str:
        context_parts = []
        for r in retrieved:
            context_parts.append(f"[Finding] {r['content']}")
        context_str = "\n".join(context_parts[:5])

        messages = [
            {
                "role": "system",
                "content": "You are solving a sub-problem. Provide a clear, concise solution. Include reasoning, code, or analysis as needed.",
            },
            {
                "role": "user",
                "content": f"Sub-problem: {sub_problem}\n\nRelevant context:\n{context_str}" if context_str else f"Sub-problem: {sub_problem}",
            },
        ]
        return self._chat(messages, temperature=0.2)

    def _reflect(self, problem: str, solutions_text: str) -> str:
        messages = [
            {
                "role": "system",
                "content": "You are evaluating the quality and completeness of a solution. Identify gaps, errors, or missing aspects. Be specific and constructive.",
            },
            {
                "role": "user",
                "content": f"Original problem: {problem}\n\nCurrent solutions:\n{solutions_text}\n\nWhat gaps remain? What needs further exploration?",
            },
        ]
        return self._chat(messages, temperature=0.4)

    def _compact(self) -> str:
        all_docs = self.master_index.get()
        if not all_docs or not all_docs.get("documents"):
            return ""
        combined = "\n\n".join(all_docs["documents"][-50:])
        messages = [
            {
                "role": "system",
                "content": "Summarize the key findings and progress so far in this exploration. Focus on solved sub-problems, breakthroughs, and remaining challenges.",
            },
            {
                "role": "user",
                "content": self._truncate_context(combined, max_tokens=600),
            },
        ]
        return self._chat(messages, temperature=0.2)

    def _is_solved(self, problem: str, solutions_text: str, reflection: str) -> bool:
        messages = [
            {
                "role": "system",
                "content": "Determine if the original problem has been fully solved. Reply with only 'YES' or 'NO' followed by a brief reason.",
            },
            {
                "role": "user",
                "content": f"Problem: {problem}\n\nSolutions found:\n{solutions_text}\n\nRemaining gaps:\n{reflection}\n\nHas the problem been fully solved?",
            },
        ]
        response = self._chat(messages, temperature=0.1)
        return response.strip().upper().startswith("YES")

    async def explore(self, task: str) -> tuple[str, dict]:
        logger.info("Starting exploration %s: %s", self.exploration_id, task[:100])

        current_problem = task
        final_solution = ""
        metadata = {
            "exploration_id": self.exploration_id,
            "iterations": 0,
            "sub_problems_solved": 0,
            "start_time": time.time(),
            "end_time": 0.0,
        }

        for iteration in range(1, self.max_iterations + 1):
            self.iteration = iteration
            logger.info("Iteration %d/%d", iteration, self.max_iterations)

            retrieved = self._retrieve(current_problem)

            analysis, sub_problems = self._decompose(current_problem, retrieved)
            self._store([f"[Decomposition] {analysis}"], [{"type": "decomposition", "iteration": iteration}])

            if not sub_problems:
                logger.info("No sub-problems decomposed; attempting direct solve")
                sub_problems = [current_problem]

            iteration_solutions = []
            for i, sp in enumerate(sub_problems):
                logger.info("  Sub-problem %d/%d: %s", i + 1, len(sub_problems), sp[:80])
                sp_retrieved = self._retrieve(sp, top_k=2)
                solution = self._solve(sp, sp_retrieved)
                if solution:
                    iteration_solutions.append({"sub_problem": sp, "solution": solution})
                    self._store(
                        [f"[Solution] {sp}\n{solution}"],
                        [{"type": "solution", "iteration": iteration, "sub_problem_index": i}],
                    )
                    metadata["sub_problems_solved"] += 1

            if not iteration_solutions:
                logger.warning("No solutions generated in iteration %d", iteration)
                continue

            combined = "\n\n".join(s["solution"] for s in iteration_solutions)
            final_solution = combined

            if iteration % self.compaction_interval == 0:
                logger.info("Compaction at iteration %d", iteration)
                summary = self._compact()
                if summary:
                    self._store([f"[Progress Summary] {summary}"], [{"type": "summary", "iteration": iteration}])

            reflection = self._reflect(current_problem, combined)
            self._store([f"[Reflection] {reflection}"], [{"type": "reflection", "iteration": iteration}])

            solved = self._is_solved(current_problem, combined, reflection)
            if solved:
                logger.info("Problem solved at iteration %d", iteration)
                final_solution = combined
                break

            if "cannot determine" in reflection.lower() or "insufficient" in reflection.lower():
                current_problem = f"{current_problem}\n\nAdditional context needed: {reflection}"
            else:
                current_problem = f"{current_problem}\n\nRefinement needed: {reflection}"

        metadata["iterations"] = self.iteration
        metadata["end_time"] = time.time()
        metadata["duration"] = metadata["end_time"] - metadata["start_time"]

        logger.info(
            "Exploration complete: %d iterations, %d sub-problems solved, %.1fs",
            metadata["iterations"],
            metadata["sub_problems_solved"],
            metadata["duration"],
        )

        return final_solution, metadata

    def close(self):
        pass
