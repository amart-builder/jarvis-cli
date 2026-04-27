"""Local-vs-remote dispatch for jarvis-cli commands.

When `~/.jarvis/setup.toml` says `mode = "remote"`, every read-only command
on the laptop becomes `ssh user@host 'jarvis <same command>'`, with stdout
streamed directly to the user's terminal and exit code propagated.

State-change commands (restart, repair, recover) confirm on the LAPTOP first
(preserving v0.3.0 muscle memory) and then dispatch with `--yes` appended so
the remote doesn't re-prompt over a non-interactive SSH session.

Implementation: forward `sys.argv[1:]` verbatim. This means we don't need
per-command flag serializers — any new flag added to a v0.3.0 command
"just works" in remote mode without touching this file.
"""
from __future__ import annotations

import os
import shlex
import sys

from jarvis.lib import ssh_wrapper
from jarvis.lib.setup_config import SetupConfig
from jarvis.lib.setup_config import load as load_setup

# Env vars on the laptop that should be forwarded to the remote `jarvis`
# invocation. JARVIS_HOST keeps its v0.3.0 semantics ("which appliance API
# endpoint to hit") — but evaluated on the remote side. JARVIS_DOCS_TTL
# controls the docs-cache TTL on whichever side the docs run on.
FORWARD_ENV_VARS = ("JARVIS_HOST", "JARVIS_DOCS_TTL")

# Non-interactive ssh sessions don't source ~/.zshrc (and on macOS the
# brew/pipx PATH lives there, not in ~/.zshenv). Without this prefix, the
# remote `jarvis` invocation can't find itself: pipx installs to
# ~/.local/bin (Linux + macOS) and brew sometimes drops binaries in
# /opt/homebrew/bin (Apple Silicon) or /usr/local/bin (Intel). The
# embedded $HOME / $PATH refs are expanded by the REMOTE shell, so we
# pass them as a literal-string prefix in remote_cmd rather than via the
# env mechanism (which would shlex-quote them).
REMOTE_PATH_PREFIX = (
    'PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH" '
)


def should_dispatch_remote() -> SetupConfig | None:
    """Return the SetupConfig if we should SSH this command, else None.

    None means "fall through to the v0.3.0 local logic" — used as the
    sentinel by every wired command.
    """
    cfg = load_setup()
    if cfg is None or cfg.mode != "remote":
        return None
    if not cfg.host or not cfg.user:
        return None
    return cfg


def dispatch_remote(
    cfg: SetupConfig,
    *,
    ensure_yes: bool = False,
) -> int:
    """SSH the current invocation to the remote and return its exit code.

    `ensure_yes=True` is for state-change commands: after the laptop has
    confirmed locally, we tack on `--yes` so the remote doesn't re-prompt
    on the non-interactive SSH session.
    """
    args = list(sys.argv[1:])
    if ensure_yes and not _has_yes_flag(args):
        args.append("--yes")

    remote_cmd = REMOTE_PATH_PREFIX + "jarvis " + " ".join(shlex.quote(a) for a in args)
    env = _forwarded_env()
    result = ssh_wrapper.run(cfg, remote_cmd, env=env, capture=False)
    return result.returncode


def build_remote_invocation(args: list[str], env: dict[str, str] | None = None) -> str:
    """Public for tests: render the exact remote command string.

    Equivalent to what `dispatch_remote` ends up sending over SSH (minus the
    forwarded-env prefix, which `ssh_wrapper.build_ssh_args` injects on its
    end). Includes the REMOTE_PATH_PREFIX so non-interactive ssh sessions
    can find pipx-installed binaries on macOS/Linux.
    """
    quoted = " ".join(shlex.quote(a) for a in args)
    cmd = f"{REMOTE_PATH_PREFIX}jarvis {quoted}"
    if env:
        prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
        return f"{prefix} {cmd}"
    return cmd


# --- internals --------------------------------------------------------------


def _has_yes_flag(args: list[str]) -> bool:
    """True if the user already passed --yes / -y (so we don't double it)."""
    for a in args:
        if a == "--yes" or a == "-y" or a.startswith("--yes="):
            return True
    return False


def _forwarded_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for k in FORWARD_ENV_VARS:
        v = os.environ.get(k)
        if v:
            out[k] = v
    return out
