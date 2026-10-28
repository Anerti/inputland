from math import dist

from inputland.tracking import (
    INDEX_PIP, INDEX_TIP, MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP, PINKY_PIP, PINKY_TIP, RING_PIP, RING_TIP, THUMB_TIP,
    WRIST, Hand,
)


def is_gesture(hand: Hand, gesture: str, min_score: float) -> bool:
    """MediaPipe recognized `gesture` (e.g. "Pointing_Up", "Victory", "Open_Palm") with at least `min_score`."""
    return hand.gesture == gesture and hand.score >= min_score


def is_pinching(hand: Hand, ratio: float) -> bool:
    """Thumb tip on the index tip, closer than `ratio` x the hand size (wrist to middle knuckle)."""
    lm = hand.landmarks
    return dist(lm[THUMB_TIP], lm[INDEX_TIP]) < ratio * dist(lm[WRIST], lm[MIDDLE_MCP])


def is_love_sign(hand: Hand) -> bool:
    """🤟 (or 🤘): index and pinky up, middle and ring folded; the thumb is ignored.

    From the landmarks: MediaPipe's own `ILoveYou` label rarely fires. Never a `Pointing_Up` hand, whose relaxed
    pinky can read as up: holding it would close the window while moving the cursor.
    """
    if hand.gesture == "Pointing_Up":
        return False
    lm = hand.landmarks

    def up(tip: int, pip: int) -> bool:  # a folded fingertip curls back nearer the wrist than its middle joint
        return dist(lm[tip], lm[WRIST]) > dist(lm[pip], lm[WRIST])

    return up(INDEX_TIP, INDEX_PIP) and up(PINKY_TIP, PINKY_PIP) and not (
        up(MIDDLE_TIP, MIDDLE_PIP) or up(RING_TIP, RING_PIP)
    )


def pick_pointer_hand(hands: list[Hand], driver: str | None, min_score: float, pinch_ratio: float) -> Hand | None:
    """The pointing hand that moves the cursor. If both point, the current `driver` side keeps control.

    A pinching driver keeps control too: MediaPipe stops calling it `Pointing_Up`.
    """
    pointing = [
        h for h in hands
        if is_gesture(h, "Pointing_Up", min_score) or (h.side == driver and is_pinching(h, pinch_ratio))
    ]
    return next((h for h in pointing if h.side == driver), pointing[0] if pointing else None)


class Debounce:
    """Turns a flickering per-frame bool into a stable one.

    Goes True after `on_frames` consecutive True inputs, False after
    `off_frames` consecutive False inputs.
    """

    def __init__(self, on_frames: int, off_frames: int) -> None:
        self.on_frames = on_frames
        self.off_frames = off_frames
        self.state = False
        self._streak = 0

    def update(self, raw: bool) -> bool:
        if raw == self.state:
            self._streak = 0
            return self.state
        self._streak += 1
        if self._streak >= (self.on_frames if raw else self.off_frames):
            self.state, self._streak = raw, 0
        return self.state
