import time

from evdev import AbsInfo, UInput, UInputError, ecodes

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
            # Without a button, libinput does not classify the device as a pointer and ignores it.
            ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT],
        }
        try:
            self._device = UInput(capabilities, name=name)
        # evdev checks access itself and raises UInputError (not PermissionError) for a missing group or module.
        except (PermissionError, UInputError) as e:
            raise RuntimeError(f"cannot use /dev/uinput ({e}); see README 'Permissions'") from e
        self._pressed_at: float | None = None

    def move_to(self, u: float, v: float) -> None:
        """Move to screen position (u, v), each 0..1."""
        self._device.write(ecodes.EV_ABS, ecodes.ABS_X, round(u * ABS_MAX))
        self._device.write(ecodes.EV_ABS, ecodes.ABS_Y, round(v * ABS_MAX))
        self._device.syn()

    def press(self) -> None:
        self._button(ecodes.BTN_LEFT, 1)
        self._pressed_at = time.monotonic()

    def release(self) -> None:
        if self._pressed_at is None:
            return
        # libinput's button debouncing can drop a release closer than ~25 ms to the press
        time.sleep(max(0.0, self._pressed_at + 0.03 - time.monotonic()))
        self._button(ecodes.BTN_LEFT, 0)
        self._pressed_at = None

    def right_click(self) -> None:
        self._button(ecodes.BTN_RIGHT, 1)
        time.sleep(0.03)  # same libinput debouncing as `release`
        self._button(ecodes.BTN_RIGHT, 0)

    def _button(self, button: int, value: int) -> None:
        self._device.write(ecodes.EV_KEY, button, value)
        self._device.syn()

    def close(self) -> None:
        self.release()  # never leave the button stuck down
        self._device.close()

    def __enter__(self) -> "VirtualPointer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
