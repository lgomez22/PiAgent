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
    python3 agent.py             # interactive REPL
    python3 agent.py --setup     # first-run: register on Moltbook
    python3 agent.py --heartbeat # run one heartbeat tick and exit
"""

__version__ = "0.2.5"

import argparse
import atexit
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import readline

# ---------------------------------------------------------------------------
# Memory guard — enforce 1 GB RSS cap (Linux only, RPi target)
# ---------------------------------------------------------------------------
def _apply_memory_cap(max_mb: int = 1024):
    try:
        import resource

        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        cap = max_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (cap, hard if hard == -1 else min(hard, cap)))
    except Exception:
        pass  # non-Linux or already capped — continue anyway


_apply_memory_cap(1024)

# ---------------------------------------------------------------------------
# Path bootstrap — make sibling imports work regardless of cwd
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from coder import CoderAssistant
from config import Config
from heartbeat import _create_post, run_heartbeat, run_threat_scan
from llm import LLMClient
from moltbook import MoltbookClient

_CONFIG_DIR = Path.home() / ".config" / "piagent"
_HISTORY_PATH = _CONFIG_DIR / "history"
_AUDIT_LOG = _CONFIG_DIR / "agent.log"
_SECURITY_DIR = _CONFIG_DIR / "security"
_LOCAL_MOLTTHREATS_BUNDLE = Path(__file__).with_name("molthreats_skill.md")
_REMOTE_MOLTTHREATS_SKILL = "https://promptintel.novahunting.ai/skill.md"


def _audit(command: str, status: str, detail: str = ""):
    """Append command audit lines to ~/.config/piagent/agent.log."""
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with _AUDIT_LOG.open("a", encoding="utf-8") as f:
            msg = f"[{ts}] cmd={command} status={status}"
            if detail:
                msg += f" detail={detail}"
            f.write(msg + "\n")
    except Exception:
        pass


def _setup_history():
    """Load and persist REPL history."""
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if _HISTORY_PATH.exists():
            readline.read_history_file(_HISTORY_PATH)
        readline.set_history_length(500)
        atexit.register(_save_history)
    except Exception:
        pass


def _save_history():
    try:
        readline.write_history_file(_HISTORY_PATH)
    except Exception:
        pass


def _show_skill_update(_: Config):
    """Show cached skill.md updates and offer to view them."""
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
    print(
        f"""
╔═══════════════════════════════════════════════╗
║            PiAgent  —  v{__version__}                 ║
║  Lightweight agent for Raspberry Pi 3B / 4    ║
║                                               ║
║  Commands:                                    ║
║    mb <action> [args]   Moltbook operations   ║
║    code <lang> <task>   Write a script        ║
║    heartbeat            Run heartbeat tick    ║
║    status               System health summary ║
║    engage-on/off        Toggle auto-engage    ║
║    engage-status        Check engage status   ║
║    threat-scan          Scan feed for threats ║
║    threats-on/off/status Toggle threat scan   ║
║    threat-skill-sync    Update MoltThreats    ║
║    threat-skill-status  Show skill version    ║
║    suspension-check     Check account status  ║
║    setup-email          Setup owner login     ║
║    post-now [--dry-run] Create post now       ║
║    post-targets ...     Manage post targets   ║
║    groq-setup           Configure Groq API    ║
║    groq-status          Check LLM status      ║
║    skill-update         View cached skills    ║
║    help                 Show this help        ║
║    quit / exit          Exit the agent        ║
║                                               ║
║  Or just type a message to chat.              ║
╚═══════════════════════════════════════════════╝
"""
    )
    # Defensive return keeps this function print-only even if downstream edits
    # accidentally append command logic inside the banner block.
    return


    print("[Agent] Owner Email Setup")
    print("        This allows your human to log in to Moltbook and manage your account.")

    value = email.strip() if email else input("        Enter owner email: ").strip()
    if not value or "@" not in value:
        print("[Agent] ✗ Invalid email address")
        return

    print(f"[Agent] Setting up email: {value}")
    try:
        data = json.dumps({"email": value}).encode()
        req = urllib.request.Request(
            "https://www.moltbook.com/api/v1/agents/me/setup-owner-email",
            data=data,
            method="POST",
        )
        req.add_header("Authorization", f"Bearer {cfg.api_key}")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=10) as r:
            response = json.loads(r.read().decode())

        if response.get("success"):
            print("[Agent] ✓ Email setup initiated!")
            print(f"        📧 Check {value} for a verification link")
            print("        Then verify X and log in to Moltbook.")
            return

        print(f"[Agent] ✗ Setup failed: {response.get('error', 'unknown')}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        print(f"[Agent] ✗ HTTP Error {e.code}: {body or e.reason}")
    except Exception as e:
        print(f"[Agent] ✗ Failed: {e}")

def _parse_molthreats_metadata(skill_text: str) -> dict:
    """Parse minimal metadata fields from frontmatter without external deps."""
    meta = {"version": "unknown", "last_updated": "unknown"}
    if not skill_text.startswith("---"):
        return meta

    lines = skill_text.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("version:"):
            meta["version"] = stripped.split(":", 1)[1].strip().strip('"')
        elif stripped.startswith("last_updated:"):
            meta["last_updated"] = stripped.split(":", 1)[1].strip().strip('"')
    return meta


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _is_recent(last_updated: str, hours: int = 24) -> bool:
    try:
        dt = datetime.strptime(last_updated, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() <= hours * 3600
    except Exception:
        return False


def _version_tuple(v: str):
    try:
        return tuple(int(p) for p in v.split("."))
    except Exception:
        return (0,)


def _sync_threat_skill() -> dict:
    """Check remote MoltThreats skill, then update local runtime copy if needed."""
    _SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    runtime_skill = _SECURITY_DIR / "molthreats_skill.md"

    local_text = _safe_read(runtime_skill)
    if not local_text and _LOCAL_MOLTTHREATS_BUNDLE.exists():
        local_text = _safe_read(_LOCAL_MOLTTHREATS_BUNDLE)
        if local_text:
            runtime_skill.write_text(local_text, encoding="utf-8")

    local_meta = _parse_molthreats_metadata(local_text)

    remote_text = ""
    remote_error = ""
    try:
        req = urllib.request.Request(_REMOTE_MOLTTHREATS_SKILL)
        req.add_header("User-Agent", "PiAgent/0.2.5")
        with urllib.request.urlopen(req, timeout=10) as r:
            remote_text = r.read().decode()
    except Exception as e:
        remote_error = str(e)

    if not remote_text:
        return {
            "updated": False,
            "source": "local-bundle",
            "local_version": local_meta.get("version", "unknown"),
            "local_last_updated": local_meta.get("last_updated", "unknown"),
            "error": remote_error,
            "path": str(runtime_skill),
        }

    remote_meta = _parse_molthreats_metadata(remote_text)
    should_update = False

    if _is_recent(remote_meta.get("last_updated", ""), 24):
        should_update = True
    elif _version_tuple(remote_meta.get("version", "0")) > _version_tuple(local_meta.get("version", "0")):
        should_update = True

    if should_update:
        runtime_skill.write_text(remote_text, encoding="utf-8")
        return {
            "updated": True,
            "source": "remote",
            "local_version": local_meta.get("version", "unknown"),
            "remote_version": remote_meta.get("version", "unknown"),
            "remote_last_updated": remote_meta.get("last_updated", "unknown"),
            "path": str(runtime_skill),
            "error": "",
        }

    return {
        "updated": False,
        "source": "remote-checked",
        "local_version": local_meta.get("version", "unknown"),
        "remote_version": remote_meta.get("version", "unknown"),
        "remote_last_updated": remote_meta.get("last_updated", "unknown"),
        "path": str(runtime_skill),
        "error": "",
    }


def _show_threat_skill_status():
    _SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    runtime_skill = _SECURITY_DIR / "molthreats_skill.md"
    text = _safe_read(runtime_skill)
    if not text:
        text = _safe_read(_LOCAL_MOLTTHREATS_BUNDLE)
    meta = _parse_molthreats_metadata(text)
    print("[Agent] MoltThreats skill status")
    print(f"  Version: {meta.get('version', 'unknown')}")
    print(f"  Last updated: {meta.get('last_updated', 'unknown')}")
    print(f"  Runtime path: {runtime_skill}")


def _run_threat_skill_sync():
    print("[Agent] Checking MoltThreats skill for updates...")
    result = _sync_threat_skill()
    if result.get("updated"):
        print(f"[Agent] ✓ Updated MoltThreats skill to v{result.get('remote_version', 'unknown')}")
        print(f"        Last updated: {result.get('remote_last_updated', 'unknown')}")
        print(f"        Path: {result.get('path', '')}")
        return

    if result.get("source") == "local-bundle":
        print("[Agent] ⚠️ Remote skill unavailable; using bundled/local MoltThreats skill copy.")
        print(f"        Local version: {result.get('local_version', 'unknown')}")
        if result.get("error"):
            print(f"        Remote check error: {result.get('error')}")
        print(f"        Path: {result.get('path', '')}")
        return

    print("[Agent] ✓ MoltThreats skill is already up to date.")
    print(f"        Local version: {result.get('local_version', 'unknown')}")
    print(f"        Remote version: {result.get('remote_version', 'unknown')}")
    print(f"        Path: {result.get('path', '')}")

def _show_engage_status(cfg: Config):
    status = "ENABLED" if cfg.auto_engage else "DISABLED"
    print(f"[Agent] Auto-engagement: {status}")
    if cfg.last_post_time:
        hours_since = (time.time() - cfg.last_post_time) / 3600
        mins_since = hours_since * 60
        if mins_since < 30:
            mins_until = 30 - mins_since
            print(f"[Agent] Last post: {mins_since:.1f} minutes ago ({mins_until:.1f} min cooldown remaining)")
        else:
            print(f"[Agent] Last post: {hours_since:.1f} hours ago (ready to post)")
    else:
        print("[Agent] Last post: Never (ready to post)")


def _show_status(cfg: Config):
    llm = LLMClient(cfg)
    hb = cfg.last_heartbeat
    heartbeat_text = "never"
    if hb:
        mins = (time.time() - hb) / 60
        heartbeat_text = f"{mins:.1f} minutes ago"

    print("[Agent] Status")
    print(f"  Version: v{__version__}")
    print(f"  Moltbook API key: {'configured' if cfg.api_key else 'missing'}")
    print(f"  Groq LLM: {'connected' if llm.is_available() else 'not configured'}")
    print(f"  Auto-engage: {'enabled' if cfg.auto_engage else 'disabled'}")
    print(f"  Last heartbeat: {heartbeat_text}")
    print(f"  Post targets: {', '.join(cfg.post_submolts)}")
    print(f"  Current target: {cfg.current_post_submolt()}")
    print(f"  Threat scan on heartbeat: {'enabled' if cfg.threat_scan_enabled else 'disabled'}")
    runtime_skill = _SECURITY_DIR / "molthreats_skill.md"
    skill_text = _safe_read(runtime_skill) or _safe_read(_LOCAL_MOLTTHREATS_BUNDLE)
    skill_meta = _parse_molthreats_metadata(skill_text)
    print(f"  MoltThreats skill: v{skill_meta.get('version', 'unknown')} ({skill_meta.get('last_updated', 'unknown')})")


def _run_post_now(cfg: Config, dry_run: bool = False):
    llm = LLMClient(cfg)
    title, content = llm.generate_post(use_llm=True)
    submolt = cfg.current_post_submolt()

    print(f"[Agent]   Target: m/{submolt}")
    print(f"[Agent]   Topic: \"{title}\"")

    if dry_run:
        print("[Agent]   Dry run only (no API request made).")
        print("\n--- post preview ---")
        print(content)
        print("--- end preview ---\n")
        return

    resp = _create_post(submolt, title, content, cfg.api_key)
    if resp.get("success"):
        post_id = resp.get("post", {}).get("id", "?")
        print(f"[Agent] ✓ Posted! https://www.moltbook.com/m/{submolt}/{post_id}")
        cfg.touch_last_post()
        cfg.advance_post_submolt()
        return

    print(f"[Agent] ✗ Failed: {resp.get('error', 'unknown')}")


def _handle_post_targets(cfg: Config, raw_args: str):
    """Structured subcommands for target management.

    Commands:
      post-targets / post-targets list
      post-targets set general,ai
      post-targets add raspberrypi
      post-targets remove general
      post-targets reset
    """
    tokens = raw_args.split()
    action = tokens[0].lower() if tokens else "list"

    if action == "list":
        targets = cfg.post_submolts
        current = cfg.post_submolt_index % len(targets)
        print("[Agent] Auto-post submolt targets:")
        for idx, target in enumerate(targets):
            marker = " (current)" if idx == current else ""
            print(f"  {idx + 1}. {target}{marker}")
        print("  Usage: post-targets set general,raspberrypi,ai")
        print("         post-targets add devops")
        print("         post-targets remove general")
        print("         post-targets reset")
        return

    if action in ("set", "replace"):
        payload = raw_args.split(None, 1)[1] if len(tokens) > 1 else ""
        targets = [t.strip() for t in payload.split(",") if t.strip()]
        if not targets:
            print("[Agent] Usage: post-targets set general,raspberrypi,ai")
            return
        cfg.post_submolts = targets
        print(f"[Agent] ✓ Auto-post targets updated: {', '.join(cfg.post_submolts)}")
        return

    if action == "add":
        if len(tokens) < 2:
            print("[Agent] Usage: post-targets add <submolt>")
            return
        add_name = tokens[1].strip()
        targets = cfg.post_submolts
        if add_name in targets:
            print(f"[Agent] '{add_name}' already in target list.")
            return
        targets.append(add_name)
        cfg.post_submolts = targets
        print(f"[Agent] ✓ Added '{add_name}'. Targets: {', '.join(cfg.post_submolts)}")
        return

    if action in ("remove", "rm", "del"):
        if len(tokens) < 2:
            print("[Agent] Usage: post-targets remove <submolt>")
            return
        remove_name = tokens[1].strip()
        targets = [t for t in cfg.post_submolts if t != remove_name]
        if len(targets) == len(cfg.post_submolts):
            print(f"[Agent] '{remove_name}' not found in target list.")
            return
        cfg.post_submolts = targets
        print(f"[Agent] ✓ Removed '{remove_name}'. Targets: {', '.join(cfg.post_submolts)}")
        return

    if action == "reset":
        cfg.post_submolts = ["general"]
        print("[Agent] ✓ Post targets reset to: general")
        return

    print("[Agent] Unknown post-targets action. Try: list, set, add, remove, reset")


def _run_threat_scan(cfg: Config, sample_posts: int = 10, comments_per_post: int = 5):
    """Run moltThreats-style scan on recent posts and comments."""
    if not cfg.api_key:
        print("[Agent] ✗ No API key found. Run: python3 agent.py --setup")
        return

    print(f"[Agent] Running threat scan on up to {sample_posts} posts...")
    findings = run_threat_scan(cfg.api_key, max_posts=sample_posts, comments_per_post=comments_per_post)

    if not findings:
        print("[Agent] ✓ No suspicious content detected in sampled posts/comments.")
        return

    print(f"[Agent] ⚠️ Found {len(findings)} suspicious item(s):")
    for i, finding in enumerate(findings[:20], 1):
        labels = ", ".join(finding.get("labels", []))
        if finding.get("type") == "post":
            print(f"  {i}. [post] id={finding.get('post_id')} by {finding.get('author')} labels={labels}")
            print(f"     title: {finding.get('title', '')[:90]}")
        else:
            print(f"  {i}. [comment] post={finding.get('post_id')} by {finding.get('author')} labels={labels}")
            print(f"     preview: {finding.get('preview', '')}")



def _check_suspension_status(cfg: Config):
    """Check whether the agent account is suspended or banned."""
    if not cfg.api_key:
        print("[Agent] ✗ No API key found. Run: python3 agent.py --setup")
        return

    print("[Agent] Checking account status...")
    try:
        req = urllib.request.Request("https://www.moltbook.com/api/v1/agents/me")
        req.add_header("Authorization", f"Bearer {cfg.api_key}")
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())

        agent_info = data.get("agent", data) if isinstance(data, dict) else {}
        suspended = bool(agent_info.get("suspended", False))
        banned = bool(agent_info.get("banned", False))

        if suspended or banned:
            status = "SUSPENDED" if suspended else "BANNED"
            reason = agent_info.get("suspension_reason") or agent_info.get("ban_reason") or "Unknown"
            print(f"[Agent] 🚨 Status: {status}")
            print(f"        Reason: {reason}")
            print(f"        Auto-engagement: {'ENABLED' if cfg.auto_engage else 'DISABLED'}")
            print("        💡 Run 'engage-off' if needed.")
            return

        print("[Agent] ✓ Account status: Active")
        print("        No suspension or ban detected")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        print(f"[Agent] ✗ HTTP Error {e.code}: {body or e.reason}")
    except Exception as e:
        print(f"[Agent] ✗ Failed to check status: {e}")


def _setup_owner_email(cfg: Config, email: str = ""):
    """Setup owner email so humans can manage the agent account."""
    if not cfg.api_key:
        print("[Agent] ✗ No API key found. Run: python3 agent.py --setup")
        return

    print("[Agent] Owner Email Setup")
    print("        This allows your human to log in to Moltbook and manage your account.")

    value = email.strip() if email else input("        Enter owner email: ").strip()
    if not value or "@" not in value:
        print("[Agent] ✗ Invalid email address")
        return

    print(f"[Agent] Setting up email: {value}")
    try:
        data = json.dumps({"email": value}).encode()
        req = urllib.request.Request(
            "https://www.moltbook.com/api/v1/agents/me/setup-owner-email",
            data=data,
            method="POST",
        )
        req.add_header("Authorization", f"Bearer {cfg.api_key}")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=10) as r:
            response = json.loads(r.read().decode())

        if response.get("success"):
            print("[Agent] ✓ Email setup initiated!")
            print(f"        📧 Check {value} for a verification link")
            print("        Then verify X and log in to Moltbook.")
            return

        print(f"[Agent] ✗ Setup failed: {response.get('error', 'unknown')}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        print(f"[Agent] ✗ HTTP Error {e.code}: {body or e.reason}")
    except Exception as e:
        print(f"[Agent] ✗ Failed: {e}")

def _route(line: str, cfg: Config, mb: MoltbookClient, coder: CoderAssistant) -> bool:
    """Route a user line to the right handler. Returns False to quit."""
    parts = line.strip().split(None, 2)
    if not parts:
        return True

    cmd = parts[0].lower()
    sub = parts[1] if len(parts) > 1 else ""
    args = parts[2] if len(parts) > 2 else ""

    if cmd in ("quit", "exit", "q"):
        _audit(cmd, "ok")
        print("Goodbye 🦞")
        return False

    def cmd_help():
        _print_banner()

    def cmd_version():
        print(f"PiAgent v{__version__}")

    def cmd_skill_update():
        _show_skill_update(cfg)

    def cmd_engage_on():
        cfg.auto_engage = True
        print("[Agent] ✓ Auto-engagement enabled. Heartbeat will comment + upvote posts.")

    def cmd_engage_off():
        cfg.auto_engage = False
        print("[Agent] ✓ Auto-engagement disabled. Heartbeat will only check for activity.")

    def cmd_engage_status():
        _show_engage_status(cfg)

    def cmd_status():
        _show_status(cfg)

    def cmd_threat_scan():
        _run_threat_scan(cfg)

    def cmd_threat_skill_sync():
        _run_threat_skill_sync()

    def cmd_threat_skill_status():
        _show_threat_skill_status()

    def cmd_threats_on():
        cfg.threat_scan_enabled = True
        print("[Agent] ✓ Heartbeat threat scan enabled")

    def cmd_threats_off():
        cfg.threat_scan_enabled = False
        print("[Agent] ✓ Heartbeat threat scan disabled")

    def cmd_threats_status():
        print(f"[Agent] Heartbeat threat scan: {'ENABLED' if cfg.threat_scan_enabled else 'DISABLED'}")

    def cmd_suspension_check():
        _check_suspension_status(cfg)

    def cmd_setup_email():
        _setup_owner_email(cfg)

    def cmd_groq_setup():
        print("[Agent] Groq API Setup")
        print("        Get your free API key at: https://console.groq.com/keys")
        key = input("        Enter Groq API key: ").strip()
        if key:
            cfg.groq_api_key = key
            print("[Agent] ✓ Groq API key saved!")
            print("        The agent will now use LLM for intelligent comments/posts.")
        else:
            print("[Agent] ✗ No key entered.")

    def cmd_groq_status():
        llm = LLMClient(cfg)
        if llm.is_available():
            print("[Agent] 🤖 Groq: Connected")
            print("        Model: llama-3.3-70b-versatile")
        else:
            print("[Agent] 🤖 Groq: Not configured")
            print("        Run 'groq-setup' to add your API key")
            print("        Currently using template-based responses")

    def cmd_heartbeat():
        run_heartbeat(cfg, mb)

    command_table = {
        "help": cmd_help,
        "h": cmd_help,
        "?": cmd_help,
        "version": cmd_version,
        "ver": cmd_version,
        "skill-update": cmd_skill_update,
        "engage-on": cmd_engage_on,
        "engage-off": cmd_engage_off,
        "engage-status": cmd_engage_status,
        "status": cmd_status,
        "threat-scan": cmd_threat_scan,
        "threat-skill-sync": cmd_threat_skill_sync,
        "threat-skill-status": cmd_threat_skill_status,
        "threats-on": cmd_threats_on,
        "threats-off": cmd_threats_off,
        "threats-status": cmd_threats_status,
        "suspension-check": cmd_suspension_check,
        "setup-email": cmd_setup_email,
        "groq-setup": cmd_groq_setup,
        "groq-status": cmd_groq_status,
        "heartbeat": cmd_heartbeat,
    }

    try:
        if cmd in command_table:
            command_table[cmd]()
            _audit(line, "ok")
            return True

        if cmd == "post-now":
            dry_run = sub.lower() in ("--dry-run", "--preview") if sub else False
            print("[Agent] Creating a post now...")
            _run_post_now(cfg, dry_run=dry_run)
            _audit(line, "ok", "dry-run" if dry_run else "posted")
            return True

        if cmd == "post-preview":
            print("[Agent] Generating post preview...")
            _run_post_now(cfg, dry_run=True)
            _audit(line, "ok", "preview")
            return True

        if cmd == "post-targets":
            post_args = " ".join(parts[1:]) if len(parts) > 1 else ""
            _handle_post_targets(cfg, post_args)
            _audit(line, "ok")
            return True

        if cmd == "mb":
            mb.dispatch(sub.lower() if sub else "", args)
            _audit(line, "ok")
            return True

        if cmd == "code":
            rest = " ".join(parts[1:]) if len(parts) > 1 else ""
            coder.handle(rest)
            _audit(line, "ok")
            return True

        _handle_freeform(line.strip(), cfg, mb, coder)
        _audit(line, "ok", "freeform")
        return True
    except Exception as e:
        _audit(line, "error", str(e))
        print(f"[Agent] ⚠️ Error: {e}")
        return True


def _handle_freeform(text: str, _: Config, __: MoltbookClient, coder: CoderAssistant):
    """Confidence-based routing for plain-English input."""
    low = text.lower()

    mb_keywords = (
        "moltbook",
        "molty",
        "post",
        "comment",
        "upvote",
        "downvote",
        "feed",
        "submolt",
        "dm",
        "heartbeat",
        "claim",
    )
    code_keywords = (
        "write a script",
        "write code",
        "python",
        "bash",
        "shell",
        "script",
        "function",
        "program",
        "snippet",
        "code",
    )

    mb_score = sum(1 for k in mb_keywords if k in low)
    code_score = sum(1 for k in code_keywords if k in low)

    if mb_score == 0 and code_score == 0:
        print("[Agent] I can help with:")
        print("  • Moltbook social interactions  → mb <action>")
        print("  • Writing Python / Bash scripts → code <lang> <task>")
        print("  • Type 'status' for a quick system snapshot")
        print("  • Type 'help' for the full command list")
        return

    if mb_score >= 2 and code_score < 2:
        print("[Agent] Looks like a Moltbook request.")
        print("        Use: mb <action> [args]")
        print("        Try: mb help")
        return

    if code_score >= 2 and mb_score < 2:
        coder.handle(text)
        return

    print("[Agent] I see both Moltbook and coding intent.")
    print("        If you want Moltbook: start with 'mb ...'")
    print("        If you want code: start with 'code ...'")


def _run_noninteractive_action(args, cfg: Config, mb: MoltbookClient):
    """Support ops-friendly one-shot commands without entering REPL."""
    if args.setup:
        mb.register()
        return True

    if args.heartbeat:
        run_heartbeat(cfg, mb)
        return True

    if args.post_now:
        _run_post_now(cfg, dry_run=False)
        return True

    if args.post_preview:
        _run_post_now(cfg, dry_run=True)
        return True

    if args.engage_on:
        cfg.auto_engage = True
        print("[Agent] ✓ Auto-engagement enabled")
        return True

    if args.engage_off:
        cfg.auto_engage = False
        print("[Agent] ✓ Auto-engagement disabled")
        return True

    if args.engage_status:
        _show_engage_status(cfg)
        return True

    if args.post_targets_set:
        _handle_post_targets(cfg, f"set {args.post_targets_set}")
        return True

    if args.status:
        _show_status(cfg)
        return True

    if args.threat_scan:
        _run_threat_scan(cfg, sample_posts=args.threat_posts, comments_per_post=args.threat_comments)
        return True

    if args.threat_skill_sync:
        _run_threat_skill_sync()
        return True

    if args.threat_skill_status:
        _show_threat_skill_status()
        return True

    if args.threats_on:
        cfg.threat_scan_enabled = True
        print("[Agent] ✓ Heartbeat threat scan enabled")
        return True

    if args.threats_off:
        cfg.threat_scan_enabled = False
        print("[Agent] ✓ Heartbeat threat scan disabled")
        return True

    if args.threats_status:
        print(f"[Agent] Heartbeat threat scan: {'ENABLED' if cfg.threat_scan_enabled else 'DISABLED'}")
        return True

    if args.suspension_check:
        _check_suspension_status(cfg)
        return True

    if args.setup_email:
        _setup_owner_email(cfg, args.setup_email)
        return True

    return False


def main():
    parser = argparse.ArgumentParser(description="PiAgent — lightweight Pi AI agent")
    parser.add_argument("--setup", action="store_true", help="Register on Moltbook (first-run)")
    parser.add_argument("--heartbeat", action="store_true", help="Run one heartbeat tick and exit")
    parser.add_argument("--post-now", action="store_true", help="Create a post and exit")
    parser.add_argument("--post-preview", action="store_true", help="Preview generated post and exit")
    parser.add_argument("--engage-on", action="store_true", help="Enable auto-engagement and exit")
    parser.add_argument("--engage-off", action="store_true", help="Disable auto-engagement and exit")
    parser.add_argument("--engage-status", action="store_true", help="Show engagement status and exit")
    parser.add_argument("--post-targets-set", type=str, default="", help="Replace auto-post targets, comma-separated")
    parser.add_argument("--status", action="store_true", help="Show one-line system snapshot and exit")
    parser.add_argument("--threat-scan", action="store_true", help="Run moltThreats-style scan and exit")
    parser.add_argument("--threat-skill-sync", action="store_true", help="Check/update local MoltThreats skill copy and exit")
    parser.add_argument("--threat-skill-status", action="store_true", help="Show local MoltThreats skill version and exit")
    parser.add_argument("--threat-posts", type=int, default=10, help="Posts to sample during --threat-scan")
    parser.add_argument("--threat-comments", type=int, default=5, help="Comments per post during --threat-scan")
    parser.add_argument("--threats-on", action="store_true", help="Enable heartbeat threat scan and exit")
    parser.add_argument("--threats-off", action="store_true", help="Disable heartbeat threat scan and exit")
    parser.add_argument("--threats-status", action="store_true", help="Show heartbeat threat scan state and exit")
    parser.add_argument("--suspension-check", action="store_true", help="Check account suspension/ban status and exit")
    parser.add_argument("--setup-email", type=str, default="", help="Setup owner email and exit")
    args = parser.parse_args()

    cfg = Config()
    mb = MoltbookClient(cfg)
    coder = CoderAssistant()

    if _run_noninteractive_action(args, cfg, mb):
        return

    _setup_history()
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
