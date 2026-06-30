#!/usr/bin/env python3
import json

workspace_root = "/home/scout/projects/sandbox/workspace"

source_file = f"{workspace_root}/primegen.go"
result = {
    "path": "primegen.go",
    "timeout": 30
}

with open(source_file, 'w') as f:
    f.write("""package main

import (
    \"crypto/sha256\"
    \"encoding/hex\"
    \"fmt\"
)

func main() {
    hash := sha256.Sum256([]byte("hello world"))
    fmt.Println(hex.EncodeToString(hash[:]))
}""")

print(json.dumps(result, indent=2))
