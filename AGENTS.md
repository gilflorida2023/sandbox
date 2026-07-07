# AGENTS.md — Constitution

## Workflow
- Read IMPLEMENTATION_PLAN.md and pick the highest-priority task
- Work on it using the available tools
- When a task is complete, verify it (read files, run commands, check output)
- Update IMPLEMENTATION_PLAN.md to mark progress
- When ALL tasks are complete, output `<promise>DONE</promise>`

## Tools
- workspace.read: Read files (path relative to workspace root)
- workspace.write: Write files (path + content)
- workspace.list: List directory contents
- workspace.run: Execute scripts/binaries (path, args[], timeout)
- workspace.search: Grep-like file search
- workspace.compile: Syntax check (go, python, c, cpp, rust)
- workspace.git_clone: Clone a git repo (url, path under repos/)
- workspace.delete: Delete files/dirs (recursive:true for dirs)
- workspace.subagent: Delegate multi-step work to a worker subagent

## Tool Rules
- Paths are relative to workspace root. Do NOT prefix with "workspace/"
- workspace.run runs scripts from workspace/ as CWD. `cd repos/simplesieve` works.
- For Go build: write a .sh script, then workspace.run it
- NEVER pass a directory to workspace.run

## Safety
- NEVER write to .netrc, .ssh/, id_rsa, .git-credentials, authorized_keys, known_hosts
- NEVER run ssh-keygen, sudo, apt-get, chsh, passwd, adduser, useradd, visudo
- These are blocked anyway — don't waste iterations on them

## Scope
- Your ONLY job is the items in IMPLEMENTATION_PLAN.md
- Do NOT install software or modify system configuration
- If a tool returns "command not found", report it as a blocker — do NOT try to install it

## Go
- Go is at ~/.local/go/bin/go. It's already on PATH.
- simplesieve repo is a Go project at repos/simplesieve/
- Build: `cd repos/simplesieve && go build -o simplesieve`
- Run: `cd repos/simplesieve && ./simplesieve -c -limit 1e6`
- Expected output: 78498

## Completion Signal
- When ALL tasks are complete and verified, output `<promise>DONE</promise>`
- Do NOT output this until you've verified the results
