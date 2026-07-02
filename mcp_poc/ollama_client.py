import httpx
import asyncio
import logging
from typing import Dict, Any, List, Optional
from config import config
from tunnel_manager import TunnelManager

logger = logging.getLogger(__name__)

class OllamaClient:
    def __init__(self, tunnel_manager: Optional[TunnelManager] = None):
        self.base_url = f"http://{config.ollama.host}:{config.ollama.port}"
        self.model = config.ollama.model
        self.client = httpx.AsyncClient(timeout=config.ollama.timeout)
        self.tunnel_manager = tunnel_manager
        self.supports_tools = True

        self.supports_tools_cache = None

    async def _check_tool_support(self) -> bool:
        try:
            resp = await self.client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            for m in data.get("models", []):
                if m["name"] == self.model:
                    caps = m.get("capabilities", [])
                    return "tools" in caps
            return True
        except Exception:
            return True

    def _ensure_tunnel(self) -> bool:
        """Verify Ollama tunnel is available via TunnelManager."""
        if self.tunnel_manager:
            return self.tunnel_manager.healthy
        return True

    def _reestablish_tunnel(self) -> bool:
        """Re-establish the SSH tunnel via systemd (not in our thread)."""
        if self.tunnel_manager:
            return self.tunnel_manager.reestablish()
        return False

    async def _make_request_with_retry(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with retry logic and tunnel validation"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Ensure tunnel before request
                if not self._ensure_tunnel():
                    raise ConnectionError("SSH tunnel not available")
                
                response = await self.client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
                
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                logger.warning("Ollama connection failed (attempt %d/%d), re-establishing tunnel...", attempt + 1, max_attempts)
                self._reestablish_tunnel()
                if attempt == max_attempts - 1:
                    raise ConnectionError(f"Connection failed after {max_attempts} attempts: {e}")
                await asyncio.sleep(2 ** attempt)

            except Exception as e:
                logger.warning("Ollama request failed (attempt %d/%d): %s", attempt + 1, max_attempts, e)
                if attempt == max_attempts - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

    async def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None, format: Optional[str] = None) -> Dict[str, Any]:
        # Pre-validate tunnel before request
        if not self._ensure_tunnel():
            raise ConnectionError("Ollama tunnel unavailable")
        
        if self.supports_tools_cache is None:
            self.supports_tools_cache = await self._check_tool_support()
            logger.info("Model '%s' tool support: %s", self.model, self.supports_tools_cache)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": config.agent.temperature,
                "num_ctx": 262144
            }
        }

        if tools and self.supports_tools_cache:
            payload["tools"] = tools

        if format:
            payload["format"] = format

        return await self._make_request_with_retry(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload
        )

    async def chat_with_stats(self, messages: List[Dict[str, Any]],
                               tools: Optional[List[Dict]] = None,
                               format: Optional[str] = None) -> tuple[str, dict]:
        response = await self.chat(messages, tools, format)
        content = response.get("message", {}).get("content", "")
        stats = {
            "prompt_tokens": response.get("prompt_eval_count", 0),
            "completion_tokens": response.get("eval_count", 0),
            "total_duration_ns": response.get("total_duration", 0),
        }
        return content, stats

    async def close(self):
        await self.client.aclose()