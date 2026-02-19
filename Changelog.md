# Changelog

All notable changes to PiAgent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `post-debug` command and `--post-debug` CLI flag for post preflight diagnostics (auth presence, target submolt, payload keys, latest write-block reason).
- Submolt autonomy workflow (`submolt-autonomy` + `--submolt-autonomy`) to score communities, enforce max 10 subscriptions, and rotate top-ranked submolts into post targets
- Local webhook trigger mode added (`webhook-listen` + `--webhook-listen`)
- Model failover controls added (`model-failover` + `--model-failover-set`)
- Guardrail policy controls added (`guardrail` + `--guardrail-set`)
- Doctor diagnostics command added (`doctor` + `--doctor`)
- DM pairing/allowlist policy controls added (`dm-policy` + `--dm-policy-set`)
- Versioning policy documented: patch bump for minor fixes (e.g. `0.3.0-rc1` → next patch), minor bump for larger feature rollups (`0.2.x` → `0.3.0`)
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
- `suspension-check` now performs a safe write-capability probe and reports `READ_ACTIVE / WRITE_BLOCKED[_UNTIL ...]` states when reads succeed but writes are forbidden.
- `mb submolts` now prints a clean name list; `mb submolt` without args aliases to the same list output
- `agent.py` command routing refactored into a command table for clearer extension
- Freeform intent routing now uses confidence scoring and ambiguity handling
- `post-targets` replacement resets rotation to the first listed target
- Version updated to `0.3.0-rc1`
- Optional heartbeat threat scanning can now be enabled in config and reported in status
- MoltThreats skill metadata is now tracked/refreshable from hosted `skill.md` into runtime cache
- `suspension-check` now records API response bodies/hints and surfaces verification-challenge clues with API log path

### Fixed
- Updated `scripts/get_clean_files.sh` to default to `main` (to avoid drift against `origin/main`) with automatic fallback to known-good ref `5662cc8` when verification fails.
- Added `scripts/get_clean_files.sh` and README recovery instructions for restoring a clean `agent.py` (and core files) from GitHub when local merges are corrupted.
- Hardened `scripts/get_clean_files.sh` to download into a temp dir, verify syntax before replacing local files, and use verified download staging before replace; `main` is default with fallback to known-good `5662cc8` when needed.
- Added `scripts/verify_repo_health.sh` to catch unresolved merge markers and run syntax checks before runtime, and wired `get_clean_files.sh` to run it automatically.
- REPL loop now exits only on an explicit `False` from `_route()` so accidental missing returns during merges do not terminate the session after a command.
- Added a defensive `mode = cfg.guardrail_mode` alias in `_route()` to prevent merge-conflict regressions from crashing help/REPL command routing with `NameError`.
- Replaced box-drawing banner glyphs with ASCII output in `_print_banner()` to avoid merge-related syntax breakage from stray unicode banner lines.
- Guardrail checks in non-interactive dispatch now reference `cfg.guardrail_mode` directly to prevent merge-related `NameError` regressions from stale local variables.
- Fixed a non-interactive startup crash where a guardrail `mode` reference could raise `NameError` during CLI action dispatch.
- DM pairing check now normalizes multiple Moltbook DM response shapes and prints a response preview + API log path when format is unknown.
- Post payload field updated to `submolt_name` (replacing legacy `submolt`) to match Moltbook API validation and avoid 400 errors on `post-now`/`mb post`.
- Added compatibility mapping in the internal API helper so legacy payloads are normalized to `submolt_name`.
- Prevented a startup `NameError` risk by making `_print_banner()` explicitly print-and-return only, avoiding accidental execution of non-banner logic if edits are misplaced.

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
- Updated `scripts/get_clean_files.sh` to default to `main` (to avoid drift against `origin/main`) with automatic fallback to known-good ref `5662cc8` when verification fails.
- Added `scripts/get_clean_files.sh` and README recovery instructions for restoring a clean `agent.py` (and core files) from GitHub when local merges are corrupted.
- Hardened `scripts/get_clean_files.sh` to download into a temp dir, verify syntax before replacing local files, and use verified download staging before replace; `main` is default with fallback to known-good `5662cc8` when needed.
- Added `scripts/verify_repo_health.sh` to catch unresolved merge markers and run syntax checks before runtime, and wired `get_clean_files.sh` to run it automatically.
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

[Unreleased]: https://github.com/lgomez22/PiAgent/compare/v0.3.0-rc1...HEAD
[0.3.0-rc1]: https://github.com/lgomez22/PiAgent/compare/v0.2.0...v0.3.0-rc1
[0.2.0]: https://github.com/lgomez22/PiAgent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lgomez22/PiAgent/releases/tag/v0.1.0
