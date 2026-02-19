#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

echo "[PiAgent] Checking for unresolved merge markers..."
if rg -n "^(<<<<<<< .+|=======|>>>>>>> .+)$" -- agent.py config.py heartbeat.py llm.py moltbook.py coder.py Readme.md Changelog.md SECURITY.md; then
  echo "[PiAgent] ERROR: merge conflict markers detected. Resolve conflicts before running agent."
  exit 1
fi

echo "[PiAgent] Running Python syntax checks..."
python3 -m py_compile agent.py config.py heartbeat.py moltbook.py llm.py coder.py

echo "[PiAgent] Health check passed."
