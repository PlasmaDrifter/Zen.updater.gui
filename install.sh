#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Zen Updater & Background Checker Installer
# Portable installer for user-level Linux environments
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
SYSTEMD_DIR="${HOME}/.config/systemd/user"

echo "Installing Zen Updater Suite..."

# 1. Create target directories
mkdir -p "${BIN_DIR}" "${APPS_DIR}" "${SYSTEMD_DIR}"

# 2. Check for PyQt6
if ! python3 -c "import PyQt6" >/dev/null 2>&1; then
    echo "Warning: PyQt6 is not detected. Please install it via your package manager or pip:"
    echo "  pip install PyQt6   OR   sudo dnf/apt/pacman install python3-pyqt6"
fi

# 3. Copy scripts to ~/.local/bin
echo "Copying scripts to ${BIN_DIR}..."
cp -f "${SCRIPT_DIR}/zen_updater_gui.py" "${BIN_DIR}/zen_updater_gui.py"
cp -f "${SCRIPT_DIR}/update_zen.sh" "${BIN_DIR}/update_zen.sh"
cp -f "${SCRIPT_DIR}/check_zen_update.sh" "${BIN_DIR}/check_zen_update.sh"
cp -f "${SCRIPT_DIR}/zen_backup.tarignore" "${BIN_DIR}/zen_backup.tarignore"

chmod +x "${BIN_DIR}/zen_updater_gui.py"
chmod +x "${BIN_DIR}/update_zen.sh"
chmod +x "${BIN_DIR}/check_zen_update.sh"

# Create handy command symlink: zen-updater
ln -sf "${BIN_DIR}/zen_updater_gui.py" "${BIN_DIR}/zen-updater"

# 4. Install Application Icon & Desktop Launcher
echo "Installing application icon and desktop launcher..."
ICONS_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
mkdir -p "${ICONS_DIR}" "${HOME}/.local/share/icons"
if [ -f "${SCRIPT_DIR}/assets/icon.png" ]; then
    cp -f "${SCRIPT_DIR}/assets/icon.png" "${HOME}/.local/share/icons/zen-updater.png"
    cp -f "${SCRIPT_DIR}/assets/icon.png" "${ICONS_DIR}/zen-updater.png"
fi

sed "s|Exec=zen_updater_gui.py|Exec=${BIN_DIR}/zen_updater_gui.py|g" \
    "${SCRIPT_DIR}/zen-updater.desktop" > "${APPS_DIR}/zen-updater.desktop"
chmod +x "${APPS_DIR}/zen-updater.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPS_DIR}" >/dev/null 2>&1 || true
fi

# 5. Install Systemd Background Checker Service & Timer
echo "Configuring systemd background update check timer..."
cp -f "${SCRIPT_DIR}/systemd/zen-update-check.service" "${SYSTEMD_DIR}/zen-update-check.service"
cp -f "${SCRIPT_DIR}/systemd/zen-update-check.timer" "${SYSTEMD_DIR}/zen-update-check.timer"

systemctl --user daemon-reload
systemctl --user enable --now zen-update-check.timer

echo ""
echo "Installation complete!"
echo "  - GUI Launcher: Run 'zen-updater' in terminal or launch from your application menu"
echo "  - Update Script: ${BIN_DIR}/update_zen.sh"
echo "  - Background Timer: active (checks every 6 hours)"
echo "    Check status with: systemctl --user status zen-update-check.timer"
