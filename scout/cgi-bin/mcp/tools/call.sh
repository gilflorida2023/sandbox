#!/bin/bash
set -euo pipefail

INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.name // ""')
ARGS=$(echo "$INPUT" | jq -c '.arguments // {}')

CGI_DIR="/home/scout/projects/sandbox/scout/cgi-bin/workspace"

case "$TOOL_NAME" in
    workspace.read)     "$CGI_DIR/read.py" <<< "$ARGS" ;;
    workspace.write)    "$CGI_DIR/write.py" <<< "$ARGS" ;;
    workspace.list)     "$CGI_DIR/list.py" <<< "$ARGS" ;;
    workspace.delete)   "$CGI_DIR/delete.py" <<< "$ARGS" ;;
    workspace.compile)  "$CGI_DIR/compile.py" <<< "$ARGS" ;;
    workspace.build)    "$CGI_DIR/build.py" <<< "$ARGS" ;;
    workspace.run)      "$CGI_DIR/run.py" <<< "$ARGS" ;;
    workspace.search)   "$CGI_DIR/search.py" <<< "$ARGS" ;;
    wiki.lookup)        "$CGI_DIR/wiki_lookup.py" <<< "$ARGS" ;;
    workspace.webfetch)  "$CGI_DIR/webfetch.py" <<< "$ARGS" ;;
    workspace.websearch)  "$CGI_DIR/websearch.py" <<< "$ARGS" ;;
    workspace.git_clone)  "$CGI_DIR/git_clone.py" <<< "$ARGS" ;;
    *)
        echo '{"success":false,"error":"Unknown tool: '"$TOOL_NAME"'","retryable":false}'
        exit 1
        ;;
esac
