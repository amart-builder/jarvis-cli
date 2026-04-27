"""Canonical agent-instructions body.

This is the literal Markdown text that `jarvis codex install` injects into
`~/.codex/AGENTS.md` (Codex CLI's global instructions file) and
`~/.claude/CLAUDE.md` (Claude Code's global instructions file).

The text is wrapped between `JARVIS_BLOCK_BEGIN` / `JARVIS_BLOCK_END`
markers so the install command can append-or-replace just our block
without overwriting any other content the user has in those files.

Treat the marker block as the source of truth — every `jarvis codex install`
run rewrites just the block, byte-identically given a fixed CLI version,
preserving everything outside the markers.

Idempotency rule: the body MUST be deterministic given a fixed CLI version.
No timestamps, no machine-specific paths, no per-invocation tokens.
"""
from __future__ import annotations

# Stable markers for find/replace inside an existing instructions file.
# DO NOT change these once shipped — older installs would orphan the old block.
JARVIS_BLOCK_BEGIN = "<!-- BEGIN jarvis-cli (auto-managed by `jarvis codex install`) -->"
JARVIS_BLOCK_END = "<!-- END jarvis-cli -->"

JARVIS_AGENT_INSTRUCTIONS_BODY = """\
## Jarvis CLI is installed on this machine

This block was injected by `jarvis codex install` (from
https://github.com/amart-builder/jarvis-cli). Treat the rules below as
operating instructions whenever the user mentions Jarvis or OpenClaw issues.

## Where jarvis-cli runs (laptop vs. remote appliance)

The user's OpenClaw appliance almost never runs on the laptop you're
talking to them on — it lives on a separate machine (a Mac Mini in
their apartment, a NUC, or a VPS). `jarvis-cli` on the laptop acts as a
**thin client**: every command transparently SSHes to the configured
remote host and prints its output here.

Dispatch is gated by `~/.jarvis/setup.toml`:
- **`mode = "remote"`** → jarvis SSHes the same command to `user@host` and
  exits with the remote's exit code. Stdout/stderr stream straight back.
- **File missing or `mode = "local"`** → jarvis runs locally (assumes the
  appliance is on this machine, which it usually isn't).

**Always check setup.toml first.** If `~/.jarvis/setup.toml` does NOT
exist, the user has not run onboarding yet — every other jarvis command
will hit the wrong machine. Your first move is to tell the user to run:

    jarvis onboard

**You, the agent, MUST NOT run `jarvis onboard` yourself.** It's
interactive by design and will hang if you spawn it as a subprocess.
Tell the user to type it in their own terminal; you watch the output
they paste back and translate any prompts. Do not pipe stdin or use
`expect`-style bypasses.

The walkthrough auto-detects Tailscale peers, verifies SSH reachability,
installs jarvis-cli on the remote if it's missing, and writes setup.toml.
After it succeeds, every subsequent `jarvis <cmd>` works transparently.

**If setup.toml exists with `mode = "local"` AND the user is reporting
an *appliance* problem,** the file is stale (left over from earlier
local-only debugging). Tell the user to run `jarvis onboard --reset` to
re-onboard to remote mode. Otherwise jarvis will query the laptop, not
the appliance, and produce misleading "everything's fine" output.

## When to use jarvis-cli

If the user mentions any of:
- "my Jarvis is broken / not responding / acting up"
- "agent isn't replying"
- "OpenClaw is down / glitchy / weird"
- "memory not working" (jarvis-memory issues)
- "gateway / channel / discord / imessage" failures from the appliance
- generally anything where their installed appliance is misbehaving

Your **first move** (assuming setup.toml exists — see above) is to run:

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
   - `jarvis docs list` — see what topics are available
   - `jarvis docs show <topic>` — read a specific topic
   - `jarvis docs search <query>` — full-text search the docs bundle
3. Inspect logs: `jarvis logs <component> -n <lines>` (add `-f` to follow)
4. Run `jarvis diagnose` if you need a packaged report of state for
   deeper analysis (its output is sanitized but more detailed than
   `context`).
5. Form a hypothesis. State your proposed fix in one sentence to the
   user.
6. **ASK the user before running any state-changing command.** Even if
   the fix is obvious.

### Worked example

User: *"memory layer's been giving me 'connection refused' for the
last hour."*

1. Run `jarvis context --json`. See `health.memory.status = "down"`
   and a "connection refused" line under `errors`.
2. Run `jarvis logs memory -n 50` to see recent error lines from the
   memory component directly.
3. Tell the user: *"Your memory backend is down (recent logs show
   <quote one line>). My proposed fix is `jarvis restart memory`.
   Want me to run that?"*
4. On user yes → run `jarvis restart memory`. Re-run `jarvis context
   --json` to confirm `health.memory.status = "ok"`.
5. If still down after one retry → stop. Follow "When you can't fix
   it" below.

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
- `jarvis restart --all` — restart everything (built-in `[y/N]` prompt)
- `jarvis repair <subcommand>` — scoped repair operations (built-in prompt)
- `jarvis recover` — full recovery walkthrough (built-in prompt)

`restart --all`, `repair`, and `recover` have built-in `[y/N]` prompts; respect them. Single-component `restart <component>` does NOT prompt — that's why **YOU must ask the user first** before running ANY of these commands. Never use `--yes`, `--force`, or piped `yes |` to bypass a prompt.

## When you can't fix it

If `jarvis context --json` doesn't give you enough to act on, OR the user
declines a proposed fix, OR you've tried two distinct fixes without
success: stop, summarize what you've learned, and tell the user to
share the `jarvis context --json` output with whoever set up their
Jarvis appliance, or open an issue at
https://github.com/amart-builder/jarvis-cli/issues.

Do not loop indefinitely. Two failed attempts is the escalation point.
"""


def render_block() -> str:
    """Return the full marker-wrapped block to inject into a target file.

    Format:
        <BEGIN-marker>\\n
        \\n
        <body>\\n
        \\n
        <END-marker>\\n

    Always ends with a single trailing newline so the file has a clean line
    ending after our block.
    """
    return f"{JARVIS_BLOCK_BEGIN}\n\n{JARVIS_AGENT_INSTRUCTIONS_BODY}\n\n{JARVIS_BLOCK_END}\n"


def upsert_block(existing: str | None) -> str:
    """Inject or refresh our marker block in a host file's content.

    - `existing is None` (file doesn't exist) → return just our block.
    - existing has our markers → replace content between BEGIN..END.
    - existing has no markers → append our block, separated by blank line.

    Pure function — no I/O. The caller writes the result to disk atomically.
    """
    block = render_block()

    if existing is None or existing == "":
        return block

    begin_idx = existing.find(JARVIS_BLOCK_BEGIN)
    end_marker_pos = existing.find(JARVIS_BLOCK_END)

    if begin_idx >= 0 and end_marker_pos >= 0 and end_marker_pos > begin_idx:
        # Replace content between markers (inclusive of both markers).
        end_marker_close = end_marker_pos + len(JARVIS_BLOCK_END)
        # Consume an immediately-following newline so we don't accumulate them
        # across upserts.
        if end_marker_close < len(existing) and existing[end_marker_close] == "\n":
            end_marker_close += 1
        return existing[:begin_idx] + block + existing[end_marker_close:]

    # No markers present — append at end with a sensible separator.
    if existing.endswith("\n\n"):
        sep = ""
    elif existing.endswith("\n"):
        sep = "\n"
    else:
        sep = "\n\n"
    return existing + sep + block
