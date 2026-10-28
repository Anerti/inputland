"""Always-on-top overlay showing what the tracker sees (GTK4 + Wayland layer-shell).

GTK owns the main thread; the vision loop runs in a worker thread and pushes
`Status` updates through `GLib.idle_add`.
"""

import ctypes
import logging
import os
import threading
import tomllib
from collections.abc import Callable
from pathlib import Path

# Must be loaded before GTK so GTK's Wayland calls go through layer-shell.
try:
    ctypes.CDLL("libgtk4-layer-shell.so.0", mode=ctypes.RTLD_GLOBAL)  # the bare .so ships only in -dev packages
except OSError as e:
    raise RuntimeError("gtk4-layer-shell not found: install it (pacman -S gtk4-layer-shell) or use --no-hud") from e

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from inputland.app import Status  # noqa: E402

log = logging.getLogger(__name__)

Worker = Callable[[Callable[[Status], None], threading.Event], None]

SIDES = ("Left", "Right")  # segment order matches the mirrored camera view

# What each segment can say: the action, not MediaPipe's gesture name.
STARTING = "Starting"
IDLE = "Point to start"  # no hand in view
ABSENT = "Not seen"
IGNORED = "-"  # a pose that does nothing
TEXTS = (
    STARTING, IDLE, ABSENT, IGNORED, "Pointing", "Moving", "At edge", "Pinch", "Right click", "Copy", "Paste", "Scrolling",
)
NAME_CHARS = max(len(t) for t in TEXTS)  # fixed width: the strip never resizes

# Used outside Omarchy, or when the theme file is missing a key.
DEFAULT_COLORS = {"background": "#121212", "foreground": "#e6e6e6", "active_border_color": "#8aa4ff"}

CSS = """
.hud {
  background: alpha(@bg, 0.94);
  border: 2px solid alpha(@fg, 0.14);
  padding: 2px;
  font-family: monospace;
  font-size: 13px;
  color: @fg;
}
.segment { padding: 3px 8px; transition: background 150ms ease-out, color 150ms ease-out; }
.segment.absent { color: alpha(@fg, 0.60); }
.segment.driving { background: @active; color: @bg; font-weight: bold; }
"""


def theme_css() -> str:
    """Color definitions from the current Omarchy theme, falling back to neutral defaults."""
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    colors = dict(DEFAULT_COLORS)
    try:
        theme = tomllib.loads((state / "omarchy/current/theme/colors.toml").read_text())
        colors.update({k: v for k, v in theme.items() if k in colors})
    except (OSError, tomllib.TOMLDecodeError) as e:
        log.debug("no Omarchy theme (%s); using default HUD colors", e)
    return (
        f"@define-color bg {colors['background']};\n"
        f"@define-color fg {colors['foreground']};\n"
        f"@define-color active {colors['active_border_color']};\n"
    )


class Hud:
    def __init__(self, corner: str = "top-right") -> None:
        self._corner = corner
        self._app = Gtk.Application(application_id="dev.inputland.Hud", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def run(self, worker: Worker) -> None:
        """Show the HUD and run `worker(publish, stop)` in a background thread.

        Returns when the worker finishes or on Ctrl+C; re-raises the worker's error.
        """
        stop = threading.Event()
        errors: list[BaseException] = []

        def target() -> None:
            try:
                worker(self._publish, stop)
            except BaseException as e:
                errors.append(e)
            finally:
                GLib.idle_add(self._app.quit)

        thread = threading.Thread(target=target, name="vision")

        def on_activate(app: Gtk.Application) -> None:
            self._build(app)
            thread.start()

        self._app.connect("activate", on_activate)
        try:
            self._app.run([])
        finally:
            stop.set()
            if thread.is_alive():
                thread.join()
        if errors:
            raise errors[0]

    def _publish(self, status: Status) -> None:
        GLib.idle_add(self._render, status)  # called from the worker; GTK is not thread-safe

    def _build(self, app: Gtk.Application) -> None:
        css = Gtk.CssProvider()
        css.load_from_string(theme_css() + CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        window = Gtk.ApplicationWindow(application=app)
        LayerShell.init_for_window(window)
        LayerShell.set_namespace(window, "inputland")
        LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
        for edge in (getattr(LayerShell.Edge, e.upper()) for e in self._corner.split("-")):
            LayerShell.set_anchor(window, edge, True)
            LayerShell.set_margin(window, edge, 12)
        # Empty input region: clicks pass through to the windows below.
        window.connect("realize", lambda w: w.get_surface().set_input_region(cairo.Region()))

        hud = Gtk.Box(spacing=2, css_classes=["hud"])
        self._segments: dict[str, Gtk.Label] = {}
        for side in SIDES:
            label = Gtk.Label(xalign=0, width_chars=NAME_CHARS + 3)
            hud.append(label)
            self._segments[side] = label
        self._render(None)  # until the first frame: model download, camera and GPU start-up
        window.set_child(hud)
        window.present()
        if not LayerShell.is_supported():
            log.warning("compositor has no layer-shell support; the HUD is a normal window")

    def _render(self, status: Status | None) -> None:
        for side, label in self._segments.items():
            text, state = describe(side, status)
            label.set_label(f"{side[0]}  {text}")
            label.set_css_classes(["segment", state])


def describe(side: str, status: Status | None) -> tuple[str, str]:
    """What the segment of `side` says, and its CSS state."""
    if status is None:
        return STARTING, "absent"
    if side == status.right_click:
        return "Right click", "driving"
    if side == status.copied:
        return "Copy", "driving"
    if side == status.pasted:
        return "Paste", "driving"
    if status.scrolling:  # both hands make the gesture; highlight the one that scrolls
        return "Scrolling", "driving" if side == status.scrolling else "seen"
    if side == status.driver:
        return "Pinch" if status.pressed else "At edge" if status.edge else "Moving", "driving"
    gesture = dict(status.hands).get(side)
    if gesture is None:
        return ABSENT if status.hands else IDLE, "absent"
    return ("Pointing", "seen") if gesture == "Pointing_Up" else (IGNORED, "absent")
