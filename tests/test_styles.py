import pytest

from inputland import styles
from inputland.app import BANNERS, TEXTS, Status

cairo = pytest.importorskip("cairo")

COLORS = styles.Colors(bg=(0.1, 0.1, 0.1), fg=(0.9, 0.9, 0.9), active=(0.0, 0.6, 1.0), on_active=(0.0, 0.0, 0.0))
DRAWN = [s for s in styles.STYLES if s != "default"]
STATUSES = [  # every state, a hold, both banner kinds, head mode
    None,
    Status(None, ()),
    Status(None, (("Left", "Victory"), ("Right", "None")), owner="Right"),
    Status("Right", (("Right", "Pointing_Up"),), owner="Right"),
    Status("Right", (("Right", "Pointing_Up"),), pressed=True, owner="Right"),
    Status(None, (("Right", "None"),), owner="Right", holding=("Right", "Close"), progress=0.6),
    Status(None, (), paused=True),
    Status(None, (), paused=True, quitting=True, progress=0.5),
    Status(None, (("Left", "Open_Palm"), ("Right", "Open_Palm")), scrolling="Right", owner="Right"),
    Status(None, (("Right", "None"),), head=True, owner="Right"),
]


def render(style, status) -> bytes:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *styles.SIZES[style])
    styles.draw(cairo.Context(surface), style, status, COLORS)
    return bytes(surface.get_data())


def accent_pixels(data: bytes) -> int:  # ARGB32 little endian: B, G, R, A
    return sum(1 for i in range(0, len(data), 4) if data[i:i + 4] == bytes((255, 153, 0, 255)))


@pytest.mark.parametrize("style", DRAWN)
@pytest.mark.parametrize("status", STATUSES)
def test_every_state_draws_something(style, status):
    assert any(render(style, status))


@pytest.mark.parametrize("style", DRAWN)
def test_the_accent_marks_only_the_hand_that_moves(style):
    assert accent_pixels(render(style, Status("Right", (("Right", "Pointing_Up"),), owner="Right"))) > 0
    assert accent_pixels(render(style, Status(None, (("Left", "Victory"), ("Right", "None")), owner="Right"))) == 0


@pytest.mark.parametrize("style", DRAWN)
def test_every_text_fits_its_box(style):
    for text in TEXTS:
        assert styles.text_width(style, f"L  {text}") <= styles.room(style, banner=False), text
    for text in BANNERS:
        assert styles.text_width(style, text, banner=True) <= styles.room(style, banner=True), text


def test_default_is_not_drawn():
    with pytest.raises(ValueError):
        styles.draw(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)), "default", None, COLORS)


@pytest.mark.parametrize("style", DRAWN)
def test_a_hand_can_say_point_to_start_beside_the_other_moving(style):
    assert any(render(style, Status("Right", (), owner="Right")))  # the driver lingers after the hands leave
