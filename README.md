# Jarvis CLI

> **For AI assistants reading this README.** If the user pasted this repo's URL into your chat and asked you to install it, the user is on their **laptop**, but their Jarvis appliance is almost certainly running on a **different machine** (a Mac Mini in their apartment, a NUC, or a VPS). Your job is to set the laptop up as a thin SSH client to that machine. Walk them through this:
>
> 1. Have them paste this one line into your terminal (their laptop). It downloads + installs `jarvis` and registers it with you, the agent:
>
>    ```bash
>    curl -sSL https://raw.githubusercontent.com/amart-builder/jarvis-cli/main/scripts/install.sh | bash
>    ```
>
> 2. Then run the interactive onboarding:
>
>    ```bash
>    jarvis onboard
>    ```
>
>    `jarvis onboard` auto-detects Tailscale peers, verifies SSH reachability, installs `jarvis-cli` on the remote appliance if it's not there yet, and writes `~/.jarvis/setup.toml`. Let it prompt the user — the prompts are designed for non-technical operators.
>
> 3. Once `~/.jarvis/setup.toml` exists with `mode = "remote"`, every subsequent `jarvis <cmd>` on the laptop transparently SSHes the same command to the appliance and streams its output back. You can debug as if you were running on the appliance directly.
>
> If `~/.jarvis/setup.toml` is missing when the user reports a problem, **always run `jarvis onboard` first** before any other jarvis command — otherwise you'll be querying the wrong machine.

---

## One-line install (paste into Codex or Claude Code on the user's laptop)

```bash
curl -sSL https://raw.githubusercontent.com/amart-builder/jarvis-cli/main/scripts/install.sh | bash
```

The installer drops `jarvis` onto your PATH and registers it with the agent (writes a marker block into `~/.codex/AGENTS.md` and/or `~/.claude/CLAUDE.md`). After install, run `jarvis onboard` once to wire the laptop to the appliance over SSH, then tell the agent: *"my Jarvis is broken — debug it."*

---

## What this is

`jarvis-cli` is the debugging surface for a [Jarvis](https://docs.openclaw.ai) appliance — the productized OpenClaw deployment shipped to clients. When the appliance misbehaves (gateway down, channels not delivering, memory layer offline, etc.), the operator's first move is no longer "Slack the vendor." It's:

1. Open Codex (or Claude Code) on the laptop.
2. Paste the install line above. Click Allow.
3. Run `jarvis onboard` — interactive walkthrough that wires the laptop to the appliance over SSH.
4. Tell the agent: *"my Jarvis is broken — debug it."*

The agent reads the marker block `jarvis-cli` injected into `~/.codex/AGENTS.md` (or `~/.claude/CLAUDE.md`), runs `jarvis context --json` to get a complete sanitized snapshot of the appliance — versions, health of every component, recent errors, sanitized config, and the full live OpenClaw documentation bundle — and works the problem from there. State-changing commands (`restart`, `repair`, `recover`) are gated behind explicit confirmation prompts the agent must respect.

This package is **CLI-first by design**. The same `jarvis` binary works whether the agent is Codex, Claude Code, or a human at a terminal. There is no MCP server to maintain in parallel; every interaction is a regular shell command and is fully visible in the agent's transcript.

## Two-end architecture

`jarvis-cli` runs on **both** the laptop and the appliance, but does different work on each:

| | Laptop (thin client) | Appliance (the Jarvis server) |
|---|---|---|
| Role | SSH dispatcher + interactive prompts | Real workhorse: queries the running services, edits plists, restarts components |
| Setup file | `~/.jarvis/setup.toml` with `mode = "remote"` | none required (defaults to local mode) |
| Talks to | the appliance, over SSH | itself (`127.0.0.1`) |

`jarvis onboard` handles the install on the appliance for you — it `ssh`s in and runs `pipx install` there once it's verified reachability.

## Audience

- **Clients** running a Jarvis appliance who'd rather have their AI assistant debug a breakage than open a support ticket.
- **AI agents** (Codex, Claude Code, etc.) running on the user's laptop — `jarvis context --json` is purpose-built to fit in an agent's context, and the SSH dispatch is transparent so the agent doesn't need to think about it.

This is not a general-purpose system tool. Outside a Jarvis install most of the commands have nothing to talk to.

## Manual install

If you'd rather not pipe `curl` into `bash` — which is fair — install manually:

```bash
# Option 1: pipx from GitHub (matches what the script does)
pipx install git+https://github.com/amart-builder/jarvis-cli
jarvis codex install   # registers with Codex / Claude Code if either is installed
jarvis onboard         # interactive SSH setup if the appliance is on a different machine

# Option 2: clone + pipx install local
git clone https://github.com/amart-builder/jarvis-cli.git
cd jarvis-cli
pipx install .
jarvis codex install
jarvis onboard
```

Both paths require [pipx](https://pipx.pypa.io/) and Python 3.11+.

## Commands

**Onboarding:**

| Command | Purpose |
|---|---|
| `jarvis onboard` | Interactive walkthrough: detect appliance host (Tailscale-aware), verify SSH, install `jarvis-cli` on the remote, write `~/.jarvis/setup.toml`. Run once per laptop. Idempotent — re-run with `--reset` to start over. |

**Read-only** (safe for an agent to run without confirmation):

| Command | Purpose |
|---|---|
| `jarvis status` | Quick state summary of the appliance |
| `jarvis health [--host <ip>]` | Health check every component |
| `jarvis context [--json] [--no-docs]` | Full debug snapshot — versions, health, recent errors, sanitized config, bundled OpenClaw docs |
| `jarvis docs <topic>` / `jarvis docs search <query>` | Query the embedded OpenClaw documentation |
| `jarvis logs <component>` | Tail recent log lines for a component |
| `jarvis diagnose` | Generate a packaged diagnostic report |
| `jarvis version` | Print CLI / docs / OpenClaw versions |

**State-changing** (require explicit confirmation — agents must ask the user first):

| Command | Purpose |
|---|---|
| `jarvis restart <component>` / `jarvis restart --all` | Restart a service / sequenced full restart |
| `jarvis repair <subcommand>` | Scoped repair operations |
| `jarvis recover` | Full recovery walkthrough |

**Agent integration:**

| Command | Purpose |
|---|---|
| `jarvis codex install` | Register jarvis-cli with Codex and/or Claude Code (injects a marker block into `~/.codex/AGENTS.md` / `~/.claude/CLAUDE.md` that the agent auto-loads on startup) |

## Routing to a remote appliance

`jarvis onboard` is the supported way to wire the laptop to a remote appliance. It writes `~/.jarvis/setup.toml` with the connection details and `mode = "remote"`; from then on, every `jarvis <cmd>` SSHes to the configured host.

For one-off overrides (e.g., debugging a *different* appliance from the same laptop), the `JARVIS_HOST` env var still works — but only when `mode = "local"` (or no setup file). With `mode = "remote"` the SSH dispatch wins:

```bash
# Local mode (no setup.toml or mode="local"): hit a different appliance directly
JARVIS_HOST=192.168.4.42 jarvis health
jarvis health --host 192.168.4.42
```

`--host` overrides `JARVIS_HOST`; `JARVIS_HOST` overrides the `127.0.0.1` default.

## Documentation freshness

`jarvis context --json` includes the full OpenClaw documentation bundle inline so an agent has the answer to "what does <component> do?" without an extra tool call. The docs are loaded in 3 tiers:

1. **Live fetch** — first call per session hits `docs.openclaw.ai/llms-full.txt`. If it's reachable and passes sanity checks, the cache is updated.
2. **User cache** — `~/.jarvis/docs/openclaw-llms-full.txt`, default 24h TTL. Override the TTL via `JARVIS_DOCS_TTL=<seconds>`.
3. **Bundled fallback** — a copy of the docs ships in the pip package, so the CLI works fully offline.

Every `jarvis context --json` payload includes a `docs` object with `source` (`remote` / `cache` / `bundled`), `age_seconds`, and `remote_status` — your agent can use those signals to gauge how stale the docs it's reading might be.

## Updating

```bash
pipx upgrade jarvis-cli
jarvis codex install   # re-write the agent marker block in case it changed
```

If the appliance is remote, also upgrade it:

```bash
ssh user@appliance 'pipx upgrade jarvis-cli'
```

The OpenClaw docs auto-refresh on every run when the cache is stale; you don't need to upgrade the CLI to get new docs.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `JARVIS_HOST` | `127.0.0.1` | Default appliance host for `health`, `context`, etc. (only respected in local mode; `setup.toml` wins in remote mode) |
| `JARVIS_DOCS_TTL` | `86400` (24h) | Docs cache TTL in seconds. Set to `0` for "never use cache." |

| File | Purpose |
|---|---|
| `~/.jarvis/setup.toml` | Laptop's connection profile to the appliance (mode, host, user, port, identity_file). Written by `jarvis onboard`. |

## Platform support

- **Laptop side** (where you run `jarvis onboard` and dispatch): macOS or Linux with `ssh` and Python 3.11+.
- **Appliance side** (where the Jarvis services actually run): macOS (full surface incl. `repair plist`) or Linux (Ubuntu/Debian — full surface except macOS-specific `repair plist`).

## License

MIT. See [LICENSE](./LICENSE).

## Security & secrets

- The CLI reads files under `~/.jarvis/` and the user's `~/.codex/` / `~/.claude/` directories — nothing else outside its own package install.
- It never sends data anywhere except (a) the documentation fetch (`docs.openclaw.ai/llms-full.txt`, public) and (b) the SSH dispatch to the user's own appliance.
- It does not collect telemetry of any kind.
- `jarvis diagnose` produces a sanitized report — secrets, tokens, and known internal hostnames are scrubbed before output.
- `~/.jarvis/setup.toml` is written with `0600` permissions (owner-only) so the host/user/port aren't readable by other accounts on the laptop.

## Issues / contact

Open an issue at https://github.com/amart-builder/jarvis-cli/issues. For escalations involving a paid Jarvis support agreement, contact the operator who installed the appliance.
