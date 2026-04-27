"""Tests for jarvis.lib.dispatch — laptop → remote command forwarding."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from jarvis.lib import dispatch, setup_config
from jarvis.lib.dispatch import (
    _has_yes_flag,
    build_remote_invocation,
    dispatch_remote,
    should_dispatch_remote,
)
from jarvis.lib.setup_config import SetupConfig


@pytest.fixture
def patched_setup_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / ".jarvis" / "setup.toml"
    monkeypatch.setattr(setup_config, "SETUP_PATH", target)
    return target


def test_should_dispatch_remote_returns_none_with_no_setup(
    patched_setup_path: Path,
) -> None:
    assert should_dispatch_remote() is None


def test_should_dispatch_remote_returns_none_for_local_mode(
    patched_setup_path: Path,
) -> None:
    setup_config.save(SetupConfig(mode="local"))
    assert should_dispatch_remote() is None


def test_should_dispatch_remote_returns_cfg_for_valid_remote(
    patched_setup_path: Path,
) -> None:
    setup_config.save(SetupConfig(mode="remote", host="192.0.2.42", user="alex"))
    cfg = should_dispatch_remote()
    assert cfg is not None
    assert cfg.host == "192.0.2.42"
    assert cfg.user == "alex"


def test_has_yes_flag_detects_long_form() -> None:
    assert _has_yes_flag(["restart", "--all", "--yes"]) is True


def test_has_yes_flag_detects_short_form() -> None:
    assert _has_yes_flag(["restart", "--all", "-y"]) is True


def test_has_yes_flag_detects_equals_form() -> None:
    assert _has_yes_flag(["--yes=true", "restart"]) is True


def test_has_yes_flag_returns_false_when_absent() -> None:
    assert _has_yes_flag(["restart", "memory"]) is False


def test_build_remote_invocation_quotes_safe_args() -> None:
    cmd = build_remote_invocation(["status", "--json"])
    assert cmd == "jarvis status --json"


def test_build_remote_invocation_quotes_special_chars() -> None:
    cmd = build_remote_invocation(["docs", "search", "rule 18"])
    # shlex.quote wraps "rule 18" in single quotes.
    assert "'rule 18'" in cmd


def test_build_remote_invocation_adds_env_prefix() -> None:
    cmd = build_remote_invocation(["status"], env={"JARVIS_HOST": "1.2.3.4"})
    assert cmd == "JARVIS_HOST=1.2.3.4 jarvis status"


def _stub_ssh_run(captured: dict, returncode: int = 0):
    """ssh_wrapper.run stub that records the args passed and returns a stub
    CompletedProcess with the supplied returncode."""

    def _run(cfg, remote_cmd, *, env=None, capture=False, stdin=None, timeout=None):
        captured["remote_cmd"] = remote_cmd
        captured["env"] = env
        captured["capture"] = capture
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr="")

    return _run


def test_dispatch_remote_appends_yes_when_ensure_yes(
    patched_setup_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_config.save(SetupConfig(mode="remote", host="h", user="u"))
    cfg = should_dispatch_remote()
    assert cfg is not None

    monkeypatch.setattr(sys, "argv", ["jarvis", "restart", "--all"])
    captured: dict = {}
    monkeypatch.setattr(dispatch.ssh_wrapper, "run", _stub_ssh_run(captured))

    rc = dispatch_remote(cfg, ensure_yes=True)
    assert rc == 0
    assert captured["remote_cmd"].endswith("--yes")
    assert "jarvis restart --all --yes" == captured["remote_cmd"]


def test_dispatch_remote_does_not_double_yes(
    patched_setup_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_config.save(SetupConfig(mode="remote", host="h", user="u"))
    cfg = should_dispatch_remote()
    assert cfg is not None

    monkeypatch.setattr(sys, "argv", ["jarvis", "restart", "--all", "-y"])
    captured: dict = {}
    monkeypatch.setattr(dispatch.ssh_wrapper, "run", _stub_ssh_run(captured))

    dispatch_remote(cfg, ensure_yes=True)
    # Only one '-y' (or '--yes') in the forwarded command, not two.
    pieces = captured["remote_cmd"].split()
    yes_tokens = [p for p in pieces if p in {"--yes", "-y"} or p.startswith("--yes=")]
    assert len(yes_tokens) == 1


def test_dispatch_remote_passes_returncode(
    patched_setup_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_config.save(SetupConfig(mode="remote", host="h", user="u"))
    cfg = should_dispatch_remote()
    assert cfg is not None

    monkeypatch.setattr(sys, "argv", ["jarvis", "status"])
    captured: dict = {}
    monkeypatch.setattr(dispatch.ssh_wrapper, "run", _stub_ssh_run(captured, returncode=42))

    rc = dispatch_remote(cfg)
    assert rc == 42


def test_dispatch_remote_forwards_jarvis_host_env(
    patched_setup_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_config.save(SetupConfig(mode="remote", host="h", user="u"))
    cfg = should_dispatch_remote()
    assert cfg is not None

    monkeypatch.setenv("JARVIS_HOST", "10.0.0.5")
    monkeypatch.setenv("JARVIS_DOCS_TTL", "0")
    monkeypatch.setattr(sys, "argv", ["jarvis", "context"])
    captured: dict = {}
    monkeypatch.setattr(dispatch.ssh_wrapper, "run", _stub_ssh_run(captured))

    dispatch_remote(cfg)
    assert captured["env"] == {"JARVIS_HOST": "10.0.0.5", "JARVIS_DOCS_TTL": "0"}


def test_dispatch_remote_omits_unset_env_vars(
    patched_setup_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_config.save(SetupConfig(mode="remote", host="h", user="u"))
    cfg = should_dispatch_remote()
    assert cfg is not None

    monkeypatch.delenv("JARVIS_HOST", raising=False)
    monkeypatch.delenv("JARVIS_DOCS_TTL", raising=False)
    monkeypatch.setattr(sys, "argv", ["jarvis", "context"])
    captured: dict = {}
    monkeypatch.setattr(dispatch.ssh_wrapper, "run", _stub_ssh_run(captured))

    dispatch_remote(cfg)
    assert captured["env"] == {}
