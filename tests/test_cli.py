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


@pytest.mark.parametrize("text", ['beta = "fast"', "speed = 3", "region = [0.3]", 'hud-corner = "middle"', "beta ="])
def test_bad_config_file_exits_naming_it(config, monkeypatch, caplog, text):
    config.path.write_text(text)
    monkeypatch.setattr(sys, "argv", ["inputland"])

    with pytest.raises(SystemExit) as exit:
        cli.main()

    assert exit.value.code == 1
    assert str(config.path) in caplog.text
    assert not config.runs
