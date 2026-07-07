# AGENTS.md — Constitution

## Workflow
1. **Read specs first** — `workspace.list {"path":"specs"}` then `workspace.read` every `.md` file in specs/
2. Read IMPLEMENTATION_PLAN.md and pick the highest-priority unchecked task
3. Work on it using the available tools
4. When a task is complete, verify it (read files, run commands, check output)
5. Update IMPLEMENTATION_PLAN.md to mark the item `[x]` with a summary of what was created
6. When ALL tasks are complete and verified, output `<promise>DONE</promise>`

## Critical Rules — Read These Carefully
- If a tool returns `"success": false` or an error field, **DO NOT retry the same call**. Read the error, understand why it failed, and try a COMPLETELY different approach.
- If a tool returns a "BLOCKER" error saying it failed 3 times, you MUST change your strategy — do NOT repeat the same call again.
- Always use the EXACT URL, path, and filename from spec files. Do NOT guess or hallucinate.
- For Go projects: first clone, then write a build script (build.sh), then workspace.run the script.

## Tools
- workspace.read: Read files (path relative to workspace root)
- workspace.write: Write files (path + content)
- workspace.list: List directory contents (use "." for root)
- workspace.run: Execute scripts/binaries (path, args[], timeout). Workspace root is CWD.
- workspace.search: Grep-like file search
- workspace.compile: Syntax check (go, python, c, cpp, rust)
- workspace.git_clone: Clone a git repo (url, path under repos/)
- workspace.delete: Delete files/dirs (recursive:true for dirs)
- workspace.subagent: Delegate multi-step work to a worker subagent

## Tool Rules
- Paths are relative to workspace root. Do NOT prefix with "workspace/"
- workspace.run runs scripts from workspace/ as CWD. `cd repos/simplesieve` in .sh scripts works.
- For Go build: write a .sh script, then workspace.run it
- NEVER pass a directory to workspace.run
- workspace.run on a .sh file auto-runs with bash. workspace.run on a .py file auto-runs with python3.

## Where Files Go
- **User code / build scripts** → workspace/ root (e.g. `workspace.read {"path":"build.sh"}`)
- **Git clones** → workspace/repos/ (e.g. `workspace.git_clone {"path":"repos/project"}`)
- **Test images** → workspace/ root or workspace/examples/
- **New tool scripts (*.py)** → write to workspace/tools/ first (e.g. `workspace.write {"path":"tools/my_tool.py","content":"..."}`), then call `workspace.deploy_tool {"source":"tools/my_tool.py","tool_name":"my_tool"}` to install it into scout/cgi-bin/workspace/ and register it.
- **You CANNOT write directly to scout/cgi-bin/workspace/** via workspace.write — the path is outside the workspace sandbox. Use workspace.deploy_tool instead.

## Subagent
- For any multi-step task (clone+build, build+run, search+analyze), delegate to a subagent instead of doing it inline:
  ```
  workspace.subagent {
    "prompt": "Clone https://github.com/gilflorida2023/simplesieve into repos/simplesieve. Write build.sh: 'cd repos/simplesieve && go build -o simplesieve'. Run build.sh. Then run ./simplesieve -c -limit 1e6 in repos/simplesieve. Report stdout and exit code.",
    "model": "qwen3:0.6b"
  }
  ```
- The subagent returns a summary. Do NOT delegate trivial single-step calls (read, list).

## Safety
- NEVER write to .netrc, .ssh/, id_rsa, .git-credentials, authorized_keys, known_hosts
- NEVER run ssh-keygen, sudo, apt-get, chsh, passwd, adduser, useradd, visudo
- These are blocked anyway — don't waste iterations on them

## Scope
- **Project goal:** Build a graphical GFM rendering tool in Java — see
  `workspace/specs/GOAL-build-gfm-graphical-viewer-java.md`.
- Your ONLY job is the items in IMPLEMENTATION_PLAN.md
- Do NOT install software or modify system configuration
- If a tool returns "command not found", report it as a blocker — do NOT try to install it

## Go
- Go is at ~/.local/go/bin/go. It's already on PATH.
- simplesieve repo is a Go project at repos/simplesieve/
- Build: `cd repos/simplesieve && go build -o simplesieve`
- Run: `cd repos/simplesieve && ./simplesieve -c -limit 1e6`
- Expected output: 78498

## Java
- JDK 21 is at `~/.local/jdk`. Set `JAVA_HOME=~/.local/jdk` (also exported by `build.sh`).
- Maven 3.9.16 is at `~/.local/maven` (`~/.local/maven/bin/mvn`).
- JavaFX 22 is pulled via Maven (`org.openjfx:javafx-controls`, `javafx-web`).
- Project: `gfm-viewer/` — a JavaFX GFM graphical viewer. Architecture in
  `workspace/specs/GOAL-build-gfm-graphical-viewer-java.md`.
- Compile & package (produces the runnable shaded jar):
    cd gfm-viewer && mvn clean package -q
    # → gfm-viewer/target/gfm-viewer-1.0.0.jar
  (or simply `bash build.sh build` from the workspace root)
- Run the GUI (needs a display):
    cd gfm-viewer && mvn javafx:run -Djavafx.args="<file.md>" -q
    # or `bash build.sh run <file.md>`
- Test (runs `gfm.SpecExampleTest` against the GFM spec):
    cd gfm-viewer && mvn test
    # or `bash build.sh test`
- Headless render: the parser/renderer in `gfm.parser` have NO JavaFX
  dependency and can be run without a display once a headless entry point
  (e.g. `gfm.parser.GfmRender`) is added:
    java -cp gfm-viewer/target/gfm-viewer-1.0.0.jar gfm.parser.GfmRender <file.md>
- Markdown spec: https://github.github.com/gfm/
- Project goal spec: `workspace/specs/GOAL-build-gfm-graphical-viewer-java.md`.

## Completion Signal
- When ALL tasks are complete and verified, output `<promise>DONE</promise>`
- Do NOT output this until you've verified the results
