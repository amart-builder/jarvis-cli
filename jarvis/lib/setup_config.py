"""Read/write `~/.jarvis/setup.toml` — the laptop-side mode config.

When the file is absent, jarvis-cli is in "local mode" — every command
behaves exactly as v0.3.0 (run locally, no SSH). When present with
`mode = "remote"`, the dispatch layer (jarvis.lib.dispatch) routes
read-only commands through SSH to the configured host. State-change
commands confirm on the laptop first, then SSH the action with `--yes`.

Schema:
    schema_version = 1
    [appliance]
    mode = "remote"                       # "local" | "remote"
    host = "100.x.x.x"                    # IP or hostname
    user = "alex"                         # SSH user
    port = 22                             # optional, default 22
    identity_file = "~/.ssh/id_ed25519"   # optional; SSH default key search applies when absent

Mode 0600 on the file. Schema version exists so future v0.5+ can extend
the shape without breaking older clients.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from jarvis.lib._tomlwrite import write_toml

log = logging.getLogger("jarvis.setup_config")

SETUP_PATH: Path = Path.home() / ".jarvis" / "setup.toml"
CURRENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SetupConfig:
    """Parsed contents of `~/.jarvis/setup.toml`.

    `mode == "local"` is semantically identical to the file being absent —
    both mean "run commands locally as v0.3.0 did." The dataclass exists
    primarily for the remote case.
    """

    mode: str  # "local" | "remote"
    host: str | None = None
    user: str | None = None
    port: int = 22
    identity_file: Path | None = None
    schema_version: int = CURRENT_SCHEMA_VERSION


def load() -> SetupConfig | None:
    """Return the parsed setup, or None if the file is absent / unusable.

    Callers treat None as local-mode (v0.3.0 behavior). We never raise on
    a malformed file — a bad config should not break local-mode commands.
    """
    if not SETUP_PATH.exists():
        return None

    try:
        with SETUP_PATH.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("setup.toml unreadable, treating as local mode: %s", exc)
        return None

    schema_version = data.get("schema_version", 0)
    if schema_version != CURRENT_SCHEMA_VERSION:
        log.warning(
            "setup.toml schema_version=%r unexpected (this jarvis-cli expects %d); "
            "treating as local mode. Re-run `jarvis onboard --reset` to refresh.",
            schema_version,
            CURRENT_SCHEMA_VERSION,
        )
        return None

    appliance = data.get("appliance") or {}
    mode = appliance.get("mode", "local")
    if mode not in {"local", "remote"}:
        log.warning("setup.toml mode=%r invalid; treating as local mode.", mode)
        return None

    if mode == "local":
        return SetupConfig(mode="local", schema_version=schema_version)

    # mode == "remote" — host + user required.
    host = appliance.get("host")
    user = appliance.get("user")
    if not host or not user:
        log.warning(
            "setup.toml mode=remote but host/user missing; treating as local mode."
        )
        return None

    port = int(appliance.get("port", 22))
    identity_file_raw = appliance.get("identity_file")
    identity_file: Path | None = None
    if identity_file_raw:
        identity_file = Path(str(identity_file_raw)).expanduser()

    return SetupConfig(
        mode="remote",
        host=str(host),
        user=str(user),
        port=port,
        identity_file=identity_file,
        schema_version=schema_version,
    )


def save(cfg: SetupConfig) -> None:
    """Write `cfg` to `~/.jarvis/setup.toml` with mode 0600."""
    appliance: dict[str, str | int] = {"mode": cfg.mode}
    if cfg.host is not None:
        appliance["host"] = cfg.host
    if cfg.user is not None:
        appliance["user"] = cfg.user
    if cfg.port != 22:
        appliance["port"] = cfg.port
    if cfg.identity_file is not None:
        appliance["identity_file"] = str(cfg.identity_file)

    data: dict[str, object] = {
        "schema_version": cfg.schema_version,
        "appliance": appliance,
    }
    write_toml(data, SETUP_PATH)
    os.chmod(SETUP_PATH, 0o600)


def is_remote() -> bool:
    """Convenience: True iff a valid remote-mode setup is active."""
    cfg = load()
    return cfg is not None and cfg.mode == "remote"


def backup() -> Path | None:
    """Copy the current setup.toml to a timestamped sibling.

    Returns the backup path, or None if no setup.toml exists. The
    backup is mode 0600 to match the original.
    """
    if not SETUP_PATH.exists():
        return None
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = SETUP_PATH.parent / f"setup.toml.bak-{stamp}"
    shutil.copy2(SETUP_PATH, backup_path)
    os.chmod(backup_path, 0o600)
    return backup_path


def restore_from_backup(backup_path: Path) -> None:
    """Reverse a `backup()` — restore setup.toml from `backup_path`.

    Used when `jarvis onboard --reset` is aborted mid-flight.
    """
    if not backup_path.exists():
        raise FileNotFoundError(backup_path)
    shutil.copy2(backup_path, SETUP_PATH)
    os.chmod(SETUP_PATH, 0o600)
