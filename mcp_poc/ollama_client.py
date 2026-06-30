import httpx
import json
from typing import Dict, Any, List, Optional
from config import config

class OllamaClient:
    def __init__(self):
        self.base_url = f"http://{config.ollama.host}:{config.ollama.port}"
        self.model = config.ollama.model
        self.client = httpx.AsyncClient(timeout=config.ollama.timeout)

    async def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None, format: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": config.agent.temperature,
                "num_ctx": 32768
            }
        }

        if tools:
            payload["tools"] = tools

        if format:
            payload["format"] = format

        response = await self.client.post(
            f"{self.base_url}/api/chat",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()