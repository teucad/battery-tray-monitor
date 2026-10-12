"""Windows "start at login" toggle, backed by the current user's registry
Run key (HKEY_CURRENT_USER) so it needs no admin rights and only applies to
this user - matches how the tray app itself runs per-user."""

import sys
import winreg
from pathlib import Path

import app_paths

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "BatteryTrayMonitor"


def _command():
    if app_paths.FROZEN:
        return f'"{sys.executable}"'
    # Running from source: prefer pythonw.exe (no console window) next to
    # whichever interpreter is currently running this script.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    script = app_paths.RESOURCE_DIR / "battery_tray.py"
    return f'"{interpreter}" "{script}"'


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False


def set_enabled(enabled):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except OSError:
                pass
