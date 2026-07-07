#!/usr/bin/env python3
"""Run a single shell command in the workspace root with security restrictions."""
import json, shlex, subprocess, sys
from pathlib import Path

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()

BLOCKED_COMMANDS = [
    "sudo", "apt-get", "apt", "dpkg", "dnf", "yum", "pacman",
    "pip", "pip3", "pipenv", "poetry", "conda",
    "ssh-keygen", "chsh", "passwd", "adduser", "useradd", "visudo",
    "curl", "wget", "nc", "netcat", "telnet",
]

def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    command = args.get("command", "")
    timeout = args.get("timeout", 10)

    if not command:
        print(json.dumps({"success": False, "error": "Missing command parameter"}))
        sys.exit(1)

    cmd_parts = shlex.split(command)
    base_cmd = cmd_parts[0] if cmd_parts else ""

    if base_cmd in BLOCKED_COMMANDS:
        print(json.dumps({"success": False, "error": f"Command blocked for security: {base_cmd}"}))
        sys.exit(1)

    if base_cmd == "chmod":
        cmd_parts = ["chmod"] + cmd_parts[1:]
    else:
        cmd_parts = [base_cmd] + cmd_parts[1:]

    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE_ROOT)
        )
        print(json.dumps({
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }))
    except subprocess.TimeoutExpired:
        print(json.dumps({"success": False, "error": f"Command timed out after {timeout}s"}))
        sys.exit(1)
    except FileNotFoundError:
        print(json.dumps({"success": False, "error": f"Command not found: {base_cmd}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
