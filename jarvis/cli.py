"""Typer entry point for the `jarvis` CLI.

Subcommand groups are registered here. Each command lives in its own module
under `jarvis.commands.*` and exposes a Typer app (or function) we mount.
"""
from __future__ import annotations

import typer
from rich.console import Console

from jarvis.commands import (
    codex as codex_cmd,
    context as context_cmd,
    diagnose as diagnose_cmd,
    docs as docs_cmd,
    health as health_cmd,
    logs as logs_cmd,
    recover as recover_cmd,
    repair as repair_cmd,
    restart as restart_cmd,
    status as status_cmd,
)
from jarvis.lib.platform import detect_platform
from jarvis.version import DOCS_VERSION, OPENCLAW_VERSION, __version__

app = typer.Typer(
    name="jarvis",
    help="Jarvis appliance debugging + control surface. Read-only by default; "
    "state-changing commands require confirmation.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register subcommand groups
app.add_typer(docs_cmd.app, name="docs", help="Query the embedded canonical docs bundle.")
app.add_typer(repair_cmd.app, name="repair", help="Scoped repair commands (write — confirmation required).")
app.add_typer(codex_cmd.app, name="codex", help="Codex / Claude Code agent integration commands.")

# Register single-command modules at top level
app.command("status")(status_cmd.status)
app.command("health")(health_cmd.health)
app.command("logs")(logs_cmd.logs)
app.command("restart")(restart_cmd.restart)
app.command("diagnose")(diagnose_cmd.diagnose)
app.command("context")(context_cmd.context)
app.command("recover")(recover_cmd.recover)


@app.command("version")
def version() -> None:
    """Print CLI version, embedded docs version, and detected platform."""
    console = Console()
    plat = detect_platform()
    console.print(f"[bold]jarvis-cli[/bold]  {__version__}")
    console.print(f"[bold]docs[/bold]        {DOCS_VERSION} (openclaw {OPENCLAW_VERSION})")
    console.print(f"[bold]platform[/bold]    {plat.os_name} ({plat.os_version})")
    console.print(f"[bold]service mgr[/bold] {plat.service_manager}")


def main() -> None:
    """Entry point used by the `jarvis` console script."""
    app()


if __name__ == "__main__":
    main()
