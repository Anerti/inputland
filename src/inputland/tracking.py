import hashlib
import http.client
import logging
import os
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Self

sys.modules.setdefault("sounddevice", None)

import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

log = logging.getLogger(__name__)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
)
MODEL_SHA256 = "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482"
FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
FACE_MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"

WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_TIP = 12
RING_PIP = 14
RING_TIP = 16
PINKY_PIP = 18
PINKY_TIP = 20
OTHER_SIDE = {"Left": "Right", "Right": "Left"}
NOSE_TIP = 1

Face = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Hand:
    side: str
    gesture: str
    score: float
    landmarks: tuple[tuple[float, float], ...]


def ensure_model(url: str, sha256: str) -> Path:
    """Return the cached model at `url`, downloading it on first run or when `sha256` no longer matches it."""
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "inputland"
    path = cache / url.rsplit("/", 1)[1]
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
        return path
    log.info("downloading model to %s", path)
    cache.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
    except http.client.HTTPException as e:
        raise RuntimeError(f"model download from {url} failed ({e}); check the network and retry") from e
    if hashlib.sha256(data).hexdigest() != sha256:
        raise RuntimeError(f"model download from {url} failed its checksum; check the network and retry")
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.rename(path)
    return path


class _VideoTask:
    """A MediaPipe task in VIDEO mode, made by `create` from the base options."""

    def __init__(self, model: Path, create: Callable[[BaseOptions], Any]) -> None:
        for delegate in (BaseOptions.Delegate.GPU, BaseOptions.Delegate.CPU):
            try:
                self._task = create(BaseOptions(model_asset_path=str(model), delegate=delegate))
                break
            except RuntimeError as e:
                if delegate == BaseOptions.Delegate.CPU:
                    raise
                log.warning(
                    "GPU unavailable, tracking on the CPU (the cursor may stutter): %s", str(e)[:200],
                    extra={"notify": isinstance(self, HandTracker)},  # the face tracker falls back too: notify once
                )
        self._last_ts = -1

    def _image(self, frame_rgb: np.ndarray, timestamp_ms: int) -> tuple[mp.Image, int]:
        self._last_ts = max(timestamp_ms, self._last_ts + 1)
        return mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb), self._last_ts

    def close(self) -> None:
        self._task.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class HandTracker(_VideoTask):
    def __init__(self, model: Path) -> None:
        super().__init__(model, lambda base: vision.GestureRecognizer.create_from_options(
            vision.GestureRecognizerOptions(
                base_options=base, running_mode=vision.RunningMode.VIDEO, num_hands=2,
            )
        ))

    def detect(self, frame_rgb: np.ndarray, timestamp_ms: int) -> list[Hand]:
        result = self._task.recognize_for_video(*self._image(frame_rgb, timestamp_ms))
        hands = []
        for handedness, gestures, landmarks in zip(result.handedness, result.gestures, result.hand_landmarks):
            top = gestures[0] if gestures else None
            hands.append(
                Hand(
                    side=OTHER_SIDE[handedness[0].category_name],
                    gesture=top.category_name if top else "None",
                    score=top.score if top else 0.0,
                    landmarks=tuple((lm.x, lm.y) for lm in landmarks),
                )
            )
        if len(hands) == 2 and hands[0].side == hands[1].side:
            hands.sort(key=lambda h: h.landmarks[INDEX_MCP][0])
            hands = [replace(h, side=side) for h, side in zip(hands, ("Left", "Right"))]
        return hands


class FaceTracker(_VideoTask):
    def __init__(self, model: Path) -> None:
        super().__init__(model, lambda base: vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(base_options=base, running_mode=vision.RunningMode.VIDEO, num_faces=1)
        ))

    def detect(self, frame_rgb: np.ndarray, timestamp_ms: int) -> Face | None:
        result = self._task.detect_for_video(*self._image(frame_rgb, timestamp_ms))
        return tuple((lm.x, lm.y) for lm in result.face_landmarks[0]) if result.face_landmarks else None
