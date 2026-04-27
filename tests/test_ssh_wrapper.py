"""Tests for jarvis.lib.ssh_wrapper — argv composition and stderr categorization."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jarvis.lib import ssh_wrapper
from jarvis.lib.setup_config import SetupConfig
from jarvis.lib.ssh_wrapper import (
    REACHABILITY_SENTINEL,
    ReachabilityResult,
    _categorize,
    build_ssh_args,
)


def _remote(host: str = "192.0.2.42", user: str = "alex", **kw) -> SetupConfig:
    return SetupConfig(mode="remote", host=host, user=user, **kw)


def test_build_ssh_args_rejects_local_cfg() -> None:
    cfg = SetupConfig(mode="local")
    with pytest.raises(ValueError):
        build_ssh_args(cfg, "echo hi")


def test_build_ssh_args_rejects_remote_without_host() -> None:
    cfg = SetupConfig(mode="remote", user="alex")
    with pytest.raises(ValueError):
        build_ssh_args(cfg, "echo hi")


def test_build_ssh_args_minimal_remote() -> None:
    args = build_ssh_args(_remote(), "echo hi")
    assert args[0] == "ssh"
    assert "alex@192.0.2.42" in args
    assert args[-1] == "echo hi"
    assert "-p" not in args  # default port 22 isn't included
    assert "-i" not in args


def test_build_ssh_args_includes_port_when_nondefault() -> None:
    args = build_ssh_args(_remote(port=2222), "x")
    assert "-p" in args
    assert args[args.index("-p") + 1] == "2222"


def test_build_ssh_args_includes_identity_file() -> None:
    args = build_ssh_args(
        _remote(identity_file=Path("/home/alex/.ssh/id_special")), "x"
    )
    assert "-i" in args
    assert args[args.index("-i") + 1] == "/home/alex/.ssh/id_special"


def test_build_ssh_args_batch_mode_adds_options() -> None:
    args = build_ssh_args(_remote(), "x", batch_mode=True)
    assert "BatchMode=yes" in args
    assert "ConnectTimeout=5" in args


def test_build_ssh_args_env_prefix() -> None:
    args = build_ssh_args(_remote(), "jarvis status", env={"JARVIS_HOST": "1.2.3.4"})
    assert args[-1] == "JARVIS_HOST=1.2.3.4 jarvis status"


def test_build_ssh_args_env_prefix_quotes_special_chars() -> None:
    args = build_ssh_args(_remote(), "jarvis status", env={"X": "a b"})
    # shlex.quote wraps "a b" in single quotes.
    assert args[-1] == "X='a b' jarvis status"


def test_build_ssh_args_extra_options_pass_through() -> None:
    args = build_ssh_args(_remote(), "x", extra_options=["-o", "StrictHostKeyChecking=no"])
    assert "StrictHostKeyChecking=no" in args


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_categorize_ok_when_sentinel_present() -> None:
    rep = _categorize(_proc(0, stdout=f"{REACHABILITY_SENTINEL}\n"))
    assert rep.result == ReachabilityResult.OK


def test_categorize_connection_refused() -> None:
    rep = _categorize(_proc(255, stderr="ssh: connect to host x port 22: Connection refused"))
    assert rep.result == ReachabilityResult.CONNECTION_REFUSED


def test_categorize_no_route_to_host_is_connection_refused() -> None:
    rep = _categorize(_proc(255, stderr="ssh: connect to host: No route to host"))
    assert rep.result == ReachabilityResult.CONNECTION_REFUSED


def test_categorize_unresolvable_hostname_is_connection_refused() -> None:
    rep = _categorize(_proc(255, stderr="ssh: Could not resolve hostname foo.bar"))
    assert rep.result == ReachabilityResult.CONNECTION_REFUSED


def test_categorize_timeout() -> None:
    rep = _categorize(_proc(255, stderr="ssh: connect to host x port 22: Operation timed out"))
    assert rep.result == ReachabilityResult.TIMEOUT


def test_categorize_auth_failed_permission_denied() -> None:
    rep = _categorize(_proc(255, stderr="alex@host: Permission denied (publickey)."))
    assert rep.result == ReachabilityResult.AUTH_FAILED


def test_categorize_host_key_unknown() -> None:
    rep = _categorize(_proc(255, stderr="Host key verification failed."))
    assert rep.result == ReachabilityResult.HOST_KEY_UNKNOWN


def test_categorize_other_for_unrecognized_stderr() -> None:
    rep = _categorize(_proc(255, stderr="something we've never seen"))
    assert rep.result == ReachabilityResult.OTHER


def test_test_reachability_returns_timeout_on_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=15)

    monkeypatch.setattr(ssh_wrapper.subprocess, "run", _raise_timeout)
    rep = ssh_wrapper.test_reachability(_remote())
    assert rep.result == ReachabilityResult.TIMEOUT
    assert rep.exit_code == 124
