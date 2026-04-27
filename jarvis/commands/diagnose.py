"""`jarvis diagnose` — comprehensive diagnostic bundle.

Captures:
- Output of `jarvis status` and `jarvis health`
- Recent errors from each component's logs
- Hardening rule check (13–20)
- Versions: jarvis-cli, openclaw, jarvis-memory, ubuntu/macOS
- Environment fingerprint (sanitized — no secrets)

v0.2 ships the structured diagnostic payload (no tarball yet). The packed
upload bundle remains a TODO until v0.3 — that's a heavier feature that
needs signed-URL plumbing on the JarvisClaw support side.
"""
from __future__ import annotations

import datetime as _dt
from typing import Annotated

import typer

from jarvis.lib.health import check_all, host_hint, resolve_host
from jarvis.lib.output import emit
from jarvis.version import __version__


def diagnose(
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            help="Appliance host. Defaults to JARVIS_HOST env, then 127.0.0.1.",
        ),
    ] = None,
    upload: Annotated[
        bool, typer.Option("--upload", help="Upload bundle to JarvisClaw support (TODO v0.3).")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate a comprehensive diagnostic snapshot.

    v0.2: emits the structured payload (timestamp, components, hint).
    TODO v0.3: pack into a tarball, run hardening rules check, capture
    recent log lines, support --upload via signed URL.
    """
    resolved_host = resolve_host(host)
    results = check_all(host=resolved_host, timeout=3.0)
    timestamp = _dt.datetime.now(_dt.UTC).isoformat()

    payload: dict[str, object] = {
        "timestamp": timestamp,
        "jarvis_cli_version": __version__,
        "host": resolved_host,
        "components": [
            {"component": r.component, "healthy": r.healthy, "detail": r.detail}
            for r in results
        ],
        "all_healthy": all(r.healthy for r in results),
    }
    hint = host_hint(resolved_host, results)
    if hint:
        payload["hint"] = hint

    if upload:
        payload["upload"] = {"status": "not-implemented", "available_in": "v0.3"}

    emit(payload, as_json=json_output)
