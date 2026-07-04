import asyncio
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List

CGI_BASE = Path("/home/scout/projects/sandbox/scout/cgi-bin/mcp/tools")


async def _run_cgi(script: str, payload: dict) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "bash", str(CGI_BASE / script),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(json.dumps(payload).encode())
    stderr_text = stderr.decode().strip()
    if proc.returncode != 0:
        msg = stderr_text or f"CGI script failed (exit {proc.returncode})"
        return {"success": False, "error": msg, "stderr": stderr_text}
    try:
        result = json.loads(stdout.decode())
        result["stderr"] = stderr_text
        return result
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": f"Invalid JSON from tool: {e}",
            "raw_stdout": stdout.decode()[:2000],
            "stderr": stderr_text,
        }


class MCPClient:
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return await _run_cgi("call.sh", {"name": name, "arguments": arguments})

    async def list_tools(self) -> List[Dict[str, Any]]:
        result = await _run_cgi("list.sh", {})
        return result.get("tools", [])

    async def close(self):
        pass
