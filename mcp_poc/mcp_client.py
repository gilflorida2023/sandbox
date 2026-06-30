import json
import httpx
from typing import Dict, Any, List
from config import config

class MCPClient:
    def __init__(self):
        self.base_url = config.scout.base_url
        self.client = httpx.AsyncClient(timeout=120.0)

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        response = await self.client.post(
            f"{self.base_url}/call.sh",
            json={"name": name, "arguments": arguments}
        )
        response.raise_for_status()
        return response.json()

    async def list_tools(self) -> List[Dict[str, Any]]:
        response = await self.client.post(
            f"{self.base_url}/list.sh",
            json={}
        )
        response.raise_for_status()
        return response.json().get("tools", [])

    async def close(self):
        await self.client.aclose()