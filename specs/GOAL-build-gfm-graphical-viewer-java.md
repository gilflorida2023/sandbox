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
See AGENTS.md "## Java" for the toolchain and exact commands. Summary:
- Build:    `bash build.sh build`        (→ `gfm-viewer/target/gfm-viewer-1.0.0.jar`)
- Test:     `bash build.sh test`         (runs `SpecExampleTest` against GFM spec)
- Run GUI:  `bash build.sh run <file.md>`(launches the JavaFX viewer)

## Deliverable
A working JavaFX GFM viewer. Optionally, add a headless render entry point
(`gfm.parser.GfmRender`) and deploy it as a scout tool `workspace.gfm_render`
so the renderer is callable without the GUI.
