# RLM Development Roadmap

## Phase 1 — Make It Work ✓
- [x] Trim system prompt to match test-proven format (~120 tokens, no markdown sections, exact examples per tool)
- [x] Add exact `workspace.run` example to prompt
- [x] Auto-switch to BUILD mode on `/rlm` toggle
- [x] Default to `qwen3:0.6b` in config.yaml (already done — `ollama.model`)

## Phase 2 — Error Recovery & Robustness
- [ ] Teach model to retry after tool failures instead of calling FINAL
- [ ] Add `ast.parse()` validation before execution (catch syntax errors before they waste an iteration)
- [ ] Improve loop detection to fire on N similar (not identical) code blocks
- [ ] Log raw model response + extracted code to help debug future failures

## Phase 3 — Quality of Life
- [ ] Add Writer model (third tier — formats tool output into prose)
- [ ] Configurable sub-LLM model (separate from Root model)
- [ ] Move `checkem_rlm.sh` into `mcp_poc/scripts/`
- [ ] Show per-iteration timing in terminal output

## Phase 4 — Advanced / Aspirational
- [ ] **Multi-model orchestration** — different models for Root, Sub, Writer roles
- [ ] **RLM self-improvement** — model learns from its own tool call logs (`rlm_tool_calls.jsonl`)
- [ ] **Parallel sub-tasks (fork-join)** — launch multiple independent sub-LLM queries concurrently, merge results
- [ ] **Persistent RLM state** — save/restore RLM history across sessions for `/resume`
- [ ] **Autonomous research** — RLM given a broad question, autonomously searches wiki + web + codebase, produces a report
- [ ] **RLM fine-tuning** — fine-tune qwen3:0.6b on successful RLM trajectories
- [ ] **Budget-aware scheduling** — dynamically adjust max_iters and model size based on task complexity
