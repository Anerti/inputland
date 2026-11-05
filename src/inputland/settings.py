"""Settings window (GTK4): every CLI flag with its current value, in three tabs (Look, Feel, Camera).

`ask` only shows the window and returns the edited values; saving and starting is the caller's job.
"""

import argparse
import dataclasses
import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cairo
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from inputland import cli, hud, styles
from inputland.app import Status
from inputland.config import Settings

log = logging.getLogger(__name__)

TABS = {"Look": ("HUD",), "Feel": ("Cursor", "Scroll and zoom", "Gestures"), "Camera": ("Camera",)}

GROUPS = {  # dest -> heading, in the window's order
    "hud": "HUD",
    "hud_corner": "HUD",
    "hud_style": "HUD",
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
    "camera": "Camera",
    "region": "Camera",
    "preview": "Camera",
    "verbose": "Camera",
}


@dataclass(frozen=True)
class Field:
    title: str
    hint: str
    ends: tuple[str, str] = ("", "")  # a slider's words at its low and high end
    span: tuple[float, float] = (0, 1)  # a slider's range (inside what Settings accepts), widened to fit any value


FIELDS = {
    "hud": Field("Show the HUD", "the overlay that shows what each hand does"),
    "hud_corner": Field("Corner", "where the HUD sits on the screen"),
    "hud_style": Field("Style", "its colors always follow the theme"),
    "min_cutoff": Field("Smoothing", "how much the cursor is steadied while the hand is still", ("Steady", "Snappy"),
                        (0.05, 5)),
    "beta": Field("Fast moves", "how quickly the cursor catches up when the hand moves fast", ("Smooth", "Quick"),
                  (0, 50)),
    "pinch_ratio": Field("Pinch", "how close thumb and index come to count as a pinch (click)", ("Tight", "Loose"),
                         (0.1, 0.9)),
    "scroll_speed": Field("Scroll speed", "two open palms moved up or down", ("Slow", "Fast"), (5, 300)),
    "scroll_dead_zone": Field("Scroll start", "how far the palms move before scrolling starts",
                              ("Right away", "Bigger move"), (0, 0.2)),
    "zoom_speed": Field("Zoom speed", "two open palms spread apart or together", ("Slow", "Fast"), (1, 50)),
    "zoom_dead_zone": Field("Zoom start", "how far the palms spread before zooming starts",
                            ("Right away", "Bigger spread"), (0, 0.5)),
    "swipe_distance": Field("Workspace swipe", "how far one open palm swipes sideways", ("Short", "Long"),
                            (0.05, 0.6)),
    "slider_step": Field("Volume and brightness", "travel of the pinching hand per step, the other palm open",
                         ("Fine steps", "Big steps"), (0.003, 0.06)),
    "head_range": Field("Head pointing", "how far the nose moves to cross the screen (index on the forehead)",
                        ("Small moves", "Big moves"), (0.03, 0.5)),
    "camera": Field("Device", "the webcam that watches your hands"),
    "region": Field("Tracking area", "your hand moving inside this box covers the whole screen: drag it or its "
                                     "corners; a smaller box needs less arm travel"),
    "preview": Field("Calibrate with the camera view", "shows the camera view instead of the HUD, this run only"),
    "verbose": Field("Debug logging", "more detail in the log"),
}

INLINE = {"hud", "hud_corner", "camera", "preview", "verbose"}  # input to the right of the text, not below it

PREVIEW_STATUS = Status("Left", (("Left", "Pointing_Up"), ("Right", "None")), owner="Left")

MIN_REGION = 0.1  # smallest tracking-area side, fraction of the frame

LOGO = Path(__file__).resolve().parents[2] / "docs/logo.svg"  # the repo's, like the launcher entry's icon

CSS = """
window.inputland-settings { background: @bg; color: @fg; }
.inputland-settings label.title { font-weight: 800; font-size: 18px; }
.inputland-settings .dim { color: alpha(@fg, 0.55); font-size: 12px; }
.inputland-settings .section { color: @accent; font-size: 11px; font-weight: bold; letter-spacing: 1px;
  margin: 16px 2px 6px; }
.inputland-settings .card { background: mix(@bg, @fg, 0.045); border: 1px solid mix(@bg, @fg, 0.09);
  border-radius: 12px; padding: 2px 14px; }
.inputland-settings .card > separator { background: mix(@bg, @fg, 0.08); min-height: 1px; }
.inputland-settings .item { padding: 10px 0; }
.inputland-settings stackswitcher { box-shadow: inset 0 -1px mix(@bg, @fg, 0.1); }
.inputland-settings stackswitcher button { background: none; border: none; box-shadow: none; border-radius: 0;
  color: alpha(@fg, 0.6); font-weight: 600; padding: 8px 0; }
.inputland-settings stackswitcher button:hover { background: none; color: @fg; box-shadow: inset 0 -2px @accent; }
.inputland-settings stackswitcher button:checked { background: none; color: @fg; box-shadow: inset 0 -3px @accent; }
.inputland-settings button { background: mix(@bg, @fg, 0.08); color: @fg; border: none; box-shadow: none;
  border-radius: 8px; }
.inputland-settings button:hover { background: mix(@bg, @fg, 0.14); }
.inputland-settings button.flat { background: none; color: alpha(@fg, 0.65); }
.inputland-settings button.flat:hover { color: @fg; }
.inputland-settings button.suggested-action { background: @accent; color: @on_accent; font-weight: bold;
  padding: 7px 30px; }
.inputland-settings button.suggested-action:hover { background: mix(@accent, @fg, 0.15); }
.inputland-settings switch { background: mix(@bg, @fg, 0.16); border: none; box-shadow: none; }
.inputland-settings switch:checked { background: @accent; }
.inputland-settings switch slider { background: @fg; border: none; box-shadow: none; }
.inputland-settings switch:checked slider { background: @on_accent; }
.inputland-settings scale trough { background: mix(@bg, @fg, 0.16); border: none; min-height: 6px;
  border-radius: 3px; }
.inputland-settings scale highlight { background: @accent; border: none; border-radius: 3px; margin: 0;
  min-height: 6px; }
.inputland-settings scale slider { background: @fg; border: none; box-shadow: 0 1px 3px alpha(black, 0.4); }
.inputland-settings flowboxchild { padding: 0; background: none; }
.inputland-settings button.style-card { background: @bg; border: 1px solid mix(@bg, @fg, 0.12);
  border-radius: 10px; padding: 14px 12px 10px; }
.inputland-settings button.style-card:hover { background: mix(@bg, @fg, 0.04); }
.inputland-settings button.style-card:checked { border: 2px solid @accent; padding: 13px 11px 9px; }
.inputland-settings .style-name { color: alpha(@fg, 0.6); }  /* not every label: Default's preview has its own */
.inputland-settings button.style-card:checked .style-name { color: @fg; font-weight: bold; }
.inputland-settings .screen { border: 2px solid alpha(@fg, 0.4); border-radius: 6px; padding: 4px; }
.inputland-settings button.corner { min-width: 18px; min-height: 10px; padding: 0; border-radius: 2px;
  background: alpha(@fg, 0.2); }
.inputland-settings button.corner:checked { background: @accent; }
.inputland-settings popover > contents { background: mix(@bg, @fg, 0.07); color: @fg; }
.inputland-settings spinbutton { background: mix(@bg, @fg, 0.07); color: @fg; border: none; box-shadow: none;
  border-radius: 7px; }
.inputland-settings *:focus-visible { outline-color: alpha(@accent, 0.8); }
.inputland-settings .error { color: mix(#e01b24, @fg, 0.3); }
"""

Input = tuple[Gtk.Widget, Callable[[], object], Callable[[object], None]]  # widget, getter, setter
Box4 = tuple[float, float, float, float]  # left, top, right, bottom


def form_fields(parser: argparse.ArgumentParser) -> list[tuple[str, argparse.Action]]:
    """(heading, action) for every flag the window shows, in `GROUPS` order."""
    actions = {a.dest: a for a in parser._actions}
    return [(heading, actions[dest]) for dest, heading in GROUPS.items()]


def field_in_error(message: str) -> str | None:
    """The setting a `Settings` / `Region` error is about: their messages name the field."""
    return next((dest for dest in GROUPS if re.search(rf"\b{dest}\b", message)), None)


def cameras(root: Path = Path("/sys/class/video4linux")) -> dict[int, str]:
    """Capture devices by number (/dev/videoN) and name; a webcam's extra metadata node (index > 0) is left out."""
    found = {}
    for node in root.glob("video*"):
        try:
            if (node / "index").read_text().strip() == "0":  # "HP Camera: HP Ca" (UVC repeats it, cut): keep the first
                found[int(node.name.removeprefix("video"))] = (node / "name").read_text().strip().split(": ")[0]
        except (OSError, ValueError):
            continue
    return dict(sorted(found.items()))


def drag(box: Box4, grab: str, dx: float, dy: float) -> Box4:
    """`box` after dragging `grab` ("move" or a corner like "top-left") by (dx, dy), in fractions of the frame:
    it stays inside the frame and at least `MIN_REGION` wide and tall; values to 2 digits, as the window shows them."""
    left, top, right, bottom = box
    if grab == "move":
        dx, dy = min(max(dx, -left), 1 - right), min(max(dy, -top), 1 - bottom)
        left, top, right, bottom = left + dx, top + dy, right + dx, bottom + dy
    if "left" in grab:
        left = min(max(left + dx, 0), right - MIN_REGION)
    if "right" in grab:
        right = max(min(right + dx, 1), left + MIN_REGION)
    if "top" in grab:
        top = min(max(top + dy, 0), bottom - MIN_REGION)
    if "bottom" in grab:
        bottom = max(min(bottom + dy, 1), top + MIN_REGION)
    return round(left, 2), round(top, 2), round(right, 2), round(bottom, 2)


def _step(default: float) -> tuple[float, int]:
    """Slider step (a tenth of the default's order of magnitude) and the digits it needs."""
    step = 10 ** math.floor(math.log10(default or 1)) / 10
    return step, max(0, -math.floor(math.log10(step) + 1e-9))


def slider_input(action: argparse.Action, value: float, field: Field) -> Input:
    step, digits = _step(action.default)
    lower, upper = min(field.span[0], value), max(field.span[1], value)
    scale = Gtk.Scale(adjustment=Gtk.Adjustment(value=value, lower=lower, upper=upper, step_increment=step,
                                                page_increment=step * 10), draw_value=False, hexpand=True)
    scale.set_round_digits(digits)
    shown = Gtk.Label(css_classes=["dim"])
    scale.connect("value-changed", lambda s: shown.set_label(f"{s.get_value():.{digits}f}"))
    shown.set_label(f"{value:.{digits}f}")
    ends = Gtk.Box()
    ends.append(Gtk.Label(label=field.ends[0], xalign=0, hexpand=True, css_classes=["dim"]))
    ends.append(shown)
    ends.append(Gtk.Label(label=field.ends[1], xalign=1, hexpand=True, css_classes=["dim"]))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.append(scale)
    box.append(ends)
    return box, lambda: round(scale.get_value(), digits), scale.set_value


def switch_input(value: object) -> Input:
    widget = Gtk.Switch(active=bool(value), valign=Gtk.Align.CENTER)
    return widget, widget.get_active, lambda v: widget.set_active(bool(v))


def camera_input(value: int) -> Input:
    found = cameras()
    found.setdefault(value, f"Camera {value}")
    numbers = sorted(found)
    names = [f"{found[n]} (video{n})" if found[n] != f"Camera {n}" else found[n] for n in numbers]
    widget = Gtk.DropDown(model=Gtk.StringList.new(names), selected=numbers.index(value), valign=Gtk.Align.CENTER)

    def set_(v: object) -> None:
        if v in numbers:
            widget.set_selected(numbers.index(v))

    return widget, lambda: numbers[widget.get_selected()], set_


def corner_input(action: argparse.Action, value: str) -> Input:
    """A small screen with a button in each corner."""
    screen = Gtk.Grid(column_spacing=38, row_spacing=18, css_classes=["screen"], valign=Gtk.Align.CENTER)
    buttons: dict[str, Gtk.ToggleButton] = {}
    for corner in action.choices:
        button = Gtk.ToggleButton(css_classes=["corner"], tooltip_text=corner.replace("-", " ").capitalize())
        if buttons:
            button.set_group(next(iter(buttons.values())))
        screen.attach(button, int("right" in corner), int("bottom" in corner), 1, 1)
        buttons[corner] = button
    buttons[value].set_active(True)
    return screen, lambda: next(c for c, b in buttons.items() if b.get_active()), lambda v: buttons[v].set_active(True)


def style_input(action: argparse.Action, value: str, views: list[hud.HudView]) -> Input:
    """One card per style, each showing the HUD drawn in it, two per line when the window is wide enough; `views` gets
    the previews, to redraw on a theme change."""
    cards = Gtk.FlowBox(homogeneous=True, max_children_per_line=2, column_spacing=10, row_spacing=10,
                        selection_mode=Gtk.SelectionMode.NONE)
    buttons: dict[str, Gtk.ToggleButton] = {}
    for style in action.choices:
        view = hud.HudView(style)
        view.render(PREVIEW_STATUS)
        view.widget.set_halign(Gtk.Align.CENTER)
        views.append(view)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER)
        content.append(view.widget)
        content.append(Gtk.Label(label=styles.NAMES[style], css_classes=["style-name"]))
        button = Gtk.ToggleButton(child=content, css_classes=["style-card"])
        if buttons:
            button.set_group(next(iter(buttons.values())))
        cards.append(button)
        buttons[style] = button
    buttons[value].set_active(True)
    return cards, lambda: next(s for s, b in buttons.items() if b.get_active()), lambda v: buttons[v].set_active(True)


def region_input(value: object) -> Input:
    """A box over a frame standing for the camera view, dragged as a whole or by a corner; a slider per side below
    it, also for the keyboard. `None` means the default region, as in the parser."""
    default = dataclasses.astuple(Settings().region)
    sliders = [Gtk.Scale(adjustment=Gtk.Adjustment(lower=0, upper=1, step_increment=0.01, page_increment=0.1),
                         draw_value=False, hexpand=True) for _ in range(4)]
    area = Gtk.DrawingArea(content_height=200, hexpand=True)
    grabbed: list[object] = []  # [grab, box at the start of the drag]
    setting: list[bool] = []  # non-empty while set_ moves the sliders: the box it sets is whole, no side to keep apart

    def box() -> Box4:
        return tuple(round(s.get_value(), 2) for s in sliders)

    def set_(v: object) -> None:
        setting.append(True)
        for slider, x in zip(sliders, v or default):
            slider.set_value(x)
        setting.clear()

    def keep_apart(i: int) -> None:
        """A side's slider stops `MIN_REGION` before the opposite side (left/right, top/bottom)."""
        value, other = sliders[i].get_value(), sliders[(i + 2) % 4].get_value()
        if not setting and (other - value if i < 2 else value - other) < MIN_REGION - 1e-9:
            sliders[i].set_value(round(other - MIN_REGION if i < 2 else other + MIN_REGION, 2))

    def frame(w: int, h: int) -> tuple[float, float, float, float]:
        fh = min(h, w * 3 / 4)  # a 4:3 camera frame, centered
        return (w - fh * 4 / 3) / 2, (h - fh) / 2, fh * 4 / 3, fh

    def draw(_: Gtk.DrawingArea, ctx: cairo.Context, w: int, h: int) -> None:
        fx, fy, fw, fh = frame(w, h)
        fg, accent = hud.theme_color(area, "fg"), hud.theme_color(area, "accent")
        ctx.rectangle(fx, fy, fw, fh)
        ctx.set_source_rgba(*fg, 0.06)
        ctx.fill_preserve()
        ctx.set_source_rgba(*fg, 0.18)
        ctx.set_line_width(1)
        ctx.stroke()
        ctx.set_source_rgba(*fg, 0.4)
        ctx.select_font_face("sans-serif")
        ctx.set_font_size(11)
        ctx.move_to(fx + 8, fy + fh - 8)
        ctx.show_text("camera view (as in the calibration view)")
        left, top, right, bottom = box()
        x0, y0, x1, y1 = fx + left * fw, fy + top * fh, fx + right * fw, fy + bottom * fh
        ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
        ctx.set_source_rgba(*accent, 0.14)
        ctx.fill_preserve()
        ctx.set_source_rgba(*accent, 1)
        ctx.set_line_width(2)
        ctx.stroke()
        ctx.set_source_rgba(*fg, 1)
        for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            ctx.rectangle(cx - 4.5, cy - 4.5, 9, 9)
        ctx.fill()

    def grab_at(x: float, y: float) -> str | None:
        fx, fy, fw, fh = frame(area.get_width(), area.get_height())
        left, top, right, bottom = box()
        for name, cx, cy in (("top-left", left, top), ("top-right", right, top),
                             ("bottom-left", left, bottom), ("bottom-right", right, bottom)):
            if abs(x - (fx + cx * fw)) <= 12 and abs(y - (fy + cy * fh)) <= 12:
                return name
        u, v = (x - fx) / fw, (y - fy) / fh
        return "move" if left <= u <= right and top <= v <= bottom else None

    def begin(_: Gtk.GestureDrag, x: float, y: float) -> None:
        grabbed[:] = [grab_at(x, y), box()]

    def update(_: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if grabbed and grabbed[0]:
            _, _, fw, fh = frame(area.get_width(), area.get_height())
            set_(drag(grabbed[1], grabbed[0], dx / fw, dy / fh))

    def hover(_: Gtk.EventControllerMotion, x: float, y: float) -> None:
        grab = grab_at(x, y)
        cursors = {"move": "move", "top-left": "nwse-resize", "bottom-right": "nwse-resize"}
        area.set_cursor_from_name(cursors.get(grab, "nesw-resize") if grab else None)

    area.set_draw_func(draw)
    gesture = Gtk.GestureDrag()
    gesture.connect("drag-begin", begin)
    gesture.connect("drag-update", update)
    area.add_controller(gesture)
    motion = Gtk.EventControllerMotion()
    motion.connect("motion", hover)
    area.add_controller(motion)
    exact = Gtk.Grid(column_spacing=12, row_spacing=2)
    for i, (name, slider) in enumerate(zip(("Left", "Top", "Right", "Bottom"), sliders)):
        shown = Gtk.Label(width_chars=4, xalign=1, css_classes=["dim"])

        def changed(s: Gtk.Scale, i: int = i, shown: Gtk.Label = shown) -> None:
            keep_apart(i)
            shown.set_label(f"{s.get_value():.2f}")
            area.queue_draw()

        slider.set_round_digits(2)
        slider.connect("value-changed", changed)
        row = (i % 2) * 2 + i // 2  # left, right, top, bottom
        exact.attach(Gtk.Label(label=name, xalign=0, width_chars=6, css_classes=["dim"]), 0, row, 1, 1)
        exact.attach(slider, 1, row, 1, 1)
        exact.attach(shown, 2, row, 1, 1)
    set_(value)
    for slider in sliders:
        slider.emit("value-changed")  # the labels, also for a side already at 0
    widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    widget.append(area)
    widget.append(exact)

    def get() -> list[float] | None:
        got = list(box())
        return None if got == list(default) else got

    return widget, get, set_


def logo() -> Gtk.Widget:
    """The app logo, drawn from its SVG so it is sharp at any scale; the name in text without librsvg or the file."""
    try:
        gi.require_version("Rsvg", "2.0")
        from gi.repository import Rsvg

        handle = Rsvg.Handle.new_from_file(str(LOGO))
    except (ValueError, ImportError, GLib.Error):
        return Gtk.Label(label="inputland", xalign=0, hexpand=True, css_classes=["title"])
    area = Gtk.DrawingArea(content_width=138, content_height=50, hexpand=True, halign=Gtk.Align.START)

    def draw(_: Gtk.DrawingArea, ctx: cairo.Context, w: int, h: int) -> None:
        viewport = Rsvg.Rectangle()
        viewport.width, viewport.height = w, h
        handle.render_document(ctx, viewport)

    area.set_draw_func(draw)
    area.update_property([Gtk.AccessibleProperty.LABEL], ["inputland"])
    return area


class _Window:
    """The settings window: `values` fill the inputs; `result` is the edited values after a valid Start."""

    def __init__(self, app: Gtk.Application, parser: argparse.ArgumentParser, values: dict[str, object]) -> None:
        self._app = app
        self._parser = parser
        self._values = values
        self.result: dict[str, object] | None = None
        self._inputs: dict[str, Input] = {}
        self._errors: dict[str, Gtk.Label] = {}
        self._views: list[hud.HudView] = []

        self._theme = hud.install_theme(self._redraw)
        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        actions = dict((action.dest, action) for _, action in form_fields(parser))
        for tab, headings in TABS.items():
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=18, margin_end=18, margin_bottom=18)
            for heading in headings:
                page.append(Gtk.Label(label=heading.upper(), xalign=0, css_classes=["section"]))
                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"])
                for dest in (d for d, h in GROUPS.items() if h == heading):
                    if card.get_first_child():
                        card.append(Gtk.Separator())
                    card.append(self._row(dest, actions[dest]))
                page.append(card)
            scroll = Gtk.ScrolledWindow(child=page, hscrollbar_policy=Gtk.PolicyType.NEVER)
            self._stack.add_titled(scroll, tab, tab)

        header = Gtk.Box(margin_top=16, margin_start=18, margin_end=18, margin_bottom=12)
        header.append(logo())
        header.append(Gtk.Label(label="settings", css_classes=["dim"]))
        tabs = Gtk.StackSwitcher(stack=self._stack, margin_start=18, margin_end=18)

        self._error = Gtk.Label(wrap=True, xalign=0, css_classes=["error"], hexpand=True)  # empty keeps Start right
        reset = Gtk.Button(label="Reset to defaults", css_classes=["flat"])
        reset.connect("clicked", lambda _: self._reset())
        start = Gtk.Button(label="Start", css_classes=["suggested-action"])
        start.connect("clicked", lambda _: self._start())
        bar = Gtk.Box(spacing=12, margin_top=10, margin_bottom=12, margin_start=18, margin_end=18)
        bar.append(reset)
        bar.append(self._error)
        bar.append(start)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for part in (header, tabs, self._stack, Gtk.Separator(), bar):
            content.append(part)

        self.window = Gtk.ApplicationWindow(application=app, title="inputland", default_width=470, default_height=720)
        self.window.add_css_class("inputland-settings")
        self.window.set_child(content)
        self.window.set_default_widget(start)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.window.add_controller(keys)

    def _row(self, dest: str, action: argparse.Action) -> Gtk.Widget:
        field = FIELDS[dest]
        widget, get, set_ = self._input(dest, action, self._initial(dest, self._values[dest]))
        self._inputs[dest] = (widget, get, set_)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        text.append(Gtk.Label(label=field.title, xalign=0))
        text.append(Gtk.Label(label=field.hint, xalign=0, wrap=True, css_classes=["dim"]))
        error = Gtk.Label(xalign=0, wrap=True, css_classes=["error"], visible=False)  # under the text: in view
        text.append(error)  # when Start scrolls to the row
        self._errors[dest] = error
        if dest in INLINE:
            row = Gtk.Box(spacing=12, css_classes=["item"])
        else:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["item"])
        row.append(text)
        row.append(widget)
        return row

    def _input(self, dest: str, action: argparse.Action, value: object) -> Input:
        if dest == "region":
            return region_input(value)
        if dest == "hud_style":
            return style_input(action, value, self._views)
        if dest == "hud_corner":
            return corner_input(action, value)
        if dest == "camera":
            return camera_input(value)
        if isinstance(action, argparse.BooleanOptionalAction):
            return switch_input(value)
        return slider_input(action, value, FIELDS[dest])

    @staticmethod
    def _initial(dest: str, value: object) -> object:
        """What an input shows when the window opens or resets: preview always starts off (it applies to one run)."""
        return False if dest == "preview" else value

    def _redraw(self) -> None:
        for view in self._views:
            view.redraw()
        self._inputs["region"][0].get_first_child().queue_draw()

    def _clear_errors(self) -> None:
        self._error.set_label("")
        for label in self._errors.values():
            label.set_visible(False)

    def _reset(self) -> None:
        for dest, (_, _, set_) in self._inputs.items():
            set_(self._initial(dest, self._parser.get_default(dest)))
        self._clear_errors()

    def _start(self) -> None:
        edited = {**self._values, **{dest: get() for dest, (_, get, _) in self._inputs.items()}}
        self._clear_errors()
        try:
            cli.settings_from(argparse.Namespace(**edited))
        except ValueError as e:
            dest = field_in_error(str(e))
            if dest is None:
                self._error.set_label(str(e))
                return
            error = self._errors[dest]
            error.set_label(str(e))
            error.set_visible(True)
            self._stack.set_visible_child_name(next(t for t, hs in TABS.items() if GROUPS[dest] in hs))
            error.get_ancestor(Gtk.Viewport).scroll_to(error.get_parent().get_parent(), None)  # its row
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
