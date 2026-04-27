"""Tests for jarvis.commands.onboard — entry-point gates."""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from jarvis.cli import app
from jarvis.commands import onboard as onboard_cmd
from jarvis.lib import setup_config
from jarvis.lib.setup_config import SetupConfig


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def patched_setup_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / ".jarvis" / "setup.toml"
    monkeypatch.setattr(setup_config, "SETUP_PATH", target)
    monkeypatch.setattr(onboard_cmd, "SETUP_PATH", target)
    return target


def test_non_interactive_flag_is_refused(runner: CliRunner) -> None:
    result = runner.invoke(app, ["onboard", "--non-interactive"])
    assert result.exit_code == onboard_cmd.EXIT_MISSING_PREREQUISITES
    assert "--non-interactive" in result.stdout


def test_missing_ssh_binary_exits_missing_prereqs(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(onboard_cmd, "_has_ssh_binary", lambda: False)
    result = runner.invoke(app, ["onboard"])
    assert result.exit_code == onboard_cmd.EXIT_MISSING_PREREQUISITES
    assert "ssh" in result.stdout.lower()


def test_existing_setup_short_circuits_to_verify(
    runner: CliRunner,
    patched_setup_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a valid remote setup exists and --reset is not passed, onboard
    should call _maybe_verify_existing instead of running the interview."""
    setup_config.save(SetupConfig(mode="remote", host="h", user="u"))

    called = {"verify": False, "interview": False}

    def fake_verify(console, cfg):
        called["verify"] = True

    def fake_interview(console):
        called["interview"] = True
        return SetupConfig(mode="remote", host="x", user="x")

    monkeypatch.setattr(onboard_cmd, "_has_ssh_binary", lambda: True)
    monkeypatch.setattr(onboard_cmd, "_maybe_verify_existing", fake_verify)
    monkeypatch.setattr(onboard_cmd, "_run_interview", fake_interview)

    result = runner.invoke(app, ["onboard"])
    assert result.exit_code == 0
    assert called["verify"] is True
    assert called["interview"] is False


def test_reset_backs_up_then_runs_interview(
    runner: CliRunner,
    patched_setup_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--reset` with an existing setup should call backup() and run the
    interview."""
    setup_config.save(SetupConfig(mode="remote", host="orig", user="orig"))

    called = {"backup": False, "interview": False, "save": False}

    def fake_backup() -> Path:
        called["backup"] = True
        return patched_setup_path.parent / "setup.toml.bak-test"

    def fake_interview(console):
        called["interview"] = True
        return SetupConfig(mode="remote", host="new", user="new")

    def fake_save(cfg):
        called["save"] = True

    monkeypatch.setattr(onboard_cmd, "_has_ssh_binary", lambda: True)
    monkeypatch.setattr(onboard_cmd.setup_config, "backup", fake_backup)
    monkeypatch.setattr(onboard_cmd, "_run_interview", fake_interview)
    monkeypatch.setattr(onboard_cmd.setup_config, "save", fake_save)

    result = runner.invoke(app, ["onboard", "--reset"])
    assert result.exit_code == 0
    assert called["backup"] is True
    assert called["interview"] is True
    assert called["save"] is True


def test_help_does_not_require_ssh(runner: CliRunner) -> None:
    """`jarvis onboard --help` should render even on a machine without ssh."""
    result = runner.invoke(app, ["onboard", "--help"])
    assert result.exit_code == 0
    assert "onboard" in result.stdout.lower() or "ssh" in result.stdout.lower()


def test_escalate_exits_with_two_failure_code() -> None:
    """_escalate raises typer.Exit(EXIT_TWO_FAILURE_ESCALATION)."""
    import typer
    from rich.console import Console

    console = Console()
    with pytest.raises(typer.Exit) as exc_info:
        onboard_cmd._escalate(console, "test step", "raw stderr")
    assert exc_info.value.exit_code == onboard_cmd.EXIT_TWO_FAILURE_ESCALATION
