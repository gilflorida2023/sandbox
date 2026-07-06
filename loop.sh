#!/usr/bin/env bash
set -euo pipefail

# Ralph-style bash loop for local Ollama + MCP tools.
# The LLM outputs tool calls as lines:  ##mcp_tool <name> <json-args>
# loop.sh parses, executes, feeds results back.

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SELF_DIR"

MODE="build"
MAX_ITERATIONS=20
ITERATION=0
INTERACTIVE=false

for arg in "$@"; do
    case "$arg" in
        -i|--interactive) INTERACTIVE=true ;;
        plan) MODE="plan" ;;
        [0-9]*) MAX_ITERATIONS="$arg" ;;
    esac
done

if [ "$MODE" = "plan" ]; then
    PROMPT_FILE="PROMPT_plan.md"
    LLM_MODEL="${LLM_PLAN_MODEL:-qwen3:1.7b}"
else
    PROMPT_FILE="PROMPT_build.md"
    LLM_MODEL="${LLM_BUILD_MODEL:-qwen2.5-coder:3b}"
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Ralph Loop — $(date)"
echo " Mode:       $MODE"
echo " Model:      $LLM_MODEL"
echo " Prompt:     $PROMPT_FILE"
echo " Max iters:  $MAX_ITERATIONS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ ! -f "$PROMPT_FILE" ] && { echo "Error: $PROMPT_FILE not found"; exit 1; }

# Accumulated tool results to feed back into context
TOOL_HISTORY=""

while true; do
    [ "$MAX_ITERATIONS" -gt 0 ] && [ "$ITERATION" -ge "$MAX_ITERATIONS" ] && break

    # Build prompt: base + plan + agents + tool history
    PROMPT=$(cat "$PROMPT_FILE")
    if [ -f "workspace/IMPLEMENTATION_PLAN.md" ] && [ -s "workspace/IMPLEMENTATION_PLAN.md" ]; then
        PROMPT="$PROMPT"$'\n\n## Current Implementation Plan\n'"$(cat workspace/IMPLEMENTATION_PLAN.md)"
    fi
    [ -f "AGENTS.md" ] && [ -s "AGENTS.md" ] && \
        PROMPT="$PROMPT"$'\n\n## Project Context\n'"$(cat AGENTS.md)"
    [ -n "$TOOL_HISTORY" ] && \
        PROMPT="$PROMPT"$'\n\n## Results from previous iteration\n'"$TOOL_HISTORY"

    if [ "$INTERACTIVE" = true ] && [ "$ITERATION" -eq 0 ]; then
        echo "Paste extra context (Ctrl-D to end):"
        EXTRA=$(cat)
        [ -n "$EXTRA" ] && PROMPT="$PROMPT"$'\n\n## User Instructions\n'"$EXTRA"
    fi

    echo "[Ralph] Iteration $((ITERATION + 1)) — $LLM_MODEL..."
    RESPONSE=$(echo "$PROMPT" | bash llm.sh "$LLM_MODEL" 2>/tmp/ralph_err.log) || {
        echo "[Ralph] LLM call failed:"; cat /tmp/ralph_err.log; exit 1
    }
    [ -z "$RESPONSE" ] && { echo "[Ralph] Empty response"; break; }

    echo "$RESPONSE"

    # Parse and execute tool calls: ##mcp_tool <name> <json-args>
    TOOL_HISTORY=""
    while IFS= read -r line; do
        if [[ "$line" =~ ^##mcp_tool\ ([a-z._]+)\ (.*) ]]; then
            TOOL="${BASH_REMATCH[1]}"
            ARGS="${BASH_REMATCH[2]}"
            echo "[exec] $TOOL $ARGS"
            RESULT=$(echo "$ARGS" | bash mcp_tool.sh "$TOOL" 2>/tmp/tool_err.log) || {
                RESULT="{\"error\":\"$(cat /tmp/tool_err.log)\"}"
            }
            echo "$RESULT" | python3 -m json.tool 2>/dev/null || echo "$RESULT"
            TOOL_HISTORY="$TOOL_HISTORY"$'\n'"##mcp_result $TOOL $RESULT"
        fi
    done <<< "$RESPONSE"

    ITERATION=$((ITERATION + 1))
    echo -e "\n━━━━━━━━━━━ LOOP $ITERATION COMPLETE ━━━━━━━━━━━\n"
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Loop finished after $ITERATION iterations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
