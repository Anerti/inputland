import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from inputland.camera import Camera
from inputland.config import Settings
from inputland.filters import OneEuroFilter
from inputland.gestures import Debounce, is_pinching, pick_pointer_hand
from inputland.pointer import VirtualPointer
from inputland.tracking import INDEX_MCP, Hand, HandTracker, ensure_model

log = logging.getLogger(__name__)

PREVIEW_WINDOW = "inputland preview"


@dataclass(frozen=True)
class Status:
    """What the loop sees, for the HUD."""

    driver: str | None  # side of the hand moving the cursor, None when idle
    hands: tuple[tuple[str, str], ...]  # (side, gesture), sorted


def run(
    settings: Settings,
    on_status: Callable[[Status], None] = lambda status: None,
    stop: threading.Event | None = None,
) -> None:
    """Main loop. Reports `on_status` whenever it changes; exits when `stop` is set."""
    model = ensure_model()
    with (
        Camera(settings.camera, settings.width, settings.height) as camera,
        HandTracker(model) as tracker,
        VirtualPointer() as pointer,
    ):
        gate = Debounce(settings.engage_frames, settings.release_frames)
        smooth_x = OneEuroFilter(settings.min_cutoff, settings.beta)
        smooth_y = OneEuroFilter(settings.min_cutoff, settings.beta)
        pinch = Debounce(settings.engage_frames, settings.release_frames)
        log.info("running; point with either index finger to move the cursor, pinch to click, hold the pinch to drag")
        driver: str | None = None
        # Survives a release: a slow pinch passes through unrecognized poses, then takes control back.
        last_driver: str | None = None
        last_status = None

        for frame in camera.frames():
            if stop is not None and stop.is_set():
                break
            now = time.monotonic()
            hands = tracker.detect(frame, int(now * 1000))
            if not hands:
                last_driver = None  # hand left the view: point again before pinching
            hand = pick_pointer_hand(hands, driver or last_driver, settings.min_gesture_score, settings.pinch_ratio)

            active = gate.update(hand is not None)
            if not active:
                driver = None
            elif hand is not None:
                if hand.side != driver:
                    # Engaged or switched hands: start fresh instead of gliding from the old position.
                    log.debug("cursor driven by %s hand", hand.side.lower())
                    smooth_x.reset()
                    smooth_y.reset()
                    driver = last_driver = hand.side
                # Base of the index finger: steadier than the fingertip, and it does not move while pinching.
                u, v = settings.region.normalize(*hand.landmarks[INDEX_MCP])
                pointer.move_to(smooth_x(u, now), smooth_y(v, now))

            # Only the driver's pinch holds the left button: down on close, up on open, so a quick pinch clicks.
            was_pinching = pinch.state
            pinching = driver is not None and hand is not None and is_pinching(hand, settings.pinch_ratio)
            if pinch.update(pinching) != was_pinching:
                log.debug("left button %s", "up" if was_pinching else "down")
                if was_pinching:
                    pointer.release()
                else:
                    pointer.press()

            status = Status(driver, tuple(sorted((h.side, h.gesture) for h in hands)))
            if status != last_status:
                on_status(status)
                last_status = status

            if settings.preview and not _show_preview(frame, hands, driver is not None, settings):
                break


def _show_preview(frame: np.ndarray, hands: list[Hand], active: bool, settings: Settings) -> bool:
    """Draw the calibration view. Returns False when the user asks to quit."""
    h, w = frame.shape[:2]
    r = settings.region
    color = (0, 200, 0) if active else (0, 160, 255)
    cv2.rectangle(frame, (int(r.left * w), int(r.top * h)), (int(r.right * w), int(r.bottom * h)), color, 2)
    for hand in hands:
        for x, y in hand.landmarks:
            cv2.circle(frame, (int(x * w), int(y * h)), 3, (255, 255, 255), -1)
        x, y = hand.landmarks[INDEX_MCP]
        cv2.circle(frame, (int(x * w), int(y * h)), 7, color, -1)
        cv2.putText(
            frame, f"{hand.side}: {hand.gesture} {hand.score:.2f}",
            (int(x * w) + 10, int(y * h)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
        )
    cv2.putText(frame, "ACTIVE" if active else "idle", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    cv2.imshow(PREVIEW_WINDOW, frame)
    return cv2.waitKey(1) & 0xFF not in (ord("q"), 27)  # q or Esc
