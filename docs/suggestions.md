# Actionable Suggestions from Model Research

The following suggestions are derived from testing 13 sub-4B models with an RLM-specific
evaluation script (`checkem_rlm.sh`). Each suggestion addresses a specific defect or
opportunity identified during the evaluation.

---

## Suggestion 1: Switch RLM Engine from `ollama run` to HTTP API

**Files affected:** `mcp_poc/rlm.py`

### Problem

The RLM engine uses `ollama run` (either via `ollama.chat()` or a subprocess call) to
get responses from the Root LLM. This introduces terminal artifacts into the model's
output:

- **Spinner characters** — Unicode braille characters (U+2800-U+28FF) like `⠙` `⠹` `⠸`
  that are rendered during model inference. These are invalid Python tokens and cause
  every single response to fail `compile()`.
- **Line-wrapping** — Long lines are wrapped at terminal width (~80 columns), breaking
  long strings across multiple lines. A line like:
  ```python
  call_tool("workspace.git_clone", {"url": "https://github.com/gilflorida2023/simplesieve", "path": "repos/simplesieve"})
  ```
  Becomes:
  ```
  call_tool("workspace.git_clone", {"url": "https://github.com/gilflorida2023
  "https://github.com/gilflorida2023/simplesieve", "path": "repos/simplesieve
  "repos/simplesieve"})
  ```
  The first `"` on line 2 closes the unterminated string from line 1, but the string
  contents are now corrupted (duplicated URL segments), AND the first string literal is
  never closed on line 1, producing `SyntaxError: unterminated string literal`.

These artifacts were the root cause of every "syntax error" failure in the original
RLM runs. The model itself generates valid code — the terminal corrupts it before the
RLM can parse it.

### Solution

Replace `ollama run` with direct HTTP calls to `http://localhost:11434/api/chat` in all
locations where the RLM engine communicates with Ollama. The API returns clean JSON
with the response in `message.content`, untouched by terminal output processing.

The `checkem_rlm.sh` script proves this works — every model that previously failed
with "syntax error" due to terminal artifacts passes cleanly via the API.

### Implementation

There are two call sites in the RLM system:

1. **Root LLM call** in `SimpleRLM.completion()` — Currently uses `self.ollama.chat()`
   which may route through `ollama run`. This should be switched to raw `httpx` POST
   to the API endpoint, identical to how `_sync_llm_request()` already works for sub-LLM
   calls.

2. **Sub-LLM queries** in `_sync_llm_request()` — Already uses `httpx` directly. This is
   correct and should not be changed.

The root LLM call should be changed from:
```python
response = await self.ollama.chat(messages, tools=None)
```
To an async `httpx` call matching the sub-LLM pattern, using the same `self.base_url`
and `self.model_name` that the class already stores.

### Why This Works

The `checkem_rlm.sh` script uses this exact approach (curl to the API, parse JSON
response) and produces clean, compilable Python code from qwen3:0.6b and the other
passing models. Switching the RLM engine to the API eliminates the terminal corruption
at the source.

---

## Suggestion 2: Add workspace.run Example to System Prompt

**Files affected:** `mcp_poc/prompts/rlm_system_prompt.txt`

### Problem

The current system prompt provides an exact usage example for `workspace.git_clone`:
```python
call_tool("workspace.git_clone", {"url": "...", "path": "repos/simplesieve"})
```

But it does NOT provide an example for `workspace.run`, despite the task requiring it.
The prompt says:
> run it with workspace.run and args -c -limit 1e6

This is ambiguous. None of the 5 passing models generated correct arguments for
`workspace.run`:

| Model | Generated | Issue |
|-------|-----------|-------|
| qwen3:0.6b | `{"args": "-c", "-limit": "1e6"}` | `-limit` becomes dict key instead of arg list element |
| qwen3:1.7b | `{"args": "-c -limit 1e6"}` | Args is a single string, not a list |
| qwen2.5:3b | `{"args": ["-c", "-limit 1e6"]}` | `-limit 1e6` is one string instead of two |
| granite3.2-vision:2b | `"--c", "--limit", "1e6"` | Positional args instead of dict |
| qwen2.5:1.5b | (didn't attempt) | Only generated clone step |

### Solution

Add a `workspace.run` example to the system prompt:
```python
call_tool("workspace.run", {"path": "repos/simplesieve/simplesieve", "args": ["-c", "-limit", "1e6"]})
```

Place this alongside the existing `workspace.git_clone` example in the "Available
Functions" section of `rlm_system_prompt.txt`.

### Why This Works

Models follow the exact format shown in examples. Both qwen2.5:3b and qwen3:0.6b
reproduced the `workspace.git_clone` format precisely because an example was provided.
Adding a `workspace.run` example will produce similarly correct output.

---

## Suggestion 3: Set qwen3:0.6b as Default Model

**Files affected:** `mcp_poc/config.yaml`

### Problem

The current `config.yaml` does not specify a default model for the RLM, or may default
to a model that is too large, too slow, or produces invalid code.

### Evaluation Results

| Model | Root-LLM | Sub-LLM | Time | Code Quality |
|-------|----------|---------|------|-------------|
| **qwen3:0.6b** | PASS | PASS | 6s | Best: correct names, proper args, all steps, 100% code |
| qwen3:1.7b | PASS | PASS | 22s | Good but 3.7× slower; empty `workspace.build` args |
| qwen2.5:1.5b | PASS | PASS | 2s | Fastest but only generates 1 step (clone) |
| qwen2.5:3b | PASS | PASS | 4s | Fast but `workspace.build` has no arguments |
| granite3.2-vision:2b | PASS | PASS | 5s | Wrong call signature on `workspace.run` |

### Recommendation

Set `qwen3:0.6b` as the default Root-LLM model in config.yaml. It is the only model
that:
- Produces all 4 required steps
- Uses correct argument formats
- Maintains 100% code ratio (no commentary)
- Runs in under 10 seconds
- Also passes the Sub-LLM summarization test

This can be overridden for users who want a larger model, but 0.6b should be the
default for new sessions.

---

## Suggestion 4: Add RLM Mode Auto-Switch to BUILD

**Files affected:** `mcp_poc/repl.py`

### Problem

When `/rlm` is toggled on, the agent stays in PLAN mode (read-only). The RLM needs
to call tools like `workspace.git_clone`, `workspace.build`, and `workspace.run`,
all of which modify the filesystem. These calls are rejected in PLAN mode, causing
the first tool call to fail with a permissions error. The Root LLM then sees the
error, may call FINAL prematurely, and the whole loop fails.

### Solution

In the `/rlm` toggle handler in `repl.py`, automatically switch to BUILD mode when
RLM mode is enabled:

```python
elif raw_input == "/rlm":
    agent.rlm_mode = not agent.rlm_mode
    if agent.rlm_mode and agent.current_mode == "PLAN":
        agent.current_mode = "BUILD"
    rlm_str = "ON" if agent.rlm_mode else "OFF"
    print(f"\nRLM mode: {rlm_str}")
    print(f"Mode: {agent.current_mode}")
```

This ensures the RLM starts in a mode where tool calls will succeed.

---

## Suggestion 5: Move checkem_rlm.sh into the Project

**Files affected:** (new file) `mcp_poc/scripts/checkem_rlm.sh`

### Problem

The evaluation script lives in `~/projects/models/` alongside data files. It should
be part of the project so developers can re-run it when models are updated or new
models are added.

### Solution

Copy `checkem_rlm.sh`, `prompt_rlm.txt`, and `prompt_sub.txt` into `mcp_poc/scripts/`.
The script can then be run from the project root:

```bash
bash mcp_poc/scripts/checkem_rlm.sh
```

This also makes the script discoverable for new contributors.

---

## Suggestion 6: Keep Dual-Role Architecture

**Files affected:** (design decision, no code change)

### Design Decision

The RLM architecture already supports two distinct roles:
- **Root LLM**: Multi-step planning, code generation, error recovery
- **Sub LLM** (`llm_query()`): Fast, focused analysis

The evaluation confirmed that:
- qwen3:0.6b works well for BOTH roles (simplest deployment)
- qwen3:1.7b could serve as a more capable Root LLM (22s, thinking capability)
- qwen2.5:1.5b could serve as a faster Sub LLM (2s, concise summaries)

The code supports using different models for each role via the `_sync_llm_request()`
function, which accepts an arbitrary model name. The `SimpleRLM` constructor already
accepts an `ollama_client` parameter for the Root LLM. The Sub LLM model could be
configured separately.

Recommendation: Keep qwen3:0.6b as the default for both, but expose a config option
for specifying a different Sub LLM model.

---

## Suggestion 7: Three-Tier Architecture — Add a Writer Model

**Files affected:** (design decision, `mcp_poc/rlm.py`, `mcp_poc/agent.py`)

### Insight

The RLM has two roles today: **Root LLM** (plans, calls tools) and **Sub LLM**
(analyzes, summarizes). There is a third implicit role: **Writer** — formatting
tool output for the user, composing diffs, formatting error messages, writing
coherent answers.

Currently the Root LLM does this itself, wasting its limited context on
presentation formatting. A small, fast Writer model could handle all user-facing
text generation, leaving the Root LLM focused purely on reasoning and tool
orchestration.

### Concrete Use Cases

| Task | Currently handled by | Should be handled by |
|------|--------------------|--------------------|
| "Here's what the tool returned: [raw JSON]" | Root LLM (writes `print()` statements) | Writer model (formats JSON into prose) |
| Formatting git diffs for display | Root LLM (formatting in code output) | Writer model (takes diff text, produces readable summary) |
| Answering "what did you do?" | Root LLM (composes FINAL message) | Writer model (takes tool call log, produces narrative) |
| Error messages to user | Root LLM (includes in code or FINAL) | Writer model (rephrases technical errors) |
| Progress updates mid-task | Root LLM (prints intermediate messages) | Writer model (summarizes current state) |

### Example Flow

```
Iteration 3:
  Root LLM produces: call_tool("workspace.run", {"path": "...", "args": [...]})
  Tool returns:      {"stdout": "78498 primes found in 0.47s", "success": true}
  Writer model:      "The sieve found 78,498 primes in 0.47 seconds. ✅"

  Root LLM produces: FINAL("done")
  Writer model:      "I cloned the repo, compiled it, and ran the sieve.
                      Results: 78,498 primes in 0.47s."
```

### Model Selection

The Writer role needs:
- Fast (<3s response time)
- Tiny (<1B params) to minimize resource usage
- Good prose generation (not code generation)
- No thinking overhead

| Candidate | Size | Time (Sub-LLM test) | Prose Quality |
|-----------|------|--------------------|---------------|
| qwen2.5:1.5b | 1.5B | 2s | Good — missed memory figure |
| qwen3:0.6b | 751M | 6s | Best — all 5 data points |
| qwen2.5:0.5b | 494M | 9s (failed) | N/A — failed syntax test |

qwen2.5:1.5b is the best candidate for Writer: 2s response time, small enough
to run alongside the Root LLM, produces coherent prose.

### Implementation Sketch

In `rlm.py`, after each Root LLM iteration completes and the tool output is
captured, pass the raw result to a Writer model before presenting to the user:

```python
async def _format_for_user(self, tool_result: dict, tool_name: str) -> str:
    writer_prompt = (
        "Summarize this tool output in 1-2 sentences for the user:\n"
        f"Tool: {tool_name}\n"
        f"Result: {json.dumps(tool_result)[:1000]}"
    )
    response = await self._call_llm_api(writer_prompt, model=self.writer_model)
    return response
```

The Writer model can be configured separately from the Root and Sub models in
`config.yaml`:

```yaml
rlm:
  model: qwen3:0.6b
  sub_model: qwen3:0.6b
  writer_model: qwen2.5:1.5b
```

### Why This Matters

The Root LLM has limited context (32K tokens for most models). Every token spent
on formatting prose is a token not spent on reasoning. Offloading presentation to
a dedicated Writer model:

1. Keeps the Root LLM's context cleaner (only code + tool results)
2. Produces better user-facing text (Writer model is specialized for prose)
3. Reduces iteration count (Root LLM doesn't need extra steps to format output)
4. Allows the Root LLM to focus on what it's best at: planning and tool orchestration

---

## Summary of Priority

| # | Suggestion | Impact | Effort | Priority |
|---|-----------|--------|--------|----------|
| 1 | Switch to HTTP API | Fixes all SyntaxErrors in RLM | Medium | **HIGH** |
| 2 | Add workspace.run example | Fixes run arg generation | Low | **HIGH** |
| 3 | Default to qwen3:0.6b | Ensures fast, correct operation | Low | **HIGH** |
| 4 | Auto-switch to BUILD on /rlm | Prevents first-call failures | Low | **HIGH** |
| 5 | Move script into project | Developer discoverability | Low | Low |
| 6 | Keep dual-role architecture | Future flexibility | None | Medium |
| 7 | Add Writer model (three-tier) | Better UX, cleaner Root context | Medium | Medium |
