#!/usr/bin/env bash
set -euo pipefail

# llm.sh - Call local Ollama from bash. Reads prompt from stdin.
# Usage: echo "prompt" | llm.sh [model]

MODEL="${1:-qwen2.5-coder:3b}"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
PROMPT=$(cat)

[ -z "$PROMPT" ] && { echo '{"error":"empty prompt"}' >&2; exit 1; }

PAYLOAD=$(jq -n --arg model "$MODEL" --arg prompt "$PROMPT" '{
    model: $model,
    messages: [{role: "user", content: $prompt}],
    stream: false,
    options: {temperature: 0.3, num_ctx: 8192}
}')

RESPONSE=$(curl -s --max-time 300 \
    "$OLLAMA_HOST/api/chat" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

ERROR=$(echo "$RESPONSE" | jq -r '.error // empty')
[ -n "$ERROR" ] && { echo "LLM ERROR: $ERROR" >&2; exit 1; }

echo "$RESPONSE" | jq -r '.message.content // empty'
