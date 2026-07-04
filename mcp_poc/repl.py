#!/usr/bin/env python3
"""Interactive REPL for the coding agent."""
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

logging.basicConfig(level=logging.WARNING)

from agent import CodingAgent, PLAN_MODE, BUILD_MODE, EXPLORE_MODE



async def repl():
    def cleanup(signum=None, frame=None):
        pass

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        agent = CodingAgent()
        
        # One-time startup check - fail fast if Ollama not reachable
        try:
            await agent.ollama.ensure_connected()
            print(f"✅ Ollama accessible via SSH tunnel at localhost:11434")
        except ConnectionError as e:
            print(f"❌ {e}")
            print(f"\nTo start the SSH tunnel, run:")
            print(f"   ssh -L 11434:localhost:11434 m4@192.168.0.7 -N -f")
            print(f"\nOr, if port 11434 is in use:")
            print(f"   kill -9 $(lsof -ti:11434)")
            print(f"   ssh -L 11434:localhost:11434 m4@192.168.0.7 -N -f")
            return
        print(f"Model: {agent.ollama.model}")
        print("Type 'exit' or Ctrl-D to quit.")
        print("  /plan | /build  — switch modes")
        print("  /pending        — list knowledge chunks awaiting approval")
        print("  /approve <id>   — approve a pending chunk")
        print("  /reject <id>    — reject a pending chunk")
        print("  /blacklist <p>  — add contamination pattern ('re:' prefix = regex)")
        print("  /search <q>     — semantic search across wiki + knowledge")
        print("  /resume <id>    — resume a previous session")
        print("  /summarize <n>  — generate conversation summary")
        print("  /correct <id> <feedback> — submit user correction")
        print("  /explore <problem> — start recursive exploration")
        print("  /rlm status     — RLM todo list + progress")
        print("  /stats          — telemetry dashboard")
        print(f"Current mode: {agent.current_mode} (Read-only: {'Yes' if agent.current_mode == PLAN_MODE else 'No'})\n")

        command_history = []
        readline.set_history_length(500)
        messages = None

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

                elif raw_input.startswith("/explore "):
                    problem = raw_input[len("/explore "):].strip()
                    if not problem:
                        print("\nUsage: /explore <problem_description>")
                    else:
                        print(f"\n=== Starting Recursive Exploration ===")
                        print(f"Problem: {problem}")
                        result, metadata = await agent.explore(problem)
                        print(f"\n=== Exploration Result ===")
                        print(result)
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

                elif raw_input == "/stats":
                    summary = agent.stats_collector.get_summary()
                    completion = agent.todo_list.completion_rate()
                    print(f"\n{summary.dashboard(todo_completion_rate=completion)}")
                    counts = agent.todo_list.count_by_status()
                    print(f"  ACTIVE TODO:    {agent.todo_list.pick_next()}")
                    print(f"  IN PROGRESS:    {counts.get('in_progress', 0)}")
                    print(f"  PENDING:        {counts.get('pending', 0)}")
                    print(f"  COMPLETED:      {counts.get('completed', 0)}")
                    print(f"  BLOCKED:        {counts.get('blocked', 0)}")
                    ss = agent.session_state.as_dict()
                    print(f"  Session tokens: P={ss.get('total_prompt_tokens', 0)} / C={ss.get('total_completion_tokens', 0)}")
                    continue

                elif raw_input == "/rlm status":
                    counts = agent.todo_list.count_by_status()
                    print(f"\n=== RLM Status ===")
                    print(f"  Completion: {agent.todo_list.completion_rate() * 100:.0f}%")
                    print(f"  In Progress: {counts.get('in_progress', 0)}")
                    print(f"  Pending:     {counts.get('pending', 0)}")
                    print(f"  Completed:   {counts.get('completed', 0)}")
                    print(f"  Blocked:     {counts.get('blocked', 0)}")
                    todos = agent.todo_list.get_all_todos()
                    if todos:
                        print(f"\n  Todos ({len(todos)}):")
                        for t in todos:
                            prefix = "[✓]" if t.status == "completed" else \
                                     "[▶]" if t.status == "in_progress" else \
                                     "[⊘]" if t.status == "blocked" else "[ ]"
                            print(f"    {prefix} {t.id[:8]} {t.description[:60]}")
                    summary = agent.stats_collector.get_summary()
                    print(f"\n  Turns: {summary.total_turns}")
                    continue

                elif raw_input.startswith("/rlm "):
                    print("\nUsage: /rlm status")
                    continue

                if raw_input.lower() in ("exit", "quit"):
                    break

                task = raw_input.strip()

                if not task:
                    continue

                if task not in command_history:
                    command_history.append(task)
                    readline.add_history(task)

                # Handle task continuation (single keyword: "continue")
                # Also accept "proceed", "go", etc. as aliases
                if task.lower() in ("continue", "proceed", "go", "let her rip"):
                    active = agent.session_state.active_task
                    if active:
                        task = active
                        agent.session_state.active_task = None
                        print(f"[Continuing: {task[:80]}...]")
                    else:
                        print("No active task to continue.")
                        continue

                content, messages = await agent.run(task, messages=messages)
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
