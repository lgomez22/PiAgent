#!/usr/bin/env python3
"""
PiAgent — A lightweight AI agent for Raspberry Pi 3B/4 (≤1 GB RAM).

Features:
  • Moltbook social integration (post, comment, vote, DMs, heartbeat)
  • Python & Bash/Shell script writing assistant
  • Suggests code in other languages when appropriate
  • Hard memory cap via resource limits (Linux only)
  • Persistent credentials & heartbeat state on disk
  • LLM integration (Groq API) with template fallback
  • Enhanced template system with keyword matching

Usage:
    python3 agent.py            # interactive REPL
    python3 agent.py --setup    # first-run: register on Moltbook
    python3 agent.py --heartbeat # run one heartbeat tick and exit
"""

__version__ = "0.2.0"

import sys, os, argparse

# ---------------------------------------------------------------------------
# Memory guard — enforce 1 GB RSS cap (Linux only, RPi target)
# ---------------------------------------------------------------------------
def _apply_memory_cap(max_mb: int = 1024):
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        cap = max_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (cap, hard if hard == -1 else min(hard, cap)))
    except (ImportError, ValueError, resource.error):
        pass  # non-Linux or already capped — continue anyway

_apply_memory_cap(1024)

# ---------------------------------------------------------------------------
# Path bootstrap — make sibling imports work regardless of cwd
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from config   import Config
from moltbook import MoltbookClient
from coder    import CoderAssistant
from heartbeat import run_heartbeat


def _show_skill_update(cfg: Config):
    """Show cached skill.md updates and offer to view them."""
    from pathlib import Path
    skill_cache = Path.home() / ".config" / "piagent" / "skill_cache"
    if not skill_cache.exists():
        print("[Agent] No skill updates cached yet. Run 'heartbeat' first.")
        return
    
    cached_files = sorted(skill_cache.glob("skill_*.md"))
    if not cached_files:
        print("[Agent] No skill updates cached yet. Run 'heartbeat' first.")
        return
    
    print("\n📚 Cached Moltbook skill updates:")
    for f in cached_files:
        size_kb = f.stat().st_size / 1024
        print(f"   • {f.name} ({size_kb:.1f} KB)")
    
    latest = cached_files[-1]
    print(f"\n💡 Latest: {latest.name}")
    print(f"   Location: {latest}")
    print(f"\n   To view: cat {latest}")
    print(f"   To search: grep -i '<keyword>' {latest}")
    print()


def _print_banner():
    print("""
╔═══════════════════════════════════════════════╗
║            PiAgent  —  v0.2.0                 ║
║  Lightweight agent for Raspberry Pi 3B / 4    ║
║                                               ║
║  Commands:                                    ║
║    mb <action> [args]   Moltbook operations   ║
║    code <lang> <task>   Write a script        ║
║    heartbeat            Run heartbeat tick    ║
║    engage-on/off        Toggle auto-engage    ║
║    engage-status        Check engage status   ║
║    post-now             Force post creation   ║
║    post-targets         Set auto-post targets ║
║    groq-setup           Configure Groq API    ║
║    groq-status          Check LLM status      ║
║    skill-update         View cached skills    ║
║    help                 Show this help        ║
║    quit / exit          Exit the agent        ║
║                                               ║
║  Or just type a message to chat.              ║
╚═══════════════════════════════════════════════╝
""")


def _route(line: str, cfg: Config, mb: MoltbookClient, coder: CoderAssistant) -> bool:
    """Route a user line to the right handler. Returns False to quit."""
    parts = line.strip().split(None, 2)
    if not parts:
        return True

    cmd = parts[0].lower()

    # --- quit ---
    if cmd in ("quit", "exit", "q"):
        print("Goodbye 🦞")
        return False

    # --- help ---
    if cmd in ("help", "h", "?"):
        _print_banner()
        return True

    # --- version ---
    if cmd in ("version", "ver"):
        print(f"PiAgent v{__version__}")
        return True

    # --- skill update ---
    if cmd == "skill-update":
        _show_skill_update(cfg)
        return True

    # --- engagement control ---
    if cmd == "engage-on":
        cfg.auto_engage = True
        print("[Agent] ✓ Auto-engagement enabled. Heartbeat will comment + upvote posts.")
        return True

    if cmd == "engage-off":
        cfg.auto_engage = False
        print("[Agent] ✓ Auto-engagement disabled. Heartbeat will only check for activity.")
        return True

    if cmd == "engage-status":
        status = "ENABLED" if cfg.auto_engage else "DISABLED"
        print(f"[Agent] Auto-engagement: {status}")
        if cfg.last_post_time:
            import time
            hours_since = (time.time() - cfg.last_post_time) / 3600
            mins_since = hours_since * 60
            if mins_since < 30:
                mins_until = 30 - mins_since
                print(f"[Agent] Last post: {mins_since:.1f} minutes ago (30-min cooldown: {mins_until:.1f} min remaining)")
            else:
                print(f"[Agent] Last post: {hours_since:.1f} hours ago (ready to post)")
        else:
            print(f"[Agent] Last post: Never (ready to post)")
        return True

    # --- groq setup ---
    if cmd == "groq-setup":
        print("[Agent] Groq API Setup")
        print("        Get your free API key at: https://console.groq.com/keys")
        key = input("        Enter Groq API key: ").strip()
        if key:
            cfg.groq_api_key = key
            print("[Agent] ✓ Groq API key saved!")
            print("        The agent will now use LLM for intelligent comments/posts.")
        else:
            print("[Agent] ✗ No key entered.")
        return True

    if cmd == "groq-status":
        from llm import LLMClient
        llm = LLMClient(cfg)
        if llm.is_available():
            print("[Agent] 🤖 Groq: Connected")
            print("        Model: llama-3.3-70b-versatile")
        else:
            print("[Agent] 🤖 Groq: Not configured")
            print("        Run 'groq-setup' to add your API key")
            print("        Currently using template-based responses")
        return True

    if cmd == "post-now":
        print("[Agent] Creating a post now (bypasses 30-minute cooldown)...")
        from llm import LLMClient
        from heartbeat import _create_post
        llm = LLMClient(cfg)
        title, content = llm.generate_post(use_llm=True)
        print(f"[Agent]   Topic: \"{title}\"")
        submolt = cfg.current_post_submolt()
        resp = _create_post(submolt, title, content, cfg.api_key)
        if resp.get("success"):
            post_id = resp.get("post", {}).get("id", "?")
            print(f"[Agent] ✓ Posted! https://www.moltbook.com/m/{submolt}/{post_id}")
            cfg.touch_last_post()
            cfg.advance_post_submolt()
        else:
            print(f"[Agent] ✗ Failed: {resp.get('error', 'unknown')}")
        return True

    if cmd == "post-targets":
        if len(parts) == 1:
            targets = cfg.post_submolts
            current = cfg.current_post_submolt()
            print("[Agent] Auto-post submolt targets:")
            for idx, target in enumerate(targets):
                marker = " (current)" if target == current else ""
                print(f"  {idx + 1}. {target}{marker}")
            print("  Set with: post-targets set general,raspberrypi,ai")
            return True

        action = parts[1].lower()
        payload = parts[2] if len(parts) > 2 else ""

        if action in ("set", "replace"):
            targets = [t.strip() for t in payload.split(",") if t.strip()]
            if not targets:
                print("[Agent] Usage: post-targets set general,raspberrypi,ai")
                return True
            cfg.post_submolts = targets
            print(f"[Agent] ✓ Auto-post targets updated: {', '.join(cfg.post_submolts)}")
            return True

        print("[Agent] Usage: post-targets set general,raspberrypi,ai")
        return True

    # --- heartbeat ---
    if cmd == "heartbeat":
        run_heartbeat(cfg, mb)
        return True

    # --- moltbook ---
    if cmd == "mb":
        sub = parts[1].lower() if len(parts) > 1 else ""
        args = parts[2] if len(parts) > 2 else ""
        mb.dispatch(sub, args)
        return True

    # --- code assistant ---
    if cmd == "code":
        # "code python write a script that ..."
        # "code bash ..."
        # "code <anything>" — treat rest as task
        rest = " ".join(parts[1:]) if len(parts) > 1 else ""
        coder.handle(rest)
        return True

    # --- fallback: treat entire input as a natural-language request ---
    _handle_freeform(line.strip(), cfg, mb, coder)
    return True


def _handle_freeform(text: str, cfg: Config, mb: MoltbookClient, coder: CoderAssistant):
    """Best-effort routing for plain-English input."""
    low = text.lower()

    # Moltbook intent keywords
    mb_keywords = ("moltbook", "molty", "post ", "comment ", "upvote", "downvote",
                   "feed", "submolt", "dm ", "heartbeat", "claim")
    if any(k in low for k in mb_keywords):
        print("[Agent] Looks like a Moltbook request. Use: mb <action> [args]")
        print("        Type 'mb help' for available actions.")
        return

    # Coding intent keywords
    code_keywords = ("write a script", "write code", "python", "bash", "shell",
                     "script", "function", "program", "snippet")
    if any(k in low for k in code_keywords):
        coder.handle(text)
        return

    # Generic catch-all
    print("[Agent] I can help with:")
    print("  • Moltbook social interactions  → mb <action>")
    print("  • Writing Python / Bash scripts → code <lang> <task>")
    print("  • Suggesting code in other languages too!")
    print()
    print("  Type 'help' for the full command list.")


def main():
    parser = argparse.ArgumentParser(description="PiAgent — lightweight Pi AI agent")
    parser.add_argument("--setup",     action="store_true", help="Register on Moltbook (first-run)")
    parser.add_argument("--heartbeat", action="store_true", help="Run one heartbeat tick and exit")
    args = parser.parse_args()

    cfg   = Config()
    mb    = MoltbookClient(cfg)
    coder = CoderAssistant()

    # --- one-shot modes ---
    if args.setup:
        mb.register()
        return
    if args.heartbeat:
        run_heartbeat(cfg, mb)
        return

    # --- interactive REPL ---
    _print_banner()
    while True:
        try:
            line = input("\n[PiAgent] > ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye 🦞")
            break
        if not _route(line, cfg, mb, coder):
            break


if __name__ == "__main__":
    main()
