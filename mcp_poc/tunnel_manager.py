#!/usr/bin/env python3
"""Background SSH tunnel manager with health monitoring thread."""
import asyncio
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Callable

TUNNEL_CHECK_SCRIPT = "/home/scout/projects/sandbox/scout/cgi-bin/workspace/tunnel_check.py"

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class TunnelManager:
    """Manages SSH tunnel lifecycle in a background thread."""
    
    def __init__(
        self,
        check_interval: int = 30,
        establish_timeout: int = 60,
        check_timeout: int = 30,
        on_tunnel_healthy: Optional[Callable[[], None]] = None,
        on_tunnel_unhealthy: Optional[Callable[[], None]] = None,
    ):
        self.check_interval = check_interval
        self.establish_timeout = establish_timeout
        self.check_timeout = check_timeout
        self.on_tunnel_healthy = on_tunnel_healthy
        self.on_tunnel_unhealthy = on_tunnel_unhealthy
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._healthy = False
        self._lock = threading.Lock()
        self._last_healthy_check: Optional[float] = None
        
    @property
    def healthy(self) -> bool:
        with self._lock:
            return self._healthy
    
    @property
    def last_healthy_check(self) -> Optional[float]:
        with self._lock:
            return self._last_healthy_check
    
    def _run_tunnel_check(self, action: str) -> dict:
        """Run tunnel check script and return parsed result."""
        try:
            result = subprocess.run(
                ["python3", TUNNEL_CHECK_SCRIPT, action],
                capture_output=True, text=True, timeout=self.check_timeout
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
            return {"success": False, "error": result.stderr}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def check_tunnel(self) -> bool:
        """Check if tunnel is healthy."""
        result = self._run_tunnel_check("check")
        is_healthy = result.get("healthy", False)
        
        with self._lock:
            was_healthy = self._healthy
            self._healthy = is_healthy
            if is_healthy:
                self._last_healthy_check = time.time()
            
            if was_healthy != is_healthy:
                if is_healthy and self.on_tunnel_healthy:
                    self.on_tunnel_healthy()
                elif not is_healthy and self.on_tunnel_unhealthy:
                    self.on_tunnel_unhealthy()
        
        return is_healthy
    
    def establish_tunnel(self) -> bool:
        """Establish new SSH tunnel."""
        result = self._run_tunnel_check("establish")
        success = result.get("success", False)
        
        with self._lock:
            self._healthy = success
            if success:
                self._last_healthy_check = time.time()
        
        return success
    
    def _monitor_loop(self):
        """Background thread main loop."""
        logger.info("Tunnel monitor thread started")
        
        while self._running:
            try:
                healthy = self.check_tunnel()
                
                if not healthy:
                    logger.warning("Tunnel unhealthy, attempting to reestablish...")
                    if self.establish_tunnel():
                        logger.info("Tunnel reestablished successfully")
                    else:
                        logger.error("Failed to reestablish tunnel")
                
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error in tunnel monitor: {e}")
                time.sleep(self.check_interval)
        
        logger.info("Tunnel monitor thread stopped")
    
    def start(self) -> bool:
        """Start the tunnel manager."""
        if self._running:
            logger.warning("Tunnel manager already running")
            return True
        
        logger.info("Starting tunnel manager...")
        
        if not self.check_tunnel():
            logger.info("Initial tunnel check failed, establishing...")
            if not self.establish_tunnel():
                logger.error("Failed to establish initial tunnel")
                return False
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        
        return True
    
    def stop(self):
        """Stop the tunnel manager."""
        if not self._running:
            return
        
        logger.info("Stopping tunnel manager...")
        self._running = False
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        
        logger.info("Tunnel manager stopped")
    
    def ensure_tunnel(self) -> bool:
        """Ensure tunnel is healthy, blocking until ready or timeout."""
        start_time = time.time()
        
        while time.time() - start_time < self.establish_timeout:
            if self.check_tunnel():
                return True
            
            logger.debug("Waiting for tunnel...")
            time.sleep(1)
        
        logger.error("Tunnel establishment timeout")
        return False


def create_tunnel_manager(**kwargs) -> TunnelManager:
    """Factory function to create TunnelManager with defaults."""
    return TunnelManager(**kwargs)