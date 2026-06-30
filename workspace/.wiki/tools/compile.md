# Tool: workspace.compile

## Description
Compile source code explicitly (optional). **`workspace.run` auto-compiles before executing** — use this only when you need to check compilation separately.

## Parameters
- `path` (string, required): Path to source file relative to workspace root
- `language` (string, optional): "go", "python", "c", "cpp", "rust", or "auto" (default: auto-detect from extension)

## Returns
```json
{
  "success": true,
  "language": "go",
  "binary": "main",
  "output": "compilation output..."
}
```

## Notes
- Prefer `workspace.run` for most tasks — it handles compile + run in one step
- For Python: validates syntax (py_compile), no binary produced
- For Rust: requires Cargo.toml
