from contextlib import nullcontext
from pathlib import Path

import pytest
from hands import hand, love, pinch, point

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

        def copy(self):
            self.events.append("copy")

        def paste(self):
            self.events.append("paste")

        def close_window(self):
            self.events.append("close")

        def scroll(self, notches):
            self.events.append(("scroll", notches))

        def zoom(self, notches):
            self.events.append(("zoom", notches))

        def stop_zoom(self):
            self.events.append("unzoom")

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


def test_switching_hands_mid_drag_releases_before_moving(devices):
    o, p, other = point("Left", 0.3, 0.3), pinch("Left", 0.3, 0.3), point("Right", 0.7, 0.7)
    # The left hand drags while the right one points, then the left leaves: the drag must not end at the right hand.
    devices.script = [[o], [p, other], [other], [other]]

    app.run(Settings(engage_frames=1, release_frames=5, pinch_frames=1))

    labels = [e if isinstance(e, str) else "move" for e in devices.events]
    assert labels == ["move", "move", "down", "up", "move", "move"]


def test_drag_survives_a_short_tracking_dropout(devices):
    o, p, moved = point("Right", 0.5, 0.45), pinch("Right", 0.5, 0.45), pinch("Right", 0.75, 0.7)
    devices.script = [[o], [p], [p], [], [], [moved]]

    app.run(Settings(engage_frames=1, release_frames=5, pinch_frames=2))

    assert [e for e in devices.events if isinstance(e, str)] == ["down"]


def test_victory_right_clicks_once_after_pointing(devices):
    o, v = point("Right", 0.5, 0.45), hand("Right", 0.5, 0.45, gesture="Victory")
    # A ✌️ before pointing and the other hand's ✌️ do nothing; a held ✌️ clicks once.
    devices.script = [[v], [o], [hand("Left", 0.2, 0.2, gesture="Victory")], [v], [v], [o], [v]]

    app.run(Settings(engage_frames=1, release_frames=1))

    labels = [e if isinstance(e, str) else "move" for e in devices.events]
    assert labels == ["move", "right", "move", "right"]


def test_thumbs_up_copies_and_held_thumbs_down_pastes_after_pointing(devices):
    o = point("Right", 0.5, 0.45)
    up, down = hand("Right", 0.5, 0.45, gesture="Thumb_Up"), hand("Right", 0.5, 0.45, gesture="Thumb_Down")
    # A 👍 before pointing and the other hand's 👍 do nothing; a held 👍 copies once; a 1-frame 👎 is too short.
    devices.script = [[up], [o], [hand("Left", 0.2, 0.2, gesture="Thumb_Up")], [up], [up], [down], [o], [down], [down]]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=1, paste_frames=2), statuses.append)

    assert [e for e in devices.events if isinstance(e, str)] == ["copy", "paste"]
    assert [(s.copied, s.pasted) for s in statuses if s.copied or s.pasted] == [("Right", None), (None, "Right")]


def test_held_love_closes_once_after_pointing(devices):
    o, l = point("Right", 0.5, 0.45), love("Right", 0.5, 0.45)
    # A 🤟 before pointing does nothing; a 2-frame 🤟 is too short; a held one closes once.
    devices.script = [[l], [l], [l], [o], [l], [l], [o], [l], [l], [l], [l]]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=1, close_frames=3), statuses.append)

    assert [e for e in devices.events if isinstance(e, str)] == ["close"]
    assert [s.closed for s in statuses if s.closed] == ["Right"]


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


def test_two_open_palms_scroll_with_the_last_driver(devices):
    o = point("Right", 0.5, 0.45)

    def palms(y):
        return [hand("Left", 0.3, 0.45, gesture="Open_Palm"), hand("Right", 0.5, y, gesture="Open_Palm")]

    # Palms before pointing do nothing; then anchor, move up, back into the dead zone, down; one palm stops it.
    # A frame with no hands mid-scroll does not end it.
    one_palm = [palms(0.3)[1]]
    devices.script = [palms(0.3), [o], palms(0.45), palms(0.3), [], palms(0.47), palms(0.6), one_palm, one_palm]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=2, scroll_dead_zone=0.05), statuses.append)

    scrolls = [e[1] for e in devices.events if isinstance(e, tuple) and e[0] == "scroll"]
    assert [s > 0 for s in scrolls] == [True, False]  # hand up scrolls up, hand down scrolls down
    assert [s.scrolling for s in statuses] == [None, None, *["Right"] * 5, None]


def palms(left_x, right_x, y=0.45):
    return [hand("Left", left_x, y, gesture="Open_Palm"), hand("Right", right_x, y, gesture="Open_Palm")]


def _palm_events(events):
    """Scroll / zoom events as (kind, positive), plus Ctrl let go."""
    return [e if e == "unzoom" else (e[0], e[1] > 0) for e in events if e == "unzoom" or e[0] in ("scroll", "zoom")]


def test_open_palms_spread_zooms_and_lock_out_scrolling(devices):
    o = point("Right", 0.5, 0.45)
    one_palm = [palms(0.4, 0.6)[1]]
    # Anchor at a 0.2 gap, spread, then move up (locked to zoom: no scroll), close in; one palm lets Ctrl go.
    devices.script = [
        [o], palms(0.4, 0.6), palms(0.3, 0.7), palms(0.3, 0.7, y=0.2), palms(0.45, 0.55), one_palm, one_palm,
    ]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=2), statuses.append)

    assert _palm_events(devices.events) == [("zoom", True), ("zoom", True), ("zoom", False), "unzoom"]
    pairs = [(s.scrolling, s.zooming) for s in statuses if s.scrolling or s.zooming]
    assert list(dict.fromkeys(pairs)) == [("Right", None), (None, "Right")]  # undecided shows as scrolling


def test_open_palms_scrolling_first_does_not_zoom(devices):
    o = point("Right", 0.5, 0.45)
    devices.script = [[o], palms(0.4, 0.6), palms(0.4, 0.6, y=0.3), palms(0.2, 0.8, y=0.3)]

    app.run(Settings(engage_frames=1, release_frames=2))

    assert _palm_events(devices.events) == [("scroll", True), ("scroll", True)]


def test_a_fist_pauses_until_an_open_palm(devices):
    o, p = point("Right", 0.5, 0.45), pinch("Right", 0.5, 0.45)
    fist, palm = hand("Left", 0.3, 0.45, gesture="Closed_Fist"), hand("Left", 0.3, 0.45, gesture="Open_Palm")
    # The other hand's fist mid-drag lets the button go; pointing while paused does nothing; a palm resumes.
    devices.script = [[o], [p], [p, fist], [o], [palm], [o]]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=1, pinch_frames=1), statuses.append)

    labels = [e if isinstance(e, str) else "move" for e in devices.events]
    assert labels == ["move", "move", "down", "up", "move"]
    assert [s.paused for s in statuses] == [False, False, True, False, False]


def test_a_palm_resumes_while_the_other_hand_is_already_open(devices):
    lp, rf = hand("Left", 0.3, 0.45, gesture="Open_Palm"), hand("Right", 0.6, 0.45, gesture="Closed_Fist")
    rp = hand("Right", 0.6, 0.45, gesture="Open_Palm")
    devices.script = [[lp], [lp, rf], [lp, rp], [point("Right", 0.6, 0.45)]]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=1), statuses.append)

    assert [s.paused for s in statuses] == [False, True, False, False]
    assert [e for e in devices.events if not isinstance(e, str)]  # the cursor moves again


def test_closing_a_hand_to_stop_scrolling_does_not_pause(devices):
    o = point("Right", 0.6, 0.45)
    lp, rp = hand("Left", 0.3, 0.45, gesture="Open_Palm"), hand("Right", 0.6, 0.45, gesture="Open_Palm")
    devices.script = [[o], [lp, rp], [lp, rp], [lp, hand("Right", 0.6, 0.45, gesture="Closed_Fist")], [o]]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=1), statuses.append)

    assert not any(s.paused for s in statuses)
    assert statuses[-1].driver == "Right"


def test_settings_reject_filter_values_that_break_smoothing():
    with pytest.raises(ValueError):
        Settings(min_cutoff=0)
    with pytest.raises(ValueError):
        Settings(beta=-1)
    with pytest.raises(ValueError):
        Settings(pinch_ratio=0)
    with pytest.raises(ValueError):
        Settings(scroll_speed=0)
    with pytest.raises(ValueError):
        Settings(zoom_dead_zone=1)
