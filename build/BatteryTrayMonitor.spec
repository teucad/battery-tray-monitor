# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['pystray._win32']
hiddenimports += collect_submodules('bleak')
hiddenimports += collect_submodules('winrt')


a = Analysis(
    ['C:/Users/yanki/teucad-automation-scripts/battery-tray-monitor/battery_tray.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/yanki/teucad-automation-scripts/battery-tray-monitor/battery_query.ps1', '.'), ('C:/Users/yanki/teucad-automation-scripts/battery-tray-monitor/build/monetization_config.json', '.')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BatteryTrayMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:/Users/yanki/teucad-automation-scripts/battery-tray-monitor/build/BatteryTrayMonitor.ico'],
)
