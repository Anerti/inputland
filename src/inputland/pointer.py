import logging
import os
import subprocess
import time

from evdev import AbsInfo, UInput, UInputError, ecodes

log = logging.getLogger(__name__)

ABS_MAX = 32767


class VirtualPointer:
    """Kernel-level virtual pointer (uinput), so it works on Wayland, X11 and the TTY.

    Absolute: the compositor maps 0..ABS_MAX onto the whole screen layout.
    Needs write access to /dev/uinput.
    """

    def __init__(self, name: str = "inputland pointer") -> None:
        axis = AbsInfo(value=0, min=0, max=ABS_MAX, fuzz=0, flat=0, resolution=0)
        capabilities = {
            ecodes.EV_ABS: [(ecodes.ABS_X, axis), (ecodes.ABS_Y, axis)],
            ecodes.EV_KEY: [
                ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTSHIFT, ecodes.KEY_INSERT,
                ecodes.KEY_LEFTALT, ecodes.KEY_F4,
            ],
            ecodes.EV_REL: [ecodes.REL_WHEEL, ecodes.REL_WHEEL_HI_RES],
        }
        try:
            self._device = UInput(capabilities, name=name)
        except (PermissionError, UInputError) as e:
            raise RuntimeError(f"cannot use /dev/uinput ({e}); see README 'Permissions'") from e
        self._pressed_at: float | None = None
        self._wheel = 0.0
        self._notch_units = 0
        self._zooming = False

    def move_to(self, u: float, v: float) -> None:
        """Move to screen position (u, v), each 0..1."""
        self._device.write(ecodes.EV_ABS, ecodes.ABS_X, round(u * ABS_MAX))
        self._device.write(ecodes.EV_ABS, ecodes.ABS_Y, round(v * ABS_MAX))
        self._device.syn()

    def press(self) -> None:
        self.stop_zoom()
        self._button(ecodes.BTN_LEFT, 1)
        self._pressed_at = time.monotonic()

    def release(self) -> None:
        if self._pressed_at is None:
            return
        time.sleep(max(0.0, self._pressed_at + 0.03 - time.monotonic()))
        self._button(ecodes.BTN_LEFT, 0)
        self._pressed_at = None

    def right_click(self) -> None:
        self.stop_zoom()
        self._button(ecodes.BTN_RIGHT, 1)
        time.sleep(0.03)
        self._button(ecodes.BTN_RIGHT, 0)

    def copy(self) -> None:
        self._shortcut(ecodes.KEY_LEFTCTRL, ecodes.KEY_INSERT)

    def paste(self) -> None:
        self._shortcut(ecodes.KEY_LEFTSHIFT, ecodes.KEY_INSERT)

    def close_window(self) -> None:
        """Close the focused window: Hyprland's killactive, Alt+F4 elsewhere."""
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            self.stop_zoom()
            _hyprctl("close the window", "hl.dsp.window.close()", "killactive")
        elif os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
            self._shortcut(ecodes.KEY_LEFTALT, ecodes.KEY_F4)
        else:
            log.warning("no window to close outside a graphical session")

    def switch_workspace(self, step: int) -> None:
        """Go to the next (`step` 1) or previous (-1) workspace with windows; Hyprland only."""
        if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            log.warning("switching workspace needs Hyprland")
            return
        self.stop_zoom()
        workspace = f"e{step:+d}"
        _hyprctl("switch workspace", f'hl.dsp.focus({{ workspace = "{workspace}" }})', f"workspace {workspace}")

    def _shortcut(self, modifier: int, key: int) -> None:
        self.stop_zoom()
        for code, value in ((modifier, 1), (key, 1), (key, 0), (modifier, 0)):
            self._button(code, value)

    def scroll(self, notches: float) -> None:
        """Scroll by `notches` wheel clicks, fractions included; positive scrolls up."""
        self._wheel += notches * 120
        hi = int(self._wheel)
        if not hi:
            return
        self._wheel -= hi
        self._device.write(ecodes.EV_REL, ecodes.REL_WHEEL_HI_RES, hi)
        self._notch_units += hi
        if clicks := int(self._notch_units / 120):
            self._device.write(ecodes.EV_REL, ecodes.REL_WHEEL, clicks)
            self._notch_units -= clicks * 120
        self._device.syn()

    def zoom(self, notches: float) -> None:
        """Ctrl+scroll, which most apps take as zoom; positive zooms in. Ctrl stays down until `stop_zoom`."""
        if not self._zooming:
            self._button(ecodes.KEY_LEFTCTRL, 1)
            self._zooming = True
            self._wheel = self._notch_units = 0
        self.scroll(notches)

    def stop_zoom(self) -> None:
        if self._zooming:
            self._button(ecodes.KEY_LEFTCTRL, 0)
            self._zooming = False
            self._wheel = self._notch_units = 0

    def _button(self, button: int, value: int) -> None:
        self._device.write(ecodes.EV_KEY, button, value)
        self._device.syn()

    def close(self) -> None:
        self.release()
        self.stop_zoom()
        self._device.close()

    def __enter__(self) -> "VirtualPointer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _hyprctl(action: str, *dispatchers: str) -> None:
    """Run the first of `dispatchers` Hyprland accepts, logging a warning that it could not `action` otherwise."""
    for dispatcher in dispatchers:
        try:
            done = subprocess.run(["hyprctl", "dispatch", dispatcher], capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("hyprctl could not %s: %s", action, e)
            return
        if done.stdout.strip() == "ok":
            return
    log.warning("hyprctl could not %s: %s", action, (done.stdout + done.stderr).strip())
