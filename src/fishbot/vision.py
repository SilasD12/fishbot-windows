"""Computer vision: locate the red fishing hook in a captured BGR frame."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class HookDetection:
    x: int
    y: int
    r: float
    area: float


@dataclass(frozen=True)
class BoxDetection:
    x: int
    y: int
    w: int
    h: int
    area: float
    fill_ratio: float

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclass(frozen=True)
class HookConfig:
    lower_a: tuple[int, int, int]
    upper_a: tuple[int, int, int]
    lower_b: tuple[int, int, int]
    upper_b: tuple[int, int, int]
    min_radius: float
    max_radius: float
    min_circularity: float

    @classmethod
    def from_toml(cls, vision: dict) -> "HookConfig":
        return cls(
            lower_a=tuple(vision["hook_hsv_lower_a"]),
            upper_a=tuple(vision["hook_hsv_upper_a"]),
            lower_b=tuple(vision["hook_hsv_lower_b"]),
            upper_b=tuple(vision["hook_hsv_upper_b"]),
            min_radius=float(vision["hook_min_radius_px"]),
            max_radius=float(vision["hook_max_radius_px"]),
            min_circularity=float(vision["hook_min_circularity"]),
        )


_KERNEL_3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
_KERNEL_9 = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))


def hook_mask(bgr: np.ndarray, cfg: HookConfig) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array(cfg.lower_a), np.array(cfg.upper_a)) | \
        cv2.inRange(hsv, np.array(cfg.lower_b), np.array(cfg.upper_b))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, _KERNEL_3)
    return m


def _circularity(contour: np.ndarray) -> float:
    area = cv2.contourArea(contour)
    perim = cv2.arcLength(contour, True)
    if perim <= 0:
        return 0.0
    return 4 * np.pi * area / (perim * perim)


@dataclass(frozen=True)
class FishConfig:
    ranges: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...]
    search_radius: int
    min_pixels: int

    @classmethod
    def from_toml(cls, vision: dict) -> "FishConfig":
        hsv_ranges = vision.get("fish_hsv_ranges")
        if hsv_ranges is None:
            ranges = (
                (
                    tuple(vision["fish_hsv_lower"]),
                    tuple(vision["fish_hsv_upper"]),
                ),
            )
        else:
            ranges = tuple(
                (tuple(item["lower"]), tuple(item["upper"]))
                for item in hsv_ranges
            )
        return cls(
            ranges=ranges,
            search_radius=int(vision["fish_search_radius_px"]),
            min_pixels=int(vision["fish_min_pixels"]),
        )


@dataclass(frozen=True)
class ChestConfig:
    ranges: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...]
    min_area: float
    min_width: int
    min_height: int
    max_width_ratio: float
    max_height_ratio: float
    min_aspect: float
    max_aspect: float
    min_fill_ratio: float
    max_fill_ratio: float
    scan_y_min_ratio: float
    scan_y_max_ratio: float

    @classmethod
    def from_toml(cls, chest: dict) -> "ChestConfig":
        hsv_ranges = chest.get(
            "hsv_ranges",
            (
                {"lower": (0, 50, 24), "upper": (16, 170, 64)},
                {"lower": (0, 45, 110), "upper": (12, 120, 190)},
                {"lower": (5, 80, 95), "upper": (24, 230, 165)},
            ),
        )
        ranges = tuple(
            (tuple(item["lower"]), tuple(item["upper"]))
            for item in hsv_ranges
        )
        return cls(
            ranges=ranges,
            min_area=float(chest.get("min_area_px", 450)),
            min_width=int(chest.get("min_width_px", 35)),
            min_height=int(chest.get("min_height_px", 28)),
            max_width_ratio=float(chest.get("max_width_ratio", 0.55)),
            max_height_ratio=float(chest.get("max_height_ratio", 0.45)),
            min_aspect=float(chest.get("min_aspect", 0.65)),
            max_aspect=float(chest.get("max_aspect", 3.2)),
            min_fill_ratio=float(chest.get("min_fill_ratio", 0.12)),
            max_fill_ratio=float(chest.get("max_fill_ratio", 1.0)),
            scan_y_min_ratio=float(chest.get("scan_y_min_ratio", 0.25)),
            scan_y_max_ratio=float(chest.get("scan_y_max_ratio", 0.98)),
        )


def fish_mask(bgr: np.ndarray, cfg: FishConfig) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in cfg.ranges:
        m |= cv2.inRange(hsv, np.array(lower), np.array(upper))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, _KERNEL_3)
    return m


def chest_mask(bgr: np.ndarray, cfg: ChestConfig) -> np.ndarray:
    """Mask likely chest wood colors.

    The dark night samples `#1f1714` and `#211a16` land around OpenCV
    HSV [8, 90, 31] and [11, 85, 33]. Day wood `#90736a` lands around
    [7, 67, 144]. Keep ranges in config because Roblox lighting shifts the
    same wood toward warmer and brighter browns during daytime.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in cfg.ranges:
        m |= cv2.inRange(hsv, np.array(lower), np.array(upper))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, _KERNEL_3)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, _KERNEL_9)
    return m


def hsv_pixel_ratio(
    bgr: np.ndarray,
    lower: tuple[int, int, int],
    upper: tuple[int, int, int],
) -> float:
    """Return the ratio of pixels inside one HSV range."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
    return cv2.countNonZero(mask) / float(mask.shape[0] * mask.shape[1])


def detect_chest(bgr: np.ndarray, cfg: ChestConfig) -> BoxDetection | None:
    """Return the most plausible chest-shaped wood object, or None."""
    frame_h, frame_w = bgr.shape[:2]
    mask = chest_mask(bgr, cfg)
    y_min = max(0, min(frame_h - 1, int(frame_h * cfg.scan_y_min_ratio)))
    y_max = max(y_min + 1, min(frame_h, int(frame_h * cfg.scan_y_max_ratio)))
    mask[:y_min, :] = 0
    mask[y_max:, :] = 0

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best: BoxDetection | None = None
    best_score = 0.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < cfg.min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w < cfg.min_width or h < cfg.min_height:
            continue
        if w > frame_w * cfg.max_width_ratio or h > frame_h * cfg.max_height_ratio:
            continue
        aspect = w / h
        if aspect < cfg.min_aspect or aspect > cfg.max_aspect:
            continue
        fill = cv2.countNonZero(mask[y:y + h, x:x + w]) / float(w * h)
        if fill < cfg.min_fill_ratio or fill > cfg.max_fill_ratio:
            continue

        # Chests are actionable when they are in the lower/near part of the
        # screen. Prefer compact, lower objects over thin rails or far planks.
        lower_weight = 1.0 + (y + h) / frame_h
        center_weight = 1.0 - min(0.75, abs((x + w / 2) - frame_w / 2) / frame_w)
        score = area * lower_weight * center_weight
        detection = BoxDetection(
            x=int(x), y=int(y), w=int(w), h=int(h),
            area=float(area), fill_ratio=float(fill),
        )
        if score > best_score:
            best = detection
            best_score = score
    return best


def count_fish_pixels_near(
    bgr: np.ndarray, cx: int, cy: int, cfg: FishConfig
) -> int:
    """Count bright-blue pixels within `search_radius` of (cx, cy)."""
    h, w = bgr.shape[:2]
    r = cfg.search_radius
    x0, x1 = max(0, cx - r), min(w, cx + r)
    y0, y1 = max(0, cy - r), min(h, cy + r)
    if x1 <= x0 or y1 <= y0:
        return 0
    crop = bgr[y0:y1, x0:x1]
    m = fish_mask(crop, cfg)
    return int(cv2.countNonZero(m))


def detect_hook(bgr: np.ndarray, cfg: HookConfig) -> HookDetection | None:
    """Return the most plausible hook detection, or None.

    "Most plausible" = largest enclosing circle within radius bounds and
    above the circularity floor. The hook is a small saturated red dot;
    this filter rejects red HUD elements (long bars, irregular patches).
    """
    mask = hook_mask(bgr, cfg)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best: HookDetection | None = None
    for c in contours:
        if len(c) < 5:
            continue
        (cx, cy), r = cv2.minEnclosingCircle(c)
        if r < cfg.min_radius or r > cfg.max_radius:
            continue
        if _circularity(c) < cfg.min_circularity:
            continue
        area = cv2.contourArea(c)
        if best is None or r > best.r:
            best = HookDetection(x=int(cx), y=int(cy), r=float(r), area=float(area))
    return best
