import argparse
import logging
import sys

from inputland.app import run
from inputland.config import Region, Settings


def main() -> None:
    defaults = Settings()
    parser = argparse.ArgumentParser(description="Control the mouse with hand gestures.")
    parser.add_argument("--camera", type=int, default=defaults.camera, help="camera index (/dev/videoN)")
    parser.add_argument("--preview", action="store_true", help="show the camera view for calibration, replaces the HUD (q/Esc quits)")
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
    parser.add_argument("--no-hud", action="store_true", help="do not show the on-screen overlay")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = Settings(
            camera=args.camera,
            region=Region(*args.region) if args.region else defaults.region,
            min_cutoff=args.min_cutoff,
            beta=args.beta,
            pinch_ratio=args.pinch_ratio,
            preview=args.preview,
        )
        # OpenCV's preview window segfaults next to GTK, and it shows the same info anyway.
        if args.no_hud or args.preview:
            run(settings)
        else:
            from inputland.hud import Hud  # loads GTK; only needed with the HUD

            Hud().run(lambda on_status, stop: run(settings, on_status, stop))
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError) as e:
        logging.error("%s", e)
        sys.exit(1)
