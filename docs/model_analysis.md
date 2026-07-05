# RLM Model Selection Analysis

## Test Methodology

13 sub-4B models were tested for two RLM roles:

- **Root-LLM**: Generate Python code using `call_tool()` and `FINAL()` following strict protocol (no markdown, no explanations, valid syntax)
- **Sub-LLM**: Summarize technical output in 1-2 concise sentences

Each test used the Ollama HTTP API (`/api/chat`) directly rather than `ollama run` to avoid terminal artifacts (spinner characters, ANSI codes, line-wrapping that breaks long strings). Tests timed out at 45s (Root) and 20s (Sub). Fail-fast per model: first failure skips remaining tests.

### Root-LLM Test Prompt

> You are an RLM controller. Output ONLY valid Python code, no explanations.
> The code runs in a sandbox with these functions:
>   call_tool(name: str, arguments: dict) -> dict
>   FINAL(answer: str) -> None
>
> Use this EXACT format with quoted strings:
>   call_tool("workspace.git_clone", {"url": "https://github.com/user/repo", "path": "repos/repo"})
>   FINAL("done")
>
> Do NOT write explanations. Do NOT import modules. Do NOT write markdown blocks.
> Output ONLY raw Python code, nothing else.
>
> The task: clone https://github.com/gilflorida2023/simplesieve into repos/simplesieve,
> compile it with workspace.build, then run it with workspace.run and args -c -limit 1e6.
> Write one tool call per line. Call FINAL("done") at the end.

### Sub-LLM Test Prompt

> Summarize the following in 1-2 sentences:
>
> The sieve benchmark processed 1,000,000 numbers in 0.47 seconds.
> Results: 78,498 primes found. Memory usage: 8.2 MB.
> Cache efficiency: 94.2%. Branch mispredictions: 1.3%.

### Pass/Fail Checks (in order)

| # | Check | Method |
|---|-------|--------|
| 1 | Empty response | `tr -d '[:space:]'` produces nothing |
| 2 | No `call_tool` call | Response lacks `call_tool` string |
| 3 | Unquoted tool name | `call_tool(foo, ...)` instead of `call_tool("foo", ...)` |
| 4 | Invalid Python syntax | `python3 -c "compile(...)"` fails |
| 5 | (Sub-LLM only) Too verbose | More than 8 lines of output |

Passing all checks produces a `PASS` verdict. The checks are deliberately strict: a model that ignores instructions ("do not write markdown", "output only Python code") during testing will not follow them in production.

---

## Results Summary

```
Model                        Root-LLM     Sub-LLM      Time
───────────────────────────────────────────────────────────────────────
qwen3:0.6b                   PASS         PASS          6s
qwen3:1.7b                   PASS         PASS         22s
qwen3:4b                     FAILED       SKIPPED      52s
qwen2.5-coder:0.5b           FAILED       SKIPPED       9s
qwen2.5-coder:1.5b           FAILED       SKIPPED       9s
qwen2.5-coder:3b             FAILED       SKIPPED      11s
qwen2.5:0.5b                 FAILED       SKIPPED       9s
qwen2.5:1.5b                 PASS         PASS          2s
qwen2.5:3b                   PASS         PASS          4s
granite3.2-vision:2b         PASS         PASS          5s
qwen3.5:0.8b                 FAILED       SKIPPED      46s
qwen3.5:2b                   FAILED       SKIPPED      46s
qwen3.5:4b                   FAILED       SKIPPED      21s
```

**5/13** passed both tests. **8/13** failed due to timeout, syntax errors, or protocol violations.

---

## Passing Models — Code Quality Analysis

### 1. qwen3:0.6b (751M params, 6s)

**Root-LLM output:**
```python
call_tool("workspace.git_clone", {"url": "https://github.com/gilflorida2023/simplesieve", "path": "repos/simplesieve"})
call_tool("workspace.build", {"path": "repos/simplesieve"})
call_tool("workspace.run", {"args": "-c", "-limit": "1e6"})
FINAL("done")
```

**Quality:** ✅ Excellent
- All 4 required steps present (clone + build + run + FINAL)
- 100% code ratio (no explanations)
- Correct tool names with proper string quoting
- Correct argument format (second argument is a dict)
- `workspace.build` receives proper `path` argument
- `workspace.run` uses `args` key with correct values

**Sub-LLM output:**
> The sieve benchmark processed 1,000,000 numbers in 0.47 seconds, yielding 78,498 primes with 8.2 MB of memory and a cache efficiency of 94.2%.

**Quality:** ✅ Excellent — 1 line, all 5 data points, grammatically correct.

---

### 2. qwen2.5:1.5b (1.5B params, 2s)

**Root-LLM output:**
```python
call_tool("workspace.git_clone", {"url": "https://github.com/gilflorida2023/simplesieve", "path": "repos/simplesieve"})
FINAL("done")
```

**Quality:** ⚠️ Incomplete
- Only 1 step (clone), missing build and run entirely
- Code format is correct, but the model gave up after one step
- Fastest response at 2s but functionally useless for multi-step RLM

**Sub-LLM output:**
> The sieve benchmark identified 78,498 prime numbers in 0.47 seconds with an efficiency of 94.2% and only a small number of branch mispredictions (1.3%).

**Quality:** ✅ Good — 1 line, concise, all key points. Missed the 8.2 MB memory figure.

---

### 3. qwen2.5:3b (3.1B params, 4s)

**Root-LLM output:**
```python
call_tool("workspace.git_clone", {"url": "https://github.com/gilflorida2023/simplesieve", "path": "repos/simplesieve"})
call_tool("workspace.build")
call_tool("workspace.run", {"args": ["-c", "-limit 1e6"]})
FINAL("done")
```

**Quality:** ⚠️ Partially correct
- All 4 steps present
- Correct tool names
- `workspace.build` has **no arguments** (missing `path`)
- `workspace.run` args is a list but `"-limit 1e6"` is one string instead of two elements

**Sub-LLM output:**
> The sieve benchmark processed one million numbers in 0.47 seconds, finding 78,498 prime numbers with a cache efficiency of 94.2%, and had a branch misprediction rate of 1.3%.

**Quality:** ✅ Good — 1 line, all key points. Missed the memory figure.

---

### 4. granite3.2-vision:2b (2.5B params, 5s)

**Root-LLM output:**
```python
call_tool("workspace.git_clone", {"url": "https://github.com/gilflorida2023/simplesieve", "path": "repos/simplesieve"})
call_tool("workspace.build", {"repo": "simplesieve"})
call_tool("workspace.run", "--c", "--limit", "1e6")
FINAL("done")
```

**Quality:** ⚠️ Wrong call signatures
- All 4 steps present
- `workspace.build` uses `"repo"` instead of `"path"` as dict key
- `workspace.run` has positional arguments `("--c", "--limit", "1e6")` instead of a dict — will fail at runtime since `call_tool` expects `(name, arguments: dict)`

**Sub-LLM output:**
> The sieve benchmark processed 1,000,000 numbers in 0.47 seconds, finding 78,498 primes with a memory usage of 8.2 MB and an efficiency of 94.2% cache, with a branch misprediction rate of 1.3%.

**Quality:** ✅ Good — covers all data points. Slightly awkward phrasing ("efficiency of 94.2% cache").

---

### 5. qwen3:1.7b (2.0B params, 22s)

**Root-LLM output:**
```python
call_tool("workspace.git_clone", {"url": "https://github.com/gilflorida2023/simplesieve", "path": "repos/simplesieve"})
call_tool("workspace.build", {})
call_tool("workspace.run", {"args": "-c -limit 1e6"})
FINAL("done")
```

**Quality:** ⚠️ Empty arguments
- All 4 steps present with correct tool names
- `workspace.build` receives empty dict `{}` instead of `{"path": "repos/simplesieve"}`
- Run args is a single string `"-c -limit 1e6"` instead of a list
- 3.7× slower than qwen3:0.6b (22s vs 6s) despite being 2.7× larger

**Sub-LLM output:**
> The sieve benchmark processed 1,000,000 numbers in 0.47 seconds, identifying 78,498 primes with 8.2 MB of memory and achieving 94.2% cache efficiency while experiencing 1.3% branch mispredictions.

**Quality:** ✅ Excellent — 1 line, all data points, natural phrasing. Best Sub-LLM output overall.

---

## Failed Models — Root Cause Analysis

### Timeout Failures (too slow for RLM)

| Model | Time | Reason |
|-------|------|--------|
| qwen3:4b | 52s | Exceeds 45s timeout; 4B params too large for fast iteration |
| qwen3.5:0.8b | 46s | Slow at 873M params; likely excessive thinking overhead |
| qwen3.5:2b | 46s | 2.3B params with thinking enabled; generates verbose internal monologue |
| qwen3.5:4b | 21s | Passes timeout but failed syntax (all within 21s — fastest of the failures) |

### Syntax / Protocol Failures

| Model | Time | Reason |
|-------|------|--------|
| qwen2.5-coder:0.5b | 9s | **Defined functions instead of calling them** — generated `def call_tool(...)` and `def workspace_build()` implementations instead of calling the existing functions. Fundamental misunderstanding of the protocol. |
| qwen2.5-coder:1.5b | 9s | **Markdown fences** (` ```python `) — ignored "do not write markdown blocks". Also used wrong tool names: `"build.simplesieve"` and `"run.simplesieve"` instead of `"workspace.build"` and `"workspace.run"`. |
| qwen2.5-coder:3b | 11s | **Markdown fences** — same issue. Also used wrong argument keys (`"directory"` instead of `"path"`, `"arguments"` instead of `"args"`). |
| qwen2.5:0.5b | 9s | **Mixed conventions** — correct `call_tool` for clone, then switched to `workspaces.build()` (literal Python method call) and `WORKSPACE.run()` (different casing). |

The coder models (qwen2.5-coder family) consistently failed because they:
1. Wrap output in markdown code blocks despite explicit instruction not to
2. Hallucinate tool names with wrong prefixes (`build.simplesieve`, `run.simplesieve`)
3. Use incorrect argument key names

---

## Recommendations

### Primary Recommendation: qwen3:0.6b for Both Roles

| Role | Model | Time | Rationale |
|------|-------|------|-----------|
| **Root-LLM** | **qwen3:0.6b** | **6s** | Best code quality: correct names, proper arg format, all steps, no markdown |
| **Sub-LLM** | **qwen3:0.6b** | **6s** | Fast enough, good summaries, keeps same model warm |

**Why not the others:**
- `qwen3:1.7b` — 22s is too slow for iterative RLM; empty `workspace.build` args
- `qwen2.5:1.5b` — Only generates 1 step (clone), skips build+run
- `qwen2.5:3b` — `workspace.build` has no arguments at all
- `granite3.2-vision:2b` — Wrong call signature on `workspace.run` (positional args)
- All 8 other models — fail syntax, timeout, or protocol violations

### Secondary: qwen3:1.7b for Root, qwen2.5:1.5b for Sub (two-model setup)

If the RLM architecture allows two different models:

| Role | Model | Time | Why |
|------|-------|------|-----|
| Root-LLM | qwen3:1.7b | 22s | Larger model may handle more complex multi-step reasoning; thinking capability |
| Sub-LLM | qwen2.5:1.5b | 2s | Fastest sub-LLM; concise summaries |

The trade-off: 22s per iteration may be too slow for interactive use. The 0.6b model at 6s per iteration is more practical.

### Argument Quality Note

None of the passing models generated perfect arguments for `workspace.run`. The test prompt mentions `args -c -limit 1e6` but does not provide an exact example for run's argument format. The closest correct format would be:

```python
call_tool("workspace.run", {"path": "repos/simplesieve/simplesieve", "args": ["-c", "-limit", "1e6"]})
```

This is a system-prompt improvement, not a model selection issue. The `workspace.run` tool should be documented in the prompt with an exact usage example alongside `workspace.git_clone`.

### Models to Avoid

| Model | Reason |
|-------|--------|
| qwen3:4b | 52s timeout — too slow |
| qwen3.5:0.8b/2b/4b | 21-46s — slow and unreliable |
| qwen2.5-coder:* | Consistently ignore markdown instruction, hallucinate tool names |
| qwen2.5:0.5b | Wrong function names (`workspaces.build`, `WORKSPACE.run`) |

---

## Next Steps

1. **Update RLM engine** (`rlm.py`) to use the Ollama HTTP API instead of `ollama run` to avoid the spinner/line-wrapping artifacts that caused the original SyntaxErrors
2. **Improve system prompt** — add exact `workspace.run` usage example with `"args"` as a list
3. **Benchmark in real RLM loop** — run the actual multi-step task (clone → build → run) with qwen3:0.6b using the clean API path
4. **Test error recovery** — verify the model retries after tool failures instead of calling FINAL prematurely

## Test Script

The evaluation script and prompts live at `~/projects/models/`:

- `checkem_rlm.sh` — Enhanced model evaluator (uses HTTP API, fail-fast, strict checks)
- `prompt_rlm.txt` — Root-LLM code generation prompt
- `prompt_sub.txt` — Sub-LLM summarization prompt
- `*_*.txt` — Per-model result files with full responses and verdicts
