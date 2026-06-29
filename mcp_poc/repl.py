#!/usr/bin/env python3
"""Sandbox REPL — interactive prompt backed by LLM + tool calling.

Usage:
  python3 repl.py

Type natural language commands.  The LLM decides which tool to call.
Type 'quit', 'exit', or Ctrl+D to stop.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent import CodingAgent


async def main():
    agent = CodingAgent()
    messages, tool_schemas = await agent.build_preamble()

    print("sandbox REPL — type 'quit' or Ctrl+D to exit")

    while True:
        try:
            user_input = input("\nsandbox> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break

        response, messages = await agent.chat(user_input, messages, tool_schemas)
        print(response)

    await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
