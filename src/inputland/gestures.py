from math import dist, inf

from inputland.tracking import (
    INDEX_PIP, INDEX_TIP, MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP, PINKY_PIP, PINKY_TIP, RING_PIP, RING_TIP, THUMB_TIP,
    WRIST, Face, Hand,
)


def is_gesture(hand: Hand, gesture: str, min_score: float) -> bool:
    """MediaPipe recognized `gesture` (e.g. "Pointing_Up", "Victory", "Open_Palm") with at least `min_score`."""
    return hand.gesture == gesture and hand.score >= min_score


def pinch_ratio(hand: Hand) -> float:
    """Thumb tip to index tip distance over the hand size (wrist to middle knuckle); inf for a hand of no size."""
    lm = hand.landmarks
    size = dist(lm[WRIST], lm[MIDDLE_MCP])
    return dist(lm[THUMB_TIP], lm[INDEX_TIP]) / size if size else inf


def is_pinching(hand: Hand, ratio: float) -> bool:
    """Thumb tip on the index tip: `pinch_ratio` under `ratio`."""
    return pinch_ratio(hand) < ratio


def is_love_sign(hand: Hand) -> bool:
    """Love-you sign (or horns): index and pinky up, middle and ring folded; the thumb is ignored.

    From the landmarks: MediaPipe's own `ILoveYou` label rarely fires. Never a `Pointing_Up` hand, whose relaxed
    pinky can read as up: holding it would close the window while moving the cursor.
    """
    if hand.gesture == "Pointing_Up":
        return False
    lm = hand.landmarks

    def up(tip: int, pip: int) -> bool:
        return dist(lm[tip], lm[WRIST]) > dist(lm[pip], lm[WRIST])

    return up(INDEX_TIP, INDEX_PIP) and up(PINKY_TIP, PINKY_PIP) and not (
        up(MIDDLE_TIP, MIDDLE_PIP) or up(RING_TIP, RING_PIP)
    )


def touches_head(hand: Hand, face: Face) -> bool:
    """Index tip on the forehead: within the face's width, from above the top of the face down to the eyebrows.

    The hand must also be about as far from the camera as the face: a hand pointing at the top of the screen
    covers the forehead in the image too, but from in front of it, so it looks bigger.
    """
    xs, ys = zip(*face)
    top, height = min(ys), max(ys) - min(ys)
    lm = hand.landmarks
    x, y = lm[INDEX_TIP]
    near_face = dist(lm[WRIST], lm[MIDDLE_MCP]) < 0.9 * (max(xs) - min(xs))
    return near_face and min(xs) <= x <= max(xs) and top - height / 3 <= y <= top + height / 3


def is_triangle(hands: list[Hand], ratio: float) -> bool:
    """Two hands making a triangle: index tips together, thumb tips together, each hand's own thumb and index apart.

    Together: closer than `ratio` hand sizes, the pinch threshold. Apart: not pinching, so two pinches touching are not
    a triangle; the wrists apart too, so one hand MediaPipe reports twice is not either.
    """
    if len(hands) != 2:
        return False
    a, b = (h.landmarks for h in hands)
    size = (dist(a[WRIST], a[MIDDLE_MCP]) + dist(b[WRIST], b[MIDDLE_MCP])) / 2
    return (
        dist(a[INDEX_TIP], b[INDEX_TIP]) < ratio * size and dist(a[THUMB_TIP], b[THUMB_TIP]) < ratio * size
        and dist(a[WRIST], b[WRIST]) > size and not any(is_pinching(h, ratio) for h in hands)
    )


def find_grabber(hands: list[Hand], min_score: float, pinch_ratio: float) -> Hand | None:
    """The pinching hand while the other hand holds an open palm (the volume / brightness slider), else None.

    The palm must not pinch too: a pinch with the other fingers up can read as `Open_Palm`.
    """
    if len(hands) != 2:
        return None
    return next((
        grab for grab, palm in (hands, hands[::-1])
        if is_pinching(grab, pinch_ratio) and is_gesture(palm, "Open_Palm", min_score)
        and not is_pinching(palm, pinch_ratio)
    ), None)


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

    def pending(self, frames: int) -> bool:
        """Turning True: at least `frames` consecutive True inputs so far, not yet `on_frames`."""
        return not self.state and self._streak >= frames

    def progress(self) -> float:
        """How far it is to turning True, 0..1: the consecutive True inputs so far over `on_frames`."""
        return 0.0 if self.state else self._streak / self.on_frames
