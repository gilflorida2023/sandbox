# GOAL — Build a Graphical GFM Rendering Tool in Java

## Objective
Build a **graphical** GitHub-Flavored-Markdown rendering tool written in **Java**
(JavaFX). This is the project's target goal spec.

## Repository
- `gfm-viewer/` — a Java 21 / JavaFX 22 / Maven project.
- Build/run wrapper: `bash build.sh {build|run|test|clean}`

## Architecture
- `gfm.parser` (headless, no JavaFX dependency):
  - `BlockParser` — parses Markdown text into an `AstNode` document tree
  - `InlineParser` — parses inline elements (emphasis, links, code spans, …)
  - `HtmlRenderer` — renders an `AstNode` tree to HTML
  - `AstNode` — the AST node type
- `gfm.viewer.MarkdownViewer` — the JavaFX GUI that loads a `.md` file,
  renders it via the parser + `HtmlRenderer`, and displays it in a `WebView`.

## Additional / reference spec (do NOT treat as the project)
The 44 `workspace/specs/gfm-language/*` files (e.g. `1-4-about-this-documentmd`,
`6-4-emphasis-and-strong-emphasismd`) plus `index.json` (in `gfm-language/`) are
the **GFM language specification** — a conformance *reference*, not a task list.
They are exercised by `gfm.SpecExampleTest` (`mvn test`). Read them only to
validate parser behavior, never as the definition of the project.

## How to build / test / run (Java)
The tool sandbox does NOT have Maven/Java on its PATH, so build via a
`workspace/`-local script (mirrors the Go pattern in AGENTS.md):
1. `workspace.write` a script `build.sh` in `workspace/`:
    #!/usr/bin/env bash
    export JAVA_HOME="$HOME/.local/jdk"
    export PATH="$JAVA_HOME/bin:$HOME/.local/maven/bin:$PATH"
    cd /home/scout/projects/sandbox/gfm-viewer
    mvn clean package -q
2. `workspace.run {"path":"build.sh", "timeout":300}` (use a large timeout).
- Build:  `mvn clean package -q` → `gfm-viewer/target/gfm-viewer-1.0.0.jar`
- Test:   `mvn test`             → runs `gfm.SpecExampleTest` against the GFM spec
- Run GUI:`mvn javafx:run -Djavafx.args="<file.md>"` (needs a display)
See AGENTS.md "## Java" for full detail.

## Deliverable
A working JavaFX GFM viewer. Optionally, add a headless render entry point
(`gfm.parser.GfmRender`) and deploy it as a scout tool `workspace.gfm_render`
so the renderer is callable without the GUI.
