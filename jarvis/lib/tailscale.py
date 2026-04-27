"""Tailscale auto-detection for `jarvis onboard`.

If the user has Tailscale installed, we can enumerate their tailnet peers
and present them as a numbered list ("which one is your OpenClaw machine?").
If not, the caller falls through to manual host entry.

We never raise on Tailscale failures — onboarding should not break because
of an unrelated Tailscale issue. List comes back empty, caller falls through.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger("jarvis.tailscale")

# Mobile devices are never an OpenClaw appliance — filter them out.
_EXCLUDED_OS_VALUES = frozenset({"iOS", "tvOS"})


@dataclass(frozen=True)
class Peer:
    hostname: str
    ip: str
    os: str  # "linux", "macOS", "windows", "android", etc.


def detect() -> bool:
    """True iff the `tailscale` binary is on PATH."""
    return shutil.which("tailscale") is not None


def list_peers() -> list[Peer]:
    """Return online, non-mobile peers from `tailscale status --json`.

    Empty list on any failure (Tailscale absent, command non-zero, JSON
    parse error, no eligible peers). Never raises.
    """
    if not detect():
        return []
    try:
        result = subprocess.run(  # noqa: S603 — argv list, not shell=True
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.debug("tailscale status failed: %s", exc)
        return []
    if result.returncode != 0:
        log.debug("tailscale status non-zero: %s", result.stderr.strip())
        return []
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        log.debug("tailscale status returned non-JSON: %s", exc)
        return []

    peer_map = status.get("Peer") or {}
    peers: list[Peer] = []
    for entry in peer_map.values():
        if not entry.get("Online", False):
            continue
        os_name = str(entry.get("OS", "")).strip()
        if os_name in _EXCLUDED_OS_VALUES:
            continue
        ips = entry.get("TailscaleIPs") or []
        if not ips:
            continue
        hostname = str(entry.get("HostName", "") or entry.get("DNSName", "")).strip()
        if not hostname:
            hostname = ips[0]
        peers.append(Peer(hostname=hostname, ip=str(ips[0]), os=os_name))
    return peers
