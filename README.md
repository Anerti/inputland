# inputland

Control the mouse with hand gestures from a webcam. Works on Wayland (Hyprland), X11 and the TTY.

**Current scope:** point with either index finger (☝️) to move the cursor. Any other pose releases it. If both hands point, the hand already moving the cursor keeps it.
While pointing, touch your thumb to your index fingertip (🤏) to left click; open the pinch before the next one. Pinch twice quickly to double click. Hold the pinch and move to drag. Raise your middle finger too (✌️) to right click.
Hold 🤟 or 🤘 (index and pinky out, thumb either way) for about a second, with the hand that was pointing, to close the focused window: `hyprctl dispatch` on Hyprland (`hl.dsp.window.close()`, or `killactive` before its Lua config), Alt+F4 elsewhere, nothing on the TTY.
Thumbs up (👍) copies and thumbs down (👎, held a moment longer) pastes, with the hand that was pointing. They send Ctrl+Insert and Shift+Insert, which most apps take as copy and paste and which, unlike Ctrl+C, do not interrupt a terminal; terminals usually paste the selected text (primary selection) on Shift+Insert.
To scroll, open both palms (🖐️🖐️) and move the hand that was pointing up or down from where it started: the further you move it, the faster it scrolls. Spread the open palms apart to zoom in, bring them together to zoom out (Ctrl+wheel, so most apps zoom around the cursor); the further, the faster. Whichever starts first, scroll or zoom, keeps the gesture until you close either hand to stop.
Swipe one open palm (🖐️) quickly left or right, with the hand that was pointing, to go to the next or previous workspace, like Hyprland's touchpad swipe (Hyprland only).
To change the volume or the screen brightness, hold one palm open (🖐️) and pinch (🤏) with the other hand, as if grabbing a slider, then move the pinching hand: up / down for volume, right / left for brightness, about one step per centimeter. Whichever direction steps first keeps the gesture until you let go of the pinch. It taps the volume and brightness keys, so your desktop's own bindings do the change and show it (Omarchy shows its OSD); a pinch that was already dragging stays a drag.
Make a fist (✊) with either hand to pause: the hands are ignored, so you can gesture freely, until you open a palm (🖐️) to resume.
Hold an index fingertip on your forehead for half a second to steer the cursor with your head instead (your nose tip; the cursor starts at the screen center), and again to go back to your hand. Pinch, right click and the other gestures still work with the hand, which must stay in the camera's view.
A HUD in the top-right corner shows what each hand is doing (`Moving`, `Pinch`, `Right click`, `Copy`, `Paste`, `Close`, `Scrolling`, `Zooming`, `Slider` / `Volume` / `Brightness`, `At edge` when the hand is outside the mapped region, `Paused`, `Head` in head mode), and `Close...`, `Paste...`, `Head...` or `Head off...` while a hold builds up, so you can let go in time. It highlights the hand moving the cursor and, when none does, underlines the one whose gestures count (the last to point), in your Omarchy theme colors. Poses that do nothing show `-`.

## Setup

```sh
sudo pacman -S gtk4-layer-shell   # HUD overlay (Wayland)
uv sync                    # Python 3.13 + MediaPipe, OpenCV, evdev, PyGObject
uv run inputland --preview # first run downloads the gesture and face models (~12 MB) to ~/.cache/inputland
```

### Permissions

The cursor is driven by a kernel virtual device, so your user needs write access to `/dev/uinput`.
Use a group of its own, not `input`: that one can also read every keyboard, so any program you run could log your keys.

```sh
sudo groupadd -f uinput
echo 'KERNEL=="uinput", GROUP="uinput", MODE="0660", OPTIONS+="static_node=uinput"' \
  | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo usermod -aG uinput "$USER"   # then log out and back in
sudo modprobe uinput
```

## Usage

```sh
uv run inputland            # run with the HUD (Ctrl+C to quit)
uv run inputland --preview  # camera view with the HUD's text and pinch ratios; green box = active (q/Esc quits)
uv run inputland --no-hud   # headless, e.g. on X11; without a display (TTY) the HUD is skipped anyway
```

Started without a terminal (e.g. from a keybinding), it shows a fatal error as a desktop notification.

### Calibration

| Flag | Default | Effect |
|---|---|---|
| `--region L T R B` | `0.25 0.2 0.75 0.7` | Part of the camera frame mapped to the screen. Smaller = less hand travel. |
| `--min-cutoff` | `1.0` | Lower = steadier cursor when still, more lag. |
| `--beta` | `10.0` | Higher = less lag on fast moves, more jitter. |
| `--pinch-ratio` | `0.35` | Thumb-index distance, as a fraction of hand size, that counts as a pinch. Raise if pinches are missed, lower if it clicks on its own; `--preview` shows each hand's ratio. |
| `--scroll-speed` | `80` | Wheel clicks per second for each frame height the hand moves past the dead zone. |
| `--scroll-dead-zone` | `0.03` | Hand travel (fraction of frame height) that does not scroll yet. Raise if it scrolls while you hold still. |
| `--zoom-speed` | `10` | Wheel clicks per second for each unit (log ratio) the gap between the palms changes past the dead zone. |
| `--zoom-dead-zone` | `0.1` | Change in the gap between the palms (log ratio, about a fraction: 0.1 is ~10%) that does not zoom yet. Raise if scrolling turns into zooming. |
| `--swipe-distance` | `0.25` | Sideways travel of one open palm (fraction of the frame width), within about a third of a second, that switches workspace. Lower if swipes are missed, raise if a wave switches workspace. |
| `--slider-step` | `0.013` | Travel of the pinching hand (fraction of the frame) per volume or brightness step. Raise if it jumps several steps at once. |
| `--head-range` | `0.12` | In head mode: nose travel (fraction of the frame) that crosses the whole screen; half of it from where head mode started reaches an edge. Lower = smaller head movements, more jitter. |
| `--camera N` | `0` | Use `/dev/videoN`. |
| `--hud-corner` | `top-right` | Screen corner of the HUD: `top-left`, `bottom-right`, `bottom-left`. |

Tune with `--preview`: hold your hand still and lower `--min-cutoff` until the jitter is gone, then move fast and raise `--beta` until the lag is gone.
Flags are not saved; keep your values in a shell alias, e.g. `alias inputland='uv run --project ~/Projects/inputland inputland --region 0.3 0.25 0.7 0.65'`.

With several monitors the region maps onto the whole screen layout, so the same hand movement covers all of them and each monitor gets less precision.

## Architecture

One loop, one direction: **camera → tracking → gesture → mapping/filter → output**.

| Module | Role |
|---|---|
| `camera.py` | OpenCV V4L2 capture, mirrored RGB frames |
| `tracking.py` | MediaPipe `GestureRecognizer` → `Hand` (side, gesture, 21 landmarks), `FaceLandmarker` → face landmarks (head mode); model download |
| `gestures.py` | Pose rules (`is_gesture`, `is_pinching`, `touches_head`, `pick_pointer_hand`) and `Debounce` against single-frame flicker |
| `filters.py` | One Euro filter (jitter vs. lag) |
| `config.py` | `Settings`, `Region` (camera box → screen) |
| `pointer.py` | uinput absolute pointer (evdev), plus the copy/paste, volume and brightness keys and closing the window |
| `app.py` | Main loop wiring the above, what the HUD says (`describe`), calibration preview |
| `hud.py` | GTK4 layer-shell overlay; GTK owns the main thread, the loop runs in a worker thread and sends `Status` updates via `GLib.idle_add` |
| `cli.py` | Argument parsing, logging, exit codes |

New gestures go in `gestures.py`; new outputs (clicks, keys, `hyprctl`) go next to `pointer.py`.

## Tests

```sh
uv run pytest
```
