#!/usr/bin/env python3
"""Pipeline framework — multi-phase LLM orchestration with persistent working memory.

Each pipeline runs as a sequence of phases. Phases can be:
- Single LLM call with structured output
- Batch over items from a previous phase (sequential, one LLM call per item)

All phase outputs are persisted to .context/<session_id>/ for crash recovery,
resume, and inspection.  Pipeline only touches paths under config.workspace.path
and config.context.path (defaults to workspace/.context).
"""

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Callable

from config import config
from ollama_client import OllamaClient
from rich.console import Console
from rich.markdown import Markdown

logger = logging.getLogger(__name__)

SANDBOX_ROOT = Path(config.workspace.path).resolve()


def _safe_path(resource: str) -> Path:
    """Resolve a workspace-relative path, ensuring it stays inside the sandbox."""
    p = (SANDBOX_ROOT / resource).resolve()
    if not str(p).startswith(str(SANDBOX_ROOT)):
        raise ValueError(f"Path '{resource}' resolves outside sandbox ({p})")
    return p


# ── Base Pipeline ──────────────────────────────────────────────────────────

class Pipeline:
    """Base class for multi-phase analysis workflows.

    Subclasses override `_run(task)` to orchestrate phases using:
      - self._phase()      — single LLM call
      - self._phase_batch()— one LLM call per item (sequential)
      - self._read_file()  — safe file read within workspace

    Each phase is persisted to .context/<session_id>/<name>.json + .md.
    Resume is automatic: already-completed phases are skipped.
    """

    name: str = "unnamed"
    description: str = ""

    def __init__(self):
        self.ollama = OllamaClient()

        ctx_path = getattr(config, "context", None)
        if ctx_path and hasattr(ctx_path, "path"):
            self.context_path = Path(ctx_path.path)
        else:
            self.context_path = Path(config.workspace.path) / ".context"
        self.context_path.mkdir(parents=True, exist_ok=True)

        self.session_id: str = ""
        self.session_dir: Path = Path()
        self.manifest: dict = {}
        self._tokens_used: int = 0

    # ── Public API ──────────────────────────────────────────────────────

    async def run(self, task: str, session_id: Optional[str] = None,
                  resume: bool = False) -> dict:
        """Execute the pipeline.  Creates or resumes a session."""
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.session_dir = self.context_path / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = self.session_dir / "manifest.json"
        if resume and manifest_path.exists():
            self.manifest = json.loads(manifest_path.read_text())
            logger.info("Resumed session %s (%d phases done)",
                        self.session_id, len(self.manifest.get("completed_phases", [])))
        else:
            self.manifest = {
                "session_id": self.session_id,
                "workflow": self.name,
                "task": task[:500],
                "created_at": datetime.now().isoformat(),
                "completed_phases": [],
                "tokens_used": 0,
                "status": "running",
            }
        self._save_manifest()

        try:
            result = await self._run(task)
            self.manifest["status"] = "complete"
            self.manifest["tokens_used"] = self._tokens_used
            self._save_manifest()
            return result
        except Exception:
            self.manifest["status"] = "failed"
            self._save_manifest()
            raise

    async def close(self):
        await self.ollama.close()

    # ── Phase helpers (to be called from _run) ──────────────────────────

    async def _phase(self, name: str, system: Optional[str] = None,
                     user: Optional[str] = None,
                     output_schema: Optional[dict] = None,
                     force: bool = False) -> dict:
        """Run a single LLM phase.  Skips if already completed (unless force)."""
        json_path = self.session_dir / f"{name}.json"

        if not force and json_path.exists():
            logger.info("Phase '%s' already completed, skipping", name)
            return json.loads(json_path.read_text())

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if user:
            final_user = user
            if output_schema:
                example = self._schema_to_example(output_schema)
                schema_hint = (
                    "\n\nRespond ONLY with valid JSON. "
                    "Here is the required structure — output DATA following this shape, "
                    "not the schema definition itself:\n\n"
                    f"{json.dumps(example, indent=2)}\n"
                )
                final_user += schema_hint
            messages.append({"role": "user", "content": final_user})

        fmt = "json" if output_schema else None
        try:
            response = await self.ollama.chat(messages, format=fmt)
        except Exception as e:
            logger.warning("Phase '%s' LLM call failed: %s", name, e)
            result = {"raw": "", "_error": str(e)}
            self._persist_phase(name, result, "", messages)
            return result

        content = response.get("message", {}).get("content", "")

        result = self._parse_output(content, output_schema)

        self._persist_phase(name, result, content, messages)
        return result

    async def _phase_batch(self, name_prefix: str, items: list,
                           prepare_fn: Callable[[Any], dict],
                           output_schema: Optional[dict] = None,
                           item_key_fn: Optional[Callable[[Any], str]] = None) -> list[dict]:
        """Run one LLM call per *item* sequentially.

        *prepare_fn(item)* returns *dict* with keys ``system``, ``user``.
        Each batch item is persisted as ``<name>-<key>.json`` for resume.
        """
        results = []
        if item_key_fn is None:
            item_key_fn = lambda x: str(x).replace("/", "_").replace(".", "_")

        for item in items:
            key = item_key_fn(item)
            phase_name = f"{name_prefix}-{key}"
            json_path = self.session_dir / f"{phase_name}.json"

            if json_path.exists():
                logger.info("Batch item '%s' already completed, resuming", phase_name)
                results.append(json.loads(json_path.read_text()))
                continue

            prompts = prepare_fn(item)
            if prompts.get("_skip"):
                logger.info("Skipping batch item '%s': %s", phase_name, prompts.get("_reason", "no reason"))
                result = {"_key": str(item), "_skipped": True, "_reason": prompts.get("_reason", "")}
                self._persist_phase(phase_name, result, "(skipped)", [])
                results.append(result)
                continue

            try:
                result = await self._phase(
                    phase_name,
                    system=prompts.get("system"),
                    user=prompts.get("user"),
                    output_schema=output_schema,
                )
            except Exception as e:
                logger.warning("Batch item '%s' failed: %s", phase_name, e)
                result = {"_key": str(item), "_error": str(e)}
                results.append(result)
                continue

            result["_key"] = str(item)
            results.append(result)

        return results

    # ── File I/O (sandbox-constrained) ──────────────────────────────────

    def _list_files(self, subdir: str = "") -> list[str]:
        """Return all file paths under a workspace subdir, relative to workspace.
        Excludes hidden directories (starting with '.') to avoid .context, .session-log, .wiki.
        """
        root = _safe_path(subdir) if subdir else SANDBOX_ROOT
        files = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            # Skip files inside hidden directories
            parts = p.relative_to(SANDBOX_ROOT).parts
            if any(part.startswith(".") for part in parts):
                continue
            rel = p.relative_to(SANDBOX_ROOT)
            files.append(str(rel))
        return files

    def _read_file(self, rel_path: str) -> str:
        full = _safe_path(rel_path)
        return full.read_text()

    def _is_text_file(self, rel_path: str, sample_size: int = 1024) -> bool:
        """Quick check if a file is text (valid UTF-8) and not a binary."""
        try:
            full = _safe_path(rel_path)
            data = full.read_bytes()[:sample_size]
            data.decode("utf-8")
            return True
        except (ValueError, UnicodeDecodeError, OSError):
            return False

    def _file_size_kb(self, rel_path: str) -> int:
        """Return file size in KB for threshold checks."""
        try:
            full = _safe_path(rel_path)
            return full.stat().st_size // 1024
        except OSError:
            return 0

    def _detect_language(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        return {
            ".go": "Go",
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".rs": "Rust",
            ".c": "C",
            ".h": "C",
            ".cpp": "C++",
            ".hpp": "C++",
            ".java": "Java",
            ".rb": "Ruby",
            ".sh": "Shell",
            ".yaml": "YAML",
            ".yml": "YAML",
            ".json": "JSON",
            ".md": "Markdown",
            ".toml": "TOML",
            ".mod": "Go Module",
            ".sum": "Go Sum",
        }.get(ext, "Text")

    # ── Internals ───────────────────────────────────────────────────────

    def _schema_to_example(self, schema: dict) -> dict:
        """Build a plausible example dict from a JSON schema."""
        example = {}
        for key, props in schema.get("properties", {}).items():
            ptype = props.get("type", "string")
            if ptype == "array":
                item_type = props.get("items", {}).get("type", "string")
                if item_type == "string":
                    example[key] = [f"<{key.rstrip('s')}_1>", f"<{key.rstrip('s')}_2>"]
                else:
                    example[key] = []
            elif ptype == "object":
                example[key] = {}
            elif ptype == "number":
                example[key] = 0
            elif ptype == "boolean":
                example[key] = False
            else:
                example[key] = f"<{key}>"
        return example

    def _parse_output(self, content: str, schema: Optional[dict]) -> dict:
        if not content:
            return {"raw": ""}
        if not schema:
            return {"raw": content}
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                # Recover if the model echoed the schema itself
                if "properties" in parsed and "type" in parsed:
                    recovered = {}
                    for k, v in parsed["properties"].items():
                        if isinstance(v, dict) and "items" in v:
                            recovered[k] = v.get("value") or v.get("items", {}).get("value") or []
                        elif isinstance(v, dict) and v.get("type") == "array":
                            recovered[k] = v.get("value") or []
                        elif isinstance(v, str):
                            recovered[k] = v
                    return recovered
                return parsed
            return {"data": parsed}
        except json.JSONDecodeError:
            return {"raw": content, "_parse_error": "response was not valid JSON"}

    def _persist_phase(self, name: str, result: dict, raw_content: str,
                       messages: list):
        json_path = self.session_dir / f"{name}.json"
        md_path = self.session_dir / f"{name}.md"
        md_body = raw_content or "(no output)"

        json_path.write_text(json.dumps(result, indent=2, default=str))
        md_path.write_text(f"# {name}\n\n{md_body}\n")

        if name not in self.manifest["completed_phases"]:
            self.manifest["completed_phases"].append(name)
        self._save_manifest()

        self._append_conversation({
            "role": "sys",
            "phase": name,
            "summary": raw_content[:200] if raw_content else "(no output)",
        })

    def _save_manifest(self):
        (self.session_dir / "manifest.json").write_text(
            json.dumps(self.manifest, indent=2)
        )

    def _append_conversation(self, entry: dict):
        conv_path = self.session_dir / "conversation.jsonl"
        entry["t"] = datetime.now().isoformat()
        with open(conv_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    # ── YAML-driven phase runner ───────────────────────────────────────────

    def _load_yaml_defs(self, path: Path) -> dict:
        """Load phase definitions from a YAML file."""
        import yaml as _yaml
        with open(path) as f:
            return _yaml.safe_load(f)

    async def _run_yaml(self, task: str, yaml_path: Path) -> dict:
        """Execute phases defined in a YAML file.

        Supports all context resolver types:
          task, list_files, read_file, detect_language,
          previous_output, literal

        Supports skip_conditions: max_size_kb, text_only
        """
        defs = self._load_yaml_defs(yaml_path)
        phase_outputs: dict[str, dict] = {}

        for phase_def in defs.get("phases", []):
            name = phase_def["name"]
            batch_over = phase_def.get("batch_over")

            # Resolve static context variables
            ctx = self._resolve_yaml_context(
                phase_def.get("context", {}), task, phase_outputs, None
            )

            if batch_over:
                # Resolve batch items: first check phase_outputs, then context, then previous phase
                items = []
                # Check if the batch_over field exists in phase_outputs
                for prev_name, prev_data in reversed(list(phase_outputs.items())):
                    if isinstance(prev_data, dict) and batch_over in prev_data:
                        items = list(prev_data[batch_over])
                        break
                if not items:
                    items = list(ctx.get(batch_over, []))
                if not items:
                    # Try previous phase with _output suffix
                    for prev_name in reversed(list(phase_outputs.keys())):
                        check = prev_name + "_output"
                        if check in phase_outputs:
                            items = list(phase_outputs[check])
                            break
                output_field = phase_def.get("output_field")
                results = []

                for item in items:
                    safe_key = str(item).replace("/", "_").replace(".", "_")
                    phase_name = f"{name}-{safe_key}"
                    json_path = self.session_dir / f"{phase_name}.json"

                    if json_path.exists():
                        logger.info("Batch item '%s' already completed, resuming", phase_name)
                        r = json.loads(json_path.read_text())
                        r["_key"] = str(item)
                        results.append(r)
                        continue

                    skip = phase_def.get("skip_conditions", {})
                    if isinstance(item, str):
                        if skip.get("text_only") and not self._is_text_file(item):
                            logger.info("Skipping '%s': binary file", phase_name)
                            r = {"_key": str(item), "_skipped": True, "_reason": "binary file"}
                            self._persist_phase(phase_name, r, "(skipped)", [])
                            results.append(r)
                            continue
                        if skip.get("max_size_kb") and self._file_size_kb(item) > skip["max_size_kb"]:
                            logger.info("Skipping '%s': too large", phase_name)
                            r = {"_key": str(item), "_skipped": True, "_reason": f"file too large ({self._file_size_kb(item)} KB)"}
                            self._persist_phase(phase_name, r, "(skipped)", [])
                            results.append(r)
                            continue

                    item_ctx = self._resolve_yaml_context(
                        phase_def.get("context", {}), task, phase_outputs, item
                    )
                    system = phase_def.get("system_prompt", "")
                    user = phase_def.get("user_prompt", "")
                    if system:
                        system = system.format(**item_ctx)
                    if user:
                        user = user.format(**item_ctx)

                    r = await self._phase(
                        phase_name,
                        system=system,
                        user=user,
                        output_schema=phase_def.get("output_schema"),
                    )
                    r["_key"] = str(item)
                    results.append(r)

                phase_outputs[name] = results

                if output_field:
                    collected = []
                    for r in results:
                        if r.get("_skipped"):
                            continue
                        val = r.get(output_field)
                        if val is not None:
                            if isinstance(val, list):
                                collected.extend(val)
                            else:
                                collected.append(val)
                    phase_outputs[name + "_output"] = collected

            else:
                r = await self._phase(
                    name,
                    system=phase_def.get("system_prompt", "").format(**ctx),
                    user=phase_def.get("user_prompt", "").format(**ctx),
                    output_schema=phase_def.get("output_schema"),
                )
                phase_outputs[name] = r

                output_field = phase_def.get("output_field")
                if output_field:
                    val = r.get(output_field)
                    if val is not None:
                        if isinstance(val, list):
                            phase_outputs[name + "_output"] = list(val)
                        else:
                            phase_outputs[name + "_output"] = [val]

        return phase_outputs

    def _resolve_yaml_context(self, ctx_def: dict, task: str,
                              phase_outputs: dict, batch_item: str | None) -> dict:
        """Resolve all context variables for a phase."""
        resolved = {"task": task}

        for key, spec in ctx_def.items():
            ctype = spec.get("type", "literal") if isinstance(spec, dict) else "literal"

            if ctype == "task":
                resolved[key] = task

            elif ctype == "list_files":
                resolved[key] = "\n".join(self._list_files())

            elif ctype == "read_file":
                path = spec.get("path", "")
                if "{item}" in path:
                    if batch_item is None:
                        continue  # deferred to per-item resolution
                    path = path.replace("{item}", batch_item)
                resolved[key] = self._read_file(path)

            elif ctype == "detect_language":
                path = spec.get("path", "")
                if "{item}" in path:
                    if batch_item is None:
                        continue  # deferred to per-item resolution
                    path = path.replace("{item}", batch_item)
                resolved[key] = self._detect_language(path)

            elif ctype == "previous_output":
                phase = spec.get("phase", "")
                aggregate = spec.get("aggregate", "json")
                key_field = spec.get("key", "all")
                data = phase_outputs.get(phase, [])

                if aggregate == "json":
                    items = []
                    for item in data:
                        if item.get("_skipped"):
                            continue
                        if key_field == "all":
                            items.append(item)
                        else:
                            v = item.get(key_field, [])
                            if isinstance(v, list):
                                items.extend(v)
                            else:
                                items.append(v)
                    resolved[key] = json.dumps(items, indent=2, default=str)

                elif aggregate == "text":
                    lines = []
                    for item in data:
                        if item.get("_skipped"):
                            continue
                        fp = item.get("file", item.get("_key", "?"))
                        lines.append(f"--- {fp} ---")
                        lines.append(f"Purpose: {item.get('purpose', '')}")
                        lines.append(f"Symbols: {', '.join(item.get('key_symbols', []))}")
                        lines.append(f"Deps: {', '.join(item.get('dependencies', []))}")
                        lines.append(f"Notable: {', '.join(item.get('notable', []))}")
                        lines.append("")
                    resolved[key] = "\n".join(lines)

            elif ctype == "literal":
                val = spec.get("value", "")
                if "{item}" in val:
                    if batch_item is None:
                        continue  # deferred to per-item resolution
                    val = val.replace("{item}", batch_item)
                resolved[key] = val

        return resolved


    # ── Subclass hook ───────────────────────────────────────────────────

    async def _run(self, task: str) -> dict:
        raise NotImplementedError


# ── CLI entry point ────────────────────────────────────────────────────────

async def _main():
    import argparse

    log_dir = Path(config.workspace.path) / ".session-log"
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    handler = logging.FileHandler(str(log_dir / "pipeline.log"))
    handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description="Run a multi-phase analysis pipeline")
    parser.add_argument("--workflow", help="Workflow name")
    parser.add_argument("--task", help="Task description")
    parser.add_argument("--session-id", help="Session ID (for resume)")
    parser.add_argument("--resume", action="store_true", help="Resume existing session")
    parser.add_argument("--list", action="store_true", help="List available workflows")
    args = parser.parse_args()

    # Lazy import so workflows register
    from workflows import get_workflow, list_workflows

    if args.list:
        print("Available workflows:")
        for name, desc in list_workflows().items():
            print(f"  {name}: {desc}")
        return

    if not args.workflow or not args.task:
        parser.print_help()
        sys.exit(1)

    pipe = get_workflow(args.workflow)
    try:
        result = await pipe.run(args.task, session_id=args.session_id,
                                resume=args.resume)

        console = Console()

        # Render markdown output if present
        blob_path = result.get("context_blob_path")
        if blob_path and Path(blob_path).exists():
            console.print(Markdown(Path(blob_path).read_text()))
        elif "synthesis" in result:
            synth = result["synthesis"]
            if isinstance(synth, dict):
                report = synth.get("report", "")
                if report:
                    console.print(Markdown(report))

        # Compact status line
        sid = result.get("session_id", pipe.session_id)
        files = result.get("files_summarized") or result.get("files_analyzed") or []
        chunks = result.get("chunks_ingested")
        parts = filter(None, [
            f"[green]✓[/green] {len(files)} files" if files else None,
            f"[green]✓[/green] {chunks} chunks" if chunks is not None else None,
        ])
        suffix = f"  {'  '.join(parts)}" if parts else ""
        console.print(f"[dim]session[/dim] {sid}  [dim]workflow[/dim] {args.workflow}{suffix}")
    except KeyboardInterrupt:
        print("\nInterrupted. Session can be resumed with --session-id %s --resume",
              pipe.session_id if pipe.session_id else "")
        sys.exit(130)
    except Exception as e:
        logger.error("Pipeline failed: %s", e)
        sid = pipe.session_id if pipe.session_id else ""
        print(json.dumps({"error": str(e), "session_id": sid}, indent=2))
        sys.exit(1)
    finally:
        await pipe.close()


if __name__ == "__main__":
    asyncio.run(_main())
