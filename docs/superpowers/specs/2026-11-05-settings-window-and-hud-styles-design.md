# Settings window and HUD styles

Date: 2026-11-05. Status: approved in conversation, not yet planned.

## Why

inputland is configured with command-line flags or by hand in `~/.config/inputland/config.toml`. Someone who
starts it from the app launcher never sees a terminal, so today they cannot change anything without editing a file.
The owner wants a window that opens from the launcher, shows every setting with its current value, lets the user
override what they want, and starts inputland with one click. While doing that, the HUD should gain a few
selectable looks beyond today's, without ever leaving the system theme's colors.

Success: open inputland from the launcher, change a value and the HUD style, click Start, and inputland runs with
them; next time the window opens with those values.

## Part 1: the settings window

### When it shows

- Opening inputland **from the app launcher entry** shows the window (`install.sh` adds the flag to the entry's
  `Exec`).
- From a terminal, a new flag **`--settings`** shows the same window. Plain `inputland`, the Hyprland keybinding
  and every other start path still start straight away, as today.
- If inputland is **already running with the HUD**, launching it again (launcher or `--settings`) only stops the
  running instance and shows no window: the launcher entry stays a toggle, through the existing unique
  `Gtk.Application` mechanism (`hud.Hud`, see AGENTS.md "A second launch with the HUD stops the running one").
  A running `--no-hud` instance is not reachable this way, as today.
- *Builder's call, suggested:* launching again while the settings window itself is open brings that window to the
  front.

### What it contains (layout "A")

One window, one scrolling page, settings grouped under small headings, each row a label, its one-line hint (the
flag's `help` text) and an input. Bottom bar: **Reset to defaults** on the left, **Start** on the right.

Every flag in `cli.py` appears, with the same meaning and range:

| Group | Settings |
|-------|----------|
| Camera | camera index, region (left, top, right, bottom) |
| Cursor | min cutoff, beta, pinch ratio |
| Scroll and zoom | scroll speed, scroll dead zone, zoom speed, zoom dead zone |
| Gestures | swipe distance, slider step, head range |
| Display | HUD on/off, HUD corner, **HUD style** (Part 2) with a small live preview of the chosen style, camera preview on/off, verbose logging on/off |

The window uses GTK 4 like the HUD and follows the system theme (no custom styling). Grouping and the exact
widget per setting (spin button, switch, dropdown) are the builder's call.

### Values, Start, Reset, closing

- The window opens filled with the **effective values**: built-in defaults, overridden by `config.toml`, overridden
  by any other flags on the same command line.
- **Start** validates by building `Settings` (and `Region`) exactly as `cli.main` does. On a `ValueError` the
  message is shown in the window and nothing is saved or started.
- When valid, Start **saves to `config.toml`**, closes the window and runs inputland with those values (HUD, or
  camera preview if that switch is on).
- The file is written with keys named like the flags without `--` (`min-cutoff = 0.8`, `region = [...]`,
  `no-hud = true`, `hud-style = "sticker"`), so `load_config` reads it back unchanged.
- *Decided (assistant's call):* only values that **differ from the built-in defaults** are written, so a later
  release that changes a default still reaches users who never touched it. The whole file is rewritten:
  comments written in it by hand are lost (accepted).
- **Camera preview applies only to the run this Start launches** (owner's decision): it is never written to
  `config.toml`, and the window always opens with it off. Otherwise every later start, the keybinding included,
  would open the calibration window instead of the HUD, and a preview run cannot be toggled off from the launcher.
  So the run started with preview on gets `--preview` on its command line, and the save step and its tests leave
  `preview` out. A `preview = true` someone wrote in the file by hand keeps working for plain starts, as today.
- **Reset to defaults** puts every input back to the built-in values; nothing is saved until Start.
- **Closing the window** (✕, Esc) saves nothing and starts nothing.

### Constraints

- The window is GTK: like `hud.py`, its module is imported lazily from `cli.py` only.
- OpenCV's preview window segfaults next to GTK (AGENTS.md). When Start is clicked with camera preview on, the
  preview must not open in a process that has loaded GTK. *Suggested:* after saving, replace the process with a
  plain `inputland` run (`os.execv`), which now reads the saved config, plus `--preview` when that switch is on;
  this also gives the HUD path a clean start.
  If the process is replaced, the D-Bus name of the unique application should be released by `exec`, so the new
  process becomes the running instance and the toggle keeps working: **verify this first** in the plan, since the
  launcher toggle depends on it.
- A broken `config.toml` on `--settings` fails as today (named in the error); a plain launch while the window is
  open is the builder's call.
- Errors follow AGENTS.md "Errors": a failure after Start reaches the user as today (log, desktop notification
  without a terminal).

## Part 2: HUD styles

### The rule for every style

- Colors come **only** from the system theme, from the same source as today (`hud.theme_css`): the Omarchy
  theme's background, foreground and highlight (`active_border_color`, else `accent`) with black/white text on it,
  else the GTK theme's colors. A theme switch re-colors the HUD live, as today.
- A style never resizes the HUD between states: fixed size per style (AGENTS.md "HUD clicks pass through").
  The new styles are taller than Default (about 70 px instead of about 25).
- Clicks still pass through, the corner setting still applies.
- Every style shows exactly what the HUD shows today: for each hand the `(text, state)` from `app.describe`, the
  shared message from `app.banner`, and `Status.progress` for holds. States are `driving` (moves the cursor),
  `owner` (its gestures count), `seen`, `absent` (dimmed: out of view or a pose that does nothing), `paused`.
  Nothing in `app.py` changes.

### The styles

Selected with a new flag **`--hud-style`** (`default`, `cyberpunk`, `sticker`, `terminal`; default `default`),
also settable in `config.toml` and in the window's dropdown. Display names: Default, Cyberpunk, Sticker,
Terminal.

**Default**: today's HUD, unchanged.

**Cyberpunk** (mockup "D. Tab panels"): each hand is its own angled card.
- Card: a rectangle with the top-right and bottom-left corners cut at 45°, thin outline; a small tab at the top
  left, slanted on its right edge, reading `HAND.L` / `HAND.R` in tiny letter-spaced capitals.
- Text in bold, letter-spaced capitals (`MOVING`, `READY`, `CLOSE...`).
- A row of 10 slanted (parallelogram) cells along the bottom of the card.
- `driving`: accent outline, faint accent fill, tab filled with the accent (text in the on-accent color), cells
  glowing faintly in the accent.
- `owner`: tab filled with the text color.
- A hold: the cells light up one per tenth of `progress` in the accent.
- `absent`: the whole card dimmed.
- Shared message (`STARTING`, `POINT TO START`, `PAUSED`, `QUIT...`): one wide card across both, its tab reading
  `INPUTLAND`; `QUIT...` fills its cells.

**Sticker** (mockup "J. Sticker", named Sticker at the owner's request): rounded pills like the logo's shape.
- Each hand a pill (fully rounded ends) with a thick outline in the text color and a hard offset shadow (no blur)
  down-right in the text color. Text in bold, as today (`L  Moving`).
- `driving`: pill filled with the accent, text in the on-accent color.
- `owner`: a small filled dot before the text.
- A hold: the pill fills from the left with the accent at partial opacity, clipped to the pill.
- `absent`: outline, shadow and text faded.
- Shared message: one wide pill across both.

**Terminal** (mockup "K. Status bar"): a tmux / vim status line.
- Each hand a segment with arrow-shaped ends (pointing right) and, at its left, a badge with the hand letter, also
  arrow-ended. Text in lowercase (`moving`, `ready`, `close...`).
- `driving`: badge filled with the accent (letter in the on-accent color), segment tinted with the accent, text
  bold.
- `owner`: badge filled with the text color (letter in the background color).
- A hold: the segment fills from the left with the accent at partial opacity.
- `absent`: badge and text faded.
- Shared message: one wide segment across both.

Exact proportions (paddings, cell sizes, opacities), the `seen` and `paused` looks (in the spirit of each style:
`seen` plain, `paused` a light tint like Default's) and where the drawing code lives are the builder's call; the mockups that were approved are
generated by `gen/cyber2.py` (`tabs`), `gen/retro.py` (`sticker`) and `gen/terminal.py` (`powerline`) in this
session's scratchpad, `/tmp/claude-1000/-home-anerti-Projects-inputland/61e73eff-b01f-4f42-8c67-8ff2258502f1/scratchpad/`,
which is temporary: use them for proportions while they exist.

### How it is drawn

*Decided (assistant's call):* these shapes (cut corners, slanted cells, arrow ends, clipped fills) are beyond GTK
CSS, so the three new styles are drawn with Cairo; Default stays the current CSS labels. *Suggested:* keep the
drawing as plain functions of a Cairo context, the style, the per-hand `(text, state)` / banner / progress and the
theme colors, so tests can draw every state onto a `cairo.ImageSurface` without a display, and the settings
window's preview can reuse them. Drawing needs the theme colors as values, not only as CSS `@define-color`s, from
the same source as `theme_css`.

## Non-goals

- No color choices of any kind: no style brings its own palette.
- No new settings beyond today's flags plus `--hud-style` (the frame-count tunables in `Settings` stay code-only).
- No change to gestures, the vision loop, or what the HUD says.
- Not a general config editor: no editing of comments or of unknown keys.

## Anti-goals (failure even if it works)

- A style that is unreadable on the user's theme, light or dark.
- The HUD changing size, flickering or covering clicks.
- The launcher entry no longer toggling inputland off.
- A crash when camera preview is chosen from the window.

## Docs and tests

- README: the window (launcher, `--settings`), `--hud-style` in the flags table, the styles in the HUD section.
  AGENTS.md: new gotchas (lazy GTK import of the window, preview and GTK, styles drawn with Cairo, only
  non-defaults saved).
- Tests (AGENTS.md "Tests"): saving then `load_config` gives the same `Settings` (preview aside), only non-defaults
  are written and `preview` never is;
  invalid values are refused without saving; `--settings` and `--hud-style` parse and validate; every style draws
  every state in `TEXTS` (and the banner, and a hold) without error. Visuals are checked manually on a light and a
  dark theme.

## Order

Two parts, built in this order: **1. HUD styles** (`--hud-style`, the drawing), then **2. the settings window**,
which then includes the style dropdown and preview from the start. *Assistant's call; either order works.*
