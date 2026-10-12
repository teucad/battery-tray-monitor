"""Where the app reads bundled resources from and writes user data to.

Running from source, both are this folder (same as before the standalone
build existed). Running as the PyInstaller one-file exe, bundled resources
(battery_query.ps1, monetization_config.json) are unpacked to a temporary
sys._MEIPASS folder that is deleted on exit, so user data (settings.json,
license.json) goes to %APPDATA%\\BatteryTrayMonitor instead - next to the
exe would also break when the exe lives somewhere read-only like
Program Files.
"""

import os
import sys
from pathlib import Path

APP_NAME = "BatteryTrayMonitor"

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    _appdata = os.environ.get("APPDATA")
    DATA_DIR = (Path(_appdata) if _appdata else Path.home()) / APP_NAME
else:
    RESOURCE_DIR = Path(__file__).resolve().parent
    DATA_DIR = RESOURCE_DIR


def data_path(name):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return DATA_DIR / name
