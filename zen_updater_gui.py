#!/usr/bin/env python3
"""
Zen Browser Updater GUI
Provides a native Qt6 interface to check, backup, update, and launch Zen Browser profiles.
"""

import configparser
import glob
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from datetime import datetime

from PyQt6.QtCore import QPoint, QProcess, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

APP_VERSION = "v1.0.13"
APP_REPO = "PlasmaDrifter/Zen.updater.gui"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_TARBALL_DIR = os.path.expanduser("~/.tarball-installations/zen")
FLATPAK_APP_IDS = ("app.zen_browser.zen", "io.github.zen_browser.zen")
DEFAULT_TIMER_INTERVAL = "24h"

BANNER_STYLES = {
    "checking": ("#233549", "#79b8ff", "#334d69", None, None),
    "update": ("#163b26", "#a6f3a6", "#2ea043", "#1d4d32", "#3fb950"),
    "info": ("#13233a", "#79c0ff", "#214068", "#1a3354", "#388bfd"),
    "warning": ("#3b2300", "#f2cc60", "#bb8009", "#4c2e00", "#d29922"),
    "success": ("#1e3328", "#7ee787", "#2a4c3a", None, None),
    "error": ("#442727", "#ff8585", "#663333", None, None),
}

SMALL_HELP_BTN_QSS = """
    QPushButton {
        background-color: #21262d;
        color: #e3b341;
        border: 1.5px solid #d29922;
        border-radius: 8px;
        font-size: 10px;
        font-weight: bold;
        padding: 0px;
    }
    QPushButton:hover {
        background-color: #bb8009;
        color: #ffffff;
        border-color: #e3b341;
    }
"""

ACCORDION_TOGGLE_QSS = """
    QPushButton {
        text-align: left;
        background-color: #1e2530;
        border: 1px solid #334155;
        border-radius: 6px;
        color: #60a5fa;
        font-size: 12px;
        font-weight: bold;
        padding: 8px 12px;
    }
    QPushButton:hover {
        background-color: #263140;
        border-color: #475569;
        color: #93c5fd;
    }
"""

SECONDARY_BTN_QSS = """
    QPushButton {
        background-color: #21262d;
        border: 1px solid #30363d;
        border-radius: 5px;
        color: #c9d1d9;
        font-size: 12px;
        padding: 6px 14px;
    }
    QPushButton:hover {
        background-color: #30363d;
        color: #ffffff;
        border-color: #58a6ff;
    }
    QPushButton:disabled {
        background-color: #161b22;
        color: #484f58;
        border-color: #21262d;
    }
"""

GREEN_BTN_QSS = """
    QPushButton {
        background-color: rgba(46, 160, 67, 0.15);
        color: #a6f3a6;
        font-weight: bold;
        font-size: 12px;
        border: 1px solid #2ea043;
        border-radius: 5px;
        padding: 6px 18px;
    }
    QPushButton:hover {
        background-color: #2ea043;
        color: #ffffff;
        border-color: #3fb950;
    }
    QPushButton:disabled {
        background-color: #21262d;
        color: #6e7681;
        border-color: #30363d;
    }
"""

BLUE_BTN_QSS = """
    QPushButton {
        background-color: rgba(56, 139, 253, 0.15);
        color: #79c0ff;
        font-weight: bold;
        font-size: 12px;
        border: 1px solid #388bfd;
        border-radius: 5px;
        padding: 6px 18px;
    }
    QPushButton:hover {
        background-color: #388bfd;
        color: #ffffff;
        border-color: #58a6ff;
    }
    QPushButton:disabled {
        background-color: #21262d;
        color: #6e7681;
        border-color: #30363d;
    }
"""

AMBER_BTN_QSS = """
    QPushButton {
        background-color: rgba(210, 153, 34, 0.15);
        color: #f2cc60;
        font-weight: bold;
        font-size: 12px;
        border: 1px solid #bb8009;
        border-radius: 5px;
        padding: 6px 18px;
    }
    QPushButton:hover {
        background-color: #bb8009;
        color: #ffffff;
        border-color: #d29922;
    }
    QPushButton:disabled {
        background-color: #21262d;
        color: #6e7681;
        border-color: #30363d;
    }
"""

RED_OUTLINE_BTN_QSS = """
    QPushButton {
        background-color: #21262d;
        color: #ff7b72;
        font-weight: bold;
        font-size: 12px;
        border: 1px solid #da3633;
        border-radius: 5px;
        padding: 6px 18px;
    }
    QPushButton:hover {
        background-color: #30363d;
        color: #ffa198;
        border-color: #f85149;
    }
    QPushButton:disabled {
        background-color: #21262d;
        color: #6e7681;
        border-color: #30363d;
    }
"""


def get_cache_dir():
    """Return the XDG cache directory."""
    return os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")


def get_config_dir():
    """Return the Zen Updater configuration directory."""
    xdg_cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(xdg_cfg, "zen-updater")


def get_github_icon():
    """Return the GitHub icon from installed assets or embedded SVG fallback."""
    svg_file = os.path.join(SCRIPT_DIR, "assets", "github.svg")
    if os.path.isfile(svg_file):
        icon = QIcon(svg_file)
        if not icon.isNull():
            return icon
    installed_svg = os.path.expanduser("~/.local/share/icons/zen-updater-github.svg")
    if os.path.isfile(installed_svg):
        icon = QIcon(installed_svg)
        if not icon.isNull():
            return icon
    svg_data = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="#c9d1d9">'
        b'<path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 '
        b'0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-'
        b'.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.'
        b'105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-'
        b'.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-'
        b'1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 '
        b'5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.'
        b'57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>'
    )
    pm = QPixmap()
    pm.loadFromData(svg_data, "SVG")
    if not pm.isNull():
        return QIcon(pm)
    theme_icon = QIcon.fromTheme("github", QIcon.fromTheme("git"))
    if not theme_icon.isNull():
        return theme_icon
    return QIcon()


def load_app_settings():
    """Load persisted user preferences from settings.json."""
    path = os.path.join(get_config_dir(), "settings.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return {}


def save_app_setting(key, val):
    """Persist a single setting key into settings.json."""
    config_dir = get_config_dir()
    os.makedirs(config_dir, exist_ok=True)
    path = os.path.join(config_dir, "settings.json")
    settings = load_app_settings()
    settings[key] = val
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError as e:
        print("Error saving setting:", e, file=sys.stderr)


def parse_app_version(ver_str):
    """Parse an updater version tag such as v1.0.12 into a 3-integer tuple."""
    clean = re.sub(r'^[^\d]*', '', str(ver_str).strip())
    parts = []
    for part in clean.split('.'):
        digits = re.match(r'^\d+', part)
        if digits:
            parts.append(int(digits.group(0)))
        else:
            break
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer_app_version(latest_str, cur_str):
    """Return True if latest_str represents a newer Zen Updater version than cur_str."""
    if not latest_str or not cur_str:
        return False
    return parse_app_version(latest_str) > parse_app_version(cur_str)


def parse_zen_version(ver_str):
    """
    Parse Zen Browser version strings (e.g., 1.24.3b, 1.0.2-a.35, 1.25.0t, 1.24.3)
    into a comparable tuple: (core_numbers, stage_rank, suffix_numbers).
    """
    clean = str(ver_str or "").strip().lstrip("vV")
    if not clean or not any(ch.isdigit() for ch in clean):
        return None

    m = re.match(r'^(\d+(?:\.\d+)*)(.*)$', clean)
    if not m:
        return None

    core = tuple(int(x) for x in m.group(1).split('.'))
    rest = m.group(2).lower().strip("-_ ")

    stage_rank = 4  # Full release without pre-release tag
    if rest.startswith("t"):
        stage_rank = 0
    elif rest.startswith("a"):
        stage_rank = 1
    elif rest.startswith("b"):
        stage_rank = 2
    elif rest.startswith("rc"):
        stage_rank = 3

    suffix_nums = tuple(int(n) for n in re.findall(r'\d+', rest))
    return (core, stage_rank, suffix_nums)


def is_newer_zen_version(latest_str, cur_str):
    """Return True only when latest_str is strictly newer than cur_str."""
    if not latest_str or not cur_str:
        return False
    clean_lat = latest_str.strip()
    clean_cur = cur_str.strip()
    if clean_lat.lower() == "unknown" or clean_cur.lower() == "unknown":
        return False
    if clean_lat == clean_cur:
        return False
    parsed_latest = parse_zen_version(clean_lat)
    parsed_cur = parse_zen_version(clean_cur)
    if parsed_latest is None or parsed_cur is None:
        return clean_lat != clean_cur
    return parsed_latest > parsed_cur


def get_update_xml_arch():
    """Return the Mozilla/Zen update.xml architecture token for this host."""
    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64"):
        return "Linux_aarch64-gcc3"
    return "Linux_x86_64-gcc3"


def find_zen_icon():
    """Locate the application icon from repo assets, user icon dirs, or Zen install."""
    candidates = [
        os.path.join(SCRIPT_DIR, "assets", "icon.png"),
        os.path.join(SCRIPT_DIR, "assets", "zen-updater.png"),
        os.path.expanduser("~/.local/share/icons/zen-updater.png"),
        os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps/zen-updater.png"),
        os.path.expanduser("~/.tarball-installations/zen/browser/chrome/icons/default/default128.png"),
        os.path.expanduser("~/.tarball-installations/zen/icons/updater.png"),
        "/usr/share/icons/hicolor/128x128/apps/zen-browser.png",
        "/usr/share/pixmaps/zen.png",
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return ""


def find_helper_script(script_name):
    """Locate a companion shell script in SCRIPT_DIR, ~/.local/bin, or ~/Scripts."""
    candidates = [
        os.path.join(SCRIPT_DIR, script_name),
        os.path.expanduser(f"~/.local/bin/{script_name}"),
        os.path.expanduser(f"~/Scripts/{script_name}"),
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return os.path.join(SCRIPT_DIR, script_name)


def detect_tarball_install_dir():
    """Fast filesystem-only lookup for an installed portable Zen tarball directory."""
    tarball_candidates = [
        DEFAULT_TARBALL_DIR,
        os.path.expanduser("~/.local/share/zen"),
        os.path.expanduser("~/Applications/zen"),
        os.path.expanduser("~/.local/opt/zen"),
        os.path.expanduser("~/.zen-browser"),
        os.path.expanduser("~/zen"),
    ]
    for cand in tarball_candidates:
        ini_file = os.path.join(cand, "application.ini")
        if os.path.isfile(ini_file):
            return cand, ini_file
    return None, None


def detect_zen_installation(check_flatpak=True):
    """
    Detect how Zen Browser is installed on the system:
      - 'type': 'tarball' | 'flatpak' | 'system' | 'none'
      - 'path': directory or Flatpak app ID
      - 'ini': path to application.ini if applicable
      - 'description': human-readable summary
    """
    tar_dir, tar_ini = detect_tarball_install_dir()
    if tar_dir and tar_ini:
        return {
            "type": "tarball",
            "path": tar_dir,
            "ini": tar_ini,
            "description": f"Portable tarball ({tar_dir})",
        }

    if check_flatpak and shutil.which("flatpak"):
        for flatpak_id in FLATPAK_APP_IDS:
            try:
                res = subprocess.run(
                    ["flatpak", "info", flatpak_id],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if res.returncode == 0:
                    flatpak_ver = "Unknown"
                    for line in res.stdout.splitlines():
                        if line.strip().startswith("Version:"):
                            flatpak_ver = line.split(":", 1)[1].strip()
                            break
                    return {
                        "type": "flatpak",
                        "path": flatpak_id,
                        "ini": "",
                        "flatpak_ver": flatpak_ver,
                        "description": f"Flatpak ({flatpak_id})",
                    }
            except (OSError, subprocess.SubprocessError):
                pass

    system_candidates = [
        "/opt/zen",
        "/usr/lib/zen",
        "/usr/lib64/zen",
        "/usr/local/lib/zen",
    ]
    for cand in system_candidates:
        ini_file = os.path.join(cand, "application.ini")
        if os.path.isfile(ini_file):
            return {
                "type": "system",
                "path": cand,
                "ini": ini_file,
                "description": f"System package ({cand})",
            }

    which_zen = shutil.which("zen") or shutil.which("zen-browser")
    if which_zen:
        try:
            real_bin = os.path.realpath(which_zen)
            bin_dir = os.path.dirname(real_bin)
            ini_file = os.path.join(bin_dir, "application.ini")
            if os.path.isfile(ini_file):
                is_user = bin_dir.startswith(os.path.expanduser("~"))
                return {
                    "type": "tarball" if is_user else "system",
                    "path": bin_dir,
                    "ini": ini_file,
                    "description": f"User binary ({bin_dir})" if is_user else f"System package ({bin_dir})",
                }
        except OSError:
            pass

    return {
        "type": "none",
        "path": "",
        "ini": "",
        "description": "Not installed",
    }


ICON_PATH = find_zen_icon()
UPDATE_SCRIPT = find_helper_script("update_zen.sh")


def get_checkmark_icon_path():
    """Return a path to the checkbox checkmark PNG without polluting ~/.local/bin."""
    repo_icon = os.path.join(SCRIPT_DIR, "assets", "checkmark.png")
    if os.path.isfile(repo_icon):
        return repo_icon
    installed_icon = os.path.expanduser("~/.local/share/icons/zen-updater-checkmark.png")
    if os.path.isfile(installed_icon):
        return installed_icon
    return os.path.join(get_cache_dir(), "zen-updater", "checkmark.png")


def ensure_checkmark_icon():
    """Ensure the checkmark PNG icon exists in a valid readable/writable asset path."""
    target = get_checkmark_icon_path()
    if os.path.isfile(target):
        return target
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        pix = QPixmap(14, 14)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(
            QColor("#ffffff"),
            2.2,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(pen)
        painter.drawLine(2, 7, 5, 11)
        painter.drawLine(5, 11, 12, 3)
        painter.end()
        pix.save(target, "PNG")
    except OSError:
        pass
    return target


def get_checkbox_qss():
    """Return dark-themed QCheckBox stylesheet with custom checkmark graphic."""
    icon_path = ensure_checkmark_icon().replace("\\", "/")
    return f"""
    QCheckBox {{
        color: #e6edf3;
        font-size: 13px;
        spacing: 10px;
        padding: 2px 0px;
    }}
    QCheckBox:disabled {{
        color: #79c0ff;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1.5px solid #6e7681;
        background-color: #21262d;
    }}
    QCheckBox::indicator:hover {{
        border-color: #58a6ff;
        background-color: #30363d;
    }}
    QCheckBox::indicator:checked {{
        background-color: #1f6feb;
        border-color: #388bfd;
        image: url("{icon_path}");
    }}
    QCheckBox::indicator:checked:disabled {{
        background-color: #238636;
        border-color: #2ea043;
        image: url("{icon_path}");
    }}
    """


def dismiss_zen_notification():
    """Dismiss any active Zen update notification via DBus."""
    nid_file = os.path.join(get_cache_dir(), "zen_update_notification_id")
    target_nid = None
    if os.path.isfile(nid_file):
        try:
            with open(nid_file, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val.isdigit():
                    target_nid = int(val)
            os.remove(nid_file)
        except OSError:
            pass

    if not target_nid:
        return

    try:
        import dbus
    except ImportError:
        dbus = None

    if dbus is not None:
        try:
            bus = dbus.SessionBus()
            notify_obj = bus.get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
            notify_iface = dbus.Interface(notify_obj, "org.freedesktop.Notifications")
            notify_iface.CloseNotification(dbus.UInt32(target_nid))
            return
        except dbus.DBusException:
            pass

    qdbus_bin = shutil.which("qdbus")
    if qdbus_bin:
        try:
            subprocess.run(
                [
                    qdbus_bin,
                    "org.freedesktop.Notifications",
                    "/org/freedesktop/Notifications",
                    "CloseNotification",
                    str(target_nid),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            return
        except (OSError, subprocess.SubprocessError):
            pass

    gdbus_bin = shutil.which("gdbus")
    if gdbus_bin:
        try:
            subprocess.run(
                [
                    gdbus_bin,
                    "call",
                    "--session",
                    "--dest",
                    "org.freedesktop.Notifications",
                    "--object-path",
                    "/org/freedesktop/Notifications",
                    "--method",
                    "org.freedesktop.Notifications.CloseNotification",
                    str(target_nid),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def fetch_github_redirect_tag(repo, timeout=8):
    """Resolve the latest release tag via GitHub's HTML redirect (no API rate limit)."""
    url = f"https://github.com/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": f"ZenUpdater/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final_url = resp.geturl()
    if "/releases/tag/" in final_url:
        tag = final_url.rstrip("/").split("/")[-1]
        if tag and tag != "latest":
            return tag, final_url
    return None, ""


class ZenProfileManager:
    """Manages discovering, configuring, and launching Zen Browser profiles."""

    def __init__(self):
        self.config_dir = get_config_dir()
        self.settings_file = os.path.join(self.config_dir, "settings.json")
        self.zen_dir = os.path.expanduser("~/.zen")
        self.ini_path = os.path.join(self.zen_dir, "profiles.ini")
        self.refresh_install_dir()

    def refresh_install_dir(self):
        """Refresh the active Zen portable installation directory."""
        tar_dir, _ = detect_tarball_install_dir()
        if tar_dir and os.path.isdir(tar_dir):
            self.install_dir = tar_dir
        else:
            self.install_dir = DEFAULT_TARBALL_DIR

    def get_profiles(self):
        """Discover Zen profiles across portable, XDG, and Flatpak profile registries."""
        profiles = []
        candidates = [
            os.path.expanduser("~/.config/zen/profiles.ini"),
            os.path.expanduser("~/.zen/profiles.ini"),
        ]
        for flatpak_id in FLATPAK_APP_IDS:
            candidates.append(os.path.expanduser(f"~/.var/app/{flatpak_id}/.zen/profiles.ini"))
            candidates.append(os.path.expanduser(f"~/.var/app/{flatpak_id}/.config/zen/profiles.ini"))

        seen_paths = set()
        desktop_map = self._scan_desktop_files()

        for ini_file in candidates:
            if not os.path.isfile(ini_file):
                continue

            cp = configparser.ConfigParser(interpolation=None)
            try:
                cp.read(ini_file, encoding="utf-8")
            except (OSError, configparser.Error):
                continue

            base_dir = os.path.dirname(ini_file)
            is_flatpak = ".var/app" in ini_file

            # Collect valid Profile sections first to accurately pick Install default
            profile_entries = []
            valid_profile_paths = set()
            for sec in cp.sections():
                if not sec.startswith("Profile"):
                    continue
                name = cp.get(sec, "Name", fallback="").strip()
                path = cp.get(sec, "Path", fallback="").strip()
                is_rel = cp.get(sec, "IsRelative", fallback="1").strip() == "1"
                if not name or not path:
                    continue
                full_profile_path = os.path.normpath(os.path.join(base_dir, path) if is_rel else path)
                if not os.path.isdir(full_profile_path):
                    continue
                valid_profile_paths.add(path)
                profile_entries.append((sec, name, path, full_profile_path))

            # Pick Install* default that actually resolves to an existing profile in this INI
            default_paths = set()
            for sec in cp.sections():
                if sec.startswith("Install") and cp.has_option(sec, "Default"):
                    cand_def = cp.get(sec, "Default").strip()
                    if cand_def in valid_profile_paths and "twilight" not in cand_def.lower():
                        default_paths.add(cand_def)
            if not default_paths:
                for sec in cp.sections():
                    if sec.startswith("Install") and cp.has_option(sec, "Default"):
                        cand_def = cp.get(sec, "Default").strip()
                        if cand_def in valid_profile_paths:
                            default_paths.add(cand_def)
                            break

            for sec, name, path, full_profile_path in profile_entries:
                if full_profile_path in seen_paths:
                    continue
                seen_paths.add(full_profile_path)

                if default_paths:
                    is_def = path in default_paths
                else:
                    is_def = cp.get(sec, "Default", fallback="0").strip() == "1"

                desktop_info = desktop_map.get(name)
                if desktop_info and desktop_info.get("name"):
                    dname = desktop_info["name"]
                    if dname.lower().startswith("zen browser (") and dname.endswith(")"):
                        dname = dname[len("zen browser ("):-1]
                    elif dname.lower().startswith("zen browser"):
                        dname = dname[len("zen browser"):].strip(" -:")
                    display_name = f"{dname} ({name})" if dname and dname.lower() != name.lower() else (dname or name)
                else:
                    display_name = name

                if is_flatpak:
                    display_name = f"{display_name} [Flatpak]"

                if is_def and "default" not in display_name.lower():
                    display_name = f"{display_name} - Default"

                profiles.append({
                    "key": full_profile_path,
                    "name": name,
                    "path": path,
                    "full_path": full_profile_path,
                    "ini_file": ini_file,
                    "is_default": is_def,
                    "display_name": display_name,
                    "desktop_file": desktop_info["file"] if desktop_info else None,
                    "exec_cmd": desktop_info["exec"] if desktop_info else None,
                    "is_flatpak_exec": desktop_info.get("is_flatpak", False) if desktop_info else False,
                })

        profiles.sort(key=lambda p: (not p["is_default"], not bool(p["desktop_file"]), p["display_name"].lower()))
        return profiles

    def _scan_desktop_files(self):
        """Scan desktop entries for Zen profile launchers (-P <profile>)."""
        mapping = {}
        search_dirs = [
            os.path.expanduser("~/.local/share/applications"),
            "/usr/local/share/applications",
            "/usr/share/applications",
        ]
        for sdir in search_dirs:
            if not os.path.isdir(sdir):
                continue
            for fpath in glob.glob(os.path.join(sdir, "*.desktop")):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    if "zen" not in content.lower():
                        continue
                    exec_cmd = None
                    app_name = None
                    in_main_entry = False
                    for raw_line in content.splitlines():
                        line = raw_line.strip()
                        if line.startswith("["):
                            in_main_entry = (line == "[Desktop Entry]")
                            continue
                        if not in_main_entry:
                            continue
                        if line.startswith("Exec=") and not exec_cmd:
                            exec_cmd = line[5:].strip()
                        elif line.startswith("Name=") and not app_name:
                            app_name = line[5:].strip()

                    if not exec_cmd:
                        continue

                    try:
                        tokens = shlex.split(exec_cmd)
                    except ValueError:
                        tokens = exec_cmd.split()

                    pname = None
                    for idx, tok in enumerate(tokens):
                        if tok in ("-P", "--profile-name") and idx + 1 < len(tokens):
                            pname = tokens[idx + 1]
                            break
                        if tok.startswith("-P") and len(tok) > 2:
                            pname = tok[2:]
                            break

                    if pname and pname not in mapping:
                        is_fp = bool(tokens and os.path.basename(tokens[0]) == "flatpak")
                        mapping[pname] = {
                            "file": fpath,
                            "name": app_name or pname,
                            "exec": exec_cmd,
                            "is_flatpak": is_fp,
                        }
                except OSError:
                    pass
        return mapping

    def load_selected_profiles(self, profiles):
        """Load selected profile keys while discarding stale profiles no longer on disk."""
        valid_by_key = {p["key"]: p for p in profiles}
        valid_by_name = {}
        for p in profiles:
            valid_by_name.setdefault(p["name"], []).append(p["key"])

        selected = set()
        if os.path.isfile(self.settings_file):
            settings = load_app_settings()
            raw_items = settings.get("selected_profiles")
            if isinstance(raw_items, list):
                for item in raw_items:
                    if item in valid_by_key:
                        selected.add(item)
                    elif item in valid_by_name:
                        # Backward compatibility for settings.json storing profile names
                        for matched_key in valid_by_name[item]:
                            selected.add(matched_key)
                return selected

        for p in profiles:
            if p["is_default"] or p["desktop_file"]:
                selected.add(p["key"])
        return selected

    def save_selected_profiles(self, selected_set, profiles=None):
        """Save selected profile identifiers, preserving human-readable names when unambiguous."""
        if profiles is None:
            save_app_setting("selected_profiles", sorted(selected_set))
            return

        name_counts = {}
        by_key = {}
        for p in profiles:
            name_counts[p["name"]] = name_counts.get(p["name"], 0) + 1
            by_key[p["key"]] = p

        serialized = []
        for key in sorted(selected_set):
            prof = by_key.get(key)
            if prof and name_counts.get(prof["name"], 0) == 1:
                serialized.append(prof["name"])
            else:
                serialized.append(key)
        save_app_setting("selected_profiles", serialized)

    def sync_profile_binaries(self):
        """Ensure isolated custom profile binaries match the main zen binary hardlink."""
        self.refresh_install_dir()
        zen_bin = os.path.join(self.install_dir, "zen")
        if not os.path.isfile(zen_bin):
            return []

        try:
            zen_stat = os.stat(zen_bin)
        except OSError:
            return []

        target_bins = set()
        # Preserve zen-bin only if already present in install_dir
        if os.path.lexists(os.path.join(self.install_dir, "zen-bin")):
            target_bins.add("zen-bin")

        desktop_dir = os.path.expanduser("~/.local/share/applications")
        norm_install = os.path.normpath(self.install_dir)
        if os.path.isdir(desktop_dir):
            for dfile in glob.glob(os.path.join(desktop_dir, "*.desktop")):
                try:
                    with open(dfile, "r", encoding="utf-8", errors="ignore") as f:
                        for raw_line in f:
                            line = raw_line.strip()
                            if not line.startswith("Exec="):
                                continue
                            cmd_str = line[5:].strip()
                            try:
                                parts = shlex.split(cmd_str)
                            except ValueError:
                                parts = cmd_str.split()
                            if not parts:
                                continue
                            exe_path = os.path.normpath(parts[0])
                            if os.path.dirname(exe_path) == norm_install:
                                tbin = os.path.basename(exe_path)
                                if tbin and tbin != "zen":
                                    target_bins.add(tbin)
                except OSError:
                    pass

        relinked = []
        for tbin in sorted(target_bins):
            tpath = os.path.join(self.install_dir, tbin)
            needs_link = False
            if not os.path.lexists(tpath):
                needs_link = True
            else:
                try:
                    tstat = os.stat(tpath)
                    if tstat.st_ino != zen_stat.st_ino or tstat.st_size != zen_stat.st_size:
                        needs_link = True
                except OSError:
                    needs_link = True

            if needs_link:
                try:
                    if os.path.lexists(tpath):
                        os.unlink(tpath)
                    os.link(zen_bin, tpath)
                    relinked.append(tbin)
                except OSError:
                    try:
                        shutil.copy2(zen_bin, tpath)
                        relinked.append(tbin)
                    except OSError:
                        pass

        self.ensure_update_policy()
        return relinked

    def ensure_update_policy(self):
        """Ensure distribution/policies.json disables internal background updates."""
        dist_dir = os.path.join(self.install_dir, "distribution")
        policy_file = os.path.join(dist_dir, "policies.json")
        try:
            os.makedirs(dist_dir, exist_ok=True)
            if not os.path.isfile(policy_file):
                with open(policy_file, "w", encoding="utf-8") as f:
                    json.dump({"policies": {"DisableAppUpdate": True}}, f, indent=2)
            else:
                with open(policy_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not data.get("policies", {}).get("DisableAppUpdate"):
                    data.setdefault("policies", {})["DisableAppUpdate"] = True
                    with open(policy_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
        except (OSError, json.JSONDecodeError, ValueError):
            pass


class ZenTimerManager:
    """Manages the user-level systemd update checker timer and service."""

    def __init__(self):
        self.systemd_dir = os.path.expanduser("~/.config/systemd/user")
        self.service_path = os.path.join(self.systemd_dir, "zen-update-check.service")
        self.timer_path = os.path.join(self.systemd_dir, "zen-update-check.timer")
        self.has_systemctl = bool(shutil.which("systemctl"))

    def is_available(self):
        return self.has_systemctl

    def get_status(self):
        """Return dict with available, installed, active, enabled, interval, and next_run."""
        res = {
            "available": self.has_systemctl,
            "installed": os.path.isfile(self.timer_path),
            "active": False,
            "enabled": False,
            "interval": DEFAULT_TIMER_INTERVAL,
            "next_run": "Unknown",
        }
        if not self.has_systemctl:
            return res

        if os.path.isfile(self.timer_path):
            try:
                with open(self.timer_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("OnUnitActiveSec="):
                            val = line.strip().split("=", 1)[1].strip()
                            if val:
                                res["interval"] = val
                            break
            except OSError:
                pass

        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", "zen-update-check.timer"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
            res["active"] = (proc.stdout.strip() == "active")
        except (OSError, subprocess.SubprocessError):
            res["active"] = False

        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-enabled", "zen-update-check.timer"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
            res["enabled"] = (proc.stdout.strip() == "enabled")
        except (OSError, subprocess.SubprocessError):
            res["enabled"] = False

        try:
            env = os.environ.copy()
            env["LC_ALL"] = "C"
            proc = subprocess.run(
                ["systemctl", "--user", "list-timers", "zen-update-check.timer", "--no-legend", "--full"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=3,
            )
            out = proc.stdout.strip()
            # Extract strictly the LEFT column between NEXT timestamp and LAST timestamp/n/a
            m = re.match(
                r'^(?:[A-Za-z]{3}\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\S+)\s+(.+?)\s+'
                r'(?:[A-Za-z]{3}\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\S+|n/a|-)\s+',
                out,
            )
            if m:
                left_val = m.group(1).strip()
                if left_val and left_val not in ("n/a", "-"):
                    res["next_run"] = left_val
        except (OSError, subprocess.SubprocessError):
            pass

        return res

    def _resolve_check_script(self):
        return find_helper_script("check_zen_update.sh")

    def ensure_service_file(self):
        """Create or repair the systemd service file if missing or pointing to a nonexistent script."""
        os.makedirs(self.systemd_dir, exist_ok=True)
        check_script = self._resolve_check_script()
        needs_write = not os.path.isfile(self.service_path)
        if not needs_write:
            try:
                with open(self.service_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("ExecStart="):
                            exe_val = line.strip().split("=", 1)[1].strip()
                            expanded = exe_val.replace("%h", os.path.expanduser("~"))
                            if not os.path.isfile(expanded):
                                needs_write = True
                            break
            except OSError:
                needs_write = True

        if needs_write:
            home_dir = os.path.expanduser("~")
            exec_path = check_script.replace(home_dir, "%h", 1) if check_script.startswith(home_dir) else check_script
            content = (
                "[Unit]\n"
                "Description=Check Zen Browser for Updates\n"
                "After=graphical-session.target\n\n"
                "[Service]\n"
                "Type=oneshot\n"
                f"ExecStart={exec_path}\n"
            )
            with open(self.service_path, "w", encoding="utf-8") as f:
                f.write(content)

    def write_timer_file(self, interval=DEFAULT_TIMER_INTERVAL):
        """Write the timer unit file with the chosen interval."""
        os.makedirs(self.systemd_dir, exist_ok=True)
        content = (
            "[Unit]\n"
            f"Description=Check Zen Browser for Updates every {interval}\n\n"
            "[Timer]\n"
            "OnBootSec=5min\n"
            f"OnUnitActiveSec={interval}\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )
        with open(self.timer_path, "w", encoding="utf-8") as f:
            f.write(content)

    def set_timer(self, enabled=True, interval=DEFAULT_TIMER_INTERVAL):
        """Configure and start/stop the systemd user timer."""
        if not self.has_systemctl:
            return False, "systemctl is not available on this system."

        try:
            if enabled:
                self.ensure_service_file()
                self.write_timer_file(interval)
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=5)
                subprocess.run(["systemctl", "--user", "enable", "--now", "zen-update-check.timer"], check=True, timeout=5)
                return True, f"Timer enabled: checking every {interval}."
            subprocess.run(["systemctl", "--user", "disable", "--now", "zen-update-check.timer"], check=True, timeout=5)
            return True, "Timer disabled."
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)


def format_iso_date(iso_str):
    """Format an ISO-8601 timestamp string cleanly for display."""
    if not iso_str:
        return "Unknown"
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        return dt.strftime("%b %d, %Y (%H:%M UTC)")
    except ValueError:
        return iso_str.split("T")[0] if "T" in iso_str else iso_str


def format_build_id(build_id):
    """Format a Mozilla BuildID (YYYYMMDD...) into a readable date."""
    if not build_id or len(build_id) < 8:
        return "Unknown"
    try:
        dt = datetime.strptime(build_id[:8], "%Y%m%d")
        return dt.strftime("%b %d, %Y")
    except ValueError:
        return build_id


class StartupStatusWorker(QThread):
    """Background worker to query systemd timer state without blocking UI startup."""
    finished = pyqtSignal(dict)

    def run(self):
        timer_mgr = ZenTimerManager()
        self.finished.emit(timer_mgr.get_status())


class CheckVersionWorker(QThread):
    """Background worker to detect Zen installation and fetch latest GitHub release info."""
    finished = pyqtSignal(dict)

    def run(self):
        install_info = detect_zen_installation(check_flatpak=True)
        result = {
            "current_version": "Unknown",
            "current_date": "Unknown",
            "latest_version": "Unknown",
            "latest_date": "Unknown",
            "release_url": "",
            "release_notes": "",
            "update_available": False,
            "install_info": install_info,
            "error": None,
        }

        # 1. Read Current Version and BuildID
        build_id = None
        if install_info["type"] == "flatpak":
            result["current_version"] = install_info.get("flatpak_ver", "Flatpak")
        elif install_info["ini"] and os.path.isfile(install_info["ini"]):
            try:
                with open(install_info["ini"], "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Version="):
                            result["current_version"] = line.split("=", 1)[1].strip()
                        elif line.startswith("BuildID="):
                            build_id = line.split("=", 1)[1].strip()
            except OSError as e:
                result["error"] = f"Failed to read application.ini: {e}"

        if build_id:
            result["current_date"] = format_build_id(build_id)

        # 2. Fetch Latest Version (redirect first or API + fallback)
        headers = {"User-Agent": f"Zen-Browser-Updater-GUI/{APP_VERSION}"}
        latest_tag = None
        latest_published_iso = None
        fallback_date_str = None

        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/zen-browser/desktop/releases/latest",
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latest_tag = data.get("tag_name")
                latest_published_iso = data.get("published_at")
                result["release_url"] = data.get("html_url", "")
                result["release_notes"] = (data.get("body") or "").strip()
        except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
            # Fallback 1: rate-limit-free GitHub redirect
            try:
                tag, final_url = fetch_github_redirect_tag("zen-browser/desktop", timeout=10)
                if tag:
                    latest_tag = tag
                    result["release_url"] = final_url
            except (urllib.error.URLError, OSError):
                pass

            # Fallback 2: Mozilla/Zen update.xml
            if not latest_tag:
                try:
                    arch_token = get_update_xml_arch()
                    req_xml = urllib.request.Request(
                        f"https://updates.zen-browser.app/updates/browser/{arch_token}/release/update.xml",
                        headers=headers,
                    )
                    with urllib.request.urlopen(req_xml, timeout=10) as resp_xml:
                        xml_content = resp_xml.read().decode("utf-8", errors="replace")
                        match_ver = re.search(r'displayVersion="([^"]+)"', xml_content)
                        if match_ver:
                            latest_tag = match_ver.group(1)
                        match_bid = re.search(r'buildID="([^"]+)"', xml_content)
                        if match_bid:
                            fallback_date_str = format_build_id(match_bid.group(1))
                except (urllib.error.URLError, OSError) as e_xml:
                    result["error"] = f"Network error: {e_xml}"

        if latest_tag:
            result["latest_version"] = latest_tag
            if not result["release_url"]:
                result["release_url"] = f"https://github.com/zen-browser/desktop/releases/tag/{latest_tag}"
            if latest_published_iso:
                result["latest_date"] = format_iso_date(latest_published_iso)
            elif fallback_date_str:
                result["latest_date"] = fallback_date_str
            else:
                result["latest_date"] = "Unknown"

            if result["current_version"] == latest_tag and result["latest_date"] != "Unknown":
                result["current_date"] = result["latest_date"]
            elif (
                result["current_version"] != "Unknown"
                and result["current_version"] != latest_tag
                and result["current_date"] == "Unknown"
            ):
                try:
                    cur_req = urllib.request.Request(
                        f"https://api.github.com/repos/zen-browser/desktop/releases/tags/{result['current_version']}",
                        headers=headers,
                    )
                    with urllib.request.urlopen(cur_req, timeout=6) as cur_resp:
                        cur_data = json.loads(cur_resp.read().decode("utf-8"))
                        if cur_data.get("published_at"):
                            result["current_date"] = format_iso_date(cur_data.get("published_at"))
                except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
                    pass

            if result["current_version"] != "Unknown":
                result["update_available"] = is_newer_zen_version(latest_tag, result["current_version"])
        else:
            if not result["error"]:
                result["error"] = "Unable to determine latest version."

        self.finished.emit(result)


class CheckAppReleaseWorker(QThread):
    """Background worker to check GitHub Releases for Zen Updater updates."""
    finished = pyqtSignal(dict)

    def run(self):
        result = {
            "has_update": False,
            "latest_version": "Unknown",
            "release_date": "Unknown",
            "release_url": "",
            "tarball_url": "",
            "body": "",
            "error": None,
        }
        url = f"https://api.github.com/repos/{APP_REPO}/releases/latest"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"ZenUpdater/{APP_VERSION}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latest_tag = data.get("tag_name", "").strip()
                result["latest_version"] = latest_tag
                result["release_url"] = data.get("html_url", "")
                result["tarball_url"] = data.get("tarball_url", "")
                result["body"] = data.get("body", "")
                pub_date = data.get("published_at", "")
                result["release_date"] = format_iso_date(pub_date) if pub_date else "Unknown"
                if latest_tag and is_newer_app_version(latest_tag, APP_VERSION):
                    result["has_update"] = True
        except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as e:
            # Fallback to rate-limit-free GitHub redirect
            try:
                tag, final_url = fetch_github_redirect_tag(APP_REPO, timeout=6)
                if tag:
                    result["latest_version"] = tag
                    result["release_url"] = final_url
                    result["has_update"] = is_newer_app_version(tag, APP_VERSION)
                else:
                    result["error"] = f"HTTP {e.code}: {e.reason}" if isinstance(e, urllib.error.HTTPError) else str(e)
            except (urllib.error.URLError, OSError):
                result["error"] = f"HTTP {e.code}: {e.reason}" if isinstance(e, urllib.error.HTTPError) else str(e)

        self.finished.emit(result)


class ApplyAppUpdateWorker(QThread):
    """Background worker to download and apply a Zen Updater self-update."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, target_version):
        super().__init__()
        self.target_version = target_version

    def run(self):
        try:
            self.progress.emit(f"Downloading Zen Updater {self.target_version}...")

            git_dir = os.path.join(SCRIPT_DIR, ".git")
            if os.path.isdir(git_dir):
                self.progress.emit("Updating via git repository...")
                fetch_res = subprocess.run(
                    ["git", "fetch", "--tags", "origin"],
                    cwd=SCRIPT_DIR,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if fetch_res.returncode != 0:
                    raise RuntimeError(f"git fetch failed: {fetch_res.stderr.strip() or fetch_res.stdout.strip()}")

                # Fast-forward main when on main, otherwise verify requested release tag exists
                branch_res = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=SCRIPT_DIR,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                current_branch = branch_res.stdout.strip()
                if current_branch == "main":
                    pull_res = subprocess.run(
                        ["git", "pull", "--ff-only", "origin", "main"],
                        cwd=SCRIPT_DIR,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if pull_res.returncode != 0:
                        chk_res = subprocess.run(
                            ["git", "checkout", self.target_version],
                            cwd=SCRIPT_DIR,
                            check=False,
                            capture_output=True,
                            text=True,
                        )
                        if chk_res.returncode != 0:
                            raise RuntimeError(
                                f"Unable to update git working tree: {pull_res.stderr.strip() or chk_res.stderr.strip()}"
                            )
                else:
                    chk_res = subprocess.run(
                        ["git", "checkout", self.target_version],
                        cwd=SCRIPT_DIR,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if chk_res.returncode != 0:
                        raise RuntimeError(f"git checkout failed: {chk_res.stderr.strip() or chk_res.stdout.strip()}")

                inst_sh = os.path.join(SCRIPT_DIR, "install.sh")
                if os.path.isfile(inst_sh):
                    self.progress.emit("Running installer upgrade...")
                    subprocess.run(["bash", inst_sh, "--upgrade"], cwd=SCRIPT_DIR, check=True)
            else:
                download_url = f"https://github.com/{APP_REPO}/archive/refs/tags/{self.target_version}.tar.gz"
                req = urllib.request.Request(
                    download_url,
                    headers={"User-Agent": f"ZenUpdater/{APP_VERSION}"},
                )
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tar_path = os.path.join(tmp_dir, "release.tar.gz")
                    with urllib.request.urlopen(req, timeout=20) as resp, open(tar_path, "wb") as out_f:
                        shutil.copyfileobj(resp, out_f)

                    self.progress.emit("Extracting release files...")
                    with tarfile.open(tar_path, "r:gz") as tar:
                        tar.extractall(path=tmp_dir, filter="data")

                    extracted_root = None
                    for entry in os.listdir(tmp_dir):
                        full_p = os.path.join(tmp_dir, entry)
                        if os.path.isdir(full_p) and entry.startswith("Zen.updater.gui"):
                            extracted_root = full_p
                            break
                    if not extracted_root:
                        for entry in os.listdir(tmp_dir):
                            full_p = os.path.join(tmp_dir, entry)
                            if os.path.isdir(full_p) and entry != "__pycache__":
                                extracted_root = full_p
                                break

                    if not extracted_root:
                        raise RuntimeError("Could not locate extracted release archive directory.")

                    inst_sh = os.path.join(extracted_root, "install.sh")
                    if os.path.isfile(inst_sh):
                        self.progress.emit("Running installer upgrade...")
                        subprocess.run(["bash", inst_sh, "--upgrade"], cwd=extracted_root, check=True)
                    else:
                        bin_dir = os.path.expanduser("~/.local/bin")
                        os.makedirs(bin_dir, exist_ok=True)
                        for fname in ["zen_updater_gui.py", "update_zen.sh", "check_zen_update.sh", "zen_backup.tarignore"]:
                            src = os.path.join(extracted_root, fname)
                            if os.path.isfile(src):
                                dst = os.path.join(bin_dir, fname)
                                shutil.copy2(src, dst)
                                os.chmod(dst, 0o755)

            target_py = os.path.expanduser("~/.local/bin/zen_updater_gui.py")
            if os.path.isfile(target_py):
                comp_res = subprocess.run(
                    [sys.executable, "-m", "py_compile", target_py],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if comp_res.returncode != 0:
                    raise RuntimeError(f"Syntax validation failed: {comp_res.stderr}")

            self.finished.emit(True, f"Successfully updated Zen Updater to {self.target_version}!")
        except (OSError, subprocess.SubprocessError, urllib.error.URLError, tarfile.TarError, RuntimeError) as e:
            self.finished.emit(False, str(e))


class ZenUpdaterWindow(QMainWindow):
    """Main Qt6 window for Zen Browser Updater."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Zen Browser Updater {APP_VERSION}")
        self.setMinimumSize(540, 560)
        self.resize(560, 710)

        if ICON_PATH and os.path.isfile(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        else:
            theme_icon = QIcon.fromTheme("zen-browser")
            if not theme_icon.isNull():
                self.setWindowIcon(theme_icon)

        self.profile_mgr = ZenProfileManager()
        self.profiles = self.profile_mgr.get_profiles()
        self.selected_profiles = self.profile_mgr.load_selected_profiles(self.profiles)
        self.profile_mgr.sync_profile_binaries()

        self.timer_mgr = ZenTimerManager()
        self.timer_status = {
            "available": self.timer_mgr.is_available(),
            "installed": os.path.isfile(self.timer_mgr.timer_path),
            "active": False,
            "enabled": False,
            "interval": DEFAULT_TIMER_INTERVAL,
            "next_run": "Checking...",
        }

        self.install_info = {"type": "none", "path": "", "ini": "", "description": "Detecting..."}
        self.zen_update_info = {}
        self.check_worker = None
        self.startup_timer_worker = None
        self.test_notify_process = None
        self.process = None
        self.active_process_mode = "update"
        self.update_available = False
        self._banner_actionable = False
        self._progress_in_extraction = False

        self.app_check_worker = None
        self.app_apply_worker = None
        self.app_update_info = {}

        dismiss_zen_notification()
        self.setup_ui()

        QTimer.singleShot(80, self.start_startup_timer_query)
        QTimer.singleShot(150, self.start_check)
        if self.load_auto_check_app_setting():
            QTimer.singleShot(800, lambda: self.start_app_update_check(silent=True))

    def setup_ui(self):
        """Construct all window layouts, cards, expandable panels, and logs."""
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                border-radius: 4px;
                margin: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #30363d;
                border-radius: 4px;
                min-height: 25px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #58a6ff;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        central = QWidget()
        central.setObjectName("centralContainer")
        central.setStyleSheet("QWidget#centralContainer { background: transparent; }")
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(10)

        # 1. Header
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        icon_label = QLabel()
        pix = None
        if ICON_PATH and os.path.isfile(ICON_PATH):
            pix = QPixmap(ICON_PATH)
        else:
            theme_icon = QIcon.fromTheme("zen-browser")
            if not theme_icon.isNull():
                pix = theme_icon.pixmap(46, 46)
        if pix and not pix.isNull():
            icon_label.setPixmap(
                pix.scaled(46, 46, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        header_layout.addWidget(icon_label)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.setAlignment(Qt.AlignmentFlag.AlignBottom)

        title_label = QLabel("Zen Browser Updater")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)

        ver_label = QLabel(APP_VERSION)
        ver_label.setStyleSheet("color: #8b949e; font-size: 11px; padding-bottom: 2px;")

        title_row.addWidget(title_label)
        title_row.addWidget(ver_label)
        title_row.addStretch()
        title_vbox.addLayout(title_row)

        subtitle_label = QLabel("Official Release & Update Manager")
        subtitle_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        title_vbox.addWidget(subtitle_label)
        header_layout.addLayout(title_vbox)
        header_layout.addStretch()

        self.badge_app_update = QPushButton("Update Available")
        self.badge_app_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.badge_app_update.setToolTip("A new release of Zen Updater is available. Click to view.")
        self.badge_app_update.setStyleSheet("""
            QPushButton {
                background-color: rgba(46, 160, 67, 0.15);
                color: #a6f3a6;
                border: 1px solid #2ea043;
                border-radius: 10px;
                font-size: 10px;
                font-weight: bold;
                padding: 3px 10px;
            }
            QPushButton:hover {
                background-color: #2ea043;
                color: #ffffff;
                border-color: #3fb950;
            }
        """)
        self.badge_app_update.setVisible(False)
        self.badge_app_update.clicked.connect(self.on_app_update_badge_clicked)
        header_layout.addWidget(self.badge_app_update, alignment=Qt.AlignmentFlag.AlignVCenter)
        main_layout.addLayout(header_layout)

        # 2. Version Information Card
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 8px;
            }
        """)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(16)

        left_box = QVBoxLayout()
        left_box.setSpacing(2)
        lbl_cur_title = QLabel("INSTALLED VERSION")
        lbl_cur_title.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; border: none; background: transparent;")
        self.lbl_cur_ver = QLabel("Detecting...")
        self.lbl_cur_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff; border: none; background: transparent;")
        self.lbl_cur_date = QLabel("Detecting...")
        self.lbl_cur_date.setStyleSheet("color: #8b949e; font-size: 11px; border: none; background: transparent;")
        left_box.addWidget(lbl_cur_title)
        left_box.addWidget(self.lbl_cur_ver)
        left_box.addWidget(self.lbl_cur_date)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet("border: none; border-left: 1px solid #30363d;")

        right_box = QVBoxLayout()
        right_box.setSpacing(2)
        lbl_lat_title = QLabel("LATEST AVAILABLE")
        lbl_lat_title.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; border: none; background: transparent;")

        lat_ver_row = QHBoxLayout()
        lat_ver_row.setSpacing(6)
        self.lbl_lat_ver = QLabel("Checking online...")
        self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #58a6ff; border: none; background: transparent;")
        lat_ver_row.addWidget(self.lbl_lat_ver)

        self.btn_zen_notes = QPushButton("Notes")
        self.btn_zen_notes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_zen_notes.setToolTip("Show Zen Browser release notes")
        self.btn_zen_notes.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 4px;
                color: #8b949e;
                font-size: 10px;
                font-weight: bold;
                padding: 2px 6px;
            }
            QPushButton:hover {
                background-color: #30363d;
                color: #ffffff;
                border-color: #58a6ff;
            }
        """)
        self.btn_zen_notes.setVisible(False)
        self.btn_zen_notes.clicked.connect(self.toggle_zen_notes)
        lat_ver_row.addWidget(self.btn_zen_notes)

        self.btn_zen_github = QPushButton()
        self.btn_zen_github.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_zen_github.setToolTip("Open Zen Browser release on GitHub")
        self.btn_zen_github.setIcon(get_github_icon())
        self.btn_zen_github.setIconSize(QSize(14, 14))
        self.btn_zen_github.setFixedSize(22, 22)
        self.btn_zen_github.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 2px;
            }
            QPushButton:hover {
                background-color: #30363d;
                border-color: #58a6ff;
            }
        """)
        self.btn_zen_github.setVisible(False)
        self.btn_zen_github.clicked.connect(self.open_zen_github_release)
        lat_ver_row.addWidget(self.btn_zen_github)
        lat_ver_row.addStretch()

        self.lbl_lat_date = QLabel("Checking online...")
        self.lbl_lat_date.setStyleSheet("color: #8b949e; font-size: 11px; border: none; background: transparent;")
        right_box.addWidget(lbl_lat_title)
        right_box.addLayout(lat_ver_row)
        right_box.addWidget(self.lbl_lat_date)

        card_layout.addLayout(left_box, 1)
        card_layout.addWidget(div)
        card_layout.addLayout(right_box, 1)
        main_layout.addWidget(card)

        # Collapsible Zen Browser Release Notes Card
        self.zen_notes_frame = QFrame()
        self.zen_notes_frame.setStyleSheet("""
            QFrame {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
        """)
        zen_notes_vbox = QVBoxLayout(self.zen_notes_frame)
        zen_notes_vbox.setContentsMargins(10, 8, 10, 8)
        zen_notes_vbox.setSpacing(4)
        lbl_zen_notes_hdr = QLabel("ZEN BROWSER RELEASE NOTES")
        lbl_zen_notes_hdr.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; border: none; background: transparent;")
        zen_notes_vbox.addWidget(lbl_zen_notes_hdr)

        self.txt_zen_notes = QTextEdit()
        self.txt_zen_notes.setReadOnly(True)
        self.txt_zen_notes.setMaximumHeight(130)
        self.txt_zen_notes.setStyleSheet("""
            QTextEdit {
                background: transparent;
                color: #c9d1d9;
                font-size: 11px;
                border: none;
            }
        """)
        zen_notes_vbox.addWidget(self.txt_zen_notes)
        self.zen_notes_frame.setVisible(False)
        main_layout.addWidget(self.zen_notes_frame)

        # 3. Status Banner
        self.status_banner = QLabel("Checking for updates...")
        self.status_banner.setWordWrap(True)
        self.status_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_banner.setMinimumHeight(42)
        self._set_banner_state("Checking for updates...", "checking")
        self.status_banner.mousePressEvent = self.on_banner_clicked
        main_layout.addWidget(self.status_banner)

        # 4. Backup Option Row
        backup_layout = QHBoxLayout()
        backup_layout.setSpacing(8)

        self.chk_backup = QCheckBox("Backup all profiles before updating or reinstalling")
        self.chk_backup.setChecked(True)
        self.chk_backup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_backup.setStyleSheet(get_checkbox_qss())

        self.btn_backup_help = QPushButton("?")
        self.btn_backup_help.setFixedSize(17, 17)
        self.btn_backup_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_backup_help.setStyleSheet(SMALL_HELP_BTN_QSS)
        self.btn_backup_help.clicked.connect(self.show_backup_info)

        self.btn_backup_now = QPushButton("Backup Now")
        self.btn_backup_now.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_backup_now.setToolTip("Create a profile snapshot in ~/.zen-backups without reinstalling")
        self.btn_backup_now.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 5px;
                color: #c9d1d9;
                font-size: 11px;
                padding: 3px 9px;
            }
            QPushButton:hover {
                background-color: #30363d;
                color: #ffffff;
                border-color: #58a6ff;
            }
            QPushButton:disabled {
                background-color: #161b22;
                color: #484f58;
                border-color: #21262d;
            }
        """)
        self.btn_backup_now.clicked.connect(self.run_backup_only)

        self.btn_open_backups = QPushButton("Backups")
        self.btn_open_backups.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_backups.setToolTip("Open ~/.zen-backups folder")
        self.btn_open_backups.setStyleSheet(self.btn_backup_now.styleSheet())
        self.btn_open_backups.clicked.connect(self.open_backups_folder)

        backup_layout.addWidget(self.chk_backup)
        backup_layout.addWidget(self.btn_backup_help)
        backup_layout.addStretch()
        backup_layout.addWidget(self.btn_backup_now)
        backup_layout.addWidget(self.btn_open_backups)
        main_layout.addLayout(backup_layout)

        # 5. Action Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.btn_run = QPushButton("Run Update")
        self.btn_run.setMinimumHeight(36)
        self.btn_run.setEnabled(False)
        self.btn_run.setStyleSheet(GREEN_BTN_QSS)
        self.btn_run.clicked.connect(self.run_update)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMinimumHeight(36)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet(RED_OUTLINE_BTN_QSS)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.cancel_active_process)

        self.btn_launch = QPushButton("Launch Zen")
        self.btn_launch.setMinimumHeight(36)
        self.btn_launch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_launch.clicked.connect(self.launch_zen)
        self.set_launch_button_highlighted(False)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setMinimumHeight(36)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setStyleSheet(SECONDARY_BTN_QSS)
        self.btn_refresh.clicked.connect(self.start_check)

        button_layout.addWidget(self.btn_run)
        button_layout.addWidget(self.btn_cancel)
        button_layout.addWidget(self.btn_launch)
        button_layout.addStretch()
        button_layout.addWidget(self.btn_refresh)
        main_layout.addLayout(button_layout)

        # 6. Expandable Launch Profiles Section
        self.btn_toggle_profiles = QPushButton()
        self.btn_toggle_profiles.setObjectName("profileToggleBtn")
        self.btn_toggle_profiles.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_profiles.setStyleSheet(ACCORDION_TOGGLE_QSS)
        self.btn_toggle_profiles.clicked.connect(self.toggle_profiles_expanded)

        self.profile_frame = QFrame()
        self.profile_frame.setObjectName("profileCard")
        self.profile_frame.setStyleSheet("""
            QFrame#profileCard {
                background-color: #151a22;
                border: 1px solid #30363d;
                border-radius: 8px;
            }
        """ + get_checkbox_qss())
        profile_layout = QVBoxLayout(self.profile_frame)
        profile_layout.setContentsMargins(16, 12, 16, 12)
        profile_layout.setSpacing(8)

        profile_header_layout = QHBoxLayout()
        profile_header_layout.setSpacing(8)
        profile_header_layout.setContentsMargins(0, 0, 0, 0)

        lbl_desc = QLabel("PROFILES TO OPEN WHEN CLICKING 'LAUNCH ZEN':")
        lbl_desc.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; letter-spacing: 0.6px; border: none; background: transparent;")
        profile_header_layout.addWidget(lbl_desc)

        self.btn_profile_help = QPushButton("?")
        self.btn_profile_help.setFixedSize(17, 17)
        self.btn_profile_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_profile_help.setToolTip("Click for Profile Migration & Default Setup guide")
        self.btn_profile_help.setStyleSheet(SMALL_HELP_BTN_QSS)
        self.btn_profile_help.clicked.connect(self.show_profile_help)
        profile_header_layout.addWidget(self.btn_profile_help)

        self.btn_migration_badge = QPushButton("Migration Guide")
        self.btn_migration_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_migration_badge.setToolTip("Click to view instructions on migrating existing profiles to this installation")
        self.btn_migration_badge.setStyleSheet("""
            QPushButton {
                background-color: rgba(248, 81, 73, 0.15);
                color: #ff9b9b;
                border: 1px solid #f85149;
                border-radius: 11px;
                font-size: 10px;
                font-weight: bold;
                padding: 2px 9px;
            }
            QPushButton:hover {
                background-color: #d73a49;
                color: #ffffff;
                border-color: #ff7b72;
            }
        """)
        self.btn_migration_badge.clicked.connect(self.show_migration_dialog)
        self.btn_migration_badge.setVisible(False)
        profile_header_layout.addWidget(self.btn_migration_badge)
        profile_header_layout.addStretch()
        profile_layout.addLayout(profile_header_layout)

        self.profile_checkboxes = {}
        self.profile_grid_layout = QGridLayout()
        self.profile_grid_layout.setHorizontalSpacing(14)
        self.profile_grid_layout.setVerticalSpacing(6)
        self.profile_grid_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.addLayout(self.profile_grid_layout)
        self._rebuild_profile_grid()

        self.profiles_expanded = False
        self.profile_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.profile_frame.setVisible(False)
        self.update_profiles_toggle_text()

        main_layout.addWidget(self.btn_toggle_profiles)
        main_layout.addWidget(self.profile_frame)

        # 7. Expandable Background Update Check Timer Section
        self.btn_toggle_timer = QPushButton()
        self.btn_toggle_timer.setObjectName("timerToggleBtn")
        self.btn_toggle_timer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_timer.setStyleSheet(ACCORDION_TOGGLE_QSS)
        self.btn_toggle_timer.clicked.connect(self.toggle_timer_expanded)

        self.timer_frame = QFrame()
        self.timer_frame.setObjectName("timerCard")
        self.timer_frame.setStyleSheet("""
            QFrame#timerCard {
                background-color: #151a22;
                border: 1px solid #30363d;
                border-radius: 8px;
            }
        """ + get_checkbox_qss() + """
            QComboBox {
                background-color: #0d1117;
                color: #e6edf3;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #161b22;
                color: #e6edf3;
                selection-background-color: #1f6feb;
                selection-color: #ffffff;
                border: 1px solid #30363d;
            }
        """)
        timer_layout = QVBoxLayout(self.timer_frame)
        timer_layout.setContentsMargins(16, 12, 16, 12)
        timer_layout.setSpacing(10)

        lbl_timer_desc = QLabel("BACKGROUND SYSTEMD NOTIFICATION SERVICE:")
        lbl_timer_desc.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; letter-spacing: 0.6px; border: none; background: transparent;")
        timer_layout.addWidget(lbl_timer_desc)

        self.chk_timer_enable = QCheckBox("Enable periodic background update checks")
        self.chk_timer_enable.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_timer_enable.toggled.connect(self.on_timer_enable_toggled)
        timer_layout.addWidget(self.chk_timer_enable)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)

        lbl_interval = QLabel("Check Interval:")
        lbl_interval.setStyleSheet("color: #c9d1d9; font-size: 12px; font-weight: bold;")
        controls_layout.addWidget(lbl_interval)

        self.combo_timer_interval = QComboBox()
        self.combo_timer_interval.addItem("Every 4 hours", "4h")
        self.combo_timer_interval.addItem("Every 12 hours", "12h")
        self.combo_timer_interval.addItem("Daily (Every 24 hours)", "24h")
        self.combo_timer_interval.addItem("Weekly (Every 7 days)", "7d")
        self.combo_timer_interval.currentIndexChanged.connect(self.on_timer_interval_changed)
        controls_layout.addWidget(self.combo_timer_interval)

        self.btn_test_notification = QPushButton("Test Check Now")
        self.btn_test_notification.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_notification.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                color: #c9d1d9;
                font-size: 11px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #30363d;
                color: #ffffff;
            }
            QPushButton:disabled {
                background-color: #161b22;
                color: #484f58;
                border-color: #21262d;
            }
        """)
        self.btn_test_notification.clicked.connect(self.test_notification_now)
        controls_layout.addWidget(self.btn_test_notification)
        controls_layout.addStretch()
        timer_layout.addLayout(controls_layout)

        self.lbl_timer_status = QLabel("Status: Checking timer...")
        self.lbl_timer_status.setStyleSheet("font-size: 11px; color: #8b949e;")
        timer_layout.addWidget(self.lbl_timer_status)

        self.timer_expanded = False
        self.timer_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.timer_frame.setVisible(False)

        main_layout.addWidget(self.btn_toggle_timer)
        main_layout.addWidget(self.timer_frame)
        self.apply_timer_status_to_ui(self.timer_status)

        # 8. Expandable Zen Updater Updates Section
        self.btn_toggle_app_update = QPushButton()
        self.btn_toggle_app_update.setObjectName("appUpdateToggleBtn")
        self.btn_toggle_app_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_app_update.setStyleSheet(ACCORDION_TOGGLE_QSS)
        self.btn_toggle_app_update.clicked.connect(self.toggle_app_update_expanded)

        self.app_update_frame = QFrame()
        self.app_update_frame.setObjectName("appUpdateCard")
        self.app_update_frame.setStyleSheet("""
            QFrame#appUpdateCard {
                background-color: #151a22;
                border: 1px solid #30363d;
                border-radius: 8px;
            }
        """ + get_checkbox_qss())
        app_update_layout = QVBoxLayout(self.app_update_frame)
        app_update_layout.setContentsMargins(16, 12, 16, 12)
        app_update_layout.setSpacing(10)

        lbl_app_desc = QLabel("ZEN UPDATER APPLICATION UPDATES:")
        lbl_app_desc.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; letter-spacing: 0.6px; border: none; background: transparent;")
        app_update_layout.addWidget(lbl_app_desc)

        self.chk_auto_check_app = QCheckBox("Check for updater updates automatically on startup")
        self.chk_auto_check_app.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_auto_check_app.setChecked(self.load_auto_check_app_setting())
        self.chk_auto_check_app.toggled.connect(self.on_auto_check_app_toggled)
        app_update_layout.addWidget(self.chk_auto_check_app)

        ver_info_layout = QHBoxLayout()
        ver_info_layout.setSpacing(16)

        v_cur_box = QVBoxLayout()
        v_cur_box.setSpacing(2)
        lbl_c_title = QLabel("CURRENT APP VERSION")
        lbl_c_title.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; border: none; background: transparent;")
        self.lbl_app_cur_ver = QLabel(APP_VERSION)
        self.lbl_app_cur_ver.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff; border: none; background: transparent;")
        v_cur_box.addWidget(lbl_c_title)
        v_cur_box.addWidget(self.lbl_app_cur_ver)

        v_lat_box = QVBoxLayout()
        v_lat_box.setSpacing(2)
        lbl_l_title = QLabel("LATEST RELEASE")
        lbl_l_title.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; border: none; background: transparent;")

        lat_row = QHBoxLayout()
        lat_row.setSpacing(8)
        self.lbl_app_lat_ver = QLabel("Not checked yet")
        self.lbl_app_lat_ver.setStyleSheet("font-size: 14px; font-weight: bold; color: #58a6ff; border: none; background: transparent;")
        lat_row.addWidget(self.lbl_app_lat_ver)

        self.btn_app_github = QPushButton()
        self.btn_app_github.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_app_github.setToolTip("Open release on GitHub")
        self.btn_app_github.setIcon(get_github_icon())
        self.btn_app_github.setIconSize(QSize(16, 16))
        self.btn_app_github.setFixedSize(26, 26)
        self.btn_app_github.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 2px;
            }
            QPushButton:hover {
                background-color: #30363d;
                border-color: #58a6ff;
            }
        """)
        self.btn_app_github.clicked.connect(self.open_app_github_release)
        self.btn_app_github.setVisible(False)
        lat_row.addWidget(self.btn_app_github)
        lat_row.addStretch()

        v_lat_box.addWidget(lbl_l_title)
        v_lat_box.addLayout(lat_row)

        ver_info_layout.addLayout(v_cur_box, 1)
        ver_info_layout.addLayout(v_lat_box, 1)
        app_update_layout.addLayout(ver_info_layout)

        app_btn_layout = QHBoxLayout()
        app_btn_layout.setSpacing(10)

        self.btn_check_app_update = QPushButton("Check for Updates")
        self.btn_check_app_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check_app_update.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                color: #c9d1d9;
                font-size: 11px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #30363d;
                color: #ffffff;
            }
        """)
        self.btn_check_app_update.clicked.connect(lambda: self.start_app_update_check(silent=False))
        app_btn_layout.addWidget(self.btn_check_app_update)

        self.btn_apply_app_update = QPushButton("Update Zen Updater")
        self.btn_apply_app_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_app_update.setEnabled(False)
        self.btn_apply_app_update.setStyleSheet("""
            QPushButton {
                background-color: rgba(46, 160, 67, 0.15);
                color: #a6f3a6;
                font-weight: bold;
                font-size: 11px;
                border: 1px solid #2ea043;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #2ea043;
                color: #ffffff;
            }
            QPushButton:disabled {
                background-color: #21262d;
                color: #6e7681;
                border-color: #30363d;
            }
        """)
        self.btn_apply_app_update.clicked.connect(self.run_apply_app_update)
        app_btn_layout.addWidget(self.btn_apply_app_update)
        app_btn_layout.addStretch()
        app_update_layout.addLayout(app_btn_layout)

        self.app_notes_frame = QFrame()
        self.app_notes_frame.setStyleSheet("""
            QFrame {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
        """)
        notes_vbox = QVBoxLayout(self.app_notes_frame)
        notes_vbox.setContentsMargins(10, 8, 10, 8)
        notes_vbox.setSpacing(4)

        lbl_notes_hdr = QLabel("RELEASE NOTES")
        lbl_notes_hdr.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; border: none; background: transparent;")
        notes_vbox.addWidget(lbl_notes_hdr)

        self.txt_app_notes = QTextEdit()
        self.txt_app_notes.setReadOnly(True)
        self.txt_app_notes.setStyleSheet("""
            QTextEdit {
                background: transparent;
                color: #c9d1d9;
                font-size: 11px;
                border: none;
            }
        """)
        self.txt_app_notes.setMaximumHeight(130)
        notes_vbox.addWidget(self.txt_app_notes)

        self.app_notes_frame.setVisible(False)
        app_update_layout.addWidget(self.app_notes_frame)

        self.lbl_app_update_status = QLabel("")
        self.lbl_app_update_status.setStyleSheet("font-size: 11px; color: #8b949e;")
        self.lbl_app_update_status.setWordWrap(True)
        app_update_layout.addWidget(self.lbl_app_update_status)

        self.app_update_expanded = False
        self.app_update_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.app_update_frame.setVisible(False)

        main_layout.addWidget(self.btn_toggle_app_update)
        main_layout.addWidget(self.app_update_frame)
        self.update_app_update_toggle_text()

        # 9. Real-Time Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid palette(mid);
                border-radius: 5px;
                text-align: center;
                height: 22px;
                font-size: 11px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #1e70bf;
                border-radius: 4px;
            }
        """)
        main_layout.addWidget(self.progress_bar)

        # 10. Console Output
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(85)
        self.log_view.setStyleSheet("""
            QTextEdit {
                background-color: #15181c;
                color: #d1d5db;
                font-family: monospace;
                font-size: 11px;
                border: 1px solid palette(mid);
                border-radius: 6px;
            }
        """)
        self.log_view.setPlaceholderText("Update details and progress will appear here...")
        main_layout.addWidget(self.log_view)

        scroll.setWidget(central)
        self.setCentralWidget(scroll)

    def _set_banner_state(self, text, style_key, clickable=False, tooltip=""):
        """Apply uniform dimensions, colors, and clickability to the status banner."""
        bg, fg, border, hover_bg, hover_border = BANNER_STYLES[style_key]
        self._banner_actionable = clickable
        self.status_banner.setText(text)
        self.status_banner.setToolTip(tooltip)
        self.status_banner.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)

        hover_css = ""
        if clickable and hover_bg and hover_border:
            hover_css = f"""
            QLabel:hover {{
                background-color: {hover_bg};
                border-color: {hover_border};
                color: #ffffff;
            }}
            """

        self.status_banner.setStyleSheet(f"""
            QLabel {{
                padding: 10px 12px;
                border-radius: 6px;
                background-color: {bg};
                color: {fg};
                font-weight: bold;
                font-size: 13px;
                border: 1px solid {border};
            }}
            {hover_css}
        """)

    def _rebuild_profile_grid(self):
        """Populate or refresh the profile selection grid from discovered profiles."""
        while self.profile_grid_layout.count():
            item = self.profile_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.profile_checkboxes.clear()

        if not self.profiles:
            lbl_empty = QLabel("No Zen profiles found yet. Launch Zen Browser once to initialize your default profile.")
            lbl_empty.setWordWrap(True)
            lbl_empty.setStyleSheet("color: #8b949e; font-size: 12px; border: none; background: transparent;")
            self.profile_grid_layout.addWidget(lbl_empty, 0, 0, 1, 2)
            return

        grid_row = 0
        grid_col = 0
        for prof in self.profiles:
            pkey = prof["key"]
            chk = QCheckBox(prof["display_name"])
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            chk.setChecked(pkey in self.selected_profiles)
            chk.toggled.connect(lambda checked, key=pkey: self.on_profile_toggled(key, checked))
            self.profile_checkboxes[pkey] = chk
            self.profile_grid_layout.addWidget(chk, grid_row, grid_col)
            grid_col += 1
            if grid_col >= 2:
                grid_col = 0
                grid_row += 1

    def refresh_profiles(self):
        """Re-scan Zen profile registries and update checkboxes and migration badge."""
        self.profiles = self.profile_mgr.get_profiles()
        self.selected_profiles = self.profile_mgr.load_selected_profiles(self.profiles)
        self._rebuild_profile_grid()
        self.update_profiles_toggle_text()

    def set_launch_button_highlighted(self, highlighted):
        """Set normal or accented glowing Zen-blue style on the Launch Zen button."""
        if highlighted:
            self.btn_launch.setStyleSheet("""
                QPushButton {
                    background-color: rgba(56, 139, 253, 0.22);
                    color: #79c0ff;
                    font-weight: bold;
                    font-size: 12px;
                    border: 1.5px solid #388bfd;
                    border-radius: 5px;
                    padding: 6px 18px;
                }
                QPushButton:hover {
                    background-color: #1f6feb;
                    color: #ffffff;
                    border-color: #58a6ff;
                }
                QPushButton:disabled {
                    background-color: #161b22;
                    color: #484f58;
                    border-color: #21262d;
                }
            """)
            glow = QGraphicsDropShadowEffect(self)
            glow.setBlurRadius(16)
            glow.setColor(QColor(56, 139, 253, 200))
            glow.setOffset(0, 0)
            self.btn_launch.setGraphicsEffect(glow)
        else:
            self.btn_launch.setStyleSheet("""
                QPushButton {
                    background-color: #21262d;
                    color: #c9d1d9;
                    font-size: 12px;
                    font-weight: 500;
                    border: 1px solid #30363d;
                    border-radius: 5px;
                    padding: 6px 18px;
                }
                QPushButton:hover {
                    background-color: #30363d;
                    color: #ffffff;
                    border-color: #58a6ff;
                }
                QPushButton:disabled {
                    background-color: #161b22;
                    color: #484f58;
                    border-color: #21262d;
                }
            """)
            self.btn_launch.setGraphicsEffect(None)

    def _collapse_other_sections(self, active_section):
        if active_section != "profiles" and self.profiles_expanded:
            self.profiles_expanded = False
            self.profile_frame.setVisible(False)
            self.update_profiles_toggle_text()
        if active_section != "timer" and self.timer_expanded:
            self.timer_expanded = False
            self.timer_frame.setVisible(False)
            self.update_timer_toggle_text()
        if active_section != "app" and getattr(self, "app_update_expanded", False):
            self.app_update_expanded = False
            self.app_update_frame.setVisible(False)
            self.update_app_update_toggle_text()

    def toggle_profiles_expanded(self):
        self.profiles_expanded = not self.profiles_expanded
        self.profile_frame.setVisible(self.profiles_expanded)
        if self.profiles_expanded:
            self._collapse_other_sections("profiles")
        self.update_profiles_toggle_text()

    def update_profiles_toggle_text(self):
        count = len(self.selected_profiles)
        arrow = "▼" if self.profiles_expanded else "▶"
        self.btn_toggle_profiles.setText(f"{arrow} Launch Profiles ({count} selected)")

    def on_profile_toggled(self, key, checked):
        if checked:
            self.selected_profiles.add(key)
        else:
            self.selected_profiles.discard(key)
        self.profile_mgr.save_selected_profiles(self.selected_profiles, self.profiles)
        self.update_profiles_toggle_text()

    def toggle_timer_expanded(self):
        self.timer_expanded = not self.timer_expanded
        self.timer_frame.setVisible(self.timer_expanded)
        if self.timer_expanded:
            self._collapse_other_sections("timer")
        self.update_timer_toggle_text()

    def update_timer_toggle_text(self):
        arrow = "▼" if self.timer_expanded else "▶"
        status_text = "Active" if self.timer_status.get("active") else "Disabled"
        interval_text = self.timer_status.get("interval", DEFAULT_TIMER_INTERVAL)
        self.btn_toggle_timer.setText(f"{arrow} Background Auto-Check ({status_text} — Every {interval_text})")

    def start_startup_timer_query(self):
        if self.startup_timer_worker and self.startup_timer_worker.isRunning():
            return
        self.startup_timer_worker = StartupStatusWorker()
        self.startup_timer_worker.finished.connect(self.apply_timer_status_to_ui)
        self.startup_timer_worker.start()

    def apply_timer_status_to_ui(self, status):
        self.timer_status = status
        if not self.timer_status.get("available", False):
            self.lbl_timer_status.setText("Systemd user services are not available on this system.")
            self.chk_timer_enable.setEnabled(False)
            self.combo_timer_interval.setEnabled(False)
            self.btn_test_notification.setEnabled(False)
            self.update_timer_toggle_text()
            return

        is_enabled = bool(self.timer_status.get("active") or self.timer_status.get("enabled"))
        self.chk_timer_enable.blockSignals(True)
        self.chk_timer_enable.setChecked(is_enabled)
        self.chk_timer_enable.blockSignals(False)

        cur_int = self.timer_status.get("interval", DEFAULT_TIMER_INTERVAL)
        self.combo_timer_interval.blockSignals(True)
        idx = self.combo_timer_interval.findData(cur_int)
        if idx < 0 and cur_int:
            self.combo_timer_interval.addItem(f"Custom ({cur_int})", cur_int)
            idx = self.combo_timer_interval.findData(cur_int)
        if idx >= 0:
            self.combo_timer_interval.setCurrentIndex(idx)
        self.combo_timer_interval.blockSignals(False)

        if self.timer_status.get("active"):
            next_run = self.timer_status.get("next_run", "Unknown")
            next_txt = f" (Next check: in {next_run})" if next_run not in ("Unknown", "Checking...") else ""
            self.lbl_timer_status.setText(f"Status: Active and running{next_txt}")
            self.lbl_timer_status.setStyleSheet("font-size: 11px; color: #7ee787; font-weight: bold;")
            self.combo_timer_interval.setEnabled(True)
        else:
            self.lbl_timer_status.setText("Status: Inactive (Periodic background checks disabled)")
            self.lbl_timer_status.setStyleSheet("font-size: 11px; color: #8b949e;")
            self.combo_timer_interval.setEnabled(False)

        self.update_timer_toggle_text()

    def refresh_timer_status_label(self):
        self.apply_timer_status_to_ui(self.timer_mgr.get_status())

    def on_timer_enable_toggled(self, checked):
        cur_int = self.combo_timer_interval.currentData() or DEFAULT_TIMER_INTERVAL
        success, msg = self.timer_mgr.set_timer(enabled=checked, interval=cur_int)
        self.append_log(f"\n[Background Timer] {msg}\n")
        if not success:
            self.chk_timer_enable.blockSignals(True)
            self.chk_timer_enable.setChecked(not checked)
            self.chk_timer_enable.blockSignals(False)
        self.refresh_timer_status_label()

    def on_timer_interval_changed(self, index):
        if not self.chk_timer_enable.isChecked():
            return
        cur_int = self.combo_timer_interval.itemData(index) or DEFAULT_TIMER_INTERVAL
        success, msg = self.timer_mgr.set_timer(enabled=True, interval=cur_int)
        if success:
            self.append_log(f"\n[Background Timer] Updated interval to every {cur_int}.\n")
        else:
            self.append_log(f"\n[Background Timer] Failed to update interval: {msg}\n")
        self.refresh_timer_status_label()

    def test_notification_now(self):
        if self.test_notify_process and self.test_notify_process.state() != QProcess.ProcessState.NotRunning:
            return
        check_script = find_helper_script("check_zen_update.sh")
        if not os.path.isfile(check_script):
            self.append_log(f"\n[Background Timer] Script not found: {check_script}\n")
            return

        self.btn_test_notification.setEnabled(False)
        self.append_log("\n[Background Timer] Running background check script now...\n")
        self.test_notify_process = QProcess(self)
        self.test_notify_process.finished.connect(self.on_test_notification_finished)
        self.test_notify_process.start("bash", [check_script])

    def on_test_notification_finished(self, exit_code, _exit_status):
        self.btn_test_notification.setEnabled(True)
        if exit_code == 0:
            nid_file = os.path.join(get_cache_dir(), "zen_update_notification_id")
            if os.path.isfile(nid_file):
                self.append_log("✓ Background check completed: update notification dispatched.\n")
            else:
                self.append_log("✓ Background check completed: Zen Browser is up to date (no notification needed).\n")
        else:
            self.append_log(f"Error: Background check script exited with code {exit_code}.\n")

    def load_auto_check_app_setting(self):
        return bool(load_app_settings().get("auto_check_app_updates", False))

    def on_auto_check_app_toggled(self, checked):
        save_app_setting("auto_check_app_updates", checked)
        status = "enabled" if checked else "disabled"
        self.append_log(f"\n[Zen Updater] Automatic update checks on startup {status}.\n")

    def toggle_app_update_expanded(self):
        self.app_update_expanded = not self.app_update_expanded
        self.app_update_frame.setVisible(self.app_update_expanded)
        if self.app_update_expanded:
            self._collapse_other_sections("app")
        self.update_app_update_toggle_text()

    def update_app_update_toggle_text(self):
        arrow = "▼" if self.app_update_expanded else "▶"
        has_upd = self.app_update_info.get("has_update", False)
        upd_str = " (Update Available)" if has_upd else ""
        self.btn_toggle_app_update.setText(f"{arrow} Zen Updater Updates ({APP_VERSION}){upd_str}")

    def on_app_update_badge_clicked(self):
        if not self.app_update_expanded:
            self.toggle_app_update_expanded()
        self.btn_apply_app_update.setFocus()

    def start_app_update_check(self, silent=False):
        if self.app_check_worker and self.app_check_worker.isRunning():
            return

        if not silent:
            self.btn_check_app_update.setEnabled(False)
            self.lbl_app_lat_ver.setText("Checking GitHub...")
            self.lbl_app_update_status.setText("Querying GitHub releases for Zen Updater updates...")

        self.app_check_worker = CheckAppReleaseWorker()
        self.app_check_worker.finished.connect(lambda res: self.on_app_update_check_finished(res, silent))
        self.app_check_worker.start()

    def open_app_github_release(self):
        url = self.app_update_info.get("release_url") or f"https://github.com/{APP_REPO}/releases"
        QDesktopServices.openUrl(QUrl(url))

    def open_zen_github_release(self):
        url = self.zen_update_info.get("release_url") or "https://github.com/zen-browser/desktop/releases"
        QDesktopServices.openUrl(QUrl(url))

    def toggle_zen_notes(self):
        visible = not self.zen_notes_frame.isVisible()
        self.zen_notes_frame.setVisible(visible)
        self.btn_zen_notes.setText("Hide Notes" if visible else "Notes")

    def on_app_update_check_finished(self, result, silent):
        self.btn_check_app_update.setEnabled(True)
        self.app_update_info = result

        if result.get("error"):
            if not silent:
                self.lbl_app_lat_ver.setText("Check failed")
                self.lbl_app_update_status.setText(f"Check failed: {result['error']}")
                self.btn_app_github.setVisible(False)
                self.app_notes_frame.setVisible(False)
            return

        latest_ver = result["latest_version"]
        pub_date = result["release_date"]
        self.lbl_app_lat_ver.setText(f"{latest_ver} ({pub_date})")
        self.btn_app_github.setVisible(bool(result.get("release_url")))

        notes = (result.get("body") or "").strip()
        if notes:
            self.txt_app_notes.setMarkdown(notes)
            self.app_notes_frame.setVisible(True)
        else:
            self.app_notes_frame.setVisible(False)

        if result.get("has_update"):
            self.badge_app_update.setText(f"Update Available ({latest_ver})")
            self.badge_app_update.setVisible(True)
            self.btn_apply_app_update.setEnabled(True)
            self.lbl_app_update_status.setText(f"A new release ({latest_ver}) is available on GitHub Releases.")
        else:
            self.badge_app_update.setVisible(False)
            self.btn_apply_app_update.setEnabled(False)
            self.lbl_app_update_status.setText(f"Zen Updater is up to date ({APP_VERSION}).")
        self.update_app_update_toggle_text()

    def run_apply_app_update(self):
        target_ver = self.app_update_info.get("latest_version")
        if not target_ver or target_ver == "Unknown":
            QMessageBox.warning(self, "Unavailable", "Check for Zen Updater updates first to determine the target release.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Zen Updater Update",
            f"Do you want to update Zen Updater to release {target_ver}?\n\n"
            "This will download the official release files, update your installation, and restart the application.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_apply_app_update.setEnabled(False)
        self.btn_check_app_update.setEnabled(False)
        self.lbl_app_update_status.setText(f"Updating to {target_ver}... Please wait.")

        self.app_apply_worker = ApplyAppUpdateWorker(target_ver)
        self.app_apply_worker.progress.connect(self.on_apply_app_update_progress)
        self.app_apply_worker.finished.connect(self.on_apply_app_update_finished)
        self.app_apply_worker.start()

    def on_apply_app_update_progress(self, msg):
        self.lbl_app_update_status.setText(msg)
        self.append_log(f"[Zen Updater Self-Update] {msg}\n")

    def on_apply_app_update_finished(self, success, msg):
        self.btn_check_app_update.setEnabled(True)
        self.append_log(f"[Zen Updater Self-Update] {msg}\n")

        if success:
            if self.app_apply_worker and self.app_apply_worker.isRunning():
                self.app_apply_worker.wait(2000)
            QMessageBox.information(
                self,
                "Update Complete",
                f"{msg}\n\nThe application will now restart.",
            )
            installed_script = os.path.expanduser("~/.local/bin/zen_updater_gui.py")
            relaunch_target = installed_script if os.path.isfile(installed_script) else os.path.abspath(sys.argv[0])
            os.execv(sys.executable, [sys.executable, relaunch_target] + sys.argv[1:])
        else:
            self.btn_apply_app_update.setEnabled(bool(self.app_update_info.get("has_update")))
            QMessageBox.critical(
                self,
                "Update Failed",
                f"Failed to update Zen Updater:\n\n{msg}",
            )
            self.lbl_app_update_status.setText(f"Update failed: {msg}")

    def on_banner_clicked(self, _event):
        if self._banner_actionable and self.btn_run.isEnabled():
            self.run_update()

    def start_check(self):
        if self.check_worker and self.check_worker.isRunning():
            return

        self.btn_refresh.setEnabled(False)
        self.btn_run.setEnabled(False)
        self._set_banner_state("Checking for updates...", "checking")
        self.lbl_lat_ver.setText("Checking online...")
        self.lbl_lat_date.setText("Checking online...")
        self.btn_zen_notes.setVisible(False)
        self.btn_zen_github.setVisible(False)
        self.zen_notes_frame.setVisible(False)

        self.check_worker = CheckVersionWorker()
        self.check_worker.finished.connect(self.on_check_finished)
        self.check_worker.start()

    def on_check_finished(self, result):
        self.btn_refresh.setEnabled(True)
        self.zen_update_info = result

        self.lbl_cur_ver.setText(result["current_version"])
        self.lbl_cur_date.setText(f"Released: {result['current_date']}")
        self.lbl_lat_ver.setText(result["latest_version"])
        self.lbl_lat_date.setText(f"Released: {result['latest_date']}")

        self.btn_zen_github.setVisible(bool(result.get("release_url")))
        notes = (result.get("release_notes") or "").strip()
        if notes:
            self.txt_zen_notes.setMarkdown(notes)
            self.btn_zen_notes.setVisible(True)
            self.btn_zen_notes.setText("Notes")
        else:
            self.btn_zen_notes.setVisible(False)
        self.zen_notes_frame.setVisible(False)

        if result["error"] and result["latest_version"] == "Unknown":
            self._set_banner_state(f"Check failed: {result['error']}", "error")
            self.btn_run.setEnabled(False)
            return

        self.update_available = result["update_available"]
        self.install_info = result.get("install_info") or self.install_info
        install_type = self.install_info.get("type", "none")

        if install_type == "none":
            self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #a6f3a6; border: none; background: transparent;")
            self._set_banner_state(
                f"Zen Browser Not Installed  —  Click to Install {result['latest_version']}",
                "update",
                clickable=True,
                tooltip="Click to download and install Zen Browser",
            )
            self.btn_run.setText("Install Zen Browser")
            self.btn_run.setStyleSheet(GREEN_BTN_QSS)
            self.btn_run.setEnabled(True)
        elif install_type == "flatpak":
            self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #79c0ff; border: none; background: transparent;")
            self._set_banner_state(
                f"Flatpak Installation Detected ({result['current_version']})  —  Updates managed via Flathub",
                "info",
                clickable=False,
                tooltip="Flatpak installation detected. Use 'Install Portable' if you want to switch to the official portable release.",
            )
            self.btn_run.setText("Install Portable")
            self.btn_run.setStyleSheet(BLUE_BTN_QSS)
            self.btn_run.setEnabled(True)
        elif install_type == "system":
            if result["current_version"] == "Unknown" and result.get("error"):
                self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #d29922; border: none; background: transparent;")
                self._set_banner_state(
                    f"System Package Detected — {result['error']}",
                    "warning",
                    clickable=False,
                )
                self.btn_run.setText("Install Portable")
                self.btn_run.setStyleSheet(AMBER_BTN_QSS)
                self.btn_run.setEnabled(True)
            elif result["update_available"]:
                self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #d29922; border: none; background: transparent;")
                self._set_banner_state(
                    f"System Package Detected ({result['current_version']})  —  Update via Package Manager (or Install Portable)",
                    "warning",
                    clickable=True,
                    tooltip="Click to install a separate official portable release in your home directory",
                )
                self.btn_run.setText("Install Portable")
                self.btn_run.setStyleSheet(AMBER_BTN_QSS)
                self.btn_run.setEnabled(True)
            else:
                self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #58a6ff; border: none; background: transparent;")
                self._set_banner_state(
                    f"✓  System Package is up to date ({result['current_version']})",
                    "info",
                    clickable=False,
                )
                self.btn_run.setText("Reinstall Portable")
                self.btn_run.setStyleSheet(RED_OUTLINE_BTN_QSS)
                self.btn_run.setEnabled(True)
        elif result["current_version"] == "Unknown":
            self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #d29922; border: none; background: transparent;")
            err_detail = result.get("error") or "Could not determine installed Zen version from application.ini."
            self._set_banner_state(
                f"{err_detail} Click to Reinstall {result['latest_version']}.",
                "warning",
                clickable=True,
                tooltip="Click to reinstall Zen Browser",
            )
            self.btn_run.setText("Reinstall")
            self.btn_run.setStyleSheet(AMBER_BTN_QSS)
            self.btn_run.setEnabled(True)
        elif result["update_available"]:
            self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #a6f3a6; border: none; background: transparent;")
            self._set_banner_state(
                f"Update Available: Version {result['latest_version']} (Released {result['latest_date']})  —  Click to Install",
                "update",
                clickable=True,
                tooltip="Click to install this update",
            )
            self.btn_run.setText("Run Update")
            self.btn_run.setStyleSheet(GREEN_BTN_QSS)
            self.btn_run.setEnabled(True)
        else:
            relinked = self.profile_mgr.sync_profile_binaries()
            if relinked:
                self.append_log(f"Auto-synced profile executables: {', '.join(relinked)}\n")
            self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #58a6ff; border: none; background: transparent;")
            self._set_banner_state(
                f"✓  Zen Browser is up to date ({result['current_version']})",
                "info",
                clickable=False,
            )
            self.btn_run.setText("Reinstall")
            self.btn_run.setStyleSheet(RED_OUTLINE_BTN_QSS)
            self.btn_run.setEnabled(True)

        has_ext_profiles = any(
            p.get("full_path") and not p.get("ini_file", "").endswith(os.path.join(".zen", "profiles.ini"))
            for p in self.profiles
        )
        is_alt_install = install_type in ("flatpak", "system")
        self.btn_migration_badge.setVisible((is_alt_install or has_ext_profiles) and len(self.profiles) > 0)

    def _set_busy_controls(self, busy):
        """Enable or disable interactive controls while update_zen.sh is running."""
        self.btn_refresh.setEnabled(not busy)
        self.btn_run.setEnabled(not busy)
        self.btn_launch.setEnabled(not busy)
        self.btn_backup_now.setEnabled(not busy)
        self.chk_backup.setEnabled(not busy)
        self.btn_apply_app_update.setEnabled(not busy and bool(self.app_update_info.get("has_update")))
        self.btn_cancel.setVisible(busy)

    def run_backup_only(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if not os.path.isfile(UPDATE_SCRIPT):
            QMessageBox.critical(self, "Error", f"Update script not found at:\n{UPDATE_SCRIPT}")
            return

        self.active_process_mode = "backup"
        self._progress_in_extraction = False
        self._set_busy_controls(True)
        self._set_banner_state("Creating profile safety backup... Please wait.", "checking")

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)
        self.progress_bar.setFormat("Creating profile snapshot...")
        self.log_view.clear()
        self.append_log("Starting standalone profile safety backup...\n")

        target_dir = self.install_info.get("path") if self.install_info.get("type") == "tarball" else DEFAULT_TARBALL_DIR
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)
        self.process.finished.connect(self.on_process_finished)
        self.process.start("bash", [UPDATE_SCRIPT, "--backup-only", "--install-dir", target_dir])

    def open_backups_folder(self):
        backup_dir = os.path.expanduser("~/.zen-backups")
        os.makedirs(backup_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(backup_dir))

    def run_update(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if not os.path.isfile(UPDATE_SCRIPT):
            QMessageBox.critical(self, "Error", f"Update script not found at:\n{UPDATE_SCRIPT}")
            return

        dismiss_zen_notification()

        install_type = self.install_info.get("type", "tarball")
        target_dir = self.install_info.get("path", "")
        if not target_dir or install_type != "tarball":
            target_dir = DEFAULT_TARBALL_DIR

        backup_note = "A safety backup of all your profiles will be created before updating.\n\n" if self.chk_backup.isChecked() else ""

        if install_type == "none":
            confirm_msg = (
                f"Zen Browser was not detected on your system.\n\n"
                f"This will download and install the official portable release to:\n{target_dir}\n\n"
                "Do you want to proceed with the installation?"
            )
        elif install_type == "flatpak":
            confirm_msg = (
                f"Zen Browser appears to be installed via Flatpak.\n\n"
                f"Flatpak versions are managed and updated through Flathub or your Software Center.\n\n"
                f"Proceeding here will install a separate portable copy of Zen Browser to:\n{target_dir}\n\n"
                f"Note: Your existing Flatpak profile will be detected in the profile list below. "
                f"You can launch it and set it as your default profile anytime in 'about:profiles'.\n\n"
                f"{backup_note}"
                "Do you want to proceed with installing a separate portable version?"
            )
        elif install_type == "system":
            confirm_msg = (
                f"Zen Browser appears to be installed via your system package manager.\n\n"
                f"It is recommended to update system packages through your distribution package manager.\n\n"
                f"Proceeding here will install a separate portable copy of Zen Browser in your user directory:\n{target_dir}\n\n"
                f"Note: Your existing profile will be detected in the profile list below. "
                f"You can launch it and set it as your default profile anytime in 'about:profiles'.\n\n"
                f"{backup_note}"
                "Do you want to proceed with installing a separate portable version?"
            )
        elif self.btn_run.text() == "Reinstall":
            confirm_msg = (
                f"Zen Browser is already on the latest version.\n\n"
                f"This will re-install core files into {target_dir}, re-link isolated profile binaries, and apply policy safeguards.\n\n"
                f"{backup_note}"
                "Do you want to proceed?"
            )
        else:
            confirm_msg = (
                f"This will download the update, close any running Zen Browser windows, and install into:\n{target_dir}\n\n"
                f"{backup_note}"
                "Do you want to proceed?"
            )

        suppress_confirm = bool(load_app_settings().get("suppress_update_confirmation", False))
        if not suppress_confirm:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Confirm Installation / Update")
            msg_box.setText(confirm_msg)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)

            chk_dont_show = QCheckBox("Do not show this warning again")
            chk_dont_show.setCursor(Qt.CursorShape.PointingHandCursor)
            chk_dont_show.setStyleSheet(get_checkbox_qss())
            msg_box.setCheckBox(chk_dont_show)

            reply = msg_box.exec()
            if reply != QMessageBox.StandardButton.Yes:
                return

            if chk_dont_show.isChecked():
                save_app_setting("suppress_update_confirmation", True)
                self.append_log("\n[Settings] Pre-update confirmation warning permanently disabled.\n")

        self.active_process_mode = "update"
        self._progress_in_extraction = False
        self._set_busy_controls(True)
        self.set_launch_button_highlighted(False)

        action_label = "Installing" if install_type == "none" else "Updating"
        self._set_banner_state(f"{action_label} Zen Browser... Please wait.", "checking")

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(5)
        self.progress_bar.setFormat(f"Initializing {action_label.lower()}...")
        self.log_view.clear()
        self.append_log(f"Starting {action_label.lower()} process for {target_dir}...\n")

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)
        self.process.finished.connect(self.on_process_finished)

        args = [UPDATE_SCRIPT, "--force", "--install-dir", target_dir]
        if self.chk_backup.isChecked():
            args.append("--backup")
        else:
            args.append("--no-backup")

        self.process.start("bash", args)

    def cancel_active_process(self):
        if not self.process or self.process.state() == QProcess.ProcessState.NotRunning:
            return
        self.btn_cancel.setEnabled(False)
        self.append_log("\n[Cancel] Terminating active process...\n")
        self.process.terminate()
        QTimer.singleShot(2500, self._force_kill_if_running)

    def _force_kill_if_running(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def on_stdout(self):
        if not self.process:
            return
        data = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self.process_output(data)

    def on_stderr(self):
        if not self.process:
            return
        data = self.process.readAllStandardError().data().decode("utf-8", errors="replace")
        self.process_output(data)

    def process_output(self, text):
        """Parse milestones and curl download percentages without spamming carriage-return progress lines."""
        clean_text = re.sub(r'\x1b\[[0-9;]*[mK]', '', text)

        # Extract download percentages before stripping curl progress bar noise
        if not self._progress_in_extraction:
            pct_matches = re.findall(r'(\d+(?:\.\d+)?)%', clean_text)
            if pct_matches:
                try:
                    curl_pct = float(pct_matches[-1])
                    if 0.0 <= curl_pct <= 100.0:
                        mapped = int(15 + (curl_pct * 0.55))
                        if mapped >= self.progress_bar.value():
                            self.progress_bar.setValue(mapped)
                        self.progress_bar.setFormat(f"Downloading: {curl_pct:.1f}%")
                except ValueError:
                    pass

        # Strip carriage-return curl progress bars from the visible console log
        filtered_lines = []
        for segment in clean_text.splitlines(keepends=True):
            if "\r" in segment:
                parts = [p for p in segment.split("\r") if p.strip()]
                for part in parts:
                    if not re.match(r'^[\s#=\-\.\d%]+$', part.strip()):
                        filtered_lines.append(part + ("\n" if not part.endswith("\n") else ""))
            else:
                if not re.match(r'^[\s#]+\s*\d+(?:\.\d+)?%\s*$', segment.strip()):
                    filtered_lines.append(segment)

        if filtered_lines:
            self.append_log("".join(filtered_lines))

        if "[1/4] Downloading" in clean_text or "[1/3] Downloading" in clean_text:
            self.progress_bar.setValue(max(self.progress_bar.value(), 15))
            self.progress_bar.setFormat("Starting download...")
        if "[2/4] Extracting" in clean_text or "[2/3] Extracting" in clean_text:
            self._progress_in_extraction = True
            self.progress_bar.setValue(max(self.progress_bar.value(), 74))
            self.progress_bar.setFormat("Extracting archive...")
        if "Closing all running Zen" in clean_text:
            self._progress_in_extraction = True
            self.progress_bar.setValue(max(self.progress_bar.value(), 78))
            self.progress_bar.setFormat("Closing browser instances...")
        if "[Safety Backup] Creating snapshot" in clean_text:
            self._progress_in_extraction = True
            self.progress_bar.setValue(max(self.progress_bar.value(), 82))
            self.progress_bar.setFormat("Creating profile safety backup...")
        if "Safety backup created" in clean_text:
            self.progress_bar.setValue(max(self.progress_bar.value(), 86))
            self.progress_bar.setFormat("Backup complete.")
        if "[3/4] Deploying" in clean_text or "Deploying files" in clean_text:
            self._progress_in_extraction = True
            self.progress_bar.setValue(max(self.progress_bar.value(), 90))
            self.progress_bar.setFormat("Deploying files...")
        if "[4/4] Re-linking" in clean_text or "[3/3] Re-linking" in clean_text:
            self._progress_in_extraction = True
            self.progress_bar.setValue(max(self.progress_bar.value(), 95))
            self.progress_bar.setFormat("Re-linking profile binaries...")
        if "successfully updated" in clean_text:
            self._progress_in_extraction = True
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Update Complete (100%)")

    def append_log(self, text):
        self.log_view.moveCursor(self.log_view.textCursor().MoveOperation.End)
        self.log_view.insertPlainText(text)
        self.log_view.moveCursor(self.log_view.textCursor().MoveOperation.End)

    def on_process_finished(self, exit_code, exit_status):
        self._set_busy_controls(False)
        self.btn_cancel.setEnabled(True)

        if self.active_process_mode == "backup":
            if exit_code == 0:
                self.progress_bar.setValue(100)
                self.progress_bar.setFormat("Backup Complete (100%)")
                self._set_banner_state("Profile safety backup created successfully.", "success")
                self.append_log("\n✓ Profile safety backup finished.\n")
                QTimer.singleShot(2500, self.start_check)
            else:
                self._set_banner_state(f"Backup failed with exit code {exit_code}", "error")
                self.append_log(f"\nError: Backup exited with code {exit_code}.\n")
            return

        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            dismiss_zen_notification()
            self.profile_mgr.refresh_install_dir()
            relinked = self.profile_mgr.sync_profile_binaries()
            if relinked:
                self.append_log(f"Refreshed profile executables: {', '.join(relinked)}\n")
            self.refresh_profiles()
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Update Complete (100%)")
            self._set_banner_state("Zen Browser updated successfully!", "success")
            self.set_launch_button_highlighted(True)
            self.append_log("\n✓ Update complete! You can now launch your Zen profiles.\n")
            if len(self.profiles) > 1:
                self.append_log(
                    "Tip: To make a profile your permanent default, launch it, navigate to\n"
                    "     about:profiles in the URL bar, and click 'Set as default profile'.\n"
                )
            self.start_check()
        else:
            self.set_launch_button_highlighted(False)
            self._set_banner_state(f"Update failed or cancelled (exit code {exit_code})", "error")
            self.append_log(f"\nProcess ended with status code {exit_code}.\n")

    def show_backup_info(self):
        help_text = (
            "<b>Profile Safety Backup Details:</b><br><br>"
            "• <b>Location:</b> Stored in <code>~/.zen-backups/</code><br>"
            "• <b>Auto-Pruned:</b> Automatically retains only the <b>2 most recent</b> snapshots so backups never accumulate.<br>"
            "• <b>Coverage:</b> Backs up profiles using multi-threaded <code>zstd</code> compression while excluding transient cache files."
        )
        pos = self.btn_backup_help.mapToGlobal(QPoint(self.btn_backup_help.width() // 2, self.btn_backup_help.height() + 4))
        QToolTip.showText(pos, help_text, self.btn_backup_help)

    def show_profile_help(self):
        help_text = (
            "<b>Profile Management & Migration:</b><br><br>"
            "• <b>Switching to Portable:</b> If you installed the portable version after using a Flatpak or repo package, "
            "select your previous profile checkbox here to launch it.<br>"
            "• <b>Setting as Default:</b> Once Zen opens, type <code>about:profiles</code> in the address bar, "
            "find your preferred profile, and click <b>Set as default profile</b>.<br>"
            "• <b>Multi-Profile:</b> Checked profiles launch staggered by 250ms when clicking 'Launch Zen'."
        )
        pos = self.btn_profile_help.mapToGlobal(QPoint(self.btn_profile_help.width() // 2, self.btn_profile_help.height() + 4))
        QToolTip.showText(pos, help_text, self.btn_profile_help)

    def show_migration_dialog(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Profile Migration Guide")
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setText(
            "<h3>Migrating Existing Profiles to Portable Zen</h3>"
            "<p>An existing Flatpak or Linux distribution installation was detected on your system. "
            "Your existing bookmarks, logins, and tabs are fully preserved.</p>"
            "<p><b>How to set your existing profile as default:</b></p>"
            "<ol style='margin-left: -15px;'>"
            "<li>Under <b>Launch Profiles</b>, check your previous profile (e.g. <i>Default Profile [Flatpak]</i>).</li>"
            "<li>Click <b>Launch Zen</b>. Zen will open with your data safely loaded.</li>"
            "<li>In Zen's address bar, type <code>about:profiles</code> and hit Enter.</li>"
            "<li>Find your profile in the list and click <b>Set as default profile</b>.</li>"
            "</ol>"
            "<p>From now on, all application menu shortcuts and browser links will open your profile automatically!</p>"
        )
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def launch_zen(self):
        self.set_launch_button_highlighted(False)
        dismiss_zen_notification()
        self.profile_mgr.refresh_install_dir()
        relinked = self.profile_mgr.sync_profile_binaries()
        if relinked:
            self.append_log(f"Auto-synced profile executables: {', '.join(relinked)}\n")

        zen_bin = os.path.join(self.profile_mgr.install_dir, "zen")
        if not os.path.isfile(zen_bin):
            sys_zen = shutil.which("zen") or shutil.which("zen-browser")
            if sys_zen:
                zen_bin = sys_zen
            else:
                QMessageBox.warning(self, "Warning", f"Zen binary not found at:\n{zen_bin}")
                return

        to_launch = [p for p in self.profiles if p["key"] in self.selected_profiles]
        if not to_launch:
            QProcess.startDetached(zen_bin, ["--allow-downgrade"])
            self.append_log("\nLaunched default Zen Browser instance.\n")
            return

        self.append_log(f"\nLaunching {len(to_launch)} profile(s)...\n")

        for idx, prof in enumerate(to_launch):
            prog = zen_bin
            args = None

            if prof.get("exec_cmd") and not prof.get("is_flatpak_exec"):
                clean = re.sub(r'%[uUfF]', '', prof["exec_cmd"]).strip()
                try:
                    parts = shlex.split(clean)
                except ValueError:
                    parts = clean.split()
                if parts and os.path.isfile(parts[0]):
                    prog = parts[0]
                    args = parts[1:]

            if args is None:
                is_standard_ini = prof.get("ini_file", "").endswith(os.path.join(".zen", "profiles.ini"))
                if prof.get("full_path") and not is_standard_ini:
                    args = ["--allow-downgrade", "--no-remote", "--profile", prof["full_path"]]
                elif prof["is_default"]:
                    args = ["--allow-downgrade"]
                else:
                    args = ["--allow-downgrade", "--no-remote", "-P", prof["name"]]

            delay = idx * 250
            if delay == 0:
                self._do_launch(prog, args, prof["display_name"])
            else:
                QTimer.singleShot(
                    delay,
                    lambda prg=prog, arg=args, dname=prof["display_name"]: self._do_launch(prg, arg, dname),
                )

    def _do_launch(self, prog, args, display_name):
        QProcess.startDetached(prog, args)
        self.append_log(f" - Launched {display_name}\n")

    def closeEvent(self, event):
        """Confirm before aborting an active update and cleanly wait on worker threads."""
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            reply = QMessageBox.question(
                self,
                "Operation in Progress",
                "An update or backup process is currently running. Stop it and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.process.terminate()
            if not self.process.waitForFinished(2000):
                self.process.kill()
                self.process.waitForFinished(1000)

        for worker in (self.check_worker, self.app_check_worker, self.app_apply_worker, self.startup_timer_worker):
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(1500)

        if self.test_notify_process and self.test_notify_process.state() != QProcess.ProcessState.NotRunning:
            self.test_notify_process.terminate()
            self.test_notify_process.waitForFinished(1000)

        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Zen Browser Updater")
    app.setDesktopFileName("zen-updater")
    window = ZenUpdaterWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
