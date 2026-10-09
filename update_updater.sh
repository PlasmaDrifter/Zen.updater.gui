#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Zen Updater Self-Update Script (CLI)
# Checks official GitHub releases for Zen.updater.gui and updates local scripts.
# ==============================================================================

REPO="PlasmaDrifter/Zen.updater.gui"
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}Checking for Zen Updater releases on GitHub...${NC}"

RELEASE_JSON=$(curl -s "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null || true)
if [ -z "${RELEASE_JSON}" ]; then
    echo -e "${RED}Error: Unable to connect to GitHub releases API.${NC}"
    exit 1
fi

LATEST_TAG=$(echo "${RELEASE_JSON}" | grep -Po '"tag_name":\s*"\K[^"]*' || true)
if [ -z "${LATEST_TAG}" ]; then
    echo -e "${RED}Error: Could not determine latest release tag.${NC}"
    exit 1
fi

echo -e "Latest release on GitHub: ${GREEN}${LATEST_TAG}${NC}"

TARBALL_URL="https://github.com/${REPO}/archive/refs/tags/${LATEST_TAG}.tar.gz"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

echo -e "Downloading ${TARBALL_URL}..."
curl -sSL "${TARBALL_URL}" -o "${TMP_DIR}/release.tar.gz"

echo "Extracting release files..."
tar -xzf "${TMP_DIR}/release.tar.gz" -C "${TMP_DIR}"

EXTRACTED_DIR=$(find "${TMP_DIR}" -mindepth 1 -maxdepth 1 -type d | head -n 1)
if [ -z "${EXTRACTED_DIR}" ] || [ ! -d "${EXTRACTED_DIR}" ]; then
    echo -e "${RED}Error: Failed to find extracted archive directory.${NC}"
    exit 1
fi

if [ -f "${EXTRACTED_DIR}/install.sh" ]; then
    echo "Running installer..."
    bash "${EXTRACTED_DIR}/install.sh"
else
    echo "Updating files in ${BIN_DIR}..."
    mkdir -p "${BIN_DIR}" "${APPS_DIR}" "${ICONS_DIR}"
    for f in zen_updater_gui.py update_zen.sh check_zen_update.sh zen_backup.tarignore; do
        if [ -f "${EXTRACTED_DIR}/${f}" ]; then
            cp -f "${EXTRACTED_DIR}/${f}" "${BIN_DIR}/${f}"
            chmod +x "${BIN_DIR}/${f}"
        fi
    done
fi

if [ -f "${BIN_DIR}/zen_updater_gui.py" ]; then
    python3 -m py_compile "${BIN_DIR}/zen_updater_gui.py"
fi

echo -e "\n${GREEN}===============================================${NC}"
echo -e "${GREEN}Zen Updater successfully updated to ${LATEST_TAG}!${NC}"
echo -e "Executable location: ${BIN_DIR}/zen_updater_gui.py"
echo -e "${GREEN}===============================================${NC}"
