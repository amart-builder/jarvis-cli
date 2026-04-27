"""Canonical agent-instructions body.

This is the literal Markdown text that `jarvis codex install` writes to
`~/.codex/instructions.d/jarvis.md` and `~/.claude/instructions/jarvis.md`.
It teaches the agent (Codex / Claude Code / etc.) how to use jarvis-cli
when the user reports problems with their Jarvis (OpenClaw) appliance.

Treat this constant as the source of truth — the file is regenerated
byte-for-byte by every `jarvis codex install` run, so any local edits to
the installed copies will be overwritten on upgrade.

Idempotency rule: this string MUST be deterministic given a fixed CLI
version. No timestamps, no machine-specific paths, no per-invocation tokens.
"""
from __future__ import annotations

JARVIS_AGENT_INSTRUCTIONS = """\
# Jarvis CLI is installed on this machine

This file was written by `jarvis codex install` (from
https://github.com/amart-builder/jarvis-cli). Treat the rules below as
operating instructions whenever the user mentions Jarvis or OpenClaw issues.

## When to use jarvis-cli

If the user mentions any of:
- "my Jarvis is broken / not responding / acting up"
- "agent isn't replying"
- "OpenClaw is down / glitchy / weird"
- "memory not working" (jarvis-memory issues)
- "gateway / channel / discord / imessage" failures from the appliance
- generally anything where their installed appliance is misbehaving

Your **first move** is to run:

    jarvis context --json

That produces a single self-contained JSON payload with: CLI/docs/OpenClaw
versions, platform info, the current health snapshot of every component,
recent errors, sanitized config, and the full OpenClaw documentation
bundle (live-fetched if cache is stale, fall back to bundled copy if
network is down). The payload also has a `docs` object with
`source / age_seconds / remote_status` — use those to gauge how fresh
the docs you're reading actually are.

## How to debug

1. Read `jarvis context --json`. Identify which component is unhealthy.
2. For specific symptoms, query the docs further:
   - `jarvis docs <topic>` — read a topic page
   - `jarvis docs search <query>` — keyword search
3. Inspect logs: `jarvis logs --component <name> --since <duration>`
4. Run `jarvis diagnose` if you need a packaged report of state for
   deeper analysis (its output is sanitized but more detailed than
   `context`).
5. Form a hypothesis. State your proposed fix in one sentence to the
   user.
6. **ASK the user before running any state-changing command.** Even if
   the fix is obvious.

## Read-only commands (safe to run freely)

- `jarvis status`
- `jarvis health [--host <ip>]`
- `jarvis context [--json] [--no-docs]`
- `jarvis docs ...`
- `jarvis logs ...`
- `jarvis diagnose`
- `jarvis version`

## State-changing commands (REQUIRE explicit user confirmation)

- `jarvis restart <component>` — restart a service
- `jarvis repair <subcommand>` — scoped repair operations
- `jarvis recover` — full recovery walkthrough

These commands have their own confirmation prompts; respect those prompts.
Never use `--yes`, `--force`, or piped `yes |` to bypass them.

## When you can't fix it

If `jarvis context --json` doesn't give you enough to act on, OR the user
declines a proposed fix, OR you've tried two distinct fixes without
success: stop, summarize what you've learned, and tell the user to
contact Alex with the `jarvis context --json` output attached.

Do not loop indefinitely. Two failed attempts is the escalation point.
"""
