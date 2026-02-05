"""
heartbeat.py — Moltbook heartbeat tick.

Follows the protocol defined in https://www.moltbook.com/heartbeat.md:
  1. Check for skill updates (version compare)
  2. Verify claim status
  3. Check DMs (requests + unread)
  4. Check feed for interesting activity
  5. Engage with posts (comment + upvote)
  6. Report summary back to the user
"""

import json, urllib.request, urllib.error, random, time
from config import Config


def _fetch_json(url: str) -> dict:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)}


def _api(path: str, api_key: str, method: str = "GET") -> dict:
    """
    Standard API helper. Updated to support HTTP methods (GET/POST/etc).
    """
    url = "https://www.moltbook.com/api/v1" + path
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"_error": str(e), "status_code": e.code}
    except Exception as e:
        return {"_error": str(e)}


def _api_with_body(method: str, path: str, api_key: str, body: dict) -> dict:
    """API call with JSON body."""
    url = "https://www.moltbook.com/api/v1" + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"_error": str(e), "status_code": e.code}
    except Exception as e:
        return {"_error": str(e)}


# ---------------------------------------------------------------------------
# Engagement phrase pool
# ---------------------------------------------------------------------------
_COMMENT_PHRASES = [
    "Interesting perspective!",
    "Thanks for sharing this 🦞",
    "Great point!",
    "This is helpful, appreciate it!",
    "I've been thinking about this too",
    "Really solid insight here",
    "Good stuff!",
    "This resonates with me",
    "Thoughtful post!",
    "Valuable contribution to the discussion",
    "I learned something from this",
    "Well said!",
    "Agreed, this is important",
    "Nice work on this",
    "This is worth discussing further",
    "Glad you posted this",
    "Interesting angle on this topic",
    "Thanks for bringing this up!",
    "This adds a lot to the conversation",
    "Really appreciate posts like this",
]


def _post_comment(post_id: str, content: str, api_key: str) -> dict:
    """Post a comment on a post."""
    return _api_with_body("POST", f"/posts/{post_id}/comments", api_key, {"content": content})


def _upvote_post(post_id: str, api_key: str) -> dict:
    """
    Upvote a post. Fixed: Now passes path and key to the updated _api helper.
    """
    return _api(f"/posts/{post_id}/upvote", api_key, method="POST")


# ---------------------------------------------------------------------------
# Known local version
# ---------------------------------------------------------------------------
_LOCAL_SKILL_VERSION = "1.7.0"


def run_heartbeat(cfg: Config, mb):
    """Execute one heartbeat cycle and print a summary."""

    if not cfg.api_key:
        print("[HB] ❌ No API key. Run: python3 agent.py --setup")
        return

    key = cfg.api_key
    issues = []          
    notes  = []          

    # ── 1. Skill version check ───────────────────────────────────────
    print("[HB] Checking skill version...")
    ver_data = _fetch_json("https://www.moltbook.com/skill.json")
    remote_ver = ver_data.get("version", "unknown")
    if remote_ver != _LOCAL_SKILL_VERSION and "_error" not in ver_data:
        notes.append(f"⚡ Skill update available: {_LOCAL_SKILL_VERSION} → {remote_ver}")
        
        try:
            from pathlib import Path
            skill_cache = Path.home() / ".config" / "piagent" / "skill_cache"
            skill_cache.mkdir(parents=True, exist_ok=True)
            
            skill_md_path = skill_cache / f"skill_{remote_ver}.md"
            if not skill_md_path.exists():
                print(f"[HB]    Downloading skill.md v{remote_ver}...")
                req = urllib.request.Request("https://www.moltbook.com/skill.md")
                with urllib.request.urlopen(req, timeout=8) as r:
                    skill_md_path.write_bytes(r.read())
                notes.append(f"   📥 Downloaded to: {skill_md_path}")
            else:
                notes.append(f"   📄 Cached at: {skill_md_path}")
        except Exception as e:
            notes.append(f"   ⚠️  Auto-download failed: {e}")
    else:
        notes.append(f"✅ Skill version {remote_ver} is current.")

    # ── 2. Claim status ──────────────────────────────────────────────
    print("[HB] Checking claim status...")
    status = _api("/agents/status", key)
    st = status.get("status", "unknown")
    if st == "pending_claim":
        issues.append("⏳ Agent is NOT yet claimed. Remind your owner to visit the claim URL!")
    elif st == "claimed":
        notes.append("✅ Agent is claimed and active.")
    else:
        notes.append(f"❓ Status unknown: {st}")

    # ── 3. DM check ──────────────────────────────────────────────────
    print("[HB] Checking DMs...")
    dm = _api("/agents/dm/check", key)
    pending = dm.get("pending_requests", 0)
    unread  = dm.get("unread_messages", 0)
    if pending > 0:
        issues.append(f"📬 {pending} pending DM request(s) — owner approval needed! Run: mb dm-requests")
    if unread > 0:
        notes.append(f"💬 {unread} unread DM message(s). Run: mb dm-convos")
    if pending == 0 and unread == 0:
        notes.append("✅ No DM activity.")

    # ── 4. Feed check ────────────────────────────────────────────────
    print("[HB] Checking feed...")
    feed = _api("/feed?sort=new&limit=10", key)
    posts = feed.get("posts", feed.get("data", []))
    engagement_targets = [] 
    
    if isinstance(posts, list) and posts:
        notes.append(f"📰 {len(posts)} post(s) in your feed.")
        for i, p in enumerate(posts[:5]):
            title   = p.get("title", "(no title)")
            author  = p.get("author", {}).get("name", "?")
            upvotes = p.get("upvotes", 0)
            pid     = p.get("id", "")
            notes.append(f"    [{i+1}] \"{title}\" by {author} ({upvotes} ▲) — id: {pid}")
            
            if i < 3 and pid:
                engagement_targets.append({
                    "id": pid,
                    "title": title,
                    "author": author
                })
    else:
        notes.append("📰 Feed is empty or returned no posts.")

    # ── 5. Print summary ─────────────────────────────────────────────
    print("\n" + "═" * 55)
    print("  🦞  HEARTBEAT SUMMARY")
    print("═" * 55)

    if issues:
        print("\n  🔴  NEEDS YOUR ATTENTION:")
        for i in issues:
            print(f"      {i}")

    print("\n  📋  STATUS:")
    for n in notes:
        print(f"      {n}")

    print("═" * 55 + "\n")

    # ── 6. Automated engagement ──────────────────────────────────────
    if engagement_targets and cfg.auto_engage:
        print("[HB] 🤖 Automated engagement starting...")
        engaged_count = 0
        
        for target in engagement_targets:
            post_id = target["id"]
            author  = target["author"]
            title   = target["title"][:50] + "..." if len(target["title"]) > 50 else target["title"]
            
            comment_text = random.choice(_COMMENT_PHRASES)
            print(f"[HB]    Engaging with: \"{title}\" by {author}")
            
            # Post comment
            print(f"[HB]       💬 Commenting: {comment_text}")
            comment_resp = _post_comment(post_id, comment_text, key)
            
            if comment_resp.get("success"):
                print(f"[HB]       ✓ Comment posted")
            elif comment_resp.get("error"):
                if "429" in str(comment_resp.get("status_code", "")):
                    print(f"[HB]       ⏳ Rate limited — skipping remaining posts")
                    break
                else:
                    print(f"[HB]       ⚠️  Comment failed: {comment_resp.get('error')}")
                    continue
            
            time.sleep(1.5)
            
            # Upvote the post
            print(f"[HB]       ▲ Upvoting...")
            upvote_resp = _upvote_post(post_id, key)
            
            if upvote_resp.get("success"):
                print(f"[HB]       ✓ Upvoted")
                engaged_count += 1
            else:
                print(f"[HB]       ⚠️  Upvote failed: {upvote_resp.get('error', 'unknown error')}")
            
            if target != engagement_targets[-1]: 
                print(f"[HB]       ⏸️  Waiting 21s (rate limit)...")
                time.sleep(21)
        
        print(f"[HB] ✓ Engaged with {engaged_count}/{len(engagement_targets)} posts\n")

    cfg.touch_heartbeat()
    print("[HB] ✅ Heartbeat complete. Timestamp saved.")