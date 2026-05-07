"""Mouse + keyboard input for fishbot on Windows.

Uses pydirectinput, which sends scan-code based events through the Win32
SendInput API. Roblox (and most DirectX games) ignores the higher-level
mouse_event / keybd_event messages that pyautogui uses, so pydirectinput
is required for the game to actually receive the bot's input.
"""

from __future__ import annotations

import time

import pydirectinput as _pdi

# pydirectinput inserts a 100 ms pause after every call by default. The bot's
# state machine already paces itself; the extra pause makes clicks/holds miss
# their windows. Disable it globally.
_pdi.PAUSE = 0
# Tell pydirectinput to fail loudly if a coord lands off-screen instead of
# silently moving to (0, 0).
_pdi.FAILSAFE = False


def _normalize(letter: str) -> str:
    """Map config-style key names ('A', 'SPACE', 'ENTER') to pydirectinput names."""
    s = str(letter).strip().lower()
    if s in {"space", " "}:
        return "space"
    if s in {"enter", "return"}:
        return "enter"
    if s in {"esc", "escape"}:
        return "esc"
    return s


def keycode_for(letter: str) -> str:
    """Kept for backwards compat with older callers; returns the pydirectinput key name."""
    return _normalize(letter)


def move_abs(x: int, y: int) -> None:
    """Move pointer to absolute screen coordinates."""
    _pdi.moveTo(int(x), int(y), _pause=False)


def click_left() -> None:
    _pdi.click(_pause=False)


def click_at(x: int, y: int) -> None:
    move_abs(x, y)
    # Tiny gap so the OS registers the move before the click.
    time.sleep(0.03)
    click_left()


def tap_key(letter: str) -> None:
    _pdi.press(_normalize(letter), _pause=False)


def key_down(letter: str) -> None:
    _pdi.keyDown(_normalize(letter), _pause=False)


def key_up(letter: str) -> None:
    _pdi.keyUp(_normalize(letter), _pause=False)


def hold_key(letter: str, seconds: float) -> None:
    key = _normalize(letter)
    _pdi.keyDown(key, _pause=False)
    try:
        time.sleep(seconds)
    finally:
        _pdi.keyUp(key, _pause=False)


def hold_keys(letters: list[str] | tuple[str, ...], seconds: float) -> None:
    pressed: list[str] = []
    try:
        for letter in letters:
            key = _normalize(letter)
            _pdi.keyDown(key, _pause=False)
            pressed.append(key)
        time.sleep(seconds)
    finally:
        for key in reversed(pressed):
            _pdi.keyUp(key, _pause=False)
