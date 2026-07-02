#!/usr/bin/env python3
"""SSH tunnel manager backed by systemd --user service.

The tunnel runs as a systemd user service (ollama-tunnel.service)
instead of a Python daemon thread.  This class is a thin wrapper
that checks health via HTTP and controls the service via systemctl.
"""
import logging
import subprocess
import time
from typing import Optional

import httpx

OLLAMA_HEALTH_URL = "http://localhost:11434/api/tags"
HEALTH_TIMEOUT = 5
SYSTEMCTL_TUNNEL_UNIT = "ollama-tunnel.service"

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class TunnelManager:
    """Manages SSH tunnel lifecycle via systemd --user."""

    def __init__(
        self,
        check_interval: int = 30,
        establish_timeout: int = 60,
        check_timeout: int = 30,
        on_tunnel_healthy: Optional[callable] = None,
        on_tunnel_unhealthy: Optional[callable] = None,
    ):
        self.check_interval = check_interval
        self.establish_timeout = establish_timeout
        self.check_timeout = check_timeout
        self.on_tunnel_healthy = on_tunnel_healthy
        self.on_tunnel_unhealthy = on_tunnel_unhealthy

        self._healthy = False
        self._last_healthy_check: Optional[float] = None
        self._client = httpx.Client(timeout=HEALTH_TIMEOUT)

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def last_healthy_check(self) -> Optional[float]:
        return self._last_healthy_check

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _http_healthy(self) -> bool:
        """Return True if Ollama API responds on localhost:11434."""
        try:
            r = self._client.get(OLLAMA_HEALTH_URL)
            return r.status_code == 200
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError):
            return False

    def _systemctl(self, action: str) -> bool:
        """Run 'systemctl --user <action> ollama-tunnel.service'.

        Returns True if the command exits with code 0.
        """
        try:
            result = subprocess.run(
                ["systemctl", "--user", action, SYSTEMCTL_TUNNEL_UNIT],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logfn = logger.debug if action == "is-active" else logger.warning
                logfn("systemctl %s: %s", action, result.stderr.strip() or "inactive")
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.error("systemctl %s timed out", action)
            return False
        except Exception as e:
            logger.error("systemctl %s error: %s", action, e)
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_tunnel(self) -> bool:
        """Check whether the SSH tunnel (and Ollama) is healthy via HTTP."""
        is_healthy = self._http_healthy()

        was_healthy = self._healthy
        self._healthy = is_healthy
        if is_healthy:
            self._last_healthy_check = time.time()

        if was_healthy and not is_healthy and self.on_tunnel_unhealthy:
            self.on_tunnel_unhealthy()
        elif not was_healthy and is_healthy and self.on_tunnel_healthy:
            self.on_tunnel_healthy()

        return is_healthy

    def establish_tunnel(self) -> bool:
        """Tell systemd to restart the tunnel service."""
        logger.info("Restarting ollama-tunnel.service via systemctl…")
        ok = self._systemctl("restart")
        self._healthy = ok
        if ok:
            self._last_healthy_check = time.time()
        return ok

    def start(self) -> bool:
        """Ensure the tunnel service is running."""
        logger.info("Starting tunnel manager (systemd-backed)…")

        if self._systemctl("is-active"):
            self._healthy = self.check_tunnel()
            return self._healthy

        if not self._systemctl("start"):
            logger.error("systemctl start failed")
            return False

        for _ in range(self.establish_timeout):
            if self._http_healthy():
                self._healthy = True
                self._last_healthy_check = time.time()
                return True
            time.sleep(1)

        logger.error("Tunnel did not become healthy within timeout")
        self._healthy = False
        return False

    def stop(self):
        """Stop the tunnel service."""
        logger.info("Stopping tunnel manager…")
        self._systemctl("stop")
        self._healthy = False

    def ensure_tunnel(self) -> bool:
        """Block until tunnel is healthy or timeout expires."""
        deadline = time.time() + self.establish_timeout
        while time.time() < deadline:
            if self.check_tunnel():
                return True
            time.sleep(1)
        return False

    def reestablish(self) -> bool:
        """Immediately restart the tunnel service and return success."""
        if self.check_tunnel():
            return True
        return self.establish_tunnel()


def create_tunnel_manager(**kwargs) -> TunnelManager:
    return TunnelManager(**kwargs)
