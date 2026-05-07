# PyInstaller spec for the fishbot CLI (console app).
#
# Build via:  pyinstaller installer/fishbot.spec --noconfirm
# Output:     dist/fishbot/fishbot.exe (+ supporting files)
#
# This spec is invoked from the repo root (build.ps1 cd's there first).

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden = []
hidden += collect_submodules("fishbot")

datas = [
    ("config.toml", "."),
    # Tesseract is copied next to the exe by build.ps1 after PyInstaller runs;
    # we don't include it here so the spec works even if vendor/ is empty
    # during dev iteration.
]

a = Analysis(
    ["src/fishbot/main.py"],
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
    name="fishbot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
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
    name="fishbot",
)
