#!/usr/bin/env python3
"""Interactive REPL for the coding agent — with automatic SSH tunnel management."""
import os
import sys
from pathlib import Path

# Auto-detect and re-execute with venv Python
_venv_python = Path(__file__).parent / "venv" / "bin" / "python"
if sys.executable != str(_venv_python) and _venv_python.exists():
    os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)

import asyncio
import logging
import signal
import readline

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
        print("  /plan | /build  — switch modes")
        print("  /pending        — list knowledge chunks awaiting approval")
        print("  /approve <id>   — approve a pending chunk")
        print("  /reject <id>    — reject a pending chunk")
        print("  /blacklist <p>  — add contamination pattern ('re:' prefix = regex)")
        print("  /search <q>     — semantic search across wiki + knowledge")
        print("  /resume <id>    — resume a previous session")
        print("  /summarize <n>   — generate conversation summary")
        print("  /task <action>   — manage tasks (add/show/update)")
        print("  /correct <id> <feedback> — submit user correction")
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
                elif raw_input == "/pending":
                    pending = agent.context.approval.get_pending_summary()
                    if not pending:
                        print("\nNo pending knowledge chunks awaiting review.")
                    else:
                        print(f"\n=== Pending Knowledge Chunks ({len(pending)}) ===")
                        for p in pending:
                            print(f"  ID: {p['id']}")
                            print(f"  Source: {p['source']}")
                            print(f"  Tags: {p['tags']}")
                            print(f"  Preview: {p['content_preview'][:120]}...")
                            print()
                    continue
                elif raw_input.startswith("/approve "):
                    chunk_id = raw_input[len("/approve "):].strip()
                    if not chunk_id:
                        print("Usage: /approve <chunk_id>")
                    elif agent.context.approval.approve(chunk_id):
                        print(f"\nApproved chunk {chunk_id}")
                    else:
                        print(f"\nChunk {chunk_id} not found in pending queue")
                    continue
                elif raw_input.startswith("/reject "):
                    chunk_id = raw_input[len("/reject "):].strip()
                    if not chunk_id:
                        print("Usage: /reject <chunk_id>")
                    elif agent.context.approval.reject(chunk_id):
                        print(f"\nRejected chunk {chunk_id}")
                    else:
                        print(f"\nChunk {chunk_id} not found in pending queue")
                    continue
                elif raw_input.startswith("/search "):
                    query = raw_input[len("/search "):].strip()
                    if not query:
                        print("Usage: /search <query>")
                    else:
                        results = agent.context.knowledge_indexer.search(query, top_k=5)
                        if not results:
                            print(f"\nNo results for: {query}")
                        else:
                            print(f"\n=== Semantic Search Results ({len(results)}) ===")
                            for r in results:
                                print(f"  [{r.source}] score={r.score:.3f}")
                                print(f"  {r.content[:200]}...")
                                print()
                    continue
                elif raw_input.startswith("/blacklist "):
                    pattern = raw_input[len("/blacklist "):].strip()
                    if not pattern:
                        print("Usage: /blacklist <pattern>")
                        print("  Add a substring pattern (e.g. 'sieve')")
                        print("  Prefix with 're:' for regex (e.g. 're:sieve\\\\s+of')")
                    else:
                        if pattern.startswith("re:"):
                            regex = pattern[3:]
                            agent.context.approval.add_blacklist_regex(regex)
                            print(f"\nAdded regex blacklist pattern: {regex}")
                        else:
                            agent.context.approval.add_blacklist_pattern(pattern)
                            print(f"\nAdded blacklist pattern: {pattern}")
                    continue

                elif raw_input == "/resume":
                    pending = agent.session_state.as_dict()
                    if not pending:
                        print("\nNo previous sessions to resume.")
                    else:
                        print(f"\n=== Current Session State ===")
                        print(f"Session ID: {pending.get('session_id')}")
                        print(f"Turn Count: {pending.get('turn_count')}")
                        print(f"Active Task: {pending.get('active_task') or 'None'}")
                        print(f"Conversation Summary: {pending.get('conversation_summary')[:100] or 'None'}...")
                        print(f"Files Referenced: {len(pending.get('referenced_files', []))}")
                        print(f"Context Fragments: {len(pending.get('context_fragments', []))}")
                    continue

                elif raw_input.startswith("/summarize "):
                    try:
                        count = int(raw_input[len("/summarize "):].strip())
                        summary = agent.session_state.as_dict().get('conversation_summary', '')
                        print(f"\n=== Conversation Summary (Last {count} Turns) ===")
                        if summary:
                            print(summary[:500] + "...")
                        else:
                            print("No summary available.")
                    except ValueError:
                        print("\nUsage: /summarize <number_of_turns>")
                    continue

                elif raw_input == "/task":
                    print("\n=== Task Management ===")
                    print("Available actions: add, show, update")
                    print("Example: /task add 'Implement Phase 3'")
                    print("Example: /task show 1")
                    print("Example: /task update 1 status 'completed'")
                    continue

                elif raw_input.startswith("/correct "):
                    try:
                        parts = raw_input[len("/correct "):].strip().split(" ", 1)
                        if len(parts) < 2:
                            print("\nUsage: /correct <topic> <feedback>")
                            continue
                        topic, feedback = parts[0], parts[1]
                        agent.correction_store.add_correction(
                            topic=topic,
                            incorrect="[previous incorrect response]",
                            correct=feedback,
                            context="User identified error"
                        )
                        print(f"\nCorrection stored for topic: {topic}")
                    except Exception as e:
                        print(f"\nError storing correction: {e}")
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
