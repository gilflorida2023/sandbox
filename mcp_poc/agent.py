#!/usr/bin/env python3
import asyncio
import sys
import json
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config import config
from mcp_client import MCPClient
from ollama_client import OllamaClient
from tool_wiki import ToolWiki
from context_manager import ContextManager
from session_log import SessionLogger

log_dir = Path(config.workspace.path) / ".session-log"
log_dir.mkdir(parents=True, exist_ok=True)
root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
handler = logging.FileHandler(str(log_dir / "agent.log"))
handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
))
root.addHandler(handler)
root.setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def _parse_text_tool_calls(content: str) -> list[dict]:
    calls = []
    
    # Try direct JSON parse (single object)
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "name" in data:
            args = data.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            calls.append({"name": data["name"], "arguments": args})
            return calls
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Try parsing as JSON array
    try:
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "name" in item:
                    args = item.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    calls.append({"name": item["name"], "arguments": args})
            if calls:
                return calls
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Extract from markdown code blocks
    for delim in ['```json', '```']:
        start = content.find(delim)
        if start == -1:
            continue
        start = content.find('\n', start) + 1
        end = content.find('```', start)
        if end == -1:
            end = len(content)
        block = content[start:end].strip()
        for line in block.split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict) and "name" in data:
                    args = data.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    calls.append({"name": data["name"], "arguments": args})
            except (json.JSONDecodeError, TypeError):
                continue
        if calls:
            return calls
    
    return calls


class CodingAgent:
    def __init__(self, session_id: str = ""):
        self.mcp = MCPClient()
        self.ollama = OllamaClient()
        self.wiki = ToolWiki()
        self.context = ContextManager(self.wiki)
        self.system_prompt = Path("prompts/system_prompt.txt").read_text()
        self.learned_tools = set()
        self.wiki_injected = set()
        self.session_id = session_id
        self.session_logger = SessionLogger(
            workspace_path=config.workspace.path,
            ollama_host=config.ollama.host,
            ollama_port=config.ollama.port,
            ollama_model=config.ollama.model,
        )

    def _build_tool_reference(self, tools: list) -> str:
        lines = ["# Tool Reference Guide", ""]
        for tool in tools:
            name = tool.get("name", "?")
            desc = tool.get("description", "")
            schema = tool.get("input_schema", {})
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            
            lines.append(f"## {name}")
            lines.append(f"{desc}")
            lines.append("")
            lines.append("**Parameters:**")
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "any")
                pdesc = pinfo.get("description", "")
                is_req = "required" if pname in required else f"optional (default: {pinfo.get('default', 'N/A')})"
                lines.append(f"- `{pname}` ({ptype}, {is_req}): {pdesc}")
            
            # Generate example call
            example_args = {}
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "string")
                if pname in required:
                    if ptype == "string":
                        if pname == "pattern":
                            example_args[pname] = "search_term"
                        elif pname == "topic":
                            example_args[pname] = "workspace.compile"
                        else:
                            example_args[pname] = f"<{pname}>"
                    elif ptype in ("integer", "number"):
                        example_args[pname] = 0
                    elif ptype == "boolean":
                        example_args[pname] = False
                    elif ptype == "array":
                        example_args[pname] = []
                    else:
                        example_args[pname] = f"<{pname}>"
            
            if example_args:
                example = json.dumps({"name": name, "arguments": example_args}, indent=2)
                lines.append("")
                lines.append("**Example:**")
                lines.append(f"```json\n{example}\n```")
            
            lines.append("")
        
        return "\n".join(lines)

    def _get_tool_wiki_doc(self, tool_name: str) -> str | None:
        doc = self.wiki.get_tool_doc(tool_name)
        if doc:
            return doc
        # Try heuristic: strip prefix if needed
        short_name = tool_name.split(".")[-1] if "." in tool_name else tool_name
        for t in self.wiki.index.get("tools", []):
            if t["name"] == tool_name or t["name"].endswith(f".{short_name}"):
                wiki_file = Path(self.wiki.wiki_path) / t["wiki_file"]
                if wiki_file.exists():
                    return wiki_file.read_text()
        return None

    async def run(self, task: str) -> str:
        logger.info(f"Starting task: {task}")
        
        # Get all tool schemas
        tools = await self.mcp.list_tools()
        tool_schemas = []
        tool_defs = []
        ref_tools = []  # Only workspace/wiki tools for the reference doc
        for tool in tools:
            if "input_schema" in tool:
                tool_schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"]
                    }
                })
                # Only show workspace/wiki tools in the visible reference
                if tool["name"].startswith(("workspace.", "wiki.")):
                    params = tool["input_schema"].get("properties", {})
                    param_str = " ".join(f"<{n}>" for n in params.keys())
                    if param_str:
                        param_str = " " + param_str
                    tool_defs.append(f"- **{tool['name']}**: {tool['description']}{param_str}")
                    ref_tools.append(tool)
        
        # Build full tool reference doc (only workspace/wiki tools)
        tool_ref = self._build_tool_reference(ref_tools)
        
        # Inject tool definitions into system prompt
        system_prompt = self.system_prompt.replace("{TOOL_DEFINITIONS}", "\n".join(tool_defs))
        
        # Initialize conversation with tool reference as a separate system message
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"## Detailed Tool Reference\n\n{tool_ref}"},
            {"role": "user", "content": task}
        ]
        
        # Add relevant wiki context
        wiki_context = self.context.get_relevant_context(task)
        if wiki_context:
            messages.insert(1, {"role": "system", "content": f"## Reference Documentation\n\n{wiki_context}"})

        # Inject context blob from pipeline (context_load workflow)
        if self.session_id:
            ctx_path = Path(config.context.path) if hasattr(config, 'context') and config.context.path else Path(config.workspace.path) / ".context"
            blob_file = ctx_path / self.session_id / "context-blob.md"
            if blob_file.exists():
                blob = blob_file.read_text()
                messages.insert(1, {"role": "system", "content": f"## Codebase Context\n\n{blob}"})
                logger.info("Injected context blob from %s", blob_file)
        
        for turn in range(config.agent.max_turns):
            logger.info(f"Turn {turn + 1}/{config.agent.max_turns}")
            
            try:
                response = await self.ollama.chat(messages, tool_schemas)
            except Exception as e:
                logger.error(f"Ollama error: {e}")
                return f"Error communicating with Ollama: {e}"
            
            done_reason = response.get("done_reason", "")
            if done_reason == "length":
                logger.warning(f"Response truncated due to context limit (turn {turn + 1})")
            
            message = response.get("message", {})
            content = message.get("content", "") or ""
            thinking = message.get("thinking", "")
            tool_calls = message.get("tool_calls", [])
            
            if not content and thinking:
                content = thinking
                logger.debug("Using thinking field as content (qwen3.5 CoT)")
            
            if not content and not tool_calls:
                logger.warning(f"Empty response from Ollama: response={json.dumps(response)[:500]}")
            elif content:
                logger.debug(f"Model content: {content[:300]}")
            if tool_calls:
                logger.info(f"Native tool calls: {[tc['function']['name'] for tc in tool_calls]}")

            # Some models output tool calls as JSON text in content (fallback)
            parsed_tc = False
            if not tool_calls and content:
                parsed_list = _parse_text_tool_calls(content)
                if parsed_list:
                    logger.info(f"Parsed {len(parsed_list)} tool call(s) from text: {[p['name'] for p in parsed_list]}")
                    parsed_tc = True
                    tool_calls = [{
                        "function": {
                            "name": p["name"],
                            "arguments": json.dumps(p["arguments"]) if isinstance(p.get("arguments"), dict) else "{}"
                        },
                        "id": f"text_tc_{i}"
                    } for i, p in enumerate(parsed_list)]

            # Add assistant message to history
            if content:
                msg = {"role": "assistant", "content": content}
                if tool_calls and not parsed_tc:
                    msg["tool_calls"] = tool_calls
                messages.append(msg)
                self.context.add_message("assistant", content, tool_calls)

            if not tool_calls:
                logger.info("No tool calls - task complete")
                return content
            
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]
                
                if isinstance(func_args, str):
                    func_args = json.loads(func_args)
                
                # Auto-inject wiki doc on first use of this tool
                if func_name not in self.wiki_injected:
                    wiki_doc = self._get_tool_wiki_doc(func_name)
                    if wiki_doc:
                        logger.info(f"Injecting wiki docs for {func_name}")
                        wiki_msg = {"role": "system", "content": f"## {func_name} Documentation\n\n{wiki_doc}"}
                        messages.insert(-1, wiki_msg)
                    self.wiki_injected.add(func_name)
                
                logger.info(f"Executing: {func_name}({func_args})")
                
                try:
                    result = await self.mcp.call_tool(func_name, func_args)
                    result_str = json.dumps(result)
                    logger.info(f"Result: {result_str[:500]}")
                    
                    messages.append({
                        "role": "tool",
                        "content": result_str,
                        "tool_call_id": tc.get("id", "")
                    })
                    self.context.add_message("tool", result_str, tool_call_id=tc.get("id", ""))
                    
                except Exception as e:
                    error_msg = f"Tool {func_name} failed: {e}"
                    logger.error(error_msg)
                    messages.append({
                        "role": "tool",
                        "content": json.dumps({"success": False, "error": str(e)}),
                        "tool_call_id": tc.get("id", "")
                    })
        
        # If we ran tool calls on the last turn, give the model one more chance
        # to produce a final answer based on the results (no new tools allowed)
        if tool_calls:
            logger.info("Running final summary turn")
            try:
                response = await self.ollama.chat(messages)
                message = response.get("message", {})
                content = message.get("content", "") or ""
                thinking = message.get("thinking", "")
                if not content and thinking:
                    content = thinking
                if content:
                    return content
            except Exception as e:
                logger.error(f"Final turn error: {e}")
        
        return "Max turns reached without completion"

    async def build_preamble(self) -> tuple[list, list]:
        """Fetch tools, build system prompt + schemas. Call once per session.
        Returns (messages, tool_schemas)."""
        tools = await self.mcp.list_tools()
        tool_schemas = []
        tool_defs = []
        ref_tools = []
        for tool in tools:
            if "input_schema" in tool:
                tool_schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                })
                if tool["name"].startswith(("workspace.", "wiki.")):
                    params = tool["input_schema"].get("properties", {})
                    param_str = " ".join(f"<{n}>" for n in params.keys())
                    if param_str:
                        param_str = " " + param_str
                    tool_defs.append(
                        f"- **{tool['name']}**: {tool['description']}{param_str}"
                    )
                    ref_tools.append(tool)

        tool_ref = self._build_tool_reference(ref_tools)
        system_prompt = self.system_prompt.replace(
            "{TOOL_DEFINITIONS}", "\n".join(tool_defs)
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"## Detailed Tool Reference\n\n{tool_ref}"},
        ]

        if self.session_id:
            ctx_path = (
                Path(config.context.path)
                if hasattr(config, "context") and config.context.path
                else Path(config.workspace.path) / ".context"
            )
            blob_file = ctx_path / self.session_id / "context-blob.md"
            if blob_file.exists():
                blob = blob_file.read_text()
                messages.insert(
                    1, {"role": "system", "content": f"## Codebase Context\n\n{blob}"}
                )
                logger.info("Injected context blob from %s", blob_file)

        return messages, tool_schemas

    async def chat(
        self,
        user_input: str,
        messages: list | None = None,
        tool_schemas: list | None = None,
    ) -> tuple[str, list]:
        """Single user turn.  Returns (response_text, updated_messages)."""
        if messages is None:
            messages, tool_schemas = await self.build_preamble()

        wiki_context = self.context.get_relevant_context(user_input)
        if wiki_context:
            messages.append(
                {
                    "role": "system",
                    "content": f"## Reference Documentation\n\n{wiki_context}",
                }
            )

        messages.append({"role": "user", "content": user_input})

        for turn in range(config.agent.max_turns):
            logger.info("Turn %d/%d", turn + 1, config.agent.max_turns)

            try:
                response = await self.ollama.chat(messages, tool_schemas)
            except Exception as e:
                logger.error("Ollama error: %s", e)
                return f"Error communicating with Ollama: {e}", messages

            done_reason = response.get("done_reason", "")
            if done_reason == "length":
                logger.warning(
                    "Response truncated due to context limit (turn %d)", turn + 1
                )

            message = response.get("message", {})
            content = message.get("content", "") or ""
            thinking = message.get("thinking", "")
            tool_calls = message.get("tool_calls", [])

            if not content and thinking:
                content = thinking

            if not content and not tool_calls:
                logger.warning("Empty response")
            elif content:
                logger.debug("Model content: %s", content[:300])
            if tool_calls:
                logger.info(
                    "Tool calls: %s",
                    [tc["function"]["name"] for tc in tool_calls],
                )

            # Some models output tool calls as JSON text in content (fallback)
            parsed_tc = False
            if not tool_calls and content:
                parsed_list = _parse_text_tool_calls(content)
                if parsed_list:
                    parsed_tc = True
                    tool_calls = [
                        {
                            "function": {
                                "name": p["name"],
                                "arguments": json.dumps(p["arguments"])
                                if isinstance(p.get("arguments"), dict)
                                else "{}",
                            },
                            "id": f"text_tc_{i}",
                        }
                        for i, p in enumerate(parsed_list)
                    ]

            if content:
                msg = {"role": "assistant", "content": content}
                if tool_calls and not parsed_tc:
                    msg["tool_calls"] = tool_calls
                messages.append(msg)
                self.context.add_message("assistant", content, tool_calls)

            if not tool_calls:
                logger.info("No tool calls — responding")
                return content, messages

            for tc in tool_calls:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]
                if isinstance(func_args, str):
                    func_args = json.loads(func_args)

                if func_name not in self.wiki_injected:
                    wiki_doc = self._get_tool_wiki_doc(func_name)
                    if wiki_doc:
                        logger.info("Injecting wiki docs for %s", func_name)
                        wiki_msg = {
                            "role": "system",
                            "content": f"## {func_name} Documentation\n\n{wiki_doc}",
                        }
                        messages.insert(-1, wiki_msg)
                    self.wiki_injected.add(func_name)

                logger.info("Executing: %s(%s)", func_name, func_args)
                try:
                    result = await self.mcp.call_tool(func_name, func_args)
                    result_str = json.dumps(result)
                    messages.append(
                        {
                            "role": "tool",
                            "content": result_str,
                            "tool_call_id": tc.get("id", ""),
                        }
                    )
                    self.context.add_message(
                        "tool", result_str, tool_call_id=tc.get("id", "")
                    )
                except Exception as e:
                    error_msg = f"Tool {func_name} failed: {e}"
                    logger.error(error_msg)
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                {"success": False, "error": str(e)}
                            ),
                            "tool_call_id": tc.get("id", ""),
                        }
                    )

        if tool_calls:
            logger.info("Running final summary turn")
            try:
                response = await self.ollama.chat(messages)
                message = response.get("message", {})
                content = message.get("content", "") or ""
                thinking = message.get("thinking", "")
                if not content and thinking:
                    content = thinking
                if content:
                    return content, messages
            except Exception as e:
                logger.error("Final turn error: %s", e)

        return "Max turns reached without completion", messages

    async def close(self):
        await self.mcp.close()
        await self.ollama.close()


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Coding agent with pipeline integration")
    parser.add_argument("task", nargs="?", help="Task description")
    parser.add_argument("--session-id", help="Session ID from pipeline run")
    parser.add_argument("--workflow", help="Run a pipeline workflow first (e.g. context_load)")
    args = parser.parse_args()

    task = args.task
    if not task and sys.stdin.isatty():
        parser.print_help()
        sys.exit(1)
    if not task:
        task = sys.stdin.read().strip()

    # Optionally run a pipeline workflow first
    if args.workflow:
        sys.path.insert(0, str(Path(__file__).parent))
        from workflows import get_workflow
        pipe = get_workflow(args.workflow)
        try:
            pipe_result = await pipe.run(task, session_id=args.session_id)
            session_id = pipe_result.get("session_id", args.session_id or "")
            logger.info("Pipeline '%s' complete (session %s)", args.workflow, session_id)
            args.session_id = session_id  # pass through to agent
        finally:
            await pipe.close()

    agent = CodingAgent(session_id=args.session_id or "")
    
    try:
        result = await agent.run(task)
        print("\n" + "="*60)
        print("RESULT:")
        print("="*60)
        print(result)
        
        # Log session knowledge
        log_result = agent.session_logger.log_session(
            agent.context.history, task
        )
        if log_result.get("cached"):
            print(f"\nSession already logged (dedup match): {log_result['output_file']}")
        else:
            print(f"\nSession knowledge written to: {log_result['output_file']}")
            extraction = log_result.get("extraction")
            if extraction:
                print(f"  Decisions: {len(extraction.decisions)}")
                print(f"  Roadblocks: {len(extraction.questions)}")
                print(f"  Action Items: {len(extraction.action_items)}")
                print(f"  Ideas: {len(extraction.ideas)}")
            files = log_result.get("files_touched", [])
            if files:
                print(f"  Files touched: {len(files)}")
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())