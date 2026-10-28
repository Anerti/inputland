import pytest
from hands import pinch, point

from inputland.config import Region
from inputland.filters import OneEuroFilter
from inputland.gestures import Debounce, is_pinching, is_pointing, pick_pointer_hand
from inputland.tracking import Hand


def test_region_maps_box_to_screen_and_clamps():
    r = Region(0.25, 0.2, 0.75, 0.7)
    assert r.normalize(0.25, 0.2) == (0.0, 0.0)
    assert r.normalize(0.5, 0.45) == pytest.approx((0.5, 0.5))
    assert r.normalize(0.0, 1.0) == (0.0, 1.0)  # outside the box sticks to the edge


def test_region_rejects_inverted_box():
    with pytest.raises(ValueError):
        Region(0.8, 0.2, 0.2, 0.7)


def test_one_euro_holds_constant_and_converges():
    f = OneEuroFilter(min_cutoff=1.0, beta=10.0)
    assert f(0.5, 0.0) == 0.5
    assert f(0.5, 1 / 30) == 0.5
    t, x = 1 / 30, 0.5
    for _ in range(90):  # 3 s after a jump to 0.9
        t += 1 / 30
        x = f(0.9, t)
    assert x == pytest.approx(0.9, abs=1e-3)


def test_one_euro_smooths_jitter_and_resets():
    f = OneEuroFilter(min_cutoff=1.0, beta=0.0)
    out = [f(0.5 + (0.01 if i % 2 else -0.01), i / 30) for i in range(60)]
    assert max(out[30:]) - min(out[30:]) < 0.01  # input swings 0.02
    f.reset()
    assert f(0.1, 10.0) == 0.1


def test_debounce_needs_consecutive_frames():
    d = Debounce(on_frames=3, off_frames=2)
    assert [d.update(x) for x in [True, True, False, True, True, True]] == [False] * 5 + [True]
    assert [d.update(x) for x in [False, True, False, False]] == [True, True, True, False]


def test_is_pointing_checks_label_and_score():
    lm = ((0.0, 0.0),) * 21
    assert is_pointing(Hand("Right", "Pointing_Up", 0.9, lm), 0.5)
    assert not is_pointing(Hand("Right", "Pointing_Up", 0.3, lm), 0.5)
    assert not is_pointing(Hand("Right", "Open_Palm", 0.9, lm), 0.5)


def test_pick_pointer_hand_accepts_either_hand_and_keeps_the_driver():
    lm = ((0.0, 0.0),) * 21
    left, right = Hand("Left", "Pointing_Up", 0.9, lm), Hand("Right", "Pointing_Up", 0.9, lm)
    palm = Hand("Right", "Open_Palm", 0.9, lm)
    assert pick_pointer_hand([left, palm], None, 0.5, 0.35) is left
    assert pick_pointer_hand([right, left], "Left", 0.5, 0.35) is left  # both point: driver keeps control
    assert pick_pointer_hand([right, left], None, 0.5, 0.35) is right
    assert pick_pointer_hand([palm], "Right", 0.5, 0.35) is None


def test_is_pinching_scales_with_hand_size():
    assert is_pinching(pinch("Right", 0.5, 0.5), 0.35)
    assert not is_pinching(point("Right", 0.5, 0.5), 0.35)  # thumb resting on the folded fingers
    assert not is_pinching(pinch("Right", 0.5, 0.5, button="right"), 0.35)  # thumb on the middle finger


def test_only_the_driver_keeps_control_while_pinching():
    hand = pinch("Left", 0.5, 0.5)
    assert pick_pointer_hand([hand], "Left", 0.5, 0.35) is hand
    assert pick_pointer_hand([hand], None, 0.5, 0.35) is None  # must point first
    assert pick_pointer_hand([hand], "Right", 0.5, 0.35) is None
