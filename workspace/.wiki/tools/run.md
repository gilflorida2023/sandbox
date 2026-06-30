# Tool: workspace.run

## Description
Execute source code, scripts, or binaries. **Auto-compiles C, C++, Go, and Rust** before running. No separate compile step needed.

## Parameters
- `path` (string, required): Source file or binary path relative to workspace root
- `args` (array of strings, optional): Command line arguments
- `timeout` (integer, optional, default: 30): Timeout in seconds

## Auto-compile behavior
| File type | Action |
|-----------|--------|
| `.c` | `gcc -o <name> <file> && ./<name>` |
| `.cpp` `.cc` `.cxx` | `g++ -o <name> <file> && ./<name>` |
| `.go` | `go build -o <name> <file> && ./<name>` |
| `.rs` | `rustc -o <name> <file> && ./<name>` |
| `.py` | `python3 <file>` |
| `.sh` | `bash <file>` |
| binary (no extension) | execute directly |
| system command (`sha256sum`, `ls`) | run with PATH lookup |

## Returns
```json
{
  "success": true,
  "stdout": "program output...",
  "stderr": "error output...",
  "exit_code": 0
}
```

On compile failure:
```json
{
  "success": false,
  "compile_error": true,
  "language": "c",
  "output": "compiler error messages..."
}
```

## Example
```json
{"name": "workspace.run", "arguments": {"path": "sieve.c", "timeout": 10}}
{"name": "workspace.run", "arguments": {"path": "sha256sum", "args": ["out.txt"]}}
{"name": "workspace.run", "arguments": {"path": "script.sh"}}
```

## Notes
- Working directory is workspace root
- Compilation is cached by source mtime — re-runs skip recompilation if source unchanged
- On compile failure, fix the errors and retry
