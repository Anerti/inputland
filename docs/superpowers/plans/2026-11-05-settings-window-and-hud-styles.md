# Settings Window and HUD Styles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three new HUD styles (Cyberpunk, Sticker, Terminal) drawn in the theme's colors, and a settings window, opened from the app launcher or `--settings`, that saves every flag to `config.toml` and starts inputland.

**Architecture:** A new pure-Cairo module `styles.py` draws the new styles from `app.describe` / `app.banner`; `hud.py` gains a `HudView` widget (CSS labels for Default, a `Gtk.DrawingArea` for the others) that both the HUD and the settings window's preview use. The settings window (`settings.py`, GTK, lazily imported) is built from the argparse parser itself, runs under the HUD's unique application id, and on Start `cli` saves the non-default values and replaces the process with a plain `inputland` run.

**Tech Stack:** Python 3.13, PyGObject (GTK 4.24, Gio), pycairo, argparse, tomllib, pytest. `uv` for everything.

**Spec:** `docs/superpowers/specs/2026-11-05-settings-window-and-hud-styles-design.md`

## Global Constraints

- Colors come only from the theme: the four `@define-color` names `bg`, `fg`, `active`, `on_active` that `hud.theme_css()` defines. No style brings its own palette.
- A style never changes the HUD's size between states (fixed size per style); clicks pass through; `--hud-corner` still applies.
- Styles show exactly `app.describe` / `app.banner` / `Status.progress`; nothing in `app.py` changes.
- `--hud-style` values: `default`, `cyberpunk`, `sticker`, `terminal`; default `default`. Display names: Default, Cyberpunk, Sticker, Terminal.
- GTK modules (`hud.py`, `settings.py`) are imported only lazily from `cli.py` (AGENTS.md).
- Config keys are flags without `--` (`min-cutoff = 0.8`); only values that differ from the built-in defaults are written; `preview` and `settings` are never written.
- Unique application id stays `dev.inputland.Hud` for the HUD and the settings window (launcher toggle).
- Project style (AGENTS.md): type hints, `X | None`, frozen dataclasses, lines up to ~120 chars, errors as `RuntimeError`/`ValueError`/`OSError` with actionable messages. Commits: one-line Conventional Commits subject, no body, no emoji.

## Review Focus

1. Longest texts (`POINT TO START` banner, `HEAD OFF...`, `RIGHT CLICK`, `BRIGHTNESS` in letter-spaced capitals) must fit inside their card in every drawn style → Task 1 test `test_every_text_fits_its_box`.
2. Start with an invalid value (region left ≥ right, slider step 0) shows the message and saves nothing → Task 3 test `test_settings_from_refuses_invalid_values` (the window calls `settings_from`).
3. First save when `~/.config/inputland/` does not exist yet → created → Task 3 test `test_save_config_creates_the_directory_and_replaces_atomically`.
4. A flag added to `cli.py` later must appear in the window → Task 4 test `test_every_flag_has_a_place_in_the_window`.
5. A crash while saving must not leave a truncated `config.toml` → written to `config.toml.part` then `os.replace` → same Task 3 test asserts no `.part` is left and old content is replaced whole.

---

## Part 1: HUD styles

### Task 1: `styles.py` draws the three new styles with Cairo

**Files:**
- Create: `src/inputland/styles.py`
- Test: `tests/test_styles.py`

**Interfaces:**
- Consumes: `app.SIDES`, `app.TEXTS`, `app.Status`, `app.describe(side, status) -> (text, state)`, `app.banner(status) -> (text, state) | None`. States: `driving`, `owner`, `seen`, `absent`, `paused`.
- Produces:
  - `RGB = tuple[float, float, float]` (0..1)
  - `@dataclass(frozen=True) class Colors: bg: RGB; fg: RGB; active: RGB; on_active: RGB`
  - `STYLES = ("default", "cyberpunk", "sticker", "terminal")`; `NAMES = {"default": "Default", "cyberpunk": "Cyberpunk", "sticker": "Sticker", "terminal": "Terminal"}`
  - `SIZES: dict[str, tuple[int, int]]` for the three drawn styles; starting values `cyberpunk (310, 70)`, `sticker (310, 52)`, `terminal (310, 30)` (adjust once if a text does not fit, then fixed).
  - `draw(ctx: cairo.Context, style: str, status: Status | None, colors: Colors) -> None` (drawn styles only)
  - `text_width(style: str, text: str) -> float` and `room(style: str, banner: bool) -> float`: the width a text takes as drawn (style font, letter spacing, case) and the width available for it; `draw` uses both.

Look and states per style are in the spec ("The styles"); proportions come from the approved mockup generators in `/tmp/claude-1000/-home-anerti-Projects-inputland/61e73eff-b01f-4f42-8c67-8ff2258502f1/scratchpad/gen/` (`cyber2.py: tabs`, `retro.py: sticker`, `terminal.py: powerline`, which are SVG of the same shapes). Text case: cyberpunk upper, terminal lower, sticker as `describe` gives it. Banner: one wide element across both hands. Font: Cairo toy API, `"monospace"`, bold where the spec says.

- [ ] **Step 1: Write the failing tests**

```python
cairo = pytest.importorskip("cairo")
COLORS = styles.Colors(bg=(0.1, 0.1, 0.1), fg=(0.9, 0.9, 0.9), active=(0.0, 0.6, 1.0), on_active=(0.0, 0.0, 0.0))
DRAWN = [s for s in styles.STYLES if s != "default"]
STATUSES = [  # every state, a hold, both banners kinds, head mode
    None, Status(None, ()), Status(None, (("Left", "Victory"), ("Right", "None")), owner="Right"),
    Status("Right", (("Right", "Pointing_Up"),), owner="Right"),
    Status("Right", (("Right", "Pointing_Up"),), pressed=True, owner="Right"),
    Status(None, (("Right", "None"),), owner="Right", holding=("Right", "Close"), progress=0.6),
    Status(None, (), paused=True), Status(None, (), paused=True, quitting=True, progress=0.5),
    Status(None, (("Left", "Open_Palm"), ("Right", "Open_Palm")), scrolling="Right", owner="Right"),
    Status(None, (("Right", "None"),), head=True, owner="Right"),
]

def render(style, status) -> bytes:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *styles.SIZES[style])
    styles.draw(cairo.Context(surface), style, status, COLORS)
    return bytes(surface.get_data())

def accent_pixels(data: bytes) -> int:  # ARGB32 little endian: B, G, R, A
    return sum(1 for i in range(0, len(data), 4) if data[i:i + 4] == bytes((255, 153, 0, 255)))

@pytest.mark.parametrize("style", DRAWN)
@pytest.mark.parametrize("status", STATUSES)
def test_every_state_draws_something(style, status):
    assert any(render(style, status))

@pytest.mark.parametrize("style", DRAWN)
def test_the_accent_marks_only_the_hand_that_moves(style):
    assert accent_pixels(render(style, Status("Right", (("Right", "Pointing_Up"),), owner="Right"))) > 0
    assert accent_pixels(render(style, Status(None, (("Left", "Victory"), ("Right", "None")), owner="Right"))) == 0

@pytest.mark.parametrize("style", DRAWN)
def test_every_text_fits_its_box(style):
    for text in TEXTS:
        assert styles.text_width(style, f"L  {text}") <= styles.room(style, banner=False), text
    for text in BANNERS:
        assert styles.text_width(style, text) <= styles.room(style, banner=True), text
```

(`TEXTS`, `BANNERS`, `Status` from `inputland.app`. If a style draws the hand letter outside the text, as Cyberpunk's tab and Terminal's badge do, `text_width` for it measures the state text only: drop the `"L  "` prefix in that style's branch of `text_width`, keep the test as written.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_styles.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'inputland.styles'`

- [ ] **Step 3: Implement `styles.py`** with the interfaces above: one private draw function per style plus a shared helper that lays out the two hand boxes and the banner box inside `SIZES[style]`; `draw` picks `banner(status)` first, else `describe` per side.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_styles.py -v` then `uv run pytest`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/inputland/styles.py tests/test_styles.py
git commit -m "feat: cyberpunk, sticker and terminal hud styles drawn with cairo"
```

### Task 2: `--hud-style` selects the style; `HudView` shows it

**Files:**
- Modify: `src/inputland/hud.py` (`Hud.__init__`, `Hud._build`, `Hud._render`; theme install code moves into `install_theme`)
- Modify: `src/inputland/cli.py` (new flag, pass it to `Hud`)
- Modify: `README.md` (flags table, HUD section), `AGENTS.md` (gotchas)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 `styles.STYLES`, `styles.SIZES`, `styles.draw`, `styles.Colors`.
- Produces (in `hud.py`, all used by Task 4):
  - `APP_ID = "dev.inputland.Hud"`
  - `install_theme(on_change: Callable[[], None]) -> Gio.FileMonitor`: adds the CSS provider (`theme_css() + CSS`) for the display, reloads it when Omarchy switches theme and then calls `on_change`; keep the monitor referenced.
  - `theme_colors(widget: Gtk.Widget) -> styles.Colors`: the four `@define-color`s via `widget.get_style_context().lookup_color(name)`. Verified to resolve names that point at `@theme_*` colors too. Mark it `# shortcut: Gtk.StyleContext.lookup_color is deprecated since GTK 4.10, still in GTK 4; replace when moving to GTK 5`.
  - `class HudView: __init__(self, style: str)`, `widget: Gtk.Widget`, `render(self, status: Status | None) -> None`, `redraw(self) -> None`. Default: today's `Gtk.Stack` of labels and banner, moved as is. Drawn styles: `Gtk.DrawingArea` with `set_content_width/height(*styles.SIZES[style])`, draw func `styles.draw(ctx, style, self._status, theme_colors(area))`; `render` stores the status and `queue_draw()`s.
  - `Hud(corner: str, style: str = "default")`
  - CLI: `--hud-style` with `choices=styles.STYLES`, `default="default"`, help `"look of the overlay; colors always follow the theme"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_cli.py`

```python
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
```

and add `'hud-style = "neon"'` to the parametrize list of `test_bad_config_file_exits_naming_it`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL (`unrecognized arguments` / `Hud()` takes no `style`)

- [ ] **Step 3: Implement** the flag in `cli.py` (`Hud(args.hud_corner, args.hud_style)`) and the `hud.py` interfaces above. `Hud._build` uses `install_theme(view.redraw)` and `HudView(self._style)`; `Hud._render` calls `view.render`.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest`
Expected: all PASS (the existing `test_hud.py` theme tests unchanged)

- [ ] **Step 5: Manual check** (hardware, AGENTS.md "Tests"): `uv run inputland --hud-style cyberpunk`, then `sticker`, `terminal`, `default`, each on a dark and a light Omarchy theme (`omarchy-theme-set`), switching theme while it runs. Expected: shapes as in the spec, colors follow the theme live, the HUD never changes size, clicks pass through.

- [ ] **Step 6: Docs**: README flags table row `| --hud-style | default | Look of the HUD: cyberpunk, sticker, terminal. Colors always follow your theme. |` and one line per style in the HUD section; AGENTS.md gotcha: "HUD styles other than Default are drawn with Cairo (`styles.py`, no GTK) from `describe` / `banner`, colors read from the HUD's `@define-color`s through `hud.theme_colors`; each has a fixed size (`styles.SIZES`)."

- [ ] **Step 7: Commit**

```bash
git add src/inputland/hud.py src/inputland/cli.py tests/test_cli.py README.md AGENTS.md
git commit -m "feat: --hud-style picks the hud look"
```

## Part 2: Settings window

### Task 3: parser, settings and config saving as reusable functions

**Files:**
- Modify: `src/inputland/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `build_parser(config: Path) -> argparse.ArgumentParser`: today's parser, moved out of `main`, plus `--settings` (`store_true`, help `"open the settings window first (what the app launcher does)"`). The `--no-hud` / `--hud` pair becomes one `--hud` with `action=argparse.BooleanOptionalAction, default=True` (dest `hud`; `--no-hud` and a config `no-hud = true` keep working); `main` uses `not args.hud`.
  - `settings_from(args: argparse.Namespace) -> Settings`: the `Settings(...)` construction moved out of `main` (raises `ValueError` like today).
  - `save_config(parser: argparse.ArgumentParser, values: dict[str, object], path: Path) -> None`: `parser` is a fresh `build_parser` (its defaults are the built-in ones); `values` keyed by dest; a dest missing from `values` counts as its default. Writes one line per value that differs from its action's default, skipping dests `help`, `settings`, `preview`. Key: the action's first `--` option string without `--`. Values: `true`; a `False` for a `BooleanOptionalAction` as `no-<key> = true` (`load_config` skips a `false`); strings with `json.dumps`; lists as `[a, b, c, d]`; numbers with `repr`. Creates the directory; writes `<path>.part` then `os.replace`.

- [ ] **Step 1: Write the failing tests**

```python
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

def test_settings_from_refuses_invalid_values(tmp_path):
    args = cli.build_parser(tmp_path / "c.toml").parse_args(["--region", "0.7", "0.2", "0.3", "0.6"])
    with pytest.raises(ValueError, match="invalid region"):
        cli.settings_from(args)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL, `AttributeError: module 'inputland.cli' has no attribute 'build_parser'`

- [ ] **Step 3: Implement** `build_parser`, `settings_from`, `save_config` in `cli.py`; `main` uses the first two (behavior unchanged). Adjust the order in Step 1's first assertion if the parser's action order differs, not the set of lines.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest`
Expected: all PASS, including `test_command_line_undoes_a_true_from_the_config_file` (`no-hud = true` then `--hud`)

- [ ] **Step 5: Commit**

```bash
git add src/inputland/cli.py tests/test_cli.py
git commit -m "refactor: reusable parser, settings and config saving"
```

### Task 4: the settings window

**Files:**
- Create: `src/inputland/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: Task 2 `hud.APP_ID`, `hud.install_theme`, `hud.HudView`; Task 3 `cli.settings_from`; `styles.NAMES`; `app.Status`.
- Produces:
  - `GROUPS: dict[str, str]` dest → heading: `camera, region` → "Camera"; `min_cutoff, beta, pinch_ratio` → "Cursor"; `scroll_speed, scroll_dead_zone, zoom_speed, zoom_dead_zone` → "Scroll and zoom"; `swipe_distance, slider_step, head_range` → "Gestures"; `hud, hud_corner, hud_style, preview, verbose` → "Display".
  - `form_fields(parser: argparse.ArgumentParser) -> list[tuple[str, argparse.Action]]`: (heading, action) for every action except `help` and `settings`, in `GROUPS` order.
  - `ask(parser: argparse.ArgumentParser, values: dict[str, object]) -> dict[str, object] | None`: shows the window filled with `values` (the effective `vars(args)`) and returns the edited values on a valid Start, or `None` when closed or when another instance was running (it was stopped; log `"inputland was already running: stopped it"` like `Hud.run`). `parser` is a fresh `build_parser`, so its defaults are the built-in ones.

Window behavior (spec, Part 1): one scrolling page, a heading per group, per row a label (option string without `--`, dashes to spaces, capitalized), the action's `help` as a hint, and an input: `Gtk.Switch` for `BooleanOptionalAction` (the `hud` switch reads "HUD"), `Gtk.DropDown` for `choices` (`hud_style` shows `styles.NAMES`), four `Gtk.SpinButton`s for `region`, a `Gtk.SpinButton` for numbers (`int`: 0 digits; `float`: 3 digits, step one tenth of the default's order of magnitude). Under the style dropdown, a `HudView` of the chosen style showing `Status("Left", (("Left", "Pointing_Up"), ("Right", "None")), owner="Left")`, rebuilt when the choice changes. `preview` starts off whatever `values` says. Bottom bar: Reset to defaults (inputs ← `parser` defaults, `preview` off) and Start (`cli.settings_from(argparse.Namespace(**edited))`; on `ValueError` show the message in the window and stay; else quit with the values). Esc or ✕ quits returning `None`. `Gtk.Application(application_id=hud.APP_ID)`: a second `activate` presents the window; never activated locally means another instance ran.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Create an empty `src/inputland/settings.py`, then run to verify it fails**

Run: `uv run pytest tests/test_settings.py -v`
Expected: FAIL, `AttributeError: module 'inputland.settings' has no attribute 'form_fields'` (not a skip: GTK is installed here)

- [ ] **Step 3: Implement `settings.py`** per the interfaces and behavior above.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/inputland/settings.py tests/test_settings.py
git commit -m "feat: settings window built from the cli flags"
```

### Task 5: `--settings` saves and starts; the launcher opens it

**Files:**
- Modify: `src/inputland/cli.py` (`main`)
- Create: `src/inputland/__main__.py` (`from inputland.cli import main` / `main()`), so the run can be started as `python -m inputland`
- Modify: `install.sh:109` (`Exec=systemd-run --user --collect "$LAUNCHER" --settings`)
- Modify: `README.md` (Usage: the window, `--settings`; config section: the window writes the file, only non-defaults, comments lost), `AGENTS.md` (gotchas below)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 3 `build_parser`, `save_config`; Task 4 `settings.ask` (imported lazily inside `main`).

`main` with `args.settings` (checked before the `--no-hud` / no-display branches): without a display raise `RuntimeError("the settings window needs a display (Wayland or X11); edit {config} or use the flags instead")`; else `chosen = ask(build_parser(config), vars(args))`; `None` → return; else `save_config(build_parser(config), chosen, config)`, flush `sys.stdout` / `sys.stderr` (buffered output is lost at `exec`, verified), then `os.execv(sys.executable, [sys.executable, "-m", "inputland", *(["--preview"] if chosen["preview"] else [])])`. Replacing the process releases the unique-app D-Bus name, so the new run becomes the running instance (verified with a probe on this machine) and OpenCV's preview never shares a process with GTK.

- [ ] **Step 1: Write the failing tests**

```python
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
    assert window.execs == [[sys.executable, "-m", "inputland", "--preview"]]
    assert config.runs == []

def test_closing_the_window_saves_and_starts_nothing(config, window):
    cli.main()
    assert not config.path.exists() and window.execs == [] and config.runs == []

def test_settings_without_a_display_says_so(config, window, monkeypatch, caplog):
    monkeypatch.delenv("WAYLAND_DISPLAY")
    with pytest.raises(SystemExit):
        cli.main()
    assert "needs a display" in caplog.text and window.execs == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL (the window is never asked; `run` is called)

- [ ] **Step 3: Implement** the `main` branch, `__main__.py`, the `install.sh` line, the docs. AGENTS.md gotchas: "**The settings window** (`settings.py`, launcher entry, `--settings`) is built from the parser; Start saves only non-defaults (never `preview`) and `exec`s `python -m inputland`, which frees the unique-app name and keeps OpenCV out of a GTK process; flush output before `exec`." and in the `hud.py` lazy-import note, that `settings.py` is the other GTK module and may import `hud`.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest`
Expected: all PASS

- [ ] **Step 5: Manual check**: `./install.sh install`, then from the app launcher: the window opens with the saved values; change beta and the style, Start → HUD in the new style, `config.toml` has only the changed keys; launcher again → inputland stops, no window; launcher again with Camera preview on → the calibration window opens, and the next launch opens the settings window with preview off; ✕ → nothing starts, file unchanged; an invalid region → message in the window, nothing saved.

- [ ] **Step 6: Commit**

```bash
git add src/inputland/cli.py src/inputland/__main__.py install.sh tests/test_cli.py README.md AGENTS.md
git commit -m "feat: settings window from the app launcher saves and starts inputland"
```
