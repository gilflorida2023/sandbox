#!/usr/bin/env python3
"""Interactive REPL for the coding agent — with automatic SSH tunnel management."""
import asyncio
import logging
import sys
import signal
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import config for tunnel settings
from config import config

logging.basicConfig(level=logging.WARNING)

from agent import CodingAgent, PLAN_MODE, BUILD_MODE
from tunnel_manager import TunnelManager


# Enhanced terminal input handler for special key support
def get_raw_input(initial_buffer=""):
    """Get a line of input with special key support for REPL control.

    Args:
        initial_buffer: Pre-filled text to show (for history editing).
    """
    try:
        import tty
        import termios
        import select

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        try:
            tty.setraw(fd)

            buf = list(initial_buffer)
            sys.stdout.write(">>> ")
            sys.stdout.write(initial_buffer)
            sys.stdout.flush()

            while True:
                ready, _, _ = select.select([sys.stdin], [], [], None)
                if not ready:
                    continue

                ch = sys.stdin.read(1)

                if ch == '\x03':            # Ctrl+C
                    raise KeyboardInterrupt
                elif ch == '\x04':           # Ctrl+D (EOF)
                    sys.stdout.write('\r\n')
                    sys.stdout.flush()
                    return ''
                elif ch in ('\r', '\n'):     # Enter
                    sys.stdout.write('\r\n')
                    sys.stdout.flush()
                    return ''.join(buf)
                elif ch == '\t':             # Tab → mode switch
                    sys.stdout.write('\r\n')
                    sys.stdout.flush()
                    return '\t'
                elif ch == '\x1b':           # Escape sequences
                    nxt = sys.stdin.read(1)
                    if nxt == '[':
                        direction = sys.stdin.read(1)
                        if direction in ('A', 'B', 'C', 'D'):
                            return '\x1b[' + direction
                    return ''
                elif ch in ('\x7f', '\x08'): # Backspace
                    if buf:
                        buf.pop()
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()
                elif ch.isprintable() or ch == ' ':
                    buf.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()

        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    except (ImportError, AttributeError, OSError):
        return input(f">>> {initial_buffer}").strip()

    return ''


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
        print("Type \'exit\' or Ctrl-D to quit.")
        print("Press Tab to switch between PLAN and BUILD modes.")
        print(f"Current mode: {agent.current_mode} (Read-only: {'Yes' if agent.current_mode == PLAN_MODE else 'No'})\n")
        
        command_history = []
        
        while True:
            try:
                raw_input = get_raw_input()
                
                if raw_input == '\t':  # Tab → mode switch
                    new_mode = BUILD_MODE if agent.current_mode == PLAN_MODE else PLAN_MODE
                    result = await agent.switch_mode(new_mode)
                    print(f"\n{result}")
                    print(f"Current mode: {agent.current_mode} (Read-only: {'Yes' if agent.current_mode == PLAN_MODE else 'No'})")
                    continue
                    
                elif raw_input == '\x1b[A':  # Up arrow → edit last command
                    if command_history:
                        raw_input = get_raw_input(initial_buffer=command_history[-1])
                    else:
                        continue
                    
                elif raw_input in ('\x1b[B', '\x1b[C', '\x1b[D'):  # Down / Right / Left
                    continue
                
                if raw_input.lower() in ("exit", "quit"):
                    break
                    
                task = raw_input.strip()
                
                if not task:
                    continue
                
                if task not in command_history:
                    command_history.append(task)
                    
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
