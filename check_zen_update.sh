#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANDIDATES=(
    "${HOME}/.tarball-installations/zen/application.ini"
    "${HOME}/.local/share/zen/application.ini"
    "${HOME}/Applications/zen/application.ini"
    "${HOME}/.local/opt/zen/application.ini"
    "${HOME}/.zen-browser/application.ini"
    "${HOME}/zen/application.ini"
    "/opt/zen/application.ini"
    "/usr/lib/zen/application.ini"
    "/usr/lib64/zen/application.ini"
    "/usr/local/lib/zen/application.ini"
)

APP_INI=""
for cand in "${CANDIDATES[@]}"; do
    if [ -f "${cand}" ]; then
        APP_INI="${cand}"
        break
    fi
done

if [ -z "${APP_INI}" ]; then
    ZEN_BIN=$(command -v zen 2>/dev/null || command -v zen-browser 2>/dev/null || true)
    if [ -n "${ZEN_BIN}" ]; then
        REAL_DIR=$(dirname "$(readlink -f "${ZEN_BIN}")")
        if [ -f "${REAL_DIR}/application.ini" ]; then
            APP_INI="${REAL_DIR}/application.ini"
        fi
    fi
fi

[ -n "${APP_INI}" ] || exit 0
INSTALL_DIR=$(dirname "${APP_INI}")

CURRENT_VER=$(grep "^Version=" "${APP_INI}" | cut -d'=' -f2 | tr -d '[:space:]' || true)
[ -n "${CURRENT_VER}" ] || exit 0

case "$(uname -m)" in
    aarch64|arm64) XML_ARCH="Linux_aarch64-gcc3" ;;
    *) XML_ARCH="Linux_x86_64-gcc3" ;;
esac

# Fetch latest release directly from GitHub redirect (no API rate limits)
LATEST_VER=""
EFFECTIVE_URL=$(curl -fsIL --connect-timeout 5 --max-time 10 -o /dev/null -w '%{url_effective}' "https://github.com/zen-browser/desktop/releases/latest" 2>/dev/null || true)
if [[ "${EFFECTIVE_URL}" == *"/releases/tag/"* ]]; then
    LATEST_VER="${EFFECTIVE_URL##*/}"
fi

# Fallback to update.xml if GitHub redirect fails
if [ -z "${LATEST_VER}" ]; then
    UPDATE_XML=$(curl -fs --connect-timeout 5 --max-time 10 "https://updates.zen-browser.app/updates/browser/${XML_ARCH}/release/update.xml" 2>/dev/null || true)
    LATEST_VER=$(echo "${UPDATE_XML}" | sed -n 's/.*displayVersion="\([^"]*\)".*/\1/p' | head -n1 | tr -d '[:space:]')
fi

[ -n "${LATEST_VER}" ] && [ "${LATEST_VER}" != "latest" ] || exit 0

IS_NEWER=$(python3 - "${LATEST_VER}" "${CURRENT_VER}" << 'PYEOF'
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

if [ "${IS_NEWER}" = "true" ]; then
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

    ICON=""
    for icon_cand in \
        "${SCRIPT_DIR}/assets/icon.png" \
        "${HOME}/.local/share/icons/zen-updater.png" \
        "${INSTALL_DIR}/browser/chrome/icons/default/default128.png"; do
        if [ -f "${icon_cand}" ]; then
            ICON="${icon_cand}"
            break
        fi
    done
    [ -n "${ICON}" ] || ICON="zen-browser"

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
