"""`jarvis health` — deep health check.

Goes beyond `status` by validating Jarvis-specific invariants beyond just
"the HTTP endpoint responded." Equivalent to running the Phase 10 verifier
from the install workers but factored as a callable command.

In v0.2 we share the same probes as `status` plus surface the resolved
host and any UX hint when checks fail in a way that suggests host
misconfig. Future expansions (called out in TODOs below) bring in the
Hardening Rule 13–20 validation, hook bearer-token checks, and channel
round-trip tests.
"""
from __future__ import annotations

from typing import Annotated

import typer

from jarvis.lib.dispatch import dispatch_remote, should_dispatch_remote
from jarvis.lib.health import check_all, host_hint, resolve_host
from jarvis.lib.output import emit


def health(
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            help="Appliance host. Defaults to JARVIS_HOST env, then 127.0.0.1.",
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Comprehensive health check. Read-only.

    TODO v0.3: validate Hardening Rules 13–20 (canonical model string,
    JARVIS_API_BEARER_TOKEN in plist, ACP routing, etc.) — call out to
    `jarvis hardening-check`.
    """
    cfg = should_dispatch_remote()
    if cfg is not None:
        raise typer.Exit(code=dispatch_remote(cfg))
    resolved_host = resolve_host(host)
    results = check_all(host=resolved_host, timeout=3.0)
    payload: dict[str, object] = {
        "host": resolved_host,
        "components": [
            {
                "component": r.component,
                "healthy": r.healthy,
                "endpoint": r.endpoint,
                "detail": r.detail,
                "status_code": r.status_code,
                "body": r.raw_body,
            }
            for r in results
        ],
        "all_healthy": all(r.healthy for r in results),
        # TODO v0.3: hardening checks, hook bearer checks, channel round-trips
    }
    hint = host_hint(resolved_host, results)
    if hint:
        payload["hint"] = hint
    emit(payload, as_json=json_output)
    raise typer.Exit(code=0 if payload["all_healthy"] else 1)
