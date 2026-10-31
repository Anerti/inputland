"""Scripted hands for the tests."""

from inputland.tracking import INDEX_TIP, MIDDLE_TIP, PINKY_TIP, THUMB_TIP, WRIST, Hand


def hand(side, x, y, gesture="Pointing_Up", pinch=None):
    """Hand of size 0.1 (wrist to middle knuckle) with the knuckles at (x, y).

    `pinch` puts the thumb tip on the "left" (index) or "right" (middle) fingertip.
    """
    lm = [(x, y)] * 21
    lm[WRIST] = (x, y + 0.1)
    lm[INDEX_TIP] = (x, y - 0.1)
    lm[MIDDLE_TIP] = (x + 0.02, y - 0.05) if pinch == "right" else (x + 0.02, y + 0.05)
    lm[THUMB_TIP] = {"left": lm[INDEX_TIP], "right": lm[MIDDLE_TIP]}.get(pinch, (x + 0.05, y + 0.05))
    return Hand(side, gesture, 0.9, tuple(lm))


def point(side, x, y):
    return hand(side, x, y)


def love(side, x, y, pinch=None):
    """Love-you sign with the pinky up too; MediaPipe usually misses it. `pinch` as in `hand`: a pinch with a loose pinky."""
    lm = list(hand(side, x, y, gesture="None", pinch=pinch).landmarks)
    lm[PINKY_TIP] = (x - 0.03, y - 0.08)
    return Hand(side, "None", 0.9, tuple(lm))


def pinch(side, x, y, button="left"):
    return hand(side, x, y, gesture="None", pinch=button)


def face(x, y):
    """Face landmarks with the nose tip at (x, y): forehead top at y - 0.15, chin at y + 0.15, 0.2 wide."""
    lm = [(x, y)] * 478
    lm[10], lm[152], lm[234], lm[454] = (x, y - 0.15), (x, y + 0.15), (x - 0.1, y), (x + 0.1, y)
    return tuple(lm)
