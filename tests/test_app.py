from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from hands import face, hand, love, pinch, point

from inputland import app
from inputland.config import Settings


@pytest.fixture
def devices(monkeypatch):
    """Fake camera, trackers and pointer. Set `.script` to the hands seen per frame (`.faces`: the face, if any);
    outputs land in `.events`, the frames the face was looked for in `.face_frames`."""

    class Fake:
        script: list = []
        faces: list = []
        face_frames: list = []
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

        def switch_workspace(self, step):
            self.events.append(("workspace", step))

        def scroll(self, notches):
            self.events.append(("scroll", notches))

        def zoom(self, notches):
            self.events.append(("zoom", notches))

        def stop_zoom(self):
            self.events.append("unzoom")

    fake = Fake()
    monkeypatch.setattr(app, "ensure_model", lambda *a: Path("model"))
    for name in ("Camera", "HandTracker", "VirtualPointer"):
        monkeypatch.setattr(app, name, lambda *a: nullcontext(fake))
    def detect_face(frame, ts):
        fake.face_frames.append(frame)
        return fake.faces[frame] if fake.faces else None

    monkeypatch.setattr(app, "FaceTracker", lambda *a: nullcontext(SimpleNamespace(detect=detect_face)))
    return fake


def test_run_engages_switches_hands_and_releases(devices):
    left, right = point("Left", 0.5, 0.45), point("Right", 0.75, 0.7)
    devices.script = [[], [left], [left], [left, right], [right], [], []]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=2), statuses.append)

    assert [s.driver for s in statuses] == [None, "Left", "Left", "Right", "Right", None]
    assert [c for m in devices.events for c in m] == pytest.approx([0.5, 0.5] * 3 + [1.0, 1.0])


def test_pinch_holds_the_button_to_drag(devices):
    p, o, moved = pinch("Right", 0.5, 0.45), point("Right", 0.5, 0.45), pinch("Right", 0.75, 0.7)
    devices.script = [[p], [o], [p], [moved], [o], [p]]

    app.run(Settings(engage_frames=1, release_frames=1, pinch_frames=1))

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
    devices.script = [[v], [o], [hand("Left", 0.2, 0.2, gesture="Victory")], [v], [v], [o], [v]]

    app.run(Settings(engage_frames=1, release_frames=1))

    labels = [e if isinstance(e, str) else "move" for e in devices.events]
    assert labels == ["move", "right", "move", "right"]


def test_thumbs_up_copies_and_held_thumbs_down_pastes_after_pointing(devices):
    o = point("Right", 0.5, 0.45)
    up, down = hand("Right", 0.5, 0.45, gesture="Thumb_Up"), hand("Right", 0.5, 0.45, gesture="Thumb_Down")
    devices.script = [[up], [o], [hand("Left", 0.2, 0.2, gesture="Thumb_Up")], [up], [up], [down], [o], [down], [down]]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=1, paste_frames=2), statuses.append)

    assert [e for e in devices.events if isinstance(e, str)] == ["copy", "paste"]
    assert [s.action for s in statuses if s.action] == [("Right", "Copy"), ("Right", "Paste")]


def test_held_love_closes_once_after_pointing(devices):
    o, l = point("Right", 0.5, 0.45), love("Right", 0.5, 0.45)
    devices.script = [[l], [l], [l], [o], [l], [l], [o], [l], [l], [l], [l]]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=1, close_frames=3), statuses.append)

    assert [e for e in devices.events if isinstance(e, str)] == ["close"]
    assert [s.action for s in statuses if s.action] == [("Right", "Close")]


def test_long_drag_with_a_loose_pinky_does_not_close_the_window(devices):
    devices.script = [[point("Right", 0.5, 0.45)]] + [[love("Right", 0.5, 0.45, pinch="left")]] * 5

    app.run(Settings(engage_frames=1, release_frames=1, pinch_frames=1, close_frames=3))

    assert [e for e in devices.events if isinstance(e, str)] == ["down"]


def test_one_open_palm_swipe_switches_workspace_after_pointing(devices):
    def palm(x):
        return [hand("Right", x, 0.45, gesture="Open_Palm")]

    other = hand("Left", 0.2, 0.45, gesture="None")
    devices.script = [
        palm(0.6), palm(0.3), [point("Right", 0.5, 0.45)], palm(0.6), palm(0.3), palm(0.3), palm(0.6),
        palm(0.6), palm(0.5), palm(0.4), palm(0.3), palm(0.7), *[palms(0.4, 0.6), palms(0.4, 0.9)] * 3,
        *[[other, *palm(0.4)], [other, *palm(0.9)]] * 3,
    ]

    app.run(Settings(engage_frames=1, release_frames=1, swipe_frames=3, swipe_cooldown_frames=3))

    assert [e for e in devices.events if isinstance(e, tuple) and e[0] == "workspace"] == [
        ("workspace", 1), ("workspace", -1),
    ]


def test_switching_hands_is_not_a_swipe(devices):
    devices.script = [
        [point("Right", 0.7, 0.45)], [hand("Right", 0.7, 0.45, gesture="Open_Palm")],
        [point("Left", 0.3, 0.45)], [hand("Left", 0.3, 0.45, gesture="Open_Palm")],
    ]

    app.run(Settings(engage_frames=1, release_frames=1))

    assert not [e for e in devices.events if isinstance(e, tuple) and e[0] == "workspace"]


def test_slow_pinch_takes_control_back_until_the_hand_leaves(devices):
    p, o, half = pinch("Right", 0.5, 0.45), point("Right", 0.5, 0.45), hand("Right", 0.5, 0.45, gesture="None")
    devices.script = [[o], [half], [p], [], [o], [], [p]]

    app.run(Settings(engage_frames=1, release_frames=1, pinch_frames=1))

    assert devices.events.count("down") == 1
    assert devices.events.index("down") == 2


@pytest.mark.parametrize("gap", ["Pointing_Up", "None"])
def test_quick_double_pinch_presses_twice(devices, gap):
    o, p, opened = point("Right", 0.5, 0.45), pinch("Right", 0.5, 0.45), hand("Right", 0.5, 0.45, gesture=gap)
    devices.script = [[o]] * 3 + [[p], [p], [opened], [opened], [p], [p]]

    app.run(Settings(engage_frames=3, release_frames=5, pinch_frames=2))

    assert [e for e in devices.events if isinstance(e, str)] == ["down", "up", "down"]


def test_status_reports_button_right_click_and_edge(devices):
    o, edge, p = point("Right", 0.5, 0.45), point("Right", 0.9, 0.45), pinch("Right", 0.5, 0.45)
    v = hand("Right", 0.5, 0.45, gesture="Victory")
    devices.script = [[o], [edge], [p], [o], [v]]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=1, pinch_frames=1), statuses.append)

    assert [(s.edge, s.pressed, s.action) for s in statuses] == [
        (False, False, None), (True, False, None), (False, True, None), (False, False, None),
        (False, False, ("Right", "Right click")),
    ]


def test_two_open_palms_scroll_with_the_last_driver(devices):
    o = point("Right", 0.5, 0.45)

    def palms(y):
        return [hand("Left", 0.3, 0.45, gesture="Open_Palm"), hand("Right", 0.5, y, gesture="Open_Palm")]

    one_palm = [palms(0.3)[1]]
    devices.script = [palms(0.3), [o], palms(0.45), palms(0.3), [], palms(0.47), palms(0.6), one_palm, one_palm]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=2, scroll_dead_zone=0.05), statuses.append)

    scrolls = [e[1] for e in devices.events if isinstance(e, tuple) and e[0] == "scroll"]
    assert [s > 0 for s in scrolls] == [True, False]
    assert [s.scrolling for s in statuses] == [None, None, *["Right"] * 5, None]


def palms(left_x, right_x, y=0.45):
    return [hand("Left", left_x, y, gesture="Open_Palm"), hand("Right", right_x, y, gesture="Open_Palm")]


def _palm_events(events):
    """Scroll / zoom events as (kind, positive), plus Ctrl let go."""
    return [e if e == "unzoom" else (e[0], e[1] > 0) for e in events if e == "unzoom" or e[0] in ("scroll", "zoom")]


def test_open_palms_spread_zooms_and_lock_out_scrolling(devices):
    o = point("Right", 0.5, 0.45)
    one_palm = [palms(0.4, 0.6)[1]]
    devices.script = [
        [o], palms(0.4, 0.6), palms(0.3, 0.7), palms(0.3, 0.7, y=0.2), palms(0.45, 0.55), one_palm, one_palm,
    ]

    statuses = []
    app.run(Settings(engage_frames=1, release_frames=2), statuses.append)

    assert _palm_events(devices.events) == [("zoom", True), ("zoom", True), ("zoom", False), "unzoom"]
    pairs = [(s.scrolling, s.zooming) for s in statuses if s.scrolling or s.zooming]
    assert list(dict.fromkeys(pairs)) == [("Right", None), (None, "Right")]


def test_open_palms_scrolling_first_does_not_zoom(devices):
    o = point("Right", 0.5, 0.45)
    devices.script = [[o], palms(0.4, 0.6), palms(0.4, 0.6, y=0.3), palms(0.2, 0.8, y=0.3)]

    app.run(Settings(engage_frames=1, release_frames=2))

    assert _palm_events(devices.events) == [("scroll", True), ("scroll", True)]


def test_a_fist_pauses_until_an_open_palm(devices):
    o, p = point("Right", 0.5, 0.45), pinch("Right", 0.5, 0.45)
    fist, palm = hand("Left", 0.3, 0.45, gesture="Closed_Fist"), hand("Left", 0.3, 0.45, gesture="Open_Palm")
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
    assert [e for e in devices.events if not isinstance(e, str)]


@pytest.mark.parametrize("unnamed", [0, 3])
def test_closing_a_hand_to_stop_scrolling_does_not_pause(devices, unnamed):
    o = point("Right", 0.6, 0.45)
    lp, rp = hand("Left", 0.3, 0.45, gesture="Open_Palm"), hand("Right", 0.6, 0.45, gesture="Open_Palm")
    closing, fist = (hand("Right", 0.6, 0.45, gesture=g) for g in ("None", "Closed_Fist"))
    devices.script = [[o], [lp, rp], [lp, rp], *[[lp, closing]] * unnamed, [lp, fist], [o]]

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


def test_touching_the_forehead_toggles_head_pointing(devices):
    still, turned = face(0.5, 0.3), face(0.6, 0.3)
    touch, low = point("Right", 0.5, 0.25), pinch("Right", 0.3, 0.6)
    devices.script = [[touch], [touch], [low], [], [touch], [touch]]
    devices.faces = [still, still, turned, turned, still, still]

    statuses = []
    settings = Settings(head_touch_frames=2, head_range=0.2, engage_frames=1, release_frames=1, pinch_frames=1)
    app.run(settings, statuses.append)

    labels = [e if isinstance(e, str) else "move" for e in devices.events]
    assert labels == ["move", "move", "move", "down", "move", "up", "move", "move"]
    assert devices.events[0] == pytest.approx((0.5, 0.1))
    assert devices.events[1] == pytest.approx((0.5, 0.5))
    assert devices.events[2][0] > 0.5
    assert devices.events[-1] == pytest.approx((0.5, 0.1))
    assert [s.head for s in statuses] == [False, True, True, True, True, False]


def test_face_is_checked_every_third_frame_with_a_hand_until_head_pointing(devices):
    touch = point("Right", 0.5, 0.25)
    devices.script = [[]] * 3 + [[touch]] * 4 + [[]] * 3
    devices.faces = [face(0.5, 0.3)] * 10

    app.run(Settings(head_touch_frames=2, engage_frames=1, release_frames=1))

    assert devices.face_frames == [3, 5, 6, 7, 8, 9]
