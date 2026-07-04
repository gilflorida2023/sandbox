import httpx
import asyncio
import logging
import socket
from typing import Dict, Any, List, Optional
from config import config

logger = logging.getLogger(__name__)

class ModelNotFoundError(ConnectionError):
    pass


class OllamaClient:
    def __init__(self):
        self.base_url = f"http://{config.ollama.host}:{config.ollama.port}"
        self.model = config.ollama.model
        self.client = httpx.AsyncClient(timeout=config.ollama.timeout)
        self.supports_tools = True

        self.supports_tools_cache = None
        self._model_verified = False
        
        # Import the simple tunnel check
        from simple_tunnel_check import ensure_ollama_tunnel
        self._simple_tunnel_check = ensure_ollama_tunnel

    async def _verify_model_exists(self) -> bool:
        try:
            resp = await self.client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            available = [m.get("name") for m in data.get("models", [])]
            if self.model not in available:
                raise ModelNotFoundError(
                    f"Model '{self.model}' is not available. "
                    f"Run: ollama pull {self.model}"
                )
            self._model_verified = True
            return True
        except ModelNotFoundError:
            raise
        except Exception:
            return True

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

    async def _make_request_with_retry(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with retry logic for transient failures."""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = await self.client.request(method, url, **kwargs)

                if response.status_code == 404 and "/api/chat" in url:
                    raise ModelNotFoundError(
                        f"Model '{self.model}' is not available. "
                        f"Run: ollama pull {self.model}"
                    )

                response.raise_for_status()
                return response.json()
                
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                logger.warning("Ollama connection failed (attempt %d/%d): %s", attempt + 1, max_attempts, e)
                if attempt == max_attempts - 1:
                    raise ConnectionError(f"Connection failed after {max_attempts} attempts: {e}")
                await asyncio.sleep(2 ** attempt)

            except ModelNotFoundError:
                raise

            except Exception as e:
                logger.warning("Ollama request failed (attempt %d/%d): %s", attempt + 1, max_attempts, e)
                if attempt == max_attempts - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

    async def ensure_connected(self) -> bool:
        """Verify Ollama is reachable. Call once at startup. Fail fast."""
        if not self._simple_tunnel_check():
            raise ConnectionError("SSH tunnel not available at localhost:11434")
        await self._verify_model_exists()
        return True

    async def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None, format: Optional[str] = None) -> Dict[str, Any]:
        if not self._model_verified:
            await self._verify_model_exists()
        
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
            },
            "think": False
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
                               format: Optional[str] = None) -> tuple[str, str, dict]:
        response = await self.chat(messages, tools, format)
        msg = response.get("message", {})
        content = msg.get("content", "")
        thinking = msg.get("thinking", "") or msg.get("reasoning_content", "")
        stats = {
            "prompt_tokens": response.get("prompt_eval_count", 0),
            "completion_tokens": response.get("eval_count", 0),
            "total_duration_ns": response.get("total_duration", 0),
        }
        return content, thinking, stats

    async def close(self):
        await self.client.aclose()