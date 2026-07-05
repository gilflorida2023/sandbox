# RLM Architecture Adaptation Plan

## Overview

Transform the existing agent from a structured tool-calling loop into a true Recursive Language Model (RLM) where the Root LLM writes Python code executed in a persistent REPL sandbox.

## Architecture

```
rlm.completion(query, context) -> str
│
├── Root LLM (Qwen3 0.6B via Ollama)
│   └── Generates Python code in each iteration
│
├── Python REPL (persistent exec sandbox)
│   ├── Variables: query, context, history, storage
│   ├── Functions: llm_query(), call_tool(), search_context(), FINAL()
│   └── Code can inspect, chunk, search, transform context
│
├── Sub-LLM (same model, sequential)
│   └── llm_query(prompt, system) -> str
│       One at a time, never >2 models running
│
└── Loop until FINAL(answer) or final_answer = "..."
    Max 30 iterations, max 50 LLM calls
```

## Files to Create

- `mcp_poc/rlm.py` — SimpleRLM class (~200 lines)
- `mcp_poc/prompts/rlm_system_prompt.txt` — Root LLM system prompt

## Files to Modify

- `mcp_poc/config.yaml` — Replace RLM config section
- `mcp_poc/config.py` — Replace RlmConfig dataclass
- `mcp_poc/agent.py` — Add rlm_mode flag + run_rlm() method
- `mcp_poc/repl.py` — Add /rlm toggle + RLM dispatch

## Implementation Plan

### 1. `mcp_poc/prompts/rlm_system_prompt.txt`
System prompt explaining the RLM protocol: available variables, functions (llm_query, call_tool, search_context, FINAL), and the code-generation loop.

### 2. `mcp_poc/rlm.py`
- `SimpleRLM` class with `async def completion(query, context) -> str`
- Persistent REPL via `exec()` with controlled globals
- Sync `llm_query()` wrapper (uses `httpx` directly for sub-calls, not async client)
- Sync `call_tool()` wrapper (direct `httpx` call to MCP CGI endpoint)
- `search_context()` wrapper around VectorStore
- `_exec_code()` with `StringIO` stdout capture and `safe_builtins`
- Iteration and LLM call limits

### 3. Config changes
- Replace old `RlmConfig` (max_turns_per_todo, require_completion_check, etc.) with new fields: `max_iterations`, `max_llm_calls`, `temperature`, `num_ctx`

### 4. Agent integration
- Add `rlm_mode: bool = False` flag to `CodingAgent`
- Add `SimpleRLM` instance (lazy init)
- Add `async run_rlm(task, context) -> str` method
- Modifies `run()` to dispatch to `run_rlm()` when `rlm_mode` is True

### 5. REPL integration
- Add `/rlm` command to toggle RLM mode
- Display "RLM mode: ON/OFF" status
- Submitting a task in RLM mode calls `agent.run_rlm()`

## Safety

- Controlled `exec()` with safe builtins (no `import`, `open`, `exec`, `eval`, `__import__`)
- File operations go through `call_tool()` which validates workspace paths
- `max_iterations = 30` hard stop
- `max_llm_calls = 50` across all `llm_query()` invocations
- `call_tool()` respects existing PLAN/BUILD mode restrictions

## Backwards Compatibility

- Existing `rlm_orchestrator.py` NOT removed — new RLM is an alternative execution path
- When `rlm_mode` is False (default), the original agent flow runs unchanged
- All 123 existing tests continue to pass
