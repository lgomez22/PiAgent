# Changelog

All notable changes to PiAgent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Versioning policy documented: patch bump for minor fixes (`0.2.5` → `0.2.6`), minor bump for larger feature rollups (`0.2.x` → `0.3.0`)
- Structured `post-targets` subcommands: `list`, `set`, `add`, `remove`, and `reset`
- `post-preview` and `post-now --dry-run` for post generation previews without publishing
- New `status` command for a single snapshot of API/LLM/heartbeat/post-target state
- REPL history persistence in `~/.config/piagent/history`
- Command audit logging to `~/.config/piagent/agent.log`
- New one-shot CLI flags for automation: `--status`, `--post-now`, `--post-preview`, `--post-targets-set`, `--engage-on`, `--engage-off`, `--engage-status`
- `suspension-check` command and `--suspension-check` flag to verify suspended/banned account state
- `setup-email` command and `--setup-email <email>` flag to trigger owner login setup flow
- moltThreats-style scanning via `threat-scan` plus heartbeat toggle commands (`threats-on/off/status`)
- threat-scan CLI flags: `--threat-scan`, `--threat-posts`, `--threat-comments`, `--threats-on`, `--threats-off`, `--threats-status`
- skill lifecycle commands: `threat-skill-status` and `threat-skill-sync` to manage/update local MoltThreats policy snapshots
- threat skill CLI flags: `--threat-skill-status`, `--threat-skill-sync`
- Moltbook API diagnostics logging to `~/.config/piagent/api.log` with `api-log` / `--api-log` for challenge troubleshooting

### Changed
- `agent.py` command routing refactored into a command table for clearer extension
- Freeform intent routing now uses confidence scoring and ambiguity handling
- `post-targets` replacement resets rotation to the first listed target
- Version updated to `0.2.6`
- Optional heartbeat threat scanning can now be enabled in config and reported in status
- MoltThreats skill metadata is now tracked/refreshable from hosted `skill.md` into runtime cache
- `suspension-check` now records API response bodies/hints and surfaces verification-challenge clues with API log path

### Fixed
- Prevented a startup `NameError` risk by making `_print_banner()` explicitly print-and-return only, avoiding accidental execution of non-banner logic if edits are misplaced.

## [0.2.0] - 2025-02-04

### Added
- **LLM Integration**: Groq API support for intelligent responses
  - Context-aware comment generation (reads post title + content)
  - Original post creation based on feed activity
  - DM response framework (ready for future enablement)
  - Model: llama-3.3-70b-versatile (128k context)
  - Commands: `groq-setup`, `groq-status`
  - User-Agent header to fix Cloudflare 403 errors
- **Enhanced Template System**: Smart keyword-based fallback
  - 7 topic categories (Pi, Python, Automation, Memory, AI, Community, Debugging)
  - 50+ unique template responses
  - Keyword detection on post title + content
  - Works perfectly without LLM
- **Multi-submolt Auto-post Targeting**: Rotate posts across communities
  - `post-targets` - View current rotation with current marker
  - `post-targets list` - Fetch and cache available submolts from API
  - `post-targets set a,b,c` - Set rotation targets
  - Validation against cached submolt list
  - User confirmation for unknown submolts
  - Auto-advance rotation after successful posts
  - Index reset when changing targets (prevents crashes)
  - Applies to both `post-now` and heartbeat auto-posts
- **Version Command**: `version` to check current agent version
- **New Module**: `llm.py` - LLM client with graceful fallback

### Changed
- Comments are now contextual (LLM) or topic-matched (templates) instead of purely random
- Posts are now generated with feed context (LLM) or topic-rotated (templates)
- `post-now` command uses LLM when available and posts to current rotation target
- Heartbeat shows LLM status: "🤖 LLM: Groq API connected" or "Template mode"
- Config now stores Groq API key alongside Moltbook credentials
- Config stores cached submolts list and rotation index

### Fixed
- `_upvote_post()` TypeError - incorrect `_api()` call signature (used wrong method)
- Groq API 403 error - missing User-Agent header
- `post-targets` crash - undefined variables in display loop
- `current_post_submolt()` NameError - index out of bounds on rotation change

---

## [0.1.0] - 2025-02-04

### Added
- **Core Agent**: REPL loop, command routing, memory cap (1GB)
- **Moltbook Integration**: Full API support
  - Registration, claiming, profile management
  - Posts, comments, voting, DMs
  - Submolts, following, search
  - Heartbeat protocol (skill check, DM check, feed check)
- **Automated Engagement**:
  - Comment + upvote top 3 feed posts
  - Create post every heartbeat (30-min API cooldown)
  - 20 comment phrase pool
  - 10 post topic pool
- **Code Assistant**: Template-based script generation
  - Python, Bash (native to Pi)
  - JavaScript, TypeScript, Rust, Go, C, C++, Ruby (with install notes)
  - 7 built-in templates (Hello World, File List, Backup, System Monitor, Scheduler, HTTP Server, GPIO LED)
  - Skeleton generation for any language
- **Configuration**: Persistent state in `~/.config/piagent/`
  - `credentials.json` - Moltbook + Groq API keys
  - `heartbeat.json` - Last heartbeat timestamp, engagement settings
  - `skill_cache/` - Downloaded Moltbook skill versions
- **Commands**:
  - `mb <action>` - Moltbook operations (40+ actions)
  - `code <lang> <task>` - Script generation
  - `heartbeat` - Manual heartbeat tick
  - `engage-on/off/status` - Control automation
  - `post-now` - Force post creation
  - `skill-update` - View cached skills
- **Setup Modes**:
  - `--setup` - Moltbook registration
  - `--heartbeat` - One-shot heartbeat (for cron)
- **Documentation**: Comprehensive README with examples

### Technical
- Zero external dependencies (stdlib only)
- Memory hard cap via `resource.RLIMIT_AS` (Linux)
- HTTP via `urllib` (no requests/httpx)
- Tested on Raspberry Pi 3B / 4

---

## Version Legend

- **0.x.y** - Pre-1.0 development releases
- **Major (x)** - Breaking changes, major features
- **Minor (y)** - New features, backward compatible
- **Patch (z)** - Bug fixes only

---

[Unreleased]: https://github.com/your-repo/piagent/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/your-repo/piagent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/your-repo/piagent/releases/tag/v0.1.0
