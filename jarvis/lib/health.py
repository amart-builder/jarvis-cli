"""Health-check primitives.

Simple HTTP probes against the well-known Jarvis component endpoints. These
are the same endpoints the install verifier uses in Phase 10, factored out
so `jarvis status`, `jarvis health`, and `jarvis diagnose` all share them.

**Host resolution.** jarvis-cli is designed to be run both ON the appliance
(checking 127.0.0.1) and FROM the operator's laptop debugging a remote
appliance over Tailscale. Resolution order for the host:
  1. Explicit `host=` argument to `check_*`.
  2. `JARVIS_HOST` env var.
  3. `~/.jarvis/config.toml` `[appliance] host = "..."` (TODO v0.3).
  4. Fallback: `127.0.0.1`.

`JARVIS_HOST` accepts bare hostnames or IPs. Examples:
    JARVIS_HOST=100.x.y.z jarvis status
    JARVIS_HOST=mymachine.tailNNNNNN.ts.net jarvis health
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

# Default host when no env or explicit override is set.
DEFAULT_HOST = "127.0.0.1"

# Per-component port + path on the host. Combined with the resolved host
# at probe time to form the final URL.
_COMPONENT_PORTS: dict[str, tuple[int, str]] = {
    "gateway": (18789, "/health"),
    "memory": (3500, "/health"),
    "neo4j": (7474, "/"),
    "lightpanda": (9223, "/json/version"),
}


def resolve_host(explicit: str | None = None) -> str:
    """Pick the host to probe. See module docstring for resolution order."""
    if explicit:
        return explicit
    env_host = os.environ.get("JARVIS_HOST", "").strip()
    if env_host:
        return env_host
    return DEFAULT_HOST


def endpoints(host: str | None = None) -> dict[str, str]:
    """Return component → URL mapping for the resolved host."""
    h = resolve_host(host)
    return {
        comp: f"http://{h}:{port}{path}" for comp, (port, path) in _COMPONENT_PORTS.items()
    }


# Back-compat shim. Some code (and tests) imports the constant directly.
# Reflects the default host at module-load time; for live override, call
# `endpoints()` instead.
ENDPOINTS: dict[str, str] = endpoints()


@dataclass(frozen=True)
class HealthResult:
    component: str
    endpoint: str
    healthy: bool
    status_code: int | None
    detail: str
    raw_body: dict[str, Any] | None


def check_component(
    component: str, *, host: str | None = None, timeout: float = 2.0
) -> HealthResult:
    """Probe a single component's health endpoint.

    Returns a HealthResult — never raises. Network errors, timeouts, and
    non-2xx responses all become `healthy=False` with a descriptive `detail`.
    """
    eps = endpoints(host)
    if component not in eps:
        return HealthResult(
            component=component,
            endpoint="(unknown)",
            healthy=False,
            status_code=None,
            detail=f"unknown component '{component}' — not in ENDPOINTS",
            raw_body=None,
        )
    url = eps[component]
    try:
        resp = httpx.get(url, timeout=timeout)
    except httpx.TimeoutException:
        return HealthResult(component, url, False, None, f"timeout after {timeout}s", None)
    except httpx.ConnectError as e:
        return HealthResult(component, url, False, None, f"connection refused: {e}", None)
    except httpx.HTTPError as e:
        return HealthResult(component, url, False, None, f"http error: {e}", None)

    body: dict[str, Any] | None = None
    if "application/json" in resp.headers.get("content-type", ""):
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = None

    healthy = 200 <= resp.status_code < 300
    # jarvis-memory's /health returns {"status":"ok","neo4j":"ok","chromadb":"ok"}
    # — we're stricter than just HTTP 2xx for it.
    if component == "memory" and isinstance(body, dict):
        healthy = (
            body.get("status") == "ok"
            and body.get("neo4j") == "ok"
            and body.get("chromadb") == "ok"
        )
    return HealthResult(
        component=component,
        endpoint=url,
        healthy=healthy,
        status_code=resp.status_code,
        detail="ok" if healthy else f"http {resp.status_code}",
        raw_body=body,
    )


def check_all(*, host: str | None = None, timeout: float = 2.0) -> list[HealthResult]:
    """Probe every known component. Order matches _COMPONENT_PORTS insertion."""
    return [check_component(c, host=host, timeout=timeout) for c in _COMPONENT_PORTS]


def host_hint(host: str, results: list[HealthResult]) -> str | None:
    """Return a UX hint when checks fail in a way that suggests host misconfig.

    If every component is unhealthy with `connection refused` AND the host is
    loopback AND no JARVIS_HOST is set in the environment, the operator is
    likely running this from a non-appliance machine and forgot to point at
    the remote host. Returns a one-line nudge or None if no hint applies.
    """
    if host != DEFAULT_HOST:
        return None
    if os.environ.get("JARVIS_HOST", "").strip():
        return None
    all_refused = results and all(
        not r.healthy and "connection refused" in (r.detail or "") for r in results
    )
    if not all_refused:
        return None
    return (
        "All endpoints refused on 127.0.0.1. If you're running this from a non-"
        "appliance machine (e.g. your laptop), set JARVIS_HOST to the appliance "
        "Tailscale IP or hostname and retry. Example: "
        "JARVIS_HOST=100.x.y.z jarvis status"
    )
