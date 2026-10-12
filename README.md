## battery-tray-monitor

A system tray app that shows battery levels for your currently connected devices — Bluetooth/BLE mice, keyboards, headsets, Logitech wireless receivers, and AirPods (including AirPods Pro and Max). Click the tray icon for a popup listing every device's battery %, with charging status and low-battery coloring. Devices can be dragged into your preferred order via the popup, which then also drives what the tray tooltip shows.

Data comes from four sources, since no single Windows API covers everything:

| Source | Covers |
|---|---|
| `battery_query.ps1` — BLE Battery Service (`DEVPKEY_Bluetooth_Battery`) | BLE mice, keyboards, headsets — same data Settings > Bluetooth & devices uses |
| `battery_query.ps1` — inbox HID Battery Strength driver | USB dongle-based wireless mice/keyboards |
| `logitech_hidpp.py` — Logitech HID++ 2.0 protocol | Lightspeed/Bolt/Unifying receivers and direct-USB Logitech mice |
| `airpods_ble.py` — passive BLE advertisement scanning | AirPods, AirPods Pro, AirPods Max (Windows exposes no PnP/WMI property for these) |

Classic-Bluetooth-only HID devices using a vendor's proprietary protocol (e.g. a Logitech K380 over BT Classic) aren't visible to any Windows app — that's a platform limitation.

### Standalone exe

`BatteryTrayMonitor.exe` is a single file that runs without Python installed. Every push that touches `battery-tray-monitor/` builds it on GitHub Actions. Download it from the **BatteryTrayMonitor** artifact of the latest [battery-tray-monitor exe](https://github.com/teucad/teucad-automation-scripts/actions/workflows/battery-tray-monitor.yml) workflow run.

To build it yourself on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File battery-tray-monitor\Build-Exe.ps1
```

This writes `battery-tray-monitor\dist\BatteryTrayMonitor.exe`. The exe keeps its settings and license in `%APPDATA%\BatteryTrayMonitor`. To start it at logon, put a shortcut to it in `shell:startup`.

### Ads & "Remove ads"

The popup shows a small rotating text ad. Users can remove it with a yearly subscription ($5/year) or a one-time lifetime purchase ($15), through **Remove ads** in the popup or the tray menu. Payments go through RevenueCat, with Paddle as the checkout, which works for a seller based in Turkey. See [`battery-tray-monitor/MONETIZATION_SETUP.md`](battery-tray-monitor/MONETIZATION_SETUP.md) for the account setup, pricing caveats and how to test.

### Setup (from source)

No manual setup needed — both entry points below install Python (via `winget`, if it's missing) and create `.venv` with the pip requirements automatically via `Ensure-Env.ps1`.

To start it manually without a console window (e.g. via a desktop/Start Menu shortcut), double-click `battery-tray-monitor\Start-BatteryTray.vbs` — it ensures the environment is set up, then launches the app via `pythonw.exe`.

To run it directly instead (useful for testing — console stays open, and lets you see install/setup output the first time):

```powershell
powershell -ExecutionPolicy Bypass -File battery-tray-monitor\Ensure-Env.ps1
.venv\Scripts\python battery-tray-monitor\battery_tray.py
```

### Autostart at logon

```powershell
powershell -ExecutionPolicy Bypass -File battery-tray-monitor\Install-BatteryTrayAutostart.ps1
```

Ensures Python/the venv/requirements are installed, then registers a scheduled task that launches the app hidden (via `pythonw.exe`, no console window) at every logon, and starts it immediately. To remove it:

```powershell
powershell -ExecutionPolicy Bypass -File battery-tray-monitor\Uninstall-BatteryTrayAutostart.ps1
```

### Files

- `battery_tray.py` — tray icon, popup UI, refresh loop, settings persistence
- `monetization.py` / `monetization_config.json` — ad rotation and the RevenueCat "remove ads" entitlement check; config holds the public API key, purchase links, price labels and house ads
- `ads_ui.py` — the ad banner and the "Remove ads" purchase dialog
- `app_paths.py` — resource/data locations for running from source vs. as the exe
- `Build-Exe.ps1` / `requirements-build.txt` — builds the standalone exe with PyInstaller
- `MONETIZATION_SETUP.md` — Paddle + RevenueCat setup guide
- `tests/` — unit tests (`python -m unittest discover -s tests`, run from `battery-tray-monitor`)
- `airpods_ble.py` — AirPods/AirPods Pro/Max battery via BLE advertisement scanning
- `logitech_hidpp.py` — Logitech receiver/mouse battery via HID++
- `battery_query.ps1` — BLE Battery Service + generic HID Battery Strength queries
- `settings.json` — persisted refresh interval and device display order (created/updated automatically; the exe uses `%APPDATA%\BatteryTrayMonitor\settings.json`)
- `Ensure-Env.ps1` — installs Python (via `winget`, if missing), creates `.venv`, and installs `requirements.txt`; used by both the installer and the manual start scripts
- `Start-BatteryTray.ps1` / `Start-BatteryTray.vbs` — manual entry point that ensures the environment, then starts the app with no console window

---
