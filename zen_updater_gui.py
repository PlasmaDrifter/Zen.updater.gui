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

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QProcess, QTimer
from PyQt6.QtGui import QIcon, QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QTextEdit, QFrame, QSizePolicy,
    QMessageBox, QGridLayout, QCheckBox, QScrollArea, QComboBox
)

APP_VERSION = "v1.0.2"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_zen_icon():
    candidates = [
        os.path.join(SCRIPT_DIR, "assets", "icon.png"),
        os.path.join(SCRIPT_DIR, "assets", "zen-updater.png"),
        os.path.expanduser("~/.local/share/icons/zen-updater.png"),
        os.path.expanduser("~/Pictures/Avatar/Square_App_Icons/Zen-Browser/zen_browser_ice_steel_256.png"),
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


def find_app_ini():
    candidates = [
        os.path.expanduser("~/.tarball-installations/zen/application.ini"),
        "/opt/zen/application.ini",
        os.path.expanduser("~/.local/opt/zen/application.ini"),
        "/usr/lib/zen/application.ini",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return os.path.expanduser("~/.tarball-installations/zen/application.ini")


ICON_PATH = find_zen_icon()
UPDATE_SCRIPT = find_update_script()
APP_INI = find_app_ini()


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
        self.install_dir = os.path.dirname(APP_INI) if os.path.isfile(APP_INI) else os.path.expanduser("~/.tarball-installations/zen")

    def get_profiles(self):
        profiles = []
        if not os.path.isfile(self.ini_path):
            return profiles

        cp = configparser.ConfigParser()
        try:
            cp.read(self.ini_path)
        except Exception:
            return profiles

        default_path = None
        for sec in cp.sections():
            if sec.startswith("Install") and cp.has_option(sec, "Default"):
                default_path = cp.get(sec, "Default")
                break

        desktop_map = self._scan_desktop_files()

        for sec in cp.sections():
            if sec.startswith("Profile"):
                name = cp.get(sec, "Name", fallback="")
                path = cp.get(sec, "Path", fallback="")
                if default_path:
                    is_def = (path == default_path)
                else:
                    is_def = (cp.get(sec, "Default", fallback="0") == "1")

                desktop_info = desktop_map.get(name)
                if name == "zen-YT":
                    display_name = "YouTube (zen-YT)"
                elif name == "Qbittorrent":
                    display_name = "qBittorrent WebUI (Qbittorrent)"
                elif is_def:
                    display_name = "Main Browser"
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

                profiles.append({
                    "name": name,
                    "path": path,
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

        # Default profile must always be selected
        if default_profile_name:
            selected.add(default_profile_name)

        return selected

    def save_selected_profiles(self, selected_set):
        os.makedirs(self.config_dir, exist_ok=True)
        try:
            with open(self.settings_file, "w") as f:
                json.dump({"selected_profiles": sorted(list(selected_set))}, f, indent=2)
        except Exception as e:
            print("Error saving settings:", e)

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
        result = {
            "current_version": "Unknown",
            "current_date": "Unknown",
            "latest_version": "Unknown",
            "latest_date": "Unknown",
            "update_available": False,
            "error": None
        }

        # 1. Read Current Version and BuildID from application.ini
        build_id = None
        if os.path.isfile(APP_INI):
            try:
                with open(APP_INI, "r", encoding="utf-8") as f:
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


class ZenUpdaterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Zen Browser Updater {APP_VERSION}")
        self.setMinimumSize(540, 560)
        self.resize(580, 640)

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

        # Clear any pending desktop notification when updater is opened
        dismiss_zen_notification()

        self.setup_ui()

        # Automatically check for updates when opened
        QTimer.singleShot(150, self.start_check)

    def setup_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
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

        # 4. Backup Option Checkbox with (?) Info Helper
        backup_layout = QHBoxLayout()
        backup_layout.setSpacing(8)

        self.chk_backup = QCheckBox("Backup all profiles before updating")
        self.chk_backup.setChecked(True)
        self.chk_backup.setStyleSheet("""
            QCheckBox {
                font-size: 12px;
                color: #e6edf3;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #484f58;
                background-color: #0d1117;
            }
            QCheckBox::indicator:hover {
                border-color: #58a6ff;
            }
            QCheckBox::indicator:checked {
                background-color: #1f6feb;
                border-color: #388bfd;
            }
        """)

        btn_backup_help = QPushButton("?")
        btn_backup_help.setFixedSize(18, 18)
        btn_backup_help.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_backup_help.setToolTip(
            "<b>Profile Safety Backup Details:</b><br><br>"
            "• <b>Location:</b> Stored in <code>~/.zen-backups/</code><br>"
            "• <b>Auto-Pruned:</b> Automatically retains only the <b>2 most recent</b> snapshots so backups never accumulate.<br>"
            "• <b>Coverage:</b> Backs up all profiles using multi-threaded <code>zstd</code> compression while excluding transient cache files."
        )
        btn_backup_help.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                color: #8b949e;
                border: 1px solid #30363d;
                border-radius: 9px;
                font-size: 11px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #30363d;
                color: #58a6ff;
                border-color: #58a6ff;
            }
        """)
        btn_backup_help.clicked.connect(self.show_backup_info)

        backup_layout.addWidget(self.chk_backup)
        backup_layout.addWidget(btn_backup_help)
        backup_layout.addStretch()
        main_layout.addLayout(backup_layout)

        # Inline Expandable Backup Info Card (Crash-Proof)
        self.backup_info_frame = QFrame()
        self.backup_info_frame.setStyleSheet("""
            QFrame {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
        """)
        backup_info_layout = QVBoxLayout(self.backup_info_frame)
        backup_info_layout.setContentsMargins(12, 10, 12, 10)
        backup_info_layout.setSpacing(5)

        info_header = QLabel("PROFILE SAFETY BACKUP DETAILS")
        info_header.setStyleSheet("color: #58a6ff; font-size: 10px; font-weight: bold; border: none; background: transparent;")
        backup_info_layout.addWidget(info_header)

        info_b1 = QLabel("• <b>Storage Location:</b> <code>~/.zen-backups/</code>")
        info_b1.setStyleSheet("color: #c9d1d9; font-size: 11px; border: none; background: transparent;")
        backup_info_layout.addWidget(info_b1)

        info_b2 = QLabel("• <b>Auto-Pruned:</b> Automatically keeps only the <b>2 most recent</b> snapshots so backups never accumulate.")
        info_b2.setStyleSheet("color: #c9d1d9; font-size: 11px; border: none; background: transparent;")
        info_b2.setWordWrap(True)
        backup_info_layout.addWidget(info_b2)

        info_b3 = QLabel("• <b>Coverage:</b> Archives all profiles, settings, and tabs in <code>~/.zen</code> using multi-threaded <code>zstd</code> compression while excluding transient browser cache files.")
        info_b3.setStyleSheet("color: #c9d1d9; font-size: 11px; border: none; background: transparent;")
        info_b3.setWordWrap(True)
        backup_info_layout.addWidget(info_b3)

        self.backup_info_frame.setVisible(False)
        main_layout.addWidget(self.backup_info_frame)

        # 5. Action Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setMinimumHeight(36)
        self.btn_refresh.clicked.connect(self.start_check)

        self.btn_run = QPushButton("Run Update")
        self.btn_run.setMinimumHeight(36)
        self.btn_run.setEnabled(False)
        self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: #1e70bf;
                color: white;
                font-weight: bold;
                border-radius: 5px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: #2582dd;
            }
            QPushButton:disabled {
                background-color: #4a545e;
                color: #8e99a4;
            }
        """)
        self.btn_run.clicked.connect(self.run_update)

        self.btn_launch = QPushButton("Launch Zen")
        self.btn_launch.setMinimumHeight(36)
        self.btn_launch.clicked.connect(self.launch_zen)

        self.btn_close = QPushButton("Close")
        self.btn_close.setMinimumHeight(36)
        self.btn_close.clicked.connect(self.close)

        button_layout.addWidget(self.btn_refresh)
        button_layout.addWidget(self.btn_run)
        button_layout.addWidget(self.btn_launch)
        button_layout.addStretch()
        button_layout.addWidget(self.btn_close)
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
            QCheckBox {
                color: #e6edf3;
                font-size: 13px;
                spacing: 10px;
                padding: 2px 0px;
            }
            QCheckBox:disabled {
                color: #79c0ff;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #484f58;
                background-color: #0d1117;
            }
            QCheckBox::indicator:hover {
                border-color: #58a6ff;
            }
            QCheckBox::indicator:checked {
                background-color: #1f6feb;
                border-color: #388bfd;
            }
            QCheckBox::indicator:checked:disabled {
                background-color: #238636;
                border-color: #2ea043;
            }
        """)
        profile_layout = QVBoxLayout(self.profile_frame)
        profile_layout.setContentsMargins(16, 12, 16, 12)
        profile_layout.setSpacing(8)

        lbl_desc = QLabel("PROFILES TO OPEN WHEN CLICKING 'LAUNCH ZEN':")
        lbl_desc.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; letter-spacing: 0.6px; border: none; background: transparent; padding-bottom: 2px;")
        profile_layout.addWidget(lbl_desc)

        self.profile_checkboxes = {}
        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(14)
        grid_layout.setVerticalSpacing(6)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        grid_row = 0
        grid_col = 0
        for p in self.profiles:
            pname = p["name"]
            if p["is_default"]:
                chk = QCheckBox(f"{p['display_name']}  —  Default (Always Launched)")
                chk.setChecked(True)
                chk.setEnabled(False)
                chk.setStyleSheet("font-weight: bold; color: #58a6ff;")
                self.profile_checkboxes[pname] = chk
                profile_layout.addWidget(chk)
            else:
                chk = QCheckBox(p["display_name"])
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
            QCheckBox {
                color: #e6edf3;
                font-size: 13px;
                spacing: 10px;
                padding: 2px 0px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #484f58;
                background-color: #0d1117;
            }
            QCheckBox::indicator:hover {
                border-color: #58a6ff;
            }
            QCheckBox::indicator:checked {
                background-color: #1f6feb;
                border-color: #388bfd;
            }
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

        # 8. Real-Time Progress Bar
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

    def toggle_profiles_expanded(self):
        self.profiles_expanded = not self.profiles_expanded
        self.profile_frame.setVisible(self.profiles_expanded)
        self.update_profiles_toggle_text()

    def update_profiles_toggle_text(self):
        count = len(self.selected_profiles)
        arrow = "▼" if self.profiles_expanded else "▶"
        hint = "Hide profile options" if self.profiles_expanded else "Configure launch profiles"
        self.btn_toggle_profiles.setText(f"{arrow} Launch Profiles ({count} selected) — {hint}")

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
        self.update_timer_toggle_text()

    def update_timer_toggle_text(self):
        arrow = "▼" if self.timer_expanded else "▶"
        status_text = "Active" if self.timer_status["active"] else "Disabled"
        interval_text = self.timer_status.get("interval", "6h")
        hint = "Hide settings" if self.timer_expanded else "Configure auto-check timer"
        self.btn_toggle_timer.setText(f"{arrow} Background Auto-Check ({status_text} — Every {interval_text}) — {hint}")

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

    def start_check(self):
        if self.check_worker and self.check_worker.isRunning():
            return

        self.btn_refresh.setEnabled(False)
        self.btn_run.setEnabled(False)
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

        if result["update_available"]:
            self.status_banner.setText(f"Update Available: Version {result['latest_version']} (Released {result['latest_date']})")
            self.status_banner.setStyleSheet("""
                QLabel {
                    padding: 10px;
                    border-radius: 6px;
                    background-color: #1d3b2b;
                    color: #56d364;
                    font-weight: bold;
                    font-size: 13px;
                    border: 1px solid #2e5e44;
                }
            """)
            self.btn_run.setText("Run Update")
            self.btn_run.setEnabled(True)
        else:
            relinked = self.profile_mgr.sync_profile_binaries()
            if relinked:
                self.append_log(f"Auto-synced profile executables: {', '.join(relinked)}\n")
            self.status_banner.setText(f"Zen Browser is up to date ({result['current_version']})")
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
            self.btn_run.setText("Reinstall / Refresh")
            self.btn_run.setEnabled(True)

    def run_update(self):
        if not os.path.isfile(UPDATE_SCRIPT):
            QMessageBox.critical(self, "Error", f"Update script not found at:\n{UPDATE_SCRIPT}")
            return

        dismiss_zen_notification()

        backup_note = "A safety backup of all your profiles will be created before updating.\n\n" if self.chk_backup.isChecked() else ""
        if self.btn_run.text() == "Reinstall / Refresh":
            confirm_msg = (
                f"Zen Browser is already on the latest version.\n\n"
                f"This will re-install core files, re-link isolated profile binaries, and apply policy safeguards.\n\n"
                f"{backup_note}"
                "Do you want to proceed?"
            )
        else:
            confirm_msg = (
                f"This will close any running Zen Browser windows and install the update.\n\n"
                f"{backup_note}"
                "Do you want to proceed?"
            )
        reply = QMessageBox.question(
            self,
            "Confirm Update",
            confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_refresh.setEnabled(False)
        self.btn_run.setEnabled(False)
        self.btn_launch.setEnabled(False)

        self.status_banner.setText("Updating Zen Browser... Please wait.")
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
        self.progress_bar.setFormat("Initializing update...")
        self.log_view.clear()
        self.append_log("Starting update process...\n")

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)
        self.process.finished.connect(self.on_process_finished)

        args = [UPDATE_SCRIPT, "--force"]
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
        self.backup_info_expanded = not getattr(self, "backup_info_expanded", False)
        self.backup_info_frame.setVisible(self.backup_info_expanded)

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
            if p["is_default"] or (p["name"] in self.selected_profiles):
                to_launch.append(p)

        if not to_launch:
            QProcess.startDetached(zen_bin, [])
            return

        self.append_log(f"\nLaunching {len(to_launch)} profile(s)...\n")

        for idx, p in enumerate(to_launch):
            if p["is_default"]:
                prog = zen_bin
                args = []
            elif p.get("exec_cmd"):
                clean = re.sub(r'%[uUfF]', '', p["exec_cmd"]).strip()
                parts = shlex.split(clean)
                prog = parts[0]
                args = parts[1:]
            else:
                prog = zen_bin
                args = ["--no-remote", "-P", p["name"]]

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
