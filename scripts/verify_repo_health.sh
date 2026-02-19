#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

FILES=(agent.py config.py heartbeat.py llm.py moltbook.py coder.py Readme.md Changelog.md SECURITY.md)
PATTERN='^(<<<<<<< .+|=======|>>>>>>> .+)$'

echo "[PiAgent] Checking for unresolved merge markers..."
if command -v rg >/dev/null 2>&1; then
  if rg -n "$PATTERN" -- "${FILES[@]}"; then
    echo "[PiAgent] ERROR: merge conflict markers detected. Resolve conflicts before running agent."
    exit 1
  fi
else
  echo "[PiAgent] NOTE: rg not found; using grep fallback for merge-marker scan."
  if grep -nE "$PATTERN" "${FILES[@]}"; then
    echo "[PiAgent] ERROR: merge conflict markers detected. Resolve conflicts before running agent."
    exit 1
  fi
fi

echo "[PiAgent] Running Python syntax checks..."
python3 -m py_compile agent.py config.py heartbeat.py moltbook.py llm.py coder.py

echo "[PiAgent] Health check passed."
