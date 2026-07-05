#!/usr/bin/env python3
"""Simple SSH tunnel check utility.

Simplified replacement for tunnel_manager.py - removes systemd overhead.
Checks if Ollama is accessible on localhost:11434 (requires SSH tunnel).
"""

import sys
import time
import httpx
import socket
from typing import Optional

OLLAMA_HEALTH_URL = "http://localhost:11434/api/tags"
HEALTH_TIMEOUT = 5

# Cache for successful checks (30 second TTL)
_tunnel_cache = {"result": False, "timestamp": 0}
CACHE_TTL = 30

def check_ollama_tunnel() -> bool:
    """Check if Ollama is accessible via SSH tunnel.
    
    Returns True if connection succeeds, False otherwise.
    """
    # Check cache first
    now = time.time()
    if _tunnel_cache["result"] and (now - _tunnel_cache["timestamp"]) < CACHE_TTL:
        return True
    
    try:
        with httpx.Client(timeout=HEALTH_TIMEOUT) as client:
            response = client.get(OLLAMA_HEALTH_URL)
            if response.status_code == 200:
                _tunnel_cache["result"] = True
                _tunnel_cache["timestamp"] = now
                return True
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.HTTPError):
        pass
    return False

def ensure_ollama_tunnel(retries: int = 3, delay: float = 0.5) -> bool:
    """Ensure Ollama is accessible via SSH tunnel.
    
    Args:
        retries: Number of retry attempts (default 3)
        delay: Delay between retries in seconds (default 0.5)
    
    Returns True if accessible, False otherwise.
    """
    for attempt in range(retries):
        if check_ollama_tunnel():
            return True
        
        if attempt < retries - 1:
            time.sleep(delay)
    
    # All retries failed - print clear error and return False
    print(f"❌ Ollama is not accessible via SSH tunnel at localhost:11434!")
    print(f"")
    print(f"To start the SSH tunnel, run:")
    print(f"   ssh -L 11434:localhost:11434 m4@192.168.0.0.7 -N -f")
    print(f"")
    print(f"Or, if port 11434 is in use:")
    print(f"   kill -9 $(lsof -ti:11434)")
    print(f"   ssh -L 11434:localhost:11434 m4@192.168.0.7 -N -f")
    return False

def check_and_log_or_error(quiet: bool = False):
    """Check tunnel and log if OK, error exit if not.
    
    Compatible with existing usage patterns.
    """
    if ensure_ollama_tunnel():
        if not quiet:
            print(f"✅ Ollama is accessible via SSH tunnel at localhost:11434")
        return True
    else:
        sys.exit(1)

if __name__ == "__main__":
    # When run as script
    check_and_log_or_error()

