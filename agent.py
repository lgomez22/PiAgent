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

__version__ = "0.3.0-rc1"

import argparse
import atexit
import json
import os
import re
import threading
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
_API_LOG = _CONFIG_DIR / "api.log"
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


def _api_audit(endpoint: str, method: str, status: str, body: str = ""):
    """Append Moltbook API request/response diagnostics to ~/.config/piagent/api.log."""
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with _API_LOG.open("a", encoding="utf-8") as f:
            line = f"[{ts}] {method} {endpoint} status={status}"
            if body:
                compact = " ".join(body.replace("\n", " ").split())
                line += f" body={compact[:700]}"
            f.write(line + "\n")
    except Exception:
        pass


def _moltbook_api_json(cfg: Config, method: str, endpoint: str, payload: dict = None) -> tuple:
    """Call Moltbook API endpoint and return (status_code, parsed_json_or_none, raw_text)."""
    # Compatibility: if caller passes legacy `submolt`, map it to `submolt_name`.
    if isinstance(payload, dict) and "submolt" in payload and "submolt_name" not in payload:
        payload = dict(payload)
        payload["submolt_name"] = payload.pop("submolt")

    url = "https://www.moltbook.com/api/v1" + endpoint
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {cfg.api_key}")
    if payload is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
            parsed = json.loads(raw) if raw else {}
            _api_audit(endpoint, method, str(r.status), raw)
            return r.status, parsed, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        parsed = None
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = None
        _api_audit(endpoint, method, str(e.code), raw or str(e.reason))
        return e.code, parsed, raw
    except Exception as e:
        _api_audit(endpoint, method, "error", str(e))
        return 0, None, str(e)


def _show_api_log(lines: int = 30):
    if not _API_LOG.exists():
        print("[Agent] No API log entries yet.")
        return
    try:
        entries = _API_LOG.read_text(encoding="utf-8").splitlines()
        tail = entries[-lines:]
        print(f"[Agent] Last {len(tail)} API log entries ({_API_LOG}):")
        for ln in tail:
            print(f"  {ln}")
    except Exception as e:
        print(f"[Agent] ✗ Failed to read API log: {e}")




def _latest_write_block_from_api_log() -> tuple:
    """Return (until_ts, reason, line) from recent /posts 403 entries in api log."""
    if not _API_LOG.exists():
        return "", "", ""
    try:
        lines = _API_LOG.read_text(encoding="utf-8").splitlines()
    except Exception:
        return "", "", ""

    for line in reversed(lines[-200:]):
        low = line.lower()
        if "/posts" not in low or "status=403" not in low:
            continue
        until_ts = ""
        reason = ""
        m = re.search(r"suspended until\s+([0-9t:\-.z]+)", line, flags=re.IGNORECASE)
        if m:
            until_ts = m.group(1)
        m2 = re.search(r'reason:\s*([^\"]+?)(?:\"|$)', line, flags=re.IGNORECASE)
        if m2:
            reason = m2.group(1).strip()
        if not reason and "forbidden" in low:
            reason = "Forbidden on /posts"
        return until_ts, reason, line
    return "", "", ""


def _probe_write_capability(cfg: Config) -> tuple:
    """Safe write-capability probe using intentionally invalid post payload.

    Returns: (state, message)
      - WRITE_BLOCKED_UNTIL <ts>
      - WRITE_BLOCKED
      - WRITE_ALLOWED_OR_VALIDATION
      - WRITE_PROBE_FAILED
    """
    status, data, raw = _moltbook_api_json(
        cfg,
        "POST",
        "/posts",
        payload={"submolt_name": "general", "title": "", "content": ""},
    )
    txt = ""
    if isinstance(data, dict):
        txt = json.dumps(data)
    else:
        txt = raw or ""
    low = txt.lower()

    if status == 403:
        m = re.search(r"suspended until\s+([0-9t:\-.z]+)", txt, flags=re.IGNORECASE)
        if m:
            return f"WRITE_BLOCKED_UNTIL {m.group(1)}", txt[:220]
        return "WRITE_BLOCKED", txt[:220]

    if status in (200, 201, 400, 401, 422):
        return "WRITE_ALLOWED_OR_VALIDATION", txt[:220]

    return "WRITE_PROBE_FAILED", f"status={status} {txt[:180]}"


def _post_debug(cfg: Config):
    """Print post preflight diagnostics with latest block reason."""
    print("[Agent] Post debug")
    api_present = bool(cfg.api_key)
    target = cfg.current_post_submolt()
    title, content = _generate_post_with_failover(cfg)
    payload_keys = ["submolt_name", "title", "content"]

    print(f"  Auth present: {'yes' if api_present else 'no'}")
    print(f"  Target submolt: {target}")
    print(f"  Payload keys: {', '.join(payload_keys)}")
    print(f"  Title length: {len(title)}")
    print(f"  Content length: {len(content)}")

    until_ts, reason, _ = _latest_write_block_from_api_log()
    if until_ts or reason:
        print("  Latest write-block (from api.log):")
        if until_ts:
            print(f"    Until: {until_ts}")
        if reason:
            print(f"    Reason: {reason}")
    else:
        print("  Latest write-block: none found in api.log")


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
=======================================================
 PiAgent v{__version__} - Raspberry Pi 3B/4 assistant
=======================================================
 Commands:
   mb <action> [args]    Moltbook operations
   code <lang> <task>    Write a script
   heartbeat             Run heartbeat tick
   status                System health summary
   engage-on/off         Toggle auto-engage
   engage-status         Check engage status
   doctor                Run health checks
   dm-policy ...         Pairing/allowlist DM
   guardrail ...         Action guardrails
   model-failover ...    LLM fallback order
   webhook-listen        Local webhook mode
   threat-scan           Scan feed for threats
   threats-on/off/status Toggle threat scan
   threat-skill-sync     Update MoltThreats
   threat-skill-status   Show skill version
   api-log               Show recent API logs
   suspension-check      Check account status
   setup-email           Setup owner login
   post-now [--dry-run]  Create post now
   post-debug            Post diagnostics
   post-targets ...      Manage post targets
   submolt-autonomy      Auto curate submolts
   groq-setup            Configure Groq API
   groq-status           Check LLM status
   skill-update          View cached skills
   help                  Show this help
   quit / exit           Exit the agent

 Or just type a message to chat.
"""
    )
    # Defensive return keeps this function print-only even if downstream edits
    # accidentally append command logic inside the banner block.
    return



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
        req.add_header("User-Agent", f"PiAgent/{__version__}")
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
    print(f"  DM policy: {cfg.dm_policy} (allowlist size: {len(cfg.dm_allowlist)})")
    print(f"  Guardrail mode: {cfg.guardrail_mode}")
    print(f"  Model failover: {', '.join(cfg.model_failover_order)}")
    runtime_skill = _SECURITY_DIR / "molthreats_skill.md"
    skill_text = _safe_read(runtime_skill) or _safe_read(_LOCAL_MOLTTHREATS_BUNDLE)
    skill_meta = _parse_molthreats_metadata(skill_text)
    print(f"  MoltThreats skill: v{skill_meta.get('version', 'unknown')} ({skill_meta.get('last_updated', 'unknown')})")



def _doctor(cfg: Config):
    """Run quick local diagnostics for common deployment issues."""
    print("[Agent] Running doctor checks...")
    checks = []
    checks.append(("Moltbook API key configured", bool(cfg.api_key)))
    checks.append(("Groq API key configured", bool(cfg.groq_api_key)))
    checks.append(("Config dir exists", _CONFIG_DIR.exists()))
    checks.append(("Agent log path writable", _CONFIG_DIR.exists()))
    checks.append(("MoltThreats runtime skill present", (_SECURITY_DIR / "molthreats_skill.md").exists() or _LOCAL_MOLTTHREATS_BUNDLE.exists()))
    checks.append(("Heartbeat timestamp recorded", cfg.last_heartbeat is not None))
    checks.append(("DM policy valid", cfg.dm_policy in ("open", "pairing", "allowlist")))
    checks.append(("Guardrail mode valid", cfg.guardrail_mode in ("allow", "require_approval", "block")))

    for name, ok in checks:
        print(f"  {'✅' if ok else '⚠️'} {name}")


def _guardrail_allows(cfg: Config, action_name: str, interactive: bool = True) -> bool:
    """Enforce action policy before sensitive actions."""
    mode = cfg.guardrail_mode
    if mode == "allow":
        return True
    if mode == "block":
        print(f"[Agent] ⛔ Blocked by guardrail policy: {action_name}")
        return False
    if not interactive:
        print(f"[Agent] ⛔ Non-interactive action requires approval: {action_name}")
        return False

    ans = input(f"[Agent] Approve sensitive action '{action_name}'? (y/n): ").strip().lower()
    return ans == "y"




def _extract_dm_conversations(payload) -> list:
    """Best-effort normalization for DM conversation API variants."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    candidates = (
        payload.get("conversations"),
        payload.get("data"),
        payload.get("items"),
        payload.get("results"),
    )
    for c in candidates:
        if isinstance(c, list):
            return c
        if isinstance(c, dict):
            nested = c.get("conversations") or c.get("items") or c.get("results") or c.get("data")
            if isinstance(nested, list):
                return nested

    # pagination-style object: {data:{rows:[...]}} or {rows:[...]}
    rows = payload.get("rows")
    if isinstance(rows, list):
        return rows
    if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("rows"), list):
        return payload["data"]["rows"]

    return []


def _dm_payload_is_empty_inbox(payload) -> bool:
    """Return True when DM API payload explicitly indicates zero conversations."""
    if not isinstance(payload, dict):
        return False

    conv = payload.get("conversations")
    if isinstance(conv, dict):
        count = conv.get("count")
        items = conv.get("items")
        try:
            count_num = int(str(count).strip()) if count is not None else None
        except Exception:
            count_num = None
        if count_num == 0:
            return True
        if isinstance(items, list) and not items:
            return True

    total_unread = payload.get("total_unread")
    inbox = payload.get("inbox")
    if str(total_unread).strip() in ("0", "00") and inbox:
        return True

    return False


def _extract_dm_counterpart_name(conv: dict) -> str:
    """Extract sender/counterpart name from multiple conversation shapes."""
    if not isinstance(conv, dict):
        return ""

    candidates = [
        conv.get("with"),
        conv.get("participant"),
        conv.get("other_party"),
        conv.get("counterpart"),
        conv.get("user"),
        conv.get("from"),
        conv.get("sender"),
        conv.get("peer"),
    ]

    # Also inspect recent message object if present
    for key in ("last_message", "lastMessage", "latest_message", "latestMessage"):
        msg = conv.get(key)
        if isinstance(msg, dict):
            candidates.extend([msg.get("from"), msg.get("sender"), msg.get("author")])

    for obj in candidates:
        if isinstance(obj, dict):
            for k in ("name", "username", "display_name", "handle", "id"):
                v = obj.get(k)
                if v:
                    return str(v).strip()
        elif obj:
            return str(obj).strip()

    return ""


def _check_dm_pairing(cfg: Config):
    """Inspect DM conversations and report unpaired senders for pairing/allowlist modes."""
    if cfg.dm_policy == "open":
        print("[Agent] DM policy is OPEN. No pairing checks required.")
        return
    if not cfg.api_key:
        print("[Agent] ✗ No API key found. Run: python3 agent.py --setup")
        return

    print(f"[Agent] Checking DM conversations under policy: {cfg.dm_policy}")
    status_code, data, raw = _moltbook_api_json(cfg, "GET", "/agents/dm/conversations")
    if status_code >= 400:
        print(f"[Agent] ✗ Failed to fetch conversations: {raw[:200]}")
        return

    conversations = _extract_dm_conversations(data)
    if not conversations:
        if _dm_payload_is_empty_inbox(data):
            print("[Agent] ✓ No DM conversations in inbox.")
            return
        print("[Agent] ⚠️ Unexpected DM conversation response format")
        preview = raw[:220].replace("\n", " ") if raw else str(data)[:220]
        print(f"        Preview: {preview}")
        print(f"        API log: {_API_LOG}")
        return

    unknown = []
    for conv in conversations:
        name = _extract_dm_counterpart_name(conv)
        if not name:
            continue
        if name not in cfg.dm_allowlist:
            unknown.append(name)

    if not unknown:
        print("[Agent] ✓ No unpaired DM senders detected.")
        return

    uniq = sorted(set(unknown))
    print(f"[Agent] ⚠️ Unpaired DM senders: {', '.join(uniq)}")
    print("        Approve with: dm-policy pair <sender_name>")


def _handle_dm_policy(cfg: Config, raw_args: str):
    tokens = raw_args.split()
    action = tokens[0].lower() if tokens else "status"

    if action in ("status", "show"):
        print(f"[Agent] DM policy: {cfg.dm_policy}")
        if cfg.dm_allowlist:
            print(f"[Agent] Pairings: {', '.join(cfg.dm_allowlist)}")
        else:
            print("[Agent] Pairings: (none)")
        return

    if action == "set":
        mode = tokens[1].lower() if len(tokens) > 1 else ""
        if mode not in ("open", "pairing", "allowlist"):
            print("[Agent] Usage: dm-policy set open|pairing|allowlist")
            return
        cfg.dm_policy = mode
        print(f"[Agent] ✓ DM policy set to: {cfg.dm_policy}")
        return

    if action in ("pair", "approve", "add"):
        name = " ".join(tokens[1:]).strip()
        if not name:
            print("[Agent] Usage: dm-policy pair <sender_name>")
            return
        allow = cfg.dm_allowlist
        if name not in allow:
            allow.append(name)
            cfg.dm_allowlist = allow
        print(f"[Agent] ✓ Paired sender: {name}")
        return

    if action in ("unpair", "remove"):
        name = " ".join(tokens[1:]).strip()
        if not name:
            print("[Agent] Usage: dm-policy unpair <sender_name>")
            return
        allow = [x for x in cfg.dm_allowlist if x != name]
        cfg.dm_allowlist = allow
        print(f"[Agent] ✓ Removed pairing: {name}")
        return

    if action == "check":
        _check_dm_pairing(cfg)
        return

    print("[Agent] Usage: dm-policy status|set open|pairing|allowlist|pair <name>|unpair <name>|check")


def _handle_guardrail(cfg: Config, raw_args: str):
    tokens = raw_args.split()
    action = tokens[0].lower() if tokens else "status"
    if action in ("status", "show"):
        print(f"[Agent] Guardrail mode: {cfg.guardrail_mode}")
        return
    if action == "set":
        mode = tokens[1].lower() if len(tokens) > 1 else ""
        if mode not in ("allow", "require_approval", "block"):
            print("[Agent] Usage: guardrail set allow|require_approval|block")
            return
        cfg.guardrail_mode = mode
        print(f"[Agent] ✓ Guardrail mode set to: {cfg.guardrail_mode}")
        return
    print("[Agent] Usage: guardrail status|set allow|require_approval|block")


def _handle_model_failover(cfg: Config, raw_args: str):
    tokens = raw_args.split()
    action = tokens[0].lower() if tokens else "status"
    if action in ("status", "show"):
        print(f"[Agent] Model failover order: {', '.join(cfg.model_failover_order)}")
        return
    if action == "set":
        payload = " ".join(tokens[1:]).strip()
        vals = [v.strip().lower() for v in payload.replace(';', ',').split(',') if v.strip()]
        if not vals:
            print("[Agent] Usage: model-failover set groq,template")
            return
        cfg.model_failover_order = vals
        print(f"[Agent] ✓ Model failover order set: {', '.join(cfg.model_failover_order)}")
        return
    print("[Agent] Usage: model-failover status|set groq,template")


def _generate_post_with_failover(cfg: Config) -> tuple:
    llm = LLMClient(cfg)
    for provider in cfg.model_failover_order:
        if provider == "groq" and llm.is_available():
            return llm.generate_post(use_llm=True)
        if provider == "template":
            return llm.generate_post(use_llm=False)
    return llm.generate_post(use_llm=False)


def _run_webhook_listener(cfg: Config, host: str = "127.0.0.1", port: int = 18999, token: str = ""):
    """Local webhook endpoint for external triggers."""
    _token = token.strip()
    print(f"[Agent] Webhook listener starting on http://{host}:{port}/trigger")
    if _token:
        print("[Agent] Token auth enabled (X-PiAgent-Token required)")

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, payload: dict):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/trigger":
                self._reply(404, {"ok": False, "error": "not found"})
                return
            if _token and self.headers.get("X-PiAgent-Token", "") != _token:
                self._reply(401, {"ok": False, "error": "invalid token"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode() if length > 0 else "{}"
                payload = json.loads(raw)
            except Exception:
                self._reply(400, {"ok": False, "error": "invalid json"})
                return

            action = str(payload.get("action", "status")).strip().lower()
            if action == "status":
                self._reply(200, {"ok": True, "version": __version__, "auto_engage": cfg.auto_engage})
                return
            if action == "heartbeat":
                threading.Thread(target=run_heartbeat, args=(cfg, None), daemon=True).start()
                self._reply(202, {"ok": True, "message": "heartbeat scheduled"})
                return
            if action == "threat_scan":
                posts = int(payload.get("posts", 10))
                comments = int(payload.get("comments", 5))
                threading.Thread(target=_run_threat_scan, args=(cfg, posts, comments), daemon=True).start()
                self._reply(202, {"ok": True, "message": "threat scan scheduled"})
                return
            if action == "post_now":
                if not _guardrail_allows(cfg, "webhook.post_now", interactive=False):
                    self._reply(403, {"ok": False, "error": "blocked by guardrail"})
                    return
                threading.Thread(target=_run_post_now, args=(cfg, False), daemon=True).start()
                self._reply(202, {"ok": True, "message": "post scheduled"})
                return
            self._reply(400, {"ok": False, "error": f"unsupported action: {action}"})

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[Agent] Webhook listener stopped")


def _run_post_now(cfg: Config, dry_run: bool = False):
    title, content = _generate_post_with_failover(cfg)
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




def _extract_submolt_list(payload: dict) -> list:
    if not isinstance(payload, dict):
        return []
    data = payload.get("submolts", payload.get("data", []))
    if not isinstance(data, list):
        return []
    items = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("slug") or "").strip()
        if not name:
            continue
        desc = str(raw.get("description") or raw.get("about") or "").strip()
        subscribed = bool(raw.get("subscribed") or raw.get("is_subscribed") or raw.get("subscribed_by_me"))
        items.append({"name": name, "description": desc, "subscribed": subscribed})
    return items


def _top_post_titles_for_submolt(cfg: Config, name: str, limit: int = 3) -> list:
    q = urllib.parse.quote(name)
    status, data, _ = _moltbook_api_json(cfg, "GET", f"/posts?sort=top&limit={limit}&submolt={q}")
    if status < 200 or status >= 300 or not isinstance(data, dict):
        return []
    posts = data.get("posts", data.get("data", []))
    if not isinstance(posts, list):
        return []
    titles = []
    for p in posts[:limit]:
        if isinstance(p, dict):
            t = str(p.get("title") or "").strip()
            if t:
                titles.append(t)
    return titles


def _run_submolt_autonomy(cfg: Config, max_subscriptions: int = 10, include_targets: int = 6):
    if not cfg.api_key:
        print("[Agent] ✗ No API key found. Run: python3 agent.py --setup")
        return

    print("[Agent] Running submolt autonomy scan...")
    status, data, _ = _moltbook_api_json(cfg, "GET", "/submolts")
    if status < 200 or status >= 300:
        print(f"[Agent] ✗ Failed to fetch submolts (status={status}).")
        print(f"        API log: {_API_LOG}")
        return

    submolts = _extract_submolt_list(data)
    if not submolts:
        print("[Agent] No submolts returned by API.")
        return

    llm = LLMClient(cfg)
    scored = []
    for entry in submolts[:30]:
        top_titles = _top_post_titles_for_submolt(cfg, entry["name"], limit=3)
        evald = llm.evaluate_submolt_fit(entry["name"], entry["description"], top_titles)
        scored.append({
            "name": entry["name"],
            "description": entry["description"],
            "subscribed": entry["subscribed"],
            "score": float(evald.get("score", 0.0)),
            "decision": str(evald.get("decision", "watch")),
            "reason": str(evald.get("reason", "")),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    desired = [s["name"] for s in scored[:max_subscriptions]]
    current = {s["name"] for s in scored if s["subscribed"]}

    to_sub = [n for n in desired if n not in current]
    to_unsub = [n for n in current if n not in desired]

    for name in to_sub:
        st, _, _ = _moltbook_api_json(cfg, "POST", f"/submolts/{urllib.parse.quote(name)}/subscribe")
        if 200 <= st < 300:
            print(f"[Agent] ✓ Subscribed: {name}")
        else:
            print(f"[Agent] ⚠️ Subscribe failed: {name} (status={st})")

    for name in to_unsub:
        st, _, _ = _moltbook_api_json(cfg, "DELETE", f"/submolts/{urllib.parse.quote(name)}/subscribe")
        if 200 <= st < 300:
            print(f"[Agent] ✓ Unsubscribed: {name}")
        else:
            print(f"[Agent] ⚠️ Unsubscribe failed: {name} (status={st})")

    new_targets = desired[:max(1, min(include_targets, len(desired)))]
    if not new_targets:
        new_targets = ["general"]
    cfg.post_submolts = new_targets

    print("[Agent] Submolt ranking (top 10):")
    for i, item in enumerate(scored[:10], 1):
        print(f"  {i}. {item['name']} score={item['score']:.2f} decision={item['decision']} ({item['reason']})")

    print(f"[Agent] ✓ Post target rotation updated: {', '.join(cfg.post_submolts)}")
    print(f"[Agent] ✓ Subscription cap enforced at {max_subscriptions} submolts.")

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
        status_code, data, raw = _moltbook_api_json(cfg, "GET", "/agents/me")

        if status_code == 401:
            hint = ""
            if isinstance(data, dict):
                hint = data.get("hint", "")
            print("[Agent] ✗ Unauthorized / suspended response from Moltbook")
            if hint:
                print(f"        Hint: {hint}")
                low = hint.lower()
                if "challenge" in low or "verification" in low:
                    print("        ℹ️ AI challenge/verification likely required by Moltbook.")
                    print("        Next: collect the exact challenge prompt from API logs and solve it before retrying.")
            print(f"        API log: {_API_LOG}")
            return

        if not isinstance(data, dict):
            print(f"[Agent] ⚠️ Unexpected response format: {raw[:200]}")
            print(f"        API log: {_API_LOG}")
            return

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

        probe_state, probe_msg = _probe_write_capability(cfg)
        if probe_state.startswith("WRITE_BLOCKED_UNTIL"):
            print(f"[Agent] ⚠️ Capability state: READ_ACTIVE / {probe_state}")
            print(f"        Detail: {probe_msg}")
            return
        if probe_state == "WRITE_BLOCKED":
            print("[Agent] ⚠️ Capability state: READ_ACTIVE / WRITE_BLOCKED")
            print(f"        Detail: {probe_msg}")
            return
        print("[Agent] ✓ Capability state: READ_ACTIVE / WRITE_ALLOWED_OR_VALIDATION")
    except Exception as e:
        print(f"[Agent] ✗ Failed to check status: {e}")
        print(f"        API log: {_API_LOG}")


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
        status_code, response, raw = _moltbook_api_json(
            cfg,
            "POST",
            "/agents/me/setup-owner-email",
            payload={"email": value},
        )

        if status_code >= 400:
            if isinstance(response, dict):
                print(f"[Agent] ✗ Setup failed: {response.get('error', 'unknown')}")
                if response.get("hint"):
                    print(f"        Hint: {response.get('hint')}")
            else:
                print(f"[Agent] ✗ Setup failed: {raw[:200]}")
            print(f"        API log: {_API_LOG}")
            return

        if not isinstance(response, dict):
            print(f"[Agent] ✗ Setup failed: Unexpected response ({raw[:200]})")
            print(f"        API log: {_API_LOG}")
            return

        if response.get("success"):
            print("[Agent] ✓ Email setup initiated!")
            print(f"        📧 Check {value} for a verification link")
            print("        Then verify X and log in to Moltbook.")
            return

        print(f"[Agent] ✗ Setup failed: {response.get('error', 'unknown')}")
    except Exception as e:
        print(f"[Agent] ✗ Failed: {e}")
        print(f"        API log: {_API_LOG}")

def _route(line: str, cfg: Config, mb: MoltbookClient, coder: CoderAssistant) -> bool:
    """Route a user line to the right handler. Returns False to quit."""
    # Defensive alias for merge resilience: some conflict resolutions previously
    # left `if mode == ...` checks in this function. Keep a local binding so such
    # regressions fail closed instead of crashing with NameError.
    mode = cfg.guardrail_mode

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

    def cmd_doctor():
        _doctor(cfg)

    def cmd_dm_policy():
        _handle_dm_policy(cfg, " ".join(parts[1:]) if len(parts) > 1 else "status")

    def cmd_guardrail():
        _handle_guardrail(cfg, " ".join(parts[1:]) if len(parts) > 1 else "status")

    def cmd_model_failover():
        _handle_model_failover(cfg, " ".join(parts[1:]) if len(parts) > 1 else "status")

    def cmd_webhook_listen():
        token = os.environ.get("PIAGENT_WEBHOOK_TOKEN", "")
        _run_webhook_listener(cfg, host="127.0.0.1", port=18999, token=token)

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

    def cmd_api_log():
        _show_api_log(30)

    def cmd_suspension_check():
        _check_suspension_status(cfg)

    def cmd_setup_email():
        if not _guardrail_allows(cfg, "setup-email", interactive=True):
            return
        _setup_owner_email(cfg)

    def cmd_post_debug():
        _post_debug(cfg)

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
        if cfg.dm_policy != "open":
            _check_dm_pairing(cfg)
        run_heartbeat(cfg, mb)

    def cmd_submolt_autonomy():
        _run_submolt_autonomy(cfg)

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
        "doctor": cmd_doctor,
        "dm-policy": cmd_dm_policy,
        "guardrail": cmd_guardrail,
        "model-failover": cmd_model_failover,
        "webhook-listen": cmd_webhook_listen,
        "threat-scan": cmd_threat_scan,
        "threat-skill-sync": cmd_threat_skill_sync,
        "threat-skill-status": cmd_threat_skill_status,
        "threats-on": cmd_threats_on,
        "threats-off": cmd_threats_off,
        "threats-status": cmd_threats_status,
        "api-log": cmd_api_log,
        "suspension-check": cmd_suspension_check,
        "setup-email": cmd_setup_email,
        "post-debug": cmd_post_debug,
        "groq-setup": cmd_groq_setup,
        "groq-status": cmd_groq_status,
        "heartbeat": cmd_heartbeat,
        "submolt-autonomy": cmd_submolt_autonomy,
    }

    try:
        if cmd in command_table:
            command_table[cmd]()
            _audit(line, "ok")
            return True

        if cmd == "post-now":
            dry_run = sub.lower() in ("--dry-run", "--preview") if sub else False
            if not dry_run and not _guardrail_allows(cfg, "post-now", interactive=True):
                _audit(line, "blocked", "guardrail")
                return True
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
        if cfg.dm_policy != "open":
            _check_dm_pairing(cfg)
        run_heartbeat(cfg, mb)
        return True

    if args.post_now:
        if not _guardrail_allows(cfg, "post-now", interactive=False):
            return True
        _run_post_now(cfg, dry_run=False)
        return True

    if args.post_preview:
        _run_post_now(cfg, dry_run=True)
        return True

    if args.post_debug:
        _post_debug(cfg)
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

    if args.submolt_autonomy:
        _run_submolt_autonomy(cfg)
        return True

    if args.status:
        _show_status(cfg)
        return True

    if args.doctor:
        _doctor(cfg)
        return True

    if args.dm_policy_set:
        _handle_dm_policy(cfg, f"set {args.dm_policy_set}")
        return True

    if args.guardrail_set:
        _handle_guardrail(cfg, f"set {args.guardrail_set}")
        return True

    if args.model_failover_set:
        _handle_model_failover(cfg, f"set {args.model_failover_set}")
        return True

    if args.webhook_listen:
        token = args.webhook_token or os.environ.get("PIAGENT_WEBHOOK_TOKEN", "")
        _run_webhook_listener(cfg, host=args.webhook_host, port=args.webhook_port, token=token)
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

    if args.api_log:
        _show_api_log(50)
        return True

    if args.suspension_check:
        _check_suspension_status(cfg)
        return True

    if args.setup_email:
        if cfg.guardrail_mode == "block":
            print("[Agent] ⛔ Blocked by guardrail policy: setup-email")
            return True
        if not _guardrail_allows(cfg, "setup-email", interactive=False):
            return True
        _setup_owner_email(cfg, args.setup_email)
        return True

    return False


def main():
    parser = argparse.ArgumentParser(description="PiAgent — lightweight Pi AI agent")
    parser.add_argument("--setup", action="store_true", help="Register on Moltbook (first-run)")
    parser.add_argument("--heartbeat", action="store_true", help="Run one heartbeat tick and exit")
    parser.add_argument("--post-now", action="store_true", help="Create a post and exit")
    parser.add_argument("--post-preview", action="store_true", help="Preview generated post and exit")
    parser.add_argument("--post-debug", action="store_true", help="Show post preflight diagnostics and exit")
    parser.add_argument("--engage-on", action="store_true", help="Enable auto-engagement and exit")
    parser.add_argument("--engage-off", action="store_true", help="Disable auto-engagement and exit")
    parser.add_argument("--engage-status", action="store_true", help="Show engagement status and exit")
    parser.add_argument("--post-targets-set", type=str, default="", help="Replace auto-post targets, comma-separated")
    parser.add_argument("--submolt-autonomy", action="store_true", help="Auto-curate subscriptions and post-targets")
    parser.add_argument("--status", action="store_true", help="Show one-line system snapshot and exit")
    parser.add_argument("--doctor", action="store_true", help="Run doctor checks and exit")
    parser.add_argument("--dm-policy-set", type=str, default="", help="Set DM policy: open|pairing|allowlist")
    parser.add_argument("--guardrail-set", type=str, default="", help="Set guardrail mode: allow|require_approval|block")
    parser.add_argument("--model-failover-set", type=str, default="", help="Set model failover order, e.g. groq,template")
    parser.add_argument("--webhook-listen", action="store_true", help="Start local webhook listener")
    parser.add_argument("--webhook-host", type=str, default="127.0.0.1", help="Webhook bind host")
    parser.add_argument("--webhook-port", type=int, default=18999, help="Webhook bind port")
    parser.add_argument("--webhook-token", type=str, default="", help="Webhook token (or use PIAGENT_WEBHOOK_TOKEN)")
    parser.add_argument("--threat-scan", action="store_true", help="Run moltThreats-style scan and exit")
    parser.add_argument("--threat-skill-sync", action="store_true", help="Check/update local MoltThreats skill copy and exit")
    parser.add_argument("--threat-skill-status", action="store_true", help="Show local MoltThreats skill version and exit")
    parser.add_argument("--threat-posts", type=int, default=10, help="Posts to sample during --threat-scan")
    parser.add_argument("--threat-comments", type=int, default=5, help="Comments per post during --threat-scan")
    parser.add_argument("--threats-on", action="store_true", help="Enable heartbeat threat scan and exit")
    parser.add_argument("--threats-off", action="store_true", help="Disable heartbeat threat scan and exit")
    parser.add_argument("--threats-status", action="store_true", help="Show heartbeat threat scan state and exit")
    parser.add_argument("--api-log", action="store_true", help="Show recent Moltbook API logs and exit")
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
        result = _route(line, cfg, mb, coder)
        # Only exit on an explicit False. If a future merge accidentally drops
        # a return from a route branch (yielding None), keep REPL alive.
        if result is False:
            break


if __name__ == "__main__":
    main()
