import pytest

from inputland import cli

try:
    from inputland import settings
except (ImportError, RuntimeError, ValueError):  # same as tests/test_hud.py: needs GTK 4
    settings = None

needs_gtk = pytest.mark.skipif(settings is None, reason="needs GTK 4")


@needs_gtk
def test_every_flag_has_a_place_in_the_window(tmp_path):
    parser = cli.build_parser(tmp_path / "c.toml")
    fields = settings.form_fields(parser)
    shown = {action.dest for _, action in fields}
    assert shown == {a.dest for a in parser._actions} - {"help", "settings"} == set(settings.FIELDS)
    assert {heading for heading, _ in fields} == {h for hs in settings.TABS.values() for h in hs}


@needs_gtk
def test_every_slider_starts_at_its_default_inside_what_settings_accepts(tmp_path):
    parser = cli.build_parser(tmp_path / "c.toml")
    for dest, field in settings.FIELDS.items():
        if field.ends != ("", ""):
            low, high = field.span
            assert low <= parser.get_default(dest) <= high, dest
            cli.settings_from(parser.parse_args([f"--{dest.replace('_', '-')}", str(low)]))
            cli.settings_from(parser.parse_args([f"--{dest.replace('_', '-')}", str(high)]))


@needs_gtk
@pytest.mark.parametrize(
    ("message", "dest"),
    [
        ("need 0 < pinch_ratio < 1, got 1.5", "pinch_ratio"),
        ("need min_cutoff > 0 and beta >= 0, got 0 and 1", "min_cutoff"),
        ("invalid region Region(left=0.7, top=0.2, right=0.3, bottom=0.6): need ...", "region"),
        ("something else", None),
    ],
)
def test_an_error_points_at_the_setting_it_names(message, dest):
    assert settings.field_in_error(message) == dest


@needs_gtk
def test_cameras_lists_capture_devices_by_name(tmp_path):
    for n, index, name in ((0, 0, "HP Wide Vision HD Camera: HP Wi"), (1, 1, "HP Wide Vision HD Camera: HP Wi"),
                           (10, 0, "USB Cam")):
        node = tmp_path / f"video{n}"
        node.mkdir()
        (node / "index").write_text(f"{index}\n")
        (node / "name").write_text(f"{name}\n")
    assert settings.cameras(tmp_path) == {0: "HP Wide Vision HD Camera", 10: "USB Cam"}
    assert settings.cameras(tmp_path / "missing") == {}


@needs_gtk
@pytest.mark.parametrize(
    ("grab", "dx", "dy", "box"),
    [
        ("move", 0.1, -0.05, (0.35, 0.15, 0.85, 0.65)),
        ("move", 0.5, 0.5, (0.5, 0.5, 1.0, 1.0)),  # stops at the frame's edge, keeps its size
        ("top-left", -0.5, -0.5, (0.0, 0.0, 0.75, 0.7)),
        ("bottom-right", -0.9, -0.9, (0.25, 0.2, 0.35, 0.3)),  # never smaller than MIN_REGION
        ("top-right", 0.05, 0.1, (0.25, 0.3, 0.8, 0.7)),
    ],
)
def test_dragging_the_tracking_area_keeps_it_inside_the_frame(grab, dx, dy, box):
    assert settings.drag((0.25, 0.2, 0.75, 0.7), grab, dx, dy) == box


@needs_gtk
def test_the_gestures_tab_shows_every_gesture_picture():
    shown = [picture for rows in settings.GESTURES.values() for picture, _, _ in rows]
    assert sorted(shown) == sorted(p.stem for p in (settings.LOGO.parent / "gestures").glob("*.jpg"))
    assert all(settings.picture(name).get_width() for name in shown)  # loading raises on a broken file
