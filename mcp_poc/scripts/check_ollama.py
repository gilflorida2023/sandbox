#!/usr/bin/env python3
"""Check Ollama health and restart if stale.

Criteria for "stale": GET /api/tags responds OK but POST /api/chat hangs or
errors out. This means the Ollama process is listening but can't run models
— it needs a restart.

Usage:
  python3 scripts/check_ollama.py                     # check only (exit 0/1)
  python3 scripts/check_ollama.py --restart            # auto-restart via SSH
  python3 scripts/check_ollama.py --restart --host m4@192.168.0.7
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request

OLLAMA_BASE = "http://localhost:11434"
SSH_HOST = "m4@192.168.0.7"


def http_get(path: str) -> int:
    try:
        resp = urllib.request.urlopen(f"{OLLAMA_BASE}{path}", timeout=5)
        return resp.status
    except Exception:
        return 0


def http_post(path: str, body: dict) -> int:
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{OLLAMA_BASE}{path}", data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status
    except Exception:
        return 0


def tags_ok() -> bool:
    return http_get("/api/tags") == 200


def chat_ok(model: str = "qwen3:0.6b") -> bool:
    return http_post("/api/chat", {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0},
    }) == 200


def restart_via_ssh(host: str = SSH_HOST) -> bool:
    cmds = (
        f"ssh {host} "
        f"\"export PATH=/usr/local/bin:/Applications/Ollama.app/Contents/Resources:\\$PATH && "
        f"pkill -9 ollama 2>/dev/null; sleep 2; "
        f"ollama serve &>/dev/null &\"" 
    )
    try:
        subprocess.run(cmds, shell=True, timeout=15)
        import time
        time.sleep(3)
        return True
    except Exception as e:
        print(f"  restart failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Check Ollama health")
    parser.add_argument("--restart", action="store_true", help="Auto-restart if stale")
    parser.add_argument("--host", default=SSH_HOST, help="SSH host for restart")
    args = parser.parse_args()

    tags = tags_ok()
    chat = chat_ok()

    if tags and chat:
        print("OK")
        return 0

    if not tags:
        print("DOWN (tags endpoint not responding)")
        return 1

    # tags OK but chat fails → stale
    print("STALE (tags OK, chat fails)")

    if args.restart:
        print("  restarting Ollama via SSH...", end=" ", flush=True)
        if restart_via_ssh(args.host):
            if chat_ok():
                print("OK")
                return 0
            print("still failing after restart")
            return 1
        print("failed")
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
