"""Tests confirming state-change commands honor `--yes` (no prompt) in local
mode AND that the dispatch prologue confirms locally then SSHes."""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from jarvis.cli import app
from jarvis.commands import recover as recover_cmd
from jarvis.commands import repair as repair_cmd
from jarvis.commands import restart as restart_cmd
from jarvis.lib import dispatch, setup_config
from jarvis.lib.setup_config import SetupConfig


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def patched_setup_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / ".jarvis" / "setup.toml"
    monkeypatch.setattr(setup_config, "SETUP_PATH", target)
    return target


def test_recover_yes_does_not_prompt_in_local_mode(
    runner: CliRunner, patched_setup_path: Path
) -> None:
    """No setup.toml → local mode → --yes skips the prompt."""
    result = runner.invoke(app, ["recover", "--yes", "--json"])
    assert result.exit_code == 0
    assert "TODO" in result.stdout  # stub payload


def test_repair_memory_yes_does_not_prompt(
    runner: CliRunner, patched_setup_path: Path
) -> None:
    result = runner.invoke(app, ["repair", "memory", "--yes", "--json"])
    assert result.exit_code == 0


def test_repair_channels_yes_does_not_prompt(
    runner: CliRunner, patched_setup_path: Path
) -> None:
    result = runner.invoke(app, ["repair", "channels", "--yes", "--json"])
    assert result.exit_code == 0


def test_restart_all_without_yes_prompts(
    runner: CliRunner, patched_setup_path: Path
) -> None:
    """`restart --all` without --yes shows the [y/N] prompt; declining exits 1."""
    # We respond with empty input → defaults to N → exit code 1.
    result = runner.invoke(app, ["restart", "--all"], input="\n")
    assert result.exit_code == 1


def test_remote_state_change_calls_local_confirm_and_dispatches(
    runner: CliRunner,
    patched_setup_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In remote mode, state-change cmd should:
    - prompt locally first
    - call dispatch_remote(ensure_yes=True) on confirm
    - skip dispatch on decline
    """
    setup_config.save(SetupConfig(mode="remote", host="h", user="u"))

    captured: dict = {"called": False, "ensure_yes": None}

    def fake_dispatch(cfg, *, ensure_yes=False):
        captured["called"] = True
        captured["ensure_yes"] = ensure_yes
        return 0

    monkeypatch.setattr(restart_cmd, "dispatch_remote", fake_dispatch)
    monkeypatch.setattr(recover_cmd, "dispatch_remote", fake_dispatch)
    monkeypatch.setattr(repair_cmd, "dispatch_remote", fake_dispatch)

    # Confirm with "y\n" — should call dispatch with ensure_yes=True.
    result = runner.invoke(app, ["recover"], input="y\n")
    assert result.exit_code == 0
    assert captured["called"] is True
    assert captured["ensure_yes"] is True


def test_remote_state_change_decline_skips_dispatch(
    runner: CliRunner,
    patched_setup_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declining the local prompt should NOT call dispatch_remote."""
    setup_config.save(SetupConfig(mode="remote", host="h", user="u"))

    called = {"dispatch": False}

    def fake_dispatch(cfg, *, ensure_yes=False):
        called["dispatch"] = True
        return 0

    monkeypatch.setattr(restart_cmd, "dispatch_remote", fake_dispatch)

    # "n\n" declines — dispatch should NOT be called.
    result = runner.invoke(app, ["restart", "--all"], input="n\n")
    assert result.exit_code == 1
    assert called["dispatch"] is False


def test_remote_readonly_dispatches_without_prompting(
    runner: CliRunner,
    patched_setup_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read-only commands should dispatch immediately, no prompt at all."""
    setup_config.save(SetupConfig(mode="remote", host="h", user="u"))

    from jarvis.commands import status as status_cmd

    called = {"dispatch": False}

    def fake_dispatch(cfg, *, ensure_yes=False):
        called["dispatch"] = True
        return 0

    monkeypatch.setattr(status_cmd, "dispatch_remote", fake_dispatch)

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert called["dispatch"] is True
