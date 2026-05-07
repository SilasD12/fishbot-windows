"""Windows screen capture via mss, returned as a BGR numpy array.

mss uses BitBlt under the hood on Windows and easily clears 60 fps for the
small regions the bot watches, so the capture is never the bottleneck.
"""

from __future__ import annotations

import numpy as np
from mss import mss

from fishbot.window import WindowRect


_sct = None


def _get_sct():
    """Lazy-init a single mss.mss() instance per process.

    mss objects are not thread-safe, but the bot is single-threaded. Re-using
    one instance avoids allocating a DC per frame.
    """
    global _sct
    if _sct is None:
        _sct = mss()
    return _sct


def capture_rect(rect: WindowRect) -> np.ndarray:
    """Capture the given screen rect as a BGR ndarray (H, W, 3).

    mss returns BGRA bytes; we drop the alpha channel and copy the slice so
    callers get a contiguous array (OpenCV operations expect that).
    """
    sct = _get_sct()
    region = {"left": int(rect.x), "top": int(rect.y),
              "width": int(rect.w), "height": int(rect.h)}
    raw = sct.grab(region)
    # raw.rgb / .bgra are bytes; np.asarray(raw) is shape (H, W, 4) BGRA.
    bgra = np.asarray(raw, dtype=np.uint8)
    return np.ascontiguousarray(bgra[:, :, :3])


if __name__ == "__main__":
    import argparse
    import sys

    import cv2

    from fishbot.paths import user_data_dir
    from fishbot.window import find_window

    p = argparse.ArgumentParser()
    p.add_argument("--process-name", default="RobloxPlayerBeta.exe")
    p.add_argument("--save", default=str(user_data_dir() / "fishbot_frame.png"))
    args = p.parse_args()

    rect = find_window(args.process_name)
    img = capture_rect(rect)
    cv2.imwrite(args.save, img)
    print(f"saved {args.save} ({img.shape[1]}x{img.shape[0]})", file=sys.stderr)
