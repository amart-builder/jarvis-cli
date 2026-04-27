"""`jarvis codex` — Codex / Claude Code agent integration commands.

Today this group has one subcommand:

    jarvis codex install [--auto] [--for {codex,claude-code,both}]

It writes a small Markdown instructions file (the canonical body lives in
`jarvis.lib.agent_instructions.JARVIS_AGENT_INSTRUCTIONS`) into the agent's
auto-loaded instructions directory:

  - Codex      → ~/.codex/instructions.d/jarvis.md
  - Claude Code → ~/.claude/instructions/jarvis.md

The file teaches the agent how to use jarvis-cli when the user reports
issues with their Jarvis appliance. Re-running the command produces a
byte-identical file — safe to call from upgrade scripts and CI.

Writing files under `~/.codex/` and `~/.claude/` is not state-changing on
the appliance, so this command is non-interactive (no `[y/N]` prompt) by
design. Use `--auto` to suppress the per-file output line; otherwise the
command prints what it wrote to stdout for visibility.
"""
from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from jarvis.lib.agent_instructions import JARVIS_AGENT_INSTRUCTIONS

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
CODEX_INSTRUCTIONS_RELPATH = ".codex/instructions.d/jarvis.md"
CLAUDE_INSTRUCTIONS_RELPATH = ".claude/instructions/jarvis.md"
CODEX_HOME_RELPATH = ".codex"
CLAUDE_HOME_RELPATH = ".claude"


def _atomic_write(path: Path, content: str) -> None:
    """Write `content` to `path` via tmp-sibling + os.replace().

    Creates parent directories as needed (mode 0o755). On any error the
    exception propagates — the caller decides how to surface it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


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
    """Register jarvis-cli with Codex and/or Claude Code.

    Writes a fixed-body instructions Markdown file to the agent's
    auto-loaded instructions directory. Idempotent — running twice
    produces byte-identical output. Non-interactive — never prompts.
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
        _atomic_write(path, JARVIS_AGENT_INSTRUCTIONS)
        console.print(f"[green]wrote[/green] {name}: {path}")
