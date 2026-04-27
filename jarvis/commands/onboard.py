"""`jarvis onboard` — interactive walkthrough that wires this laptop to a
remote OpenClaw appliance.

Designed for a non-technical user who has Codex installed and has been told
"paste this GitHub URL." Codex (or any LLM agent) reads the README and runs
this command on the user's behalf, translating prompts into yes/no answers
and copy-pasteable commands.

The command is *interactive by design.* It cannot be scripted with stdin
piping; `--non-interactive` is rejected. Builders / CI should write
`~/.jarvis/setup.toml` directly via `setup_config.save()`.

Branches:
- Tailscale auto-detect (with peer list) OR manual host entry
- SSH reachability probe → OK / CONNECTION_REFUSED / TIMEOUT / AUTH_FAILED / HOST_KEY_UNKNOWN
- Per-failure walkthroughs:
  - HOST_KEY_UNKNOWN: ssh-keyscan + show fingerprint + confirm + append to known_hosts
  - CONNECTION_REFUSED/TIMEOUT: enable-Remote-Login walkthrough (mac/linux/not-sure)
  - AUTH_FAILED: ssh-copy-id walkthrough (with key generation if needed)
- Two-failure escalation per sub-step
- Two-end install: SSH the remote and run install.sh there
- End-to-end verify: ssh remote 'jarvis context --json' returns valid schema 2.0 JSON

After success: writes ~/.jarvis/setup.toml; future `jarvis <cmd>` calls
SSH-route to the configured host via `jarvis.lib.dispatch`.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from jarvis.lib import setup_config, ssh_wrapper, tailscale
from jarvis.lib.setup_config import SETUP_PATH, SetupConfig
from jarvis.lib.ssh_wrapper import ReachabilityResult

# Public install URL — the same one the public README points to.
PUBLIC_INSTALL_URL = "https://raw.githubusercontent.com/amart-builder/jarvis-cli/main/scripts/install.sh"
PUBLIC_REPO_URL = "https://github.com/amart-builder/jarvis-cli"

# Generic escalation contact line (per spec OQ4 default — no specific email).
ESCALATION_CONTACT = (
    "share this output with whoever set up your Jarvis appliance "
    "(if that's not you), or open an issue at "
    "https://github.com/amart-builder/jarvis-cli/issues"
)

# Exit codes (per spec Assumption 19).
EXIT_OK = 0
EXIT_USER_ABORT = 1
EXIT_TWO_FAILURE_ESCALATION = 2
EXIT_MISSING_PREREQUISITES = 3


def onboard(
    reset: Annotated[
        bool,
        typer.Option(
            "--reset",
            help="Force a fresh interview, backing up any existing setup.toml.",
        ),
    ] = False,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="(Refused.) Onboarding is interactive by design. Use setup_config.save() directly for automation.",
        ),
    ] = False,
) -> None:
    """Walk through SSH setup for a remote OpenClaw appliance."""
    console = Console()

    if non_interactive:
        console.print(
            "[red]--non-interactive is not supported.[/red] Onboarding is interactive by design.\n"
            "If you're scripting, write ~/.jarvis/setup.toml directly using "
            "jarvis.lib.setup_config.save()."
        )
        raise typer.Exit(code=EXIT_MISSING_PREREQUISITES)

    # Pre-flight: confirm `ssh` binary exists.
    if not _has_ssh_binary():
        console.print(
            "[red]The `ssh` command isn't on your PATH.[/red] On macOS this should be "
            "installed by default; on Linux, install OpenSSH client (e.g. `sudo apt install openssh-client`)."
        )
        raise typer.Exit(code=EXIT_MISSING_PREREQUISITES)

    # If setup already exists and we're not in --reset, just verify and exit.
    existing = setup_config.load()
    if existing is not None and existing.mode == "remote" and not reset:
        _maybe_verify_existing(console, existing)
        return

    backup_path: Path | None = None
    if reset and existing is not None:
        backup_path = setup_config.backup()
        console.print(f"[dim]Backed up existing setup.toml → {backup_path}[/dim]")

    try:
        cfg = _run_interview(console)
    except typer.Abort:
        if backup_path is not None:
            setup_config.restore_from_backup(backup_path)
            console.print(
                f"[yellow]Aborted. Restored previous setup from {backup_path}.[/yellow]"
            )
        else:
            console.print("[yellow]Aborted. No setup file was written.[/yellow]")
        raise typer.Exit(code=EXIT_USER_ABORT)

    setup_config.save(cfg)
    console.print(
        Panel(
            f"[green]Setup complete.[/] Wrote [cyan]{SETUP_PATH}[/].\n\n"
            "From now on, every `jarvis <cmd>` on this laptop SSHes into "
            f"[bold]{cfg.user}@{cfg.host}[/] and runs the command there.\n\n"
            "Try: [cyan]jarvis context --json[/]",
            title="onboard complete",
            expand=False,
        )
    )


# --- the interview ---------------------------------------------------------


def _run_interview(console: Console) -> SetupConfig:
    """Drive the full onboarding interview. Returns a saved-ready SetupConfig."""
    console.print(
        Panel(
            "[bold]Jarvis CLI onboarding[/]\n\n"
            "I'll help you connect this laptop to your remote OpenClaw appliance "
            "(your Mac Mini, VPS, or wherever OpenClaw is running).\n\n"
            "If anything goes wrong, you can press Ctrl+C to abort. "
            "I'll restore your previous setup if you used --reset.",
            expand=False,
        )
    )

    host = _pick_host(console)
    user = _pick_user(console)
    port = _pick_port(console)
    identity_file = _pick_identity_file(console)

    cfg = SetupConfig(
        mode="remote",
        host=host,
        user=user,
        port=port,
        identity_file=identity_file,
    )

    cfg = _ensure_reachable(console, cfg)
    _ensure_remote_jarvis_installed(console, cfg)
    _verify_end_to_end(console, cfg)
    return cfg


def _pick_host(console: Console) -> str:
    """Step 1: Tailscale auto-detect, or manual entry."""
    if tailscale.detect():
        peers = tailscale.list_peers()
        if peers:
            console.print(
                "[bold]Step 1.[/] I see Tailscale on this laptop. "
                "Pick the machine where your OpenClaw appliance is running:"
            )
            table = Table(show_header=True, header_style="bold")
            table.add_column("#", justify="right")
            table.add_column("Hostname")
            table.add_column("Tailscale IP")
            table.add_column("OS")
            for i, peer in enumerate(peers, start=1):
                table.add_row(str(i), peer.hostname, peer.ip, peer.os)
            table.add_row(str(len(peers) + 1), "(none of these — I'll type the address)", "", "")
            console.print(table)
            choice = typer.prompt(
                "Pick a number",
                type=int,
                default=1 if len(peers) == 1 else None,
            )
            if 1 <= choice <= len(peers):
                chosen = peers[choice - 1]
                # Always confirm — even when one peer remains after filtering.
                if typer.confirm(
                    f"Use {chosen.hostname} ({chosen.ip})?",
                    default=True,
                ):
                    return chosen.ip
            # Either user picked "none of these" or said no to the only candidate.
        else:
            console.print(
                "[dim]Tailscale is installed but I don't see any reachable peers — "
                "you can enter the address manually.[/]"
            )
    else:
        console.print(
            "[dim]Tailscale not detected; you can enter the address manually.[/]"
        )

    console.print("[bold]Step 1 (manual).[/] What's the IP address or hostname of your OpenClaw machine?")
    console.print(
        "[dim]Examples:  100.64.0.5   (Tailscale)\n"
        "          mini.local   (Bonjour on local network)\n"
        "          203.0.113.42 (public IP for a VPS)[/]"
    )
    return typer.prompt("Address")


def _pick_user(console: Console) -> str:
    default_user = os.environ.get("USER", "")
    console.print("[bold]Step 2.[/] What's your username on the OpenClaw machine?")
    console.print(
        "[dim]This is the account you'd use if you were logging into that machine directly.[/]"
    )
    return typer.prompt("Username", default=default_user)


def _pick_port(console: Console) -> int:
    return typer.prompt(
        "[bold]Step 3.[/] SSH port (almost always 22)",
        type=int,
        default=22,
    )


def _pick_identity_file(console: Console) -> Path | None:
    """Optional: ask if the user has a specific SSH key file to use.

    Default is None → SSH's default key search applies (id_ed25519, id_rsa,
    etc.). For most users we keep this empty.
    """
    if typer.confirm(
        "Do you want to use a specific SSH key file? "
        "(Most people say no — SSH will find your default key automatically.)",
        default=False,
    ):
        path_str = typer.prompt("Path to private key", default="~/.ssh/id_ed25519")
        return Path(path_str).expanduser()
    return None


# --- reachability + walkthroughs -------------------------------------------


def _ensure_reachable(console: Console, cfg: SetupConfig) -> SetupConfig:
    """Step 4: probe reachability, branch into walkthroughs on failure.

    Returns the (possibly host-key-trust-updated) cfg on success.
    Raises typer.Exit on two-failure escalation.
    """
    failures = 0
    while True:
        report = ssh_wrapper.test_reachability(cfg)
        if report.result == ReachabilityResult.OK:
            console.print(f"[green]✓[/] SSH to {cfg.user}@{cfg.host} works.")
            return cfg
        failures += 1

        console.print(
            f"\n[yellow]SSH probe: {report.result}[/]\n"
            f"[dim]{report.stderr.splitlines()[-1] if report.stderr else '(no stderr)'}[/]"
        )

        if failures >= 2:
            _escalate(console, "SSH connectivity", report.stderr)

        if report.result == ReachabilityResult.HOST_KEY_UNKNOWN:
            _walkthrough_host_key(console, cfg)
            continue
        if report.result in (
            ReachabilityResult.CONNECTION_REFUSED,
            ReachabilityResult.TIMEOUT,
        ):
            _walkthrough_enable_ssh(console)
            continue
        if report.result == ReachabilityResult.AUTH_FAILED:
            _walkthrough_ssh_copy_id(console, cfg)
            continue
        # OTHER — print stderr verbatim and ask user to retry.
        console.print(
            f"[red]Unrecognized SSH error.[/red] Raw output:\n[dim]{report.stderr}[/dim]"
        )
        if not typer.confirm("Retry the probe?", default=True):
            _escalate(console, "SSH connectivity", report.stderr)


def _walkthrough_host_key(console: Console, cfg: SetupConfig) -> None:
    """5: present host fingerprint, append to known_hosts on confirm."""
    console.print("[bold]Step 5 (host key).[/] I haven't seen this host before.")
    line = ssh_wrapper.keyscan_and_trust(cfg.host or "", cfg.port)
    if not line:
        console.print(
            f"[red]ssh-keyscan {cfg.host} failed.[/] The host might be unreachable."
        )
        return
    console.print(
        Panel(
            f"This is the cryptographic identity of [bold]{cfg.host}[/]:\n\n"
            f"[dim]{line}[/]\n\n"
            "If you've never connected to this machine before, this is normal and expected.",
            title="host key",
            expand=False,
        )
    )
    if not typer.confirm(
        f"Trust this host and add it to ~/.ssh/known_hosts?", default=True
    ):
        raise typer.Abort
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    known_hosts.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with known_hosts.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    os.chmod(known_hosts, 0o600)
    console.print(f"[green]✓[/] Appended host key to {known_hosts}.")


def _walkthrough_enable_ssh(console: Console) -> None:
    """5a: walk through enabling SSH on the remote."""
    console.print("[bold]Step 5a (enable SSH on the remote).[/]")
    family = Prompt.ask(
        "What kind of machine is your OpenClaw running on?",
        choices=["mac", "linux", "not-sure"],
        default="mac",
    )
    if family in ("mac", "not-sure"):
        console.print(
            Panel(
                "[bold]Mac walkthrough[/]\n\n"
                "On the Mac that's running OpenClaw (NOT this laptop):\n\n"
                "1. Open [cyan]System Settings[/] → [cyan]General[/] → [cyan]Sharing[/].\n"
                "2. Turn on [cyan]Remote Login[/].\n"
                "3. Make sure your username is in the allowed list.\n\n"
                "Then come back here and press Enter.",
                expand=False,
            )
        )
    if family in ("linux", "not-sure"):
        console.print(
            Panel(
                "[bold]Linux walkthrough[/]\n\n"
                "On the Linux server that's running OpenClaw, run:\n\n"
                "  [cyan]sudo systemctl enable --now sshd[/]\n\n"
                "(This enables SSH at boot and starts it now.) Then come back here and press Enter.",
                expand=False,
            )
        )
    typer.prompt("Press Enter when done", default="", show_default=False)


def _walkthrough_ssh_copy_id(console: Console, cfg: SetupConfig) -> None:
    """5b: walk the user through generating a key (if needed) and ssh-copy-id."""
    console.print("[bold]Step 5b (set up SSH keys).[/]")
    console.print(
        "Your laptop reached the OpenClaw machine, but it doesn't have a key the "
        "remote will accept. Let's fix that."
    )

    # Ask if they have an existing key.
    has_key = typer.confirm(
        "Do you already have an SSH key on this laptop? "
        "(If you've never set one up, the answer is no.)",
        default=False,
    )

    if not has_key:
        console.print(
            Panel(
                "[bold]Generate a key[/]\n\n"
                "In a NEW Terminal window, run this exactly:\n\n"
                "  [cyan]ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519[/]\n\n"
                "(This creates a passwordless SSH key — the standard for these setups.)\n\n"
                "Press Enter here when done.",
                expand=False,
            )
        )
        typer.prompt("Press Enter when done", default="", show_default=False)

    port_arg = f"-p {cfg.port} " if cfg.port != 22 else ""
    console.print(
        Panel(
            "[bold]Copy your key to the remote[/]\n\n"
            f"Run this in your terminal:\n\n"
            f"  [cyan]ssh-copy-id {port_arg}{cfg.user}@{cfg.host}[/]\n\n"
            "It will ask for the password ON THE OPENCLAW MACHINE — that's your "
            "login password for that machine, NOT this laptop's password.\n\n"
            "Type it carefully (it won't show as you type — that's normal).\n\n"
            "Press Enter here when done.",
            expand=False,
        )
    )
    typer.prompt("Press Enter when done", default="", show_default=False)


# --- two-end install + verify ----------------------------------------------


def _ensure_remote_jarvis_installed(console: Console, cfg: SetupConfig) -> None:
    """Step 6: detect or install jarvis-cli on the remote machine."""
    console.print("[bold]Step 6.[/] Checking whether jarvis-cli is on the remote machine…")
    probe = ssh_wrapper.run(cfg, "command -v jarvis", capture=True, timeout=15)
    if probe.returncode == 0 and probe.stdout.strip():
        version_probe = ssh_wrapper.run(cfg, "jarvis version", capture=True, timeout=15)
        if version_probe.returncode == 0:
            console.print(
                f"[green]✓[/] jarvis-cli is already installed remotely.\n"
                f"[dim]{version_probe.stdout.splitlines()[0]}[/]"
            )
            return
    console.print(
        f"jarvis-cli isn't on the remote. Installing it from {PUBLIC_REPO_URL} now…"
    )
    install_cmd = f"curl -sSL {PUBLIC_INSTALL_URL} | bash"
    result = ssh_wrapper.run(cfg, install_cmd, timeout=180)
    if result.returncode != 0:
        _escalate(
            console,
            f"installing jarvis-cli on {cfg.host}",
            "Install script exited non-zero. Try running it manually on the remote first.",
        )
    # Re-probe.
    version_probe = ssh_wrapper.run(cfg, "jarvis version", capture=True, timeout=15)
    if version_probe.returncode != 0:
        _escalate(
            console,
            "post-install jarvis version probe",
            version_probe.stderr or "remote `jarvis` not on PATH after install",
        )
    console.print(f"[green]✓[/] {version_probe.stdout.splitlines()[0]}")


def _verify_end_to_end(console: Console, cfg: SetupConfig) -> None:
    """Step 8: real round-trip — `ssh remote 'jarvis context --json'`."""
    console.print("[bold]Step 7.[/] Running a real end-to-end test…")
    result = ssh_wrapper.run(
        cfg, "jarvis context --json", capture=True, timeout=60
    )
    if result.returncode != 0:
        _escalate(
            console,
            "end-to-end verify",
            result.stderr or "remote `jarvis context --json` exited non-zero",
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        _escalate(
            console,
            "parsing remote jarvis context JSON",
            f"remote returned non-JSON: {exc}",
        )

    required_keys = {"docs", "openclaw_docs", "platform", "versions", "health"}
    missing = required_keys - set(payload.keys())
    if missing:
        _escalate(
            console,
            "verifying schema 2.0 keys",
            f"remote payload missing keys: {sorted(missing)}",
        )
    console.print(
        f"[green]✓[/] Remote responded with {len(result.stdout):,} chars of JSON "
        f"(docs.source={payload['docs'].get('source')!r})."
    )


# --- helpers ---------------------------------------------------------------


def _maybe_verify_existing(console: Console, cfg: SetupConfig) -> None:
    """Idempotent re-run on already-set-up machine."""
    console.print(
        f"[bold]Already set up:[/] mode=remote, host={cfg.host}, user={cfg.user}\n"
        "Verifying SSH still works…"
    )
    report = ssh_wrapper.test_reachability(cfg)
    if report.result != ReachabilityResult.OK:
        console.print(
            f"[yellow]SSH probe failed:[/] {report.result}\n"
            f"[dim]{report.stderr}[/]\n\n"
            "Run [cyan]jarvis onboard --reset[/] to re-run the interview."
        )
        raise typer.Exit(code=EXIT_OK)
    console.print("[green]✓[/] SSH OK. Verifying remote jarvis-cli…")
    version = ssh_wrapper.run(cfg, "jarvis version", capture=True, timeout=15)
    if version.returncode != 0:
        console.print(
            "[yellow]Remote jarvis-cli not responding.[/]\n"
            "Run [cyan]jarvis onboard --reset[/] to reinstall."
        )
        raise typer.Exit(code=EXIT_OK)
    console.print(
        f"[green]✓[/] Remote: {version.stdout.splitlines()[0]}\n\n"
        "Everything checks out. Use [cyan]jarvis onboard --reset[/] to start over."
    )


def _has_ssh_binary() -> bool:
    import shutil

    return shutil.which("ssh") is not None


def _escalate(console: Console, step: str, stderr: str) -> None:
    """Two-failure escalation: print the verbatim error + contact line, exit 2."""
    setup_hint = (
        f"\nIf {SETUP_PATH} exists, attach its contents to your message — "
        "it has the host/user/port settings that may be wrong."
        if SETUP_PATH.exists()
        else ""
    )
    console.print(
        Panel(
            f"[red]I couldn't get past {step} after two tries.[/red]\n\n"
            f"Here's what I saw:\n[dim]{stderr.strip()}[/dim]\n\n"
            f"Please {ESCALATION_CONTACT}.{setup_hint}\n\n"
            "I'm not going to keep retrying — the next attempt won't help "
            "without changing something.",
            title="escalation",
            expand=False,
        )
    )
    raise typer.Exit(code=EXIT_TWO_FAILURE_ESCALATION)
