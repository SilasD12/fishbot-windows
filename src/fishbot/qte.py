"""Detect the QTE keyboard prompt at screen center via Tesseract OCR."""

from __future__ import annotations

from dataclasses import dataclass
import logging

import cv2
import numpy as np
import pytesseract


_KERNEL_3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
_LONG_HORIZONTAL_KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (131, 1))
log = logging.getLogger("fishbot")


@dataclass(frozen=True)
class QteConfig:
    crop_w: int
    crop_h: int
    whitelist: str

    @classmethod
    def from_toml(cls, qte: dict) -> "QteConfig":
        return cls(
            crop_w=int(qte["crop_w"]),
            crop_h=int(qte["crop_h"]),
            whitelist=str(qte["ocr_whitelist"]),
        )


def center_crop(bgr: np.ndarray, w: int, h: int) -> np.ndarray:
    fh, fw = bgr.shape[:2]
    cx, cy = fw // 2, fh // 2
    x0 = max(0, cx - w // 2)
    y0 = max(0, cy - h // 2)
    x1 = min(fw, x0 + w)
    y1 = min(fh, y0 + h)
    return bgr[y0:y1, x0:x1]


def read_qte_key(bgr: np.ndarray, cfg: QteConfig) -> str | None:
    """Return a single uppercase letter/digit, or None if nothing readable."""
    crop = center_crop(bgr, cfg.crop_w, cfg.crop_h)
    return _ocr_key(crop, cfg.whitelist)


def read_key_in_region(
    bgr: np.ndarray, w: int, h: int, whitelist: str,
    debug_path: str | None = None,
) -> str | None:
    """OCR a centered region of arbitrary size for a single key glyph."""
    crop = center_crop(bgr, w, h)
    return _ocr_key(crop, whitelist, debug_path=debug_path)


def _ocr_key(
    crop: np.ndarray, whitelist: str, debug_path: str | None = None,
) -> str | None:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Glyphs are bright on dark; threshold high to isolate them.
    _, thr = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

    # A real key prompt is a small white letter centered inside a compact
    # dark keycap. Textboxes are also white-on-dark, so the keycap shape is
    # required before OCR runs.
    contours, _ = cv2.findContours(thr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    glyphs: list[tuple[float, np.ndarray]] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 80:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w < 4 or h < 20 or w > 80 or h > 80:
            continue
        aspect = w / h
        if aspect < 0.07 or aspect > 1.4:
            continue
        # Serif/keycap letters like T/F/E have sparse strokes and can fill
        # less than 20% of their glyph bbox. The keycap gate below is the
        # actual false-positive guard, so keep this only as a tiny-fragment
        # filter.
        if area / (w * h) < 0.12:
            continue
        # Sample a 6-px ring just outside the bounding box in the grayscale.
        pad_check = 6
        gx0 = max(0, x - pad_check)
        gy0 = max(0, y - pad_check)
        gx1 = min(gray.shape[1], x + w + pad_check)
        gy1 = min(gray.shape[0], y + h + pad_check)
        outer = gray[gy0:gy1, gx0:gx1].copy()
        # Mask out the inner glyph region; keep only the surrounding ring.
        inner_x0 = max(0, x - gx0)
        inner_y0 = max(0, y - gy0)
        outer[inner_y0:inner_y0 + h, inner_x0:inner_x0 + w] = 255
        ring = outer[outer < 255]
        if ring.size == 0:
            continue
        if float(np.mean(ring)) > 90:
            # Surroundings are too bright — this isn't a glyph in a dark box.
            continue
        keycap = _keycap_bounds(gray, x, y, w, h)
        if keycap is None:
            continue

        kx, ky, kw, kh = keycap
        # Prefer the most centered/filled glyph inside a valid keycap if more
        # than one bright blob survives the gates.
        gx_mid = x + w / 2
        gy_mid = y + h / 2
        kx_mid = kx + kw / 2
        ky_mid = ky + kh / 2
        center_error = abs(gx_mid - kx_mid) / kw + abs(gy_mid - ky_mid) / kh
        score = area - center_error * 100

        pad = 12
        x0 = max(0, x - pad)
        y0 = max(0, y - pad)
        x1 = min(thr.shape[1], x + w + pad)
        y1 = min(thr.shape[0], y + h + pad)
        glyph = thr[y0:y1, x0:x1]
        tight = thr[y:y + h, x:x + w].copy()
        glyph = cv2.copyMakeBorder(
            glyph, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=0,
        )
        # Tesseract is more stable on normal black-on-white text, and the
        # prompt glyph crop is small enough that upscaling avoids single-pixel
        # antialiasing gaps changing the recognized letter.
        glyph = cv2.resize(
            255 - glyph, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST,
        )
        glyphs.append((score, glyph, tight))

    if not glyphs:
        return None
    best = max(glyphs, key=lambda item: item[0])
    glyph = best[1]
    tight = best[2]
    if debug_path is not None:
        cv2.imwrite(debug_path, glyph)

    config = (
        f"--psm 13 --oem 3 "
        f"-c tessedit_char_whitelist={whitelist}"
    )
    txt = pytesseract.image_to_string(glyph, config=config).strip()
    if not txt:
        return None
    ch = txt[0].upper()
    if ch in ("C", "G") and "C" in whitelist and "G" in whitelist:
        ch = _disambiguate_c_g(tight, fallback=ch)
    if ch in whitelist:
        return ch
    return None


def _disambiguate_c_g(tight: np.ndarray, fallback: str) -> str:
    """Distinguish G from C by detecting the horizontal bar in the right interior.

    Tesseract regularly reads the game's blocky `G` glyph as `C`. `tight` is the
    white-on-black glyph cropped to its bounding box. A C is open on the right;
    a G has a short horizontal stroke crossing the right-interior region.
    """
    h, w = tight.shape[:2]
    if w < 6 or h < 6:
        return fallback
    rx0 = int(w * 0.55)
    rx1 = int(w * 0.98)
    ry0 = int(h * 0.40)
    ry1 = int(h * 0.78)
    region = tight[ry0:ry1, rx0:rx1]
    if region.size == 0:
        return fallback
    fill = float(np.mean(region > 127))
    decided = "G" if fill > 0.15 else "C"
    if decided != fallback:
        log.debug(
            "C/G disambiguation overrode tesseract=%s -> %s (fill=%.3f)",
            fallback, decided, fill,
        )
    return decided


def _keycap_bounds(
    gray: np.ndarray, glyph_x: int, glyph_y: int, glyph_w: int, glyph_h: int,
) -> tuple[int, int, int, int] | None:
    """Return a compact dark keycap enclosing the glyph, or None.

    The Roblox chat/user textbox creates the same white-on-dark glyph pattern
    as the prompt. Requiring the enclosing dark component to be square-ish
    rejects wide text fields before Tesseract sees them.
    """
    dark = cv2.inRange(gray, 0, 105)
    # Interaction prompts can have a long dark progress/action bar directly
    # under the square keycap. If that touches the keycap shadow, connected
    # components sees one wide dark object and rejects the real prompt. Remove
    # only horizontal runs longer than the max keycap width before looking for
    # the compact enclosing box.
    long_horizontal = cv2.morphologyEx(
        dark, cv2.MORPH_OPEN, _LONG_HORIZONTAL_KERNEL,
    )
    if cv2.countNonZero(long_horizontal) > 0:
        dark = cv2.bitwise_and(dark, cv2.bitwise_not(long_horizontal))
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, _KERNEL_3)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)

    glyph_cx = glyph_x + glyph_w // 2
    glyph_cy = glyph_y + glyph_h // 2
    if (
        glyph_cx < 0 or glyph_cx >= gray.shape[1]
        or glyph_cy < 0 or glyph_cy >= gray.shape[0]
    ):
        return None

    label = int(labels[glyph_cy, glyph_cx])
    if label == 0:
        # The glyph itself is bright, so sample just outside it when the exact
        # center falls on a white stroke.
        probes = (
            (glyph_x - 3, glyph_cy),
            (glyph_x + glyph_w + 3, glyph_cy),
            (glyph_cx, glyph_y - 3),
            (glyph_cx, glyph_y + glyph_h + 3),
        )
        probe_labels = [
            int(labels[py, px])
            for px, py in probes
            if 0 <= px < gray.shape[1] and 0 <= py < gray.shape[0]
            and int(labels[py, px]) != 0
        ]
        if not probe_labels:
            return _keycap_bounds_from_local_contours(
                dark, gray, glyph_x, glyph_y, glyph_w, glyph_h,
            )
        label = max(set(probe_labels), key=probe_labels.count)

    x, y, w, h, area = (int(v) for v in stats[label])
    if w < 36 or h < 36 or w > 130 or h > 130:
        return _keycap_bounds_from_local_contours(
            dark, gray, glyph_x, glyph_y, glyph_w, glyph_h,
        )
    aspect = w / h
    if aspect < 0.65 or aspect > 1.45:
        return _keycap_bounds_from_local_contours(
            dark, gray, glyph_x, glyph_y, glyph_w, glyph_h,
        )
    if area / (w * h) < 0.55:
        return _keycap_bounds_from_local_contours(
            dark, gray, glyph_x, glyph_y, glyph_w, glyph_h,
        )

    # The letter should sit inside the keycap with a visible dark margin.
    margin_x = min(glyph_x - x, x + w - (glyph_x + glyph_w))
    margin_y = min(glyph_y - y, y + h - (glyph_y + glyph_h))
    if margin_x < 5 or margin_y < 5:
        return _keycap_bounds_from_local_contours(
            dark, gray, glyph_x, glyph_y, glyph_w, glyph_h,
        )

    # Reject dark UI surfaces clipped by the OCR crop, which is common for
    # centered textboxes but not for a standalone key prompt.
    if (
        x <= 1 or y <= 1
        or x + w >= gray.shape[1] - 1
        or y + h >= gray.shape[0] - 1
    ):
        return _keycap_bounds_from_local_contours(
            dark, gray, glyph_x, glyph_y, glyph_w, glyph_h,
        )

    return x, y, w, h


def _keycap_bounds_from_local_contours(
    dark: np.ndarray,
    gray: np.ndarray,
    glyph_x: int,
    glyph_y: int,
    glyph_w: int,
    glyph_h: int,
) -> tuple[int, int, int, int] | None:
    """Find a compact keycap near the glyph after component probing fails."""
    sx0 = max(0, glyph_x - 70)
    sy0 = max(0, glyph_y - 70)
    sx1 = min(dark.shape[1], glyph_x + glyph_w + 70)
    sy1 = min(dark.shape[0], glyph_y + glyph_h + 70)
    local = dark[sy0:sy1, sx0:sx1]
    contours, _ = cv2.findContours(
        local, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
    )

    best: tuple[float, tuple[int, int, int, int]] | None = None
    glyph_cx = glyph_x + glyph_w / 2
    glyph_cy = glyph_y + glyph_h / 2
    for c in contours:
        area = cv2.contourArea(c)
        if area <= 0:
            continue
        lx, ly, w, h = cv2.boundingRect(c)
        x = sx0 + lx
        y = sy0 + ly
        if w < 36 or h < 36 or w > 130 or h > 130:
            continue
        aspect = w / h
        if aspect < 0.65 or aspect > 1.45:
            continue
        if not (
            x <= glyph_x
            and y <= glyph_y
            and x + w >= glyph_x + glyph_w
            and y + h >= glyph_y + glyph_h
        ):
            continue
        fill = area / (w * h)
        if fill < 0.50:
            continue
        margin_x = min(glyph_x - x, x + w - (glyph_x + glyph_w))
        margin_y = min(glyph_y - y, y + h - (glyph_y + glyph_h))
        if margin_x < 5 or margin_y < 5:
            continue
        if (
            x <= 1 or y <= 1
            or x + w >= gray.shape[1] - 1
            or y + h >= gray.shape[0] - 1
        ):
            continue

        cx = x + w / 2
        cy = y + h / 2
        center_error = abs(glyph_cx - cx) / w + abs(glyph_cy - cy) / h
        score = fill - center_error
        if best is None or score > best[0]:
            best = (score, (x, y, w, h))

    if best is not None:
        log.debug("OCR keycap recovered from local contour: %s", best[1])
        return best[1]
    return _keycap_bounds_from_edge_search(gray, glyph_x, glyph_y, glyph_w, glyph_h)


def _keycap_bounds_from_edge_search(
    gray: np.ndarray,
    glyph_x: int,
    glyph_y: int,
    glyph_w: int,
    glyph_h: int,
) -> tuple[int, int, int, int] | None:
    """Recover keycaps on dark scenery by finding the square border edges."""
    if glyph_h < 32:
        return None

    edges = cv2.Canny(gray, 35, 120)
    glyph_cx = glyph_x + glyph_w / 2
    glyph_cy = glyph_y + glyph_h / 2
    min_side = max(44, glyph_w + 18, glyph_h + 18)
    max_side = min(130, max(min_side, int(max(glyph_w * 2.8, glyph_h * 2.0))))

    best: tuple[float, tuple[int, int, int, int]] | None = None
    for side in range(int(min_side), int(max_side) + 1, 4):
        for dx in range(-10, 11, 5):
            for dy in range(-10, 11, 5):
                x = int(round(glyph_cx - side / 2 + dx))
                y = int(round(glyph_cy - side / 2 + dy))
                if (
                    x <= 1 or y <= 1
                    or x + side >= gray.shape[1] - 1
                    or y + side >= gray.shape[0] - 1
                ):
                    continue
                if not (
                    x <= glyph_x
                    and y <= glyph_y
                    and x + side >= glyph_x + glyph_w
                    and y + side >= glyph_y + glyph_h
                ):
                    continue
                margin_x = min(glyph_x - x, x + side - (glyph_x + glyph_w))
                margin_y = min(glyph_y - y, y + side - (glyph_y + glyph_h))
                if margin_x < 5 or margin_y < 5:
                    continue

                roi_gray = gray[y:y + side, x:x + side]
                roi_edges = edges[y:y + side, x:x + side]
                glyph_mask = np.zeros_like(roi_gray, dtype=np.uint8)
                gx0 = glyph_x - x
                gy0 = glyph_y - y
                glyph_mask[gy0:gy0 + glyph_h, gx0:gx0 + glyph_w] = 255
                dark_samples = roi_gray[glyph_mask == 0]
                if dark_samples.size == 0 or float(np.mean(dark_samples)) > 95:
                    continue

                band = 5
                top = roi_edges[:band, :]
                bottom = roi_edges[-band:, :]
                left = roi_edges[:, :band]
                right = roi_edges[:, -band:]
                side_hits = [
                    cv2.countNonZero(top) / top.size,
                    cv2.countNonZero(bottom) / bottom.size,
                    cv2.countNonZero(left) / left.size,
                    cv2.countNonZero(right) / right.size,
                ]
                strong_sides = sum(hit >= 0.035 for hit in side_hits)
                if strong_sides < 3:
                    continue

                edge_score = sum(side_hits)
                center_error = (
                    abs(glyph_cx - (x + side / 2)) / side
                    + abs(glyph_cy - (y + side / 2)) / side
                )
                score = edge_score - center_error
                if best is None or score > best[0]:
                    best = (score, (x, y, side, side))

    if best is not None:
        log.debug("OCR keycap recovered from edge search: %s", best[1])
        return best[1]
    return None
