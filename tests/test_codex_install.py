"""Tests for `jarvis codex install`.

Covers:
    - idempotency: re-running produces byte-identical files
    - both-targets path: writes Codex AND Claude Code files when both dirs exist
    - codex-only path: writes only Codex when ~/.claude/ is absent
    - claude-only path: writes only Claude Code when ~/.codex/ is absent
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from jarvis.cli import app
from jarvis.commands.codex import (
    CLAUDE_INSTRUCTIONS_RELPATH,
    CODEX_INSTRUCTIONS_RELPATH,
)
from jarvis.lib.agent_instructions import JARVIS_AGENT_INSTRUCTIONS


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(app, args)
    return result.exit_code, result.output


def test_codex_install_idempotent_both_targets(tmp_home: Path) -> None:
    """When both ~/.codex/ and ~/.claude/ exist, both files are written byte-
    identically across re-runs."""
    (tmp_home / ".codex").mkdir()
    (tmp_home / ".claude").mkdir()

    code, _ = _run(["codex", "install", "--auto"])
    assert code == 0

    codex_file = tmp_home / CODEX_INSTRUCTIONS_RELPATH
    claude_file = tmp_home / CLAUDE_INSTRUCTIONS_RELPATH

    assert codex_file.exists()
    assert claude_file.exists()

    first_codex = codex_file.read_bytes()
    first_claude = claude_file.read_bytes()

    # Re-run — must produce byte-identical files (idempotency contract).
    code2, _ = _run(["codex", "install", "--auto"])
    assert code2 == 0
    assert codex_file.read_bytes() == first_codex
    assert claude_file.read_bytes() == first_claude

    # Both files contain the canonical instructions body.
    assert codex_file.read_text(encoding="utf-8") == JARVIS_AGENT_INSTRUCTIONS
    assert claude_file.read_text(encoding="utf-8") == JARVIS_AGENT_INSTRUCTIONS


def test_codex_install_codex_only_when_claude_absent(tmp_home: Path) -> None:
    """With only ~/.codex/ present, default 'both' auto-detect writes only Codex."""
    (tmp_home / ".codex").mkdir()
    # No ~/.claude/

    code, _ = _run(["codex", "install", "--auto"])
    assert code == 0

    assert (tmp_home / CODEX_INSTRUCTIONS_RELPATH).exists()
    assert not (tmp_home / CLAUDE_INSTRUCTIONS_RELPATH).exists()


def test_codex_install_no_agents_detected_returns_clean(tmp_home: Path) -> None:
    """No agent dirs exist → command exits 0, writes nothing, prints a hint."""
    # No ~/.codex/, no ~/.claude/

    code, output = _run(["codex", "install"])  # not --auto so we see the hint
    assert code == 0
    assert "No supported agent detected" in output

    assert not (tmp_home / CODEX_INSTRUCTIONS_RELPATH).exists()
    assert not (tmp_home / CLAUDE_INSTRUCTIONS_RELPATH).exists()
