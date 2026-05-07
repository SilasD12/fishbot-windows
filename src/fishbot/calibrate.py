"""Interactive calibration: pick the cast region with a Qt overlay, write to config.

The overlay is a translucent fullscreen window painted across every screen.
The user drags a rectangle; on release we convert the screen rect to
window-relative coordinates (so the value survives window moves) by
subtracting the game window's origin, then rewrite the cast.rect line in
the user's config.toml.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from fishbot.paths import ensure_user_config
from fishbot.window import find_window


_RECT_LINE_RE = re.compile(
    r"^rect\s*=\s*\{[^}]*\}\s*$",
    re.MULTILINE,
)


class _Overlay(QWidget):
    """Translucent fullscreen widget that captures one drag selection."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Cover the full virtual desktop so multi-monitor users can drag across screens.
        virt = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(virt)
        self._origin_x = virt.x()
        self._origin_y = virt.y()

        self._start: QPoint | None = None
        self._end: QPoint | None = None
        self.result: tuple[int, int, int, int] | None = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.pos()
            self._end = event.pos()
            self.update()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._start is not None:
            self._end = event.pos()
            r = QRect(self._start, self._end).normalized()
            if r.width() > 4 and r.height() > 4:
                # Translate widget-relative coords back to absolute screen coords.
                self.result = (
                    r.x() + self._origin_x,
                    r.y() + self._origin_y,
                    r.width(),
                    r.height(),
                )
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.result = None
            self.close()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self._start is not None and self._end is not None:
            r = QRect(self._start, self._end).normalized()
            # Punch a hole through the dim layer so the user sees what they're picking.
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(r, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(QColor(0, 200, 255, 220))
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(r)


def pick_region() -> tuple[int, int, int, int] | None:
    """Show the overlay and return (x, y, w, h) in absolute screen pixels, or None."""
    app = QApplication.instance() or QApplication(sys.argv)
    overlay = _Overlay()
    overlay.showFullScreen()
    overlay.activateWindow()
    overlay.raise_()
    app.exec()
    return overlay.result


def main() -> int:
    cfg_path: Path = ensure_user_config()
    if not cfg_path.exists():
        print(f"config not found and no bundled default: {cfg_path}", file=sys.stderr)
        return 1

    cfg = tomllib.loads(cfg_path.read_text())
    process_name = cfg["window"].get("process_name", "RobloxPlayerBeta.exe")

    print(f"Locating window for process={process_name} ...", file=sys.stderr)
    win = find_window(process_name)
    print(f"  window: x={win.x} y={win.y} w={win.w} h={win.h}", file=sys.stderr)

    print("Drag a rectangle over the WATER where you want the bot to cast. "
          "Press Esc to cancel.", file=sys.stderr)
    picked = pick_region()
    if picked is None:
        print("Calibration cancelled.", file=sys.stderr)
        return 130
    sx, sy, sw, sh = picked
    print(f"  picked: x={sx} y={sy} w={sw} h={sh} (screen coords)", file=sys.stderr)

    rx, ry = sx - win.x, sy - win.y
    if rx < 0 or ry < 0 or rx + sw > win.w or ry + sh > win.h:
        print("WARNING: selection extends outside the game window — "
              "click coords may miss.", file=sys.stderr)

    new_line = f"rect = {{ x = {rx}, y = {ry}, w = {sw}, h = {sh} }}"
    text = cfg_path.read_text()
    if not _RECT_LINE_RE.search(text):
        print("Could not find an existing `rect = { ... }` line in config.toml; "
              "edit by hand.", file=sys.stderr)
        return 2
    new_text = _RECT_LINE_RE.sub(new_line, text, count=1)
    cfg_path.write_text(new_text)
    print(f"Updated {cfg_path}: cast.rect = window-relative "
          f"({rx}, {ry}, {sw}, {sh})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
