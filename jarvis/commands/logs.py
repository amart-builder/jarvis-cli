"""`jarvis logs` — tail logs for a Jarvis component.

Thin wrapper over `journalctl` (Linux) or the macOS log files at
~/Desktop/<agent>/logs/. v0.1 returns a snapshot; --follow streaming
support is a v0.2 feature (needs proper async streaming through Typer/Rich).
"""
from __future__ import annotations

from typing import Annotated

import typer

from jarvis.lib.output import emit
from jarvis.lib.services import service_logs


def logs(
    component: Annotated[str, typer.Argument(help="Component name (gateway, memory, neo4j, ...)")],
    n: Annotated[int, typer.Option("-n", "--lines", help="Number of lines to retrieve.")] = 100,
    follow: Annotated[bool, typer.Option("-f", "--follow", help="Tail in real time.")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Tail logs for one component."""
    if follow:
        # TODO v0.2: stream via subprocess.Popen + iter on stdout
        typer.echo("--follow not yet implemented in v0.1; use journalctl -fu directly")
        raise typer.Exit(code=2)

    output = service_logs(component, lines=n, follow=False)
    if json_output:
        emit({"component": component, "lines": output.splitlines()}, as_json=True)
    else:
        typer.echo(output)
