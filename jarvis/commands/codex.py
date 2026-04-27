"""`jarvis codex` — Codex / Claude Code agent integration commands.

Today this group has one subcommand:

    jarvis codex install [--auto] [--for {codex,claude-code,both}]

It injects a small Markdown block (the canonical body lives in
`jarvis.lib.agent_instructions.JARVIS_AGENT_INSTRUCTIONS_BODY`) into the
agent's auto-loaded global instructions file:

  - Codex CLI   → ~/.codex/AGENTS.md
  - Claude Code → ~/.claude/CLAUDE.md

The block is wrapped between stable markers (`<!-- BEGIN jarvis-cli ... -->`
and `<!-- END jarvis-cli -->`), so the install command is safe even when
the user already has content in those files: any existing content
outside our markers is preserved verbatim. Re-running the command refreshes
just our block; everything else is untouched.

Writing files under `~/.codex/` and `~/.claude/` is not state-changing on
the appliance, so this command is non-interactive (no `[y/N]` prompt) by
design. Use `--auto` to suppress the per-file output line; otherwise the
command prints what it touched to stdout for visibility.
"""
from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from jarvis.lib.agent_instructions import upsert_block

app = typer.Typer(
    name="codex",
    help="Codex / Claude Code agent integration commands.",
    no_args_is_help=True,
)


class _Target(StrEnum):
    codex = "codex"
    claude_code = "claude-code"
    both = "both"


# Path templates relative to HOME — exposed for tests.
# These match the documented auto-load conventions:
#   - Codex CLI auto-loads ~/.codex/AGENTS.md (and project-local AGENTS.md)
#   - Claude Code auto-loads ~/.claude/CLAUDE.md (and project-local CLAUDE.md)
CODEX_INSTRUCTIONS_RELPATH = ".codex/AGENTS.md"
CLAUDE_INSTRUCTIONS_RELPATH = ".claude/CLAUDE.md"
CODEX_HOME_RELPATH = ".codex"
CLAUDE_HOME_RELPATH = ".claude"


def _atomic_upsert(path: Path) -> str:
    """Inject or refresh our jarvis-cli block in `path`.

    Returns one of "created" / "updated-block" / "appended-block" describing
    what happened. Atomic via tmp-sibling + os.replace(). Creates parent
    directories as needed.
    """
    existing: str | None = (
        path.read_text(encoding="utf-8") if path.exists() else None
    )

    new_content = upsert_block(existing)

    # Decide outcome label for the user message.
    if existing is None:
        outcome = "created"
    elif existing == new_content:
        outcome = "unchanged"
    else:
        # Was our block already there? upsert_block only changes the file in
        # two ways: replacing between markers, or appending at end.
        from jarvis.lib.agent_instructions import JARVIS_BLOCK_BEGIN

        outcome = "updated-block" if JARVIS_BLOCK_BEGIN in existing else "appended-block"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    os.replace(tmp, path)
    return outcome


def _detect_codex(home: Path) -> bool:
    return (home / CODEX_HOME_RELPATH).exists()


def _detect_claude_code(home: Path) -> bool:
    return (home / CLAUDE_HOME_RELPATH).exists()


@app.command("install")
def install(
    target: Annotated[
        _Target,
        typer.Option(
            "--for",
            help="Which agent to register with. `both` auto-detects (default).",
            case_sensitive=False,
        ),
    ] = _Target.both,
    auto: Annotated[
        bool,
        typer.Option(
            "--auto",
            help="Suppress per-file output. Used by scripts/install.sh.",
        ),
    ] = False,
) -> None:
    """Register jarvis-cli with Codex CLI and/or Claude Code.

    Injects a marker-delimited block of agent operating instructions into
    the agent's global instructions file (`~/.codex/AGENTS.md` and/or
    `~/.claude/CLAUDE.md`). Any existing content outside the markers is
    preserved. Idempotent — re-running refreshes just our block.

    Non-interactive — never prompts.
    """
    console = Console(quiet=auto)
    home = Path.home()

    targets: list[tuple[str, Path]] = []

    want_codex = target in (_Target.codex, _Target.both)
    want_claude = target in (_Target.claude_code, _Target.both)

    # For an explicit --for codex / --for claude-code, always write.
    # For --for both (default), only write if the agent is detected.
    if want_codex and (target == _Target.codex or _detect_codex(home)):
        targets.append(("codex", home / CODEX_INSTRUCTIONS_RELPATH))

    if want_claude and (target == _Target.claude_code or _detect_claude_code(home)):
        targets.append(("claude-code", home / CLAUDE_INSTRUCTIONS_RELPATH))

    if not targets:
        console.print(
            "[yellow]No supported agent detected[/yellow] — neither "
            f"~/{CODEX_HOME_RELPATH} nor ~/{CLAUDE_HOME_RELPATH} exists."
        )
        console.print(
            "Install Codex (https://github.com/openai/codex) or Claude Code "
            "(https://github.com/anthropics/claude-code), then re-run "
            "`jarvis codex install`."
        )
        raise typer.Exit(code=0)

    for name, path in targets:
        outcome = _atomic_upsert(path)
        console.print(f"[green]{outcome}[/green] {name}: {path}")
