#!/usr/bin/env bash
set -euo pipefail

# Ralph loop — pure bash pipe. Each iteration feeds PROMPT + plan + specs + AGENTS.md
# to ralph_agent.py, which handles its own inner tool-calling loop.
# When the model produces text (no more tool calls), the iteration is done.

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
    echo "[Ralph] --clean: unloading stale models, resetting workspace/repos/ and IMPLEMENTATION_PLAN.md"
    ollama ps 2>/dev/null | tail -n +2 | awk '{print $1}' | while read -r model; do
    echo "  Unloading $model"
    ollama stop "$model" 2>/dev/null || true
    done
    rm -rf workspace/repos/*
    # Remove stale workspace scripts from previous runs
    find workspace/ -maxdepth 1 -name '*.sh' -delete
    cat > workspace/IMPLEMENTATION_PLAN.md << 'PLAN'
# Implementation Plan

## Remaining
- [ ] Clone simplesieve Go repo from GitHub
- [ ] Build Go binary using `go build`
- [ ] Run with `-c -limit 1e6`
- [ ] Verify output is 78498
PLAN
fi

if [ "$MODE" = "plan" ]; then
    PROMPT_FILE="PROMPT_plan.md"
    export LLM_BUILD_MODEL="${LLM_PLAN_MODEL:-qwen2.5:7b}"
else
    PROMPT_FILE="PROMPT_build.md"
    export LLM_BUILD_MODEL="${LLM_BUILD_MODEL:-qwen2.5:7b}"
fi

export RALPH_TEXT_ONLY=1
[ "$VERBOSE" = true ] && export RALPH_VERBOSE=1

# Go is installed at ~/.local/go/bin — ensure it's on PATH for the agent
export PATH="$HOME/.local/go/bin:$PATH"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Ralph Loop — $(date)"
echo " Mode:       $MODE"
echo " Root model: $LLM_BUILD_MODEL"
echo " Prompt:     $PROMPT_FILE"
echo " Max iters:  $MAX_ITERATIONS"
echo " Verbose:    $VERBOSE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ ! -f "$PROMPT_FILE" ] && { echo "Error: $PROMPT_FILE not found"; exit 1; }

while [ "$ITERATION" -lt "$MAX_ITERATIONS" ]; do
    echo ""
    echo "[Ralph] Iteration $((ITERATION + 1))..."

    # Build workspace context: list files so the model doesn't guess paths
    WORKSPACE_TREE=$( (echo "  workspace/"; find workspace/ -type f -o -type d | sed 's|^workspace/|    |' | sort) 2>/dev/null || echo "  (empty)")

    {
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
    } | python3 ralph_agent.py || {
        exit_code=$?
        echo "[Ralph] Agent exited ($exit_code) — logging to plan, continuing"
        echo "" >> workspace/IMPLEMENTATION_PLAN.md
        echo "## Previous iteration error (exit $exit_code)" >> workspace/IMPLEMENTATION_PLAN.md
        echo "The last agent run failed. The plan may need adjustment." >> workspace/IMPLEMENTATION_PLAN.md
        sleep 1
    }

    ITERATION=$((ITERATION + 1))
    echo ""
    echo "━━━━━━━━━━━ LOOP $ITERATION COMPLETE ━━━━━━━━━━━"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Loop finished after $ITERATION iterations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
