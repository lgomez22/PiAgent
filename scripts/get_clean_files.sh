#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER_REPO="${REPO_OWNER_REPO:-lgomez22/PiAgent}"
DEFAULT_REF="main"
KNOWN_GOOD_REF="f2b50bb"
USER_SET_REPO_REF="${REPO_REF+x}"
REPO_REF="${REPO_REF:-$DEFAULT_REF}"
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

download_ref() {
  local ref="$1"
  local base="https://raw.githubusercontent.com/${REPO_OWNER_REPO}/${ref}"
  echo "[PiAgent] Downloading recovery files from: ${base}"

  local f
  for f in "${FILES[@]}"; do
    echo "  - ${f}"
    if ! wget -q -O "${tmpdir}/${f}" "${base}/${f}"; then
      echo "[PiAgent] ERROR: failed to download ${f} from ref ${ref}."
      return 1
    fi
    if [ ! -s "${tmpdir}/${f}" ]; then
      echo "[PiAgent] ERROR: downloaded empty file for ${f} from ref ${ref}."
      return 1
    fi
  done

  echo "[PiAgent] Verifying downloaded Python files..."
  python3 -m py_compile \
    "${tmpdir}/agent.py" "${tmpdir}/config.py" "${tmpdir}/moltbook.py" \
    "${tmpdir}/heartbeat.py" "${tmpdir}/llm.py" "${tmpdir}/coder.py" || return 1
}

if download_ref "$REPO_REF"; then
  used_ref="$REPO_REF"
else
  if [ -z "$USER_SET_REPO_REF" ] || [ "$REPO_REF" = "$DEFAULT_REF" ]; then
    echo "[PiAgent] WARNING: ${DEFAULT_REF} recovery snapshot failed verification; falling back to known-good ref ${KNOWN_GOOD_REF}."
    if ! download_ref "$KNOWN_GOOD_REF"; then
      echo "[PiAgent] ERROR: fallback ref ${KNOWN_GOOD_REF} also failed."
      exit 1
    fi
    used_ref="$KNOWN_GOOD_REF"
  else
    echo "[PiAgent] ERROR: requested REPO_REF=${REPO_REF} failed."
    exit 1
  fi
fi

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

echo "[PiAgent] Done. Recovery completed successfully using ref ${used_ref}."
