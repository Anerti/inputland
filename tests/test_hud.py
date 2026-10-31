import pytest

from inputland.app import TEXTS, Status, describe

try:
    from inputland import hud
except (ImportError, RuntimeError, ValueError):
    hud = None


@pytest.mark.parametrize(
    ("status", "left", "right"),
    [
        (None, "Starting", "Starting"),
        (Status(None, ()), "Point to start", "Point to start"),
        (Status("Right", (("Left", "Thumb_Up"), ("Right", "Pointing_Up"))), "-", "Moving"),
        (Status("Right", (("Left", "Pointing_Up"), ("Right", "None")), pressed=True), "Pointing", "Pinch"),
        (Status("Right", (("Right", "Pointing_Up"),), edge=True), "Not seen", "At edge"),
        (Status(None, (("Right", "Victory"),), action=("Right", "Right click")), "Not seen", "Right click"),
        (Status(None, (("Right", "Thumb_Up"),), action=("Right", "Copy")), "Not seen", "Copy"),
        (Status(None, (("Right", "Thumb_Down"),), action=("Right", "Paste")), "Not seen", "Paste"),
        (Status(None, (("Right", "ILoveYou"),), action=("Right", "Close")), "Not seen", "Close"),
        (Status(None, (("Left", "Open_Palm"), ("Right", "Open_Palm")), scrolling="Right"), "Scrolling", "Scrolling"),
        (Status(None, (("Left", "Open_Palm"), ("Right", "Open_Palm")), zooming="Right"), "Zooming", "Zooming"),
        (Status(None, (("Left", "Open_Palm"), ("Right", "None")), adjusting=("Right", "Volume")), "Volume", "Volume"),
        (Status(None, (), paused=True), "Paused", "Paused"),
        (Status(None, (), paused=True, quitting=True), "Quit...", "Quit..."),
        (Status(None, (), head=True), "Head", "Head"),
        (Status("Right", (("Left", "Pointing_Up"), ("Right", "None")), pressed=True, head=True), "Head", "Pinch"),
        (Status(None, (("Right", "None"),), owner="Right", holding=("Right", "Close")), "Not seen", "Close..."),
        (Status("Right", (("Right", "Pointing_Up"),), owner="Right", holding=("Right", "Head")), "Not seen", "Head..."),
        (
            Status(None, (("Left", "None"), ("Right", "None")), head=True, holding=("Right", "Head off")),
            "Head", "Head off...",
        ),
    ],
)
def test_hud_shows_actions_not_gestures(status, left, right):
    assert describe("Left", status)[0] == left
    assert describe("Right", status)[0] == right
    assert {left, right} <= set(TEXTS)


def test_hud_marks_the_hand_whose_gestures_count_unless_it_drives():
    idle = Status(None, (("Left", "Victory"), ("Right", "None")), owner="Right")
    assert describe("Left", idle) == ("-", "absent")
    assert describe("Right", idle) == ("-", "owner")
    assert describe("Right", Status(None, (("Left", "Victory"),), owner="Right")) == ("Not seen", "owner")
    head = Status("Right", (("Right", "Pointing_Up"),), head=True, owner="Right")
    assert describe("Right", head) == ("Head", "owner")
    assert describe("Right", Status(None, (("Right", "None"),), owner="Right", holding=("Right", "Close"))) == (
        "Close...", "owner",
    )
    assert describe("Right", Status("Right", (("Right", "Pointing_Up"),), owner="Right")) == ("Moving", "driving")


@pytest.mark.skipif(hud is None, reason="needs GTK 4 and gtk4-layer-shell")
@pytest.mark.parametrize(
    ("theme", "active", "text"),
    [
        ('accent = "#7aa2f7"', "#7aa2f7", "#000000"),
        ('accent = "#1e66f5"', "#1e66f5", "#ffffff"),
        ('accent = "#1e66f5"\nactive_border_color = "#d6d3de"', "#d6d3de", "#000000"),
        (None, "#8aa4ff", "#000000"),
    ],
)
def test_hud_highlight_is_the_theme_accent_with_readable_text(tmp_path, monkeypatch, theme, active, text):
    if theme:
        colors = tmp_path / "omarchy/current/theme/colors.toml"
        colors.parent.mkdir(parents=True)
        colors.write_text(theme)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    css = hud.theme_css()
    assert f"@define-color active {active};" in css
    assert f"@define-color on_active {text};" in css
