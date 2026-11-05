"""The drawn HUD styles (Cyberpunk, Sticker, Terminal): plain functions of a Cairo context, no GTK."""

import math
from dataclasses import dataclass

import cairo

from inputland.app import SIDES, Status, banner, describe

RGB = tuple[float, float, float]


@dataclass(frozen=True)
class Colors:
    bg: RGB
    fg: RGB
    active: RGB
    on_active: RGB


STYLES = ("default", "cyberpunk", "sticker", "terminal")
NAMES = {"default": "Default", "cyberpunk": "Cyberpunk", "sticker": "Sticker", "terminal": "Terminal"}
SIZES = {"cyberpunk": (310, 70), "sticker": (310, 52), "terminal": (310, 30)}

HAND_W = 148  # one hand's box; the second starts at SECOND_X, the banner spans both
SECOND_X = 160
BANNER_W = 306
FONT = "monospace"
SIZE = {"cyberpunk": 15, "sticker": 12, "terminal": 12}
SPACING = {"cyberpunk": 2, "sticker": 0, "terminal": 0}
LEFT = {"cyberpunk": 12, "sticker": 26, "terminal": 44}  # from a hand's left edge to its text
LEFT_BANNER = {"cyberpunk": 12, "sticker": 26, "terminal": 12}
RIGHT = {"cyberpunk": 12, "sticker": 12, "terminal": 14}
INK = {"driving": 1.0, "owner": 0.85, "seen": 0.85, "paused": 0.85, "absent": 0.35}

_scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))


def _font(ctx: cairo.Context, style: str, bold: bool, size: float | None = None) -> None:
    ctx.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size or SIZE[style])


def _shown(style: str, text: str) -> str:
    return text.upper() if style == "cyberpunk" else text.lower() if style == "terminal" else text


def _width(ctx: cairo.Context, text: str, spacing: float) -> float:
    return ctx.text_extents(text).x_advance + spacing * len(text)


def text_width(style: str, text: str) -> float:
    """Width `text` takes as `style` draws it (font, letter spacing, case); Cyberpunk and Terminal draw the hand
    letter outside the text, so a leading `L  ` is not counted there."""
    if style in ("cyberpunk", "terminal") and text.startswith(("L  ", "R  ")):
        text = text[3:]
    _font(_scratch, style, bold=True)  # bold is the widest the font gets
    return _width(_scratch, _shown(style, text), SPACING[style])


def room(style: str, banner: bool) -> float:
    """Width available for the text of one hand, or of the banner."""
    return (BANNER_W if banner else HAND_W) - (LEFT_BANNER if banner else LEFT)[style] - RIGHT[style]


def _poly(ctx: cairo.Context, points: list[tuple[float, float]]) -> None:
    ctx.move_to(*points[0])
    for point in points[1:]:
        ctx.line_to(*point)
    ctx.close_path()


def _pill(ctx: cairo.Context, x: float, y: float, w: float, h: float) -> None:
    r = h / 2
    ctx.new_sub_path()
    ctx.arc(x + r, y + r, r, math.pi / 2, 3 * math.pi / 2)
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, math.pi / 2)
    ctx.close_path()


def _text(ctx: cairo.Context, x: float, y: float, text: str, spacing: float = 0) -> None:
    for char in text if spacing else (text,):
        ctx.move_to(x, y)
        ctx.show_text(char)
        x += ctx.text_extents(char).x_advance + spacing


def _rgba(ctx: cairo.Context, color: RGB, alpha: float = 1.0) -> None:
    ctx.set_source_rgba(*color, alpha)


def _cyberpunk(ctx: cairo.Context, x: float, w: float, label: str, text: str, state: str, p: float, c: Colors) -> None:
    ink, ink_c = INK[state], (c.active if state == "driving" else c.fg)
    body = [(x, 12), (x + w - 8, 12), (x + w, 20), (x + w, 66), (x + 8, 66), (x, 58)]
    _font(ctx, "cyberpunk", bold=False, size=8)
    tab_w = _width(ctx, label, 1.5) + 12
    tab = [(x, 2), (x + tab_w, 2), (x + tab_w + 8, 12), (x, 12)]
    _poly(ctx, body)
    _rgba(ctx, c.bg, 0.9)
    ctx.fill()
    if state in ("driving", "paused"):
        _poly(ctx, body)
        _rgba(ctx, c.active if state == "driving" else c.fg, 0.14 if state == "driving" else 0.12)
        ctx.fill()
    _poly(ctx, body)
    _rgba(ctx, ink_c, ink)
    ctx.set_line_width(1.5)
    ctx.stroke()
    solid = state in ("driving", "owner")
    _poly(ctx, tab)
    _rgba(ctx, ink_c, ink)
    if solid:
        ctx.fill_preserve()
    ctx.set_line_width(1)
    ctx.stroke()
    if state == "driving":
        _rgba(ctx, c.on_active)
    else:
        _rgba(ctx, c.bg if state == "owner" else ink_c, 1 if state == "owner" else ink)
    _text(ctx, x + 6, 10, label, 1.5)
    _font(ctx, "cyberpunk", bold=True)
    _rgba(ctx, ink_c, ink)
    _text(ctx, x + 12, 42, _shown("cyberpunk", text), SPACING["cyberpunk"])
    lit = 10 if state == "driving" else round(p * 10)
    step = (w - 26) / 10
    for i in range(10):
        cx = x + 12 + i * step
        _poly(ctx, [(cx, 58), (cx + 3, 51), (cx + step - 1, 51), (cx + step - 4, 58)])
        _rgba(ctx, c.active if i < lit else c.fg, (0.35 if state == "driving" else 1) if i < lit else 0.15)
        ctx.fill()


def _sticker(ctx: cairo.Context, x: float, w: float, label: str, text: str, state: str, p: float, c: Colors) -> None:
    px, py, pw, h = x + 1, 4, w - 5, 38  # the 4 px shadow stays inside the box
    dim = state == "absent"
    _pill(ctx, px + 4, py + 4, pw, h)
    _rgba(ctx, c.fg, 0.2 if dim else 0.9)
    ctx.fill()
    _pill(ctx, px, py, pw, h)
    _rgba(ctx, c.active if state == "driving" else c.bg)
    ctx.fill()
    if state == "paused":
        _pill(ctx, px, py, pw, h)
        _rgba(ctx, c.fg, 0.12)
        ctx.fill()
    if p:
        ctx.save()
        _pill(ctx, px, py, pw, h)
        ctx.clip()
        ctx.rectangle(px, py, pw * p, h)
        _rgba(ctx, c.active, 0.45)
        ctx.fill()
        ctx.restore()
    _pill(ctx, px, py, pw, h)
    _rgba(ctx, c.fg, 0.35 if dim else 1)
    ctx.set_line_width(2.5)
    ctx.stroke()
    if state == "owner":
        ctx.arc(px + 18, py + h / 2, 4, 0, 2 * math.pi)
        _rgba(ctx, c.fg)
        ctx.fill()
    _font(ctx, "sticker", bold=True)
    _rgba(ctx, c.on_active if state == "driving" else c.fg, 0.4 if dim else 1)
    _text(ctx, px + 25, py + 24, f"{label}  {text}" if label else text)


def _terminal(ctx: cairo.Context, x: float, w: float, label: str, text: str, state: str, p: float, c: Colors) -> None:
    y0, y1, ym = 3, 27, 15
    dim = state == "absent"
    start = x + 28 if label else x
    body = [(start, y0), (x + w - 8, y0), (x + w, ym), (x + w - 8, y1), (start, y1)]
    if label:
        body.append((start + 8, ym))
    tint, tint_alpha = {"driving": (c.active, 0.25), "owner": (c.fg, 0.14), "seen": (c.fg, 0.1),
                        "paused": (c.fg, 0.12), "absent": (c.fg, 0.06)}[state]
    _poly(ctx, body)
    _rgba(ctx, c.bg, 0.92)
    ctx.fill()
    _poly(ctx, body)
    _rgba(ctx, tint, tint_alpha)
    ctx.fill()
    if p:
        ctx.save()
        _poly(ctx, body)
        ctx.clip()
        ctx.rectangle(start, y0, (x + w - start) * p, y1 - y0)
        _rgba(ctx, c.active, 0.4)
        ctx.fill()
        ctx.restore()
    if label:
        _poly(ctx, [(x, y0), (x + 28, y0), (x + 36, ym), (x + 28, y1), (x, y1)])
        badge, badge_alpha = {"driving": (c.active, 1), "owner": (c.fg, 0.9), "absent": (c.fg, 0.18)}.get(
            state, (c.fg, 0.45))
        _rgba(ctx, badge, badge_alpha)
        ctx.fill()
        _font(ctx, "terminal", bold=True)
        _rgba(ctx, c.on_active if state == "driving" else c.fg if dim else c.bg, 0.5 if dim else 1)
        _text(ctx, x + 14 - ctx.text_extents(label).x_advance / 2, ym + 4.5, label)
    _font(ctx, "terminal", bold=state == "driving")
    _rgba(ctx, c.fg, 0.45 if dim else 1)
    _text(ctx, x + (LEFT if label else LEFT_BANNER)["terminal"], ym + 4.5, _shown("terminal", text))


_DRAW = {"cyberpunk": _cyberpunk, "sticker": _sticker, "terminal": _terminal}


def draw(ctx: cairo.Context, style: str, status: Status | None, colors: Colors) -> None:
    """Draw the HUD for `status` in a drawn `style` (not "default") onto a surface of SIZES[style]."""
    if style not in _DRAW:
        raise ValueError(f"Not a drawn HUD style: {style!r}.")
    paint = _DRAW[style]
    shared = banner(status)
    if shared:
        text, state = shared
        label = "INPUTLAND" if style == "cyberpunk" else ""
        progress = status.progress if status and status.quitting else 0.0
        paint(ctx, 2, BANNER_W, label, text, state, progress, colors)
        return
    for side, x in zip(SIDES, (2, SECOND_X)):
        text, state = describe(side, status)
        letter = side[0]
        holding = status is not None and status.holding is not None and status.holding[0] == side
        paint(ctx, x, HAND_W, f"HAND.{letter}" if style == "cyberpunk" else letter, text, state,
              status.progress if holding else 0.0, colors)
