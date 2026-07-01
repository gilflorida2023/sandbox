#!/usr/bin/env python3
"""Interactive REPL for the coding agent — with automatic SSH tunnel management."""
import asyncio
import logging
import sys
import signal
import readline
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import config for tunnel settings
from config import config

logging.basicConfig(level=logging.WARNING)

from agent import CodingAgent, PLAN_MODE, BUILD_MODE
from tunnel_manager import TunnelManager


async def repl():
    tunnel_mgr = TunnelManager(
        check_interval=30,
        on_tunnel_healthy=lambda: print("\U0001f7e2 SSH tunnel restored"),
        on_tunnel_unhealthy=lambda: print("\U0001f534 SSH tunnel lost - attempting recovery..."),
    )

    def cleanup(signum=None, frame=None):
        print("\nShutting down tunnel manager...")
        tunnel_mgr.stop()

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("Starting SSH tunnel manager...")
    if not tunnel_mgr.start():
        print("\u26a0\ufe0f  Failed to start tunnel manager, proceeding anyway...")

    try:
        agent = CodingAgent(tunnel_manager=tunnel_mgr)
        print(f"Model: {agent.ollama.model}")
        print("Type 'exit' or Ctrl-D to quit.")
        print("Type /plan or /build to switch modes.")
        print(f"Current mode: {agent.current_mode} (Read-only: {'Yes' if agent.current_mode == PLAN_MODE else 'No'})\n")

        command_history = []
        readline.set_history_length(500)

        while True:
            try:
                raw_input = input(f">>> ")

                if raw_input == "/plan":
                    result = await agent.switch_mode(PLAN_MODE)
                    print(f"\n{result}")
                    print(f"Current mode: {agent.current_mode} (Read-only: {'Yes' if agent.current_mode == PLAN_MODE else 'No'})")
                    continue
                elif raw_input == "/build":
                    result = await agent.switch_mode(BUILD_MODE)
                    print(f"\n{result}")
                    print(f"Current mode: {agent.current_mode} (Read-only: {'Yes' if agent.current_mode == PLAN_MODE else 'No'})")
                    continue

                if raw_input.lower() in ("exit", "quit"):
                    break

                task = raw_input.strip()

                if not task:
                    continue

                if task not in command_history:
                    command_history.append(task)
                    readline.add_history(task)

                content, _ = await agent.chat(task)
                print(content)

            except (EOFError, KeyboardInterrupt):
                print()
                break
            except Exception as e:
                print(f"\u274c Error: {e}")

    finally:
        cleanup()
        await agent.close()


if __name__ == "__main__":
    asyncio.run(repl())
