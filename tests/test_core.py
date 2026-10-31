from pathlib import Path

import pytest
from hands import face, hand, love, pinch, point

from inputland.config import Region
from inputland.filters import OneEuroFilter
from inputland.gestures import Debounce, is_gesture, is_love_sign, is_pinching, pick_pointer_hand, touches_head
from inputland.tracking import WRIST, Hand


def test_region_maps_box_to_screen_and_clamps():
    r = Region(0.25, 0.2, 0.75, 0.7)
    assert r.normalize(0.25, 0.2) == (0.0, 0.0)
    assert r.normalize(0.5, 0.45) == pytest.approx((0.5, 0.5))
    assert r.normalize(0.0, 1.0) == (0.0, 1.0)


def test_region_rejects_inverted_box():
    with pytest.raises(ValueError):
        Region(0.8, 0.2, 0.2, 0.7)


def test_one_euro_holds_constant_and_converges():
    f = OneEuroFilter(min_cutoff=1.0, beta=10.0)
    assert f(0.5, 0.0) == 0.5
    assert f(0.5, 1 / 30) == 0.5
    t, x = 1 / 30, 0.5
    for _ in range(90):
        t += 1 / 30
        x = f(0.9, t)
    assert x == pytest.approx(0.9, abs=1e-3)


def test_one_euro_smooths_jitter_and_resets():
    f = OneEuroFilter(min_cutoff=1.0, beta=0.0)
    out = [f(0.5 + (0.01 if i % 2 else -0.01), i / 30) for i in range(60)]
    assert max(out[30:]) - min(out[30:]) < 0.01
    f.reset()
    assert f(0.1, 10.0) == 0.1


def test_debounce_needs_consecutive_frames():
    d = Debounce(on_frames=3, off_frames=2)
    assert [d.update(x) for x in [True, True, False, True, True, True]] == [False] * 5 + [True]
    assert [d.update(x) for x in [False, True, False, False]] == [True, True, True, False]


def test_is_gesture_checks_label_and_score():
    lm = ((0.0, 0.0),) * 21
    assert is_gesture(Hand("Right", "Pointing_Up", 0.9, lm), "Pointing_Up", 0.5)
    assert not is_gesture(Hand("Right", "Pointing_Up", 0.3, lm), "Pointing_Up", 0.5)
    assert not is_gesture(Hand("Right", "Open_Palm", 0.9, lm), "Pointing_Up", 0.5)


def test_pick_pointer_hand_accepts_either_hand_and_keeps_the_driver():
    lm = ((0.0, 0.0),) * 21
    left, right = Hand("Left", "Pointing_Up", 0.9, lm), Hand("Right", "Pointing_Up", 0.9, lm)
    palm = Hand("Right", "Open_Palm", 0.9, lm)
    assert pick_pointer_hand([left, palm], None, 0.5, 0.35) is left
    assert pick_pointer_hand([right, left], "Left", 0.5, 0.35) is left
    assert pick_pointer_hand([right, left], None, 0.5, 0.35) is right
    assert pick_pointer_hand([palm], "Right", 0.5, 0.35) is None


def test_is_pinching_scales_with_hand_size():
    assert is_pinching(pinch("Right", 0.5, 0.5), 0.35)
    assert not is_pinching(point("Right", 0.5, 0.5), 0.35)
    assert not is_pinching(pinch("Right", 0.5, 0.5, button="right"), 0.35)


def test_love_sign_needs_index_and_pinky_up_middle_and_ring_folded():
    assert is_love_sign(love("Right", 0.5, 0.5))
    assert not is_love_sign(point("Right", 0.5, 0.5))
    assert not is_love_sign(hand("Right", 0.5, 0.5, pinch="right"))
    assert not is_love_sign(Hand("Right", "Pointing_Up", 0.9, love("Right", 0.5, 0.5).landmarks))


def test_only_the_driver_keeps_control_while_pinching():
    hand = pinch("Left", 0.5, 0.5)
    assert pick_pointer_hand([hand], "Left", 0.5, 0.35) is hand
    assert pick_pointer_hand([hand], None, 0.5, 0.35) is None
    assert pick_pointer_hand([hand], "Right", 0.5, 0.35) is None


def test_tracker_falls_back_to_cpu_without_gpu(monkeypatch):
    from inputland import tracking

    tried = []

    def create(options):
        tried.append(options.base_options.delegate)
        if options.base_options.delegate == tracking.BaseOptions.Delegate.GPU:
            raise RuntimeError('Service "kGpuService" ... unavailable')
        return "cpu recognizer"

    monkeypatch.setattr(tracking.vision.GestureRecognizer, "create_from_options", create)
    tracker = tracking.HandTracker(Path("model"))
    assert tried == [tracking.BaseOptions.Delegate.GPU, tracking.BaseOptions.Delegate.CPU]
    assert tracker._task == "cpu recognizer"


def test_tracker_swaps_sides_and_forces_increasing_timestamps(monkeypatch):
    from types import SimpleNamespace as NS

    import numpy as np

    from inputland import tracking

    seen = []
    xs = [0.5]

    class Recognizer:
        def recognize_for_video(self, image, ts):
            seen.append(ts)
            return NS(
                handedness=[[NS(category_name="Left")]] * len(xs),
                gestures=[[NS(category_name="Pointing_Up", score=0.9)]] * len(xs),
                hand_landmarks=[[NS(x=x, y=0.5)] * 21 for x in xs],
            )

    monkeypatch.setattr(tracking.vision.GestureRecognizer, "create_from_options", lambda options: Recognizer())
    tracker = tracking.HandTracker(Path("model"))
    frame = np.zeros((4, 4, 3), np.uint8)
    [hand] = tracker.detect(frame, 100)
    tracker.detect(frame, 100)
    assert hand.side == "Right"
    assert seen == [100, 101]

    xs[:] = [0.7, 0.2]
    assert [(h.side, h.landmarks[0][0]) for h in tracker.detect(frame, 200)] == [("Left", 0.2), ("Right", 0.7)]


def test_pointer_without_uinput_access_points_to_the_readme(monkeypatch):
    from inputland import pointer

    def denied(*a, **kw):
        raise pointer.UInputError('"/dev/uinput" cannot be opened for writing')

    monkeypatch.setattr(pointer, "UInput", denied)
    with pytest.raises(RuntimeError, match="Permissions"):
        pointer.VirtualPointer()


@pytest.fixture
def uinput(monkeypatch):
    """Real `VirtualPointer` on a fake device; `.writes` collects (code, value)."""
    from inputland import pointer

    writes = []

    class Device:
        def __init__(self, *a, **kw): ...
        def write(self, type, code, value): writes.append((code, value))
        def syn(self): ...
        def close(self): ...

    monkeypatch.setattr(pointer, "UInput", Device)
    p = pointer.VirtualPointer()
    p.writes = writes
    return p


def test_pointer_scroll_adds_up_fractions_into_hi_res_and_notches(uinput):
    from inputland.pointer import ecodes

    for notches in (0.004, 0.5, 0.6, -0.3):
        uinput.scroll(notches)

    hi = ecodes.REL_WHEEL_HI_RES
    assert uinput.writes == [(hi, 60), (hi, 72), (ecodes.REL_WHEEL, 1), (hi, -35)]


def test_pointer_close_lets_go_of_button_and_ctrl(uinput):
    from inputland.pointer import ecodes

    uinput.press()
    uinput.zoom(1)
    uinput.close()

    assert {(ecodes.BTN_LEFT, 0), (ecodes.KEY_LEFTCTRL, 0)} <= set(uinput.writes[-2:])


def test_pointer_clicks_and_keys_let_go_of_zoom_ctrl_first(uinput):
    from inputland.pointer import ecodes

    for action, first in ((uinput.press, ecodes.BTN_LEFT), (uinput.right_click, ecodes.BTN_RIGHT),
                          (uinput.copy, ecodes.KEY_LEFTCTRL), (uinput.paste, ecodes.KEY_LEFTSHIFT)):
        uinput.zoom(1)
        uinput.writes.clear()
        action()
        uinput.release()
        assert uinput.writes[:2] == [(ecodes.KEY_LEFTCTRL, 0), (first, 1)], action.__name__


@pytest.mark.parametrize(
    ("lua", "tried"), [(True, ["hl.dsp.window.close()"]), (False, ["hl.dsp.window.close()", "killactive"])],
)
def test_pointer_close_window_on_hyprland_falls_back_to_killactive(uinput, monkeypatch, lua, tried):
    import subprocess

    from inputland import pointer

    calls = []

    def hyprctl(args, **kw):
        calls.append(args[-1])
        ok = args[-1] == "killactive" or lua
        return subprocess.CompletedProcess(args, 0, "ok" if ok else "Invalid dispatcher", "")

    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "x")
    monkeypatch.setattr(pointer.subprocess, "run", hyprctl)
    uinput.close_window()
    assert calls == tried and uinput.writes == []


def test_pointer_close_window_survives_missing_hyprctl(uinput, monkeypatch):
    from inputland import pointer

    def missing(*a, **kw):
        raise FileNotFoundError("hyprctl")

    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "x")
    monkeypatch.setattr(pointer.subprocess, "run", missing)
    uinput.close_window()
    assert uinput.writes == []


@pytest.mark.parametrize(("display", "closes"), [("wayland-1", True), (None, False)])
def test_pointer_close_window_sends_alt_f4_only_in_a_graphical_session(uinput, monkeypatch, display, closes):
    from inputland.pointer import ecodes

    for name in ("HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    if display:
        monkeypatch.setenv("WAYLAND_DISPLAY", display)
    uinput.close_window()
    assert (uinput.writes[:1] == [(ecodes.KEY_LEFTALT, 1)]) is closes


def test_pointer_zoom_does_not_inherit_scroll_leftovers(uinput):
    from inputland.pointer import ecodes

    uinput.scroll(100 / 120)
    uinput.zoom(20 / 120)
    uinput.stop_zoom()
    uinput.scroll(20 / 120)

    assert (ecodes.REL_WHEEL, 1) not in uinput.writes


def test_model_download_with_bad_checksum_is_not_cached(monkeypatch, tmp_path):
    import io

    from inputland import tracking

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(tracking.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"<html>login</html>"))
    with pytest.raises(RuntimeError, match="checksum"):
        tracking.ensure_model(tracking.MODEL_URL, tracking.MODEL_SHA256)
    assert not list((tmp_path / "inputland").iterdir())

    digest = tracking.hashlib.sha256(b"<html>login</html>").hexdigest()
    assert tracking.ensure_model(tracking.MODEL_URL, digest).read_bytes() == b"<html>login</html>"


def test_cached_model_is_downloaded_again_when_its_checksum_changes(monkeypatch, tmp_path):
    import io

    from inputland import tracking

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    (tmp_path / "inputland").mkdir()
    (tmp_path / "inputland/gesture_recognizer.task").write_bytes(b"old model")
    digest = tracking.hashlib.sha256(b"new model").hexdigest()
    monkeypatch.setattr(tracking.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"new model"))
    assert tracking.ensure_model(tracking.MODEL_URL, digest).read_bytes() == b"new model"

    def offline(url, timeout):
        raise OSError("offline")

    monkeypatch.setattr(tracking.urllib.request, "urlopen", offline)
    assert tracking.ensure_model(tracking.MODEL_URL, digest).read_bytes() == b"new model"


def test_index_tip_on_the_forehead_touches_the_head():
    head = face(0.5, 0.3)
    assert touches_head(point("Right", 0.5, 0.25), head)
    assert not touches_head(point("Right", 0.5, 0.4), head)
    assert not touches_head(point("Right", 0.5, 0.6), head)
    assert not touches_head(point("Right", 0.75, 0.25), head)
    near = list(point("Right", 0.5, 0.25).landmarks)
    near[WRIST] = (0.5, 0.45)
    assert not touches_head(Hand("Right", "Pointing_Up", 0.9, tuple(near)), head)


def test_face_model_is_cached_next_to_the_hand_model(monkeypatch, tmp_path):
    import io

    from inputland import tracking

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(tracking.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"face model"))
    digest = tracking.hashlib.sha256(b"face model").hexdigest()

    path = tracking.ensure_model(tracking.FACE_MODEL_URL, digest)

    assert path.name == "face_landmarker.task" and path.read_bytes() == b"face model"
