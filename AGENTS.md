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
- `hud.py` is imported lazily in `cli.py` because it loads GTK and `libgtk4-layer-shell.so`; keep it out of other modules' imports. What the HUD says (`describe`) lives in `app.py` so `--preview` shows it too.
- Devices (`Camera`, `HandTracker`, `VirtualPointer`) are context managers; tests replace them with fakes via `monkeypatch.setattr(app, ...)`, so keep `app.py` referencing them as module-level names.

Where new code goes: new gestures in `gestures.py`, new outputs (clicks, keys, `hyprctl`) next to `pointer.py`, tunables as `Settings` fields in `config.py` (validated in `__post_init__`) with a CLI flag in `cli.py`.

## Gotchas (do not "fix" these)

- **`sys.modules.setdefault("sounddevice", None)` in `tracking.py`** must run before `import mediapipe`. Otherwise PipeWire's JACK client sets `RLIMIT_RTTIME` to 0 and the kernel SIGKILLs the process. Guarded by `tests/test_tracking_import.py`.
- **Handedness is swapped** (`OTHER_SIDE`): frames are mirrored, so MediaPipe reports the opposite hand. `Hand.side` is the user's real hand. When MediaPipe names both hands the same, `detect` relabels them by x position.
- **Cursor anchor is `INDEX_MCP`** (base of the index finger), not the fingertip: steadier, and stays put while pinching.
- **Filters reset when the driving hand changes**, so the cursor jumps instead of gliding between hands.
- **A pinch by the driver holds the left button**: down when it closes, up when it opens, so a quick pinch clicks and a held one drags. A hand lost for a few frames keeps the button while the cursor stays engaged, but one in view that stops pinching lets go even in a pose MediaPipe does not name (else a quick double pinch is one long press); a pinching hand never counts as 🤟 (its loose pinky would close the window mid-drag); a switch to the other hand releases it before the cursor moves. `VirtualPointer.release` keeps at least 30 ms after the press because libinput's button debouncing drops closer ones, and `close` releases a held button.
- **A pinching driver keeps control** even though MediaPipe no longer calls it `Pointing_Up`. The last driver can also take control back by pinching (a slow pinch passes through unrecognized poses), until no hand is in view.
- **✌️ by the last driver is a right click**, once per ✌️, and only after that hand pointed: a stray ✌️ does nothing.
- **Two open palms scroll**, joystick style: the last driver's hand, moved up/down past a dead zone from where the palms opened, sets the scroll speed. `VirtualPointer.scroll` sends `REL_WHEEL_HI_RES` for smooth scrolling and a `REL_WHEEL` click per 120 hi-res units for clients that only read that.
- **Two open palms spread apart / together zoom** (Ctrl+wheel, Ctrl held until the palms close or a click / key is sent, so it never turns into Ctrl+click), on the log ratio of their horizontal gap to where they opened. Axis lock: whichever of scroll and zoom leaves its dead zone first owns the gesture until the palms close.
- **One open palm swiped sideways switches workspace** (Hyprland only), by the last driver and with no other hand in view, so two palms opening to zoom never swipe. Counted in frames, not seconds; a cooldown keeps the hand swinging back from undoing it. Swipe left = next workspace, like the touchpad.
- **An open palm plus a pinch by the other hand is a slider**: the pinching hand's travel from where it grabbed, in `slider_step`s, taps the volume (up/down) or brightness (sideways) media keys; whichever axis steps first owns it until the pinch opens, and a step back needs a full step from the last one sent (raw landmarks jitter across a step edge). Until that side is seen with the pinch open, even after the palm goes or a dropout, the pinch never presses (it wins over the click) and is never a pausing fist (a curled pinch can read as `Closed_Fist`). It freezes the cursor and is never two palms (an OK-sign pinch can read as `Open_Palm`). A pinch already holding the button stays a drag.
- **A fist pauses, an open palm resumes** (either hand): while paused `run` drops every detected hand, so a held button, Ctrl and the cursor wind down as if the hands left the view. Debounced per side, so a palm or fist the other hand already holds does not hide this one's; a fist within `palms_cooldown_frames` of two open palms does not pause, since a closing hand passes through poses MediaPipe does not name. Both fists held `quit_frames` end `run`; that check reads the raw detections, since the first fist already paused, and the HUD shows `Quit...` over `Paused` while it builds up.
- **Head pointing**: an index tip held on the forehead (`head_touch_frames`) toggles it; it must leave the forehead to toggle back. The nose tip's offset from where head mode started, over `head_range`, maps around the screen center, with its own filters; the hand keeps driver, pinch and gestures but stops moving the cursor. In hand mode the face is looked for only every `FACE_EVERY` frames (the touch is held for many), reusing the last one in between; in head mode every frame.
- **`--preview` disables the HUD**: OpenCV's window segfaults next to GTK.
- **Model URLs are pinned** (`float16/1`), not `latest`, so the gesture set cannot change underneath. Downloads must match `MODEL_SHA256` / `FACE_MODEL_SHA256` (a captive-portal page must not get cached), then go to a `.part` file and rename atomically; bump both together. The cached file is re-hashed on every start, so a bump reaches existing installs.
- **HUD clicks pass through** via an empty input region; segment width is fixed (`NAME_CHARS`) so the overlay never resizes, and the owner underline is an inset `box-shadow`, not a border, for the same reason.
- **HUD highlight color** is the theme's `active_border_color`, else `accent` (every Omarchy theme has `accent`, few the former), with black or white text picked by luminance: the theme's own background on its accent drops under 4.5:1 on several themes. Without Omarchy it uses the GTK theme's `@theme_*` colors (not libadwaita's `@accent_bg_color`, unset in plain GTK). The owner underline uses the text color instead: some accents fall under 3:1 on the HUD background.
- **`HandTracker` runs on the GPU delegate**, falling back to the CPU: on a throttled CPU (battery, power-saver) inference takes 30–60 ms, over the 33 ms frame budget, and the cursor stutters.
- **`HandTracker.detect` forces strictly increasing timestamps**: MediaPipe VIDEO mode rejects repeats.

## Errors

Raise `RuntimeError`/`ValueError`/`OSError` with an actionable message (what to install, which README section); `cli.main` logs it, shows it as a desktop notification when there is no terminal to read the log, and exits 1. Don't catch broader in library code.

## Tests

- `tests/test_core.py`: pure logic (region, filter, debounce, hand picking).
- `tests/test_app.py`: drives `run` end to end with fake devices and a scripted list of hands per frame.
- Add a test for any new gesture rule, filter change or loop behavior. Hardware behavior (camera, uinput, HUD) is checked manually with `--preview` / a real run.

## Commits

One-line subject, no body.
