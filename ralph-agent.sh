#!/usr/bin/env bash
# ralph-agent.sh — Pure bash inner tool loop for local Ollama models.
# Reads prompt from stdin, calls Ollama with tools, executes tool calls,
# loops until <promise>DONE</promise> or max inner iterations.
set -euo pipefail

MAX_INNER="${MAX_INNER:-50}"
MODEL="${LLM_BUILD_MODEL:-qwen2.5:7b}"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
VERBOSE="${RALPH_VERBOSE:-0}"
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_FILE="$SELF_DIR/tool_definitions.json"

PROMPT=$(cat)

MESSAGES_FILE=$(mktemp)
MSG_FILE=$(mktemp)
cleanup() { rm -f "$MESSAGES_FILE" "$MSG_FILE" "$MSG_FILE.tmp"; }
trap cleanup EXIT

jq -n --arg prompt "$PROMPT" '[{"role":"user","content":$prompt}]' > "$MESSAGES_FILE"

[ "$VERBOSE" = "1" ] && echo "[ralph-agent] Model: $MODEL, tokens: $(wc -c <<< "$PROMPT")" >&2

declare -A FAIL_COUNTS

for ((i=1; i<=MAX_INNER; i++)); do
    [ "$VERBOSE" = "1" ] && echo "[ralph-agent] iter $i → Ollama" >&2

    MESSAGES=$(cat "$MESSAGES_FILE")
    TOOLS=$(cat "$TOOLS_FILE")

    PAYLOAD=$(jq -n \
        --arg model "$MODEL" \
        --argjson messages "$MESSAGES" \
        --argjson tools "$TOOLS" \
        '{
            model: $model,
            messages: $messages,
            tools: $tools,
            stream: false,
            options: {temperature: 0.3, num_ctx: 8192}
        }')

    RESPONSE=$(curl -s --max-time 300 "$OLLAMA_HOST/api/chat" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" 2>/dev/null) || {
        rc=$?
        echo "Ollama error: curl failed (exit $rc)" >&2
        continue
    }

    ROLE=$(echo "$RESPONSE" | jq -r '.message.role // "assistant"')
    CONTENT=$(echo "$RESPONSE" | jq -r '.message.content // ""')
    TC_RAW=$(echo "$RESPONSE" | jq -c '.message.tool_calls // []')
    NUM_TOOLS=$(echo "$TC_RAW" | jq 'length')

    [ "$VERBOSE" = "1" ] && {
        if [ "$NUM_TOOLS" -gt 0 ]; then
            echo "[ralph-agent] iter $i ← $NUM_TOOLS tool(s)" >&2
        else
            echo "[ralph-agent] iter $i ← text (${#CONTENT} chars)" >&2
        fi
    }

    # Append assistant message to conversation
    jq --arg role "$ROLE" --arg content "$CONTENT" --argjson tc "$TC_RAW" \
        '. + [{"role":$role, "content":$content, "tool_calls":$tc}]' \
        "$MESSAGES_FILE" > "$MSG_FILE" && cp "$MSG_FILE" "$MESSAGES_FILE"

    # Check for DONE signal
    if echo "$CONTENT" | grep -qF '<promise>DONE</promise>'; then
        echo "$CONTENT"
        exit 0
    fi

    # Execute tool calls (process substitution avoids subshell)
    if [ "$NUM_TOOLS" -gt 0 ]; then
        while read -r tc; do
            [ -z "$tc" ] && continue
            NAME=$(echo "$tc" | jq -r '.function.name')
            ARGS_RAW=$(echo "$tc" | jq -r '.function.arguments | if type=="string" then . else tojson end')
            TC_ID=$(echo "$tc" | jq -r '.id // "call_'$i'"')

            [ "$VERBOSE" = "1" ] && echo "[ralph-agent]  → $NAME $(echo "$ARGS_RAW" | head -c 200)" >&2

            RESULT=$(echo "$ARGS_RAW" | timeout 60 bash "$SELF_DIR/mcp_tool.sh" "$NAME" 2>/dev/null || echo '{"error":"tool execution failed or timed out"}')

            # Repeated-failure guard: if same tool+args fails 3+ times, override result
            if echo "$RESULT" | jq -e '.success == false or (.error != null and .error != "")' >/dev/null 2>&1; then
                FAIL_KEY="$NAME|$ARGS_RAW"
                COUNT="${FAIL_COUNTS[$FAIL_KEY]:-0}"
                COUNT=$((COUNT + 1))
                FAIL_COUNTS["$FAIL_KEY"]=$COUNT
                if [ "$COUNT" -ge 3 ]; then
                    RESULT='{"success":false,"error":"BLOCKER: This exact tool call has failed 3 times. STOP repeating it. Read the error messages above and completely change your approach.","blocker":true}'
                    [ "$VERBOSE" = "1" ] && echo "[ralph-agent]  ⛔ blocker: $NAME failed $COUNT times" >&2
                fi
            fi

            jq --arg id "$TC_ID" --arg result "$RESULT" \
                '. + [{"role":"tool", "content":$result, "tool_call_id":$id}]' \
                "$MESSAGES_FILE" > "$MSG_FILE" && cp "$MSG_FILE" "$MESSAGES_FILE"
        done < <(echo "$TC_RAW" | jq -c '.[]')
    fi
done

exit 1
