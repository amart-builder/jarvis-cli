"""Output formatting helpers.

Every command supports both human-readable (Rich-formatted) and JSON output.
The `--json` flag is implemented per-command; this module gives them shared
helpers so the structured output stays consistent.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def emit(payload: Any, *, as_json: bool, human_renderer: Any = None) -> None:
    """Emit a result either as JSON to stdout or human-readable via Rich.

    `human_renderer` may be a Rich renderable (Table, Panel, str, etc.) or a
    callable that returns one. If omitted, we pretty-print the payload with
    Rich's default formatting.

    Important: JSON output goes through plain `print()`, NOT Rich. Rich's
    console.print word-wraps to the terminal width even when piped, which
    inserts raw newlines into JSON string literals and breaks parsing.
    """
    if as_json:
        # Plain print — must not be touched by Rich's word-wrapping.
        print(json.dumps(_to_jsonable(payload), indent=2, default=str))  # noqa: T201
        return

    rendered = human_renderer() if callable(human_renderer) else human_renderer
    if rendered is not None:
        console.print(rendered)
    else:
        console.print(payload)


def fail(message: str, *, exit_code: int = 1, doc_excerpt: str | None = None) -> None:
    """Print an error to stderr with optional embedded doc excerpt, then exit.

    The doc excerpt feature is the killer move for LLM debugging: when a check
    fails, we surface the canonical fix from the bundled docs in the same
    output. The LLM never has to remember.
    """
    err_console.print(f"[red bold]✗ {message}[/red bold]")
    if doc_excerpt:
        err_console.print()
        err_console.print("[dim]DOCS:[/dim]")
        err_console.print(doc_excerpt)
    sys.exit(exit_code)


def status_table(rows: list[dict[str, Any]], *, title: str | None = None) -> Table:
    """Build a Rich table from a list of dicts. All dicts must share keys."""
    if not rows:
        return Table(title=title or "(no rows)")
    table = Table(title=title)
    for col in rows[0]:
        table.add_column(col)
    for row in rows:
        table.add_row(*(_render_cell(row[col]) for col in rows[0]))
    return table


def _render_cell(value: Any) -> str:
    if isinstance(value, bool):
        return "[green]✓[/green]" if value else "[red]✗[/red]"
    return str(value)


def _to_jsonable(value: Any) -> Any:
    """Convert dataclasses, Paths, etc. to JSON-serializable structures."""
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, "__fspath__"):
        return str(value)
    return value
