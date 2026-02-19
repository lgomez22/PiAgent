#!/usr/bin/env bash
set -euo pipefail

# Default to a known-good PiAgent commit if upstream main is temporarily broken.
REPO_OWNER_REPO="${REPO_OWNER_REPO:-lgomez22/PiAgent}"
REPO_REF="${REPO_REF:-5662cc8}"
REPO_RAW_BASE="${REPO_RAW_BASE:-https://raw.githubusercontent.com/${REPO_OWNER_REPO}/${REPO_REF}}"
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

tmpdir="$(mktemp -d)"
cleanup() { rm -rf "$tmpdir"; }
trap cleanup EXIT

echo "[PiAgent] Downloading recovery files from: ${REPO_RAW_BASE}"
for f in "${FILES[@]}"; do
  echo "  - ${f}"
  wget -q -O "${tmpdir}/${f}" "${REPO_RAW_BASE}/${f}"
done

echo "[PiAgent] Verifying downloaded Python files..."
python3 -m py_compile \
  "${tmpdir}/agent.py" "${tmpdir}/config.py" "${tmpdir}/moltbook.py" \
  "${tmpdir}/heartbeat.py" "${tmpdir}/llm.py" "${tmpdir}/coder.py"

echo "[PiAgent] Applying files to working directory..."
for f in "${FILES[@]}"; do
  cp "${tmpdir}/${f}" "${f}"
done

echo "[PiAgent] Verifying checkout health..."
if [ -x "scripts/verify_repo_health.sh" ]; then
  bash scripts/verify_repo_health.sh
else
  python3 -m py_compile agent.py config.py moltbook.py heartbeat.py llm.py coder.py
fi

echo "[PiAgent] Done. Recovery completed successfully."
