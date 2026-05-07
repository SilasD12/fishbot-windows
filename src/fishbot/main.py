"""Fishing bot main loop and state machine."""

from __future__ import annotations

import argparse
import logging
import random
import shutil
import signal
import sys
import time
import tomllib
from collections import deque
from enum import Enum, auto
from pathlib import Path

import cv2
import pytesseract

from fishbot import inputs, paths
from fishbot.capture import capture_rect
from fishbot.qte import QteConfig, read_key_in_region
from fishbot.vision import (
    ChestConfig,
    FishConfig,
    HookConfig,
    chest_mask,
    count_fish_pixels_near,
    detect_chest,
    detect_hook,
    fish_mask,
    hook_mask,
    hsv_pixel_ratio,
)
from fishbot.window import WindowNotFound, WindowRect, find_window


log = logging.getLogger("fishbot")


class State(Enum):
    IDLE = auto()
    WAIT_HOOK = auto()
    WAIT_BITE = auto()
    REEL = auto()
    QTE_LOOP = auto()
    CHEST_HUNT = auto()


_running = True


def _sigint_handler(signum, frame):  # noqa: ARG001
    global _running
    _running = False
    log.warning("interrupt received, shutting down after current step")


def resolve_default_config() -> Path:
    """Where main() looks for config.toml when --config is not given.

    Order: %APPDATA%\\Fishbot\\config.toml (created on first run from the
    bundled default) -> the bundled config.toml next to the install dir.
    """
    return paths.ensure_user_config() or paths.bundled_config_path()


def configure_tesseract() -> str | None:
    """Point pytesseract at the bundled tesseract.exe if it exists.

    Returns a human-readable error string if Tesseract still cannot be
    located on PATH, otherwise None.
    """
    bundled = paths.tesseract_path()
    if bundled.exists():
        pytesseract.pytesseract.tesseract_cmd = str(bundled)
        tessdata = paths.tessdata_dir()
        if tessdata.exists():
            import os
            os.environ.setdefault("TESSDATA_PREFIX", str(tessdata.parent))
        return None
    if shutil.which("tesseract") is None:
        return (
            "Tesseract OCR was not found. The installer normally bundles it "
            "under <install>\\vendor\\tesseract\\tesseract.exe. If you are "
            "running from source, install Tesseract and ensure tesseract.exe "
            "is on PATH."
        )
    return None


def pick_cast_point(rect_cfg: dict, randomize: bool) -> tuple[int, int]:
    """Window-relative cast point sampled from the configured rect."""
    x, y, w, h = rect_cfg["x"], rect_cfg["y"], rect_cfg["w"], rect_cfg["h"]
    if not randomize or w <= 0 or h <= 0:
        return x + w // 2, y + h // 2
    return x + random.randint(0, w - 1), y + random.randint(0, h - 1)


def click_in_window(process_name: str, rel_x: int, rel_y: int, dry_run: bool) -> None:
    """Translate window-relative coords to absolute and click (unless dry_run)."""
    win = find_window(process_name)
    abs_x, abs_y = win.x + rel_x, win.y + rel_y
    log.info("click at (%d, %d) [window-rel (%d, %d)]", abs_x, abs_y, rel_x, rel_y)
    if dry_run:
        return
    inputs.click_at(abs_x, abs_y)


def run(cfg: dict, args: argparse.Namespace) -> int:
    process_name = cfg["window"]["process_name"]
    cast_cfg = cfg["cast"]
    loop_cfg = cfg["loop"]
    qte_section = cfg["qte"]
    chest_cfg = cfg["chest"]

    hook_cfg = HookConfig.from_toml(cfg["vision"])
    fish_cfg = FishConfig.from_toml(cfg["vision"])
    chest_vision_cfg = ChestConfig.from_toml(chest_cfg)
    qte_cfg = QteConfig.from_toml(qte_section)

    period = 1.0 / float(loop_cfg["capture_hz"])
    max_wait_bite = float(loop_cfg["max_wait_bite_seconds"])
    max_hook_lost = float(loop_cfg.get("max_hook_lost_seconds", 8.0))
    flicker_window_seconds = float(loop_cfg.get("flicker_window_seconds", 5.0))
    flicker_max_transitions = int(loop_cfg.get("flicker_max_transitions", 6))
    flicker_min_spread_px = float(loop_cfg.get("flicker_min_spread_px", 30.0))
    hook_lock_radius_px = float(loop_cfg.get("hook_lock_radius_px", 60.0))
    cast_settle = float(loop_cfg["cast_settle_seconds"])
    reel_after_bite = float(loop_cfg["reel_after_bite_ms"]) / 1000.0
    reel_click_x_ratio = float(loop_cfg.get("reel_click_x_ratio", 0.82))
    reel_click_y_ratio = float(loop_cfg.get("reel_click_y_ratio", 0.50))
    qte_poll = float(qte_section["poll_seconds"])
    qte_quiet = float(qte_section["quiet_seconds"])
    qte_max_sequence = float(qte_section.get("max_sequence_seconds", 12.0))
    qte_debounce = float(qte_section["debounce_ms"]) / 1000.0

    chest_watch = float(chest_cfg.get("watch_seconds", 4.0))
    chest_approach_step = float(chest_cfg.get("approach_step_seconds", 0.30))
    chest_max_approach = float(chest_cfg.get("max_approach_seconds", 5.5))
    chest_hold_seconds = float(chest_cfg.get("hold_e_seconds", 2.5))
    chest_close_height_ratio = float(chest_cfg.get("close_height_ratio", 0.19))
    chest_grass_min_ratio = float(chest_cfg.get("grass_min_screen_ratio", 0.50))
    chest_grass_grace_seconds = float(chest_cfg.get("grass_grace_seconds", 0.6))
    chest_grass_walk_threshold = float(chest_cfg.get("grass_walk_threshold", 0.65))
    chest_grass_hsv_lower = tuple(chest_cfg.get("grass_hsv_lower", (35, 45, 20)))
    chest_grass_hsv_upper = tuple(chest_cfg.get("grass_hsv_upper", (95, 255, 255)))

    debug_dir: Path | None = None
    if args.debug_mask:
        debug_dir = paths.debug_frames_dir()
        debug_dir.mkdir(parents=True, exist_ok=True)
        log.info("writing debug masks to %s/", debug_dir)

    bite_y_drop_px = float(cfg["vision"].get("bite_y_drop_px", 25))
    bite_sustain_frames = int(cfg["vision"].get("bite_sustain_frames", 4))
    y_drop_recent_visible_frames = int(
        cfg["vision"].get("y_drop_recent_visible_frames", 10),
    )
    fish_initial_ignore = float(cfg["vision"].get("fish_initial_ignore_seconds", 2.0))
    pos_history_len = int(cfg["vision"].get("position_history_len", 40))
    baseline_exclude_tail = int(cfg["vision"].get("baseline_exclude_tail", 8))

    state = State.IDLE
    last_state_change = time.monotonic()
    detection_history: deque[bool] = deque(
        maxlen=max(12, y_drop_recent_visible_frames),
    )
    position_history: deque[tuple[int, int]] = deque(maxlen=pos_history_len)
    fish_history: deque[int] = deque(maxlen=20)
    last_hook_pos: tuple[int, int] | None = None
    hook_lost_since = 0.0
    drop_streak = 0
    last_qte_letter: str | None = None
    last_qte_at = 0.0
    qte_last_seen = 0.0
    qte_started = 0.0
    qte_pending_letter: str | None = None
    qte_keys_pressed = 0
    chest_started = 0.0
    chest_first_seen = 0.0
    flicker_times: deque[float] = deque()
    flicker_positions: deque[tuple[int, int]] = deque()
    fish_ever_seen = False
    debug_idx = 0

    catches = 0

    def transition(new: State) -> None:
        nonlocal state, last_state_change
        nonlocal drop_streak, last_hook_pos, hook_lost_since
        nonlocal fish_ever_seen
        log.info("state: %s -> %s", state.name, new.name)
        state = new
        last_state_change = time.monotonic()
        detection_history.clear()
        position_history.clear()
        fish_history.clear()
        last_hook_pos = None
        hook_lost_since = 0.0
        drop_streak = 0
        flicker_times.clear()
        flicker_positions.clear()
        fish_ever_seen = False

    while _running:
        loop_start = time.monotonic()

        if state == State.IDLE:
            try:
                rel_x, rel_y = pick_cast_point(cast_cfg["rect"], cast_cfg["randomize"])
                click_in_window(process_name, rel_x, rel_y, args.dry_run)
            except WindowNotFound as e:
                log.error("%s; retrying in 2 s", e)
                time.sleep(2)
                continue
            time.sleep(cast_settle)
            transition(State.WAIT_HOOK)
            continue

        try:
            cap_start = time.monotonic()
            win = find_window(process_name)
            if state in (State.QTE_LOOP, State.CHEST_HUNT):
                watch = win
            else:
                margin = 120
                cr = cast_cfg["rect"]
                watch = WindowRect(
                    x=max(0, win.x + cr["x"] - margin),
                    y=max(0, win.y + cr["y"] - margin),
                    w=cr["w"] + 2 * margin,
                    h=cr["h"] + 2 * margin,
                )
            frame = capture_rect(watch)
            cap_ms = (time.monotonic() - cap_start) * 1000
            if debug_idx % 40 == 0:
                log.info("capture: %.0f ms (target period %.0f ms)", cap_ms, period * 1000)
        except WindowNotFound:
            log.warning("game window disappeared; waiting 2 s")
            time.sleep(2)
            continue
        except Exception as e:
            log.exception("capture failed: %s", e)
            time.sleep(0.5)
            continue

        if state in (State.WAIT_HOOK, State.WAIT_BITE):
            hook = detect_hook(frame, hook_cfg)
            if (
                hook is not None
                and state == State.WAIT_BITE
                and last_hook_pos is not None
            ):
                dx = hook.x - last_hook_pos[0]
                dy = hook.y - last_hook_pos[1]
                if (dx * dx + dy * dy) ** 0.5 > hook_lock_radius_px:
                    hook = None
            if debug_dir is not None and debug_idx % 6 == 0:
                m = hook_mask(frame, hook_cfg)
                fm = fish_mask(frame, fish_cfg)
                cv2.imwrite(str(debug_dir / f"mask_{debug_idx:05d}.png"), m)
                cv2.imwrite(str(debug_dir / f"fish_{debug_idx:05d}.png"), fm)
                cv2.imwrite(str(debug_dir / f"frame_{debug_idx:05d}.png"), frame)
            debug_idx += 1
            prev_seen = detection_history[-1] if detection_history else None
            now_seen = hook is not None
            detection_history.append(now_seen)
            if hook is not None:
                position_history.append((hook.x, hook.y))
                last_hook_pos = (hook.x, hook.y)
                hook_lost_since = 0.0

            fish_px = 0
            if state == State.WAIT_BITE and last_hook_pos is not None:
                fish_armed = time.monotonic() - last_state_change >= fish_initial_ignore
                if fish_armed:
                    fish_px = count_fish_pixels_near(
                        frame, last_hook_pos[0], last_hook_pos[1], fish_cfg,
                    )
                    fish_history.append(fish_px)
                    if fish_px >= fish_cfg.min_pixels:
                        fish_ever_seen = True
                else:
                    fish_history.clear()

            if state == State.WAIT_HOOK:
                if hook is not None:
                    log.info("hook visible at (%d, %d) r=%.1f", hook.x, hook.y, hook.r)
                    transition(State.WAIT_BITE)
                elif time.monotonic() - last_state_change > 6.0:
                    log.warning("hook never appeared; re-casting")
                    transition(State.IDLE)

            else:  # WAIT_BITE
                now = time.monotonic()
                transitioned = False
                if prev_seen is True and not now_seen:
                    log.info("hook LOST (watching for bite)")
                    hook_lost_since = now
                    position_history.clear()
                    drop_streak = 0
                    transitioned = True
                    flicker_times.append(now)
                elif prev_seen is False and now_seen:
                    log.info("hook back at (%d, %d) r=%.1f", hook.x, hook.y, hook.r)
                    transitioned = True
                    flicker_times.append(now)
                    flicker_positions.append((hook.x, hook.y))
                elif not now_seen and hook_lost_since == 0.0:
                    hook_lost_since = now
                    position_history.clear()
                    drop_streak = 0
                if transitioned and debug_dir is not None:
                    m = hook_mask(frame, hook_cfg)
                    fm = fish_mask(frame, fish_cfg)
                    cv2.imwrite(str(debug_dir / f"transition_{debug_idx:05d}_mask.png"), m)
                    cv2.imwrite(str(debug_dir / f"transition_{debug_idx:05d}_fish.png"), fm)
                    cv2.imwrite(str(debug_dir / f"transition_{debug_idx:05d}_frame.png"), frame)
                bite_fired = False

                if not bite_fired and len(fish_history) >= 6:
                    recent = list(fish_history)[-3:]
                    older = list(fish_history)[:-3]
                    fish_was_present = any(p >= fish_cfg.min_pixels for p in older)
                    fish_now_gone = all(p < fish_cfg.min_pixels for p in recent)
                    hook_under_or_dropped = (hook is None) or (drop_streak > 0)
                    if fish_was_present and fish_now_gone and hook_under_or_dropped:
                        peak = max(older) if older else 0
                        log.info(
                            "BITE via fish-contact: peak_blue=%d now=%d hook=%s (catches=%d)",
                            peak, fish_px, "under" if hook is None else "down",
                            catches + 1,
                        )
                        bite_fired = True

                recent_seen = list(detection_history)[-y_drop_recent_visible_frames:]
                y_drop_stable = (
                    len(recent_seen) == y_drop_recent_visible_frames
                    and all(recent_seen)
                )
                if (
                    not bite_fired
                    and hook is not None
                    and y_drop_stable
                    and len(position_history) >= baseline_exclude_tail + 4
                ):
                    older_ys = sorted(
                        y for _, y in list(position_history)[:-baseline_exclude_tail]
                    )
                    baseline_y = older_ys[len(older_ys) // 2]
                    drop = hook.y - baseline_y
                    if drop >= bite_y_drop_px:
                        drop_streak += 1
                        if drop_streak >= bite_sustain_frames:
                            log.info(
                                "BITE via Y-drop: y=%d baseline=%d drop=%.1f sustained=%d (catches=%d)",
                                hook.y, baseline_y, drop, drop_streak, catches + 1,
                            )
                            bite_fired = True
                    else:
                        drop_streak = 0
                elif hook is None or not y_drop_stable:
                    drop_streak = 0

                while flicker_times and now - flicker_times[0] > flicker_window_seconds:
                    flicker_times.popleft()
                while len(flicker_positions) > len(flicker_times):
                    flicker_positions.popleft()

                position_spread = 0.0
                if len(flicker_positions) >= 2:
                    xs = [p[0] for p in flicker_positions]
                    ys = [p[1] for p in flicker_positions]
                    position_spread = max(max(xs) - min(xs), max(ys) - min(ys))

                if bite_fired:
                    transition(State.REEL)
                elif (
                    not fish_ever_seen
                    and len(flicker_times) >= flicker_max_transitions
                    and position_spread >= flicker_min_spread_px
                ):
                    log.warning(
                        "hook flickered %d times in %.1fs spread=%.0fpx with no fish; "
                        "cast likely failed, re-casting",
                        len(flicker_times), flicker_window_seconds, position_spread,
                    )
                    transition(State.IDLE)
                elif hook_lost_since > 0 and now - hook_lost_since > max_hook_lost:
                    log.warning(
                        "hook missing for %.1fs without bite signal; re-casting",
                        now - hook_lost_since,
                    )
                    transition(State.IDLE)
                elif now - last_state_change > max_wait_bite:
                    seen_count = sum(detection_history)
                    log.warning(
                        "no bite within %.0fs (last %d frames seen=%d/%d); re-casting",
                        max_wait_bite, len(detection_history), seen_count,
                        len(detection_history),
                    )
                    transition(State.IDLE)

        elif state == State.REEL:
            time.sleep(reel_after_bite)
            try:
                win = find_window(process_name)
                reel_x = max(0, min(win.w - 1, int(win.w * reel_click_x_ratio)))
                reel_y = max(0, min(win.h - 1, int(win.h * reel_click_y_ratio)))
                click_in_window(process_name, reel_x, reel_y, args.dry_run)
            except WindowNotFound as e:
                log.error("%s; retrying", e)
                time.sleep(1)
                continue
            catches += 1
            if args.no_qte:
                if not args.no_chest:
                    log.info("skipping chest hunt because --no-qte bypasses QTE")
                transition(State.IDLE)
            else:
                qte_started = time.monotonic()
                qte_last_seen = 0.0
                last_qte_letter = None
                last_qte_at = 0.0
                qte_pending_letter = None
                qte_keys_pressed = 0
                transition(State.QTE_LOOP)

        elif state == State.QTE_LOOP:
            now = time.monotonic()
            dbg = None
            if debug_dir is not None and debug_idx % 4 == 0:
                dbg = str(debug_dir / f"qte_thr_{debug_idx:05d}.png")
                cv2.imwrite(str(debug_dir / f"qte_frame_{debug_idx:05d}.png"), frame)
            debug_idx += 1
            raw = read_key_in_region(
                frame, qte_cfg.crop_w, qte_cfg.crop_h, qte_cfg.whitelist,
                debug_path=dbg,
            )
            if raw is not None and raw != qte_pending_letter:
                log.debug("QTE OCR candidate: %s (awaiting confirmation)", raw)
            letter: str | None = None
            if raw is not None and raw == qte_pending_letter:
                letter = raw
            qte_pending_letter = raw
            if letter is not None:
                qte_last_seen = now
                debounced = (
                    letter == last_qte_letter
                    and (now - last_qte_at) < qte_debounce
                )
                if not debounced:
                    log.info("QTE key: %s", letter)
                    if not args.dry_run:
                        try:
                            inputs.tap_key(letter)
                        except ValueError:
                            log.warning("no keymap for %r; skipping", letter)
                    qte_keys_pressed += 1
                    last_qte_letter = letter
                    last_qte_at = now

            elapsed_total = now - qte_started
            quiet = qte_last_seen > 0 and (now - qte_last_seen) >= qte_quiet
            never_seen = qte_last_seen == 0 and elapsed_total >= qte_poll
            timed_out = qte_last_seen > 0 and elapsed_total >= qte_max_sequence
            if timed_out:
                log.info("QTE sequence timeout after %.1fs", elapsed_total)
            qte_complete = quiet or timed_out
            if never_seen:
                log.info(
                    "no QTE keys detected within %.1fs; no chest expected",
                    qte_poll,
                )
                transition(State.IDLE)
            elif qte_complete:
                if args.no_chest:
                    transition(State.IDLE)
                elif qte_keys_pressed <= 0:
                    log.info("QTE ended without a key press; no chest expected")
                    transition(State.IDLE)
                else:
                    chest_started = time.monotonic()
                    chest_first_seen = 0.0
                    transition(State.CHEST_HUNT)

        elif state == State.CHEST_HUNT:
            now = time.monotonic()
            chest = detect_chest(frame, chest_vision_cfg)
            if debug_dir is not None and debug_idx % 4 == 0:
                cm = chest_mask(frame, chest_vision_cfg)
                annotated = frame.copy()
                if chest is not None:
                    cv2.rectangle(
                        annotated,
                        (chest.x, chest.y),
                        (chest.x + chest.w, chest.y + chest.h),
                        (0, 255, 255),
                        2,
                    )
                cv2.imwrite(str(debug_dir / f"chest_mask_{debug_idx:05d}.png"), cm)
                cv2.imwrite(
                    str(debug_dir / f"chest_frame_{debug_idx:05d}.png"), annotated,
                )
            debug_idx += 1

            elapsed_total = now - chest_started
            frame_h = frame.shape[0]
            grass_ratio = hsv_pixel_ratio(
                frame,
                chest_grass_hsv_lower,
                chest_grass_hsv_upper,
            )

            if grass_ratio > chest_grass_walk_threshold:
                if elapsed_total >= chest_watch + chest_max_approach:
                    log.info(
                        "still buried in grass=%.2f after %.1fs; giving up",
                        grass_ratio, elapsed_total,
                    )
                    transition(State.IDLE)
                else:
                    log.debug(
                        "knockback recovery: walking A+E (grass=%.2f > %.2f)",
                        grass_ratio, chest_grass_walk_threshold,
                    )
                    if not args.dry_run:
                        inputs.hold_keys(("A", "E"), chest_approach_step)
            elif chest is None:
                if elapsed_total >= chest_watch:
                    log.info(
                        "no chest detected within %.1fs (grass=%.2f)",
                        chest_watch, grass_ratio,
                    )
                    transition(State.IDLE)
                else:
                    log.debug(
                        "near shore (grass=%.2f) but no chest yet; nudging A+E",
                        grass_ratio,
                    )
                    if not args.dry_run:
                        inputs.hold_keys(("A", "E"), chest_approach_step)
            else:
                if chest_first_seen == 0.0:
                    chest_first_seen = now
                    log.info(
                        "chest detected at (%d,%d) %dx%d area=%.0f fill=%.2f grass=%.2f",
                        chest.x, chest.y, chest.w, chest.h, chest.area,
                        chest.fill_ratio, grass_ratio,
                    )

                close_by_size = chest.h >= frame_h * chest_close_height_ratio
                approach_expired = (now - chest_first_seen) >= chest_max_approach
                approach_elapsed = now - chest_first_seen
                grass_overshot = (
                    approach_elapsed >= chest_grass_grace_seconds
                    and grass_ratio <= chest_grass_min_ratio
                )
                if close_by_size or approach_expired or grass_overshot:
                    log.info(
                        "stopping strafe and holding E on chest "
                        "(close=%s grass=%.2f approach=%.1fs)",
                        close_by_size, grass_ratio, approach_elapsed,
                    )
                    if not args.dry_run:
                        inputs.hold_key("E", chest_hold_seconds)
                    transition(State.IDLE)
                else:
                    log.debug(
                        "approaching chest with A+E; bbox=%dx%d close_h=%d grass=%.2f",
                        chest.w, chest.h, int(frame_h * chest_close_height_ratio),
                        grass_ratio,
                    )
                    if not args.dry_run:
                        inputs.hold_keys(("A", "E"), chest_approach_step)

        elapsed = time.monotonic() - loop_start
        sleep_for = period - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)

    log.info("done. total catches: %d", catches)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=None,
                   help="path to config.toml (default: %APPDATA%\\Fishbot\\config.toml)")
    p.add_argument("--dry-run", action="store_true",
                   help="capture and detect, but issue no clicks/keypresses")
    p.add_argument("--no-qte", action="store_true",
                   help="skip QTE detection after reeling")
    p.add_argument("--no-chest", action="store_true",
                   help="skip chest hunt after QTE")
    p.add_argument("--debug-mask", action="store_true",
                   help="write hook mask + frame snapshots to %LOCALAPPDATA%\\Fishbot\\debug_frames\\")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="enable DEBUG-level logging")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    paths.ensure_user_dirs()

    cfg_path: Path = args.config if args.config is not None else resolve_default_config()
    if not cfg_path.exists():
        print(f"config not found: {cfg_path}", file=sys.stderr)
        return 1
    cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    log.info("loaded config from %s", cfg_path)

    tess_err = configure_tesseract()
    if tess_err and not args.dry_run:
        log.error("startup: %s", tess_err)
        return 2
    if tess_err:
        log.warning("startup (ignored under --dry-run): %s", tess_err)

    signal.signal(signal.SIGINT, _sigint_handler)
    if hasattr(signal, "SIGBREAK"):
        # Windows console Ctrl-Break maps to SIGBREAK; the GUI sends this to
        # request a graceful shutdown across the process boundary.
        signal.signal(signal.SIGBREAK, _sigint_handler)
    signal.signal(signal.SIGTERM, _sigint_handler)

    return run(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
