#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export JAVA_HOME="$HOME/.local/jdk"
export PATH="$JAVA_HOME/bin:$HOME/.local/maven/bin:$PATH"

MODE="${1:-build}"

case "$MODE" in
    build)
        echo "=== Building GFM Viewer ==="
        cd gfm-viewer
        mvn clean package -q
        echo "Build complete: gfm-viewer/target/gfm-viewer-1.0.0.jar"
        ;;
    run)
        echo "=== Running GFM Viewer ==="
        FILE="${2:-}"
        if [ -n "$FILE" ]; then
            cd gfm-viewer
            mvn javafx:run -Djavafx.args="$FILE" -q
        else
            echo "Usage: $0 run <markdown-file>"
            exit 1
        fi
        ;;
    test)
        echo "=== Running Tests ==="
        cd gfm-viewer
        mvn test
        ;;
    clean)
        rm -rf gfm-viewer/target
        echo "Cleaned"
        ;;
    *)
        echo "Usage: $0 {build|run|test|clean}"
        exit 1
        ;;
esac
