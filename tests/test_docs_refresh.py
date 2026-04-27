"""Tests for `jarvis.lib.docs_refresh.load_docs()`.

Covers the four critical code paths:
    1. cache hit — cache is fresh, no network call made
    2. cache miss + remote OK — fetch, sanity-pass, cache write
    3. remote unreachable — falls back to bundled (when no cache exists)
    4. sanity-fail — fetched body is too short → falls back to bundled

Plus a fifth case verifying the TTL override via `JARVIS_DOCS_TTL`.
"""
from __future__ import annotations

import io
import time
from pathlib import Path
from urllib import error as _urlerror

import pytest

from jarvis.lib import docs_refresh


def _fake_response(body: str, status: int = 200):
    """Build a fake urlopen() return value mimicking http.client.HTTPResponse."""

    class _Resp:
        def __init__(self, raw: bytes, code: int) -> None:
            self._raw = raw
            self.status = code

        def read(self) -> bytes:
            return self._raw

        def getcode(self) -> int:
            return self.status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    return _Resp(body.encode("utf-8"), status)


def _make_sanity_passing_body(extra: str = "") -> str:
    """Synthesize a body that passes sanity (>=50_000 chars + >=5 OpenClaw)."""
    base = "OpenClaw " * 100  # 100 occurrences of the required marker
    padding_size = max(0, docs_refresh.MIN_LENGTH - len(base) - len(extra) + 100)
    return base + ("x" * padding_size) + extra


# ---------------------------------------------------------------------------


def test_cache_hit_skips_network(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh cache file means no network call is made; source == 'cache'."""
    cache_dir = tmp_home / ".jarvis" / "docs"
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache_file = cache_dir / docs_refresh.CACHE_FILE_NAME
    cache_body = _make_sanity_passing_body(extra="-fromcache")
    cache_file.write_text(cache_body, encoding="utf-8")
    # mtime = now (well within TTL)
    now = time.time()
    import os as _os

    _os.utime(cache_file, (now, now))

    def _boom(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("urlopen should not be called when cache is fresh")

    monkeypatch.setattr(docs_refresh._urlrequest, "urlopen", _boom)

    result = docs_refresh.load_docs()

    assert result.source == "cache"
    assert result.text == cache_body
    assert result.remote_status == "skipped-fresh"
    assert result.cache_path == str(cache_file)


def test_cache_miss_remote_ok_writes_cache(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No cache exists → live fetch succeeds → cache is written; source=='remote'."""
    body = _make_sanity_passing_body(extra="-remote")

    def _fake_open(req, timeout=None):  # noqa: ARG001
        return _fake_response(body, status=200)

    monkeypatch.setattr(docs_refresh._urlrequest, "urlopen", _fake_open)

    result = docs_refresh.load_docs()

    assert result.source == "remote"
    assert result.text == body
    assert result.remote_status == "200-ok"
    assert result.age_seconds == 0
    cache_file = tmp_home / ".jarvis" / "docs" / docs_refresh.CACHE_FILE_NAME
    assert cache_file.exists(), "cache file should have been written"
    assert cache_file.read_text(encoding="utf-8") == body


def test_remote_unreachable_falls_back_to_bundled(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Network error + no cache → bundled fallback; remote_status describes failure."""

    def _raise_url_error(*args, **kwargs):  # noqa: ARG001
        raise _urlerror.URLError("simulated DNS failure")

    monkeypatch.setattr(docs_refresh._urlrequest, "urlopen", _raise_url_error)

    result = docs_refresh.load_docs()

    assert result.source == "bundled"
    assert result.remote_status == "network-error"
    # bundled body should pass sanity (the real shipped file is ~5 MB)
    assert len(result.text) >= docs_refresh.MIN_LENGTH


def test_sanity_fail_too_short_falls_back(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 OK with a too-short body → sanity-fail:too-short, fallback to bundled."""

    def _fake_open(req, timeout=None):  # noqa: ARG001
        return _fake_response("tiny error page OpenClaw OpenClaw", status=200)

    monkeypatch.setattr(docs_refresh._urlrequest, "urlopen", _fake_open)

    result = docs_refresh.load_docs()

    assert result.source == "bundled"
    assert result.remote_status == "sanity-fail:too-short"
    cache_file = tmp_home / ".jarvis" / "docs" / docs_refresh.CACHE_FILE_NAME
    assert not cache_file.exists(), "sanity-failed body must not be cached"


def test_ttl_override_zero_forces_refetch(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JARVIS_DOCS_TTL=0 makes any existing cache stale → always re-fetches."""
    cache_dir = tmp_home / ".jarvis" / "docs"
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache_file = cache_dir / docs_refresh.CACHE_FILE_NAME
    stale_body = _make_sanity_passing_body(extra="-stale")
    cache_file.write_text(stale_body, encoding="utf-8")
    # mtime = now (would be fresh under default TTL — but we force TTL=0)

    fresh_body = _make_sanity_passing_body(extra="-fresh")

    calls = []

    def _fake_open(req, timeout=None):  # noqa: ARG001
        calls.append(1)
        return _fake_response(fresh_body, status=200)

    monkeypatch.setattr(docs_refresh._urlrequest, "urlopen", _fake_open)
    monkeypatch.setenv("JARVIS_DOCS_TTL", "0")

    result = docs_refresh.load_docs()

    assert calls == [1], "TTL=0 should force a network call even with fresh cache"
    assert result.source == "remote"
    assert result.text == fresh_body
