from collections.abc import Iterator

import cv2
import numpy as np


class Camera:
    """Webcam that yields mirrored RGB frames, so moving the hand right moves the cursor right."""

    def __init__(self, index: int, width: int, height: int) -> None:
        self._cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open camera {index} (/dev/video{index})")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def frames(self) -> Iterator[np.ndarray]:
        while True:
            ok, frame = self._cap.read()
            if not ok:
                raise RuntimeError("camera stopped delivering frames")
            yield cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)

    def close(self) -> None:
        self._cap.release()

    def __enter__(self) -> "Camera":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
