#!/usr/bin/env python3
"""Interactive REPL for the coding agent — model is yours to query."""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.WARNING)

from agent import CodingAgent


async def repl():
    agent = CodingAgent()
    print(f"Model: {agent.ollama.model}")
    print("Type 'exit' or Ctrl-D to quit.\n")
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
    await agent.close()


if __name__ == "__main__":
    asyncio.run(repl())
