#!/usr/bin/env python3
"""
Zen Browser Updater GUI
Provides a native Qt6 interface to check, backup, update, and launch Zen Browser profiles.
"""

import sys
import os
import re
import json
import glob
import shlex
import shutil
import subprocess
import configparser
import urllib.request
import urllib.error
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QProcess, QTimer, QPoint
from PyQt6.QtGui import QIcon, QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QTextEdit, QFrame, QSizePolicy,
    QMessageBox, QGridLayout, QCheckBox, QScrollArea, QComboBox, QToolTip
)

APP_VERSION = "v1.0.4"  # Set to v1.0.4 for test update (latest GitHub release is v1.0.5)
APP_REPO = "PlasmaDrifter/Zen.updater.gui"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_app_settings():
    path = os.path.expanduser("~/.config/zen-updater/settings.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_app_setting(key, val):
    config_dir = os.path.expanduser("~/.config/zen-updater")
    os.makedirs(config_dir, exist_ok=True)
    path = os.path.join(config_dir, "settings.json")
    settings = load_app_settings()
    settings[key] = val
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print("Error saving setting:", e)


def parse_app_version(ver_str):
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
    try:
        return parse_app_version(latest_str) > parse_app_version(cur_str)
    except Exception:
        return False


def find_zen_icon():
    candidates = [
        os.path.join(SCRIPT_DIR, "assets", "icon.png"),
        os.path.join(SCRIPT_DIR, "assets", "zen-updater.png"),
        os.path.expanduser("~/Pictures/Avatar/Square_App_Icons/Zen-Browser/zen_browser_ice_steel_256.png"),
        os.path.expanduser("~/.local/share/icons/zen-updater.png"),
        os.path.expanduser("~/Pictures/Avatar/Square_App_Icons/Zen-Browser/zen_browser_ice_steel_128.png"),
        os.path.expanduser("~/.tarball-installations/zen/browser/chrome/icons/default/default128.png"),
        os.path.expanduser("~/.tarball-installations/zen/icons/updater.png"),
        "/usr/share/icons/hicolor/128x128/apps/zen-browser.png",
        "/usr/share/pixmaps/zen.png",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""


def find_update_script():
    candidates = [
        os.path.join(SCRIPT_DIR, "update_zen.sh"),
        os.path.expanduser("~/Scripts/update_zen.sh"),
        os.path.expanduser("~/.local/bin/update_zen.sh"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return os.path.join(SCRIPT_DIR, "update_zen.sh")


DEFAULT_TARBALL_DIR = os.path.expanduser("~/.tarball-installations/zen")


def detect_zen_installation():
    """
    Detects how Zen Browser is installed on the system:
    Returns dict:
      - 'type': 'tarball' | 'flatpak' | 'system' | 'none'
      - 'path': directory or identifier
      - 'ini': path to application.ini if found
      - 'description': human-readable summary
    """
    # 1. Check known/common user-level tarball locations
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
            return {
                "type": "tarball",
                "path": cand,
                "ini": ini_file,
                "description": f"Portable tarball ({cand})"
            }

    # 2. Check Flatpak
    try:
        res = subprocess.run(["flatpak", "info", "app.zen_browser.zen"], capture_output=True, text=True)
        if res.returncode == 0:
            # Check if version can be extracted
            flatpak_ver = "Unknown"
            for line in res.stdout.splitlines():
                if line.strip().startswith("Version:"):
                    flatpak_ver = line.split(":", 1)[1].strip()
                    break
            return {
                "type": "flatpak",
                "path": "app.zen_browser.zen",
                "ini": "",
                "flatpak_ver": flatpak_ver,
                "description": "Flatpak (app.zen_browser.zen)"
            }
    except Exception:
        pass

    # 3. Check System / Distro Packages
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
                "description": f"System package ({cand})"
            }

    # 4. Check PATH binary if symlinked
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
                    "description": f"User binary ({bin_dir})" if is_user else f"System package ({bin_dir})"
                }
        except Exception:
            pass

    return {
        "type": "none",
        "path": "",
        "ini": "",
        "description": "Not installed"
    }


ICON_PATH = find_zen_icon()
UPDATE_SCRIPT = find_update_script()
INSTALL_INFO = detect_zen_installation()
APP_INI = INSTALL_INFO.get("ini") or os.path.join(DEFAULT_TARBALL_DIR, "application.ini")

CHECKMARK_ICON_PATH = os.path.join(SCRIPT_DIR, "assets", "checkmark.png")


def ensure_checkmark_icon():
    """Ensure the checkmark PNG icon exists in assets."""
    if os.path.isfile(CHECKMARK_ICON_PATH):
        return CHECKMARK_ICON_PATH
    try:
        from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
        from PyQt6.QtCore import Qt
        os.makedirs(os.path.dirname(CHECKMARK_ICON_PATH), exist_ok=True)
        pix = QPixmap(14, 14)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor('#ffffff'), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(2, 7, 5, 11)
        p.drawLine(5, 11, 12, 3)
        p.end()
        pix.save(CHECKMARK_ICON_PATH, 'PNG')
    except Exception:
        pass
    return CHECKMARK_ICON_PATH


def get_checkbox_qss():
    ensure_checkmark_icon()
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
        image: url("{CHECKMARK_ICON_PATH}");
    }}
    QCheckBox::indicator:checked:disabled {{
        background-color: #238636;
        border-color: #2ea043;
        image: url("{CHECKMARK_ICON_PATH}");
    }}
    """


def dismiss_zen_notification():
    """Dismiss any active Zen update notification via DBus."""
    cache_dir = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    nid_file = os.path.join(cache_dir, "zen_update_notification_id")
    target_nid = None
    if os.path.isfile(nid_file):
        try:
            with open(nid_file, "r") as f:
                val = f.read().strip()
                if val.isdigit():
                    target_nid = int(val)
            os.remove(nid_file)
        except Exception:
            pass

    if target_nid:
        try:
            import dbus
            bus = dbus.SessionBus()
            notify_obj = bus.get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
            notify_iface = dbus.Interface(notify_obj, "org.freedesktop.Notifications")
            notify_iface.CloseNotification(dbus.UInt32(target_nid))
        except Exception:
            try:
                os.system(f"qdbus org.freedesktop.Notifications /org/freedesktop/Notifications CloseNotification {target_nid} >/dev/null 2>&1")
            except Exception:
                pass


class ZenProfileManager:
    """Manages discovering, configuring, and launching Zen Browser profiles."""
    def __init__(self):
        self.config_dir = os.path.expanduser("~/.config/zen-updater")
        self.settings_file = os.path.join(self.config_dir, "settings.json")
        self.zen_dir = os.path.expanduser("~/.zen")
        self.ini_path = os.path.join(self.zen_dir, "profiles.ini")
        self.install_dir = INSTALL_INFO["path"] if (INSTALL_INFO["type"] == "tarball" and os.path.isdir(INSTALL_INFO["path"])) else (
            os.path.dirname(APP_INI) if os.path.isfile(APP_INI) else DEFAULT_TARBALL_DIR
        )

    def get_profiles(self):
        profiles = []
        # Candidates for profiles.ini across repo builds, tarball, and flatpak
        candidates = [
            os.path.expanduser("~/.config/zen/profiles.ini"),
            os.path.expanduser("~/.zen/profiles.ini"),
            os.path.expanduser("~/.var/app/app.zen_browser.zen/.zen/profiles.ini"),
            os.path.expanduser("~/.var/app/app.zen_browser.zen/.config/zen/profiles.ini"),
        ]

        seen_paths = set()
        desktop_map = self._scan_desktop_files()

        for ini_file in candidates:
            if not os.path.isfile(ini_file):
                continue

            cp = configparser.ConfigParser()
            try:
                cp.read(ini_file)
            except Exception:
                continue

            base_dir = os.path.dirname(ini_file)
            is_flatpak = ".var/app" in ini_file
            is_xdg = ".config/zen" in ini_file

            default_path = None
            for sec in cp.sections():
                if sec.startswith("Install") and cp.has_option(sec, "Default"):
                    default_path = cp.get(sec, "Default")
                    break

            for sec in cp.sections():
                if sec.startswith("Profile"):
                    name = cp.get(sec, "Name", fallback="")
                    path = cp.get(sec, "Path", fallback="")
                    is_rel = cp.get(sec, "IsRelative", fallback="1") == "1"

                    if not name or not path:
                        continue

                    full_profile_path = os.path.join(base_dir, path) if is_rel else path
                    if not os.path.isdir(full_profile_path):
                        continue
                    if full_profile_path in seen_paths:
                        continue
                    seen_paths.add(full_profile_path)

                    if default_path:
                        is_def = (path == default_path)
                    else:
                        is_def = (cp.get(sec, "Default", fallback="0") == "1")

                    desktop_info = desktop_map.get(name)
                    if name == "zen-YT":
                        display_name = "YouTube (zen-YT)"
                    elif name == "Qbittorrent":
                        display_name = "qBittorrent WebUI (Qbittorrent)"
                    elif name == "Default (twilight)":
                        display_name = "Twilight Profile"
                    elif name == "Default Profile":
                        display_name = "Default Profile (Secondary)"
                    elif desktop_info and desktop_info.get("name"):
                        dname = desktop_info["name"]
                        if dname.lower().startswith("zen browser (") and dname.endswith(")"):
                            dname = dname[len("zen browser ("):-1]
                        elif dname.lower().startswith("zen browser"):
                            dname = dname[len("zen browser"):].strip(" -:")
                        display_name = f"{dname} ({name})" if dname and dname != name else (dname or name)
                    else:
                        display_name = name

                    if is_flatpak:
                        display_name = f"{display_name} [Flatpak]"
                    elif is_xdg and not os.path.isfile(os.path.expanduser("~/.zen/profiles.ini")):
                        # Standard repo location
                        pass

                    if is_def:
                        if not display_name.lower().endswith("default") and not "[flatpak]" in display_name.lower():
                            display_name = f"{display_name} - Default"

                    profiles.append({
                        "name": name,
                        "path": path,
                        "full_path": full_profile_path,
                        "ini_file": ini_file,
                        "is_default": is_def,
                        "display_name": display_name,
                        "desktop_file": desktop_info["file"] if desktop_info else None,
                        "exec_cmd": desktop_info["exec"] if desktop_info else None
                    })

        # Ensure default profile is first in list, followed by desktop-configured profiles, then alphabetical
        profiles.sort(key=lambda p: (not p["is_default"], not bool(p["desktop_file"]), p["display_name"]))
        return profiles

    def _scan_desktop_files(self):
        mapping = {}
        search_dirs = [
            os.path.expanduser("~/.local/share/applications"),
            "/usr/local/share/applications",
            "/usr/share/applications"
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
                    for line in content.splitlines():
                        line = line.strip()
                        if line.startswith("Exec="):
                            exec_cmd = line[5:].strip()
                        elif line.startswith("Name=") and not app_name:
                            app_name = line[5:].strip()

                    if exec_cmd:
                        m = re.search(r"-P\s+([^\s]+)", exec_cmd)
                        if m:
                            pname = m.group(1).strip("\"'\\")
                            if pname not in mapping:
                                mapping[pname] = {
                                    "file": fpath,
                                    "name": app_name or pname,
                                    "exec": exec_cmd
                                }
                except Exception:
                    pass
        return mapping

    def load_selected_profiles(self, profiles):
        selected = set()
        default_profile_name = None
        for p in profiles:
            if p["is_default"]:
                default_profile_name = p["name"]

        if os.path.isfile(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
                    for item in data.get("selected_profiles", []):
                        selected.add(item)
            except Exception:
                pass
        else:
            # Default to all profiles with desktop entries or default profile
            for p in profiles:
                if p["is_default"] or p["desktop_file"]:
                    selected.add(p["name"])

        return selected

    def save_selected_profiles(self, selected_set):
        save_app_setting("selected_profiles", sorted(list(selected_set)))

    def sync_profile_binaries(self):
        """Ensures all isolated profile executables match the main zen binary hardlink."""
        zen_bin = os.path.join(self.install_dir, "zen")
        if not os.path.isfile(zen_bin):
            return []

        try:
            zen_stat = os.stat(zen_bin)
        except OSError:
            return []

        target_bins = {"zen-youtube", "qbittorrent-webui", "zen-qbittorrent", "zen-bin"}

        desktop_dir = os.path.expanduser("~/.local/share/applications")
        if os.path.isdir(desktop_dir):
            for dfile in glob.glob(os.path.join(desktop_dir, "*.desktop")):
                try:
                    with open(dfile, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if line.startswith(f"Exec={self.install_dir}/"):
                                m = re.match(rf"^Exec={re.escape(self.install_dir)}/([^\s\"']+)", line)
                                if m:
                                    tbin = m.group(1)
                                    if tbin and tbin != "zen":
                                        target_bins.add(tbin)
                                break
                except Exception:
                    pass

        relinked = []
        for tbin in sorted(target_bins):
            tpath = os.path.join(self.install_dir, tbin)
            needs_link = False
            if not os.path.exists(tpath):
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
                    if os.path.exists(tpath):
                        os.unlink(tpath)
                    os.link(zen_bin, tpath)
                    relinked.append(tbin)
                except Exception:
                    try:
                        import shutil
                        shutil.copy2(zen_bin, tpath)
                        relinked.append(tbin)
                    except Exception:
                        pass

        self.ensure_update_policy()
        return relinked

    def ensure_update_policy(self):
        """Ensures distribution/policies.json disables internal background updates."""
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
        except Exception:
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
        """Returns dict with available, installed, active, enabled, interval, and next_run."""
        res = {
            "available": self.has_systemctl,
            "installed": os.path.isfile(self.timer_path),
            "active": False,
            "enabled": False,
            "interval": "6h",
            "next_run": "Unknown"
        }
        if not self.has_systemctl:
            return res

        # Read interval from timer file if present
        if os.path.isfile(self.timer_path):
            try:
                with open(self.timer_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("OnUnitActiveSec="):
                            res["interval"] = line.strip().split("=", 1)[1].strip()
                            break
            except Exception:
                pass

        # Check active state
        try:
            out = subprocess.check_output(
                ["systemctl", "--user", "is-active", "zen-update-check.timer"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            res["active"] = (out == "active")
        except Exception:
            res["active"] = False

        # Check enabled state
        try:
            out = subprocess.check_output(
                ["systemctl", "--user", "is-enabled", "zen-update-check.timer"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            res["enabled"] = (out == "enabled")
        except Exception:
            res["enabled"] = False

        # Check next run
        try:
            out = subprocess.check_output(
                ["systemctl", "--user", "list-timers", "zen-update-check.timer", "--no-legend", "--full"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            m = re.search(r'(\d+h\s*\d+min|\d+min|\d+h|\d+s)', out)
            if m:
                res["next_run"] = m.group(1)
        except Exception:
            pass

        return res

    def ensure_service_file(self):
        """Creates the systemd service file if it doesn't already exist."""
        if not os.path.isfile(self.service_path):
            os.makedirs(self.systemd_dir, exist_ok=True)
            check_script = os.path.join(SCRIPT_DIR, "check_zen_update.sh")
            if not os.path.isfile(check_script):
                check_script = os.path.expanduser("~/Scripts/check_zen_update.sh")
            if not os.path.isfile(check_script):
                check_script = os.path.expanduser("~/.local/bin/check_zen_update.sh")

            content = (
                "[Unit]\n"
                "Description=Check Zen Browser for Updates\n"
                "After=graphical-session.target\n\n"
                "[Service]\n"
                "Type=oneshot\n"
                f"ExecStart={check_script}\n"
            )
            with open(self.service_path, "w", encoding="utf-8") as f:
                f.write(content)

    def write_timer_file(self, interval="6h"):
        """Writes the timer file with the chosen interval."""
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

    def set_timer(self, enabled=True, interval="6h"):
        """Configures and starts/stops the systemd user timer."""
        if not self.has_systemctl:
            return False, "systemctl is not available on this system."

        try:
            if enabled:
                self.ensure_service_file()
                self.write_timer_file(interval)
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
                subprocess.run(["systemctl", "--user", "enable", "--now", "zen-update-check.timer"], check=True)
                return True, f"Timer enabled: checking every {interval}."
            else:
                subprocess.run(["systemctl", "--user", "disable", "--now", "zen-update-check.timer"], check=True)
                return True, "Timer disabled."
        except Exception as e:
            return False, str(e)

    def trigger_check_now(self):
        """Runs the service immediately for testing."""
        if not self.has_systemctl:
            return False, "systemctl is not available."
        try:
            self.ensure_service_file()
            subprocess.run(["systemctl", "--user", "start", "zen-update-check.service"], check=True)
            return True, "Update check initiated in background."
        except Exception as e:
            return False, str(e)


def format_iso_date(iso_str):
    if not iso_str:
        return "Unknown"
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        return dt.strftime("%b %d, %Y (%H:%M UTC)")
    except Exception:
        return iso_str.split("T")[0] if "T" in iso_str else iso_str


def format_build_id(build_id):
    if not build_id or len(build_id) < 8:
        return "Unknown"
    try:
        dt = datetime.strptime(build_id[:8], "%Y%m%d")
        return dt.strftime("%b %d, %Y")
    except Exception:
        return build_id


class CheckVersionWorker(QThread):
    finished = pyqtSignal(dict)

    def run(self):
        install_info = detect_zen_installation()
        result = {
            "current_version": "Unknown",
            "current_date": "Unknown",
            "latest_version": "Unknown",
            "latest_date": "Unknown",
            "update_available": False,
            "install_info": install_info,
            "error": None
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
            except Exception as e:
                result["error"] = f"Failed to read application.ini: {e}"

        if build_id:
            result["current_date"] = format_build_id(build_id)

        # 2. Fetch Latest Version from GitHub redirect / API
        headers = {"User-Agent": "Zen-Browser-Updater-GUI/1.0"}
        latest_tag = None
        latest_published_at = None

        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/zen-browser/desktop/releases/latest",
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latest_tag = data.get("tag_name")
                latest_published_at = data.get("published_at")
        except Exception:
            # Fallback to redirect check
            try:
                redirect_req = urllib.request.Request(
                    "https://github.com/zen-browser/desktop/releases/latest",
                    headers=headers
                )
                with urllib.request.urlopen(redirect_req, timeout=10) as resp:
                    final_url = resp.geturl()
                    latest_tag = final_url.rstrip("/").split("/")[-1]
            except Exception:
                pass

            # Fallback to update.xml if redirect also fails
            if not latest_tag:
                try:
                    req_xml = urllib.request.Request(
                        "https://updates.zen-browser.app/updates/browser/Linux_x86_64-gcc3/release/update.xml",
                        headers=headers
                    )
                    with urllib.request.urlopen(req_xml, timeout=10) as resp_xml:
                        xml_content = resp_xml.read().decode("utf-8")
                        match_ver = re.search(r'displayVersion="([^"]+)"', xml_content)
                        if match_ver:
                            latest_tag = match_ver.group(1)
                        match_bid = re.search(r'buildID="([^"]+)"', xml_content)
                        if match_bid:
                            latest_published_at = format_build_id(match_bid.group(1))
                except Exception as e_xml:
                    result["error"] = f"Network error: {e_xml}"

        if latest_tag:
            result["latest_version"] = latest_tag
            result["latest_date"] = format_iso_date(latest_published_at) if latest_published_at else "Unknown"

            if result["current_version"] == latest_tag and latest_published_at:
                result["current_date"] = result["latest_date"]
            elif result["current_version"] != "Unknown" and result["current_version"] != latest_tag:
                try:
                    cur_req = urllib.request.Request(
                        f"https://api.github.com/repos/zen-browser/desktop/releases/tags/{result['current_version']}",
                        headers=headers
                    )
                    with urllib.request.urlopen(cur_req, timeout=8) as cur_resp:
                        cur_data = json.loads(cur_resp.read().decode("utf-8"))
                        if cur_data.get("published_at"):
                            result["current_date"] = format_iso_date(cur_data.get("published_at"))
                except Exception:
                    pass

            if result["current_version"] != "Unknown":
                result["update_available"] = (result["current_version"] != result["latest_version"])
        else:
            if not result["error"]:
                result["error"] = "Unable to determine latest version."

        self.finished.emit(result)


class CheckAppReleaseWorker(QThread):
    finished = pyqtSignal(dict)

    def run(self):
        result = {
            "has_update": False,
            "latest_version": "Unknown",
            "release_date": "Unknown",
            "release_url": "",
            "tarball_url": "",
            "body": "",
            "error": None
        }
        url = f"https://api.github.com/repos/{APP_REPO}/releases/latest"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"ZenUpdater/{APP_VERSION}",
                "Accept": "application/vnd.github.v3+json"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
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
        except urllib.error.HTTPError as e:
            result["error"] = f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            result["error"] = str(e)

        self.finished.emit(result)


class ApplyAppUpdateWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, target_version):
        super().__init__()
        self.target_version = target_version

    def run(self):
        try:
            import tempfile, tarfile
            self.progress.emit(f"Downloading Zen Updater {self.target_version}...")

            git_dir = os.path.join(SCRIPT_DIR, ".git")
            if os.path.isdir(git_dir):
                self.progress.emit("Updating via git repository...")
                subprocess.run(["git", "fetch", "--tags"], cwd=SCRIPT_DIR, capture_output=True, text=True)
                res = subprocess.run(["git", "checkout", self.target_version], cwd=SCRIPT_DIR, capture_output=True, text=True)
                if res.returncode != 0:
                    subprocess.run(["git", "pull", "origin", "main"], cwd=SCRIPT_DIR, capture_output=True, text=True)
                inst_sh = os.path.join(SCRIPT_DIR, "install.sh")
                if os.path.isfile(inst_sh):
                    self.progress.emit("Running installer script...")
                    subprocess.run(["bash", inst_sh], cwd=SCRIPT_DIR, check=True)
            else:
                download_url = f"https://github.com/{APP_REPO}/archive/refs/tags/{self.target_version}.tar.gz"
                req = urllib.request.Request(
                    download_url,
                    headers={"User-Agent": f"ZenUpdater/{APP_VERSION}"}
                )
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tar_path = os.path.join(tmp_dir, "release.tar.gz")
                    with urllib.request.urlopen(req, timeout=20) as resp, open(tar_path, "wb") as out_f:
                        shutil.copyfileobj(resp, out_f)

                    self.progress.emit("Extracting release files...")
                    with tarfile.open(tar_path, "r:gz") as tar:
                        tar.extractall(path=tmp_dir)

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
                        self.progress.emit("Running installer script...")
                        subprocess.run(["bash", inst_sh], cwd=extracted_root, check=True)
                    else:
                        bin_dir = os.path.expanduser("~/.local/bin")
                        for f in ["zen_updater_gui.py", "update_zen.sh", "check_zen_update.sh", "zen_backup.tarignore"]:
                            src = os.path.join(extracted_root, f)
                            if os.path.isfile(src):
                                dst = os.path.join(bin_dir, f)
                                shutil.copy2(src, dst)
                                os.chmod(dst, 0o755)

            target_py = os.path.expanduser("~/.local/bin/zen_updater_gui.py")
            if os.path.isfile(target_py):
                comp_res = subprocess.run([sys.executable, "-m", "py_compile", target_py], capture_output=True, text=True)
                if comp_res.returncode != 0:
                    raise RuntimeError(f"Syntax validation failed: {comp_res.stderr}")

            self.finished.emit(True, f"Successfully updated Zen Updater to {self.target_version}!")
        except Exception as e:
            self.finished.emit(False, str(e))


class ZenUpdaterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Zen Browser Updater {APP_VERSION}")
        self.setMinimumSize(540, 560)
        self.resize(540, 691)

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
        self.timer_status = self.timer_mgr.get_status()

        self.check_worker = None
        self.process = None
        self.update_available = False

        self.app_check_worker = None
        self.app_apply_worker = None
        self.app_update_info = {}

        # Clear any pending desktop notification when updater is opened
        dismiss_zen_notification()

        self.setup_ui()

        # Automatically check for updates when opened
        QTimer.singleShot(150, self.start_check)

        # If user enabled auto-check for updater updates on startup, trigger background check
        if self.load_auto_check_app_setting():
            QTimer.singleShot(800, lambda: self.start_app_update_check(silent=True))

    def setup_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
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
            QScrollBar::track:vertical {
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

        # 1. Header with App Icon and Title
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

        # Header badge for app update (anchored to the right side of header, matching update green)
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

        # 2. Version Information Card (Side-by-Side 2-Column Layout)
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

        # Installed Column
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

        # Subtle Vertical Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet("border: none; border-left: 1px solid #30363d;")

        # Latest Column
        right_box = QVBoxLayout()
        right_box.setSpacing(2)
        lbl_lat_title = QLabel("LATEST AVAILABLE")
        lbl_lat_title.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; border: none; background: transparent;")
        self.lbl_lat_ver = QLabel("Checking online...")
        self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #58a6ff; border: none; background: transparent;")
        self.lbl_lat_date = QLabel("Checking online...")
        self.lbl_lat_date.setStyleSheet("color: #8b949e; font-size: 11px; border: none; background: transparent;")
        right_box.addWidget(lbl_lat_title)
        right_box.addWidget(self.lbl_lat_ver)
        right_box.addWidget(self.lbl_lat_date)

        card_layout.addLayout(left_box, 1)
        card_layout.addWidget(div)
        card_layout.addLayout(right_box, 1)
        main_layout.addWidget(card)

        # 3. Status Banner
        self.status_banner = QLabel("Checking for updates...")
        self.status_banner.setWordWrap(True)
        self.status_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_banner.setStyleSheet("""
            QLabel {
                padding: 8px 12px;
                border-radius: 6px;
                background-color: #2b3a4a;
                color: #8ac4ff;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #3c526a;
            }
        """)
        main_layout.addWidget(self.status_banner)
        self.status_banner.mousePressEvent = self.on_banner_clicked

        # 4. Backup Option Checkbox with (?) Info Helper
        backup_layout = QHBoxLayout()
        backup_layout.setSpacing(8)

        self.chk_backup = QCheckBox("Backup all profiles before updating or reinstalling")
        self.chk_backup.setChecked(True)
        self.chk_backup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_backup.setStyleSheet(get_checkbox_qss())
        self.btn_backup_help = QPushButton("?")
        self.btn_backup_help.setFixedSize(17, 17)
        self.btn_backup_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_backup_help.setStyleSheet("""
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
        """)
        self.btn_backup_help.clicked.connect(self.show_backup_info)

        backup_layout.addWidget(self.chk_backup)
        backup_layout.addWidget(self.btn_backup_help)
        backup_layout.addStretch()
        main_layout.addLayout(backup_layout)

        # 5. Action Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.btn_run = QPushButton("Run Update")
        self.btn_run.setMinimumHeight(36)
        self.btn_run.setEnabled(False)
        self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: rgba(46, 160, 67, 0.15);
                color: #a6f3a6;
                font-weight: bold;
                font-size: 12px;
                border: 1.5px solid #2ea043;
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
        """)
        self.btn_run.clicked.connect(self.run_update)

        self.btn_launch = QPushButton("Launch Zen")
        self.btn_launch.setMinimumHeight(36)
        self.btn_launch.clicked.connect(self.launch_zen)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setMinimumHeight(36)
        self.btn_refresh.clicked.connect(self.start_check)

        button_layout.addWidget(self.btn_run)
        button_layout.addWidget(self.btn_launch)
        button_layout.addStretch()
        button_layout.addWidget(self.btn_refresh)
        main_layout.addLayout(button_layout)

        # 6. Expandable Launch Profiles Section
        self.btn_toggle_profiles = QPushButton()
        self.btn_toggle_profiles.setObjectName("profileToggleBtn")
        self.btn_toggle_profiles.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_profiles.setStyleSheet("""
            QPushButton#profileToggleBtn {
                text-align: left;
                background-color: #1e2530;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #60a5fa;
                font-size: 12px;
                font-weight: bold;
                padding: 8px 12px;
            }
            QPushButton#profileToggleBtn:hover {
                background-color: #263140;
                border-color: #475569;
                color: #93c5fd;
            }
        """)
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
        self.btn_profile_help.setStyleSheet("""
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
        """)
        self.btn_profile_help.clicked.connect(self.show_profile_help)
        profile_header_layout.addWidget(self.btn_profile_help)

        # Migration badge button shown if Flatpak or Repo profiles / installs are detected
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
        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(14)
        grid_layout.setVerticalSpacing(6)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        grid_row = 0
        grid_col = 0
        for p in self.profiles:
            pname = p["name"]
            chk = QCheckBox(p["display_name"])
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            chk.setChecked(pname in self.selected_profiles)
            chk.toggled.connect(lambda checked, name=pname: self.on_profile_toggled(name, checked))
            self.profile_checkboxes[pname] = chk
            grid_layout.addWidget(chk, grid_row, grid_col)
            grid_col += 1
            if grid_col >= 2:
                grid_col = 0
                grid_row += 1
        profile_layout.addLayout(grid_layout)

        self.profiles_expanded = False
        self.profile_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.profile_frame.setVisible(False)  # Collapsed by default
        self.update_profiles_toggle_text()

        main_layout.addWidget(self.btn_toggle_profiles)
        main_layout.addWidget(self.profile_frame)

        # 7. Expandable Background Update Check Timer Section
        self.btn_toggle_timer = QPushButton()
        self.btn_toggle_timer.setObjectName("timerToggleBtn")
        self.btn_toggle_timer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_timer.setStyleSheet("""
            QPushButton#timerToggleBtn {
                text-align: left;
                background-color: #1e2530;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #60a5fa;
                font-size: 12px;
                font-weight: bold;
                padding: 8px 12px;
            }
            QPushButton#timerToggleBtn:hover {
                background-color: #263140;
                border-color: #475569;
                color: #93c5fd;
            }
        """)
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

        # Enable / Disable Checkbox
        self.chk_timer_enable = QCheckBox("Enable periodic background update checks")
        self.chk_timer_enable.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_timer_enable.setChecked(self.timer_status["active"] or self.timer_status["enabled"])
        self.chk_timer_enable.toggled.connect(self.on_timer_enable_toggled)
        timer_layout.addWidget(self.chk_timer_enable)

        # Controls Row (Interval + Test Button)
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)

        lbl_interval = QLabel("Check Interval:")
        lbl_interval.setStyleSheet("color: #c9d1d9; font-size: 12px; font-weight: bold;")
        controls_layout.addWidget(lbl_interval)

        self.combo_timer_interval = QComboBox()
        self.combo_timer_interval.addItem("Every 2 hours", "2h")
        self.combo_timer_interval.addItem("Every 4 hours", "4h")
        self.combo_timer_interval.addItem("Every 6 hours (Default)", "6h")
        self.combo_timer_interval.addItem("Every 12 hours", "12h")
        self.combo_timer_interval.addItem("Every 24 hours / Daily", "24h")

        cur_int = self.timer_status.get("interval", "6h")
        idx = self.combo_timer_interval.findData(cur_int)
        if idx >= 0:
            self.combo_timer_interval.setCurrentIndex(idx)
        else:
            self.combo_timer_interval.setCurrentIndex(2)

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
        """)
        self.btn_test_notification.clicked.connect(self.test_notification_now)
        controls_layout.addWidget(self.btn_test_notification)
        controls_layout.addStretch()
        timer_layout.addLayout(controls_layout)

        # Status row
        self.lbl_timer_status = QLabel()
        self.lbl_timer_status.setStyleSheet("font-size: 11px; color: #8b949e;")
        timer_layout.addWidget(self.lbl_timer_status)

        self.timer_expanded = False
        self.timer_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.timer_frame.setVisible(False)

        main_layout.addWidget(self.btn_toggle_timer)
        main_layout.addWidget(self.timer_frame)
        self.refresh_timer_status_label()

        # 8. Expandable Zen Updater Updates Section (Self-Updater)
        self.btn_toggle_app_update = QPushButton()
        self.btn_toggle_app_update.setObjectName("appUpdateToggleBtn")
        self.btn_toggle_app_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_app_update.setStyleSheet("""
            QPushButton#appUpdateToggleBtn {
                text-align: left;
                background-color: #1e2530;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #60a5fa;
                font-size: 12px;
                font-weight: bold;
                padding: 8px 12px;
            }
            QPushButton#appUpdateToggleBtn:hover {
                background-color: #263140;
                border-color: #475569;
                color: #93c5fd;
            }
        """)
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

        # Checkbox: Automatic startup check (off by default)
        self.chk_auto_check_app = QCheckBox("Check for updater updates automatically on startup")
        self.chk_auto_check_app.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_auto_check_app.setChecked(self.load_auto_check_app_setting())
        self.chk_auto_check_app.toggled.connect(self.on_auto_check_app_toggled)
        app_update_layout.addWidget(self.chk_auto_check_app)

        # Version Info Row
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
        self.lbl_app_lat_ver = QLabel("Not checked yet")
        self.lbl_app_lat_ver.setStyleSheet("font-size: 14px; font-weight: bold; color: #58a6ff; border: none; background: transparent;")
        v_lat_box.addWidget(lbl_l_title)
        v_lat_box.addWidget(self.lbl_app_lat_ver)

        ver_info_layout.addLayout(v_cur_box, 1)
        ver_info_layout.addLayout(v_lat_box, 1)
        app_update_layout.addLayout(ver_info_layout)

        # Action Buttons Row
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

        # Status text in card
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

        # 8. Console / Progress Output
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(80)
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

    def toggle_profiles_expanded(self):
        self.profiles_expanded = not self.profiles_expanded
        self.profile_frame.setVisible(self.profiles_expanded)
        if self.profiles_expanded:
            if self.timer_expanded:
                self.timer_expanded = False
                self.timer_frame.setVisible(False)
                self.update_timer_toggle_text()
            if getattr(self, "app_update_expanded", False):
                self.app_update_expanded = False
                self.app_update_frame.setVisible(False)
                self.update_app_update_toggle_text()
        self.update_profiles_toggle_text()

    def update_profiles_toggle_text(self):
        count = len(self.selected_profiles)
        arrow = "▼" if self.profiles_expanded else "▶"
        self.btn_toggle_profiles.setText(f"{arrow} Launch Profiles ({count} selected)")

    def on_profile_toggled(self, name, checked):
        if checked:
            self.selected_profiles.add(name)
        else:
            self.selected_profiles.discard(name)
        self.profile_mgr.save_selected_profiles(self.selected_profiles)
        self.update_profiles_toggle_text()

    def toggle_timer_expanded(self):
        self.timer_expanded = not self.timer_expanded
        self.timer_frame.setVisible(self.timer_expanded)
        if self.timer_expanded:
            if self.profiles_expanded:
                self.profiles_expanded = False
                self.profile_frame.setVisible(False)
                self.update_profiles_toggle_text()
            if getattr(self, "app_update_expanded", False):
                self.app_update_expanded = False
                self.app_update_frame.setVisible(False)
                self.update_app_update_toggle_text()
        self.update_timer_toggle_text()

    def update_timer_toggle_text(self):
        arrow = "▼" if self.timer_expanded else "▶"
        status_text = "Active" if self.timer_status["active"] else "Disabled"
        interval_text = self.timer_status.get("interval", "6h")
        self.btn_toggle_timer.setText(f"{arrow} Background Auto-Check ({status_text} — Every {interval_text})")

    def refresh_timer_status_label(self):
        self.timer_status = self.timer_mgr.get_status()
        if not self.timer_status["available"]:
            self.lbl_timer_status.setText("Systemd user services are not available on this system.")
            self.chk_timer_enable.setEnabled(False)
            self.combo_timer_interval.setEnabled(False)
            self.btn_test_notification.setEnabled(False)
            return

        if self.timer_status["active"]:
            next_txt = f" (Next check: in {self.timer_status['next_run']})" if self.timer_status["next_run"] != "Unknown" else ""
            self.lbl_timer_status.setText(f"Status: Active and running{next_txt}")
            self.lbl_timer_status.setStyleSheet("font-size: 11px; color: #7ee787; font-weight: bold;")
            self.combo_timer_interval.setEnabled(True)
        else:
            self.lbl_timer_status.setText("Status: Inactive (Periodic background checks disabled)")
            self.lbl_timer_status.setStyleSheet("font-size: 11px; color: #8b949e;")
            self.combo_timer_interval.setEnabled(False)

        self.update_timer_toggle_text()

    def on_timer_enable_toggled(self, checked):
        cur_int = self.combo_timer_interval.currentData() or "6h"
        success, msg = self.timer_mgr.set_timer(enabled=checked, interval=cur_int)
        self.append_log(f"\n[Background Timer] {msg}\n")
        self.refresh_timer_status_label()

    def on_timer_interval_changed(self, index):
        if not self.chk_timer_enable.isChecked():
            return
        cur_int = self.combo_timer_interval.itemData(index) or "6h"
        success, msg = self.timer_mgr.set_timer(enabled=True, interval=cur_int)
        self.append_log(f"\n[Background Timer] Updated interval to every {cur_int}.\n")
        self.refresh_timer_status_label()

    def test_notification_now(self):
        self.append_log("\n[Background Timer] Running check_zen_update.sh service now...\n")
        success, msg = self.timer_mgr.trigger_check_now()
        if success:
            self.append_log("✓ Background check initiated. If an update is available, a notification will appear.\n")
        else:
            self.append_log(f"Error triggering background check: {msg}\n")

    def load_auto_check_app_setting(self):
        settings = load_app_settings()
        return bool(settings.get("auto_check_app_updates", False))

    def on_auto_check_app_toggled(self, checked):
        save_app_setting("auto_check_app_updates", checked)
        status = "enabled" if checked else "disabled"
        self.append_log(f"\n[Zen Updater] Automatic update checks on startup {status}.\n")

    def toggle_app_update_expanded(self):
        self.app_update_expanded = not self.app_update_expanded
        self.app_update_frame.setVisible(self.app_update_expanded)
        if self.app_update_expanded:
            if self.profiles_expanded:
                self.profiles_expanded = False
                self.profile_frame.setVisible(False)
                self.update_profiles_toggle_text()
            if self.timer_expanded:
                self.timer_expanded = False
                self.timer_frame.setVisible(False)
                self.update_timer_toggle_text()
        self.update_app_update_toggle_text()

    def update_app_update_toggle_text(self):
        arrow = "▼" if self.app_update_expanded else "▶"
        has_upd = getattr(self, "app_update_info", {}).get("has_update", False)
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

    def on_app_update_check_finished(self, result, silent):
        self.btn_check_app_update.setEnabled(True)
        self.app_update_info = result

        if result.get("error"):
            if not silent:
                self.lbl_app_lat_ver.setText("Check failed")
                self.lbl_app_update_status.setText(f"Check failed: {result['error']}")
            return

        latest_ver = result["latest_version"]
        pub_date = result["release_date"]
        self.lbl_app_lat_ver.setText(f"{latest_ver} ({pub_date})")

        if result.get("has_update"):
            self.badge_app_update.setText(f"Update Available ({latest_ver})")
            self.badge_app_update.setVisible(True)
            self.btn_apply_app_update.setEnabled(True)
            self.lbl_app_update_status.setText(f"A new release ({latest_ver}) is available on GitHub Releases.")
            self.update_app_update_toggle_text()
        else:
            self.badge_app_update.setVisible(False)
            self.btn_apply_app_update.setEnabled(False)
            self.lbl_app_update_status.setText(f"Zen Updater is up to date ({APP_VERSION}).")
            self.update_app_update_toggle_text()

    def run_apply_app_update(self):
        target_ver = self.app_update_info.get("latest_version") or "v1.0.5"
        reply = QMessageBox.question(
            self,
            "Confirm Zen Updater Update",
            f"Do you want to update Zen Updater to release {target_ver}?\n\n"
            "This will download the official release files, update your installation, and restart the application.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
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
        self.btn_apply_app_update.setEnabled(True)
        self.btn_check_app_update.setEnabled(True)
        self.append_log(f"[Zen Updater Self-Update] {msg}\n")

        if success:
            QMessageBox.information(
                self,
                "Update Complete",
                f"{msg}\n\nThe application will now restart."
            )
            QApplication.quit()
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            QMessageBox.critical(
                self,
                "Update Failed",
                f"Failed to update Zen Updater:\n\n{msg}"
            )
            self.lbl_app_update_status.setText(f"Update failed: {msg}")

    def on_banner_clicked(self, event):
        if getattr(self, "update_available", False) and self.btn_run.isEnabled():
            self.run_update()

    def start_check(self):
        if self.check_worker and self.check_worker.isRunning():
            return

        self.btn_refresh.setEnabled(False)
        self.btn_run.setEnabled(False)
        self.status_banner.setCursor(Qt.CursorShape.ArrowCursor)
        self.status_banner.setToolTip("")
        self.status_banner.setText("Checking for updates...")
        self.status_banner.setStyleSheet("""
            QLabel {
                padding: 8px 12px;
                border-radius: 6px;
                background-color: #233549;
                color: #79b8ff;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #334d69;
            }
        """)
        self.lbl_lat_ver.setText("Checking online...")
        self.lbl_lat_date.setText("Checking online...")

        self.check_worker = CheckVersionWorker()
        self.check_worker.finished.connect(self.on_check_finished)
        self.check_worker.start()

    def on_check_finished(self, result):
        self.btn_refresh.setEnabled(True)

        self.lbl_cur_ver.setText(result["current_version"])
        self.lbl_cur_date.setText(f"Released: {result['current_date']}")
        self.lbl_lat_ver.setText(result["latest_version"])
        self.lbl_lat_date.setText(f"Released: {result['latest_date']}")

        if result["error"] and result["latest_version"] == "Unknown":
            self.status_banner.setText(f"Check failed: {result['error']}")
            self.status_banner.setStyleSheet("""
                QLabel {
                    padding: 10px;
                    border-radius: 6px;
                    background-color: #442727;
                    color: #ff8585;
                    font-weight: bold;
                    font-size: 13px;
                    border: 1px solid #663333;
                }
            """)
            self.btn_run.setEnabled(False)
            return

        self.update_available = result["update_available"]
        self.install_info = result.get("install_info") or INSTALL_INFO

        if self.install_info["type"] == "none":
            self.status_banner.setCursor(Qt.CursorShape.PointingHandCursor)
            self.status_banner.setToolTip("Click to download and install Zen Browser")
            self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #a6f3a6; border: none; background: transparent;")
            self.status_banner.setText(f"★  Zen Browser Not Installed  —  Click to Install {result['latest_version']}")
            self.status_banner.setStyleSheet("""
                QLabel {
                    padding: 10px;
                    border-radius: 6px;
                    background-color: #163b26;
                    color: #a6f3a6;
                    font-weight: bold;
                    font-size: 13px;
                    border: 1.5px solid #2ea043;
                }
                QLabel:hover {
                    background-color: #1d4d32;
                    border-color: #3fb950;
                    color: #ffffff;
                }
            """)
            self.btn_run.setText("Install Zen Browser")
            self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: rgba(46, 160, 67, 0.15);
                color: #a6f3a6;
                font-weight: bold;
                font-size: 12px;
                border: 1.5px solid #2ea043;
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
            """)
            self.btn_run.setEnabled(True)
        elif self.install_info["type"] == "flatpak":
            self.status_banner.setCursor(Qt.CursorShape.PointingHandCursor)
            self.status_banner.setToolTip("Flatpak installation detected")
            self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #79c0ff; border: none; background: transparent;")
            self.status_banner.setText(f"ℹ  Flatpak Installation Detected ({result['current_version']})  —  Updates managed via Flathub")
            self.status_banner.setStyleSheet("""
                QLabel {
                    padding: 10px;
                    border-radius: 6px;
                    background-color: #13233a;
                    color: #79c0ff;
                    font-weight: bold;
                    font-size: 13px;
                    border: 1px solid #214068;
                }
                QLabel:hover {
                    background-color: #1a3354;
                    border-color: #388bfd;
                }
            """)
            self.btn_run.setText("Install Portable")
            self.btn_run.setStyleSheet("""
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
            """)
            self.btn_run.setEnabled(True)
        elif self.install_info["type"] == "system":
            if result["update_available"]:
                self.status_banner.setCursor(Qt.CursorShape.PointingHandCursor)
                self.status_banner.setToolTip("System packages must be updated via your distribution package manager. Click if you wish to install a separate official portable release.")
                self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #d29922; border: none; background: transparent;")
                self.status_banner.setText(f"⚠  System Package Detected ({result['current_version']})  —  Update via Package Manager (or Install Portable)")
                self.status_banner.setStyleSheet("""
                    QLabel {
                        padding: 10px;
                        border-radius: 6px;
                        background-color: #3b2300;
                        color: #f2cc60;
                        font-weight: bold;
                        font-size: 13px;
                        border: 1px solid #bb8009;
                    }
                """)
                self.btn_run.setText("Install Portable")
                self.btn_run.setStyleSheet("""
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
                }
                """)
                self.btn_run.setEnabled(True)
            else:
                self.status_banner.setCursor(Qt.CursorShape.ArrowCursor)
                self.status_banner.setToolTip("")
                self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #58a6ff; border: none; background: transparent;")
                self.status_banner.setText(f"✓  System Package is up to date ({result['current_version']})")
                self.status_banner.setStyleSheet("""
                    QLabel {
                        padding: 10px;
                        border-radius: 6px;
                        background-color: #13233a;
                        color: #79c0ff;
                        font-weight: bold;
                        font-size: 13px;
                        border: 1px solid #214068;
                    }
                """)
                self.btn_run.setText("Reinstall Portable")
                self.btn_run.setStyleSheet("""
                QPushButton {
                    background-color: rgba(248, 81, 73, 0.12);
                    color: #ff7b72;
                    font-weight: bold;
                    font-size: 12px;
                    border: 1px solid #f85149;
                    border-radius: 5px;
                    padding: 6px 18px;
                }
                QPushButton:hover {
                    background-color: rgba(248, 81, 73, 0.22);
                    color: #ffa198;
                    border-color: #ff7b72;
                }
                """)
                self.btn_run.setEnabled(True)
        elif result["update_available"]:
            self.status_banner.setCursor(Qt.CursorShape.PointingHandCursor)
            self.status_banner.setToolTip("Click to install this update")
            self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #a6f3a6; border: none; background: transparent;")
            self.status_banner.setText(f"★  Update Available: Version {result['latest_version']} (Released {result['latest_date']})  —  Click to Install")
            self.status_banner.setStyleSheet("""
                QLabel {
                    padding: 10px;
                    border-radius: 6px;
                    background-color: #163b26;
                    color: #a6f3a6;
                    font-weight: bold;
                    font-size: 13px;
                    border: 1.5px solid #2ea043;
                }
                QLabel:hover {
                    background-color: #1d4d32;
                    border-color: #3fb950;
                    color: #ffffff;
                }
            """)
            self.btn_run.setText("Run Update")
            self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: rgba(46, 160, 67, 0.15);
                color: #a6f3a6;
                font-weight: bold;
                font-size: 12px;
                border: 1.5px solid #2ea043;
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
            """)
            self.btn_run.setEnabled(True)
        else:
            relinked = self.profile_mgr.sync_profile_binaries()
            if relinked:
                self.append_log(f"Auto-synced profile executables: {', '.join(relinked)}\n")
            self.status_banner.setCursor(Qt.CursorShape.ArrowCursor)
            self.status_banner.setToolTip("")
            self.lbl_lat_ver.setStyleSheet("font-size: 15px; font-weight: bold; color: #58a6ff; border: none; background: transparent;")
            self.status_banner.setText(f"✓  Zen Browser is up to date ({result['current_version']})")
            self.status_banner.setStyleSheet("""
                QLabel {
                    padding: 10px;
                    border-radius: 6px;
                    background-color: #13233a;
                    color: #79c0ff;
                    font-weight: bold;
                    font-size: 13px;
                    border: 1px solid #214068;
                }
            """)
            self.btn_run.setText("Reinstall")
            self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: rgba(248, 81, 73, 0.12);
                color: #ff7b72;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #f85149;
                border-radius: 5px;
                padding: 6px 18px;
            }
            QPushButton:hover {
                background-color: rgba(248, 81, 73, 0.22);
                color: #ffa198;
                border-color: #ff7b72;
            }
            QPushButton:disabled {
                background-color: #21262d;
                color: #6e7681;
                border-color: #30363d;
            }
            """)
            self.btn_run.setEnabled(True)

        # Show migration badge if Flatpak/System install is detected or external profiles exist
        has_ext_profiles = any(
            p.get("full_path") and not p.get("ini_file", "").endswith(".zen/profiles.ini")
            for p in self.profiles
        )
        is_alt_install = self.install_info.get("type") in ("flatpak", "system")
        if (is_alt_install or has_ext_profiles) and len(self.profiles) > 0:
            self.btn_migration_badge.setVisible(True)
        else:
            self.btn_migration_badge.setVisible(False)

    def run_update(self):
        if not os.path.isfile(UPDATE_SCRIPT):
            QMessageBox.critical(self, "Error", f"Update script not found at:\n{UPDATE_SCRIPT}")
            return

        dismiss_zen_notification()

        install_type = getattr(self, "install_info", {}).get("type", "tarball")
        target_dir = getattr(self, "install_info", {}).get("path", "")
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
                f"This will close any running Zen Browser windows and install the update into:\n{target_dir}\n\n"
                f"{backup_note}"
                "Do you want to proceed?"
            )

        reply = QMessageBox.question(
            self,
            "Confirm Installation / Update",
            confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_refresh.setEnabled(False)
        self.btn_run.setEnabled(False)
        self.btn_launch.setEnabled(False)

        action_label = "Installing" if install_type == "none" else "Updating"
        self.status_banner.setText(f"{action_label} Zen Browser... Please wait.")
        self.status_banner.setStyleSheet("""
            QLabel {
                padding: 10px;
                border-radius: 6px;
                background-color: #2b3a4a;
                color: #8ac4ff;
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #3c526a;
            }
        """)

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
        clean_text = re.sub(r'\x1b\[[0-9;]*[mK]', '', text)
        self.append_log(clean_text)

        # Milestone detection
        if "Closing all running Zen" in clean_text:
            self.progress_bar.setValue(10)
            self.progress_bar.setFormat("Closing browser instances...")
        elif "[Safety Backup] Creating snapshot" in clean_text:
            self.progress_bar.setValue(15)
            self.progress_bar.setFormat("Creating profile safety backup...")
        elif "Safety backup created" in clean_text:
            self.progress_bar.setValue(25)
            self.progress_bar.setFormat("Backup complete. Starting download...")
        elif "[1/3] Downloading" in clean_text:
            self.progress_bar.setValue(25)
            self.progress_bar.setFormat("Starting download...")
        elif "[2/3] Extracting" in clean_text:
            self.progress_bar.setValue(80)
            self.progress_bar.setFormat("Extracting files...")
        elif "[3/3] Re-linking" in clean_text:
            self.progress_bar.setValue(92)
            self.progress_bar.setFormat("Re-linking profile binaries...")
        elif "successfully updated" in clean_text:
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Update Complete (100%)")

        pct_matches = re.findall(r'(\d+(?:\.\d+)?)%', clean_text)
        if pct_matches:
            try:
                curl_pct = float(pct_matches[-1])
                if 0.0 <= curl_pct <= 100.0:
                    mapped = int(25 + (curl_pct * 0.53))
                    self.progress_bar.setValue(mapped)
                    self.progress_bar.setFormat(f"Downloading: {curl_pct:.1f}%")
            except ValueError:
                pass

    def append_log(self, text):
        self.log_view.moveCursor(self.log_view.textCursor().MoveOperation.End)
        self.log_view.insertPlainText(text)
        self.log_view.moveCursor(self.log_view.textCursor().MoveOperation.End)

    def on_process_finished(self, exit_code, exit_status):
        self.btn_refresh.setEnabled(True)
        self.btn_launch.setEnabled(True)

        if exit_code == 0:
            dismiss_zen_notification()
            relinked = self.profile_mgr.sync_profile_binaries()
            if relinked:
                self.append_log(f"Refreshed profile executables: {', '.join(relinked)}\n")
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Update Complete (100%)")
            self.status_banner.setText("Zen Browser updated successfully!")
            self.status_banner.setStyleSheet("""
                QLabel {
                    padding: 10px;
                    border-radius: 6px;
                    background-color: #1e3328;
                    color: #7ee787;
                    font-weight: bold;
                    font-size: 13px;
                    border: 1px solid #2a4c3a;
                }
            """)
            self.append_log("\n✓ Update complete! You can now launch your Zen profiles.\n")
            if len(self.profiles) > 1:
                self.append_log("Tip: To make a profile your permanent default, launch it, navigate to\n     about:profiles in the URL bar, and click 'Set as default profile'.\n")
            self.start_check()
        else:
            self.btn_run.setEnabled(True)
            self.status_banner.setText(f"Update failed with exit code {exit_code}")
            self.status_banner.setStyleSheet("""
                QLabel {
                    padding: 10px;
                    border-radius: 6px;
                    background-color: #442727;
                    color: #ff8585;
                    font-weight: bold;
                    font-size: 13px;
                    border: 1px solid #663333;
                }
            """)
            self.append_log(f"\nError: Update script exited with status code {exit_code}.\n")

    def show_backup_info(self):
        help_text = (
            "<b>Profile Safety Backup Details:</b><br><br>"
            "• <b>Location:</b> Stored in <code>~/.zen-backups/</code><br>"
            "• <b>Auto-Pruned:</b> Automatically retains only the <b>2 most recent</b> snapshots so backups never accumulate.<br>"
            "• <b>Coverage:</b> Backs up all profiles using multi-threaded <code>zstd</code> compression while excluding transient cache files."
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
        dismiss_zen_notification()
        relinked = self.profile_mgr.sync_profile_binaries()
        if relinked:
            self.append_log(f"Auto-synced profile executables: {', '.join(relinked)}\n")
        zen_bin = os.path.join(self.profile_mgr.install_dir, "zen")
        if not os.path.isfile(zen_bin):
            import shutil
            sys_zen = shutil.which("zen")
            if sys_zen:
                zen_bin = sys_zen
            else:
                QMessageBox.warning(self, "Warning", f"Zen binary not found at:\n{zen_bin}")
                return

        to_launch = []
        for p in self.profiles:
            if p["name"] in self.selected_profiles:
                to_launch.append(p)

        if not to_launch:
            QProcess.startDetached(zen_bin, ["--allow-downgrade"])
            return

        self.append_log(f"\nLaunching {len(to_launch)} profile(s)...\n")

        for idx, p in enumerate(to_launch):
            if p.get("exec_cmd"):
                clean = re.sub(r'%[uUfF]', '', p["exec_cmd"]).strip()
                parts = shlex.split(clean)
                prog = parts[0]
                args = parts[1:]
            elif p.get("full_path") and not p.get("ini_file", "").endswith(".zen/profiles.ini"):
                # Profile is stored in an alternate location (e.g. ~/.config/zen or Flatpak)
                prog = zen_bin
                args = ["--allow-downgrade", "--no-remote", "--profile", p["full_path"]]
            elif p["is_default"]:
                prog = zen_bin
                args = ["--allow-downgrade"]
            else:
                prog = zen_bin
                args = ["--allow-downgrade", "--no-remote", "-P", p["name"]]

            delay = idx * 250
            if delay == 0:
                QProcess.startDetached(prog, args)
                self.append_log(f" - Launched {p['display_name']}\n")
            else:
                QTimer.singleShot(
                    delay,
                    lambda prg=prog, arg=args, dname=p['display_name']: self._do_launch(prg, arg, dname)
                )

    def _do_launch(self, prog, args, display_name):
        QProcess.startDetached(prog, args)
        self.append_log(f" - Launched {display_name}\n")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Zen Browser Updater")
    window = ZenUpdaterWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
