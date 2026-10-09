#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANDIDATES=(
    "${HOME}/.tarball-installations/zen/application.ini"
    "${HOME}/.local/share/zen/application.ini"
    "${HOME}/Applications/zen/application.ini"
    "${HOME}/.local/opt/zen/application.ini"
    "${HOME}/.zen-browser/application.ini"
    "/opt/zen/application.ini"
)

APP_INI=""
for cand in "${CANDIDATES[@]}"; do
    if [ -f "${cand}" ]; then
        APP_INI="${cand}"
        break
    fi
done

[ -n "${APP_INI}" ] || exit 0

CURRENT_VER=$(grep "^Version=" "${APP_INI}" | cut -d'=' -f2 | tr -d '[:space:]')

# Fetch latest release directly from GitHub redirect (authoritative tarball source, no API rate limits)
LATEST_VER=$(curl -sIL -o /dev/null -w '%{url_effective}' "https://github.com/zen-browser/desktop/releases/latest" 2>/dev/null | sed 's#.*/##' | tr -d '[:space:]' || true)

# Fallback to update.xml if GitHub redirect fails
if [ -z "${LATEST_VER}" ]; then
    UPDATE_XML=$(curl -s --max-time 10 "https://updates.zen-browser.app/updates/browser/Linux_x86_64-gcc3/release/update.xml" || true)
    LATEST_VER=$(echo "${UPDATE_XML}" | sed -n 's/.*displayVersion="\([^"]*\)".*/\1/p' | head -n1 | tr -d '[:space:]')
fi

if [ -n "${LATEST_VER}" ] && [ "${LATEST_VER}" != "${CURRENT_VER}" ]; then
    export DISPLAY="${DISPLAY:-:0}"
    export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

    CACHE_DIR="${XDG_CACHE_HOME:-${HOME}/.cache}"
    mkdir -p "${CACHE_DIR}"
    NID_FILE="${CACHE_DIR}/zen_update_notification_id"

    EXTRA_ARGS=()
    if [ -f "${NID_FILE}" ]; then
        OLD_NID=$(cat "${NID_FILE}" 2>/dev/null || true)
        if [[ "${OLD_NID}" =~ ^[0-9]+$ ]]; then
            EXTRA_ARGS+=("-r" "${OLD_NID}")
        fi
    fi

    ICON="${SCRIPT_DIR}/assets/icon.png"
    if [ ! -f "${ICON}" ]; then
        ICON="${HOME}/.local/share/icons/zen-updater.png"
    fi
    if [ ! -f "${ICON}" ]; then
        ICON="${HOME}/Pictures/Avatar/Square_App_Icons/Zen-Browser/zen_browser_ice_steel_128.png"
    fi
    if [ ! -f "${ICON}" ]; then
        if [ -f "${HOME}/.tarball-installations/zen/browser/chrome/icons/default/default128.png" ]; then
            ICON="${HOME}/.tarball-installations/zen/browser/chrome/icons/default/default128.png"
        else
            ICON="zen-browser"
        fi
    fi
    NEW_NID=$(notify-send -p \
        --app-name="Zen Browser" \
        --icon="${ICON}" \
        --urgency=critical \
        --expire-time=0 \
        "${EXTRA_ARGS[@]}" \
        "Zen Browser Update Available" \
        "Version ${LATEST_VER} is available! (Current: ${CURRENT_VER})" || true)

    if [[ "${NEW_NID}" =~ ^[0-9]+$ ]]; then
        echo "${NEW_NID}" > "${NID_FILE}"
    fi
fi
