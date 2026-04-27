# Jarvis CLI

```bash
curl -sSL https://raw.githubusercontent.com/amart-builder/jarvis-cli/main/scripts/install.sh | bash
```

**Paste that one line into Codex or Claude Code on the affected Mac and click Allow when macOS prompts.** The installer drops `jarvis` onto your PATH and registers it with the agent — within a couple of minutes the agent can run `jarvis context --json` against the local Jarvis appliance and debug the issue autonomously.

---

## What this is

`jarvis-cli` is the debugging surface for a [Jarvis](https://docs.openclaw.ai) appliance — the productized OpenClaw deployment shipped to clients on a Mac Mini. When the appliance misbehaves (gateway down, channels not delivering, memory layer offline, etc.), the operator's first move is no longer "Slack the vendor." It's:

1. Open Codex (or Claude Code) on the affected machine.
2. Paste the install line above. Click Allow.
3. Tell the agent: *"my Jarvis is broken — debug it."*

The agent reads the instructions file `jarvis-cli` installed under `~/.codex/instructions.d/jarvis.md` (or `~/.claude/instructions/jarvis.md`), runs `jarvis context --json` to get a complete sanitized snapshot of the appliance — versions, health of every component, recent errors, sanitized config, and the full live OpenClaw documentation bundle — and works the problem from there. State-changing commands (`restart`, `repair`, `recover`) are gated behind explicit confirmation prompts the agent must respect.

This package is **CLI-first by design**. The same `jarvis` binary works whether the agent is Codex, Claude Code, or a human at a terminal. There is no MCP server to maintain in parallel; every interaction is a regular shell command and is fully visible in the agent's transcript.

## Audience

- **Clients** running a Jarvis appliance who'd rather have their AI assistant debug a breakage than open a support ticket.
- **AI agents** (Codex, Claude Code, etc.) running on the affected machine — `jarvis context --json` is purpose-built to fit in an agent's context.

This is not a general-purpose system tool. Outside a Jarvis install most of the commands have nothing to talk to.

## Manual install

If you'd rather not pipe `curl` into `bash` — which is fair — install manually:

```bash
# Option 1: pipx from GitHub (matches what the script does)
pipx install git+https://github.com/amart-builder/jarvis-cli
jarvis codex install   # registers with Codex / Claude Code if either is installed

# Option 2: clone + pipx install local
git clone https://github.com/amart-builder/jarvis-cli.git
cd jarvis-cli
pipx install .
jarvis codex install
```

Both paths require [pipx](https://pipx.pypa.io/) and Python 3.11+.

## Commands

**Read-only** (safe for an agent to run without confirmation):

| Command | Purpose |
|---|---|
| `jarvis status` | Quick state summary of the appliance |
| `jarvis health [--host <ip>]` | Health check every component |
| `jarvis context [--json] [--no-docs]` | Full debug snapshot — versions, health, recent errors, sanitized config, bundled OpenClaw docs |
| `jarvis docs <topic>` / `jarvis docs search <query>` | Query the embedded OpenClaw documentation |
| `jarvis logs --component <name> --since <duration>` | Tail recent log lines for a component |
| `jarvis diagnose` | Generate a packaged diagnostic report |
| `jarvis version` | Print CLI / docs / OpenClaw versions |

**State-changing** (require explicit confirmation — agents must ask the user first):

| Command | Purpose |
|---|---|
| `jarvis restart <component>` | Restart a service |
| `jarvis repair <subcommand>` | Scoped repair operations |
| `jarvis recover` | Full recovery walkthrough |

**Agent integration:**

| Command | Purpose |
|---|---|
| `jarvis codex install` | Register jarvis-cli with Codex and/or Claude Code (writes an instructions file the agent auto-loads) |

## Routing to a remote appliance

By default `jarvis` talks to `127.0.0.1`. To point at a different host:

```bash
JARVIS_HOST=192.168.4.42 jarvis health
# or
jarvis health --host 192.168.4.42
```

`--host` overrides the env var; the env var overrides the default.

## Documentation freshness

`jarvis context --json` includes the full OpenClaw documentation bundle inline so an agent has the answer to "what does <component> do?" without an extra tool call. The docs are loaded in 3 tiers:

1. **Live fetch** — first call per session hits `docs.openclaw.ai/llms-full.txt`. If it's reachable and passes sanity checks, the cache is updated.
2. **User cache** — `~/.jarvis/docs/openclaw-llms-full.txt`, default 24h TTL. Override the TTL via `JARVIS_DOCS_TTL=<seconds>`.
3. **Bundled fallback** — a copy of the docs ships in the pip package, so the CLI works fully offline.

Every `jarvis context --json` payload includes a `docs` object with `source` (`remote` / `cache` / `bundled`), `age_seconds`, and `remote_status` — your agent can use those signals to gauge how stale the docs it's reading might be.

## Updating

```bash
pipx upgrade jarvis-cli
jarvis codex install   # re-write the instructions file in case it changed
```

The OpenClaw docs auto-refresh on every run when the cache is stale; you don't need to upgrade the CLI to get new docs.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `JARVIS_HOST` | `127.0.0.1` | Default appliance host for `health`, `context`, etc. |
| `JARVIS_DOCS_TTL` | `86400` (24h) | Docs cache TTL in seconds. Set to `0` for "never use cache." |

## Platform support

macOS only for v0.3.0. Linux / Windows are out of scope for the public release. The bulk of the CLI's runtime checks are macOS-specific (`launchctl`, `brew`, `~/.codex`, etc.).

## License

MIT. See [LICENSE](./LICENSE).

## Security & secrets

- The CLI reads files under `~/.jarvis/` and the user's `~/.codex/` / `~/.claude/` directories — nothing else outside its own package install.
- It never sends data anywhere except the documentation fetch (`docs.openclaw.ai/llms-full.txt`, public).
- It does not collect telemetry of any kind.
- `jarvis diagnose` produces a sanitized report — secrets, tokens, and known internal hostnames are scrubbed before output.

## Issues / contact

Open an issue at https://github.com/amart-builder/jarvis-cli/issues. For escalations involving a paid Jarvis support agreement, contact the operator who installed the appliance.
