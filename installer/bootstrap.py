"""Fishbot one-shot bootstrap installer.

Builds (via PyInstaller --onefile) into a small standalone .exe that, on
first run, downloads everything needed to run fishbot and launches the GUI:

  1. Python 3.12 embeddable distribution -> %LOCALAPPDATA%\\Fishbot\\python
  2. pip (via get-pip.py)
  3. Tesseract OCR (UB-Mannheim build) -> %LOCALAPPDATA%\\Fishbot\\app\\vendor\\tesseract
  4. Fishbot source (GitHub zip)        -> %LOCALAPPDATA%\\Fishbot\\app
  5. pip install -e <app>               (pulls runtime deps)
  6. Start Menu shortcut + launches GUI

Idempotent: re-running skips already-installed components and re-launches
the GUI.

No admin / UAC required. Per-user install only.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.request
import zipfile
from pathlib import Path
from tkinter import StringVar, Tk, ttk

# ---------------------------------------------------------------------------
# Build-time configuration. EDIT FISHBOT_SOURCE_URL before building the .exe.
# ---------------------------------------------------------------------------

PYTHON_VERSION = "3.12.7"
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}"
    f"/python-{PYTHON_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

TESSERACT_VERSION = "5.4.0.20240606"
TESSERACT_URL = (
    f"https://github.com/UB-Mannheim/tesseract/releases/download"
    f"/v{TESSERACT_VERSION}/tesseract-ocr-w64-setup-{TESSERACT_VERSION}.exe"
)

# Public ZIP archive of the fishbot-windows source tree. The default points at
# the GitHub "Download ZIP" URL; replace YOUR-USER (or pass --source-url) before
# distributing the bootstrapper.
FISHBOT_SOURCE_URL = os.environ.get(
    "FISHBOT_SOURCE_URL",
    "https://github.com/SilasD12/fishbot-windows/archive/refs/tags/v1.0.0.zip",
)

CREATE_NO_WINDOW = 0x08000000

# ---------------------------------------------------------------------------
# Install layout
# ---------------------------------------------------------------------------

INSTALL_ROOT = Path(os.environ["LOCALAPPDATA"]) / "Fishbot"
PY_DIR = INSTALL_ROOT / "python"
PY_EXE = PY_DIR / "python.exe"
APP_DIR = INSTALL_ROOT / "app"
TESS_DIR = APP_DIR / "vendor" / "tesseract"
LAUNCHER = INSTALL_ROOT / "Fishbot.cmd"

START_MENU = (
    Path(os.environ["APPDATA"])
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
)


# ---------------------------------------------------------------------------
# Small Tk progress UI
# ---------------------------------------------------------------------------


class ProgressUI:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Fishbot — Setup")
        self.root.geometry("520x150")
        self.root.resizable(False, False)
        self.status = StringVar(value="Starting…")
        ttk.Label(
            self.root,
            textvariable=self.status,
            padding=14,
            wraplength=480,
            justify="left",
        ).pack(fill="x")
        self.bar = ttk.Progressbar(self.root, mode="indeterminate", length=480)
        self.bar.pack(padx=20, pady=8)
        self.bar.start(12)

    def set(self, text: str) -> None:
        self.root.after(0, self.status.set, text)

    def close(self) -> None:
        self.bar.stop()
        self.root.destroy()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "fishbot-bootstrap"})
    with urllib.request.urlopen(req) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, creationflags=CREATE_NO_WINDOW)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def install_python(ui: ProgressUI, work: Path) -> None:
    if PY_EXE.exists():
        return
    ui.set(f"Downloading Python {PYTHON_VERSION}…")
    zip_path = work / "python-embed.zip"
    _download(PYTHON_EMBED_URL, zip_path)
    ui.set("Extracting Python…")
    PY_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(PY_DIR)
    # The embeddable distribution ships with `import site` commented out in
    # python<ver>._pth; pip needs site enabled to find Lib/site-packages.
    pth_files = list(PY_DIR.glob("python*._pth"))
    if not pth_files:
        raise RuntimeError("python._pth not found in embeddable distribution")
    pth = pth_files[0]
    pth.write_text(pth.read_text().replace("#import site", "import site"))


def install_pip(ui: ProgressUI, work: Path) -> None:
    if (PY_DIR / "Scripts" / "pip.exe").exists():
        return
    ui.set("Installing pip…")
    get_pip = work / "get-pip.py"
    _download(GET_PIP_URL, get_pip)
    _run([str(PY_EXE), str(get_pip), "--no-warn-script-location"])


def install_fishbot_source(ui: ProgressUI, work: Path) -> None:
    if (APP_DIR / "pyproject.toml").exists():
        return
    ui.set("Downloading Fishbot source…")
    src_zip = work / "fishbot.zip"
    _download(FISHBOT_SOURCE_URL, src_zip)
    ui.set("Extracting Fishbot…")
    extract_to = work / "src"
    extract_to.mkdir()
    with zipfile.ZipFile(src_zip) as z:
        z.extractall(extract_to)
    # GitHub archive zips wrap everything in <repo>-<ref>/.
    children = [p for p in extract_to.iterdir() if p.is_dir()]
    if len(children) != 1:
        raise RuntimeError(
            f"Unexpected archive layout: {[p.name for p in children]}"
        )
    APP_DIR.mkdir(parents=True, exist_ok=True)
    for item in children[0].iterdir():
        shutil.move(str(item), str(APP_DIR / item.name))


def install_python_deps(ui: ProgressUI) -> None:
    # Marker file: if present we've completed a successful pip install.
    marker = INSTALL_ROOT / ".deps-installed"
    if marker.exists():
        return
    ui.set(
        "Installing Python dependencies (PyQt6, OpenCV, NumPy… a few minutes)"
    )
    _run([
        str(PY_EXE),
        "-m",
        "pip",
        "install",
        "--no-warn-script-location",
        "-e",
        str(APP_DIR),
    ])
    marker.write_text("ok")


def install_tesseract(ui: ProgressUI, work: Path) -> None:
    if (TESS_DIR / "tesseract.exe").exists():
        return
    ui.set(f"Downloading Tesseract {TESSERACT_VERSION}…")
    setup_exe = work / "tesseract-setup.exe"
    _download(TESSERACT_URL, setup_exe)
    ui.set("Installing Tesseract…")
    TESS_DIR.mkdir(parents=True, exist_ok=True)
    _run([
        str(setup_exe),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/NOICONS",
        f"/DIR={TESS_DIR}",
    ])


def write_launcher() -> None:
    LAUNCHER.write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "PATH={TESS_DIR};%PATH%"\r\n'
        f'set "TESSDATA_PREFIX={TESS_DIR}"\r\n'
        f'start "" "{PY_EXE}" -m fishbot.gui %*\r\n',
        encoding="ascii",
    )


def make_start_menu_shortcut() -> None:
    START_MENU.mkdir(parents=True, exist_ok=True)
    lnk = START_MENU / "Fishbot.lnk"
    if lnk.exists():
        return
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
        f"'{lnk}'); "
        f"$s.TargetPath = '{LAUNCHER}'; "
        f"$s.WorkingDirectory = '{INSTALL_ROOT}'; "
        "$s.WindowStyle = 7; "
        "$s.Save()"
    )
    _run(["powershell", "-NoProfile", "-Command", ps])


def launch_gui() -> None:
    subprocess.Popen(
        ["cmd", "/c", str(LAUNCHER)],
        creationflags=0x00000008 | 0x00000200,  # DETACHED | NEW_PROCESS_GROUP
        cwd=str(INSTALL_ROOT),
        close_fds=True,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def install(ui: ProgressUI) -> None:
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fishbot-bootstrap-") as tmp:
        work = Path(tmp)
        install_python(ui, work)
        install_pip(ui, work)
        install_fishbot_source(ui, work)
        install_tesseract(ui, work)
        install_python_deps(ui)
    write_launcher()
    make_start_menu_shortcut()
    ui.set("Launching Fishbot…")
    launch_gui()


def main() -> int:
    if "YOUR-USER" in FISHBOT_SOURCE_URL:
        ctypes.windll.user32.MessageBoxW(
            0,
            "This bootstrapper was built without a real source URL. "
            "Set FISHBOT_SOURCE_URL in installer/bootstrap.py before "
            "building.",
            "Fishbot — Setup",
            0x10,
        )
        return 2

    ui = ProgressUI()
    err: list[BaseException] = []

    def worker() -> None:
        try:
            install(ui)
        except BaseException as e:  # noqa: BLE001
            err.append(e)
        finally:
            ui.root.after(500, ui.close)

    threading.Thread(target=worker, daemon=True).start()
    ui.root.mainloop()

    if err:
        msg = "".join(
            traceback.format_exception(type(err[0]), err[0], err[0].__traceback__)
        )
        ctypes.windll.user32.MessageBoxW(0, msg, "Fishbot — Setup failed", 0x10)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
