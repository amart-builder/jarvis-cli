"""Hand-rolled minimal TOML writer for jarvis-cli's flat schema.

We need to write `~/.jarvis/setup.toml` with a deliberately tiny shape:
    schema_version = 1                 # top-level int
    [appliance]
    mode = "remote"                    # string
    host = "100.x.x.x"                 # string
    user = "alex"                      # string
    port = 22                          # int
    identity_file = "~/.ssh/id_ed25519" # optional string

Stdlib `tomllib` reads TOML but doesn't write it. Rather than pull in
`tomli-w` for a fixed-shape file, we hand-roll the writer.

Supports ONLY:
- top-level scalar values (str, int, bool)
- one or more named tables ([section]) with scalar values

Does NOT support: nested tables, arrays, dates, multi-line strings.
If you need those, switch to `tomli-w` — don't extend this.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _format_scalar(value: Any) -> str:
    """Render a Python scalar as its TOML literal form."""
    if isinstance(value, bool):
        # bool BEFORE int — bool is a subclass of int in Python.
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _format_string(value)
    raise TypeError(
        f"_tomlwrite: unsupported value type {type(value).__name__} (only str/int/bool supported)"
    )


def _format_string(value: str) -> str:
    """Render a Python str as a TOML basic-string literal.

    Escapes backslash and double-quote per TOML spec; rejects control chars
    other than tab. Sufficient for paths and IPs and usernames.
    """
    forbidden = [c for c in value if ord(c) < 0x20 and c != "\t"]
    if forbidden:
        raise ValueError(
            f"_tomlwrite: control character (0x{ord(forbidden[0]):02x}) not allowed in TOML basic string"
        )
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_toml(data: dict[str, Any], path: Path) -> None:
    """Write `data` to `path` as TOML, atomic via .tmp + os.replace.

    `data` schema:
        - keys whose values are scalars (str/int/bool) → top-level entries
        - keys whose values are dicts → named tables ([section])
    """
    lines: list[str] = []

    # Top-level scalars first (in dict insertion order).
    for k, v in data.items():
        if isinstance(v, dict):
            continue
        if not _is_bare_key(k):
            raise ValueError(f"_tomlwrite: top-level key {k!r} is not a TOML bare key")
        lines.append(f"{k} = {_format_scalar(v)}")

    # Named tables.
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        if not _is_bare_key(k):
            raise ValueError(f"_tomlwrite: table name {k!r} is not a TOML bare key")
        if lines:
            lines.append("")  # blank line before each table
        lines.append(f"[{k}]")
        for sub_k, sub_v in v.items():
            if isinstance(sub_v, dict):
                raise ValueError(
                    f"_tomlwrite: nested tables not supported (in [{k}].{sub_k})"
                )
            if not _is_bare_key(sub_k):
                raise ValueError(
                    f"_tomlwrite: key {sub_k!r} in [{k}] is not a TOML bare key"
                )
            lines.append(f"{sub_k} = {_format_scalar(sub_v)}")

    body = "\n".join(lines) + "\n"

    # Atomic write: tmp-sibling + os.replace.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)


def _is_bare_key(s: str) -> bool:
    """A TOML bare key matches A-Za-z0-9_- and is non-empty.

    We reject anything else rather than try to quote-escape, because our
    schema doesn't need exotic keys.
    """
    if not s:
        return False
    return all(c.isalnum() or c in {"_", "-"} for c in s)
