"""macOS-specific helpers for jarvis-cli.

Wraps the launchctl + plutil + plist roundtrip patterns used in the install
workers (HARDENING Rule 18 in particular). Pure Python — uses subprocess
to call plutil and launchctl, and the json module for the actual editing
(no dependency on jq).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

GATEWAY_PLIST_RELATIVE = "Library/LaunchAgents/ai.openclaw.gateway.plist"
GATEWAY_LABEL = "ai.openclaw.gateway"
GATEWAY_HEALTH_URL = "http://127.0.0.1:18789/health"


@dataclass(frozen=True)
class AgentInstall:
    """One detected agent install on this machine."""

    name_lower: str
    secrets_dir: Path
    plist_path: Path


def find_agent_installs() -> list[AgentInstall]:
    """Glob ~/.*-secrets/ to discover Jarvis agent installs.

    Each install puts its secrets at ~/.<agent_name_lower>-secrets/. We use
    the presence of jarvis-memory.env in that dir as the signal that this is
    a real install (not some other random .*-secrets/ dir).
    """
    home = Path.home()
    plist_path = home / GATEWAY_PLIST_RELATIVE
    installs: list[AgentInstall] = []
    for secrets_dir in sorted(home.glob(".*-secrets")):
        if not secrets_dir.is_dir():
            continue
        if not (secrets_dir / "jarvis-memory.env").exists():
            continue
        # Strip leading "." and trailing "-secrets" → agent name lower
        name_lower = secrets_dir.name.removeprefix(".").removesuffix("-secrets")
        installs.append(
            AgentInstall(
                name_lower=name_lower,
                secrets_dir=secrets_dir,
                plist_path=plist_path,
            )
        )
    return installs


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env-style file. Strips quotes; ignores comments/blank lines."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        out[key] = value
    return out


def read_plist_as_json(path: Path) -> dict[str, Any]:
    """Run `plutil -convert json -o -` and return the parsed dict."""
    result = subprocess.run(
        ["plutil", "-convert", "json", "-o", "-", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def write_plist_atomic(data: dict[str, Any], path: Path) -> None:
    """Write a plist file atomically: JSON → xml1 → lint → swap.

    1. Serialize the dict to JSON in a temp file
    2. plutil -convert xml1 to a second temp file (plists on disk are xml1)
    3. plutil -lint the new file (verify it's a valid plist)
    4. Atomic move into place

    Raises subprocess.CalledProcessError if any plutil step fails. Caller
    is responsible for backing up the existing file before calling this.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp_json:
        json.dump(data, tmp_json)
        tmp_json_path = tmp_json.name

    tmp_plist_handle = tempfile.NamedTemporaryFile(suffix=".plist", delete=False)
    tmp_plist_path = tmp_plist_handle.name
    tmp_plist_handle.close()

    try:
        subprocess.run(
            ["plutil", "-convert", "xml1", "-o", tmp_plist_path, tmp_json_path],
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["plutil", "-lint", tmp_plist_path],
            capture_output=True,
            text=True,
            check=True,
        )
        # Atomic move (same filesystem since both temps are in /var/folders)
        shutil.move(tmp_plist_path, path)
    finally:
        for f in (tmp_json_path,):
            try:
                os.unlink(f)
            except FileNotFoundError:
                pass
        # tmp_plist_path is gone after shutil.move on success; clean up on failure
        if Path(tmp_plist_path).exists():
            os.unlink(tmp_plist_path)


def backup_plist(plist_path: Path, suffix: str) -> Path:
    """Copy plist to a timestamped backup. Returns the backup path."""
    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = plist_path.with_suffix(f".plist.bak.{suffix}-{timestamp}")
    shutil.copy2(plist_path, backup)
    return backup


def launchctl_reload(plist_path: Path, label: str) -> None:
    """bootout + bootstrap a LaunchAgent.

    bootout returns 113 ("Could not find specified service") if the service
    isn't loaded — we tolerate that. bootstrap is the load step and must
    succeed.

    NOTE: kickstart -k does NOT re-read env vars from the plist; only
    bootout + bootstrap does. This matters for HARDENING Rule 18.
    """
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{label}"],
        capture_output=True,
        check=False,  # 113 is acceptable
    )
    time.sleep(2)
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
        capture_output=True,
        text=True,
        check=True,
    )


def wait_for_endpoint(
    url: str, *, timeout_total: float = 30.0, interval: float = 2.0
) -> bool:
    """Poll a URL until it returns 2xx or timeout. Returns True if healthy."""
    deadline = time.monotonic() + timeout_total
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=interval)
            if 200 <= resp.status_code < 300:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(interval)
    return False
