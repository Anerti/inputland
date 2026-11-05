import pytest

from inputland import cli

try:
    from inputland import settings
except (ImportError, RuntimeError, ValueError):  # same as tests/test_hud.py: needs GTK 4 and gtk4-layer-shell
    settings = None


@pytest.mark.skipif(settings is None, reason="needs GTK 4 and gtk4-layer-shell")
def test_every_flag_has_a_place_in_the_window(tmp_path):
    parser = cli.build_parser(tmp_path / "c.toml")
    fields = settings.form_fields(parser)
    shown = {action.dest for _, action in fields}
    assert shown == {a.dest for a in parser._actions} - {"help", "settings"}
    assert all(heading in settings.GROUPS.values() for heading, _ in fields)
