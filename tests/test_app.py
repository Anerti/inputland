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

        def press(self):
            self.events.append("down")

        def release(self):
            self.events.append("up")

        def right_click(self):
            self.events.append("right")

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


def test_pinch_holds_the_button_to_drag(devices):
    p, o, moved = pinch("Right", 0.5, 0.45), point("Right", 0.5, 0.45), pinch("Right", 0.75, 0.7)
    # Pinch without pointing first, then point, pinch and move, open, pinch again.
    devices.script = [[p], [o], [p], [moved], [o], [p]]

    app.run(Settings(engage_frames=1, release_frames=1, pinch_frames=1))

    # Nothing before the hand pointed; the button stays down while the pinching hand moves the cursor.
    labels = [e if isinstance(e, str) else "move" for e in devices.events]
    assert labels == ["move", "move", "down", "move", "move", "up", "move", "down"]
    assert devices.events[3] != devices.events[1]


def test_hand_leaving_mid_drag_releases_the_button(devices):
    o, p = point("Right", 0.5, 0.45), pinch("Right", 0.5, 0.45)
    devices.script = [[o], [p], [], []]

    app.run(Settings(engage_frames=1, release_frames=1, pinch_frames=1))

    assert [e for e in devices.events if isinstance(e, str)] == ["down", "up"]


def test_victory_right_clicks_once_after_pointing(devices):
    o, v = point("Right", 0.5, 0.45), hand("Right", 0.5, 0.45, gesture="Victory")
    # A ✌️ before pointing and the other hand's ✌️ do nothing; a held ✌️ clicks once.
    devices.script = [[v], [o], [hand("Left", 0.2, 0.2, gesture="Victory")], [v], [v], [o], [v]]

    app.run(Settings(engage_frames=1, release_frames=1))

    labels = [e if isinstance(e, str) else "move" for e in devices.events]
    assert labels == ["move", "right", "move", "right"]


def test_slow_pinch_takes_control_back_until_the_hand_leaves(devices):
    p, o, half = pinch("Right", 0.5, 0.45), point("Right", 0.5, 0.45), hand("Right", 0.5, 0.45, gesture="None")
    # Half-closed pinch drops the driver, the finished pinch still presses; after the hand leaves it must point again.
    devices.script = [[o], [half], [p], [], [o], [], [p]]

    app.run(Settings(engage_frames=1, release_frames=1, pinch_frames=1))

    assert devices.events.count("down") == 1
    assert devices.events.index("down") == 2  # move (pointing), move (pinch re-engaged), down


def test_quick_double_pinch_presses_twice(devices):
    o, p = point("Right", 0.5, 0.45), pinch("Right", 0.5, 0.45)
    # Opening for 2 frames is shorter than release_frames: the pinch has its own, shorter debounce.
    devices.script = [[o]] * 3 + [[p], [p], [o], [o], [p], [p]]

    app.run(Settings(engage_frames=3, release_frames=5, pinch_frames=2))

    assert [e for e in devices.events if isinstance(e, str)] == ["down", "up", "down"]


def test_status_reports_button_right_click_and_edge(devices):
    o, edge, p = point("Right", 0.5, 0.45), point("Right", 0.9, 0.45), pinch("Right", 0.5, 0.45)
    v = hand("Right", 0.5, 0.45, gesture="Victory")
    devices.script = [[o], [edge], [p], [o], [v]]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=1, pinch_frames=1), statuses.append)

    assert [(s.edge, s.pressed, s.right_click) for s in statuses] == [
        (False, False, None), (True, False, None), (False, True, None), (False, False, None), (False, False, "Right"),
    ]


def test_settings_reject_filter_values_that_break_smoothing():
    with pytest.raises(ValueError):
        Settings(min_cutoff=0)
    with pytest.raises(ValueError):
        Settings(beta=-1)
    with pytest.raises(ValueError):
        Settings(pinch_ratio=0)
