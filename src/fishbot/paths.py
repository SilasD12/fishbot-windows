"""Windows-conventional path resolution for fishbot.

Three different "homes" are kept distinct so the app behaves like a normal
Windows program:

* install_dir       — read-only program files (PyInstaller exe folder, or
                      the repo root in dev mode).
* user_config_dir   — %APPDATA%\\Fishbot, where the editable config.toml
                      lives so the user's settings survive reinstall.
* user_data_dir     — %LOCALAPPDATA%\\Fishbot, for logs and debug frames.

This module deliberately does not write anything at import time; callers
that need a directory should call ensure_user_dirs() once at startup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Fishbot"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    """Folder containing the running executable (frozen) or the repo root (dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _appdata_root() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata)
    # Sensible fallback for non-Windows dev machines.
    return Path.home() / ".config"


def _localappdata_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local)
    return Path.home() / ".local" / "share"


def user_config_dir() -> Path:
    return _appdata_root() / APP_NAME


def user_config_path() -> Path:
    return user_config_dir() / "config.toml"


def user_data_dir() -> Path:
    return _localappdata_root() / APP_NAME


def debug_frames_dir() -> Path:
    return user_data_dir() / "debug_frames"


def bundled_config_path() -> Path:
    return install_dir() / "config.toml"


def _tesseract_search_roots() -> list[Path]:
    """Folders to search for the bundled Tesseract.

    The installer puts vendor/ next to the GUI (the user-facing top-level
    install dir), but the CLI exe lives one level deeper. We therefore search
    install_dir() AND its parent so both processes resolve to the same copy.
    """
    me = install_dir()
    roots = [me]
    if me.parent != me:
        roots.append(me.parent)
    return roots


def tesseract_path() -> Path:
    """Path to the bundled Tesseract executable.

    Returns the first match across the search roots; if none exist, returns
    the canonical (preferred) path so callers can show it in error messages.
    """
    name = "tesseract.exe" if os.name == "nt" else "tesseract"
    for root in _tesseract_search_roots():
        candidate = root / "vendor" / "tesseract" / name
        if candidate.exists():
            return candidate
    return install_dir() / "vendor" / "tesseract" / name


def tessdata_dir() -> Path:
    for root in _tesseract_search_roots():
        candidate = root / "vendor" / "tesseract" / "tessdata"
        if candidate.exists():
            return candidate
    return install_dir() / "vendor" / "tesseract" / "tessdata"


def ensure_user_dirs() -> None:
    user_config_dir().mkdir(parents=True, exist_ok=True)
    user_data_dir().mkdir(parents=True, exist_ok=True)


def ensure_user_config() -> Path:
    """If %APPDATA%\\Fishbot\\config.toml does not exist, seed it from the bundled
    default. Returns the resolved user-config path."""
    user = user_config_path()
    if user.exists():
        return user
    bundled = bundled_config_path()
    if not bundled.exists():
        return user
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_bytes(bundled.read_bytes())
    return user
