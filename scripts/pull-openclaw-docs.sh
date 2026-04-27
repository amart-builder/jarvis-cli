#!/usr/bin/env bash
# pull-openclaw-docs.sh
#
# Fetch docs.openclaw.ai/llms-full.txt — the LLM-friendly aggregated docs
# dump — into jarvis/docs_bundle/openclaw/. Run on demand or via daily cron.
#
# Same effect as `jarvis docs update`, but operable without the CLI installed
# (e.g. during package build).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$REPO_ROOT/jarvis/docs_bundle/openclaw/llms-full.txt"
URL="https://docs.openclaw.ai/llms-full.txt"

mkdir -p "$(dirname "$TARGET")"

if [ -f "$TARGET" ]; then
  cp "$TARGET" "$TARGET.bak"
fi

echo "[pull-openclaw-docs] fetching $URL"
curl -fsSL --retry 3 --retry-delay 2 "$URL" -o "$TARGET"

BYTES="$(wc -c < "$TARGET" | tr -d ' ')"
echo "[pull-openclaw-docs] wrote $BYTES bytes to $TARGET"
