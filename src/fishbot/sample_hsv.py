"""Print HSV stats for a small box around (x, y) in a saved debug frame.

Usage:
    uv run python -m fishbot.sample_hsv debug_frames/frame_00012.png 320 240
    uv run python -m fishbot.sample_hsv debug_frames/frame_00012.png 320 240 --box 8
"""

from __future__ import annotations

import argparse
import sys

import cv2
import numpy as np


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("x", type=lambda s: int(float(s)))
    p.add_argument("y", type=lambda s: int(float(s)))
    p.add_argument("--box", type=int, default=5,
                   help="half-width of sample box (default 5 -> 11x11)")
    args = p.parse_args()

    bgr = cv2.imread(args.image)
    if bgr is None:
        print(f"could not read {args.image}", file=sys.stderr)
        return 1

    h, w = bgr.shape[:2]
    x0, x1 = max(0, args.x - args.box), min(w, args.x + args.box + 1)
    y0, y1 = max(0, args.y - args.box), min(h, args.y + args.box + 1)
    crop = bgr[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    print(f"sampled box ({x0},{y0})-({x1},{y1}) = {crop.shape[1]}x{crop.shape[0]} px")
    print(f"  H: min={H.min():3d}  median={int(np.median(H)):3d}  max={H.max():3d}")
    print(f"  S: min={S.min():3d}  median={int(np.median(S)):3d}  max={S.max():3d}")
    print(f"  V: min={V.min():3d}  median={int(np.median(V)):3d}  max={V.max():3d}")
    print(f"suggested HSV range (loose):")
    pad = 10
    print(f"  lower = [{max(0, int(H.min())-pad)}, {max(0, int(S.min())-30)}, {max(0, int(V.min())-30)}]")
    print(f"  upper = [{min(179, int(H.max())+pad)}, 255, 255]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
