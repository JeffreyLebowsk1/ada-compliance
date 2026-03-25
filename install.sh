#!/usr/bin/env bash
# install.sh — Linux installer for ada-compliance-bot
# Usage: bash install.sh

set -euo pipefail

# ── Colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Colour

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}   ADA / WCAG Compliance Bot — Linux Installer      ${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo

# ── 1. Detect OS ────────────────────────────────────────────────────────────
if [[ "$(uname -s)" != "Linux" ]]; then
    error "This installer is intended for Linux only. Detected: $(uname -s)"
fi
success "Linux detected"

# ── 2. Check Python 3.10+ ───────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null || true)
        major=$("$cmd" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || true)
        minor=$("$cmd" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || true)
        if [[ "${major:-0}" -ge 3 && "${minor:-0}" -ge 10 ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    error "Python 3.10 or higher is required but was not found.\n       Install it with your package manager, e.g.:\n         sudo apt install python3.10"
fi
success "Python found: $($PYTHON --version)"

# ── 3. Determine install directory ──────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_URL="https://github.com/JeffreyLebowsk1/ada-compliance.git"

# If pyproject.toml exists in the same directory as this script, assume we're
# already inside the cloned repository.
if [[ -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
    INSTALL_DIR="${SCRIPT_DIR}"
    info "Repository detected at: ${INSTALL_DIR}"
else
    # Otherwise clone into a new directory
    INSTALL_DIR="${HOME}/ada-compliance"
    if [[ -d "${INSTALL_DIR}/.git" ]]; then
        info "Existing clone found at ${INSTALL_DIR} — pulling latest changes"
        git -C "${INSTALL_DIR}" pull --ff-only
    else
        info "Cloning repository into ${INSTALL_DIR}"
        git clone "${REPO_URL}" "${INSTALL_DIR}"
    fi
fi

cd "${INSTALL_DIR}"
success "Working directory: ${INSTALL_DIR}"

# ── 4. Create virtual environment ───────────────────────────────────────────
VENV_DIR="${INSTALL_DIR}/.venv"
if [[ -d "${VENV_DIR}" ]]; then
    info "Virtual environment already exists at ${VENV_DIR}"
else
    info "Creating virtual environment at ${VENV_DIR}"
    "$PYTHON" -m venv "${VENV_DIR}"
fi
success "Virtual environment ready"

# ── 5. Upgrade pip ──────────────────────────────────────────────────────────
info "Upgrading pip"
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip

# ── 6. Install the package ──────────────────────────────────────────────────
info "Installing ada-compliance-bot and dependencies"
"${VENV_DIR}/bin/pip" install --quiet -e .
success "Package installed"

# ── 7. Install Playwright's Chromium browser ────────────────────────────────
info "Installing Playwright Chromium browser (required for axe-core and vision layers)"

# Some Linux distros need extra system libraries for Chromium.
# Playwright can install them automatically if the user has sudo access.
if command -v apt-get &>/dev/null && [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    info "Running as root — installing Playwright system dependencies"
    "${VENV_DIR}/bin/playwright" install-deps chromium
elif command -v sudo &>/dev/null; then
    info "Attempting to install Playwright system dependencies via sudo"
    sudo "${VENV_DIR}/bin/playwright" install-deps chromium || \
        warn "Could not install system dependencies automatically.\n       If Chromium fails to launch, run:\n         sudo ${VENV_DIR}/bin/playwright install-deps chromium"
else
    warn "sudo not available — skipping system dependency installation.\n       If Chromium fails to launch, install its dependencies manually."
fi

"${VENV_DIR}/bin/playwright" install chromium
success "Playwright Chromium installed"

# ── 8. Done ─────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}   Installation complete!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
echo -e "  Activate the virtual environment:"
echo -e "    ${CYAN}source ${VENV_DIR}/bin/activate${NC}"
echo
echo -e "  Run an audit:"
echo -e "    ${CYAN}ada-bot audit https://example.com${NC}"
echo
echo -e "  Run with AI vision (requires PERPLEXITY_API_KEY):"
echo -e "    ${CYAN}PERPLEXITY_API_KEY=pplx-... ada-bot audit https://example.com --vision${NC}"
echo
echo -e "  See all options:"
echo -e "    ${CYAN}ada-bot audit --help${NC}"
echo
