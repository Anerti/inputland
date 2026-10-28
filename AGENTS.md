# AGENTS.md

Hand-gesture mouse control: webcam → MediaPipe → uinput pointer, with a GTK4 layer-shell HUD. Linux only (Wayland/Hyprland, X11, TTY). See `README.md` for setup, flags and the module table.

## Commands

```sh
uv sync                     # Python 3.13, deps from uv.lock
uv run pytest               # all tests; no camera, GPU, display or /dev/uinput needed
uv run inputland --preview  # manual check with the real camera (q/Esc quits)
uv run inputland -v         # debug logging
```

Use `uv` for everything; do not call `pip` or edit `uv.lock` by hand. No linter/formatter is configured: match the existing style (type hints everywhere, `X | None`, frozen dataclasses, lines up to ~120 chars).

## Architecture

One loop in `app.run`, one direction: `Camera` → `HandTracker.detect` → `pick_pointer_hand` + `Debounce` → `Region.normalize` → `OneEuroFilter` → `VirtualPointer.move_to`.

- `run` reports a `Status` through `on_status` only when it changes, and stops when the `stop` event is set.
- With the HUD, GTK owns the main thread and `run` executes in the `vision` worker thread. Touch GTK only via `GLib.idle_add` (see `Hud._publish`).
- `hud.py` is imported lazily in `cli.py` because it loads GTK and `libgtk4-layer-shell.so`; keep it out of other modules' imports.
- Devices (`Camera`, `HandTracker`, `VirtualPointer`) are context managers; tests replace them with fakes via `monkeypatch.setattr(app, ...)`, so keep `app.py` referencing them as module-level names.

Where new code goes: new gestures in `gestures.py`, new outputs (clicks, keys, `hyprctl`) next to `pointer.py`, tunables as `Settings` fields in `config.py` (validated in `__post_init__`) with a CLI flag in `cli.py`.

## Gotchas (do not "fix" these)

- **`sys.modules.setdefault("sounddevice", None)` in `tracking.py`** must run before `import mediapipe`. Otherwise PipeWire's JACK client sets `RLIMIT_RTTIME` to 0 and the kernel SIGKILLs the process. Guarded by `tests/test_tracking_import.py`.
- **Handedness is swapped** (`OTHER_SIDE`): frames are mirrored, so MediaPipe reports the opposite hand. `Hand.side` is the user's real hand.
- **Cursor anchor is `INDEX_MCP`** (base of the index finger), not the fingertip: steadier, and stays put while pinching.
- **Filters reset when the driving hand changes**, so the cursor jumps instead of gliding between hands.
- **A pinch by the driver is a left click**, once per pinch. `VirtualPointer.click` sleeps 30 ms between press and release because libinput's button debouncing drops closer ones.
- **A pinching driver keeps control** even though MediaPipe no longer calls it `Pointing_Up`. The last driver can also take control back by pinching (a slow pinch passes through unrecognized poses), until no hand is in view.
- **`--preview` disables the HUD**: OpenCV's window segfaults next to GTK.
- **Model URL is pinned** (`float16/1`), not `latest`, so the gesture set cannot change underneath. Downloads go to a `.part` file then rename atomically.
- **HUD clicks pass through** via an empty input region; segment width is fixed (`NAME_CHARS`) so the overlay never resizes.
- **`HandTracker` runs on the GPU delegate**, falling back to the CPU: on a throttled CPU (battery, power-saver) inference takes 30–60 ms, over the 33 ms frame budget, and the cursor stutters.
- **`HandTracker.detect` forces strictly increasing timestamps**: MediaPipe VIDEO mode rejects repeats.

## Errors

Raise `RuntimeError`/`ValueError`/`OSError` with an actionable message (what to install, which README section); `cli.main` logs it and exits 1. Don't catch broader in library code.

## Tests

- `tests/test_core.py`: pure logic (region, filter, debounce, hand picking).
- `tests/test_app.py`: drives `run` end to end with fake devices and a scripted list of hands per frame.
- Add a test for any new gesture rule, filter change or loop behavior. Hardware behavior (camera, uinput, HUD) is checked manually with `--preview` / a real run.

## Commits

One-line subject, no body.
