#!/usr/bin/env bash
set -euo pipefail

# Ralph Loop — canonical style. Pure bash outer loop.
# Each iteration feeds PROMPT + AGENTS.md + plan + workspace tree
# to ralph-agent.sh, which handles the inner tool loop.
# Exits when agent outputs <promise>DONE</promise>.

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SELF_DIR"

MODE="build"
MAX_ITERATIONS=20
ITERATION=0
CLEAN=false
VERBOSE=false

for arg in "$@"; do
    case "$arg" in
        plan) MODE="plan" ;;
        --clean) CLEAN=true ;;
        -v|--verbose) VERBOSE=true ;;
        [0-9]*) MAX_ITERATIONS="$arg" ;;
    esac
done

if [ "$CLEAN" = true ]; then
    echo "[Ralph] --clean: resetting workspace"
    ollama ps 2>/dev/null | tail -n +2 | awk '{print $1}' | while read -r model; do
        ollama stop "$model" 2>/dev/null || true
    done
    find workspace/ -maxdepth 1 -not -name 'specs' | tail -n +2 | xargs rm -rf 2>/dev/null || true
    # Write fresh plan from specs
    SPEC_FILES=$(ls workspace/specs/*.md 2>/dev/null | sed 's|.*/||' | sed 's|\.md$||')
    {
        echo "# Implementation Plan"
        echo ""
        echo "## Remaining"
        while IFS= read -r spec; do
            [ -n "$spec" ] && echo "- [ ] $spec (specs/${spec}.md)"
        done <<< "$SPEC_FILES"
    } > workspace/IMPLEMENTATION_PLAN.md
    exit 0
fi

PROMPT_FILE="PROMPT_${MODE}.md"
export LLM_BUILD_MODEL="${LLM_BUILD_MODEL:-qwen2.5:7b}"
export PATH="$HOME/.local/go/bin:$PATH"
[ "$VERBOSE" = true ] && export RALPH_VERBOSE=1
[ -n "${LLM_WORKER_MODEL:-}" ] && export LLM_WORKER_MODEL

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Ralph Loop — $(date)"
echo " Mode:       $MODE"
echo " Root model: $LLM_BUILD_MODEL"
echo " Prompt:     $PROMPT_FILE"
echo " Max iters:  $MAX_ITERATIONS"
echo " Verbose:    $VERBOSE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ ! -f "$PROMPT_FILE" ] && { echo "Error: $PROMPT_FILE not found"; exit 1; }

# Check if all plan items are already completed before starting
if [ -f "workspace/IMPLEMENTATION_PLAN.md" ]; then
    ALL_DONE=$(grep -c '^- \[x\]' workspace/IMPLEMENTATION_PLAN.md 2>/dev/null || true)
    TOTAL=$(grep -c '^- \[' workspace/IMPLEMENTATION_PLAN.md 2>/dev/null || true)
    if [ "$TOTAL" -gt 0 ] && [ "$ALL_DONE" -eq "$TOTAL" ]; then
        echo "[Ralph] All tasks already completed. Nothing to do."
        exit 0
    fi
fi

while [ "$ITERATION" -lt "$MAX_ITERATIONS" ]; do
    ITERATION=$((ITERATION + 1))
    echo ""
    echo "[Ralph] Iteration $ITERATION..."

    WORKSPACE_TREE=$( (echo "  workspace/"; find workspace/ -type f -o -type d | sed 's|^workspace/|    |' | sort) 2>/dev/null || echo "  (empty)")

    {
        echo "## Instructions"
        cat "$PROMPT_FILE"
        echo ""
        echo "## Workspace Files"
        echo "$WORKSPACE_TREE"
        echo ""
        if [ -f "workspace/IMPLEMENTATION_PLAN.md" ] && [ -s "workspace/IMPLEMENTATION_PLAN.md" ]; then
            echo "## IMPLEMENTATION_PLAN.md"
            cat workspace/IMPLEMENTATION_PLAN.md
            echo ""
        fi
        if [ -f "AGENTS.md" ] && [ -s "AGENTS.md" ]; then
            echo "## AGENTS.md"
            cat AGENTS.md
            echo ""
        fi
    } | bash ralph-agent.sh && {
        echo ""
        echo "[Ralph] ✅ Task complete! DONE signal detected."
        break
    } || {
        exit_code=$?
        echo "[Ralph] Agent exit $exit_code — no DONE signal, continuing"
        echo "" >> workspace/IMPLEMENTATION_PLAN.md
        echo "## Previous iteration error (exit $exit_code)" >> workspace/IMPLEMENTATION_PLAN.md
        sleep 1
    }

    echo ""
    echo "━━━━━━━━━━━ LOOP $ITERATION COMPLETE ─────────"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Loop finished after $ITERATION iterations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
