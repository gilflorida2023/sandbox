#!/usr/bin/env python3
"""Interactive REPL for the coding agent — with automatic SSH tunnel management."""
import asyncio
import logging
import sys
import signal
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import config for tunnel settings
from config import config

logging.basicConfig(level=logging.WARNING)

from agent import CodingAgent
from tunnel_manager import TunnelManager


async def repl():
    # Create tunnel manager with REPL-specific callbacks
    tunnel_mgr = TunnelManager(
        check_interval=30,
        on_tunnel_healthy=lambda: print("🟢 SSH tunnel restored"),
        on_tunnel_unhealthy=lambda: print("🔴 SSH tunnel lost - attempting recovery..."),
    )
    
    # Handle cleanup on exit
    def cleanup(signum=None, frame=None):
        print("\nShutting down tunnel manager...")
        tunnel_mgr.stop()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    
    # Start tunnel manager (replaces _ensure_tunnel_before_repl)
    print("Starting SSH tunnel manager...")
    if not tunnel_mgr.start():
        print("⚠️  Failed to start tunnel manager, proceeding anyway...")
    
    try:
        # Pass tunnel manager to agent
        agent = CodingAgent(tunnel_manager=tunnel_mgr)
        print(f"Model: {agent.ollama.model}")
        print("Type \'exit\' or Ctrl-D to quit.\n")
        while True:
            try:
                task = input(">>> ").strip()
                if not task:
                    continue
                if task.lower() in ("exit", "quit"):
                    break
                    
                content, _ = await agent.chat(task)
                print(content)
                
            except (EOFError, KeyboardInterrupt):
                print()
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                
    finally:
        cleanup()
        await agent.close()


if __name__ == "__main__":
    asyncio.run(repl())
