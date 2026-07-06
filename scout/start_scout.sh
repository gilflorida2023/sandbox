#!/bin/bash
set -euo pipefail

SCOUT_DIR="/home/scout/projects/sandbox/scout"
echo "=== Starting Scout CGI MCP Server (Python) ==="
exec python3 "$SCOUT_DIR/scout.py"
