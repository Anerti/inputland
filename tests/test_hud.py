import pytest

from inputland.app import Status

try:
    from inputland import hud
except (ImportError, RuntimeError):  # no GTK 4 or gtk4-layer-shell on this machine
    pytest.skip("needs GTK 4 and gtk4-layer-shell", allow_module_level=True)


@pytest.mark.parametrize(
    ("status", "left", "right"),
    [
        (None, "Starting", "Starting"),
        (Status(None, ()), "Point to start", "Point to start"),
        (Status("Right", (("Left", "Thumb_Up"), ("Right", "Pointing_Up"))), "-", "Moving"),
        (Status("Right", (("Left", "Pointing_Up"), ("Right", "None")), pressed=True), "Pointing", "Pinch"),
        (Status("Right", (("Right", "Pointing_Up"),), edge=True), "Not seen", "At edge"),
        (Status(None, (("Right", "Victory"),), right_click="Right"), "Not seen", "Right click"),
        (Status(None, (("Right", "Thumb_Up"),), copied="Right"), "Not seen", "Copy"),
        (Status(None, (("Right", "Thumb_Down"),), pasted="Right"), "Not seen", "Paste"),
        (Status(None, (("Right", "ILoveYou"),), closed="Right"), "Not seen", "Close"),
        (Status(None, (("Left", "Open_Palm"), ("Right", "Open_Palm")), scrolling="Right"), "Scrolling", "Scrolling"),
        (Status(None, (("Left", "Open_Palm"), ("Right", "Open_Palm")), zooming="Right"), "Zooming", "Zooming"),
        (Status(None, (), paused=True), "Paused", "Paused"),
    ],
)
def test_hud_shows_actions_not_gestures(status, left, right):
    assert hud.describe("Left", status)[0] == left
    assert hud.describe("Right", status)[0] == right
    assert all(len(t) <= hud.NAME_CHARS for t in (left, right))
