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

try:
    ctypes.CDLL("libgtk4-layer-shell.so.0", mode=ctypes.RTLD_GLOBAL)
except OSError as e:
    raise RuntimeError("gtk4-layer-shell not found: install it (pacman -S gtk4-layer-shell) or use --no-hud") from e

import cairo
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk
from gi.repository import Gtk4LayerShell as LayerShell

from inputland.app import SIDES, TEXTS, Status, banner, describe

log = logging.getLogger(__name__)

Worker = Callable[[Callable[[Status], None], threading.Event], None]

NAME_CHARS = max(len(t) for t in TEXTS)

DEFAULT_COLORS = {"background": "#121212", "foreground": "#e6e6e6", "accent": "#8aa4ff"}

# Plain GTK 4 names (not libadwaita's @accent_bg_color); the selected pair already contrasts.
GTK_THEME_CSS = (
    "@define-color bg @theme_bg_color;\n"
    "@define-color fg @theme_fg_color;\n"
    "@define-color active @theme_selected_bg_color;\n"
    "@define-color on_active @theme_selected_fg_color;\n"
)

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
.segment.absent { color: alpha(@fg, 0.7); }
.segment.paused { background: alpha(@fg, 0.12); }
.segment.owner { box-shadow: inset 0 -2px @fg; }
.segment.driving { background: @active; color: @on_active; font-weight: bold; }
"""

# A hold's progress fills its segment from the left: one class per tenth, as GTK CSS has no per-widget values.
CSS += "".join(
    f".segment.fill-{i} {{ background-image: linear-gradient(to right, alpha(@fg, 0.35) {i}0%, transparent {i}0%); }}\n"
    for i in range(1, 11)
)


def omarchy_current() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "omarchy/current"


def watch_theme(on_change: Callable[[], None]) -> Gio.FileMonitor:
    """Call `on_change` when Omarchy switches theme: it swaps a staged copy in for `current/theme`, so the watch is on
    `current`, not on the theme's files. Keep the monitor referenced: it stops once collected."""
    monitor = Gio.File.new_for_path(str(omarchy_current())).monitor_directory(Gio.FileMonitorFlags.NONE, None)
    monitor.connect("changed", lambda *_: on_change())
    return monitor


def theme_css() -> str:
    """Color definitions from the current Omarchy theme, else from the GTK theme (any desktop).

    The highlight is the theme's `active_border_color`, else its `accent` (every theme has one, few the former), with
    black or white text, whichever contrasts more: they tie at luminance 0.179, so either reaches 4.5:1 (WCAG AA).
    """
    colors = dict(DEFAULT_COLORS)
    try:
        theme = tomllib.loads((omarchy_current() / "theme/colors.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        log.debug("no Omarchy theme (%s); using the GTK theme's colors", e)
        return GTK_THEME_CSS
    colors.update({k: v for k, v in theme.items() if k in colors})
    active = theme.get("active_border_color", colors["accent"])
    rgba = Gdk.RGBA()
    rgba.parse(active)
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (rgba.red, rgba.green, rgba.blue))
    return (
        f"@define-color bg {colors['background']};\n"
        f"@define-color fg {colors['foreground']};\n"
        f"@define-color active {active};\n"
        f"@define-color on_active {'#000000' if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.179 else '#ffffff'};\n"
    )


class Hud:
    def __init__(self, corner: str) -> None:
        self._corner = corner
        self._app = Gtk.Application(application_id="dev.inputland.Hud")

    def run(self, worker: Worker) -> None:
        """Show the HUD and run `worker(publish, stop)` in a background thread.

        Returns when the worker finishes, on Ctrl+C or when inputland is launched again (GTK hands a second launch to
        the running instance, so the launcher or a keybinding toggles it); re-raises the worker's error.
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
            if thread.ident is not None:  # started already: this is a second launch
                app.quit()
                return
            self._build(app)
            thread.start()

        self._app.connect("activate", on_activate)
        try:
            code = self._app.run([])
        finally:
            stop.set()
            if thread.is_alive():
                thread.join()
        if thread.ident is None:  # never activated here: a second launch, or GTK could not start
            if code:
                raise RuntimeError("the HUD could not start (see the GLib message above); use --no-hud")
            log.info("inputland was already running: stopped it")
        if errors:
            raise errors[0]

    def _publish(self, status: Status) -> None:
        GLib.idle_add(self._render, status)

    def _build(self, app: Gtk.Application) -> None:
        css = Gtk.CssProvider()
        css.load_from_string(theme_css() + CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._theme = watch_theme(lambda: css.load_from_string(theme_css() + CSS))

        window = Gtk.ApplicationWindow(application=app)
        LayerShell.init_for_window(window)
        LayerShell.set_namespace(window, "inputland")
        LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
        for edge in (getattr(LayerShell.Edge, e.upper()) for e in self._corner.split("-")):
            LayerShell.set_anchor(window, edge, True)
            LayerShell.set_margin(window, edge, 12)
        window.connect("realize", lambda w: w.get_surface().set_input_region(cairo.Region()))

        self._hands = Gtk.Box(spacing=2)
        self._segments: dict[str, Gtk.Label] = {}
        for side in SIDES:
            label = Gtk.Label(xalign=0, width_chars=NAME_CHARS + 3, css_classes=["segment"])  # padding sets width
            self._hands.append(label)
            self._segments[side] = label
        self._banner = Gtk.Label()
        self._stack = Gtk.Stack(css_classes=["hud"])  # as wide as the segments, so the banner never resizes it
        self._stack.add_child(self._hands)
        self._stack.add_child(self._banner)
        self._render(None)
        window.set_child(self._stack)
        window.present()
        if not LayerShell.is_supported():
            log.warning("no layer-shell support in the compositor; the HUD is a normal window", extra={"notify": True})

    def _render(self, status: Status | None) -> None:
        shared = banner(status)
        self._stack.set_visible_child(self._banner if shared else self._hands)
        if shared:
            _show(self._banner, *shared, status)
        else:
            for side, label in self._segments.items():
                text, state = describe(side, status)
                _show(label, f"{side[0]}  {text}", state, status)


def _show(label: Gtk.Label, text: str, state: str, status: Status | None) -> None:
    fill = round(status.progress * 10) if status and text.endswith("...") else 0  # "...": a hold
    label.set_label(text)
    label.set_css_classes(["segment", state, f"fill-{fill}"])
