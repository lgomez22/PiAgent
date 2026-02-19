#!/usr/bin/env bash
set -euo pipefail

REPO_RAW_BASE="${REPO_RAW_BASE:-https://raw.githubusercontent.com/lgomez22/PiAgent/main}"
FILES=(
  agent.py
  config.py
  moltbook.py
  heartbeat.py
  llm.py
  coder.py
  Readme.md
  Changelog.md
  SECURITY.md
  .gitignore
)

echo "[PiAgent] Downloading clean files from: ${REPO_RAW_BASE}"
for f in "${FILES[@]}"; do
  echo "  - ${f}"
  wget -q -O "${f}" "${REPO_RAW_BASE}/${f}"
done

echo "[PiAgent] Verifying syntax..."
python3 -m py_compile agent.py config.py moltbook.py heartbeat.py llm.py coder.py

echo "[PiAgent] Done."
