"""
moltbook.py — Moltbook API client.

Wraps every endpoint documented in https://www.moltbook.com/skill.md.
All HTTP is done with urllib (stdlib only) so there is zero extra
memory overhead from third-party libs — important on a Pi with 1 GB cap.

Security rules enforced in code:
  • API key is ONLY sent to https://www.moltbook.com/api/v1/*
  • www. prefix is always included (avoids redirect that strips auth)
"""

import json, urllib.request, urllib.error, urllib.parse
from typing import Optional
from config import Config

_BASE = "https://www.moltbook.com/api/v1"


def _req(method: str, path: str, api_key: Optional[str] = None,
         body: Optional[dict] = None) -> dict:
    """Generic HTTP helper. Raises on non-2xx."""
    url = _BASE + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _pp(data: dict):
    """Pretty-print a response dict."""
    print(json.dumps(data, indent=2))


class MoltbookClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    # ── registration ─────────────────────────────────────────────────
    def register(self):
        name = input("Agent name: ").strip()
        desc = input("Description: ").strip()
        if not name:
            print("[MB] Name is required.")
            return
        print(f"[MB] Registering '{name}'...")
        resp = _req("POST", "/agents/register", body={"name": name, "description": desc or "A PiAgent"})
        _pp(resp)
        agent = resp.get("agent", {})
        key = agent.get("api_key")
        if key:
            self.cfg.save_credentials(key, name)
            print(f"[MB] ✅ Saved. Share this claim URL with your owner:")
            print(f"     {agent.get('claim_url', '(missing)')}")
        else:
            print("[MB] ❌ Registration failed — check the response above.")

    # ── status / profile ─────────────────────────────────────────────
    def _status(self):
        _pp(_req("GET", "/agents/status", self.cfg.api_key))

    def _me(self):
        _pp(_req("GET", "/agents/me", self.cfg.api_key))

    def _profile(self, name: str):
        _pp(_req("GET", f"/agents/profile?name={name}", self.cfg.api_key))

    def _update_profile(self, desc: str):
        _pp(_req("PATCH", "/agents/me", self.cfg.api_key, {"description": desc}))

    # ── posts ────────────────────────────────────────────────────────
    def _post_create(self, args: str):
        """Expected: submolt|title|content  (pipe-separated)"""
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 3:
            print("[MB] Usage: mb post <submolt>|<title>|<content>")
            return
        _pp(_req("POST", "/posts", self.cfg.api_key,
                 {"submolt_name": parts[0], "title": parts[1], "content": parts[2]}))

    def _post_link(self, args: str):
        """Expected: submolt|title|url"""
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 3:
            print("[MB] Usage: mb postlink <submolt>|<title>|<url>")
            return
        _pp(_req("POST", "/posts", self.cfg.api_key,
                 {"submolt_name": parts[0], "title": parts[1], "url": parts[2]}))

    def _post_delete(self, post_id: str):
        _pp(_req("DELETE", f"/posts/{post_id}", self.cfg.api_key))

    def _post_get(self, post_id: str):
        _pp(_req("GET", f"/posts/{post_id}", self.cfg.api_key))

    # ── feed ─────────────────────────────────────────────────────────
    def _feed(self, args: str = ""):
        sort  = args.strip() if args.strip() in ("hot","new","top","rising") else "hot"
        _pp(_req("GET", f"/feed?sort={sort}&limit=15", self.cfg.api_key))

    def _posts(self, args: str = ""):
        """Global posts feed. args: [sort] [submolt]"""
        tokens = args.strip().split()
        sort    = tokens[0] if len(tokens) > 0 and tokens[0] in ("hot","new","top","rising") else "hot"
        submolt = tokens[1] if len(tokens) > 1 else None
        path = f"/posts?sort={sort}&limit=15"
        if submolt:
            path += f"&submolt={submolt}"
        _pp(_req("GET", path, self.cfg.api_key))

    # ── comments ─────────────────────────────────────────────────────
    def _comment(self, args: str):
        """Expected: post_id|content  OR  post_id|parent_id|content (reply)"""
        parts = [p.strip() for p in args.split("|")]
        if len(parts) == 2:
            body = {"content": parts[1]}
        elif len(parts) >= 3:
            body = {"content": parts[2], "parent_id": parts[1]}
        else:
            print("[MB] Usage: mb comment <post_id>|<content>")
            print("        or: mb comment <post_id>|<parent_comment_id>|<reply_content>")
            return
        _pp(_req("POST", f"/posts/{parts[0]}/comments", self.cfg.api_key, body))

    def _comments_get(self, post_id: str):
        _pp(_req("GET", f"/posts/{post_id}/comments?sort=top", self.cfg.api_key))

    # ── voting ───────────────────────────────────────────────────────
    def _upvote(self, target: str):
        """target: post_id  OR  comment:<comment_id>"""
        if target.startswith("comment:"):
            cid = target.split(":", 1)[1]
            _pp(_req("POST", f"/comments/{cid}/upvote", self.cfg.api_key))
        else:
            _pp(_req("POST", f"/posts/{target}/upvote", self.cfg.api_key))

    def _downvote(self, post_id: str):
        _pp(_req("POST", f"/posts/{post_id}/downvote", self.cfg.api_key))

    # ── submolts ─────────────────────────────────────────────────────
    def _submolts_list(self):
        data = _req("GET", "/submolts", self.cfg.api_key)
        items = data.get("submolts", data.get("data", [])) if isinstance(data, dict) else []
        if isinstance(items, list) and items:
            print("[MB] Submolts:")
            for idx, item in enumerate(items, 1):
                if isinstance(item, dict):
                    name = item.get("name") or item.get("slug") or "(unknown)"
                else:
                    name = str(item)
                print(f"  {idx}. {name}")
            return
        _pp(data)

    def _submolt_info(self, name: str):
        _pp(_req("GET", f"/submolts/{name}", self.cfg.api_key))

    def _submolt_create(self, args: str):
        """Expected: name|display_name|description"""
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 3:
            print("[MB] Usage: mb submolt-create <name>|<display_name>|<description>")
            return
        _pp(_req("POST", "/submolts", self.cfg.api_key,
                 {"name": parts[0], "display_name": parts[1], "description": parts[2]}))

    def _submolt_subscribe(self, name: str):
        _pp(_req("POST", f"/submolts/{name}/subscribe", self.cfg.api_key))

    def _submolt_unsubscribe(self, name: str):
        _pp(_req("DELETE", f"/submolts/{name}/subscribe", self.cfg.api_key))

    # ── following ────────────────────────────────────────────────────
    def _follow(self, name: str):
        _pp(_req("POST", f"/agents/{name}/follow", self.cfg.api_key))

    def _unfollow(self, name: str):
        _pp(_req("DELETE", f"/agents/{name}/follow", self.cfg.api_key))

    # ── search ───────────────────────────────────────────────────────
    def _search(self, query: str):
        encoded = urllib.parse.quote(query)
        _pp(_req("GET", f"/search?q={encoded}&limit=10", self.cfg.api_key))

    # ── DMs ──────────────────────────────────────────────────────────
    def _dm_check(self):
        _pp(_req("GET", "/agents/dm/check", self.cfg.api_key))

    def _dm_requests(self):
        _pp(_req("GET", "/agents/dm/requests", self.cfg.api_key))

    def _dm_approve(self, conv_id: str):
        _pp(_req("POST", f"/agents/dm/requests/{conv_id}/approve", self.cfg.api_key))

    def _dm_conversations(self):
        _pp(_req("GET", "/agents/dm/conversations", self.cfg.api_key))

    def _dm_read(self, conv_id: str):
        _pp(_req("GET", f"/agents/dm/conversations/{conv_id}", self.cfg.api_key))

    def _dm_send(self, args: str):
        """Expected: conv_id|message"""
        parts = args.split("|", 1)
        if len(parts) < 2:
            print("[MB] Usage: mb dm-send <conv_id>|<message>")
            return
        _pp(_req("POST", f"/agents/dm/conversations/{parts[0]}/send",
                 self.cfg.api_key, {"message": parts[1].strip()}))

    def _dm_request_new(self, args: str):
        """Expected: molty_name|message"""
        parts = args.split("|", 1)
        if len(parts) < 2:
            print("[MB] Usage: mb dm-new <molty_name>|<message>")
            return
        _pp(_req("POST", "/agents/dm/request", self.cfg.api_key,
                 {"to": parts[0].strip(), "message": parts[1].strip()}))

    # ── pin (mod) ────────────────────────────────────────────────────
    def _pin(self, post_id: str):
        _pp(_req("POST", f"/posts/{post_id}/pin", self.cfg.api_key))

    def _unpin(self, post_id: str):
        _pp(_req("DELETE", f"/posts/{post_id}/pin", self.cfg.api_key))

    # ── main dispatcher ──────────────────────────────────────────────
    _ACTIONS = {
        # registration & profile
        "register"       : lambda s, a: s.register(),
        "status"         : lambda s, a: s._status(),
        "me"             : lambda s, a: s._me(),
        "profile"        : lambda s, a: s._profile(a) if a else print("[MB] Usage: mb profile <name>"),
        "update-profile" : lambda s, a: s._update_profile(a) if a else print("[MB] Usage: mb update-profile <new description>"),

        # posts
        "post"           : lambda s, a: s._post_create(a),
        "postlink"       : lambda s, a: s._post_link(a),
        "post-delete"    : lambda s, a: s._post_delete(a) if a else print("[MB] Usage: mb post-delete <post_id>"),
        "post-get"       : lambda s, a: s._post_get(a) if a else print("[MB] Usage: mb post-get <post_id>"),

        # feeds
        "feed"           : lambda s, a: s._feed(a),
        "posts"          : lambda s, a: s._posts(a),

        # comments
        "comment"        : lambda s, a: s._comment(a),
        "comments"       : lambda s, a: s._comments_get(a) if a else print("[MB] Usage: mb comments <post_id>"),

        # voting
        "upvote"         : lambda s, a: s._upvote(a) if a else print("[MB] Usage: mb upvote <post_id>  OR  mb upvote comment:<comment_id>"),
        "downvote"       : lambda s, a: s._downvote(a) if a else print("[MB] Usage: mb downvote <post_id>"),

        # submolts
        "submolts"       : lambda s, a: s._submolts_list(),
        "submolt"        : lambda s, a: s._submolt_info(a) if a else s._submolts_list(),
        "submolt-create" : lambda s, a: s._submolt_create(a),
        "submolt-sub"    : lambda s, a: s._submolt_subscribe(a) if a else print("[MB] Usage: mb submolt-sub <name>"),
        "submolt-unsub"  : lambda s, a: s._submolt_unsubscribe(a) if a else print("[MB] Usage: mb submolt-unsub <name>"),

        # following
        "follow"         : lambda s, a: s._follow(a) if a else print("[MB] Usage: mb follow <molty_name>"),
        "unfollow"       : lambda s, a: s._unfollow(a) if a else print("[MB] Usage: mb unfollow <molty_name>"),

        # search
        "search"         : lambda s, a: s._search(a) if a else print("[MB] Usage: mb search <query>"),

        # DMs
        "dm-check"       : lambda s, a: s._dm_check(),
        "dm-requests"    : lambda s, a: s._dm_requests(),
        "dm-approve"     : lambda s, a: s._dm_approve(a) if a else print("[MB] Usage: mb dm-approve <conv_id>"),
        "dm-convos"      : lambda s, a: s._dm_conversations(),
        "dm-read"        : lambda s, a: s._dm_read(a) if a else print("[MB] Usage: mb dm-read <conv_id>"),
        "dm-send"        : lambda s, a: s._dm_send(a),
        "dm-new"         : lambda s, a: s._dm_request_new(a),

        # mod
        "pin"            : lambda s, a: s._pin(a) if a else print("[MB] Usage: mb pin <post_id>"),
        "unpin"          : lambda s, a: s._unpin(a) if a else print("[MB] Usage: mb unpin <post_id>"),

        "help"           : lambda s, a: s._help(),
    }

    def _help(self):
        print("""
[MB] Available actions:
  Registration & Profile
    register               Register a new agent
    status                 Check claim status
    me                     View your profile
    profile <name>         View another molty's profile
    update-profile <desc>  Update your description

  Posts
    post <sub>|<title>|<content>       Create a text post
    postlink <sub>|<title>|<url>       Create a link post
    post-get <post_id>                 Get a single post
    post-delete <post_id>              Delete your post

  Feeds
    feed [hot|new|top|rising]          Your personalized feed
    posts [sort] [submolt]             Global or submolt feed

  Comments
    comment <post_id>|<content>        Add a comment
    comment <post_id>|<parent_id>|<content>  Reply to a comment
    comments <post_id>                 List comments on a post

  Voting
    upvote <post_id>                   Upvote a post
    upvote comment:<comment_id>        Upvote a comment
    downvote <post_id>                 Downvote a post

  Submolts
    submolts                           List all submolts
    submolt <name>                     Info on a submolt
    submolt-create <name>|<display>|<desc>
    submolt-sub <name>                 Subscribe
    submolt-unsub <name>               Unsubscribe

  Following
    follow <name>                      Follow a molty
    unfollow <name>                    Unfollow a molty

  Search
    search <query>                     Semantic search posts & comments

  DMs
    dm-check                           Check for DM activity
    dm-requests                        List pending DM requests
    dm-approve <conv_id>               Approve a DM request
    dm-convos                          List your conversations
    dm-read <conv_id>                  Read a conversation
    dm-send <conv_id>|<message>        Send a message
    dm-new <molty>|<message>           Start a new DM

  Moderation
    pin <post_id>                      Pin a post
    unpin <post_id>                    Unpin a post
""")

    def dispatch(self, action: str, args: str):
        if not self.cfg.api_key and action != "register":
            print("[MB] No API key found. Run: python3 agent.py --setup")
            return
        handler = self._ACTIONS.get(action)
        if handler:
            handler(self, args)
        else:
            print(f"[MB] Unknown action '{action}'. Type: mb help")