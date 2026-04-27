"""Tests for jarvis.lib.tailscale — peer enumeration."""
from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from jarvis.lib import tailscale


def test_detect_false_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tailscale.shutil, "which", lambda _: None)
    assert tailscale.detect() is False


def test_detect_true_when_binary_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tailscale.shutil, "which", lambda _: "/usr/local/bin/tailscale")
    assert tailscale.detect() is True


def test_list_peers_empty_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tailscale.shutil, "which", lambda _: None)
    assert tailscale.list_peers() == []


def _stub_run(stdout: str = "", returncode: int = 0, raises: Exception | None = None):
    """Build a fake subprocess.run that returns the given completed-process."""

    def _run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(
            args=args[0] if args else [], returncode=returncode, stdout=stdout, stderr=""
        )

    return _run


def test_list_peers_parses_valid_json_filters_offline_and_mobile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tailscale.shutil, "which", lambda _: "/bin/tailscale")
    payload = {
        "Peer": {
            "node-1": {
                "HostName": "mac-mini",
                "OS": "macOS",
                "Online": True,
                "TailscaleIPs": ["192.0.2.42"],
            },
            "node-2": {
                "HostName": "test-iphone",
                "OS": "iOS",
                "Online": True,
                "TailscaleIPs": ["100.64.0.5"],
            },
            "node-3": {
                "HostName": "old-server",
                "OS": "linux",
                "Online": False,
                "TailscaleIPs": ["100.64.0.6"],
            },
            "node-4": {
                "HostName": "vps",
                "OS": "linux",
                "Online": True,
                "TailscaleIPs": ["100.64.0.7"],
            },
        }
    }
    monkeypatch.setattr(tailscale.subprocess, "run", _stub_run(stdout=json.dumps(payload)))

    peers = tailscale.list_peers()
    hosts = {p.hostname for p in peers}
    assert hosts == {"mac-mini", "vps"}  # iOS and offline filtered
    macmini = next(p for p in peers if p.hostname == "mac-mini")
    assert macmini.ip == "192.0.2.42"
    assert macmini.os == "macOS"


def test_list_peers_empty_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tailscale.shutil, "which", lambda _: "/bin/tailscale")
    monkeypatch.setattr(tailscale.subprocess, "run", _stub_run(returncode=1))
    assert tailscale.list_peers() == []


def test_list_peers_empty_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tailscale.shutil, "which", lambda _: "/bin/tailscale")
    monkeypatch.setattr(tailscale.subprocess, "run", _stub_run(stdout="not json"))
    assert tailscale.list_peers() == []


def test_list_peers_empty_on_subprocess_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tailscale.shutil, "which", lambda _: "/bin/tailscale")
    monkeypatch.setattr(
        tailscale.subprocess,
        "run",
        _stub_run(raises=subprocess.SubprocessError("boom")),
    )
    assert tailscale.list_peers() == []


def test_list_peers_empty_when_no_peer_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tailscale.shutil, "which", lambda _: "/bin/tailscale")
    monkeypatch.setattr(
        tailscale.subprocess, "run", _stub_run(stdout=json.dumps({"Self": {}}))
    )
    assert tailscale.list_peers() == []
