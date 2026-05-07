"""Smoke tests: import every module + synthetic A-Z OCR check.

Run on Windows with Python 3.12+:

    python -m tests.test_smoke

The OCR check is the same fixture used in the original Linux project:
synthesise a key-cap image for each letter, run it through read_qte_key,
and verify every letter round-trips.
"""

from __future__ import annotations

import sys
import traceback


def test_imports() -> None:
    print("[1] importing modules ...")
    from fishbot import paths  # noqa: F401
    from fishbot import qte  # noqa: F401
    from fishbot import vision  # noqa: F401
    from fishbot import capture  # noqa: F401
    from fishbot import inputs  # noqa: F401  -- needs pydirectinput
    if sys.platform == "win32":
        from fishbot import window  # noqa: F401
    from fishbot import main  # noqa: F401
    from fishbot import gui  # noqa: F401
    print("    OK")


def test_synthetic_ocr() -> None:
    print("[2] synthetic A-Z OCR ...")
    import cv2
    import numpy as np

    from fishbot.qte import QteConfig, read_qte_key

    bad: list[tuple[str, str | None]] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        img = np.full((220, 220, 3), 45, np.uint8)
        cv2.rectangle(img, (72, 55), (148, 131), (20, 20, 20), -1)
        cv2.rectangle(img, (72, 55), (148, 131), (80, 80, 80), 2)
        cv2.line(img, (64, 139), (156, 139), (8, 8, 8), 4)
        cv2.putText(
            img, letter, (88, 118),
            cv2.FONT_HERSHEY_SIMPLEX, 2.0, (245, 245, 245), 4, cv2.LINE_AA,
        )
        got = read_qte_key(img, QteConfig(220, 220, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        if got != letter:
            bad.append((letter, got))

    print(f"    synthetic A-Z prompt mismatches: {bad}")
    if bad:
        raise AssertionError(f"OCR mismatches: {bad}")
    print("    OK")


def main() -> int:
    failures: list[str] = []
    for fn in (test_imports, test_synthetic_ocr):
        try:
            fn()
        except Exception:
            traceback.print_exc()
            failures.append(fn.__name__)
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
