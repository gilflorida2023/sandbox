#!/usr/bin/env python3
"""Deploy a Python tool script from workspace/ into scout/cgi-bin/workspace/ and register it."""
import json, os, sys, stat
from pathlib import Path

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()
CGI_DIR = Path("/home/scout/projects/sandbox/scout/cgi-bin/workspace").resolve()
PROJECT_ROOT = Path("/home/scout/projects/sandbox").resolve()
MCP_TOOL_SH = PROJECT_ROOT / "mcp_tool.sh"
TOOL_DEFS = PROJECT_ROOT / "tool_definitions.json"

def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    source = args.get("source", "")
    tool_name = args.get("tool_name", "")

    if not source or not tool_name:
        print(json.dumps({"success": False, "error": "Missing source and/or tool_name parameters"}))
        sys.exit(1)

    src_path = (WORKSPACE_ROOT / source).resolve()
    if not str(src_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Source must be inside workspace"}))
        sys.exit(1)
    if not src_path.is_file():
        print(json.dumps({"success": False, "error": f"Source file not found: {source}"}))
        sys.exit(1)

    dest_name = tool_name.split(".")[-1] + ".py" if "." in tool_name else tool_name + ".py"
    dest_path = CGI_DIR / dest_name

    content = src_path.read_text()
    if not content.startswith("#!/usr/bin/env python3"):
        content = "#!/usr/bin/env python3\n" + content
    dest_path.write_text(content)
    os.chmod(dest_path, os.stat(dest_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    mcp_line = f"    workspace.{tool_name})  script=\"$CGI_DIR/{dest_name}\" ;;"
    mcp_content = MCP_TOOL_SH.read_text()
    if f"workspace.{tool_name})" not in mcp_content:
        mcp_content = mcp_content.replace(
            "    workspace.subagent)  script=\"$CGI_DIR/subagent.sh\" ;;",
            f"    workspace.{tool_name})  script=\"$CGI_DIR/{dest_name}\" ;;\n    workspace.subagent)  script=\"$CGI_DIR/subagent.sh\" ;;"
        )
        MCP_TOOL_SH.write_text(mcp_content)

    print(json.dumps({
        "success": True,
        "deployed_to": str(dest_path),
        "tool_name": tool_name,
        "mcp_registered": True,
        "message": f"Deployed {source} → {dest_name} as workspace.{tool_name}"
    }))

if __name__ == "__main__":
    main()
