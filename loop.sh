#!/usr/bin/env bash
set -euo pipefail

# Ralph loop — multi-turn tool calling via ralph_agent.py.
# Each loop iteration: one full cycle of LLM thinking + tool execution.
# The agent handles one Ollama turn at a time; loop.sh manages conversation state.

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SELF_DIR"

MODE="build"
MAX_ITERATIONS=20
ITERATION=0

for arg in "$@"; do
    case "$arg" in
        plan) MODE="plan" ;;
        [0-9]*) MAX_ITERATIONS="$arg" ;;
    esac
done

if [ "$MODE" = "plan" ]; then
    PROMPT_FILE="PROMPT_plan.md"
    export LLM_BUILD_MODEL="${LLM_PLAN_MODEL:-qwen2.5:7b}"
else
    PROMPT_FILE="PROMPT_build.md"
    export LLM_BUILD_MODEL="${LLM_BUILD_MODEL:-qwen3:0.6b}"
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Ralph Loop — $(date)"
echo " Mode:       $MODE"
echo " Model:      $LLM_BUILD_MODEL"
echo " Prompt:     $PROMPT_FILE"
echo " Max iters:  $MAX_ITERATIONS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ ! -f "$PROMPT_FILE" ] && { echo "Error: $PROMPT_FILE not found"; exit 1; }

# Build initial user message
USER_MSG=$(cat "$PROMPT_FILE")
if [ -f "workspace/IMPLEMENTATION_PLAN.md" ] && [ -s "workspace/IMPLEMENTATION_PLAN.md" ]; then
    USER_MSG="$USER_MSG"$'\n\n## Current Implementation Plan\n'"$(cat workspace/IMPLEMENTATION_PLAN.md)"
fi
if [ -f "AGENTS.md" ] && [ -s "AGENTS.md" ]; then
    USER_MSG="$USER_MSG"$'\n\n## Project Context\n'"$(cat AGENTS.md)"
fi

# Initialize conversation as JSON
CONVERSATION=$(python3 -c "
import json, sys
sys.stdout.write(json.dumps([{'role': 'user', 'content': sys.stdin.read()}]))
" <<< "$USER_MSG")

while true; do
    [ "$MAX_ITERATIONS" -gt 0 ] && [ "$ITERATION" -ge "$MAX_ITERATIONS" ] && break

    echo "[Ralph] Iteration $((ITERATION + 1)) — $LLM_BUILD_MODEL..."

    # Inner loop: keep calling agent until it produces text (no tool calls)
    MAX_INNER=20
    INNER=0
    FINAL_TEXT=""
    AGENT_CONV="$CONVERSATION"

    while [ "$INNER" -lt "$MAX_INNER" ]; do
        NEW_CONV=$(echo "$AGENT_CONV" | python3 ralph_agent.py 2>/tmp/agent_err.log) || {
            echo "[Ralph] Agent error:"; cat /tmp/agent_err.log; exit 1
        }

        # Check if the last message has content (text) and no new tool calls
        LAST=$(echo "$NEW_CONV" | python3 -c "
import json, sys
conv = json.load(sys.stdin)
last = conv[-1] if conv else {}
is_tool = last.get('role') == 'tool'
content = last.get('content', '')
if last.get('role') == 'assistant' and content:
    print('TEXT:' + content[:500])
elif last.get('role') == 'assistant' and last.get('tool_calls'):
    print('TOOLS')
elif is_tool:
    print('TOOL_RESULT')
else:
    print('UNKNOWN')
")

        AGENT_CONV="$NEW_CONV"

        case "$LAST" in
            TEXT:*)
                FINAL_TEXT="${LAST#TEXT:}"
                break
                ;;
            TOOLS)
                # Continue inner loop — more tool calls to process
                INNER=$((INNER + 1))
                continue
                ;;
            TOOL_RESULT)
                # Tool result means we need another assistant turn
                INNER=$((INNER + 1))
                continue
                ;;
            *)
                # Model produced no tool calls but also no text?
                # Could be the model is done
                FINAL_TEXT=$(echo "$NEW_CONV" | python3 -c "
import json, sys
conv = json.load(sys.stdin)
for m in reversed(conv):
    if m.get('role') == 'assistant' and m.get('content'):
        print(m['content'][:500])
        break
")
                break
                ;;
        esac
    done

    if [ -n "$FINAL_TEXT" ]; then
        echo "---"
        echo "$FINAL_TEXT"
        echo "---"
    else
        echo "[Ralph] No text produced (all tool calls)"
    fi

    # Update conversation for next outer iteration (keep the history)
    CONVERSATION="$AGENT_CONV"

    # Unload model from GPU memory to minimize concurrent LLMs
    ollama stop "$LLM_BUILD_MODEL" 2>/dev/null || true

    ITERATION=$((ITERATION + 1))
    echo -e "\n━━━━━━━━━━━ LOOP $ITERATION COMPLETE ━━━━━━━━━━━\n"
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Loop finished after $ITERATION iterations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
