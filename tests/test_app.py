from contextlib import nullcontext
from pathlib import Path

import pytest
from hands import hand, pinch, point

from inputland import app
from inputland.config import Settings


@pytest.fixture
def devices(monkeypatch):
    """Fake camera, tracker and pointer. Set `.script` to the hands seen per frame; outputs land in `.events`."""

    class Fake:
        script: list = []
        events: list = []

        def frames(self):
            return iter(range(len(self.script)))

        def detect(self, frame, ts):
            return self.script[frame]

        def move_to(self, u, v):
            self.events.append((u, v))

        def double_click(self):
            self.events.append("double")

    fake = Fake()
    monkeypatch.setattr(app, "ensure_model", lambda: Path("model"))
    for name in ("Camera", "HandTracker", "VirtualPointer"):
        monkeypatch.setattr(app, name, lambda *a: nullcontext(fake))
    return fake


def test_run_engages_switches_hands_and_releases(devices):
    left, right = point("Left", 0.5, 0.45), point("Right", 0.75, 0.7)  # -> screen (0.5, 0.5) and (1, 1)
    devices.script = [[], [left], [left], [left, right], [right], [], []]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=2), statuses.append)

    # Both pointing: the left hand keeps control; a lone right hand takes over; the cursor stays through one empty frame.
    assert [s.driver for s in statuses] == [None, "Left", "Left", "Right", "Right", None]
    # The switch resets the filter, so the cursor jumps to the right hand instead of gliding from the left one.
    assert [c for m in devices.events for c in m] == pytest.approx([0.5, 0.5] * 3 + [1.0, 1.0])


def test_pinch_double_clicks_once_per_pinch(devices):
    p, o = pinch("Right", 0.5, 0.45), point("Right", 0.5, 0.45)
    # Pinch without pointing first, then point, hold a pinch, open, pinch again.
    devices.script = [[p], [o], [p], [p], [p], [o], [p]]

    app.run(Settings(engage_frames=1, release_frames=1))

    # The pinching hand keeps moving the cursor; one double click per pinch, none before the hand pointed.
    moves = [e for e in devices.events if e != "double"]
    assert len(moves) == 6
    assert [i for i, e in enumerate(devices.events) if e == "double"] == [2, 7]


def test_slow_pinch_takes_control_back_until_the_hand_leaves(devices):
    p, o, half = pinch("Right", 0.5, 0.45), point("Right", 0.5, 0.45), hand("Right", 0.5, 0.45, gesture="None")
    # Half-closed pinch drops the driver, the finished pinch still clicks; after the hand leaves it must point again.
    devices.script = [[o], [half], [p], [], [o], [], [p]]

    app.run(Settings(engage_frames=1, release_frames=1))

    assert devices.events.count("double") == 1
    assert devices.events.index("double") == 2  # move (pointing), move (pinch re-engaged), double


def test_settings_reject_filter_values_that_break_smoothing():
    with pytest.raises(ValueError):
        Settings(min_cutoff=0)
    with pytest.raises(ValueError):
        Settings(beta=-1)
    with pytest.raises(ValueError):
        Settings(pinch_ratio=0)
