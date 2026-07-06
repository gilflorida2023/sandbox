#!/usr/bin/env bash
set -euo pipefail

# mcp_tool.sh - Call MCP tools via scout CGI scripts directly.
# Usage: mcp_tool.sh <tool_name> '<json_arguments>'
# Examples:
#   mcp_tool.sh workspace.read '{"path":"test.txt"}'
#   mcp_tool.sh workspace.write '{"path":"test.txt","content":"hello"}'
#   mcp_tool.sh workspace.run '{"path":"test.py","timeout":10}'
#   mcp_tool.sh workspace.search '{"pattern":"main"}'
#   mcp_tool.sh wiki.lookup '{"topic":"webfetch"}'
#   mcp_tool.sh workspace.webfetch '{"url":"https://example.com"}'

TOOL_NAME="${1:?Usage: mcp_tool.sh <tool_name> [json_args]}"
ARGS="${2:-$(cat)}"
[ -z "$ARGS" ] && ARGS="{}"

CGI_DIR="/home/scout/projects/sandbox/scout/cgi-bin/workspace"

case "$TOOL_NAME" in
    workspace.read)     script="$CGI_DIR/read.py" ;;
    workspace.write)    script="$CGI_DIR/write.py" ;;
    workspace.list)     script="$CGI_DIR/list.py" ;;
    workspace.delete)   script="$CGI_DIR/delete.py" ;;
    workspace.compile)  script="$CGI_DIR/compile.py" ;;
    workspace.build)    script="$CGI_DIR/build.py" ;;
    workspace.run)      script="$CGI_DIR/run.py" ;;
    workspace.search)   script="$CGI_DIR/search.py" ;;
    wiki.lookup)        script="$CGI_DIR/wiki_lookup.py" ;;
    workspace.webfetch) script="$CGI_DIR/webfetch.py" ;;
    workspace.websearch) script="$CGI_DIR/websearch.py" ;;
    workspace.git_clone) script="$CGI_DIR/git_clone.py" ;;
    *)
        echo "{\"success\":false,\"error\":\"Unknown tool: $TOOL_NAME\"}"
        exit 1
        ;;
esac

echo "$ARGS" | python3 "$script"
