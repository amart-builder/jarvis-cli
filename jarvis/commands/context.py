"""`jarvis context` — dump everything an LLM needs to debug Jarvis.

This is THE command the client's LLM runs first when the user reports an
issue. It produces a single self-contained JSON blob that the LLM can
ingest as context — no further tool calls needed before the LLM has full
ground truth.

Output structure (JSON, top-level keys):
    schema_version, generated_at, versions, platform, host, health,
    errors_recent_24h, config_sanitized, hardening_check,
    docs               — freshness metadata for the OpenClaw docs payload
                          {source, age_seconds, remote_status, bundled_version, cache_path}
    openclaw_docs      — full text of the active OpenClaw documentation bundle
                          (live-fetched if cache is stale, cached if fresh,
                          bundled fallback if remote unreachable)
    next_steps_hint, host_hint (optional)

The `docs` object lets a downstream LLM reason about how trustworthy the
`openclaw_docs` payload is — e.g., a `source: "bundled"` plus a stale
`age_seconds` is a signal to mention "docs may be out of date" in its reply.

Use `--no-docs` to skip the `openclaw_docs` payload (faster, smaller output;
useful for repeat calls in the same session that already ingested docs).

`--topic` is preserved for backward compatibility but is now a no-op — the
`openclaw_docs` payload is always the full bundle. Use grep / search on the
output if you need a topic slice.
"""
from __future__ import annotations

import datetime as _dt
from typing import Annotated

import typer

from jarvis.lib.docs_refresh import load_docs
from jarvis.lib.health import check_all, host_hint, resolve_host
from jarvis.lib.output import emit
from jarvis.lib.platform import detect_platform
from jarvis.version import DOCS_VERSION, OPENCLAW_VERSION, __version__


def context(
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            help="Appliance host. Defaults to JARVIS_HOST env, then 127.0.0.1.",
        ),
    ] = None,
    topic: Annotated[
        str | None,
        typer.Option(
            "--topic",
            help="Deprecated in v0.3.0 (no-op). The full OpenClaw docs bundle is always returned; grep the output for a topic slice.",
        ),
    ] = None,
    no_docs: Annotated[
        bool,
        typer.Option(
            "--no-docs",
            help="Skip the openclaw_docs payload (faster, smaller). Freshness metadata under `docs` is still emitted.",
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Dump full debugging context for LLM consumption."""
    plat = detect_platform()
    resolved_host = resolve_host(host)
    health_results = check_all(host=resolved_host, timeout=3.0)
    hint = host_hint(resolved_host, health_results)

    # `--topic` is intentionally accepted but no-op — preserved so existing
    # invocations don't break. We pass it to the renderer for visibility.
    _ = topic

    docs_result = load_docs()
    docs_meta: dict[str, object] = {
        "source": docs_result.source,
        "age_seconds": docs_result.age_seconds,
        "remote_status": docs_result.remote_status,
        "bundled_version": docs_result.bundled_version,
        "cache_path": docs_result.cache_path,
    }

    payload: dict[str, object] = {
        "schema_version": "2.0",
        "generated_at": _dt.datetime.now(_dt.UTC).isoformat(),
        "versions": {
            "jarvis_cli": __version__,
            "docs": DOCS_VERSION,
            "openclaw": OPENCLAW_VERSION,
        },
        "platform": {
            "os": plat.os_name,
            "version": plat.os_version,
            "service_manager": plat.service_manager,
            "is_apple_silicon": plat.is_apple_silicon,
        },
        "host": resolved_host,
        "health": {
            "all_healthy": all(r.healthy for r in health_results),
            "components": [
                {
                    "component": r.component,
                    "healthy": r.healthy,
                    "endpoint": r.endpoint,
                    "detail": r.detail,
                    "status_code": r.status_code,
                }
                for r in health_results
            ],
        },
        # TODO v0.4: errors_recent, config_sanitized, hardening_check
        "errors_recent_24h": "TODO v0.4",
        "config_sanitized": "TODO v0.4",
        "hardening_check": "TODO v0.4",
        "docs": docs_meta,
        "openclaw_docs": None if no_docs else docs_result.text,
        "next_steps_hint": (
            "If something looks wrong, run `jarvis diagnose` for a packaged report. "
            "For specific fixes, query `jarvis docs <topic>` or `jarvis docs search <query>`. "
            "Read-only commands are safe to call freely; restart/repair/recover "
            "commands change state and require confirmation."
        ),
    }
    if hint:
        payload["host_hint"] = hint
    emit(payload, as_json=True if json_output else False, human_renderer=_render_human(payload))


def _render_human(payload: dict[str, object]):
    """Render a compact summary when --json isn't set.

    The full payload is huge (~5 MB of OpenClaw docs). We don't dump it to
    terminal by default — we tell the user to use --json for full output and
    show a freshness-aware summary instead.
    """

    def render():
        from rich.panel import Panel
        from rich.text import Text

        versions = payload["versions"]  # type: ignore[index]
        platform_info = payload["platform"]  # type: ignore[index]
        health = payload["health"]  # type: ignore[index]
        docs = payload["docs"]  # type: ignore[index]
        openclaw_docs = payload.get("openclaw_docs")
        text = Text()
        text.append("jarvis context\n", style="bold")
        text.append(
            f"  jarvis-cli {versions['jarvis_cli']}  "  # type: ignore[index]
            f"docs {versions['docs']}  "  # type: ignore[index]
            f"openclaw {versions['openclaw']}\n"  # type: ignore[index]
        )
        text.append(
            f"  platform   {platform_info['os']} ({platform_info['version']})\n",  # type: ignore[index]
        )
        text.append(
            "  health     "
            + ("all healthy" if health["all_healthy"] else "degraded")  # type: ignore[index]
            + "\n"
        )
        if isinstance(docs, dict):
            source = docs.get("source", "?")
            age = docs.get("age_seconds", "?")
            remote_status = docs.get("remote_status", "?")
            text.append(
                f"  docs       source={source}  age={age}s  remote={remote_status}\n",
            )
        size = len(openclaw_docs) if isinstance(openclaw_docs, str) else 0
        text.append(f"  payload    openclaw_docs={size:,} chars\n")
        text.append("\n")
        text.append(
            "Use --json to emit the full payload (recommended for piping into an LLM):\n",
            style="dim",
        )
        text.append("  jarvis context --json > /tmp/jarvis-ctx.json\n", style="cyan")
        return Panel(text, expand=False)

    return render
