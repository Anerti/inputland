import time

from evdev import AbsInfo, UInput, ecodes

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
            ecodes.EV_KEY: [ecodes.BTN_LEFT],
        }
        try:
            self._device = UInput(capabilities, name=name)
        except PermissionError as e:
            raise RuntimeError("no write access to /dev/uinput; see README 'Permissions'") from e

    def move_to(self, u: float, v: float) -> None:
        """Move to screen position (u, v), each 0..1."""
        self._device.write(ecodes.EV_ABS, ecodes.ABS_X, round(u * ABS_MAX))
        self._device.write(ecodes.EV_ABS, ecodes.ABS_Y, round(v * ABS_MAX))
        self._device.syn()

    def click(self) -> None:
        self._device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
        self._device.syn()
        time.sleep(0.03)  # libinput's button debouncing can drop a release closer than ~25 ms to the press
        self._device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)
        self._device.syn()

    def close(self) -> None:
        self._device.close()

    def __enter__(self) -> "VirtualPointer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
