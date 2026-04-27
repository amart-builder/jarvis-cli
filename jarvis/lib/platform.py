"""Platform detection.

The CLI runs on both macOS (existing Mac mini installs) and Linux (the new
Beelink/VPS Jarvis appliance). Most operations branch on platform — this
module is the single source of truth for that branching.
"""
from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

ServiceManager = Literal["launchctl", "systemctl"]
OSName = Literal["macos", "linux", "unknown"]


@dataclass(frozen=True)
class Platform:
    """Detected runtime platform facts."""

    os_name: OSName
    os_version: str
    service_manager: ServiceManager
    home: Path
    log_dir: Path  # Where Jarvis components write their logs
    secrets_dir: Path  # Where install-time secrets live (e.g. JARVIS_API_BEARER_TOKEN)
    is_apple_silicon: bool


@lru_cache(maxsize=1)
def detect_platform() -> Platform:
    """Detect the host platform once and cache.

    On macOS we expect launchctl + a `~/.<agent>-secrets/` directory and
    LaunchAgent plists under `~/Library/LaunchAgents/`. On Linux we expect
    systemctl + `/etc/jarvis/` for secrets and `/var/log/jarvis/` for logs.
    """
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return Platform(
            os_name="macos",
            os_version=platform.mac_ver()[0] or "unknown",
            service_manager="launchctl",
            home=home,
            log_dir=_find_macos_log_dir(home),
            secrets_dir=_find_macos_secrets_dir(home),
            is_apple_silicon=platform.machine() == "arm64",
        )
    if system == "Linux":
        if not shutil.which("systemctl"):
            raise RuntimeError(
                "systemctl not found. jarvis-cli on Linux requires systemd. "
                "We don't currently support Linux distros without systemd."
            )
        return Platform(
            os_name="linux",
            os_version=_linux_version(),
            service_manager="systemctl",
            home=home,
            log_dir=Path("/var/log/jarvis"),
            secrets_dir=Path("/etc/jarvis"),
            is_apple_silicon=False,
        )
    return Platform(
        os_name="unknown",
        os_version=platform.release(),
        service_manager="systemctl",  # arbitrary default; will fail loud at first call
        home=home,
        log_dir=home / ".jarvis" / "logs",
        secrets_dir=home / ".jarvis" / "secrets",
        is_apple_silicon=False,
    )


def _find_macos_log_dir(home: Path) -> Path:
    """On macOS the agent's log dir lives at ~/Desktop/<AgentName>/logs/.

    Without knowing the agent name yet we return ~/Desktop and let callers
    glob. A later config file (~/.jarvis/config.toml) can override.
    """
    desktop = home / "Desktop"
    return desktop


def _find_macos_secrets_dir(home: Path) -> Path:
    """On macOS the secrets dir is ~/.<agent_name_lower>-secrets/.

    Same caveat as logs — without the agent name we return $HOME and let
    callers glob `.*-secrets`.
    """
    return home


def _linux_version() -> str:
    """Read /etc/os-release for a friendly Linux version string."""
    try:
        os_release = Path("/etc/os-release").read_text(encoding="utf-8")
        fields = dict(
            line.split("=", 1)
            for line in os_release.splitlines()
            if "=" in line and not line.startswith("#")
        )
        pretty = fields.get("PRETTY_NAME", "").strip('"')
        return pretty or platform.release()
    except OSError:
        return platform.release()
