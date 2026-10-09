#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Zen Browser Safe Update Script
# Updates the official tarball installation while preserving isolated profile
# hard links and desktop icon configurations.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.tarball-installations/zen"
TEMP_DIR=""

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

cleanup() {
    if [ -n "${TEMP_DIR:-}" ] && [ -d "${TEMP_DIR}" ]; then
        rm -rf "${TEMP_DIR}"
    fi
}
trap cleanup EXIT

echo -e "${CYAN}===============================================${NC}"
echo -e "${CYAN}         Zen Browser Safe Updater              ${NC}"
echo -e "${CYAN}===============================================${NC}"

# Parse flags
FORCE_UPDATE_FLAG=false
BACKUP_FLAG=true

while [ $# -gt 0 ]; do
    case "$1" in
        -f|--force|-y|--yes)
            FORCE_UPDATE_FLAG=true
            shift
            ;;
        --no-backup)
            BACKUP_FLAG=false
            shift
            ;;
        --backup)
            BACKUP_FLAG=true
            shift
            ;;
        -d|--install-dir)
            if [ -n "${2:-}" ]; then
                INSTALL_DIR="$2"
                shift 2
            else
                shift
            fi
            ;;
        *)
            shift
            ;;
    esac
done

APP_INI="${INSTALL_DIR}/application.ini"

# 1. Determine Current and Latest Versions
CURRENT_VER="Unknown"
if [ -f "${APP_INI}" ]; then
    CURRENT_VER=$(grep "^Version=" "${APP_INI}" | cut -d'=' -f2 | tr -d '[:space:]')
fi
echo -e "Current installed version: ${BOLD}${CURRENT_VER}${NC}"

echo -e "\nChecking latest version from GitHub..."
LATEST_VER=$(curl -sIL -o /dev/null -w '%{url_effective}' "https://github.com/zen-browser/desktop/releases/latest" 2>/dev/null | sed 's#.*/##' | tr -d '[:space:]' || true)

if [ -z "${LATEST_VER}" ]; then
    UPDATE_XML=$(curl -s --max-time 10 "https://updates.zen-browser.app/updates/browser/Linux_x86_64-gcc3/release/update.xml" || true)
    LATEST_VER=$(echo "${UPDATE_XML}" | sed -n 's/.*displayVersion="\([^"]*\)".*/\1/p' | head -n1 | tr -d '[:space:]')
fi

if [ -z "${LATEST_VER}" ]; then
    echo -e "${YELLOW}Could not fetch version from redirect or update.xml, checking GitHub API...${NC}"
    LATEST_VER=$(curl -s https://api.github.com/repos/zen-browser/desktop/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' | tr -d '[:space:]' || true)
fi

echo -e "Latest available version : ${BOLD}${LATEST_VER}${NC}"

if [ "${CURRENT_VER}" == "${LATEST_VER}" ]; then
    echo -e "\n${GREEN}✓ Zen Browser is already up to date! (${CURRENT_VER})${NC}"
    if [ "${FORCE_UPDATE_FLAG}" = true ]; then
        echo "Force update requested. Proceeding with update/re-install..."
    else
        read -r -p "Do you want to re-install/refresh anyway? [y/N] " FORCE_UPDATE
        if [[ ! "${FORCE_UPDATE}" =~ ^[Yy] ]]; then
            echo "Refreshing profile links and policies..."
            for custom_bin in zen-youtube qbittorrent-webui zen-qbittorrent zen-bin; do
                rm -f "${INSTALL_DIR}/${custom_bin}" 2>/dev/null || true
                ln "${INSTALL_DIR}/zen" "${INSTALL_DIR}/${custom_bin}" 2>/dev/null || cp -a "${INSTALL_DIR}/zen" "${INSTALL_DIR}/${custom_bin}" 2>/dev/null || true
            done
            mkdir -p "${INSTALL_DIR}/distribution"
            cat << 'EOF' > "${INSTALL_DIR}/distribution/policies.json"
{
  "policies": {
    "DisableAppUpdate": true
  }
}
EOF
            echo "Profile links and policies are up to date. Exiting."
            exit 0
        fi
    fi
fi

# 2. Close / terminate all running Zen instances
SCRIPT_PID="$$"
if pgrep -f "^${INSTALL_DIR}/" > /dev/null 2>&1 || pgrep -x "zen|zen-bin|zen-browser|zen-youtube|qbittorrent-web.*" > /dev/null 2>&1; then
    echo -e "\n${CYAN}Closing all running Zen Browser instances...${NC}"
    killall zen zen-youtube qbittorrent-webui qbittorrent-web zen-bin zen-browser 2>/dev/null || true
    pkill --signal 15 -f "^${INSTALL_DIR}/" 2>/dev/null || true

    # Wait up to 5 seconds for clean database/session flush
    for i in {1..5}; do
        if ! pgrep -f "^${INSTALL_DIR}/" > /dev/null 2>&1 && ! pgrep -x "zen|zen-bin|zen-browser|zen-youtube|qbittorrent-web.*" > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done

    # Force kill if any browser process is still hanging
    if pgrep -f "^${INSTALL_DIR}/" > /dev/null 2>&1 || pgrep -x "zen|zen-bin|zen-browser|zen-youtube|qbittorrent-web.*" > /dev/null 2>&1; then
        echo -e "${YELLOW}Force terminating remaining processes...${NC}"
        killall -9 zen zen-youtube qbittorrent-webui qbittorrent-web zen-bin zen-browser 2>/dev/null || true
        pkill -9 -f "^${INSTALL_DIR}/" 2>/dev/null || true
        sleep 1
    fi
    echo -e "${GREEN}✓ All Zen instances closed.${NC}"
fi

# 2.5 Pre-Update Profile Safety Snapshot
if [ "${BACKUP_FLAG}" = true ] && [ -d "${HOME}/.zen" ]; then
    echo -e "\n${CYAN}[Safety Backup] Creating snapshot of all profiles in ~/.zen...${NC}"
    BACKUP_DIR="${HOME}/.zen-backups"
    mkdir -p "${BACKUP_DIR}"
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_FILE="${BACKUP_DIR}/zen-backup-${TIMESTAMP}-v${CURRENT_VER}.tar.zst"
    TARIGNORE="${SCRIPT_DIR}/zen_backup.tarignore"
    
    if [ -f "${TARIGNORE}" ]; then
        (tar --exclude-from="${TARIGNORE}" -C "${HOME}" -c ".zen" || [ $? -eq 1 ]) | zstd -3 -T0 -q -o "${BACKUP_FILE}"
    else
        (tar -C "${HOME}" -c ".zen" || [ $? -eq 1 ]) | zstd -3 -T0 -q -o "${BACKUP_FILE}"
    fi
    
    BACKUP_SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
    echo -e "${GREEN}✓ Safety backup created: ${BACKUP_FILE} (${BACKUP_SIZE})${NC}"
    
    # Automatically prune older backups, keeping only the 2 most recent
    OLD_BACKUPS=$(ls -1t "${BACKUP_DIR}"/zen-backup-*.tar.zst 2>/dev/null | tail -n +3 || true)
    if [ -n "${OLD_BACKUPS}" ]; then
        echo "${OLD_BACKUPS}" | xargs -r rm -f
        echo -e "  (Pruned older snapshots, keeping the 2 most recent)"
    fi
fi

# 3. Download the latest tarball
ARCH=$(uname -m)
case "${ARCH}" in
    x86_64) ARCH_STR="x86_64" ;;
    aarch64|arm64) ARCH_STR="aarch64" ;;
    *)
        echo -e "${RED}Unsupported architecture: ${ARCH}${NC}"
        exit 1
        ;;
esac

DOWNLOAD_URL="https://github.com/zen-browser/desktop/releases/latest/download/zen.linux-${ARCH_STR}.tar.xz"
TEMP_DIR=$(mktemp -d /tmp/zen-update-XXXXXX)
TAR_FILE="${TEMP_DIR}/zen.tar.xz"

echo -e "\n${CYAN}[1/3] Downloading ${LATEST_VER}...${NC}"
curl -L --progress-bar -o "${TAR_FILE}" "${DOWNLOAD_URL}" 2>&1

# 4. Extract and deploy
echo -e "\n${CYAN}[2/3] Extracting and updating installation files...${NC}"
tar -xf "${TAR_FILE}" -C "${TEMP_DIR}"

if [ ! -d "${TEMP_DIR}/zen" ]; then
    echo -e "${RED}Error: Extraction failed; unexpected archive structure.${NC}"
    exit 1
fi

mkdir -p "${INSTALL_DIR}"
# Copy new files over existing directory (preserves any custom files not in archive)
cp -a "${TEMP_DIR}/zen/"* "${INSTALL_DIR}/"

# 5. Re-link isolated profile binaries (CRITICAL for taskbar & icon stability)
echo -e "\n${CYAN}[3/3] Re-linking isolated profile binaries...${NC}"
for custom_bin in zen-youtube qbittorrent-webui zen-qbittorrent zen-bin; do
    rm -f "${INSTALL_DIR}/${custom_bin}" 2>/dev/null || true
    ln "${INSTALL_DIR}/zen" "${INSTALL_DIR}/${custom_bin}" 2>/dev/null || cp -a "${INSTALL_DIR}/zen" "${INSTALL_DIR}/${custom_bin}" 2>/dev/null || true
done

# Dynamically discover and re-link any custom profile binaries referenced in user desktop files
if [ -d "${HOME}/.local/share/applications" ]; then
    for dfile in "${HOME}/.local/share/applications"/*.desktop; do
        [ -f "${dfile}" ] || continue
        target_bin=$(grep -E "^Exec=${INSTALL_DIR}/" "${dfile}" 2>/dev/null | head -n1 | sed -E "s|^Exec=${INSTALL_DIR}/([^ \"']+).*|\1|" || true)
        if [ -n "${target_bin}" ] && [ "${target_bin}" != "zen" ]; then
            rm -f "${INSTALL_DIR}/${target_bin}" 2>/dev/null || true
            ln "${INSTALL_DIR}/zen" "${INSTALL_DIR}/${target_bin}" 2>/dev/null || cp -a "${INSTALL_DIR}/zen" "${INSTALL_DIR}/${target_bin}" 2>/dev/null || true
        fi
    done
fi

# 6. Ensure in-browser background updater does not desync profile hardlinks
mkdir -p "${INSTALL_DIR}/distribution"
cat << 'EOF' > "${INSTALL_DIR}/distribution/policies.json"
{
  "policies": {
    "DisableAppUpdate": true
  }
}
EOF

# Refresh desktop caches
update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
kbuildsycoca6 --noincremental >/dev/null 2>&1 || true

echo -e "\n${GREEN}===============================================${NC}"
echo -e "${GREEN}✓ Zen Browser successfully updated to ${LATEST_VER}!${NC}"
echo -e "  - Main executable updated: ${INSTALL_DIR}/zen"
echo -e "  - Profile hardlink refreshed: ${INSTALL_DIR}/zen-youtube"
echo -e "  - Profile hardlink refreshed: ${INSTALL_DIR}/qbittorrent-webui"
echo -e "  - All taskbar pins, custom icons, and profiles preserved."
echo -e "${GREEN}===============================================${NC}"

if [ -t 0 ]; then
    echo ""
    read -r -p "Press Enter to close..."
fi
