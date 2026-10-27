from contextlib import nullcontext
from pathlib import Path

import pytest

from inputland import app
from inputland.config import Settings
from inputland.tracking import Hand


def point(side, x, y):
    return Hand(side, "Pointing_Up", 0.9, ((x, y),) * 21)


def test_run_engages_switches_hands_and_releases(monkeypatch):
    left, right = point("Left", 0.5, 0.45), point("Right", 0.75, 0.7)  # -> screen (0.5, 0.5) and (1, 1)
    script = iter([[], [left], [left], [left, right], [right], [], []])
    moves = []

    class Fake:
        def frames(self):
            return iter(range(7))

        def detect(self, frame, ts):
            return next(script)

        def move_to(self, u, v):
            moves.append((u, v))

    monkeypatch.setattr(app, "ensure_model", lambda: Path("model"))
    for name in ("Camera", "HandTracker", "VirtualPointer"):
        monkeypatch.setattr(app, name, lambda *a: nullcontext(Fake()))

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=2), statuses.append)

    # Both pointing: the left hand keeps control; a lone right hand takes over; the cursor stays through one empty frame.
    assert [s.driver for s in statuses] == [None, "Left", "Left", "Right", "Right", None]
    # The switch resets the filter, so the cursor jumps to the right hand instead of gliding from the left one.
    assert [c for m in moves for c in m] == pytest.approx([0.5, 0.5] * 3 + [1.0, 1.0])


def test_settings_reject_filter_values_that_break_smoothing():
    with pytest.raises(ValueError):
        Settings(min_cutoff=0)
    with pytest.raises(ValueError):
        Settings(beta=-1)
