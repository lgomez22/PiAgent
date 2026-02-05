# Changelog

All notable changes to PiAgent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Multi-submolt auto-post targeting with rotation (`post-targets` command)

## [0.2.0] - 2025-02-04

### Added
- **LLM Integration**: Groq API support for intelligent responses
  - Context-aware comment generation (reads post title + content)
  - Original post creation based on feed activity
  - DM response framework (ready for future enablement)
  - Model: llama-3.3-70b-versatile (128k context)
  - Commands: `groq-setup`, `groq-status`
- **Enhanced Template System**: Smart keyword-based fallback
  - 7 topic categories (Pi, Python, Automation, Memory, AI, Community, Debugging)
  - 50+ unique template responses
  - Keyword detection on post title + content
  - Works perfectly without LLM
- **Version Command**: `version` to check current agent version
- **New Module**: `llm.py` - LLM client with graceful fallback

### Changed
- Comments are now contextual (LLM) or topic-matched (templates) instead of purely random
- Posts are now generated with feed context (LLM) or topic-rotated (templates)
- `post-now` command uses LLM when available
- Heartbeat shows LLM status: "🤖 LLM: Groq API connected" or "Template mode"
- Config now stores Groq API key alongside Moltbook credentials

### Fixed
- None (this is a feature release)

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
