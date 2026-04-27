"""Docs auto-refresh — 3-tier loader for the OpenClaw documentation bundle.

Priority order:
    1. live fetch  (HTTPS GET to docs.openclaw.ai/llms-full.txt, max 1× / TTL)
    2. user cache  (~/.jarvis/docs/openclaw-llms-full.txt, default 24h TTL)
    3. bundled     (jarvis/docs_bundle/openclaw/llms-full.txt — offline floor)

The bundled copy ships in the pip package so day-1 installs and air-gapped
clients never break. The cache is the warm layer for normal use. The live
fetch ensures the docs an LLM is reasoning over stay fresh — within 24h of
the upstream `docs.openclaw.ai` source.

Every fetched payload is sanity-checked before being written to cache: it
must be at least `MIN_LENGTH` chars and contain `REQUIRED_MARKER` at least
`MIN_MARKER_COUNT` times. This guards against the URL being repurposed
(e.g., redirect to a marketing page after a site redesign).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib import error as _urlerror
from urllib import request as _urlrequest

from jarvis.version import DOCS_VERSION, __version__

# Public constants — exposed for tests and for callers that want to override.
DOCS_URL: Final[str] = "https://docs.openclaw.ai/llms-full.txt"
DEFAULT_TTL_SECONDS: Final[int] = 86_400  # 24h

CONNECT_TIMEOUT: Final[float] = 5.0
READ_TIMEOUT: Final[float] = 10.0

# Sanity-check thresholds. The live llms-full.txt is ~5 MB and mentions
# "OpenClaw" hundreds of times; anything under these floors is almost
# certainly an error page or a redesigned URL serving the wrong content.
MIN_LENGTH: Final[int] = 50_000
REQUIRED_MARKER: Final[str] = "OpenClaw"
MIN_MARKER_COUNT: Final[int] = 5

CACHE_DIR_NAME: Final[str] = ".jarvis"
CACHE_SUBDIR_NAME: Final[str] = "docs"
CACHE_FILE_NAME: Final[str] = "openclaw-llms-full.txt"

USER_AGENT: Final[str] = (
    f"jarvis-cli/{__version__} (+https://github.com/amart-builder/jarvis-cli)"
)


@dataclass(frozen=True)
class DocsResult:
    """Result of `load_docs()` — the docs text plus freshness metadata.

    Fields mirror the keys callers (notably `jarvis context --json`) emit so
    a downstream LLM can reason about how stale or trustworthy the payload is.
    """

    text: str
    source: str  # "remote" | "cache" | "bundled"
    age_seconds: int
    remote_status: str  # "200-ok" | "skipped-fresh" | "timeout" | "http-NNN" | "sanity-fail:..." | "network-error" | "not-attempted"
    bundled_version: str  # always populated; reads from version.DOCS_VERSION
    cache_path: str  # absolute path to the cache file (whether or not it exists)


# --- Path helpers -----------------------------------------------------------


def _cache_dir() -> Path:
    return Path.home() / CACHE_DIR_NAME / CACHE_SUBDIR_NAME


def _cache_file() -> Path:
    return _cache_dir() / CACHE_FILE_NAME


def _bundled_file() -> Path:
    """Path to the offline-floor docs bundled inside the pip package."""
    # this file lives at jarvis/lib/docs_refresh.py — bundled is at jarvis/docs_bundle/openclaw/<file>
    return Path(__file__).parent.parent / "docs_bundle" / "openclaw" / "llms-full.txt"


# --- TTL & sanity helpers ---------------------------------------------------


def _resolve_ttl_seconds() -> int:
    """Read `JARVIS_DOCS_TTL` from env, fall back to default. Negative or
    invalid values are treated as the default (no surprises)."""
    raw = os.environ.get("JARVIS_DOCS_TTL")
    if raw is None:
        return DEFAULT_TTL_SECONDS
    try:
        ttl = int(raw)
    except ValueError:
        return DEFAULT_TTL_SECONDS
    if ttl < 0:
        return DEFAULT_TTL_SECONDS
    return ttl


def _passes_sanity(body: str) -> tuple[bool, str]:
    """Return (passed, reason) for the fetched body. Reason is the
    `remote_status` value to record on failure."""
    if len(body) < MIN_LENGTH:
        return False, "sanity-fail:too-short"
    if body.count(REQUIRED_MARKER) < MIN_MARKER_COUNT:
        return False, "sanity-fail:missing-marker"
    return True, "200-ok"


def _file_age_seconds(path: Path) -> int:
    import time

    return max(0, int(time.time() - path.stat().st_mtime))


# --- Atomic cache write -----------------------------------------------------


def _atomic_write_cache(body: str) -> Path:
    """Write `body` to the cache file via tmp-sibling + os.replace().

    Creates the cache directory mode 0o700 if missing. Returns the final
    cache path. Errors propagate so the caller can route to bundled fallback.
    """
    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    final = _cache_file()
    tmp = final.with_suffix(final.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, final)
    return final


# --- Public API -------------------------------------------------------------


def load_docs() -> DocsResult:
    """Resolve the OpenClaw docs payload following the 3-tier priority.

    Never raises on network or filesystem errors — degrades to the bundled
    copy with a descriptive `remote_status`. The only exception is if the
    bundled file itself is missing, which would mean a broken install; that
    re-raises the underlying OSError.
    """
    cache_path = _cache_file()
    ttl = _resolve_ttl_seconds()

    # Tier 2 first: cache-fresh path skips the network entirely.
    # TTL must be strictly positive — TTL=0 explicitly means "never use cache."
    if ttl > 0 and cache_path.exists():
        age = _file_age_seconds(cache_path)
        if age <= ttl:
            text = cache_path.read_text(encoding="utf-8")
            return DocsResult(
                text=text,
                source="cache",
                age_seconds=age,
                remote_status="skipped-fresh",
                bundled_version=DOCS_VERSION,
                cache_path=str(cache_path),
            )

    # Tier 1: cache miss or stale → try live fetch.
    body, remote_status = _try_fetch_remote()
    if body is not None:
        try:
            written = _atomic_write_cache(body)
            return DocsResult(
                text=body,
                source="remote",
                age_seconds=0,
                remote_status=remote_status,
                bundled_version=DOCS_VERSION,
                cache_path=str(written),
            )
        except OSError as exc:  # pragma: no cover — extremely rare
            remote_status = f"cache-write-error:{type(exc).__name__}"
            # fall through to bundled

    # Tier 3: bundled fallback. If cache exists but is stale and remote failed,
    # prefer cache over bundled — it's almost certainly fresher.
    if cache_path.exists():
        age = _file_age_seconds(cache_path)
        text = cache_path.read_text(encoding="utf-8")
        return DocsResult(
            text=text,
            source="cache",
            age_seconds=age,
            remote_status=remote_status,
            bundled_version=DOCS_VERSION,
            cache_path=str(cache_path),
        )

    bundled = _bundled_file()
    text = bundled.read_text(encoding="utf-8")
    return DocsResult(
        text=text,
        source="bundled",
        age_seconds=_file_age_seconds(bundled),
        remote_status=remote_status,
        bundled_version=DOCS_VERSION,
        cache_path=str(cache_path),
    )


def _try_fetch_remote() -> tuple[str | None, str]:
    """Attempt a live GET against `DOCS_URL`. Return (body, remote_status).

    `body` is None on any failure (network error, non-200, sanity-fail, etc.)
    and `remote_status` describes the failure for logging.
    """
    req = _urlrequest.Request(DOCS_URL, headers={"User-Agent": USER_AGENT})
    try:
        with _urlrequest.urlopen(req, timeout=READ_TIMEOUT) as resp:  # noqa: S310 — HTTPS only, validated URL
            status = getattr(resp, "status", None) or resp.getcode()
            if status != 200:
                return None, f"http-{status}"
            raw = resp.read()
    except _urlerror.HTTPError as exc:
        return None, f"http-{exc.code}"
    except _urlerror.URLError as exc:
        reason = getattr(exc, "reason", None)
        if reason is not None:
            name = type(reason).__name__.lower()
            if "timeout" in name:
                return None, "timeout"
        return None, "network-error"
    except TimeoutError:
        return None, "timeout"
    except Exception:  # noqa: BLE001 — defensive: never let docs fetch break the CLI
        return None, "network-error"

    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "decode-error"

    ok, reason = _passes_sanity(body)
    if not ok:
        return None, reason
    return body, "200-ok"
