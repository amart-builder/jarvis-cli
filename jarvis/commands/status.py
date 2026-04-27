"""`jarvis status` — quick health overview of all Jarvis components.

This is the workhorse command — what an LLM runs first when something feels
off. Output is intentionally compact: one row per component, healthy/not,
recent logline if unhealthy.

Cross-platform: works on the existing macOS Mac mini installs (launchctl
services + ~/Desktop/<agent>/logs) and the new Linux Beelink installs
(systemd units + journalctl).

Host resolution: pass `--host`, set `JARVIS_HOST`, or fall back to
127.0.0.1. Run from your laptop with the appliance's Tailscale IP to debug
a remote install.
"""
from __future__ import annotations

from typing import Annotated

import typer
from rich.panel import Panel
from rich.text import Text

from jarvis.lib.health import check_all, host_hint, resolve_host
from jarvis.lib.output import emit, status_table
from jarvis.lib.platform import detect_platform


def status(
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            help="Appliance host. Defaults to JARVIS_HOST env, then 127.0.0.1.",
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit JSON for programmatic consumption.")
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Per-endpoint probe timeout, seconds.")
    ] = 2.0,
) -> None:
    """Quick health overview. Read-only, fast (~3s)."""
    resolved_host = resolve_host(host)
    results = check_all(host=resolved_host, timeout=timeout)
    plat = detect_platform()

    payload = {
        "host": resolved_host,
        "platform": {
            "os": plat.os_name,
            "version": plat.os_version,
            "service_manager": plat.service_manager,
        },
        "components": [
            {
                "component": r.component,
                "healthy": r.healthy,
                "endpoint": r.endpoint,
                "detail": r.detail,
                "status_code": r.status_code,
            }
            for r in results
        ],
        "all_healthy": all(r.healthy for r in results),
    }
    hint = host_hint(resolved_host, results)
    if hint:
        payload["hint"] = hint

    def _human():
        rows = [
            {
                "component": r.component,
                "healthy": r.healthy,
                "endpoint": r.endpoint,
                "detail": r.detail,
            }
            for r in results
        ]
        table = status_table(rows, title=f"Jarvis status @ {resolved_host} ({plat.os_name})")
        renderables = [table]
        if hint:
            renderables.append(
                Panel(Text.from_markup(f"[yellow bold]hint:[/yellow bold] {hint}"), expand=False)
            )
        summary_text = (
            "[green bold]✓ All components healthy[/green bold]"
            if payload["all_healthy"]
            else "[red bold]✗ One or more components unhealthy[/red bold] — "
            "run [cyan]jarvis diagnose[/cyan] for details"
        )
        renderables.append(Panel(Text.from_markup(summary_text), expand=False))
        return renderables

    if json_output:
        emit(payload, as_json=True)
        return
    for renderable in _human():
        emit(renderable, as_json=False)
    raise typer.Exit(code=0 if payload["all_healthy"] else 1)
