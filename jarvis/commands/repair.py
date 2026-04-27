"""`jarvis repair <thing>` — scoped repair commands.

Each repair targets a known failure mode with a known fix. WRITE commands —
require confirmation unless --yes.

v0.2 ships `repair plist` (HARDENING Rule 18) as the first real
implementation. `repair memory` and `repair channels` remain stubs until we
have ground truth from real failures.
"""
from __future__ import annotations

import subprocess
from typing import Annotated

import typer

from jarvis.lib import macos as mac
from jarvis.lib.dispatch import dispatch_remote, should_dispatch_remote
from jarvis.lib.output import emit, fail
from jarvis.lib.platform import detect_platform

app = typer.Typer(
    help="Scoped repair commands. WRITE — require confirmation.", no_args_is_help=True
)


# Excerpt of HARDENING Rule 18 — printed when this repair fails so the
# operator (or LLM) sees the canonical explanation inline. Kept short; full
# text is available via `jarvis docs show hardening rule-18`.
RULE_18_EXCERPT = """
HARDENING Rule 18 — Bearer Token Injection

jarvis-memory's REST API gates /api/v1/* and /api/v2/* behind a Bearer
token. Without it in the gateway env, every hook call returns 401 and
memory reads fail silently. /health is unauthenticated, so naive checks
pass.

The token lives at ~/.<agent>-secrets/jarvis-memory.env as
JARVIS_API_BEARER_TOKEN=<64char>. It must be in the gateway LaunchAgent
plist's EnvironmentVariables. Reload via bootout + bootstrap (NOT
kickstart -k — kickstart does not re-read env vars).

Full text: jarvis docs show hardening rule-18
""".strip()


@app.command("plist")
def plist(
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            help="Agent name (lowercase). Auto-detected from ~/.*-secrets/ if omitted.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would change without modifying anything."),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Re-inject JARVIS_API_BEARER_TOKEN into the gateway plist + reload.

    Targets HARDENING Rule 18 — the single most common silent failure mode
    on macOS installs. Without the token in the gateway environment, every
    hook call returns 401 and memory writes fail silently.

    Procedure:
        1. Detect agent install (or use --agent)
        2. Read token from ~/.<agent>-secrets/jarvis-memory.env
        3. Backup the gateway plist
        4. Inject token into EnvironmentVariables via plutil JSON roundtrip
        5. plutil -lint the new plist
        6. launchctl bootout + bootstrap the gateway
        7. Wait for /health (up to 30s)
        8. Verify the token is present in the on-disk plist
    """
    # Remote-dispatch prologue: confirm locally (unless --dry-run, which is
    # read-only), then SSH the action with --yes so the remote shell doesn't
    # re-prompt over the non-interactive SSH session.
    cfg = should_dispatch_remote()
    if cfg is not None:
        if not dry_run and not yes and not json_output:
            if not typer.confirm(
                "Inject JARVIS_API_BEARER_TOKEN into the gateway plist and "
                "reload the gateway? Brief outage (~5s)."
            ):
                raise typer.Exit(code=1)
        raise typer.Exit(code=dispatch_remote(cfg, ensure_yes=not dry_run))

    plat = detect_platform()
    if plat.os_name != "macos":
        fail(
            "jarvis repair plist is macOS-only. On Linux, env vars live in "
            "the systemd unit drop-in /etc/systemd/system/jarvis-gateway.service.d/"
            "env.conf — Linux equivalent coming in v0.3 once Phase 07 is ported."
        )

    install = _resolve_install(agent)

    secrets_env = install.secrets_dir / "jarvis-memory.env"
    if not secrets_env.exists():
        fail(
            f"secrets file missing: {secrets_env}",
            doc_excerpt=RULE_18_EXCERPT,
        )
    env_vars = mac.parse_env_file(secrets_env)
    token = env_vars.get("JARVIS_API_BEARER_TOKEN", "")
    if not token or len(token) <= 16:
        fail(
            f"JARVIS_API_BEARER_TOKEN missing or too short in {secrets_env} "
            f"(found {len(token)} chars; expected >16)",
            doc_excerpt=RULE_18_EXCERPT,
        )

    if not install.plist_path.exists():
        fail(
            f"gateway plist not found: {install.plist_path}. "
            "OpenClaw gateway may not be installed.",
            doc_excerpt=RULE_18_EXCERPT,
        )

    try:
        config = mac.read_plist_as_json(install.plist_path)
    except subprocess.CalledProcessError as e:
        fail(f"failed to read plist as JSON: {e.stderr.strip() or e}")
        return  # mypy

    env = config.setdefault("EnvironmentVariables", {})
    if not isinstance(env, dict):
        fail(f"plist EnvironmentVariables is not a dict (got {type(env).__name__})")
        return

    current_token = env.get("JARVIS_API_BEARER_TOKEN")
    already_correct = current_token == token

    if dry_run:
        emit(
            {
                "action": "repair-plist",
                "dry_run": True,
                "agent": install.name_lower,
                "plist_path": str(install.plist_path),
                "secrets_env": str(secrets_env),
                "token_present_already": current_token is not None,
                "token_correct_already": already_correct,
                "would_inject_bytes": len(token),
                "would_reload_gateway": not already_correct,
            },
            as_json=json_output,
        )
        return

    if already_correct:
        emit(
            {
                "action": "repair-plist",
                "agent": install.name_lower,
                "result": "no-op",
                "detail": "token already present and correct in plist",
            },
            as_json=json_output,
        )
        return

    if not yes and not json_output:
        if not typer.confirm(
            f"Inject JARVIS_API_BEARER_TOKEN into {install.plist_path.name} "
            f"and reload the gateway? Brief outage (~5s)."
        ):
            raise typer.Exit(code=1)

    env["JARVIS_API_BEARER_TOKEN"] = token
    backup_path = mac.backup_plist(install.plist_path, suffix="jarvis-token")

    try:
        mac.write_plist_atomic(config, install.plist_path)
    except subprocess.CalledProcessError as e:
        fail(
            f"failed to write new plist: {e.stderr.strip() or e}. "
            f"Original backed up at {backup_path}.",
            doc_excerpt=RULE_18_EXCERPT,
        )
        return

    try:
        mac.launchctl_reload(install.plist_path, mac.GATEWAY_LABEL)
    except subprocess.CalledProcessError as e:
        fail(
            f"launchctl bootstrap failed: {e.stderr.strip() or e}. "
            f"Original backed up at {backup_path} — restore manually if "
            f"gateway doesn't come back.",
            doc_excerpt=RULE_18_EXCERPT,
        )
        return

    came_back = mac.wait_for_endpoint(mac.GATEWAY_HEALTH_URL, timeout_total=30.0)

    # Verify token is in the on-disk plist after the swap.
    try:
        verify_config = mac.read_plist_as_json(install.plist_path)
        verify_env = verify_config.get("EnvironmentVariables", {})
        verified = (
            isinstance(verify_env, dict)
            and verify_env.get("JARVIS_API_BEARER_TOKEN") == token
        )
    except subprocess.CalledProcessError:
        verified = False

    payload = {
        "action": "repair-plist",
        "agent": install.name_lower,
        "plist_path": str(install.plist_path),
        "backup_path": str(backup_path),
        "token_bytes_injected": len(token),
        "gateway_came_back": came_back,
        "token_verified_in_plist": verified,
        "result": "PASS" if (came_back and verified) else "PARTIAL",
        "next_step": (
            "Tail /tmp/jarvis-memory-api.log for ~5 min — look for `200 OK` on "
            "/api/v2/save_episode (hook auth working) vs `401` on /api/v1/search "
            "(hook auth NOT working)."
        ),
    }
    emit(payload, as_json=json_output)
    if not (came_back and verified):
        raise typer.Exit(code=1)


def _resolve_install(agent_arg: str | None) -> mac.AgentInstall:
    """Pick which install to operate on. Auto-detect or honor --agent."""
    installs = mac.find_agent_installs()
    if not installs:
        fail(
            "No agent install detected. Looked for ~/.<agent>-secrets/jarvis-memory.env "
            "and found nothing. Pass --agent <name_lower> if your secrets dir is "
            "in a non-standard location."
        )
    if agent_arg:
        for inst in installs:
            if inst.name_lower == agent_arg.lower():
                return inst
        fail(
            f"--agent '{agent_arg}' not found among detected installs: "
            f"{[i.name_lower for i in installs]}"
        )
    if len(installs) > 1:
        fail(
            f"Multiple agent installs detected ({[i.name_lower for i in installs]}). "
            f"Pass --agent <name_lower> to disambiguate."
        )
    return installs[0]


@app.command("memory")
def memory(
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Restart jarvis-memory + clear stale Neo4j locks.

    TODO v0.3: stop service, rm $NEO4J_DATA/databases/*/store_lock if stale,
    restart, wait for /health 200.
    """
    # Remote-dispatch prologue: confirm locally, then SSH with --yes.
    cfg = should_dispatch_remote()
    if cfg is not None:
        if not yes and not json_output:
            if not typer.confirm("Restart jarvis-memory and clear stale locks?"):
                raise typer.Exit(code=1)
        raise typer.Exit(code=dispatch_remote(cfg, ensure_yes=True))

    if not yes and not json_output:
        if not typer.confirm("Restart jarvis-memory and clear stale locks?"):
            raise typer.Exit(code=1)
    emit({"action": "repair-memory", "status": "TODO v0.3"}, as_json=json_output)


@app.command("channels")
def channels(
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Probe and re-auth channel tokens (currently: Discord only).

    iMessage / BlueBubbles was dropped from V1. The EtherealOS bridge will
    take its place once that ships — at which point this command grows a
    second probe path.

    TODO v0.3: probe Discord with bot token, surface specific re-auth
    prompts the operator can act on.
    """
    # Remote-dispatch prologue: confirm locally, then SSH with --yes.
    cfg = should_dispatch_remote()
    if cfg is not None:
        if not yes and not json_output:
            if not typer.confirm("Probe and re-auth Discord channel token?"):
                raise typer.Exit(code=1)
        raise typer.Exit(code=dispatch_remote(cfg, ensure_yes=True))

    if not yes and not json_output:
        if not typer.confirm("Probe and re-auth Discord channel token?"):
            raise typer.Exit(code=1)
    emit({"action": "repair-channels", "status": "TODO v0.3"}, as_json=json_output)
