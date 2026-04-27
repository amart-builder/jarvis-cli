"""Service control abstraction.

Hides the launchctl/systemctl difference behind a uniform API. Every other
module that needs to inspect or manipulate services goes through here.

Service names follow this convention:
- macOS: `com.<agent_name_lower>.<component>` (LaunchAgent label)
  e.g. `com.bob.gateway`, `com.bob.jarvis-memory-api`, `com.bob.neo4j`
- Linux: `jarvis-<component>.service` (systemd unit name)
  e.g. `jarvis-gateway.service`, `jarvis-memory-api.service`, `jarvis-neo4j.service`

The abstraction normalizes both worlds to a short component name (`gateway`,
`memory`, `neo4j`, `lightpanda`, `discord`, `imessage-bridge`).
"""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Literal

from jarvis.lib.platform import detect_platform

ServiceState = Literal["running", "stopped", "failed", "unknown"]

# Canonical short names used everywhere in jarvis-cli output.
# iMessage was dropped from V1 — Jarvis ships Discord-only and adds the
# EtherealOS bridge later when EtherealOS is ready.
KNOWN_COMPONENTS: list[str] = [
    "gateway",
    "memory",
    "neo4j",
    "lightpanda",
    "discord",
    "watchdog",
]


@dataclass(frozen=True)
class Service:
    """A service registered with the host's service manager."""

    component: str  # Short canonical name, e.g. "gateway"
    full_name: str  # launchctl label or systemd unit
    state: ServiceState
    pid: int | None
    last_exit_code: int | None


def list_services(agent_name_lower: str | None = None) -> list[Service]:
    """List all Jarvis services, regardless of state.

    `agent_name_lower` is required on macOS to construct LaunchAgent labels.
    On Linux it's ignored — Jarvis always installs services with the
    `jarvis-` prefix.
    """
    plat = detect_platform()
    if plat.service_manager == "launchctl":
        if not agent_name_lower:
            raise ValueError(
                "agent_name_lower required on macOS to construct LaunchAgent labels"
            )
        return [_macos_service(agent_name_lower, comp) for comp in KNOWN_COMPONENTS]
    return [_linux_service(comp) for comp in KNOWN_COMPONENTS]


def restart_service(component: str, agent_name_lower: str | None = None) -> None:
    """Restart a service by its canonical short name."""
    plat = detect_platform()
    if plat.service_manager == "launchctl":
        if not agent_name_lower:
            raise ValueError("agent_name_lower required on macOS")
        label = f"com.{agent_name_lower}.{component}"
        # bootout + bootstrap is the only reliable restart on modern macOS;
        # `kickstart -k` doesn't re-read env from the plist.
        plist = f"{plat.home}/Library/LaunchAgents/{label}.plist"
        _run(f"launchctl bootout gui/$(id -u)/{label}")
        _run(f"launchctl bootstrap gui/$(id -u) {plist}")
        return
    _run(f"systemctl restart jarvis-{component}.service")


def service_logs(component: str, lines: int = 100, follow: bool = False) -> str:
    """Return recent logs for a service. Follow mode returns nothing — caller
    should use a generator-based helper instead (TODO)."""
    plat = detect_platform()
    if plat.service_manager == "launchctl":
        # Logs live in agent's ~/Desktop/<agent>/logs/ on macOS
        # TODO: glob and tail the right file based on component
        return f"<TODO macOS log retrieval for {component}>"
    cmd = f"journalctl -u jarvis-{component}.service -n {lines}"
    if follow:
        cmd += " -f"
    return _run(cmd, capture=True)


def _macos_service(agent: str, component: str) -> Service:
    label = f"com.{agent}.{component}"
    output = _run(f"launchctl print gui/$(id -u)/{label}", capture=True, ok_codes={0, 113})
    state: ServiceState = "unknown"
    pid: int | None = None
    last_exit: int | None = None
    if "state = running" in output:
        state = "running"
    elif "Could not find service" in output:
        state = "stopped"
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("pid = "):
            try:
                pid = int(line.split("=", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("last exit code = "):
            try:
                last_exit = int(line.split("=", 1)[1].strip())
            except ValueError:
                pass
    return Service(
        component=component, full_name=label, state=state, pid=pid, last_exit_code=last_exit
    )


def _linux_service(component: str) -> Service:
    unit = f"jarvis-{component}.service"
    output = _run(
        f"systemctl show {unit} --property=ActiveState,SubState,MainPID,ExecMainStatus "
        "--no-pager",
        capture=True,
        ok_codes={0, 1, 4},
    )
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            fields[k] = v
    active = fields.get("ActiveState", "")
    state: ServiceState = "unknown"
    if active == "active":
        state = "running"
    elif active in {"inactive", "deactivating"}:
        state = "stopped"
    elif active == "failed":
        state = "failed"
    pid_str = fields.get("MainPID", "0")
    pid = int(pid_str) if pid_str.isdigit() and int(pid_str) > 0 else None
    exit_code_str = fields.get("ExecMainStatus", "")
    last_exit = int(exit_code_str) if exit_code_str.lstrip("-").isdigit() else None
    return Service(
        component=component, full_name=unit, state=state, pid=pid, last_exit_code=last_exit
    )


def _run(
    cmd: str,
    *,
    capture: bool = False,
    ok_codes: set[int] | None = None,
) -> str:
    """Run a shell command. Return stdout (if capture=True) or empty string.

    `ok_codes` lets callers accept non-zero exit codes (e.g. systemctl returns
    3 for inactive services, which is informational, not an error).
    """
    ok = ok_codes or {0}
    result = subprocess.run(  # noqa: S602 - controlled command strings
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in ok:
        raise RuntimeError(
            f"command failed (exit {result.returncode}): {shlex.quote(cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result.stdout if capture else ""
