import argparse
import contextlib
import html
import logging
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from inputland.app import run
from inputland.config import Region, Settings
from inputland.styles import STYLES


def main() -> None:
    defaults = Settings()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "inputland/config.toml"
    parser = argparse.ArgumentParser(
        description=f"Control the mouse with hand gestures. Flags can also be set in {config}.",
    )
    parser.add_argument("--camera", type=int, default=defaults.camera, help="camera index (/dev/videoN)")
    parser.add_argument(
        "--preview", action=argparse.BooleanOptionalAction, default=False,
        help="show the camera view for calibration, replaces the HUD (q/Esc quits)",
    )
    parser.add_argument(
        "--region", type=float, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
        help="part of the camera frame (0..1) mapped to the screen",
    )
    parser.add_argument("--min-cutoff", type=float, default=defaults.min_cutoff, help="lower = less jitter, more lag")
    parser.add_argument("--beta", type=float, default=defaults.beta, help="higher = less lag on fast moves")
    parser.add_argument(
        "--pinch-ratio", type=float, default=defaults.pinch_ratio,
        help="thumb-index distance (fraction of hand size) that counts as a pinch",
    )
    parser.add_argument(
        "--scroll-speed", type=float, default=defaults.scroll_speed,
        help="wheel clicks per second per frame height the hand moves while scrolling (two open palms)",
    )
    parser.add_argument(
        "--scroll-dead-zone", type=float, default=defaults.scroll_dead_zone,
        help="hand travel (fraction of frame height) that does not scroll yet",
    )
    parser.add_argument(
        "--zoom-speed", type=float, default=defaults.zoom_speed,
        help="wheel clicks per second per unit of spread (log ratio) while zooming (two open palms apart / together)",
    )
    parser.add_argument(
        "--zoom-dead-zone", type=float, default=defaults.zoom_dead_zone,
        help="change in the gap between the palms (log ratio, ~fraction) that does not zoom yet",
    )
    parser.add_argument(
        "--swipe-distance", type=float, default=defaults.swipe_distance,
        help="sideways travel (fraction of frame width) of one open palm that switches workspace",
    )
    parser.add_argument(
        "--slider-step", type=float, default=defaults.slider_step,
        help="travel (fraction of the frame) of the pinching hand, other palm open, per volume / brightness step",
    )
    parser.add_argument(
        "--head-range", type=float, default=defaults.head_range,
        help="nose travel (fraction of the frame) that crosses the screen in head mode (index finger on the forehead)",
    )
    parser.add_argument("--no-hud", action="store_true", help="do not show the on-screen overlay")
    parser.add_argument(
        "--hud", dest="no_hud", action="store_false", help="show the overlay, even if the config file sets no-hud",
    )
    parser.add_argument(
        "--hud-corner", choices=("top-right", "top-left", "bottom-right", "bottom-left"), default="top-right",
        help="screen corner of the overlay",
    )
    parser.add_argument(
        "--hud-style", choices=STYLES, default="default", help="look of the overlay; colors always follow the theme",
    )
    parser.add_argument("-v", "--verbose", action=argparse.BooleanOptionalAction, default=False, help="debug logging")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    display = os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")
    unseen = display and not (sys.stderr and sys.stderr.isatty())  # from a keybinding or launcher: nobody sees the log
    if unseen:
        logging.getLogger().addHandler(NotifyHandler())
    try:
        load_config(parser, config)
        args = parser.parse_args()
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        settings = Settings(
            camera=args.camera,
            region=Region(*args.region) if args.region else defaults.region,
            min_cutoff=args.min_cutoff,
            beta=args.beta,
            pinch_ratio=args.pinch_ratio,
            scroll_speed=args.scroll_speed,
            scroll_dead_zone=args.scroll_dead_zone,
            zoom_speed=args.zoom_speed,
            zoom_dead_zone=args.zoom_dead_zone,
            swipe_distance=args.swipe_distance,
            slider_step=args.slider_step,
            head_range=args.head_range,
            preview=args.preview,
        )
        if args.no_hud or args.preview:
            run(settings)
        elif not display:
            logging.info("no display (TTY?): running without the HUD")
            run(settings)
        else:
            from inputland.hud import Hud

            Hud(args.hud_corner, args.hud_style).run(lambda on_status, stop: run(settings, on_status, stop))
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError) as e:
        logging.error("%s", e)
        if unseen:
            notify("inputland stopped", str(e))
        sys.exit(1)


def notify(summary: str, body: str) -> None:
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(["notify-send", "--app-name=inputland", summary, html.escape(body)], timeout=2)


class NotifyHandler(logging.Handler):
    """Shows the log records marked `extra={"notify": True}` as desktop notifications."""

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "notify", False):
            notify("inputland", record.getMessage())


def load_config(parser: argparse.ArgumentParser, path: Path) -> None:
    """Make the flags set in `path` the parser's defaults, so the command line still wins; no file is fine.

    Each key is a flag without the leading `--` (`min-cutoff = 0.8`, `region = [...]`, `no-hud = true`). The values go
    through the parser as arguments, so they are checked exactly like the command line.
    """
    try:
        config = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: {e}") from e
    argv = []
    for flag, value in config.items():
        if value is not False:
            values = [] if value is True else value if isinstance(value, list) else [value]
            argv += [f"--{flag.replace('_', '-')}", *map(str, values)]
    parser.exit_on_error = False  # raise instead, so a bad file reaches the notification too
    try:
        parser.set_defaults(**vars(parser.parse_args(argv)))
    except argparse.ArgumentError as e:
        raise ValueError(f"{path}: {e}") from e
    finally:
        parser.exit_on_error = True
