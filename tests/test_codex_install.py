"""Tests for `jarvis codex install`.

Covers:
    - Fresh install: no existing AGENTS.md / CLAUDE.md → file created with our block
    - Idempotent re-run: byte-identical file across two runs
    - Append to existing user content: user's existing CLAUDE.md is preserved
      and our block is added at the end
    - Replace stale block: our markers are present with stale text → just the
      block content is refreshed; surrounding user content is preserved
    - Codex-only auto-detect: Codex dir present, Claude absent → only Codex
      file is touched
    - No-agents-detected: both dirs absent → exits clean, writes nothing
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
from jarvis.lib.agent_instructions import (
    JARVIS_AGENT_INSTRUCTIONS_BODY,
    JARVIS_BLOCK_BEGIN,
    JARVIS_BLOCK_END,
)


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(app, args)
    return result.exit_code, result.output


# ---------------------------------------------------------------------------


def test_codex_install_creates_files_when_no_existing_content(tmp_home: Path) -> None:
    """Fresh install: AGENTS.md / CLAUDE.md don't exist → created with our block."""
    (tmp_home / ".codex").mkdir()
    (tmp_home / ".claude").mkdir()

    code, _ = _run(["codex", "install", "--auto"])
    assert code == 0

    codex_file = tmp_home / CODEX_INSTRUCTIONS_RELPATH
    claude_file = tmp_home / CLAUDE_INSTRUCTIONS_RELPATH

    assert codex_file.exists()
    assert claude_file.exists()

    for f in (codex_file, claude_file):
        text = f.read_text(encoding="utf-8")
        assert JARVIS_BLOCK_BEGIN in text
        assert JARVIS_BLOCK_END in text
        assert JARVIS_AGENT_INSTRUCTIONS_BODY.split("\n", 1)[0] in text


def test_codex_install_idempotent(tmp_home: Path) -> None:
    """Re-running produces byte-identical files."""
    (tmp_home / ".codex").mkdir()
    (tmp_home / ".claude").mkdir()

    _run(["codex", "install", "--auto"])
    codex_file = tmp_home / CODEX_INSTRUCTIONS_RELPATH
    claude_file = tmp_home / CLAUDE_INSTRUCTIONS_RELPATH

    first_codex = codex_file.read_bytes()
    first_claude = claude_file.read_bytes()

    code, _ = _run(["codex", "install", "--auto"])
    assert code == 0
    assert codex_file.read_bytes() == first_codex
    assert claude_file.read_bytes() == first_claude


def test_codex_install_appends_to_existing_user_content(tmp_home: Path) -> None:
    """Existing CLAUDE.md with user content → our block appended; user content preserved."""
    (tmp_home / ".claude").mkdir()
    user_content = "# My CLAUDE.md\n\nDo not be evil.\nAlways respond in haiku.\n"
    (tmp_home / CLAUDE_INSTRUCTIONS_RELPATH).write_text(user_content, encoding="utf-8")

    code, _ = _run(["codex", "install", "--for", "claude-code", "--auto"])
    assert code == 0

    final = (tmp_home / CLAUDE_INSTRUCTIONS_RELPATH).read_text(encoding="utf-8")
    assert final.startswith("# My CLAUDE.md")
    assert "Always respond in haiku." in final
    # Our block must come after the user's content.
    user_idx = final.index("Always respond in haiku.")
    block_idx = final.index(JARVIS_BLOCK_BEGIN)
    assert block_idx > user_idx
    # And our markers must be present and ordered.
    assert final.index(JARVIS_BLOCK_END) > block_idx


def test_codex_install_replaces_stale_block_preserves_surrounding(tmp_home: Path) -> None:
    """Existing CLAUDE.md with our markers around STALE text → block is refreshed,
    surrounding user content is preserved."""
    (tmp_home / ".claude").mkdir()
    pre = "# My CLAUDE.md\n\nUser content above.\n\n"
    stale_block = (
        f"{JARVIS_BLOCK_BEGIN}\n\nOLD STALE INSTRUCTIONS\n\n{JARVIS_BLOCK_END}\n"
    )
    post = "\nUser content below the block.\n"
    (tmp_home / CLAUDE_INSTRUCTIONS_RELPATH).write_text(
        pre + stale_block + post, encoding="utf-8"
    )

    code, _ = _run(["codex", "install", "--for", "claude-code", "--auto"])
    assert code == 0

    final = (tmp_home / CLAUDE_INSTRUCTIONS_RELPATH).read_text(encoding="utf-8")
    # Stale text must be GONE.
    assert "OLD STALE INSTRUCTIONS" not in final
    # Surrounding user content preserved.
    assert "User content above." in final
    assert "User content below the block." in final
    # Our refreshed block is present.
    assert JARVIS_BLOCK_BEGIN in final
    assert JARVIS_BLOCK_END in final
    # New body is in there.
    body_first_line = JARVIS_AGENT_INSTRUCTIONS_BODY.split("\n", 1)[0]
    assert body_first_line in final


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
