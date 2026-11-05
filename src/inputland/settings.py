"""Settings window (GTK4): every CLI flag with its current value, built from the argparse parser.

`ask` only shows the window and returns the edited values; saving and starting is the caller's job.
"""

import argparse
import dataclasses
import logging
import math
from collections.abc import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from inputland import cli, hud, styles
from inputland.app import Status
from inputland.config import Settings

log = logging.getLogger(__name__)

GROUPS = {
    "camera": "Camera",
    "region": "Camera",
    "min_cutoff": "Cursor",
    "beta": "Cursor",
    "pinch_ratio": "Cursor",
    "scroll_speed": "Scroll and zoom",
    "scroll_dead_zone": "Scroll and zoom",
    "zoom_speed": "Scroll and zoom",
    "zoom_dead_zone": "Scroll and zoom",
    "swipe_distance": "Gestures",
    "slider_step": "Gestures",
    "head_range": "Gestures",
    "hud": "Display",
    "hud_corner": "Display",
    "hud_style": "Display",
    "preview": "Display",
    "verbose": "Display",
}

PREVIEW_STATUS = Status("Left", (("Left", "Pointing_Up"), ("Right", "None")), owner="Left")

MAX_VALUE = 1000  # Settings validation catches nonsense; its message shows in the window

Input = tuple[Gtk.Widget, Callable[[], object], Callable[[object], None]]  # widget, getter, setter


def form_fields(parser: argparse.ArgumentParser) -> list[tuple[str, argparse.Action]]:
    """(heading, action) for every flag the window shows, in `GROUPS` order."""
    actions = {a.dest: a for a in parser._actions}
    return [(heading, actions[dest]) for dest, heading in GROUPS.items()]


def label_for(action: argparse.Action) -> str:
    option = next(o for o in action.option_strings if o.startswith("--"))
    return option[2:].replace("-", " ").capitalize().replace("Hud", "HUD")


def spin(value: float, digits: int, step: float, upper: float = MAX_VALUE) -> Gtk.SpinButton:
    return Gtk.SpinButton(adjustment=Gtk.Adjustment(value=value, lower=0, upper=upper, step_increment=step,
                                                    page_increment=step * 10), digits=digits)


def number_input(action: argparse.Action, value: object) -> Input:
    if action.type is int:
        widget = spin(float(value), 0, 1)
        return widget, widget.get_value_as_int, lambda v: widget.set_value(v)
    default = action.default or 1
    widget = spin(float(value), 3, 10 ** math.floor(math.log10(default)) / 10)
    return widget, lambda: round(widget.get_value(), 3), lambda v: widget.set_value(v)


def region_input(value: object) -> Input:
    spins = [spin(v, 2, 0.01, 1) for v in (value or dataclasses.astuple(Settings().region))]
    box = Gtk.Box(spacing=6)
    for s in spins:
        box.append(s)

    def get() -> list[float] | None:
        got = [round(s.get_value(), 2) for s in spins]
        return None if got == list(dataclasses.astuple(Settings().region)) else got

    def set_(v: object) -> None:
        for s, x in zip(spins, v or dataclasses.astuple(Settings().region)):
            s.set_value(x)

    return box, get, set_


def choice_input(action: argparse.Action, value: object) -> Input:
    choices = list(action.choices)
    names = [styles.NAMES[c] for c in choices] if action.dest == "hud_style" else choices
    widget = Gtk.DropDown(model=Gtk.StringList.new(names), selected=choices.index(value))
    return widget, lambda: choices[widget.get_selected()], lambda v: widget.set_selected(choices.index(v))


def switch_input(value: object) -> Input:
    widget = Gtk.Switch(active=bool(value), valign=Gtk.Align.CENTER)
    return widget, widget.get_active, lambda v: widget.set_active(bool(v))


def make_input(action: argparse.Action, value: object) -> Input:
    if action.dest == "region":
        return region_input(value)
    if isinstance(action, argparse.BooleanOptionalAction):
        return switch_input(value)
    if action.choices:
        return choice_input(action, value)
    return number_input(action, value)


class _Window:
    """The settings window: `values` fill the inputs; `result` is the edited values after a valid Start."""

    def __init__(self, app: Gtk.Application, parser: argparse.ArgumentParser, values: dict[str, object]) -> None:
        self._app = app
        self._parser = parser
        self._values = values
        self.result: dict[str, object] | None = None
        self._inputs: dict[str, Input] = {}

        self._theme = hud.install_theme(lambda: self._view.redraw())
        self._preview = Gtk.Box()

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=12, margin_bottom=12,
                       margin_start=18, margin_end=18)
        group = None
        for heading, action in form_fields(parser):
            if heading != group:
                group = heading
                page.append(Gtk.Label(label=heading, xalign=0, css_classes=["heading"], margin_top=12))
            page.append(self._row(action))
            if action.dest == "hud_style":
                page.append(self._preview)
        self._show_preview()
        self._inputs["hud_style"][0].connect("notify::selected", lambda *_: self._show_preview())

        self._error = Gtk.Label(wrap=True, xalign=0, css_classes=["error"], visible=False, hexpand=True)
        reset = Gtk.Button(label="Reset to defaults")
        reset.connect("clicked", lambda _: self._reset())
        start = Gtk.Button(label="Start", css_classes=["suggested-action"])
        start.connect("clicked", lambda _: self._start())
        bar = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=18, margin_end=18)
        bar.append(reset)
        bar.append(self._error)
        bar.append(start)
        start.set_halign(Gtk.Align.END)

        scroll = Gtk.ScrolledWindow(child=page, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(scroll)
        content.append(bar)

        self.window = Gtk.ApplicationWindow(application=app, title="inputland", default_width=560, default_height=720)
        self.window.set_child(content)
        self.window.set_default_widget(start)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.window.add_controller(keys)

    def _row(self, action: argparse.Action) -> Gtk.Widget:
        widget, get, set_ = make_input(action, self._values[action.dest])
        self._inputs[action.dest] = (widget, get, set_)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        text.append(Gtk.Label(label=label_for(action), xalign=0))
        if action.help:
            text.append(Gtk.Label(label=action.help, xalign=0, wrap=True, css_classes=["dim-label"]))
        row = Gtk.Box(spacing=12)
        row.append(text)
        widget.set_valign(Gtk.Align.CENTER)
        row.append(widget)
        return row

    def _show_preview(self) -> None:
        child = self._preview.get_first_child()
        if child:
            self._preview.remove(child)
        self._view = hud.HudView(self._inputs["hud_style"][1]())
        self._view.render(PREVIEW_STATUS)
        self._view.widget.set_halign(Gtk.Align.START)
        self._preview.append(self._view.widget)

    def _reset(self) -> None:
        for dest, (_, _, set_) in self._inputs.items():
            set_(False if dest == "preview" else self._parser.get_default(dest))
        self._error.set_visible(False)

    def _start(self) -> None:
        edited = {**self._values, **{dest: get() for dest, (_, get, _) in self._inputs.items()}}
        try:
            cli.settings_from(argparse.Namespace(**edited))
        except ValueError as e:
            self._error.set_label(str(e))
            self._error.set_visible(True)
            return
        self.result = edited
        self._app.quit()

    def _on_key(self, _: Gtk.EventControllerKey, keyval: int, *_rest: object) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.window.close()
            return True
        return False


def ask(parser: argparse.ArgumentParser, values: dict[str, object]) -> dict[str, object] | None:
    """Show the settings window filled with `values`; the edited values after a valid Start, else None
    (closed, or another instance was running and has been stopped)."""
    app = Gtk.Application(application_id=hud.APP_ID)
    windows: list[_Window] = []

    def on_activate(app: Gtk.Application) -> None:
        if windows:  # inputland launched again while the window is open
            windows[0].window.present()
            return
        windows.append(_Window(app, parser, values))
        windows[0].window.present()

    app.connect("activate", on_activate)
    code = app.run([])
    if not windows:  # never activated here: a second launch, or GTK could not start
        if code:
            raise RuntimeError(
                "the settings window could not start (see the GLib message above); run inputland without --settings"
            )
        log.info("inputland was already running: stopped it")
        return None
    return windows[0].result
