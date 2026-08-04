# PyInstaller spec — Smooth Client Launcher
# Goal: onefile .exe under 50MB. PyQt6 bundles a LOT of modules we never use
# (Qt3D, QtBluetooth, QtMultimedia, QtSql, QtQml/Quick, QtPdf, QtDesigner,
# QtHelp, QtNfc, QtPositioning, QtSensors, QtTest, QtWebEngine...). Excluding
# them + UPX is what gets this under the size cap.

block_cipher = None

EXCLUDE_MODULES = [
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngine",
    "PyQt6.QtMultimedia", "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuickWidgets",
    "PyQt6.QtSql", "PyQt6.QtTest", "PyQt6.QtDesigner", "PyQt6.QtHelp",
    "PyQt6.QtBluetooth", "PyQt6.QtNfc", "PyQt6.QtPositioning",
    "PyQt6.QtSensors", "PyQt6.QtPdf", "PyQt6.QtPdfWidgets",
    "PyQt6.Qt3DCore", "PyQt6.Qt3DRender", "PyQt6.Qt3DInput",
    "PyQt6.Qt3DLogic", "PyQt6.Qt3DAnimation", "PyQt6.Qt3DExtras",
    "PyQt6.QtRemoteObjects", "PyQt6.QtSpatialAudio", "PyQt6.QtSvgWidgets",
    "PyQt6.QtBluetooth", "PyQt6.QtSerialPort",
    "tkinter", "unittest", "pydoc_data", "test",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("smooth_launcher/icon.ico", "smooth_launcher"),
        ("smooth_launcher/icon.png", "smooth_launcher"),
    ],
    hiddenimports=[],
    hookspath=[],
    excludes=EXCLUDE_MODULES,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SmoothClientLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,          # strip=True breaks on Windows, skip it there
    upx=True,             # UPX compression — needs upx on PATH in CI
    upx_exclude=[
        "vcruntime140.dll", "python3*.dll",  # UPX-compressing these can crash
    ],
    runtime_tmpdir=None,
    console=False,        # windowed app, no terminal flash
    icon="smooth_launcher/icon.ico",
    onefile=True,
)
