"""
config.py — Persistent configuration & credential management.

Stores everything under ~/.config/piagent/ so it survives restarts
and is out of the project directory (good practice on shared machines).

Files:
    credentials.json   { "api_key": "moltbook_xxx", "agent_name": "..." }
    heartbeat.json     { "last_check": "<ISO timestamp or null>" }
"""

import json, os, time
from pathlib import Path
from typing import Optional

_CONFIG_DIR = Path.home() / ".config" / "piagent"


class Config:
    def __init__(self):
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._cred_path = _CONFIG_DIR / "credentials.json"
        self._hb_path   = _CONFIG_DIR / "heartbeat.json"
        self._creds     = self._load(_self_path=self._cred_path)
        self._hb        = self._load(_self_path=self._hb_path)

    # ── generic load / save ──────────────────────────────────────────
    @staticmethod
    def _load(_self_path: Path) -> dict:
        try:
            return json.loads(_self_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _save(path: Path, data: dict):
        path.write_text(json.dumps(data, indent=2))

    # ── credentials ──────────────────────────────────────────────────
    @property
    def api_key(self) -> Optional[str]:
        return self._creds.get("api_key")

    @api_key.setter
    def api_key(self, value: str):
        self._creds["api_key"] = value
        self._save(self._cred_path, self._creds)

    @property
    def agent_name(self) -> Optional[str]:
        return self._creds.get("agent_name")

    @agent_name.setter
    def agent_name(self, value: str):
        self._creds["agent_name"] = value
        self._save(self._cred_path, self._creds)

    @property
    def groq_api_key(self) -> Optional[str]:
        """Groq API key for LLM-powered responses."""
        return self._creds.get("groq_api_key")

    @groq_api_key.setter
    def groq_api_key(self, value: str):
        self._creds["groq_api_key"] = value
        self._save(self._cred_path, self._creds)

    def save_credentials(self, api_key: str, agent_name: str, groq_key: Optional[str] = None):
        self._creds = {"api_key": api_key, "agent_name": agent_name}
        if groq_key:
            self._creds["groq_api_key"] = groq_key
        self._save(self._cred_path, self._creds)
        print(f"[Config] Credentials saved to {self._cred_path}")

    # ── heartbeat state ──────────────────────────────────────────────
    @property
    def last_heartbeat(self) -> Optional[float]:
        """Epoch timestamp of last heartbeat, or None."""
        val = self._hb.get("last_check")
        return float(val) if val is not None else None

    def touch_heartbeat(self):
        self._hb["last_check"] = time.time()
        self._save(self._hb_path, self._hb)

    def heartbeat_due(self, interval_hours: float = 4.0) -> bool:
        """True if ≥ interval_hours since last heartbeat (or never run)."""
        if self.last_heartbeat is None:
            return True
        return (time.time() - self.last_heartbeat) >= interval_hours * 3600

    # ── engagement settings ──────────────────────────────────────────
    @property
    def auto_engage(self) -> bool:
        """Whether to auto-comment and upvote posts during heartbeat."""
        return self._hb.get("auto_engage", True)  # Default: enabled

    @auto_engage.setter
    def auto_engage(self, value: bool):
        self._hb["auto_engage"] = value
        self._save(self._hb_path, self._hb)

    @property
    def last_post_time(self) -> Optional[float]:
        """Epoch timestamp of last auto-post, or None. For display only."""
        val = self._hb.get("last_post")
        return float(val) if val is not None else None

    def touch_last_post(self):
        """Record that we just made a post (for display/tracking only)."""
        self._hb["last_post"] = time.time()
        self._save(self._hb_path, self._hb)

    # ── dm safety policy ─────────────────────────────────────────────
    @property
    def dm_policy(self) -> str:
        """DM policy: open | pairing | allowlist."""
        val = str(self._hb.get("dm_policy", "open")).lower()
        return val if val in ("open", "pairing", "allowlist") else "open"

    @dm_policy.setter
    def dm_policy(self, value: str):
        val = str(value).lower().strip()
        self._hb["dm_policy"] = val if val in ("open", "pairing", "allowlist") else "open"
        self._save(self._hb_path, self._hb)

    @property
    def dm_allowlist(self) -> list:
        """Approved DM identities for pairing/allowlist mode."""
        vals = self._hb.get("dm_allowlist", [])
        if isinstance(vals, list):
            cleaned = [str(v).strip() for v in vals if str(v).strip()]
            return sorted(set(cleaned))
        return []

    @dm_allowlist.setter
    def dm_allowlist(self, values: list):
        cleaned = sorted(set(str(v).strip() for v in values if str(v).strip()))
        self._hb["dm_allowlist"] = cleaned
        self._save(self._hb_path, self._hb)

    # ── guardrails and failover ──────────────────────────────────────
    @property
    def guardrail_mode(self) -> str:
        """Action guardrail mode: allow | require_approval | block."""
        val = str(self._hb.get("guardrail_mode", "allow")).lower()
        return val if val in ("allow", "require_approval", "block") else "allow"

    @guardrail_mode.setter
    def guardrail_mode(self, value: str):
        val = str(value).lower().strip()
        self._hb["guardrail_mode"] = val if val in ("allow", "require_approval", "block") else "allow"
        self._save(self._hb_path, self._hb)

    @property
    def model_failover_order(self) -> list:
        """Ordered failover providers (currently supports groq/template)."""
        vals = self._hb.get("model_failover_order", ["groq", "template"])
        if not isinstance(vals, list):
            return ["groq", "template"]
        cleaned = [str(v).strip().lower() for v in vals if str(v).strip()]
        allowed = [v for v in cleaned if v in ("groq", "template")]
        if not allowed:
            return ["groq", "template"]
        # preserve order and uniqueness
        out = []
        for item in allowed:
            if item not in out:
                out.append(item)
        return out

    @model_failover_order.setter
    def model_failover_order(self, values: list):
        cleaned = []
        for value in values:
            val = str(value).strip().lower()
            if val in ("groq", "template") and val not in cleaned:
                cleaned.append(val)
        self._hb["model_failover_order"] = cleaned if cleaned else ["groq", "template"]
        self._save(self._hb_path, self._hb)

    @property
    def threat_scan_enabled(self) -> bool:
        """Whether heartbeat should run moltThreats-style content scanning."""
        return self._hb.get("threat_scan_enabled", False)

    @threat_scan_enabled.setter
    def threat_scan_enabled(self, value: bool):
        self._hb["threat_scan_enabled"] = bool(value)
        self._save(self._hb_path, self._hb)

    # ── multi-submolt targeting ─────────────────────────────────────
    @property
    def post_submolts(self) -> list:
        """Ordered list of submolts to target for auto-posting."""
        submolts = self._hb.get("post_submolts", ["general"])
        if isinstance(submolts, list) and submolts:
            return [str(s).strip() for s in submolts if str(s).strip()]
        return ["general"]

    @post_submolts.setter
    def post_submolts(self, values: list):
        cleaned = [str(v).strip() for v in values if str(v).strip()]
        self._hb["post_submolts"] = cleaned if cleaned else ["general"]
        self._hb["post_submolt_index"] = 0
        self._save(self._hb_path, self._hb)

    @property
    def post_submolt_index(self) -> int:
        """Rotation index for auto-post submolts."""
        try:
            return int(self._hb.get("post_submolt_index", 0))
        except (TypeError, ValueError):
            return 0

    @post_submolt_index.setter
    def post_submolt_index(self, value: int):
        self._hb["post_submolt_index"] = max(int(value), 0)
        self._save(self._hb_path, self._hb)

    def current_post_submolt(self) -> str:
        """Return the current submolt without advancing the rotation."""
        targets = self.post_submolts
        index = self.post_submolt_index
        if not targets:
            return "general"
        return targets[index % len(targets)]

    def advance_post_submolt(self):
        """Advance the submolt rotation after a successful post."""
        targets = self.post_submolts
        if not targets:
            return
        self.post_submolt_index = (self.post_submolt_index + 1) % len(targets)
