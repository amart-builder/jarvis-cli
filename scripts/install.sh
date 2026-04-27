#!/usr/bin/env bash
# install.sh — one-liner installer for jarvis-cli.
#
# Designed for `curl -sSL https://raw.githubusercontent.com/amart-builder/jarvis-cli/main/scripts/install.sh | bash`.
# Detects (or installs) pipx, installs jarvis-cli from the public repo,
# then registers it with Codex and/or Claude Code.
#
# Safe to re-run — `pipx install --force` upgrades in place, and
# `jarvis codex install --auto` overwrites instruction files byte-identically.
#
# Exits 0 on success. Aborts with a clear error on any step failure.

set -euo pipefail

REPO_URL="https://github.com/amart-builder/jarvis-cli"
PIPX_PACKAGE="git+${REPO_URL}"

# --- Pretty output (fall back to plain echo if no tty) -----------------------

if [ -t 1 ]; then
  c_green=$'\033[32m'
  c_yellow=$'\033[33m'
  c_red=$'\033[31m'
  c_bold=$'\033[1m'
  c_reset=$'\033[0m'
else
  c_green=""; c_yellow=""; c_red=""; c_bold=""; c_reset=""
fi

step() { printf "%s==>%s %s\n" "${c_bold}" "${c_reset}" "$1"; }
ok()   { printf "%s✓%s %s\n" "${c_green}" "${c_reset}" "$1"; }
warn() { printf "%s!%s %s\n" "${c_yellow}" "${c_reset}" "$1" >&2; }
die()  { printf "%sx%s %s\n" "${c_red}" "${c_reset}" "$1" >&2; exit 1; }

# --- Sanity checks -----------------------------------------------------------

step "checking environment"

if ! command -v python3 >/dev/null 2>&1; then
  die "python3 not found. Install Python 3.11+ first (e.g. https://www.python.org/downloads/macos/)."
fi

PY_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  die "python3 is ${PY_VERSION}; jarvis-cli requires 3.11+."
fi
ok "python3 ${PY_VERSION}"

# --- Ensure pipx is available -----------------------------------------------

step "ensuring pipx is installed"

if command -v pipx >/dev/null 2>&1; then
  ok "pipx already installed"
else
  if command -v brew >/dev/null 2>&1; then
    step "installing pipx via brew"
    brew install pipx
    pipx ensurepath || true
  else
    step "installing pipx via pip --user"
    # On modern macOS / PEP 668 systems, pip --user can refuse with
    # "externally-managed-environment". Try the safe path first; fall back
    # to --break-system-packages (still scoped to --user, so it can't touch
    # the system Python).
    if ! python3 -m pip install --user pipx 2>/dev/null; then
      warn "pip --user blocked by PEP 668 — retrying with --break-system-packages (user scope only)"
      python3 -m pip install --user --break-system-packages pipx
    fi
    python3 -m pipx ensurepath || true
  fi

  # pipx may not be on PATH yet in this shell — locate it manually.
  if ! command -v pipx >/dev/null 2>&1; then
    PIPX_USER_BASE=$(python3 -c 'import site; print(site.USER_BASE)')
    if [ -x "${PIPX_USER_BASE}/bin/pipx" ]; then
      export PATH="${PIPX_USER_BASE}/bin:${PATH}"
      ok "pipx installed at ${PIPX_USER_BASE}/bin/pipx (added to PATH for this session)"
    else
      die "pipx installed but not on PATH. Open a new terminal and re-run, or run: export PATH=\"${PIPX_USER_BASE}/bin:\$PATH\""
    fi
  else
    ok "pipx ready"
  fi
fi

# --- Install jarvis-cli -------------------------------------------------------

step "installing jarvis-cli from ${REPO_URL}"
pipx install --force "${PIPX_PACKAGE}"

# Locate the installed jarvis binary. pipx ensurepath may not be active yet
# in this non-interactive shell, so check the standard pipx bin dir.
if ! command -v jarvis >/dev/null 2>&1; then
  PIPX_BIN_DIR=$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "${HOME}/.local/bin")
  if [ -x "${PIPX_BIN_DIR}/jarvis" ]; then
    export PATH="${PIPX_BIN_DIR}:${PATH}"
    ok "jarvis installed at ${PIPX_BIN_DIR}/jarvis (added to PATH for this session)"
  else
    die "jarvis installed but not on PATH. Open a new terminal, or run: export PATH=\"${PIPX_BIN_DIR}:\$PATH\""
  fi
fi
ok "jarvis on PATH"

# --- Register with Codex / Claude Code ---------------------------------------

step "registering jarvis with Codex / Claude Code"
jarvis codex install --auto
ok "agent instructions written"

# --- Final report ------------------------------------------------------------

INSTALLED_VERSION=$(jarvis version 2>&1 | head -1 || true)
printf "\n%sjarvis-cli installed:%s %s\n" "${c_bold}" "${c_reset}" "${INSTALLED_VERSION}"
printf "Try: %sjarvis context --json%s\n" "${c_green}" "${c_reset}"
