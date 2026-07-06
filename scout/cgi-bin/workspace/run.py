#!/usr/bin/env python3
"""Simple and effective runner for Go binaries and other executables."""
import json
import os
import sys
import subprocess
from pathlib import Path

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()

def main():
    """Simple and effective runner for Go binaries and other executables."""
    try:
        args = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({'success': False, 'error': 'Invalid JSON input'}))
        sys.exit(1)

    path = args.get('path', '')
    cmd_args = args.get('args', [])
    timeout = args.get('timeout', 30)
    display_output = args.get('display_output', False)

    if not path:
        print(json.dumps({'success': False, 'error': 'Missing path parameter'}))
        sys.exit(1)

    full_path = (WORKSPACE_ROOT / path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({'success': False, 'error': 'Path outside workspace'}))
        sys.exit(1)

    # Auto-detect interpreter for non-executable scripts
    interpreter = None
    if not os.access(full_path, os.X_OK):
        ext = full_path.suffix.lower()
        if ext == '.py':
            interpreter = 'python3'
        elif ext == '.sh':
            interpreter = 'bash'
        elif ext == '.pl':
            interpreter = 'perl'
        elif ext == '.rb':
            interpreter = 'ruby'
        elif ext == '.js':
            interpreter = 'node'
    cmd = [interpreter, str(full_path)] if interpreter else [str(full_path)]
    try:
        result = subprocess.run(
            cmd + cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if display_output:
            sys.stderr.write(f"Executing: [binary] {path}\n")
            if cmd_args:
                sys.stderr.write(f"Args: {cmd_args}\n")
            sys.stderr.write(f"Timeout: {timeout}s\n")
            sys.stderr.write("-" * 80 + "\n")
            if result.stdout:
                sys.stderr.write("STDOUT:\n")
                sys.stderr.write(result.stdout)
                sys.stderr.write("-" * 80 + "\n")
            if result.stderr:
                sys.stderr.write("STDERR:\n")
                sys.stderr.write(result.stderr)
                sys.stderr.write("-" * 80 + "\n")
            sys.stderr.write(f"Exit Code: {result.returncode}\n")
            sys.stderr.write("-" * 80 + "\n")
        
        print(json.dumps({
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'exit_code': result.returncode
        }))
        
    except subprocess.TimeoutExpired:
        error_msg = f'Execution timed out after {timeout}s'
        if display_output:
            sys.stderr.write(f"ERROR: {error_msg}\n")
            sys.stderr.write("-" * 80 + "\n")
        print(json.dumps({'success': False, 'error': error_msg}))
        sys.exit(1)
    except FileNotFoundError:
        error_msg = f'File not found or not executable: {path}'
        if display_output:
            sys.stderr.write(f"ERROR: {error_msg}\n")
            sys.stderr.write("-" * 80 + "\n")
        print(json.dumps({'success': False, 'error': error_msg}))
        sys.exit(1)
    except Exception as e:
        error_msg = str(e)
        if display_output:
            sys.stderr.write(f"ERROR: {error_msg}\n")
            sys.stderr.write("-" * 80 + "\n")
        print(json.dumps({'success': False, 'error': error_msg}))
        sys.exit(1)

if __name__ == '__main__':
    main()
