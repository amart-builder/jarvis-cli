"""`jarvis restart` — restart a service or all services.

WRITE command. Single-component restarts are low-risk (idempotent for our
services) and don't require confirmation. `--all` is a sequenced restart
(memory before gateway, etc.) and DOES require confirmation.
"""
from __future__ import annotations

from typing import Annotated

import typer

from jarvis.lib.output import emit
from jarvis.lib.services import KNOWN_COMPONENTS, restart_service

# Canonical sequenced order for --all. Memory and Neo4j first (gateway hooks
# auth against memory; if memory isn't up the gateway emits 401s). Channels
# last (they fan out from gateway).
RESTART_ORDER: list[str] = [
    "neo4j",
    "memory",
    "gateway",
    "lightpanda",
    "discord",
    "watchdog",
]


def restart(
    component: Annotated[
        str | None, typer.Argument(help="Component to restart. Use 'all' for sequenced restart.")
    ] = None,
    all_services: Annotated[
        bool, typer.Option("--all", help="Restart everything in canonical order.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt for --all.")
    ] = False,
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            help="Agent name (lowercase). Required on macOS to construct LaunchAgent labels.",
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Restart one component, or `--all` for a sequenced full restart."""
    if all_services or component == "all":
        if not yes and not json_output:
            confirm = typer.confirm(
                f"Restart all {len(RESTART_ORDER)} components in sequence? "
                "Brief (~10–30s) outage during the cycle."
            )
            if not confirm:
                raise typer.Exit(code=1)
        results: list[dict[str, str]] = []
        for comp in RESTART_ORDER:
            try:
                restart_service(comp, agent_name_lower=agent)
                results.append({"component": comp, "result": "restarted"})
            except Exception as e:  # noqa: BLE001 - we want to report any error
                results.append({"component": comp, "result": f"FAILED: {e}"})
        emit({"action": "restart_all", "results": results}, as_json=json_output)
        return

    if not component:
        typer.echo("specify a component or use --all")
        raise typer.Exit(code=2)
    if component not in KNOWN_COMPONENTS:
        typer.echo(
            f"unknown component '{component}'. Known: {', '.join(KNOWN_COMPONENTS)}"
        )
        raise typer.Exit(code=2)
    restart_service(component, agent_name_lower=agent)
    emit({"action": "restart", "component": component, "result": "restarted"}, as_json=json_output)
