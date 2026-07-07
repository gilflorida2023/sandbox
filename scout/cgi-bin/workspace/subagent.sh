#!/usr/bin/env bash
# subagent.sh — Replace subagent.py. Calls ralph-agent.sh for a worker prompt.
set -euo pipefail

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
MODEL=$(echo "$INPUT" | jq -r '.model // "qwen3:0.6b"')

if [ -z "$PROMPT" ]; then
    echo '{"success":false,"error":"Missing prompt parameter"}'
    exit 1
fi

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
RALPH_AGENT="$SELF_DIR/../../../ralph-agent.sh"

OUTPUT=$(LLM_BUILD_MODEL="$MODEL" bash "$RALPH_AGENT" 2>/dev/null <<< "$PROMPT") || true

if [ -z "$OUTPUT" ]; then
    echo '{"success":false,"error":"subagent produced no output"}'
    exit 1
fi

echo "{\"success\":true,\"output\":$(echo "$OUTPUT" | jq -Rs .)}"
