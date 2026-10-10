#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Zen Updater & Background Checker Uninstaller
# Cleans up all files, desktop shortcuts, icons, and background timers
# ==============================================================================

BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
CONFIG_DIR="${HOME}/.config/zen-updater"
CACHE_FILE="${HOME}/.cache/zen_update_notification_id"

echo "Uninstalling Zen Updater Suite..."

# 1. Stop and disable systemd service and timer
if command -v systemctl >/dev/null 2>&1; then
    echo "Disabling and stopping systemd background update check timer..."
    systemctl --user stop zen-update-check.timer 2>/dev/null || true
    systemctl --user disable zen-update-check.timer 2>/dev/null || true
    systemctl --user stop zen-update-check.service 2>/dev/null || true
    systemctl --user daemon-reload 2>/dev/null || true
fi

# Remove systemd unit files
rm -f "${SYSTEMD_DIR}/zen-update-check.service"
rm -f "${SYSTEMD_DIR}/zen-update-check.timer"

# 2. Remove desktop launcher and application icons
echo "Removing desktop launcher and application icons..."
rm -f "${APPS_DIR}/zen-updater.desktop"
rm -f "${ICONS_DIR}/zen-updater.png"
rm -f "${ICONS_DIR}/hicolor/256x256/apps/zen-updater.png"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPS_DIR}" >/dev/null 2>&1 || true
fi

# 3. Remove installed binaries and helper scripts
echo "Removing scripts from ${BIN_DIR}..."
rm -f "${BIN_DIR}/zen-updater"
rm -f "${BIN_DIR}/zen_updater_gui.py"
rm -f "${BIN_DIR}/update_zen.sh"
rm -f "${BIN_DIR}/check_zen_update.sh"
rm -f "${BIN_DIR}/update_updater.sh"
rm -f "${BIN_DIR}/zen_backup.tarignore"

# 4. Remove notification cache
rm -f "${CACHE_FILE}"

# Optional prompt for configuration directory
if [ -d "${CONFIG_DIR}" ]; then
    echo "Removed application files. Configuration remains in ${CONFIG_DIR}."
    echo "To remove user settings completely, run: rm -rf '${CONFIG_DIR}'"
fi

echo ""
echo "Zen Updater Suite has been successfully uninstalled."
