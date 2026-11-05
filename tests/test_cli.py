import logging
import sys
from types import SimpleNamespace

import pytest

from inputland import cli
from inputland.config import Region


@pytest.fixture
def config(tmp_path, monkeypatch):
    """`.path`: the config file `main` reads; `main`'s runs land in `.runs`. No display, so no notification is sent."""
    fake = SimpleNamespace(path=tmp_path / "inputland/config.toml", runs=[])
    fake.path.parent.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for name in ("WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "run", fake.runs.append)
    return fake


def test_config_file_sets_flags_and_the_command_line_wins(config, monkeypatch):
    config.path.write_text(
        "beta = 12.0\nmin_cutoff = 0.5\nregion = [0.3, 0.25, 0.7, 0.65]\npreview = true\nverbose = false\n"
    )
    monkeypatch.setattr(sys, "argv", ["inputland", "--beta", "20"])

    cli.main()

    (settings,) = config.runs
    assert (settings.beta, settings.min_cutoff, settings.region) == (20, 0.5, Region(0.3, 0.25, 0.7, 0.65))
    assert settings.preview


def test_command_line_undoes_a_true_from_the_config_file(config, monkeypatch):
    config.path.write_text("preview = true\nno-hud = true\n")
    monkeypatch.setattr(sys, "argv", ["inputland", "--no-preview", "--hud"])

    cli.main()

    (settings,) = config.runs
    assert not settings.preview


def test_only_log_records_marked_notify_reach_the_desktop(monkeypatch):
    sent = []
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kwargs: sent.append(argv))
    handler = cli.NotifyHandler()  # not through a logger: another test's `main` leaves one on the root logger

    handler.handle(logging.makeLogRecord({"msg": "GPU <unavailable>", "notify": True}))
    handler.handle(logging.makeLogRecord({"msg": "not for the desktop"}))

    assert sent == [["notify-send", "--app-name=inputland", "inputland", "GPU &lt;unavailable&gt;"]]


@pytest.mark.parametrize(
    "text", ['beta = "fast"', "speed = 3", "region = [0.3]", 'hud-corner = "middle"', 'hud-style = "neon"', "beta ="]
)
def test_bad_config_file_exits_naming_it(config, monkeypatch, caplog, text):
    config.path.write_text(text)
    monkeypatch.setattr(sys, "argv", ["inputland"])

    with pytest.raises(SystemExit) as exit:
        cli.main()

    assert exit.value.code == 1
    assert str(config.path) in caplog.text
    assert not config.runs


def test_hud_style_reaches_the_hud(config, monkeypatch):
    made = []
    fake = SimpleNamespace(Hud=lambda corner, style: SimpleNamespace(run=lambda worker: made.append((corner, style))))
    monkeypatch.setitem(sys.modules, "inputland.hud", fake)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True)  # no notification handler
    config.path.write_text('hud-style = "sticker"\n')
    monkeypatch.setattr(sys, "argv", ["inputland", "--hud-corner", "top-left"])

    cli.main()

    assert made == [("top-left", "sticker")]


def test_save_config_writes_only_what_differs_and_reads_back(tmp_path):
    path = tmp_path / "config.toml"
    values = vars(cli.build_parser(path).parse_args([])) | {
        "beta": 12.0, "region": [0.3, 0.25, 0.7, 0.65], "hud": False, "hud_corner": "top-left", "preview": True,
    }
    cli.save_config(cli.build_parser(path), values, path)

    assert path.read_text().splitlines() == [
        "region = [0.3, 0.25, 0.7, 0.65]", "beta = 12.0", "no-hud = true", 'hud-corner = "top-left"',
    ]  # order: the parser's
    parser = cli.build_parser(path)
    cli.load_config(parser, path)
    assert vars(parser.parse_args([])) == values | {"preview": False}


def test_save_config_creates_the_directory_and_replaces_atomically(tmp_path):
    path = tmp_path / "inputland/config.toml"
    cli.save_config(cli.build_parser(path), {"beta": 20.0}, path)
    cli.save_config(cli.build_parser(path), {"beta": 10.0}, path)  # back to the default
    assert path.read_text() == ""
    assert list(path.parent.iterdir()) == [path]


def test_save_config_keeps_a_symlinked_config(tmp_path):
    target = tmp_path / "dotfiles/config.toml"
    target.parent.mkdir()
    target.write_text("")
    link = tmp_path / "config.toml"
    link.symlink_to(target)
    cli.save_config(cli.build_parser(link), {"beta": 12.0}, link)

    assert link.is_symlink()
    assert target.read_text() == "beta = 12.0\n"


def test_settings_from_refuses_invalid_values(tmp_path):
    args = cli.build_parser(tmp_path / "c.toml").parse_args(["--region", "0.7", "0.2", "0.3", "0.6"])
    with pytest.raises(ValueError, match="invalid region"):
        cli.settings_from(args)


@pytest.fixture
def window(config, monkeypatch):
    """`--settings` with a fake window: `.answer` is what it returns; `.execs` the argv of each exec."""
    fake = SimpleNamespace(answer=None, execs=[])
    monkeypatch.setitem(sys.modules, "inputland.settings", SimpleNamespace(ask=lambda parser, values: fake.answer))
    monkeypatch.setattr(cli.os, "execv", lambda path, argv: fake.execs.append(argv))
    monkeypatch.setattr(sys, "argv", ["inputland", "--settings"])
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True)  # no notification handler
    return fake


def test_start_in_the_window_saves_and_restarts_without_the_window(config, window):
    window.answer = vars(cli.build_parser(config.path).parse_args([])) | {"beta": 12.0, "preview": True}
    cli.main()
    assert config.path.read_text() == "beta = 12.0\n"
    assert window.execs == [[sys.executable, "-P", "-m", "inputland", "--preview"]]
    assert config.runs == []


def test_closing_the_window_saves_and_starts_nothing(config, window):
    cli.main()
    assert not config.path.exists() and window.execs == [] and config.runs == []


def test_settings_without_a_display_says_so(config, window, monkeypatch, caplog):
    monkeypatch.delenv("WAYLAND_DISPLAY")
    with pytest.raises(SystemExit):
        cli.main()
    assert "needs a display" in caplog.text and window.execs == []
