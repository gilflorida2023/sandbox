#!/bin/bash
set -euo pipefail

SCOUT_DIR="/home/scout/projects/sandbox/scout"
BIN_DIR="$SCOUT_DIR/bin"
CGI_DIR="$SCOUT_DIR/cgi-bin"

echo "=== Starting Scout CGI MCP Server ==="

find "$CGI_DIR" -name "*.py" -exec chmod +x {} \;

if [[ ! -x "$BIN_DIR/scout" ]] || [[ "$SCOUT_DIR/scout.go" -nt "$BIN_DIR/scout" ]]; then
    echo "Building scout.go..."
    cd "$SCOUT_DIR"
    go build -o "$BIN_DIR/scout" scout.go
fi

echo "Starting Scout on :8080..."
exec "$BIN_DIR/scout"
