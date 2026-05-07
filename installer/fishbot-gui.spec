# PyInstaller spec for the fishbot GUI (windowed app — no console).
#
# Build via:  pyinstaller installer/fishbot-gui.spec --noconfirm
# Output:     dist/fishbot-gui/fishbot-gui.exe (+ supporting files)

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden = []
hidden += collect_submodules("fishbot")
hidden += collect_submodules("PyQt6")

datas = [
    ("config.toml", "."),
]

a = Analysis(
    ["src/fishbot/gui.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="fishbot-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="fishbot-gui",
)
