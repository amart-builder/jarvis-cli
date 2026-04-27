"""Tests for jarvis.lib.setup_config — load/save/backup roundtrip."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from jarvis.lib import setup_config
from jarvis.lib.setup_config import SetupConfig


@pytest.fixture
def patched_setup_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Re-point setup_config.SETUP_PATH at a tmp file."""
    target = tmp_path / ".jarvis" / "setup.toml"
    monkeypatch.setattr(setup_config, "SETUP_PATH", target)
    return target


def test_load_returns_none_when_file_absent(patched_setup_path: Path) -> None:
    assert setup_config.load() is None


def test_save_then_load_roundtrips_remote_config(patched_setup_path: Path) -> None:
    cfg = SetupConfig(
        mode="remote",
        host="192.0.2.42",
        user="alex",
        port=22,
        identity_file=None,
    )
    setup_config.save(cfg)
    loaded = setup_config.load()
    assert loaded is not None
    assert loaded.mode == "remote"
    assert loaded.host == "192.0.2.42"
    assert loaded.user == "alex"
    assert loaded.port == 22


def test_save_writes_mode_0600(patched_setup_path: Path) -> None:
    cfg = SetupConfig(mode="remote", host="h", user="u")
    setup_config.save(cfg)
    perms = stat.S_IMODE(os.stat(patched_setup_path).st_mode)
    assert perms == 0o600


def test_load_returns_none_on_malformed_toml(patched_setup_path: Path) -> None:
    patched_setup_path.parent.mkdir(parents=True, exist_ok=True)
    patched_setup_path.write_text("this is :: not valid toml", encoding="utf-8")
    assert setup_config.load() is None


def test_load_returns_none_on_schema_mismatch(patched_setup_path: Path) -> None:
    patched_setup_path.parent.mkdir(parents=True, exist_ok=True)
    patched_setup_path.write_text(
        'schema_version = 99\n[appliance]\nmode = "remote"\nhost = "h"\nuser = "u"\n',
        encoding="utf-8",
    )
    assert setup_config.load() is None


def test_load_returns_local_config_for_mode_local(patched_setup_path: Path) -> None:
    patched_setup_path.parent.mkdir(parents=True, exist_ok=True)
    patched_setup_path.write_text(
        'schema_version = 1\n[appliance]\nmode = "local"\n', encoding="utf-8"
    )
    loaded = setup_config.load()
    assert loaded is not None
    assert loaded.mode == "local"
    assert loaded.host is None


def test_load_returns_none_when_remote_missing_host(patched_setup_path: Path) -> None:
    patched_setup_path.parent.mkdir(parents=True, exist_ok=True)
    patched_setup_path.write_text(
        'schema_version = 1\n[appliance]\nmode = "remote"\nuser = "alex"\n',
        encoding="utf-8",
    )
    assert setup_config.load() is None


def test_load_returns_none_when_mode_invalid(patched_setup_path: Path) -> None:
    patched_setup_path.parent.mkdir(parents=True, exist_ok=True)
    patched_setup_path.write_text(
        'schema_version = 1\n[appliance]\nmode = "elsewhere"\n', encoding="utf-8"
    )
    assert setup_config.load() is None


def test_is_remote_true_for_valid_remote(patched_setup_path: Path) -> None:
    setup_config.save(SetupConfig(mode="remote", host="h", user="u"))
    assert setup_config.is_remote() is True


def test_is_remote_false_when_no_setup(patched_setup_path: Path) -> None:
    assert setup_config.is_remote() is False


def test_backup_returns_none_when_no_setup(patched_setup_path: Path) -> None:
    assert setup_config.backup() is None


def test_backup_and_restore_roundtrip(patched_setup_path: Path) -> None:
    original = SetupConfig(mode="remote", host="orig.host", user="orig-user")
    setup_config.save(original)

    backup_path = setup_config.backup()
    assert backup_path is not None
    assert backup_path.exists()

    # Mutate the file.
    setup_config.save(SetupConfig(mode="remote", host="new.host", user="new-user"))
    assert setup_config.load().host == "new.host"  # type: ignore[union-attr]

    # Restore — original values come back.
    setup_config.restore_from_backup(backup_path)
    restored = setup_config.load()
    assert restored is not None
    assert restored.host == "orig.host"
    assert restored.user == "orig-user"


def test_save_with_identity_file_and_nondefault_port(patched_setup_path: Path) -> None:
    cfg = SetupConfig(
        mode="remote",
        host="h",
        user="u",
        port=2222,
        identity_file=Path("~/.ssh/id_special").expanduser(),
    )
    setup_config.save(cfg)
    loaded = setup_config.load()
    assert loaded is not None
    assert loaded.port == 2222
    assert loaded.identity_file is not None
    assert "id_special" in str(loaded.identity_file)
