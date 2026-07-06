#!/usr/bin/env python3
import json, sys, os
from pathlib import Path

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()

def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        print(json.dumps({"success": False, "error": "Missing path parameter"}))
        sys.exit(1)

    full_path = (WORKSPACE_ROOT / path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Path outside workspace"}))
        sys.exit(1)

    blocked_paths = [
        ".netrc", "._netrc", ".git-credentials", ".gitconfig",
        "authorized_keys", "known_hosts",
        ".ssh/", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ]
    for bp in blocked_paths:
        if bp in full_path.name or (bp.endswith("/") and bp.rstrip("/") in str(full_path)):
            print(json.dumps({"success": False, "error": f"Blocked path: {path}. Writing to {bp} is not allowed."}))
            sys.exit(1)

    blocked_content = [
        "ssh-keygen", "credential.helper", "chsh", "passwd",
        "adduser", "useradd", "visudo", "sudo ",
    ]
    for bc in blocked_content:
        if bc in content:
            print(json.dumps({"success": False, "error": f"Blocked content: script contains '{bc}'. Not allowed."}))
            sys.exit(1)

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    bytes_written = len(content.encode("utf-8"))
    print(json.dumps({"success": True, "path": path, "bytes_written": bytes_written}))

if __name__ == "__main__":
    main()
