#!/usr/bin/env bash
# build-docs-bundle.sh
#
# Refresh jarvis/docs_bundle/ from the canonical sources before packaging.
# - HARDENING.md, ORCHESTRATOR.md, workers/*.md come from astack/Setup prompts/
# - openclaw/llms-full.txt comes from docs.openclaw.ai (fetched by pull-openclaw-docs.sh)
# - lessons-learned.md is hand-maintained inside the bundle
#
# Usage:
#   ./scripts/build-docs-bundle.sh
#   ./scripts/build-docs-bundle.sh --pull-openclaw   # also re-pull upstream

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE="$REPO_ROOT/jarvis/docs_bundle"
ASTACK_PROMPTS="$REPO_ROOT/../Setup prompts"

if [ ! -d "$ASTACK_PROMPTS" ]; then
  echo "FAIL: expected canonical sources at $ASTACK_PROMPTS"
  exit 1
fi

echo "[build-docs-bundle] copying canonical Setup prompts → $BUNDLE"
cp "$ASTACK_PROMPTS/HARDENING.md" "$BUNDLE/HARDENING.md"
cp "$ASTACK_PROMPTS/ORCHESTRATOR.md" "$BUNDLE/ORCHESTRATOR.md"

mkdir -p "$BUNDLE/workers"
rm -f "$BUNDLE/workers/"*.md
cp "$ASTACK_PROMPTS/workers/"*.md "$BUNDLE/workers/"

if [ "${1:-}" = "--pull-openclaw" ]; then
  "$REPO_ROOT/scripts/pull-openclaw-docs.sh"
fi

# Stamp the docs version in jarvis/version.py so package builds carry it.
TODAY="$(date -u +%Y-%m-%d)"
python3 - <<PY
from pathlib import Path
import re
p = Path("$REPO_ROOT/jarvis/version.py")
text = p.read_text()
text = re.sub(r'DOCS_VERSION = "[^"]+"', f'DOCS_VERSION = "$TODAY"', text)
p.write_text(text)
print(f"[build-docs-bundle] stamped DOCS_VERSION = $TODAY in jarvis/version.py")
PY

echo "[build-docs-bundle] done"
