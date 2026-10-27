from inputland.tracking import Hand


def is_pointing(hand: Hand, min_score: float) -> bool:
    return hand.gesture == "Pointing_Up" and hand.score >= min_score


def pick_pointer_hand(hands: list[Hand], driver: str | None, min_score: float) -> Hand | None:
    """The pointing hand that moves the cursor. If both point, the current `driver` side keeps control."""
    pointing = [h for h in hands if is_pointing(h, min_score)]
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
