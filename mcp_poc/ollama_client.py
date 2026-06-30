import httpx
import json
import asyncio
import socket
from typing import Dict, Any, List, Optional, Tuple
from config import config
from tunnel_manager import TunnelManager

class OllamaClient:
    def __init__(self, tunnel_manager: Optional[TunnelManager] = None):
        self.base_url = f"http://{config.ollama.host}:{config.ollama.port}"
        self.model = config.ollama.model
        self.client = httpx.AsyncClient(timeout=config.ollama.timeout)
        self.tunnel_manager = tunnel_manager
        if tunnel_manager is None:
            # Fallback to script-based check for backward compatibility
            self.tunnel_check_script = "/home/scout/projects/sandbox/scout/cgi-bin/workspace/tunnel_check.py"

    def _run_tunnel_check(self, action: str) -> Tuple[bool, str]:
        """Run tunnel check script and return result"""
        import subprocess
        try:
            result = subprocess.run(
                ["python3", self.tunnel_check_script, action],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("success", data.get("healthy", False)), data.get("status", "Unknown")
            else:
                return False, f"Script failed: {result.stderr}"
        except Exception as e:
            return False, f"Check failed: {e}"

    def _ensure_tunnel(self) -> bool:
        """Verify Ollama tunnel is available - uses TunnelManager if available"""
        if self.tunnel_manager:
            return self.tunnel_manager.healthy
        
        # Fallback for backward compatibility: direct script check
        try:
            if "healthcheck" in self._run_tunnel_check("check")[1].lower():
                return True
            return self._run_tunnel_check("establish")[0]
        except Exception as e:
            print(f"Tunnel check error: {e}")
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
                if attempt == max_attempts - 1:
                    raise ConnectionError(f"Connection failed after {max_attempts} attempts: {e}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

    async def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None, format: Optional[str] = None) -> Dict[str, Any]:
        # Pre-validate tunnel before request
        if not self._ensure_tunnel():
            raise ConnectionError("Ollama tunnel unavailable")
        
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

        return await self._make_request_with_retry(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload
        )

    async def close(self):
        await self.client.aclose()