"""Version stamps for the CLI and the embedded docs bundle.

The docs version moves independently from the CLI version because docs are
re-pulled from upstream OpenClaw periodically. `jarvis version` prints both.
"""
from __future__ import annotations

__version__ = "0.3.0"

# Docs bundle version — set by scripts/build-docs-bundle.sh at package build time.
# Format: ISO date of the latest pull from docs.openclaw.ai/llms-full.txt.
DOCS_VERSION = "2026-04-25"

# OpenClaw upstream version this docs snapshot was taken against.
# Updated by scripts/pull-openclaw-docs.sh.
OPENCLAW_VERSION = "2026.4.23"
