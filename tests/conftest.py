"""Shared pytest fixtures for jarvis-cli tests."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Re-root HOME to an isolated tmp directory.

    Patches both `os.environ["HOME"]` and `Path.home()` so any code under
    test that reads either gets the tmp path. Yields the tmp HOME for the
    test to inspect / pre-populate.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Some platforms also consult USERPROFILE (Windows) — patch defensively.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _scrub_jarvis_docs_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests don't inherit a JARVIS_DOCS_TTL from the developer's
    shell. Removed for every test; individual tests can re-set it."""
    monkeypatch.delenv("JARVIS_DOCS_TTL", raising=False)
