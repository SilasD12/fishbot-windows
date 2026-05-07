"""Find the Roblox game window and return its absolute screen rect.

Strategy: enumerate every visible top-level window via Win32, look up its
owning process via psutil, and pick the first window whose process image
name matches the configured value. Matching by process name (rather than
window title) survives Roblox's title-bar text changes between updates.

Only used on Windows. The pywin32/psutil imports are guarded so the module
can be imported on a Linux dev machine for syntax checks.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowRect:
    x: int
    y: int
    w: int
    h: int

    def __iter__(self):
        yield from (self.x, self.y, self.w, self.h)


class WindowNotFound(RuntimeError):
    pass


def _ensure_windows() -> None:
    if sys.platform != "win32":
        raise WindowNotFound(
            "fishbot.window only works on Windows; running under "
            f"sys.platform={sys.platform!r}."
        )


def _matching_pids(process_name: str) -> set[int]:
    import psutil

    target = process_name.lower()
    pids: set[int] = set()
    for proc in psutil.process_iter(["pid", "name"]):
        name = proc.info.get("name") or ""
        if name.lower() == target:
            pids.add(proc.info["pid"])
    return pids


def find_window(process_name: str = "RobloxPlayerBeta.exe") -> WindowRect:
    """Return the rect of the first visible top-level window for `process_name`.

    Coordinates are absolute screen pixels (the same coordinate space mss
    consumes), so the runtime can pass them straight to capture_rect().
    """
    _ensure_windows()
    import win32gui
    import win32process

    pids = _matching_pids(process_name)
    if not pids:
        raise WindowNotFound(
            f"No running process named {process_name!r}. "
            "Is the game open?"
        )

    found: list[WindowRect] = []

    def cb(hwnd: int, _ctx) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        # Skip zero-sized / minimised windows.
        try:
            l, t, r, b = win32gui.GetWindowRect(hwnd)
        except Exception:  # noqa: BLE001
            return True
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:  # noqa: BLE001
            return True
        if pid in pids:
            found.append(WindowRect(l, t, w, h))
        return True

    win32gui.EnumWindows(cb, None)

    if not found:
        raise WindowNotFound(
            f"Process {process_name!r} is running but has no visible window."
        )

    # Pick the largest window — Roblox's main game window dwarfs splash/popups.
    found.sort(key=lambda r: r.w * r.h, reverse=True)
    return found[0]


def list_windows() -> list[tuple[str, str, WindowRect]]:
    """Debug helper: list every visible top-level (process_name, title, rect)."""
    _ensure_windows()
    import psutil
    import win32gui
    import win32process

    pid_to_name: dict[int, str] = {}
    for proc in psutil.process_iter(["pid", "name"]):
        pid_to_name[proc.info["pid"]] = proc.info.get("name") or ""

    out: list[tuple[str, str, WindowRect]] = []

    def cb(hwnd: int, _ctx) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            title = win32gui.GetWindowText(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:  # noqa: BLE001
            return True
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            return True
        out.append((pid_to_name.get(pid, ""), title, WindowRect(l, t, w, h)))
        return True

    win32gui.EnumWindows(cb, None)
    return out


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "RobloxPlayerBeta.exe"
    try:
        r = find_window(name)
        print(f"{name}: x={r.x} y={r.y} w={r.w} h={r.h}")
    except WindowNotFound as e:
        print(f"{e}\n")
        print("Visible top-level windows on this desktop:")
        for proc_name, title, rect in list_windows():
            print(f"  {proc_name:<32} {rect.w:>5}x{rect.h:<5}  {title}")
        sys.exit(1)
