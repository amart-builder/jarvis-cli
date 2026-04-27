"""`jarvis docs` — query the embedded canonical docs bundle.

The killer feature for LLM-as-support. Bundle includes:
- HARDENING.md (the 20 install rules)
- ORCHESTRATOR.md (phase sequence)
- workers/phase-NN-*.md (per-phase procedures)
- lessons-learned.md (canonical fix patterns from real installs)
- openclaw/ (full upstream pull from docs.openclaw.ai/llms-full.txt)

Usage:
    jarvis docs                       # list available docs
    jarvis docs hardening             # full HARDENING.md
    jarvis docs hardening rule-18     # specific rule
    jarvis docs phase 7               # phase-07-jarvis-memory.md
    jarvis docs known-issues          # lessons-learned.md
    jarvis docs search "401"          # full-text search
    jarvis docs update                # pull latest OpenClaw upstream

Always returns content; never modifies state (except `update`).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.markdown import Markdown

from jarvis.lib.dispatch import dispatch_remote, should_dispatch_remote
from jarvis.lib.output import console, emit, fail

app = typer.Typer(help="Query the embedded canonical docs bundle.", no_args_is_help=True)

# Bundle lives next to the jarvis package after install. Use __file__-relative
# discovery so it works whether installed via pip or run from source.
_BUNDLE_ROOT = Path(__file__).parent.parent / "docs_bundle"

# Where to pull OpenClaw upstream docs from. The /llms-full.txt endpoint is an
# LLM-friendly aggregation of the entire docs site — single file, no scraping.
_OPENCLAW_LLMS_URL = "https://docs.openclaw.ai/llms-full.txt"


@app.command("list")
def list_docs(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    """List every doc in the bundle."""
    cfg = should_dispatch_remote()
    if cfg is not None:
        raise typer.Exit(code=dispatch_remote(cfg))
    if not _BUNDLE_ROOT.exists():
        fail(f"Docs bundle not found at {_BUNDLE_ROOT}. Run `jarvis docs update` first.")
    docs = sorted(p.relative_to(_BUNDLE_ROOT) for p in _BUNDLE_ROOT.rglob("*.md"))
    docs += sorted(p.relative_to(_BUNDLE_ROOT) for p in _BUNDLE_ROOT.rglob("*.txt"))
    payload = {"bundle_root": str(_BUNDLE_ROOT), "docs": [str(d) for d in docs]}
    if json_output:
        emit(payload, as_json=True)
        return
    console.print(f"[bold]docs bundle[/bold]: {_BUNDLE_ROOT}")
    for d in docs:
        console.print(f"  {d}")


@app.command("show")
def show(
    topic: Annotated[str, typer.Argument(help="Top-level doc name (hardening, orchestrator, ...)")],
    sub: Annotated[
        str | None,
        typer.Argument(help="Optional sub-section, e.g. 'rule-18' for hardening, '7' for phase."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show a doc or a sub-section of one."""
    cfg = should_dispatch_remote()
    if cfg is not None:
        raise typer.Exit(code=dispatch_remote(cfg))
    path = _resolve_topic(topic, sub)
    if not path or not path.exists():
        fail(
            f"No doc found for '{topic}' "
            + (f"sub='{sub}' " if sub else "")
            + f"in {_BUNDLE_ROOT}"
        )
    text = path.read_text(encoding="utf-8")
    if sub and topic.lower() == "hardening":
        text = _extract_hardening_rule(text, sub) or text
    if json_output:
        emit({"path": str(path), "content": text}, as_json=True)
    else:
        console.print(Markdown(text))


@app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Substring or regex to search for.")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
    regex: Annotated[bool, typer.Option("--regex", help="Treat query as a regex.")] = False,
) -> None:
    """Full-text search across the docs bundle."""
    cfg = should_dispatch_remote()
    if cfg is not None:
        raise typer.Exit(code=dispatch_remote(cfg))
    if not _BUNDLE_ROOT.exists():
        fail(f"Docs bundle not found at {_BUNDLE_ROOT}.")
    pattern = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    hits: list[dict[str, str]] = []
    for path in sorted(_BUNDLE_ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".txt"}:
            continue
        try:
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if pattern.search(line):
                    hits.append(
                        {
                            "path": str(path.relative_to(_BUNDLE_ROOT)),
                            "line": str(lineno),
                            "text": line.strip(),
                        }
                    )
        except UnicodeDecodeError:
            continue
    if json_output:
        emit({"query": query, "hits": hits, "count": len(hits)}, as_json=True)
        return
    console.print(f"[bold]{len(hits)} matches[/bold] for '{query}'")
    for hit in hits[:50]:
        console.print(f"  {hit['path']}:{hit['line']}  {hit['text']}")
    if len(hits) > 50:
        console.print(f"  ... and {len(hits) - 50} more (use --json for full list)")


@app.command("update")
def update(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Pull latest OpenClaw upstream docs into the bundle.

    Fetches the LLM-friendly aggregated docs file from docs.openclaw.ai and
    overwrites docs_bundle/openclaw/llms-full.txt. The JarvisClaw-authored
    docs (HARDENING, ORCHESTRATOR, workers, lessons-learned) are NOT
    touched — those are part of the package and updated by package release.
    """
    cfg = should_dispatch_remote()
    if cfg is not None:
        raise typer.Exit(code=dispatch_remote(cfg))
    target = _BUNDLE_ROOT / "openclaw" / "llms-full.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = httpx.get(_OPENCLAW_LLMS_URL, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        fail(f"Failed to pull {_OPENCLAW_LLMS_URL}: {e}")
        return  # mypy
    backup = target.with_suffix(".txt.bak")
    if target.exists():
        shutil.copy2(target, backup)
    target.write_text(resp.text, encoding="utf-8")
    payload = {
        "url": _OPENCLAW_LLMS_URL,
        "path": str(target),
        "bytes": len(resp.text),
        "backup": str(backup) if backup.exists() else None,
    }
    emit(payload, as_json=json_output)


def _resolve_topic(topic: str, sub: str | None) -> Path | None:
    """Map a (topic, sub) pair to a file in the bundle."""
    topic_lower = topic.lower()
    if topic_lower == "hardening":
        return _BUNDLE_ROOT / "HARDENING.md"
    if topic_lower == "orchestrator":
        return _BUNDLE_ROOT / "ORCHESTRATOR.md"
    if topic_lower == "phase":
        if not sub:
            return None
        # phase 7 -> workers/phase-07-*.md
        try:
            n = int(sub)
        except ValueError:
            return None
        candidates = sorted((_BUNDLE_ROOT / "workers").glob(f"phase-{n:02d}-*.md"))
        return candidates[0] if candidates else None
    if topic_lower in {"known-issues", "lessons", "lessons-learned"}:
        return _BUNDLE_ROOT / "lessons-learned.md"
    if topic_lower == "openclaw":
        return _BUNDLE_ROOT / "openclaw" / "llms-full.txt"
    # Fallback: try a file named exactly <topic>.md in the bundle root
    direct = _BUNDLE_ROOT / f"{topic}.md"
    return direct if direct.exists() else None


def _extract_hardening_rule(text: str, rule_id: str) -> str | None:
    """Pull a single 'Rule N' block out of HARDENING.md by id like 'rule-18' or '18'."""
    m = re.match(r"(?:rule[-_])?(\d+)", rule_id, re.IGNORECASE)
    if not m:
        return None
    n = int(m.group(1))
    # Match `## Rule 18` (or similar) up to the next `## ` or `# ` heading.
    pattern = re.compile(
        rf"^(#{{2,3}})\s*Rule\s+{n}\b.*?(?=^#{{1,3}}\s|\Z)", re.MULTILINE | re.DOTALL
    )
    match = pattern.search(text)
    return match.group(0) if match else None
