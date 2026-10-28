import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from inputland.camera import Camera
from inputland.config import Settings
from inputland.filters import OneEuroFilter
from inputland.gestures import (
    Debounce, is_gesture, is_pinching, pick_pointer_hand,
)
from inputland.pointer import VirtualPointer
from inputland.tracking import INDEX_MCP, Hand, HandTracker, ensure_model

log = logging.getLogger(__name__)

PREVIEW_WINDOW = "inputland preview"


@dataclass(frozen=True)
class Status:
    """What the loop sees, for the HUD."""

    driver: str | None  # side of the hand moving the cursor, None when idle
    hands: tuple[tuple[str, str], ...]  # (side, gesture), sorted
    pressed: bool = False  # the driver holds the left button (pinch: click or drag)
    right_click: str | None = None  # side holding the ✌️ that right clicked
    edge: bool = False  # cursor pinned to a screen edge: the hand is outside the region
    scrolling: str | None = None  # side whose hand scrolls (two open palms)
    copied: str | None = None  # side holding the 👍 that copied
    pasted: str | None = None  # side holding the 👎 that pasted
    zooming: str | None = None  # side of the last driver while two open palms zoom


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
        pinch = Debounce(settings.pinch_frames, settings.pinch_frames)
        victory = Debounce(settings.engage_frames, settings.release_frames)
        palms = Debounce(settings.engage_frames, settings.release_frames)
        thumb_up = Debounce(settings.engage_frames, settings.release_frames)
        thumb_down = Debounce(settings.paste_frames, settings.release_frames)
        log.info(
            "running; point with either index finger to move the cursor, pinch to click, hold the pinch to drag, "
            "raise the middle finger too to right click, thumbs up to copy, thumbs down to paste, "
            "open both palms and move the pointing hand up or down to scroll, or spread / close them to zoom"
        )
        driver: str | None = None
        # Survives a release: a slow pinch passes through unrecognized poses, then takes control back.
        last_driver: str | None = None
        last_status = None
        scroll_anchor = spread_anchor = 0.0
        palm_axis: str | None = None  # "scroll" or "zoom" once the open palms leave a dead zone
        last_frame = time.monotonic()

        for frame in camera.frames():
            if stop is not None and stop.is_set():
                break
            now = time.monotonic()
            dt, last_frame = now - last_frame, now
            hands = tracker.detect(frame, int(now * 1000))
            if not hands and not palms.state:  # a frame dropped mid-scroll keeps the scroller
                last_driver = None  # hand left the view: point again before pinching
            hand = pick_pointer_hand(hands, driver or last_driver, settings.min_gesture_score, settings.pinch_ratio)

            active = gate.update(hand is not None)
            edge = False
            if not active:
                driver = None
            elif hand is not None:
                if hand.side != driver:
                    # Engaged or switched hands: start fresh instead of gliding from the old position.
                    log.debug("cursor driven by %s hand", hand.side.lower())
                    smooth_x.reset()
                    smooth_y.reset()
                    driver = last_driver = hand.side
                    if pinch.state:  # a held button must not drop where the new hand is
                        log.debug("left button up")
                        pointer.release()
                        pinch = Debounce(settings.pinch_frames, settings.pinch_frames)
                # Base of the index finger: steadier than the fingertip, and it does not move while pinching.
                u, v = settings.region.normalize(*hand.landmarks[INDEX_MCP])
                edge = u in (0.0, 1.0) or v in (0.0, 1.0)  # normalize clamps to the edges
                pointer.move_to(smooth_x(u, now), smooth_y(v, now))

            # Only the driver's pinch holds the left button: down on close, up on open, so a quick pinch clicks.
            # A hand lost for a few frames (motion blur) keeps the button until the cursor lets go too.
            was_pinching = pinch.state
            if hand is None:
                pinching = driver is not None and was_pinching
            else:
                pinching = driver is not None and is_pinching(hand, settings.pinch_ratio)
            if pinch.update(pinching) != was_pinching:
                log.debug("left button %s", "up" if was_pinching else "down")
                if was_pinching:
                    pointer.release()
                else:
                    pointer.press()

            # ✌️ / 👍 / 👎 by the last driver fire once each; it no longer points, so the cursor stays where it aimed.
            owner = driver or last_driver
            owned = [h for h in hands if h.side == owner]
            if _started(victory, any(is_gesture(h, "Victory", settings.min_gesture_score) for h in owned)):
                log.debug("right click")
                pointer.right_click()
            if _started(thumb_up, any(is_gesture(h, "Thumb_Up", settings.min_gesture_score) for h in owned)):
                log.debug("copy")
                pointer.copy()
            if _started(thumb_down, any(is_gesture(h, "Thumb_Down", settings.min_gesture_score) for h in owned)):
                log.debug("paste")
                pointer.paste()

            # Two open palms, joystick style: the last driver's hand, above where the palms opened, scrolls up;
            # palms spread apart zoom in. Axis lock: the first to leave its dead zone owns it until the palms close.
            mover = next(iter(owned), None)
            both_palms = (
                mover is not None and len(hands) == 2
                and all(is_gesture(h, "Open_Palm", settings.min_gesture_score) for h in hands)
            )
            was_palms = palms.state
            if palms.update(both_palms) and both_palms:
                y, spread = mover.landmarks[INDEX_MCP][1], _spread(hands)
                if not was_palms:
                    log.debug("palms open")
                    scroll_anchor, spread_anchor, palm_axis = y, spread, None
                scroll = _excess(scroll_anchor - y, settings.scroll_dead_zone)  # image y grows downward
                zoom = _excess(math.log(spread / spread_anchor), settings.zoom_dead_zone)
                if palm_axis is None and (scroll or zoom):
                    palm_axis = "scroll" if scroll else "zoom"
                    log.debug("palms %s", palm_axis)
                if palm_axis == "scroll" and scroll:
                    pointer.scroll(scroll * settings.scroll_speed * dt)
                elif palm_axis == "zoom" and zoom:
                    pointer.zoom(zoom * settings.zoom_speed * dt)
            elif was_palms and not palms.state and palm_axis == "zoom":
                pointer.stop_zoom()

            status = Status(
                driver, tuple(sorted((h.side, h.gesture) for h in hands)),
                pinch.state, owner if victory.state else None, edge,
                owner if palms.state and palm_axis != "zoom" else None,
                owner if thumb_up.state else None, owner if thumb_down.state else None,
                owner if palms.state and palm_axis == "zoom" else None,
            )
            if status != last_status:
                on_status(status)
                last_status = status

            if settings.preview and not _show_preview(frame, hands, driver is not None, settings):
                break


def _started(debounce: Debounce, raw: bool) -> bool:
    """True on the frame `debounce` turns on."""
    was = debounce.state
    return debounce.update(raw) and not was


def _excess(offset: float, dead_zone: float) -> float:
    """How far `offset` goes past `dead_zone`, keeping its sign; 0 inside it."""
    return math.copysign(max(abs(offset) - dead_zone, 0.0), offset)


def _spread(hands: list[Hand]) -> float:
    """Horizontal gap between two hands; the floor keeps the zoom ratio finite if they cross."""
    a, b = (h.landmarks[INDEX_MCP][0] for h in hands)
    return max(abs(a - b), 0.05)


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
