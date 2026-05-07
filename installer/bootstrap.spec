# PyInstaller spec for the fishbot one-shot bootstrap installer.
#
# Build via:  pyinstaller installer/bootstrap.spec --noconfirm
# Output:     dist/fishbot-setup.exe   (single-file, windowed)
#
# Invoked from the repo root (build-bootstrap.ps1 cd's there first).

block_cipher = None

a = Analysis(
    ["installer/bootstrap.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Bootstrap only uses urllib + tkinter + zipfile + subprocess; trim
        # heavy stdlib pieces PyInstaller would otherwise pull in.
        "numpy",
        "PIL",
        "pytest",
        "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
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
    name="fishbot-setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
