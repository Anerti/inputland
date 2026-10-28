import logging
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# MediaPipe imports sounddevice for audio tasks we don't use. Its PortAudio init loads
# PipeWire's JACK client, which sets RLIMIT_RTTIME to 0, and the kernel then SIGKILLs us.
# MediaPipe treats the module as optional.
sys.modules.setdefault("sounddevice", None)

import cv2  # noqa: E402
import mediapipe as mp  # noqa: E402
import numpy as np  # noqa: E402
from mediapipe.tasks.python import BaseOptions, vision  # noqa: E402

log = logging.getLogger(__name__)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"  # pinned: "latest" could change gestures under us
)

# MediaPipe hand landmarks
WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5  # base of the index finger
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_TIP = 12
OTHER_SIDE = {"Left": "Right", "Right": "Left"}


@dataclass(frozen=True)
class Hand:
    side: str  # the user's real hand: "Left" / "Right"
    gesture: str  # MediaPipe canned gesture, e.g. "Pointing_Up"; "None" if unrecognized
    score: float
    landmarks: tuple[tuple[float, float], ...]  # 21 (x, y) points, normalized 0..1


def ensure_model() -> Path:
    """Return the cached gesture model, downloading it on first run."""
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "inputland"
    path = cache / "gesture_recognizer.task"
    if not path.exists():
        log.info("downloading gesture model to %s", path)
        cache.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, tmp)
        tmp.rename(path)  # atomic: an interrupted download never looks like a valid model
    return path


class HandTracker:
    def __init__(self, model: Path, max_hands: int = 2) -> None:
        # GPU first: on a throttled CPU (battery, power-saver) inference overruns the 33 ms frame budget
        # and the cursor stutters; the GPU stays at ~16 ms.
        for delegate in (BaseOptions.Delegate.GPU, BaseOptions.Delegate.CPU):
            options = vision.GestureRecognizerOptions(
                base_options=BaseOptions(model_asset_path=str(model), delegate=delegate),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=max_hands,
            )
            try:
                self._recognizer = vision.GestureRecognizer.create_from_options(options)
                break
            except RuntimeError as e:
                if delegate == BaseOptions.Delegate.CPU:
                    raise
                log.warning("GPU unavailable, tracking on the CPU (the cursor may stutter): %s", str(e)[:200])
        self._last_ts = -1

    def detect(self, frame_bgr: np.ndarray, timestamp_ms: int) -> list[Hand]:
        # VIDEO mode rejects timestamps that do not strictly increase.
        self._last_ts = max(timestamp_ms, self._last_ts + 1)
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = self._recognizer.recognize_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), self._last_ts
        )
        hands = []
        for handedness, gestures, landmarks in zip(result.handedness, result.gestures, result.hand_landmarks):
            top = gestures[0] if gestures else None
            hands.append(
                Hand(
                    # On our mirrored frames MediaPipe names the opposite hand (verified on real hands).
                    side=OTHER_SIDE[handedness[0].category_name],
                    gesture=top.category_name if top else "None",
                    score=top.score if top else 0.0,
                    landmarks=tuple((lm.x, lm.y) for lm in landmarks),
                )
            )
        return hands

    def close(self) -> None:
        self._recognizer.close()

    def __enter__(self) -> "HandTracker":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
