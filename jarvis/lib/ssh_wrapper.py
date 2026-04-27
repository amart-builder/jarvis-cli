"""SSH transport for jarvis-cli remote-mode commands.

Stdlib `subprocess` + the system `ssh` binary. No paramiko, no fabric.

This buys us:
- the user's existing `~/.ssh/config` (jumphosts, ProxyCommand, multiplexing,
  IdentityAgent, etc.) is honored automatically
- whatever SSH version they trust is the one we use
- zero new dependencies
- familiar errors when something breaks (any user who's ever ssh'd anywhere
  recognizes "Permission denied (publickey)")

Two main entry points:
- `run(cfg, remote_cmd, ...)` — fire-and-forget invocation
- `test_reachability(cfg)` — categorize a probe so onboarding can branch
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from jarvis.lib.setup_config import SetupConfig

log = logging.getLogger("jarvis.ssh_wrapper")

# Sentinel echoed by the reachability probe so we know our command really ran
# (vs. the SSH connection succeeding but the remote shell saying nothing).
REACHABILITY_SENTINEL = "jarvis-onboard-ssh-ok"


class ReachabilityResult(StrEnum):
    OK = "ok"
    CONNECTION_REFUSED = "connection-refused"
    TIMEOUT = "timeout"
    AUTH_FAILED = "auth-failed"
    HOST_KEY_UNKNOWN = "host-key-unknown"
    OTHER = "other"


@dataclass(frozen=True)
class ReachabilityReport:
    """Result of a reachability probe — branch on this in onboarding."""

    result: ReachabilityResult
    stderr: str
    exit_code: int


def build_ssh_args(
    cfg: SetupConfig,
    remote_cmd: str,
    *,
    env: dict[str, str] | None = None,
    batch_mode: bool = False,
    extra_options: list[str] | None = None,
) -> list[str]:
    """Build the argv for an `ssh` invocation against `cfg`.

    `remote_cmd` is the literal string the remote shell should run. We DON'T
    re-quote it here — caller is responsible for ensuring it's well-formed
    (typically `build_remote_invocation` in dispatch.py does this via
    `shlex.quote` per arg).

    `env` becomes a `KEY=value KEY=value cmd` prefix on the remote side.

    `batch_mode=True` adds `-o BatchMode=yes -o ConnectTimeout=5` for the
    reachability probe (fail fast on missing keys instead of prompting).
    """
    if cfg.mode != "remote" or not cfg.host or not cfg.user:
        raise ValueError("build_ssh_args: cfg is not a valid remote setup")

    args: list[str] = ["ssh"]
    if batch_mode:
        args += ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    if cfg.port != 22:
        args += ["-p", str(cfg.port)]
    if cfg.identity_file is not None:
        args += ["-i", str(_expand_path(cfg.identity_file))]
    if extra_options:
        args += list(extra_options)
    args.append(f"{cfg.user}@{cfg.host}")

    if env:
        env_prefix = " ".join(
            f"{k}={shlex.quote(v)}" for k, v in env.items()
        )
        args.append(f"{env_prefix} {remote_cmd}")
    else:
        args.append(remote_cmd)
    return args


def run(
    cfg: SetupConfig,
    remote_cmd: str,
    *,
    env: dict[str, str] | None = None,
    capture: bool = False,
    stdin: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `remote_cmd` over SSH, return CompletedProcess.

    `capture=True` collects stdout/stderr (text); `False` lets them stream
    to the user's terminal. `stdin` is fed to the remote command's stdin
    (used by the `--yes` fallback that pipes `y\\n` for state-change cmds).
    """
    args = build_ssh_args(cfg, remote_cmd, env=env)
    return subprocess.run(  # noqa: S603 — argv list, not shell=True
        args,
        check=False,
        capture_output=capture,
        text=True,
        input=stdin,
        timeout=timeout,
    )


def test_reachability(cfg: SetupConfig) -> ReachabilityReport:
    """Probe whether SSH key-auth works to `cfg.host`.

    Runs `ssh -o BatchMode=yes -o ConnectTimeout=5 user@host -p port
    'echo <SENTINEL>'`. Categorizes the result so `jarvis onboard` can
    branch (OK / CONNECTION_REFUSED / TIMEOUT / AUTH_FAILED / HOST_KEY_UNKNOWN).

    BatchMode disables interactive prompts — so missing-key scenarios fail
    fast (exit 255, "Permission denied") rather than hanging on a password
    prompt.
    """
    args = build_ssh_args(
        cfg,
        f"echo {REACHABILITY_SENTINEL}",
        batch_mode=True,
    )
    try:
        result = subprocess.run(  # noqa: S603
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        return ReachabilityReport(
            result=ReachabilityResult.TIMEOUT,
            stderr=str(exc) or "ssh probe timed out",
            exit_code=124,
        )
    except OSError as exc:
        return ReachabilityReport(
            result=ReachabilityResult.OTHER,
            stderr=f"ssh launch error: {exc}",
            exit_code=-1,
        )

    return _categorize(result)


def keyscan_and_trust(host: str, port: int = 22) -> str | None:
    """Run `ssh-keyscan -p port host`, return the host-key line.

    Caller is responsible for showing the fingerprint to the user, getting
    confirmation, and appending to `~/.ssh/known_hosts`. Returns None on
    failure.
    """
    args = ["ssh-keyscan"]
    if port != 22:
        args += ["-p", str(port)]
    args += [host]
    try:
        result = subprocess.run(  # noqa: S603
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.debug("ssh-keyscan failed: %s", exc)
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


# --- internals --------------------------------------------------------------


def _expand_path(p: Path) -> Path:
    return p.expanduser()


def _categorize(result: subprocess.CompletedProcess[str]) -> ReachabilityReport:
    """Map an ssh CompletedProcess to a ReachabilityReport."""
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    code = result.returncode

    if code == 0 and REACHABILITY_SENTINEL in stdout:
        return ReachabilityReport(ReachabilityResult.OK, stderr, code)

    lower = stderr.lower()
    if "connection refused" in lower:
        return ReachabilityReport(ReachabilityResult.CONNECTION_REFUSED, stderr, code)
    if "operation timed out" in lower or "connection timed out" in lower:
        return ReachabilityReport(ReachabilityResult.TIMEOUT, stderr, code)
    if "no route to host" in lower:
        return ReachabilityReport(ReachabilityResult.CONNECTION_REFUSED, stderr, code)
    if "could not resolve hostname" in lower:
        return ReachabilityReport(ReachabilityResult.CONNECTION_REFUSED, stderr, code)
    if "permission denied" in lower or "publickey" in lower:
        return ReachabilityReport(ReachabilityResult.AUTH_FAILED, stderr, code)
    if "host key verification failed" in lower or "no matching host key" in lower:
        return ReachabilityReport(ReachabilityResult.HOST_KEY_UNKNOWN, stderr, code)
    return ReachabilityReport(ReachabilityResult.OTHER, stderr, code)
