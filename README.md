# inputland

Control the mouse with hand gestures from a webcam. Works on Wayland (Hyprland), X11 and the TTY.

**Current scope:** point with either index finger (☝️) to move the cursor. Any other pose releases it. If both hands point, the hand already moving the cursor keeps it.
While pointing, touch your thumb to your index fingertip (🤏) to left click; open the pinch before the next one. Pinch twice quickly to double click. Hold the pinch and move to drag. Raise your middle finger too (✌️) to right click.
A HUD in the top-right corner shows the gesture of each hand and highlights the one moving the cursor, in your Omarchy theme colors.

## Setup

```sh
sudo pacman -S gtk4-layer-shell   # HUD overlay (Wayland)
uv sync                    # Python 3.13 + MediaPipe, OpenCV, evdev, PyGObject
uv run inputland --preview # first run downloads the gesture model (~8 MB) to ~/.cache/inputland
```

### Permissions

The cursor is driven by a kernel virtual device, so your user needs write access to `/dev/uinput`:

```sh
echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' \
  | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo usermod -aG input "$USER"   # then log out and back in
sudo modprobe uinput
```

## Usage

```sh
uv run inputland            # run with the HUD (Ctrl+C to quit)
uv run inputland --preview  # camera view instead of the HUD: green box = active, orange = idle (q/Esc quits)
uv run inputland --no-hud   # headless, e.g. on X11 or the TTY
```

### Calibration

| Flag | Default | Effect |
|---|---|---|
| `--region L T R B` | `0.25 0.2 0.75 0.7` | Part of the camera frame mapped to the screen. Smaller = less hand travel. |
| `--min-cutoff` | `1.0` | Lower = steadier cursor when still, more lag. |
| `--beta` | `10.0` | Higher = less lag on fast moves, more jitter. |
| `--pinch-ratio` | `0.35` | Thumb-index distance, as a fraction of hand size, that counts as a pinch. Raise if pinches are missed, lower if it clicks on its own. |
| `--camera N` | `0` | Use `/dev/videoN`. |

Tune with `--preview`: hold your hand still and lower `--min-cutoff` until the jitter is gone, then move fast and raise `--beta` until the lag is gone.

## Architecture

One loop, one direction: **camera → tracking → gesture → mapping/filter → output**.

| Module | Role |
|---|---|
| `camera.py` | OpenCV V4L2 capture, mirrored frames |
| `tracking.py` | MediaPipe `GestureRecognizer` → `Hand` (side, gesture, 21 landmarks); model download |
| `gestures.py` | Pose rules (`is_pointing`, `is_pinching`, `is_victory`, `pick_pointer_hand`) and `Debounce` against single-frame flicker |
| `filters.py` | One Euro filter (jitter vs. lag) |
| `config.py` | `Settings`, `Region` (camera box → screen) |
| `pointer.py` | uinput absolute pointer (evdev) |
| `app.py` | Main loop wiring the above, calibration preview |
| `hud.py` | GTK4 layer-shell overlay; GTK owns the main thread, the loop runs in a worker thread and sends `Status` updates via `GLib.idle_add` |
| `cli.py` | Argument parsing, logging, exit codes |

New gestures go in `gestures.py`; new outputs (clicks, keys, `hyprctl`) go next to `pointer.py`.

## Tests

```sh
uv run pytest
```
