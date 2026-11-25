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

FORCE_UPDATE_FLAG=false
BACKUP_FLAG=true
BACKUP_ONLY_FLAG=false

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
        --backup-only)
            BACKUP_ONLY_FLAG=true
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

CURRENT_VER="Unknown"
if [ -f "${APP_INI}" ]; then
    CURRENT_VER=$(grep "^Version=" "${APP_INI}" | cut -d'=' -f2 | tr -d '[:space:]' || echo "Unknown")
fi
echo -e "Current installed version: ${BOLD}${CURRENT_VER}${NC}"

discover_custom_bins() {
    python3 - "${INSTALL_DIR}" << 'PYEOF'
import glob, os, shlex, sys

install_dir = os.path.normpath(sys.argv[1])
bins = set()
if os.path.lexists(os.path.join(install_dir, "zen-bin")):
    bins.add("zen-bin")

desktop_dir = os.path.expanduser("~/.local/share/applications")
if os.path.isdir(desktop_dir):
    for dfile in glob.glob(os.path.join(desktop_dir, "*.desktop")):
        try:
            with open(dfile, "r", encoding="utf-8", errors="ignore") as f:
                for raw in f:
                    line = raw.strip()
                    if not line.startswith("Exec="):
                        continue
                    try:
                        parts = shlex.split(line[5:].strip())
                    except ValueError:
                        parts = line[5:].strip().split()
                    if parts and os.path.normpath(os.path.dirname(parts[0])) == install_dir:
                        bname = os.path.basename(parts[0])
                        if bname and bname != "zen":
                            bins.add(bname)
        except OSError:
            pass

for b in sorted(bins):
    print(b)
PYEOF
}

refresh_links_and_policy() {
    local relinked_list=()
    while IFS= read -r custom_bin; do
        [ -n "${custom_bin}" ] || continue
        rm -f "${INSTALL_DIR}/${custom_bin}" 2>/dev/null || true
        if ln "${INSTALL_DIR}/zen" "${INSTALL_DIR}/${custom_bin}" 2>/dev/null || cp -a "${INSTALL_DIR}/zen" "${INSTALL_DIR}/${custom_bin}" 2>/dev/null; then
            relinked_list+=("${custom_bin}")
        fi
    done < <(discover_custom_bins)

    mkdir -p "${INSTALL_DIR}/distribution"
    cat << 'EOF' > "${INSTALL_DIR}/distribution/policies.json"
{
  "policies": {
    "DisableAppUpdate": true
  }
}
EOF

    if [ "${#relinked_list[@]}" -gt 0 ]; then
        for rb in "${relinked_list[@]}"; do
            echo -e "  - Profile hardlink refreshed: ${INSTALL_DIR}/${rb}"
        done
    fi
}

create_profile_backup() {
    if ! command -v zstd >/dev/null 2>&1; then
        echo -e "${YELLOW}Warning: 'zstd' is not installed; skipping profile backup.${NC}"
        return 0
    fi

    local backup_targets=()
    [ -d "${HOME}/.zen" ] && backup_targets+=(".zen")
    [ -d "${HOME}/.config/zen" ] && backup_targets+=(".config/zen")

    if [ "${#backup_targets[@]}" -eq 0 ]; then
        echo -e "${YELLOW}No existing ~/.zen or ~/.config/zen profile directories found to back up.${NC}"
        return 0
    fi

    echo -e "\n${CYAN}[Safety Backup] Creating snapshot of Zen profiles...${NC}"
    local backup_dir="${HOME}/.zen-backups"
    mkdir -p "${backup_dir}"
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    local backup_file="${backup_dir}/zen-backup-${timestamp}-v${CURRENT_VER}.tar.zst"
    local tmp_backup="${backup_file}.tmp"
    local tarignore="${SCRIPT_DIR}/zen_backup.tarignore"

    local tar_args=(-C "${HOME}" -c)
    if [ -f "${tarignore}" ]; then
        tar_args=(--exclude-from="${tarignore}" "${tar_args[@]}")
    fi

    if (tar "${tar_args[@]}" "${backup_targets[@]}" || [ $? -eq 1 ]) | zstd -3 -T0 -q -o "${tmp_backup}"; then
        mv -f "${tmp_backup}" "${backup_file}"
    else
        rm -f "${tmp_backup}"
        echo -e "${RED}Error: Profile safety backup failed.${NC}"
        return 1
    fi

    local backup_size
    backup_size=$(du -sh "${backup_file}" | cut -f1)
    echo -e "${GREEN}✓ Safety backup created: ${backup_file} (${backup_size})${NC}"

    local old_backups
    old_backups=$(ls -1t "${backup_dir}"/zen-backup-*.tar.zst 2>/dev/null | tail -n +3 || true)
    if [ -n "${old_backups}" ]; then
        echo "${old_backups}" | xargs -d '\n' -r rm -f
        echo -e "  (Pruned older snapshots, keeping the 2 most recent)"
    fi
}

if [ "${BACKUP_ONLY_FLAG}" = true ]; then
    create_profile_backup
    exit 0
fi

close_running_zen() {
    if pgrep -f "^${INSTALL_DIR}/" > /dev/null 2>&1 || pgrep -x "zen|zen-bin|zen-browser|zen-youtube|qbittorrent-web.*" > /dev/null 2>&1; then
        echo -e "\n${CYAN}Closing all running Zen Browser instances...${NC}"
        pkill -15 -x "zen|zen-bin|zen-browser|zen-youtube|qbittorrent-web.*" 2>/dev/null || true
        pkill -15 -f "^${INSTALL_DIR}/" 2>/dev/null || true

        for _ in {1..5}; do
            if ! pgrep -f "^${INSTALL_DIR}/" > /dev/null 2>&1 && ! pgrep -x "zen|zen-bin|zen-browser|zen-youtube|qbittorrent-web.*" > /dev/null 2>&1; then
                break
            fi
            sleep 1
        done

        if pgrep -f "^${INSTALL_DIR}/" > /dev/null 2>&1 || pgrep -x "zen|zen-bin|zen-browser|zen-youtube|qbittorrent-web.*" > /dev/null 2>&1; then
            echo -e "${YELLOW}Force terminating remaining processes...${NC}"
            pkill -9 -x "zen|zen-bin|zen-browser|zen-youtube|qbittorrent-web.*" 2>/dev/null || true
            pkill -9 -f "^${INSTALL_DIR}/" 2>/dev/null || true
            sleep 1
        fi
        echo -e "${GREEN}✓ All Zen instances closed.${NC}"
    fi
}

ARCH=$(uname -m)
case "${ARCH}" in
    x86_64)
        ARCH_STR="x86_64"
        XML_ARCH="Linux_x86_64-gcc3"
        ;;
    aarch64|arm64)
        ARCH_STR="aarch64"
        XML_ARCH="Linux_aarch64-gcc3"
        ;;
    *)
        echo -e "${RED}Unsupported architecture: ${ARCH}${NC}"
        exit 1
        ;;
esac

# 1. Determine Latest Version
echo -e "\nChecking latest version from GitHub..."
LATEST_VER=""
EFFECTIVE_URL=$(curl -fsIL --connect-timeout 5 --max-time 10 -o /dev/null -w '%{url_effective}' "https://github.com/zen-browser/desktop/releases/latest" 2>/dev/null || true)
if [[ "${EFFECTIVE_URL}" == *"/releases/tag/"* ]]; then
    LATEST_VER="${EFFECTIVE_URL##*/}"
fi

if [ -z "${LATEST_VER}" ]; then
    UPDATE_XML=$(curl -fs --connect-timeout 5 --max-time 10 "https://updates.zen-browser.app/updates/browser/${XML_ARCH}/release/update.xml" 2>/dev/null || true)
    LATEST_VER=$(echo "${UPDATE_XML}" | sed -n 's/.*displayVersion="\([^"]*\)".*/\1/p' | head -n1 | tr -d '[:space:]')
fi

if [ -z "${LATEST_VER}" ]; then
    echo -e "${YELLOW}Could not fetch version from redirect or update.xml, checking GitHub API...${NC}"
    LATEST_VER=$(curl -fs --connect-timeout 5 --max-time 10 https://api.github.com/repos/zen-browser/desktop/releases/latest 2>/dev/null | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' | tr -d '[:space:]' || true)
fi

if [ -z "${LATEST_VER}" ] || [ "${LATEST_VER}" = "latest" ]; then
    echo -e "${RED}Error: Could not determine latest version. Please check your internet connection.${NC}"
    exit 1
fi

echo -e "Latest available version : ${BOLD}${LATEST_VER}${NC}"

is_update_needed=true
if [ "${CURRENT_VER}" != "Unknown" ]; then
    is_update_needed=$(python3 - "${LATEST_VER}" "${CURRENT_VER}" << 'PYEOF'
import re, sys

def parse(v):
    c = v.strip().lstrip("vV")
    m = re.match(r'^(\d+(?:\.\d+)*)(.*)$', c)
    if not m:
        return None
    core = tuple(int(x) for x in m.group(1).split('.'))
    rest = m.group(2).lower().strip("-_ ")
    rank = 0 if rest.startswith("t") else 1 if rest.startswith("a") else 2 if rest.startswith("b") else 3 if rest.startswith("rc") else 4
    snums = tuple(int(n) for n in re.findall(r'\d+', rest))
    return (core, rank, snums)

pl, pc = parse(sys.argv[1]), parse(sys.argv[2])
if pl is None or pc is None:
    print("true" if sys.argv[1].strip() != sys.argv[2].strip() else "false")
else:
    print("true" if pl > pc else "false")
PYEOF
)
fi

if [ "${is_update_needed}" = "false" ]; then
    echo -e "\n${GREEN}✓ Zen Browser is already up to date! (${CURRENT_VER})${NC}"
    if [ "${FORCE_UPDATE_FLAG}" = true ]; then
        echo "Force update requested. Proceeding with update/re-install..."
    else
        read -r -p "Do you want to re-install/refresh anyway? [y/N] " FORCE_UPDATE
        if [[ ! "${FORCE_UPDATE}" =~ ^[Yy] ]]; then
            echo "Refreshing profile links and policies..."
            refresh_links_and_policy
            echo "Profile links and policies are up to date. Exiting."
            exit 0
        fi
    fi
fi

# 2. Download & verify tarball BEFORE killing running Zen instances
DOWNLOAD_URL="https://github.com/zen-browser/desktop/releases/download/${LATEST_VER}/zen.linux-${ARCH_STR}.tar.xz"
TEMP_DIR=$(mktemp -d /tmp/zen-update-XXXXXX)
TAR_FILE="${TEMP_DIR}/zen.tar.xz"

echo -e "\n${CYAN}[1/4] Downloading ${LATEST_VER}...${NC}"
if ! curl -fL --progress-bar -o "${TAR_FILE}" "${DOWNLOAD_URL}" 2>&1; then
    echo -e "${YELLOW}Tagged asset URL failed; retrying latest release redirect...${NC}"
    FALLBACK_URL="https://github.com/zen-browser/desktop/releases/latest/download/zen.linux-${ARCH_STR}.tar.xz"
    curl -fL --progress-bar -o "${TAR_FILE}" "${FALLBACK_URL}" 2>&1
fi

if ! tar -tf "${TAR_FILE}" >/dev/null 2>&1; then
    echo -e "${RED}Error: Downloaded archive failed integrity verification.${NC}"
    exit 1
fi

echo -e "\n${CYAN}[2/4] Extracting archive to staging directory...${NC}"
tar -xf "${TAR_FILE}" -C "${TEMP_DIR}"
if [ ! -d "${TEMP_DIR}/zen" ] || [ ! -f "${TEMP_DIR}/zen/zen" ]; then
    echo -e "${RED}Error: Extraction failed; unexpected archive structure.${NC}"
    exit 1
fi

# 3. Close running instances & create safety snapshot cleanly before deploying
close_running_zen

if [ "${BACKUP_FLAG}" = true ]; then
    create_profile_backup
fi

# 4. Deploy staged files (removing stale files from old versions while preserving distribution/)
echo -e "\n${CYAN}[3/4] Deploying files to ${INSTALL_DIR}...${NC}"
mkdir -p "${INSTALL_DIR}"
if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete --exclude='distribution' "${TEMP_DIR}/zen/" "${INSTALL_DIR}/"
else
    cp -a "${TEMP_DIR}/zen/"* "${INSTALL_DIR}/"
fi

# 5. Re-link isolated profile binaries & ensure disable-app-update policy
echo -e "\n${CYAN}[4/4] Re-linking isolated profile binaries...${NC}"
refresh_links_and_policy

# 6. Ensure Zen Browser Desktop Entry and Application Icons exist
DESKTOP_ENTRY="${HOME}/.local/share/applications/zen-browser.desktop"
if [ ! -f "${DESKTOP_ENTRY}" ]; then
    echo -e "\n${CYAN}Creating desktop entry and application icons...${NC}"
    mkdir -p "${HOME}/.local/share/applications" "${HOME}/.local/share/icons/hicolor/128x128/apps"

    mkdir -p "${HOME}/.local/share/icons"
    for sz in 16 32 48 64 128; do
        src_icon="${INSTALL_DIR}/browser/chrome/icons/default/default${sz}.png"
        if [ -f "${src_icon}" ]; then
            dest_dir="${HOME}/.local/share/icons/hicolor/${sz}x${sz}/apps"
            mkdir -p "${dest_dir}"
            cp -f "${src_icon}" "${dest_dir}/zen-browser.png" 2>/dev/null || true
        fi
    done
    if [ -f "${INSTALL_DIR}/browser/chrome/icons/default/default128.png" ]; then
        cp -f "${INSTALL_DIR}/browser/chrome/icons/default/default128.png" "${HOME}/.local/share/icons/zen-browser.png" 2>/dev/null || true
        mkdir -p "${HOME}/.local/share/icons/hicolor/256x256/apps"
        cp -f "${INSTALL_DIR}/browser/chrome/icons/default/default128.png" "${HOME}/.local/share/icons/hicolor/256x256/apps/zen-browser.png" 2>/dev/null || true
    fi

    cat << EOF > "${DESKTOP_ENTRY}"
[Desktop Entry]
Version=1.0
Type=Application
Name=Zen Browser
GenericName=Web Browser
Comment=Experience tranquillity while browsing the web without people tracking you!
Keywords=Internet;WWW;Browser;Web;Explorer;zen;
Exec=${INSTALL_DIR}/zen %u
Icon=zen-browser
Terminal=false
StartupNotify=true
StartupWMClass=zen
X-KDE-Wayland-AppId=zen
Categories=Network;WebBrowser;
MimeType=text/html;text/xml;application/xhtml+xml;x-scheme-handler/http;x-scheme-handler/https;application/x-xpinstall;application/pdf;application/json;
Actions=new-window;new-private-window;profile-manager-window;

[Desktop Action new-window]
Name=Open a New Window
Exec=${INSTALL_DIR}/zen --new-window %u

[Desktop Action new-private-window]
Name=Open a New Private Window
Exec=${INSTALL_DIR}/zen --private-window %u

[Desktop Action profile-manager-window]
Name=Open the Profile Manager
Exec=${INSTALL_DIR}/zen --ProfileManager
EOF
    chmod +x "${DESKTOP_ENTRY}"
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
    fi
fi

update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
kbuildsycoca6 --noincremental >/dev/null 2>&1 || true

echo -e "\n${GREEN}===============================================${NC}"
echo -e "${GREEN}✓ Zen Browser successfully updated to ${LATEST_VER}!${NC}"
echo -e "  - Main executable updated: ${INSTALL_DIR}/zen"
echo -e "  - All taskbar pins, custom icons, and profiles preserved."
echo -e "  - Tip: To set any profile as default, launch it, visit"
echo -e "         about:profiles in Zen, and click 'Set as default profile'."
echo -e "${GREEN}===============================================${NC}"

if [ -t 0 ]; then
    echo ""
    read -r -p "Press Enter to close..."
fi
