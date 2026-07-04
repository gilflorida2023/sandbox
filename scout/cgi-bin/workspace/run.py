#!/usr/bin/env python3
"""Simple and effective runner for Go binaries and other executables."""
import json
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

    try:
        result = subprocess.run(
            [str(full_path)] + cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if display_output:
            print(f"Executing: [binary] {path}")
            if cmd_args:
                print(f"Args: {cmd_args}")
            print(f"Timeout: {timeout}s")
            print("-" * 80)
            if result.stdout:
                print("STDOUT:")
                print(result.stdout)
                print("-" * 80)
            if result.stderr:
                print("STDERR:")
                print(result.stderr)
                print("-" * 80)
            print(f"Exit Code: {result.returncode}")
            print("-" * 80)
        
        print(json.dumps({
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'exit_code': result.returncode
        }))
        
    except subprocess.TimeoutExpired:
        error_msg = f'Execution timed out after {timeout}s'
        if display_output:
            print(f"ERROR: {error_msg}")
            print("-" * 80)
        print(json.dumps({'success': False, 'error': error_msg}))
        sys.exit(1)
    except FileNotFoundError:
        error_msg = f'File not found or not executable: {path}'
        if display_output:
            print(f"ERROR: {error_msg}")
            print("-" * 80)
        print(json.dumps({'success': False, 'error': error_msg}))
        sys.exit(1)
    except Exception as e:
        error_msg = str(e)
        if display_output:
            print(f"ERROR: {error_msg}")
            print("-" * 80)
        print(json.dumps({'success': False, 'error': error_msg}))
        sys.exit(1)

if __name__ == '__main__':
    main()
