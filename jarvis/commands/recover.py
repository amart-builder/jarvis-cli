"""`jarvis recover` — last-resort full recovery walkthrough.

Multi-step interactive flow. Snapshot state, stop everything, run a clean
restart sequence, verify each component comes back. Operator (or LLM) sees
exactly what's happening at each step.

v0.1: stub. v0.2: full implementation once we've watched the first Linux
install hit a recoverable failure and codified the steps.
"""
from __future__ import annotations

from typing import Annotated

import typer

from jarvis.lib.dispatch import dispatch_remote, should_dispatch_remote
from jarvis.lib.output import emit


def recover(
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Last-resort full recovery walkthrough."""
    # Remote-dispatch prologue: confirm locally, then SSH with --yes.
    cfg = should_dispatch_remote()
    if cfg is not None:
        if not yes and not json_output:
            if not typer.confirm(
                "This will snapshot state, stop everything, and run a sequenced "
                "clean restart. Brief outage (~30s). Continue?"
            ):
                raise typer.Exit(code=1)
        raise typer.Exit(code=dispatch_remote(cfg, ensure_yes=True))

    if not yes and not json_output:
        if not typer.confirm(
            "This will snapshot state, stop everything, and run a sequenced "
            "clean restart. Brief outage (~30s). Continue?"
        ):
            raise typer.Exit(code=1)
    emit({"action": "recover", "status": "TODO v0.2"}, as_json=json_output)
